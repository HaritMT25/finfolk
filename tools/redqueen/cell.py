"""cell.py: one Red Queen assay cell, the procedure shared by the runner and its replay.

execute(cell, d, exe, paths) runs, in the empty directory d:
  1. the prey world X:
       prey_policy "common": common.py builds common.json (+ common.manifest.json) from the
       registered template and prey snapshot with the cell's sampling seed;
       prey_policy "native": prey.json, the prey snapshot itself;
     every input (prey snapshot, donor, template) is first FROZEN: read once, hashed against
     its registered SHA-256, and written as a read-only file in d from those very bytes; the
     engine and the provenance store read only these copies, never an archive path;
  2. the design's two engine calls, and nothing else (design section 2):
       evo_boids --load-checkpoint X --predators-from Y --transplant-count K
                 --transplant-seed S --assay MODE --transplant-out arena.json
       evo_boids --load-checkpoint arena.json --reseed-after-load R --headless STEPS --no-render
                 --log-every L --checkpoint-every C --save-checkpoint end.json --csv run.csv
     Y is pred.json (the frozen predator snapshot), or "random"; the
     predator-free fork is "random" with K = 0. Relative paths only, so the engine's arena
     manifest is the same in a replay;
  3. the checks: a serial-build arena; a live arena (challenge or control) without a predator
     floor; the checkpoint schedule (end.<f0 + m C>.json for every m, end.json the last step's
     state, byte-identical to the periodic one), then score.py at every horizon (the predator-
     free fork refused if a predator, capture, birth or refill shows anywhere). The arena's prey
     settings (its config without the predator keys) are hashed into the bundle, so the runner
     can check that a challenge and its control share them;
  4. the BUNDLE (bundle.json, canonical JSON): the cell row, the binary's and the output tools'
     SHA-256, both engine argument lists, the SHA-256 of every file the cell produced (the
     checkpoints too, which are then deleted: they replay exactly), the common manifest's hash,
     the arena manifest, the score, and the text of run.predators.csv and of run.csv without its
     two timing columns. Everything in it is a function of the cell row, the binary, the tools
     and the source contents: the same row gives the same bytes (tested), and a replay compares
     them. What is not (wall times, host) goes into done.json, outside the bundle.

Age diagnostics (bundle /3, D8 v2 rule 48; the nested score's existing fields and schema stay
unchanged): each score.horizons entry adds age_strata (schema finfolk.redqueen.agestrata/1,
score.age_strata). Ten START-age bins [0,12), [12,24), ..., [108,120] seconds (bin_edges_s; the
last closed), each crossed with rule 46's age feasibility at that horizon: F_i(H) from
common.age_feasible, the engine's binary32 age clock (start age rounded to binary32, then
H additions of binary32(0.016), age death when the age exceeds binary32(maxAge); age_clock names
it). Not the exact-arithmetic start age <= maxAge - H x dt, which rounding contradicts near the
boundary. Every bin, each bin's feasible and infeasible stratum, the two feasibility totals and
the cohort total carry n_start, survivors and survival (null for an empty denominator). Ages come
from arena.json at f0, keyed by the initial prey IDs, never the horizon's ages; max_age_s is
config.maxAge, dt_s score.dt; steps and frame name the horizon. Missing / invalid ages, ages
beyond the fixed bins, totals that do not reconcile with the score's n_start and survivors, and
any age-infeasible survivor refuse scoring. score.age_strata_problems is the contract: execute
checks it against the cell's horizons before the bundle is bound (so before any checkpoint is
deleted), store.completion_problems at completion verification, packing and resume,
store.indexed_age_problems for packed cells (index_problems, verify_all, recover: pack()'s index
stamp bound to the bundle's digest, over a chunk whose bytes still match, or else the packed
bundle), and the
collectors at ingestion: a /3 bundle without a complete summary is refused (a recording omission,
never zero survival). Readers accept old /1 and /2 bundles without age_strata (explicitly
unavailable, never inferred or rewritten) and /3 for either plan version; plan/2 still requires
its sharing record in /2 and /3 bundles.

Exit codes (also the worker's): 0 ok, 2 the engine is not a serial build, 3 an engine call
failed, 4 a score check failed, 5 a source is missing or not its registered content (hashed
from the very bytes parsed), 6 the checkpoint schedule is incomplete, 7 (the worker) the
provenance could not be stored, 9 biological (the prey source has no living prey, or the
predator donor has none), 10 an engine was killed by a signal.
"""
from __future__ import annotations

import csv
import io
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ckpt  # noqa: E402
import common  # noqa: E402
import rqlib  # noqa: E402
import score as score_mod  # noqa: E402

BUNDLE_SCHEMA = "finfolk.redqueen.bundle/1"
BUNDLE_SCHEMA_V2 = "finfolk.redqueen.bundle/2"   # a plan/2 row's (reference ages, roles, global seeds)
BUNDLE_SCHEMA_V3 = "finfolk.redqueen.bundle/3"   # start-age diagnostics, either plan version
SHARING_SCHEMA = "finfolk.redqueen.sharing/1"
OUTPUT_TOOLS = ("rqlib.py", "ckpt.py", "common.py", "score.py", "cell.py")   # what a bundle depends on
TIMING_COLS = ("elapsed_s", "steps_per_sec")   # run.csv columns that depend on the machine, not the run
HERE = os.path.dirname(os.path.abspath(__file__))


class CellFailure(Exception):
    def __init__(self, code, msg, role=None):
        super().__init__(msg)
        self.code = code
        self.role = role          # for a biological failure (9): the source's role, "prey" / "predators"


def sharing_record(cell, arena, arena_manifest, files):
    """(design v4 §3.5) A plan/2 cell's actual sharing: its group keys and seeds, and what the shared
    draws realized: the common checkpoint (the sample and the ages), the transplant's donor draw
    (seed, pool, the donors picked) and the predators' placement in the arena (positions,
    velocities, genomes). Cells of one transplant group (a predator snapshot x replicate) and one K
    must realize the same draw and placement (run.py records it in done.json, store.py checks it at
    packing): the coupled donor selection / placement is validated, not assumed."""
    p = (arena_manifest or {}).get("predators") or {}
    draw = {"source": p.get("source"), "seed": p.get("seed"), "pool": p.get("pool"), "count": p.get("count"),
            "with_replacement": p.get("withReplacement"),
            "picked": [[x.get("sourceIndex"), x.get("sourceId"), x.get("lineageId")] for x in p.get("picked") or []]}
    place = [[r.get("posX"), r.get("posY"), r.get("velX"), r.get("velY"),
              ckpt.genome_sha(r["genes"])[:16] if r.get("genes") is not None else None]
             for r in ckpt.predators(arena)]
    return {"schema": SHARING_SCHEMA, "keys": dict(cell.get("groups") or {}), "seeds": dict(cell.get("seeds") or {}),
            "realized": {"common_sha256": files.get("common.json"),
                         "common_manifest_sha256": files.get("common.manifest.json"),
                         "transplant": draw, "transplant_draw_sha256": rqlib.canonical_sha(draw),
                         "placement_sha256": rqlib.canonical_sha(place),
                         "transplant_realized_sha256": rqlib.canonical_sha([draw, place])}}


def tools_sha256(here=HERE):
    return {f: rqlib.sha256_file(os.path.join(here, f)) for f in OUTPUT_TOOLS}


def normalize_run_csv(text):
    """run.csv without its timing columns (deterministic)."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return ""
    keep = [i for i, c in enumerate(rows[0]) if c not in TIMING_COLS]
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    for r in rows:
        w.writerow([r[i] for i in keep if i < len(r)])
    return out.getvalue()


def commands(cell, x_name):
    """The two engine argument lists (without the binary)."""
    p = cell["predators"]
    if cell["kind"] == "nopred":
        src, k = "random", 0
    elif p.get("source") in ("random", "scripted"):
        src, k = p["source"], int(cell["k"])
    else:
        src, k = "pred.json", int(cell["k"])
    s = cell["seeds"]
    t = ["--load-checkpoint", x_name, "--predators-from", src, "--transplant-count", str(k),
         "--transplant-seed", str(s["transplant"]), "--assay", cell["assay"], "--transplant-out", "arena.json"]
    a = ["--load-checkpoint", "arena.json", "--reseed-after-load", str(s["reseed"]), "--headless", str(cell["steps"]),
         "--no-render", "--log-every", str(cell["log_every"]), "--checkpoint-every", str(cell["checkpoint_every"]),
         "--save-checkpoint", "end.json", "--csv", "run.csv"]
    return t, a


def _engine(exe, args, d, name, procs):
    with open(os.path.join(d, name + ".stdout.log"), "w") as so, open(os.path.join(d, name + ".stderr.log"), "w") as se:
        try:
            p = subprocess.Popen([exe] + args, cwd=d, stdout=so, stderr=se, stdin=subprocess.DEVNULL,
                                 preexec_fn=rqlib.death_signal())
        except (OSError, subprocess.SubprocessError) as e:
            raise CellFailure(3, f"engine ({name}) could not start: {e}")
        procs.append(p)
        _, status, ru = os.wait4(p.pid, 0)
    p.returncode = os.waitstatus_to_exitcode(status)
    procs.remove(p)
    rc = p.returncode
    if rc < 0:
        raise CellFailure(10, f"engine ({name}) killed by signal {-rc}")
    if rc != 0:
        tail = rqlib.read_text(os.path.join(d, name + ".stderr.log"))[-300:].strip()
        raise CellFailure(3, f"engine ({name}) exit {rc}: {tail}")
    return ru


def _pause_hook(stage, d):
    """Test hook: RQ_TEST_PAUSE=<stage>:<seconds>[:<flag file>] sleeps at that stage (the resume-
    after-kill tests); with a flag file, only while that file does not exist, which it creates
    first with the cell's id in it (so one cell, once, pauses, and the test knows which)."""
    v = os.environ.get("RQ_TEST_PAUSE", "")
    if not v.startswith(stage + ":"):
        return
    parts = v.split(":", 2)
    if len(parts) == 3:
        try:
            fd = os.open(parts[2], os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return
        os.write(fd, (os.path.basename(os.path.abspath(d)) + "\n").encode())
        os.close(fd)
    time.sleep(float(parts[1]))


def _freeze(d, name, data, sha):
    """Write `data` (bytes already hashed to `sha`) as the read-only file d/name the engine will
    read, and check the file's own hash: the engine never opens an archive path."""
    p = os.path.join(d, name)
    with open(p, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(p, 0o444)
    if rqlib.sha256_file(p) != sha:
        raise CellFailure(5, f"the frozen copy {name} does not hash to its registered content")


def execute(cell, d, exe, paths, procs=None):
    """Run cell (a plan row) in the empty directory d with the engine exe. paths: role -> the file to
    read for that role ('prey', 'predators', 'template'), already checked against the registered
    SHA-256 by the caller. -> (bundle dict, info dict); raises CellFailure."""
    procs = [] if procs is None else procs
    t0 = time.time()
    info = {"frozen_inputs": {}}
    prey_src = paths["prey"]
    raw = rqlib.read_bytes(prey_src)       # hashed and parsed from the same bytes
    if rqlib.sha256_bytes(raw) != cell["prey"]["sha256"]:
        raise CellFailure(5, f"the prey snapshot {prey_src} is not its registered content")
    try:
        x_cp = ckpt.loads(raw.decode("utf-8"), prey_src)
        ckpt.validate(x_cp, prey_src)
    except ckpt.CheckpointError as e:
        raise CellFailure(5, str(e))
    # (review round 3) every input is frozen: the engine (native prey) and the store (provenance)
    # read a copy of the very bytes verified above, never the archive path, which could be
    # replaced between the check and a later open
    _freeze(d, "prey.json", raw, cell["prey"]["sha256"])
    info["frozen_inputs"]["prey"] = os.path.join(d, "prey.json")
    del raw
    smeta = ckpt.meta(x_cp)
    if smeta["prey_alive"] == 0:
        raise CellFailure(9, f"biological: the prey snapshot {cell['prey']['path']} has no living prey", "prey")
    if int(smeta["frame"]) != int(cell["prey"]["frame"]):
        raise CellFailure(5, f"the prey snapshot is at frame {smeta['frame']}, registered {cell['prey']['frame']}")
    scripted = cell["kind"] == "assay" and cell["predators"].get("source") == "scripted"
    if cell["kind"] == "assay" and cell["predators"].get("source") not in ("random", "scripted"):
        yraw = rqlib.read_bytes(paths["predators"])
        if rqlib.sha256_bytes(yraw) != cell["predators"]["sha256"]:
            raise CellFailure(5, f"the predator snapshot {paths['predators']} is not its registered content")
        try:
            y = ckpt.loads(yraw.decode("utf-8"), paths["predators"])
            ckpt.validate(y, paths["predators"])
        except ckpt.CheckpointError as e:
            raise CellFailure(5, str(e))
        ym = ckpt.meta(y)
        if ym["format_version"] != ckpt.V2:
            raise CellFailure(5, "the predator snapshot has no predator brains (format version 2 required)")
        if ym["frame"] != int(cell["predators"]["frame"]):
            raise CellFailure(5, f"the predator snapshot is at frame {ym['frame']}, registered {cell['predators']['frame']}")
        if ym["predators"] == 0:
            raise CellFailure(9, f"biological: the predator snapshot {cell['predators']['path']} has no predators",
                              "predators")
        _freeze(d, "pred.json", yraw, cell["predators"]["sha256"])   # the engine reads the verified bytes
        info["frozen_inputs"]["predators"] = os.path.join(d, "pred.json")
        del yraw
        info["donor_predators"] = ym["predators"]

    files = {}
    common_manifest_sha = None
    if cell["prey_policy"] == "common":
        traw = rqlib.read_bytes(paths["template"])
        if rqlib.sha256_bytes(traw) != cell["template"]["sha256"]:
            raise CellFailure(5, f"the template {paths['template']} is not its registered content")
        _freeze(d, "template.json", traw, cell["template"]["sha256"])
        info["frozen_inputs"]["template"] = os.path.join(d, "template.json")
        del traw
        ages = cell.get("ages")            # (plan/2) the reference-age construction, design v3 §3.2
        if ages:
            araw = rqlib.read_bytes(paths["ages"])
            if rqlib.sha256_bytes(araw) != ages["sha256"]:
                raise CellFailure(5, f"the age reference {paths['ages']} is not its registered content")
            _freeze(d, "age_reference.json", araw, ages["sha256"])
            info["frozen_inputs"]["ages"] = os.path.join(d, "age_reference.json")
            del araw
        meta = {"world": cell["prey"]["world"], "uuid": cell["prey"]["uuid"], "time": cell["prey"]["time"]}
        if cell["prey"].get("snapshot"):
            meta["snapshot"] = cell["prey"]["snapshot"]
        try:
            man, csha = common.build_files(
                info["frozen_inputs"]["template"], prey_src, int(cell["n_prey"]), int(cell["seeds"]["sample"]),
                cell["sampling"],
                os.path.join(d, "common.json"), os.path.join(d, "common.manifest.json"),
                template_label=cell["template"]["path"], source_label=cell["prey"]["path"],
                source_meta=meta, source_cp=x_cp, source_sha=cell["prey"]["sha256"],
                ages_path=info["frozen_inputs"].get("ages"), age_seed=(cell["seeds"].get("ages") if ages else None),
                ages_label=ages["path"] if ages else None)
        except (common.CommonError, ckpt.CheckpointError) as e:
            bio = "no living prey" in str(e)
            raise CellFailure(9 if bio else 5, f"common checkpoint: {e}", "prey" if bio else None)
        if man["template"]["sha256"] != cell["template"]["sha256"]:
            raise CellFailure(5, "the template is not its registered content")
        if ages and man["ages"]["sha256"] != ages["sha256"]:
            raise CellFailure(5, "the age reference is not its registered content")
        x_name = "common.json"
        files["common.json"] = csha
        common_manifest_sha = rqlib.sha256_file(os.path.join(d, "common.manifest.json"))
        files["common.manifest.json"] = common_manifest_sha
        info["sampling"] = man["sampling"]
    else:
        x_name = "prey.json"     # frozen above
    info["t_build"] = time.time() - t0

    targs, aargs = commands(cell, x_name)
    t1 = time.time()
    ru_t = _engine(exe, targs, d, "transplant", procs)
    _pause_hook("after-transplant", d)
    ru_a = _engine(exe, aargs, d, "assay", procs)
    info["engine_wall_s"] = time.time() - t1
    info["engine_user_s"] = ru_t.ru_utime + ru_a.ru_utime
    info["engine_maxrss_kb"] = max(ru_t.ru_maxrss, ru_a.ru_maxrss)

    arena = ckpt.load(os.path.join(d, "arena.json"))
    if not str(arena.get("determinism", "")).startswith("serial build"):
        raise CellFailure(2, f"the engine is not a serial build ({arena.get('determinism')!r}): its assays do not replay")
    acfg = arena["config"]
    if cell["assay"] == "live" and int(acfg.get("predatorMinPopulation", 0)) != 0:
        # (review round 2) a live arena keeps X's config, floor included: a floor would refill
        # predators into a challenge's control and change the challenge's density
        raise CellFailure(4, f"a live challenge or its control needs predatorMinPopulation 0 in the prey world "
                             f"(it is {acfg.get('predatorMinPopulation')})")
    if int(acfg.get("minPopulation", 0)) != 0:
        # (review round 3) a prey floor would replenish the prey a challenge removes (and not those
        # of its control): every arena must be without one (the frozen modes set it to 0 already)
        raise CellFailure(4, f"the arena has a prey floor (minPopulation {acfg.get('minPopulation')}): prey would "
                             "be replenished during the assay")
    # the prey settings the challenge and its control must share (checked across cells at packing)
    prey_cfg_sha = rqlib.canonical_sha({k: v for k, v in acfg.items() if not k.startswith("predator")})
    f0, steps, ce = int(arena["world"]["frame"]), int(cell["steps"]), int(cell["checkpoint_every"])
    want = [f0 + m * ce for m in range(1, steps // ce + 1)]
    missing = [f for f in want if not os.path.isfile(os.path.join(d, f"end.{f}.json"))]
    if missing or not os.path.isfile(os.path.join(d, "end.json")):
        raise CellFailure(6, f"checkpoint schedule incomplete: missing frames {missing[:5]} or end.json")
    extra = sorted(f for f in os.listdir(d) if f.startswith("end.") and f.endswith(".json") and f != "end.json"
                   and f not in {f"end.{x}.json" for x in want})
    if extra:
        raise CellFailure(6, f"unexpected checkpoints {extra[:5]}")
    if scripted:
        # a scripted (Stage A) arena has no brain: no predators.csv; it must be version 1, K hunters,
        # immortal and fixed (the economy off)
        if (int(arena.get("formatVersion", 0)) != ckpt.V1 or int(arena["predators"]["count"]) != int(cell["k"])
                or acfg.get("predatorEconomy")):
            raise CellFailure(4, "the scripted arena is not K immortal Stage A hunters (version 1, economy off)")
        if os.path.exists(os.path.join(d, "run.predators.csv")):
            raise CellFailure(4, "a scripted assay wrote predators.csv (a brain where none belongs)")
    for f in ["arena.json", "arena.manifest.json"] + ([] if scripted else ["run.predators.csv"]) + \
            ["run.config.txt", "end.json"] + [f"end.{x}.json" for x in want]:
        files[f] = rqlib.sha256_file(os.path.join(d, f))
    if steps % ce:
        raise CellFailure(6, f"steps {steps} is not a multiple of checkpoint_every {ce}")
    if files["end.json"] != files[f"end.{f0 + steps}.json"]:    # (score.py reads the latter's frame)
        raise CellFailure(6, "end.json differs from the periodic checkpoint at the last step")

    t2 = time.time()
    try:
        sc = score_mod.score(d, 0 if cell["kind"] == "nopred" else int(cell["k"]), steps, list(cell["horizons"]),
                             int(cell["log_every"]), cell["assay"], fork=cell["kind"] == "nopred", scripted=scripted)
    except (score_mod.ScoreError, ckpt.CheckpointError, KeyError, ValueError) as e:
        raise CellFailure(4, f"score check failed: {e}")
    # (D8 v2 rule 48) the bundle binds a complete age summary for every registered horizon
    probs = score_mod.age_strata_problems(sc, list(cell["horizons"]))
    if probs:
        raise CellFailure(4, "score check failed: incomplete age summary: " + "; ".join(probs[:3]))
    info["t_score"] = time.time() - t2
    pred_csv = ""
    if not scripted:
        with open(os.path.join(d, "run.predators.csv")) as f:
            pred_csv = f.read()
    with open(os.path.join(d, "run.csv")) as f:
        run_csv = normalize_run_csv(f.read())
    files["run.csv (without timing columns)"] = rqlib.sha256_bytes(run_csv.encode())
    arena_manifest = rqlib.read_json(os.path.join(d, "arena.manifest.json"))
    plan2 = cell.get("schema") == "finfolk.redqueen.plan/2"
    bundle = {
        "schema": BUNDLE_SCHEMA_V3,
        "cell": cell,
        "binary_sha256": rqlib.sha256_file(exe), "tools_sha256": tools_sha256(),
        "engine_args": {"transplant": targs, "assay": aargs},
        "files": files, "common_manifest_sha256": common_manifest_sha,
        "arena_prey_config_sha256": prey_cfg_sha,
        "arena_manifest": arena_manifest, "score": sc,
        "predators_csv": pred_csv, "run_csv": run_csv,
    }
    if plan2:
        bundle["sharing"] = sharing_record(cell, arena, arena_manifest, files)
    return bundle, info


def forward_signals(procs):
    """Install handlers so a signal to this worker stops its engine first (no engine outlives it)."""
    def fwd(signum, frame):
        for q in list(procs):
            if q.poll() is None:
                q.terminate()
                try:
                    q.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    q.kill()
                    try:
                        q.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        pass
        os._exit(128 + signum)
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, fwd)

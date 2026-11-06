"""cell.py: one Red Queen assay cell, the procedure shared by the runner and its replay.

execute(cell, d, exe, paths) runs, in the empty directory d:
  1. the prey world X:
       prey_policy "common": common.py builds common.json (+ common.manifest.json) from the
       registered template and prey snapshot with the cell's sampling seed;
       prey_policy "native": prey.json, a symlink to the prey snapshot itself;
  2. the design's two engine calls, and nothing else (design section 2):
       evo_boids --load-checkpoint X --predators-from Y --transplant-count K
                 --transplant-seed S --assay MODE --transplant-out arena.json
       evo_boids --load-checkpoint arena.json --reseed-after-load R --headless STEPS --no-render
                 --log-every L --checkpoint-every C --save-checkpoint end.json --csv run.csv
     Y is pred.json (a symlink to the registered predator snapshot), or "random"; the
     predator-free fork is "random" with K = 0. Relative paths only, so the engine's arena
     manifest is the same in a replay;
  3. the checks: the checkpoint schedule (end.<f0 + m C>.json for every m, end.json the last
     step's state, byte-identical to the periodic one), then score.py at every horizon;
  4. the BUNDLE (bundle.json, canonical JSON): the cell row, the binary's and the output tools'
     SHA-256, both engine argument lists, the SHA-256 of every file the cell produced (the
     checkpoints too, which are then deleted: they replay exactly), the common manifest's hash,
     the arena manifest, the score, and the text of run.predators.csv and of run.csv without its
     two timing columns. Everything in it is a function of the cell row, the binary, the tools
     and the source contents: the same row gives the same bytes (tested), and a replay compares
     them. What is not (wall times, host) goes into done.json, outside the bundle.

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
OUTPUT_TOOLS = ("rqlib.py", "ckpt.py", "common.py", "score.py", "cell.py")   # what a bundle depends on
TIMING_COLS = ("elapsed_s", "steps_per_sec")   # run.csv columns that depend on the machine, not the run
HERE = os.path.dirname(os.path.abspath(__file__))


class CellFailure(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


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
    elif p.get("source") == "random":
        src, k = "random", int(cell["k"])
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
        p = subprocess.Popen([exe] + args, cwd=d, stdout=so, stderr=se, stdin=subprocess.DEVNULL,
                             preexec_fn=rqlib.die_with_parent)
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


def execute(cell, d, exe, paths, procs=None):
    """Run cell (a plan row) in the empty directory d with the engine exe. paths: role -> the file to
    read for that role ('prey', 'predators', 'template'), already checked against the registered
    SHA-256 by the caller. -> (bundle dict, info dict); raises CellFailure."""
    procs = [] if procs is None else procs
    t0 = time.time()
    info = {}
    prey_src = paths["prey"]
    raw = rqlib.read_bytes(prey_src)       # hashed and parsed from the same bytes
    if rqlib.sha256_bytes(raw) != cell["prey"]["sha256"]:
        raise CellFailure(5, f"the prey snapshot {prey_src} is not its registered content")
    try:
        x_cp = ckpt.loads(raw.decode("utf-8"), prey_src)
        ckpt.validate(x_cp, prey_src)
    except ckpt.CheckpointError as e:
        raise CellFailure(5, str(e))
    del raw
    smeta = ckpt.meta(x_cp)
    if smeta["prey_alive"] == 0:
        raise CellFailure(9, f"biological: the prey snapshot {cell['prey']['path']} has no living prey")
    if int(smeta["frame"]) != int(cell["prey"]["frame"]):
        raise CellFailure(5, f"the prey snapshot is at frame {smeta['frame']}, registered {cell['prey']['frame']}")
    if cell["kind"] == "assay" and cell["predators"].get("source") != "random":
        yraw = rqlib.read_bytes(paths["predators"])
        if rqlib.sha256_bytes(yraw) != cell["predators"]["sha256"]:
            raise CellFailure(5, f"the predator snapshot {paths['predators']} is not its registered content")
        try:
            y = ckpt.loads(yraw.decode("utf-8"), paths["predators"])
            ckpt.validate(y, paths["predators"])
        except ckpt.CheckpointError as e:
            raise CellFailure(5, str(e))
        del yraw
        ym = ckpt.meta(y)
        if ym["format_version"] != ckpt.V2:
            raise CellFailure(5, "the predator snapshot has no predator brains (format version 2 required)")
        if ym["frame"] != int(cell["predators"]["frame"]):
            raise CellFailure(5, f"the predator snapshot is at frame {ym['frame']}, registered {cell['predators']['frame']}")
        if ym["predators"] == 0:
            raise CellFailure(9, f"biological: the predator snapshot {cell['predators']['path']} has no predators")
        os.symlink(os.path.abspath(paths["predators"]), os.path.join(d, "pred.json"))
        info["donor_predators"] = ym["predators"]

    files = {}
    common_manifest_sha = None
    if cell["prey_policy"] == "common":
        try:
            man, csha = common.build_files(
                paths["template"], prey_src, int(cell["n_prey"]), int(cell["seeds"]["sample"]), cell["sampling"],
                os.path.join(d, "common.json"), os.path.join(d, "common.manifest.json"),
                template_label=cell["template"]["path"], source_label=cell["prey"]["path"],
                source_meta={"world": cell["prey"]["world"], "uuid": cell["prey"]["uuid"], "time": cell["prey"]["time"]},
                source_cp=x_cp, source_sha=cell["prey"]["sha256"])
        except (common.CommonError, ckpt.CheckpointError) as e:
            raise CellFailure(9 if "no living prey" in str(e) else 5, f"common checkpoint: {e}")
        if man["template"]["sha256"] != cell["template"]["sha256"]:
            raise CellFailure(5, "the template is not its registered content")
        x_name = "common.json"
        files["common.json"] = csha
        common_manifest_sha = rqlib.sha256_file(os.path.join(d, "common.manifest.json"))
        files["common.manifest.json"] = common_manifest_sha
        info["sampling"] = man["sampling"]
    else:
        os.symlink(os.path.abspath(prey_src), os.path.join(d, "prey.json"))
        x_name = "prey.json"
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
    f0, steps, ce = int(arena["world"]["frame"]), int(cell["steps"]), int(cell["checkpoint_every"])
    want = [f0 + m * ce for m in range(1, steps // ce + 1)]
    missing = [f for f in want if not os.path.isfile(os.path.join(d, f"end.{f}.json"))]
    if missing or not os.path.isfile(os.path.join(d, "end.json")):
        raise CellFailure(6, f"checkpoint schedule incomplete: missing frames {missing[:5]} or end.json")
    extra = sorted(f for f in os.listdir(d) if f.startswith("end.") and f.endswith(".json") and f != "end.json"
                   and f not in {f"end.{x}.json" for x in want})
    if extra:
        raise CellFailure(6, f"unexpected checkpoints {extra[:5]}")
    for f in ["arena.json", "arena.manifest.json", "run.predators.csv", "run.config.txt", "end.json"] + \
            [f"end.{x}.json" for x in want]:
        files[f] = rqlib.sha256_file(os.path.join(d, f))
    if steps % ce:
        raise CellFailure(6, f"steps {steps} is not a multiple of checkpoint_every {ce}")
    if files["end.json"] != files[f"end.{f0 + steps}.json"]:    # (score.py reads the latter's frame)
        raise CellFailure(6, "end.json differs from the periodic checkpoint at the last step")

    t2 = time.time()
    try:
        sc = score_mod.score(d, 0 if cell["kind"] == "nopred" else int(cell["k"]), steps, list(cell["horizons"]),
                             int(cell["log_every"]), cell["assay"])
    except (score_mod.ScoreError, ckpt.CheckpointError, KeyError, ValueError) as e:
        raise CellFailure(4, f"score check failed: {e}")
    info["t_score"] = time.time() - t2
    with open(os.path.join(d, "run.predators.csv")) as f:
        pred_csv = f.read()
    with open(os.path.join(d, "run.csv")) as f:
        run_csv = normalize_run_csv(f.read())
    files["run.csv (without timing columns)"] = rqlib.sha256_bytes(run_csv.encode())
    arena_manifest = rqlib.read_json(os.path.join(d, "arena.manifest.json"))
    bundle = {
        "schema": BUNDLE_SCHEMA, "cell": cell,
        "binary_sha256": rqlib.sha256_file(exe), "tools_sha256": tools_sha256(),
        "engine_args": {"transplant": targs, "assay": aargs},
        "files": files, "common_manifest_sha256": common_manifest_sha,
        "arena_manifest": arena_manifest, "score": sc,
        "predators_csv": pred_csv, "run_csv": run_csv,
    }
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
                    q.wait()
        os._exit(128 + signum)
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, fwd)

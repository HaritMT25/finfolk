#!/usr/bin/env python3
"""run.py: the invasion-matrix runner. Resumable, failure-propagating, bounded.

    run.py --plan PLAN.jsonl --root DIR --binary EVO_BOIDS [--workers N] [--mem-min-mb M]
    run.py --root DIR --status

PLAN.jsonl (from plan.py) holds one cell per line: one (resident, invader or
sham/self, condition, fraction, replicate) with its seeds and window. Every
cell runs in DIR/cells/<id>/:
    cell.json            the plan entry (a later plan must agree with it)
    arena.json           + arena.manifest.json (arena.py)
    run.csv, run.births.csv, stdout.log, stderr.log   (the engine, serial build)
    end.json             the end checkpoint (intermediate ones are scored, hashed
                         and, unless the cell says keep_intermediate, deleted:
                         the run is bit-exact from arena.json + reseed)
    score.json           score.py (child-id derivation checked)
    done.json            written atomically LAST, only after the process
                         succeeded and the scorer's checks passed
Rules:
  * at most --workers (1..4, default 4) cells at once, each one engine process
    (single-threaded serial build) under nice 19;
  * one runner per DIR (flock DIR/.runner.lock);
  * the binary is pinned: copied to DIR/bin/evo_boids on first use, its SHA-256
    checked before every launch; a different binary for the same DIR is refused;
  * so are the tools: on first use tools/invasion/*.py are copied to DIR/tools/
    and every cell runs from that copy, so editing the sources while a runner
    is going cannot reach a running cell (it once did: a cell imported a
    half-edited score.py). A later start with different sources keeps the
    pinned copy and says so; --update-tools replaces it (finished cells keep
    the tool hashes they ran with in done.json);
  * resume: a cell with done.json has its outputs re-hashed and is skipped (a
    corrupt finished cell is an error); a cell without one is rerun from
    scratch, the earlier attempt moved to DIR/cells/<id>.attempt<N>/;
  * a failed cell (engine exit, scorer check, missing output) stops admission;
    running cells finish; exit 1;
  * DIR/STOP: stop admitting, let running cells finish, exit 75 (remove the
    file and start again to resume);
  * no cell is admitted while MemAvailable < --mem-min-mb (default 1500; this
    is the WSL/Linux reading, not the Windows host's);
  * SIGINT/SIGTERM: the running engines are terminated; exit 130.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import invlib  # noqa: E402

SCHEMA = "finfolk.invasion.cell/1"
TOOL_FILES = ("invlib.py", "arena.py", "score.py", "run.py")
SPEC_KEYS = ("id", "resident", "invader", "mode", "fraction", "state", "condition", "predators",
             "replicate", "slot_seed", "donor_seed", "pred_seed", "reseed", "steps",
             "checkpoint_every", "log_every", "keep_intermediate")


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mem_available_mb():
    try:
        with open("/proc/meminfo") as f:
            for ln in f:
                if ln.startswith("MemAvailable:"):
                    return int(ln.split()[1]) // 1024
    except OSError:
        pass
    return 1 << 30


def load_plan(path):
    cells = []
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                c = json.loads(ln)
                missing = [k for k in SPEC_KEYS if k not in c]
                if missing:
                    raise SystemExit(f"plan cell {c.get('id')}: missing {missing}")
                cells.append(c)
    ids = [c["id"] for c in cells]
    if len(set(ids)) != len(ids):
        raise SystemExit("plan has duplicate cell ids")
    return cells


# --------------------------------------------------------------------- one cell
def run_cell(root, cell_id):
    """Child process: build, run, score, finalize one cell. Exit 0 only when done.json is written."""
    import arena as arena_mod
    import score as score_mod
    d = os.path.join(root, "cells", cell_id)
    c = json.load(open(os.path.join(d, "cell.json")))
    exe = os.path.join(root, "bin", "evo_boids")
    want = open(os.path.join(root, "bin", "evo_boids.sha256")).read().split()[0]
    if invlib.sha256_file(exe) != want:
        print("pinned binary changed", file=sys.stderr)
        return 2
    t0 = time.time()
    cp, man = arena_mod.build(c["resident"], c["invader"], c["mode"], c["fraction"], c["state"],
                              c["predators"], c["slot_seed"], c["donor_seed"], c["pred_seed"], exe)
    ap = os.path.join(d, "arena.json")
    invlib.write_atomic(ap, invlib.dumps_checkpoint(cp))
    man["output"] = {"path": ap, "sha256": invlib.sha256_file(ap)}
    invlib.write_json_atomic(os.path.join(d, "arena.manifest.json"), man)
    t_build = time.time() - t0

    cmd = [exe, "--load-checkpoint", "arena.json", "--reseed-after-load", str(c["reseed"]),
           "--headless", str(c["steps"]), "--no-render", "--log-every", str(c["log_every"]),
           "--csv", "run.csv", "--repro-log", "--repro-log-max", "100000000",
           "--save-checkpoint", "end.json"]
    if c["checkpoint_every"]:
        cmd += ["--checkpoint-every", str(c["checkpoint_every"])]
    t1 = time.time()
    with open(os.path.join(d, "stdout.log"), "w") as so, open(os.path.join(d, "stderr.log"), "w") as se:
        p = subprocess.Popen(cmd, cwd=d, stdout=so, stderr=se, stdin=subprocess.DEVNULL)
        _, status, ru = os.wait4(p.pid, 0)
    wall = time.time() - t1
    rc = os.waitstatus_to_exitcode(status)
    if rc != 0:
        print(f"engine exit {rc}", file=sys.stderr)
        return 3
    start_frame = man["start"]["frame"]
    mids = sorted((f for f in os.listdir(d) if f.startswith("end.") and f.endswith(".json") and f != "end.json"),
                  key=lambda f: int(f.split(".")[1]))
    # the periodic checkpoint at the last step duplicates end.json
    mids = [f for f in mids if int(f.split(".")[1]) != start_frame + c["steps"]]
    t2 = time.time()
    try:
        res = score_mod.score(ap, os.path.join(d, "arena.manifest.json"), os.path.join(d, "run.births.csv"),
                              [os.path.join(d, f) for f in mids] + [os.path.join(d, "end.json")])
    except score_mod.DerivationError as e:
        print(f"DERIVATION CHECK FAILED: {e}", file=sys.stderr)
        return 4
    invlib.write_json_atomic(os.path.join(d, "score.json"), res)
    t_score = time.time() - t2
    # run.csv: population and speed over the window
    pops, sps = [], []
    with open(os.path.join(d, "run.csv")) as f:
        for r in csv.DictReader(f):
            pops.append(int(r["population"]))
            sps.append(float(r["steps_per_sec"]))
    intermediates = {f: invlib.sha256_file(os.path.join(d, f)) for f in mids}
    if not c["keep_intermediate"]:
        for f in mids:
            os.remove(os.path.join(d, f))
    outputs = {f: invlib.sha256_file(os.path.join(d, f))
               for f in ("arena.json", "arena.manifest.json", "run.csv", "run.births.csv", "end.json", "score.json")}
    done = {
        "schema": SCHEMA, "finished_utc": now(), "cell": c,
        "binary_sha256": want,
        "tools_sha256": {f: invlib.sha256_file(os.path.join(HERE, f)) for f in TOOL_FILES},
        "command": cmd,
        "timing": {"build_s": round(t_build, 3), "engine_wall_s": round(wall, 3),
                   "engine_user_s": round(ru.ru_utime, 3), "engine_sys_s": round(ru.ru_stime, 3),
                   "engine_maxrss_kb": ru.ru_maxrss, "score_s": round(t_score, 3),
                   "steps_per_s": round(c["steps"] / wall, 1) if wall > 0 else None},
        "population": {"start": res["n0"], "mean": sum(pops) / len(pops) if pops else None,
                       "min": min(pops) if pops else None, "max": max(pops) if pops else None},
        "outputs": outputs, "intermediate_checkpoints": intermediates,
        "derivation": res["derivation"],
    }
    invlib.write_json_atomic(os.path.join(d, "done.json"), done)
    return 0


def verify_done(d):
    done = json.load(open(os.path.join(d, "done.json")))
    bad = [f for f, h in done["outputs"].items()
           if not os.path.exists(os.path.join(d, f)) or invlib.sha256_file(os.path.join(d, f)) != h]
    return done, bad


# ------------------------------------------------------------------- the runner
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--plan")
    ap.add_argument("--root", required=True)
    ap.add_argument("--binary")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--mem-min-mb", type=int, default=1500)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--quick-resume", action="store_true",
                    help="skip re-hashing finished cells' outputs (existence only)")
    ap.add_argument("--update-tools", action="store_true",
                    help="replace DIR/tools with the current tools/invasion sources")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)

    if a.status:
        cdir = os.path.join(root, "cells")
        ids = [x for x in os.listdir(cdir) if ".attempt" not in x] if os.path.isdir(cdir) else []
        n_done = sum(1 for x in ids if os.path.exists(os.path.join(cdir, x, "done.json")))
        print(f"{root}: {n_done} done of {len(ids)} started")
        return 0
    if not (a.plan and a.binary):
        ap.error("--plan and --binary are required to run")
    if not 1 <= a.workers <= 4:
        ap.error("--workers must be 1..4")

    os.makedirs(os.path.join(root, "cells"), exist_ok=True)
    os.makedirs(os.path.join(root, "bin"), exist_ok=True)
    lock = open(os.path.join(root, ".runner.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"another runner holds {root}", file=sys.stderr)
        return 73
    os.nice(19 - os.nice(0))   # everything below (and every child) at nice 19

    logf = open(os.path.join(root, "runner.log"), "a")

    def log(msg):
        line = f"{now()} {msg}"
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    # pin the binary
    pinned = os.path.join(root, "bin", "evo_boids")
    want = invlib.sha256_file(a.binary)
    if not os.path.exists(pinned):
        shutil.copy2(a.binary, pinned)
        with open(pinned + ".sha256", "w") as f:
            f.write(f"{want}  {os.path.abspath(a.binary)}\n")
    have = open(pinned + ".sha256").read().split()[0]
    if have != want:
        print(f"{root} already runs another binary ({have[:12]}); this one is {want[:12]}", file=sys.stderr)
        return 2
    if invlib.sha256_file(pinned) != have:
        print("the pinned binary no longer matches its hash", file=sys.stderr)
        return 2

    # pin the tools (see the header)
    tdir = os.path.join(root, "tools")
    src = {f: invlib.sha256_file(os.path.join(HERE, f)) for f in TOOL_FILES}
    if os.path.abspath(HERE) != os.path.abspath(tdir):
        if not os.path.isdir(tdir) or a.update_tools:
            os.makedirs(tdir, exist_ok=True)
            for f in TOOL_FILES:
                shutil.copy2(os.path.join(HERE, f), os.path.join(tdir, f))
            log(f"tools pinned in {tdir}: " + " ".join(f"{f}={h[:10]}" for f, h in src.items()))
        else:
            pin = {f: invlib.sha256_file(os.path.join(tdir, f)) for f in TOOL_FILES}
            if pin != src:
                log(f"note: tools/invasion differs from the pinned {tdir}; running the pinned copy "
                    f"(--update-tools to replace it)")
    cell_runner = os.path.join(tdir, "run.py")

    cells = load_plan(a.plan)
    todo = []
    for c in cells:
        d = os.path.join(root, "cells", c["id"])
        spec = dict(c)
        if os.path.exists(os.path.join(d, "cell.json")):
            old = json.load(open(os.path.join(d, "cell.json")))
            if old != spec:
                print(f"cell {c['id']}: plan entry differs from the one already in {d}", file=sys.stderr)
                return 2
        if os.path.exists(os.path.join(d, "done.json")):
            if a.quick_resume:
                continue
            _, bad = verify_done(d)
            if bad:
                print(f"cell {c['id']}: finished outputs changed: {bad}", file=sys.stderr)
                return 1
            continue
        todo.append(spec)
    log(f"plan {a.plan}: {len(cells)} cells, {len(cells) - len(todo)} already done, {len(todo)} to run, "
        f"workers {a.workers}")

    running = {}   # pid -> (Popen, id, t0)
    failed = []
    stop_reason = None
    attempts = open(os.path.join(root, "attempts.tsv"), "a")

    def terminate(signum, frame):
        for p, _, _ in running.values():
            try:
                p.terminate()
            except OSError:
                pass
        for p, _, _ in running.values():
            p.wait()
        log(f"signal {signum}: terminated {len(running)} running cells")
        sys.exit(130)
    signal.signal(signal.SIGINT, terminate)
    signal.signal(signal.SIGTERM, terminate)

    queue = list(todo)
    n_done = 0
    while queue or running:
        # reap
        for pid in list(running):
            p, cid, t0 = running[pid]
            rc = p.poll()
            if rc is None:
                continue
            del running[pid]
            dt = time.time() - t0
            attempts.write(f"{now()}\t{cid}\t{rc}\t{dt:.1f}\n")
            attempts.flush()
            if rc == 0 and os.path.exists(os.path.join(root, "cells", cid, "done.json")):
                n_done += 1
                if n_done % 10 == 0 or not queue:
                    log(f"done {n_done}/{len(todo)} (last {cid}, {dt:.0f}s)")
            else:
                failed.append(cid)
                err = open(os.path.join(root, "cells", cid, "cell.stderr.log")).read()[-400:]
                log(f"FAILED {cid} (exit {rc}): {err.strip()}")
        # admission
        if os.path.exists(os.path.join(root, "STOP")) and stop_reason is None:
            stop_reason = "STOP"
            log(f"STOP file: no new cells; waiting for {len(running)}")
        admit = stop_reason is None and not failed
        while admit and queue and len(running) < a.workers:
            if mem_available_mb() < a.mem_min_mb:
                break
            spec = queue.pop(0)
            d = os.path.join(root, "cells", spec["id"])
            if os.path.exists(d):
                k = 1
                while os.path.exists(f"{d}.attempt{k}"):
                    k += 1
                os.rename(d, f"{d}.attempt{k}")
            os.makedirs(d)
            invlib.write_json_atomic(os.path.join(d, "cell.json"), spec)
            err = open(os.path.join(d, "cell.stderr.log"), "w")
            p = subprocess.Popen([sys.executable, "-I", cell_runner, "--root", root,
                                  "--_cell", spec["id"]], stdout=err, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL)
            running[p.pid] = (p, spec["id"], time.time())
        if not admit and not running:
            break
        time.sleep(0.5)

    if failed:
        log(f"stopped: {len(failed)} failed cell(s): {failed[:5]}")
        return 1
    if stop_reason:
        log("stopped by STOP file")
        return 75
    log(f"all {len(cells)} cells done")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 5 and sys.argv[3] == "--_cell":
        sys.exit(run_cell(os.path.abspath(sys.argv[2]), sys.argv[4]))
    sys.exit(main())

#!/usr/bin/env python3
"""run.py: the invasion-matrix runner. Resumable, failure-propagating, bounded.

    run.py --plan PLAN.jsonl --root DIR --binary EVO_BOIDS [--workers N] [--mem-min-mb M]
           [--prune] [--disk-min PATH:MB ...] [--quick-resume] [--update-tools | --update-runner]
    run.py --root DIR --status
    run.py --root DIR --prune-finished
    run.py --root DIR --replay CELL_ID --out EMPTY_DIR

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
    done.json            written LAST, only after the process succeeded and the
                         scorer's checks passed, by finalize(): every file it
                         vouches for fsync'd, then the directory; done.json
                         itself a temporary file fsync'd, renamed, and the
                         directory fsync'd after the rename (the engine does
                         not fsync; a crash once left durable done.json files
                         over zero-length outputs); only then deletions, and
                         the directory fsync'd again. The prune sweep uses the
                         same protocol (review round 4)
With --prune a finished cell keeps only cell.json, done.json, score.json,
arena.manifest.json, run.csv, run.config.txt, stdout.log and
run.births.csv.gz (see below): everything analyze.py and horizon.py read.
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
    the tool hashes they ran with in done.json), after putting the pinned
    versions into DIR/store, and refuses if a finished cell needs a version
    the store lacks; --update-runner replaces only run.py (the scoring tools
    every cell ran with stay pinned);
  * so are the snapshots: plan.py registers each source file's SHA-256 in the
    cell (resident_sha256 / invader_sha256). Every registered file is checked
    before anything is admitted (a mismatch refuses the batch, exit 2) and
    again before every build (a mismatch fails the cell, exit 5), so a
    snapshot overwritten between or during batch attempts never mixes in;
  * resume: a cell with done.json has its outputs re-hashed and is skipped (a
    corrupt finished cell is an error); a cell without one is rerun from
    scratch, the earlier attempt moved to DIR/cells/<id>.attempt<N>/;
  * the checkpoint schedule is verified: every periodic checkpoint the cell's
    checkpoint_every implies must exist (the engine only warns when a
    periodic write fails) and end.json must be the cell's last step; a gap
    fails the cell (exit 6) instead of moving a window's read;
  * a failed cell (engine exit, scorer check, missing output) stops admission;
    running cells finish; exit 1;
  * DIR/STOP: stop admitting, let running cells finish, exit 75 (remove the
    file and start again to resume);
  * memory, fail closed: a cell is admitted only while min(MemAvailable, every
    cgroup v2 memory.max - memory.current up the tree) >= --mem-min-mb
    (default 1500) + the reserve for one more cell (the largest engine RSS
    seen so far + 64 MB, at least 150 MB). An unreadable or malformed reading
    admits nothing; if it stays unreadable with no cell running the runner
    exits 2. (These are the WSL / Linux readings, not the Windows host's.)
    Test hooks: INVASION_MEMINFO, INVASION_PROC_CGROUP, INVASION_CGROUP_ROOT;
  * SIGINT/SIGTERM (to the runner alone or its group): every cell worker leads
    its own process group, which its engine joins; the runner signals each
    group, reaps the worker and waits until the group is empty (SIGKILL after
    20 s), and a worker signalled on its own forwards to its engine and waits
    for it. Children also get PR_SET_PDEATHSIG. No engine outlives the
    runner's lock; exit 130;
  * --prune (an error bank: tens of thousands of cells, ~3.4 MB of checkpoints
    each): once a cell is scored and its checks passed (check_finished: every
    output matches its hash, the score reached the cell's last step with the
    derivation checks passed, on these very arena and births files) AND its
    replay can be verified (replay_prereqs, review round 4: the pinned binary
    is the cell's by hash; the scoring-tool versions it ran and the snapshots
    its arena read are in DIR/store by content hash, copied there from the
    pinned tools / registered paths while those still match; round 5: all of
    them, the pinned binary and the directories holding them fsync'd before
    any deletion, durability_barrier), its arena.json,
    end.json and every end.<frame>.json are deleted and its birth log is kept
    gzipped (run.births.csv.gz: level 9, mtime 0, lossless; zcat gives the
    original bytes). Each deleted file is hashed against its record first and
    its SHA-256 kept in done.json "pruned" (with the gzip's own hash, verified
    by decompressing), so a replay is checked byte for byte. Order (finalize):
    gzip + verify, fsync what stays, done.json with the pruned record (durable),
    then the deletions and a directory fsync; a cell stopped in between keeps
    extra files, which the next --prune start deletes after revalidating the
    cell. At start --prune also prunes every finished cell not yet pruned (the
    same protocol; a cell that fails its checks is left untouched and the
    runner exits 1; a cell whose replay provenance cannot be established, e.g.
    from before tool pinning, keeps its checkpoints), checks that every cell
    pruned earlier can still be replayed, and strips failed attempts'
    checkpoints. --prune-finished runs only that sweep. --prune overrides
    keep_intermediate. The pinned tools must support it (--update-runner once);
  * replay: a pruned cell's checkpoints come back exactly from the pinned
    binary, its tools, its snapshots and the cell's seeds:
        run.py --root DIR --replay CELL_ID --out EMPTY_DIR
    rebuilds arena.json, reruns the engine with the cell's recorded arguments,
    rescores, and compares arena.json, end.json, every periodic checkpoint,
    run.births.csv and score.json with the recorded SHA-256s (run.csv without
    its two timing columns, the manifest without its time stamp and paths);
    exit 0 only if every one matches (replay.json in EMPTY_DIR, which
    keeps the replayed files). It needs DIR/bin/evo_boids and the scoring
    tools and snapshots the cell recorded: the pinned ones, or (if they have
    been updated or moved since) their copies in DIR/store, rebuilt in
    EMPTY_DIR/replay_tools;
  * disk guard, fail closed: before each cell every --disk-min PATH:MB must
    have MB free (statvfs f_bavail x f_frsize = df --output=avail). Default on
    WSL (/mnt/c mounted): / >= 10240 MB and /mnt/c >= 6000 MB (WSL's ext4.vhdx
    lives on the Windows drive, grows and never shrinks by itself); elsewhere
    DIR >= 1024 MB; 'none' disables it. Below a threshold, or with an
    unreadable reading, the runner takes the STOP path (no new cells, running
    cells finish, exit 75) and writes the reason into DIR/STOP. Admission stops
    in memory first: a failed write (ENOSPC / EIO) of STOP, progress.json, the
    logs or a new cell's directory does not break that path (review round 4),
    and whatever else breaks the loop, the running cells' workers and engines
    are terminated before the runner exits;
  * scratch files: each cell worker and its engine get TMPDIR (TMP, TEMP) = the
    cell's own tmp/, removed when the cell finishes (done.json counts what was
    left in it), so no cell leaves files under /tmp.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import errno
import fcntl
import gzip
import hashlib
import json
import math
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
PRUNE_SCHEMA = "finfolk.invasion.prune/1"
TOOL_FILES = ("invlib.py", "arena.py", "score.py", "run.py")
SCORING_TOOLS = ("invlib.py", "arena.py", "score.py")   # what a cell's arena and score depend on
BIRTHS, BIRTHS_GZ = "run.births.csv", "run.births.csv.gz"
TIMING_COLS = ("elapsed_s", "steps_per_sec")   # run.csv columns that depend on the machine, not the run
SPEC_KEYS = ("id", "resident", "invader", "mode", "fraction", "state", "condition", "predators",
             "replicate", "slot_seed", "donor_seed", "pred_seed", "reseed", "steps",
             "checkpoint_every", "log_every", "keep_intermediate")


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def die_with_parent():
    """preexec_fn: SIGTERM this child if its parent dies, even by SIGKILL (Linux prctl
    PR_SET_PDEATHSIG; best effort elsewhere). Backs up the explicit forwarding below."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM, 0, 0, 0)
    except (OSError, AttributeError):
        pass


def stop_group(pgid, log=None, grace=20.0):
    """SIGTERM every process in group pgid, then wait until the group is empty (SIGKILL after
    `grace` seconds). The caller reaps its own direct child separately."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    t0 = time.time()
    killed = False
    while True:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        if time.time() - t0 > grace and not killed:
            if log:
                log(f"process group {pgid} still alive after {grace:.0f} s: SIGKILL")
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                return
            killed = True
        elif killed and time.time() - t0 > grace + 5:
            if log:   # only unreaped zombies can be left (an init that does not reap orphans)
                log(f"process group {pgid} still listed 5 s after SIGKILL (zombies?)")
            return
        time.sleep(0.05)


def _cgroup_headroom_mb():
    """Smallest (memory.max - memory.current) over this process's cgroup v2 and its ancestors, in MB;
    None when no limit applies; raises ValueError / OSError on a malformed or unreadable reading."""
    root = os.environ.get("INVASION_CGROUP_ROOT", "/sys/fs/cgroup")
    rel = None
    with open(os.environ.get("INVASION_PROC_CGROUP", "/proc/self/cgroup")) as f:
        for ln in f:
            if ln.startswith("0::"):
                rel = ln.strip()[3:]
    if rel is None:
        return None                       # no unified hierarchy: no cgroup v2 limit to honour
    best = None
    d = os.path.normpath(os.path.join(root, rel.lstrip("/")))
    while True:
        mx_p = os.path.join(d, "memory.max")
        if os.path.exists(mx_p):
            mx = open(mx_p).read().strip()
            if mx != "max":
                cur = int(open(os.path.join(d, "memory.current")).read().strip())
                h = (int(mx) - cur) // (1 << 20)
                best = h if best is None else min(best, h)
        if os.path.normpath(d) == os.path.normpath(root) or len(d) <= len(root):
            break
        d = os.path.dirname(d)
    return best


def mem_headroom_mb():
    """Memory a new cell may use, in MB: min(MemAvailable, every applicable cgroup v2 headroom).
    None when any reading is missing or malformed: the caller must then NOT start a cell (fail closed)."""
    avail = None
    try:
        with open(os.environ.get("INVASION_MEMINFO", "/proc/meminfo")) as f:
            for ln in f:
                if ln.startswith("MemAvailable:"):
                    p = ln.split()
                    if len(p) >= 2 and p[1].isdigit():
                        avail = int(p[1]) // 1024
                    break
        if avail is None:
            return None
        cg = _cgroup_headroom_mb()
    except (OSError, ValueError):
        return None
    return avail if cg is None else min(avail, cg)


def snapshot_problems(c, cache=None):
    """Registered snapshot files whose content no longer matches the plan (plan.py records
    resident_sha256 / invader_sha256; a plan without them registers paths only)."""
    bad = []
    cache = {} if cache is None else cache
    for role in ("resident", "invader"):
        want = c.get(f"{role}_sha256")
        if want and c.get(role):
            if c[role] not in cache:
                cache[c[role]] = invlib.sha256_file(c[role]) if os.path.exists(c[role]) else "missing"
            have = cache[c[role]]
            if have != want:
                bad.append(f"{role} {c[role]}: sha256 {have[:12]} != registered {want[:12]}")
    return bad


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
def execute(c, d, exe):
    """Build cell c's arena in directory d, run the engine there and score it -> (exit code, info).
    The same steps for a cell (run_cell) and for its replay (replay_cell)."""
    import arena as arena_mod
    import score as score_mod
    t0 = time.time()
    cp, man = arena_mod.build(c["resident"], c["invader"], c["mode"], c["fraction"], c["state"],
                              c["predators"], c["slot_seed"], c["donor_seed"], c["pred_seed"], exe)
    for role in ("resident", "invader"):   # ... and the arena read the registered content
        reg = c.get(f"{role}_sha256")
        if reg and man.get(role) and man[role]["sha256"] != reg:
            print(f"SNAPSHOT CHANGED during the build: {role} {man[role]['sha256'][:12]} != {reg[:12]}",
                  file=sys.stderr)
            return 5, None
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
    engine = []

    def forward(signum, frame):
        # The runner stops a cell by signalling the cell's process group (this worker and its
        # engine); a signal sent to the worker alone is forwarded here, and the worker does not
        # exit before its engine has, so no engine outlives the runner's lock.
        for q in engine:
            if q.poll() is None:
                q.terminate()
                try:
                    q.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    q.kill()
                    q.wait()
        os._exit(128 + signum)
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, forward)
    with open(os.path.join(d, "stdout.log"), "w") as so, open(os.path.join(d, "stderr.log"), "w") as se:
        p = subprocess.Popen(cmd, cwd=d, stdout=so, stderr=se, stdin=subprocess.DEVNULL, preexec_fn=die_with_parent)
        engine.append(p)
        _, status, ru = os.wait4(p.pid, 0)
    p.returncode = os.waitstatus_to_exitcode(status)   # reaped by wait4: keep poll() from asking again
    wall = time.time() - t1
    rc = os.waitstatus_to_exitcode(status)
    if rc != 0:
        print(f"engine exit {rc}", file=sys.stderr)
        return 3, None
    start_frame = man["start"]["frame"]
    gap = check_schedule(os.listdir(d), start_frame, c["steps"], c["checkpoint_every"])
    if gap:
        print(f"CHECKPOINT SCHEDULE INCOMPLETE: no periodic checkpoint at frames {gap[:5]}"
              f"{' ...' if len(gap) > 5 else ''} ({len(gap)} missing)", file=sys.stderr)
        return 6, None
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
        return 4, None
    if res["points"][-1]["steps"] != c["steps"]:   # end.json is the run's end, not an earlier state
        print(f"END CHECKPOINT at {res['points'][-1]['steps']} steps, the cell asked for {c['steps']}", file=sys.stderr)
        return 6, None
    invlib.write_json_atomic(os.path.join(d, "score.json"), res)
    t_score = time.time() - t2
    return 0, {"man": man, "cmd": cmd, "res": res, "mids": mids, "wall": wall, "ru": ru,
               "t_build": t_build, "t_score": t_score}


def run_cell(root, cell_id, prune=False):
    """Child process: build, run, score, finalize one cell. Exit 0 only when done.json is written."""
    d = os.path.join(root, "cells", cell_id)
    c = json.load(open(os.path.join(d, "cell.json")))
    exe = os.path.join(root, "bin", "evo_boids")
    want = open(os.path.join(root, "bin", "evo_boids.sha256")).read().split()[0]
    if invlib.sha256_file(exe) != want:
        print("pinned binary changed", file=sys.stderr)
        return 2
    bad = snapshot_problems(c)   # before every build: a snapshot overwritten mid-batch never mixes in
    if bad:
        print("SNAPSHOT CHANGED since planning: " + "; ".join(bad), file=sys.stderr)
        return 5
    rc, x = execute(c, d, exe)
    if rc:
        return rc
    res, mids, cmd, wall, ru = x["res"], x["mids"], x["cmd"], x["wall"], x["ru"]
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
        "timing": {"build_s": round(x["t_build"], 3), "engine_wall_s": round(wall, 3),
                   "engine_user_s": round(ru.ru_utime, 3), "engine_sys_s": round(ru.ru_stime, 3),
                   "engine_maxrss_kb": ru.ru_maxrss, "score_s": round(x["t_score"], 3),
                   "steps_per_s": round(c["steps"] / wall, 1) if wall > 0 else None},
        "population": {"start": res["n0"], "mean": sum(pops) / len(pops) if pops else None,
                       "min": min(pops) if pops else None, "max": max(pops) if pops else None},
        "outputs": outputs, "intermediate_checkpoints": intermediates,
        "derivation": res["derivation"],
    }
    tmpd = os.path.join(d, "tmp")   # the cell's TMPDIR (see the header): gone when the cell is done
    if os.path.isdir(tmpd):
        done["tmp_files_left"] = sum(len(fs) for _, _, fs in os.walk(tmpd))
        shutil.rmtree(tmpd, ignore_errors=True)
    try:
        _, warn = finalize(root, d, done, prune)
    except (PruneError, ProvenanceError, OSError) as e:
        print(f"{'PRUNE CHECK FAILED' if prune else 'FINALIZE FAILED'} (nothing deleted, no done.json): {e}",
              file=sys.stderr)
        return 7
    if warn:   # the cell is done; the next --prune start finishes its prune
        print(f"warning: {warn}", file=sys.stderr)
    return 0


# ------------------------------------------------------- durable finalization
def fsync_dir(d):
    """fsync a directory (its entries: a rename or unlink in it is durable after this). A
    filesystem that cannot fsync a directory (EINVAL / ENOTSUP) is tolerated."""
    fd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(fd)
    except OSError as e:
        if e.errno not in (errno.EINVAL, errno.ENOTSUP, errno.EBADF):
            raise
    finally:
        os.close(fd)


def fsync_files(d, names):
    """fsync each regular file d/name, then d itself."""
    for f in names:
        p = os.path.join(d, f)
        if os.path.isfile(p):
            fd = os.open(p, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    fsync_dir(d)


def write_durable(path, obj):
    """JSON (invlib.write_json_atomic's format) to a temporary file, fsync'd, renamed over path,
    then the directory fsync'd AFTER the rename, so the new record is durable before anything it
    describes is deleted (review round 4, P2-3). Self-contained: a pinned older invlib does not
    change it."""
    write_durable_text(path, json.dumps(obj, indent=1, sort_keys=True, allow_nan=False) + "\n")


def write_durable_text(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fsync_dir(os.path.dirname(os.path.abspath(path)))


def pin_binary(root, binary):
    """Pin the engine binary as DIR/bin/evo_boids on first use, durably (review round 5: replays of
    pruned cells depend on it): a temporary copy fsync'd and renamed, its sha256 record written
    durably, then bin/ and the root fsync'd. An existing pin is left as it is. -> the binary's hash."""
    bdir = os.path.join(root, "bin")
    pinned = os.path.join(bdir, "evo_boids")
    want = invlib.sha256_file(binary)
    if not os.path.exists(pinned):
        tmp = pinned + ".tmp"
        shutil.copy2(binary, tmp)
        with open(tmp, "rb") as f:
            os.fsync(f.fileno())
        os.replace(tmp, pinned)
        write_durable_text(pinned + ".sha256", f"{want}  {os.path.abspath(binary)}\n")
        fsync_dir(bdir)
        fsync_dir(root)
    return want


def finalize(root, d, done, prune):
    """THE finalization protocol of a finished cell, shared by a new cell (run_cell) and the sweep
    (prune_finished) (review round 4, P2-3):
      1. with prune: check_finished (the score is valid on these very files), replay_prereqs (a
         replay can be verified: binary, tool versions and snapshots by content hash, see there),
         then prune_plan (hash every checkpoint to go against its record, gzip the birth log
         and verify it by decompressing; nothing deleted);
      2. fsync every file that stays (the gzip included), then the directory (its entries);
      3. done.json durably (write_durable: temporary file fsync'd, renamed, directory fsync'd);
      4. with prune: the deletions (each file re-hashed against its record first), then the
         directory fsync'd again.
    A failed check raises before step 3 (PruneError, ProvenanceError for replay prerequisites):
    nothing is deleted and no done.json is written. -> (bytes freed, warning or None): a failed
    deletion after step 3 is only a warning (the next --prune start finishes it)."""
    if prune:
        probs = check_finished(d, done)
        if probs:
            raise PruneError("; ".join(probs))
        probs, deps = replay_deps(root, d, done)
        if probs:
            raise ProvenanceError("replay provenance not established: " + "; ".join(probs))
        durability_barrier(root, deps)   # (review round 5) the replay inputs are durable before any deletion
        done["pruned"] = prune_plan(d, done)
    gone = (set(done["pruned"]["removed"]) | set(done["pruned"].get("compressed") or {})) if prune else set()
    fsync_files(d, [f for f in os.listdir(d) if f not in gone and not f.endswith(".tmp")])
    write_durable(os.path.join(d, "done.json"), done)
    if not prune:
        return 0, None
    try:
        freed = prune_apply(d, done)
        fsync_dir(d)
    except (PruneError, OSError) as e:
        return 0, f"prune incomplete ({e})"
    return freed, None


def finish_prune(root, d, done):
    """Complete an interrupted prune (done.json has its 'pruned' record but files it lists are
    still there): REVALIDATE first (review round 4: this branch used to delete without
    check_finished) - the score check, the record itself (every listed file still present matches
    its hash, the gzip matches and decompresses to the recorded birth log) and the replay
    prerequisites - then flush what stays (done.json included), delete, fsync the directory.
    -> bytes freed; raises PruneError / ProvenanceError with nothing deleted."""
    probs = check_finished(d, done) + check_prune_record(d, done)
    if probs:
        raise PruneError("; ".join(probs))
    probs, deps = replay_deps(root, d, done)
    if probs:
        raise ProvenanceError("replay provenance not established: " + "; ".join(probs))
    durability_barrier(root, deps)
    gone = set(done["pruned"]["removed"]) | set(done["pruned"].get("compressed") or {})
    fsync_files(d, [f for f in os.listdir(d) if f not in gone and not f.endswith(".tmp")])
    freed = prune_apply(d, done)
    fsync_dir(d)
    return freed


def prune_leftovers(d, done):
    """Files a 'pruned' record lists for deletion that are still present."""
    pr = done.get("pruned") or {}
    return [f for f in list(pr.get("removed") or {}) + list(pr.get("compressed") or {}) if os.path.exists(os.path.join(d, f))]


def check_prune_record(d, done):
    """Problems of a 'pruned' record against the directory (see finish_prune)."""
    pr = done.get("pruned") or {}
    bad = []
    if pr.get("schema") != PRUNE_SCHEMA:
        bad.append(f"pruned record schema {pr.get('schema')!r}")
    for f, h in (pr.get("removed") or {}).items():
        p = os.path.join(d, f)
        if os.path.exists(p) and invlib.sha256_file(p) != h:
            bad.append(f"{f} is not the file the prune recorded")
    for f, rec in (pr.get("compressed") or {}).items():
        gz = os.path.join(d, rec.get("file", ""))
        if not os.path.isfile(gz) or invlib.sha256_file(gz) != rec.get("sha256"):
            bad.append(f"{rec.get('file')} missing or not the recorded gzip")
        elif gunzip_sha256(gz) != (done.get("outputs") or {}).get(f):
            bad.append(f"{rec.get('file')} does not decompress to the recorded {f}")
    return bad


# ------------------------------------------------- replay provenance (the store)
# Review round 4, P1-2: before pruning deletes the last usable simulation state of a cell, a
# verified replay must be possible. DIR/store/<sha256> keeps, by content hash, every scoring-tool
# version (invlib / arena / score) and every snapshot a pruned cell read; --update-tools puts the
# pinned versions there before replacing them and refuses if a finished cell needs a version the
# store lacks; a replay whose cell ran other tools rebuilds that version set from the store, and
# a snapshot missing or changed at its path is read from the store. The binary is pinned per root
# (a different one is refused) and checked by hash.
STORE = "store"
REPLAY_TOOLS = "replay_tools"   # --replay OUT/replay_tools: a cell's stored scoring-tool versions + this run.py
_STORE_OK = set()   # blobs verified by this process
_BIN_SHA = {}


class ProvenanceError(Exception):
    """A finished cell whose replay could not be verified: it keeps its checkpoints."""


def store_path(root, sha):
    return os.path.join(root, STORE, sha)


def store_has(root, sha):
    """The store holds a blob with this content (hash-verified once per process)."""
    if not sha:
        return False
    if (root, sha) in _STORE_OK:
        return True
    p = store_path(root, sha)
    if os.path.isfile(p) and invlib.sha256_file(p) == sha:
        _STORE_OK.add((root, sha))
        return True
    return False


def store_put(root, src, want=None):
    """Copy src into the store under its SHA-256: idempotent, atomic (a per-process temporary
    file, fsync'd, verified, read-only, renamed; the store directory fsync'd), safe for
    concurrent workers. want: the content src must have. -> the hash; raises ProvenanceError."""
    sha = invlib.sha256_file(src)
    if want is not None and sha != want:
        raise ProvenanceError(f"{src} is {sha[:12]}, not the needed {want[:12]}")
    if store_has(root, sha):
        return sha
    sd = os.path.join(root, STORE)
    if not os.path.isdir(sd):
        os.makedirs(sd, exist_ok=True)
        fsync_dir(root)   # the store directory's own entry (review round 5)
    tmp = f"{store_path(root, sha)}.tmp.{os.getpid()}"
    shutil.copyfile(src, tmp)
    with open(tmp, "rb") as f:
        os.fsync(f.fileno())
    if invlib.sha256_file(tmp) != sha:
        os.remove(tmp)
        raise ProvenanceError(f"{src} changed while it was copied into the store")
    os.chmod(tmp, 0o444)
    os.replace(tmp, store_path(root, sha))
    fsync_dir(sd)
    _STORE_OK.add((root, sha))
    return sha


def needed_versions_missing(root):
    """Scoring-tool versions some finished cell under DIR/cells ran with that the store lacks
    (a cell's replay rebuilds its version set from there). -> sorted ['file sha', ...]."""
    cdir = os.path.join(root, "cells")
    need = set()
    for x in (os.listdir(cdir) if os.path.isdir(cdir) else []):
        p = os.path.join(cdir, x, "done.json")
        if ".attempt" in x or not os.path.isfile(p):
            continue
        try:
            t = json.load(open(p)).get("tools_sha256") or {}
        except ValueError:
            continue
        need |= {(f, t[f]) for f in SCORING_TOOLS if t.get(f)}
    return sorted(f"{f} {h[:12]}" for f, h in need if not store_has(root, h))


def _pinned_binary_sha(root):
    if root not in _BIN_SHA:
        p = os.path.join(root, "bin", "evo_boids")
        _BIN_SHA[root] = invlib.sha256_file(p) if os.path.isfile(p) else None
    return _BIN_SHA[root]


_SYNCED = set()   # (root, path or blob hash) made durable by this process (fsync: durable whoever wrote it)


def _fsync_path(p):
    if os.path.isdir(p):
        fsync_dir(p)
        return
    fd = os.open(p, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durability_barrier(root, blobs):
    """Review round 5, P2-1: before a deletion is authorized, the WHOLE replay-dependency set is
    durable, not only hash-verified: every needed store blob (its content: it may have been put
    by another process, or found by a cache fast path), then the store directory (their entries),
    the pinned binary and its sha256 record, bin/ (their entries), and the root (the entries of
    store/ and bin/). Each path is synced once per process; a blob new to this process re-syncs
    the store directory and the root.
    A blob counts as synced only after its content, store/ and the root all synced (quick check of
    round 5): if a directory fsync raises, the next call with the same blobs syncs them again."""
    new = [h for h in blobs if (root, h) not in _SYNCED]
    for h in new:
        _fsync_path(store_path(root, h))
    sd = os.path.join(root, STORE)
    if new and os.path.isdir(sd):
        fsync_dir(sd)
    bdir = os.path.join(root, "bin")
    for p in (os.path.join(bdir, "evo_boids"), os.path.join(bdir, "evo_boids.sha256"), bdir):
        if (root, p) not in _SYNCED and os.path.exists(p):
            _fsync_path(p)
            _SYNCED.add((root, p))
    if new or (root, root) not in _SYNCED:
        fsync_dir(root)
        _SYNCED.add((root, root))
    _SYNCED.update((root, h) for h in new)


def replay_prereqs(root, d, done, put=True):
    """replay_deps' problems only."""
    return replay_deps(root, d, done, put)[0]


def replay_deps(root, d, done, put=True):
    """What a verified replay of this finished cell needs (review round 4, P1-2), checked before
    anything of it is deleted: the pinned binary is the one the cell ran (done.json's hash); every
    scoring tool the cell ran (done.json tools_sha256: a cell from before tool pinning has none)
    is in the store by content hash, put there from the pinned tools if they still are that
    version; every snapshot the arena read (its manifest's hash, which must be the plan's
    registered one) is in the store, put there from its registered path if that file still has
    that content; the engine command is recorded. -> (problems, [] if a replay can be verified;
    the store blobs it needs, for durability_barrier)."""
    probs = []
    c = done.get("cell") or {}
    bh = done.get("binary_sha256")
    if not bh:
        probs.append("done.json records no binary hash")
    elif _pinned_binary_sha(root) != bh:
        probs.append(f"the pinned binary is not the {bh[:12]} this cell ran")
    if not isinstance(done.get("command"), list) or not done["command"]:
        probs.append("done.json records no engine command")
    tools = done.get("tools_sha256") or {}
    want = []
    for f in SCORING_TOOLS:
        h = tools.get(f)
        if not h:
            probs.append(f"done.json records no {f} hash (a cell from before tool pinning)")
        else:   # from the pinned copy, or the copy this process runs (a cell worker runs the pinned one)
            want.append((f"{f} {h[:12]}", h, [os.path.join(root, "tools", f), os.path.join(HERE, f)]))
    try:
        man = json.load(open(os.path.join(d, "arena.manifest.json")))
    except (OSError, ValueError) as e:
        probs.append(f"arena.manifest.json unreadable ({e})")
        man = {}
    for role in ("resident", "invader"):
        if not c.get(role):
            continue
        h, reg = (man.get(role) or {}).get("sha256"), c.get(f"{role}_sha256")
        if not h:
            probs.append(f"the arena manifest records no {role} snapshot hash")
        elif reg and reg != h:
            probs.append(f"the arena read {role} {h[:12]}, the plan registered {reg[:12]}")
        else:
            want.append((f"{role} snapshot {h[:12]} ({c[role]})", h, [c[role]]))
    for what, h, srcs in want:
        if store_has(root, h):
            continue
        ok = False
        for s in srcs:
            if put and os.path.isfile(s):
                try:
                    store_put(root, s, h)
                    ok = True
                    break
                except (ProvenanceError, OSError):
                    pass
        if not ok:
            probs.append(f"{what}: no copy of that version (stored, pinned or at its path)")
    return probs, [h for _, h, _ in want]


# ------------------------------------------------------------------- pruning
class PruneError(Exception):
    pass


def _is_ckpt(f):
    """end.json or a periodic end.<frame>.json the engine wrote."""
    p = f.split(".")
    return f == "end.json" or (len(p) == 3 and p[0] == "end" and p[2] == "json" and p[1].isdigit())


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def check_finished(d, done):
    """Is a finished cell's score valid (before anything of it is deleted)? -> problems, [] if ok:
    done.json is this cell's record (cell.json agrees), every recorded output still on disk matches
    its hash, and score.json reached the cell's last step with the derivation checks passed, on
    these very arena and births files, with a finite score (or a recorded extinction)."""
    if done.get("schema") != SCHEMA:
        return [f"done.json schema {done.get('schema')!r}"]
    bad = []
    c = done.get("cell") or {}
    try:
        if json.load(open(os.path.join(d, "cell.json"))) != c:
            bad.append("cell.json differs from done.json's cell")
    except (OSError, ValueError) as e:
        bad.append(f"cell.json unreadable ({e})")
    out = done.get("outputs") or {}
    pr = done.get("pruned") or {}
    for f in ("arena.json", "arena.manifest.json", "run.csv", BIRTHS, "end.json", "score.json"):
        if f not in out:
            bad.append(f"done.json records no {f}")
    for f, h in out.items():
        p = os.path.join(d, f)
        if os.path.exists(p):
            if invlib.sha256_file(p) != h:
                bad.append(f"{f} does not match done.json")
        elif f not in (pr.get("removed") or {}) and f not in (pr.get("compressed") or {}):
            bad.append(f"{f} missing")
    try:
        sc = json.load(open(os.path.join(d, "score.json")))
        last = sc["points"][-1]
        if sc["derivation"].get("ok") is not True or sc["derivation"] != done.get("derivation"):
            bad.append("score derivation not ok, or not the one done.json recorded")
        if last["steps"] != c.get("steps"):
            bad.append(f"score read at {last['steps']} steps, the cell asked for {c.get('steps')}")
        if sc.get("arena_sha256") != out.get("arena.json") or sc.get("births_sha256") != out.get(BIRTHS):
            bad.append("score.json scored other arena / births files")
        if not (_finite(last["score"]) or (last.get("extinct") is True and last["score"] is None)):
            bad.append(f"end score {last['score']!r} is neither a finite number nor a recorded extinction")
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
        bad.append(f"score.json unreadable ({e!r})")
    return bad


def gzip_file(src, dst):
    """Lossless, byte-reproducible gzip of src (level 9, mtime 0, no file name) -> its SHA-256."""
    with open(src, "rb") as f:
        gz = gzip.compress(f.read(), compresslevel=9, mtime=0)
    tmp = dst + ".tmp"
    with open(tmp, "wb") as f:
        f.write(gz)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, dst)
    return hashlib.sha256(gz).hexdigest()


def gunzip_sha256(path):
    h = hashlib.sha256()
    with gzip.open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def prune_plan(d, done):
    """Prepare pruning a finished cell, deleting nothing: hash every checkpoint to go against its
    record (arena.json, end.json; an end.<frame>.json is a recorded intermediate or the last step's
    duplicate of end.json) and gzip the birth log, verified by decompressing and re-hashing.
    -> the 'pruned' record for done.json. Raises PruneError on any mismatch."""
    out = done["outputs"]
    inter = done.get("intermediate_checkpoints") or {}
    removed = {}
    for f in sorted(os.listdir(d)):
        if f == "arena.json" or _is_ckpt(f):
            h = invlib.sha256_file(os.path.join(d, f))
            want = out.get(f) if f in ("arena.json", "end.json") else inter.get(f, out.get("end.json"))
            if h != want:
                raise PruneError(f"{f}: sha256 {h[:12]} is not the recorded {str(want)[:12]}")
            removed[f] = h
    for f in ("arena.json", "end.json"):
        if f not in removed:
            raise PruneError(f"{f} missing")
    src, gz = os.path.join(d, BIRTHS), os.path.join(d, BIRTHS_GZ)
    if not os.path.exists(src) or invlib.sha256_file(src) != out.get(BIRTHS):
        raise PruneError(f"{BIRTHS} missing or not the recorded one")
    gz_sha = gzip_file(src, gz)
    if gunzip_sha256(gz) != out[BIRTHS]:
        raise PruneError(f"{BIRTHS_GZ} does not decompress to the recorded birth log")
    root = os.path.dirname(os.path.dirname(os.path.abspath(d)))
    freed = sum(os.path.getsize(os.path.join(d, f)) for f in removed) + os.path.getsize(src) - os.path.getsize(gz)
    return {"schema": PRUNE_SCHEMA, "utc": now(), "removed": removed,
            "compressed": {BIRTHS: {"file": BIRTHS_GZ, "sha256": gz_sha, "format": "gzip level 9, mtime 0"}},
            "freed_bytes": freed,
            "replay": f"python3 -I {root}/tools/run.py --root {root} --replay {os.path.basename(d)} --out EMPTY_DIR"}


def prune_apply(d, done):
    """Delete what done.json's 'pruned' record lists (each file re-hashed first) and the plain
    birth log once its gzip is in place. Idempotent: finishes an interrupted prune. -> bytes freed."""
    pr = done["pruned"]
    freed = 0
    for f, h in pr["removed"].items():
        p = os.path.join(d, f)
        if os.path.exists(p):
            if invlib.sha256_file(p) != h:
                raise PruneError(f"{f} is not the file the prune recorded; not deleting it")
            freed += os.path.getsize(p)
            os.remove(p)
    for f, rec in pr.get("compressed", {}).items():
        p = os.path.join(d, f)
        if os.path.exists(p):
            gz = os.path.join(d, rec["file"])
            if not os.path.exists(gz) or invlib.sha256_file(gz) != rec["sha256"]:
                raise PruneError(f"{rec['file']} missing or changed; keeping {f}")
            if invlib.sha256_file(p) != done["outputs"][f]:
                raise PruneError(f"{f} is not the recorded file; not deleting it")
            freed += os.path.getsize(p)
            os.remove(p)
    return freed


def strip_attempt(d):
    """A failed attempt (<id>.attempt<N>/) loses its checkpoints and scratch files (they replay;
    its logs stay) -> bytes freed."""
    freed = 0
    for f in os.listdir(d):
        p = os.path.join(d, f)
        if f == "tmp" and os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        elif f == "arena.json" or _is_ckpt(f) or f.endswith(".tmp"):
            freed += os.path.getsize(p)
            os.remove(p)
    return freed


def prune_finished(root, log):
    """Prune every finished cell under DIR/cells not pruned yet, through finalize() (the protocol
    new cells use: the score check, the replay prerequisites, flush, durable done.json, delete);
    finish interrupted prunes after revalidating them (finish_prune); check that every cell pruned
    earlier still has its replay prerequisites; strip failed attempts.
    A cell whose replay provenance cannot be established (e.g. from before tool pinning) keeps its
    checkpoints: listed, not an error. -> [(cell, problems)]: integrity problems (a cell that fails
    its score check, a broken prune record, a pruned cell whose replay can no longer be verified);
    those cells are left as they are and the caller should stop."""
    cdir = os.path.join(root, "cells")
    names = sorted(os.listdir(cdir)) if os.path.isdir(cdir) else []
    n_new = n_old = n_fin = n_att = freed = 0
    bad, kept = [], []
    t0 = time.time()
    for k, x in enumerate(names, 1):
        d = os.path.join(cdir, x)
        if k % 5000 == 0:
            log(f"prune sweep: {k}/{len(names)} entries")
        try:
            if ".attempt" in x:
                b = strip_attempt(d)
                n_att += b > 0
                freed += b
                continue
            dp = os.path.join(d, "done.json")
            if not os.path.exists(dp):
                continue
            done = json.load(open(dp))
            if "pruned" in done:
                if prune_leftovers(d, done):
                    freed += finish_prune(root, d, done)
                    n_fin += 1
                else:
                    probs = replay_prereqs(root, d, done)
                    if probs:
                        bad.append((x, ["pruned earlier, and its replay can no longer be verified: " + "; ".join(probs)]))
                    n_old += 1
                continue
            freed += finalize(root, d, done, prune=True)[0]
            n_new += 1
        except ProvenanceError as e:
            kept.append((x, str(e)))
        except (PruneError, OSError, ValueError, KeyError) as e:
            bad.append((x, [str(e) if isinstance(e, PruneError) else repr(e)]))
    log(f"prune sweep: {n_new} finished cells pruned now, {n_old} already pruned, {n_fin} interrupted prunes "
        f"finished, {n_att} failed attempts stripped, {freed / 1e6:.1f} MB freed, {len(kept)} kept unpruned "
        f"(replay provenance not established), {len(bad)} cell(s) with problems (left untouched), "
        f"{time.time() - t0:.0f} s")
    for x, why in kept[:10]:
        log(f"  KEPT (checkpoints stay) {x}: {why[:400]}")
    for x, probs in bad[:10]:
        log(f"  NOT PRUNED {x}: {'; '.join(probs)[:400]}")
    return bad


# -------------------------------------------------------------------- replay
def replay_cell(root, cid, out):
    """Child process (the pinned copy): rebuild, rerun and rescore finished cell cid in `out` and
    compare every recorded hash. -> 0 all identical, 8 a mismatch, 2 / 3-6 refusals / failures."""
    d = os.path.join(root, "cells", cid)
    done = json.load(open(os.path.join(d, "done.json")))
    c = dict(done["cell"])
    for f in SCORING_TOOLS:
        if invlib.sha256_file(os.path.join(HERE, f)) != (done.get("tools_sha256") or {}).get(f):
            print(f"{os.path.join(HERE, f)} is not the {f} this cell ran with", file=sys.stderr)
            return 2
    exe = os.path.join(root, "bin", "evo_boids")
    if invlib.sha256_file(exe) != done["binary_sha256"]:
        print(f"{exe} is not the binary this cell ran with", file=sys.stderr)
        return 2
    # the snapshots: the very content the arena read (its manifest's hash); from the registered path
    # if it still has it, else from the root's store (review round 4)
    man0 = json.load(open(os.path.join(d, "arena.manifest.json")))
    snap_from = {}
    for role in ("resident", "invader"):
        if not c.get(role):
            continue
        h = (man0.get(role) or {}).get("sha256") or c.get(f"{role}_sha256")
        if c.get(f"{role}_sha256") and h != c[f"{role}_sha256"]:
            print(f"the arena read {role} {h[:12]}, the plan registered {c[role + '_sha256'][:12]}", file=sys.stderr)
            return 5
        if os.path.isfile(c[role]) and invlib.sha256_file(c[role]) == h:
            snap_from[role] = "registered path"
        elif store_has(root, h):
            c[role] = store_path(root, h)
            snap_from[role] = "store"
        else:
            print(f"SNAPSHOT {role} {h[:12]} is neither at {c[role]} nor in {root}/{STORE}", file=sys.stderr)
            return 5
    out = os.path.abspath(out)
    os.makedirs(out, exist_ok=True)
    if [f for f in os.listdir(out) if f != REPLAY_TOOLS]:
        print(f"--out {out} must be an empty directory", file=sys.stderr)
        return 2
    os.nice(19 - os.nice(0))
    rc, x = execute(c, out, exe)
    if rc:
        return rc
    rec, pr = done["outputs"], done.get("pruned") or {}

    def sha(f):
        p = os.path.join(out, f)
        return invlib.sha256_file(p) if os.path.exists(p) else None
    # the binary is checked by its hash above; its path is the root's (a copied root has another)
    checks = {"engine command (arguments)": x["cmd"][1:] == done["command"][1:]}
    for f in ("arena.json", "end.json", BIRTHS, "score.json"):
        checks[f] = sha(f) == rec[f]
    for f, h in sorted((done.get("intermediate_checkpoints") or {}).items()):
        checks[f] = sha(f) == h
    for f, h in sorted((pr.get("removed") or {}).items()):   # e.g. the last step's duplicate of end.json
        checks.setdefault(f, sha(f) == h)

    def man_key(p):
        m = json.load(open(p))
        m.pop("created_utc", None)
        m["output"] = {"sha256": m["output"]["sha256"]}
        if m.get("binary"):
            m["binary"] = {"sha256": m["binary"]["sha256"]}
        for role in snap_from:   # a snapshot read from the store has the store's path (same content)
            if snap_from[role] == "store" and isinstance(m.get(role), dict):
                m[role] = {k_: v for k_, v in m[role].items() if k_ != "path"}
        return m
    checks["arena.manifest.json (but its time stamp, output and binary paths)"] = \
        man_key(os.path.join(out, "arena.manifest.json")) == man_key(os.path.join(d, "arena.manifest.json"))

    def rows(p):
        with open(p) as f:
            return [{k: v for k, v in r.items() if k not in TIMING_COLS} for r in csv.DictReader(f)]
    checks["run.csv (but its timing columns)"] = rows(os.path.join(out, "run.csv")) == rows(os.path.join(d, "run.csv"))
    ok = all(checks.values())
    invlib.write_json_atomic(os.path.join(out, "replay.json"), {
        "schema": "finfolk.invasion.replay/1", "utc": now(), "root": root, "cell": cid, "identical": ok,
        "checks": checks, "binary_sha256": done["binary_sha256"],
        "tools_sha256": {f: done["tools_sha256"][f] for f in SCORING_TOOLS},
        "tools_from": ("the store or the pinned copies (rebuilt in replay_tools, run by a store-capable driver)"
                       if os.path.basename(HERE) == REPLAY_TOOLS else "the pinned tools"), "snapshots_from": snap_from})
    for k, v in checks.items():
        print(f"{'same     ' if v else 'DIFFERENT'} {k}")
    print(f"replay {cid}: {'identical' if ok else 'MISMATCH'} ({sum(checks.values())}/{len(checks)} checks) -> {out}")
    return 0 if ok else 8


# ---------------------------------------------------------------- disk guard
def disk_guards(specs, root):
    """--disk-min values -> [(path, MB)] (see the header for the defaults)."""
    if specs and [s.lower() for s in specs] == ["none"]:
        return []
    if not specs:
        return [("/", 10240), ("/mnt/c", 6000)] if os.path.ismount("/mnt/c") else [(root, 1024)]
    out = []
    for s in specs:
        path, sep, mb = s.rpartition(":")
        if not sep or not path or not mb.isdigit():
            raise SystemExit(f"--disk-min {s!r}: expected PATH:MB (or 'none')")
        out.append((path, int(mb)))
    return out


def disk_free_mb(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize // (1 << 20)


def _free_or(path):
    try:
        return disk_free_mb(path)
    except OSError:
        return "unreadable"


def disk_problem(guards):
    """None when every guarded filesystem has its free space, else the reason (fail closed)."""
    for path, need in guards:
        try:
            have = disk_free_mb(path)
        except OSError as e:
            return f"the free space of {path} is unreadable ({e.strerror or e}): fail closed"
        if have < need:
            return f"{path} has {have} MB free, below the disk guard's {need} MB"
    return None


def check_schedule(files, start_frame, steps, every):
    """The periodic checkpoints a run with --checkpoint-every `every` must have left: one at every
    start_frame + m x every (m = 1 .. steps // every; the last may coincide with the end). The
    engine reports a failed periodic write on stderr and carries on, and the scorer reads
    whichever checkpoints exist, so a gap would silently move a window's read. -> missing frames."""
    if not every:
        return []
    have = set()
    for f in files:
        p = f.split(".")
        if len(p) == 3 and p[0] == "end" and p[2] == "json" and p[1].isdigit():
            have.add(int(p[1]))
    return [start_frame + m * every for m in range(1, steps // every + 1) if start_frame + m * every not in have]


def verify_done(d):
    """A finished cell's outputs still match done.json: a pruned file is not checked (its hash is
    the replay's target), a gzipped one by its gzip's recorded hash."""
    done = json.load(open(os.path.join(d, "done.json")))
    pr = done.get("pruned") or {}
    removed, comp = pr.get("removed") or {}, pr.get("compressed") or {}
    bad = []
    for f, h in done["outputs"].items():
        if f in removed:
            continue
        p, want = os.path.join(d, f), h
        if f in comp:
            p, want = os.path.join(d, comp[f]["file"]), comp[f]["sha256"]
        if not os.path.exists(p) or invlib.sha256_file(p) != want:
            bad.append(f)
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
                    help="replace DIR/tools with the current tools/invasion sources (the pinned versions go into "
                         "DIR/store first; refused if a finished cell needs a version the store lacks)")
    ap.add_argument("--update-runner", action="store_true",
                    help="replace only the pinned run.py (the cell finalization and replay driver); the scoring "
                         "tools (invlib, arena, score) every cell ran with stay pinned")
    ap.add_argument("--prune", action="store_true",
                    help="delete each scored cell's arena / end / periodic checkpoints (they replay exactly), "
                         "keep its birth log gzipped; at start, prune the finished cells not pruned yet")
    ap.add_argument("--prune-finished", action="store_true", help="only prune the finished cells (no plan needed)")
    ap.add_argument("--replay", metavar="CELL_ID", help="rerun a finished cell into --out and compare every hash")
    ap.add_argument("--out", help="--replay: an empty directory for the replayed files")
    ap.add_argument("--disk-min", action="append", metavar="PATH:MB",
                    help="disk guard: stop admitting cells when PATH has less than MB free (repeatable; "
                         "'none' disables; default on WSL / 10240 and /mnt/c 6000, else DIR 1024)")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)

    if a.status:
        cdir = os.path.join(root, "cells")
        ids = [x for x in os.listdir(cdir) if ".attempt" not in x] if os.path.isdir(cdir) else []
        n_done = sum(1 for x in ids if os.path.exists(os.path.join(cdir, x, "done.json")))
        print(f"{root}: {n_done} done of {len(ids)} started")
        return 0
    if a.replay:
        if not a.out:
            ap.error("--replay needs --out EMPTY_DIR")
        out = os.path.abspath(a.out)
        if os.path.isdir(out) and os.listdir(out):
            print(f"--out {out} must be an empty directory", file=sys.stderr)
            return 2
        done = json.load(open(os.path.join(root, "cells", a.replay, "done.json")))
        need = {f: (done.get("tools_sha256") or {}).get(f) for f in SCORING_TOOLS}
        tdir = os.path.join(root, "tools")
        pinned = {f: invlib.sha256_file(os.path.join(tdir, f)) if os.path.isfile(os.path.join(tdir, f)) else None
                  for f in SCORING_TOOLS}
        pinned_run = os.path.join(tdir, "run.py")
        # review round 5: every snapshot role is checked by the hash of what the arena read (its manifest),
        # registered or not; a path-only legacy cell used to pass this vacuously and get an old pinned driver
        # that cannot read the store
        cell = done["cell"]
        try:
            man0 = json.load(open(os.path.join(root, "cells", a.replay, "arena.manifest.json")))
        except (OSError, ValueError):
            man0 = {}

        def at_path(r):
            h = (man0.get(r) or {}).get("sha256") or cell.get(f"{r}_sha256")
            return bool(h) and os.path.isfile(cell[r]) and invlib.sha256_file(cell[r]) == h
        snaps_ok = all(at_path(r) for r in ("resident", "invader") if cell.get(r))
        if pinned == need and snaps_ok and os.path.exists(pinned_run) and "def replay_cell(" in open(pinned_run).read():
            runner = pinned_run   # the pinned copy, as the cell ran (nothing needs the store)
        else:
            # the cell ran scoring tools that are no longer pinned (--update-tools since), or a snapshot
            # left its path: its version set comes back from the store (or the pinned copy, when that is
            # the version) by content hash, with this run.py - store-capable - as the replay driver (the
            # run.py version is not part of the check)
            srcs = {f: (store_path(root, h) if store_has(root, h) else
                        os.path.join(tdir, f) if h and pinned.get(f) == h else None) for f, h in need.items()}
            missing = [f"{f} {str(need[f])[:12]}" for f, s in srcs.items() if s is None]
            if missing:
                print(f"cannot replay {a.replay}: no stored copy of {', '.join(missing)}", file=sys.stderr)
                return 2
            rdir = os.path.join(out, REPLAY_TOOLS)
            os.makedirs(rdir, exist_ok=True)
            for f, s in srcs.items():
                shutil.copyfile(s, os.path.join(rdir, f))
            shutil.copyfile(os.path.abspath(__file__), os.path.join(rdir, "run.py"))
            runner = os.path.join(rdir, "run.py")
        return subprocess.call([sys.executable, "-I", runner, "--root", root, "--_replay", a.replay, out])
    if not a.prune_finished and not (a.plan and a.binary):
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
    log_lost = [0]   # lines a failing write (a full disk: ENOSPC / EIO) could not record

    def log(msg):
        # never raises: the clean-stop paths log, and they must work when the disk is full (review round 4)
        line = f"{now()} {msg}"
        for out in (sys.stdout, logf):
            try:
                out.write(line + "\n")
                out.flush()
            except (OSError, ValueError):
                log_lost[0] += 1

    if a.prune_finished:
        return 1 if prune_finished(root, log) else 0
    guards = disk_guards(a.disk_min, root)

    # pin the binary
    pinned = os.path.join(root, "bin", "evo_boids")
    want = pin_binary(root, a.binary)
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
        fresh = not os.path.isdir(tdir)
        if fresh or a.update_tools or a.update_runner:
            files = TOOL_FILES if fresh or a.update_tools else ("run.py",)
            if not fresh:
                # review round 4, P1-2: an update must not discard a version a finished cell needs (its
                # replay rebuilds that version set from the store): the pinned copies go into the store
                # first, and every finished cell's scoring-tool versions must be there before anything
                # is replaced
                try:
                    for f in TOOL_FILES:
                        if os.path.isfile(os.path.join(tdir, f)):
                            store_put(root, os.path.join(tdir, f))
                    lost = needed_versions_missing(root)
                except (OSError, ProvenanceError) as e:
                    print(f"--update-tools: could not keep the pinned versions in {root}/{STORE} ({e}): "
                          "nothing replaced", file=sys.stderr)
                    return 2
                if lost:
                    print(f"--update-tools refused: finished cells need tool versions the store lacks: {lost[:5]}",
                          file=sys.stderr)
                    return 2
            os.makedirs(tdir, exist_ok=True)
            for f in files:
                shutil.copy2(os.path.join(HERE, f), os.path.join(tdir, f))
            log(f"tools pinned in {tdir}: " + " ".join(f"{f}={src[f][:10]}" for f in files)
                + ("" if fresh else f" (the previous versions kept in {root}/{STORE})"))
        else:
            pin = {f: invlib.sha256_file(os.path.join(tdir, f)) for f in TOOL_FILES}
            if pin != src:
                log(f"note: tools/invasion differs from the pinned {tdir}; running the pinned copy "
                    f"(--update-tools / --update-runner to replace it)")
    cell_runner = os.path.join(tdir, "run.py")
    if a.prune:
        if "def replay_prereqs(" not in open(cell_runner).read():
            print(f"--prune: the pinned {cell_runner} predates the replay-provenance checks before pruning (review "
                  "round 4; its cells would delete checkpoints unchecked); start once with --update-runner",
                  file=sys.stderr)
            return 2
        log("pruning on: a scored cell's arena / end / periodic checkpoints are deleted (replay: run.py --root "
            f"{root} --replay CELL_ID --out EMPTY_DIR), its birth log kept as {BIRTHS_GZ}")
        if prune_finished(root, log):
            log("stopped: finished cells with problems (above) were not pruned; look before resuming")
            return 1
    log("disk guard: " + (", ".join(f"{p} >= {mb} MB (now {_free_or(p)})" for p, mb in guards) or "off"))

    cells = load_plan(a.plan)
    hashed, changed = {}, []
    for c in cells:   # every registered snapshot (each file hashed once) before anything is admitted
        changed += snapshot_problems(c, hashed)
    if changed:
        print("snapshots changed since planning (re-plan, or restore them): " + "; ".join(sorted(set(changed))),
              file=sys.stderr)
        return 2
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

    def kill_running(why):
        # every cell worker leads its own process group (start_new_session), which its engine
        # joins: signal the whole group, reap the worker, and wait until the group is empty, so
        # no engine keeps writing after the lock is released
        n = len(running)
        for p, _, _ in list(running.values()):
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for p, _, _ in list(running.values()):
            p.wait()
            stop_group(p.pid, log)
        running.clear()
        log(f"{why}: terminated {n} running cells and their engines")

    def terminate(signum, frame):
        kill_running(f"signal {signum}")
        sys.exit(130)
    signal.signal(signal.SIGINT, terminate)
    signal.signal(signal.SIGTERM, terminate)

    queue = list(todo)
    n_done = 0
    mem_bad = 0      # consecutive unreadable memory polls
    rss_mb = 0       # largest engine RSS seen this session (the per-cell reserve)
    t_start = time.time()
    n_before = len(cells) - len(todo)
    persist_failed = []   # progress / STOP writes that failed (a full disk): the state stays in memory

    def progress(state="running"):
        """DIR/progress.json: done / total, this session's rate and the projected finish. Never raises
        (review round 4: a full disk must not break the clean-stop path)."""
        el = time.time() - t_start
        rate = n_done / el * 3600 if el > 0 else 0.0
        left = len(cells) - n_before - n_done
        eta = (datetime.datetime.now() + datetime.timedelta(hours=left / rate)).isoformat(timespec="seconds") \
            if rate > 0 and left > 0 else None
        try:
            invlib.write_json_atomic(os.path.join(root, "progress.json"), {
                "state": state, "updated": now(), "plan": os.path.abspath(a.plan), "total": len(cells),
                "done": n_before + n_done, "failed": failed, "running": len(running), "queued": len(queue),
                "workers": a.workers, "session_cells_per_hour": rate, "projected_finish": eta,
                "prune": a.prune, "stop_reason": stop_reason,
                "disk_free_mb": {p: _free_or(p) for p, _ in guards}, "disk_min_mb": {p: mb for p, mb in guards}})
        except OSError as e:
            if not persist_failed:
                log(f"warning: progress.json not written ({e}); carrying on (the state is in memory)")
            persist_failed.append("progress.json")

    def stop_admission(reason, persist=True):
        """Stop admitting cells: in memory FIRST, so admission stops even if nothing can be written;
        then (best effort) the reason into DIR/STOP; running cells finish; exit 75."""
        nonlocal stop_reason
        stop_reason = reason
        if persist:
            try:
                invlib.write_atomic(os.path.join(root, "STOP"), f"{now()} {reason}\n")
                where = f"wrote the reason to {root}/STOP"
            except OSError as e:
                persist_failed.append("STOP")
                where = f"could NOT write {root}/STOP ({e}); stopping anyway"
            log(f"{reason}; {where}; no new cells; waiting for {len(running)}")
        progress()

    progress()
    try:
        while queue or running:
            # reap
            for pid in list(running):
                p, cid, t0 = running[pid]
                rc = p.poll()
                if rc is None:
                    continue
                del running[pid]
                dt = time.time() - t0
                try:
                    attempts.write(f"{now()}\t{cid}\t{rc}\t{dt:.1f}\n")
                    attempts.flush()
                except OSError:
                    persist_failed.append("attempts.tsv")
                if rc == 0 and os.path.exists(os.path.join(root, "cells", cid, "done.json")):
                    n_done += 1
                    try:
                        kb = json.load(open(os.path.join(root, "cells", cid, "done.json")))["timing"]["engine_maxrss_kb"]
                        rss_mb = max(rss_mb, kb // 1024)
                    except (OSError, ValueError, KeyError):
                        pass
                    if n_done % 10 == 0 or not queue:
                        log(f"done {n_done}/{len(todo)} (last {cid}, {dt:.0f}s)")
                else:
                    failed.append(cid)
                    try:
                        err = open(os.path.join(root, "cells", cid, "cell.stderr.log")).read()[-400:]
                    except OSError as e:
                        err = f"(cell.stderr.log unreadable: {e})"
                    log(f"FAILED {cid} (exit {rc}): {err.strip()}")
                progress()
            # admission
            if os.path.exists(os.path.join(root, "STOP")) and stop_reason is None:
                stop_admission("STOP", persist=False)
                log(f"STOP file: no new cells; waiting for {len(running)}")
            admit = stop_reason is None and not failed
            while admit and queue and len(running) < a.workers:
                why = disk_problem(guards)   # before each cell
                if why:
                    stop_admission(f"disk guard: {why}")
                    admit = False
                    break
                head = mem_headroom_mb()
                if head is None:
                    mem_bad += 1
                    if mem_bad == 1:
                        log("memory reading unavailable or malformed: admitting nothing (fail closed)")
                    if not running and mem_bad >= 20:
                        log("memory reading still unavailable with nothing running: exiting")
                        return 2
                    break
                mem_bad = 0
                if head < a.mem_min_mb + max(150, rss_mb + 64):
                    break
                spec = queue.pop(0)
                d = os.path.join(root, "cells", spec["id"])
                try:
                    if os.path.exists(d):
                        k = 1
                        while os.path.exists(f"{d}.attempt{k}"):
                            k += 1
                        os.rename(d, f"{d}.attempt{k}")
                        if a.prune:
                            strip_attempt(f"{d}.attempt{k}")
                    os.makedirs(d)
                    invlib.write_json_atomic(os.path.join(d, "cell.json"), spec)
                    tmpd = os.path.join(d, "tmp")
                    os.makedirs(tmpd)
                    err = open(os.path.join(d, "cell.stderr.log"), "w")
                except OSError as e:
                    # a write failure while admitting (e.g. ENOSPC): the cell goes back to the queue (its
                    # partial directory becomes an attempt on resume) and admission stops cleanly
                    queue.insert(0, spec)
                    stop_admission(f"admission failed: {e}")
                    admit = False
                    break
                p = subprocess.Popen([sys.executable, "-I", cell_runner, "--root", root, "--_cell", spec["id"]]
                                     + (["--prune"] if a.prune else []), stdout=err, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True, preexec_fn=die_with_parent,
                                     env=dict(os.environ, TMPDIR=tmpd, TMP=tmpd, TEMP=tmpd))
                err.close()
                running[p.pid] = (p, spec["id"], time.time())
            if not admit and not running:
                break
            # Up to 0.5 s, but back as soon as a cell worker exits: a finished cell's slot is refilled at
            # once rather than at the next half-second tick, which idled a worker ~0.25 s per cell
            # (~2% of a 4-worker bank; docs/throughput.md). Scheduling only: no output changes.
            t_wait = time.monotonic() + 0.5
            while time.monotonic() < t_wait and all(p.poll() is None for p, _, _ in running.values()):
                time.sleep(0.02)
    except BaseException as e:
        # guaranteed cleanup (review round 4): whatever breaks the loop, no cell worker or engine outlives
        # the runner (terminate() has already done this for a signal)
        if running and not isinstance(e, SystemExit):
            kill_running(f"runner error {e!r}")
        raise

    if persist_failed:
        log(f"note: {len(persist_failed)} state write(s) failed this session ({sorted(set(persist_failed))}); "
            f"{log_lost[0]} log line(s) lost")
    if failed:
        progress("stopped: failed cell(s)")
        log(f"stopped: {len(failed)} failed cell(s): {failed[:5]}")
        return 1
    if stop_reason:
        msg = "stopped by STOP file" if stop_reason == "STOP" else f"stopped by the {stop_reason}"
        progress(msg)
        log(msg)
        return 75
    progress("all done")
    log(f"all {len(cells)} cells done")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 5 and sys.argv[3] == "--_cell":
        sys.exit(run_cell(os.path.abspath(sys.argv[2]), sys.argv[4], prune="--prune" in sys.argv[5:]))
    if len(sys.argv) >= 6 and sys.argv[3] == "--_replay":
        sys.exit(replay_cell(os.path.abspath(sys.argv[2]), sys.argv[4], sys.argv[5]))
    sys.exit(main())

#!/usr/bin/env python3
"""run.py: the Red Queen tournament runner. Resumable, bounded, failure-propagating.

    run.py --plan PLAN.jsonl --root STUDY --binary EVO_BOIDS [--workers N] [--mem-min-mb M]
           [--disk-min PATH:MB ...] [--chunk-size N] [--retries N] [--quick-resume] [--update-tools]
    run.py --root STUDY --status
    run.py --root STUDY --pack                       pack every finished cell now (no plan needed)
    run.py --root STUDY --replay CELL_ID --out EMPTY_DIR

PLAN.jsonl is plan.py's output (schema finfolk.redqueen.plan/1): one assay cell per line. A
cell runs cell.py's procedure (common checkpoint or native prey, the transplant, the assay,
the score) in STUDY/work/<id>/ and leaves bundle.json (deterministic) and done.json; the
runner packs finished cells into verified chunks (store.py) and deletes their working files.

STUDY/
  bin/evo_boids (+ .sha256)    the pinned engine (a different binary for the same root is refused)
  tools/                       the pinned copy of tools/redqueen/*.py every cell runs from
  env.json                     the Python and platform of the first start (a later start that
                               differs is logged), the build manifest if given (--build-manifest)
  plans/<sha256>.jsonl         every plan this root has run
  work/<id>/                   cells in flight, and finished cells not yet packed
  attempts/<id>.attempt<N>/    failed attempts (checkpoints stripped, logs kept)
  chunks/, store/              see store.py
  runner.log, attempts.tsv, progress.json, STOP, .runner.lock

Rules (the first study's runner, tools/invasion/run.py, adapted; workers are plain
subprocesses, never multiprocessing, so Python 3.12 to 3.14 behave the same):
  * up to --workers (1..64) cells at once, each one worker process (the pinned run.py) leading
    its own process group, whose engine calls join it; everything at nice 19; one runner per root
    (flock STUDY/.runner.lock);
  * pinning: the binary (copied to bin/ and into the store), the tools (copied to tools/, every
    version into the store; --update-tools replaces the pinned copy, older versions stay in the
    store for replays), the plan (plans/<sha256>.jsonl);
  * sources: every registered snapshot / template a cell to run reads is hashed before anything
    is admitted (one changed file refuses the batch, exit 2) and again by the worker before its
    build (exit 5). A finished cell's sources go into the store (hard links where possible), and
    its common manifest (gzip), before its done.json, so a replay never depends on the archive;
  * durable completion: bundle.json, then done.json, each fsync'd and renamed with a directory
    fsync; the cell's checkpoints are deleted only after both (their hashes are in the bundle);
  * resume: a packed cell (in the chunk index) or a finished one (done.json whose bundle matches)
    is skipped, after checking its plan row is unchanged (row_sha256); an unfinished working
    directory is moved to attempts/ and the cell rerun from scratch;
  * failures: a failed cell stops admission, running cells finish, exit 1 - except a cell whose
    worker or engine was killed by a signal (an out-of-memory kill, say), which is requeued up to
    --retries times (default 0) in this session;
  * STOP: the file STUDY/STOP stops admission; running cells finish and are packed; exit 75;
  * memory, fail closed: a cell is admitted only while min(MemAvailable, every cgroup v2
    memory.max - memory.current up the tree) >= --mem-min-mb + the largest per-cell RSS seen
    (worker + engine) + 64 MB (at least 150 MB). An unreadable reading admits nothing (exit 2 if it
    stays so with nothing running). Test hooks: RQ_MEMINFO, RQ_PROC_CGROUP, RQ_CGROUP_ROOT;
  * disk, fail closed: before each admission every --disk-min PATH:MB must have MB free (default
    on WSL: / 10240 and /mnt/c 6000; elsewhere the root 1024; 'none' disables); below it the runner
    takes the STOP path with the reason in STUDY/STOP;
  * packing: whenever --chunk-size finished cells are waiting, and at every exit, they are packed
    (store.pack: written, verified, committed, then deleted); at start store.recover() finishes or
    undoes an interrupted pack and every committed chunk is re-hashed (--quick-resume: sizes only);
  * signals: SIGINT / SIGTERM to the runner stop every worker's process group (SIGKILL after 20 s)
    and exit 130; workers forward signals to their engine; every child has PR_SET_PDEATHSIG, so no
    engine outlives a SIGKILLed runner for long;
  * replay: --replay rebuilds one cell (packed or not) into an empty directory from the pinned
    binary, the tool versions it ran (from the store when they are no longer pinned) and its
    sources (registered path, else the store), and compares the new bundle with the recorded one
    byte for byte (replay.json; exit 0 identical, 8 different). The replayed checkpoints stay
    there: that is how a deleted state comes back.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
import resource
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rqlib  # noqa: E402
import store  # noqa: E402

PLAN_SCHEMA = "finfolk.redqueen.plan/1"
DONE_SCHEMA = "finfolk.redqueen.done/1"
REPLAY_SCHEMA = "finfolk.redqueen.replay/1"
TOOL_FILES = ("rqlib.py", "ckpt.py", "common.py", "score.py", "cell.py", "store.py", "run.py", "plan.py")
OUTPUT_TOOLS = ("rqlib.py", "ckpt.py", "common.py", "score.py", "cell.py")   # = cell.OUTPUT_TOOLS
ROW_KEYS = ("schema", "id", "kind", "prey", "predators", "template", "prey_policy", "n_prey", "sampling", "assay",
            "k", "steps", "horizons", "log_every", "checkpoint_every", "replicate", "seeds", "groups")
ROLES = ("prey", "predators", "template")
RETRYABLE = {10, -9, -15, 137, 143}
MAX_WORKERS = 64


def log_to(logf, lost):
    def log(msg):
        line = f"{rqlib.now_utc()} {msg}"
        for out in (sys.stdout, logf):
            try:
                out.write(line + "\n")
                out.flush()
            except (OSError, ValueError):
                lost[0] += 1
    return log


# ---------------------------------------------------------------- the plan
def row_sha(row):
    return rqlib.canonical_sha(row)


def load_plan(path):
    rows = []
    with open(path) as f:
        for n, ln in enumerate(f, 1):
            if not ln.strip():
                continue
            r = json.loads(ln)
            if r.get("schema") != PLAN_SCHEMA:
                raise SystemExit(f"{path}:{n}: schema {r.get('schema')!r}, expected {PLAN_SCHEMA}")
            miss = [k for k in ROW_KEYS if k not in r]
            if miss:
                raise SystemExit(f"{path}:{n}: cell {r.get('id')} lacks {miss}")
            for role in ROLES:
                if isinstance(r.get(role), dict) and r[role].get("sha256") == rqlib.SHA_PENDING:
                    raise SystemExit(f"{path}:{n}: cell {r['id']} has a pending {role} hash: a pending plan cannot "
                                     "run (build the final plan with plan.py --against)")
            rows.append(r)
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise SystemExit(f"{path}: duplicate cell ids")
    return rows


def registered_sources(cell):
    """[(role, path, sha256)] the cell reads (random predators and the fork read no donor)."""
    out = []
    for role in ROLES:
        x = cell.get(role)
        if isinstance(x, dict) and x.get("path"):
            out.append((role, x["path"], x["sha256"]))
    return out


def resolve_sources(root, cell, cache=None):
    """role -> a readable file with the registered content (the registered path, else the store)
    -> (paths, problems)."""
    cache = {} if cache is None else cache
    paths, probs = {}, []
    for role, p, want in registered_sources(cell):
        if p not in cache:
            cache[p] = rqlib.sha256_file(p) if os.path.isfile(p) else "missing"
        if cache[p] == want:
            paths[role] = p
        elif store.has(root, want):
            paths[role] = store.has(root, want)
        else:
            probs.append(f"{role} {p}: {cache[p][:12]}, registered {want[:12]}, and not in the store")
    return paths, probs


# ------------------------------------------------------------ memory, disk
def _cgroup_headroom_mb():
    root = os.environ.get("RQ_CGROUP_ROOT", "/sys/fs/cgroup")
    rel = None
    with open(os.environ.get("RQ_PROC_CGROUP", "/proc/self/cgroup")) as f:
        for ln in f:
            if ln.startswith("0::"):
                rel = ln.strip()[3:]
    if rel is None:
        return None
    best = None
    d = os.path.normpath(os.path.join(root, rel.lstrip("/")))
    while True:
        mx_p = os.path.join(d, "memory.max")
        if os.path.exists(mx_p):
            mx = rqlib.read_text(mx_p).strip()
            if mx != "max":
                cur = int(rqlib.read_text(os.path.join(d, "memory.current")).strip())
                h = (int(mx) - cur) // (1 << 20)
                best = h if best is None else min(best, h)
        if os.path.normpath(d) == os.path.normpath(root) or len(d) <= len(root):
            break
        d = os.path.dirname(d)
    return best


def mem_headroom_mb():
    """min(MemAvailable, every cgroup v2 headroom) in MB; None when any reading is unreadable."""
    avail = None
    try:
        with open(os.environ.get("RQ_MEMINFO", "/proc/meminfo")) as f:
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


def disk_guards(specs, root):
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


def disk_problem(guards):
    for path, need in guards:
        try:
            have = disk_free_mb(path)
        except OSError as e:
            return f"the free space of {path} is unreadable ({e.strerror or e}): fail closed"
        if have < need:
            return f"{path} has {have} MB free, below the disk guard's {need} MB"
    return None


def stop_group(pgid, log=None, grace=20.0):
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    t0, killed = time.time(), False
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
            return
        time.sleep(0.05)


# ------------------------------------------------------------- one cell
def run_cell(root, cid):
    """Worker: build, run, score, publish one cell. Exit 0 only once done.json is durable."""
    import cell as cell_mod
    d = os.path.join(root, store.WORK, cid)
    c = rqlib.read_json(os.path.join(d, "cell.json"))
    exe = os.path.join(root, "bin", "evo_boids")
    want = rqlib.read_text(exe + ".sha256").split()[0]
    if rqlib.sha256_file(exe) != want:
        print("the pinned binary changed", file=sys.stderr)
        return 2
    paths, probs = resolve_sources(root, c)
    if probs:
        print("SOURCE CHANGED since planning: " + "; ".join(probs), file=sys.stderr)
        return 5
    procs = []
    cell_mod.forward_signals(procs)
    t0 = time.time()
    try:
        bundle, info = cell_mod.execute(c, d, exe, paths, procs)
    except cell_mod.CellFailure as e:
        print(f"cell failed (exit {e.code}): {e}", file=sys.stderr)
        return e.code
    # provenance first (review-round lesson of the first study): everything a replay needs is in
    # the store, durably, before done.json says the cell is finished
    try:
        shas = [store.put_file(root, paths[role], want=c[role]["sha256"]) for role, _, _ in registered_sources(c)]
        if bundle["common_manifest_sha256"]:
            with open(os.path.join(d, "common.manifest.json"), "rb") as f:
                shas.append(store.put_bytes(root, f.read(), compress=True))
        shas += [bundle["binary_sha256"]] + [bundle["tools_sha256"][f] for f in OUTPUT_TOOLS]
        store.sync_objects(root, shas)
    except (store.StoreError, OSError) as e:
        print(f"FINALIZE FAILED (provenance): {e}", file=sys.stderr)
        return 7
    data = rqlib.canonical(bundle)
    rqlib.write_durable(os.path.join(d, "bundle.json"), data)
    g = c["groups"].get("common")
    done = {"schema": DONE_SCHEMA, "id": cid, "kind": c["kind"], "bundle_sha256": rqlib.sha256_bytes(data),
            "row_sha256": row_sha(c), "common_group": g if c["prey_policy"] == "common" else None,
            "common_sha256": bundle["files"].get("common.json"), "finished_utc": rqlib.now_utc(),
            "host": platform.node(),
            "timing": {"wall_s": round(time.time() - t0, 3), "build_s": round(info["t_build"], 3),
                       "engine_wall_s": round(info["engine_wall_s"], 3),
                       "engine_user_s": round(info["engine_user_s"], 3),
                       "engine_maxrss_kb": info["engine_maxrss_kb"],
                       "worker_maxrss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                       "score_s": round(info["t_score"], 3),
                       "steps_per_s": round(int(c["steps"]) / info["engine_wall_s"], 1) if info["engine_wall_s"] > 0 else None}}
    rqlib.write_json_durable(os.path.join(d, "done.json"), done)
    for f in os.listdir(d):    # the bulky, replayable files go (their SHA-256 are in the bundle)
        if f.endswith(".json") and f not in ("cell.json", "bundle.json", "done.json", "common.manifest.json",
                                              "arena.manifest.json") or f in ("pred.json", "prey.json"):
            os.remove(os.path.join(d, f))
    shutil.rmtree(os.path.join(d, "tmp"), ignore_errors=True)
    rqlib.fsync_dir(d)
    return 0


# ---------------------------------------------------------------- replay
def find_bundle(root, cid):
    data = store.read_member(root, cid, "bundle.json")
    if data is not None:
        return data, "chunk"
    p = os.path.join(root, store.WORK, cid)
    if os.path.isfile(os.path.join(p, "done.json")):
        done = rqlib.read_json(os.path.join(p, "done.json"))
        data = rqlib.read_bytes(os.path.join(p, "bundle.json"))
        if rqlib.sha256_bytes(data) != done["bundle_sha256"]:
            raise SystemExit(f"{cid}: bundle.json does not match its done.json")
        return data, "work"
    return None, None


def replay_cell(root, cid, out):
    """Child (the right tool versions): rerun cid into out, compare -> 0 identical, 8 different."""
    import cell as cell_mod
    data, where = find_bundle(root, cid)
    if data is None:
        print(f"{cid}: no finished cell of that id in {root}", file=sys.stderr)
        return 2
    rec = json.loads(data)
    c = rec["cell"]
    have = cell_mod.tools_sha256()
    if have != rec["tools_sha256"]:
        print(f"the replay tools {HERE} are not the versions this cell ran", file=sys.stderr)
        return 2
    exe = os.path.join(root, "bin", "evo_boids")
    if rqlib.sha256_file(exe) != rec["binary_sha256"]:
        print(f"{exe} is not the binary this cell ran", file=sys.stderr)
        return 2
    paths, probs = resolve_sources(root, c)
    if probs:
        print("SOURCE unavailable: " + "; ".join(probs), file=sys.stderr)
        return 5
    os.nice(19 - os.nice(0))
    try:
        b2, _ = cell_mod.execute(c, out, exe, paths)
    except cell_mod.CellFailure as e:
        print(f"replay failed (exit {e.code}): {e}", file=sys.stderr)
        return e.code
    new = rqlib.canonical(b2)
    checks = {"bundle.json (byte for byte)": new == data}
    for f, h in sorted(rec["files"].items()):
        checks[f] = b2["files"].get(f) == h
    for k in ("score", "arena_manifest", "predators_csv", "run_csv", "engine_args"):
        checks[k] = b2[k] == rec[k]
    ok = all(checks.values())
    rqlib.write_json_durable(os.path.join(out, "replay.json"), {
        "schema": REPLAY_SCHEMA, "utc": rqlib.now_utc(), "root": root, "cell": cid, "bundle_from": where,
        "identical": ok, "checks": checks, "bundle_sha256": rqlib.sha256_bytes(data),
        "replayed_bundle_sha256": rqlib.sha256_bytes(new), "binary_sha256": rec["binary_sha256"],
        "tools_sha256": rec["tools_sha256"], "tools_from": HERE, "sources": paths})
    with open(os.path.join(out, "bundle.json"), "wb") as f:
        f.write(new)
    for k, v in checks.items():
        print(f"{'same     ' if v else 'DIFFERENT'} {k}")
    print(f"replay {cid}: {'identical' if ok else 'MISMATCH'} ({sum(checks.values())}/{len(checks)} checks) -> {out}")
    return 0 if ok else 8


def start_replay(root, cid, out):
    """Pick the tool versions the cell ran (pinned, else rebuilt from the store) and run the replay."""
    out = os.path.abspath(out)
    if os.path.isdir(out) and os.listdir(out):
        print(f"--out {out} must be an empty directory", file=sys.stderr)
        return 2
    data, _ = find_bundle(root, cid)
    if data is None:
        print(f"{cid}: no finished cell of that id in {root}", file=sys.stderr)
        return 2
    need = json.loads(data)["tools_sha256"]
    tdir = os.path.join(root, "tools")
    pinned = {f: rqlib.sha256_file(os.path.join(tdir, f)) if os.path.isfile(os.path.join(tdir, f)) else None
              for f in OUTPUT_TOOLS}
    os.makedirs(out, exist_ok=True)
    if pinned == need:
        runner = os.path.join(tdir, "run.py")
    else:
        rdir = os.path.join(out, "replay_tools")
        os.makedirs(rdir)
        for f in OUTPUT_TOOLS:
            if not store.has(root, need[f]):
                print(f"cannot replay {cid}: no stored {f} {need[f][:12]}", file=sys.stderr)
                return 2
            store.materialize(root, need[f], os.path.join(rdir, f))
        for f in ("run.py", "store.py"):     # the drivers (any version that reads this root)
            shutil.copyfile(os.path.join(HERE, f), os.path.join(rdir, f))
        runner = os.path.join(rdir, "run.py")
    work = os.path.join(out, "cell")
    os.makedirs(work)
    return subprocess.call([sys.executable, "-I", runner, "--root", root, "--_replay", cid, work])


# ---------------------------------------------------------------- status
def status(root):
    recs, cells = store.load_index(root)
    fin = store.finished_cells(root)
    wd = os.path.join(root, store.WORK)
    inflight = [x for x in (os.listdir(wd) if os.path.isdir(wd) else []) if x not in fin and x not in cells]
    ad = os.path.join(root, "attempts")
    attempts = os.listdir(ad) if os.path.isdir(ad) else []
    plans = sorted(os.listdir(os.path.join(root, "plans"))) if os.path.isdir(os.path.join(root, "plans")) else []
    total = None
    cur = os.path.join(root, "plan.current")
    plan_ids = set()
    if os.path.isfile(cur):
        sha = rqlib.read_text(cur).strip()
        with open(os.path.join(root, "plans", sha + ".jsonl")) as f:
            plan_ids = {json.loads(ln)["id"] for ln in f if ln.strip()}
        total = len(plan_ids)
    done_ids = set(cells) | set(fin)
    prog = {}
    try:
        prog = rqlib.read_json(os.path.join(root, "progress.json"))
    except (OSError, ValueError):
        pass
    st = {"root": root, "plan_cells": total, "done": len(done_ids & plan_ids) if plan_ids else len(done_ids),
          "packed": len(cells), "finished_unpacked": len(fin), "in_flight_or_interrupted": len(inflight),
          "failed_attempts": len(attempts), "chunks": len(recs), "chunk_bytes": sum(r["bytes"] for r in recs),
          "plans": plans, "stop_file": os.path.exists(os.path.join(root, "STOP")),
          "runner": {k: prog.get(k) for k in ("state", "updated", "running", "workers", "session_cells_per_hour",
                                              "projected_finish", "stop_reason")}}
    print(json.dumps(st, indent=1, sort_keys=True))
    return 0


# ----------------------------------------------------------------- pinning
def pin_binary(root, binary):
    bdir = os.path.join(root, "bin")
    os.makedirs(bdir, exist_ok=True)
    pinned = os.path.join(bdir, "evo_boids")
    want = rqlib.sha256_file(binary)
    if not os.path.exists(pinned):
        tmp = pinned + ".tmp"
        shutil.copy2(binary, tmp)
        rqlib.fsync_file(tmp)
        os.replace(tmp, pinned)
        rqlib.write_durable(pinned + ".sha256", f"{want}  {os.path.abspath(binary)}\n")
        rqlib.fsync_dir(bdir)
        rqlib.fsync_dir(root)
    have = rqlib.read_text(pinned + ".sha256").split()[0]
    if have != want:
        raise SystemExit(f"{root} already runs another binary ({have[:12]}); this one is {want[:12]}")
    if rqlib.sha256_file(pinned) != have:
        raise SystemExit("the pinned binary no longer matches its hash")
    store.put_file(root, pinned, want=have, link=False)
    return have


def pin_tools(root, update, log):
    tdir = os.path.join(root, "tools")
    src = {f: rqlib.sha256_file(os.path.join(HERE, f)) for f in TOOL_FILES}
    if os.path.abspath(HERE) == os.path.abspath(tdir):
        return
    fresh = not os.path.isdir(tdir)
    if fresh or update:
        if not fresh:
            for f in TOOL_FILES:     # the versions finished cells ran stay replayable
                if os.path.isfile(os.path.join(tdir, f)):
                    store.put_file(root, os.path.join(tdir, f), link=False)
        os.makedirs(tdir, exist_ok=True)
        for f in TOOL_FILES:
            tmp = os.path.join(tdir, f + ".tmp")
            shutil.copyfile(os.path.join(HERE, f), tmp)
            rqlib.fsync_file(tmp)
            os.replace(tmp, os.path.join(tdir, f))
        rqlib.fsync_dir(tdir)
        log(f"tools pinned in {tdir}: " + " ".join(f"{f}={src[f][:10]}" for f in TOOL_FILES))
    else:
        pin = {f: rqlib.sha256_file(os.path.join(tdir, f)) for f in TOOL_FILES}
        if pin != src:
            log(f"note: tools/redqueen differs from the pinned {tdir}; running the pinned copy (--update-tools)")
    for f in TOOL_FILES:
        store.put_file(root, os.path.join(tdir, f), link=False)


def pin_env(root, build_manifest, log):
    env = {"python": sys.version.split()[0], "implementation": platform.python_implementation(),
           "platform": platform.platform(), "machine": platform.machine()}
    p = os.path.join(root, "env.json")
    if build_manifest:
        env["build_manifest_sha256"] = store.put_file(root, build_manifest, link=False)
    if not os.path.exists(p):
        rqlib.write_json_durable(p, dict(env, first_start_utc=rqlib.now_utc()))
        return
    old = rqlib.read_json(p)
    diff = {k: [old.get(k), v] for k, v in env.items() if old.get(k) != v}
    if diff:
        log(f"note: this start's environment differs from env.json's first start: {diff}")


# ------------------------------------------------------------------ runner
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--plan")
    ap.add_argument("--root", required=True)
    ap.add_argument("--binary")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--mem-min-mb", type=int, default=1500)
    ap.add_argument("--disk-min", action="append", metavar="PATH:MB")
    ap.add_argument("--chunk-size", type=int, default=1000)
    ap.add_argument("--retries", type=int, default=0)
    ap.add_argument("--quick-resume", action="store_true", help="check chunk sizes, not their SHA-256, at start")
    ap.add_argument("--update-tools", action="store_true")
    ap.add_argument("--build-manifest", help="the engine build's manifest, kept in the store and env.json")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--pack", action="store_true")
    ap.add_argument("--replay", metavar="CELL_ID")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)

    if a.status:
        return status(root)
    if a.replay:
        if not a.out:
            ap.error("--replay needs --out EMPTY_DIR")
        return start_replay(root, a.replay, a.out)
    if not a.pack and not (a.plan and a.binary):
        ap.error("--plan and --binary are required to run")
    if not 1 <= a.workers <= MAX_WORKERS:
        ap.error(f"--workers must be 1..{MAX_WORKERS}")
    if a.chunk_size < 1 or a.retries < 0:
        ap.error("--chunk-size >= 1 and --retries >= 0")

    os.makedirs(os.path.join(root, store.WORK), exist_ok=True)
    lock = open(os.path.join(root, ".runner.lock"), "w")
    try:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"another runner holds {root}", file=sys.stderr)
        return 73
    os.nice(19 - os.nice(0))
    logf = open(os.path.join(root, "runner.log"), "a")
    lost = [0]
    log = log_to(logf, lost)
    try:
        acts = store.recover(root, log)
    except store.StoreError as e:
        log(f"recover failed: {e}")
        return 1
    probs = store.verify_all(root, deep=not a.quick_resume)
    if probs:
        log(f"committed chunks damaged: {probs[:5]}")
        return 1
    if a.pack:
        name, n = store.pack(root, log=log)
        log(f"pack: {n} cells" + (f" into {name}" if name else "") + (f" (recovered: {len(acts)} actions)" if acts else ""))
        return 0

    if (os.cpu_count() or 1) < a.workers:
        log(f"note: --workers {a.workers} exceeds this machine's {os.cpu_count()} CPUs")
    guards = disk_guards(a.disk_min, root)
    pin_binary(root, a.binary)
    pin_tools(root, a.update_tools, log)
    pin_env(root, a.build_manifest, log)
    cell_runner = os.path.join(root, "tools", "run.py")

    rows = load_plan(a.plan)
    psha = rqlib.sha256_file(a.plan)
    _, packed = store.load_index(root)
    fin = store.finished_cells(root)
    todo = []
    for r in rows:
        rs = row_sha(r)
        if r["id"] in packed:
            if packed[r["id"]][1].get("row_sha256") != rs:
                print(f"cell {r['id']}: the plan row differs from the one it was packed with", file=sys.stderr)
                return 2
            continue
        if r["id"] in fin:
            dn = fin[r["id"]]
            if dn.get("row_sha256") != rs:
                print(f"cell {r['id']}: the plan row differs from the one it finished with", file=sys.stderr)
                return 2
            d = os.path.join(root, store.WORK, r["id"])
            if rqlib.sha256_file(os.path.join(d, "bundle.json")) != dn["bundle_sha256"]:
                print(f"cell {r['id']}: its bundle.json no longer matches done.json", file=sys.stderr)
                return 1
            continue
        todo.append(r)
    cache, changed = {}, []
    for r in todo:
        changed += resolve_sources(root, r, cache)[1]
    if changed:
        print("sources changed since planning (re-plan, or restore them): " + "; ".join(sorted(set(changed))[:10]),
              file=sys.stderr)
        return 2
    pdir = os.path.join(root, "plans")     # the plan is pinned only once it is accepted
    os.makedirs(pdir, exist_ok=True)
    if not os.path.exists(os.path.join(pdir, psha + ".jsonl")):
        shutil.copyfile(a.plan, os.path.join(pdir, psha + ".jsonl"))
        rqlib.fsync_file(os.path.join(pdir, psha + ".jsonl"))
        rqlib.fsync_dir(pdir)
    rqlib.write_durable(os.path.join(root, "plan.current"), psha + "\n")
    log(f"plan {a.plan} ({psha[:12]}): {len(rows)} cells, {len(rows) - len(todo)} already done, {len(todo)} to run, "
        f"workers {a.workers}, chunk size {a.chunk_size}, retries {a.retries}")

    running = {}      # pid -> (Popen, id, t0)
    failed, tries = [], {}
    stop_reason = None
    attempts_log = open(os.path.join(root, "attempts.tsv"), "a")
    queue = list(todo)
    n_done, n_before, t_start = 0, len(rows) - len(todo), time.time()
    rss_mb, mem_bad = 0, 0
    persist_failed = []
    unpacked = set(fin)   # finished, reaped, not yet packed (a running worker's cell never is)

    def kill_running(why):
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

    def progress(state="running"):
        el = time.time() - t_start
        rate = n_done / el * 3600 if el > 0 else 0.0
        left = len(rows) - n_before - n_done
        eta = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=left / rate)).strftime(
            "%Y-%m-%dT%H:%M:%SZ") if rate > 0 and left > 0 else None
        try:
            rqlib.write_json_durable(os.path.join(root, "progress.json"), {
                "state": state, "updated": rqlib.now_utc(), "plan_sha256": psha, "total": len(rows),
                "done": n_before + n_done, "failed": failed, "running": len(running), "queued": len(queue),
                "workers": a.workers, "session_cells_per_hour": rate, "projected_finish": eta,
                "stop_reason": stop_reason})
        except OSError:
            persist_failed.append("progress.json")

    def stop_admission(reason, persist=True):
        nonlocal stop_reason
        stop_reason = reason
        if persist:
            try:
                rqlib.write_durable(os.path.join(root, "STOP"), f"{rqlib.now_utc()} {reason}\n")
                where = f"wrote the reason to {root}/STOP"
            except OSError as e:
                persist_failed.append("STOP")
                where = f"could NOT write {root}/STOP ({e}); stopping anyway"
            log(f"{reason}; {where}; no new cells; waiting for {len(running)}")
        progress()

    def pack_now(final=False):
        # only cells the runner has reaped: a worker that wrote done.json but is still exiting
        # keeps its directory until its exit status is seen
        ids = sorted(unpacked)
        if ids and (final or len(ids) >= a.chunk_size):
            try:
                store.pack(root, ids=ids, log=log)
                unpacked.clear()
            except (store.StoreError, OSError) as e:
                failed.append(f"pack: {e}")
                log(f"PACK FAILED (nothing deleted): {e}")

    progress()
    try:
        while queue or running:
            for pid in list(running):
                p, cid, t0 = running[pid]
                rc = p.poll()
                if rc is None:
                    continue
                del running[pid]
                dt = time.time() - t0
                try:
                    attempts_log.write(f"{rqlib.now_utc()}\t{cid}\t{rc}\t{dt:.1f}\n")
                    attempts_log.flush()
                except OSError:
                    persist_failed.append("attempts.tsv")
                dpath = os.path.join(root, store.WORK, cid, "done.json")
                if rc == 0 and os.path.exists(dpath):
                    n_done += 1
                    unpacked.add(cid)
                    try:
                        t = rqlib.read_json(dpath)["timing"]
                        rss_mb = max(rss_mb, (t["engine_maxrss_kb"] + t["worker_maxrss_kb"]) // 1024)
                    except (OSError, ValueError, KeyError):
                        pass
                    if n_done % 50 == 0 or not queue:
                        log(f"done {n_done}/{len(todo)} (last {cid}, {dt:.0f}s)")
                    pack_now()
                else:
                    try:
                        err = rqlib.read_text(os.path.join(root, store.WORK, cid, "cell.stderr.log"))[-400:]
                    except OSError as e:
                        err = f"(cell.stderr.log unreadable: {e})"
                    if rc in RETRYABLE and tries.get(cid, 0) < a.retries:
                        tries[cid] = tries.get(cid, 0) + 1
                        log(f"KILLED {cid} (exit {rc}); requeued (retry {tries[cid]}/{a.retries}): {err.strip()[-200:]}")
                        queue.insert(0, next(r for r in todo if r["id"] == cid))
                    else:
                        failed.append(cid)
                        log(f"FAILED {cid} (exit {rc}): {err.strip()}")
                progress()
            if os.path.exists(os.path.join(root, "STOP")) and stop_reason is None:
                stop_admission("STOP", persist=False)
                log(f"STOP file: no new cells; waiting for {len(running)}")
            admit = stop_reason is None and not failed
            while admit and queue and len(running) < a.workers:
                why = disk_problem(guards)
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
                d = os.path.join(root, store.WORK, spec["id"])
                try:
                    if os.path.exists(d):
                        adir = os.path.join(root, "attempts")
                        os.makedirs(adir, exist_ok=True)
                        k = 1
                        while os.path.exists(os.path.join(adir, f"{spec['id']}.attempt{k}")):
                            k += 1
                        dst = os.path.join(adir, f"{spec['id']}.attempt{k}")
                        os.rename(d, dst)
                        for f in os.listdir(dst):     # keep the logs, not the replayable checkpoints
                            if f.endswith(".json") and f not in ("cell.json",) or f == "tmp":
                                pth = os.path.join(dst, f)
                                shutil.rmtree(pth) if os.path.isdir(pth) and not os.path.islink(pth) else os.remove(pth)
                    os.makedirs(d)
                    rqlib.write_json_durable(os.path.join(d, "cell.json"), spec)
                    tmpd = os.path.join(d, "tmp")
                    os.makedirs(tmpd)
                    err = open(os.path.join(d, "cell.stderr.log"), "w")
                except OSError as e:
                    queue.insert(0, spec)
                    stop_admission(f"admission failed: {e}")
                    admit = False
                    break
                p = subprocess.Popen([sys.executable, "-I", cell_runner, "--root", root, "--_cell", spec["id"]],
                                     stdout=err, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     start_new_session=True, preexec_fn=rqlib.die_with_parent,
                                     env=dict(os.environ, TMPDIR=tmpd, TMP=tmpd, TEMP=tmpd))
                err.close()
                running[p.pid] = (p, spec["id"], time.time())
            if not admit and not running:
                break
            t_wait = time.monotonic() + 0.5
            while time.monotonic() < t_wait and all(p.poll() is None for p, _, _ in running.values()):
                time.sleep(0.02)
    except BaseException as e:
        if running and not isinstance(e, SystemExit):
            kill_running(f"runner error {e!r}")
        raise
    pack_now(final=True)
    if persist_failed:
        log(f"note: {len(persist_failed)} state write(s) failed ({sorted(set(persist_failed))}); {lost[0]} log line(s) lost")
    if failed:
        progress("stopped: failed cell(s)")
        log(f"stopped: {len(failed)} failed: {failed[:5]}")
        return 1
    if stop_reason:
        msg = "stopped by STOP file" if stop_reason == "STOP" else f"stopped by the {stop_reason}"
        progress(msg)
        log(msg)
        return 75
    progress("all done")
    log(f"all {len(rows)} cells done")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 5 and sys.argv[3] == "--_cell":
        sys.exit(run_cell(os.path.abspath(sys.argv[2]), sys.argv[4]))
    if len(sys.argv) >= 6 and sys.argv[3] == "--_replay":
        sys.exit(replay_cell(os.path.abspath(sys.argv[2]), sys.argv[4], os.path.abspath(sys.argv[5])))
    sys.exit(main())

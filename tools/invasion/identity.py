#!/usr/bin/env python3
"""identity.py: are two engine binaries byte-identical on a study's real cells?

    identity.py --root STUDY_ROOT --out NEW_DIR --binary ref=PINNED --binary new=CANDIDATE
                [--sample N [--seed S] | --ids FILE] [--workers 1..4] [--keep]
    identity.py --report NEW_DIR

The gate a new engine binary passes before a study may use it (docs/throughput.md,
"Registering a new engine binary"). Every selected finished cell of STUDY_ROOT is
replayed from its own inputs (the cell's plan entry and its snapshots) once per
binary, each in its own directory under NEW_DIR/runs/<name>/<cell>/, by
run.execute(): the very build -> engine -> score procedure a study cell runs
(arena.py, the engine with the cell's arguments, score.py; the tools next to this
file). Then every output is hashed and the binaries' hashes compared, file by file:

  arena.json, every end.<frame>.json, end.json, run.births.csv, score.json: raw
  bytes; arena.manifest.json without its time stamp and its binary / output paths;
  run.csv without its two timing columns; run.config.txt and stdout.log without
  the build stamp and the timings; stderr.log raw.

A cell is IDENTICAL when every binary produced the same set of files with the
same hashes. The first binary is the reference; it is also compared with what the
study recorded for the cell (done.json: arena.json, end.json, run.births.csv, the
intermediate checkpoints, and score.json when the scoring tools are the ones the
cell ran with), so the replay is shown to reproduce the study, not just itself.
Exit 0 only when every cell is identical across the binaries and the reference
matches every record it can be compared with; the evidence is NEW_DIR/identity.json.

Rules: STUDY_ROOT is only read (cells/<id>/done.json, the manifest, the snapshot
files), never written, and refused while a runner holds it (a live, blind bank is
never read); NEW_DIR must be new or empty and outside STUDY_ROOT. Each binary is
copied into NEW_DIR/bin/ and its SHA-256 checked before every launch. Every
process runs at nice 19, at most --workers (1..4) engines at once; with --keep
unset only the small files of each run are kept (digest.json, score.json, logs).
--sample N picks N finished cells, round-robin over the (condition, mode,
predators) strata, shuffled within each stratum by --seed: every kind of cell is
covered before any kind repeats.
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import invlib  # noqa: E402

SCHEMA = "finfolk.invasion.identity/1"
TIMING_COLS = ("elapsed_s", "steps_per_sec")
BIG = ("arena.json", "run.births.csv")   # deleted after digesting unless --keep (with every end*.json)
STAMP = re.compile(r"\(built [^)]*\)")
TIMES = [re.compile(r"\(\s*[0-9.]+s, [0-9]+/s\)"),                       # per-sample "(1.5s, 1665/s)"
         re.compile(r"steps in [0-9.]+s \([0-9]+ steps/sec\)")]           # "Headless done. N steps in ..."


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def norm_text(path):
    t = open(path, encoding="utf-8", errors="surrogateescape").read()
    t = STAMP.sub("(built -)", t)
    for r in TIMES:
        t = r.sub("(-)", t)
    return t.encode("utf-8", errors="surrogateescape")


def norm_manifest(path):
    m = json.load(open(path))
    m.pop("created_utc", None)
    m["output"] = {"sha256": m["output"]["sha256"]}
    m.pop("binary", None)      # the binary under test: its path and hash differ by design
    return json.dumps(m, sort_keys=True).encode()


def norm_csv(path):
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return b""
    keep = [i for i, k in enumerate(rows[0]) if k not in TIMING_COLS]
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    for r in rows:
        w.writerow([r[i] for i in keep if i < len(r)])
    return out.getvalue().encode()


def digest_dir(d):
    """file -> sha256 of every output in a run directory (normalized where the doc says)."""
    out = {}
    for f in sorted(os.listdir(d)):
        p = os.path.join(d, f)
        if not os.path.isfile(p) or f in ("digest.json", "cell.json", "identity.log") or f.endswith(".tmp"):
            continue
        if f == "arena.manifest.json":
            out[f + " (no stamp, paths)"] = sha_bytes(norm_manifest(p))
        elif f == "run.csv":
            out[f + " (no timing columns)"] = sha_bytes(norm_csv(p))
        elif f in ("stdout.log", "run.config.txt"):
            out[f + " (no build stamp, timings)"] = sha_bytes(norm_text(p))
        else:
            out[f] = invlib.sha256_file(p)
    return out


# ------------------------------------------------------------------ one run
def run_one(out, name, cid):
    """Child: replay cell cid with binary `name` in out/runs/name/cid -> exit 0 when it ran and was digested."""
    import importlib.util
    spec_ = importlib.util.spec_from_file_location("run", os.path.join(HERE, "run.py"))
    run = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(run)
    d = os.path.join(out, "runs", name, cid)
    c = json.load(open(os.path.join(d, "cell.json")))
    meta = json.load(open(os.path.join(out, "binaries.json")))
    exe = os.path.join(out, "bin", name)
    if invlib.sha256_file(exe) != meta[name]["sha256"]:
        print(f"{exe} no longer has its recorded hash", file=sys.stderr)
        return 2
    for role in ("resident", "invader"):   # the snapshots the study's arena read, by content
        want = c.get(f"_{role}_read_sha256")
        if want and invlib.sha256_file(c[role]) != want:
            print(f"SNAPSHOT {role} {c[role]} changed since the study read it", file=sys.stderr)
            return 5
    t0 = time.time()
    rc, x = run.execute(c, d, exe)
    wall = time.time() - t0
    dig = {"rc": rc, "files": digest_dir(d) if rc == 0 else {}, "wall_s": round(wall, 3)}
    if rc == 0:
        ru = x["ru"]
        dig["timing"] = {"build_s": round(x["t_build"], 3), "engine_wall_s": round(x["wall"], 3),
                         "engine_user_s": round(ru.ru_utime, 3), "engine_sys_s": round(ru.ru_stime, 3),
                         "engine_maxrss_kb": ru.ru_maxrss, "score_s": round(x["t_score"], 3),
                         "steps": c["steps"]}
    invlib.write_json_atomic(os.path.join(d, "digest.json"), dig)
    if not KEEP:
        for f in os.listdir(d):
            if f in BIG or (f.startswith("end") and f.endswith(".json")):
                os.remove(os.path.join(d, f))
    return 0 if rc == 0 else 3


KEEP = False


# ------------------------------------------------------------------ the driver
def root_busy(root):
    """A runner holds the root (its flock), or its progress.json says running."""
    try:
        if json.load(open(os.path.join(root, "progress.json"))).get("state") == "running":
            return "its progress.json says running"
    except (OSError, ValueError):
        pass
    lp = os.path.join(root, ".runner.lock")
    if os.path.exists(lp):
        with open(lp) as f:
            try:
                fcntl.flock(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
            except OSError:
                return "a runner holds its lock"
    return None


def finished_cells(root):
    cdir = os.path.join(root, "cells")
    return sorted(x for x in os.listdir(cdir)
                  if ".attempt" not in x and os.path.exists(os.path.join(cdir, x, "done.json")))


def stratified(root, ids, n, seed):
    groups = {}
    for cid in ids:
        c = json.load(open(os.path.join(root, "cells", cid, "done.json")))["cell"]
        groups.setdefault((c["condition"], c["mode"], int(c["predators"]) > 0), []).append(cid)
    rng = random.Random(seed)
    for k in sorted(groups):
        rng.shuffle(groups[k])
    pick, i = [], 0
    while len(pick) < min(n, len(ids)):
        for k in sorted(groups):
            if i < len(groups[k]) and len(pick) < n:
                pick.append(groups[k][i])
        i += 1
    return pick


def compare(out):
    meta = json.load(open(os.path.join(out, "binaries.json")))
    names = sorted(meta, key=lambda k: meta[k]["order"])
    ref = names[0]
    src = json.load(open(os.path.join(out, "source.json")))
    cells = [ln.strip() for ln in open(os.path.join(out, "cells.txt")) if ln.strip()]
    tools_now = {f: invlib.sha256_file(os.path.join(HERE, f)) for f in ("invlib.py", "arena.py", "score.py")}
    res, n_files, bad, rec_bad, rec_n, missing = {}, 0, [], [], 0, []
    timing = {k: [] for k in names}
    comp = {}
    for cid in cells:
        digs = {}
        for k in names:
            p = os.path.join(out, "runs", k, cid, "digest.json")
            digs[k] = json.load(open(p)) if os.path.exists(p) else None
        if any(v is None or v["rc"] != 0 for v in digs.values()):
            missing.append(cid)
            res[cid] = {"identical": False, "why": "a run is missing or failed"}
            continue
        for k in names:
            timing[k].append(digs[k]["timing"])
        same = all(digs[k]["files"] == digs[ref]["files"] for k in names)
        diff = sorted({f for k in names for f in set(digs[k]["files"]) | set(digs[ref]["files"])
                       if digs[k]["files"].get(f) != digs[ref]["files"].get(f)})
        n_files += len(digs[ref]["files"])
        # the reference against what the study recorded
        done = json.load(open(os.path.join(src["root"], "cells", cid, "done.json")))
        c = done["cell"]
        key = (c["condition"], c["mode"], int(c["predators"]))
        comp[str(key)] = comp.get(str(key), 0) + 1
        recs = {f: done["outputs"].get(f) for f in ("arena.json", "end.json", "run.births.csv")}
        recs.update(done.get("intermediate_checkpoints") or {})
        if all(done.get("tools_sha256", {}).get(f) == h for f, h in tools_now.items()):
            recs["score.json"] = done["outputs"].get("score.json")
        rdiff = sorted(f for f, h in recs.items() if h is not None and digs[ref]["files"].get(f) != h)
        rec_n += sum(1 for h in recs.values() if h is not None)
        if not same:
            bad.append(cid)
        if rdiff:
            rec_bad.append(cid)
        res[cid] = {"identical": same, "different_files": diff, "files": len(digs[ref]["files"]),
                    "record_checked": sorted(f for f, h in recs.items() if h is not None),
                    "record_mismatch": rdiff}

    def med(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else None
    speed = {k: {"median_engine_wall_s": med([t["engine_wall_s"] for t in timing[k]]),
                 "median_engine_user_s": med([t["engine_user_s"] for t in timing[k]]),
                 "total_engine_user_s": round(sum(t["engine_user_s"] for t in timing[k]), 1),
                 "median_build_s": med([t["build_s"] for t in timing[k]]),
                 "median_score_s": med([t["score_s"] for t in timing[k]])} for k in names}
    ok = not bad and not missing and not rec_bad and bool(cells)
    rep = {"schema": SCHEMA, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "source": src, "binaries": meta, "reference": ref,
           "tools_sha256": {f: invlib.sha256_file(os.path.join(HERE, f)) for f in
                            ("invlib.py", "arena.py", "score.py", "run.py", "identity.py")},
           "cells": len(cells), "composition": comp, "files_compared_per_binary": n_files,
           "record_hashes_checked": rec_n,
           "identical": len(cells) - len(bad) - len(missing), "different": bad, "missing_or_failed": missing,
           "record_mismatch": rec_bad, "verdict": "IDENTICAL" if ok else "NOT IDENTICAL",
           "speed": speed, "per_cell": res}
    invlib.write_json_atomic(os.path.join(out, "identity.json"), rep)
    print(f"{rep['verdict']}: {rep['identical']}/{len(cells)} cells identical across {', '.join(names)} "
          f"({n_files} files per binary); reference vs the study's record: {rec_n} hashes, "
          f"{len(rec_bad)} cells mismatched; {len(missing)} missing or failed")
    for k in names:
        s = speed[k]
        print(f"  {k}: {meta[k]['sha256'][:16]}  median engine {s['median_engine_wall_s']} s wall, "
              f"{s['median_engine_user_s']} s user; total user {s['total_engine_user_s']} s")
    for cid in (bad + rec_bad)[:10]:
        print(f"  {cid}: {res[cid]}")
    return 0 if ok else 1


def main(argv=None):
    global KEEP
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root")
    ap.add_argument("--out", required=False)
    ap.add_argument("--binary", action="append", default=[], help="NAME=PATH (the first is the reference)")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--ids")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--report")
    a = ap.parse_args(argv)
    if a.report:
        return compare(os.path.abspath(a.report))
    if not (a.root and a.out) or len(a.binary) < 2 or not (a.sample or a.ids):
        ap.error("--root, --out, two or more --binary NAME=PATH and --sample or --ids are required")
    if not 1 <= a.workers <= 4:
        ap.error("--workers must be 1..4")
    KEEP = a.keep
    root, out = os.path.realpath(a.root), os.path.realpath(a.out)
    if out == root or out.startswith(root + os.sep):
        ap.error("--out must be outside the study root (the study root is never written)")
    busy = root_busy(root)
    if busy:
        print(f"refused: {root} is in use ({busy}); a live study is never read", file=sys.stderr)
        return 2
    if os.path.exists(out) and os.listdir(out):
        ap.error(f"--out {out} must be new or empty")
    os.nice(19 - os.nice(0))
    os.makedirs(os.path.join(out, "bin"), exist_ok=True)
    meta = {}
    for i, b in enumerate(a.binary):
        name, sep, path = b.partition("=")
        if not sep or not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in meta:
            ap.error(f"--binary {b!r}: expected a unique NAME=PATH")
        dst = os.path.join(out, "bin", name)
        shutil.copy2(path, dst)
        meta[name] = {"path": os.path.abspath(path), "sha256": invlib.sha256_file(dst), "order": i}
        if invlib.sha256_file(path) != meta[name]["sha256"]:
            print(f"{path} changed while it was copied", file=sys.stderr)
            return 2
    invlib.write_json_atomic(os.path.join(out, "binaries.json"), meta)
    ids = finished_cells(root)
    if a.ids:
        want = [ln.strip() for ln in open(a.ids) if ln.strip()]
        unknown = [x for x in want if x not in set(ids)]
        if unknown:
            ap.error(f"--ids: not finished cells of {root}: {unknown[:5]}")
        cells = want
    else:
        cells = stratified(root, ids, a.sample, a.seed)
    with open(os.path.join(out, "cells.txt"), "w") as f:
        f.write("".join(c + "\n" for c in cells))
    invlib.write_json_atomic(os.path.join(out, "source.json"),
                             {"root": root, "selection": f"--ids {a.ids}" if a.ids else f"--sample {a.sample} --seed {a.seed}",
                              "finished_cells": len(ids)})
    names = sorted(meta, key=lambda k: meta[k]["order"])
    jobs = []
    for cid in cells:
        src = os.path.join(root, "cells", cid)
        c = dict(json.load(open(os.path.join(src, "done.json")))["cell"])
        man = json.load(open(os.path.join(src, "arena.manifest.json")))
        for role in ("resident", "invader"):   # the content the study's arena read
            if c.get(role) and isinstance(man.get(role), dict):
                c[f"_{role}_read_sha256"] = man[role]["sha256"]
        for k in names:   # interleaved, so both binaries see the same machine load
            d = os.path.join(out, "runs", k, cid)
            os.makedirs(d)
            invlib.write_json_atomic(os.path.join(d, "cell.json"), c)
            jobs.append((k, cid))
    print(f"{len(cells)} cells x {len(names)} binaries = {len(jobs)} runs, {a.workers} worker(s), nice 19 -> {out}",
          flush=True)
    t0 = time.time()
    running, failed, done_n = {}, [], 0
    while jobs or running:
        while jobs and len(running) < a.workers:
            k, cid = jobs.pop(0)
            log = open(os.path.join(out, "runs", k, cid, "identity.log"), "w")
            p = subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "--_one", out, k, cid]
                                 + (["--keep"] if KEEP else []), stdout=log, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL)
            running[p.pid] = (p, k, cid, log)
        pid, status = os.wait()
        if pid not in running:
            continue
        p, k, cid, log = running.pop(pid)
        log.close()
        rc = os.waitstatus_to_exitcode(status)
        p.returncode = rc
        done_n += 1
        if rc:
            failed.append((k, cid, rc))
            print(f"FAILED {k} {cid} (exit {rc})", flush=True)
        if done_n % 20 == 0 or not (jobs or running):
            print(f"{done_n} runs done, {time.time() - t0:.0f} s", flush=True)
    return compare(out)


if __name__ == "__main__":
    if len(sys.argv) >= 5 and sys.argv[1] == "--_one":
        KEEP = "--keep" in sys.argv[5:]
        sys.exit(run_one(os.path.abspath(sys.argv[2]), sys.argv[3], sys.argv[4]))
    sys.exit(main())

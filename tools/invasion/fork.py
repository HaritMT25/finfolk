#!/usr/bin/env python3
"""fork.py: fork one checkpoint into K sister populations that evolve apart (heterosis control).

    fork.py --ancestor ANC.json --sisters K --steps N --out DIR --binary EVO_BOIDS
            [--name NAME] [--checkpoint-every M] [--workers W] [--seed-base S]

Each sister is the ancestor's world continued with its own random stream:
    evo_boids --load-checkpoint ANC.json --reseed-after-load R_s --headless N ...
so all K start from the SAME population (same genomes, same state) and diverge
only through the rng from the first step: "diverged but not better" relatives
whose invasion pair separates kinship from progress. The ancestor's config is
kept as is (its home regime: predators, min-pop floor and every other dial), so a
sister evolves exactly as its ancestor's run would have, on a different stream.

R_s = derive_seed("sister", SHA-256 of the ancestor, s, seed-base). Engines run
at nice 19, at most --workers (1..4) at a time. Outputs in DIR:
    NAME.s<k>.json             the sister at the end (and NAME.s<k>.<frame>.json
                               every M steps with --checkpoint-every)
    NAME.s<k>.csv / .log       the run's metrics and console
    NAME.fork.json             manifest: ancestor path + hash, reseeds, binary
                               hash, commands, output hashes
"""
from __future__ import annotations

import argparse
import datetime
import os
import signal
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import invlib  # noqa: E402
import run  # noqa: E402  (die_with_parent)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ancestor", required=True)
    ap.add_argument("--sisters", type=int, default=2)
    ap.add_argument("--steps", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--name")
    ap.add_argument("--checkpoint-every", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed-base", default="0")
    a = ap.parse_args(argv)
    if not 1 <= a.workers <= 4:
        ap.error("--workers must be 1..4")
    if a.sisters < 2:
        ap.error("--sisters must be >= 2")
    anc = os.path.abspath(a.ancestor)
    cp = invlib.load_checkpoint(anc)   # validates the format
    if not str(cp.get("determinism", "")).startswith("serial build"):
        raise SystemExit("the ancestor was not written by a serial build")
    h = invlib.sha256_file(anc)
    name = a.name or os.path.splitext(os.path.basename(anc))[0]
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    os.nice(19 - os.nice(0))
    jobs = []
    for s in range(a.sisters):
        r = invlib.derive_seed("sister", h, s, a.seed_base)
        stem = os.path.join(out, f"{name}.s{s}")
        cmd = [os.path.abspath(a.binary), "--load-checkpoint", anc, "--reseed-after-load", str(r),
               "--headless", str(a.steps), "--no-render", "--log-every", "5000",
               "--csv", stem + ".csv", "--save-checkpoint", stem + ".json"]
        if a.checkpoint_every:
            cmd += ["--checkpoint-every", str(a.checkpoint_every)]
        jobs.append({"sister": s, "reseed": r, "stem": stem, "cmd": cmd})
    running, pending, failed = [], list(jobs), []

    def terminate(signum, frame):   # no sister engine outlives fork.py
        for p, _ in running:
            if p.poll() is None:
                p.terminate()
        for p, _ in running:
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        print(f"fork: signal {signum}: stopped {len(running)} running sisters", file=sys.stderr)
        sys.exit(130)
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, terminate)
    while pending or running:
        while pending and len(running) < a.workers:
            j = pending.pop(0)
            log = open(j["stem"] + ".log", "w")
            running.append((subprocess.Popen(j["cmd"], stdout=log, stderr=subprocess.STDOUT,
                                             stdin=subprocess.DEVNULL, preexec_fn=run.die_with_parent), j))
        p, j = running.pop(0)
        rc = p.wait()
        j["exit"] = rc
        if rc != 0:
            failed.append(j["sister"])
    for j in jobs:
        if j.get("exit") == 0:
            j["outputs"] = {os.path.basename(f): invlib.sha256_file(f)
                            for f in (j["stem"] + ".json", j["stem"] + ".csv")}
    man = {"schema": "finfolk.invasion.fork/1",
           "finished_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "ancestor": {"path": anc, "sha256": h, "frame": int(cp["world"]["frame"]),
                        "n": int(cp["creatures"]["count"]), "predators": int(cp["predators"]["count"])},
           "binary": {"path": os.path.abspath(a.binary), "sha256": invlib.sha256_file(a.binary)},
           "steps": a.steps, "seed_base": a.seed_base, "sisters": jobs}
    invlib.write_json_atomic(os.path.join(out, f"{name}.fork.json"), man)
    if failed:
        print(f"fork: sisters {failed} failed", file=sys.stderr)
        return 1
    print(f"fork: {a.sisters} sisters of {name} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

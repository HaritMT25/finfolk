#!/usr/bin/env python3
"""plan.py: the job list for one phase of the study, from the frozen files.

    python3 tools/alife2027/plan.py PROTOCOL OUT.jsonl --phase main|engineering|ext:ID
        [--first N] [--arms C1,D1,...] [--steps N] [--seeds-file FILE]

One JSON object per line, one per (seed, arm) [extension arms are labelled
ARM+suffix]: the job id, seed, its index in the phase's published order, the
arm's keys, the compact --cfg JSON (common config + extension overrides), the
driver argv (relative output prefix), and `expect`: what the validator
requires of the outputs. Which instruments a job gets is decided here, from
protocol.json's `subsets` by seed index (first N of the phase's order) --
never by the runner. --steps shortens every run of an engineering plan (the
checkpoints, behav-at and encounter horizon past it are dropped); the main
phase refuses it.
"""
from __future__ import annotations

import csv
import json
import os
import sys


def read_ids(path):
    with open(path) as f:
        return [int(x) for x in f.read().split()]


def load(proto_path):
    base = os.path.dirname(os.path.abspath(proto_path))
    proto = json.load(open(proto_path))
    arms = {}
    with open(os.path.join(base, proto["arms"]), newline="") as f:
        for r in csv.DictReader(f):
            arms[r["arm"]] = {k: (int(v) if k in ("eye", "eyeOnly", "steerFrame", "labelFrame", "eyeCode", "seeds") else v)
                              for k, v in r.items()}
    common = json.load(open(os.path.join(base, proto["common_config"])))
    return base, proto, arms, common


def check_arm(name, a):
    """driver_arm's letter / digit must say what the row says (eye, eyeOnly, steerFrame)."""
    letters = {"A": (0, 0), "B": (1, 0), "C": (1, 1), "D": (0, 1)}
    d = a["driver_arm"]
    if len(d) != 2 or d[0] not in letters or d[1] not in "01":
        raise SystemExit(f"arm {name}: bad driver_arm {d}")
    if letters[d[0]] != (a["eye"], a["eyeOnly"]) or int(d[1]) != a["steerFrame"]:
        raise SystemExit(f"arm {name}: driver_arm {d} disagrees with eye/eyeOnly/steerFrame")


def in_first(sub, idx):
    return idx < sub.get("seeds_first", 0)


def make_jobs(proto_path, phase, first=None, arm_filter=None, steps_override=None, seeds_file=None):
    base, proto, arms, common = load(proto_path)
    for n, a in arms.items():
        check_arm(n, a)
    run = proto["run"]
    steps = run["steps"]
    if steps_override is not None:
        if phase == "main":
            raise SystemExit("--steps is for engineering plans only")
        steps = steps_override
    every = run["csv_every"]
    ext = None
    if phase == "main":
        seeds = read_ids(os.path.join(base, proto["seeds"]["main"]))
        arm_names = list(arms)
    elif phase == "engineering":
        seeds = read_ids(seeds_file or os.path.join(base, proto["seeds"]["engineering"]))
        arm_names = list(arms)
    elif phase.startswith("ext:"):
        ext = next((e for e in proto["extensions"] if e["id"] == phase[4:]), None)
        if ext is None:
            raise SystemExit("no extension " + phase[4:])
        seeds = read_ids(seeds_file or os.path.join(base, proto["seeds"]["main"]))[:ext["seeds_first"]]
        arm_names = list(ext["arms"])
    else:
        raise SystemExit("phase is main, engineering or ext:ID")
    if first is not None:
        seeds = seeds[:first]
    if arm_filter:
        unknown = [a for a in arm_filter if a not in arms]
        if unknown:
            raise SystemExit(f"unknown arms {unknown}")
        arm_names = [a for a in arm_names if a in arm_filter]
    cfg = dict(common)
    if ext:
        cfg.update(ext.get("config_overrides", {}))
    cfg_json = json.dumps(cfg, separators=(",", ":"), sort_keys=False)
    subs = proto["subsets"]
    br = proto["branches"]
    jobs = []
    for idx, seed in enumerate(seeds):
        for arm in arm_names:
            a = arms[arm]
            label = arm + (ext["label_suffix"] if ext else "")
            prefix = f"{label}_s{seed}"
            jdir = f"s{seed}/{label}"
            w = proto["world"]
            argv = ["--arm", a["driver_arm"], "--label", label, "--eye-code", str(a["eyeCode"]),
                    "--label-frame", str(a["labelFrame"]), "--seed", str(seed), "--steps", str(steps),
                    "--every", str(every), "--w", str(w["width"]), "--h", str(w["height"]), "--depth", str(w["depth"]),
                    "--pop", str(w["founders"]), "--cfg", cfg_json, "--out", prefix, "--behav",
                    "--resolved", prefix + ".resolved.json", "--manifest", prefix + ".run.json",
                    "--diag", prefix + ".diag.csv", "--fp", prefix + ".fp.txt",
                    "--fp-every", str(run["fingerprints"]["every"])]
            expect = {"steps": steps, "every": every, "csv": True, "behav": True, "diag": True,
                      "fp": "sparse", "fp_every": run["fingerprints"]["every"], "behav_at": [], "branches": [],
                      "encounters": None, "wiring": None, "arm": {k: a[k] for k in ("eye", "eyeOnly", "steerFrame",
                                                                                       "labelFrame", "eyeCode")}}
            ver = subs["verification"]
            if arm in ver["arms"] and in_first(ver, idx) and not ext:
                argv.append("--fp-dense")
                expect["fp"] = "dense"
            wiring = None
            for wh in subs["wiring_history"]:
                if arm in wh["arms"] and in_first(wh, idx) and not ext:
                    wiring = {"every": wh["every"], "paths": wh["paths"]}
            if wiring is None:
                wiring = {"every": 0, "paths": subs["wiring_terminal"]["paths"]}
            argv += ["--dump-wiring", prefix + ".wiring.csv"]
            if wiring["every"]:
                argv += ["--wiring-every", str(wiring["every"])]
            if not wiring["paths"]:
                argv.append("--wiring-no-paths")
            expect["wiring"] = wiring
            enc = subs["encounters"]
            if arm in enc["arms"] and in_first(enc, idx) and not ext:
                until = min(enc["until"], steps)
                argv += ["--encounters", prefix + ".enc.csv", "--encounters-until", str(until),
                         "--encounters-every", str(enc["every"])]
                expect["encounters"] = {"until": until, "every": enc["every"]}
            bs = subs["branches"]
            if arm in bs["arms"] and in_first(bs, idx) and arm in br["continuations"] and not ext:
                cps = [c for c in br["checkpoints"] if c <= steps]
                if cps:
                    argv += ["--branches", br["continuations"][arm], "--branch-at", ",".join(map(str, cps)),
                             "--branch-out", prefix + ".branches.csv", "--branch-steps", str(br["steps"]),
                             "--branch-fp-every", str(br["fp_every"]), "--branch-early", str(br["early_steps"])]
                    expect["branches"] = cps
                    expect["branch_spec"] = br["continuations"][arm]
                    expect["branch_steps"] = br["steps"]
                    ba = [s for s in br.get("behav_at", []) if s <= steps and s != steps]
                    if ba:
                        argv += ["--behav-at", ",".join(map(str, ba))]
                        expect["behav_at"] = ba
            jobs.append({"id": f"{phase}/{jdir}", "phase": phase, "seed": seed, "seed_index": idx, "arm": label,
                         "base_arm": arm, "dir": jdir, "prefix": prefix, "argv": argv, "cfg": cfg, "expect": expect})
    return jobs


def main():
    if len(sys.argv) < 3 or "--phase" not in sys.argv:
        print(__doc__)
        return 2
    args = sys.argv
    opt = lambda k: args[args.index(k) + 1] if k in args else None  # noqa: E731
    jobs = make_jobs(args[1], opt("--phase"), int(opt("--first")) if opt("--first") else None,
                     opt("--arms").split(",") if opt("--arms") else None,
                     int(opt("--steps")) if opt("--steps") else None, opt("--seeds-file"))
    with open(args[2], "w", newline="\n") as f:
        for j in jobs:
            f.write(json.dumps(j, separators=(",", ":")) + "\n")
    print(f"{len(jobs)} jobs -> {args[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

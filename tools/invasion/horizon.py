#!/usr/bin/env python3
"""horizon.py: calibrate the common fixed-step horizon T on independent cells (stdlib only).

    horizon.py --root DIR [--root DIR2] --plan PLAN.jsonl --select fraction=0.15 [--select condition=off]
               [--generations 5] [--grid 2000] --out horizon.json

Stats spec section 1: the primary horizon is ONE common number of steps T for every assay,
calibrated to about five turnover generations from independent pilot data, with 2T as the
long-horizon sensitivity. A per-resident clock (analyze.py --clock gens) is estimated from the
very shams it is then used to read, and it gives the two directions of a pair different
exposure durations; a fixed T avoids both.

T = generations x mean over (snapshot, condition) of the mean-population turnover g_pop =
steps x mean population / births of the SELECTED sham cells (registered cells only, checked by
analyze.load), rounded to the checkpoint grid so that every run is read exactly at a
checkpoint. The selection must be cells whose outcomes the analysis does not use (e.g. the
pilot's 15% shams for its 5% matrices, or the whole pilot for a confirmatory run).

horizon.json: T, T2 = 2T, the unrounded value, the per-(snapshot, condition) clocks, and the
calibration cells by content hash (plus the plan's and this code's hashes).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze  # noqa: E402


def matches(c, sel):
    for k, v in sel:
        x = c.get(k)
        if isinstance(x, float) or k == "fraction":
            if x is None or abs(float(x) - float(v)) > 1e-12:
                return False
        elif str(x) != v:
            return False
    return True


def calibrate(recs, generations, grid):
    gens = analyze.gen_length(recs, "pop")
    clocks = [{"snapshot": j, "condition": c, "g_pop": v["g_pop"], "g_pop_sd": v["g_pop_sd"], "runs": v["runs"]}
              for (j, c), v in sorted(gens.items())]
    if not clocks:
        raise SystemExit("horizon.py: no sham cell in the selection")
    g = sum(x["g_pop"] for x in clocks) / len(clocks)
    raw = generations * g
    T = max(grid, int(round(raw / grid)) * grid) if grid else max(1, int(round(raw)))
    return {"T": T, "T2": 2 * T, "raw_T": raw, "mean_g_pop": g, "generations": generations, "grid": grid,
            "clocks": clocks}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", action="append", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--select", action="append", default=[], help="cell-spec field=value (repeatable), e.g. fraction=0.15")
    ap.add_argument("--generations", type=float, default=5.0)
    ap.add_argument("--grid", type=int, default=2000, help="checkpoint spacing T is rounded to (steps)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    plan = {}
    for ln in open(a.plan):
        if ln.strip():
            c = json.loads(ln)
            plan[c["id"]] = c
    sel = [tuple(s.split("=", 1)) for s in a.select]
    sub = {cid: c for cid, c in plan.items() if matches(c, sel)}
    recs, problems, _, _ = analyze.load(a.root, sub)
    recs = [r for r in recs if r["mode"] == "sham"]
    res = calibrate(recs, a.generations, a.grid)
    here = os.path.dirname(os.path.abspath(__file__))
    res.update({
        "schema": "finfolk.invasion.horizon/1",
        "calibration": f"{len(recs)} sham cells with {' '.join(a.select) or 'no selection'}",
        "plan_sha256": analyze.sha256(a.plan),
        "code_sha256": {f: analyze.sha256(os.path.join(here, f)) for f in ("horizon.py", "analyze.py")},
        "cells": [{"id": r["id"], "done_sha256": r["hashes"]["done.json"]} for r in sorted(recs, key=lambda r: r["id"])],
        "identity_problems": problems, "args": vars(a),
    })
    with open(a.out, "w") as f:
        f.write(json.dumps(res, indent=1, sort_keys=True) + "\n")
    print(f"T = {res['T']} steps (2T = {res['T2']}; {a.generations:g} x mean g_pop {res['mean_g_pop']:.0f} = "
          f"{res['raw_T']:.0f}, grid {a.grid}) from {res['calibration']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

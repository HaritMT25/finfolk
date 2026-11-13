#!/usr/bin/env python3
"""score.py: read one Red Queen assay's outputs at its registered horizons.

    score.py --dir CELL_DIR --k K --steps N --horizons 5000,10000,20000 --log-every 500 [--assay frozen]

Inputs (the files cell.py's two engine calls leave in CELL_DIR): arena.json (the transplant's
arena: the starting prey ids, the start frame f0, the counters' baseline), run.predators.csv
(Stage C's per-interval predator readout), and end.<f0 + h>.json at every horizon h.

Readouts per horizon h (summed counts over summed exposure, never a mean of interval rates):
  * captures      sum of predators.csv captures_interval over the rows f0 < step <= f0 + h
                  (its counters start at the load; design section 5);
  * predator_seconds  sum over those rows of predator_pop x log_every x dt (dt = 0.016). In the
                  frozen modes the count is fixed (checked: every row and every checkpoint has K),
                  so this is exact; in live mode it is a sampled approximation (flagged);
  * capture_rate  captures / predator_seconds (None with no exposure, e.g. the predator-free fork);
  * virtual_buds and their rate (the frozen assay's energetic readout), pursuit_seconds;
  * survivors / survival: how many of the arena's prey ids (the initial cohort) are alive in
    end.<f0 + h>.json, over the cohort size (compared with the predator-free fork later);
  * prey, births, deaths by cause: from the checkpoints' cumulative counters minus the arena's
    (exact; the main CSV's first interval row can carry a loaded world's history).
Checks (any failure raises ScoreError): rows exactly at f0 + m x log_every; the checkpoint at
each horizon at its frame; the arena's and every checkpoint's predator count == K in the frozen
modes, no predator births / deaths / refills there; the predation-death counter difference
equals the summed captures; and in the predator-free fork (--fork), in every assay mode, no
predator at any sample or horizon, no capture, predator birth or refill in any row, and no
change of the predator-birth, refill or predation-death counters; and in every cell, no prey
replenishment (a prey floor's injected founders): at each horizon the living prey are exactly
the start plus births minus deaths, and no prey outside the initial cohort is a founder.

--scripted (K fresh scripted Stage A hunters, the H-C benchmark: no brain, so no predators.csv). The
mode is VERIFIED from the inputs, never taken from the flag (Codex #74 r1 P2-4): the arena and every
horizon checkpoint must be format version 1 with the brain and the economy off and K hunters, and
there must be no run.predators.csv (a neural metrics file); a neural or economy-enabled input is
refused. Captures are then the predation-death counter's difference from the arena's (a loaded
baseline subtracted), the exposure K x h x dt, and no predator birth, refill or death may occur.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
import csv
import io
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ckpt  # noqa: E402

SCHEMA = "finfolk.redqueen.score/1"
DT = 0.016          # main.cpp fixedDt
FROZEN = ("frozen", "frozen-newborn")
START_AGE_EDGES_S = tuple(range(0, 121, 12))  # fixed diagnostic bins; not the cell's maxAge


class ScoreError(Exception):
    pass


def read_predators_csv(text):
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ScoreError("predators.csv has no rows")
    return rows


def _ratio(a, b):
    return a / b if b > 0 else None


def _start_ages(arena, start_ids):
    """The initial cohort's ages at f0, keyed by the same IDs as the survival readout."""
    max_age = (arena.get("config") or {}).get("maxAge")
    if (isinstance(max_age, bool) or not isinstance(max_age, (int, float)) or
            not math.isfinite(max_age) or max_age < 0):
        raise ScoreError("arena.json: missing or invalid config.maxAge")
    cs = arena["creatures"]
    ages = cs.get("age")
    if not isinstance(ages, list) or len(ages) != len(cs["id"]):
        raise ScoreError("arena.json: missing start age (creature age column incomplete)")
    by_id = {}
    for i, age in zip(cs["id"], ages):
        if int(i) not in start_ids:
            continue
        if (isinstance(age, bool) or not isinstance(age, (int, float)) or
                not math.isfinite(age) or not 0 <= age <= max_age):
            raise ScoreError(f"arena.json: start age {age!r} for prey {i} outside [0, maxAge={max_age}]")
        if age > START_AGE_EDGES_S[-1]:
            raise ScoreError(f"arena.json: start age {age} for prey {i} outside fixed diagnostic bins "
                             f"[0, {START_AGE_EDGES_S[-1]}] s")
        by_id[int(i)] = age
    if set(by_id) != start_ids:
        raise ScoreError("arena.json: missing start age for an initial-cohort ID")
    return by_id, max_age


def _age_strata(start_ages, alive_ids, max_age, h, dt, n_start, survivors):
    """Partition by START age, independently by fixed seconds bins and age-only feasibility."""
    bins = [{"n_start": 0, "survivors": 0} for _ in START_AGE_EDGES_S[1:]]
    structural = {k: {"n_start": 0, "survivors": 0} for k in ("feasible", "infeasible")}
    limit = max_age - h * dt
    for i, age in start_ages.items():
        # bisect puts interior edges in the bin on their right; the final edge is closed.
        b = min(bisect_right(START_AGE_EDGES_S, age) - 1, len(bins) - 1)
        for stratum in (bins[b], structural["feasible" if age <= limit else "infeasible"]):
            stratum["n_start"] += 1
            stratum["survivors"] += int(i in alive_ids)
    for label, strata in (("bins", bins), ("feasibility", structural.values())):
        if (sum(s["n_start"] for s in strata) != n_start or
                sum(s["survivors"] for s in strata) != survivors):
            raise ScoreError(f"horizon {h}: age strata {label} do not sum to n_start / survivors")
    if structural["infeasible"]["survivors"] != 0:
        raise ScoreError(f"horizon {h}: age-infeasible initial prey survived")
    return {"bin_edges_s": list(START_AGE_EDGES_S), "bins": bins,
            "max_age_s": max_age, "feasible_start_age_max_s": limit, **structural}


def scripted_problems(cp, k, what):
    """Why a checkpoint is not a scripted (Stage A) arena of K hunters: version 1, brain and economy off."""
    cfg = cp.get("config") or {}
    probs = []
    if int(cp.get("formatVersion", 0)) != ckpt.V1:
        probs.append(f"{what} is format version {cp.get('formatVersion')} (a scripted arena is version 1: no brains)")
    if cfg.get("predatorBrain"):
        probs.append(f"{what} has predatorBrain on (neural predators)")
    if cfg.get("predatorEconomy"):
        probs.append(f"{what} has predatorEconomy on (scripted hunters are immortal and fixed)")
    if int((cp.get("predators") or {}).get("count", -1)) != k:
        probs.append(f"{what} has {(cp.get('predators') or {}).get('count')} predators, not K = {k}")
    return probs


def score(d, k, steps, horizons, log_every, assay, fork=False, scripted=False):
    """fork: the predator-free continuation (K = 0). Any predator at any sample or horizon, any
    capture, predator birth or refill, or any predation death refuses it (review round 2: a live
    control could otherwise be refilled by a predator floor and still pass). scripted: K fixed,
    immortal Stage A hunters (no brain: no predators.csv): captures are the predation-death counter's
    difference (exact), the exposure K x h x dt; K and no predator birth or refill at every horizon."""
    # Read ages before the adapter's general validation so missing / non-finite ages are
    # reported as scoring failures, just like out-of-range ages and the partition invariants.
    arena_path = os.path.join(d, "arena.json")
    arena = ckpt.load(arena_path, check=False)
    f0 = int(arena["world"]["frame"])
    start_ids = {int(i) for i, a in zip(arena["creatures"]["id"], arena["creatures"]["alive"]) if int(a)}
    n0 = len(start_ids)
    start_ages, max_age = _start_ages(arena, start_ids)
    ckpt.validate(arena, arena_path)
    k_arena = int(arena["predators"]["count"])
    if k_arena != k:
        raise ScoreError(f"the arena has {k_arena} predators, the cell asked for K = {k}")
    base = arena["counters"]
    if scripted:
        if fork or k < 1:
            raise ScoreError("a scripted assay has K >= 1 hunters and is not a fork")
        probs = scripted_problems(arena, k, "arena.json")
        if os.path.exists(os.path.join(d, "run.predators.csv")):
            probs.append("run.predators.csv exists (a neural metrics file: not a scripted assay)")
        if probs:
            raise ScoreError("not a scripted (Stage A) assay: " + "; ".join(probs))
        prow = []                                   # (no predator readout: the counters are the evidence)
    else:
        with open(os.path.join(d, "run.predators.csv")) as f:
            prow = read_predators_csv(f.read())
        steps_seen = [int(r["step"]) for r in prow]
        want = [f0 + m * log_every for m in range(1, steps // log_every + 1)]
        if steps_seen != want:
            raise ScoreError(f"predators.csv rows at {steps_seen[:3]}..., expected every {log_every} from "
                             f"{f0 + log_every} to {f0 + steps}")
    frozen = assay in FROZEN or scripted
    if fork:
        if k != 0:
            raise ScoreError(f"a predator-free fork with K = {k}")
        for r in prow:
            bad = {c: r[c] for c in ("predator_pop", "captures_interval", "births_interval", "reseeds_interval")
                   if int(r[c]) != 0}
            if bad:
                raise ScoreError(f"the predator-free fork has predators at step {r['step']}: {bad}")
    if frozen and not scripted:
        for r in prow:
            if int(r["predator_pop"]) != k:
                raise ScoreError(f"predator count {r['predator_pop']} at step {r['step']} in a frozen assay (K = {k})")
            for c in ("births_interval", "deaths_starv_interval", "deaths_age_interval", "reseeds_interval"):
                if int(r[c]) != 0:
                    raise ScoreError(f"{c} = {r[c]} at step {r['step']} in a frozen assay")
    out = []
    for h in horizons:
        if h % log_every or not 0 < h <= steps:
            raise ScoreError(f"horizon {h} is not a multiple of log_every {log_every} within {steps} steps")
        cp = ckpt.load(os.path.join(d, f"end.{f0 + h}.json"))
        if int(cp["world"]["frame"]) != f0 + h:
            raise ScoreError(f"end.{f0 + h}.json is at frame {cp['world']['frame']}")
        if frozen and int(cp["predators"]["count"]) != k:
            raise ScoreError(f"{cp['predators']['count']} predators at frame {f0 + h} in a frozen assay (K = {k})")
        if fork:
            moved = {c: int(cp["counters"].get(c, 0)) - int(base.get(c, 0)) for c in
                     ("totalPredatorBirths", "totalPredatorReseeds", "totalDeathsPredation")}
            if int(cp["predators"]["count"]) != 0 or any(moved.values()):
                raise ScoreError(f"the predator-free fork at frame {f0 + h}: {cp['predators']['count']} predators, "
                                 f"counter changes {moved}")
        rows = [r for r in prow if int(r["step"]) <= f0 + h]
        if scripted:
            probs = scripted_problems(cp, k, f"end.{f0 + h}.json")
            if probs:
                raise ScoreError("not a scripted (Stage A) assay: " + "; ".join(probs))
            moved = {c: int(cp["counters"].get(c, 0)) - int(base.get(c, 0)) for c in
                     ("totalPredatorBirths", "totalPredatorReseeds", "totalPredatorDeathsStarvation",
                      "totalPredatorDeathsAge")}
            if any(moved.values()):
                raise ScoreError(f"scripted hunters at frame {f0 + h}: predator counter changes {moved}")
            captures = int(cp["counters"].get("totalDeathsPredation", 0)) - int(base.get("totalDeathsPredation", 0))
            pred_s, pursuit_s, vbuds = k * h * DT, None, 0
        else:
            captures = sum(int(r["captures_interval"]) for r in rows)
            pred_s = sum(int(r["predator_pop"]) * log_every * DT for r in rows)
            pursuit_s = sum(float(r["pursuit_frac"]) * int(r["predator_pop"]) * log_every * DT for r in rows)
            vbuds = sum(int(r["virtual_buds_interval"]) for r in rows)
        cs = cp["creatures"]
        survivors = sum(1 for i, a in zip(cs["id"], cs["alive"]) if int(a) and int(i) in start_ids)
        alive_ids = {int(i) for i, a in zip(cs["id"], cs["alive"]) if int(a)}
        age_strata = _age_strata(start_ages, alive_ids, max_age, h, DT, n0, survivors)
        ctr = cp["counters"]
        dc = {key: int(ctr[key]) - int(base.get(key, 0)) for key in
              ("totalBirths", "totalDeaths", "totalDeathsPredation", "totalDeathsStarvation", "totalDeathsAge")}
        if dc["totalDeathsPredation"] != captures:
            raise ScoreError(f"horizon {h}: {dc['totalDeathsPredation']} predation deaths in the counters, "
                             f"{captures} captures in predators.csv")
        # (review round 3) prey replenishment: the prey alive now must be exactly the start plus
        # births minus deaths (a floor's injected founders are neither); and no prey that is not
        # of the initial cohort may be a founder (generation 0, or its own lineage)
        alive_now = sum(1 for a in cs["alive"] if int(a))
        injected = alive_now - (n0 + dc["totalBirths"] - dc["totalDeaths"])
        founders = [int(i) for i, a, ln, g in zip(cs["id"], cs["alive"], cs["lineageId"], cs["generation"])
                    if int(a) and int(i) not in start_ids and (int(g) == 0 or int(ln) == int(i))]
        if injected != 0 or founders:
            raise ScoreError(f"horizon {h}: prey replenished during the assay ({injected} beyond births and deaths; "
                             f"new founders {founders[:5]})")
        out.append({
            "steps": h, "frame": f0 + h, "captures": captures, "predator_seconds": pred_s,
            "exposure": "exact (fixed K)" if frozen else "sampled (count at each log row)",
            "capture_rate": _ratio(captures, pred_s), "virtual_buds": vbuds,
            "virtual_bud_rate": _ratio(vbuds, pred_s), "pursuit_seconds": pursuit_s,
            "captures_per_pursuit_s": _ratio(captures, pursuit_s) if pursuit_s is not None else None,
            "survivors": survivors, "survival": _ratio(survivors, n0),
            "age_strata": age_strata,
            "prey": int(cs["count"]), "predators": int(cp["predators"]["count"]),
            "births": dc["totalBirths"], "deaths": dc["totalDeaths"],
            "deaths_predation": dc["totalDeathsPredation"], "deaths_starvation": dc["totalDeathsStarvation"],
            "deaths_age": dc["totalDeathsAge"],
        })
    return {"schema": SCHEMA, "f0": f0, "k": k, "assay": assay, "n_start": n0, "dt": DT, "log_every": log_every,
            "steps": steps, "horizons": out,
            "scripted": scripted,
            "checks": {"rows": None if scripted else len(prow), "frozen_k_constant": frozen,
                       # (scripted: captures ARE the counter difference, so the equality holds by construction)
                       "predation_deaths_equal_captures": "by construction (scripted)" if scripted else True,
                       "scripted_inputs": ("arena and every horizon checkpoint: version 1, brain and economy off, "
                                           "K hunters; no predators.csv; no predator birth, refill or death")
                       if scripted else None,
                       "fork_predator_free": fork, "no_prey_replenishment": True}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--k", type=int, required=True)
    ap.add_argument("--steps", type=int, required=True)
    ap.add_argument("--horizons", required=True)
    ap.add_argument("--log-every", type=int, required=True)
    ap.add_argument("--assay", default="frozen")
    ap.add_argument("--fork", action="store_true", help="the predator-free continuation (K = 0)")
    ap.add_argument("--scripted", action="store_true", help="K scripted Stage A hunters (no predators.csv)")
    a = ap.parse_args(argv)
    try:
        res = score(a.dir, a.k, a.steps, [int(x) for x in a.horizons.split(",")], a.log_every, a.assay, a.fork,
                    a.scripted)
    except (ScoreError, ckpt.CheckpointError, OSError, KeyError, ValueError) as e:
        print(f"score.py: {e}", file=sys.stderr)
        return 1
    print(json.dumps(res, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
    (exact; the main CSV's first interval row can carry a loaded world's history);
  * age_strata (D8 v2 rule 48; age_strata() below): the initial cohort by START age, ten 12-second
    bins crossed with rule 46's age feasibility at that horizon (common.age_feasible: the engine's
    binary32 age clock), with counts, survival fractions (None for an empty denominator), the bin
    and feasibility totals and the identities. age_strata_problems() is its contract, checked here,
    at bundle creation, at completion verification and at ingestion.
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
import common  # noqa: E402  (the engine's binary32 age clock: the one feasibility definition)

SCHEMA = "finfolk.redqueen.score/1"
DT = 0.016          # main.cpp fixedDt
FROZEN = ("frozen", "frozen-newborn")
START_AGE_EDGES_S = tuple(range(0, 121, 12))  # fixed diagnostic bins; not the cell's maxAge
AGE_STRATA_SCHEMA = "finfolk.redqueen.agestrata/1"
AGE_BINS = ("start ages from arena.json at f0, keyed by live initial-cohort id; bins [0,12), [12,24), ..., "
            "[96,108), [108,120]: an interior edge belongs to the bin on its right, 120 to the last")
_STRATUM_KEYS = {"n_start", "survivors", "survival"}
_BIN_KEYS = _STRATUM_KEYS | {"feasible", "infeasible"}
_STRATA_KEYS = _STRATUM_KEYS | {"schema", "steps", "frame", "max_age_s", "dt_s", "age_clock", "bin_edges_s",
                                "bin_convention", "bins", "feasible", "infeasible"}


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


def _stratum(n, s):
    return {"n_start": n, "survivors": s, "survival": _ratio(s, n)}


def age_strata(start_ages, alive_ids, max_age, h, frame, dt, n_start, survivors):
    """D8 v2 rule 48's summary at horizon h: the initial cohort (start_ages: {live start id: START age})
    in ten 12-second start-age bins, each crossed with rule 46's age feasibility F_i(h), evaluated per
    individual by common.age_feasible (the engine's binary32 clock; never a+h*dt <= maxAge, never a
    bin midpoint). Every bin x feasibility stratum, every bin, both feasibility totals and the whole
    cohort carry n_start, survivors and survival (None for an empty denominator). n_start and
    survivors are the scorer's own totals, so the strata must reconcile to them; an age-infeasible
    survivor is impossible in the engine. Either failure refuses scoring (age_strata_problems)."""
    cnt = [[[0, 0], [0, 0]] for _ in START_AGE_EDGES_S[1:]]   # [bin][feasible, infeasible][n, survivors]
    for i, age in start_ages.items():
        # bisect puts interior edges in the bin on their right; the final edge is closed.
        b = min(bisect_right(START_AGE_EDGES_S, age) - 1, len(cnt) - 1)
        c = cnt[b][0 if common.age_feasible(age, h, max_age, dt) else 1]
        c[0] += 1
        c[1] += int(i in alive_ids)
    bins = [{**_stratum(f[0] + x[0], f[1] + x[1]), "feasible": _stratum(*f), "infeasible": _stratum(*x)}
            for f, x in cnt]
    rec = {"schema": AGE_STRATA_SCHEMA, "steps": h, "frame": frame, **_stratum(n_start, survivors),
           "max_age_s": max_age, "dt_s": dt, "age_clock": common.AGE_CLOCK,
           "bin_edges_s": list(START_AGE_EDGES_S), "bin_convention": AGE_BINS, "bins": bins}
    for k in ("feasible", "infeasible"):
        rec[k] = _stratum(sum(b[k]["n_start"] for b in bins), sum(b[k]["survivors"] for b in bins))
    probs = _strata_problems(rec, h, frame, n_start, survivors, dt)
    if probs:
        raise ScoreError(f"horizon {h}: " + "; ".join(probs))
    return rec


def _count(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _stratum_problems(s, what):
    if not isinstance(s, dict) or set(s) != _STRATUM_KEYS:
        return [f"{what} is not an n_start / survivors / survival record"]
    n, k = s["n_start"], s["survivors"]
    if not (_count(n) and _count(k) and k <= n):
        return [f"{what}: counts {n!r} / {k!r} are not 0 <= survivors <= n_start"]
    if isinstance(s["survival"], bool) or s["survival"] != _ratio(k, n) or (n == 0) != (s["survival"] is None):
        return [f"{what}: survival {s['survival']!r} is not survivors / n_start (None when n_start is 0)"]
    return []


def _strata_problems(a, steps, frame, n_start, survivors, dt):
    """One horizon's age_strata against the contract and the scorer's horizon, frame, totals and dt."""
    if not isinstance(a, dict):
        return ["age_strata is not a record"]
    if set(a) != _STRATA_KEYS:
        return [f"age_strata keys differ from the contract ({sorted(set(a) ^ _STRATA_KEYS)})"]
    probs = []
    if a["schema"] != AGE_STRATA_SCHEMA:
        probs.append(f"age_strata schema {a['schema']!r}, not {AGE_STRATA_SCHEMA}")
    if a["age_clock"] != common.AGE_CLOCK:
        probs.append(f"age predicate {a['age_clock']!r}, not {common.AGE_CLOCK}")
    if (a["steps"], a["frame"]) != (steps, frame):
        probs.append(f"age_strata for steps / frame {a['steps']} / {a['frame']}, the horizon is {steps} / {frame}")
    if a["dt_s"] != dt:
        probs.append(f"age_strata dt {a['dt_s']!r}, the score's is {dt!r}")
    m = a["max_age_s"]
    if isinstance(m, bool) or not isinstance(m, (int, float)) or not math.isfinite(m) or m < 0:
        probs.append(f"age_strata maxAge {m!r} is not a finite age")
    if a["bin_edges_s"] != list(START_AGE_EDGES_S) or a["bin_convention"] != AGE_BINS:
        probs.append("age_strata bins are not the fixed 12-second start-age bins")
    probs += _stratum_problems({k: a[k] for k in _STRATUM_KEYS}, "the cohort total")
    if (a["n_start"], a["survivors"]) != (n_start, survivors):
        probs.append(f"the cohort total {a['n_start']} / {a['survivors']} is not the scorer's n_start / survivors "
                     f"{n_start} / {survivors}")
    bins = a["bins"]
    if not isinstance(bins, list) or len(bins) != len(START_AGE_EDGES_S) - 1:
        return probs + ["age_strata does not hold ten bins"]
    sums = {k: [0, 0] for k in ("bins", "feasible", "infeasible")}
    for j, b in enumerate(bins):
        what = f"bin {START_AGE_EDGES_S[j]}-{START_AGE_EDGES_S[j + 1]} s"
        if not isinstance(b, dict) or set(b) != _BIN_KEYS:
            probs.append(f"{what} is not a bin x feasibility record")
            continue
        counted = True
        for k, s, w in (("bins", {x: b[x] for x in _STRATUM_KEYS}, what), ("feasible", b["feasible"], what + " feasible"),
                        ("infeasible", b["infeasible"], what + " infeasible")):
            probs += _stratum_problems(s, w)
            if isinstance(s, dict) and _count(s.get("n_start")) and _count(s.get("survivors")):
                sums[k][0] += s["n_start"]
                sums[k][1] += s["survivors"]
            else:
                counted = False
        if counted:
            for x in ("n_start", "survivors"):
                if b["feasible"][x] + b["infeasible"][x] != b[x]:
                    probs.append(f"{what}: feasible + infeasible {x} is not the bin's")
    for k in ("feasible", "infeasible"):
        p = _stratum_problems(a[k], f"the {k} total")
        probs += p
        if not p and [a[k]["n_start"], a[k]["survivors"]] != sums[k]:
            probs.append(f"the {k} total {a[k]['n_start']} / {a[k]['survivors']} is not the sum of its bins "
                         f"{sums[k][0]} / {sums[k][1]}")
    if sums["bins"] != [n_start, survivors]:
        probs.append(f"the bins sum to {sums['bins'][0]} / {sums['bins'][1]}, not the scorer's n_start / survivors "
                     f"{n_start} / {survivors}")
    if isinstance(a["infeasible"], dict) and a["infeasible"].get("survivors") != 0:
        probs.append("age-infeasible initial prey survived (impossible on the engine's binary32 age clock)")
    return probs


def age_strata_problems(sc, horizons=None):
    """Why a score lacks rule 48's complete age summary -> problems ([] = complete): every horizon
    record (and, given the cell's registered `horizons`, exactly those, in order) must carry an
    age_strata that satisfies the contract (_strata_problems) and reconciles with that horizon's
    steps, frame and survivors and the score's n_start and dt. A missing summary is a recording
    omission (repair it or record a deviation), never zero survival."""
    if not isinstance(sc, dict) or not isinstance(sc.get("horizons"), list) or not sc["horizons"]:
        return ["the score has no horizon records"]
    hs = sc["horizons"]
    probs = []
    steps = [h.get("steps") if isinstance(h, dict) else None for h in hs]
    if horizons is not None and (not isinstance(horizons, (list, tuple)) or steps != list(horizons)):
        probs.append(f"the scored horizons {steps} are not the cell's registered horizons {horizons!r}")
    for h in hs:
        if not isinstance(h, dict):
            probs.append("a horizon record is not an object")
        elif "age_strata" not in h:
            probs.append(f"horizon {h.get('steps')}: no age_strata (a recording omission, not zero survival)")
        else:
            probs += [f"horizon {h.get('steps')}: {p}" for p in
                      _strata_problems(h["age_strata"], h.get("steps"), h.get("frame"), sc.get("n_start"),
                                       h.get("survivors"), sc.get("dt"))]
    return probs


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
        strata = age_strata(start_ages, alive_ids, max_age, h, f0 + h, DT, n0, survivors)
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
            "age_strata": strata,
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

#!/usr/bin/env python3
"""arena.py: build one invasion arena checkpoint (Classic engine) from two snapshots.

    arena.py --resident J.json [--invader I.json] --mode invade|sham|self
             [--fraction 0.05] [--state slot|carry] [--predators K]
             --slot-seed S1 [--donor-seed S2] [--pred-seed S3]
             --out ARENA.json --manifest ARENA.manifest.json [--binary EVO_BOIDS]

The arena is J's world (food, pheromones, frame, rng state, every resident)
with m = round(fraction * n_J) of J's fish (the "slots", chosen with
--slot-seed) replaced, so the population size is unchanged:

  invade  each slot gets a fish sampled from I (--donor-seed), marked invader.
  sham    each slot gets a fish sampled from J itself (the self-invasion
          baseline s(j->j) by the SAME procedure). With the same --slot-seed
          and the same rng reseed as a paired invade arena, it is that arena's
          paired fork: same slots, same random stream, only the donors differ.
  self    no swap: the m slot fish are marked in place (a pure-label null).

--state decides what a swapped-in fish keeps:
  slot   (default) it takes the replaced resident's physical and physiological
         state (position, velocity, heading, speed, body trail, age, reserves,
         repro/interact timers) and brings its own genome, recurrent neuron
         outputs, responsiveness, oscillator, body parameters, generation and
         lineage. Invaders then differ from residents in heritable traits and
         brain state only, not in the age/energy their home world happened to
         be in when it was saved (food abundance cycles every ~6,300 steps).
  carry  it keeps all its own state except the position slot (pos, velocity,
         heading and trail come from the slot, so nobody lands on top of a
         resident).

Every swapped-in fish gets a fresh id (J's nextId upward; nextId is bumped).

The condition's dials are written into the 'config' block (a resume ignores the
CLI, main.cpp) and HELD FIXED whatever the home runs used: minPopulation 0 (no
reseeding: every id handed out during the run is a newborn, which is what lets
score.py derive child ids), maxPopulation 0, fastTanh off, reproMaxDistance off,
soft gate and grace off, geneCost 0, the predator economy off. Predators: J's
are removed; with --predators K > 0, K fresh Stage A predators are injected
(random position in [10, size-10], random heading, digestTimer 0, energy
predatorNewbornEnergy, age 0, traits 1.0/1.0, generation 0: exactly the state
World::init gives a spawned predator) and the Stage A dials are set to their
defaults. The birth-log counters are reset (totalBirthsLogged 0, reproStride 1)
so a --repro-log run of the arena keeps every event.

The manifest records the sources (paths, SHA-256), the slots and the donors
(old and new ids), the marked ids, the fractions, the seeds, every config
change, the predators, and the output's SHA-256.
"""
from __future__ import annotations

import argparse
import copy
import datetime
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import invlib  # noqa: E402

SCHEMA = "finfolk.invasion.arena/1"

# SimConfig defaults for the Stage A dials (src/core/config.hpp); the arena sets
# them explicitly so a home run's own predator settings never leak in.
STAGE_A = {"predatorPerception": 150.0, "predatorSpeed": 110.0,
           "predatorCaptureRadius": 14.0, "predatorCooldown": 3.0}
HELD = {"minPopulation": 0, "maxPopulation": 0, "fastTanh": False,
        "reproMaxDistance": -1.0, "reproSoftWidth": 0.0, "reproGracePeriod": 0.0,
        "geneCost": 0.0, "predatorEconomy": False, "predatorMinPopulation": 0,
        "predatorMaxPopulation": 0, "predatorInheritance": False}
# Keys that may legitimately differ between the two source worlds (they are
# overwritten above, or are the predator setting of the home run).
OVERRIDDEN = set(HELD) | set(STAGE_A) | {"predatorCount", "predatorNewbornEnergy",
                                         "predatorMetabolism", "predatorMoveCost",
                                         "predatorReproEnergy", "predatorMeal",
                                         "predatorMaxAge", "predatorTraitMutation"}

# What a swapped-in fish takes from the slot it fills.
SLOT_KINEMATIC = ["posX", "posY", "velX", "velY", "lastMoveDirX", "lastMoveDirY", "speed"]
SLOT_PHYSIOLOGY = ["age", "foodReserves", "reproTimer", "interactTimer"]


def _same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    return a == b


def build(resident_path, invader_path, mode, fraction, state, predators, slot_seed,
          donor_seed, pred_seed, binary=None, allow_mismatch=False):
    if mode not in ("invade", "sham", "self"):
        raise SystemExit(f"unknown mode {mode}")
    if state not in ("slot", "carry"):
        raise SystemExit(f"unknown state policy {state}")
    if not (0.0 < fraction < 1.0):
        raise SystemExit("--fraction must be in (0, 1)")
    if mode == "invade" and not invader_path:
        raise SystemExit("--mode invade needs --invader")
    if mode != "invade" and invader_path:
        raise SystemExit(f"--mode {mode} takes its donors from the resident; drop --invader")
    if predators < 0:
        raise SystemExit("--predators must be >= 0")

    J = invlib.load_checkpoint(resident_path)
    jrows = invlib.creature_rows(J)
    if any(int(r["alive"]) == 0 for r in jrows):
        raise SystemExit(f"{resident_path}: has dead creatures (not an end-of-step checkpoint)")
    if not str(J.get("determinism", "")).startswith("serial build"):
        raise SystemExit(f"{resident_path}: not written by a serial build")
    n = len(jrows)
    m = int(math.floor(fraction * n + 0.5))
    if m < 1 or m >= n:
        raise SystemExit(f"fraction {fraction} of {n} fish gives m={m}")

    warnings = []
    if mode == "invade":
        I = invlib.load_checkpoint(invader_path)
        donors_pool = invlib.creature_rows(I)
        if (I["world"]["width"], I["world"]["height"]) != (J["world"]["width"], J["world"]["height"]):
            raise SystemExit("resident and invader worlds have different sizes")
        if I.get("engineVersion") != J.get("engineVersion"):
            warnings.append(f"engineVersion differs: resident {J.get('engineVersion')}, invader {I.get('engineVersion')}")
        diffs = {k: [J["config"].get(k), I["config"].get(k)]
                 for k in sorted(set(J["config"]) | set(I["config"]))
                 if k not in OVERRIDDEN and not _same(J["config"].get(k), I["config"].get(k))}
        if diffs and not allow_mismatch:
            raise SystemExit(f"resident and invader configs differ beyond the held dials: {diffs}")
        if diffs:
            warnings.append(f"config differs (allowed): {diffs}")
        if any(int(r["alive"]) == 0 for r in donors_pool):
            raise SystemExit(f"{invader_path}: has dead creatures")
    else:
        donors_pool = jrows

    out = copy.deepcopy(J)
    rows = [dict(r) for r in jrows]
    rng_slot = invlib.Rng(slot_seed)
    slots = rng_slot.sample(n, m)

    next_id = int(J["world"]["nextId"])
    max_id = max(int(r["id"]) for r in jrows)
    if next_id <= max_id:
        raise SystemExit(f"{resident_path}: nextId {next_id} does not exceed max id {max_id}")

    swapped = []
    marked = []
    if mode == "self":
        for s in slots:
            marked.append(int(rows[s]["id"]))
            swapped.append({"slot": s, "id": int(rows[s]["id"])})
    else:
        if donor_seed is None:
            raise SystemExit(f"--mode {mode} needs --donor-seed")
        rng_donor = invlib.Rng(donor_seed)
        nd = len(donors_pool)
        if m <= nd:
            picks = rng_donor.sample(nd, m)
        else:
            picks = [rng_donor.below(nd) for _ in range(m)]
            warnings.append(f"donor pool ({nd}) smaller than m ({m}): sampled with replacement")
        for s, p in zip(slots, picks):
            slot_row = rows[s]
            donor = donors_pool[p]
            new = dict(donor)
            new["neurons"] = list(donor["neurons"])
            new["genes"] = list(donor["genes"])
            # kinematics always from the slot (nobody lands on top of a resident)
            for k in SLOT_KINEMATIC:
                new[k] = slot_row[k]
            new["body"] = list(slot_row["body"])
            if state == "slot":
                for k in SLOT_PHYSIOLOGY:
                    new[k] = slot_row[k]
            new["id"] = next_id
            next_id += 1
            new["alive"] = 1
            # lineageId == id is the founder predicate (kernel::reproGraced); grace
            # is held off, but never let a transplanted fish satisfy it by accident.
            if int(new["lineageId"]) == int(new["id"]):
                new["lineageId"] = 0
            rows[s] = new
            marked.append(int(new["id"]))
            swapped.append({"slot": s, "replaced_id": int(slot_row["id"]),
                            "donor_index": p, "donor_id": int(donor["id"]), "id": int(new["id"])})
    invlib.set_creature_rows(out, rows)
    out["world"]["nextId"] = next_id

    # counters: a fresh birth archive for this run
    out["counters"]["totalBirthsLogged"] = 0
    out["counters"]["reproStride"] = 1

    # the condition's dials
    cfg = out["config"]
    changes = {}

    def setc(k, v):
        old = cfg.get(k)
        if k not in cfg or not _same(old, v):
            changes[k] = [old, v]
        cfg[k] = v

    for k, v in HELD.items():
        setc(k, v)
    setc("predatorCount", predators)
    for k, v in STAGE_A.items():
        setc(k, v)

    # predators: J's are dropped; K fresh Stage A hunters (World::init's spawn state)
    W, H = float(J["world"]["width"]), float(J["world"]["height"])
    newborn_e = float(cfg.get("predatorNewbornEnergy", 30.0))
    preds = []
    if predators > 0:
        if pred_seed is None:
            raise SystemExit("--predators > 0 needs --pred-seed")
        rp = invlib.Rng(pred_seed)
        for _ in range(predators):
            x = 10.0 + (W - 20.0) * rp.unit()
            y = 10.0 + (H - 20.0) * rp.unit()
            a = 6.2832 * rp.unit()
            preds.append({"posX": x, "posY": y, "velX": math.cos(a), "velY": math.sin(a),
                          "digestTimer": 0, "energy": newborn_e, "age": 0, "alive": 1,
                          "speedFactor": 1, "buddingFactor": 1, "generation": 0})
    out["predators"] = {"count": len(preds)}
    for k in invlib.PREDATOR_COLS:
        out["predators"][k] = [p[k] for p in preds]

    ids = [int(r["id"]) for r in rows]
    if len(set(ids)) != len(ids):
        raise SystemExit("internal error: duplicate ids in the arena")

    manifest = {
        "schema": SCHEMA,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode, "state": state,
        "resident": {"path": os.path.abspath(resident_path), "sha256": invlib.sha256_file(resident_path),
                     "frame": int(J["world"]["frame"]), "nextId": int(J["world"]["nextId"]), "n": n,
                     "predators": int(J["predators"]["count"])},
        "invader": None if mode != "invade" else {
            "path": os.path.abspath(invader_path), "sha256": invlib.sha256_file(invader_path),
            "frame": int(I["world"]["frame"]), "n": len(donors_pool), "predators": int(I["predators"]["count"])},
        "fraction_requested": fraction, "m": m, "n": n, "fraction": m / n,
        "seeds": {"slot": slot_seed, "donor": donor_seed, "pred": pred_seed},
        "swapped": swapped, "marked_ids": sorted(marked),
        "predators": {"count": predators, "state": preds},
        "config_changes": changes,
        "start": {"frame": int(out["world"]["frame"]), "nextId": next_id,
                  "totalBirthsLogged": 0, "totalBirths": int(out["counters"]["totalBirths"])},
        "warnings": warnings,
    }
    if binary:
        manifest["binary"] = {"path": os.path.abspath(binary), "sha256": invlib.sha256_file(binary)}
    return out, manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--resident", required=True)
    ap.add_argument("--invader")
    ap.add_argument("--mode", required=True, choices=["invade", "sham", "self"])
    ap.add_argument("--fraction", type=float, default=0.05)
    ap.add_argument("--state", default="slot", choices=["slot", "carry"])
    ap.add_argument("--predators", type=int, default=0)
    ap.add_argument("--slot-seed", type=int, required=True)
    ap.add_argument("--donor-seed", type=int)
    ap.add_argument("--pred-seed", type=int)
    ap.add_argument("--out", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--binary")
    ap.add_argument("--allow-config-mismatch", action="store_true")
    a = ap.parse_args(argv)
    cp, man = build(a.resident, a.invader, a.mode, a.fraction, a.state, a.predators,
                    a.slot_seed, a.donor_seed, a.pred_seed, a.binary, a.allow_config_mismatch)
    invlib.write_atomic(a.out, invlib.dumps_checkpoint(cp))
    man["output"] = {"path": os.path.abspath(a.out), "sha256": invlib.sha256_file(a.out)}
    invlib.write_json_atomic(a.manifest, man)
    for w in man["warnings"]:
        print("warning:", w, file=sys.stderr)
    print(f"arena {a.out}: {man['mode']} m={man['m']}/{man['n']} predators={a.predators} nextId={man['start']['nextId']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

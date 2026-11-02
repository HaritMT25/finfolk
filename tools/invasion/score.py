#!/usr/bin/env python3
"""score.py: invader-ancestry score of one arena run, with the child-id derivation checked.

    score.py --arena ARENA.json --manifest ARENA.manifest.json --births RUN.births.csv
             --checkpoint END.json [--checkpoint MID.json ...] [--out SCORE.json]

The engine's birth log (--repro-log) records each pairing's parents but not the
child's id. On an arena resume no id is handed out except to newborns
(minPopulation 0 => no reseed; markFounder runs only at init and in the reseed,
world.hpp), newborns are numbered in the order their births are logged
(world.hpp: `baby.id = nextId_++` over the newborns vector, which is filled in
recordPairing order), and logBirth gives every birth one ordinal, decimated or
not (world_common.hpp). So

    child id = start nextId + (index - start totalBirthsLogged).

That is CHECKED, not assumed, on every run; any failure exits 1 with the reason:
  * the log is complete: decimation stride 1, kept == seen - start ordinal, the
    indices are exactly start..seen-1 in order, frames non-decreasing and after
    the start frame;
  * the arena's config really has minPopulation 0;
  * every parent is a start id or an EARLIER derived id;
  * for every checkpoint C: the births with frame <= C.frame are exactly
    C.nextId - start nextId (max derived id == C.nextId - 1), the engine's own
    totalBirths agrees, its ids are unique, and every live id is a start id or a
    derived id; the last checkpoint is the end of the log.

Ancestry: marked (invader) founders 1, every other start fish 0, a child the
mean of its parents. Score at C: mean live ancestry - start fraction (m/n).
Generation turnover: the steps until cumulative births reach k * n_start
(k = 1, 2, ...), the first being "one generation".
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import invlib  # noqa: E402

SCHEMA = "finfolk.invasion.score/1"


class DerivationError(Exception):
    pass


def need(cond, msg):
    if not cond:
        raise DerivationError(msg)


def read_births(path):
    seen = kept = stride = None
    rows = []
    with open(path) as f:
        header = None
        for ln in f:
            if ln.startswith("#"):
                m = re.search(r"events seen:\s*(\d+)\s+kept:\s*(\d+)\s+decimation stride:\s*(\d+)", ln)
                if m:
                    seen, kept, stride = (int(x) for x in m.groups())
                continue
            if header is None:
                header = ln.strip().split(",")
                need(header == ["index", "frame", "parent1", "parent2", "lineage1", "lineage2"],
                     f"unexpected births.csv header {header}")
                continue
            p = ln.strip().split(",")
            if len(p) != 6:
                continue
            rows.append((int(p[0]), int(p[1]), int(p[2]), int(p[3])))
    need(seen is not None, f"{path}: no 'events seen / kept / stride' comment line")
    return seen, kept, stride, rows


def score(arena_path, manifest_path, births_path, checkpoint_paths):
    man = json.load(open(manifest_path))
    A = invlib.load_checkpoint(arena_path)
    need(invlib.sha256_file(arena_path) == man["output"]["sha256"], "arena file does not match its manifest")
    need(int(A["config"]["minPopulation"]) == 0, "arena config minPopulation is not 0 (reseeds would mint ids)")
    start_next = int(A["world"]["nextId"])
    start_ord = int(A["counters"]["totalBirthsLogged"])
    start_frame = int(A["world"]["frame"])
    start_births = int(A["counters"]["totalBirths"])
    start_ids = invlib.live_ids(A)
    n0 = len(start_ids)
    start_set = set(start_ids)
    marked = set(int(x) for x in man["marked_ids"])
    need(marked <= set(start_ids), "manifest marks ids that are not in the arena")
    frac0 = len(marked) / n0
    anc = {i: (1.0 if i in marked else 0.0) for i in start_ids}

    seen, kept, stride, rows = read_births(births_path)
    need(stride == 1, f"birth log decimated (stride {stride}): raise --repro-log-max")
    need(kept == len(rows), f"births.csv says kept {kept}, has {len(rows)} rows")
    need(kept == seen - start_ord, f"kept {kept} != seen {seen} - start ordinal {start_ord}")
    prev_frame = start_frame
    born = []   # (frame, child id)
    for k, (idx, frame, p1, p2) in enumerate(rows):
        need(idx == start_ord + k, f"birth row {k}: index {idx}, expected {start_ord + k}")
        need(frame > start_frame and frame >= prev_frame, f"birth {idx}: frame {frame} out of order")
        prev_frame = frame
        need(p1 in anc and p2 in anc, f"birth {idx}: parent {p1 if p1 not in anc else p2} is neither a start id nor an earlier child")
        cid = start_next + (idx - start_ord)
        need(cid not in anc, f"birth {idx}: derived id {cid} collides")
        anc[cid] = 0.5 * (anc[p1] + anc[p2])
        born.append((frame, cid))

    # generation turnover: steps until cumulative births reach k * n0
    turnover = []
    for k in range(1, len(born) // n0 + 1):
        turnover.append(born[k * n0 - 1][0] - start_frame)

    results = []
    cps = []
    for path in checkpoint_paths:
        C = invlib.load_checkpoint(path)
        cps.append((int(C["world"]["frame"]), path, C))
    cps.sort(key=lambda t: t[0])
    need(cps, "no checkpoint given")
    for frame, path, C in cps:
        need(frame > start_frame, f"{path}: frame {frame} is not after the arena's {start_frame}")
        nb = sum(1 for f, _ in born if f <= frame)
        cnext = int(C["world"]["nextId"])
        need(cnext - start_next == nb, f"{path}: nextId {cnext} - start {start_next} != births up to frame {frame} ({nb})")
        if nb:
            need(born[nb - 1][1] == cnext - 1, f"{path}: max derived id {born[nb - 1][1]} != nextId - 1 ({cnext - 1})")
        need(int(C["counters"]["totalBirths"]) - start_births == nb, f"{path}: engine totalBirths disagrees with the log")
        ids = invlib.live_ids(C)
        need(len(ids) == int(C["creatures"]["count"]), f"{path}: has dead creatures")
        need(len(set(ids)) == len(ids), f"{path}: duplicate ids")
        valid = start_set | {cid for f, cid in born[:nb]}
        bad = [i for i in ids if i not in valid]
        need(not bad, f"{path}: live ids neither start nor derived: {bad[:5]}")
        a = [anc[i] for i in ids]
        n = len(a)
        mean = sum(a) / n if n else None
        results.append({
            "checkpoint": os.path.basename(path), "frame": frame, "steps": frame - start_frame,
            "births": nb, "generations": nb / n0, "n": n,
            "mean_ancestry": mean, "score": (mean - frac0) if n else None,
            "n_any_invader": sum(1 for x in a if x > 0), "n_pure_invader": sum(1 for x in a if x == 1.0),
            "n_founders_alive": sum(1 for i in ids if i in start_set),
            "extinct": n == 0, "invader_lost": n > 0 and all(x == 0 for x in a),
            "predators": int(C["predators"]["count"]),
        })
    last_frame = cps[-1][0]
    need(all(f <= last_frame for f, _ in born), "births logged after the last checkpoint (it is not the run's end)")
    need(seen == int(cps[-1][2]["counters"]["totalBirthsLogged"]), "end checkpoint's totalBirthsLogged != births seen")

    return {
        "schema": SCHEMA,
        "arena_sha256": man["output"]["sha256"], "births_sha256": invlib.sha256_file(births_path),
        "mode": man["mode"], "m": len(marked), "n0": n0, "start_fraction": frac0,
        "start_frame": start_frame, "start_nextId": start_next, "start_ordinal": start_ord,
        "births": len(born), "turnover_steps": turnover,
        "derivation": {"ok": True, "checked_births": len(born), "checked_checkpoints": len(cps),
                       "max_derived_id": born[-1][1] if born else None,
                       "end_nextId": int(cps[-1][2]["world"]["nextId"])},
        "points": results,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--arena", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--births", required=True)
    ap.add_argument("--checkpoint", action="append", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        res = score(a.arena, a.manifest, a.births, a.checkpoint)
    except DerivationError as e:
        print(f"score.py: DERIVATION CHECK FAILED: {e}", file=sys.stderr)
        return 1
    if a.out:
        invlib.write_json_atomic(a.out, res)
    last = res["points"][-1]
    print(f"score: births={res['births']} gen1={res['turnover_steps'][:1]} end n={last['n']} "
          f"score={last['score']} (derivation ok over {res['births']} births, {len(res['points'])} checkpoints)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""plan.py: expand an invasion design (JSON) into a runner plan (JSONL, one cell per line).

    plan.py DESIGN.json > PLAN.jsonl

DESIGN.json:
  {
    "name": "pilot1",
    "snapshots": {"A": "/abs/path/A.json", "B": "/abs/path/B.json", ...},
    "conditions": {"off": 0, "predA4": 4},       # name -> Stage A predator count
    "fractions": [0.05, 0.15],
    "replicates": 10,
    "state": "slot",
    "steps": 30000,                               # or {"A": 27000, ...} per resident
    "checkpoint_every": 2000,                     # or per resident; 0 = end only
    "log_every": 1000,
    "keep_intermediate": false,
    "matrix": ["A", "B", "C"],                    # all ordered pairs + every diagonal sham
    "pairs": [["A", "B"], ...],                   # extra invade cells i -> j (both orders if "both": true)
    "both": true,
    "shams": ["A", ...],                          # extra j -> j sham cells
    "selfs": ["A", ...]                           # extra mark-in-place cells
  }

Snapshots are registered by path AND content: every cell carries the SHA-256
of its resident (and invader) file as it was at planning time
(resident_sha256 / invader_sha256). run.py refuses to build an arena from a
file whose content changed since, and analyze.py checks that every cell of
one item read the same file, so a snapshot overwritten between batch attempts
cannot mix two populations under one name.

Seeds are derived (SHA-256 of their parts) so that the arena of i -> j,
replicate r, and the sham j -> j, replicate r, share the SLOT seed (same
replaced fish), the PREDATOR seed and the engine RESEED: only the donors
differ. The sham j -> j / r is therefore the paired fork of every i -> j / r,
and s~(i->j) = mean_r [s(i->j, r) - s(j->j, r)] is a paired difference at no
extra cost. The slot seed does not depend on the condition, so the predators-
off and -on arenas of one (j, r) replace the same fish.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import invlib  # noqa: E402


def fr_tag(f):
    return f"f{int(round(f * 1000)):03d}"


def per(v, key):
    return v[key] if isinstance(v, dict) else v


def expand(design):
    snaps = design["snapshots"]
    for k, p in snaps.items():
        if not os.path.isabs(p):
            raise SystemExit(f"snapshot {k}: path must be absolute")
        if any(ch in k for ch in "/_ "):
            raise SystemExit(f"snapshot name {k!r}: no '/', '_' or spaces")
    conds = design["conditions"]
    reps = int(design["replicates"])
    state = design.get("state", "slot")
    cells_ij = set()
    for name in design.get("matrix", []):
        cells_ij.add((name, name, "sham"))
    mat = design.get("matrix", [])
    for i in mat:
        for j in mat:
            if i != j:
                cells_ij.add((i, j, "invade"))
    for i, j in design.get("pairs", []):
        cells_ij.add((i, j, "invade"))
        cells_ij.add((j, j, "sham"))
        if design.get("both"):
            cells_ij.add((j, i, "invade"))
            cells_ij.add((i, i, "sham"))
    for j in design.get("shams", []):
        cells_ij.add((j, j, "sham"))
    for j in design.get("selfs", []):
        cells_ij.add((j, j, "self"))
    used = {n for i, j, mode in cells_ij for n in ((i, j) if mode == "invade" else (j,))}
    for n in used:
        if n not in snaps:
            raise SystemExit(f"unknown snapshot {n}")
    digest = {n: invlib.sha256_file(snaps[n]) for n in sorted(used)}
    out = []
    order = {"sham": 0, "self": 1, "invade": 2}
    for frac in design["fractions"]:
        for cname, K in conds.items():
            for r in range(reps):
                for (i, j, mode) in sorted(cells_ij, key=lambda t: (t[1], order[t[2]], t[0])):
                    for n in (i, j):
                        if n not in snaps:
                            raise SystemExit(f"unknown snapshot {n}")
                    cid = f"{cname}_{fr_tag(frac)}_{j}_{'sham' if mode == 'sham' else ('self' if mode == 'self' else i)}_r{r:02d}"
                    out.append({
                        "id": cid, "design": design.get("name", ""),
                        "resident": snaps[j], "resident_name": j, "resident_sha256": digest[j],
                        "invader": snaps[i] if mode == "invade" else None,
                        "invader_sha256": digest[i] if mode == "invade" else None,
                        "invader_name": i, "mode": mode, "fraction": frac, "state": state,
                        "condition": cname, "predators": int(K), "replicate": r,
                        "slot_seed": invlib.derive_seed("slot", j, fr_tag(frac), r),
                        "donor_seed": None if mode == "self" else invlib.derive_seed("donor", i, j, fr_tag(frac), r),
                        "pred_seed": invlib.derive_seed("pred", j, cname, r) if K > 0 else None,
                        "reseed": invlib.derive_seed("reseed", j, fr_tag(frac), cname, r),
                        "steps": int(per(design["steps"], j)),
                        "checkpoint_every": int(per(design.get("checkpoint_every", 0), j)),
                        "log_every": int(design.get("log_every", 1000)),
                        "keep_intermediate": bool(design.get("keep_intermediate", False)),
                    })
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    design = json.load(open(argv[0]))
    for c in expand(design):
        print(json.dumps(c, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

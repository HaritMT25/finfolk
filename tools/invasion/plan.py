#!/usr/bin/env python3
"""plan.py: expand an invasion design (JSON) into a runner plan (JSONL, one cell per line).

    plan.py DESIGN.json [--avoid OLD_PLAN.jsonl ...] > PLAN.jsonl

--avoid: refuse (exit 2) if any seed of the new plan equals any seed of an archived plan.

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
    "selfs": ["A", ...],                          # extra mark-in-place cells
    "cores": [["np", ["A", "B", ...]], ["p4", [...]]],   # separate home-regime cores: every ordered
                                                  # pair WITHIN each core + its shams, no cross-core cell
    "seed_scheme": {...}                          # optional, see below
  }

Seed schemes. Default ('derived'): SHA-256 of the cell's parts (below). 'indexed' (review round 3:
an explicit, registered allocation in a namespace of its own; changing design.name does not change
derived seeds): needs "cores" of equal size M, one fraction, and "assays" (the condition order).
With core h, resident index j, invader index i (within the core), replicate r (of R), assay a:
    u = R (M h + j) + r
    slot_seed  = slot_base + u                  (shared by every cell of column-replicate (j, r))
    donor_seed = donor_base + M u + i           (i = j for the sham)
    pred_seed  = pred_base + u                  (Stage A conditions only)
    reseed     = reseed_base + A u + a          (A assays; shared by invade and sham cells)
  "seed_scheme": {"type": "indexed", "namespace": "bank1", "slot_base": 1000000000,
                  "donor_base": 1100000000, "pred_base": 1200000000, "reseed_base": 2000000000,
                  "assays": ["off", "predA4"]}
Every seed must stay below 2^32 (the engine parses an unsigned 32-bit reseed).

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
    cores = design.get("cores", [])
    core_of = {}   # name -> (core index h, index within the core)
    for h, (cname_, members) in enumerate(cores):
        for idx, n in enumerate(members):
            if n in core_of:
                raise SystemExit(f"snapshot {n} is in two cores")
            core_of[n] = (h, idx)
        for i in members:
            cells_ij.add((i, i, "sham"))
            for j in members:
                if i != j:
                    cells_ij.add((i, j, "invade"))
    scheme = design.get("seed_scheme", {"type": "derived"})
    if scheme["type"] == "indexed":
        if not cores or len({len(m) for _, m in cores}) != 1:
            raise SystemExit("seed_scheme indexed: needs 'cores' of equal size")
        if len(design["fractions"]) != 1:
            raise SystemExit("seed_scheme indexed: one fraction only (the formulas do not include it)")
        if sorted(scheme["assays"]) != sorted(design["conditions"]):
            raise SystemExit("seed_scheme indexed: 'assays' must list every condition once")
        if any(mode == "self" or i not in core_of or j not in core_of or core_of[i][0] != core_of[j][0]
               for i, j, mode in cells_ij):
            raise SystemExit("seed_scheme indexed: every cell must lie inside one core")
    elif scheme["type"] != "derived":
        raise SystemExit(f"unknown seed_scheme {scheme['type']!r}")
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
                    if scheme["type"] == "indexed":
                        M, A = len(cores[0][1]), len(scheme["assays"])
                        h, jj = core_of[j]
                        ii = core_of[i][1]
                        u = reps * (M * h + jj) + r
                        seeds = {"slot_seed": scheme["slot_base"] + u,
                                 "donor_seed": scheme["donor_base"] + M * u + ii,
                                 "pred_seed": scheme["pred_base"] + u if K > 0 else None,
                                 "reseed": scheme["reseed_base"] + A * u + scheme["assays"].index(cname)}
                    else:
                        seeds = {"slot_seed": invlib.derive_seed("slot", j, fr_tag(frac), r),
                                 "donor_seed": None if mode == "self" else invlib.derive_seed("donor", i, j, fr_tag(frac), r),
                                 "pred_seed": invlib.derive_seed("pred", j, cname, r) if K > 0 else None,
                                 "reseed": invlib.derive_seed("reseed", j, fr_tag(frac), cname, r)}
                    cell = {
                        "id": cid, "design": design.get("name", ""),
                        "resident": snaps[j], "resident_name": j, "resident_sha256": digest[j],
                        "invader": snaps[i] if mode == "invade" else None,
                        "invader_sha256": digest[i] if mode == "invade" else None,
                        "invader_name": i, "mode": mode, "fraction": frac, "state": state,
                        "condition": cname, "predators": int(K), "replicate": r, **seeds,
                        "steps": int(per(design["steps"], j)),
                        "checkpoint_every": int(per(design.get("checkpoint_every", 0), j)),
                        "log_every": int(design.get("log_every", 1000)),
                        "keep_intermediate": bool(design.get("keep_intermediate", False)),
                    }
                    if scheme["type"] == "indexed":
                        cell["seed_namespace"] = scheme.get("namespace", "")
                    if cores:
                        cell["core"] = cores[core_of[j][0]][0] if j in core_of else None
                    for kk in ("slot_seed", "donor_seed", "pred_seed", "reseed"):
                        if cell[kk] is not None and not 0 <= cell[kk] < 2 ** 32:
                            raise SystemExit(f"{cid}: {kk} {cell[kk]} outside [0, 2^32)")
                    out.append(cell)
    return out


SEED_KEYS = ("slot_seed", "donor_seed", "pred_seed", "reseed")


def seed_values(cells):
    return {c[k] for c in cells for k in SEED_KEYS if c.get(k) is not None}


def collisions(cells, avoid_paths):
    """Seeds of `cells` that also occur (as any seed kind) in the archived plans."""
    old = set()
    for p in avoid_paths:
        old |= seed_values(json.loads(ln) for ln in open(p) if ln.strip())
    return sorted(seed_values(cells) & old)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    avoid = []
    while "--avoid" in argv:
        k = argv.index("--avoid")
        avoid.append(argv[k + 1])
        del argv[k:k + 2]
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    design = json.load(open(argv[0]))
    cells = expand(design)
    if avoid:
        hit = collisions(cells, avoid)
        if hit:
            print(f"{len(hit)} seed(s) also used by {avoid}: {hit[:10]}", file=sys.stderr)
            return 2
        print(f"seeds checked against {len(avoid)} archived plan(s): no overlap", file=sys.stderr)
    for c in cells:
        print(json.dumps(c, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

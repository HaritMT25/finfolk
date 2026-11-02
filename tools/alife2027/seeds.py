#!/usr/bin/env python3
"""seeds.py: the registered seed list, from the recorded analysis RNG.

    python3 tools/alife2027/seeds.py experiments/alife2027/v2/protocol.json [--write | --check]

Draws 32-bit outputs of reference PCG32 XSH-RR (finstats.PCG32) seeded with
protocol.json's seeds.generation (initstate, initseq), in order, rejecting
duplicates and every excluded ID (the development seeds, the engineering
seeds and any listed range), until `count` are accepted. The analysis RNG is
independent of the simulation's (a Mersenne Twister seeded by the ID).
--write writes main_seeds.txt; --check (the default) regenerates and compares
with the frozen file, exiting 1 on any difference.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finstats as fs  # noqa: E402


def read_ids(path):
    with open(path) as f:
        return [int(x) for x in f.read().split()]


def excluded_ids(proto, base):
    gen = proto["seeds"]["generation"]
    ex = set()
    for key in gen.get("exclude_files", []):
        ex.update(read_ids(os.path.join(base, proto["seeds"][key])))
    for lo, hi in gen.get("exclude_ranges", []):
        ex.update(range(lo, hi + 1))
    return ex


def generate(proto, base):
    gen = proto["seeds"]["generation"]
    if gen["algorithm"] != "pcg32-xsh-rr-reference":
        raise SystemExit("unknown generator " + gen["algorithm"])
    rng = fs.PCG32(gen["initstate"], gen["initseq"])
    ex = excluded_ids(proto, base)
    out, seen, rejected = [], set(), 0
    while len(out) < gen["count"]:
        v = rng.next_u32()
        if v in seen or v in ex:
            rejected += 1
            continue
        seen.add(v)
        out.append(v)
    return out, rejected


def write_ids(path, ids, per_line=16):
    with open(path, "w", newline="\n") as f:
        for i in range(0, len(ids), per_line):
            f.write(" ".join(str(v) for v in ids[i:i + per_line]) + "\n")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    ppath = sys.argv[1]
    base = os.path.dirname(os.path.abspath(ppath))
    proto = json.load(open(ppath))
    ids, rejected = generate(proto, base)
    target = os.path.join(base, proto["seeds"]["main"])
    if "--write" in sys.argv:
        write_ids(target, ids)
        print(f"wrote {len(ids)} seeds ({rejected} rejected) to {target}")
        return 0
    frozen = read_ids(target)
    if frozen != ids:
        print(f"MISMATCH: {target} differs from the regenerated list")
        return 1
    print(f"ok: {target} == regenerated ({len(ids)} seeds, {rejected} rejected)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

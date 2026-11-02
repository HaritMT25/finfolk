"""invlib.py: shared helpers for the invasion-matrix tooling (Python 3 stdlib only).

Classic checkpoints (src/core/checkpoint_io.hpp) are columnar JSON: per-creature
arrays under "creatures", genomes as one flat (wiring, weight) stream sized by
"genomeLengths". This module turns them into per-creature rows and back, so a
tool can swap fish between worlds without knowing the column layout.

Round-trip exactness: the engine writes floats with %.9g and reads them with a
correctly rounded strtod; Python's repr is the shortest string that round-trips
the same double, so load + dump is exact. The one hole is "-0": json parses it
as the int 0, which would turn a float -0.0 into +0.0, so ints are parsed with a
hook that keeps the sign.
"""
from __future__ import annotations

import hashlib
import json
import os
import random

FORMAT_ID = "evo_boids.checkpoint"

# Per-creature scalar columns, in the order checkpoint_io.hpp writes them. The
# optional ones (generation, bodySize, bodyElong) are written by every engine
# since v0.23 / v0.26; a checkpoint without them is refused here (the tooling
# targets current checkpoints only).
SCALAR_COLS = ["id", "lineageId", "alive", "generation",
               "posX", "posY", "velX", "velY", "lastMoveDirX", "lastMoveDirY",
               "speed", "age", "foodReserves", "reproTimer", "interactTimer",
               "responsiveness", "oscPeriod", "oscPhase", "bodySize", "bodyElong"]

PREDATOR_COLS = ["posX", "posY", "velX", "velY", "digestTimer", "energy", "age",
                 "alive", "speedFactor", "buddingFactor", "generation"]


class CheckpointError(Exception):
    pass


def _parse_int(s):
    return -0.0 if s == "-0" else int(s)


def load_checkpoint(path):
    with open(path, "r") as f:
        cp = json.load(f, parse_int=_parse_int)
    if cp.get("format") != FORMAT_ID or cp.get("formatVersion") != 1:
        raise CheckpointError(f"{path}: not a version-1 evo_boids checkpoint")
    for k in ("world", "counters", "config", "creatures", "predators", "rngState"):
        if k not in cp:
            raise CheckpointError(f"{path}: missing '{k}'")
    cs = cp["creatures"]
    for k in SCALAR_COLS + ["neuronOutputs", "body", "genomeLengths", "genes"]:
        if k not in cs:
            raise CheckpointError(f"{path}: creatures lack column '{k}'")
    return cp


def dumps_checkpoint(cp):
    # Compact separators keep the file the size the engine writes.
    return json.dumps(cp, separators=(",", ":"), allow_nan=False) + "\n"


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_json_atomic(path, obj):
    write_atomic(path, json.dumps(obj, indent=1, sort_keys=True, allow_nan=False) + "\n")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def derive_seed(*parts):
    """A 32-bit seed from any printable parts (stable across runs and Python versions)."""
    h = hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:4], "little")


class Rng:
    """random.Random restricted to calls whose algorithms are stable across Python 3 versions
    (seeding from an int, random(), and randrange via _randbelow)."""

    def __init__(self, seed):
        self._r = random.Random(int(seed))

    def below(self, n):
        return self._r.randrange(n)

    def unit(self):
        return self._r.random()

    def sample(self, n, k):
        """k distinct indices from range(n), in draw order (partial Fisher-Yates)."""
        if k > n:
            raise ValueError(f"cannot draw {k} distinct of {n}")
        idx = list(range(n))
        for i in range(k):
            j = i + self.below(n - i)
            idx[i], idx[j] = idx[j], idx[i]
        return idx[:k]


def creature_rows(cp):
    """Per-creature dicts: the scalar columns plus 'neurons', 'body', 'genes' (flat lists)."""
    cs = cp["creatures"]
    n = int(cs["count"])
    npc = int(cs["neuronsPerCreature"])
    blen = int(cs["bodyLen"])
    for k in SCALAR_COLS:
        if len(cs[k]) != n:
            raise CheckpointError(f"column {k} has {len(cs[k])} entries, count is {n}")
    if len(cs["neuronOutputs"]) != n * npc or len(cs["body"]) != n * blen * 2 or len(cs["genomeLengths"]) != n:
        raise CheckpointError("creature block arrays disagree with count")
    if sum(int(L) for L in cs["genomeLengths"]) * 2 != len(cs["genes"]):
        raise CheckpointError("'genes' length does not match 'genomeLengths'")
    rows = []
    gi = 0
    for i in range(n):
        r = {k: cs[k][i] for k in SCALAR_COLS}
        r["neurons"] = cs["neuronOutputs"][i * npc:(i + 1) * npc]
        r["body"] = cs["body"][i * blen * 2:(i + 1) * blen * 2]
        L = int(cs["genomeLengths"][i])
        r["genes"] = cs["genes"][gi:gi + 2 * L]
        gi += 2 * L
        rows.append(r)
    return rows


def set_creature_rows(cp, rows):
    cs = cp["creatures"]
    cs["count"] = len(rows)
    for k in SCALAR_COLS:
        cs[k] = [r[k] for r in rows]
    cs["neuronOutputs"] = [v for r in rows for v in r["neurons"]]
    cs["body"] = [v for r in rows for v in r["body"]]
    cs["genomeLengths"] = [len(r["genes"]) // 2 for r in rows]
    cs["genes"] = [v for r in rows for v in r["genes"]]


def live_ids(cp):
    cs = cp["creatures"]
    return [int(i) for i, a in zip(cs["id"], cs["alive"]) if int(a) != 0]

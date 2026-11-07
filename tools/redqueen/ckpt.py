#!/usr/bin/env python3
"""ckpt.py: the Red Queen tools' checkpoint adapter (Classic engine, format versions 1 and 2).

    ckpt.py info PATH [PATH ...]      one JSON line of metadata per checkpoint
    ckpt.py validate PATH [PATH ...]  exit 0 if every file passes the checks below, else 1

tools/invasion/invlib.load_checkpoint() reads version 1 only and stays as it is (the first
study's pinned tooling); this module is its Stage C (v0.27.0) counterpart. A version-2 file is
a world with neural predators (src/core/checkpoint_io.hpp): the config carries predatorBrain,
world.nextPredatorId, a predatorRngState, and the predators block per-predator ids, lineages,
parents, speed, captures, recurrent outputs and genomes. Version 1 (Stage A / B worlds, whose
prey the shared benchmark also challenges) loads too; its predators have no genomes.

validate() applies the engine's own load rules (deserialize / readPredators) in Python, so a
file this module accepts is one the pinned engine accepts, and it refuses rather than repairs:
  * format id, version 1 or 2, and predatorBrain present iff version 2;
  * world size > 0, nextId above every creature id, nextPredatorId >= 1 (v2) and above every
    predator id and lineage id;
  * every creature / predator column the length its count implies, genes matching genomeLengths,
    the neuron counts, body length and (v2) the predator sensor set;
  * predator ids unique and > 0, lineage > 0, parent >= 0, traits in [0.5, 2], finite floats;
  * rngState (and predatorRngState for v2) present.

Round-trip exactness: the engine writes floats with %.9g and reads them correctly rounded;
Python's repr is the shortest string giving the same double, so load + dumps resumes byte for
byte (tested end to end). "-0" parses as the float -0.0, not the int 0.
"""
from __future__ import annotations

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rqlib  # noqa: E402

FORMAT_ID = "evo_boids.checkpoint"
V1, V2 = 1, 2
PRED_SENSOR_SET = 1        # predator_brain.hpp PRED_SENSOR_SET (the frozen 21-input list)
PRED_TRAIT_MIN, PRED_TRAIT_MAX = 0.5, 2.0
BODY_MIN, BODY_MAX = 0.5, 2.0

# Per-creature scalar columns, in the order checkpoint_io.hpp writes them.
PREY_COLS = ["id", "lineageId", "alive", "generation",
             "posX", "posY", "velX", "velY", "lastMoveDirX", "lastMoveDirY",
             "speed", "age", "foodReserves", "reproTimer", "interactTimer",
             "responsiveness", "oscPeriod", "oscPhase", "bodySize", "bodyElong"]
PREY_INT_COLS = ("id", "lineageId", "alive", "generation")
# Per-predator columns: every version; then the brain columns of a version-2 file.
PRED_COLS = ["posX", "posY", "velX", "velY", "digestTimer", "energy", "age", "alive",
             "speedFactor", "buddingFactor", "generation"]
PRED_BRAIN_COLS = ["id", "lineageId", "parentId", "speed", "captures"]
PRED_OPTIONAL_COLS = ["sourceId", "virtualBuds"]   # written only when some predator has one


class CheckpointError(Exception):
    pass


def _parse_int(s):
    return -0.0 if s == "-0" else int(s)


def loads(text, label="checkpoint"):
    try:
        return json.loads(text, parse_int=_parse_int)
    except ValueError as e:
        raise CheckpointError(f"{label}: not JSON ({e})")


def load(path, check=True):
    """Parse (and by default validate) a checkpoint file -> the dict."""
    with open(path, "rb") as f:
        cp = loads(f.read().decode("utf-8"), path)
    if check:
        validate(cp, path)
    return cp


def dumps(cp):
    """Compact JSON, the size the engine writes. Exact for anything load() returned."""
    return json.dumps(cp, separators=(",", ":"), allow_nan=False) + "\n"


def version(cp):
    return cp.get("formatVersion")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _finite(v):
    return _num(v) and math.isfinite(v)


def _intlike(v):
    return _num(v) and float(v) == int(v)


def validate(cp, label="checkpoint"):
    """Raise CheckpointError on anything the engine would refuse to load (see the module doc)."""
    def bad(msg):
        raise CheckpointError(f"{label}: {msg}")

    if not isinstance(cp, dict) or cp.get("format") != FORMAT_ID:
        bad("not an evo_boids checkpoint")
    ver = cp.get("formatVersion")
    if ver not in (V1, V2):
        bad(f"format version {ver!r}; this adapter reads 1 and 2")
    brain = ver == V2
    cfg = cp.get("config")
    if not isinstance(cfg, dict):
        bad("missing 'config'")
    if bool(cfg.get("predatorBrain", False)) != brain:
        bad("a version-2 checkpoint must have predatorBrain true, a version-1 one must not")
    for k in ("world", "counters", "creatures", "rngState"):
        if k not in cp:
            bad(f"missing '{k}'")
    if not isinstance(cp["rngState"], str) or not cp["rngState"]:
        bad("missing or empty rngState")
    w = cp["world"]
    if not (_intlike(w.get("width")) and _intlike(w.get("height")) and w["width"] > 0 and w["height"] > 0):
        bad("bad world dimensions")
    if not (_intlike(w.get("frame")) and w["frame"] >= 0):
        bad("bad world.frame")
    if brain:
        if not isinstance(cp.get("predatorRngState"), str) or not cp["predatorRngState"]:
            bad("a version-2 checkpoint needs predatorRngState")
        if not (_num(w.get("nextPredatorId")) and w["nextPredatorId"] >= 1):
            bad("a version-2 checkpoint needs world.nextPredatorId >= 1")
        if "predators" not in cp:
            bad("a version-2 checkpoint needs its 'predators' block")

    # creatures
    cs = cp["creatures"]
    n = cs.get("count")
    if not (_intlike(n) and n >= 0):
        bad("creatures.count")
    n = int(n)
    npc, blen = cs.get("neuronsPerCreature"), cs.get("bodyLen")
    if not (_intlike(npc) and npc > 0 and _intlike(blen) and blen > 0):
        bad("creatures.neuronsPerCreature / bodyLen")
    for k in PREY_COLS:
        if not isinstance(cs.get(k), list) or len(cs[k]) != n:
            bad(f"creature column '{k}' missing or not {n} long")
    for k in ("neuronOutputs", "body", "genomeLengths", "genes"):
        if not isinstance(cs.get(k), list):
            bad(f"creature column '{k}' missing")
    if len(cs["neuronOutputs"]) != n * int(npc) or len(cs["body"]) != n * int(blen) * 2 or len(cs["genomeLengths"]) != n:
        bad("creature neuron / body / genomeLengths arrays disagree with the count")
    if any(not _intlike(L) or L < 0 for L in cs["genomeLengths"]):
        bad("negative or non-integer creature genome length")
    if sum(int(L) for L in cs["genomeLengths"]) * 2 != len(cs["genes"]):
        bad("creature 'genes' length does not match 'genomeLengths'")
    for k in PREY_INT_COLS:
        if any(not _intlike(v) or v < 0 for v in cs[k]):
            bad(f"creature column '{k}' has a non-integer or negative value")
    if n and int(w.get("nextId", 0)) <= max(int(v) for v in cs["id"]):
        bad("'nextId' must exceed every creature id")
    if len(set(int(v) for v in cs["id"])) != n:
        bad("duplicate creature ids")
    for k in PREY_COLS:
        if k not in PREY_INT_COLS and any(not _finite(v) for v in cs[k]):
            bad(f"creature column '{k}' has a non-finite value")
    for k in ("bodySize", "bodyElong"):
        if any(not BODY_MIN <= v <= BODY_MAX for v in cs[k]):
            bad(f"'{k}' value out of range [0.5, 2]")
    if any(not _finite(v) for v in cs["neuronOutputs"]):
        bad("creature neuron output is not finite")

    # predators
    jp = cp.get("predators")
    if jp is None:
        return
    m = jp.get("count")
    if not (_intlike(m) and m >= 0):
        bad("predators.count")
    m = int(m)
    for k in PRED_COLS:
        if not isinstance(jp.get(k), list) or len(jp[k]) != m:
            bad(f"predator column '{k}' missing or not {m} long")
    for k in ("posX", "posY", "velX", "velY", "digestTimer", "energy", "age"):
        if any(not _finite(v) for v in jp[k]):
            bad(f"predator column '{k}' has a non-finite value")
    for k in ("speedFactor", "buddingFactor"):
        if any(not PRED_TRAIT_MIN <= v <= PRED_TRAIT_MAX for v in jp[k]):
            bad("predator trait value out of range [0.5, 2]")
    if any(not _intlike(v) or not 0 <= v <= 0xFFFFFFFF for v in jp["generation"]):
        bad("predator 'generation' out of range")
    if not brain:
        return
    if jp.get("sensorSet") != PRED_SENSOR_SET:
        bad(f"predator sensor set {jp.get('sensorSet')!r}, this adapter's is {PRED_SENSOR_SET}")
    if jp.get("neuronsPerPredator") != npc:
        bad("neurons per predator differ from neurons per creature (one build has one MAX_INTERNAL_NEURONS)")
    for k in PRED_BRAIN_COLS:
        if not isinstance(jp.get(k), list) or len(jp[k]) != m:
            bad(f"predator brain column '{k}' missing or not {m} long")
    for k in PRED_OPTIONAL_COLS:
        if k in jp and (not isinstance(jp[k], list) or len(jp[k]) != m):
            bad(f"predator column '{k}' not {m} long")
    for k in ("neuronOutputs", "genomeLengths", "genes"):
        if not isinstance(jp.get(k), list):
            bad(f"predator column '{k}' missing")
    if len(jp["neuronOutputs"]) != m * int(npc) or len(jp["genomeLengths"]) != m:
        bad("predator neuronOutputs / genomeLengths disagree with the count")
    if any(not _finite(v) for v in jp["neuronOutputs"]):
        bad("predator neuron output is not finite")
    if any(not _intlike(L) or L < 0 for L in jp["genomeLengths"]):
        bad("negative predator genome length")
    if sum(int(L) for L in jp["genomeLengths"]) * 2 != len(jp["genes"]):
        bad("predator 'genes' length does not match 'genomeLengths'")
    nxt = int(w["nextPredatorId"])
    ids = [int(v) for v in jp["id"]]
    if any(i <= 0 for i in ids) or len(set(ids)) != m:
        bad("predator ids must be unique and > 0")
    if any(i >= nxt for i in ids):
        bad("'nextPredatorId' must exceed every predator id")
    if any(not _intlike(v) or v <= 0 or v >= nxt for v in jp["lineageId"]):
        bad("predator lineageId out of range (must be > 0 and below nextPredatorId)")
    if any(not _intlike(v) or v < 0 for v in jp["parentId"]):
        bad("predator parentId out of range")
    if any(not _intlike(v) or not 0 <= v <= 0xFFFFFFFF for v in jp["captures"]):
        bad("predator 'captures' out of range")
    if any(not _finite(v) or v < 0 for v in jp["speed"]):
        bad("predator 'speed' must be finite and >= 0")
    for k in PRED_OPTIONAL_COLS:
        if k in jp and any(not _intlike(v) or v < 0 for v in jp[k]):
            bad(f"predator '{k}' out of range")


# ------------------------------------------------------------------ extraction
def prey(cp, alive_only=False):
    """Per-creature dicts: the scalar columns plus 'neurons', 'body' and 'genes' (the genome as its
    flat [wiring, weight, wiring, weight, ...] list, as the file stores it)."""
    cs = cp["creatures"]
    n, npc, blen = int(cs["count"]), int(cs["neuronsPerCreature"]), int(cs["bodyLen"])
    rows, gi = [], 0
    for i in range(n):
        r = {k: cs[k][i] for k in PREY_COLS}
        r["neurons"] = cs["neuronOutputs"][i * npc:(i + 1) * npc]
        r["body"] = cs["body"][i * blen * 2:(i + 1) * blen * 2]
        L = int(cs["genomeLengths"][i])
        r["genes"] = cs["genes"][gi:gi + 2 * L]
        gi += 2 * L
        if not alive_only or int(r["alive"]) != 0:
            rows.append(r)
    return rows


def set_prey(cp, rows):
    cs = cp["creatures"]
    cs["count"] = len(rows)
    for k in PREY_COLS:
        cs[k] = [r[k] for r in rows]
    cs["neuronOutputs"] = [v for r in rows for v in r["neurons"]]
    cs["body"] = [v for r in rows for v in r["body"]]
    cs["genomeLengths"] = [len(r["genes"]) // 2 for r in rows]
    cs["genes"] = [v for r in rows for v in r["genes"]]


def predators(cp, alive_only=False):
    """Per-predator dicts: PRED_COLS, and for a version-2 file the brain columns, 'neurons', 'genes'
    (flat), 'sourceId' and 'virtualBuds' (0 when the file omits them)."""
    jp = cp.get("predators") or {"count": 0}
    m = int(jp.get("count", 0))
    brain = version(cp) == V2
    npp = int(jp.get("neuronsPerPredator", 0)) if brain else 0
    rows, gi = [], 0
    for i in range(m):
        r = {k: jp[k][i] for k in PRED_COLS}
        if brain:
            for k in PRED_BRAIN_COLS:
                r[k] = jp[k][i]
            for k in PRED_OPTIONAL_COLS:
                r[k] = jp[k][i] if k in jp else 0
            r["neurons"] = jp["neuronOutputs"][i * npp:(i + 1) * npp]
            L = int(jp["genomeLengths"][i])
            r["genes"] = jp["genes"][gi:gi + 2 * L]
            gi += 2 * L
        if not alive_only or int(r["alive"]) != 0:
            rows.append(r)
    return rows


def genome_sha(genes):
    """SHA-256 of one genome's flat (wiring, weight) integer list: an identity for manifests."""
    return rqlib.sha256_bytes(",".join(str(int(v)) for v in genes).encode())


def meta(cp):
    """The metadata a plan or a manifest records about a checkpoint."""
    w = cp["world"]
    cs = cp["creatures"]
    jp = cp.get("predators") or {"count": 0}
    alive_prey = sum(1 for a in cs["alive"] if int(a) != 0)
    out = {
        "format_version": cp["formatVersion"], "engine_version": cp.get("engineVersion"),
        "determinism": cp.get("determinism"), "width": int(w["width"]), "height": int(w["height"]),
        "frame": int(w["frame"]), "next_id": int(w["nextId"]),
        "prey": int(cs["count"]), "prey_alive": alive_prey,
        "predators": int(jp.get("count", 0)),
        "predator_brain": cp["formatVersion"] == V2,
        "arena": bool(w.get("arena", False)),
        "counters": dict(cp.get("counters") or {}),
    }
    if cp["formatVersion"] == V2:
        out["next_predator_id"] = int(w["nextPredatorId"])
        out["predator_sensor_set"] = jp.get("sensorSet")
        out["predator_lineages"] = len({int(v) for v in jp.get("lineageId", [])})
    return out


def config_diff(a, b, keys=None):
    """{key: [a's, b's]} for every config key whose values differ (numbers compared as floats)."""
    ca, cb = a.get("config") or {}, b.get("config") or {}
    out = {}
    for k in sorted(set(ca) | set(cb) if keys is None else keys):
        x, y = ca.get(k), cb.get(k)
        if isinstance(x, bool) or isinstance(y, bool) or not (_num(x) and _num(y)):
            same = x == y
        else:
            same = float(x) == float(y)
        if not same:
            out[k] = [x, y]
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2 or argv[0] not in ("info", "validate"):
        print(__doc__, file=sys.stderr)
        return 2
    rc = 0
    for p in argv[1:]:
        try:
            cp = load(p)
        except (OSError, CheckpointError) as e:
            print(f"INVALID {p}: {e}", file=sys.stderr)
            rc = 1
            continue
        if argv[0] == "info":
            m = meta(cp)
            m["path"] = os.path.abspath(p)
            m["sha256"] = rqlib.sha256_file(p)
            print(json.dumps(m, sort_keys=True))
        else:
            print(f"ok {p} (version {cp['formatVersion']}, frame {cp['world']['frame']})")
    return rc


if __name__ == "__main__":
    sys.exit(main())

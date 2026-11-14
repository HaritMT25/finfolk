#!/usr/bin/env python3
"""common.py: build a common-environment prey checkpoint (Red Queen design section 2).

    common.py build --template T.json --source X.json --n 600 --seed S [--sampling wor-balanced|hybrid|iid]
                    [--ages config/age_reference.json --age-seed S2]
                    --out X.common.json --manifest X.common.manifest.json [--allow-config-mismatch]
    common.py ages --source SENTINEL.json [--source ...] --n 600 --out config/age_reference.json
    common.py validate --binary EVO_BOIDS --work EMPTY_DIR X.common.json

The transplant primitive (src/core/transplant.hpp) keeps everything of its prey world X: its
prey's ages, reserves, recurrent state, schooling geometry, food, pheromones and frame. A raw
time-shift transplant therefore mixes inherited prey differences with the ecological state
the archive happened to be in. The common-environment checkpoint removes that state: the prey
GENOMES of an archived population, put into one shared reference world.

What the output is (one per (prey world, prey time, replicate); then the engine's transplant
adds the predators):
  * the TEMPLATE's world: geometry, config (topology, genome bounds, all assay physics), frame,
    food field, food patches, current vortices, the global random state (and, for a version-2
    template, the predators' random state); its pheromone field CLEARED (all zero); its
    predators REMOVED (count 0; a version-2 template keeps format 2 with an empty block and
    nextPredatorId 1); every counter zero (strides 1); nextId = n + 1.
  * n reference SLOTS: the template's first n creatures give position, velocity, last move
    direction, body trail and oscillator phase ("template oscillator phases").
  * into slot i, the genome of sampled source creature i, with fresh physiology and controller
    state: the AgentCore defaults of src/core/agent_core.hpp (age 0, reserves 30, speed 80,
    responsiveness 0.5, oscillator period 34, both timers 0) and every recurrent neuron output
    0.5 (buildNeuralNet's birth state); id i + 1, lineageId = its own id (a founder), generation
    0. The heritable body parameters (bodySize, bodyElong) come with the genome (1.0 / 1.0 when
    the body model is off, as in the study).
  * AGE (design v3 §3.2), the one deliberate exception to newborn resetting: with an age
    reference (--ages; schema finfolk.redqueen.agereference/1: n fixed quantile ages of one
    frozen prey age CDF) slot i gets reference age perm[i], perm a permutation drawn from
    --age-seed (the plan's prey-snapshot x replicate key, so one realization serves every
    opponent and condition of that snapshot and replicate); the manifest is then schema /2.
    Without one, every age is 0 (phase A's newborn construction, schema /1).
  * SAMPLING, from the source's m living prey (seeded, frequency-preserving):
      wor-balanced (default; design v3 §3.1, registered): without replacement when m >= n,
        otherwise every source creature n // m times plus n % m distinct extras (no abrupt loss
        of distinct individuals near the cap; at m = n a census);
      hybrid: without replacement when m >= n, otherwise n independent uniform draws with
        replacement (v2's law; explicit only);
      iid: n independent uniform draws with replacement, whatever m.
    Every manifest records the source count, multiplicities, distinct genomes and lineages and
    their effective numbers (inverse Simpson).
    The slot order is random (the draw order), so source order never maps onto slot positions.
  * the MANIFEST: template and source (registered labels, SHA-256, frames), the policy and its
    duplication summary, every reset value, config differences, and per slot the source index,
    id, lineage and generation (source lineage ids are in the SOURCE world's id namespace: the
    plan row carries that world's UUID). Deterministic: no time stamps, no machine paths beyond
    the labels the caller passes.

The source's prey-relevant config (every key not starting with "predator") must equal the
template's, or the build is refused (--allow-config-mismatch keeps the template's values and
lists the differences). Predator keys may differ (a Stage A or B prey archive in a Stage C
common environment); they are listed, not refused, since the engine's transplant checks the
predator physics against the predator source.

validate runs the pinned engine on a built checkpoint: it loads and runs 100 steps (s100),
resumes s100 for 100 more (a), resumes a Python load + dump of s100 for 100 more (b), and runs
200 steps straight from the common checkpoint (c). It requires a == b (the Python adapter
round-trips exactly) and a == c (the engine's save / load round trip is exact on this world).

The engine's binary32 age clock (age_death_frame, age_feasible, age_feasible_count; D8 v2 rule
46, used by rule 48) is defined here, once, for every tool that needs age feasibility: score.py's
age strata, and the statistics' age ceiling M_H (import it from here; do not re-derive it).
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ckpt  # noqa: E402
import rqlib  # noqa: E402

SCHEMA = "finfolk.redqueen.common/1"
SCHEMA_AGES = "finfolk.redqueen.common/2"        # with reference ages (design v3 §3.2)
AGE_SCHEMA = "finfolk.redqueen.agereference/1"
POLICIES = ("wor-balanced", "hybrid", "iid")   # wor-balanced: design v3 §3.1 (registered)
# src/core/agent_core.hpp member defaults (a test parses the header to keep these in step).
AGENT_DEFAULTS = {"age": 0.0, "foodReserves": 30.0, "speed": 80.0, "reproTimer": 0.0,
                  "interactTimer": 0.0, "responsiveness": 0.5, "oscPeriod": 34.0}
NEURON_BIRTH_OUTPUT = 0.5      # buildNeuralNet's reset of every internal neuron's output
SLOT_COLS = ("posX", "posY", "velX", "velY", "lastMoveDirX", "lastMoveDirY", "oscPhase")
COUNTER_ONES = ("clusterStride", "reproStride")


class CommonError(Exception):
    pass


# ---------------------------------------------------------------- the engine's binary32 age clock
# D8 v2 rule 46 (and rule 48, which uses the same predicate): the ONE definition of age feasibility.
# The pinned engine keeps a creature's age as a binary32 float (src/core/agent_core.hpp:42
# `float age`), loads it from a checkpoint as the (float) cast of the parsed double
# (src/core/json_min.hpp:288 readFloats for the age column, :132 floatOr for maxAge), adds the fixed step every frame
# (src/core/kernel.hpp:97 `c.age += dt;`, dt = `const float fixedDt = 0.016f;` src/app/main.cpp:687)
# and kills a prey of age when the UPDATED age is strictly greater than the binary32 maxAge
# (src/core/kernel.hpp:117 `if (c.age > cfg.maxAge) return 'a';`, src/core/config.hpp:119
# `float maxAge`). The build forbids contraction (-ffp-contract=off), so each += is one correctly
# rounded binary32 addition. For a start age a, maxAge m and horizon H (frames):
#
#     A_0 = binary32(a),   A_{k+1} = round32(A_k + binary32(0.016)),
#     age death at the first frame k >= 1 with A_k > binary32(m);
#     F(H) = 1 (age-feasible) exactly when no k in 1..H has A_k > binary32(m).
#
# This is NOT the exact-arithmetic a + H * 0.016 <= m (nor that with its equality case corrected):
# rounding moves individuals across that boundary. Start 40.00001907348633 reaches
# 119.99422454833984 after 5,000 frames on this clock (feasible) although 40.000019 + 80 > 120.
# The engine tests starvation before age (deathCause); F is an age-only support predicate.
# A binary32 sum computed in double and rounded once to binary32 is the correctly rounded binary32
# sum (53 >= 2 x 24 + 2 bits), so the simulation below is exact. Each start age's clock is cached and
# resumed (a later, longer horizon continues where an earlier one stopped): an exactly equivalent
# cache, as rule 46 permits.
AGE_CLOCK = "finfolk.redqueen.ageclock/binary32-1"   # the predicate's identity, recorded with each summary
ENGINE_DT = 0.016                                     # fixedDt (main.cpp:687); score.DT is the same value
_F32 = struct.Struct("<f")
_CLOCKS = {}                                          # (A_0, binary32 m, binary32 dt) -> [k, A_k, death]


def binary32(x):
    """x rounded to the nearest IEEE-754 binary32 value (ties to even): the engine's (float) cast of a
    parsed double. Raises ValueError for a value that is not a finite binary32 number."""
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError(f"age clock: {x!r} is not a finite number")
    try:
        return _F32.unpack(_F32.pack(x))[0]
    except OverflowError:
        raise ValueError(f"age clock: {x!r} is outside the binary32 range") from None


def age_death_frame(start_age, max_age, limit, dt=ENGINE_DT):
    """The frame k (1 <= k <= limit) of the age death of a prey whose engine-loaded age at frame 0 is
    start_age, on the engine's binary32 age clock (above), or None if it does not come within `limit`
    frames (predation and starvation aside)."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError(f"age clock: limit {limit!r} is not a frame count")
    key = (binary32(start_age), binary32(max_age), binary32(dt))
    if not key[2] > 0:
        raise ValueError(f"age clock: dt {dt!r} is not positive")
    st = _CLOCKS.get(key)
    if st is None:
        if len(_CLOCKS) >= 1 << 16:
            _CLOCKS.clear()
        st = _CLOCKS[key] = [0, key[0], None]
    k, a, death = st
    if death is None and k < limit:
        m, d = key[1], key[2]
        pack, unpack = _F32.pack, _F32.unpack
        while k < limit:
            k += 1
            try:
                a = unpack(pack(a + d))[0]
            except OverflowError:                   # (rounds to +inf: past any finite maxAge)
                a = math.inf
            if a > m:
                death = k
                break
        st[:] = [k, a, death]
    return death if death is not None and death <= limit else None


def age_feasible(start_age, horizon, max_age, dt=ENGINE_DT):
    """F(H) of D8 v2 rule 46: True exactly when the engine's age-death predicate stays false through
    all `horizon` frames from the engine-loaded start age (the binary32 clock above)."""
    return age_death_frame(start_age, max_age, horizon, dt) is None


def age_feasible_count(start_ages, horizon, max_age, dt=ENGINE_DT):
    """M_H of D8 v2 rule 46: how many of start_ages are age-feasible at the horizon (age_feasible)."""
    return sum(age_feasible(a, horizon, max_age, dt) for a in start_ages)


def sample_indices(m, n, seed, policy):
    """n source indices (into a pool of m) for the n slots, in slot order -> (picks, summary)."""
    if m <= 0:
        raise CommonError("the source has no living prey")
    if n <= 0:
        raise CommonError("n must be >= 1")
    rng = rqlib.SplitMix64(seed)
    if policy == "hybrid":
        picks = rng.sample(m, n) if m >= n else [rng.below(m) for _ in range(n)]
    elif policy == "wor-balanced":
        if m >= n:
            picks = rng.sample(m, n)
        else:
            q, rem = divmod(n, m)
            picks = list(range(m)) * q + rng.sample(m, rem)
            rng.shuffle(picks)
    elif policy == "iid":
        picks = [rng.below(m) for _ in range(n)]
    else:
        raise CommonError(f"unknown sampling policy {policy!r} (one of {', '.join(POLICIES)})")
    copies = {}
    for p in picks:
        copies[p] = copies.get(p, 0) + 1
    summary = {"policy": policy, "seed": int(seed), "pool": m, "n": n,
               "with_replacement": policy == "iid" or m < n,
               "distinct": len(copies), "max_copies": max(copies.values()),
               "duplicated_slots": n - len(copies)}
    return picks, summary


def _inverse_simpson(counts):
    tot = sum(counts)
    return tot * tot / sum(c * c for c in counts) if tot else 0.0


def diversity(pool, picks):
    """The sample's diversity: distinct source individuals, genomes and lineages, and the effective
    (inverse Simpson) numbers of genomes and lineages among the n slots."""
    g, ln = {}, {}
    for p in picks:
        h = ckpt.genome_sha(pool[p]["genes"])
        g[h] = g.get(h, 0) + 1
        k = int(pool[p]["lineageId"])
        ln[k] = ln.get(k, 0) + 1
    return {"distinct_individuals": len(set(picks)), "distinct_genomes": len(g), "distinct_lineages": len(ln),
            "effective_genomes": _inverse_simpson(list(g.values())),
            "effective_lineages": _inverse_simpson(list(ln.values()))}


def load_age_reference(path_or_dict):
    """A validated age reference -> dict (n ages, finite, >= 0, ascending)."""
    ref = path_or_dict if isinstance(path_or_dict, dict) else rqlib.read_json(path_or_dict)
    if ref.get("schema") != AGE_SCHEMA:
        raise CommonError(f"age reference schema {ref.get('schema')!r}, expected {AGE_SCHEMA}")
    ages = ref.get("ages")
    if not isinstance(ages, list) or len(ages) != ref.get("n") or not ages:
        raise CommonError("the age reference needs its n ages")
    if any(not isinstance(a, (int, float)) or isinstance(a, bool) or not (a >= 0) or a != a or a == float("inf")
           for a in ages) or ages != sorted(ages):
        raise CommonError("reference ages must be finite, >= 0 and ascending (quantiles)")
    return ref


def reference_ages(sources, n, labels=None):
    """One prey age CDF pooled from the living prey of `sources` (checkpoint dicts of the frozen
    stable interval) -> its n quantile ages at the mid-probabilities (i + 0.5) / n, i = 0 .. n - 1:
    the pooled sorted ages at floor((i + 0.5) M / n), in exact integer arithmetic (the upper order
    statistic at the empirical CDF's jumps). The sources must share one maxAge (recorded; the
    construction and the final plan both check it against the template's)."""
    pooled, srcs = [], []
    max_age = None
    for k, cp in enumerate(sources):
        ckpt.validate(cp, f"age source {k}")
        a = [float(r["age"]) for r in ckpt.prey(cp, alive_only=True)]
        pooled += a
        ma = float(cp["config"].get("maxAge", 120.0))
        if max_age is not None and ma != max_age:
            raise CommonError("the age sources differ in maxAge")
        max_age = ma
        srcs.append({"label": (labels or [None] * len(sources))[k], "frame": int(cp["world"]["frame"]),
                     "prey": len(a)})
    if not pooled:
        raise CommonError("the age sources hold no living prey")
    pooled.sort()
    M = len(pooled)
    ages = [pooled[min(M - 1, ((2 * i + 1) * M) // (2 * n))] for i in range(n)]
    return {"schema": AGE_SCHEMA, "n": n, "ages": ages, "pooled": M, "max_age": max_age,
            "method": "the pooled living-prey ages, sorted, at floor((i + 0.5) M / n), i = 0 .. n - 1 (the upper "
                      "order statistic at the empirical CDF's jumps)",
            "sources": srcs}


def _clear_predators(cp):
    jp = cp.get("predators") or {}
    out = {}
    for k, v in jp.items():
        if k in ckpt.PRED_OPTIONAL_COLS:
            continue
        out[k] = [] if isinstance(v, list) else v
    out["count"] = 0
    for k in ckpt.PRED_COLS:
        out.setdefault(k, [])
    cp["predators"] = out


def build(template, source, n, seed, policy="wor-balanced", template_label=None, source_label=None,
          template_sha=None, source_sha=None, source_meta=None, allow_config_mismatch=False,
          age_reference=None, age_seed=None, ages_label=None, ages_sha=None):
    """template, source: checkpoint dicts (ckpt.load). -> (common checkpoint dict, manifest dict).
    age_reference (load_age_reference's dict, n ages) + age_seed: the reference-age construction.
    The manifest's 'output' (the written file's hash) is the caller's to add."""
    ckpt.validate(template, template_label or "template")
    ckpt.validate(source, source_label or "source")
    trows = ckpt.prey(template)
    if len(trows) < n:
        raise CommonError(f"the template has {len(trows)} creatures, fewer than the {n} slots asked for")
    if any(int(r["alive"]) == 0 for r in trows[:n]):
        raise CommonError("a template slot holds a dead creature")
    pool = ckpt.prey(source, alive_only=True)
    if (template["creatures"]["neuronsPerCreature"], template["creatures"]["bodyLen"]) != \
            (source["creatures"]["neuronsPerCreature"], source["creatures"]["bodyLen"]):
        raise CommonError("template and source differ in neurons per creature or body length (another build)")
    diffs = ckpt.config_diff(source, template)
    prey_diffs = {k: v for k, v in diffs.items() if not k.startswith("predator")}
    pred_diffs = {k: v for k, v in diffs.items() if k.startswith("predator")}
    if prey_diffs and not allow_config_mismatch:
        raise CommonError(f"source and template prey configs differ: {prey_diffs} "
                          "(--allow-config-mismatch keeps the template's)")
    tcfg = template["config"]
    gmin, gmax = int(tcfg["genomeMinLength"]), int(tcfg["genomeMaxLength"])

    picks, summary = sample_indices(len(pool), n, seed, policy)
    summary.update(diversity(pool, picks))
    slot_age = None
    if age_reference is not None:
        ref = load_age_reference(age_reference)
        if ref["n"] != n:
            raise CommonError(f"the age reference has {ref['n']} ages, the construction {n} slots")
        if age_seed is None:
            raise CommonError("reference ages need their permutation seed")
        perm = rqlib.SplitMix64(age_seed).shuffle(list(range(n)))
        slot_age = [float(ref["ages"][perm[i]]) for i in range(n)]
        if ref.get("max_age") is not None and float(template["config"].get("maxAge", 120.0)) != float(ref["max_age"]):
            raise CommonError("the age reference was estimated under another prey maxAge than the template's")

    out = copy.deepcopy(template)
    rows = []
    for i in range(n):
        slot, src = trows[i], pool[picks[i]]
        L = len(src["genes"]) // 2
        if not gmin <= L <= gmax:
            raise CommonError(f"source creature {src['id']}: genome length {L} outside the template's [{gmin}, {gmax}]")
        r = {k: slot[k] for k in SLOT_COLS}
        r["body"] = list(slot["body"])
        r.update(AGENT_DEFAULTS)
        if slot_age is not None:
            r["age"] = slot_age[i]
        r["neurons"] = [NEURON_BIRTH_OUTPUT] * len(slot["neurons"])
        r["genes"] = list(src["genes"])
        r["bodySize"], r["bodyElong"] = src["bodySize"], src["bodyElong"]
        r["id"] = i + 1
        r["lineageId"] = i + 1
        r["generation"] = 0
        r["alive"] = 1
        rows.append(r)
    ckpt.set_prey(out, rows)

    w = out["world"]
    w["nextId"] = n + 1
    w.pop("arena", None)
    if out["formatVersion"] == ckpt.V2:
        w["nextPredatorId"] = 1
    _clear_predators(out)
    sig = out.get("signals")
    if isinstance(sig, dict):
        sig["rle"] = [0, int(sig["cols"]) * int(sig["rows"])]
    for k in list(out["counters"]):
        out["counters"][k] = 1 if k in COUNTER_ONES else 0
    ckpt.validate(out, "common checkpoint")

    smeta, tmeta = ckpt.meta(source), ckpt.meta(template)
    manifest = {
        "schema": SCHEMA if slot_age is None else SCHEMA_AGES,
        "template": {"label": template_label, "sha256": template_sha, "frame": tmeta["frame"],
                     "format_version": tmeta["format_version"], "engine_version": tmeta["engine_version"],
                     "creatures": tmeta["prey"], "slots_used": n},
        "source": {"label": source_label, "sha256": source_sha, "frame": smeta["frame"],
                   "format_version": smeta["format_version"], "engine_version": smeta["engine_version"],
                   "next_id": smeta["next_id"], "prey_alive": smeta["prey_alive"], "predators": smeta["predators"],
                   **({"meta": source_meta} if source_meta else {})},
        "n": n,
        "sampling": summary,
        "reset": dict(AGENT_DEFAULTS, neuronOutputs=NEURON_BIRTH_OUTPUT, id="slot + 1", lineageId="own id (founder)",
                      generation=0, bodySize_bodyElong="the source creature's (heritable)",
                      slot="template creature i: pos, vel, lastMoveDir, body trail, oscPhase"),
        "world": {"from": "template", "frame": int(w["frame"]), "signals": "cleared", "food": "template",
                  "food_count": int((out.get("food") or {}).get("count", 0)), "counters": "zeroed (strides 1)",
                  "next_id": n + 1, "predators": "removed", "rng": "template",
                  "format_version": out["formatVersion"]},
        "config_differences": prey_diffs,
        "predator_config_differences": pred_diffs,
        "slots": {"source_index": list(picks),
                  "source_id": [int(pool[p]["id"]) for p in picks],
                  "source_lineage": [int(pool[p]["lineageId"]) for p in picks],
                  "source_generation": [int(pool[p]["generation"]) for p in picks],
                  "genome_length": [len(pool[p]["genes"]) // 2 for p in picks],
                  "genome_sha16": [ckpt.genome_sha(pool[p]["genes"])[:16] for p in picks]},
    }
    if slot_age is not None:
        manifest["ages"] = {"policy": "reference quantile ages, permuted", "label": ages_label, "sha256": ages_sha,
                            "permutation_seed": int(age_seed), "n": n, "min": min(slot_age), "max": max(slot_age),
                            "mean": sum(slot_age) / n}
        manifest["reset"]["age"] = "the reference age of slot i (permuted)"
    return out, manifest


def build_files(template_path, source_path, n, seed, policy, out_path, manifest_path, template_label=None,
                source_label=None, source_meta=None, allow_config_mismatch=False, durable=False,
                source_cp=None, source_sha=None, ages_path=None, age_seed=None, ages_label=None):
    """Load, build, write the checkpoint and its manifest -> (manifest, checkpoint sha256).
    source_cp / source_sha: the source already loaded and hashed by the caller (not re-read).
    ages_path: an age reference (read, hashed and parsed from the same bytes)."""
    age_ref, ages_sha = None, None
    if ages_path:
        araw = rqlib.read_bytes(ages_path)
        ages_sha = rqlib.sha256_bytes(araw)
        age_ref = load_age_reference(json.loads(araw.decode("utf-8")))
    traw = rqlib.read_bytes(template_path)          # hashed and parsed from the same bytes
    tsha, tcp = rqlib.sha256_bytes(traw), ckpt.loads(traw.decode("utf-8"), template_path)
    if source_cp is None:
        sraw = rqlib.read_bytes(source_path)
        source_sha, source_cp = rqlib.sha256_bytes(sraw), ckpt.loads(sraw.decode("utf-8"), source_path)
    cp, man = build(tcp, source_cp, n, seed, policy, template_label or os.path.abspath(template_path),
                    source_label or os.path.abspath(source_path), tsha, source_sha, source_meta,
                    allow_config_mismatch, age_ref, age_seed,
                    ages_label or (os.path.abspath(ages_path) if ages_path else None), ages_sha)
    text = ckpt.dumps(cp).encode()
    man["output"] = {"sha256": rqlib.sha256_bytes(text), "bytes": len(text)}
    write = rqlib.write_durable if durable else _write
    write(out_path, text)
    write(manifest_path, rqlib.canonical(man))
    return man, man["output"]["sha256"]


def _write(path, data):
    with open(path, "wb") as f:
        f.write(data)


# ----------------------------------------------------------------- validation
def validate_with_engine(binary, common_path, work):
    """Load + 100 steps, resume, Python round trip, straight 200 (see the module doc) -> report dict;
    raises CommonError on any failure."""
    os.makedirs(work, exist_ok=True)
    if os.listdir(work):
        raise CommonError(f"--work {work} must be empty")
    src = os.path.join(work, "common.json")
    with open(common_path, "rb") as f, open(src, "wb") as g:
        g.write(f.read())

    def eng(args, name):
        with open(os.path.join(work, name + ".log"), "w") as log:
            rc = subprocess.call([binary, "--no-render", "--log-every", "50"] + args, cwd=work, stdout=log,
                                 stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        if rc != 0:
            raise CommonError(f"engine {name} exited {rc} (see {work}/{name}.log)")

    c0 = ckpt.load(src)
    f0, n0 = int(c0["world"]["frame"]), int(c0["creatures"]["count"])
    eng(["--load-checkpoint", "common.json", "--headless", "100", "--save-checkpoint", "s100.json"], "s100")
    s100 = ckpt.load(os.path.join(work, "s100.json"))
    if int(s100["world"]["frame"]) != f0 + 100:
        raise CommonError(f"s100 is at frame {s100['world']['frame']}, expected {f0 + 100}")
    with open(os.path.join(work, "s100_rt.json"), "w") as f:
        f.write(ckpt.dumps(s100))
    eng(["--load-checkpoint", "s100.json", "--headless", "100", "--save-checkpoint", "a.json"], "a")
    eng(["--load-checkpoint", "s100_rt.json", "--headless", "100", "--save-checkpoint", "b.json"], "b")
    eng(["--load-checkpoint", "common.json", "--headless", "200", "--save-checkpoint", "c.json"], "c")
    h = {k: rqlib.sha256_file(os.path.join(work, k + ".json")) for k in ("a", "b", "c")}
    rep = {"common_sha256": rqlib.sha256_file(src), "frame0": f0, "prey0": n0,
           "prey_at_100": int(s100["creatures"]["count"]), "s100_version": s100["formatVersion"],
           "python_round_trip_exact": h["a"] == h["b"], "engine_resume_exact": h["a"] == h["c"], "sha256": h}
    if not rep["python_round_trip_exact"]:
        raise CommonError("a Python load + dump of the engine's checkpoint does not resume identically")
    if not rep["engine_resume_exact"]:
        raise CommonError("save / load / resume differs from the straight run (not a serial build?)")
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--template", required=True)
    b.add_argument("--source", required=True)
    b.add_argument("--n", type=int, required=True)
    b.add_argument("--seed", type=int, required=True)
    b.add_argument("--sampling", default="wor-balanced", choices=POLICIES)
    b.add_argument("--ages", help="an age reference (common.py ages); the slots then get its permuted ages")
    b.add_argument("--age-seed", type=int)
    b.add_argument("--out", required=True)
    b.add_argument("--manifest", required=True)
    b.add_argument("--allow-config-mismatch", action="store_true")
    g = sub.add_parser("ages")
    g.add_argument("--source", action="append", required=True, help="a checkpoint of the frozen stable interval")
    g.add_argument("--n", type=int, required=True)
    g.add_argument("--out", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--binary", required=True)
    v.add_argument("--work", required=True)
    v.add_argument("common")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            if bool(a.ages) != (a.age_seed is not None):
                raise CommonError("--ages and --age-seed go together")
            man, sha = build_files(a.template, a.source, a.n, a.seed, a.sampling, a.out, a.manifest,
                                   allow_config_mismatch=a.allow_config_mismatch, ages_path=a.ages,
                                   age_seed=a.age_seed)
            s = man["sampling"]
            print(f"common {a.out}: {a.n} slots from {s['pool']} living prey ({s['policy']}, "
                  f"{s['distinct']} distinct, max copies {s['max_copies']}); frame {man['world']['frame']}; "
                  f"sha256 {sha[:12]}")
            for k, d in man["config_differences"].items():
                print(f"warning: config {k}: source {d[0]!r}, template {d[1]!r} (template kept)", file=sys.stderr)
        elif a.cmd == "ages":
            raws = [rqlib.read_bytes(p) for p in a.source]
            cps = [ckpt.loads(r.decode("utf-8"), p) for r, p in zip(raws, a.source)]
            ref = reference_ages(cps, a.n, [os.path.abspath(p) for p in a.source])
            for src, r in zip(ref["sources"], raws):
                src["sha256"] = rqlib.sha256_bytes(r)
            ref["tool_sha256"] = rqlib.sha256_file(os.path.abspath(__file__))
            rqlib.write_durable(a.out, rqlib.canonical(ref))
            print(f"age reference {a.out}: {a.n} quantile ages from {ref['pooled']} prey of {len(cps)} checkpoint(s) "
                  f"(min {ref['ages'][0]:.2f}, median {ref['ages'][a.n // 2]:.2f}, max {ref['ages'][-1]:.2f} s)")
        else:
            rep = validate_with_engine(os.path.abspath(a.binary), a.common, a.work)
            rqlib.write_json_durable(os.path.join(a.work, "validate.json"), rep)
            print(f"valid: {a.common} loads, runs 100 steps ({rep['prey0']} -> {rep['prey_at_100']} prey), "
                  f"resumes exactly and round-trips through Python exactly")
    except (CommonError, ckpt.CheckpointError, OSError, ValueError) as e:
        print(f"common.py {a.cmd}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

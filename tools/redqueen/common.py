#!/usr/bin/env python3
"""common.py: build a common-environment prey checkpoint (Red Queen design section 2).

    common.py build --template T.json --source X.json --n 600 --seed S [--sampling wor-balanced|iid]
                    --out X.common.json --manifest X.common.manifest.json [--allow-config-mismatch]
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
  * SAMPLING, from the source's living prey (seeded, frequency-preserving):
      wor-balanced (default): without replacement when the source has >= n prey; otherwise every
        source creature n // m times plus n % m distinct extras, so frequencies are kept as
        evenly as the counts allow (duplication recorded);
      iid: n independent uniform draws with replacement (duplication recorded).
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
"""
from __future__ import annotations

import argparse
import copy
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ckpt  # noqa: E402
import rqlib  # noqa: E402

SCHEMA = "finfolk.redqueen.common/1"
POLICIES = ("wor-balanced", "iid")
# src/core/agent_core.hpp member defaults (a test parses the header to keep these in step).
AGENT_DEFAULTS = {"age": 0.0, "foodReserves": 30.0, "speed": 80.0, "reproTimer": 0.0,
                  "interactTimer": 0.0, "responsiveness": 0.5, "oscPeriod": 34.0}
NEURON_BIRTH_OUTPUT = 0.5      # buildNeuralNet's reset of every internal neuron's output
SLOT_COLS = ("posX", "posY", "velX", "velY", "lastMoveDirX", "lastMoveDirY", "oscPhase")
COUNTER_ONES = ("clusterStride", "reproStride")


class CommonError(Exception):
    pass


def sample_indices(m, n, seed, policy):
    """n source indices (into a pool of m) for the n slots, in slot order -> (picks, summary)."""
    if m <= 0:
        raise CommonError("the source has no living prey")
    if n <= 0:
        raise CommonError("n must be >= 1")
    rng = rqlib.SplitMix64(seed)
    if policy == "wor-balanced":
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
          template_sha=None, source_sha=None, source_meta=None, allow_config_mismatch=False):
    """template, source: checkpoint dicts (ckpt.load). -> (common checkpoint dict, manifest dict).
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
        "schema": SCHEMA,
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
                  "genome_length": [len(pool[p]["genes"]) // 2 for p in picks]},
    }
    return out, manifest


def build_files(template_path, source_path, n, seed, policy, out_path, manifest_path, template_label=None,
                source_label=None, source_meta=None, allow_config_mismatch=False, durable=False,
                source_cp=None, source_sha=None):
    """Load, build, write the checkpoint and its manifest -> (manifest, checkpoint sha256).
    source_cp / source_sha: the source already loaded and hashed by the caller (not re-read)."""
    traw = rqlib.read_bytes(template_path)          # hashed and parsed from the same bytes
    tsha, tcp = rqlib.sha256_bytes(traw), ckpt.loads(traw.decode("utf-8"), template_path)
    if source_cp is None:
        sraw = rqlib.read_bytes(source_path)
        source_sha, source_cp = rqlib.sha256_bytes(sraw), ckpt.loads(sraw.decode("utf-8"), source_path)
    cp, man = build(tcp, source_cp, n, seed, policy, template_label or os.path.abspath(template_path),
                    source_label or os.path.abspath(source_path), tsha, source_sha, source_meta,
                    allow_config_mismatch)
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
    b.add_argument("--out", required=True)
    b.add_argument("--manifest", required=True)
    b.add_argument("--allow-config-mismatch", action="store_true")
    v = sub.add_parser("validate")
    v.add_argument("--binary", required=True)
    v.add_argument("--work", required=True)
    v.add_argument("common")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            man, sha = build_files(a.template, a.source, a.n, a.seed, a.sampling, a.out, a.manifest,
                                   allow_config_mismatch=a.allow_config_mismatch)
            s = man["sampling"]
            print(f"common {a.out}: {a.n} slots from {s['pool']} living prey ({s['policy']}, "
                  f"{s['distinct']} distinct, max copies {s['max_copies']}); frame {man['world']['frame']}; "
                  f"sha256 {sha[:12]}")
            for k, d in man["config_differences"].items():
                print(f"warning: config {k}: source {d[0]!r}, template {d[1]!r} (template kept)", file=sys.stderr)
        else:
            rep = validate_with_engine(os.path.abspath(a.binary), a.common, a.work)
            rqlib.write_json_durable(os.path.join(a.work, "validate.json"), rep)
            print(f"valid: {a.common} loads, runs 100 steps ({rep['prey0']} -> {rep['prey_at_100']} prey), "
                  f"resumes exactly and round-trips through Python exactly")
    except (CommonError, ckpt.CheckpointError, OSError) as e:
        print(f"common.py {a.cmd}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

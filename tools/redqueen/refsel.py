#!/usr/bin/env python3
"""refsel.py: reference selection by information content (design v4 §4.2): the candidate-grid plan, the
collection of its results, and the deterministic greedy / swap selection of EIGHT references per guild
on the registered information criterion, written as config/references.json (finfolk.redqueen.references/1,
the format sealing.py consumes). The criterion and the constraints are FROZEN in the plan (their sha256)
before any candidate outcome exists; main-world performance never enters (only the sentinel grid).

CANDIDATES. The four PREDETERMINED sentinels of the VALIDATION registry, by THE RULE (no override): the first
four C worlds in id order (arena #1: w01, w02, w03, w06), at F1, 20, 60, 100, 120, 140, 180, 200M, where the snapshot is archived and valid (before the
world's first zero): the same (sentinel, time) set for both guilds (a candidate prey reference is the
sentinel's prey snapshot, a candidate predator reference its predators). Four usable sentinels: 32 per
guild. THE BINDING (Codex #71 r1 P1; checked at plan AND at selection):
  - the validation registry <validation dir>/config/worlds.json has the worlds block's registry_sha256 and
    the registered namespace VALIDATION_NAMESPACE (the references' namespace);
  - every sentinel is registered there, treatment C, with uuid uuid5(URL, "finfolk:redqueen:<namespace>:
    <id>") (the references' identity recipe), and the block's uuid IS that identity;
  - no sentinel identity and no candidate snapshot identity is a study identity (sealing.study_identities
    of the main registries, --main-registry, mandatory, and the fork registry, --forks), and no main
    registry uses the validation namespace.
THE EXTINCTION FALLBACK (registered): a sentinel is never replaced. A candidate is OMITTED, with its reason
recorded in the plan and the receipt, when its snapshot is not archived, lies at or after the world's first
zero (valid_before), or its sentinel is a restarted attempt (another history: not the registered
identity). The pool shrinks; the constraints (at least three distinct sentinels among the eight, the
early / late counts) must still be satisfiable, else the plan is refused.

PLAN (`plan`): a design/2 for plan.py: every prey candidate against every predator candidate (family
refgrid) plus each prey candidate's predator-free control (refgrid-free), the production assay (frozen,
K 6, 600 common prey, 5k, the production age reference: mandatory), R = 6, role diagnostic, its own seed
namespace; every engine seed checked against every --avoid input (mandatory). 32 x 32 x 6 = 6,144 grid
trajectories (+ 192 controls). The plan records the binding, the omitted candidates with their reasons and
the AVAILABILITY of every sentinel (its uuid, attempt, archived candidate frames, valid_before: the inputs
that determine the pool, with their sha256) and the whole block's sha256.

COLLECT (`collect`): the packed cells through store.py's verified index, bound to the FINAL plan (every
bundle carries its plan row exactly; the 600 cohort; every cell collected or declared missing).

THE OBSERVATIONS (Codex #71 r1 P2-2 / P2-3): exactly the registered replicates 0..R-1 (R = 6) of every grid
cell, each with ITS matched predator-free control (the same prey candidate and replicate); a missing,
extra or unregistered replicate, or a missing control, is refused (no silent fallback to fewer
replicates). Every observation must be exactly a cell of the final plan (its id, prey, predators and
replicate).

THE CRITERION (registered; CRITERION below, frozen in the plan). Per cell and replicate: the capture
logit l = logit((C + 1/2) / (B + 1)), B = the registered capture bound (324: K 6, the 1.5 s cooldown,
5k), and the survival contrast q = (S_exposed - S_free) / 600 (the same replicate's common prey). Per
readout X in {l, q}: the replicate means X (prey x predator candidates), double-centred (the map's
intercepts removed), its SVD U S V'; a predator candidate's rank-r embedding v_j = V_j,1..r S_1..r^(1/2)
(a prey candidate's u_i likewise). TIED SINGULAR SUBSPACES (Codex #71 r1 P2-6): singular values within
SV_TIE_REL = 1e-8 of the largest (relative) of each other form one group, and a rank r that would split a
group is EXTENDED to the group's end (r_eff, reported; "ranks 1-4" are ranks 1-4, each extended to the end
of its tie group, at most RANK_MAX = 6; a group crossing 6 is a structural degeneracy: refused): the information I_r then depends on the group's
projector only, never on the SVD's basis within it (lambda_min is invariant to rotations inside an
equal-scale group and to sign flips). A predator-reference SET places a prey population from its responses:
its noise-weighted information for rank r is I_r = sum_{j in set} w_j [1, v_j][1, v_j]' (w_j = 1 / the
mean over prey candidates of the cell's variance of the mean: the replicate variance / R, floored at the
binomial count variance / R: 1 / (B p (1 - p)) for the capture logit at p = (C + 1/2) / (B + 1), and
(S (1 - S) + S0 (1 - S0)) / 600 for the survival contrast; a saturated cell's replicates barely vary
but it carries little information); likewise a prey-reference set for predators. The
objective of a set: sum over readouts and ranks 1..4 of log lambda_min(I_r + eps_r I) (the worst-placed
direction; eps_r = 1e-9 tr(I_r over all candidates) / ((r + 1) n): a fixed floor for partial sets) minus
the SATURATION PENALTY 2.0 x the sum over the set of each candidate's saturated share (the share of its
cells whose mean capture fraction C/B or exposed survival lies outside [0.02, 0.98], averaged over the
two readouts); a candidate whose saturated share exceeds 0.5 is not eligible at all (a mostly saturated
reference places nothing, and double-centring would give its flat responses a spurious embedding).
CONSTRAINTS (each guild): eight references; at least three distinct sentinels; at least four at times
<= 120M; at least two at times >= 140M.
PROCEDURE: greedy (add the best candidate whose addition keeps a constraint-satisfying completion
possible: an exact search over the (sentinel, early/late) attribute counts), then swaps (the best
improving exchange of a selected and an unselected candidate keeping the constraints, until none
improves; at most 200, the report saying whether the search CONVERGED or stopped at the limit); every
tie (relative 1e-12) broken by the order of
sha256("<criterion namespace>|refsel|<guild>|<world>|<frame>"). Slots: the selected references sorted by
(frame, that hash): RQ:0..7 (prey references), RP:0..7 (predator references).
THE RECEIPT (references/1 "selection"; Codex #71 r1 P2-3): the criterion, design, final-plan and
OBSERVATIONS content hashes, the block's and the availability's sha256 with the availability itself, the
omitted candidates, the binding (the validation registry, the main / fork registries checked) and the
implementation (refsel.py's sha256, numpy's version).

    refsel.py plan --block worlds_block.json --validation-dir ~/finfolk/validation \\
        --main-registry STUDY/config/worlds.json [--forks STUDY/config/forks.json] --templates /abs/t.json ... \\
        --age-reference /abs/ages.json --avoid PRODUCTION/config/worlds.json [--avoid ...] --out grid.json
    refsel.py collect --study GRID_STUDY --design grid.json --plan FINAL_PLAN.jsonl --out obs.json \\
        [--age-diagnostics age_diagnostics.json]
    refsel.py select obs.json --design grid.json --plan FINAL_PLAN.jsonl --out config/references.json \\
        --report refsel_report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
import plan as planlib  # noqa: E402
import rqlib  # noqa: E402

SCHEMA = "finfolk.redqueen.refsel/1"
REFS_SCHEMA = "finfolk.redqueen.references/1"
OBS_SCHEMA = "finfolk.redqueen.refsel.obs/1"
SEED_NAMESPACE = "rq2026-refgrid"
VALIDATION_NAMESPACE = "finfolk-rq-validation-pilot-2026-11-a1"  # (the arena-#1 validation registry's: the references')
WORLDS_SCHEMA = "finfolk.redqueen.worlds/1"
N_SENTINELS = 4
SENTINEL_RULE = "the first four C worlds in id order of the bound validation registry (its sentinel flags, when present, must agree)"


def sentinels_of(reg):
    """The predetermined sentinels by the registered rule (never an argument): the first N_SENTINELS C worlds in
    id order of the validation registry. A registry that flags sentinels must flag exactly those."""
    cw = sorted(w["id"] for w in reg["worlds"] if w.get("treatment") == "C")
    if len(cw) < N_SENTINELS:
        raise RefselError(f"the validation registry has {len(cw)} C worlds; {N_SENTINELS} sentinels are registered")
    out = cw[:N_SENTINELS]
    flagged = sorted(w["id"] for w in reg["worlds"] if w.get("sentinel"))
    if flagged and flagged != out:
        raise RefselError(f"the registry's sentinel flags {flagged} disagree with the rule ({out})")
    return out
TIMES = ("F1", "20M", "60M", "100M", "120M", "140M", "180M", "200M")
REPLICATES = 6
HORIZON = 5000
N_PREY = 600
K = 6
CRITERION = {
    "version": 1, "n_ref": 8, "min_sentinels": 3, "early_max_M": 120, "min_early": 4, "late_min_M": 140,
    "min_late": 2, "ranks": [1, 2, 3, 4], "readouts": ["capture_logit", "survival_contrast"],
    "capture_bound": 324, "saturation": [0.02, 0.98], "saturation_penalty": 2.0, "eps": 1e-9,
    "variance_floor": "binomial", "max_saturated_share": 0.5,
    "tie_namespace": "rq2026-refsel", "max_swaps": 200, "replicates": REPLICATES, "horizon": HORIZON,
    "sv_tie_rel": 1e-8, "rank_max": 6, "replicate_rule": "exact 0..R-1 with matched controls",
}


class RefselError(Exception):
    pass


def frame_of(label):
    return 1 if label == "F1" else int(label[:-1]) * 1_000_000


def time_m(label):
    return frame_of(label) / 1e6


def tie_key(guild, world, frame, crit=CRITERION):
    return hashlib.sha256(f"{crit['tie_namespace']}|refsel|{guild}|{world}|{frame}".encode()).hexdigest()


# ================================================================== seeds (as worlds.py's --avoid reader)
def _collect_seeds(obj, out, hint=False):
    if isinstance(obj, dict):
        for k, v in obj.items():
            _collect_seeds(v, out, hint or "seed" in str(k).lower())
    elif isinstance(obj, list):
        for v in obj:
            _collect_seeds(v, out, hint)
    elif isinstance(obj, int) and not isinstance(obj, bool) and hint:
        out.add(obj)
    return out


def avoid_seeds(path):
    text = rqlib.read_text(path)
    try:
        doc = json.loads(text)
    except ValueError:
        doc = None
    if isinstance(doc, dict):
        return _collect_seeds(doc, set())
    rows = [json.loads(ln) for ln in text.split("\n") if ln.strip()]
    return planlib.plan_seeds(rows) | _collect_seeds(rows, set())


# ================================================================== the plan
def recipe(namespace, wid):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:redqueen:{namespace}:{wid}"))


def _registry(path, what):
    try:
        reg = rqlib.read_json(path)
    except (OSError, ValueError) as e:
        raise RefselError(f"{what} {path}: unreadable ({type(e).__name__})")
    if not isinstance(reg, dict) or not isinstance(reg.get("worlds"), list):
        raise RefselError(f"{what} {path}: not a worlds registry")
    return reg


def study_exclusion(main_registries, forks=None):
    """The study identities the references must avoid (sealing.study_identities over every main registry
    and the fork registry) -> (ids, snapshot ids, the registries' records)."""
    import sealing
    if not main_registries:
        raise RefselError("--main-registry: the main study's registries are mandatory (the references must be "
                          "disjoint from every study identity)")
    uuids, recs, branches = {}, [], {}
    for p in main_registries:
        m = _registry(p, "main registry")
        if m.get("namespace") == VALIDATION_NAMESPACE:
            raise RefselError(f"main registry {p}: the validation namespace itself")
        for w in m["worlds"]:
            uuids[f"{m.get('namespace')}/{w.get('id')}"] = w.get("uuid")
        recs.append({"path": os.path.abspath(p), "sha256": rqlib.sha256_file(p), "namespace": m.get("namespace")})
    if forks:
        fk = _registry(forks, "fork registry")
        for b in fk["worlds"]:
            branches[b.get("id")] = {"uuid": b.get("uuid")}
        recs.append({"path": os.path.abspath(forks), "sha256": rqlib.sha256_file(forks), "kind": "forks"})
    ids, snaps = sealing.study_identities(uuids, branches)
    return ids, snaps, recs


def bind_validation(block, validation_dir, main_registries, forks=None):
    """THE BINDING (see the module docstring; Codex #71 r1 P1) -> the binding record."""
    if block.get("schema") != "finfolk.redqueen.worldsblock/1":
        raise RefselError(f"worlds block schema {block.get('schema')!r}")
    if not validation_dir:
        raise RefselError("--validation-dir: the validation run (its registry) is mandatory")
    vdir = os.path.abspath(validation_dir)
    rp = os.path.join(vdir, "config", "worlds.json")
    if not os.path.isfile(rp):
        raise RefselError(f"no validation registry at {rp}")
    reg = _registry(rp, "validation registry")
    sha = rqlib.sha256_file(rp)
    if block.get("registry_sha256") != sha:
        raise RefselError(f"the worlds block was not made from the validation registry {rp}")
    if block.get("root") is not None and os.path.abspath(block["root"]) != vdir:
        raise RefselError(f"the worlds block was read from {block['root']!r}, not {vdir!r}")
    if reg.get("schema") != WORLDS_SCHEMA or reg.get("namespace") != VALIDATION_NAMESPACE:
        raise RefselError(f"registry namespace {reg.get('namespace')!r}: the references come from the validation "
                          f"registry ({VALIDATION_NAMESPACE})")
    by = {w.get("id"): w for w in reg["worlds"]}
    sent = sentinels_of(reg)
    for w in sent:
        r = by.get(w)
        if r is None or r.get("treatment") != "C" or r.get("uuid") != recipe(VALIDATION_NAMESPACE, w):
            raise RefselError(f"sentinel {w} is not a registered C identity of the validation namespace")
        if w not in block["worlds"]:
            raise RefselError(f"sentinel {w} is not in the worlds block")
    ids, snaps, recs = study_exclusion(main_registries, forks)
    for w in sent:
        u = by[w]["uuid"]
        if u in ids:
            raise RefselError(f"sentinel {w}'s identity is a study identity ({ids[u]})")
        for lab in TIMES:
            s = planlib.snapshot_uuid(u, frame_of(lab))
            if s in snaps:
                raise RefselError(f"sentinel {w}@{lab} is a study snapshot identity ({snaps[s]})")
    return {"validation_dir": vdir, "registry": rp, "registry_sha256": sha, "namespace": VALIDATION_NAMESPACE,
            "sentinels": sent, "sentinel_rule": SENTINEL_RULE, "studies": recs}


def attempt_uuid(base, k):
    """val_block.py's identity of a restarted attempt k > 0 (worlds.py keeps the registry uuid instead)."""
    return base if not k else str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:attempt:{base}:{k}"))


BURN_IN = 5_000_000              # (the validation run's burn-in rule: a zero before it restarts the world)


def establishment(a, burn_in=BURN_IN):
    """THE EVIDENCED ESTABLISHMENT DECISION of a sentinel's current attempt, as worlds.py's burn_in_decided,
    from the block's evidence and SEPARATE from its technical status (Codex #71 r4 P2-1) -> (established, why):
      - no burn-in rule: established;
      - an evidenced zero (valid_before) before the burn-in frame: NOT established (a restart is due, or the
        restarts are exhausted: an early failure), whatever the status;
      - a first zero at or after the burn-in frame: established (data);
      - no zero: established when its FULL archive (archived_through, recorded before any projection on the
        candidate times) reaches the burn-in frame alive, else not yet.
    A later technical failure ("failed") keeps an established attempt's valid snapshots."""
    if not burn_in:
        return True, "no burn-in rule"
    vb = a.get("valid_before")
    if vb is not None and vb < burn_in:
        return False, f"a zero at frame {vb} before the burn-in frame {burn_in}"
    if vb is not None:
        return True, f"its first zero {vb} is at or after the burn-in frame"
    through = a.get("archived_through")             # (Codex #71 r5: the FULL archive, never its projection on TIMES)
    if through is None:
        through = max([f for f in (a.get("archived") or []) if isinstance(f, int)] or [0])
    if through >= burn_in:
        return True, "alive at the burn-in frame"
    return False, f"not yet alive at the burn-in frame {burn_in}"


def availability_reason(a, w, lab):
    """THE AVAILABILITY RULE (Codex #71 r3 P2, r4): None when (w, lab) is a candidate, else the registered
    omission reason, from the availability record alone:
      - the sentinel's current attempt must be ESTABLISHED (the evidenced decision, never the technical
        status), its identity the registered recipe (worlds.py keeps it across restarts) or val_block's
        attempt identity of it;
      - the snapshot must be archived and before the world's first zero."""
    reg_uuid = recipe(VALIDATION_NAMESPACE, w)
    k = a.get("attempt") or 0
    fr = frame_of(lab)
    if a.get("uuid") not in (reg_uuid, attempt_uuid(reg_uuid, k)):
        return "an identity that is not the registered one (nor its attempt's)"
    ok, why = establishment(a, a.get("burn_in", BURN_IN))
    if not ok:
        return f"attempt {k} is not established ({why})"
    if fr not in (a.get("archived") or []):
        return "not archived"
    if a.get("valid_before") is not None and fr >= a["valid_before"]:
        return f"at or after the world's first zero (frame {a['valid_before']})"
    return None


def candidates(block, sentinels, reg=None):
    """The usable (sentinel, time) candidates (the same for both guilds), the omitted ones with their reasons
    (the extinction fallback) and every sentinel's availability record. A sentinel's ESTABLISHED current
    attempt is accepted (Codex #71 r3 P2-3: a burn-in restart keeps the predetermined identity): its attempt
    number, seed and archive provenance are bound in the availability record."""
    ws = block["worlds"]
    by = {w.get("id"): w for w in (reg or {}).get("worlds", [])}
    out, omitted, avail = [], [], {}
    for w in sentinels:
        v = ws[w]
        k = v.get("attempt") or 0
        rw = by.get(w, {})
        seed = rw.get("founder_seed") if not k else next(
            (r["seeds"][k] for r in (reg or {}).get("reserved", []) if r.get("slot") == rw.get("seed_slot")
             and k < len(r.get("seeds", []))), None)
        avail[w] = {"uuid": v.get("uuid"), "attempt": k, "status": v.get("status"), "seed": seed,
                    "burn_in": BURN_IN if (reg or {}).get("burn_in") is None else int(reg["burn_in"]),   # (0: no rule)
                    "archived_through": max([f for f in v.get("archived", []) if isinstance(f, int)] or [0]),
                    "pattern": v.get("pattern"), "f1": (v.get("paths") or {}).get("F1"),
                    "valid_before": v.get("valid_before"),
                    "archived": sorted(f for f in v.get("archived", []) if f in {frame_of(t) for t in TIMES})}
        for lab in TIMES:
            fr = frame_of(lab)
            if block["times"].get(lab) != fr:
                raise RefselError(f"the worlds block has no time {lab} = frame {fr}")
            why = availability_reason(avail[w], w, lab)
            if why is None:
                out.append((w, lab))
            else:
                omitted.append({"world": w, "time": lab, "reason": why})
    return out, omitted, avail


def feasible(chosen, pool, crit=CRITERION):
    """Can `chosen` (a list of (world, label)) be completed from `pool` (the unchosen candidates) to a
    set meeting every constraint? Exact: a search over the counts of the (sentinel, early / late / other)
    attribute types."""
    need = crit["n_ref"] - len(chosen)
    if need < 0:
        return False

    def cls(lab):
        t = time_m(lab)
        return "E" if t <= crit["early_max_M"] else "L" if t >= crit["late_min_M"] else "O"
    avail = {}
    for w, lab in pool:
        avail[(w, cls(lab))] = avail.get((w, cls(lab)), 0) + 1
    types = sorted(avail)
    have_s = {w for w, _ in chosen}
    have_e = sum(1 for _, lab in chosen if cls(lab) == "E")
    have_l = sum(1 for _, lab in chosen if cls(lab) == "L")

    def ok(counts):
        s = have_s | {types[i][0] for i, c in enumerate(counts) if c}
        e = have_e + sum(c for i, c in enumerate(counts) if types[i][1] == "E")
        lt = have_l + sum(c for i, c in enumerate(counts) if types[i][1] == "L")
        return len(s) >= crit["min_sentinels"] and e >= crit["min_early"] and lt >= crit["min_late"]

    def rec(i, left, counts):
        if i == len(types):
            return left == 0 and ok(counts)
        for c in range(min(left, avail[types[i]]), -1, -1):
            if rec(i + 1, left - c, counts + [c]):
                return True
        return False
    return rec(0, need, [])


def make_design(block, templates, ages, avoid_paths, validation_dir=None, main_registries=(), forks=None,
                ns=SEED_NAMESPACE):
    binding = bind_validation(block, validation_dir, main_registries, forks)
    if not isinstance(ages, str) or not os.path.isabs(ages) or not os.path.isfile(ages):
        raise RefselError("--age-reference: the production age reference (an absolute path to a file) is mandatory")
    if not avoid_paths:
        raise RefselError("--avoid: the production reservations are mandatory")
    cands, omitted, avail = candidates(block, binding["sentinels"], _registry(binding["registry"], "validation registry"))
    if not feasible([], cands):
        raise RefselError(f"the usable candidates ({len(cands)}; omitted: {len(omitted)}) cannot meet the "
                          "registered constraints (a sentinel is never replaced)")
    ws = block["worlds"]
    worlds = {w: {"uuid": recipe(VALIDATION_NAMESPACE, w), "pattern": ws[w]["pattern"], "paths": ws[w].get("paths", {})}
              for w in sorted({w for w, _ in cands})}       # (the REGISTERED identity, before plan expansion:
    #                                                         the assayed endpoints carry what selection emits)
    times = {lab: frame_of(lab) for lab in TIMES}
    edges = []
    for wq, tq in cands:
        prey = {"world": wq, "time": tq}
        base = {"role": "diagnostic", "horizon": "short", "prey": prey, "namespace": "refgrid"}
        for wp, tp in cands:
            edges.append(dict(base, family="refgrid", predators={"world": wp, "time": tp}))
        edges.append(dict(base, family="refgrid-free", predators=None))
    for n, e in enumerate(edges, 1):
        e["edge"] = f"ref{n:05d}"
    design = {"schema": "finfolk.redqueen.design/2", "name": "refgrid", "seed_namespace": ns, "times": times,
              "worlds": worlds, "templates": list(templates), "age_reference": ages, "replicates": REPLICATES,
              "defaults": {"assay": "frozen", "k": K, "prey_policy": "common", "n_prey": N_PREY,
                           "short_steps": HORIZON, "short_horizons": [HORIZON]},
              "long": {"fraction": 0.0}, "edges": edges}
    try:
        rows, _, _ = planlib.expand_v2(design, pending=True)
    except planlib.DesignError as e:
        raise RefselError(f"plan.py refuses the design: {e}")
    seeds = planlib.plan_seeds(rows)
    checked = []
    for p in avoid_paths:
        hit = sorted(seeds & avoid_seeds(p))
        if hit:
            raise RefselError(f"{len(hit)} grid engine seed(s) are reserved in {p}: {hit[:5]}")
        checked.append({"path": os.path.abspath(p), "sha256": rqlib.sha256_file(p)})
    design["refsel"] = {"schema": SCHEMA, "criterion": CRITERION, "criterion_sha256": rqlib.canonical_sha(CRITERION),
                        "sentinels": binding["sentinels"], "sentinel_namespace": VALIDATION_NAMESPACE, "binding": binding,
                        "candidates": [[w, t] for w, t in cands], "omitted": omitted, "availability": avail,
                        "availability_sha256": rqlib.canonical_sha(avail), "block_sha256": rqlib.canonical_sha(block),
                        "registry_sha256": block.get("registry_sha256"), "avoid": checked, "cells": len(rows)}
    return design


def rebind(design, main_registries=None, forks=None):
    """The binding checked AGAIN at selection (Codex #71 r1 P1): the recorded validation registry unchanged,
    the sentinels and namespace the registered ones, and the exclusion re-evaluated on the CURRENT main /
    fork registries (the recorded ones unless given) -> the current studies record."""
    rs = design.get("refsel") or {}
    b = rs.get("binding") or {}
    if rs.get("sentinel_namespace") != VALIDATION_NAMESPACE or b.get("namespace") != VALIDATION_NAMESPACE:
        raise RefselError("the design's namespace is not the registered one")
    if not b.get("registry") or not os.path.isfile(b["registry"]) or rqlib.sha256_file(b["registry"]) != b.get("registry_sha256"):
        raise RefselError("the validation registry the plan was bound to is missing or changed")
    reg = _registry(b["registry"], "validation registry")              # (Codex #71 r2 P1: its content, not only its hash)
    by = {w.get("id"): w for w in reg["worlds"]}
    if reg.get("schema") != WORLDS_SCHEMA or reg.get("namespace") != VALIDATION_NAMESPACE:
        raise RefselError("the validation registry's schema / namespace are not the registered ones")
    sent = sentinels_of(reg)                     # (re-derived by the rule from the registry's content)
    if rs.get("sentinels") != sent or b.get("sentinels") != sent:
        raise RefselError(f"the design's sentinels {rs.get('sentinels')} are not the rule's {sent}")
    for w in sent:
        r_ = by.get(w)
        if r_ is None or r_.get("treatment") != "C" or r_.get("uuid") != recipe(VALIDATION_NAMESPACE, w):
            raise RefselError(f"sentinel {w} is not a registered C identity of the validation namespace")
    mains = list(main_registries) if main_registries else [r["path"] for r in b.get("studies", []) if r.get("kind") != "forks"]
    fk = forks or next((r["path"] for r in b.get("studies", []) if r.get("kind") == "forks"), None)
    ids, snaps, recs = study_exclusion(mains, fk)
    for w in sent:                               # (all four identities, omitted ones included)
        u = recipe(VALIDATION_NAMESPACE, w)
        if u in ids or any(planlib.snapshot_uuid(u, frame_of(lab)) in snaps for lab in TIMES):
            raise RefselError(f"sentinel {w}'s identity or a snapshot of it is a study identity")
    times = design.get("times") or {}                  # (Codex #71 r3 P1: the SOURCE frames are the canonical ones)
    if any(times.get(lab) != frame_of(lab) for lab in TIMES) or any(frame_of(lab) != fr for lab, fr in times.items()
                                                                     if lab in TIMES):
        raise RefselError("the design's time map is not the canonical one (a label mapped to another frame)")
    avail = rs.get("availability") or {}
    if rqlib.canonical_sha(avail) != rs.get("availability_sha256") or set(avail) != set(sent):
        raise RefselError("the recorded availability does not match its sha256 or the sentinels")
    expected = {(w, lab) for w in sent for lab in TIMES}
    cand = [tuple(c) for c in rs["candidates"]]
    om = rs.get("omitted", [])
    omk = [(o.get("world"), o.get("time")) for o in om]
    if len(set(cand)) != len(cand) or len(set(omk)) != len(omk) or set(cand) & set(omk) \
            or set(cand) | set(omk) != expected:
        raise RefselError("the candidates and the omissions are not exactly the registered sentinel x time set")
    for w, lab in expected:                            # (availability alone decides the membership and the reason)
        why = availability_reason(avail[w], w, lab)
        if (why is None) != ((w, lab) in set(cand)):
            raise RefselError(f"{w}@{lab}: its membership disagrees with the recorded availability")
    for o in om:
        if o.get("reason") != availability_reason(avail[o["world"]], o["world"], o["time"]):
            raise RefselError(f"{o['world']}@{o['time']}: the omission reason is not the availability's")
    for w, lab in cand:
        if design["worlds"][w]["uuid"] != recipe(VALIDATION_NAMESPACE, w):
            raise RefselError(f"candidate {w}@{lab}: the design's identity is not the registered one")
    return recs


def check_plan_endpoints(rows):
    """Codex #71 r3 P1: every bound source endpoint of the final plan carries the CANONICAL frame of its time
    label and the snapshot identity of that frame."""
    for cid, r in rows.items():
        for role in ("prey", "predators"):
            e = r.get(role)
            if not isinstance(e, dict):
                continue
            fr = frame_of(e.get("time"))
            if e.get("frame") != fr or e.get("snapshot") != planlib.snapshot_uuid(e.get("uuid"), fr):
                raise RefselError(f"plan cell {cid}: its {role} endpoint is not {e.get('time')}'s canonical frame")


# ================================================================== collect (bound to the final plan)
HASHED = ("prey", "predators", "template", "ages")


def _unhashed(row):
    r = json.loads(json.dumps(row))
    for k in HASHED:
        if isinstance(r.get(k), dict):
            r[k].pop("sha256", None)
    return r


def bind_plan(design, plan_path):
    exp, _, _ = planlib.expand_v2(design, pending=True)
    want = {r["id"]: r for r in exp}
    got = {}
    for ln in rqlib.read_text(plan_path).split("\n"):
        if ln.strip():
            r = json.loads(ln)
            if r.get("id") in got:
                raise RefselError(f"plan {plan_path}: cell {r.get('id')} occurs twice")
            got[r.get("id")] = r
    if set(got) != set(want):
        raise RefselError(f"plan {plan_path}: not the design's cells ({len(set(want) ^ set(got))} differ)")
    for cid, r in got.items():
        if _unhashed(r) != _unhashed(want[cid]):
            raise RefselError(f"plan {plan_path}: cell {cid} differs from the design's expansion")
        for k in HASHED:
            x = r.get(k)
            if isinstance(x, dict) and x.get("path") and not (isinstance(x.get("sha256"), str) and len(x["sha256"]) == 64):
                raise RefselError(f"plan {plan_path}: cell {cid} has no content hash for its {k} (a pending plan)")
    return got, rqlib.sha256_file(plan_path)


def collect(study, design, plan_path, declared_missing=()):
    return collect_with_age_diagnostics(study, design, plan_path, declared_missing)[0]


def collect_with_age_diagnostics(study, design, plan_path, declared_missing=()):
    """collect's observations (the same bytes) and, separately versioned, the collected cells'
    age-stratified diagnostics (D8 v2 rule 48; store.age_diagnostics_doc). A /3 bundle without its
    complete age summary is refused; a /1 or /2 bundle's diagnostics are explicitly unavailable.
    (Codex re-review of 6407f80, P2) Every indexed bundle is read through store.read_packed: one that
    cannot be read (a compression method pack() never writes, refused before decoding; damaged bytes; a
    mismatch with the index) refuses the WHOLE collection, naming the root, chunk and cell, whatever its
    design: its design is inside the unreadable bundle, so it is never skipped (store.collect_refusal)."""
    import store
    rows, plan_sha = bind_plan(design, plan_path)
    try:
        _, cells = store.load_index(study)
    except store.StoreError as e:
        raise RefselError(f"study {study}: its chunk index cannot be read ({e})")
    obs, ages = [], []
    for cid in sorted(cells):
        try:
            b = json.loads(store.read_packed(study, cid, cells=cells))
        except store.StoreError as e:
            raise RefselError(store.collect_refusal(e, cid in rows))
        c = b["cell"]
        if c.get("design") != design.get("name"):
            continue
        row = rows.get(cid)
        if row is None or rqlib.canonical(c) != rqlib.canonical(row):
            raise RefselError(f"{cid}: not exactly a cell of the final plan")
        if b["score"].get("n_start") != N_PREY:
            raise RefselError(f"{cid}: cohort {b['score'].get('n_start')}, not {N_PREY}")
        try:
            ages.append(store.age_diagnostics_entry(cid, b))
        except store.StoreError as e:
            raise RefselError(str(e))
        h = [x for x in b["score"]["horizons"] if x["steps"] == HORIZON]
        if len(h) != 1:
            raise RefselError(f"{cid}: no single {HORIZON}-step horizon")
        p = row["predators"]
        obs.append({"cell": cid, "prey": [row["prey"]["world"], row["prey"]["time"]],
                    "pred": None if p is None else [p["world"], p["time"]], "replicate": row["replicate"],
                    "captures": h[0].get("captures"), "survivors": h[0]["survivors"], "cohort": N_PREY})
    missing = sorted(set(rows) - {o["cell"] for o in obs})
    if missing != sorted(set(declared_missing)):
        raise RefselError(f"{len(missing)} plan cells are not collected; a missing cell must be declared exactly")
    doc = {"schema": OBS_SCHEMA, "design_sha256": rqlib.canonical_sha(design), "plan_sha256": plan_sha,
           "missing": missing, "observations": obs}
    return doc, store.age_diagnostics_doc(doc, ages)


# ================================================================== the criterion
def matrices(obs, cands, crit=CRITERION):
    """Replicate-level readouts -> per readout the mean matrix (prey x predator candidates) and the cell
    variance of the mean, plus each cell's saturation flags."""
    import numpy as np
    n = len(cands)
    pos = {tuple(c): i for i, c in enumerate(cands)}
    R = crit["replicates"]
    B = crit["capture_bound"]
    free = {}
    cells = {}
    for o in obs:
        r_ = o.get("replicate")
        if not isinstance(r_, int) or isinstance(r_, bool) or not 0 <= r_ < R:
            raise RefselError(f"{o.get('cell')}: replicate {r_!r} is not one of the registered 0..{R - 1}")
        if o.get("cohort") != N_PREY or isinstance(o.get("cohort"), bool):      # (Codex #71 r2 P2: survival / 600)
            raise RefselError(f"{o.get('cell')}: cohort {o.get('cohort')!r}, not the registered {N_PREY}")
        if not (isinstance(o.get("survivors"), int) and 0 <= o["survivors"] <= N_PREY):
            raise RefselError(f"{o.get('cell')}: survivors {o.get('survivors')!r}")
        q = pos.get(tuple(o["prey"]))
        if q is None:
            raise RefselError(f"{o.get('cell')}: prey {o['prey']} is not a candidate")
        if o["pred"] is None:
            if (q, o["replicate"]) in free:
                raise RefselError(f"free control {o['prey']} r{o['replicate']} twice")
            free[(q, o["replicate"])] = o["survivors"]
            continue
        p = pos.get(tuple(o["pred"]))
        if p is None:
            raise RefselError(f"{o.get('cell')}: predators {o['pred']} are not a candidate")
        c = o.get("captures")
        if not (isinstance(c, int) and 0 <= c):
            raise RefselError(f"{o.get('cell')}: captures {c!r}")
        cells.setdefault((q, p), {})
        if o["replicate"] in cells[(q, p)]:
            raise RefselError(f"cell {o['prey']} x {o['pred']} r{o['replicate']} twice")
        cells[(q, p)][o["replicate"]] = (c, o["survivors"])
    out = {k: np.full((n, n), np.nan) for k in ("l_mean", "l_var", "q_mean", "q_var", "cap_frac", "surv")}
    want = list(range(R))
    for q in range(n):                          # (Codex #71 r1 P2-2: exactly R replicates, controls matched)
        if [r for r in want if (q, r) in free] != want:
            raise RefselError(f"prey candidate {cands[q]}: its predator-free controls are not exactly replicates 0..{R - 1}")
    for (q, p), reps in cells.items():
        rs = sorted(reps)
        if rs != want:
            raise RefselError(f"cell {cands[q]} x {cands[p]}: replicates {rs}, not exactly 0..{R - 1}")
        lv = [math.log((reps[r][0] + 0.5) / (B + 1 - reps[r][0] - 0.5)) if reps[r][0] < B + 0.5 else math.inf for r in rs]
        if not all(math.isfinite(x) for x in lv):
            raise RefselError(f"captures above the capture bound {B} in {cands[q]} x {cands[p]}")
        qv = [(reps[r][1] - free[(q, r)]) / N_PREY for r in rs]
        # the cell's variance of the mean: the replicate variance, floored at the binomial (count)
        # variance (a saturated cell's replicates barely vary, but it carries little information)
        pc = (np.mean([reps[r][0] for r in rs]) + 0.5) / (B + 1)
        ps = np.mean([reps[r][1] for r in rs]) / N_PREY
        p0 = np.mean([free[(q, r)] for r in rs]) / N_PREY
        lfloor = 1.0 / (B * pc * (1 - pc)) / len(rs)
        qfloor = (max(ps * (1 - ps), 0.25 / N_PREY) + max(p0 * (1 - p0), 0.25 / N_PREY)) / N_PREY / len(rs)
        out["l_mean"][q, p], out["l_var"][q, p] = np.mean(lv), max(np.var(lv, ddof=1) / len(rs), lfloor)
        out["q_mean"][q, p], out["q_var"][q, p] = np.mean(qv), max(np.var(qv, ddof=1) / len(rs), qfloor)
        out["cap_frac"][q, p] = np.mean([reps[r][0] / B for r in rs])
        out["surv"][q, p] = ps
    for k, v in out.items():
        if np.isnan(v).any():
            miss = int(np.isnan(v).sum())
            raise RefselError(f"the candidate grid is incomplete: {miss} cells missing (the criterion needs the "
                              "full grid at every registered replicate)")
    return out


def embeddings(mats, crit=CRITERION):
    """Per guild and readout: the candidates' rank-4 embeddings, noise weights; per guild the saturation
    shares. Guild "RP" (predator references, placing prey): the columns; "RQ": the rows."""
    import numpy as np
    lo, hi = crit["saturation"]
    rmax = max(crit["ranks"])
    out = {}
    for guild, axis in (("RP", 1), ("RQ", 0)):
        g = {"readouts": {}}
        for name, mk, vk in (("capture_logit", "l_mean", "l_var"), ("survival_contrast", "q_mean", "q_var")):
            M = mats[mk]
            Mc = M - M.mean(axis=1, keepdims=True) - M.mean(axis=0, keepdims=True) + M.mean()
            U, S, Vt = np.linalg.svd(Mc)
            reff = tied_ranks(S, crit)
            k = max(reff.values())
            Ssq = np.sqrt(S[:k])
            emb = (Vt[:k].T * Ssq) if axis == 1 else (U[:, :k] * Ssq)
            var = mats[vk].mean(axis=0) if axis == 1 else mats[vk].mean(axis=1)
            if np.any(var <= 0):
                raise RefselError(f"{guild} {name}: a candidate with zero replicate variance")
            g["readouts"][name] = {"emb": emb, "w": 1.0 / var, "sv": S[:k].tolist(), "reff": reff}
        satC = ((mats["cap_frac"] < lo) | (mats["cap_frac"] > hi)).mean(axis=0 if axis == 1 else 1)
        satS = ((mats["surv"] < lo) | (mats["surv"] > hi)).mean(axis=0 if axis == 1 else 1)
        g["sat"] = (satC + satS) / 2
        out[guild] = g
    return out


def tied_ranks(S, crit=CRITERION):
    """{r: r_eff}: each registered rank extended to the end of its tied singular-value group (values within
    sv_tie_rel x the largest of each other: Codex #71 r1 P2-6), at most rank_max = 6 (identifiable with eight
    references: Codex #71 r2 P2). A tie group crossing rank_max is a STRUCTURAL DEGENERACY: the selection is
    refused (with noisy assays exact ties are practically impossible)."""
    tol = crit["sv_tie_rel"] * (float(S[0]) if len(S) else 0.0)
    out = {}
    for r in crit["ranks"]:
        k = min(r, len(S))
        while k < len(S) and abs(float(S[k - 1]) - float(S[k])) <= tol:
            k += 1
        if k > crit["rank_max"]:
            raise RefselError(f"structural degeneracy: rank {r} lies in a tied singular-value group that ends at "
                              f"rank {k} > {crit['rank_max']}")
        out[r] = k
    return out


def objective(g, idx, crit=CRITERION, detail=False):
    """The registered objective of a candidate index set for one guild (see the module doc)."""
    import numpy as np
    n = len(g["sat"])
    total, parts = 0.0, {}
    for name, rd in g["readouts"].items():
        for r in crit["ranks"]:
            k = rd["reff"][r]
            X = np.hstack([np.ones((n, 1)), rd["emb"][:, :k]])
            Iall = (X * rd["w"][:, None]).T @ X
            eps = crit["eps"] * np.trace(Iall) / ((k + 1) * n)
            I = (X[idx] * rd["w"][idx][:, None]).T @ X[idx] + eps * np.eye(k + 1)
            lam = float(np.linalg.eigvalsh((I + I.T) / 2)[0])
            v = math.log(max(lam, 1e-300))
            parts[f"{name}/rank{r}"] = v
            total += v
    pen = crit["saturation_penalty"] * float(np.sum(g["sat"][idx]))
    total -= pen
    if detail:
        return total, dict(parts, saturation_penalty=pen)
    return total


def select_guild(g, cands, guild, crit=CRITERION):
    """Greedy, then the best improving swaps; ties by the registered hash order. -> (indices, log)."""
    order = sorted((i for i in range(len(cands)) if g["sat"][i] <= crit["max_saturated_share"]),
                   key=lambda i: tie_key(guild, cands[i][0], frame_of(cands[i][1]), crit))
    rank = {i: k for k, i in enumerate(order)}
    if not feasible([], [cands[i] for i in order], crit):
        raise RefselError(f"{guild}: the eligible (not mostly saturated) candidates cannot meet the constraints")
    chosen, log = [], []

    def better(a, b):            # (value, tie rank): a strictly better than b
        if b is None:
            return True
        if a[0] > b[0] + 1e-12 * max(1.0, abs(b[0])):
            return True
        return abs(a[0] - b[0]) <= 1e-12 * max(1.0, abs(b[0])) and a[1] < b[1]
    while len(chosen) < crit["n_ref"]:
        best = None
        for i in order:
            if i in chosen:
                continue
            S = chosen + [i]
            pool = [cands[j] for j in order if j not in S]
            if not feasible([cands[j] for j in S], pool, crit):
                continue
            cand = (objective(g, S, crit), rank[i], i)
            if better(cand, best):
                best = cand
        if best is None:
            raise RefselError(f"{guild}: no candidate keeps the constraints satisfiable")
        chosen.append(best[2])
        log.append({"add": list(cands[best[2]]), "objective": best[0]})
    cur = objective(g, chosen, crit)
    converged = False
    for _ in range(crit["max_swaps"] + 1):
        best = None
        for s in sorted(chosen, key=lambda i: rank[i]):
            for c in order:
                if c in chosen:
                    continue
                S = [c if x == s else x for x in chosen]
                if not feasible([cands[j] for j in S], [], crit):
                    continue
                v = objective(g, S, crit)
                if v > cur + 1e-9 * max(1.0, abs(cur)):
                    cand = (v, rank[s] * len(cands) + rank[c], (s, c))
                    if better(cand, best):
                        best = cand
        if best is None:
            converged = True
            break
        if sum(1 for x in log if "swap_in" in x) >= crit["max_swaps"]:
            break                       # (an improving exchange remains: the limit, not convergence)
        s, c = best[2]
        chosen = [c if x == s else x for x in chosen]
        cur = best[0]
        log.append({"swap_out": list(cands[s]), "swap_in": list(cands[c]), "objective": cur})
    log.append({"converged": converged, "swaps": sum(1 for x in log if "swap_in" in x),
                "max_swaps": crit["max_swaps"]})
    return chosen, log


def check_observations(obs, plan_rows):
    """Codex #71 r1 P2-3: every observation is exactly a cell of the final plan (its id, prey, predators,
    replicate), each cell once."""
    seen = set()
    for o in obs:
        cid = o.get("cell")
        r = plan_rows.get(cid)
        if r is None:
            raise RefselError(f"observation {cid!r} is not a cell of the final plan")
        if cid in seen:
            raise RefselError(f"observation {cid!r} occurs twice")
        seen.add(cid)
        p = r.get("predators")
        if (list(o.get("prey") or []) != [r["prey"]["world"], r["prey"]["time"]] or o.get("replicate") != r["replicate"]
                or (o.get("pred") is None) != (p is None)
                or (p is not None and list(o["pred"]) != [p["world"], p["time"]])):
            raise RefselError(f"observation {cid!r} disagrees with its plan row")


def implementation():
    import numpy as np
    return {"refsel_sha256": rqlib.sha256_file(os.path.abspath(__file__)), "numpy": np.__version__}


def select(obs, design, plan_rows=None, crit=CRITERION, studies=None, plan_sha=None):
    """The registered selection from the grid observations -> (references/1 document with its provenance
    receipt, report). plan_rows: the final plan (every observation is checked against it)."""
    rs = design["refsel"]
    if rs["criterion_sha256"] != rqlib.canonical_sha(crit) or rs["criterion"] != crit:
        raise RefselError("the criterion is not the one frozen in the plan (sha256 differs)")
    if plan_rows is not None:
        check_plan_endpoints(plan_rows)
        check_observations(obs, plan_rows)
    cands = [tuple(c) for c in rs["candidates"]]
    mats = matrices(obs, cands, crit)
    emb = embeddings(mats, crit)
    ns = rs["sentinel_namespace"]
    refs, report = {}, {"criterion_sha256": rs["criterion_sha256"], "guilds": {}}
    for guild in ("RQ", "RP"):
        idx, log = select_guild(emb[guild], cands, guild, crit)
        conv = log.pop()
        total, parts = objective(emb[guild], idx, crit, detail=True)
        sel = sorted((cands[i] for i in idx), key=lambda c: (frame_of(c[1]), tie_key(guild, c[0], frame_of(c[1]), crit)))
        for k, (w, lab) in enumerate(sel):
            fr = frame_of(lab)
            wu = recipe(VALIDATION_NAMESPACE, w)          # (the predetermined identity, whatever the attempt)
            ent = {"world": w, "frame": fr, "uuid": wu, "snapshot": planlib.snapshot_uuid(wu, fr),
                   "archive": planlib.snapshot_path(design, w, lab),
                   "attempt": (rs.get("availability") or {}).get(w, {}).get("attempt", 0)}
            ent["sha256"] = _archive_sha(plan_rows, w, lab, guild) if plan_rows else None
            refs[f"{guild}:{k}"] = ent
        report["guilds"][guild] = {"selected": [list(c) for c in sel], "objective": total, "parts": parts,
                                   "steps": log, "sentinels": sorted({w for w, _ in sel}),
                                   "early": sum(1 for _, t in sel if time_m(t) <= crit["early_max_M"]),
                                   "late": sum(1 for _, t in sel if time_m(t) >= crit["late_min_M"]),
                                   "singular_values": {k: v["sv"] for k, v in emb[guild]["readouts"].items()},
                                   "effective_ranks": {k: {str(r): e for r, e in v["reff"].items()}
                                                       for k, v in emb[guild]["readouts"].items()},
                                   "search": conv}
    receipt = {"refsel_schema": SCHEMA, "criterion_sha256": rs["criterion_sha256"],
               "design_sha256": rqlib.canonical_sha(design), "plan_sha256": plan_sha,
               "observations_sha256": rqlib.canonical_sha(sorted(obs, key=lambda o: str(o.get("cell")))),
               "observations": len(obs), "block_sha256": rs.get("block_sha256"),
               "availability_sha256": rs.get("availability_sha256"), "availability": rs.get("availability"),
               "omitted": rs.get("omitted", []), "binding": rs.get("binding"), "studies_checked": studies,
               "implementation": implementation()}
    doc = {"schema": REFS_SCHEMA, "namespace": ns, "references": refs, "selection": receipt}
    report["receipt_sha256"] = rqlib.canonical_sha(receipt)
    return doc, report


def _archive_sha(rows, world, label, guild):
    """The snapshot file's sha256 as the final plan registered it (the prey role for RQ, predators for RP)."""
    role = "prey" if guild == "RQ" else "predators"
    for r in rows.values():
        x = r.get(role)
        if isinstance(x, dict) and x.get("world") == world and x.get("time") == label and x.get("sha256"):
            return x["sha256"]
    raise RefselError(f"no plan row carries the {role} snapshot {world} {label}")


# ================================================================== CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan")
    s.add_argument("--block", required=True)
    s.add_argument("--validation-dir", required=True)
    s.add_argument("--main-registry", action="append", default=[], help="the main study's registries (mandatory)")
    s.add_argument("--forks", help="the fork registry (its branch identities are excluded too)")
    s.add_argument("--templates", nargs="+", required=True)
    s.add_argument("--age-reference", required=True)
    s.add_argument("--avoid", action="append", required=True)
    s.add_argument("--namespace", default=SEED_NAMESPACE)
    s.add_argument("--out", required=True)
    s = sub.add_parser("collect")
    s.add_argument("--study", required=True)
    s.add_argument("--design", required=True)
    s.add_argument("--plan", required=True)
    s.add_argument("--declare-missing")
    s.add_argument("--out", required=True)
    s.add_argument("--age-diagnostics", help="also write the collected cells' age-stratified diagnostics "
                   "(finfolk.redqueen.agediagnostics/1, D8 rule 48) to this path")
    s = sub.add_parser("select")
    s.add_argument("obs")
    s.add_argument("--design", required=True)
    s.add_argument("--plan", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--report", required=True)
    s.add_argument("--main-registry", action="append", default=[], help="(default: the plan's recorded ones)")
    s.add_argument("--forks", help="(default: the plan's recorded fork registry, if any)")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":
            d = make_design(rqlib.read_json(a.block), a.templates, a.age_reference, a.avoid, a.validation_dir,
                            a.main_registry, a.forks, a.namespace)
            rqlib.write_json_durable(a.out, d)
            print(f"{len(d['refsel']['candidates'])} candidates per guild; {d['refsel']['cells']} cells; "
                  f"criterion {d['refsel']['criterion_sha256'][:16]}")
            return 0
        design = rqlib.read_json(a.design)
        if a.cmd == "collect":
            miss = ([x.strip() for x in rqlib.read_text(a.declare_missing).split("\n") if x.strip()]
                    if a.declare_missing else [])
            doc, ages = collect_with_age_diagnostics(a.study, design, a.plan, miss)
            rqlib.write_json_durable(a.out, doc)
            if a.age_diagnostics:
                rqlib.write_json_durable(a.age_diagnostics, ages)
            print(f"{len(doc['observations'])} observations; missing {len(doc['missing'])}")
            return 0
        doc = rqlib.read_json(a.obs)
        rows, plan_sha = bind_plan(design, a.plan)
        if doc.get("schema") != OBS_SCHEMA or doc.get("plan_sha256") != plan_sha \
                or doc.get("design_sha256") != rqlib.canonical_sha(design):
            raise RefselError("the observations were not collected under this design and final plan")
        studies = rebind(design, a.main_registry or None, a.forks)
        refs, report = select(doc["observations"], design, rows, studies=studies, plan_sha=plan_sha)
        report["plan_sha256"] = plan_sha
        rqlib.write_json_durable(a.out, refs)
        rqlib.write_json_durable(a.report, report)
        for g in ("RQ", "RP"):
            print(g, report["guilds"][g]["selected"])
        return 0
    except Exception as e:                       # (Codex #71 r1 P3: every refusal is one normalized error)
        import sealing
        import store
        import zipfile
        known = (RefselError, OSError, ValueError, KeyError, TypeError, AttributeError, IndexError,
                 zipfile.BadZipFile, planlib.DesignError, store.StoreError, sealing.SealError)
        if not isinstance(e, known):
            raise
        what = "" if isinstance(e, RefselError) else f"{type(e).__name__}: "
        print(f"refsel.py {a.cmd}: {what}{e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

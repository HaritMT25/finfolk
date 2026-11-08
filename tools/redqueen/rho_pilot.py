#!/usr/bin/env python3
"""rho_pilot.py: the H-C allocation pilot (USER DECISIONS 2, items 5-6, of Annex H; Gemini q32 §3), as
redesigned after Codex's review of 8569fcc and Gemini q34 §5. The assay plan, the collection of its
results and the estimator of rho, with the allocation rule FIXED before any pilot assay is run (this
file's sha256 is recorded in statusB.log and the PR body).

THE PILOT WORLDS: the floor-free validation run, 8 C + 2 A + 2 B worlds to 100M (worlds.py), its
archived checkpoints every 10M.

PLAN (`plan`): a design/2 for plan.py, from the validation study's worlds block (worlds.py
design-block), in its own seed namespace (default rq2026-rho-pilot). Production H-C measures prey
against FIXED predator panels, so the pilot does too:
  * THE FIXED NEURAL PANEL, registered in the plan before any assay: the predator snapshots at 100M
    (the final pilot time) of the first five C worlds in the order of sha256("<namespace>|rho-panel|
    <world>") whose 100M snapshot is archived and valid (before the world's first zero). A prey world
    meets the first four of them that are not itself, so a panel world's own predators are replaced by
    the fifth. The same panel at every time; no swap, ever. Fewer than five valid: the plan is refused
    (the pilot is then unavailable: 64 worlds).
  * THE FIXED SCRIPTED BENCHMARK: K = 6 fresh scripted Stage A hunters (the engine's --predators-from
    scripted), the same benchmark for every prey snapshot.
  * THE PREDATOR-FREE control (descriptive; it is not part of the contrast).
Every pilot world (C, A and B) at every time t in 10, 20, ..., 100M whose prey snapshot is archived and
valid gets R = 12 replicates of the production assay: frozen, K 6, 600 common prey, the 5k horizon,
role "diagnostic", families rho-neural / rho-scripted / rho-free, and the production AGE REFERENCE
(mandatory). Snapshots that are not planned are recorded, with the reason: biological (at or after the
world's first zero) or technical (not archived).
INDEPENDENCE: every prey snapshot (w, t) has its own plan namespace "rho-<w>-<t>m". Every cell's
transplant draw (the donor sample and the placement) is therefore keyed by prey world x time x opponent
x replicate, and so is its common prey's sample and reseed. The conditions of one (w, t, r) share their
common prey (paired contrasts). Templates follow plan.py: replicate r uses templates[r mod n], a fixed
construction object, not a random draw.
SEEDS: every engine seed of the plan is checked against every --avoid input and refused on any
overlap. --avoid is mandatory and repeatable. Pass the production worlds registry (founder seeds and every
reserved restart seed) and the production plans when they exist; otherwise production's registration
passes this plan to its own --avoid.

COLLECT (`collect`): the pilot study's packed cells through store.py's index. load_index refuses a cell
in two chunks, and read_member checks every bundle against its indexed sha256. Collection is BOUND to
the FINAL executable plan (the rows run.py ran, every content hash filled): the plan must be exactly the
design's expansion but for those hashes (bind_plan); every bundle of the design must carry its plan row
EXACTLY (inputs, hashes, seeds) and the registered cohort of 600; every plan cell must be collected
unless declared missing, and the declaration must match exactly. The result is an observation document
(the design's canonical sha256, the plan file's sha256, the missing cells) with one observation per
cell: world, time, condition (neural:<world> | scripted | free), replicate, survivors at the 5000-step
horizon, cohort, cell id and seeds; `estimate` re-checks that binding and records it in its result.

ESTIMATOR (`estimate`; the registered definitions):
  VALIDATION against the plan: (world, time, condition, replicate) unique (a duplicate is refused,
    whatever its values); the snapshot planned; the condition one the plan registered for that prey
    world (its panel members, scripted, free); the replicate in 0..11; counts integral, cohort > 0,
    0 <= survivors <= cohort. Any violation refuses the whole estimate.
  CONTRAST per replicate: z_r = (1/4) sum over the panel, in its registered order, of S_N - S_S
    (S = survivors / cohort; math.fsum, so the arithmetic order is canonical). A replicate missing a
    panel or scripted cell drops THAT replicate only. A snapshot needs >= 2 complete replicates. Then
    y_{w,t} = mean_r z_r and v_{w,t} = Var_r(z_r) / n.
  INCREMENTS: D_{w,j} = 5 (y_{t_j} - y_{t_{j-1}}) per 50M, for consecutive available pilot times after
    the 0-10M burn-in (j = 1..9). Their assay covariance is 25 (v_j + v_{j-1}) on the diagonal and
    -25 v_j between increments sharing time t_j. A world ENTERS with >= 4 increments; a world extinct
    after 50M keeps its earlier increments (no complete-case dropping). The others are excluded and
    reported.
  MODEL: D_{w,j} = mu_T + eta_j + u_w + e_{w,j} + xi_{w,j}.
    - mu_T: the treatment means (fixed). eta_j: the epoch effects common to all worlds (fixed).
    - u_w ~ (0, s_u,G^2): the persistent velocity. e ~ (0, s_e,G^2): the transient epoch drift.
    - xi: the known assay noise.
    - The components are per GROUP G: C, and the pooled controls (A and B, each with its own mean).
    The fixed effects are removed by least squares (the residual projection P over the available
    cells, unbalanced). Per group, two Henderson-I sums of squares of the residuals: SSW_G (within
    world) and SSB_G (between worlds, within treatment). Their EXACT expectations, E[r'Ar] =
    sum_k theta_k tr(P A P V_k) + tr(P A P Sigma), give a 4 x 4 linear system in (s_u,C^2, s_e,C^2,
    s_u,ctrl^2, s_e,ctrl^2), solved and truncated at 0. The pooled estimate (one s_u^2, one s_e^2) is
    the 2 x 2 system of the summed sums of squares.
  PROJECTION per group: V_G = s_u,G^2 + gamma_OLS s_e,G^2 / 20 + Vassay_G.
    - gamma_OLS = 20 Var(the OLS slope per 50M over the 41 coarse times of 200M) / s_e^2 for a 10M-epoch
      random walk, computed exactly (about 1.17).
    - Vassay_G = the group's mean production snapshot variance (v n / 6, i.e. R = 6) / Sxx, Sxx over
      x = t / 50 on the coarse times.
  THE DECISION VARIANCE (the block-contrast equivalence): the 1-control block contrast has variance
    v1 = V_C / 4 + V_ctrl, equated to 1.25 rho^2 0.02^2 (the homoskedastic 4C+1A+1B rationale). With
    the conservative envelope against the controls' few degrees of freedom (Gemini q34):
    V_dec = max(V_pooled, (V_C / 4 + V_ctrl) / 1.25), and rho = sqrt(V_dec) / 0.02.
  BOOTSTRAP (the FITTED Gaussian model, parametric; #69 round 2): each of 20,000 draws (stream
    AnnexH/1/H-C/rho-pilot/bootstrap) simulates a whole pilot data set of the observed layout: per
    world u ~ N(0, s_u,G^2), per available increment the fitted fixed effects + u + e, e ~ N(0, s_e,G^2)
    (the latent snapshot means), per snapshot its n complete replicates N(mean, v n) (v n: the observed
    replicate variance), from which y, v are formed as from real replicates; the COMPLETE estimator
    (projection, sums of squares, assay terms from the re-estimated v, systems, truncation, envelope) is
    rerun on it. So the joint law of the quadratic forms and the uncertainty of the assay variances are
    both carried. (q75 of these draws is a registered conservative policy, not a calibrated bound.)
  THE DECISION STATISTIC: the registered field DECISION = "q75", the bootstrap 75th percentile of rho
    (the point estimate is median-biased low on few degrees of freedom). The point estimate, q75 and the
    90% interval (5th / 95th percentiles) are all reported.
  AVAILABILITY: >= 4 C worlds and >= 3 control worlds (>= 1 A and >= 1 B) entered, and a nonsingular
    system; otherwise unavailable -> 64.
THE ALLOCATION RULE (fixed now; never tuned):
  rho <= 0.85 -> 48 worlds, 8 x (4C+1A+1B);
  0.85 < rho <= 1.35 -> 56, 4 x (4C+2A+1B) + 4 x (4C+1A+2B);
  rho > 1.35 -> 64, 8 x (4C+2A+2B);
  unavailable -> 64.

    rho_pilot.py plan --block worlds_block.json --templates /abs/t1.json ... --age-reference /abs/ages.json \\
        --avoid PRODUCTION/config/worlds.json [--avoid PLAN.jsonl ...] --out design.json
    rho_pilot.py collect --study PILOT_STUDY --design design.json --plan FINAL_PLAN.jsonl \\
        [--declare-missing ids.txt] --out obs.json
    rho_pilot.py estimate obs.json --design design.json --plan FINAL_PLAN.jsonl [--out rho.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plan as planlib  # noqa: E402
import rqlib  # noqa: E402

SCHEMA = "finfolk.redqueen.rhopilot/2"
NAMESPACE = "rq2026-rho-pilot"
TIMES_M = tuple(range(10, 101, 10))
PANEL_TIME_M = 100
REPLICATES = 12
PANEL = 4
K = 6
N_PREY = 600
HORIZON = 5000
DELTA = 0.02
THRESHOLDS = (0.85, 1.35)
ALLOCATIONS = {48: "8 x (4C+1A+1B)", 56: "4 x (4C+2A+1B) + 4 x (4C+1A+2B)", 64: "8 x (4C+2A+2B)"}
DECISION = "q75"
PILOT_WORLDS = {"C": 8, "A": 2, "B": 2}
MIN_INCREMENTS = 4
MIN_C, MIN_CTRL = 4, 3
COARSE = [1e-6] + [5.0 * k for k in range(1, 41)]
BOOT = 20000
BOOT_STREAM = b"AnnexH/1/H-C/rho-pilot/bootstrap"


class PilotError(Exception):
    pass


def allocation(rho):
    """The FIXED allocation rule (None / non-finite: unavailable -> the conservative 64)."""
    if rho is None or not math.isfinite(rho):
        return 64
    if rho <= THRESHOLDS[0]:
        return 48
    if rho <= THRESHOLDS[1]:
        return 56
    return 64


# ================================================================== seeds
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
    """An --avoid input's seeds: a JSON document's nested seeds (a worlds registry: every founder and
    reserved restart seed), or a plan's (JSONL rows) seeds."""
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
def _valid(ws, w, t):
    v = ws[w]
    fr = t * 1_000_000
    return fr in v.get("archived", []) and (v.get("valid_before") is None or fr < v["valid_before"])


def fixed_panel(block, ns=NAMESPACE):
    """The registered neural panel: the first PANEL + 1 C worlds, in hash order, valid at 100M."""
    ws = block["worlds"]
    cw = sorted((w for w, v in ws.items() if v["treatment"] == "C"),
                key=lambda c: hashlib.sha256(f"{ns}|rho-panel|{c}".encode()).hexdigest())
    panel = [c for c in cw if _valid(ws, c, PANEL_TIME_M)][:PANEL + 1]
    if len(panel) < PANEL + 1:
        raise PilotError(f"only {len(panel)} C worlds have a valid {PANEL_TIME_M}M predator snapshot; the fixed "
                         f"panel needs {PANEL + 1} (the pilot is unavailable: 64)")
    return panel


def panel_of(panel, w):
    """A prey world's four panel members: the first four that are not itself."""
    return [c for c in panel if c != w][:PANEL]


def snapshot_namespace(w, t_m):
    return f"rho-{w}-{t_m}m"


def make_design(block, templates, ages, avoid_paths, ns=NAMESPACE):
    """worlds.py's worlds block -> (design/2 dict, notes)."""
    if block.get("schema") != "finfolk.redqueen.worldsblock/1":
        raise PilotError(f"worlds block schema {block.get('schema')!r}")
    if not isinstance(ages, str) or not os.path.isabs(ages) or not os.path.isfile(ages):
        raise PilotError("--age-reference: the production age reference (an absolute path to a file) is mandatory")
    if not avoid_paths:
        raise PilotError("--avoid: the production reservations (the worlds registry, production plans) are mandatory")
    ws = block["worlds"]
    have = {t: sum(1 for v in ws.values() if v["treatment"] == t) for t in PILOT_WORLDS}
    if have != PILOT_WORLDS or len(ws) != sum(PILOT_WORLDS.values()):
        raise PilotError(f"the pilot is 8 C + 2 A + 2 B worlds, not {have}")
    labels = {f"{t}M": t * 1_000_000 for t in TIMES_M}
    for lab, fr in labels.items():
        if block["times"].get(lab) != fr:
            raise PilotError(f"the validation schedule does not archive {lab} (frame {fr})")
    panel = fixed_panel(block, ns)
    worlds = {w: {"uuid": v["uuid"], "pattern": v["pattern"], "paths": v.get("paths", {})} for w, v in ws.items()}
    edges, skipped = [], []
    for w in sorted(ws):
        pw = panel_of(panel, w)
        for t in TIMES_M:
            lab = f"{t}M"
            if not _valid(ws, w, t):
                vb = ws[w].get("valid_before")
                why = (f"biological: at or after the world's first zero (frame {vb})"
                       if vb is not None and t * 1_000_000 >= vb else "technical: not archived")
                skipped.append({"world": w, "time": lab, "reason": why})
                continue
            base = {"role": "diagnostic", "horizon": "short", "prey": {"world": w, "time": lab},
                    "namespace": snapshot_namespace(w, t)}
            for c in pw:
                edges.append(dict(base, family="rho-neural", predators={"world": c, "time": f"{PANEL_TIME_M}M"}))
            edges.append(dict(base, family="rho-scripted", predators={"source": "scripted"}))
            edges.append(dict(base, family="rho-free", predators=None))
    for n, e in enumerate(edges, 1):
        e["edge"] = f"rho{n:05d}"
    design = {"schema": "finfolk.redqueen.design/2", "name": "rho-pilot", "seed_namespace": ns, "times": labels,
              "worlds": worlds, "templates": list(templates), "age_reference": ages, "replicates": REPLICATES,
              "defaults": {"assay": "frozen", "k": K, "prey_policy": "common", "n_prey": N_PREY,
                           "short_steps": HORIZON, "short_horizons": [HORIZON]},
              "long": {"fraction": 0.0}, "edges": edges}
    try:
        rows, _, _ = planlib.expand_v2(design, pending=True)
    except planlib.DesignError as e:
        raise PilotError(f"plan.py refuses the design: {e}")
    seeds = planlib.plan_seeds(rows)
    checked = []
    for p in avoid_paths:
        a = avoid_seeds(p)
        hit = sorted(seeds & a)
        if hit:
            raise PilotError(f"{len(hit)} pilot engine seed(s) are reserved in {p}: {hit[:5]}")
        checked.append({"path": os.path.abspath(p), "sha256": rqlib.sha256_file(p), "seeds": len(a)})
    design["rho_pilot"] = {
        "schema": SCHEMA, "registry_sha256": block.get("registry_sha256"), "namespace": ns, "panel": panel,
        "panel_time": f"{PANEL_TIME_M}M", "per_world_panel": {w: panel_of(panel, w) for w in sorted(ws)},
        "treatment": {w: v["treatment"] for w, v in sorted(ws.items())}, "skipped": skipped,
        "replicates": REPLICATES, "times_M": list(TIMES_M), "thresholds": list(THRESHOLDS), "decision": DECISION,
        "min_worlds": {"C": MIN_C, "controls": MIN_CTRL}, "min_increments": MIN_INCREMENTS,
        "avoid": checked, "engine_seeds": len(seeds), "cells": len(rows)}
    return design, {"skipped": skipped}


# ================================================================== collect
def _condition(row):
    if row["kind"] == "nopred":
        return "free"
    return "scripted" if row["predators"].get("source") == "scripted" else f"neural:{row['predators']['world']}"


HASHED = ("prey", "predators", "template", "ages")
OBS_SCHEMA = "finfolk.redqueen.rhopilot.obs/1"


def _unhashed(row):
    """A plan row without its content hashes (pending in the design's expansion, filled in the final plan)."""
    r = json.loads(json.dumps(row))
    for k in HASHED:
        if isinstance(r.get(k), dict):
            r[k].pop("sha256", None)
    return r


def bind_plan(design, plan_path):
    """The FINAL executable plan (plan.py's rows, every content hash filled: what run.py runs) bound to the
    design: exactly the design's cell ids, every row equal to the design's expansion but for the filled
    hashes (template, age reference, prey and donor files, cohort, sampling, seeds: everything), every
    hash filled, the registered cohort -> ({cell id: row}, the plan file's sha256)."""
    try:
        exp, _, _ = planlib.expand_v2(design, pending=True)
    except planlib.DesignError as e:
        raise PilotError(f"the design: {e}")
    want = {r["id"]: r for r in exp}
    got = {}
    for ln in rqlib.read_text(plan_path).split("\n"):
        if ln.strip():
            r = json.loads(ln)
            if r.get("id") in got:
                raise PilotError(f"plan {plan_path}: cell {r.get('id')} occurs twice")
            got[r.get("id")] = r
    if set(got) != set(want):
        raise PilotError(f"plan {plan_path}: {len(set(want) - set(got))} design cells missing, "
                         f"{len(set(got) - set(want))} cells the design does not have")
    for cid, r in got.items():
        if _unhashed(r) != _unhashed(want[cid]):
            raise PilotError(f"plan {plan_path}: cell {cid} differs from the design's expansion")
        for k in HASHED:
            x = r.get(k)
            if isinstance(x, dict) and x.get("path") and not (isinstance(x.get("sha256"), str)
                                                              and len(x["sha256"]) == 64):
                raise PilotError(f"plan {plan_path}: cell {cid} has no content hash for its {k} (a pending plan)")
        if r.get("n_prey") != N_PREY:
            raise PilotError(f"plan {plan_path}: cell {cid} has cohort {r.get('n_prey')}, not {N_PREY}")
    return got, rqlib.sha256_file(plan_path)


def _key(row):
    return {"world": row["prey"]["world"], "time": row["prey"]["time"], "condition": _condition(row),
            "replicate": row["replicate"]}


def collect(study, design, plan_path, declared_missing=()):
    """The pilot's packed cells through store.py's verified index, BOUND to the final plan (#69 round 2,
    P1-5): every bundle of the design must be a plan cell whose complete row it carries, with the
    registered cohort; every plan cell must be collected unless declared missing (the declaration must
    match exactly) -> the observation document (its provenance: the design's and the plan's hashes)."""
    import store
    rows, plan_sha = bind_plan(design, plan_path)
    _, cells = store.load_index(study)
    obs = []
    for cid in sorted(cells):
        b = json.loads(store.read_member(study, cid, cells=cells))
        c = b["cell"]
        if c.get("design") != design.get("name"):
            continue
        row = rows.get(cid)
        if row is None or c.get("id") != cid:
            raise PilotError(f"{cid}: a cell of design {design.get('name')!r} that the plan does not have")
        if rqlib.canonical(c) != rqlib.canonical(row):
            raise PilotError(f"{cid}: its bundle's cell row differs from the plan's (inputs, hashes or seeds)")
        if b["score"].get("n_start") != row["n_prey"]:
            raise PilotError(f"{cid}: cohort {b['score'].get('n_start')}, the plan registers {row['n_prey']}")
        h = [x for x in b["score"]["horizons"] if x["steps"] == HORIZON]
        if len(h) != 1:
            raise PilotError(f"{cid}: no single {HORIZON}-step horizon in its score")
        obs.append(dict(_key(row), survivors=h[0]["survivors"], cohort=b["score"]["n_start"], cell=cid,
                        seeds=row["seeds"]))
    missing = sorted(set(rows) - {o["cell"] for o in obs})
    if missing != sorted(set(declared_missing)):
        raise PilotError(f"{len(missing)} plan cells are not collected (e.g. {missing[:3]}); a missing cell must be "
                         f"declared (--declare-missing), exactly: declared {len(set(declared_missing))}")
    return {"schema": OBS_SCHEMA, "design_sha256": rqlib.canonical_sha(design), "plan_sha256": plan_sha,
            "plan_cells": len(rows), "collected": len(obs), "missing": missing, "observations": obs}


def bound_observations(doc, design, plan_path):
    """An observation document checked against the design and the final plan it was collected under
    -> (observations, provenance)."""
    if doc.get("schema") != OBS_SCHEMA:
        raise PilotError(f"observations schema {doc.get('schema')!r}")
    rows, plan_sha = bind_plan(design, plan_path)
    if doc.get("design_sha256") != rqlib.canonical_sha(design) or doc.get("plan_sha256") != plan_sha:
        raise PilotError("the observations were collected under another design or plan")
    obs = doc["observations"]
    ids = [o.get("cell") for o in obs]
    if len(set(ids)) != len(ids) or set(ids) | set(doc["missing"]) != set(rows) or set(ids) & set(doc["missing"]):
        raise PilotError("the observations do not cover the plan's cells exactly (with the declared missing ones)")
    for o in obs:
        row = rows[o["cell"]]
        if {k: o.get(k) for k in ("world", "time", "condition", "replicate")} != _key(row) \
                or o.get("seeds") != row["seeds"]:
            raise PilotError(f"{o['cell']}: the observation's key or seeds differ from its plan cell")
    return obs, {"design_sha256": doc["design_sha256"], "plan_sha256": plan_sha, "plan_cells": len(rows),
                 "collected": len(obs), "missing": doc["missing"]}


# ================================================================== the estimator: observations
def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def validate(obs, rp):
    """Observations checked against the plan's registration -> {(w, t label, condition, r): survival}."""
    pw = rp["per_world_panel"]
    times = [f"{t}M" for t in rp["times_M"]]
    skipped = {(s["world"], s["time"]) for s in rp.get("skipped", [])}
    seen = {}
    for o in obs:
        if not isinstance(o, dict):
            raise PilotError(f"observation {o!r} is not an object")
        key = (o.get("world"), o.get("time"), o.get("condition"), o.get("replicate"))
        w, t, cond, r = key
        if key in seen:
            raise PilotError(f"observation {key} occurs twice")
        if w not in pw:
            raise PilotError(f"{key}: {w!r} is not a pilot world")
        if t not in times or (w, t) in skipped:
            raise PilotError(f"{key}: the snapshot {w} {t} is not planned")
        if cond not in [f"neural:{c}" for c in pw[w]] + ["scripted", "free"]:
            raise PilotError(f"{key}: the condition is not one the plan registered for {w} (panel {pw[w]})")
        if not _is_int(r) or not 0 <= r < rp["replicates"]:
            raise PilotError(f"{key}: the replicate is not in 0..{rp['replicates'] - 1}")
        s, n = o.get("survivors"), o.get("cohort")
        if not (_is_int(s) and _is_int(n) and n == rp.get("n_prey", N_PREY) and 0 <= s <= n):
            raise PilotError(f"{key}: survivors {s!r} of cohort {n!r} (the registered cohort is "
                             f"{rp.get('n_prey', N_PREY)})")
        seen[key] = s / n
    return seen


def contrasts(obs, rp):
    """-> ({w: {time index: (y, v, n)}}, report)."""
    seen = validate(obs, rp)
    pw = rp["per_world_panel"]
    rep = {"dropped_replicates": [], "thin_snapshots": [], "missing_snapshots": [], "replicates_without_free": 0}
    skipped = {(s["world"], s["time"]) for s in rp.get("skipped", [])}
    by_snap = {}
    for (w, t, cond, r) in seen:
        by_snap.setdefault((w, t), set()).add(r)
    out = {}
    for w in sorted(pw):
        need = [f"neural:{c}" for c in pw[w]] + ["scripted"]
        for i, tm in enumerate(rp["times_M"]):
            t = f"{tm}M"
            if (w, t) in skipped:
                continue
            reps = sorted(by_snap.get((w, t), ()))
            if not reps:
                rep["missing_snapshots"].append({"world": w, "time": t})
                continue
            z = []
            for r in reps:
                vals = [seen.get((w, t, c, r)) for c in need]
                if any(v is None for v in vals):
                    rep["dropped_replicates"].append({"world": w, "time": t, "replicate": r})
                    continue
                rep["replicates_without_free"] += (w, t, "free", r) not in seen
                z.append(math.fsum(vals[:PANEL]) / PANEL - vals[PANEL])
            if len(z) < 2:
                rep["thin_snapshots"].append({"world": w, "time": t, "complete_replicates": len(z)})
                continue
            m = math.fsum(z) / len(z)
            v = math.fsum((x - m) ** 2 for x in z) / (len(z) - 1) / len(z)
            out.setdefault(w, {})[i] = (m, v, len(z))
    return out, rep


def increments(series):
    """{w: [(epoch j, D_wj)]} for consecutive available times after the first, and {w: Sigma_w}."""
    inc, sig = {}, {}
    for w, s in sorted(series.items()):
        lst = [(j, 5.0 * (s[j][0] - s[j - 1][0])) for j in sorted(s) if j >= 1 and j - 1 in s]
        if not lst:
            continue
        J = len(lst)
        S = [[0.0] * J for _ in range(J)]
        for a, (ja, _) in enumerate(lst):
            S[a][a] = 25.0 * (s[ja][1] + s[ja - 1][1])
            if a + 1 < J and lst[a + 1][0] == ja + 1:
                S[a][a + 1] = S[a + 1][a] = -25.0 * s[ja][1]
        inc[w], sig[w] = lst, S
    return inc, sig


# ================================================================== projection constants
def _ols_weights(xs):
    xb = sum(xs) / len(xs)
    sxx = sum((x - xb) ** 2 for x in xs)
    return [(x - xb) / sxx for x in xs], sxx


def gamma_ols():
    """20 Var(OLS slope per 50M over the 41 coarse times) / s_e^2 for a 10M-epoch random walk whose
    per-50M increments have variance s_e^2 (exact)."""
    c, _ = _ols_weights([t / 50.0 for t in COARSE])
    return 20.0 * sum(ci * ck * min(ti, tk) / 10.0 / 25.0 for ci, ti in zip(c, COARSE) for ck, tk in zip(c, COARSE))


def sxx_coarse():
    return _ols_weights([t / 50.0 for t in COARSE])[1]


# ================================================================== the estimator: moments
class Layout:
    """The entered cells (w, j, D) in canonical order, their worlds, groups and fixed-effect basis."""

    def __init__(self, inc, sig, treat):
        self.worlds = sorted(inc)
        self.treat = {w: treat[w] for w in self.worlds}
        self.idx, self.D, self.ep = {}, [], []
        for w in self.worlds:
            self.idx[w] = list(range(len(self.D), len(self.D) + len(inc[w])))
            for j, d in inc[w]:
                self.D.append(d)
                self.ep.append(j)
        self.sig = {w: sig[w] for w in self.worlds}
        self.n = len(self.D)
        self.groups = {"C": [w for w in self.worlds if self.treat[w] == "C"],
                       "K": [w for w in self.worlds if self.treat[w] != "C"]}
        cols = []
        for T in sorted(set(self.treat.values())):
            cols.append([1.0 if self.treat[w] == T else 0.0 for w in self.worlds for _ in self.idx[w]])
        for j in sorted(set(self.ep))[1:]:
            cols.append([1.0 if e == j else 0.0 for e in self.ep])
        self.Q = _orthonormal(cols)
        self.r = self.proj(self.D)

    def proj(self, x):
        out = list(x)
        for q in self.Q:
            d = math.fsum(a * b for a, b in zip(q, x))
            out = [a - d * b for a, b in zip(out, q)]
        return out

    def A(self, form, x):
        """The quadratic forms' matrices as operators: ("W", G) within-world centering, ("B", G)
        world means minus treatment means (cell-weighted), on group G's cells."""
        kind, g = form
        out = [0.0] * self.n
        ws = self.groups[g]
        if kind == "W":
            for w in ws:
                ids = self.idx[w]
                m = math.fsum(x[i] for i in ids) / len(ids)
                for i in ids:
                    out[i] = x[i] - m
            return out
        for T in sorted({self.treat[w] for w in ws}):
            wt = [w for w in ws if self.treat[w] == T]
            JT = sum(len(self.idx[w]) for w in wt)
            mT = math.fsum(x[i] for w in wt for i in self.idx[w]) / JT
            for w in wt:
                ids = self.idx[w]
                m = math.fsum(x[i] for i in ids) / len(ids)
                for i in ids:
                    out[i] = m - mT
        return out

    def V(self, basis, x):
        """The covariance bases as operators: ("u", G) world blocks of ones, ("e", G) the identity, on
        group G's cells; ("S", None) the known assay covariance."""
        kind, g = basis
        out = [0.0] * self.n
        for w in (self.worlds if kind == "S" else self.groups[g]):
            ids = self.idx[w]
            if kind == "u":
                s = math.fsum(x[i] for i in ids)
                for i in ids:
                    out[i] = s
            elif kind == "e":
                for i in ids:
                    out[i] = x[i]
            else:
                S = self.sig[w]
                for a, i in enumerate(ids):
                    out[i] = math.fsum(S[a][b] * x[k] for b, k in enumerate(ids))
        return out

    def trAV(self, form, basis):
        """tr(A V) in closed form (A and V block structured; the groups are disjoint)."""
        kind, g = form
        vk, h = basis
        ws = self.groups[g]
        if vk != "S" and h != g:
            return 0.0
        J = {w: len(self.idx[w]) for w in ws}
        one = {w: math.fsum(math.fsum(row) for row in self.sig[w]) for w in ws}       # 1'Sigma_w 1
        if kind == "W":
            if vk == "u":
                return 0.0
            if vk == "e":
                return float(sum(J[w] - 1 for w in ws))
            return math.fsum(math.fsum(self.sig[w][a][a] for a in range(J[w])) - one[w] / J[w] for w in ws)
        JT = {}
        for w in ws:
            JT[self.treat[w]] = JT.get(self.treat[w], 0) + J[w]
        if vk == "u":
            return math.fsum(J[w] - J[w] ** 2 / JT[self.treat[w]] for w in ws)
        if vk == "e":
            return float(len(ws) - len(JT))
        return math.fsum(one[w] / J[w] - one[w] / JT[self.treat[w]] for w in ws)

    def trA(self, form):
        kind, g = form
        ws = self.groups[g]
        if kind == "W":
            return float(sum(len(self.idx[w]) - 1 for w in ws))
        return float(len(ws) - len({self.treat[w] for w in ws}))

    def applied(self, op, arg):
        """(op Q, Q' op Q) for an operator (self.A or self.V) and its argument."""
        XQ = [op(arg, q) for q in self.Q]
        return XQ, [[_dot(p, x) for x in XQ] for p in self.Q]

    def coef(self, form, basis, A_, V_):
        """tr(P A P V) = tr(AV) - 2 tr(Q'AVQ) + tr((Q'AQ)(Q'VQ)), P = I - QQ' (A, V symmetric)."""
        (AQ, qaq), (VQ, qvq) = A_, V_
        m = len(self.Q)
        t2 = math.fsum(_dot(AQ[k], VQ[k]) for k in range(m))
        t3 = math.fsum(qaq[p][q] * qvq[q][p] for p in range(m) for q in range(m))
        return self.trAV(form, basis) - 2.0 * t2 + t3

    def df(self, form, A_):
        """tr(P A) = tr(A) - tr(Q'AQ)."""
        return self.trA(form) - math.fsum(A_[1][k][k] for k in range(len(self.Q)))

    def ss(self, form):
        return math.fsum(a * b for a, b in zip(self.r, self.A(form, self.r)))


def _dot(a, b):
    return math.fsum(x * y for x, y in zip(a, b))


def _orthonormal(cols):
    Q = []
    for c in cols:
        v = list(c)
        n0 = math.sqrt(math.fsum(x * x for x in v))
        if n0 == 0:
            continue
        for _ in range(2):                    # (re-orthogonalized: classical Gram-Schmidt, twice)
            for q in Q:
                d = math.fsum(a * b for a, b in zip(q, v))
                v = [a - d * b for a, b in zip(v, q)]
        nv = math.sqrt(math.fsum(x * x for x in v))
        if nv > 1e-9 * n0:
            Q.append([x / nv for x in v])
    return Q


def _solve(M, y):
    """Gaussian elimination with partial pivoting -> x, or None if (numerically) singular."""
    n = len(y)
    a = [list(M[i]) + [y[i]] for i in range(n)]
    scale = max(abs(x) for row in M for x in row) or 1.0
    for c in range(n):
        p = max(range(c, n), key=lambda i: abs(a[i][c]))
        if abs(a[p][c]) < 1e-12 * scale:
            return None
        a[c], a[p] = a[p], a[c]
        for i in range(c + 1, n):
            f = a[i][c] / a[c][c]
            for k in range(c, n + 1):
                a[i][k] -= f * a[c][k]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (a[i][n] - math.fsum(a[i][k] * x[k] for k in range(i + 1, n))) / a[i][i]
    return x


FORMS = [("W", "C"), ("B", "C"), ("W", "K"), ("B", "K")]
BASES = [("u", "C"), ("e", "C"), ("u", "K"), ("e", "K")]


def moments(lay):
    """-> {"K": 4 x 4, "c": 4, "q": 4 observed, "df": 4, "Kp": 2 x 2, "cp", "qp"}: the expectation system."""
    Kmat, c, q, df = [], [], [], []
    Vs = {b: lay.applied(lay.V, b) for b in BASES + [("S", None)]}
    for f in FORMS:
        A_ = lay.applied(lay.A, f)
        Kmat.append([lay.coef(f, b, A_, Vs[b]) for b in BASES])
        c.append(lay.coef(f, ("S", None), A_, Vs[("S", None)]))
        q.append(lay.ss(f))
        df.append(lay.df(f, A_))
    # the pooled system: SSW = SSW_C + SSW_K, SSB likewise; V_u = V_uC + V_uK, V_e likewise
    Kp = [[Kmat[a][u] + Kmat[a][u + 2] + Kmat[a + 2][u] + Kmat[a + 2][u + 2] for u in (0, 1)] for a in (0, 1)]
    return {"K": Kmat, "c": c, "q": q, "df": df, "Kp": Kp, "cp": [c[0] + c[2], c[1] + c[3]]}


def solve_components(m, q, c=None):
    """Sums of squares q and assay terms c (default: the observed ones) -> ((su2_C, se2_C), (su2_K, se2_K),
    (su2_P, se2_P)), truncated at 0; None if a system is singular."""
    c = m["c"] if c is None else c
    th = _solve(m["K"], [a - b for a, b in zip(q, c)])
    tp = _solve(m["Kp"], [q[0] + q[2] - c[0] - c[2], q[1] + q[3] - c[1] - c[3]])
    if th is None or tp is None:
        return None
    th = [max(0.0, x) for x in th]
    return (th[0], th[1]), (th[2], th[3]), (max(0.0, tp[0]), max(0.0, tp[1]))


def assay_coefficients(lay):
    """tr(P A_f P Sigma) is linear in the snapshot variances v: -> {form: {(world, snapshot j): kappa}} with
    c_f = sum kappa v (Sigma: 25 (v_j + v_{j-1}) on the diagonal, -25 v_j between consecutive increments).
    The entries of M = P A P on Sigma's pattern: A - Q(Q'A) - (AQ)Q' + Q (Q'AQ) Q'."""
    m = len(lay.Q)
    epoch = {}
    for w in lay.worlds:
        for i in lay.idx[w]:
            epoch[i] = lay.ep[i]
    out = {}
    for f in FORMS:
        AQ, qaq = lay.applied(lay.A, f)
        kind, g = f
        ws = set(lay.groups[g])
        JT = {}
        for w in ws:
            JT[lay.treat[w]] = JT.get(lay.treat[w], 0) + len(lay.idx[w])

        def M(a, b, w):
            if w in ws:
                Jw = len(lay.idx[w])
                base = ((1.0 if a == b else 0.0) - 1.0 / Jw) if kind == "W" else 1.0 / Jw - 1.0 / JT[lay.treat[w]]
            else:
                base = 0.0
            s = base - math.fsum(lay.Q[k][a] * AQ[k][b] + AQ[k][a] * lay.Q[k][b] for k in range(m))
            return s + math.fsum(lay.Q[k][a] * qaq[k][l] * lay.Q[l][b] for k in range(m) for l in range(m))
        kap = {}
        for w in lay.worlds:
            ids = lay.idx[w]
            for x, a in enumerate(ids):
                j = epoch[a]
                d = 25.0 * M(a, a, w)
                kap[(w, j)] = kap.get((w, j), 0.0) + d
                kap[(w, j - 1)] = kap.get((w, j - 1), 0.0) + d
                if x + 1 < len(ids) and epoch[ids[x + 1]] == j + 1:
                    kap[(w, j)] = kap.get((w, j), 0.0) - 50.0 * M(a, ids[x + 1], w)
        out[f] = kap
    return out


class Core:
    """The estimator for one LAYOUT (the entered worlds' available snapshots and increments): the fixed-
    effect basis, the expectation system and the assay coefficients are layout-fixed; evaluate() runs the
    complete estimator on any (y, v, n) series of that layout. The observed estimate and every parametric-
    bootstrap draw go through the same evaluate()."""

    def __init__(self, series, treat, entered):
        self.treat = treat
        self.snaps = {w: sorted(series[w]) for w in entered}
        inc, sig = increments({w: series[w] for w in entered})
        self.lay = Layout(inc, sig, treat)
        self.cells = [(w, j) for w in self.lay.worlds for j, _ in inc[w]]
        self.m = moments(self.lay)
        self.kappa = assay_coefficients(self.lay)
        self.fitted = [d - r for d, r in zip(self.lay.D, self.lay.r)]
        self.groups = {"C": [w for w in entered if treat[w] == "C"], "K": [w for w in entered if treat[w] != "C"]}
        self.g, self.sxx = gamma_ols(), sxx_coarse()

    def evaluate(self, s):
        """(y, v, n) series of this layout -> the estimate record, or None (a singular system)."""
        lay = self.lay
        D = [5.0 * (s[w][j][0] - s[w][j - 1][0]) for w, j in self.cells]
        r = lay.proj(D)
        q = [_dot(r, lay.A(f, r)) for f in FORMS]
        c = [math.fsum(k * s[w][j][1] for (w, j), k in self.kappa[f].items()) for f in FORMS]
        comp = solve_components(self.m, q, c)
        if comp is None:
            return None

        def vassay(ws):
            cells = [s[w][j] for w in ws for j in self.snaps[w]]
            return math.fsum(v * n / 6.0 for _, v, n in cells) / len(cells) / self.sxx
        va = {"C": vassay(self.groups["C"]), "K": vassay(self.groups["K"]),
              "P": vassay(self.groups["C"] + self.groups["K"])}
        (uc, ec), (uk, ek), (up, ep) = comp
        g = self.g
        VC, VK, VP = uc + g * ec / 20.0 + va["C"], uk + g * ek / 20.0 + va["K"], up + g * ep / 20.0 + va["P"]
        Vd = decision_variance(VC, VK, VP)
        return {"comp": comp, "q": q, "c": c, "va": va, "V": (VC, VK, VP), "V_dec": Vd, "rho": math.sqrt(Vd) / DELTA}

    def simulate(self, rng, est, s):
        """One data set from the FITTED Gaussian model (#69 round 2, P1-1), at the replicate level: per world
        a persistent velocity u ~ N(0, s_u,G^2), per available increment the fitted fixed effects + u +
        e ~ N(0, s_e,G^2) (the latent snapshot means, levels arbitrary), per snapshot its n complete
        replicates z ~ N(mean, sigma^2) with sigma^2 = v n (the observed replicate variance) -> (y, v, n)
        from them, exactly as contrasts() forms them (so the assay variances are re-estimated too)."""
        (uc, ec), (uk, ek), _ = est["comp"]
        fit = dict(zip(self.cells, self.fitted))
        out = {}
        for w in self.lay.worlds:
            su, se = (uc, ec) if self.treat[w] == "C" else (uk, ek)
            u = math.sqrt(su) * _normal(rng)
            lvl, sw = None, {}
            for j in self.snaps[w]:
                if lvl is None or (w, j) not in fit:
                    lvl = s[w][j][0]                        # (a run's first snapshot: any level)
                else:
                    lvl += (fit[(w, j)] + u + math.sqrt(se) * _normal(rng)) / 5.0
                _, v, n = s[w][j]
                sd = math.sqrt(v * n)
                z = [lvl + sd * _normal(rng) for _ in range(n)]
                mz = math.fsum(z) / n
                sw[j] = (mz, math.fsum((x - mz) ** 2 for x in z) / (n - 1) / n, n)
            out[w] = sw
        return out


def _normal(rng):
    u1 = 1.0 - rng.next64() / 2.0 ** 64
    u2 = rng.next64() / 2.0 ** 64
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2 * math.pi * u2)


def decision_variance(VC, Vk, Vp):
    """The block-contrast equivalence with the conservative envelope (Gemini q34)."""
    return max(Vp, (VC / 4.0 + Vk) / 1.25)


def _q(srt, u):
    return srt[min(len(srt), max(1, math.ceil(u * (len(srt) + 1)))) - 1]


def estimate(obs, design, boot=BOOT, provenance=None):
    """The registered estimate, interval, decision and allocation (provenance: the plan binding)."""
    rp = design["rho_pilot"]
    treat = rp["treatment"]
    series, rep = contrasts(obs, rp)
    inc, _ = increments(series)
    out = {"schema": SCHEMA, "decision_statistic": DECISION, "thresholds": list(THRESHOLDS),
           "allocations": {str(k): v for k, v in ALLOCATIONS.items()}, "gamma_ols": gamma_ols(),
           "sxx_coarse": sxx_coarse(), "report": rep, "skipped_snapshots": rp.get("skipped", []),
           "provenance": provenance,
           "post_burn_in_extinctions": [s for s in rp.get("skipped", []) if s["reason"].startswith("biological")]}
    entered = [w for w in sorted(inc) if len(inc[w]) >= MIN_INCREMENTS]
    out["excluded_worlds"] = {w: f"{len(inc.get(w, []))} increments (< {MIN_INCREMENTS})"
                              for w in sorted(treat) if w not in entered}
    C = [w for w in entered if treat[w] == "C"]
    ctrl = [w for w in entered if treat[w] in ("A", "B")]
    out["entered"] = {"C": C, "controls": ctrl}
    why, core, est = None, None, None
    if len(C) < MIN_C:
        why = f"{len(C)} C worlds entered (< {MIN_C})"
    elif len(ctrl) < MIN_CTRL or not any(treat[w] == "A" for w in ctrl) or not any(treat[w] == "B" for w in ctrl):
        why = f"{len(ctrl)} control worlds entered (needs >= {MIN_CTRL}, with >= 1 A and >= 1 B)"
    else:
        core = Core(series, treat, entered)
        est = core.evaluate(series)
        if est is None:
            why = "the moment system is singular"
    if why is not None:
        out.update(available=False, reason=why, rho_point=None, rho_q75=None, rho_decision=None,
                   allocation=allocation(None))
        return out
    # the PARAMETRIC BOOTSTRAP of the fitted Gaussian model: whole data sets simulated (replicates
    # included) and the complete estimator rerun on each (#69 round 2, P1-1)
    rng = rqlib.SplitMix64(int.from_bytes(hashlib.sha256(BOOT_STREAM).digest()[:8], "little"))
    rs = []
    for _ in range(boot):
        e = core.evaluate(core.simulate(rng, est, series))
        rs.append(e["rho"] if e is not None else math.inf)
    rs.sort()
    q75 = _q(rs, 0.75)
    rho = est["rho"]
    dec = q75 if DECISION == "q75" else rho
    m, comp = core.m, est["comp"]
    VC, VK, VP = est["V"]
    names = {"C": (comp[0], VC, C, m["df"][1], m["df"][0], est["va"]["C"]),
             "controls": (comp[1], VK, ctrl, m["df"][3], m["df"][2], est["va"]["K"])}
    out.update(
        available=True, rho_point=rho, rho_q75=q75, rho_decision=dec, allocation=allocation(dec),
        ci90=[_q(rs, 0.05), _q(rs, 0.95)],
        components={k: {"s_u2": c[0], "s_e2": c[1], "V": V, "assay_prod": va, "worlds": len(ws),
                        "df_between": db, "df_within": dw}
                    for k, (c, V, ws, db, dw, va) in names.items()},
        pooled={"s_u2": comp[2][0], "s_e2": comp[2][1], "V": VP, "assay_prod": est["va"]["P"]},
        decision_variance={"V_pooled": VP, "block_equivalent": (VC / 4.0 + VK) / 1.25, "V_dec": est["V_dec"],
                           "governs": "pooled" if VP >= (VC / 4.0 + VK) / 1.25 else "block contrast"},
        moments={"forms": ["SSW_C", "SSB_C", "SSW_ctrl", "SSB_ctrl"], "observed": est["q"], "df": m["df"],
                 "K": m["K"], "assay": est["c"]},
        bootstrap={"draws": boot, "stream": BOOT_STREAM.decode(), "method": "parametric: the fitted Gaussian model "
                   "simulated at the replicate level, the complete estimator rerun", "singular_draws": rs.count(math.inf)})
    return out


# ================================================================== CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan")
    s.add_argument("--block", required=True)
    s.add_argument("--templates", nargs="+", required=True)
    s.add_argument("--age-reference", required=True)
    s.add_argument("--avoid", action="append", required=True, help="the production worlds registry, production plans")
    s.add_argument("--namespace", default=NAMESPACE)
    s.add_argument("--out", required=True)
    s = sub.add_parser("collect")
    s.add_argument("--study", required=True)
    s.add_argument("--design", required=True)
    s.add_argument("--plan", required=True, help="the FINAL plan the pilot study ran (plan.py --against)")
    s.add_argument("--declare-missing", help="a file of cell ids (one per line) declared missing, exactly")
    s.add_argument("--out", required=True)
    s = sub.add_parser("estimate")
    s.add_argument("obs")
    s.add_argument("--design", required=True)
    s.add_argument("--plan", required=True)
    s.add_argument("--boot", type=int, default=BOOT, help=argparse.SUPPRESS)
    s.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":
            design, notes = make_design(rqlib.read_json(a.block), a.templates, a.age_reference, a.avoid, a.namespace)
            rqlib.write_json_durable(a.out, design)
            r = design["rho_pilot"]
            print(f"{len(design['edges'])} edges ({r['cells']} cells); panel {r['panel']}; skipped {len(notes['skipped'])}")
            for n in notes["skipped"]:
                print(f"  skipped {n['world']} {n['time']}: {n['reason']}")
            return 0
        design = rqlib.read_json(a.design)
        if a.cmd == "collect":
            miss = ([x.strip() for x in rqlib.read_text(a.declare_missing).split("\n") if x.strip()]
                    if a.declare_missing else [])
            doc = collect(a.study, design, a.plan, miss)
            rqlib.write_json_durable(a.out, doc)
            print(f"{doc['collected']} observations of {doc['plan_cells']} plan cells; missing {len(doc['missing'])}")
            return 0
        obs, prov = bound_observations(rqlib.read_json(a.obs), design, a.plan)
        res = estimate(obs, design, boot=a.boot, provenance=prov)
        if a.out:
            rqlib.write_json_durable(a.out, res)
        print(json.dumps(res, indent=1, sort_keys=True))
        return 0
    except PilotError as e:
        print(f"rho_pilot.py {a.cmd}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

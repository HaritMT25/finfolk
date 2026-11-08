#!/usr/bin/env python3
"""noisebank.py: the independent noise bank (design v4 §7.4; Annex H.3.1's bank covariance, H.9.2's noise
model, amendment D4's monotone s(mu)). The plan of its assays, their collection, and the estimator of the
noise components that feed the analysis covariance V, map.py's replicate-variance prior and calib.py's
generator noise block.

THE PLAN (design/2, registered here):
  worlds   the N_WORLDS = 8 C-treatment worlds of the VALIDATION run whose TIMES = 20, 40, 60, 80M
           snapshots are all archived and valid (before the world's first zero), in the order of
           sha256("<seed namespace>|noisebank|<world uuid>"), the first 8; each world's partner is the next
           one in that order (cyclically). The worlds block (worlds.py design-block or val_block.py) must
           be bound to the validation registry <validation dir>/config/worlds.json:
             - its sha256 is the block's registry_sha256;
             - its namespace is VALIDATION_NAMESPACE;
             - every block world is a registered identity of that namespace (uuid5(URL,
               "finfolk:redqueen:<namespace>:<id>"), or val_block's attempt uuid of it);
             - no validation identity occurs in the main-study registries (--main-registry, mandatory:
               disjoint histories, not only disjoint seeds);
  pairs    every prey snapshot (w, t) meets the predator snapshots of its own world at all four times
           (4 within-pilot pairs) and of its partner at all four times (4 cross-pilot pairs): 32 prey
           snapshots x 8 = 128 within-pilot + 128 cross-pilot pairs; every predator snapshot faces 8 prey
           snapshots: a CROSSED design (896 row-sharing and 896 donor-sharing cell pairs);
  controls one predator-free continuation per prey snapshot (32);
  assays   the production assay:
             - frozen, K 6, the common 600-prey cohort, the production templates and age reference;
             - 64 replicates, 20k steps scored at 5k, 10k and 20k;
             - the PRODUCTION SEED SHARING of plan.py (sample / reseed per prey snapshot x replicate: the row;
               transplant per predator snapshot x replicate: the donor);
             - its own seed namespace (rq2026-noisebank, plan namespace "noisebank");
             - 16,384 predator trajectories and 2,048 predator-free ones, 18,432 in all;
             - --avoid (the production reservations) and the age reference are mandatory, and every engine
               seed is checked against the reservations.
COLLECT: through store.py's verified index, bound to the final plan (rows exact, the 600 cohort, every cell
collected or declared missing), the three horizons per cell.

THE ESTIMATOR (per horizon; Annex H.9.2: an interval-censored Gaussian composite likelihood).
  Model. A count k of N (captures of B(T) = K (1 + floor(T dt / cooldown)), or survivors of 600) is
  floor(N sigma(z) + 1/2) of a latent z = a_c + sigma_c u, so z lies in [logit((k - 1/2)/N),
  logit((k + 1/2)/N)] (-inf at 0, +inf at N). Per cell c and channel there is a location a_c and a total
  latent SD sigma_c = s(mu_c). The standardized latent u has unit variance and is the sum of the sharing
  components (H.9.2):
    exposed C, S of cell (i, j), replicate r:  u = R_ir + D_jr + E_ijr   (prey row, predator donor, cell),
    free F of prey snapshot i, replicate r:     u = R_ir[F] + E_ir[F]     (its own control error).
  SigmaR (3 x 3: C, S, F), SigmaD (2 x 2) and SigmaE (2 x 2) are PSD, with the unit total variance
  rR + rD + rE = 1 per exposed channel (the marginal scale is s(mu)). The correlation of two latent
  observations sharing a registered source is then one of NINE identified quantities (the groups):
    R_CC, R_SS, R_CS   row-sharing pairs (same prey snapshot and replicate, different predators);
    D_CC, D_SS, D_CS   donor-sharing pairs (same predator snapshot and replicate, different prey);
    T_CS               capture with exposed survival of the same cell and replicate (SigmaR + SigmaD +
                       SigmaE, C-S);
    R_CF, R_SF         an exposed channel with its prey snapshot's free control, same replicate.
  The free row variance SigmaR[F, F] is NOT identified: with one control per row only R_FF + E_FF = 1 is.
  It is set by CONVENTION to its smallest feasible value v' A^+ v (A the C-S row block, v = (R_CF, R_SF))
  and reported as a convention, never as a recovered variance. The survival-difference covariance depends
  on the total free variance only.
  Composite likelihood: the marginal interval log-likelihoods of every observation plus, for every pair of
  observations sharing a registered source (the nine groups), the dependence contribution
  log P(both intervals; rho) - log P(first) - log P(second) of the bivariate normal (Genz's BVNU,
  20-point Gauss-Legendre). It is maximized in TWO STAGES (inference functions for margins):
    (1) per cell and channel, the marginal MLE (a_c, sigma_c), by Newton from the empirical-logit moments
        (STARTING VALUES ONLY);
    (2) the nine dependence parameters, by the pairwise dependence contributions at the stage-1 margins.
  THE RECTANGLE PROBABILITIES (Codex #72 r2 P1): log_rect, the conditional integral over the narrower
  interval of phi(x) P(l < Y < h | x) in LOG space (composite Gauss-Legendre with slope-bounded panels;
  every conditional probability by the tail-stable _log_iprob): no differencing of tail probabilities, no
  floor; contributions below log P = -700 are counted (deep_tail), never clipped.
  THE GRID (Codex #72 r2 P2): each group's contribution is computed EXACTLY at Z_INTERVALS + 1 = 241 nodes
  uniform in z = atanh(rho) over the evaluable domain |rho| <= RHO_MAX = 0.995, and interpolated by local
  cubics IN z (the log likelihood bends like 1 / (1 - rho) near the limits; a uniform rho grid did not hold
  the registered tolerances there). Registered tolerances, verified off-grid near both limits in the tests:
  one pair's interpolated contribution within GRID_LL_TOL = 1e-3 log units, a group maximizer within
  GRID_RHO_TOL = 1e-3.
  When the unconstrained group maxima are jointly FEASIBLE (all three components PSD, the unit totals
  non-negative, the free row convention <= 1), they are the fit (a feasible vector of coordinate-wise
  maxima maximizes their sum over the feasible set). Otherwise the composite likelihood is maximized over
  the feasible set in the nine GROUP VALUES: three linear matrix inequalities (the row block with the free
  convention [[rC, rCS, vC], [rCS, rS, vS], [vC, vS, 1]], the donor block, the cell block) and the evaluable
  box |rho| < RHO_MAX, a convex set; by a log-barrier interior-point method (every evaluation strictly
  inside: never a clamped value). The maximum is certified by MULTI_START = 5 registered strictly feasible
  starts: every start must converge and their optima agree within START_TOL = 1e-4, else the fit is
  refused. (_theta_map, the spherical-angle parametrization, remains as a feasibility construction only.)
  FIXED-REPLICATE BIAS (Codex #72 r2): two-stage (IFM) estimation is consistent as replicates grow; with
  R = 64 fixed each cell's estimated location and scale leave an incidental-parameter bias (in the Gaussian
  limit a variance factor 63/64). It is measured by simulation at the registered size (the PR) and NOT
  corrected (no correction is exact for this model).
  REFUSED (status "unavailable", with reasons; never a silent number): a group without pairs, a group whose
  curvature per pair at its maximum is below INFO_MIN (unidentified), no usable cells.
  Support. Each CHANNEL has its own saturation mask: a cell's channel is unusable when its mean fraction lies
  outside SATURATION = [0.02, 0.98], and a saturated survival never removes the cell's capture. Each channel's
  marginal must also be identified: converged, sigma >= SIGMA_MIN, a negative definite Hessian, and the
  observed information of log sigma at least MARG_INFO_MIN R = 0.4 R (an uncensored normal sample has 2 R;
  a cell whose counts barely leave one or two latent intervals has almost none). Every exclusion is counted.
  s(mu) (D4 rule 13; the bins are retired), per channel:
    - the isotonic regression of the cells' sigma^2 on x = logit(mu-hat) (mu-hat the cell's mean fraction),
      with TIED LOCATIONS POOLED first (weights summed, the weighted mean variance);
    - direction "increasing" / "decreasing" by the smaller weighted squared error ("decreasing" on an exact
      tie);
    - each PLATEAU of the isotonic fit (a maximal run of equal fitted values: the fit is unique, PAVA's
      merge order is not) gives ONE knot, at the weighted mean of its locations, with value sqrt(the
      plateau's variance);
    - s is linear in logit(mu) between knots and CONSTANT beyond the outermost knots: an extrapolation
      assumption beyond the bank's support, recorded with the support.
  This family does not contain the H.9.2 bins: plateaus become ramps between block centres. The curves are
  serialized for noisescale.py, the ONE evaluator shared with calib.py.
  map.py's prior nu0, per channel:
    - the excess: the dispersion of log sigma_c^2 around log s(mu_c)^2, beyond the mean sampling variance of
      log sigma-hat^2 (from each marginal fit's observed information);
    - the scaled-inverse-chi-square prior has Var log sigma^2 = trigamma(nu0 / 2), solved EXACTLY for nu0;
    - encoded explicitly: {"status": "estimated", "nu0"}, {"status": "full_pooling"} (no excess dispersion:
      the prior is s(mu)^2 alone) or {"status": "unavailable", "reason"} (fewer than 3 cells); never Infinity
      or NaN.
  Uncertainty (registered; the coordinator's ruling on Codex #72 r2): a WORLD-MULTIPLICITY WEIGHTED
  LIKELIHOOD.
    - The 8 worlds are resampled with replacement twice, independently: prey-role multiplicities m and
      predator-role multiplicities m'.
    - Each pair's weight is the product of m over the DISTINCT prey worlds of its sources and of m' over its
      DISTINCT predator worlds (a world counts once however many of its snapshots the pair involves); a free
      control follows its prey snapshot.
    - Each draw refits stage 2 with the weighted contributions (the stage-1 margins are per cell and
      unchanged), 999 draws, percentile intervals.
    - Failed draws (a group without weight, or a refused fit) are counted; the INTERVAL is "unavailable"
      (a status separate from the point estimate's) when they exceed BOOT_FAIL_MAX = 5%, otherwise it is
      reported with the failure rate, labelled approximate and conditional on identification.
    - This departs from H.7's materialized-record bootstrap: the bank's intervals are descriptive and
      outside the confirmatory family. No coverage study is registered.

THE PRODUCTION V BUILDER (cov_parts; Annex H.3.1): one block's bank covariance diag(d) + U U' (for
recurrence.Cov), from the bank's components and the bank's s(mu) curves (noisescale.evaluate, the
registered D4 scale; there is no binned default), EVALUATED AT THE MEANS PASSED IN (D4: the null-model
fitted means m0; the builder never chooses). It is the LINEARIZED (delta-method) covariance of the
replicate means, g(mu) = s(mu) mu (1 - mu): a first-order approximation of H.9.2's rounded logistic-normal
counts, not their exact native-scale covariance (checked against simulation at small s in the tests).

    noisebank.py plan --block val_block.json --validation-dir ~/finfolk/validation --arena ARENA_ID \\
        --main-registry ~/finfolk/study/config/worlds.json --templates t.json ... \\
        --age-reference ages.json --avoid production_plan.jsonl ... --out nb_design.json
    noisebank.py collect --study STUDY --design noisebank_design.json --plan plan.jsonl [--declare-missing ...]
    noisebank.py estimate --obs noisebank_obs.json --out bank.json [--boot 999]
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
import noisescale  # noqa: E402
import plan as planlib  # noqa: E402
import rqlib  # noqa: E402

SCHEMA = "finfolk.redqueen.noisebank/2"
OBS_SCHEMA = "finfolk.redqueen.noisebank.obs/1"
BANK_SCHEMA = "finfolk.redqueen.noisebank.bank/2"
WORLDS_SCHEMA = "finfolk.redqueen.worlds/1"
SEED_NAMESPACE = "rq2026-noisebank"
PLAN_NAMESPACE = "noisebank"
VALIDATION_NAMESPACE = "finfolk-rq-validation-pilot-2026-11"     # (the validation run's registry namespace)
TIMES = ("20M", "40M", "60M", "80M")
N_WORLDS = 8
TREATMENT = "C"
REPLICATES = 64
K = 6
N_PREY = 600
STEPS = 20000
HORIZONS = (5000, 10000, 20000)
DT, COOLDOWN = 0.016, 1.5          # (the engine step and the predator cooldown in seconds: the capture bound)
SATURATION = (0.02, 0.98)          # (a channel's mean fraction outside: that channel of the cell is unusable)
SIGMA_MIN = 0.01                   # (a marginal latent SD below this: degenerate, unidentified)
MARG_INFO_MIN = 0.4                # (the observed information of log sigma below this x R: unidentified;
                                   #  an uncensored normal sample has 2 R)
INFO_MIN = 1e-3                    # (a dependence group's curvature per pair below this: unidentified)
RHO_MAX = 0.995                    # (the evaluable correlation domain)
Z_MAX = math.atanh(RHO_MAX)
Z_INTERVALS = 240                  # (the registered dependence grid: 241 nodes uniform in z = atanh(rho))
GRID_LL_TOL = 1e-3                 # (registered: |interpolation error| of one pair's contribution, log units)
GRID_RHO_TOL = 1e-3                # (registered: the interpolated group maximizer's error in rho)
TRUNC = 40.0                       # (log_rect: an infinite outer end truncated this far beyond the bulk)
PANEL_EFOLDS = 2.0                 # (log_rect: e-folds of the log integrand per Gauss-Legendre panel)
MAX_PANELS = 4096
LOG_RECT_TOL = 1e-6                # (log_rect's verified log-probability error against a 16x refinement)
MULTI_START = 5                    # (the constrained fit's registered starts)
START_TOL = 1e-4                   # (their optima must agree within this, log-likelihood units)
BOOT_FAIL_MAX = 0.05               # (the interval is unavailable beyond this share of failed draws)
MARGINAL_TOL = 1e-8                # (the marginal Newton's gradient tolerance, per replicate)
FEAS_TOL = 1e-12                   # (the feasibility tolerance of the unconstrained group maxima)
BOOT = 999
GROUPS = ("R_CC", "R_SS", "R_CS", "D_CC", "D_SS", "D_CS", "T_CS", "R_CF", "R_SF")
KINDS = ("C", "RC", "Q", "RQ")


class NoiseBankError(Exception):
    pass


def capture_bound(steps):
    """B(T) = K (1 + floor(T dt / cooldown)): 324 at 5k (recovery.py's B_COUNT), 642 at 10k, 1284 at 20k."""
    return K * (1 + int(math.floor(steps * DT / COOLDOWN + 1e-9)))


def frame_of(label):
    return int(label[:-1]) * 1_000_000


def registry_uuid(namespace, wid):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:redqueen:{namespace}:{wid}"))


def attempt_uuid(base, k):
    """val_block.py's identity of a restarted attempt k > 0 (another history)."""
    return base if not k else str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:attempt:{base}:{k}"))


# ================================================================== the plan
def pick_worlds(block, ns=SEED_NAMESPACE, n=N_WORLDS):
    """The registered worlds and partners (see the module docstring)."""
    if block.get("schema") != "finfolk.redqueen.worldsblock/1":
        raise NoiseBankError(f"worlds block schema {block.get('schema')!r}")
    ws = block["worlds"]
    ok = []
    for w, v in ws.items():
        if v.get("treatment") != TREATMENT:
            continue
        good = True
        for lab in TIMES:
            fr = frame_of(lab)
            if block["times"].get(lab) != fr or fr not in v.get("archived", []) or \
                    (v.get("valid_before") is not None and fr >= v["valid_before"]):
                good = False
        if good:
            ok.append(w)
    if len(ok) < n:
        raise NoiseBankError(f"{len(ok)} eligible {TREATMENT} worlds (all of {list(TIMES)} archived and valid); "
                             f"{n} are registered")
    order = sorted(ok, key=lambda w: hashlib.sha256(f"{ns}|noisebank|{ws[w]['uuid']}".encode()).hexdigest())[:n]
    return order, {w: order[(k + 1) % n] for k, w in enumerate(order)}


def _registry(path, what):
    try:
        reg = rqlib.read_json(path)
    except (OSError, ValueError) as e:
        raise NoiseBankError(f"{what} {path}: unreadable ({type(e).__name__})")
    if not isinstance(reg, dict) or reg.get("schema") != WORLDS_SCHEMA or not isinstance(reg.get("worlds"), list):
        raise NoiseBankError(f"{what} {path}: not a worlds registry ({WORLDS_SCHEMA})")
    return reg


def bind_validation(block, validation_dir, main_registries):
    """The worlds block bound to the VALIDATION registry and disjoint from the main study (Codex #72 r1 P2-8)
    -> the binding record (registry path, sha256, namespace; the main registries checked)."""
    vdir = os.path.abspath(validation_dir)
    rp = os.path.join(vdir, "config", "worlds.json")
    if not os.path.isfile(rp):
        raise NoiseBankError(f"no validation registry at {rp}")
    reg = _registry(rp, "validation registry")
    sha = rqlib.sha256_file(rp)
    if block.get("registry_sha256") != sha:
        raise NoiseBankError(f"the worlds block was not made from the validation registry {rp} (registry_sha256 "
                             "differs)")
    if block.get("root") is not None and os.path.abspath(block["root"]) != vdir:
        raise NoiseBankError(f"the worlds block was read from {block['root']!r}, not {vdir!r}")
    if reg.get("namespace") != VALIDATION_NAMESPACE:
        raise NoiseBankError(f"registry namespace {reg.get('namespace')!r}: the noise bank samples the validation "
                             f"run ({VALIDATION_NAMESPACE})")
    by = {w["id"]: w for w in reg["worlds"]}
    for wid, v in block["worlds"].items():
        r = by.get(wid)
        if r is None:
            raise NoiseBankError(f"block world {wid} is not in the validation registry")
        if r.get("uuid") != registry_uuid(reg["namespace"], wid):
            raise NoiseBankError(f"{wid}: its registry uuid is not the validation namespace's identity")
        if v.get("uuid") not in (r["uuid"], attempt_uuid(r["uuid"], v.get("attempt") or 0)):
            raise NoiseBankError(f"{wid}: the block's uuid is neither the registered identity nor its attempt")
        if v.get("treatment") != r.get("treatment"):
            raise NoiseBankError(f"{wid}: treatment {v.get('treatment')!r} in the block, {r.get('treatment')!r} "
                                 "registered")
    if not main_registries:
        raise NoiseBankError("--main-registry: the main study's registries are mandatory (disjoint histories)")
    val_ids = {w["uuid"] for w in reg["worlds"]} | {v.get("uuid") for v in block["worlds"].values()}
    mains = []
    for p in main_registries:
        m = _registry(p, "main registry")
        if m.get("namespace") == reg["namespace"]:
            raise NoiseBankError(f"main registry {p}: the validation namespace itself")
        hit = sorted(val_ids & {w.get("uuid") for w in m["worlds"]})
        if hit:
            raise NoiseBankError(f"main registry {p}: {len(hit)} validation identities are main-study worlds")
        mains.append({"path": os.path.abspath(p), "sha256": rqlib.sha256_file(p), "namespace": m.get("namespace")})
    return {"registry": rp, "registry_sha256": sha, "namespace": reg["namespace"], "main_registries": mains}


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


def make_design(block, templates, ages, avoid_paths, ns=SEED_NAMESPACE, validation_dir=None, arena=None,
                main_registries=()):
    """The noise bank's design/2 (registered: see the module docstring), bound to the validation registry it
    samples and disjoint from the main study, with its arena id recorded (the arena may still change)."""
    if not validation_dir or not arena:
        raise NoiseBankError("--validation-dir and --arena are mandatory (the bank samples one validation run of one arena)")
    binding = bind_validation(block, validation_dir, main_registries)
    if not isinstance(ages, str) or not os.path.isabs(ages) or not os.path.isfile(ages):
        raise NoiseBankError("--age-reference: the production age reference (an absolute path to a file) is mandatory")
    if not avoid_paths:
        raise NoiseBankError("--avoid: the production reservations are mandatory")
    order, partner = pick_worlds(block, ns)
    ws = block["worlds"]
    worlds = {w: {"uuid": ws[w]["uuid"], "pattern": ws[w]["pattern"], "paths": ws[w].get("paths", {})} for w in order}
    edges = []
    for w in order:
        for tq in TIMES:
            base = {"role": "diagnostic", "horizon": "long", "namespace": PLAN_NAMESPACE, "prey": {"world": w, "time": tq}}
            for fam, wp in (("nb-within", w), ("nb-cross", partner[w])):
                for tp in TIMES:
                    edges.append(dict(base, family=fam, predators={"world": wp, "time": tp}))
            edges.append(dict(base, family="nb-free", predators=None))
    for k, e in enumerate(edges, 1):
        e["edge"] = f"nb{k:05d}"
    design = {"schema": "finfolk.redqueen.design/2", "name": "noisebank", "seed_namespace": ns,
              "times": {lab: frame_of(lab) for lab in TIMES}, "worlds": worlds, "templates": list(templates),
              "age_reference": ages, "replicates": REPLICATES,
              "defaults": {"assay": "frozen", "k": K, "prey_policy": "common", "n_prey": N_PREY,
                           "long_steps": STEPS, "long_horizons": list(HORIZONS)},
              "long": {"fraction": 0.0}, "edges": edges}
    try:
        rows, _, _ = planlib.expand_v2(design, pending=True)
    except planlib.DesignError as e:
        raise NoiseBankError(f"plan.py refuses the design: {e}")
    seeds = planlib.plan_seeds(rows)
    checked = []
    for p in avoid_paths:
        hit = sorted(seeds & avoid_seeds(p))
        if hit:
            raise NoiseBankError(f"{len(hit)} noise-bank engine seed(s) are reserved in {p}: {hit[:5]}")
        checked.append({"path": os.path.abspath(p), "sha256": rqlib.sha256_file(p)})
    n_pred = sum(1 for r in rows if r.get("predators") is not None)
    design["noisebank"] = {"schema": SCHEMA, "validation_dir": os.path.abspath(validation_dir), "arena": str(arena),
                           "validation": binding, "worlds": order, "partner": partner, "times": list(TIMES),
                           "registry_sha256": binding["registry_sha256"], "avoid": checked, "cells": len(rows),
                           "predator_trajectories": n_pred, "free_trajectories": len(rows) - n_pred,
                           "horizons": list(HORIZONS), "capture_bounds": {str(h): capture_bound(h) for h in HORIZONS}}
    return design


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
                raise NoiseBankError(f"plan {plan_path}: cell {r.get('id')} occurs twice")
            got[r.get("id")] = r
    if set(got) != set(want):
        raise NoiseBankError(f"plan {plan_path}: not the design's cells ({len(set(want) ^ set(got))} differ)")
    for cid, r in got.items():
        if _unhashed(r) != _unhashed(want[cid]):
            raise NoiseBankError(f"plan {plan_path}: cell {cid} differs from the design's expansion")
        for k in HASHED:
            x = r.get(k)
            if isinstance(x, dict) and x.get("path") and not (isinstance(x.get("sha256"), str) and len(x["sha256"]) == 64):
                raise NoiseBankError(f"plan {plan_path}: cell {cid} has no content hash for its {k} (a pending plan)")
    return got, rqlib.sha256_file(plan_path)


def collect(study, design, plan_path, declared_missing=()):
    """The bank's observations, bound to the final plan: per cell the prey and predator snapshots, the
    replicate and, per horizon, the captures and survivors of the 600 cohort."""
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
        if row is None or rqlib.canonical(c) != rqlib.canonical(row):
            raise NoiseBankError(f"{cid}: not exactly a cell of the final plan")
        if b["score"].get("n_start") != N_PREY:
            raise NoiseBankError(f"{cid}: cohort {b['score'].get('n_start')}, not {N_PREY}")
        hz = {}
        for h in HORIZONS:
            x = [y for y in b["score"]["horizons"] if y["steps"] == h]
            if len(x) != 1:
                raise NoiseBankError(f"{cid}: no single {h}-step horizon")
            hz[str(h)] = {"captures": x[0].get("captures"), "survivors": x[0]["survivors"]}
        p = row["predators"]
        obs.append({"cell": cid, "prey": [row["prey"]["world"], row["prey"]["time"]],
                    "pred": None if p is None else [p["world"], p["time"]], "replicate": row["replicate"],
                    "horizons": hz})
    missing = sorted(set(rows) - {o["cell"] for o in obs})
    if missing != sorted(set(declared_missing)):
        raise NoiseBankError(f"{len(missing)} plan cells are not collected; a missing cell must be declared exactly")
    return {"schema": OBS_SCHEMA, "design_sha256": rqlib.canonical_sha(design), "plan_sha256": plan_sha,
            "missing": missing, "observations": obs}


# ================================================================== numerics: normal tails, BVN
def _erfc(x):
    """erfc, vectorized, finite or +-inf: the alternating Taylor series of erf below |x| = 2, the continued
    fraction of erfc above (relative error <= 1e-12)."""
    import numpy as np
    x = np.asarray(x, float)
    out = np.empty_like(x)
    fin = np.isfinite(x)
    out[~fin] = np.where(x[~fin] > 0, 0.0, 2.0)
    ax = np.abs(x)
    sm = fin & (ax < 2.0)
    xs = x[sm]
    x2 = xs * xs
    term, s = xs.copy(), xs.copy()
    for n in range(1, 70):
        term = term * (-x2) / n
        s = s + term / (2 * n + 1)
    out[sm] = 1.0 - 2.0 / math.sqrt(math.pi) * s
    lg = fin & ~sm
    xl = ax[lg]
    f = xl.copy()
    for n in range(90, 0, -1):
        f = xl + (n / 2.0) / f
    val = np.exp(-xl * xl) / math.sqrt(math.pi) / f
    out[lg] = np.where(x[lg] > 0, val, 2.0 - val)
    return out


def _Q(z):
    """The upper normal tail P(Z > z)."""
    import numpy as np
    return 0.5 * _erfc(np.asarray(z, float) / math.sqrt(2.0))


def _phi(z):
    import numpy as np
    z = np.asarray(z, float)
    with np.errstate(over="ignore"):
        return np.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)


def _iprob(zl, zh):
    """P(zl < Z < zh), accurate in either tail."""
    import numpy as np
    return np.where(zl > 0, _Q(zl) - _Q(zh), _Q(-zh) - _Q(-zl))


_GL = []


def _gl20():
    if not _GL:
        import numpy as np
        _GL.append(np.polynomial.legendre.leggauss(20))
    return _GL[0]


def _bvnu_finite(h, k, r):
    """P(X > h, Y > k) of a standard bivariate normal with correlation r (scalar, |r| < 1), finite h, k
    (arrays): Genz's BVNU (Drezner-Wesolowsky with 20-point Gauss-Legendre; the asymptotic form for |r| >=
    0.925); absolute error about 1e-15."""
    import numpy as np
    x, w = _gl20()
    h, k = np.asarray(h, float), np.asarray(k, float)
    hk = h * k
    if abs(r) < 0.925:
        hs = (h * h + k * k) / 2
        asr = math.asin(r)
        acc = np.zeros_like(h)
        for t, wt in zip(x, w):
            sn = math.sin(asr * (1 + t) / 2)
            acc += wt * np.exp((sn * hk - hs) / (1 - sn * sn))
        return np.clip(acc * asr / (4 * math.pi) + _Q(h) * _Q(k), 0.0, 1.0)
    if r < 0:
        k = -k
        hk = -hk
    as_ = (1 - r) * (1 + r)
    a = math.sqrt(as_)
    bs = (h - k) ** 2
    c = (4 - hk) / 8
    d = (12 - hk) / 16
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        asr = -(bs / as_ + hk) / 2
        bvn = np.where(asr > -100, a * np.exp(asr) * (1 - c * (bs - as_) * (1 - d * bs / 5) / 3 + c * d * as_ * as_ / 5),
                       0.0)
        b = np.sqrt(bs)
        sp = math.sqrt(2 * math.pi) * _Q(b / a)
        bvn = bvn - np.where(hk > -100, np.exp(-hk / 2) * sp * b * (1 - c * bs * (1 - d * bs / 5) / 3), 0.0)
        a2 = a / 2
        for t, wt in zip(x, w):
            xs = (a2 * (t + 1)) ** 2
            rs = math.sqrt(1 - xs)
            asr = -(bs / xs + hk) / 2
            sp = 1 + c * xs * (1 + d * xs)
            ep = np.exp(-hk * (1 - rs) / (2 * (1 + rs))) / rs
            bvn = bvn + np.where(asr > -100, a2 * wt * np.exp(asr) * (ep - sp), 0.0)
        bvn = -bvn / (2 * math.pi)
    if r > 0:
        bvn = bvn + _Q(np.maximum(h, k))
    else:
        L = np.where(h < 0, _Q(-k) - _Q(-h), _Q(h) - _Q(k))
        bvn = np.where(h >= k, -bvn, L - bvn)
    return np.clip(bvn, 0.0, 1.0)


def bvn_upper(h, k, r):
    """P(X > h, Y > k), any h, k in [-inf, +inf] (arrays), |r| < 1."""
    import numpy as np
    h, k = np.broadcast_arrays(np.asarray(h, float), np.asarray(k, float))
    out = np.zeros(h.shape)
    fh, fk = np.isfinite(h), np.isfinite(k)
    both = fh & fk
    if both.any():
        out[both] = _bvnu_finite(h[both], k[both], r)
    hm, km = h == -np.inf, k == -np.inf
    out[hm & km] = 1.0
    sel = hm & fk
    out[sel] = _Q(k[sel])
    sel = km & fh
    out[sel] = _Q(h[sel])
    return out                                   # (+inf anywhere: 0)


def bvn_rect(l1, h1, l2, h2, r):
    """P(l1 < X < h1, l2 < Y < h2) by differencing upper tails: accurate in ABSOLUTE terms only (a check of
    log_rect for moderate rectangles; never the likelihood)."""
    return (bvn_upper(l1, l2, r) - bvn_upper(h1, l2, r) - bvn_upper(l1, h2, r) + bvn_upper(h1, h2, r))

# ---- tail-stable log probabilities (Codex #72 r2 P1: no subtraction of tails, no floor)
def _logQ(z):
    """log P(Z > z), vectorized over finite / infinite z, accurate in the far upper tail (the continued
    fraction of erfc in log form: no underflow)."""
    import numpy as np
    z = np.asarray(z, float)
    out = np.empty_like(z)
    out[z == np.inf] = -np.inf
    out[z == -np.inf] = 0.0
    fin = np.isfinite(z)
    sm = fin & (z < 5.0)
    out[sm] = np.log(_Q(z[sm]))
    big = fin & (z >= 5.0)
    xl = z[big] / math.sqrt(2.0)
    f = xl.copy()
    for n in range(90, 0, -1):
        f = xl + (n / 2.0) / f
    out[big] = math.log(0.5) - xl * xl - 0.5 * math.log(math.pi) - np.log(f)
    return out


def _log_iprob(a, b):
    """log P(a < Z < b) (a < b), stable in either tail: the difference of the two tails taken on the side
    of the smaller tail in log form (log1p(-exp(.))); -inf only for an empty interval."""
    import numpy as np
    a, b = np.broadcast_arrays(np.asarray(a, float), np.asarray(b, float))
    out = np.full(a.shape, -np.inf)
    ok = b > a
    up = ok & (a > 0)
    dn = ok & (b < 0) & ~up
    mid = ok & ~up & ~dn
    with np.errstate(divide="ignore", invalid="ignore"):
        if up.any():
            la, lb = _logQ(a[up]), _logQ(b[up])
            out[up] = la + np.log1p(-np.exp(lb - la))
        if dn.any():
            lb, la = _logQ(-b[dn]), _logQ(-a[dn])
            out[dn] = lb + np.log1p(-np.exp(la - lb))
        if mid.any():
            out[mid] = np.log1p(-(_Q(b[mid]) + _Q(-a[mid])))
    return out


def _logphi(x):
    return -0.5 * x * x - 0.5 * math.log(2 * math.pi)


def log_rect(l1, h1, l2, h2, r, chunk=20000):
    """log P(l1 < X < h1, l2 < Y < h2) for the standard bivariate normal with correlation r (|r| < 1),
    WITHOUT differencing tail probabilities (Codex #72 r2 P1). The registered evaluation: the conditional
    integral over the outer variable (the narrower interval) of phi(x) P(l < Y < h | x), each conditional
    probability by _log_iprob, by composite 20-point Gauss-Legendre in log space (log-sum-exp). An infinite
    outer end is truncated TRUNC = 40 beyond the bulk. The panel count is the power of two >= (width x the
    log-integrand slope bound) / PANEL_EFOLDS (at most MAX_PANELS), so each panel spans a bounded number of
    e-folds; the log-probability error is verified in the tests (|error| <= LOG_RECT_TOL against a 16x
    refinement, and against the thin-rectangle density limit)."""
    import numpy as np
    l1, h1, l2, h2 = (np.asarray(v, float).ravel() for v in (l1, h1, l2, h2))
    w1, w2 = h1 - l1, h2 - l2
    swap = w2 < w1
    lo, hi = np.where(swap, l2, l1), np.where(swap, h2, h1)
    il, ih = np.where(swap, l1, l2), np.where(swap, h1, h2)
    lo = np.where(np.isfinite(lo), lo, np.minimum(hi, 0.0) - TRUNC)
    hi = np.where(np.isfinite(hi), hi, np.maximum(lo, 0.0) + TRUNC)
    s = math.sqrt((1.0 - r) * (1.0 + r))
    slope = np.zeros(len(lo))
    for x in (lo, hi):
        za, zb = (il - r * x) / s, (ih - r * x) / s
        m = np.maximum(np.where(np.isfinite(za), np.abs(za), 0.0), np.where(np.isfinite(zb), np.abs(zb), 0.0))
        slope = np.maximum(slope, np.abs(x) + abs(r) / s * np.maximum(m, 1.0))
    need = np.maximum(1.0, (hi - lo) * slope / PANEL_EFOLDS)
    panels = np.minimum(2 ** np.ceil(np.log2(need)).astype(int), MAX_PANELS)
    t, w = _gl20()
    out = np.empty(len(lo))
    for n in np.unique(panels):
        sel = np.flatnonzero(panels == n)
        u = ((np.arange(n)[:, None] + (t[None, :] + 1) / 2) / n).ravel()          # (n x 20 nodes on [0, 1])
        lw = np.log(np.tile(w, n) / (2 * n))
        for c0 in range(0, len(sel), max(1, chunk // len(u))):
            k = sel[c0:c0 + max(1, chunk // len(u))]
            span = (hi[k] - lo[k])[:, None]
            x = lo[k][:, None] + span * u[None, :]
            li = _log_iprob((il[k][:, None] - r * x) / s, (ih[k][:, None] - r * x) / s)
            v = lw[None, :] + np.log(span) + _logphi(x) + li
            mx = np.max(v, axis=1)
            out[k] = mx + np.log(np.sum(np.exp(v - mx[:, None]), axis=1))
    return out



# ================================================================== stage 1: the marginals
def interval_bounds(k, N):
    """The latent interval of count k of N: [logit((k - 1/2)/N), logit((k + 1/2)/N)], -inf at 0, +inf at N."""
    import numpy as np
    k = np.asarray(k, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        lo = np.where(k <= 0, -np.inf, np.log((k - 0.5) / (N - k + 0.5)))
        hi = np.where(k >= N, np.inf, np.log((k + 0.5) / (N - k - 0.5)))
    return lo, hi


def _marg_ll(lo, hi, a, t):
    """Per row: the interval log-likelihood and its gradient in (a, t = log sigma)."""
    import numpy as np
    s = np.exp(t)[:, None]
    zl, zh = (lo - a[:, None]) / s, (hi - a[:, None]) / s
    P = _iprob(zl, zh)
    with np.errstate(divide="ignore", invalid="ignore"):
        ll = np.sum(np.log(P), axis=1)
        pl, ph = _phi(zl), _phi(zh)
        zpl = np.where(np.isfinite(zl), zl * pl, 0.0)
        zph = np.where(np.isfinite(zh), zh * ph, 0.0)
        ga = np.sum((pl - ph) / (s * P), axis=1)
        gt = np.sum((zpl - zph) / P, axis=1)
    return ll, np.stack([ga, gt], axis=1)


def _marg_hess(lo, hi, a, t, eps=1e-5):
    """The symmetrized finite-difference Hessian of the analytic gradient (rows x 2 x 2)."""
    import numpy as np
    H = np.empty((len(a), 2, 2))
    for j, (da, dt) in enumerate(((eps, 0.0), (0.0, eps))):
        gp = _marg_ll(lo, hi, a + da, t + dt)[1]
        gm = _marg_ll(lo, hi, a - da, t - dt)[1]
        H[:, :, j] = (gp - gm) / (2 * eps)
    return 0.5 * (H + np.transpose(H, (0, 2, 1)))


def fit_marginals(K, N, max_iter=200):
    """Stage 1: per row of K (rows x R counts of N) the interval-censored normal MLE (a, sigma): Newton
    (finite-difference Hessian of the analytic gradient, step halving) from the EMPIRICAL-LOGIT MOMENTS (the
    starting values only). -> dict a, sigma, loglik, ok (converged, sigma >= SIGMA_MIN, negative definite
    Hessian), var_t (the observed-information variance of log sigma-hat)."""
    import numpy as np
    K = np.asarray(K, float)
    n, R = K.shape
    lo, hi = interval_bounds(K, N)
    z0 = np.log((K + 0.5) / (N - K + 0.5))
    a = z0.mean(axis=1)
    t = np.log(np.maximum(z0.std(axis=1, ddof=1), 0.05))
    ll, g = _marg_ll(lo, hi, a, t)
    done = np.zeros(n, bool)
    floor_t = math.log(SIGMA_MIN) - 3
    for _ in range(max_iter):
        act = np.flatnonzero(~done & np.isfinite(ll))
        if not len(act):
            break
        lo_, hi_ = lo[act], hi[act]
        H = _marg_hess(lo_, hi_, a[act], t[act])
        ga = g[act]
        step = np.empty_like(ga)
        for m in range(len(act)):
            Hm = H[m]
            if Hm[0, 0] < 0 and np.linalg.det(Hm) > 0:
                step[m] = -np.linalg.solve(Hm, ga[m])
            else:                                             # (not concave here: a gradient step)
                step[m] = ga[m] / (1.0 + np.abs(ga[m]).max())
        lam = np.ones(len(act))
        a0, t0, ll0 = a[act].copy(), t[act].copy(), ll[act].copy()
        a_new, t_new = a0 + step[:, 0], t0 + step[:, 1]
        ll_new, g_new = _marg_ll(lo_, hi_, a_new, t_new)
        for _h in range(40):
            bad = ~(np.isfinite(ll_new) & (ll_new >= ll0 - 1e-12))
            if not bad.any():
                break
            lam[bad] *= 0.5
            a_new[bad] = a0[bad] + lam[bad] * step[bad, 0]
            t_new[bad] = t0[bad] + lam[bad] * step[bad, 1]
            ll_new[bad], g_new[bad] = _marg_ll(lo_[bad], hi_[bad], a_new[bad], t_new[bad])
        a[act], t[act], ll[act], g[act] = a_new, t_new, ll_new, g_new
        conv = (np.abs(g_new).max(axis=1) < MARGINAL_TOL * R) | (lam * np.abs(step).max(axis=1) < 1e-13) | \
            (t_new < floor_t)
        done[act[conv]] = True
    H = _marg_hess(lo, hi, a, t)
    ok = done & np.isfinite(ll) & (np.exp(t) >= SIGMA_MIN) & (H[:, 0, 0] < 0) & (np.linalg.det(H) > 0) & \
        (np.abs(g).max(axis=1) < 1e-5 * R)
    var_t = np.full(n, np.nan)
    good = np.flatnonzero(ok)
    if len(good):
        var_t[good] = np.linalg.inv(-H[good])[:, 1, 1]
    ok &= var_t * MARG_INFO_MIN * R <= 1.0                 # (a spread the data cannot measure: degenerate)
    var_t[~ok] = np.nan
    return {"a": a, "sigma": np.exp(t), "loglik": ll, "ok": ok, "var_t": var_t}


# ================================================================== the bank's arrays and pairs
def arrays(obs, horizon):
    """-> per horizon the complete exposed cells (prey / predator snapshot keys and indices, counts C and S:
    cells x R), the free controls (prey snapshot x R, NaN where missing), N per channel, the replicates."""
    import numpy as np
    B = capture_bound(horizon)
    h = str(horizon)
    by, free = {}, {}
    reps = {o["replicate"] for o in obs}
    if any(not isinstance(r, int) or isinstance(r, bool) for r in reps) or sorted(reps) != list(range(len(reps))):
        raise NoiseBankError(f"replicates must be the integers 0..R-1 (got {sorted(map(str, reps))[:5]}...)")
    reps = sorted(reps)
    for o in obs:
        x = o["horizons"][h]
        vals = [x.get("survivors")] + ([] if o["pred"] is None else [x.get("captures")])
        if any(not isinstance(v, int) or isinstance(v, bool) for v in vals):
            raise NoiseBankError(f"{o.get('cell')}: counts at {h} steps must be integers")
        if o["pred"] is None:
            free.setdefault(tuple(o["prey"]), {})[o["replicate"]] = x["survivors"]
        else:
            key = (tuple(o["prey"]), tuple(o["pred"]))
            if o["replicate"] in by.get(key, {}):
                raise NoiseBankError(f"{key} replicate {o['replicate']} occurs twice")
            by.setdefault(key, {})[o["replicate"]] = (x["captures"], x["survivors"])
    R = len(reps)
    cells = sorted(k for k, v in by.items() if len(v) == R)
    prey = sorted({i for i, _ in cells} | set(free))
    pred = sorted({j for _, j in cells})
    pi = {k: n for n, k in enumerate(prey)}
    pj = {k: n for n, k in enumerate(pred)}
    Cc = np.array([[by[c][r][0] for r in reps] for c in cells], float).reshape(len(cells), R)
    Sc = np.array([[by[c][r][1] for r in reps] for c in cells], float).reshape(len(cells), R)
    Fc = np.array([[free.get(i, {}).get(r, np.nan) for r in reps] for i in prey], float).reshape(len(prey), R)
    for name, arr, n in (("captures", Cc, B), ("survivors", Sc, N_PREY), ("free survivors", Fc, N_PREY)):
        v = arr[np.isfinite(arr)]
        if np.any(v < 0) or np.any(v > n):
            raise NoiseBankError(f"{name} outside the integers 0..{n} at {horizon} steps")
    return {"prey": prey, "pred": pred, "I": np.array([pi[i] for i, _ in cells], int),
            "J": np.array([pj[j] for _, j in cells], int), "C": Cc, "S": Sc, "F": Fc,
            "N": {"C": B, "S": N_PREY, "F": N_PREY}, "R": R, "incomplete_cells": len(by) - len(cells)}


def usable(A):
    """Per CHANNEL: the saturation mask, then the stage-1 marginal fits -> {ch: {"ok", "mu", "a", "sigma",
    "var_t", "counts"}}."""
    import numpy as np
    out = {}
    for ch in ("C", "S", "F"):
        Kc = A[ch]
        N = A["N"][ch]
        complete = np.all(np.isfinite(Kc), axis=1)
        mu = np.full(len(Kc), np.nan)
        mu[complete] = Kc[complete].mean(axis=1) / N
        sat = complete & ((mu < SATURATION[0]) | (mu > SATURATION[1]))
        fit_rows = np.flatnonzero(complete & ~sat)
        ok = np.zeros(len(Kc), bool)
        a, sg, vt = (np.full(len(Kc), np.nan) for _ in range(3))
        if len(fit_rows):
            f = fit_marginals(Kc[fit_rows], N)
            ok[fit_rows] = f["ok"]
            a[fit_rows], sg[fit_rows], vt[fit_rows] = f["a"], f["sigma"], f["var_t"]
        out[ch] = {"ok": ok, "mu": mu, "a": a, "sigma": sg, "var_t": vt,
                   "counts": {"rows": int(len(Kc)), "incomplete": int((~complete).sum()), "saturated": int(sat.sum()),
                              "unidentified": int(len(fit_rows) - ok[fit_rows].sum()), "usable": int(ok.sum())}}
    return out


def _std_bounds(A, U, ch, rows):
    """The standardized interval bounds (rows x R) of channel ch at the stage-1 margins."""
    lo, hi = interval_bounds(A[ch][rows], A["N"][ch])
    a, s = U[ch]["a"][rows][:, None], U[ch]["sigma"][rows][:, None]
    return (lo - a) / s, (hi - a) / s


def group_pairs(A, U):
    """The nine groups' observation pairs (see the module docstring): per group a list of blocks (channel 1,
    rows 1, channel 2, rows 2, [prey-world arrays], [predator-world arrays]); every pair is repeated over the
    replicates (the same r for both members). Rows index the exposed cells (C, S) or the prey snapshots
    (F). -> (groups, the worlds in index order)."""
    import numpy as np
    I, J = A["I"], A["J"]
    n = len(I)
    worlds = sorted({p[0] for p in A["prey"]} | {p[0] for p in A["pred"]})
    wi = {w: k for k, w in enumerate(worlds)}
    pw = np.array([wi[A["prey"][i][0]] for i in I], int).reshape(n)
    qw = np.array([wi[A["pred"][j][0]] for j in J], int).reshape(n)
    a, b = np.triu_indices(n, 1)
    rowp = (I[a] == I[b]) & (J[a] != J[b])
    donp = (J[a] == J[b]) & (I[a] != I[b])
    ok = {ch: U[ch]["ok"] for ch in ("C", "S", "F")}
    G = {g: [] for g in GROUPS}

    def add(g, c1, r1, c2, r2, prey_w, pred_w):
        m = ok[c1][r1] & ok[c2][r2]
        if m.any():
            G[g].append((c1, r1[m], c2, r2[m], [x[m] for x in prey_w], [x[m] for x in pred_w]))
    ra, rb = a[rowp], b[rowp]
    da, db = a[donp], b[donp]
    add("R_CC", "C", ra, "C", rb, [pw[ra]], [qw[ra], qw[rb]])
    add("R_SS", "S", ra, "S", rb, [pw[ra]], [qw[ra], qw[rb]])
    add("R_CS", "C", ra, "S", rb, [pw[ra]], [qw[ra], qw[rb]])
    add("R_CS", "S", ra, "C", rb, [pw[ra]], [qw[ra], qw[rb]])
    add("D_CC", "C", da, "C", db, [pw[da], pw[db]], [qw[da]])
    add("D_SS", "S", da, "S", db, [pw[da], pw[db]], [qw[da]])
    add("D_CS", "C", da, "S", db, [pw[da], pw[db]], [qw[da]])
    add("D_CS", "S", da, "C", db, [pw[da], pw[db]], [qw[da]])
    cr = np.arange(n)
    add("T_CS", "C", cr, "S", cr, [pw], [qw])
    add("R_CF", "C", cr, "F", I, [pw], [qw])
    add("R_SF", "S", cr, "F", I, [pw], [qw])
    return G, worlds


def rho_grid(m=Z_INTERVALS):
    """The registered dependence grid (Codex #72 r2 P2): m + 1 nodes UNIFORM IN z = atanh(rho) over
    [-atanh(RHO_MAX), +atanh(RHO_MAX)] (finer in rho near the limits, where the log likelihood bends like
    1 / (1 - rho)) -> the rho values."""
    import numpy as np
    if not isinstance(m, int) or m < 8:
        raise NoiseBankError(f"the grid needs at least 8 intervals (got {m!r})")
    return np.tanh(np.linspace(-Z_MAX, Z_MAX, m + 1))


def group_tables(A, U, G, m=Z_INTERVALS, chunk=40000):
    """Stage 2's exact contributions: per group and per bootstrap source key, the summed dependence
    contributions log P(both; rho) - log P(1) - log P(2) at every grid node (log_rect / _log_iprob: no
    floor; the deep-tail contributions, log P(both) < -700, are counted per group) -> {g: {"keys": [(prey
    worlds, predator worlds): DISTINCT worlds per role], "T": keys x nodes, "pairs": n, "deep_tail": n}}."""
    import numpy as np
    grid = rho_grid(m)
    out = {}
    for g in GROUPS:
        keys, blocks, npairs = {}, [], 0
        for c1, r1, c2, r2, prey_w, pred_w in G[g]:
            l1, h1 = _std_bounds(A, U, c1, r1)
            l2, h2 = _std_bounds(A, U, c2, r2)
            kp = np.stack(prey_w, 1)
            kq = np.stack(pred_w, 1)
            kid = np.array([keys.setdefault((tuple(sorted({int(x) for x in kp[i]})),
                                             tuple(sorted({int(x) for x in kq[i]}))), len(keys))
                            for i in range(len(r1))], int)
            blocks.append((l1.ravel(), h1.ravel(), l2.ravel(), h2.ravel(), np.repeat(kid, l1.shape[1])))
            npairs += l1.size
        T = np.zeros((len(keys), len(grid)))
        deep = 0
        for l1, h1, l2, h2, kid in blocks:
            for c0 in range(0, len(l1), chunk):
                sl = slice(c0, c0 + chunk)
                base = _log_iprob(l1[sl], h1[sl]) + _log_iprob(l2[sl], h2[sl])
                if not np.all(np.isfinite(base)):
                    raise NoiseBankError(f"{g}: an empty marginal interval")
                for j, r in enumerate(grid):
                    lp = log_rect(l1[sl], h1[sl], l2[sl], h2[sl], float(r))
                    if not np.all(np.isfinite(lp)):
                        raise NoiseBankError(f"{g}: a rectangle log probability is not finite at rho {r:.4f}")
                    deep += int(np.sum(lp < -700.0))
                    T[:, j] += np.bincount(kid[sl], weights=lp - base, minlength=len(keys))
        out[g] = {"keys": list(keys), "T": T, "pairs": int(npairs), "deep_tail": deep}
    return out


def _zcoord(rho, m):
    import numpy as np
    return (np.arctanh(np.asarray(rho, float)) + Z_MAX) / (2 * Z_MAX / m)


def _cubic(vals, rho, m=Z_INTERVALS):
    """The local-cubic interpolant (4 nodes, in z = atanh(rho)) of grid values at rho (array); rho must lie
    in [-RHO_MAX, RHO_MAX] (never clamped)."""
    import numpy as np
    vals = np.asarray(vals, float)
    rho = np.asarray(rho, float)
    if np.any(np.abs(rho) > RHO_MAX + 1e-12):
        raise NoiseBankError("a correlation outside the evaluable domain [-RHO_MAX, RHO_MAX]")
    x = _zcoord(np.clip(rho, -RHO_MAX, RHO_MAX), m)
    M = len(vals)
    k = np.clip(np.floor(x).astype(int), 1, M - 3)
    u = x - k
    v0, v1, v2, v3 = vals[k - 1], vals[k], vals[k + 1], vals[k + 2]
    return (v0 * (-(u * (u - 1) * (u - 2)) / 6) + v1 * ((u + 1) * (u - 1) * (u - 2) / 2)
            + v2 * (-(u + 1) * u * (u - 2) / 2) + v3 * ((u + 1) * u * (u - 1) / 6))


def _cubic1(vals, rho, m=Z_INTERVALS):
    """_cubic for one rho over a Python list (the optimizer's inner loop); rho in the domain (checked by
    the caller's barrier)."""
    M = len(vals)
    x = (math.atanh(rho) + Z_MAX) / (2 * Z_MAX / m)
    k = min(max(int(math.floor(x)), 1), M - 3)
    u = x - k
    return (vals[k - 1] * (-(u * (u - 1) * (u - 2)) / 6) + vals[k] * ((u + 1) * (u - 1) * (u - 2) / 2)
            + vals[k + 1] * (-(u + 1) * u * (u - 2) / 2) + vals[k + 2] * ((u + 1) * u * (u - 1) / 6))


def _argmax(vals, m=Z_INTERVALS, sub=50):
    import numpy as np
    fine = np.tanh(np.linspace(-Z_MAX, Z_MAX, m * sub + 1))
    f = _cubic(vals, np.clip(fine, -RHO_MAX, RHO_MAX), m)
    k = int(np.argmax(f))
    return float(np.clip(fine[k], -RHO_MAX, RHO_MAX)), float(f[k])


# ================================================================== components from the nine groups
def components_of(r):
    """The nine group correlations -> (SigmaR, SigmaD, SigmaE, feasible, problems); SigmaR[F, F] by the
    minimal-feasible CONVENTION v' A^+ v."""
    import numpy as np
    rC, rS, rCS = r["R_CC"], r["R_SS"], r["R_CS"]
    dC, dS, dCS = r["D_CC"], r["D_SS"], r["D_CS"]
    eC, eS = 1.0 - rC - dC, 1.0 - rS - dS
    eCS = r["T_CS"] - rCS - dCS
    A = np.array([[rC, rCS], [rCS, rS]], float)
    v = np.array([r["R_CF"], r["R_SF"]], float)
    Ap = np.linalg.pinv(A, rcond=1e-12)
    FF = float(v @ Ap @ v)
    SR = np.array([[rC, rCS, v[0]], [rCS, rS, v[1]], [v[0], v[1], FF]])
    SD = np.array([[dC, dCS], [dCS, dS]])
    SE = np.array([[eC, eCS], [eCS, eS]])
    prob = []
    for name, M in (("the C-S row block", A), ("SigmaD", SD), ("SigmaE", SE)):
        if np.min(np.linalg.eigvalsh(M)) < -FEAS_TOL:
            prob.append(f"{name} is not PSD")
    if np.linalg.norm(A @ Ap @ v - v) > 1e-9 * max(1.0, float(np.linalg.norm(v))):
        prob.append("the free row covariances are outside the C-S row block's range")
    if FF > 1 + FEAS_TOL:
        prob.append(f"the free row convention {FF:.4f} exceeds the unit free variance")
    if np.min(np.linalg.eigvalsh(SR)) < -1e-9:
        prob.append("SigmaR is not PSD")
    return SR, SD, SE, not prob, prob


def _theta_map(th):
    """The PSD parametrization (9 angles) -> the nine group correlations (every point feasible)."""
    pC1, pC2, pS1, pS2, psR, psD, psE, om, ta = th
    rC, dC, eC = math.cos(pC1) ** 2, math.sin(pC1) ** 2 * math.cos(pC2) ** 2, math.sin(pC1) ** 2 * math.sin(pC2) ** 2
    rS, dS, eS = math.cos(pS1) ** 2, math.sin(pS1) ** 2 * math.cos(pS2) ** 2, math.sin(pS1) ** 2 * math.sin(pS2) ** 2
    cR, cD, cE = math.sin(psR), math.sin(psD), math.sin(psE)
    rCS, dCS, eCS = cR * math.sqrt(rC * rS), cD * math.sqrt(dC * dS), cE * math.sqrt(eC * eS)
    lr = math.sin(om)
    l0, l1 = lr * math.cos(ta), lr * math.sin(ta)
    vC = math.sqrt(rC) * l0
    vS = cR * math.sqrt(rS) * l0 + math.sqrt(rS) * math.sqrt(max(0.0, 1 - cR * cR)) * l1
    return {"R_CC": rC, "R_SS": rS, "R_CS": rCS, "D_CC": dC, "D_SS": dS, "D_CS": dCS, "T_CS": rCS + dCS + eCS,
            "R_CF": vC, "R_SF": vS}


def _theta_start(r):
    """The projection of (possibly infeasible) group values onto the parametrization's angles."""
    def shares(x, y):
        v = [max(x, 0.0), max(y, 0.0), max(1.0 - x - y, 0.0)]
        s = sum(v) or 1.0
        return [q / s for q in v]
    rC, dC, eC = shares(r["R_CC"], r["D_CC"])
    rS, dS, eS = shares(r["R_SS"], r["D_SS"])

    def ang(rr, dd, ee):
        p1 = math.acos(min(1.0, math.sqrt(rr)))
        p2 = math.acos(min(1.0, math.sqrt(dd / (dd + ee)))) if dd + ee > 0 else 0.0
        return p1, p2

    def corr(c, x, y):
        return math.asin(max(-1.0, min(1.0, c / math.sqrt(x * y)))) if x * y > 1e-15 else 0.0
    pC1, pC2 = ang(rC, dC, eC)
    pS1, pS2 = ang(rS, dS, eS)
    psR, psD = corr(r["R_CS"], rC, rS), corr(r["D_CS"], dC, dS)
    psE = corr(r["T_CS"] - r["R_CS"] - r["D_CS"], eC, eS)
    cR = math.sin(psR)
    l0 = r["R_CF"] / math.sqrt(rC) if rC > 1e-15 else 0.0
    den = math.sqrt(rS) * math.sqrt(max(0.0, 1 - cR * cR))
    l1 = (r["R_SF"] - cR * math.sqrt(rS) * l0) / den if den > 1e-12 else 0.0
    nrm = math.hypot(l0, l1)
    if nrm > 1:
        l0, l1, nrm = l0 / nrm, l1 / nrm, 1.0
    return [pC1, pC2, pS1, pS2, psR, psD, psE, math.asin(nrm), math.atan2(l1, l0)]


def nelder_mead(f, x0, step=0.1, max_iter=6000, ftol=1e-12, xtol=1e-10):
    """A plain deterministic Nelder-Mead MINIMIZER (no scipy) -> (x, f(x), converged)."""
    n = len(x0)
    pts = [list(x0)] + [[x0[j] + (step if j == i else 0.0) for j in range(n)] for i in range(n)]
    val = [f(p) for p in pts]
    converged = False
    for _ in range(max_iter):
        order = sorted(range(n + 1), key=lambda k: val[k])
        pts, val = [pts[k] for k in order], [val[k] for k in order]
        if math.isfinite(val[-1]) and abs(val[-1] - val[0]) <= ftol * (1 + abs(val[0])) and \
                max(abs(pts[k][j] - pts[0][j]) for k in range(1, n + 1) for j in range(n)) <= xtol:
            converged = True
            break
        cen = [sum(p[j] for p in pts[:-1]) / n for j in range(n)]
        xr = [cen[j] + (cen[j] - pts[-1][j]) for j in range(n)]
        fr = f(xr)
        if fr < val[0]:
            xe = [cen[j] + 2 * (cen[j] - pts[-1][j]) for j in range(n)]
            fe = f(xe)
            pts[-1], val[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < val[-2]:
            pts[-1], val[-1] = xr, fr
        else:
            xc = [cen[j] + 0.5 * (pts[-1][j] - cen[j]) for j in range(n)]
            fc = f(xc)
            if fc < val[-1]:
                pts[-1], val[-1] = xc, fc
            else:
                for k in range(1, n + 1):
                    pts[k] = [pts[0][j] + 0.5 * (pts[k][j] - pts[0][j]) for j in range(n)]
                    val[k] = f(pts[k])
    k = min(range(n + 1), key=lambda i: val[i])
    return pts[k], val[k], converged


def _mats(r):
    """The three LMIs of the feasible set, affine in the nine group values (GROUPS order): the row block
    with the free convention [[rC, rCS, vC], [rCS, rS, vS], [vC, vS, 1]], the donor block, the cell block."""
    import numpy as np
    rC, rS, rCS, dC, dS, dCS, T, vC, vS = r
    return (np.array([[rC, rCS, vC], [rCS, rS, vS], [vC, vS, 1.0]]), np.array([[dC, dCS], [dCS, dS]]),
            np.array([[1 - rC - dC, T - rCS - dCS], [T - rCS - dCS, 1 - rS - dS]]))


def _dmats():
    """d(LMI)/d(group value i), constant."""
    import numpy as np
    base = _mats(np.zeros(9))
    out = []
    for i in range(9):
        e = np.zeros(9)
        e[i] = 1.0
        out.append([a - b for a, b in zip(_mats(e), base)])
    return out


def _interior(lists, x0, m, mu0=1.0):
    """Maximize sum_g l_g(rho_g) over {the three LMIs PD, |rho_g| < RHO_MAX}: a log-barrier interior-point
    method (damped Newton on -L + mu B, mu decreased 5x per stage to 1e-10), every evaluation strictly
    inside the evaluable domain -> (rho, L, converged)."""
    import numpy as np
    dM = _dmats()
    a2 = RHO_MAX ** 2

    def feasible(x):
        return np.all(np.abs(x) < RHO_MAX) and all(np.min(np.linalg.eigvalsh(M)) > 0 for M in _mats(x))

    def L(x):
        return sum(_cubic1(lists[g], float(x[i]), m) for i, g in enumerate(GROUPS))

    def phi(x, mu):
        if not feasible(x):
            return math.inf
        b = -sum(np.linalg.slogdet(M)[1] for M in _mats(x)) - float(np.sum(np.log(a2 - x * x)))
        return -L(x) + mu * b

    def grad_hess(x, mu):
        h = 1e-6
        g = np.zeros(9)
        H = np.zeros((9, 9))
        for i, gr in enumerate(GROUPS):
            xi = float(x[i])
            lo, hi = max(xi - h, -RHO_MAX + 1e-12), min(xi + h, RHO_MAX - 1e-12)
            f0, fm, fp = _cubic1(lists[gr], xi, m), _cubic1(lists[gr], lo, m), _cubic1(lists[gr], hi, m)
            g[i] = -(fp - fm) / (hi - lo)
            H[i, i] = -max((fp - 2 * f0 + fm) / ((hi - lo) / 2) ** 2, -1e12)
        inv = [np.linalg.inv(M) for M in _mats(x)]
        for i in range(9):
            g[i] += mu * (-sum(np.trace(Mi @ dM[i][k]) for k, Mi in enumerate(inv)) + 2 * x[i] / (a2 - x[i] ** 2))
            H[i, i] += mu * 2 * (a2 + x[i] ** 2) / (a2 - x[i] ** 2) ** 2
            for j in range(i, 9):
                v = mu * sum(np.trace(Mi @ dM[i][k] @ Mi @ dM[j][k]) for k, Mi in enumerate(inv))
                H[i, j] += v
                if j != i:
                    H[j, i] += v
        return g, H
    x = np.array(x0, float)
    if not feasible(x):
        raise NoiseBankError("the interior-point start is not strictly feasible")
    mu = mu0
    while mu > 1e-10:
        ok = False
        for _ in range(200):
            g, H = grad_hess(x, mu)
            lam = 0.0
            while True:
                try:
                    step = -np.linalg.solve(H + lam * np.eye(9), g)
                    if np.all(np.isfinite(step)) and g @ step < 0:
                        break
                except np.linalg.LinAlgError:
                    pass
                lam = max(2 * lam, 1e-8 * (1 + float(np.max(np.abs(np.diag(H))))))
            dec = -float(g @ step)
            if dec < 1e-12:
                ok = True
                break
            f0, t = phi(x, mu), 1.0
            while t > 1e-14 and not phi(x + t * step, mu) <= f0 - 1e-4 * t * dec:
                t *= 0.5
            if t <= 1e-14:
                ok = dec < 1e-8
                break
            x = x + t * step
        if not ok:
            return x, L(x), False
        mu /= 5.0
    return x, L(x), True


def _strict_start(un, frac):
    """A strictly feasible start: the unconstrained maxima shrunk toward the central point (shares 1/3,
    correlations 0) to frac of the largest feasible step."""
    import numpy as np
    c0 = np.array([1 / 3, 1 / 3, 0, 1 / 3, 1 / 3, 0, 0, 0, 0], float)
    u = np.clip(np.array([un[g] for g in GROUPS], float), -RHO_MAX, RHO_MAX)

    def ok(x):
        return np.all(np.abs(x) < RHO_MAX) and all(np.min(np.linalg.eigvalsh(M)) > 1e-12 for M in _mats(x))
    lo, hi = 0.0, 1.0
    if ok(u):
        return u
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if ok(c0 + mid * (u - c0)) else (lo, mid)
    return c0 + frac * lo * (u - c0)


def fit_dependence(obj, m=Z_INTERVALS):
    """Stage 2 from per-group grid objectives {g: values at the nodes} -> {"rho": the nine values, "fit":
    "unconstrained" | "constrained", "loglik", "SigmaR", "SigmaD", "SigmaE", "unconstrained": the group
    maxima, "problems": their infeasibilities, "starts": the multi-start record}.
    The constrained branch (Codex #72 r2 P2-3) maximizes over the feasible set in the GROUP VALUES (three
    linear matrix inequalities and the evaluable box |rho| < RHO_MAX: convex) by a log-barrier interior-point
    method, every evaluation strictly inside the domain (never a clamped value), from MULTI_START registered
    strictly feasible starts (the unconstrained maxima shrunk toward the central point: the first to 98% of
    the feasible step, the rest to seeded fractions); every start must converge and their optima agree within
    START_TOL (log-likelihood units), else the fit is REFUSED (NoiseBankError: not certified)."""
    import numpy as np
    un = {g: _argmax(obj[g], m)[0] for g in GROUPS}
    SR, SD, SE, feas, prob = components_of(un)
    lists = {g: [float(v) for v in obj[g]] for g in GROUPS}
    starts = None
    if feas:
        rho, how = un, "unconstrained"
    else:
        import numpy as np
        res = []
        rng = np.random.default_rng(rqlib.derive_seed(SEED_NAMESPACE, "multistart"))
        for k in range(MULTI_START):
            frac = 0.98 if k == 0 else float(rng.uniform(0.05, 0.95))
            x0 = _strict_start(un, frac)
            x, Lx, ok = _interior(lists, x0, m)
            if not ok:
                raise NoiseBankError("the constrained fit did not converge (interior point)")
            res.append((Lx, x))
        Lbest = max(v for v, _ in res)
        spread = Lbest - min(v for v, _ in res)
        starts = {"starts": MULTI_START, "loglik_spread": spread}
        if spread > START_TOL:
            raise NoiseBankError(f"the constrained fit is not certified: {MULTI_START} starts disagree by "
                                 f"{spread:.3g} log-likelihood units (> {START_TOL})")
        best = max(res, key=lambda t: t[0])[1]
        rho, how = {g: float(best[i]) for i, g in enumerate(GROUPS)}, "constrained"
        SR, SD, SE, feas2, prob2 = components_of(rho)
        if not feas2:
            raise NoiseBankError(f"the constrained fit is infeasible: {prob2}")
    ll = sum(_cubic1(lists[g], rho[g], m) for g in GROUPS)
    return {"rho": rho, "fit": how, "loglik": ll, "SigmaR": SR, "SigmaD": SD, "SigmaE": SE,
            "unconstrained": un, "problems": prob, "starts": starts}


# ================================================================== s(mu)
def pava(x, w, increasing=True):
    """Weighted isotonic regression (pool adjacent violators) of x (in order) -> (fitted values, the blocks
    [(start, stop)])."""
    import numpy as np
    vals = np.asarray(x, float) if increasing else -np.asarray(x, float)
    out = []
    for k, (v, wt) in enumerate(zip(vals, np.asarray(w, float))):
        out.append([v, wt, k, k + 1])
        while len(out) > 1 and out[-2][0] > out[-1][0]:
            v2, w2, _, e2 = out.pop()
            v1, w1, s1, _ = out.pop()
            out.append([(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2, s1, e2])
    fit = np.concatenate([np.full(e - s, v) for v, _, s, e in out]) if out else np.zeros(0)
    return (fit if increasing else -fit), [(s, e) for _, _, s, e in out]


def fit_scale(mu, var, weights=None):
    """D4's s(mu) for one channel (see the module docstring): the tie-pooled isotonic regression of var on
    logit(mu), one knot per plateau (its weighted mean location) with sqrt(its variance) -> a noisescale
    curve with "direction", "support", "cells", "blocks"; None without usable cells."""
    import numpy as np
    mu, var = np.asarray(mu, float), np.asarray(var, float)
    w = np.ones(len(mu)) if weights is None else np.asarray(weights, float)
    ok = np.isfinite(mu) & np.isfinite(var) & (mu > 0) & (mu < 1) & (w > 0)
    mu, var, w = mu[ok], var[ok], w[ok]
    if not len(mu):
        return None
    x = np.log(mu / (1 - mu))
    ux, inv = np.unique(x, return_inverse=True)                         # (tied locations pooled)
    W = np.bincount(inv, weights=w, minlength=len(ux))
    V = np.bincount(inv, weights=w * var, minlength=len(ux)) / W
    fits = {}
    for d in ("decreasing", "increasing"):
        f, _ = pava(V, W, increasing=(d == "increasing"))
        fits[d] = (float(np.sum(W * (V - f) ** 2)), f)
    d = min(fits, key=lambda k: (fits[k][0], k))
    f = fits[d][1]
    starts = [0] + [i for i in range(1, len(f)) if f[i] != f[i - 1]]      # (the plateaus)
    blocks = list(zip(starts, starts[1:] + [len(f)]))
    kx = [float(np.sum(W[s:e] * ux[s:e]) / np.sum(W[s:e])) for s, e in blocks]
    ks = [float(math.sqrt(max(f[s], 0.0))) for s, e in blocks]
    if min(ks) <= 0:
        return None
    curve = {"x": kx, "s": ks, "direction": d, "support": [float(ux[0]), float(ux[-1])], "cells": int(len(mu)),
             "blocks": len(blocks), "extrapolation": "constant beyond the outermost knots (an assumption beyond "
                                                     "the bank's support, not an estimate)"}
    return noisescale.check_curve(curve)


def _trigamma(x):
    """psi'(x) for x > 0: the recurrence up to x >= 10, then the asymptotic series through x^-15 (relative error
    below 1e-13, so no visible jump where the recurrence count changes)."""
    acc = 0.0
    while x < 10.0:
        acc += 1.0 / (x * x)
        x += 1.0
    t = 1.0 / (x * x)
    tail = 1 / 6 + t * (-1 / 30 + t * (1 / 42 + t * (-1 / 30 + t * (5 / 66 + t * (-691 / 2730 + t * 7 / 6)))))
    return acc + 1.0 / x + t / 2.0 + t / x * tail


def inv_trigamma(y):
    """x > 0 with trigamma(x) = y (> 0; trigamma is decreasing): bisection on log x inside a bracket grown
    from the asymptotic guess 1 / y + 1/2 until it encloses the root (any tiny or large y)."""
    if not y > 0 or not math.isfinite(y):
        raise NoiseBankError(f"inv_trigamma needs a positive finite value (got {y!r})")
    g = math.log(1.0 / y + 0.5)
    lo, hi = g - 2.0, g + 2.0
    while _trigamma(math.exp(lo)) <= y:
        lo -= 2.0
    while _trigamma(math.exp(hi)) > y:
        hi += 2.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _trigamma(math.exp(mid)) > y:
            lo = mid
        else:
            hi = mid
    return math.exp(0.5 * (lo + hi))


def nu0_of(mu, sigma, var_t, curve):
    """map.py's prior degrees of freedom (see the module docstring), explicitly encoded."""
    import numpy as np
    mu, sigma, var_t = (np.asarray(x, float) for x in (mu, sigma, var_t))
    ok = np.isfinite(mu) & np.isfinite(sigma) & np.isfinite(var_t)
    if curve is None:
        return {"status": "unavailable", "reason": "no s(mu) curve"}
    if ok.sum() < 3:
        return {"status": "unavailable", "reason": f"{int(ok.sum())} usable cells (3 needed)"}
    s = noisescale.evaluate(curve, mu[ok])
    lr = np.log(sigma[ok] ** 2) - np.log(s ** 2)
    samp = float(np.mean(4.0 * var_t[ok]))
    excess = float(np.var(lr, ddof=1) - samp)
    rec = {"excess_log_variance": excess, "sampling_log_variance": samp, "cells": int(ok.sum())}
    if not excess > 0:
        return dict(rec, status="full_pooling")
    return dict(rec, status="estimated", nu0=2.0 * inv_trigamma(excess))


# ================================================================== the estimate
def pick_weights(keys, m, mp):
    """The registered bootstrap weights (Codex #72 r2 P2-4, the coordinator's ruling): a WORLD-MULTIPLICITY
    WEIGHTED LIKELIHOOD. Each pair's weight is the product of the prey-role multiplicities m over the DISTINCT
    prey worlds of its sources and of the predator-role multiplicities mp over its DISTINCT predator worlds
    (a world counts once however many of its snapshots the pair involves)."""
    import numpy as np
    return np.array([math.prod(int(m[a]) for a in set(kp)) * math.prod(int(mp[b]) for b in set(kq))
                     for kp, kq in keys], float)


BOOT_NAMES = ("R_CC", "R_SS", "R_CS", "R_CF", "R_SF", "D_CC", "D_SS", "D_CS", "E_CC", "E_SS", "E_CS")


def _entries(f):
    SR, SD, SE = f["SigmaR"], f["SigmaD"], f["SigmaE"]
    return [SR[0, 0], SR[1, 1], SR[0, 1], SR[0, 2], SR[1, 2], SD[0, 0], SD[1, 1], SD[0, 1], SE[0, 0], SE[1, 1], SE[0, 1]]


def bootstrap(tab, n_worlds, boot, seed, m=Z_INTERVALS):
    """The registered uncertainty procedure (see the module docstring) -> (draws x BOOT_NAMES array, failed
    draws: a group with no weight left, or a refused / non-converged fit)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    out, failed = [], 0
    for _ in range(boot):
        mm = np.bincount(rng.integers(0, n_worlds, n_worlds), minlength=n_worlds)
        mp = np.bincount(rng.integers(0, n_worlds, n_worlds), minlength=n_worlds)
        ob = {}
        for g in GROUPS:
            w = pick_weights(tab[g]["keys"], mm, mp)
            if not w.any():
                ob = None
                break
            ob[g] = w @ tab[g]["T"]
        if ob is None:
            failed += 1
            continue
        try:
            out.append(_entries(fit_dependence(ob, m)))
        except NoiseBankError:
            failed += 1
    return np.array(out, float).reshape(len(out), len(BOOT_NAMES)), failed


def interval_record(D, failed, boot):
    """Codex #72 r2 P2-5: the failed draws are counted; the interval is UNAVAILABLE (its own status, apart
    from the point estimate's) when they exceed BOOT_FAIL_MAX of the draws, otherwise reported with the
    failure rate, labelled approximate and conditional on identification."""
    import numpy as np
    rate = failed / boot if boot else 1.0
    rec = {"draws": boot, "failed": failed, "failure_rate": rate,
           "procedure": "world-multiplicity weighted likelihood (prey and predator roles resampled independently; "
                        "a pair weighted by the product over the DISTINCT worlds of each role); a departure from "
                        "H.7's materialized-record bootstrap: descriptive, outside the confirmatory family",
           "label": "approximate; conditional on identification (failed draws excluded)"}
    if rate > BOOT_FAIL_MAX or not len(D):
        return dict(rec, status="unavailable", ci95=None,
                    reason=f"{failed} of {boot} draws failed (> {BOOT_FAIL_MAX:.0%})")
    return dict(rec, status="ok", ci95={n: [float(np.percentile(D[:, k], 2.5)), float(np.percentile(D[:, k], 97.5))]
                                        for k, n in enumerate(BOOT_NAMES)})


def horizon_estimate(A, boot=BOOT, seed=0, m=Z_INTERVALS):
    """One horizon: the usable channels, the s(mu) curves and nu0, the nine groups, the components (or
    "unavailable" with reasons), the registered uncertainty procedure."""
    import numpy as np
    U = usable(A)
    rec = {"capture_bound": A["N"]["C"], "replicates": A["R"], "incomplete_cells": A["incomplete_cells"],
           "channels": {ch: U[ch]["counts"] for ch in ("C", "S", "F")}, "scales": {}, "nu0": {}, "curve_points": {}}
    for ch in ("C", "S", "F"):
        ok = U[ch]["ok"]
        cv = fit_scale(U[ch]["mu"][ok], U[ch]["sigma"][ok] ** 2)
        rec["scales"][ch] = cv
        rec["nu0"][ch] = nu0_of(U[ch]["mu"][ok], U[ch]["sigma"][ok], U[ch]["var_t"][ok], cv)
        rec["curve_points"][ch] = sorted([float(a), float(b)] for a, b in zip(U[ch]["mu"][ok], U[ch]["sigma"][ok]))
    G, worlds = group_pairs(A, U)
    rec["worlds"] = worlds
    reasons = [f"no {g} pairs" for g in GROUPS if not G[g]]
    if reasons:
        rec.update(status="unavailable", reasons=reasons, components=None, bootstrap=None)
        return rec
    tab = group_tables(A, U, G, m)
    obj = {g: tab[g]["T"].sum(axis=0) for g in GROUPS}
    groups = {}
    for g in GROUPS:
        r_hat, _ = _argmax(obj[g], m)
        z, h = math.atanh(r_hat), 2 * Z_MAX / m
        zs = [max(-Z_MAX, min(Z_MAX, z + d)) for d in (-h, 0.0, h)]
        f = [float(_cubic(obj[g], math.tanh(v), m)) for v in zs]
        d2 = (f[0] - 2 * f[1] + f[2]) / h ** 2 / (1 - r_hat ** 2) ** 2      # (d2 / d rho2 at the maximum)
        per = -d2 / tab[g]["pairs"]
        groups[g] = {"pairs": tab[g]["pairs"], "rho_max": r_hat, "curvature_per_pair": per,
                     "at_grid_edge": abs(r_hat) >= RHO_MAX - 1e-12, "deep_tail": tab[g]["deep_tail"]}
        if not per >= INFO_MIN:
            reasons.append(f"{g} is unidentified (curvature per pair {per:.3g} < {INFO_MIN})")
    rec["groups"] = groups
    if reasons:
        rec.update(status="unavailable", reasons=reasons, components=None, bootstrap=None)
        return rec
    try:
        fit = fit_dependence(obj, m)
    except NoiseBankError as e:
        rec.update(status="unavailable", reasons=[str(e)], components=None, bootstrap=None)
        return rec
    rec["components"] = {"SigmaR": fit["SigmaR"].tolist(), "SigmaD": fit["SigmaD"].tolist(),
                         "SigmaE": fit["SigmaE"].tolist(), "fit": fit["fit"], "loglik": fit["loglik"],
                         "unconstrained_problems": fit["problems"], "multistart": fit["starts"],
                         "SigmaR_FF": {"value": float(fit["SigmaR"][2, 2]), "status": "convention",
                                       "rule": "the minimal feasible free row variance v' A^+ v: one control per "
                                               "row leaves the free row / control split unidentified"},
                         "shares": {ch: {"row": float(fit["SigmaR"][k, k]), "donor": float(fit["SigmaD"][k, k]),
                                         "cell": float(fit["SigmaE"][k, k])} for k, ch in enumerate("CS")}}
    D, failed = bootstrap(tab, len(worlds), boot, seed, m)
    rec["bootstrap"] = interval_record(D, failed, boot)
    rec.update(status="ok", reasons=[])
    return rec


def estimate(doc, boot=BOOT, seed=0, m=Z_INTERVALS, replicates=None):
    """The bank: per horizon (horizon_estimate); the generator noise block and map.py's prior at the
    production 5k horizon (available only when its components and all three curves are)."""
    if doc.get("schema") != OBS_SCHEMA:
        raise NoiseBankError(f"observations schema {doc.get('schema')!r}")
    if not isinstance(boot, int) or isinstance(boot, bool) or boot < 1:
        raise NoiseBankError(f"bootstrap draws must be a positive integer (got {boot!r})")
    obs = doc["observations"]
    out = {"schema": BANK_SCHEMA, "obs_design_sha256": doc.get("design_sha256"), "plan_sha256": doc.get("plan_sha256"),
           "estimator": {"z_intervals": m, "rho_max": RHO_MAX, "saturation": list(SATURATION), "sigma_min": SIGMA_MIN,
                         "info_min": INFO_MIN, "multi_start": MULTI_START, "start_tol": START_TOL,
                         "boot": boot, "boot_fail_max": BOOT_FAIL_MAX, "seed": seed,
                         "rectangle": "log_rect (conditional integral, log space)",
                         "fixed_replicate_bias": "not corrected (see the PR's simulation)"}, "horizons": {}}
    for h in HORIZONS:
        A = arrays(obs, h)
        if replicates is not None and A["R"] != replicates:
            raise NoiseBankError(f"{A['R']} replicates; {replicates} are registered")
        out["horizons"][str(h)] = horizon_estimate(A, boot, seed, m)
    base = out["horizons"][str(HORIZONS[0])]
    why = list(base.get("reasons") or []) + [f"no {ch} curve" for ch in ("C", "S", "F") if base["scales"][ch] is None]
    if why:
        out["generator_noise"] = {"available": False, "reasons": why}
    else:
        c = base["components"]
        out["generator_noise"] = {"available": True,
                                  "s_logit": {ch: {k: base["scales"][ch][k] for k in ("x", "s", "direction")}
                                              for ch in ("C", "S", "F")},
                                  "SigmaR": c["SigmaR"], "SigmaD": c["SigmaD"], "SigmaE": c["SigmaE"],
                                  "horizon": HORIZONS[0], "capture_bound": capture_bound(HORIZONS[0])}
    out["map_variance"] = {"s_logit": out["generator_noise"].get("s_logit"), "nu0": base["nu0"],
                           "rule": "replicate-mean variance (nu0 s(mu)^2 + (R - 1) s_obs^2) / (nu0 + R - 1) / R; "
                                   "full_pooling: s(mu)^2 / R"}
    return out


# ================================================================== THE PRODUCTION V BUILDER
def _psd_factor(M):
    """F with F F' = M for a PSD M (the eigen square root; a singular M is allowed)."""
    import numpy as np
    w, V = np.linalg.eigh(np.asarray(M, float))
    if np.min(w) < -1e-12:
        raise NoiseBankError("a bank covariance component is not PSD")
    return V * np.sqrt(np.clip(w, 0.0, None))


def cov_parts(bank_noise, kind, structure, means, R=6):
    """THE PRODUCTION V BUILDER (Annex H.3.1): the bank covariance of one block's replicate means as (d, U),
    V = diag(d) + U U' (recurrence.Cov(d, U)), from the bank's components and its s(mu) curves (the D4
    registration, noisescale.evaluate), at the means GIVEN EXPLICITLY (the registration's choice: D4's
    null-model fitted means). The LINEARIZED (delta-method) covariance, g(mu) = s(mu) mu (1 - mu) (see the
    module docstring). kind "C" / "RC" (capture: rows share a prey key and a predator key) or "Q" / "RQ"
    (exposed survival minus its prey snapshot's free control: rows share the prey snapshot's row and free
    components and the predator key). structure: {"prey": per-row prey-key index, "pred": per-row
    predator-key index, "n_prey", "n_pred"}; means: {"C": per row} or {"S": per row, "F": per prey key}."""
    import numpy as np
    if kind not in KINDS:
        raise NoiseBankError(f"covariance kind {kind!r} (one of {KINDS})")
    if not isinstance(R, int) or isinstance(R, bool) or R < 1:
        raise NoiseBankError(f"replicates must be a positive integer (got {R!r})")
    try:
        curves = noisescale.check_set(bank_noise.get("s_logit"))
    except noisescale.ScaleError as e:
        raise NoiseBankError(f"the bank's s(mu): {e}")
    SR, SD, SE = (np.asarray(bank_noise[k], float) for k in ("SigmaR", "SigmaD", "SigmaE"))
    pi, pj = np.asarray(structure["prey"], int), np.asarray(structure["pred"], int)
    n = len(pi)
    if len(pj) != n or (n and (pi.min() < 0 or pi.max() >= structure["n_prey"] or pj.min() < 0
                                or pj.max() >= structure["n_pred"])):
        raise NoiseBankError("structure: prey / predator indices outside their key counts, or of unequal length")
    rows = np.arange(n)

    def g(ch, x, N):
        x = np.clip(np.asarray(x, float), 0.5 / N, 1 - 0.5 / N)
        return noisescale.evaluate(curves[ch], x) * x * (1 - x)
    if kind in ("C", "RC"):
        mC = np.asarray(means["C"], float)
        if len(mC) != n:
            raise NoiseBankError("means: one capture mean per row")
        gg = g("C", mC, bank_noise["capture_bound"])
        d = gg ** 2 * SE[0, 0] / R
        U1 = np.zeros((n, structure["n_prey"]))
        U1[rows, pi] = gg * math.sqrt(max(SR[0, 0], 0.0) / R)
        U2 = np.zeros((n, structure["n_pred"]))
        U2[rows, pj] = gg * math.sqrt(max(SD[0, 0], 0.0) / R)
        return d, np.hstack([U1, U2])
    mS, mF = np.asarray(means["S"], float), np.asarray(means["F"], float)
    if len(mS) != n or len(mF) != structure["n_prey"]:
        raise NoiseBankError("means: one exposed survival mean per row and one free mean per prey key")
    gS = g("S", mS, N_PREY)
    gF = g("F", mF[pi], N_PREY)
    Fm = _psd_factor([[SR[1, 1], SR[1, 2]], [SR[1, 2], SR[2, 2]]])
    eF = 1.0 - SR[2, 2]
    if eF < -1e-12:
        raise NoiseBankError("the free row variance exceeds the unit free variance")
    d = gS ** 2 * SE[1, 1] / R
    nuk = structure["n_prey"]
    M = np.zeros((n, 3 * nuk))
    M[rows, 3 * pi] = (gS * Fm[0, 0] - gF * Fm[1, 0]) / math.sqrt(R)
    M[rows, 3 * pi + 1] = (gS * Fm[0, 1] - gF * Fm[1, 1]) / math.sqrt(R)
    M[rows, 3 * pi + 2] = (-gF * math.sqrt(max(eF, 0.0))) / math.sqrt(R)
    Md = np.zeros((n, structure["n_pred"]))
    Md[rows, pj] = gS * math.sqrt(max(SD[1, 1], 0.0) / R)
    return d, np.hstack([M, Md])


# ================================================================== CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan")
    s.add_argument("--block", required=True)
    s.add_argument("--templates", nargs="+", required=True)
    s.add_argument("--age-reference", required=True)
    s.add_argument("--avoid", nargs="+", default=[])
    s.add_argument("--seed-namespace", default=SEED_NAMESPACE)
    s.add_argument("--validation-dir", required=True)
    s.add_argument("--main-registry", nargs="+", default=[], help="the main study's worlds registries (mandatory)")
    s.add_argument("--arena", required=True)
    s.add_argument("--out", required=True)
    s = sub.add_parser("collect")
    s.add_argument("--study", required=True)
    s.add_argument("--design", required=True)
    s.add_argument("--plan", required=True)
    s.add_argument("--declare-missing", nargs="*", default=[])
    s.add_argument("--out", required=True)
    s = sub.add_parser("estimate")
    s.add_argument("--obs", required=True)
    s.add_argument("--boot", type=int, default=BOOT)
    s.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":
            d = make_design(rqlib.read_json(a.block), [os.path.abspath(t) for t in a.templates],
                            os.path.abspath(a.age_reference), a.avoid, a.seed_namespace, a.validation_dir, a.arena,
                            a.main_registry)
            rqlib.write_json_durable(a.out, d)
            print(json.dumps({k: d["noisebank"][k] for k in ("worlds", "cells", "predator_trajectories",
                                                            "free_trajectories")}))
        elif a.cmd == "collect":
            doc = collect(a.study, rqlib.read_json(a.design), a.plan, a.declare_missing)
            rqlib.write_json_durable(a.out, doc)
            print(f"{len(doc['observations'])} observations, {len(doc['missing'])} declared missing")
        else:
            bank = estimate(rqlib.read_json(a.obs), boot=a.boot, replicates=REPLICATES)
            rqlib.write_json_durable(a.out, bank)
            g = bank["generator_noise"]
            print(json.dumps(g))
            if not g["available"]:
                print(f"noisebank.py estimate: the 5k generator noise is unavailable: {g['reasons']}", file=sys.stderr)
                return 2
        return 0
    except NoiseBankError as e:
        print(f"noisebank.py {a.cmd}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

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
  THE RECTANGLE PROBABILITIES (Codex #72 r2 P1, r3): log_rect on a REGISTERED ADMISSIBLE DOMAIN (what the
  bank produces; anything else is refused): finite standardized endpoints within +-E_MAX = 40 (infinite ends
  only for the counts 0 and N), widths >= W_MIN = 1e-6, |rho| <= RHO_MAX. The conditional integral over the
  narrower interval of phi(x) P(l < Y < h | x) (log-concave) in LOG space; half-infinite outer intervals
  restricted to where log f is within DROP = 50 of its maximum, the omitted mass bounded by log-concavity
  (refused above OMIT_TOL = 1e-14 relative); panels from a VALID slope bound (the Mills-ratio bound for
  one-sided ends), refused (never capped) beyond MAX_PANELS; narrow conditional intervals by the corrected
  midpoint rule, tail differences through expm1. No floor; deep-tail contributions (log P < -700) are
  counted. VALIDATED against an independent reference (math.erfc, the asymptotic tail series, a fixed
  8,000-interval composite Simpson rule) on the registered test set, Codex's counterexamples included: max |error| <=
  LOG_RECT_TOL = 1e-8 (test_noisebank).
  THE GRID (Codex #72 r2 P2, r3): exact contributions at 289 nodes in z = atanh(rho) (241 uniform, the outer 8
  intervals at each end split in 4), interpolated by a not-a-knot cubic SPLINE in z (C2) with ANALYTIC derivatives
  (l_rr = l_zz z_r^2 + l_z z_rr). LOCAL OBJECTIVE-VALUE VALIDATION at the point estimate: per group, the EXACT objective
  at the fitted rho and the off-grid midpoints of its bracket and neighbours; a miss above GRID_LL_TOL = 1e-3
  per pair inserts those exact columns as nodes (deduplicated at MIN_KNOT), and the fit is redone ONCE on the
  refined table; that refit's parameter shift is reported and FLAGGED above GRID_RHO_TOL = 1e-3 (never
  refused). This validates objective values locally; it is not a global certificate.
  IDENTIFICATION (the point estimate and EVERY bootstrap refit alike): the analytic curvature per (weighted)
  pair at the group maximum >= INFO_MIN; a maximum on the box |rho| = RHO_MAX is flagged (at_box) and needs a
  one-sided slope per pair >= INFO_MIN instead.
  When the unconstrained group maxima are jointly FEASIBLE (all three components PSD, the unit totals
  non-negative, the free row convention <= 1), they are the fit. Otherwise: the feasible set in the nine
  GROUP VALUES (three linear matrix inequalities: the row block with the free convention [[rC, rCS, vC],
  [rCS, rS, vS], [vC, vS, 1]], the donor block, the cell block; and the box) is convex but the likelihood is
  NOT concave there, so the fit is MULTI-START VALIDATED, NOT CERTIFIED: a log-barrier interior-point method
  (analytic derivatives, every evaluation strictly inside) from MULTI_START = 16 registered quasi-random
  (Halton) strictly feasible starts spread across the set; accepted only when >= MIN_AGREE = 3 runs reach the
  best value within START_TOL = 1e-4, those runs agree in every group value within PARAM_TOL = 1e-3, and the
  barrier problem's KKT residual (its gradient's max norm over max(1, ||grad L||)) is <= KKT_TOL = 1e-6, the
  Newton model kept positive definite; otherwise refused. The box |rho| <= 0.995 is a
  registered NUMERICAL restriction (a variance share above 0.995 cannot be fitted); a fitted value on it is
  flagged (at_box).
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
    noisebank.py collect --study STUDY --design noisebank_design.json --plan plan.jsonl [--declare-missing ...] \\
        --out obs.json [--age-diagnostics age_diagnostics.json]
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
VALIDATION_NAMESPACE = "finfolk-rq-validation-pilot-2026-11-a1"  # (the arena-#1 validation registry's namespace)
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
RHO_MAX = 0.995                    # (the registered evaluable box |rho| <= RHO_MAX: a NUMERICAL restriction)
Z_MAX = math.atanh(RHO_MAX)
Z_INTERVALS = 240                  # (the base grid: 241 nodes uniform in z = atanh(rho) ...)
Z_EDGE_INTERVALS, Z_EDGE_SPLIT = 8, 4   # (... with the outer 8 intervals at each end split in 4: 289 nodes)
GRID_LL_TOL = 1e-3                 # (registered: |interpolation - exact| of a group objective / its pairs, log units)
GRID_RHO_TOL = 1e-3                # (registered: a refit shift above this, after the local refinement, is FLAGGED)
MIN_KNOT = 1e-6                    # (inserted knots: at least this far apart in z, from each other and the grid)
E_MAX = 40.0                       # (log_rect's admissible domain: finite standardized endpoints |e| <= E_MAX)
W_MIN = 1e-6                       # (... and standardized interval widths >= W_MIN)
TRUNC_MARGIN = 12.0                # (an infinite outer end is first truncated at +-(E_MAX + TRUNC_MARGIN))
DROP = 50.0                        # (a restricted range: where log f >= its max - DROP)
RESTRICT_PANELS = 16               # (a finite interval needing more panels than this is restricted too)
OMIT_TOL = 1e-14                   # (the omitted mass beyond the integration range, relative: else refused)
PANEL_EFOLDS = 2.0                 # (log_rect: e-folds of the log integrand per Gauss-Legendre panel, by a VALID bound)
MAX_PANELS = 4096                  # (beyond: refused, never capped)
TINY_W = 1e-4                      # (_log_iprob: narrower intervals by the corrected midpoint rule)
LOG_RECT_TOL = 1e-8                # (registered: max |log_rect - reference| on the registered test set)
MULTI_START = 16                   # (the constrained fit's registered quasi-random (Halton) starts)
START_TOL = 1e-4                   # (log-likelihood units: the runs counted as reaching the best value)
PARAM_TOL = 1e-3                   # (those runs must agree in every group value within this)
MIN_AGREE = 3                      # (at least this many runs must reach the best value)
KKT_TOL = 1e-6                     # (the barrier problem's KKT residual: ||gradient||_inf / max(1, ||grad L||_inf))
MU_FINAL = 1e-7                    # (the last barrier weight: its duality gap, 25 mu, is far below START_TOL)
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
    return collect_with_age_diagnostics(study, design, plan_path, declared_missing)[0]


def collect_with_age_diagnostics(study, design, plan_path, declared_missing=()):
    """collect's observations (the same bytes) and, separately versioned, the collected cells'
    age-stratified diagnostics (D8 v2 rule 48; store.age_diagnostics_doc). A /3 bundle without its
    complete age summary is refused; a /1 or /2 bundle's diagnostics are explicitly unavailable."""
    import store
    rows, plan_sha = bind_plan(design, plan_path)
    _, cells = store.load_index(study)
    obs, ages = [], []
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
        try:
            ages.append(store.age_diagnostics_entry(cid, b))
        except store.StoreError as e:
            raise NoiseBankError(str(e))
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
    doc = {"schema": OBS_SCHEMA, "design_sha256": rqlib.canonical_sha(design), "plan_sha256": plan_sha,
           "missing": missing, "observations": obs}
    return doc, store.age_diagnostics_doc(doc, ages)


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

# ---- tail-stable log probabilities on a REGISTERED ADMISSIBLE DOMAIN (Codex #72 r2 P1, r3 P2-1)
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


def _logphi(x):
    return -0.5 * x * x - 0.5 * math.log(2 * math.pi)


def _log_iprob(a, b):
    """log P(a < Z < b) (a < b) without cancellation: a narrow interval (b - a < TINY_W) by the corrected
    midpoint rule log phi(m) + log w + log1p(w^2 (m^2 - 1) / 24); otherwise the difference of the two tails
    on the side of the smaller tail as log Q(a) + log(-expm1(log Q(b) - log Q(a))); the central case as
    log1p(-(Q(b) + Q(-a))). -inf only for an empty interval."""
    import numpy as np
    a, b = np.broadcast_arrays(np.asarray(a, float), np.asarray(b, float))
    out = np.full(a.shape, -np.inf)
    ok = b > a
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        w = b - a
        tiny = ok & np.isfinite(w) & (w < TINY_W)
        m = 0.5 * (a + b)
        out[tiny] = _logphi(m[tiny]) + np.log(w[tiny]) + np.log1p(w[tiny] ** 2 * (m[tiny] ** 2 - 1) / 24.0)
        rest = ok & ~tiny
        up = rest & (a > 0)
        dn = rest & (b < 0) & ~up
        mid = rest & ~up & ~dn
        if up.any():
            la, lb = _logQ(a[up]), _logQ(b[up])
            out[up] = la + np.log(-np.expm1(lb - la))
        if dn.any():
            lb, la = _logQ(-b[dn]), _logQ(-a[dn])
            out[dn] = lb + np.log(-np.expm1(la - lb))
        if mid.any():
            out[mid] = np.log1p(-(_Q(b[mid]) + _Q(-a[mid])))
    return out


def check_domain(l1, h1, l2, h2, r):
    """THE REGISTERED ADMISSIBLE DOMAIN of log_rect (what the bank produces; anything else is refused):
    |rho| <= RHO_MAX; every finite standardized endpoint within +-E_MAX (infinite ends only for the
    counts 0 and N); every interval at least W_MIN wide."""
    import numpy as np
    if not abs(r) <= RHO_MAX:
        raise NoiseBankError(f"log_rect: rho {r} outside the registered box")
    for lo, hi in ((l1, h1), (l2, h2)):
        bad = (np.isfinite(lo) & (np.abs(lo) > E_MAX)) | (np.isfinite(hi) & (np.abs(hi) > E_MAX)) | \
            (lo == np.inf) | (hi == -np.inf) | ~(hi - lo >= W_MIN)
        if bad.any():
            k = int(np.flatnonzero(bad)[0])
            raise NoiseBankError(f"log_rect: an interval outside the registered domain ([{lo[k]}, {hi[k]}]: "
                                 f"|e| <= {E_MAX}, width >= {W_MIN})")


def _cond(x, il, ih, r, s):
    """log P(il < Y < ih | X = x) and E[Z | a < Z < b] (the truncated mean, from which the log integrand's
    exact slope is -x + (r / s) E)."""
    import numpy as np
    a, b = (il - r * x) / s, (ih - r * x) / s
    lg = _log_iprob(a, b)
    with np.errstate(invalid="ignore", over="ignore"):
        pa = np.where(np.isfinite(a), np.exp(_logphi(np.where(np.isfinite(a), a, 0.0)) - lg), 0.0)
        pb = np.where(np.isfinite(b), np.exp(_logphi(np.where(np.isfinite(b), b, 0.0)) - lg), 0.0)
    return lg, pa - pb


def _logf(x, il, ih, r, s):
    lg, e = _cond(x, il, ih, r, s)
    return _logphi(x) + lg, -x + (r / s) * e


def _bisect(fn, lo, hi, iters=80):
    """Vectorized bisection for the root of a decreasing fn on [lo, hi] (fn(lo) > 0 > fn(hi))."""
    import numpy as np
    lo, hi = lo.copy(), hi.copy()
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        pos = fn(mid) > 0
        lo, hi = np.where(pos, mid, lo), np.where(pos, hi, mid)
    return 0.5 * (lo + hi)


def log_rect(l1, h1, l2, h2, r, chunk=20000):
    """log P(l1 < X < h1, l2 < Y < h2) for the standard bivariate normal with correlation r, on the
    REGISTERED ADMISSIBLE DOMAIN (check_domain; refused outside), WITHOUT differencing tail probabilities:
    the conditional integral over the outer variable (the narrower interval) of f(x) = phi(x) P(l < Y < h |
    x), log-concave, in log space by composite 20-point Gauss-Legendre.
      - A half-infinite outer interval is truncated at +-(E_MAX + TRUNC_MARGIN), then (like a finite interval
        that would need more than RESTRICT_PANELS panels: a steep integrand) restricted to where
        log f >= max log f - DROP (the mode and the cut points by bisection on the exact slope); the mass
        beyond each cut is bounded by f(cut) / |slope(cut)| (log-concavity) and must be below OMIT_TOL x the
        result, else the rectangle is REFUSED.
      - Panels: the power of two >= width x S / PANEL_EFOLDS with S a VALID bound on the log integrand's
        |slope| over the range: the integrand is log-concave, so the exact slopes at the range's two ends
        bound it (falling back to the Mills-ratio bound |x| + (|r| / s)(max finite |inner endpoint| + 1) where
        an endpoint slope is not finite). More than MAX_PANELS is REFUSED, never capped.
    Validated against an independent reference (math.erfc and the asymptotic tail series; a golden-section
    mode; a FIXED 8,000-interval composite Simpson rule in log space) on the registered test set: max |error| <=
    LOG_RECT_TOL."""
    import numpy as np
    l1, h1, l2, h2 = (np.asarray(v, float).ravel() for v in (l1, h1, l2, h2))
    check_domain(l1, h1, l2, h2, r)
    w1, w2 = h1 - l1, h2 - l2
    swap = w2 < w1
    lo, hi = np.where(swap, l2, l1), np.where(swap, h2, h1)
    il, ih = np.where(swap, l1, l2), np.where(swap, h1, h2)
    s = math.sqrt((1.0 - r) * (1.0 + r))
    T = E_MAX + TRUNC_MARGIN
    lo_fin, hi_fin = np.isfinite(lo), np.isfinite(hi)
    lo, hi = np.where(lo_fin, lo, -T), np.where(hi_fin, hi, T)
    a_, b_ = lo.copy(), hi.copy()

    def restrict(k):
        """The integration range where log f >= its maximum - DROP (log-concave: the mode and the cut points
        by bisection on the exact slope)."""
        def slope(x):
            return _logf(x, il[k], ih[k], r, s)[1]
        s_lo, s_hi = slope(lo[k]), slope(hi[k])
        mode = np.where(s_lo <= 0, lo[k], np.where(s_hi >= 0, hi[k], _bisect(slope, lo[k], hi[k])))
        fm = _logf(mode, il[k], ih[k], r, s)[0]

        def drop(x):
            return _logf(x, il[k], ih[k], r, s)[0] - (fm - DROP)
        fl, fh = drop(lo[k]), drop(hi[k])
        a_[k] = np.where(fl >= 0, lo[k], _bisect(lambda x: -drop(x), lo[k], mode))
        b_[k] = np.where(fh >= 0, hi[k], _bisect(drop, mode, hi[k]))

    def panels_needed():
        """The log integrand is CONCAVE, so its |slope| over [a, b] is largest at an endpoint: the exact
        endpoint slopes bound it (the Mills-ratio bound |x| + (|r| / s)(max |inner endpoint| + 1) where a slope
        is not finite)."""
        S = np.zeros(len(lo))
        for x in (a_, b_):
            sl = np.abs(_logf(x, il, ih, r, s)[1])
            za, zb = (il - r * x) / s, (ih - r * x) / s
            mfin = np.maximum(np.where(np.isfinite(za), np.abs(za), 0.0), np.where(np.isfinite(zb), np.abs(zb), 0.0))
            S = np.maximum(S, np.where(np.isfinite(sl), sl, np.abs(x) + abs(r) / s * (mfin + 1.0)))
        return np.maximum(1.0, (b_ - a_) * S / PANEL_EFOLDS)
    restricted = ~(lo_fin & hi_fin)                     # (a half-infinite outer interval: always restricted)
    if restricted.any():
        restrict(np.flatnonzero(restricted))
    need = panels_needed()
    wide = ~restricted & (need > RESTRICT_PANELS)       # (a finite interval the integrand crosses steeply)
    if wide.any():
        restrict(np.flatnonzero(wide))
        restricted |= wide
        need = panels_needed()
    t, w = _gl20()
    if np.any(need > MAX_PANELS):
        raise NoiseBankError(f"log_rect: a rectangle needs more than {MAX_PANELS} panels (refused, not capped)")
    panels = 2 ** np.ceil(np.log2(need)).astype(int)
    out = np.empty(len(lo))
    for n in np.unique(panels):
        sel = np.flatnonzero(panels == n)
        u = ((np.arange(n)[:, None] + (t[None, :] + 1) / 2) / n).ravel()
        lw = np.log(np.tile(w, n) / (2 * n))
        step = max(1, chunk // len(u))
        for c0 in range(0, len(sel), step):
            k = sel[c0:c0 + step]
            span = (b_[k] - a_[k])[:, None]
            x = a_[k][:, None] + span * u[None, :]
            li = _log_iprob((il[k][:, None] - r * x) / s, (ih[k][:, None] - r * x) / s)
            v = lw[None, :] + np.log(span) + _logphi(x) + li
            mx = np.max(v, axis=1)
            out[k] = mx + np.log(np.sum(np.exp(v - mx[:, None]), axis=1))
    if restricted.any():                               # (the omitted-mass bound, relative)
        k = np.flatnonzero(restricted)
        om = np.full(len(k), -np.inf)
        for cut, edge, fin in ((a_[k], lo[k], lo_fin[k]), (b_[k], hi[k], hi_fin[k])):
            f_, sl = _logf(cut, il[k], ih[k], r, s)
            inner = ~(fin & (cut == edge))             # (a truncated infinite end is never a true edge)
            with np.errstate(divide="ignore"):
                om = np.logaddexp(om, np.where(inner, f_ - np.log(np.maximum(np.abs(sl), 1e-300)), -np.inf))
        if np.any(om - out[k] > math.log(OMIT_TOL)):
            raise NoiseBankError("log_rect: the omitted mass beyond the integration range exceeds OMIT_TOL (refused)")
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


def z_nodes(m=Z_INTERVALS):
    """The registered grid in z = atanh(rho): m + 1 uniform nodes over [-Z_MAX, Z_MAX], the outer
    Z_EDGE_INTERVALS intervals at each end split in Z_EDGE_SPLIT (the log likelihood bends like
    1 / (1 - rho) there; Codex #72 r3's (-7, 7) thin rectangle)."""
    import numpy as np
    if not isinstance(m, int) or m < 2 * Z_EDGE_INTERVALS + 4:
        raise NoiseBankError(f"the grid needs at least {2 * Z_EDGE_INTERVALS + 4} intervals (got {m!r})")
    base = np.linspace(-Z_MAX, Z_MAX, m + 1)
    h = base[1] - base[0]
    extra = [base[i] + h * j / Z_EDGE_SPLIT for i in list(range(Z_EDGE_INTERVALS)) + list(range(m - Z_EDGE_INTERVALS, m))
             for j in range(1, Z_EDGE_SPLIT)]
    return np.unique(np.concatenate([base, np.array(extra)]))


def rho_grid(m=Z_INTERVALS):
    import numpy as np
    return np.tanh(z_nodes(m))


def _pair_blocks(A, U, G):
    """Per group: the pair blocks (standardized bounds, source keys) and the keys."""
    import numpy as np
    out = {}
    for g in GROUPS:
        keys, blocks = {}, []
        for c1, r1, c2, r2, prey_w, pred_w in G[g]:
            l1, h1 = _std_bounds(A, U, c1, r1)
            l2, h2 = _std_bounds(A, U, c2, r2)
            kp, kq = np.stack(prey_w, 1), np.stack(pred_w, 1)
            kid = np.array([keys.setdefault((tuple(sorted({int(x) for x in kp[i]})),
                                             tuple(sorted({int(x) for x in kq[i]}))), len(keys))
                            for i in range(len(r1))], int)
            blocks.append((l1.ravel(), h1.ravel(), l2.ravel(), h2.ravel(), np.repeat(kid, l1.shape[1])))
        out[g] = (list(keys), blocks)
    return out


def exact_column(blocks, nkeys, r, chunk=40000):
    """The EXACT per-key summed contributions at one rho (and the deep-tail count)."""
    import numpy as np
    col = np.zeros(nkeys)
    deep = 0
    for l1, h1, l2, h2, kid in blocks:
        for c0 in range(0, len(l1), chunk):
            sl = slice(c0, c0 + chunk)
            base = _log_iprob(l1[sl], h1[sl]) + _log_iprob(l2[sl], h2[sl])
            lp = log_rect(l1[sl], h1[sl], l2[sl], h2[sl], float(r))
            if not (np.all(np.isfinite(lp)) and np.all(np.isfinite(base))):
                raise NoiseBankError(f"a non-finite contribution at rho {r:.4f}")
            deep += int(np.sum(lp < -700.0))
            col += np.bincount(kid[sl], weights=lp - base, minlength=nkeys)
    return col, deep


def group_tables(A, U, G, m=Z_INTERVALS):
    """Stage 2's exact contributions: per group and per bootstrap source key (DISTINCT worlds per role), the
    summed dependence contributions log P(both; rho) - log P(1) - log P(2) at every grid node, the pair blocks
    (kept for the certification) -> {g: {"keys", "z" (nodes), "T" (keys x nodes), "pairs", "npk" (pairs per
    key), "deep_tail", "blocks"}}."""
    import numpy as np
    zn = z_nodes(m)
    pb = _pair_blocks(A, U, G)
    out = {}
    for g in GROUPS:
        keys, blocks = pb[g]
        T = np.zeros((len(keys), len(zn)))
        deep = 0
        for j, z in enumerate(zn):
            T[:, j], d = exact_column(blocks, len(keys), math.tanh(z))
            deep += d
        npk = np.zeros(len(keys))
        for *_, kid in blocks:
            npk += np.bincount(kid, minlength=len(keys))
        out[g] = {"keys": keys, "z": zn.copy(), "T": T, "pairs": int(npk.sum()), "npk": npk, "deep_tail": deep,
                  "blocks": blocks}
    return out


_SPL = {}


def _spline_K(zn):
    """The not-a-knot cubic spline's second derivatives as a linear map of the node values: M = K y
    (cached per node set)."""
    import numpy as np
    key = zn.tobytes()
    if key not in _SPL:
        n = len(zn)
        h = np.diff(zn)
        A = np.zeros((n, n))
        B = np.zeros((n, n))
        for i in range(1, n - 1):
            A[i, i - 1], A[i, i], A[i, i + 1] = h[i - 1], 2 * (h[i - 1] + h[i]), h[i]
            B[i, i - 1], B[i, i], B[i, i + 1] = 6 / h[i - 1], -6 / h[i - 1] - 6 / h[i], 6 / h[i]
        A[0, 0], A[0, 1], A[0, 2] = h[1], -(h[0] + h[1]), h[0]                 # (not-a-knot)
        A[-1, -3], A[-1, -2], A[-1, -1] = h[-1], -(h[-2] + h[-1]), h[-2]
        _SPL[key] = np.linalg.solve(A, B)
        if len(_SPL) > 64:
            _SPL.pop(next(iter(_SPL)))
    return _SPL[key]


def _interp(zn, vals, z):
    """The not-a-knot cubic spline in z through the node values (C2: a smooth objective for Newton) and its
    ANALYTIC first and second z-derivatives, vectorized over z in [zn[0], zn[-1]]."""
    import numpy as np
    z = np.atleast_1d(np.asarray(z, float))
    y = np.asarray(vals, float)
    M = _spline_K(zn) @ y
    i = np.clip(np.searchsorted(zn, z, side="right") - 1, 0, len(zn) - 2)
    z0, z1 = zn[i], zn[i + 1]
    h = z1 - z0
    a, b = z1 - z, z - z0
    c0, c1 = y[i] / h - M[i] * h / 6, y[i + 1] / h - M[i + 1] * h / 6
    f = M[i] * a ** 3 / (6 * h) + M[i + 1] * b ** 3 / (6 * h) + c0 * a + c1 * b
    d1 = -M[i] * a ** 2 / (2 * h) + M[i + 1] * b ** 2 / (2 * h) - c0 + c1
    d2 = M[i] * a / h + M[i + 1] * b / h
    return f, d1, d2


def obj_rho(zn, vals, rho):
    """A group objective at rho (inside the registered box): value and ANALYTIC rho-derivatives (chain rule,
    with the 2 rho l_z term: l_rr = l_zz z_r^2 + l_z z_rr)."""
    import numpy as np
    rho = np.atleast_1d(np.asarray(rho, float))
    if np.any(np.abs(rho) > RHO_MAX + 1e-12):
        raise NoiseBankError("a correlation outside the registered box")
    rho = np.clip(rho, -RHO_MAX, RHO_MAX)
    z = np.arctanh(rho)
    f, fz, fzz = _interp(zn, vals, z)
    zr = 1.0 / (1.0 - rho * rho)
    zrr = 2.0 * rho * zr * zr
    return f, fz * zr, fzz * zr * zr + fz * zrr


def _argmax(zn, vals, sub=40):
    """The interpolant's maximizer: a dense search in z, then Newton on the analytic derivatives inside the
    bracket -> (rho, value)."""
    import numpy as np
    fine = np.unique(np.concatenate([np.linspace(zn[i], zn[i + 1], sub + 1) for i in range(len(zn) - 1)]))
    f = _interp(zn, vals, fine)[0]
    k = int(np.argmax(f))
    z = float(fine[k])
    lo, hi = float(fine[max(k - 1, 0)]), float(fine[min(k + 1, len(fine) - 1)])
    for _ in range(50):
        _, d1, d2 = _interp(zn, vals, np.array([z]))
        if not d2[0] < 0:
            break
        zn_ = min(max(z - float(d1[0] / d2[0]), lo), hi)
        if abs(zn_ - z) < 1e-14:
            break
        z = zn_
    fz = float(_interp(zn, vals, np.array([z]))[0][0])
    if fz < float(f[k]):
        z, fz = float(fine[k]), float(f[k])
    return math.tanh(z), fz


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
    import numpy as np
    base = _mats(np.zeros(9))
    out = []
    for i in range(9):
        e = np.zeros(9)
        e[i] = 1.0
        out.append([a - b for a, b in zip(_mats(e), base)])
    return out


def _strict(x):
    import numpy as np
    return np.all(np.abs(x) < RHO_MAX) and all(np.min(np.linalg.eigvalsh(M)) > 1e-12 for M in _mats(x))


def _interior(objs, x0, mu0=1.0):
    """Maximize sum_g l_g(rho_g) over {three LMIs PD, |rho_g| < RHO_MAX}: log-barrier interior point, damped
    Newton (a positive-definite, regularized model) on the ANALYTIC interpolant derivatives, every evaluation
    strictly inside -> (x, L, converged, the KKT residual at the final mu, the final mu). A centring stage ends
    when its KKT residual meets the stage tolerance, or (an internal exit) when the Newton decrement vanishes
    (<= 1e-24 |phi|); ACCEPTANCE is decided by the final KKT gate alone, never by the decrement."""
    import numpy as np
    dM = _dmats()
    a2 = RHO_MAX ** 2

    def L(x):
        return sum(float(obj_rho(*objs[g], x[i])[0][0]) for i, g in enumerate(GROUPS))

    def phi(x, mu):
        if not _strict(x):
            return math.inf
        b = -sum(np.linalg.slogdet(M)[1] for M in _mats(x)) - float(np.sum(np.log(a2 - x * x)))
        return -L(x) + mu * b

    def grad_hess(x, mu):
        g = np.zeros(9)
        H = np.zeros((9, 9))
        for i, gr in enumerate(GROUPS):
            _, d1, d2 = obj_rho(*objs[gr], x[i])
            g[i], H[i, i] = -float(d1[0]), -float(d2[0])
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
    def kkt(x, mu):
        """The barrier problem's KKT (stationarity) residual: ||grad(-L + mu B)||_inf scaled by
        max(1, ||grad L||_inf); it does not depend on the Hessian's inertia (Codex #72 r4 P2-1)."""
        g, _ = grad_hess(x, mu)
        gl = np.array([float(obj_rho(*objs[gr], x[i])[1][0]) for i, gr in enumerate(GROUPS)])
        return float(np.max(np.abs(g))) / max(1.0, float(np.max(np.abs(gl))))
    x = np.array(x0, float)
    if not _strict(x):
        raise NoiseBankError("the interior-point start is not strictly feasible")
    mu = mu0
    while True:
        final = mu <= MU_FINAL
        tol = KKT_TOL if final else max(KKT_TOL, 0.1 * mu)   # (centring: loose on the path, tight at the end)
        ok = False
        for _ in range(300):
            g, H = grad_hess(x, mu)
            lam = 0.0
            while True:                                # (a POSITIVE-DEFINITE (regularized) Newton model)
                try:
                    C = np.linalg.cholesky(H + lam * np.eye(9))
                    step = -np.linalg.solve(C.T, np.linalg.solve(C, g))
                    if np.all(np.isfinite(step)):
                        break
                except np.linalg.LinAlgError:
                    pass
                lam = max(2 * lam, 1e-8 * (1 + float(np.max(np.abs(np.diag(H))))))
            dec = -float(g @ step)
            f0 = phi(x, mu)
            if kkt(x, mu) <= tol or dec <= 1e-24 * max(1.0, abs(f0)):   # (stationary: the GRADIENT)
                ok = True
                break
            t = 1.0
            while t > 1e-14 and not phi(x + t * step, mu) <= f0 - 1e-4 * t * dec:
                t *= 0.5
            if t <= 1e-14 or float(np.max(np.abs(t * step))) <= 1e-15 * max(1.0, float(np.max(np.abs(x)))):
                ok = kkt(x, mu) <= tol                   # (no representable progress left: float-limited)
                break
            x = x + t * step
        if not ok:
            return x, L(x), False, math.inf, mu
        if final:
            break
        mu = max(mu / 5.0, MU_FINAL)
    return x, L(x), True, kkt(x, mu), mu


def _halton(n, dims):
    """The first n points of the Halton sequence (primes 2, 3, 5, ...), skipping the origin."""
    primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29][:dims]
    out = []
    for i in range(1, n + 1):
        row = []
        for p in primes:
            f, r, k = 1.0, 0.0, i
            while k:
                f /= p
                r += f * (k % p)
                k //= p
            row.append(r)
        out.append(row)
    return out


def _starts(un, k=MULTI_START):
    """The registered quasi-random strictly feasible starts, spread across the feasible set: Halton points
    mapped through the spherical-angle parametrization (_theta_map: every point PSD), each shrunk toward the
    central point (shares 1/3, correlations 0) until strictly inside the box and the LMIs."""
    import numpy as np
    c0 = np.array([1 / 3, 1 / 3, 0, 1 / 3, 1 / 3, 0, 0, 0, 0], float)
    out = []
    for h in _halton(k, 9):
        th = [math.pi * h[0], math.pi * h[1], math.pi * h[2], math.pi * h[3], math.pi * (h[4] - 0.5),
              math.pi * (h[5] - 0.5), math.pi * (h[6] - 0.5), 0.5 * math.pi * h[7], 2 * math.pi * h[8]]
        r = _theta_map(th)
        x = np.array([r[g] for g in GROUPS], float)
        t = 1.0
        while not _strict(c0 + t * (x - c0)) and t > 1e-6:
            t *= 0.9
        out.append(c0 + t * (x - c0))
    return out


def fit_dependence(objs, pairs=None):
    """Stage 2 from per-group objectives {g: (z nodes, values)} -> {"rho", "fit": "unconstrained" |
    "constrained", "loglik", "SigmaR", "SigmaD", "SigmaE", "unconstrained", "problems", "starts", "at_box"}.
    The constrained branch (Codex #72 r3 P2-3): the interior-point fit (_interior) from MULTI_START = 16
    registered quasi-random strictly feasible starts (_starts); ACCEPTED only when at least MIN_AGREE runs
    reach the best log likelihood within START_TOL, all of those agree in every group value within
    PARAM_TOL, and the best run's KKT residual (the scaled gradient of the barrier problem) is within KKT_TOL;
    otherwise
    REFUSED. "Multi-start validated, not a global certificate": the problem is not concave. A group value on
    the registered box |rho| = RHO_MAX is FLAGGED (at_box)."""
    import numpy as np
    un = {g: _argmax(*objs[g])[0] for g in GROUPS}
    SR, SD, SE, feas, prob = components_of(un)
    starts = None
    if feas:
        rho, how = un, "unconstrained"
    else:
        runs = []
        for x0 in _starts(un):
            x, Lx, ok, resid, mu = _interior(objs, x0)
            if ok:
                runs.append((Lx, x, resid))
        if not runs:
            raise NoiseBankError("the constrained fit did not converge from any start")
        Lbest = max(v for v, _, _ in runs)
        top = [(v, x, rs) for v, x, rs in runs if v >= Lbest - START_TOL]
        spread = max(float(np.max(np.abs(x - top[0][1]))) for _, x, _ in top)
        best = max(top, key=lambda t: t[0])
        starts = {"starts": MULTI_START, "converged": len(runs), "reaching_best": len(top),
                  "parameter_spread": spread, "kkt_residual": best[2],
                  "label": "multi-start validated, not a global certificate"}
        if len(top) < MIN_AGREE or spread > PARAM_TOL or not best[2] <= KKT_TOL:
            raise NoiseBankError(f"the constrained fit is refused: {len(top)} runs reach the best value, their "
                                 f"parameters spread {spread:.3g}, KKT residual {best[2]:.3g}")
        rho, how = {g: float(best[1][i]) for i, g in enumerate(GROUPS)}, "constrained"
        SR, SD, SE, feas2, prob2 = components_of(rho)
        if not feas2:
            raise NoiseBankError(f"the constrained fit is infeasible: {prob2}")
    ll = sum(float(obj_rho(*objs[g], rho[g])[0][0]) for g in GROUPS)
    at_box = sorted(g for g in GROUPS if abs(rho[g]) >= RHO_MAX - 1e-6)
    return {"rho": rho, "fit": how, "loglik": ll, "SigmaR": SR, "SigmaD": SD, "SigmaE": SE,
            "unconstrained": un, "problems": prob, "starts": starts, "at_box": at_box}


def identified(zn, vals, rho, npairs):
    """THE IDENTIFICATION RULE (point estimate and every bootstrap refit alike): the analytic curvature per
    (weighted) pair at the group maximum, -l_rr / pairs >= INFO_MIN; a maximum on the registered box is
    flagged and identified by its one-sided slope instead (|l_r| / pairs >= INFO_MIN: the likelihood still
    rises into the box). -> (ok, curvature per pair, at_box)."""
    _, d1, d2 = obj_rho(zn, vals, rho)
    at_box = abs(rho) >= RHO_MAX - 1e-6
    per = (abs(float(d1[0])) if at_box else -float(d2[0])) / max(npairs, 1e-300)
    return per >= INFO_MIN, per, at_box


def validate_grid(tab, fitrho):
    """LOCAL OBJECTIVE-VALUE VALIDATION (Codex #72 r3 P2-2, narrowed by the coordinator after r4): per group,
    the EXACT objective at the fitted rho and at the off-grid midpoints of its bracket and both neighbours,
    against the interpolant; where a miss exceeds GRID_LL_TOL per pair, those exact columns are inserted as
    nodes (candidates deduplicated against each other and the grid at MIN_KNOT in z; an invalid grid is a
    NoiseBankError) -> (inserted?, the worst miss per pair). This validates the objective VALUES locally; it
    is not a global certificate."""
    import numpy as np
    worst, inserted = 0.0, False
    for g in GROUPS:
        t = tab[g]
        zn = t["z"]
        z = math.atanh(max(-RHO_MAX, min(RHO_MAX, fitrho[g])))
        k = int(np.clip(np.searchsorted(zn, z, side="right") - 1, 0, len(zn) - 2))
        cand = sorted({round(v, 15) for v in [z] + [0.5 * (zn[i] + zn[i + 1]) for i in (k - 1, k, k + 1)
                                                     if 0 <= i < len(zn) - 1]})
        pts = []
        for zz in cand:
            if np.min(np.abs(zn - zz)) < MIN_KNOT or (pts and zz - pts[-1] < MIN_KNOT):
                continue
            pts.append(zz)
        newz, newc = [], []
        for zz in pts:
            col, _ = exact_column(t["blocks"], len(t["keys"]), math.tanh(zz))
            miss = abs(float(_interp(zn, t["T"].sum(axis=0), np.array([zz]))[0][0]) - float(col.sum())) / t["pairs"]
            worst = max(worst, miss)
            if miss > GRID_LL_TOL:
                newz.append(zz)
                newc.append(col)
        if newz:
            inserted = True
            z_all = np.concatenate([zn, np.array(newz)])
            T_all = np.hstack([t["T"], np.array(newc).T])
            o = np.argsort(z_all)
            z_all, T_all = z_all[o], T_all[:, o]
            if not np.all(np.diff(z_all) >= MIN_KNOT):
                raise NoiseBankError(f"{g}: the refined grid has knots closer than {MIN_KNOT}")
            t["z"], t["T"] = z_all, T_all
    return inserted, worst


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
    """x > 0 with trigamma(x) = y (> 0, finite; trigamma is decreasing), in LOG space: bisection on log x
    inside a bracket grown from the asymptotic guess; for very small y (x beyond 1e15) the asymptotic
    inverse x = 1 / y + 1/2 (relative error below 1e-15) is used directly, so nothing overflows; a result
    beyond the float range is a NoiseBankError (the caller reports full pooling)."""
    if not y > 0 or not math.isfinite(y):
        raise NoiseBankError(f"inv_trigamma needs a positive finite value (got {y!r})")
    if y < 1e-15:
        x = 1.0 / y + 0.5
        if not math.isfinite(x):
            raise NoiseBankError("inv_trigamma: the result overflows")
        return x
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
    try:
        return dict(rec, status="estimated", nu0=2.0 * inv_trigamma(excess))
    except NoiseBankError:
        return dict(rec, status="full_pooling", note="nu0 beyond the float range: full pooling")


# ================================================================== the estimate
def pick_weights(keys, m, mp):
    """The registered bootstrap weights (Codex #72 r2 P2-4, the coordinator's ruling): a WORLD-MULTIPLICITY
    WEIGHTED LIKELIHOOD. Each pair's weight is the product of the prey-role multiplicities m over the DISTINCT
    prey worlds of its sources and of the predator-role multiplicities mp over its DISTINCT predator worlds."""
    import numpy as np
    return np.array([math.prod(int(m[a]) for a in set(kp)) * math.prod(int(mp[b]) for b in set(kq))
                     for kp, kq in keys], float)


BOOT_NAMES = ("R_CC", "R_SS", "R_CS", "R_CF", "R_SF", "D_CC", "D_SS", "D_CS", "E_CC", "E_SS", "E_CS")


def _entries(f):
    SR, SD, SE = f["SigmaR"], f["SigmaD"], f["SigmaE"]
    return [SR[0, 0], SR[1, 1], SR[0, 1], SR[0, 2], SR[1, 2], SD[0, 0], SD[1, 1], SD[0, 1], SE[0, 0], SE[1, 1], SE[0, 1]]


def bootstrap(tab, n_worlds, boot, seed):
    """The registered uncertainty procedure -> (draws x BOOT_NAMES, failed draws, of which identification
    rejections). Each weighted refit applies THE SAME identification rule as the point estimate (identified,
    with the WEIGHTED pair counts); a group without weight, an unidentified group or a refused fit is a failed
    draw (Codex #72 r3 P2-5)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    out, failed, unident = [], 0, 0
    for _ in range(boot):
        mm = np.bincount(rng.integers(0, n_worlds, n_worlds), minlength=n_worlds)
        mp = np.bincount(rng.integers(0, n_worlds, n_worlds), minlength=n_worlds)
        objs, pairs, bad = {}, {}, False
        for g in GROUPS:
            w = pick_weights(tab[g]["keys"], mm, mp)
            if not w.any():
                bad = True
                break
            objs[g] = (tab[g]["z"], w @ tab[g]["T"])
            pairs[g] = float(w @ tab[g]["npk"])
            r_hat, _ = _argmax(*objs[g])
            if not identified(*objs[g], r_hat, pairs[g])[0]:
                bad = True
                unident += 1
                break
        if bad:
            failed += 1
            continue
        try:
            out.append(_entries(fit_dependence(objs, pairs)))
        except NoiseBankError:
            failed += 1
    return np.array(out, float).reshape(len(out), len(BOOT_NAMES)), failed, unident


def interval_record(D, failed, boot, unident=0):
    """Codex #72 r2 P2-5 / r3 P2-5: the failed draws (identification rejections included) are counted; the
    interval is UNAVAILABLE (its own status) beyond BOOT_FAIL_MAX of the draws, otherwise reported with the
    failure rate, labelled approximate and conditional on identification."""
    import numpy as np
    rate = failed / boot if boot else 1.0
    rec = {"draws": boot, "failed": failed, "identification_rejections": unident, "failure_rate": rate,
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
    """One horizon: the usable channels, the s(mu) curves and nu0, the nine groups (identification), the
    components (or "unavailable" with reasons) with the grid VALIDATED LOCALLY at the fit, the registered uncertainty
    procedure."""
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
    try:
        tab = group_tables(A, U, G, m)
        objs = {g: (tab[g]["z"], tab[g]["T"].sum(axis=0)) for g in GROUPS}
        groups = {}
        for g in GROUPS:
            r_hat, _ = _argmax(*objs[g])
            ok, per, at_box = identified(*objs[g], r_hat, tab[g]["pairs"])
            groups[g] = {"pairs": tab[g]["pairs"], "rho_max": r_hat, "curvature_per_pair": per, "at_box": at_box,
                         "deep_tail": tab[g]["deep_tail"]}
            if not ok:
                reasons.append(f"{g} is unidentified ({'one-sided slope' if at_box else 'curvature'} per pair "
                               f"{per:.3g} < {INFO_MIN})")
        if reasons:
            rec.update(status="unavailable", reasons=reasons, components=None, bootstrap=None, groups=groups)
            return rec
        fit = fit_dependence(objs, {g: tab[g]["pairs"] for g in GROUPS})
        inserted, worst = validate_grid(tab, fit["rho"])
        shift = 0.0
        if inserted:                                   # (ONE refit on the locally refined table: its shift reported)
            objs = {g: (tab[g]["z"], tab[g]["T"].sum(axis=0)) for g in GROUPS}
            for g in GROUPS:                           # (Codex #72 r5: identification re-checked on the REFINED table)
                r_hat, _ = _argmax(*objs[g])
                ok, per, at_box = identified(*objs[g], r_hat, tab[g]["pairs"])
                groups[g].update(rho_max=r_hat, curvature_per_pair=per, at_box=at_box)
                if not ok:
                    reasons.append(f"{g} is unidentified on the refined grid ({'one-sided slope' if at_box else 'curvature'} "
                                   f"per pair {per:.3g} < {INFO_MIN})")
            if reasons:
                rec.update(status="unavailable", reasons=reasons, components=None, bootstrap=None, groups=groups)
                return rec
            refit = fit_dependence(objs, {g: tab[g]["pairs"] for g in GROUPS})
            shift = max(abs(refit["rho"][g] - fit["rho"][g]) for g in GROUPS)
            fit = refit
        for g in GROUPS:
            groups[g]["nodes"] = int(len(tab[g]["z"]))
    except NoiseBankError as e:
        rec.update(status="unavailable", reasons=[str(e)], components=None, bootstrap=None)
        return rec
    rec["groups"] = groups
    rec["grid_validation"] = {"label": "local objective-value validation (not a global certificate)",
                              "worst_miss_per_pair": worst, "tolerance": GRID_LL_TOL, "refined": inserted,
                              "refit_shift": shift, "shift_flag": shift > GRID_RHO_TOL}
    rec["components"] = {"SigmaR": fit["SigmaR"].tolist(), "SigmaD": fit["SigmaD"].tolist(),
                         "SigmaE": fit["SigmaE"].tolist(), "fit": fit["fit"], "loglik": fit["loglik"],
                         "unconstrained_problems": fit["problems"], "multistart": fit["starts"], "at_box": fit["at_box"],
                         "box": f"|rho| <= {RHO_MAX}: a registered numerical restriction (a share above it cannot be fitted)",
                         "SigmaR_FF": {"value": float(fit["SigmaR"][2, 2]), "status": "convention",
                                       "rule": "the minimal feasible free row variance v' A^+ v: one control per "
                                               "row leaves the free row / control split unidentified"},
                         "shares": {ch: {"row": float(fit["SigmaR"][k, k]), "donor": float(fit["SigmaD"][k, k]),
                                         "cell": float(fit["SigmaE"][k, k])} for k, ch in enumerate("CS")}}
    D, failed, unident = bootstrap(tab, len(worlds), boot, seed)
    rec["bootstrap"] = interval_record(D, failed, boot, unident)
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
                         "rectangle": f"log_rect on the registered domain (|e| <= {E_MAX}, width >= {W_MIN}, "
                                      f"|rho| <= {RHO_MAX}); validated max error {LOG_RECT_TOL}",
                         "grid": "z = atanh(rho), refined edges; local objective-value validation at the fit",
                         "constrained_fit": "interior point from 16 Halton starts; multi-start validated, not a "
                                            "global certificate",
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
    s.add_argument("--age-diagnostics", help="also write the collected cells' age-stratified diagnostics "
                   "(finfolk.redqueen.agediagnostics/1, D8 rule 48) to this path")
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
            doc, ages = collect_with_age_diagnostics(a.study, rqlib.read_json(a.design), a.plan, a.declare_missing)
            rqlib.write_json_durable(a.out, doc)
            if a.age_diagnostics:
                rqlib.write_json_durable(a.age_diagnostics, ages)
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

#!/usr/bin/env python3
"""test_obslaw.py: obslaw.py, the bank/D8 observation law of recovery option A (A_design_v5.md; test IDs of its
section 5). Synthetic data only: no bank observation, no study store or output is opened.

  T1 law oracle: T1-1 category probabilities and E[K] against an independent scalar oracle (explicit intervals,
     the capped top category, tail-stable math.erfc); T1-2 a definitional quadrature; T1-3 location solves and a
     knot-inclusive location table (exact solves outside +-12 even where a knot extends it); T1-4 uncapped draws
     above the ceiling; T1-5 the analytic and Monte Carlo mean, and the two prohibited substitutions; T1-6
     endpoints and refusals (+ the #68 cross-check, adoption gate); T1-7 the fitter-table certification under the v5
     adaptive policy, the empirical-logit moments and probe inversions against test-local oracles, its negative
     controls, caps (knot set and initial grid included) and extrapolation.
  T2 (obslaw's part): the clock fixture, the registered ceilings and the model's age_clock, the static and the
     monkeypatch guards.
  T3 (obslaw's unit part; the bank-mode recovery integration is test_graph.py's): latent correlations per sharing
     class, a singular PSD SigmaR, no second layer.
  T5-3 / T5-7 the strict bank/3 loader (V5_FIELDS: every field v5 2.8 prescribes, by v5 line and the section of
     A_design_v5_clarification_1.md that fixes its representation; V5_VALUES: types and values, C1-C5 and Addendum
     A's C7-C9: screened, exact horizon records, noise / map_variance equal to their 5k sources); T5-5 the D8
     streams (+ #68's normals, adoption gate); 4.2 item 7 the tables (shapes, identity incl. the noisescale evaluator).

    RQ_REQUIRE_NUMPY=1 python3 -I -W error::ResourceWarning tools/redqueen/test_obslaw.py -v

The adoption gates (v5 5: T1-6's #68 cross-check, T5-5's VecSplitMix64 equality) run against a read-only `git
archive` extraction of the pinned #68 commit: RQ_PR68_DIR names the extraction root, which holds PINNED_COMMIT (the
full 40-hex sha, printed by the gate), MANIFEST (`git ls-tree -r <that sha> tools/redqueen`, written at extraction:
git's record of that commit's files and blob ids) and tools/redqueen/. Before any gate runs, every extracted file's
git blob id is checked against MANIFEST (a mismatch, an extra or a missing file refuses), which authenticates the
extraction against that commit's tree as git recorded it. Without RQ_PR68_DIR the gates are skipped with a reason
starting "adoption gate".
"""
from __future__ import annotations

import ast
import copy
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
import tracemalloc
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
try:
    import numpy as np  # noqa: E402
except ImportError:
    if os.environ.get("RQ_REQUIRE_NUMPY"):
        raise SystemExit("RQ_REQUIRE_NUMPY is set, but numpy cannot be imported")
    np = None
import common  # noqa: E402
import material  # noqa: E402
import noisebank  # noqa: E402  (numpy only inside its functions)
import rqlib  # noqa: E402
if np is not None:
    import obslaw as ol  # noqa: E402

NEED_NP = unittest.skipIf(np is None, "numpy not installed")
PR68 = os.environ.get("RQ_PR68_DIR")
C247 = 247 / 600
VAL_SC = {"x": [-2.2, -0.6, 0.4], "s": [0.55, 0.30, 0.20]}     # v5 2.10's validation curves (synthetic)
VAL_SS = {"x": [-2.5, -1.2, -0.5], "s": [0.35, 0.25, 0.22]}
SIGMA_R = [[0.25, 0.05, 0.05], [0.05, 0.25, 0.15], [0.05, 0.15, 0.50]]   # #68's placeholder block (calib.py)
SIGMA_D = [[0.25, 0.05], [0.05, 0.25]]
SIGMA_E = [[0.50, 0.10], [0.10, 0.50]]


# ------------------------------------------------------------------ the independent scalar oracle (no obslaw code)
def _lower(x):                     # P(Z < x)
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _upper(x):                     # P(Z >= x)
    return 0.5 * math.erfc(x / math.sqrt(2.0))


def oracle_probs(a, s, N, M):
    """Category k has the latent interval [t_k, t_{k+1}) with t_0 = -inf, t_{M+1} = +inf (the capped category
    M's upper end is +inf), t_k = log((k - 1/2) / (N - k + 1/2)); tail-stable erfc differences."""
    t = [math.log((k - 0.5) / (N - k + 0.5)) for k in range(1, M + 1)]
    p = []
    for k in range(M + 1):
        lo = -math.inf if k == 0 else (t[k - 1] - a) / s
        hi = math.inf if k == M else (t[k] - a) / s
        if hi == math.inf:
            p.append(_upper(lo))
        elif lo == -math.inf:
            p.append(_lower(hi))
        elif lo > 0:
            p.append(_upper(lo) - _upper(hi))
        else:
            p.append(_lower(hi) - _lower(lo))
    return p


def oracle_mean(a, s, N, M):
    return math.fsum(k * pk for k, pk in enumerate(oracle_probs(a, s, N, M)))


def oracle_var(a, s, N, M):
    p = oracle_probs(a, s, N, M)
    m = math.fsum(k * pk for k, pk in enumerate(p))
    return math.fsum((k - m) ** 2 * pk for k, pk in enumerate(p))


def oracle_location(mu, s, N, M):
    """A bisection on the oracle's mean (independent of obslaw's solver)."""
    lo, hi = -40.0, 40.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if oracle_mean(mid, s, N, M) / N < mu else (lo, mid)
        if hi - lo < 1e-15:
            break
    return 0.5 * (lo + hi)


def oracle_logit_moments(a, s, N, M):
    """(m_z, V_z) of ell_N(K) = log((K + 1/2) / (N - K + 1/2)) under the oracle's categories: the mean and the
    CENTERED variance sum_k p_k (ell_k - m_z)^2 (v5 1.7b (ii)), by math.fsum."""
    p = oracle_probs(a, s, N, M)
    ell = [math.log((k + 0.5) / (N - k + 0.5)) for k in range(M + 1)]
    m = math.fsum(pk * lk for pk, lk in zip(p, ell))
    return m, math.fsum(pk * (lk - m) ** 2 for pk, lk in zip(p, ell))


def oracle_curve(curve, x):
    """S at x = logit(mu): linear in x between the knots, constant beyond (noisescale's documented rule, re-coded)."""
    xs, ss = curve["x"], curve["s"]
    if x <= xs[0]:
        return float(ss[0])
    for (x0, s0), (x1, s1) in zip(zip(xs, ss), zip(xs[1:], ss[1:])):
        if x <= x1:
            return s0 + (x - x0) / (x1 - x0) * (s1 - s0)
    return float(ss[-1])


def oracle_pipeline(curve, x, B=324):
    """The exact capture pipeline at x = logit(mu), test-local: mu, S_C(mu), the oracle location, (m_z, V_z)."""
    mu = 1.0 / (1.0 + math.exp(-x))
    s = oracle_curve(curve, x)
    a = oracle_location(mu, s, B, B)
    m, v = oracle_logit_moments(a, s, B, B)
    return mu, s, a, m, v


def oracle_inverse(curve, z, xl, xr, B=324):
    """mu* with m_z(mu*) = z by a scalar bisection in x inside [xl, xr] over the test-local pipeline."""
    lo, hi = xl, xr
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if oracle_pipeline(curve, mid, B)[3] < z:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            break
    return oracle_pipeline(curve, 0.5 * (lo + hi), B)


# ------------------------------------------------------------------ an independent SplitMix64 (published reference)
M64 = (1 << 64) - 1
GAMMA = 0x9E3779B97F4A7C15


def ref_seed(text):
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "little")


def ref_sm64(seed):
    x = seed & M64
    while True:
        x = (x + GAMMA) & M64
        z = x
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M64
        yield z ^ (z >> 31)


REFIT = "AnnexH/D8/1/noisebank/D8-refit/h5000/bootstrap"
VALROWS = "AnnexH/D8/1/noisebank/D8-validation/bank1/rows"
PINNED = {   # pinned from the independent implementation above (scripts: pin_streams.py), never from obslaw
    REFIT: {"seed": 0x0E6C854D8C459AF3,
            "outs": [0xDB304D7B0EE828AD, 0x6D284CA1F65B7F69, 0x63249C26423527AE, 0xFE7069AA64D73AFD],
            "below8": [5, 1, 6, 5, 3, 1, 7, 7, 7, 7, 5, 3, 5, 5, 1, 6],
            "unif": [0.8562057900843746, 0.4263961692252972, 0.3872773736386148],
            "normals": [-1.7625711502609331, 0.9890645718535409, -1.5444271719424003, -0.8864877981208008],
            "annexH1": 0x906E3E19C2EF00A5},
    VALROWS: {"seed": 0xDDDB5E295768CF2D,
              "outs": [0xCCA2A8514541B790, 0x47AAEBA1CD9C5DD9, 0x7BE1CDDEEF9474C1, 0x6352F11262F938B1],
              "below8": [0, 1, 1, 1, 0, 0, 7, 3, 7, 4, 2, 6, 3, 2, 3, 3],
              "unif": [0.7993569563307179, 0.2799517889048827, 0.48391424839754094],
              "normals": [-0.33531628490275384, -0.8768896799992083, 1.0475803078934, -1.0907048538529467],
              "annexH1": 0xBB6E1F131C78DD7A},
}


# ------------------------------------------------------------------ shared expensive objects (built once)
_CACHE = {}


def fitter_validation():
    """The fitter table of the v5 1.7c validation curve (the complete adaptive build, ~20 s)."""
    if "fit" not in _CACHE:
        _CACHE["fit"] = ol.build_fitter_table(VAL_SC, "0" * 64)
    return _CACHE["fit"]


def location_validation(ch):
    key = ("loc", ch)
    if key not in _CACHE:
        N, M = (324, 324) if ch == "C" else (600, 247)
        _CACHE[key] = ol.build_location_table(VAL_SC if ch == "C" else VAL_SS, ch, 1.0, N, M, "0" * 64)
    return _CACHE[key]


def sha_of(tag):
    return hashlib.sha256(tag.encode()).hexdigest()


REFIT_TEXTS = [f"AnnexH/D8/1/noisebank/D8-refit/h{h}/bootstrap" for h in (5000, 10000, 20000)]   # v5 L641-643; C2 order
AGE_PREDICATE = ("updated binary32 age > binary32(max_age) is an age death; F_i(H)=1 iff false through H frames "
                 "(common.age_feasible)")                                                     # v5 L748, verbatim
CAPPED_CATEGORY = "k = M_H: latent upper endpoint +inf, scale N = 600"                        # v5 L748, verbatim
STRUCTURAL_ZERO = {"status": "structural_zero", "M_H": 0,                                    # v5 2.6 L671-673; C4
                   "reason": "D8 rule 46: no age-feasible initial individual at this horizon"}
# A_design_v5_clarification_1.md (coordinator, 2026-11-14), verbatim
C3_CEILINGS = {"5000": 247, "10000": 0, "20000": 0}                                           # C3
C3_SATURATION = {"basis": "mean fraction of N", "denominator": 600,                           # C3
                 "window": {"C": [0.02, 0.98], "S": [0.02, 0.98], "F": [0.02, 0.98]}}
C5_RULE = ("working replicate-mean variance (nu0*phi*W(z) + (R-1)*s_hat^2)/(nu0 + R - 1)/R, W the empirical-logit "
           "variance of the frozen fitter table (A_design_v5.md section 1.7b, the adopted design; its sha256 as "
           "recorded in the dated adoption receipt); full_pooling: phi*W(z)/R")                # C5
R2_RULE = ("working replicate-mean variance (nu0 phi W(z) + (R-1) s2) / (nu0 + R - 1) / R, W the empirical-logit "
           "variance of the frozen fitter table (A_design_v5.md 1.7b); full_pooling: phi W(z) / R")   # (7e02fd0's)
# noisebank's horizon encoding (noisebank.py @4991907 L1683-1757 and the records it writes), by line
NB_GROUPS = ("R_CC", "R_SS", "R_CS", "D_CC", "D_SS", "D_CS", "T_CS", "R_CF", "R_SF")          # L220
NB_BOOT_NAMES = ("R_CC", "R_SS", "R_CS", "R_CF", "R_SF", "D_CC", "D_SS", "D_CS", "E_CC", "E_SS", "E_CS")   # L1623
CAP_GROUPS = ("R_CC", "D_CC")                                                                 # v5 L674; C4
CAP_BOOT_NAMES = ("R_CC", "D_CC", "E_CC")                                                     # C4.1: L1623 on C
COUNT_KEYS = ("rows", "incomplete", "saturated", "unidentified", "usable",                    # L946-947
              "screened")                                                        # clarification Addendum A C7
CURVE_KEYS = ("x", "s", "direction", "support", "cells", "blocks", "extrapolation")           # L1546-1548
NU0_KEYS = {"estimated": ("status", "nu0", "excess_log_variance", "sampling_log_variance", "cells"),   # L1597-1610
            "full_pooling": ("status", "excess_log_variance", "sampling_log_variance", "cells"),
            "unavailable": ("status", "reason")}
GROUP_KEYS = ("pairs", "rho_max", "curvature_per_pair", "at_box", "deep_tail", "nodes")       # L1710-1711, L1737
GRID_KEYS = ("label", "worst_miss_per_pair", "tolerance", "refined", "refit_shift", "shift_flag")   # L1742-1744
COMPONENT_KEYS = ("SigmaR", "SigmaD", "SigmaE", "fit", "loglik", "unconstrained_problems", "multistart", "at_box",
                  "box", "SigmaR_FF", "shares")                                               # L1745-1753
FF_KEYS = ("value", "status", "rule")                                                         # L1749-1751
SHARE_KEYS = ("row", "donor", "cell")                                                         # L1752-1753
INTERVAL_KEYS = ("draws", "failed", "identification_rejections", "failure_rate", "procedure", "label", "status",
                 "ci95")                                                                      # L1671-1680
# the fixture's nu0 statuses, (horizon, channel) -> status (map_variance.nu0 is the 5k horizon's, L1794)
NU0_STATUS = {("5000", "C"): "estimated", ("5000", "S"): "full_pooling", ("5000", "F"): "unavailable",
              ("10000", "C"): "estimated", ("20000", "C"): "full_pooling"}
CAP_RHO = (0.375, 0.125)                     # the 10k capture-only fit: rho_R, rho_D (E = 1 - 0.375 - 0.125 = 0.5)


# ------------------------------------------------------------------ noisebank's own source (texts, estimator record)
def _nb_tree():
    if "nb_ast" not in _CACHE:
        _CACHE["nb_ast"] = ast.parse(rqlib.read_text(os.path.join(HERE, "noisebank.py")))
    return _CACHE["nb_ast"]


def _nb_eval(node, **local):
    """One expression of noisebank's source, evaluated in noisebank's module namespace (plus local names)."""
    return eval(compile(ast.Expression(node), "noisebank.py", "eval"), dict(vars(noisebank), **local))


def nb_texts():
    """Every string literal of noisebank.py (implicit concatenations joined by the parser; f-strings evaluated in
    noisebank's namespace when they name module constants only)."""
    if "nb_texts" not in _CACHE:
        out = set()
        parts = {id(c) for js in ast.walk(_nb_tree()) if isinstance(js, ast.JoinedStr)   # (an f-string's pieces)
                 for c in ast.walk(js) if c is not js}
        for node in ast.walk(_nb_tree()):
            if id(node) in parts:
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.add(node.value)
            elif isinstance(node, ast.JoinedStr):
                try:
                    out.add(_nb_eval(node))
                except Exception:   # (an f-string of local names is not a record text)
                    pass
        _CACHE["nb_texts"] = out
    return _CACHE["nb_texts"]


def nb_text(prefix):
    """The one string literal of noisebank.py starting with prefix (a record text noisebank writes)."""
    key = ("nb_text", prefix)
    if key not in _CACHE:
        hits = sorted(t for t in nb_texts() if t.startswith(prefix))
        if len(hits) != 1:
            raise AssertionError(f"noisebank.py: {len(hits)} literals start with {prefix!r}: {hits[:3]}")
        _CACHE[key] = hits[0]
    return _CACHE[key]


def nb_existing_estimator():
    """noisebank.estimate's existing estimator record (L1769-1777), evaluated from its source with the registered
    arguments (m = Z_INTERVALS, boot = BOOT, seed = 0): what the registered estimator writes today."""
    if "nb_est" not in _CACHE:
        fn = next(n for n in ast.walk(_nb_tree()) if isinstance(n, ast.FunctionDef) and n.name == "estimate")
        recs = [_nb_eval(v, m=noisebank.Z_INTERVALS, boot=noisebank.BOOT, seed=0)
                for node in ast.walk(fn) if isinstance(node, ast.Dict)
                for k, v in zip(node.keys, node.values)
                if isinstance(k, ast.Constant) and k.value == "estimator" and isinstance(v, ast.Dict)]
        if len(recs) != 1:
            raise AssertionError(f"noisebank.estimate writes {len(recs)} estimator records")
        _CACHE["nb_est"] = recs[0]
    return copy.deepcopy(_CACHE["nb_est"])


def c3_estimator():
    """Clarification C3's record: the existing one minus seed (C1), plus ceilings, saturation, capped_category."""
    rec = nb_existing_estimator()
    del rec["seed"]
    rec.update(ceilings=dict(C3_CEILINGS), saturation=copy.deepcopy(C3_SATURATION), capped_category=CAPPED_CATEGORY)
    return rec


# ------------------------------------------------------------------ the synthetic bank/3 fixture
def counts_rec():
    return {"rows": 512, "incomplete": 0, "saturated": 12, "unidentified": 4, "usable": 496, "screened": 2}


def curve_rec(base):
    c = copy.deepcopy(base)
    c.update(direction="decreasing", support=[c["x"][0] - 0.5, c["x"][-1] + 0.5], cells=496, blocks=len(c["x"]),
             extrapolation=nb_text("constant beyond the outermost knots"))
    return c


def nu0_rec(status):
    if status == "unavailable":
        return {"status": "unavailable", "reason": "synthetic test"}
    rec = {"excess_log_variance": 0.08 if status == "estimated" else -0.01, "sampling_log_variance": 0.02,
           "cells": 496, "status": status}
    if status == "estimated":
        rec["nu0"] = 12.5
    return rec


def group_rec(ok=True):
    g = {"pairs": 4096, "rho_max": 0.2, "curvature_per_pair": 0.05, "at_box": False, "deep_tail": 0}
    if ok:
        g["nodes"] = 241
    return g


def interval_rec(names):
    return {"draws": noisebank.BOOT, "failed": 3, "identification_rejections": 1, "failure_rate": 3 / noisebank.BOOT,
            "procedure": nb_text("world-multiplicity weighted likelihood ("),
            "label": nb_text("approximate; conditional on identification"), "status": "ok",
            "ci95": {n: [0.05, 0.4] for n in names}}


def components_rec(zero):
    if zero:
        rR, rD = CAP_RHO
        SR, SD, SE = [[rR]], [[rD]], [[1.0 - rR - rD]]
    else:
        SR, SD, SE = (copy.deepcopy(m) for m in (SIGMA_R, SIGMA_D, SIGMA_E))
    c = {"SigmaR": SR, "SigmaD": SD, "SigmaE": SE, "fit": "unconstrained", "loglik": -15234.25,
         "unconstrained_problems": [], "multistart": None, "at_box": [], "box": nb_text("|rho| <= "),
         "shares": {ch: {"row": SR[k][k], "donor": SD[k][k], "cell": SE[k][k]}
                    for k, ch in enumerate("C" if zero else "CS")}}
    if not zero:
        c["SigmaR_FF"] = {"value": SR[2][2], "status": "convention",
                          "rule": nb_text("the minimal feasible free row variance")}
    return c


def _horizon_record(h, status):
    """A synthetic per-horizon record in noisebank's 5k encoding (v5 L751 "as now": noisebank.py L1683-1757); at the
    zero-ceiling horizons (10k, 20k) the channels.S/F structural-zero declarations (C4) and the capture-only fit
    as the 5k encoding restricted to C (C4.1). Placeholder values, not a fit."""
    zero = h != "5000"
    chans = "C" if zero else "CSF"
    curves = {"C": VAL_SC, "S": VAL_SS, "F": VAL_SS}
    rec = {"capture_bound": {"5000": 324, "10000": 642, "20000": 1284}[h], "replicates": 64, "incomplete_cells": 0,
           "channels": {ch: dict(STRUCTURAL_ZERO) if zero and ch != "C" else counts_rec() for ch in "CSF"},
           "scales": {ch: curve_rec(curves[ch]) for ch in chans},
           "nu0": {ch: nu0_rec(NU0_STATUS[(h, ch)]) for ch in chans},
           "curve_points": {ch: [[0.2, 0.5], [0.8, 0.25]] for ch in chans},
           "worlds": [f"w{i}" for i in range(8)], "status": status,
           "reasons": [] if status == "ok" else ["R_CC is unidentified (curvature per pair 0.0004 < 0.001)"],
           "components": None, "bootstrap": None}
    gs = CAP_GROUPS if zero else NB_GROUPS
    if status == "ok":
        rec.update(groups={g: group_rec() for g in gs},
                   grid_validation={"label": nb_text("local objective-value validation ("), "worst_miss_per_pair": 2e-4,
                                    "tolerance": noisebank.GRID_LL_TOL, "refined": False, "refit_shift": 0.0,
                                    "shift_flag": False},
                   components=components_rec(zero), bootstrap=interval_rec(CAP_BOOT_NAMES if zero else NB_BOOT_NAMES))
    else:                                       # (the identification-failure shape, L1716: groups without nodes)
        rec["groups"] = {g: group_rec(ok=False) for g in gs}
    return rec


def bank3_doc(synthetic=False):
    """A complete, valid synthetic bank/3 artifact (v5 2.8 with clarification 1): every field V5_FIELDS lists,
    declared synthetic parameters, the registered constants and texts (the estimator record and the horizon texts
    read from noisebank's own source; the C2/C3/C5 records from the clarification), placeholder identities and
    placeholder fit values, no survival quantity at 10k/20k. Not a bank fit. noise and map_variance are built from
    horizons["5000"] as noisebank.py L1788-1796 builds them (clarification Addendum A C9): s_logit = {x, s,
    direction} of the 5k curves, the matrices = the 5k components, map_variance.nu0 = the 5k nu0 records."""
    hz = {"5000": _horizon_record("5000", "ok"), "10000": _horizon_record("10000", "ok"),
          "20000": _horizon_record("20000", "unavailable")}
    base = hz["5000"]
    curves = {ch: {k: copy.deepcopy(base["scales"][ch][k]) for k in ("x", "s", "direction")} for ch in "CSF"}
    inputs = dict(ol.REGISTERED_INPUTS, design_canonical_sha256=sha_of("dc"), provenance_sha256=sha_of("pv"),
                  validation_report_sha256=sha_of("vr"))
    firsts = []
    for t in REFIT_TEXTS:                       # (C2: the independent SplitMix64 above, never obslaw's)
        g = ref_sm64(ref_seed(t))
        firsts.append([next(g), next(g)])
    return {
        "schema": ol.BANK_SCHEMA, "status": ol.STATUS_FITTED, "synthetic": synthetic,
        "cohort": material.registered_ages(), "cohort_sha256": material.AGES_SHA256, "horizon": 5000, "dt": 0.016,
        "support_law": material.SUPPORT_LAW, "age_clock": copy.deepcopy(material.age_clock_identity()),  # (lru-cached)
        "survivor_ceiling": 247,
        "fit": {"noise_likelihood": ol.NOISE_LIKELIHOOD,
                "noise": {"implementation_sha256": sha_of("impl"), "inputs_sha256": rqlib.canonical_sha(inputs),
                          "receipt_sha256": sha_of("receipt"), "engine_sha256": sha_of("engine")},
                "streams": {"bootstrap": {"generator": "rqlib.SplitMix64", "namespace": "AnnexH/D8/1",
                                          "texts": list(REFIT_TEXTS), "seeds": [ref_seed(t) for t in REFIT_TEXTS],
                                          "first_outputs": firsts}}},
        "noise": {"available": True, "s_logit": curves, "SigmaR": copy.deepcopy(base["components"]["SigmaR"]),
                  "SigmaD": copy.deepcopy(base["components"]["SigmaD"]),
                  "SigmaE": copy.deepcopy(base["components"]["SigmaE"]), "horizon": 5000,
                  "capture_bound": 324, "survivor_ceiling": 247},
        "map_variance": {"s_logit": copy.deepcopy(curves), "nu0": copy.deepcopy(base["nu0"]),
                         "rule": C5_RULE, "consumer": "map.fit rep_prior, capture channel"},
        "d8": {"amendment_sha256": ol.D8_SHA256, "capture_law": ol.CAPTURE_LAW, "ceilings": dict(ol.CEILINGS),
               "max_age": material.registered_ages()["max_age"], "denominator": 600,
               "age_predicate": AGE_PREDICATE, "capped_category": CAPPED_CATEGORY},
        "inputs": inputs,
        "estimator": c3_estimator(),
        "horizons": hz,
    }


# v5 2.8's required fields, from v5's own text (A_design_v5.md, sha256 5d4c00be...) and clarification 1: (path, v5 line
# and clarification section, what v5 cites). Deleting any one from the complete fixture must be refused naming it
# (v5 2.9 L773: "a missing field of 2.8").
_NB = "noisebank.py @4991907"


def _v5_horizon_fields():
    """The horizon contents: v5 L751 'per horizon as now' (noisebank.py L1683-1757) and, at the zero-ceiling
    horizons, clarification C4 (the declarations, whatever the status) and C4.1 (the 5k encoding restricted to C)."""
    out = []
    for h, status in (("5000", "ok"), ("10000", "ok"), ("20000", "unavailable")):
        zero = h != "5000"
        chans = "C" if zero else "CSF"
        H = ("horizons", h)
        v5 = "751; C4, C4.1" if zero else "751"
        out += [(H + ("channels", ch), v5, f"{_NB} L1690") for ch in "CSF"]
        out += [(H + ("channels", ch, k), v5 + ("; clarification Addendum A C7" if k == "screened" else ""),
                 "v5 L666-667, the screen's counts" if k == "screened" else f"{_NB} L946-947")
                for ch in chans for k in COUNT_KEYS]
        if zero:
            out += [(H + ("channels", ch, k), "671-673; C4", "the structural-zero declaration, whatever the status")
                    for ch in "SF" for k in STRUCTURAL_ZERO]
        out += [(H + (k, ch), v5, f"{_NB} L1690-1696") for k in ("scales", "nu0", "curve_points") for ch in chans]
        out += [(H + ("scales", ch, k), v5, f"{_NB} L1546-1548") for ch in chans for k in CURVE_KEYS]
        out += [(H + ("nu0", ch, k), v5, f"{_NB} L1597-1610") for ch in chans for k in NU0_KEYS[NU0_STATUS[(h, ch)]]]
        if status != "ok":
            continue
        gs, names = (CAP_GROUPS, CAP_BOOT_NAMES) if zero else (NB_GROUPS, NB_BOOT_NAMES)
        out += [(H + ("groups", g), v5, f"{_NB} L1706-1711") for g in gs]
        out += [(H + ("groups", g, k), v5, f"{_NB} L1710-1711, L1737") for g in gs for k in GROUP_KEYS]
        out += [(H + ("grid_validation", k), v5, f"{_NB} L1742-1744") for k in GRID_KEYS]
        out += [(H + ("components", k), v5, f"{_NB} L1745-1753") for k in COMPONENT_KEYS
                if not (zero and k == "SigmaR_FF")]
        if not zero:
            out += [(H + ("components", "SigmaR_FF", k), v5, f"{_NB} L1749-1751") for k in FF_KEYS]
        shares = "C" if zero else "CS"
        out += [(H + ("components", "shares", ch), v5, f"{_NB} L1752-1753") for ch in shares]
        out += [(H + ("components", "shares", ch, k), v5, f"{_NB} L1752-1753") for ch in shares for k in SHARE_KEYS]
        out += [(H + ("bootstrap", k), v5, f"{_NB} L1671-1680") for k in INTERVAL_KEYS]
        out += [(H + ("bootstrap", "ci95", n), v5, f"{_NB} L1623, L1679") for n in names]
    return out


V5_FIELDS = (
    *(((k,), line, "") for k, line in (("schema", 734), ("status", 735), ("synthetic", 736), ("cohort", 737),
                                       ("cohort_sha256", 738), ("horizon", 739), ("dt", 740), ("support_law", 741),
                                       ("age_clock", 742), ("survivor_ceiling", 744))),
    (("fit",), 745, ""), (("fit", "noise_likelihood"), 745, ""), (("fit", "noise"), 745, ""),
    *((("fit", "noise", k), 745, "") for k in ("implementation_sha256", "inputs_sha256", "receipt_sha256",
                                                "engine_sha256")),
    (("fit", "streams"), 745, ""), (("fit", "streams", "bootstrap"), "745; C2", ""),
    *((("fit", "streams", "bootstrap", k), "745; C2", "") for k in ("generator", "namespace", "texts", "seeds")),
    (("fit", "streams", "bootstrap", "first_outputs"), "646; C2", "the first two outputs of each stream"),
    (("noise",), 746, ""),
    *((("noise", k), 746, "") for k in ("available", "s_logit", "SigmaR", "SigmaD", "SigmaE", "horizon",
                                         "capture_bound", "survivor_ceiling")),
    *((("noise", "s_logit", ch), 746, "{C,S,F}") for ch in "CSF"),
    (("map_variance",), 747, ""),
    *((("map_variance", k), "747" + ("; C5" if k == "rule" else ""), "") for k in ("s_logit", "nu0", "rule",
                                                                                    "consumer")),
    *((("map_variance", "nu0", ch), 747, "{C,S,F}") for ch in "CSF"),
    *((("map_variance", "nu0", ch, k), 747, f"the existing encoding, {_NB} L1597-1610")   # (an estimated record's
      for ch in "CSF" for k in NU0_KEYS[NU0_STATUS[("5000", ch)]] if k != "nu0"),          # nu0: T5-7, since a903ee8)
    (("d8",), 748, ""),
    *((("d8", k), 748, "") for k in ("amendment_sha256", "capture_law", "ceilings", "max_age", "denominator",
                                      "age_predicate", "capped_category")),
    (("inputs",), 749, ""),
    *((("inputs", k), 749, "") for k in ("observations_sha256", "ages_sha256", "plan_sha256", "design_file_sha256",
                                          "design_canonical_sha256", "provenance_sha256", "validation_report_sha256")),
    (("estimator",), "750; C3", ""),
    *((("estimator", k), "750, 612-616; C3", f"the existing record without seed (C1), {_NB} L1769-1777")
      for k in ("z_intervals", "rho_max", "sigma_min", "info_min", "multi_start", "start_tol", "boot",
                "boot_fail_max", "rectangle", "grid", "constrained_fit", "fixed_replicate_bias")),
    (("estimator", "saturation"), "750, 613; C3", f"the existing key ({_NB} L1769) holding C3's object"),
    *((("estimator", "saturation", k), "613, 624-629, 750; C3", "saturation per channel and its basis")
      for k in C3_SATURATION),
    *((("estimator", "saturation", "window", ch), "624-625; C3", "the same window for every channel")
      for ch in "CSF"),
    (("estimator", "ceilings"), "750; C3", ""),
    *((("estimator", "ceilings", h), "748, 750; C3", "equal to d8.ceilings") for h in C3_CEILINGS),
    (("estimator", "capped_category"), "750; C3", ""),
    (("horizons",), 751, ""),
    *((("horizons", h), 751, f"'per horizon as now', {_NB} L1778-1782") for h in ("5000", "10000", "20000")),
    *((("horizons", h, k), 751, f"'as now', {_NB} L1689-1690, L1698, L1701, L1756")
      for h in ("5000", "10000", "20000")
      for k in ("capture_bound", "replicates", "incomplete_cells", "channels", "scales", "nu0", "curve_points",
                "worlds", "status", "reasons", "components", "bootstrap")),
    *((("horizons", h, k), 751, f"'as now' with status ok, {_NB} L1741-1742")
      for h in ("5000", "10000") for k in ("groups", "grid_validation")),
    *_v5_horizon_fields(),
)


def _set(path, value):
    """mutate(d): d[path] = value."""
    def mutate(d):
        node = d
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = value
    return mutate


def _get(d, path):
    for k in path:
        d = d[k]
    return d


def _put(path, factory):
    """mutate(d): d[path] = factory() (a fresh value built when the case runs)."""
    return lambda d: _get(d, path[:-1]).__setitem__(path[-1], factory())


def _upd(path, **kw):
    return lambda d: _get(d, path).update(copy.deepcopy(kw))


def _permute_streams(order):
    def mutate(d):
        b = d["fit"]["streams"]["bootstrap"]
        for k in ("texts", "seeds", "first_outputs"):
            b[k] = [b[k][i] for i in order]
    return mutate


def _cap_fit(rR, rD):
    """The 10k capture-only fit replaced consistently (components and shares) by rho_R, rho_D."""
    def mutate(d):
        d["horizons"]["10000"]["components"].update(
            SigmaR=[[rR]], SigmaD=[[rD]], SigmaE=[[1.0 - rR - rD]],
            shares={"C": {"row": rR, "donor": rD, "cell": 1.0 - rR - rD}})
    return mutate


def constrained_fit(d, **extra):
    """The 5k components as a constrained (multi-start) fit (noisebank.fit_dependence L1423-1440), extra keys
    added to its multistart record."""
    d["horizons"]["5000"]["components"].update(
        fit="constrained", unconstrained_problems=["SigmaE is not PSD"],
        multistart=dict({"starts": 16, "converged": 12, "reaching_best": 9, "parameter_spread": 2e-4,
                         "kkt_residual": 3e-7, "label": nb_text("multi-start validated")}, **extra))


def unavailable_interval(d, h="5000", **extra):
    """horizons[h].bootstrap as an unavailable interval (interval_record L1676-1678), extra keys added."""
    d["horizons"][h]["bootstrap"].update(dict(failed=60, identification_rejections=10, failure_rate=60 / 999,
                                              status="unavailable", ci95=None,
                                              reason="60 of 999 draws failed (> 5%)"), **extra)


def _both_s_logit(ch, change):
    """noise.s_logit[ch] and map_variance.s_logit[ch] changed alike (so v5 4.2 item 5 still passes)."""
    def mutate(d):
        for blk in ("noise", "map_variance"):
            change(d[blk]["s_logit"][ch])
    return mutate


_BOOT = ("fit", "streams", "bootstrap")
_FO = _BOOT + ("first_outputs",)
_5K, _10K, _20K = ("horizons", "5000"), ("horizons", "10000"), ("horizons", "20000")
# v5 2.8's types and fixed values (and 2.5 / 2.6 / 2.7 where 2.8 cites them), with clarification 1's sections:
# (mutation, refusal pattern, v5 line; clarification section). Entries 0-37 are round 2's (21 and 22, the rule's,
# re-bound to C5's fixed text); 38-188 are round 3's; every later entry is round 4's (clarification Addendum A).
V5_VALUES = (
    (_set(("estimator",), {}), r"missing field estimator\.z_intervals", "750"),          # (the review's cases)
    (_set(("horizons",), {}), r"missing field horizons\.5000", "751"),
    (lambda d: d["fit"]["streams"]["bootstrap"].update(texts=None, seeds=None), "texts must be a list", "745"),
    (_set(_BOOT + ("texts",), None), "texts must be a list", "745"),
    (_set(_BOOT + ("seeds",), None), "seeds must be a list", "745"),
    (_set(_BOOT + ("texts",), {"5000": REFIT_TEXTS[0]}), "texts must be a list", "745"),
    (_set(_BOOT + ("texts",), REFIT_TEXTS[:2] + [5]), "texts must be a list", "745"),
    (lambda d: d["fit"]["streams"]["bootstrap"].update(texts=REFIT_TEXTS[:2], seeds=[ref_seed(t) for t in
                                                                                     REFIT_TEXTS[:2]]),
     "texts must be exactly the refit streams", "641-643"),
    (lambda d: d["fit"]["streams"]["bootstrap"].update(texts=REFIT_TEXTS[:2] + REFIT_TEXTS[:1],
                                                       seeds=[ref_seed(t) for t in REFIT_TEXTS[:2] + REFIT_TEXTS[:1]]),
     "texts must be exactly the refit streams", "641-643"),
    (lambda d: d["fit"]["streams"]["bootstrap"]["texts"].__setitem__(1, REFIT_TEXTS[1].replace("D8/1", "1")),
     "texts must be exactly the refit streams", "641-643, 647-649"),
    (lambda d: d["fit"]["streams"]["bootstrap"]["seeds"].pop(), "seeds must be a list", "745"),
    (lambda d: d["fit"]["streams"]["bootstrap"]["seeds"].__setitem__(0, True), "seeds must be a list", "745"),
    (lambda d: d["fit"]["streams"]["bootstrap"]["seeds"].__setitem__(0, -1), "seeds must be a list", "745"),
    (lambda d: d["fit"]["streams"]["bootstrap"]["seeds"].__setitem__(0, 1 << 64), "seeds must be a list", "745"),
    (lambda d: d["fit"]["streams"]["bootstrap"]["seeds"].__setitem__(0, str(ref_seed(REFIT_TEXTS[0]))),
     "seeds must be a list", "745"),
    (lambda d: d["fit"]["streams"]["bootstrap"]["seeds"].reverse(), "is not the derived seed", "631-633"),
    (lambda d: d["fit"]["streams"]["bootstrap"]["seeds"].__setitem__(2, ref_seed(REFIT_TEXTS[2]) ^ 1),
     "is not the derived seed", "631-633"),
    (_set(("fit", "noise", "inputs_sha256"), sha_of("inputs")), "inputs_sha256 is not the canonical sha256", "755"),
    (_set(("d8", "age_predicate"), "updated binary32 age > binary32(max_age) is an age death"),
     "d8.age_predicate is not", "748"),
    (_set(("d8", "capped_category"), "k = M_H: capped"), "d8.capped_category is not", "748"),
    (_set(("map_variance", "consumer"), "map.fit"), "map_variance.consumer is not", "747"),
    (_set(("map_variance", "rule"), None), "map_variance.rule is not the fixed rule text", "747; C5"),
    (_set(("map_variance", "rule"), ""), "map_variance.rule is not the fixed rule text", "747; C5"),
    (_set(("estimator",), []), "estimator must be an object", "750"),
    (_set(("estimator", "boot"), 1000), "estimator.boot 1000 is not the registered 999", "616"),
    (_set(("estimator", "boot"), 999.0), "estimator.boot 999.0 is not the registered 999", "616"),
    (_set(("estimator", "multi_start"), 8), "estimator.multi_start 8 is not the registered 16", "615"),
    (_set(("horizons",), []), "horizons must be an object", "751"),
    (_set(("horizons", "5000"), "ok"), "horizons.5000 must be an object", "751"),
    (_set(("horizons", "5000", "status"), "unavailable"), r"horizons\.5000\.status 'unavailable' is refused",
     "692 (R7), 735"),
    (_set(("horizons", "10000", "status"), "maybe"), r"horizons\.10000\.status 'maybe' is refused", "676-678"),
    (_set(("horizons", "20000", "status"), None), r"horizons\.20000\.status None is refused", "676-678"),
    (_set(("horizons", "5000", "components"), None), r"horizons\.5000\.components must be an object", "751"),
    (_set(("horizons", "10000", "bootstrap"), None), r"horizons\.10000\.bootstrap must be an object", "751"),
    (_set(("horizons", "5000", "capture_bound"), 323), r"horizons\.5000\.capture_bound 323", "592-594, 751"),
    (_set(("horizons", "10000", "capture_bound"), 324), r"horizons\.10000\.capture_bound 324", "592-594, 751"),
    (_set(("horizons", "5000", "capture_bound"), 324.0), r"horizons\.5000\.capture_bound 324\.0", "592-594, 751"),
    (_set(("horizons", "5000", "reasons"), None), r"horizons\.5000\.reasons must be a list", "751"),
    # ---- round 3: C1 (the legacy seed) and C2 (the stream record)
    (_upd(("estimator",), seed=0), r"estimator\.seed is refused", "641, 750; C1"),
    (_upd(("estimator",), seed=None), r"estimator\.seed is refused", "641, 750; C1"),
    (lambda d: _get(d, _FO)[1].__setitem__(1, _get(d, _FO)[1][1] ^ 1), "are not the first two outputs",
     "646; C2"),
    (lambda d: _get(d, _FO).reverse(), "are not the first two outputs", "646; C2"),
    (lambda d: _get(d, _FO)[2].reverse(), "are not the first two outputs", "646; C2"),
    (_set(_FO, None), "first_outputs must be one pair", "646; C2"),
    (lambda d: _get(d, _FO).pop(), "first_outputs must be one pair", "646; C2"),
    (lambda d: _get(d, _FO)[0].pop(), "first_outputs must be one pair", "646; C2"),
    (lambda d: _get(d, _FO)[2].__setitem__(0, True), "first_outputs must be one pair", "646; C2"),
    (lambda d: _get(d, _FO)[0].__setitem__(0, 1 << 64), "first_outputs must be one pair", "646; C2"),
    (lambda d: _get(d, _FO)[0].__setitem__(0, float(_get(d, _FO)[0][0])), "first_outputs must be one pair",
     "646; C2"),
    (_permute_streams([1, 0, 2]), r"texts must be in the order h = 5000, 10000, 20000", "641-643; C2"),
    (_permute_streams([2, 1, 0]), r"texts must be in the order", "641-643; C2"),
    (_upd(_BOOT, seed=0), r"fit\.streams\.bootstrap has keys \['seed'\] outside", "745; C2"),
    # ---- C3 (the estimator record): Codex's four examples, 7e02fd0's wrong constants, types, values, the basis
    (_set(("estimator", "ceilings"), None), r"estimator\.ceilings is null", "750; C3"),
    (_set(("estimator", "saturation"), None), r"estimator\.saturation is null", "750; C3"),
    (_set(("estimator", "capped_category"), None), r"estimator\.capped_category is null", "750; C3"),
    (_set(("estimator", "sigma_min"), -1),
     r"estimator\.sigma_min -1 is not the registered 0\.01 \(noisebank\.SIGMA_MIN\)", "612-613; C3"),
    (_set(("estimator", "rho_max"), 0.95), r"estimator\.rho_max 0\.95 is not the registered 0\.995", "612-616; C3"),
    (_set(("estimator", "sigma_min"), 0.05), r"estimator\.sigma_min 0\.05 is not the registered 0\.01", "613; C3"),
    (_set(("estimator", "info_min"), 0.25), r"estimator\.info_min 0\.25 is not the registered 0\.001", "614; C3"),
    (_set(("estimator", "z_intervals"), 64), r"estimator\.z_intervals 64 is not the registered 240", "612; C3"),
    (_set(("estimator", "z_intervals"), 240.0), r"estimator\.z_intervals 240\.0 is not the registered 240",
     "612; C3"),
    (_set(("estimator", "start_tol"), "0.0001"), r"estimator\.start_tol '0\.0001' is not the registered", "615; C3"),
    (_set(("estimator", "start_tol"), True), r"estimator\.start_tol True is not the registered", "615; C3"),
    (_set(("estimator", "boot_fail_max"), 0.1), r"estimator\.boot_fail_max 0\.1 is not the registered 0\.05",
     "616; C3"),
    (_set(("estimator", "rectangle"), "log_rect (synthetic)"), r"estimator\.rectangle 'log_rect \(synthetic\)' is not",
     "612; C3"),
    (_set(("estimator", "grid"), "z = atanh(rho)"), r"estimator\.grid 'z = atanh\(rho\)' is not", "615; C3"),
    (_set(("estimator", "constrained_fit"), "interior point from 8 Halton starts"),
     r"estimator\.constrained_fit .* is not the registered", "615; C3"),
    (_set(("estimator", "fixed_replicate_bias"), "corrected"), r"estimator\.fixed_replicate_bias 'corrected' is not",
     "612; C3"),
    (_set(("estimator", "saturation", "basis"), "mean fraction of M_H"),
     r"estimator\.saturation\.basis 'mean fraction of M_H' is not the registered 'mean fraction of N'",
     "613, 624-629; C3"),
    (_set(("estimator", "saturation", "basis"), "mean fraction of N "), r"estimator\.saturation\.basis .* is not",
     "613, 624-629; C3"),
    (_set(("estimator", "saturation", "denominator"), 247),
     r"estimator\.saturation\.denominator 247 is not the registered 600", "624; C3"),
    (_set(("estimator", "saturation", "denominator"), 600.0),
     r"estimator\.saturation\.denominator 600\.0 is not the registered 600", "624; C3"),
    (_set(("estimator", "saturation", "window", "S"), [0.02, 1.0]),
     r"estimator\.saturation\.window\.S \[0\.02, 1\.0\] is not the registered \[0\.02, 0\.98\]", "624-629; C3"),
    (_set(("estimator", "saturation", "window", "C"), [0.02]), r"estimator\.saturation\.window\.C \[0\.02\] is not",
     "624-629; C3"),
    (_set(("estimator", "saturation", "window"), [0.02, 0.98]),
     r"estimator\.saturation\.window \[0\.02, 0\.98\] is not the registered object", "750; C3"),
    (_set(("estimator", "saturation"), [0.02, 0.98]),
     r"estimator\.saturation \[0\.02, 0\.98\] is not the registered object", "750; C3"),
    (_upd(("estimator", "saturation"), channels={"C": [0.02, 0.98], "S": [0.02, 0.98], "F": [0.02, 0.98]}),
     r"estimator\.saturation carries keys outside the registered record: \['channels'\]", "750; C3"),
    (_set(("estimator", "ceilings", "20000"), 1), r"estimator\.ceilings\.20000 1 is not the registered 0",
     "748, 750; C3"),
    (_set(("estimator", "ceilings", "10000"), 0.0), r"estimator\.ceilings\.10000 0\.0 is not the registered 0",
     "748, 750; C3"),
    (_set(("estimator", "capped_category"), {"S": CAPPED_CATEGORY, "F": CAPPED_CATEGORY}),
     r"estimator\.capped_category \{.*\} is not the registered 'k = M_H", "748, 750; C3"),
    (_set(("estimator", "capped_category"), "k = M_H: capped"), r"estimator\.capped_category 'k = M_H: capped' is not",
     "748, 750; C3"),
    (_upd(("estimator",), marg_info_min=0.4), r"estimator carries keys outside the C3 record: \['marg_info_min'\]",
     "750; C3"),
    # ---- C5 (map_variance.rule is one fixed string)
    (_put(("map_variance", "rule"), lambda: nb_text("replicate-mean variance (")),
     "map_variance.rule is not the fixed rule text", "747; C5"),
    (_set(("map_variance", "rule"), R2_RULE), "map_variance.rule is not the fixed rule text", "747; C5"),
    (_set(("map_variance", "rule"), C5_RULE.replace("A_design_v5.md", "A_design_v4.md")),
     "map_variance.rule is not the fixed rule text", "747; C5"),
    (_set(("map_variance", "rule"), C5_RULE + " "), "map_variance.rule is not the fixed rule text", "747; C5"),
    (_set(("map_variance", "rule"), [C5_RULE]), "map_variance.rule is not the fixed rule text", "747; C5"),
    # ---- C4 at the zero-ceiling horizons: survival covariance, S/F groups and any other survival quantity
    (_set(_10K + ("components", "SigmaR"), SIGMA_R),
     r"horizons\.10000\.components\.SigmaR has survival rows/columns", "671-673; C4"),
    (_set(_10K + ("components", "SigmaD"), SIGMA_D),
     r"horizons\.10000\.components\.SigmaD has survival rows/columns", "671-673; C4"),
    (_set(_10K + ("components", "SigmaE"), SIGMA_E),
     r"horizons\.10000\.components\.SigmaE has survival rows/columns", "671-673; C4"),
    (_set(_10K + ("components", "SigmaR"), [[0.375, 0.05], [0.05, 0.25]]),
     r"horizons\.10000\.components\.SigmaR has survival rows/columns", "671-673; C4"),
    (_put(_10K + ("groups", "R_SS"), group_rec), r"horizons\.10000\.groups\.R_SS is a survival fitted quantity",
     "672-674; C4"),
    (_put(_10K + ("groups", "T_CS"), group_rec), r"horizons\.10000\.groups\.T_CS is a survival fitted quantity",
     "672-674; C4"),
    (_put(_10K + ("groups", "R_CF"), group_rec), r"horizons\.10000\.groups\.R_CF is a survival fitted quantity",
     "672-674; C4"),
    (_put(_20K + ("groups", "D_SS"), lambda: group_rec(ok=False)),
     r"horizons\.20000\.groups\.D_SS is a survival fitted quantity", "672-674; C4"),
    (_put(_10K + ("nu0", "S"), lambda: nu0_rec("full_pooling")), r"horizons\.10000\.nu0\.S is a survival",
     "672; C4"),
    (_put(_20K + ("nu0", "S"), lambda: dict(STRUCTURAL_ZERO)), r"horizons\.20000\.nu0\.S is a survival",
     "671-673; C4 (7e02fd0's placement)"),
    (_put(_10K + ("scales", "S"), lambda: dict(STRUCTURAL_ZERO)), r"horizons\.10000\.scales\.S is a survival",
     "671-673; C4 (7e02fd0's placement)"),
    (_put(_10K + ("scales", "F"), lambda: curve_rec(VAL_SS)), r"horizons\.10000\.scales\.F is a survival",
     "672; C4"),
    (_set(_10K + ("curve_points", "S"), []), r"horizons\.10000\.curve_points\.S is a survival", "672; C4"),
    (_put(_10K + ("components", "SigmaR_FF"), lambda: {"value": 0.5, "status": "convention", "rule": "x"}),
     r"horizons\.10000\.components\.SigmaR_FF is a survival fitted quantity", "673; C4"),
    (_put(_10K + ("components", "shares", "S"), lambda: {"row": 0.25, "donor": 0.25, "cell": 0.5}),
     r"horizons\.10000\.components\.shares\.S is a survival fitted quantity", "673; C4"),
    (_set(_10K + ("bootstrap", "ci95", "R_SS"), [0.1, 0.2]),
     r"horizons\.10000\.bootstrap\.ci95\.R_SS is a survival fitted quantity", "673; C4"),
    (_set(_10K + ("bootstrap", "ci95", "E_CS"), [0.1, 0.2]),
     r"horizons\.10000\.bootstrap\.ci95\.E_CS is a survival fitted quantity", "673; C4"),
    (_set(_10K + ("components", "at_box"), ["R_SS"]), r"horizons\.10000\.components\.at_box \['R_SS'\] is not",
     "674; C4"),
    # ---- C4: the declarations, whatever the status
    (_put(_20K + ("channels", "S"), counts_rec), r"missing field horizons\.20000\.channels\.S\.status$",
     "671-673; C4 (unavailable)"),
    (_set(_20K + ("channels", "F", "M_H"), 247), r"horizons\.20000\.channels\.F\.M_H 247 is not the registered 0",
     "671; C4 (unavailable)"),
    (_set(_10K + ("channels", "S", "reason"), "no survivors"), r"horizons\.10000\.channels\.S\.reason .* is not",
     "671-672; C4"),
    (_set(_10K + ("channels", "S", "status"), "unavailable"),
     r"horizons\.10000\.channels\.S\.status 'unavailable' is not the registered 'structural_zero'", "671; C4"),
    (_set(_10K + ("channels", "S", "M_H"), 0.0), r"horizons\.10000\.channels\.S\.M_H 0\.0 is not the registered 0",
     "671; C4"),
    (_upd(_20K + ("channels", "F"), note="x"), r"horizons\.20000\.channels\.F carries keys outside", "671-673; C4"),
    (_set(_10K + ("channels", "S"), None), r"horizons\.10000\.channels\.S is null", "671-673; C4"),
    (_upd(_20K + ("channels",), X={}), r"horizons\.20000\.channels has keys \['X'\] outside", "751; C4"),
    # ---- C4.1: the capture-only fit
    (_set(_10K + ("components", "fit"), "constrained"), r"horizons\.10000\.components\.fit 'constrained' is refused",
     "675-678; C4.1"),
    (_set(_10K + ("components", "SigmaE"), [[0.5 + 2 ** -20]]), r"horizons\.10000\.components\.SigmaE \[0\]\[0\]",
     "677; C4.1"),
    (_cap_fit(-0.125, 0.125), r"rho_R -0\.125, rho_D 0\.125: an ok capture-only fit needs", "676-678; C4.1"),
    (_cap_fit(0.75, 0.375), r"rho_R 0\.75, rho_D 0\.375: an ok capture-only fit needs", "676-678; C4.1"),
    (_put(_10K + ("components", "multistart"), lambda: {"starts": 16}),
     r"horizons\.10000\.components\.multistart must be null", "678; C4.1"),
    (_set(_10K + ("components", "unconstrained_problems"), ["SigmaD is not PSD"]),
     r"horizons\.10000\.components\.unconstrained_problems .* disagrees with fit 'unconstrained'", "676-678; C4.1"),
    (_set(_20K + ("components",), {}), r"horizons\.20000\.components must be null when the status is unavailable",
     "751; C4.1, L1701"),
    (_set(_20K + ("reasons",), []), r"horizons\.20000\.reasons must name a reason", "751; C4.1, L1701"),
    # ---- the horizon contents (Codex: empty records passed): containers, types, the values the encoding fixes
    (_set(_5K + ("components",), {}), r"missing field horizons\.5000\.components\.SigmaR$", "751, L1745"),
    (_set(_5K + ("bootstrap",), {}), r"missing field horizons\.5000\.bootstrap\.draws$", "751, L1671"),
    (_set(_5K + ("channels",), {}), r"missing field horizons\.5000\.channels\.C$", "751, L1690"),
    (_set(_5K + ("scales",), {}), r"missing field horizons\.5000\.scales\.C$", "751, L1690"),
    (_set(_5K + ("nu0",), {}), r"missing field horizons\.5000\.nu0\.C$", "751, L1690"),
    (_set(_5K + ("curve_points",), {}), r"missing field horizons\.5000\.curve_points\.C$", "751, L1690"),
    (_set(_5K + ("groups",), {}), r"missing field horizons\.5000\.groups\.R_CC$", "751, L1741"),
    (_set(_5K + ("grid_validation",), {}), r"missing field horizons\.5000\.grid_validation\.label$", "751, L1742"),
    (_set(_10K + ("components",), {}), r"missing field horizons\.10000\.components\.SigmaR$", "751; C4.1"),
    (_set(_10K + ("bootstrap",), {}), r"missing field horizons\.10000\.bootstrap\.draws$", "751; C4.1"),
    (_set(_10K + ("channels",), {}), r"missing field horizons\.10000\.channels\.C$", "751; C4"),
    (_set(_10K + ("groups",), {}), r"missing field horizons\.10000\.groups\.R_CC$", "751; C4.1"),
    (_set(_5K + ("channels", "C", "rows"), -1), r"horizons\.5000\.channels\.C\.rows -1 is not a non-negative", "L947"),
    (_set(_5K + ("channels", "S", "usable"), 120.0), r"horizons\.5000\.channels\.S\.usable 120\.0 is not", "L947"),
    (_set(_5K + ("channels", "F", "saturated"), "3"), r"horizons\.5000\.channels\.F\.saturated '3' is not", "L947"),
    (_set(_5K + ("channels", "C"), None), r"horizons\.5000\.channels\.C must be an object", "L1690"),
    (_set(_5K + ("scales", "S"), None), r"horizons\.5000\.scales\.S is null \(refused at 5k", "692 (R7), 751"),
    (_set(_5K + ("scales", "C", "s"), [0.55, 0.30, 0.40]), r"scales\.C\]: the values are not monotone", "L1549"),
    (_set(_5K + ("scales", "C", "x"), []), r"scales\.C\]: 0 knots", "L1549"),
    (_set(_5K + ("scales", "C", "direction"), None), r"horizons\.5000\.scales\.C\.direction None is refused",
     "L1546"),
    (_set(_5K + ("scales", "C", "blocks"), 2), r"horizons\.5000\.scales\.C\.blocks 2 is not the number of knots 3",
     "L1546-1547"),
    (_set(_5K + ("scales", "F", "extrapolation"), "linear"), r"horizons\.5000\.scales\.F\.extrapolation is not",
     "L1547-1548"),
    (_set(_5K + ("scales", "C", "cells"), 0), r"horizons\.5000\.scales\.C\.cells 0 is not an integer >= 1", "L1546"),
    (_set(_5K + ("scales", "C", "support"), [1.0, -1.0]), r"horizons\.5000\.scales\.C\.support must be", "L1546"),
    (_put(_5K + ("nu0", "C"), lambda: nu0_rec("unavailable")),
     r"horizons\.5000\.nu0\.C status 'unavailable' is refused \(the capture channel", "692 (R7)"),
    (_set(_5K + ("nu0", "S", "cells"), 2), r"horizons\.5000\.nu0\.S\.cells 2 is not an integer >= 3", "L1598-1604"),
    (_set(_5K + ("nu0", "S", "excess_log_variance"), None),
     r"horizons\.5000\.nu0\.S\.excess_log_variance None is not a finite number", "L1604"),
    (_set(_10K + ("nu0", "C", "nu0"), -1.0), r"horizons\.10000\.nu0\.C is estimated but nu0 -1\.0", "L1608"),
    (_set(("map_variance", "nu0", "S", "sampling_log_variance"), "0.03"),
     r"map_variance\.nu0\.S\.sampling_log_variance '0\.03' is not a finite number", "747, L1604"),
    (_set(_5K + ("curve_points", "C"), [[0.8, 0.25], [0.2, 0.5]]), r"horizons\.5000\.curve_points\.C is not sorted",
     "L1696"),
    (_set(_5K + ("curve_points", "S"), [[0.2]]), r"horizons\.5000\.curve_points\.S must be a list of", "L1696"),
    (_set(_5K + ("worlds",), ["w1", "w0"]), r"horizons\.5000\.worlds must be a sorted list", "L1698"),
    (_set(_5K + ("worlds",), [0, 1]), r"horizons\.5000\.worlds must be a sorted list", "L1698"),
    (_set(_5K + ("replicates",), 0), r"horizons\.5000\.replicates 0 is not an integer >= 1", "L1689"),
    (_set(_5K + ("replicates",), "64"), r"horizons\.5000\.replicates '64' is not an integer", "L1689"),
    (_set(_5K + ("incomplete_cells",), -1), r"horizons\.5000\.incomplete_cells -1 is not", "L1689"),
    (_set(_5K + ("reasons",), ["x"]), r"horizons\.5000\.reasons \['x'\] must be \[\] when the status is ok", "L1756"),
    (_upd(_5K + ("groups",), E_CS=group_rec()), r"horizons\.5000\.groups has keys \['E_CS'\] outside",
     "L220 (7e02fd0's group name)"),
    (_set(_5K + ("groups", "R_CC", "pairs"), 0), r"horizons\.5000\.groups\.R_CC\.pairs 0 is not", "L1710"),
    (_set(_5K + ("groups", "R_CC", "pairs"), True), r"horizons\.5000\.groups\.R_CC\.pairs True is not", "L1710"),
    (_set(_5K + ("groups", "D_SS", "at_box"), "no"), r"horizons\.5000\.groups\.D_SS\.at_box 'no' is not", "L1710"),
    (_set(_5K + ("groups", "R_SF", "rho_max"), 0.999), r"horizons\.5000\.groups\.R_SF\.rho_max 0\.999 is not",
     "L193, L1710"),
    (_set(_5K + ("groups", "T_CS", "nodes"), 0), r"horizons\.5000\.groups\.T_CS\.nodes 0 is not", "L1737"),
    (_set(_5K + ("grid_validation", "tolerance"), 0.01),
     r"horizons\.5000\.grid_validation\.tolerance 0\.01 is not noisebank\.GRID_LL_TOL", "L197, L1743"),
    (_set(_5K + ("grid_validation", "label"), "global certificate"), r"grid_validation\.label is not", "L1742"),
    (_upd(_5K + ("grid_validation",), refit_shift=0.01), r"grid_validation\.shift_flag False is not", "L198, L1744"),
    (_set(_5K + ("grid_validation", "refined"), 0), r"grid_validation\.refined is not true or false", "L1743"),
    (_set(_5K + ("components", "fit"), "barrier"), r"horizons\.5000\.components\.fit 'barrier' is refused", "L1407"),
    (_set(_5K + ("components", "fit"), "constrained"), r"unconstrained_problems \[\] disagrees with fit 'constrained'",
     "L1418-1421"),
    (_upd(_5K + ("components",), fit="constrained", unconstrained_problems=["SigmaE is not PSD"]),
     r"horizons\.5000\.components\.multistart must be an object", "L1434-1436"),
    (_set(_5K + ("components", "unconstrained_problems"), ["SigmaE is not PSD"]),
     r"disagrees with fit 'unconstrained'", "L1418-1421"),
    (lambda d: d["horizons"]["5000"]["components"]["SigmaR"][0].__setitem__(1, 0.06),
     r"horizons\.5000\.components\.SigmaR is not symmetric", "L1168"),
    (_set(_5K + ("components", "SigmaR"), SIGMA_D), r"horizons\.5000\.components\.SigmaR must be a 3x3 array",
     "L1168, L1745"),
    (lambda d: d["horizons"]["5000"]["components"]["SigmaE"][1].__setitem__(1, 0.5 + 2 ** -20),
     r"horizons\.5000\.components\.SigmaE \[1\]\[1\]", "L1162"),
    (_set(_5K + ("components", "SigmaR_FF", "value"), 0.25), r"horizons\.5000\.components\.SigmaR_FF is not",
     "L1749"),
    (_set(_5K + ("components", "SigmaR_FF", "status"), "estimate"), r"horizons\.5000\.components\.SigmaR_FF is not",
     "L1749"),
    (_set(_5K + ("components", "shares", "S", "donor"), 0.3), r"components\.shares\.S\.donor 0\.3 is not",
     "L1752-1753"),
    (_set(_5K + ("components", "box"), "|rho| <= 0.99"), r"horizons\.5000\.components\.box is not", "L1748"),
    (_set(_5K + ("components", "at_box"), ["X_YY"]), r"horizons\.5000\.components\.at_box \['X_YY'\] is not",
     "L1445"),
    (_set(_5K + ("components", "loglik"), None), r"horizons\.5000\.components\.loglik is not a finite", "L1446"),
    (_set(_5K + ("bootstrap", "draws"), 1000), r"horizons\.5000\.bootstrap\.draws 1000 is not the registered 999",
     "616, L1671"),
    (_set(_5K + ("bootstrap", "failure_rate"), 0.003), r"bootstrap\.failure_rate 0\.003 is not failed / draws",
     "L1670"),
    (_set(_5K + ("bootstrap", "ci95"), None), r"horizons\.5000\.bootstrap\.ci95 must be an object", "L1679"),
    (_set(_5K + ("bootstrap", "ci95", "R_CC"), [0.4, 0.05]), r"bootstrap\.ci95\.R_CC \[0\.4, 0\.05\] is not",
     "L1679"),
    (_set(_5K + ("bootstrap", "procedure"), "PCG64 resampling"), r"horizons\.5000\.bootstrap\.procedure is not",
     "L1672-1674"),
    (_set(_5K + ("bootstrap", "status"), "unavailable"), r"bootstrap\.status is unavailable within BOOT_FAIL_MAX",
     "L1676"),
    (_upd(_5K + ("bootstrap",), failed=60, failure_rate=60 / 999), r"bootstrap\.status is ok beyond BOOT_FAIL_MAX",
     "L1676"),
    (_set(_5K + ("bootstrap", "identification_rejections"), 4),
     r"bootstrap\.identification_rejections is not an integer in 0\.\.failed", "L1671"),
    # ---- round 4, clarification Addendum A. C7: screened (missing: the V5_FIELDS deletions)
    (_set(_5K + ("channels", "C", "screened"), -1), r"horizons\.5000\.channels\.C\.screened -1 is not a non-negative",
     "666-667; Addendum A C7"),
    (_set(_5K + ("channels", "C", "screened"), None), r"horizons\.5000\.channels\.C\.screened None is not",
     "666-667; Addendum A C7"),
    (_set(_5K + ("channels", "S", "screened"), 1.0), r"horizons\.5000\.channels\.S\.screened 1\.0 is not",
     "666-667; Addendum A C7"),
    (_set(_5K + ("channels", "F", "screened"), "2"), r"horizons\.5000\.channels\.F\.screened '2' is not",
     "666-667; Addendum A C7"),
    (_set(_10K + ("channels", "C", "screened"), True), r"horizons\.10000\.channels\.C\.screened True is not",
     "666-667; Addendum A C7"),
    (_set(_5K + ("channels", "F", "screened"), 5), r"horizons\.5000\.channels\.F\.screened 5 exceeds unidentified 4",
     "656, 666-667; Addendum A C7"),
    (_set(_20K + ("channels", "C", "screened"), 5),
     r"horizons\.20000\.channels\.C\.screened 5 exceeds unidentified 4", "656, 666-667; Addendum A C7"),
    (_upd(_10K + ("channels", "S"), screened=0),
     r"horizons\.10000\.channels\.S carries screened: a structural-zero declaration has no counts",
     "671-673; C4, Addendum A C7"),
    (_upd(_20K + ("channels", "F"), screened=0),
     r"horizons\.20000\.channels\.F carries screened: a structural-zero declaration has no counts",
     "671-673; C4, Addendum A C7 (unavailable)"),
    # ---- C8: an extra key at every record level of a horizon (both unavailable shapes stay admitted)
    (_upd(_5K, note="x"), r"horizons\.5000 has keys \['note'\] outside its ok record", "751; Addendum A C8"),
    (_upd(_10K, note="x"), r"horizons\.10000 has keys \['note'\] outside its ok record", "751; C4.1, Addendum A C8"),
    (_put(_20K + ("grid_validation",), lambda: dict(_horizon_record("5000", "ok")["grid_validation"])),
     r"horizons\.20000 has keys \['grid_validation'\] outside its unavailable record", "751; C4.1, Addendum A C8"),
    (_upd(_5K + ("channels", "C"), excluded=0), r"horizons\.5000\.channels\.C has keys \['excluded'\] outside",
     "L946-947; Addendum A C7, C8"),
    (_upd(_10K + ("channels", "C"), excluded=0), r"horizons\.10000\.channels\.C has keys \['excluded'\] outside",
     "L946-947; C4.1, Addendum A C8"),
    (_upd(_5K + ("scales", "S"), knots=3), r"horizons\.5000\.scales\.S has keys \['knots'\] outside",
     "L1546-1548; Addendum A C8"),
    (_upd(_20K + ("scales", "C"), knots=3), r"horizons\.20000\.scales\.C has keys \['knots'\] outside",
     "L1546-1548; C4.1, Addendum A C8"),
    (_upd(_5K + ("nu0", "C"), note="x"), r"horizons\.5000\.nu0\.C has keys \['note'\] outside",
     "L1597-1610; Addendum A C8 (estimated)"),
    (_upd(_5K + ("nu0", "S"), extra=1), r"horizons\.5000\.nu0\.S has keys \['extra'\] outside",
     "L1597-1610; Addendum A C8 (full_pooling)"),
    (_upd(_5K + ("nu0", "S"), note="x"), r"horizons\.5000\.nu0\.S\.note 'x' is not noisebank's text",
     "L1610; Addendum A C8 (full_pooling's one note)"),
    (_upd(_5K + ("nu0", "F"), cells=3), r"horizons\.5000\.nu0\.F has keys \['cells'\] outside",
     "L1597-1599; Addendum A C8 (unavailable)"),
    (_upd(_10K + ("nu0", "C"), extra=1), r"horizons\.10000\.nu0\.C has keys \['extra'\] outside",
     "L1597-1610; C4.1, Addendum A C8"),
    (_upd(("map_variance", "nu0", "S"), extra=1), r"map_variance\.nu0\.S has keys \['extra'\] outside",
     "747; Addendum A C8, C9"),
    (_upd(_5K + ("groups", "R_CC"), weight=1), r"horizons\.5000\.groups\.R_CC has keys \['weight'\] outside",
     "L1710-1711, L1737; Addendum A C8"),
    (_upd(_10K + ("groups", "D_CC"), weight=1), r"horizons\.10000\.groups\.D_CC has keys \['weight'\] outside",
     "L1710-1711, L1737; C4.1, Addendum A C8"),
    (_upd(_20K + ("groups", "R_CC"), nodes=241), r"horizons\.20000\.groups\.R_CC has keys \['nodes'\] outside",
     "L1716, L1737; C4.1, Addendum A C8 (unavailable: no nodes)"),
    (_upd(_5K + ("grid_validation",), certificate=False),
     r"horizons\.5000\.grid_validation has keys \['certificate'\] outside", "L1742-1744; Addendum A C8"),
    (_upd(_10K + ("grid_validation",), certificate=False),
     r"horizons\.10000\.grid_validation has keys \['certificate'\] outside", "L1742-1744; C4.1, Addendum A C8"),
    (_upd(_5K + ("components",), problems=[]), r"horizons\.5000\.components has keys \['problems'\] outside",
     "L1745-1753; Addendum A C8"),
    (_upd(_10K + ("components",), rho={}), r"horizons\.10000\.components has keys \['rho'\] outside",
     "L1745-1753; C4.1, Addendum A C8"),
    (_upd(_5K + ("components", "SigmaR_FF"), note="x"),
     r"horizons\.5000\.components\.SigmaR_FF has keys \['note'\] outside", "L1749-1751; Addendum A C8"),
    (_upd(_5K + ("components", "shares", "C"), total=1.0),
     r"horizons\.5000\.components\.shares\.C has keys \['total'\] outside", "L1752-1753; Addendum A C8"),
    (_upd(_10K + ("components", "shares", "C"), total=1.0),
     r"horizons\.10000\.components\.shares\.C has keys \['total'\] outside", "L1752-1753; C4.1, Addendum A C8"),
    (lambda d: constrained_fit(d, extra=1), r"horizons\.5000\.components\.multistart has keys \['extra'\] outside",
     "L1434-1436; Addendum A C8"),
    (_upd(_5K + ("bootstrap",), seed=0), r"horizons\.5000\.bootstrap has keys \['seed'\] outside",
     "L1671-1680; Addendum A C8"),
    (_upd(_5K + ("bootstrap",), reason="x"), r"horizons\.5000\.bootstrap has keys \['reason'\] outside",
     "L1676-1680; Addendum A C8 (an ok interval has no reason)"),
    (lambda d: unavailable_interval(d, extra=1), r"horizons\.5000\.bootstrap has keys \['extra'\] outside",
     "L1676-1678; Addendum A C8 (unavailable interval)"),
    (_upd(_10K + ("bootstrap",), seed=0), r"horizons\.10000\.bootstrap has keys \['seed'\] outside",
     "L1671-1680; C4.1, Addendum A C8"),
    # ---- C9: noise and map_variance against their sources in horizons["5000"] (noisebank.py L1788-1796)
    (_both_s_logit("C", lambda c: c.update(s=[0.56, 0.30, 0.20])),
     r"noise\.s_logit\.C differs from \{x, s, direction\} of horizons\.5000\.scales\.C", "746; Addendum A C9 (L1790)"),
    (_both_s_logit("S", lambda c: c.update(x=[-2.5, -1.2, -0.4])),
     r"noise\.s_logit\.S differs from \{x, s, direction\} of horizons\.5000\.scales\.S", "746; Addendum A C9 (L1790)"),
    (_both_s_logit("F", lambda c: c.pop("direction")),
     r"noise\.s_logit\.F differs from \{x, s, direction\} of horizons\.5000\.scales\.F", "746; Addendum A C9 (L1790)"),
    (_both_s_logit("C", lambda c: c.update(support=[-2.7, 0.9])),
     r"noise\.s_logit\.C differs from \{x, s, direction\} of horizons\.5000\.scales\.C",
     "746; Addendum A C9 (L1790: exactly x, s, direction)"),
    (_set(_5K + ("scales", "C", "s"), [0.56, 0.30, 0.20]),
     r"noise\.s_logit\.C differs from \{x, s, direction\} of horizons\.5000\.scales\.C",
     "746; Addendum A C9 (the source side)"),
    (_set(("noise", "SigmaR"), [[0.25, 0.05, 0.05], [0.05, 0.25, 0.15], [0.05, 0.15, 0.4]]),
     r"noise\.SigmaR differs from horizons\.5000\.components\.SigmaR", "746; Addendum A C9 (L1788, L1792)"),
    (_set(("noise", "SigmaD"), [[0.25, 0.04], [0.04, 0.25]]),
     r"noise\.SigmaD differs from horizons\.5000\.components\.SigmaD", "746; Addendum A C9 (L1788, L1792)"),
    (_set(("noise", "SigmaE"), [[0.5, 0.05], [0.05, 0.5]]),
     r"noise\.SigmaE differs from horizons\.5000\.components\.SigmaE", "746; Addendum A C9 (L1788, L1792)"),
    (_set(("map_variance", "nu0", "C", "nu0"), 13.0),
     r"map_variance\.nu0\.C differs from horizons\.5000\.nu0\.C", "747; Addendum A C9 (L1794)"),
    (_set(("map_variance", "nu0", "S", "excess_log_variance"), -0.02),
     r"map_variance\.nu0\.S differs from horizons\.5000\.nu0\.S", "747; Addendum A C9 (L1794)"),
    (_set(("map_variance", "nu0", "F", "reason"), "another reason"),
     r"map_variance\.nu0\.F differs from horizons\.5000\.nu0\.F", "747; Addendum A C9 (L1794)"),
    (_set(_5K + ("nu0", "C", "nu0"), 12.0),
     r"map_variance\.nu0\.C differs from horizons\.5000\.nu0\.C", "747; Addendum A C9 (the source side)"),
)


class TmpDir(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def write(self, name, data):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as f:
            f.write(data if isinstance(data, bytes) else rqlib.canonical(data))
        return p


# ================================================================== T1
@NEED_NP
class TestLawOracle(unittest.TestCase):
    LAWS = ((600, 247), (600, 600), (324, 324))
    A = (-8.0, -3.0, -1.0, -0.4, -0.36, 0.0, 0.18, 0.5, 2.0, 5.0, 8.0)
    S = (0.05, 0.2, 0.35, 0.6, 1.0, 2.0)

    def test_T1_1_categories_and_mean_vs_scalar_oracle(self):
        worst_p = worst_e = worst_count = worst_sum = 0.0
        for N, M in self.LAWS:
            a, s = np.meshgrid(np.array(self.A), np.array(self.S), indexing="ij")
            p = ol.category_probs(a, s, N, M)
            E = ol.expected_count(a, s, N, M)
            worst_sum = max(worst_sum, float(np.max(np.abs(p.sum(axis=-1) - 1.0))))
            for i, ai in enumerate(self.A):
                for j, sj in enumerate(self.S):
                    po = oracle_probs(ai, sj, N, M)
                    worst_p = max(worst_p, float(np.max(np.abs(p[i, j] - np.array(po)))))
                    eo = math.fsum(k * pk for k, pk in enumerate(po))
                    worst_e = max(worst_e, abs(E[i, j] - eo) / N)
                    worst_count = max(worst_count, abs(E[i, j] - eo))
        self.assertLessEqual(worst_sum, 1e-13)
        self.assertLessEqual(worst_e, 1e-13, "E[K]/N against the oracle")
        self.assertLessEqual(worst_p, 1e-13, "each category probability against the oracle")
        self.assertLessEqual(worst_count, 1e-11, "E[K] on the count scale")

    def test_T1_1_capped_top_category_has_infinite_upper_end(self):
        """P(K = M) = Phi((a - t_M) / s) under the cap; without the cap the same category is [t_M, t_{M+1})."""
        a, s = -0.3, 0.3
        p = ol.category_probs(a, s, 600, 247)
        tM = math.log((247 - 0.5) / (600 - 247 + 0.5))
        self.assertAlmostEqual(float(p[247]), _upper((tM - a) / s), delta=1e-15)
        unc = ol.category_probs(a, s, 600, 600)
        self.assertLess(float(unc[247]), float(p[247]) - 0.1)
        self.assertAlmostEqual(float(unc[247:].sum()), float(p[247]), delta=1e-13)

    def test_T1_2_definitional_quadrature(self):
        """E min{M, floor(N sigma(a + s Z) + 1/2)} by quadrature of the definition (rounding restored)."""
        n, L = 4_000_001, 12.0
        z = np.linspace(-L, L, n)
        h = z[1] - z[0]
        w = np.exp(-0.5 * z * z) / math.sqrt(2 * math.pi) * h
        for N, M, a, s in ((600, 247, -1.0, 0.3), (600, 247, -0.4, 0.25), (600, 247, -0.36, 0.6),
                           (600, 247, 0.5, 0.8), (600, 247, -3.0, 0.4), (324, 324, 2.0, 0.2), (324, 324, -4.0, 0.5)):
            q = 0.0
            for c0 in range(0, n, 500_000):
                zz = z[c0:c0 + 500_000]
                K = np.minimum(M, np.floor(N / (1 + np.exp(-(a + s * zz))) + 0.5))
                q += float(np.sum(K * w[c0:c0 + 500_000]))
            self.assertLessEqual(abs(float(ol.expected_fraction(a, s, N, M)) - q / N), 2e-6, (N, M, a, s))


@NEED_NP
class TestLocation(unittest.TestCase):
    def test_T1_3_solves_near_the_ceiling_mid_and_low(self):
        cases = [(C247 - 1e-4, 0.5, 600, 247), (C247 - 1e-3, 0.3, 600, 247), (C247 - 2e-3, 0.4, 600, 247),
                 (0.5 * C247, 0.4, 600, 247), (1e-3, 0.3, 600, 247), (1e-6, 0.25, 600, 247),
                 (0.999, 0.2, 324, 324), (0.5, 0.3, 324, 324), (1e-3, 0.55, 324, 324)]
        for mu, s, N, M in cases:
            a, r = ol.solve_location(mu, s, N, M)
            self.assertLessEqual(float(r), 1e-12)
            self.assertLessEqual(abs(oracle_mean(float(a), s, N, M) / N - mu), 1e-12, (mu, s, N, M))
        a, r = ol.solve_location(np.array([c[0] for c in cases[:6]]), np.array([c[1] for c in cases[:6]]), 600, 247)
        self.assertEqual(a.shape, (6,))
        self.assertLessEqual(float(np.max(r)), 1e-12)

    def test_T1_3_location_table_midpoints_and_knots(self):
        for ch in ("S", "C"):
            t = location_validation(ch)
            N, M = t.N, t.M
            c = M / N
            self.assertLessEqual(t.record["attempts"][-1]["max_midpoint_error"], ol.LOC_TOL)
            self.assertLessEqual(t.record["max_node_residual"], 1e-12)
            self.assertLessEqual(t.record["halvings"], ol.LOC_HALVINGS)
            curve = VAL_SC if ch == "C" else VAL_SS
            self.assertTrue(np.all(np.isin(ol.location_knots(curve, N, M), t.x)))     # the knots are nodes
            for xi in curve["x"]:                   # (an independent mapping logit(sigma(xi) / c))
                r = (1 / (1 + math.exp(-xi))) / c
                xk = xi if M == N else math.log(r / (1 - r))
                self.assertLessEqual(float(np.min(np.abs(t.x - xk))), 1e-12, (ch, xi))
            self.assertEqual(t.x[0], -12.0)
            self.assertEqual(t.x[-1], 12.0)
            xm = 0.5 * (t.x[:-1] + t.x[1:])            # every midpoint, re-evaluated
            mum = c / (1 + np.exp(-xm))
            err = np.abs(ol.expected_fraction(0.5 * (t.a[:-1] + t.a[1:]), ol.scale(curve, mum), N, M) - mum)
            self.assertLessEqual(float(err.max()), ol.LOC_TOL)
            rng = np.random.default_rng(7)             # a sample of midpoints through the scalar oracle
            for i in rng.choice(len(xm), 25, replace=False):
                s = float(ol.scale(curve, mum[i]))
                self.assertLessEqual(abs(oracle_mean(0.5 * (t.a[i] + t.a[i + 1]), s, N, M) / N - mum[i]), 2.0001e-7)

    def test_T1_3_locate_inside_outside_and_with_exact_axis(self):
        t = location_validation("S")
        eta = np.array([-14.0, -3.0, 0.2, 5.0, 13.0])
        mu = C247 / (1 + np.exp(-eta))
        a = t.locate(mu)
        a_eta = t.locate(mu, x=eta)
        self.assertLessEqual(float(np.max(np.abs(a - a_eta))), 1e-9)
        for ai, mi in zip(a_eta, mu):                  # outside |x| <= 12: the exact solve
            self.assertLessEqual(abs(oracle_mean(float(ai), float(ol.scale(VAL_SS, mi)), 600, 247) / 600 - mi), 2e-7)
        ex = ol.solve_location(mu[[0, 4]], ol.scale(VAL_SS, mu[[0, 4]]), 600, 247)[0]
        self.assertTrue(np.array_equal(a_eta[[0, 4]], ex))
        with self.assertRaises(ValueError):
            t.locate(mu, x=eta + 0.01)                 # (x must be logit(mu / c))
        with self.assertRaises(ValueError):
            t.locate(np.array([0.0]))

    def test_T1_3_exterior_knot_extends_the_table_but_beyond_12_the_solve_is_exact(self):
        """v5 1.7 (L300-302, L309): the knot union is literal, so a capture-curve knot at -13 extends the table to
        -13; but outside [-12, 12] the location is solved exactly whatever the table covers. Lookups at -12.5 (and
        other points between -13 and -12) equal the exact solve bit for bit, by mu alone and with the exact axis;
        inside +-12 the table still interpolates."""
        curve = {"x": [-13.0, -2.2, -0.6, 0.4], "s": [0.6, 0.55, 0.30, 0.20]}
        t = ol.build_location_table(curve, "C", 1.0, 324, 324, "0" * 64)
        self.assertEqual((float(t.x[0]), float(t.x[1])), (-13.0, -12.0))     # (the knot is a node; no grid below -12)
        xs = np.array([-12.5, -12.9, -12.25, -12.0 - 1e-9])
        mu = 1.0 / (1.0 + np.exp(-xs))
        exact = ol.solve_location(mu, ol.scale(curve, mu, 1.0), 324, 324)[0]
        self.assertTrue(np.array_equal(t.locate(mu, x=xs), exact))
        self.assertTrue(np.array_equal(t.locate(mu), exact))
        interp = np.interp(xs, t.x, t.a)                                       # (what an interpolation would give)
        self.assertNotEqual(float(interp[0]), float(exact[0]))
        inner = np.array([-11.995, 0.123])
        mi = 1.0 / (1.0 + np.exp(-inner))
        self.assertTrue(np.array_equal(t.locate(mi, x=inner), np.interp(inner, t.x, t.a)))


@NEED_NP
class TestSampler(unittest.TestCase):
    def test_T1_4_uncapped_draws_exceed_the_ceiling(self):
        """H.17 vector 37 / D8:118: near the ceiling the uncapped rounded values exceed 247; the law caps them."""
        mu, s = C247 - 2e-3, 0.4
        a = float(ol.solve_location(mu, s, 600, 247)[0])
        u = np.random.default_rng(20261113).standard_normal(2_000_000)
        unc = ol.rounded_count(a, s, u, 600, None)
        self.assertGreater(int((unc > 247).sum()), 1_000_000)
        K, loc, _ = ol.generate_counts(np.array([mu]), u[None, :], 600, 247, lambda m: np.full(m.shape, s),
                                       lambda m, i: np.full(m.shape, a))
        self.assertEqual(int(K.max()), 247)
        self.assertTrue(np.array_equal(K[0], np.minimum(247, unc)))

    def test_T1_5_analytic_mean_and_prohibited_substitutions(self):
        mu, s = C247 - 2e-3, 0.4
        a = float(ol.solve_location(mu, s, 600, 247)[0])
        self.assertLessEqual(abs(oracle_mean(a, s, 600, 247) / 600 - mu), 1e-12)
        a_unc = float(ol.solve_location(mu, s, 600, 600)[0])          # solve-then-cap
        self.assertGreater(abs(oracle_mean(a_unc, s, 600, 247) / 600 - mu), 1e-3)
        a247 = float(ol.solve_location(mu * 600 / 247, s, 247, 247)[0])   # 247-scale rounding, same mean
        self.assertLessEqual(abs(oracle_mean(a247, s, 247, 247) / 600 - mu), 1e-12)
        dP = oracle_probs(a, s, 600, 247)[247] - oracle_probs(a247, s, 247, 247)[247]
        self.assertGreater(abs(dP), 0.1)

    def test_T1_5_monte_carlo_mean_within_4_se(self):
        mu, s, n = C247 - 2e-3, 0.4, 2_000_000
        a = float(ol.solve_location(mu, s, 600, 247)[0])
        u = np.random.default_rng(31).standard_normal((1, n))
        K, _, _ = ol.generate_counts(np.array([mu]), u, 600, 247, lambda m: np.full(m.shape, s),
                                     lambda m, i: np.full(m.shape, a))
        se = math.sqrt(oracle_var(a, s, 600, 247)) / 600 / math.sqrt(n)
        self.assertLessEqual(abs(float(K.mean()) / 600 - mu), 4 * se)

    def test_T1_6_endpoints_generated_and_refusals(self):
        u = np.random.default_rng(1).standard_normal((3, 5))
        s_of = lambda m: ol.scale(VAL_SS, m)  # noqa: E731
        loc = lambda m, i: ol.solve_location(m, ol.scale(VAL_SS, m), 600, 247)[0]  # noqa: E731
        K, a, _ = ol.generate_counts(np.array([0.0, C247, 0.2]), u, 600, 247, s_of, loc)
        self.assertTrue(np.all(K[0] == 0) and np.all(K[1] == 247))
        self.assertEqual((a[0], a[1]), (-math.inf, math.inf))
        K0, _, _ = ol.generate_counts(np.zeros(3), u, 600, 0, s_of, loc)        # M_H = 0: every count 0
        self.assertTrue(np.all(K0 == 0))
        for bad in (-1e-12, C247 + 1e-12, float("nan"), float("inf")):
            with self.subTest(mu=bad), self.assertRaises(ValueError):
                ol.generate_counts(np.array([0.2, bad, 0.1]), u, 600, 247, s_of, loc)
        with self.assertRaises(ValueError):
            ol.generate_counts(np.array([1e-9]), u[:1], 600, 0, s_of, loc)       # (mu > 0 at M = 0)
        with self.assertRaises(ValueError):
            ol.solve_location(C247, 0.3, 600, 247)                                # (an endpoint has no location)

    def factors(self):
        return ol.psd_factors(SIGMA_R, SIGMA_D, SIGMA_E)

    def test_T3_1_latent_correlations_per_sharing_class(self):
        qi, pj = np.array([0, 0, 1, 1, 2]), np.array([0, 1, 0, 1, 2])
        R = 20000
        Z = ol.standard_normals(np.random.default_rng(5), 3, 3, len(qi), R)
        u = ol.latent(Z, self.factors(), qi, pj)
        cor = lambda x, y: float(np.corrcoef(x, y)[0, 1])  # noqa: E731
        tol = 4.5 / math.sqrt(R)
        SR, SD, SE = np.array(SIGMA_R), np.array(SIGMA_D), np.array(SIGMA_E)
        checks = [(u["C"][0], u["C"][1], SR[0, 0]), (u["S"][0], u["S"][1], SR[1, 1]),   # same prey row
                  (u["C"][0], u["C"][2], SD[0, 0]), (u["S"][1], u["S"][3], SD[1, 1]),   # same donor
                  (u["C"][0], u["S"][0], SR[0, 1] + SD[0, 1] + SE[0, 1]),               # same cell C-S
                  (u["C"][0], u["S"][1], SR[0, 1]),                                     # same prey, C-S
                  (u["C"][2], u["F"][1], SR[0, 2]), (u["S"][3], u["F"][1], SR[1, 2]),   # exposed - free
                  (u["C"][0], u["C"][4], 0.0), (u["S"][0], u["F"][2], 0.0),             # nothing shared
                  (u["C"][0][:-1], u["C"][0][1:], 0.0), (u["F"][0][:-1], u["F"][0][1:], 0.0)]   # replicates
        for i, (x, y, want) in enumerate(checks):
            self.assertLessEqual(abs(cor(x, y) - want), tol, i)
        for ch in ("C", "S", "F"):
            self.assertLessEqual(abs(float(u[ch].var()) - 1.0), 0.03, ch)

    def test_T3_2_singular_psd_rows_generate_and_non_psd_is_refused(self):
        b = np.array([0.05, 0.15])
        A = np.array(SIGMA_R)[:2, :2]
        ff = float(b @ np.linalg.solve(A, b))             # the free-row convention: Schur complement 0
        SR = [[0.25, 0.05, 0.05], [0.05, 0.25, 0.15], [0.05, 0.15, ff]]
        f = ol.psd_factors(SR, SIGMA_D, SIGMA_E)
        self.assertLessEqual(float(np.max(np.abs(f["R"] @ f["R"].T - np.array(SR)))), 1e-12)
        self.assertLess(float(np.min(np.linalg.eigvalsh(np.array(SR)))), 1e-12)
        Z = ol.standard_normals(np.random.default_rng(2), 2, 2, 3, 4000)
        u = ol.latent(Z, f, np.array([0, 1, 1]), np.array([0, 0, 1]))
        self.assertTrue(all(np.all(np.isfinite(v)) for v in u.values()))
        bad = [[0.25, 0.05, 0.05], [0.05, 0.25, 0.15], [0.05, 0.15, ff - 0.01]]
        with self.assertRaisesRegex(ValueError, "SigmaR: not PSD"):
            ol.psd_factors(bad, SIGMA_D, SIGMA_E)

    def test_T3_3_no_second_layer(self):
        """The replicate variance of z = ell_B(K) is the law's exact category variance V_z (no binomial layer)."""
        mu = 0.3
        s = float(ol.scale(VAL_SC, mu))
        a = float(ol.solve_location(mu, s, 324, 324)[0])
        n = 400_000
        u = np.random.default_rng(11).standard_normal((1, n))
        K, _, _ = ol.generate_counts(np.array([mu]), u, 324, 324, lambda m: ol.scale(VAL_SC, m),
                                     lambda m, i: np.full(m.shape, a))
        z = ol.empirical_logit(K[0], 324)
        m, V = (float(v) for v in ol.logit_moments(a, s))
        p = ol.category_probs(a, s, 324, 324)
        ell = ol.empirical_logit(np.arange(325), 324)
        m4 = float(p @ (ell - m) ** 4)
        se = math.sqrt((m4 - V * V) / n)
        self.assertLessEqual(abs(float(z.var()) - V), 4 * se)
        self.assertLessEqual(abs(float(z.mean()) - m), 4 * math.sqrt(V / n))
        binom = V + 1.0 / (324 * mu * (1 - mu))              # what a second binomial layer would add (roughly)
        self.assertGreater(abs(float(z.var()) - binom), 40 * se)


# ================================================================== T1-7
@NEED_NP
class TestFitterTable(unittest.TestCase):
    def test_T1_7_validation_curve_certifies_under_the_v5_policy(self):
        t = fitter_validation()
        r = t.record
        depths = [int(d) for d in r["depth_histogram"]]
        self.assertLessEqual(max(depths), ol.FIT_DEPTH_CAP)
        self.assertLessEqual(r["nodes"], ol.FIT_NODE_CAP)
        self.assertTrue(2600 <= r["nodes"] <= 2750, r["nodes"])     # (v5 1.7c's prototype: 2,669 nodes, depth 6)
        self.assertTrue(5 <= max(depths) <= 7, depths)
        self.assertEqual(sum(r["depth_histogram"].values()), r["segments"])
        self.assertTrue(r["m_z_strictly_increasing"] and np.all(np.diff(t.m) > 0))
        self.assertLessEqual(r["max_location_residual"], 1e-12)
        self.assertLessEqual(r["max_inversion_residual"], ol.FIT_INVERT_TOL)
        for k in ol.FIT_ITEMS:
            self.assertLessEqual(r["worst"][k]["value"], ol.FIT_TOL[k], k)
        lo, hi = r["inserted_x_range"]
        self.assertTrue(4.5 < lo and hi < 6.2, (lo, hi))
        self.assertTrue(np.all(np.isin(ol.fitter_initial_nodes(VAL_SC), t.x)))
        self.assertTrue(all(np.any(t.x == k) for k in VAL_SC["x"]))
        self.assertFalse(np.any(np.abs(t.x[:, None] - np.array(VAL_SC["x"])[None, :])[~np.isin(t.x, VAL_SC["x"])]
                                <= ol.FIT_KNOT_GAP))

    def test_T1_7_repeated_production_certification_of_the_final_table(self):
        """A REPEATED PRODUCTION CERTIFICATION, not an independent oracle: certify_segments (the code that built the
        table) runs again on the FINAL table, every refined segment and a sample of the others, and the production
        lookup reproduces its interpolants. An error shared by the build and the certifier (e.g., in logit_moments)
        passes this; the independent evidence is test_T1_7_logit_moments_vs_scalar_oracle and
        test_T1_7_probes_inverted_independently."""
        t = fitter_validation()
        segs = np.arange(len(t.x) - 1)
        refined = segs[(t.x[1:] - t.x[:-1]) < 0.0099]
        rng = np.random.default_rng(3)
        pick = np.union1d(refined, rng.choice(segs, 150, replace=False))
        left = (t.A[pick], t.m[pick], t.V[pick], t.L[pick])
        right = (t.A[pick + 1], t.m[pick + 1], t.V[pick + 1], t.L[pick + 1])
        cert = ol.certify_segments(VAL_SC, t.x[pick], t.x[pick + 1], left, right)
        self.assertFalse(cert["fail"].any())
        for k in ol.FIT_ITEMS:                                # and through the production lookup
            self.assertLessEqual(float(cert["errors"][k].max()), ol.FIT_TOL[k])
        z = cert["z"].ravel()
        ev = t.evaluate(z)
        j = np.repeat(pick, 3)
        lam = (z - t.m[j]) / (t.m[j + 1] - t.m[j])
        self.assertLessEqual(float(np.max(np.abs(ev["W"] - (t.V[j] + lam * (t.V[j + 1] - t.V[j]))))), 1e-15)

    def test_T1_7_logit_moments_vs_scalar_oracle(self):
        """v5 1.7b (L341-344, (ii)): m_z and the centered V_z of the empirical logit against the test-local scalar
        category oracle (explicit intervals, math.fsum), from the deep tails through saturation, both laws."""
        worst_m = worst_v = 0.0
        for N, M in ((324, 324), (600, 247)):
            for a in (-9.0, -5.0, -2.2, -0.6, 0.0, 0.4, 2.0, 4.8, 5.775, 6.5, 9.0):
                for s in (0.05, 0.2, 0.3, 0.55, 1.0):
                    m, v = (float(u) for u in ol.logit_moments(a, s, N, M))
                    mo, vo = oracle_logit_moments(a, s, N, M)
                    worst_m = max(worst_m, abs(m - mo))
                    worst_v = max(worst_v, abs(v - vo) / (vo + 1e-300))
        self.assertLessEqual(worst_m, 1e-12, "m_z")
        self.assertLessEqual(worst_v, 1e-9, "V_z (relative)")

    def test_T1_7_probes_inverted_independently(self):
        """v5 1.7b items 1-4 at probes of refined and unrefined segments of the final table, against a scalar
        bisection in x over the test-local exact pipeline (oracle_curve, oracle_location, oracle_logit_moments; no
        obslaw solver, moments or inversion): the inverse fraction, W, L and the score location against mu*, and
        the round trip m_z(mu_hat(z)) evaluated by the oracle."""
        t = fitter_validation()
        widths = np.diff(t.x)
        refined = np.flatnonzero(widths < 0.0099)
        codex = int(np.searchsorted(t.x, 5.775 + 1e-7) - 1)                   # (a segment of Codex's probe region)
        unrefined = [int(np.searchsorted(t.x, v) - 1) for v in (-6.003, -2.205, 0.005, 3.005)]
        probes = [(codex, f) for f in (0.25, 0.5, 0.75)] + [(int(refined[k]), 0.5) for k in (0, len(refined) // 2, -1)]
        probes += [(j, 0.5) for j in unrefined]
        self.assertTrue(widths[codex] < 0.0099 and all(widths[j] > 0.0099 for j in unrefined))
        for j, f in probes:
            z = float(t.m[j] + f * (t.m[j + 1] - t.m[j]))
            ev = t.evaluate(np.array([z]))
            xh, W, A, L = (float(ev[k][0]) for k in ("x", "W", "A", "L"))
            mus, ss, _, ms, vs = oracle_inverse(VAL_SC, z, float(t.x[j]), float(t.x[j + 1]))
            self.assertLessEqual(abs(ms - z), 1e-9, (j, f))                    # (the reference itself converged)
            muh = 1.0 / (1.0 + math.exp(-xh))
            rt = oracle_pipeline(VAL_SC, xh)[3]
            with self.subTest(segment=j, fraction=f, x=float(t.x[j])):
                self.assertLessEqual(abs(rt - z), ol.FIT_TOL["roundtrip"])
                self.assertLessEqual(abs(muh - mus), ol.FIT_TOL["inverse"])
                self.assertLessEqual(abs(W - vs), ol.FIT_TOL["W"] * vs)
                self.assertLessEqual(abs(L - ss * ss), ol.FIT_TOL["L"] * ss * ss)
                self.assertLessEqual(abs(oracle_mean(A, ss, 324, 324) / 324 - mus), ol.FIT_TOL["score"])

    def test_T1_7_negative_control_v4_uniform_rule_refuses_at_codex_probe(self):
        """v4's rule (uniform h = 0.01 / 2^k, k <= 4): the z-midpoint of the segment containing x = 5.775 fails the
        W item at every spacing; at h = 0.000625 it is Codex's probe (W relative error 1.131598e-3)."""
        rel = []
        for k in range(5):
            h = 0.01 / 2 ** k
            xl = math.floor(5.775 / h + 1e-9) * h
            x = np.array([xl, xl + h])
            a, m, v, L, _ = ol._fit_values(VAL_SC, x)
            cert = ol.certify_segments(VAL_SC, x[:1], x[1:], (a[:1], m[:1], v[:1], L[:1]),
                                       (a[1:], m[1:], v[1:], L[1:]))
            rel.append(float(cert["errors"]["W"][0, 1]))
            self.assertTrue(cert["fail"][0], h)
            if k == 4:
                self.assertAlmostEqual(float(cert["z"][0, 1]), 5.373697357126879, delta=1e-9)
        self.assertAlmostEqual(rel[4], 1.131598e-3, delta=2e-9)
        for got, want in zip(rel, (0.2583325, 0.0592175, 0.01764754, 0.004531487, 0.001131598)):
            self.assertAlmostEqual(got, want, delta=1e-6 * max(1.0, want * 1e3))
            self.assertGreater(got, ol.FIT_TOL["W"])

    def test_T1_7_constant_curve_displaced_inverse_is_refused(self):
        """Constant S_C (L trivially exact), refinement disabled (one certification pass), the inverse displaced:
        the round-trip and inverse-fraction items refuse it although W, L and the score location pass."""
        curve = {"x": [0.0], "s": [0.3]}
        x = np.arange(-200, 201) * 0.01
        a, m, v, L, _ = ol._fit_values(curve, x)
        good = ol.certify_segments(curve, x[:-1], x[1:], (a[:-1], m[:-1], v[:-1], L[:-1]), (a[1:], m[1:], v[1:], L[1:]))
        self.assertFalse(good["fail"].any())
        cert = ol.certify_segments(curve, x[:-1], x[1:], (a[:-1], m[:-1], v[:-1], L[:-1]),
                                   (a[1:], m[1:], v[1:], L[1:]), inverse=(x[:-1] + 1e-3, x[1:] + 1e-3))
        self.assertTrue(cert["fail"].all())
        e = cert["errors"]
        self.assertTrue(np.all(e["roundtrip"] > ol.FIT_TOL["roundtrip"]) and np.all(e["inverse"] > ol.FIT_TOL["inverse"]))
        self.assertEqual(float(e["L"].max()), 0.0)
        for k in ("W", "score"):
            self.assertLessEqual(float(e[k].max()), ol.FIT_TOL[k], k)

    def test_T1_7_depth_and_node_caps_refuse(self):
        few = lambda curve: np.arange(575, 581) * 0.01  # noqa: E731  (the near-saturation staircase only)
        with mock.patch.object(ol, "fitter_initial_nodes", few), mock.patch.object(ol, "FIT_DEPTH_CAP", 3):
            with self.assertRaisesRegex(ValueError, "depth 3"):
                ol.build_fitter_table(VAL_SC, "0" * 64)
        with mock.patch.object(ol, "fitter_initial_nodes", few), mock.patch.object(ol, "FIT_NODE_CAP", 10):
            with self.assertRaisesRegex(ValueError, "exceed 10"):
                ol.build_fitter_table(VAL_SC, "0" * 64)

    def test_T1_7_over_cap_initial_grid_is_refused_before_any_evaluation(self):
        """v5 1.7b (L397-398): the table may not exceed the node cap, the initial grid included. (1) A smooth,
        already certifiable initial grid of 201 nodes under a cap lowered to 150; (2) the real 2,401-node initial
        grid of a smooth constant curve under a cap lowered to 2,000: both refused before any node is evaluated or
        any segment certified."""
        def never(name):
            def f(*a, **k):
                raise AssertionError(f"{name} ran on an over-cap initial grid")
            return f
        smooth = {"x": [0.0], "s": [0.3]}
        grid = lambda curve: np.arange(-100, 101) * 0.01  # noqa: E731
        with mock.patch.object(ol, "_fit_values", never("_fit_values")), \
                mock.patch.object(ol, "certify_segments", never("certify_segments")):
            with mock.patch.object(ol, "fitter_initial_nodes", grid), mock.patch.object(ol, "FIT_NODE_CAP", 150):
                with self.assertRaisesRegex(ValueError, "initial grid has 201 nodes, over the node cap 150"):
                    ol.build_fitter_table(smooth, "0" * 64)
            with mock.patch.object(ol, "FIT_NODE_CAP", 2000):
                with self.assertRaisesRegex(ValueError, "initial grid has 2401 nodes, over the node cap 2000"):
                    ol.build_fitter_table(smooth, "0" * 64)
        with mock.patch.object(ol, "fitter_initial_nodes", grid), mock.patch.object(ol, "FIT_NODE_CAP", 201):
            self.assertEqual(ol.build_fitter_table(smooth, "0" * 64).record["nodes"], 201)   # (at the cap: built)

    def test_T1_7_over_cap_knot_set_is_refused_before_any_allocation(self):
        """A knot set larger than the node cap is refused before the initial grid (or any array) is built."""
        curve = {"x": [k * 1e-3 for k in range(60)], "s": [0.3] * 60}
        with mock.patch.object(ol, "FIT_NODE_CAP", 50), \
                mock.patch.object(ol.np, "arange", side_effect=AssertionError("an array was allocated")):
            with self.assertRaisesRegex(ValueError, "60 curve knots exceed the node cap 50"):
                ol.build_fitter_table(curve, "0" * 64)
            with self.assertRaisesRegex(ValueError, "60 curve knots exceed the node cap 50"):
                ol.fitter_initial_nodes(curve)

    def test_T1_7_initial_nodes_sorted_search_equals_the_rule_without_a_dense_matrix(self):
        """v5 1.7b's initial-node rule, computed here densely (min over all knots), equals fitter_initial_nodes on
        knots near grid nodes (inside and outside 1e-9), outside [-12, 12], unsorted and duplicated; and with 5,000
        knots fitter_initial_nodes allocates far less than the 2,401 x 5,000 distance matrix (96 MB)."""
        def dense(knots):
            xu = np.arange(-1200, 1201) * 0.01
            k = np.asarray(knots, float)
            xu = xu[np.min(np.abs(xu[:, None] - k[None, :]), axis=1) > 1e-9]
            return np.union1d(xu, k[(k >= -12.0) & (k <= 12.0)])
        rng = np.random.default_rng(13)
        cases = [[0.0], [-2.2, -0.6, 0.4], [0.5 + 5e-10, 0.5 + 2e-9, -11.99 - 1e-9, 12.0 + 5e-10, 12.3, -13.0],
                 [3.0, -1.0, 3.0, 2.5], rng.uniform(-13, 13, 300).tolist(),
                 (np.round(rng.uniform(-12, 12, 200), 2) + rng.choice([-2e-9, -5e-10, 0.0, 5e-10, 2e-9], 200)).tolist()]
        for knots in cases:
            self.assertTrue(np.array_equal(ol.fitter_initial_nodes({"x": knots}), dense(knots)), knots[:4])
        big = sorted(set(rng.uniform(-11.9, 11.9, 5000).tolist()))
        tracemalloc.start()
        try:
            got = ol.fitter_initial_nodes({"x": big})
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 8 << 20, f"peak {peak} bytes")
        self.assertTrue(np.all(np.isin(big, got)) and np.all(np.diff(got) > 0))

    def test_T1_7_non_monotone_m_z_is_refused(self):
        x = np.array([0.0, 0.01, 0.02])
        a, m, v, L, _ = ol._fit_values(VAL_SC, x)
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            ol.FitterTable(x, m[::-1], v, a, L, {}, {})
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            ol.certify_segments(VAL_SC, x[1:], x[:-1], (a[1:], m[1:], v[1:], L[1:]), (a[:-1], m[:-1], v[:-1], L[:-1]))

    def test_T1_7_extrapolation_holds_end_nodes_and_counts(self):
        t = fitter_validation()
        z = np.array([t.m[0] - 1.0, t.m[0], 0.0, t.m[-1], t.m[-1] + 0.5, t.m[-1] + 3.0])
        ev = t.evaluate(z)
        self.assertEqual(ev["extrapolated"].tolist(), [True, False, False, False, True, True])
        for name, y in (("x", t.x), ("W", t.V), ("A", t.A), ("L", t.L)):
            self.assertEqual((ev[name][0], ev[name][1]), (y[0], y[0]))
            self.assertEqual((ev[name][3], ev[name][4], ev[name][5]), (y[-1], y[-1], y[-1]))
        zc = np.array([t.m[0] - 1.0, -1.0, 0.0, 1.0, t.m[-1] + 0.5, t.m[-1] + 3.0])   # (clearly in or out)
        evc = t.evaluate(zc)
        wv = ol.WorkingVariance(t, "tag")
        p = 1 / (1 + np.exp(-zc))
        w = wv(p)
        self.assertEqual(wv.extrapolated, 3)
        wv(np.array([0.5]))
        self.assertEqual((wv.extrapolated, wv.evaluations, wv.identity), (3, 7, "tag"))
        self.assertLessEqual(float(np.max(np.abs(w - evc["W"]))), 1e-12 * float(np.max(evc["W"])))
        sl = ol.ScoreLaw(t, "tag")
        A, L = sl(p)
        self.assertEqual(sl.extrapolated, 3)
        self.assertEqual((A[0], L[-1]), (t.A[0], t.L[-1]))
        with self.assertRaises(ValueError):
            wv(np.array([0.0, 0.5]))

    def test_T1_7_nodes_evaluate_exactly_and_slope_range_maximum(self):
        t = fitter_validation()
        ev = t.evaluate(t.m[::97])
        self.assertTrue(np.array_equal(ev["x"], t.x[::97]) and np.array_equal(ev["A"], t.A[::97]))
        rng = np.random.default_rng(9)
        lo = rng.uniform(t.m[0] - 1, t.m[-1] + 1, 400)
        hi = lo + rng.exponential(0.3, 400)
        got = t.slope_max(lo, hi)
        k = np.abs(t.kappa)
        for i in range(400):
            sel = (t.m[1:] >= lo[i]) & (t.m[:-1] <= hi[i])
            self.assertEqual(got[i], float(k[sel].max()) if sel.any() else 0.0, i)
        self.assertEqual(float(t.slope_max(t.m[-1] + 1, t.m[-1] + 2)), 0.0)
        self.assertEqual(float(t.slope_max(t.m[0], t.m[0])), k[0])
        self.assertEqual(t.lat_var_min, float(t.L.min()))
        self.assertGreater(float(k.max()), 14.0)          # (v5 1.7b: the slopes reach 14.3 in the interior)


# ================================================================== T5-5 the D8 streams
@NEED_NP
class TestD8Streams(unittest.TestCase):
    def test_T5_5_generator_and_published_vector(self):
        r = rqlib.SplitMix64(0)
        self.assertEqual([r.next64() for _ in range(3)], [0xE220A8397B1DCDAF, 0x6E789E6AA1B965F4, 0x06C45D188009454F])
        self.assertIsInstance(ol.d8_stream(REFIT), rqlib.SplitMix64)

    def test_T5_5_actual_draws_equal_the_pinned_independent_values(self):
        for text, pin in PINNED.items():
            self.assertEqual(ol.stream_seed_d8(text), pin["seed"])
            self.assertEqual(ref_seed(text), pin["seed"])
            g = ref_sm64(pin["seed"])
            self.assertEqual([next(g) for _ in range(4)], pin["outs"])
            r = ol.d8_stream(text)
            self.assertEqual([r.next64() for _ in range(4)], pin["outs"])
            self.assertEqual(ol.splitmix_below(ol.d8_stream(text), 8, 16).tolist(), pin["below8"])
            self.assertEqual(ol.splitmix_uniforms(ol.d8_stream(text), 3).tolist(), pin["unif"])
            got = ol.splitmix_normals(ol.d8_stream(text), 4)
            self.assertLessEqual(float(np.max(np.abs(got - np.array(pin["normals"])))), 1e-14)
            rec = ol.stream_record(text)
            self.assertEqual((rec["seed"], rec["first_outputs"], rec["generator"]),
                             (pin["seed"], pin["outs"][:2], "rqlib.SplitMix64"))
            self.assertEqual(ref_seed(text.replace("AnnexH/D8/1/", "AnnexH/1/")), pin["annexH1"])
            self.assertNotEqual(pin["annexH1"], pin["seed"])

    def test_T5_5_below_is_unbiased_rejection(self):
        n = 3 * 2 ** 61                                         # (rejection probability 1/4)
        limit = (1 << 64) - ((1 << 64) % n)
        g, r = ref_sm64(ref_seed(REFIT)), ol.d8_stream(REFIT)
        want = []
        while len(want) < 40:
            x = next(g)
            if x < limit:
                want.append(x % n)
        self.assertEqual(ol.splitmix_below(r, n, 40).tolist(), want)

    def test_T5_5_separation_of_refit_and_validation_streams(self):
        texts = [f"AnnexH/D8/1/noisebank/D8-refit/h{h}/bootstrap" for h in (5000, 10000, 20000)]
        for k in range(0, 11):
            for tag in (f"bank{k}", f"bank{k}-r2"):
                texts += [f"AnnexH/D8/1/noisebank/D8-validation/{tag}/{p}" for p in ("means", "rows", "donors", "cells", "free")]
        seeds = [ol.stream_seed_d8(t) for t in texts]
        self.assertEqual(len(set(seeds)), len(texts))
        inv = pow(GAMMA, -1, 1 << 64)
        window = 1 << 32                     # (SplitMix64 is counter based: streams overlap iff (s2 - s1) / GAMMA is small)
        for i in range(len(seeds)):
            for j in range(i + 1, len(seeds)):
                d = ((seeds[j] - seeds[i]) * inv) & M64
                self.assertGreater(min(d, (1 << 64) - d), window, (texts[i], texts[j]))
        firsts = [ol.d8_stream(t).next64() for t in texts]
        self.assertEqual(len(set(firsts)), len(texts))
        for t, s in zip(texts, seeds):
            self.assertNotEqual(ref_seed(t.replace("AnnexH/D8/1/", "AnnexH/1/")), s)
        for bad in ("AnnexH/1/noisebank/D8-refit/h5000/bootstrap", "noisebank/x", 5):
            with self.assertRaises(ValueError):
                ol.stream_seed_d8(bad)
        self.assertEqual(ol.d8_text("noisebank", "D8-refit", "h5000", "bootstrap"), REFIT)


# ================================================================== T5-3, T5-7, T2 the bank/3 loader
@NEED_NP
class TestBankArtifact(TmpDir):
    def load(self, doc=None, raw=None, flag=False, bound=True):
        p = self.write("bank.json", raw if raw is not None else rqlib.canonical(doc))
        return ol.BankArtifact(p, sha256=rqlib.sha256_file(p) if bound else None, allow_synthetic=flag)

    def refuses(self, mutate, pattern, flag=False):
        d = bank3_doc()
        mutate(d)
        with self.assertRaisesRegex(ValueError, pattern):
            self.load(d, flag=flag)

    def test_valid_artifact_loads(self):
        b = self.load(bank3_doc())
        self.assertEqual((b.nu0_C, b.M_H, b.law("C"), b.law("S")), (12.5, 247, (324, 324), (600, 247)))
        self.assertLessEqual(float(np.max(np.abs(b.factors["R"] @ b.factors["R"].T - np.array(SIGMA_R)))), 1e-12)
        self.assertAlmostEqual(b.factors["free_sd"], math.sqrt(0.5))
        d = bank3_doc()                         # (map_variance.nu0 and its source alike: Addendum A C9)
        d["map_variance"]["nu0"]["C"] = nu0_rec("full_pooling")
        d["horizons"]["5000"]["nu0"]["C"] = nu0_rec("full_pooling")
        self.assertIsNone(self.load(d).nu0_C)
        d = bank3_doc()                         # (the admitted variants of the exact records, Addendum A C8)
        for rec in (d["horizons"]["5000"]["nu0"]["S"], d["map_variance"]["nu0"]["S"]):
            rec["note"] = nb_text("nu0 beyond the float range")              # (full_pooling's one note, L1610)
        constrained_fit(d)                                                 # (the multi-start branch, L1423-1440)
        unavailable_interval(d)                                            # (L1676-1678)
        unavailable_interval(d, "10000")
        self.load(d)
        d = bank3_doc()                         # (C4.1: a capture-only 10k fit may be unavailable, 20k ok; groups
        d["horizons"]["10000"] = _horizon_record("10000", "unavailable")   # of an unavailable record are optional)
        del d["horizons"]["10000"]["groups"]
        d["horizons"]["20000"] = _horizon_record("20000", "ok")
        d["horizons"]["20000"]["scales"]["C"] = None                      # (null: no usable cells, as at 5k L1528)
        self.load(d)

    def test_C1_to_C5_registered_records_are_noisebank_and_the_clarification(self):
        """The loader's registered records against independent sources: C3's estimator = noisebank.estimate's
        existing record evaluated from noisebank's own source, minus seed (C1), plus the clarification's verbatim
        objects; C5's rule = the clarification's verbatim text (ASCII); C4's declaration; the horizon texts =
        noisebank's literals; the group and interval names = noisebank's (v5 2.5 L612-616 "retained exactly")."""
        est = ol.registered_estimator()
        self.assertEqual(rqlib.canonical(est), rqlib.canonical(c3_estimator()))
        self.assertNotIn("seed", est)
        self.assertEqual(set(est), (set(nb_existing_estimator()) - {"seed"}) | {"ceilings", "saturation",
                                                                                "capped_category"})   # (C3 erratum)
        self.assertEqual(rqlib.canonical(est["saturation"]), rqlib.canonical(C3_SATURATION))
        self.assertEqual(est["ceilings"], C3_CEILINGS)
        self.assertEqual((est["multi_start"], est["boot"]), (16, 999))
        self.assertEqual(ol.MAP_VARIANCE_RULE, C5_RULE)
        C5_RULE.encode("ascii")
        self.assertEqual(rqlib.canonical(ol.STRUCTURAL_ZERO), rqlib.canonical(STRUCTURAL_ZERO))
        self.assertEqual((tuple(noisebank.GROUPS), tuple(noisebank.BOOT_NAMES)), (NB_GROUPS, NB_BOOT_NAMES))
        self.assertEqual((ol.GROUPS, ol.BOOT_NAMES, ol.CAPTURE_GROUPS, ol.CAPTURE_BOOT_NAMES),
                         (NB_GROUPS, NB_BOOT_NAMES, CAP_GROUPS, CAP_BOOT_NAMES))
        for name, prefix in (("CURVE_EXTRAPOLATION", "constant beyond the outermost knots"),
                             ("GRID_LABEL", "local objective-value validation ("), ("COMPONENT_BOX", "|rho| <= "),
                             ("FF_RULE", "the minimal feasible free row variance"),
                             ("MULTISTART_LABEL", "multi-start validated"),
                             ("INTERVAL_PROCEDURE", "world-multiplicity weighted likelihood ("),
                             ("INTERVAL_LABEL", "approximate; conditional on identification")):
            self.assertEqual(getattr(ol, name), nb_text(prefix), name)
        self.assertEqual(rqlib.read_text(os.path.join(HERE, "obslaw.py")).count(C5_RULE[:40]), 1)   # (one constant)

    def test_item1_bytes(self):
        p = self.write("bank.json", rqlib.canonical(bank3_doc()))
        with self.assertRaisesRegex(ValueError, "configured"):
            ol.BankArtifact(p, sha256="0" * 64)
        text = rqlib.canonical(bank3_doc()).decode()
        for tok in ("NaN", "Infinity", "-Infinity"):
            raw = text.replace('"nu0":12.5', f'"nu0":{tok}').encode()
            with self.subTest(token=tok), self.assertRaisesRegex(ValueError, "NaN / Infinity"):
                self.load(raw=raw)
        raw = text.replace('"SigmaD":[[0.25,0.05],[0.05,0.25]]', '"SigmaD":[[NaN,0.05],[0.05,0.25]]').encode()
        with self.assertRaisesRegex(ValueError, "NaN / Infinity"):
            self.load(raw=raw)
        with self.assertRaisesRegex(ValueError, "duplicate key"):
            self.load(raw=text.replace('"status":"d8-fitted"', '"status":"d8-fitted","status":"d8-fitted"').encode())
        with self.assertRaisesRegex(ValueError, "strict JSON"):
            self.load(raw=b"{not json")

    def test_T5_3_schema_status_synthetic_engine(self):
        self.refuses(lambda d: d.update(schema="finfolk.redqueen.noisebank.bank/2"), "is not finfolk.redqueen.noisebank.bank/3")
        self.refuses(lambda d: d.update(status="unavailable"), "status")
        self.refuses(lambda d: d.update(synthetic=True), "synthetic: true is refused")
        self.refuses(lambda d: d.update(synthetic=1), "synthetic must be")
        self.refuses(lambda d: d.update(engine_sha256=sha_of("e")), "top-level engine_sha256")
        self.refuses(lambda d: d["noise"].update(available=False), "noise.available")
        d = bank3_doc(synthetic=True)
        self.assertTrue(self.load(d, flag=True).synthetic)

    def test_T5_3_each_v5_required_field_missing_is_refused_and_named(self):
        """V5_FIELDS (from v5 2.8's text, by line; not from obslaw's own lists): deleting each field from the complete
        fixture, with the file hash correctly bound, is refused with that field named."""
        self.assertEqual(len({p for p, _, _ in V5_FIELDS}), len(V5_FIELDS))
        for path, line, _ in V5_FIELDS:
            d = bank3_doc()
            node = d
            for k in path[:-1]:
                node = node[k]
            del node[path[-1]]
            name = ".".join(path)
            if path[:2] == ("noise", "s_logit") and len(path) == 3:
                pattern = re.escape("noise.s_logit") + ".*" + re.escape(f"no curve for ['{path[2]}']")
            elif len(path) >= 3 and path[-1] == "nu0" and path[-3] == "nu0":     # (an estimated record's nu0)
                pattern = re.escape(".".join(path[:-1]) + " is estimated but nu0 None")
            else:
                pattern = re.escape(f"missing field {name}") + "$"
            with self.subTest(field=name, v5_line=line), self.assertRaisesRegex(ValueError, pattern):
                self.load(d)

    def test_T5_3_v5_types_and_fixed_values_of_the_records(self):
        """V5_VALUES: the estimator record (C1, C3), the horizon records (their containers, types and the values
        noisebank's encoding fixes; C4's declarations and the absence of survival quantities at 10k/20k; C4.1),
        the bootstrap stream record (C2), the derived inputs_sha256 and the fixed texts (v5 2.8, C5); each
        malformed artifact has its file hash correctly bound, so only the semantic check can refuse it."""
        for i, (mutate, pattern, line) in enumerate(V5_VALUES):
            with self.subTest(case=i, pattern=pattern, v5_line=line):
                self.refuses(mutate, pattern)

    def test_T5_3_each_wrong_value_of_section_2_9(self):
        cases = [
            (lambda d: d.update(support_law="D8/600-rounded-logistic-normal/1"), "support_law"),
            (lambda d: d["age_clock"].update(helper_sha256="0" * 64), "age_clock"),
            (lambda d: d["cohort"]["ages"].__setitem__(0, d["cohort"]["ages"][0] + 1.0), "cohort differs"),
            (lambda d: d.update(cohort_sha256="1" * 64), "cohort_sha256"),
            (lambda d: d.update(survivor_ceiling=246), "survivor_ceiling"),
            (lambda d: d["noise"].update(survivor_ceiling=248), "noise.survivor_ceiling"),
            (lambda d: d["d8"]["ceilings"].update({"5000": 246}), "d8.ceilings"),
            (lambda d: d["d8"]["ceilings"].update({"10000": 1}), "d8.ceilings"),
            (lambda d: d["inputs"].update(observations_sha256="2" * 64), "inputs.observations_sha256"),
            (lambda d: d["inputs"].update(plan_sha256="3" * 64), "inputs.plan_sha256"),
            (lambda d: d["inputs"].update(provenance_sha256="xyz"), "inputs.provenance_sha256 is not a sha256"),
            (lambda d: d["fit"].update(noise_likelihood="600-rounded-logistic-normal"), "fit.noise_likelihood"),
            (lambda d: d["fit"]["noise"].update(engine_sha256="ABC"), "fit.noise.engine_sha256 is not a sha256"),
            (lambda d: d["fit"]["noise"].update(receipt_sha256=None), "fit.noise.receipt_sha256 is not a sha256"),
            (lambda d: d["fit"]["streams"]["bootstrap"].update(generator="numpy.PCG64"), "fit.streams.bootstrap"),
            (lambda d: d["fit"]["streams"]["bootstrap"].update(namespace="AnnexH/1"), "fit.streams.bootstrap"),
            (lambda d: d["d8"].update(amendment_sha256="4" * 64), "d8.amendment_sha256"),
            (lambda d: d["d8"].update(capture_law="H.9.2/other"), "d8.capture_law"),
            (lambda d: d["d8"].update(denominator=247), "d8.denominator"),
            (lambda d: d.update(estimator=[]), "estimator must be an object"),
        ]
        for i, (mut, pat) in enumerate(cases):
            with self.subTest(case=i, pattern=pat):
                self.refuses(mut, pat)

    def test_T5_7_semantic_refusals_with_correctly_bound_hashes(self):
        cases = [
            (lambda d: d["map_variance"]["nu0"].update(C={"status": "estimated", "nu0": -5}), "nu0 -5"),
            (lambda d: d["map_variance"]["nu0"].update(C={"status": "estimated", "nu0": 0.0}), "nu0.C is estimated"),
            (lambda d: d["map_variance"]["nu0"].update(C={"status": "estimated", "nu0": True}), "nu0.C is estimated"),
            (lambda d: d["map_variance"]["nu0"].update(C={"status": "estimated"}), "nu0.C is estimated"),
            (lambda d: d["map_variance"]["nu0"].update(C={"status": "full_pooling", "nu0": 3.0}), "carries a nu0 key"),
            (lambda d: d["map_variance"]["nu0"].update(C={"status": "unavailable", "reason": "x"}), "consumed"),
            (lambda d: d["map_variance"]["nu0"].update(S={"status": "maybe"}), "nu0.S status"),
            (lambda d: d["map_variance"]["nu0"].update(F={"status": "unavailable"}), "without a reason"),
            (lambda d: d["noise"]["SigmaD"].__setitem__(0, [0.25, 0.05 + 1e-6]), "SigmaD: not symmetric"),
            (lambda d: d["noise"]["SigmaE"].__setitem__(0, [0.5 + 1e-6, 0.1]), "unit total C"),
            (lambda d: d["noise"].update(SigmaE=[[0.5, 0.6], [0.6, 0.5]]), "SigmaE: not PSD"),
            (lambda d: d["noise"].update(SigmaR=[[0.25, 0.05], [0.05, 0.25]]), "SigmaR: must be a 3x3"),
            (lambda d: d["noise"]["SigmaR"].__setitem__(2, [0.05, 0.15]), "SigmaR: must be a 3x3"),
            (lambda d: d["noise"]["SigmaD"].__setitem__(1, [0.05, True]), "not bool"),
            (lambda d: d["noise"]["SigmaD"].__setitem__(1, [0.05, "0.25"]), "not bool"),
            (lambda d: d["noise"].update(SigmaR=[[0.25, 0.05, 0.05], [0.05, 0.25, 0.15], [0.05, 0.15, 1.0 + 1e-9]]),
             "free residual"),
            (lambda d: d["map_variance"]["s_logit"]["C"].update(s=[0.55, 0.30, 0.21]), "map_variance.s_logit differs"),
            (lambda d: d["noise"]["s_logit"]["S"].update(s=[0.35, 0.40, 0.22]), "not monotone"),
            (lambda d: d["noise"]["s_logit"].pop("F"), "no curve for"),
            (lambda d: d.update(horizon=10000), "horizon 10000"),
            (lambda d: d["noise"].update(horizon=5000.0), "noise.horizon 5000.0"),
            (lambda d: d.update(dt=0.0160001), "dt"),
            (lambda d: d["noise"].update(capture_bound=323), "capture_bound 323"),
        ]
        for i, (mut, pat) in enumerate(cases):
            with self.subTest(case=i, pattern=pat):
                self.refuses(mut, pat)
        big = rqlib.canonical(bank3_doc()).decode().replace('"SigmaE":[[0.5,0.1]', '"SigmaE":[[1e999,0.1]').encode()
        with self.assertRaisesRegex(ValueError, "finite number"):
            self.load(raw=big)

    def test_item3_registered_constants_agree_with_the_tools(self):
        """v5 4.2 item 3: 324 == recovery.B_COUNT == noisebank.capture_bound(5000) (obslaw does not import recovery)."""
        import noisebank
        import recovery
        self.assertEqual((ol.CAPTURE_BOUND, recovery.B_COUNT, noisebank.capture_bound(5000)), (324, 324, 324))
        self.assertEqual((recovery.R_REPS, ol.SURV_N, ol.HORIZON), (6, noisebank.N_PREY, 5000))

    def test_T2_1_clock_fixture(self):
        self.assertTrue(common.age_feasible(40.00001907348633, 5000, 120.0))
        self.assertFalse(40.00001907348633 + 5000 * 0.016 <= 120)

    def test_T2_2_registered_ceilings_and_identity(self):
        ages = material.registered_ages()
        self.assertEqual([material.cohort_ceiling(ages, h, 0.016) for h in (5000, 10000, 20000)], [247, 0, 0])
        self.assertEqual(bank3_doc()["age_clock"], material.age_clock_identity())

    def test_T2_3_obslaw_derives_no_age_arithmetic(self):
        """Static guard over obslaw's CODE: comments and string literals are blanked by the tokenizer first (v5 2.8
        L748's verbatim d8.age_predicate text names common.age_feasible and binary32(max_age) as text)."""
        src = rqlib.read_text(os.path.join(HERE, "obslaw.py"))
        drop = {tokenize.COMMENT, tokenize.STRING} | {getattr(tokenize, n) for n in ("FSTRING_MIDDLE", "TSTRING_MIDDLE")
                                                      if hasattr(tokenize, n)}
        starts = [0]
        for line in src.splitlines(keepends=True):
            starts.append(starts[-1] + len(line))
        chars = list(src)
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in drop:
                for i in range(starts[tok.start[0] - 1] + tok.start[1], starts[tok.end[0] - 1] + tok.end[1]):
                    if chars[i] != "\n":
                        chars[i] = " "
        code = "".join(chars)
        self.assertIn("material.cohort_ceiling(", code)                  # (the blanking keeps code)
        for pat in (r"\bcommon\.", r"age_feasible", r"age_death_frame", r"binary32\(", r"_CLOCKS",
                    r"\bages\b.*\*\s*(DT|0\.016)", r"max_age\s*[-+*/<>]", r"^\s*(import|from)\s+common\b"):
            self.assertIsNone(re.search(pat, code, re.M), pat)
        self.assertEqual(len(re.findall(r"material\.cohort_ceiling\(", code)), 1)

    def test_T2_3_monkeypatched_clock_changes_the_ceiling_and_the_load_refuses(self):
        d = bank3_doc()
        with mock.patch.object(common, "age_feasible_count", lambda *a, **k: 246):
            self.assertEqual(material.cohort_ceiling(material.registered_ages(), 5000, 0.016), 246)
            with self.assertRaisesRegex(ValueError, "cohort_ceiling 246"):
                self.load(d)
        self.load(d)


# ================================================================== item 7 and the model
def _model_fixture(tmp, gammas=(1.0,), doc=None):
    """A synthetic bank/3 in tmp and its tables (location tables reuse the shared builds' node values under this
    bank's identity; the fitter table reuses the validation build: the curves are the same)."""
    bp = os.path.join(tmp, "bank.json")
    rqlib.write_durable(bp, rqlib.canonical(doc or bank3_doc()))
    bank = ol.BankArtifact(bp)
    loc = {}
    for g in gammas:
        for ch in ol.CHANNELS:
            N, M = bank.law(ch)
            if g == 1.0:
                src = location_validation("C" if ch == "C" else "S")
                ident = ol.location_identity(bank.s_logit[ch], ch, g, N, M, src.identity["h"], bank.sha256)
                loc[(ch, g)] = ol.LocationTable(src.x, src.a, ident, src.record)
            else:
                loc[(ch, g)] = ol.build_location_table(bank.s_logit[ch], ch, g, N, M, bank.sha256)
    f = fitter_validation()
    fit = ol.FitterTable(f.x, f.m, f.V, f.A, f.L, ol.fitter_identity(bank.s_logit["C"], bank.sha256), f.record)
    tp = os.path.join(tmp, "obs_tables.npz")
    ol.ObsTables(loc, fit, bank.sha256).save(tp)
    return bp, tp


def _rehashed_tables(raw, changes):
    """A tables file with some arrays changed (changes: {member: f(array) -> array}) and its content sha256
    RE-COMPUTED here for the changed arrays (the obstables/1 rule: canonical sha256 of {schema, identity, records,
    arrays: {name: [dtype, shape, sha256 of the C-order bytes]}}), so only a semantic check can refuse it."""
    with np.load(io.BytesIO(raw), allow_pickle=False) as z:
        arrays = {k: np.array(z[k]) for k in z.files}
    meta = json.loads(str(arrays.pop("meta")))
    for k, f in changes.items():
        arrays[k] = f(arrays[k])
    body = {k: meta[k] for k in ("schema", "identity", "records")}
    digest = {k: [v.dtype.str, list(v.shape), hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest()]
              for k, v in sorted(arrays.items())}
    meta["content_sha256"] = rqlib.canonical_sha(dict(body, arrays=digest))
    buf = io.BytesIO()
    np.savez(buf, meta=np.array(rqlib.canonical(meta).decode("ascii")), **arrays)
    return buf.getvalue(), meta["content_sha256"]


_LOAD_MODEL = r"""
import sys
sys.path.insert(0, sys.argv[1])
import obslaw
obslaw.BankObservationModel(sys.argv[2], sys.argv[3])
print("LOADED")
"""


@NEED_NP
class TestModel(TmpDir):
    def model(self, **kw):
        bp, tp = _model_fixture(self.tmp)
        return ol.BankObservationModel(bp, tp, bank_sha256=rqlib.sha256_file(bp), tables_sha256=rqlib.sha256_file(tp), **kw)

    def test_load_and_expose(self):
        bp, tp = _model_fixture(self.tmp)
        m = ol.BankObservationModel(bp, tp)
        self.assertEqual((m.nu0_C, m.M_H, m.c_H, m.accepting), (12.5, 247, 247 / 600, True))
        ident = m.identity()
        self.assertEqual(ident["age_clock"], material.age_clock_identity())               # T2-2 (the model's)
        self.assertEqual((ident["bank_artifact_sha256"], ident["obs_tables_sha256"]),
                         (rqlib.sha256_file(bp), rqlib.sha256_file(tp)))
        self.assertEqual(ident["fitter"], {"var_fn": "W", "rep_prior": "nu0_C", "score_law": "A,L"})
        self.assertEqual(m.identity_sha, rqlib.canonical_sha(ident))
        wv, sl = m.working_var_fn(), m.score_law()
        self.assertEqual((wv.identity, sl.identity), (m.identity_sha, m.identity_sha))
        p = np.array([0.01, 0.3, 0.9])
        self.assertTrue(np.array_equal(wv(p), m.tables.fitter.evaluate(np.log(p) - np.log1p(-p))["W"]))
        A, L = sl(p)
        ev = m.tables.fitter.evaluate(np.log(p) - np.log1p(-p))
        self.assertTrue(np.array_equal(A, ev["A"]) and np.array_equal(L, ev["L"]))
        self.assertTrue(np.allclose(m.s("S", np.array([0.2]), 2.0), 2 * ol.scale(VAL_SS, 0.2), rtol=0, atol=0))
        again = ol.BankObservationModel(bp, tp, bank_sha256=ident["bank_artifact_sha256"],
                                        tables_sha256=ident["obs_tables_sha256"],
                                        tables_content_sha256=ident["obs_tables_content_sha256"])
        self.assertEqual(again.identity_sha, m.identity_sha)
        bp2 = os.path.join(self.tmp, "bank_syn.json")
        rqlib.write_durable(bp2, rqlib.canonical(bank3_doc(synthetic=True)))
        with self.assertRaisesRegex(ValueError, "synthetic"):
            ol.BankObservationModel(bp2, tp)

    def test_tables_file_is_deterministic(self):
        bp, tp = _model_fixture(self.tmp)
        raw = rqlib.read_bytes(tp)
        t = ol.ObsTables.from_bytes(raw)
        self.assertEqual(ol.ObsTables(t.location, t.fitter, t.bank_sha256).to_bytes(), raw)

    def test_item7_tables_refusals(self):
        bp, tp = _model_fixture(self.tmp)
        with self.assertRaisesRegex(ValueError, "file sha256"):
            ol.BankObservationModel(bp, tp, tables_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "content sha256"):
            ol.BankObservationModel(bp, tp, tables_content_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "no location table for channel C at gamma 2.0"):
            ol.BankObservationModel(bp, tp, gammas=(1.0, 2.0))
        d = bank3_doc()                                     # another bank (one curve value changed, in its source
        d["noise"]["s_logit"]["S"]["s"][0] = 0.36           # and both copies: Addendum A C9)
        d["map_variance"]["s_logit"]["S"]["s"][0] = 0.36
        d["horizons"]["5000"]["scales"]["S"]["s"][0] = 0.36
        bp2 = os.path.join(self.tmp, "bank2.json")
        rqlib.write_durable(bp2, rqlib.canonical(d))
        with self.assertRaisesRegex(ValueError, "another bank artifact"):
            ol.BankObservationModel(bp2, tp)
        with mock.patch.object(ol, "implementation_sha256", lambda: "5" * 64):
            with self.assertRaisesRegex(ValueError, "another obslaw implementation"):
                ol.BankObservationModel(bp, tp)
        raw = rqlib.read_bytes(tp)                          # a doctored array under the original meta
        zin = zipfile.ZipFile(io.BytesIO(raw))
        buf = io.BytesIO()
        with zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zout:
            for info in zin.infolist():
                data = zin.read(info)
                if info.filename == "fit_V.npy":
                    arr = np.load(io.BytesIO(data))
                    arr[100] *= 1.001
                    b = io.BytesIO()
                    np.save(b, arr)
                    data = b.getvalue()
                zout.writestr(info, data)
        bad = os.path.join(self.tmp, "bad.npz")
        rqlib.write_durable(bad, buf.getvalue())
        with self.assertRaisesRegex(ValueError, "content sha256 does not match"):
            ol.BankObservationModel(bp, bad)
        with self.assertRaisesRegex(ValueError, "not a readable npz"):
            ol.ObsTables.from_bytes(b"PK not a zip")

    def test_item7_table_identity_must_match_the_rule(self):
        bp, tp = _model_fixture(self.tmp)
        t = ol.ObsTables.load(tp)
        bank = ol.BankArtifact(bp)
        lt = t.location[("S", 1.0)]
        ident = dict(lt.identity, loc_tol=1e-6)
        loc = dict(t.location)
        loc[("S", 1.0)] = ol.LocationTable(lt.x, lt.a, ident, lt.record)
        p = os.path.join(self.tmp, "t2.npz")
        ol.ObsTables(loc, t.fitter, bank.sha256).save(p)
        with self.assertRaisesRegex(ValueError, "location table S/1.0 identity"):
            ol.BankObservationModel(bp, p)
        loc[("S", 1.0)] = ol.LocationTable(lt.x[1:], lt.a[1:], lt.identity, lt.record)
        ol.ObsTables(loc, t.fitter, bank.sha256).save(p)
        with self.assertRaisesRegex(ValueError, "nodes are not the grid rule's"):
            ol.BankObservationModel(bp, p)
        f = t.fitter
        bad_fit = ol.FitterTable(f.x, f.m, f.V, f.A, f.L, dict(f.identity, depth_cap=20), f.record)
        ol.ObsTables(t.location, bad_fit, bank.sha256).save(p)
        with self.assertRaisesRegex(ValueError, "fitter table's identity"):
            ol.BankObservationModel(bp, p)

    def test_item7_column_shaped_fitter_axis_is_refused_at_load(self):
        """A tables file whose fit_x is (n, 1), correctly re-hashed (content sha256 recomputed, file sha256
        configured), is refused at load with the field named; so is a (n, 1) fit_m. The control (a re-hash of the
        unchanged arrays) loads."""
        bp, tp = _model_fixture(self.tmp)
        raw = rqlib.read_bytes(tp)
        for member in ("fit_x", "fit_m"):
            data, content = _rehashed_tables(raw, {member: lambda a: a.reshape(-1, 1)})
            p = self.write(f"{member}_col.npz", data)
            n = len(ol.ObsTables.from_bytes(raw).fitter.x)
            msg = re.escape(f"fitter table: {member} has shape ({n}, 1), not ({n},)")
            with self.subTest(member=member), self.assertRaisesRegex(ValueError, msg):
                ol.BankObservationModel(bp, p, tables_sha256=rqlib.sha256_file(p), tables_content_sha256=content)
        data, content = _rehashed_tables(raw, {})
        p = self.write("control.npz", data)
        ol.BankObservationModel(bp, p, tables_sha256=rqlib.sha256_file(p), tables_content_sha256=content)

    def test_P3_1_tables_identity_binds_obslaw_and_noisescale_sources(self):
        """Coordinator decision on review P3-1: every table identity records obslaw_sha256 and noisescale_sha256
        (sha256 of each source file); tables whose recorded value differs from the current file are refused. A
        copy of tools/redqueen in which ONLY noisescale.py (or only obslaw.py) changed refuses the tables built
        here; an unchanged copy loads them."""
        bp, tp = _model_fixture(self.tmp)
        ident = ol.ObsTables.load(tp).identity()
        want = {"obslaw_sha256": rqlib.sha256_file(os.path.join(HERE, "obslaw.py")),
                "noisescale_sha256": rqlib.sha256_file(os.path.join(HERE, "noisescale.py"))}
        for rec in [ident] + ident["location"] + [ident["fitter"]]:
            self.assertEqual({k: rec[k] for k in want}, want)
        for changed, field in ((None, None), ("noisescale.py", "noisescale_sha256"), ("obslaw.py", "obslaw_sha256")):
            tools = os.path.join(self.tmp, f"tools_{changed}")
            shutil.copytree(HERE, tools, ignore=shutil.ignore_patterns("__pycache__", "test_*.py", "*.pyc"))
            if changed:
                with open(os.path.join(tools, changed), "ab") as fh:
                    fh.write(b"\n# (this file alone changed)\n")
            r = subprocess.run([sys.executable, "-I", "-c", _LOAD_MODEL, tools, bp, tp], capture_output=True,
                               text=True, timeout=900)
            with self.subTest(changed=changed):
                if changed is None:
                    self.assertEqual((r.returncode, r.stdout.strip()), (0, "LOADED"), r.stderr[-1500:])
                else:
                    self.assertNotEqual(r.returncode, 0, r.stdout)
                    self.assertIn(f"({field})", r.stderr)

    def test_generate_draw_order_and_endpoints(self):
        """PC-3 (v5 1.4, L231-233): the expected observations are built HERE from default_rng([17, 3]) drawn
        explicitly in v5's order, Z_R (nQ, R, 3), Z_EF (nQ, R), Z_D (nP, R, 2), Z_E (|E|, R, 2), with the latents
        (L216-218) and the capped rounded counts (L260-265) composed here; only the location lookup and S are
        production's. Exchanging any two of obslaw.standard_normals' draws fails this test."""
        m = self.model()
        qi, pj = np.array([0, 0, 1, 2, 2]), np.array([0, 1, 1, 0, 1])
        nQ, nP, nE, R = 3, 2, 5, 6
        eta = np.array([-2.0, 0.3, 1.5, 40.0, -1.0])
        mu = {"C": 1 / (1 + np.exp(-eta)), "S": m.c_H / (1 + np.exp(-(eta - 0.5))), "F": np.array([0.2, m.c_H, 0.0])}
        xs = {"S": eta - 0.5}
        out = m.generate(np.random.default_rng([17, 3]), qi, pj, nQ, nP, mu, x=xs)
        g = np.random.default_rng([17, 3])
        ZR = g.standard_normal((nQ, R, 3))
        ZEF = g.standard_normal((nQ, R))
        ZD = g.standard_normal((nP, R, 2))
        ZE = g.standard_normal((nE, R, 2))
        FR, FD, FE = (np.asarray(m.factors[k], float) for k in ("R", "D", "E"))
        rows, donors, cells = ZR @ FR.T, ZD @ FD.T, ZE @ FE.T
        u = {"C": rows[qi, :, 0] + donors[pj, :, 0] + cells[:, :, 0],
             "S": rows[qi, :, 1] + donors[pj, :, 1] + cells[:, :, 1],
             "F": rows[:, :, 2] + math.sqrt(1.0 - SIGMA_R[2][2]) * ZEF}
        for ch in ol.CHANNELS:
            N, M = (324, 324) if ch == "C" else (600, 247)
            c = M / N
            want = np.zeros((len(mu[ch]), R), np.int64)
            want[mu[ch] == c] = M
            inner = np.flatnonzero((mu[ch] > 0) & (mu[ch] < c))
            tab = m.location_table(ch, 1.0)
            a = tab.locate(mu[ch][inner], None if ch not in xs else xs[ch][inner])
            s = m.s(ch, mu[ch][inner])
            v = np.floor(N * (1.0 / (1.0 + np.exp(-(a[:, None] + s[:, None] * u[ch][inner])))) + 0.5)
            want[inner] = np.minimum(M, v).astype(np.int64)
            self.assertTrue(np.array_equal(out["counts"][ch], want), ch)
        self.assertEqual(out["counts"]["C"].shape, (5, 6))
        self.assertTrue(np.all(out["counts"]["F"][1] == 247) and np.all(out["counts"]["F"][2] == 0))
        self.assertTrue(np.all(out["counts"]["C"][3] == 324))       # (sigma(40) = 1 exactly: the endpoint mu = c)
        self.assertTrue(np.all(out["counts"]["S"] <= 247))
        bad = dict(mu, S=mu["S"] + 1.0)
        rng = np.random.default_rng(0)
        state = rng.bit_generator.state
        with self.assertRaisesRegex(ValueError, "mean S"):
            m.generate(rng, qi, pj, 3, 2, bad)
        self.assertEqual(rng.bit_generator.state, state)               # (refused before any draw)
        with self.assertRaisesRegex(ValueError, "no location table"):
            m.generate(rng, qi, pj, 3, 2, mu, gamma=2.0)


# ================================================================== the #68 adoption gates
_GATE68 = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import numpy as np
import calib, transition
p = json.load(sys.stdin)
out = {"loc": [float(calib.location(np.array([mu]), np.array([s]), N, ceiling)[0]) for mu, s, N, ceiling in p["loc"]],
       "ef": [float(calib.expected_fraction(np.array([a]), s, N, ceiling)[0]) for a, s, N, ceiling in p["ef"]],
       "normals": [transition.VecSplitMix64(seed).normals(n).tolist() for seed, n in p["normals"]]}
print(json.dumps(out))
"""


def git_blob_id(path):
    """git's blob id of one extracted file (sha1 of "blob <size>\\0" + the bytes; a symlink's bytes are its target)."""
    if os.path.islink(path):
        data = os.readlink(path).encode()
    else:
        with open(path, "rb") as f:
            data = f.read()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def pr68_pinned_commit(root):
    """The #68 extraction root's PINNED_COMMIT (a full 40-hex sha), after authenticating the extraction against its
    MANIFEST: the `git ls-tree -r <PINNED_COMMIT> tools/redqueen` output written beside it when the extraction was
    made (git's own record of that commit's tree: mode, type, blob id and path of every file). Every file under
    tools/redqueen/ must have the blob id MANIFEST records for its path, and no file may be missing or extra;
    otherwise the gate is refused (AssertionError) before anything runs. -> (sha, number of files verified)."""
    pin = os.path.join(root, "PINNED_COMMIT")
    if not os.path.isfile(pin):
        raise AssertionError(f"adoption gate refused: {pin} is absent (RQ_PR68_DIR must be the root of a git-archive "
                             "extraction of the pinned #68 commit, holding PINNED_COMMIT, MANIFEST and "
                             "tools/redqueen/)")
    sha = rqlib.read_text(pin).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise AssertionError(f"adoption gate refused: PINNED_COMMIT {sha!r} is not a full 40-hex commit sha")
    man = os.path.join(root, "MANIFEST")
    if not os.path.isfile(man):
        raise AssertionError(f"adoption gate refused: {man} is absent (git ls-tree -r {sha} tools/redqueen, written at "
                             "extraction)")
    want = {}
    for i, line in enumerate(rqlib.read_text(man).splitlines(), 1):
        m = re.fullmatch(r"(100644|100755|120000) blob ([0-9a-f]{40})\t(tools/redqueen/[^\t]+)", line)
        if not m or m.group(3) in want:
            raise AssertionError(f"adoption gate refused: MANIFEST line {i} {line!r} is not a new git ls-tree -r "
                                 "blob entry under tools/redqueen/")
        want[m.group(3)] = m.group(2)
    if not want:
        raise AssertionError("adoption gate refused: MANIFEST lists no file")
    have = {}
    for d, dirs, files in os.walk(os.path.join(root, "tools", "redqueen")):
        for name in files + [x for x in dirs if os.path.islink(os.path.join(d, x))]:
            p = os.path.join(d, name)
            have[os.path.relpath(p, root).replace(os.sep, "/")] = git_blob_id(p)
    missing, extra = sorted(set(want) - set(have)), sorted(set(have) - set(want))
    bad = sorted(p for p in set(want) & set(have) if want[p] != have[p])
    if missing or extra or bad:
        raise AssertionError(f"adoption gate refused: the extraction differs from MANIFEST ({sha}): missing "
                             f"{missing[:5]}, extra {extra[:5]}, blob mismatch {bad[:5]}")
    return sha, len(want)


class TestAdoptionGatePin(TmpDir):
    SHA = "75817e293a8368a1cb1168f446bd33f9454dd644"
    HELLO = "ce013625030ba8dba906f756967f9e9ca394464a"     # git's blob id of b"hello\n" (git hash-object)
    EMPTY = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"     # git's blob id of the empty file

    def extraction(self):
        """A synthetic extraction root: PINNED_COMMIT, MANIFEST and two files, ids from git (not from the helper)."""
        os.makedirs(os.path.join(self.tmp, "tools", "redqueen", "sub"))
        self.write("tools/redqueen/a.py", b"hello\n")
        self.write("tools/redqueen/sub/b.txt", b"")
        self.write("PINNED_COMMIT", (self.SHA + "\n").encode())
        self.write("MANIFEST", (f"100644 blob {self.HELLO}\ttools/redqueen/a.py\n"
                                f"100644 blob {self.EMPTY}\ttools/redqueen/sub/b.txt\n").encode())

    def test_pinned_commit_is_required_and_read(self):
        """The gate's provenance check (review: RQ_PR68_DIR alone does not prove which commit was extracted)."""
        with self.assertRaisesRegex(AssertionError, "PINNED_COMMIT is absent"):
            pr68_pinned_commit(self.tmp)
        self.write("PINNED_COMMIT", b"75817e2\n")
        with self.assertRaisesRegex(AssertionError, "not a full 40-hex"):
            pr68_pinned_commit(self.tmp)
        self.extraction()
        self.assertEqual(pr68_pinned_commit(self.tmp), (self.SHA, 2))

    def test_P3_manifest_is_required(self):
        self.extraction()
        os.remove(os.path.join(self.tmp, "MANIFEST"))
        with self.assertRaisesRegex(AssertionError, "MANIFEST is absent"):
            pr68_pinned_commit(self.tmp)
        for bad in (b"", f"100644 blob {self.HELLO} tools/redqueen/a.py\n".encode(),
                    f"100644 tree {self.HELLO}\ttools/redqueen/a.py\n".encode(),
                    f"160000 commit {self.HELLO}\ttools/redqueen/a.py\n".encode(),
                    f"100644 blob {self.HELLO}\ttools/redqueen/a.py\n100644 blob {self.HELLO}\ttools/redqueen/a.py\n"
                    .encode()):
            self.write("MANIFEST", bad)
            with self.subTest(manifest=bad), self.assertRaisesRegex(AssertionError, "MANIFEST (line|lists no)"):
                pr68_pinned_commit(self.tmp)

    def test_P3_the_extraction_is_authenticated_against_the_manifest(self):
        """The review's scenario: the expected sha in PINNED_COMMIT beside a different extraction is refused (a
        changed file, an extra file, a missing file), before any gate runs."""
        self.extraction()
        self.write("tools/redqueen/a.py", b"hello!\n")
        with self.assertRaisesRegex(AssertionError, r"blob mismatch \['tools/redqueen/a\.py'\]"):
            pr68_pinned_commit(self.tmp)
        self.write("tools/redqueen/a.py", b"hello\n")
        self.write("tools/redqueen/c.py", b"")
        with self.assertRaisesRegex(AssertionError, r"extra \['tools/redqueen/c\.py'\]"):
            pr68_pinned_commit(self.tmp)
        os.remove(os.path.join(self.tmp, "tools", "redqueen", "c.py"))
        os.remove(os.path.join(self.tmp, "tools", "redqueen", "sub", "b.txt"))
        with self.assertRaisesRegex(AssertionError, r"missing \['tools/redqueen/sub/b\.txt'\]"):
            pr68_pinned_commit(self.tmp)
        self.write("tools/redqueen/sub/b.txt", b"")
        self.assertEqual(pr68_pinned_commit(self.tmp), (self.SHA, 2))


@NEED_NP
@unittest.skipUnless(PR68, "adoption gate: RQ_PR68_DIR (the root of a read-only extraction of the pinned #68 "
                           "commit, with PINNED_COMMIT, MANIFEST and tools/redqueen) not set")
class TestAdoptionGate68(unittest.TestCase):
    """v5 5: T1-6's cross-check with #68's law and T5-5's normals against transition.VecSplitMix64, at the commit
    named by the extraction's PINNED_COMMIT, the extraction first authenticated against its MANIFEST (printed;
    refused when either is absent or any file differs)."""

    @classmethod
    def setUpClass(cls):
        cls.commit, n = pr68_pinned_commit(PR68)
        tools = os.path.join(PR68, "tools", "redqueen")
        print(f"\nadoption gate: #68 PINNED_COMMIT {cls.commit} (extraction {tools}; {n} files match MANIFEST, git "
              "ls-tree -r of that commit)", file=sys.stderr, flush=True)
        cls.loc = [(C247 - 1e-3, 0.3, 600, 247), (C247 - 1e-4, 0.5, 600, 247), (0.2, 0.25, 600, 247),
                   (1e-3, 0.3, 600, 247), (0.5, 0.3, 324, 324), (0.99, 0.2, 324, 324), (0.02, 0.45, 324, 324)]
        cls.ef = [(-1.0, 0.3, 600, 247), (-0.36, 0.6, 600, 247), (0.5, 0.8, 600, 247), (2.0, 0.2, 324, 324)]
        cls.normals = [(ref_seed(REFIT), 64), (ref_seed(VALROWS), 64)]
        r = subprocess.run([sys.executable, "-I", "-B", "-c", _GATE68, tools], capture_output=True, text=True,
                           timeout=1800,
                           input=json.dumps({"loc": cls.loc, "ef": cls.ef, "normals": cls.normals}))
        if r.returncode:
            raise AssertionError(f"#68 side failed: {r.stderr[-2000:]}")
        cls.got = json.loads(r.stdout)

    def test_T1_6_locations_through_the_independent_expectation(self):
        for (mu, s, N, M), a68 in zip(self.loc, self.got["loc"]):
            a = float(ol.solve_location(mu, s, N, M)[0])
            self.assertLessEqual(abs(oracle_mean(a, s, N, M) / N - mu), 1e-12, "obslaw exact solve")
            self.assertLessEqual(abs(oracle_mean(a68, s, N, M) / N - mu), 2e-6, "calib LOC_S_TOL")
        for ch in ("C", "S"):
            t = location_validation(ch)
            curve = VAL_SC if ch == "C" else VAL_SS
            for mu in ((0.01, 0.4, 0.97) if ch == "C" else (0.01, 0.2, C247 - 1e-3)):
                a = float(t.locate(np.array([mu]))[0])
                self.assertLessEqual(abs(oracle_mean(a, float(ol.scale(curve, mu)), t.N, t.M) / t.N - mu), ol.LOC_TOL)

    def test_T1_6_expected_fractions_agree(self):
        for (a, s, N, M), e68 in zip(self.ef, self.got["ef"]):
            self.assertLessEqual(abs(float(ol.expected_fraction(a, s, N, M)) - e68), 1e-10)

    def test_T5_5_normals_equal_vec_splitmix64(self):
        for (seed, n), v68 in zip(self.normals, self.got["normals"]):
            self.assertEqual(ol.splitmix_normals(rqlib.SplitMix64(seed), n).tolist(), v68)


if __name__ == "__main__":
    unittest.main()

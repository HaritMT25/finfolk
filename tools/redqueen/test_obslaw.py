#!/usr/bin/env python3
"""test_obslaw.py: obslaw.py, the bank/D8 observation law of recovery option A (A_design_v5.md; test IDs of its
section 5). Synthetic data only: no bank observation, no study store or output is opened.

  T1 law oracle: T1-1 category probabilities and E[K] against an independent scalar oracle (explicit intervals,
     the capped top category, tail-stable math.erfc); T1-2 a definitional quadrature; T1-3 location solves and a
     knot-inclusive location table; T1-4 uncapped draws above the ceiling; T1-5 the analytic and Monte Carlo
     mean, and the two prohibited substitutions; T1-6 endpoints and refusals (+ the #68 cross-check, adoption
     gate); T1-7 the fitter-table certification under the v5 adaptive policy, its negative controls, caps and
     extrapolation.
  T2 (obslaw's part): the clock fixture, the registered ceilings and the model's age_clock, the static and the
     monkeypatch guards.
  T3 (obslaw's unit part; the bank-mode recovery integration is test_graph.py's): latent correlations per sharing
     class, a singular PSD SigmaR, no second layer.
  T5-3 / T5-7 the strict bank/3 loader; T5-5 the D8 streams (+ #68's normals, adoption gate).

    RQ_REQUIRE_NUMPY=1 python3 -I -W error::ResourceWarning tools/redqueen/test_obslaw.py -v

The adoption gates (v5 5: T1-6's #68 cross-check, T5-5's VecSplitMix64 equality) run against a read-only
extraction of the pinned #68 commit's tools/redqueen named by RQ_PR68_DIR; otherwise they are skipped with a
reason starting "adoption gate".
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile
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


def bank3_doc(synthetic=False):
    """A complete, valid synthetic bank/3 artifact (v5 2.8): declared synthetic parameters, the registered constants,
    placeholder identities. Not a bank fit."""
    curves = {"C": copy.deepcopy(VAL_SC), "S": copy.deepcopy(VAL_SS), "F": copy.deepcopy(VAL_SS)}
    texts = [f"AnnexH/D8/1/noisebank/D8-refit/h{h}/bootstrap" for h in (5000, 10000, 20000)]
    return {
        "schema": ol.BANK_SCHEMA, "status": ol.STATUS_FITTED, "synthetic": synthetic,
        "cohort": material.registered_ages(), "cohort_sha256": material.AGES_SHA256, "horizon": 5000, "dt": 0.016,
        "support_law": material.SUPPORT_LAW, "age_clock": copy.deepcopy(material.age_clock_identity()),  # (lru-cached)
        "survivor_ceiling": 247,
        "fit": {"noise_likelihood": ol.NOISE_LIKELIHOOD,
                "noise": {k: sha_of("fit.noise." + k) for k in ol.FIT_NOISE_SHAS},
                "streams": {"bootstrap": {"generator": "rqlib.SplitMix64", "namespace": "AnnexH/D8/1", "texts": texts,
                                          "seeds": [ol.stream_seed_d8(t) for t in texts]}}},
        "noise": {"available": True, "s_logit": curves, "SigmaR": copy.deepcopy(SIGMA_R),
                  "SigmaD": copy.deepcopy(SIGMA_D), "SigmaE": copy.deepcopy(SIGMA_E), "horizon": 5000,
                  "capture_bound": 324, "survivor_ceiling": 247},
        "map_variance": {"s_logit": copy.deepcopy(curves),
                         "nu0": {"C": {"status": "estimated", "nu0": 12.5, "cells": 200},
                                 "S": {"status": "full_pooling", "cells": 120},
                                 "F": {"status": "unavailable", "reason": "synthetic test"}},
                         "rule": "working replicate-mean variance (nu0 phi W(z) + (R-1) s2) / (nu0 + R - 1) / R "
                                 "(A_design_v5.md 1.7b)", "consumer": "map.fit rep_prior, capture channel"},
        "d8": {"amendment_sha256": ol.D8_SHA256, "capture_law": ol.CAPTURE_LAW, "ceilings": dict(ol.CEILINGS),
               "max_age": material.registered_ages()["max_age"], "denominator": 600,
               "age_predicate": "updated binary32 age > binary32(max_age) is an age death",
               "capped_category": "k = M_H: latent upper endpoint +inf, scale N = 600"},
        "inputs": dict(ol.REGISTERED_INPUTS, design_canonical_sha256=sha_of("dc"), provenance_sha256=sha_of("pv"),
                       validation_report_sha256=sha_of("vr")),
        "estimator": {"note": "synthetic test artifact (declared parameters)"},
        "horizons": {"5000": {"status": "ok"}},
    }


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

    def test_T1_7_every_final_segment_meets_items_1_to_4_on_recheck(self):
        """An independent re-run of the certification on the FINAL table: every refined segment and a sample of
        the others."""
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
        d = bank3_doc()
        d["map_variance"]["nu0"]["C"] = {"status": "full_pooling", "cells": 9}
        self.assertIsNone(self.load(d).nu0_C)

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

    def test_T5_3_each_missing_field_is_named(self):
        paths = [(k,) for k in ol.TOP_FIELDS if k != "schema"] + [("noise", k) for k in ol.NOISE_FIELDS] + \
                [("map_variance", k) for k in ol.MAP_VARIANCE_FIELDS] + [("d8", k) for k in ol.D8_FIELDS] + \
                [("fit", "noise_likelihood"), ("fit", "noise"), ("fit", "streams")] + \
                [("fit", "noise", k) for k in ol.FIT_NOISE_SHAS] + [("inputs", k) for k in ol.INPUT_KEYS] + \
                [("map_variance", "nu0", ch) for ch in ("C", "S", "F")]
        for path in paths:
            d = bank3_doc()
            node = d
            for k in path[:-1]:
                node = node[k]
            del node[path[-1]]
            name = ".".join(path)
            with self.subTest(field=name), self.assertRaisesRegex(ValueError, re.escape(f"missing field {name}")):
                self.load(d)
        d = bank3_doc()
        del d["schema"]
        with self.assertRaisesRegex(ValueError, "missing field schema"):
            self.load(d)

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
        src = rqlib.read_text(os.path.join(HERE, "obslaw.py"))
        code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
        for pat in (r"\bcommon\.", r"age_feasible", r"age_death_frame", r"binary32\(", r"_CLOCKS",
                    r"\bages\b.*\*\s*(DT|0\.016)", r"max_age\s*[-+*/<>]"):
            self.assertIsNone(re.search(pat, code), pat)
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
        d = bank3_doc()                                     # another bank (one curve value changed)
        d["noise"]["s_logit"]["S"]["s"][0] = 0.36
        d["map_variance"]["s_logit"]["S"]["s"][0] = 0.36
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

    def test_generate_draw_order_and_endpoints(self):
        m = self.model()
        qi, pj = np.array([0, 0, 1, 2, 2]), np.array([0, 1, 1, 0, 1])
        eta = np.array([-2.0, 0.3, 1.5, 40.0, -1.0])
        mu = {"C": 1 / (1 + np.exp(-eta)), "S": m.c_H / (1 + np.exp(-(eta - 0.5))), "F": np.array([0.2, m.c_H, 0.0])}
        out = m.generate(np.random.default_rng([17, 3]), qi, pj, 3, 2, mu, x={"S": eta - 0.5})
        Z = ol.standard_normals(np.random.default_rng([17, 3]), 3, 2, 5, 6)
        u = ol.latent(Z, m.factors, qi, pj)
        for ch in ol.CHANNELS:
            K, _, _ = m.counts(ch, mu[ch], u[ch], 1.0, eta - 0.5 if ch == "S" else None)
            self.assertTrue(np.array_equal(out["counts"][ch], K), ch)
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


@NEED_NP
@unittest.skipUnless(PR68, "adoption gate: RQ_PR68_DIR (a read-only extraction of the pinned #68 commit's "
                           "tools/redqueen) not set")
class TestAdoptionGate68(unittest.TestCase):
    """v5 5: T1-6's cross-check with #68's law and T5-5's normals against transition.VecSplitMix64."""

    @classmethod
    def setUpClass(cls):
        cls.loc = [(C247 - 1e-3, 0.3, 600, 247), (C247 - 1e-4, 0.5, 600, 247), (0.2, 0.25, 600, 247),
                   (1e-3, 0.3, 600, 247), (0.5, 0.3, 324, 324), (0.99, 0.2, 324, 324), (0.02, 0.45, 324, 324)]
        cls.ef = [(-1.0, 0.3, 600, 247), (-0.36, 0.6, 600, 247), (0.5, 0.8, 600, 247), (2.0, 0.2, 324, 324)]
        cls.normals = [(ref_seed(REFIT), 64), (ref_seed(VALROWS), 64)]
        r = subprocess.run([sys.executable, "-I", "-c", _GATE68, PR68], capture_output=True, text=True, timeout=1800,
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

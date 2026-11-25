#!/usr/bin/env python3
"""test_stats.py: Annex H's required checks for stats.py (H.13 1-3, 7-10; H.16 29-34; H.17 35, 36, 38, 40;
the user's Holm decision).

    python3 -I tools/redqueen/test_stats.py [-v]
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rqlib  # noqa: E402
import stats  # noqa: E402


def layout(blocks=8):
    out = []
    for b in range(1, blocks + 1):
        out += [{"id": f"C{b}{k}", "treatment": "C", "block": b} for k in range(4)]
        out += [{"id": f"A{b}", "treatment": "A", "block": b}, {"id": f"B{b}", "treatment": "B", "block": b}]
    return out


class TestConventions(unittest.TestCase):
    def test_clock_projection_units(self):
        """H.13 1-3: the actual F1 clock; the linear projection (not an endpoint derivative); material units."""
        self.assertEqual(stats.t_of_frame(1), 1e-6)
        self.assertAlmostEqual(stats.x_of_frame(1), 2e-8, places=20)
        self.assertAlmostEqual(stats.t_of_frame(50_000_000) - stats.t_of_frame(1), 49.999999)
        a, b, c = 0.3, -0.7, 0.25
        xs = [0, 1, 2, 3, 4]
        slope, icpt = stats.projection(xs, [a + b * x + c * x * x for x in xs])
        self.assertAlmostEqual(slope, b + 4 * c)
        self.assertAlmostEqual(icpt, a - 2 * c)
        ts = [stats.t_of_frame(f) for f in [1] + list(range(5_000_000, 200_000_001, 5_000_000))]
        xs = [t / 50 for t in ts]
        self.assertAlmostEqual(stats.projection(xs, [0.4 + math.log(1.10) * t / 50 for t in ts])[0], math.log(1.10))
        self.assertAlmostEqual(stats.projection(xs, [0.7 + 0.02 * t / 50 for t in ts])[0], 0.02)
        self.assertAlmostEqual(stats.projection(xs, [0.1 - 0.05 for _ in ts])[0], 0.0, places=15)   # q = -k

    def test_streams_and_quantiles(self):
        s1 = stats.stream_seed("H-F", "development", "F0", 7)
        self.assertEqual(s1, int.from_bytes(hashlib.sha256(b"AnnexH/1/H-F/development/F0/7").digest()[:8], "little"))
        self.assertNotEqual(s1, stats.stream_seed("H-F", "development", "F0", 8))
        z = list(range(1, 10000))                                      # 9,999 sorted draws
        self.assertEqual(stats.Q(z, 0.975), 9750)
        self.assertEqual(stats.Q(z, 0.0), 1)
        self.assertEqual(stats.Q(z, 1.0), 9999)


class TestClusterBootstrap(unittest.TestCase):
    def values(self, shift=0.0, n=32, seed=5):
        r = rqlib.SplitMix64(seed)
        return [shift + (r.below(10 ** 6) / 10 ** 6 - 0.5) for _ in range(n)]

    def test_centring_and_decisions(self):
        """H.13 7: T*_b = (theta_b - theta) / s_b, not theta_b / s_b; detection and material rules."""
        strong = self.values(0.3)
        r = stats.cluster_test(strong, stats.mean_se, draws=999, rng=stats.bootstrap_stream("H-P", "unit"), delta=0.28)
        self.assertTrue(r["available"] and r["detected"])
        self.assertLess(r["p"], 0.01)
        self.assertLess(r["CI95"][0], r["estimate"])
        self.assertLess(r["L99"], r["estimate"])
        self.assertGreater(r["p_delta"], r["p"])
        # uncentred draws (theta_b / s_b) would sit near T and give p near one half: centring keeps p small
        null = stats.cluster_test(self.values(0.0), stats.mean_se, draws=999, rng=stats.bootstrap_stream("H-P", "unit"))
        self.assertGreater(null["p"], 0.01)
        self.assertFalse(null["detected"])
        self.assertEqual(r["t_sensitivity"]["df"], 31)
        self.assertGreaterEqual(r["leave_one_out"]["max_influence"], 0.0)

    def test_degenerate_draws_retained(self):
        """H.13 8: zero-SE resamples are retained (0 / +inf / -inf), 9,999 draws, denominator 10,000;
        an original SE of zero is unavailable."""
        vals = [1.0] * 30 + [1.0, 2.0]
        r = stats.cluster_test(vals, stats.mean_se, draws=9999, rng=stats.bootstrap_stream("H-Q", "degenerate"))
        self.assertEqual((r["draws"], r["retained"]), (9999, 9999))
        k = round(r["p"] * 10000) - 1
        self.assertAlmostEqual((k + 1) / 10000, r["p"])
        z = stats.cluster_test([0.5] * 10, stats.mean_se, draws=10)
        self.assertFalse(z["available"])
        self.assertIn("standard error is 0", z["reason"])
        calls = []

        def est(units):
            calls.append(1)
            return stats.mean_se(units)
        two = stats.cluster_test([0.0, 1.0], est, draws=200, rng=rqlib.SplitMix64(3))
        self.assertEqual(two["retained"], 200)            # draws of one world twice: se 0, kept as +-inf
        self.assertEqual(len(calls), 1 + 200 + 2)          # original, draws, leave-one-out

    def test_refit_and_determinism(self):
        """H.13 9-10: a pooled nuisance is refitted per draw (est called once + B + n leave-one-out);
        identical inputs give identical results; input order does not matter after canonical sorting."""
        recs = [{"id": f"w{i:02d}", "x": x, "y": y} for i, (x, y) in enumerate(zip(self.values(0.1, 20, 1),
                                                                                  self.values(0.4, 20, 2)))]
        n_calls = [0]

        def est(units):
            n_calls[0] += 1
            mu = sum(u["x"] for u in units) / len(units)                # pooled across the resample
            return stats.mean_se([u["y"] - 0.5 * mu for u in units])
        a = stats.cluster_test(recs, est, draws=300, rng=stats.bootstrap_stream("H-P", "refit"), key=lambda u: u["id"])
        self.assertEqual(n_calls[0], 1 + 300 + 20)
        b = stats.cluster_test(list(reversed(recs)), est, draws=300, rng=stats.bootstrap_stream("H-P", "refit"),
                               key=lambda u: u["id"])
        self.assertEqual(a, b)


class TestHC(unittest.TestCase):
    def test_block_deltas(self):
        """H.16 31: three eligible C worlds: their arithmetic mean, not scaled by the count."""
        ws = layout(2)
        sl = {f"C1{k}": {"neural": 1.0 + k, "scripted": 0.5} for k in range(4)}
        sl.update({"A1": {"neural": 0.2, "scripted": 0.1}, "B1": {"neural": 0.4, "scripted": 0.3}})
        sl["C11"] = {"neural": float("nan"), "scripted": 0.5}
        sl.update({"C20": {"neural": 1.0, "scripted": 1.0}, "A2": {"neural": 0.0, "scripted": 0.0}})   # no B2
        d, bad = stats.hc_block_deltas(sl, ws)
        dc = ((1.0 - 0.5) + (3.0 - 0.5) + (4.0 - 0.5)) / 3
        self.assertAlmostEqual(d[1][0], dc - (0.2 - 0.1))
        self.assertAlmostEqual(d[1][1], dc - (0.4 - 0.3))
        self.assertIn("0 B", bad[2])

    def test_precision_weights(self):
        """USER DECISIONS 2: the precision-weighted Fisher-Pitman IUT. Balanced intact blocks: exactly H.5's
        statistic (p, estimates, bounds). Two-control blocks (4C+2A+1B, 4C+1A+2B): w = 1/(1/n_C + 1/n_G)
        (5/3 relative weight), the weighted sum enumerated, the weighted inversion, exact level."""
        import itertools
        D = {b: (0.03 + 0.01 * math.sin(b), 0.02 - 0.015 * math.cos(3 * b)) for b in range(8)}
        r0 = stats.hc_test(D)
        r1 = stats.hc_test(D, weights={b: (0.8, 0.8) for b in D})               # balanced: constant weights
        for k in ("p_A", "p_B", "p", "estimate_A", "estimate_B", "p_material"):
            self.assertAlmostEqual(r0[k], r1[k], places=14)
        self.assertEqual(r0["lower99"], r1["lower99"])
        # the registry: half the blocks 4C+2A+1B, half 4C+1A+2B
        ws = []
        for b in range(1, 9):
            ws += [{"id": f"C{b}{k}", "treatment": "C", "block": b} for k in range(4)]
            na, nb = (2, 1) if b <= 4 else (1, 2)
            ws += [{"id": f"A{b}{k}", "treatment": "A", "block": b} for k in range(na)]
            ws += [{"id": f"B{b}{k}", "treatment": "B", "block": b} for k in range(nb)]
        sl = {w["id"]: {"neural": 0.05 + 0.003 * i, "scripted": 0.01} for i, w in enumerate(ws)}
        d, bad, wt = stats.hc_block_deltas(sl, ws, with_weights=True)
        self.assertEqual(bad, {})
        self.assertAlmostEqual(wt[1][0] / wt[1][1], (1 / (0.25 + 0.5)) / (1 / (0.25 + 1.0)))   # 5/3
        self.assertAlmostEqual(wt[1][0], 4 / 3)
        self.assertAlmostEqual(wt[5][1], 4 / 3)
        dA1 = (sum(sl[f"C1{k}"]["neural"] - 0.01 for k in range(4)) / 4
               - sum(sl[f"A1{k}"]["neural"] - 0.01 for k in range(2)) / 2)
        self.assertAlmostEqual(d[1][0], dA1)
        r = stats.hc_test(d, weights=wt, alpha=0.0167)
        DA = [d[b][0] for b in sorted(d)]
        WA = [wt[b][0] for b in sorted(d)]
        tA = sum(w * x for w, x in zip(WA, DA))
        k = sum(sum(e * w * x for e, w, x in zip(es, WA, DA)) >= tA - 1e-15
                for es in itertools.product((1, -1), repeat=8))
        self.assertEqual(r["p_A"], k / 256)
        self.assertAlmostEqual(r["estimate_A"], tA / sum(WA))
        L = r["lower99"]["A"]
        eps = 1e-9
        self.assertLessEqual(stats.signflip_p([x - (L - eps) for x in DA], WA)[2], 0.0167)
        self.assertGreater(stats.signflip_p([x - (L + eps) for x in DA], WA)[2], 0.0167)
        # exact level under block-error symmetry: over every sign pattern of fixed magnitudes, at most
        # floor(alpha 2^n) patterns reject (the weights are known constants)
        mags = [abs(x) + 0.001 * i for i, x in enumerate(DA)]
        for alpha in (0.01, 0.0167, 0.05):
            rej = sum(stats.signflip_p([e * m for e, m in zip(es, mags)], WA)[2] <= alpha
                      for es in itertools.product((1, -1), repeat=8))
            self.assertLessEqual(rej, math.floor(alpha * 256))
        # H-C's threshold is its active Holm level
        h = stats.holm({"H-P": 0.001, "H-Q": 0.002, "H-F": 0.2, "H-T": 0.5, "H-C": 0.015})
        self.assertAlmostEqual(stats.active_level(h, "H-C"), 0.05 / 3)
        self.assertTrue(stats.hc_test({b: (0.01 + 0.001 * b, 0.02) for b in range(7)},
                                      alpha=stats.active_level(h, "H-C"))["reject"])     # 7 blocks: 1/128 <= 1/60

    def test_floors(self):
        """H.16 29-30: all-positive vectors give p = 2^-n (8 and 7 blocks can reject, 6 cannot); negative or
        opposite directions never reject; an all-zero control vector has p = 1."""
        for n, can in ((8, True), (7, True), (6, False)):
            d = {b: (0.1 + 0.01 * b, 0.2 + 0.02 * b) for b in range(n)}
            r = stats.hc_test(d)
            self.assertEqual((r["p"], r["p_floor"]), (2.0 ** -n, 2.0 ** -n))
            self.assertEqual(r["reject"], can)
            self.assertEqual(r["alpha_attainable"], can)
        neg = stats.hc_test({b: (-0.1 - 0.01 * b, -0.2) for b in range(8)})
        opp = stats.hc_test({b: (0.1 + 0.01 * b, -0.2 - 0.01 * b) for b in range(8)})
        self.assertFalse(neg["reject"] or opp["reject"])
        self.assertEqual(stats.signflip_p([0.0] * 8)[2], 1.0)

    def test_legacy_counterexample(self):
        """H.16 32: D_A = e_b(0.20 + 0.05 b) (exactly symmetric null), D_B = 2 + 0.01 b, over all 256 sign
        vectors: the legacy joint two-sided minimum rejects 4/256 at 0.01; the chosen IUT 2/256."""
        def legacy(DA, DB):
            obs = max(min(stats.t_stat(DA), stats.t_stat(DB)), min(-stats.t_stat(DA), -stats.t_stat(DB)))
            k = 0
            for e in itertools.product((1, -1), repeat=8):
                a = [x * s for x, s in zip(DA, e)]
                b = [x * s for x, s in zip(DB, e)]
                t = max(min(stats.t_stat(a), stats.t_stat(b)), min(-stats.t_stat(a), -stats.t_stat(b)))
                k += t >= obs - 1e-12
            return k / 256
        DB = [2 + 0.01 * b for b in range(8)]
        old = new = 0
        for e in itertools.product((1, -1), repeat=8):
            DA = [s * (0.20 + 0.05 * b) for b, s in enumerate(e)]
            old += legacy(DA, DB) <= 0.01
            new += stats.hc_test({b: (DA[b], DB[b]) for b in range(8)})["reject"]
        self.assertEqual((old, new), (4, 2))

    def test_material_and_inversion(self):
        """H.16 33-34: material = detection on D - DELTA_C, then max; the exact lower bound's breakpoints are
        the nonempty-subset means: at 7 blocks the minimum block delta, at 6 blocks -inf."""
        d = {b: (0.03 + 0.001 * b, 0.05 + 0.002 * b) for b in range(8)}
        r = stats.hc_test(d)
        pa = stats.signflip_p([v[0] - stats.DELTA_C for v in d.values()])[2]
        pb = stats.signflip_p([v[1] - stats.DELTA_C for v in d.values()])[2]
        self.assertEqual(r["p_material"], max(pa, pb))
        D7 = [0.4, -0.1, 0.3, 0.25, 0.6, 0.05, 0.2]
        self.assertEqual(stats.signflip_lower(D7), min(D7))
        self.assertEqual(stats.signflip_lower(D7[:6]), -math.inf)
        D8 = D7 + [0.15]
        L = stats.signflip_lower(D8)
        means = sorted({sum(c) / len(c) for k in range(1, 9) for c in itertools.combinations(D8, k)})
        self.assertTrue(any(abs(L - x) < 1e-12 for x in means))
        eps = 1e-9                                                    # p(D - a) <= 0.01 just below L, not above
        self.assertLessEqual(stats.signflip_p([x - (L - eps) for x in D8])[2], 0.01)
        self.assertGreater(stats.signflip_p([x - (L + eps) for x in D8])[2], 0.01)


class TestReview68(unittest.TestCase):
    def test_holm_plateau_keeps_the_raw_order(self):
        """#68 review 1: raw p H-C = 3/256, H-P .012, H-Q .014, H-F .020, H-T .030: every adjusted p is
        .05859375 and Holm rejects nothing; H-C is FIRST in the raw step-down, so its active level is .01
        (not .05), the step-down reached it, and the family decision rejects nothing."""
        h = stats.holm({"H-C": 3 / 256, "H-P": 0.012, "H-Q": 0.014, "H-F": 0.020, "H-T": 0.030})
        self.assertTrue(all(abs(v - 0.05859375) < 1e-15 for v in h["adjusted"].values()))
        self.assertEqual(h["order"], ["H-C", "H-P", "H-Q", "H-F", "H-T"])
        self.assertEqual(stats.active_level(h, "H-C"), 0.01)
        self.assertTrue(h["reached"]["H-C"])
        self.assertFalse(h["reached"]["H-P"])                       # (H-C not rejected: the step-down stops)
        hc = {"available": True, "estimate_A": 0.1, "estimate_B": 0.1}
        self.assertEqual(stats.family_decision(h, hc), {k: False for k in stats.HYPOTHESES})
        # a rejecting family: H-P .001 (level .01), H-C .0117 at level .0125, then H-Q .02 > .0167 stops
        h2 = stats.holm({"H-C": 3 / 256, "H-P": 0.001, "H-Q": 0.02, "H-F": 0.5, "H-T": 0.6})
        self.assertEqual((stats.active_level(h2, "H-C"), h2["reached"]["H-C"]), (0.05 / 4, True))
        fd = stats.family_decision(h2, hc)
        self.assertEqual((fd["H-P"], fd["H-C"], fd["H-Q"]), (True, True, False))
        self.assertFalse(stats.family_decision(h2, dict(hc, estimate_B=-0.01))["H-C"])   # (the IUT direction)
        with self.assertRaises(stats.StatsError):
            stats.holm({"H-C": math.nan})

    def test_constant_samples_have_zero_se(self):
        """#68 review 2: non-dyadic constant samples (0.1 x 32, 0.1 x 30, 0.3 x 7): se exactly 0, so the
        original-zero-SE rule makes the test unavailable (no T* = 0 artefact, no p = .0001)."""
        for v, n in ((0.1, 32), (0.1, 30), (0.3, 7), (1 / 3, 11)):
            m, se = stats.mean_se([v] * n)
            self.assertEqual((m, se), (v, 0.0))
            r = stats.cluster_test([v] * n, stats.mean_se, draws=50)
            self.assertFalse(r["available"])
            self.assertIn("standard error is 0", r["reason"])
        m, se = stats.mean_se([0.1] * 31 + [0.1000000001])
        self.assertGreater(se, 0)

    def test_failed_draws_make_the_test_unavailable(self):
        """#68 review 3: a NaN (or failing) bootstrap estimate is a failure with its draw recorded, never a
        -inf or a non-exceedance; a NaN observed score has no model p-value."""
        vals = [0.1 * k for k in range(12)]
        calls = {"n": 0}

        def est(units):
            calls["n"] += 1
            if calls["n"] == 5:                     # (the 4th bootstrap draw)
                return math.nan, math.nan
            return stats.mean_se(units)
        r = stats.cluster_test(vals, est, draws=100, rng=rqlib.SplitMix64(1))
        self.assertFalse(r["available"])
        self.assertEqual(r["failed_draw"], 3)
        calls["n"] = 0

        def boom(units):
            calls["n"] += 1
            if calls["n"] == 3:
                raise ZeroDivisionError("x")
            return stats.mean_se(units)
        r = stats.cluster_test(vals, boom, draws=100, rng=rqlib.SplitMix64(1))
        self.assertEqual((r["available"], r["failed_draw"]), (False, 1))

        def inf_se(units):
            return stats.mean_se(units)[0], math.inf
        self.assertFalse(stats.cluster_test(vals, lambda u: (stats.mean_se(u)[0], 0.5), draws=5)["available"] is False)
        self.assertFalse(stats.cluster_interval(vals[:3], inf_se, draws=5)["available"])
        with self.assertRaises(stats.StatsError):
            stats.model_p(math.nan, {"a": [1.0, 2.0]})
        with self.assertRaises(stats.StatsError):
            stats.model_p(1.0, {"a": [math.nan, 2.0]})
        with self.assertRaises(stats.StatsError):
            stats.critical_value([1.0, math.nan])
        self.assertEqual(stats.model_p(math.inf, {"a": [1.0, math.inf]}), 2 / 3)   # (+inf is a value)

    def test_reported_bounds_are_99_percent(self):
        """#68 review 9: lower99 is the 99% bound at every decision level; the active-level bound is
        reported beside it with its own confidence."""
        D = {b: (0.03 + 0.01 * math.sin(b), 0.02 - 0.015 * math.cos(3 * b)) for b in range(8)}
        r1, r5 = stats.hc_test(D, alpha=0.01), stats.hc_test(D, alpha=0.05)
        self.assertEqual(r1["lower99"], r5["lower99"])
        self.assertEqual(r5["lower99"]["confidence"], 0.99)
        self.assertEqual(r5["lower_at_alpha"]["confidence"], 0.95)
        self.assertGreater(r5["lower_at_alpha"]["min"], r5["lower99"]["min"])

    def test_exact_ties(self):
        """#68 review 12: eight deltas all 1e-14: the exact sum test's p is 1/256 (no absolute tolerance),
        and the inversion's 99% bound is positive, consistently; exact symmetric ties still count."""
        D = [1e-14] * 8
        self.assertEqual(stats.signflip_p(D)[2], 1 / 256)
        self.assertGreater(stats.signflip_lower(D), 0.0)
        self.assertEqual(stats.signflip_p([0.0] * 8)[2], 1.0)
        self.assertEqual(stats.signflip_p([0.1, -0.1])[0], 3)          # (exact zero sums: ties, counted)
        # p(D - a) <= alpha exactly when a < L, at the bound's breakpoint
        D8 = [0.4, -0.1, 0.3, 0.25, 0.6, 0.05, 0.2, 0.15]
        L = stats.signflip_lower(D8)
        self.assertGreater(stats.signflip_p([x - L for x in D8])[2], 0.01)         # (closed at L)
        self.assertLessEqual(stats.signflip_p([x - (L - 1e-12) for x in D8])[2], 0.01)


class TestMultiplicityAndCalibration(unittest.TestCase):
    def test_holm(self):
        """The user's decision: Holm at familywise 0.05 over the five; an unavailable hypothesis keeps its
        row as p = 1 (no reallocation); the reciprocal headline needs both H-P and H-Q."""
        h = stats.holm({"H-P": 0.004, "H-Q": 0.011, "H-F": 0.03, "H-T": None, "H-C": 0.2})
        self.assertAlmostEqual(h["adjusted"]["H-P"], 0.02)
        self.assertAlmostEqual(h["adjusted"]["H-Q"], 0.044)
        self.assertAlmostEqual(h["adjusted"]["H-F"], 0.09)
        self.assertEqual(h["adjusted"]["H-T"], 1.0)
        self.assertEqual(h["unavailable"], ["H-T"])
        self.assertEqual([k for k, v in h["reject"].items() if v], ["H-P", "H-Q"])
        rd = stats.reciprocal_directional(h)
        self.assertTrue(rd["claim"])
        self.assertAlmostEqual(rd["p"], 0.044)
        h2 = stats.holm({"H-P": 0.004, "H-Q": 0.02, "H-F": 0.5, "H-T": 0.5, "H-C": 0.5})
        self.assertFalse(stats.reciprocal_directional(h2)["claim"])
        self.assertEqual(stats.holm({})["adjusted"], {k: 1.0 for k in stats.HYPOTHESES})   # (H.17 40: rows kept)

    def test_acceptance_and_cpu(self):
        """H.17 35-36 and H.11: U95 at N = 1,000 (12 pass, 13 fail); the CPU arithmetic; critical values."""
        self.assertAlmostEqual(stats.clopper_pearson_upper(12, 1000), 0.0193702, places=6)
        self.assertAlmostEqual(stats.clopper_pearson_upper(13, 1000), 0.0205893, places=6)
        self.assertTrue(stats.acceptance(12, 1000)["pass"])
        self.assertFalse(stats.acceptance(13, 1000)["pass"])
        self.assertEqual(stats.clopper_pearson_upper(5, 5), 1.0)
        self.assertEqual(stats.CPU_CEILING_H, 240.0)                       # (amendment D5)
        self.assertAlmostEqual(24_000 * 36.0 / 3600, 240.0)
        self.assertAlmostEqual(24_000 * 35.1 / 3600, 234.0)
        self.assertEqual(stats.cpu_targets(), {"ceiling_cpu_s_per_panel": 36.0, "target_cpu_s_per_panel": 35.1})
        self.assertEqual(stats.critical_value(list(range(160))), 159)    # ceil(.99 x 161) = 160: the maximum
        self.assertAlmostEqual(stats.model_p(5.0, {"a": [1.0, 6.0, 7.0], "b": [9.0, 9.0, 1.0]}), 3 / 4)
        self.assertAlmostEqual(stats.t_sf(2.0395134, 31), 0.025, places=5)

    def test_source_weights(self):
        """H.17 38: m1 = 2, m2 = 1, m3 = 0."""
        m = {1: 2, 2: 1, 3: 0}
        self.assertEqual(stats.source_weight(m, 1, 2), 2)
        self.assertEqual(stats.source_weight(m, 1, 1), 2)               # within-world: m_w, not m_w^2
        self.assertEqual(stats.source_weight(m, 3, 1), 0)
        self.assertEqual(stats.source_weight(m, 1, None), 2)            # against a frozen reference
        recs = [("w1", "w2", 1.0), ("w2", "w1", 0.0), ("w1", "w1", 1.0), ("w3", None, 0.5)]
        with self.assertRaises(stats.StatsError):                     # (a draw of w2 alone has no mean)
            stats.crossed_mean_draws(recs, draws=300, rng=rqlib.SplitMix64(4))
        full, draws = stats.crossed_mean_draws(recs, draws=300, rng=rqlib.SplitMix64(4), undefined="-inf")
        self.assertAlmostEqual(full, 2.5 / 4)
        self.assertEqual(len(draws), 300)                               # (never silently shortened)
        self.assertTrue(all(0.0 <= x <= 1.0 or x == -math.inf for x in draws))
        self.assertGreater(sum(x == -math.inf for x in draws), 0)

    def test_undefined_crossed_draws(self):
        """#68 review 10: one edge w1 -> w2: a draw of the same root twice weighs 0 (about half the draws);
        "fail" refuses, "-inf" keeps every draw."""
        recs = [("w1", "w2", 0.3)]
        with self.assertRaises(stats.StatsError):
            stats.crossed_mean_draws(recs, draws=200, rng=rqlib.SplitMix64(9))
        _, d = stats.crossed_mean_draws(recs, draws=200, rng=rqlib.SplitMix64(9), undefined="-inf")
        k = sum(x == -math.inf for x in d)
        self.assertEqual(len(d), 200)
        self.assertTrue(60 < k < 140, k)
        self.assertTrue(all(x == 0.3 for x in d if x != -math.inf))
        with self.assertRaises(stats.StatsError):
            stats.crossed_mean_draws(recs, undefined="drop")


def layout64(blocks=8):
    """The registered D7 layout: per block 4C + 2A + 2B."""
    out = []
    for b in range(1, blocks + 1):
        out += [{"id": f"C{b}{k}", "treatment": "C", "block": b} for k in range(4)]
        out += [{"id": f"{t}{b}{k}", "treatment": t, "block": b} for t in "AB" for k in range(2)]
    return out


def eco_doc(reg, dead=(), refill=(), q200=None):
    """worlds.py ecology's form (#75): per slot its attempts (the retained one last); Q200 recomputed unless given."""
    slots = {w["id"]: {"treatment": w["treatment"], "block": w["block"],
                       "attempts": [{"observation": "event" if w["id"] in dead else "administrative",
                                     "refill": {"frame": 9_000_000} if w["id"] in refill else None}]} for w in reg}
    q = sorted(w for w, s in slots.items() if s["treatment"] == "C" and w not in dead and w not in refill)
    return {"schema": stats.ECOLOGY_SCHEMA, "registry_sha256": "r" * 64, "primary_horizon": 200_000_000,
            "slots": slots, "Q200": {"worlds": q if q200 is None else q200, "count": len(q)},
            "summary": {t: {"first_attempt": {"survival": {"200000000": {"N": n}}}} for t, n in (("C", 32), ("A", 16), ("B", 16))}}


def hc_slopes(reg, missing=(), effect=0.3, incomplete=()):
    """Per world H-C coarse fit records: C worlds d = effect (+ a small world term), controls d = 0, each certified
    complete; `missing` worlds a failed fit (a nonfinite slope), `incomplete` ones finite but not certified."""
    out = {}
    for k, w in enumerate(reg):
        if w["id"] in missing:
            out[w["id"]] = {"neural": float("nan"), "scripted": 0.1, "complete": True}
            continue
        d = (effect + 0.01 * (k % 3)) if w["treatment"] == "C" else 0.001 * (k % 2)
        out[w["id"]] = {"neural": 0.5 + d, "scripted": 0.5, "complete": w["id"] not in incomplete}
    return out


def mask_doc(reg, gaps):
    """A graphmask/2 of the registry (every world established at attempt 0, 5M burn-in, 8 restarts) whose snapshots
    are the given technical gaps {(world, t): why}; its own evidence consistent (graph.mask_evidence_problems)."""
    est = {"decided": True, "disposition": "established", "why": "alive at the burn-in frame"}
    W = {w["id"]: {"uuid": f"u-{w['id']}", "attempt": 0, "attempt_uuid": f"u-{w['id']}", "burn_in": est,
                   "valid_before": None, "first_terminal": None, "frontier": 200_000_000, "refill": None,
                   "prior_attempts": [], "available_sha256": {}} for w in reg}
    import uuid

    def snap(u, f):                            # (plan.py's snapshot uuid recipe)
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:snapshot:{u}:{int(f)}"))
    S = {f"{w}:{1 if t == 0 else t * 1_000_000}": {
        "world": w, "time": t, "frame": 1 if t == 0 else t * 1_000_000, "status": "technical", "why": why,
        "uuid": f"u-{w}", "attempt": 0, "snapshot": snap(f"u-{w}", 1 if t == 0 else t * 1_000_000)}
        for (w, t), why in gaps.items()}
    return {"schema": stats.MASK_SCHEMA, "graph": {"edges_sha256": "g" * 64},
            "registry": {"sha256": "r" * 64, "burn_in_frame": 5_000_000, "max_restarts": 8}, "worlds": W, "snapshots": S}


def has_validator():
    import graph as graphlib
    return hasattr(graphlib, "mask_evidence_problems")


class TestEligibility(unittest.TestCase):
    """THE ELIGIBILITY DISPATCHER (Annex H D6 rules 26-27, 33; D7 rules 36-38): |Q200| >= 24 only for H-P/Q/F/T on the
    common Q200; H-C independently by usable blocks with count weights; unavailable rows as p = 1 in Holm; technical
    gaps and failed / incomplete fits pending repair, never dropped (Codex #68 D6)."""

    def setUp(self):
        self.reg = {"worlds": layout64()}

    def run_(self, dead=(), refill=(), missing=(), incomplete=(), mask=None, results=None):
        reg = self.reg
        hc = hc_slopes(reg["worlds"], missing, incomplete=incomplete)
        rec, D, W = stats.eligibility(eco_doc(reg["worlds"], dead, refill), reg, hc, registry_sha256="r" * 64,
                                      mask=mask, eco_sha256="e" * 64, mask_sha256=None if mask is None else "m" * 64,
                                      hc_provenance=None if mask is None else
                                      stats.observation_provenance(mask, "m" * 64, sorted(hc)))
        return rec, D, W, stats.decide(rec, results or {}, D, W)

    def test_fewer_than_24_survivors_with_usable_hc_blocks(self):
        """Q200 = 22 (ten C histories ended): H-P, H-Q, H-F and H-T are unavailable (p = 1 in Holm, their results
        never used), while H-C keeps all eight usable blocks (>= 1 C in each), is tested and decided under Holm at
        its reached active level; the ecology is bound, consuming no alpha."""
        dead = [f"C{b}{k}" for b in range(1, 6) for k in (0, 1)]
        res = {h: {"available": True, "p": 1e-9, "worlds": []} for h in stats.Q200_FAMILY}
        rec, D, W, dec = self.run_(dead=dead, results=res)
        self.assertEqual((rec["Q200"]["count"], rec["Q200"]["available"]), (22, False))
        for h in stats.Q200_FAMILY:
            self.assertFalse(rec["hypotheses"][h]["available"])
            self.assertIn("22 < 24", rec["hypotheses"][h]["reason"])
            self.assertIsNone(dec["pvalues"][h])
            self.assertEqual(dec["holm"]["raw"][h], 1.0)
        hc = rec["hypotheses"]["H-C"]
        self.assertEqual((hc["available"], hc["n_blocks"], hc["p_floor"]), (True, 8, 1 / 256))
        self.assertEqual(hc["counts"]["1"], {"C": 2, "A": 2, "B": 2})
        self.assertEqual((dec["pvalues"]["H-C"], dec["H-C"]["alpha"], dec["H-C"]["reached"]), (1 / 256, 0.01, True))
        self.assertEqual(dec["decision"], {"H-P": False, "H-Q": False, "H-F": False, "H-T": False, "H-C": True})
        self.assertEqual((rec["ecology"]["sha256"], rec["ecology"]["alpha"][:4]), ("e" * 64, "none"))
        self.assertEqual(rec["ecology"]["first_attempt_200M"]["C"], {"N": 32})

    def test_one_surviving_control_of_each_type(self):
        """Block 3 keeps ONE A and ONE B (the others ended): it is usable, its count weights a = (1/n_C + 1/n_G)^-1 =
        (1/4 + 1)^-1 = 0.8 against 4/3 in intact blocks, normalized per control type; the weighted estimates are
        the normalized-weight sums (stats.hc_test's normalization, verified, not replaced)."""
        rec, D, W, dec = self.run_(dead=["A30", "B31"])
        hc = rec["hypotheses"]["H-C"]
        self.assertEqual((hc["n_blocks"], hc["counts"]["3"]), (8, {"C": 4, "A": 1, "B": 1}))
        self.assertAlmostEqual(hc["weights_a"]["3"]["A"], 0.8)
        self.assertAlmostEqual(hc["weights_a"]["1"]["B"], 4 / 3)
        for G in "AB":
            wn = hc["weights_normalized"][G]
            self.assertAlmostEqual(sum(wn.values()), 1.0)
            self.assertAlmostEqual(wn["3"], 0.8 / (7 * 4 / 3 + 0.8))
            est = sum(wn[str(b)] * D[b][0 if G == "A" else 1] for b in D)
            self.assertAlmostEqual(dec["H-C"][f"estimate_{G}"], est)
        self.assertNotIn("A31", rec["ineligible"])
        self.assertIn("no complete retained 200M history", rec["ineligible"]["A30"])
        self.assertTrue(dec["decision"]["H-C"])

    def test_block_with_an_ineligible_control(self):
        """Block 5 loses both B controls (their histories ended) and is unusable; block 6's refilled A is ineligible (a
        refill never establishes natural coexistence) but its other A keeps the block usable: 7 usable blocks, floor
        1/128; no control is selected or replaced. (Codex #68 D6 P2-1) A complete-history control whose H-C fit
        FAILED, or whose finite slopes are not certified complete, is never an exclusion: H-C is pending repair."""
        rec, D, W, dec = self.run_(dead=["B50", "B51"], refill=["A60"])
        hc = rec["hypotheses"]["H-C"]
        self.assertEqual((hc["n_blocks"], hc["p_floor"], sorted(D)), (7, 1 / 128, [1, 2, 3, 4, 6, 7, 8]))
        self.assertIn("0 B", hc["unusable_blocks"]["5"])
        self.assertIn("refill", rec["ineligible"]["A60"])
        self.assertEqual(hc["counts"]["6"], {"C": 4, "A": 1, "B": 2})
        self.assertEqual(dec["pvalues"]["H-C"], 1 / 128)
        self.assertNotIn("A60", rec["eligible"]["A"])
        for kw, status in (({"missing": ["B51"]}, "failed"), ({"incomplete": ["B51"]}, "incomplete")):
            rec2, D2, W2, dec2 = self.run_(dead=["B50"], refill=["A60"], **kw)
            h2 = rec2["hypotheses"]["H-C"]
            self.assertEqual((h2["available"], h2["fits"]), (False, {"B51": status}))
            self.assertIn("pending repair", h2["reason"])
            self.assertIn("pending repair", rec2["ineligible"]["B51"])
            self.assertIsNone(dec2["pvalues"]["H-C"])
            self.assertFalse(dec2["decision"]["H-C"])

    def test_q200_population_and_holm_rows(self):
        """With >= 24 survivors H-P / H-Q / H-F / H-T enter only through their ANALYSIS RESULTS (Codex #68 D6 P2-4:
        family_p): available, computed on EXACTLY the common Q200 (another population is refused), H-F with its
        calibrated critical value (its model p only when S_F exceeds c_F), H-T with its frozen critical value; an
        unavailable or uncalibrated result is an unavailable row (p = 1); fewer than two usable blocks make H-C
        unavailable (p = 1), never dropped from the five-row Holm family."""
        rec, D, W = stats.eligibility(eco_doc(self.reg["worlds"]), self.reg, hc_slopes(self.reg["worlds"]),
                                      registry_sha256="r" * 64)
        q = rec["Q200"]["worlds"]
        self.assertEqual(len(q), 32)
        bind = {h: stats.result_binding(rec, h) for h in stats.Q200_FAMILY}
        res = {"H-P": {"available": True, "p": 0.001, "worlds": q, "binding": bind["H-P"]},
               "H-Q": {"available": True, "p": 0.004, "worlds": list(reversed(q)), "binding": bind["H-Q"]},
               "H-F": {"available": True, "S_F": 0.2, "c_F": 0.5, "p_F": 0.001, "worlds": q, "binding": bind["H-F"]},
               "H-T": {"available": False, "p_model": 0.001, "c_T": 7.0, "T_T": 8.0, "worlds": q, "failure": None}}
        dec = stats.decide(rec, res, D, W)
        self.assertEqual((dec["pvalues"]["H-P"], dec["pvalues"]["H-Q"], dec["pvalues"]["H-F"], dec["pvalues"]["H-T"]),
                         (0.001, 0.004, 1.0, None))                      # (S_F <= c_F: never a rejection; H-T failed)
        self.assertIn("unavailable", dec["unavailable"]["H-T"])
        self.assertEqual(sorted(dec["holm"]["unavailable"]), ["H-T"])
        self.assertEqual(stats.family_p("H-F", dict(res["H-F"], S_F=0.9)), (0.001, None))
        self.assertIsNone(stats.family_p("H-F", dict(res["H-F"], c_F=None))[0])
        self.assertEqual(stats.family_p("H-T", dict(res["H-T"], available=True)), (0.001, None))
        self.assertEqual(stats.family_p("H-T", dict(res["H-T"], available=True, T_T=0.5)), (1.0, None))
        self.assertIsNone(stats.family_p("H-T", dict(res["H-T"], available=True, c_T=None))[0])
        p, why = stats.family_p("H-T", dict(res["H-T"], available=True, c_T=1.0, T_T=3.0))   # (Codex #68 D6 r2 P2-4)
        self.assertIsNone(p)
        self.assertIn("below the registered guard", why)
        self.assertEqual(stats.family_p("H-T", dict(res["H-T"], available=True, c_T=stats.HT_GUARD)), (0.001, None))
        self.assertAlmostEqual(stats.HT_GUARD, math.log(600), places=12)
        self.assertIsNone(stats.family_p("H-P", {"available": False, "p": 0.001})[0])
        with self.assertRaisesRegex(stats.StatsError, "another population"):
            stats.decide(rec, {"H-P": {"available": True, "p": 0.001, "worlds": q[1:]}}, D, W)
        # (Codex #68 D6 r2 P2-2: only results BOUND to this record enter: unbound, another record's, another
        # hypothesis's binding are refused; the record's identity survives a file round trip)
        for b in (None, dict(bind["H-P"], eligibility_sha256="0" * 64), bind["H-Q"]):
            with self.assertRaisesRegex(stats.StatsError, "not bound to this eligibility record"):
                stats.decide(rec, {"H-P": {"available": True, "p": 0.001, "worlds": q, "binding": b}}, D, W)
        self.assertEqual(stats.record_sha256(json.loads(json.dumps(rec))), bind["H-P"]["eligibility_sha256"])
        self.assertEqual(stats.require_population(rec, "H-P", q), bind["H-P"])
        stats.require_population(rec, "H-C", rec["hypotheses"]["H-C"]["worlds"])
        recb = json.loads(json.dumps(rec))
        prov = {"graph_edges_sha256": "g" * 64, "mask_sha256": "m" * 64, "snapshots_sha256": "s" * 64}
        recb["hypotheses"]["H-P"]["binding"] = prov
        self.assertEqual(stats.require_population(recb, "H-P", q, dict(prov))["provenance"], prov)
        for bad in (None, dict(prov, graph_edges_sha256="h" * 64), dict(prov, snapshots_sha256="t" * 64)):
            with self.assertRaisesRegex(stats.StatsError, "provenance"):
                stats.require_population(recb, "H-P", q, bad)
        with self.assertRaisesRegex(stats.StatsError, "registered population"):
            stats.require_population(rec, "H-F", q[1:])
        dead = [w["id"] for w in self.reg["worlds"] if w["treatment"] != "C" and w["block"] > 1]
        rec1, D1, W1 = stats.eligibility(eco_doc(self.reg["worlds"], dead), self.reg, hc_slopes(self.reg["worlds"]))
        dec1 = stats.decide(rec1, {}, D1, W1)
        self.assertEqual((rec1["hypotheses"]["H-C"]["available"], dec1["pvalues"]["H-C"], dec1["holm"]["raw"]["H-C"]),
                         (False, None, 1.0))
        self.assertIn("1 usable block", dec1["unavailable"]["H-C"])
        self.assertEqual(sorted(dec1["decision"]), sorted(stats.HYPOTHESES))
        with self.assertRaisesRegex(stats.StatsError, "is unavailable"):
            stats.require_population(rec1, "H-C", [])

    def test_ecology_export_and_technical_gaps(self):
        """The ecological export must be this registry's and its Q200 its own slots' (recomputed). (Codex #68 D6 P2-2)
        A bound mask needs its bytes' sha256 and #77's shared validator; a technical gap at ANY graph time (here
        11M: a fine / reference time, not a coarse one) of a Q200 world makes H-P / H-Q / H-F / H-T pending repair
        (the world stays in Q200), while H-C (its coarse measurements intact) stays available; a coarse gap makes H-C
        pending repair too."""
        reg = self.reg
        for bad, msg in ((dict(eco_doc(reg["worlds"]), registry_sha256="x" * 64), "another registry"),
                         (eco_doc(reg["worlds"], q200=["C10"]), "Q200 is not its own"),
                         (dict(eco_doc(reg["worlds"]), schema="x"), "ecology schema")):
            with self.assertRaisesRegex(stats.StatsError, msg):
                stats.eligibility(bad, reg, hc_slopes(reg["worlds"]), registry_sha256="r" * 64)
        mask = mask_doc(reg["worlds"], {("C11", 11): "not archived, and attempt 0 is done"})
        with self.assertRaisesRegex(stats.StatsError, "mask_sha256"):
            stats.eligibility(eco_doc(reg["worlds"]), reg, hc_slopes(reg["worlds"]), mask=mask)
        if not has_validator():
            with self.assertRaisesRegex(stats.StatsError, "mask_evidence_problems"):
                self.run_(mask=mask)
            self.skipTest("graph.mask_evidence_problems (#77) is not on this branch yet")
        rec, D, W, dec = self.run_(mask=mask)
        self.assertIn("C11", rec["Q200"]["worlds"])
        self.assertEqual(rec["technical_gaps"], {"C11": [[11, "technical", "not archived, and attempt 0 is done"]]})
        self.assertEqual(rec["mask"]["sha256"], "m" * 64)
        for h in stats.Q200_FAMILY:
            self.assertFalse(rec["hypotheses"][h]["available"], h)
            self.assertIn("pending repair", rec["hypotheses"][h]["reason"])
            self.assertIsNone(dec["pvalues"][h])
        self.assertTrue(rec["hypotheses"]["H-C"]["available"])
        rec2, _, _, _ = self.run_(mask=mask_doc(reg["worlds"], {("C11", 50): "not archived"}))
        self.assertFalse(rec2["hypotheses"]["H-C"]["available"])
        self.assertIn("excluded by the mask", rec2["ineligible"]["C11"])
        # (Codex #68 D6 r2 P2-2: observations are bound to the mask's graph, digest and snapshot identities)
        clean, hc = mask_doc(reg["worlds"], {}), hc_slopes(reg["worlds"])
        for prov in (None, stats.observation_provenance(dict(clean, graph={"edges_sha256": "h" * 64}), "m" * 64,
                                                        sorted(hc))):
            with self.assertRaisesRegex(stats.StatsError, "H-C fits' provenance"):
                stats.eligibility(eco_doc(reg["worlds"]), reg, hc, registry_sha256="r" * 64, mask=clean,
                                  eco_sha256="e" * 64, mask_sha256="m" * 64, hc_provenance=prov)
        rec3, D3, W3, _ = self.run_(mask=clean)
        q = rec3["Q200"]["worlds"]
        prov = stats.observation_provenance(clean, "m" * 64, q)
        self.assertEqual(rec3["hypotheses"]["H-P"]["binding"], prov)
        self.assertEqual(rec3["mask"]["graph_edges_sha256"], "g" * 64)
        other = json.loads(json.dumps(clean))
        other["worlds"][q[0]]["available_sha256"] = {"5000000": "a" * 64}          # (another snapshot's bytes)
        for bad in (stats.observation_provenance(other, "m" * 64, q), stats.observation_provenance(clean, "n" * 64, q),
                    stats.observation_provenance(clean, "m" * 64, sorted(hc))):
            with self.assertRaisesRegex(stats.StatsError, "provenance"):
                stats.require_population(rec3, "H-P", q, bad)
        b = stats.require_population(rec3, "H-P", q, prov)
        dec3 = stats.decide(rec3, {"H-P": {"available": True, "p": 0.001, "worlds": q, "binding": b}}, D3, W3)
        self.assertEqual(dec3["pvalues"]["H-P"], 0.001)

    def test_hc_contrasts_are_anchored_in_their_record(self):
        """Codex #68 D6 r3 P2-2, r5: the eligibility record ANCHORS H-C's two payloads: its H-C entry stores their
        role-tagged digests (contrast_digest: role, H-C binding, blocks), and decide refuses, before either hc_test,
        anything that does not hash to them: another record's contrasts, edited values, a fabricated stamp, weights
        passed as deltas. The stamp an HCContrasts carries can only refuse, never accept. The matching case, plain
        copies and pickles of the producer's values, and a validated restore (check_restoration) pass."""
        import copy
        import pickle
        recA, DA, WA, decA = self.run_(dead=["A30"])
        recB, DB, WB, decB = self.run_(dead=["B31"])
        self.assertNotEqual((dict(DA), dict(WA)), (dict(DB), dict(WB)))     # (the two records' numbers differ)
        cd = recB["hypotheses"]["H-C"]["contrast_digests"]
        self.assertEqual(cd, {"deltas": stats.contrast_digest("deltas", DB, None),
                              "weights": stats.contrast_digest("weights", WB, None)})
        self.assertNotEqual(cd["deltas"], stats.contrast_digest("weights", DB, None))      # (the role is in the digest)
        self.assertEqual(stats.record_sha256(json.loads(json.dumps(recB))), DB.binding["eligibility_sha256"])
        self.assertEqual(decA["pvalues"]["H-C"], stats.decide(recA, {}, DA, WA)["pvalues"]["H-C"])   # (matching: passes)
        bindA = stats.result_binding(recA, "H-C")
        self.assertEqual((DA.role, WA.role, DA.binding, WA.binding), ("deltas", "weights", bindA, bindA))
        self.assertEqual(DA.binding["provenance"], recA["hypotheses"]["H-C"]["binding"])
        msg = "not bound to this eligibility record"
        for d, w in ((DA, WA), (DA, WB), (DB, WA)):                      # (A's stamped contrasts, or half, into B)
            with self.assertRaisesRegex(stats.StatsError, msg):
                stats.decide(recB, {}, d, w)
        produced = "not the values stats.eligibility produced for this record"
        # (A's values without their stamp, and Codex's fabricated stamp of B on A's values, hash to A's digests, not B's)
        def fabricated(elig, values):                                    # (Codex r5's construction, verbatim)
            x = stats.HCContrasts(values)
            x.binding = stats.result_binding(elig, "H-C")
            x.digest = stats.contrasts_sha256(x, x.binding)
            return x
        for d, w in ((dict(DA), dict(WA)), (fabricated(recB, DA), fabricated(recB, WA)), (DB, fabricated(recB, WA)),
                     (fabricated(recB, DA), WB)):
            with self.assertRaisesRegex(stats.StatsError, produced):
                stats.decide(recB, {}, d, w)
        # (weights passed as deltas, authentic, copied or fabricated; the reverse: the role is in the digest)
        with self.assertRaisesRegex(stats.StatsError, "role mismatch"):
            stats.decide(recB, {}, WB, WB)
        for d, w in ((dict(WB), dict(WB)), (fabricated(recB, WB), fabricated(recB, WB)), (dict(DB), dict(DB))):
            with self.assertRaisesRegex(stats.StatsError, produced):
                stats.decide(recB, {}, d, w)
        with self.assertRaisesRegex(stats.StatsError, "role mismatch"):      # (Codex r5's second snippet, verbatim)
            stats.restore_hc_contrasts(recB, WB.to_json(), WB.to_json())
        # (the producer's own values pass in any carrier: plain copies, deepcopies, pickles; they match the record)
        for d, w in ((dict(DB), dict(WB)), (copy.deepcopy(DB), copy.deepcopy(WB)), (stats.HCContrasts(DB), stats.HCContrasts(WB)),
                     (pickle.loads(pickle.dumps(DB)), pickle.loads(pickle.dumps(WB)))):
            self.assertEqual(stats.decide(recB, {}, d, w)["pvalues"], decB["pvalues"])
        # (string block keys, a missing block, nothing: decide wants the record's blocks; restore normalizes keys)
        for d, w in ((json.loads(json.dumps(DB)), WB), (DB, {}), ({}, {})):
            with self.assertRaisesRegex(stats.StatsError, "usable blocks"):
                stats.decide(recB, {}, d, w)
        altered = stats.HCContrasts(DB)                                  # (edited after production, its stamp kept)
        altered.role, altered.binding, altered.digest = DB.role, DB.binding, DB.digest
        altered[next(iter(altered))] = (9.0, 9.0)
        with self.assertRaisesRegex(stats.StatsError, "changed after they were produced"):
            stats.decide(recB, {}, altered, WB)
        relabel = stats.HCContrasts(DA)                                  # (A's content under B's binding, A's checksum)
        relabel.role, relabel.binding, relabel.digest = "deltas", DB.binding, DA.digest
        with self.assertRaisesRegex(stats.StatsError, "changed after they were produced"):
            stats.decide(recB, {}, relabel, WB)
        edited = dict(DB)                                                # (edited, no stamp: the anchor refuses)
        edited[next(iter(edited))] = (9.0, 9.0)
        with self.assertRaisesRegex(stats.StatsError, produced):
            stats.decide(recB, {}, edited, WB)
        fewer = stats._stamp_contrasts(recB, {b: v for b, v in list(DB.items())[1:]}, "deltas")
        with self.assertRaisesRegex(stats.StatsError, "usable blocks"):
            stats.decide(recB, {}, fewer, WB)
        self.assertFalse(hasattr(stats, "stamp_contrasts") or hasattr(stats, "bind_hc_contrasts"))   # (no re-stamping)
        self.check_restoration(recB, DB, WB, DA, WA, msg)
        # (a record without the producer's digests, an older record: refused, never trusted)
        old = json.loads(json.dumps(recB))
        del old["hypotheses"]["H-C"]["contrast_digests"]
        with self.assertRaisesRegex(stats.StatsError, "stores no producer digest"):
            stats.decide(old, {}, DB, WB)
        # (an unavailable H-C uses no contrasts: nothing to validate)
        dead = [w["id"] for w in self.reg["worlds"] if w["treatment"] != "C" and w["block"] > 1]
        rec1, _, _, dec1 = self.run_(dead=dead)
        self.assertFalse(rec1["hypotheses"]["H-C"]["available"])
        self.assertIsNone(stats.decide(rec1, {}, {}, {})["pvalues"]["H-C"])
        if not has_validator():
            self.skipTest("graph.mask_evidence_problems (#77) is not on this branch yet")
        # (graph / mask A into B: the same worlds, blocks and values, other graph edges / mask bytes / snapshot bytes)
        reg = self.reg
        clean = mask_doc(reg["worlds"], {})
        snaps = json.loads(json.dumps(clean))
        snaps["worlds"][reg["worlds"][0]["id"]]["available_sha256"] = {"5000000": "a" * 64}
        hc = hc_slopes(reg["worlds"])
        mA, mB = (clean, "m" * 64), (dict(clean, graph={"edges_sha256": "h" * 64}), "m" * 64)
        for other in (mB, (clean, "n" * 64), (snaps, "m" * 64)):
            recs = []
            for mask, sha in (mA, other):
                recs.append(stats.eligibility(eco_doc(reg["worlds"]), reg, hc, registry_sha256="r" * 64, mask=mask,
                                              eco_sha256="e" * 64, mask_sha256=sha,
                                              hc_provenance=stats.observation_provenance(mask, sha, sorted(hc))))
            (rA, dA, wA), (rB, dB, wB) = recs
            self.assertNotEqual(rA["hypotheses"]["H-C"]["binding"], rB["hypotheses"]["H-C"]["binding"])
            self.assertNotEqual(rA["hypotheses"]["H-C"]["contrast_digests"], rB["hypotheses"]["H-C"]["contrast_digests"])
            self.assertEqual((dict(dA), dict(wA)), (dict(dB), dict(wB)))         # (the same numbers: only provenance differs)
            self.assertIsNotNone(stats.decide(rA, {}, dA, wA)["pvalues"]["H-C"])
            self.assertIsNotNone(stats.decide(rB, {}, dB, wB)["pvalues"]["H-C"])
            with self.assertRaisesRegex(stats.StatsError, msg):                  # (A's stamped contrasts: refused)
                stats.decide(rB, {}, dA, wA)
            self.check_restoration(rB, dB, wB, dA, wA, msg)         # (A's stamped contrasts never restore as B's)

    def check_restoration(self, rec, D, W, otherD, otherW, msg):
        """Codex #68 D6 r4 P2-2, r5: restore_hc_contrasts accepts a payload only if its role-tagged digest is the one
        the RECORD stores (a carried stamp can only refuse); string block keys are normalized first. `D, W` are the
        record's own contrasts (stats.eligibility's), `otherD, otherW` another record's."""
        import pickle
        produced = "not the values stats.eligibility produced for this record"

        def wire(x):                                      # (a real JSON round trip: the block keys become strings)
            return json.loads(json.dumps(x.to_json()))

        def bare(x):                                      # (json.dumps of the mapping itself: string keys, no stamp)
            return json.loads(json.dumps(x))
        first = next(iter(wire(D)["blocks"]))
        self.assertIsInstance(first, str)
        distinct = (dict(otherD), dict(otherW)) != (dict(D), dict(W))
        # (the record's own contrasts restore from a JSON document, in memory, a bare JSON mapping, a plain dict or a
        # pickle, also against a record loaded from its file; the int keys are back, the document's stamp is kept)
        loaded = json.loads(json.dumps(rec))
        for rec_, d, w in ((rec, wire(D), wire(W)), (rec, D, W), (loaded, wire(D), wire(W)), (rec, bare(D), bare(W)),
                           (rec, dict(D), dict(W)), (rec, pickle.loads(pickle.dumps(D)), pickle.loads(pickle.dumps(W)))):
            d2, w2 = stats.restore_hc_contrasts(rec_, d, w)
            self.assertEqual((dict(d2), dict(w2)), (dict(D), dict(W)))
            self.assertTrue(all(isinstance(b, int) for b in d2) and all(isinstance(b, int) for b in w2))
            self.assertEqual(stats.decide(rec, {}, d2, w2)["pvalues"], stats.decide(rec, {}, D, W)["pvalues"])
        d2, w2 = stats.restore_hc_contrasts(rec, wire(D), wire(W))
        self.assertEqual((d2.role, d2.binding, d2.digest, w2.role), (D.role, D.binding, D.digest, W.role))
        # (the other record's stamped contrasts, restored for this record, in memory or serialized, whole or half)
        for d, w in ((otherD, otherW), (wire(otherD), wire(otherW)), (otherD, W), (wire(D), wire(otherW))):
            with self.assertRaisesRegex(stats.StatsError, msg):
                stats.restore_hc_contrasts(rec, d, w)
        if distinct:                                      # (the other record's values without a stamp: the anchor)
            for d, w in ((dict(otherD), dict(otherW)), (bare(otherD), bare(otherW)), (D, dict(otherW))):
                with self.assertRaisesRegex(stats.StatsError, produced):
                    stats.restore_hc_contrasts(rec, d, w)
        # (edited, relabelled or stripped stamps, and edited values without any stamp, are refused)
        edited = wire(D)
        edited["blocks"][first][0] += 1.0
        relabelled = wire(otherD)
        relabelled["binding"] = D.binding
        stripped = wire(D)
        stripped["digest"] = None
        for doc in (edited, relabelled, stripped):
            with self.assertRaisesRegex(stats.StatsError, "changed after they were produced"):
                stats.restore_hc_contrasts(rec, doc, wire(W))
        unstamped = dict(edited, binding=None, digest=None, role=None)
        with self.assertRaisesRegex(stats.StatsError, produced):
            stats.restore_hc_contrasts(rec, unstamped, wire(W))
        unbound = wire(D)
        unbound["binding"] = None
        with self.assertRaisesRegex(stats.StatsError, msg):
            stats.restore_hc_contrasts(rec, unbound, wire(W))
        # (weights restored as deltas and the reverse: the stamp's role refuses it; with the role erased, the
        # anchor's role-tagged digest does)
        for d, w in ((wire(W), wire(W)), (wire(D), wire(D)), (W, W), (D, D)):
            with self.assertRaisesRegex(stats.StatsError, "role mismatch"):
                stats.restore_hc_contrasts(rec, d, w)
        for d, w in ((dict(wire(W), role=None), wire(W)), (bare(W), bare(W)), (dict(W), dict(W))):
            with self.assertRaisesRegex(stats.StatsError, produced):
                stats.restore_hc_contrasts(rec, d, w)
        # (malformed: not a mapping, another schema, a block key that is not a canonical block id or a second spelling of
        # one (json.loads drops duplicate members before this API sees them, so only duplicate normalized ids are
        # claimed), non-finite or bool values, a pair of the wrong length)
        bad_blocks = [{"01": [1.0, 2.0]}, {"x": [1.0, 2.0]}, {1: [1.0, 2.0], "1": [1.0, 2.0]},
                      {first: [float("nan"), 0.0]}, {first: [True, 0.0]}, {first: [1.0]}]
        for bad, why in ([(None, "not a mapping"), (dict(wire(D), schema="x"), "not a contrasts document"),
                          ({"blocks": 5}, "not a contrasts document"), ({"01": [1.0, 2.0]}, "not a block id")]
                         + [(dict(wire(D), blocks=b), "not a block id") for b in bad_blocks]):
            with self.assertRaisesRegex(stats.StatsError, why):
                stats.restore_hc_contrasts(rec, bad, wire(W))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""test_stats.py: Annex H's required checks for stats.py (H.13 1-3, 7-10; H.16 29-34; H.17 35, 36, 38, 40;
the user's Holm decision).

    python3 -I tools/redqueen/test_stats.py [-v]
"""
from __future__ import annotations

import hashlib
import itertools
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
        """H.16 33-34: material = detection on D - 0.02, then max; the exact lower bound's breakpoints are
        the nonempty-subset means: at 7 blocks the minimum block delta, at 6 blocks -inf."""
        d = {b: (0.03 + 0.001 * b, 0.05 + 0.002 * b) for b in range(8)}
        r = stats.hc_test(d)
        pa = stats.signflip_p([v[0] - 0.02 for v in d.values()])[2]
        pb = stats.signflip_p([v[1] - 0.02 for v in d.values()])[2]
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
        self.assertAlmostEqual(24_000 * 14.4 / 3600, 96.0)
        self.assertAlmostEqual(24_000 * 13.5 / 3600, 90.0)
        self.assertEqual(stats.cpu_targets(), {"ceiling_cpu_s_per_panel": 14.4, "target_cpu_s_per_panel": 13.5})
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
        full, draws = stats.crossed_mean_draws(recs, draws=300, rng=rqlib.SplitMix64(4))
        self.assertAlmostEqual(full, 2.5 / 4)
        self.assertTrue(all(0.0 <= x <= 1.0 for x in draws))


if __name__ == "__main__":
    unittest.main()

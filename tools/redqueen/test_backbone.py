#!/usr/bin/env python3
"""test_backbone.py: Annex H.13's estimator checks for backbone.py (H.1 fits, H.2 slopes, H.5 contrasts).
numpy required (skipped without it unless RQ_REQUIRE_NUMPY=1).

    python3 -I tools/redqueen/test_backbone.py [-v]
"""
from __future__ import annotations

import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
try:
    import numpy as np
except ImportError:
    np = None
if np is None and os.environ.get("RQ_REQUIRE_NUMPY"):
    raise SystemExit("RQ_REQUIRE_NUMPY is set, but numpy cannot be imported")

COARSE = [1e-6] + [5.0 * k for k in range(1, 41)]                 # actual times (M): F1, 5M, ..., 200M


def sig(x):
    return 1.0 / (1.0 + math.exp(-x))


def logit(p):
    return math.log(p / (1 - p))


@unittest.skipIf(np is None, "numpy is not installed")
class TestBackbone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import backbone
        import stats
        cls.bb, cls.st = backbone, stats

    def capture_panel(self, slope50, base=-0.4, prey=0.3, shift=0.0, B=324.0):
        """Noiseless expected counts: logit capture = base + shift + prey effect(i) + slope * t / 50."""
        panel = {}
        for k, ti in enumerate(COARSE):
            eff = prey * math.sin(k)
            cs = [B * sig(base + shift + eff + slope50 * t / 50) for t in COARSE]
            panel[ti] = (COARSE, cs, [B] * len(COARSE))
        return panel

    def test_basis(self):
        Bm = self.bb.bspline(np.linspace(0, 1, 11))
        self.assertTrue(np.allclose(Bm.sum(axis=1), 1.0))          # a partition of unity, the end included
        self.assertEqual(Bm.shape, (11, 6))

    def test_hp_material_units_and_world_effects(self):
        """H.13 3 and 6: a logit slope of log(1.10) per 50M returns log(1.10); an added constant in a world
        leaves its slope; repeating a world's cells changes nothing (equal world weights)."""
        d = math.log(1.10)
        b, _ = self.bb.hp_world(self.capture_panel(d), COARSE)
        self.assertAlmostEqual(b, d, places=4)
        b2, _ = self.bb.hp_world(self.capture_panel(d, shift=0.7), COARSE)
        self.assertAlmostEqual(b2, d, places=4)
        rep = {k: (v[0] * 3, v[1] * 3, v[2] * 3) for k, v in self.capture_panel(d).items()}   # cells repeated
        b3, _ = self.bb.hp_world(rep, COARSE)
        self.assertAlmostEqual(b3, b, places=6)
        zeros = {k: (v[0], [0.0] + list(v[1][1:]), v[2]) for k, v in self.capture_panel(d).items()}
        self.assertTrue(math.isfinite(self.bb.hp_world(zeros, COARSE)[0]))   # observed zeros stay zeros

    def test_hq_units_age_only_and_shared_baseline(self):
        """H.13 3-5: a survival-difference slope of 0.02 per 50M returns 0.02; an age-only baseline change
        with S_exposed = S0 - k gives slope 0; the shared baseline cancels exactly in d_w."""
        N = 600.0
        s0 = [0.8 + 0.1 * math.sin(t / 30) for t in COARSE]               # the free baseline varies with age
        free = (COARSE, [N * s for s in s0])
        q = {j: [-0.2 + 0.02 * t / 50 for t in COARSE] for j in range(4)}
        exposed = {j: (COARSE, [N * (s + dq) for s, dq in zip(s0, q[j])]) for j in range(4)}
        b, _ = self.bb.hq_world(free, exposed, COARSE)
        self.assertAlmostEqual(b, 0.02, places=3)
        flat = {j: (COARSE, [N * (s - 0.15) for s in s0]) for j in range(4)}
        b0, _ = self.bb.hq_world(free, flat, COARSE)
        self.assertAlmostEqual(b0, 0.0, places=3)
        neural = {k: (COARSE, [N * (s - 0.1 + 0.03 * t / 50) for s, t in zip(s0, COARSE)]) for k in range(4)}
        scripted = (COARSE, [N * (s - 0.1 + 0.01 * t / 50) for s, t in zip(s0, COARSE)])
        r = self.bb.hc_world(free, neural, scripted, COARSE)
        self.assertAlmostEqual(r["d"], 0.02, places=3)
        self.assertAlmostEqual(r["d"], r["beta_N"] - r["beta_S"], places=12)
        # a perturbed free control moves both q's together: d_w is unchanged (one shared baseline)
        free2 = (COARSE, [N * (s + 0.02 * math.cos(t / 20)) for s, t in zip(s0, COARSE)])
        r2 = self.bb.hc_world(free2, neural, scripted, COARSE)
        self.assertAlmostEqual(r2["d"], r["d"], delta=0.003)

    def test_fast_fits_match_the_reference(self):
        """The batched capture fit and the arrowhead survival fit reproduce the per-opponent and dense
        Newton fits (the same estimator; algebra only)."""
        bb = self.bb
        panel = self.capture_panel(0.1)
        keys = sorted(panel)
        G = bb.fit_captures(COARSE, [panel[k][1] for k in keys], [panel[k][2] for k in keys])
        for k, g in zip(keys, G):
            self.assertTrue(np.allclose(g, bb.fit_capture(*panel[k]), atol=1e-9))
        N = 600.0
        s0 = [0.8 + 0.1 * math.sin(t / 30) for t in COARSE]
        free = (COARSE, [N * s for s in s0])
        exposed = {j: (COARSE, [N * (s - 0.2 + 0.01 * j + 0.02 * t / 50) for s, t in zip(s0, COARSE)]) for j in range(5)}
        c1, d1 = bb.fit_survival(free, exposed)
        c2, d2 = bb.fit_survival_dense(free, exposed)
        self.assertTrue(np.allclose(c1, c2, atol=1e-8))
        for j in range(5):
            self.assertTrue(np.allclose(d1[j], d2[j], atol=1e-8))

    def test_convergence_is_required(self):
        """#68 review 5: an exhausted iteration budget raises (never a returned last iterate); saturated
        counts (all zero, all bounded) converge under the safeguarded Newton; the fast fits too."""
        t = np.array([1e-6] + [5.0 * k for k in range(1, 41)])
        with self.assertRaises(self.bb.BackboneError):
            self.bb._newton(self.bb.basis(t), np.full(len(t), 30.0), np.full(len(t), 100.0), iters=2)
        with self.assertRaises(self.bb.BackboneError):
            self.bb.fit_captures(t, [np.full(len(t), 30.0)], [np.full(len(t), 100.0)], iters=2)
        free = (t, np.full(len(t), 500.0))
        with self.assertRaises(self.bb.BackboneError):
            self.bb.fit_survival(free, {0: (t, np.full(len(t), 400.0))}, iters=2)
        for y in (np.zeros(len(t)), np.full(len(t), 100.0)):           # (saturated: the penalty bounds it)
            g = self.bb.fit_capture(t, y, np.full(len(t), 100.0))
            self.assertTrue(np.all(np.isfinite(g)))
            G = self.bb.fit_captures(t, [y, np.full(len(t), 50.0)], [np.full(len(t), 100.0)] * 2)
            self.assertTrue(np.allclose(G[0], g, atol=1e-6, rtol=1e-9))

    def test_epoch_fits_see_their_epoch_only(self):
        """#68 review 6: a capture panel observed over the whole history, flat inside E2 = [75, 125] but
        changing outside it: the E2 fit restricts the focal observations (every opponent kept), so its
        slope is 0; the basis refuses an out-of-interval time rather than clamping it."""
        t = np.array([1e-6] + [5.0 * k for k in range(1, 41)])
        foc = [x for x in t if 75 <= x <= 125]
        y = np.where(t < 75, 10.0, np.where(t > 125, 90.0, 40.0))
        cap = {k: (t, y, np.full(len(t), 100.0)) for k in range(4)}
        b, m = self.bb.hp_world(cap, foc, (75.0, 125.0))
        self.assertAlmostEqual(b, 0.0, places=8)
        with self.assertRaises(self.bb.BackboneError):
            self.bb.basis([70.0], (75.0, 125.0))
        with self.assertRaises(self.bb.BackboneError):
            self.bb.fit_capture(t, y, np.full(len(t), 100.0), (75.0, 125.0))
        with self.assertRaises(self.bb.BackboneError):                     # (an opponent without an E2 row)
            self.bb.hp_world({0: (t[:5], y[:5], np.full(5, 100.0))}, foc, (75.0, 125.0))
        free = (t, np.where(t < 75, 300.0, 500.0))
        ex = {j: (t, np.where(t > 125, 100.0, 400.0)) for j in range(3)}
        bq, _ = self.bb.hq_world(free, ex, foc, (75.0, 125.0))
        self.assertAlmostEqual(bq, 0.0, places=8)

    def test_directional_test(self):
        """The H.2 test on per-world slopes: detection at a material slope with world spread."""
        rng = self.st.stream("H-P", "unit-test", "worlds", 0)
        slopes = {f"w{i:02d}": 0.12 + (rng.below(1000) / 1000 - 0.5) * 0.1 for i in range(32)}
        r = self.bb.directional_test(slopes, "H-P", self.st.DELTA_P, draws=999)
        self.assertTrue(r["available"] and r["detected"])
        self.assertTrue(r["material_point"])
        r0 = self.bb.directional_test({k: v - 0.12 for k, v in slopes.items()}, "H-P", self.st.DELTA_P, draws=999)
        self.assertFalse(r0["detected"])
        # (Codex #68 D6 P2-2: given the eligibility record the test runs only when the hypothesis is available, on
        # exactly its registered population)
        ids = sorted(slopes)
        elig = {"schema": self.st.ELIGIBILITY_SCHEMA,
                "hypotheses": {"H-P": {"available": True, "worlds": ids},
                               "H-Q": {"available": False, "reason": "pending repair", "worlds": ids}}}
        rb = self.bb.directional_test(slopes, "H-P", self.st.DELTA_P, draws=999, eligibility=elig)
        self.assertEqual((rb["detected"], rb["p"]), (r["detected"], r["p"]))
        with self.assertRaisesRegex(self.st.StatsError, "registered population"):
            self.bb.directional_test({k: slopes[k] for k in ids[1:]}, "H-P", self.st.DELTA_P, draws=999, eligibility=elig)
        with self.assertRaisesRegex(self.st.StatsError, "is unavailable"):
            self.bb.directional_test(slopes, "H-Q", self.st.DELTA_Q, draws=999, eligibility=elig)
        with self.assertRaisesRegex(self.st.StatsError, "not an eligibility record"):
            self.bb.directional_test(slopes, "H-P", self.st.DELTA_P, draws=999, eligibility={"hypotheses": {}})


if __name__ == "__main__":
    unittest.main()

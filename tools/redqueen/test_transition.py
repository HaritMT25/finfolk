#!/usr/bin/env python3
"""test_transition.py: Annex H.15's H-T known-answer checks for transition.py (22-28), the "mixed" class
(the user's decision 3), the paired bootstrap streams and the vectorized per-draw gates. numpy required
(skipped without it unless RQ_REQUIRE_NUMPY=1).

    python3 -I tools/redqueen/test_transition.py [-v]
"""
from __future__ import annotations

import json
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

B = 999
ARD = dict(beta_P=0.20, beta_Q=0.05, EU_C=0.002, EU_Q=0.0002, EF_C=0.0, EF_Q=0.0)
FSD = dict(beta_P=0.0, beta_Q=0.0, EU_C=0.05, EU_Q=0.01, EF_C=0.04, EF_Q=0.008)
MIXED = dict(beta_P=0.20, beta_Q=0.05, EU_C=0.05, EU_Q=0.01, EF_C=0.04, EF_Q=0.008)
NONE = dict(beta_P=0.0, beta_Q=0.0, EU_C=0.05, EU_Q=0.01, EF_C=0.0, EF_Q=0.0)
SD = dict(beta_P=0.004, beta_Q=0.001, EU_C=0.0002, EU_Q=0.00003, EF_C=0.002, EF_Q=0.0002)


@unittest.skipIf(np is None, "numpy is not installed")
class TestTransition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import recurrence
        import rqlib
        import stats
        import transition
        cls.tr, cls.rc, cls.st, cls.rq = transition, recurrence, stats, rqlib
        cls.z = transition.VecSplitMix64(12345).normals(B * 6).reshape(6, B)

    def comps(self, recs, sd=SD, z=None):
        """Component records and their draws: each component's draws = obs + sd * a fixed normal vector
        (one shared vector per component across epochs: a paired fixture)."""
        z = self.z if z is None else z
        obs = {e: dict(r) for e, r in zip(self.tr.EPOCHS, recs)}
        draws = {e: {k: r[k] + sd[k] * z[i] for i, k in enumerate(self.tr.KEYS)} for e, r in obs.items()}
        return obs, draws

    def test_streams_reproduce_rqlib(self):
        tr, rq = self.tr, self.rq
        for seed in (0, 7, 2 ** 63 + 5):
            v, r = tr.VecSplitMix64(seed), rq.SplitMix64(seed)
            self.assertEqual(v.next64(50).tolist(), [r.next64() for _ in range(50)])
            self.assertEqual(v.below(24, 300).tolist(), [r.below(24) for _ in range(300)])
            self.assertEqual(v.s, r.s)
        idx, xi = tr.draw_streams("x", 32, 3, 10)
        idx2, xi2 = tr.draw_streams("x", 32, 3, 10)
        self.assertTrue(np.array_equal(idx, idx2) and np.array_equal(xi, xi2))          # determinism
        r = rq.SplitMix64(self.st.stream_seed("H-T", "x", "bootstrap"))
        self.assertEqual(idx.ravel().tolist(), [r.below(32) for _ in range(320)])
        zz = tr.VecSplitMix64(1).normals(200000)
        self.assertLess(abs(zz.mean()), 0.01)
        self.assertLess(abs(zz.std() - 1), 0.01)

    def test_stable_classes(self):
        """22: stable ARD, stable FSD and stable mixed epochs: no transition candidate passes."""
        for rec in (ARD, FSD, MIXED):
            obs, draws = self.comps([rec, rec, rec])
            st = self.tr.ht_statistic(obs, draws, {e: True for e in self.tr.EPOCHS})
            self.assertEqual(st["T_T"], -math.inf, rec)

    def test_absence_requires_a_bound(self):
        """23: H-F non-significant (no gate) and E^U below material, but its upper bound above it: the
        epoch is not ARD-certified."""
        rec = dict(ARD, EU_C=0.008)
        obs, draws = self.comps([rec, FSD, NONE], sd=dict(SD, EU_C=0.01))
        cl = self.tr.classify(obs["E1"], draws["E1"], gate=False)
        self.assertGreater(cl["bounds"]["EU_C"][1], self.tr.D_C ** 2)
        self.assertNotEqual(cl["class"], "ARD")
        obs, draws = self.comps([ARD, FSD, NONE])
        self.assertEqual(self.tr.classify(obs["E1"], draws["E1"], gate=False)["class"], "ARD")

    def test_mixed_is_not_ard(self):
        """24 and the user's decision 3: an early epoch with material directional AND recurrent structure is
        "mixed" (not ARD, not FSD) and cannot be the ARD side of a transition to a later FSD epoch."""
        obs, draws = self.comps([MIXED, FSD, NONE])
        gates = {e: True for e in self.tr.EPOCHS}
        cl = self.tr.classify(obs["E1"], draws["E1"], gate=True)
        self.assertEqual((cl["class"], cl["directional"]), ("mixed", "material"))
        self.assertEqual(self.tr.classify(obs["E2"], draws["E2"], gate=True)["class"], "FSD")
        st = self.tr.ht_statistic(obs, draws, gates)
        c = next(c for c in st["candidates"] if (c["ARD"], c["FSD"]) == ("E1", "E2"))
        self.assertEqual(c["T"], -math.inf)
        self.assertLess(c["margins"]["dC2-EU_C[a]"], 0)
        # FSD dominance needs directional equivalence: material recurrence with a slope outside the band
        rec = dict(FSD, beta_P=0.15)
        obs, draws = self.comps([rec, rec, rec])
        self.assertEqual(self.tr.classify(obs["E1"], draws["E1"], gate=True)["class"], "mixed")

    def test_actual_contrast_required(self):
        """25: one required epoch contrast exactly zero, every other margin positive: -inf."""
        a = dict(ARD, beta_P=0.05)
        f = dict(FSD, beta_P=0.05)
        obs, draws = self.comps([a, f, NONE])
        c = next(c for c in self.tr.ht_statistic(obs, draws, {e: True for e in self.tr.EPOCHS})["candidates"]
                 if (c["ARD"], c["FSD"]) == ("E1", "E2"))
        self.assertEqual(c["margins"]["beta_P[a]-beta_P[f]"], 0.0)
        self.assertTrue(all(v > 0 for k, v in c["margins"].items() if k != "beta_P[a]-beta_P[f]"))
        self.assertEqual(c["T"], -math.inf)

    def test_both_directions(self):
        """26: swapping the early and late records (and their draws) reverses the winning direction and
        keeps the maximum's value."""
        gates = {e: True for e in self.tr.EPOCHS}
        obs, draws = self.comps([ARD, FSD, NONE])
        s1 = self.tr.ht_statistic(obs, draws, gates)
        self.assertEqual((s1["winner"]["ARD"], s1["winner"]["FSD"], s1["winner"]["direction"]), ("E1", "E2", "ARD->FSD"))
        obs2 = {"E1": obs["E2"], "E2": obs["E1"], "E3": obs["E3"]}
        draws2 = {"E1": draws["E2"], "E2": draws["E1"], "E3": draws["E3"]}
        s2 = self.tr.ht_statistic(obs2, draws2, gates)
        self.assertEqual((s2["winner"]["ARD"], s2["winner"]["FSD"], s2["winner"]["direction"]), ("E2", "E1", "FSD->ARD"))
        self.assertEqual(s1["T_T"], s2["T_T"])
        self.assertGreater(s1["T_T"], -math.inf)

    def test_one_complete_maximum(self):
        """27: the six candidate scores computed independently; the implementation returns their maximum;
        the hardest component sets it (deleting it would change the test, which this fixture detects)."""
        tr = self.tr
        gates = {e: True for e in tr.EPOCHS}
        hard = dict(ARD, EU_C=0.0085)                    # the recurrence exclusion is the difficult margin
        obs, draws = self.comps([hard, FSD, FSD], sd=dict(SD, EU_C=0.0005))
        st = tr.ht_statistic(obs, draws, gates)
        mine = []
        for a, f, _ in tr.candidates():
            ms = tr.margins(obs, a, f)
            if not all(v > 0 for _, v in ms):
                mine.append(-math.inf)
                continue
            md = dict(tr.margins(draws, a, f))
            ps = [(1 + int(np.sum(np.asarray(md[k]) - v >= v))) / (B + 1) for k, v in ms]
            mine.append(-math.log(max(ps)))
        self.assertEqual(st["T_T"], max(mine))
        self.assertEqual(sum(t > -math.inf for t in mine), 2)       # E1->E2 and E1->E3
        w = st["winner"]
        hardest = max(w["p"], key=w["p"].get)
        self.assertEqual(hardest, "dC2-EU_C[a]")
        without = -math.log(max(v for k, v in w["p"].items() if k != hardest))
        self.assertGreater(without, st["T_T"])

    def test_paired_epoch_resampling(self):
        """28: one world index selects all three epochs: a covariance-sensitive contrast (a world effect
        shared by the epochs) has zero bootstrap spread; independent epoch indices would not."""
        tr = self.tr
        n = 12
        u = np.linspace(-0.3, 0.4, n)
        betas = {"E1": {"P": u + 0.01, "Q": u}, "E2": {"P": u, "Q": u}, "E3": {"P": u - 0.02, "Q": u}}
        idx, _ = tr.draw_streams("paired", n, 0, 400)
        dummy = [{"obs": {"id": str(i), "scope": "E1", "periods": [{"P": 4.0, "fails": [], "supported": True,
                                                                     "s": 0.0, "r_C": 0.0, "r_Q": 0.0, "phase_C": 0.0,
                                                                     "phase_Q": 0.0, "phase_conditional": False}],
                          "phase_support": {"conditional": 0, "supported_at_fitted_phase": 0, "periods": []}},
                  "EU_obs": (0.0, 0.0), "maxC": np.zeros(400), "maxQ": np.zeros(400), "selC": np.zeros(400),
                  "selQ": np.zeros(400)} for i in range(n)]
        d = {e: tr.epoch_components(dummy, betas[e], idx)[1] for e in tr.EPOCHS}
        contrast = d["E1"]["beta_P"] - d["E2"]["beta_P"]
        self.assertLess(np.ptp(contrast), 1e-12)
        self.assertAlmostEqual(float(contrast[0]), 0.01, places=12)
        idx2, _ = tr.draw_streams("independent", n, 0, 400)
        d2 = tr.epoch_components(dummy, betas["E2"], idx2)[1]
        self.assertGreater(np.std(d["E1"]["beta_P"] - d2["beta_P"]), 0.05)

    def test_guard_and_decision(self):
        tr = self.tr
        self.assertAlmostEqual(tr.GUARD, 6.396929655, places=8)
        obs, draws = self.comps([ARD, FSD, NONE])
        st = tr.ht_statistic(obs, draws, {e: True for e in tr.EPOCHS})
        self.assertLessEqual(st["T_T"], math.log(B + 1))           # (the bootstrap's attainable maximum)
        no_gate = tr.ht_statistic(obs, draws, {"E1": True, "E2": False, "E3": True})
        self.assertEqual(no_gate["T_T"], -math.inf)                # the FSD epoch's gate is required

    def test_world_epoch_draws_match_observed(self):
        """The vectorized per-draw gates and selections reproduce the observed analysis when the reference-
        source draw is zero, and move with it otherwise; the whole pipeline runs on small epoch designs and
        reports the phase-conditional support per epoch."""
        tr, rc = self.tr, self.rc
        refs = np.array(["a", "b", "c", "d"], object)
        nw = 3
        epochs, betas, loads = {}, {}, {}
        for e in tr.EPOCHS:
            L, U = rc.SCOPES[e]
            t = np.array([max(L, 1e-6)] + [L + float(k) for k in range(1, 51)])
            ti, tj = (a.ravel() for a in np.meshgrid(t, t, indexing="ij"))
            rt, rr = np.tile(t, 4), np.repeat(refs, len(t))
            cw, cr = rc.Cov(np.full(len(ti), 1e-4)), rc.Cov(np.full(len(rt), 1e-4))
            epochs[e], betas[e] = [], {"P": {}, "Q": {}}
            for w in range(nw):
                wd = rc.WorldDesign(f"w{w}", {"C": (ti, tj, cw), "Q": (ti, tj, cw)}, {"C": (rt, rr, cr), "Q": (rt, rr, cr)},
                                    e, (8.0, 12.0, 25.0))
                P, ph = (8.0, 12.0, 8.0)[w], 0.7 * w
                amp = 1.0 if e == "E2" else 0.0
                lag = 2 * math.pi * (tj - ti) / P - ph
                y = {"within": {"C": 0.3 + amp * 0.05 * np.cos(lag), "Q": -0.1 + amp * 0.02 * np.cos(lag)},
                     "ref": {"C": 0.4 + amp * 0.05 * np.cos(2 * math.pi * rt / P - ph),
                             "Q": -0.1 + amp * 0.02 * np.cos(2 * math.pi * rt / P - ph)}}
                epochs[e].append((wd, y))
                betas[e]["P"][f"w{w}"] = 0.2 if e == "E1" else 0.0
                betas[e]["Q"][f"w{w}"] = 0.05 if e == "E1" else 0.0
                loads[f"w{w}"] = {"C": np.repeat(np.eye(4), len(t), axis=0)[np.argsort(np.argsort(rr))] * 0.0,
                            "Q": None}
        # zero loadings: every draw equals the observed analysis
        xi = np.zeros((7, 2))
        for wd, y in epochs["E2"]:
            we = tr.world_epoch(wd, y, None, xi)
            obsP, contrib, g = rc.select(we["obs"])
            r = next(r for r in we["obs"]["periods"] if r["P"] == obsP)
            self.assertTrue(np.allclose(we["selC"], g * r["r_C"] ** 2))
            self.assertTrue(np.allclose(we["selQ"], g * r["r_Q"] ** 2))
        # a nonzero reference-source draw moves the phases, hence the gates of some draws
        wd, y = epochs["E2"][0]
        Lc = np.zeros((len(y["ref"]["C"]), 2))
        Lc[:, 0] = np.sin(np.arange(len(Lc)))
        Lc[:, 1] = 0.05 * np.cos(2 * math.pi * wd.ref["C"].t / 8.0 + 1.3)
        xi = tr.VecSplitMix64(3).normals(400).reshape(200, 2)
        we = tr.world_epoch(wd, y, {"C": Lc}, xi)
        self.assertGreater(np.ptp(we["selC"]), 0)
        out = tr.ht(epochs, betas, {e: True for e in tr.EPOCHS}, loads=None, k=0, analysis="t", draws=199)
        self.assertTrue(out["available"])
        self.assertEqual(set(out["phase_support"]), set(tr.EPOCHS))
        self.assertGreater(out["components"]["E2"]["EF_C"], 0)
        self.assertEqual(out["components"]["E1"]["EF_C"], 0.0)
        self.assertIn(out["classes"]["E1"]["class"], ("ARD", "unresolved"))
        self.assertEqual(out["worlds"], ["w0", "w1", "w2"])
        cov = out["coverage"]["E2"]                                  # (#68 round 4 (D): E^U support coverage)
        self.assertEqual(cov["worlds"], 3)
        self.assertEqual(cov["excluded_periods"], [25.0])
        self.assertEqual(sum(v["cells"] for v in cov["bands"].values()), 3 * 3)
        nc = tr.ht(epochs, betas, {e: True for e in tr.EPOCHS}, loads=None, k=0, analysis="t", draws=19, c_T=None)
        self.assertEqual((nc["available"], nc["reject"], nc["c_T"]), (False, False, None))   # (no calibration)
        # #68 review 11: identities, not positions. One epoch's worlds reversed (their slopes keyed by id):
        # the identical result; a different world set, a duplicate id or position-keyed slopes are refused
        rev = dict(epochs, E2=list(reversed(epochs["E2"])))
        out2 = tr.ht(rev, betas, {e: True for e in tr.EPOCHS}, loads=None, k=0, analysis="t", draws=199)
        self.assertEqual(json.dumps(out2["components"], sort_keys=True, default=float),
                         json.dumps(out["components"], sort_keys=True, default=float))
        self.assertEqual(out2["T_T"], out["T_T"])
        bad = dict(epochs, E3=epochs["E3"][:2] + [epochs["E3"][0]])
        with self.assertRaises(tr.TransitionError):
            tr.ht(bad, betas, {e: True for e in tr.EPOCHS}, analysis="t", draws=19)
        with self.assertRaises(tr.TransitionError):
            tr.ht(epochs, dict(betas, E1={"P": [0.2] * 3, "Q": [0.05] * 3}), {e: True for e in tr.EPOCHS},
                  analysis="t", draws=19)
        with self.assertRaises(tr.TransitionError):
            tr.ht(epochs, betas, {e: True for e in tr.EPOCHS}, loads={"zz": {}}, analysis="t", draws=19)
        nanb = {e: {h: dict(betas[e][h]) for h in "PQ"} for e in tr.EPOCHS}
        nanb["E2"]["P"]["w1"] = math.nan
        u = tr.ht(epochs, nanb, {e: True for e in tr.EPOCHS}, analysis="t", draws=19)
        self.assertEqual((u["available"], u["reject"]), (False, False))

    def test_nan_draws_are_failures(self):
        """#68 review 3: a NaN draw is a numerical failure (never a non-exceedance); +inf is a value."""
        tr = self.tr
        with self.assertRaises(tr.TransitionError):
            tr.tail_p(0.1, [0.2, math.nan, 0.3])
        with self.assertRaises(tr.TransitionError):
            tr.tail_p(math.nan, [0.2, 0.3])
        self.assertEqual(tr.tail_p(0.1, [0.2, math.inf, 0.0]), 3 / 4)
        obs, draws = self.comps([ARD, FSD, FSD])
        draws["E2"]["EF_C"] = np.where(np.arange(B) == 7, math.nan, draws["E2"]["EF_C"])
        with self.assertRaises(tr.TransitionError):
            tr.ht_statistic(obs, draws, {e: True for e in tr.EPOCHS})
        self.assertEqual(tr.classify(obs["E2"], draws["E2"], True)["class"], "unresolved")

    def test_failed_perturbations_are_failures(self):
        """#68 round 2 (P1-3 residual): a nonfinite loading makes the perturbed coefficients NaN; that is a
        failure BEFORE any gate or zero substitution (never zero energy), and the analysis is unavailable."""
        tr, rc = self.tr, self.rc
        refs = np.array(["a", "b", "c", "d"], object)
        L, U = rc.SCOPES["E2"]
        t = np.array([L] + [L + float(k) for k in range(1, 51)])
        ti, tj = (a.ravel() for a in np.meshgrid(t, t, indexing="ij"))
        rt, rr = np.tile(t, 4), np.repeat(refs, len(t))
        cw, cr = rc.Cov(np.full(len(ti), 1e-4)), rc.Cov(np.full(len(rt), 1e-4))
        wd = rc.WorldDesign("w0", {"C": (ti, tj, cw), "Q": (ti, tj, cw)}, {"C": (rt, rr, cr), "Q": (rt, rr, cr)},
                            "E2", (8.0, 12.0))
        lag = 2 * math.pi * (tj - ti) / 8.0
        y = {"within": {"C": 0.3 + 0.05 * np.cos(lag), "Q": -0.1 + 0.02 * np.cos(lag)},
             "ref": {"C": 0.4 + 0.05 * np.cos(2 * math.pi * rt / 8.0), "Q": -0.1 + 0.02 * np.cos(2 * math.pi * rt / 8.0)}}
        Lc = np.zeros((len(rt), 2))
        Lc[5, 0] = math.nan
        xi = tr.VecSplitMix64(3).normals(40).reshape(20, 2)
        with self.assertRaises(tr.TransitionError) as cm:
            tr.world_epoch(wd, y, {"C": Lc}, xi)
        self.assertIn("w0", str(cm.exception))
        Lc[5, 0] = 1e308                                          # (finite, but the perturbed projection overflows)
        Lc[6, 0] = -1e308
        with self.assertRaises(tr.TransitionError):
            tr.world_epoch(wd, y, {"C": Lc * 1e10}, xi)

    def test_window_arithmetic_is_checked(self):
        """#68 round 3 P2: FINITE residuals whose cumulative sums overflow, window means / contrasts that
        overflow, ranges and squared components that overflow, and capture energies that overflow are
        numerical failures before any comparison; a capture denominator <= 0 stays the registered +inf."""
        tr = self.tr
        with self.assertRaises(tr.TransitionError):
            tr.cumulative(np.full((4, 3), 1e308), "w")                 # (finite inputs, an overflowing cumsum)
        cs = np.array([[0.0], [-1e308], [1e308], [0.0], [1.0], [2.0], [3.0]])
        lo = np.array([[0, 1, 2, 3, 4]])
        hi = np.array([[1, 2, 3, 4, 5]])
        with self.assertRaises(tr.TransitionError):
            tr.windows(cs, lo, hi, np.array([0]), np.array([1.0]), "w")  # (inf - (-inf) -> a nonfinite window)
        ok = np.cumsum(np.vstack([np.zeros((1, 1)), np.ones((6, 1))]), axis=0)
        rev, ret = tr.windows(ok, lo, hi, np.array([0]), np.array([1.0]), "w")
        self.assertEqual(rev.shape, (1,))
        with self.assertRaises(tr.TransitionError):
            tr.energy(np.array([[1e308], [-1e308]]), np.array([1.0]), "Q", "w")   # (the range overflows)
        with self.assertRaises(tr.TransitionError):
            tr.energy(np.array([[1e200], [1e200]]), np.array([1.0]), "Q", "w")   # (the squares overflow)
        with self.assertRaises(tr.TransitionError):
            tr.energy(np.array([[0.1], [-0.1]]), np.array([1e-200]), "C", "w")   # (the ratio overflows)
        r2, _ = tr.energy(np.array([[0.1, 0.1], [-0.1, -0.1]]), np.array([0.0, 2.0]), "C", "w")
        self.assertEqual(r2[0], math.inf)                                         # (the registered +inf)
        self.assertAlmostEqual(r2[1], 0.01 / 4)
        # #68 round 4 P2-2 (Codex's counterexample): the denominator's square overflows, the relative energy
        # is 0.16, never 0
        r2, _ = tr.energy(np.array([[8e153], [-8e153]]), np.array([2e154]), "C", "w")
        self.assertAlmostEqual(r2[0], 0.16, delta=1e-15)

    def test_mixed_needs_affirmative_evidence(self):
        """#68 review 8: material recurrence with directional bounds spanning the band is UNRESOLVED, not
        mixed; bounds without a passed gate are unresolved; mixed needs both affirmatively."""
        tr = self.tr
        rec = dict(EF_C=0.05, EF_Q=0.01, EU_C=0.05, EU_Q=0.01)
        span = dict(rec, beta_P=0.0, beta_Q=0.0)                 # bounds wide: spanning the band
        mat = dict(rec, beta_P=0.6, beta_Q=0.0)                  # beta_P far above delta_P
        wide = dict(SD, beta_P=0.08, beta_Q=0.03)
        o, d = self.comps([span, span, span], sd=wide)
        c = tr.classify(o["E1"], d["E1"], True)
        self.assertEqual((c["class"], c["directional"]), ("unresolved", "unresolved"))
        o, d = self.comps([mat, mat, mat], sd=dict(SD, beta_P=0.02))
        self.assertEqual(tr.classify(o["E1"], d["E1"], True)["class"], "mixed")
        c = tr.classify(o["E1"], d["E1"], False)                 # (the epoch gate failed)
        self.assertEqual((c["class"], c["recurrent"], c["recurrence_bounds"]), ("unresolved", False, True))


if __name__ == "__main__":
    unittest.main()

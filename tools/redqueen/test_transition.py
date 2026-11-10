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

    def test_ht_binds_the_population(self):
        """Codex #68 D6 P2-2: given the eligibility record H-T runs only when available, on exactly the common Q200
        in every epoch; otherwise StatsError, before any analysis."""
        from types import SimpleNamespace
        tr, st = self.tr, self.st
        ids = ["a", "b", "c"]
        def inputs(ws):
            return ({e: [(SimpleNamespace(id=w, periods=()), None) for w in ws] for e in tr.EPOCHS},
                    {e: {"P": {w: 0.0 for w in ws}, "Q": {w: 0.0 for w in ws}} for e in tr.EPOCHS},
                    {e: True for e in tr.EPOCHS})
        elig = {"schema": st.ELIGIBILITY_SCHEMA, "hypotheses": {"H-T": {"available": True, "worlds": ids}}}
        with self.assertRaisesRegex(st.StatsError, "registered population"):
            tr.ht(*inputs(ids[1:]), c_T=None, report=False, eligibility=elig)
        off = {"schema": st.ELIGIBILITY_SCHEMA,
               "hypotheses": {"H-T": {"available": False, "reason": "pending repair", "worlds": ids}}}
        with self.assertRaisesRegex(st.StatsError, "is unavailable"):
            tr.ht(*inputs(ids), c_T=None, report=False, eligibility=off)
        r = tr.ht(*inputs(ids), c_T=None, report=False, eligibility=elig)   # (bound: the analysis proceeds,
        self.assertEqual((r["failure"], r["worlds"]), ("domain", ids))          # here to its domain check)

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
        epochs, betas, loads, geo = {}, {}, {}, {}
        for e in tr.EPOCHS:
            L, U = rc.SCOPES[e]
            t = np.array([max(L, 1e-6)] + [L + float(k) for k in range(1, 51)])
            ti, tj = (a.ravel() for a in np.meshgrid(t, t, indexing="ij"))
            rt, rr = np.tile(t, 4), np.repeat(refs, len(t))
            cw, cr = rc.Cov(np.full(len(ti), 1e-4)), rc.Cov(np.full(len(rt), 1e-4))
            geo[e] = (ti, tj, rt, rr, cw, cr)
            epochs[e], betas[e] = [], {"P": {}, "Q": {}}
            for w in range(nw):
                wd = rc.WorldDesign(f"w{w}", {"C": (ti, tj, cw), "Q": (ti, tj, cw)}, {"C": (rt, rr, cr), "Q": (rt, rr, cr)},
                                    e)                                # (#68 round 5: the registered grid)
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
        self.assertLess(out["components"]["E1"]["EF_C"], 1e-20)         # (no recurrence in E1)
        self.assertIn(out["classes"]["E1"]["class"], ("ARD", "unresolved"))
        self.assertEqual(out["worlds"], ["w0", "w1", "w2"])
        cov = out["coverage"]["E2"]                       # (D3: per world x readout x band, the actual grid)
        self.assertEqual(sorted(cov["worlds"]), ["w0", "w1", "w2"])
        self.assertEqual((cov["grid"], cov["registered"], cov["excluded_periods"]),
                         (list(rc.EPOCH_PERIODS), list(rc.EPOCH_PERIODS), [25.0]))
        self.assertEqual(sum(v[1] for v in cov["totals"]["joint"].values()), 3 * len(rc.EPOCH_PERIODS))
        self.assertEqual(set(cov["worlds"]["w0"]), {"C", "Q", "joint"})
        self.assertEqual(sorted(cov["worlds"]["w0"]["C"]), ["15-20", "4-8", "9-14"])
        ti2, tj2, rt2, rr2, cw2, cr2 = geo["E2"]                    # (one design on a supplied list: refused)
        bad_wd = rc.WorldDesign("w1", {"C": (ti2, tj2, cw2), "Q": (ti2, tj2, cw2)},
                                {"C": (rt2, rr2, cr2), "Q": (rt2, rr2, cr2)}, "E2", (8.0, 12.0, 25.0))
        off = {e: [(bad_wd if e == "E2" and wd.id == "w1" else wd, y_) for wd, y_ in epochs[e]] for e in tr.EPOCHS}
        dom = tr.ht(off, betas, {e: True for e in tr.EPOCHS}, loads=None, k=0, analysis="t", draws=19)
        self.assertEqual((dom["available"], dom["reject"], dom["failure"]), (False, False, "domain"))
        # (#68 round 6 P3: a static failure of Q alone leaves C's coverage intact; joint support falls)
        wd0 = epochs["E2"][0][0]
        wd0.within["Q"].fails[8.0] = ["test-Q-only"]
        one = tr.ht(epochs, betas, {e: True for e in tr.EPOCHS}, loads=None, k=0, analysis="t", draws=19)
        cw0 = one["coverage"]["E2"]["worlds"]["w0"]
        self.assertEqual(cw0["C"]["4-8"], cov["worlds"]["w0"]["C"]["4-8"])
        self.assertEqual(cw0["Q"]["4-8"][0], cov["worlds"]["w0"]["Q"]["4-8"][0] - 1)
        self.assertEqual(cw0["joint"]["4-8"][0], cov["worlds"]["w0"]["joint"]["4-8"][0] - 1)
        del wd0.within["Q"].fails[8.0][:]
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

    def test_draw_loop_lever_matches_the_per_period_path(self):
        """#68 draw-loop lever 1 against the pre-lever per-period path (the oracle below, verbatim): on random
        epoch panels with a fixed reference-source draw, the per-draw gates, selections and window decisions
        agree EXACTLY and the energies to <= 1e-12 relative, including a capture denominator near 0 (some draws
        <= 0: the registered +inf) and a degenerate (collinear, duplicated) avgQ."""
        tr, rc = self.tr, self.rc
        rng = np.random.default_rng(11)
        refs = np.array(["a", "b", "c", "d"], object)
        for trial in range(4):
            L, U = rc.SCOPES["E2"]
            t = np.array([L] + [L + float(k) for k in range(1, 51)])
            ti, tj = (a_.ravel() for a_ in np.meshgrid(t, t, indexing="ij"))
            rt, rr = np.tile(t, 4), np.repeat(refs, len(t))
            cw, cr = rc.Cov(np.full(len(ti), 1e-4)), rc.Cov(1e-4 * (1 + rng.random(len(rt))))
            wd = rc.WorldDesign(f"w{trial}", {"C": (ti, tj, cw), "Q": (ti, tj, cw)}, {"C": (rt, rr, cr), "Q": (rt, rr, cr)},
                                "E2", (6.0, 8.0, 12.0, 17.0))
            P0, ph = (8.0, 12.0, 6.0, 17.0)[trial], rng.uniform(0, 6)
            lag = 2 * math.pi * (tj - ti) / P0 - ph
            dc = 0.4 if trial != 2 else 0.002                                 # (trial 2: a denominator near 0)
            y = {"within": {"C": 0.3 + 0.05 * np.cos(lag), "Q": -0.1 + 0.02 * np.cos(lag)},
                 "ref": {"C": dc + 0.05 * np.cos(2 * math.pi * rt / P0 - ph) + 0.01 * rng.standard_normal(len(rt)),
                         "Q": -0.1 + 0.02 * np.cos(2 * math.pi * rt / P0 - ph) + 0.005 * rng.standard_normal(len(rt))}}
            if trial == 3:                                                     # (a degenerate, collinear avgQ)
                for hm in wd.ref["C"].harm.values():
                    if hm.avgQ is not None and len(hm.avgQ):
                        hm.avgQ = np.outer(np.repeat(np.linspace(-1, 1, (len(hm.avgQ) + 1) // 2), 2)[:len(hm.avgQ)],
                                           [0.3, -0.7])
            Lc = np.zeros((len(rt), 2))
            Lc[:, 0] = 0.01 * np.sin(np.arange(len(rt)))
            Lc[:, 1] = 0.003 * np.cos(2 * math.pi * rt / 8.0 + 1.3) if trial != 2 else 0.004   # (trial 2: den crosses 0)
            xi = tr.VecSplitMix64(5 + trial).normals(2 * 999).reshape(999, 2)
            new = tr.world_epoch(wd, y, {"C": Lc, "Q": 0.5 * Lc}, xi, _expose=True)
            old = _world_epoch_oracle(tr, rc, wd, y, {"C": Lc, "Q": 0.5 * Lc}, xi)
            for k in ("selC", "selQ", "maxC", "maxQ"):
                fin = np.isfinite(old[k])
                self.assertTrue(np.array_equal(fin, np.isfinite(new[k])), k)
                self.assertTrue(np.array_equal(old[k] > 0, new[k] > 0), k)       # (the same selections / gates)
                self.assertLessEqual(float(np.max(np.abs(old[k][fin] - new[k][fin]) / np.maximum(np.abs(old[k][fin]), 1e-300),
                                                  initial=0.0)), 1e-10, k)
            for h in "CQ":
                self.assertTrue(np.array_equal(old["_G"][h], new["_G"][h]), h)       # (0 gate differences)
                fo, fn = np.isfinite(old["_r2"][h]), np.isfinite(new["_r2"][h])
                self.assertTrue(np.array_equal(fo, fn) and np.array_equal(np.isnan(old["_r2"][h]), np.isnan(new["_r2"][h])))
                # (the error relative to the energy's rounding scale ||avgQ||^2 ||x||^2 / m, which bounds the energy:
                # both routes are backward stable; on near-cancelling draws plain relative differences reach ~2e-12)
                d = np.abs(old["_r2"][h][fo] - new["_r2"][h][fo]) / np.maximum(old["_scale"][h][fo], 1e-300)
                self.assertLessEqual(float(np.max(d, initial=0.0)), 1e-12, h)
                rel = np.abs(old["_r2"][h][fo] - new["_r2"][h][fo]) / np.maximum(np.abs(old["_r2"][h][fo]), 1e-300)
                self.assertLessEqual(float(np.max(rel, initial=0.0)), 1e-10, h)
            if trial == 2:
                self.assertTrue(np.isinf(old["maxC"]).any() or np.isinf(old["_r2"]["C"]).any())
        for Q in (rng.standard_normal((51, 2)), np.outer(np.linspace(-1, 1, 51), [0.3, -0.7]),
                  np.repeat(rng.standard_normal((5, 2)), 10, axis=0)):            # (generic, collinear, duplicated)
            bb = rng.standard_normal((2, 999)) * np.array([[1.0], [1e3]])
            want = np.ptp(Q @ bb, axis=0)
            got = tr.range_hull(bb, tr.hull_vertices(Q), "w")
            sc = np.linalg.norm(Q, 2) * np.linalg.norm(bb, axis=0)
            self.assertLessEqual(float(np.max(np.abs(got - want) / sc)), 1e-12)
        V = tr.hull_vertices(np.array([[0, 0], [1, 1], [2, 2], [2, 2], [1, 0], [0, 1], [0.5, 0.5]]))
        self.assertEqual(sorted(map(tuple, V.tolist())), [(0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (2.0, 2.0)])
        self.assertEqual(tr.hull_vertices(np.array([[1.0, 2.0], [1.0, 2.0]])).tolist(), [[1.0, 2.0]])

    def test_redesign_path_is_exact_with_the_same_design(self):
        """D4 spec 5: transition.ht's per-draw redesign path, handed the observed design itself for every draw,
        reproduces the fixed-design path exactly (the machinery adds nothing)."""
        tr, rc = self.tr, self.rc
        refs = np.array(["a", "b", "c", "d"], object)
        epochs, betas, loads = {}, {}, {}
        for e in tr.EPOCHS:
            L, U = rc.SCOPES[e]
            tt = np.array([max(L, 1e-6)] + [L + float(k) for k in range(1, 51)])
            ti, tj = (a_.ravel() for a_ in np.meshgrid(tt, tt, indexing="ij"))
            rt, rr = np.tile(tt, 4), np.repeat(refs, len(tt))
            cw, cr = rc.Cov(np.full(len(ti), 1e-4)), rc.Cov(np.full(len(rt), 1e-4))
            epochs[e], betas[e] = [], {"P": {}, "Q": {}}
            for w in range(2):
                wd = rc.WorldDesign(f"w{w}", {"C": (ti, tj, cw), "Q": (ti, tj, cw)}, {"C": (rt, rr, cr), "Q": (rt, rr, cr)}, e)
                lag = 2 * math.pi * (tj - ti) / 8.0 - 0.7 * w
                y = {"within": {"C": 0.3 + 0.05 * np.cos(lag), "Q": -0.1 + 0.02 * np.cos(lag)},
                     "ref": {"C": 0.4 + 0.05 * np.cos(2 * math.pi * rt / 8.0 - 0.7 * w),
                             "Q": -0.1 + 0.02 * np.cos(2 * math.pi * rt / 8.0 - 0.7 * w)}}
                epochs[e].append((wd, y))
                betas[e]["P"][f"w{w}"], betas[e]["Q"][f"w{w}"] = 0.0, 0.0
                loads[f"w{w}"] = {"C": 0.003 * np.ones((len(rt), 2)), "Q": 0.001 * np.ones((len(rt), 2))}
        by = {(e, wd.id): wd for e in tr.EPOCHS for wd, _ in epochs[e]}
        a = tr.ht(epochs, betas, {e: True for e in tr.EPOCHS}, loads=loads, k=2, analysis="t", draws=7)
        b = tr.ht(epochs, betas, {e: True for e in tr.EPOCHS}, loads=loads, k=2, analysis="t", draws=7,
                  redesign=lambda e, w, xb: by[(e, w)])
        self.assertEqual(json.dumps(a["components"], sort_keys=True, default=float),
                         json.dumps(b["components"], sort_keys=True, default=float))
        self.assertEqual(a["T_T"], b["T_T"])

    def _eligible_fixture(self):
        """Three worlds; E1 directional with no recurrence, E2 recurrent (period 8 / 12 / 8), E3 flat: the
        candidate (E1 ARD, E2 FSD) is eligible; nonzero reference-source loadings move the draws."""
        tr, rc = self.tr, self.rc
        refs = np.array(["a", "b", "c", "d"], object)
        epochs, betas, loads = {}, {"E1": {"P": {}, "Q": {}}, "E2": {"P": {}, "Q": {}}, "E3": {"P": {}, "Q": {}}}, {}
        geo = {}
        for e in tr.EPOCHS:
            L, U = rc.SCOPES[e]
            t = np.array([max(L, 1e-6)] + [L + float(k) for k in range(1, 51)])
            ti, tj = (a.ravel() for a in np.meshgrid(t, t, indexing="ij"))
            rt, rr = np.tile(t, 4), np.repeat(refs, len(t))
            geo[e] = (ti, tj, rt, rr)
            epochs[e] = []
            for w in range(3):
                P, ph = (8.0, 12.0, 8.0)[w], 0.7 * w
                amp = 1.0 if e == "E2" else 0.0
                lag = 2 * math.pi * (tj - ti) / P - ph
                y = {"within": {"C": 0.3 + amp * 0.08 * np.cos(lag), "Q": -0.1 + amp * 0.08 * np.cos(lag)},
                     "ref": {"C": 0.4 + amp * 0.08 * np.cos(2 * math.pi * rt / P - ph),
                             "Q": -0.1 + amp * 0.08 * np.cos(2 * math.pi * rt / P - ph)}}
                epochs[e].append((self._wd(f"w{w}", geo[e], e, 1.0), y))
                betas[e]["P"][f"w{w}"] = 0.2 if e == "E1" else 0.0
                betas[e]["Q"][f"w{w}"] = 0.05 if e == "E1" else 0.0
                Lc = np.zeros((len(rt), 2))
                Lc[:, 0] = 0.004 * np.sin(np.arange(len(rt)))
                Lc[:, 1] = 0.004 * np.cos(2 * math.pi * rt / P + 1.3)
                loads[f"w{w}"] = {"C": Lc, "Q": 0.3 * Lc}
        return epochs, betas, loads, geo

    def _wd(self, wid, g, e, scale):
        rc = self.rc
        ti, tj, rt, rr = g
        cw, cr = rc.Cov(np.full(len(ti), 1e-4 * scale)), rc.Cov(np.full(len(rt), 1e-4 * scale))
        return rc.WorldDesign(wid, {"C": (ti, tj, cw), "Q": (ti, tj, cw)}, {"C": (rt, rr, cr), "Q": (rt, rr, cr)}, e)

    def test_redesign_draw_oracle_and_observed_support(self):
        """Codex r8 P2-2 + P3: the per-draw-V path on a fixture with an ELIGIBLE candidate. (1) A numerical
        draw-level oracle: each draw's E^U maxima equal the plain observed analysis of that draw's perturbed
        reference responses under that draw's own design. (2) Support-sensitive draws (the draw's design marks
        a period unsupported) keep the OBSERVED support decision: the draws stay finite where the fixed-design
        observed analysis is supported."""
        tr, rc = self.tr, self.rc
        epochs, betas, loads, geo = self._eligible_fixture()
        gates = {e: True for e in tr.EPOCHS}
        base = tr.ht(epochs, betas, gates, loads=loads, k=2, analysis="t", draws=9)
        self.assertTrue(base["available"])
        self.assertGreater(base["T_T"], -math.inf)                    # (an eligible candidate)
        idx, xi = tr.draw_streams("t", 3, 2, 9)

        def scale_of(xb):
            return 1.0 + 0.5 * math.tanh(float(xb[0]))

        def redesign(e, w, xb):
            return self._wd(w, geo[e], e, scale_of(xb))
        seen = []
        real = tr.world_epoch

        def spy(wd, y, ld, x, _expose=False, support=None):
            out = real(wd, y, ld, x, _expose, support)
            if support is not None:
                seen.append((wd, y, ld, x, out))
            return out
        tr.world_epoch = spy
        try:
            got = tr.ht(epochs, betas, gates, loads=loads, k=2, analysis="t", draws=9, redesign=redesign)
        finally:
            tr.world_epoch = real
        self.assertTrue(got["available"])
        self.assertEqual(len(seen), 3 * 3 * 9)
        compared = 0
        for wd, y, ld, x, out in seen[::5]:
            yb = {"within": y["within"], "ref": {h: np.asarray(y["ref"][h], float) + np.asarray(ld[h]) @ x[0]
                                                 for h in "CQ"}}
            o = rc.analyze_world(wd, yb)
            if out["support"]["unsup"]:
                continue
            self.assertAlmostEqual(float(out["maxC"][0]), max(r["r_C"] ** 2 for r in o["periods"]), delta=1e-9)
            self.assertAlmostEqual(float(out["maxQ"][0]), max(r["r_Q"] ** 2 for r in o["periods"]), delta=1e-9)
            compared += 1
        self.assertGreaterEqual(compared, 10)
        # (2) support-sensitive draws: every draw's design marks period 8 unsupported for C
        def flagged(e, w, xb):
            wd = self._wd(w, geo[e], e, scale_of(xb))
            wd.within["C"].fails[8.0] = ["test-draw-only"]
            return wd
        e2 = [we_ for we_ in (real(wd, y, loads[wd.id], xi) for wd, y in epochs["E2"])]
        self.assertTrue(all(not w_["support"]["unsup"] for w_ in e2))          # (observed: all supported)
        alone = real(flagged("E2", "w0", xi[0]), epochs["E2"][0][1], loads["w0"], xi[:1])
        self.assertTrue(alone["support"]["unsup"])                              # (the draw's own decision: +inf)
        self.assertEqual(float(alone["maxC"][0]), math.inf)
        kept = real(flagged("E2", "w0", xi[0]), epochs["E2"][0][1], loads["w0"], xi[:1], support=e2[0]["support"])
        self.assertTrue(math.isfinite(float(kept["maxC"][0])))                  # (the observed decision kept)
        flg = tr.ht(epochs, betas, gates, loads=loads, k=2, analysis="t", draws=9, redesign=flagged)
        self.assertTrue(flg["available"])
        with self.assertRaises(tr.TransitionError):
            real(epochs["E2"][0][0], epochs["E2"][0][1], loads["w0"], xi[:1],
                 support=dict(e2[0]["support"], periods=[4.0]))

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


def _world_epoch_oracle(tr, rc, wd, y, loads, xi, lever=False):
    """The pre-lever world_epoch (transition.py before #68 draw-loop lever 1), verbatim but for exposing the
    per-period gates and energies; lever=True swaps in the lever's energy and range only."""
    obs = rc.analyze_world(wd, y)
    B = xi.shape[0]
    P_all = [r["P"] for r in obs["periods"]]
    static = [set(r["fails"]) <= {"6-windows", "capture-denominator"} for r in obs["periods"]]
    G = {h: np.zeros((len(P_all), B), bool) for h in "CQ"}
    r2 = {h: np.full((len(P_all), B), np.nan) for h in "CQ"}
    scale = {h: np.full((len(P_all), B), np.nan) for h in "CQ"}
    for h in "CQ":
        rd = wd.ref[h]
        if not hasattr(rd, "proj") or not any(static):
            continue
        yh = np.asarray(y["ref"][h], float)[rd.mask]
        Lh = loads.get(h) if loads else None
        Lm = np.asarray(Lh, float)[rd.mask] if Lh is not None else None
        where = f"world {wd.id}"

        def lin(op):
            base = op @ yh
            if Lm is None:
                return np.repeat(np.asarray(base, float)[..., None], B, axis=-1)
            return np.asarray(base, float)[..., None] + np.asarray(op @ Lm) @ xi.T
        rho, den = lin(rd.rbar), lin(rd.mean_op)
        cs = tr.cumulative(rho, where)
        for i, P in enumerate(P_all):
            if not static[i]:
                continue
            hm = rd.harm[P]
            b = hm.Sqinv @ lin(hm.WQ.T)
            a = hm.Rinv @ b
            A = np.hypot(a[0], a[1])
            phi = np.arctan2(a[1], a[0])
            if lever:
                r2[h][i] = tr.energy_form(b, np.linalg.qr(hm.avgQ, mode="r"), len(hm.avgQ), den, h, where)
                Rf = tr.range_hull(b, tr.hull_vertices(hm.avgQ), where)
            else:
                r2[h][i], Rf = tr.energy(hm.avgQ @ b, den, h, where)
            x = b / np.where(den > 0, den, 1.0)[None, :] if h == "C" else b
            scale[h][i] = np.linalg.norm(hm.avgQ, 2) ** 2 * np.sum(x * x, axis=0) / max(len(hm.avgQ), 1)
            lo, hi, kk, ok = rd.tables[P].lookup(phi)
            rev, ret = tr.windows(cs, lo, hi, kk, Rf, where)
            g = ok & (A > 0) & rev & ret
            if h == "C":
                g &= den > 0
            G[h][i] = g
    JC = np.array([r.get("J_C", 0.0) for r in obs["periods"]])
    JQ = np.array([r.get("J_Q", 0.0) for r in obs["periods"]])
    s = (G["C"] & G["Q"]) * np.minimum(JC, JQ)[:, None]
    best = s.max(axis=0) if len(P_all) else np.zeros(B)
    sel = s.argmax(axis=0) if len(P_all) else np.zeros(B, int)
    g = best > 0
    cols = np.arange(B)
    out = {"selC": np.where(g, r2["C"][sel, cols], 0.0), "selQ": np.where(g, r2["Q"][sel, cols], 0.0), "_G": G,
           "_r2": r2, "_scale": scale}
    EU, unsup = tr.eu_observed(obs)
    if obs["periods"] and not unsup:
        out["maxC"], out["maxQ"] = np.max(r2["C"], axis=0), np.max(r2["Q"], axis=0)
    else:
        out["maxC"] = out["maxQ"] = np.full(B, np.inf)
    return out


if __name__ == "__main__":
    unittest.main()

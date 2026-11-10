#!/usr/bin/env python3
"""test_recurrence.py: Annex H.14's H-F known-answer checks for recurrence.py (and H.13 1), with the
phase-conditional support rule (rule 6 at the fitted phase). numpy required (skipped without it unless
RQ_REQUIRE_NUMPY=1).

    python3 -I tools/redqueen/test_recurrence.py [-v]
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

T = [1e-6] + [float(k) for k in range(1, 41)]          # actual times (M) of a dense synthetic scope
SC = (0.0, 40.0)
PER = tuple(float(p) for p in range(4, 17))
REFS = ("r1", "r2", "r3", "r4")


def poly_within(ti, tj, c):
    """A nuisance inside the 6x6 cubic tensor-spline space (products of cubics)."""
    x, y = ti / 40.0, tj / 40.0
    return c[0] + c[1] * x + c[2] * y ** 2 + c[3] * x * y + c[4] * x ** 3 * y ** 2


def poly_ref(t, c):
    x = t / 40.0
    return c[0] + c[1] * x - c[2] * x ** 3


@unittest.skipIf(np is None, "numpy is not installed")
class TestRecurrence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import recurrence
        cls.rc = recurrence
        t = np.array(T)
        ti, tj = np.meshgrid(t, t, indexing="ij")
        cls.ti, cls.tj = ti.ravel(), tj.ravel()
        cls.rt = np.tile(t, 4)
        cls.rr = np.repeat(np.array(REFS, object), len(t))
        cw = recurrence.Cov(np.full(len(cls.ti), 1e-4))
        cr = recurrence.Cov(np.full(len(cls.rt), 1e-4))
        cls.wd = recurrence.WorldDesign("w", {"C": (cls.ti, cls.tj, cw), "Q": (cls.ti, cls.tj, cw)},
                                        {"C": (cls.rt, cls.rr, cr), "Q": (cls.rt, cls.rr, cr)}, SC, PER)

    def data(self, P=None, phC=0.0, phQ=0.0, aC=0.0, aQ=0.0, rC=0.0, rQ=0.0, k=0):
        """Noiseless responses: polynomial nuisance (+ reference intercepts) and optional harmonics: on
        the lag within the world, on the focal time on the reference panels."""
        ti, tj, rt, rr = self.ti, self.tj, self.rt, self.rr
        alpha = {"r1": 0.03, "r2": -0.01, "r3": 0.02, "r4": -0.04}
        ra = np.array([alpha[r] for r in rr])

        def hw(a, ph):
            return a * np.cos(2 * math.pi * (tj - ti) / P - ph) if P else 0.0

        def hr(a, ph):
            return a * np.cos(2 * math.pi * rt / P - ph) if P else 0.0
        return {"within": {"C": poly_within(ti, tj, [0.35 + 0.01 * k, 0.05, -0.04, 0.03, 0.02]) + hw(aC, phC),
                           "Q": poly_within(ti, tj, [-0.12, 0.02, 0.01, -0.02, 0.01]) + hw(aQ, phQ)},
                "ref": {"C": poly_ref(rt, [0.40 + 0.01 * k, 0.05, 0.03]) + ra + hr(rC, phC),
                        "Q": poly_ref(rt, [-0.10, 0.02, 0.01]) + ra / 4 + hr(rQ, phQ)}}

    # ------------------------------------------------------------ H.13 1, H.14 11-13
    def test_f1_clock_and_span_tolerance(self):
        rc = self.rc
        self.assertTrue(rc.two_cycles(50.0 - 1e-6, 25.0))            # F1..50M: two 25M cycles, by one step
        self.assertFalse(rc.two_cycles(50.0 - 2e-6, 25.0))
        self.assertTrue(rc.series_ok([1e-6] + list(range(5, 51, 5)), 25.0))

    def test_pure_nuisance(self):
        """11: Y = X gamma: M_X Y = 0 and J = 0 at every supported period."""
        res = self.rc.analyze_world(self.wd, self.data())
        for r in res["periods"]:
            if "J_C" in r:
                self.assertLess(abs(r["J_C"]) + abs(r["J_Q"]), 1e-12, r["P"])
        wdC = self.wd.within["C"]
        y = self.data()["within"]["C"]
        self.assertLess(np.max(np.abs(y - wdC.proj.null_fit(y))), 1e-10)

    def test_exact_partial_regression(self):
        """12: Y = X gamma + H_P a: a recovered; Delta = M_X H a, X'W Delta = 0, J = a'H'WM_XHa / 2, and the
        refitted full minus nuisance-only prediction equals Delta."""
        P, a = 8.0, np.array([0.03, -0.02])
        wdC = self.wd.within["C"]
        H = self.rc.harmonic_matrix(self.tj - self.ti, P)
        y = self.data()["within"]["C"] + H @ a
        hm = wdC.harm[P]
        ah, J, D = hm.fit(y)
        self.assertTrue(np.allclose(ah, a, atol=1e-10))
        self.assertTrue(np.allclose(D, hm.MH @ a, atol=1e-12))
        self.assertLess(np.max(np.abs(wdC.proj.WX.T @ D)), 1e-6)
        self.assertAlmostEqual(J, 0.5 * a @ hm.S @ a, delta=1e-9 * J)
        full, coef = wdC.proj.joint_fit(y, H)
        self.assertTrue(np.allclose(full - wdC.proj.null_fit(y), D, atol=1e-9))
        self.assertTrue(np.allclose(coef, a, atol=1e-9))

    def test_rms_conversion(self):
        """13: intercept-only nuisance, complete uniform cycles: RMS{a cos + b sin} = sqrt((a^2 + b^2) / 2);
        a cosine of amplitude sqrt(2) 0.10 m is a 10% relative RMS, sqrt(2) 0.04 an RMS of 0.04."""
        rc = self.rc
        P = 10.0
        t = np.arange(0, 3 * P, P / 16)
        proj = rc.Projector(np.ones((len(t), 1)), rc.Cov(np.ones(len(t))))
        hm = proj.harmonic(rc.harmonic_matrix(t, P))
        for a, b in ((0.3, 0.4), (math.sqrt(2) * 0.10 * 0.45, 0.0), (math.sqrt(2) * 0.04, 0.0)):
            y = 0.45 + a * np.cos(2 * math.pi * t / P) + b * np.sin(2 * math.pi * t / P)
            D = hm.fit(y)[2]
            rms = math.sqrt(np.mean(D ** 2))
            self.assertAlmostEqual(rms, math.sqrt((a * a + b * b) / 2), places=12)
        self.assertAlmostEqual(math.sqrt(2) * 0.10 * 0.45 / math.sqrt(2) / 0.45, 0.10, places=15)

    # ------------------------------------------------------------ H.14 14-17
    def test_hf_binds_the_population(self):
        """Codex #68 D6 P2-2 (r2): given the eligibility record (stats.eligibility) H-F runs only when it is available,
        on exactly its registered population (the common Q200), from analyses of the bound graph / mask / snapshots
        (their provenance); otherwise StatsError, before any analysis; the result carries its binding."""
        import stats
        ws = [dict(self.rc.analyze_world(self.wd, self.data(k=i)), id=f"w{i}") for i in range(3)]
        ids = [w["id"] for w in ws]
        elig = {"schema": stats.ELIGIBILITY_SCHEMA, "hypotheses": {"H-F": {"available": True, "worlds": ids}}}
        a, b = self.rc.hf(ws), self.rc.hf(list(reversed(ws)), eligibility=elig)
        self.assertEqual((a["n"], a["S_F"]), (b["n"], b["S_F"]))
        with self.assertRaisesRegex(stats.StatsError, "registered population"):
            self.rc.hf(ws[1:], eligibility=elig)
        off = {"schema": stats.ELIGIBILITY_SCHEMA,
               "hypotheses": {"H-F": {"available": False, "reason": "|Q200| = 20 < 24", "worlds": ids}}}
        with self.assertRaisesRegex(stats.StatsError, "is unavailable"):
            self.rc.hf(ws, eligibility=off)
        # (Codex #68 D6 r2 P2-2: the analyses' provenance must be the record's binding; hf_decision keeps it)
        prov = {"graph_edges_sha256": "g" * 64, "mask_sha256": "m" * 64, "snapshots_sha256": "s" * 64}
        bound = {"schema": stats.ELIGIBILITY_SCHEMA, "hypotheses": {"H-F": {"available": True, "worlds": ids,
                                                                            "binding": prov}}}
        r = self.rc.hf(ws, eligibility=bound, provenance=dict(prov))
        self.assertEqual(r["binding"], stats.result_binding(bound, "H-F"))
        d = self.rc.hf_decision(r, c_F=0.0, p_F=0.001)
        self.assertEqual((d["worlds"], d["binding"]), (ids, r["binding"]))
        self.assertEqual(self.rc.hf_decision(r, c_F=None)["binding"], r["binding"])
        with self.assertRaisesRegex(stats.StatsError, "provenance"):
            self.rc.hf(ws, eligibility=bound, provenance=dict(prov, mask_sha256="n" * 64))
        self.assertNotIn("binding", self.rc.hf_decision(a, c_F=0.0, p_F=0.001))

    def hfw(self, datas):
        return self.rc.hf([dict(self.rc.analyze_world(self.wd, d), id=f"w{i}") for i, d in enumerate(datas)])

    def test_phase_preservation(self):
        """14: four worlds at phases 0, pi/2, pi, 3pi/2: their average harmonic cancels, but every world's
        own reciprocal score is positive (no averaging of curves before fitting)."""
        phs = [0.0, math.pi / 2, math.pi, 3 * math.pi / 2]
        ds = [self.data(8.0, ph, ph, 0.05, 0.02, 0.05, 0.02) for ph in phs]
        self.assertLess(np.max(np.abs(sum(np.cos(2 * math.pi * self.rt / 8 - ph) for ph in phs))), 1e-12)
        res = self.hfw(ds)
        self.assertTrue(res["available"])
        for w in res["worlds"].values():
            self.assertEqual((w["P"], w["g"]), (8.0, 1))
            self.assertGreater(w["contribution"], 0)
        self.assertEqual(res["positive"], 4)

    def test_different_periods_by_world(self):
        """15: each world's period is selected separately (no population period)."""
        Ps = [6.0, 8.0, 12.0]
        res = self.hfw([self.data(P, 0.3, 1.1, 0.05, 0.02, 0.05, 0.02) for P in Ps])
        self.assertEqual([res["worlds"][f"w{i}"]["P"] for i in range(3)], Ps)

    def test_single_readout_recurrence(self):
        """16: capture recurrence alone, then survival alone: the reciprocal score is zero."""
        for kw in (dict(aC=0.05, rC=0.05), dict(aQ=0.02, rQ=0.02)):
            res = self.hfw([self.data(8.0, 0.4, 0.4, **kw)])
            self.assertTrue(res["available"])
            self.assertLess(res["S_F"], 1e-12)

    def test_disjoint_world_recurrence(self):
        """17: capture-only recurrence in half the worlds, survival-only in the other half: zero."""
        ds = [self.data(8.0, 0.4, 0.4, aC=0.05, rC=0.05, k=k) for k in range(2)]
        ds += [self.data(8.0, 0.4, 0.4, aQ=0.02, rQ=0.02, k=k) for k in range(2)]
        res = self.hfw(ds)
        self.assertLess(res["S_F"], 1e-12)
        self.assertEqual(res["E_C"] + res["E_Q"], 0.0)

    # ------------------------------------------------------------ H.14 18-20
    def test_window_weights_and_returns(self):
        """18: an ideal P = 8M cosine with interior centres 10, 14, 18, 22, 26 and integer-M observations:
        three times per window, window means of magnitude A(1 + sqrt 2)/3, alternating, returns 0."""
        rc = self.rc
        P, A = 8.0, 0.3
        times = np.arange(8.0, 31.0)
        phi = 2 * math.pi * 10 / P
        k, wins = rc.chain(times, 8.0, 30.0, P, phi)
        self.assertEqual([times[lo:hi].tolist() for lo, hi in wins],
                         [[c - 1, c, c + 1] for c in (10.0, 14.0, 18.0, 22.0, 26.0)])
        y = A * np.cos(2 * math.pi * times / P - phi)
        v = [float(np.mean(y[lo:hi])) for lo, hi in wins]
        e = [1.0 if (k + j) % 2 == 0 else -1.0 for j in range(5)]
        for vj, ej in zip(v, e):
            self.assertAlmostEqual(vj, ej * A * (1 + math.sqrt(2)) / 3, places=12)
        self.assertEqual(rc.gate(v, e, 2 * A), (True, True))
        self.assertAlmostEqual(abs(v[2] - v[0]), 0.0, places=12)
        # through a reference panel: the fitted phase puts the windows at the same centres
        t = np.tile(times, 4)
        r = np.repeat(np.array(REFS, object), len(times))
        rd = rc.RefDesign(t, r, rc.Cov(np.full(len(t), 1e-4)), (8.0, 30.0), (P,))
        out = rd.readout(0.4 + A * np.cos(2 * math.pi * t / P - phi), P)
        self.assertEqual(out["windows"], [[c - 1, c, c + 1] for c in (10.0, 14.0, 18.0, 22.0, 26.0)])
        self.assertEqual(out["G"], 1)

    def test_return_failure_despite_reversals(self):
        """19: (0.10, -0.10, 0.21, -0.10, 0.10) with fitted range 0.20: reversals pass, |v2 - v0| = 0.11
        > 0.10 fails the return."""
        self.assertEqual(self.rc.gate([0.10, -0.10, 0.21, -0.10, 0.10], [1, -1, 1, -1, 1], 0.20), (True, False))

    def test_unsupported_periods(self):
        """20: a coarse-only 5M series cannot support 4M (the P/4 gap rule); a removed window makes the
        candidate unsupported (never interpolated); too short a span fails rule 1."""
        rc = self.rc
        coarse = [1e-6] + [5.0 * k for k in range(1, 41)]
        self.assertFalse(rc.series_ok(coarse, 4.0))
        self.assertTrue(rc.series_ok(coarse, 20.0))
        # remove every time near one extremum centre of the fitted phase: no chain at that phase
        P, phi = 8.0, 0.0                                       # centres 0, 4, ..., 40: no run of five
        keep = [t for t in T if not (15.0 <= t <= 17.0 or 27.0 <= t <= 29.0)]
        self.assertIsNone(rc.chain(np.array(keep), 0.0, 40.0, P, phi))
        self.assertIsNotNone(rc.chain(np.array(T), 0.0, 40.0, P, phi))
        t = np.tile(np.array(keep), 4)
        r = np.repeat(np.array(REFS, object), len(keep))
        rd = rc.RefDesign(t, r, rc.Cov(np.full(len(t), 1e-4)), SC, (P,))
        self.assertEqual(rd.fails[P], ["2-refseries"])            # (the 8M gap > P/4 as well)
        out = rd.readout(0.4 + 0.05 * np.cos(2 * math.pi * t / P - phi), P)
        self.assertFalse(out["chain"])
        self.assertEqual(out["G"], 0)
        wd = rc.WorldDesign("w", {"C": (self.ti, self.tj, rc.Cov(np.full(len(self.ti), 1e-4))),
                                  "Q": (self.ti, self.tj, rc.Cov(np.full(len(self.ti), 1e-4)))},
                            {"C": (self.rt, self.rr, rc.Cov(np.full(len(self.rt), 1e-4))),
                             "Q": (self.rt, self.rr, rc.Cov(np.full(len(self.rt), 1e-4)))}, (0.0, 30.0), (16.0,))
        self.assertEqual(wd.within["C"].fails[16.0], ["1-span"])        # 30 < 32

    # ------------------------------------------------------------ rule 6: phase-conditional support
    def test_phase_conditional_support(self):
        """The coordinator's pre-seal decision: at P = 25M in a 50M epoch the five windows exist only for
        phases with an extremum near the epoch's start; a candidate is supported for a world exactly when
        ITS FITTED PHASE admits the chain, and the per-world frequency is reported."""
        rc = self.rc
        t1 = np.array([1e-6] + [float(k) for k in range(1, 51)])
        ti, tj = (a.ravel() for a in np.meshgrid(t1, t1, indexing="ij"))
        rt = np.tile(t1, 4)
        rr = np.repeat(np.array(REFS, object), len(t1))
        P = 25.0
        wd = rc.WorldDesign("w", {"C": (ti, tj, rc.Cov(np.full(len(ti), 1e-4))), "Q": (ti, tj, rc.Cov(np.full(len(ti), 1e-4)))},
                            {"C": (rt, rr, rc.Cov(np.full(len(rt), 1e-4))), "Q": (rt, rr, rc.Cov(np.full(len(rt), 1e-4)))},
                            "E1", (20.0, P))
        self.assertTrue(wd.ref["C"].cond[P])                     # some phases admit the chain, some do not
        self.assertFalse(wd.ref["C"].cond[20.0])
        tab = wd.ref["C"].tables[P]
        self.assertTrue(np.any(tab.ok) and not np.all(tab.ok))

        def ys(ph):
            def hw(a):
                return a * np.cos(2 * math.pi * (tj - ti) / P - ph)
            return {"within": {"C": 0.3 + hw(0.05), "Q": -0.1 + hw(0.02)},
                    "ref": {"C": 0.4 + 0.05 * np.cos(2 * math.pi * rt / P - ph),
                            "Q": -0.1 + 0.02 * np.cos(2 * math.pi * rt / P - ph)}}
        good = rc.analyze_world(wd, ys(0.0))                     # extrema at 0, 12.5, ..., 50
        bad = rc.analyze_world(wd, ys(2 * math.pi * 6 / P))      # extrema at 6, 18.5, ..., 56: no chain
        g = next(r for r in good["periods"] if r["P"] == P)
        b = next(r for r in bad["periods"] if r["P"] == P)
        self.assertTrue(g["supported"] and g["phase_conditional"])
        self.assertFalse(b["supported"])
        self.assertIn("6-windows", b["fails"])
        self.assertTrue(b["phase_conditional"])
        self.assertEqual(good["phase_support"], {"conditional": 1, "supported_at_fitted_phase": 1, "periods": [P]})
        self.assertEqual(bad["phase_support"], {"conditional": 1, "supported_at_fitted_phase": 0, "periods": []})
        res = rc.hf([dict(good, id="a"), dict(bad, id="b")])
        self.assertEqual(res["phase_support"], {"conditional": 2, "supported_at_fitted_phase": 1,
                                                "worlds_with_conditional": 2})
        # the chain table (the bootstrap's vectorized rule 6) agrees with chain() at any phase
        phis = np.linspace(-math.pi, math.pi, 997)
        self.assert_table_matches(tab, wd.ref["C"].common, 0.0, 50.0, P, phis)

    def assert_table_matches(self, tab, times, L, U, P, phis):
        lo, hi, k, ok = tab.lookup(phis)
        for b, ph in enumerate(phis):
            ch = self.rc.chain(times, L, U, P, float(ph))
            self.assertEqual(bool(ok[b]), ch is not None, ph)
            if ch is not None:
                self.assertEqual(int(k[b]), ch[0])
                self.assertEqual([(int(x), int(y)) for x, y in zip(lo[b], hi[b])], ch[1], ph)

    def test_chain_table_at_every_crossing(self):
        """#68 review 7: at a window-boundary crossing the closed window holds the boundary time; the
        table equals chain() AT every crossing and on both sides of it (window indices, k, feasibility),
        and through the scalar route the readout uses (ChainTable.at)."""
        rc = self.rc
        t = np.array(sorted({1e-6} | {float(x) for x in range(1, 51)} | {12.5, 37.5, 6.25}))
        for P in (8.0, 12.0, 25.0):
            tab = rc.ChainTable(t, 0.0, 50.0, P)
            w = 2 * math.pi / P
            phis = []
            for u in tab.bp:
                for d in (0.0, 1e-12, -1e-12, 1e-9, -1e-9, 1e-7, -1e-7, 1e-5, -1e-5, 1e-3, -1e-3):
                    for q in (0, 1, -2):
                        phis.append(w * (u + d + q * P / 2))
            self.assert_table_matches(tab, t, 0.0, 50.0, P, np.array(phis))
            for ph in phis[:: 37]:
                self.assertEqual(tab.at(ph), rc.chain(t, 0.0, 50.0, P, ph))
            lo, hi, k, ok = tab.lookup([math.nan, math.inf])
            self.assertFalse(ok.any())

    def test_rank_rule_on_the_singular_values(self):
        """#68 review 4: rule 5 is the registered metric, the singular values of M_X H itself (not the
        W-weighted S); singular and near-threshold known answers; a strongly non-uniform W does not move
        the decision; the stable fit equals the full refit."""
        rc = self.rc
        t = np.linspace(0.0, 40.0, 81)
        w = 2 * math.pi / 8.0
        base = np.cos(w * t)
        for eps, want in ((0.0, False), (1e-13, False), (1e-8, True), (1.0, True)):
            H = np.column_stack([base, base + eps * np.sin(w * t)])
            for d in (np.ones(len(t)), np.exp(np.linspace(-12, 12, len(t)))):
                proj = rc.Projector(np.ones((len(t), 1)), rc.Cov(d))
                hm = proj.harmonic(H)
                MH = H - np.ones((len(t), 1)) @ (proj.Ginv @ (proj.WX.T @ H))
                sv = np.linalg.svd(MH, compute_uv=False)
                ref = sv[1] / sv[0]
                self.assertEqual(hm.rank2, want, (eps, d[0]))
                self.assertAlmostEqual(hm.ratio, ref, delta=1e-6 * max(ref, 1e-16) + 1e-15)
        # a valid harmonic under a very non-uniform W: J and Delta equal the dense joint refit
        H = rc.harmonic_matrix(t, 8.0)
        d = np.exp(np.linspace(-6, 6, len(t)))
        X = np.column_stack([np.ones(len(t)), t / 40.0])
        proj = rc.Projector(X, rc.Cov(d))
        hm = proj.harmonic(H)
        y = 0.3 + 0.1 * t / 40 + 0.05 * np.cos(w * t - 0.4) + 0.001 * np.sin(1.3 * t)
        a, J, D = hm.fit(y)
        full, coef = proj.joint_fit(y, H)
        self.assertTrue(np.allclose(full - proj.null_fit(y), D, atol=1e-10))
        self.assertTrue(np.allclose(coef, a, atol=1e-9))
        Wy = proj.cov.wmul(y - proj.null_fit(y))
        rss0 = float((y - proj.null_fit(y)) @ Wy)
        r1 = y - full
        self.assertAlmostEqual(J, 0.5 * (rss0 - float(r1 @ proj.cov.wmul(r1))), delta=1e-9 * rss0)

    def test_structured_and_dense_covariances_agree(self):
        """H.14: the Woodbury (diag + U U') and the dense metric give the same J, phases and support."""
        rc = self.rc
        rng = np.random.default_rng(3)
        n = len(self.ti)
        d = 1e-4 * (1 + rng.random(n))
        U = 3e-3 * rng.standard_normal((n, 3))
        dense = np.diag(d) + U @ U.T
        ws, wd_ = rc.WithinDesign(self.ti, self.tj, rc.Cov(d, U), SC, PER), \
            rc.WithinDesign(self.ti, self.tj, rc.Cov(dense=dense), SC, PER)
        y = self.data(8.0, 0.3, 0.3, 0.05, 0.02, 0.06, 0.03)["within"]["C"]
        for P in PER:
            self.assertEqual(ws.fails[P], wd_.fails[P])
            if ws.harm[P].rank2:
                self.assertAlmostEqual(ws.J(y, P), wd_.J(y, P), delta=1e-7 * max(1.0, abs(wd_.J(y, P))))

    def test_subset_drops_zero_columns_exactly(self):
        """#68 CPU lever L1: Cov.subset keeps only the shared-source columns loading on a kept row; on a g4-shaped
        structured bank (n 2143, k 412, four nonzeros per row, random diagonal) W A on the epoch subset equals
        the full-column subset to <= 1e-12 (relative), and both equal the dense solve on a smaller case."""
        rc = self.rc
        rng = np.random.default_rng(7)
        for n, k, m in ((2143, 412, 267), (300, 60, 40)):
            d = 1e-4 * (1 + rng.random(n))
            U = np.zeros((n, k))
            pre = rng.integers(0, k - 40, n)                     # (three prey-snapshot columns and a predator key)
            for j, c in enumerate((pre, pre + 1, pre + 2, k - 40 + rng.integers(0, 40, n))):
                U[np.arange(n), c] = 3e-3 * rng.standard_normal(n)
            mask = np.zeros(n, bool)
            mask[np.sort(rng.choice(n, m, replace=False))] = True
            cov = rc.Cov(d, U)
            sub, full = cov.subset(mask), rc.Cov(d[mask], U[mask])
            self.assertLess(sub.U.shape[1], full.U.shape[1])
            A = rng.standard_normal((m, 36))
            ws, wf = sub.wmul(A), full.wmul(A)
            self.assertLessEqual(float(np.max(np.abs(ws - wf)) / np.max(np.abs(wf))), 1e-12)
            if n < 1000:
                ridge = rc.RIDGE * float(np.median(full.diag))
                dense = np.linalg.solve(np.diag(d[mask] + ridge) + U[mask] @ U[mask].T, A)
                self.assertLessEqual(float(np.max(np.abs(ws - dense)) / np.max(np.abs(dense))), 1e-10)

    def test_structured_woodbury_is_exact(self):
        """#68 CPU lever L2: the structured W-apply (K assembled from U's sparse rows, the n x k product never
        formed) against (i) the pre-L2 dense Woodbury, verbatim, and (ii) the dense solve, on g4-shaped full-scope
        banks (n 2143; k 234 with two nonzeros per row, k 412 with four) including extreme diagonals (1e-6 and
        1e6 entries): <= 1e-12 relative to the dense Woodbury and to the dense solve where it is well posed."""
        rc = self.rc
        rng = np.random.default_rng(13)
        for n, k, w, extreme in ((2143, 234, 2, False), (2143, 412, 4, False), (2143, 412, 4, True), (500, 90, 4, True)):
            d = 1e-4 * (1 + rng.random(n))
            if extreme:
                d[rng.random(n) < 0.3] = 1e-6
                d[rng.random(n) < 0.3] = 1e6
            U = np.zeros((n, k))
            if w == 2:
                cols = (rng.integers(0, k // 2, n), k // 2 + rng.integers(0, k - k // 2, n))
            else:
                pre = rng.integers(0, k - 42, n)
                cols = (pre, pre + 1, pre + 2, k - 40 + rng.integers(0, 40, n))
            for c in cols:
                U[np.arange(n), c] = 3e-3 * rng.standard_normal(n)
            cov = rc.Cov(d, U)
            A = rng.standard_normal((n, 36))
            got = cov.wmul(A)
            DU = U * cov.dinv[:, None]                                      # (the pre-L2 dense Woodbury)
            Kc = np.linalg.cholesky(np.eye(k) + U.T @ DU)
            Ki = np.linalg.solve(Kc.T, np.linalg.solve(Kc, np.eye(k)))
            old = A * cov.dinv[:, None] - (DU @ ((Ki + Ki.T) / 2)) @ (U.T @ (A * cov.dinv[:, None]))
            rel = np.max(np.abs(got - old), axis=0) / np.max(np.abs(old), axis=0)
            self.assertLessEqual(float(rel.max()), 1e-12, (n, k, extreme))
            if n <= 600:
                ridge = rc.RIDGE * float(np.median(cov.diag))
                dense = np.linalg.solve(np.diag(d + ridge) + U @ U.T, A)
                rel = np.max(np.abs(got - dense), axis=0) / np.max(np.abs(dense), axis=0)
                self.assertLessEqual(float(rel.max()), 1e-12, (n, k, extreme))
            v = cov.wmul(A[:, 0])                                           # (a vector: the same operator)
            self.assertLessEqual(float(np.max(np.abs(v - got[:, 0])) / np.max(np.abs(got[:, 0]))), 1e-13)

    def test_empty_right_hand_side(self):
        """Codex r7 P3: W applied to an (n, 0) right-hand side is an (n, 0) result, for both covariance forms."""
        rc = self.rc
        rng = np.random.default_rng(2)
        n = 30
        for cov in (rc.Cov(1e-4 * (1 + rng.random(n)), 1e-3 * rng.standard_normal((n, 4))),
                    rc.Cov(dense=np.diag(1e-4 * (1 + rng.random(n))))):
            self.assertEqual(cov.wmul(np.zeros((n, 0))).shape, (n, 0))

    def test_no_period_from_graph_density(self):
        """21 (noiseless part): constant and drifting strategies on an irregular coarse + fine graph give
        zero residual recurrence at every candidate."""
        rc = self.rc
        coarse = [1e-6] + [5.0 * k for k in range(1, 9)]
        fine = sorted(set(coarse + [c + d for c in (10.0, 20.0, 30.0) for d in (-4, -2, -1, 1, 2, 4)]))
        pairs = [(a, b) for a in coarse for b in fine] + [(a, b) for a in fine for b in coarse]
        ti = np.array([a for a, _ in pairs])
        tj = np.array([b for _, b in pairs])
        wdes = rc.WithinDesign(ti, tj, rc.Cov(np.full(len(ti), 1e-4)), SC, PER)
        for c in ([0.4, 0, 0, 0, 0], [0.3, 0.1, -0.05, 0.02, 0.01]):          # constant, drifting
            y = poly_within(ti, tj, c)
            for P in PER:
                if P in wdes.harm and wdes.harm[P].rank2:
                    self.assertLess(wdes.J(y, P), 1e-12)

    def test_decisions_and_failures(self):
        """H.3.7: the three results; an input failure (zero covariance) and a world without support make
        the decision unavailable."""
        rc = self.rc
        with self.assertRaises(rc.RecurrenceError):
            rc.Cov(np.zeros(5))
        res = self.hfw([self.data(8.0, 0.3, 0.3, 0.05, 0.02, 0.06, 0.03)])
        d = rc.hf_decision(res, c_F=res["S_F"] / 2, p_F=0.005, c_M=1.0, p_M=0.004)
        self.assertTrue(d["detection"])
        self.assertEqual(d["operational"], res["R_C"] >= 0.10 and res["R_Q"] >= 0.04)
        self.assertFalse(rc.hf_decision(res, c_F=res["S_F"], p_F=0.005)["detection"])   # strictly greater
        self.assertFalse(rc.hf_decision(res, c_F=0.0, p_F=0.02)["detection"])
        empty = {"id": "z", "periods": [{"P": 8.0, "fails": ["1-span"], "supported": False, "s": 0.0,
                                          "phase_conditional": False}],
                 "phase_support": {"conditional": 0, "supported_at_fitted_phase": 0, "periods": []}}
        r2 = rc.hf([empty, dict(rc.analyze_world(self.wd, self.data()), id="a")])
        self.assertFalse(r2["available"])
        self.assertFalse(rc.hf_decision(r2, c_F=0.0, p_F=0.0)["available"])


if __name__ == "__main__":
    unittest.main()

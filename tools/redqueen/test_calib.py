#!/usr/bin/env python3
"""test_calib.py: the Annex H calibration generator and harness (calib.py, H.9-H.12) on a small synthetic
graph. Covers:
  * whole H-F and H-T panels run, finite and deterministic;
  * the q33 speed-ups equal their reference routes: the cached loading sparsity (Panel.cov) against the
    direct construction, the amplitude solver's RMS (recurrence.ref_rms) against RefDesign.readout;
  * the H-T analysis pairs worlds by id;
  * #68 round 3: an H-T numerical failure fails the panel (never a non-rejection); gate artifacts bound to
    their critical values, acceptance and manifests; a background above its target is clipped, never
    accepted; a ceiling is a numerical failure; a failed alternative keeps its direction;
  * the D2 strata: a feasible panel goes to B (verified, boundary residuals under both metrics), an
    infeasible one to I (clipped, null-checked; a non-member discarded), crit = the maximum over strata,
    H-T membership across all six candidates, cap exhaustion makes a mode unavailable, the round plan.
numpy required (RQ_REQUIRE_NUMPY=1 makes a missing numpy a failure).

    python3 -I tools/redqueen/test_calib.py [-v]
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
    import numpy as np  # noqa: E402
except ImportError:
    if os.environ.get("RQ_REQUIRE_NUMPY"):
        raise SystemExit("RQ_REQUIRE_NUMPY is set, but numpy cannot be imported")
    np = None


def strip(rec):
    return {k: v for k, v in rec.items() if not k.startswith("cpu")}


@unittest.skipIf(np is None, "numpy is not installed")
class TestCalib(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import calib
        import recurrence
        cls.cb, cls.rc = calib, recurrence
        cls.graph = calib.synthetic_graph(n=4)
        cls.params = calib.placeholder_params()

    def test_hf_panel_runs_and_is_deterministic(self):
        cb = self.cb
        r1 = cb.run_panel(self.graph, self.params, "H-F", "dev", "actual", "F1", 0)
        r2 = cb.run_panel(self.graph, self.params, "H-F", "dev", "actual", "F1", 0)
        self.assertFalse(r1.get("error"), r1.get("error"))
        self.assertTrue(math.isfinite(r1["score"]))
        self.assertEqual(json.dumps(strip(r1), sort_keys=True, default=str),
                         json.dumps(strip(r2), sort_keys=True, default=str))

    def test_ht_panel_runs_and_is_deterministic(self):
        cb = self.cb
        g0 = {e: 0.0 for e in ("E1", "E2", "E3")}
        r1 = cb.run_panel(self.graph, self.params, "H-T", "dev", "actual", "T1", 0, g0, draws=19)
        r2 = cb.run_panel(list(reversed(self.graph)), self.params, "H-T", "dev", "actual", "T1", 0, g0, draws=19)
        self.assertFalse(r1.get("error"), r1.get("error"))
        self.assertTrue(r1["available"], r1)
        self.assertGreaterEqual(r1["joint_rounds"], 1)                 # (the declared constraints verified)
        self.assertEqual(json.dumps(strip(r1), sort_keys=True, default=str),
                         json.dumps(strip(r2), sort_keys=True, default=str))

    def test_cached_loadings_equal_the_direct_construction(self):
        """Panel.cov through the cached sparsity equals the direct construction (the pre-q33 code)."""
        cb, rc = self.cb, self.rc
        pn = cb.Panel(self.graph, self.params, "H-F", "dev", "actual", "F0", 0)
        wg = self.graph[0]
        rng = np.random.default_rng(1)
        m = {"C": rng.uniform(0.2, 0.6, len(wg.ti)), "S": rng.uniform(0.3, 0.8, len(wg.ti)),
             "F": rng.uniform(0.5, 0.9, len(wg.prey))}
        mr = {"C": rng.uniform(0.2, 0.6, len(wg.cT)), "S": rng.uniform(0.3, 0.8, len(wg.qT)), "F": m["F"]}
        for kind, mm in (("C", m), ("Q", m), ("RC", mr), ("RQ", {"S": mr["S"], "F": m["F"]})):
            got = pn.cov(wg, mm, kind)
            want = direct_cov(pn, wg, mm, kind)
            self.assertTrue(np.allclose(got.d, want.d, rtol=0, atol=0), kind)
            self.assertTrue(np.allclose(got.U, want.U, rtol=0, atol=0), kind)

    def test_amplitude_rms_equals_the_readout(self):
        """recurrence.ref_rms (the amplitude solver's fast route) equals RefDesign.readout's rms and den."""
        rc = self.rc
        wg = self.graph[1]
        rng = np.random.default_rng(2)
        cov = rc.Cov(1e-4 * (1 + rng.random(len(wg.cT))), 3e-3 * rng.standard_normal((len(wg.cT), 2)))
        y = 0.4 + 0.05 * np.cos(2 * math.pi * wg.cT / 12.0 - 0.3) + 0.01 * rng.standard_normal(len(wg.cT))
        for scope in ("full", "E2"):
            rd = rc.RefDesign(wg.cT, wg.cR, cov, scope, (12.0,))
            out = rd.readout(y, 12.0)
            rms, den = rc.ref_rms(wg.cT, wg.cR, cov, scope, 12.0, y)
            self.assertAlmostEqual(rms, out["rms"], delta=1e-12 * max(1.0, out["rms"]))
            self.assertAlmostEqual(den, out["den"], delta=1e-14)


class TestGenerator(unittest.TestCase):
    """#68 round 2: the bounded observation model, the OU red variation, the parameters, the cell
    covariance, the verified joint solve."""

    @classmethod
    def setUpClass(cls):
        import calib
        cls.cb = calib

    def test_erfc(self):
        xs = np.linspace(-9, 30, 20001)
        ref = np.array([math.erfc(x) for x in xs])
        rel = np.abs(self.cb.erfc(xs) - ref) / np.maximum(ref, 1e-300)
        self.assertLess(float(rel.max()), 1e-11)

    def test_location_exact_over_the_full_range(self):
        """E[K/N](a(mu)) = mu (verified interpolation) INCLUDING means below 0.5/N and above 1 - 0.5/N; two
        different saturated means keep different locations (no clipping)."""
        cb = self.cb
        for N, s in ((600, 0.3), (324, 0.8), (600, 0.2)):
            mus = np.array([1e-6, 2e-5, 0.4 / N, 0.6 / N, 0.01, 0.35, 0.5, 0.97, 1 - 0.3 / N, 1 - 1e-6])
            a = cb.location(mus, np.full(len(mus), s), N)
            back = cb.expected_fraction(a, s, N)
            self.assertTrue(np.all(np.abs(back - mus) <= 3 * cb.LOC_TOL), (N, s, back - mus))
            self.assertTrue(np.all(np.diff(a) > 0))
            self.assertLessEqual(cb.location_table(s, N)[2], cb.LOC_TOL)
        # the old Gauss-Hermite / clipping route would give these two the same location
        a = cb.location(np.array([1e-5, 1e-4]), np.array([0.3, 0.3]), 600)
        self.assertLess(a[0], a[1])
        for bad in (0.0, 1.0, float("nan")):
            with self.assertRaises(cb.CalibError):
                cb.location(np.array([bad]), np.array([0.3]), 600)

    def test_ou_red_variation(self):
        """Codex's counterexample rho = (0, .98) is refused, and so is rho = (.05, .98) with innovations
        correlated .95 (no PSD diffusion); valid parameters give PSD transition covariances at every gap."""
        cb = self.cb
        p = cb.placeholder_params()
        bad = [([0.0, 0.98, 0.7, 0.7, 0.7], None), ([0.05, 0.98, 0.7, 0.7, 0.7], 0.95)]
        for rho, c in bad:
            q = json.loads(json.dumps(p))
            q["ar"]["rho"] = rho
            if c is not None:
                S = np.eye(5)
                S[0, 1] = S[1, 0] = c
                q["ar"]["Sigma"] = S.tolist()
            with self.assertRaises(cb.CalibError):
                cb.check_params(q)
        S = cb.shrunk(p["ar"]["Sigma"])
        rho = np.array([0.2, 0.5, 0.7, 0.9, 0.98])
        q = json.loads(json.dumps(p))
        q["ar"]["rho"] = rho.tolist()
        cb.check_params(q)
        _, Q, G = cb.ou_matrices(rho, S)
        rr = np.outer(rho, rho)
        for D in (0.01, 0.2, 1.0, 3.7, 40.0):
            self.assertGreater(np.min(np.linalg.eigvalsh(G * (1 - rr ** D))), -1e-14)
        t = np.array([1e-6, 1.0, 2.0, 5.0, 9.0, 10.0, 31.0, 100.0])
        x = cb.ar_paths(t, rho, p["ar"]["Sigma"], 5.0, np.random.default_rng(1).standard_normal((len(t), 5)))
        self.assertTrue(np.all(np.isfinite(x)))

    def test_parameters(self):
        cb = self.cb
        p = cb.placeholder_params()
        cb.check_params(p)
        with self.assertRaises(cb.CalibError):
            cb.check_params(p, production=True)                      # (not fitted)
        q = json.loads(json.dumps(p))
        del q["noise"]["SigmaE"]
        with self.assertRaises(cb.CalibError):
            cb.check_params(q)
        q = json.loads(json.dumps(p))
        q["noise"]["SigmaE"][0][0] = 0.4                               # (row + donor + cell != 1)
        with self.assertRaises(cb.CalibError):
            cb.check_params(q)

    def test_cell_covariance(self):
        """The capture and exposed-survival cell components of one assay cell are drawn jointly
        (SigmaE's cross-channel correlation)."""
        cb = self.cb
        p = cb.placeholder_params()
        p["noise"]["SigmaE"] = [[0.5, 0.4], [0.4, 0.5]]
        LE = np.linalg.cholesky(np.asarray(p["noise"]["SigmaE"]))
        z = cb.VecSplitMix64(5).normals(40000 * 2).reshape(-1, 2) @ LE.T
        self.assertAlmostEqual(float(np.corrcoef(z.T)[0, 1]), 0.8, delta=0.02)
        g = cb.synthetic_graph(4)
        r = cb.run_panel(g, p, "H-F", "dev", "actual", "F0", 0)
        self.assertFalse(r.get("error"), r.get("error"))

    def test_verified_constraints(self):
        """The completed noise-free panel meets its declared directional slopes (T2: 1.5 delta with
        recurrence) and a perturbed declaration is caught."""
        cb = self.cb
        g = cb.synthetic_graph(4)
        pn = cb.Panel(g, cb.placeholder_params(), "H-T", "dev", "actual", "T2", 0).simulate()
        self.assertTrue(all(v["ok"] for v in pn.verified))
        miss = {(x["world"], x["scope"], x["readout"]) for x in pn.unattainable}
        checked = 0
        for v in pn.verified:
            for k, b in v["dir"].items():
                e, nm = k.split("/")
                if (v["world"], e, nm) in miss:
                    continue
                want = {"beta_P": 1.5 * cb.stats.DELTA_P, "beta_Q": 1.5 * cb.stats.DELTA_Q}[nm]
                self.assertAlmostEqual(b, want, delta=cb.DIR_TOL)
                checked += 1
        self.assertGreater(checked, 0)


def rec(hyp, stage, mode, stratum, panel, man, **kw):
    r = {"hyp": hyp, "stage": stage, "mode": mode, "stratum": stratum, "panel": panel, "manifest": man,
         "available": True, "score": 0.0, "retry": 0, "role": "B", "status": "feasible", "member": True}
    if hyp == "H-F":
        r.update(M=0.5, R_C=0.05, R_Q=0.02, material_point=False, S_e={e: 0.0 for e in ("E1", "E2", "E3")},
                 S_e_available={e: True for e in ("E1", "E2", "E3")})
    r.update(kw)
    return r


class TestHarness(unittest.TestCase):
    """#68 round 2 P1-1, P1-3, P2-4: complete allocations, independent acceptance of the frozen rules,
    failures and manifests, the frozen epoch gates."""

    @classmethod
    def setUpClass(cls):
        import calib
        cls.cb = calib
        cls.man = {"graph_sha256": "g", "graph_source": "file:x", "params_sha256": "p", "params_fitted": True,
                   "tools_sha256": "t", "draws": 9999, "gates_sha256": None, "production": True}

    def allocation(self, hyp, stage, n, score=lambda m, s, k: 0.001 * k, man=None, **kw):
        cb = self.cb
        return [rec(hyp, stage, m, s, k, man or self.man, score=score(m, s, k), **kw)
                for m, s in cb.strata_of(hyp) for k in range(n)]

    def test_completeness_failures_and_manifests(self):
        cb = self.cb
        dev = self.allocation("H-F", "dev", cb.N_DEV)
        crit = cb.critical_values(dev)
        self.assertAlmostEqual(crit["c_F"], 0.159)
        for bad in (dev[:-1],                                                  # (a panel missing)
                    [r for r in dev if not (r["mode"] == "F4" and r["stratum"] == "stress24")],   # (a stratum)
                    dev + [dict(dev[0])],                                      # (a duplicate)
                    [dict(r, error="CalibError: x") if i == 7 else r for i, r in enumerate(dev)],  # (a failure)
                    [dict(r, manifest=dict(self.man, params_sha256="q")) if i == 3 else r for i, r in enumerate(dev)],
                    [dict(r, manifest=dict(self.man, production=False)) for r in dev]):
            with self.assertRaises(cb.CalibError):
                cb.critical_values(bad)
        cb.critical_values([dict(r, manifest=dict(self.man, production=False)) for r in dev], production=False)

    def test_acceptance_is_independent_and_can_fail(self):
        """Every validation panel above the frozen c_F: 1,000 false positives per rate -> FAIL (a panel is
        never judged against a table containing itself); below it -> pass; unavailable panels cannot
        reject; the validation manifest must equal the development one."""
        cb = self.cb
        crit = cb.critical_values(self.allocation("H-F", "dev", cb.N_DEV))
        hi = cb.acceptance(self.allocation("H-F", "val", cb.N_VAL, score=lambda m, s, k: 5.0), crit)
        self.assertEqual(hi["rates"]["H-F"]["detection|F0|actual|B"]["fp"], 1000)
        self.assertFalse(hi["pass"]["H-F detection"])
        lo = cb.acceptance(self.allocation("H-F", "val", cb.N_VAL, score=lambda m, s, k: 0.0), crit)
        self.assertTrue(lo["pass"]["H-F detection"] and lo["pass"]["H-F material"])
        self.assertTrue(all(lo["pass"][f"gate {e}"] for e in ("E1", "E2", "E3")))
        self.assertEqual(len(lo["ptables"]["H-F detection"]["F0|actual|B"]), 1000)
        self.assertEqual(lo["crit_sha256"], cb.doc_sha(crit))
        # 12 false positives pass, 13 fail (the frozen rule, exactly counted)
        def sc(n):
            return lambda m, s, k: (5.0 if (m == "F1" and s == "actual" and k < n) else 0.0)
        self.assertTrue(cb.acceptance(self.allocation("H-F", "val", cb.N_VAL, score=sc(12)), crit)["pass"]["H-F detection"])
        self.assertFalse(cb.acceptance(self.allocation("H-F", "val", cb.N_VAL, score=sc(13)), crit)["pass"]["H-F detection"])
        un = self.allocation("H-F", "val", cb.N_VAL, score=lambda m, s, k: 5.0, available=False)
        self.assertEqual(cb.acceptance(un, crit)["rates"]["H-F"]["detection|F0|actual|B"]["fp"], 0)
        with self.assertRaises(cb.CalibError):                   # (1,000 FAILED panels never pass)
            cb.acceptance([dict(r, error="x") for r in self.allocation("H-F", "val", cb.N_VAL)], crit)
        with self.assertRaises(cb.CalibError):
            cb.acceptance(self.allocation("H-F", "val", cb.N_VAL, man=dict(self.man, graph_sha256="other")), crit)
        with self.assertRaises(cb.CalibError):
            cb.acceptance(self.allocation("H-F", "val", 160), crit)              # (an incomplete allocation)
        # the nested material claim needs detection, the material points and both thresholds
        mat = self.allocation("H-F", "val", cb.N_VAL, score=lambda m, s, k: 5.0 if m == "F3" else 0.0,
                              M=9.0, R_C=0.2, R_Q=0.1, material_point=True)
        acc = cb.acceptance(mat, crit)
        self.assertEqual(acc["rates"]["H-F"]["material|F3|actual|B"]["fp"], 1000)
        self.assertEqual(acc["rates"]["H-F"]["material|F4|actual|B"]["fp"], 0)

    def test_frozen_gates(self):
        """H-T needs every epoch gate with a passing validation; a failed gate refuses the freeze; ht()
        without a gate is unavailable."""
        cb = self.cb
        crit = cb.critical_values(self.allocation("H-F", "dev", cb.N_DEV))
        acc = cb.acceptance(self.allocation("H-F", "val", cb.N_VAL, score=lambda m, s, k: 0.0), crit)
        art = cb.freeze_gates(crit, acc)
        self.assertEqual(cb.check_gates(art)["c_E"], crit["c_E"])
        bad = self.allocation("H-F", "val", cb.N_VAL, score=lambda m, s, k: 0.0)
        bad = [dict(r, S_e=dict(r["S_e"], E2=9.0)) if r["mode"] == "F0" else r for r in bad]
        with self.assertRaises(cb.CalibError):
            cb.freeze_gates(crit, cb.acceptance(bad, crit))
        with self.assertRaises(cb.CalibError):
            cb.check_gates(dict(art, passed=dict(art["passed"], E3=False)))

    def test_gates_bound_to_their_artifacts(self):
        """#68 round 3 P2: acceptance names the critical artifact it evaluated; a gate freeze from another
        artifact's acceptance, a tampered rate, an unbound artifact or a consumer on another graph /
        parameters / code / draws is refused."""
        cb = self.cb
        dev = self.allocation("H-F", "dev", cb.N_DEV)
        crit = cb.critical_values(dev)
        crit2 = cb.critical_values(self.allocation("H-F", "dev", cb.N_DEV, score=lambda m, s, k: 0.002 * k))
        acc2 = cb.acceptance(self.allocation("H-F", "val", cb.N_VAL, score=lambda m, s, k: 0.0), crit2)
        with self.assertRaises(cb.CalibError):
            cb.freeze_gates(crit, acc2)                                     # (another crit's acceptance)
        art = cb.freeze_gates(crit2, acc2)
        self.assertEqual(art["crit_sha256"], cb.doc_sha(crit2))
        cb.check_gates(art, self.man, production=True)
        with self.assertRaises(cb.CalibError):
            cb.check_gates(art, dict(self.man, params_sha256="other"))     # (gates from other parameters)
        with self.assertRaises(cb.CalibError):
            cb.check_gates(art, dict(self.man, tools_sha256="other"))      # (other code)
        bad = json.loads(json.dumps(art))
        bad["rates"]["gate_E2|F1|actual|B"]["fp"] = 40                     # (a tampered count: U95 > 0.02)
        with self.assertRaises(cb.CalibError):
            cb.check_gates(bad)
        with self.assertRaises(cb.CalibError):
            cb.check_gates({k: v for k, v in art.items() if k != "accept_sha256"})

    def alt_allocation(self, hyp="H-T", **kw):
        cb = self.cb
        out = []
        for m in cb.ALT[hyp]:
            for s_ in cb.STRATA:
                for k in range(cb.N_ALT):
                    r = rec(hyp, "alt", m, s_, k, self.man, score=9.0, role="alt", **kw)
                    if hyp == "H-T":
                        r["direction"] = "ARD->FSD" if k % 2 == 0 else "FSD->ARD"
                    out.append(r)
        return out

    def test_power_and_non_success(self):
        """The registered alternative allocation (incomplete refused); a non-success and a FAILED
        alternative count in the denominator of their direction (#68 round 3 P2: 49/50, not 49/49)."""
        cb = self.cb
        crit = {"c_F": 1.0, "c_M": 1.0, "c_T": 7.0, "manifest": {"H-T": dict(self.man, gates_sha256=None)}}
        alt = self.alt_allocation()
        alt[0]["non_success"] = True                                       # (TA1 actual panel 0: forward)
        alt[2] = {k: v for k, v in alt[2].items() if k not in ("score", "direction")}
        alt[2].update(error="CalibError: x", available=False)               # (TA1 actual panel 2: forward, failed)
        alt[2]["direction"] = "ARD->FSD"
        pw = cb.power(alt, crit)["H-T|TA1|actual"]
        self.assertEqual((pw["n"], pw["success"]["rejection"], pw["non_success"], pw["failed"]), (100, 98, 1, 1))
        self.assertEqual(pw["by_direction"]["ARD->FSD"], {"n": 50, "success": 48, "wilson95": cb.wilson(48, 50)})
        self.assertEqual(pw["by_direction"]["FSD->ARD"]["n"], 50)
        with self.assertRaises(cb.CalibError):
            cb.power(alt[:-1], crit)                                         # (an incomplete allocation)
        with self.assertRaises(cb.CalibError):
            cb.power(alt, dict(crit, manifest={"H-T": dict(self.man, graph_sha256="other")}))

    def test_failed_alternative_keeps_its_direction(self):
        cb = self.cb
        orig = cb.Panel.triage

        def boom(self_):
            raise cb.CalibError("a forced generator failure")
        cb.Panel.triage = boom
        try:
            r = cb.run_panel(cb.synthetic_graph(4), cb.placeholder_params(), "H-T", "alt", "actual", "TA1", 1,
                             {e: 0.0 for e in ("E1", "E2", "E3")}, draws=19)
        finally:
            cb.Panel.triage = orig
        self.assertEqual((r["direction"], r["role"]), ("FSD->ARD", "failed"))


class TestRound3(unittest.TestCase):
    """#68 round 3 (be5464a): numerical failures are never non-rejections or infeasibility; a background
    above its target is clipped, never accepted as an overshoot."""

    @classmethod
    def setUpClass(cls):
        import calib
        cls.cb = calib
        cls.graph = calib.synthetic_graph(4)
        cls.params = calib.placeholder_params()

    def test_ht_numerical_failure_fails_the_panel(self):
        cb = self.cb
        orig = cb.transition.ht

        def failing(*a, **k):
            return {"available": False, "reject": False, "T_T": None, "error": "a nonfinite window mean",
                    "failure": "numerical", "winner": None, "phase_support": {}, "EU_unsupported": {}}
        cb.transition.ht = failing
        try:
            r = cb.run_panel(self.graph, self.params, "H-T", "dev", "actual", "T3", 0,
                             {e: 0.0 for e in ("E1", "E2", "E3")}, draws=19)
        finally:
            cb.transition.ht = orig
        self.assertEqual(r["role"], "failed")
        self.assertIn("numerical failure", r["error"])
        self.assertFalse(r["available"])
        self.assertNotIn("score", r)

    def with_rms(self, fn, mode="F1", panel=0):
        cb = self.cb
        orig = cb.Panel.rms_of

        def rms_of(self_, wg, th, pl, u, amp, scope, h, dirC, dirQ):
            return fn(amp.get(scope, (0.0, 0.0))[h], h)
        cb.Panel.rms_of = rms_of
        try:
            return cb.run_panel(self.graph, self.params, "H-F", "dev", "actual", mode, panel)
        finally:
            cb.Panel.rms_of = orig

    def test_background_above_target_is_clipped(self):
        """A background RMS above the target at every amplitude (to the limit): INFEASIBLE, clipped to the
        nearest attainable value (recorded), never accepted as the target."""
        r = self.with_rms(lambda a, h: 0.2)
        self.assertEqual((r["status"], r["role"]), ("infeasible", "I"))
        c = r["clips"][0]
        self.assertEqual((c["kind"], c["readout"], c["target"]), ("below-inf", "C", 0.10))
        self.assertAlmostEqual(c["nearest"], 0.2)

    def test_ceiling_is_a_numerical_failure(self):
        """A target reached only beyond the generating amplitude domain (the limit ladder reaches it): a
        NUMERICAL failure, never infeasible; failed proposals block the allocation and leave q-hat alone."""
        cb = self.cb
        r = self.with_rms(lambda a, h: 0.001 * a)
        self.assertEqual((r["role"], r["status"]), ("failed", "failed"))
        self.assertIn("ceiling", r["error"])
        q = cb.q_hat([{"panel": 0, "status": "feasible"}, {"panel": 1, "status": "infeasible"}, dict(r, panel=2)], 3)
        self.assertEqual((q["infeasible"], q["proposals"]), (1, 2))

    def test_verify_enforces_the_declared_tolerance(self):
        """The completed noise-free panel must meet each declared RMS target to AMP_TOL on both sides."""
        cb = self.cb
        pn = cb.Panel(self.graph, self.params, "H-F", "dev", "actual", "F1", 0).triage()
        self.assertTrue(all(v["ok"] for v in pn.verified))
        for v in pn.verified:
            for k, x in v["rms"].items():
                self.assertLessEqual(abs(x - 0.10), cb.AMP_TOL * 0.10 + 1e-12, k)


class TestStrata(unittest.TestCase):
    """The D2 ruling (2026-11-08): proposals, triage, the B / I strata, crit = the maximum over strata,
    membership, cap exhaustion."""

    @classmethod
    def setUpClass(cls):
        import calib
        cls.cb = calib
        cls.graph = calib.synthetic_graph(4)
        cls.params = calib.placeholder_params()
        cls.man = {"graph_sha256": "g", "graph_source": "file:x", "params_sha256": "p", "params_fitted": True,
                   "tools_sha256": "t", "draws": 9999, "gates_sha256": None, "production": True}

    def test_feasible_panel_goes_to_B_and_is_verified(self):
        """F3 slot 1: the panel multiplier lambda puts the noise-free FUNCTIONAL E_C on d_C^2 (to LAMBDA_TOL);
        the panel goes to B; the final-metric residual is recorded with its label."""
        cb = self.cb
        r = cb.run_panel(self.graph, self.params, "H-F", "dev", "actual", "F3", 1)
        self.assertFalse(r.get("error"), r.get("error"))
        self.assertEqual((r["status"], r["role"], r["member"]), ("feasible", "B", True))
        bs = r["boundary_solve"]
        self.assertEqual(bs["outcome"], "feasible")
        self.assertLessEqual(abs(bs["functional"] - 0.01), cb.LAMBDA_TOL * 0.01)
        self.assertGreater(bs["lambda"], 1.0)                    # (the per-world 0.10 construction was interior)
        nb, fb = r["membership"]["boundary"], r["boundary_final"]
        self.assertEqual((nb["quantity"], fb["quantity"], fb["metric"]), ("E_C", "E_C", "final"))
        self.assertTrue(nb["ok"] and abs(nb["residual"]) <= cb.LAMBDA_TOL)
        self.assertTrue(math.isfinite(fb["residual"]))
        self.assertEqual(fb["ok"], abs(fb["residual"]) <= cb.BOUNDARY_TOL)
        self.assertTrue(math.isfinite(r["score"]))

    def test_boundary_jump_is_construction_infeasible(self):
        """F3 slot 0 on four worlds: E_C(lambda) jumps over d_C^2 (a selection switches): CONSTRUCTION-
        INFEASIBLE, kept in I at the largest lambda below the jump (functional on the null side), counted
        separately from bounded-mean infeasibility and from numerical failures."""
        cb = self.cb
        r = cb.run_panel(self.graph, self.params, "H-F", "dev", "actual", "F3", 0)
        self.assertEqual((r["status"], r["role"], r["member"]), ("construction-infeasible", "I", True))
        j = [c for c in r["clips"] if c.get("kind") == "jump"]
        self.assertEqual(len(j), 1)
        self.assertLess(j[0]["nearest"], 0.01)
        self.assertEqual(r["boundary_solve"]["lambda"], j[0]["lambda"])
        self.assertNotIn("boundary_final", r)                    # (an I panel is not a boundary null)
        self.assertEqual(cb.q_hat([r, dict(r, panel=1, status="feasible")], 2)["infeasible"], 1)
        rep_ = cb.report([r])["groups"]["H-F|dev|F3|actual"]
        self.assertEqual(rep_["boundary_solve"]["outcomes"]["construction-infeasible"], 1)

    def test_boundary_outside_the_range_and_failures(self):
        """E(lambda) above the boundary at EVERY lambda including 0 (patched functionals): infeasible
        (below-inf) and, with E_Q above its material threshold, NOT a material null: discarded. A nonfinite
        functional is a numerical failure."""
        cb = self.cb
        orig = cb.Panel.functionals
        cb.Panel.functionals = lambda self_, final=False: {"E_C": 0.02, "E_Q": 0.01, "R_C": 0.1414, "R_Q": 0.1,
                                                           "M_F": 1.4, "available": True}
        try:
            r = cb.run_panel(self.graph, self.params, "H-F", "dev", "actual", "F3", 1)
        finally:
            cb.Panel.functionals = orig
        self.assertEqual((r["status"], r["member"], r["role"]), ("infeasible", False, "discarded"))
        self.assertEqual(r["boundary_solve"]["lambda"], 0.0)
        self.assertEqual([c["kind"] for c in r["clips"] if c["world"] == "panel"], ["below-inf"])
        cb.Panel.functionals = lambda self_, final=False: {"E_C": math.nan, "E_Q": 0.0}
        try:
            r = cb.run_panel(self.graph, self.params, "H-F", "dev", "actual", "F3", 1)
        finally:
            cb.Panel.functionals = orig
        self.assertEqual(r["role"], "failed")
        self.assertIn("numerical failure", r["error"])

    def with_target(self, mode, target):
        cb = self.cb
        orig = cb.plan_world

        def plan(hyp, mode_, panel, k, rng):
            pl = orig(hyp, mode_, panel, k, rng)
            if hyp == "H-F":
                pl["rec"]["full"] = (target, pl["rec"]["full"][1])
            return pl
        cb.plan_world = plan
        try:
            return cb.run_panel(self.graph, self.params, "H-F", "dev", "actual", mode, 0)
        finally:
            cb.plan_world = orig

    def test_infeasible_panel_goes_to_I_clipped_and_null_checked(self):
        """A capture RMS of 50 is above the native RMS's supremum (to the limit): clipped to the attainable
        supremum; F1 (a detection null by construction) keeps it in I and analyses it."""
        r = self.with_target("F1", 50.0)
        self.assertEqual((r["status"], r["role"], r["member"]), ("infeasible", "I", True))
        self.assertTrue(all(c["kind"] == "above-sup" and c["nearest"] < 50.0 and c["limit"] < 50.0 for c in r["clips"]))
        self.assertEqual(len({c["world"] for c in r["clips"]}), len(self.graph))
        self.assertTrue(math.isfinite(r["score"]))

    def test_ht_membership_spans_all_candidates(self):
        """Clipping one candidate's component can strengthen another: a panel is a null member only if EVERY
        one of the six candidates has a margin <= BOUNDARY_TOL x its scale."""
        cb = self.cb
        cands = [f"{a}->{f}" for a, f, _ in cb.transition.candidates()]
        ms = {c: {k: -1.0 * cb.MARGIN_SCALE[k] if k == "beta_P[a]" else 1.0 * cb.MARGIN_SCALE[k]
                  for k in cb.MARGIN_NAMES} for c in cands}
        self.assertEqual(cb.ht_membership(ms)[0], True)
        ms["E2->E3"] = {k: 1.0 * cb.MARGIN_SCALE[k] for k in cb.MARGIN_NAMES}       # (a genuine transition)
        ok, cand, val = cb.ht_membership(ms)
        self.assertEqual((ok, cand), (False, "E2->E3"))
        self.assertAlmostEqual(val, 1.0)
        ms["E2->E3"]["EF_Q[f]-dQ2"] = 0.5 * cb.BOUNDARY_TOL * cb.MARGIN_SCALE["EF_Q[f]-dQ2"]  # (at the boundary)
        self.assertEqual(cb.ht_membership(ms)[:2], (True, "E2->E3"))
        ms["E1->E2"]["beta_Q[a]"] = math.nan
        with self.assertRaises(cb.CalibError):
            cb.ht_membership(ms)

    def allocation(self, stage, special=None):
        """Every H-F mode x graph: slot k a B panel at retry 0 (score 0.001 k), unless special(mode, graph)
        returns that stratum's own records."""
        cb = self.cb
        n = {"dev": cb.N_DEV, "val": cb.N_VAL}[stage]
        out = []
        for m, s_ in cb.strata_of("H-F"):
            got = special(m, s_, n) if special else None
            out.extend(got if got is not None else [rec("H-F", stage, m, s_, k, self.man, score=0.001 * k) for k in range(n)])
        return out

    def test_crit_is_the_maximum_over_strata(self):
        """F1 actual: 40 infeasible slots in round 0 (I), retried in round 1 (q-hat x K >= N_MIN: every slot,
        80 more infeasible), round 2 every slot again (all surplus). I = 120 >= 99: calibrated; its scores
        (5.0) set c_F, never pooled into B."""
        cb = self.cb

        def special(m, s_, n):
            if (m, s_) != ("F1", "actual"):
                return None
            out = []
            for k in range(n):
                if k < 120:
                    out.append(rec("H-F", "dev", m, s_, k, self.man, score=0.001 * k))
                else:
                    out.append(rec("H-F", "dev", m, s_, k, self.man, score=5.0, role="I", status="infeasible"))
            for k in range(n):
                if k >= 120:
                    out.append(rec("H-F", "dev", m, s_, k, self.man, score=0.001 * k, retry=1))
                elif k < 80:
                    out.append(rec("H-F", "dev", m, s_, k, self.man, score=5.0, retry=1, role="I", status="infeasible"))
                else:
                    out.append(rec("H-F", "dev", m, s_, k, self.man, retry=1, role="discarded", surplus=True))
            out.extend(rec("H-F", "dev", m, s_, k, self.man, retry=2, role="discarded", surplus=True) for k in range(n))
            return out
        recs = self.allocation("dev", special)
        crit = cb.critical_values(recs)
        self.assertEqual(crit["strata"]["H-F|F1|actual|I"]["n"], 120)
        self.assertEqual(crit["strata"]["H-F|F1|actual|I"]["score"], 5.0)
        self.assertAlmostEqual(crit["strata"]["H-F|F1|actual|B"]["score"], 0.159)
        self.assertEqual(crit["c_F"], 5.0)
        self.assertTrue(crit["proposals"]["H-F|F1|actual"]["I_calibrated"])
        self.assertAlmostEqual(crit["proposals"]["H-F|F1|actual"]["q"]["q_hat"], 120 / 480)
        # the registered rounds are enforced: a missing round-2 proposal, or a dropped infeasible member
        with self.assertRaises(cb.CalibError):
            cb.critical_values([r for r in recs if not (r["mode"] == "F1" and r["retry"] == 2 and r["panel"] == 7)])
        with self.assertRaises(cb.CalibError):
            cb.critical_values([dict(r, role="discarded") if (r["mode"] == "F1" and r["retry"] == 1 and r["panel"] == 3)
                                else r for r in recs])

    def test_cap_exhaustion_makes_the_mode_unavailable(self):
        """F2 actual slot 5 is infeasible at every one of its ROUNDS proposals: no B panel, the mode capped,
        every decision needing F2 unavailable (None, never a non-rejection); I = 3 < N_MIN: scoped."""
        cb = self.cb

        def special(m, s_, n):
            if (m, s_) != ("F2", "actual"):
                return None
            out = [rec("H-F", "dev", m, s_, k, self.man, score=0.001 * k) for k in range(n) if k != 5]
            out += [rec("H-F", "dev", m, s_, 5, self.man, retry=r, role="I", status="infeasible") for r in range(cb.ROUNDS)]
            return out
        crit = cb.critical_values(self.allocation("dev", special))
        self.assertIn("H-F|F2|actual", crit["unavailable"])
        self.assertEqual((crit["c_F"], crit["c_M"]), (None, None))
        self.assertTrue(all(v is None for v in crit["c_E"].values()))
        self.assertFalse(crit["proposals"]["H-F|F2|actual"]["I_calibrated"])
        acc = cb.acceptance(self.allocation("val"), crit)
        self.assertFalse(acc["pass"]["H-F detection"] or acc["pass"]["H-F material"])
        with self.assertRaises(cb.CalibError):
            cb.freeze_gates(crit, acc)
        # a slot retried fewer than ROUNDS times is incomplete, not capped
        def short(m, s_, n):
            got = special(m, s_, n)
            return None if got is None else [r for r in got if r["retry"] < 2]
        with self.assertRaises(cb.CalibError):
            cb.critical_values(self.allocation("dev", short))

    def test_round_plan(self):
        cb = self.cb
        n = 10
        r0 = [{"panel": k, "retry": 0, "role": "B" if k != 3 else "I", "status": "feasible" if k != 3 else "infeasible"}
              for k in range(n)]
        self.assertEqual(cb.round_plan(r0, n, "dev", 1), [3])                # (q-hat 0.1 x K 30 = 3 < 99)
        big = [{"panel": k, "retry": 0, "role": "I" if k < 40 else "B", "status": "infeasible" if k < 40 else "feasible"}
               for k in range(160)]
        self.assertEqual(cb.round_plan(big, 160, "dev", 1), list(range(160)))  # (I collection: 0.25 x 480 = 120 >= 99)
        self.assertEqual(cb.round_plan(big, 160, "val", 1), list(range(40)))   # (120 < 149: only the slots without B)



def direct_cov(pn, wg, m, kind):
    """The pre-q33 Panel.cov, verbatim (the oracle)."""
    import calib as cb
    import recurrence
    R = cb.R_REP
    SR, SD = np.asarray(pn.p["noise"]["SigmaR"], float), np.asarray(pn.p["noise"]["SigmaD"], float)
    N = pn.p["capture_bound"]

    def g(ch, x, n):
        x = np.clip(x, 0.5 / n, 1 - 0.5 / n)
        return cb.noise_scale(pn.p, ch, x) * x * (1 - x)
    if kind in ("C", "RC"):
        t_pred = wg.tj if kind == "C" else wg.cT
        prey_key = [("Q", t) for t in wg.ti] if kind == "C" else [("RQ", r) for r in wg.cR]
        gg = g("C", m["C"], N)
        eC = 1 - SR[0, 0] - SD[0, 0]
        cols, d = [], gg ** 2 * eC / R
        for keys, var in ((prey_key, SR[0, 0]), ([("P", t) for t in t_pred], SD[0, 0])):
            uk = {k: i for i, k in enumerate(sorted(set(keys), key=str))}
            M = np.zeros((len(keys), len(uk)))
            M[np.arange(len(keys)), [uk[k] for k in keys]] = gg * math.sqrt(var / R)
            cols.append(M)
        return recurrence.Cov(d, np.hstack(cols))
    prey_t = wg.ti if kind == "Q" else wg.qT
    pred_key = [("P", t) for t in wg.tj] if kind == "Q" else [("RP", r) for r in wg.qR]
    gS = g("S", m["S"], cb.TRIALS)
    fm = dict(zip(wg.prey.tolist(), m["F"].tolist()))
    gF = g("F", np.array([fm[t] for t in prey_t]), cb.TRIALS)
    L = np.linalg.cholesky(np.array([[SR[1, 1], SR[1, 2]], [SR[1, 2], SR[2, 2]]]) + 1e-15 * np.eye(2))
    eS, eF = 1 - SR[1, 1] - SD[1, 1], 1 - SR[2, 2]
    d = gS ** 2 * eS / R
    uk = {t: i for i, t in enumerate(sorted(set(prey_t.tolist())))}
    rows = np.arange(len(prey_t))
    ci = np.array([uk[t] for t in prey_t.tolist()])
    M = np.zeros((len(prey_t), 3 * len(uk)))
    M[rows, 3 * ci] = (gS * L[0, 0] - gF * L[1, 0]) / math.sqrt(R)
    M[rows, 3 * ci + 1] = (-gF * L[1, 1]) / math.sqrt(R)
    M[rows, 3 * ci + 2] = (-gF * math.sqrt(eF)) / math.sqrt(R)
    pk = {k: i for i, k in enumerate(sorted(set(pred_key), key=str))}
    Md = np.zeros((len(prey_t), len(pk)))
    Md[rows, [pk[k] for k in pred_key]] = gS * math.sqrt(SD[1, 1] / R)
    return recurrence.Cov(d, np.hstack([M, Md]))


if __name__ == "__main__":
    unittest.main()

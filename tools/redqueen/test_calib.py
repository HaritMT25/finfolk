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
  * the D2 strata (#68 round 4): a feasible panel enters B only inside the one-sided boundary window under
    BOTH metrics (a final-metric failure is discarded), an unreached one goes to I (clipped, null-checked;
    a non-member discarded), membership without scientific slack across all six H-T candidates, pooled
    ordered streams per quota cell with the registered stopping point, crit = the maximum over strata, cap
    exhaustion makes a mode unavailable, the audit's q-hats, the stratum set frozen at dev, the
    unavailability adapters, the CPU ledger.
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

    def test_structured_woodbury_end_to_end(self):
        """#68 CPU lever L2 end to end: every world's full-history and epoch analysis (supports, selections,
        phases, J, RMS) under the structured W-apply equals the pre-L2 dense Woodbury's (support and selection
        decisions identical; values <= 1e-10 relative)."""
        cb, rc = self.cb, self.rc

        class OldCov(rc.Cov):
            def subset(self, mask):
                c = rc.Cov.subset(self, mask)
                c.__class__ = OldCov
                return c

            def wmul(self, A):
                A = np.asarray(A, float)
                A2 = A.reshape(self.n, -1)
                out = A2 * self.dinv[:, None]
                if self.U is not None:
                    DU = self.U * self.dinv[:, None]
                    Kc = np.linalg.cholesky(np.eye(self.U.shape[1]) + self.U.T @ DU)
                    Ki = np.linalg.solve(Kc.T, np.linalg.solve(Kc, np.eye(Kc.shape[0])))
                    out = out - (DU @ ((Ki + Ki.T) / 2)) @ (self.U.T @ out)
                return out.ravel() if A.ndim == 1 else out
        pn = cb.Panel(self.graph, self.params, "H-F", "dev", "actual", "F1", 0).simulate()
        for w in pn.worlds[:2]:
            old = {k: v for k, v in w["cov"].items()}
            for v in old.values():
                v.__class__ = OldCov
            for scope in ("full", "E2"):
                a = rc.analyze_world(cb.Panel._world_design(w["graph"], old, scope), w["y"])
                new = {k: rc.Cov(v.d, v.U) for k, v in old.items()}
                b = rc.analyze_world(cb.Panel._world_design(w["graph"], new, scope), w["y"])
                self.assertEqual(rc.select(a)[:1] + (rc.select(a)[2],), rc.select(b)[:1] + (rc.select(b)[2],))
                for ra, rb in zip(a["periods"], b["periods"]):
                    self.assertEqual((ra["supported"], ra["fails"]), (rb["supported"], rb["fails"]))
                    for key in ("J_C", "J_Q", "r_C", "r_Q", "s"):
                        if key in ra and math.isfinite(ra[key]):
                            self.assertLessEqual(abs(ra[key] - rb[key]), 1e-10 * max(1.0, abs(ra[key])), (scope, key))
            for v in old.values():
                v.__class__ = rc.Cov

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
         "available": True, "score": 0.0, "role": "B", "eligible": "B", "status": "feasible", "member": True,
         "stream": None}
    if stage in ("dev", "val"):
        import calib
        n = {"dev": calib.N_DEV, "val": calib.N_VAL}[stage]
        c = calib.quota_cell(hyp, mode, panel)
        r.update(cell=c, k=calib.cells_of(hyp, mode, n)[c].index(panel))
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
    """#68 rounds 3-4: numerical failures are never non-rejections or unreached; a background above its
    target is clipped (unreached), never accepted as an overshoot."""

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
                             {e: 0.0 for e in ("E1", "E2", "E3")}, draws=19, cell="all", k=0)
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
            return cb.run_panel(self.graph, self.params, "H-F", "dev", "actual", mode, panel, cell="lvl0", k=0)
        finally:
            cb.Panel.rms_of = orig

    def test_background_above_target_is_clipped(self):
        """A background RMS above the target at every amplitude of the registered search: UNREACHED, clipped to
        the attained minimum (recorded with its shortfall), never accepted as the target."""
        r = self.with_rms(lambda a, h: 0.2)
        self.assertEqual((r["status"], r["role"]), ("unreached", "I"))
        c = r["clips"][0]
        self.assertEqual((c["kind"], c["readout"], c["target"]), ("unreached-below", "C", 0.10))
        self.assertAlmostEqual(c["nearest"], 0.2)
        self.assertAlmostEqual(c["shortfall"], 0.1)

    def test_unreached_is_neither_infeasible_nor_failed(self):
        """#68 round 4 P2-4: a target above the maximum attained on the registered search ([0, A_SUP]) is
        UNREACHED (an honest class, kept in I), whatever larger amplitudes might do; a nonfinite solver value
        is a NUMERICAL failure, which blocks the allocation and stays out of every q-hat."""
        cb = self.cb
        r = self.with_rms(lambda a, h: 0.001 * a)
        self.assertEqual((r["status"], r["eligible"], r["role"]), ("unreached", "I", "I"))
        self.assertTrue(all(c["kind"] == "unreached-above" and abs(c["nearest"] - 0.001 * cb.A_SUP) < 1e-12
                            for c in r["clips"]))
        bad = self.with_rms(lambda a, h: math.nan)
        self.assertEqual((bad["role"], bad["status"]), ("failed", "failed"))
        a = cb.audit_classes([r, dict(r, eligible="B", role="B", status="feasible"), bad])
        self.assertEqual((a["n"], a["classes"]["I_eligible"], a["classes"]["B"], a["classes"]["failed"]), (2, 1, 1, 1))

    def test_capture_slope_fallback(self):
        """#68 repair: when the coupled capture secant does not converge (forced here: DIR_STEPS = 1), each epoch
        is solved alone on KNOB_GRID with the safeguarded root; the completed panel still verifies its slopes."""
        cb = self.cb
        old = cb.DIR_STEPS
        cb.DIR_STEPS = 1
        try:
            pn = cb.Panel(self.graph, self.params, "H-T", "dev", "actual", "T0", 0).triage()
        finally:
            cb.DIR_STEPS = old
        self.assertTrue(all(v["ok"] for v in pn.verified))
        for v in pn.verified:
            for e in ("E1", "E2", "E3"):
                self.assertAlmostEqual(v["dir"][f"{e}/beta_P"], 1.5 * cb.stats.DELTA_P, delta=cb.DIR_TOL)

    def test_knob_stays_in_its_domain(self):
        """#68 round 5 P2-1: a survival-slope root just outside the registered knob domain (8.2 > KNOB_MAX = 8) with
        a warm start at 7.5: the walk never evaluates beyond 8, the grid search finds no bracket, and the target is
        UNREACHED at a knob inside the domain (never an accepted root at 8.2)."""
        cb = self.cb
        pn = cb.Panel(self.graph, self.params, "H-T", "dev", "actual", "T0", 0)
        pn.member = lambda: {"member": True, "by": "test"}
        pn.triage()
        w = pn.worlds[0]
        th, u, dirC, dirQ = w["_ctx"]
        seen = []
        mid = {"E1": (10.0, 40.0), "E2": (85.0, 115.0), "E3": (160.0, 190.0)}

        def fake(wg, th_, pl, u_, dC, dQ, only=None, which="PQ", amp=None):
            out = {}
            for e in ([only] if only else cb.transition.EPOCHS):
                t1, t2 = mid[e]
                kq = (dQ(t2) - dQ(t1)) / (t2 - t1) * 50.0
                seen.append(kq)
                out[e] = (pl["dir"][e][0], pl["dir"][e][1] + 0.1 * (kq - 8.2))
            return out
        pn.noiseless_betas = fake
        pn.unattainable = []
        E = cb.transition.EPOCHS
        _, _, (bC, bQ) = pn.solve_dir(w["graph"], th, w["plan"], u, {}, ({e: 0.0 for e in E}, {e: 7.5 for e in E}))
        self.assertTrue(all(abs(k) <= cb.KNOB_MAX + 1e-9 for k in seen), max(seen))
        self.assertTrue(all(abs(v) <= cb.KNOB_MAX for v in bQ.values()))
        un = [x for x in pn.unattainable if x["readout"] == "beta_Q"]
        self.assertEqual(len(un), 3)
        self.assertTrue(all(x["kind"] == "unreached-above" and abs(x["knob"]) <= cb.KNOB_MAX for x in un))

    def test_structural_membership(self):
        """C2 (Codex round 5): T0-T3 membership from the completed, verified slopes alone (no functionals),
        with its witness: T1 pins beta_P[a] (scaled <= DIR_TOL / delta_P), T0 pins delta_P - beta_P[f] (about
        -0.5)."""
        cb = self.cb
        orig = cb.Panel.functionals
        cb.Panel.functionals = lambda self_, final=False: (_ for _ in ()).throw(AssertionError("functionals called"))
        try:
            p1 = cb.Panel(self.graph, self.params, "H-T", "dev", "actual", "T1", 0).triage()
            p0 = cb.Panel(self.graph, self.params, "H-T", "dev", "actual", "T0", 1).triage()
        finally:
            cb.Panel.functionals = orig
        for pn, pin, lim in ((p1, "beta_P[a]", cb.DIR_TOL / cb.stats.DELTA_P), (p0, "dP-beta_P[f]", -0.5 + cb.DIR_TOL / cb.stats.DELTA_P)):
            m = pn.membership
            self.assertEqual((m["by"], m["member"]), ("structural", True))
            self.assertEqual(len(m["witness"]), 6)
            self.assertLessEqual(m["strongest_margin"], lim + 1e-12)
            self.assertLess(m["bound"], cb.TAU_NUM)
            self.assertTrue(all(v["scaled"] <= lim + 1e-12 for v in m["witness"].values()))
            self.assertTrue(set(v["margin"] for v in m["witness"].values()) <= set(cb.MARGIN_NAMES))

    def test_solver_identity_in_the_manifest(self):
        """C3: the registered solver settings (the frozen-metric lambda included) are bound into every manifest
        and compared across artifacts (IDENT)."""
        cb = self.cb
        man = cb.manifest(self.graph, self.params, 19)
        self.assertEqual(man["solver"]["lambda_frozen_metric"], cb.LAMBDA_FROZEN_METRIC)
        self.assertEqual(man["solver_sha256"], cb.doc_sha(cb.solver_identity()))
        self.assertIn("solver_sha256", cb.IDENT)

    def test_verify_enforces_the_declared_tolerance(self):
        """The completed noise-free panel must meet each declared RMS target to AMP_TOL on both sides."""
        cb = self.cb
        pn = cb.Panel(self.graph, self.params, "H-F", "dev", "actual", "F1", 0).triage()
        self.assertTrue(all(v["ok"] for v in pn.verified))
        for v in pn.verified:
            for k, x in v["rms"].items():
                self.assertLessEqual(abs(x - 0.10), cb.AMP_TOL * 0.10 + 1e-12, k)

    def test_unavailability_adapters(self):
        """#68 round 4 P3: an unavailable critical value never reaches a numeric comparison: hf_decision and
        ht() return unavailable (p = 1 in Holm), decision_inputs reports it."""
        cb = self.cb
        res = {"available": True, "S_F": 9.0, "material_point": True, "M_F": 2.0, "R_C": 0.2, "R_Q": 0.1}
        d = cb.recurrence.hf_decision(res, None, p_F=0.001)
        self.assertFalse(d["available"])
        ok = {"pass": {"H-F detection": True, "H-F material": True, "H-T": True}}
        inp = cb.decision_inputs({"manifest": {"H-F": {}, "H-T": {}}, "c_F": None, "c_M": 1.0, "c_T": 7.0}, ok)
        self.assertEqual((inp["H-F detection"]["available"], inp["H-F material"]["available"], inp["H-T"]["available"]),
                         (False, False, True))
        # (#68 round 5 P3: an F3-only cap leaves detection available)
        inp = cb.decision_inputs({"manifest": {"H-F": {}}, "c_F": 1.0, "c_M": None},
                                 {"pass": {"H-F detection": True, "H-F material": False}})
        self.assertEqual((inp["H-F detection"]["available"], inp["H-F material"]["available"]), (True, False))


class TestStrata(unittest.TestCase):
    """The D2 ruling with Codex round 4: proposals, triage, the enforced boundary, the B / I strata from
    pooled per-cell streams, crit = the maximum over strata, membership, cap exhaustion, the audit, the
    frozen stratum set, the CPU ledger."""

    @classmethod
    def setUpClass(cls):
        import calib
        cls.cb = calib
        cls.graph = calib.synthetic_graph(4)
        cls.params = calib.placeholder_params()
        cls.man = {"graph_sha256": "g", "graph_source": "file:x", "params_sha256": "p", "params_fitted": True,
                   "tools_sha256": "t", "draws": 9999, "gates_sha256": None, "production": True}

    def run_(self, mode, slot, **kw):
        cb = self.cb
        c = cb.quota_cell("H-F", mode, slot)
        return cb.run_panel(self.graph, self.params, "H-F", "dev", "actual", mode, slot, cell=c,
                            k=cb.cells_of("H-F", mode, cb.N_DEV)[c].index(slot), **kw)

    def test_feasible_panel_goes_to_B_and_is_verified(self):
        """F4 slot 0: the panel multiplier lambda puts the noise-free FUNCTIONAL E_Q in the one-sided window
        [d_Q^2 (1 - LAMBDA_TOL), d_Q^2]; the final-metric check passes too (ok REQUIRED); the panel is B."""
        cb = self.cb
        self.assertFalse(cb.LAMBDA_FROZEN_METRIC)                            # (the registered value: OFF)
        r = self.run_("F4", 0)
        self.assertFalse(r.get("error"), r.get("error"))
        self.assertEqual((r["status"], r["eligible"], r["role"], r["member"]), ("feasible", "B", "B", True))
        bs = r["boundary_solve"]
        self.assertEqual(bs["outcome"], "feasible")
        self.assertTrue(-cb.LAMBDA_TOL * cb.D_Q ** 2 <= bs["functional"] - cb.D_Q ** 2 <= 0.0)
        nb, fb = r["membership"]["boundary"], r["boundary_final"]
        self.assertTrue(nb["ok"] and fb["ok"])
        self.assertEqual(fb["metric"], "final")
        self.assertTrue(-cb.BOUNDARY_TOL <= fb["residual"] <= 0.0)
        self.assertTrue(math.isfinite(r["score"]))
        self.assertIn("full/Q", r["targets"])

    def test_design_cache_and_frozen_metric_lambda(self):
        """#68 CPU levers: (a) a world's final-metric design is built once and shared by the analysis and the
        final-metric boundary check (the identical covariance: exact); (c) with LAMBDA_FROZEN_METRIC the lambda
        iterates are proposed on a frozen metric but ACCEPTED only by the true one (the same window)."""
        cb = self.cb
        pn = cb.Panel(self.graph, self.params, "H-F", "dev", "actual", "F4", 0).simulate()
        w = pn.worlds[0]
        d1 = pn.design(w, "full")
        self.assertIs(pn.design(w, "full"), d1)
        fresh = cb.Panel._world_design(w["graph"], w["cov"], "full")
        a, b = cb.recurrence.analyze_world(d1, w["y"]), cb.recurrence.analyze_world(fresh, w["y"])
        self.assertEqual(json.dumps(a, default=str, sort_keys=True), json.dumps(b, default=str, sort_keys=True))
        self.assertIs(pn.design_nf(w, "full"), pn.design_nf(w, "full"))
        old = cb.LAMBDA_FROZEN_METRIC
        try:
            cb.LAMBDA_FROZEN_METRIC = False
            off = self.run_("F4", 0)
            cb.LAMBDA_FROZEN_METRIC = True
            on = self.run_("F4", 0)
        finally:
            cb.LAMBDA_FROZEN_METRIC = old
        for r in (off, on):
            bs = r["boundary_solve"]
            self.assertEqual(bs["outcome"], "feasible")
            self.assertTrue(-cb.LAMBDA_TOL * cb.D_Q ** 2 <= bs["functional"] - cb.D_Q ** 2 <= 0.0)   # (the TRUE metric)
        self.assertIsNone(off["boundary_solve"]["frozen"])
        self.assertGreater(on["boundary_solve"]["frozen"]["evals"], 0)
        self.assertLessEqual(on["boundary_solve"]["evals"], off["boundary_solve"]["evals"])
        self.assertEqual(on["role"], off["role"])

    def test_design_cache_guard(self):
        """#68 round 6 P3: a cached design carries its covariance version, graph and periods; a lookup after the
        covariance changed raises (a stale design is impossible); observe resets the final-metric cache."""
        cb = self.cb
        pn = cb.Panel(self.graph, self.params, "H-F", "dev", "actual", "F1", 0).simulate()
        w = pn.worlds[0]
        pn.design(w, "full")
        w["_cov_ver"] += 1000
        with self.assertRaises(cb.CalibError):
            pn.design(w, "full")
        pn.observe_all()
        self.assertIsNotNone(pn.design(w, "full"))
        d = pn.design_nf(w, "E2")
        self.assertIs(pn.design_nf(w, "E2"), d)
        w["_cov_nf_ver"] += 1000
        with self.assertRaises(cb.CalibError):
            pn.design_nf(w, "E2")

    def test_lambda_bracket_handoff(self):
        """The frozen-metric proposals hand their first TRUE bracket to the true safeguarded solver: the
        classification equals the pure true-metric search's, the accepted functional lies in the same true
        window, and the handoff never takes more true evaluations than the pure search."""
        cb = self.cb
        old = cb.LAMBDA_FROZEN_METRIC
        out = {}
        try:
            for flag in (False, True):
                cb.LAMBDA_FROZEN_METRIC = flag
                out[flag] = [self.run_(m, k) for m, k in (("F3", 0), ("F3", 1), ("F4", 0), ("F4", 1))]
        finally:
            cb.LAMBDA_FROZEN_METRIC = old
        for a, b in zip(out[False], out[True]):
            self.assertEqual((a["status"], a.get("eligible")), (b["status"], b.get("eligible")))
            for r in (a, b):
                bs = r["boundary_solve"]
                if bs["outcome"] == "feasible":
                    self.assertTrue(-cb.BOUNDARY_TOL <= bs["residual"] <= 0.0)
            self.assertLessEqual(b["boundary_solve"]["evals"], a["boundary_solve"]["evals"] + 1)

    def test_final_metric_is_reported_never_gating(self):
        """The coordinator's ruling (2026-11-08): F3 slot 1 meets its boundary under the triage metric (the
        definition) but not under the FINAL metric (residual about -10%): it is a B panel, analysed, with the
        final-metric value REPORTED as the estimator distortion (never a discard)."""
        r = self.run_("F3", 1)
        self.assertEqual((r["eligible"], r["role"], r.get("discard")), ("B", "B", None))
        self.assertTrue(r["membership"]["boundary"]["ok"])
        self.assertFalse(r["boundary_final"]["ok"])
        self.assertLess(r["boundary_final"]["residual"], -self.cb.BOUNDARY_TOL)
        self.assertTrue(math.isfinite(r["score"]))
        self.assertEqual(self.cb.audit_classes([r])["classes"]["final_boundary"], 0)

    def test_boundary_jump_is_unreached(self):
        """F3 slot 0 on four worlds: E_C(lambda) jumps over d_C^2 (a selection switches) with the null-side
        endpoint outside the window, and the registered LAMBDA_GRID holds no other bracket: UNREACHED on the
        registered search, kept in I at the attained null-side endpoint, the shortfall recorded."""
        cb = self.cb
        r = self.run_("F3", 0)
        self.assertEqual((r["status"], r["eligible"], r["role"], r["member"]), ("unreached", "I", "I", True))
        j = [c for c in r["clips"] if c.get("kind") == "jump"]
        self.assertEqual(len(j), 1)
        self.assertLess(j[0]["nearest"], 0.01 * (1 - cb.BOUNDARY_TOL))
        self.assertAlmostEqual(j[0]["shortfall"], 0.01 - j[0]["nearest"])
        self.assertEqual(r["boundary_solve"]["lambda"], j[0]["lambda"])
        self.assertIn(j[0]["lambda"], [p[0] for p in r["boundary_solve"]["path"]])      # (an evaluated point)
        self.assertNotIn("boundary_final", r)
        g = cb.report([r])["groups"]["H-F|dev|F3|actual"]
        self.assertEqual(g["boundary_solve"]["outcomes"]["unreached"], 1)
        self.assertIsNotNone(g["targets"]["full/Q"]["achieved_max"])           # (#68 round 5 P3: "max" ranges kept)
        self.assertLessEqual(g["targets"]["full/Q"]["achieved_min"], g["targets"]["full/Q"]["achieved_max"])

    def test_boundary_outside_the_range_and_failures(self):
        """E(lambda) above the boundary on the whole registered grid (patched functionals): unreached and,
        with E_Q above its material threshold, NOT a material null: discarded. A nonfinite functional is a
        numerical failure."""
        cb = self.cb
        orig = cb.Panel.functionals
        cb.Panel.functionals = lambda self_, final=False: {"E_C": 0.02, "E_Q": 0.01, "R_C": 0.1414, "R_Q": 0.1,
                                                           "M_F": 1.4, "available": True}
        try:
            r = self.run_("F3", 1)
        finally:
            cb.Panel.functionals = orig
        self.assertEqual((r["status"], r["member"], r["role"], r["discard"]), ("unreached", False, "discarded", "non-member"))
        self.assertEqual([c["kind"] for c in r["clips"] if c["world"] == "panel"], ["unreached-below"])
        cb.Panel.functionals = lambda self_, final=False: {"E_C": math.nan, "E_Q": 0.0}
        try:
            r = self.run_("F3", 1)
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
            return self.run_(mode, 0)
        finally:
            cb.plan_world = orig

    def test_unreached_panel_goes_to_I_clipped_and_null_checked(self):
        """A capture RMS of 50 is above the maximum attained on the registered search: clipped to it; F1 (a
        detection null by construction) keeps it in I and analyses it."""
        r = self.with_target("F1", 50.0)
        self.assertEqual((r["status"], r["role"], r["member"]), ("unreached", "I", True))
        self.assertTrue(all(c["kind"] == "unreached-above" and c["nearest"] < 50.0 for c in r["clips"]))
        self.assertEqual(len({c["world"] for c in r["clips"]}), len(self.graph))
        self.assertEqual(r["targets"]["full/C"]["clipped"], len(self.graph))
        self.assertTrue(math.isfinite(r["score"]))

    def test_ht_membership_has_no_scientific_slack(self):
        """#68 round 4 P2-5: a member iff EVERY one of the six candidates has a margin <= TAU_NUM x its scale
        (1e-3: the solver accuracy); Codex's +0.025 scaled candidate is a genuine transition (not a member)."""
        cb = self.cb
        self.assertAlmostEqual(cb.TAU_NUM, 2 * cb.DIR_TOL / cb.stats.DELTA_Q)
        cands = [f"{a}->{f}" for a, f, _ in cb.transition.candidates()]
        ms = {c: {k: -1.0 * cb.MARGIN_SCALE[k] if k == "beta_P[a]" else 1.0 * cb.MARGIN_SCALE[k]
                  for k in cb.MARGIN_NAMES} for c in cands}
        self.assertEqual(cb.ht_membership(ms)[0], True)
        ms["E2->E3"] = {k: 1.0 * cb.MARGIN_SCALE[k] for k in cb.MARGIN_NAMES}
        ms["E2->E3"]["EF_Q[f]-dQ2"] = 0.025 * cb.MARGIN_SCALE["EF_Q[f]-dQ2"]          # (Codex: +0.025 scaled)
        ok, cand, val = cb.ht_membership(ms)
        self.assertEqual((ok, cand), (False, "E2->E3"))
        self.assertAlmostEqual(val, 0.025)
        ms["E2->E3"]["EF_Q[f]-dQ2"] = 0.5 * cb.TAU_NUM * cb.MARGIN_SCALE["EF_Q[f]-dQ2"]  # (a solver-pinned zero)
        self.assertEqual(cb.ht_membership(ms)[:2], (True, "E2->E3"))
        ms["E1->E2"]["beta_Q[a]"] = math.nan
        with self.assertRaises(cb.CalibError):
            cb.ht_membership(ms)

    def stream(self, stage, m, s_, cell, roles, score=lambda k: 0.001 * k):
        """One quota cell's ordered stream from a role list ("B", "I", "s" = an I-eligible surplus, "n" = a
        non-member, "f" = a B-eligible final-boundary failure)."""
        cb = self.cb
        n = {"dev": cb.N_DEV, "val": cb.N_VAL}[stage]
        out = []
        for k, ro in enumerate(roles):
            panel, st = cb.proposal_of("H-F", m, n, cell, k)
            kw = {"cell": cell, "k": k, "stream": st, "score": score(k)}
            if ro == "I":
                kw.update(role="I", eligible="I", status="unreached", score=5.0)
            elif ro == "s":
                kw.update(role="discarded", eligible="I", status="unreached", discard="surplus")
            elif ro == "n":
                kw.update(role="discarded", eligible=None, status="feasible", member=False, discard="non-member")
            elif ro == "f":
                kw.update(role="discarded", eligible="B", status="feasible", discard="final-boundary")
            out.append(rec("H-F", stage, m, s_, panel, self.man, **kw))
        return out

    def allocation(self, stage, special=None, score=None):
        cb = self.cb
        n = {"dev": cb.N_DEV, "val": cb.N_VAL}[stage]
        sc = score or ((lambda k: 0.001 * k) if stage == "dev" else (lambda k: 0.0))
        out = []
        for m, s_ in cb.strata_of("H-F"):
            got = special(m, s_, n) if special else None
            out.extend(got if got is not None else [rec("H-F", stage, m, s_, k, self.man, score=sc(k)) for k in range(n)])
        return out

    def test_crit_is_the_maximum_over_strata(self):
        """F1 actual, each level cell (n_c = 80): an audit of 60 B then 20 I (I-eligible fraction 0.25 x K 480 =
        120 >= 99: I collection), then the stream continues to 80 B and 80 I (k = 159, the registered stopping
        point). I = 160 >= 99: calibrated; its scores (5.0) set c_F, never pooled into B."""
        cb = self.cb

        def special(m, s_, n):
            if (m, s_) != ("F1", "actual"):
                return None
            return [r for c in ("lvl0", "lvl1") for r in self.stream("dev", m, s_, c, ["B"] * 60 + ["I"] * 20 + ["B"] * 20 + ["I"] * 60)]
        recs = self.allocation("dev", special)
        crit = cb.critical_values(recs)
        self.assertEqual(crit["strata"]["H-F|F1|actual|I"]["n"], 160)
        self.assertEqual(crit["strata"]["H-F|F1|actual|I"]["score"], 5.0)
        self.assertEqual(crit["c_F"], 5.0)
        self.assertEqual(crit["strata_set"]["H-F|F1|actual"], ["B", "I"])
        pr = crit["proposals"]["H-F|F1|actual"]
        self.assertTrue(pr["I_calibrated"] and pr["collect_I"])
        self.assertAlmostEqual(pr["audit"]["q_I"]["q_hat"], 40 / 160)
        # the registered stream is enforced: a gap, a stop before the stopping point, a surplus before full
        with self.assertRaises(cb.CalibError):
            cb.critical_values([r for r in recs if not (r["mode"] == "F1" and r.get("cell") == "lvl0" and r["k"] == 100)])
        with self.assertRaises(cb.CalibError):
            cb.critical_values([r for r in recs if not (r["mode"] == "F1" and r.get("cell") == "lvl1" and r["k"] >= 150)])
        bad = [dict(r, role="discarded", discard="surplus") if (r["mode"] == "F1" and r.get("cell") == "lvl0" and r["k"] == 85)
               else r for r in recs]
        with self.assertRaises(cb.CalibError):
            cb.critical_values(bad)

    def test_cap_exhaustion_makes_the_mode_unavailable(self):
        """F2 actual, cell lvl1: 79 B in its audit and none after, the stream run to its cap K_c = 240 (the I
        surplus once I is full): CAPPED, every decision needing F2 unavailable (None, never a non-rejection);
        I = 80 < 99: not calibrated."""
        cb = self.cb

        def special(m, s_, n):
            if (m, s_) != ("F2", "actual"):
                return None
            return (self.stream("dev", m, s_, "lvl0", ["B"] * 80)
                    + self.stream("dev", m, s_, "lvl1", ["B"] * 79 + ["I"] + ["I"] * 79 + ["s"] * 81))
        crit = cb.critical_values(self.allocation("dev", special))
        self.assertIn("H-F|F2|actual", crit["unavailable"])
        self.assertEqual(crit["proposals"]["H-F|F2|actual"]["capped"], ["lvl1"])
        self.assertEqual((crit["c_F"], crit["c_M"]), (None, None))
        self.assertTrue(all(v is None for v in crit["c_E"].values()))
        acc = cb.acceptance(self.allocation("val"), crit)
        self.assertFalse(acc["pass"]["H-F detection"] or acc["pass"]["H-F material"])
        with self.assertRaises(cb.CalibError):
            cb.freeze_gates(crit, acc)

        def short(m, s_, n):                                                  # (a stream stopped short of its cap)
            got = special(m, s_, n)
            return None if got is None else [r for r in got if not (r.get("cell") == "lvl1" and r["k"] >= 200)]
        with self.assertRaises(cb.CalibError):
            cb.critical_values(self.allocation("dev", short))

    def test_stratum_set_is_frozen_at_dev(self):
        """#68 round 4 P2-7: an I not calibrated at dev is never rated at validation (the scope limitation,
        with the audit's uncovered classes, carries through); an I calibrated at dev but short at validation
        fails its decisions ("unvalidated")."""
        cb = self.cb
        crit = cb.critical_values(self.allocation("dev"))
        self.assertEqual(crit["strata_set"]["H-F|F3|actual"], ["B"])

        def val_I(m, s_, n):                                               # (F3 val: 500 audit I, I collection)
            if (m, s_) != ("F3", "actual"):
                return None
            return self.stream("val", m, s_, "all", ["B"] * 500 + ["I"] * 500 + ["B"] * 500 + ["I"] * 500,
                               score=lambda k: 0.0)
        acc = cb.acceptance(self.allocation("val", val_I), crit)
        self.assertNotIn("material|F3|actual|I", acc["rates"]["H-F"])
        sc = acc["scope"]["H-F|F3|actual"]
        self.assertEqual((sc["uncovered_null_classes"]["I_eligible"], sc["audit_n"]), (500, 1000))
        self.assertGreater(sc["q_uncovered_U"], 0.5)
        self.assertIn("material", sc["bounds"])

        def dev_I(m, s_, n):
            if (m, s_) != ("F3", "actual"):
                return None
            return self.stream("dev", m, s_, "all", ["B"] * 100 + ["I"] * 60 + ["B"] * 60 + ["I"] * 100)
        crit2 = cb.critical_values(self.allocation("dev", dev_I))
        self.assertEqual(crit2["strata_set"]["H-F|F3|actual"], ["B", "I"])
        acc2 = cb.acceptance(self.allocation("val"), crit2)
        self.assertIn("H-F|F3|actual", acc2["unvalidated"])
        self.assertFalse(acc2["pass"]["H-F material"])
        self.assertTrue(acc2["pass"]["H-F detection"])                    # (F3 is not a detection mode)
        with self.assertRaises(cb.CalibError):
            cb.acceptance(self.allocation("val"), {k: v for k, v in crit.items() if k != "strata_set"})

    def test_cell_stop_and_quota_cells(self):
        cb = self.cb
        self.assertEqual(sorted(cb.cells_of("H-F", "F1", 160)), ["lvl0", "lvl1"])
        self.assertEqual(len(cb.cells_of("H-T", "T4", 160)), 96)
        self.assertEqual(cb.proposal_of("H-F", "F1", 160, "lvl1", 3), (7, None))
        self.assertEqual(cb.proposal_of("H-F", "F1", 160, "lvl1", 80), (1, "lvl1/80"))
        with self.assertRaises(cb.CalibError):
            cb.proposal_of("H-F", "F1", 160, "lvl1", 240)
        cx = [{"k": k, "role": r} for k, r in enumerate(["B", "I", "B", "B"])]
        self.assertEqual(cb.cell_stop(cx, 3, False), 3)
        self.assertIsNone(cb.cell_stop(cx, 3, True))

    def test_cpu_ledger(self):
        import tempfile
        cb = self.cb
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "cpu.jsonl")
            cb.ledger_add(p, {"kind": "panels", "cpu_s": 3600.0})
            cb.ledger_add(p, {"kind": "fitting", "cpu_s": 7200.0})
            t = cb.ledger_total([p])
            self.assertAlmostEqual(t["cpu_h"], 3.0)
            self.assertAlmostEqual(t["remaining_h"], cb.stats.CPU_CEILING_H - 3.0)
            self.assertEqual(t["by_kind_h"], {"fitting": 2.0, "panels": 1.0})
        finally:
            import shutil
            shutil.rmtree(d)


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

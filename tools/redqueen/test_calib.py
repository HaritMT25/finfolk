#!/usr/bin/env python3
"""test_calib.py: the Annex H calibration generator and harness (calib.py, H.9-H.12) on a small synthetic
graph. Covers:
  * whole H-F and H-T panels run, finite and deterministic;
  * the q33 speed-ups equal their reference routes: the cached loading sparsity (Panel.cov) against the
    direct construction, the amplitude solver's RMS (recurrence.ref_rms) against RefDesign.readout;
  * the H-T analysis pairs worlds by id.
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
         "available": True, "score": 0.0}
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
        self.assertEqual(hi["rates"]["H-F"]["detection|F0|actual"]["fp"], 1000)
        self.assertFalse(hi["pass"]["H-F detection"])
        lo = cb.acceptance(self.allocation("H-F", "val", cb.N_VAL, score=lambda m, s, k: 0.0), crit)
        self.assertTrue(lo["pass"]["H-F detection"] and lo["pass"]["H-F material"])
        self.assertTrue(all(lo["pass"][f"gate {e}"] for e in ("E1", "E2", "E3")))
        self.assertEqual(len(lo["ptables"]["H-F detection"]["F0|actual"]), 1000)
        # 12 false positives pass, 13 fail (the frozen rule, exactly counted)
        def sc(n):
            return lambda m, s, k: (5.0 if (m == "F1" and s == "actual" and k < n) else 0.0)
        self.assertTrue(cb.acceptance(self.allocation("H-F", "val", cb.N_VAL, score=sc(12)), crit)["pass"]["H-F detection"])
        self.assertFalse(cb.acceptance(self.allocation("H-F", "val", cb.N_VAL, score=sc(13)), crit)["pass"]["H-F detection"])
        un = self.allocation("H-F", "val", cb.N_VAL, score=lambda m, s, k: 5.0, available=False)
        self.assertEqual(cb.acceptance(un, crit)["rates"]["H-F"]["detection|F0|actual"]["fp"], 0)
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
        self.assertEqual(acc["rates"]["H-F"]["material|F3|actual"]["fp"], 1000)
        self.assertEqual(acc["rates"]["H-F"]["material|F4|actual"]["fp"], 0)

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

    def test_power_and_non_success(self):
        cb = self.cb
        crit = {"c_F": 1.0, "c_M": 1.0, "c_T": 7.0}
        alt = [rec("H-T", "alt", "TA1", "actual", k, self.man, score=9.0, direction="ARD->FSD" if k % 2 == 0 else
                   "FSD->ARD", non_success=(k == 0)) for k in range(100)]
        pw = cb.power(alt, crit)["H-T|TA1|actual"]
        self.assertEqual((pw["n"], pw["success"]["rejection"], pw["non_success"]), (100, 99, 1))
        self.assertEqual(pw["by_direction"]["ARD->FSD"], {"n": 50, "success": 49, "wilson95": cb.wilson(49, 50)})


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

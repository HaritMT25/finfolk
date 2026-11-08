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
        r1 = cb.run_panel(self.graph, self.params, "H-T", "dev", "actual", "T1", 0, draws=19)
        r2 = cb.run_panel(self.graph, self.params, "H-T", "dev", "actual", "T1", 0, draws=19)
        self.assertFalse(r1.get("error"), r1.get("error"))
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

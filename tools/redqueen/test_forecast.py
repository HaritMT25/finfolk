#!/usr/bin/env python3
"""test_forecast.py: the Level-2 linear forecasts (forecast.py, design v4 §10.6). Covers the three
forecasters (persistence; the GLS drift, exact on a line; the regularized linear state-space model recovering
a known system by EM, its LAMBDA chosen on validation), the window and extinction rules, the evaluation
arithmetic against futures with KNOWN conditional distributions (MSE, V_fork and REDUCIBLE = MSE - V_fork,
measurement-corrected; extinct futures excluded and counted; the original continuation as a sensitivity),
the energy score and calibration, the chi-square CDF, and the sealing contract of the CLI (evaluation only
under the committed predictions' sha256). numpy required.

    python3 -I tools/redqueen/test_forecast.py [-v]
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
import forecast as fc  # noqa: E402
import rqlib  # noqa: E402
try:
    import numpy as np  # noqa: E402
except ImportError:
    if os.environ.get("RQ_REQUIRE_NUMPY"):
        raise SystemExit("RQ_REQUIRE_NUMPY is set, but numpy cannot be imported")
    np = None

A_TRUE = [[0.85, 0.10], [-0.05, 0.90]]
C_TRUE = [0.05, -0.02]
Q_TRUE = [[0.010, 0.002], [0.002, 0.008]]
R_MEAS = 0.002


def simulate(seed=1, n_worlds=(8, 4, 4), T=40, extinct=None):
    """Native 1M profile series from a known linear system (d = 2) with covariates (abundance etc.) that do
    not enter the dynamics; measurement covariance R_MEAS I."""
    rng = np.random.default_rng(seed)
    A, c, Q = np.array(A_TRUE), np.array(C_TRUE), np.array(Q_TRUE)
    L = np.linalg.cholesky(Q)
    worlds = {}
    k = 0
    for split, n in zip(fc.SPLITS, n_worlds):
        for _ in range(n):
            w = f"w{k:02d}"
            k += 1
            z = rng.normal(0, 0.3, 2)
            ser = []
            for t in range(1, T + 1):
                ext = extinct is not None and w in extinct and t >= extinct[w]
                if ext:
                    ser.append({"t": t, "extinct": True})
                    continue
                y = z + math.sqrt(R_MEAS) * rng.standard_normal(2)
                ser.append({"t": t, "z": y.tolist(), "cov": (R_MEAS * np.eye(2)).tolist(),
                            "covariates": {"abundance_prey": float(rng.uniform(300, 600)),
                                           "abundance_pred": float(rng.uniform(4, 12)), "energy": float(rng.normal()),
                                           "turnover": float(rng.uniform(0, 1))}})
                z = A @ z + c + L @ rng.standard_normal(2)
            worlds[w] = {"split": split, "block": k % 4, "series": ser}
    return {"schema": fc.PROFILES, "dim": 2, "worlds": worlds}


@unittest.skipIf(np is None, "numpy is not installed")
class TestForecasters(unittest.TestCase):
    def test_persistence_drift_and_window(self):
        doc = simulate(T=12)
        worlds, d = fc.load_profiles(doc)
        W = dict(worlds["w00"])
        W["z"] = np.array([[0.1 * t, 1.0 - 0.2 * t] for t in W["t"]])        # (an exact line)
        idx = fc.window(W, 8)
        self.assertEqual([int(W["t"][i]) for i in idx], [4, 5, 6, 7, 8])
        self.assertTrue(np.allclose(fc.drift(W, idx, 3), [1.1, 1.0 - 2.2], atol=1e-9))
        self.assertTrue(np.allclose(fc.persistence(W, idx, 3), W["z"][idx[-1]]))
        self.assertIsNone(fc.window(W, 3))                                   # (t0 - 4 < 1)
        doc2 = json.loads(json.dumps(doc))
        del doc2["worlds"]["w01"]["series"][5]                               # (t = 6 missing)
        w2, _ = fc.load_profiles(doc2)
        self.assertIsNone(fc.window(w2["w01"], 8))
        bad = json.loads(json.dumps(doc))
        bad["worlds"]["w02"]["series"][3] = {"t": 4, "extinct": True}         # (a live profile after it)
        with self.assertRaises(fc.ForecastError):
            fc.load_profiles(bad)
        bad = json.loads(json.dumps(doc))
        bad["worlds"]["w02"]["series"][3]["covariates"].pop("energy")
        with self.assertRaises(fc.ForecastError):
            fc.load_profiles(bad)

    def test_state_space_recovers_a_known_system(self):
        """EM on the training worlds recovers A, c and Q of the simulated system; LAMBDA is chosen on the
        validation worlds from the registered grid; its forecasts beat persistence there."""
        worlds, d = fc.load_profiles(simulate(seed=2, n_worlds=(10, 4, 2), T=60))
        model = fc.fit_all(worlds, d, horizons=(1, 4), primary=4, lambdas=(0.1, 10.0))
        m = model["lss"]
        self.assertIn(model["lambda"], (0.1, 10.0))
        self.assertLess(float(np.max(np.abs(m.Th[:, :2] - np.array(A_TRUE)))), 0.12, m.Th)
        self.assertLess(float(np.max(np.abs(m.Q - np.array(Q_TRUE)))), 0.006, m.Q)
        lss = fc.corrected_mse(worlds, "validation", 4, lambda W, idx, H: m.forecast(W, idx, H)[0])[0]
        per = fc.corrected_mse(worlds, "validation", 4, fc.persistence)[0]
        self.assertLess(lss, per)
        for name in ("persistence", "drift"):
            P = model["covs"][name][4]
            self.assertGreaterEqual(float(np.min(np.linalg.eigvalsh(P))), -1e-12)

    def test_chi2(self):
        self.assertAlmostEqual(fc.chi2_cdf(2.0, 2), 1 - math.exp(-1), places=12)
        self.assertAlmostEqual(fc.chi2_cdf(3.841458820694124, 1), 0.95, places=9)
        self.assertAlmostEqual(fc.chi2_cdf(30.0, 4), 1 - math.exp(-15) * (1 + 15), places=12)


def futures_for(origins, mu_fn, Sc, meas, n_reseed=4, seed=5, extinct_every=None):
    """Futures with a KNOWN conditional distribution N(mu, Sc), each measured with noise meas I."""
    rng = np.random.default_rng(seed)
    L = np.linalg.cholesky(np.array(Sc))
    out = []
    for k, (w, t0, H) in enumerate(origins):
        fs = []
        for j in range(n_reseed + 1):
            if extinct_every and k % extinct_every == 0 and j == 0:
                fs.append({"kind": "reseed", "extinct": True})
                continue
            z = mu_fn(w, t0, H) + L @ rng.standard_normal(2) + math.sqrt(meas) * rng.standard_normal(2)
            fs.append({"kind": "reseed" if j < n_reseed else "original", "z": z.tolist(),
                       "cov": (meas * np.eye(2)).tolist()})
        out.append({"world": w, "t0": t0, "horizon": H, "futures": fs})
    return {"schema": fc.FUTURES, "origins": out}


@unittest.skipIf(np is None, "numpy is not installed")
class TestEvaluation(unittest.TestCase):
    def test_arithmetic_on_known_futures(self):
        """With futures drawn from N(mu, Sc) and measured with noise: the pooled V_fork estimates tr Sc, the
        exact forecast's REDUCIBLE is about 0 and an offset forecast's about ||delta||^2 (measurement-corrected,
        negatives allowed); extinct futures are excluded and counted; the correct forecast has the lower energy
        score and calibrated coverage."""
        origins = [(f"w{k % 12:02d}", 10 + k, 10) for k in range(360)]
        Sc = [[0.04, 0.01], [0.01, 0.03]]

        def mu(w, t0, H):
            return np.array([0.01 * t0, -0.02 * int(w[1:])])
        fut = futures_for(origins, mu, Sc, meas=0.01, extinct_every=7)
        delta = np.array([0.15, -0.1])
        preds = []
        for w, t0, H in origins:
            m = mu(w, t0, H)
            cov = (np.array(Sc)).tolist()
            preds.append({"world": w, "t0": t0, "horizon": H, "available": True, "forecasts": {
                "persistence": {"z": (m + delta).tolist(), "cov": cov}, "drift": {"z": m.tolist(), "cov": cov},
                "lss": {"z": m.tolist(), "cov": (4 * np.array(Sc)).tolist()}}})
        ev = fc.evaluate({"dim": 2, "origins": preds}, fut, boot=99)
        P = ev["pooled"]
        tr = 0.07
        self.assertAlmostEqual(P["drift@10"]["v_fork"], tr, delta=0.008)
        self.assertAlmostEqual(P["drift@10"]["reducible"], 0.0, delta=0.008)
        self.assertAlmostEqual(P["persistence@10"]["reducible"], float(delta @ delta), delta=0.01)
        lo, hi = P["drift@10"]["ci95"]["reducible"]
        self.assertTrue(lo <= 0.0 <= hi)
        o0 = ev["origins"][0]["metrics"]["drift"]
        self.assertEqual((o0["extinct"], o0["reseeds"]), (1, 3))
        self.assertIsNotNone(o0["with_original"]["mse"])
        drift_es = np.mean([r["metrics"]["drift"]["energy"] for r in ev["origins"]])
        pers_es = np.mean([r["metrics"]["persistence"]["energy"] for r in ev["origins"]])
        self.assertLess(drift_es, pers_es)
        c50 = np.mean([r["metrics"]["drift"]["cover50"] for r in ev["origins"]])
        c90 = np.mean([r["metrics"]["drift"]["cover90"] for r in ev["origins"]])
        self.assertAlmostEqual(c50, 0.5, delta=0.05)
        self.assertAlmostEqual(c90, 0.9, delta=0.04)
        wide90 = np.mean([r["metrics"]["lss"]["cover90"] for r in ev["origins"]])
        self.assertGreater(wide90, 0.97)                                     # (over-wide: over-covers)
        rqlib.canonical(ev)                                                  # (no Infinity / NaN)

    def test_cli_predict_commit_evaluate(self):
        """predict fits, selects and writes every origin's forecasts; evaluate refuses any sha256 but the
        committed one; unavailable origins (no complete live window) are recorded, never forecast."""
        tmp = tempfile.mkdtemp()
        try:
            prof = simulate(seed=4, n_worlds=(6, 3, 3), T=30, extinct={"w11": 25})
            origins = [(w, 12, 10) for w in sorted(prof["worlds"])] + [("w11", 26, 1)]
            fut = futures_for(origins, lambda w, t0, H: np.zeros(2), [[0.02, 0], [0, 0.02]], 0.002)
            pp = os.path.join(tmp, "p.json")
            fp = os.path.join(tmp, "f.json")
            out = os.path.join(tmp, "pred.json")
            for p, o in ((pp, prof), (fp, fut)):
                with open(p, "w") as f:
                    json.dump(o, f)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(fc.main(["predict", "--profiles", pp, "--futures", fp, "--out", out]), 0)
            pred = rqlib.read_json(out)
            self.assertEqual(pred["profiles_sha256"], rqlib.canonical_sha(prof))
            last = pred["origins"][-1]
            self.assertFalse(last["available"])
            sha = rqlib.sha256_file(out)
            ev = os.path.join(tmp, "ev.json")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(fc.main(["evaluate", "--predictions", out, "--pred-sha", "0" * 64, "--futures", fp,
                                          "--boot", "9", "--out", ev]), 2)
                self.assertEqual(fc.main(["evaluate", "--predictions", out, "--pred-sha", sha, "--futures", fp,
                                          "--boot", "9", "--out", ev]), 0)
                self.assertEqual(fc.main(["evaluate", "--predictions", os.path.join(tmp, "none"), "--pred-sha", sha,
                                          "--futures", fp, "--out", ev]), 2)
            e = rqlib.read_json(ev)
            self.assertEqual(e["predictions_sha256"], sha)
            self.assertEqual(e["pooled"]["lss@10"]["origins"], 12)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()

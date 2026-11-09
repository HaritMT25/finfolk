#!/usr/bin/env python3
"""test_forecast.py: the Level-2 linear forecasts (forecast.py, design v4 §10.6, §7.1-7.3).

NUMERICS (known answers): the registered initial-state prior conditions on y(0) exactly once (diffuse: the
scalar R = Q = 1 posterior variance is 1, not 2/3; a three-step smoother equals direct Gaussian conditioning);
the penalized EM's M-step is the exact maximizer of its penalized objective (perturbations, and the Q
update with its penalty term against the one without), equals augmented least squares on fully observed
data, reaches Theta0 under strong regularization, and the penalized objective never decreases; the
forecasters' gains are exact; a SHARED measurement error in the inputs and the futures gives the latent MSE
(Codex's counterexample: observed error 0, corrected MSE tr S, never negative); the evaluation arithmetic
on futures with known laws (V_fork, REDUCIBLE, one surviving reseed, extinct and unavailable futures).
PIPELINE against a real split manifest (sealing.manifest with the fork registry), the fork registry and
sealing's commitments and freeze: register -> predict-candidates -> commit -> score-validation (lambda the
argmin over the registered selection set) -> open-validation -> predict-test -> commit -> freeze ->
evaluate-test, every category reported on its own. LEAKAGE GUARDS: fit rows past the cutoff, of held-out
worlds, held-out snapshots, branches or with labels; map / reference provenance; prefix rows outside the
registered windows; target rows of another stage, missing or substituted; the commitment (no marker, other
bytes, no selection record, another model, no freeze, verified bytes consumed); the fork panel (missing,
unregistered, aliased branches; explicit unavailable; invalid covariances). numpy required.

    python3 -I tools/redqueen/test_forecast.py [-v]
"""
from __future__ import annotations

import contextlib
import gzip
import io
import json
import math
import os
import shutil
import sys
import tempfile
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
import forecast as fc  # noqa: E402
import rqlib  # noqa: E402
import sealing  # noqa: E402
try:
    import numpy as np  # noqa: E402
except ImportError:
    if os.environ.get("RQ_REQUIRE_NUMPY"):
        raise SystemExit("RQ_REQUIRE_NUMPY is set, but numpy cannot be imported")
    np = None

M = 1_000_000
A_TRUE = [[0.85, 0.10], [-0.05, 0.90]]
C_TRUE = [0.05, -0.02]
Q_TRUE = [[0.010, 0.002], [0.002, 0.008]]
S_SH, R_OWN = 0.001, 0.002                     # shared (per root world) and own measurement variances
TRAIN = [f"T{k:02d}" for k in range(8)]
VAL, TEST = ["V0", "V1", "V2"], ["S0", "S1", "S2"]
SPLIT = dict({w: "train" for w in TRAIN}, **{w: "val" for w in VAL}, **{w: "test" for w in TEST}, A1="train")
FORK, ORIG, SEEDS = ["T00", "V0", "S0", "S1"], [30, 100, 185], 4
HOLD = {"T00:34": "val", "T01:40": "val", "T02:150": "test", "T03:195": "val"}
UUIDS = {w: str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:redqueen:ns-main:{w}")) for w in sorted(SPLIT)}
MAP = {"cutoff": 120, "fit_sha256": "a" * 64, "references": {"sha256": "b" * 64, "max_frame": 120 * M}}
COVS = ["abundance_prey", "energy"]


def bid(w, t0, k):
    return f"{w}.o{t0}M.s{k}"


def buuid(b):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:fork:ns-forks:{b}"))


def wr(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(data if isinstance(data, str) else json.dumps(data))


def config(**over):
    cfg = {"schema": fc.CFG_SCHEMA, "channels": ["rq0", "rq1"], "events": ["extinction"], "covariates": COVS,
           "window": 5, "horizons": [1, 4, 10], "primary": 10,
           "temporal": {"fit_through": 120, "validation": [141, 160], "test": [181, 200], "separation": 20},
           "map": {"cutoff": 120, "reference_frame_max": None},
           "lss": {"lambdas": [0.1, 100.0], "initial_state": {"kind": "diffuse"}, "em_iters": 400, "em_tol": 1e-7},
           "evaluation": {"bootstrap": 99, "energy_draws": 200, "seed_namespace": "test-forecast"}}
    for k, v in over.items():
        cfg[k] = dict(cfg[k], **v) if isinstance(v, dict) and isinstance(cfg.get(k), dict) else v
    return cfg


def make_root(tmp, cfg_over=None, register=True):
    """A study's graph + registry + fork registry -> the split manifest; a commitment root holding it, the
    fork registry and the registered forecast configuration."""
    g = os.path.join(tmp, "graph")
    wr(os.path.join(g, "graph.meta.json"), {"schema": "finfolk.redqueen.graph/1", "namespace": "ns", "edges_sha256": "e" * 64,
                                            "split": SPLIT, "holdout": HOLD, "fork": FORK, "intensive": []})
    with gzip.open(os.path.join(g, "graph.jsonl.gz"), "wt") as f:
        f.write(json.dumps({"family": "within", "prey": "Q:T03:9", "pred": "P:T04:9", "role": "training"}) + "\n")
    wr(os.path.join(tmp, "worlds.json"), {"namespace": "ns-main", "worlds": [{"id": w, "uuid": UUIDS[w]} for w in sorted(SPLIT)]})
    br = [{"id": bid(w, t0, k), "uuid": buuid(bid(w, t0, k)), "kind": "main", "root": w, "root_uuid": UUIDS[w],
           "origin": {"frame": t0 * M, "k": k}} for w in FORK for t0 in ORIG for k in range(SEEDS)]
    br.append({"id": "V1.p50M.s0", "uuid": buuid("V1.p50M.s0"), "kind": "pilot", "root": "V1", "root_uuid": UUIDS["V1"],
               "origin": {"frame": 50 * M, "k": 0}})
    forks = {"schema": fc.FORKS_SCHEMA, "namespace": "ns-forks", "horizon": 10 * M, "seeds": SEEDS,
             "origins": [t * M for t in ORIG], "fork_worlds": FORK, "native_panel": sorted(TRAIN + VAL + TEST), "worlds": br}
    fp = os.path.join(tmp, "forks.json")
    wr(fp, rqlib.canonical(forks).decode())
    root = os.path.join(tmp, "root")
    man = rqlib.canonical(sealing.manifest(os.path.join(g, "graph.meta.json"), os.path.join(tmp, "worlds.json"), fp))
    sealing.publish_manifest(root, man)
    wr(os.path.join(root, "config", "forks.json"), rqlib.canonical(forks).decode())
    cfg = config(**(cfg_over or {}))
    cfg.update(split_manifest_sha256=rqlib.sha256_bytes(man), forks_sha256=rqlib.sha256_file(fp))
    cp = os.path.join(tmp, "forecast_cfg.json")
    wr(cp, cfg)
    if register:
        fc.register(root, cp)
    return root, cp


def simulate(seed=7):
    """Every native row (T, V, S worlds, t = 0 .. 200) and every fork branch's rows (+1, +4, +10) from the known
    linear system; measured with a shared per-root component (group g:<root>) plus own noise. S2 goes extinct
    at 190; branch S1.o185M.s2 is extinct at 195; S0.o185M.s3's +4 assay is unavailable."""
    rng = np.random.default_rng(seed)
    A, c, L = np.array(A_TRUE), np.array(C_TRUE), np.linalg.cholesky(np.array(Q_TRUE))
    zbar = np.linalg.solve(np.eye(2) - A, c)
    rows, truth, us = {}, {}, {}

    def meas(w, root, t, z):
        return {"world": w, "t": t, "uuid": UUIDS.get(w) or buuid(w), "z": (z + us[root] + math.sqrt(R_OWN) * rng.standard_normal(2)).tolist(),
                "cov": ((S_SH + R_OWN) * np.eye(2)).tolist(), "meas_group": f"g:{root}",
                "covariates": {"abundance_prey": float(rng.uniform(300, 600)), "energy": float(rng.normal())},
                "events": {"extinction": False}}
    for w in sorted(TRAIN + VAL + TEST):
        us[w] = math.sqrt(S_SH) * rng.standard_normal(2)
        z = zbar + 0.2 * rng.standard_normal(2)
        for t in range(0, 201):
            truth[(w, t)] = z
            rows[(w, t)] = ({"world": w, "t": t, "events": {"extinction": True}} if w == "S2" and t >= 190
                            else meas(w, w, t, z))
            z = A @ z + c + L @ rng.standard_normal(2)
    for w in FORK:
        for t0 in ORIG:
            for k in range(SEEDS):
                b, z = bid(w, t0, k), truth[(w, t0)]
                for h in range(1, 11):
                    z = A @ z + c + L @ rng.standard_normal(2)
                    if h in (1, 4, 10):
                        rows[(b, t0 + h)] = meas(b, w, t0 + h, z)
    rows[(bid("S1", 185, 2), 195)] = {"world": bid("S1", 185, 2), "t": 195, "events": {"extinction": True}}
    rows[(bid("S0", 185, 3), 189)] = {"world": bid("S0", 185, 3), "t": 189, "unavailable": "assay failed"}
    return rows


def doc(rows, **over):
    d = {"schema": fc.PROFILES, "channels": ["rq0", "rq1"], "map": MAP,
         "measurement": {"shared": {f"g:{w}": (S_SH * np.eye(2)).tolist() for w in sorted(TRAIN + VAL + TEST)}},
         "rows": rows}
    d.update(over)
    return d


def fit_rows(rows, man):
    return [rows[(w, t)] for w in TRAIN for t in range(0, 121) if sealing.node_role(man, w, t * M if t else 1) == "training"]


def run(args):
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        rc = fc.main(args)
    return rc, err.getvalue()


@unittest.skipIf(np is None, "numpy is not installed")
class TestNumerics(unittest.TestCase):
    def test_initial_state_conditioned_once(self):
        """P2-9: the diffuse prior conditions on y(0) exactly once (posterior variance R = 1, not 2/3); a
        proper prior N(0, 2) conditioned once gives 2/3; a three-step RTS smoother equals direct Gaussian
        conditioning (means, variances, lag-one covariances, the diffuse log-likelihood)."""
        m = fc.LSS(1, 0, 1.0, [], [], {"kind": "diffuse"})
        m.Th, m.Q = np.array([[1.0, 0.0]]), np.array([[1.0]])
        z, R, x = np.array([[[0.7]]]), np.array([[[[1.0]]]]), np.zeros((1, 1, 0))
        mf, Pf, _, _, ll, _ = m.filter(z, R, x)
        self.assertEqual((float(mf[0, 0, 0]), float(Pf[0, 0, 0, 0]), float(ll[0])), (0.7, 1.0, 0.0))
        p = fc.LSS(1, 0, 1.0, [], [], {"kind": "proper", "mean": [0.0], "cov": [[2.0]]})
        p.Th, p.Q = m.Th, m.Q
        mf, Pf, _, _, _, _ = p.filter(z, R, x)
        self.assertAlmostEqual(float(Pf[0, 0, 0, 0]), 2 / 3, places=14)
        self.assertAlmostEqual(float(mf[0, 0, 0]), 0.7 * 2 / 3, places=14)
        a, c, q = 0.8, 0.1, 0.5
        Rs, y = [1.0, 0.6, 0.3], [0.2, -0.4, 1.1]
        m.Th, m.Q = np.array([[a, c]]), np.array([[q]])
        ms, Ps, C, ll = m.smooth(np.array(y).reshape(1, 3, 1), np.array(Rs).reshape(1, 3, 1, 1), np.zeros((1, 3, 0)))
        mu = np.array([y[0], a * y[0] + c, a * (a * y[0] + c) + c])     # z | y(0): z0 ~ N(y0, R0), then the dynamics
        v1 = a * a * Rs[0] + q
        S = np.array([[Rs[0], a * Rs[0], a * a * Rs[0]], [a * Rs[0], v1, a * v1], [a * a * Rs[0], a * v1, a * a * v1 + q]])
        Hm = np.array([[0.0, 1, 0], [0, 0, 1]])
        Sy = Hm @ S @ Hm.T + np.diag(Rs[1:])
        K = S @ Hm.T @ np.linalg.inv(Sy)
        post_m, post_S = mu + K @ (np.array(y[1:]) - Hm @ mu), S - K @ Hm @ S
        self.assertTrue(np.allclose(ms[0, :, 0], post_m, atol=1e-12))
        self.assertTrue(np.allclose(Ps[0, :, 0, 0], np.diag(post_S), atol=1e-12))
        self.assertAlmostEqual(float(C[0, 1, 0, 0]), post_S[1, 0], places=12)
        self.assertAlmostEqual(float(C[0, 2, 0, 0]), post_S[2, 1], places=12)
        r = np.array(y[1:]) - Hm @ mu
        want = -0.5 * (r @ np.linalg.solve(Sy, r) + np.linalg.slogdet(Sy)[1] + 2 * math.log(2 * math.pi))
        self.assertAlmostEqual(float(ll[0]), want, places=12)

    def _series(self, n=300, seed=3, R=0.0):
        rng = np.random.default_rng(seed)
        A, c, L = np.array(A_TRUE), np.array(C_TRUE), np.linalg.cholesky(np.array(Q_TRUE))
        z = np.zeros(2)
        Z, X = [], []
        for _ in range(n):
            Z.append(z + math.sqrt(R) * rng.standard_normal(2) if R else z)
            X.append([rng.normal(), rng.uniform(0, 1)])
            z = A @ z + c + L @ rng.standard_normal(2)
        Rm = np.broadcast_to((R if R else 1e-14) * np.eye(2), (n, 2, 2))
        X = np.array(X)
        return np.array(Z)[None], np.array(Rm)[None], X[None], X.mean(axis=0), X.std(axis=0)

    def test_penalized_em(self):
        """P2-8: (a) the M-step maximizes the penalized expected complete-data objective (random
        perturbations; the Q update without lambda (Theta - Theta0) D (Theta - Theta0)' is worse); (b) on fully
        observed data the fit equals augmented least squares (rows sqrt(lambda) e_j -> sqrt(lambda) Theta0_j) and
        its Q the augmented residual scatter / n; strong regularization gives Theta0 (A = I, B = 0) with the
        mean increment as intercept; (c) the penalized objective never decreases over the EM iterations."""
        z, R, x, mu, sd = self._series(R=0.003)
        m = fc.LSS(2, 2, 5.0, mu, sd, {"kind": "diffuse"})
        m.Th = np.hstack([np.array(A_TRUE), np.zeros((2, 3))])
        m.Q = np.array(Q_TRUE)
        S00, S10, S11, n, _ = m.estep([(z, R, x)])
        m.mstep(S00, S10, S11, n)
        _, D, Th0 = m.penalty()

        def obj(Th, Q, lam=5.0):
            E = Th - Th0
            sc = S11 - Th @ S10.T - S10 @ Th.T + Th @ S00 @ Th.T + lam * E @ D @ E.T
            return -0.5 * n * np.linalg.slogdet(Q)[1] - 0.5 * np.trace(np.linalg.solve(Q, sc))
        best = obj(m.Th, m.Q)
        rng = np.random.default_rng(1)
        for _ in range(20):
            dT = 1e-3 * rng.standard_normal(m.Th.shape)
            dQ = 1e-4 * rng.standard_normal((2, 2))
            self.assertLess(obj(m.Th + dT, m.Q), best)
            self.assertLess(obj(m.Th, m.Q + (dQ + dQ.T) / 2), best)
        E = m.Th - Th0
        Q_nopen = (S11 - m.Th @ S10.T - S10 @ m.Th.T + m.Th @ S00 @ m.Th.T) / n
        self.assertLess(obj(m.Th, Q_nopen), best - 1e-6)
        self.assertGreater(np.max(np.abs(Q_nopen - m.Q)), 1e-6)
        # (b) fully observed: augmented least squares
        z, R, x, mu, sd = self._series(R=0.0)
        for lam in (50.0, 1e9):
            f = fc.LSS(2, 2, lam, mu, sd, {"kind": "diffuse"}).fit([(z, R, x)], 20, 1e-10)
            Phi = np.hstack([z[0, :-1], (x[0, :-1] - mu) / sd, np.ones((len(z[0]) - 1, 1))])
            Y = z[0, 1:]
            aug = np.vstack([Phi, math.sqrt(lam) * np.eye(5)[:4]])
            tgt = np.vstack([Y, math.sqrt(lam) * np.hstack([np.eye(2), np.zeros((2, 3))]).T[:4]])
            Th = np.linalg.lstsq(aug, tgt, rcond=None)[0].T
            res = tgt - aug @ Th.T
            self.assertTrue(f.converged)
            self.assertTrue(np.allclose(f.Th, Th, atol=1e-7), (lam, f.Th, Th))
            self.assertTrue(np.allclose(f.Q, res.T @ res / len(Y), atol=1e-8), (lam, f.Q))
        self.assertLess(np.max(np.abs(f.Th[:, :2] - np.eye(2))), 1e-6)       # (lambda 1e9: A = I, B = 0)
        self.assertLess(np.max(np.abs(f.Th[:, 2:4])), 1e-6)
        inc = Y - z[0, :-1]
        self.assertTrue(np.allclose(f.Th[:, 4], inc.mean(axis=0), atol=1e-6))
        self.assertTrue(np.allclose(f.Q, np.cov(inc.T, ddof=0), atol=1e-6))
        # (c) monotone
        z, R, x, mu, sd = self._series(R=0.003, n=200)
        f = fc.LSS(2, 2, 1.0, mu, sd, {"kind": "diffuse"}).fit([(z, R, x)], 60, 1e-15)
        self.assertTrue(f.monotone)
        self.assertGreater(f.trace[-1], f.trace[0])

    def test_gains_are_exact(self):
        """The drift is exact on a line; every forecaster is affine in its window measurements with the
        recorded gains (the basis of the measurement cross-covariance)."""
        rng = np.random.default_rng(4)
        ts = [4, 5, 6, 7, 8]
        Zl = np.array([[0.1 * t, 1.0 - 0.2 * t] for t in ts])
        Rs = [np.diag(rng.uniform(0.001, 0.01, 2)) for _ in ts]
        self.assertTrue(np.allclose(fc.drift(Zl, Rs, ts, 3)[0], [1.1, 1.0 - 2.2], atol=1e-9))
        Z = rng.normal(size=(5, 2))
        dZ = rng.normal(size=(5, 2))
        for fn in (fc.persistence, fc.drift):
            z0, G = fn(Z, Rs, ts, 4)
            z1, _ = fn(Z + dZ, Rs, ts, 4)
            self.assertTrue(np.allclose(z1 - z0, sum(G[s] @ dZ[s] for s in range(5)), atol=1e-10))
        for init in ({"kind": "diffuse"}, {"kind": "proper", "mean": [0.0, 0.0], "cov": [[1.0, 0.0], [0.0, 2.0]]}):
            m = fc.LSS(2, 1, 1.0, [0.0], [1.0], init)
            m.Th = np.array([[0.9, 0.1, 0.2, 0.05], [-0.1, 0.8, -0.1, 0.0]])
            m.Q = np.array(Q_TRUE)
            X = rng.normal(size=(1, 5, 1))
            Rb = np.array(Rs)[None]
            m0, _, Mg = m.forecast(Z[None], Rb, X, 4)
            m1, _, _ = m.forecast((Z + dZ)[None], Rb, X, 4)
            self.assertTrue(np.allclose(m1[0] - m0[0], Mg[0] @ dZ.reshape(-1), atol=1e-10))

    def test_shared_noise_known_answer(self):
        """P2-10: constant true profile; the same shared measurement error in the persistence input and every
        future (R = S): the observed squared error is 0, the corrected MSE is tr S (the latent error, positive),
        V_fork is 0 and REDUCIBLE tr S; without the cross-covariance the MSE would be -tr S. Monte Carlo over
        origins with shared and own noise: the corrected MSE estimates the latent MSE tr R."""
        S = 0.01 * np.eye(2)
        meas = {"g": S}
        z, u = np.array([0.3, -0.2]), np.array([0.05, -0.08])

        def row(y, R, g="g"):
            return {"z": np.asarray(y, float), "R": R, "g": g, "events": {}, "unavailable": None}
        win = [row(z + u, S) for _ in range(5)]
        zh, G = fc.persistence(np.array([r["z"] for r in win]), [S] * 5, [1, 2, 3, 4, 5], 4)
        f = {"z": zh.tolist(), "cov": np.zeros((2, 2)).tolist(),
             "cross": {g: c.tolist() for g, c in fc.cross_cov(G, win, meas).items()}}
        futs = [{"kind": "reseed", "row": row(z + u, S)} for _ in range(4)] + [{"kind": "original", "row": row(z + u, S)}]
        rng_of = lambda j: np.random.default_rng(j)  # noqa: E731
        r = fc.origin_metrics(f, futs, meas, [], rng_of, 50)
        self.assertAlmostEqual(r["mse"], float(np.trace(S)), places=14)
        self.assertAlmostEqual(r["v_fork"], 0.0, places=14)
        self.assertAlmostEqual(r["reducible"], float(np.trace(S)), places=14)
        r0 = fc.origin_metrics(dict(f, cross={}), futs, meas, [], rng_of, 50)
        self.assertAlmostEqual(r0["mse"], -float(np.trace(S)), places=14)
        rng = np.random.default_rng(8)
        Rt = 0.03 * np.eye(2)
        est = []
        for _ in range(4000):
            uu = rng.multivariate_normal(np.zeros(2), S)
            win = [row(z + uu + rng.multivariate_normal(np.zeros(2), Rt - S), Rt) for _ in range(5)]
            zh, G = fc.persistence(np.array([w["z"] for w in win]), [Rt] * 5, [1, 2, 3, 4, 5], 1)
            f = {"z": zh.tolist(), "cov": np.zeros((2, 2)).tolist(),
                 "cross": {g: c.tolist() for g, c in fc.cross_cov(G, win, meas).items()}}
            fut = [{"kind": "native", "row": row(z + uu + rng.multivariate_normal(np.zeros(2), Rt - S), Rt)}]
            est.append(fc.origin_metrics(f, fut, meas, [], rng_of, 1)["mse"])
        self.assertAlmostEqual(float(np.mean(est)), float(np.trace(Rt)), delta=0.004)

    def test_evaluation_arithmetic(self):
        """Futures with KNOWN conditional laws N(mu, Sc), measured independently: pooled V_fork estimates tr Sc;
        the exact forecast's REDUCIBLE ~ 0 (its CI covering 0), an offset forecast's ~ ||delta||^2; one surviving
        reseed still gives an MSE (P3) but no V_fork; extinct and unavailable futures are counted; the energy
        score and coverage rank the forecasts."""
        rng = np.random.default_rng(5)
        Sc = np.array([[0.04, 0.01], [0.01, 0.03]])
        Lc = np.linalg.cholesky(Sc)
        meas_R = 0.01 * np.eye(2)
        delta = np.array([0.15, -0.1])
        per = []
        for k in range(360):
            mu = np.array([0.01 * k, -0.02 * (k % 12)])
            futs = []
            for j in range(5):
                if k % 7 == 0 and j == 0:
                    futs.append({"kind": "reseed", "row": {"z": None, "R": None, "g": None, "events": {"extinction": True},
                                                           "unavailable": None}})
                    continue
                if k % 11 == 0 and j == 1:
                    futs.append({"kind": "reseed", "row": {"z": None, "R": None, "g": None, "events": {},
                                                           "unavailable": "assay failed"}})
                    continue
                y = mu + Lc @ rng.standard_normal(2) + 0.1 * rng.standard_normal(2)
                futs.append({"kind": "reseed" if j < 4 else "original",
                             "row": {"z": y, "R": meas_R, "g": None, "events": {}, "unavailable": None}})
            rng_of = lambda j, k=k: np.random.default_rng([k, j])  # noqa: E731
            mets = {name: fc.origin_metrics({"z": z.tolist(), "cov": cov.tolist(), "cross": {}}, futs, {}, ["extinction"],
                                            rng_of, 300)
                    for name, z, cov in (("drift", mu, Sc), ("persistence", mu + delta, Sc), ("lss", mu, 4 * Sc))}
            per.append({"available": True, "stage": "test", "category": "world_transfer", "kind": "fork", "horizon": 10,
                        "world": f"w{k % 12:02d}", "metrics": mets})
        ctx = {"cfg": {"primary": 10, "evaluation": {"bootstrap": 199, "seed_namespace": "t"}}}
        P = fc.pool(ctx, per)
        d0 = P["test/world_transfer/fork/H10/drift"]
        self.assertAlmostEqual(d0["v_fork"]["mean"], 0.07, delta=0.008)
        self.assertAlmostEqual(d0["reducible"]["mean"], 0.0, delta=0.008)
        lo, hi = d0["reducible"]["ci95"]
        self.assertTrue(lo <= 0.0 <= hi)
        self.assertAlmostEqual(P["test/world_transfer/fork/H10/persistence"]["reducible"]["mean"], float(delta @ delta), delta=0.01)
        o0 = per[0]["metrics"]["drift"]
        self.assertEqual((o0["events"]["extinction"], o0["reseeds"], o0["unavailable"]), (1, 2, 1))   # (k = 0: both)
        one = fc.origin_metrics({"z": [0.0, 0.0], "cov": Sc.tolist(), "cross": {}},
                                [{"kind": "reseed", "row": {"z": np.array([0.3, 0.4]), "R": meas_R, "g": None,
                                                            "events": {}, "unavailable": None}}], {}, [],
                                lambda j: np.random.default_rng(j), 10)
        self.assertAlmostEqual(one["mse"], 0.25 - 0.02, places=12)
        self.assertIsNone(one["v_fork"])
        es = {n: np.mean([r["metrics"][n]["energy"] for r in per]) for n in ("drift", "persistence")}
        self.assertLess(es["drift"], es["persistence"])
        self.assertAlmostEqual(d0["cover90"]["mean"], 0.9, delta=0.04)
        self.assertGreater(P["test/world_transfer/fork/H10/lss"]["cover90"]["mean"], 0.97)
        rqlib.canonical(P)

    def test_chi2(self):
        self.assertAlmostEqual(fc.chi2_cdf(2.0, 2), 1 - math.exp(-1), places=12)
        self.assertAlmostEqual(fc.chi2_cdf(3.841458820694124, 1), 0.95, places=9)
        self.assertAlmostEqual(fc.chi2_cdf(30.0, 4), 1 - math.exp(-15) * (1 + 15), places=12)


@unittest.skipIf(np is None, "numpy is not installed")
class TestPipeline(unittest.TestCase):
    """One registered study, its pipeline run once (setUpClass); tamper tests work on copies of the root."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root, cls.cfg_path = make_root(cls.tmp)
        cls.rows = simulate()
        cls.ctx = fc.load_ctx(cls.root)
        man = cls.ctx["manifest"]
        cls.files = {}

        def put(name, rows):
            p = os.path.join(cls.tmp, name)
            wr(p, doc(rows))
            cls.files[name] = p
            return p
        put("fit.json", fit_rows(cls.rows, man))
        for stage, sts in (("val", {"validation"}), ("test", {"test", "training"})):
            pre, tgt = fc.stage_rows(cls.ctx, sts)
            put(f"{stage}_prefix.json", [cls.rows[k] for k in sorted(pre)])
            put(f"{stage}_targets.json", [cls.rows[k] for k in sorted(tgt)])
        cls.base = os.path.join(cls.tmp, "base")              # the root after the validation commitment
        shutil.copytree(cls.root, cls.base)
        f = cls.files
        cls.val = os.path.join(cls.tmp, "val.jsonl")
        cls.model = os.path.join(cls.tmp, "model.json")
        cls.scores = os.path.join(cls.tmp, "val_scores.json")
        cls.test = os.path.join(cls.tmp, "test.jsonl")
        cls.eval = os.path.join(cls.tmp, "eval.json")
        cls.rc = [run(["predict-candidates", "--root", cls.root, "--fit", f["fit.json"], "--prefix", f["val_prefix.json"],
                       "--model-out", cls.model, "--out", cls.val])]
        cls.precommit = os.path.join(cls.tmp, "precommit")
        shutil.copytree(cls.root, cls.precommit)
        sealing.commit(cls.root, "validation", cls.val)
        cls.committed = os.path.join(cls.tmp, "committed")
        shutil.copytree(cls.root, cls.committed)
        cls.rc.append(run(["score-validation", "--root", cls.root, "--predictions", cls.val, "--targets",
                           f["val_targets.json"], "--out", cls.scores]))
        sealing.open_validation(cls.root, cls.scores)
        cls.opened = os.path.join(cls.tmp, "opened")
        shutil.copytree(cls.root, cls.opened)
        cls.rc.append(run(["predict-test", "--root", cls.root, "--prefix", f["test_prefix.json"], "--model", cls.model,
                           "--selection", cls.scores, "--out", cls.test]))
        sealing.commit(cls.root, "test", cls.test, fc.__file__)
        cls.prereg = os.path.join(cls.tmp, "prereg.pdf")
        wr(cls.prereg, "the preregistration\n")
        cls.unfrozen = os.path.join(cls.tmp, "unfrozen")
        shutil.copytree(cls.root, cls.unfrozen)
        sealing.freeze(cls.root, cls.prereg, fc.__file__, osf_url="https://osf.io/abc12", registered_utc=rqlib.now_utc())
        cls.rc.append(run(["evaluate-test", "--root", cls.root, "--predictions", cls.test, "--targets",
                           f["test_targets.json"], "--out", cls.eval]))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def copy(self, which):
        d = tempfile.mkdtemp(dir=self.tmp)
        dst = os.path.join(d, "root")
        shutil.copytree(which, dst)
        return dst

    def put(self, name, obj):
        p = os.path.join(tempfile.mkdtemp(dir=self.tmp), name)
        wr(p, obj if isinstance(obj, str) else json.dumps(obj))
        return p

    def test_end_to_end(self):
        """The staged pipeline runs; categories are reported on their own; lambda is the argmin over the
        registered selection set; provenance binds every input; the test score records its fingerprint."""
        self.assertEqual([r[0] for r in self.rc], [0, 0, 0, 0], [r[1] for r in self.rc])
        op = os.path.join(self.tmp, "origins.json")
        self.assertEqual(run(["origins", "--root", self.root, "--out", op])[0], 0)
        od = rqlib.read_json(op)                                                     # (the outcome-free manifest)
        self.assertEqual(od["origins_sha256"], self.ctx["origins_sha"])
        self.assertEqual({tuple(x) for x in od["rows"]["validation"]["prefix"]}, fc.stage_rows(self.ctx, {"validation"})[0])
        self.assertFalse(any("z" in o for o in od["origins"]))
        cats = {(o["category"], o["stage"]) for o in self.ctx["origins"]}
        for want in (("world_transfer", "validation"), ("world_transfer", "test"), ("forward_time", "validation"),
                     ("forward_time", "test"), ("intersection", "validation"), ("intersection", "test"),
                     ("snapshot_transfer", "validation"), ("in_sample", "training")):
            self.assertIn(want, cats)
        by = self.ctx["by_id"]
        self.assertEqual(by["fork:T00:30:4"]["category"], "snapshot_transfer")       # (T00@34 is held out)
        self.assertEqual(by["fork:V0:185:10"]["stage"], "test")                        # (the test period)
        self.assertEqual(by["native:T02:146:4"]["stage"], "test")                      # (its target T02@150 is a test holdout)
        self.assertEqual(by["native:T02:150:1"]["stage"], "test")                      # (... and in this window)
        self.assertEqual((by["native:T03:191:4"]["stage"], by["native:T03:191:4"]["category"]), ("test", "forward_time"))
        val = [json.loads(ln) for ln in rqlib.read_text(self.val).splitlines()]
        self.assertEqual({ln["stage"] for ln in val}, {"validation"})
        self.assertTrue(all(sorted(ln["forecasts"]) == ["drift", "lss[0.1]", "lss[100.0]", "persistence"]
                            for ln in val if ln["available"]))
        prov = val[0]["provenance"]
        self.assertEqual(prov["model_sha256"], rqlib.sha256_file(self.model))
        self.assertEqual(prov["fit_sha256"], rqlib.sha256_file(self.files["fit.json"]))
        self.assertEqual(prov["prefix_sha256"], rqlib.sha256_file(self.files["val_prefix.json"]))
        self.assertEqual(prov["config_sha256"], rqlib.sha256_file(os.path.join(self.root, "config", "forecast.json")))
        sc = rqlib.read_json(self.scores)
        self.assertEqual(sc["targets_sha256"], rqlib.sha256_file(self.files["val_targets.json"]))
        rows = [r for r in sc["origins"] if r["available"] and r["primary"] and by[r["target_id"]]["time_role"] == "validation"]
        self.assertTrue(rows and {by[r["target_id"]]["category"] for r in rows} == {"forward_time", "intersection"})
        mean = {lam: np.mean([r["metrics"][fc.lss_name(lam)]["mse"] for r in rows]) for lam in (0.1, 100.0)}
        self.assertEqual(sc["selection"]["lambda"], min(mean, key=lambda k: (mean[k], -k)))
        self.assertLess(min(mean.values()), sc["selection"]["reference"]["persistence"])
        mod = rqlib.read_json(self.model)
        lss01 = next(s for s in mod["lss"] if s["lambda"] == 0.1)                    # (the known system, recovered)
        self.assertTrue(lss01["converged"] and lss01["monotone"])
        self.assertLess(np.max(np.abs(np.array(lss01["Theta"])[:, :2] - np.array(A_TRUE))), 0.12)
        self.assertLess(np.max(np.abs(np.array(lss01["Q"]) - np.array(Q_TRUE))), 0.006)
        ev = rqlib.read_json(self.eval)
        self.assertEqual(ev["TEST_PRED_SHA"], rqlib.sha256_file(self.test))
        self.assertEqual(ev["targets_sha256"], rqlib.sha256_file(self.files["test_targets.json"]))
        self.assertEqual(ev["lambda"], sc["selection"]["lambda"])
        keys = set(ev["pooled"])
        for k in ("test/intersection/fork/H10/lss", "test/world_transfer/fork/H10/lss", "test/forward_time/native/H10/lss",
                  "test/intersection/native/H10/lss", "training/in_sample/fork/H10/lss"):
            self.assertIn(k, keys)
        for v in ev["pooled"].values():
            self.assertIn(v["category"], fc.CATEGORIES)
        s1 = next(r for r in ev["origins"] if r["target_id"] == "fork:S1:185:10")["metrics"]["lss"]
        self.assertEqual((s1["events"]["extinction"], s1["reseeds"]), (1, 3))
        s0 = next(r for r in ev["origins"] if r["target_id"] == "fork:S0:185:4")["metrics"]["lss"]
        self.assertEqual((s0["unavailable"], s0["reseeds"]), (1, 3))
        s2 = {r["target_id"]: r for r in ev["origins"] if r["target_id"] in ("native:S2:188:4", "native:S2:190:1")}
        self.assertFalse(s2["native:S2:190:1"]["available"])                             # (S2 extinct at 190: its window)
        m2 = s2["native:S2:188:4"]["metrics"]["lss"]                                      # (... its target: absorbed)
        self.assertEqual((m2["events"]["extinction"], m2["live"], m2["mse"]), (1, 0, None))

    def test_fit_guards(self):
        """P1-1 / P1-2: the fit refuses rows past the cutoff, of held-out worlds, held-out snapshots, fork
        branches, rows carrying a split label or another world's UUID; a map past the registered cutoff;
        references past a registered reference cutoff; fit and prefix from different maps."""
        root = self.copy(self.base)
        fit = rqlib.read_json(self.files["fit.json"])
        pre = self.files["val_prefix.json"]
        out = os.path.join(self.tmp, "x.jsonl")
        mo = os.path.join(self.tmp, "x_model.json")
        cases = [(self.rows[("T03", 121)], "fitting cutoff"), (self.rows[("V1", 50)], "role validation"),
                 (self.rows[("T01", 40)], "role validation"), (self.rows[(bid("T00", 30, 0), 31)], "fork branch"),
                 (dict(self.rows[("T04", 10)], split="training", t=200), "roles come from the split manifest"),
                 (dict(self.rows[("T04", 10)], uuid=UUIDS["S0"]), "UUID")]
        for extra, why in cases:
            f2 = self.put("fit.json", dict(fit, rows=fit["rows"] + [extra]))
            rc, err = run(["predict-candidates", "--root", root, "--fit", f2, "--prefix", pre, "--model-out", mo, "--out", out])
            self.assertEqual(rc, 2, why)
            self.assertIn(why, err)
        for mp, why in ((dict(MAP, cutoff=150), "after the registered cutoff"), ({"cutoff": 120}, "map provenance")):
            f2 = self.put("fit.json", dict(fit, map=mp))
            rc, err = run(["predict-candidates", "--root", root, "--fit", f2, "--prefix", pre, "--model-out", mo, "--out", out])
            self.assertIn(why, err)
        p2 = self.put("prefix.json", dict(rqlib.read_json(pre), map=dict(MAP, fit_sha256="c" * 64)))
        rc, err = run(["predict-candidates", "--root", root, "--fit", self.files["fit.json"], "--prefix", p2,
                       "--model-out", mo, "--out", out])
        self.assertIn("another map", err)
        self.assertFalse(os.path.exists(out))
        d = tempfile.mkdtemp(dir=self.tmp)
        r120, _ = make_root(d, {"map": {"cutoff": 120, "reference_frame_max": 100 * M}})
        c120 = fc.load_ctx(r120)
        with self.assertRaisesRegex(fc.ForecastError, "references reach"):
            fc.load_profiles(c120, fit, "x" * 64, "fit")

    def test_embargo_guards(self):
        """P1-3: predict-candidates takes no targets; a prefix holding any row outside the stage's registered
        windows (a target, another stage's row) is refused, as is a missing window row; score-validation
        refuses target rows of another stage, missing targets and substituted futures."""
        root = self.copy(self.base)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fc.main(["predict-candidates", "--root", root, "--fit", "f", "--prefix", "p", "--model-out", "m", "--out", "o",
                     "--targets", "t"])
        pre = rqlib.read_json(self.files["val_prefix.json"])
        out = os.path.join(self.tmp, "y.jsonl")
        for extra, why in ((self.rows[("T05", 160)], "not registered prefix rows"),       # (a validation target only)
                           (self.rows[("S0", 182)], "not registered prefix rows")):       # (a test-stage row)
            p2 = self.put("prefix.json", dict(pre, rows=pre["rows"] + [extra]))
            rc, err = run(["predict-candidates", "--root", root, "--fit", self.files["fit.json"], "--prefix", p2,
                           "--model-out", os.path.join(self.tmp, "m.json"), "--out", out])
            self.assertEqual(rc, 2)
            self.assertIn(why, err)
        p2 = self.put("prefix.json", dict(pre, rows=pre["rows"][1:]))
        rc, err = run(["predict-candidates", "--root", root, "--fit", self.files["fit.json"], "--prefix", p2,
                       "--model-out", os.path.join(self.tmp, "m.json"), "--out", out])
        self.assertIn("missing", err)
        root = self.copy(self.committed)
        tg = rqlib.read_json(self.files["val_targets.json"])
        sc = os.path.join(self.tmp, "sc.json")
        for rows, why in ((tg["rows"] + [self.rows[("S1", 195)]], "not targets of the committed"),     # (a test target)
                          (tg["rows"] + [dict(self.rows[(bid("V0", 30, 1), 34)], t=35)], "not targets"),  # (no such future)
                          (tg["rows"][:-1], "missing")):
            t2 = self.put("targets.json", dict(tg, rows=rows))
            rc, err = run(["score-validation", "--root", root, "--predictions", self.val, "--targets", t2, "--out", sc])
            self.assertEqual(rc, 2)
            self.assertIn(why, err)
        self.assertFalse(os.path.exists(sc))

    def test_commitment_guards(self):
        """P1-4 / P1-5: scoring needs the committed bytes (no marker; other bytes refused); predict-test needs
        the scores recorded by open-validation and the model they name; evaluate-test needs the public freeze
        and the committed test predictions, and scores the verified bytes even if the file changes after the
        gate. The candidate file is sealing's commit format."""
        sc = os.path.join(self.tmp, "sc2.json")
        rc, err = run(["score-validation", "--root", self.copy(self.precommit), "--predictions", self.val, "--targets",
                       self.files["val_targets.json"], "--out", sc])
        self.assertIn("no VAL_PRED_SHA", err)
        root = self.copy(self.committed)
        data = rqlib.read_text(self.val)
        v2 = self.put("val.jsonl", data.replace('"available":true', '"available":true ', 1))
        rc, err = run(["score-validation", "--root", root, "--predictions", v2, "--targets", self.files["val_targets.json"],
                       "--out", sc])
        self.assertIn("not the committed validation predictions", err)
        t2 = os.path.join(self.tmp, "t2.jsonl")
        rc, err = run(["predict-test", "--root", root, "--prefix", self.files["test_prefix.json"], "--model", self.model,
                       "--selection", self.scores, "--out", t2])
        self.assertIn("not recorded", err)
        root = self.copy(self.opened)
        s2 = self.put("val_scores.json", dict(rqlib.read_json(self.scores), selection=dict(
            rqlib.read_json(self.scores)["selection"], **{"lambda": 100.0 if rqlib.read_json(self.scores)["selection"]["lambda"] == 0.1 else 0.1})))
        rc, err = run(["predict-test", "--root", root, "--prefix", self.files["test_prefix.json"], "--model", self.model,
                       "--selection", s2, "--out", t2])
        self.assertIn("not the validation scores recorded", err)
        m2 = self.put("model.json", rqlib.read_text(self.model).replace('"converged":true', '"converged":true ', 1))
        rc, err = run(["predict-test", "--root", root, "--prefix", self.files["test_prefix.json"], "--model", m2,
                       "--selection", self.scores, "--out", t2])
        self.assertIn("not the model state", err)
        ev = os.path.join(self.tmp, "ev2.json")
        rc, err = run(["evaluate-test", "--root", self.copy(self.unfrozen), "--predictions", self.test, "--targets",
                       self.files["test_targets.json"], "--out", ev])
        self.assertIn("no public freeze record", err)
        fresh = self.put("test.jsonl", rqlib.read_text(self.test).replace('"available":true', '"available":true ', 1))
        rc, err = run(["evaluate-test", "--root", self.copy(self.root), "--predictions", fresh, "--targets",
                       self.files["test_targets.json"], "--out", ev])
        self.assertIn("not the committed test predictions", err)
        root = self.copy(self.root)
        tp = self.put("test.jsonl", rqlib.read_text(self.test))
        real = sealing.require_test_freeze

        def gate_then_swap(study, pred_path, script):
            got = real(study, pred_path, script)
            wr(pred_path, "garbage\n")                                          # (replaced after the gate)
            return got
        sealing.require_test_freeze = gate_then_swap
        try:
            rc, err = run(["evaluate-test", "--root", root, "--predictions", tp, "--targets", self.files["test_targets.json"],
                           "--out", ev])
        finally:
            sealing.require_test_freeze = real
        self.assertEqual(rc, 0, err)
        self.assertEqual(rqlib.read_json(ev)["TEST_PRED_SHA"], rqlib.sha256_file(self.test))

    def test_panel_verification(self):
        """P2-13: the registered fork panel: a dropped branch, an unregistered branch, a branch row with
        another branch's identity, a future at an unregistered horizon are refused; invalid covariances
        (asymmetric, not PSD, non-finite; a shared component larger than the row's) are refused."""
        root = self.copy(self.root)
        tg = rqlib.read_json(self.files["test_targets.json"])
        ev = os.path.join(self.tmp, "ev3.json")
        b0, b1 = bid("S0", 185, 0), bid("S0", 185, 1)
        k1 = next(i for i, r in enumerate(tg["rows"]) if r["world"] == b1 and r["t"] == 195)

        def variant(fn):
            rows = json.loads(json.dumps(tg["rows"]))
            fn(rows)
            return self.put("targets.json", dict(tg, rows=rows))
        bad_cov = [[0.003, 0.001], [0.0, 0.003]]
        cases = [(lambda rs: rs.pop(k1), "missing"),
                 (lambda rs: rs.append(dict(rs[k1], world="S0.o185M.s9", uuid=None)), "not in the split manifest"),
                 (lambda rs: rs[k1].update(uuid=buuid(b0)), "UUID"),
                 (lambda rs: rs.append(dict(rs[k1], t=190)), "not targets"),
                 (lambda rs: rs[k1].update(cov=bad_cov), "not symmetric"),
                 (lambda rs: rs[k1].update(cov=[[0.003, 0.0], [0.0, -0.001]]), "positive semidefinite"),
                 (lambda rs: rs[k1].update(cov=[[float("nan"), 0.0], [0.0, 0.003]]), "finite"),
                 (lambda rs: rs[k1].update(cov=[[0.0005, 0.0], [0.0, 0.0005]]), "shared component"),
                 (lambda rs: rs[k1].update(unavailable="assay failed"), "at once")]
        for fn, why in cases:
            rc, err = run(["evaluate-test", "--root", root, "--predictions", self.test, "--targets", variant(fn), "--out", ev])
            self.assertEqual(rc, 2, why)
            self.assertIn(why, err)

    def test_config_and_classification(self):
        """P1-7: horizons and the primary come from the registered configuration (bound to the fork registry);
        the separation is checked; counts must be positive; a registered configuration is never replaced and
        follows no candidate. A forward-time window crossing the separation is excluded."""
        for over, why in (({"primary": 4}, "fork registry's horizon"),
                          ({"temporal": {"validation": [131, 160]}}, "separation"),
                          ({"evaluation": {"bootstrap": 0}}, "bootstrap"),
                          ({"horizons": [10, 4]}, "ascending")):
            d = tempfile.mkdtemp(dir=self.tmp)
            with self.assertRaisesRegex(fc.ForecastError, why):
                make_root(d, over)
        root = self.copy(self.base)
        cfg = rqlib.read_json(self.cfg_path)
        cp = self.put("cfg.json", dict(cfg, window=4))
        with self.assertRaisesRegex(fc.ForecastError, "never replaced"):
            fc.register(root, cp)
        fc.register(root, self.cfg_path)                                           # (the same bytes: accepted)
        d = tempfile.mkdtemp(dir=self.tmp)
        r2, c2 = make_root(d, register=False)
        os.makedirs(os.path.join(r2, "registration"), exist_ok=True)
        wr(os.path.join(r2, "registration", "VAL_PRED_SHA"), "0" * 64 + "\n")
        with self.assertRaisesRegex(fc.ForecastError, "before the candidates"):
            fc.register(r2, c2)
        d = tempfile.mkdtemp(dir=self.tmp)
        r3, _ = make_root(d, {"temporal": {"test": [182, 200]}})
        c3 = fc.load_ctx(r3)
        self.assertIn("crosses the registered separation", c3["by_id"]["fork:S0:185:10"]["excluded"])
        pre, tgt = fc.stage_rows(c3, {"test"})
        self.assertNotIn((bid("S0", 185, 0), 195), tgt)                             # (excluded: its targets never read)
        self.assertNotIn(("S0", 181), pre)


if __name__ == "__main__":
    unittest.main()

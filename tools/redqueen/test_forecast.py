#!/usr/bin/env python3
"""test_forecast.py: the Level-2 linear forecasts (forecast.py, design v4 §10.6, §7.1-7.3).

NUMERICS (known answers): the registered initial-state prior conditions on y(0) exactly once; the penalized
EM's M-step is the exact maximizer of its penalized objective, equals augmented least squares on fully
observed data, reaches Theta0 under strong regularization, never decreases its objective; the numerical-
failure policy (a non-monotone or unconverged EM is unavailable and never selected); the forecasters' gains
are exact; SHARED measurement noise: the persistence point metrics (Codex r1: observed error 0, corrected
MSE tr S), the lss predictive covariance under the source structure (Codex r2: constant scalar state, five
observations, R = 1, S = 0.5, Q -> 0: 0.6, not the working 0.2; Monte Carlo variance and coverage), and the
fit's translation equivariance (a shift of every fitting profile moves only c by (I - A) u; the forecast's
total loading on the shared component is I); the evaluation arithmetic on futures with known laws.
PIPELINE against a real split manifest (sealing.manifest with the fork registry) and sealing's commitments
and freeze, with the evaluator's implementation manifest as the frozen evaluation script: the registration
is TARGET-DISJOINT (no stage reads its own or a later stage's targets); categories and registered roles are
pooled apart; lambda is the argmin over the selection set; outputs are byte-reproducible. GUARDS: fit rows
(cutoff, held-out worlds and snapshots, branches, labels, UUIDs, map / reference provenance); prefix and
target membership checked before any value; a non-disjoint registration; an unsupported measurement-source
structure; the commitments (marker, bytes, selection record, model, freeze); the implementation (a changed
helper module, an RQ_PYLIB shadow); the validation-evaluation record substituted before and after the gate;
the fork registry replaced and read once; the fork panel; contradictory absorbing rows. numpy required.

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
import subprocess
import sys
import tempfile
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
import forecast as fc  # noqa: E402  (first: its helpers are the verified-loaded ones, used below)
rqlib, sealing, staging = fc.rqlib, fc.sealing, fc.staging
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
S_SH, R_OWN = 0.001, 0.002                     # shared (per measurement group) and own measurement variances
TRAIN = [f"T{k:02d}" for k in range(8)]
VAL, TEST = ["V0", "V1", "V2"], ["S0", "S1", "S2"]
SPLIT = dict({w: "train" for w in TRAIN}, **{w: "val" for w in VAL}, **{w: "test" for w in TEST}, A1="train")
FORK, ORIG, SEEDS = ["T00", "V0", "S0", "S1"], [30, 100, 185], 4
HOLD = {"T00:34": "val", "T01:40": "val", "T02:150": "test", "T03:195": "val"}
HELD = {(k.split(":")[0], int(k.split(":")[1])) for k in HOLD}
UUIDS = {w: str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:redqueen:ns-main:{w}")) for w in sorted(SPLIT)}
MAP = {"cutoff": 120, "fit_sha256": "a" * 64, "references": {"sha256": "b" * 64, "max_frame": 120 * M}}
COVS = ["abundance_prey", "energy"]
GROUPS = ([f"fit:{w}" for w in TRAIN] + [f"g:{w}" for w in sorted(TRAIN + VAL + TEST)]
          + [f"test:{w}" for w in sorted(TRAIN + VAL + TEST)])


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
           "temporal": {"fit_through": 120, "validation": [141, 160], "test": [181, 200], "separation": 20,
                        "inputs_through": {"validation": 150, "test": 190}},
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


def group_of(w, root, t, test_rows=frozenset()):
    """The fixture's registered source structure (designed from the outcome-free registration): a training
    world's fitting rows are measured in their own group (fit:<world>), the test stage's target rows in
    test:<root>, every other row in g:<root>: independent of the fit, and the test targets independent of the
    lambda selection's inputs and targets."""
    if w in TRAIN and t <= 120 and (w, t) not in HELD:
        return f"fit:{w}"
    return f"test:{root}" if (w, t) in test_rows else f"g:{root}"


def simulate(seed=7, test_rows=frozenset()):
    """Every native row (T, V, S worlds, t = 0 .. 200) and every fork branch's rows (+1, +4, +10) from the known
    linear system, measured with the group's shared component plus own noise. S2 goes extinct at 190; branch
    S1.o185M.s2 is extinct at 195; S0.o185M.s3's +4 assay is unavailable."""
    rng = np.random.default_rng(seed)
    A, c, L = np.array(A_TRUE), np.array(C_TRUE), np.linalg.cholesky(np.array(Q_TRUE))
    zbar = np.linalg.solve(np.eye(2) - A, c)
    us = {g: math.sqrt(S_SH) * rng.standard_normal(2) for g in GROUPS}
    rows, truth = {}, {}

    def meas(w, root, t, z):
        g = group_of(w, root, t, test_rows)
        return {"world": w, "t": t, "uuid": UUIDS.get(w) or buuid(w), "z": (z + us[g] + math.sqrt(R_OWN) * rng.standard_normal(2)).tolist(),
                "cov": ((S_SH + R_OWN) * np.eye(2)).tolist(), "meas_group": g,
                "covariates": {"abundance_prey": float(rng.uniform(300, 600)), "energy": float(rng.normal())},
                "events": {"extinction": False}}
    for w in sorted(TRAIN + VAL + TEST):
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
         "measurement": {"shared": {g: (S_SH * np.eye(2)).tolist() for g in GROUPS}}, "rows": rows}
    d.update(over)
    return d


def fit_rows(rows, man):
    return [rows[(w, t)] for w in TRAIN for t in range(0, 121) if sealing.node_role(man, w, t * M if t else 1) == "training"]


def run(args):
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        rc = fc.main(args)
    return rc, err.getvalue()


def row(y, R, g="g"):
    return {"z": np.asarray(y, float), "R": np.asarray(R, float), "g": g, "events": {}, "unavailable": None}


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

    def _series(self, n=300, seed=3, R=0.0, shift=None):
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
        Z = np.array(Z) + (0 if shift is None else np.asarray(shift))
        return Z[None], np.array(Rm)[None], X[None], X.mean(axis=0), X.std(axis=0)

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
        Q_nopen = (S11 - m.Th @ S10.T - S10 @ m.Th.T + m.Th @ S00 @ m.Th.T) / n
        self.assertLess(obj(m.Th, Q_nopen), best - 1e-6)
        self.assertGreater(np.max(np.abs(Q_nopen - m.Q)), 1e-6)
        z, R, x, mu, sd = self._series(R=0.0)
        for lam in (50.0, 1e9):
            f = fc.LSS(2, 2, lam, mu, sd, {"kind": "diffuse"}).fit([(z, R, x)], 20, 1e-10)
            Phi = np.hstack([z[0, :-1], (x[0, :-1] - mu) / sd, np.ones((len(z[0]) - 1, 1))])
            Y = z[0, 1:]
            aug = np.vstack([Phi, math.sqrt(lam) * np.eye(5)[:4]])
            tgt = np.vstack([Y, math.sqrt(lam) * np.hstack([np.eye(2), np.zeros((2, 3))]).T[:4]])
            Th = np.linalg.lstsq(aug, tgt, rcond=None)[0].T
            res = tgt - aug @ Th.T
            self.assertTrue(f.converged and f.usable)
            self.assertTrue(np.allclose(f.Th, Th, atol=1e-7), (lam, f.Th, Th))
            self.assertTrue(np.allclose(f.Q, res.T @ res / len(Y), atol=1e-8), (lam, f.Q))
        self.assertLess(np.max(np.abs(f.Th[:, :2] - np.eye(2))), 1e-6)       # (lambda 1e9: A = I, B = 0)
        self.assertLess(np.max(np.abs(f.Th[:, 2:4])), 1e-6)
        inc = Y - z[0, :-1]
        self.assertTrue(np.allclose(f.Th[:, 4], inc.mean(axis=0), atol=1e-6))
        self.assertTrue(np.allclose(f.Q, np.cov(inc.T, ddof=0), atol=1e-6))
        z, R, x, mu, sd = self._series(R=0.003, n=200)
        f = fc.LSS(2, 2, 1.0, mu, sd, {"kind": "diffuse"}).fit([(z, R, x)], 60, 1e-15)
        self.assertTrue(f.monotone)
        self.assertGreater(f.trace[-1], f.trace[0])

    def test_em_failure_policy(self):
        """Codex r2 P2-9: a fit whose penalized objective decreases (here: a sabotaged M-step) is unusable with
        its diagnostic, even when it then 'converges'; one that does not converge too; select_lambda never
        picks an unavailable lambda."""
        z, R, x, mu, sd = self._series(R=0.003, n=200)
        m = fc.LSS(2, 2, 1.0, mu, sd, {"kind": "diffuse"})
        real, calls = m.mstep, [0]

        def bad(*a):
            real(*a)
            calls[0] += 1
            if calls[0] == 3:
                m.Q = m.Q * 50.0                                   # (an objective drop)
        m.mstep = bad
        m.fit([(z, R, x)], 200, 1e-7)
        self.assertTrue(m.converged)
        self.assertFalse(m.usable)
        self.assertIn("decreased", m.failure)
        st = m.state()
        self.assertEqual((st["usable"], st["monotone"]), (False, False))
        f = fc.LSS(2, 2, 1.0, mu, sd, {"kind": "diffuse"}).fit([(z, R, x)], 2, 1e-15)
        self.assertIn("did not converge", f.failure)
        per = [{"available": True, "stage": "validation", "primary": True, "time_role": "validation",
                "metrics": {"lss[0.1]": {"forecast_unavailable": "the penalized objective decreased"},
                            "lss[1.0]": {"mse": 0.5}, "persistence": {"mse": 0.9}, "drift": {"mse": 1.0}}}]
        ctx = {"cfg": {"lss": {"lambdas": [0.1, 1.0]}}}
        sel = fc.select_lambda(ctx, per)
        self.assertEqual(sel["lambda"], 1.0)
        self.assertIn("decreased", sel["candidates"][0]["reason"])

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

    def test_shared_noise_point_metrics(self):
        """P2-10 (r1): constant true profile; the same shared measurement error in the persistence input and
        every future (R = S): the observed squared error is 0, the corrected MSE is tr S (positive), V_fork 0
        and REDUCIBLE tr S; without the cross-covariance it would be -tr S. Monte Carlo with shared and own
        noise: the corrected MSE estimates the latent MSE tr R."""
        S = 0.01 * np.eye(2)
        meas = {"g": S}
        z, u = np.array([0.3, -0.2]), np.array([0.05, -0.08])
        win = [row(z + u, S) for _ in range(5)]
        zh, G = fc.persistence(np.array([r["z"] for r in win]), [S] * 5, [1, 2, 3, 4, 5], 4)
        V, cross, _ = fc.measurement_parts(G, win, meas)
        f = {"z": zh.tolist(), "cov": V.tolist(), "cross": {g: c.tolist() for g, c in cross.items()}}
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
            V, cross, _ = fc.measurement_parts(G, win, meas)
            f = {"z": zh.tolist(), "cov": V.tolist(), "cross": {g: c.tolist() for g, c in cross.items()}}
            fut = [{"kind": "native", "row": row(z + uu + rng.multivariate_normal(np.zeros(2), Rt - S), Rt)}]
            est.append(fc.origin_metrics(f, fut, meas, [], rng_of, 1)["mse"])
        self.assertAlmostEqual(float(np.mean(est)), float(np.trace(Rt)), delta=0.004)

    def test_lss_covariance_under_shared_noise(self):
        """Codex r2 P2-5: the lss predictive covariance under the registered source structure. Analytic: a
        constant scalar state (A = 1, c = 0, Q -> 0), diffuse initialization, five observations with R = 1 and
        a shared S = 0.5: the working filter's P is 0.2, the latent forecast-error variance 0.5 + 0.5 / 5 =
        0.6. Monte Carlo (the 2-d system, fixed parameters, a shared component per window and target): the
        recorded covariance matches the latent error covariance, and the PIT coverage is nominal."""
        m = fc.LSS(1, 0, 1.0, [], [], {"kind": "diffuse"})
        m.Th, m.Q = np.array([[1.0, 0.0]]), np.array([[1e-14]])
        Z = np.array([[[0.3], [-0.1], [0.2], [0.5], [0.0]]])
        R = np.ones((1, 5, 1, 1))
        mean, Pw, Mg = m.forecast(Z, R, np.zeros((1, 5, 0)), 1)
        G = [Mg[0][:, s:s + 1] for s in range(5)]
        win = [row(Z[0, s], [[1.0]]) for s in range(5)]
        V, cross, own = fc.measurement_parts(G, win, {"g": np.array([[0.5]])})
        self.assertAlmostEqual(float(Pw[0, 0, 0]), 0.2, places=9)
        self.assertAlmostEqual(float((Pw[0] - own + V)[0, 0]), 0.6, places=9)
        self.assertAlmostEqual(float(cross["g"][0, 0]), 0.5, places=9)          # (L = 1: Cov(z_hat, v_f) = S)
        rng = np.random.default_rng(11)
        A, c, Qm = np.diag([0.95, 0.9]), np.array([0.01, 0.0]), 0.0005 * np.eye(2)   # (slow states, noisy profiles)
        Lq = np.linalg.cholesky(Qm)
        m = fc.LSS(2, 0, 1.0, [], [], {"kind": "diffuse"})
        m.Th, m.Q = np.hstack([A, c[:, None]]), Qm
        Sg, Rt = 0.025 * np.eye(2), 0.03 * np.eye(2)
        n, H = 4000, 1
        Zs, zf, yf = [], [], []
        for _ in range(n):
            z = np.linalg.solve(np.eye(2) - A, c) + 0.3 * rng.standard_normal(2)
            u = rng.multivariate_normal(np.zeros(2), Sg)
            ys = []
            for s in range(5):
                ys.append(z + u + rng.multivariate_normal(np.zeros(2), Rt - Sg))
                if s < 4:
                    z = A @ z + c + Lq @ rng.standard_normal(2)
            for _ in range(H):
                z = A @ z + c + Lq @ rng.standard_normal(2)
            Zs.append(ys)
            zf.append(z)
            yf.append(z + u + rng.multivariate_normal(np.zeros(2), Rt - Sg))
        Zs = np.array(Zs)
        mean, Pw, Mg = m.forecast(Zs, np.broadcast_to(Rt, (n, 5, 2, 2)).copy(), np.zeros((n, 5, 0)), H)
        G = [Mg[0][:, 2 * s:2 * s + 2] for s in range(5)]                  # (the gains do not depend on y)
        win = [row(Zs[0, s], Rt) for s in range(5)]
        V, cross, own = fc.measurement_parts(G, win, {"g": Sg})
        cov = Pw[0] - own + V
        err = mean - np.array(zf)
        emp = np.cov(err.T)
        self.assertLess(abs(np.trace(emp) - np.trace(cov)) / np.trace(cov), 0.06, (emp, cov))
        self.assertGreater(abs(np.trace(cov) - np.trace(Pw[0])) / np.trace(Pw[0]), 0.1)   # (the working P differs)
        C = cross["g"]
        Sy = cov + Rt - C - C.T
        q = np.einsum("bi,ij,bj->b", np.array(yf) - mean, np.linalg.inv(Sy), np.array(yf) - mean)
        cover = np.mean([fc.chi2_cdf(float(x), 2) <= 0.9 for x in q])
        self.assertAlmostEqual(cover, 0.9, delta=0.02)

    def test_fit_shift_equivariance(self):
        """Codex r2 P2-5 (shared fitting sources): one measurement group across the whole fit. Shifting every
        fitting profile by u leaves A, B, Q and moves c by (I - A) u; the lss forecast of a window shifted by u
        moves by exactly u; the recorded loading K = (d z_hat / d c)(I - A) makes the total loading on the shared
        component sum_s G_s + K = I (so Cov(z_hat, v_f) = S for a target in that group)."""
        u = np.array([0.07, -0.04])
        z, R, x, mu, sd = self._series(R=0.003, n=250)
        zs = z + u
        f0 = fc.LSS(2, 2, 1.0, mu, sd, {"kind": "diffuse"}).fit([(z, R, x)], 400, 1e-12)
        f1 = fc.LSS(2, 2, 1.0, mu, sd, {"kind": "diffuse"}).fit([(zs, R, x)], 400, 1e-12)
        A0 = f0.Th[:, :2]
        self.assertTrue(np.allclose(f1.Th[:, :4], f0.Th[:, :4], atol=1e-6))
        self.assertTrue(np.allclose(f1.Q, f0.Q, atol=1e-8))
        self.assertTrue(np.allclose(f1.Th[:, 4] - f0.Th[:, 4], (np.eye(2) - A0) @ u, atol=1e-6))
        W = z[:, 200:205]
        Rw, Xw = R[:, 200:205], x[:, 200:205]
        m0, _, Mg = f0.forecast(W, Rw, Xw, 4)
        m1, _, _ = f1.forecast(W + u, Rw, Xw, 4)
        self.assertTrue(np.allclose(m1 - m0, u, atol=1e-6))
        K = f0.fit_loading(W, Rw, Xw, 4)[0]
        Gsum = sum(Mg[0][:, 2 * s:2 * s + 2] for s in range(5))
        self.assertTrue(np.allclose(Gsum + K, np.eye(2), atol=1e-9))

    def test_proper_prior_breaks_equivariance(self):
        """Codex r3 P2-3: under a PROPER initial state the shift response fails (the first filtered mean moves
        by K0 u, not u): the refit's forecast does not move by u, and Sum G_s + K is not I; so the single-fit-
        group source case is refused under a proper prior (the pipeline test checks the refusal)."""
        u = np.array([0.7, -0.4])
        z, R, x, mu, sd = self._series(R=0.003, n=60)
        init = {"kind": "proper", "mean": [0.0, 0.0], "cov": [[1e-4, 0.0], [0.0, 1e-4]]}
        f0 = fc.LSS(2, 2, 1.0, mu, sd, init).fit([(z, R, x)], 300, 1e-12)
        f1 = fc.LSS(2, 2, 1.0, mu, sd, init).fit([(z + u, R, x)], 300, 1e-12)
        W, Rw, Xw = z[:, 40:45], R[:, 40:45], x[:, 40:45]
        m0, _, Mg = f0.forecast(W, Rw, Xw, 4)
        m1, _, _ = f1.forecast(W + u, Rw, Xw, 4)
        self.assertGreater(float(np.max(np.abs(m1 - m0 - u))), 1e-4)
        K = f0.fit_loading(W, Rw, Xw, 4)[0]
        Gsum = sum(Mg[0][:, 2 * s:2 * s + 2] for s in range(5))
        self.assertGreater(float(np.max(np.abs(Gsum + K - np.eye(2)))), 1e-4)

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
            per.append({"available": True, "stage": "test", "world_role": "test", "target_role": "test",
                        "time_role": "fit", "category": "world_transfer", "kind": "fork", "horizon": 10,
                        "world": f"w{k % 12:02d}", "metrics": mets})
        ctx = {"cfg": {"primary": 10, "evaluation": {"bootstrap": 199, "seed_namespace": "t"}}}
        P = fc.pool(ctx, per)
        key = "test/test/test/fit/world_transfer/fork/H10/"
        d0 = P[key + "drift"]
        self.assertAlmostEqual(d0["v_fork"]["mean"], 0.07, delta=0.008)
        self.assertAlmostEqual(d0["reducible"]["mean"], 0.0, delta=0.008)
        lo, hi = d0["reducible"]["ci95"]
        self.assertTrue(lo <= 0.0 <= hi)
        self.assertAlmostEqual(P[key + "persistence"]["reducible"]["mean"], float(delta @ delta), delta=0.01)
        o0 = per[0]["metrics"]["drift"]
        self.assertEqual((o0["events"]["extinction"], o0["reseeds"], o0["unavailable"]), (1, 2, 1))
        # (PR-D, Annex H D6 rule 27 §10.6) explicit denominators and conditioning; conditioned origins are
        # pooled apart from complete ones, never together
        self.assertEqual((o0["denominators"], o0["conditioning"], o0["reseeds_registered"]),
                         ({"registered": 5, "observable": 4, "live": 3, "event": 1}, "survivor-conditioned", 4))
        self.assertEqual(per[11]["metrics"]["drift"]["conditioning"], "observable-only")     # (k = 11: a gap only)
        self.assertEqual(per[1]["metrics"]["drift"]["conditioning"], "complete")
        sc = P[key + "drift/survivor-conditioned"]
        n_sc = sum(1 for k in range(360) if k % 7 == 0)
        self.assertEqual((sc["origins"], sc["conditioning"], d0["conditioning"]), (n_sc, "survivor-conditioned", "complete"))
        self.assertEqual(d0["origins"] + sc["origins"] + P[key + "drift/observable-only"]["origins"], 360)
        self.assertGreaterEqual(d0["reducible"]["roots"], 2)
        one = fc.origin_metrics({"z": [0.0, 0.0], "cov": Sc.tolist(), "cross": {}},
                                [{"kind": "reseed", "row": {"z": np.array([0.3, 0.4]), "R": meas_R, "g": None,
                                                            "events": {}, "unavailable": None}}], {}, [],
                                lambda j: np.random.default_rng(j), 10)
        self.assertAlmostEqual(one["mse"], 0.25 - 0.02, places=12)
        self.assertIsNone(one["v_fork"])
        self.assertIn("needs two", one["v_fork_unavailable"])
        # a pool of one root world: the point, never an interval
        P1 = fc.pool(ctx, [dict(r, world="w00") for r in per[:20]])
        p1 = P1[key + "drift"]["mse"]
        self.assertEqual((p1["roots"], p1["ci95"]), (1, None))
        self.assertIn("two contributing root worlds", p1["ci95_unavailable"])
        es = {n: np.mean([r["metrics"][n]["energy"] for r in per]) for n in ("drift", "persistence")}
        self.assertLess(es["drift"], es["persistence"])
        self.assertAlmostEqual(d0["cover90"]["mean"], 0.9, delta=0.04)
        self.assertGreater(P[key + "lss"]["cover90"]["mean"], 0.97)
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
        cls.ctx = fc.load_ctx(cls.root)
        cls.rows = simulate(test_rows=frozenset(fc.stage_rows(cls.ctx, {"test", "training"})[1]))
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
        cls.base = os.path.join(cls.tmp, "base")
        shutil.copytree(cls.root, cls.base)
        f = cls.files
        cls.val, cls.model, cls.scores, cls.test, cls.eval, cls.impl = (
            os.path.join(cls.tmp, n) for n in ("val.jsonl", "model.json", "val_scores.json", "test.jsonl", "eval.json",
                                               "impl.json"))
        cls.rc = []

        def step(args):                                          # (a failing stage stops the fixture, with its error)
            cls.rc.append(run(args))
            if cls.rc[-1][0] != 0:
                raise RuntimeError(f"{args[0]} failed: {cls.rc[-1][1]}")
        step(["predict-candidates", "--root", cls.root, "--fit", f["fit.json"], "--prefix", f["val_prefix.json"],
              "--model-out", cls.model, "--out", cls.val])
        cls.precommit = os.path.join(cls.tmp, "precommit")
        shutil.copytree(cls.root, cls.precommit)
        sealing.commit(cls.root, "validation", cls.val)
        cls.committed = os.path.join(cls.tmp, "committed")
        shutil.copytree(cls.root, cls.committed)
        step(["score-validation", "--root", cls.root, "--predictions", cls.val, "--targets", f["val_targets.json"],
              "--out", cls.scores])
        sealing.open_validation(cls.root, cls.scores)
        cls.opened = os.path.join(cls.tmp, "opened")
        shutil.copytree(cls.root, cls.opened)
        step(["predict-test", "--root", cls.root, "--prefix", f["test_prefix.json"], "--model", cls.model,
              "--selection", cls.scores, "--out", cls.test])
        step(["implementation", "--out", cls.impl])
        sealing.commit(cls.root, "test", cls.test, cls.impl)
        cls.prereg = os.path.join(cls.tmp, "prereg.pdf")
        wr(cls.prereg, "the preregistration\n")
        cls.unfrozen = os.path.join(cls.tmp, "unfrozen")
        shutil.copytree(cls.root, cls.unfrozen)
        sealing.freeze(cls.root, cls.prereg, cls.impl, osf_url="https://osf.io/abc12", registered_utc=rqlib.now_utc())
        step(["evaluate-test", "--selection", cls.scores, "--root", cls.root, "--predictions", cls.test, "--targets",
              f["test_targets.json"], "--out", cls.eval])

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

    def test_prefix_unavailable_origin_keeps_its_outcomes(self):
        """Codex #78 r1 P2-5 and the §10.5 disposition: an origin WITHOUT a continuous forecast (its prefix extinct or
        technically unavailable) still carries its outcome / denominator receipt from its registered futures; an
        excluded origin is marked (its futures unread); the summary counts every origin; the §10.5 completeness
        gate is incomplete with every reason, and complete only on a complete 32-world native panel."""
        keys = {"stage": "test", "world_role": "test", "target_role": "test", "time_role": "fit",
                "category": "world_transfer", "horizon": 10, "t0": 10, "target_t": 20, "primary": True}

        def row(z, ev=None, un=None):
            return {"z": z, "R": None, "g": None, "events": ev or {}, "unavailable": un}
        T = {"rows": {("w1", 20): row(None, {"extinction": True}), ("b1", 20): row(None, {"extinction": True}),
                      ("b2", 20): row([0.1, 0.2]), ("b3", 20): row(None, None, "assay failed"), ("n1", 20): row([0.0, 0.0])},
             "meas": {}}
        lines = [dict(keys, target_id="fork:w1", kind="fork", world="w1", available=False, reason="its prefix is extinct",
                      branches=["b1", "b2", "b3"]),
                 dict(keys, target_id="fork:w2", kind="fork", world="w2", available=False, reason="in-sample", branches=[]),
                 dict(keys, target_id="native:n1", kind="native", world="n1", available=False, reason="a technical gap",
                      branches=[])]
        ctx = {"cfg": {"events": ["extinction"], "evaluation": {"seed_namespace": "t", "energy_draws": 10}, "primary": 10},
               "by_id": {"fork:w1": {"excluded": None}, "fork:w2": {"excluded": "in-sample"}, "native:n1": {"excluded": None}}}
        per = fc.score_lines(ctx, lines, T)
        o = per[0]["outcomes"]
        self.assertEqual((o["denominators"], o["conditioning"], o["events"]),
                         ({"registered": 4, "observable": 3, "live": 1, "event": 2}, "survivor-conditioned", {"extinction": 2}))
        self.assertEqual((per[0]["available"], per[0]["reason"], "metrics" in per[0]), (False, "its prefix is extinct", False))
        self.assertEqual((per[1]["excluded"], per[1]["outcomes"]), (True, None))
        self.assertEqual((per[2]["outcomes"]["denominators"]["live"], per[2]["outcomes"]["conditioning"]), (1, "complete"))
        S = fc.outcome_summary(per)
        f = S["test/fork/H10/primary"]
        self.assertEqual((f["origins"], f["prefix_unavailable"], f["excluded"], f["futures"]["registered"],
                          f["conditioning"]["survivor-conditioned"]), (2, 1, 1, 4, 1))
        self.assertFalse(hasattr(fc, "decomposition_gate"))           # (r2: never derived from forecast summaries)

    def test_registered_panel_receipt(self):
        """Codex #78 r2 P2-1 (D6 rule 27, §10.5): a separate REGISTERED panel receipt from the fork registry: per origin
        (30, 100, 185M) its primary target (40, 110, 195M), the native component (every native-panel world) and the
        fork component (every root's branches and original) SEPARATELY, each required row's disposition; the pooled
        primary only with all three origins complete. Codex's former 'success' fixture (the native panel at one target
        plus one fork row) FAILS; one absorbed branch makes its origin unavailable; outcomes of a closed stage are
        'not released'; forecast availability never enters."""
        def row(z, ev=None, un=None):
            return {"z": z, "R": None, "g": None, "events": ev or {}, "unavailable": un}
        req = fc.panel_required(self.ctx)
        self.assertEqual({o: r["target"] for o, r in req.items()}, {30: 40, 100: 110, 185: 195})
        nat = len(self.ctx["forks"]["native_panel"])
        self.assertTrue(all(len(r["native"]) == nat for r in req.values()))
        self.assertEqual(sorted(len(r["fork"]) for r in req.values()), sorted(
            sum(1 + len(bs) for (_, t0), bs in self.ctx["fork_origins"].items() if t0 == o) for o in req))
        roles = {"training", "validation", "test"}
        full = {k: row([0.1, 0.2]) for r in req.values() for kind in ("native", "fork") for k in r[kind]}
        P = fc.panel_receipt(self.ctx, full, roles)
        self.assertEqual((P["pooled_primary"], P["schema"]), ({"available": True, "reasons": []}, fc.PANEL_SCHEMA))
        k0 = next(k for k in req[30]["fork"] if k not in req[30]["native"])      # (a branch: a root's original is
        P2 = fc.panel_receipt(self.ctx, {**full, k0: row(None, {"extinction": True})}, roles)   # also its native row)
        o30 = P2["origins"]["30"]
        self.assertEqual((P2["pooled_primary"]["available"], o30["available"], o30["native"]["complete"],
                          o30["fork"]["complete"]), (False, False, True, False))
        self.assertEqual(o30["fork"]["dispositions"][f"{k0[0]}@{k0[1]}"], "absorbed: extinction")
        some = {k: row([0.0, 0.0]) for k in req[100]["native"]}
        some[req[100]["fork"][0]] = row([0.0, 0.0])
        P3 = fc.panel_receipt(self.ctx, some, roles)                  # (the former success fixture: it must fail)
        self.assertFalse(P3["pooled_primary"]["available"])
        self.assertEqual((P3["origins"]["100"]["native"]["complete"], P3["origins"]["100"]["fork"]["complete"]), (True, False))
        self.assertTrue(any("missing" in v for v in P3["origins"]["30"]["native"]["dispositions"].values()))
        P4 = fc.panel_receipt(self.ctx, full, {"training", "validation"})
        self.assertFalse(P4["pooled_primary"]["available"])
        self.assertTrue(any(v.startswith("not released") for o in P4["origins"].values()
                            for kind in ("native", "fork") for v in o[kind]["dispositions"].values()))
        # (Codex #78 r3 P2-1) the MOST RESTRICTIVE registered use: the validation root V0's 185M -> 195M target is
        # read by a test-stage origin (the forward-time test period), so it is not released at the validation stage
        st = fc.panel_row_stages(self.ctx)
        self.assertEqual((fc.node_role(self.ctx["manifest"], "V0", 195), st[("V0", 195)]), ("validation", "test"))
        self.assertEqual(fc.row_stage(self.ctx, st, "V0", 195), "test")
        self.assertTrue(P4["origins"]["185"]["native"]["dispositions"]["V0@195"].startswith("not released (a test-stage"))
        self.assertEqual(P4["origins"]["185"]["fork"]["dispositions"]["V0@195"], P4["origins"]["185"]["native"]["dispositions"]["V0@195"])
        # (Codex #78 r3 P2-2) the release gates are #73's VALIDATED path, never a marker or a file's presence
        nowhere = dict(self.ctx, root=os.path.join(self.tmp, "nowhere"))
        for stage in ("validation", "test"):
            with self.assertRaises((fc.ForecastError, fc.staging.StageError)):
                fc.panel_document(nowhere, self.files["val_targets.json"], stage, self.val)

    def test_end_to_end(self):
        """The staged pipeline runs on a TARGET-DISJOINT registration (no stage's prefix row is one of its
        targets, no validation prefix row a test target, no target a fitting row; in-sample origins
        excluded); registered roles are pooled apart (validation-root V0 and test-root S0 at 185 never share a
        pool); lambda is the argmin over the selection set; provenance, the implementation manifest and the
        scoring environment are recorded."""
        self.assertEqual([r[0] for r in self.rc], [0, 0, 0, 0, 0], [r[1] for r in self.rc])
        for sts in ({"validation"}, {"test", "training"}):
            pre, tgt = fc.stage_rows(self.ctx, sts)
            self.assertEqual(pre & tgt, set())
        self.assertEqual(fc.stage_rows(self.ctx, {"validation"})[0] & fc.stage_rows(self.ctx, {"test"})[1], set())
        self.assertEqual(fc.disjointness_problems(self.ctx, self.ctx["origins"]), [])
        by = self.ctx["by_id"]
        self.assertIn("in-sample", by["fork:T00:30:1"]["excluded"])
        self.assertIn("fork origin's target", by["native:S0:186:10"]["excluded"])      # (its window holds S0@186)
        self.assertNotIn("native:T05:146:1", by)                                       # (not under the split rule)
        self.assertEqual(by["fork:T00:30:4"]["category"], "snapshot_transfer")
        self.assertEqual(by["fork:V0:185:10"]["stage"], "test")
        self.assertEqual(by["native:T02:150:1"]["stage"], "test")                      # (its window holds T02@150)
        p = by["native:T02:147:4"]                                       # (Codex r3: it shares T02@151 with 150:1)
        self.assertEqual((p["stage"], p["promoted"]), ("test", "from validation: it shares an outcome with a test-stage origin"))
        vt = set().union(*[fc.target_rows(o) for o in self.ctx["origins"] if not o["excluded"] and o["stage"] == "validation"])
        tt = set().union(*[fc.target_rows(o) for o in self.ctx["origins"] if not o["excluded"] and o["stage"] == "test"])
        self.assertEqual(vt & tt, set())                                 # (complete panels: no outcome in two stages)
        op = os.path.join(self.tmp, "origins.json")
        self.assertEqual(run(["origins", "--root", self.root, "--out", op])[0], 0)
        od = rqlib.read_json(op)
        self.assertEqual(od["origins_sha256"], self.ctx["origins_sha"])
        self.assertFalse(any("z" in o for o in od["origins"]))
        cats = {(o["category"], o["stage"]) for o in self.ctx["origins"] if not o["excluded"]}
        for want in (("world_transfer", "validation"), ("world_transfer", "test"), ("forward_time", "validation"),
                     ("forward_time", "test"), ("intersection", "validation"), ("intersection", "test"),
                     ("snapshot_transfer", "validation")):
            self.assertIn(want, cats)
        val = [json.loads(ln) for ln in rqlib.read_text(self.val).splitlines()]
        self.assertEqual({ln["stage"] for ln in val}, {"validation"})
        prov = val[0]["provenance"]
        self.assertEqual(prov["model_sha256"], rqlib.sha256_file(self.model))
        self.assertEqual(prov["fit_sha256"], rqlib.sha256_file(self.files["fit.json"]))
        self.assertEqual(val[0]["measurement"], {"fit_groups": [f"fit:{w}" for w in TRAIN], "fit_group": None})
        sc = rqlib.read_json(self.scores)
        self.assertEqual(sc["targets_sha256"], rqlib.sha256_file(self.files["val_targets.json"]))
        rows = [r for r in sc["origins"] if r["available"] and r["primary"] and r["time_role"] == "validation"
                and r["stage"] == "validation"]
        self.assertTrue(rows and {r["category"] for r in rows} == {"forward_time", "intersection"})
        mean = {lam: np.mean([r["metrics"][fc.lss_name(lam)]["mse"] for r in rows]) for lam in (0.1, 100.0)}
        self.assertEqual(sc["selection"]["lambda"], min(mean, key=lambda k: (mean[k], -k)))
        self.assertLess(min(mean.values()), sc["selection"]["reference"]["persistence"])
        src = sc["selection"]["group_sources"]
        self.assertEqual(src["fit"], [f"fit:{w}" for w in TRAIN])                   # (Codex r4: the fit's groups too)
        self.assertTrue(src["windows"] and all(g.startswith("g:") for g in src["windows"] + src["targets"]))
        self.assertEqual(sc["selection"]["groups"], sorted(set(src["fit"] + src["windows"] + src["targets"])))
        tl = [json.loads(x) for x in rqlib.read_text(self.test).splitlines()]
        self.assertEqual(tl[0]["provenance"]["selection_groups"], sc["selection"]["groups"])
        mod = rqlib.read_json(self.model)
        lss01 = next(s for s in mod["lss"] if s["lambda"] == 0.1)
        self.assertTrue(lss01["usable"] and lss01["monotone"])
        self.assertLess(np.max(np.abs(np.array(lss01["Theta"])[:, :2] - np.array(A_TRUE))), 0.12)
        self.assertLess(np.max(np.abs(np.array(lss01["Q"]) - np.array(Q_TRUE))), 0.006)
        ev = rqlib.read_json(self.eval)
        self.assertEqual(ev["TEST_PRED_SHA"], rqlib.sha256_file(self.test))
        self.assertEqual(ev["targets_sha256"], rqlib.sha256_file(self.files["test_targets.json"]))
        self.assertEqual(ev["scoring"]["implementation_sha256"], rqlib.sha256_file(self.impl))
        self.assertIn("environment", ev["scoring"])
        keys = set(ev["pooled"])
        v0 = "test/validation/validation/test/intersection/fork/H10/lss"                # (V0: fed the lambda selection)
        s0 = "test/test/test/test/intersection/fork/H10/lss"                            # (S0, S1: held out throughout)
        self.assertIn(v0, keys)
        self.assertIn(s0, keys)
        # (PR-D, D6 rule 27 §10.6: S1's origin with an extinct future is survivor-conditioned, pooled apart)
        self.assertEqual((ev["pooled"][v0]["worlds"], ev["pooled"][s0]["worlds"]), (1, 1))
        sc0 = ev["pooled"][s0 + "/survivor-conditioned"]
        self.assertEqual((sc0["worlds"], sc0["conditioning"], ev["pooled"][s0]["conditioning"]),
                         (1, "survivor-conditioned", "complete"))
        self.assertIn("test/training/training/test/forward_time/fork/H10/lss", keys)
        for v in ev["pooled"].values():
            self.assertIn(v["category"], fc.CATEGORIES)
        s1 = next(r for r in ev["origins"] if r["target_id"] == "fork:S1:185:10")["metrics"]["lss"]
        self.assertEqual((s1["events"]["extinction"], s1["reseeds"]), (1, 3))
        s0r = next(r for r in ev["origins"] if r["target_id"] == "fork:S0:185:4")["metrics"]["lss"]
        self.assertEqual((s0r["unavailable"], s0r["reseeds"]), (1, 3))
        # (Codex #78 r1 P2-5) every non-excluded origin has its outcome receipt; §10.5 is the separate registered panel
        # receipt (forecast.py panel), never part of the forecast scores (r2 P2-1)
        for doc in (sc, ev):
            self.assertTrue(all((r["outcomes"] is None) == r["excluded"] for r in doc["origins"]))
            self.assertEqual(sum(c["origins"] for c in doc["outcomes"].values()), len(doc["origins"]))
            self.assertNotIn("decomposition_10_5", doc)
        # (the release-stage gates, Codex #78 r3 P2-2) before VAL_PRED_SHA is committed the panel receipt is refused at
        # either stage (the validated commitment / freeze chain, not a marker's presence); on the committed root the
        # validation gate opens, and the test gate needs the frozen test commitment
        base = self.copy(self.base)
        for st in ("validation", "test"):
            rc_, err = run(["panel", "--root", base, "--targets", self.files["val_targets.json"], "--stage", st,
                            "--predictions", self.val, "--out", os.path.join(self.tmp, f"panel.{st}.json")])
            self.assertEqual(rc_, 2, err)
        self.assertIn("not a registered §10.5 panel row", run(["panel", "--root", self.root, "--targets",
                                                               self.files["val_targets.json"], "--stage", "validation",
                                                               "--predictions", self.val, "--out",
                                                               os.path.join(self.tmp, "panel.v.json")])[1])

    def test_reproducible(self):
        """The same bytes and environment give byte-identical outputs at every stage."""
        root = self.copy(self.base)
        mo, vo = os.path.join(self.tmp, "m2.json"), os.path.join(self.tmp, "v2.jsonl")
        self.assertEqual(run(["predict-candidates", "--root", root, "--fit", self.files["fit.json"], "--prefix",
                              self.files["val_prefix.json"], "--model-out", mo, "--out", vo])[0], 0)
        self.assertEqual((rqlib.read_bytes(mo), rqlib.read_bytes(vo)), (rqlib.read_bytes(self.model), rqlib.read_bytes(self.val)))
        so = os.path.join(self.tmp, "s2.json")
        self.assertEqual(run(["score-validation", "--root", self.copy(self.committed), "--predictions", self.val,
                              "--targets", self.files["val_targets.json"], "--out", so])[0], 0)
        self.assertEqual(rqlib.read_bytes(so), rqlib.read_bytes(self.scores))
        to = os.path.join(self.tmp, "t2.jsonl")
        self.assertEqual(run(["predict-test", "--root", self.copy(self.opened), "--prefix", self.files["test_prefix.json"],
                              "--model", self.model, "--selection", self.scores, "--out", to])[0], 0)
        self.assertEqual(rqlib.read_bytes(to), rqlib.read_bytes(self.test))
        eo = os.path.join(self.tmp, "e2.json")
        self.assertEqual(run(["evaluate-test", "--selection", self.scores, "--root", self.copy(self.root), "--predictions", self.test, "--targets",
                              self.files["test_targets.json"], "--out", eo])[0], 0)
        self.assertEqual(rqlib.read_bytes(eo), rqlib.read_bytes(self.eval))

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
            fc.load_profiles(c120, fit, "x" * 64, "fit", fc.fit_admit(c120))

    def test_embargo_guards(self):
        """P1-3: predict-candidates takes no targets; a prefix holding any row outside the stage's registered
        windows is refused on its IDENTITY, before any of its values is read (a target row whose z is not even
        numeric is refused as a membership violation), as is a missing window row; score-validation refuses
        target rows of another stage, missing targets and substituted futures."""
        root = self.copy(self.base)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fc.main(["predict-candidates", "--root", root, "--fit", "f", "--prefix", "p", "--model-out", "m", "--out", "o",
                     "--targets", "t"])
        pre = rqlib.read_json(self.files["val_prefix.json"])
        out = os.path.join(self.tmp, "y.jsonl")
        for extra, why in ((dict(self.rows[("T05", 160)], z="SECRET"), "may not be read at this stage"),
                           (self.rows[("T05", 151)], "not a registered prefix row"),        # (a validation target)
                           (self.rows[("S0", 182)], "not a registered prefix row")):        # (a test-stage row)
            p2 = self.put("prefix.json", dict(pre, rows=pre["rows"] + [extra]))
            rc, err = run(["predict-candidates", "--root", root, "--fit", self.files["fit.json"], "--prefix", p2,
                           "--model-out", os.path.join(self.tmp, "m.json"), "--out", out])
            self.assertEqual(rc, 2)
            self.assertIn(why, err)
            self.assertNotIn("not numeric", err)
        p2 = self.put("prefix.json", dict(pre, rows=pre["rows"][1:]))
        rc, err = run(["predict-candidates", "--root", root, "--fit", self.files["fit.json"], "--prefix", p2,
                       "--model-out", os.path.join(self.tmp, "m.json"), "--out", out])
        self.assertIn("missing", err)
        root = self.copy(self.committed)
        tg = rqlib.read_json(self.files["val_targets.json"])
        sc = os.path.join(self.tmp, "sc.json")
        for rows, why in ((tg["rows"] + [self.rows[("S1", 195)]], "not a target of the committed"),
                          (tg["rows"] + [dict(self.rows[(bid("V0", 30, 1), 34)], t=35)], "not a target"),
                          (tg["rows"][:-1], "missing")):
            t2 = self.put("targets.json", dict(tg, rows=rows))
            rc, err = run(["score-validation", "--root", root, "--predictions", self.val, "--targets", t2, "--out", sc])
            self.assertEqual(rc, 2)
            self.assertIn(why, err)
        self.assertFalse(os.path.exists(sc))

    def test_source_structure(self):
        """Codex r2 P2-5: a measurement group shared with PART of the fit is an unsupported source structure:
        a window in it makes its origin unavailable with the reason (the fixture's snapshot-transfer fork
        origin, whose window is fitting rows; here also a training world's later rows put in its fitting
        group), and a target in it is refused at scoring."""
        val = {ln["target_id"]: ln for ln in map(json.loads, rqlib.read_text(self.val).splitlines())}
        self.assertFalse(val["fork:T00:30:4"]["available"])
        self.assertIn("shared with part of the fit", val["fork:T00:30:4"]["reason"])
        root = self.copy(self.base)
        pre = rqlib.read_json(self.files["val_prefix.json"])
        for r in pre["rows"]:
            if r["world"] == "T05" and "z" in r:
                r["meas_group"] = "fit:T05"
        p2, vo = self.put("prefix.json", pre), os.path.join(self.tmp, "v3.jsonl")
        rc, err = run(["predict-candidates", "--root", root, "--fit", self.files["fit.json"], "--prefix", p2,
                       "--model-out", os.path.join(self.tmp, "m3.json"), "--out", vo])
        self.assertEqual(rc, 0, err)
        t05 = [json.loads(x) for x in rqlib.read_text(vo).splitlines() if '"world":"T05"' in x]
        self.assertTrue(t05 and all(not ln["available"] and "shared with part of the fit" in ln["reason"] for ln in t05))
        root = self.copy(self.committed)
        tg = rqlib.read_json(self.files["val_targets.json"])
        for r in tg["rows"]:
            if r["world"] == "T05" and "z" in r:
                r["meas_group"] = "fit:T05"
        rc, err = run(["score-validation", "--root", root, "--predictions", self.val, "--targets",
                       self.put("t.json", tg), "--out", os.path.join(self.tmp, "s3.json")])
        self.assertEqual(rc, 2)
        self.assertIn("shared with part of the fit", err)

    def test_selection_independence_and_proper_prior(self):
        """Codex r3 P2-4: a test target in a measurement group of the lambda selection's inputs or targets is
        refused at evaluate-test (the selected forecast would depend on that noise; a registration
        requirement). Codex r3 P2-3: under a proper prior, a fit whose profiles all share one group is
        refused (the K loading needs the diffuse prior's translation equivariance)."""
        sel = rqlib.read_json(self.scores)["selection"]["group_sources"]["windows"]
        tg = rqlib.read_json(self.files["test_targets.json"])
        k = next(i for i, r in enumerate(tg["rows"]) if "z" in r and r["world"] == "T05")
        tg["rows"][k]["meas_group"] = sel[0]
        rc, err = run(["evaluate-test", "--selection", self.scores, "--root", self.copy(self.root), "--predictions", self.test, "--targets",
                       self.put("targets.json", tg), "--out", os.path.join(self.tmp, "ev5.json")])
        self.assertEqual(rc, 2)
        self.assertIn("share measurement group", err)
        d = tempfile.mkdtemp(dir=self.tmp)
        rp, _ = make_root(d, {"lss": {"initial_state": {"kind": "proper", "mean": [0.0, 0.0], "cov": [[1.0, 0.0], [0.0, 1.0]]}}})
        fit = rqlib.read_json(self.files["fit.json"])
        for r in fit["rows"]:
            if "z" in r:
                r["meas_group"] = "fit:T00"
        rc, err = run(["predict-candidates", "--root", rp, "--fit", self.put("fit.json", fit), "--prefix",
                       self.files["val_prefix.json"], "--model-out", os.path.join(d, "m.json"), "--out", os.path.join(d, "v.jsonl")])
        self.assertEqual(rc, 2)
        self.assertIn("diffuse initial state only", err)

    def test_fit_group_selection_dependence(self):
        """Codex r4 P2-2, its configuration: the diffuse prior, EVERY fitting profile in one group g (the
        supported K-loading structure), validation windows and targets independent of g. The selection depends
        on u_g through the K_lambda loadings, so g is recorded among the selection's groups (source "fit");
        the pipeline evaluates when the test targets are independent of g, and refuses when one is in g."""
        root = self.copy(self.base)
        tmp = tempfile.mkdtemp(dir=self.tmp)

        def ext(name):                                   # (every fitting measurement, in every document, in glob)
            d = rqlib.read_json(self.files[name])
            d["measurement"]["shared"]["glob"] = (S_SH * np.eye(2)).tolist()
            for r in d["rows"]:
                if "z" in r and str(r.get("meas_group")).startswith("fit:"):
                    r["meas_group"] = "glob"
            p = os.path.join(tmp, name)
            wr(p, d)
            return p
        f = {n: ext(n) for n in ("fit.json", "val_prefix.json", "val_targets.json", "test_prefix.json", "test_targets.json")}
        val, mo, sc, tst = (os.path.join(tmp, n) for n in ("val.jsonl", "model.json", "scores.json", "test.jsonl"))
        self.assertEqual(run(["predict-candidates", "--root", root, "--fit", f["fit.json"], "--prefix", f["val_prefix.json"],
                              "--model-out", mo, "--out", val])[0], 0)
        self.assertEqual(rqlib.read_json(mo)["fit"]["measurement"], {"fit_groups": ["glob"], "fit_group": "glob"})
        sealing.commit(root, "validation", val)
        self.assertEqual(run(["score-validation", "--root", root, "--predictions", val, "--targets", f["val_targets.json"],
                              "--out", sc])[0], 0)
        sel = rqlib.read_json(sc)["selection"]
        self.assertIn("glob", sel["groups"])
        self.assertEqual(sel["group_sources"]["fit"], ["glob"])
        self.assertNotIn("glob", sel["group_sources"]["windows"] + sel["group_sources"]["targets"])
        sealing.open_validation(root, sc)
        self.assertEqual(run(["predict-test", "--root", root, "--prefix", f["test_prefix.json"], "--model", mo,
                              "--selection", sc, "--out", tst])[0], 0)
        sealing.commit(root, "test", tst, self.impl)
        sealing.freeze(root, self.prereg, self.impl, osf_url="https://osf.io/abc12", registered_utc=rqlib.now_utc())
        ev = os.path.join(tmp, "ev.json")
        rc, err = run(["evaluate-test", "--selection", sc, "--root", root, "--predictions", tst, "--targets",
                       f["test_targets.json"], "--out", ev])
        self.assertEqual(rc, 0, err)
        tt = rqlib.read_json(f["test_targets.json"])
        k = next(i for i, r in enumerate(tt["rows"]) if "z" in r and r["world"] == "T05")
        tt["rows"][k]["meas_group"] = "glob"
        rc, err = run(["evaluate-test", "--selection", sc, "--root", root, "--predictions", tst, "--targets",
                       self.put("targets.json", tt), "--out", ev])
        self.assertEqual(rc, 2)
        self.assertIn("share measurement group(s) ['glob'] with the fitting profiles", err)

    def test_selection_metadata(self):
        """Codex r4 P2-3: evaluate-test takes the selection's groups ONLY from the score document the frozen
        validation-evaluation record names: committed and frozen test lines whose group metadata is omitted,
        [] or substituted are refused, as is another score document."""
        for name, mutate in (("omitted", lambda p: p.pop("selection_groups")),
                             ("empty", lambda p: p.__setitem__("selection_groups", [])),
                             ("substituted", lambda p: p.__setitem__("selection_groups", ["g:NOPE"]))):
            root = self.copy(self.opened)
            lines = [json.loads(x) for x in rqlib.read_text(self.test).splitlines()]
            for ln in lines:
                mutate(ln["provenance"])
            tp = self.put("test.jsonl", staging.jsonl_bytes(lines).decode())
            sealing.commit(root, "test", tp, self.impl)
            sealing.freeze(root, self.prereg, self.impl, osf_url="https://osf.io/abc12", registered_utc=rqlib.now_utc())
            rc, err = run(["evaluate-test", "--selection", self.scores, "--root", root, "--predictions", tp, "--targets",
                           self.files["test_targets.json"], "--out", os.path.join(self.tmp, "ev6.json")])
            self.assertEqual(rc, 2, name)
            self.assertIn("selection-group metadata that is missing or not the verified selection's", err)
        s = rqlib.read_json(self.scores)
        other = self.put("scores.json", dict(s, selection=dict(s["selection"], groups=[])))
        rc, err = run(["evaluate-test", "--selection", other, "--root", self.copy(self.root), "--predictions", self.test,
                       "--targets", self.files["test_targets.json"], "--out", os.path.join(self.tmp, "ev7.json")])
        self.assertEqual(rc, 2)
        self.assertIn("not the validation scores the frozen validation-evaluation record names", err)

    def test_commitment_guards(self):
        """P1-4 / P1-5: scoring needs the committed bytes; predict-test needs the scores recorded by open-
        validation and the model they name; evaluate-test needs the public freeze and the committed test
        predictions, and scores the verified bytes even if the file changes after the gate. Codex r2 P1-3:
        the validation-evaluation record substituted BEFORE the gate is refused; substituted AFTER it, the
        verified record is the one checked."""
        sc = os.path.join(self.tmp, "sc2.json")
        rc, err = run(["score-validation", "--root", self.copy(self.precommit), "--predictions", self.val, "--targets",
                       self.files["val_targets.json"], "--out", sc])
        self.assertIn("no VAL_PRED_SHA", err)
        root = self.copy(self.committed)
        v2 = self.put("val.jsonl", rqlib.read_text(self.val).replace('"available":true', '"available":true ', 1))
        rc, err = run(["score-validation", "--root", root, "--predictions", v2, "--targets", self.files["val_targets.json"],
                       "--out", sc])
        self.assertIn("not the committed validation predictions", err)
        t2 = os.path.join(self.tmp, "t2x.jsonl")
        rc, err = run(["predict-test", "--root", root, "--prefix", self.files["test_prefix.json"], "--model", self.model,
                       "--selection", self.scores, "--out", t2])
        self.assertIn("not recorded", err)
        root = self.copy(self.opened)
        s = rqlib.read_json(self.scores)
        s2 = self.put("val_scores.json", dict(s, selection=dict(s["selection"], **{"lambda": 100.0 if s["selection"]["lambda"] == 0.1 else 0.1})))
        rc, err = run(["predict-test", "--root", root, "--prefix", self.files["test_prefix.json"], "--model", self.model,
                       "--selection", s2, "--out", t2])
        self.assertIn("not the validation scores recorded", err)
        m2 = self.put("model.json", rqlib.read_text(self.model).replace('"usable":true', '"usable":true ', 1))
        rc, err = run(["predict-test", "--root", root, "--prefix", self.files["test_prefix.json"], "--model", m2,
                       "--selection", self.scores, "--out", t2])
        self.assertIn("not the model state", err)
        ev = os.path.join(self.tmp, "ev2.json")
        rc, err = run(["evaluate-test", "--selection", self.scores, "--root", self.copy(self.unfrozen), "--predictions", self.test, "--targets",
                       self.files["test_targets.json"], "--out", ev])
        self.assertIn("no public freeze record", err)
        fresh = self.put("test.jsonl", rqlib.read_text(self.test).replace('"available":true', '"available":true ', 1))
        rc, err = run(["evaluate-test", "--selection", self.scores, "--root", self.copy(self.root), "--predictions", fresh, "--targets",
                       self.files["test_targets.json"], "--out", ev])
        self.assertIn("not the committed test predictions", err)
        # the validation-evaluation record, BEFORE the gate
        root = self.copy(self.root)
        vp = os.path.join(root, "registration", "validation_evaluation.json")
        rec = rqlib.read_json(vp)
        os.chmod(vp, 0o644)
        rqlib.write_durable(vp, rqlib.canonical(dict(rec, scores_sha256="0" * 64)))
        rc, err = run(["evaluate-test", "--selection", self.scores, "--root", root, "--predictions", self.test, "--targets",
                       self.files["test_targets.json"], "--out", ev])
        self.assertEqual(rc, 2)
        self.assertIn("not the validation evaluation the freeze recorded", err)
        # ... AFTER the gate (and the predictions file too): the verified bytes are the ones used
        root = self.copy(self.root)
        tp = self.put("test.jsonl", rqlib.read_text(self.test))
        real = sealing.require_test_freeze

        def gate_then_swap(study, pred_path, script, script_bytes=None):
            got = real(study, pred_path, script, script_bytes=script_bytes)
            wr(pred_path, "garbage\n")
            v = os.path.join(study, "registration", "validation_evaluation.json")
            os.chmod(v, 0o644)
            rqlib.write_durable(v, rqlib.canonical(dict(rqlib.read_json(v), scores_sha256="0" * 64)))
            return got
        sealing.require_test_freeze = gate_then_swap
        try:
            rc, err = run(["evaluate-test", "--selection", self.scores, "--root", root, "--predictions", tp, "--targets", self.files["test_targets.json"],
                           "--out", ev])
        finally:
            sealing.require_test_freeze = real
        self.assertEqual(rc, 0, err)
        self.assertEqual(rqlib.read_json(ev)["TEST_PRED_SHA"], rqlib.sha256_file(self.test))

    def _evaluate_subprocess(self, script, env_pylib):
        env = dict(os.environ)
        if env_pylib is None:
            env.pop("RQ_PYLIB", None)
        else:
            env["RQ_PYLIB"] = env_pylib
        ev = os.path.join(tempfile.mkdtemp(dir=self.tmp), "ev.json")
        p = subprocess.run([sys.executable, "-I", script, "evaluate-test", "--selection", self.scores, "--root", self.copy(self.root), "--predictions",
                            self.test, "--targets", self.files["test_targets.json"], "--out", ev],
                           env=env, capture_output=True, text=True)
        return p.returncode, p.stderr

    def test_implementation_freeze(self):
        """Codex r2 P1-2: the freeze covers the implementation as LOADED: the unchanged tool evaluates in a
        fresh process; a copy of the tool whose imported helper (staging.py) differs by one comment is
        refused, as is the original tool with an RQ_PYLIB directory shadowing rqlib.py."""
        pylib = os.environ.get("RQ_PYLIB")
        rc, err = self._evaluate_subprocess(os.path.join(HERE, "forecast.py"), pylib)
        self.assertEqual(rc, 0, err)
        tools = os.path.join(tempfile.mkdtemp(dir=self.tmp), "tools")
        os.makedirs(tools)
        for n in ("forecast.py", "staging.py", "sealing.py", "rqlib.py"):
            shutil.copy(os.path.join(HERE, n), tools)
        with open(os.path.join(tools, "staging.py"), "a") as f:
            f.write("\n# a changed helper\n")
        rc, err = self._evaluate_subprocess(os.path.join(tools, "forecast.py"), pylib)
        self.assertEqual(rc, 2)
        self.assertIn("not the frozen evaluation script", err)
        shadow = os.path.join(tempfile.mkdtemp(dir=self.tmp), "pylib")
        os.makedirs(shadow)
        if pylib:
            for n in os.listdir(pylib):
                if n != "rqlib.py":
                    os.symlink(os.path.join(pylib, n), os.path.join(shadow, n))
        with open(os.path.join(HERE, "rqlib.py")) as f:
            src = f.read()
        wr(os.path.join(shadow, "rqlib.py"), src + "\n# a shadowing copy\n")
        rc, err = self._evaluate_subprocess(os.path.join(HERE, "forecast.py"), shadow)
        self.assertEqual(rc, 2)
        self.assertIn("not the frozen evaluation script", err)

    def test_executed_bytes(self):
        """Codex r3 P2-2: the hashed bytes ARE the executed code. A copy of the tool whose __pycache__ holds a
        timestamp-valid, sabotaged staging bytecode (a plain import of staging would run it) evaluates
        correctly: the helpers are compiled from the source bytes hashed, never from bytecode. The manifest
        hashes a module's executed bytes, not its file; a helper not loaded from verified bytes is refused;
        numpy is bound by its distribution (RECORD) and its core / linalg / random / BLAS files."""
        import importlib._bootstrap_external as be
        import importlib.util
        import types
        tools = os.path.join(tempfile.mkdtemp(dir=self.tmp), "tools")
        os.makedirs(tools)
        for n in ("forecast.py", "staging.py", "sealing.py", "rqlib.py"):
            shutil.copy2(os.path.join(HERE, n), tools)
        src = os.path.join(tools, "staging.py")
        with open(src) as f:
            bad = f.read() + "\nraise RuntimeError('SABOTAGED bytecode executed')\n"
        st = os.stat(src)
        pyc = importlib.util.cache_from_source(src)
        os.makedirs(os.path.dirname(pyc), exist_ok=True)
        with open(pyc, "wb") as f:
            f.write(be._code_to_timestamp_pyc(compile(bad, src, "exec"), int(st.st_mtime), st.st_size))
        env = dict(os.environ)
        p = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {tools!r}); "
                            f"sys.path.insert(0, {os.environ.get('RQ_PYLIB') or tools!r}); import staging"],
                           env=env, capture_output=True, text=True)
        self.assertIn("SABOTAGED", p.stderr)                               # (a plain import runs the bytecode)
        rc, err = self._evaluate_subprocess(os.path.join(tools, "forecast.py"), os.environ.get("RQ_PYLIB"))
        self.assertEqual(rc, 0, err)                                         # (the tool runs the hashed source)
        fake = types.ModuleType("rqfake")
        fake.__rq_source__, fake.__file__ = b"x = 1\n", os.path.join(HERE, "rqlib.py")
        sys.modules["rqfake"] = fake
        try:
            doc = json.loads(staging.implementation_manifest(fc, modules=("rqfake",)))
            self.assertEqual(doc["modules"]["rqfake"], {"sha256": rqlib.sha256_bytes(b"x = 1\n"), "source": "x = 1\n"})
            del fake.__rq_source__
            with self.assertRaisesRegex(staging.StageError, "not loaded from verified source bytes"):
                staging.implementation_manifest(fc, modules=("rqfake",))
        finally:
            del sys.modules["rqfake"]
        impl = rqlib.read_json(self.impl)
        self.assertEqual(impl["modules"]["staging"]["sha256"], rqlib.sha256_file(os.path.join(HERE, "staging.py")))
        self.assertIn("def implementation_manifest", impl["modules"]["staging"]["source"])   # (the deposit carries it)
        b = impl["numpy"]
        self.assertEqual(b["version"], np.__version__)
        files = b["files"]
        for part in ("numpy/lib/", "numpy/linalg/", "numpy/_core/", "numpy/random/"):   # (Codex r4: np.cov's numpy.lib)
            self.assertTrue(any(k.startswith(part) for k in files), part)
        self.assertTrue(any(k.startswith("numpy.libs/") for k in files))
        pkg = os.path.dirname(np.__file__)
        pycs = [os.path.relpath(os.path.join(d, n), os.path.dirname(pkg)).replace(os.sep, "/")
                for d, _, ns in os.walk(pkg) for n in ns if n.endswith(".pyc")]
        self.assertTrue(set(pycs) <= set(files))                          # (every bytecode it may execute is bound)
        self.assertTrue(rqlib.is_sha256(b["record_sha256"]) and b["record_entries_verified"] > 100)

    def test_redirected_bytecode_cache_refused(self):
        """Codex r5: with a redirected bytecode cache (-X pycache_prefix), the interpreter reads bytecode
        outside the inventoried trees, so an implementation manifest is neither built nor verified: in a fresh
        process `implementation` and `evaluate-test` both refuse; the frozen manifest records no prefix."""
        self.assertIsNone(rqlib.read_json(self.impl)["python"]["pycache_prefix"])
        env = dict(os.environ)
        cache = tempfile.mkdtemp(dir=self.tmp)
        out = os.path.join(cache, "impl.json")
        for args in (["implementation", "--out", out],
                     ["evaluate-test", "--selection", self.scores, "--root", self.copy(self.root), "--predictions", self.test,
                      "--targets", self.files["test_targets.json"], "--out", os.path.join(cache, "ev.json")]):
            p = subprocess.run([sys.executable, "-I", "-X", f"pycache_prefix={cache}", os.path.join(HERE, "forecast.py")] + args,
                               env=env, capture_output=True, text=True)
            self.assertEqual(p.returncode, 2, (args[0], p.stderr))
            self.assertIn("sys.pycache_prefix is set", p.stderr)
        self.assertFalse(os.path.exists(out))

    def test_record_verification(self):
        """Codex r4 P2-1: every RECORD entry's sha256 is checked against the installed file: a changed file and
        a missing one are reported; hashless entries (the RECORD) and bytecode entries are skipped (a shipped
        .pyc rewritten by the installer's byte-compilation, as numpy 2.2's wheel for Python 3.10 has, is bound by
        its own file hash in the manifest instead)."""
        import base64
        d = tempfile.mkdtemp(dir=self.tmp)
        wr(os.path.join(d, "pkg", "a.py"), "a = 1\n")
        wr(os.path.join(d, "pkg", "b.so"), "binary\n")

        def b64(text):
            return base64.urlsafe_b64encode(bytes.fromhex(rqlib.sha256_bytes(text.encode()))).rstrip(b"=").decode()
        wr(os.path.join(d, "pkg", "__pycache__", "d.cpython-310.pyc"), "recompiled by the installer\n")
        rec = (f"pkg/a.py,sha256={b64('a = 1' + chr(10))},6\npkg/b.so,sha256={b64('other' + chr(10))},6\n"
               f"pkg/c.py,sha256={b64('c' + chr(10))},2\npkg/__pycache__/a.cpython-312.pyc,,\npkg-1.dist-info/RECORD,,\n"
               f"pkg/__pycache__/d.cpython-310.pyc,sha256={b64('as shipped' + chr(10))},11\n")   # (numpy 2.2's wheel)
        probs = staging.record_problems(d, rec, rqlib.sha256_file)
        self.assertEqual(len(probs), 2, probs)
        self.assertTrue(probs[0].startswith("pkg/b.so: not the installed") and probs[1] == "pkg/c.py: missing")

    def test_panel_verification(self):
        """P2-13: the registered fork panel: a dropped branch, an unregistered branch, a branch row with
        another branch's identity, a future at an unregistered horizon are refused; invalid covariances
        are refused; Codex r2 P2-7: contradictory rows (a profile with an absorbing event, an event with an
        unavailable reason, a profile with an unavailable reason) are refused."""
        root = self.copy(self.root)
        tg = rqlib.read_json(self.files["test_targets.json"])
        ev = os.path.join(self.tmp, "ev3.json")
        b0, b1 = bid("S0", 185, 0), bid("S0", 185, 1)
        k1 = next(i for i, r in enumerate(tg["rows"]) if r["world"] == b1 and r["t"] == 195)
        ke = next(i for i, r in enumerate(tg["rows"]) if r["world"] == bid("S1", 185, 2) and r["t"] == 195)

        def variant(fn):
            rows = json.loads(json.dumps(tg["rows"]))
            fn(rows)
            return self.put("targets.json", dict(tg, rows=rows))
        cases = [(lambda rs: rs.pop(k1), "missing"),
                 (lambda rs: rs.append(dict(rs[k1], world="S0.o185M.s9", uuid=None)), "not in the split manifest"),
                 (lambda rs: rs[k1].update(uuid=buuid(b0)), "UUID"),
                 (lambda rs: rs.append(dict(rs[k1], t=190)), "not a target"),
                 (lambda rs: rs[k1].update(cov=[[0.003, 0.001], [0.0, 0.003]]), "not symmetric"),
                 (lambda rs: rs[k1].update(cov=[[0.003, 0.0], [0.0, -0.001]]), "positive semidefinite"),
                 (lambda rs: rs[k1].update(cov=[[float("nan"), 0.0], [0.0, 0.003]]), "finite"),
                 (lambda rs: rs[k1].update(cov=[[0.0005, 0.0], [0.0, 0.0005]]), "shared component"),
                 (lambda rs: rs[k1].update(unavailable="assay failed"), "a profile and an unavailable reason"),
                 (lambda rs: rs[k1].update(events={"extinction": True}), "a profile and an absorbing event"),
                 (lambda rs: rs[ke].update(unavailable="assay failed"), "an absorbing event and an unavailable")]
        for fn, why in cases:
            rc, err = run(["evaluate-test", "--selection", self.scores, "--root", root, "--predictions", self.test, "--targets", variant(fn), "--out", ev])
            self.assertEqual(rc, 2, why)
            self.assertIn(why, err)

    def test_config_registry_and_classification(self):
        """P1-7: horizons and the primary come from the registered configuration (bound to the fork registry);
        the separation is checked; counts must be positive; a registered configuration is never replaced and
        follows no candidate. Codex r2 P2-6: the fork registry is read once, and a replaced registry is
        refused. Codex r2 P1-1: a registration that is not target-disjoint is refused."""
        for over, why in (({"primary": 4}, "fork registry's horizon"),
                          ({"temporal": {"validation": [131, 160]}}, "separation"),
                          ({"evaluation": {"bootstrap": 0}}, "bootstrap"),
                          ({"horizons": [10, 4]}, "ascending"),
                          ({"temporal": {"inputs_through": {"validation": 155, "test": 190}}}, "inputs_through")):
            d = tempfile.mkdtemp(dir=self.tmp)
            with self.assertRaisesRegex(fc.ForecastError, why):
                make_root(d, over)
        root = self.copy(self.base)
        cfg = rqlib.read_json(self.cfg_path)
        cp = self.put("cfg.json", dict(cfg, window=4))
        with self.assertRaisesRegex(fc.ForecastError, "never replaced"):
            fc.register(root, cp)
        fc.register(root, self.cfg_path)
        d = tempfile.mkdtemp(dir=self.tmp)
        r2, c2 = make_root(d, register=False)
        os.makedirs(os.path.join(r2, "registration"), exist_ok=True)
        wr(os.path.join(r2, "registration", "VAL_PRED_SHA"), "0" * 64 + "\n")
        with self.assertRaisesRegex(fc.ForecastError, "before the candidates"):
            fc.register(r2, c2)
        # the fork registry: read exactly once per context; replaced bytes refused
        reads, real = [], rqlib.read_bytes

        def counting(p):
            reads.append(os.path.basename(p))
            return real(p)
        rqlib.read_bytes = counting
        try:
            fc.load_ctx(root)
        finally:
            rqlib.read_bytes = real
        self.assertEqual((reads.count("forks.json"), reads.count("splits.json"), reads.count("forecast.json")), (1, 1, 1))
        fp = os.path.join(root, "config", "forks.json")
        forks = rqlib.read_json(fp)
        forks["worlds"] = [b for b in forks["worlds"] if b["id"] != bid("S0", 185, 3)]
        wr(fp, rqlib.canonical(forks).decode())
        with self.assertRaisesRegex(fc.ForecastError, "not the registered fork registry"):
            fc.load_ctx(root)
        # a registration whose fork windows hold native targets is not target-disjoint
        d = tempfile.mkdtemp(dir=self.tmp)
        with self.assertRaisesRegex(fc.ForecastError, "not target-disjoint"):
            make_root(d, {"temporal": {"validation": [141, 160], "test": [176, 200], "separation": 15,
                                       "inputs_through": {"validation": 150, "test": 182}}})
            fc.load_ctx(os.path.join(d, "root"))


if __name__ == "__main__":
    unittest.main()

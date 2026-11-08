#!/usr/bin/env python3
"""backbone.py: the confirmatory backbone's frozen estimators (Annex H.1-H.2, H.5's slopes; design v4
§8; (d) item 5, part 2). numpy; deterministic. The decisions and resampling live in stats.py.

H.1 THE DIRECTIONAL MEAN-FITTING PRIMITIVE (independent of the Level-1 map fitter). For a focal-time
interval [L, U] (full history [0, 200] M; an epoch its nominal boundaries), z = (t - L) / (U - L) and six
cubic B-splines on the knots (0, 0, 0, 0, 1/3, 2/3, 1, 1, 1, 1), evaluated at ACTUAL times (F1 = 1e-6 M).
Every coefficient is world-specific; no pooling, no validation-selected penalty.
  capture: for each fixed prey opponent i, mu_wi(t) = sigma(B(z)'gamma_wi), minimizing the mean
    quasi-likelihood sum_{j,r} [B_wijr log(1 + exp(eta)) - C_wijr eta] + 1e-6/2 |gamma|^2 (Newton);
    l_wij = logit mu_wi(t_j) (no pseudocounts: zeros stay zeros).
  survival: for a prey time t and fixed predator opponents j, logit mu0_w(t) = B'c_w (the predator-free
    controls) and logit muS_wj(t) = B'(c_w + d_wj), fitted JOINTLY (600-trial binomial quasi-likelihood
    of the free and exposed observations, each free observation once, + 1e-6/2 |all coefficients|^2);
    q_wj(t) = muS_wj(t) - mu0_w(t) (a positive q is kept).
H.2 H-P / H-Q. m^P_w(t_j) = mean_i l_wij over the 41-member coarse prey panel; m^Q_w(t_i) = mean_j q_wij
  over the coarse predator panel; beta_hw = the equal-weight linear projection of m^h_w on x = t / 50
  over the coarse times (stats.projection); the population estimate is the mean over worlds, its SE
  sd / sqrt(n) (stats.mean_se), tested by stats.cluster_test (unpooled fits: a world's slope is cached).
H.5 H-C slopes. The four neural references and the scripted benchmark are fitted jointly with the free
  control (one shared baseline); beta_N is the slope of the uniform average of the four references' q,
  beta_S the scripted q's; d_w = beta_N - beta_S (the baseline cancels exactly in d_w).
"""
from __future__ import annotations

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
import numpy as np  # noqa: E402

import stats  # noqa: E402

KNOTS = np.array([0, 0, 0, 0, 1 / 3, 2 / 3, 1, 1, 1, 1], float)
PENALTY = 1e-6
FULL = (0.0, 200.0)
EPOCHS = {"E1": (0.0, 50.0), "E2": (75.0, 125.0), "E3": (150.0, 200.0)}
TRIALS = 600


class BackboneError(Exception):
    pass


def bspline(z):
    """The six cubic B-splines at z in [0, 1] (Cox-de Boor; z = 1 belongs to the last interval)."""
    z = np.clip(np.atleast_1d(np.asarray(z, float)), 0.0, 1.0)
    B = np.zeros((len(z), len(KNOTS) - 1))
    for i in range(len(KNOTS) - 1):
        B[:, i] = (KNOTS[i] <= z) & (z < KNOTS[i + 1])
    B[z == 1.0, 5] = 1.0                       # (z = 1: the last nonempty interval, [2/3, 1])
    for d in range(1, 4):
        nb = np.zeros((len(z), len(KNOTS) - 1 - d))
        for i in range(len(KNOTS) - 1 - d):
            a = (z - KNOTS[i]) / (KNOTS[i + d] - KNOTS[i]) * B[:, i] if KNOTS[i + d] > KNOTS[i] else 0.0
            b = ((KNOTS[i + d + 1] - z) / (KNOTS[i + d + 1] - KNOTS[i + 1]) * B[:, i + 1]
                 if KNOTS[i + d + 1] > KNOTS[i + 1] else 0.0)
            nb[:, i] = a + b
        B = nb
    return B


def basis(t, interval=FULL):
    L, U = interval
    return bspline((np.asarray(t, float) - L) / (U - L))


def _sigma(x):
    return 1.0 / (1.0 + np.exp(-x))


def _newton(X, succ, trials, pen=PENALTY, iters=100, tol=1e-12):
    """argmin sum [n log(1 + e^eta) - y eta] + pen/2 |gamma|^2, eta = X gamma (Newton, a convex problem)."""
    g = np.zeros(X.shape[1])
    for _ in range(iters):
        eta = X @ g
        mu = _sigma(eta)
        grad = X.T @ (trials * mu - succ) + pen * g
        H = X.T @ (X * (trials * mu * (1 - mu))[:, None]) + pen * np.eye(X.shape[1])
        step = np.linalg.solve(H, grad)
        g = g - step
        if np.max(np.abs(step)) < tol:
            break
    if not np.all(np.isfinite(g)):
        raise BackboneError("the quasi-likelihood fit did not converge")
    return g


def fit_capture(times, captures, bounds, interval=FULL):
    """One fixed prey opponent's capture curve: times (focal predator times, M), captures and bounds
    (summed over replicates or not: the loss is additive) -> gamma (6,)."""
    X = basis(times, interval)
    return _newton(X, np.asarray(captures, float), np.asarray(bounds, float))


def logit_curve(gamma, times, interval=FULL):
    return basis(times, interval) @ gamma


def fit_captures(times, captures, bounds, interval=FULL, pen=PENALTY, iters=100, tol=1e-12):
    """fit_capture for K opponents observed at the SAME focal times, batched (identical iterates):
    captures, bounds (K x m) -> gammas (K x 6)."""
    X = basis(times, interval)
    Y, N = np.atleast_2d(np.asarray(captures, float)), np.atleast_2d(np.asarray(bounds, float))
    g = np.zeros((Y.shape[0], X.shape[1]))
    I = np.eye(X.shape[1])
    for _ in range(iters):
        mu = _sigma(g @ X.T)
        grad = (N * mu - Y) @ X + pen * g
        H = np.einsum("km,ma,mb->kab", N * mu * (1 - mu), X, X) + pen * I
        step = np.linalg.solve(H, grad[:, :, None])[:, :, 0]
        g = g - step
        if np.max(np.abs(step)) < tol:
            break
    if not np.all(np.isfinite(g)):
        raise BackboneError("the quasi-likelihood fit did not converge")
    return g


def fit_survival(free, exposed, interval=FULL, trials=TRIALS, pen=PENALTY, iters=100, tol=1e-12):
    """The joint survival fit of one world (fit_survival_dense's estimator and Newton iterates, by the
    arrowhead structure of its Hessian: the shared c block bordered by independent d_k blocks; a Schur
    complement solve, O(K) instead of O(K^3))."""
    keys = sorted(exposed)
    ft, fs = free
    Xf = basis(ft, interval)
    yf = np.asarray(fs, float)
    Xs = [basis(exposed[k][0], interval) for k in keys]
    ys = [np.asarray(exposed[k][1], float) for k in keys]
    c = np.zeros(6)
    d = np.zeros((len(keys), 6))
    I = np.eye(6)
    for _ in range(iters):
        mu = _sigma(Xf @ c)
        gc = Xf.T @ (trials * mu - yf) + pen * c
        Hcc = Xf.T @ (Xf * (trials * mu * (1 - mu))[:, None]) + pen * I
        gd, Hkk, Hck = [], [], []
        for k, (X, y) in enumerate(zip(Xs, ys)):
            m = _sigma(X @ (c + d[k]))
            r = X.T @ (trials * m - y)
            A = X.T @ (X * (trials * m * (1 - m))[:, None])
            gc += r
            Hcc += A
            gd.append(r + pen * d[k])
            Hkk.append(A + pen * I)
            Hck.append(A)
        S, rhs, sol = Hcc.copy(), gc.copy(), []
        for k in range(len(keys)):
            Ki = np.linalg.solve(Hkk[k], np.column_stack([Hck[k].T, gd[k]]))     # Hkk^-1 [Hck', g_k]
            S -= Hck[k] @ Ki[:, :6]
            rhs -= Hck[k] @ Ki[:, 6]
            sol.append(Ki)
        dc = np.linalg.solve(S, rhs)
        dd = np.array([Ki[:, 6] - Ki[:, :6] @ dc for Ki in sol]) if keys else d
        c, d = c - dc, d - dd
        if max(np.max(np.abs(dc)), np.max(np.abs(dd)) if len(keys) else 0.0) < tol:
            break
    if not (np.all(np.isfinite(c)) and np.all(np.isfinite(d))):
        raise BackboneError("the quasi-likelihood fit did not converge")
    return c, {key: d[n_] for n_, key in enumerate(keys)}


def fit_survival_dense(free, exposed, interval=FULL, trials=TRIALS):
    """The joint survival fit of one world. free: (times, survivors) of the predator-free controls (each
    observation once); exposed: {opponent: (times, survivors)} -> (c (6,), {opponent: d (6,)})."""
    keys = sorted(exposed)
    k = len(keys)
    rows, succ = [], []
    ft, fs = free
    Xf = basis(ft, interval)
    rows.append(np.hstack([Xf, np.zeros((len(ft), 6 * k))]))
    succ.append(np.asarray(fs, float))
    for n_, key in enumerate(keys):
        et, es = exposed[key]
        Xe = basis(et, interval)
        blk = np.zeros((len(et), 6 * k))
        blk[:, 6 * n_:6 * n_ + 6] = Xe
        rows.append(np.hstack([Xe, blk]))
        succ.append(np.asarray(es, float))
    X = np.vstack(rows)
    y = np.concatenate(succ)
    g = _newton(X, y, np.full(len(y), float(trials)))
    return g[:6], {key: g[6 + 6 * n_:12 + 6 * n_] for n_, key in enumerate(keys)}


def q_curve(c, d, times, interval=FULL):
    Bt = basis(times, interval)
    return _sigma(Bt @ (c + d)) - _sigma(Bt @ c)


def slope(times_m, values):
    """The H.2 projection slope per 50M of a fitted mean response at the focal times (in M)."""
    return stats.projection([t / 50.0 for t in times_m], list(values))[0]


# ================================================================== per-world H-P / H-Q
def hp_world(capture, focal_times, interval=FULL):
    """H-P slope of one world. capture: {prey opponent time: (predator times, captures, bounds)} (the
    coarse prey panel); focal_times: the coarse predator times (M) the response is evaluated at."""
    if not capture:
        raise BackboneError("no capture panel")
    focal = np.asarray(focal_times, float)
    keys = sorted(capture)
    t0 = np.asarray(capture[keys[0]][0], float)
    if all(np.array_equal(np.asarray(capture[k][0], float), t0) for k in keys):     # (batched, identical)
        G = fit_captures(t0, [capture[k][1] for k in keys], [capture[k][2] for k in keys], interval)
        m = np.mean(basis(focal, interval) @ G.T, axis=1)
        return slope(focal, m), m
    m = np.zeros(len(focal))
    for key in keys:
        t, c, b = capture[key]
        m += logit_curve(fit_capture(t, c, b, interval), focal, interval)
    m /= len(capture)
    return slope(focal, m), m


def hq_world(free, exposed, focal_times, interval=FULL):
    """H-Q slope of one world: the joint survival fit; m^Q(t) the mean over the opponents of q(t)."""
    c, ds = fit_survival(free, exposed, interval)
    focal = np.asarray(focal_times, float)
    m = np.mean([q_curve(c, ds[k], focal, interval) for k in sorted(ds)], axis=0)
    return slope(focal, m), m


def hc_world(free, neural, scripted, focal_times, interval=FULL):
    """H-C's world contrast d_w = beta_N - beta_S: the four neural references and the scripted benchmark
    fitted jointly with the shared free control; beta_N from the uniform average of the references' q."""
    exposed = {("N", k): v for k, v in neural.items()}
    exposed[("S", 0)] = scripted
    c, ds = fit_survival(free, exposed, interval)
    focal = np.asarray(focal_times, float)
    qn = np.mean([q_curve(c, ds[("N", k)], focal, interval) for k in sorted(neural)], axis=0)
    qs = q_curve(c, ds[("S", 0)], focal, interval)
    bn, bs = slope(focal, qn), slope(focal, qs)
    return {"beta_N": bn, "beta_S": bs, "d": bn - bs}


def directional_test(world_slopes, hypothesis, delta, draws=stats.B_BOOT):
    """The H.2 test of a mean of per-world slopes {world id: slope} (unpooled fits: cached), with the
    registered bootstrap stream and material scale."""
    ids = sorted(world_slopes)
    vals = [float(world_slopes[w]) for w in ids]
    if not all(math.isfinite(v) for v in vals):
        return {"available": False, "reason": "a nonfinite world slope"}
    return stats.cluster_test(vals, stats.mean_se, draws=draws, rng=stats.bootstrap_stream(hypothesis, "slope"),
                              delta=delta)

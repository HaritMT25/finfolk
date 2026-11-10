#!/usr/bin/env python3
"""backbone.py: the confirmatory backbone's frozen estimators (Annex H.1-H.2, H.5's slopes; design v4
§8; (d) item 5, part 2). numpy; deterministic. The decisions and resampling live in stats.py.

H.1 THE DIRECTIONAL MEAN-FITTING PRIMITIVE (independent of the Level-1 map fitter). For a focal-time
interval [L, U] (full history [0, 200] M; an epoch its nominal boundaries), z = (t - L) / (U - L) and six
cubic B-splines on the knots (0, 0, 0, 0, 1/3, 2/3, 1, 1, 1, 1), evaluated at ACTUAL times (F1 = 1e-6 M).
Every coefficient is world-specific; no pooling, no validation-selected penalty. An epoch fit takes the
epoch's own focal observations only (every opponent kept, its out-of-epoch rows dropped; the basis
refuses a time outside its interval rather than clamping it). Fits are safeguarded Newton (Armijo step
halving) and must CONVERGE: an exhausted iteration budget or a failed step is a BackboneError (the
analysis then unavailable), never a returned last iterate.
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


def in_interval(t, interval, what="a time"):
    """Times outside the scope's interval are refused (#68 review 6: the basis never clamps an
    out-of-epoch observation into an endpoint likelihood); 1e-9 M of float tolerance."""
    L, U = interval
    t = np.asarray(t, float)
    bad = (t < L - 1e-9) | (t > U + 1e-9) | ~np.isfinite(t)
    if bad.any():
        raise BackboneError(f"{int(bad.sum())} {what}(s) outside the interval [{L}, {U}] (e.g. {t[bad][:3].tolist()})")
    return t


def restrict(times, *cols, interval=FULL):
    """One opponent's observations restricted to the interval (focal times inside it; the opponent kept)."""
    t = np.asarray(times, float)
    keep = (t >= interval[0] - 1e-9) & (t <= interval[1] + 1e-9)
    return (t[keep],) + tuple(np.asarray(c, float)[keep] for c in cols)


_BASIS = {}


def basis(t, interval=FULL):
    """The six-spline basis at times t in the interval (cached by the times and the interval: the same
    focal times recur across opponents, worlds and calibration panels; a read-only array)."""
    L, U = interval
    t = np.asarray(t, float)
    key = (t.tobytes(), float(L), float(U))
    B = _BASIS.get(key)
    if B is None:
        B = bspline((in_interval(t, interval) - L) / (U - L))
        B.setflags(write=False)
        if len(_BASIS) > 8192:
            _BASIS.clear()
        _BASIS[key] = B
    return B


def _sigma(x):
    return 1.0 / (1.0 + np.exp(-x))


def _resid_w(eta, y, n):
    """(n mu - y, n mu (1 - mu)) without cancellation: n mu - y = (n - y) sigma(eta) - y sigma(-eta)."""
    s, sm = _sigma(eta), _sigma(-eta)
    return (n - y) * s - y * sm, n * s * sm


ITERS, TOL, HALVINGS, ARMIJO = 100, 1e-12, 40, 1e-4


def _objective(eta, succ, trials, g, pen):
    """sum [n log(1 + e^eta) - y eta] + pen/2 |g|^2 (over the last axis for a batch), in the cancellation-
    free form (n - y) softplus(eta) + y softplus(-eta) (equal: softplus(eta) - eta = softplus(-eta))."""
    return (np.sum((trials - succ) * np.logaddexp(0.0, eta) + succ * np.logaddexp(0.0, -eta), axis=-1)
            + 0.5 * pen * np.sum(g * g, axis=-1))


def _converged(step, g, tol):
    return np.max(np.abs(step), axis=-1) <= tol * np.maximum(1.0, np.max(np.abs(g), axis=-1))


def _newton(X, succ, trials, pen=PENALTY, iters=ITERS, tol=TOL):
    """argmin sum [n log(1 + e^eta) - y eta] + pen/2 |gamma|^2, eta = X gamma: SAFEGUARDED Newton (a convex
    problem; Armijo step halving), CONVERGENCE REQUIRED: the iteration budget's exhaustion, a failed line
    search away from the optimum or a nonfinite iterate is a BackboneError, never a returned last iterate
    (#68 review 5)."""
    g = np.zeros(X.shape[1])
    f = float(_objective(X @ g, succ, trials, g, pen))
    for _ in range(iters):
        r, wt = _resid_w(X @ g, succ, trials)
        grad = X.T @ r + pen * g
        H = X.T @ (X * wt[:, None]) + pen * np.eye(X.shape[1])
        step = np.linalg.solve(H, grad)
        if not np.all(np.isfinite(step)):
            raise BackboneError("the quasi-likelihood fit failed (a nonfinite Newton step)")
        if bool(_converged(step, g, tol)):
            return g - step
        dec, t = float(grad @ step), 1.0
        for _h in range(HALVINGS):
            gn = g - t * step
            fn = float(_objective(X @ gn, succ, trials, gn, pen))
            if fn <= f - ARMIJO * t * dec or fn <= f + 1e-15 * max(1.0, abs(f)):
                break
            t /= 2
        else:
            raise BackboneError("the quasi-likelihood fit failed (no descent along the Newton step)")
        g, f = gn, fn
    raise BackboneError(f"the quasi-likelihood fit did not converge in {iters} Newton iterations")


def fit_capture(times, captures, bounds, interval=FULL):
    """One fixed prey opponent's capture curve: times (focal predator times, M), captures and bounds
    (summed over replicates or not: the loss is additive) -> gamma (6,)."""
    X = basis(times, interval)
    return _newton(X, np.asarray(captures, float), np.asarray(bounds, float))


def logit_curve(gamma, times, interval=FULL):
    return basis(times, interval) @ gamma


def fit_captures(times, captures, bounds, interval=FULL, pen=PENALTY, iters=ITERS, tol=TOL):
    """fit_capture for K opponents observed at the SAME focal times, batched (each row: _newton's
    safeguarded iterates and convergence rule): captures, bounds (K x m) -> gammas (K x 6)."""
    X = basis(times, interval)
    Y, N = np.atleast_2d(np.asarray(captures, float)), np.atleast_2d(np.asarray(bounds, float))
    g = np.zeros((Y.shape[0], X.shape[1]))
    I = np.eye(X.shape[1])
    f = _objective(g @ X.T, Y, N, g, pen)
    done = np.zeros(len(g), bool)
    for _ in range(iters):
        r, wt = _resid_w(g @ X.T, Y, N)
        grad = r @ X + pen * g
        H = np.einsum("km,ma,mb->kab", wt, X, X) + pen * I
        step = np.linalg.solve(H, grad[:, :, None])[:, :, 0]
        if not np.all(np.isfinite(step)):
            raise BackboneError("the quasi-likelihood fit failed (a nonfinite Newton step)")
        conv = _converged(step, g, tol) & ~done
        g[conv] -= step[conv]                                  # (a converged row takes its last step, once)
        done |= conv
        if done.all():
            return g
        live = ~done
        dec = np.sum(grad * step, axis=1)
        t = np.ones(len(g))
        acc = ~live
        gn = g.copy()
        for _h in range(HALVINGS):
            trial = g - t[:, None] * step
            fn = _objective(trial @ X.T, Y, N, trial, pen)
            ok = live & ~acc & ((fn <= f - ARMIJO * t * dec) | (fn <= f + 1e-15 * np.maximum(1.0, np.abs(f))))
            gn[ok], f[ok] = trial[ok], fn[ok]
            acc |= ok
            if acc.all():
                break
            t = np.where(acc, t, t / 2)
        else:
            raise BackboneError("the quasi-likelihood fit failed (no descent along the Newton step)")
        g = np.where(live[:, None], gn, g)
    raise BackboneError(f"the quasi-likelihood fit did not converge in {iters} Newton iterations")


def fit_survival(free, exposed, interval=FULL, trials=TRIALS, pen=PENALTY, iters=ITERS, tol=TOL):
    """The joint survival fit of one world (fit_survival_dense's estimator and safeguarded Newton
    iterates, by the arrowhead structure of its Hessian: the shared c block bordered by independent d_k
    blocks; a Schur complement solve, O(K) instead of O(K^3)). Convergence required (_newton's rule)."""
    keys = sorted(exposed)
    ft, fs = free
    Xf = basis(ft, interval)
    yf = np.asarray(fs, float)
    Xs = [basis(exposed[k][0], interval) for k in keys]
    ys = [np.asarray(exposed[k][1], float) for k in keys]
    if keys and all(X is Xs[0] for X in Xs) and all(len(y) == len(ys[0]) for y in ys):
        return _fit_survival_shared(Xf, yf, Xs[0], np.vstack(ys), keys, trials, pen, iters, tol)
    c = np.zeros(6)
    d = np.zeros((len(keys), 6))
    I = np.eye(6)

    def obj(c, d):
        v = float(_objective(Xf @ c, yf, trials, np.zeros(1), 0.0))
        for k, (X, y) in enumerate(zip(Xs, ys)):
            v += float(_objective(X @ (c + d[k]), y, trials, np.zeros(1), 0.0))
        return v + 0.5 * pen * (float(c @ c) + float(np.sum(d * d)))
    f = obj(c, d)
    for _ in range(iters):
        rf, wf = _resid_w(Xf @ c, yf, trials)
        gc = Xf.T @ rf + pen * c
        Hcc = Xf.T @ (Xf * wf[:, None]) + pen * I
        gd, Hkk, Hck = [], [], []
        for k, (X, y) in enumerate(zip(Xs, ys)):
            rk, wk = _resid_w(X @ (c + d[k]), y, trials)
            r = X.T @ rk
            A = X.T @ (X * wk[:, None])
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
        dd = np.array([Ki[:, 6] - Ki[:, :6] @ dc for Ki in sol]) if keys else np.zeros_like(d)
        if not (np.all(np.isfinite(dc)) and np.all(np.isfinite(dd))):
            raise BackboneError("the quasi-likelihood fit failed (a nonfinite Newton step)")
        step = np.concatenate([dc, dd.ravel()])
        cur = np.concatenate([c, d.ravel()])
        if bool(_converged(step, cur, tol)):
            return c - dc, {key: (d - dd)[n_] for n_, key in enumerate(keys)}
        dec = float(np.concatenate([gc, np.ravel(gd) if keys else np.zeros(0)]) @ step)
        t = 1.0
        for _h in range(HALVINGS):
            cn, dn = c - t * dc, d - t * dd
            fn = obj(cn, dn)
            if fn <= f - ARMIJO * t * dec or fn <= f + 1e-15 * max(1.0, abs(f)):
                break
            t /= 2
        else:
            raise BackboneError("the quasi-likelihood fit failed (no descent along the Newton step)")
        c, d, f = cn, dn, fn
    raise BackboneError(f"the quasi-likelihood fit did not converge in {iters} Newton iterations")


def _fit_survival_shared(Xf, yf, Xe, Y, keys, trials, pen, iters, tol):
    """fit_survival when every opponent is observed at the same focal times (the registered complete
    panels): the K arrowhead blocks stacked (one batched 6 x 6 solve per iteration instead of K); the
    same safeguarded Newton iterates and convergence rule."""
    K = len(keys)
    c = np.zeros(6)
    d = np.zeros((K, 6))
    I = np.eye(6)

    def obj(c, d):
        return (float(_objective(Xf @ c, yf, trials, np.zeros(1), 0.0))
                + float(np.sum(_objective((c + d) @ Xe.T, Y, trials, np.zeros((K, 1)), 0.0)))
                + 0.5 * pen * (float(c @ c) + float(np.sum(d * d))))
    f = obj(c, d)
    for _ in range(iters):
        rf, wf = _resid_w(Xf @ c, yf, trials)
        r, w = _resid_w((c + d) @ Xe.T, Y, trials)                        # K x m
        rk = r @ Xe                                                       # K x 6
        A = np.einsum("km,ma,mb->kab", w, Xe, Xe)                         # K x 6 x 6
        gc = Xf.T @ rf + pen * c + rk.sum(axis=0)
        Hcc = Xf.T @ (Xf * wf[:, None]) + pen * I + A.sum(axis=0)
        gd = rk + pen * d
        Ki = np.linalg.solve(A + pen * I, np.concatenate([np.transpose(A, (0, 2, 1)), gd[:, :, None]], axis=2))
        S = Hcc - np.einsum("kab,kbc->ac", A, Ki[:, :, :6])
        rhs = gc - np.einsum("kab,kb->a", A, Ki[:, :, 6])
        dc = np.linalg.solve(S, rhs)
        dd = Ki[:, :, 6] - np.einsum("kab,b->ka", Ki[:, :, :6], dc)
        if not (np.all(np.isfinite(dc)) and np.all(np.isfinite(dd))):
            raise BackboneError("the quasi-likelihood fit failed (a nonfinite Newton step)")
        step = np.concatenate([dc, dd.ravel()])
        if bool(_converged(step, np.concatenate([c, d.ravel()]), tol)):
            c, d = c - dc, d - dd
            return c, {key: d[n_] for n_, key in enumerate(keys)}
        dec = float(np.concatenate([gc, gd.ravel()]) @ step)
        t = 1.0
        for _h in range(HALVINGS):
            cn, dn = c - t * dc, d - t * dd
            fn = obj(cn, dn)
            if fn <= f - ARMIJO * t * dec or fn <= f + 1e-15 * max(1.0, abs(f)):
                break
            t /= 2
        else:
            raise BackboneError("the quasi-likelihood fit failed (no descent along the Newton step)")
        c, d, f = cn, dn, fn
    raise BackboneError(f"the quasi-likelihood fit did not converge in {iters} Newton iterations")


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
    focal = in_interval(focal_times, interval, "focal time")
    capture = _restricted(capture, interval)
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


def _restricted(panel, interval):
    """Every opponent's observations restricted to the interval's focal times (#68 review 6: an epoch
    fit sees its epoch only); every opponent kept, and one left without an observation is refused."""
    out = {}
    for k, v in panel.items():
        r = restrict(v[0], *v[1:], interval=interval)
        if not len(r[0]):
            raise BackboneError(f"opponent {k}: no observation inside the interval {interval}")
        out[k] = r
    return out


def hq_world(free, exposed, focal_times, interval=FULL):
    """H-Q slope of one world: the joint survival fit; m^Q(t) the mean over the opponents of q(t)."""
    free = _restricted({"free": free}, interval)["free"]
    c, ds = fit_survival(free, _restricted(exposed, interval), interval)
    focal = in_interval(focal_times, interval, "focal time")
    m = np.mean([q_curve(c, ds[k], focal, interval) for k in sorted(ds)], axis=0)
    return slope(focal, m), m


def hc_world(free, neural, scripted, focal_times, interval=FULL):
    """H-C's world contrast d_w = beta_N - beta_S: the four neural references and the scripted benchmark
    fitted jointly with the shared free control; beta_N from the uniform average of the references' q."""
    exposed = {("N", k): v for k, v in neural.items()}
    exposed[("S", 0)] = scripted
    free = _restricted({"free": free}, interval)["free"]
    c, ds = fit_survival(free, _restricted(exposed, interval), interval)
    focal = in_interval(focal_times, interval, "focal time")
    qn = np.mean([q_curve(c, ds[("N", k)], focal, interval) for k in sorted(neural)], axis=0)
    qs = q_curve(c, ds[("S", 0)], focal, interval)
    bn, bs = slope(focal, qn), slope(focal, qs)
    return {"beta_N": bn, "beta_S": bs, "d": bn - bs}


def directional_test(world_slopes, hypothesis, delta, draws=stats.B_BOOT, eligibility=None):
    """The H.2 test of a mean of per-world slopes {world id: slope} (unpooled fits: cached), with the
    registered bootstrap stream and material scale. eligibility (stats.eligibility's record; Annex H D6 rules
    26-27): the analysis runs only when the hypothesis is available, on exactly its registered population (the
    common Q200: stats.require_population; StatsError otherwise)."""
    if eligibility is not None:
        stats.require_population(eligibility, hypothesis, list(world_slopes))
    ids = sorted(world_slopes)
    vals = [float(world_slopes[w]) for w in ids]
    if not all(math.isfinite(v) for v in vals):
        return {"available": False, "reason": "a nonfinite world slope"}
    return stats.cluster_test(vals, stats.mean_se, draws=draws, rng=stats.bootstrap_stream(hypothesis, "slope"),
                              delta=delta)

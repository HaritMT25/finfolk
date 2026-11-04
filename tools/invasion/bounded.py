#!/usr/bin/env python3
"""bounded.py: bounded-scale sensitivity of the ladder / cycle split (stdlib only).

Why. The endpoint is bounded: q, the invaders' final mean founder-pedigree contribution, lies
in [0, 1], and a losing invader cannot go below q = 0 (s = -f). A transitive but non-additive
bounded ladder makes cardinal Hodge residuals with no ordinal cycle:
q_ij = logistic(logit(0.05) + u_i - u_j) is perfectly ordered, yet for strengths 0, 1, 2 its
antisymmetric part has triangle circulation -0.0606 (Bertrand, Czarnecki & Gidel 2023:
"transitive, not additive"). So a cyclic residual on the raw score scale is not by itself a
strategy cycle. Two complementary checks (review round 2):

1. Transformed endpoints. Each replicate's endpoint q and its start fraction f are transformed
   before the unchanged pipeline (sham pairing, units, infer.py): s_h = h(q) - h(f).
     logit:EPS  h(q) = logit(clip(q, EPS, 1 - EPS)). Exact zeros occur (the invader pedigree
                was lost), so the clip matters: EPS = 0.001 primary, 1e-6 sensitivity.
     asin       h(q) = asin(sqrt(q)), the angular (variance-stabilizing) transform; no clip.
   Descriptive sensitivity: no transformation is uniquely right, and the tests on a
   transformed scale test additivity ON THAT SCALE.

2. Bounded node-additive models for the EXPECTED endpoint, fitted per condition to the cell
   means qbar_ij (invader i, resident j, i != j; equal cell weights; least squares). The shams
   are column constants on the outcome scale and never reach the cyclic part, so they are not
   modelled.
     logistic   q_ij = sigma(mu + a_i + b_j)                                   2N - 1 params
     aoceil     q_ij = U * AO_lam(mu + a_i + b_j), AO_lam(x) = 1 - (1 + lam e^x)^(-1/lam)
                (Aranda-Ordaz: lam = 1 is logistic, lam -> 0 the complementary log-log) with a
                ceiling U in (0, 1): a free, asymmetric saturating link       2N + 1 params
     strength   q_ij = sigma(c + u_i - u_j): one strength per item, the resident effect minus
                the invader effect (the most restrictive; Codex's example)     N params
   Each is TRANSITIVE: sign(q_ij - q_ji) = sign(d_i - d_j) for one score d per item. None is
   additive in A = q - q^T. The question is whether the observed cyclic residual survives:
     T_C     ||Q A(qbar)||^2, the raw cyclic energy (infer.py's T_C)
     C_fit   ||Q A(fit)||^2, the curl the bounded ladder itself makes
     R_C     ||Q A(qbar - fit)||^2, the cyclic energy the model leaves
     F_res   R_C / tau_C, tau_C the units' curl noise energy (as in infer.py)
     p_res   parametric-residual bootstrap: qbar* = fit + the mean of k resampled residual units
             per column, the model REFITTED to every draw, F* = R_C* / tau_C*. Approximate in the
             same way as infer.py's bootstrap (asymptotic in k; see there).
     R_C_nc  R_C - mean(R_C*): noise-corrected (the bootstrap mean is the noise that survives
             the refit). share_res_nc = R_C_nc / (T_A - tau_A) with the raw scale's paired
             signal energy, so it compares directly with infer's share_nc; survival =
             R_C_nc / (T_C - tau_C), the fraction of the noise-corrected cyclic energy left.
   and the same for the symmetric interaction (T_S, R_S, F_res_S, p_res_S).
"""
from __future__ import annotations

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hodge  # noqa: E402
import infer  # noqa: E402

MODELS = ("logistic", "aoceil", "strength")
DEFAULT_SCALES = ("logit:0.001", "logit:1e-06", "asin")


# ------------------------------------------------------------ transforms
def sigmoid(x):
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def dsigmoid(x):
    """sigma'(x) = e^-|x| / (1 + e^-|x|)^2, without the cancellation of sigma (1 - sigma) near sigma = 1."""
    e = math.exp(-abs(x))
    return e / ((1.0 + e) * (1.0 + e))


def transform(spec):
    """-> (h, eps): the endpoint transform named by spec, and its clip (None if it has none)."""
    if spec == "raw":
        return (lambda q: q), None
    if spec.startswith("logit:"):
        eps = float(spec.split(":", 1)[1])
        if not 0.0 < eps < 0.5:
            raise ValueError(spec)

        def h(q):
            q = min(max(q, eps), 1.0 - eps)
            return math.log(q / (1.0 - q))
        return h, eps
    if spec == "asin":
        return (lambda q: math.asin(math.sqrt(min(max(q, 0.0), 1.0)))), None
    raise ValueError(f"unknown scale {spec!r} (raw, logit:EPS, asin)")


def transform_rows(rows, spec):
    """Rows (analyze.run_rows) with s replaced by h(q) - h(f), q = s + f the endpoint. -> (rows,
    number of endpoints at or beyond the clip)."""
    h, eps = transform(spec)
    out, clipped = [], 0
    for x in rows:
        y = dict(x)
        if x.get("s") is not None:
            q = x["s"] + x["f0"]
            if eps is not None and (q <= eps or q >= 1 - eps):
                clipped += 1
            y["s"] = h(q) - h(x["f0"])
        out.append(y)
    return out, clipped


# ------------------------------------------------------------ models
class Model:
    """q_ij = g(eta_ij; phi). Identifiable parameters: the last item's a / b / u is minus the
    sum of the others."""

    def __init__(self, name, N):
        if name not in MODELS:
            raise ValueError(name)
        self.name, self.N = name, N
        self.P = {"logistic": 2 * N - 1, "aoceil": 2 * N + 1, "strength": N}[name]

    def _expand(self, v):
        return list(v) + [-sum(v)]

    def eval(self, th, cells):
        """-> (predictions, Jacobian rows) over cells [(i, j)]."""
        N, P, nm = self.N, self.P, self.name
        preds, J = [], []
        if nm == "strength":
            c, u = th[0], self._expand(th[1:N])
        else:
            mu, a, b = th[0], self._expand(th[1:N]), self._expand(th[N:2 * N - 1])
        if nm == "aoceil":
            # lam = l^2 >= 0 and U = 1 / (1 + om^2) <= 1: the complementary log-log limit (lam = 0) and
            # 'no ceiling' (U = 1) are reached at finite parameters, so a fit that wants them converges
            ell, om = th[-2], th[-1]
            lam = ell * ell
            U = 1.0 / (1.0 + om * om)
            dU = -2.0 * om * U * U
        for i, j in cells:
            row = [0.0] * P
            if nm == "strength":
                eta = c + u[i] - u[j]
            else:
                eta = mu + a[i] + b[j]
            x = min(max(eta, -40.0), 40.0)
            if nm == "aoceil":
                e = math.exp(x)
                t = lam * e
                base = 1.0 + t
                # rr = log(1 + lam e) / lam (w = exp(-rr)); the series in t = lam e is used only where
                # t is small (review round 3: a series in lam alone diverges for lam e >= 1)
                if t < 1e-4:
                    rr = e * (1.0 - t / 2.0 + t * t / 3.0)
                    drr = e * e * (-0.5 + 2.0 * t / 3.0 - 0.75 * t * t)   # d rr / d lam
                else:
                    rr = math.log1p(t) / lam
                    drr = (e / base - rr) / lam
                w = math.exp(-rr)
                g = U * (1.0 - w)
                d = U * e * w / base
                row[-2] = U * w * drr * 2.0 * ell                  # d g / d l
                row[-1] = (1.0 - w) * dU                           # d g / d om
            else:
                g = sigmoid(x)
                d = dsigmoid(x)   # (stable: g (1 - g) cancels to 0 near g = 1; review of #49)
            row[0] = d
            if nm == "strength":
                for t, sgn in ((i, 1.0), (j, -1.0)):
                    if t < N - 1:
                        row[1 + t] += sgn * d
                    else:
                        for s_ in range(N - 1):
                            row[1 + s_] -= sgn * d
            else:
                for t, off in ((i, 1), (j, N)):
                    if t < N - 1:
                        row[off + t] += d
                    else:
                        for s_ in range(N - 1):
                            row[off + s_] -= d
            preds.append(g)
            J.append(row)
        return preds, J

    def predict(self, th, cells):
        """The predictions of eval without the Jacobian (the same arithmetic, so bit-identical)."""
        if self.name == "aoceil":
            return self.eval(th, cells)[0]
        N = self.N
        if self.name == "strength":
            c, u = th[0], self._expand(th[1:N])
            return [sigmoid(min(max(c + u[i] - u[j], -40.0), 40.0)) for i, j in cells]
        mu, a, b = th[0], self._expand(th[1:N]), self._expand(th[N:2 * N - 1])
        return [sigmoid(min(max(mu + a[i] + b[j], -40.0), 40.0)) for i, j in cells]

    def etas(self, th, cells):
        """The unclamped linear predictors eta over cells."""
        N = self.N
        if self.name == "strength":
            c, u = th[0], self._expand(th[1:N])
            return [c + u[i] - u[j] for i, j in cells]
        mu, a, b = th[0], self._expand(th[1:N]), self._expand(th[N:2 * N - 1])
        return [mu + a[i] + b[j] for i, j in cells]

    def design(self, cells):
        """The linear predictor's design rows, eta_c = sum_k x_ck theta_k: [{k: x_ck}] (logistic, strength);
        None for aoceil (its link has further parameters)."""
        N = self.N
        if self.name == "aoceil":
            return None

        def eff(t, off, sgn, row):
            if t < N - 1:
                row[off + t] = row.get(off + t, 0.0) + sgn
            else:
                for s_ in range(N - 1):
                    row[off + s_] = row.get(off + s_, 0.0) - sgn
        out = []
        for i, j in cells:
            row = {0: 1.0}
            if self.name == "strength":
                eff(i, 1, 1.0, row)
                eff(j, 1, -1.0, row)
            else:
                eff(i, 1, 1.0, row)
                eff(j, N, 1.0, row)
            out.append(row)
        return out

    def describe(self, th):
        N = self.N
        if self.name == "strength":
            return {"c": th[0], "u": self._expand(th[1:N])}
        d = {"mu": th[0], "a": self._expand(th[1:N]), "b": self._expand(th[N:2 * N - 1])}
        if self.name == "aoceil":
            d.update(lam=th[-2] ** 2, U=1.0 / (1.0 + th[-1] ** 2))
        return d


GTOL = 1e-9   # stationarity at the iteration cap: max |J'r| <= GTOL x max(1, ||y||)
STAT_TOL = 1e-4   # first-order stationarity at every non-exact exit (prereg gate, review round 5 item 4):
STAT_ABS = 1e-12  # the Gauss-Newton step may not promise more than STAT_TOL SSE + STAT_ABS max(||y||^2, n)
RANK_TOL = 1e-13  # flat cells (a Jacobian row <= RANK_TOL max|J|); the gain's rank cut is gain_cut(n) = RANK_TOL / sqrt(n)
SAT_D = 1e-12     # (reported only) a cell whose Jacobian row is <= SAT_D everywhere is numerically saturated
ETA_CLAMP = 40.0  # model.eval clamps eta to +-40 (beyond it the link is constant)
LM_DIAG = 1e-18   # lm's absolute diagonal stabilizer: (J'J + lam diag(J'J) + LM_DIAG I) step = J'r
PROBE_SHRINK = 0.8     # the probe's coarse scan: t = 1, 0.8, 0.8^2, ...
PROBE_STEPS = 220      # ... down to 0.8^219 ~ 6e-22 of the Gauss-Newton step
PROBE_REFINE = 8       # then the lowest PROBE_REFINE local minima of the scanned SSE are refined ...
PROBE_GOLDEN = 40      # ... by this many golden-section iterations in log t between their neighbours

# The fitting freeze (preregistration section 3, "Fit failures"): deterministic initialization, this optimizer
# and these tolerances are part of the registered procedure; the gate manifest records this dict and the
# source hash of this file; tools/invasion/FIT_FREEZE.md is the dated attachment. Every fit reports its
# termination reason, gradient and stationarity. The classifier only ever MARKS a fit unconverged: it never
# changes a fitted value (no outcome-dependent rescue).
FIT_FREEZE = {
    "optimizer": ("Levenberg-Marquardt (bounded.lm): (J'J + lam diag(J'J) + 1e-18 I) step = J'r; lambda0 1e-3, /3 "
                  "(floor 1e-9) on an accepted step, x10 on a rejected one; exits: an exact fit (SSE <= 1e-26 "
                  "max(||y||^2, 1e-30)), a relative SSE improvement S - Sn <= tol max(S, 1e-30), a step <= 1e-12 "
                  "(1 + max|theta|), damping > 1e6, or the iteration cap"),
    "iters": 200, "tol": 1e-11, "gtol": GTOL, "stat_tol": STAT_TOL, "stat_abs": STAT_ABS, "rank_tol": RANK_TOL,
    "rank_tol_gain": "rank_tol / sqrt(n)", "lm_diag": LM_DIAG, "eta_clamp": ETA_CLAMP,
    "probe_shrink": PROBE_SHRINK, "probe_steps": PROBE_STEPS, "probe_refine": PROBE_REFINE, "probe_golden": PROBE_GOLDEN,
    "init": "logistic: two-way additive fit of the logit:0.001-clipped means (bounded.initial); no restarts",
    "derivatives": "sigma'(x) = e^-|x| / (1 + e^-|x|)^2 (stable), evaluated at the clamped eta",
    "converged": ("an exact fit; otherwise the exit counts as converged only if, with allow = stat_tol SSE + "
                  "stat_abs max(||y||^2, n) (n = cells): (1) the EXACT linearized gain ||Q1'r||^2 (Householder QR "
                  "of J with column pivoting, numerical rank at |R_kk| <= (rank_tol / sqrt(n)) |R_11|, which "
                  "nests inside the flat-row rule since |R_11| <= sqrt(n) max|J|; any direction or combination "
                  "of the tangent space, however weak but numerically resolvable, counts) is <= allow, OR the "
                  "Gauss-Newton probe (theta + t d along the exact least-squares step d on the resolved columns, "
                  "never adopted: t = 1, probe_shrink, probe_shrink^2, ... for probe_steps points, then the "
                  "probe_refine lowest local minima of the scanned SSE refined by probe_golden golden-section "
                  "iterations in log t between their neighbours) realizes no SSE decrease > allow; (2) the "
                  "residual energy on numerically flat cells (|eta| >= eta_clamp, or every Jacobian entry of the "
                  "row <= rank_tol max|J|) is <= allow - fail-closed: a legitimate irreducible residual there is "
                  "a false unavailability, never a false certification; (3) at the cap also max |J'r| <= gtol "
                  "max(1, ||y||); a non-finite SSE, parameter, fitted value or Jacobian entry is never converged. "
                  "The classifier only marks fits; it changes no fitted value (no outcome-dependent rescue)"),
    "reported": ("every fit also reports its rank, flat-cell SSE, probe decrease (when probed), the residual "
                 "energy the unresolved columns would explain, and the extreme eigenvalues of the Hessian of "
                 "SSE/2 on the resolved coordinates (logistic and strength models): diagnostics, not rules"),
    "unavailable": "any required unconverged fit, non-finite result or failed projection makes H1b unavailable",
}


class LMResult(tuple):
    """(theta, SSE, converged) with .reason (the exit), .grad (max |J'r|) and .stationarity."""
    reason = None
    grad = None
    stationarity = None
    saturated_sse = None
    rank = None
    flat_sse = None
    probe_decrease = None
    unresolved_gain = None
    hess_min = None
    hess_max = None
    allow = None


def _normal(J, r, P):
    JtJ = [[0.0] * P for _ in range(P)]
    Jtr = [0.0] * P
    for row, ri in zip(J, r):
        for a_ in range(P):
            ra = row[a_]
            if ra:
                Jtr[a_] += ra * ri
                Ja = JtJ[a_]
                for b_ in range(a_, P):
                    Ja[b_] += ra * row[b_]
    for a_ in range(P):
        for b_ in range(a_):
            JtJ[a_][b_] = JtJ[b_][a_]
    return JtJ, Jtr


def gain_cut(n):
    """The gain's relative rank cut for n rows (review of #49, round 4, P1-1): RANK_TOL / sqrt(n). Since |R_11| (the
    largest column norm) <= sqrt(n) max|J|, a pivot dropped from the gain has |R_kk| <= RANK_TOL max|J|, the
    flat-row threshold: the gain rule and the flat-cell rule nest (at RANK_TOL |R_11|, a weak combination on cells
    with derivatives between 2.5e-14 and ~7e-14 was in neither)."""
    return RANK_TOL / math.sqrt(max(1, n))


def qr_factor(J, r, P, tol=None):
    """Householder QR of J with column pivoting, the reflections applied to r as they are formed (review of #49,
    round 3: a diagonal scaling plus a ridge still hid a weak COMBINATION of strong columns, a0 - a1). Numerical
    rank: the first pivot |R_kk| <= tol |R_11| (tol = gain_cut(rows)); the resolved block ends there. The
    factorization is continued past the cut, with no cut, only to REPORT the residual energy the unresolved
    columns would explain ('unresolved').
    -> dict(gain = ||Q1'r||^2 on the resolved block, rank, unresolved, perm, R (resolved rows, pivoted order), qtr)."""
    from operator import mul
    m = len(J)
    tol = gain_cut(m) if tol is None else tol
    cols = [[row[a_] for row in J] for a_ in range(P)]   # (each column trimmed to its rows j.. as j advances)
    perm = list(range(P))
    Rrows, qtr = [], []
    v = list(r)
    n2 = [sum(map(mul, c, c)) for c in cols]
    gain = unres = r11 = 0.0
    rank, resolving = 0, True
    for j in range(min(P, m)):
        p = max(range(j, P), key=n2.__getitem__)
        if p != j:
            cols[j], cols[p] = cols[p], cols[j]
            n2[j], n2[p] = n2[p], n2[j]
            perm[j], perm[p] = perm[p], perm[j]
            for row_ in Rrows:   # (the stored R entries follow the column swap)
                row_[j], row_[p] = row_[p], row_[j]
        c = cols[j]
        alpha = math.sqrt(sum(map(mul, c, c)))   # (recomputed exactly, never from the downdated norm)
        if j == 0:
            r11 = alpha
        if alpha == 0.0:
            break
        if resolving and alpha <= tol * r11:
            resolving = False   # (pivots never grow: every later one is unresolved too)
        s_ = -alpha if c[0] > 0 else alpha
        u = list(c)
        u[0] -= s_
        un = sum(map(mul, u, u))
        if un <= 0.0:
            break
        row = None
        if resolving:
            row = [0.0] * P
            row[j] = s_
        for t in range(j + 1, P):
            ct = cols[t]
            f = 2.0 * sum(map(mul, u, ct)) / un
            if f:
                ct = [x - f * ui for x, ui in zip(ct, u)]
            if row is not None:
                row[t] = ct[0]
            old = n2[t]
            n2[t] = old - ct[0] * ct[0]
            ct = ct[1:]
            if n2[t] < 1e-8 * old:   # cancellation in the downdate: recompute
                n2[t] = sum(map(mul, ct, ct))
            cols[t] = ct
        f = 2.0 * sum(map(mul, u, v)) / un
        v = [x - f * ui for x, ui in zip(v, u)]
        if resolving:
            gain += v[0] * v[0]
            Rrows.append(row)
            qtr.append(v[0])
            rank += 1
        else:
            unres += v[0] * v[0]
        v = v[1:]
    return {"gain": gain, "rank": rank, "unresolved": unres, "perm": perm, "R": Rrows, "qtr": qtr}


def gn_step(fac, P):
    """The Gauss-Newton step of a factorization: the least-squares solution of J d = r on the resolved columns,
    0 on the others."""
    rank, R, qtr, perm = fac["rank"], fac["R"], fac["qtr"], fac["perm"]
    z = [0.0] * P                          # back-substitution in the pivoted order, on the resolved block
    for j in reversed(range(rank)):
        z[j] = (qtr[j] - sum(R[j][t] * z[t] for t in range(j + 1, rank))) / R[j][j]
    d = [0.0] * P
    for j in range(rank):
        d[perm[j]] = z[j]
    return d


def qr_gain(J, r, P, tol=None, step=False):
    """-> (gain, rank) of qr_factor, or with step=True (gain, rank, the Gauss-Newton step)."""
    fac = qr_factor(J, r, P, tol)
    if not step:
        return fac["gain"], fac["rank"]
    return fac["gain"], fac["rank"], gn_step(fac, P)


def gn_probe(model, cells, y, th, d, S, enough=None):
    """The largest SSE decrease found along the Gauss-Newton direction d: a coarse scan t = 1, PROBE_SHRINK,
    PROBE_SHRINK^2, ... (PROBE_STEPS points), then the PROBE_REFINE lowest local minima of the scanned SSE (lowest
    first) refined by PROBE_GOLDEN golden-section iterations in log t between their scan neighbours (review of
    #49, round 4, P2-2: a decrease window narrower than the 0.8 grid's 1.25 ratio was skipped). It stops once a
    decrease of `enough` is found. A probe only: the fit is never moved."""
    def sse(t):
        g = model.predict([a_ + t * b_ for a_, b_ in zip(th, d)], cells)
        Sn = sum((p_ - q_) ** 2 for p_, q_ in zip(y, g))
        return Sn if math.isfinite(Sn) else float("inf")
    best = 0.0
    ts, ss = [], []
    t = 1.0
    for _ in range(PROBE_STEPS):
        Sn = sse(t)
        ts.append(t)
        ss.append(Sn)
        best = max(best, S - Sn)
        if enough is not None and best >= enough:
            return best
        t *= PROBE_SHRINK
    K = len(ss)
    mins = [k for k in range(K) if ss[k] < float("inf") and (k == 0 or ss[k] < ss[k - 1])
            and (k == K - 1 or ss[k] <= ss[k + 1])]
    mins.sort(key=lambda k: (ss[k], k))
    phi = (math.sqrt(5.0) - 1.0) / 2.0
    for k in mins[:PROBE_REFINE]:
        lo, hi = math.log(ts[min(k + 1, K - 1)]), math.log(ts[max(k - 1, 0)])
        if not hi > lo:
            continue
        x1, x2 = hi - phi * (hi - lo), lo + phi * (hi - lo)
        f1, f2 = sse(math.exp(x1)), sse(math.exp(x2))
        best = max(best, S - f1, S - f2)
        for _ in range(PROBE_GOLDEN):
            if enough is not None and best >= enough:
                return best
            if f1 <= f2:   # the minimum is in [lo, x2]
                hi, x2, f2 = x2, x1, f1
                x1 = hi - phi * (hi - lo)
                f1 = sse(math.exp(x1))
                best = max(best, S - f1)
            else:          # ... in [x1, hi]
                lo, x1, f1 = x1, x2, f2
                x2 = lo + phi * (hi - lo)
                f2 = sse(math.exp(x2))
                best = max(best, S - f2)
    return best


def _sym_extremes(A):
    """(smallest, largest) eigenvalue of a symmetric matrix: Householder tridiagonalization, then bisection on
    Sturm counts (absolute accuracy ~ eps ||A||)."""
    n = len(A)
    a = [list(row) for row in A]
    for k in range(n - 2):
        x = [a[i][k] for i in range(k + 1, n)]
        alpha = math.sqrt(sum(v * v for v in x))
        if alpha == 0.0:
            continue
        if x[0] > 0:
            alpha = -alpha
        v = list(x)
        v[0] -= alpha
        vn = sum(t * t for t in v)
        if vn == 0.0:
            continue
        beta = 2.0 / vn
        idx = range(k + 1, n)
        p = [beta * sum(a[i][j] * v[j - k - 1] for j in idx) for i in idx]
        K = 0.5 * beta * sum(pi * vi for pi, vi in zip(p, v))
        q = [pi - K * vi for pi, vi in zip(p, v)]
        for ii, i in enumerate(idx):
            ai, vi, qi = a[i], v[ii], q[ii]
            for jj, j in enumerate(idx):
                ai[j] -= vi * q[jj] + qi * v[jj]
        a[k + 1][k] = a[k][k + 1] = alpha
        for i in range(k + 2, n):
            a[i][k] = a[k][i] = 0.0
    d = [a[i][i] for i in range(n)]
    e2 = [a[i + 1][i] ** 2 for i in range(n - 1)]
    rad = [(math.sqrt(e2[i - 1]) if i > 0 else 0.0) + (math.sqrt(e2[i]) if i < n - 1 else 0.0) for i in range(n)]
    lo0, hi0 = min(x - r_ for x, r_ in zip(d, rad)), max(x + r_ for x, r_ in zip(d, rad))
    tiny = 1e-300 + 1e-300 * max(abs(lo0), abs(hi0))

    def below(x):   # the number of eigenvalues < x
        c, qv = 0, d[0] - x
        for i in range(n):
            if i:
                qv = (d[i] - x) - e2[i - 1] / qv
            if qv == 0.0:
                qv = -tiny
            c += qv < 0.0
        return c

    def kth(kk):   # the smallest x with at least kk eigenvalues < x
        lo, hi = lo0, hi0
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if mid <= lo or mid >= hi:
                break
            if below(mid) >= kk:
                hi = mid
            else:
                lo = mid
        return 0.5 * (lo + hi)
    return kth(1), kth(n)


def hessian_extremes(model, th, cells, r, fac):
    """(lambda_min, lambda_max) of the Hessian of SSE / 2, H = J'J - sum_c r_c sigma''(eta_c) x_c x_c', on the
    resolved coordinates of fac (its first rank pivoted parameters, where J'J is R'R exactly; sigma'' = -sigma'
    tanh(eta / 2), 0 beyond the clamp). Reported only (review of #49, round 4: not a decision rule - its margins
    between stalls and legitimate minima are a few roundoffs). (None, None) for the aoceil model."""
    X = model.design(cells)
    rank = fac["rank"]
    if X is None or rank == 0:
        return None, None
    R, perm = fac["R"], fac["perm"]
    pos = {perm[k]: k for k in range(rank)}
    H = [[0.0] * rank for _ in range(rank)]
    for a_ in range(rank):
        for b_ in range(a_, rank):
            H[a_][b_] = H[b_][a_] = sum(R[k][a_] * R[k][b_] for k in range(a_ + 1))
    for x, rc, e in zip(X, r, model.etas(th, cells)):
        if not rc or abs(e) >= ETA_CLAMP:
            continue
        w = -rc * dsigmoid(e) * math.tanh(0.5 * e)   # r_c sigma''(eta_c)
        idx = [(pos[k], v) for k, v in x.items() if k in pos]
        for p_, vp in idx:
            Hp = H[p_]
            for q_, vq in idx:
                Hp[q_] -= w * vp * vq
    return _sym_extremes(H)


def stationarity(J, r, P, clamped=None):
    """-> (gain / r'r, max |J'r|, numerical rank, flat SSE, factorization): the exact linearized gain of qr_factor (0 at a
    least-squares stationary point, ~1 on a stalled saturation, whatever the direction or combination), and
    the residual energy on numerically FLAT cells - rows whose every Jacobian entry is <= RANK_TOL max |J|, or
    cells whose linear predictor is at or beyond the clamp (`clamped`: the link is constant there, the
    reported derivative is the clamp point's) - where no first-order information exists."""
    S = sum(x * x for x in r)
    Jtr = [sum(row[a_] * ri for row, ri in zip(J, r)) for a_ in range(P)]
    grad = max(abs(x) for x in Jtr) if Jtr else 0.0
    if not (math.isfinite(S) and math.isfinite(grad)) or not all(math.isfinite(x) for row in J for x in row):
        return float("inf"), grad, 0, float("inf"), None
    rowmax = [max(abs(x) for x in row) for row in J]
    big = max(rowmax) if rowmax else 0.0
    clamped = clamped or [False] * len(r)
    flat = sum(ri * ri for rm, ri, cl in zip(rowmax, r, clamped) if cl or rm <= RANK_TOL * big)
    if S <= 0.0:
        return 0.0, grad, P, 0.0, None
    fac = qr_factor(J, r, P)
    return fac["gain"] / S, grad, fac["rank"], flat, fac


def lm(model, cells, y, th0, iters=200, tol=1e-11):
    """Levenberg-Marquardt least squares; stops when an accepted step improves the SSE by less
    than tol (relative). -> LMResult (theta, SSE, converged) with .reason / .grad / .stationarity /
    .rank / .flat_sse / .probe_decrease. Converged (FIT_FREEZE["converged"]): an exact fit, or an exit
    whose exact linearized gain (qr_gain) is within the allowance or is not realizable by the
    Gauss-Newton probe, with no unresolved residual on flat cells; at the iteration cap also
    max |J'r| <= GTOL max(1, ||y||). Anything else is NOT converged and decides nothing; the
    classifier never changes the fitted values."""
    th = list(th0)
    g, J = model.eval(th, cells)
    r = [a - b for a, b in zip(y, g)]
    S = sum(x * x for x in r)
    lam = 1e-3
    P = model.P
    floor = 1e-26 * max(1e-30, sum(v * v for v in y))   # an exact fit: nothing left to improve

    def out(reason, cap=False):
        st, grad, rank, flat, fac = stationarity(J, r, P, [abs(e) >= ETA_CLAMP for e in model.etas(th, cells)])
        finite = math.isfinite(S) and all(math.isfinite(t) for t in th) and all(math.isfinite(x) for x in r)
        yy = sum(v * v for v in y)
        allow = STAT_TOL * S + STAT_ABS * max(yy, float(len(y)))
        sat = sum(ri * ri for row, ri in zip(J, r) if max(abs(x) for x in row) <= SAT_D)   # (reported only)
        probe = None
        if finite and reason != "exact" and math.isfinite(st) and st * S > allow and fac is not None and flat <= allow:
            # the linearized gain promises more than allowed (and nothing else already rejects the fit): is it
            # REALIZABLE? Probe (never adopt) the exact
            # Gauss-Newton direction with a fine backtracking search (review of #49, round 3: a stalled saturation
            # - Codex's a0 = +25 / a1 = -25 - realizes it; a weak direction at a boundary infimum or a legitimate
            # optimum does not, the exact GN step with a line search reaching nothing)
            probe = gn_probe(model, cells, y, th, gn_step(fac, P), S, enough=allow)
        ok = finite and (reason == "exact" or ((st * S <= allow or (probe is not None and probe < allow))
                                               and flat <= allow))
        if cap:
            ok = ok and grad <= GTOL * max(1.0, math.sqrt(yy))
        res = LMResult((th, S, ok))
        res.reason, res.grad, res.stationarity, res.saturated_sse = reason, grad, st, sat
        res.rank, res.flat_sse, res.probe_decrease = rank, flat, probe
        res.unresolved_gain = fac["unresolved"] if fac is not None else None
        res.allow = allow
        if finite and fac is not None:   # (reported only)
            try:
                res.hess_min, res.hess_max = hessian_extremes(model, th, cells, r, fac)
            except (ValueError, ZeroDivisionError, OverflowError):
                pass
        return res
    for _ in range(iters):
        if S <= floor:
            return out("exact")
        JtJ, Jtr = _normal(J, r, P)
        while True:
            M = [[JtJ[a_][b_] + (lam * JtJ[a_][a_] + LM_DIAG if a_ == b_ else 0.0) for b_ in range(P)] for a_ in range(P)]
            try:
                step = hodge.solve(M, Jtr)
            except ValueError:
                step = None
            if step is not None:
                if max(abs(s_) for s_ in step) <= 1e-12 * (1.0 + max(abs(t) for t in th)):
                    return out("step")   # nothing left to move
                thn = [t + s_ for t, s_ in zip(th, step)]
                gn, Jn = model.eval(thn, cells)
                rn = [a - b for a, b in zip(y, gn)]
                Sn = sum(x * x for x in rn)
                if Sn <= S:
                    done = S - Sn <= tol * max(S, 1e-30) or Sn <= floor
                    th, J, r, S = thn, Jn, rn, Sn
                    lam = max(lam / 3.0, 1e-9)
                    if done:
                        return out("exact" if S <= floor else "tol")
                    break
            lam *= 10.0
            if lam > 1e6:
                return out("damping")   # no descent along even a short gradient step: a (local) minimum
    return out("cap", cap=True)


def _cells(N):
    return [(i, j) for i in range(N) for j in range(N) if i != j]


def initial(model_name, M, base=None):
    """Starting parameters: a two-way additive fit on the clipped logit scale (logistic), the
    logistic fit with lam = 1, U ~ 1 (aoceil), or its (a - b) / 2 (strength)."""
    N = len(M)
    if model_name == "logistic" or base is None:
        h, _ = transform("logit:0.001")
        Z = [[h(M[i][j]) if i != j else None for j in range(N)] for i in range(N)]
        mu, a, b, _ = hodge.twoway(Z)
        th = [mu] + a[:N - 1] + b[:N - 1]
        if model_name == "logistic":
            return th
        base = th
    mu, a, b = base[0], list(base[1:N]) + [-sum(base[1:N])], list(base[N:2 * N - 1]) + [-sum(base[N:2 * N - 1])]
    if model_name == "aoceil":
        return list(base[:2 * N - 1]) + [1.0, 0.05]   # lam = 1 (logistic), U = 0.9975
    u = [0.5 * (x - y) for x, y in zip(a, b)]
    return [mu] + u[:N - 1]


def fit(M, model_name, th0=None):
    """Fit one model to the mean matrix M[i][j] (invader i into resident j, diagonal None).
    -> dict(theta, F (fitted matrix), sse, converged, params)."""
    N = len(M)
    model = Model(model_name, N)
    cells = _cells(N)
    y = [M[i][j] for i, j in cells]
    if th0 is None:
        th0 = initial(model_name, M, fit(M, "logistic")["theta"] if model_name != "logistic" else None)
    res = lm(model, cells, y, th0)
    th, sse, ok = res
    g, _ = model.eval(th, cells)
    F = [[None] * N for _ in range(N)]
    for (i, j), v in zip(cells, g):
        F[i][j] = v
    finite = math.isfinite(sse) and all(math.isfinite(t) for t in th) and all(math.isfinite(v) for v in g)
    return {"model": model_name, "theta": th, "F": F, "sse": sse, "converged": bool(ok) and finite,
            "params": model.describe(th), "reason": getattr(res, "reason", None) if finite else "non-finite",
            "grad": getattr(res, "grad", None), "stationarity": getattr(res, "stationarity", None),
            "saturated_sse": getattr(res, "saturated_sse", None), "rank": getattr(res, "rank", None),
            "flat_sse": getattr(res, "flat_sse", None), "probe_decrease": getattr(res, "probe_decrease", None),
            "unresolved_gain": getattr(res, "unresolved_gain", None), "hess_min": getattr(res, "hess_min", None),
            "hess_max": getattr(res, "hess_max", None)}


# --------------------------------------------- per-decision summaries of the classifier's reports
FIT_DIAG_KEYS = ("fits", "unconverged", "probed", "probe_certified", "max_probe_decrease", "max_unresolved_gain",
                 "max_flat_sse", "min_hess_min")


def fit_diag(items=()):
    """A summary of fit reports (fit() dicts or LMResults; review of #49, round 4, P2-3): fits, unconverged,
    probed (the exact gain exceeded the allowance), probe-certified (probed, yet converged: the probe realized no
    decrease above the allowance), the largest probe decrease, unresolved-block energy and flat-cell SSE, and the
    smallest Hessian eigenvalue on the resolved coordinates."""
    out = {"fits": 0, "unconverged": 0, "probed": 0, "probe_certified": 0, "max_probe_decrease": None,
           "max_unresolved_gain": None, "max_flat_sse": None, "min_hess_min": None}
    for it in items:
        get = it.get if isinstance(it, dict) else (lambda k_, d_=None, it=it: getattr(it, k_, d_))
        ok = bool(get("converged")) if isinstance(it, dict) else bool(it[2])
        pr = get("probe_decrease")
        one = {"fits": 1, "unconverged": int(not ok), "probed": int(pr is not None),
               "probe_certified": int(pr is not None and ok), "max_probe_decrease": pr,
               "max_unresolved_gain": get("unresolved_gain"), "max_flat_sse": get("flat_sse"),
               "min_hess_min": get("hess_min")}
        out = merge_fit_diag(out, one)
    return out


def merge_fit_diag(a, b):
    """Combine two fit_diag summaries (counts add; maxima / minima over the non-None values)."""
    if a is None or b is None:
        return a if b is None else b
    out = {k_: a[k_] + b[k_] for k_ in ("fits", "unconverged", "probed", "probe_certified")}
    for k_, f_ in (("max_probe_decrease", max), ("max_unresolved_gain", max), ("max_flat_sse", max),
                   ("min_hess_min", min)):
        v = [x for x in (a[k_], b[k_]) if x is not None and isinstance(x, (int, float)) and math.isfinite(x)]
        out[k_] = f_(v) if v else None
    return out


# ------------------------------------------------------------ energies
def _colmeans(M):
    """Matrix M[i][j] (i into j) -> infer's column layout m[j][i]."""
    N = len(M)
    return [[(M[i][j] if i != j else 0.0) for i in range(N)] for j in range(N)]


def energies(M):
    """-> (T_A, T_C, T_S) of a directed matrix M[i][j], as infer.block_stats defines them."""
    N = len(M)
    m = _colmeans(M)
    TA, TC = infer.energies(infer.antisym(m), N)
    return TA, TC, infer.sym_energy(infer.symm(m), N)


def _sub(M, F):
    N = len(M)
    return [[(M[i][j] - F[i][j]) if i != j else None for j in range(N)] for i in range(N)]


def model_test(zq, model_name, B=1999, seed=1, kind=infer.DEFAULT_KIND, TA_pair=None, tauA_pair=None):
    """Lack of fit of a bounded node-additive model for one condition. zq[p][r][i] = the
    endpoint q of replicate r of i invading resident p (i != p; [p][r][p] = 0), one unit per
    (column, replicate) as in infer.py. TA_pair / tauA_pair: the raw paired block's T_A and
    tau_A (infer.block_stats of the sham-paired units) for the share denominator."""
    N, k = len(zq), len(zq[0])
    m = infer.column_means(zq)
    M = [[(m[j][i] if i != j else None) for j in range(N)] for i in range(N)]
    st = infer.block_stats(zq)
    f = fit(M, model_name)
    F = f["F"]
    _, C_fit, _ = energies(F)
    RA, RC, RS = energies(_sub(M, F))
    res = infer.residual_units(zq)
    E = [[infer.unit_energies(u, N) for u in col] for col in res]
    rnd = random.Random(seed)
    cells = _cells(N)
    model = Model(model_name, N)
    yfit = [F[i][j] for i, j in cells]
    FC, FS, RCs, RSs, bad = [], [], [], [], 0
    bdiag = fit_diag()
    for _ in range(B):
        plan = infer._draw_plan(rnd, kind, N, k)
        sb = infer._fast_stats(res, E, plan, kind)
        mb = sb["m"]
        yb = [v + mb[j][i] for v, (i, j) in zip(yfit, cells)]
        rb = lm(model, cells, yb, f["theta"])
        th, _, ok = rb
        bad += not ok
        bdiag = merge_fit_diag(bdiag, fit_diag([rb]))
        gb, _ = model.eval(th, cells)
        Mb = [[None] * N for _ in range(N)]
        for (i, j), a_, b_ in zip(cells, yb, gb):
            Mb[i][j] = a_ - b_
        _, rc, rs = energies(Mb)
        RCs.append(rc)
        RSs.append(rs)
        FC.append(infer._ratio(rc, sb["tauC"]))
        FS.append(infer._ratio(rs, sb["tauS"]))
    F_res = infer._ratio(RC, st["tauC"])
    F_res_S = infer._ratio(RS, st["tauS"])
    nullC = sum(RCs) / B
    nullS = sum(RSs) / B
    RC_nc = RC - nullC
    den = (TA_pair - tauA_pair) if TA_pair is not None else None
    P = N * (N - 1) // 2
    # an unconverged fit decides nothing (review round 4): no p-value rests on it; nor does a failed
    # projection (prereg gate: unavailable, not an abort)
    ok_fit, ok_boot = bool(f["converged"]), bad == 0
    p_res_flip = None
    if ok_fit:
        try:
            p_res_flip = infer.flip_p_vectors([residual_replicate_vectors(zq, model_name, f)[0]])
        except Unavailable:
            p_res_flip = None
    return {"model": model_name, "N": N, "k": k, "B": B, "kind": kind, "converged": f["converged"],
            "boot_not_converged": bad, "boot_fit_diag": bdiag, "fit_diag": fit_diag([f]), "sse": f["sse"],
            "params": f["params"],
            "T_C": st["TC"], "tau_C": st["tauC"], "C_fit": C_fit, "R_A": RA, "R_C": RC,
            "F_res": F_res,
            "p_res": (1 + sum(1 for x in FC if x >= F_res)) / (B + 1) if ok_fit and ok_boot else None,
            "R_C_null": nullC, "R_C_nc": RC_nc,
            "share_res_nc": RC_nc / den if den and den > 0 else float("nan"),
            "survival": RC_nc / (st["TC"] - st["tauC"]) if st["TC"] > st["tauC"] else float("nan"),
            "dC_res": math.sqrt(max(0.0, RC_nc) / P),
            "T_S": st["TS"], "tau_S": st["tauS"], "R_S": RS, "F_res_S": F_res_S,
            "p_res_S": (1 + sum(1 for x in FS if x >= F_res_S)) / (B + 1) if ok_fit and ok_boot else None,
            "R_S_null": nullS, "R_S_nc": RS - nullS, "p_res_flip": p_res_flip,
            "reason": f.get("reason"), "grad": f.get("grad"), "stationarity": f.get("stationarity")}


# ------------------------------------------------------- the frozen co-primary (hypothesis 1b)
# Review round 3: the logistic residual test as a co-primary needs ONE joint statistic over the
# four primary matrices (two home regimes x two assays), four separate mean fits, paired resampling
# (the assays of one regime share their units; regimes are independent) and a fixed multiplicity
# family. Frozen here:
#   H1b  "all four primary endpoint-mean matrices belong to the fitted logistic family": for every condition c, fit
#        sigma(mu_c + a_ci + b_cj) to that matrix's endpoint means; project each replicate r's cell
#        residuals d_cr = y_cr - fit_c off the model's tangent space at the fit (P_perp = I -
#        J (J'J)^-1 J'), take their curl, v_cr = Q A(P_perp d_cr), and sign-flip whole replicates
#        jointly over a regime's assays and independently across regimes:
#        T = sum_g ||sum_r delta_r (v_gr concatenated over the group's conditions)||^2.
#        At the least-squares fit P_perp leaves the residual of the means unchanged, so
#        T(+1) = k^2 sum_c R_C,c. Under H0 the projected replicate vectors have mean ~0 (to first
#        order in the noise); the test is exact only for independent, centrally symmetric v_cr and
#        to first order in the fit (the fit is not redone per pattern) - its level is calibrated
#        (calibrate.py --compound). The joint refitting bootstrap (residual_omnibus(B > 0): every
#        draw refits all four models, paired plans) is reported beside it.
#   Allocation (preregistration section 3): twelve fixed alpha slots (the stats spec's hypotheses
#        1-11 plus H1b), of which only H1 and H1b are active; ALPHA_FAMILY = a = 0.05 / 12. The ten
#        inactive slots get p = 1 and their allocations stay unused.
#   Claim rule: the fixed conjunction "H1 and H1b both p <= a" (with a valid complete dataset and a
#        passed calibration gate, read at T only: analyze.py --gate). It is sufficient for both
#        rejections under twelve-test Holm but it is NOT full Holm: no later Holm thresholds, no
#        recycled alpha. The claim it licenses: cardinal circulation beyond the fitted logistic
#        endpoint-mean family (not an ordinal cycle, not every transitive model).
#   Fit failures (review round 4; prereg gate): if any of the four logistic mean fits did not
#        converge, or a result is non-finite, or the tangent-space projection fails, H1b is
#        UNAVAILABLE: p_flip is None (a computed value is kept as p_flip_unconverged, a
#        diagnostic), so neither H1b nor the claim can reject. calibrate.py reports the raw
#        procedure rate (unavailable = no rejection) and the gate screen (unavailable = a
#        rejection under a null, a failure under an alternative). Likewise the refitting
#        bootstrap's p_boot is None if any of its refits did not converge (boot_not_converged).
CO_PRIMARY_MODEL = "logistic"
ALPHA_FAMILY = 0.05 / 12


def _inverse(Mx):
    n = len(Mx)
    return [list(col) for col in zip(*[hodge.solve(Mx, [1.0 if a == b else 0.0 for a in range(n)]) for b in range(n)])]


class Unavailable(ValueError):
    """A required H1b quantity cannot be computed (failed projection, non-finite result): the test is
    unavailable - never an abort, never a rejection (preregistration section 3, 'Fit failures')."""


def residual_replicate_vectors(zq, model_name=CO_PRIMARY_MODEL, fitres=None):
    """Per replicate r: Q A(P_perp (y_r - fit)), the curl of replicate r's cell residuals after
    projecting off the fitted model's tangent space. -> (vectors, fit). Raises Unavailable if the
    projection fails (singular normal matrix) or anything is non-finite."""
    N, k = len(zq), len(zq[0])
    m = infer.column_means(zq)
    M = [[(m[j][i] if i != j else None) for j in range(N)] for i in range(N)]
    f = fitres or fit(M, model_name)
    model = Model(model_name, N)
    cells = _cells(N)
    if not all(math.isfinite(t) for t in f["theta"]):
        raise Unavailable("non-finite fitted parameters")
    g, J = model.eval(f["theta"], cells)
    P = model.P
    JtJ = [[sum(row[a] * row[b] for row in J) for b in range(P)] for a in range(P)]
    for a in range(P):
        JtJ[a][a] += 1e-12 * max(JtJ[a][a], 1e-30)
    try:
        inv = _inverse(JtJ)
    except (ValueError, ZeroDivisionError, OverflowError) as e:
        raise Unavailable(f"tangent-space projection failed ({e})") from None
    if not all(math.isfinite(x) for row in inv for x in row):
        raise Unavailable("tangent-space projection failed (non-finite inverse)")
    out = []
    for r in range(k):
        d = [zq[j][r][i] - gv for (i, j), gv in zip(cells, g)]
        Jtd = [sum(row[a] * dv for row, dv in zip(J, d)) for a in range(P)]
        co = [sum(inv[a][b] * Jtd[b] for b in range(P)) for a in range(P)]
        mm = [[0.0] * N for _ in range(N)]
        for (i, j), dv, row in zip(cells, d, J):
            mm[j][i] = dv - sum(row[a] * co[a] for a in range(P))
        v = infer.curl_vec(infer.antisym(mm), N)[0]
        if not all(math.isfinite(x) for x in v):
            raise Unavailable("non-finite projected residual")
        out.append(v)
    return out, f


def residual_omnibus(groups, model_name=CO_PRIMARY_MODEL, B=0, seed=1, kind=infer.DEFAULT_KIND, fits=None):
    """H1b over independent groups of aligned conditions (groups[g][c] = endpoint units zq).
    -> dict: F_res_joint = sum R_C / sum tau_C, p_flip (the frozen decision; None = INVALID when a
    mean fit did not converge, see above), p_boot (joint refitting bootstrap with paired plans, if
    B > 0; None if any refit did not converge), per-condition R_C / C_fit / T_C / converged, and
    'valid' / 'invalid' / 'diagnostics'."""
    # One invalid-dataset path (prereg gate, review round 5 item 4): an unconverged or non-finite fit,
    # a failed projection or a non-finite statistic makes H1b UNAVAILABLE (valid False, p_flip None,
    # 'invalid' says why); nothing here may abort the analysis or a calibration dataset.
    fl, gv, per, why = [], [], [], []
    for g, zs in enumerate(groups):
        fg, vec_c = [], []
        for c, zq in enumerate(zs):
            try:
                f = fit_matrix(zq, model_name) if fits is None else fits[g][c]
            except (ValueError, ZeroDivisionError, OverflowError) as e:
                f = None
                why.append(f"{g}/{c}: fit failed ({e})")
            fg.append(f)
            vec = None
            if f is not None:
                try:
                    vec = residual_replicate_vectors(zq, model_name, f)[0]
                except Unavailable as e:
                    why.append(f"{g}/{c}: {e}")
                except (ValueError, ZeroDivisionError, OverflowError) as e:
                    why.append(f"{g}/{c}: projection failed ({e})")
            vec_c.append(vec)
            st = infer.block_stats(zq)
            M = _means(zq)
            per.append({"group": g, "cond": c, "T_C": st["TC"], "tau_C": st["tauC"],
                        "C_fit": energies(f["F"])[1] if f else float("nan"),
                        "R_C": energies(_sub(M, f["F"]))[1] if f else float("nan"),
                        "converged": bool(f and f["converged"]), "sse": f["sse"] if f else None,
                        "reason": f.get("reason") if f else "failed", "grad": f.get("grad") if f else None,
                        "stationarity": f.get("stationarity") if f else None,
                        **{k_: (f.get(k_) if f else None) for k_ in ("rank", "flat_sse", "probe_decrease",
                                                                       "unresolved_gain", "hess_min", "hess_max")}})
        fl.append(fg)
        if all(v is not None for v in vec_c):
            k = len(vec_c[0])
            gv.append([[x for vc in vec_c for x in vc[r]] for r in range(k)])
    F = infer._ratio(sum(x["R_C"] for x in per), sum(x["tau_C"] for x in per))
    bad = [f"{x['group']}/{x['cond']}" for x in per if not x["converged"]]
    p_flip = infer.flip_p_vectors(gv) if len(gv) == len(groups) else None
    if not why and (p_flip is None or not math.isfinite(p_flip)):
        why.append("non-finite sign-flip statistic")
    invalid = "; ".join(([f"logistic mean fit(s) not converged: group/condition {' '.join(bad)}"] if bad else []) + why)
    valid = not invalid
    out = {"model": model_name, "groups": len(groups), "conditions": len(per), "F_res_joint": F,
           "p_flip": p_flip if valid else None, "p_flip_unconverged": None if valid else p_flip,
           "valid": valid, "invalid": invalid or None,
           "fits_converged": len(per) - len(bad), "per_condition": per, "B": B, "p_boot": None,
           "boot_not_converged": 0, "fit_diag": fit_diag([f for fg in fl for f in fg if f is not None]),
           "boot_fit_diag": None,
           "flip_min_p": math.prod(1.0 / (1 << (len(zs[0][0]) - 1)) for zs in groups)}
    if not valid:
        return out
    if B > 0:
        rnd = random.Random(seed)
        shape = [(len(zs[0]), len(zs[0][0])) for zs in groups]
        prep = []
        for g, zs in enumerate(groups):
            for c, zq in enumerate(zs):
                res = infer.residual_units(zq)
                N = len(zq)
                prep.append((g, res, [[infer.unit_energies(u, N) for u in col] for col in res], fl[g][c],
                             Model(model_name, N), _cells(N)))
        ge = nbad = 0
        bdiag = fit_diag()
        for _ in range(B):
            plans = [infer._draw_plan(rnd, kind, N_, k_) for N_, k_ in shape]
            num = den = 0.0
            ok_all = True
            for g, res, E, f, model, cells in prep:
                sb = infer._fast_stats(res, E, plans[g], kind)
                mb = sb["m"]
                yb = [f["F"][i][j] + mb[j][i] for i, j in cells]
                rb = lm(model, cells, yb, f["theta"])
                th, _, ok = rb
                ok_all = ok_all and ok
                bdiag = merge_fit_diag(bdiag, fit_diag([rb]))
                gb, _ = model.eval(th, cells)
                N = model.N
                Mb = [[None] * N for _ in range(N)]
                for (i, j), a_, b_ in zip(cells, yb, gb):
                    Mb[i][j] = a_ - b_
                num += energies(Mb)[1]
                den += sb["tauC"]
            nbad += not ok_all
            ge += infer._ratio(num, den) >= F
        out["boot_not_converged"] = nbad
        out["boot_fit_diag"] = bdiag
        # a draw whose refit did not converge has no valid statistic: the bootstrap p is then not
        # reported (review round 4: never a rejection resting on an unfinished optimization)
        out["p_boot"] = (1 + ge) / (B + 1) if nbad == 0 and out["valid"] else None
    return out


def _means(zq):
    N = len(zq)
    m = infer.column_means(zq)
    return [[(m[j][i] if i != j else None) for j in range(N)] for i in range(N)]


def fit_matrix(zq, model_name=CO_PRIMARY_MODEL, th0=None):
    return fit(_means(zq), model_name, th0)


# ------------------------------------------------------------ self-test
def selftest():
    rnd = random.Random(5)
    # Codex's example: a perfectly ordered logistic ladder (strengths 0, 1, 2 from logit 0.05) has
    # reciprocal differences 0.10617 and 0.27293 and triangle circulation -0.0606, no ordinal cycle
    f0 = 0.05
    L0 = math.log(f0 / (1 - f0))
    u = [0.0, 1.0, 2.0]
    q = [[sigmoid(L0 + u[i] - u[j]) if i != j else None for j in range(3)] for i in range(3)]
    assert abs((q[1][0] - q[0][1]) - 0.10617) < 1e-4 and abs((q[2][0] - q[0][2]) - 0.27293) < 1e-4
    circ = (q[0][1] - q[1][0]) + (q[1][2] - q[2][1]) + (q[2][0] - q[0][2])
    assert abs(circ - 0.0606) < 1e-3, circ   # orientation 0 -> 1 -> 2 -> 0
    # a bounded transitive two-way world: raw cyclic energy > 0; every model that contains it
    # leaves (numerically) none; the strength model cannot fit separate invader / resident effects
    N = 7
    a = [rnd.gauss(0, 0.9) for _ in range(N)]
    b = [rnd.gauss(0, 0.6) for _ in range(N)]
    M = [[sigmoid(-2.5 + a[i] + b[j]) if i != j else None for j in range(N)] for i in range(N)]
    TA, TC, TS = energies(M)
    assert TC > 1e-4 * TA, (TC, TA)
    fr = fit(M, "logistic")
    assert fr["converged"] and energies(_sub(M, fr["F"]))[1] < 1e-14 * TC, energies(_sub(M, fr["F"]))
    fr = fit(M, "aoceil")   # (its optimum is on the boundary U -> 1, lam = 1: approached, not reached)
    assert energies(_sub(M, fr["F"]))[1] < 1e-8 * TC, energies(_sub(M, fr["F"]))
    # a free ceiling and asymmetric link is recovered
    lam0, U0 = 0.3, 0.4
    Mao = [[U0 * (1 - (1 + lam0 * math.exp(-1.0 + a[i] + b[j])) ** (-1 / lam0)) if i != j else None
            for j in range(N)] for i in range(N)]
    fr = fit(Mao, "aoceil")
    assert fr["sse"] < 1e-16 and abs(fr["params"]["lam"] - lam0) < 1e-4 and abs(fr["params"]["U"] - U0) < 1e-4, fr["params"]
    # a sign-reversing cycle planted on top survives every transitive model
    Mc = [row[:] for row in M]
    for (i, j) in ((0, 1), (1, 2), (2, 0)):
        Mc[i][j] += 0.08
        Mc[j][i] -= 0.08
    for nm in MODELS:
        fr = fit(Mc, nm)
        assert energies(_sub(Mc, fr["F"]))[1] > 0.25 * 3 * 0.16 ** 2, (nm, energies(_sub(Mc, fr["F"])))
    # the bootstrap test: units built from the logistic world with heteroscedastic noise; at this
    # scale a pure bounded ladder is not rejected but the planted cycle is, while the raw-scale
    # lack of fit flags both
    k = 6
    sds = [[0.0 if i == p else rnd.choice((0.004, 0.01, 0.02)) for i in range(N)] for p in range(N)]

    def units(Mx):
        return [[[Mx[i][p] + sds[p][i] * rnd.gauss(0, 1) if i != p else 0.0 for i in range(N)]
                 for _ in range(k)] for p in range(N)]
    z0 = units([[sigmoid(-2.0 + 1.6 * a[i] + b[j]) if i != j else None for j in range(N)] for i in range(N)])
    t0 = model_test(z0, "logistic", B=199, seed=2)
    assert t0["p_res"] > 0.01 and t0["C_fit"] > 0, t0
    assert infer.infer([z0], B=199, seed=2)["p_lof"] <= 0.01   # raw scale: "cycle"
    zc = units(Mc)
    tc = model_test(zc, "logistic", B=199, seed=2)
    assert tc["p_res"] <= 0.01 and tc["R_C_nc"] > 0, tc
    # the frozen co-primary H1b: projected replicate vectors reproduce the residual cyclic energy
    # (T(+1) = k^2 R_C), a pure bounded ladder is not flagged, a sign-reversing cycle is, and groups
    # flip independently (floor 1/2^(k-1) per group)
    N5, k5 = 5, 6
    a5 = [rnd.gauss(0, 0.9) for _ in range(N5)]
    b5 = [rnd.gauss(0, 0.6) for _ in range(N5)]

    def units5(cyc):
        Mx = [[sigmoid(-2.2 + a5[i] + b5[j]) if i != j else None for j in range(N5)] for i in range(N5)]
        for (i, j) in ((0, 1), (1, 2), (2, 0)):
            Mx[i][j] += cyc
            Mx[j][i] -= cyc
        return [[[Mx[i][p] + 0.004 * rnd.gauss(0, 1) if i != p else 0.0 for i in range(N5)] for _ in range(k5)]
                for p in range(N5)]
    zl = units5(0.0)
    vecs, f5 = residual_replicate_vectors(zl)
    tplus = sum(sum(v[e] for v in vecs) ** 2 for e in range(len(vecs[0])))
    want = k5 * k5 * energies(_sub(_means(zl), f5["F"]))[1]   # (exact at the LS optimum; up to its tolerance)
    assert abs(tplus - want) < 1e-6 * max(tplus, 1e-30), (tplus, want)
    om = residual_omnibus([[zl, units5(0.0)], [units5(0.0)]])
    assert om["p_flip"] > 0.01 and om["conditions"] == 3 and abs(om["flip_min_p"] - 1 / 32 ** 2) < 1e-15, om["p_flip"]
    oc = residual_omnibus([[units5(0.08), units5(0.08)], [units5(0.08)]], B=19, seed=3)
    # (the bootstrap's pseudo-means here leave [0, 1]; refits stall along a weak combination - the exact
    # Gauss-Newton probe realizes a lower SSE - and are correctly unconverged, which withholds p_boot. Seeded,
    # hence pinned (review of #49, round 4): 16 of 19 draws, 31 of 57 refits unconverged, 21 probe-certified)
    bd = oc["boot_fit_diag"]
    assert oc["p_flip"] <= 1 / 32 ** 2 + 1e-12 and oc["p_boot"] is None and oc["boot_not_converged"] == 16,         (oc["p_flip"], oc["p_boot"], oc["boot_not_converged"])
    assert (bd["fits"], bd["unconverged"], bd["probed"], bd["probe_certified"]) == (57, 31, 52, 21), bd
    assert bd["max_flat_sse"] == 0 and oc["fit_diag"]["fits"] == 3 and oc["fit_diag"]["unconverged"] == 0, oc["fit_diag"]
    assert oc["valid"] and oc["fits_converged"] == 3, oc["invalid"]
    # an unconverged mean fit makes H1b invalid (no p-value, the computed one kept as a diagnostic)
    zc5 = units5(0.08)
    fu = dict(fit_matrix(zc5), converged=False)
    ou = residual_omnibus([[zc5]], fits=[[fu]], B=5)
    assert ou["p_flip"] is None and ou["p_boot"] is None and not ou["valid"] and "not converged" in ou["invalid"]
    assert ou["p_flip_unconverged"] is not None and ou["fits_converged"] == 0, ou
    # the Aranda-Ordaz link is finite and accurate at every lam >= 0, also where lam e^eta is large for
    # tiny lam (review round 3: the old series overflowed at eta = 30, lam = 1e-10), and its Jacobian
    # matches finite differences in the series, the exact and the cloglog regime
    m3 = Model("aoceil", 3)
    cells3 = _cells(3)
    for eta, lam_ in ((30.0, 1e-10), (30.0, 0.0), (-3.0, 1e-12), (2.0, 0.7), (35.0, 1e-16), (-5.0, 4.0)):
        th = [eta, 0.0, 0.0, 0.0, 0.0, math.sqrt(lam_), 0.3]
        g, J = m3.eval(th, cells3)
        assert all(0.0 <= v <= 1.0 for v in g), (eta, lam_, g)
        exact = math.log1p(lam_ * math.exp(eta)) / lam_ if lam_ > 0 else math.exp(eta)
        U = 1.0 / 1.09
        assert abs(g[0] - U * (1.0 - math.exp(-exact))) < 1e-12, (eta, lam_)
        for pk in (0, 5, 6):
            hh = 1e-6 * max(1.0, abs(th[pk]))
            tp, tm = list(th), list(th)
            tp[pk] += hh
            tm[pk] -= hh
            num = (m3.eval(tp, cells3)[0][0] - m3.eval(tm, cells3)[0][0]) / (2 * hh)
            assert abs(num - J[0][pk]) < 1e-5 * max(1.0, abs(num)), (eta, lam_, pk, num, J[0][pk])
    # transforms
    h, eps = transform("logit:0.001")
    assert eps == 0.001 and abs(h(0.0) - math.log(0.001 / 0.999)) < 1e-12 and h(0.5) == 0.0
    h, eps = transform("asin")
    assert eps is None and abs(h(1.0) - math.pi / 2) < 1e-12
    rows = [{"s": -0.05, "f0": 0.05}, {"s": None, "f0": 0.05}, {"s": 0.1, "f0": 0.05}]
    tr, nclip = transform_rows(rows, "logit:0.001")
    assert nclip == 1 and tr[1]["s"] is None and abs(tr[2]["s"] - (math.log(0.15 / 0.85) - math.log(0.05 / 0.95))) < 1e-12
    print("bounded selftest: ok")


if __name__ == "__main__":
    selftest()

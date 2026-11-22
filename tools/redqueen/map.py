#!/usr/bin/env python3
"""map.py: the registered Level-1 map fitter (design v4 §6.1-6.4): two heads, one embedding.

Capture head (the primary one): for prey snapshot i and predator snapshot j, on the empirical-logit
scale of the capture fraction C/B,
    E[z_ij] = G( F_C(a_j, b_i) + u_i.v_j )
  - G, the flexible increasing BOUNDED link (v4 §6.1, a monotone spline link):
        G(eta) = logit(lo + (hi - lo) sigma(h(eta)))
    h is a monotone linear spline with `basis` nodal values at frozen knots (quantiles 0.02..0.98 of the
    fitting pairs' predictor at the first link fit). Its two end values are PINNED at the identity
    (h(k_1) = k_1, h(k_L) = k_L: the location / scale gauge that F_C carries), every interval slope is at
    least LINK_MIN_SLOPE, and beyond the end knots h extends linearly with the end slopes (monotone). Its
    interior values are fitted by Gauss-Newton under the monotone constraints (an exact QP) with a
    slope-difference smoothness penalty; the asymptotes lo, hi on the registered grid (LINK_LO x LINK_HI;
    lo = 0, hi = 1 with h the identity is the identity link). Refitted every LINK_EVERY sweeps.
  - F_C, the two-way monotone tensor baseline: a k x k piecewise-bilinear surface (k = 6 basis functions
    per axis registered; 4 and 8 the registered sensitivities) over the predator and prey qualities, knots
    at the qualities' quantiles, nondecreasing in a (predator quality) and nonincreasing in b (prey quality):
    its k^2 coefficients by an exact active-set QP under the 2k(k-1) monotonicity constraints with a
    second-difference penalty. Beyond the knot box the surface is EXTENDED linearly with one constant slope
    per side (the mean terminal-interval slope along that edge), which keeps it monotone and continuous
    everywhere (bilinear extrapolation does not: Codex #66 r1 P2-5).
  - u_i.v_j, the rank-r specificity (r = 0..4), shared with the survival head, CENTRED on the fixed opponent
    distributions (v4 §6.3: E_muQ[u] = 0 over the eight external prey references, E_muP[v] = 0 over the
    predator references), enforced exactly inside every node update (a Lagrange-constrained solve over the
    reference nodes); center="train_c" is the registered second distribution (the training-C snapshots).
Survival head, fitted jointly (v4 §6.2: the predator-free baseline is a latent, not a plug-in):
    logit S_i0 = c_i                       (the prey snapshot's predator-free controls)
    logit S_ij = c_i + F_S(a^S_j, b^S_i) + u_i' D_S v_j
  with its OWN ordered qualities a^S, b^S, its own monotone baseline F_S (nonincreasing in a^S,
  nondecreasing in b^S) and a full r x r D_S (embedding="separate", the registered sensitivity: its own
  embedding u^S_i.v^S_j instead). c_i has a hierarchical prior N(cbar, tau_c^2) fitted on the accessible
  controls, so a prey without accessible controls is still a measured latent.
CONTROL ACCESS (Codex #66 r1 P1-1): a fit reads the predator-free controls of the prey in `ctrl` ONLY
(control_access: prey with a training-role fitting pair, and, in a time-limited fit, at or before its
time bound): the control noise, the prior, the initialization, the fit and the objective never see an
excluded control.
Working likelihoods: Gaussian on the empirical logits, capture cells weighted by 1 / V(p) of the registered
capture-level variance function (var_fn: in production the noise bank's), normalized to mean 1. ONE
ABSOLUTE UNIT for every row (capture_scale, Codex #66 r2 P2-1): a weight-1 capture row has variance unit =
phi / (R mean(1/V)), so weight / unit is each row's absolute precision; the exposed survival rows, the
controls and the c_i prior are weighted in that unit (unit / their variance).
BANK MODE (Red Queen recovery option A, A_design_v5.md section 3.3; the hooks are None in planning mode and in
every numerical fit, which then run exactly as before): var_fn is the bank's working variance W, the
empirical-logit replicate variance of obslaw's frozen fitter table at the fitted mean; rep_prior {"nu0": nu0_C}
shrinks each cell's replicate variance toward phi W with the bank's prior degrees of freedom (capture_scale;
the bank artifact's map_variance rule, obslaw.MAP_VARIANCE_RULE; nu0 None: full pooling); score_law (A, L) is
the bank's latent law, which the count score uses at mu^ = m_z^-1(predicted empirical logit) with phi scaling
the latent variance (_score_law), the integration step bounding the composed location's slope (_score_need), the
integration range certified by the end-node check and a tail bound (_tail_ok; A_design_v5 clarification 2, D1). A
rep_prior or score_law without a var_fn is refused. THIS IS ALSO THE PRODUCTION MAP'S PATH (A_design_v5 3.3,
design v4 D:711): the production map fit must call fit_best with the same bank-derived var_fn (W), rep_prior
(nu0_C) and score_law from the adopted bank/3 artifact's frozen tables; a different production variance model
would need its own prospective amendment and a recovery re-run.

Fitting: alternating, from the additive fit: the capture surface (IRLS through the link), the link, the
survival surface, the c_i and D_S, then every prey node's (b_i, b^S_i, u_i) and every predator node's
(a_j, a^S_j, v_j) by damped Gauss-Newton over both heads' rows (the predator step at the updated prey
nodes), the qualities standardized over the fitting nodes; held-out populations are placed by their support
pairs alone. The embedding starts WARM (q30b: the top-r singular vectors of the degree-normalized residual
matrix of the rank-0 spline baseline; start="cold": small random normals). Every QP reports its KKT status
(m["qp"]: every solve, the warm start's and each link Gauss-Newton step's included). Level 1 is placed on
the common cross-world support alone (option (b) is dropped: fit refuses own_layer); within-world pairs get
the cross-fitted STAGE-2 own-world layer for either head (own_world_stage2: a shared lag curve plus shrunk
per-world deviations; an unseen world integrates its lag-dependent deviation, world_var per lag bin).

THE PREDICTIVE MODEL (v4 §6.2, §7.4, §7.6): after the fit, the node blocks' Laplace covariances (the working
model's Hessian per prey block (c_i, b_i, b^S_i, u_i) and predator block (a_j, a^S_j, v_j) times the
absolute unit: block-diagonal, conditional on the surfaces, the link and D_S), the replicate dispersion
phi (within-pair replicate scatter / V) and the pair-residual variance tau^2 ON THE PREDICTOR SCALE (the
registered placement: delta_ij inside the link; pair_variance, with the strongly shrunk BLUPs of the fitting
pairs). pred_eta: an unseen pair's predictor and its variance there (posterior + tau^2 [+ an unseen world's
own-world deviation]); pred_count_lpd, the registered score: the capture-count log predictive density under
the bounded observation model of Annex H.9.2 (a rounded latent logit-normal: normalized over 0..B, no
Bernoulli capture opportunities) at G(eta + e) with a fresh replicate's variance phi V, e integrated through
the link (exact for the identity link with a constant variance; otherwise a log-space trapezoid grid with
the registered heteroscedastic integrand at every node, every observation checked a posteriori for
resolution and range and refined or extended; unresolved cases are reported, a non-finite score refused,
nothing silently capped); pred_var: the first-order moments
(phi V + G'(eta)^2 s2), for the Gaussian diagnostic only. pair_variance solves its likelihood score
safeguarded (bracketing and bisection); world_deviation_var subtracts each cell's own sampling noise. survival_posterior: q_ij = E[sigma(c_i + eta^S_ij) - sigma(c_i) | data] under the joint (c_i,
exposed-logit) covariance (2-D Gauss-Hermite), with its SD.
"""
from __future__ import annotations

import math

import numpy as np

K = 6                                   # basis functions per axis (v4 §6.1)
BASES = (4, 6, 8)                       # the registered value and its two sensitivities
SMOOTH = 1e-2
LINK_LO = (0.0, 0.01, 0.02, 0.04)
LINK_HI = (0.7, 0.8, 0.9, 0.95, 1.0)
LINK_SMOOTH = 1e-2                      # (the link's slope-difference penalty, relative to its data scale)
LINK_MIN_SLOPE = 0.05                   # (h' >= this on every interval: strictly increasing)
LINK_QUANTILES = (0.02, 0.98)           # (the link knots: equally spaced quantile levels between these)
LINK_EVERY = 5
LINK_STEPS = 3
CENTERS = ("references", "train_c")
EMBEDDINGS = ("shared", "separate")
QP_ITERS = 400
GH_NODES = 12
C_PRIOR_FLOOR = 0.01                    # (the c_i prior variance floor)


# ------------------------------------------------------------------ the QP
def _qp_status(A, c, C, d, x, W, lam, converged, iters):
    g = A @ x - c
    if lam is None:
        lam = np.linalg.lstsq(C[W].T, g, rcond=None)[0] if W else np.zeros(0)
    stat = g - (C[W].T @ lam if W else 0.0)
    viol = float(max(0.0, float(np.max(d - C @ x)))) if len(C) else 0.0
    return {"converged": bool(converged), "iterations": int(iters),
            "stationarity": float(np.max(np.abs(stat)) / (1.0 + float(np.max(np.abs(c))))),
            "violation": viol, "min_multiplier": float(lam.min()) if len(lam) else 0.0}


def monotone_qp(A, c, C, x0, d=None, iters=QP_ITERS, tol=1e-10):
    """min 0.5 x'Ax - c'x subject to Cx >= d (d = 0 by default), from a feasible x0 (primal active set;
    A positive definite) -> (x, status). status (Codex #66 r1 P3: never a silent cap): converged (the step
    on the working set vanished with every multiplier >= -1e-9: the KKT point), iterations, and the KKT
    residuals: stationarity |Ax - c - C_W' lam|_inf / (1 + |c|_inf), the largest violation of Cx >= d, the
    most negative multiplier. At the iteration cap the last iterate is returned with converged False."""
    d = np.zeros(len(C)) if d is None else np.asarray(d, float)
    x = np.array(x0, float)
    n = len(x)
    W = []
    for it in range(iters):
        g = A @ x - c
        if W:
            CW = C[W]
            kkt = np.block([[A, -CW.T], [CW, np.zeros((len(W), len(W)))]])
            sol = np.linalg.lstsq(kkt, np.concatenate([-g, np.zeros(len(W))]), rcond=None)[0]
            p, lam = sol[:n], sol[n:]
        else:
            p, lam = np.linalg.solve(A, -g), np.zeros(0)
        if np.linalg.norm(p) <= tol * (1.0 + np.linalg.norm(x)):
            if not len(lam) or lam.min() >= -1e-9:
                return x, _qp_status(A, c, C, d, x, W, lam, True, it + 1)
            W.pop(int(np.argmin(lam)))
            continue
        Cp = C @ p
        alpha, block = 1.0, None
        for i in np.flatnonzero(Cp < -1e-14):
            if i in W:
                continue
            step = (d[i] - C[i] @ x) / Cp[i]
            if step < alpha:
                alpha, block = max(step, 0.0), int(i)
        x = x + alpha * p
        if block is not None:
            W.append(block)
    return x, _qp_status(A, c, C, d, x, W, None, False, iters)


def qp_summary(statuses):
    st = [s for s in statuses if s is not None]
    return {"solves": len(st), "unconverged": sum(not s["converged"] for s in st),
            "max_stationarity": max((s["stationarity"] for s in st), default=0.0),
            "max_violation": max((s["violation"] for s in st), default=0.0)}


# ------------------------------------------------------------------ the monotone surface
def _constraints(k=K, inc_a=True, inc_b=False):
    """Rows of C (C theta >= 0): theta[k+1,l] - theta[k,l] (sign by inc_a) and theta[k,l+1] -
    theta[k,l] (sign by inc_b), theta flattened row-major (a index first)."""
    rows = []
    for i in range(k - 1):
        for j in range(k):
            r = np.zeros(k * k)
            s = 1.0 if inc_a else -1.0
            r[(i + 1) * k + j], r[i * k + j] = s, -s
            rows.append(r)
    for i in range(k):
        for j in range(k - 1):
            r = np.zeros(k * k)
            s = 1.0 if inc_b else -1.0
            r[i * k + j + 1], r[i * k + j] = s, -s
            rows.append(r)
    return np.array(rows)


def _smooth_penalty(k=K):
    d2 = np.zeros((k - 2, k))
    for i in range(k - 2):
        d2[i, i:i + 3] = (1.0, -2.0, 1.0)
    eye = np.eye(k)
    Da, Db = np.kron(d2, eye), np.kron(eye, d2)
    return Da.T @ Da + Db.T @ Db


_MATS = {}


def surface_mats(k, direction):
    """(constraints, penalty) of a k x k surface with direction ("inc"|"dec", "inc"|"dec")."""
    if (k, direction) not in _MATS:
        _MATS[(k, direction)] = (_constraints(k, direction[0] == "inc", direction[1] == "inc"), _smooth_penalty(k))
    return _MATS[(k, direction)]


CONS = {dr: surface_mats(K, dr)[0] for dr in (("inc", "dec"), ("dec", "inc"))}
PEN = _smooth_penalty(K)


def _coords(x, kn):
    """The tile of x on knots kn: (index, fraction, width, excess). The tile is that of x CLAMPED to
    [kn_0, kn_-1], so the fraction stays in [0, 1]; the excess x - clamp(x) carries the extension."""
    xc = np.clip(x, kn[0], kn[-1])
    i0 = np.clip(np.searchsorted(kn, xc, side="right") - 1, 0, len(kn) - 2)
    h = kn[i0 + 1] - kn[i0]
    return i0, (xc - kn[i0]) / h, h, x - xc


class Surface:
    """A k x k piecewise-bilinear surface over (a, b) with monotone coefficients (k = len(ka)). Inside the
    knot box: the bilinear interpolant. Beyond a boundary knot: the clamped value plus a LINEAR extension with
    one constant slope per side, the mean terminal-interval slope along that edge (side_slopes). Each of
    those slopes is a mean of coefficient differences of one sign, and no slope depends on the other
    coordinate, so the surface is monotone in both axes and continuous everywhere (the registered
    monotonicity-preserving extension)."""

    def __init__(self, ka, kb, direction):
        ka, kb = np.asarray(ka, float), np.asarray(kb, float)
        if len(ka) != len(kb) or len(ka) not in BASES:
            raise ValueError(f"a surface takes {BASES} knots per axis, the same on both")
        self.k = len(ka)
        self.ka, self.kb, self.direction = ka, kb, direction
        self.C, self.P = surface_mats(self.k, direction)
        self.theta = np.zeros((self.k, self.k))
        self.pen = 0.0
        self.status = None
        self.statuses = []                   # (every QP solve's status, in order: Codex #66 r2 P3)

    def side_slopes(self, T=None):
        """The extension slopes (a below, a above, b below, b above)."""
        T = self.theta if T is None else T
        ka, kb = self.ka, self.kb
        return (float(np.mean(T[1] - T[0])) / (ka[1] - ka[0]), float(np.mean(T[-1] - T[-2])) / (ka[-1] - ka[-2]),
                float(np.mean(T[:, 1] - T[:, 0])) / (kb[1] - kb[0]),
                float(np.mean(T[:, -1] - T[:, -2])) / (kb[-1] - kb[-2]))

    def _functionals(self):
        """side_slopes as linear functionals of the flattened coefficients."""
        k, out = self.k, []
        for lo, hi, h, axis in ((0, 1, self.ka[1] - self.ka[0], 0), (k - 2, k - 1, self.ka[-1] - self.ka[-2], 0),
                                (0, 1, self.kb[1] - self.kb[0], 1), (k - 2, k - 1, self.kb[-1] - self.kb[-2], 1)):
            L = np.zeros((k, k))
            if axis == 0:
                L[hi, :] += 1.0 / (k * h)
                L[lo, :] -= 1.0 / (k * h)
            else:
                L[:, hi] += 1.0 / (k * h)
                L[:, lo] -= 1.0 / (k * h)
            out.append(L.ravel())
        return out

    def value(self, a, b, grads=False):
        ia, ta, ha, ea = _coords(a, self.ka)
        ib, tb, hb, eb = _coords(b, self.kb)
        T = self.theta
        t00, t10, t01, t11 = T[ia, ib], T[ia + 1, ib], T[ia, ib + 1], T[ia + 1, ib + 1]
        f = t00 * (1 - ta) * (1 - tb) + t10 * ta * (1 - tb) + t01 * (1 - ta) * tb + t11 * ta * tb
        sal, sah, sbl, sbh = self.side_slopes()
        sa = np.where(ea < 0, sal, sah)
        sb = np.where(eb < 0, sbl, sbh)
        f = f + sa * ea + sb * eb
        if not grads:
            return f
        fa = np.where(ea != 0, sa, ((t10 - t00) * (1 - tb) + (t11 - t01) * tb) / ha)
        fb = np.where(eb != 0, sb, ((t01 - t00) * (1 - ta) + (t11 - t10) * ta) / hb)
        return f, fa, fb

    def fit(self, a, b, y, w):
        k = self.k
        n = k * k
        ia, ta, _, ea = _coords(a, self.ka)
        ib, tb, _, eb = _coords(b, self.kb)
        cols = np.stack([ia * k + ib, (ia + 1) * k + ib, ia * k + ib + 1, (ia + 1) * k + ib + 1], axis=1)
        vals = np.stack([(1 - ta) * (1 - tb), ta * (1 - tb), (1 - ta) * tb, ta * tb], axis=1)
        ext = (ea != 0) | (eb != 0)
        inn = ~ext
        ci, vi, wi, yi = cols[inn], vals[inn], w[inn], y[inn]
        A = np.zeros(n * n)
        c = np.zeros(n)
        for p in range(4):
            for q in range(4):
                A += np.bincount(ci[:, p] * n + ci[:, q], weights=wi * vi[:, p] * vi[:, q], minlength=n * n)
            c += np.bincount(ci[:, p], weights=wi * vi[:, p] * yi, minlength=n)
        A = A.reshape(n, n)
        if ext.any():                          # (the extension's rows: dense, few)
            X = np.zeros((int(ext.sum()), n))
            rows = np.arange(len(X))
            for p in range(4):
                np.add.at(X, (rows, cols[ext, p]), vals[ext, p])
            sal, sah, sbl, sbh = self._functionals()
            e_a, e_b = ea[ext], eb[ext]
            X += (np.minimum(e_a, 0.0)[:, None] * sal + np.maximum(e_a, 0.0)[:, None] * sah
                  + np.minimum(e_b, 0.0)[:, None] * sbl + np.maximum(e_b, 0.0)[:, None] * sbh)
            we = w[ext]
            A += X.T @ (we[:, None] * X)
            c += X.T @ (we * y[ext])
        scale = np.trace(A) / n
        A = A + SMOOTH * scale * self.P + 1e-8 * scale * np.eye(n)
        x0 = self.theta.ravel()
        if (self.C @ x0 < -1e-9).any():
            x0 = np.full(n, float(np.sum(w * y) / np.sum(w)))
        th, self.status = monotone_qp(A, c, self.C, x0)
        self.statuses.append(self.status)
        self.theta = th.reshape(k, k)
        self.pen = float(SMOOTH * scale * th @ self.P @ th)


def _knots(x, k=K):
    kn = np.quantile(x, np.linspace(0.0, 1.0, k))
    for i in range(1, k):                    # strictly increasing
        if kn[i] <= kn[i - 1]:
            kn[i] = kn[i - 1] + 1e-6
    return kn


# ------------------------------------------------------------------ the link
def _sig(x):
    return 0.5 * (1.0 + np.tanh(0.5 * np.asarray(x, float)))


class Link:
    """G(eta) = logit(lo + (hi - lo) sigma(h(eta))), h the monotone linear spline (see the module doc);
    knots None: h is the identity (the start; lo = 0, hi = 1 then make G the identity)."""

    def __init__(self, knots=None, theta=None, lo=0.0, hi=1.0):
        self.knots = None if knots is None else np.asarray(knots, float)
        self.theta = None if knots is None else (self.knots.copy() if theta is None else np.asarray(theta, float))
        self.lo, self.hi = float(lo), float(hi)
        self.pen = 0.0
        self.status = None
        self.statuses = []                   # (every QP solve's status, carried by copy: Codex #66 r2 P3)

    def copy(self):
        lk = Link(self.knots, None if self.theta is None else self.theta.copy(), self.lo, self.hi)
        lk.pen, lk.status, lk.statuses = self.pen, self.status, list(self.statuses)
        return lk

    def identity(self):
        return self.lo == 0.0 and self.hi == 1.0 and (self.knots is None or np.array_equal(self.theta, self.knots))

    def _seg(self, eta):
        kn = self.knots
        i0 = np.clip(np.searchsorted(kn, eta, side="right") - 1, 0, len(kn) - 2)
        return i0, (eta - kn[i0]) / (kn[i0 + 1] - kn[i0])       # (unclipped: the end segments extend linearly)

    def h(self, eta, deriv=False):
        eta = np.asarray(eta, float)
        if self.knots is None:
            return (eta, np.ones_like(eta)) if deriv else eta
        i0, t = self._seg(eta)
        th, kn = self.theta, self.knots
        hv = th[i0] * (1 - t) + th[i0 + 1] * t
        if not deriv:
            return hv
        return hv, (th[i0 + 1] - th[i0]) / (kn[i0 + 1] - kn[i0])

    def _from_h(self, hv):
        """(G, dG/dh) at spline values hv."""
        if self.lo == 0.0 and self.hi == 1.0:
            return hv, np.ones_like(hv)
        s, sc = _sig(hv), _sig(-hv)
        p = self.lo + (self.hi - self.lo) * s
        q = (1.0 - self.hi) + (self.hi - self.lo) * sc          # (= 1 - p, without cancellation)
        with np.errstate(divide="ignore"):
            return np.log(p) - np.log(q), (self.hi - self.lo) * s * sc / (p * q)

    def G(self, eta):
        return self._from_h(self.h(eta))[0]

    def max_slope(self, lo_, hi_):
        """A CONSERVATIVE bound on G' over [lo_, hi_]: the steepest spline interval meeting the range (the
        linear extensions included) times 1 / (hi - lo), which bounds the logistic factor
        (hi - lo) s (1 - s) / (p (1 - p)) whenever 0 <= lo < hi <= 1 (p >= (hi - lo) s, 1 - p >= (hi - lo)(1 - s))."""
        if self.knots is None:
            sl = 1.0
        else:
            kn, th = self.knots, self.theta
            slopes = np.diff(th) / np.diff(kn)
            a = int(np.clip(np.searchsorted(kn, lo_, side="right") - 1, 0, len(kn) - 2))
            b = int(np.clip(np.searchsorted(kn, hi_, side="right") - 1, 0, len(kn) - 2))
            sl = float(slopes[a:b + 1].max())
        return sl if (self.lo == 0.0 and self.hi == 1.0) else sl / (self.hi - self.lo)

    def dG(self, eta):
        hv, hp = self.h(eta, True)
        return self._from_h(hv)[1] * hp

    def _system(self):
        """The interior QP's fixed parts: (C, d, P_full) for x = theta[1:-1]: theta[k+1] - theta[k] >=
        LINK_MIN_SLOPE (k_{k+1} - k_k), the ends pinned at the knots; P_full penalizes slope differences."""
        kn = self.knots
        L = len(kn)
        dk = np.diff(kn)
        C = np.zeros((L - 1, L - 2))
        d = LINK_MIN_SLOPE * dk
        for k in range(L - 1):
            if k + 1 <= L - 2:
                C[k, k] += 1.0
            else:
                d[k] -= kn[-1]
            if k >= 1:
                C[k, k - 1] -= 1.0
            else:
                d[k] += kn[0]
        Dm = np.zeros((L - 2, L))
        for k in range(L - 2):
            Dm[k, k + 1] += 1.0 / dk[k + 1] + 1.0 / dk[k]
            Dm[k, k + 2] -= 1.0 / dk[k + 1]
            Dm[k, k] -= 1.0 / dk[k]
        return C, d, Dm.T @ Dm

    def fit_h(self, base, z, w, steps=LINK_STEPS):
        """Gauss-Newton on the interior nodal values of h at the current (lo, hi) (each step an exact QP)."""
        kn = self.knots
        L = len(kn)
        C, d, P = self._system()
        th = self.theta.copy()
        fixed = np.zeros(L)
        fixed[0], fixed[-1] = kn[0], kn[-1]
        for _ in range(steps):
            i0, t = self._seg(base)
            hv = th[i0] * (1 - t) + th[i0 + 1] * t
            g, gh = self._from_h(hv)
            yl = z - g + gh * hv                  # (z ~ g + gh (h_new - h): yl = gh h_new = J theta_new)
            A = np.zeros(L * L)
            c = np.zeros(L)
            for cp, vp in ((i0, (1 - t) * gh), (i0 + 1, t * gh)):
                for cq, vq in ((i0, (1 - t) * gh), (i0 + 1, t * gh)):
                    A += np.bincount(cp * L + cq, weights=w * vp * vq, minlength=L * L)
                c += np.bincount(cp, weights=w * vp * yl, minlength=L)
            A = A.reshape(L, L)
            scale = max(float(np.trace(A)) / L, 1e-12)
            A = A + LINK_SMOOTH * scale * P
            Af = A[1:-1, 1:-1] + 1e-8 * scale * np.eye(L - 2)
            cf = c[1:-1] - A[1:-1, :] @ fixed
            x, self.status = monotone_qp(Af, cf, C, th[1:-1], d)
            self.statuses.append(self.status)
            th = np.concatenate([[kn[0]], x, [kn[-1]]])
            self.pen = float(LINK_SMOOTH * scale * th @ P @ th)
        self.theta = th


def _link_knots(base, k):
    kn = np.quantile(base, np.linspace(LINK_QUANTILES[0], LINK_QUANTILES[1], k))
    for i in range(1, k):
        if kn[i] <= kn[i - 1]:
            kn[i] = kn[i - 1] + 1e-6
    return kn


def update_link(lk, base, z, w, basis=K):
    """One registered link update: the knots frozen at the first update; h at the current asymptotes, the
    asymptotes profiled over the registered grid with h fixed, then h again -> the new Link."""
    lk = lk.copy() if lk.knots is not None else Link(_link_knots(base, basis), lo=lk.lo, hi=lk.hi)
    lk.fit_h(base, z, w)
    best = None
    for lo in LINK_LO:
        for hi in LINK_HI:
            sse = float(np.sum(w * (z - Link(lk.knots, lk.theta, lo, hi).G(base)) ** 2))
            if best is None or sse < best[0]:
                best = (sse, lo, hi)
    lk.lo, lk.hi = best[1], best[2]
    lk.fit_h(base, z, w)
    return lk


# ------------------------------------------------------------------ access, centring, nodes
def control_access(D, idx, tmax=None):
    """The prey whose predator-free controls a fit may read (Codex #66 r1 P1-1; v4 §7.1, §7.3): prey with a
    TRAINING-role pair among the fitting pairs idx (a snapshot held out for validation or test enters only
    through its support pairs, and its non-support outcomes, controls included, never fit global
    parameters), and with tmax (a time-limited fit: §7.3's 120M) only prey at times <= tmax."""
    import recovery as rec
    idx = np.asarray(idx)
    m = np.zeros(D.nQ, bool)
    m[D.qi[idx[D.role[idx] == rec.ROLES.index("training")]]] = True
    if tmax is not None:
        m &= D.qt <= tmax
    return m


def center_sets(D, on_q, on_p, center="references"):
    """The node sets of the fixed opponent distributions (v4 §6.3) a fit centres u and v on: "references":
    the external references with fitting pairs (the eight of each guild in the primary fit; a time-limited
    fit has only its early ones); "train_c": the registered second distribution, the training-C snapshots
    with fitting pairs (training world, not held out)."""
    if center == "references":
        return np.flatnonzero(D.qref & on_q), np.flatnonzero(D.pref & on_p)
    if center != "train_c":
        raise ValueError(f"center {center!r}: one of {CENTERS}")
    out = []
    for w_, ref, held, on in ((D.qw, D.qref, D.qheld, on_q), (D.pw, D.pref, D.pheld, on_p)):
        ok = (w_ >= 0) & ~ref
        tr = np.zeros(len(w_), bool)
        tr[ok] = (D.treat[w_[ok]] == "C") & (D.wsplit[w_[ok]] == "train") & (held[ok] == "train")
        out.append(np.flatnonzero(tr & on))
    return out[0], out[1]


def _solve_nodes(idx, X, y, w, n, ridge, damp_to=None, damp=0.0, center=None):
    """Per node k: (sum w X_e X_e' + diag(ridge) [+ damping]) theta_k = sum w X_e y_e. center (S, cols): the
    columns cols of the nodes S are constrained to sum to zero (an exact Lagrange solve: v4 §6.3's centring)."""
    d = X.shape[1]
    A = np.empty((n, d, d))
    rhs = np.empty((n, d))
    for p in range(d):
        rhs[:, p] = np.bincount(idx, weights=w * X[:, p] * y, minlength=n)
        for q in range(p, d):
            A[:, p, q] = np.bincount(idx, weights=w * X[:, p] * X[:, q], minlength=n)
            A[:, q, p] = A[:, p, q]
    A[:, np.arange(d), np.arange(d)] += ridge
    if damp_to is not None and damp:          # Levenberg damping of the first columns toward damp_to
        dt = damp_to.reshape(n, -1)
        for j in range(dt.shape[1]):
            A[:, j, j] += damp
            rhs[:, j] += damp * dt[:, j]
    th = np.linalg.solve(A, rhs[..., None])[..., 0]
    if center is not None:
        S, cols = center
        if len(S) and len(cols):
            E = np.zeros((d, len(cols)))
            E[cols, np.arange(len(cols))] = 1.0
            AinvE = np.linalg.solve(A[S], np.broadcast_to(E, (len(S), d, len(cols))))
            M = AinvE[:, cols, :].sum(axis=0)
            lam_ = np.linalg.solve(M, th[S][:, cols].sum(axis=0))
            th[S] -= AinvE @ lam_
    return th


def _noise(x):
    """The noise variance of a replicate mean: the mean replicate variance / R."""
    return float(np.mean(np.var(x, axis=1, ddof=1)) / x.shape[1])


UNIT_FLOOR = 1e-6                       # (the absolute unit's floor: noiseless data)


def _check_nu0(nu0):
    """The bank's prior degrees of freedom nu0 (A_design_v5 3.1: a positive float, or None for full pooling)."""
    if nu0 is None:
        return None
    if isinstance(nu0, bool) or not isinstance(nu0, (int, float, np.floating, np.integer)) \
            or not math.isfinite(float(nu0)) or float(nu0) <= 0.0:
        raise ValueError(f"nu0 {nu0!r}: a positive finite number, or None (full pooling)")
    return float(nu0)


def capture_scale(V, zrep, R, nu0=None):
    """The capture rows' working weights and their ABSOLUTE scale under the registered predictive model
    (Codex #66 r2 P2-1). Cell e's replicate-mean variance is v_e = phi V_e / R, with phi = mean(zrep / V)
    the replicate dispersion of the variance function V (zrep: the cells' replicate variances). The weights
    are w_e = (1 / V_e) / mean(1 / V) (mean 1, so the penalties keep their meaning), and one weight unit is
    unit = phi / (R mean(1 / V)), so unit / w_e = v_e exactly: a weighted Hessian times unit is the absolute
    covariance. V None (unweighted): w = 1, phi = mean(zrep), unit = phi / R. -> (w, unit, phi).
    nu0 (bank mode, A_design_v5 3.3; the bank artifact's map_variance rule, obslaw.MAP_VARIANCE_RULE): the
    cells' variances are shrunk toward the pooled working variance, v~_e = (nu0 phi V_e + (R - 1) zrep_e) /
    (nu0 + R - 1) with phi as above (unchanged definition; V_e and zrep_e both empirical-logit variances), and
    w_e = (1 / v~_e) / mean(1 / v~), unit = 1 / (R mean(1 / v~)), so unit / w_e = v~_e / R exactly. nu0 None
    (full pooling, planning, numerical) is exactly the rule above. nu0 needs V (refused without it).
    The nu0 branch is evaluated IN LOGARITHMS (A_design_v5 clarification 2, Revisions 4 and 4a, "Log-space
    evaluation", which supersedes the arithmetic, the intermediate checks and the compatibility requirements of
    Revisions 1-3: item 0), so no intermediate (phi V, v~, 1 / v~, mean(1 / v~)) is ever formed as a float: none can
    overflow or cause a refusal (D3 needs only the exact v~ positive), and only negligible max-shifted terms of a sum
    underflow. With n cells, l(x) = log x (log 0 = -inf), lae = logaddexp and lse(x) = m + log sum e^(x - m) with m
    = max x and a pairwise sum (np.sum): l_D = lae(l(nu0), l(R - 1)), l_a = l(nu0) - l_D, l_ac = l(R - 1) - l_D (a =
    nu0 / (nu0 + R - 1), ac = 1 - a); l_phi = lse(l(zrep_e) - l(V_e)) - log n; l(v~_e) = lae(l_a + l_phi + l(V_e),
    l_ac + l(zrep_e)); l_M = lse(-l(v~_e)) - log n (M = mean(1 / v~)); returned: phi = e^l_phi, w_e = e^(-l(v~_e) -
    l_M), unit = e^(-log R - l_M). The accuracy contract (item 3): each returned quantity is within 1e-10 relative of
    the formula's exact value on the floored float inputs (a subnormal one: 1e-10 relative + 2^-1074); no byte
    requirement against the float forms. The refusal rule (item 4, Revision 4a): refused when a RETURNED quantity's
    computed logarithm is above log(largest finite float) or at or below log 2^-1075 (the value rounds to zero); in
    floats, in range is log 2^-1075 < l <= log(largest float), both float logarithms lying below the true values (by
    1.4e-14 and 2.4e-14), so this is exactly "not at or below" and "not above". Every successful return is finite
    and strictly positive: if the conversion e^l to binary64 still gives 0 or inf (possible only within an ulp of
    an edge, inside the indeterminate band, where a refusal is allowed; this libm gives positive finite values on
    the whole range), the call is refused, never returned. Within a factor e^(+-1e-10) of an edge either outcome is
    allowed. Its domain (clarification 2, D3; item 1): V and zrep are validated RAW, before main's 1e-8 floor of V
    (a non-finite V, -inf included, a non-finite zrep or a negative replicate variance is refused; finite values
    then take the floor exactly as before); a data set with no replicate variance in any cell (phi = 0, so every
    v~_e = 0 and the inverse-variance weights are undefined) is refused with that context, never floored and never
    fully pooled instead. No cap on nu0 (subnormal ones included) and no variance floor. nu0 None: main's code and
    bytes (the floor first, no check)."""
    nu0 = _check_nu0(nu0)
    zrep = np.asarray(zrep, float)
    if V is None:
        if nu0 is not None:
            raise ValueError("capture_scale: nu0 without a variance function V (refused)")
        phi = float(np.mean(zrep))
        return np.ones(len(zrep)), max(phi / R, UNIT_FLOOR), phi
    if nu0 is not None and not (np.all(np.isfinite(np.asarray(V, float))) and np.all(np.isfinite(zrep))):
        raise ValueError("capture_scale: a non-finite value in V or zrep (checked raw, before the 1e-8 floor of V): "
                         "the nu0 shrinkage is refused (A_design_v5 clarification 2, D3)")
    if nu0 is not None and np.any(zrep < 0.0):
        raise ValueError("capture_scale: a negative replicate variance in zrep (checked raw, before the 1e-8 floor of "
                         "V): the nu0 shrinkage is refused (A_design_v5 clarification 2, Revision 4)")
    V = np.maximum(np.asarray(V, float), 1e-8)
    if nu0 is None:
        M = float(np.mean(1.0 / V))
        phi = float(np.mean(zrep / V))
        return (1.0 / V) / M, max(phi / (R * M), UNIT_FLOOR), phi
    if not np.any(zrep):
        raise ValueError("capture_scale: every replicate variance is zero (phi = 0), so every shrunk cell variance "
                         "v~ is 0 and the inverse-variance weights are undefined: the nu0 shrinkage is refused, not "
                         "floored (A_design_v5 clarification 2, D3)")
    n = len(V)

    def lse(x):                          # (log sum e^x = m + log sum e^(x - m), m = max x; numpy's pairwise sum)
        m = float(np.max(x))
        return m + math.log(float(np.sum(np.exp(x - m))))
    with np.errstate(divide="ignore", over="ignore", invalid="ignore", under="ignore"):
        lV, lz = np.log(V), np.log(zrep)                  # (V >= 1e-8 after the floor; log 0 = -inf: a zero cell)
        l0, lR = math.log(nu0), float(np.log(np.float64(R - 1)))
        lD = float(np.logaddexp(l0, lR))                  # (log (nu0 + R - 1))
        la, lac = l0 - lD, lR - lD                        # (log a, log (1 - a))
        lphi = lse(lz - lV) - math.log(n)
        lvt = np.logaddexp(la + lphi + lV, lac + lz)      # (log v~_e)
        lM = lse(-lvt) - math.log(n)                      # (log mean(1 / v~))
        lw = -lvt - lM
        lunit = -math.log(R) - lM
    lo, hi = -1075.0 * math.log(2.0), math.log(float(np.finfo(np.float64).max))   # (log 2^-1075, log of the largest)
    bad = [f"{lab} (log {float(x)!r})" for lab, x in (("phi", lphi), ("unit", lunit)) if not lo < x <= hi]
    out = np.flatnonzero(~((lw > lo) & (lw <= hi)))
    bad += [f"w of cell {int(e)} (V {float(V[e])!r}, zrep {float(zrep[e])!r}; log {float(lw[e])!r})" for e in out[:3]]
    if bad:
        more = f"; and {len(out) - 3} more w" if len(out) > 3 else ""
        raise ValueError(f"capture_scale: a returned quantity of the nu0 shrinkage is outside the float range (its "
                         f"logarithm not in (log 2^-1075, log of the largest float] = ({lo!r}, {hi!r}]: "
                         f"{'; '.join(bad)}{more}): refused (A_design_v5 clarification 2, Revision 4a)")
    with np.errstate(under="ignore", over="ignore"):
        w, unit, phi = np.exp(lw), float(np.exp(lunit)), float(np.exp(lphi))
    if not (np.all((w > 0.0) & np.isfinite(w)) and 0.0 < unit < math.inf and 0.0 < phi < math.inf):
        raise ValueError(f"capture_scale: a returned quantity of the nu0 shrinkage is outside the float range after "
                         f"its conversion to binary64 (e^l gave 0 or inf at a logarithm within an ulp of an edge, "
                         f"inside the indeterminate band: phi {phi!r}, unit {unit!r}, w in [{float(np.min(w))!r}, "
                         f"{float(np.max(w))!r}]): refused, never returned (A_design_v5 clarification 2, Revision 4a)")
    return w, unit, phi


def pair_variance(r, s2, grid=200, iters=200, full=False):
    """The pair-residual variance tau^2 on the PREDICTOR scale (v4 §6.2: delta_ij inside the link): r the
    working residuals (z - G(eta)) / G'(eta) of the fitting pairs, s2 their replicate-mean variances on that
    scale (v / G'^2), r ~ N(0, tau^2 + s2). The weighted moment equation sum (r^2 - s2 - t) / (t + s2)^2 = 0 is
    the score of that Gaussian likelihood; a fixed-point iteration of it can cycle (Codex #66 r3 P2-2), so it
    is solved SAFEGUARDED: every + to - sign change of the score on a log grid over (0, max r^2] (the score is
    negative beyond: every term is) is bracketed and bisected to convergence, t = 0 (the floor: strong
    shrinkage) is a candidate, and the candidate of largest likelihood is returned (full: with the score
    there, the roots and convergence)."""
    r2, s2 = np.asarray(r, float) ** 2, np.asarray(s2, float)
    tmax = float(r2.max()) if len(r2) else 0.0

    def score(t):
        return float(np.sum((r2 - s2 - t) / (t + s2) ** 2))

    def loglik(t):
        return float(-0.5 * np.sum(np.log(t + s2) + r2 / (t + s2)))
    roots, ok = [], True
    if tmax > 0:
        ts = np.concatenate([[0.0], tmax * np.geomspace(1e-12, 1.0, grid)])
        gs = np.array([score(t) for t in ts])
        for k in np.flatnonzero((gs[:-1] > 0) & (gs[1:] <= 0)):
            a, b = float(ts[k]), float(ts[k + 1])
            for _ in range(iters):
                c = 0.5 * (a + b)
                if score(c) > 0:
                    a = c
                else:
                    b = c
                if b - a <= 1e-13 * b:
                    break
            else:
                ok = False
            roots.append(0.5 * (a + b))
    cands = [0.0] + roots
    t = max(cands, key=loglik)
    if full:
        return {"tau2": t, "score": score(t), "roots": roots, "converged": ok}
    return t


def top_singular(qi, pj, val, nQ, nP, k, seed=0, iters=12):
    """The top-k singular triplets of the sparse nQ x nP matrix with entries val at (qi, pj):
    randomized subspace iteration on sparse products (k + 6 columns, `iters` power steps) ->
    (U (nQ x k), s (k,), V (nP x k))."""
    rng = np.random.default_rng([seed, 3])
    ell = k + 6

    def mv(X):                                 # R @ X
        return np.stack([np.bincount(qi, weights=val * X[pj, c], minlength=nQ) for c in range(X.shape[1])], axis=1)

    def rmv(Y):                                # R' @ Y
        return np.stack([np.bincount(pj, weights=val * Y[qi, c], minlength=nP) for c in range(Y.shape[1])], axis=1)
    Q = np.linalg.qr(mv(rng.normal(size=(nP, ell))))[0]
    for _ in range(iters):
        Q = np.linalg.qr(mv(np.linalg.qr(rmv(Q))[0]))[0]
    Ub, s, Vt = np.linalg.svd(rmv(Q).T, full_matrices=False)
    return (Q @ Ub)[:, :k], s[:k], Vt[:k].T


def svd_start(qi, pj, resid, nQ, nP, rank, seed=0):
    """The warm start of the interaction embedding (q30b): the top-`rank` singular vectors of the
    degree-normalized residual matrix N = Dq^-1/2 R Dp^-1/2 (R: the fitting pairs' residuals from the
    rank-0 spline baseline, zero elsewhere), mapped back to the residual's scale under the
    configuration-model sampling E[R_ij] ~ d_i d_j / m M_ij: u = sqrt(m) Dq^-1/2 U S^1/2, v likewise
    (m pairs). A node without fitting pairs starts at 0 (it is placed by its support pairs)."""
    dq = np.bincount(qi, minlength=nQ).astype(float)
    dp = np.bincount(pj, minlength=nP).astype(float)
    rq, rp = 1.0 / np.sqrt(np.maximum(dq, 1.0)), 1.0 / np.sqrt(np.maximum(dp, 1.0))
    U, s, V = top_singular(qi, pj, resid * rq[qi] * rp[pj], nQ, nP, rank, seed)
    m = math.sqrt(len(qi))
    root = np.sqrt(np.maximum(s, 0.0))
    return m * rq[:, None] * U * root, m * rp[:, None] * V * root


def _block_cov(node, X, w, diag, nn, unit):
    """unit x (sum_rows w x x' per node + diag)^-1: the node blocks' Laplace covariances (nn x d x d)."""
    d = X.shape[1]
    H = np.zeros((nn, d, d))
    for p in range(d):
        for q in range(p, d):
            H[:, p, q] = np.bincount(node, weights=w * X[:, p] * X[:, q], minlength=nn)
            H[:, q, p] = H[:, p, q]
    H[:, np.arange(d), np.arange(d)] += diag
    return unit * np.linalg.inv(H)


# ------------------------------------------------------------------ the fitter
def fit(D, idx, data, rank, lam, own_layer=False, iters=40, seed=0, survival=True, link=True,
        lam_ab=1e-3, lam_world=10.0, init=None, start="warm", var_fn=None, ctrl=None, basis=K,
        embedding="shared", center="references", rep_prior=None, score_law=None):
    """The registered map on the fitting pairs idx -> its parameters (see the module doc). start:
    "warm" (the embedding starts from svd_start on the rank-0 spline residuals) or "cold" (small
    random normals); init (a previous fit) overrides both; fit_best runs both and keeps the lower
    penalized training objective. var_fn (the registered capture-level variance function, p ->
    per-replicate variance of the empirical logit; in production from the noise bank, v4 §7.4):
    every capture cell is weighted by 1 / var_fn(p_ij) at its fitted capture fraction (IRLS: the
    weights follow the fit; normalized to mean 1 so the penalties keep their meaning); None: equal.
    ctrl: the prey whose predator-free controls may be read (None: control_access(D, idx)). basis: the
    surfaces' and the link's basis functions (6; 4 and 8 the sensitivities). embedding: "shared" or
    "separate" (the sensitivity). center: the fixed distribution u and v are centred on.
    Bank mode (A_design_v5 3.3; recovery.any_fit passes all three or none): var_fn the bank's working variance
    W; rep_prior {"nu0": nu0_C} (nu0 a positive float, or None: full pooling), the cells' variance shrinkage
    of capture_scale; score_law the bank's latent law p -> (A, L) of the frozen fitter table, used by the
    scorer (_score_law) and carrying that table (.table: slope_max, lat_var_min) and its extrapolation count
    (.extrapolated). A rep_prior or score_law without a var_fn is REFUSED (a fit without a variance function,
    e.g. a numerical case, can never carry a variance model)."""
    import recovery as rec          # (the data layout and the additive start)
    if own_layer:
        raise ValueError("option (b) is dropped (q30b): the Level-1 map is placed on the common cross-world "
                         "support alone; within-world edges are the cross-fitted stage 2 (own_world_stage2)")
    if var_fn is None and (rep_prior is not None or score_law is not None):
        raise ValueError("a rep_prior or score_law without a var_fn: refused (a fit without a variance function "
                         "can never carry a variance model; A_design_v5 3.3)")
    if rep_prior is not None:
        if not isinstance(rep_prior, dict) or set(rep_prior) != {"nu0"}:
            raise ValueError(f"rep_prior {rep_prior!r}: exactly {{'nu0': nu0}} (A_design_v5 3.2)")
        rep_prior = {"nu0": _check_nu0(rep_prior["nu0"])}
    if score_law is not None and not (callable(score_law) and hasattr(score_law, "extrapolated")
                                      and all(hasattr(getattr(score_law, "table", None), k)
                                              for k in ("slope_max", "lat_var_min"))):
        raise ValueError("score_law: a callable p -> (A, L) carrying its frozen fitter table (.table with slope_max "
                         "and lat_var_min) and its extrapolation count (.extrapolated), as obslaw.ScoreLaw")
    if start not in ("warm", "cold"):
        raise ValueError(f"start {start!r}: warm or cold")
    if basis not in BASES:
        raise ValueError(f"basis {basis}: one of {BASES}")
    if embedding not in EMBEDDINGS:
        raise ValueError(f"embedding {embedding!r}: one of {EMBEDDINGS}")
    rng = np.random.default_rng(seed)
    idx = np.asarray(idx)
    qi, pj = D.qi[idx], D.pj[idx]
    n = len(idx)
    z = data["zbar"][idx]
    R = data["z"].shape[1]
    noiseC = max(_noise(data["z"][idx]), 1e-6)
    surv = survival and "sbar" in data
    sep = surv and embedding == "separate" and rank > 0
    ctrl = control_access(D, idx) if ctrl is None else np.asarray(ctrl, bool)
    if ctrl.shape != (D.nQ,):
        raise ValueError("ctrl: one flag per prey node")
    s0 = np.zeros(D.nQ)
    s = np.zeros(n)
    nS = n0 = None
    cbar, tau2 = 0.0, 1.0
    zrep = np.var(data["z"][idx], axis=1, ddof=1) if R > 1 else np.zeros(n)
    if surv:
        s = data["sbar"][idx]
        nS = max(_noise(data["s"][idx]), 1e-6)     # (the exposed survival rows' replicate-mean variance)
        if ctrl.any():
            raw = data["s0"][ctrl]                  # (only the accessible controls are ever read)
            n0 = max(_noise(raw), 1e-6)
            s0[ctrl] = raw.mean(axis=1)
            cbar = float(s0[ctrl].mean())
            tau2 = max(float(s0[ctrl].var()) - n0, C_PRIOR_FLOOR) if ctrl.sum() > 1 else 1.0
        else:
            cbar = float(np.mean(s))
    c0 = np.where(ctrl, s0, cbar)
    nu0 = rep_prior and rep_prior["nu0"]
    ext0 = getattr(var_fn, "extrapolated", None)     # (a bank working variance counts its table extrapolations)

    def scales(zfit):
        """The capture weights at the fitted capture fraction, their absolute unit (capture_scale) and the
        other rows' weights IN THAT UNIT (an absolute precision is weight / unit for every row: Codex #66 r2
        P2-1): exposed survival unit / nS, a control unit / n0, the c_i prior unit / tau_c^2."""
        V = None if var_fn is None else var_fn(np.clip(_sig(zfit), 1e-4, 1.0 - 1e-4))
        w, unit, ph = capture_scale(V, zrep, R, nu0=nu0)
        if not surv:
            return w, unit, ph, 0.0, 0.0, 0.0
        return w, unit, ph, unit / nS, (unit / n0 if n0 else 0.0), unit / tau2
    wC, unit, phi, wS, wS0, wC0 = scales(z)
    # the additive starts (rank 0, identity link) for each head's own ordered qualities (v4 §6.2:
    # head-specific ordered terms; only the interaction embedding u, v is shared)
    if init is None:
        m0 = rec.fit(D, idx, data["zbar"], 0, 0.0, False, 30, seed)
        a, b = m0["a"].copy(), m0["b"].copy()
        aS, bS = -a, -b
        if surv:     # (negated: survival is nonincreasing in a predator's, nondecreasing in a prey's quality)
            m1 = rec.fit(D, idx, data["sbar"] - c0[D.qi], 0, 0.0, False, 30, seed)
            aS, bS = -m1["a"], -m1["b"]
    else:
        a, b, aS, bS = (init[k].copy() for k in ("a", "b", "aS", "bS"))
    on_q = np.bincount(qi, minlength=D.nQ) > 0
    on_p = np.bincount(pj, minlength=D.nP) > 0

    def std(x, on):
        return (x - x[on].mean()) / max(x[on].std(), 1e-9)

    def standardize():
        nonlocal a, b, aS, bS
        a, b, aS, bS = std(a, on_p), std(b, on_q), std(aS, on_p), std(bS, on_q)
    standardize()
    surfC = Surface(_knots(a[on_p], basis), _knots(b[on_q], basis), ("inc", "dec"))
    surfS = Surface(_knots(aS[on_p], basis), _knots(bS[on_q], basis), ("dec", "inc"))
    lk = init["link"].copy() if (init is not None and init.get("link") is not None and link) else Link()
    lk.statuses = []                         # (this fit's solves only)
    SQ, SP = center_sets(D, on_q, on_p, center)
    ones, zero = np.ones(n), np.zeros(n)
    uS, vS = np.zeros((D.nQ, 0)), np.zeros((D.nP, 0))
    if init is not None:
        u, v = init["u"].copy(), init["v"].copy()
        if sep:
            ok = init.get("uS") is not None and init["uS"].shape[1] == rank
            uS = init["uS"].copy() if ok else np.zeros((D.nQ, rank))
            vS = init["vS"].copy() if ok else np.zeros((D.nP, rank))
    elif start == "warm" and rank:
        surfC.fit(a[pj], b[qi], z, wC)
        u, v = svd_start(qi, pj, z - surfC.value(a[pj], b[qi]), D.nQ, D.nP, rank, seed)
        if sep:
            surfS.fit(aS[pj], bS[qi], s - c0[qi], wS * ones)
            uS, vS = svd_start(qi, pj, s - c0[qi] - surfS.value(aS[pj], bS[qi]), D.nQ, D.nP, rank, seed + 1)
    else:
        u, v = rng.normal(0.0, 0.1, (D.nQ, rank)), rng.normal(0.0, 0.1, (D.nP, rank))
        if sep:
            uS, vS = rng.normal(0.0, 0.1, (D.nQ, rank)), rng.normal(0.0, 0.1, (D.nP, rank))

    def centred(x, S):
        return x - x[S].mean(axis=0) if (x.shape[1] and len(S)) else x
    u, v, uS, vS = centred(u, SQ), centred(v, SP), centred(uS, SQ), centred(vS, SP)
    DS = (init["DS"].copy() if (init is not None and not sep and np.shape(init.get("DS")) == (rank, rank))
          else np.zeros((rank, rank)))
    c = init["c"].copy() if (init is not None and init.get("c") is not None) else c0.copy()
    ne = rank * (2 if sep else 1)
    ridge = np.array([lam_ab, lam_ab] + [lam] * ne)
    ucols = np.arange(2, 2 + ne)
    zr = np.zeros((n, rank))

    def inter_s():
        if not rank:
            return zero
        if sep:
            return (uS[qi] * vS[pj]).sum(axis=1)
        return (u[qi] * (v[pj] @ DS.T)).sum(axis=1)

    def stack_rows(node, rows):
        return (np.concatenate([node] * len(rows)), np.concatenate([r_[0] for r_ in rows]),
                np.concatenate([r_[1] for r_ in rows]), np.concatenate([r_[2] for r_ in rows]))

    for it in range(iters):
        inter = (u[qi] * v[pj]).sum(axis=1)
        # 1. the capture surface (IRLS through the link) and the link
        FC = surfC.value(a[pj], b[qi])
        eta = FC + inter
        g, dg = lk.G(eta), lk.dG(eta)
        wC, unit, phi, wS, wS0, wC0 = scales(g)
        work = eta + (z - g) / np.maximum(dg, 1e-6)
        surfC.fit(a[pj], b[qi], work - inter, wC * dg ** 2)
        FC = surfC.value(a[pj], b[qi])
        if link and it % LINK_EVERY == LINK_EVERY - 1:
            lk = update_link(lk, FC + inter, z, wC, basis)
        # 2. the survival head: its surface, the predator-free baselines c_i, D_S
        if surv:
            iS = inter_s()
            surfS.fit(aS[pj], bS[qi], s - c[qi] - iS, wS * ones)
            FS = surfS.value(aS[pj], bS[qi])
            num = wS0 * s0 + wC0 * cbar + np.bincount(qi, weights=wS * (s - FS - iS), minlength=D.nQ)
            den = wS0 * ctrl + wC0 + wS * np.bincount(qi, minlength=D.nQ)
            c = num / den
            if rank and not sep:
                Xd = (u[qi][:, :, None] * v[pj][:, None, :]).reshape(n, rank * rank)
                A = Xd.T @ Xd + 1e-6 * np.eye(rank * rank)
                DS = np.linalg.solve(A, Xd.T @ (s - c[qi] - FS)).reshape(rank, rank)
        # 3. prey nodes (b_i, b^S_i, u_i [, u^S_i]), then predator nodes at the updated prey nodes: damped
        #    Gauss-Newton over both heads' rows (each head moves only its own quality; u, v see both)
        FC, FCa, FCb = surfC.value(a[pj], b[qi], grads=True)
        eta = FC + inter
        g, dg = lk.G(eta), lk.dG(eta)
        rows = [(np.column_stack([dg * FCb, zero, dg[:, None] * v[pj]] + ([zr] if sep else [])),
                 z - g + dg * (FCb * b[qi] + inter), wC)]
        if surv:
            FS, FSa, FSb = surfS.value(aS[pj], bS[qi], grads=True)
            emb = [zr, vS[pj]] if sep else [v[pj] @ DS.T if rank else zr]
            rows.append((np.column_stack([zero, FSb] + emb), s - c[qi] - FS + FSb * bS[qi], wS * ones))
        th = _solve_nodes(*stack_rows(qi, rows), D.nQ, ridge, np.stack([b, bS], axis=1), 1.0, center=(SQ, ucols))
        b, bS, u = th[:, 0], th[:, 1], th[:, 2:2 + rank]
        if sep:
            uS = th[:, 2 + rank:]
        inter = (u[qi] * v[pj]).sum(axis=1)
        FC, FCa, FCb = surfC.value(a[pj], b[qi], grads=True)
        eta = FC + inter
        g, dg = lk.G(eta), lk.dG(eta)
        rows = [(np.column_stack([dg * FCa, zero, dg[:, None] * u[qi]] + ([zr] if sep else [])),
                 z - g + dg * (FCa * a[pj] + inter), wC)]
        if surv:
            FS, FSa, FSb = surfS.value(aS[pj], bS[qi], grads=True)
            emb = [zr, uS[qi]] if sep else [u[qi] @ DS if rank else zr]
            rows.append((np.column_stack([zero, FSa] + emb), s - c[qi] - FS + FSa * aS[pj], wS * ones))
        th = _solve_nodes(*stack_rows(pj, rows), D.nP, ridge, np.stack([a, aS], axis=1), 1.0, center=(SP, ucols))
        a, aS, v = th[:, 0], th[:, 1], th[:, 2:2 + rank]
        if sep:
            vS = th[:, 2 + rank:]
        standardize()
    # the penalized training objective at the end (the criterion between starts: never validation)
    inter = (u[qi] * v[pj]).sum(axis=1)
    FC, FCa, FCb = surfC.value(a[pj], b[qi], grads=True)
    eta = FC + inter
    g, dg = lk.G(eta), lk.dG(eta)
    wC, unit, phi, wS, wS0, wC0 = scales(g)
    obj = float(np.sum(wC * (z - g) ** 2)) + surfC.pen + lk.pen
    iS = inter_s()
    FSa = FSb = zero
    if surv:
        FS, FSa, FSb = surfS.value(aS[pj], bS[qi], grads=True)
        obj += float(wS * np.sum((s - c[qi] - FS - iS) ** 2) + wS0 * np.sum(((s0 - c) ** 2)[ctrl])
                     + wC0 * np.sum((c - cbar) ** 2)) + surfS.pen
    obj += lam * float(np.sum(u ** 2) + np.sum(v ** 2) + np.sum(uS ** 2) + np.sum(vS ** 2)) + lam_ab * float(
        np.sum(a ** 2) + np.sum(b ** 2) + np.sum(aS ** 2) + np.sum(bS ** 2))
    # the predictive model: the replicate dispersion (in scales), the pair residuals ON THE PREDICTOR SCALE
    # (v4 §6.2: delta_ij inside the link; Codex #66 r2 P2-2), the node blocks' covariances in the same unit
    repv = unit / wC                                  # (each cell's replicate-mean variance: phi V / R)
    dgc = np.maximum(dg, 1e-6)
    s2e = repv / dgc ** 2                             # (... on the predictor scale)
    reta = (z - g) / dgc                              # (the working residual on the predictor scale)
    pair_var = pair_variance(reta, s2e)
    delta = pair_var / (pair_var + s2e) * reta        # (the shrunk pair residuals of the fitting pairs: BLUPs)
    qrows = [(np.column_stack([zero, dg * FCb, zero, dg[:, None] * v[pj]] + ([zr] if sep else [])), wC)]
    prows = [(np.column_stack([dg * FCa, zero, dg[:, None] * u[qi]] + ([zr] if sep else [])), wC)]
    if surv:
        emb_q = [zr, vS[pj]] if sep else [v[pj] @ DS.T if rank else zr]
        emb_p = [zr, uS[qi]] if sep else [u[qi] @ DS if rank else zr]
        qrows.append((np.column_stack([ones, zero, FSb] + emb_q), wS * ones))
        prows.append((np.column_stack([zero, FSa] + emb_p), wS * ones))
    dq_ = np.zeros((D.nQ, 3 + ne))
    dq_[:, 0] = (wS0 * ctrl + wC0) if surv else 1.0
    dq_[:, 1:3] = lam_ab
    dq_[:, 3:] = max(lam, 1e-9)
    dp_ = np.array([lam_ab, lam_ab] + [max(lam, 1e-9)] * ne)
    covQ = _block_cov(np.concatenate([qi] * len(qrows)), np.concatenate([r_[0] for r_ in qrows]),
                      np.concatenate([r_[1] for r_ in qrows]), dq_, D.nQ, unit)
    covP = _block_cov(np.concatenate([pj] * len(prows)), np.concatenate([r_[0] for r_ in prows]),
                      np.concatenate([r_[1] for r_ in prows]), dp_, D.nP, unit)
    return {"a": a, "b": b, "aS": aS, "bS": bS, "u": u, "v": v, "uS": uS if sep else None, "vS": vS if sep else None,
            "DS": DS, "c": c, "surfC": surfC, "surfS": surfS, "link": lk,
            "h": np.zeros(D.nbins), "hw": np.zeros((len(D.worlds), D.nbins)), "own": False, "rank": rank,
            "objective": obj, "start": "init" if init is not None else start, "weighted": var_fn is not None,
            "var_fn": var_fn, "R": R, "noise_C": noiseC, "phi": phi, "unit": unit, "pair_var": pair_var,
            "delta": delta, "fit_idx": idx, "covQ": covQ, "covP": covP, "survival": surv, "basis": basis,
            "embedding": embedding, "weights": {"survival": wS, "control": wS0, "c_prior": wC0},
            "center": {"distribution": center, "prey": int(len(SQ)), "pred": int(len(SP))},
            "center_nodes": {"prey": SQ, "pred": SP},
            "controls": {"accessible": int(ctrl.sum()), "cbar": cbar, "prior_var": tau2},
            "qp": qp_summary(surfC.statuses + surfS.statuses + lk.statuses),
            "rep_prior": rep_prior, "score_law": score_law, "var_fn_identity": getattr(var_fn, "identity", None),
            "table_extrapolated": None if ext0 is None else int(var_fn.extrapolated - ext0)}


def fit_best(D, idx, data, rank, lam, iters=40, seed=0, starts=("warm", "cold"), **kw):
    """The registered fit: every start in `starts` (rank > 0; rank 0 has no embedding to start) and
    the one with the lower PENALIZED TRAINING objective kept (never chosen by validation) -> the fit,
    with "objectives" {start: value}."""
    if not rank or kw.get("init") is not None:
        m = fit(D, idx, data, rank, lam, False, iters, seed, start=starts[0], **kw)
        m["objectives"] = {m["start"]: m["objective"]}
        return m
    fits = {st: fit(D, idx, data, rank, lam, False, iters, seed, start=st, **kw) for st in starts}
    best = min(starts, key=lambda st: fits[st]["objective"])
    m = fits[best]
    m["objectives"] = {st: fits[st]["objective"] for st in starts}
    return m


# ------------------------------------------------------------------ predictions
def _eta(D, m, idx):
    qi, pj = D.qi[idx], D.pj[idx]
    return m["surfC"].value(m["a"][pj], m["b"][qi]) + (m["u"][qi] * m["v"][pj]).sum(axis=1)


def predict(D, m, idx, own=None):
    """The capture head's predictions (empirical-logit scale) on pairs idx; with own (a capture stage-2
    layer, own_world_stage2), its lag terms are added on the within-world pairs."""
    eta = _eta(D, m, idx)
    if own is not None:
        eta = eta + _own_terms(D, own, idx)
    return m["link"].G(eta)


def pred_eta(D, m, idx, own=None):
    """The capture predictor of pairs idx ON ITS OWN SCALE (inside the link, v4 §6.2) and its predictive
    variance there -> (eta, s2): s2 = the location's posterior variance (the node blocks' Laplace covariances,
    gradients on the predictor scale) + the pair-residual variance (an unseen pair's delta_ij integrated out)
    [+ with own, a capture stage-2 layer: its lag terms in eta and, for a world the layer never saw, the
    lag-bin deviation variance own_var]."""
    idx = np.asarray(idx)
    qi, pj = D.qi[idx], D.pj[idx]
    r = m["rank"]
    FC, FCa, FCb = m["surfC"].value(m["a"][pj], m["b"][qi], grads=True)
    eta = FC + (m["u"][qi] * m["v"][pj]).sum(axis=1)
    gq = np.zeros((len(idx), m["covQ"].shape[1]))
    gq[:, 1] = FCb
    gq[:, 3:3 + r] = m["v"][pj]
    gp = np.zeros((len(idx), m["covP"].shape[1]))
    gp[:, 0] = FCa
    gp[:, 2:2 + r] = m["u"][qi]
    s2 = (np.einsum("ni,nij,nj->n", gq, m["covQ"][qi], gq) + np.einsum("ni,nij,nj->n", gp, m["covP"][pj], gp)
          + m["pair_var"])
    if own is not None:
        if own.get("head") != "capture":
            raise ValueError("the capture predictor takes a capture stage-2 layer")
        eta = eta + _own_terms(D, own, idx)
        s2 = s2 + own_var(D, own, idx)
    return eta, np.maximum(s2, 0.0)


def _rep_var(m, loc):
    """phi V(p) at the predicted capture fraction: one fresh replicate's row, column and cell variance."""
    vf = m.get("var_fn")
    loc = np.asarray(loc, float)
    if vf is None:
        return np.full(loc.shape, float(m["phi"]))
    return m["phi"] * np.maximum(vf(np.clip(_sig(loc), 1e-4, 1 - 1e-4)), 1e-8)


def _score_law(m, loc):
    """The latent law of one fresh replicate at predicted empirical logits loc -> (location, variance), shaped like
    loc. score_law None: (loc, _rep_var(m, loc)), exactly today's scorer (planning). Bank mode (A_design_v5 3.3,
    PC-17): (A(mu^), phi L(mu^)) with mu^ = m_z^-1(loc) from the frozen fitter table: the bank's latent law at the
    predicted mean (location solved at gamma = 1; phi scales the variance only). Its argument p is clipped as
    _rep_var's; the clip cannot change a value (the table's m_z lies inside the empirical-logit range +-6.48,
    inside the clip's +-9.21, and beyond m_z the table holds its end values)."""
    sl = m.get("score_law")
    if sl is None:
        return loc, _rep_var(m, loc)
    A, L = sl(np.clip(_sig(loc), 1e-4, 1 - 1e-4))
    return A, m["phi"] * L


def _score_z(g):
    """The z at which the score law evaluates predicted empirical logits g: logit of _score_law's clipped p."""
    p = np.clip(_sig(g), 1e-4, 1 - 1e-4)
    return np.log(p) - np.log1p(-p)


def _max_slope_each(lk, lo_, hi_):
    """Link.max_slope over [lo_e, hi_e] for each pair (the same conservative bound on G', vectorized)."""
    lo_, hi_ = np.asarray(lo_, float), np.asarray(hi_, float)
    if lk.knots is None:
        sl = np.ones(lo_.shape)
    else:
        kn, th = lk.knots, lk.theta
        slopes = np.diff(th) / np.diff(kn)
        a = np.clip(np.searchsorted(kn, lo_, side="right") - 1, 0, len(kn) - 2)
        b = np.clip(np.searchsorted(kn, hi_, side="right") - 1, 0, len(kn) - 2)
        j = np.arange(len(slopes))
        sl = np.where((j >= a[..., None]) & (j <= b[..., None]), slopes, -np.inf).max(axis=-1)
    return sl if (lk.lo == 0.0 and lk.hi == 1.0) else sl / (lk.hi - lk.lo)


def _score_need(lk, m, eta, sd, span):
    """The node requirement of the grid rule with the score law (A_design_v5 3.3, PC-24) on +-TRAP_SD x span
    prior SDs: h_e = min(sd_e, TRAP_H s_lat / (g_max,e max(H^max_e, 1e-12))), where Delta_e = TRAP_SD span_e sd_e,
    H^max_e is the exact range maximum of the table's segment slopes |kappa_j| over the image [G(eta_e - Delta_e),
    G(eta_e + Delta_e)] (G increasing; 0 wholly in the constant extrapolation), g_max,e = Link.max_slope over
    [eta_e - Delta_e, eta_e + Delta_e] and s_lat = sqrt(phi min_j L_j) (the latent SD floor). -> ceil(2 TRAP_SD
    span_e sd_e / h_e) + 1 per pair; recomputed by the caller on every range extension."""
    tab = m["score_law"].table
    delta = TRAP_SD * span * sd
    lo_, hi_ = eta - delta, eta + delta
    hmax = tab.slope_max(_score_z(lk.G(lo_)), _score_z(lk.G(hi_)))
    gmax = np.maximum(_max_slope_each(lk, lo_, hi_), 1e-12)
    slat = math.sqrt(max(float(m["phi"]) * float(tab.lat_var_min), 1e-300))
    h = np.minimum(sd, TRAP_H * slat / (gmax * np.maximum(hmax, 1e-12)))
    return np.ceil(2 * TRAP_SD * span * sd / np.maximum(h, 1e-300)) + 1


def pred_var(D, m, idx, own=None):
    """The capture head's predictive MOMENTS for one fresh replicate observation of each pair of idx, to first
    order (the Gaussian diagnostic's; the registered score integrates exactly, pred_count_lpd) -> (location
    G(eta), latent variance phi V(p) + G'(eta)^2 s2), s2 from pred_eta: the predictor-scale variance enters
    through the link, so its contribution varies with the location."""
    eta, s2 = pred_eta(D, m, idx, own)
    lk = m["link"]
    loc, dg = lk.G(eta), lk.dG(eta)
    return loc, np.maximum(_rep_var(m, loc) + dg ** 2 * s2, 1e-8)


TRAP_H = 0.25                            # (the grid step, in units of the narrowest replicate SD / steepest slope)
TRAP_SD = 7.0                            # (the grid covers +-TRAP_SD prior SDs)
TRAP_KS = (15, 23, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193,
           12289, 16385, 24577, 32769, 49153, 65537, 98305, 131073, 196609, 262145)   # (grid sizes: bucketed)
TRAP_CELLS = 1_000_000                   # (pairs x replicates x nodes per vectorized chunk)
TRAP_TOL = 1e-3                          # (the a-posteriori check, log units: full grid vs every other node)
TRAP_SPAN_MAX = 8                        # (the range may double up to +-TRAP_SD x 8 = +-56 prior SDs)
TRAP_EDGE = math.log(1e-10)              # (an end node's share of the integral above this: the range is extended)
VMIN_GRID = np.linspace(-20.0, 20.0, 20001)    # (the logit grid on which the variance function's minimum is taken)
TRAP_TAIL = 1e-4                         # (bank mode: the omitted prior mass 2 PhiBar(b) <= this share of the integral)
_TAIL_SWITCH = 25.0                      # (_log_2sf: math.erfc below, Laplace's continued fraction at and above)
_TAIL_CF_TERMS = 60


def _log_2sf(b):
    """log(2 PhiBar(b)) for a scalar b >= 0, PhiBar the standard normal upper tail, in log space so that it never
    underflows: log erfc(b / sqrt 2) below 25 and, at and above, log 2 - b^2/2 - log sqrt(2 pi) - log(b + 1/(b + 2/(b +
    3/(b + ...)))) (Laplace's continued fraction, 60 terms). The T6-10 reference's method, copied here (the reference
    shares no code with the scorer; A_design_v5 clarification 2, D1)."""
    b = float(b)
    if b < _TAIL_SWITCH:
        return math.log(math.erfc(b / math.sqrt(2.0)))
    t = 0.0
    for k in range(_TAIL_CF_TERMS, 0, -1):
        t = k / (b + t)
    return math.log(2.0) - 0.5 * b * b - 0.5 * math.log(2.0 * math.pi) - math.log(b + t)


def _tail_ok(full, span):
    """The bank-mode tail bound of a grid pass on +-b = TRAP_SD x span prior SDs (A_design_v5 clarification 2, D1),
    per pair: for EVERY replicate, log(2 PhiBar(b)) <= log(TRAP_TAIL) + log I^, where log I^ = full + log(1 - 2
    PhiBar(b)) is the pass's estimate (full: Gaussian weights normalized over the grid) converted to the unnormalized
    integral over [-b, b]. Rigorous because the count probability is <= 1: the omitted part of the integral is at most
    2 PhiBar(b), so the omitted fraction is at most TRAP_TAIL (the log score low by at most log(1 + TRAP_TAIL))."""
    lt = _log_2sf(TRAP_SD * span)
    return np.all(lt <= math.log(TRAP_TAIL) + (full + math.log1p(-math.exp(lt))), axis=1)


def _logsumexp(a, axis):
    mx = np.max(a, axis=axis, keepdims=True)
    mx = np.where(np.isfinite(mx), mx, 0.0)
    with np.errstate(divide="ignore"):
        return np.squeeze(mx, axis=axis) + np.log(np.sum(np.exp(a - mx), axis=axis))


def _grid_pass(lk, m, cnt, eta, sd, N, K, span):
    """The e-order trapezoid, in log space, on K nodes over +-TRAP_SD x span prior SDs (span per pair), the same
    on every other node (the check), and the larger end node's log share of the integral (the range check) ->
    (log P, log P on the half grid, edge share), pairs x replicates. The integrand is the registered one at every
    node: the bounded count probability with the replicate variance phi V(G(eta + e)) at that node (bank mode:
    the score law's latent location and variance at that node, _score_law)."""
    x = np.linspace(-1.0, 1.0, K)[None, :] * (TRAP_SD * span)[:, None]                      # (pairs x nodes, SDs)
    lw = -0.5 * x * x
    lwh = lw[:, ::2] - _logsumexp(lw[:, ::2], 1)[:, None]
    lw = lw - _logsumexp(lw, 1)[:, None]
    loc = lk.G(eta[:, None] + sd[:, None] * x)
    sloc, svar = _score_law(m, loc)
    lp = _interval_logp(cnt[:, :, None], N, sloc[:, None, :], svar[:, None, :])
    terms = lp + lw[:, None, :]
    full = _logsumexp(terms, 2)
    with np.errstate(invalid="ignore"):
        edge = np.maximum(terms[..., 0], terms[..., -1]) - full
    return full, _logsumexp(lp[..., ::2] + lwh[:, None, :], 2), edge


def pred_count_lpd(D, m, idx, cnt, N, own=None, info=None):
    """THE registered score (v4 §7.6) of the capture head on pairs idx: the capture-count log predictive
    density per replicate observation, with the predictor-scale uncertainty (pred_eta: the posterior variance
    of eta and the pair residual delta_ij, both INSIDE the link) integrated through the link:
        P(K = k) = E_e[P(k | G(eta + e), phi V(G(eta + e)))],  e ~ N(0, s2),
    each P from Annex H.9.2's bounded model with the fresh replicate's variance (count_logp). Per observation
    (the marginal score: the mixture is not shared across a pair's replicates). -> one value per pair.
    THE INTEGRAL, by case (Codex #66 r3 P2-1, r4 P2-1/2: never silently capped, never a frozen variance,
    never a silent non-finite value):
      - s2 = 0: the plain density;
      - the identity link with a constant replicate variance (no var_fn): EXACT, Y ~ N(eta, phi + s2);
      - otherwise the e-order trapezoid IN LOG SPACE with the registered integrand at every node (the bounded
        count probability at the replicate variance phi V(G(eta + e)) of that node; the far tails of the
        interval probability are log-space continued fractions, so a count beyond the link's reach is a finite,
        very negative log probability). The grid covers +-TRAP_SD prior SDs; its step is at most one SD and at
        most TRAP_H x the narrowest replicate SD (the variance function's minimum on VMIN_GRID) / a
        CONSERVATIVE bound on the link's slope over the range (Link.max_slope), on the smallest of TRAP_KS
        (15 .. 262,145 nodes) that achieves it. Every observation is CHECKED a posteriori:
          * resolution: against the same grid's every other node; above TRAP_TOL its pair moves to the next grid;
          * range: if an end node carries more than 1e-10 of the integral (the integrand still rises at the edge,
            e.g. a count beyond the link's asymptote), the pair's range doubles, up to +-56 SDs;
        a pair failing a check on the largest grid or range keeps that value and is counted as grid_unresolved
        (a finite but UNRESOLVED score: reported, never hidden, and the callers' comparisons (recovery.py) refuse
        to decide on it); a pair whose rule needs more than the largest grid, in its initial range or in an
        extended one (Codex #66 r5 P2-2), is computed there, checked, and counted ONCE in beyond_rule.
      - any non-finite result is REFUSED (ValueError): it never reaches a model comparison.
    info (a dict): the counts per case are added to it (pairs, plain, exact, grid, refined, extended,
    beyond_rule, grid_unresolved) with the largest accepted check difference (max_check).
    BANK MODE (m["score_law"] set; A_design_v5 3.3, PC-17, PC-24): every node's latent law is the score law's,
    _score_law (the plain case likewise); the exact case is never reached (a score law needs a var_fn: refused
    otherwise); the step accounts for the composed location H(G(eta)), H = A piecewise linear with segment slopes
    kappa_j: h_e = min(sd_e, TRAP_H s_lat / (g_max,e max(H^max_e, 1e-12))) per pair (_score_need), recomputed on
    every range extension with the node requirement ceil(2 TRAP_SD span_e sd_e / h_e) + 1; a pass is
    RANGE-ADEQUATE only if the end-node check AND the tail bound hold for every replicate (_tail_ok: log(2
    PhiBar(b)) <= log(TRAP_TAIL) + log I^ on +-b = TRAP_SD span prior SDs; A_design_v5 clarification 2, D1: the
    end-node share alone cannot see a larger mode beyond the range), and either failure extends the range exactly
    as the end-node check does (recomputed requirement, counted in extended; still inadequate at the cap: kept and
    counted in grid_unresolved); everything else (the buckets, the resolution check, beyond_rule, grid_unresolved,
    the refusal) is the rule above. info also gains table_extrapolated: the score law's evaluations outside its
    table in this call. score_law unset: this function is unchanged (main's rule and integrand, byte for byte; no
    tail bound)."""
    eta, s2 = pred_eta(D, m, idx, own)
    lk = m["link"]
    sl = m.get("score_law")
    if sl is not None and m.get("var_fn") is None:
        raise ValueError("pred_count_lpd: a score law without a var_fn (refused: A_design_v5 3.3)")
    ext0 = None if sl is None else sl.extrapolated
    cnt = np.asarray(cnt)
    out = np.empty(len(eta))
    sd = np.sqrt(s2)
    st = {"pairs": int(len(eta)), "plain": 0, "exact": 0, "grid": 0, "refined": 0, "extended": 0, "beyond_rule": 0,
          "grid_unresolved": 0, "max_check": 0.0}
    plain = sd <= 1e-9
    if plain.any():
        g0 = lk.G(eta[plain])
        out[plain] = count_lpd(cnt[plain], N, *_score_law(m, g0))
        st["plain"] = int(plain.sum())
    q = np.flatnonzero(~plain)
    if len(q) and lk.identity() and m.get("var_fn") is None:
        out[q] = count_lpd(cnt[q], N, eta[q], m["phi"] + s2[q])
        st["exact"] = int(len(q))
    elif len(q):
        R = cnt.shape[1]
        if sl is None:
            lo_, hi_ = float((eta[q] - TRAP_SD * sd[q]).min()), float((eta[q] + TRAP_SD * sd[q]).max())
            gmax = max(lk.max_slope(lo_, hi_), 1e-12)
            smin = math.sqrt(max(float(_rep_var(m, VMIN_GRID).min()), 1e-300))
            h = np.minimum(sd[q], TRAP_H * smin / gmax)
            need0 = np.ceil(2 * TRAP_SD * sd[q] / np.maximum(h, 1e-300)) + 1          # (nodes at span 1)
        else:
            need0 = _score_need(lk, m, eta[q], sd[q], 1.0)                            # (the v3/v5 rule, span 1)
        top = len(TRAP_KS) - 1
        bucket = np.searchsorted(TRAP_KS, need0)
        beyond = np.zeros(len(eta), bool)                         # (pairs whose rule exceeded the largest grid, once)
        beyond[q[bucket > top]] = True
        cur, cb, cs, n0 = q, np.minimum(bucket, top), np.ones(len(q)), need0
        while len(cur):
            nxt = []
            for b, s_ in sorted(set(zip(cb.tolist(), cs.tolist()))):
                sel = (cb == b) & (cs == s_)
                rows, need_r = cur[sel], n0[sel]
                Kb = TRAP_KS[int(b)]
                step = max(1, TRAP_CELLS // (R * Kb))
                for k0 in range(0, len(rows), step):
                    r_, nr_ = rows[k0:k0 + step], need_r[k0:k0 + step]
                    full, half, edge = _grid_pass(lk, m, cnt[r_], eta[r_], sd[r_], N, Kb, np.full(len(r_), s_))
                    with np.errstate(invalid="ignore"):
                        err = np.max(np.abs(full - half), axis=1)
                        res_ok = err <= TRAP_TOL                                   # (NaN: not ok)
                        range_ok = np.all(edge <= TRAP_EDGE, axis=1)               # (main's end-node check)
                        if sl is not None:            # (bank mode: and the tail bound, every replicate; clar. 2 D1)
                            range_ok &= _tail_ok(full, s_)
                    fin = np.isfinite(full).all(axis=1)
                    ok = res_ok & range_ok & fin
                    out[r_[ok]] = full[ok].mean(axis=1)
                    st["grid"] += int(ok.sum())
                    if ok.any():
                        st["max_check"] = max(st["max_check"], float(err[ok].max()))
                    for i in np.flatnonzero(~ok):
                        if fin[i] and not range_ok[i] and s_ < TRAP_SPAN_MAX:         # (extend the range)
                            s2_ = 2 * s_
                            if sl is None:
                                nb2 = max(int(b), int(np.searchsorted(TRAP_KS, nr_[i] * s2_)))
                            else:                     # (g_max, H^max and h recomputed on the extended range)
                                ri = r_[i:i + 1]
                                nb2 = max(int(b), int(np.searchsorted(TRAP_KS, _score_need(lk, m, eta[ri], sd[ri],
                                                                                           s2_)[0])))
                            if nb2 > top:                                     # (the extended range's rule is beyond
                                beyond[r_[i]] = True                          #  the cap: counted, Codex #66 r5 P2-2)
                            nxt.append((r_[i], min(nb2, top), s2_, nr_[i]))
                            st["extended"] += 1
                        elif fin[i] and not res_ok[i] and b < top:                    # (refine the grid)
                            nxt.append((r_[i], int(b) + 1, s_, nr_[i]))
                            st["refined"] += 1
                        else:                                                        # (kept, flagged)
                            out[r_[i]] = full[i].mean()
                            st["grid_unresolved"] += 1
            cur = np.array([t[0] for t in nxt], int)
            cb = np.array([t[1] for t in nxt], int)
            cs = np.array([t[2] for t in nxt], float)
            n0 = np.array([t[3] for t in nxt], float)
        st["beyond_rule"] = int(beyond.sum())
    bad = ~np.isfinite(out)
    if bad.any():
        raise ValueError(f"pred_count_lpd: {int(bad.sum())} non-finite count scores: refused (never compared)")
    if sl is not None:
        st["table_extrapolated"] = int(sl.extrapolated - ext0)
    if info is not None:
        for k, v in st.items():
            info[k] = max(info.get(k, 0.0), v) if k == "max_check" else info.get(k, 0) + v
    return out


def count_lpd(cnt, N, loc, var):
    """count_logp's mean over replicates, per pair."""
    return count_logp(cnt, N, loc, var).mean(axis=1)


def count_logp(cnt, N, loc, var):
    """The registered capture-count log predictive density (v4 §7.6) under the bounded observation model of
    Annex H.9.2 (v4 §6.2): a replicate count k of N is a rounded latent logit-normal, K = floor(N sigma(Y) +
    1/2), Y ~ N(loc, var), so P(K = k) = P(logit((k - 1/2)/N) < Y < logit((k + 1/2)/N)), the end intervals
    open at k = 0 and k = N. It is normalized over k = 0..N and assumes no independent Bernoulli capture
    opportunities. cnt: pairs x replicates; loc, var: one per pair -> the log probability of every replicate
    observation (pairs x replicates; noisebank's tail-stable interval probabilities). The location is the map's
    predicted mean EMPIRICAL logit (what both heads are fitted to): an interior count's empirical logit lies
    in its latent interval, so the latent mean and the mean empirical logit agree up to the rounding (H.9.2's
    exact location solve, matching the expected rounded fraction, is not applied). On narrow interior
    intervals the density is the Gaussian density times the interval width, which is the same for every
    candidate model, so a score DIFFERENCE departs from the Gaussian working score's only where intervals are
    wide: low and high counts and the open ends at 0 and N."""
    return _interval_logp(cnt, N, np.asarray(loc, float)[:, None], np.asarray(var, float)[:, None])


def _interval_logp(cnt, N, loc, var):
    """log P(K = cnt) of count_logp, loc and var broadcast against cnt (pairs x replicates)."""
    import noisebank as nb
    cnt = np.asarray(cnt)
    if cnt.ndim < 2 or (cnt < 0).any() or (cnt > N).any():
        raise ValueError(f"counts: pairs x replicates in 0..{N}")
    lo, hi = nb.interval_bounds(cnt, N)
    sd = np.sqrt(np.maximum(var, 1e-12))
    return nb._log_iprob((lo - loc) / sd, (hi - loc) / sd)


def predict_survival(D, m, idx, own=None):
    """(logit S_i0, logit S_ij) of pairs idx: the predator-free baseline and the exposed survival (with own,
    a survival stage-2 layer's lag terms on the within-world pairs)."""
    qi, pj = D.qi[idx], D.pj[idx]
    if not m["rank"]:
        inter = 0.0
    elif m["embedding"] == "separate" and m.get("uS") is not None:
        inter = (m["uS"][qi] * m["vS"][pj]).sum(axis=1)
    else:
        inter = (m["u"][qi] * (m["v"][pj] @ m["DS"].T)).sum(axis=1)
    base = m["c"][qi]
    out = base + m["surfS"].value(m["aS"][pj], m["bS"][qi]) + inter
    if own is not None:
        out = out + _own_terms(D, own, idx)
    return base, out


def _gh2(mu0, mu1, v00, v01, v11, nodes=GH_NODES, chunk=20000):
    """E and SD of sigma(X1) - sigma(X0), (X0, X1) bivariate normal, by Gauss-Hermite on the Cholesky
    factor (nodes^2 points)."""
    x, w = np.polynomial.hermite_e.hermegauss(nodes)
    w = w / w.sum()
    W = w[:, None] * w[None, :]
    q, sd = np.empty(len(mu0)), np.empty(len(mu0))
    for k0 in range(0, len(mu0), chunk):
        sl = slice(k0, k0 + chunk)
        l11 = np.sqrt(np.maximum(v00[sl], 0.0))
        l21 = np.where(l11 > 0, v01[sl] / np.where(l11 > 0, l11, 1.0), 0.0)
        l22 = np.sqrt(np.maximum(v11[sl] - l21 ** 2, 0.0))
        X0 = mu0[sl, None, None] + l11[:, None, None] * x[None, :, None]
        X1 = mu1[sl, None, None] + l21[:, None, None] * x[None, :, None] + l22[:, None, None] * x[None, None, :]
        dlt = _sig(X1) - _sig(X0)
        q[sl] = (W * dlt).sum(axis=(1, 2))
        sd[sl] = np.sqrt(np.maximum((W * dlt ** 2).sum(axis=(1, 2)) - q[sl] ** 2, 0.0))
    return q, sd


def survival_posterior(D, m, idx, own=None):
    """v4 §6.2's H-Q mapping: q_ij = E[sigma(c_i + eta^S_ij) - sigma(c_i) | data] over the JOINT fitted
    distribution of (c_i, c_i + eta^S_ij): the prey block's Laplace covariance couples c_i with b^S_i and u_i
    (c_i is estimated from the controls AND the exposed rows), the predator block adds its own; the 2 x 2
    covariance is propagated (never independent marginal error bars). With own (a SURVIVAL stage-2 layer):
    its lag terms enter the exposed logit, and for a world the layer never saw its lag-bin deviation variance
    (own_var) is added to the exposed logit's variance (the baseline c_i is unaffected) -> {"q" (the
    posterior mean), "q_sd", "q_plugin" (sigma at the point estimates), "logit0", "logit1", "var0", "cov01",
    "var1"}."""
    if not m.get("survival"):
        raise ValueError("this fit has no survival head")
    if own is not None and own.get("head") != "survival":
        raise ValueError("survival_posterior takes a survival stage-2 layer")
    idx = np.asarray(idx)
    qi, pj = D.qi[idx], D.pj[idx]
    r = m["rank"]
    sep = m["embedding"] == "separate" and r > 0
    x0, x1 = predict_survival(D, m, idx, own)
    _, FSa, FSb = m["surfS"].value(m["aS"][pj], m["bS"][qi], grads=True)
    n = len(idx)
    gq = np.zeros((n, m["covQ"].shape[1]))
    gq[:, 0] = 1.0
    gq[:, 2] = FSb
    gp = np.zeros((n, m["covP"].shape[1]))
    gp[:, 1] = FSa
    if r and sep:
        gq[:, 3 + r:] = m["vS"][pj]
        gp[:, 2 + r:] = m["uS"][qi]
    elif r:
        gq[:, 3:3 + r] = m["v"][pj] @ m["DS"].T
        gp[:, 2:2 + r] = m["u"][qi] @ m["DS"]
    CQ, CP = m["covQ"][qi], m["covP"][pj]
    v00 = CQ[:, 0, 0]
    v01 = np.einsum("nj,nj->n", CQ[:, 0, :], gq)
    v11 = np.einsum("ni,nij,nj->n", gq, CQ, gq) + np.einsum("ni,nij,nj->n", gp, CP, gp)
    if own is not None:
        v11 = v11 + own_var(D, own, idx)
    q, sd = _gh2(x0, x1, v00, v01, v11)
    return {"q": q, "q_sd": sd, "q_plugin": _sig(x1) - _sig(x0), "logit0": x0, "logit1": x1,
            "var0": v00, "cov01": v01, "var1": v11}


def survival_penalty(D, m, idx):
    """q_ij on H-Q's probability scale: the posterior expectation under the joint uncertainty
    (survival_posterior's "q")."""
    return survival_posterior(D, m, idx)["q"]


def ladder(D, m, guild="prey", chunk=2000):
    """Ordered performance against the FIXED opponent distribution the fit is centred on (v4 §6.3: uniform
    over the opposite guild's external references; with center="train_c", its training-C snapshots): for
    every node of `guild`, the mean capture-head predictor over that distribution (the interaction averages
    to zero there under the centring: the ordered part) and the mean predicted capture fraction ->
    {"eta": ..., "capture": ..., "opponents": n} (one value per node)."""
    opp = m["center_nodes"]["pred" if guild == "prey" else "prey"]
    nn = D.nQ if guild == "prey" else D.nP
    eta_m, cap_m = np.full(nn, np.nan), np.full(nn, np.nan)
    if not len(opp):
        return {"eta": eta_m, "capture": cap_m, "opponents": 0}
    for k0 in range(0, nn, chunk):
        me = np.arange(k0, min(nn, k0 + chunk))
        mi, oj = np.repeat(me, len(opp)), np.tile(opp, len(me))
        if guild == "prey":
            eta = m["surfC"].value(m["a"][oj], m["b"][mi]) + (m["u"][mi] * m["v"][oj]).sum(axis=1)
        else:
            eta = m["surfC"].value(m["a"][mi], m["b"][oj]) + (m["u"][oj] * m["v"][mi]).sum(axis=1)
        eta_m[me] = eta.reshape(len(me), len(opp)).mean(axis=1)
        cap_m[me] = _sig(m["link"].G(eta)).reshape(len(me), len(opp)).mean(axis=1)
    return {"eta": eta_m, "capture": cap_m, "opponents": int(len(opp))}


# ------------------------------------------------------------------ stage 2: the own-world layer
def _own_terms(D, own, idx):
    idx = np.asarray(idx)
    wi = D.within[idx]
    out = np.zeros(len(idx))
    lb, lw = D.lagbin[idx][wi], D.ownw[idx][wi]
    out[wi] = own["h"][lb] + own["hw"][lw, lb]
    return out


def own_world_stage2(D, m, data, idx_w, folds=5, lam_world=10.0, seed=0, sweeps=10, head="capture"):
    """STAGE 2, the own-world layer (q30b: option (b) dropped; the Level-1 map m is placed on the
    common cross-world support alone), for either head (v4 §6.2: the survival predictor has its own
    own-world terms). On the within-world pairs idx_w, the working residuals of m -- capture: on its link
    scale, r = (z - G(eta)) / G'(eta) with weights G'(eta)^2; survival: the exposed empirical logit minus
    c_i + eta^S, weight 1 -- are fitted by a lag-bin curve h(lag) shared by the worlds plus a per-world
    deviation h_w(lag) shrunk by lam_world (backfitting, `sweeps` passes). Cross-fitted: the pairs are dealt
    into `folds` folds (a seeded permutation); each fold's layer is predicted by the layer fitted on the
    others -> {"h", "hw" (fitted on every pair), "oof" (the out-of-fold layer at idx_w), "fold", "world_var"
    (world_deviation_var: the variance of the LAG-DEPENDENT world deviations, one per lag bin; an UNSEEN
    world's deviation is integrated out with it, never estimated from its targets, v4 §6.4: own_var,
    pred_eta, pred_count_lpd, survival_posterior), "worlds" (those with pairs), ...}. m is unchanged."""
    idx_w = np.asarray(idx_w)
    if not D.within[idx_w].all():
        raise ValueError("own_world_stage2 takes within-world pairs only")
    if head == "capture":
        eta = _eta(D, m, idx_w)
        lk = m["link"]
        dg = np.maximum(lk.dG(eta), 1e-6)
        r = (data["zbar"][idx_w] - lk.G(eta)) / dg
        w = dg ** 2
    elif head == "survival":
        r = data["sbar"][idx_w] - predict_survival(D, m, idx_w)[1]
        w = np.ones(len(idx_w))
    else:
        raise ValueError(f"head {head!r}: capture or survival")
    lb, lw = D.lagbin[idx_w], D.ownw[idx_w]
    nb, nW = D.nbins, len(D.worlds)
    fold = np.random.default_rng([seed, 5]).permutation(len(idx_w)) % folds

    def layer(sel):
        h, hw = np.zeros(nb), np.zeros((nW, nb))
        b_, w_, r_, k2 = lb[sel], w[sel], r[sel], lw[sel] * nb + lb[sel]
        for _ in range(sweeps):
            h = (np.bincount(b_, weights=w_ * (r_ - hw.ravel()[k2]), minlength=nb)
                 / np.maximum(np.bincount(b_, weights=w_, minlength=nb), 1e-9))
            hw = (np.bincount(k2, weights=w_ * (r_ - h[b_]), minlength=nW * nb)
                  / (np.bincount(k2, weights=w_, minlength=nW * nb) + lam_world)).reshape(nW, nb)
        return h, hw
    oof = np.zeros(len(idx_w))
    for k in range(folds):
        h, hw = layer(fold != k)
        te = fold == k
        oof[te] = h[lb[te]] + hw[lw[te], lb[te]]
    h, hw = layer(np.ones(len(idx_w), bool))
    world_var, supported, raw = world_deviation_var(r - h[lb], lb, lw, nb)
    return {"h": h, "hw": hw, "oof": oof, "fold": fold, "folds": folds, "lam_world": lam_world, "head": head,
            "world_var": world_var, "world_var_supported": supported, "world_var_raw": raw, "worlds": np.unique(lw)}


def world_deviation_var(e, lb, lw, nb, row_var=None):
    """The between-world variance of the LAG-DEPENDENT deviations h_w(lag) (Codex #66 r2 P2-3), per lag bin b:
    e the residuals after the shared curve, cell (w, b) its mean m_wb over n_wb pairs, and
        tau^2_b = max(0, var_w(m_wb, ddof 1) - mean_w(noise_wb)),
    noise_wb the CELL's own sampling variance of its mean (Codex #66 r3 P2-3: with unequal, heteroscedastic
    cells, a pooled within-variance times mean(1 / n) is not the noise of the world means): row_var given
    (each residual's variance), sum(row_var) / n^2; otherwise the cell's own variance (ddof 1) / n, and a
    single-pair cell the bin's pooled within-cell variance. Opposite deviations at two lags (+d, -d) are seen,
    unlike in world-averaged residuals. A bin with fewer than two worlds takes the mean of the supported bins
    (0 if none) -> (tau^2 per bin, supported flags, the unfloored estimates (nan where unsupported))."""
    out = np.zeros(nb)
    raw = np.full(nb, np.nan)
    ok = np.zeros(nb, bool)
    for b in range(nb):
        sel = lb == b
        ws = np.unique(lw[sel])
        if len(ws) < 2:
            continue
        masks = [sel & (lw == x) for x in ws]
        cells = [e[mk] for mk in masks]
        mw = np.array([c.mean() for c in cells])
        nwb = np.array([len(c) for c in cells], float)
        dof = sum(len(c) - 1 for c in cells)
        pooled = sum(float(((c - c.mean()) ** 2).sum()) for c in cells) / dof if dof > 0 else 0.0
        if row_var is not None:
            noise = np.array([float(np.sum(row_var[mk])) for mk in masks]) / nwb ** 2
        else:
            noise = np.array([(float(np.var(c, ddof=1)) if len(c) > 1 else pooled) for c in cells]) / nwb
        raw[b] = float(np.var(mw, ddof=1)) - float(np.mean(noise))
        out[b] = max(0.0, raw[b])
        ok[b] = True
    if (~ok).any():
        out[~ok] = float(out[ok].mean()) if ok.any() else 0.0
    return out, ok, raw


def own_var(D, own, idx):
    """The own-world layer's integrated variance on pairs idx: the lag bin's world_var on the within-world pairs
    of a world the layer never saw (its deviation is integrated out), 0 elsewhere (a seen world's shrunk
    deviation is a plug-in)."""
    idx = np.asarray(idx)
    wi = D.within[idx]
    unseen = wi & ~np.isin(D.ownw[idx], own["worlds"])
    return np.where(unseen, own["world_var"][np.maximum(D.lagbin[idx], 0)], 0.0)

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
capture-level variance function (var_fn: in production the noise bank's), the survival rows by the
replicate noise of each head.

Fitting: alternating, from the additive fit: the capture surface (IRLS through the link), the link, the
survival surface, the c_i and D_S, then every prey node's (b_i, b^S_i, u_i) and every predator node's
(a_j, a^S_j, v_j) by damped Gauss-Newton over both heads' rows (the predator step at the updated prey
nodes), the qualities standardized over the fitting nodes; held-out populations are placed by their support
pairs alone. The embedding starts WARM (q30b: the top-r singular vectors of the degree-normalized residual
matrix of the rank-0 spline baseline; start="cold": small random normals). Every QP reports its KKT status
(m["qp"]). Level 1 is placed on the common cross-world support alone (option (b) is dropped: fit refuses
own_layer); within-world pairs get the cross-fitted STAGE-2 own-world layer for either head
(own_world_stage2: a shared lag curve plus shrunk per-world deviations; unseen worlds integrate the
deviation, world_var).

THE PREDICTIVE MODEL (v4 §6.2, §7.4, §7.6): after the fit, the node blocks' Laplace covariances (the working
model's Hessian per prey block (c_i, b_i, b^S_i, u_i) and predator block (a_j, a^S_j, v_j): block-diagonal,
conditional on the surfaces, the link and D_S), the replicate dispersion phi (within-pair replicate scatter
/ V) and the pair-residual variance (the strongly shrunk pair residuals delta_ij of the fitting pairs, their
BLUPs; an unseen pair's is integrated out). pred_var: one FRESH replicate observation has latent location
G(eta) and variance phi V(p) + pair variance + the location's posterior variance; count_lpd: the registered
capture-count log predictive density under the bounded observation model of Annex H.9.2 (a rounded latent
logit-normal: normalized over 0..B, no Bernoulli capture opportunities). survival_posterior: q_ij =
E[sigma(c_i + eta^S_ij) - sigma(c_i) | data] under the joint (c_i, exposed-logit) covariance (2-D
Gauss-Hermite), with its SD.
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

    def copy(self):
        lk = Link(self.knots, None if self.theta is None else self.theta.copy(), self.lo, self.hi)
        lk.pen, lk.status = self.pen, self.status
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
        embedding="shared", center="references"):
    """The registered map on the fitting pairs idx -> its parameters (see the module doc). start:
    "warm" (the embedding starts from svd_start on the rank-0 spline residuals) or "cold" (small
    random normals); init (a previous fit) overrides both; fit_best runs both and keeps the lower
    penalized training objective. var_fn (the registered capture-level variance function, p ->
    per-replicate variance of the empirical logit; in production from the noise bank, v4 §7.4):
    every capture cell is weighted by 1 / var_fn(p_ij) at its fitted capture fraction (IRLS: the
    weights follow the fit; normalized to mean 1 so the penalties keep their meaning); None: equal.
    ctrl: the prey whose predator-free controls may be read (None: control_access(D, idx)). basis: the
    surfaces' and the link's basis functions (6; 4 and 8 the sensitivities). embedding: "shared" or
    "separate" (the sensitivity). center: the fixed distribution u and v are centred on."""
    import recovery as rec          # (the data layout and the additive start)
    if own_layer:
        raise ValueError("option (b) is dropped (q30b): the Level-1 map is placed on the common cross-world "
                         "support alone; within-world edges are the cross-fitted stage 2 (own_world_stage2)")
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
    wS = wS0 = wC0 = 0.0
    cbar, tau2 = 0.0, 1.0
    if surv:
        s = data["sbar"][idx]
        wS = noiseC / max(_noise(data["s"][idx]), 1e-6)
        if ctrl.any():
            raw = data["s0"][ctrl]                  # (only the accessible controls are ever read)
            n0 = max(_noise(raw), 1e-6)
            s0[ctrl] = raw.mean(axis=1)
            wS0 = noiseC / n0
            cbar = float(s0[ctrl].mean())
            tau2 = max(float(s0[ctrl].var()) - n0, C_PRIOR_FLOOR) if ctrl.sum() > 1 else 1.0
        else:
            cbar = float(np.mean(s))
        wC0 = noiseC / tau2                         # (the c_i prior's precision, in capture-row units)
    c0 = np.where(ctrl, s0, cbar)

    def cap_weights(zfit):
        if var_fn is None:
            return np.ones(n)
        p = np.clip(_sig(zfit), 1e-4, 1.0 - 1e-4)
        w = 1.0 / np.maximum(var_fn(p), 1e-8)
        return w / w.mean()
    wC = cap_weights(z)
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
    qps = []

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
        wC = cap_weights(g)
        work = eta + (z - g) / np.maximum(dg, 1e-6)
        surfC.fit(a[pj], b[qi], work - inter, wC * dg ** 2)
        qps.append(surfC.status)
        FC = surfC.value(a[pj], b[qi])
        if link and it % LINK_EVERY == LINK_EVERY - 1:
            lk = update_link(lk, FC + inter, z, wC, basis)
            qps.append(lk.status)
        # 2. the survival head: its surface, the predator-free baselines c_i, D_S
        if surv:
            iS = inter_s()
            surfS.fit(aS[pj], bS[qi], s - c[qi] - iS, wS * ones)
            qps.append(surfS.status)
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
    wC = cap_weights(g)
    obj = float(np.sum(wC * (z - g) ** 2)) + surfC.pen + lk.pen
    iS = inter_s()
    FSa = FSb = zero
    if surv:
        FS, FSa, FSb = surfS.value(aS[pj], bS[qi], grads=True)
        obj += float(wS * np.sum((s - c[qi] - FS - iS) ** 2) + wS0 * np.sum(((s0 - c) ** 2)[ctrl])
                     + wC0 * np.sum((c - cbar) ** 2)) + surfS.pen
    obj += lam * float(np.sum(u ** 2) + np.sum(v ** 2) + np.sum(uS ** 2) + np.sum(vS ** 2)) + lam_ab * float(
        np.sum(a ** 2) + np.sum(b ** 2) + np.sum(aS ** 2) + np.sum(bS ** 2))
    # the predictive model: the replicate dispersion, the pair residuals, the node blocks' covariances
    zrep = np.var(data["z"][idx], axis=1, ddof=1) if R > 1 else np.zeros(n)
    if var_fn is not None:
        Vp = np.maximum(var_fn(np.clip(_sig(g), 1e-4, 1 - 1e-4)), 1e-8)
        phi = float(np.mean(zrep / Vp))
        repv = phi * Vp / R
    else:
        phi = float(np.mean(zrep))
        repv = np.full(n, phi / R)
    resid = z - g
    pair_var = max(0.0, float(np.mean(resid ** 2 - repv)))
    delta = pair_var / np.maximum(pair_var + repv, 1e-12) * resid
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
                      np.concatenate([r_[1] for r_ in qrows]), dq_, D.nQ, noiseC)
    covP = _block_cov(np.concatenate([pj] * len(prows)), np.concatenate([r_[0] for r_ in prows]),
                      np.concatenate([r_[1] for r_ in prows]), dp_, D.nP, noiseC)
    return {"a": a, "b": b, "aS": aS, "bS": bS, "u": u, "v": v, "uS": uS if sep else None, "vS": vS if sep else None,
            "DS": DS, "c": c, "surfC": surfC, "surfS": surfS, "link": lk,
            "h": np.zeros(D.nbins), "hw": np.zeros((len(D.worlds), D.nbins)), "own": False, "rank": rank,
            "objective": obj, "start": "init" if init is not None else start, "weighted": var_fn is not None,
            "var_fn": var_fn, "R": R, "noise_C": noiseC, "phi": phi, "pair_var": pair_var, "delta": delta,
            "fit_idx": idx, "covQ": covQ, "covP": covP, "survival": surv, "basis": basis, "embedding": embedding,
            "center": {"distribution": center, "prey": int(len(SQ)), "pred": int(len(SP))},
            "center_nodes": {"prey": SQ, "pred": SP},
            "controls": {"accessible": int(ctrl.sum()), "cbar": cbar, "prior_var": tau2},
            "qp": qp_summary(qps)}


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


def pred_var(D, m, idx):
    """The capture head's predictive distribution of ONE FRESH replicate observation of each pair of idx
    (the registered scoring model, v4 §6.2, §7.4, §7.6) -> (location on the logit scale, latent variance):
    phi V(p) (the registered per-replicate variance at the predicted capture fraction: fresh row, column and
    cell components) + the pair-residual variance (an unseen pair's residual integrated out) + the posterior
    variance of the location (the node blocks' Laplace covariances, the delta method through the link)."""
    idx = np.asarray(idx)
    qi, pj = D.qi[idx], D.pj[idx]
    r = m["rank"]
    FC, FCa, FCb = m["surfC"].value(m["a"][pj], m["b"][qi], grads=True)
    eta = FC + (m["u"][qi] * m["v"][pj]).sum(axis=1)
    lk = m["link"]
    loc, dg = lk.G(eta), lk.dG(eta)
    gq = np.zeros((len(idx), m["covQ"].shape[1]))
    gq[:, 1] = dg * FCb
    gq[:, 3:3 + r] = dg[:, None] * m["v"][pj]
    gp = np.zeros((len(idx), m["covP"].shape[1]))
    gp[:, 0] = dg * FCa
    gp[:, 2:2 + r] = dg[:, None] * m["u"][qi]
    vpost = (np.einsum("ni,nij,nj->n", gq, m["covQ"][qi], gq) + np.einsum("ni,nij,nj->n", gp, m["covP"][pj], gp))
    vf = m.get("var_fn")
    rep = m["phi"] * (np.maximum(vf(np.clip(_sig(loc), 1e-4, 1 - 1e-4)), 1e-8) if vf is not None else 1.0)
    return loc, np.maximum(rep + m["pair_var"] + vpost, 1e-8)


def count_lpd(cnt, N, loc, var):
    """The registered capture-count log predictive density (v4 §7.6) under the bounded observation model of
    Annex H.9.2 (v4 §6.2): a replicate count k of N is a rounded latent logit-normal, K = floor(N sigma(Y) +
    1/2), Y ~ N(loc, var), so P(K = k) = P(logit((k - 1/2)/N) < Y < logit((k + 1/2)/N)), the end intervals
    open at k = 0 and k = N. It is normalized over k = 0..N and assumes no independent Bernoulli capture
    opportunities. cnt: pairs x replicates; loc, var: one per pair -> the mean log probability per replicate
    observation, per pair (noisebank's tail-stable interval probabilities)."""
    import noisebank as nb
    cnt = np.asarray(cnt)
    if cnt.ndim != 2 or (cnt < 0).any() or (cnt > N).any():
        raise ValueError(f"counts: pairs x replicates in 0..{N}")
    lo, hi = nb.interval_bounds(cnt, N)
    loc = np.asarray(loc, float)[:, None]
    sd = np.sqrt(np.maximum(np.asarray(var, float), 1e-12))[:, None]
    return nb._log_iprob((lo - loc) / sd, (hi - loc) / sd).mean(axis=1)


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


def survival_posterior(D, m, idx):
    """v4 §6.2's H-Q mapping: q_ij = E[sigma(c_i + eta^S_ij) - sigma(c_i) | data] over the JOINT fitted
    distribution of (c_i, c_i + eta^S_ij): the prey block's Laplace covariance couples c_i with b^S_i and u_i
    (c_i is estimated from the controls AND the exposed rows), the predator block adds its own; the 2 x 2
    covariance is propagated (never independent marginal error bars) -> {"q" (the posterior mean), "q_sd",
    "q_plugin" (sigma at the point estimates), "logit0", "logit1", "var0", "cov01", "var1"}."""
    if not m.get("survival"):
        raise ValueError("this fit has no survival head")
    idx = np.asarray(idx)
    qi, pj = D.qi[idx], D.pj[idx]
    r = m["rank"]
    sep = m["embedding"] == "separate" and r > 0
    x0, x1 = predict_survival(D, m, idx)
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
    (the moment estimate of the world deviations' variance: an UNSEEN world's deviation is integrated out
    with it, never estimated from its targets, v4 §6.4), "worlds" (those with pairs), ...}. m is unchanged."""
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
    e = r - h[lb]                                  # (world-level moments of the residual after the shared curve)
    ws = np.unique(lw)
    em = np.array([e[lw == x].mean() for x in ws])
    ev = np.array([e[lw == x].var() / max(int((lw == x).sum()), 1) for x in ws])
    world_var = max(0.0, float(np.mean(em ** 2 - ev))) if len(ws) else 0.0
    return {"h": h, "hw": hw, "oof": oof, "fold": fold, "folds": folds, "lam_world": lam_world, "head": head,
            "world_var": world_var, "worlds": ws}


def own_var(D, own, idx):
    """The own-world layer's integrated variance on pairs idx: world_var on the within-world pairs of a world
    the layer never saw (its deviation is integrated out), 0 elsewhere."""
    idx = np.asarray(idx)
    wi = D.within[idx]
    unseen = wi & ~np.isin(D.ownw[idx], own["worlds"])
    return np.where(unseen, own["world_var"], 0.0)

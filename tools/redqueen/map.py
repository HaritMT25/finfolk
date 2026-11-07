#!/usr/bin/env python3
"""map.py: the registered Level-1 map fitter (design v4 §6.1-6.4): two heads, one embedding.

Capture head (the primary one): for prey snapshot i and predator snapshot j, on the empirical-logit
scale of the capture fraction C/B,
    E[z_ij] = G( F_C(a_j, b_i) + u_i.v_j [+ h(lag) + h_w(lag) on own-world pairs] )
  - G, the bounded monotone link: G(eta) = logit(lo + (hi - lo) sigma(eta)), its asymptotes lo, hi
    fitted on a registered grid (lo = 0, hi = 1 is the identity);
  - F_C, the two-way monotone tensor baseline: a 6 x 6 piecewise-bilinear surface over the
    predator and prey qualities (knots at the qualities' sextiles, linear extrapolation beyond),
    nondecreasing in a (predator quality) and nonincreasing in b (prey quality): its 36
    coefficients are fitted by an exact active-set quadratic program under the 60 monotonicity
    constraints, with a second-difference smoothness penalty;
  - u_i.v_j, the rank-r specificity (r = 0..4), shared with the survival head.
Survival head, fitted jointly (v4 §6.2: the predator-free baseline is a latent, not a plug-in):
    logit S_i0 = c_i                       (the prey snapshot's predator-free controls)
    logit S_ij = c_i + F_S(a^S_j, b^S_i) + u_i' D_S v_j
  with its OWN ordered qualities a^S, b^S (head-specific ordered terms: the heads share only the
  interaction embedding u, v), its own monotone baseline F_S (nonincreasing in a^S, nondecreasing
  in b^S) and a full r x r D_S. (Sharing the qualities across heads pulled the capture coordinates
  off their own optimum, and a rank-1 interaction then repaired it: a false positive on a rank-0
  two-way surface.) Its link is the identity on the empirical-logit scale.
Both heads use Gaussian working likelihoods on their empirical logits, weighted by the replicate
noise of each head (estimated from the replicates).

Fitting: alternating, from the additive fit: the surfaces (IRLS through the link), the link, the
c_i and D_S, then every prey node's (b_i, u_i) and every predator node's (a_j, v_j) by damped
Gauss-Newton over both heads' rows, the qualities standardized over the fitting nodes; held-out
populations are placed by their support pairs alone. The embedding starts WARM (q30b): from the
top-r singular vectors of the degree-normalized residual matrix of the rank-0 spline baseline
(svd_start; start="cold" keeps small random normals, for comparison only). predict() gives the
capture head's predictions on the empirical-logit scale (the scale recovery.py scores).
Level 1 is placed on the common cross-world support alone (option a; option (b), within-world
pairs inside the Level-1 fit, is dropped: fit refuses own_layer). Within-world pairs get the
cross-fitted STAGE-2 own-world layer (own_world_stage2: a shared lag curve plus shrunk per-world
deviations on the Level-1 map's working residuals, fold-wise out-of-fold predictions).
"""
from __future__ import annotations

import math

import numpy as np

K = 6
SMOOTH = 1e-2
LINK_LO = (0.0, 0.01, 0.02, 0.04)
LINK_HI = (0.7, 0.8, 0.9, 0.95, 1.0)


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


CONS = {("inc", "dec"): _constraints(K, True, False), ("dec", "inc"): _constraints(K, False, True)}
PEN = _smooth_penalty(K)


def monotone_qp(A, c, C, x0, iters=400, tol=1e-10):
    """min 0.5 x'Ax - c'x subject to Cx >= 0, from a feasible x0 (primal active set; A positive
    definite)."""
    x = x0.copy()
    n = len(x)
    W = []
    for _ in range(iters):
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
                return x
            W.pop(int(np.argmin(lam)))
            continue
        Cp = C @ p
        alpha, block = 1.0, None
        for i in np.flatnonzero(Cp < -1e-14):
            if i in W:
                continue
            step = -(C[i] @ x) / Cp[i]
            if step < alpha:
                alpha, block = max(step, 0.0), int(i)
        x = x + alpha * p
        if block is not None:
            W.append(block)
    return x


def _hat(x, kn):
    i0 = np.clip(np.searchsorted(kn, x) - 1, 0, len(kn) - 2)
    h = kn[i0 + 1] - kn[i0]
    return i0, (x - kn[i0]) / h, h


class Surface:
    """A K x K piecewise-bilinear surface over (a, b) with monotone coefficients."""

    def __init__(self, ka, kb, direction):
        self.ka, self.kb, self.direction = ka, kb, direction
        self.theta = np.zeros((K, K))
        self.pen = 0.0

    def parts(self, a, b):
        ia, ta, ha = _hat(a, self.ka)
        ib, tb, hb = _hat(b, self.kb)
        return ia, ta, ha, ib, tb, hb

    def value(self, a, b, grads=False):
        ia, ta, ha, ib, tb, hb = self.parts(a, b)
        T = self.theta
        t00, t10, t01, t11 = T[ia, ib], T[ia + 1, ib], T[ia, ib + 1], T[ia + 1, ib + 1]
        f = t00 * (1 - ta) * (1 - tb) + t10 * ta * (1 - tb) + t01 * (1 - ta) * tb + t11 * ta * tb
        if not grads:
            return f
        fa = ((t10 - t00) * (1 - tb) + (t11 - t01) * tb) / ha
        fb = ((t01 - t00) * (1 - ta) + (t11 - t10) * ta) / hb
        return f, fa, fb

    def fit(self, a, b, y, w):
        ia, ta, _, ib, tb, _ = self.parts(a, b)
        cols = np.stack([ia * K + ib, (ia + 1) * K + ib, ia * K + ib + 1, (ia + 1) * K + ib + 1], axis=1)
        vals = np.stack([(1 - ta) * (1 - tb), ta * (1 - tb), (1 - ta) * tb, ta * tb], axis=1)
        n = K * K
        A = np.zeros(n * n)
        for p in range(4):
            for q in range(4):
                A += np.bincount(cols[:, p] * n + cols[:, q], weights=w * vals[:, p] * vals[:, q], minlength=n * n)
        A = A.reshape(n, n)
        c = np.zeros(n)
        for p in range(4):
            c += np.bincount(cols[:, p], weights=w * vals[:, p] * y, minlength=n)
        scale = np.trace(A) / n
        A = A + SMOOTH * scale * PEN + 1e-8 * scale * np.eye(n)
        C = CONS[self.direction]
        x0 = self.theta.ravel()
        if (C @ x0 < -1e-9).any():
            x0 = np.full(n, float(np.sum(w * y) / np.sum(w)))
        self.theta = monotone_qp(A, c, C, x0).reshape(K, K)
        th = self.theta.ravel()
        self.pen = float(SMOOTH * scale * th @ PEN @ th)


def _knots(x):
    kn = np.quantile(x, np.linspace(0.0, 1.0, K))
    for i in range(1, K):                    # strictly increasing
        if kn[i] <= kn[i - 1]:
            kn[i] = kn[i - 1] + 1e-6
    return kn


# ------------------------------------------------------------------ the link
class Link:
    def __init__(self, lo=0.0, hi=1.0):
        self.lo, self.hi = lo, hi

    def identity(self):
        return self.lo == 0.0 and self.hi == 1.0

    def G(self, eta):
        if self.identity():
            return eta
        s = 1.0 / (1.0 + np.exp(-eta))
        p = self.lo + (self.hi - self.lo) * s
        return np.log(p / (1.0 - p))

    def dG(self, eta):
        if self.identity():
            return np.ones_like(eta)
        s = 1.0 / (1.0 + np.exp(-eta))
        p = self.lo + (self.hi - self.lo) * s
        return (self.hi - self.lo) * s * (1.0 - s) / (p * (1.0 - p))

    def inverse(self, z):
        """eta with G(eta) = z (z clipped into the link's range)."""
        if self.identity():
            return z
        p = np.clip(1.0 / (1.0 + np.exp(-z)), self.lo + 1e-6, self.hi - 1e-6)
        s = (p - self.lo) / (self.hi - self.lo)
        return np.log(s / (1.0 - s))


# ------------------------------------------------------------------ the fitter
def _solve_nodes(idx, X, y, w, n, ridge, damp_to=None, damp=0.0):
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
    return np.linalg.solve(A, rhs[..., None])[..., 0]


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


def fit(D, idx, data, rank, lam, own_layer=False, iters=40, seed=0, survival=True, link=True,
        lam_ab=1e-3, lam_world=10.0, init=None, start="warm", var_fn=None):
    """The registered map on the fitting pairs idx -> its parameters (see the module doc). start:
    "warm" (the embedding starts from svd_start on the rank-0 spline residuals) or "cold" (small
    random normals); init (a previous fit) overrides both; fit_best runs both and keeps the lower
    penalized training objective. var_fn (the registered capture-level variance function, p ->
    per-replicate variance of the empirical logit; in production from the noise bank, v4 §7.4):
    every capture cell is weighted by 1 / var_fn(p_ij) at its fitted capture fraction (IRLS: the
    weights follow the fit; normalized to mean 1 so the penalties keep their meaning); None: equal."""
    import recovery as rec          # (the data layout and the additive start)
    if own_layer:
        raise ValueError("option (b) is dropped (q30b): the Level-1 map is placed on the common cross-world "
                         "support alone; within-world edges are the cross-fitted stage 2 (own_world_stage2)")
    rng = np.random.default_rng(seed)
    qi, pj = D.qi[idx], D.pj[idx]
    z = data["zbar"][idx]
    wC = 1.0 / max(_noise(data["z"][idx]), 1e-6)
    surv = survival and "sbar" in data
    if surv:
        s = data["sbar"][idx]
        wS = 1.0 / max(_noise(data["s"][idx]), 1e-6) / wC     # (in units of a capture row: the
        wS0 = 1.0 / max(_noise(data["s0"]), 1e-6) / wC        #  penalties mean what recovery.fit's do)
        s0 = data["s0bar"]
    wC = 1.0

    def cap_weights(zfit):
        if var_fn is None:
            return np.ones(len(idx))
        p = np.clip(1.0 / (1.0 + np.exp(-zfit)), 1e-4, 1.0 - 1e-4)
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
            m1 = rec.fit(D, idx, data["sbar"] - s0[D.qi], 0, 0.0, False, 30, seed)
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
    surfC = Surface(_knots(a[on_p]), _knots(b[on_q]), ("inc", "dec"))
    surfS = Surface(_knots(aS[on_p]), _knots(bS[on_q]), ("dec", "inc"))
    lk = Link()
    if init is not None:
        u, v = init["u"].copy(), init["v"].copy()
    elif start == "warm" and rank:
        surfC.fit(a[pj], b[qi], z, wC)
        u, v = svd_start(qi, pj, z - surfC.value(a[pj], b[qi]), D.nQ, D.nP, rank, seed)
    elif start in ("warm", "cold"):
        u, v = rng.normal(0.0, 0.1, (D.nQ, rank)), rng.normal(0.0, 0.1, (D.nP, rank))
    else:
        raise ValueError(f"start {start!r}: warm or cold")
    DS = np.zeros((rank, rank))
    c = np.zeros(D.nQ)
    if surv:
        c = s0.copy()
    nb, nW = D.nbins, len(D.worlds)
    h, hw = np.zeros(nb), np.zeros((nW, nb))
    wi = D.within[idx] if own_layer else np.zeros(len(idx), bool)
    lb, lw = D.lagbin[idx][wi], D.ownw[idx][wi]
    ones = np.ones(len(idx))
    zero = np.zeros(len(idx))
    ridge = np.array([lam_ab, lam_ab] + [lam] * rank)       # (capture quality, survival quality, u / v)
    for it in range(iters):
        own = np.zeros(len(idx))
        if wi.any():
            own[wi] = h[lb] + hw[lw, lb]
        inter = (u[qi] * v[pj]).sum(axis=1)
        # 1. the capture surface (IRLS through the link) and the link
        FC = surfC.value(a[pj], b[qi])
        eta = FC + inter + own
        g, dg = lk.G(eta), lk.dG(eta)
        wC = cap_weights(g)
        work = eta + (z - g) / np.maximum(dg, 1e-6)
        surfC.fit(a[pj], b[qi], work - inter - own, wC * dg ** 2)
        FC = surfC.value(a[pj], b[qi])
        if link and it % 5 == 4:
            base = FC + inter + own
            best = None
            for lo in LINK_LO:
                for hi in LINK_HI:
                    L = Link(lo, hi)
                    sse = float(np.sum(wC * (z - L.G(base)) ** 2))
                    if best is None or sse < best[0]:
                        best = (sse, lo, hi)
            lk = Link(best[1], best[2])
        # 2. the survival head: its surface, the predator-free baselines c_i, D_S
        if surv:
            interS = (u[qi] * (v[pj] @ DS.T)).sum(axis=1) if rank else zero
            surfS.fit(aS[pj], bS[qi], s - c[qi] - interS, wS * ones)
            FS = surfS.value(aS[pj], bS[qi])
            num = wS0 * s0 + np.bincount(qi, weights=wS * (s - FS - interS), minlength=D.nQ)
            den = wS0 + wS * np.bincount(qi, minlength=D.nQ) + 1e-6
            c = num / den
            if rank:
                Xd = (u[qi][:, :, None] * v[pj][:, None, :]).reshape(len(idx), rank * rank)
                A = Xd.T @ Xd + 1e-6 * np.eye(rank * rank)
                DS = np.linalg.solve(A, Xd.T @ (s - c[qi] - FS)).reshape(rank, rank)
        # 3. prey nodes (b_i, b^S_i, u_i), then predator nodes (a_j, a^S_j, v_j): damped Gauss-Newton
        #    over both heads' rows (each head moves only its own quality; u, v see both)
        FC, FCa, FCb = surfC.value(a[pj], b[qi], grads=True)
        eta = FC + inter + own
        g, dg = lk.G(eta), lk.dG(eta)
        rows_X = [np.column_stack([dg * FCb, zero, dg[:, None] * v[pj]])]
        rows_y = [z - g + dg * (FCb * b[qi] + inter)]
        rows_w = [wC]
        rows_i = [qi]
        if surv:
            FS, FSa, FSb = surfS.value(aS[pj], bS[qi], grads=True)
            DSv = v[pj] @ DS.T if rank else np.zeros((len(idx), 0))
            rows_X.append(np.column_stack([zero, FSb, DSv]))
            rows_y.append(s - c[qi] - FS + FSb * bS[qi])
            rows_w.append(wS * ones)
            rows_i.append(qi)
        th = _solve_nodes(np.concatenate(rows_i), np.concatenate(rows_X), np.concatenate(rows_y),
                          np.concatenate(rows_w), D.nQ, ridge, np.stack([b, bS], axis=1), 1.0)
        b, bS, u = th[:, 0], th[:, 1], th[:, 2:]
        inter = (u[qi] * v[pj]).sum(axis=1)
        eta = FC + inter + own
        g, dg = lk.G(eta), lk.dG(eta)
        rows_X = [np.column_stack([dg * FCa, zero, dg[:, None] * u[qi]])]
        rows_y = [z - g + dg * (FCa * a[pj] + inter)]
        rows_w = [wC]
        rows_i = [pj]
        if surv:
            uDS = u[qi] @ DS if rank else np.zeros((len(idx), 0))
            rows_X.append(np.column_stack([zero, FSa, uDS]))
            rows_y.append(s - c[qi] - FS + FSa * aS[pj])
            rows_w.append(wS * ones)
            rows_i.append(pj)
        th = _solve_nodes(np.concatenate(rows_i), np.concatenate(rows_X), np.concatenate(rows_y),
                          np.concatenate(rows_w), D.nP, ridge, np.stack([a, aS], axis=1), 1.0)
        a, aS, v = th[:, 0], th[:, 1], th[:, 2:]
        standardize()
    # the penalized training objective at the end (the criterion between starts: never validation)
    inter = (u[qi] * v[pj]).sum(axis=1)
    g = lk.G(surfC.value(a[pj], b[qi]) + inter)
    wC = cap_weights(g)
    obj = float(np.sum(wC * (z - g) ** 2)) + surfC.pen
    if surv:
        interS = (u[qi] * (v[pj] @ DS.T)).sum(axis=1) if rank else zero
        obj += float(wS * np.sum((s - c[qi] - surfS.value(aS[pj], bS[qi]) - interS) ** 2)
                     + wS0 * np.sum((s0 - c) ** 2)) + surfS.pen
    obj += lam * float(np.sum(u ** 2) + np.sum(v ** 2)) + lam_ab * float(np.sum(a ** 2) + np.sum(b ** 2)
                                                                      + np.sum(aS ** 2) + np.sum(bS ** 2))
    return {"a": a, "b": b, "aS": aS, "bS": bS, "u": u, "v": v, "DS": DS, "c": c, "surfC": surfC,
            "surfS": surfS, "link": lk, "h": h, "hw": hw, "own": False, "rank": rank, "objective": obj,
            "start": "init" if init is not None else start, "weighted": var_fn is not None}


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


def _eta(D, m, idx):
    qi, pj = D.qi[idx], D.pj[idx]
    return m["surfC"].value(m["a"][pj], m["b"][qi]) + (m["u"][qi] * m["v"][pj]).sum(axis=1)


def predict(D, m, idx, own=None):
    """The capture head's predictions (empirical-logit scale) on pairs idx; with own (a stage-2
    layer, own_world_stage2), its lag terms are added on the within-world pairs."""
    eta = _eta(D, m, idx)
    if own is not None:
        wi = D.within[idx]
        lb, lw = D.lagbin[idx][wi], D.ownw[idx][wi]
        eta[wi] += own["h"][lb] + own["hw"][lw, lb]
    return m["link"].G(eta)


def own_world_stage2(D, m, data, idx_w, folds=5, lam_world=10.0, seed=0, sweeps=10):
    """STAGE 2, the own-world layer (q30b: option (b) dropped; the Level-1 map m is placed on the
    common cross-world support alone). On the within-world pairs idx_w, the working residuals of m
    on its link scale, r = (z - G(eta)) / G'(eta) with weights G'(eta)^2, are fitted by a lag-bin
    curve h(lag) shared by the worlds plus a per-world deviation h_w(lag) shrunk by lam_world
    (backfitting, `sweeps` passes). Cross-fitted: the pairs are dealt into `folds` folds (a seeded
    permutation); each fold's layer is predicted by the layer fitted on the others -> {"h", "hw"
    (fitted on every pair), "oof" (the out-of-fold layer at idx_w), "fold", ...}. m is unchanged."""
    idx_w = np.asarray(idx_w)
    if not D.within[idx_w].all():
        raise ValueError("own_world_stage2 takes within-world pairs only")
    eta = _eta(D, m, idx_w)
    lk = m["link"]
    dg = np.maximum(lk.dG(eta), 1e-6)
    r = (data["zbar"][idx_w] - lk.G(eta)) / dg
    w = dg ** 2
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
    return {"h": h, "hw": hw, "oof": oof, "fold": fold, "folds": folds, "lam_world": lam_world}


def predict_survival(D, m, idx):
    """(logit S_i0, logit S_ij) of pairs idx: the predator-free baseline and the exposed survival."""
    qi, pj = D.qi[idx], D.pj[idx]
    inter = (m["u"][qi] * (m["v"][pj] @ m["DS"].T)).sum(axis=1) if m["rank"] else 0.0
    base = m["c"][qi]
    return base, base + m["surfS"].value(m["aS"][pj], m["bS"][qi]) + inter


def survival_penalty(D, m, idx):
    """q_ij = sigma(c_i + eta^S_ij) - sigma(c_i): the survival head on H-Q's probability scale (the
    point estimate; the posterior expectation of v4 §6.2 needs the joint uncertainty, item 7)."""
    s0, s1 = predict_survival(D, m, idx)
    return 1.0 / (1.0 + np.exp(-s1)) - 1.0 / (1.0 + np.exp(-s0))

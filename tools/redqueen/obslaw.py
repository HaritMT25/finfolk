#!/usr/bin/env python3
"""obslaw.py: the bank/D8 observation law of Red Queen recovery option A (the frozen specification
A_design_v5.md: sections 1.4-1.7c, 2.5 item 5 and 4.2). One small module serves the D8 bank refit (noisebank's
D8 path) and bank-mode recovery (recovery.py, recovery_extra.py, map.py).

THE LAW (v5 1.6; D8 v2 rules 46-48; Annex H.9.2). A count of a channel with scale N, ceiling M <= N, location a
and latent scale s is
    K = min{M, floor(N sigma(a + s Z) + 1/2)},   Z ~ N(0, 1).
With the thresholds t_k = logit((k - 1/2) / N), k = 1..M: P(K >= k) = Phi((a - t_k) / s); category k's latent
interval is [t_k, t_{k+1}) with t_0 = -inf and t_{M+1} = +inf, so the CAPPED category k = M has upper end +inf
while the scale stays N; E[K] = sum_{k=1..M} Phi((a - t_k) / s). Capture: N = M = B = 324 (the 5k capture
bound). Survival, exposed (S) and predator-free (F): N = 600, M = M_H = 247 at 5k (#90's binary32 age clock
through material.cohort_ceiling; never re-derived here). There is no binomial or Poisson layer. Phi is
math.erfc's (vectorized); category probabilities are formed tail-stably (v5 1.7b (i)).

LOCATIONS (v5 1.7, PC-5). a(mu) solves E[K]/N = mu for 0 < mu < c = M/N with the cap INSIDE the expectation:
bracketed bisection, then a safeguarded Newton, and the residual |E/N - mu| <= SOLVE_TOL = 1e-12 is verified at
the returned iterate (else refused). The generator's location tables (one per channel and noise multiplier
gamma; s = gamma S_ch(mu)) live on x = logit(mu / c): the uniform grid k h, |k h| <= 12, united with the s-curve
knots mapped to x; linear interpolation verified at EVERY midpoint (|E/N(a_interp) - mu| <= LOC_TOL = 2e-7);
h = 0.01 halving up to 4 times, else the build refuses. Outside |x| <= 12 the location is solved exactly per cell,
whatever the table covers (a mapped knot beyond +-12 extends the node set but is never interpolated).

THE FITTER TABLE (v5 1.7b/1.7c, PC-16). The exact conversion, for the registered map, between the bank's latent
capture law and the empirical-logit coordinate z = log((K + 1/2) / (B - K + 1/2)) (capture, gamma = 1, unscaled
curve): at nodes x_j = logit(mu_j) the exact location A_j, the mean m_z,j and centered variance V_z,j of the
empirical logit, and L_j = S_C(mu_j)^2. The fitter's four functions ARE the piecewise-linear interpolants in z
(x(z), so mu(z) = sigma(x(z)); W(z); A(z); L(z)), held at the end-node values outside [m_z,1, m_z,n] (an
extrapolation approximation, counted by the callers' `extrapolated`). Initial nodes k 0.01 (exact integer
multiples, |x| <= 12), uniform nodes within 1e-9 of a knot dropped, the knots inserted. Certification against an
INDEPENDENT inversion (Illinois iteration in x on the exact pipeline, to |m_z - z| <= 1e-11) at the probes 1/4,
1/2, 3/4 of every segment in z: (1) round trip |m_z(mu(z)) - z| <= 1e-5; (2) inverse |mu(z) - mu*| <= 2e-7;
(3) |W - V_z(mu*)| <= 1e-4 V_z(mu*) and |L - S_C(mu*)^2| <= 1e-5 S_C(mu*)^2; (4) score location
|E_{A(z), S_C(mu*)}[K] / B - mu*| <= 2e-7. Refinement: local adaptive bisection of every failing segment at its
x-midpoint; certified segments are final; refused at bisection depth 12, beyond 100,000 nodes (an over-cap knot
set before any allocation, an over-cap initial grid before any evaluation), or when m_z is not strictly increasing.

THE SAMPLER (v5 1.4-1.6). Independent across keys and replicates: rows R (prey node x replicate; C, S, F),
donors D (predator node x replicate; C, S), cells E (pair x replicate; C, S) and the free residual E^F with
variance 1 - SigmaR[F, F]; each component is Z @ F.T with F = noisebank._psd_factor (the eigen square root, PC-2;
the free-row convention makes SigmaR singular). Draw order from one NumPy generator (PC-3): Z_R (nQ, R, 3),
Z_EF (nQ, R), Z_D (nP, R, 2), Z_E (|E|, R, 2): every free control is generated once per prey node and replicate.
Deterministic endpoints are generated, not refused: mu = 0 -> 0, mu = c -> M (so M = 0 -> 0); a mean outside
[0, c] or non-finite is refused (ValueError), never clipped.

D8 STREAMS (v5 2.5 item 5, PC-9; D8:285; H.0.4). rqlib.SplitMix64 seeded by the first eight SHA-256 bytes,
little-endian, of an "AnnexH/D8/1/..." text; bounded integers by its unbiased below(n); uniforms (x >> 11) 2^-53
of one output; standard normals by #68's Box-Muller (two outputs: u1 = 1 - (x1 >> 11) 2^-53, u2 = (x2 >> 11)
2^-53, z = sqrt(-2 ln u1) cos(2 pi u2); transition.VecSplitMix64.normals).

THE BANK MODEL (v5 4.2, 2.8, 2.9). BankObservationModel loads a finfolk.redqueen.noisebank.bank/3 artifact and
its finfolk.redqueen.obstables/1 tables and validates them in 4.2's order (bytes, schema and identity, scalars,
matrices, curves, nu0, tables). Item 2's required fields are 2.8's: every field it prescribes must be present, with
the type and value 2.8 (or the section it cites) fixes; where 2.8 names a record without fixing its internal
structure (estimator.ceilings / saturation / capped_category, the horizon records' contents), only what it states is
required. The tables' identity records obslaw_sha256 AND noisescale_sha256 (the evaluator of S the builds call),
and both must equal the current files' (stricter than, and consistent with, 4.2 item 7's "obslaw implementation
sha"). Every failure is an ObsLawError (a ValueError) naming the field; no default is ever substituted. The fitter
receives W (working_var_fn) and the score law (A, L) (score_law), evaluated only at fitted quantities.

Imports: numpy, noisescale, material (and through it common's clock), rqlib and noisebank (its _psd_factor and
capture_bound) only. noisebank imports this module only inside its D8 functions, so there is no cycle. This
module reads no bank observation, no study store and no study output.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
import numpy as np  # noqa: E402

import material  # noqa: E402
import noisebank  # noqa: E402
import noisescale  # noqa: E402
import rqlib  # noqa: E402

DESIGN = "A_design_v5.md"
BANK_SCHEMA = "finfolk.redqueen.noisebank.bank/3"
TABLES_SCHEMA = "finfolk.redqueen.obstables/1"
STATUS_FITTED = "d8-fitted"
NOISE_LIKELIHOOD = "600-rounded-capped-upper-infinity"
CAPTURE_LAW = "H.9.2/B-rounded-logistic-normal/1"
D8_SHA256 = "566966e9c42952ab1699c47c520b2f61f91afd0228d9f0185be7cd7d027f92c9"
REGISTERED_INPUTS = {                       # (v5 0.3: the frozen bank's four registered inputs, by hash only)
    "observations_sha256": "64b113ce30bf76c52cda19efcde227becc2b9c00de0e2a5bbbe2892630f5cf84",
    "ages_sha256": "6ffb99ec4062801b68c462ab08208e8367d128ca820e0a9e84752f4403a717d5",
    "plan_sha256": "2ce2bb7a71d01129a0c5317a159f91bfe3fcc1dc8a2edb51c40ba806fbae31f5",
    "design_file_sha256": "6559a8da361b9b1d0399120c58cb4310ba6cb4f429e29b66599969896581ce57",
}
INPUT_KEYS = tuple(REGISTERED_INPUTS) + ("design_canonical_sha256", "provenance_sha256", "validation_report_sha256")
HORIZON = 5000                              # the generator horizon (recovery generates 5k only)
DT = 0.016
CAPTURE_BOUND = 324                         # B = recovery.B_COUNT = noisebank.capture_bound(5000)
SURV_N = 600                                # the survival scale N (D8: the cohort, not the ceiling)
SURVIVOR_CEILING = 247                      # M_5000 for the registered cohort (D8:154)
CEILINGS = {"5000": 247, "10000": 0, "20000": 0}
CHANNELS = ("C", "S", "F")
STREAM_NAMESPACE = "AnnexH/D8/1"
STREAM_GENERATOR = "rqlib.SplitMix64"

SOLVE_TOL = 1e-12        # every location solve: |E/N - mu| verified at the returned iterate (v5 1.7, 1.7b (iii))
NEWTON_TOL = 1e-13       # (the Newton stops at the CURRENT iterate once its residual is this small)
BISECT_WIDTH = 0.05      # (bracketed bisection until the bracket is this narrow, then the safeguarded Newton)
LOC_TOL = 2e-7           # the location tables' midpoint fraction tolerance (#68's, calib.py LOC_TOL)
LOC_X, LOC_H0, LOC_HALVINGS = 12.0, 0.01, 4     # PC-5
FIT_X, FIT_H0, FIT_KNOT_GAP = 12.0, 0.01, 1e-9  # v5 1.7b initial nodes
FIT_PROBES = (0.25, 0.5, 0.75)
FIT_TOL = {"roundtrip": 1e-5, "inverse": 2e-7, "W": 1e-4, "L": 1e-5, "score": 2e-7}   # v5 1.7b items 1-4
FIT_ITEMS = tuple(FIT_TOL)
FIT_INVERT_TOL = 1e-11   # the independent inversion: |m_z(mu*) - z|
FIT_DEPTH_CAP = 12       # v5 1.7b: refused when a failing segment is already at this bisection depth
FIT_NODE_CAP = 100_000   # v5 1.7b: refused when the table would exceed this many nodes
INVERT_ITERS = 200       # (Illinois iterations before the inversion is a refusal)
SYM_TOL, PSD_TOL, UNIT_TOL, FREE_TOL = 1e-12, 1e-12, 1e-9, 1e-12   # v5 4.2 item 4

SQRT2 = math.sqrt(2.0)
SQRT2PI = math.sqrt(2.0 * math.pi)
_ERFC = np.frompyfunc(math.erfc, 1, 1)
_ERFC_CUT = 40.0         # (|z| >= 40: Phi is exactly 0.0 or 1.0 in binary64, as math.erfc gives)
_CHUNK = 1 << 20         # (array elements per block)


class ObsLawError(ValueError):
    pass


def implementation_sha256():
    """sha256 of this file's bytes: the 'obslaw implementation sha' of the table identities (v5 1.7, 4.2 item 7)."""
    return rqlib.sha256_file(os.path.abspath(__file__))


def noisescale_sha256():
    """sha256 of the imported noisescale.py's bytes: the evaluator of S that every table build calls. Every table
    identity records it beside obslaw_sha256 and the loader refuses tables whose recorded value differs from the
    current file (coordinator decision on review P3-1: stricter than, and consistent with, v5 4.2 item 7's
    'obslaw implementation sha')."""
    return rqlib.sha256_file(os.path.abspath(noisescale.__file__))


# ================================================================== the law
def Phi(z):
    """The standard normal CDF, vectorized through math.erfc."""
    z = np.asarray(z, float)
    shape, z = z.shape, z.ravel()
    out = np.where(z > 0, 1.0, 0.0)
    mid = np.abs(z) < _ERFC_CUT
    if mid.any():
        out[mid] = 0.5 * _ERFC(-z[mid] / SQRT2).astype(float)
    out[np.isnan(z)] = np.nan
    return out.reshape(shape)


def sig(x):
    with np.errstate(over="ignore"):
        return 1.0 / (1.0 + np.exp(-np.asarray(x, float)))


def _check_law(N, M):
    if type(N) is not int or type(M) is not int or N < 1 or not 0 <= M <= N:
        raise ObsLawError(f"count law: N {N!r}, M {M!r} (integers, 0 <= M <= N, N >= 1)")


def thresholds(N, M):
    """t_k = logit((k - 1/2) / N), k = 1..M."""
    _check_law(N, M)
    k = np.arange(1, M + 1, dtype=float)
    return np.log((k - 0.5) / (N - k + 0.5))


def empirical_logit(k, N):
    """ell_N(k) = log((k + 1/2) / (N - k + 1/2)) (recovery.py's z, s, s0)."""
    k = np.asarray(k, float)
    return np.log((k + 0.5) / (N - k + 0.5))


def _flat(a, s):
    a, s = np.broadcast_arrays(np.asarray(a, float), np.asarray(s, float))
    return a.ravel().copy(), s.ravel().copy(), a.shape


def _check_scale(s):
    if not np.all(np.isfinite(s)) or np.any(s <= 0):
        raise ObsLawError("count law: the latent scale s must be finite and > 0")


def _blocks(n, width):
    step = max(1, _CHUNK // max(1, width))
    return (slice(i, min(n, i + step)) for i in range(0, n, step))


def _efrac(a, s, t, N, deriv=False):
    """E[K] / N (and its derivative in a) for flat arrays a, s; no validation (internal)."""
    f = np.empty(len(a))
    d = np.empty(len(a)) if deriv else None
    for sl in _blocks(len(a), len(t)):
        z = (a[sl, None] - t[None, :]) / s[sl, None]
        f[sl] = Phi(z).sum(axis=1)
        if deriv:
            d[sl] = np.exp(-0.5 * np.minimum(z * z, 1400.0)).sum(axis=1) / (SQRT2PI * s[sl])
    return (f / N, d / N) if deriv else f / N


def expected_count(a, s, N, M):
    """E[K] = sum_{k=1..M} Phi((a - t_k) / s), vectorized over broadcast (a, s)."""
    t = thresholds(N, M)
    a, s, shape = _flat(a, s)
    _check_scale(s)
    if not np.all(np.isfinite(a)):
        raise ObsLawError("count law: the location a must be finite")
    return (_efrac(a, s, t, N) * N).reshape(shape)


def expected_fraction(a, s, N, M):
    return expected_count(a, s, N, M) / N


def category_probs(a, s, N, M):
    """P(K = k), k = 0..M (last axis), tail-stably (v5 1.7b (i)): with z_k = (a - t_k) / s, G_k = Phi(z_k),
    H_k = Phi(-z_k) (G_0 = 1, G_{M+1} = 0, H_0 = 0, H_{M+1} = 1), p_k = H_{k+1} - H_k where z_{k+1} > 0 and
    p_k = G_k - G_{k+1} otherwise, so no probability is a difference of two numbers close to 1."""
    t = thresholds(N, M)
    a, s, shape = _flat(a, s)
    _check_scale(s)
    if not np.all(np.isfinite(a)):
        raise ObsLawError("count law: the location a must be finite")
    out = np.empty((len(a), M + 1))
    for sl in _blocks(len(a), M + 2):
        z = (a[sl, None] - t[None, :]) / s[sl, None]
        n = z.shape[0]
        G = np.concatenate([np.ones((n, 1)), Phi(z), np.zeros((n, 1))], axis=1)
        H = np.concatenate([np.zeros((n, 1)), Phi(-z), np.ones((n, 1))], axis=1)
        znext = np.concatenate([z, np.full((n, 1), -np.inf)], axis=1)        # z_{k+1}, k = 0..M
        out[sl] = np.where(znext > 0, H[:, 1:] - H[:, :-1], G[:, :-1] - G[:, 1:])
    return out.reshape(shape + (M + 1,))


def logit_moments(a, s, N=CAPTURE_BOUND, M=None):
    """(m_z, V_z): the mean and the CENTERED (two-pass) variance of ell_N(K) under the law (v5 1.7b (ii))."""
    M = N if M is None else M
    p = category_probs(a, s, N, M)
    ell = empirical_logit(np.arange(M + 1), N)
    m = p @ ell
    v = (p * (ell - m[..., None]) ** 2).sum(axis=-1)
    return m, v


def solve_location(mu, s, N, M, lo=None, hi=None):
    """a with |E[K]/N - mu| <= SOLVE_TOL for 0 < mu < M/N (the cap inside the expectation; v5 1.7): bracketed
    bisection, then a safeguarded Newton that stops at the CURRENT iterate once converged; the residual is
    re-verified at the returned iterate (else ObsLawError). lo, hi: an optional bracket per element (used where
    it brackets the root, else the wide bracket). -> (a, residual), shaped like mu (broadcast with s)."""
    t = thresholds(N, M)
    mu, s, shape = _flat(mu, s)
    c = M / N
    if not np.all(np.isfinite(mu)) or np.any(mu <= 0) or np.any(mu >= c):
        raise ObsLawError(f"location: a mean outside the open interval (0, M/N = {c!r}) has no location "
                          "(the endpoints 0 and M/N are deterministic counts)")
    _check_scale(s)
    n = len(mu)
    if n == 0:
        return np.zeros(shape), np.zeros(shape)
    L = t[0] - 14.0 * s - 5.0
    U = t[-1] + 14.0 * s + 5.0
    wide = np.ones(n, bool)
    if lo is not None:
        bl = np.broadcast_to(np.asarray(lo, float).ravel(), (n,)).copy()
        bh = np.broadcast_to(np.asarray(hi, float).ravel(), (n,)).copy()
        ok = np.isfinite(bl) & np.isfinite(bh) & (bl < bh)
        if ok.any():
            i = np.flatnonzero(ok)
            fl, fh = _efrac(bl[i], s[i], t, N), _efrac(bh[i], s[i], t, N)
            good = i[(fl < mu[i]) & (fh > mu[i])]
            L[good], U[good] = bl[good], bh[good]
            wide[good] = False
    for side in (0, 1):                                   # (widen the wide bracket where it does not bracket)
        iw = np.flatnonzero(wide)
        for _ in range(64):
            if not len(iw):
                break
            f = _efrac(L[iw] if side == 0 else U[iw], s[iw], t, N)
            bad = (f >= mu[iw]) if side == 0 else (f <= mu[iw])
            iw = iw[bad]
            w = U[iw] - L[iw]
            if side == 0:
                L[iw] -= w
            else:
                U[iw] += w
        else:
            raise ObsLawError("location: no bracket found")
    act = (U - L) > BISECT_WIDTH
    for _ in range(80):
        ia = np.flatnonzero(act)
        if not len(ia):
            break
        mid = 0.5 * (L[ia] + U[ia])
        below = _efrac(mid, s[ia], t, N) < mu[ia]
        L[ia[below]], U[ia[~below]] = mid[below], mid[~below]
        act[ia] = (U[ia] - L[ia]) > BISECT_WIDTH
    a = 0.5 * (L + U)
    act = np.ones(n, bool)
    for _ in range(60):
        ia = np.flatnonzero(act)
        if not len(ia):
            break
        f, d = _efrac(a[ia], s[ia], t, N, deriv=True)
        r = f - mu[ia]
        conv = np.abs(r) <= NEWTON_TOL
        act[ia[conv]] = False                             # (converged at the current iterate: kept, never moved)
        ib, rb, db = ia[~conv], r[~conv], d[~conv]
        low = rb < 0
        L[ib[low]], U[ib[~low]] = a[ib[low]], a[ib[~low]]
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            an = a[ib] - rb / db
        inside = np.isfinite(an) & (an > L[ib]) & (an < U[ib])
        a[ib] = np.where(inside, an, 0.5 * (L[ib] + U[ib]))
    ia = np.flatnonzero(act)
    if len(ia):                                           # (a remainder: bisection on its bracket)
        for _ in range(200):
            mid = 0.5 * (L[ia] + U[ia])
            below = _efrac(mid, s[ia], t, N) < mu[ia]
            L[ia[below]], U[ia[~below]] = mid[below], mid[~below]
        a[ia] = 0.5 * (L[ia] + U[ia])
    resid = np.abs(_efrac(a, s, t, N) - mu)
    if not np.all(resid <= SOLVE_TOL):
        raise ObsLawError(f"location: residual {float(np.max(resid)):.3e} > {SOLVE_TOL} (refused)")
    return a.reshape(shape), resid.reshape(shape)


def scale(curve, mu, gamma=1.0):
    """s(mu) = gamma S(mu), S = noisescale.evaluate (v5 1.5: at the INTENDED mean)."""
    if isinstance(gamma, bool) or not isinstance(gamma, (int, float)) or not math.isfinite(gamma) or gamma <= 0:
        raise ObsLawError(f"noise multiplier gamma {gamma!r}: a finite number > 0")
    return float(gamma) * np.asarray(noisescale.evaluate(curve, mu), float)


def rounded_count(a, s, u, N, M=None):
    """floor(N sigma(a + s u) + 1/2), capped at M unless M is None (the uncapped value: diagnostics only)."""
    v = np.floor(N * sig(np.asarray(a, float) + np.asarray(s, float) * np.asarray(u, float)) + 0.5)
    return (v if M is None else np.minimum(M, v)).astype(np.int64)


def check_means(mu, N, M, what="mean"):
    """A mean must be finite and inside [0, M/N]: refused otherwise (ValueError), never clipped (D8:190)."""
    mu = np.asarray(mu, float)
    c = M / N
    if not np.all(np.isfinite(mu)) or np.any(mu < 0) or np.any(mu > c):
        raise ObsLawError(f"{what}: outside [0, M/N = {c!r}] or non-finite (refused, never clipped)")
    return mu


def generate_counts(mu, u, N, M, s_of, locate):
    """The capped count law per cell and replicate (v5 1.6): mu (n,) intended means, u (n, R) standardized
    latents; s_of(mu) the latent scales; locate(mu, index) the interior locations. Deterministic endpoints:
    mu = 0 -> 0, mu = M/N -> M (so M = 0 -> 0). -> (K int64 (n, R), location (n,) with -inf / +inf at the
    endpoints, scale (n,))."""
    _check_law(N, M)
    mu = check_means(mu, N, M).ravel()
    u = np.asarray(u, float)
    if u.ndim != 2 or u.shape[0] != len(mu):
        raise ObsLawError("counts: u must be (cells, replicates)")
    c = M / N
    K = np.zeros(u.shape, np.int64)
    loc = np.where(mu == 0, -np.inf, np.inf)
    s = scale_cells = np.asarray(s_of(mu), float).reshape(mu.shape)
    top = (mu == c) & (mu > 0)
    K[top] = M
    inner = np.flatnonzero((mu > 0) & (mu < c))
    if len(inner):
        a = np.asarray(locate(mu[inner], inner), float)
        loc[inner] = a
        K[inner] = rounded_count(a[:, None], s[inner, None], u[inner], N, M)
    return K, loc, scale_cells


# ================================================================== the generator's location tables (v5 1.7)
def _mu_of_x(x, c):
    return c * sig(x)


def location_knots(curve, N, M):
    """The s-curve knots xi mapped to x = logit(sigma(xi) / c), for every knot with sigma(xi) < c (capture,
    c = 1: x = xi exactly)."""
    c = M / N
    out = set()
    for xi in curve["x"]:
        xi = float(xi)
        if M == N:
            out.add(xi)
            continue
        mk = 1.0 / (1.0 + math.exp(-xi)) if xi >= 0 else math.exp(xi) / (1.0 + math.exp(xi))
        if mk < c:
            out.add(math.log(mk) - math.log(c - mk))
    return sorted(out)


def location_nodes(knots, h):
    n = int(round(LOC_X / h))
    return np.union1d(np.arange(-n, n + 1) * h, np.asarray(knots, float))


class LocationTable:
    """One channel's frozen generator location table for one noise multiplier (v5 1.7, PC-5)."""

    def __init__(self, x, a, identity, record):
        self.x, self.a = np.asarray(x, float), np.asarray(a, float)
        self.identity, self.record = identity, record
        self.channel, self.gamma = identity["channel"], identity["gamma"]
        self.N, self.M, self.curve = identity["N"], identity["M"], identity["curve"]
        if self.x.ndim != 1 or self.x.shape != self.a.shape or len(self.x) < 2 or not np.all(np.diff(self.x) > 0) \
                or not np.all(np.isfinite(self.a)):
            raise ObsLawError(f"location table {self.channel}/{self.gamma}: malformed nodes")

    def locate(self, mu, x=None):
        """Interior locations a(mu) (0 < mu < c): the table's linear interpolation on x = logit(mu / c) where
        |x| <= X = 12 and x lies inside its node range; the exact solve everywhere else (v5 1.7: outside [-X, X]
        the location is solved exactly per cell WHATEVER the table covers, so mapped knots beyond +-12, which do
        extend the node set, are never interpolated). x: the exact axis value when the caller has it (for the
        logit link and the survival heads x = eta exactly), checked against mu."""
        mu = np.asarray(mu, float).ravel()
        c = self.M / self.N
        if not np.all((mu > 0) & (mu < c)):
            raise ObsLawError("locate: interior means only (0 < mu < M/N)")
        if x is None:
            x = np.log(mu) - np.log(c - mu)
        else:
            x = np.asarray(x, float).ravel()
            if x.shape != mu.shape or not np.all(np.abs(_mu_of_x(x, c) - mu) <= 1e-14):
                raise ObsLawError("locate: x is not logit(mu / c) for the given means")
        a = np.empty(mu.shape)
        inside = (x >= self.x[0]) & (x <= self.x[-1]) & (np.abs(x) <= LOC_X)
        a[inside] = np.interp(x[inside], self.x, self.a)
        out = ~inside
        if out.any():
            a[out] = solve_location(mu[out], scale(self.curve, mu[out], self.gamma), self.N, self.M)[0]
        return a


def location_identity(curve, channel, gamma, N, M, h, bank_sha256):
    return {"kind": "location", "channel": channel, "gamma": float(gamma), "N": N, "M": M, "X": LOC_X,
            "h0": LOC_H0, "max_halvings": LOC_HALVINGS, "h": h, "knots_x": location_knots(curve, N, M),
            "curve": curve, "loc_tol": LOC_TOL, "solve_tol": SOLVE_TOL, "bank_artifact_sha256": bank_sha256,
            "obslaw_sha256": implementation_sha256(), "noisescale_sha256": noisescale_sha256()}


def build_location_table(curve, channel, gamma, N, M, bank_sha256):
    """Build and verify one location table (v5 1.7): every midpoint |E/N(a_interp) - mu| <= LOC_TOL, h from
    0.01 halving up to LOC_HALVINGS times, else refused."""
    noisescale.check_curve(curve, channel)
    _check_law(N, M)
    scale(curve, 0.5, gamma)
    if M == 0:
        raise ObsLawError("location table: M = 0 has no interior mean")
    c = M / N
    knots = location_knots(curve, N, M)
    cache, attempts, worst_resid = {}, [], 0.0
    for halving in range(LOC_HALVINGS + 1):
        h = LOC_H0 / 2 ** halving
        x = location_nodes(knots, h)
        need = [v for v in x.tolist() if v not in cache]
        if need:
            xn = np.array(need)
            mun = _mu_of_x(xn, c)
            an, rn = solve_location(mun, scale(curve, mun, gamma), N, M)
            cache.update(zip(need, zip(an.tolist(), rn.tolist())))
        a = np.array([cache[v][0] for v in x.tolist()])
        worst_resid = max(worst_resid, max(cache[v][1] for v in x.tolist()))
        xm = 0.5 * (x[:-1] + x[1:])
        mum = _mu_of_x(xm, c)
        err = np.abs(expected_fraction(0.5 * (a[:-1] + a[1:]), scale(curve, mum, gamma), N, M) - mum)
        w = int(np.argmax(err))
        attempts.append({"h": h, "nodes": len(x), "max_midpoint_error": float(err[w]), "at_x": float(xm[w])})
        if err[w] <= LOC_TOL:
            return LocationTable(x, a, location_identity(curve, channel, gamma, N, M, h, bank_sha256),
                                 {"halvings": halving, "attempts": attempts, "max_node_residual": worst_resid})
    raise ObsLawError(f"location table {channel}/gamma {gamma}: midpoint error {attempts[-1]['max_midpoint_error']:.3e}"
                      f" > {LOC_TOL} after {LOC_HALVINGS} halvings (refused)")


# ================================================================== the fitter table (v5 1.7b, 1.7c)
def _lerp(z, m0, m1, y0, y1):
    """THE piecewise-linear evaluation of the fitter functions (the certification and every lookup share it)."""
    return y0 + (z - m0) / (m1 - m0) * (y1 - y0)


def fitter_initial_nodes(curve):
    """v5 1.7b: x_k = k h0 (exact integer multiples, |x| <= 12); uniform nodes within 1e-9 of a knot dropped;
    the knots inside [-12, 12] inserted. A knot set larger than the node cap is refused before anything is
    allocated; the distance of each uniform node to its nearest knot is found by a sorted search (its predecessor
    or successor among the sorted knots: floating subtraction is monotone, so this is exactly the minimum over all
    knots), never through a uniform-node x knot matrix."""
    if len(curve["x"]) > FIT_NODE_CAP:
        raise ObsLawError(f"fitter table: {len(curve['x'])} curve knots exceed the node cap {FIT_NODE_CAP} (refused "
                          "before any table allocation)")
    n = int(round(FIT_X / FIT_H0))
    xu = np.arange(-n, n + 1) * FIT_H0
    knots = np.asarray([float(v) for v in curve["x"]], float)
    if len(knots):
        ks = np.unique(knots)
        i = np.searchsorted(ks, xu)
        near = np.minimum(np.abs(xu - ks[np.maximum(i - 1, 0)]), np.abs(xu - ks[np.minimum(i, len(ks) - 1)]))
        xu = xu[near > FIT_KNOT_GAP]
    return np.union1d(xu, knots[(knots >= -FIT_X) & (knots <= FIT_X)])


def _fit_values(curve, x, lo=None, hi=None):
    """Exact node values at x (capture, gamma 1): (A, m_z, V_z, L, location residual)."""
    mu = sig(x)
    s = scale(curve, mu)
    a, r = solve_location(mu, s, CAPTURE_BOUND, CAPTURE_BOUND, lo, hi)
    m, v = logit_moments(a, s)
    return a, m, v, s * s, r


def _invert(curve, z, xl, xr, fl, fr, al, ar):
    """The independent inversion (v5 1.7b): Illinois iteration in x inside [xl, xr] on the exact pipeline (a
    bracketed exact location solve at sigma(x), then the exact moments) to |m_z(mu*) - z| <= FIT_INVERT_TOL.
    -> (x*, a*, V*, s*, max |m_z - z|, max location residual)."""
    lo, hi, flo, fhi = xl.copy(), xr.copy(), fl.copy(), fr.copy()
    alo, ahi = al.copy(), ar.copy()
    n = len(z)
    xs, as_, vs, ss = (np.empty(n) for _ in range(4))
    side = np.zeros(n)
    done = np.zeros(n, bool)
    worst_f = worst_r = 0.0
    for _ in range(INVERT_ITERS):
        ia = np.flatnonzero(~done)
        if not len(ia):
            break
        xn = hi[ia] - fhi[ia] * (hi[ia] - lo[ia]) / (fhi[ia] - flo[ia])
        xn = np.minimum(np.maximum(xn, lo[ia]), hi[ia])
        mu = sig(xn)
        s = scale(curve, mu)
        an, rn = solve_location(mu, s, CAPTURE_BOUND, CAPTURE_BOUND, alo[ia], ahi[ia])
        mn, vn = logit_moments(an, s)
        worst_r = max(worst_r, float(np.max(rn)))
        fn = mn - z[ia]
        conv = np.abs(fn) <= FIT_INVERT_TOL
        ic = ia[conv]
        xs[ic], as_[ic], vs[ic], ss[ic] = xn[conv], an[conv], vn[conv], s[conv]
        if conv.any():
            worst_f = max(worst_f, float(np.max(np.abs(fn[conv]))))
        done[ic] = True
        nc = ~conv
        ib, fb, xb, ab = ia[nc], fn[nc], xn[nc], an[nc]
        left = fb < 0                                     # (flo < 0 < fhi throughout)
        i1, i2 = ib[left], ib[~left]
        fhi[i1] = np.where(side[i1] == 1, 0.5 * fhi[i1], fhi[i1])
        lo[i1], flo[i1], alo[i1], side[i1] = xb[left], fb[left], ab[left], 1
        flo[i2] = np.where(side[i2] == -1, 0.5 * flo[i2], flo[i2])
        hi[i2], fhi[i2], ahi[i2], side[i2] = xb[~left], fb[~left], ab[~left], -1
    if not done.all():
        raise ObsLawError(f"fitter table: the independent inversion did not reach {FIT_INVERT_TOL} in "
                          f"{INVERT_ITERS} iterations at {int((~done).sum())} probes (refused)")
    return xs, as_, vs, ss, worst_f, worst_r


def certify_segments(curve, xl, xr, left, right, inverse=None):
    """v5 1.7b items 1-4 at the probes 1/4, 1/2, 3/4 (in z) of each segment [xl, xr] whose node values are
    left = (A, m_z, V_z, L) at xl and right at xr. inverse: the table's inverse ordinates (x at the two nodes) when
    they are not xl, xr (a table under test); the independent inversion always searches [xl, xr].
    -> {"errors": {item: (segments, 3)}, "z": (segments, 3), "fail": (segments,) bool, "max_inversion": ...,
    "max_location_residual": ...}."""
    xl, xr = np.asarray(xl, float), np.asarray(xr, float)
    il, ir = (xl, xr) if inverse is None else (np.asarray(inverse[0], float), np.asarray(inverse[1], float))
    al, ml, vl, Ll = (np.asarray(v, float) for v in left)
    ar, mr, vr, Lr = (np.asarray(v, float) for v in right)
    n = len(xl)
    if not np.all(mr > ml):
        raise ObsLawError("fitter table: m_z is not strictly increasing (no inversion exists; refused)")
    j = np.repeat(np.arange(n), len(FIT_PROBES))
    f = np.tile(np.asarray(FIT_PROBES, float), n)
    z = ml[j] + f * (mr[j] - ml[j])
    seg = (z, ml[j], mr[j])
    xh = _lerp(*seg, il[j], ir[j])
    W = _lerp(*seg, vl[j], vr[j])
    A = _lerp(*seg, al[j], ar[j])
    Lh = _lerp(*seg, Ll[j], Lr[j])
    xs, _, vs, ss, worst_f, worst_r = _invert(curve, z, xl[j], xr[j], ml[j] - z, mr[j] - z, al[j], ar[j])
    mus = sig(xs)
    muh = sig(xh)
    sh = scale(curve, muh)
    ah, rh = solve_location(muh, sh, CAPTURE_BOUND, CAPTURE_BOUND, al[j], ar[j])
    mh, _ = logit_moments(ah, sh)
    err = {"roundtrip": np.abs(mh - z), "inverse": np.abs(muh - mus), "W": np.abs(W - vs) / vs,
           "L": np.abs(Lh - ss * ss) / (ss * ss),
           "score": np.abs(expected_fraction(A, ss, CAPTURE_BOUND, CAPTURE_BOUND) - mus)}
    shaped = {k: v.reshape(n, len(FIT_PROBES)) for k, v in err.items()}
    fail = np.zeros(n, bool)
    for k, v in shaped.items():
        fail |= np.any(~(v <= FIT_TOL[k]), axis=1)
    return {"errors": shaped, "z": z.reshape(n, len(FIT_PROBES)), "fail": fail, "max_inversion": worst_f,
            "max_location_residual": max(worst_r, float(np.max(rh)) if len(rh) else 0.0)}


def fitter_identity(curve, bank_sha256):
    return {"kind": "fitter", "channel": "C", "gamma": 1.0, "N": CAPTURE_BOUND, "M": CAPTURE_BOUND, "X": FIT_X,
            "h0": FIT_H0, "knot_gap": FIT_KNOT_GAP, "knots": [float(v) for v in curve["x"]], "curve": curve,
            "probes": list(FIT_PROBES), "tolerances": dict(FIT_TOL), "invert_tol": FIT_INVERT_TOL,
            "solve_tol": SOLVE_TOL, "depth_cap": FIT_DEPTH_CAP, "node_cap": FIT_NODE_CAP,
            "bank_artifact_sha256": bank_sha256, "obslaw_sha256": implementation_sha256(),
            "noisescale_sha256": noisescale_sha256()}


def build_fitter_table(curve, bank_sha256):
    """Build and certify the fitter table (v5 1.7b, local adaptive bisection; 1.7c). Refused at bisection depth
    FIT_DEPTH_CAP, beyond FIT_NODE_CAP nodes (the initial grid included: checked before any node is evaluated or
    certified), or when m_z is not strictly increasing."""
    noisescale.check_curve(curve, "C")
    depth_cap, node_cap = FIT_DEPTH_CAP, FIT_NODE_CAP
    x0 = fitter_initial_nodes(curve)
    if len(x0) > node_cap:
        raise ObsLawError(f"fitter table: the initial grid has {len(x0)} nodes, over the node cap {node_cap} (refused "
                          "before evaluating or certifying)")
    a0, m0, v0, L0, r0 = _fit_values(curve, x0)
    if not np.all(np.diff(m0) > 0):
        raise ObsLawError("fitter table: m_z is not strictly increasing over the initial nodes (refused)")
    node = {float(x): (a, m, v, L) for x, a, m, v, L in zip(x0, a0, m0, v0, L0)}
    worst_loc = float(np.max(r0))
    queue = (x0[:-1].copy(), x0[1:].copy(), np.zeros(len(x0) - 1, int))
    worst = {k: {"value": 0.0} for k in FIT_ITEMS}
    depths, passes, inserted, worst_inv = {}, 0, [], 0.0
    while len(queue[0]):
        passes += 1
        xl, xr, dep = queue
        left = tuple(np.array([node[float(x)][i] for x in xl]) for i in range(4))
        right = tuple(np.array([node[float(x)][i] for x in xr]) for i in range(4))
        cert = certify_segments(curve, xl, xr, left, right)
        worst_inv = max(worst_inv, cert["max_inversion"])
        worst_loc = max(worst_loc, cert["max_location_residual"])
        ok = np.flatnonzero(~cert["fail"])
        for k, e in cert["errors"].items():
            if len(ok):
                pe = e[ok].max(axis=1)
                i = int(np.argmax(pe))
                if pe[i] > worst[k]["value"]:
                    s_, p_ = ok[i], int(np.argmax(e[ok[i]]))
                    worst[k] = {"value": float(pe[i]), "x_lo": float(xl[s_]), "x_hi": float(xr[s_]),
                                "depth": int(dep[s_]), "z": float(cert["z"][s_, p_])}
        for d in dep[ok].tolist():
            depths[d] = depths.get(d, 0) + 1
        bad = np.flatnonzero(cert["fail"])
        if not len(bad):
            break
        if int(dep[bad].max()) >= depth_cap:
            raise ObsLawError(f"fitter table: {int((dep[bad] >= depth_cap).sum())} segments still fail at bisection "
                              f"depth {depth_cap} (refused)")
        xm = 0.5 * (xl[bad] + xr[bad])
        if len(node) + len(xm) > node_cap:
            raise ObsLawError(f"fitter table: {len(node) + len(xm)} nodes would exceed {node_cap} (refused)")
        am, mm, vm, Lm, rm = _fit_values(curve, xm, left[0][bad], right[0][bad])
        worst_loc = max(worst_loc, float(np.max(rm)))
        if not np.all((mm > left[1][bad]) & (mm < right[1][bad])):
            raise ObsLawError("fitter table: m_z is not strictly increasing across a new node (refused)")
        for x, a, m, v, L in zip(xm, am, mm, vm, Lm):
            node[float(x)] = (a, m, v, L)
        inserted.extend(xm.tolist())
        queue = (np.concatenate([xl[bad], xm]), np.concatenate([xm, xr[bad]]),
                 np.concatenate([dep[bad] + 1, dep[bad] + 1]))
    xs = np.array(sorted(node))
    vals = np.array([node[x] for x in xs.tolist()])
    for k in FIT_ITEMS:
        worst[k]["tolerance"] = FIT_TOL[k]
    record = {"nodes": len(xs), "segments": len(xs) - 1, "passes": passes, "inserted": len(inserted),
              "inserted_x_range": [min(inserted), max(inserted)] if inserted else None,
              "depth_histogram": {str(d): n for d, n in sorted(depths.items())}, "worst": worst,
              "max_location_residual": worst_loc, "max_inversion_residual": worst_inv,
              "m_z_strictly_increasing": bool(np.all(np.diff(vals[:, 1]) > 0))}
    return FitterTable(xs, vals[:, 1], vals[:, 2], vals[:, 0], vals[:, 3], fitter_identity(curve, bank_sha256), record)


class FitterTable:
    """The frozen conversion of v5 1.7b: inside [m_z,1, m_z,n] the piecewise-linear interpolants in z of
    x (the inverse; mu(z) = sigma(x(z))), W = V_z, A and L = S_C^2; outside, the end-node values (counted)."""

    def __init__(self, x, m, V, A, L, identity, record):
        self.x, self.m, self.V, self.A, self.L = (np.asarray(v, float) for v in (x, m, V, A, L))
        self.identity, self.record = identity, record
        n = self.x.shape[0] if self.x.ndim else 0
        for name in ("x", "m", "V", "A", "L"):               # (every node array flat, (n,): checked at load)
            shape = getattr(self, name).shape
            if shape != (n,):
                raise ObsLawError(f"fitter table: fit_{name} has shape {shape}, not ({n},) (refused)")
        if n < 2 or not all(np.all(np.isfinite(v)) for v in (self.x, self.m, self.V, self.A, self.L)):
            raise ObsLawError("fitter table: malformed node arrays")
        if not np.all(np.diff(self.x) > 0) or not np.all(np.diff(self.m) > 0):
            raise ObsLawError("fitter table: x and m_z must be strictly increasing (refused)")
        if np.any(self.V <= 0) or np.any(self.L <= 0):
            raise ObsLawError("fitter table: V_z and L must be positive")
        self.kappa = np.diff(self.A) / np.diff(self.m)       # the exact segment slopes dA/dz (v5 3.3)
        self._st = [np.abs(self.kappa)]
        while 2 ** len(self._st) <= len(self.kappa):
            prev, half = self._st[-1], 2 ** (len(self._st) - 1)
            self._st.append(np.maximum(prev[:-half], prev[half:]))
        self.lat_var_min = float(np.min(self.L))             # min_j L_j (the latent SD floor's square, v5 3.3)

    def evaluate(self, z):
        """-> {x, W, A, L, extrapolated (bool mask)} at z (any shape)."""
        z = np.asarray(z, float)
        shape, zr = z.shape, z.ravel()
        if not np.all(np.isfinite(zr)):
            raise ObsLawError("fitter table: z must be finite")
        m = self.m
        n = len(m)
        j = np.clip(np.searchsorted(m, zr, side="right") - 1, 0, n - 2)
        below, above = zr < m[0], zr > m[-1]
        out = {}
        for name, y in (("x", self.x), ("W", self.V), ("A", self.A), ("L", self.L)):
            v = _lerp(zr, m[j], m[j + 1], y[j], y[j + 1])
            v[below], v[zr >= m[-1]] = y[0], y[-1]           # (the end-node values, exactly)
            out[name] = v.reshape(shape)
        out["extrapolated"] = (below | above).reshape(shape)
        return out

    def mu_hat(self, z):
        return sig(self.evaluate(z)["x"])

    def slope_max(self, zlo, zhi):
        """H^max (v5 3.3): max |kappa_j| over the segments [m_j, m_{j+1}] meeting [zlo, zhi] (closed), 0 where the
        interval lies wholly outside the tabulated range; an exact range maximum (sparse table)."""
        zlo, zhi = np.broadcast_arrays(np.asarray(zlo, float), np.asarray(zhi, float))
        shape, lo, hi = zlo.shape, zlo.ravel(), zhi.ravel()
        if not (np.all(np.isfinite(lo)) and np.all(np.isfinite(hi)) and np.all(lo <= hi)):
            raise ObsLawError("slope_max: finite intervals with zlo <= zhi")
        m = self.m
        jlo = np.searchsorted(m[1:], lo, side="left")
        jhi = np.searchsorted(m[:-1], hi, side="right") - 1
        out = np.zeros(len(lo))
        ok = jlo <= jhi
        if ok.any():
            a, b = jlo[ok], jhi[ok]
            k = np.frexp((b - a + 1).astype(float))[1] - 1
            res = np.empty(len(a))
            for kk in np.unique(k):
                sel = k == kk
                st = self._st[int(kk)]
                res[sel] = np.maximum(st[a[sel]], st[b[sel] - 2 ** int(kk) + 1])
            out[ok] = res
        return out.reshape(shape)


class _FitterFn:
    """A fitter function of p = sigma(z) with the model identity tag and a running count of evaluations
    outside the tabulated range (`extrapolated`, the candidate record's table_extrapolated diagnostic)."""

    def __init__(self, table, identity):
        self.table, self.identity = table, identity
        self.extrapolated = 0
        self.evaluations = 0

    def _eval(self, p):
        p = np.asarray(p, float)
        if not np.all((p > 0) & (p < 1)):
            raise ObsLawError("fitter function: p must lie in (0, 1)")
        r = self.table.evaluate(np.log(p) - np.log1p(-p))
        self.extrapolated += int(np.count_nonzero(r["extrapolated"]))
        self.evaluations += int(p.size)
        return r


class WorkingVariance(_FitterFn):
    """p -> W(logit p): the per-replicate variance of the empirical logit (map.fit's var_fn; v5 1.7b, 3.3)."""

    def __call__(self, p):
        return self._eval(p)["W"]


class ScoreLaw(_FitterFn):
    """p -> (A, L)(logit p): the latent location and the latent variance S_C^2 of the bank's law at the mean
    mu = m_z^{-1}(logit p) (map's score_law; v5 3.3, PC-17)."""

    def __call__(self, p):
        r = self._eval(p)
        return r["A"], r["L"]


# ================================================================== the tables file (finfolk.redqueen.obstables/1)
def _array_digest(arrays):
    return {k: [v.dtype.str, list(v.shape), rqlib.sha256_bytes(v.tobytes(order="C"))] for k, v in sorted(arrays.items())}


class ObsTables:
    """The location tables (per channel and gamma) and the fitter table, with identity and content sha256."""

    def __init__(self, location, fitter, bank_sha256):
        self.location, self.fitter, self.bank_sha256 = dict(location), fitter, bank_sha256
        self.file_sha256 = self.stored_content_sha256 = self._stored_identity = None

    def _order(self):
        return sorted(self.location, key=lambda k: (CHANNELS.index(k[0]), k[1]))

    def identity(self):
        """The tables' identity: as stored in the file when loaded, else as built by this implementation."""
        if self._stored_identity is not None:
            return self._stored_identity
        return {"schema": TABLES_SCHEMA, "bank_artifact_sha256": self.bank_sha256,
                "obslaw_sha256": implementation_sha256(), "noisescale_sha256": noisescale_sha256(),
                "location": [self.location[k].identity for k in self._order()], "fitter": self.fitter.identity}

    def _payload(self):
        arrays, records = {}, []
        for i, k in enumerate(self._order()):
            t = self.location[k]
            arrays[f"loc{i}_x"], arrays[f"loc{i}_a"] = t.x, t.a
            records.append(t.record)
        for name in ("x", "m", "V", "A", "L"):
            arrays[f"fit_{name}"] = getattr(self.fitter, name)
        body = {"schema": TABLES_SCHEMA, "identity": self.identity(),
                "records": {"location": records, "fitter": self.fitter.record}}
        return arrays, body

    def content_sha256(self):
        arrays, body = self._payload()
        return rqlib.canonical_sha(dict(body, arrays=_array_digest(arrays)))

    def to_bytes(self):
        """A deterministic .npz (stored zip, fixed timestamps): the same tables always give the same bytes."""
        arrays, body = self._payload()
        meta = dict(body, content_sha256=rqlib.canonical_sha(dict(body, arrays=_array_digest(arrays))))
        members = dict(arrays, meta=np.array(rqlib.canonical(meta).decode("ascii")))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            for name in sorted(members):
                b = io.BytesIO()
                arr = members[name]
                np.lib.format.write_array(b, arr if arr.flags.c_contiguous else arr.copy(order="C"), allow_pickle=False)
                info = zipfile.ZipInfo(name + ".npy", date_time=(1980, 1, 1, 0, 0, 0))
                info.external_attr = 0o644 << 16
                zf.writestr(info, b.getvalue())
        return buf.getvalue()

    def save(self, path):
        raw = self.to_bytes()
        rqlib.write_durable(path, raw)
        self.file_sha256 = rqlib.sha256_bytes(raw)
        return self.file_sha256

    @classmethod
    def from_bytes(cls, raw):
        try:
            with np.load(io.BytesIO(raw), allow_pickle=False) as z:
                arrays = {k: np.array(z[k]) for k in z.files}
        except Exception as e:                            # (any unreadable npz)
            raise ObsLawError(f"observation tables: not a readable npz ({type(e).__name__}: {e})") from None
        if "meta" not in arrays:
            raise ObsLawError("observation tables: no meta record")
        meta = _strict_json(str(arrays.pop("meta")).encode("utf-8"), "observation tables meta")
        if not isinstance(meta, dict) or meta.get("schema") != TABLES_SCHEMA:
            raise ObsLawError(f"observation tables: schema {meta.get('schema') if isinstance(meta, dict) else meta!r}"
                              f" is not {TABLES_SCHEMA}")
        for k in ("identity", "records", "content_sha256"):
            if k not in meta:
                raise ObsLawError(f"observation tables: missing field {k}")
        body = {k: meta[k] for k in ("schema", "identity", "records")}
        if rqlib.canonical_sha(dict(body, arrays=_array_digest(arrays))) != meta["content_sha256"]:
            raise ObsLawError("observation tables: content sha256 does not match the stored arrays (refused)")
        ident = meta["identity"]
        try:
            loc = {}
            for i, (li, rec) in enumerate(zip(ident["location"], meta["records"]["location"])):
                t = LocationTable(arrays[f"loc{i}_x"], arrays[f"loc{i}_a"], li, rec)
                if (t.channel, t.gamma) in loc:
                    raise ObsLawError(f"observation tables: duplicate table {t.channel}/{t.gamma}")
                loc[(t.channel, t.gamma)] = t
            if len(ident["location"]) != len(meta["records"]["location"]) or \
                    sum(k.startswith("loc") for k in arrays) != 2 * len(loc):
                raise ObsLawError("observation tables: location arrays and identities disagree")
            fit = FitterTable(arrays["fit_x"], arrays["fit_m"], arrays["fit_V"], arrays["fit_A"], arrays["fit_L"],
                              ident["fitter"], meta["records"]["fitter"])
        except (KeyError, TypeError) as e:
            raise ObsLawError(f"observation tables: malformed ({type(e).__name__}: {e})") from None
        if not isinstance(ident, dict) or ident.get("schema") != TABLES_SCHEMA or \
                [li for li in ident.get("location", [])] != [loc[k].identity for k in
                                                             sorted(loc, key=lambda k: (CHANNELS.index(k[0])
                                                                                        if k[0] in CHANNELS else 9, k[1]))]:
            raise ObsLawError("observation tables: the identity record is malformed or out of order")
        out = cls(loc, fit, ident.get("bank_artifact_sha256"))
        out.file_sha256 = rqlib.sha256_bytes(raw)
        out.stored_content_sha256 = meta["content_sha256"]
        out._stored_identity = ident
        return out

    @classmethod
    def load(cls, path, sha256=None):
        raw = rqlib.read_bytes(path)
        got = rqlib.sha256_bytes(raw)
        if sha256 is not None and got != sha256:
            raise ObsLawError(f"observation tables: file sha256 {got} differs from the configured {sha256} (refused)")
        return cls.from_bytes(raw)


def build_obs_tables(bank, gammas):
    """All tables for a validated BankArtifact: location tables for C, S, F at every gamma, the fitter table."""
    gs = sorted({float(g) for g in gammas})
    if not gs:
        raise ObsLawError("observation tables: at least one noise multiplier")
    loc = {}
    for g in gs:
        for ch in CHANNELS:
            N, M = bank.law(ch)
            loc[(ch, g)] = build_location_table(bank.s_logit[ch], ch, g, N, M, bank.sha256)
    return ObsTables(loc, build_fitter_table(bank.s_logit["C"], bank.sha256), bank.sha256)


# ================================================================== the sampler (v5 1.4)
def check_matrix(v, n, name):
    """v5 4.2 item 4 for one component: an n x n list of lists of finite numbers (not bool), symmetric within
    SYM_TOL (both triangles read), PSD (smallest eigenvalue >= -PSD_TOL), diagonal >= 0 -> (A + A') / 2."""
    if not isinstance(v, list) or len(v) != n or any(not isinstance(r, list) or len(r) != n for r in v):
        raise ObsLawError(f"{name}: must be a {n}x{n} list of lists")
    if not all(_num(x) for r in v for x in r):
        raise ObsLawError(f"{name}: every entry must be a finite number (not bool)")
    A = np.array(v, float)
    if float(np.max(np.abs(A - A.T))) > SYM_TOL:
        raise ObsLawError(f"{name}: not symmetric (max |A - A'| {float(np.max(np.abs(A - A.T))):.3e} > {SYM_TOL})")
    S = 0.5 * (A + A.T)
    if float(np.min(np.linalg.eigvalsh(S))) < -PSD_TOL:
        raise ObsLawError(f"{name}: not PSD (smallest eigenvalue {float(np.min(np.linalg.eigvalsh(S))):.3e})")
    if np.any(np.diag(S) < 0):
        raise ObsLawError(f"{name}: a negative diagonal entry")
    return S


def psd_factors(SigmaR, SigmaD, SigmaE):
    """The components' PSD eigen factors (PC-2; noisebank._psd_factor) and the free residual SD
    sqrt(1 - SigmaR[F, F]) (validated per v5 4.2 item 4, including the unit totals)."""
    raw = lambda v: v if isinstance(v, list) else np.asarray(v, float).tolist()  # noqa: E731  (JSON lists as read)
    SR, SD, SE = (check_matrix(raw(v), n, k) for v, n, k in
                  ((SigmaR, 3, "SigmaR"), (SigmaD, 2, "SigmaD"), (SigmaE, 2, "SigmaE")))
    for i, ch in enumerate(("C", "S")):
        tot = SR[i, i] + SD[i, i] + SE[i, i]
        if abs(tot - 1.0) > UNIT_TOL:
            raise ObsLawError(f"unit total {ch}: SigmaR + SigmaD + SigmaE diagonal = {tot!r}, not 1 within {UNIT_TOL}")
    if 1.0 - SR[2, 2] < -FREE_TOL:
        raise ObsLawError(f"free residual 1 - SigmaR[F,F] = {1.0 - SR[2, 2]!r} < 0")
    return {"R": noisebank._psd_factor(SR), "D": noisebank._psd_factor(SD), "E": noisebank._psd_factor(SE),
            "free_sd": math.sqrt(max(0.0, 1.0 - SR[2, 2])), "SigmaR": SR, "SigmaD": SD, "SigmaE": SE}


def standard_normals(rng, nQ, nP, nE, reps):
    """PC-3's draw order from one NumPy generator: Z_R (nQ, R, 3), Z_EF (nQ, R), Z_D (nP, R, 2), Z_E (|E|, R, 2)."""
    return {"R": rng.standard_normal((nQ, reps, 3)), "EF": rng.standard_normal((nQ, reps)),
            "D": rng.standard_normal((nP, reps, 2)), "E": rng.standard_normal((nE, reps, 2))}


def latent(Z, factors, qi, pj):
    """The standardized latents (v5 1.4): u^C, u^S per pair (R_q + D_p + E_e) and u^F per prey node (R^F + E^F)."""
    qi, pj = np.asarray(qi, np.int64), np.asarray(pj, np.int64)
    Rm = Z["R"] @ factors["R"].T
    Dm = Z["D"] @ factors["D"].T
    Em = Z["E"] @ factors["E"].T
    if Em.shape[0] != len(qi) or len(qi) != len(pj):
        raise ObsLawError("latent: one cell draw per pair")
    return {"C": Rm[qi, :, 0] + Dm[pj, :, 0] + Em[:, :, 0],
            "S": Rm[qi, :, 1] + Dm[pj, :, 1] + Em[:, :, 1],
            "F": Rm[:, :, 2] + factors["free_sd"] * Z["EF"]}


# ================================================================== D8 streams (v5 2.5 item 5, PC-9)
def d8_text(*parts):
    return STREAM_NAMESPACE + "/" + "/".join(str(p) for p in parts)


def stream_seed_d8(text):
    """The first eight SHA-256 bytes, little-endian, of the stream text (stats.stream_seed's derivation)."""
    if not isinstance(text, str) or not text.startswith(STREAM_NAMESPACE + "/"):
        raise ObsLawError(f"D8 stream text {text!r} must start with {STREAM_NAMESPACE}/")
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little")


def d8_stream(text):
    return rqlib.SplitMix64(stream_seed_d8(text))


def stream_record(text, n=2):
    """{text, seed, first_outputs}: what a D8 consumer records for each stream (v5 2.5 item 5)."""
    rng = d8_stream(text)
    return {"text": text, "seed": stream_seed_d8(text), "generator": STREAM_GENERATOR,
            "first_outputs": [rng.next64() for _ in range(n)]}


def splitmix_below(rng, n, count):
    """count draws of rqlib.SplitMix64.below(n) (H.0.4's unbiased bounded integer)."""
    return np.array([rng.below(n) for _ in range(count)], dtype=np.int64)


def splitmix_uniforms(rng, count):
    """count uniforms on [0, 1): (x >> 11) 2^-53 of one next64() output each."""
    x = np.array([rng.next64() for _ in range(count)], dtype=np.uint64)
    return (x >> np.uint64(11)).astype(np.float64) * (1.0 / (1 << 53))


def splitmix_normals(rng, count):
    """count standard normals by #68's transform (transition.VecSplitMix64.normals) on the scalar generator:
    two consecutive outputs x1, x2; u1 = 1 - (x1 >> 11) 2^-53, u2 = (x2 >> 11) 2^-53; sqrt(-2 ln u1) cos(2 pi u2)."""
    x = np.array([rng.next64() for _ in range(2 * count)], dtype=np.uint64)
    u = (x >> np.uint64(11)).astype(np.float64) * (1.0 / (1 << 53))
    u1, u2 = 1.0 - u[0::2], u[1::2]
    return np.sqrt(-2.0 * np.log(u1)) * np.cos(2 * math.pi * u2)


# ================================================================== the bank/3 artifact (v5 2.8, 2.9, 4.2)
# What v5 2.8 prescribes (table L732-751; test_obslaw.py's V5_FIELDS cites the line of every entry). Where 2.8 names a
# record without fixing its internal structure, only what it does state is required (presence, type, a fixed value).
TOP_FIELDS = ("schema", "status", "synthetic", "cohort", "cohort_sha256", "horizon", "dt", "support_law", "age_clock",
              "survivor_ceiling", "fit", "noise", "map_variance", "d8", "inputs", "estimator", "horizons")
NOISE_FIELDS = ("available", "s_logit", "SigmaR", "SigmaD", "SigmaE", "horizon", "capture_bound", "survivor_ceiling")
MAP_VARIANCE_FIELDS = ("s_logit", "nu0", "rule", "consumer")
MAP_VARIANCE_CONSUMER = "map.fit rep_prior, capture channel"                                  # (L747)
D8_FIELDS = ("amendment_sha256", "capture_law", "ceilings", "max_age", "denominator", "age_predicate",
             "capped_category")
D8_TEXTS = {"age_predicate": "updated binary32 age > binary32(max_age) is an age death; F_i(H)=1 iff false through "
                             "H frames (common.age_feasible)",                               # (L748)
            "capped_category": "k = M_H: latent upper endpoint +inf, scale N = 600"}
FIT_FIELDS = ("noise_likelihood", "noise", "streams")
FIT_NOISE_SHAS = ("implementation_sha256", "inputs_sha256", "receipt_sha256", "engine_sha256")
BOOTSTRAP_FIELDS = ("generator", "namespace", "texts", "seeds")
REFIT_TEXT = STREAM_NAMESPACE + "/noisebank/D8-refit/h{}/bootstrap"   # (v5 2.5 item 5, L641-643)
HORIZON_KEYS = ("5000", "10000", "20000")                    # (noisebank.HORIZONS, keyed str(h) as now: L1778-1782)
# estimator (L750): "the existing record (noisebank.py L1769-1777 @4991907) plus ceilings, saturation per channel and
# its basis, capped_category". The existing record's "seed" (the legacy NumPy bootstrap seed, which the D8 path
# replaces by the fit.streams.bootstrap streams) is NOT required: v5 is ambiguous on it (reported, not decided).
ESTIMATOR_FIELDS = ("z_intervals", "rho_max", "saturation", "sigma_min", "info_min", "multi_start", "start_tol", "boot",
                    "boot_fail_max", "rectangle", "grid", "constrained_fit", "fixed_replicate_bias", "ceilings",
                    "capped_category")
ESTIMATOR_VALUES = {"multi_start": 16, "boot": 999}          # (v5 2.5 L615-616: 16 Halton starts, 999 draws)
# horizons (L751): "per horizon as now (noisebank.py L1683-1757)": the fields every record carries (L1689-1690, L1698,
# L1701 / L1756) and, with status ok, groups and grid_validation (L1741-1742).
HORIZON_FIELDS = ("capture_bound", "replicates", "incomplete_cells", "channels", "scales", "nu0", "curve_points",
                  "worlds", "status", "reasons", "components", "bootstrap")
HORIZON_OK_FIELDS = ("groups", "grid_validation")
HORIZON_STATUSES = ("ok", "unavailable")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _int(v):
    return type(v) is int


def _strict_json(raw, what):
    """Strict JSON: NaN / Infinity tokens and duplicate keys refused at parse (v5 4.2 item 1)."""
    def constant(tok):
        raise ObsLawError(f"{what}: the JSON token {tok} is refused (no NaN / Infinity)")

    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ObsLawError(f"{what}: duplicate key {k!r}")
            out[k] = v
        return out
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=constant, object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ObsLawError(f"{what}: not strict JSON ({e})") from None


def _field(d, key, where):
    if not isinstance(d, dict):
        raise ObsLawError(f"bank artifact: {where} must be an object")
    if key not in d:
        raise ObsLawError(f"bank artifact: missing field {where}.{key}" if where else f"bank artifact: missing field {key}")
    return d[key]


def _sha_field(d, key, where):
    v = _field(d, key, where)
    if not rqlib.is_sha256(v):
        raise ObsLawError(f"bank artifact: {where}.{key} is not a sha256 identity")
    return v


def _nu0_record(rec, ch, consumed):
    """v5 4.2 item 6 / 2.8: exactly one of estimated (nu0 > 0 finite, not bool), full_pooling (no nu0 key) or
    unavailable (refused for the consumed capture channel). -> nu0 float or None."""
    where = f"map_variance.nu0.{ch}"
    if not isinstance(rec, dict) or "status" not in rec:
        raise ObsLawError(f"bank artifact: {where} must be an object with a status")
    st = rec["status"]
    if st == "estimated":
        v = rec.get("nu0")
        if not _num(v) or not v > 0:
            raise ObsLawError(f"bank artifact: {where} is estimated but nu0 {v!r} is not a finite number > 0")
        return float(v)
    if st == "full_pooling":
        if "nu0" in rec:
            raise ObsLawError(f"bank artifact: {where} is full_pooling but carries a nu0 key")
        return None
    if st == "unavailable" and not consumed:
        if not isinstance(rec.get("reason"), str):
            raise ObsLawError(f"bank artifact: {where} is unavailable without a reason")
        return None
    raise ObsLawError(f"bank artifact: {where} status {st!r} is refused"
                      + (" (the capture channel's nu0 is consumed by map.fit)" if consumed else ""))


class BankArtifact:
    """A finfolk.redqueen.noisebank.bank/3 artifact, validated in v5 4.2's order (items 1-6)."""

    def __init__(self, path, *, sha256=None, allow_synthetic=False):
        raw = rqlib.read_bytes(path)
        got = rqlib.sha256_bytes(raw)                                       # 1. bytes
        if sha256 is not None and got != sha256:
            raise ObsLawError(f"bank artifact: file sha256 {got} differs from the configured {sha256} (refused)")
        self.path, self.sha256 = os.path.abspath(path), got
        doc = _strict_json(raw, "bank artifact")
        if not isinstance(doc, dict):
            raise ObsLawError("bank artifact: not a JSON object")
        self.doc = doc
        self._identity(doc, allow_synthetic)                                # 2.
        self._scalars(doc)                                                  # 3.
        nz = doc["noise"]
        self.factors = psd_factors(nz["SigmaR"], nz["SigmaD"], nz["SigmaE"])  # 4.
        try:                                                                # 5.
            noisescale.check_set(nz["s_logit"])
        except noisescale.ScaleError as e:
            raise ObsLawError(f"bank artifact: noise.s_logit: {e}") from None
        if rqlib.canonical(doc["map_variance"]["s_logit"]) != rqlib.canonical(nz["s_logit"]):
            raise ObsLawError("bank artifact: map_variance.s_logit differs from noise.s_logit")
        self.s_logit = {ch: nz["s_logit"][ch] for ch in CHANNELS}
        nu0 = doc["map_variance"]["nu0"]                                    # 6.
        if not isinstance(nu0, dict):
            raise ObsLawError("bank artifact: map_variance.nu0 must be an object")
        for ch in CHANNELS:
            v = _nu0_record(_field(nu0, ch, "map_variance.nu0"), ch, consumed=(ch == "C"))
            if ch == "C":
                self.nu0_C = v
        self.synthetic = doc["synthetic"]
        self.M_H = SURVIVOR_CEILING

    @staticmethod
    def _identity(doc, allow_synthetic):
        schema = _field(doc, "schema", "")
        if schema != BANK_SCHEMA:
            raise ObsLawError(f"bank artifact: schema {schema!r} is not {BANK_SCHEMA} (a bank/2 or older artifact "
                              "lacks the D8 fields and is refused)")
        for k in TOP_FIELDS:
            _field(doc, k, "")
        if "engine_sha256" in doc:
            raise ObsLawError("bank artifact: a top-level engine_sha256 is refused in bank/3 (the bank executable is "
                              "fit.noise.engine_sha256; v5 2.8)")
        if doc["status"] != STATUS_FITTED:
            raise ObsLawError(f"bank artifact: status {doc['status']!r} is not {STATUS_FITTED}")
        if type(doc["synthetic"]) is not bool:
            raise ObsLawError("bank artifact: synthetic must be true or false")
        if doc["synthetic"] and not allow_synthetic:
            raise ObsLawError("bank artifact: synthetic: true is refused (test flag --allow-synthetic-bank only)")
        if doc["support_law"] != material.SUPPORT_LAW:
            raise ObsLawError(f"bank artifact: support_law {doc['support_law']!r} is not {material.SUPPORT_LAW}")
        if doc["age_clock"] != material.age_clock_identity():
            raise ObsLawError("bank artifact: age_clock differs from material.age_clock_identity() (stale)")
        if doc["cohort"] != material.registered_ages():
            raise ObsLawError("bank artifact: cohort differs from material.registered_ages()")
        if doc["cohort_sha256"] != material.AGES_SHA256:
            raise ObsLawError("bank artifact: cohort_sha256 is not the registered ages sha256")
        inputs = doc["inputs"]
        for k in INPUT_KEYS:
            _sha_field(inputs, k, "inputs")
        for k, v in REGISTERED_INPUTS.items():
            if inputs[k] != v:
                raise ObsLawError(f"bank artifact: inputs.{k} is not the registered {v[:8]}...")
        fit = doc["fit"]
        for k in FIT_FIELDS:
            _field(fit, k, "fit")
        if fit["noise_likelihood"] != NOISE_LIKELIHOOD:
            raise ObsLawError(f"bank artifact: fit.noise_likelihood is not {NOISE_LIKELIHOOD}")
        noise = fit["noise"]
        for k in FIT_NOISE_SHAS:
            _sha_field(noise, k, "fit.noise")
        if noise["inputs_sha256"] != rqlib.canonical_sha(inputs):           # (v5 2.8 L755)
            raise ObsLawError("bank artifact: fit.noise.inputs_sha256 is not the canonical sha256 of the inputs block")
        BankArtifact._bootstrap_streams(_field(_field(fit, "streams", "fit"), "bootstrap", "fit.streams"))
        d8 = doc["d8"]
        for k in D8_FIELDS:
            _field(d8, k, "d8")
        if not rqlib.is_sha256(d8["amendment_sha256"]) or d8["amendment_sha256"] != D8_SHA256:
            raise ObsLawError("bank artifact: d8.amendment_sha256 is not amendment D8 v2's sha256")
        if d8["capture_law"] != CAPTURE_LAW:
            raise ObsLawError(f"bank artifact: d8.capture_law is not {CAPTURE_LAW}")
        if not (_int(d8["denominator"]) and d8["denominator"] == SURV_N):
            raise ObsLawError(f"bank artifact: d8.denominator is not {SURV_N}")
        if d8["max_age"] != material.registered_ages()["max_age"]:
            raise ObsLawError("bank artifact: d8.max_age is not the registered cohort's")
        for k, v in D8_TEXTS.items():
            if d8[k] != v:
                raise ObsLawError(f"bank artifact: d8.{k} is not v5 2.8's text {v!r}")
        for k in NOISE_FIELDS:
            _field(doc["noise"], k, "noise")
        mv = doc["map_variance"]
        for k in MAP_VARIANCE_FIELDS:
            _field(mv, k, "map_variance")
        if not isinstance(mv["rule"], str) or not mv["rule"]:
            raise ObsLawError("bank artifact: map_variance.rule must be a non-empty string")
        if mv["consumer"] != MAP_VARIANCE_CONSUMER:
            raise ObsLawError(f"bank artifact: map_variance.consumer is not {MAP_VARIANCE_CONSUMER!r}")
        BankArtifact._estimator(doc["estimator"])
        BankArtifact._horizons(doc["horizons"])

    @staticmethod
    def _bootstrap_streams(boot):
        """fit.streams.bootstrap (v5 2.8 L745; 2.5 item 5 L630-647): the generator and namespace; texts = the refit
        streams AnnexH/D8/1/noisebank/D8-refit/h<h>/bootstrap, one per horizon (any order, no duplicate); seeds = one
        unsigned 64-bit integer per text, each the text's derived seed (first eight SHA-256 bytes, little-endian)."""
        where = "fit.streams.bootstrap"
        for k in BOOTSTRAP_FIELDS:
            _field(boot, k, where)
        if boot["generator"] != STREAM_GENERATOR or boot["namespace"] != STREAM_NAMESPACE:
            raise ObsLawError(f"bank artifact: {where} must be {STREAM_GENERATOR} under {STREAM_NAMESPACE}")
        texts, seeds = boot["texts"], boot["seeds"]
        if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
            raise ObsLawError(f"bank artifact: {where}.texts must be a list of stream texts")
        want = sorted(REFIT_TEXT.format(h) for h in HORIZON_KEYS)
        if sorted(texts) != want:
            raise ObsLawError(f"bank artifact: {where}.texts must be exactly the refit streams {want} "
                              "(one per horizon)")
        if not isinstance(seeds, list) or len(seeds) != len(texts) or \
                not all(_int(s) and 0 <= s < 1 << 64 for s in seeds):
            raise ObsLawError(f"bank artifact: {where}.seeds must be a list of unsigned 64-bit integers, one per text")
        for t, s in zip(texts, seeds):
            if s != stream_seed_d8(t):
                raise ObsLawError(f"bank artifact: {where}.seeds: {s} is not the derived seed of {t!r}")

    @staticmethod
    def _estimator(est):
        """estimator (v5 2.8 L750): an object with the existing record's fields and ceilings, saturation,
        capped_category (their internal structure is not fixed by v5: presence only), and the two values v5 2.5
        fixes (multi_start 16, boot 999)."""
        if not isinstance(est, dict):
            raise ObsLawError("bank artifact: estimator must be an object")
        for k in ESTIMATOR_FIELDS:
            _field(est, k, "estimator")
        for k, v in ESTIMATOR_VALUES.items():
            if not (_int(est[k]) and est[k] == v):
                raise ObsLawError(f"bank artifact: estimator.{k} {est[k]!r} is not the registered {v}")

    @staticmethod
    def _horizons(hz):
        """horizons (v5 2.8 L751): one record per horizon 5000, 10000, 20000, each with the fields every record
        carries as now; status a string, 'ok' at 5000 (R7: a d8-fitted artifact's 5k fit is ok), 'ok' or
        'unavailable' at 10k/20k (2.6); with status ok the groups, grid_validation, components and bootstrap
        records; capture_bound = noisebank.capture_bound(h); reasons a list."""
        if not isinstance(hz, dict):
            raise ObsLawError("bank artifact: horizons must be an object")
        for h in HORIZON_KEYS:
            rec = _field(hz, h, "horizons")
            where = f"horizons.{h}"
            for k in HORIZON_FIELDS:
                _field(rec, k, where)
            st = rec["status"]
            if st not in HORIZON_STATUSES or (h == HORIZON_KEYS[0] and st != "ok"):
                raise ObsLawError(f"bank artifact: {where}.status {st!r} is refused "
                                  + ("(a d8-fitted artifact's 5k fit is ok, R7)" if h == HORIZON_KEYS[0] else
                                     f"(one of {HORIZON_STATUSES})"))
            if st == "ok":
                for k in HORIZON_OK_FIELDS:
                    _field(rec, k, where)
                for k in ("components", "bootstrap"):
                    if not isinstance(rec[k], dict):
                        raise ObsLawError(f"bank artifact: {where}.{k} must be an object when the status is ok")
            cb = rec["capture_bound"]
            if not (_int(cb) and cb == noisebank.capture_bound(int(h))):
                raise ObsLawError(f"bank artifact: {where}.capture_bound {cb!r} is not "
                                  f"noisebank.capture_bound({h}) = {noisebank.capture_bound(int(h))}")
            if not isinstance(rec["reasons"], list):
                raise ObsLawError(f"bank artifact: {where}.reasons must be a list")

    @staticmethod
    def _scalars(doc):
        nz, d8 = doc["noise"], doc["d8"]
        for where, v in (("horizon", doc["horizon"]), ("noise.horizon", nz["horizon"])):
            if not (_int(v) and v == HORIZON):
                raise ObsLawError(f"bank artifact: {where} {v!r} is not the integer {HORIZON}")
        if not (_num(doc["dt"]) and doc["dt"] == DT):
            raise ObsLawError(f"bank artifact: dt {doc['dt']!r} is not {DT}")
        ce = d8["ceilings"]
        if not isinstance(ce, dict) or set(ce) != set(CEILINGS) or any(not _int(ce[k]) or ce[k] != v
                                                                       for k, v in CEILINGS.items()):
            raise ObsLawError(f"bank artifact: d8.ceilings is not {CEILINGS}")
        computed = material.cohort_ceiling(material.registered_ages(), HORIZON, DT)   # (#90's clock, at every load)
        for where, v in (("survivor_ceiling", doc["survivor_ceiling"]), ("noise.survivor_ceiling", nz["survivor_ceiling"]),
                         ('d8.ceilings["5000"]', ce["5000"])):
            if not (_int(v) and v == SURVIVOR_CEILING == computed):
                raise ObsLawError(f"bank artifact: {where} {v!r}, the registered {SURVIVOR_CEILING} and the clock's "
                                  f"material.cohort_ceiling {computed!r} must agree")
        cb = nz["capture_bound"]
        if not (_int(cb) and cb == CAPTURE_BOUND == noisebank.capture_bound(HORIZON)):
            raise ObsLawError(f"bank artifact: noise.capture_bound {cb!r} is not {CAPTURE_BOUND} "
                              f"(= noisebank.capture_bound({HORIZON}))")
        if nz["available"] is not True:
            raise ObsLawError("bank artifact: noise.available is not true")

    def law(self, ch):
        if ch == "C":
            return CAPTURE_BOUND, CAPTURE_BOUND
        if ch in ("S", "F"):
            return SURV_N, self.M_H
        raise ObsLawError(f"channel {ch!r}")


class BankObservationModel:
    """The bank/D8 observation model of bank-mode recovery: a validated bank/3 artifact and its tables (v5 3.1,
    4.2). bank_sha256 / tables_sha256 / tables_content_sha256: the configured identities (None at the first,
    establishing load); gammas: every noise multiplier a scheduled scenario uses; allow_synthetic_bank: the
    test-only flag (the model is then never accepting)."""

    def __init__(self, bank, tables, *, bank_sha256=None, tables_sha256=None, tables_content_sha256=None,
                 gammas=(1.0,), allow_synthetic_bank=False):
        self.bank = BankArtifact(bank, sha256=bank_sha256, allow_synthetic=allow_synthetic_bank)
        self.tables = ObsTables.load(tables, sha256=tables_sha256)          # 7.
        self.allow_synthetic_bank = bool(allow_synthetic_bank)
        self.accepting = not self.allow_synthetic_bank
        self.gammas = sorted({float(g) for g in gammas})
        self._check_tables(tables_content_sha256)
        self.factors = self.bank.factors
        self.nu0_C = self.bank.nu0_C
        self.M_H = self.bank.M_H
        self.c_H = self.M_H / SURV_N
        self.identity_sha = rqlib.canonical_sha(self.identity())

    def _check_tables(self, content_sha256):
        t, b = self.tables, self.bank
        got = t.stored_content_sha256
        if content_sha256 is not None and got != content_sha256:
            raise ObsLawError(f"observation tables: content sha256 {got} differs from the configured {content_sha256}")
        impl, nsc = implementation_sha256(), noisescale_sha256()
        ident = t.identity()
        if t.bank_sha256 != b.sha256:
            raise ObsLawError("observation tables: built from another bank artifact (bank_artifact_sha256)")
        for k in [ident] + ident["location"] + [ident["fitter"]]:
            if k.get("bank_artifact_sha256") != b.sha256:
                raise ObsLawError("observation tables: a table of another bank artifact")
            if k.get("obslaw_sha256") != impl:
                raise ObsLawError("observation tables: built by another obslaw implementation (obslaw_sha256)")
            if k.get("noisescale_sha256") != nsc:
                raise ObsLawError("observation tables: built with another noisescale evaluator (noisescale_sha256)")
        for (ch, g), lt in t.location.items():
            N, M = b.law(ch)
            want = location_identity(b.s_logit[ch], ch, g, N, M, lt.identity.get("h"), b.sha256)
            hs = {LOC_H0 / 2 ** k for k in range(LOC_HALVINGS + 1)}
            if lt.identity != want or lt.identity.get("h") not in hs:
                raise ObsLawError(f"observation tables: location table {ch}/{g} identity differs from this bank, "
                                  "channel law, curve, grid rule or tolerances")
            if not np.array_equal(lt.x, location_nodes(want["knots_x"], want["h"])):
                raise ObsLawError(f"observation tables: location table {ch}/{g} nodes are not the grid rule's")
        for g in self.gammas:
            for ch in CHANNELS:
                if (ch, g) not in t.location:
                    raise ObsLawError(f"observation tables: no location table for channel {ch} at gamma {g}")
        if t.fitter.identity != fitter_identity(b.s_logit["C"], b.sha256):
            raise ObsLawError("observation tables: the fitter table's identity differs from this bank, curve, "
                              "node rule, tolerances or caps")
        if not np.all(np.isin(fitter_initial_nodes(b.s_logit["C"]), t.fitter.x)):
            raise ObsLawError("observation tables: the fitter table lacks initial nodes of the v5 rule")

    # ---------------------------------------------------------------- what generation and the fitter use
    def law(self, ch):
        return self.bank.law(ch)

    def s(self, ch, mu, gamma=1.0):
        return scale(self.bank.s_logit[ch], mu, gamma)

    def location_table(self, ch, gamma):
        key = (ch, float(gamma))
        if key not in self.tables.location:
            raise ObsLawError(f"no location table for channel {ch} at gamma {gamma}")
        return self.tables.location[key]

    def counts(self, ch, mu, u, gamma=1.0, x=None):
        """The capped counts of one channel (v5 1.6) -> (K, location, scale)."""
        N, M = self.law(ch)
        tab = self.location_table(ch, gamma)
        xs = None if x is None else np.asarray(x, float).ravel()
        return generate_counts(mu, u, N, M, lambda m: self.s(ch, m, gamma),
                               lambda m, i: tab.locate(m, None if xs is None else xs[i]))

    def generate(self, rng, qi, pj, nQ, nP, mu, gamma=1.0, reps=6, x=None):
        """One dataset's observations (v5 1.4-1.6) from the observation stream rng (recovery: default_rng([seed,
        3])): mu = {"C": (|E|,), "S": (|E|,), "F": (nQ,)} intended means, x optionally the exact axes. Means are
        checked before any draw. -> {"counts": {C, S, F}, "loc": {...}, "scale": {...}}."""
        x = x or {}
        nE = len(qi)
        for ch, n in (("C", nE), ("S", nE), ("F", nQ)):
            if np.asarray(mu[ch]).shape != (n,):
                raise ObsLawError(f"generate: mu[{ch}] must have shape ({n},)")
            check_means(mu[ch], *self.law(ch), what=f"mean {ch}")
            self.location_table(ch, gamma)
        u = latent(standard_normals(rng, nQ, nP, nE, reps), self.factors, qi, pj)
        out = {"counts": {}, "loc": {}, "scale": {}}
        for ch in CHANNELS:
            K, loc, sc = self.counts(ch, mu[ch], u[ch], gamma, x.get(ch))
            out["counts"][ch], out["loc"][ch], out["scale"][ch] = K, loc, sc
        return out

    def working_var_fn(self):
        """W (v5 1.7b): p -> W(logit p), tagged with this model's identity."""
        return WorkingVariance(self.tables.fitter, self.identity_sha)

    def score_law(self):
        """(A, L) (v5 1.7b, 3.3): p -> (A, L)(logit p), tagged with this model's identity."""
        return ScoreLaw(self.tables.fitter, self.identity_sha)

    def identity(self):
        """What a configuration binds of this model (v5 4.1; the recovery tool adds mode, noise_source, D9, streams)."""
        d = self.bank.doc
        return {"bank_artifact_sha256": self.bank.sha256, "bank_schema": BANK_SCHEMA, "status": d["status"],
                "synthetic": d["synthetic"], "allow_synthetic_bank": self.allow_synthetic_bank,
                "accepting": self.accepting, "obs_tables_sha256": self.tables.file_sha256,
                "obs_tables_content_sha256": self.tables.stored_content_sha256,
                "tables_identity": self.tables.identity(),
                "support_law": d["support_law"], "capture_law": d["d8"]["capture_law"], "age_clock": d["age_clock"],
                "survivor_ceiling": d["survivor_ceiling"], "cohort_sha256": d["cohort_sha256"],
                "amendment_D8_sha256": d["d8"]["amendment_sha256"], "inputs": d["inputs"],
                "noise_engine_sha256": d["fit"]["noise"]["engine_sha256"],
                "parameters_sha256": rqlib.canonical_sha({"noise": d["noise"], "map_variance": d["map_variance"]}),
                "receipt_sha256": d["fit"]["noise"]["receipt_sha256"],
                "fitter": {"var_fn": "W", "rep_prior": "nu0_C", "score_law": "A,L"},
                "obslaw_sha256": implementation_sha256(), "noisescale_sha256": noisescale_sha256(), "design": DESIGN}

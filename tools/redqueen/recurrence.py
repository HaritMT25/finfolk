#!/usr/bin/env python3
"""recurrence.py: H-F, reciprocal temporal recurrence (Annex H.3; design v4 §8.3; (d) item 5, part 3),
and the per-world, per-epoch recurrence quantities that H-T uses (transition.py). numpy; deterministic.

RESPONSES AND METRIC (H.3.1). Replicate-mean native responses: capture Y^C = sum C / sum B, survival
Y^Q = sum L / 600R - sum L0 / 600R. V is the bank covariance of those means, given as a Cov: a
structured diag(d) + U U' (the shared-source loadings: prey construction, predator draws, reference
sources; Woodbury solves) or a small dense matrix. W = (V + 1e-8 median(diag V) I)^-1. A zero or
invalid V is an input failure.

PROJECTION (H.3.2). Within-world nuisance: per world and readout the full 6x6 tensor of the H.1 cubic
B-splines in the prey and predator times (36 columns, the scope's own interval: full history [0, 200]M,
an epoch its nominal bounds, "newly scaled"). Reference-panel nuisance: a common six-basis trend plus a
sum-to-zero intercept per reference (9 columns). P_X = X (X'WX)^- X'W, M_X = I - P_X. A period P adds a
harmonic H_P: on the lag t_j - t_i within a world, on the focal time t on a reference panel. By
Frisch-Waugh-Lovell (exact): q = H'W M_X y, S = H'W M_X H, a = S^-1 q (the joint-refit harmonic
coefficients), J = (RSS_0 - RSS_1) / 2 = q'S^-1 q / 2 (dimensionless), the post-refit recurrent
component Delta = M_X H a (= full refit minus nuisance-only fit).

PERIODS AND SUPPORT (H.3.3). Full history {4..20} U {25..100 by 5} M (33); an epoch {4..20} M (17: the
25M candidate is dropped PROVISIONALLY, see EPOCH_PERIODS).
A candidate is supported for a world only when ALL SIX rules hold, for both readouts:
  1 both guilds' within-world source-time spans >= 2P (one engine step, 1e-6 M, of tolerance, here and
    in rule 2's span only);
  2 each of the four reference series spans >= 2P, has >= 9 distinct times and no interior gap > P/4;
  3 every time used in a reversal window has all four references measured (the windows use only the
    common times);
  4 the within-world lag phases 2 pi (t_j - t_i) / P cover the circle with no gap > pi/2 (+1e-10);
  5 M_X H_P has rank two, within the world and on the reference panel: its smaller / larger singular
    value >= 1e-10 (Annex H's metric: the singular values of the n x 2 matrix M_X H_P itself, from its
    QR factor; the fit then works in that orthonormal basis, never inverting H'W M_X H);
  6 PHASE-CONDITIONAL (the coordinator's pre-seal decision, 2026-11-07): the five-window chain of H.3.5
    can be constructed AT THE FITTED PHASE of each readout's reference panel. A candidate whose chain
    exists only for some phases (the full-history 90-100M candidates on the real graph; the epoch
    25M candidate, dropped) is supported exactly when its fitted phase admits the chain. The SAME
    rule, in this same code, decides support inside every calibration null panel (calib.py calls
    analyze_world), and every result reports, per world, how many candidates were phase-conditional
    and how many of those the fitted phase supported (phase_support).
Also unsupported: a zero capture denominator (H.3.6). An unsupported candidate is excluded from that
world's search, never shortened or interpolated; a world without any supported candidate makes the
decision unavailable.

STATISTIC (H.3.4). s_w(P) = G_Cw(P) G_Qw(P) min{J_Cw(P), J_Qw(P)}; per world the maximum over its
supported candidates (ties: the smaller period; all zero: "no supported reciprocal selection", zero
contribution); S_F = the mean over all n worlds.

REVERSAL / RETURN GATE (H.3.5). On the reference panel: phi = atan2(b, a) of the harmonic coefficients
(A = 0 fails); centres c_k = (phi + k pi) / omega; the EARLIEST k whose five windows {t: |t - c| <= P/8}
(clipped to the scope) all contain common measured times (never searched for the best result);
v_j = the plain mean over the window's times of the four-reference average of y - (nuisance-only fit);
e_j = cos(omega c - phi) = +-1; reversals (e_{j+1} - e_j)(v_{j+1} - v_j) > 0 for j = 0..3; returns
|v2 - v0|, |v3 - v1|, |v4 - v2| <= R_fit / 2, R_fit = the range over the common times of the
four-reference average Delta. G = 1 exactly when all pass.

MATERIAL (H.3.6). r_C = RMS_t(avg Delta_C) / mean_{t,r} Y^C (relative), r_Q = RMS_t(avg Delta_Q)
(absolute); E_h = (1/n) sum_w g_w r_hw(P_w)^2, R_h = sqrt(E_h) over all n worlds; operational
materiality R_C >= 0.10 and R_Q >= 0.04. The material-boundary statistic (calibrated under F0-F4, H.11)
is M_F = min(R_C / 0.10, R_Q / 0.04) (> 1 exactly when both estimates exceed their thresholds).

DECISIONS (H.3.7). Detection S_F > c_F and p_F <= 0.01; operational success = detection and both
materiality estimates; exceeding material = operational and M_F > c_M, p_M <= 0.01, R_C > 0.10,
R_Q > 0.04.
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

import backbone  # noqa: E402

FULL_PERIODS = tuple(float(p) for p in list(range(4, 21)) + list(range(25, 101, 5)))
# The epoch candidate periods (H.3.3). P = 25M (two cycles in a 50M epoch) is the only epoch period whose
# five-window chain is phase-conditional (rule 6); on the real g4 graph its fitted phase fails the chain in
# 27-32 of the 32 worlds in every epoch, which made E^U = +inf in every epoch and H-T unreachable. PROVISIONAL
# (the coordinator, 2026-11-08, pending Codex): dropped from BOTH sides of the epoch analysis (S_e and the
# epoch gates, E^F, E^U, the H-T generator's period grid), so nothing detectable in an epoch is uncertifiable:
# within-epoch recurrence is claimed at periods <= 20M; slower recurrence is H-F's (full history, to 100M).
# Restoring it is this one line: + [25].
EPOCH_PERIODS = tuple(float(p) for p in range(4, 21))
EPOCH_EXCLUDED = (25.0,)          # (reported in every coverage summary; restore with the line above)
SCOPES = {"full": (0.0, 200.0), "E1": (0.0, 50.0), "E2": (75.0, 125.0), "E3": (150.0, 200.0)}
PERIODS = {"full": FULL_PERIODS, "E1": EPOCH_PERIODS, "E2": EPOCH_PERIODS, "E3": EPOCH_PERIODS}
SPAN_TOL = 1e-6          # one engine step: the two-cycle span comparisons only
RANK_TOL = 1e-10
PHASE_TOL = 1e-10
CLAMP_TOL = 1e-10
WIN_EPS = 1e-9           # closed windows |t - c| <= P/8 (M; float safety only)
BP_TOL = 1e-7            # a phase this close (in M of window centre) to a window-boundary crossing: scalar chain()
RIDGE = 1e-8
D_C, D_Q = 0.10, 0.04
TRIALS = 600


class RecurrenceError(Exception):
    pass


def scope_bounds(scope):
    return SCOPES[scope] if isinstance(scope, str) else (float(scope[0]), float(scope[1]))


def _chol(A):
    try:
        return np.linalg.cholesky(A)
    except np.linalg.LinAlgError as e:
        raise RecurrenceError(f"the bank covariance is not positive definite: {e}") from None


def _chol_solve(L, B):
    return np.linalg.solve(L.T, np.linalg.solve(L, B))


# ================================================================== the bank metric
class Cov:
    """The bank covariance of the replicate means: diag(d) + U U' (structured; U the shared-source
    loadings, n x k) or a dense matrix. W = (V + 1e-8 median(diag V) I)^-1."""

    def __init__(self, d=None, U=None, dense=None):
        if dense is not None:
            V = np.array(dense, float)
            if V.ndim != 2 or V.shape[0] != V.shape[1]:
                raise RecurrenceError("a dense covariance must be square")
            self.n, self.V, self.d, self.U = len(V), V, None, None
            diag = np.diag(V).copy()
        else:
            self.d = np.array(d, float).ravel()
            self.n = len(self.d)
            self.U = None if U is None else np.array(U, float).reshape(self.n, -1)
            self.V = None
            diag = self.d + (np.sum(self.U ** 2, axis=1) if self.U is not None else 0.0)
        if self.n == 0 or not np.all(np.isfinite(diag)) or np.any(diag < 0) or not np.any(diag > 0):
            raise RecurrenceError("the bank covariance is zero or invalid (an input failure)")
        self.diag = diag
        ridge = RIDGE * float(np.median(diag))
        if self.V is not None:
            if not np.all(np.isfinite(self.V)):
                raise RecurrenceError("the bank covariance is not finite")
            self.L = _chol(self.V + ridge * np.eye(self.n))
        else:
            dd = self.d + ridge
            if np.any(dd <= 0):
                raise RecurrenceError("a structured bank covariance needs a positive cell diagonal")
            self.dinv = 1.0 / dd
            self._M = None                               # (the Woodbury factor: built on first use, q33)
            if self.U is None or not self.U.shape[1]:
                self.U = None

    @property
    def M(self):
        """W A = D^-1 A - M (U' D^-1 A): built once, when first needed (a bank only subset never pays)."""
        if self._M is None:
            DU = self.U * self.dinv[:, None]
            Kc = _chol(np.eye(self.U.shape[1]) + self.U.T @ DU)
            Ki = _chol_solve(Kc, np.eye(Kc.shape[0]))
            self._M = DU @ ((Ki + Ki.T) / 2)
        return self._M

    def subset(self, mask):
        mask = np.asarray(mask, bool)
        if mask.all():                                   # (the whole bank: no refactorization)
            return self
        if self.V is not None:
            return Cov(dense=self.V[np.ix_(mask, mask)])
        return Cov(self.d[mask], None if self.U is None else self.U[mask])

    def wmul(self, A):
        """W A."""
        A = np.asarray(A, float)
        one = A.ndim == 1
        A2 = A.reshape(self.n, -1)
        if self.V is not None:
            out = _chol_solve(self.L, A2)
        else:
            out = A2 * self.dinv[:, None]
            if self.U is not None:
                out = out - self.M @ (self.U.T @ out)
        return out.ravel() if one else out


# ================================================================== Frisch-Waugh-Lovell
class Harmonic:
    """One period's operators in a STABLE basis (#68 review 4). MH = M_X H (n x 2); rule 5 on its
    singular values (the registered rank metric: s_min / s_max >= 1e-10, unweighted), computed from the
    triangular factor of the thin QR MH = Q R (Householder: backward stable). Fitting never inverts
    H'W M_X H: with WQ = W Q and the 2 x 2 positive-definite Sq = Q'W Q (its condition is W's on the
    plane, whatever MH's), for any y: c = WQ'y (= Q'W M_X y, since W M_X = M_X'W and M_X Q = Q),
    b = Sq^-1 c, J = c'b / 2 (= q'S^-1 q / 2, basis-free), Delta = Q b (= M_X H a), a = R^-1 b."""

    def __init__(self, MH, Q, R, WQ, sv):
        self.MH, self.Q, self.R, self.WQ = MH, Q, R, WQ
        self.sv = sv
        self.ratio = float(sv[1] / sv[0]) if sv[0] > 0 else 0.0
        self.rank2 = bool(np.isfinite(self.ratio) and self.ratio >= RANK_TOL)
        self.Sqinv = self.Rinv = None
        if self.rank2:
            Sq = Q.T @ WQ
            Sq = (Sq + Sq.T) / 2
            self.Sqinv = np.linalg.solve(Sq, np.eye(2))
            self.Sqinv = (self.Sqinv + self.Sqinv.T) / 2
            self.Rinv = np.linalg.solve(R, np.eye(2))
        self._aop = self._dbar = None
        self.avgQ = None                     # (a reference design's: the four-reference average of Q)

    @property
    def dbar(self):
        """y -> the four-reference average Delta (n_t x n; a reference design's harmonic)."""
        if self._dbar is None:
            self._dbar = self.avgQ @ self.Sqinv @ self.WQ.T
        return self._dbar

    @property
    def S(self):
        """H'W M_X H (= MH'W MH = R'Sq R), for checks."""
        S = self.R.T @ (self.Q.T @ self.WQ) @ self.R
        return (S + S.T) / 2

    def coords(self, y):
        """-> (c, b) for one response vector, or (2, ...) arrays for a matrix of them."""
        c = self.WQ.T @ y
        return c, self.Sqinv @ c

    def score(self, y):
        """J alone (the within-world readout: no n-vector is formed)."""
        c, b = self.coords(y)
        return _clamp(0.5 * float(c @ b))

    def fit(self, y):
        """-> (a (2,), J, Delta = M_X H a)."""
        c, b = self.coords(y)
        return self.Rinv @ b, _clamp(0.5 * float(c @ b)), self.Q @ b

    @property
    def aop(self):
        """y -> a (2 x n)."""
        if self._aop is None:
            self._aop = self.Rinv @ self.Sqinv @ self.WQ.T
        return self._aop


def _clamp(J):
    if J < 0:
        if J < -CLAMP_TOL:
            raise RecurrenceError(f"a negative recurrence score J = {J} (an implementation failure)")
        return 0.0
    return J


class Projector:
    """A fixed nuisance X and the bank metric: everything that does not depend on y."""

    def __init__(self, X, cov):
        self.X, self.cov = X, cov
        self.WX = cov.wmul(X)
        A = X.T @ self.WX
        self.Ginv = np.linalg.pinv((A + A.T) / 2, rcond=1e-12, hermitian=True)

    def null_fit(self, y):
        return self.X @ (self.Ginv @ (self.WX.T @ y))

    def harmonic(self, H):
        return self.harmonics([H])[0]

    def harmonics(self, Hs=None, H=None):
        """Every period's Harmonic in one pass (one nuisance projection, one batched QR, one Woodbury
        solve for all periods: #68 / q33's batching; identical operators to the per-period route).
        Hs: the periods' n x 2 matrices, or H: them stacked (n x 2M)."""
        if H is None:
            if not Hs:
                return []
            H = np.hstack(Hs)                                      # n x 2M
        n, M = self.X.shape[0], H.shape[1] // 2
        if M == 0:
            return []
        MH = H - self.X @ (self.Ginv @ (self.WX.T @ H))
        MH3 = MH.reshape(n, M, 2).transpose(1, 0, 2)               # M x n x 2
        Q3, R3 = np.linalg.qr(MH3)
        sv = np.linalg.svd(R3, compute_uv=False)                   # M x 2 (descending)
        WQ = self.cov.wmul(Q3.transpose(1, 0, 2).reshape(n, 2 * M)).reshape(n, M, 2)
        return [Harmonic(MH3[m], Q3[m], R3[m], WQ[:, m, :], sv[m]) for m in range(M)]

    def joint_fit(self, y, H):
        """The full refit [X, H] in the W metric (an independent route, for the FWL check)."""
        Z = np.hstack([self.X, H])
        WZ = self.cov.wmul(Z)
        coef = np.linalg.pinv(Z.T @ WZ, rcond=1e-12, hermitian=True) @ (WZ.T @ y)
        return Z @ coef, coef[-H.shape[1]:]


def harmonic_matrix(x, P):
    w = 2 * math.pi / P
    return np.column_stack([np.cos(w * x), np.sin(w * x)])


def tensor_basis(ti, tj, interval):
    Bi = backbone.basis(ti, interval)
    Bj = backbone.basis(tj, interval)
    return (Bi[:, :, None] * Bj[:, None, :]).reshape(len(ti), 36)


# ================================================================== support helpers
def two_cycles(span, P):
    return span >= 2 * P - SPAN_TOL


def quadrants_ok(lags, P):
    """Rule 4: the lag phases cover the circle with no circular gap > pi/2."""
    if len(lags) == 0:
        return False
    ph = np.sort(np.mod(2 * math.pi * np.asarray(lags, float) / P, 2 * math.pi))
    gaps = np.diff(np.concatenate([ph, [ph[0] + 2 * math.pi]]))
    return float(gaps.max()) <= math.pi / 2 + PHASE_TOL


def series_ok(times, P):
    """Rule 2 for one reference series (times within the scope)."""
    ts = np.unique(np.asarray(times, float))
    if len(ts) < 9 or not two_cycles(ts[-1] - ts[0], P):
        return False
    return float(np.max(np.diff(ts))) <= P / 4 + 1e-12


def chain(times, L, U, P, phi):
    """The EARLIEST five-window chain at phase phi over the sorted common times in [L, U] -> (k, [(lo,
    hi)] index ranges into times) or None. Centres c_m = (phi + m pi) / omega; window |t - c| <= P/8."""
    times = np.asarray(times, float)
    if len(times) == 0 or not math.isfinite(phi):
        return None
    w = 2 * math.pi / P
    k0 = math.floor((w * L - phi) / math.pi) - 1
    k1 = math.ceil((w * U - phi) / math.pi) + 1
    m = np.arange(k0, k1 + 1)
    c = (phi + m * math.pi) / w
    h = P / 8 + WIN_EPS
    lo = np.searchsorted(times, c - h, "left")
    hi = np.searchsorted(times, c + h, "right")
    cov = hi > lo
    if len(cov) < 5:
        return None
    ok = np.flatnonzero(cov[:-4] & cov[1:-3] & cov[2:-2] & cov[3:-1] & cov[4:])
    if not len(ok):
        return None
    i = int(ok[0])
    return int(m[i]), [(int(lo[i + j]), int(hi[i + j])) for j in range(5)]


def gate(v, e, R_fit):
    """-> (reversals pass, returns pass) for five window means v and extremum signs e."""
    rev = all((e[j + 1] - e[j]) * (v[j + 1] - v[j]) > 0 for j in range(4))
    ret = all(abs(v[j + 2] - v[j]) <= R_fit / 2 for j in range(3))
    return rev, ret


class ChainTable:
    """chain() tabulated over the phase, for vectorized bootstrap draws: the window structure depends on
    u = (phi / omega) mod (P/2) only through finitely many segments between the window-boundary
    crossings u = (t +- (P/8 + eps)) mod (P/2); each segment holds (k relative to u, windows) or None.
    AT a crossing the closed window holds the boundary time (membership differs from both open
    sides): a phase within BP_TOL of a crossing is decided by the scalar chain() itself (#68 review 7),
    so the table and chain() agree at every phase."""

    def __init__(self, times, L, U, P):
        self.times, self.P, self.L, self.U = np.asarray(times, float), P, L, U
        half = P / 2
        h = P / 8 + WIN_EPS
        bp = np.sort(np.mod(np.concatenate([self.times - h, self.times + h]), half)) if len(times) else np.array([0.0])
        bp = bp[np.concatenate([[True], np.diff(bp) > 1e-12])]
        self.bp = bp
        # segment i = [bp_i, bp_i+1); the last one wraps: [bp_-1, bp_0 + P/2) (u < bp_0 is read as u + P/2)
        reps = [(bp[i] + bp[i + 1]) / 2 for i in range(len(bp) - 1)] + [(bp[-1] + bp[0] + half) / 2]
        self.k = np.full(len(reps), -10 ** 9, dtype=np.int64)
        self.lo = np.zeros((len(reps), 5), dtype=np.int64)
        self.hi = np.zeros((len(reps), 5), dtype=np.int64)
        self.ok = np.zeros(len(reps), bool)
        w = 2 * math.pi / P
        for i, u in enumerate(reps):
            ch = chain(self.times, L, U, P, w * u)
            if ch is not None:
                self.ok[i] = True
                self.k[i] = ch[0]
                self.lo[i] = [a for a, _ in ch[1]]
                self.hi[i] = [b for _, b in ch[1]]

    def lookup(self, phi):
        """phi (B,) -> (window starts (B, 5), window ends (B, 5), the draw's k (B,), feasible (B,)): index
        ranges into the common times, exactly chain()'s (near a crossing: chain() itself)."""
        P, half = self.P, self.P / 2
        phi = np.atleast_1d(np.asarray(phi, float))
        s = np.where(np.isfinite(phi), phi, 0.0) / (2 * math.pi / P)     # (a nonfinite phase: chain() below)
        u = np.mod(s, half)
        u = np.where(u < self.bp[0], u + half, u)                 # (the wrapping segment)
        q = np.rint((s - u) / half).astype(np.int64)
        seg = np.searchsorted(self.bp, u, "right") - 1
        lo, hi, k, ok = self.lo[seg].copy(), self.hi[seg].copy(), self.k[seg] - q, self.ok[seg].copy()
        nxt = np.where(seg + 1 < len(self.bp), self.bp[np.minimum(seg + 1, len(self.bp) - 1)], self.bp[0] + half)
        near = (np.minimum(u - self.bp[seg], nxt - u) <= BP_TOL) | ~np.isfinite(phi)
        for b in np.flatnonzero(near):
            ch = chain(self.times, self.L, self.U, P, float(phi[b]))
            ok[b] = ch is not None
            if ch is not None:
                k[b] = ch[0]
                lo[b] = [x for x, _ in ch[1]]
                hi[b] = [y for _, y in ch[1]]
        return lo, hi, k, ok

    def at(self, phi):
        """The scalar chain at one phase, (k, [(lo, hi)]) or None: chain()'s result through the table."""
        lo, hi, k, ok = self.lookup([phi])
        if not ok[0]:
            return None
        return int(k[0]), [(int(a), int(b)) for a, b in zip(lo[0], hi[0])]


_TABLES = {}


def chain_table(times, L, U, P):
    """ChainTable, cached by (times, scope, period): it depends on the measured times only (the graph),
    so calibration panels on one graph share it."""
    key = (np.asarray(times, float).tobytes(), float(L), float(U), float(P))
    if key not in _TABLES:
        if len(_TABLES) > 50000:
            _TABLES.clear()
        _TABLES[key] = ChainTable(times, L, U, P)
    return _TABLES[key]


# ================================================================== graph geometry (cached)
_GEO = {}


def _cached(key, build):
    """Everything about a design that depends on the measured times only (the graph), never on the
    covariance or the responses, is built once and shared (calibration panels on one graph; q33)."""
    g = _GEO.get(key)
    if g is None:
        if len(_GEO) > 512:
            _GEO.clear()
        g = _GEO[key] = build()
    return g


def within_geometry(ti, tj, bounds, periods):
    """A within-world design's tensor nuisance, stacked harmonics and static support (rules 1, 4)."""
    def build():
        L, U = bounds
        lag = tj - ti
        span = min(np.ptp(ti), np.ptp(tj))
        static = {}
        for P in periods:
            f = []
            if not two_cycles(span, P):
                f.append("1-span")
            if not quadrants_ok(lag, P):
                f.append("4-quadrants")
            static[P] = tuple(f)
        return {"X": tensor_basis(ti, tj, (L, U)), "static": static,
                "H": np.hstack([harmonic_matrix(lag, P) for P in periods]) if periods else np.zeros((len(ti), 0))}
    return _cached(("W", ti.tobytes(), tj.tobytes(), tuple(bounds), tuple(periods)), build)


def ref_geometry(t, ref, bounds, periods):
    """A reference panel's mask, common times, averaging operators, nuisance, stacked harmonics, static
    support (rules 2, 3) and chain tables (rule 6's phase segments)."""
    t = np.asarray(t, float)
    ref = np.asarray(ref, object)
    key = ("R", t.tobytes(), tuple(str(r) for r in ref.tolist()), tuple(bounds), tuple(periods))

    def build():
        L, U = bounds
        mask = (t >= L) & (t <= U)
        tm, rm = t[mask], ref[mask]
        refs = sorted(set(rm.tolist()), key=str)
        out = {"mask": mask, "refs": refs}
        if len(refs) != 4:
            return out
        if len(set(zip(tm.tolist(), rm.tolist()))) != len(tm):
            raise RecurrenceError("a reference series holds two observations at one time")
        series = {r: sorted(set(tm[rm == r].tolist())) for r in refs}
        common = np.array(sorted(set.intersection(*(set(s) for s in series.values()))), float)
        n, nt = len(tm), len(common)
        pos = {c: i for i, c in enumerate(common.tolist())}
        avg = np.zeros((nt, n))
        for o, tt in enumerate(tm.tolist()):
            if tt in pos:
                avg[pos[tt], o] = 0.25
        eff = np.zeros((n, 3))
        for k, r in enumerate(refs[:3]):
            eff[rm == r, k] = 1.0
        eff[rm == refs[3], :] = -1.0
        X = np.hstack([backbone.basis(tm, (L, U)), eff])
        tables = {P: chain_table(common, L, U, P) for P in periods}
        out.update(t=tm, common=common, avg=avg, X=X, avgX=avg @ X, mean_op=avg.sum(axis=0) / max(nt, 1),
                   H=np.hstack([harmonic_matrix(tm, P) for P in periods]) if periods else np.zeros((n, 0)),
                   static={P: ("2-refseries",) if not all(series_ok(s, P) for s in series.values()) else ()
                           for P in periods},
                   tables=tables, cond={P: nt > 0 and not bool(np.all(tables[P].ok)) for P in periods})
        return out
    return _cached(key, build)


def ref_rms_op(t, ref, cov, scope, P):
    """The reference-panel readout's RMS and capture denominator alone (RefDesign.readout's "rms" and
    "den", the same operators) without the support machinery, as an operator y -> (rms, den) for a FIXED
    metric (the calibration generator's amplitude solver evaluates it many times per world), or None (not
    four references / rank)."""
    bounds = scope_bounds(scope)
    geo = ref_geometry(t, ref, bounds, (float(P),))
    if len(geo["refs"]) != 4:
        return None
    hm = Projector(geo["X"], cov.subset(geo["mask"])).harmonics(H=geo["H"])[0]
    if not hm.rank2:
        return None
    avgQ, mask, mean_op = geo["avg"] @ hm.Q, geo["mask"], geo["mean_op"]

    def op(y):
        ym = np.asarray(y, float)[mask]
        _, b = hm.coords(ym)
        dbar = avgQ @ b
        return (float(np.sqrt(np.mean(dbar ** 2))) if len(dbar) else 0.0), float(mean_op @ ym)
    return op


def ref_rms(t, ref, cov, scope, P, y):
    op = ref_rms_op(t, ref, cov, scope, P)
    return None if op is None else op(y)


# ================================================================== designs
class WithinDesign:
    """One world's within-world matrix for one readout in one scope (rules 1, 4, 5)."""

    def __init__(self, ti, tj, cov, scope, periods):
        L, U = scope_bounds(scope)
        ti, tj = np.asarray(ti, float), np.asarray(tj, float)
        self.mask = (ti >= L) & (ti <= U) & (tj >= L) & (tj <= U)
        self.ti, self.tj = np.ascontiguousarray(ti[self.mask]), np.ascontiguousarray(tj[self.mask])
        self.harm, self.fails = {}, {}
        if len(self.ti) < 37:
            for P in periods:
                self.fails[P] = ["0-cells"]
            return
        geo = within_geometry(self.ti, self.tj, (L, U), tuple(periods))
        self.proj = Projector(geo["X"], cov.subset(self.mask))
        hms = self.proj.harmonics(H=geo["H"])
        for P, hm in zip(periods, hms):
            f = list(geo["static"][P])
            if not hm.rank2:
                f.append("5-rank")
            self.harm[P], self.fails[P] = hm, f

    def masked(self, y):
        return np.asarray(y, float)[self.mask]

    def J(self, y, P, masked=False):
        return self.harm[P].score(y if masked else self.masked(y))


class RefDesign:
    """One world's four fixed-reference profiles for one readout in one scope (rules 2, 3, 5-ref, 6)."""

    def __init__(self, t, ref, cov, scope, periods):
        L, U = self.L, self.U = scope_bounds(scope)
        self.periods = tuple(periods)
        geo = ref_geometry(t, ref, (L, U), self.periods)
        self.mask, self.refs = geo["mask"], geo["refs"]
        self.harm, self.fails, self.cond, self.tables = {}, {}, {}, {}
        if len(self.refs) != 4:
            for P in periods:
                self.fails[P] = ["2-references"]
            return
        self.common, self.avg, self.mean_op, self.t = geo["common"], geo["avg"], geo["mean_op"], geo["t"]
        X = geo["X"]
        self.proj = Projector(X, cov.subset(self.mask))
        self.rbar = self.avg - geo["avgX"] @ self.proj.Ginv @ self.proj.WX.T   # avg of y - null fit
        hms = self.proj.harmonics(H=geo["H"])
        for P, hm in zip(periods, hms):
            f = list(geo["static"][P])
            if not hm.rank2:
                f.append("5-rank-ref")
            else:
                hm.avgQ = self.avg @ hm.Q                             # b -> four-reference average Delta
            self.harm[P], self.fails[P] = hm, f
            # does the chain exist at EVERY phase? If not, rule 6 is phase-conditional for this candidate
            # (reported; the decision is always the fitted phase's). Exact: the chain's phase segments.
            self.tables[P] = geo["tables"][P]
            self.cond[P] = geo["cond"][P]

    def prepare(self, y):
        """The period-free parts of a readout (computed once per response vector, #68 / q33)."""
        ym = np.asarray(y, float)[self.mask]
        return {"y": ym, "rho": self.rbar @ ym, "den": float(self.mean_op @ ym)}

    def readout(self, y, P, pre=None):
        """The reference-panel readout at period P: phase, chain (rule 6 at the fitted phase), gate, RMS."""
        hm = self.harm[P]
        pre = pre or self.prepare(y)
        _, b = hm.coords(pre["y"])
        a = hm.Rinv @ b
        A = math.hypot(a[0], a[1])
        phi = math.atan2(a[1], a[0])
        dbar = hm.avgQ @ b
        out = {"phase": phi, "A": A, "rms": float(np.sqrt(np.mean(dbar ** 2))) if len(dbar) else 0.0,
               "den": pre["den"], "R_fit": float(np.ptp(dbar)) if len(dbar) else 0.0}
        ch = self.tables[P].at(phi) if A > 0 else None              # (= chain(common, L, U, P, phi))
        out["chain"] = ch is not None
        if ch is None:
            out.update(G=0, reversals=False, returns=False)
            return out
        k, wins = ch
        rho = pre["rho"]
        v = [float(np.mean(rho[lo:hi])) for lo, hi in wins]
        e = [1.0 if (k + j) % 2 == 0 else -1.0 for j in range(5)]
        rev, ret = gate(v, e, out["R_fit"])
        out.update(k=k, windows=[self.common[lo:hi].tolist() for lo, hi in wins], v=v, e=e, reversals=rev,
                   returns=ret, G=int(rev and ret))
        return out


class WorldDesign:
    """One world's H-F designs in one scope: within-world capture / survival matrices and the two
    four-reference panels. within: {"C": (ti, tj, Cov), "Q": (...)}; ref: {"C": (t, ref ids, Cov),
    "Q": (...)} (C: the world's predators against its four prey references; Q: its prey against its
    four predator references). Everything that does not depend on the responses is built once."""

    def __init__(self, wid, within, ref, scope, periods=None):
        self.id, self.scope = wid, scope
        self.periods = tuple(periods or PERIODS[scope])
        self.within = {h: WithinDesign(*within[h], scope, self.periods) for h in ("C", "Q")}
        self.ref = {h: RefDesign(*ref[h], scope, self.periods) for h in ("C", "Q")}


# ================================================================== analysis
def analyze_world(wd, y):
    """One world: y = {"within": {"C": y, "Q": y}, "ref": {"C": y, "Q": y}} (full-length response
    vectors in the designs' input order) -> {"periods": [per-candidate records], "phase_support": ...}.
    Support is decided here, the phase-conditional rule 6 at each readout's FITTED phase."""
    recs = []
    ym, pre = {}, {}                                   # (the period-free parts, once per response vector)
    for P in wd.periods:
        fails = sorted(set(wd.within["C"].fails[P] + wd.within["Q"].fails[P]
                           + wd.ref["C"].fails[P] + wd.ref["Q"].fails[P]))
        rec = {"P": P, "fails": fails, "supported": False, "s": 0.0,
               "phase_conditional": bool(not fails and (wd.ref["C"].cond[P] or wd.ref["Q"].cond[P]))}
        if not fails:
            if not ym:
                ym = {h: wd.within[h].masked(y["within"][h]) for h in "CQ"}
                pre = {h: wd.ref[h].prepare(y["ref"][h]) for h in "CQ"}
            rc = wd.ref["C"].readout(None, P, pre["C"])
            rq = wd.ref["Q"].readout(None, P, pre["Q"])
            JC = wd.within["C"].J(ym["C"], P, masked=True)
            JQ = wd.within["Q"].J(ym["Q"], P, masked=True)
            if not (rc["chain"] and rq["chain"]):
                fails.append("6-windows")
            if rc["den"] <= 0:
                fails.append("capture-denominator")
            rec.update(J_C=JC, J_Q=JQ, G_C=rc["G"], G_Q=rq["G"], phase_C=rc["phase"], phase_Q=rq["phase"],
                       r_C=rc["rms"] / rc["den"] if rc["den"] > 0 else math.nan, r_Q=rq["rms"],
                       readout={"C": rc, "Q": rq})
            if not fails:
                rec["supported"] = True
                rec["s"] = rc["G"] * rq["G"] * min(JC, JQ)
        recs.append(rec)
    cond = [r for r in recs if r["phase_conditional"]]
    return {"id": wd.id, "scope": wd.scope, "periods": recs,
            "phase_support": {"conditional": len(cond), "supported_at_fitted_phase": sum(r["supported"] for r in cond),
                              "periods": [r["P"] for r in cond if r["supported"]]}}


def select(world):
    """-> (P_hat or None, contribution, g) for one world's analysis (ties: the smaller period)."""
    best, bP = 0.0, None
    for r in world["periods"]:                         # (ascending periods: ">" keeps the smaller on ties)
        if r["supported"] and r["s"] > best:
            best, bP = r["s"], r["P"]
    return bP, best, int(bP is not None)


def hf(worlds):
    """S_F and the material quantities over all n qualifying worlds' analyses (analyze_world)."""
    n = len(worlds)
    out = {"n": n, "worlds": {}, "available": True, "reasons": []}
    if n == 0:
        return dict(out, available=False, reasons=["no qualifying worlds"])
    S, EC, EQ, pos = 0.0, 0.0, 0.0, 0
    for w in worlds:
        sup = [r for r in w["periods"] if r["supported"]]
        if not sup:
            out["available"] = False
            out["reasons"].append(f"{w['id']}: no supported candidate")
        P, contrib, g = select(w)
        rec = {"P": P, "contribution": contrib, "g": g, "supported": [r["P"] for r in sup],
               "support_failures": {str(r["P"]): r["fails"] for r in w["periods"] if not r["supported"]},
               "phase_support": w["phase_support"]}
        if P is None:
            rec["selection"] = "no supported reciprocal selection"
        else:
            r = next(r for r in w["periods"] if r["P"] == P)
            rec.update(r_C=r["r_C"], r_Q=r["r_Q"], phase_C=r["phase_C"], phase_Q=r["phase_Q"])
            EC += g * r["r_C"] ** 2
            EQ += g * r["r_Q"] ** 2
            pos += 1
        S += contrib
        out["worlds"][w["id"]] = rec
    out.update(S_F=S / n, E_C=EC / n, E_Q=EQ / n, R_C=math.sqrt(EC / n), R_Q=math.sqrt(EQ / n), positive=pos)
    out["M_F"] = min(out["R_C"] / D_C, out["R_Q"] / D_Q)
    out["material_point"] = out["R_C"] >= D_C and out["R_Q"] >= D_Q
    cs = [w["phase_support"] for w in worlds]
    out["phase_support"] = {"conditional": sum(c["conditional"] for c in cs),
                            "supported_at_fitted_phase": sum(c["supported_at_fitted_phase"] for c in cs),
                            "worlds_with_conditional": sum(1 for c in cs if c["conditional"])}
    return out


def hf_decision(res, c_F, p_F=None, c_M=None, p_M=None, alpha=0.01):
    """H.3.7's three results from a hf() result and its calibration (critical values from the
    development panels, model p-values from the validation tables; None: not calibrated yet)."""
    if not res["available"]:
        return {"available": False, "reasons": res["reasons"]}
    if c_F is None:                      # (#68 round 4 P3: an unavailable calibration never enters a comparison)
        return {"available": False, "reasons": ["the H-F calibration is unavailable (a capped mode): p = 1 in Holm"]}
    det = res["S_F"] > c_F and (p_F is not None and p_F <= alpha)
    op = det and res["material_point"]
    ex = (op and c_M is not None and res["M_F"] > c_M and p_M is not None and p_M <= alpha
          and res["R_C"] > D_C and res["R_Q"] > D_Q)
    return {"available": True, "detection": det, "operational": op, "exceeds_material": ex,
            "S_F": res["S_F"], "c_F": c_F, "p_F": p_F, "M_F": res["M_F"], "c_M": c_M, "p_M": p_M,
            "R_C": res["R_C"], "R_Q": res["R_Q"]}


def responses_capture(C, B):
    """Y^C = sum_r C / sum_r B per cell (rows: cells, columns: replicates)."""
    C, B = np.atleast_2d(np.asarray(C, float)), np.atleast_2d(np.asarray(B, float))
    return C.sum(axis=1) / B.sum(axis=1)


def responses_survival(Lx, L0, trials=TRIALS):
    """Y^Q = sum_r L / 600R - sum_r L0 / 600R per cell."""
    Lx, L0 = np.atleast_2d(np.asarray(Lx, float)), np.atleast_2d(np.asarray(L0, float))
    return Lx.sum(axis=1) / (trials * Lx.shape[1]) - L0.sum(axis=1) / (trials * L0.shape[1])

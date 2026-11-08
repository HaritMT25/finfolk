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

PERIODS AND SUPPORT (H.3.3). Full history {4..20} U {25..100 by 5} M (33); an epoch {4..20, 25} M (18).
A candidate is supported for a world only when ALL SIX rules hold, for both readouts:
  1 both guilds' within-world source-time spans >= 2P (one engine step, 1e-6 M, of tolerance, here and
    in rule 2's span only);
  2 each of the four reference series spans >= 2P, has >= 9 distinct times and no interior gap > P/4;
  3 every time used in a reversal window has all four references measured (the windows use only the
    common times);
  4 the within-world lag phases 2 pi (t_j - t_i) / P cover the circle with no gap > pi/2 (+1e-10);
  5 M_X H_P has rank two, within the world and on the reference panel (smaller / larger singular value
    in the W metric >= 1e-10);
  6 PHASE-CONDITIONAL (the coordinator's pre-seal decision, 2026-11-07): the five-window chain of H.3.5
    can be constructed AT THE FITTED PHASE of each readout's reference panel. A candidate whose chain
    exists only for some phases (the full-history 90-100M and the epoch 25M candidates on the real
    graph) is supported exactly when its fitted phase admits the chain. The SAME rule, in this same
    code, decides support inside every calibration null panel (calib.py calls analyze_world), and every
    result reports, per world, how many candidates were phase-conditional and how many of those the
    fitted phase supported (phase_support).
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
EPOCH_PERIODS = tuple(float(p) for p in list(range(4, 21)) + [25])
SCOPES = {"full": (0.0, 200.0), "E1": (0.0, 50.0), "E2": (75.0, 125.0), "E3": (150.0, 200.0)}
PERIODS = {"full": FULL_PERIODS, "E1": EPOCH_PERIODS, "E2": EPOCH_PERIODS, "E3": EPOCH_PERIODS}
SPAN_TOL = 1e-6          # one engine step: the two-cycle span comparisons only
RANK_TOL = 1e-10
PHASE_TOL = 1e-10
CLAMP_TOL = 1e-10
WIN_EPS = 1e-9           # closed windows |t - c| <= P/8 (M; float safety only)
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
            if self.U is not None and self.U.shape[1]:
                DU = self.U * self.dinv[:, None]
                Kc = _chol(np.eye(self.U.shape[1]) + self.U.T @ DU)
                Ki = _chol_solve(Kc, np.eye(Kc.shape[0]))
                self.M = DU @ ((Ki + Ki.T) / 2)          # W A = D^-1 A - M (U' D^-1 A)
            else:
                self.U = None

    def subset(self, mask):
        mask = np.asarray(mask, bool)
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
    """One period's projection operators: G = W M_X H (n x 2), S = H'W M_X H, M_X H; rank ratio."""

    def __init__(self, proj, H):
        self.H = H
        WH = proj.cov.wmul(H)
        C = proj.Ginv @ (proj.WX.T @ H)
        self.G = WH - proj.WX @ C
        S = H.T @ self.G
        self.S = (S + S.T) / 2
        self.MH = H - proj.X @ C
        ev = np.linalg.eigvalsh(self.S)
        self.ratio = math.sqrt(max(ev[0], 0.0) / ev[1]) if ev[1] > 0 else 0.0
        self.rank2 = self.ratio >= RANK_TOL
        self.Sinv = np.linalg.inv(self.S) if self.rank2 else None

    def fit(self, y):
        """-> (a (2,), J, Delta = M_X H a)."""
        q = self.G.T @ y
        a = self.Sinv @ q
        J = 0.5 * float(q @ a)
        if J < 0:
            if J < -CLAMP_TOL:
                raise RecurrenceError(f"a negative recurrence score J = {J} (an implementation failure)")
            J = 0.0
        return a, J, self.MH @ a


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
        return Harmonic(self, H)

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
    crossings u = (t +- (P/8 + eps)) mod (P/2); each segment holds (k relative to u, windows) or None."""

    def __init__(self, times, L, U, P):
        self.times, self.P = np.asarray(times, float), P
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
        """phi (B,) -> (segment index (B,), the draw's k (B,), feasible (B,))."""
        P, half = self.P, self.P / 2
        s = np.asarray(phi, float) / (2 * math.pi / P)
        u = np.mod(s, half)
        u = np.where(u < self.bp[0], u + half, u)                 # (the wrapping segment)
        q = np.rint((s - u) / half).astype(np.int64)
        seg = np.searchsorted(self.bp, u, "right") - 1
        return seg, self.k[seg] - q, self.ok[seg]


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


# ================================================================== designs
class WithinDesign:
    """One world's within-world matrix for one readout in one scope (rules 1, 4, 5)."""

    def __init__(self, ti, tj, cov, scope, periods):
        L, U = scope_bounds(scope)
        ti, tj = np.asarray(ti, float), np.asarray(tj, float)
        self.mask = (ti >= L) & (ti <= U) & (tj >= L) & (tj <= U)
        self.ti, self.tj = ti[self.mask], tj[self.mask]
        self.harm, self.fails = {}, {}
        if len(self.ti) < 37:
            for P in periods:
                self.fails[P] = ["0-cells"]
            return
        self.proj = Projector(tensor_basis(self.ti, self.tj, (L, U)), cov.subset(self.mask))
        lag = self.tj - self.ti
        span = min(np.ptp(self.ti), np.ptp(self.tj))
        for P in periods:
            f = []
            if not two_cycles(span, P):
                f.append("1-span")
            if not quadrants_ok(lag, P):
                f.append("4-quadrants")
            hm = self.proj.harmonic(harmonic_matrix(lag, P))
            if not hm.rank2:
                f.append("5-rank")
            self.harm[P], self.fails[P] = hm, f

    def J(self, y, P):
        return self.harm[P].fit(np.asarray(y, float)[self.mask])[1]


class RefDesign:
    """One world's four fixed-reference profiles for one readout in one scope (rules 2, 3, 5-ref, 6)."""

    def __init__(self, t, ref, cov, scope, periods):
        L, U = self.L, self.U = scope_bounds(scope)
        t = np.asarray(t, float)
        ref = np.asarray(ref, object)
        self.mask = (t >= L) & (t <= U)
        t, ref = t[self.mask], ref[self.mask]
        self.refs = sorted(set(ref.tolist()), key=str)
        self.periods = tuple(periods)
        self.harm, self.fails, self.cond, self.tables = {}, {}, {}, {}
        series = {r: sorted(set(t[ref == r].tolist())) for r in self.refs}
        if len(self.refs) != 4:
            for P in periods:
                self.fails[P] = ["2-references"]
            return
        if len(set(zip(t.tolist(), ref.tolist()))) != len(t):
            raise RecurrenceError("a reference series holds two observations at one time")
        self.common = np.array(sorted(set.intersection(*(set(s) for s in series.values()))), float)
        n, nt = len(t), len(self.common)
        pos = {c: i for i, c in enumerate(self.common.tolist())}
        self.avg = np.zeros((nt, n))
        for o, (tt, rr) in enumerate(zip(t.tolist(), ref.tolist())):
            if tt in pos:
                self.avg[pos[tt], o] = 0.25
        eff = np.zeros((n, 3))
        for k, r in enumerate(self.refs[:3]):
            eff[ref == r, k] = 1.0
        eff[ref == self.refs[3], :] = -1.0
        X = np.hstack([backbone.basis(t, (L, U)), eff])
        self.proj = Projector(X, cov.subset(self.mask))
        self.mean_op = self.avg.sum(axis=0) / max(nt, 1)            # mean over the common (t, r) cells
        self.rbar = self.avg - (self.avg @ X) @ self.proj.Ginv @ self.proj.WX.T   # avg of y - null fit
        self.t = t
        for P in periods:
            f = []
            if not all(series_ok(s, P) for s in series.values()):
                f.append("2-refseries")
            hm = self.proj.harmonic(harmonic_matrix(t, P))
            if not hm.rank2:
                f.append("5-rank-ref")
            else:
                hm.aop = hm.Sinv @ hm.G.T                             # y -> a
                hm.dbar = self.avg @ hm.MH @ hm.aop                   # y -> four-reference average Delta
            self.harm[P], self.fails[P] = hm, f
            # does the chain exist at EVERY phase? If not, rule 6 is phase-conditional for this candidate
            # (reported; the decision is always the fitted phase's). Exact: the chain's phase segments.
            self.tables[P] = chain_table(self.common, L, U, P)
            self.cond[P] = nt > 0 and not bool(np.all(self.tables[P].ok))

    def readout(self, y, P):
        """The reference-panel readout at period P: phase, chain (rule 6 at the fitted phase), gate, RMS."""
        hm = self.harm[P]
        y = np.asarray(y, float)[self.mask]
        a = hm.aop @ y
        A = math.hypot(a[0], a[1])
        phi = math.atan2(a[1], a[0])
        dbar = hm.dbar @ y
        out = {"phase": phi, "A": A, "rms": float(np.sqrt(np.mean(dbar ** 2))) if len(dbar) else 0.0,
               "den": float(self.mean_op @ y), "R_fit": float(np.ptp(dbar)) if len(dbar) else 0.0}
        ch = chain(self.common, self.L, self.U, P, phi) if A > 0 else None
        out["chain"] = ch is not None
        if ch is None:
            out.update(G=0, reversals=False, returns=False)
            return out
        k, wins = ch
        rho = self.rbar @ y
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
    for P in wd.periods:
        fails = sorted(set(wd.within["C"].fails[P] + wd.within["Q"].fails[P]
                           + wd.ref["C"].fails[P] + wd.ref["Q"].fails[P]))
        rec = {"P": P, "fails": fails, "supported": False, "s": 0.0,
               "phase_conditional": bool(not fails and (wd.ref["C"].cond[P] or wd.ref["Q"].cond[P]))}
        if not fails:
            rc = wd.ref["C"].readout(y["ref"]["C"], P)
            rq = wd.ref["Q"].readout(y["ref"]["Q"], P)
            JC = wd.within["C"].J(y["within"]["C"], P)
            JQ = wd.within["Q"].J(y["within"]["Q"], P)
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

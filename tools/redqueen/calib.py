#!/usr/bin/env python3
"""calib.py: the focused calibration of H-F and H-T (Annex H.9-H.12; design v4 §9.3-9.4; (d) item 5,
part 5): the compact null generator (its simulation side), the registered null modes and alternatives,
the panel harness, critical values, model p-values, the validation acceptance and the CPU benchmark.
numpy; deterministic; subprocess-free (one panel at a time; shard panel ranges across processes).

GENERATOR (H.9). Parameters are a JSON document (finfolk.redqueen.annexH.generator/1). FITTING them to
the bank and the permitted training-world observations (H.9.1's Gaussian state-space likelihood, H.9.2's
interval-censored composite likelihood) needs those data and is NOT implemented here; placeholder_params()
is a documented synthetic stand-in ("fitted": false) for the tests and the benchmark only.
  Means (logit): capture eta_C(i,j) = B(t_i)'G_C B(t_j) + u_CQ(t_i) + u_CP(t_j); exposed survival
  eta_S(i,j) = c(t_i) + B(t_i)'G_S B(t_j) + u_SQ(t_i) + u_SP(t_j); free eta_0(i) = c(t_i) + u_0(t_i);
  capture references (the world's predator at t vs prey reference r) m_C(t) + u_CP(t) + a_C,r;
  survival references (its prey at t vs predator reference r) c(t) + m_S(t) + u_SQ(t) + a_S,r. B: the
  six H.1 splines on [0, 200]M. A synthetic world's coefficient vector is a training world's (uniform,
  with replacement) with its deviation from the training mean enlarged by 1.5.
  Red variation: five diagonal AR(1) processes (rho per 5M step in [0, 0.98], correlated innovations;
  exact at irregular times: x' = rho^D x + eta, Cov eta = Gamma o (1 - (rho_i rho_j)^D), stationary
  start Gamma = Sigma / (1 - rho rho')); innovation covariance 0.95 Sigma + 0.05 tr(Sigma)/5 I.
  Validation stress: rho = 0.98, innovation SD x 1.5.
  Observation (H.9.2): K = floor(N sigma(a + eps) + 1/2), N = the capture bound or 600; eps = s(mu) (R +
  D + E) with the row (prey snapshot: C, S, F channels), donor (predator snapshot: C, S) and cell
  components by the ACTUAL sharing keys (a reference is one snapshot shared by its block's worlds; a
  free control is generated once per prey snapshot and replicate and reused), unit total latent
  variance per channel; s(mu) by the mean bins [0,.35), [.35,.70), [.70,1] (capture) and [0,.25),
  [.25,.75), [.75,1] (survival); a(mu) solves E[K/N] = mu (48-node Gauss-Hermite, tabulated on 801 logit
  nodes per (s, N), linear interpolation). Validation stress: s_C = max(1.5 s_bank, 0.80 below 0.35 else
  0.35), survival 1.5 s_bank. No second binomial layer.
  Recurrence (H.9.3): world period uniform on the registered grid, phase uniform; a lag harmonic
  cos(omega (t_j - t_i) - phi) within the world and cos(omega t - phi) on the reference panels, one latent
  amplitude per readout (and epoch), solved (safeguarded secant) so that the NOISE-FREE post-refit
  native RMS on the world's reference panel (recurrence.RefDesign, the actual graph and metric) equals
  the target; "max" (as large as bounded means permit) = the latent amplitude 6; an unattainable target
  is recorded and the panel is a non-success (never redrawn).
  Directional knobs (H-T modes): per epoch, a latent focal-time slope (capture: predator time; exposed
  survival: prey time), continuous, linear within each epoch; targets on the epoch slopes beta_P,e /
  beta_Q,e are met per world on noise-free data (capture exactly: the fitted logit is linear-additive;
  survival by three secant steps).
  The analysis covariance V of a panel is the bank model evaluated at the panel's observed per-channel
  replicate means (clipped to [1/2N, 1 - 1/2N]; the delta method; shared columns per sharing key) - the
  same plug-in rule the real analysis uses.

MODES (H.10). H-F (full history): F0 none; F1 capture only (RMS 0.10 / 0.20 by panel parity); F2
survival only (0.04 / 0.08); F3 capture 0.10 + survival max; F4 survival 0.04 + capture max;
alternatives FA1 (0.10, 0.04), FA2 (0.20, 0.08). H-T (epochs; one period per world across epochs): T0
stable material directional (1.5 delta), no recurrence; T1 stable recurrence (0.15, 0.06), no
directional change; T2 both; T3 none, stressed red variation, half the worlds saturated (+2.5 logit
capture), noise x 1.5; T4 cycles 32 subtypes ((14 boundary components + a capture-only + a survival-only
transition) x 2 directions) over the three epoch pairs; alternatives TA1 / TA2 (material / doubled,
direction by panel parity). Graph strata: "actual" (the qualifying worlds) and "stress24" (24 worlds by
sha256 of the registry id). Streams: AnnexH/1/<hyp>/<stage>:<stratum>/<mode>/<panel>[/<purpose>].

DECISIONS (H.11). Development: per stratum (160 panels) the plus-one 0.99 order statistic (= the
maximum); the largest applicable stratum value: c_F over F0-F2, c_M (M_F) over F0-F4, epoch gates
c_E1..c_E3 (S_e) over F0-F2, c_T = max(log 600, over T0-T4). Validation: p_m(s) = (1 + #{null >= s}) /
1001 per stratum, p_model = max_m; false positives of the complete locked rule; U95 <= 0.02 per
mode/stratum (at most 12 / 1,000).
BENCHMARK (H.12). `calib.py bench` runs the first 50 development panels of a hypothesis (the ten strata
in turn) with every fit, period, window, material rule, epoch, direction and bootstrap used in the
decision, and reports CPU seconds per panel against the 13.5 s target.

    python3 calib.py panels --hyp H-F --stage dev --graph g.jsonl.gz --from 0 --to 160 --out dev.jsonl
    python3 calib.py crit dev_HF.jsonl dev_HT.jsonl > crit.json
    python3 calib.py accept --crit crit.json val_HF.jsonl ...
    python3 calib.py bench --hyp H-F --graph g.jsonl.gz [--params p.json] [--panels 50]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
if __name__ == "__main__":                 # one BLAS thread per process: honest CPU seconds; shard panels
    for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(_v, "1")
import numpy as np  # noqa: E402

import backbone  # noqa: E402
import recurrence  # noqa: E402
import stats  # noqa: E402
import transition  # noqa: E402
from transition import VecSplitMix64  # noqa: E402

SCHEMA = "finfolk.redqueen.annexH.generator/1"
COARSE = (1e-6,) + tuple(5.0 * k for k in range(1, 41))
R_REP = 6
TRIALS = 600
CAP_BINS = (0.35, 0.70)
SURV_BINS = (0.25, 0.75)
STRESS_RHO, STRESS_SD = 0.98, 1.5
COEF_STRESS = 1.5
A_MAX = 6.0
NTHETA = 98
F_MODES = ("F0", "F1", "F2", "F3", "F4")
T_MODES = ("T0", "T1", "T2", "T3", "T4")
ALT = {"H-F": ("FA1", "FA2"), "H-T": ("TA1", "TA2")}
STRATA = ("actual", "stress24")
N_DEV, N_VAL, N_ALT = 160, 1000, 100
GREVILLE = np.array([0.0, 1 / 9, 1 / 3, 2 / 3, 8 / 9, 1.0])
GH_X, GH_W = np.polynomial.hermite_e.hermegauss(48)
GH_W = GH_W / GH_W.sum()


class CalibError(Exception):
    pass


def sig(x):
    return 1.0 / (1.0 + np.exp(-x))


def logit(p):
    p = np.asarray(p, float)
    return np.log(p / (1 - p))


# ================================================================== graph
class WorldGraph:
    """One qualifying C world's measured assays: within-world pairs (prey time, predator time), its
    capture references (its predator at t vs prey reference r) and survival references (its prey at t vs
    predator reference r). Times in M (actual: F1 = 1e-6)."""

    def __init__(self, wid, block, within, refC, refQ):
        self.id, self.block = wid, block
        w = sorted(set(within))
        self.ti = np.array([a for a, _ in w], float)
        self.tj = np.array([b for _, b in w], float)
        rc = sorted(set(refC), key=lambda x: (x[0], str(x[1])))
        rq = sorted(set(refQ), key=lambda x: (x[0], str(x[1])))
        self.cT, self.cR = np.array([t for t, _ in rc], float), np.array([r for _, r in rc], object)
        self.qT, self.qR = np.array([t for t, _ in rq], float), np.array([r for _, r in rq], object)
        self.prey = np.array(sorted(set(self.ti.tolist()) | set(self.qT.tolist())))
        self.pred = np.array(sorted(set(self.tj.tolist()) | set(self.cT.tolist())))
        self.times = np.array(sorted(set(self.prey.tolist()) | set(self.pred.tolist())))
        self.coarse = all((a, b) in set(w) for a in COARSE for b in COARSE)


def synthetic_graph(n=32, centres=(30.0, 100.0, 170.0), offsets=(1.0, 2.0, 4.0)):
    """A small stand-in for the real graph (tests, benchmark without the real file): coarse 41 x 41, a fine
    window of +-1, 2, 4M around each centre (fine x fine pairs), reference series at coarse + fine times,
    four prey and four predator references per block of four worlds."""
    fine = sorted({c + s * o for c in centres for o in offsets for s in (-1, 1)})
    times = sorted(set(COARSE) | set(fine))
    within = [(a, b) for a in COARSE for b in COARSE] + [(a, b) for a in fine for b in fine]
    out = []
    for w in range(n):
        b = w // 4
        rc = [(t, f"RQ:b{b}:{k}") for t in times for k in range(4)]
        rq = [(t, f"RP:b{b}:{k}") for t in times for k in range(4)]
        out.append(WorldGraph(f"C{w + 1:02d}", b, within, rc, rq))
    return out


def load_graph(path, worlds=None):
    """The real assay graph (graph.py's graph.jsonl.gz): the C worlds with four capture and four survival
    references; blocks = worlds sharing a reference set."""
    def tt(x):
        return 1e-6 if float(x) == 0 else float(x)
    within, rc, rq = {}, {}, {}
    with gzip.open(path, "rt") as f:
        for ln in f:
            e = json.loads(ln)
            q, p = e["prey"], e["pred"]
            if q.startswith("Q:") and p.startswith("P:"):
                _, wq, a = q.split(":")
                _, wp, b = p.split(":")
                if wq == wp:
                    within.setdefault(wq, []).append((tt(a), tt(b)))
            elif q.startswith("RQ:") and p.startswith("P:"):
                _, w, t = p.split(":")
                rc.setdefault(w, []).append((tt(t), q))
            elif q.startswith("Q:") and p.startswith("RP:"):
                _, w, t = q.split(":")
                rq.setdefault(w, []).append((tt(t), p))
    ids = sorted(w for w in within if len({r for _, r in rc.get(w, [])}) == 4 and len({r for _, r in rq.get(w, [])}) == 4)
    if worlds:
        ids = [w for w in ids if w in set(worlds)]
    blocks = {}
    for w in ids:
        key = tuple(sorted({r for _, r in rc[w]} | {r for _, r in rq[w]}))
        blocks.setdefault(key, len(blocks))
    return [WorldGraph(w, blocks[tuple(sorted({r for _, r in rc[w]} | {r for _, r in rq[w]}))], within[w], rc[w], rq[w])
            for w in ids]


def stratum_worlds(graph, stratum):
    """"actual": every qualifying world; "stress24": 24 of them by the sha256 of the registry id."""
    if stratum == "actual":
        return list(graph)
    if len(graph) < 24:
        raise CalibError("the 24-world stress stratum needs at least 24 qualifying worlds")
    pick = sorted(graph, key=lambda g: hashlib.sha256(g.id.encode()).hexdigest())[:24]
    return sorted(pick, key=lambda g: g.id)


# ================================================================== parameters
def _th(theta, name):
    sl = {"GC": (0, 36), "GS": (36, 72), "c": (72, 78), "mC": (78, 84), "mS": (84, 90), "aC": (90, 94), "aS": (94, 98)}[name]
    return theta[sl[0]:sl[1]]


def placeholder_params(n_train=20, seed=11, capture_bound=324):
    """A SYNTHETIC generator parameter set (NOT fitted to any bank or training data): smooth capture
    surfaces near 0.35 with a predator-time trend, survival near 0.8 with an exposure cost, moderate red
    variation, the pilot-like capture noise scales. For the tests and the CPU benchmark only."""
    z = VecSplitMix64(seed).normals(n_train * NTHETA).reshape(n_train, NTHETA)
    th = np.zeros((n_train, NTHETA))
    for k in range(n_train):
        gc = (logit(0.35) + 0.08 * 4 * GREVILLE[None, :] - 0.04 * 4 * GREVILLE[:, None]
              + 0.15 * z[k, 0:36].reshape(6, 6))
        gs = -0.6 + 0.03 * 4 * GREVILLE[:, None] + 0.10 * z[k, 36:72].reshape(6, 6)
        th[k, 0:36], th[k, 36:72] = gc.ravel(), gs.ravel()
        th[k, 72:78] = logit(0.8) + 0.10 * z[k, 72:78]
        th[k, 78:84] = logit(0.35) + 0.08 * 4 * GREVILLE + 0.10 * z[k, 78:84]
        th[k, 84:90] = -0.6 + 0.10 * z[k, 84:90]
        a = 0.2 * z[k, 90:94]
        th[k, 90:94] = a - a.mean()
        a = 0.1 * z[k, 94:98]
        th[k, 94:98] = a - a.mean()
    sd = np.array([0.12, 0.12, 0.08, 0.08, 0.06])
    corr = np.full((5, 5), 0.3) + 0.7 * np.eye(5)
    return {"schema": SCHEMA, "fitted": False, "note": "synthetic placeholder: tests and benchmark only",
            "theta": th.tolist(), "ar": {"rho": [0.7] * 5, "Sigma": (corr * np.outer(sd, sd)).tolist(), "step": 5.0},
            "noise": {"s": {"C": [0.55, 0.25, 0.20], "S": [0.30, 0.20, 0.30], "F": [0.30, 0.20, 0.30]},
                      "SigmaR": [[0.25, 0.05, 0.05], [0.05, 0.25, 0.15], [0.05, 0.15, 0.5]],
                      "SigmaD": [[0.25, 0.05], [0.05, 0.25]]},
            "capture_bound": capture_bound, "replicates": R_REP}


def check_params(p):
    if p.get("schema") != SCHEMA:
        raise CalibError(f"generator parameters: schema {p.get('schema')!r}")
    th = np.asarray(p["theta"], float)
    if th.ndim != 2 or th.shape[1] != NTHETA or len(th) < 2:
        raise CalibError("generator parameters: theta must be (training worlds >= 2) x 98")
    rho = np.asarray(p["ar"]["rho"], float)
    if np.any(rho < 0) or np.any(rho > 0.98):
        raise CalibError("generator parameters: each autoregression lies in [0, 0.98]")
    for k in ("SigmaR", "SigmaD"):
        if np.min(np.linalg.eigvalsh(np.asarray(p["noise"][k], float))) < -1e-12:
            raise CalibError(f"generator parameters: {k} is not PSD")
    tot = np.diag(np.asarray(p["noise"]["SigmaR"]))[:2] + np.diag(np.asarray(p["noise"]["SigmaD"]))
    if np.any(tot > 1) or np.asarray(p["noise"]["SigmaR"])[2][2] > 1:
        raise CalibError("generator parameters: row + donor variance exceeds the unit latent variance")
    return p


def noise_scale(p, ch, mu, stress=False, extra=1.0):
    """s_ch(mu) by the registered mean bins (validation stress: H.9.2's floors / multipliers)."""
    s = np.asarray(p["noise"]["s"][ch], float)
    bins = CAP_BINS if ch == "C" else SURV_BINS
    out = np.where(mu < bins[0], s[0], np.where(mu < bins[1], s[1], s[2]))
    if stress:
        out = np.maximum(1.5 * out, np.where(mu < 0.35, 0.80, 0.35)) if ch == "C" else 1.5 * out
    return out * extra


# ================================================================== the bounded observation model
_LOC = {}


def location(mu, s, N):
    """a(mu) with E[floor(N sigma(a + s Z) + 1/2)] / N = mu, Z ~ N(0, 1) (vectorized over cells)."""
    mu, s = np.asarray(mu, float), np.asarray(s, float)
    out = np.empty_like(mu)
    for sv in np.unique(s):
        key = (float(sv), int(N))
        if key not in _LOC:
            lm = np.linspace(float(logit(0.5 / N)), float(logit(1 - 0.5 / N)), 801)
            tgt = sig(lm)
            lo, hi = lm - 12.0, lm + 12.0
            for _ in range(64):
                mid = (lo + hi) / 2
                f = np.floor(N * sig(mid[:, None] + sv * GH_X[None, :]) + 0.5) @ GH_W / N
                lo, hi = np.where(f < tgt, mid, lo), np.where(f < tgt, hi, mid)
            _LOC[key] = (lm, (lo + hi) / 2)
        lm, a = _LOC[key]
        m = s == sv
        out[m] = np.interp(logit(np.clip(mu[m], 0.5 / N, 1 - 0.5 / N)), lm, a)
    return out


def counts(mu, s, eps, N):
    """K = floor(N sigma(a(mu) + eps) + 1/2) (eps already scaled by s(mu))."""
    return np.floor(N * sig(location(mu, s, N) + eps) + 0.5)


# ================================================================== red variation
def ar_paths(times, rho, Sigma, step, z):
    """Five diagonal AR(1) processes at sorted irregular times (exact), stationary start."""
    rho = np.asarray(rho, float)
    S = np.asarray(Sigma, float)
    d = S.shape[0]
    S = 0.95 * S + 0.05 * np.trace(S) / d * np.eye(d)
    rr = np.outer(rho, rho)
    Gam = S / (1 - rr)
    x = np.zeros((len(times), d))
    x[0] = np.linalg.cholesky(Gam) @ z[0]
    for k in range(1, len(times)):
        D = (times[k] - times[k - 1]) / step
        C = Gam * (1 - rr ** D)
        x[k] = rho ** D * x[k - 1] + np.linalg.cholesky(C + 1e-15 * np.eye(d)) @ z[k]
    return x


# ================================================================== mode plans
def epoch_of(t):
    for e in transition.EPOCHS:
        L, U = recurrence.SCOPES[e]
        if L <= t <= U:
            return e
    return None


def plan_world(hyp, mode, panel, k, rng):
    """One world's knobs for (hyp, mode, panel): rec targets {scope: (C, Q)} (None / RMS / "max"),
    directional targets {epoch: (beta_P, beta_Q)} or None, period, phase, saturation, noise multiplier."""
    grid = recurrence.FULL_PERIODS if hyp == "H-F" else recurrence.EPOCH_PERIODS
    P = grid[int(rng.below(len(grid), 1)[0])]
    phi = float((rng.next64(1)[0] >> np.uint64(11)).astype(np.float64) * (2 * math.pi / (1 << 53)))
    pl = {"P": P, "phi": phi, "rec": {}, "dir": None, "sat": 0.0, "extra": 1.0, "stress_ar": False}
    dP, dQ = stats.DELTA_P, stats.DELTA_Q
    if hyp == "H-F":
        m = 1 if panel % 2 == 0 else 2
        pl["rec"]["full"] = {"F0": (None, None), "F1": (0.10 * m, None), "F2": (None, 0.04 * m),
                             "F3": (0.10, "max"), "F4": ("max", 0.04), "FA1": (0.10, 0.04),
                             "FA2": (0.20, 0.08)}[mode]
        return pl
    E = transition.EPOCHS
    zero = {e: (0.0, 0.0) for e in E}
    if mode == "T0":
        pl["dir"] = {e: (1.5 * dP, 1.5 * dQ) for e in E}
    elif mode == "T1":
        pl["dir"], pl["rec"] = dict(zero), {e: (0.15, 0.06) for e in E}
    elif mode == "T2":
        pl["dir"], pl["rec"] = {e: (1.5 * dP, 1.5 * dQ) for e in E}, {e: (0.15, 0.06) for e in E}
    elif mode == "T3":
        pl["dir"] = dict(zero)
        pl.update(sat=2.5 if k % 2 == 0 else 0.0, extra=1.5, stress_ar=True)
    elif mode in ("T4", "TA1", "TA2"):
        pair = transition.PAIRS[(panel // 32) % 3] if mode == "T4" else transition.PAIRS[(panel // 2) % 3]
        sub = panel % 32 if mode == "T4" else None
        forward = (sub % 2 == 0) if mode == "T4" else (panel % 2 == 0)
        a, f = (pair[0], pair[1]) if forward else (pair[1], pair[0])
        ard_dir, fsd_rec = {"T4": ((1.5 * dP, 1.5 * dQ), (0.15, 0.06)), "TA1": ((dP, dQ), (0.10, 0.04)),
                            "TA2": ((2 * dP, 2 * dQ), (0.20, 0.08))}[mode]
        d = {e: (0.0, 0.0) for e in E}
        r = {e: (None, None) for e in E}
        d[a] = ard_dir
        r[f] = fsd_rec
        if sub is not None:
            comp = sub // 2                     # 0..13 the boundary component, 14 capture-only, 15 survival-only
            if comp == 0:
                d[a] = (0.0, d[a][1])
            elif comp == 1:
                d[a] = (d[a][0], 0.0)
            elif comp == 2:
                r[a] = (0.10, r[a][1])
            elif comp == 3:
                r[a] = (r[a][0], 0.04)
            elif comp == 4:
                r[f] = (0.10, r[f][1])
            elif comp == 5:
                r[f] = (r[f][0], 0.04)
            elif comp in (6, 7):
                d[f] = ((dP if comp == 6 else -dP), d[f][1])
            elif comp in (8, 9):
                d[f] = (d[f][0], (dQ if comp == 8 else -dQ))
            elif comp == 10:
                d[a], d[f] = (dP / 2, d[a][1]), (dP / 2, d[f][1])
            elif comp == 11:
                d[a] = (d[a][0], dQ / 2)
                d[f] = (d[f][0], dQ / 2)
            elif comp == 12:
                r[a], r[f] = (0.10, r[a][1]), (0.10, r[f][1])
            elif comp == 13:
                r[a], r[f] = (r[a][0], 0.04), (r[f][0], 0.04)
            elif comp == 14:                    # only capture changes
                d = {e: (d[e][0], 0.0) for e in E}
                r = {e: (r[e][0], None) for e in E}
            else:                               # only survival changes
                d = {e: (0.0, d[e][1]) for e in E}
                r = {e: (None, r[e][1]) for e in E}
            pl["subtype"] = sub
        pl["dir"], pl["rec"] = d, r
    else:
        raise CalibError(f"unknown mode {mode}")
    return pl


# ================================================================== a panel
_BS = {}


def _bspline_full(t):
    """The full-history basis at a graph's times (cached: graph-invariant; q33)."""
    t = np.asarray(t, float)
    key = t.tobytes()
    B = _BS.get(key)
    if B is None:
        if len(_BS) > 4096:
            _BS.clear()
        B = _BS[key] = backbone.basis(t, (0.0, 200.0))
    return B


def _cum_slope(t, slopes):
    """A continuous latent focal-time term whose slope per 50M is slopes[e] inside epoch e (linear
    interpolation across the gaps; 0 before F1)."""
    knots = [(0.0, slopes["E1"]), (50.0, slopes["E1"]), (75.0, slopes["E2"]), (125.0, slopes["E2"]),
             (150.0, slopes["E3"]), (200.0, slopes["E3"])]
    xs = np.linspace(0.0, 200.0, 4001)
    sl = np.interp(xs, [k for k, _ in knots], [v for _, v in knots])
    integ = np.concatenate([[0.0], np.cumsum((sl[1:] + sl[:-1]) / 2 * np.diff(xs) / 50.0)])
    return np.interp(np.asarray(t, float), xs, integ)


class Panel:
    """Simulates one panel on a graph stratum and builds the analysis inputs."""

    def __init__(self, graph, params, hyp, stage, stratum, mode, panel, stress=None):
        self.g, self.p = graph, check_params(params)
        self.hyp, self.stage, self.stratum, self.mode, self.panel = hyp, stage, stratum, mode, panel
        self.stress = (stage == "val") if stress is None else stress
        self.tag = (hyp, f"{stage}:{stratum}", mode, panel)
        self.unattainable = []

    def rng(self, purpose):
        return VecSplitMix64(stats.stream_seed(*self.tag, purpose))

    # -------------------------------------------------------- means
    def latent(self, wg, th, pl, u, amp, dirC, dirQ, refs_only=False):
        """Latent means of every channel of one world given amplitudes amp {scope-or-epoch: (aC, aQ)}
        (refs_only: the free controls and the two reference panels only)."""
        idx = {t: i for i, t in enumerate(wg.times.tolist())}
        U_ = lambda t, k: u[[idx[x] for x in np.asarray(t).tolist()], k]  # noqa: E731
        GC, GS = _th(th, "GC").reshape(6, 6), _th(th, "GS").reshape(6, 6)
        c, mC, mS, aC, aS = _th(th, "c"), _th(th, "mC"), _th(th, "mS"), _th(th, "aC"), _th(th, "aS")
        w = 2 * math.pi / pl["P"]
        out = {}
        if not refs_only:
            Bi, Bj = _bspline_full(wg.ti), _bspline_full(wg.tj)
            lagc = np.cos(w * (wg.tj - wg.ti) - pl["phi"])
            ampC_w, ampQ_w = self._amp_pairs(wg.ti, wg.tj, amp)
            out["C"] = (np.einsum("na,ab,nb->n", Bi, GC, Bj) + U_(wg.ti, 0) + U_(wg.tj, 1) + pl["sat"]
                        + dirC(wg.tj) + ampC_w * lagc)
            out["S"] = (Bi @ c + np.einsum("na,ab,nb->n", Bi, GS, Bj) + U_(wg.ti, 2) + U_(wg.tj, 3)
                        + dirQ(wg.ti) + ampQ_w * lagc)
        out["F"] = _bspline_full(wg.prey) @ c + U_(wg.prey, 4)
        refs = sorted(set(wg.cR.tolist()), key=str)
        ra = np.array([aC[refs.index(r)] for r in wg.cR])
        out["RC"] = (_bspline_full(wg.cT) @ mC + U_(wg.cT, 1) + ra + pl["sat"] + dirC(wg.cT)
                     + self._amp_t(wg.cT, amp, 0) * np.cos(w * wg.cT - pl["phi"]))
        refs = sorted(set(wg.qR.tolist()), key=str)
        ra = np.array([aS[refs.index(r)] for r in wg.qR])
        out["RS"] = (_bspline_full(wg.qT) @ (c + mS) + U_(wg.qT, 2) + ra + dirQ(wg.qT)
                     + self._amp_t(wg.qT, amp, 1) * np.cos(w * wg.qT - pl["phi"]))
        return out

    @staticmethod
    def _amp_t(t, amp, h):
        if "full" in amp:
            return np.full(len(t), amp["full"][h])
        t = np.asarray(t, float)
        out = np.zeros(len(t))
        done = np.zeros(len(t), bool)
        for e in transition.EPOCHS:                 # (epoch_of, vectorized: the first epoch containing t)
            L, U = recurrence.SCOPES[e]
            m = ~done & (t >= L) & (t <= U)
            out[m] = amp.get(e, (0.0, 0.0))[h]
            done |= m
        return out

    def _amp_pairs(self, ti, tj, amp):
        if "full" in amp:
            return np.full(len(ti), amp["full"][0]), np.full(len(ti), amp["full"][1])
        aC = self._amp_t(tj, amp, 0)            # capture: by the predator time's epoch
        aQ = self._amp_t(ti, amp, 1)            # survival: by the prey time's epoch
        return aC, aQ

    # -------------------------------------------------------- native means and covariance
    def native(self, wg, lat):
        """Native expected responses (noise-free): within C, within Q, ref C, ref Q."""
        free = dict(zip(wg.prey.tolist(), sig(lat["F"]).tolist()))
        out = {"RC": sig(lat["RC"]), "RQ": sig(lat["RS"]) - np.array([free[t] for t in wg.qT])}
        if "C" in lat:
            out.update(C=sig(lat["C"]), Q=sig(lat["S"]) - np.array([free[t] for t in wg.ti]))
        return out

    def cov(self, wg, m, kind):
        """The plug-in bank covariance (Cov) of one panel block. m: per-channel replicate-mean fractions
        {"C" or "S": cells, "F": per prey snapshot}."""
        R = R_REP
        SR, SD = np.asarray(self.p["noise"]["SigmaR"], float), np.asarray(self.p["noise"]["SigmaD"], float)
        N = self.p["capture_bound"]

        def g(ch, x, n):
            x = np.clip(x, 0.5 / n, 1 - 0.5 / n)
            return noise_scale(self.p, ch, x) * x * (1 - x)
        ix = self._cov_index(wg, kind)
        rows = ix["rows"]
        if kind in ("C", "RC"):
            gg = g("C", m["C"], N)
            eC = 1 - SR[0, 0] - SD[0, 0]
            cols, d = [], gg ** 2 * eC / R
            for (col, ncol), var in zip(ix["cols"], (SR[0, 0], SD[0, 0])):
                M = np.zeros((len(rows), ncol))
                M[rows, col] = gg * math.sqrt(var / R)
                cols.append(M)
            return recurrence.Cov(d, np.hstack(cols))
        # survival: exposed cell minus its prey snapshot's free control
        gS = g("S", m["S"], TRIALS)
        gF = g("F", np.asarray(m["F"], float)[ix["prey_pos"]], TRIALS)
        L = np.linalg.cholesky(np.array([[SR[1, 1], SR[1, 2]], [SR[1, 2], SR[2, 2]]]) + 1e-15 * np.eye(2))
        eS, eF = 1 - SR[1, 1] - SD[1, 1], 1 - SR[2, 2]
        d = gS ** 2 * eS / R
        ci, nuk = ix["ci"], ix["nuk"]
        M = np.zeros((len(rows), 3 * nuk))
        M[rows, 3 * ci] = (gS * L[0, 0] - gF * L[1, 0]) / math.sqrt(R)
        M[rows, 3 * ci + 1] = (-gF * L[1, 1]) / math.sqrt(R)
        M[rows, 3 * ci + 2] = (-gF * math.sqrt(eF)) / math.sqrt(R)
        Md = np.zeros((len(rows), ix["npk"]))
        Md[rows, ix["pk"]] = gS * math.sqrt(SD[1, 1] / R)
        return recurrence.Cov(d, np.hstack([M, Md]))

    @staticmethod
    def _cov_index(wg, kind):
        """The graph-invariant sparsity of a block's loadings (built once per world graph; q33)."""
        cache = wg.__dict__.setdefault("_cov_idx", {})
        if kind in cache:
            return cache[kind]

        def index(keys):
            uk = {k: i for i, k in enumerate(sorted(set(keys), key=str))}
            return np.array([uk[k] for k in keys], dtype=np.int64), len(uk)
        if kind in ("C", "RC"):
            t_pred = wg.tj if kind == "C" else wg.cT
            prey_key = [("Q", t) for t in wg.ti] if kind == "C" else [("RQ", r) for r in wg.cR]
            ix = {"rows": np.arange(len(prey_key)), "cols": [index(prey_key), index([("P", t) for t in t_pred])]}
        else:
            prey_t = wg.ti if kind == "Q" else wg.qT
            pred_key = [("P", t) for t in wg.tj] if kind == "Q" else [("RP", r) for r in wg.qR]
            uk = {t: i for i, t in enumerate(sorted(set(prey_t.tolist())))}
            pos = {t: i for i, t in enumerate(wg.prey.tolist())}
            pk, npk = index(pred_key)
            ix = {"rows": np.arange(len(prey_t)), "ci": np.array([uk[t] for t in prey_t.tolist()], dtype=np.int64),
                  "nuk": len(uk), "pk": pk, "npk": npk,
                  "prey_pos": np.array([pos[t] for t in prey_t.tolist()], dtype=np.int64)}
        cache[kind] = ix
        return ix

    def ref_loads(self, wg, m, refkeys):
        """The shared-reference source loadings (H.4.2) of the world's two reference panels over the
        panel's global reference keys."""
        R = R_REP
        SR, SD = np.asarray(self.p["noise"]["SigmaR"], float), np.asarray(self.p["noise"]["SigmaD"], float)
        N = self.p["capture_bound"]
        xc = np.clip(m["RC"], 0.5 / N, 1 - 0.5 / N)
        gC = noise_scale(self.p, "C", xc) * xc * (1 - xc)
        LC = np.zeros((len(wg.cT), len(refkeys)))
        LC[np.arange(len(wg.cT)), [refkeys[("RQ", r)] for r in wg.cR]] = gC * math.sqrt(SR[0, 0] / R)
        xs = np.clip(m["RS"], 0.5 / TRIALS, 1 - 0.5 / TRIALS)
        gS = noise_scale(self.p, "S", xs) * xs * (1 - xs)
        LQ = np.zeros((len(wg.qT), len(refkeys)))
        LQ[np.arange(len(wg.qT)), [refkeys[("RP", r)] for r in wg.qR]] = gS * math.sqrt(SD[1, 1] / R)
        return {"C": LC, "Q": LQ}

    # -------------------------------------------------------- amplitude and slope solving
    def rms_of(self, wg, th, pl, u, amp, scope, h, dirC, dirQ):
        """Noise-free post-refit native RMS (relative for capture) on the world's reference panel."""
        lat = self.latent(wg, th, pl, u, amp, dirC, dirQ, refs_only=True)
        nat = self.native(wg, lat)
        key = "RC" if h == 0 else "RQ"
        t, r = (wg.cT, wg.cR) if h == 0 else (wg.qT, wg.qR)
        m = {"C": sig(lat["RC"]), "S": sig(lat["RS"]), "F": sig(lat["F"])}
        cv = self.cov(wg, m, key)
        # (q33: the readout's RMS alone, on the cached graph geometry; = RefDesign.readout's rms / den)
        rr = recurrence.ref_rms(t, r, cv, scope, pl["P"], nat[key])
        if rr is None:
            return math.nan
        rms, den = rr
        return rms / den if h == 0 else rms

    def solve_amp(self, wg, th, pl, u, amp, scope, h, target, dirC, dirQ):
        """The latent amplitude giving the target noise-free RMS (safeguarded secant on [0, A_MAX])."""
        def f(a):
            am = dict(amp)
            cur = list(am.get(scope, (0.0, 0.0)))
            cur[h] = a
            am[scope] = tuple(cur)
            return self.rms_of(wg, th, pl, u, am, scope, h, dirC, dirQ)
        if target == "max":
            return A_MAX
        hi_v = f(A_MAX)
        if not (hi_v >= target):
            self.unattainable.append({"world": wg.id, "scope": scope, "readout": "CQ"[h], "target": target,
                                      "max": hi_v})
            return A_MAX
        lo, hi, flo, fhi = 0.0, A_MAX, f(0.0) - target, hi_v - target
        if flo >= 0:
            return 0.0
        a = lo + (hi - lo) * (-flo) / (fhi - flo)
        for _ in range(40):
            fa = f(a) - target
            if abs(fa) <= 1e-7 * max(target, 1e-12):
                return a
            if fa < 0:
                lo, flo = a, fa
            else:
                hi, fhi = a, fa
            a_sec = lo + (hi - lo) * (-flo) / (fhi - flo)
            a = a_sec if lo < a_sec < hi and (hi - lo) > 1e-12 else (lo + hi) / 2
        return a

    # -------------------------------------------------------- simulate
    def simulate(self):
        p = self.p
        th_all = np.asarray(p["theta"], float)
        thbar = th_all.mean(axis=0)
        R, N = R_REP, p["capture_bound"]
        ar = p["ar"]
        rho = np.asarray(ar["rho"], float)
        Sig = np.asarray(ar["Sigma"], float)
        if self.stress:
            rho = np.full(5, STRESS_RHO)
            Sig = Sig * STRESS_SD ** 2
        rw = self.rng("worlds")
        refkeys = {}
        for wg in self.g:
            for r in wg.cR:
                refkeys.setdefault(("RQ", r), len(refkeys))
            for r in wg.qR:
                refkeys.setdefault(("RP", r), len(refkeys))
        # the shared reference components: one draw per reference key and replicate (block-shared)
        SR, SD = np.asarray(p["noise"]["SigmaR"], float), np.asarray(p["noise"]["SigmaD"], float)
        LR, LD = np.linalg.cholesky(SR + 1e-15 * np.eye(3)), np.linalg.cholesky(SD + 1e-15 * np.eye(2))
        zr = self.rng("reference-noise").normals(len(refkeys) * R * 3).reshape(len(refkeys), R, 3)
        ref_comp = {k: zr[i] @ (LR.T if k[0] == "RQ" else np.vstack([LD.T, np.zeros((1, 2))])[:3, :])
                    for k, i in refkeys.items()}
        self.worlds = []
        for k, wg in enumerate(self.g):
            s = int(rw.below(len(th_all), 1)[0])
            th = thbar + COEF_STRESS * (th_all[s] - thbar)
            pl = plan_world(self.hyp, self.mode, self.panel, k, rw)
            u = ar_paths(wg.times, rho, Sig, ar["step"], self.rng(f"ar/{wg.id}").normals(len(wg.times) * 5).reshape(-1, 5))
            dirC, dirQ = (lambda t: 0.0 * np.asarray(t, float)), (lambda t: 0.0 * np.asarray(t, float))
            if pl["dir"] is not None:
                dirC, dirQ = self.solve_dir(wg, th, pl, u)
            amp = {}
            for scope, tg in pl["rec"].items():
                cur = [0.0, 0.0]
                for h in (0, 1):
                    if tg[h] is not None:
                        am = dict(amp)
                        am[scope] = tuple(cur)
                        cur[h] = self.solve_amp(wg, th, pl, u, am, scope, h, tg[h], dirC, dirQ)
                amp[scope] = tuple(cur)
            lat = self.latent(wg, th, pl, u, amp, dirC, dirQ)
            mu = {ch: sig(lat[ch]) for ch in lat}
            self.worlds.append(self.observe(wg, mu, pl, k, ref_comp, refkeys, LR, LD))
            self.worlds[-1].update(id=wg.id, plan=pl, amp={s: list(v) for s, v in amp.items()}, graph=wg)
        return self

    def solve_dir(self, wg, th, pl, u):
        """Directional knobs meeting the epoch slope targets per world on noise-free data."""
        zero = {e: 0.0 for e in transition.EPOCHS}

        def make(sl):
            return lambda t: _cum_slope(t, sl)
        base = self.noiseless_betas(wg, th, pl, u, make(zero), make(zero))
        bC = {e: pl["dir"][e][0] - base[e][0] for e in transition.EPOCHS}
        dirC = make(bC)
        bQ = dict(zero)
        for e in transition.EPOCHS:                      # three secant steps per epoch, in time order
            tgt = pl["dir"][e][1]
            x0, f0 = 0.0, self.noiseless_betas(wg, th, pl, u, dirC, make(bQ), only=e, which="Q")[e][1] - tgt
            x1 = x0 + (-f0) * 4.0
            for _ in range(3):
                bQ[e] = x1
                f1 = self.noiseless_betas(wg, th, pl, u, dirC, make(bQ), only=e, which="Q")[e][1] - tgt
                if f1 == f0:
                    break
                x0, f0, x1 = x1, f1, x1 - f1 * (x1 - x0) / (f1 - f0)
            bQ[e] = x1
        return dirC, make(bQ)

    def noiseless_betas(self, wg, th, pl, u, dirC, dirQ, only=None, which="PQ"):
        lat = self.latent(wg, th, pl, u, {}, dirC, dirQ)
        return self.betas(wg, {"C": sig(lat["C"]) * self.p["capture_bound"] * R_REP,
                               "S": sig(lat["S"]) * TRIALS * R_REP, "F": sig(lat["F"]) * TRIALS * R_REP}, only, which)

    def betas(self, wg, K, only=None, which="PQ"):
        """Per-epoch backbone slopes (H.1-H.2 restricted to the epoch's focal times, the complete coarse
        opponent panels) from replicate-summed counts K {"C": cells, "S": cells, "F": prey snapshots}."""
        if not wg.coarse:
            raise CalibError(f"{wg.id}: the complete coarse panel is required for the epoch slopes")
        cell = {(a, b): i for i, (a, b) in enumerate(zip(wg.ti.tolist(), wg.tj.tolist()))}
        fr = dict(zip(wg.prey.tolist(), K["F"].tolist()))
        Nc = self.p["capture_bound"] * R_REP
        out = {}
        for e in transition.EPOCHS if only is None else (only,):
            L, U = recurrence.SCOPES[e]
            foc = [t for t in COARSE if L <= t <= U]
            bP = math.nan
            if "P" in which:
                cap = {i: (foc, [K["C"][cell[(i, j)]] for j in foc], [Nc] * len(foc)) for i in COARSE}
                bP = backbone.hp_world(cap, foc, (L, U))[0]
            free = (foc, [fr[t] for t in foc])
            exp_ = {j: (foc, [K["S"][cell[(i, j)]] for i in foc]) for j in COARSE}
            c, ds = backbone.fit_survival(free, exp_, (L, U), trials=TRIALS * R_REP)
            m = np.mean([backbone.q_curve(c, ds[j], foc, (L, U)) for j in sorted(ds)], axis=0)
            out[e] = (bP, backbone.slope(foc, m))
        return out

    def observe(self, wg, mu, pl, k, ref_comp, refkeys, LR, LD):
        """Counts by the actual sharing keys, replicate means, the plug-in covariances."""
        p, R, N = self.p, R_REP, self.p["capture_bound"]
        z = self.rng(f"noise/{wg.id}")
        SR, SD = np.asarray(p["noise"]["SigmaR"], float), np.asarray(p["noise"]["SigmaD"], float)
        eC, eS, eF = 1 - SR[0, 0] - SD[0, 0], 1 - SR[1, 1] - SD[1, 1], 1 - SR[2, 2]
        prey_t, pred_t = wg.prey, wg.pred
        Rw = (z.normals(len(prey_t) * R * 3).reshape(len(prey_t), R, 3)) @ LR.T          # C, S, F rows
        Dw = (z.normals(len(pred_t) * R * 2).reshape(len(pred_t), R, 2)) @ LD.T          # C, S donors
        EF = z.normals(len(prey_t) * R).reshape(len(prey_t), R) * math.sqrt(eF)
        pi = {t: i for i, t in enumerate(prey_t.tolist())}
        pj = {t: i for i, t in enumerate(pred_t.tolist())}
        I = np.array([pi[t] for t in wg.ti.tolist()])
        J = np.array([pj[t] for t in wg.tj.tolist()])
        stress, extra = self.stress, pl["extra"]
        # within: capture and exposed survival
        sC = noise_scale(p, "C", mu["C"], stress, extra)
        sS = noise_scale(p, "S", mu["S"], stress, extra)
        sF = noise_scale(p, "F", mu["F"], stress, extra)
        EC = z.normals(len(I) * R).reshape(len(I), R) * math.sqrt(eC)
        ES = z.normals(len(I) * R).reshape(len(I), R) * math.sqrt(eS)
        KC = counts(mu["C"][:, None], sC[:, None], sC[:, None] * (Rw[I, :, 0] + Dw[J, :, 0] + EC), N)
        KS = counts(mu["S"][:, None], sS[:, None], sS[:, None] * (Rw[I, :, 1] + Dw[J, :, 1] + ES), TRIALS)
        KF = counts(mu["F"][:, None], sF[:, None], sF[:, None] * (Rw[:, :, 2] + EF), TRIALS)
        # references: capture (prey reference shared, the world's predator donor), survival (the world's
        # prey row and free control, the predator reference's donor)
        Jc = np.array([pj[t] for t in wg.cT.tolist()])
        sRC = noise_scale(p, "C", mu["RC"], stress, extra)
        ERC = z.normals(len(Jc) * R).reshape(len(Jc), R) * math.sqrt(eC)
        RCs = np.array([ref_comp[("RQ", r)][:, 0] for r in wg.cR])
        KRC = counts(mu["RC"][:, None], sRC[:, None], sRC[:, None] * (RCs + Dw[Jc, :, 0] + ERC), N)
        Iq = np.array([pi[t] for t in wg.qT.tolist()])
        sRS = noise_scale(p, "S", mu["RS"], stress, extra)
        ERS = z.normals(len(Iq) * R).reshape(len(Iq), R) * math.sqrt(eS)
        RSd = np.array([ref_comp[("RP", r)][:, 1] for r in wg.qR])
        KRS = counts(mu["RS"][:, None], sRS[:, None], sRS[:, None] * (Rw[Iq, :, 1] + RSd + ERS), TRIALS)
        fmean = KF.mean(axis=1) / TRIALS
        y = {"within": {"C": KC.mean(axis=1) / N, "Q": KS.mean(axis=1) / TRIALS - fmean[I]},
             "ref": {"C": KRC.mean(axis=1) / N, "Q": KRS.mean(axis=1) / TRIALS - fmean[Iq]}}
        m = {"C": KC.mean(axis=1) / N, "S": KS.mean(axis=1) / TRIALS, "F": fmean,
             "RC": KRC.mean(axis=1) / N, "RS": KRS.mean(axis=1) / TRIALS}
        cov = {"C": self.cov(wg, {"C": m["C"]}, "C"), "Q": self.cov(wg, {"S": m["S"], "F": m["F"]}, "Q"),
               "RC": self.cov(wg, {"C": m["RC"]}, "RC"), "RQ": self.cov(wg, {"S": m["RS"], "F": m["F"]}, "RQ")}
        return {"y": y, "cov": cov, "K": {"C": KC.sum(axis=1), "S": KS.sum(axis=1), "F": KF.sum(axis=1)},
                "loads": self.ref_loads(wg, m, refkeys), "nref": len(refkeys)}

    # -------------------------------------------------------- analyses
    def design(self, w, scope):
        wg = w["graph"]
        return recurrence.WorldDesign(wg.id, {"C": (wg.ti, wg.tj, w["cov"]["C"]), "Q": (wg.ti, wg.tj, w["cov"]["Q"])},
                                      {"C": (wg.cT, wg.cR, w["cov"]["RC"]), "Q": (wg.qT, wg.qR, w["cov"]["RQ"])}, scope)

    def analyze_hf(self):
        """S_F, M_F (full history) and the epoch scores S_e (the H-T gates' calibration), every candidate's
        support decided by recurrence.analyze_world: the phase-conditional rule 6 at the fitted phase,
        exactly as in the main analysis."""
        out = {}
        for scope in ("full",) + transition.EPOCHS:
            res = recurrence.hf([recurrence.analyze_world(self.design(w, scope), w["y"]) for w in self.worlds])
            out[scope] = {"S": res["S_F"], "M": res["M_F"], "available": res["available"],
                          "phase_support": res["phase_support"], "positive": res["positive"]}
        return out

    def analyze_ht(self, gates_c, draws=stats.B_BOOT):
        epochs, betas = {}, {}
        for e in transition.EPOCHS:
            epochs[e] = [(self.design(w, e), w["y"]) for w in self.worlds]
            bs = {w["graph"].id: self.betas(w["graph"], w["K"], only=e)[e] for w in self.worlds}
            betas[e] = {"P": {i: b[0] for i, b in bs.items()}, "Q": {i: b[1] for i, b in bs.items()}}
        S = {e: recurrence.hf([recurrence.analyze_world(d, y) for d, y in epochs[e]])["S_F"] for e in transition.EPOCHS}
        gates = {e: S[e] > gates_c.get(e, 0.0) for e in transition.EPOCHS}
        loads = {w["graph"].id: w["loads"] for w in self.worlds}           # (by world id: #68 review 11)
        k = self.worlds[0]["nref"] if self.worlds else 0
        res = transition.ht(epochs, betas, gates, loads=loads, k=k, analysis=f"calib/{'/'.join(map(str, self.tag))}",
                            draws=draws, report=False)
        return {"T": res["T_T"], "S_e": S, "gates": gates, "available": res["available"],
                "winner": None if not res["winner"] else [res["winner"]["ARD"], res["winner"]["FSD"]],
                "phase_support": res["phase_support"], "EU_unsupported": res["EU_unsupported"]}


def run_panel(graph, params, hyp, stage, stratum, mode, panel, gates_c=None, draws=stats.B_BOOT):
    """One registered panel -> its JSON record (score, support report, CPU seconds, failures)."""
    t0 = time.process_time()
    rec = {"hyp": hyp, "stage": stage, "stratum": stratum, "mode": mode, "panel": panel}
    try:
        pn = Panel(stratum_worlds(graph, stratum), params, hyp, stage, stratum, mode, panel).simulate()
        rec["unattainable"] = pn.unattainable
        t1 = time.process_time()
        if hyp == "H-F":
            a = pn.analyze_hf()
            rec.update(score=a["full"]["S"], M=a["full"]["M"], S_e={e: a[e]["S"] for e in transition.EPOCHS},
                       available=a["full"]["available"], phase_support={s: a[s]["phase_support"] for s in a})
        else:
            a = pn.analyze_ht(gates_c or {}, draws)
            rec.update(score=a["T"], S_e=a["S_e"], gates=a["gates"], available=a["available"], winner=a["winner"],
                       phase_support=a["phase_support"], EU_unsupported=a["EU_unsupported"])
        rec["cpu"] = {"simulate": t1 - t0, "analyze": time.process_time() - t1}
    except (CalibError, recurrence.RecurrenceError, transition.TransitionError, backbone.BackboneError,
            np.linalg.LinAlgError, ValueError, FloatingPointError, KeyError) as e:
        rec.update(error=f"{type(e).__name__}: {e}", available=False)
    rec["cpu_total"] = time.process_time() - t0
    return rec


# ================================================================== critical values and acceptance
def strata_of(hyp):
    modes = F_MODES if hyp == "H-F" else T_MODES
    return [(m, s) for m in modes for s in STRATA]


def nth_dev_panel(hyp, n):
    st = strata_of(hyp)
    m, s = st[n % len(st)]
    return m, s, n // len(st)


def _score(r, key):
    """A panel's statistic; an unavailable decision or a failed panel cannot reject (-inf) but stays in
    every denominator (H.0.4); failures are counted and reported separately."""
    v = r.get(key)
    if v is None or not r.get("available", False) or r.get("error"):
        return -math.inf
    return v


def critical_values(records):
    """H.11 development critical values from development records (any order)."""
    by = {}
    for r in records:
        if r["stage"] != "dev":
            continue
        by.setdefault((r["hyp"], r["mode"], r["stratum"]), []).append(r)
    out = {"strata": {}}

    def stratum_crit(rs, key):
        sc = sorted(_score(r, key) if key in ("score", "M") else
                    (r["S_e"].get(key[2:], -math.inf) if r.get("S_e") and not r.get("error") else -math.inf)
                    for r in rs)
        k = math.ceil(0.99 * (len(sc) + 1))
        return sc[min(k, len(sc)) - 1]
    for (hyp, mode, s), rs in sorted(by.items()):
        if len(rs) != N_DEV:
            raise CalibError(f"{hyp} {mode} {s}: {len(rs)} development panels, {N_DEV} registered")
        rec = {"score": stratum_crit(rs, "score")}
        if hyp == "H-F":
            rec["M"] = stratum_crit(rs, "M")
            for e in transition.EPOCHS:
                rec[f"S_{e}"] = stratum_crit(rs, f"S_{e}")
        out["strata"][f"{hyp}|{mode}|{s}"] = rec

    def mx(hyp, modes, key):
        vals = [out["strata"][f"{hyp}|{m}|{s}"][key] for m in modes for s in STRATA if f"{hyp}|{m}|{s}" in out["strata"]]
        return max(vals) if vals else None
    out["c_F"] = mx("H-F", ("F0", "F1", "F2"), "score")
    out["c_M"] = mx("H-F", F_MODES, "M")
    out["c_E"] = {e: mx("H-F", ("F0", "F1", "F2"), f"S_{e}") for e in transition.EPOCHS}
    cT = mx("H-T", T_MODES, "score")
    out["c_T"] = None if cT is None else max(transition.GUARD, cT)
    return out


def p_model(s, tables):
    """max over the applicable validation strata of (1 + #{null >= s}) / (N + 1)."""
    return max((1 + sum(1 for v in t if v >= s)) / (len(t) + 1) for t in tables)


def acceptance(records, crit):
    """Independent validation: false positives of the complete locked rule per mode/stratum, U95."""
    tabs = {}
    for r in records:
        if r["stage"] == "val":
            tabs.setdefault((r["hyp"], r["mode"], r["stratum"]), []).append(r)
    out = {}
    det = {"H-F": [k for k in tabs if k[0] == "H-F" and k[1] in ("F0", "F1", "F2")],
           "H-T": [k for k in tabs if k[0] == "H-T"]}
    mat = [k for k in tabs if k[0] == "H-F"]
    for key, rs in sorted(tabs.items()):
        hyp = key[0]
        if hyp == "H-F":
            tables = [[_score(r, "score") for r in tabs[k]] for k in det["H-F"]]
            fp = sum(1 for r in rs if _score(r, "score") > crit["c_F"] and p_model(_score(r, "score"), tables) <= 0.01)
            raw = sum(1 for r in rs if _score(r, "score") > crit["c_F"])
            mt = [[_score(r, "M") for r in tabs[k]] for k in mat]
            fpm = sum(1 for r in rs if _score(r, "M") > crit["c_M"] and p_model(_score(r, "M"), mt) <= 0.01)
            n = len(rs)
            rec = {"n": n, "material_fp": fpm, "material_U95": stats.clopper_pearson_upper(fpm, n),
                   "material_pass": stats.acceptance(fpm, n)}
            if key[1] in ("F0", "F1", "F2"):
                rec.update(fp=fp, U95=stats.clopper_pearson_upper(fp, n), passes=stats.acceptance(fp, n),
                           raw_detection_fp=raw)
            out["|".join(map(str, key))] = rec
        else:
            tables = [[_score(r, "score") for r in tabs[k]] for k in det["H-T"]]
            fp = sum(1 for r in rs if _score(r, "score") > crit["c_T"] and p_model(_score(r, "score"), tables) <= 0.01)
            n = len(rs)
            out["|".join(map(str, key))] = {"n": n, "fp": fp, "U95": stats.clopper_pearson_upper(fp, n),
                                            "passes": stats.acceptance(fp, n)}
    return out


# ================================================================== CLI
def read_records(paths):
    out = []
    for p in paths:
        with open(p) as f:
            out.extend(json.loads(ln) for ln in f if ln.strip())
    return out


def get_graph(a):
    if a.graph:
        return load_graph(a.graph)
    return synthetic_graph(a.synthetic_worlds)


def get_params(a):
    if a.params:
        with open(a.params) as f:
            return json.load(f)
    return placeholder_params()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("panels", "bench"):
        s = sub.add_parser(name)
        s.add_argument("--hyp", choices=("H-F", "H-T"), required=True)
        s.add_argument("--graph")
        s.add_argument("--synthetic-worlds", type=int, default=32)
        s.add_argument("--params")
        s.add_argument("--gates", help="crit.json with the frozen epoch gates (H-T)")
        s.add_argument("--draws", type=int, default=stats.B_BOOT)
        if name == "panels":
            s.add_argument("--stage", choices=("dev", "val", "alt"), required=True)
            s.add_argument("--mode", required=True)
            s.add_argument("--stratum", choices=STRATA, required=True)
            s.add_argument("--from", dest="lo", type=int, default=0)
            s.add_argument("--to", dest="hi", type=int, required=True)
            s.add_argument("--out", required=True)
        else:
            s.add_argument("--panels", type=int, default=50)
            s.add_argument("--out")
    s = sub.add_parser("crit")
    s.add_argument("files", nargs="+")
    s = sub.add_parser("accept")
    s.add_argument("--crit", required=True)
    s.add_argument("files", nargs="+")
    a = ap.parse_args(argv)
    if a.cmd in ("panels", "bench"):
        graph, params = get_graph(a), get_params(a)
        gates = {}
        if a.gates:
            with open(a.gates) as f:
                gates = json.load(f)["c_E"]
        if a.cmd == "panels":
            with open(a.out, "a") as f:
                for k in range(a.lo, a.hi):
                    r = run_panel(graph, params, a.hyp, a.stage, a.stratum, a.mode, k, gates, a.draws)
                    f.write(json.dumps(r, sort_keys=True) + "\n")
                    f.flush()
            return 0
        recs = []
        for n in range(a.panels):
            m, s, k = nth_dev_panel(a.hyp, n)
            r = run_panel(graph, params, a.hyp, "dev", s, m, k, gates, a.draws)
            recs.append(r)
            print(f"{n:3d} {m} {s:8s} panel {k}: score {r.get('score')} cpu {r['cpu_total']:.2f}s"
                  + (f" ERROR {r['error']}" if r.get("error") else ""), flush=True)
        cpu = [r["cpu_total"] for r in recs]
        summ = {"hyp": a.hyp, "panels": len(recs), "mean_cpu_s": sum(cpu) / len(cpu), "max_cpu_s": max(cpu),
                "target_s": stats.cpu_targets()["target_cpu_s_per_panel"],
                "errors": sum(1 for r in recs if r.get("error")), "params_fitted": params.get("fitted", False),
                "worlds": len(graph)}
        print(json.dumps(summ, indent=1))
        if a.out:
            with open(a.out, "w") as f:
                json.dump({"summary": summ, "records": recs}, f, sort_keys=True)
        return 0
    if a.cmd == "crit":
        print(json.dumps(critical_values(read_records(a.files)), indent=1, sort_keys=True))
        return 0
    with open(a.crit) as f:
        crit = json.load(f)
    print(json.dumps(acceptance(read_records(a.files), crit), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

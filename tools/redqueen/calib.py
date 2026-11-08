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
  Red variation: five diagonal processes with correlated innovations, an exact irregular-time OU form
  (ou_matrices): rho per 5M step in (0, 0.98], the one-step innovation covariance S = 0.95 Sigma +
  0.05 tr(Sigma)/5 I; kappa = -log rho, the diffusion Q = S o (kappa_i + kappa_j) / (1 - rho_i rho_j)
  must be PSD (check_params refuses parameters without that OU form), so every gap's transition
  covariance Gamma o (1 - (rho_i rho_j)^D) (Gamma = S / (1 - rho rho'), the stationary start) is PSD.
  Validation stress: rho = 0.98, innovation SD x 1.5.
  Observation (H.9.2): K = floor(N sigma(a + eps) + 1/2), N = the capture bound or 600; eps = s(mu) (R +
  D + E) with the row (prey snapshot: C, S, F channels), donor (predator snapshot: C, S) and cell
  (SigmaE: capture and exposed survival of one assay cell JOINTLY, their cross-channel covariance kept)
  components by the ACTUAL sharing keys (a reference is one snapshot shared by its block's worlds; a
  free control is generated once per prey snapshot and replicate and reused), unit total latent
  variance per channel; s(mu) by the mean bins [0,.35), [.35,.70), [.70,1] (capture) and [0,.25),
  [.25,.75), [.75,1] (survival); a(mu) solves E[K/N] = mu over the FULL intended range (no clipping):
  E[K] = sum_k Phi((a - logit((k - 1/2)/N)) / s) exactly, tabulated on a 0.004 logit grid per (s, N)
  and inverted by linear interpolation whose error is verified at every grid midpoint (<= 2e-7).
  Validation stress: s_C = max(1.5 s_bank, 0.80 below 0.35 else 0.35), survival 1.5 s_bank. No second
  binomial layer.
  Recurrence (H.9.3): world period uniform on the registered grid, phase uniform; a lag harmonic
  cos(omega (t_j - t_i) - phi) within the world and cos(omega t - phi) on the reference panels, one latent
  amplitude per readout (and epoch), solved (safeguarded secant) so that the NOISE-FREE post-refit
  native RMS on the world's reference panel (recurrence.RefDesign, the actual graph and metric) equals
  the target (convergence required); "max" (as large as bounded means permit) = the amplitude in [0, 6]
  MAXIMIZING the native RMS (grid + golden section); an unattainable target is recorded: an alternative
  is then a non-success, a null panel fails (never redrawn); a background already above a target is
  recorded as a deviation (above a boundary null: conservative). D2 (2026-11-08): a NULL world with an
  unattainable target is redrawn from the same null mode with the next registered seed (its own redraw
  streams), at most 5 times; beyond that the panel is INFEASIBLE (recorded, not a failure), its mode x
  stratum is declared infeasible and reported (excluded from the critical maxima and the acceptance
  rates); the redraw rate per mode is reported.
  Directional knobs (H-T modes): per epoch, a latent focal-time slope (capture: predator time; exposed
  survival: prey time), continuous, linear within each epoch. The knobs and the amplitudes are solved
  JOINTLY (alternating, each with the other present) and the COMPLETED noise-free panel is verified
  against every declared constraint (epoch slopes to 1e-5, RMS targets to 1e-6 relative); a panel that
  does not verify fails.
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
c_E1..c_E3 (S_e) over F0-F2, c_T = max(log 600, over T0-T4). Every allocation must be COMPLETE: every
mode x graph stratum, panels 0..n-1 each once, no failed panel (a failure is repaired and rerun, H.12),
one manifest (graph, parameters, tools, draws, gates), production records only (fitted parameters,
the real graph, 9,999 draws). Validation (acceptance) is INDEPENDENT of the panels it judges: the
false positives of the FROZEN critical rules (the model p-value can only reduce rejections) on the
1,000-panel validation allocation per mode x graph stratum: H-F detection (F0-F2: the raw reciprocal
rule), the nested exceeding-material claim (F0-F4), each epoch gate (F0-F2), H-T (T0-T4; T4 subtype
rates as diagnostics); U95 <= 0.02 for every rate. The validation null scores then form the p-tables
of the final evaluation (p_m(s) = (1 + #{null >= s}) / 1001, p_model = max_m). H-T needs the FROZEN
epoch-gate artifact (`gates`: every epoch's c_E with a passing validation); without it H-T is
unavailable. Power: development alternatives with Wilson intervals, H-T by generating direction.
BENCHMARK (H.12). `calib.py bench` runs the first 50 development panels of a hypothesis (the ten strata
in turn) with every fit, period, window, material rule, epoch, direction and bootstrap used in the
decision, and reports CPU seconds per panel against the 13.5 s target (smoke records: never accepted
by crit / accept).

    python3 calib.py panels --hyp H-F --stage dev --graph g.jsonl.gz --params fitted.json --mode F0 \\
        --stratum actual --to 160 --out dev_HF.jsonl                       (production; --smoke for tests)
    python3 calib.py crit dev_HF.jsonl > crit_HF.json
    python3 calib.py accept --crit crit_HF.json val_HF.jsonl > acc_HF.json
    python3 calib.py gates --crit crit_HF.json --accept acc_HF.json --out gates.json
    python3 calib.py panels --hyp H-T ... --gates gates.json ...; crit / accept / power likewise
    python3 calib.py bench --hyp H-F [--graph g.jsonl.gz] [--params p.json] [--panels 50]
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
AMP_TOL = 1e-7           # the amplitude solver's relative RMS tolerance
DIR_TOL = 1e-5           # the declared epoch slopes, met on the completed noise-free panel to this (absolute)
DIR_STEPS = 12
KNOB_MAX = 8.0           # |a directional knob| in latent logit per 50M
JOINT_ROUNDS = 24
REDRAW_CAP = 5           # D2: redraws of a null world with unattainable targets before the panel is infeasible
NTHETA = 98
F_MODES = ("F0", "F1", "F2", "F3", "F4")
T_MODES = ("T0", "T1", "T2", "T3", "T4")
ALT = {"H-F": ("FA1", "FA2"), "H-T": ("TA1", "TA2")}
STRATA = ("actual", "stress24")
N_DEV, N_VAL, N_ALT = 160, 1000, 100
GREVILLE = np.array([0.0, 1 / 9, 1 / 3, 2 / 3, 8 / 9, 1.0])


class CalibError(Exception):
    pass


class PanelInfeasible(CalibError):
    """A null panel whose declared targets stay unattainable after the capped redraws (D2): recorded as
    infeasible (its mode reported), never a failed panel."""


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
                      "SigmaD": [[0.25, 0.05], [0.05, 0.25]],
                      "SigmaE": [[0.5, 0.1], [0.1, 0.5]]},
            "capture_bound": capture_bound, "replicates": R_REP}


def ou_matrices(rho, S):
    """The red variation as an exact irregular-time diagonal OU process (H.9.1; #68 round 2, P2-9). rho:
    per-step autocorrelations, S: the innovation covariance of one registered step (after the shrinkage).
    -> (kappa = -log rho per step, the diffusion Q = S o (kappa_i + kappa_j) / (1 - rho_i rho_j), the
    stationary Gamma = Q / (kappa_i + kappa_j) = S / (1 - rho rho')). A gap of D steps then has transition
    exp(-kappa D) and innovation covariance Gamma o (1 - (rho_i rho_j)^D) = integral_0^D e^{-kappa s} Q
    e^{-kappa s} ds: PSD at EVERY gap exactly when Q is PSD (checked by check_params)."""
    rho = np.asarray(rho, float)
    kap = -np.log(rho)
    rr = np.outer(rho, rho)
    Q = S * (kap[:, None] + kap[None, :]) / (1 - rr)
    return kap, Q, S / (1 - rr)


def shrunk(Sigma):
    S = np.asarray(Sigma, float)
    d = S.shape[0]
    return 0.95 * S + 0.05 * np.trace(S) / d * np.eye(d)


def check_params(p, production=False):
    """The generator parameters: shapes and constraints (#68 round 2: the OU consistency of the red
    variation, the cell covariance, positive noise scales); production also needs FITTED parameters."""
    if p.get("schema") != SCHEMA:
        raise CalibError(f"generator parameters: schema {p.get('schema')!r}")
    if production and p.get("fitted") is not True:
        raise CalibError("generator parameters: production calibration needs FITTED parameters (H.9.1-H.9.2), "
                         "not the synthetic placeholder")
    th = np.asarray(p["theta"], float)
    if th.ndim != 2 or th.shape[1] != NTHETA or len(th) < 2:
        raise CalibError("generator parameters: theta must be (training worlds >= 2) x 98")
    rho = np.asarray(p["ar"]["rho"], float)
    if np.any(rho <= 0) or np.any(rho > 0.98):
        raise CalibError("generator parameters: each autoregression lies in (0, 0.98] (rho = 0 has no "
                         "irregular-time OU form)")
    for stress in (False, True):
        r = np.full(len(rho), STRESS_RHO) if stress else rho
        S = shrunk(p["ar"]["Sigma"]) * (STRESS_SD ** 2 if stress else 1.0)
        if np.min(np.linalg.eigvalsh(S)) <= 0:
            raise CalibError("generator parameters: the (shrunk) innovation covariance is not positive definite")
        Q = ou_matrices(r, S)[1]
        if np.min(np.linalg.eigvalsh((Q + Q.T) / 2)) < -1e-12 * max(1.0, float(np.max(np.abs(Q)))):
            raise CalibError("generator parameters: the innovation covariance and the autoregressions have no "
                             "PSD irregular-time diffusion (OU) form: refit in the OU parametrization")
    nz = p["noise"]
    for k in ("SigmaR", "SigmaD", "SigmaE"):
        if k not in nz:
            raise CalibError(f"generator parameters: noise.{k} is required (H.9.2: row, donor AND cell)")
        if np.min(np.linalg.eigvalsh(np.asarray(nz[k], float))) < -1e-12:
            raise CalibError(f"generator parameters: {k} is not PSD")
    SR, SD, SE = (np.asarray(nz[k], float) for k in ("SigmaR", "SigmaD", "SigmaE"))
    tot = np.diag(SR)[:2] + np.diag(SD) + np.diag(SE)
    if np.any(np.abs(tot - 1) > 1e-9) or SR[2, 2] > 1:
        raise CalibError("generator parameters: row + donor + cell variance must be the unit latent variance "
                         "(capture and exposed survival), the free row at most 1")
    for ch in ("C", "S", "F"):
        if np.any(np.asarray(nz["s"][ch], float) <= 0):
            raise CalibError(f"generator parameters: noise scales s_{ch} must be positive")
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


LOC_STEP = 0.004          # the location table's spacing in a (logit units)
LOC_TOL = 2e-7            # the verified bound on |E[K/N](a(mu)) - mu| (interpolation)
def erfc(x):
    """erfc, vectorized: the alternating Taylor series of erf below |x| = 2, the continued fraction of erfc
    above (relative error <= 1e-12 against math.erfc on [-9, 30]; test_calib checks it)."""
    x = np.asarray(x, float)
    out = np.empty_like(x)
    ax = np.abs(x)
    sm = ax < 2.0
    xs = x[sm]
    x2 = xs * xs
    term, s = xs.copy(), xs.copy()
    for n in range(1, 70):
        term = term * (-x2) / n
        s = s + term / (2 * n + 1)
    out[sm] = 1.0 - 2.0 / math.sqrt(math.pi) * s
    xl = ax[~sm]
    f = xl.copy()
    for n in range(90, 0, -1):
        f = xl + (n / 2.0) / f
    val = np.exp(-xl * xl) / math.sqrt(math.pi) / f
    out[~sm] = np.where(x[~sm] > 0, val, 2.0 - val)
    return out


def expected_fraction(a, s, N):
    """E[floor(N sigma(a + s Z) + 1/2)] / N EXACTLY (no quadrature, #68 round 2 P2-6): K >= k iff
    sigma(a + sZ) >= (k - 1/2) / N, so E[K] = sum_{k=1..N} Phi((a - logit((k - 1/2)/N)) / s)."""
    a = np.atleast_1d(np.asarray(a, float))
    lk = logit((np.arange(1, N + 1) - 0.5) / N)
    res = np.empty(len(a))
    for c0 in range(0, len(a), 256):                          # (chunks: bounded memory)
        z = (a[c0:c0 + 256, None] - lk[None, :]) / s
        out = np.where(z > 9.0, 1.0, 0.0)                     # (Phi beyond +-9: 1 or 0 within 1e-19)
        mid = np.abs(z) <= 9.0
        out[mid] = 0.5 * erfc(-z[mid] / math.sqrt(2.0))
        res[c0:c0 + 256] = out.sum(axis=1)
    return res / N


def location_table(s, N):
    """a on a uniform grid and E[K/N](a) (exact), over the range where the expectation leaves (1e-12,
    1 - 1e-12); the linear interpolation's error is VERIFIED at every grid midpoint (<= LOC_TOL)."""
    key = (float(s), int(N))
    if key not in _LOC:
        lo, hi = float(logit(0.5 / N)) - 9.0 * s - 2.0, float(logit(1 - 0.5 / N)) + 9.0 * s + 2.0
        a = np.arange(lo, hi + LOC_STEP, LOC_STEP)
        f = expected_fraction(a, s, N)
        if np.any(np.diff(f) < 0):
            raise CalibError(f"the rounded-count expectation is not monotone (s {s}, N {N})")
        fm = expected_fraction((a[1:] + a[:-1]) / 2, s, N)
        err = float(np.max(np.abs(fm - (f[1:] + f[:-1]) / 2)))
        if err > LOC_TOL:
            raise CalibError(f"the location table's interpolation error {err:.2e} exceeds {LOC_TOL} (s {s}, N {N})")
        _LOC[key] = (a, f, err)
    return _LOC[key]


def location(mu, s, N):
    """a(mu) with E[floor(N sigma(a + s Z) + 1/2)] / N = mu, Z ~ N(0, 1) (vectorized over cells), over the
    FULL intended range (0, 1): no clipping, so distinct intended means keep distinct expected fractions
    (#68 round 2 P2-6); a mean outside the table's range is refused."""
    mu, s = np.asarray(mu, float), np.asarray(s, float)
    out = np.empty_like(mu)
    for sv in np.unique(s):
        a, f, _ = location_table(sv, N)
        m = s == sv
        x = mu[m]
        if np.any(x <= f[0]) or np.any(x >= f[-1]) or not np.all(np.isfinite(x)):
            raise CalibError(f"an intended mean outside ({f[0]:.3g}, {1 - f[-1]:.3g} from 1): the bounded model "
                             "cannot attain it")
        out[m] = np.interp(x, f, a)
    return out


def counts(mu, s, eps, N):
    """K = floor(N sigma(a(mu) + eps) + 1/2) (eps already scaled by s(mu))."""
    return np.floor(N * sig(location(mu, s, N) + eps) + 0.5)


# ================================================================== red variation
def ar_paths(times, rho, Sigma, step, z):
    """Five diagonal OU (AR(1) at the registered step) processes at sorted irregular times, exact,
    stationary start (ou_matrices: PSD transition covariances at every gap); a covariance that is not PSD
    is a CalibError, never a jittered Cholesky."""
    rho = np.asarray(rho, float)
    S = shrunk(Sigma)
    d = S.shape[0]
    _, Q, Gam = ou_matrices(rho, S)
    rr = np.outer(rho, rho)

    def chol(C, what):
        C = (C + C.T) / 2
        w, V = np.linalg.eigh(C)
        if w.min() < -1e-12 * max(1.0, float(w.max())):
            raise CalibError(f"the red-variation {what} covariance is not PSD (min eigenvalue {w.min():.3g})")
        return V * np.sqrt(np.clip(w, 0.0, None))          # (a PSD square root: exact for singular C)
    x = np.zeros((len(times), d))
    x[0] = chol(Gam, "stationary") @ z[0]
    for k in range(1, len(times)):
        D = (times[k] - times[k - 1]) / step
        x[k] = rho ** D * x[k - 1] + chol(Gam * (1 - rr ** D), f"gap-{D:g}") @ z[k]
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
        self.unattainable, self.deviations, self.verified, self.achieved = [], [], [], {}
        self._metric, self.redraws = {}, []

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
        """Noise-free post-refit native RMS (relative for capture) on the world's reference panel. The
        projection's metric is the plug-in bank model at the world's BASE noise-free means (no periodic
        amplitude, no directional knob; #68 round 2): one fixed metric per world, so the RMS is continuous
        in the amplitudes and knobs (the bank's binned noise scales would otherwise switch the metric, and
        jump the RMS, as an amplitude crosses a bin)."""
        lat = self.latent(wg, th, pl, u, amp, dirC, dirQ, refs_only=True)
        nat = self.native(wg, lat)
        key = "RC" if h == 0 else "RQ"
        t, r = (wg.cT, wg.cR) if h == 0 else (wg.qT, wg.qR)
        ok = (wg.id, key, scope, pl["P"])
        if ok not in self._metric:
            z0 = lambda t_: 0.0 * np.asarray(t_, float)  # noqa: E731
            lat0 = self.latent(wg, th, pl, u, {}, z0, z0, refs_only=True)
            cv = self.cov(wg, {"C": sig(lat0["RC"]), "S": sig(lat0["RS"]), "F": sig(lat0["F"])}, key)
            # (q33: the readout's RMS alone, on the cached graph geometry; = RefDesign.readout's rms / den)
            self._metric[ok] = recurrence.ref_rms_op(t, r, cv, scope, pl["P"])
        op = self._metric[ok]
        rr = None if op is None else op(nat[key])
        if rr is None:
            return math.nan
        rms, den = rr
        return rms / den if h == 0 else rms

    def solve_amp(self, wg, th, pl, u, amp, scope, h, target, dirC, dirQ):
        """The latent amplitude giving the target noise-free post-refit native RMS (safeguarded secant on
        [0, A_MAX]; CONVERGENCE REQUIRED: exhaustion is a CalibError). "max": the amplitude maximizing the
        native RMS (as large as bounded means permit, H.10). An unattainable target is recorded (an
        alternative: a non-success; a null: a failed panel); a background already above the target is
        recorded as a deviation (the panel stays: above a boundary null is conservative)."""
        def f(a):
            am = dict(amp)
            cur = list(am.get(scope, (0.0, 0.0)))
            cur[h] = a
            am[scope] = tuple(cur)
            return self.rms_of(wg, th, pl, u, am, scope, h, dirC, dirQ)
        tag = {"world": wg.id, "scope": scope, "readout": "CQ"[h], "target": target}
        if target == "max":
            return self.native_max(f)
        hi_v = f(A_MAX)
        if not (hi_v >= target):
            a_m = self.native_max(f)
            v_m = f(a_m)
            if v_m >= target:                       # (the RMS is not monotone in the latent amplitude)
                hi_v, top = v_m, a_m
            else:
                self.unattainable.append(dict(tag, max=v_m))
                return a_m
        else:
            top = A_MAX
        lo, hi, flo, fhi = 0.0, top, f(0.0) - target, hi_v - target
        if not math.isfinite(flo) or not math.isfinite(fhi):
            raise CalibError(f"{wg.id} {scope} {'CQ'[h]}: a nonfinite noise-free RMS")
        key = (wg.id, scope, h)
        if flo >= 0:
            self.deviations.append(dict(tag, type="background", achieved=flo + target))
            self.achieved[key] = flo + target
            return 0.0
        a = lo + (hi - lo) * (-flo) / (fhi - flo)
        for it in range(200):
            fa = f(a) - target
            if abs(fa) <= AMP_TOL * max(target, 1e-12):
                self.achieved[key] = fa + target
                return a
            if fa < 0:
                lo, flo = a, fa
            else:
                hi, fhi = a, fa
            if hi - lo <= 1e-11 * max(1.0, hi):
                # the bracket closed on a JUMP of the noise-free RMS (the plug-in metric's noise-scale bins
                # switch there): the upper side, at least the target (a boundary null: conservative), recorded
                self.deviations.append(dict(tag, type="metric_discontinuity", achieved=fhi + target,
                                            below=flo + target))
                self.achieved[key] = fhi + target
                return hi
            a_sec = lo + (hi - lo) * (-flo) / (fhi - flo)
            a = a_sec if (lo < a_sec < hi and it < 40 and (hi - lo) > 1e-9) else (lo + hi) / 2
        raise CalibError(f"{wg.id} {scope} {'CQ'[h]}: the amplitude solver did not converge to RMS {target}")

    @staticmethod
    def native_max(f):
        """argmax over [0, A_MAX] of the native RMS f (a 13-point grid, then golden-section refinement)."""
        grid = np.linspace(0.0, A_MAX, 13)
        vals = [f(a) for a in grid]
        if not all(math.isfinite(v) for v in vals):
            raise CalibError("a nonfinite noise-free RMS in the maximum search")
        k = int(np.argmax(vals))
        lo, hi = grid[max(k - 1, 0)], grid[min(k + 1, len(grid) - 1)]
        g = (math.sqrt(5) - 1) / 2
        x1, x2 = hi - g * (hi - lo), lo + g * (hi - lo)
        f1, f2 = f(x1), f(x2)
        for _ in range(24):
            if f1 >= f2:
                hi, x2, f2 = x2, x1, f1
                x1 = hi - g * (hi - lo)
                f1 = f(x1)
            else:
                lo, x1, f1 = x1, x2, f2
                x2 = lo + g * (hi - lo)
                f2 = f(x2)
        best = max([(vals[k], grid[k]), (f1, x1), (f2, x2)])
        return float(best[1])

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
            for j in range(REDRAW_CAP + 1):
                n0 = len(self.unattainable)
                dirC, dirQ, amp, ver = self.solve_joint(wg, th, pl, u)
                if len(self.unattainable) == n0 or self.stage == "alt":     # (an alternative: a non-success)
                    break
                # D2 (2026-11-08): a NULL world whose declared target bounded means cannot attain is
                # REDRAWN from the same null mode with the next registered seed (its own redraw streams:
                # the other worlds' draws are untouched), at most REDRAW_CAP times; beyond the cap the
                # panel is infeasible (recorded and reported; not a failed calibration)
                self.redraws.append({"world": wg.id, "redraw": j + 1, "unattainable": self.unattainable[n0:]})
                del self.unattainable[n0:]
                if j == REDRAW_CAP:
                    raise PanelInfeasible(f"{wg.id}: null targets unattainable after {REDRAW_CAP} redraws")
                rr = self.rng(f"redraw/{wg.id}/{j + 1}")
                s = int(rr.below(len(th_all), 1)[0])
                th = thbar + COEF_STRESS * (th_all[s] - thbar)
                pl = plan_world(self.hyp, self.mode, self.panel, k, rr)
                u = ar_paths(wg.times, rho, Sig, ar["step"],
                             self.rng(f"ar/{wg.id}/redraw{j + 1}").normals(len(wg.times) * 5).reshape(-1, 5))
                self._metric = {key: v for key, v in self._metric.items() if key[0] != wg.id}
            self.verified.append(dict(ver, world=wg.id))
            lat = self.latent(wg, th, pl, u, amp, dirC, dirQ)
            mu = {ch: sig(lat[ch]) for ch in lat}
            self.worlds.append(self.observe(wg, mu, pl, k, ref_comp, refkeys, LR, LD))
            self.worlds[-1].update(id=wg.id, plan=pl, amp={s: list(v) for s, v in amp.items()}, graph=wg)
        return self

    def solve_amps(self, wg, th, pl, u, dirC, dirQ):
        amp = {}
        for scope, tg in pl["rec"].items():
            cur = [0.0, 0.0]
            for h in (0, 1):
                if tg[h] is not None:
                    am = dict(amp)
                    am[scope] = tuple(cur)
                    cur[h] = self.solve_amp(wg, th, pl, u, am, scope, h, tg[h], dirC, dirQ)
            amp[scope] = tuple(cur)
        return amp

    def solve_joint(self, wg, th, pl, u):
        """The directional knobs and the periodic amplitudes solved JOINTLY (#68 round 2 P2-7): the slopes
        are solved WITH the amplitudes present, the amplitudes with the slopes present, alternating until
        the final noise-free panel meets every declared constraint (verify); otherwise a CalibError (a
        failed panel), never an unchecked panel."""
        E = transition.EPOCHS
        zero = {e: 0.0 for e in E}
        dirC = dirQ = (lambda t: _cum_slope(t, zero))
        knobs, amp, seq = None, {}, []
        for r in range(JOINT_ROUNDS):
            u0, d0 = len(self.unattainable), len(self.deviations)
            if pl["dir"] is not None:
                dirC, dirQ, knobs = self.solve_dir(wg, th, pl, u, amp, knobs)
                seq.append((dict(knobs[0]), dict(knobs[1])))
            amp = self.solve_amps(wg, th, pl, u, dirC, dirQ)
            ver = self.verify(wg, th, pl, u, amp, dirC, dirQ)
            if ver["ok"]:
                return dirC, dirQ, amp, dict(ver, rounds=r + 1)
            if pl["dir"] is None:
                break
            del self.unattainable[u0:], self.deviations[d0:]     # (the next round records its own)
            if len(seq) >= 3 and len(seq) % 3 == 0 and pl["rec"]:
                # the alternation knob -> amplitude -> knob converges linearly (often oscillating): Aitken's
                # extrapolation of the knobs, the amplitudes re-solved there, then the alternation resumes
                ext = []
                for c in (0, 1):
                    y0, y1, y2 = (s_[c] for s_ in seq[-3:])
                    x = {}
                    for e in E:
                        d1, d2 = y1[e] - y0[e], y2[e] - y1[e]
                        x[e] = y2[e] - d2 * d2 / (d2 - d1) if abs(d2 - d1) > 1e-15 else y2[e]
                        if not abs(x[e]) <= KNOB_MAX:
                            x[e] = y2[e]
                    ext.append(x)
                knobs = tuple(ext)
                amp = self.solve_amps(wg, th, pl, u, (lambda t, s_=dict(ext[0]): _cum_slope(t, s_)),
                                      (lambda t, s_=dict(ext[1]): _cum_slope(t, s_)))
        raise CalibError(f"{wg.id}: the declared constraints are not met after the joint solve: "
                         f"{ver['violations'][:3]}")

    def verify(self, wg, th, pl, u, amp, dirC, dirQ):
        """The completed NOISE-FREE panel against its declared constraints: every directional epoch slope
        (beta_P, beta_Q) and every numeric post-refit RMS target (an unattainable one is the recorded
        exception: a non-success alternative / a failed null)."""
        viol, out = [], {"dir": {}, "rms": {}}
        if pl["dir"] is not None:
            b = self.noiseless_betas(wg, th, pl, u, dirC, dirQ, amp=amp)
            skip = {(x["scope"], x["readout"]) for x in self.unattainable if x["world"] == wg.id}
            for e in transition.EPOCHS:
                for i, nm in ((0, "beta_P"), (1, "beta_Q")):
                    err = b[e][i] - pl["dir"][e][i]
                    out["dir"][f"{e}/{nm}"] = b[e][i]
                    if (e, nm) not in skip and not abs(err) <= DIR_TOL:
                        viol.append(f"{e} {nm} {b[e][i]:.6g} vs {pl['dir'][e][i]:.6g}")
        miss = {(x["scope"], x["readout"]) for x in self.unattainable if x["world"] == wg.id}
        for scope, tg in pl["rec"].items():
            for h in (0, 1):
                if tg[h] is None or tg[h] == "max" or (scope, "CQ"[h]) in miss:
                    continue
                v = self.rms_of(wg, th, pl, u, amp, scope, h, dirC, dirQ)
                out["rms"][f"{scope}/{'CQ'[h]}"] = v
                ach = self.achieved.get((wg.id, scope, h))
                # the completed panel reproduces the solver's value, which is the target (to AMP_TOL) or the
                # recorded upper side of a jump / a background above it: never below the target
                if ach is None or not abs(v - ach) <= 1e-9 * max(ach, 1e-12) or v < tg[h] * (1 - 10 * AMP_TOL):
                    viol.append(f"{scope} RMS {'CQ'[h]} {v:.6g} vs target {tg[h]} (solved {ach})")
        out.update(ok=not viol, violations=viol)
        return out

    def solve_dir(self, wg, th, pl, u, amp, init=None):
        """Directional knobs meeting the epoch slope targets per world on noise-free data, with the
        periodic amplitudes amp present: capture exactly (the fitted logit is linear-additive), survival
        by a secant per epoch to DIR_TOL (warm-started from init; CONVERGENCE REQUIRED)."""
        def make(sl):
            sl = dict(sl)
            return lambda t: _cum_slope(t, sl)
        E = transition.EPOCHS
        bC, bQ = (dict(init[0]), dict(init[1])) if init else ({e: 0.0 for e in E}, {e: 0.0 for e in E})
        # capture: a per-epoch secant on the (near-unit) response, all epochs together
        prev = {}
        for _ in range(DIR_STEPS):
            base = self.noiseless_betas(wg, th, pl, u, make(bC), make(bQ), which="P", amp=amp)
            err = {e: base[e][0] - pl["dir"][e][0] for e in E}
            if all(abs(v) <= DIR_TOL / 4 for v in err.values()):
                break
            for e in E:
                d = 1.0
                if e in prev and err[e] != prev[e][1]:
                    d = (err[e] - prev[e][1]) / (bC[e] - prev[e][0])
                prev[e] = (bC[e], err[e])
                bC[e] -= err[e] / (d if abs(d) > 1e-3 else 1.0)
        else:
            raise CalibError(f"{wg.id}: the capture slope solver did not converge")
        dirC = make(bC)
        for e in E:                                      # (in time order: a later epoch's knob leaves earlier ones)
            tgt = pl["dir"][e][1]

            def g(x):
                bQ[e] = x
                return self.noiseless_betas(wg, th, pl, u, dirC, make(bQ), only=e, which="Q", amp=amp)[e][1] - tgt
            x0 = bQ[e]
            f0 = g(x0)
            if abs(f0) <= DIR_TOL / 4:
                continue
            # bracket the target along the knob (|knob| <= KNOB_MAX), then the Illinois method
            sgn = -1.0 if f0 > 0 else 1.0
            step, a, fa = max(0.05, 4 * abs(f0)), x0, f0
            b, fb = None, None
            while abs(a + sgn * step - x0) <= KNOB_MAX + 1e-12:
                xb = x0 + sgn * step
                fx = g(xb)
                if fx * f0 <= 0:
                    b, fb = xb, fx
                    break
                a, fa, step = xb, fx, step * 2
            if b is None:
                bQ[e] = x0 if abs(f0) <= abs(fa) else a
                self.unattainable.append({"world": wg.id, "scope": e, "readout": "beta_Q", "target": tgt,
                                          "best": tgt + min(abs(f0), abs(fa)) * (1 if f0 > 0 else -1)})
                continue
            side = 0
            for _ in range(80):
                c = (a * fb - b * fa) / (fb - fa)
                fc = g(c)
                if abs(fc) <= DIR_TOL / 4:
                    break
                if fc * fb > 0:
                    b, fb = c, fc
                    if side == -1:
                        fa /= 2
                    side = -1
                else:
                    a, fa = c, fc
                    if side == 1:
                        fb /= 2
                    side = 1
                if abs(b - a) <= 1e-13 * max(1.0, abs(a)):
                    raise CalibError(f"{wg.id} {e}: the survival slope jumps across its target (no solution)")
            else:
                raise CalibError(f"{wg.id} {e}: the survival slope solver did not converge")
        return dirC, make(bQ), (bC, dict(bQ))

    def noiseless_betas(self, wg, th, pl, u, dirC, dirQ, only=None, which="PQ", amp=None):
        lat = self.latent(wg, th, pl, u, amp or {}, dirC, dirQ)
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
            bQ = math.nan
            if "Q" in which:
                free = (foc, [fr[t] for t in foc])
                exp_ = {j: (foc, [K["S"][cell[(i, j)]] for i in foc]) for j in COARSE}
                c, ds = backbone.fit_survival(free, exp_, (L, U), trials=TRIALS * R_REP)
                m = np.mean([backbone.q_curve(c, ds[j], foc, (L, U)) for j in sorted(ds)], axis=0)
                bQ = backbone.slope(foc, m)
            out[e] = (bP, bQ)
        return out

    def observe(self, wg, mu, pl, k, ref_comp, refkeys, LR, LD):
        """Counts by the actual sharing keys, replicate means, the plug-in covariances."""
        p, R, N = self.p, R_REP, self.p["capture_bound"]
        z = self.rng(f"noise/{wg.id}")
        SR, SD = np.asarray(p["noise"]["SigmaR"], float), np.asarray(p["noise"]["SigmaD"], float)
        SE = np.asarray(p["noise"]["SigmaE"], float)
        eC, eS, eF = SE[0, 0], SE[1, 1], 1 - SR[2, 2]
        LE = np.linalg.cholesky(SE + 1e-15 * np.eye(2))
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
        # the cell component, capture and exposed survival of one assay cell jointly (H.9.2: the fitted
        # cross-channel cell covariance SigmaE; #68 round 2 P2-8)
        Ecs = z.normals(len(I) * R * 2).reshape(len(I), R, 2) @ LE.T
        EC, ES = Ecs[:, :, 0], Ecs[:, :, 1]
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
        """S_F, M_F, R_C, R_Q (full history) and the epoch scores S_e with their availability (the H-T
        gates' calibration), every candidate's support decided by recurrence.analyze_world: the phase-
        conditional rule 6 at the fitted phase, exactly as in the main analysis."""
        out = {}
        for scope in ("full",) + transition.EPOCHS:
            res = recurrence.hf([recurrence.analyze_world(self.design(w, scope), w["y"]) for w in self.worlds])
            out[scope] = {"S": res["S_F"], "M": res["M_F"], "R_C": res["R_C"], "R_Q": res["R_Q"],
                          "material_point": res["material_point"], "available": res["available"],
                          "phase_support": res["phase_support"], "positive": res["positive"]}
        return out

    def analyze_ht(self, gates_c, draws=stats.B_BOOT):
        """The complete H-T analysis; gates_c: the FROZEN epoch critical values ({e: c_E}); an epoch without
        one has no passing gate calibration and H-T is unavailable (H.12)."""
        epochs, betas = {}, {}
        for e in transition.EPOCHS:
            epochs[e] = [(self.design(w, e), w["y"]) for w in self.worlds]
            bs = {w["graph"].id: self.betas(w["graph"], w["K"], only=e)[e] for w in self.worlds}
            betas[e] = {"P": {i: b[0] for i, b in bs.items()}, "Q": {i: b[1] for i, b in bs.items()}}
        hf = {e: recurrence.hf([recurrence.analyze_world(d, y) for d, y in epochs[e]]) for e in transition.EPOCHS}
        S = {e: hf[e]["S_F"] for e in transition.EPOCHS}
        gates = {e: (bool(hf[e]["available"] and S[e] > gates_c[e]) if gates_c.get(e) is not None else None)
                 for e in transition.EPOCHS}
        loads = {w["graph"].id: w["loads"] for w in self.worlds}           # (by world id: #68 review 11)
        k = self.worlds[0]["nref"] if self.worlds else 0
        res = transition.ht(epochs, betas, gates, loads=loads, k=k, analysis=f"calib/{'/'.join(map(str, self.tag))}",
                            draws=draws, report=False)
        return {"T": res["T_T"], "S_e": S, "gates": gates, "available": res["available"],
                "winner": None if not res["winner"] else [res["winner"]["ARD"], res["winner"]["FSD"]],
                "phase_support": res["phase_support"], "EU_unsupported": res["EU_unsupported"],
                "error": res.get("error")}


# ================================================================== provenance
TOOLS = ("calib.py", "recurrence.py", "transition.py", "backbone.py", "stats.py")
GATES_SCHEMA = "finfolk.redqueen.annexH.gates/1"


def graph_sha(graph):
    """The content of a graph stratum's worlds (ids, blocks, every measured time and reference)."""
    h = hashlib.sha256()
    for wg in sorted(graph, key=lambda g: g.id):
        h.update(json.dumps([wg.id, int(wg.block), wg.ti.tolist(), wg.tj.tolist(), wg.cT.tolist(),
                             [str(r) for r in wg.cR.tolist()], wg.qT.tolist(), [str(r) for r in wg.qR.tolist()]]).encode())
    return h.hexdigest()


def tools_sha():
    h = hashlib.sha256()
    for f in TOOLS:
        with open(os.path.join(HERE, f), "rb") as fh:
            h.update(f.encode() + b"\0" + fh.read())
    return h.hexdigest()


def manifest(graph, params, draws, gates=None, production=False, graph_source="synthetic"):
    """Everything a panel record depends on: crit / accept refuse to mix two of them (#68 round 2 P1-3)."""
    return {"graph_sha256": graph_sha(graph), "graph_source": graph_source, "worlds": len(graph),
            "params_sha256": hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest(),
            "params_fitted": params.get("fitted") is True, "tools_sha256": tools_sha(), "draws": int(draws),
            "gates_sha256": None if gates is None else hashlib.sha256(json.dumps(gates, sort_keys=True).encode()).hexdigest(),
            "production": bool(production)}


def check_gates(art):
    """A frozen epoch-gate artifact (calib.py gates): every epoch's c_E with its passing validation."""
    if not isinstance(art, dict) or art.get("schema") != GATES_SCHEMA:
        raise CalibError("H-T needs the frozen epoch-gate artifact (calib.py gates), schema " + GATES_SCHEMA)
    for e in transition.EPOCHS:
        if not isinstance(art.get("c_E", {}).get(e), (int, float)) or art.get("passed", {}).get(e) is not True:
            raise CalibError(f"the recurrence gate of {e} lacks a passing frozen calibration: H-T is unavailable")
    return art


# ================================================================== a panel
def run_panel(graph, params, hyp, stage, stratum, mode, panel, gates_c=None, draws=stats.B_BOOT, man=None):
    """One registered panel -> its JSON record (score, support report, constraint checks, CPU seconds,
    failures, the manifest). The graph is canonicalized (sorted by world id) first: results never depend
    on the caller's order. An unattainable NULL target fails the panel (an alternative's makes it a
    non-success)."""
    t0 = time.process_time()
    rec = {"hyp": hyp, "stage": stage, "stratum": stratum, "mode": mode, "panel": panel, "manifest": man,
           "draws": int(draws)}
    if hyp == "H-T" and mode == "T4":
        rec["subtype"] = panel % 32
    try:
        g = sorted(graph, key=lambda w: w.id)
        pn = Panel(stratum_worlds(g, stratum), params, hyp, stage, stratum, mode, panel)
        try:
            pn.simulate()
        except PanelInfeasible as e:                 # (D2: recorded and reported, not a failed panel)
            rec.update(infeasible=str(e), redraws=pn.redraws, available=False)
            rec["cpu_total"] = time.process_time() - t0
            return rec
        rec.update(unattainable=pn.unattainable, deviations=pn.deviations, redraws=pn.redraws,
                   joint_rounds=max((v.get("rounds", 1) for v in pn.verified), default=0))
        if pn.unattainable and stage != "alt":
            raise CalibError(f"unattainable null targets after the redraws: {pn.unattainable[:3]}")
        rec["non_success"] = bool(pn.unattainable)
        if hyp == "H-T" and mode in ("TA1", "TA2"):
            rec["direction"] = "ARD->FSD" if panel % 2 == 0 else "FSD->ARD"
        t1 = time.process_time()
        if hyp == "H-F":
            a = pn.analyze_hf()
            f = a["full"]
            rec.update(score=f["S"], M=f["M"], R_C=f["R_C"], R_Q=f["R_Q"], material_point=f["material_point"],
                       S_e={e: a[e]["S"] for e in transition.EPOCHS},
                       S_e_available={e: a[e]["available"] for e in transition.EPOCHS},
                       available=f["available"], phase_support={s: a[s]["phase_support"] for s in a})
        else:
            a = pn.analyze_ht(gates_c or {}, draws)
            rec.update(score=a["T"], S_e=a["S_e"], gates=a["gates"], available=a["available"], winner=a["winner"],
                       phase_support=a["phase_support"], EU_unsupported=a["EU_unsupported"])
            if a.get("error"):
                rec["unavailable_reason"] = a["error"]
        rec["cpu"] = {"simulate": t1 - t0, "analyze": time.process_time() - t1}
    except (CalibError, recurrence.RecurrenceError, transition.TransitionError, backbone.BackboneError,
            stats.StatsError, np.linalg.LinAlgError, ValueError, FloatingPointError, KeyError) as e:
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


def _num(v):
    """A statistic value: a decision unavailable BY RULE (not a failure) cannot reject (-inf)."""
    return -math.inf if v is None else float(v)


def complete(records, hyp, stage, n, production):
    """The registered allocation of one hypothesis and stage, complete and clean (#68 round 2 P1-3): every
    mode x graph stratum with exactly the panels 0..n-1, each once; no failed panel (a failure must be
    repaired and rerun, H.12); one manifest; production records only (unless a smoke run). -> {(mode,
    stratum): [records by panel]}, the manifest."""
    rs = [r for r in records if r.get("hyp") == hyp and r.get("stage") == stage]
    by, seen, probs = {}, set(), []
    for r in rs:
        key = (r["mode"], r["stratum"], r["panel"])
        if key in seen:
            probs.append(f"duplicate panel {key}")
        seen.add(key)
        by.setdefault((r["mode"], r["stratum"]), []).append(r)
    for m, s in strata_of(hyp):
        got = sorted(r["panel"] for r in by.get((m, s), []))
        if got != list(range(n)):
            probs.append(f"{hyp} {stage} {m} {s}: {len(got)} panels, the registered 0..{n - 1} needed")
    failed = [(r["mode"], r["stratum"], r["panel"], r["error"]) for r in rs if r.get("error")]
    if failed:
        probs.append(f"{len(failed)} failed panels (repair and rerun): {failed[:3]}")
    mans = {json.dumps(r.get("manifest"), sort_keys=True) for r in rs}
    if len(mans) > 1:
        probs.append(f"{len(mans)} different manifests (graph, parameters, tools, draws or gates)")
    man = json.loads(next(iter(mans))) if len(mans) == 1 else None
    if production and (man is None or not man.get("production") or man.get("draws") != stats.B_BOOT
                       or not man.get("params_fitted") or man.get("graph_source") == "synthetic"):
        probs.append("not a production calibration (fitted parameters, the real graph, 9,999 draws)")
    if probs:
        raise CalibError("; ".join(probs[:6]))
    return {k: sorted(v, key=lambda r: r["panel"]) for k, v in by.items()}, man


def critical_values(records, production=True):
    """H.11 development critical values from the COMPLETE development allocations of the hypotheses
    present (every stratum required; none silently skipped)."""
    out = {"strata": {}, "manifest": {}}
    for hyp in ("H-F", "H-T"):
        if not any(r.get("hyp") == hyp and r.get("stage") == "dev" for r in records):
            continue
        by, man = complete(records, hyp, "dev", N_DEV, production)
        out["manifest"][hyp] = man
        out.setdefault("redraws", {}).update(redraw_report(by, hyp))
        for (m, s), rs in sorted(by.items()):
            if any(r.get("infeasible") for r in rs):   # (D2: the mode is declared infeasible and reported)
                out.setdefault("infeasible", {})[f"{hyp}|{m}|{s}"] = sum(1 for r in rs if r.get("infeasible"))
                continue
            def crit(vals):
                sc = sorted(vals)
                return sc[min(math.ceil(0.99 * (len(sc) + 1)), len(sc)) - 1]
            rec = {"score": crit(_num(r["score"]) if r["available"] else -math.inf for r in rs)}
            if hyp == "H-F":
                rec["M"] = crit(_num(r["M"]) if r["available"] else -math.inf for r in rs)
                for e in transition.EPOCHS:
                    rec[f"S_{e}"] = crit(_num(r["S_e"][e]) if r["S_e_available"][e] else -math.inf for r in rs)
            out["strata"][f"{hyp}|{m}|{s}"] = rec

    def mx(hyp, modes, key):
        v = [out["strata"][f"{hyp}|{m}|{s}"][key] for m in modes for s in STRATA if f"{hyp}|{m}|{s}" in out["strata"]]
        return max(v) if v else None
    if "H-F" in out["manifest"]:
        out["c_F"] = mx("H-F", ("F0", "F1", "F2"), "score")
        out["c_M"] = mx("H-F", F_MODES, "M")
        out["c_E"] = {e: mx("H-F", ("F0", "F1", "F2"), f"S_{e}") for e in transition.EPOCHS}
    if "H-T" in out["manifest"]:
        cT = mx("H-T", T_MODES, "score")
        out["c_T"] = None if cT is None else max(transition.GUARD, cT)
    return out


def redraw_report(by, hyp):
    """D2: per mode x graph stratum, the panels with a redrawn null world, the redraws and the infeasible
    panels (the redraw rate is reported, never hidden)."""
    out = {}
    for (m, s), rs in sorted(by.items()):
        red = [len(r.get("redraws") or []) for r in rs]
        out[f"{hyp}|{m}|{s}"] = {"panels": len(rs), "panels_redrawn": sum(1 for x in red if x),
                                 "redraws": sum(red), "infeasible": sum(1 for r in rs if r.get("infeasible")),
                                 "redraw_rate": sum(1 for x in red if x) / len(rs) if rs else None}
    return out


def p_model(s, tables):
    """max over the applicable validation strata of (1 + #{null >= s}) / (N + 1) (stats.model_p: NaN-safe)."""
    return stats.model_p(s, {str(k): list(t) for k, t in enumerate(tables)})


def hf_rejects(r, crit):
    """The locked H-F rules on one record (the critical part; the p-table requirement can only reduce
    rejections, so validating it is conservative): detection, and the complete nested exceeding-material
    claim (detection, both material points, M_F > c_M, R_C > 0.10, R_Q > 0.04)."""
    if not r["available"]:
        return False, False
    det = _num(r["score"]) > crit["c_F"]
    mat = (det and bool(r["material_point"]) and _num(r["M"]) > crit["c_M"] and _num(r["R_C"]) > recurrence.D_C
           and _num(r["R_Q"]) > recurrence.D_Q)
    return det, mat


def acceptance(records, crit, production=True):
    """INDEPENDENT validation (H.11; #68 round 2 P1-1): the false positives of the FROZEN critical rules on
    the complete validation allocation (a panel is never judged against a table containing itself), the
    one-sided Clopper-Pearson U95 per applicable mode x graph rate, pass iff every U95 <= 0.02. Rates: H-F
    detection (F0-F2; the raw reciprocal-detection rule), the nested exceeding-material claim (F0-F4),
    every epoch recurrence gate (F0-F2: S_e > c_E); H-T (T0-T4). The validation manifest must equal the
    development one. Then the model p-value tables (the validation null scores) for the final evaluation."""
    out = {"rates": {}, "pass": {}, "ptables": {}, "diagnostics": {}}
    for hyp in ("H-F", "H-T"):
        if hyp not in crit.get("manifest", {}):
            continue
        by, man = complete(records, hyp, "val", N_VAL, production)
        dev = dict(crit["manifest"][hyp])
        if production or dev.get("production"):
            same = {k: man.get(k) == dev.get(k) for k in ("graph_sha256", "params_sha256", "tools_sha256", "draws",
                                                          "gates_sha256")}
            if not all(same.values()):
                raise CalibError(f"{hyp}: the validation manifest differs from the development one: {same}")
        rates = {}
        out.setdefault("redraws", {}).update(redraw_report(by, hyp))
        infeasible = {k for k, rs in by.items() if any(r.get("infeasible") for r in rs)} | {
            tuple(k.split("|")[1:]) for k in crit.get("infeasible", {}) if k.startswith(hyp + "|")}
        out.setdefault("infeasible", []).extend(sorted(f"{hyp}|{m}|{s}" for m, s in infeasible))

        def rate(name, flags):
            k, n = sum(flags), len(flags)
            u = stats.clopper_pearson_upper(k, n)
            rates[name] = {"fp": k, "n": n, "U95": u, "pass": u <= 0.02}
        for (m, s), rs in sorted(by.items()):
            if (m, s) in infeasible:
                continue
            if hyp == "H-F":
                rej = [hf_rejects(r, crit) for r in rs]
                if m in ("F0", "F1", "F2"):
                    rate(f"detection|{m}|{s}", [d for d, _ in rej])
                    for e in transition.EPOCHS:
                        rate(f"gate_{e}|{m}|{s}", [bool(r["S_e_available"][e]) and _num(r["S_e"][e]) > crit["c_E"][e]
                                                   for r in rs])
                rate(f"material|{m}|{s}", [x for _, x in rej])
                out["diagnostics"][f"{hyp}|{m}|{s}"] = {
                    "unavailable": sum(1 for r in rs if not r["available"]),
                    "background_deviations": sum(1 for r in rs if r.get("deviations"))}
            else:
                flags = [bool(r["available"]) and _num(r["score"]) > crit["c_T"] for r in rs]
                rate(f"transition|{m}|{s}", flags)
                d = {"unavailable": sum(1 for r in rs if not r["available"]),
                     "background_deviations": sum(1 for r in rs if r.get("deviations"))}
                if m == "T4":                           # (subtype rates: diagnostics, H.10)
                    d["subtypes"] = {st: sum(f for f, r in zip(flags, rs) if r.get("subtype") == st)
                                     for st in range(32)}
                out["diagnostics"][f"{hyp}|{m}|{s}"] = d
        out["rates"][hyp] = rates
        if hyp == "H-F":
            out["pass"]["H-F detection"] = all(v["pass"] for k, v in rates.items() if k.startswith("detection"))
            out["pass"]["H-F material"] = all(v["pass"] for k, v in rates.items() if k.startswith("material"))
            for e in transition.EPOCHS:
                out["pass"][f"gate {e}"] = all(v["pass"] for k, v in rates.items() if k.startswith(f"gate_{e}|"))
            out["ptables"]["H-F detection"] = {f"{m}|{s}": sorted(_num(r["score"]) if r["available"] else -math.inf
                                                                  for r in by[(m, s)])
                                               for m in ("F0", "F1", "F2") for s in STRATA if (m, s) not in infeasible}
            out["ptables"]["H-F material"] = {f"{m}|{s}": sorted(_num(r["M"]) if r["available"] else -math.inf
                                                                 for r in by[(m, s)])
                                              for m in F_MODES for s in STRATA if (m, s) not in infeasible}
        else:
            out["pass"]["H-T"] = all(v["pass"] for v in rates.values())
            out["ptables"]["H-T"] = {f"{m}|{s}": sorted(_num(r["score"]) if r["available"] else -math.inf
                                                        for r in by[(m, s)])
                                     for m in T_MODES for s in STRATA if (m, s) not in infeasible}
        out.setdefault("manifest", {})[hyp] = man
    return out


def freeze_gates(crit, acc):
    """The frozen epoch-gate artifact H-T development needs (H.11-H.12): every epoch's c_E with its
    independently passing validation rate; a gate that did not pass refuses the freeze (H-T unavailable)."""
    if "c_E" not in crit:
        raise CalibError("no H-F development calibration (c_E)")
    passed = {e: acc.get("pass", {}).get(f"gate {e}") is True for e in transition.EPOCHS}
    if not all(passed.values()):
        raise CalibError(f"epoch gates without a passing validation: {[e for e, p in passed.items() if not p]}: "
                         "H-T is unavailable")
    return {"schema": GATES_SCHEMA, "c_E": crit["c_E"], "passed": passed, "hf_manifest": crit["manifest"]["H-F"],
            "rates": {k: v for k, v in acc["rates"]["H-F"].items() if k.startswith("gate_")}}


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(c - h, 0.0), min(c + h, 1.0)]


def power(records, crit):
    """Development-alternative power (H.10-H.11) with binomial (Wilson) Monte Carlo intervals: a success is
    the frozen rule's rejection on a panel whose targets were all attained (an unattainable alternative is
    a non-success); H-T also by generating direction (denominator 50 each)."""
    out = {}
    for r in records:
        if r.get("stage") != "alt":
            continue
        key = f"{r['hyp']}|{r['mode']}|{r['stratum']}"
        if r.get("error"):
            ok = False
        elif r["hyp"] == "H-F":
            d, mt = hf_rejects(r, crit)
            ok = {"detection": d, "material": mt}
        else:
            ok = bool(r["available"]) and _num(r["score"]) > crit["c_T"]
        rec = out.setdefault(key, {"n": 0, "failed": 0, "non_success": 0, "success": {}, "by_direction": {}})
        rec["n"] += 1
        rec["failed"] += bool(r.get("error"))
        rec["non_success"] += bool(r.get("non_success"))
        flags = ok if isinstance(ok, dict) else {"rejection": ok}
        for k, v in flags.items():
            rec["success"][k] = rec["success"].get(k, 0) + bool(v and not r.get("non_success"))
        if r["hyp"] == "H-T":
            dd = rec["by_direction"].setdefault(r.get("direction"), {"n": 0, "success": 0})
            dd["n"] += 1
            dd["success"] += bool(flags["rejection"] and not r.get("non_success"))
    for rec in out.values():
        rec["wilson95"] = {k: wilson(v, rec["n"]) for k, v in rec["success"].items()}
        for dd in rec["by_direction"].values():
            dd["wilson95"] = wilson(dd["success"], dd["n"])
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
        return load_graph(a.graph), "file:" + hashlib.sha256(open(a.graph, "rb").read()).hexdigest()
    return synthetic_graph(a.synthetic_worlds), "synthetic"


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
        s.add_argument("--gates", help="the frozen epoch-gate artifact (calib.py gates) H-T requires")
        s.add_argument("--draws", type=int, default=stats.B_BOOT)
        s.add_argument("--smoke", action="store_true", help="a smoke / test run: synthetic inputs allowed, the "
                       "records marked non-production (crit / accept refuse them)")
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
    for name in ("crit", "accept", "power"):
        s = sub.add_parser(name)
        if name in ("accept", "power"):
            s.add_argument("--crit", required=True)
        s.add_argument("--smoke", action="store_true")
        s.add_argument("files", nargs="+")
    s = sub.add_parser("gates")
    s.add_argument("--crit", required=True)
    s.add_argument("--accept", required=True)
    s.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd in ("panels", "bench"):
            graph, src = get_graph(a)
            params = get_params(a)
            production = a.cmd == "panels" and not a.smoke
            check_params(params, production=production)
            if production and (src == "synthetic" or a.draws != stats.B_BOOT):
                raise CalibError("production panels need the real graph (--graph) and the locked 9,999 draws "
                                 "(--smoke for a test run)")
            gates, art = None, None
            if a.gates:
                with open(a.gates) as f:
                    art = check_gates(json.load(f))
                gates = art["c_E"]
            elif a.hyp == "H-T":
                if production:
                    raise CalibError("production H-T panels need the frozen, passing epoch gates (--gates)")
                gates = {e: 0.0 for e in transition.EPOCHS}          # (smoke / bench only: zero gates)
            man = manifest(graph, params, a.draws, art if art else (gates if a.hyp == "H-T" else None),
                           production, src)
            if a.cmd == "panels":
                with open(a.out, "a") as f:
                    for k in range(a.lo, a.hi):
                        r = run_panel(graph, params, a.hyp, a.stage, a.stratum, a.mode, k, gates, a.draws, man)
                        f.write(json.dumps(r, sort_keys=True) + "\n")
                        f.flush()
                return 0
            recs = []
            for n in range(a.panels):
                m, s, k = nth_dev_panel(a.hyp, n)
                r = run_panel(graph, params, a.hyp, "dev", s, m, k, gates, a.draws, man)
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
        if a.cmd == "gates":
            with open(a.crit) as f:
                crit = json.load(f)
            with open(a.accept) as f:
                acc = json.load(f)
            art = freeze_gates(crit, acc)
            with open(a.out, "w") as f:
                json.dump(art, f, indent=1, sort_keys=True)
            print(json.dumps(art["passed"]))
            return 0
        recs = read_records(a.files)
        if a.cmd == "crit":
            print(json.dumps(critical_values(recs, production=not a.smoke), indent=1, sort_keys=True))
            return 0
        with open(a.crit) as f:
            crit = json.load(f)
        if a.cmd == "accept":
            print(json.dumps(acceptance(recs, crit, production=not a.smoke), indent=1, sort_keys=True))
        else:
            print(json.dumps(power(recs, crit), indent=1, sort_keys=True))
        return 0
    except CalibError as e:
        print(f"calib.py {a.cmd}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

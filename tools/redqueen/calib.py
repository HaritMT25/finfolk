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
  amplitude >= 0 per readout (and epoch), solved so that the NOISE-FREE post-refit native RMS on the
  world's reference panel (recurrence.ref_rms_op; the metric: the plug-in bank model at the world's BASE
  noise-free means, decision D1) equals the target to AMP_TOL relative, on BOTH sides (no overshoot is
  accepted; #68 round 3): the smallest such amplitude on the grid AMP_GRID ([0, A_MAX] by 0.5, then 12,
  24 = A_SUP), its bracket solved by the Illinois method. "max" (as large as bounded means permit) = the
  native RMS maximized over [0, A_SUP] (grid, golden-section refinement).
  Directional knobs (H-T modes): per epoch, a latent focal-time slope (capture: predator time; exposed
  survival: prey time), continuous, linear within each epoch. The knobs and the amplitudes are solved
  JOINTLY (alternating, each with the other present) and the COMPLETED noise-free panel is verified
  against every declared constraint (epoch slopes to DIR_TOL, RMS targets to AMP_TOL relative, both
  sides); a panel that does not verify is a numerical failure.
  The analysis covariance V of a panel is the bank model evaluated at the panel's observed per-channel
  replicate means (clipped to [1/2N, 1 - 1/2N]; the delta method; shared columns per sharing key) - the
  same plug-in rule the real analysis uses.

FEASIBILITY AND STRATA (the D2 ruling, 2026-11-08; an Annex H amendment). A target is INFEASIBLE only
when the bounded-mean limit shows it: an RMS target above the native RMS's supremum over EVERY amplitude
(the evidence ladder continues past A_SUP to A_LIM, the step pattern), or below its infimum (a
background above the target at every amplitude); a survival-slope target outside the range of the noise-
free epoch slope over the knob, the ladder continued until the slope's limit has converged. A target
inside those limits that the solver cannot reach (an amplitude or knob ceiling, non-convergence, a limit
that cannot be established) is a NUMERICAL FAILURE: an error, never infeasible; its allocation is
refused until repaired and rerun (H.12). An infeasible target is CLIPPED to the nearest attainable value
(the attainable supremum / infimum on the generating domain) and recorded (requested, achieved).
PROPOSALS. The proposal unit is the complete panel (its worlds and their dependence kept). One stream
family per hyp x stage x mode x graph: slot j (0..n-1, carrying panel j's registered parity / subtype /
direction), retry r (0..ROUNDS-1; r = 0 is the slot's original stream tag, r >= 1 the tag
"<j>/retry<r>"). TRIAGE (noise-free) classifies a proposal on its final noise-free mean panel under the
registered analysis functionals (Panel.functionals: the plug-in metric at the noise-free means): FEASIBLE
(every declared constraint met) or INFEASIBLE (a target clipped), then NULL MEMBERSHIP: H-F F0-F2 by
construction (the absent readout's amplitude is zero); F3 / F4 not both R_C > d_C and R_Q > d_Q beyond
BOUNDARY_TOL; H-T: for EVERY one of the six candidates some margin <= BOUNDARY_TOL x its scale (clipping
one component can strengthen another candidate). A non-member is discarded (counted). STRATA per mode x
graph: B = feasible members (slot j's first in retry order), I = infeasible members (the first n_I = n in
(retry, slot) order). Round 0 proposes every slot; round r >= 1 re-proposes the slots without a B panel
and, while I is short and q-hat (the infeasible fraction of the complete rounds) x K could still reach
N_MIN, every slot; K = ROUNDS x n. Only kept proposals get the noisy simulation and the analysis. A slot
without a B panel after ROUNDS proposals is CAPPED: the mode's calibration is UNAVAILABLE (reported; the
decisions needing it are unavailable, p = 1 in Holm), never a non-rejection. I is calibrated when it
holds >= N_MIN panels (dev 99: the plus-one 0.99 order statistic exists; val 149: 0 false positives give
U95 <= 0.02); otherwise its scope is reported: q-hat, its Clopper-Pearson q_U and alpha_F + q_U.
Alternatives are unchanged (an infeasible alternative target is a non-success). q-hat from the synthetic
placeholder parameters is illustrative only; the binding q-hat is the production run's.
BOUNDARY (the D1 caveat). A B panel with a declared boundary (F3: R_C = d_C; F4: R_Q = d_Q; T4 components
0-13: margin k of its candidate = 0) is labelled an Annex H boundary null only when the boundary
quantity, recomputed on the noise-free means under the FINAL analysis metric (built from the observed
means), lies within BOUNDARY_TOL x its scale of the boundary (recorded per panel and reported).
H-F F3 / F4 BOUNDARIES ARE FUNCTIONAL (the coordinator's decision (a), 2026-11-08): E_C = d_C^2 (F3) or
E_Q = d_Q^2 (F4) of the noise-free panel (the triage metric) is met by ONE panel multiplier lambda on the
declared component's per-world targets (lambda x 0.10 / 0.04; the other readout's "max" unchanged):
lambda in [0, LAMBDA_MAX = 10], from lambda = 1 by the scaling step lambda sqrt(b / E) until bracketed,
then Illinois, |E - b| <= LAMBDA_TOL x b, at most LAMBDA_EVALS evaluations (else a numerical failure). A
functional that JUMPS over b (a selection switching: the bracket narrows below LAMBDA_JUMP without
convergence) is CONSTRUCTION-INFEASIBLE: kept in I at the largest lambda below the jump (its functional
on the null side) and counted separately; it is infeasible within the registered construction, not shown
unattainable. b outside the functional's range on [0, LAMBDA_MAX] is infeasible (above-sup / below-inf).
T4's boundaries stay construction-level (labelled) pending the E^U support decision.

MODES (H.10).MODES (H.10). H-F (full history): F0 none; F1 capture only (RMS 0.10 / 0.20 by panel parity); F2
survival only (0.04 / 0.08); F3 capture 0.10 + survival max; F4 survival 0.04 + capture max;
alternatives FA1 (0.10, 0.04), FA2 (0.20, 0.08). H-T (epochs; one period per world across epochs): T0
stable material directional (1.5 delta), no recurrence; T1 stable recurrence (0.15, 0.06), no
directional change; T2 both; T3 none, stressed red variation, half the worlds saturated (+2.5 logit
capture), noise x 1.5; T4 cycles 32 subtypes ((14 boundary components + a capture-only + a survival-only
transition) x 2 directions) over the three epoch pairs; alternatives TA1 / TA2 (material / doubled,
direction by panel parity). Graph strata: "actual" (the qualifying worlds) and "stress24" (24 worlds by
sha256 of the registry id). Streams: AnnexH/1/<hyp>/<stage>:<stratum>/<mode>/<panel>[/<purpose>].

DECISIONS (H.11). Development: per mode x graph x stratum (B; I when calibrated) the plus-one 0.99
order statistic; a decision's critical value is the LARGEST over its applicable modes, graphs and strata
(never pooled: interior I cases would dilute the boundary): c_F over F0-F2, c_M (M_F) over F0-F4, epoch
gates c_E1..c_E3 (S_e) over F0-F2, c_T = max(log 600, over T0-T4); a capped mode makes it unavailable.
Every allocation must be COMPLETE: every mode x graph with its registered proposal rounds, no failed
proposal (a failure is repaired and rerun, H.12), one manifest (graph, parameters, tools, draws, gates),
production records only (fitted parameters, the real graph, 9,999 draws). Validation (acceptance) is
INDEPENDENT of the panels it judges: the false positives of the FROZEN critical rules (the model p-value
can only reduce rejections) on the 1,000-panel validation B stratum (and the calibrated I stratum) per
mode x graph: H-F detection (F0-F2: the raw reciprocal rule), the nested exceeding-material claim
(F0-F4), each epoch gate (F0-F2), H-T (T0-T4; T4 subtype counts with denominators as diagnostics); U95 <=
0.02 for every rate. The claim is "passed the model-based screen (U95 <= 0.02) for the registered
strata", never certified alpha control (H.11). The validation null scores form the p-tables per stratum
(p_m(s) = (1 + #{null >= s}) / (N + 1), p_model = the LARGEST over the tables). The acceptance report
names the critical-value artifact it evaluated (crit_sha256); the frozen epoch-gate artifact (`gates`)
binds that identity, the acceptance's, the recomputed gate rates and the H-F manifest, and H-T refuses
gates calibrated on another graph, parameters, code or draws. Power: development alternatives (the
registered 100 panels per mode x graph, failures counted as non-successes) with Wilson intervals, H-T
by generating direction (assigned from panel parity before generation).
BENCHMARK (H.12). `calib.py bench` runs the first 50 development panels of a hypothesis (the ten strata
in turn) with every fit, period, window, material rule, epoch, direction and bootstrap used in the
decision, and reports CPU seconds per panel against the 13.5 s target (smoke records: never accepted
by crit / accept).

    python3 calib.py panels --hyp H-F --stage dev --graph g.jsonl.gz --params fitted.json --mode F3 \\
        --stratum actual --to 160 --out dev_HF_r0.jsonl          (round 0; production; --smoke for tests)
    python3 calib.py panels ... --round 1 --prior dev_HF_r0.jsonl --out dev_HF_r1.jsonl   (rounds 1, 2)
    python3 calib.py crit dev_HF.jsonl > crit_HF.json
    python3 calib.py accept --crit crit_HF.json val_HF.jsonl > acc_HF.json
    python3 calib.py gates --crit crit_HF.json --accept acc_HF.json --out gates.json
    python3 calib.py panels --hyp H-T ... --gates gates.json ...; crit / accept / power likewise
    python3 calib.py bench --hyp H-F [--graph g.jsonl.gz] [--params p.json] [--panels 50]
    python3 calib.py report dev_*.jsonl val_*.jsonl > report.json       (proposals, clips, boundaries, CPU)
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
KNOB_MAX = 8.0           # the survival knob's search grid [-KNOB_MAX, KNOB_MAX] (latent logit per 50M)
KNOB_LIM = 1024.0        # the knob's evidence ladder (the bounded-mean limit; infeasibility evidence only)
JOINT_ROUNDS = 24
A_SUP = 4 * A_MAX        # the generating amplitude domain [0, A_SUP] (the means stay inside the location tables)
A_LIM = 1e4              # the amplitude's bounded-mean limit (the step pattern; infeasibility evidence only)
AMP_GRID = tuple(0.5 * k for k in range(13)) + (2 * A_MAX, A_SUP)
LIM_GRID = tuple(A_SUP * 2.0 ** k for k in range(1, 9)) + (A_LIM,)
BOUNDARY_TOL = 0.05      # boundary residuals and null membership, relative to the margin's scale
D_C, D_Q = recurrence.D_C, recurrence.D_Q
ROUNDS = 3               # the proposal cap K = ROUNDS x n per stage x mode x graph (the D2 ruling)
LAMBDA_MAX = 10.0        # H-F F3 / F4: the panel multiplier's bracket [0, LAMBDA_MAX] on the declared per-world targets
LAMBDA_TOL = 1e-3        # |functional - boundary| <= LAMBDA_TOL x boundary
LAMBDA_JUMP = 1e-3       # a bracket narrower than this (relative) without convergence: a jump (construction-infeasible)
LAMBDA_EVALS = 40        # evaluations before the iteration is a numerical failure
INFEASIBLE = ("infeasible", "construction-infeasible")
N_MIN = {"dev": 99, "val": 149}
NTHETA = 98
F_MODES = ("F0", "F1", "F2", "F3", "F4")
T_MODES = ("T0", "T1", "T2", "T3", "T4")
ALT = {"H-F": ("FA1", "FA2"), "H-T": ("TA1", "TA2")}
STRATA = ("actual", "stress24")
N_DEV, N_VAL, N_ALT = 160, 1000, 100
GREVILLE = np.array([0.0, 1 / 9, 1 / 3, 2 / 3, 8 / 9, 1.0])


class CalibError(Exception):
    pass


def sig(x):
    with np.errstate(over="ignore"):                      # (exp overflow at the limit ladders: sigma = 0 exactly)
        return 1.0 / (1.0 + np.exp(-x))


def extremum(f, grid, sign):
    """The maximum of sign * f over a registered grid, refined by golden section between the best grid
    point's neighbours -> (argument, f there). A nonfinite value is a numerical failure."""
    grid = [float(x) for x in grid]
    vals = [sign * f(x) for x in grid]
    if not all(math.isfinite(v) for v in vals):
        raise CalibError("a nonfinite value in an extremum search")
    k = int(np.argmax(vals))
    best = (vals[k], grid[k])
    lo, hi = grid[max(k - 1, 0)], grid[min(k + 1, len(grid) - 1)]
    if hi > lo:
        g = (math.sqrt(5) - 1) / 2
        x1, x2 = hi - g * (hi - lo), lo + g * (hi - lo)
        f1, f2 = sign * f(x1), sign * f(x2)
        for _ in range(24):
            if f1 >= f2:
                hi, x2, f2 = x2, x1, f1
                x1 = hi - g * (hi - lo)
                f1 = sign * f(x1)
            else:
                lo, x1, f1 = x1, x2, f2
                x2 = lo + g * (hi - lo)
                f2 = sign * f(x2)
        best = max(best, (f1, x1), (f2, x2))
    if not math.isfinite(best[0]):
        raise CalibError("a nonfinite value in an extremum search")
    return float(best[1]), sign * float(best[0])


def root(g, lo, glo, hi, ghi, tol, what):
    """g(x) = 0 to |g| <= tol on a sign-change bracket (Illinois). Exhaustion or a jump across zero is a
    NUMERICAL FAILURE (CalibError), never infeasibility."""
    side = 0
    for _ in range(200):
        c = (lo * ghi - hi * glo) / (ghi - glo)
        gc = g(c)
        if not math.isfinite(gc):
            raise CalibError(f"{what}: a nonfinite value in the solver (a numerical failure)")
        if abs(gc) <= tol:
            return c
        if gc * ghi > 0:
            hi, ghi = c, gc
            if side == -1:
                glo /= 2
            side = -1
        else:
            lo, glo = c, gc
            if side == 1:
                ghi /= 2
            side = 1
        if abs(hi - lo) <= 1e-13 * max(1.0, abs(lo)):
            raise CalibError(f"{what}: the function jumps across its target (a numerical failure)")
    raise CalibError(f"{what}: the solver did not converge (a numerical failure)")


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

    def __init__(self, graph, params, hyp, stage, stratum, mode, panel, stress=None, retry=0):
        self.g, self.p = graph, check_params(params)
        self.hyp, self.stage, self.stratum, self.mode, self.panel = hyp, stage, stratum, mode, panel
        self.retry = int(retry)
        self.stress = (stage == "val") if stress is None else stress
        # (the slot's original streams at retry 0; the D2 retries have their own)
        self.tag = (hyp, f"{stage}:{stratum}", mode, panel if self.retry == 0 else f"{panel}/retry{self.retry}")
        self.unattainable, self.verified, self.achieved, self.maxima = [], [], {}, []
        self._metric = {}

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
        """The latent amplitude (>= 0) giving the target noise-free post-refit native RMS to AMP_TOL relative
        (both sides): the smallest on AMP_GRID's brackets. "max": the amplitude in [0, A_SUP] maximizing the
        native RMS (H.10). FEASIBILITY (the D2 ruling): a target outside the native RMS's range over EVERY
        amplitude (the evidence ladder LIM_GRID to the bounded-mean limit A_LIM) is INFEASIBLE, recorded and
        CLIPPED to the nearest attainable value on [0, A_SUP] (kind "above-sup": the supremum is below the
        target; "below-inf": the infimum, a background, is above it). A target inside that range that is not
        reached on [0, A_SUP] (a ceiling), or a solver that fails, is a NUMERICAL FAILURE (CalibError)."""
        def f(a):
            am = dict(amp)
            cur = list(am.get(scope, (0.0, 0.0)))
            cur[h] = a
            am[scope] = tuple(cur)
            v = self.rms_of(wg, th, pl, u, am, scope, h, dirC, dirQ)
            if not math.isfinite(v):
                raise CalibError(f"{wg.id} {scope} {'CQ'[h]}: a nonfinite noise-free RMS (a numerical failure)")
            return v
        tag = {"world": wg.id, "scope": scope, "readout": "CQ"[h], "target": target}
        key = (wg.id, scope, h)
        if target == "max":
            a_m, v_m = extremum(f, AMP_GRID, 1.0)
            self.maxima.append(dict(tag, amp=a_m, value=v_m, edge=bool(a_m >= A_SUP - 1e-9)))
            return a_m
        tol = AMP_TOL * target
        what = f"{wg.id} {scope} {'CQ'[h]} RMS {target}"
        grid = [float(a) for a in AMP_GRID]
        gv = [f(a) - target for a in grid]
        for k, (a, v) in enumerate(zip(grid, gv)):                 # (the smallest amplitude meeting the target)
            if abs(v) <= tol:
                self.achieved[key] = v + target
                return a
            if k + 1 < len(grid) and v * gv[k + 1] < 0:
                a_r = root(lambda x: f(x) - target, a, v, grid[k + 1], gv[k + 1], tol, what)
                self.achieved[key] = f(a_r)
                return a_r
        sign = 1.0 if gv[0] < 0 else -1.0                           # (every grid value on one side)
        a_x, v_x = extremum(f, grid, sign)
        if sign * (v_x - target) >= -tol:                           # (the extremum reaches it: bracket there)
            if abs(v_x - target) <= tol:
                self.achieved[key] = v_x
                return a_x
            nb = min((x for x in grid if x != a_x), key=lambda x: (abs(x - a_x), x))
            a_r = root(lambda x: f(x) - target, nb, f(nb) - target, a_x, v_x - target, tol, what)
            self.achieved[key] = f(a_r)
            return a_r
        # the bounded-mean limit: does ANY amplitude reach the target? (evidence only)
        _, v_l = extremum(f, (A_SUP,) + LIM_GRID, sign)
        if sign * (v_l - target) >= -tol:
            raise CalibError(f"{what}: reached only beyond the generating domain [0, {A_SUP:g}] (an amplitude "
                             f"ceiling: a numerical failure, not infeasibility; limit {v_l:.6g})")
        self.unattainable.append(dict(tag, kind="above-sup" if sign > 0 else "below-inf", nearest=v_x,
                                      limit=v_l, amp=a_x))
        return a_x

    # -------------------------------------------------------- simulate = triage + observe
    def simulate(self):
        """The whole panel: the noise-free triage, then the noisy observation of every world."""
        return self.triage().observe_all()

    def triage(self):
        """A proposal's NOISE-FREE stage (the D2 ruling): every world's coefficients, plan and red variation,
        the jointly solved knobs and amplitudes (an infeasible target clipped and recorded), the completed
        panel verified; then the panel's class (feasible / infeasible) and, under the registered analysis
        functionals on its noise-free means, its null membership and declared-boundary residual."""
        p = self.p
        th_all = np.asarray(p["theta"], float)
        thbar = th_all.mean(axis=0)
        ar = p["ar"]
        rho = np.asarray(ar["rho"], float)
        Sig = np.asarray(ar["Sigma"], float)
        if self.stress:
            rho = np.full(5, STRESS_RHO)
            Sig = Sig * STRESS_SD ** 2
        rw = self.rng("worlds")
        self.worlds = []
        for k, wg in enumerate(self.g):
            s = int(rw.below(len(th_all), 1)[0])
            th = thbar + COEF_STRESS * (th_all[s] - thbar)
            pl = plan_world(self.hyp, self.mode, self.panel, k, rw)
            u = ar_paths(wg.times, rho, Sig, ar["step"], self.rng(f"ar/{wg.id}").normals(len(wg.times) * 5).reshape(-1, 5))
            dirC, dirQ, amp, ver = self.solve_joint(wg, th, pl, u)
            self.verified.append(dict(ver, world=wg.id))
            lat = self.latent(wg, th, pl, u, amp, dirC, dirQ)
            nat = self.native(wg, lat)
            w = {"id": wg.id, "plan": pl, "amp": {sc: list(v) for sc, v in amp.items()}, "graph": wg, "k": k,
                 "_ctx": (th, u, dirC, dirQ),
                 "mu": {ch: sig(lat[ch]) for ch in lat},
                 "y_true": {"within": {"C": nat["C"], "Q": nat["Q"]}, "ref": {"C": nat["RC"], "Q": nat["RQ"]}}}
            if pl["dir"] is not None:
                w["betas_true"] = {e: (ver["dir"][f"{e}/beta_P"], ver["dir"][f"{e}/beta_Q"]) for e in transition.EPOCHS}
            self.worlds.append(w)
        decl = declared_boundary(self.hyp, self.mode, self.panel)
        self.lam = None
        if decl is not None and decl["kind"] == "hf" and self.stage != "alt":
            self.lam = self.solve_boundary(decl)
            self.status = self.lam["outcome"]
        else:
            self.status = "infeasible" if self.unattainable else "feasible"
        self.membership = self.member()
        return self

    def _world_at(self, w, h, target):
        """One world's declared readout h re-solved to `target` (the other readout's amplitude kept) and its
        noise-free means rebuilt. -> the world's clips."""
        th, u, dirC, dirQ = w["_ctx"]
        wg, pl = w["graph"], w["plan"]
        amp = {sc: tuple(v) for sc, v in w["amp"].items()}
        saved, self.unattainable = self.unattainable, []
        try:
            a = self.solve_amp(wg, th, pl, u, amp, "full", h, target, dirC, dirQ)
            clips = self.unattainable
        finally:
            self.unattainable = saved
        cur = list(amp.get("full", (0.0, 0.0)))
        cur[h] = a
        amp["full"] = tuple(cur)
        lat = self.latent(wg, th, pl, u, amp, dirC, dirQ)
        nat = self.native(wg, lat)
        w.update(amp={sc: list(v) for sc, v in amp.items()}, mu={ch: sig(lat[ch]) for ch in lat},
                 y_true={"within": {"C": nat["C"], "Q": nat["Q"]}, "ref": {"C": nat["RC"], "Q": nat["RQ"]}})
        w.pop("cov_nf", None)
        return clips

    def solve_boundary(self, decl):
        """H-F F3 / F4: the panel multiplier lambda on the declared component's per-world RMS targets with the
        noise-free functional (E_C or E_Q, the triage metric) equal to the boundary (see the docstring's
        H-F F3 / F4 BOUNDARIES). -> {"outcome": feasible / construction-infeasible / infeasible, "lambda",
        "functional", "boundary", "evals", "path"}; the panel is left at the chosen lambda (its per-world
        clips there recorded; verify re-run)."""
        h = 0 if decl["name"] == "E_C" else 1
        base = self.worlds[0]["plan"]["rec"]["full"][h]
        b, tol = decl["boundary"], LAMBDA_TOL * decl["boundary"]
        states, path = {}, []

        def E(lam):
            if lam in states:
                return states[lam]["E"]
            if len(path) >= LAMBDA_EVALS:
                raise CalibError(f"the boundary multiplier did not converge in {LAMBDA_EVALS} evaluations (a "
                                 f"numerical failure): {path[-4:]}")
            clips = []
            for w in self.worlds:
                clips += self._world_at(w, h, lam * base)
            v = self.functionals()[decl["name"]]
            if not math.isfinite(v):
                raise CalibError("a nonfinite boundary functional (a numerical failure)")
            states[lam] = {"E": v, "clips": clips, "worlds": [{k: w[k] for k in ("amp", "mu", "y_true")}
                                                              for w in self.worlds]}
            path.append((lam, v))
            return v

        def finish(lam, outcome, kind=None):
            st = states[lam]
            for w, x in zip(self.worlds, st["worlds"]):
                w.update(x)
                w.pop("cov_nf", None)
                w["plan"]["rec"]["full"] = tuple(lam * base if i == h else t for i, t in enumerate(w["plan"]["rec"]["full"]))
            self.unattainable = list(st["clips"])
            if kind is not None:
                self.unattainable.append({"world": "panel", "scope": "full", "readout": decl["name"], "target": b,
                                          "kind": kind, "nearest": st["E"], "lambda": lam})
            self.verified = []
            for w in self.worlds:
                th, u, dirC, dirQ = w["_ctx"]
                self.achieved.pop((w["id"], "full", h), None)
                self.achieved[(w["id"], "full", h)] = self.rms_of(w["graph"], th, w["plan"], u,
                                                                  {sc: tuple(v) for sc, v in w["amp"].items()},
                                                                  "full", h, dirC, dirQ)
                ver = self.verify(w["graph"], th, w["plan"], u, {sc: tuple(v) for sc, v in w["amp"].items()}, dirC, dirQ)
                if not ver["ok"]:
                    raise CalibError(f"{w['id']}: the per-world targets at lambda {lam:.6g} do not verify: "
                                     f"{ver['violations'][:2]} (a numerical failure)")
                self.verified.append(dict(ver, world=w["id"]))
            return {"outcome": outcome, "lambda": lam, "functional": st["E"], "boundary": b, "evals": len(path),
                    "residual": (st["E"] - b) / b, "path": [list(x) for x in path]}
        lo = hi = None                                   # (lo: E < b, hi: E > b)
        lam = 1.0
        while True:
            v = E(lam)
            if abs(v - b) <= tol:
                return finish(lam, "feasible")
            if v < b:
                lo = lam if lo is None or lam > lo else lo
            else:
                hi = lam if hi is None or lam < hi else hi
            if lo is not None and hi is not None:
                break
            if v < b:
                if lam >= LAMBDA_MAX:                    # (E(LAMBDA_MAX) < b: the bracket's top cannot reach it)
                    return finish(lam, "infeasible", "above-sup")
                lam = min(LAMBDA_MAX, lam * 2 if v <= 0 else lam * math.sqrt(b / v) * 1.02)
            else:
                if lam <= 0.0:                           # (E(0) > b: no multiplier reaches it)
                    return finish(lam, "infeasible", "below-inf")
                nl = lam * math.sqrt(b / v) * 0.98
                lam = 0.0 if nl < 1e-3 else nl
            if lam in states:                            # (the scaling step repeats itself: bracket by halving)
                lam = (lam + (lo if lo is not None else 0.0)) / 2
        # Illinois on E(lambda) - b between lo (E < b) and hi (E > b), in either order
        glo, ghi = E(lo) - b, E(hi) - b
        side = 0
        while True:
            if abs(hi - lo) <= LAMBDA_JUMP * max(abs(lo), abs(hi), 1e-9):
                return finish(lo, "construction-infeasible", "jump")        # (lo: the null side of the jump)
            c = (lo * ghi - hi * glo) / (ghi - glo)
            if not min(lo, hi) < c < max(lo, hi):
                c = (lo + hi) / 2
            gc = E(c) - b
            if abs(gc) <= tol:
                return finish(c, "feasible")
            if gc > 0:
                hi, ghi = c, gc
                if side == -1:
                    glo /= 2
                side = -1
            else:
                lo, glo = c, gc
                if side == 1:
                    ghi /= 2
                side = 1

    def observe_all(self):
        """The noisy observation of every triaged world (the shared reference components first)."""
        p, R = self.p, R_REP
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
        for w in self.worlds:
            w.update(self.observe(w["graph"], w["mu"], w["plan"], w["k"], ref_comp, refkeys, LR, LD))
        return self

    # -------------------------------------------------------- the registered functionals of the noise-free panel
    def functionals(self, final=False):
        """The registered analysis functionals of the panel's NOISE-FREE means: H-F the full-history hf()
        quantities (E_C, E_Q, R_C, R_Q, M_F); H-T per epoch the components (the noise-free slopes, the
        searched E^U, the gated selected E^F) and every candidate's fourteen margins. The metric: the
        plug-in bank model at the noise-free means (triage), or the FINAL one, built from the observed
        means (final=True: the D1 boundary check, after observe)."""
        def design(w, scope):
            wg = w["graph"]
            if final:
                cv = w["cov"]
            else:
                if "cov_nf" not in w:
                    mu = w["mu"]
                    w["cov_nf"] = {"C": self.cov(wg, {"C": mu["C"]}, "C"),
                                   "Q": self.cov(wg, {"S": mu["S"], "F": mu["F"]}, "Q"),
                                   "RC": self.cov(wg, {"C": mu["RC"]}, "RC"),
                                   "RQ": self.cov(wg, {"S": mu["RS"], "F": mu["F"]}, "RQ")}
                cv = w["cov_nf"]
            return recurrence.WorldDesign(wg.id, {"C": (wg.ti, wg.tj, cv["C"]), "Q": (wg.ti, wg.tj, cv["Q"])},
                                          {"C": (wg.cT, wg.cR, cv["RC"]), "Q": (wg.qT, wg.qR, cv["RQ"])}, scope)
        if self.hyp == "H-F":
            res = recurrence.hf([recurrence.analyze_world(design(w, "full"), w["y_true"]) for w in self.worlds])
            return {k: (bool(res[k]) if k == "available" else float(res[k]))
                    for k in ("E_C", "E_Q", "R_C", "R_Q", "M_F", "available")}
        comps = {}
        for e in transition.EPOCHS:
            per = []
            for w in self.worlds:
                obs = recurrence.analyze_world(design(w, e), w["y_true"])
                per.append({"obs": obs, "EU_obs": transition.eu_observed(obs)[0]})
            bt = {"P": [w["betas_true"][e][0] for w in self.worlds], "Q": [w["betas_true"][e][1] for w in self.worlds]}
            c = transition.epoch_components(per, bt)[0]
            comps[e] = {k: float(c[k]) for k in transition.KEYS}
        return {"components": comps,
                "margins": {f"{a}->{f}": {k: float(v) for k, v in transition.margins(comps, a, f)}
                            for a, f, _ in transition.candidates()}}

    def member(self):
        """Null membership on the noise-free functionals (the triage metric), with the declared boundary's
        residual there (the D2 ruling). H-F F0-F2: by construction (the absent readout's amplitude is 0);
        F3 / F4: not both R_C > d_C and R_Q > d_Q beyond BOUNDARY_TOL (energy scale); H-T: every one of the
        six candidates has a margin <= BOUNDARY_TOL x its scale. Alternatives: not applicable."""
        if self.stage == "alt":
            return {"member": None, "by": "alternative"}
        if self.hyp == "H-F" and self.mode in ("F0", "F1", "F2"):
            return {"member": True, "by": "construction"}
        fn = self.functionals()
        out = {"by": "functionals", "functionals": fn}
        if self.hyp == "H-F":
            ex = min((fn["E_C"] - D_C ** 2) / D_C ** 2, (fn["E_Q"] - D_Q ** 2) / D_Q ** 2)
            if math.isnan(ex):
                raise CalibError("a NaN material functional (a numerical failure)")
            out.update(member=bool(ex <= BOUNDARY_TOL), exceedance=float(ex))
        else:
            ok, cand, val = ht_membership(fn["margins"])
            out.update(member=ok, strongest=cand, strongest_margin=val)
        decl = declared_boundary(self.hyp, self.mode, self.panel)
        if decl is not None:
            out["boundary"] = boundary_residual(decl, fn)
        return out

    def boundary_final(self):
        """The D1 boundary check after observe: the declared boundary quantity on the noise-free means under
        the FINAL analysis metric (built from the observed means). None without a declared boundary."""
        decl = declared_boundary(self.hyp, self.mode, self.panel)
        if decl is None or self.stage == "alt":
            return None
        try:
            return dict(boundary_residual(decl, self.functionals(final=True)), metric="final")
        except (recurrence.RecurrenceError, transition.TransitionError, backbone.BackboneError,
                np.linalg.LinAlgError, FloatingPointError, ValueError) as e:
            return {"ok": False, "metric": "final", "failure": f"{type(e).__name__}: {e}"}

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
            u0 = len(self.unattainable)
            if pl["dir"] is not None:
                dirC, dirQ, knobs = self.solve_dir(wg, th, pl, u, amp, knobs)
                seq.append((dict(knobs[0]), dict(knobs[1])))
            amp = self.solve_amps(wg, th, pl, u, dirC, dirQ)
            ver = self.verify(wg, th, pl, u, amp, dirC, dirQ)
            if ver["ok"]:
                return dirC, dirQ, amp, dict(ver, rounds=r + 1)
            if pl["dir"] is None:
                break
            del self.unattainable[u0:]                           # (the next round records its own)
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
        raise CalibError(f"{wg.id}: the declared constraints are not met after the joint solve (a numerical "
                         f"failure): {ver['violations'][:3]}")

    def verify(self, wg, th, pl, u, amp, dirC, dirQ):
        """The completed NOISE-FREE panel against its declared constraints: every directional epoch slope
        (beta_P, beta_Q) to DIR_TOL and every numeric post-refit RMS target to AMP_TOL (both sides); an
        infeasible (clipped) target is the recorded exception."""
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
                # the completed panel reproduces the solver's value AND meets the declared target to AMP_TOL
                # on both sides (#68 round 3 P2-4: no overshoot is accepted)
                if (ach is None or not abs(v - ach) <= 1e-9 * max(ach, 1e-12)
                        or not abs(v - tg[h]) <= AMP_TOL * tg[h] + 1e-9 * max(ach, 1e-12)):
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
                # no bracket on the warm-started walk: the registered knob grid, then the extremum, then the
                # bounded-mean limit (the D2 ruling: a ceiling is a numerical failure, not infeasibility)
                xs = [float(x) for x in np.linspace(-KNOB_MAX, KNOB_MAX, 33)]
                gs = [g(x) for x in xs]
                if not all(math.isfinite(v) for v in gs):
                    raise CalibError(f"{wg.id} {e}: a nonfinite survival slope on the knob grid")
                br = [k for k in range(len(xs) - 1) if gs[k] * gs[k + 1] <= 0]
                if br:
                    k = min(br, key=lambda k: (abs(xs[k] - x0), k))
                    a, fa, b, fb = xs[k], gs[k], xs[k + 1], gs[k + 1]
                else:
                    sgn = 1.0 if gs[0] < 0 else -1.0
                    xm, gm = extremum(g, xs, sgn)
                    if sgn * gm >= 0:
                        nb = min((x for x in xs if x != xm), key=lambda x: (abs(x - xm), x))
                        a, fa, b, fb = nb, g(nb), xm, g(xm)
                    else:
                        lad = [s_ * KNOB_MAX * 2.0 ** k for k in range(1, 8) for s_ in (-1, 1)]
                        lad = [x for x in lad if abs(x) <= KNOB_LIM]
                        try:
                            lv = {x: g(x) for x in lad}
                        except (backbone.BackboneError, np.linalg.LinAlgError, FloatingPointError, ValueError) as err:
                            raise CalibError(f"{wg.id} {e}: the survival slope's bounded-mean limit cannot be "
                                             f"established ({type(err).__name__}): a numerical failure") from None
                        ends = [lv[x] for x in lad[-4:]]
                        conv = (all(math.isfinite(v) for v in lv.values())
                                and abs(ends[0] - ends[2]) <= DIR_TOL and abs(ends[1] - ends[3]) <= DIR_TOL)
                        if any(sgn * v >= 0 for v in lv.values()) or not conv:
                            raise CalibError(f"{wg.id} {e}: the survival slope target {tgt:.6g} is "
                                             f"{'reached beyond the knob grid' if conv else 'not shown unattainable'}"
                                             f" (a ceiling: a numerical failure, not infeasibility)")
                        bQ[e] = xm
                        g(xm)
                        self.unattainable.append({"world": wg.id, "scope": e, "readout": "beta_Q", "target": tgt,
                                                  "kind": "above-sup" if sgn > 0 else "below-inf",
                                                  "nearest": tgt + gm, "limit": tgt + max(lv.values(), key=lambda v: sgn * v),
                                                  "knob": xm})
                        continue
            bQ[e] = root(g, a, fa, b, fb, DIR_TOL / 4, f"{wg.id} {e} survival slope {tgt:.6g}")
            g(bQ[e])
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
                "error": res.get("error"), "failure": res.get("failure")}


# ================================================================== declared boundaries, membership
MARGIN_NAMES = tuple(n for n, _ in transition.margins({e: {k: 0.0 for k in transition.KEYS} for e in transition.EPOCHS},
                                                      "E1", "E2"))
MARGIN_SCALE = dict(zip(MARGIN_NAMES, (stats.DELTA_P, stats.DELTA_Q, D_C ** 2, D_Q ** 2, D_C ** 2, D_Q ** 2,
                                       stats.DELTA_P, stats.DELTA_P, stats.DELTA_Q, stats.DELTA_Q,
                                       stats.DELTA_P, stats.DELTA_Q, D_C ** 2, D_Q ** 2)))


def declared_boundary(hyp, mode, slot):
    """The scientific boundary a null panel is constructed AT (the D1 caveat / the D2 ruling): F3 E_C =
    d_C^2 (R_C = d_C), F4 E_Q = d_Q^2; T4 components 0-13: margin k of the subtype's candidate = 0. Other
    modes' numeric levels are settings, not boundaries (None)."""
    if hyp == "H-F" and mode in ("F3", "F4"):
        b = D_C ** 2 if mode == "F3" else D_Q ** 2
        return {"kind": "hf", "name": "E_C" if mode == "F3" else "E_Q", "boundary": b, "scale": b}
    if hyp == "H-T" and mode == "T4":
        sub = slot % 32
        if sub // 2 > 13:
            return None
        pair = transition.PAIRS[(slot // 32) % 3]
        a, f = (pair[0], pair[1]) if sub % 2 == 0 else (pair[1], pair[0])
        nm = MARGIN_NAMES[sub // 2]
        return {"kind": "ht", "cand": f"{a}->{f}", "name": nm, "boundary": 0.0, "scale": MARGIN_SCALE[nm]}
    return None


def boundary_residual(decl, fn):
    v = fn[decl["name"]] if decl["kind"] == "hf" else fn["margins"][decl["cand"]][decl["name"]]
    r = (v - decl["boundary"]) / decl["scale"]
    out = {"quantity": decl["name"] if decl["kind"] == "hf" else f"{decl['cand']}:{decl['name']}",
           "value": float(v), "residual": float(r), "ok": bool(math.isfinite(r) and abs(r) <= BOUNDARY_TOL)}
    return out


def ht_membership(margins):
    """H-T null membership from every candidate's margins {cand: {name: value}}: a member iff EVERY one of
    the six candidates has some margin <= BOUNDARY_TOL x its scale (no genuine qualifying transition in any
    epoch pair or direction: clipping one component can strengthen another candidate). -> (member, the
    strongest candidate, its smallest scaled margin). A NaN margin is a numerical failure."""
    best = None
    for cand in sorted(margins):
        vals = [margins[cand][k] / MARGIN_SCALE[k] for k in MARGIN_NAMES]
        if any(math.isnan(v) for v in vals):
            raise CalibError(f"a NaN noise-free margin ({cand}): a numerical failure")
        m = min(vals)
        if best is None or m > best[1]:
            best = (cand, m)
    return bool(best[1] <= BOUNDARY_TOL), best[0], float(best[1])


# ================================================================== provenance
TOOLS = ("calib.py", "recurrence.py", "transition.py", "backbone.py", "stats.py")
GATES_SCHEMA = "finfolk.redqueen.annexH.gates/1"
IDENT = ("graph_sha256", "graph_source", "params_sha256", "params_fitted", "tools_sha256", "draws", "production")


def doc_sha(d):
    """The identity of a JSON artifact (canonical: sorted keys)."""
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()


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


def gate_rates_pass(rates):
    """Every epoch gate's validation re-derived from its counts: the B stratum of F0-F2 x every graph on the
    complete 1,000-panel allocation, each present rate (B and a calibrated I) with its U95 recomputed <=
    0.02. -> {epoch: passed}"""
    out = {}
    for e in transition.EPOCHS:
        ok = all(isinstance(rates.get(f"gate_{e}|{m}|{s}|B"), dict) and rates[f"gate_{e}|{m}|{s}|B"].get("n") == N_VAL
                 for m in ("F0", "F1", "F2") for s in STRATA)
        for k, v in rates.items():
            if not k.startswith(f"gate_{e}|"):
                continue
            fp, n = v.get("fp"), v.get("n")
            if not (isinstance(fp, int) and isinstance(n, int) and 0 <= fp <= n and n >= N_MIN["val"]):
                ok = False
                continue
            ok = ok and stats.clopper_pearson_upper(fp, n) <= 0.02
        out[e] = bool(ok)
    return out


def check_gates(art, man=None, production=False):
    """A frozen epoch-gate artifact (calib.py gates; #68 round 3 P2): every epoch's c_E with its passing
    validation (the rates re-derived), bound to the critical-value and acceptance artifacts it came from;
    with `man` (the consuming H-T run's manifest) the gates must have been calibrated on the SAME graph,
    parameters, code and draws."""
    if not isinstance(art, dict) or art.get("schema") != GATES_SCHEMA:
        raise CalibError("H-T needs the frozen epoch-gate artifact (calib.py gates), schema " + GATES_SCHEMA)
    for e in transition.EPOCHS:
        c = art.get("c_E", {}).get(e)
        if not isinstance(c, (int, float)) or math.isnan(c) or art.get("passed", {}).get(e) is not True:
            raise CalibError(f"the recurrence gate of {e} lacks a passing frozen calibration: H-T is unavailable")
    bad = [e for e, ok in gate_rates_pass(art.get("rates", {})).items() if not ok]
    if bad:
        raise CalibError(f"the gate artifact's validation rates do not support {bad}: H-T is unavailable")
    if not all(isinstance(art.get(k), str) and len(art[k]) == 64 for k in ("crit_sha256", "accept_sha256")):
        raise CalibError("the gate artifact is not bound to its critical-value and acceptance artifacts")
    hm = art.get("hf_manifest") or {}
    if production and not (art.get("production") is True and hm.get("production") is True):
        raise CalibError("production H-T needs gates from a production H-F calibration")
    if man is not None:
        diff = [k for k in IDENT if hm.get(k) != man.get(k)]
        if diff:
            raise CalibError(f"the epoch gates were calibrated on another graph / parameters / code / draws "
                             f"({diff}): H-T cannot consume them")
    return art


# ================================================================== a panel
def run_panel(graph, params, hyp, stage, stratum, mode, panel, gates_c=None, draws=stats.B_BOOT, man=None,
              retry=0, keep=None):
    """One registered PROPOSAL (slot `panel`, retry `retry`; the D2 ruling) -> its JSON record. The graph is
    canonicalized (sorted by world id) first. TRIAGE (noise-free): the class (feasible / infeasible: a
    clipped target), the clips (requested, nearest attainable, the limit evidence), the "max" targets,
    null membership and the noise-free boundary residual. Role: "B" (a feasible member), "I" (an
    infeasible member), "discarded" (a non-member, or `keep(record)` false: a surplus), "alt" (an
    alternative: an infeasible target makes it a non-success), "failed" (a numerical failure ANYWHERE:
    never infeasible, never a non-rejection). Only B / I / alt proposals are simulated with noise and
    analysed (B with the D1 boundary check under the final metric)."""
    t0 = time.process_time()
    rec = {"hyp": hyp, "stage": stage, "stratum": stratum, "mode": mode, "panel": int(panel), "retry": int(retry),
           "manifest": man, "draws": int(draws)}
    if hyp == "H-T" and mode == "T4":
        rec["subtype"] = panel % 32
    if hyp == "H-T" and mode in ("TA1", "TA2"):            # (before generation: a failed alternative keeps it)
        rec["direction"] = "ARD->FSD" if panel % 2 == 0 else "FSD->ARD"
    try:
        g = sorted(graph, key=lambda w: w.id)
        pn = Panel(stratum_worlds(g, stratum), params, hyp, stage, stratum, mode, panel, retry=retry).triage()
        mx = [m["value"] for m in pn.maxima]
        if pn.lam is not None:
            rec["boundary_solve"] = pn.lam
        rec.update(status=pn.status, member=pn.membership["member"], membership=pn.membership, worlds=len(pn.g),
                   clips=pn.unattainable, joint_rounds=max((v.get("rounds", 1) for v in pn.verified), default=0),
                   maxima={"n": len(mx), "min": min(mx) if mx else None, "max": max(mx) if mx else None,
                           "at_edge": sum(1 for m in pn.maxima if m["edge"])})
        if stage == "alt":
            rec.update(role="alt", non_success=bool(pn.unattainable))
        elif not pn.membership["member"]:
            rec["role"] = "discarded"
        else:
            rec["role"] = "B" if pn.status == "feasible" else "I"          # (both infeasible kinds: I)
            if keep is not None and not keep(rec):
                rec.update(role="discarded", surplus=True)
        t1 = time.process_time()
        rec["cpu"] = {"triage": t1 - t0}
        if rec["role"] == "discarded":
            rec["available"] = False
            rec["cpu_total"] = time.process_time() - t0
            return rec
        pn.observe_all()
        if rec["role"] == "B":
            bf = pn.boundary_final()
            if bf is not None:
                rec["boundary_final"] = bf
        t2 = time.process_time()
        if hyp == "H-F":
            a = pn.analyze_hf()
            f = a["full"]
            rec.update(score=f["S"], M=f["M"], R_C=f["R_C"], R_Q=f["R_Q"], material_point=f["material_point"],
                       S_e={e: a[e]["S"] for e in transition.EPOCHS},
                       S_e_available={e: a[e]["available"] for e in transition.EPOCHS},
                       available=f["available"], phase_support={s: a[s]["phase_support"] for s in a})
        else:
            a = pn.analyze_ht(gates_c or {}, draws)
            if a.get("failure"):
                raise CalibError(f"H-T numerical failure (a failed panel, never a non-rejection): {a['error']}")
            rec.update(score=a["T"], S_e=a["S_e"], gates=a["gates"], available=a["available"], winner=a["winner"],
                       phase_support=a["phase_support"], EU_unsupported=a["EU_unsupported"])
            if a.get("error"):
                rec["unavailable_reason"] = a["error"]
        rec["cpu"].update(simulate=t2 - t1, analyze=time.process_time() - t2)
    except (CalibError, recurrence.RecurrenceError, transition.TransitionError, backbone.BackboneError,
            stats.StatsError, np.linalg.LinAlgError, ValueError, FloatingPointError, KeyError) as e:
        rec.update(error=f"{type(e).__name__}: {e}", available=False, role="failed", status="failed")
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


def _manifest(rs, production, probs):
    mans = {json.dumps(r.get("manifest"), sort_keys=True) for r in rs}
    if len(mans) > 1:
        probs.append(f"{len(mans)} different manifests (graph, parameters, tools, draws or gates)")
    man = json.loads(next(iter(mans))) if len(mans) == 1 else None
    if production and (man is None or not man.get("production") or man.get("draws") != stats.B_BOOT
                       or not man.get("params_fitted") or man.get("graph_source") == "synthetic"):
        probs.append("not a production calibration (fitted parameters, the real graph, 9,999 draws)")
    return man


def complete(records, hyp, stage, n, production, modes=None, allow_failed=False):
    """A plain registered allocation (the alternatives): every mode x graph with exactly the panels 0..n-1,
    each once; failures refused unless allow_failed (power counts them as non-successes); one manifest;
    production records only (unless a smoke run). -> {(mode, graph): [records by panel]}, the manifest."""
    rs = [r for r in records if r.get("hyp") == hyp and r.get("stage") == stage]
    by, seen, probs = {}, set(), []
    for r in rs:
        key = (r["mode"], r["stratum"], r["panel"])
        if key in seen:
            probs.append(f"duplicate panel {key}")
        seen.add(key)
        by.setdefault((r["mode"], r["stratum"]), []).append(r)
    for m in (modes or (F_MODES if hyp == "H-F" else T_MODES)):
        for s in STRATA:
            got = sorted(r["panel"] for r in by.get((m, s), []))
            if got != list(range(n)):
                probs.append(f"{hyp} {stage} {m} {s}: {len(got)} panels, the registered 0..{n - 1} needed")
    failed = [(r["mode"], r["stratum"], r["panel"], r["error"]) for r in rs if r.get("error")]
    if failed and not allow_failed:
        probs.append(f"{len(failed)} failed panels (repair and rerun): {failed[:3]}")
    man = _manifest(rs, production, probs)
    if probs:
        raise CalibError("; ".join(probs[:6]))
    return {k: sorted(v, key=lambda r: r["panel"]) for k, v in by.items()}, man


def q_hat(rs, n):
    """The panel-level infeasible fraction over the COMPLETE rounds (every slot proposed: unconditional
    draws of the registered slot mixture), failed proposals excluded, with its Clopper-Pearson q_U."""
    by_r = {}
    for x in rs:
        by_r.setdefault(int(x.get("retry", 0)), []).append(x)
    full = [x for xs in by_r.values() if len({int(y["panel"]) for y in xs}) == n for x in xs]
    cl = [x for x in full if x.get("status") in ("feasible",) + INFEASIBLE]
    k = sum(1 for x in cl if x["status"] in INFEASIBLE)
    return {"infeasible": k, "proposals": len(cl), "q_hat": k / len(cl) if cl else 0.0,
            "q_U": stats.clopper_pearson_upper(k, len(cl)) if cl else 1.0}


def round_plan(rs, n, stage, r):
    """The registered round-r slots (r >= 1) of one stage x mode x graph from its records of rounds < r:
    the slots without a B panel, and EVERY slot while I is short (< n) and q-hat x K could still reach
    N_MIN (I collection)."""
    prev = [x for x in rs if int(x.get("retry", 0)) < r]
    filled = {int(x["panel"]) for x in prev if x.get("role") == "B"}
    n_i = sum(1 for x in prev if x.get("role") == "I")
    if n_i < n and q_hat(prev, n)["q_hat"] * ROUNDS * n >= N_MIN.get(stage, math.inf):
        return list(range(n))
    return [j for j in range(n) if j not in filled]


def proposal_counts(xs):
    c = {"proposals": len(xs), "worlds": sum(int(x.get("worlds", 0)) for x in xs),
         "world_clips": sum(len({c_["world"] for c_ in x.get("clips", []) if c_["world"] != "panel"}) for x in xs)}
    for k in ("feasible",) + INFEASIBLE + ("failed",):
        c[k] = sum(1 for x in xs if x.get("status") == k)
    c["non_null"] = sum(1 for x in xs if x.get("member") is False)
    for k in ("B", "I", "discarded"):
        c[k] = sum(1 for x in xs if x.get("role") == k)
    c["surplus"] = sum(1 for x in xs if x.get("surplus"))
    c["cpu_h"] = sum(float(x.get("cpu_total", 0.0)) for x in xs) / 3600
    return c


def strata(records, hyp, stage, production):
    """The stratified null allocation of one hypothesis and stage (the D2 ruling; #68 round 2 P1-3): per
    mode x graph the complete registered proposal rounds (round 0 every slot; round r exactly round_plan),
    each proposal once, no failed proposal (repair and rerun), B = each slot's FIRST feasible member, every
    infeasible member kept as I, one manifest, production records only (unless a smoke run). -> ({(mode,
    graph): {"B": [by slot], "I": [the first n in (retry, slot) order], "capped": [slots without B],
    "q": q_hat, "counts"}}, the manifest)."""
    n = {"dev": N_DEV, "val": N_VAL}[stage]
    rs = [r for r in records if r.get("hyp") == hyp and r.get("stage") == stage]
    by, seen, probs = {}, set(), []
    for r in rs:
        key = (r["mode"], r["stratum"], int(r["panel"]), int(r.get("retry", 0)))
        if key in seen:
            probs.append(f"duplicate proposal {key}")
        seen.add(key)
        by.setdefault((r["mode"], r["stratum"]), []).append(r)
    failed = [(r["mode"], r["stratum"], r["panel"], r.get("retry", 0), r["error"]) for r in rs if r.get("error")]
    if failed:
        probs.append(f"{len(failed)} failed proposals (numerical failures: repair and rerun): {failed[:3]}")
    man = _manifest(rs, production, probs)
    out = {}
    for m, s in strata_of(hyp):
        xs = by.get((m, s), [])
        where = f"{hyp} {stage} {m} {s}"
        if any(not 0 <= int(x["panel"]) < n or not 0 <= int(x.get("retry", 0)) < ROUNDS for x in xs):
            probs.append(f"{where}: a proposal outside slots 0..{n - 1} x retries 0..{ROUNDS - 1}")
            continue
        r0 = sorted(int(x["panel"]) for x in xs if int(x.get("retry", 0)) == 0)
        if r0 != list(range(n)):
            probs.append(f"{where}: round 0 holds {len(r0)} of the {n} slots")
            continue
        bad_round = False
        for rr in range(1, ROUNDS):
            want = round_plan(xs, n, stage, rr)
            got = sorted(int(x["panel"]) for x in xs if int(x.get("retry", 0)) == rr)
            if got != sorted(want):
                probs.append(f"{where}: round {rr} proposed {len(got)} slots, the registered plan {len(want)}")
                bad_round = True
                break
        if bad_round:
            continue
        B = {}
        for x in sorted(xs, key=lambda x: int(x.get("retry", 0))):
            j = int(x["panel"])
            if x.get("status") == "feasible" and x.get("member") and j not in B:
                if x.get("role") != "B":
                    probs.append(f"{where}: slot {j}'s first feasible member (retry {x.get('retry', 0)}) is not its B")
                B[j] = x
            elif x.get("role") == "B":
                probs.append(f"{where}: slot {j} has a second B panel (retry {x.get('retry', 0)})")
        if any(x.get("status") in INFEASIBLE and x.get("member") and x.get("role") != "I" for x in xs):
            probs.append(f"{where}: an infeasible member was not kept in I")
        I = sorted((x for x in xs if x.get("role") == "I"), key=lambda x: (int(x.get("retry", 0)), int(x["panel"])))
        out[(m, s)] = {"B": [B[j] for j in sorted(B)], "I": I[:n], "capped": [j for j in range(n) if j not in B],
                       "q": q_hat(xs, n), "counts": proposal_counts(xs)}
    if probs:
        raise CalibError("; ".join(probs[:6]))
    return out, man


def _crit(vals):
    sc = sorted(vals)
    return sc[min(math.ceil(0.99 * (len(sc) + 1)), len(sc)) - 1]


def critical_values(records, production=True):
    """H.11 development critical values from the COMPLETE stratified development allocations of the
    hypotheses present (the D2 ruling): per mode x graph x stratum (B; I when it holds >= N_MIN["dev"]
    panels) the plus-one 0.99 order statistic; a decision's value is the LARGEST over its applicable
    modes, graphs and strata; a capped mode makes every decision needing it unavailable (None)."""
    out = {"strata": {}, "manifest": {}, "proposals": {}, "unavailable": {}, "cpu": {}}
    for hyp in ("H-F", "H-T"):
        if not any(r.get("hyp") == hyp and r.get("stage") == "dev" for r in records):
            continue
        st, man = strata(records, hyp, "dev", production)
        out["manifest"][hyp] = man
        out["cpu"][hyp] = {"proposals": sum(d["counts"]["proposals"] for d in st.values()),
                           "cpu_h": sum(d["counts"]["cpu_h"] for d in st.values()), "ceiling_h": stats.CPU_CEILING_H}
        for (m, s), d in sorted(st.items()):
            key = f"{hyp}|{m}|{s}"
            out["proposals"][key] = {"capped": d["capped"], "q": d["q"], "counts": d["counts"], "I_panels": len(d["I"]),
                                     "I_calibrated": len(d["I"]) >= N_MIN["dev"]}
            if d["capped"]:
                out["unavailable"][key] = f"{len(d['capped'])} slot(s) without a B panel after {ROUNDS} proposals"
                continue
            for name, rs in (("B", d["B"]), ("I", d["I"])):
                if name == "I" and len(rs) < N_MIN["dev"]:
                    continue
                rec = {"n": len(rs), "score": _crit(_num(r["score"]) if r["available"] else -math.inf for r in rs)}
                if hyp == "H-F":
                    rec["M"] = _crit(_num(r["M"]) if r["available"] else -math.inf for r in rs)
                    for e in transition.EPOCHS:
                        rec[f"S_{e}"] = _crit(_num(r["S_e"][e]) if r["S_e_available"][e] else -math.inf for r in rs)
                out["strata"][f"{key}|{name}"] = rec

    def mx(hyp, modes, key):
        if any(f"{hyp}|{m}|{s}" in out["unavailable"] for m in modes for s in STRATA):
            return None
        return max(v[key] for k, v in out["strata"].items() if k.split("|")[0] == hyp and k.split("|")[1] in modes)
    if "H-F" in out["manifest"]:
        out["c_F"] = mx("H-F", ("F0", "F1", "F2"), "score")
        out["c_M"] = mx("H-F", F_MODES, "M")
        out["c_E"] = {e: mx("H-F", ("F0", "F1", "F2"), f"S_{e}") for e in transition.EPOCHS}
    if "H-T" in out["manifest"]:
        cT = mx("H-T", T_MODES, "score")
        out["c_T"] = None if cT is None else max(transition.GUARD, cT)
    return out


def p_model(s, tables):
    """max over the applicable validation strata of (1 + #{null >= s}) / (N + 1) (stats.model_p: NaN-safe)."""
    return stats.model_p(s, {str(k): list(t) for k, t in enumerate(tables)})


def hf_rejects(r, crit):
    """The locked H-F rules on one record (the critical part; the p-table requirement can only reduce
    rejections, so validating it is conservative): detection, and the complete nested exceeding-material
    claim (detection, both material points, M_F > c_M, R_C > 0.10, R_Q > 0.04). An unavailable (None)
    critical value is never a rejection here: the decision itself is unavailable (reported separately)."""
    if not r["available"] or crit.get("c_F") is None:
        return False, False
    det = _num(r["score"]) > crit["c_F"]
    mat = (det and crit.get("c_M") is not None and bool(r["material_point"]) and _num(r["M"]) > crit["c_M"]
           and _num(r["R_C"]) > recurrence.D_C and _num(r["R_Q"]) > recurrence.D_Q)
    return det, mat


def acceptance(records, crit, production=True):
    """INDEPENDENT validation (H.11; #68 round 2 P1-1; the D2 ruling): the false positives of the FROZEN
    critical rules on the complete stratified validation allocation (a panel is never judged against a
    table containing itself), per mode x graph x stratum (B; I when it holds >= N_MIN["val"] panels, else
    its scope is reported: q-hat, q_U, alpha_F + q_U with alpha_F the B rate's U95), the one-sided
    Clopper-Pearson U95, pass iff every U95 <= 0.02 and the decision is available. Rates: H-F detection
    (F0-F2), the nested exceeding-material claim (F0-F4), every epoch gate (F0-F2: S_e > c_E); H-T (T0-T4;
    T4 subtype counts with their denominators). The validation manifest must equal the development one.
    Then the model p-value tables per stratum. The report names the critical-value artifact it evaluated
    (crit_sha256). Claim: "passed the model-based screen (U95 <= 0.02) for the registered strata"."""
    out = {"rates": {}, "pass": {}, "ptables": {}, "diagnostics": {}, "proposals": {}, "unavailable": {},
           "scope": {}, "cpu": {}, "crit_sha256": doc_sha(crit), "production": bool(production),
           "critical": {k: crit.get(k) for k in ("c_F", "c_M", "c_E", "c_T") if k in crit},
           "claim": "passed the model-based screen (U95 <= 0.02) for the registered strata"}
    for hyp in ("H-F", "H-T"):
        if hyp not in crit.get("manifest", {}):
            continue
        st, man = strata(records, hyp, "val", production)
        dev = dict(crit["manifest"][hyp])
        if production or dev.get("production"):
            same = {k: man.get(k) == dev.get(k) for k in IDENT + ("gates_sha256",)}
            if not all(same.values()):
                raise CalibError(f"{hyp}: the validation manifest differs from the development one: {same}")
        out["cpu"][hyp] = {"proposals": sum(d["counts"]["proposals"] for d in st.values()),
                           "cpu_h": sum(d["counts"]["cpu_h"] for d in st.values()), "ceiling_h": stats.CPU_CEILING_H}
        rates, tables = {}, {}

        def rate(name, flags):
            k, n = sum(flags), len(flags)
            u = stats.clopper_pearson_upper(k, n)
            rates[name] = {"fp": k, "n": n, "U95": u, "pass": u <= 0.02}
        for (m, s), d in sorted(st.items()):
            key = f"{hyp}|{m}|{s}"
            calI = len(d["I"]) >= N_MIN["val"]
            out["proposals"][key] = {"capped": d["capped"], "q": d["q"], "counts": d["counts"],
                                     "I_panels": len(d["I"]), "I_calibrated": calI}
            if d["capped"]:
                out["unavailable"][key] = f"{len(d['capped'])} slot(s) without a B panel after {ROUNDS} proposals"
                continue
            for name, rs in (("B", d["B"]), ("I", d["I"] if calI else [])):
                if not rs:
                    continue
                sk = f"{m}|{s}|{name}"
                if hyp == "H-F":
                    rej = [hf_rejects(r, crit) for r in rs]
                    if m in ("F0", "F1", "F2"):
                        if crit.get("c_F") is not None:
                            rate(f"detection|{sk}", [d_ for d_, _ in rej])
                        for e in transition.EPOCHS:
                            if crit.get("c_E", {}).get(e) is not None:
                                rate(f"gate_{e}|{sk}", [bool(r["S_e_available"][e]) and _num(r["S_e"][e]) > crit["c_E"][e]
                                                        for r in rs])
                        tables.setdefault("H-F detection", {})[sk] = sorted(_num(r["score"]) if r["available"]
                                                                            else -math.inf for r in rs)
                    if crit.get("c_M") is not None:
                        rate(f"material|{sk}", [x for _, x in rej])
                    tables.setdefault("H-F material", {})[sk] = sorted(_num(r["M"]) if r["available"] else -math.inf
                                                                       for r in rs)
                    dg = {}
                else:
                    flags = [bool(r["available"]) and crit.get("c_T") is not None and _num(r["score"]) > crit["c_T"]
                             for r in rs]
                    if crit.get("c_T") is not None:
                        rate(f"transition|{sk}", flags)
                    tables.setdefault("H-T", {})[sk] = sorted(_num(r["score"]) if r["available"] else -math.inf
                                                              for r in rs)
                    dg = {}
                    if m == "T4":                           # (subtype counts with denominators: diagnostics, H.10)
                        dg["subtypes"] = {st_: {"fp": sum(f for f, r in zip(flags, rs) if r.get("subtype") == st_),
                                                "n": sum(1 for r in rs if r.get("subtype") == st_)} for st_ in range(32)}
                bl = [r.get("boundary_final") for r in rs if r.get("boundary_final")]
                dg.update(unavailable=sum(1 for r in rs if not r["available"]),
                          boundary_checked=len(bl), boundary_null=sum(1 for b in bl if b.get("ok")),
                          boundary_max_abs_residual=max((abs(b["residual"]) for b in bl if "residual" in b), default=None))
                out["diagnostics"][f"{hyp}|{sk}"] = dg
            if not calI:
                bounds = {nm.rsplit("|", 3)[0]: {"alpha_F": v["U95"], "alpha_F_plus_q_U": v["U95"] + d["q"]["q_U"]}
                          for nm, v in rates.items() if nm.endswith(f"|{m}|{s}|B")}
                out["scope"][key] = {"claim": "feasibility-conditioned", "I_panels": len(d["I"]), "q_hat": d["q"]["q_hat"],
                                     "q_U": d["q"]["q_U"], "bounds": bounds}
        out["rates"][hyp] = rates
        out["ptables"].update(tables)

        def ok(prefix, modes):
            if any(f"{hyp}|{m}|{s}" in out["unavailable"] for m in modes for s in STRATA):
                return False
            sel = [v["pass"] for k, v in rates.items() if k.startswith(prefix)]
            return bool(sel) and all(sel)
        if hyp == "H-F":
            out["pass"]["H-F detection"] = ok("detection|", ("F0", "F1", "F2"))
            out["pass"]["H-F material"] = ok("material|", F_MODES)
            for e in transition.EPOCHS:
                out["pass"][f"gate {e}"] = ok(f"gate_{e}|", ("F0", "F1", "F2"))
        else:
            out["pass"]["H-T"] = ok("transition|", T_MODES)
        out.setdefault("manifest", {})[hyp] = man
    return out


def freeze_gates(crit, acc, production=True):
    """The frozen epoch-gate artifact H-T development needs (H.11-H.12; #68 round 3 P2): every epoch's c_E
    with its independently passing validation, BOUND to the artifacts: the acceptance must have evaluated
    exactly this critical-value artifact (crit_sha256) on the same graph, parameters, code and draws, and
    the gate rates are re-derived from their counts; a gate that did not pass refuses the freeze."""
    if crit.get("c_E") is None or "H-F" not in crit.get("manifest", {}):
        raise CalibError("no H-F development calibration (c_E)")
    if acc.get("crit_sha256") != doc_sha(crit):
        raise CalibError("the acceptance report did not evaluate this critical-value artifact (crit_sha256 differs)")
    dm, vm = crit["manifest"]["H-F"], (acc.get("manifest") or {}).get("H-F") or {}
    diff = [k for k in IDENT if vm.get(k) != dm.get(k)]
    if diff:
        raise CalibError(f"the acceptance ran on another graph / parameters / code / draws: {diff}")
    if production and not (acc.get("production") is True and dm.get("production") is True):
        raise CalibError("a production gate artifact needs a production calibration and acceptance")
    rates = {k: v for k, v in acc.get("rates", {}).get("H-F", {}).items() if k.startswith("gate_")}
    passed = gate_rates_pass(rates)
    passed = {e: passed[e] and acc.get("pass", {}).get(f"gate {e}") is True and crit["c_E"].get(e) is not None
              for e in transition.EPOCHS}
    if not all(passed.values()):
        raise CalibError(f"epoch gates without a passing validation: {[e for e, p in passed.items() if not p]}: "
                         "H-T is unavailable")
    return {"schema": GATES_SCHEMA, "c_E": crit["c_E"], "passed": passed, "hf_manifest": dm, "rates": rates,
            "crit_sha256": doc_sha(crit), "accept_sha256": doc_sha(acc), "production": bool(production)}


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(c - h, 0.0), min(c + h, 1.0)]


def power(records, crit, production=True):
    """Development-alternative power (H.10-H.11) with binomial (Wilson) Monte Carlo intervals on the
    registered allocation (#68 round 3 P2): every alternative mode x graph with exactly the panels 0..99,
    one manifest compatible with the development one; a failed or infeasible (non-success) alternative
    counts in the denominator; H-T also by generating direction (assigned from panel parity BEFORE
    generation: 50 each)."""
    out = {}
    for hyp in ("H-F", "H-T"):
        if not any(r.get("hyp") == hyp and r.get("stage") == "alt" for r in records):
            continue
        by, man = complete(records, hyp, "alt", N_ALT, production, modes=ALT[hyp], allow_failed=True)
        dev = (crit.get("manifest") or {}).get(hyp)
        if production and dev is None:
            raise CalibError(f"{hyp}: the critical values carry no development manifest")
        if dev is not None and (production or dev.get("production")):
            diff = [k for k in IDENT + ("gates_sha256",) if man.get(k) != dev.get(k)]
            if diff:
                raise CalibError(f"{hyp}: the alternatives ran on another graph / parameters / code / draws / gates: {diff}")
        for (m, s), rs in sorted(by.items()):
            rec = out.setdefault(f"{hyp}|{m}|{s}", {"n": 0, "failed": 0, "non_success": 0, "success": {}, "by_direction": {}})
            for r in rs:
                if r.get("error"):
                    ok = False
                elif hyp == "H-F":
                    d, mt = hf_rejects(r, crit)
                    ok = {"detection": d, "material": mt}
                else:
                    ok = bool(r["available"]) and crit.get("c_T") is not None and _num(r["score"]) > crit["c_T"]
                rec["n"] += 1
                rec["failed"] += bool(r.get("error"))
                rec["non_success"] += bool(r.get("non_success"))
                flags = ok if isinstance(ok, dict) else ({"detection": False, "material": False} if hyp == "H-F"
                                                         else {"rejection": ok})
                for k, v in flags.items():
                    rec["success"][k] = rec["success"].get(k, 0) + bool(v and not r.get("non_success"))
                if hyp == "H-T":
                    dn = r.get("direction") or ("ARD->FSD" if r["panel"] % 2 == 0 else "FSD->ARD")
                    dd = rec["by_direction"].setdefault(dn, {"n": 0, "success": 0})
                    dd["n"] += 1
                    dd["success"] += bool(flags["rejection"] and not r.get("non_success"))
    for rec in out.values():
        rec["wilson95"] = {k: wilson(v, rec["n"]) for k, v in rec["success"].items()}
        for dd in rec["by_direction"].values():
            dd["wilson95"] = wilson(dd["success"], dd["n"])
    return out


def _dist(xs):
    xs = sorted(xs)
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "mean": sum(xs) / len(xs), "median": xs[len(xs) // 2], "max": xs[-1]}


def report(records):
    """The D2 report per hyp x stage x mode x graph (and per T4 subtype / TA direction): proposals by class
    and role, capped slots, numerical failures, world-level clip rates, requested vs achieved (the clip
    frequency and the shortfall distribution, maximum included), the "max" targets, the boundary
    residuals (noise-free and final metric), null membership, CPU over EVERY proposal (discarded ones
    included), and the registered rules."""
    groups = {}
    for r in records:
        key = f"{r.get('hyp')}|{r.get('stage')}|{r.get('mode')}|{r.get('stratum')}"
        groups.setdefault(key, []).append(r)
        if r.get("subtype") is not None:
            groups.setdefault(f"{key}|sub{int(r['subtype']):02d}", []).append(r)
        if r.get("direction"):
            groups.setdefault(f"{key}|{r['direction']}", []).append(r)
    fitted = {bool((r.get("manifest") or {}).get("params_fitted")) for r in records}
    out = {"rules": {"rounds": ROUNDS, "K": "ROUNDS x n per stage x mode x graph", "N_MIN": N_MIN,
                     "n_I": "n (dev 160, val 1000)", "BOUNDARY_TOL": BOUNDARY_TOL, "AMP_TOL": AMP_TOL,
                     "DIR_TOL": DIR_TOL, "A_SUP": A_SUP, "A_LIM": A_LIM, "KNOB_MAX": KNOB_MAX, "KNOB_LIM": KNOB_LIM,
                     "streams": "AnnexH/1/<hyp>/<stage>:<graph>/<mode>/<slot>[/retry<r>]/<purpose>",
                     "rounds_rule": "round 0 every slot; round r: the slots without B, every slot while I < n "
                                    "and q_hat x K >= N_MIN"},
           "note": None if fitted == {True} else ("q-hat from synthetic placeholder parameters: illustrative only; "
                                                  "the binding q-hat is the production run's"),
           "groups": {}}
    for key, rs in sorted(groups.items()):
        clips = [c for r in rs for c in r.get("clips", [])]
        rms = [abs(c["target"] - c["nearest"]) / abs(c["target"]) for c in clips if c["readout"] in ("C", "Q", "E_C", "E_Q")]
        slo = [abs(c["target"] - c["nearest"]) for c in clips if c["readout"].startswith("beta")]
        nb = [r["membership"]["boundary"] for r in rs if (r.get("membership") or {}).get("boundary")]
        fb = [r["boundary_final"] for r in rs if r.get("boundary_final")]
        mem = [r for r in rs if r.get("member") is not None]
        g = {"counts": proposal_counts(rs),
             "clips": {"proposals_clipped": sum(1 for r in rs if r.get("clips")), "world_readouts": len(clips),
                       "kinds": {k: sum(1 for c in clips if c.get("kind") == k) for k in ("above-sup", "below-inf", "jump")},
                       "rms_shortfall_relative": _dist(rms), "slope_shortfall": _dist(slo)},
             "maxima_at_edge": sum(int((r.get("maxima") or {}).get("at_edge", 0)) for r in rs),
             "boundary_solve": {"outcomes": {o: sum(1 for r in rs if (r.get("boundary_solve") or {}).get("outcome") == o)
                                             for o in ("feasible",) + INFEASIBLE},
                                "lambda": _dist([r["boundary_solve"]["lambda"] for r in rs if r.get("boundary_solve")]),
                                "evals": _dist([r["boundary_solve"]["evals"] for r in rs if r.get("boundary_solve")])},
             "boundary_noise_free": {"n": len(nb), "ok": sum(1 for b in nb if b["ok"]),
                                     "max_abs_residual": max((abs(b["residual"]) for b in nb), default=None)},
             "boundary_final": {"n": len(fb), "ok": sum(1 for b in fb if b.get("ok")),
                                "max_abs_residual": max((abs(b["residual"]) for b in fb if "residual" in b), default=None)},
             "membership": {"members": sum(1 for r in mem if r["member"]), "non_members": sum(1 for r in mem if not r["member"]),
                            "strongest_candidates": {c: sum(1 for r in mem if not r["member"]
                                                            and r["membership"].get("strongest") == c)
                                                     for c in sorted({r["membership"].get("strongest") for r in mem
                                                                      if not r["member"] and r["membership"].get("strongest")})}}}
        out["groups"][key] = g
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
            s.add_argument("--round", type=int, default=0, help="the proposal round (D2): 0, then 1..ROUNDS-1")
            s.add_argument("--prior", nargs="*", default=[], help="the records of the earlier rounds (round >= 1)")
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
    s.add_argument("--smoke", action="store_true")
    s = sub.add_parser("report")
    s.add_argument("files", nargs="+")
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
                with open(a.gates) as f:                  # (#68 round 3: the gates' graph / parameters / code)
                    art = check_gates(json.load(f), manifest(graph, params, a.draws, None, production, src), production)
                gates = art["c_E"]
            elif a.hyp == "H-T":
                if production:
                    raise CalibError("production H-T panels need the frozen, passing epoch gates (--gates)")
                gates = {e: 0.0 for e in transition.EPOCHS}          # (smoke / bench only: zero gates)
            man = manifest(graph, params, a.draws, art if art else (gates if a.hyp == "H-T" else None),
                           production, src)
            if a.cmd == "panels":
                n_reg = {"dev": N_DEV, "val": N_VAL, "alt": N_ALT}[a.stage]
                if not 0 <= a.lo <= a.hi <= n_reg:
                    raise CalibError(f"slots {a.lo}..{a.hi} outside the registered 0..{n_reg}")
                filled, slots = set(), list(range(a.lo, a.hi))
                if a.round:
                    if a.stage == "alt" or not 1 <= a.round < ROUNDS:
                        raise CalibError(f"proposal rounds 1..{ROUNDS - 1} exist for the null stages only")
                    prior = [r for r in read_records(a.prior) if r.get("hyp") == a.hyp and r.get("stage") == a.stage
                             and r.get("mode") == a.mode and r.get("stratum") == a.stratum
                             and int(r.get("retry", 0)) < a.round]
                    if sorted({int(r["retry"]) for r in prior}) != list(range(a.round)):
                        raise CalibError(f"round {a.round} needs the records of rounds 0..{a.round - 1} (--prior)")
                    plan = set(round_plan(prior, n_reg, a.stage, a.round))
                    slots = [j for j in slots if j in plan]
                    filled = {int(r["panel"]) for r in prior if r.get("role") == "B"}
                with open(a.out, "a") as f:
                    for k in slots:
                        r = run_panel(graph, params, a.hyp, a.stage, a.stratum, a.mode, k, gates, a.draws, man,
                                      retry=a.round, keep=lambda rec: rec["role"] != "B" or rec["panel"] not in filled)
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
            art = freeze_gates(crit, acc, production=not a.smoke)
            with open(a.out, "w") as f:
                json.dump(art, f, indent=1, sort_keys=True)
            print(json.dumps(art["passed"]))
            return 0
        recs = read_records(a.files)
        if a.cmd == "report":
            print(json.dumps(report(recs), indent=1, sort_keys=True))
            return 0
        if a.cmd == "crit":
            print(json.dumps(critical_values(recs, production=not a.smoke), indent=1, sort_keys=True))
            return 0
        with open(a.crit) as f:
            crit = json.load(f)
        if a.cmd == "accept":
            print(json.dumps(acceptance(recs, crit, production=not a.smoke), indent=1, sort_keys=True))
        else:
            print(json.dumps(power(recs, crit, production=not a.smoke), indent=1, sort_keys=True))
        return 0
    except CalibError as e:
        print(f"calib.py {a.cmd}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

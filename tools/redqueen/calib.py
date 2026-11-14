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
  Observation (H.9.2; age-support correction): K = floor(N sigma(a + eps) + 1/2). Capture N is its
  registered bound; survival is min(M_H, floor(600 sigma(a + eps) + 1/2)), with M_H =
  material.cohort_ceiling (#90's common.age_feasible_count: the engine's binary32 age clock, D8 v2
  rule 46). Survival heads are (M_H/600) sigma(eta). The location solves E[K/600] = mu
  under that capped law; endpoint distributions are deterministic. eps = s(mu) (R +
  D + E) with the row (prey snapshot: C, S, F channels), donor (predator snapshot: C, S) and cell
  (SigmaE: capture and exposed survival of one assay cell JOINTLY, their cross-channel covariance kept)
  components by the ACTUAL sharing keys (a reference is one snapshot shared by its block's worlds; a
  free control is generated once per prey snapshot and replicate and reused), unit total latent
  variance per channel; s(mu) by the mean bins [0,.35), [.35,.70), [.70,1] (capture) and [0,.25),
  [.25,.75), [.75,1] (survival); a solves E[K/N] = the requested fraction over its FULL feasible range
  (no clipping):
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
  The analysis covariance V (amendment D4, provisional, 2026-11-08): the bank model evaluated at the
  NULL-MODEL FITTED means (METRIC_MEANS = "null_fit"): per scope (full history and each epoch), per
  channel, the unweighted (OLS) projection of the means onto that scope's own nuisance basis (the within
  design's tensor backbone, the reference design's time basis + reference effects, the predator-free
  survival's six B-splines in prey time), clipped to [1/2N, 1 - 1/2N]; the delta method; shared columns
  per sharing key. The weights then cannot track a tested component that is ORTHOGONAL to the scope's
  nuisance basis (m0 is exactly unchanged by it: a score-test-style metric under H0); a general harmonic
  can overlap the basis and move m0 (the fixture's 3% metric-induced change is no general bound). The triage metric fits the TRUE means, the final metric (the analysis) the OBSERVED
  replicate means; the H-T shared-reference loadings use each reference row's epoch fit. V is computed
  ONCE per observed panel and held fixed across the bootstrap draws (V_PER_DRAW = False: a registered
  conditional approximation, measured by the calibration as part of the whole procedure); True re-fits
  m0 and V for every draw (Panel.redesign through transition.ht(redesign=...): exact but slow).
  s(mu) is SMOOTH and monotone (D4): the noise bank's fitted curve on logit(mu) (noise.s_logit, evaluated
  by noisescale.py, the ONE evaluator the bank's V builder shares: knots and values, linear between,
  constant beyond). PRODUCTION REQUIRES validated curves for C, S and F (check_params; Codex r8 P2-1).
  Synthetic and comparison runs only, when the parameters carry no curve, use the registered bins blended
  linearly on logit(mu) over SMOOTH_W = 0.8 logit units centred on each bin edge (SMOOTH_W = 0 is exactly
  the bins; NOT monotone in general, e.g. the placeholder's survival bins). The validation-stress capture
  floor (0.80 / 0.35 at 0.35) is blended alike. The generator's
  location a(mu; s) interpolates linearly between tables on the registered s grid (S_STEP = 0.005), each
  grid cell's interpolation verified once at its midpoint s over the REGISTERED PROBE SET (the expected
  fractions there of every 7th location of the cell's lower table's grid, within (1e-9, 1 - 1e-9)):
  |E[K/N] - mu| <= LOC_S_TOL. The grid tables depend on (s, N) only: they are built once per process, or
  once per code identity with the on-disk cache (TABLE_CACHE: --table-cache / RQ_TABLE_CACHE, shared by
  shard processes; `calib.py tables` pre-builds every cell a parameter set can reach). The identity is the
  grid constants and tools_sha256 (any change to the tools is a new identity). Each entry carries its kind,
  identity, N and k (checked on read: an entry copied under another name is refused) and a content hash; a
  cell's verification carries the content hashes of its two endpoint tables (checked on read).

FEASIBILITY AND STRATA (the D2 ruling, 2026-11-08; Codex round 4). Three classes. UNREACHED ON THE
REGISTERED SEARCH: the target is not reached by the registered deterministic search (AMP_GRID on [0, A_SUP],
KNOB_GRID on [-KNOB_MAX, KNOB_MAX], LAMBDA_GRID on [0, LAMBDA_MAX], each with a safeguarded bracketed
refinement); the target is clipped to the attained extremum, recorded with the shortfall, and the proposal
is kept in I under that name (never called infeasible). BOUNDED-MEAN INFEASIBLE: only with an analytic bound
(none is implemented: the class is empty). NUMERICAL FAILURE: a solver error or non-convergence: an error;
its allocation is refused until repaired and rerun (H.12).
PROPOSALS (#68 round 4 P2-3: POOLED ORDERED STREAMS PER QUOTA CELL). The proposal unit is the complete
panel. The registered quota cells of a mode (quota_cell): F1 / F2 the two levels (panel parity), T4 the
(subtype, epoch pair) classes of the registered cycle, every other mode one cell; n_c = the cell's slots
among 0..n-1; K_c = ROUNDS x n_c. A cell's stream: proposal k < n_c is its k-th slot on that slot's original
stream (THE AUDIT: every cell's first n_c, i.e. the mode's first n proposals, classified regardless of any
stopping); k >= n_c reuses the cell's configuration on stream "<cell>/<k>". TRIAGE (noise-free) gives the
class (feasible / unreached / numerical failure) and NULL MEMBERSHIP with NO scientific slack (#68 round 4
P2-5): H-F F0-F2 by construction; F3 / F4 not both material energies above threshold + TAU_NUM; H-T
max_c min_j m_cj / s_j <= TAU_NUM over all six candidates (TAU_NUM = 2 DIR_TOL / min(delta) = 1e-3: two
slopes each verified to DIR_TOL at the smallest delta). B-eligible: feasible members (with a declared
boundary, its noise-free residual inside the one-sided window); I-eligible: unreached members. A cell's B
is its first n_c B panels (the triage-metric boundary inside its window), its I its first n_c
I-eligible; the stream continues after the audit while B_c < n_c or (I collection and I_c < n_c), up to K_c;
I collection runs when the mode's audit I-eligible fraction x K >= N_MIN. A cell short of B at K_c is
CAPPED: the mode's calibration and every decision needing it are UNAVAILABLE (p = 1 in Holm), never a
non-rejection. I is calibrated with >= N_MIN panels (dev 99, val 149). THE STRATUM SET IS FROZEN AT DEV
(#68 round 4 P2-7): validation rates exactly the development strata (an I missing at dev keeps its scope
limitation; an I calibrated at dev but short at validation fails the decision) and the set is part of the
critical-value artifact. q-hat (#68 round 4 P2-6) comes from the fixed AUDIT only (Clopper-Pearson), every
class reported (B, final-boundary failures, I-eligible, non-members, failures); the population is "the
registered generator's proposals". Alternatives are unchanged (an unreached alternative is a non-success).
q-hat from the synthetic placeholder parameters is illustrative only; the binding q-hat is the production
run's. T4 subtypes / directions are REPORTED per cell; critical values and p-tables are mode-level (H.10:
the claim is scoped to the registered subtype mixture).
BOUNDARY (#68 round 4 P2-1; the coordinator's ruling of 2026-11-08, Codex r7). A declared boundary (F3:
E_C = d_C^2; F4: E_Q = d_Q^2; T4 components 0-13: margin k of its candidate = 0) is DEFINED under the
TRIAGE metric: the registered analysis functional at the panel's TRUE (noise-free) means, the plug-in
covariance evaluated at those means (the analysis metric's population limit; null membership is a
population property). It must hold ONE-SIDED from the null side, in the window [b (1 - BOUNDARY_TOL), b]
(margins: [-BOUNDARY_TOL, TAU_NUM] x scale), else the proposal is unreached by the construction. The
same functional of the TRUE means under the FINAL analysis metric, T{y(mu); V[m0(mu-hat)]}, is REPORTED
per panel as the METRIC-INDUCED CHANGE at the boundary (not the estimator's total bias), and never gates (gating would condition B on the
noise draw; solving under it would couple the truth to the noise). A numerical exception in the triage
check is a failed proposal; one in the reported final-metric value is recorded with the panel.
H-F F3 / F4 BOUNDARIES ARE FUNCTIONAL (the coordinator's decision (a), 2026-11-08): E_C = d_C^2 (F3) or
E_Q = d_Q^2 (F4) of the noise-free panel (the triage metric) is met by ONE panel multiplier lambda on the
declared component's per-world targets (lambda x D_C / D_Q (D8); the other readout's "max" unchanged):
the actual searched functional (selection, gates, projections, the all-n denominator); lambda in [0,
LAMBDA_MAX = 10], from lambda = 1 by the scaling step lambda sqrt(b / E) until bracketed, then a
safeguarded Illinois / bisection hybrid accepting the NULL-SIDE point E in [b (1 - LAMBDA_TOL), b]; at most
LAMBDA_EVALS evaluations (else a numerical failure). On a JUMP (a selection switching: the bracket narrows
below LAMBDA_JUMP without an accepted point) or an unbracketed domain, LAMBDA_GRID is searched for another
bracket; none: UNREACHED on the registered search, retained at the attained null-side bracket endpoint
(an evaluated point, never a limit), the shortfall recorded.
T4's boundaries stay construction-level (labelled) pending the E^U support decision.

MODES (H.10). H-F (full history): F0 none; F1 capture only (RMS 0.10 / 0.20 by panel parity); F2
survival only (D_Q / 2 D_Q; D8); F3 capture 0.10 + survival max; F4 survival D_Q (D8) + capture max;
alternatives FA1 (D_C, D_Q), FA2 (2 D_C, 2 D_Q). H-T (epochs; one period per world across epochs): T0
stable material directional (1.5 delta), no recurrence; T1 stable recurrence (1.5 D_C, 1.5 D_Q; D8), no
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
production records only (fitted parameters, the real graph restricted to the common Q200 by stats.eligibility's
record, --eligibility: refused below 24, Annex H D6 §§9.1-9.4; 9,999 draws). Validation (acceptance) is
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
decision, and reports CPU seconds per panel against stats.cpu_targets() (D5: 35.1 s; smoke records: never accepted
by crit / accept).

    python3 calib.py panels --hyp H-F --stage dev --graph g.jsonl.gz --params fitted.json --mode F3 \\
        --stratum actual --to 160 --out dev_F3.jsonl --ledger cpu.jsonl        (the audit; --smoke for tests)
    python3 calib.py panels ... --phase continue --cell all --kfrom 160 --kto 480 --prior dev_F3.jsonl \\
        --out dev_F3_c.jsonl                                   (each quota cell's stream to its stopping point)
    python3 calib.py crit dev_HF.jsonl > crit_HF.json
    python3 calib.py accept --crit crit_HF.json val_HF.jsonl > acc_HF.json
    python3 calib.py gates --crit crit_HF.json --accept acc_HF.json --out gates.json
    python3 calib.py panels --hyp H-T ... --gates gates.json ...; crit / accept / power likewise
    python3 calib.py bench --hyp H-F [--graph g.jsonl.gz] [--params p.json] [--panels 50]
    python3 calib.py report dev_*.jsonl val_*.jsonl > report.json       (proposals, clips, boundaries, CPU)
    python3 calib.py ledger cpu.jsonl [--add fitting 7200]               (the cumulative CPU against 240 h: D5)
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
import graph as graphlib  # noqa: E402
import noisescale  # noqa: E402
import recurrence  # noqa: E402
import stats  # noqa: E402
import rqlib  # noqa: E402
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
JOINT_ROUNDS = 24
# THE REGISTERED SEARCHES (#68 round 4 P2-4). A target not reached on its registered search (a deterministic
# grid plus a safeguarded bracketed refinement over a registered domain) is UNREACHED: recorded with the
# attained extremum and the shortfall, kept in I under that name. BOUNDED-MEAN INFEASIBLE needs an analytic
# bound; none is implemented, so that class is empty. A solver error or non-convergence is a NUMERICAL FAILURE.
A_SUP = 4 * A_MAX                                             # the amplitude domain [0, A_SUP]
AMP_GRID = tuple(0.5 * k for k in range(13)) + (2 * A_MAX, A_SUP)
KNOB_MAX = 8.0                                                # the survival knob's domain [-KNOB_MAX, KNOB_MAX]
KNOB_GRID = tuple(float(x) for x in np.linspace(-KNOB_MAX, KNOB_MAX, 33))
LAMBDA_MAX = 10.0                                             # H-F F3 / F4: the panel multiplier's domain [0, 10]
LAMBDA_GRID = tuple(0.5 * k for k in range(21))
LAMBDA_TOL = 1e-3        # the null-side acceptance of the multiplier: E in [b (1 - LAMBDA_TOL), b]
LAMBDA_JUMP = 1e-3       # a bracket narrower than this (relative) without an accepted point: a jump
LAMBDA_EVALS = 60        # evaluations before the multiplier search is a numerical failure
LAMBDA_FROZEN_METRIC = False   # the frozen-metric lambda proposals (Codex round 5 C3: accepted with conditions;
                                 # OFF as registered, 2026-11-08: on g4 its bracket handoff took more true evaluations)
FROZEN_ROUNDS = 4        # re-anchorings of the frozen metric before the true-metric search takes over
BOUNDARY_TOL = 0.05      # the ONE-SIDED boundary window, energy scale [b (1 - 0.05), b] (RMS: [0.9747, 1] x d)
TAU_NUM = 2 * DIR_TOL / min(stats.DELTA_P, stats.DELTA_Q)    # null membership's NUMERICAL allowance (D8 scales)
METRIC_MEANS = "null_fit"    # D4 (provisional, 2026-11-08): V at the null-model fitted means ("raw": the means)
V_PER_DRAW = False           # D4: V once per observed panel, held fixed across the bootstrap draws (registered:
                             # a conditional approximation); True re-fits m0 and V per draw (a slow exact path)
SMOOTH_W = 0.8               # D4: the smooth s(mu)'s blend width at each bin edge, logit units (0: the bins)
S_STEP = 0.005               # D4: the location tables' s grid (linear interpolation between grid tables)
LOC_S_TOL = 2e-6             # D4: the verified bound on |E[K/N](a(mu; s)) - mu| between grid tables
D_C, D_Q = recurrence.D_C, recurrence.D_Q
ROUNDS = 3               # each quota cell's proposal cap K_c = ROUNDS x n_c (the D2 ruling)
N_MIN = {"dev": 99, "val": 149}
UNREACHED = ("unreached", "infeasible")
STRUCTURAL_MODES = ("T0", "T1", "T2", "T3")   # (C2: membership witnessed by the verified slopes alone)
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
        ws = set(w)
        self.coarse = all((a, b) in ws for a in COARSE for b in COARSE)


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
            "capture_bound": capture_bound, "replicates": R_REP,
            "cohort": {"ages": [0.0] * TRIALS, "n": TRIALS, "max_age": 120.0},
            "horizon": 5000, "dt": 0.016}


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
    if production:
        # D8 v2 rules 46 / 51: a fitted mean/noise artifact states its support law, ceiling and age-predicate
        # identity, horizon, timestep and cohort hash; none is defaulted, and a pre-D8 (legacy) fit is refused.
        required = ("cohort", "cohort_sha256", "horizon", "dt", "support_law", "age_clock", "engine_sha256", "survivor_ceiling", "fit")
        missing = [k for k in required if k not in p]
        if missing:
            raise CalibError(f"D8 production fit provenance missing: {missing}; legacy fits must be regenerated")
        expected = {"support_law": stats.material.SUPPORT_LAW, "cohort_sha256": stats.material.AGES_SHA256,
                    "age_clock": stats.material.age_clock_identity(),
                    "survivor_ceiling": stats.material.cohort_ceiling(stats.material.registered_ages(), 5000, 0.016)}
        wrong = sorted(k for k, v in expected.items() if p[k] != v)
        if wrong:
            raise CalibError(f"D8 production fit support-law / age-clock provenance mismatch {wrong}; refit required")
        if not rqlib.is_sha256(p["engine_sha256"]):
            raise CalibError("D8 production fit needs the engine executable sha256")
        fit = p["fit"]
        if not isinstance(fit, dict) or fit.get("mean_head") != "c_H*sigmoid(eta)" or fit.get("noise_likelihood") != "600-rounded-capped-upper-infinity":
            raise CalibError("D8 production fitting identities must describe bounded means and capped interval likelihood")
        # (#68 round 14, engine-field convention, pr68_engine_field_spec_v2 / A_design_v5 2.8: the top-level
        # engine_sha256 is the PRODUCTION ASSAY engine and equals fit.mean.engine_sha256; each fit records the
        # executable that produced its inputs; fit.noise names the adopted noisebank.bank/3 artifact it was
        # copied from. The two engines may differ.)
        for kind in ("mean", "noise"):
            record = fit.get(kind, {})
            if not isinstance(record, dict) or not all(
                    rqlib.is_sha256(record.get(k))
                    for k in ("implementation_sha256", "inputs_sha256", "receipt_sha256", "engine_sha256")):
                raise CalibError(f"D8 production {kind} fit needs implementation, inputs, receipt and engine "
                                 "sha256 identities")
        if not rqlib.is_sha256(fit["noise"].get("source_artifact_sha256")):
            raise CalibError("D8 production noise fit needs the sha256 of the bank artifact it was copied from")
        if p["engine_sha256"] != fit["mean"]["engine_sha256"]:
            raise CalibError("engine_sha256 names the production assay engine and must equal "
                             "fit.mean.engine_sha256; the noise source's executable is fit.noise.engine_sha256")
    cohort = p.get("cohort", stats.material.registered_ages())
    if len(cohort.get("ages", [])) != TRIALS:
        raise CalibError("generator parameters: initial cohort must contain 600 registered ages")
    if production and (cohort != stats.material.registered_ages() or p.get("horizon") != 5000
                       or p.get("dt") != 0.016):
        raise CalibError("production requires the registered ages, 5k horizon and dt=0.016")
    stats.material.cohort_ceiling(cohort, p.get("horizon", 5000), p.get("dt", 0.016))
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
    # (#68 round 14, spec v2 (b): a copied bank noise block agrees with the top-level fields; all modes, and a
    # key that is absent is not checked here, because synthetic placeholder parameters do not carry it)
    for key, top in (("horizon", "horizon"), ("survivor_ceiling", "survivor_ceiling"),
                     ("capture_bound", "capture_bound")):
        if key in nz and nz[key] != p.get(top):
            raise CalibError(f"generator parameters: noise.{key} {nz[key]!r} differs from {top} {p.get(top)!r}")
    if "available" in nz and nz["available"] is not True:
        raise CalibError("generator parameters: the noise block is marked unavailable")
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
    if "s_logit" in nz:                      # (D4 / Codex r8 P2-1: the bank's monotone curves, validated)
        try:
            noisescale.check_set(nz["s_logit"])
        except noisescale.ScaleError as e:
            raise CalibError(f"generator parameters: {e}")
    elif production:
        raise CalibError("generator parameters: production needs the noise bank's monotone s(mu) curves "
                         "(noise.s_logit for C, S and F; D4); the blended bins are for synthetic and comparison "
                         "runs only")
    if "s_logit" not in nz or "s" in nz:
        for ch in ("C", "S", "F"):
            if np.any(np.asarray(nz["s"][ch], float) <= 0):
                raise CalibError(f"generator parameters: noise scales s_{ch} must be positive")
    return p


BANK_SCHEMA_D8 = "finfolk.redqueen.noisebank.bank/3"
NOISE_SOURCE_ADDED = ("source_artifact_sha256",)   # the only key the assembly adds to fit.noise


def check_noise_source(p, bank_bytes):
    """The production noise block and fit.noise are the adopted D8 bank artifact's, copied verbatim: the complete
    canonical noise block, the complete fit.noise record except the enumerated added key, the noise likelihood, and
    the seven shared provenance fields. (#68 round 14, pr68_engine_field_spec_v2; run after
    check_params(production=True), which guarantees the fields read here.)"""
    fit = p["fit"]
    if hashlib.sha256(bank_bytes).hexdigest() != fit["noise"].get("source_artifact_sha256"):
        raise CalibError("noise source: the bank artifact bytes are not the ones named by fit.noise")
    bank = json.loads(bank_bytes)
    if bank.get("schema") != BANK_SCHEMA_D8 or bank.get("status") != "d8-fitted" or bank.get("synthetic") is not False:
        raise CalibError("noise source: not an adopted, non-synthetic noisebank.bank/3 artifact")
    if rqlib.canonical(p["noise"]) != rqlib.canonical(bank["noise"]):
        raise CalibError("noise source: the noise block is not the bank artifact's, verbatim")
    copied = {k: v for k, v in fit["noise"].items() if k not in NOISE_SOURCE_ADDED}
    if rqlib.canonical(copied) != rqlib.canonical(bank["fit"]["noise"]):
        raise CalibError("noise source: fit.noise is not the bank artifact's (only source_artifact_sha256 may be added)")
    if fit["noise_likelihood"] != bank["fit"]["noise_likelihood"]:
        raise CalibError("noise source: noise_likelihood differs from the bank artifact")
    for k in ("cohort", "cohort_sha256", "horizon", "dt", "support_law", "age_clock", "survivor_ceiling"):
        if rqlib.canonical(p[k]) != rqlib.canonical(bank[k]):
            raise CalibError(f"noise source: {k} differs from the bank artifact")
    return p


def _edge_weight(mu, edge, width):
    """0 below the blend band, 1 above, linear on logit(mu) across [logit(edge) - width / 2, + width / 2];
    width 0: the step at the edge, the cutpoint itself in the UPPER bin (mu >= edge: the registered endpoint
    convention of the bins; mooted by the smooth s)."""
    mu = np.asarray(mu, float)
    if width <= 0:
        return (mu >= edge).astype(float)
    x = np.log(np.clip(mu, 1e-300, None) / np.clip(1 - mu, 1e-300, None))
    e = math.log(edge / (1 - edge))
    return np.clip((x - (e - width / 2)) / width, 0.0, 1.0)


def noise_scale(p, ch, mu, stress=False, extra=1.0):
    """s_ch(mu), SMOOTH and monotone (D4): the noise bank's fitted curve (noise.s_logit[ch], evaluated by
    noisescale.evaluate: the evaluator the bank's V builder shares; production requires it, check_params).
    Synthetic / comparison runs without a curve: the registered bins blended on logit(mu) over SMOOTH_W at
    each edge (SMOOTH_W = 0: exactly the bins; not monotone in general). Validation stress (H.9.2): capture
    max(1.5 s, the floor 0.80 below 0.35 / 0.35 above, blended alike), survival 1.5 s."""
    mu = np.asarray(mu, float)
    fn = (p["noise"].get("s_logit") or {}).get(ch)
    if fn:
        out = noisescale.evaluate(fn, mu)
    else:
        s = np.asarray(p["noise"]["s"][ch], float)
        lo, hi = CAP_BINS if ch == "C" else SURV_BINS
        out = s[0] + (s[1] - s[0]) * _edge_weight(mu, lo, SMOOTH_W) + (s[2] - s[1]) * _edge_weight(mu, hi, SMOOTH_W)
    if stress:
        if ch == "C":
            out = np.maximum(1.5 * out, 0.80 + (0.35 - 0.80) * _edge_weight(mu, 0.35, SMOOTH_W))
        else:
            out = 1.5 * out
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


def count_law(N, ceiling=None):
    """Cache key: retain the count scale separately from the upper capped category."""
    if isinstance(N, tuple):
        return N
    return int(N) if ceiling is None or ceiling == N else (int(N), int(ceiling))


def law_support(N):
    return N if isinstance(N, tuple) else (N, N)


def expected_fraction(a, s, N, ceiling=None):
    """E[floor(N sigma(a + s Z) + 1/2)] / N EXACTLY (no quadrature, #68 round 2 P2-6): K >= k iff
    sigma(a + sZ) >= (k - 1/2) / N, so for cap M, E[K] = sum_{k=1..M} Phi((a - logit((k - 1/2)/N)) / s)."""
    N, M = law_support(count_law(N, ceiling))
    a = np.atleast_1d(np.asarray(a, float))
    lk = logit((np.arange(1, M + 1) - 0.5) / N)
    res = np.empty(len(a))
    for c0 in range(0, len(a), 256):                          # (chunks: bounded memory)
        z = (a[c0:c0 + 256, None] - lk[None, :]) / s
        out = np.where(z > 9.0, 1.0, 0.0)                     # (Phi beyond +-9: 1 or 0 within 1e-19)
        mid = np.abs(z) <= 9.0
        out[mid] = 0.5 * erfc(-z[mid] / math.sqrt(2.0))
        res[c0:c0 + 256] = out.sum(axis=1)
    return res / N


def _build_table(s, N):
    """a on a uniform grid and E[K/N](a) (exact), over the range where the expectation leaves (1e-12,
    1 - 1e-12); the linear interpolation's error is VERIFIED at every grid midpoint (<= LOC_TOL)."""
    scale, limit = law_support(N)
    lo, hi = float(logit(0.5 / scale)) - 9.0 * s - 2.0, float(logit((limit - 0.5) / scale)) + 9.0 * s + 2.0
    step = LOC_STEP
    for _ in range(5):
        a = np.arange(lo, hi + step, step)
        f = expected_fraction(a, s, N)
        if np.any(np.diff(f) < 0):
            raise CalibError(f"the rounded-count expectation is not monotone (s {s}, N {N})")
        fm = expected_fraction((a[1:] + a[:-1]) / 2, s, N)
        err = float(np.max(np.abs(fm - (f[1:] + f[:-1]) / 2)))
        if err <= LOC_TOL or limit == scale:
            break
        step /= 2  # The capped category has greater curvature; keep the same verified tolerance.
    if err > LOC_TOL:
        raise CalibError(f"the location table's interpolation error {err:.2e} exceeds {LOC_TOL} (s {s}, N {N})")
    return a, f, err


def location_table(s, N):
    """The verified location table at any s (in-memory cache; the generator itself uses grid_table)."""
    key = (float(s), count_law(N))
    if key not in _LOC:
        _LOC[key] = _build_table(s, N)
    return _LOC[key]


# ---- D4: the s-grid tables, built ONCE: in memory per process, and on disk (TABLE_CACHE) per code identity
TABLE_CACHE = os.environ.get("RQ_TABLE_CACHE") or None
_GRID, _SCELL, _IDENT = {}, {}, []


def tables_identity():
    """The grid tables' identity (Codex r9 P2-2): the registered grid constants and tools_sha256, the whole
    implementation (every numerical helper included); a cached entry is reused only under the same identity."""
    if not _IDENT:
        _IDENT.append(hashlib.sha256(json.dumps([LOC_STEP, LOC_TOL, S_STEP, LOC_S_TOL, tools_sha(), stats.material.specification()]).encode())
                      .hexdigest()[:20])
    return _IDENT[0]


def _arrays_sha(d):
    h = hashlib.sha256()
    for n in sorted(d):
        x = np.ascontiguousarray(d[n])
        h.update(f"{n}|{x.dtype.str}|{x.shape}|".encode())
        h.update(x.tobytes())
    return h.hexdigest()


def _disk(kind, k, N, arrays=None):
    """Read (arrays None) or write one cached grid entry (None without a cache or an entry). Writes are atomic
    (a temporary file renamed), so concurrent shard processes are safe; a damaged entry is a CalibError, never
    silently rebuilt."""
    if not TABLE_CACHE:
        return None
    ident = tables_identity()
    law_tag = str(N).replace(' ', '_')
    path = os.path.join(TABLE_CACHE, f"{kind}-{ident}-N{law_tag}-k{int(k)}.npz")
    me = {"kind": np.array(kind), "identity": np.array(ident), "N": np.array(str(N)), "k": np.array(int(k))}
    if arrays is None:
        if not os.path.isfile(path):
            return None
        try:
            with np.load(path, allow_pickle=False) as z:
                d = {n: z[n] for n in z.files}
        except Exception as e:
            raise CalibError(f"table cache {path}: unreadable ({type(e).__name__})")
        sha = str(d.pop("sha256", ""))
        if sha != _arrays_sha(d):
            raise CalibError(f"table cache {path}: content hash mismatch")
        if any(n not in d or d[n].shape != () or d[n].item() != v.item() for n, v in me.items()):
            raise CalibError(f"table cache {path}: the entry is not ({kind}, {ident}, N {N}, k {k})")
        return {n: v for n, v in d.items() if n not in me}
    import secrets
    import socket
    os.makedirs(TABLE_CACHE, exist_ok=True)
    full = dict(arrays, **me)
    tmp = f"{path}.{socket.gethostname()}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    with open(tmp, "wb") as f:
        np.savez(f, sha256=np.array(_arrays_sha(full)), **full)
    os.replace(tmp, path)
    return arrays


def grid_table(k, N):
    """The verified location table at s = k S_STEP: from memory, else the disk cache, else built (and stored)."""
    key = (int(k), count_law(N))
    if key not in _GRID:
        d = _disk("loc", k, N)
        if d is None:
            a, f, err = _build_table(k * S_STEP, N)
            d = {"a": a, "f": f, "err": np.array(err)}
            _disk("loc", k, N, d)
        _GRID[key] = (d["a"], d["f"], float(d["err"]))
    return _GRID[key]


def _location_grid(mu, k, N):
    a, f, _ = grid_table(k, N)
    if np.any(mu <= f[0]) or np.any(mu >= f[-1]) or not np.all(np.isfinite(mu)):
        raise CalibError(f"an intended mean outside table interior ({f[0]:.3g}, {f[-1]:.3g}), count law {N}: "
                         "cannot attain it")
    return np.interp(mu, f, a)


def _cell_error(k, N):
    """D4: the error of the linear interpolation in s between the grid tables k and k + 1, at the cell's
    midpoint s, over the REGISTERED PROBE SET: the expected fractions there of every 7th location of table k's
    grid, within (1e-9, 1 - 1e-9)."""
    sm = (k + 0.5) * S_STEP
    mu = expected_fraction(grid_table(k, N)[0][::7], sm, N)
    scale, limit = law_support(N)
    mu = mu[(mu > 1e-9) & (mu < limit / scale - 1e-9)]
    if not len(mu):
        return 0.0
    a = 0.5 * (_location_grid(mu, k, N) + _location_grid(mu, k + 1, N))
    return float(np.max(np.abs(expected_fraction(a, sm, N) - mu)))


def _ends(k, N):
    """The content hashes of the cell's two endpoint tables (a cached verification is bound to them)."""
    return np.array([_arrays_sha({"a": grid_table(j, N)[0], "f": grid_table(j, N)[1]}) for j in (k, k + 1)])


def _verify_s_cell(k, N):
    """The grid cell [k, k + 1] S_STEP verified once (|E[K/N] - mu| <= LOC_S_TOL; memory, then the disk cache,
    whose entry must name the content of the endpoint tables in use)."""
    key = (int(k), count_law(N))
    if key not in _SCELL:
        d = _disk("cell", k, N)
        ends = _ends(k, N)
        if d is not None and (d.get("ends") is None or d["ends"].shape != ends.shape or
                              not np.array_equal(d["ends"], ends)):
            raise CalibError(f"table cache: the cell (N {N}, k {k}) was verified on other endpoint tables")
        err = float(d["err"]) if d is not None else _cell_error(k, N)
        if err > LOC_S_TOL:
            raise CalibError(f"the s-grid interpolation error {err:.2e} exceeds {LOC_S_TOL} "
                             f"(s {(k + 0.5) * S_STEP:.4f}, N {N})")
        if d is None:
            _disk("cell", k, N, {"err": np.array(err), "ends": ends})
        _SCELL[key] = err
    return _SCELL[key]


def s_bounds(p, ch, stress=False, extra=1.0):
    """A CONSERVATIVE [lo, hi] of s_ch(mu) over (0, 1) from the SERIALIZED scale values (#68 r10 P3: no sampling of
    mu, which passes through sigmoid and inverse logit, can hide an extreme): a fitted curve is linear in logit
    between knots and constant beyond (noisescale.evaluate), so its range is exactly [min s, max s] of its values;
    the registered bins blend consecutive bins (convex combinations). Then validation stress (capture max(1.5 s,
    the 0.35 .. 0.80 floor): within [max(1.5 lo, 0.35), max(1.5 hi, 0.80)]; survival 1.5 s) and the noise extra."""
    fn = (p["noise"].get("s_logit") or {}).get(ch)
    vals = np.asarray(fn["s"] if fn else p["noise"]["s"][ch], float)
    lo, hi = float(np.min(vals)), float(np.max(vals))
    if stress:
        lo, hi = (max(1.5 * lo, 0.35), max(1.5 * hi, 0.80)) if ch == "C" else (1.5 * lo, 1.5 * hi)
    return lo * extra, hi * extra


def s_spans(p, extras=(1.0, 1.5)):
    """{law: (lo, hi)}, law=N or (N, ceiling): every s the parameter set can reach per trial count (each channel, unstressed and under
    validation stress, at the registered noise extras): the UNION of the sampled range (the logit sample over
    [-16, 16] and every serialized knot, through the real evaluator) and s_bounds' bounds from the serialized
    values (which cover what the sample might miss)."""
    xs = [np.linspace(-16.0, 16.0, 4001)]
    for cv in ((p.get("noise") or {}).get("s_logit") or {}).values():
        xs.append(np.asarray(cv.get("x", []), float))
    mu = sig(np.concatenate(xs))
    spans = {}
    ceiling = stats.material.cohort_ceiling(p.get("cohort", stats.material.registered_ages()),
                                           p.get("horizon", 5000), p.get("dt", 0.016))
    for ch, N in (("C", int(p["capture_bound"])), ("S", count_law(TRIALS, ceiling)), ("F", count_law(TRIALS, ceiling))):
        if law_support(N)[1] == 0:
            continue
        for stress in (False, True):
            for extra in extras:
                s = noise_scale(p, ch, mu, stress, extra)
                blo, bhi = s_bounds(p, ch, stress, extra)
                lo, hi = spans.get(N, (math.inf, -math.inf))
                spans[N] = (min(lo, float(np.min(s)), blo), max(hi, float(np.max(s)), bhi))
    return spans


def warm_tables(p, extras=(1.0, 1.5)):
    """Build (and, with TABLE_CACHE, store) every grid table and cell the parameter set can reach (s_spans: the
    sampled range and the bounds from the serialized scale values) -> {N: [k_lo, k_hi]} (the cells verified)."""
    spans = s_spans(p, extras)
    out = {}
    for N, (lo, hi) in sorted(spans.items(), key=lambda kv: str(kv[0])):
        k0, k1 = int(math.floor(lo / S_STEP + 1e-9)), int(math.floor(hi / S_STEP + 1e-9))
        for k in range(k0, k1 + 1):
            _verify_s_cell(k, N)
        out[N] = [k0, k1]
    return out


def location(mu, s, N, ceiling=None):
    """a(mu) with E[floor(N sigma(a + s Z) + 1/2)] / N = mu, Z ~ N(0, 1) (vectorized over cells), over the
    FULL interior support (0, ceiling/N): no clipping, so distinct means keep distinct expected fractions
    (#68 round 2 P2-6); a mean outside the table's range is refused. A continuous s (D4) interpolates
    linearly between the tables of the registered s grid (S_STEP), each grid cell verified (LOC_S_TOL)."""
    N = count_law(N, ceiling)
    mu, s = np.broadcast_arrays(np.asarray(mu, float), np.asarray(s, float))
    out = np.empty_like(mu)
    k = np.floor(s / S_STEP + 1e-9).astype(np.int64)
    t = s / S_STEP - k
    for kk in np.unique(k):
        m = k == kk
        x = mu[m]
        on = np.abs(t[m]) <= 1e-9
        a_lo = _location_grid(x, kk, N)
        if on.all():
            out[m] = a_lo
            continue
        _verify_s_cell(kk, N)
        a_hi = _location_grid(x, kk + 1, N)
        out[m] = np.where(on, a_lo, (1 - t[m]) * a_lo + t[m] * a_hi)
    return out


def counts(mu, s, eps, N, ceiling=None):
    """Rounded logistic-normal counts on 0..ceiling, preserving feasible means as fractions of N.

    Survival's ceiling is the age-eligible cohort, NOT the binomial denominator (still 600).
    Infeasible means are refused, never silently censored into a different boundary functional.
    """
    limit = N if ceiling is None else ceiling
    mu, s, eps = np.broadcast_arrays(np.asarray(mu, float), s, eps)
    if (type(limit) is not int or not 0 <= limit <= N or np.any(~np.isfinite(mu)) or
            np.any(mu < 0) or np.any(mu > limit / N)):
        raise CalibError("rounded-count mean outside age-bounded support (boundary infeasible)")
    out = np.where(mu == 0, 0., float(limit))
    interior = (mu > 0) & (mu < limit / N)
    if np.any(interior):
        a = location(mu[interior], s[interior], N, limit)
        out[interior] = np.minimum(limit, np.floor(N * sig(a + eps[interior]) + 0.5))
    return out


# ================================================================== D4: the null-model fitted means
NULL_RCOND = 1e-10           # D4: the null fit's lstsq cutoff (relative to the largest singular value)


def _ols(X, y):
    """The deterministic OLS projection of y on X (lstsq, rcond NULL_RCOND); a rank-deficient basis is a
    numerical failure (D4 spec 1)."""
    beta, _, rank, _ = np.linalg.lstsq(X, y, rcond=NULL_RCOND)
    if rank < X.shape[1]:
        raise CalibError(f"a rank-deficient nuisance basis in the null fit ({rank} < {X.shape[1]}): a numerical failure")
    return X @ beta


def null_fit_means(wg, means, scope, N):
    """D4: m0, the means V is evaluated at for `scope`: per channel the unweighted (OLS) projection of `means`
    onto the scope's OWN registered H.3.2 nuisance basis, no harmonics: within capture C and the EXPOSED
    survival S (fitted separately, never the contrast S - F) on the within tensor surface; the free
    controls F (one per prey snapshot, reused by every matched cell) on their six B-splines in prey time;
    reference capture RC and reference exposed survival RS on the common trend + reference intercepts;
    clipped to [0.5 / n, 1 - 0.5 / n]. Entries outside the scope are left as given (its designs mask them).
    The same fit runs on the TRUE channels (the triage metric, the population analogue theta0(mu)) and on the
    OBSERVED ones (the analysis and the final-metric diagnostic)."""
    L, U = recurrence.scope_bounds(scope)
    per = tuple(recurrence.PERIODS.get(scope, ()))
    out = {k: np.array(v, float, copy=True) for k, v in means.items()}
    mw = (wg.ti >= L) & (wg.ti <= U) & (wg.tj >= L) & (wg.tj <= U)
    if mw.any():
        X = recurrence.within_geometry(np.ascontiguousarray(wg.ti[mw]), np.ascontiguousarray(wg.tj[mw]), (L, U), per)["X"]
        for ch, n in (("C", N), ("S", TRIALS)):
            out[ch][mw] = np.clip(_ols(X, out[ch][mw]), 0.5 / n, 1 - 0.5 / n)
    for ch, t, r, n in (("RC", wg.cT, wg.cR, N), ("RS", wg.qT, wg.qR, TRIALS)):
        geo = recurrence.ref_geometry(t, r, (L, U), per)
        if "X" in geo:
            mk = geo["mask"]
            out[ch][mk] = np.clip(_ols(geo["X"], out[ch][mk]), 0.5 / n, 1 - 0.5 / n)
    pm = (wg.prey >= L) & (wg.prey <= U)
    if pm.sum() >= 2:
        Bf = backbone.basis(np.asarray(wg.prey, float)[pm], (L, U))
        out["F"][pm] = np.clip(_ols(Bf, out["F"][pm]), 0.5 / TRIALS, 1 - 0.5 / TRIALS)
    return out


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
        pl["rec"]["full"] = {"F0": (None, None), "F1": (0.10 * m, None), "F2": (None, D_Q * m),
                             "F3": (0.10, "max"), "F4": ("max", D_Q), "FA1": (0.10, D_Q),
                             "FA2": (0.20, (2 * D_Q))}[mode]
        return pl
    E = transition.EPOCHS
    zero = {e: (0.0, 0.0) for e in E}
    if mode == "T0":
        pl["dir"] = {e: (1.5 * dP, 1.5 * dQ) for e in E}
    elif mode == "T1":
        pl["dir"], pl["rec"] = dict(zero), {e: (0.15, (1.5 * D_Q)) for e in E}
    elif mode == "T2":
        pl["dir"], pl["rec"] = {e: (1.5 * dP, 1.5 * dQ) for e in E}, {e: (0.15, (1.5 * D_Q)) for e in E}
    elif mode == "T3":
        pl["dir"] = dict(zero)
        pl.update(sat=2.5 if k % 2 == 0 else 0.0, extra=1.5, stress_ar=True)
    elif mode in ("T4", "TA1", "TA2"):
        pair = transition.PAIRS[(panel // 32) % 3] if mode == "T4" else transition.PAIRS[(panel // 2) % 3]
        sub = panel % 32 if mode == "T4" else None
        forward = (sub % 2 == 0) if mode == "T4" else (panel % 2 == 0)
        a, f = (pair[0], pair[1]) if forward else (pair[1], pair[0])
        ard_dir, fsd_rec = {"T4": ((1.5 * dP, 1.5 * dQ), (0.15, (1.5 * D_Q))), "TA1": ((dP, dQ), (0.10, D_Q)),
                            "TA2": ((2 * dP, 2 * dQ), (0.20, (2 * D_Q)))}[mode]
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
                r[a] = (r[a][0], D_Q)
            elif comp == 4:
                r[f] = (0.10, r[f][1])
            elif comp == 5:
                r[f] = (r[f][0], D_Q)
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
                r[a], r[f] = (r[a][0], D_Q), (r[f][0], D_Q)
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
_VERSION = __import__("itertools").count(1)          # (cache-guard versions: never reused, unlike id())


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

    def __init__(self, graph, params, hyp, stage, stratum, mode, panel, stress=None, stream=None):
        self.g, self.p = graph, check_params(params)
        self.survivor_ceiling = stats.material.cohort_ceiling(
            params.get("cohort", stats.material.registered_ages()), params.get("horizon", 5000), params.get("dt", 0.016))
        self.hyp, self.stage, self.stratum, self.mode, self.panel = hyp, stage, stratum, mode, panel
        self.stress = (stage == "val") if stress is None else stress
        # (the slot's original streams for the audit; a quota cell's continuation "<cell>/<k>" its own)
        self.tag = (hyp, f"{stage}:{stratum}", mode, panel if stream is None else stream)
        self.unattainable, self.verified, self.achieved, self.maxima = [], [], {}, []
        self._metric = {}

    def rng(self, purpose):
        return VecSplitMix64(stats.stream_seed(*self.tag, purpose, namespace=CALIBRATION_NAMESPACE))

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

    def means(self, lat):
        """D8 mean heads on the feasible support, including every boundary-search proposal."""
        c = self.survivor_ceiling / TRIALS
        return {ch: sig(eta) * (1.0 if ch in ("C", "RC") else c) for ch, eta in lat.items()}

    # -------------------------------------------------------- native means and covariance
    def native(self, wg, lat):
        """Native expected responses (noise-free): within C, within Q, ref C, ref Q."""
        m = self.means(lat)
        free = dict(zip(wg.prey.tolist(), m["F"].tolist()))
        out = {"RC": m["RC"], "RQ": m["RS"] - np.array([free[t] for t in wg.qT])}
        if "C" in lat:
            out.update(C=m["C"], Q=m["S"] - np.array([free[t] for t in wg.ti]))
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

    def eval_means(self, wg, means, scope):
        """D4: the means V is evaluated at (METRIC_MEANS: "null_fit", registered; "raw" for comparison)."""
        if METRIC_MEANS == "raw":
            return means
        if METRIC_MEANS != "null_fit":
            raise CalibError(f"METRIC_MEANS {METRIC_MEANS!r}")
        return null_fit_means(wg, means, scope, self.p["capture_bound"])

    def loading_means(self, wg, m):
        """The H-T shared-reference loadings' means (D4): each reference observation at its own epoch's null fit
        (the epochs are disjoint), the full-history fit between epochs."""
        if METRIC_MEANS == "raw":
            return m
        out = self.eval_means(wg, m, "full")
        for e in transition.EPOCHS:
            fe = self.eval_means(wg, m, e)
            L, U = recurrence.SCOPES[e]
            for ch, t in (("RC", wg.cT), ("RS", wg.qT)):
                k = (t >= L) & (t <= U)
                out[ch][k] = fe[ch][k]
        return out

    def scope_covs(self, wg, m):
        return {"C": self.cov(wg, {"C": m["C"]}, "C"), "Q": self.cov(wg, {"S": m["S"], "F": m["F"]}, "Q"),
                "RC": self.cov(wg, {"C": m["RC"]}, "RC"), "RQ": self.cov(wg, {"S": m["RS"], "F": m["F"]}, "RQ")}

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
            m0 = self.means(lat0)
            cv = self.cov(wg, {"C": m0["RC"], "S": m0["RS"], "F": m0["F"]}, key)
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
        (both sides): the smallest on AMP_GRID's brackets. "max": the native RMS maximized on the registered
        search (AMP_GRID on [0, A_SUP], golden refinement; H.10's "as large as bounded means permit" is only
        approximated by that search). A target not reached on the registered search is UNREACHED (#68 round 4
        P2-4): clipped to the attained extremum ("unreached-above": the attained maximum is below the target;
        "unreached-below": the attained minimum, a background, is above it), with the shortfall. A solver that
        fails is a NUMERICAL FAILURE (CalibError)."""
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
        if sign * (v_x - target) >= -tol:                           # (the refined extremum reaches it: bracket)
            if abs(v_x - target) <= tol:
                self.achieved[key] = v_x
                return a_x
            nb = min((x for x in grid if x != a_x), key=lambda x: (abs(x - a_x), x))
            a_r = root(lambda x: f(x) - target, nb, f(nb) - target, a_x, v_x - target, tol, what)
            self.achieved[key] = f(a_r)
            return a_r
        # UNREACHED on the registered search (#68 round 4 P2-4): clipped to the attained extremum
        self.unattainable.append(dict(tag, kind="unreached-above" if sign > 0 else "unreached-below", nearest=v_x,
                                      amp=a_x, shortfall=abs(target - v_x)))
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
                 "mu": self.means(lat),
                 "y_true": {"within": {"C": nat["C"], "Q": nat["Q"]}, "ref": {"C": nat["RC"], "Q": nat["RQ"]}}}
            if pl["dir"] is not None:
                w["betas_true"] = {e: (ver["dir"][f"{e}/beta_P"], ver["dir"][f"{e}/beta_Q"]) for e in transition.EPOCHS}
            self.worlds.append(w)
        decl = declared_boundary(self.hyp, self.mode, self.panel)
        self.lam = None
        if decl is not None and decl["kind"] == "hf" and self.stage != "alt":
            self.lam = self.solve_boundary(decl)
            status = self.lam["outcome"]
        else:
            status = "unreached" if self.unattainable else "feasible"
        self.membership = self.member()
        bnd = self.membership.get("boundary")
        if status == "feasible" and bnd is not None and not bnd["ok"]:
            status = "unreached"              # (the declared boundary not reached by the registered construction)
        self.status = status
        return self

    def target_summary(self):
        """Requested vs achieved for every declared constraint of the completed noise-free panel (#68 round 4
        P3), per scope / readout: the requested value, worlds, clipped worlds, the achieved range and the
        largest deviation of the unclipped."""
        out = {}
        clip = {(c["world"], c["scope"], c["readout"]): c for c in self.unattainable}
        mx = {(m["world"], m["scope"], m["readout"]): m["value"] for m in self.maxima}
        for w, v in zip(self.worlds, self.verified):
            pl, wid = w["plan"], w["id"]
            items = []
            for scope, tg in pl["rec"].items():
                for h in (0, 1):
                    if tg[h] is None:
                        continue
                    rd = "CQ"[h]
                    got = (mx.get((wid, scope, rd)) if tg[h] == "max"
                           else clip[(wid, scope, rd)]["nearest"] if (wid, scope, rd) in clip
                           else v["rms"].get(f"{scope}/{rd}"))
                    items.append((f"{scope}/{rd}", tg[h], got, (wid, scope, rd) in clip))
            for e, (bp, bq) in (pl["dir"] or {}).items():
                for nm, want in (("beta_P", bp), ("beta_Q", bq)):
                    items.append((f"{e}/{nm}", want, v["dir"].get(f"{e}/{nm}"), (wid, e, nm) in clip))
            for key, want, got, clipped in items:
                d = out.setdefault(key, {"requested": [], "n": 0, "clipped": 0, "achieved_min": None,
                                         "achieved_max": None, "max_abs_dev": 0.0})
                if want not in d["requested"]:
                    d["requested"].append(want)
                d["n"] += 1
                d["clipped"] += clipped
                if got is not None:
                    d["achieved_min"] = got if d["achieved_min"] is None else min(d["achieved_min"], got)
                    d["achieved_max"] = got if d["achieved_max"] is None else max(d["achieved_max"], got)
                    if not clipped and want != "max":
                        d["max_abs_dev"] = max(d["max_abs_dev"], abs(got - want))
        return out

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
        w.update(amp={sc: list(v) for sc, v in amp.items()}, mu=self.means(lat),
                 y_true={"within": {"C": nat["C"], "Q": nat["Q"]}, "ref": {"C": nat["RC"], "Q": nat["RQ"]}})
        self._reset_nf(w)
        return clips

    def solve_boundary(self, decl):
        """H-F F3 / F4: the panel multiplier lambda on the declared component's per-world RMS targets with the
        ACTUAL searched noise-free functional (E_C or E_Q of recurrence.hf: selection, gates, projections, the
        all-n denominator; the triage metric) in the null-side window [b (1 - LAMBDA_TOL), b] (see the
        docstring's H-F F3 / F4 BOUNDARIES; #68 round 4 (C)). With LAMBDA_FROZEN_METRIC the iterates are first
        PROPOSED on a metric frozen at an anchor's means (designs fixed: no rebuild per evaluation) and each
        proposal is accepted only by the TRUE metric (re-anchored up to FROZEN_ROUNDS times); otherwise, and
        whenever no proposal is accepted, the true-metric search decides (it alone classifies unreached).
        -> {"outcome": feasible / unreached, "lambda", "functional", "boundary", "evals", "path"}; the panel
        is left at the retained lambda (its per-world clips there recorded; verify re-run)."""
        h = 0 if decl["name"] == "E_C" else 1
        base = self.worlds[0]["plan"]["rec"]["full"][h]
        b = decl["boundary"]
        tolb = LAMBDA_TOL * b
        states, path, last = {}, [], {}
        frozen = {"evals": 0, "path": []}

        def apply(lam):
            clips = []
            for w in self.worlds:
                clips += self._world_at(w, h, lam * base)
            return clips

        def E(lam):                                         # (the TRUE metric)
            lam = float(lam)
            if lam in states:
                return states[lam]["E"]
            if len(path) >= LAMBDA_EVALS:
                raise CalibError(f"the boundary multiplier did not converge in {LAMBDA_EVALS} evaluations (a "
                                 f"numerical failure): {path[-4:]}")
            clips = apply(lam)
            v = self.functionals()[decl["name"]]
            if not math.isfinite(v):
                raise CalibError("a nonfinite boundary functional (a numerical failure)")
            states[lam] = {"E": v, "clips": clips, "worlds": [{k: w[k] for k in ("amp", "mu", "y_true")}
                                                              for w in self.worlds]}
            last.clear()
            last.update(lam=lam, nf=[(w.get("_dcache_nf"), w.get("_cov_nf_ver")) for w in self.worlds])
            path.append((lam, v))
            return v

        def accepted(v):
            return -tolb <= v - b <= 0.0

        def within(v):                    # (the registered one-sided boundary window [b (1 - BOUNDARY_TOL), b])
            return -BOUNDARY_TOL * b <= v - b <= 0.0

        def finish(lam, outcome, kind=None):
            st = states[lam]
            reuse = last.get("lam") == lam                  # (the designs of the last evaluation: exact reuse)
            for i, (w, x) in enumerate(zip(self.worlds, st["worlds"])):
                w.update(x)
                self._reset_nf(w)
                if reuse and last["nf"][i][0] is not None:
                    w["_dcache_nf"], w["_cov_nf_ver"] = last["nf"][i]
                w["plan"]["rec"]["full"] = tuple(lam * base if i_ == h else t
                                                 for i_, t in enumerate(w["plan"]["rec"]["full"]))
            self.unattainable = list(st["clips"])
            if kind is not None:
                self.unattainable.append({"world": "panel", "scope": "full", "readout": decl["name"], "target": b,
                                          "kind": kind, "nearest": st["E"], "lambda": lam,
                                          "shortfall": abs(b - st["E"])})
            self.verified = []
            for w in self.worlds:
                th, u, dirC, dirQ = w["_ctx"]
                ampw = {sc: tuple(v) for sc, v in w["amp"].items()}
                self.achieved[(w["id"], "full", h)] = self.rms_of(w["graph"], th, w["plan"], u, ampw, "full", h, dirC, dirQ)
                ver = self.verify(w["graph"], th, w["plan"], u, ampw, dirC, dirQ)
                if not ver["ok"]:
                    raise CalibError(f"{w['id']}: the per-world targets at lambda {lam:.6g} do not verify: "
                                     f"{ver['violations'][:2]} (a numerical failure)")
                self.verified.append(dict(ver, world=w["id"]))
            return {"outcome": outcome, "lambda": lam, "functional": st["E"], "boundary": b, "evals": len(path),
                    "residual": (st["E"] - b) / b, "path": [list(x) for x in path],
                    "frozen": {"evals": frozen["evals"], "proposals": frozen["path"], "handoff": frozen.get("handoff")}
                    if LAMBDA_FROZEN_METRIC else None}

        def drive(Ef, seen):
            """The registered search with the evaluator Ef (seen: its evaluated points): -> ("feasible", lam),
            ("jump", the null-side endpoint) or ("end", the unbracketed side: "unreached-above" / "-below")."""
            lo = hi = None
            lam = 1.0
            while True:
                v = Ef(lam)
                if accepted(v):
                    return "feasible", lam
                if v < b:
                    lo = (lam, v - b)
                else:
                    hi = (lam, v - b)
                if lo is not None and hi is not None:
                    break
                if v < b and lam >= LAMBDA_MAX or v > b and lam <= 0.0:
                    return "end", "unreached-above" if v < b else "unreached-below"
                if v < b:
                    lam = min(LAMBDA_MAX, lam * 2 if v <= 0 else lam * math.sqrt(b / v) * 1.02)
                else:
                    nl = lam * math.sqrt(b / v) * 0.98
                    lam = 0.0 if nl < 1e-3 else nl
                if lam in seen:
                    lam = (lam + (lo[0] if lo is not None else 0.0)) / 2
            return drive_from(lo[0], hi[0], Ef, seen)

        def grid_search(skip):
            """Every LAMBDA_GRID cell with a sign change of the TRUE E - b (increasing lambda; the cell holding a
            known jump skipped): the first accepted point, else None."""
            gv = [(x, E(x) - b) for x in LAMBDA_GRID]
            for x, v in gv:
                if accepted(v + b):
                    return x
            for (x0, v0), (x1, v1) in zip(gv, gv[1:]):
                if v0 * v1 < 0 and not (skip is not None and x0 <= skip <= x1):
                    res = drive_bracket(x0, v0, x1, v1)
                    if res is not None:
                        return res
            return None

        def drive_bracket(x0, v0, x1, v1):
            lo_, hi_ = (x0, x1) if v0 < 0 else (x1, x0)
            seen_ = {}

            def Ef(x):
                return E(x)
            kind, val = drive_from(lo_, hi_, Ef, seen_)
            return val if kind == "feasible" else None

        def drive_from(lo_, hi_, Ef, seen_):
            glo, ghi = Ef(lo_) - b, Ef(hi_) - b
            side, width, since = 0, abs(hi_ - lo_), 0
            lo, hi = lo_, hi_
            while True:
                if abs(hi - lo) <= LAMBDA_JUMP * max(abs(lo), abs(hi), 1e-9):
                    return "jump", lo
                if since >= 2:
                    c = (lo + hi) / 2
                else:
                    c = (lo * ghi - hi * glo) / (ghi - glo)
                    if not min(lo, hi) < c < max(lo, hi):
                        c = (lo + hi) / 2
                gc = Ef(c) - b
                if accepted(gc + b):
                    return "feasible", c
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
                since += 1
                if abs(hi - lo) <= width / 2:
                    width, since = abs(hi - lo), 0

        def true_bracket():
            """The tightest pair of TRUE evaluations straddling b (the null side below the acceptance window, the
            other above b), or None: the frozen proposals' bracket handed to the true safeguarded solver."""
            lo_ = [(v, lam) for lam, v in path if v - b < -tolb]
            hi_ = [(v, lam) for lam, v in path if v > b]
            if not lo_ or not hi_:
                return None
            return max(lo_)[1], min(hi_)[1]

        def unreached(kind, jump_lo=None):
            if jump_lo is not None:
                keep = jump_lo                                          # (the attained null-side endpoint)
            else:
                below = [(v, lam) for lam, v in path if v <= b]
                keep = max(below)[1] if below else min(path, key=lambda x: x[1])[0]
            if within(states[keep]["E"]):
                return finish(keep, "feasible")                        # (inside the registered boundary window)
            return finish(keep, "unreached", kind)

        if LAMBDA_FROZEN_METRIC:                            # (c): proposals on a frozen metric, the TRUE accepts
            anchor = 1.0
            for _ in range(FROZEN_ROUNDS):
                E(anchor)                                   # (the true metric at the anchor: its designs frozen)
                designs = [self.design_nf(w, "full") for w in self.worlds]
                memo = {}

                def Ef(lam, designs=designs, memo=memo):
                    lam = float(lam)
                    if lam not in memo:
                        if frozen["evals"] >= LAMBDA_EVALS * FROZEN_ROUNDS:
                            raise CalibError("the frozen-metric proposals did not converge (a numerical failure)")
                        apply(lam)
                        memo[lam] = recurrence.hf([recurrence.analyze_world(d, w["y_true"])
                                                   for d, w in zip(designs, self.worlds)])[decl["name"]]
                        frozen["evals"] += 1
                    return memo[lam]
                kind, val = drive(Ef, memo)
                if kind != "feasible":
                    break
                frozen["path"].append(val)
                if accepted(E(val)):
                    return finish(float(val), "feasible")
                br = true_bracket()
                if br is not None:                          # (the handoff: two TRUE values straddle b)
                    frozen["handoff"] = list(br)
                    break
                anchor = float(val)
        br = true_bracket() if LAMBDA_FROZEN_METRIC else None
        kind, val = drive_from(br[0], br[1], E, states) if br is not None else drive(E, states)
        if kind == "feasible":
            return finish(float(val), "feasible")
        if kind == "jump":
            if within(states[val]["E"]):                                # (a jump inside the window: met)
                return finish(val, "feasible")
            c = grid_search(val)
            return finish(float(c), "feasible") if c is not None else unreached("jump", val)
        best = max(((x, lm) for lm, x in path if x <= b), default=None)
        if best is not None and within(best[0]):
            return finish(best[1], "feasible")
        c = grid_search(None)
        return finish(float(c), "feasible") if c is not None else unreached(val)

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
            w["_cov_ver"] = next(_VERSION)                    # (the final metric's version: the cache guard)
            w.pop("_dcache", None)
        return self

    # -------------------------------------------------------- the registered functionals of the noise-free panel
    def functionals(self, final=False):
        """The registered analysis functionals of the panel's NOISE-FREE means: H-F the full-history hf()
        quantities (E_C, E_Q, R_C, R_Q, M_F); H-T per epoch the components (the noise-free slopes, the
        searched E^U, the gated selected E^F) and every candidate's fourteen margins. The metric: the
        plug-in bank model at the noise-free means (triage), or the FINAL one, built from the observed
        means (final=True: the D1 boundary check, after observe)."""
        def design(w, scope):
            return self.design(w, scope) if final else self.design_nf(w, scope)
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
        """Null membership on the noise-free functionals (the triage metric) with NO scientific slack (#68
        round 4 P2-5), and the declared boundary's one-sided residual there. H-F F0-F2: by construction (the
        absent readout's amplitude is 0); F3 / F4: not both material energies above threshold x (1 +
        TAU_NUM); H-T: max_c min_j m_cj / s_j <= TAU_NUM over all six candidates. Alternatives: n/a."""
        if self.stage == "alt":
            return {"member": None, "by": "alternative"}
        if self.hyp == "H-F" and self.mode in ("F0", "F1", "F2"):
            return {"member": True, "by": "construction"}
        if self.hyp == "H-T" and self.mode in STRUCTURAL_MODES:
            w_ = self.structural_witness()
            if w_["member"]:
                return w_
        fn = self.functionals()
        out = {"by": "functionals", "functionals": fn}
        if self.hyp == "H-F":
            ex = min((fn["E_C"] - D_C ** 2) / D_C ** 2, (fn["E_Q"] - D_Q ** 2) / D_Q ** 2)
            if math.isnan(ex):
                raise CalibError("a NaN material functional (a numerical failure)")
            out.update(member=bool(ex <= TAU_NUM), exceedance=float(ex))
        else:
            ok, cand, val = ht_membership(fn["margins"])
            out.update(member=ok, strongest=cand, strongest_margin=val)
        decl = declared_boundary(self.hyp, self.mode, self.panel)
        if decl is not None:
            out["boundary"] = boundary_residual(decl, fn)
        return out

    def structural_witness(self):
        """C2 (Codex round 5, accepted): H-T null membership from the COMPLETED, VERIFIED noise-free capture and
        survival epoch slopes alone. Every candidate's slope-only margins (beta[a], delta -+ beta[f], beta[a] -
        beta[f], panel means of the verified per-world slopes, exactly as the functionals compute them) are
        evaluated; the panel is a member when max_c min_j (slope margin)_cj / s_j <= TAU_NUM. T0 / T2 (beta_P =
        1.5 delta_P in every epoch): delta_P - beta_P[f] scaled <= -0.5 + DIR_TOL / delta_P; T1 / T3 (beta_P
        = 0): beta_P[a] scaled <= DIR_TOL / delta_P (about 1.05e-4 < TAU_NUM = 1e-3). The witness (per candidate
        its pinning margin and scaled value) and the bound are recorded; the noisy analysis runs in full."""
        E = transition.EPOCHS
        comps = {e: {"beta_P": float(np.mean([w["betas_true"][e][0] for w in self.worlds])),
                     "beta_Q": float(np.mean([w["betas_true"][e][1] for w in self.worlds]))} for e in E}
        slope_only = [k for k in MARGIN_NAMES if "E" not in k]
        wit, best = {}, -math.inf
        for a, f, _ in transition.candidates():
            A, F = comps[a], comps[f]
            vals = {"beta_P[a]": A["beta_P"], "beta_Q[a]": A["beta_Q"],
                    "dP-beta_P[f]": stats.DELTA_P - F["beta_P"], "dP+beta_P[f]": stats.DELTA_P + F["beta_P"],
                    "dQ-beta_Q[f]": stats.DELTA_Q - F["beta_Q"], "dQ+beta_Q[f]": stats.DELTA_Q + F["beta_Q"],
                    "beta_P[a]-beta_P[f]": A["beta_P"] - F["beta_P"], "beta_Q[a]-beta_Q[f]": A["beta_Q"] - F["beta_Q"]}
            assert set(vals) == set(slope_only)
            nm = min(vals, key=lambda k: (vals[k] / MARGIN_SCALE[k], k))
            sc = vals[nm] / MARGIN_SCALE[nm]
            if math.isnan(sc):
                raise CalibError("a NaN verified slope (a numerical failure)")
            wit[f"{a}->{f}"] = {"margin": nm, "scaled": float(sc)}
            best = max(best, sc)
        return {"member": bool(best <= TAU_NUM), "by": "structural", "witness": wit, "strongest_margin": float(best),
                "bound": DIR_TOL / stats.DELTA_P, "tau_num": TAU_NUM}

    def boundary_final(self):
        """The REPORTED metric-induced change at the boundary (the coordinator's ruling, 2026-11-08; Codex r7: it
        measures T{y(mu); V[m0(mu-hat)]} against the definition, not the estimator's total bias): the declared
        boundary quantity on the noise-free means under the FINAL analysis metric (built from the observed
        means), with its residual and window flag. Never gates; a numerical exception is recorded here, not a
        failed proposal (the analysis itself decides that). None without a declared boundary."""
        decl = declared_boundary(self.hyp, self.mode, self.panel)
        if decl is None or self.stage == "alt":
            return None
        try:
            return dict(boundary_residual(decl, self.functionals(final=True)), metric="final")
        except (CalibError, recurrence.RecurrenceError, transition.TransitionError, np.linalg.LinAlgError,
                FloatingPointError, ValueError) as e:
            return {"metric": "final", "ok": False, "error": f"{type(e).__name__}: {e}"}

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
        # (#68 round 5 P2-1: every knob, warm starts included, stays in the registered [-KNOB_MAX, KNOB_MAX])
        bC = {e: min(max(v, -KNOB_MAX), KNOB_MAX) for e, v in bC.items()}
        bQ = {e: min(max(v, -KNOB_MAX), KNOB_MAX) for e, v in bQ.items()}
        # capture: a per-epoch secant on the (near-unit) response, all epochs together; an iterate leaving the
        # domain ends it (the per-epoch bracketed fallback below searches the domain itself)
        prev, conv = {}, False
        for _ in range(DIR_STEPS):
            base = self.noiseless_betas(wg, th, pl, u, make(bC), make(bQ), which="P", amp=amp)
            err = {e: base[e][0] - pl["dir"][e][0] for e in E}
            if all(abs(v) <= DIR_TOL / 4 for v in err.values()):
                conv = True
                break
            for e in E:
                d = 1.0
                if e in prev and err[e] != prev[e][1]:
                    d = (err[e] - prev[e][1]) / (bC[e] - prev[e][0])
                prev[e] = (bC[e], err[e])
                bC[e] -= err[e] / (d if abs(d) > 1e-3 else 1.0)
            if any(abs(v) > KNOB_MAX for v in bC.values()):
                bC = {e: min(max(v, -KNOB_MAX), KNOB_MAX) for e, v in bC.items()}
                break
        if not conv:
            # (#68 repair: the coupled secant did not converge, e.g. two epochs oscillating: each epoch in time
            # order alone, bracketed on KNOB_GRID and solved by the safeguarded root; not reached on the grid:
            # UNREACHED, clipped to the attained extremum, like the survival knob)
            for e in E:
                tgt = pl["dir"][e][0]

                def gP(x, e=e, tgt=tgt):
                    bC[e] = x
                    return self.noiseless_betas(wg, th, pl, u, make(bC), make(bQ), only=e, which="P", amp=amp)[e][0] - tgt
                x0 = bC[e]
                f0 = gP(x0)
                if abs(f0) <= DIR_TOL / 4:
                    continue
                xs = list(KNOB_GRID)
                gs = [gP(x) for x in xs]
                if not all(math.isfinite(v) for v in gs):
                    raise CalibError(f"{wg.id} {e}: a nonfinite capture slope on the knob grid")
                br = [k for k in range(len(xs) - 1) if gs[k] * gs[k + 1] <= 0]
                if br:
                    k = min(br, key=lambda k: (abs(xs[k] - x0), k))
                    bC[e] = root(gP, xs[k], gs[k], xs[k + 1], gs[k + 1], DIR_TOL / 4, f"{wg.id} {e} capture slope {tgt:.6g}")
                    gP(bC[e])
                    continue
                sgn = 1.0 if gs[0] < 0 else -1.0
                xm, gm = extremum(gP, xs, sgn)
                if sgn * gm >= 0:
                    nb = min((x for x in xs if x != xm), key=lambda x: (abs(x - xm), x))
                    bC[e] = root(gP, nb, gP(nb), xm, gP(xm), DIR_TOL / 4, f"{wg.id} {e} capture slope {tgt:.6g}")
                    gP(bC[e])
                    continue
                bC[e] = xm
                gP(xm)
                self.unattainable.append({"world": wg.id, "scope": e, "readout": "beta_P", "target": tgt,
                                          "kind": "unreached-above" if sgn > 0 else "unreached-below",
                                          "nearest": tgt + gm, "knob": xm, "shortfall": abs(gm)})
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
            while abs(x0 + sgn * step) <= KNOB_MAX:           # (the ACTUAL trial knob, #68 round 5 P2-1)
                xb = x0 + sgn * step
                fx = g(xb)
                if fx * f0 <= 0:
                    b, fb = xb, fx
                    break
                a, fa, step = xb, fx, step * 2
            if b is None:
                # no bracket on the warm-started walk: the registered knob grid, then the refined extremum; not
                # reached there: UNREACHED (#68 round 4 P2-4), clipped to the attained extremum
                xs = list(KNOB_GRID)
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
                        bQ[e] = xm
                        g(xm)
                        self.unattainable.append({"world": wg.id, "scope": e, "readout": "beta_Q", "target": tgt,
                                                  "kind": "unreached-above" if sgn > 0 else "unreached-below",
                                                  "nearest": tgt + gm, "knob": xm, "shortfall": abs(gm)})
                        continue
            bQ[e] = root(g, a, fa, b, fb, DIR_TOL / 4, f"{wg.id} {e} survival slope {tgt:.6g}")
            g(bQ[e])
        return dirC, make(bQ), (bC, dict(bQ))

    def noiseless_betas(self, wg, th, pl, u, dirC, dirQ, only=None, which="PQ", amp=None):
        lat = self.latent(wg, th, pl, u, amp or {}, dirC, dirQ)
        m = self.means(lat)
        return self.betas(wg, {"C": m["C"] * self.p["capture_bound"] * R_REP,
                               "S": m["S"] * TRIALS * R_REP, "F": m["F"] * TRIALS * R_REP}, only, which)

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
        KS = counts(mu["S"][:, None], sS[:, None], sS[:, None] * (Rw[I, :, 1] + Dw[J, :, 1] + ES), TRIALS, self.survivor_ceiling)
        KF = counts(mu["F"][:, None], sF[:, None], sF[:, None] * (Rw[:, :, 2] + EF), TRIALS, self.survivor_ceiling)
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
        KRS = counts(mu["RS"][:, None], sRS[:, None], sRS[:, None] * (Rw[Iq, :, 1] + RSd + ERS), TRIALS, self.survivor_ceiling)
        fmean = KF.mean(axis=1) / TRIALS
        y = {"within": {"C": KC.mean(axis=1) / N, "Q": KS.mean(axis=1) / TRIALS - fmean[I]},
             "ref": {"C": KRC.mean(axis=1) / N, "Q": KRS.mean(axis=1) / TRIALS - fmean[Iq]}}
        m = {"C": KC.mean(axis=1) / N, "S": KS.mean(axis=1) / TRIALS, "F": fmean,
             "RC": KRC.mean(axis=1) / N, "RS": KRS.mean(axis=1) / TRIALS}
        return {"y": y, "m": m, "K": {"C": KC.sum(axis=1), "S": KS.sum(axis=1), "F": KF.sum(axis=1)},
                "loads": self.ref_loads(wg, self.loading_means(wg, m), refkeys), "nref": len(refkeys)}

    # -------------------------------------------------------- analyses
    @staticmethod
    def _world_design(wg, cv, scope):
        return recurrence.WorldDesign(wg.id, {"C": (wg.ti, wg.tj, cv["C"]), "Q": (wg.ti, wg.tj, cv["Q"])},
                                      {"C": (wg.cT, wg.cR, cv["RC"]), "Q": (wg.qT, wg.qR, cv["RQ"])}, scope)

    def _cached(self, w, cache, ver, means, scope, src=None):
        """A cached design with its GUARD (#68 round 6 P3): the entry stores the means' version (a counter, never
        reused, unlike id()), the graph object, the scope's registered period tuple and the registered
        evaluation means (METRIC_MEANS), and every lookup must match (a mismatch raises). This guards the
        registered lifecycle (means replaced, never mutated in place; the m0 basis is fixed code, fingerprinted
        in solver_identity as m0_basis); it does not detect in-place mutation of arrays or parameters. The
        covariance is built at that scope's evaluation means (D4)."""
        token = (w[ver], id(w["graph"]), tuple(recurrence.PERIODS[scope]), METRIC_MEANS, SMOOTH_W, id(src))
        dc = w.setdefault(cache, {})
        if scope not in dc:
            cv = self.scope_covs(w["graph"], self.eval_means(w["graph"], means, scope))
            dc[scope] = (token, self._world_design(w["graph"], cv, scope))
        elif dc[scope][0] != token:
            raise CalibError(f"{w['id']} {scope}: a stale cached design (means, graph, periods or metric changed)")
        return dc[scope][1]

    def design(self, w, scope):
        """The world's design under the FINAL metric (V at the evaluation means of the OBSERVED replicate means;
        D4: their null fit for this scope), CACHED per scope (#68 CPU lever (a), exact: the analysis and the
        final-metric boundary value use the identical covariance), guarded."""
        return self._cached(w, "_dcache", "_cov_ver", w["m"], scope, src=w["m"])

    def design_nf(self, w, scope):
        """The world's design under the triage metric (V at the evaluation means of the TRUE means; D4: their
        null fit for this scope), CACHED per scope until the means change (_reset_nf)."""
        if "_cov_nf_ver" not in w:
            w["_cov_nf_ver"] = next(_VERSION)
            w["_dcache_nf"] = {}
        mu = w["mu"]
        return self._cached(w, "_dcache_nf", "_cov_nf_ver",
                            {"C": mu["C"], "S": mu["S"], "F": mu["F"], "RC": mu["RC"], "RS": mu["RS"]}, scope, src=mu)

    @staticmethod
    def _reset_nf(w):
        w.pop("_dcache_nf", None)
        w.pop("_cov_nf_ver", None)

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
        return self._analyze_ht(gates_c, draws)

    def redesign(self, e, wid, xi_b):
        """V_PER_DRAW (D4 spec 5; registered OFF): world wid's epoch-e design with V re-fitted for ONE bootstrap
        draw: its reference channels perturbed by the draw's shared-reference source (y + L xi_b; the survival
        loading on the exposed channel), m0 re-fitted, the covariances rebuilt. The within channels do not move."""
        w = next(x for x in self.worlds if x["id"] == wid)
        m = {k: np.array(v, float, copy=True) for k, v in w["m"].items()}
        m["RC"] = m["RC"] + w["loads"]["C"] @ xi_b
        m["RS"] = m["RS"] + w["loads"]["Q"] @ xi_b
        return self._world_design(w["graph"], self.scope_covs(w["graph"], self.eval_means(w["graph"], m, e)), e)

    def _analyze_ht(self, gates_c, draws=stats.B_BOOT):
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
        # (D8 rule 51: only the prefix AnnexH/1/ becomes AnnexH/D8/1/; the remaining keys are the registered ones)
        res = transition.ht(epochs, betas, gates, loads=loads, k=k, analysis=f"calib/{'/'.join(map(str, self.tag))}",
                            draws=draws, report=False, stream_namespace=CALIBRATION_NAMESPACE, redesign=self.redesign if V_PER_DRAW else None)
        return {"T": res["T_T"], "S_e": S, "gates": gates, "available": res["available"],
                "winner": None if not res["winner"] else [res["winner"]["ARD"], res["winner"]["FSD"]],
                "phase_support": res["phase_support"], "EU_unsupported": res["EU_unsupported"],
                "error": res.get("error"), "failure": res.get("failure"), "coverage": res.get("coverage")}


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
    """The declared boundary quantity and its scaled residual r = (v - b) / scale; ok iff r lies in the
    ONE-SIDED null-side window [-BOUNDARY_TOL, 0] (energies), [-BOUNDARY_TOL, TAU_NUM] (margins, whose
    slope pins carry the solver accuracy). #68 round 4 P2-1."""
    v = fn[decl["name"]] if decl["kind"] == "hf" else fn["margins"][decl["cand"]][decl["name"]]
    r = (v - decl["boundary"]) / decl["scale"]
    hi = 0.0 if decl["kind"] == "hf" else TAU_NUM
    return {"quantity": decl["name"] if decl["kind"] == "hf" else f"{decl['cand']}:{decl['name']}",
            "value": float(v), "residual": float(r), "window": [-BOUNDARY_TOL, hi],
            "ok": bool(math.isfinite(r) and -BOUNDARY_TOL <= r <= hi)}


def ht_membership(margins):
    """H-T null membership from every candidate's margins {cand: {name: value}} with NO scientific slack
    (#68 round 4 P2-5): a member iff max_c min_j m_cj / s_j <= TAU_NUM (no genuine qualifying transition in
    any epoch pair or direction, up to the solver accuracy; clipping one component can strengthen another
    candidate). -> (member, the strongest candidate, its smallest scaled margin). A NaN margin is a
    numerical failure."""
    best = None
    for cand in sorted(margins):
        vals = [margins[cand][k] / MARGIN_SCALE[k] for k in MARGIN_NAMES]
        if any(math.isnan(v) for v in vals):
            raise CalibError(f"a NaN noise-free margin ({cand}): a numerical failure")
        m = min(vals)
        if best is None or m > best[1]:
            best = (cand, m)
    return bool(best[1] <= TAU_NUM), best[0], float(best[1])


def quota_cell(hyp, mode, slot):
    """The registered quota cell of a slot (#68 round 4 P2-3): F1 / F2 their level (panel parity), T4 its
    (subtype, epoch pair) of the registered cycle, every other mode one cell."""
    if hyp == "H-F" and mode in ("F1", "F2"):
        return f"lvl{slot % 2}"
    if hyp == "H-T" and mode == "T4":
        return f"sub{slot % 32:02d}pair{(slot // 32) % 3}"
    return "all"


def cells_of(hyp, mode, n):
    """{cell: [its slots among 0..n-1, in order]} (n_c = len)."""
    out = {}
    for j in range(n):
        out.setdefault(quota_cell(hyp, mode, j), []).append(j)
    return out


def proposal_of(hyp, mode, n, cell, k):
    """(configuration slot, stream tag or None) of a cell's k-th proposal: the AUDIT (k < n_c) is the cell's
    k-th slot on its original stream; a continuation (k >= n_c) reuses the cell's first slot's
    configuration on stream "<cell>/<k>"."""
    sl = cells_of(hyp, mode, n)[cell]
    if not 0 <= k < ROUNDS * len(sl):
        raise CalibError(f"proposal {k} outside the cell {cell}'s cap {ROUNDS * len(sl)}")
    return (sl[k], None) if k < len(sl) else (sl[0], f"{cell}/{k}")


# ================================================================== provenance
def _dist(xs):
    xs = sorted(xs)
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "mean": sum(xs) / len(xs), "median": xs[len(xs) // 2], "min": xs[0], "max": xs[-1]}


# (Codex #68 D6 r3 P2: graph.py is part of the calibration identity: eligible_graph / panel_problems execute its
# WINDOWS, OFFSETS and splits() to authorize production inputs, so a change to those checks is a new identity)
TOOLS = ("calib.py", "recurrence.py", "transition.py", "backbone.py", "stats.py", "noisescale.py", "graph.py", "material.py", "fixtures/registered_ages.json")
GATES_SCHEMA = "finfolk.redqueen.annexH.gates/1"
CALIBRATION_NAMESPACE = "AnnexH/D8/1"
IDENT = ("calibration_stream_namespace", "material_spec_sha256", "graph_sha256", "graph_source", "params_sha256", "params_fitted", "tools_sha256", "solver_sha256", "draws",
         "production")


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


def solver_identity():
    """The registered generator / solver settings (#68 round 5 C3: bound into every artifact; tools_sha256 binds
    the implementation itself)."""
    return {"lambda_frozen_metric": LAMBDA_FROZEN_METRIC, "frozen_rounds": FROZEN_ROUNDS, "lambda_grid": list(LAMBDA_GRID),
            "lambda_tol": LAMBDA_TOL, "lambda_jump": LAMBDA_JUMP, "lambda_evals": LAMBDA_EVALS,
            "amp_grid": list(AMP_GRID), "knob_grid": [KNOB_GRID[0], KNOB_GRID[-1], len(KNOB_GRID)],
            "boundary_tol": BOUNDARY_TOL, "tau_num": TAU_NUM, "rounds": ROUNDS, "n_min": N_MIN,
            "structural_modes": list(STRUCTURAL_MODES), "epoch_periods": list(recurrence.EPOCH_PERIODS),
            "metric_means": METRIC_MEANS, "v_per_draw": V_PER_DRAW, "smooth_w": SMOOTH_W, "s_step": S_STEP,
            "loc_s_tol": LOC_S_TOL, "m0_basis": m0_basis()}


def m0_basis():
    """The D4 null fit's basis fingerprint (Codex r8 P3): the scope bounds, the B-spline knots and penalty, the
    registered periods per scope and NULL_RCOND."""
    return doc_sha({"scopes": {k: list(v) for k, v in sorted(recurrence.SCOPES.items())},
                    "knots": [float(x) for x in backbone.KNOTS], "penalty": backbone.PENALTY,
                    "periods": {k: [float(x) for x in v] for k, v in sorted(recurrence.PERIODS.items())},
                    "null_rcond": NULL_RCOND})


def manifest(graph, params, draws, gates=None, production=False, graph_source="synthetic"):
    """Everything a panel record depends on: crit / accept refuse to mix two of them (#68 round 2 P1-3)."""
    return {"calibration_stream_namespace": CALIBRATION_NAMESPACE, "graph_sha256": graph_sha(graph), "graph_source": graph_source, "worlds": len(graph),
            "material_spec": stats.material.specification(), "material_spec_sha256": doc_sha(stats.material.specification()),
            "solver": solver_identity(), "solver_sha256": doc_sha(solver_identity()),
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
    if production and hm.get("material_spec_sha256") != doc_sha(stats.material.specification()):
        raise CalibError("production H-T needs epoch gates calibrated under D8")
    if production and hm.get("calibration_stream_namespace") != CALIBRATION_NAMESPACE:
        raise CalibError("production H-T needs the D8 calibration stream namespace")
    if man is not None:
        diff = [k for k in IDENT if hm.get(k) != man.get(k)]
        if diff:
            raise CalibError(f"the epoch gates were calibrated on another graph / parameters / code / draws "
                             f"({diff}): H-T cannot consume them")
    return art


# ================================================================== a panel
def run_panel(graph, params, hyp, stage, stratum, mode, panel, gates_c=None, draws=stats.B_BOOT, man=None,
              cell=None, k=None, stream=None, keep=None):
    """One registered PROPOSAL -> its JSON record (#68 round 4). `panel`: the configuration slot; `cell`,
    `k`: its quota cell and index in the cell's ordered stream; `stream`: None (the slot's original stream,
    the audit) or "<cell>/<k>". TRIAGE (noise-free): the class (feasible / unreached / numerical failure),
    the clips (requested, attained, shortfall), requested vs achieved for every constraint, null
    membership and the noise-free boundary residual. eligible: "B" (a feasible member), "I" (an unreached
    member) or None. role: "B" / "I" (kept: simulated with noise and analysed; a B panel with a declared
    boundary has its final-metric value REPORTED, never gating), "discarded" (a non-
    member, or `keep(record)` false: a surplus), "alt" (an unreached alternative is a non-success), "failed"
    (a numerical failure ANYWHERE: never unreached, never a non-rejection)."""
    t0 = time.process_time()
    rec = {"hyp": hyp, "stage": stage, "stratum": stratum, "mode": mode, "panel": int(panel), "cell": cell,
           "k": None if k is None else int(k), "stream": stream, "manifest": man, "draws": int(draws)}
    if hyp == "H-T" and mode == "T4":
        rec["subtype"] = panel % 32
    if hyp == "H-T" and mode in ("TA1", "TA2"):            # (before generation: a failed alternative keeps it)
        rec["direction"] = "ARD->FSD" if panel % 2 == 0 else "FSD->ARD"
    try:
        g = sorted(graph, key=lambda w: w.id)
        pn = Panel(stratum_worlds(g, stratum), params, hyp, stage, stratum, mode, panel, stream=stream).triage()
        if pn.lam is not None:
            rec["boundary_solve"] = pn.lam
        mx = [m["value"] for m in pn.maxima]
        mem = pn.membership["member"]
        rec.update(status=pn.status, member=mem, membership=pn.membership, worlds=len(pn.g), clips=pn.unattainable,
                   targets=pn.target_summary(), joint_rounds=max((v.get("rounds", 1) for v in pn.verified), default=0),
                   maxima={"n": len(mx), "min": min(mx) if mx else None, "max": max(mx) if mx else None,
                           "at_edge": sum(1 for m in pn.maxima if m["edge"])})
        if stage == "alt":
            rec.update(role="alt", non_success=pn.status != "feasible")
        else:
            elig = ("B" if pn.status == "feasible" else "I" if pn.status in UNREACHED else None) if mem else None
            rec["eligible"] = elig
            if elig is None:
                rec.update(role="discarded", discard="non-member")
            elif keep is not None and not keep(rec):
                rec.update(role="discarded", discard="surplus")
            else:
                rec["role"] = elig
        t1 = time.process_time()
        rec["cpu"] = {"triage": t1 - t0}
        if rec["role"] == "discarded":
            rec["available"] = False
            rec["cpu_total"] = time.process_time() - t0
            return rec
        pn.observe_all()
        if rec["role"] == "B":
            bf = pn.boundary_final()                      # (REPORTED: the metric-induced change; never gates)
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
                       phase_support=a["phase_support"], EU_unsupported=a["EU_unsupported"], coverage=a.get("coverage"))
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
    if production and (man is None or man.get("material_spec_sha256") != doc_sha(stats.material.specification())
                       or man.get("calibration_stream_namespace") != CALIBRATION_NAMESPACE
                       or not man.get("production") or man.get("draws") != stats.B_BOOT
                       or not man.get("params_fitted") or man.get("graph_source") == "synthetic"
                       or "+eligibility:" not in str(man.get("graph_source"))):
        probs.append("not a production calibration (fitted parameters, the real graph restricted to the common Q200 "
                     "by its eligibility record, 9,999 draws)")
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


def audit_classes(xs):
    """The fixed AUDIT's classes (#68 round 4 P2-6: every cell's first n_c proposals, the mode's first n,
    classified regardless of any stopping) with fixed-sample Clopper-Pearson bounds. Population: the
    registered generator's proposals. Classes: B (a feasible member passing every boundary check),
    final_boundary (a legacy class, always 0 since the final metric is reported only), I_eligible (an
    unreached member),
    feasible_non_member, unreached_non_member, failed (numerical: blocks the allocation)."""
    c = dict.fromkeys(("B", "final_boundary", "I_eligible", "feasible_non_member", "unreached_non_member",
                       "failed"), 0)
    for x in xs:
        if x.get("error"):
            c["failed"] += 1
        elif x.get("eligible") == "B":
            c["final_boundary" if x.get("discard") == "final-boundary" else "B"] += 1
        elif x.get("eligible") == "I":
            c["I_eligible"] += 1
        elif x.get("status") == "feasible":
            c["feasible_non_member"] += 1
        else:
            c["unreached_non_member"] += 1
    n = len(xs) - c["failed"]

    def cp(k):
        return {"k": k, "n": n, "q_hat": k / n if n else 0.0, "q_U": stats.clopper_pearson_upper(k, n) if n else 1.0}
    return {"classes": c, "n": n, "q_I": cp(c["I_eligible"]), "q_final_boundary": cp(c["final_boundary"]),
            "q_non_member": cp(c["feasible_non_member"] + c["unreached_non_member"]),
            "q_not_B": cp(n - c["B"])}


def collect_I(audit, n, stage):
    """I collection (registered): the cells' streams continue past B for I while the mode's AUDIT I-eligible
    fraction x K (= ROUNDS n) >= N_MIN[stage]: fixed by the audit, never by later proposals."""
    a = audit_classes(audit)
    return a["n"] > 0 and a["q_I"]["q_hat"] * ROUNDS * n >= N_MIN.get(stage, math.inf)


def cell_stop(cx, n_c, collect):
    """The registered stopping index of a cell's ordered stream (records sorted by k): the first k >= n_c - 1
    at which the cell holds n_c accepted B panels and, with I collection, n_c I panels; None if the
    records do not reach it."""
    b = i = 0
    for x in cx:
        b += x.get("role") == "B"
        i += x.get("role") == "I"
        if x["k"] >= n_c - 1 and b >= n_c and (not collect or i >= n_c):
            return x["k"]
    return None


def proposal_counts(xs):
    c = {"proposals": len(xs), "worlds": sum(int(x.get("worlds", 0)) for x in xs),
         "world_clips": sum(len({c_["world"] for c_ in x.get("clips", []) if c_["world"] != "panel"}) for x in xs)}
    for k in ("feasible", "unreached", "failed"):
        c[k] = sum(1 for x in xs if x.get("status") == k)
    c["non_member"] = sum(1 for x in xs if x.get("member") is False)
    for k in ("B", "I", "discarded"):
        c[k] = sum(1 for x in xs if x.get("role") == k)
    for k in ("surplus", "final-boundary", "non-member"):
        c[f"discard_{k}"] = sum(1 for x in xs if x.get("discard") == k)
    c["cpu_h"] = sum(float(x.get("cpu_total", 0.0)) for x in xs) / 3600
    return c


def strata(records, hyp, stage, production):
    """The stratified null allocation of one hypothesis and stage (the D2 ruling; #68 round 4 P2-3): per mode
    x graph, per quota cell, the ordered stream k = 0, 1, ... with no gap, its audit complete (k < n_c, each
    the cell's k-th slot on its original stream), the continuation on "<cell>/<k>", run at least to the
    registered stopping point (cell_stop) or the cap K_c; an eligible proposal discarded as a surplus
    before its stratum was full is refused; no failed proposal (repair and rerun); one manifest;
    production records only (unless a smoke run). -> ({(mode, graph): {"B": [...], "I": [...], "capped":
    [cells short of B at K_c], "audit": audit_classes, "collect_I", "counts"}}, the manifest)."""
    n = {"dev": N_DEV, "val": N_VAL}[stage]
    rs = [r for r in records if r.get("hyp") == hyp and r.get("stage") == stage]
    by, seen, probs = {}, set(), []
    for r in rs:
        key = (r["mode"], r["stratum"], r.get("cell"), r.get("k"))
        if key in seen:
            probs.append(f"duplicate proposal {key}")
        seen.add(key)
        by.setdefault((r["mode"], r["stratum"]), []).append(r)
    failed = [(r["mode"], r["stratum"], r.get("cell"), r.get("k"), r["error"]) for r in rs if r.get("error")]
    if failed:
        probs.append(f"{len(failed)} failed proposals (numerical failures: repair and rerun): {failed[:3]}")
    man = _manifest(rs, production, probs)
    out = {}
    for m, s_ in strata_of(hyp):
        xs = by.get((m, s_), [])
        where = f"{hyp} {stage} {m} {s_}"
        cells = cells_of(hyp, m, n)
        bycell = {}
        for x in xs:
            if x.get("cell") not in cells or not isinstance(x.get("k"), int):
                probs.append(f"{where}: a proposal outside the registered quota cells ({x.get('cell')}, {x.get('k')})")
                continue
            bycell.setdefault(x["cell"], []).append(x)
        audit = [x for x in xs if x.get("cell") in cells and isinstance(x.get("k"), int)
                 and x["k"] < len(cells[x["cell"]])]
        collect = collect_I(audit, n, stage)
        B, I, capped = [], [], []
        for c, sl in cells.items():
            cx = sorted(bycell.get(c, []), key=lambda x: x["k"])
            ks = [x["k"] for x in cx]
            if ks != list(range(len(ks))) or len(ks) < len(sl):
                probs.append(f"{where} {c}: the stream holds {len(ks)} proposals with gaps or a short audit "
                             f"({len(sl)} needed)")
                continue
            if any((x["panel"], x.get("stream")) != proposal_of(hyp, m, n, c, x["k"]) for x in cx):
                probs.append(f"{where} {c}: a proposal on the wrong configuration or stream")
                continue
            stop = cell_stop(cx, len(sl), collect)
            if stop is None and len(cx) < ROUNDS * len(sl):
                probs.append(f"{where} {c}: the stream stops before its registered stopping point or cap")
                continue
            used = [x for x in cx if stop is None or x["k"] <= stop]
            b = i = 0
            for x in used:
                if x.get("eligible") == "B":
                    if x.get("discard") == "surplus" and b < len(sl):
                        probs.append(f"{where} {c}: B-eligible proposal {x['k']} discarded before B was full")
                    b += x.get("role") == "B"
                elif x.get("eligible") == "I":
                    if x.get("discard") == "surplus" and i < len(sl):
                        probs.append(f"{where} {c}: I-eligible proposal {x['k']} discarded before I was full")
                    i += x.get("role") == "I"
            cb = [x for x in used if x.get("role") == "B"][:len(sl)]
            if len(cb) < len(sl):
                capped.append(c)
            B += cb
            I += [x for x in used if x.get("role") == "I"][:len(sl)]
        out[(m, s_)] = {"B": B, "I": I, "capped": capped, "audit": audit_classes(audit), "collect_I": collect,
                        "counts": proposal_counts(xs)}
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
    modes, graphs and strata; a capped mode makes every decision needing it unavailable (None). The
    calibrated stratum set is FROZEN here (strata_set; validation rates exactly it)."""
    out = {"strata": {}, "manifest": {}, "proposals": {}, "unavailable": {}, "cpu": {}, "strata_set": {}}
    for hyp in ("H-F", "H-T"):
        if not any(r.get("hyp") == hyp and r.get("stage") == "dev" for r in records):
            continue
        st, man = strata(records, hyp, "dev", production)
        out["manifest"][hyp] = man
        out["cpu"][hyp] = {"proposals": sum(d["counts"]["proposals"] for d in st.values()),
                           "cpu_h": sum(d["counts"]["cpu_h"] for d in st.values()), "ceiling_h": stats.CPU_CEILING_H}
        for (m, s), d in sorted(st.items()):
            key = f"{hyp}|{m}|{s}"
            out["proposals"][key] = {"capped": d["capped"], "audit": d["audit"], "collect_I": d["collect_I"],
                                     "counts": d["counts"], "I_panels": len(d["I"]),
                                     "I_calibrated": len(d["I"]) >= N_MIN["dev"]}
            if d["capped"]:
                out["unavailable"][key] = f"quota cell(s) {d['capped']} short of B at their cap K_c"
                continue
            # (the stratum set, frozen here and bound into the artifact: #68 round 4 P2-7)
            out["strata_set"][key] = ["B"] + (["I"] if len(d["I"]) >= N_MIN["dev"] else [])
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
    claim (detection, both material points, M_F > c_M, R_C > 0.10, R_Q > D_Q (D8)). An unavailable (None)
    critical value is never a rejection here: the decision itself is unavailable (reported separately)."""
    if not r["available"] or crit.get("c_F") is None:
        return False, False
    det = _num(r["score"]) > crit["c_F"]
    mat = (det and crit.get("c_M") is not None and bool(r["material_point"]) and _num(r["M"]) > crit["c_M"]
           and _num(r["R_C"]) > recurrence.D_C and _num(r["R_Q"]) > recurrence.D_Q)
    return det, mat


def acceptance(records, crit, production=True):
    """INDEPENDENT validation (H.11; #68 round 2 P1-1; the D2 ruling; #68 round 4 P2-7): the false positives of
    the FROZEN critical rules on the complete stratified validation allocation, per mode x graph x stratum
    of the stratum set FROZEN AT DEV (crit["strata_set"]): B, and I when development calibrated it (an I
    calibrated at dev but short of N_MIN["val"] here fails its decisions: "unvalidated"); a mode whose I was
    not calibrated at dev keeps its scope limitation however many I panels validation holds (the audit's
    q-hats, alpha_F + q_U for the uncovered null classes). One-sided Clopper-Pearson U95; pass iff every
    U95 <= 0.02 and the decision is available. Rates: H-F detection (F0-F2), the nested exceeding-material
    claim (F0-F4), every epoch gate (F0-F2: S_e > c_E); H-T (T0-T4; T4 subtype counts with denominators:
    reporting only). The validation manifest must equal the development one; the report names the
    critical-value artifact it evaluated (crit_sha256). Claim: "passed the model-based screen (U95 <= 0.02)
    for the registered strata", T4 within its registered subtype mixture."""
    out = {"rates": {}, "pass": {}, "ptables": {}, "diagnostics": {}, "proposals": {}, "unavailable": {},
           "unvalidated": {}, "scope": {}, "cpu": {}, "crit_sha256": doc_sha(crit), "production": bool(production),
           "strata_set": crit.get("strata_set"),
           "critical": {k: crit.get(k) for k in ("c_F", "c_M", "c_E", "c_T") if k in crit},
           "claim": "passed the model-based screen (U95 <= 0.02) for the registered strata (T4: the registered "
                    "subtype mixture)"}
    if not isinstance(crit.get("strata_set"), dict):
        raise CalibError("the critical-value artifact carries no frozen stratum set (strata_set)")
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
            dset = crit["strata_set"].get(key)
            out["proposals"][key] = {"capped": d["capped"], "audit": d["audit"], "collect_I": d["collect_I"],
                                     "counts": d["counts"], "I_panels": len(d["I"]), "dev_strata": dset}
            if d["capped"] or key in crit.get("unavailable", {}) or dset is None:
                out["unavailable"][key] = (f"quota cell(s) {d['capped']} short of B at their cap" if d["capped"]
                                           else "unavailable at development")
                continue
            groups = [("B", d["B"])]
            if "I" in dset:
                if len(d["I"]) >= N_MIN["val"]:
                    groups.append(("I", d["I"]))
                else:
                    out["unvalidated"][key] = f"I calibrated at development, {len(d['I'])} < {N_MIN['val']} here"
            for name, rs in groups:
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
                    if m == "T4":                           # (subtype counts with denominators: reporting, H.10)
                        dg["subtypes"] = {st_: {"fp": sum(f for f, r in zip(flags, rs) if r.get("subtype") == st_),
                                                "n": sum(1 for r in rs if r.get("subtype") == st_)} for st_ in range(32)}
                bl = [r.get("boundary_final") for r in rs if r.get("boundary_final")]
                res_ = [b["residual"] for b in bl if "residual" in b and math.isfinite(b["residual"])]
                dg.update(unavailable=sum(1 for r in rs if not r["available"]), boundary_checked=len(bl),
                          metric_induced_change=_dist(res_),      # (T{y(mu); V[m0(mu-hat)]}: reported only)
                          final_metric_errors=sum(1 for b in bl if "error" in b),
                          boundary_max_abs_residual=max((abs(x) for x in res_), default=None))
                out["diagnostics"][f"{hyp}|{sk}"] = dg
            if "I" not in dset:                             # (the dev scope limitation carries through)
                a = d["audit"]
                unc = a["classes"]["I_eligible"] + a["classes"]["final_boundary"]
                qU = stats.clopper_pearson_upper(unc, a["n"]) if a["n"] else 1.0
                bounds = {nm.rsplit("|", 3)[0]: {"alpha_F": v["U95"], "alpha_F_plus_q_U": v["U95"] + qU}
                          for nm, v in rates.items() if nm.endswith(f"|{m}|{s}|B")}
                out["scope"][key] = {"claim": "feasibility-conditioned (I not calibrated at development)",
                                     "population": "the registered generator's proposals",
                                     "uncovered_null_classes": {"I_eligible": a["classes"]["I_eligible"],
                                                                "final_boundary": a["classes"]["final_boundary"]},
                                     "excluded_non_null": a["classes"]["feasible_non_member"]
                                     + a["classes"]["unreached_non_member"],
                                     "audit_n": a["n"], "q_uncovered_U": qU, "bounds": bounds}
        out["rates"][hyp] = rates
        out["ptables"].update(tables)

        def ok(prefix, modes):
            if any(f"{hyp}|{m}|{s}" in out["unavailable"] or f"{hyp}|{m}|{s}" in out["unvalidated"]
                   for m in modes for s in STRATA):
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


def decision_inputs(crit, acc):
    """The UNAVAILABILITY ADAPTER (#68 round 4 P3; round 5 P3: per claim): H-F DETECTION (c_F and its
    validation) is independent of the nested exceeding-material claim (c_M and its validation, which also
    needs detection), so an F3-only cap leaves detection available; H-T (c_T). A None never reaches a numeric
    API: the claim is unavailable and its p enters Holm as 1."""
    out = {}
    acc = acc or {}
    if "H-F" in crit.get("manifest", {}):
        for claim, keys, passes in (("H-F detection", ("c_F",), ("H-F detection",)),
                                    ("H-F material", ("c_F", "c_M"), ("H-F detection", "H-F material"))):
            cs = {k: crit.get(k) for k in keys}
            missing = [k for k, v in cs.items() if v is None]
            failed = [p for p in passes if acc.get("pass", {}).get(p) is not True]
            out[claim] = {"critical": cs, "available": not missing and not failed,
                          "reason": None if not missing and not failed else
                          f"unavailable: {missing or ''} {failed or ''} (p = 1 in Holm)".strip()}
    if "H-T" in crit.get("manifest", {}):
        missing = [] if crit.get("c_T") is not None else ["c_T"]
        failed = [] if acc.get("pass", {}).get("H-T") is True else ["H-T"]
        out["H-T"] = {"critical": {"c_T": crit.get("c_T")}, "available": not missing and not failed,
                      "reason": None if not missing and not failed else f"unavailable: {missing} {failed} (p = 1 in Holm)"}
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


def report(records):
    """The D2 report per hyp x stage x mode x graph, per quota cell and per T4 subtype / TA direction
    (#68 round 4 P3): proposals by class and role, the audit's classes and q-hats, cells at their cap short of
    B, numerical failures, world-level clips, requested vs achieved for every constraint (the largest
    deviation, clipped counts, the shortfall distribution), "max" edges, the boundary solve, the boundary
    residuals (noise-free and final), membership, CPU over EVERY proposal (discarded ones included), and the
    registered rules."""
    groups = {}
    for r in records:
        key = f"{r.get('hyp')}|{r.get('stage')}|{r.get('mode')}|{r.get('stratum')}"
        groups.setdefault(key, []).append(r)
        if r.get("cell") not in (None, "all"):
            groups.setdefault(f"{key}|cell:{r['cell']}", []).append(r)
        if r.get("direction"):
            groups.setdefault(f"{key}|{r['direction']}", []).append(r)
    fitted = {bool((r.get("manifest") or {}).get("params_fitted")) for r in records}
    out = {"material_spec": stats.material.specification(), "rules": {"K_c": "ROUNDS x n_c per quota cell", "ROUNDS": ROUNDS, "N_MIN": N_MIN, "n_I": "n (per cell n_c)",
                     "BOUNDARY_TOL": BOUNDARY_TOL, "TAU_NUM": TAU_NUM, "AMP_TOL": AMP_TOL, "DIR_TOL": DIR_TOL,
                     "A_SUP": A_SUP, "AMP_GRID": AMP_GRID, "KNOB_GRID": [KNOB_GRID[0], KNOB_GRID[-1], len(KNOB_GRID)],
                     "LAMBDA_GRID": [LAMBDA_GRID[0], LAMBDA_GRID[-1], len(LAMBDA_GRID)], "LAMBDA_TOL": LAMBDA_TOL,
                     "streams": "audit: the slot's original AnnexH/1/<hyp>/<stage>:<graph>/<mode>/<slot>/...; "
                                "continuation: .../<mode>/<cell>/<k>/...",
                     "stopping": "after the audit while B_c < n_c or (I collection and I_c < n_c), up to K_c; I "
                                 "collection iff the audit I-eligible fraction x ROUNDS n >= N_MIN",
                     "classes": "feasible / unreached on the registered search / bounded-mean infeasible (empty: "
                                "no analytic bound) / numerical failure"},
           "note": None if fitted == {True} else ("q-hat from synthetic placeholder parameters: illustrative only; "
                                                  "the binding q-hat is the production run's"),
           "groups": {}}
    for key, rs in sorted(groups.items()):
        clips = [c for r in rs for c in r.get("clips", [])]
        rms = [c["shortfall"] / abs(c["target"]) for c in clips if c.get("shortfall") is not None
               and c["readout"] in ("C", "Q", "E_C", "E_Q") and c["target"]]
        slo = [c["shortfall"] for c in clips if c.get("shortfall") is not None and c["readout"].startswith("beta")]
        nb = [r["membership"]["boundary"] for r in rs if (r.get("membership") or {}).get("boundary")]
        fb = [r["boundary_final"] for r in rs if r.get("boundary_final")]
        mem = [r for r in rs if r.get("member") is not None]
        tg = {}
        for r in rs:
            for k, v in (r.get("targets") or {}).items():
                d = tg.setdefault(k, {"requested": [], "n": 0, "clipped": 0, "max_abs_dev": 0.0,
                                      "achieved_min": None, "achieved_max": None})
                d["requested"] = sorted(set(map(str, d["requested"])) | set(map(str, v["requested"])))
                d["n"] += v["n"]
                d["clipped"] += v["clipped"]
                d["max_abs_dev"] = max(d["max_abs_dev"], v["max_abs_dev"])
                for key_, fn_ in (("achieved_min", min), ("achieved_max", max)):     # (#68 round 5 P3)
                    if v.get(key_) is not None:
                        d[key_] = v[key_] if d[key_] is None else fn_(d[key_], v[key_])
        aud = [r for r in rs if r.get("cell") is not None and r.get("k") is not None
               and r.get("stream") is None and r.get("stage") in ("dev", "val")]
        g = {"counts": proposal_counts(rs), "audit": audit_classes(aud) if aud else None,
             "capped_cells": capped_cells(rs),
             "clips": {"proposals_clipped": sum(1 for r in rs if r.get("clips")), "world_readouts": len(clips),
                       "kinds": {k: sum(1 for c in clips if c.get("kind") == k)
                                 for k in ("unreached-above", "unreached-below", "jump")},
                       "rms_shortfall_relative": _dist(rms), "slope_shortfall": _dist(slo)},
             "targets": tg,
             "maxima_at_edge": sum(int((r.get("maxima") or {}).get("at_edge", 0)) for r in rs),
             "boundary_solve": {"outcomes": {o: sum(1 for r in rs if (r.get("boundary_solve") or {}).get("outcome") == o)
                                             for o in ("feasible", "unreached")},
                                "lambda": _dist([r["boundary_solve"]["lambda"] for r in rs if r.get("boundary_solve")]),
                                "evals": _dist([r["boundary_solve"]["evals"] for r in rs if r.get("boundary_solve")])},
             "boundary_noise_free": {"n": len(nb), "ok": sum(1 for b in nb if b["ok"]),
                                     "residual": _dist([b["residual"] for b in nb if math.isfinite(b["residual"])])},
             "boundary_final": {"n": len(fb), "ok": sum(1 for b in fb if b.get("ok")),
                                "errors": sum(1 for b in fb if "error" in b),
                                "metric_induced_change": _dist([b["residual"] for b in fb if "residual" in b
                                                                and math.isfinite(b["residual"])])},
             "membership": {"members": sum(1 for r in mem if r["member"]), "non_members": sum(1 for r in mem if not r["member"]),
                            "strongest_candidates": {c: sum(1 for r in mem if not r["member"]
                                                            and r["membership"].get("strongest") == c)
                                                     for c in sorted({r["membership"].get("strongest") for r in mem
                                                                      if not r["member"] and r["membership"].get("strongest")})}}}
        out["groups"][key] = g
    return out


def capped_cells(rs):
    """The quota cells of one stage x mode x graph whose streams reached their cap K_c short of B."""
    out = []
    for c in sorted({r["cell"] for r in rs if r.get("cell") is not None and r.get("stage") in ("dev", "val")}):
        cx = [r for r in rs if r.get("cell") == c]
        n_c = len(cells_of(cx[0]["hyp"], cx[0]["mode"], {"dev": N_DEV, "val": N_VAL}[cx[0]["stage"]])[c])
        if len(cx) >= ROUNDS * n_c and sum(r.get("role") == "B" for r in cx) < n_c:
            out.append(c)
    return out


def ledger_add(path, entry):
    """Append one CPU entry to the cumulative ledger (#68 round 4 P3)."""
    if path:
        with open(path, "a") as f:
            f.write(json.dumps(dict(entry, utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())), sort_keys=True) + "\n")


def ledger_total(paths):
    """The cumulative CPU ledger against the H.12 ceiling (stats.CPU_CEILING_H = 240 CPU-h, amendment D5): every entry (panels, benches, shards,
    repairs, reruns; fitting and anything else added with `ledger --add`)."""
    ent = read_records(paths)
    by = {}
    for e in ent:
        by[e.get("kind", "?")] = by.get(e.get("kind", "?"), 0.0) + float(e.get("cpu_s", 0.0))
    tot = sum(by.values())
    return {"entries": len(ent), "cpu_h": tot / 3600, "by_kind_h": {k: v / 3600 for k, v in sorted(by.items())},
            "ceiling_h": stats.CPU_CEILING_H, "remaining_h": stats.CPU_CEILING_H - tot / 3600}


# ================================================================== CLI
def read_records(paths):
    out = []
    for p in paths:
        with open(p) as f:
            out.extend(json.loads(ln) for ln in f if ln.strip())
    return out


GRAPH_TIMES = tuple(range(201))          # (graph.TIMES: every graph time, 0..200M)


def registered_fine(intensive=False, lag=None):
    """graph.build's registered FINE within-world pairs of a C world beyond its coarse grid (Codex #68 D6 r2 P2-3)
    -> {(prey time, predator time)} in calib's times (0 -> 1e-6): in every fine window (graph.WINDOWS) each time
    with each registered offset (graph.OFFSETS) inside the window; an INTENSIVE world's complete window grids; a
    non-intensive world's lag probe (the coarse prey times at +-lag, when the graph registers one)."""
    req = set()
    for lo, hi in graphlib.WINDOWS:
        for s in range(lo, hi + 1):
            req |= {(s, s + o) for o in graphlib.OFFSETS if lo <= s + o <= hi}
            if intensive:
                req |= {(s, t) for t in range(lo, hi + 1)}
    if lag and not intensive:
        req |= {(s, s + d) for s in range(0, 201, 5) for d in (lag, -lag) if 0 <= s + d <= 200}
    req -= {(a, b) for a in range(0, 201, 5) for b in range(0, 201, 5)}

    def tt(x):
        return 1e-6 if x == 0 else float(x)
    return {(tt(a), tt(b)) for a, b in req}


def panel_problems(g, intensive=False, lag=None):
    """The REQUIRED panel coverage of one qualifying world (Codex #68 D6 P2-3 and r2; graph.py's design): the
    complete coarse 41 x 41 within-world grid, its registered FINE within-world pairs (registered_fine: the fine
    windows, an intensive world's complete window grids, the lag probe), and its four predator-reference (RQ) and
    four prey-reference (RP) series, each at EVERY graph time (graph.TIMES, 0..200M) -> [problem]."""
    probs = [] if g.coarse else ["its coarse 41 x 41 within-world grid is incomplete"]
    miss = registered_fine(intensive, lag) - set(zip(g.ti.tolist(), g.tj.tolist()))
    if miss:
        a, b = min(miss)
        probs.append(f"its {'intensive ' if intensive else ''}fine within-world panel misses {len(miss)} registered "
                     f"pair(s) (e.g. {a:g}M -> {b:g}M)")
    full = {1e-6 if t == 0 else float(t) for t in GRAPH_TIMES}
    for what, T, R in (("predator-reference (RQ)", g.cT, g.cR), ("prey-reference (RP)", g.qT, g.qR)):
        refs = sorted(set(R.tolist()), key=str)
        if len(refs) != 4:
            probs.append(f"{len(refs)} {what} series, not 4")
        for r in refs:
            miss = full - {float(t) for t, x in zip(T.tolist(), R.tolist()) if x == r}
            if miss:
                probs.append(f"its {what} series {r} misses {len(miss)} graph time(s) (e.g. {min(miss):g}M)")
    return probs


def eligible_graph(path, elig_path, hyp):
    """The ACTUAL QUALIFYING C graph (Annex H D6 §§9.1-9.4; stats.eligibility's record) for hyp (H-F or H-T): the
    dispatcher must have made hyp AVAILABLE (its own flag: |Q200| >= 24 AND no technical gap pending repair; never
    a smaller-n substitute), the record's bound mask must be THIS graph's (graphmask/2 graph.edges_sha256 against
    the graph's edges; its meta, beside it, those edges' and that namespace's: the intensive worlds re-derived by
    graph.splits), and every world of hyp's population (the common Q200) must carry its REQUIRED panels in the
    graph (panel_problems: coarse, fine, intensive and lag-probe within pairs, the reference series) -> (the graph
    restricted to that population, its source: the graph file's and the
    eligibility record's sha256). The stress24 stratum is drawn from it (stratum_worlds). Codex #68 D6 P2-3."""
    with open(elig_path, "rb") as f:
        raw = f.read()
    rec = json.loads(raw.decode("utf-8"))
    if rec.get("schema") != stats.ELIGIBILITY_SCHEMA:
        raise CalibError(f"{elig_path}: not an eligibility record ({stats.ELIGIBILITY_SCHEMA})")
    h = (rec.get("hypotheses") or {}).get(hyp) or {}
    if h.get("available") is not True:
        raise CalibError(f"{hyp} is unavailable under the eligibility record ({h.get('reason') or 'no entry'}): no "
                         "calibration (no smaller-n confirmatory calibration is substituted; Annex H D6 §§9.1-9.4)")
    q = h.get("worlds") or []
    if h.get("population") != "Q200" or q != (rec.get("Q200") or {}).get("worlds") or len(q) < stats.MIN_Q200:
        raise CalibError(f"{hyp}'s population is not the common Q200 of at least {stats.MIN_Q200} worlds")
    with open(path, "rb") as f:
        graw = f.read()
    gsha, esha = hashlib.sha256(graw).hexdigest(), hashlib.sha256(gzip.decompress(graw)).hexdigest()
    m = rec.get("mask") or {}
    if m.get("graph_edges_sha256") != esha:
        raise CalibError("the eligibility record's bound mask is not this graph's (its graph.edges_sha256 "
                         f"{str(m.get('graph_edges_sha256'))[:16]}, the graph's edges {esha[:16]})")
    try:                                       # (graph.write's meta: the registered design of these edges)
        with open(os.path.join(os.path.dirname(os.path.abspath(path)), "graph.meta.json")) as f:
            meta = json.load(f)
    except (OSError, ValueError) as e:
        raise CalibError(f"the graph's meta (graph.meta.json beside it) is unreadable: {e}") from None
    if meta.get("edges_sha256") != esha or meta.get("namespace") != m.get("graph_namespace"):
        raise CalibError("the graph's meta is not these edges' or not the bound mask's graph (edges_sha256 / "
                         "namespace)")
    try:
        intensive = graphlib.splits(meta["namespace"], meta["worlds"])[2]
    except (graphlib.GraphError, KeyError, TypeError) as e:
        raise CalibError(f"the graph's registered design cannot be re-derived from its meta: {e}") from None
    if sorted(meta.get("intensive") or []) != intensive:
        raise CalibError("the graph's intensive worlds are not its registered design's (graph.splits)")
    g = load_graph(path, q)
    miss = sorted(set(q) - {x.id for x in g})
    if miss:
        raise CalibError(f"{len(miss)} Q200 world(s) without their complete fixed panels in the graph: {miss[:5]}")
    bad = {x.id: p for x in g for p in [panel_problems(x, x.id in intensive, meta.get("lag_probe"))] if p}
    if bad:
        w = sorted(bad)
        raise CalibError(f"{len(w)} Q200 world(s) without their complete fixed panels in the graph: "
                         + "; ".join(f"{x}: {bad[x][0]}" for x in w[:3]))
    return g, f"file:{gsha}+eligibility:{hashlib.sha256(raw).hexdigest()}"


def get_graph(a):
    if a.graph and getattr(a, "eligibility", None):
        return eligible_graph(a.graph, a.eligibility, a.hyp)
    if getattr(a, "eligibility", None):
        raise CalibError("--eligibility needs --graph (the qualifying worlds' assay graph)")
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
        s.add_argument("--eligibility", help="stats.eligibility's record: the graph restricted to the common Q200 "
                                             "(refused below 24; a production calibration requires it)")
        s.add_argument("--synthetic-worlds", type=int, default=32)
        s.add_argument("--params")
        s.add_argument("--noise-source", help="the adopted noisebank.bank/3 artifact named by the parameters' "
                       "fit.noise.source_artifact_sha256 (production panels require it: check_noise_source)")
        s.add_argument("--gates", help="the frozen epoch-gate artifact (calib.py gates) H-T requires")
        s.add_argument("--draws", type=int, default=stats.B_BOOT)
        s.add_argument("--smoke", action="store_true", help="a smoke / test run: synthetic inputs allowed, the "
                       "records marked non-production (crit / accept refuse them)")
        if name == "panels":
            s.add_argument("--stage", choices=("dev", "val", "alt"), required=True)
            s.add_argument("--mode", required=True)
            s.add_argument("--stratum", choices=STRATA, required=True)
            s.add_argument("--phase", choices=("audit", "continue"), default="audit",
                           help="audit: the slots --from..--to (every quota cell's first n_c proposals); continue: "
                                "one cell's stream --kfrom..--kto")
            s.add_argument("--from", dest="lo", type=int, default=0)
            s.add_argument("--to", dest="hi", type=int)
            s.add_argument("--cell")
            s.add_argument("--kfrom", type=int)
            s.add_argument("--kto", type=int)
            s.add_argument("--prior", nargs="*", default=[], help="continue: the audit and earlier records (keeps "
                           "only what the stopping rule needs and stops there; without them every eligible "
                           "proposal is kept)")
            s.add_argument("--out", required=True)
        s.add_argument("--ledger", help="append this run's CPU to the cumulative ledger (JSONL)")
        s.add_argument("--table-cache", help="the on-disk location-table cache shared by shard processes "
                       "(default: $RQ_TABLE_CACHE; none: built per process)")
        if name == "bench":
            s.add_argument("--panels", type=int, default=50)
            s.add_argument("--out")
    for name in ("crit", "accept", "power"):
        s = sub.add_parser(name)
        if name in ("accept", "power"):
            s.add_argument("--crit", required=True)
        s.add_argument("--smoke", action="store_true")
        s.add_argument("files", nargs="+")
    s = sub.add_parser("tables", help="pre-build the location tables a parameter set can reach (once per "
                       "code identity) into --table-cache")
    s.add_argument("--params")
    s.add_argument("--table-cache", required=True)
    s = sub.add_parser("gates")
    s.add_argument("--crit", required=True)
    s.add_argument("--accept", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--smoke", action="store_true")
    s = sub.add_parser("report")
    s.add_argument("files", nargs="+")
    s = sub.add_parser("ledger")
    s.add_argument("files", nargs="+")
    s.add_argument("--add", nargs=2, metavar=("KIND", "CPU_S"), help="append an entry (e.g. fitting 3600) to the "
                   "first file first")
    a = ap.parse_args(argv)
    global TABLE_CACHE
    if getattr(a, "table_cache", None):
        TABLE_CACHE = os.path.abspath(a.table_cache)
    try:
        if a.cmd == "tables":
            c0 = time.process_time()
            span = warm_tables(get_params(a))
            print(json.dumps({"identity": tables_identity(), "cells": {str(law): bounds for law, bounds in span.items()}, "cpu_s": round(time.process_time() - c0, 1)}))
            return 0
        if a.cmd in ("panels", "bench"):
            if a.cmd == "panels" and not a.smoke and not a.eligibility:     # (Codex #68 D6 P3: before any panel)
                raise CalibError("production panels need --eligibility (stats.eligibility's record: the graph "
                                 "restricted to the common Q200; --smoke for a test run)")
            graph, src = get_graph(a)
            params = get_params(a)
            production = a.cmd == "panels" and not a.smoke
            check_params(params, production=production)
            # (#68 round 14, spec v2: the noise block's source, verbatim. The bank bytes are bound in every record's
            # manifest through params_sha256, which covers fit.noise.source_artifact_sha256 = sha256 of these bytes.)
            if production and not a.noise_source:
                raise CalibError("production panels need --noise-source (the adopted noisebank.bank/3 artifact "
                                 "named by fit.noise.source_artifact_sha256)")
            if a.noise_source:
                with open(a.noise_source, "rb") as f:
                    check_noise_source(params, f.read())
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
                c0 = time.process_time()
                todo = []                                     # [(panel, cell, k, stream)]
                if a.phase == "audit":
                    hi = n_reg if a.hi is None else a.hi
                    if not 0 <= a.lo <= hi <= n_reg:
                        raise CalibError(f"slots {a.lo}..{hi} outside the registered 0..{n_reg}")
                    cells = cells_of(a.hyp, a.mode, n_reg) if a.stage != "alt" else {}
                    for j in range(a.lo, hi):
                        if a.stage == "alt":
                            todo.append((j, None, None, None))
                        else:
                            c = quota_cell(a.hyp, a.mode, j)
                            todo.append((j, c, cells[c].index(j), None))
                    keep, st_ = None, None
                else:
                    if a.stage == "alt":
                        raise CalibError("alternatives have no continuation (the registered 100 panels)")
                    cells = cells_of(a.hyp, a.mode, n_reg)
                    if a.cell not in cells or a.kfrom is None or a.kto is None:
                        raise CalibError(f"continue needs --cell (one of {sorted(cells)[:4]}...) --kfrom --kto")
                    n_c = len(cells[a.cell])
                    lo, hi = max(a.kfrom, n_c), min(a.kto, ROUNDS * n_c)
                    keep, st_ = None, None
                    if a.prior:
                        prior = [r for r in read_records(a.prior) if r.get("hyp") == a.hyp and r.get("stage") == a.stage
                                 and r.get("mode") == a.mode and r.get("stratum") == a.stratum]
                        aud = [r for r in prior if r.get("cell") in cells and r.get("k") is not None
                               and r["k"] < len(cells[r["cell"]])]
                        if len(aud) != n_reg:
                            raise CalibError(f"--prior holds {len(aud)} of the {n_reg} audit proposals")
                        mine = sorted((r for r in prior if r.get("cell") == a.cell and r["k"] < lo), key=lambda r: r["k"])
                        if [r["k"] for r in mine] != list(range(lo)):
                            raise CalibError(f"--prior must hold the cell's proposals 0..{lo - 1}")
                        st_ = {"b": sum(r.get("role") == "B" for r in mine), "i": sum(r.get("role") == "I" for r in mine),
                               "collect": collect_I(aud, n_reg, a.stage), "n_c": n_c}

                        def keep(rec, st_=st_):
                            return st_["b"] < st_["n_c"] if rec["eligible"] == "B" else st_["i"] < st_["n_c"]
                    todo = [(*proposal_of(a.hyp, a.mode, n_reg, a.cell, k)[:1], a.cell, k,
                             proposal_of(a.hyp, a.mode, n_reg, a.cell, k)[1]) for k in range(lo, hi)]
                with open(a.out, "a") as f:
                    for panel, c, k, stream in todo:
                        if a.phase == "continue" and st_ is not None and st_["b"] >= st_["n_c"] and \
                                (not st_["collect"] or st_["i"] >= st_["n_c"]):
                            break                             # (the registered stopping point)
                        r = run_panel(graph, params, a.hyp, a.stage, a.stratum, a.mode, panel, gates, a.draws, man,
                                      cell=c, k=k, stream=stream, keep=keep)
                        if st_ is not None:
                            st_["b"] += r.get("role") == "B"
                            st_["i"] += r.get("role") == "I"
                        f.write(json.dumps(r, sort_keys=True) + "\n")
                        f.flush()
                ledger_add(a.ledger, {"kind": "panels", "hyp": a.hyp, "stage": a.stage, "mode": a.mode,
                                      "stratum": a.stratum, "phase": a.phase, "records": len(todo),
                                      "cpu_s": time.process_time() - c0})
                return 0
            c0 = time.process_time()
            recs = []
            for n in range(a.panels):
                m, s, k = nth_dev_panel(a.hyp, n)
                c = quota_cell(a.hyp, m, k)
                r = run_panel(graph, params, a.hyp, "dev", s, m, k, gates, a.draws, man, cell=c,
                              k=cells_of(a.hyp, m, N_DEV)[c].index(k))
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
            ledger_add(a.ledger, {"kind": "bench", "hyp": a.hyp, "records": len(recs), "cpu_s": time.process_time() - c0})
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
        if a.cmd == "ledger":
            if a.add:
                ledger_add(a.files[0], {"kind": a.add[0], "cpu_s": float(a.add[1])})
            print(json.dumps(ledger_total(a.files), indent=1, sort_keys=True))
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

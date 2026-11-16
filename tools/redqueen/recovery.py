#!/usr/bin/env python3
"""recovery.py: the exact-graph recovery simulation of design v4 §6.5, with a minimal map fitter.

    recovery.py run --graph G/graph.jsonl.gz --out DIR [--set main|stress|numerical|all]
                    [--reps 20] [--jobs 2] [--fitter minimal|registered] [--ranks 4] [--lambdas L,..]
                    [--options a,..] [--iters N] [--start both|warm|cold] [--basis 6] [--embedding shared]
    recovery.py one --graph G/graph.jsonl.gz --scenario NAME --rep N --out FILE.json [...]
    recovery.py summarize --dir DIR [--out summary.json]
    recovery.py conditioning --graph G/graph.jsonl.gz [--out conditioning.json]
    recovery.py bench --graph G/graph.jsonl.gz
  run / one also take --obs-model planning|bank (default planning) and, in bank mode only, --bank BANK_D8.json
  --obs-tables OBS_TABLES.npz [--allow-synthetic-bank] (OBSERVATION MODES below). Bank mode also has:
    recovery.py obs-tables --bank BANK_D8.json --noise-scales 1,2 --out OBS_TABLES.npz [--allow-synthetic-bank]
    recovery.py pairing --dirs D1,D2,... [--out pairing.json]
    recovery.py packet --mode acceptance|diagnostic --schedule SCHEDULE.json --out PACKET.json [--allow-synthetic-bank]

OBSERVATION MODES (Red Queen recovery option A, A_design_v5.md sections 1, 3.1-3.8, 4; its clarifications 1-3).
  planning (the default; main's model, byte for byte: the scenario's planning noise below, the binomial counts and
      the Binomial(600) survival layer). LABELLED NON-ACCEPTING: configurations, results and summaries carry
      noise_source "scenario_planning_only" and accepting false, a summary states "PLANNING NOISE: NOT GATE-2
      EVIDENCE", and pairing / packet refuse planning input (v5 3.7).
  bank (v5 1): the SAME scenario truth (the prefix of the streams default_rng(seed) and default_rng([seed, 2]):
      scenario_truth, survival_truth), observed under the bank/D8 law from the frozen bank/3 artifact and its
      observation tables (obslaw.BankObservationModel, validated at every load, v5 4.2): joint row / donor / cell
      latents (PSD factors), the capped 600-scaled survival law with M_5000 = 247 from #90's clock, bounded survival
      heads c_H sigma(eta), one free control per prey node and replicate, no binomial or Poisson layer, from the
      observation stream default_rng([seed, 3]) (observe_bank). The scenario's noise_scale gamma multiplies the bank's
      latent scales (locations re-solved); the planning noise parameters are ignored (settings record noise_model
      "bank") and the *_cap / *_cap15 scenarios are refused (BANK_REFUSED), as is a configuration whose ceiling M_H
      is 0. The registered map receives the bank's working variance W, its nu0 prior and its latent score law, all
      three through any_fit (the single choke point) for a weighted fit of a dataset with counts, none of them
      otherwise (numerical fits): never the scenario settings or another truth-only field (v5 1.8). Every result
      records noise_source "bank_d8", accepting, observation_model_sha256, noiseless and the observations' hashes
      (observation_hashes; a noiseless dataset's absent counts are the explicit record {"absent": "noiseless"}).
  obs-tables builds and verifies the location tables and the fitter table once (v5 1.7, 1.7b) and publishes them
  with no replacement; pairing refuses a directory that is not bank mode (before reading any result) and directories
  whose shared (scenario, rep) observations differ (v5 3.6, 3.7); packet evaluates the acceptance packet from a frozen
  schedule (v5 3.8; the schedule document of clarification 4 F1: --mode acceptance refuses, before any check, an
  incomplete schedule, directories whose bound settings do not satisfy CRITERION C2's matrix, or a synthetic bank;
  --mode diagnostic evaluates what is scheduled and can never report acceptance).

Needs numpy (RQ_PYLIB, when set, is put on sys.path first: an unpacked wheel on a host without pip).
`run` starts `one` jobs as subprocesses (never multiprocessing), each with one BLAS thread, and
skips datasets already written (resumable: every kept result is checked against its filename, its
derived seed and the run's configuration first; Codex #66 r1 P2-9).

DEFAULTS PER FITTER (FITTER_DEFAULTS; Codex #66 r1 P2-7): minimal: --options a,b,base --lambdas
0.02,0.1,0.5 --iters 40; registered: --options a --lambdas REGISTERED_LAMBDAS (0.01,0.02,0.05,0.2)
--iters 30 --start both --basis 6 --embedding shared. Incompatible choices (option b or --ab-cap with
the registered map; --start / --basis / --embedding / --center with the minimal fitter) are refused
before any worker starts.

THE SCORE (v4 §7.6; Codex #66 r1 P1-3): every candidate is scored by the registered CAPTURE-COUNT log
predictive density per replicate observation (map.count_lpd: the bounded rounded logit-normal of Annex
H.9.2 at the fit's predictive location and latent variance, map.pred_var; the minimal fitter: its
training residual variance). Validation selection and the test decision use it; the Gaussian working
density at the empirical logits (the reg1-reg5 score) is kept per candidate as a labelled diagnostic
(*_gauss). A decision needs at least two contributing test-root worlds (D6 rule 27), else it is
recorded unavailable; so is a comparison (the selection, the test, the snapshot, the forward tests) that contains a
finite but UNRESOLVED count score (map.pred_count_lpd's grid_unresolved; Codex #66 r5 P2-1): both models'
integration diagnostics are kept beside it and it never silently decides.

THE QUESTION (v4 §6.5, the review's must-fix 1): on the exact post-split graph (graph.py), with
shared row / column / cell noise, is rank > 0 specificity recoverable by the registered selection
and prediction procedure? Compared on the same simulated datasets:
  a     v4: the global families' training and support pairs, with the four training-only matchings;
  b     the same without the new matchings, plus the training within-world pairs in the fit with an
        own-world lag layer (shared lag function, shrunk world deviations): the review's option (b);
  base  neither (the v3 graph after the splits).

TRUTH (per dataset). Every population snapshot has an escalating quality (a per-world random walk
around a common rise; prey b, predators a; references: sentinel snapshots at the candidate times)
and, for rank r > 0, an r-dimensional strategy embedding (u for prey, v for predators) that drifts
along each world's history ("clustered": strategies jump between four types), centred on the eight
references of the opposite guild (v4 §6.3). The capture predictor is
    eta = mu0 + a_j - b_i [- kappa a_j b_i: "twoway"] + c u_i.v_j [+ own-world lag on within pairs]
with c set so the interaction's energy left after an additive (rank-0) refit is the given fraction
of the signal's (1.7% or 3.4%, v4 §6.5). Each of R = 6 replicates adds prey-row and predator-column
noise shared across the replicate's pairs (the global seeds) and cell noise on the logit scale; the
capture fraction is the logistic ("asym": bounded in [0.03, 0.80], saturation) and the count is
Binomial(B = 324) (planning mode; bank mode: OBSERVATION MODES above). The data are the empirical logits.

THE FITTER (minimal; the production map, item 7, replaces it). Ridge alternating least squares of
    z = mu + a_j - b_i + u_i.v_j [+ h(lag) + h_w(lag) on within pairs, option b]
on the replicate means of the fitting pairs, ranks 0..--ranks, penalty on u, v from --lambdas.
Held-out populations are placed only by their support pairs. The procedure: every candidate's
validation score (THE SCORE above, on the validation pairs that are not support; equal
validation-world weights) selects rank and penalty; the selected map and the rank-0 baseline then
score the world-transfer test pairs (non-support test pairs of the global families with an endpoint
in a test world); success = a selected rank > 0 and the 95% lower bound of the crossed source-world
bootstrap of the mean score improvement > 0 (v4 §7.6). The 80/10/10 interpolation is not part of
this fit (a separate secondary fit). The forward-time fit (option fwd) reads the predator-free
controls of prey at <= 120M only (map.control_access).

SETS. main: rank 0, rank 1 and rank 2 at 1.7% and 3.4% (--reps each; v4 proposes 20: 100 noisy
datasets). stress (--reps // 2 each): saturation (asym), a two-way monotone surface (a misfit for
this additive-baseline fitter: the registered 6 x 6 monotone tensor baseline exists for it),
clustered strategies, a strong own-world lag, doubled noise (also at 1.7%). The noise magnitudes
(row 0.15, column 0.15, cell 0.20 on the logit scale, plus the binomial) are planning values until
the independent noise bank (v4 §7.4) measures them (planning mode; bank mode takes them from the bank, and a
scenario's noise multiplier scales the bank's latent scales). power (--reps // 2 each): the noise tripled and
quadrupled at 3.4% and 1.7% (and rank 0 at triple noise), where the options can differ.
capture-level noise (the measured 5k assay noise, predC/noise5k variant 2; scenarios *_cap and *_cap15
for r0, r0_twoway, r1_017, r2_017, r2_034): the per-replicate logit SD, binomial included, is 0.6 at a
capture fraction <= 0.25, linear to 0.15 at >= 0.45 (CAPTURE_SD), the row / column / cell structure kept;
_cap15 is x1.5 (the age-permutation component was not measured: a lower bound).
numerical: noiseless data at ranks 1-4, fitted at the true rank with a penalty continuation (relative
test RMSE: the graph identifies them). --scenarios runs a list instead of a set.

ACCURACY BY TARGET CLASS (every dataset): the selected map's and rank 0's RMSE against the truth on
the world-transfer targets with A/B prey, those with C prey, and the snapshot-test targets
(numerical: the relative RMSE per class). --ab-cap R holds the A/B prey's interaction to rank <= R
in every fit (the comparison's rejected option, kept for the record).

THE SURVIVAL HEAD'S DATA (simulate_survival: its own random stream, so the capture data stay what
they were): logit S_i0 = c_i (one predator-free control per prey snapshot x replicate) and logit
S_ij = c_i - 0.6 (a_j - b_i) - 0.3 [+ u_i' D_S v_j, a full D_S]; the control and the exposed cells
of a prey x replicate share its row noise (the global seeds); survivors ~ Binomial(600) (planning mode; bank
mode: the capped law at the bounded heads c_H sigma(.), above). The minimal fitter ignores them; --fitter
registered (map.py, item 7) fits both heads jointly.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
import numpy as np  # noqa: E402

import graph as graphlib  # noqa: E402
import rqlib  # noqa: E402

RESULT_SCHEMA = "finfolk.redqueen.recovery/1"
R_REPS = 6
B_COUNT = 324                     # K [1 + floor(80 s / 1.5 s)]: the 1.5 s cooldown's capture bound
FAMS = list(graphlib.FAMILIES)
ROLES = ["training", "validation", "test", "support"]
OPTIONS = ("a", "b", "base")
REF_TIMES = (0, 20, 60, 100, 120, 140, 180, 200)   # (ASSUMED slot times: planning only, before references exist)
REFS_SCHEMA = "finfolk.redqueen.references/1"


def reference_times(path):
    """The ACTUAL reference frames per guild and slot from a references/1 document (refsel.py's selection;
    Codex #71 r1 P2-5): {"RQ": {k: t_M}, "RP": {k: t_M}} (F1 = frame 1 -> 0), with the file's sha256. The
    slot -> time map is the selection's, never the assumed REF_TIMES (several references may share a time, and
    a panel with exactly four early references has its slot 4 late)."""
    doc = rqlib.read_json(path)
    if doc.get("schema") != REFS_SCHEMA:
        raise SystemExit(f"{path}: not a references/1 document")
    out = {"RQ": {}, "RP": {}}
    for slot, v in (doc.get("references") or {}).items():
        g, _, k = slot.partition(":")
        fr = v.get("frame") if isinstance(v, dict) else None
        if g not in out or not k.isdigit() or not isinstance(fr, int) or (fr != 1 and fr % 1_000_000):
            raise SystemExit(f"{path}: {slot} is not a reference slot with a snapshot frame")
        out[g][int(k)] = 0 if fr == 1 else fr // 1_000_000
        if not isinstance(v.get("world"), str):
            raise SystemExit(f"{path}: {slot} needs its sentinel world")
    for g in ("RQ", "RP"):
        if sorted(out[g]) != list(range(8)):
            raise SystemExit(f"{path}: {g} needs exactly the slots 0..7")
    out["sentinels"] = {g: {int(s_.partition(":")[2]): v["world"] for s_, v in doc["references"].items()
                            if s_.partition(":")[0] == g} for g in ("RQ", "RP")}
    return out, rqlib.sha256_file(path)
LAG_EDGES = (-200, -50, -20, -10, -5, -3, -2, -1, 0, 1, 2, 3, 5, 10, 20, 50, 201)

SC0 = {"r0": dict(rank=0), "r0_twoway": dict(rank=0, kappa=0.25), "r1_017": dict(rank=1, energy=0.017),
       "r2_017": dict(rank=2, energy=0.017), "r2_034": dict(rank=2, energy=0.034)}
CAP_SET = ("r0", "r0_twoway", "r1_017", "r2_017", "r2_034")
# per-replicate logit SD at 5k against the capture fraction C/B (noise5k REPORT.md, variant 2: 0.47-0.79
# at C/B 0.23-0.31, 0.10-0.24 at C/B >= 0.42): 0.6 at <= 0.25, linear to 0.15 at >= 0.45; it INCLUDES the
# binomial count noise (the simulated Gaussian part is the remainder, at least 0.05). Not measured: the
# reference-age permutation (a lower bound: hence the x1.5 case)
CAPTURE_SD = ((0.25, 0.6), (0.45, 0.15))
SCENARIOS = {
    "r0": dict(rank=0), "r1_017": dict(rank=1, energy=0.017), "r1_034": dict(rank=1, energy=0.034),
    "r2_017": dict(rank=2, energy=0.017), "r2_034": dict(rank=2, energy=0.034),
    "r0_asym": dict(rank=0, link="asym"), "r2_034_asym": dict(rank=2, energy=0.034, link="asym"),
    "r0_twoway": dict(rank=0, kappa=0.25), "r2_034_clustered": dict(rank=2, energy=0.034, clustered=True),
    "r0_ownworld": dict(rank=0, own=-0.6), "r2_034_noisy": dict(rank=2, energy=0.034, noise_scale=2.0),
    "r1_017_noisy": dict(rank=1, energy=0.017, noise_scale=2.0),
    "r2_017_noisy": dict(rank=2, energy=0.017, noise_scale=2.0),
    "r0_x3": dict(rank=0, noise_scale=3.0), "r1_017_x3": dict(rank=1, energy=0.017, noise_scale=3.0),
    "r2_017_x3": dict(rank=2, energy=0.017, noise_scale=3.0), "r1_017_x4": dict(rank=1, energy=0.017, noise_scale=4.0),
    "r2_017_x4": dict(rank=2, energy=0.017, noise_scale=4.0),
    "r1_034_x3": dict(rank=1, energy=0.034, noise_scale=3.0), "r2_034_x3": dict(rank=2, energy=0.034, noise_scale=3.0),
    "r1_034_x4": dict(rank=1, energy=0.034, noise_scale=4.0), "r2_034_x4": dict(rank=2, energy=0.034, noise_scale=4.0),
    # the measured 5k noise (predC/noise5k, v4-like variant 2: the donor draw varies per replicate): the
    # per-replicate logit SD depends on the capture level (CAPTURE_SD), x1.5 the conservative case
    **{f"{n}_cap": dict(SC0[n], noise_model="capture") for n in CAP_SET},
    **{f"{n}_cap15": dict(SC0[n], noise_model="capture", noise_scale=1.5) for n in CAP_SET},
    "num_r1": dict(rank=1, energy=0.034, noiseless=True), "num_r2": dict(rank=2, energy=0.034, noiseless=True),
    "num_r3": dict(rank=3, energy=0.034, noiseless=True), "num_r4": dict(rank=4, energy=0.034, noiseless=True),
}
SETS = {"main": ["r0", "r1_017", "r1_034", "r2_017", "r2_034"],
        "stress": ["r0_asym", "r2_034_asym", "r0_twoway", "r2_034_clustered", "r0_ownworld", "r2_034_noisy",
                   "r1_017_noisy", "r2_017_noisy"],
        "numerical": ["num_r1", "num_r2", "num_r3", "num_r4"],
        "power": ["r0_x3", "r1_034_x3", "r2_034_x3", "r1_034_x4", "r2_034_x4",
                  "r1_017_x3", "r2_017_x3", "r1_017_x4", "r2_017_x4"]}
DEFAULTS = dict(rank=0, energy=0.0, link="logit", kappa=0.0, clustered=False, own=-0.25, noise_scale=1.0,
                noiseless=False, mu0=-0.5, rise=1.5, rw_end=0.5, snap_sd=0.1,
                noise_row=0.15, noise_col=0.15, noise_cell=0.20, noise_model="flat")
SETS_CAP = [f"{n}_cap" for n in CAP_SET] + [f"{n}_cap15" for n in CAP_SET]

# ------------------------------------------------------------------ observation modes (A_design_v5.md 1, 3.2, 3.7, 4.1)
OBS_MODELS = ("planning", "bank")
NOISE_SOURCE = {"planning": "scenario_planning_only", "bank": "bank_d8"}
BANK_REFUSED = frozenset(SETS_CAP)       # (the *_cap / *_cap15 planning approximations of the bank: refused, PC-4)
PLANNING_LABEL = "PLANNING NOISE: NOT GATE-2 EVIDENCE"
BANK_SCOPE = "bank/D8-calibrated observation model (A_design_v5.md)"
D9_SHA256 = "6bff81343ae0b58175c6cf36b5ad0ee0a9d92157d62cd570318796ee3a0c0636"   # amendment D9 (A_design_v5 0.1, 4.1)
STREAMS = {"truth": "default_rng(seed)", "survival_truth": "default_rng([seed,2])",
           "observations": "default_rng([seed,3])"}                              # (v5 4.1: what bank mode draws from)
OBS_KEYS = ("eta", "inter", "cnt", "z", "s", "s0")       # observation_hashes' fixed key list (v5 3.2)
BANK_OBS_KEYS = ("mu_C", "mu_S", "mu_F")                 # (+ in bank mode: the intended means, v5 1.8)
ABSENT_CNT = {"absent": "noiseless"}                     # a noiseless dataset's absent counts (v5 1.8, Codex P1)
TRUTH_ONLY = ("eta", "inter", "mu", "loc", "c", "energy", "settings", "cS", "etaS", "DS")   # (v5 1.8: never read by
#                                                          a bank-mode fit, score or selection: T6-9)


def var_model(settings):
    """The registered capture-level variance function of a scenario (the generator's own noise model:
    p -> per-replicate variance of the empirical logit, binomial included); None for noiseless data. PLANNING MODE
    ONLY (it reads the scenario settings): bank mode never calls it (any_fit, A_design_v5 3.2)."""
    s = dict(DEFAULTS, **(settings or {}))
    if s["noiseless"]:
        return None
    if s["noise_model"] == "capture":
        return lambda p: capture_sd(p, s["noise_scale"]) ** 2
    flat = s["noise_scale"] ** 2 * (s["noise_row"] ** 2 + s["noise_col"] ** 2 + s["noise_cell"] ** 2)
    return lambda p: flat + 1.0 / (B_COUNT * np.clip(p, 1e-4, 1 - 1e-4) * (1 - np.clip(p, 1e-4, 1 - 1e-4)))


def capture_sd(p, scale=1.0):
    """The measured per-replicate logit SD at capture fraction p (CAPTURE_SD, flat beyond its ends), x scale."""
    (p0, s0), (p1, s1) = CAPTURE_SD
    return scale * np.interp(p, [p0, p1], [s0, s1])


# ------------------------------------------------------------------ data
class Data:
    """The graph as arrays: prey / predator node indices of every pair, family, role, lags, worlds."""

    def __init__(self, g, refs=None):
        """refs: the ACTUAL reference times per guild and slot (reference_times); None: the assumed REF_TIMES
        (planning before the selection exists, recorded as such)."""
        self.g = g
        self.ref_times = refs
        split, treat = g["split"], {w["id"]: w["treatment"] for w in g["worlds"]}
        self.worlds = sorted(treat)
        widx = {w: i for i, w in enumerate(self.worlds)}
        self.treat = np.array([treat[w] for w in self.worlds])
        self.wsplit = np.array([split[w] for w in self.worlds])
        holdout = {}
        for k, v in g["holdout"].items():
            w, t = k.rsplit(":", 1)
            holdout[(w, int(t))] = v
        qn, pn = {}, {}
        for q, p, *_ in g["edges"]:
            qn.setdefault(q, len(qn))
            pn.setdefault(p, len(pn))

        sents = sorted({x for g in ("RQ", "RP") for x in refs["sentinels"][g].values()}) if refs else None

        def nodes(d):
            w, t, ref, held = np.zeros(len(d), int), np.zeros(len(d), int), np.zeros(len(d), bool), \
                np.zeros(len(d), "<U5")
            sent = np.full(len(d), -1)
            for n, i in d.items():
                gg, ww, tt = graphlib.parse(n)
                if ww is None:
                    w[i], t[i], ref[i], held[i] = -1, (refs[gg][tt] if refs else REF_TIMES[tt]), True, "train"
                    # (#71 r3 P2: the slot's ACTUAL sentinel; planning without references: slot mod 4, assumed)
                    sent[i] = sents.index(refs["sentinels"][gg][tt]) if refs else tt % 4
                else:
                    w[i], t[i] = widx[ww], tt
                    held[i] = split[ww] if split[ww] != "train" else holdout.get((ww, tt), "train")
            return w, t, ref, held, sent
        self.nQ, self.nP = len(qn), len(pn)
        self.qw, self.qt, self.qref, self.qheld, self.qsent = nodes(qn)
        self.pw, self.pt, self.pref, self.pheld, self.psent = nodes(pn)
        self.qkey = {i: n for n, i in qn.items()}
        self.pkey = {i: n for n, i in pn.items()}
        E = len(g["edges"])
        self.qi = np.fromiter((qn[e[0]] for e in g["edges"]), int, E)
        self.pj = np.fromiter((pn[e[1]] for e in g["edges"]), int, E)
        self.fam = np.fromiter((FAMS.index(e[2]) for e in g["edges"]), int, E)
        self.role = np.fromiter((ROLES.index(e[3]) for e in g["edges"]), int, E)
        self.within = np.isin(self.fam, [FAMS.index(f) for f in graphlib.WITHIN])
        lag = self.pt[self.pj] - self.qt[self.qi]
        self.lagbin = np.where(self.within, np.digitize(lag, LAG_EDGES[1:-1]), -1)
        self.nbins = len(LAG_EDGES) - 1
        self.ownw = np.where(self.within, self.qw[self.qi], -1)
        glob = ~self.within
        heldq, heldp = self.qheld[self.qi], self.pheld[self.pj]
        nonsup = self.role != ROLES.index("support")
        # world-transfer test targets, and their test world (prey's if held out at world level)
        qtest = (self.qw[self.qi] >= 0) & (self.wsplit[np.maximum(self.qw[self.qi], 0)] == "test") & ~self.qref[self.qi]
        ptest = (self.pw[self.pj] >= 0) & (self.wsplit[np.maximum(self.pw[self.pj], 0)] == "test") & ~self.pref[self.pj]
        self.test_idx = np.flatnonzero(glob & nonsup & (self.role == ROLES.index("test")) & (qtest | ptest))
        self.test_world = np.where(qtest, self.qw[self.qi], self.pw[self.pj])[self.test_idx]
        self.stest_idx = np.flatnonzero(glob & nonsup & (self.role == ROLES.index("test")) & ~(qtest | ptest))
        val = glob & nonsup & (self.role == ROLES.index("validation"))
        self.val_idx = np.flatnonzero(val)
        qv = np.where(heldq == "val", self.qw[self.qi], -1)
        self.val_world = np.where(qv >= 0, qv, self.pw[self.pj])[self.val_idx]
        fitrole = (self.role == ROLES.index("training")) | (self.role == ROLES.index("support"))
        tm = self.fam == FAMS.index("train_match")
        self.fit = {"a": np.flatnonzero(glob & fitrole),
                    "base": np.flatnonzero(glob & fitrole & ~tm),
                    "b": np.flatnonzero((glob & fitrole & ~tm) | (self.within & (self.role == ROLES.index("training"))))}
        # target classes: world-transfer targets with A/B prey and with C prey; snapshot-test targets
        # both source worlds of every test target (-1: a frozen reference), for the crossed bootstrap
        self.test_qworld = self.qw[self.qi][self.test_idx]
        self.test_pworld = self.pw[self.pj][self.test_idx]
        self.forward = self.forward_sets(glob)
        self.qab = (self.qw >= 0) & np.isin(self.treat[np.maximum(self.qw, 0)], ["A", "B"]) & ~self.qref
        ab = self.qab[self.qi[self.test_idx]]
        self.classes = {"world_test_ab_prey": self.test_idx[ab], "world_test_c_prey": self.test_idx[~ab],
                        "snapshot_test": self.stest_idx}


    def forward_sets(self, glob):
        """The forward-time recovery's sets (v4 §7.3): fit on the training worlds' main outcomes through
        120M (both endpoints, cross-world) plus every world snapshot's reference pairs against references
        at <= 120M only (their placement); validation targets with both endpoints in 141-160M, test
        targets in 181-200M (no window crossing the 20M separations); test split into the forward transfer
        (both endpoints in training worlds) and the intersection (an endpoint in a test world).
        The graph's ACCESS RULES hold alongside the time and world masks (v4 §7.1, the 400 snapshot
        exclusions): the fit takes training and support pairs only (a non-support pair of a snapshot
        held out for validation or test never enters it), and validation never takes a test-role pair
        (a snapshot-test outcome never steers the selection)."""
        QT, PT = self.qt[self.qi], self.pt[self.pj]
        qw, pw = self.qw[self.qi], self.pw[self.pj]
        qr, pr = self.qref[self.qi], self.pref[self.pj]
        split = lambda w: np.where(w >= 0, self.wsplit[np.maximum(w, 0)], "ref")  # noqa: E731
        qs, ps = split(qw), split(pw)
        main = glob & ~qr & ~pr
        oneref = glob & (qr ^ pr)
        reft = np.where(qr, QT, PT)
        both = lambda lo, hi: (QT >= lo) & (QT <= hi) & (PT >= lo) & (PT <= hi)  # noqa: E731
        trainpair = (qs == "train") & (ps == "train")
        fitrole = (self.role == ROLES.index("training")) | (self.role == ROLES.index("support"))
        notest = self.role != ROLES.index("test")
        fit = np.flatnonzero(((main & trainpair & both(0, 120)) | (oneref & (reft <= 120))) & fitrole)
        # the reference support of the forward fit (#71 r1 P2-5), per readout side: every world population's
        # distinct EARLY (<= 120M) reference slots among its fitted reference pairs, at the actual frames
        sup = {}
        er = oneref & (reft <= 120) & fitrole
        wblock = {i: w.get("block") for i, w in enumerate(sorted(self.g["worlds"], key=lambda w: w["id"]))}
        for side, node, slot, isref, nw in (("prey", self.qi, self.pj, pr, self.qw), ("pred", self.pj, self.qi, qr, self.pw)):
            sel = np.flatnonzero(er & isref)
            per = {}
            for n_, k_ in zip(node[sel].tolist(), slot[sel].tolist()):
                per.setdefault(n_, set()).add(k_)
            pops = np.unique(node[np.flatnonzero(glob & isref & ~(qr if side == "prey" else pr))])
            counts = [len(per.get(int(x), ())) for x in pops]
            byb = {}                                   # (#71 r2 P2: per block x readout)
            for x, c in zip(pops.tolist(), counts):
                b = str(wblock.get(int(nw[x])))
                d = byb.setdefault(b, {"populations": 0, "min_early_references": None, "without_early_reference": 0})
                d["populations"] += 1
                d["min_early_references"] = c if d["min_early_references"] is None else min(d["min_early_references"], c)
                d["without_early_reference"] += c == 0
            sup[side] = {"populations": len(counts), "min_early_references": min(counts) if counts else 0,
                         "without_early_reference": sum(1 for c in counts if c == 0), "blocks": byb}
        val = np.flatnonzero(main & ((qs != "test") & (ps != "test")) & both(141, 160) & notest)
        fwd = np.flatnonzero(main & trainpair & both(181, 200))
        inter = np.flatnonzero(main & ((qs == "test") | (ps == "test")) & both(181, 200))
        return {"fit": fit, "val": val, "val_world": np.where(qw[val] >= 0, qw[val], pw[val]),
                "tests": {"forward_transfer": fwd, "intersection": inter},
                "reference_support": dict(sup, times="actual" if self.ref_times else "assumed")}


# ------------------------------------------------------------------ truth
def _walk(rng, n_t, end_sd, dim=None):
    shape = (n_t,) if dim is None else (n_t, dim)
    steps = rng.normal(0.0, end_sd / math.sqrt(n_t), shape)
    steps[0] = 0.0
    return np.cumsum(steps, axis=0)


def _rise(t):
    return np.log1p(np.asarray(t) / 10.0) / math.log1p(20.0)


def simulate(D, sc, seed, obs=None):
    """-> the truth (eta per pair, the interaction) and the data (empirical logits, R per pair). obs None: PLANNING
    mode, main's observation model byte for byte (observe_planning). obs a loaded obslaw.BankObservationModel: BANK
    mode (A_design_v5 1): the same truth (scenario_truth, survival_truth: for one seed bank and planning truths are
    byte-identical), observed by observe_bank; the same keys, plus mu, loc (the truth-only intended means and
    locations), obs (the model: what any_fit routes on) and noise_source, and settings record noise_model "bank".
    Refused in bank mode: a *_cap / *_cap15 (planning noise_model "capture") scenario and a zero ceiling M_H."""
    truth, rng = scenario_truth(D, sc, seed)
    nodes = truth.pop("nodes")
    s = truth["settings"]
    if obs is not None:
        if s["noise_model"] == "capture":
            raise ValueError("bank mode refuses the *_cap / *_cap15 scenarios (planning approximations of the bank; "
                             "A_design_v5 1.5 PC-4)")
        require_survival(obs)
    truth_S, rng2 = survival_truth(D, s, seed, nodes["a"], nodes["b"], nodes["u"], nodes["v"], truth["c"],
                                   nodes["rank"])
    if obs is None:
        ob = observe_planning(D, truth, rng, truth_S, rng2)
    else:
        truth["settings"] = dict(s, noise_model="bank")
        ob = observe_bank(D, truth, truth_S, obs, seed)
    out = {"eta": truth["eta"], "inter": truth["inter"], "z": ob["z"], "zbar": ob["zbar"], "c": truth["c"],
           "energy": truth["energy"], "settings": truth["settings"]}
    if "cnt" in ob:
        out["cnt"] = ob["cnt"]
    out.update({"cS": truth_S["cS"], "etaS": truth_S["etaS"], "DS": truth_S["DS"], "s": ob["s"], "sbar": ob["sbar"],
                "s0": ob["s0"], "s0bar": ob["s0bar"]})
    if obs is not None:
        out["mu"] = ob["mu"]
        if "loc" in ob:
            out["loc"] = ob["loc"]
        out.update(obs=obs, noise_source=NOISE_SOURCE["bank"])
    return out


def require_survival(obs):
    """A_design_v5 1.10: a configuration whose survival horizon has M_H = 0 has no survival information and is refused
    in bank mode (recovery generates the 5k horizon only)."""
    if not obs.M_H:
        raise ValueError(f"bank mode: the survivor ceiling M_H is {obs.M_H!r}: a zero-ceiling configuration has no "
                         "survival information (A_design_v5 1.10): refused")


def scenario_truth(D, sc, seed):
    """The capture truth (A_design_v5 1.2; main's L351-409 and the energy check L440, unchanged): the prefix of the
    stream default_rng(seed) -> (truth {eta, inter, c, energy, settings, nodes: {a, b, u, v, rank}}, rng), rng
    continuing where the truth draws end (planning's capture noise reads on from there). On main every truth draw
    precedes every noise draw, so a planning and a bank dataset of one seed share this truth byte for byte."""
    s = dict(DEFAULTS, **sc)
    rng = np.random.default_rng(seed)
    nW = len(D.worlds)
    T = 201
    qual = {}
    for g in ("Q", "P"):
        lat = np.empty((nW + 4, T))
        for w in range(nW + 4):           # (the last four: the sentinels the references come from)
            tr = D.treat[w] if w < nW else "C"
            rise = s["rise"] * (1.0 if tr == "C" else 0.7 if tr == "A" else 0.85)
            lat[w] = rise * _rise(np.arange(T)) + _walk(rng, T, s["rw_end"])
        qual[g] = lat
    rank = s["rank"]

    def embed():
        if rank == 0:
            return None
        out = np.empty((nW + 4, T, rank))
        if s["clustered"]:
            centres = rng.normal(0.0, 1.5, (4, rank))
            for w in range(nW + 4):
                k = rng.integers(4)
                for t in range(T):
                    if rng.random() < 0.02:
                        k = rng.integers(4)
                    out[w, t] = centres[k]
        else:
            for w in range(nW + 4):
                out[w] = rng.normal(0.0, 1.0, rank) + _walk(rng, T, 1.0, rank)
        return out
    emb = {"Q": embed(), "P": embed()}

    def node_vals(g, wv, tv, ref, sidx):
        sent = np.where(ref, nW + sidx, wv)              # (a reference's history: its ACTUAL sentinel's)
        x = qual[g][sent, tv] + rng.normal(0.0, s["snap_sd"], len(wv))
        e = None
        if rank:
            e = emb[g][sent, tv] + rng.normal(0.0, 0.3, (len(wv), rank))
            e -= e[ref].mean(axis=0)               # centred on the eight references (v4 §6.3)
        return x, e
    b, u = node_vals("Q", D.qw, D.qt, D.qref, D.qsent)
    a, v = node_vals("P", D.pw, D.pt, D.pref, D.psent)
    eta0 = s["mu0"] + a[D.pj] - b[D.qi] - s["kappa"] * a[D.pj] * b[D.qi]
    own = np.zeros(len(D.qi))
    if D.within.any():
        lag = (D.pt[D.pj] - D.qt[D.qi])[D.within]
        wdev = rng.normal(0.0, 0.08, len(D.worlds))
        own[D.within] = (s["own"] + wdev[D.qw[D.qi][D.within]]) * np.exp(-np.abs(lag) / 8.0)
    inter = np.zeros(len(D.qi))
    c = 0.0
    if rank:
        raw = (u[D.qi] * v[D.pj]).sum(axis=1)
        res = raw - additive_projection(D, raw)
        base = eta0 + own
        c = 0.1
        for _ in range(20):                       # c^2 Var(residual) = energy x Var(signal)
            c = math.sqrt(s["energy"] * np.var(base + c * raw) / np.var(res))
        inter = c * raw
    eta = eta0 + own + inter
    energy = float(np.var(c * (inter / c - additive_projection(D, inter / c))) / np.var(eta)) if rank else 0.0
    return {"eta": eta, "inter": inter, "c": c, "energy": energy, "settings": s,
            "nodes": {"a": a, "b": b, "u": u, "v": v, "rank": rank}}, rng


def observe_planning(D, truth, rng, truth_S, rng2):
    """PLANNING observations (main's L410-439 and L463-474, unchanged), continuing the truth streams rng and rng2
    -> {z, zbar, cnt (noisy only), s, sbar, s0, s0bar}: byte-identical to main for every branch (flat, capture-level,
    asym, noiseless, survival; A_design_v5 T6-5)."""
    s, eta = truth["settings"], truth["eta"]
    cnt = None
    if s["noiseless"]:
        z = np.repeat(eta[:, None], R_REPS, axis=1)
    elif s["noise_model"] == "capture":
        # the row / column / cell structure kept, its total per-pair SD set by the pair's capture level:
        # the Gaussian part's SD g = sqrt(capture_sd^2 - binomial variance), at least 0.05
        pt = 1.0 / (1.0 + np.exp(-eta))
        if s["link"] == "asym":
            pt = 0.03 + 0.77 * pt
        flat = math.sqrt(s["noise_row"] ** 2 + s["noise_col"] ** 2 + s["noise_cell"] ** 2)
        g = np.sqrt(np.maximum(capture_sd(pt, s["noise_scale"]) ** 2 - 1.0 / (B_COUNT * pt * (1.0 - pt)), 0.05 ** 2))
        y = eta[:, None] + (g / flat)[:, None] * (
            s["noise_row"] * rng.normal(size=(D.nQ, R_REPS))[D.qi]
            + s["noise_col"] * rng.normal(size=(D.nP, R_REPS))[D.pj]
            + s["noise_cell"] * rng.normal(size=(len(eta), R_REPS)))
        p = 1.0 / (1.0 + np.exp(-y))
        if s["link"] == "asym":
            p = 0.03 + 0.77 * p
        cnt = rng.binomial(B_COUNT, p)
        z = np.log((cnt + 0.5) / (B_COUNT - cnt + 0.5))
    else:
        k = s["noise_scale"]
        y = (eta[:, None] + k * s["noise_row"] * rng.normal(size=(D.nQ, R_REPS))[D.qi]
             + k * s["noise_col"] * rng.normal(size=(D.nP, R_REPS))[D.pj]
             + k * s["noise_cell"] * rng.normal(size=(len(eta), R_REPS)))
        p = 1.0 / (1.0 + np.exp(-y))
        if s["link"] == "asym":
            p = 0.03 + 0.77 * p
        cnt = rng.binomial(B_COUNT, p)
        z = np.log((cnt + 0.5) / (B_COUNT - cnt + 0.5))
    out = {"z": z, "zbar": z.mean(axis=1)}
    if cnt is not None:
        out["cnt"] = cnt.astype(np.int16)         # (the capture counts: the registered count score's data)
    out.update(_survival_planning(D, s, truth_S, rng2))
    return out


N_SURV = 600


def simulate_survival(D, s, seed, a, b, u, v, c, rank):
    """The survival head's truth and data (its own stream: the capture data stay what they were):
    logit S_i0 = c_i (predator-free controls, one per prey snapshot x replicate), logit S_ij =
    c_i - 0.6 (a_j - b_i) - 0.3 + c' u_i' D_S v_j (a full D_S); the prey-row noise of a replicate
    is shared by its control and its exposed cells (the global seeds); survivors ~ Binomial(600). PLANNING mode:
    survival_truth and the planning observation tail (bank mode never reaches that tail)."""
    truth_S, rng = survival_truth(D, s, seed, a, b, u, v, c, rank)
    return dict(truth_S, **_survival_planning(D, s, truth_S, rng))


def survival_truth(D, s, seed, a, b, u, v, c, rank):
    """The survival truth (A_design_v5 1.2; main's L456-462, unchanged): the prefix of default_rng([seed, 2]) ->
    ({cS, etaS, DS}, rng2), rng2 continuing where the truth draws end."""
    rng = np.random.default_rng([seed, 2])
    cS = 1.4 + 0.35 * rng.normal(size=D.nQ)
    etaS = cS[D.qi] - 0.6 * (a[D.pj] - b[D.qi]) - 0.3
    DS = None
    if rank:
        DS = rng.normal(size=(rank, rank)) / math.sqrt(rank)
        etaS = etaS + 0.8 * c * (u[D.qi] * (v[D.pj] @ DS.T)).sum(axis=1)
    return {"cS": cS, "etaS": etaS, "DS": DS}, rng


def _survival_planning(D, s, truth_S, rng):
    """PLANNING survival observations (main's L463-474, unchanged) continuing rng -> {s, sbar, s0, s0bar}."""
    cS, etaS = truth_S["cS"], truth_S["etaS"]
    if s["noiseless"]:
        S = np.repeat(etaS[:, None], R_REPS, axis=1)
        S0 = np.repeat(cS[:, None], R_REPS, axis=1)
    else:
        k = s["noise_scale"]
        row = k * 0.15 * rng.normal(size=(D.nQ, R_REPS))
        y = (etaS[:, None] + row[D.qi] + k * 0.10 * rng.normal(size=(D.nP, R_REPS))[D.pj]
             + k * 0.15 * rng.normal(size=(len(etaS), R_REPS)))
        y0 = cS[:, None] + row + k * 0.15 * rng.normal(size=(D.nQ, R_REPS))
        lg = lambda x: np.log((x + 0.5) / (N_SURV - x + 0.5))  # noqa: E731
        S = lg(rng.binomial(N_SURV, 1.0 / (1.0 + np.exp(-y))))
        S0 = lg(rng.binomial(N_SURV, 1.0 / (1.0 + np.exp(-y0))))
    return {"s": S, "sbar": S.mean(axis=1), "s0": S0, "s0bar": S0.mean(axis=1)}


def observe_bank(D, truth, truth_S, obs, seed):
    """BANK observations of the truths (A_design_v5 1.2-1.8) -> {z, zbar, cnt (noisy only), s, sbar, s0, s0bar, mu
    (+ loc, noisy only)}. Intended means (v5 1.2, PC-1): mu_C = sigma(eta) (link "asym": 0.03 + 0.77 sigma(eta)), mu_S
    = c_H sigma(eta_S), mu_F = c_H sigma(c_q), c_H = M_H / 600 (the bounded heads, D8:171). Noiseless (PC-6): no
    observation model, z = eta replicated as on main, s = logit mu_S and s0 = logit mu_F replicated, no counts. Noisy:
    obs.generate draws, from the observation stream default_rng([seed, 3]), the joint row / donor / cell latents in
    PC-3's order (rows, free cells, donors, cells: one free control per prey node and replicate) and the capped counts
    at the frozen tables' locations, gamma = the scenario's noise_scale (v5 1.4-1.6; obslaw, never re-derived here);
    the data are the empirical logits of those counts (z of K_C with B = 324, s and s0 of L_S and L_F with N = 600).
    Reads the truth only to form the intended means; never the planning noise parameters."""
    import obslaw
    s = truth["settings"]
    require_survival(obs)
    eta, etaS, cS = truth["eta"], truth_S["etaS"], truth_S["cS"]
    cH = obs.c_H
    muC = obslaw.sig(eta) if s["link"] == "logit" else 0.03 + 0.77 * obslaw.sig(eta)
    mu = {"C": muC, "S": cH * obslaw.sig(etaS), "F": cH * obslaw.sig(cS)}
    if s["noiseless"]:
        def rep(x):
            return np.repeat(x[:, None], R_REPS, axis=1)
        z, S, S0 = rep(eta), rep(np.log(mu["S"]) - np.log1p(-mu["S"])), rep(np.log(mu["F"]) - np.log1p(-mu["F"]))
        return {"z": z, "zbar": z.mean(axis=1), "s": S, "sbar": S.mean(axis=1), "s0": S0, "s0bar": S0.mean(axis=1),
                "mu": mu}
    x = {"S": etaS, "F": cS}             # (the exact axes x = logit(mu / c): eta_S, c_q; eta for the logit link)
    if s["link"] == "logit":
        x["C"] = eta
    g = obs.generate(np.random.default_rng([seed, 3]), D.qi, D.pj, D.nQ, D.nP, mu, float(s["noise_scale"]), R_REPS,
                     x=x)
    K = g["counts"]
    z = obslaw.empirical_logit(K["C"], B_COUNT)
    S = obslaw.empirical_logit(K["S"], N_SURV)
    S0 = obslaw.empirical_logit(K["F"], N_SURV)
    return {"z": z, "zbar": z.mean(axis=1), "cnt": K["C"].astype(np.int16), "s": S, "sbar": S.mean(axis=1), "s0": S0,
            "s0bar": S0.mean(axis=1), "mu": mu, "loc": g["loc"]}


def observation_hashes(data):
    """The observations' identity (A_design_v5 3.2, 3.6; shared by every result): over the fixed key list OBS_KEYS
    (+ BANK_OBS_KEYS, the intended means data["mu"]["C" | "S" | "F"], in bank mode: "obs" in data) each present key ->
    {shape, dtype "<f8", sha256 of its C-order little-endian float64 bytes}; an absent cnt (a noiseless dataset) ->
    the explicit record {"absent": "noiseless"}; any other absent key refused (ValueError)."""
    keys = OBS_KEYS + (BANK_OBS_KEYS if "obs" in data else ())
    out = {}
    for key in keys:
        if key.startswith("mu_"):
            mu = data.get("mu")
            present = isinstance(mu, dict) and key[3:] in mu
            value = mu[key[3:]] if present else None
        else:
            present = key in data
            value = data.get(key)
        if not present or value is None:
            if key == "cnt" and not present:
                out[key] = dict(ABSENT_CNT)
                continue
            raise ValueError(f"observation_hashes: {key} is absent (only a noiseless dataset's cnt may be)")
        v = np.ascontiguousarray(value, dtype="<f8")
        out[key] = {"shape": list(v.shape), "dtype": "<f8", "sha256": rqlib.sha256_bytes(v.tobytes(order="C"))}
    return out


def check_observations(sc, r, bank, where):
    """A result's observations record (A_design_v5 1.8, 3.2): exactly observation_hashes' keys for its mode; the
    absent-cnt record if and only if its scenario is noiseless (a noisy scenario carrying it is refused); every
    other entry a {shape, dtype "<f8", sha256} record; result["noiseless"] equal to the scenario's. -> None, or
    raises ValueError naming what is wrong."""
    noiseless = bool(SCENARIOS[sc].get("noiseless"))
    if r.get("noiseless") is not noiseless:
        raise ValueError(f"{where}: noiseless {r.get('noiseless')!r} is not the scenario's {noiseless}")
    ob = r.get("observations")
    keys = OBS_KEYS + (BANK_OBS_KEYS if bank else ())
    if not isinstance(ob, dict) or set(ob) != set(keys):
        raise ValueError(f"{where}: observations must hold exactly {list(keys)}")
    for k in keys:
        v = ob[k]
        if k == "cnt" and v == ABSENT_CNT:
            if not noiseless:
                raise ValueError(f"{where}: a noisy scenario ({sc}) carries the absent-cnt record {ABSENT_CNT}")
            continue
        if k == "cnt" and noiseless:
            raise ValueError(f"{where}: a noiseless scenario ({sc}) must record cnt as {ABSENT_CNT}")
        if not (isinstance(v, dict) and set(v) == {"shape", "dtype", "sha256"} and v["dtype"] == "<f8"
                and isinstance(v["shape"], list) and rqlib.is_sha256(v["sha256"])):
            raise ValueError(f"{where}: observations.{k} is not a {{shape, dtype, sha256}} record")


def additive_projection(D, y, iters=40):
    """The additive (mu + a_j - b_i) least-squares fit of y over every pair of the graph."""
    a, b = np.zeros(D.nP), np.zeros(D.nQ)
    mu = y.mean()
    nq = np.bincount(D.qi, minlength=D.nQ)
    npp = np.bincount(D.pj, minlength=D.nP)
    for _ in range(iters):
        b = -np.bincount(D.qi, weights=y - mu - a[D.pj], minlength=D.nQ) / np.maximum(nq, 1)
        a = np.bincount(D.pj, weights=y - mu + b[D.qi], minlength=D.nP) / np.maximum(npp, 1)
        mu = (y - a[D.pj] + b[D.qi]).mean()
    return mu + a[D.pj] - b[D.qi]


# ------------------------------------------------------------------ the minimal map fitter
def _solve_nodes(idx, X, y, n, ridge):
    """For every node k: (sum X_e X_e' + diag(ridge)) theta_k = sum X_e y_e over its pairs."""
    d = X.shape[1]
    A = np.empty((n, d, d))
    rhs = np.empty((n, d))
    for p in range(d):
        rhs[:, p] = np.bincount(idx, weights=X[:, p] * y, minlength=n)
        for q in range(p, d):
            A[:, p, q] = np.bincount(idx, weights=X[:, p] * X[:, q], minlength=n)
            A[:, q, p] = A[:, p, q]
    A[:, np.arange(d), np.arange(d)] += ridge
    return np.linalg.solve(A, rhs[..., None])[..., 0]


def fit(D, idx, zbar, rank, lam, own_layer, iters=40, seed=0, lam_ab=1e-3, lam_world=10.0, balance=False,
        init=None, ab_cap=None):
    """Ridge ALS of z = mu + a_j - b_i + u_i.v_j [+ h(lag) + h_w(lag) on within pairs] -> params.
    balance: rescale each latent dimension to equal u and v norms after every sweep (the product is
    unchanged; it keeps a nearly unpenalized fit, the numerical check's, from drifting along the
    scale freedom). init: a previous fit's parameters to start from (a warm start). ab_cap r: the
    A/B prey's interaction is held to its first r dimensions (the rest pinned at 0)."""
    rng = np.random.default_rng(seed)
    qi, pj, z = D.qi[idx], D.pj[idx], zbar[idx]
    a, b = np.zeros(D.nP), np.zeros(D.nQ)
    u = rng.normal(0.0, 0.1, (D.nQ, rank))
    v = rng.normal(0.0, 0.1, (D.nP, rank))
    mu = float(z.mean())
    nb, nW = D.nbins, len(D.worlds)
    h, hw = np.zeros(nb), np.zeros((nW, nb))
    if init is not None:
        a, b, u, v, mu, h, hw = (init["a"].copy(), init["b"].copy(), init["u"].copy(), init["v"].copy(),
                                 init["mu"], init["h"].copy(), init["hw"].copy())
    wi = D.within[idx] if own_layer else np.zeros(len(idx), bool)
    lb, lw = D.lagbin[idx][wi], D.ownw[idx][wi]
    ridge = np.array([lam_ab] + [lam] * rank)
    ridge_q = ridge
    if ab_cap is not None and ab_cap < rank:
        ridge_q = np.tile(ridge, (D.nQ, 1))
        ridge_q[D.qab, 1 + ab_cap:] = 1e9
        u[D.qab, ab_cap:] = 0.0
    one = np.ones(len(idx))
    for _ in range(iters):
        own = np.zeros(len(idx))
        if wi.any():
            own[wi] = h[lb] + hw[lw, lb]
        th = _solve_nodes(qi, np.column_stack([-one, v[pj]]), z - mu - a[pj] - own, D.nQ, ridge_q)
        b, u = th[:, 0], th[:, 1:]
        th = _solve_nodes(pj, np.column_stack([one, u[qi]]), z - mu + b[qi] - own, D.nP, ridge)
        a, v = th[:, 0], th[:, 1:]
        if balance:
            for k in range(rank):
                nu, nv = np.linalg.norm(u[:, k]), np.linalg.norm(v[:, k])
                if nu > 0 and nv > 0:
                    s = math.sqrt(nv / nu)
                    u[:, k] *= s
                    v[:, k] /= s
        core = a[pj] - b[qi] + (u[qi] * v[pj]).sum(axis=1)
        mu = float((z - core - own).mean())
        if wi.any():
            r = (z - mu - core)[wi]
            cnt = np.bincount(lb, minlength=nb)
            h = np.bincount(lb, weights=r - hw[lw, lb], minlength=nb) / np.maximum(cnt, 1)
            k = lw * nb + lb
            rr = r - h[lb]
            hw = (np.bincount(k, weights=rr, minlength=nW * nb)
                  / (np.bincount(k, minlength=nW * nb) + lam_world)).reshape(nW, nb)
    return {"mu": mu, "a": a, "b": b, "u": u, "v": v, "h": h, "hw": hw, "own": bool(wi.any())}


def predict(D, m, idx):
    qi, pj = D.qi[idx], D.pj[idx]
    out = m["mu"] + m["a"][pj] - m["b"][qi] + (m["u"][qi] * m["v"][pj]).sum(axis=1)
    if m["own"]:
        wi = D.within[idx]
        lb, lw = D.lagbin[idx][wi], D.ownw[idx][wi]
        out[wi] += m["h"][lb] + m["hw"][lw, lb]
    return out


def lpd(z, pred, s2):
    """DIAGNOSTIC ONLY (the Gaussian working score of reg1-reg5): the mean Gaussian log density of the
    empirical logits per replicate observation, per pair; s2 a scalar or one variance per pair."""
    s2 = np.asarray(s2, dtype=float)
    if s2.ndim:
        s2 = s2[:, None]
    return (-0.5 * np.log(2 * math.pi * s2) - ((z - pred[:, None]) ** 2) / (2 * s2)).mean(axis=1)


def count_lpd(cnt, loc, var):
    """THE registered score: the capture-count log predictive density per replicate observation, per pair
    (map.count_lpd: Annex H.9.2's bounded observation model, B = B_COUNT)."""
    import map as mapfit
    return mapfit.count_lpd(cnt, B_COUNT, loc, var)


def scorer(D, data, m, idx, fitter):
    """A fit's predictive model as a scoring function ix -> (count lpd per pair, Gaussian working lpd per
    pair). The registered map: the count score is map.pred_count_lpd (the predictor-scale uncertainty -- the
    location's posterior variance and the pair residual, both inside the link -- integrated through the
    link, with a fresh replicate's phi V(p)); the Gaussian diagnostic uses map.pred_var's first-order
    moments. The minimal fitter: its predictions with one variance, the training residual mean square, for
    both. Only the count density decides."""
    if fitter == "registered":
        import map as mapfit

        def score(ix, info=None):
            loc, var = mapfit.pred_var(D, m, ix)
            return (mapfit.pred_count_lpd(D, m, ix, data["cnt"][ix], B_COUNT, info=info),
                    lpd(data["z"][ix], loc, var))
        return score
    pf = predict(D, m, idx)
    s2 = float(((data["z"][idx] - pf[:, None]) ** 2).mean())

    def score(ix, info=None):
        loc, var = predict(D, m, ix), np.full(len(ix), s2)
        if info is not None:
            info["exact"] = info.get("exact", 0) + int(len(ix))          # (one variance: no integral)
        return count_lpd(data["cnt"][ix], loc, var), lpd(data["z"][ix], loc, var)
    return score


def world_mean(vals, worlds):
    ws = np.unique(worlds)
    return float(np.mean([vals[worlds == w].mean() for w in ws])), ws


def cluster_lb(diff, worlds, rng, n=2000):
    """(Superseded for the decision by crossed_lb.) Mean of the per-world means of diff, and its
    test-world cluster-bootstrap 2.5% quantile."""
    ws = np.unique(worlds)
    per = np.array([diff[worlds == w].mean() for w in ws])
    boots = per[rng.integers(0, len(ws), (n, len(ws)))].mean(axis=1)
    return float(per.mean()), float(np.quantile(boots, 0.025)), per.tolist()


def crossed_lb(diff, test_world, qworld, pworld, rng, n=2000):
    """The registered statistic (the mean over test worlds of their targets' mean score difference) and
    its CROSSED source-world bootstrap 2.5% quantile (v4 §7.6; Annex H.7): every draw resamples the
    targets' SOURCE worlds (both endpoints' worlds; a frozen reference is a calibration object, never
    resampled) with replacement, multiplicities m; a target keeps its observed equal-test-world weight
    times m_u m_v (cross-world), m_u (within one world, or against a reference). A draw whose weights
    vanish counts as -inf (never dropped). -> (mean, lower bound, per-test-world means)."""
    ws, tinv = np.unique(test_world, return_inverse=True)
    nper = np.bincount(tinv)
    per = np.bincount(tinv, weights=diff) / nper
    base = 1.0 / (nper[tinv] * len(ws))
    src = np.unique(np.concatenate([qworld[qworld >= 0], pworld[pworld >= 0]]))
    qi = np.where(qworld >= 0, np.searchsorted(src, np.maximum(qworld, 0)), -1)
    pj = np.where((pworld >= 0) & (pworld != qworld), np.searchsorted(src, np.maximum(pworld, 0)), -1)
    keys, ginv = np.unique(np.stack([qi, pj]), axis=1, return_inverse=True)   # targets grouped by source pair
    ginv = np.ravel(ginv)
    gw = np.bincount(ginv, weights=base)
    gd = np.bincount(ginv, weights=base * diff)
    stats = np.empty(n)
    for k0 in range(0, n, 500):
        k1 = min(n, k0 + 500)
        M = rng.multinomial(len(src), np.full(len(src), 1.0 / len(src)), size=k1 - k0).astype(float)
        mq = np.where(keys[0] >= 0, M[:, np.maximum(keys[0], 0)], 1.0)
        mp = np.where(keys[1] >= 0, M[:, np.maximum(keys[1], 0)], 1.0)
        wts = mq * mp
        den = wts @ gw
        with np.errstate(invalid="ignore", divide="ignore"):
            stats[k0:k1] = np.where(den > 0, (wts @ gd) / np.where(den > 0, den, 1.0), -np.inf)
    srt = np.sort(stats)                     # (the order statistic: -inf draws stay in, never interpolated)
    return float(per.mean()), float(srt[min(n, max(1, math.ceil(0.025 * (n + 1)))) - 1]), per.tolist()


FITTERS = ("minimal", "registered")


def any_fit(fitter, D, idx, data, rank, lam, own_layer, iters, seed, ab_cap=None, init=None, balance=False,
            start="both", weighted=True, ctrl=None, basis=6, embedding="shared", center="references"):
    """The minimal fitter (fit) or the registered map (map.py: the monotone 6 x 6 tensor baseline, the
    monotone-spline bounded link, the joint survival head, heteroscedastic capture weights from the
    scenario's variance function; start "both": warm and cold, the lower penalized training objective
    kept; ctrl: the accessible predator-free controls, None = map.control_access(D, idx)).
    THE SINGLE CHOKE POINT of the observation model (A_design_v5 3.2, 3.5): every procedure, forward procedure,
    numerical check and recovery_extra procedure fits through here. Bank mode ("obs" in data): bank_hooks (the bank's
    W, nu0 prior and score law together for a weighted fit of a dataset with counts, all three None otherwise); it
    never reads data["settings"] or another truth-only field. Planning mode: unchanged (var_model(settings))."""
    if fitter == "registered":
        try:
            import map as mapfit
        except ImportError:
            raise SystemExit("--fitter registered needs map.py (item 7, the registered map; its own PR)")
        if own_layer:
            return mapfit.fit(D, idx, data, rank, lam, own_layer, iters, seed)     # (refused: option b)
        if "obs" in data:
            hooks = bank_hooks(data, weighted)
        else:
            hooks = {"var_fn": var_model(data.get("settings")) if weighted else None}
        starts = ("warm", "cold") if start == "both" else (start,)
        return mapfit.fit_best(D, idx, data, rank, lam, iters, seed, starts=starts, init=init, ctrl=ctrl, basis=basis,
                               embedding=embedding, center=center, **hooks)
    return fit(D, idx, data["zbar"], rank, lam, own_layer, iters, seed, ab_cap=ab_cap, init=init, balance=balance)


def bank_hooks(data, weighted):
    """Bank mode's variance model for map.fit (A_design_v5 3.2, 3.3, 3.5; PC-6, PC-14, PC-17): weighted with counts ->
    var_fn = W (obs.working_var_fn(), tagged .identity = the model's identity sha), rep_prior = {"nu0": nu0_C} (None:
    full pooling), score_law = (A, L) (obs.score_law()), fresh objects per call (per-call extrapolation counts);
    otherwise (a numerical fit: weighted False, or a noiseless dataset without counts) all three None. Reads data["obs"]
    and the presence of data["cnt"] only."""
    obs = data["obs"]
    if weighted and "cnt" in data:
        return {"var_fn": obs.working_var_fn(), "rep_prior": {"nu0": obs.nu0_C}, "score_law": obs.score_law()}
    return {"var_fn": None, "rep_prior": None, "score_law": None}


def any_predict(D, m, idx):
    if "surfC" in m:
        import map as mapfit
        return mapfit.predict(D, m, idx)
    return predict(D, m, idx)


def class_accuracy(D, data, m1, m0):
    """Per target class: the selected map's and rank 0's RMSE against the truth (a labelled TRUTH DIAGNOSTIC: None
    when the truth-only fields are absent, A_design_v5 1.8 / T6-9; no criterion reads it)."""
    if "eta" not in data or "inter" not in data:
        return None
    out = {}
    for name, ix in D.classes.items():
        if len(ix):
            e = data["eta"][ix]
            out[name] = {"n": int(len(ix)),
                         "rmse_selected": float(np.sqrt(np.mean((any_predict(D, m1, ix) - e) ** 2))),
                         "rmse_rank0": float(np.sqrt(np.mean((any_predict(D, m0, ix) - e) ** 2))),
                         "interaction_sd": float(np.std(data["inter"][ix]))}
    return out


PRIMARY_RANKS = 2      # (v4 amendment proposed 2026-11-07: the primary confirmatory rank set is {0, 1, 2})
MIN_TEST_ROOTS = 2     # (Annex H D6 rule 27: the crossed bound / a prediction decision needs at least two contributing test roots)
MIN_TEST_WORLDS = MIN_TEST_ROOTS


def _flagged(*infos):
    """Pairs whose count score is FINITE BUT UNRESOLVED (map.pred_count_lpd's grid_unresolved: a check failed on
    the largest grid or range), summed over integration diagnostics (None / {}: none). A comparison that
    contains one is never decided on it (Codex #66 r5 P2-1)."""
    return int(sum(int((i or {}).get("grid_unresolved", 0)) for i in infos))


def _unresolved_why(n, where):
    return (f"{n} pair score(s) UNRESOLVED by the count integral (grid_unresolved; {where}): finite but not "
            "checked to tolerance, so the comparison is not decided")
FORWARD_TMAX = 120     # (v4 §7.3: the forward fit's main outcomes and controls through 120M)
SCORE = {"decision": "capture-count lpd per replicate observation (map.pred_count_lpd: Annex H.9.2's rounded "
                     "logit-normal at G(eta + e), e ~ N(0, posterior + pair-residual variance) integrated inside the "
                     "link; the minimal fitter: map.count_lpd at its residual variance)",
         "diagnostic": "Gaussian working lpd of the empirical logits at map.pred_var's first-order moments "
                       "(*_gauss; the reg1-reg5 score)"}


def _cand_record(D, data, m, r, lam, fitter, score, val, val_world, t0, extra=None):
    info = {}
    vc, vg = score(val, info)
    rec = {"rank": r, "lambda": lam, "val_lpd": world_mean(vc, val_world)[0],
           "val_lpd_gauss": world_mean(vg, val_world)[0], "start": m.get("start"), "objectives": m.get("objectives"),
           "integration": {"validation": info}}          # (map.pred_count_lpd's cases and checks, reported)
    if fitter == "registered":
        rec.update(qp=m["qp"], link={"lo": m["link"].lo, "hi": m["link"].hi}, phi=m["phi"], pair_var=m["pair_var"])
        if "obs" in data:               # (bank mode only, so planning records stay byte-identical; A_design_v5 1.7b)
            sl = m.get("score_law")
            rec["observation_model"] = {"var_fn_identity": m.get("var_fn_identity"), "rep_prior": m.get("rep_prior"),
                                        "score_law_identity": getattr(sl, "identity", None),
                                        "table_extrapolated": m.get("table_extrapolated")}
    rec.update(extra or {})
    rec["seconds"] = round(time.time() - t0, 2)
    return rec


def _bounded(diff, tw, qw, pw, seed):
    """crossed_lb, or (None, None, []) without targets."""
    if not len(diff):
        return None, None, []
    return crossed_lb(diff, tw, qw, pw, np.random.default_rng(seed))


def unavailable(fit, val, test, test_world, val_world):
    """(why, test roots): why the selection-and-prediction procedure is UNDEFINED on a (masked) graph's sets (Codex
    #77 r1 P2-6; None: defined): no fitting pairs, no validation targets (nothing selects), or fewer than
    MIN_TEST_ROOTS contributing test roots (test worlds; none: the bootstrap would have no source)."""
    roots = int(len(np.unique(test_world))) if len(test) else 0
    if not len(fit):
        return "no fitting pairs (every one excluded by the mask)", roots
    if not len(val) or not len(np.unique(val_world)):
        return "no validation targets under the mask: the selection is undefined", roots
    if roots < MIN_TEST_ROOTS:
        return (f"{roots} contributing test root(s) under the mask: the crossed bound needs at least "
                f"{MIN_TEST_ROOTS}"), roots
    return None, roots


def procedure(D, data, option, ranks, lambdas, iters, seed, ab_cap=None, fitter="minimal", start="both",
              basis=6, embedding="shared", center="references"):
    """The registered selection and prediction procedure on one dataset for one fitting option, under THE
    SCORE (the capture-count lpd; the Gaussian working score beside it as *_gauss, diagnostic only).
    Every candidate also records its test improvement over rank 0 and the crossed lower bound, and the
    selection restricted to ranks <= PRIMARY_RANKS is reported beside the full one (selected_primary).
    With fewer than MIN_TEST_ROOTS contributing test roots (or no fitting pairs or validation targets under a mask) the
    procedure is UNAVAILABLE, with its reason and no success (D6 rule 27; unavailable(): Codex #77 r1 P2-6)."""
    idx = D.fit[option]
    why, roots = unavailable(idx, D.val_idx, D.test_idx, D.test_world, D.val_world)
    if why:
        return {"available": False, "reason": why, "fitter": fitter, "fit_pairs": int(len(idx)),
                "validation_targets": int(len(D.val_idx)), "test_targets": int(len(D.test_idx)), "test_roots": roots}
    own_layer = option == "b"
    cands = [(0, 0.0)] + [(r, lam) for r in range(1, ranks + 1) for lam in lambdas]
    out = {"candidates": [], "fitter": fitter, "start": start if fitter == "registered" else None, "score": SCORE}
    if fitter == "registered":
        out.update(basis=basis, embedding=embedding, center=center)
    best, models = None, {}
    for r, lam in cands:
        t0 = time.time()
        m = any_fit(fitter, D, idx, data, r, lam, own_layer, iters, seed, ab_cap=ab_cap, start=start, basis=basis,
                    embedding=embedding, center=center)
        sc = scorer(D, data, m, idx, fitter)
        tinfo = {}
        tc, tg = sc(D.test_idx, tinfo) if len(D.test_idx) else (np.zeros(0), np.zeros(0))
        pt = any_predict(D, m, D.test_idx)
        rec = _cand_record(D, data, m, r, lam, fitter, sc, D.val_idx, D.val_world, t0, {      # (a truth diagnostic)
            "test_rmse_truth": float(np.sqrt(np.mean((pt - data["eta"][D.test_idx]) ** 2)))
            if len(pt) and "eta" in data else None})
        rec["integration"]["test"] = tinfo
        out["candidates"].append(rec)
        models[(r, lam)] = (m, sc, tc, tg)
        if best is None or rec["val_lpd"] > best["val_lpd"]:
            best = rec
    sel = (best["rank"], best["lambda"])
    m1, sc1, tc1, tg1 = models[sel]
    m0, sc0, tc0, tg0 = models[(0, 0.0)]
    nw = int(len(np.unique(D.test_world)))
    rec0 = out["candidates"][0]
    # Codex #66 r5 P2-1: a finite UNRESOLVED score (grid_unresolved) never silently decides. The selection reads every
    # candidate's validation scores; a comparison reads its two models' test (or snapshot) scores. Each flagged
    # comparison is reported unresolved: its improvement and bound are withheld and its success is False.
    unres_val = _flagged(*(c["integration"]["validation"] for c in out["candidates"]))
    pair_inf = [best["integration"]["test"]] + ([rec0["integration"]["test"]] if best is not rec0 else [])
    unres_test = _flagged(*pair_inf)
    avail = nw >= MIN_TEST_WORLDS and not (unres_val or unres_test)
    tw = (D.test_world, D.test_qworld, D.test_pworld)
    for rec in out["candidates"]:      # (every candidate against rank 0: any restricted selection, post hoc)
        _, _, tck, tgk = models[(rec["rank"], rec["lambda"])]
        rec["test_improvement"], rec["test_lb"], _ = _bounded(tck - tc0, *tw, seed + 7)
        rec["integration_unresolved"] = _flagged(rec["integration"]["test"],
                                                 *([rec0["integration"]["test"]] if rec is not rec0 else []))
        if rec["integration_unresolved"]:
            rec["test_improvement"] = rec["test_lb"] = None
        rec["test_improvement_gauss"], rec["test_lb_gauss"], _ = _bounded(tgk - tg0, *tw, seed + 7)

    def ok(rank, lb):
        return bool(avail and rank > 0 and lb is not None and lb > 0)
    # Codex #66 r6 P2-1: an unresolved VALIDATION score leaves the selection itself unresolved, so EVERY selection-
    # dependent reported metric (the selected and primary improvements and bounds, the snapshot comparison, the
    # alignment, the class accuracy of the selected map) is withheld (None), not only the decision and success; the
    # primary selection reads the validation scores of its own candidates (rank <= PRIMARY_RANKS) only.
    prim = max((c for c in out["candidates"] if c["rank"] <= PRIMARY_RANKS), key=lambda c: c["val_lpd"])
    unres_val_prim = _flagged(*(c["integration"]["validation"] for c in out["candidates"]
                                if c["rank"] <= PRIMARY_RANKS))
    avail_prim = bool(nw >= MIN_TEST_WORLDS and not unres_val_prim and not prim["integration_unresolved"])
    pimp, plb = (prim["test_improvement"], prim["test_lb"]) if not unres_val_prim else (None, None)
    out["selected_primary"] = {"ranks": list(range(PRIMARY_RANKS + 1)), "rank": prim["rank"],
                               "lambda": prim["lambda"], "start": prim["start"], "available": avail_prim,
                               "test_improvement": pimp, "test_lb": plb,
                               "success": bool(avail_prim and prim["rank"] > 0 and plb is not None and plb > 0)}
    if unres_val_prim:
        out["selected_primary"]["selection_unresolved"] = True
    mean, lb, per = _bounded(tc1 - tc0, *tw, seed + 7)
    if unres_test or unres_val:
        mean = lb = None
        per = []
    gbest = max(out["candidates"], key=lambda c: c["val_lpd_gauss"])
    si1, si0 = {}, {}
    if len(D.stest_idx):
        (s1c, s1g), (s0c, s0g) = sc1(D.stest_idx, si1), sc0(D.stest_idx, si0)
        snap, snap_g = float((s1c - s0c).mean()), float((s1g - s0g).mean())
    else:
        snap = snap_g = None
    unres_snap = _flagged(si1, *([si0] if sel != (0, 0.0) else []))
    if unres_snap or unres_val:
        snap = None
    if unres_val:
        snap_g = None
    if sel[0] > 0 and not unres_val:
        trn = D.fit[option]
        qn = np.unique(D.qi[trn])
        lead = m1["u"][qn, 0]
        align = float(abs(np.corrcoef(lead, m1["b"][qn])[0, 1])) if lead.std() > 0 else 0.0
    else:
        align = None
    selected = {"rank": sel[0], "lambda": sel[1], "start": best["start"]}
    if unres_val:
        selected["selection_unresolved"] = True        # (the nominal pick: not a result; summarize() leaves it out)
    out.update(selected=selected, test_improvement=mean,
               test_lb=lb, per_test_world=per, success=ok(sel[0], lb),
               decision={"available": avail, "test_worlds": nw, "selection_unresolved": bool(unres_val),
                         "integration_unresolved": unres_val + unres_test,
                         "reason": (None if avail else
                                    f"fewer than {MIN_TEST_WORLDS} contributing test worlds" if nw < MIN_TEST_WORLDS else
                                    _unresolved_why(unres_val + unres_test,
                                                    f"{unres_val} in validation, {unres_test} in the test comparison"))},
               integration_comparison={"selected": best["integration"]["test"], "rank0": rec0["integration"]["test"],
                                       "snapshot": {"selected": si1, "rank0": si0},
                                       "unresolved": {"validation": unres_val, "test": unres_test,
                                                      "snapshot": unres_snap}},
               gauss_diagnostic={"selected": {"rank": gbest["rank"], "lambda": gbest["lambda"]},
                                 "test_improvement": gbest["test_improvement_gauss"],
                                 "test_lb": gbest["test_lb_gauss"], "success": ok(gbest["rank"], gbest["test_lb_gauss"])},
               snapshot_test_improvement=snap, snapshot_test_improvement_gauss=snap_g, alignment_u1_b=align,
               fit_pairs=int(len(idx)), classes=None if unres_val else class_accuracy(D, data, m1, m0),
               ab_cap=ab_cap)
    return out


def forward_procedure(D, data, ranks, lambdas, iters, seed, ab_cap=None, fitter="minimal", start="both",
                      basis=6, embedding="shared", center="references"):
    """The SEPARATE forward-time recovery (v4 §7.3): the same selection-and-prediction procedure on
    D.forward's sets (fit through 120M plus references <= 120M; validation 141-160M; test 181-200M),
    reported separately for the forward transfer and its intersection with the test worlds (each with
    the crossed bootstrap). The registered map reads the predator-free controls of prey at <= 120M only
    (map.control_access(D, fit, FORWARD_TMAX): Codex #66 r1 P1-1) and centres on the early references
    it places."""
    F = D.forward
    idx = F["fit"]
    ctrl = None
    if fitter == "registered":
        import map as mapfit
        ctrl = mapfit.control_access(D, idx, FORWARD_TMAX)
    cands = [(0, 0.0)] + [(r, lam) for r in range(1, ranks + 1) for lam in lambdas]
    out = {"procedure": "forward", "candidates": [], "fitter": fitter, "fit_pairs": int(len(idx)), "score": SCORE,
           "val_pairs": int(len(F["val"])), "test_pairs": {k: int(len(v)) for k, v in F["tests"].items()},
           "controls": int(ctrl.sum()) if ctrl is not None else None}
    if not len(idx) or not len(F["val"]):              # (Codex #77 r1 P2-6: nothing to fit or select under the mask)
        return dict(out, available=False, reason="no fitting pairs" if not len(idx) else
                    "no validation targets under the mask: the selection is undefined")
    best, models = None, {}
    for r, lam in cands:
        t0 = time.time()
        m = any_fit(fitter, D, idx, data, r, lam, False, iters, seed, ab_cap=ab_cap, start=start, ctrl=ctrl,
                    basis=basis, embedding=embedding, center=center)
        sc = scorer(D, data, m, idx, fitter)
        rec = _cand_record(D, data, m, r, lam, fitter, sc, F["val"], F["val_world"], t0)
        out["candidates"].append(rec)
        models[(r, lam)] = (m, sc)
        if best is None or rec["val_lpd"] > best["val_lpd"]:
            best = rec
    sel = (best["rank"], best["lambda"])
    m1, sc1 = models[sel]
    m0, sc0 = models[(0, 0.0)]
    out["selected"] = {"rank": sel[0], "lambda": sel[1], "start": best["start"]}
    unres_val = _flagged(*(c["integration"]["validation"] for c in out["candidates"]))      # (Codex #66 r5 P2-1)
    out["integration_unresolved"] = {"validation": unres_val}
    for name, t in F["tests"].items():
        if not len(t):
            out[name] = {"available": False, "reason": "no targets"}
            continue
        i1, i0 = {}, {}                                  # (the two models' integration diagnostics, kept)
        (c1, g1), (c0, g0) = sc1(t, i1), sc0(t, i0)
        qw, pw = D.qw[D.qi[t]], D.pw[D.pj[t]]
        tw = np.where((qw >= 0) & (D.wsplit[np.maximum(qw, 0)] == ("test" if name == "intersection" else "train")),
                      qw, pw)
        nw = int(len(np.unique(tw)))
        if nw < MIN_TEST_ROOTS:                         # (Codex #77 r1 P2-6: the D6 minimum, never a one-root bound)
            out[name] = {"available": False, "targets": int(len(t)), "test_roots": nw,
                         "reason": f"fewer than {MIN_TEST_ROOTS} contributing test roots"}
            continue
        unres_t = _flagged(i1, *([i0] if sel != (0, 0.0) else []))      # (Codex #66 r5 P2-1: finite but unresolved:
                                                                         #  never decided)
        if unres_t or unres_val:
            out[name] = {"available": False, "integration_unresolved": unres_t + unres_val, "targets": int(len(t)),
                         "worlds": nw, "integration": {"selected": i1, "rank0": i0},
                         "reason": _unresolved_why(unres_t + unres_val,
                                                   f"{unres_val} in validation, {unres_t} in this comparison")}
            continue
        mean, lb, per = crossed_lb(c1 - c0, tw, qw, pw, np.random.default_rng(seed + 11 + len(name)))
        gmean, glb, _ = crossed_lb(g1 - g0, tw, qw, pw, np.random.default_rng(seed + 11 + len(name)))
        out[name] = {"available": True, "test_improvement": mean, "test_lb": lb, "per_world": per,
                     "success": bool(nw >= MIN_TEST_WORLDS and sel[0] > 0 and lb > 0), "targets": int(len(t)),
                     "worlds": nw, "decision_available": nw >= MIN_TEST_WORLDS,
                     "integration": {"selected": i1, "rank0": i0}, "integration_unresolved": 0,
                     "test_improvement_gauss": gmean, "test_lb_gauss": glb}
    ft = out["forward_transfer"]
    out["decision"] = {"available": bool(ft.get("available") and ft.get("decision_available")),
                       "reason": ft.get("reason"), "selection_unresolved": bool(unres_val),
                       "integration_unresolved": max(unres_val, int(ft.get("integration_unresolved", 0)))}
    if unres_val:
        out["selected"]["selection_unresolved"] = True
    out["success"] = out["forward_transfer"].get("success", False)
    out["test_improvement"] = out["forward_transfer"].get("test_improvement")
    out["test_lb"] = out["forward_transfer"].get("test_lb")
    out["classes"] = {}
    return out


CONTINUATION = (0.3, 0.1, 0.03, 0.01, 0.003, 0.001)
# the registered map's path ends at 0.01, its minimum on noiseless data (below it the flexible surface and
# the interaction trade off: the error rises; the registered grid never goes below 0.01)
REG_CONTINUATION = (0.3, 0.1, 0.03, 0.01)
REGISTERED_LAMBDAS = (0.01, 0.02, 0.05, 0.2)


def numerical(D, data, option, rank, iters, seed, ab_cap=None, fitter="minimal", basis=6, embedding="shared",
              center="references"):
    """Noiseless data fitted at the true rank (the penalty continued down to 0.001, warm-started and
    balanced, 100 sweeps per step: a cold nearly unpenalized ALS stalls short of the exact fit; the
    registered map: REG_CONTINUATION, 30 sweeps per step, each step started from the last): the
    test targets' errors relative to the interaction's SD, overall and without the targets that have
    an endpoint with fewer fitting pairs than the rank's parameters (rank + 1: not identifiable)."""
    idx = D.fit[option]
    m = None
    predict = any_predict              # noqa: F811
    for lam in CONTINUATION if fitter == "minimal" else REG_CONTINUATION:
        m = any_fit(fitter, D, idx, data, rank, lam, option == "b", 100 if fitter == "minimal" else 30, seed,
                    ab_cap=ab_cap, init=m, balance=True, start="warm" if m is None else "both", weighted=False,
                    basis=basis, embedding=embedding, center=center)
    t = D.test_idx
    err = predict(D, m, t) - data["eta"][t]
    sd = float(np.std(data["inter"][t]))
    dq = np.bincount(D.qi[idx], minlength=D.nQ)
    dp = np.bincount(D.pj[idx], minlength=D.nP)
    under = (dq[D.qi[t]] < rank + 1) | (dp[D.pj[t]] < rank + 1)
    rel = lambda e: float(np.sqrt(np.mean(e ** 2)) / sd) if len(e) and sd else None  # noqa: E731
    cls = {name: rel(predict(D, m, ix) - data["eta"][ix]) for name, ix in D.classes.items() if len(ix)}
    return {"rank": rank, "interaction_sd": sd, "relative": rel(err),
            "relative_identified": rel(err[~under]), "underdetermined_targets": int(under.sum()),
            "median_abs_relative": float(np.median(np.abs(err)) / sd) if sd else None,
            "p90_abs_relative": float(np.quantile(np.abs(err), 0.9) / sd) if sd else None,
            "relative_by_class": cls, "ab_cap": ab_cap}


# ------------------------------------------------------------------ commands
_DATA = {}
CONFIG_SCHEMA = "finfolk.redqueen.recoverycfg/1"


FITTER_DEFAULTS = {     # (Codex #66 r1 P2-7: each fitter's registered command-line defaults)
    "minimal": {"options": "a,b,base", "lambdas": "0.02,0.1,0.5", "iters": 40, "start": "both", "basis": 6,
                "embedding": "shared", "center": "references"},
    "registered": {"options": "a", "lambdas": ",".join(repr(x) for x in REGISTERED_LAMBDAS), "iters": 30,
                   "start": "both", "basis": 6, "embedding": "shared", "center": "references"},
}
TOOLS = ("recovery.py", "map.py", "graph.py", "rqlib.py", "noisebank.py",   # (every computational dependency;
         "noisescale.py", "common.py", "material.py", "obslaw.py",          #  bank mode's transitive sources,
         "fixtures/registered_ages.json")                                   #  A_design_v5 3.2 / memo L99)


def resolve(a):
    """Fill the fitter's registered defaults into the arguments a (None: not given) and refuse incompatible
    choices BEFORE any worker starts (Codex #66 r1 P2-7) -> a."""
    fitter = getattr(a, "fitter", None) or "minimal"
    if fitter not in FITTERS:
        raise SystemExit(f"--fitter {fitter}: one of {FITTERS}")
    a.fitter = fitter
    d = FITTER_DEFAULTS[fitter]
    for k, v in d.items():
        if getattr(a, k, None) is None:
            setattr(a, k, v)
    if getattr(a, "ab_cap", None) is None:
        a.ab_cap = -1
    opts = a.options.split(",")
    if not opts or len(set(opts)) != len(opts) or any(o not in OPTIONS + ("fwd",) for o in opts):
        raise SystemExit(f"--options {a.options}: distinct options of {OPTIONS + ('fwd',)}")
    try:
        lams = [float(x) for x in a.lambdas.split(",")]
    except ValueError:
        raise SystemExit(f"--lambdas {a.lambdas}: a comma list of numbers")
    if not lams or any(not (math.isfinite(x) and x > 0) for x in lams):
        raise SystemExit(f"--lambdas {a.lambdas}: positive finite penalties")
    if getattr(a, "ranks", 0) < 0 or a.iters < 1:
        raise SystemExit("--ranks >= 0 and --iters >= 1")
    if fitter == "registered":
        if "b" in opts:
            raise SystemExit("--options b: option (b), the own-world layer inside the Level-1 fit, is dropped for the "
                             "registered map (q30b; map.fit refuses it): use a, base or fwd")
        if a.ab_cap >= 0:
            raise SystemExit("--ab-cap: a minimal-fitter comparison only (the registered map has no A/B cap)")
        if a.start not in ("both", "warm", "cold"):
            raise SystemExit(f"--start {a.start}: both, warm or cold")
        if a.basis not in (4, 6, 8) or a.embedding not in ("shared", "separate") or a.center not in ("references",
                                                                                                        "train_c"):
            raise SystemExit("--basis 4|6|8, --embedding shared|separate, --center references|train_c")
    else:
        for k in ("start", "basis", "embedding", "center"):
            if getattr(a, k) != d[k]:
                raise SystemExit(f"--{k}: the registered map's option (the minimal fitter has none)")
    a.obs_model = getattr(a, "obs_model", None) or "planning"            # (A_design_v5 3.2 CLI; planning: default)
    if a.obs_model not in OBS_MODELS:
        raise SystemExit(f"--obs-model {a.obs_model}: one of {OBS_MODELS}")
    given = [k for k in ("bank", "obs_tables") if getattr(a, k, None)]
    if a.obs_model == "bank" and len(given) != 2:
        raise SystemExit("--obs-model bank needs --bank and --obs-tables (the frozen bank/3 artifact and its tables)")
    if a.obs_model == "planning" and (given or getattr(a, "allow_synthetic_bank", False)):
        raise SystemExit("--bank / --obs-tables / --allow-synthetic-bank are bank mode's (--obs-model bank) only")
    return a


def graph_identity(meta):
    """The graph a run consumes (Codex #66 r1 P2-8): its edges' sha256 and the canonical sha256 of all of its
    metadata (worlds and treatments, splits, snapshot holdouts, the settings: everything Data reads besides
    the edges)."""
    m = {k: v for k, v in meta.items() if k != "edges"}
    return {"edges_sha256": m["edges_sha256"], "meta_sha256": rqlib.canonical_sha(m)}


def scenario_gamma(name):
    """The noise multiplier gamma of a registered scenario (its noise_scale; bank mode scales the bank's latent
    scales by it, A_design_v5 1.5)."""
    return float(dict(DEFAULTS, **SCENARIOS[name])["noise_scale"])


def scenario_names(a):
    """The scenarios a run argument set schedules (run's rule): --scenarios, else --set's."""
    if getattr(a, "scenarios", None):
        return a.scenarios.split(",")
    st = getattr(a, "set", None)
    if not st:
        return []
    return SETS[st] if st != "all" else [n for s in ("main", "stress", "power", "numerical") for n in SETS[s]]


def bank_refusals(a, names):
    """Bank mode refuses, before any file or worker: a *_cap / *_cap15 scenario (BANK_REFUSED: planning
    approximations of the bank, A_design_v5 1.5 PC-4; T7-5)."""
    if getattr(a, "obs_model", "planning") == "bank":
        bad = sorted(set(names) & BANK_REFUSED)
        if bad:
            raise SystemExit(f"--obs-model bank refuses the planning approximations of the bank {bad} (A_design_v5 "
                             "1.5 PC-4: BANK_REFUSED)")


def load_model(a, gammas=(1.0,)):
    """Bank mode: the bank/3 artifact and its tables, loaded and validated in A_design_v5 4.2's order
    (obslaw.BankObservationModel: every noise multiplier in gammas must have its tables), with the test-only
    --allow-synthetic-bank flag (the model is then never accepting); a zero ceiling M_H is refused (v5 1.10) ->
    the model; planning mode -> None. Any refusal is a SystemExit naming the field."""
    if getattr(a, "obs_model", "planning") != "bank":
        return None
    import obslaw
    try:
        obs = obslaw.BankObservationModel(a.bank, a.obs_tables, gammas=tuple(gammas) or (1.0,),
                                          allow_synthetic_bank=bool(getattr(a, "allow_synthetic_bank", False)))
        require_survival(obs)
    except (ValueError, OSError) as e:
        raise SystemExit(f"--obs-model bank: {e}")
    except RecursionError:          # (obslaw's strict parsers: named here, obslaw.py unchanged; Codex WP4 r3 P3-R3-2)
        try:
            obslaw.BankArtifact(a.bank, allow_synthetic=bool(getattr(a, "allow_synthetic_bank", False)))
            what = f"the observation tables {a.obs_tables}"
        except RecursionError:
            what = f"the bank artifact {a.bank}"
        except (ValueError, OSError):
            what = f"the bank artifact {a.bank} or its observation tables {a.obs_tables}"
        raise SystemExit(f"--obs-model bank: {what} is {DEEP}") from None
    return obs


def observation_model(a, obs=None):
    """The configuration's observation_model record (A_design_v5 4.1). Planning: {mode, noise_source, accepting false,
    label}. Bank: the loaded model's identity (obslaw.BankObservationModel.identity: the bank artifact's and the
    tables' sha256, the tables' identity, support and capture laws, age clock, ceiling, cohort, D8, inputs, the bank
    engine, parameters, receipt, the fitter's three hooks, the obslaw / noisescale sources) with mode, noise_source,
    the D9 sha256 and the streams added. Its canonical sha256 is every result's observation_model_sha256."""
    mode = getattr(a, "obs_model", None) or "planning"
    if mode == "planning":
        return {"mode": "planning", "noise_source": NOISE_SOURCE["planning"], "accepting": False,
                "label": PLANNING_LABEL}
    if obs is None:
        raise SystemExit("bank mode: the observation model is not loaded")
    # (PROPOSED READING S4: "inputs" is the artifact's complete inputs block, as obslaw's identity records it --
    #  v5 4.1's four registered hashes, provenance and validation report, and the design's canonical sha256 beside
    #  its file sha)
    om = dict(obs.identity())
    om.update(mode="bank", noise_source=NOISE_SOURCE["bank"], accepting=bool(obs.accepting),
              amendment_D9_sha256=D9_SHA256, streams=dict(STREAMS))
    return om


def run_config(a, graph, obs=None):
    """Everything a recovery result depends on (resume and summary refuse to mix two of them): the graph's
    identity (edges and metadata), the reference assignment (its sha256 and actual times, or the assumed
    REF_TIMES), the resolved arguments, the sha256 of every computational source (TOOLS: the seed
    derivation in rqlib and the count density's numerics in noisebank included) and the observation model
    (observation_model: in bank mode the bank artifact's and the tables' bytes by sha256, so a changed byte is
    another configuration and refuses resume; A_design_v5 4.1, 4.3)."""
    tools = {f: rqlib.sha256_file(os.path.join(HERE, f)) for f in TOOLS if os.path.isfile(os.path.join(HERE, f))}
    rp = getattr(a, "references", None)
    if rp:
        times, sha = reference_times(rp)
        refs = {"sha256": sha, "times": {g: [times[g][k] for k in range(8)] for g in ("RQ", "RP")},
                "sentinels": {g: [times["sentinels"][g][k] for k in range(8)] for g in ("RQ", "RP")}}
    else:
        refs = {"assumed": list(REF_TIMES)}
    return {"schema": CONFIG_SCHEMA, "graph_edges_sha256": graph["edges_sha256"], "graph": graph,
            "namespace": a.namespace, "references": refs, "fitter": a.fitter, "options": a.options, "ranks": a.ranks,
            "lambdas": a.lambdas, "iters": a.iters, "ab_cap": a.ab_cap, "start": a.start, "basis": a.basis,
            "embedding": a.embedding, "center": a.center, "tools_sha256": tools, "scenarios": SCENARIOS,
            "defaults": DEFAULTS, "lambda_grid": list(REGISTERED_LAMBDAS), "bootstrap": "crossed/1", "score": SCORE,
            "min_test_worlds": MIN_TEST_WORLDS, "observation_model": observation_model(a, obs)}


def graph_meta(path):
    return graph_identity(_read_json_at(os.path.join(os.path.dirname(os.path.abspath(path)), "graph.meta.json")))


def load_data(path, refs_path=None):
    key = (path, refs_path)
    if key not in _DATA:
        _DATA[key] = Data(graphlib.load(path), reference_times(refs_path)[0] if refs_path else None)
    return _DATA[key]


def one(a):
    resolve(a)
    if a.scenario not in SCENARIOS:
        raise SystemExit(f"--scenario {a.scenario}: not a registered scenario")
    bank_refusals(a, [a.scenario])
    obs = load_model(a, (scenario_gamma(a.scenario),))      # (once per worker, validated: A_design_v5 3.2, 3.5)
    D = load_data(a.graph, getattr(a, "references", None))
    sc = SCENARIOS[a.scenario]
    seed = rqlib.derive_seed(a.namespace, "recovery", a.scenario, a.rep)
    t0 = time.time()
    data = simulate(D, sc, seed, obs=obs)
    gid = graph_identity(D.g)
    cfg = run_config(a, gid, obs)
    om = cfg["observation_model"]
    res = {"schema": RESULT_SCHEMA, "scenario": a.scenario, "rep": a.rep, "seed": seed,
           "settings": data["settings"], "interaction_scale": data["c"], "energy_check": data["energy"],
           "graph_edges_sha256": gid["edges_sha256"], "graph": gid, "options": {},
           "config_sha256": rqlib.canonical_sha(cfg),
           # (A_design_v5 3.2 / 4.1: every result, numerical ones included, planning ones labelled non-accepting)
           "noise_source": om["noise_source"], "accepting": om["accepting"],
           "observation_model_sha256": rqlib.canonical_sha(om), "noiseless": bool(sc.get("noiseless")),
           "observations": observation_hashes(data)}
    check_observations(a.scenario, res, om["mode"] == "bank", a.out)
    cap = a.ab_cap if a.ab_cap >= 0 else None
    res["fitter"] = a.fitter
    res["start"] = a.start
    lams = [float(x) for x in a.lambdas.split(",")]
    reg = dict(basis=a.basis, embedding=a.embedding, center=a.center)
    for opt in a.options.split(","):
        if sc.get("noiseless") and opt == "fwd":       # (the forward procedure is a noisy-data selection)
            res["options"][opt] = {"procedure": "forward", "available": False,
                                   "reason": "the forward-time procedure is not defined for a noiseless scenario"}
        elif sc.get("noiseless"):
            res["options"][opt] = numerical(D, data, opt, sc["rank"], a.iters, seed, ab_cap=cap, fitter=a.fitter, **reg)
        elif opt == "fwd":
            res["options"][opt] = forward_procedure(D, data, a.ranks, lams, a.iters, seed, ab_cap=cap,
                                                    fitter=a.fitter, start=a.start, **reg)
        else:
            res["options"][opt] = procedure(D, data, opt, a.ranks, lams, a.iters, seed, ab_cap=cap, fitter=a.fitter,
                                            start=a.start, **reg)
    res["reference_support"] = D.forward["reference_support"]            # (#71 r2 P2: persisted)
    res["seconds"] = round(time.time() - t0, 1)
    rqlib.write_json_durable(a.out, res)
    return 0


def _result_files(d):
    """The result files of a run directory: every .json but config.json and summary*."""
    return sorted(f for f in os.listdir(d) if f.endswith(".json") and f != "config.json" and not f.startswith("summary"))


def check_result(d, f, r, want, namespace, refusing, cfg=None):
    """A kept result's identity (Codex #66 r1 P2-9): its name is exactly <scenario>.<rep:03d>.json of its
    recorded scenario and rep, the scenario is registered, the seed is the derived seed of (namespace,
    scenario, rep), and it carries the run's configuration -> (scenario, rep). With the configuration cfg (A_design_v5
    3.2, 4.3): its noise_source, accepting and observation_model_sha256 are the configuration's, and its observations
    record is its mode's (the absent-cnt record exactly for a noiseless scenario: check_observations)."""
    if not isinstance(r, dict) or r.get("schema") != RESULT_SCHEMA:
        raise SystemExit(f"{d}/{f}: not a recovery result: {refusing}")
    if r.get("config_sha256") != want:
        raise SystemExit(f"{f}: a result of another configuration in {d}: {refusing}")
    sc, rep = r.get("scenario"), r.get("rep")
    if sc not in SCENARIOS or not isinstance(rep, int) or rep < 0 or f != f"{sc}.{rep:03d}.json":
        raise SystemExit(f"{d}/{f}: its identity ({sc!r}, {rep!r}) does not match its file name: {refusing}")
    if r.get("seed") != rqlib.derive_seed(namespace, "recovery", sc, rep):
        raise SystemExit(f"{d}/{f}: its seed is not the derived seed of ({namespace}, {sc}, {rep}): {refusing}")
    if cfg is not None:
        om = cfg.get("observation_model")
        if not isinstance(om, dict) or om.get("mode") not in OBS_MODELS:
            raise SystemExit(f"{d}: a configuration without an observation model (an older recovery.py's): {refusing}")
        if (r.get("noise_source"), r.get("accepting"), r.get("observation_model_sha256")) != \
                (om["noise_source"], om["accepting"], rqlib.canonical_sha(om)):
            raise SystemExit(f"{d}/{f}: a result of another noise source or observation model (noise_source "
                             f"{r.get('noise_source')!r}, the configuration's {om['noise_source']!r}): {refusing}")
        try:
            check_observations(sc, r, om["mode"] == "bank", f"{d}/{f}")
        except ValueError as e:
            raise SystemExit(f"{e}: {refusing}")
    return sc, rep


def prepare_run(a, obs=None):
    """Resolve the arguments, write the run's config.json (or check it against an existing one) and check every
    kept result's configuration and identity -> the configuration's sha256. Bank mode: the model is loaded (once,
    validated; obs: already loaded by run) and bound by the configuration, so any changed bank or table byte is
    another configuration and refuses the resume (A_design_v5 3.2, 4.3)."""
    resolve(a)
    names = [n for n in scenario_names(a) if n in SCENARIOS]
    bank_refusals(a, names)
    if obs is None:
        obs = load_model(a, sorted({scenario_gamma(n) for n in names}) or (1.0,))
    os.makedirs(a.out, exist_ok=True)
    cfg = rqlib.canonical(run_config(a, graph_meta(a.graph), obs))
    cp = os.path.join(a.out, "config.json")
    if os.path.isfile(cp):
        if rqlib.read_bytes(cp) != cfg:
            have = rqlib.read_json(cp)
            diff = sorted(k for k in set(have) | set(json.loads(cfg)) if have.get(k) != json.loads(cfg).get(k))
            raise SystemExit(f"{a.out} holds a recovery run of another configuration ({diff}): refusing to resume")
    else:
        rqlib.write_durable(cp, cfg)
    want = rqlib.canonical_sha(json.loads(cfg))
    for f in _result_files(a.out):
        check_result(a.out, f, rqlib.read_json(os.path.join(a.out, f)), want, a.namespace, "refusing to resume",
                     json.loads(cfg))
    return want


def run(a):
    resolve(a)
    names = scenario_names(a)
    bank_refusals(a, names)                 # (before any file or worker: T7-5)
    obs = load_model(a, sorted({scenario_gamma(n) for n in names if n in SCENARIOS}) or (1.0,))
    prepare_run(a, obs=obs)
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        raise SystemExit(f"unknown scenarios {unknown}")
    jobs = []
    for sc in names:
        reps = 1 if sc in SETS["numerical"] else a.reps if (sc in SETS["main"] or a.scenarios) else max(2, a.reps // 2)
        for rep in range(reps):
            f = os.path.join(a.out, f"{sc}.{rep:03d}.json")
            if not os.path.exists(f):
                jobs.append((sc, rep, f))
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    running, failed = [], 0
    print(f"{len(jobs)} datasets to run, {a.jobs} at a time", flush=True)
    while jobs or running:
        while jobs and len(running) < a.jobs:
            sc, rep, f = jobs.pop(0)
            cmd = [sys.executable, os.path.abspath(__file__), "one", "--graph", a.graph, "--scenario", sc,
                   "--rep", str(rep), "--out", f, "--options", a.options, "--ranks", str(a.ranks),
                   "--lambdas", a.lambdas, "--iters", str(a.iters), "--namespace", a.namespace,
                   "--ab-cap", str(a.ab_cap), "--fitter", a.fitter, "--start", a.start, "--basis", str(a.basis),
                   "--embedding", a.embedding, "--center", a.center] + \
                (["--references", a.references] if getattr(a, "references", None) else []) + \
                (["--obs-model", "bank", "--bank", a.bank, "--obs-tables", a.obs_tables] +       # (A_design_v5 3.2)
                 (["--allow-synthetic-bank"] if getattr(a, "allow_synthetic_bank", False) else [])
                 if a.obs_model == "bank" else [])
            running.append((subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL), sc, rep))
        time.sleep(0.5)
        for item in list(running):
            rc = item[0].poll()
            if rc is not None:
                running.remove(item)
                failed += rc != 0
                print(f"{item[1]}.{item[2]:03d}: {'ok' if rc == 0 else f'FAILED rc={rc}'}", flush=True)
    return 1 if failed else 0


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def _mean(xs):
    v = [x for x in xs if x is not None]
    return float(np.mean(v)) if v else None


def _median(xs):
    v = [x for x in xs if x is not None]
    return float(np.median(v)) if v else None


def _counts(xs):
    out = {}
    for x in xs:
        out[str(x)] = out.get(str(x), 0) + 1
    return dict(sorted(out.items()))


def _decided(o):
    """A result that DECIDED (decision.available, absent: yes). An unavailable one (the procedure undefined on the
    masked sets, fewer than two test worlds, or a finite but UNRESOLVED count score in its selection or comparison:
    Codex #66 r5/r6 P2-1) is counted by itself and kept out of every numeric aggregate and rank histogram of
    summarize(); for ACCEPTANCE it is still an unsuccessful dataset (_rates)."""
    return o.get("available") is not False and bool((o.get("decision") or {"available": True})["available"])


def _ratio(k, n):
    return round(k / n, 3) if n else None


def _rates(k, total, decided):
    """A success count on its two denominators (Codex #66 r7 P2-1). "rate" / "wilson95" are the ACCEPTANCE rate,
    successes / datasets: the registered §6.5 criterion evaluates the full selection-and-prediction procedure over
    every noise realization with no exemption for unavailable results, so an unavailable dataset counts as an
    unsuccessful one (and keeps its own status in the availability counts). "conditional" is successes / decided,
    descriptive only: it is NOT the acceptance rate (a conditional criterion would need a frozen amendment)."""
    return {"rate": _ratio(k, total), "wilson95": wilson(k, total),
            "rate_basis": "successes / datasets: the acceptance rate (an unavailable dataset is unsuccessful)",
            "decided": decided, "unavailable": total - decided, "decided_fraction": _ratio(decided, total),
            "conditional": {"basis": "successes / decided: conditional on availability, descriptive, NOT the "
                                     "acceptance rate", "rate": _ratio(k, decided), "wilson95": wilson(k, decided)}}


def summarize(d):
    """The run directory's cells. Refused (Codex #66 r1 P2-9): a directory without its config.json, a result
    of another configuration, a result whose name, recorded identity and derived seed disagree, and a second
    result of one (scenario, rep)."""
    cp = os.path.join(d, "config.json")
    if not os.path.isfile(cp):
        raise SystemExit(f"{d}: no config.json (a run directory is written by run / prepare_run): refusing a summary")
    cfg = _read_json_at(cp)
    want = rqlib.canonical_sha(cfg)
    om = cfg.get("observation_model")
    if not isinstance(om, dict) or om.get("mode") not in OBS_MODELS:
        raise SystemExit(f"{d}: a configuration without an observation model (an older recovery.py's): refusing a "
                         "summary")
    rows, seen, sups = {}, {}, []
    for f in _result_files(d):
        r = _read_json_at(os.path.join(d, f))
        key = check_result(d, f, r, want, cfg.get("namespace"), "refusing a mixed summary", cfg)
        if key in seen or r["seed"] in {s for _, s in seen.values()}:
            raise SystemExit(f"{d}: {f} duplicates {seen.get(key, ('another result',))[0]}: refusing a summary")
        seen[key] = (f, r["seed"])
        sups.append(rqlib.canonical(r.get("reference_support")))
        for opt, o in r["options"].items():
            rows.setdefault((r["scenario"], opt), []).append(o)
    out = {"schema": "finfolk.redqueen.recoverysummary/2", "config_sha256": want, "datasets": len(seen), "cells": [],
           # (A_design_v5 3.2, 3.7: one noise source per summary; a planning summary is never gate-2 evidence)
           "noise_source": om["noise_source"], "accepting": om["accepting"],
           "scope": BANK_SCOPE if om["mode"] == "bank" else PLANNING_LABEL}
    if om["mode"] == "planning":
        out["label"] = PLANNING_LABEL
    if len(set(sups)) > 1:
        raise SystemExit(f"{d}: results with different reference support (another reference assignment?)")
    out["reference_support"] = json.loads(sups[0]) if sups else None
    for (sc, opt), lst in sorted(rows.items()):
        if "success" in lst[0]:
            # (Codex #66 r6 P2-1: the aggregates and rank histograms read the DECIDED results only; the others are
            #  counted by themselves: decision_unavailable, and unresolved_decisions for those whose count integral
            #  left a score unresolved)
            dec = [o for o in lst if _decided(o)]
            k = sum(bool(o.get("success")) for o in lst)
            sel = {}
            for o in dec:
                sel[o["selected"]["rank"]] = sel.get(o["selected"]["rank"], 0) + 1
            # (Codex #66 r7 P2-2: the primary result has its OWN availability -- it reads only the validation scores of
            #  its rank <= PRIMARY_RANKS candidates -- so it is aggregated over EVERY dataset, not over the full
            #  selection's decided ones; its counts stay even when none decides)
            prim_all = [o["selected_primary"] for o in lst if "selected_primary" in o]       # (#66: the {0,1,2} primary)
            prim = [p for p in prim_all if p.get("available", True)]
            kp = sum(bool(p["success"]) for p in prim_all)
            selp = {}
            for p in prim:
                selp[p["rank"]] = selp.get(p["rank"], 0) + 1
            gd = [o["gauss_diagnostic"] for o in dec if o.get("gauss_diagnostic")]
            cell = {"scenario": sc, "option": opt, "datasets": len(lst), "successes": k,
                    **_rates(k, len(lst), len(dec)),
                    "selected_ranks": dict(sorted(sel.items())),
                    "positive_rank_selected": sum(o["selected"]["rank"] > 0 for o in dec),
                    "decision_unavailable": len(lst) - len(dec),
                    "unresolved_decisions": sum(1 for o in lst
                                                if (o.get("decision") or {}).get("integration_unresolved")),
                    "unresolved_selections": sum(1 for o in lst if (o.get("decision") or {}).get("selection_unresolved")),
                    "integration_unresolved": sum(int((c.get("integration") or {}).get(s, {}).get(k, 0))
                                                  for o in lst for c in o.get("candidates", ())
                                                  for s in ("validation", "test")
                                                  for k in ("grid_unresolved", "eps_unresolved")),
                    "primary": ({"ranks": prim_all[0]["ranks"], "datasets": len(prim_all), "successes": kp,
                                 **_rates(kp, len(prim_all), len(prim)),
                                 "selected_ranks": dict(sorted(selp.items())),
                                 "positive_rank_selected": sum(p["rank"] > 0 for p in prim),
                                 "median_test_lb": _median(p["test_lb"] for p in prim)}
                                if prim_all else None),
                    "start": lst[0].get("start"),
                    # (the winning start of the SELECTED candidate: over every decided dataset, a rank-0 selection
                    #  counted under its single warm fit, the reg5 table's convention; and over rank > 0 only)
                    "selected_start": _counts(o["selected"].get("start") for o in dec),
                    "selected_start_positive": _counts(o["selected"].get("start") for o in dec
                                                       if o["selected"]["rank"] > 0),
                    "mean_test_improvement": _mean(o["test_improvement"] for o in dec),
                    "mean_test_lb": _mean(o["test_lb"] for o in dec),
                    "median_test_lb": _median(o["test_lb"] for o in dec),
                    "gauss_diagnostic": ({"successes": sum(g["success"] for g in gd),
                                          "selected_ranks": _counts(g["selected"]["rank"] for g in gd),
                                          "median_test_lb": _median(g["test_lb"] for g in gd)} if gd else None),
                    "fit_pairs": lst[0]["fit_pairs"],
                    "classes": {k: {f: float(np.mean([o["classes"][k][f] for o in dec]))
                                    for f in ("rmse_selected", "rmse_rank0", "interaction_sd")}
                                for k in ((dec[0].get("classes") or {}) if dec else {})}}
            if lst[0].get("procedure") == "forward":       # (both branches: the top level is the transfer)
                cell["branches"] = {}
                for b in ("forward_transfer", "intersection"):
                    av = [o[b] for o in lst if (o.get(b) or {}).get("available")]
                    kb = sum(x["success"] for x in av)
                    cell["branches"][b] = {"datasets": len(lst), "available": len(av), "successes": kb,
                                           "integration_unresolved": sum(
                                               1 for o in lst if (o.get(b) or {}).get("integration_unresolved")),
                                           **_rates(kb, len(lst), len(av)),
                                           "mean_test_improvement": _mean(x["test_improvement"] for x in av),
                                           "mean_test_lb": _mean(x["test_lb"] for x in av)}
            out["cells"].append(cell)
        elif "relative" not in lst[0]:                       # (unavailable, e.g. fwd on a noiseless scenario)
            out["cells"].append({"scenario": sc, "option": opt, "datasets": len(lst), "available": False,
                                 "reasons": sorted({o.get("reason", "") for o in lst})})
        else:
            out["cells"].append({"scenario": sc, "option": opt, "datasets": len(lst),
                                 "relative_test_rmse": [o["relative"] for o in lst],
                                 "relative_test_rmse_identified": [o.get("relative_identified") for o in lst],
                                 "median_abs_relative": [o.get("median_abs_relative") for o in lst],
                                 "underdetermined_targets": [o.get("underdetermined_targets") for o in lst],
                                 "relative_by_class": [o.get("relative_by_class") for o in lst]})
    return out


def conditioning(D, rank, option="a", seed=0):
    """The conditioning of every population's rank-r placement design from its fitting pairs: rows
    [-1, v_j] for a prey (the opponents' standard-normal embeddings; [1, u_i] for a predator) ->
    per population class, the condition-number quantiles and the share above 30 or singular."""
    rng = np.random.default_rng(seed)
    idx = D.forward["fit"] if option == "fwd" else D.fit[option]       # (#71 r3 P2: the forward panel too)
    out = {}
    for guild, me, other, n_me, n_other, held, wv, ref in (
            ("prey", D.qi, D.pj, D.nQ, D.nP, D.qheld, D.qw, D.qref),
            ("predators", D.pj, D.qi, D.nP, D.nQ, D.pheld, D.pw, D.pref)):
        emb = rng.normal(size=(n_other, rank))
        X = np.column_stack([np.ones(len(idx)), emb[other[idx]]])
        d = rank + 1
        A = np.zeros((n_me, d, d))
        for p in range(d):
            for q in range(d):
                A[:, p, q] = np.bincount(me[idx], weights=X[:, p] * X[:, q], minlength=n_me)
        ev = np.linalg.eigvalsh(A)
        cond = np.sqrt(np.where(ev[:, 0] > 1e-9, ev[:, -1] / np.maximum(ev[:, 0], 1e-300), np.inf))
        split = np.where(wv >= 0, D.wsplit[np.maximum(wv, 0)], "ref")
        kind = np.where(ref, "reference", np.where(split != "train", "world-" + split,
                                                   np.where(held != "train", "snapshot-" + held, "train")))
        for k in np.unique(kind):
            c = cond[kind == k]
            fin = c[np.isfinite(c)]
            out[f"{guild}:{k}"] = {"n": int(len(c)), "singular": int((~np.isfinite(c)).sum()),
                                   "above_30": int((c > 30).sum()),
                                   "median": float(np.median(fin)) if len(fin) else None,
                                   "p90": float(np.quantile(fin, 0.9)) if len(fin) else None,
                                   "max": float(fin.max()) if len(fin) else None}
    return out


def bench(a):
    D = load_data(a.graph, getattr(a, "references", None))
    t0 = time.time()
    data = simulate(D, SCENARIOS["r2_034"], 1)
    t1 = time.time()
    iters = a.iters or 40
    m = fit(D, D.fit["a"], data["zbar"], 2, 0.1, False, iters, 1)
    t2 = time.time()
    print(json.dumps({"pairs": len(D.qi), "simulate_s": round(t1 - t0, 2), "fit_rank2_s": round(t2 - t1, 2),
                      "iters": iters, "mu": m["mu"]}))
    return 0


# ------------------------------------------------------------------ bank mode's commands (A_design_v5 3.2, 3.6, 3.8)
def _publish_new(tmp, path, sha):
    """Publish the fsync'd, verified private file tmp (sha256 sha) at path WITHOUT REPLACEMENT (Codex WP4 P2-WP4-4):
    os.link fails if any file is at path, so a command that loses a race to another publisher refuses and the
    winner's bytes stay intact; the directory is fsync'd after the link. Every publication OSError is a contextual
    refusal (Codex WP4 r2 P3-R2-1): a failed link (an existing file, or a filesystem refusing hard links) published
    nothing; a failed directory fsync AFTER the link leaves the verified file published but its directory entry
    possibly not durable, and says so. The caller removes its own tmp."""
    try:
        os.link(tmp, path)
    except FileExistsError:
        try:
            same = rqlib.read_bytes(path) == rqlib.read_bytes(tmp)
        except OSError:
            same = None
        raise SystemExit(f"obs-tables: {path} was published by another command while these tables were built ("
                         f"{'the same' if same else 'other' if same is False else 'unreadable'} bytes): refused, the "
                         "existing file is left intact (a published table file is never replaced)")
    except OSError as e:
        raise SystemExit(f"obs-tables: publishing {path} by a hard link failed ({type(e).__name__}: {e}): refused, "
                         "NOTHING was published (this command's temporary file is removed; an existing file is never "
                         "replaced)")
    try:
        rqlib.fsync_dir(os.path.dirname(os.path.abspath(path)))
    except OSError as e:
        raise SystemExit(f"obs-tables: {path} IS PUBLISHED (the verified tables, sha256 {sha}), but the directory "
                         f"fsync after the link failed ({type(e).__name__}: {e}): its directory entry may not be "
                         "durable; refused -- check the file's sha256 before relying on it")


def obs_tables(a):
    """`obs-tables` (A_design_v5 1.7, 1.7b, 7 step 7): from a validated bank/3 artifact, the location tables of every
    channel at every noise multiplier and the fitter table (obslaw.build_obs_tables: built once, before the freeze;
    workers only load them). The completed bytes are written to a private temporary file beside --out and fsync'd,
    verified there by loading them through the model with both file hashes configured, and only then published at
    --out with no replacement (_publish_new: an existing --out, including one another command published meanwhile,
    is never overwritten, and that command's bytes are left intact; only this command's own temporary file is
    removed) -> prints the identity and the certification records."""
    import uuid

    import obslaw
    try:
        gammas = sorted({float(x) for x in a.noise_scales.split(",")})
    except ValueError:
        raise SystemExit(f"--noise-scales {a.noise_scales}: a comma list of numbers")
    if not gammas or any(not (math.isfinite(g) and g > 0) for g in gammas):
        raise SystemExit(f"--noise-scales {a.noise_scales}: positive finite noise multipliers")
    if os.path.lexists(a.out):
        raise SystemExit(f"{a.out} exists: refusing to overwrite (the tables are built once, before the freeze)")
    try:
        bank = obslaw.BankArtifact(a.bank, allow_synthetic=a.allow_synthetic_bank)
        raw = obslaw.build_obs_tables(bank, gammas).to_bytes()
    except (ValueError, OSError) as e:
        raise SystemExit(f"obs-tables: {e} (refused; nothing written)")
    sha = rqlib.sha256_bytes(raw)
    tmp = f"{os.path.abspath(a.out)}.tmp.{os.getpid()}.{uuid.uuid4().hex[:16]}"
    made = False
    try:
        try:
            with open(tmp, "xb") as f:
                made = True
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            obs = obslaw.BankObservationModel(a.bank, tmp, bank_sha256=bank.sha256, tables_sha256=sha, gammas=gammas,
                                              allow_synthetic_bank=a.allow_synthetic_bank)
        except (ValueError, OSError) as e:
            raise SystemExit(f"obs-tables: the built tables do not write or load back ({e}): refused, nothing "
                             "published")
        _publish_new(tmp, a.out, sha)
    finally:
        if made:
            os.unlink(tmp)
    rep = {"obs_tables_sha256": sha, "obs_tables_content_sha256": obs.tables.stored_content_sha256,
           "bank_artifact_sha256": bank.sha256, "noise_scales": gammas, "accepting": obs.accepting,
           "location": [{"channel": ch, "gamma": g, "nodes": int(len(t.x)), "h": t.identity["h"], "record": t.record}
                        for (ch, g), t in sorted(obs.tables.location.items(),
                                                 key=lambda kv: (obslaw.CHANNELS.index(kv[0][0]), kv[0][1]))],
           "fitter": {"nodes": int(len(obs.tables.fitter.x)), "record": obs.tables.fitter.record}}
    print(json.dumps(rep, indent=1, sort_keys=True))
    return 0


DEEP = "nested deeper than the parser's recursion limit"


def _read_json_at(path):
    """rqlib.read_json with a parser / serializer recursion failure named (Codex WP4 r3 P3-R3-2) -> the document;
    ValueError naming path otherwise."""
    try:
        return rqlib.read_json(path)
    except RecursionError:
        raise ValueError(f"{path}: {DEEP}") from None


def _extra_call(fn, d, *args):
    """A recovery_extra reader of directory d (its frozen plan, results, summary; recovery_extra.py is accepted and
    unchanged) with a recursion failure named -> fn's result; ValueError naming d otherwise."""
    try:
        return fn(d, *args)
    except RecursionError:
        raise ValueError(f"{d}: its frozen plan, a result or an input recovery_extra re-reads is {DEEP}") from None


def _dir_kind(d):
    if os.path.isfile(os.path.join(d, "config.json")):
        return "legacy"
    if os.path.isfile(os.path.join(d, "plan.json")):
        return "extra"
    raise SystemExit(f"{d}: neither a recovery.py run directory (config.json) nor a recovery_extra.py one (plan.json)")


def _legacy_results(d):
    """A legacy run directory's results, each identity-checked against its config.json -> [(where, scenario, rep,
    result)]; a document nested deeper than the parser's recursion limit is a ValueError naming it."""
    cfg = _read_json_at(os.path.join(d, "config.json"))
    try:
        want = rqlib.canonical_sha(cfg)
    except RecursionError:
        raise ValueError(f"{d}/config.json: {DEEP}") from None
    out = []
    for f in _result_files(d):
        r = _read_json_at(os.path.join(d, f))
        sc, rep = check_result(d, f, r, want, cfg.get("namespace"), "refused", cfg)
        out.append((f"{d}/{f}", sc, rep, r))
    return out


def _extra_results(d):
    """A recovery_extra.py directory's results (its frozen plan and result identities verified by recovery_extra's
    own readers) -> [(where, scenario, rep, result)]."""
    import recovery_extra as X
    plan = _extra_call(X.read_frozen, d)
    return [(f"{d}/results/{n}", r["scenario"], r["rep"], r)
            for n, r in sorted(_extra_call(X.read_results, d, plan).items())]


def _bank_directory(d):
    """pairing's input rule (A_design_v5 3.6, 3.7; Codex WP4 P2-WP4-5): a directory's configuration (legacy:
    config.json's observation_model) or frozen plan (extra: plan.json) must be bank mode, checked BEFORE any result
    is read, so a planning directory is refused whether or not it holds results -> its kind; SystemExit naming the
    directory otherwise (an unreadable configuration or plan included)."""
    kind = _dir_kind(d)
    try:
        if kind == "legacy":
            cfg = _read_json_at(os.path.join(d, "config.json"))
            om = cfg.get("observation_model") if isinstance(cfg, dict) else None
            src = om.get("noise_source") if isinstance(om, dict) else None
            bank = isinstance(om, dict) and om.get("mode") == "bank" and src == NOISE_SOURCE["bank"]
        else:
            import recovery_extra as X
            src = _extra_call(X.read_frozen, d).get("noise_source")
            bank = src == NOISE_SOURCE["bank"]
    except (OSError, ValueError) as e:
        raise SystemExit(f"pairing: {d}: its {'configuration' if kind == 'legacy' else 'frozen plan'} cannot be read "
                         f"({e}): refused")
    if not bank:
        raise SystemExit(f"pairing: {d} is not a bank-mode {'run directory' if kind == 'legacy' else 'plan'} "
                         f"(noise_source {src!r}): planning input is refused (A_design_v5 3.7), with or without "
                         "results")
    return kind


def pairing(dirs):
    """`pairing` (A_design_v5 3.6): every (scenario, rep) present in two or more results of the given directories
    (legacy run directories and recovery_extra directories, every case of the latter) must carry identical
    observations hashes; a directory whose configuration or plan is not bank mode is refused before any of its
    results is read (v5 3.7: an empty or zero-rep planning directory too), so is a planning-mode result, and so is any
    mismatch (SystemExit naming both results) -> {directories, datasets, comparisons}."""
    if not dirs:
        raise SystemExit("pairing: no directories")
    kinds = [_bank_directory(d) for d in dirs]
    seen, compared = {}, 0
    for d, kind in zip(dirs, kinds):
        try:
            rows = _legacy_results(d) if kind == "legacy" else _extra_results(d)
        except (OSError, ValueError) as e:
            raise SystemExit(f"pairing: {d}: a result cannot be read ({e}): refused")
        for where, sc, rep, r in rows:
            if r.get("noise_source") != NOISE_SOURCE["bank"]:
                raise SystemExit(f"pairing: {where} is not a bank-mode result (noise_source {r.get('noise_source')!r}):"
                                 " planning input is refused (A_design_v5 3.7)")
            ob = r.get("observations")
            if not isinstance(ob, dict) or not ob:
                raise SystemExit(f"pairing: {where} records no observations")
            try:
                c = rqlib.canonical(ob)
            except RecursionError:
                raise SystemExit(f"pairing: {where}: its observations record is {DEEP}: refused") from None
            if (sc, rep) in seen:
                compared += 1
                if seen[(sc, rep)][0] != c:
                    raise SystemExit(f"pairing: ({sc}, {rep}) has different observations in {seen[(sc, rep)][1]} and "
                                     f"{where} (A_design_v5 3.6): refused")
            else:
                seen[(sc, rep)] = (c, where)
    return {"directories": list(dirs), "datasets": len(seen), "comparisons": compared, "result": "paired"}


# The schedule document is A_design_v5 clarification 4 F1's (frozen 87053a80..., WP4 stop S1): ONE JSON object
# with exactly {schema, observation_model_sha256 (the one model every configuration, plan and result carries),
# inputs: exactly {graph, references (a path or null), bank, obs_tables} (what the read-only prepare_run / verified
# logic re-derives from), directories: a non-empty list of entries with exactly v5 3.8's fields}, reps a positive
# count (reps 0..reps-1), every path resolving relative to the schedule file's directory (an absolute path, which
# would not, is refused). Acceptance completeness (WP4 stop S2, ruled by Codex and clarification 4) is the frozen C2
# matrix of CRITERION C2-C4 (rec_C_v2 b8a3323e..., unchanged by v5 6.1 but for the namespace): its roles and blocks
# (schedule_gaps), AND every scheduled directory's bound settings (bound_settings_gaps: C2's registered settings for
# every noisy fit, exactly one directory per sensitivity variant, clarification 4 F3's settings for the numerical and
# extra roles); every acceptance directory in namespace A_NAMESPACE (identity). The guards check (stop S3;
# _guard_violations) checks availability and unresolved-state consistency of every decision, branch and primary
# selection, successful or not, against the candidate and integration records they summarize, and the root guards
# (CRITERION C1, C4, C6). The acceptance-role fit settings (WP4 stops S5 / S6) are clarification 4 F3's (frozen
# 87053a80...): F3_NUMERICAL, F3_EXTRA_FIT and F3_EXTRA_LEGACY below.
SCHEDULE_SCHEMA = "finfolk.redqueen.recoveryschedule/1"
SCHEDULE_KEYS = ("schema", "observation_model_sha256", "inputs", "directories")     # (clarification 4 F1)
SCHEDULE_INPUTS = ("graph", "references", "bank", "obs_tables")
PACKET_SCHEMA = "finfolk.redqueen.recoverypacket/1"
SCHEDULE_ROLES = ("C1-primary", "stress", "numerical", "sensitivity",
                  "extra-interp", "extra-fwd_all", "extra-fwd_early", "extra-attrition")     # (A_design_v5 3.8)
LEGACY_ROLES = frozenset(SCHEDULE_ROLES[:4])
A_NAMESPACE = "rq2026-d8-recovery-A1"                     # (v5 3.8, 4.4; CRITERION C5 as v5 6.1 drafts it)
C1_RULE = {"scenarios": ("r1_034", "r2_034"), "reps": 20, "min_successes": 16, "option": "a"}   # (CRITERION C1)
C1_PRIMARY_CONFIG = {"fitter": "registered", "ranks": 4, "lambdas": "0.01,0.02,0.05,0.2", "iters": 30,
                     "start": "both", "basis": 6, "embedding": "shared", "center": "references",
                     "namespace": A_NAMESPACE}            # (v5 3.8: part of the expected configuration hash)
ATTRITION_CASES = ("biological_at", "biological_after", "technical", "pending_prefix", "pending_attempt", "mixed",
                   "roots0", "roots1", "roots2")
# The frozen C2 matrix (CRITERION C2-C4 of rec_C_v2 b8a3323e..., which A_design_v5 6.1 leaves unchanged but for the
# namespace): role -> the blocks it must schedule; an acceptance schedule must contain every block (v5 3.8), each
# sensitivity block in its own directory (basis4, basis8, separate, train_c).
_MAIN = tuple(SETS["main"])
C2_MATRIX = {
    "C1-primary": ({"scenarios": _MAIN, "reps": 20, "options": ("a", "fwd")},),
    "stress": ({"scenarios": tuple(SETS["stress"]), "reps": 10, "options": ("a", "fwd")},),
    "numerical": ({"scenarios": tuple(SETS["numerical"]), "reps": 1, "options": ("a",)},),
    "sensitivity": ({"scenarios": _MAIN, "reps": 20, "options": ("a", "fwd")},) * 4,
    "extra-interp": ({"cases": ("intact",), "scenarios": _MAIN, "reps": 20, "options": ("interp",)},),
    "extra-fwd_all": ({"cases": ("intact",), "scenarios": _MAIN, "reps": 20, "options": ("fwd_all",)},),
    "extra-fwd_early": ({"cases": ("intact",), "scenarios": _MAIN, "reps": 20, "options": ("fwd_early",)},),
    "extra-attrition": ({"cases": ATTRITION_CASES, "scenarios": ("r0",), "reps": 1,
                         "options": ("a", "interp", "fwd_all", "fwd_early")},),
}
NUMERICAL_FWD = {"procedure": "forward", "available": False,
                 "reason": "the forward-time procedure is not defined for a noiseless scenario"}
ACCEPTED_TEXT = "UNRESOLVED (review required, D8:327)"
# CRITERION C2's settings for every noisy fit ("All noisy fits use ranks 0..4, lambdas .01,.02,.05,.2, 30 sweeps,
# both starts; default basis6/shared/references"), the registered map (the minimal fitter never satisfies a role),
# and C2's four sensitivity variants, each exactly ONE change of the default surface. (v5 3.8; clarification 4)
REGISTERED_FIT = {"fitter": "registered", "ranks": 4, "lambdas": FITTER_DEFAULTS["registered"]["lambdas"],
                  "iters": 30, "start": "both", "ab_cap": -1}
DEFAULT_SURFACE = {"basis": 6, "embedding": "shared", "center": "references"}
SENSITIVITY_VARIANTS = {"basis4": {"basis": 4}, "basis8": {"basis": 8}, "separate": {"embedding": "separate"},
                        "train_c": {"center": "train_c"}}
# Clarification 4 F3 (frozen 87053a80...), acceptance mode only (diagnostic mode permits reduced settings):
#  the numerical role's bound configuration: fitter "registered", basis 6, embedding shared, center references and
#  ab_cap -1, recording ranks 4, lambdas "0.01,0.02,0.05,0.2", iters 30 and start both as binding configuration metadata
#  (the numerical procedure itself -- the scenario's true rank, REG_CONTINUATION, 30 sweeps per step, its initialization
#  sequence, the disabled observation-model hooks -- is unchanged; no numerical RMSE threshold);
F3_NUMERICAL = {"fitter": "registered", "basis": 6, "embedding": "shared", "center": "references", "ab_cap": -1,
                "ranks": 4, "lambdas": "0.01,0.02,0.05,0.2", "iters": 30, "start": "both"}
#  the extra noisy roles (C2's "All noisy fits"): each plan's fit, and its legacy_config's fitter and ab_cap.
F3_EXTRA_FIT = {"ranks": 4, "lambdas": "0.01,0.02,0.05,0.2", "iters": 30, "start": "both", "basis": 6,
                "embedding": "shared", "center": "references"}
F3_EXTRA_LEGACY = {"fitter": "registered", "ab_cap": -1}


class Refused(Exception):
    """A packet refused before any check (exit 2 with the reason; A_design_v5 3.8)."""


def _items(e):
    return {(c, s, r) for c in (e.get("cases") or (None,)) for s in e["scenarios"] for r in range(e["reps"])}


def _schedule_path(p, base, where):
    """A schedule path (clarification 4 F1: resolved relative to the schedule file's directory) -> its absolute
    normalized path; an empty, non-string or absolute path is refused (an absolute one would not resolve relative to
    the schedule's directory)."""
    if not isinstance(p, str) or not p:
        raise Refused(f"{where}: a non-empty path relative to the schedule file's directory")
    if os.path.isabs(p):
        raise Refused(f"{where}: {p!r} is absolute; every schedule path resolves relative to the schedule file's "
                      "directory (clarification 4 F1)")
    return os.path.normpath(os.path.join(base, p))


def _exact_keys(d, keys, where):
    """d must hold exactly keys (clarification 4 F1) -> None, or Refused naming the extra and missing keys."""
    extra, missing = sorted(set(d) - set(keys)), sorted(set(keys) - set(d))
    if extra or missing:
        raise Refused(f"{where} must hold exactly {sorted(keys)} (clarification 4 F1): extra {extra}, missing "
                      f"{missing}")


def _schedule_entries(sched, base):
    """The schedule's structure (both modes; clarification 4 F1: exactly its keys, inputs and per-directory fields,
    reps a positive integer, every path relative to the schedule file's directory) -> [entries with an absolute
    'path'], or Refused naming the defect. Types are checked before any membership test (Codex WP4 P3-WP4-6)."""
    if not isinstance(sched, dict) or sched.get("schema") != SCHEDULE_SCHEMA:
        raise Refused(f"the schedule is not a {SCHEDULE_SCHEMA} document")
    _exact_keys(sched, SCHEDULE_KEYS, "the schedule")
    if not rqlib.is_sha256(sched["observation_model_sha256"]):
        raise Refused("the schedule must bind observation_model_sha256 (64 hex)")
    inp = sched["inputs"]
    if not isinstance(inp, dict):
        raise Refused("the schedule's inputs must be an object")
    _exact_keys(inp, SCHEDULE_INPUTS, "the schedule's inputs")
    for k in SCHEDULE_INPUTS:
        if not (k == "references" and inp[k] is None):
            _schedule_path(inp[k], base, f"inputs.{k}")
    ds = sched["directories"]
    if not isinstance(ds, list) or not ds:
        raise Refused("the schedule names no directory (a packet needs a non-empty schedule)")
    out, paths = [], set()
    for i, e in enumerate(ds):
        where = f"directories[{i}]"
        role = e.get("role") if isinstance(e, dict) else e
        if not isinstance(e, dict) or not isinstance(role, str) or role not in SCHEDULE_ROLES:
            raise Refused(f"{where}: role {role!r} is not one of {SCHEDULE_ROLES}")
        kind = "legacy" if e["role"] in LEGACY_ROLES else "extra"
        keys = {"dir", "kind", "role", "scenarios", "reps", "options"} | (
            {"expected_config_sha256"} if kind == "legacy" else {"cases", "expected_plan_sha256"})
        _exact_keys(e, keys, f"{where} ({e['role']}, a {kind} directory)")
        if e["kind"] != kind:
            raise Refused(f"{where} ({e['role']}): kind {e['kind']!r}, not {kind!r}")
        sc, opts = e["scenarios"], e["options"]
        if not (isinstance(sc, list) and sc and all(isinstance(s, str) and s in SCENARIOS for s in sc)
                and len(set(sc)) == len(sc)):
            raise Refused(f"{where}: scenarios must be distinct registered scenarios")
        if (e["role"] == "numerical") != all(SCENARIOS[s].get("noiseless") for s in sc) or \
                (e["role"] != "numerical" and any(SCENARIOS[s].get("noiseless") for s in sc)):
            raise Refused(f"{where}: the numerical role schedules exactly the noiseless scenarios, the others none")
        if type(e["reps"]) is not int or e["reps"] < 1:
            raise Refused(f"{where}: reps must be an integer >= 1 (reps 0..reps-1)")
        if not (isinstance(opts, list) and opts and all(isinstance(o, str) for o in opts)
                and len(set(opts)) == len(opts)):
            raise Refused(f"{where}: options must be distinct option names")
        if kind == "extra" and not (isinstance(e["cases"], list) and e["cases"] and
                                    all(isinstance(c, str) for c in e["cases"])):
            raise Refused(f"{where}: cases must be a non-empty list of case names")
        sha = e["expected_config_sha256" if kind == "legacy" else "expected_plan_sha256"]
        if not rqlib.is_sha256(sha):
            raise Refused(f"{where}: its expected sha256 must be 64 hex")
        path = _schedule_path(e["dir"], base, f"{where}.dir")
        if path in paths:
            raise Refused(f"{where}: {e['dir']} is scheduled twice")
        paths.add(path)
        out.append(dict(e, path=path))
    return out


def schedule_gaps(entries):
    """Acceptance mode (A_design_v5 3.8): every role of the frozen C2 matrix, exactly one C1-primary directory and
    every block of C2_MATRIX (each (case, scenario, rep) with at least the block's options; a sensitivity block per
    directory) -> the list of gaps (empty: complete)."""
    by = {}
    for e in entries:
        by.setdefault(e["role"], []).append(e)
    gaps = [f"role {r} is not scheduled" for r in SCHEDULE_ROLES if r not in by]
    if len(by.get("C1-primary", ())) != 1:
        gaps.append(f"{len(by.get('C1-primary', ()))} C1-primary directories (exactly one is required)")
    for role, blocks in C2_MATRIX.items():
        ents = by.get(role, [])
        if role == "sensitivity":
            n = sum(_items(blocks[0]) <= _items(e) and set(blocks[0]["options"]) <= set(e["options"]) for e in ents)
            if n < len(blocks):
                gaps.append(f"sensitivity: {n} directories cover the main five x 20 with options a,fwd ({len(blocks)} "
                            "are required: basis4, basis8, separate, train_c)")
            continue
        for b in blocks:
            have = set().union(*[_items(e) for e in ents if set(b["options"]) <= set(e["options"])]) if ents else set()
            miss = sorted(_items(b) - have, key=str)
            if miss:
                gaps.append(f"{role}: {len(miss)} scheduled (case, scenario, rep) missing or without options "
                            f"{list(b['options'])}, e.g. {miss[:3]}")
    return gaps


def _same(v, w):
    return type(v) is type(w) and v == w


def _fit_settings(e):
    """A scheduled directory's fit settings as bound in it: a legacy directory's config.json (fitter, ranks, lambdas,
    iters, start, ab_cap, basis, embedding, center), or an extra directory's frozen plan (plan.json's fit;
    recovery_extra fits with its legacy_config's fitter, the registered map, and no A/B cap)."""
    keys = (*REGISTERED_FIT, *DEFAULT_SURFACE)
    if e["kind"] == "legacy":
        cfg = _read_json_at(os.path.join(e["path"], "config.json"))
        if not isinstance(cfg, dict):
            raise ValueError("config.json is not an object")
        return {k: cfg.get(k) for k in keys}
    import recovery_extra as X
    plan = _extra_call(X.read_frozen, e["path"])
    fit, lc = plan.get("fit"), plan.get("legacy_config")
    if not isinstance(fit, dict) or not isinstance(lc, dict):
        raise ValueError("plan.json has no fit / legacy_config object")
    return {k: (lc.get(k) if k in ("fitter", "ab_cap") else fit.get(k)) for k in keys}


def _role_settings(e):
    """The bound settings an acceptance role requires (CRITERION C2-C4; clarification 4 F3) -> {key: value} over the
    fit keys and, except for a sensitivity (whose surface is one of SENSITIVITY_VARIANTS), the surface keys."""
    if e["role"] == "numerical":
        return dict(F3_NUMERICAL)                             # (F3: the numerical role)
    if e["kind"] == "extra":
        return dict(F3_EXTRA_FIT, **F3_EXTRA_LEGACY)          # (F3: the extra noisy roles, C2's "All noisy fits")
    if e["role"] == "sensitivity":
        return dict(REGISTERED_FIT)                           # (C2; the surface: one variant)
    return dict(REGISTERED_FIT, **DEFAULT_SURFACE)            # (C2: C1-primary, stress)


def bound_settings_gaps(entries):
    """Acceptance mode (CRITERION C2-C4 via A_design_v5 3.8 and clarification 4 F3; Codex WP4 P2-WP4-2), before any
    check: every scheduled directory's BOUND settings (_fit_settings) are its role's (_role_settings) -- C1-primary and
    stress C2's registered noisy-fit settings with the default surface basis 6 / shared / references; numerical
    F3_NUMERICAL; the extra roles F3_EXTRA_FIT and F3_EXTRA_LEGACY; each sensitivity the registered settings with
    exactly one of the four variants, and exactly one directory per variant; every field compared by type and value,
    ab_cap included -> the list of gaps (empty: none). The expected configuration / plan sha256 is checked in addition
    (identity, C1): a hash shows which configuration a directory used, not that it satisfies C2 / F3."""
    gaps, variants = [], {name: [] for name in SENSITIVITY_VARIANTS}
    for e in entries:
        where = f"{e['dir']} ({e['role']})"
        try:
            got = _fit_settings(e)
        except (SystemExit, OSError, ValueError) as ex:
            gaps.append(f"{where}: its bound configuration or plan cannot be read ({ex})")
            continue
        want = _role_settings(e)
        bad = {k: got[k] for k in want if k not in DEFAULT_SURFACE and not _same(got[k], want[k])}
        if bad:
            gaps.append(f"{where}: not the registered fit settings ({bad}; C2: the registered map, ranks 0..4, "
                        "lambdas .01,.02,.05,.2, 30 sweeps, both starts, no A/B cap; clarification 4 F3)")
        surf = {k: got[k] for k in DEFAULT_SURFACE}
        if e["role"] == "sensitivity":
            name = next((n for n, ch in SENSITIVITY_VARIANTS.items()
                         if all(_same(surf[k], v) for k, v in dict(DEFAULT_SURFACE, **ch).items())), None)
            if name is None:
                gaps.append(f"{where}: basis / embedding / center {surf} is none of the four sensitivity variants "
                            f"{sorted(SENSITIVITY_VARIANTS)} (C2: each one change of {DEFAULT_SURFACE})")
            else:
                variants[name].append(e["dir"])
        elif not all(_same(surf[k], want[k]) for k in DEFAULT_SURFACE):
            gaps.append(f"{where}: basis / embedding / center {surf}, not the default {DEFAULT_SURFACE} (C2; "
                        "clarification 4 F3)")
    for name, ds in variants.items():
        if len(ds) != 1:
            gaps.append(f"sensitivity variant {name}: {len(ds)} directories {ds} (C2: exactly one each of "
                        f"{sorted(SENSITIVITY_VARIANTS)})")
    return gaps


def _check(fn):
    try:
        return fn()
    except Refused:
        raise
    except (SystemExit, ValueError, KeyError, TypeError, OSError, OverflowError) as e:
        return {"status": "fail", "reason": f"{type(e).__name__}: {e}"}
    except RecursionError as e:      # (a backstop: the readers name their input; Codex WP4 r3 P3-R3-2)
        return {"status": "fail", "reason": f"RecursionError: an input is {DEEP} ({e})"}


def _rederive_config(e, cfg, inputs, obs, allow_synthetic):
    """The read-only prepare_run logic: the configuration re-derived from the schedule's inputs, the directory's own
    recorded arguments and the CURRENT tools -> its canonical bytes."""
    a = argparse.Namespace(graph=inputs["graph"], namespace=cfg["namespace"], fitter=cfg["fitter"],
                           options=cfg["options"], ranks=cfg["ranks"], lambdas=cfg["lambdas"], iters=cfg["iters"],
                           ab_cap=cfg["ab_cap"], start=cfg["start"], basis=cfg["basis"], embedding=cfg["embedding"],
                           center=cfg["center"], obs_model="bank", bank=inputs["bank"],
                           obs_tables=inputs["obs_tables"], allow_synthetic_bank=allow_synthetic,
                           references=inputs["references"] if "sha256" in (cfg.get("references") or {}) else None)
    resolve(a)
    return rqlib.canonical(run_config(a, graph_meta(a.graph), obs))


def _identity(entries, inputs, obs, om_sha, mode, allow_synthetic):
    """Check 1 (A_design_v5 3.8): every directory's configuration (legacy: the read-only prepare_run logic) or frozen
    plan (extra: recovery_extra's verified logic) verifies and hashes to its scheduled expected sha256; every result
    has noise_source bank_d8 and the scheduled observation_model_sha256; acceptance: the namespace is
    rq2026-d8-recovery-A1 and the C1-primary configuration has the registered settings."""
    import recovery_extra as X
    model_sha = rqlib.canonical_sha(observation_model(argparse.Namespace(obs_model="bank"), obs))
    fails = []
    if model_sha != om_sha:
        fails.append(f"the inputs' observation model hashes to {model_sha}, not the scheduled {om_sha}")
    for e in entries:
        d = e["path"]
        try:
            if e["kind"] == "legacy":
                raw = rqlib.read_bytes(os.path.join(d, "config.json"))
                try:
                    cfg = json.loads(raw)
                except RecursionError:
                    raise ValueError(f"config.json is {DEEP}") from None
                if raw != rqlib.canonical(cfg):
                    raise ValueError("config.json is not canonical JSON")
                if rqlib.canonical_sha(cfg) != e["expected_config_sha256"]:
                    raise ValueError(f"config.json hashes to {rqlib.canonical_sha(cfg)}, not the scheduled "
                                     f"{e['expected_config_sha256']}")
                om = cfg.get("observation_model") or {}
                if om.get("noise_source") != NOISE_SOURCE["bank"]:
                    raise ValueError(f"a {om.get('noise_source')!r} directory: planning input is refused (v5 3.7)")
                if rqlib.canonical_sha(om) != om_sha:
                    raise ValueError("its observation model is not the scheduled one")
                derived = _rederive_config(e, cfg, inputs, obs, allow_synthetic)
                if derived != raw:
                    diff = sorted(k for k in cfg if json.loads(derived).get(k) != cfg[k])
                    raise ValueError(f"the configuration re-derived from the inputs and the current tools differs "
                                     f"({diff})")
                if mode == "acceptance" and cfg["namespace"] != A_NAMESPACE:
                    raise ValueError(f"namespace {cfg['namespace']!r} is not {A_NAMESPACE}")
                if e["role"] == "C1-primary" and mode == "acceptance":
                    bad = {k: cfg.get(k) for k, v in C1_PRIMARY_CONFIG.items() if cfg.get(k) != v}
                    if bad:
                        raise ValueError(f"the C1-primary configuration is not the registered one: {bad}")
                _legacy_results(d)
            else:
                plan = _extra_call(X.read_frozen, d)
                if rqlib.canonical_sha(plan) != e["expected_plan_sha256"]:
                    raise ValueError(f"plan.json hashes to {rqlib.canonical_sha(plan)}, not the scheduled "
                                     f"{e['expected_plan_sha256']}")
                if plan.get("noise_source") != NOISE_SOURCE["bank"]:
                    raise ValueError(f"a {plan.get('noise_source')!r} plan: planning input is refused (v5 3.7; "
                                     "recovery_extra's bank mode, v5 3.4, is WP5's)")
                _extra_call(X.verified, d, inputs["graph"], inputs["references"])
                if mode == "acceptance" and plan.get("namespace") != A_NAMESPACE:
                    raise ValueError(f"namespace {plan.get('namespace')!r} is not {A_NAMESPACE}")
                for n, r in sorted(_extra_call(X.read_results, d, plan).items()):
                    if r.get("noise_source") != NOISE_SOURCE["bank"] or r.get("observation_model_sha256") != om_sha:
                        raise ValueError(f"results/{n}: noise_source / observation_model_sha256 not the scheduled ones")
        except (SystemExit, ValueError, KeyError, TypeError, OSError) as ex:
            fails.append(f"{e['dir']} ({e['role']}): {ex}")
        except RecursionError:       # (a re-serialization of a parsed document: Codex WP4 r3 P3-R3-2)
            fails.append(f"{e['dir']} ({e['role']}): a configuration, plan or result is {DEEP}")
    out = {"status": "fail" if fails else "pass", "directories": len(entries)}
    if fails:
        out.update(reason=" | ".join(fails), failures=fails)
    return out


def _result_path(e, case, sc, rep):
    if e["kind"] == "legacy":
        return os.path.join(e["path"], f"{sc}.{rep:03d}.json")
    return os.path.join(e["path"], "results", f"{case}.{sc}.{rep:03d}.json")


def _completeness(entries):
    """Check 2: every scheduled (scenario, rep) / (case, scenario, rep) result exists with the scheduled options."""
    miss = []
    for e in entries:
        for case, sc, rep in sorted(_items(e), key=str):
            p = _result_path(e, case, sc, rep)
            if not os.path.isfile(p):
                miss.append(f"{e['dir']}: {os.path.basename(p)} missing")
                continue
            try:
                r = _read_json_at(p)
            except (OSError, ValueError) as ex:
                miss.append(f"{e['dir']}: {os.path.basename(p)} unreadable ({ex})")
                continue
            lack = sorted(set(e["options"]) - set(((r.get("options") if isinstance(r, dict) else None) or {})))
            if lack:
                miss.append(f"{e['dir']}: {os.path.basename(p)} lacks options {lack}")
    return {"status": "fail" if miss else "pass", **({"reason": "; ".join(miss[:20]) + (
        f" (and {len(miss) - 20} more)" if len(miss) > 20 else "")} if miss else {}),
        "scheduled": sum(len(_items(e)) for e in entries)}


def _numerical(entries):
    """Check 3 (numerical role, num_r1..num_r4, option a): relative finite, noiseless true, observations.cnt the
    absent record; an fwd entry is the registered not-defined record. No RMSE threshold (RB:291-293)."""
    ents = [e for e in entries if e["role"] == "numerical"]
    if not ents:
        return {"status": "not_evaluated", "reason": "no numerical directory scheduled"}
    bad, rows = [], []
    for e in ents:
        for _, sc, rep in sorted(_items(e), key=str):
            p = _result_path(e, None, sc, rep)
            try:
                r = _read_json_at(p)
            except (OSError, ValueError) as ex:
                bad.append(f"{e['dir']}: {sc}.{rep:03d} unreadable or missing ({ex})")
                continue
            o = (r.get("options") or {}).get("a") or {}
            rel = o.get("relative")
            ok = (_num(rel) is not None and math.isfinite(_num(rel))
                  and r.get("noiseless") is True and (r.get("observations") or {}).get("cnt") == ABSENT_CNT)
            fwd = (r.get("options") or {}).get("fwd")
            if fwd is not None and fwd != NUMERICAL_FWD:
                ok = False
            rows.append({"scenario": sc, "rep": rep, "relative": rel, "ok": bool(ok)})
            if not ok:
                bad.append(f"{e['dir']}: {sc}.{rep:03d} (relative {rel!r}, noiseless {r.get('noiseless')!r}, "
                           f"cnt {(r.get('observations') or {}).get('cnt')!r}, fwd {fwd!r})")
    return {"status": "fail" if bad else "pass", **({"reason": "; ".join(bad)} if bad else {}), "cases": rows}


BRANCHES = ("forward_transfer", "intersection", "world_transfer", "interpolation")


def _unresolved(x):
    """An unresolved record as stored -> its count: None / absent 0, a bool 0 / 1, an int itself, a {phase: count}
    record its sum; anything else 1 (an unreadable unresolved state is never read as resolved)."""
    if x is None:
        return 0
    if isinstance(x, bool):
        return int(x)
    if isinstance(x, int):
        return x
    if isinstance(x, dict):
        return sum(_unresolved(v) for v in x.values())
    return 1


def _roots(*xs):
    return next((x for x in xs if type(x) is int), None)


def _sub(d, *keys):
    """d[k1][k2]... where every level is a dict, else None."""
    for k in keys:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def _grid(*infos):
    """procedure's _flagged over STORED integration records: the summed grid_unresolved flags (absent record: 0; a
    record that is not an object: 1, never read as resolved)."""
    return sum(0 if i is None else _unresolved(i.get("grid_unresolved")) if isinstance(i, dict) else 1 for i in infos)


_ABSENT = object()


def _at(d, path):
    """d at path (a tuple of keys, every level an object) -> the value, or _ABSENT."""
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return _ABSENT
        d = d[k]
    return d


def _num(x):
    """A JSON number as a float -> None for a non-number (bool included) or one no float represents (Codex WP4 r3
    P3-R3-1: a huge JSON integer raises OverflowError in float())."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    try:
        return float(x)
    except OverflowError:
        return None


def _score(x):
    """A candidate's val_lpd as the procedures compare it -> a float: finite, or -inf (stored as the number or, by
    recovery_extra, as the text "-Infinity"); None when absent, not a number, NaN, +inf or not representable."""
    if x == "-Infinity":
        return -math.inf
    f = _num(x)
    return f if f is not None and (math.isfinite(f) or f == -math.inf) else None


def _val_key(c):
    """A candidate's validation score as the procedures compare it (max over val_lpd, first on ties); an unreadable
    score ranks lowest (and is itself a violation: _require)."""
    s = _score(c.get("val_lpd"))
    return -math.inf if s is None else s


_SHAPES = {"object": lambda x: isinstance(x, dict), "list": lambda x: isinstance(x, list),
           "count": lambda x: type(x) is int, "flag": lambda x: type(x) is bool, "rank": lambda x: type(x) is int,
           "penalty": lambda x: _num(x) is not None and math.isfinite(_num(x)),
           "score": lambda x: _score(x) is not None}
# The records each live guard / C1 path reads, with the producers' shapes (procedure, forward_procedure,
# recovery_extra.forward always store them; Codex WP4 r3 P2: an absent record is a violation, never zero flags):
_CAND_SELECTION = ((("rank",), "rank"), (("lambda",), "penalty"), (("val_lpd",), "score"),
                   (("integration", "validation"), "object"))            # (every candidate a selection compares)
_CAND_TEST = ((("integration", "test"), "object"),)                       # (a comparison's two candidates)
_CAND_COMPARED = ((("integration_unresolved",), "count"),) + _CAND_TEST   # (the winner compared with rank 0)
_PROC_DECIDED = ((("success",), "flag"), (("selected", "rank"), "rank"), (("selected", "lambda"), "penalty"),
                 (("decision", "available"), "flag"), (("decision", "test_worlds"), "count"),
                 (("decision", "selection_unresolved"), "flag"), (("decision", "integration_unresolved"), "count"),
                 (("per_test_world",), "list"))
_FWD_DECIDED = ((("success",), "flag"), (("selected", "rank"), "rank"), (("selected", "lambda"), "penalty"),
                (("decision", "available"), "flag"), (("decision", "selection_unresolved"), "flag"),
                (("decision", "integration_unresolved"), "count"))
_BRANCH_LIVE = ((("available",), "flag"), (("decision_available",), "flag"), (("success",), "flag"),
                (("integration_unresolved",), "count"), (("integration", "selected"), "object"),
                (("per_world",), "list"))
_PRIMARY_LIVE = ((("rank",), "rank"), (("lambda",), "penalty"), (("available",), "flag"), (("success",), "flag"))
_PRIMARY_ROOTS = ((("decision", "test_worlds"), "count"),)       # (the live primary's roots)
_CAND_SCORE, _CAND_VALIDATION = _CAND_SELECTION[:3], _CAND_SELECTION[3:]


def _require(rec, fields, where):
    """The records a live guard or C1 path reads must be present with the producer's shape (an empty object the
    producer writes is valid) -> violations naming each absent or malformed field."""
    v = []
    for path, shape in fields:
        x = _at(rec, path)
        if x is _ABSENT:
            v.append(f"{where}: {'.'.join(path)} is absent (the producer always records this {shape})")
        elif not _SHAPES[shape](x):
            v.append(f"{where}: {'.'.join(path)} is not a {shape} ({repr(x)[:60]})")
    return v


def _per_world(per, roots, where):
    """A decided comparison's contributing roots against its stored per-world record (crossed_lb's per-test-world
    means: one entry per contributing root) -> violations."""
    if not isinstance(per, list):
        return [f"{where}: a decision without its per-world comparison record"]
    if roots is None or len(per) != roots:
        return [f"{where}: {len(per)} per-world comparison(s) for {roots} recorded contributing root(s)"]
    return []


def _branch_live(br):
    """A forward branch that claims something: decided, successful or available (recovery.py forward_procedure;
    recovery_extra.forward) -- live on its own, whatever the top-level decision says (Codex WP4 r4 P2-R4-1)."""
    return isinstance(br, dict) and (br.get("decision_available") is True or bool(br.get("success"))
                                     or br.get("available") is True)


def _record_violations(o, where, decided):
    """The decision flags checked against the records they summarize (Codex WP4 r2 P2-WP4-3: no availability or
    success flag is trusted on its own) -> violations. From the stored candidate records, exactly as procedure /
    forward_procedure / recovery_extra.forward compute the flags: the validation flags (grid_unresolved over every
    candidate's validation integration); the full selection (the recorded `selected` is the validation winner) and,
    for the selection-and-prediction procedure, the winner's comparison against rank zero (its stored
    integration_unresolved and its own and rank zero's test-integration flags); the RESTRICTED PRIMARY (ranks <=
    PRIMARY_RANKS: their validation flags only, the recorded primary is the restricted winner, and that winner's
    comparison against rank zero), so a higher-rank failure outside the restricted set never touches its derivation;
    for the forward procedures, each branch's comparison (its stored flag, its selected / rank-zero integration
    records and the validation flags) and the decision branch behind the top-level decision and success; and a decided
    comparison's contributing roots against its per-world record (_per_world). Each claim is LIVE on its own (Codex
    WP4 r4): the top-level decision (decided or successful), the restricted primary (available or successful) and
    EACH forward branch (_branch_live), whatever the others say; each live claim requires, present and with the
    producer's shape (_require), exactly the records its derivation reads: any live claim every candidate's rank /
    lambda / val_lpd (the validation-winner consistency reads them); the top-level decision or a live branch every
    candidate's validation integration (the validation flags); the top-level decision its decision fields and the
    winner's and rank zero's comparison records; a live branch its own records; the live primary its fields, its
    restricted candidates' records, its restricted winner's and rank zero's comparison records and its
    contributing-root count decision.test_worlds (P2-R4-2), whose minimum the root guard enforces."""
    v = []
    cands = o.get("candidates")
    sp = o.get("selected_primary") if isinstance(o.get("selected_primary"), dict) else None
    live_full = decided or bool(o.get("success"))
    live_primary = sp is not None and (sp.get("available") is True or bool(sp.get("success")))
    live_branches = [b for b in BRANCHES if _branch_live(o.get(b))]
    live_any = live_full or live_primary or bool(live_branches)
    if not (isinstance(cands, list) and cands and all(isinstance(c, dict) for c in cands)):
        if live_any:
            v.append(f"{where}: a decision without its candidate records")
        return v
    rank0 = next((c for c in cands if c.get("rank") == 0), None)
    if rank0 is None:
        return [f"{where}: no rank-0 candidate record"]
    fwd = o.get("procedure") == "forward" or "reference_policy" in o
    win = max(cands, key=_val_key)
    wi, zi = next(i for i, c in enumerate(cands) if c is win), next(i for i, c in enumerate(cands) if c is rank0)
    validation_read = live_full or bool(live_branches)
    for i, c in enumerate(cands):
        if live_any:            # (the validation-winner consistency check below reads every candidate's score)
            v += _require(c, _CAND_SCORE, f"{where}.candidates[{i}]")
        if validation_read:     # (the validation flags: every candidate's validation integration)
            v += _require(c, _CAND_VALIDATION, f"{where}.candidates[{i}]")
    if live_full:
        v += _require(o, _FWD_DECIDED if fwd else _PROC_DECIDED, where)
        if not fwd:
            v += _require(win, _CAND_COMPARED, f"{where}.candidates[{wi}]")
            v += _require(rank0, _CAND_TEST, f"{where}.candidates[{zi}]")
    val_all = _grid(*(_sub(c, "integration", "validation") for c in cands)) if validation_read else 0
    s = o.get("selected") if isinstance(o.get("selected"), dict) else {}
    if (s.get("rank"), s.get("lambda")) != (win.get("rank"), win.get("lambda")):
        v.append(f"{where}: the selected candidate ({s.get('rank')}, {s.get('lambda')}) is not the validation winner "
                 f"({win.get('rank')}, {win.get('lambda')})")

    def compared(c):        # (a candidate against rank zero, as procedure stores it)
        own = _grid(_sub(c, "integration", "test")) + (0 if c is rank0 else _grid(_sub(rank0, "integration", "test")))
        return max(_unresolved(c.get("integration_unresolved")), own)
    sel0 = (s.get("rank"), s.get("lambda")) == (0, 0.0)
    for b in live_branches:     # (every live branch, of any record kind: Codex WP4 r4 P2-R4-1)
        br = o[b]
        v += _require(br, _BRANCH_LIVE + (() if sel0 else ((("integration", "rank0"), "object"),)), f"{where}.{b}")
        n = (_unresolved(br.get("integration_unresolved")) + _grid(_sub(br, "integration", "selected"))
             + (0 if sel0 else _grid(_sub(br, "integration", "rank0"))) + val_all)
        if n:
            v.append(f"{where}.{b}: decided or available on an unresolved comparison ({n} flag(s) in its "
                     "integration records or the validation)")
        if br.get("decision_available") is True or br.get("success"):
            v += _per_world(br.get("per_world"), _roots(br.get("test_roots"), br.get("worlds")), f"{where}.{b}")
    if fwd:
        db = o.get("forward_transfer") if "forward_transfer" in o else next(
            (o[b] for b in ("world_transfer", "interpolation") if isinstance(o.get(b), dict)), None)
        if decided and not (isinstance(db, dict) and db.get("available") is True and
                            db.get("decision_available") is True):
            v.append(f"{where}: a decision whose decision branch is not decided")
        if o.get("success") and not (isinstance(db, dict) and db.get("success") is True):
            v.append(f"{where}: success whose decision branch is not successful")
        if (decided or o.get("success")) and val_all:
            v.append(f"{where}: decided on an unresolved selection ({val_all} validation flag(s) in the candidates)")
        return list(dict.fromkeys(v))
    full = val_all + compared(win) if live_full else 0
    if (decided or o.get("success")) and full:
        v.append(f"{where}: decided on an unresolved selection or comparison (from the candidate records: {val_all} "
                 f"validation flag(s), {compared(win)} in the winner's comparison against rank zero)")
    if decided or o.get("success"):
        v += _per_world(o.get("per_test_world"), _roots(_sub(o, "decision", "test_worlds")), where)
    if sp is not None:
        restricted = [c for c in cands if type(c.get("rank")) is int and c["rank"] <= PRIMARY_RANKS]
        live = live_primary
        if live:                # (every rank, to tell the restricted set; the restricted candidates' records only)
            v += _require(sp, _PRIMARY_LIVE, f"{where}.selected_primary")
            v += _require(o, _PRIMARY_ROOTS, where)          # (its contributing roots: Codex WP4 r4 P2-R4-2)
            for i, c in enumerate(cands):
                inside = any(c is r for r in restricted)
                v += _require(c, ((("rank",), "rank"),) + (_CAND_SELECTION[1:] if inside else ()),
                              f"{where}.candidates[{i}]")
        if not restricted:
            if live:
                v.append(f"{where}.selected_primary: decided without restricted candidate records")
            return list(dict.fromkeys(v))
        pw = max(restricted, key=_val_key)
        if live:
            pi = next(i for i, c in enumerate(cands) if c is pw)
            v += _require(pw, _CAND_COMPARED, f"{where}.candidates[{pi}]")
            v += _require(rank0, _CAND_TEST, f"{where}.candidates[{zi}]")
        if (sp.get("rank"), sp.get("lambda")) != (pw.get("rank"), pw.get("lambda")):
            v.append(f"{where}.selected_primary: ({sp.get('rank')}, {sp.get('lambda')}) is not the restricted "
                     f"validation winner ({pw.get('rank')}, {pw.get('lambda')})")
        pv = _grid(*(_sub(c, "integration", "validation") for c in restricted)) if live else 0
        if live and (pv or compared(pw)):
            v.append(f"{where}.selected_primary: available or successful on an unresolved restricted selection or "
                     f"comparison ({pv} validation flag(s) over ranks <= {PRIMARY_RANKS}, {compared(pw)} in the "
                     "restricted winner's comparison against rank zero)")
    return list(dict.fromkeys(v))


def _guard_violations(o, where):
    """The registered guards on one option record (A_design_v5 3.8 check 5; CRITERION C1, C4, C6; Codex WP4 P2-WP4-3),
    for the top-level decision, every branch and the primary selection, SUCCESSFUL OR NOT: a success needs an
    available, decided record; a decision (decision.available / decision_available true) needs an available record;
    an unresolved selection or comparison is never decided, successful or marked available; no decision or success
    with fewer than MIN_TEST_ROOTS contributing roots (D6 rule 27); and every such flag agrees with the stored
    candidate and integration records it summarizes (_record_violations; the restricted primary's own comparison
    included). Unavailable records and one-root descriptive scores (available false, no decision) are permitted
    (C4)."""
    if not isinstance(o, dict):
        return [f"{where}: not a record"]
    v = []
    dec = o.get("decision") if isinstance(o.get("decision"), dict) else None
    decided = (dec is not None and dec.get("available") is True) or o.get("decision_available") is True
    d0 = dec or {}
    sel = o.get("selected") if isinstance(o.get("selected"), dict) else {}
    unres = (_unresolved(d0.get("integration_unresolved")) + _unresolved(d0.get("selection_unresolved"))
             + _unresolved(sel.get("selection_unresolved")))
    roots = _roots(d0.get("test_worlds"), o.get("test_roots"), o.get("worlds"))
    if o.get("success") and (o.get("available") is False or not decided):
        v.append(f"{where}: success without an available decision")
    if decided and o.get("available") is False:
        v.append(f"{where}: a decision while unavailable")
    if unres and (decided or o.get("success")):
        v.append(f"{where}: an unresolved comparison decided")
    if roots is not None and roots < MIN_TEST_ROOTS and (decided or o.get("success")):
        v.append(f"{where}: a decision with {roots} contributing test root(s)")
    for b in BRANCHES:
        br = o.get(b)
        if not isinstance(br, dict):
            continue
        w = f"{where}.{b}"
        bdec = br.get("decision_available") is True
        broots = _roots(br.get("test_roots"), br.get("worlds"))
        if br.get("success") and (br.get("available") is not True or not bdec):
            v.append(f"{w}: success without an available decision")
        if bdec and br.get("available") is not True:
            v.append(f"{w}: a decision while unavailable")
        if _unresolved(br.get("integration_unresolved")) and (bdec or br.get("success") or br.get("available") is True):
            v.append(f"{w}: an unresolved comparison decided or marked available")
        if broots is not None and broots < MIN_TEST_ROOTS and (bdec or br.get("success")):
            v.append(f"{w}: a decision with {broots} contributing root(s)")
    sp = o.get("selected_primary")
    if isinstance(sp, dict):
        if sp.get("success") and sp.get("available") is not True:
            v.append(f"{where}.selected_primary: success while unavailable")
        if _unresolved(sp.get("selection_unresolved")) and (sp.get("available") is True or sp.get("success")):
            v.append(f"{where}.selected_primary: an unresolved selection decided")
        if roots is not None and roots < MIN_TEST_ROOTS and (sp.get("available") is True or sp.get("success")):
            v.append(f"{where}.selected_primary: decided with {roots} contributing test root(s)")
    v += _record_violations(o, where, decided)
    return v


def _guards(entries):
    """Check 5: availability / unresolved counts as summarize recomputes them (recovery.summarize per legacy
    directory, recovery_extra.summarize per extra one: either refusing fails the check) and the root / unresolved
    guards on every result's option records."""
    import recovery_extra as X
    viol, counts = [], {}
    for e in entries:
        try:
            if e["kind"] == "legacy":
                summ = summarize(e["path"])
                counts[e["dir"]] = [{k: c.get(k) for k in ("scenario", "option", "datasets", "decided", "unavailable",
                                                           "unresolved_decisions", "unresolved_selections")}
                                    for c in summ["cells"]]
                rows = [(f"{e['dir']}/{os.path.basename(w)}", r) for w, _, _, r in _legacy_results(e["path"])]
            else:
                summ = _extra_call(X.summarize, e["path"])
                counts[e["dir"]] = [{k: c.get(k) for k in ("case", "scenario", "option", "branch", "datasets",
                                                           "completed", "decided", "unavailable")}
                                    for c in summ["cells"]]
                rows = [(f"{e['dir']}/{os.path.basename(w)}", r) for w, _, _, r in _extra_results(e["path"])]
        except (SystemExit, ValueError, KeyError, TypeError, OSError) as ex:
            viol.append(f"{e['dir']}: summarize refused ({ex})")
            continue
        except RecursionError:
            viol.append(f"{e['dir']}: summarize refused (a document is {DEEP})")
            continue
        for w, r in rows:
            for opt, o in (r.get("options") or {}).items():
                try:
                    viol += _guard_violations(o, f"{w}:{opt}")
                except RecursionError:
                    viol.append(f"{w}:{opt}: a record nested deeper than the recursion limit")
    return {"status": "fail" if viol else "pass", **({"reason": "; ".join(viol[:20])} if viol else {}),
            "counts": counts}


def c1_success(o):
    """CRITERION C1's success on one option-a record (Codex WP4 P2-WP4-3): "selected rank > 0 AND crossed-source-
    bootstrap test lower bound > 0, with an available resolved comparison and at least two contributing test roots"
    -- success true; the record not unavailable; decision.available true with no unresolved comparison or selection;
    decision.test_worlds >= MIN_TEST_ROOTS; the selected rank > 0 and a finite test_lb > 0; and no guard violation.
    Anything else (an unavailable, unresolved or inconsistent "success" included) is unsuccessful."""
    if not isinstance(o, dict) or o.get("success") is not True or o.get("available") is False:
        return False
    dec, sel, lb = o.get("decision"), o.get("selected"), _num(o.get("test_lb"))   # (_num: never an OverflowError)
    if not isinstance(dec, dict) or dec.get("available") is not True or \
            _unresolved(dec.get("integration_unresolved")) or _unresolved(dec.get("selection_unresolved")):
        return False
    tw = dec.get("test_worlds")
    if type(tw) is not int or tw < MIN_TEST_ROOTS:
        return False
    if not (isinstance(sel, dict) and type(sel.get("rank")) is int and sel["rank"] > 0 and lb is not None
            and math.isfinite(lb) and lb > 0):
        return False
    return not _guard_violations(o, "C1")


def _c1(entries, mode):
    """Check 6, C1 (A_design_v5 3.8 PC-23; CRITERION C1): from the C1-primary directory ONLY, after verifying that its
    config.json hashes to the scheduled expected_config_sha256 (and has the registered settings): option a's
    successes (c1_success: an available, resolved success only) for r1_034 and r2_034, reps 0..19 exactly, at least
    16 of 20 separately; a missing, unreadable, unavailable or unresolved realization is unsuccessful. Never pooled,
    never substituted by another directory's identical identities."""
    prim = [e for e in entries if e["role"] == "C1-primary"]
    if not prim:
        return {"status": "not_evaluated", "reason": "C1: no C1-primary directory scheduled"}
    if len(prim) != 1:
        return {"status": "fail", "reason": f"{len(prim)} C1-primary directories (exactly one)"}
    e = prim[0]
    d = e["path"]
    cfg = _read_json_at(os.path.join(d, "config.json"))
    sha = rqlib.canonical_sha(cfg)
    if sha != e["expected_config_sha256"]:
        return {"status": "fail", "reason": f"refused: the C1-primary config.json hashes to {sha}, not the scheduled "
                                            f"{e['expected_config_sha256']}"}
    bad = {k: cfg.get(k) for k, v in C1_PRIMARY_CONFIG.items() if cfg.get(k) != v and (k != "namespace" or
                                                                                       mode == "acceptance")}
    if bad:
        return {"status": "fail", "reason": f"refused: the C1-primary configuration is not the registered one: {bad}"}
    out, ok = {}, True
    for sc in C1_RULE["scenarios"]:
        k = flagged = 0
        for rep in range(C1_RULE["reps"]):
            f = f"{sc}.{rep:03d}.json"
            try:
                r = _read_json_at(os.path.join(d, f))
                check_result(d, f, r, sha, cfg.get("namespace"), "C1", cfg)
            except (SystemExit, OSError, ValueError):
                continue                                   # (missing or invalid: unsuccessful, never removed)
            o = (r.get("options") or {}).get(C1_RULE["option"])
            try:
                win = c1_success(o)
            except RecursionError:
                win = False
            k += win
            flagged += bool(isinstance(o, dict) and o.get("success") is True and not win)
        out[sc] = {"successes": k, "datasets": C1_RULE["reps"], "wilson95": wilson(k, C1_RULE["reps"]),
                   "pass": k >= C1_RULE["min_successes"], "success_flags_not_counted": flagged}
        ok &= k >= C1_RULE["min_successes"]
    return {"status": "pass" if ok else "fail", "dir": e["dir"], "scenarios": out,
            "rule": ">= 16/20 successes separately in r1_034 and r2_034, option a; a success counts only when "
                    "available and resolved with >= 2 contributing test roots; unavailable = unsuccessful"}


def packet(schedule_path, mode, allow_synthetic=False):
    """`packet` (A_design_v5 3.8, PC-19, PC-23) -> (the packet document, exit code 0 / 2); Refused before any check.
    --mode acceptance (the wrapper's only mode): a schedule lacking a role of the frozen C2 matrix, its single
    C1-primary or any block of C2_MATRIX is refused, so is a synthetic bank (--allow-synthetic-bank, or a model that
    is not accepting); every check runs; scope "bank/D8", scientific_ACCEPTED "UNRESOLVED (review required,
    D8:327)"; exit 0 iff every check passes. --mode diagnostic: any non-empty schedule; each check whose inputs are
    scheduled runs, the others are not_evaluated with their reason; scope "diagnostic (partial)", accepting false,
    no acceptance field; exit 0 iff every evaluated check passes. Everything is re-derived from the directories;
    summary files are never trusted. Acceptance mode also refuses, before any check, a schedule whose directories'
    bound settings do not satisfy the C2 matrix (bound_settings_gaps). A schedule that cannot be read, is not strict
    JSON (a duplicated key included) or is malformed is a contextual refusal (Codex WP4 P3-WP4-6), never an
    exception."""
    if mode not in ("acceptance", "diagnostic"):
        raise Refused(f"--mode {mode}: acceptance or diagnostic")
    try:
        raw = rqlib.read_bytes(schedule_path)
    except OSError as e:
        raise Refused(f"the schedule {schedule_path} cannot be read ({e})")

    def strict(pairs):
        keys = [k for k, _ in pairs]
        if len(set(keys)) != len(keys):
            raise ValueError(f"duplicate key(s) {sorted({k for k in keys if keys.count(k) > 1})}")
        return dict(pairs)
    try:
        sched = json.loads(raw, object_pairs_hook=strict)
    except RecursionError:                # (Codex WP4 r2 P3-WP4-6: a nesting depth the parser cannot follow)
        raise Refused(f"the schedule {schedule_path} is not strict JSON (nested deeper than the parser's recursion "
                      "limit)") from None
    except ValueError as e:
        raise Refused(f"the schedule {schedule_path} is not strict JSON ({e})")
    base = os.path.dirname(os.path.abspath(schedule_path))
    if mode == "acceptance" and allow_synthetic:
        raise Refused("--mode acceptance refuses --allow-synthetic-bank: a synthetic bank is never acceptance evidence")
    try:
        entries = _schedule_entries(sched, base)
        gaps = schedule_gaps(entries) if mode == "acceptance" else []
    except (TypeError, KeyError, ValueError, AttributeError, RecursionError) as e:     # (a backstop: types first)
        raise Refused(f"the schedule {schedule_path} is malformed ({type(e).__name__}: {e})") from None
    if gaps:
        raise Refused("--mode acceptance: the schedule is incomplete: " + "; ".join(gaps))
    if mode == "acceptance":
        gaps = bound_settings_gaps(entries)
        if gaps:
            raise Refused("--mode acceptance: the scheduled directories' bound settings do not satisfy the C2 matrix "
                          "(CRITERION C2-C4; a scheduled hash alone does not show that): " + "; ".join(gaps))
    inputs = {k: (None if v is None else os.path.normpath(os.path.join(base, v))) for k, v in sched["inputs"].items()}
    gammas = sorted({scenario_gamma(s) for e in entries for s in e["scenarios"]})
    try:
        obs = load_model(argparse.Namespace(obs_model="bank", bank=inputs["bank"], obs_tables=inputs["obs_tables"],
                                            allow_synthetic_bank=allow_synthetic), gammas)
    except SystemExit as e:
        raise Refused(f"the scheduled bank / tables: {e}")
    if mode == "acceptance" and not obs.accepting:
        raise Refused("--mode acceptance: the observation model is not accepting (a synthetic bank)")
    om_sha = sched["observation_model_sha256"]
    checks = {
        "identity": _check(lambda: _identity(entries, inputs, obs, om_sha, mode, allow_synthetic)),
        "completeness": _check(lambda: _completeness(entries)),
        "numerical": _check(lambda: _numerical(entries)),
        "pairing": _check(lambda: dict(status="pass", **pairing([e["path"] for e in entries]))),
        "guards": _check(lambda: _guards(entries)),
        "C1": _check(lambda: _c1(entries, mode)),
    }
    evaluated = [c for c in checks.values() if c["status"] != "not_evaluated"]
    if mode == "acceptance" and len(evaluated) != len(checks):
        raise Refused("--mode acceptance: a check was not evaluated")      # (cannot happen after schedule_gaps)
    ok = all(c["status"] == "pass" for c in evaluated)
    doc = {"schema": PACKET_SCHEMA, "mode": mode, "schedule_sha256": rqlib.sha256_bytes(raw),
           "observation_model_sha256": om_sha, "checks": checks, "exit": 0 if ok else 2}
    if mode == "acceptance":
        doc.update(scope="bank/D8", accepting=True, scientific_ACCEPTED=ACCEPTED_TEXT)
    else:
        doc.update(scope="diagnostic (partial)", accepting=False)
    return doc, (0 if ok else 2)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "one", "bench", "summarize", "conditioning"):
        s = sub.add_parser(name)
        if name == "conditioning":
            s.add_argument("--graph", required=True)
            s.add_argument("--out")
            s.add_argument("--references", help="the selected references/1 document (the actual frames)")
            continue
        if name != "summarize":
            s.add_argument("--graph", required=True)
            s.add_argument("--iters", type=int, default=None, help="sweeps (default: the fitter's, FITTER_DEFAULTS)")
            s.add_argument("--references", help="the selected references/1 document: the ACTUAL reference "
                                                "frames per guild (default: the assumed REF_TIMES, planning only)")
        if name in ("run", "one"):
            s.add_argument("--options", default=None, help="default: the fitter's (minimal a,b,base; registered a)")
            s.add_argument("--ranks", type=int, default=4)
            s.add_argument("--lambdas", default=None,
                           help="default: the fitter's (minimal 0.02,0.1,0.5; registered REGISTERED_LAMBDAS)")
            s.add_argument("--namespace", default="rq2026-recovery")
            s.add_argument("--out", required=True)
            s.add_argument("--ab-cap", type=int, default=-1, metavar="R",
                           help="hold the A/B prey's interaction to rank <= R in every fit (-1: no cap; minimal only)")
            s.add_argument("--fitter", choices=FITTERS, default="minimal",
                           help="minimal (ridge ALS) or registered (map.py, item 7: the v4 §6 map)")
            s.add_argument("--start", choices=("both", "warm", "cold"), default=None,
                           help="the registered map's embedding start: both (registered: the lower penalized "
                                "training objective kept), or one")
            s.add_argument("--basis", type=int, choices=(4, 6, 8), default=None,
                           help="the registered map's basis functions per axis (6; 4 and 8: the sensitivities)")
            s.add_argument("--embedding", choices=("shared", "separate"), default=None,
                           help="the registered map's survival embedding (separate: the sensitivity)")
            s.add_argument("--center", choices=("references", "train_c"), default=None,
                           help="the registered map's fixed centring distribution (train_c: the sensitivity)")
            s.add_argument("--obs-model", choices=OBS_MODELS, default="planning",
                           help="planning (default: the scenario planning noise, labelled non-accepting) or bank "
                                "(the bank/D8 observation model, A_design_v5.md; needs --bank and --obs-tables)")
            s.add_argument("--bank", help="bank mode: the bank/3 artifact (bank_d8.json)")
            s.add_argument("--obs-tables", help="bank mode: its observation tables (obs_tables.npz, recovery.py "
                                                "obs-tables)")
            s.add_argument("--allow-synthetic-bank", action="store_true",
                           help="TEST ONLY: admit a synthetic bank (the configuration is then never accepting)")
        if name == "run":
            s.add_argument("--set", choices=("main", "stress", "power", "numerical", "all"), default="main")
            s.add_argument("--scenarios", help="a comma list instead of --set (--reps each; numerical: 1)")
            s.add_argument("--reps", type=int, default=20)
            s.add_argument("--jobs", type=int, default=2)
        if name == "one":
            s.add_argument("--scenario", required=True, choices=sorted(SCENARIOS))
            s.add_argument("--rep", type=int, required=True)
        if name == "summarize":
            s.add_argument("--dir", required=True)
            s.add_argument("--out")
    s = sub.add_parser("obs-tables", help="build and verify the observation tables of a bank/3 artifact (bank mode)")
    s.add_argument("--bank", required=True)
    s.add_argument("--noise-scales", required=True, help="the noise multipliers to tabulate, e.g. 1,2")
    s.add_argument("--out", required=True)
    s.add_argument("--allow-synthetic-bank", action="store_true", help="TEST ONLY: admit a synthetic bank")
    s = sub.add_parser("pairing", help="refuse directories whose shared (scenario, rep) observations differ")
    s.add_argument("--dirs", required=True, help="a comma list of recovery.py / recovery_extra.py directories")
    s.add_argument("--out")
    s = sub.add_parser("packet", help="the acceptance packet from a frozen schedule (A_design_v5 3.8)")
    s.add_argument("--mode", required=True, choices=("acceptance", "diagnostic"))
    s.add_argument("--schedule", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--allow-synthetic-bank", action="store_true",
                   help="TEST ONLY (diagnostic mode): admit a synthetic bank; refused in acceptance mode")
    a = ap.parse_args(argv)
    if a.cmd == "obs-tables":
        return obs_tables(a)
    if a.cmd == "pairing":
        rep = pairing([x for x in a.dirs.split(",") if x])
        text = json.dumps(rep, indent=1, sort_keys=True)
        if a.out:
            rqlib.write_durable(a.out, text.encode() + b"\n")
        print(text)
        return 0
    if a.cmd == "packet":
        try:
            doc, code = packet(a.schedule, a.mode, a.allow_synthetic_bank)
        except Refused as e:
            print(f"recovery.py packet --mode {a.mode}: REFUSED before any check: {e}", file=sys.stderr)
            return 2
        rqlib.write_json_durable(a.out, doc)
        print(json.dumps({k: doc[k] for k in ("mode", "scope", "accepting", "exit")}, sort_keys=True))
        return code
    if a.cmd == "one":
        return one(a)
    if a.cmd == "run":
        return run(a)
    if a.cmd == "bench":
        return bench(a)
    if a.cmd == "conditioning":
        D = load_data(a.graph, a.references)
        rep = {opt: {f"rank{r}": conditioning(D, r, opt, r) for r in (1, 2, 3, 4)} for opt in OPTIONS + ("fwd",)}
        rep["references"] = ({"sha256": reference_times(a.references)[1]} if a.references
                             else {"assumed": list(REF_TIMES)})
        rep["reference_support"] = D.forward["reference_support"]
        text = json.dumps(rep, indent=1, sort_keys=True)
        if a.out:
            rqlib.write_durable(a.out, text.encode() + b"\n")
        print(text)
        return 0
    summ = summarize(a.dir)
    text = json.dumps(summ, indent=1, sort_keys=True)
    if a.out:
        rqlib.write_durable(a.out, text.encode() + b"\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

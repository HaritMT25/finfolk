#!/usr/bin/env python3
"""recovery.py: the exact-graph recovery simulation of design v4 §6.5, with a minimal map fitter.

    recovery.py run --graph G/graph.jsonl.gz --out DIR [--set main|stress|numerical|all]
                    [--reps 20] [--jobs 2] [--ranks 4] [--lambdas 0.02,0.1,0.5] [--iters 40]
    recovery.py one --graph G/graph.jsonl.gz --scenario NAME --rep N --out FILE.json [...]
    recovery.py summarize --dir DIR [--out summary.json]
    recovery.py conditioning --graph G/graph.jsonl.gz [--out conditioning.json]
    recovery.py bench --graph G/graph.jsonl.gz

Needs numpy (RQ_PYLIB, when set, is put on sys.path first: an unpacked wheel on a host without pip).
`run` starts `one` jobs as subprocesses (never multiprocessing), each with one BLAS thread, and
skips datasets already written (resumable).

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
Binomial(B = 324). The data are the empirical logits.

THE FITTER (minimal; the production map, item 7, replaces it). Ridge alternating least squares of
    z = mu + a_j - b_i + u_i.v_j [+ h(lag) + h_w(lag) on within pairs, option b]
on the replicate means of the fitting pairs, ranks 0..--ranks, penalty on u, v from --lambdas.
Held-out populations are placed only by their support pairs. The procedure: every candidate's
validation score (mean log predictive density per replicate observation on the validation pairs
that are not support, with a Gaussian working likelihood whose variance is the fit's replicate
residual variance; equal validation-world weights) selects rank and penalty; the selected map and
the rank-0 baseline then score the world-transfer test pairs (non-support test pairs of the global
families with an endpoint in a test world); success = a selected rank > 0 and the 95% lower bound of
a test-world cluster bootstrap of the mean score improvement > 0 (v4 §7.6). The 80/10/10
interpolation is not part of this fit (a separate secondary fit).

SETS. main: rank 0, rank 1 and rank 2 at 1.7% and 3.4% (--reps each; v4 proposes 20: 100 noisy
datasets). stress (--reps // 2 each): saturation (asym), a two-way monotone surface (a misfit for
this additive-baseline fitter: the registered 6 x 6 monotone tensor baseline exists for it),
clustered strategies, a strong own-world lag, doubled noise (also at 1.7%). The noise magnitudes
(row 0.15, column 0.15, cell 0.20 on the logit scale, plus the binomial) are planning values until
the independent noise bank (v4 §7.4) measures them. power (--reps // 2 each): the noise tripled and
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
of a prey x replicate share its row noise (the global seeds); survivors ~ Binomial(600). The
minimal fitter ignores them; --fitter registered (map.py, item 7) fits both heads jointly.
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
REF_TIMES = (0, 20, 60, 100, 120, 140, 180, 200)
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


def capture_sd(p, scale=1.0):
    """The measured per-replicate logit SD at capture fraction p (CAPTURE_SD, flat beyond its ends), x scale."""
    (p0, s0), (p1, s1) = CAPTURE_SD
    return scale * np.interp(p, [p0, p1], [s0, s1])


# ------------------------------------------------------------------ data
class Data:
    """The graph as arrays: prey / predator node indices of every pair, family, role, lags, worlds."""

    def __init__(self, g):
        self.g = g
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

        def nodes(d):
            w, t, ref, held = np.zeros(len(d), int), np.zeros(len(d), int), np.zeros(len(d), bool), \
                np.zeros(len(d), "<U5")
            for n, i in d.items():
                gg, ww, tt = graphlib.parse(n)
                if ww is None:
                    w[i], t[i], ref[i], held[i] = -1, REF_TIMES[tt], True, "train"
                else:
                    w[i], t[i] = widx[ww], tt
                    held[i] = split[ww] if split[ww] != "train" else holdout.get((ww, tt), "train")
            return w, t, ref, held
        self.nQ, self.nP = len(qn), len(pn)
        self.qw, self.qt, self.qref, self.qheld = nodes(qn)
        self.pw, self.pt, self.pref, self.pheld = nodes(pn)
        self.qkey = {i: n for n, i in qn.items()}
        self.pkey = {i: n for n, i in pn.items()}
        E = len(g["edges"])
        self.qi = np.fromiter((qn[e[0]] for e in g["edges"]), int, E)
        self.pj = np.fromiter((pn[e[1]] for e in g["edges"]), int, E)
        self.fam = np.fromiter((FAMS.index(e[2]) for e in g["edges"]), int, E)
        self.role = np.fromiter((ROLES.index(e[3]) for e in g["edges"]), int, E)
        self.within = self.fam == FAMS.index("within")
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
        self.qab = (self.qw >= 0) & np.isin(self.treat[np.maximum(self.qw, 0)], ["A", "B"]) & ~self.qref
        ab = self.qab[self.qi[self.test_idx]]
        self.classes = {"world_test_ab_prey": self.test_idx[ab], "world_test_c_prey": self.test_idx[~ab],
                        "snapshot_test": self.stest_idx}


# ------------------------------------------------------------------ truth
def _walk(rng, n_t, end_sd, dim=None):
    shape = (n_t,) if dim is None else (n_t, dim)
    steps = rng.normal(0.0, end_sd / math.sqrt(n_t), shape)
    steps[0] = 0.0
    return np.cumsum(steps, axis=0)


def _rise(t):
    return np.log1p(np.asarray(t) / 10.0) / math.log1p(20.0)


def simulate(D, sc, seed):
    """-> the truth (eta per pair, the interaction) and the data (empirical logits, R per pair)."""
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

    def node_vals(g, wv, tv, ref):
        sent = np.where(ref, nW + (np.arange(len(wv)) % 4), wv)
        x = qual[g][sent, tv] + rng.normal(0.0, s["snap_sd"], len(wv))
        e = None
        if rank:
            e = emb[g][sent, tv] + rng.normal(0.0, 0.3, (len(wv), rank))
            e -= e[ref].mean(axis=0)               # centred on the eight references (v4 §6.3)
        return x, e
    b, u = node_vals("Q", D.qw, D.qt, D.qref)
    a, v = node_vals("P", D.pw, D.pt, D.pref)
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
    energy = float(np.var(c * (inter / c - additive_projection(D, inter / c))) / np.var(eta)) if rank else 0.0
    out = {"eta": eta, "inter": inter, "z": z, "zbar": z.mean(axis=1), "c": c, "energy": energy, "settings": s}
    out.update(simulate_survival(D, s, seed, a, b, u, v, c, rank))
    return out


N_SURV = 600


def simulate_survival(D, s, seed, a, b, u, v, c, rank):
    """The survival head's truth and data (its own stream: the capture data stay what they were):
    logit S_i0 = c_i (predator-free controls, one per prey snapshot x replicate), logit S_ij =
    c_i - 0.6 (a_j - b_i) - 0.3 + c' u_i' D_S v_j (a full D_S); the prey-row noise of a replicate
    is shared by its control and its exposed cells (the global seeds); survivors ~ Binomial(600)."""
    rng = np.random.default_rng([seed, 2])
    cS = 1.4 + 0.35 * rng.normal(size=D.nQ)
    etaS = cS[D.qi] - 0.6 * (a[D.pj] - b[D.qi]) - 0.3
    DS = None
    if rank:
        DS = rng.normal(size=(rank, rank)) / math.sqrt(rank)
        etaS = etaS + 0.8 * c * (u[D.qi] * (v[D.pj] @ DS.T)).sum(axis=1)
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
    return {"cS": cS, "etaS": etaS, "DS": DS, "s": S, "sbar": S.mean(axis=1), "s0": S0, "s0bar": S0.mean(axis=1)}


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
    """Mean log predictive density per replicate observation, per pair (Gaussian working model)."""
    return (-0.5 * np.log(2 * math.pi * s2) - ((z - pred[:, None]) ** 2) / (2 * s2)).mean(axis=1)


def world_mean(vals, worlds):
    ws = np.unique(worlds)
    return float(np.mean([vals[worlds == w].mean() for w in ws])), ws


def cluster_lb(diff, worlds, rng, n=2000):
    """Mean of the per-world means of diff, and its test-world cluster-bootstrap 2.5% quantile."""
    ws = np.unique(worlds)
    per = np.array([diff[worlds == w].mean() for w in ws])
    boots = per[rng.integers(0, len(ws), (n, len(ws)))].mean(axis=1)
    return float(per.mean()), float(np.quantile(boots, 0.025)), per.tolist()


FITTERS = ("minimal", "registered")


def any_fit(fitter, D, idx, data, rank, lam, own_layer, iters, seed, ab_cap=None, init=None, balance=False,
            start="warm"):
    """The minimal fitter (fit) or the registered map (map.py: monotone 6 x 6 tensor baseline,
    bounded link, the joint survival head; start: its embedding's SVD warm start or a cold one)."""
    if fitter == "registered":
        try:
            import map as mapfit
        except ImportError:
            raise SystemExit("--fitter registered needs map.py (item 7, the registered map; its own PR)")
        return mapfit.fit(D, idx, data, rank, lam, own_layer, iters, seed, init=init, start=start)
    return fit(D, idx, data["zbar"], rank, lam, own_layer, iters, seed, ab_cap=ab_cap, init=init, balance=balance)


def any_predict(D, m, idx):
    if "surfC" in m:
        import map as mapfit
        return mapfit.predict(D, m, idx)
    return predict(D, m, idx)


def class_accuracy(D, data, m1, m0):
    """Per target class: the selected map's and rank 0's RMSE against the truth."""
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


def procedure(D, data, option, ranks, lambdas, iters, seed, ab_cap=None, fitter="minimal", start="warm"):
    """The registered selection and prediction procedure on one dataset for one fitting option.
    Every candidate also records its test improvement over rank 0 and the world-cluster lower
    bound, and the selection restricted to ranks <= PRIMARY_RANKS is reported beside the full one
    (selected_primary)."""
    idx = D.fit[option]
    own_layer = option == "b"
    cands = [(0, 0.0)] + [(r, lam) for r in range(1, ranks + 1) for lam in lambdas]
    out = {"candidates": [], "fitter": fitter, "start": start if fitter == "registered" else None}
    best, models = None, {}
    predict = any_predict              # noqa: F811 (the procedure scores whichever fitter it ran)
    for r, lam in cands:
        t0 = time.time()
        m = any_fit(fitter, D, idx, data, r, lam, own_layer, iters, seed, ab_cap=ab_cap, start=start)
        s2 = float(((data["z"][idx] - predict(D, m, idx)[:, None]) ** 2).mean())
        pv = predict(D, m, D.val_idx)
        vscore, _ = world_mean(lpd(data["z"][D.val_idx], pv, s2), D.val_world)
        pt = predict(D, m, D.test_idx)
        rec = {"rank": r, "lambda": lam, "s2": s2, "val_lpd": vscore,
               "test_rmse_truth": float(np.sqrt(np.mean((pt - data["eta"][D.test_idx]) ** 2))),
               "seconds": round(time.time() - t0, 2)}
        out["candidates"].append(rec)
        models[(r, lam)] = (m, s2)
        if best is None or vscore > best["val_lpd"]:
            best = rec
    sel = (best["rank"], best["lambda"])
    m1, s21 = models[sel]
    m0, s20 = models[(0, 0.0)]
    zt = data["z"][D.test_idx]
    base = lpd(zt, predict(D, m0, D.test_idx), s20)
    for rec in out["candidates"]:      # (every candidate against rank 0: any restricted selection, post hoc)
        mk, sk = models[(rec["rank"], rec["lambda"])]
        rec["test_improvement"], rec["test_lb"], _ = cluster_lb(lpd(zt, predict(D, mk, D.test_idx), sk) - base,
                                                                D.test_world, np.random.default_rng(seed + 7))
    prim = max((c for c in out["candidates"] if c["rank"] <= PRIMARY_RANKS), key=lambda c: c["val_lpd"])
    out["selected_primary"] = {"ranks": list(range(PRIMARY_RANKS + 1)), "rank": prim["rank"],
                               "lambda": prim["lambda"], "test_improvement": prim["test_improvement"],
                               "test_lb": prim["test_lb"], "success": bool(prim["rank"] > 0 and prim["test_lb"] > 0)}
    diff = lpd(zt, predict(D, m1, D.test_idx), s21) - base
    mean, lb, per = cluster_lb(diff, D.test_world, np.random.default_rng(seed + 7))
    zs = data["z"][D.stest_idx]
    sdiff = lpd(zs, predict(D, m1, D.stest_idx), s21) - lpd(zs, predict(D, m0, D.stest_idx), s20)
    if sel[0] > 0:
        trn = D.fit[option]
        qn = np.unique(D.qi[trn])
        lead = m1["u"][qn, 0]
        align = float(abs(np.corrcoef(lead, m1["b"][qn])[0, 1])) if lead.std() > 0 else 0.0
    else:
        align = None
    out.update(selected={"rank": sel[0], "lambda": sel[1]}, test_improvement=mean, test_lb=lb,
               per_test_world=per, success=bool(sel[0] > 0 and lb > 0),
               snapshot_test_improvement=float(sdiff.mean()), alignment_u1_b=align,
               fit_pairs=int(len(idx)), classes=class_accuracy(D, data, m1, m0), ab_cap=ab_cap)
    return out


CONTINUATION = (0.3, 0.1, 0.03, 0.01, 0.003, 0.001)


def numerical(D, data, option, rank, iters, seed, ab_cap=None, fitter="minimal"):
    """Noiseless data fitted at the true rank (the penalty continued down to 0.001, warm-started and
    balanced, 100 sweeps per step: a cold nearly unpenalized ALS stalls short of the exact fit): the
    test targets' errors relative to the interaction's SD, overall and without the targets that have
    an endpoint with fewer fitting pairs than the rank's parameters (rank + 1: not identifiable)."""
    idx = D.fit[option]
    m = None
    predict = any_predict              # noqa: F811
    for lam in CONTINUATION:
        m = any_fit(fitter, D, idx, data, rank, lam, option == "b", 100 if fitter == "minimal" else 30, seed,
                    ab_cap=ab_cap, init=m, balance=True)
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


def load_data(path):
    if path not in _DATA:
        _DATA[path] = Data(graphlib.load(path))
    return _DATA[path]


def one(a):
    D = load_data(a.graph)
    sc = SCENARIOS[a.scenario]
    seed = rqlib.derive_seed(a.namespace, "recovery", a.scenario, a.rep)
    t0 = time.time()
    data = simulate(D, sc, seed)
    res = {"schema": RESULT_SCHEMA, "scenario": a.scenario, "rep": a.rep, "seed": seed,
           "settings": data["settings"], "interaction_scale": data["c"], "energy_check": data["energy"],
           "graph_edges_sha256": D.g["edges_sha256"], "options": {}}
    cap = a.ab_cap if a.ab_cap >= 0 else None
    res["fitter"] = a.fitter
    res["start"] = a.start
    for opt in a.options.split(","):
        if sc.get("noiseless"):
            res["options"][opt] = numerical(D, data, opt, sc["rank"], a.iters, seed, ab_cap=cap, fitter=a.fitter)
        else:
            res["options"][opt] = procedure(D, data, opt, a.ranks, [float(x) for x in a.lambdas.split(",")],
                                            a.iters, seed, ab_cap=cap, fitter=a.fitter, start=a.start)
    res["seconds"] = round(time.time() - t0, 1)
    rqlib.write_json_durable(a.out, res)
    return 0


def run(a):
    os.makedirs(a.out, exist_ok=True)
    names = SETS[a.set] if a.set != "all" else [n for s in ("main", "stress", "power", "numerical") for n in SETS[s]]
    if a.scenarios:
        names = a.scenarios.split(",")
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
                   "--ab-cap", str(a.ab_cap), "--fitter", a.fitter, "--start", a.start]
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


def summarize(d):
    rows = {}
    for f in sorted(os.listdir(d)):
        if not f.endswith(".json") or f.startswith("summary"):
            continue
        r = rqlib.read_json(os.path.join(d, f))
        for opt, o in r["options"].items():
            rows.setdefault((r["scenario"], opt), []).append(o)
    out = {"schema": "finfolk.redqueen.recoverysummary/1", "cells": []}
    for (sc, opt), lst in sorted(rows.items()):
        if "success" in lst[0]:
            k = sum(o["success"] for o in lst)
            sel = {}
            for o in lst:
                sel[o["selected"]["rank"]] = sel.get(o["selected"]["rank"], 0) + 1
            prim = [o["selected_primary"] for o in lst if "selected_primary" in o]
            kp = sum(p["success"] for p in prim)
            selp = {}
            for p in prim:
                selp[p["rank"]] = selp.get(p["rank"], 0) + 1
            out["cells"].append({"scenario": sc, "option": opt, "datasets": len(lst), "successes": k,
                                 "rate": round(k / len(lst), 3), "wilson95": wilson(k, len(lst)),
                                 "selected_ranks": dict(sorted(sel.items())),
                                 "positive_rank_selected": sum(o["selected"]["rank"] > 0 for o in lst),
                                 "primary": ({"ranks": prim[0]["ranks"], "datasets": len(prim), "successes": kp,
                                              "rate": round(kp / len(prim), 3), "wilson95": wilson(kp, len(prim)),
                                              "selected_ranks": dict(sorted(selp.items())),
                                              "positive_rank_selected": sum(p["rank"] > 0 for p in prim)}
                                             if prim else None),
                                 "start": lst[0].get("start"),
                                 "mean_test_improvement": float(np.mean([o["test_improvement"] for o in lst])),
                                 "mean_test_lb": float(np.mean([o["test_lb"] for o in lst])),
                                 "fit_pairs": lst[0]["fit_pairs"],
                                 "classes": {k: {f: float(np.mean([o["classes"][k][f] for o in lst]))
                                                 for f in ("rmse_selected", "rmse_rank0", "interaction_sd")}
                                             for k in (lst[0].get("classes") or {})}})
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
    idx = D.fit[option]
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
    D = load_data(a.graph)
    t0 = time.time()
    data = simulate(D, SCENARIOS["r2_034"], 1)
    t1 = time.time()
    m = fit(D, D.fit["a"], data["zbar"], 2, 0.1, False, a.iters, 1)
    t2 = time.time()
    print(json.dumps({"pairs": len(D.qi), "simulate_s": round(t1 - t0, 2), "fit_rank2_s": round(t2 - t1, 2),
                      "iters": a.iters, "mu": m["mu"]}))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "one", "bench", "summarize", "conditioning"):
        s = sub.add_parser(name)
        if name == "conditioning":
            s.add_argument("--graph", required=True)
            s.add_argument("--out")
            continue
        if name != "summarize":
            s.add_argument("--graph", required=True)
            s.add_argument("--iters", type=int, default=40)
        if name in ("run", "one"):
            s.add_argument("--options", default="a,b,base")
            s.add_argument("--ranks", type=int, default=4)
            s.add_argument("--lambdas", default="0.02,0.1,0.5")
            s.add_argument("--namespace", default="rq2026-recovery")
            s.add_argument("--out", required=True)
            s.add_argument("--ab-cap", type=int, default=-1, metavar="R",
                           help="hold the A/B prey's interaction to rank <= R in every fit (-1: no cap)")
            s.add_argument("--fitter", choices=FITTERS, default="minimal",
                           help="minimal (ridge ALS) or registered (map.py, item 7: the v4 §6 map)")
            s.add_argument("--start", choices=("warm", "cold"), default="warm",
                           help="the registered map's embedding start: SVD warm start (registered) or cold")
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
    a = ap.parse_args(argv)
    if a.cmd == "one":
        return one(a)
    if a.cmd == "run":
        return run(a)
    if a.cmd == "bench":
        return bench(a)
    if a.cmd == "conditioning":
        D = load_data(a.graph)
        rep = {opt: {f"rank{r}": conditioning(D, r, opt, r) for r in (1, 2, 3, 4)} for opt in OPTIONS}
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

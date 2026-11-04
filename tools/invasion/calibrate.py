#!/usr/bin/env python3
"""calibrate.py: null rejection rate, confidence-ball coverage and planted-cycle power of
infer.py's (and bounded.py's) tests, by simulation.

    calibrate.py --blocks DIR/blocks.json --key off/0.05/5.0 [--key ...] --out OUTDIR
                 [--sims 1000] [--B 999] [--kinds residual[,wild]] [--pilot-k K]
                 [--worlds iso,hetero,pilotcov,empirical,skew,concentrated,skewfactor,mixture,rare1,bounded]
                 [--design 20:10,28:10] [--design-sims 500] [--design-B 499]
                 [--omnibus 12:10:2:2] [--omnibus-sims 2000] [--omnibus-B 999] [--omnibus-plants all|none]
                 [--omnibus-tests both|flip] [--omnibus-worlds hetero-design,skew-design]
                 [--assay-corr R] [--bounded-null logistic] [--bnull-sims 300] [--bnull-B 199]
                 [--bank BANK/blocks.json --bank-plan PLAN.jsonl [--bank-spec SPEC.json] [--bank-exploratory]
                  [--bank-k 10] [--bank-sims 10000] [--bank-outer M]]
                 [--compound N:k:G [--compound-sims 2000] [--compound-variants all|null|nominal|target]]
                 [--workers 4] [--seed 1]

Every simulated dataset goes through exactly analyze.py's procedure (infer.block_stats,
infer's studentized unit bootstrap of kind --kinds, the replicate sign-flip), and the primary
configuration is infer.PRIMARY, the one analyze.py applies: the default bootstrap kind IS the
analysis default (review round 2: this tool used to default to the wild bootstrap). The
rejection rate at alpha is the fraction with p <= alpha; every rate carries its Clopper-Pearson
95% interval (the stats spec's binomial lower bound on power is its lower end).

PILOT SCALE (N, k of the block; --pilot-k sets k). Null worlds, built from the block (a pure
ladder: neither the ladder nor any column constant changes the tests, so most worlds carry
noise only):
  iso          iid Gaussian, one SD for every cell (the old chi-square test's assumption)
  hetero       independent Gaussian with the block's own per-cell SDs (they differ ~50x)
  pilotcov     Gaussian with each column's sample covariance shrunk halfway to its diagonal
  empirical    the block's own centred, variance-restored units, drawn WITH replacement (iid
               from the empirical distribution, any k; review round 3: drawing k of K units
               without replacement gave the means only (1 - k/K) of the noise)
  empirical-wor  that without-replacement draw, kept as a labelled diagnostic only
  skew         per-cell SDs, independent centred exponential errors (skewness 2)
  concentrated per-cell SDs plus a strong Gaussian common factor within each unit (+-1 loadings):
               curl noise concentrated in few directions
  skewfactor   concentrated, but factor AND errors centred exponential: skewed, concentrated
  mixture      per-cell SDs, a rare-event common factor within each unit (-c with probability
               0.95, +19c otherwise; mean 0, variance 1) on +-1 loadings, plus a small Gaussian
               part: bounded, skewed, occasional large effects
  rare1        review round 2's counterexample, exactly: ONE resident column whose replicate
               factor x = -0.002 (p 0.95) / +0.038 (p 0.05) loads +1 / -1 on two invaders, and a
               1e-4 jitter everywhere. Mean zero, bounded, and both tests break (k = 6: ~0.73
               rejection at alpha 0.05): the limit of what six replicates can represent
  bounded      endpoint scale: means = a pure additive ladder of the block's endpoint means (zq,
               shrunk to stay > 0), multiplicative skewed noise q = mu * M * e with a column-
               replicate common factor M ~ Gamma (CV 0.3) and cell noise e ~ Gamma matched to
               the block's per-cell SDs: positive, right-skewed, correlated within a unit
Old tests are evaluated on the same datasets for comparison (chi2, F(q, q(k-1))).
Confidence-ball coverage: the 95% ball (infer.confidence_ball's radius = the bootstrap's 95th
percentile of the edge-noise norm) covers the true edge mean iff ||A - A_true|| <= r95; the
share and d_C ranges derived from it cover whenever the ball does. Reported per world.

Planted-cycle power (pilot and design scale), on the same datasets (the bootstrap null does not
depend on the planted mean): divergence-free templates ('measured', 'diffuse', 'random',
'triangle') at RMS cyclic signal d_C per pair. The largest planted directed shift, max |d v|/2,
is reported against the endpoint floor (a losing invader cannot go below s = -f).

DESIGN SCALE, one condition (--design N:k): per-cell SDs drawn from the block, hetero / skew.

OMNIBUS DESIGN (--omnibus N:k:G:C, the stats spec's primary structure): G independent groups
(home regimes: other snapshots, other seeds) x C aligned conditions (assays, sharing units:
replicate noise correlated across them with --assay-corr, default the correlation measured
between the first two --key blocks if they share items, else 0). Per-cell SDs drawn from the
block; hetero-design (Gaussian) and skew-design (centred exponential) worlds. The omnibus
statistic F = sum T_C / sum tau_C over all G x C conditions, the grouped studentized bootstrap
(infer.bootstrap_groups) and the grouped sign-flip (infer.signflip_groups). Alternatives: a
diffuse cycle of RMS d_C in EVERY condition ('all'), in ONE condition only ('one'), and one
local triangle of per-edge amplitude 0.01 / 0.02 in one condition.

BOUNDED NULL (--bounded-null logistic): the block's endpoint means replaced by the fitted
bounded model (transitive, not additive), the block's own centred endpoint units as noise.
Reports how often the raw-scale lack of fit rejects (it should: a bounded ladder has curl) and
the null rejection rate of bounded.py's refitting residual test.

ERROR BANK (--bank BLOCKS.json, an analysis of a high-replication bank: its primary_blocks):
omnibus level / power with k units per column drawn WITH replacement from the bank's centred,
variance-restored units (the same draw for a regime's assays, regimes independent); 'bank-gauss'
draws Gaussian units with each column's joint cross-assay covariance; --bank-outer M resamples
the bank itself (finite-bank uncertainty, reported separately). The bank must BE the registered
one (review round 4): validate_bank checks it against the frozen BANK_SPEC (or --bank-spec) and
its plan (--bank-plan): exact assays and groups (the plan's cores, items included), every block
formal at the fixed-step horizon, replicates 0..K-1, aligned assays, unique keys, shapes; a bank
that fails is refused (exit 2) unless --bank-exploratory (rows keyed 'bank (exploratory)').

COMPOUND DECISION (--compound N:k:G): the frozen decision (H1, H1b, the claim = both rejected) in
a transitive bounded world: logistic ladders sigma(mu + a_i + b_j), support-preserving
zero-inflated Beta endpoints with the declared means exactly (zib_moments; infeasible SDs capped
and counted), and two families of alternatives (review round 4): the old nominal plants on the
probability scale (clipped; their achieved d_add / d_res and clipping in diag.csv) and feasible
logit-scale plants solved to a noiseless logistic-residual RMS d_res (the gate's effect
definition). A dataset whose H1b fit did not converge is a non-rejection, kept in the denominator.
Without --bank the --key blocks are the conditions and each dataset draws N items (with
replacement) from their fitted items and per-cell SDs from their cells; with --bank, each group /
condition is the bank's own primary block: its own fitted ladder over its own items and its own
cell SDs (key 'bank' in calib.csv), so N:G must be the bank's.

Outputs in OUTDIR: calib.csv (one row per key, scale, world, N, k, G, C, test, effect, alpha:
rate, its Clopper-Pearson interval, n), diag.csv (compound diagnostics: n, mean, SD, min, max of
each planted quantity), calib.md, and manifest.json (review round 2, P3): the SHA-256 of the
blocks file and of every tool source, the full arguments and seeds, the Python version, the bank
check, and the SHA-256 of the outputs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import multiprocessing
import os
import platform
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bounded  # noqa: E402
import hodge  # noqa: E402
import infer  # noqa: E402

ALPHAS = (0.05, 0.01, 0.0045, 0.05 / 12)   # 0.05/12: Holm's first step over hypotheses 1-11 + 1b
D_GRID = (0.0025, 0.005, 0.01, 0.02)
WORLDS = ("iso", "hetero", "pilotcov", "empirical", "skew", "concentrated", "skewfactor", "mixture", "rare1", "bounded")
CODE = ("calibrate.py", "infer.py", "hodge.py", "bounded.py")


def cholesky(S):
    n = len(S)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = S[i][j] - sum(L[i][t] * L[j][t] for t in range(j))
            if i == j:
                L[i][i] = math.sqrt(max(s, 1e-30))
            else:
                L[i][j] = s / L[j][j]
    return L


def cell_sds(z):
    N, k = len(z), len(z[0])
    out = [[0.0] * N for _ in range(N)]
    for p in range(N):
        for i in range(N):
            if i != p:
                v = [z[p][r][i] for r in range(k)]
                m = sum(v) / k
                out[p][i] = math.sqrt(sum((x - m) ** 2 for x in v) / (k - 1))
    return out


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _mix(rnd):
    """Rare-event factor: -c with probability 0.95, +19c otherwise (mean 0, variance 1)."""
    c = 1.0 / math.sqrt(19.0)
    return 19.0 * c if rnd.random() < 0.05 else -c


def _additive_means(zq):
    """A pure additive ladder (two-way fit) of the endpoint means, shrunk toward the grand mean
    until every cell is >= 0.003 (still additive). -> M[p][i] (column p, invader i)."""
    N = len(zq)
    m = infer.column_means(zq)
    Mx = [[(m[j][i] if i != j else None) for j in range(N)] for i in range(N)]
    mu, a, b, _ = hodge.twoway(Mx)
    lo = min(mu + a[i] + b[j] for i in range(N) for j in range(N) if i != j)
    t = 1.0 if lo >= 0.003 else (mu - 0.003) / (mu - lo)
    return [[(mu + t * (a[i] + b[p]) if i != p else 0.0) for i in range(N)] for p in range(N)]


class World:
    """Null generators built from one pilot block (see the module doc)."""

    def __init__(self, z, name, N=None, k=None, seed=0, zq=None):
        self.name = name
        self.N0, self.k0 = len(z), len(z[0])
        self.N = N or self.N0
        self.k = k or self.k0
        self.sds = cell_sds(z)
        flat = [self.sds[p][i] for p in range(self.N0) for i in range(self.N0) if i != p]
        self.sigma = math.sqrt(sum(s * s for s in flat) / len(flat))
        rnd = random.Random(seed + 17)
        if self.N != self.N0:   # design scale: per-cell SDs drawn from the pilot's distribution
            self.sds = [[0.0 if i == p else rnd.choice(flat) for i in range(self.N)] for p in range(self.N)]
        self.res = infer.residual_units(z)
        self.true_A = [0.0] * (self.N * (self.N - 1) // 2)
        if name == "pilotcov":
            self.L = []
            for p in range(self.N0):
                idx = [i for i in range(self.N0) if i != p]
                m = [sum(z[p][r][i] for r in range(self.k0)) / self.k0 for i in idx]
                C = [[sum((z[p][r][a] - m[x]) * (z[p][r][b] - m[y]) for r in range(self.k0)) / (self.k0 - 1)
                      for y, b in enumerate(idx)] for x, a in enumerate(idx)]
                C = [[C[x][y] * (1.0 if x == y else 0.5) for y in range(len(idx))] for x in range(len(idx))]
                self.L.append((idx, cholesky(C)))
        if name in ("concentrated", "skewfactor", "mixture"):
            self.lam = [[rnd.choice((-1.0, 1.0)) for _ in range(self.N)] for _ in range(self.N)]
        if name == "bounded":
            if zq is None:
                raise ValueError("world 'bounded' needs the block's endpoint units (blocks.json 'zq')")
            self.mu = _additive_means(zq)
            self.true_A = infer.antisym(self.mu)
            sq = cell_sds(zq)
            self.kM = 1.0 / 0.3 ** 2    # common factor CV 0.3
            self.ke = [[None] * self.N for _ in range(self.N)]
            for p in range(self.N):
                for i in range(self.N):
                    if i != p:
                        cv2 = (sq[p][i] / self.mu[p][i]) ** 2
                        x = (1.0 + cv2) / (1.0 + 1.0 / self.kM) - 1.0
                        self.ke[p][i] = 1.0 / x if x > 1e-9 else None   # None: no cell noise beyond the factor
        if name == "empirical-wor":
            # DIAGNOSTIC only: k of the K centred units WITHOUT replacement and without the variance
            # restoration. Its means carry only (1 - k/K) of the bank's noise (review round 3), so it
            # is not an iid null calibration.
            if self.k > self.k0:
                raise ValueError("empirical-wor needs k <= the block's replicates")
            self.res = [[[x / math.sqrt(self.k0 / (self.k0 - 1.0)) for x in u] for u in col] for col in self.res]

    def draw(self, rnd):
        N, k, nm = self.N, self.k, self.name
        z = []
        for p in range(N):
            col = []
            if nm == "empirical-wor":
                picks = rnd.sample(range(self.k0), k)
            for r in range(k):
                if nm == "iso":
                    u = [0.0 if i == p else self.sigma * rnd.gauss(0, 1) for i in range(N)]
                elif nm in ("hetero", "hetero-design"):
                    u = [0.0 if i == p else self.sds[p][i] * rnd.gauss(0, 1) for i in range(N)]
                elif nm in ("skew", "skew-design"):
                    u = [0.0 if i == p else self.sds[p][i] * (rnd.expovariate(1.0) - 1.0) for i in range(N)]
                elif nm == "concentrated":
                    h = rnd.gauss(0, 1)
                    u = [0.0 if i == p else self.sds[p][i] * (rnd.gauss(0, 1) + 2.0 * self.lam[p][i] * h) / math.sqrt(5.0)
                         for i in range(N)]
                elif nm == "skewfactor":
                    h = rnd.expovariate(1.0) - 1.0
                    u = [0.0 if i == p else self.sds[p][i] * ((rnd.expovariate(1.0) - 1.0) + 2.0 * self.lam[p][i] * h)
                         / math.sqrt(5.0) for i in range(N)]
                elif nm == "mixture":
                    h = _mix(rnd)
                    u = [0.0 if i == p else self.sds[p][i] * (math.sqrt(0.1) * rnd.gauss(0, 1)
                                                              + math.sqrt(0.9) * self.lam[p][i] * h) for i in range(N)]
                elif nm == "rare1":
                    u = [0.0 if i == p else 1e-4 * rnd.gauss(0, 1) for i in range(N)]
                    if p == 0:
                        x = 0.038 if rnd.random() < 0.05 else -0.002
                        u[1] += x
                        u[2] -= x
                elif nm == "bounded":
                    M = rnd.gammavariate(self.kM, 1.0 / self.kM)
                    u = [0.0] * N
                    for i in range(N):
                        if i != p:
                            ke = self.ke[p][i]
                            e = rnd.gammavariate(ke, 1.0 / ke) if ke else 1.0
                            u[i] = self.mu[p][i] * M * e
                elif nm == "empirical":
                    # iid draws from the centred, variance-restored units (WITH replacement, any k)
                    u = list(self.res[p][rnd.randrange(len(self.res[p]))])
                elif nm == "empirical-wor":
                    u = list(self.res[p][picks[r]])
                elif nm == "pilotcov":
                    idx, L = self.L[p]
                    g = [rnd.gauss(0, 1) for _ in idx]
                    u = [0.0] * N
                    for x, i in enumerate(idx):
                        u[i] = sum(L[x][t] * g[t] for t in range(x + 1))
                else:
                    raise ValueError(nm)
                col.append(u)
            z.append(col)
        return z


def old_tests(z):
    """The superseded lack-of-fit p-values (chi2 and its F counterpart) for comparison."""
    N, k = len(z), len(z[0])
    st = infer.block_stats(z)
    C_r = [infer.curl_vec(infer.antisym([z[p][r] for p in range(N)]), N)[0] for r in range(k)]
    P = len(C_r[0])
    EnC = 0.0
    for e in range(P):
        v = [c[e] for c in C_r]
        m = sum(v) / k
        EnC += sum((x - m) ** 2 for x in v) / (k - 1) / k
    df = (N - 1) * (N - 2) // 2
    X = df * st["TC"] / EnC if EnC > 0 else float("inf")
    return hodge.chi2_sf(X, df), hodge.f_sf(X / df, df, df * (k - 1))


def boot_null(groups, B, seed, kind):
    """-> sorted null F_C*, F_S*, T_C0*, and the 95th percentile of the edge-noise norm (of
    groups[0][0]) for the confidence ball."""
    b = infer.bootstrap_groups(groups, B=B, seed=seed, kind=kind)
    return (sorted(x["F_C"] for x in b), sorted(x["F_S"] for x in b), sorted(x["T_C0"] for x in b),
            infer.percentile([x["eA"] for x in b], 0.95))


def p_from(sorted_null, x):
    """(1 + #{null >= x}) / (B + 1) with a sorted null."""
    import bisect
    B = len(sorted_null)
    return (1 + B - bisect.bisect_left(sorted_null, x - 1e-15 * max(1.0, abs(x)))) / (B + 1)


# ----------------------------------------------------------------- tasks
G = {}


def _init(cfg):
    try:
        os.nice(19 - os.nice(0))
    except OSError:
        pass
    G.update(cfg)


class Counter:
    def __init__(self):
        self.cnt = {}
        self.st = {}    # (quantity, effect) -> [n, sum, sum of squares, min, max]: diagnostics

    def hit(self, test, effect, p, alphas=ALPHAS):
        """p None = no valid decision (e.g. an unconverged fit): counted as NOT rejected, and the
        dataset stays in the denominator (review round 4)."""
        for a in alphas:
            k_ = (test, effect, a)
            self.cnt[k_] = self.cnt.get(k_, 0) + (1 if p is not None and p <= a + 1e-15 else 0)

    def cover(self, test, ok):
        k_ = (test, "null", 0.95)
        self.cnt[k_] = self.cnt.get(k_, 0) + (1 if ok else 0)

    def stat(self, quantity, effect, x):
        s = self.st.setdefault((quantity, effect), [0, 0.0, 0.0, math.inf, -math.inf])
        s[0] += 1
        s[1] += x
        s[2] += x * x
        s[3] = min(s[3], x)
        s[4] = max(s[4], x)


def merge_stats(into, st):
    for k_, s in st.items():
        t = into.setdefault(k_, [0, 0.0, 0.0, math.inf, -math.inf])
        t[0] += s[0]
        t[1] += s[1]
        t[2] += s[2]
        t[3] = min(t[3], s[3])
        t[4] = max(t[4], s[4])


def task_pilot(args):
    """Pilot or single-condition design scale. -> (group key, counts, n)."""
    key, scale, wname, N, k, n, seed = args
    blk = G["blocks"][key]
    world = World(blk["z"], wname, N if scale == "design" else None, k if scale != "pilot" else G["pilot_k"],
                  seed=G["seed"], zq=blk.get("zq"))
    rnd = random.Random(seed)
    kinds = G["kinds"] if scale == "pilot" else [G["kinds"][0]]
    B = G["B"] if scale == "pilot" else G["design_B"]
    plants = G["plants"][(key, scale, N)]
    c = Counter()
    for _ in range(n):
        z = world.draw(rnd)
        st = infer.block_stats(z)
        if scale == "pilot":
            pc, pf = old_tests(z)
            c.hit("chi2 (superseded)", "null", pc)
            c.hit("F(q,q(k-1)) (superseded)", "null", pf)
        c.hit("sign-flip lof", "null", infer.signflip([z], "curl"))
        c.hit("sign-flip sym", "null", infer.signflip([z], "sym") if world.N >= 4 else None)
        bs = rnd.randrange(1 << 30)
        nulls = {}
        for kind in kinds:
            FC, FS, TC0, r95 = boot_null([[z]], B, bs, kind)
            nulls[kind] = FC
            c.hit(f"boot {kind} lof", "null", p_from(FC, infer._ratio(st["TC"], st["tauC"])))
            c.hit(f"boot {kind} sym", "null", p_from(FS, infer._ratio(st["TS"], st["tauS"])) if world.N >= 4 else None)
            if scale == "pilot":
                c.hit(f"boot {kind} lof unstudentized", "null", p_from(TC0, st["TC"]))
                dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(st["A"], world.true_A)))
                c.cover(f"ball coverage ({kind})", dist <= r95)
        prim = kinds[0]
        for label, v, d in plants:
            zp = infer.plant(z, v, d)
            sp = infer.block_stats(zp)
            c.hit(f"boot {prim} lof", label, p_from(nulls[prim], infer._ratio(sp["TC"], sp["tauC"])))
            c.hit("sign-flip lof", label, infer.signflip([zp], "curl"))
            if scale == "pilot":
                c.hit("chi2 (superseded)", label, old_tests(zp)[0])
    return (key, scale, wname, world.N, world.k, 1, 1), c.cnt, n


def omni_draw(worlds, rnd, rho):
    """One omnibus dataset: groups[g][c] = z of condition c in group g; within a group the C
    conditions' unit noise has correlation rho (a shared and an own component)."""
    out = []
    a, b = math.sqrt(max(0.0, rho)), math.sqrt(max(0.0, 1.0 - rho))
    for wg, C in worlds:
        shared = wg.draw(rnd)
        zs = []
        for _ in range(C):
            own = wg.draw(rnd)
            zs.append([[[a * x + b * y for x, y in zip(su, ou)] for su, ou in zip(sc, oc)] for sc, oc in zip(shared, own)])
        out.append(zs)
    return out


def task_omnibus(args):
    key, wname, N, k, Gn, C, n, seed = args
    z0 = G["blocks"][key]["z"]
    worlds = [(World(z0, wname, N, k, seed=G["seed"] + 101 * g), C) for g in range(Gn)]
    rnd = random.Random(seed)
    B, kind = G["omnibus_B"], G["kinds"][0]
    plants = G["omni_plants"][(N, Gn, C)]
    c = Counter()
    boot = G.get("omni_tests", "both") == "both"
    for _ in range(n):
        groups = omni_draw(worlds, rnd, G["rho"])
        bs = rnd.randrange(1 << 30)   # (drawn either way: the datasets do not depend on --omnibus-tests)
        FC = boot_null(groups, B, bs, kind)[0] if boot else None

        def stat(gs):
            st = [infer.block_stats(z) for zs in gs for z in zs]
            return infer._ratio(sum(s["TC"] for s in st), sum(s["tauC"] for s in st))
        if boot:
            c.hit(f"omnibus boot {kind}", "null", p_from(FC, stat(groups)))
        c.hit("omnibus sign-flip", "null", infer.signflip_groups(groups, "curl"))
        for label, spec in plants:
            gp = [[(infer.plant(z, *spec[(g, ci)]) if (g, ci) in spec else z) for ci, z in enumerate(zs)]
                  for g, zs in enumerate(groups)]
            if boot:
                c.hit(f"omnibus boot {kind}", label, p_from(FC, stat(gp)))
            c.hit("omnibus sign-flip", label, infer.signflip_groups(gp, "curl"))
    return (key, "omnibus", wname, N, k, Gn, C), c.cnt, n


def task_bnull(args):
    """Bounded null: endpoint means = the fitted bounded model, noise = the block's centred
    endpoint units resampled."""
    key, model, n, seed = args
    zq = G["blocks"][key]["zq"]
    N, k = len(zq), len(zq[0])
    m = infer.column_means(zq)
    M = [[(m[j][i] if i != j else None) for j in range(N)] for i in range(N)]
    F = bounded.fit(M, model)["F"]
    res = infer.residual_units(zq)
    rnd = random.Random(seed)
    c = Counter()
    for _ in range(n):
        z = [[[(F[i][p] + u[i]) if i != p else 0.0 for i in range(N)] for u in (res[p][rnd.randrange(k)] for _ in range(k))]
             for p in range(N)]
        inf = infer.infer([z], B=G["bnull_B"], seed=rnd.randrange(1 << 30), kind=G["kinds"][0])
        c.hit(f"raw lack of fit, boot {G['kinds'][0]}", "bounded ladder", inf["p_lof"])
        c.hit("raw lack of fit, sign-flip", "bounded ladder", inf["p_lof_flip"])
        t = bounded.model_test(z, model, B=G["bnull_B"], seed=rnd.randrange(1 << 30), kind=G["kinds"][0])
        c.hit(f"bounded {model} residual test", "null", t["p_res"])
        c.hit(f"bounded {model} residual sym test", "null", t["p_res_S"])
    return (key, "bnull", f"{model} + empirical units", N, k, 1, 1), c.cnt, n


# Review round 4, P2-4: an error bank is used only if it IS the registered bank. The frozen
# specification of the confirmation design's bank (bank1: two home regimes x the two assays,
# twelve items per regime, K = 50 replicates, the fixed-step horizon T = 13,500 at fraction 0.05);
# --bank-spec FILE replaces it for another registered bank, --bank-plan PLAN.jsonl is the
# registration it is checked against, and --bank-exploratory turns the refusals into warnings.
# Review round 5: strict validation also binds the bank to its APPROVED original plan (plan_sha256 =
# bank1/plan.jsonl as registered on 2026-11-02, so its items, snapshot hashes, seeds and policies), and checks
# the arena state policy, every assay's predator count and the run length explicitly.
BANK_SPEC = {"schema": "finfolk.invasion.bank-spec/2", "clock": "steps", "frac": 0.05, "G": 13500.0,
             "assays": ["off", "predA4"], "groups": 2, "items": 12, "K": 50,
             "state": "slot", "predators": {"off": 0, "predA4": 4}, "steps": 13500,
             "plan_sha256": "1040e6736a864e7794f47baf7ad4d17b04ebb2ed4631fb6431bd3834f6a00e77"}
BLOCKS_SCHEMA = "finfolk.invasion.blocks/2"


def plan_cores(cells):
    """Registered core membership {core: sorted items} of plan cells: an item belongs to the core
    of the cells it is the RESIDENT of (plan.py tags a cell with its resident's core; every core
    member has its own sham there), so a secondary cross-home cell adds nobody (review round 4)."""
    out = {}
    for c in cells:
        if c.get("core"):
            out.setdefault(c["core"], set()).add(c["resident_name"])
    return {k_: sorted(v) for k_, v in out.items()}


def _finite_shape(z, N, K, what):
    """Problems of one unit array z[p][r][i]: N columns of K replicate vectors of N finite values,
    zero on the diagonal."""
    if not isinstance(z, list) or len(z) != N:
        return [f"{what}: {len(z) if isinstance(z, list) else type(z).__name__} columns, expected {N}"]
    for p, col in enumerate(z):
        if not isinstance(col, list) or len(col) != K:
            return [f"{what}: column {p} has {len(col) if isinstance(col, list) else '?'} replicates, expected {K}"]
        for r, u in enumerate(col):
            if not isinstance(u, list) or len(u) != N:
                return [f"{what}: column {p} replicate {r} is not a vector of {N}"]
            if u[p] != 0.0 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in u):
                return [f"{what}: column {p} replicate {r}: non-finite value or nonzero diagonal"]
    return []


def validate_bank(bb, spec, plan_cells=None, plan_sha=None):
    """Check an analysis' blocks.json against the frozen bank specification (and, given the plan,
    against its registration): schema, the fixed-step clock, exactly the spec's assays and number
    of groups at (frac, G), unique (group, assay) keys, every block formal, `items` items and
    replicates 0..K-1 in every block, aligned items and replicates across a group's assays,
    disjoint groups, the shapes / finiteness of z and zq; with a plan: its hash is the one the
    analysis bound AND the spec's approved plan_sha256 (review round 5: so items, snapshot hashes,
    seeds and policies are the registered ones), the groups are its cores with exactly their items,
    the assays are its conditions at frac, every core cell registers replicates 0..K-1, and its
    state policy, predator counts and run length are the spec's.
    -> (groups, assays, {(group, assay): block}, problems)."""
    probs = []
    if bb.get("schema") != BLOCKS_SCHEMA:
        probs.append(f"blocks schema {bb.get('schema')!r} is not {BLOCKS_SCHEMA!r}")
    if bb.get("clock") != spec["clock"]:
        probs.append(f"the bank was analysed on the {bb.get('clock')!r} clock; the spec registers {spec['clock']!r}")
    pbs = [b for b in bb.get("primary_blocks", []) if b.get("frac") == spec["frac"] and float(b.get("G", -1)) == float(spec["G"])]
    if not pbs:
        probs.append(f"no primary blocks at fraction {spec['frac']} / window {spec['G']}")
        return [], [], {}, probs
    keys = [(b["group"], b["cond"]) for b in pbs]
    dup = sorted({x for x in keys if keys.count(x) > 1})
    if dup:
        probs.append(f"duplicate (group, assay) blocks: {dup}")
    byk = {(b["group"], b["cond"]): b for b in pbs}
    gnames = sorted({g_ for g_, _ in keys})
    cnames = sorted({c_ for _, c_ in keys})
    if cnames != sorted(spec["assays"]):
        probs.append(f"assays {cnames}, the spec registers {sorted(spec['assays'])}")
    if len(gnames) != spec["groups"]:
        probs.append(f"{len(gnames)} group(s) {gnames}, the spec registers {spec['groups']}")
    K = spec["K"]
    for g_ in gnames:
        for c_ in spec["assays"]:
            if (g_, c_) not in byk:
                probs.append(f"group {g_}: no {c_} block")
        bs = [byk[(g_, c_)] for c_ in cnames if (g_, c_) in byk]
        for b in bs:
            tag = f"{g_}/{b['cond']}"
            if b.get("status") != "formal":
                probs.append(f"{tag}: status {b.get('status')!r} (only a formal block is the registered one)")
            if len(b.get("names", [])) != spec["items"]:
                probs.append(f"{tag}: {len(b.get('names', []))} items, the spec registers {spec['items']}")
            if list(b.get("reps", [])) != list(range(K)):
                probs.append(f"{tag}: replicates {b.get('reps', [])[:3]}... ({len(b.get('reps', []))}), "
                             f"the spec registers 0..{K - 1}")
            for what in ("z", "zq"):
                if what not in b:
                    probs.append(f"{tag}: no {what} units")
                else:
                    probs += _finite_shape(b[what], len(b.get("names", [])), len(b.get("reps", [])), f"{tag} {what}")
        if any(b["names"] != bs[0]["names"] or b["reps"] != bs[0]["reps"] for b in bs):
            probs.append(f"group {g_}: its assays differ in items or replicates (units must align)")
    seen = {}
    for g_ in gnames:
        for nm in byk.get((g_, cnames[0]), {}).get("names", []):
            if nm in seen and seen[nm] != g_:
                probs.append(f"item {nm} is in groups {seen[nm]} and {g_}")
            seen[nm] = g_
    if plan_cells is None:
        probs.append("no --bank-plan: the bank's registration (cores, assays, replicates, plan hash) is unchecked")
    else:
        if plan_sha != bb.get("plan_sha256"):
            probs.append(f"the analysis bound plan {str(bb.get('plan_sha256'))[:12]}, --bank-plan is {plan_sha[:12]}")
        if not spec.get("plan_sha256"):
            probs.append("the spec names no approved plan (plan_sha256): the registration itself is unbound")
        elif plan_sha != spec["plan_sha256"]:
            probs.append(f"--bank-plan {plan_sha[:12]} is not the approved registration {spec['plan_sha256'][:12]}")
        core = [c for c in plan_cells if c.get("core") and c["fraction"] == spec["frac"]]
        for fld, what in (("state", "arena state policy"), ("steps", "run length")):
            bad = sorted({str(c.get(fld)) for c in core if fld in spec and c.get(fld) != spec[fld]})
            if bad:
                probs.append(f"the plan's {what} {bad} is not the spec's {spec[fld]!r}")
        if "predators" in spec:
            bad = sorted({(c["condition"], c.get("predators")) for c in core
                          if c.get("predators") != spec["predators"].get(c["condition"])})
            if bad:
                probs.append(f"predator counts {bad[:4]} differ from the spec's {spec['predators']}")
        cores = plan_cores(plan_cells)
        got = {g_: sorted(byk[(g_, cnames[0])]["names"]) for g_ in gnames if (g_, cnames[0]) in byk}
        if cores != got:
            probs.append(f"the groups / items are not the plan's registered cores ({sorted(cores)} vs {sorted(got)})")
        conds = sorted({c["condition"] for c in plan_cells if c["fraction"] == spec["frac"]})
        if conds != sorted(spec["assays"]):
            probs.append(f"the plan registers conditions {conds} at {spec['frac']}, the spec {sorted(spec['assays'])}")
        reps = {}
        for c in plan_cells:
            if c.get("core") and c["mode"] in ("invade", "sham") and c["fraction"] == spec["frac"]:
                reps.setdefault((c["condition"], c["invader_name"], c["resident_name"]), set()).add(c["replicate"])
        if any(v != set(range(K)) for v in reps.values()):
            probs.append(f"the plan's core cells do not all register replicates 0..{K - 1}")
    return gnames, cnames, byk, probs


def _bank_groups(bank, outer_seed=None):
    """The bank's primary blocks as groups[g][c] of centred, variance-restored units (K per column).
    With outer_seed, first resample each column's K raw units with replacement (the same indices
    for every condition of a group: the assays' units are aligned), for finite-bank uncertainty."""
    out = []
    rnd = random.Random(outer_seed) if outer_seed is not None else None
    for zs in bank:
        N, K = len(zs[0]), len(zs[0][0])
        if rnd is not None:
            idx = [[rnd.randrange(K) for _ in range(K)] for _ in range(N)]
            zs = [[[z[p][i] for i in idx[p]] for p in range(N)] for z in zs]
        out.append([infer.residual_units(z) for z in zs])
    return out


def _bank_cov(res_g):
    """Per column p of a group: the Cholesky factor of the joint covariance of the conditions'
    unit residuals (vectors over invaders i != p, concatenated over conditions)."""
    N, K = len(res_g[0]), len(res_g[0][0])
    out = []
    for p in range(N):
        idx = [(c, i) for c in range(len(res_g)) for i in range(N) if i != p]
        vecs = [[res_g[c][p][r][i] for c, i in idx] for r in range(K)]
        S = [[sum(v[a] * v[b] for v in vecs) / K for b in range(len(idx))] for a in range(len(idx))]
        out.append((idx, cholesky(S)))
    return out


def task_bank(args):
    """Omnibus calibration from an error bank (review round 3): k units per column drawn WITH
    replacement from the bank's centred, variance-restored units, the same draw for every assay of
    a group (aligned units), independently across groups; world 'bank-gauss' draws Gaussian units
    with each column's joint (cross-assay) covariance instead. outer >= 0: the draws come from an
    outer resample of the bank (finite-bank uncertainty)."""
    world, k, n, outer, seed = args
    groups0 = _bank_groups(G["bank"], None if outer < 0 else G["seed"] * 7919 + outer)
    covs = [_bank_cov(rg) for rg in groups0] if world == "bank-gauss" else None
    rnd = random.Random(seed)
    B, kind = G["omnibus_B"], G["kinds"][0]
    N = len(groups0[0][0])
    plants = G["bank_plants"]
    c = Counter()
    for _ in range(n):
        groups = []
        for g, rg in enumerate(groups0):
            C = len(rg)
            zs = [[None] * N for _ in range(C)]
            for p in range(N):
                if world == "bank":
                    K = len(rg[0][p])
                    pick = [rnd.randrange(K) for _ in range(k)]
                    for ci in range(C):
                        zs[ci][p] = [list(rg[ci][p][i]) for i in pick]
                else:
                    idx, L = covs[g][p]
                    for ci in range(C):
                        zs[ci][p] = []
                    for _r in range(k):
                        e = [rnd.gauss(0, 1) for _ in idx]
                        v = [sum(L[a][t] * e[t] for t in range(a + 1)) for a in range(len(idx))]
                        rows = [[0.0] * N for _ in range(C)]
                        for (ci, i), x in zip(idx, v):
                            rows[ci][i] = x
                        for ci in range(C):
                            zs[ci][p].append(rows[ci])
            groups.append(zs)
        bs = rnd.randrange(1 << 30)
        FC = boot_null(groups, B, bs, kind)[0] if G.get("omni_tests", "both") == "both" else None

        def stat(gs):
            st = [infer.block_stats(z) for zs_ in gs for z in zs_]
            return infer._ratio(sum(s["TC"] for s in st), sum(s["tauC"] for s in st))
        if FC is not None:
            c.hit(f"omnibus boot {kind}", "null", p_from(FC, stat(groups)))
        c.hit("omnibus sign-flip", "null", infer.signflip_groups(groups, "curl"))
        for label, spec in plants:
            gp = [[(infer.plant(z, *spec[(g, ci)]) if (g, ci) in spec else z) for ci, z in enumerate(zs_)]
                  for g, zs_ in enumerate(groups)]
            if FC is not None:
                c.hit(f"omnibus boot {kind}", label, p_from(FC, stat(gp)))
            c.hit("omnibus sign-flip", label, infer.signflip_groups(gp, "curl"))
    C0 = len(groups0[0])
    return (G.get("bank_label", "bank"), "bank", world + ("" if outer < 0 else f" outer{outer}"), N, k, len(groups0),
            C0), c.cnt, n


ZIB_PZ = 0.05        # exact-zero probability of a losing invader (mu < ZIB_LOSING), as in the pilot
ZIB_LOSING = 0.03
ZIB_VMAX = 0.9       # the Beta part's variance stays <= 0.9 mb (1 - mb) (phi >= 1/9: no degenerate U)


def zib_moments(mu, sd):
    """The zero-inflated Beta endpoint law for mean mu and SD sd (review round 4: the MEAN is exact,
    never clipped, so a null world's declared means are the generator's means; the SD is exact
    whenever it is feasible). X = 0 with probability pz, else Beta with mean mb = mu / (1 - pz) and
    variance vb, so E X = mu and Var X = (1 - pz)(vb + mb^2) - mu^2.
      pz   ZIB_PZ for a losing invader (mu < ZIB_LOSING: exact zeros), lowered to half of
           sd^2 / (sd^2 + mu^2) where the zeros alone would exceed the requested variance;
      vb   from the requested variance; feasible iff sd^2 < mu (1 - mu) (the Bernoulli bound,
           whatever pz); kept <= ZIB_VMAX mb (1 - mb): a request beyond it is CAPPED (flagged,
           its achieved SD returned).
    A mean outside (0, 1) has only the point mass (flagged 'boundary').
    -> {pz, mb, vb, sd (achieved), capped, boundary}."""
    s2 = sd * sd
    if not 0.0 < mu < 1.0:
        return {"pz": 0.0, "mb": min(max(mu, 0.0), 1.0), "vb": 0.0, "sd": 0.0, "capped": sd > 0, "boundary": True}
    pz = min(ZIB_PZ, 0.5 * s2 / (s2 + mu * mu)) if mu < ZIB_LOSING and s2 > 0 else 0.0
    mb = mu / (1.0 - pz)
    vb = (s2 + mu * mu) / (1.0 - pz) - mb * mb
    vmax = ZIB_VMAX * mb * (1.0 - mb)
    capped = vb > vmax
    vb = min(max(vb, 0.0), vmax)
    return {"pz": pz, "mb": mb, "vb": vb, "sd": math.sqrt(max(0.0, (1.0 - pz) * (vb + mb * mb) - mu * mu)),
            "capped": capped, "boundary": False}


def _zib(rnd, mu, sd):
    """One support-preserving endpoint draw in [0, 1] with mean exactly mu (zib_moments)."""
    m = zib_moments(mu, sd)
    if m["pz"] and rnd.random() < m["pz"]:
        return 0.0
    mb, vb = m["mb"], m["vb"]
    if m["boundary"] or vb <= 1e-15 * mb * (1.0 - mb):
        return mb
    phi = mb * (1.0 - mb) / vb - 1.0
    return rnd.betavariate(mb * phi, (1.0 - mb) * phi)


# ------------------------------------------------- planted alternatives in the compound world
# Review round 4, P2-5: a nominal plant (+d v / 2 on the means of the probability scale) leaves
# [0, 1] near the floor and was clipped, so its achieved effect was unmeasured. Every alternative
# now reports what was planted: clipped cells and their magnitude, d_add = the RMS added
# circulation per pair (||Q A(mean - null mean)|| / sqrt(P), after clipping), and d_res = the
# NOISELESS residual RMS per pair after refitting the logistic model (||Q A(mean - logistic fit)|| /
# sqrt(P)) - the cyclic signal beyond the logistic family that H1b tests. The gate's target is
# defined on d_res: the 'feasible' plants put a divergence-free cycle on the LOGIT scale,
# mean = sigmoid(eta + c v / 2 ...), inside (0, 1) for every c (no clipping), with c solved per
# block so that d_res = the target exactly (relative tolerance PLANT_TOL).
PLANT_CLIP = (0.002, 0.998)
PLANT_TOL = 1e-4


def _cols_to_M(mean):
    """Column layout mean[p][i] (invader i into resident p) -> M[i][j] (diagonal None)."""
    N = len(mean)
    return [[(mean[j][i] if i != j else None) for j in range(N)] for i in range(N)]


def _plant_cols(x, v, d):
    """+d v_pq / 2 on p -> q (column q, entry p), -d v_pq / 2 on q -> p (as infer.plant)."""
    N = len(x)
    out = [row[:] for row in x]
    e = 0
    for p in range(N):
        for q in range(p + 1, N):
            h = 0.5 * d * v[e]
            out[q][p] += h
            out[p][q] -= h
            e += 1
    return out


def _ladder(par, t, N):
    """The fitted ladder over items t: (eta, mean) in column layout and its parameters in
    bounded.Model's identifiable form (effects centred), so a refit can start exactly there."""
    eta = [[(par["mu"] + par["a"][t[i]] + par["b"][t[p]]) if i != p else 0.0 for i in range(N)] for p in range(N)]
    mean = [[bounded.sigmoid(eta[p][i]) if i != p else 0.0 for i in range(N)] for p in range(N)]
    a = [par["a"][x] for x in t]
    b = [par["b"][x] for x in t]
    ma, mb = sum(a) / N, sum(b) / N
    th = [par["mu"] + ma + mb] + [x - ma for x in a[:N - 1]] + [x - mb for x in b[:N - 1]]
    return eta, mean, th


def _curl_rms(M, F):
    """sqrt(||Q A(M - F)||^2 / P): the RMS cyclic part per pair of M - F (M[i][j] layout)."""
    N = len(M)
    return math.sqrt(max(0.0, bounded.energies(bounded._sub(M, F))[1]) / (N * (N - 1) // 2))


def plant_diagnostics(mean, mean0, th0):
    """-> (d_add, d_res, refit converged, theta of the refit) of a noiseless planted mean."""
    M, M0 = _cols_to_M(mean), _cols_to_M(mean0)
    f = bounded.fit(M, "logistic", th0)
    return _curl_rms(M, M0), _curl_rms(M, f["F"]), bool(f["converged"]), f["theta"]


def nominal_plant(mean0, v, d):
    """The old plant: +d v / 2 on the probability-scale means, clipped to PLANT_CLIP.
    -> (mean, clipped cells, sum |clip|, max |clip|)."""
    mean = _plant_cols(mean0, v, d)
    n, tot, mx = 0, 0.0, 0.0
    lo, hi = PLANT_CLIP
    N = len(mean)
    for p in range(N):
        for i in range(N):
            if i != p and not lo <= mean[p][i] <= hi:
                x = min(max(mean[p][i], lo), hi)
                n += 1
                tot += abs(x - mean[p][i])
                mx = max(mx, abs(x - mean[p][i]))
                mean[p][i] = x
    return mean, n, tot, mx


def feasible_plant(eta, mean0, th0, v, target, iters=40):
    """The logit-scale plant at noiseless residual RMS d_res = target (see above): Illinois
    regula falsi on c, each step one logistic refit (warm-started). -> dict(mean, c, d_add, d_res,
    converged (the refit), solved (|d_res - target| <= PLANT_TOL target), evals)."""
    N = len(eta)
    g = [bounded.sigmoid(eta[p][i]) * (1.0 - bounded.sigmoid(eta[p][i])) for p in range(N) for i in range(N) if i != p]
    warm = [list(th0)]

    def at(c):
        e2 = _plant_cols(eta, v, c)
        m = [[bounded.sigmoid(e2[p][i]) if i != p else 0.0 for i in range(N)] for p in range(N)]
        d_add, d_res, ok, th = plant_diagnostics(m, mean0, warm[0])
        warm[0] = th
        return d_res - target, {"mean": m, "c": c, "d_add": d_add, "d_res": d_res, "converged": ok}
    a, fa = 0.0, -target                        # d_res(0) = 0: the null ladder is a logistic one
    b = target / max(sum(g) / len(g), 1e-6)     # first order: d_res ~ c x the mean slope sigma'(eta)
    fb, best = at(b)
    evals = 1
    while fb < 0 and evals < iters:             # bracket (d_res saturates: a target can be out of reach)
        a, fa = b, fb
        b *= 2.0
        fb, x = at(b)
        evals += 1
        best = x if abs(fb) < abs(best["d_res"] - target) else best
    side = 0
    while fb >= 0 > fa and abs(best["d_res"] - target) > PLANT_TOL * target and evals < iters:
        c = b - fb * (b - a) / (fb - fa)         # Illinois regula falsi, bracket [a, b]
        fc, x = at(c)
        evals += 1
        if abs(fc) < abs(best["d_res"] - target):
            best = x
        if fc >= 0:
            b, fb = c, fc
            if side == 1:
                fa *= 0.5
            side = 1
        else:
            a, fa = c, fc
            if side == -1:
                fb *= 0.5
            side = -1
    best["solved"] = abs(best["d_res"] - target) <= PLANT_TOL * target
    best["evals"] = evals
    return best


def task_compound(args):
    """The frozen confirmatory decision at design scale (review round 3): H1 (raw grouped sign-flip
    omnibus), H1b (bounded.residual_omnibus sign-flip) and the claim (both <= alpha), under a
    TRANSITIVE bounded world: per group (home regime) N items drawn from the pilot's items, each
    assay's endpoint means the pilot block's fitted logistic ladder sigma(mu + a_i + b_j), cells'
    SDs drawn from that block's endpoint SDs, support-preserving zero-inflated Beta endpoints
    (zib_moments: the means EXACT, the SDs exact where feasible, capped SDs counted).
    With an error bank (keys None): each group / condition is the bank's own primary block - its
    fitted ladder over its own items (not resampled) and its cells' own SDs.
    Review round 4: the null's means are the ladder itself (no clipping ever); alternatives are the
    old nominal plants (probability scale, clipped, now measured: d_add, d_res, clipping) and the
    feasible logit-scale plants at a registered d_res (see feasible_plant); a dataset whose H1b fit
    did not converge counts as a non-rejection and stays in the denominator (its count reported)."""
    keys, N, k, Gn, n, variants, seed = args
    fits, pools = [], []
    srcs = ([[(G["bank_zq"][g][c]) for c in range(len(G["bank_zq"][g]))] for g in range(len(G["bank_zq"]))]
            if keys is None else [[G["blocks"][key]["zq"] for key in keys]] * Gn)
    src_ok = True   # review round 5: the source ladders are the registered fits only if every fit converged
    for g in range(Gn):
        fg, pg = [], []
        for zq in srcs[g]:
            sf = _source_fit(zq)
            src_ok = src_ok and bool(sf["converged"])
            fg.append(sf["params"])
            sq = cell_sds(zq)
            pg.append(sq if keys is None else [sq[p][i] for p in range(len(zq)) for i in range(len(zq)) if i != p])
        fits.append(fg)
        pools.append(pg)
    N0 = len(fits[0][0]["a"])
    C = len(srcs[0])
    rnd = random.Random(seed)
    tmpl = [infer.cycle_template(N, "diffuse", seed=5 + g) for g in range(Gn)]
    c = Counter()
    vlist = compound_variants(variants)
    if keys is None and N != N0:
        raise ValueError("compound from a bank: N must be the bank's item count")
    # with a bank the items (hence every noiseless mean and plant) are the same in every dataset:
    # each plant is built once per worker
    cache = G.setdefault("_plants", {}) if keys is None else None
    for _ in range(n):
        if keys is None:   # the bank's own items and cells
            items = [list(range(N)) for _ in range(Gn)]
            sds = [[pools[g][ci] for ci in range(C)] for g in range(Gn)]
        else:
            items = [[rnd.randrange(N0) for _ in range(N)] for _ in range(Gn)]
            sds = [[[[rnd.choice(pools[g][ci]) if i != p else 0.0 for i in range(N)] for p in range(N)] for ci in range(C)]
                   for g in range(Gn)]
        base = {(g, ci): _ladder(fits[g][ci], items[g], N) for g in range(Gn) for ci in range(C)}
        plants = {} if cache is None else cache   # (family, d, g, ci) -> the planted mean and its diagnostics

        def planted(fam, d, g, ci):
            key_ = (fam, d, g, ci)
            if key_ not in plants:
                eta, mean0, th0 = base[(g, ci)]
                if fam == "nominal":
                    mean, ncl, tot, mx = nominal_plant(mean0, tmpl[g], d)
                    d_add, d_res, ok, _ = plant_diagnostics(mean, mean0, th0)
                    plants[key_] = {"mean": mean, "clipped": ncl, "clip_sum": tot, "clip_max": mx, "d_add": d_add,
                                    "d_res": d_res, "converged": ok, "solved": True}
                else:
                    x = feasible_plant(eta, mean0, th0, tmpl[g], d)
                    x.update(clipped=0, clip_sum=0.0, clip_max=0.0)
                    plants[key_] = x
            return plants[key_]
        for label, fam, d, where in vlist:
            groups = []
            ncl = ncap = nbound = ncells = 0
            clip_max, ratio_min, unsolved, refit_bad = 0.0, 1.0, 0, 0
            for g in range(Gn):
                zs = []
                for ci in range(C):
                    mean = base[(g, ci)][1]   # the null mean: exactly the ladder (never clipped)
                    if d and (where == "all" or (g, ci) == (0, 0)):
                        x = planted(fam, d, g, ci)
                        mean = x["mean"]
                        ncl += x["clipped"]
                        clip_max = max(clip_max, x["clip_max"])
                        unsolved += not x["solved"]
                        refit_bad += not x["converged"]
                        c.stat("d_add: RMS added circulation per planted condition", label, x["d_add"])
                        c.stat("d_res: noiseless logistic-residual RMS per planted condition", label, x["d_res"])
                        c.stat("clipped cells per planted condition", label, x["clipped"])
                        c.stat("|clip| summed per planted condition", label, x["clip_sum"])
                        if fam == "target":
                            c.stat("logit plant scale c", label, x["c"])
                            c.stat("refits to solve the plant", label, x["evals"])
                    for p in range(N):
                        for i in range(N):
                            if i != p:
                                m_ = zib_moments(mean[p][i], sds[g][ci][p][i])
                                ncells += 1
                                ncap += m_["capped"]
                                nbound += m_["boundary"]
                                if sds[g][ci][p][i] > 0:
                                    ratio_min = min(ratio_min, m_["sd"] / sds[g][ci][p][i])
                    zs.append([[[_zib(rnd, mean[p][i], sds[g][ci][p][i]) if i != p else 0.0 for i in range(N)]
                                for _ in range(k)] for p in range(N)])
                groups.append(zs)
            # review round 5: a dataset is evidence about its label only if its world was built as
            # registered - every source fit converged and, for a feasible plant, every planted block was
            # solved to its target with a converged noiseless refit. Otherwise it is a FAILED dataset:
            # no test is run, it stays in the denominator as a non-rejection (a power failure), counted.
            built = src_ok and not (fam == "target" and (unsolved or refit_bad))
            if built:
                p1 = infer.signflip_groups(groups, "curl")
                ro = bounded.residual_omnibus(groups)
                p1b = ro["p_flip"]   # None: H1b invalid (a fit did not converge) -> no rejection, still counted
            else:
                p1 = p1b = None
                ro = {"valid": False}
            c.hit("H1 raw sign-flip omnibus", label, p1)
            c.hit("H1b logistic residual sign-flip omnibus", label, p1b)
            c.hit("claim: H1 and H1b", label, max(p1, p1b) if p1b is not None and p1 is not None else None)
            c.cover(f"world not built as registered (source fit or plant failed; counted as a failure): {label}",
                    not built)
            c.cover(f"H1b invalid (a logistic fit did not converge): {label}", built and not ro["valid"])
            c.cover(f"all four fits converged: {label}", ro["valid"])
            c.cover(f"feasible (no clipped mean): {label}", ncl == 0)
            c.cover(f"feasible SDs (no capped cell, no boundary mean): {label}", ncap == 0 and nbound == 0)
            if d:
                c.cover(f"plant at its target (feasible family: solved; refits converged): {label}",
                        unsolved == 0 and refit_bad == 0)
            c.stat("cells with a capped SD (share)", label, ncap / ncells)
            c.stat("achieved / requested SD, smallest cell", label, ratio_min)
            c.stat("max |clip| over planted cells", label, clip_max)
    world = ("logistic ladder + zero-inflated Beta" if keys is not None
             else "the bank's own logistic ladders + zero-inflated Beta")
    return ((G.get("bank_label", "bank") if keys is None else "compound"), "compound", world, N, k, Gn, C), c.cnt, n, c.st


def _source_fit(zq):
    """The logistic fit of a source block (pilot or bank) that defines a compound world's ladder."""
    return bounded.fit_matrix(zq)


def compound_variants(which):
    """(label, family, d, where) of the compound world. 'nominal' = the old probability-scale plant
    (clipped; d = its nominal d_C), 'target' = the feasible logit-scale plant at d_res = d."""
    out = [("bounded ladder", None, 0.0, "all")]
    if which in ("all", "nominal"):
        out += [(f"bounded ladder + d_C={d} in all conditions", "nominal", d, "all") for d in (0.01, 0.02, 0.03)]
        out += [(f"bounded ladder + d_C={d} in one condition", "nominal", d, "one") for d in (0.02, 0.03)]
    if which in ("all", "target"):
        out += [(f"bounded ladder + feasible plant d_res={d} in all conditions", "target", d, "all")
                for d in (0.01, 0.02, 0.03)]
        out += [(f"bounded ladder + feasible plant d_res={d} in one condition", "target", d, "one") for d in (0.02, 0.03)]
    return out


def task_bdesign(args):
    """Design scale for the bounded residual test: a transitive logistic ladder sigma(mu + a_i +
    b_j) with (a_i, b_i) drawn from the block's fitted items, per-cell SDs drawn from the block's
    endpoint units (Gaussian), and diffuse cycles planted on top. Reports how often the raw-scale
    lack of fit (bootstrap, sign-flip) and the bounded logistic residual test reject."""
    key, model, N, k, n, seed = args
    zq = G["blocks"][key]["zq"]
    N0 = len(zq)
    m = infer.column_means(zq)
    M0 = [[(m[j][i] if i != j else None) for j in range(N0)] for i in range(N0)]
    par = bounded.fit(M0, model)["params"]
    sq = cell_sds(zq)
    pool = [sq[p][i] for p in range(N0) for i in range(N0) if i != p]
    rnd = random.Random(seed)
    B = G["bdesign_B"]
    c = Counter()
    for _ in range(n):
        items = [rnd.randrange(N0) for _ in range(N)]
        a_ = [par["a"][t] for t in items]
        b_ = [par["b"][t] for t in items]
        F = [[bounded.sigmoid(par["mu"] + a_[i] + b_[j]) if i != j else None for j in range(N)] for i in range(N)]
        sds = [[rnd.choice(pool) if i != p else 0.0 for i in range(N)] for p in range(N)]
        noise = [[[sds[p][i] * rnd.gauss(0, 1) if i != p else 0.0 for i in range(N)] for _ in range(k)] for p in range(N)]
        for label, d in [("bounded ladder", 0.0)] + [(f"bounded ladder + diffuse d_C={d}", d) for d in (0.01, 0.02)]:
            v = infer.cycle_template(N, "diffuse", seed=5)
            z = [[[(F[i][p] + u[i]) if i != p else 0.0 for i in range(N)] for u in col] for p, col in enumerate(noise)]
            if d:
                z = infer.plant(z, v, d)
            s0 = rnd.randrange(1 << 30)
            inf = infer.infer([z], B=B, seed=s0, kind=G["kinds"][0])
            c.hit(f"raw lack of fit, boot {G['kinds'][0]}", label, inf["p_lof"])
            c.hit("raw lack of fit, sign-flip", label, inf["p_lof_flip"])
            t = bounded.model_test(z, model, B=B, seed=s0, kind=G["kinds"][0])
            c.hit(f"bounded {model} residual test", label, t["p_res"])
    return (key, "bdesign", f"{model} ladder + hetero", N, k, 1, 1), c.cnt, n


def plant_list(z, scale, N):
    """(label, template, d) for the power part."""
    out = []
    P = N * (N - 1) // 2
    for tk in ("diffuse", "random"):
        v = infer.cycle_template(N, tk, seed=5)
        for d in D_GRID:
            out.append((f"{tk} d_C={d}", v, d))
    tri = infer.cycle_template(N, "triangle")
    for a in (0.01, 0.02, 0.04):
        out.append((f"triangle edge={a}", tri, a * math.sqrt(3.0 / P)))
    inf = infer.infer([z], B=199, seed=1)
    if scale == "pilot":
        A = infer.block_stats(z)["A"]
        c = infer.curl_vec(A, N)[0]
        nrm = math.sqrt(sum(x * x for x in c) / P)
        vm = [x / nrm for x in c]
        for d in D_GRID:
            out.append((f"measured d_C={d}", vm, d))
        out.append((f"measured d_C=observed {inf['dC']:.4f}", vm, inf["dC"]))
    else:
        dG = math.sqrt(max(0.0, inf["G_nc"]) / len(infer.block_stats(z)["A"]))
        v = infer.cycle_template(N, "diffuse", seed=5)
        for rho in (0.035, 0.07):
            d = dG * math.sqrt(rho / (1 - rho))
            out.append((f"diffuse share={rho} (d_C={d:.4f})", v, d))
    return out


def omni_plants(N, Gn, C):
    """(label, {(group, condition): (template, d)}) for the omnibus design."""
    P = N * (N - 1) // 2
    tmpl = [infer.cycle_template(N, "diffuse", seed=5 + g) for g in range(Gn)]
    tri = infer.cycle_template(N, "triangle")
    out = []
    for d in D_GRID:
        out.append((f"all conditions d_C={d}", {(g, ci): (tmpl[g], d) for g in range(Gn) for ci in range(C)}))
        out.append((f"one condition d_C={d}", {(0, 0): (tmpl[0], d)}))
    for a in (0.01, 0.02):
        out.append((f"one triangle edge={a}", {(0, 0): (tri, a * math.sqrt(3.0 / P))}))
    return out


def assay_corr(za, zb):
    """Correlation of the two conditions' centred unit residuals, cell by cell."""
    ra, rb = infer.residual_units(za), infer.residual_units(zb)
    xs, ys = [], []
    for p in range(len(za)):
        for r in range(len(za[0])):
            for i in range(len(za)):
                if i != p:
                    xs.append(ra[p][r][i])
                    ys.append(rb[p][r][i])
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx > 0 and sy > 0 else 0.0


def max_shift(plants):
    """Largest planted directed shift max |d v_e| / 2 (feasibility against the bounded score)."""
    out = 0.0
    for p in plants:
        specs = p[1].values() if isinstance(p[1], dict) else [(p[1], p[2])]
        for v, d in specs:
            out = max(out, max(abs(d * x) / 2 for x in v))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--blocks", required=True)
    ap.add_argument("--key", action="append", required=True, help="cond/frac/G, e.g. off/0.05/5.0")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sims", type=int, default=1000)
    ap.add_argument("--B", type=int, default=999)
    ap.add_argument("--kinds", default=infer.PRIMARY["kind"],
                    help=f"bootstrap kinds; the first is the primary one and must be the analysis default "
                         f"({infer.PRIMARY['kind']}, infer.PRIMARY) unless --allow-other-primary")
    ap.add_argument("--allow-other-primary", action="store_true")
    ap.add_argument("--worlds", default="iso,hetero,pilotcov,empirical,skew,concentrated,skewfactor,mixture,rare1,bounded")
    ap.add_argument("--pilot-k", type=int, default=None, help="pilot-scale replicates (default the block's k); "
                    "the empirical world then subsamples real units without replacement")
    ap.add_argument("--no-plants", action="store_true", help="null worlds only")
    ap.add_argument("--design", default="", help="single-condition design-scale N:k list, e.g. 20:10,28:10")
    ap.add_argument("--design-sims", type=int, default=500)
    ap.add_argument("--design-B", type=int, default=499)
    ap.add_argument("--omnibus", default="", help="omnibus design N:k:G:C list, e.g. 12:10:2:2")
    ap.add_argument("--omnibus-sims", type=int, default=2000)
    ap.add_argument("--omnibus-B", type=int, default=999)
    ap.add_argument("--omnibus-worlds", default="hetero-design,skew-design")
    ap.add_argument("--omnibus-plants", default="all", choices=["all", "none"])
    ap.add_argument("--omnibus-tests", default="both", choices=["both", "flip"],
                    help="'flip': the sign-flip only, no bootstrap (cheap: large null counts for that test)")
    ap.add_argument("--assay-corr", type=float, default=None)
    ap.add_argument("--bounded-null", default="", help="bounded models for the bounded-null check, e.g. logistic")
    ap.add_argument("--bnull-sims", type=int, default=300)
    ap.add_argument("--bnull-B", type=int, default=199)
    ap.add_argument("--bounded-design", default="", help="N:k list for the bounded residual test at design scale "
                    "(model from --bounded-null, default logistic)")
    ap.add_argument("--bdesign-sims", type=int, default=200)
    ap.add_argument("--bdesign-B", type=int, default=499)
    ap.add_argument("--bank", help="an error bank's analysis blocks.json (primary_blocks): omnibus calibration "
                    "by resampling its units WITH replacement, assays jointly, regimes independently")
    ap.add_argument("--bank-spec", help="the registered bank specification (JSON, keys of calibrate.BANK_SPEC); "
                    "default: the frozen confirmation bank (2 groups x off / predA4, 12 items, K = 50, T = 13500)")
    ap.add_argument("--bank-plan", help="the bank's registered plan (JSONL): its hash, cores, conditions and "
                    "replicates must be the bank's (required unless --bank-exploratory)")
    ap.add_argument("--bank-exploratory", action="store_true",
                    help="run a bank that fails the specification anyway, rows labelled 'bank (exploratory)'")
    ap.add_argument("--bank-frac", type=float, default=None, help="(overrides the spec: exploratory only)")
    ap.add_argument("--bank-G", type=float, default=None, help="(overrides the spec: exploratory only)")
    ap.add_argument("--bank-k", type=int, default=10)
    ap.add_argument("--bank-sims", type=int, default=10000)
    ap.add_argument("--bank-worlds", default="bank,bank-gauss")
    ap.add_argument("--bank-outer", type=int, default=0, help="outer resamples of the bank (finite-bank uncertainty)")
    ap.add_argument("--bank-inner", type=int, default=500, help="datasets per outer resample")
    ap.add_argument("--compound", default="", help="N:k:G for the frozen decision (H1, H1b, claim) in a transitive "
                    "bounded world; the --key blocks are the conditions (assays), their endpoint units the source; "
                    "with --bank, the bank's own primary blocks (items, fits and cell SDs) are")
    ap.add_argument("--compound-sims", type=int, default=2000)
    ap.add_argument("--compound-variants", default="all", choices=["all", "null", "nominal", "target"],
                    help="'nominal': the null + the old clipped plants; 'target': the null + the feasible plants at "
                         "d_res; 'all' both")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--chunk", type=int, default=50)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    if not 1 <= a.workers <= 4:
        ap.error("--workers must be 1..4")
    kinds = a.kinds.split(",")
    if kinds[0] != infer.PRIMARY["kind"] and not a.allow_other_primary:
        ap.error(f"the primary bootstrap kind must be the analysis default {infer.PRIMARY['kind']!r} "
                 "(infer.PRIMARY), or pass --allow-other-primary")
    t0 = time.time()
    code = {f: sha256(os.path.join(HERE, f)) for f in CODE}   # at start: the code that runs
    blocks_sha = sha256(a.blocks)
    os.makedirs(a.out, exist_ok=True)
    bj = json.load(open(a.blocks))
    blocks = {f"{b['cond']}/{b['frac']}/{b['G']}": b for b in bj["blocks"]}
    for key in a.key:
        if key not in blocks:
            raise SystemExit(f"no block {key} in {a.blocks} (have {sorted(blocks)})")
        if blocks[key]["status"] != "formal":
            print(f"note: block {key} is {blocks[key]['status']}", file=sys.stderr)
    worlds = [w for w in a.worlds.split(",") if w]
    design = [tuple(int(x) for x in d.split(":")) for d in a.design.split(",") if d]
    omni = [tuple(int(x) for x in d.split(":")) for d in a.omnibus.split(",") if d]
    rho = a.assay_corr
    if rho is None:
        k0, k1 = (a.key + [None])[:2]
        rho = 0.0
        if k1 and blocks[k0]["names"] == blocks[k1]["names"] and blocks[k0]["reps"] == blocks[k1]["reps"]:
            rho = assay_corr(blocks[k0]["z"], blocks[k1]["z"])
    plants, oplants, tasks = {}, {}, []
    sd = a.seed * 1000003
    for key in a.key:
        z = blocks[key]["z"]
        N0, k0 = len(z), len(z[0])
        plants[(key, "pilot", N0)] = [] if a.no_plants else plant_list(z, "pilot", N0)
        for w in worlds:
            if w == "bounded" and "zq" not in blocks[key]:
                print(f"note: world 'bounded' skipped for {key}: no endpoint units in {a.blocks}", file=sys.stderr)
                continue
            for c0 in range(0, a.sims, a.chunk):
                sd += 1
                tasks.append(("pilot", (key, "pilot", w, N0, k0, min(a.chunk, a.sims - c0), sd)))
        for N, k in design:
            if (key, "design", N) not in plants:
                plants[(key, "design", N)] = [] if a.no_plants else plant_list(z, "design", N)
            for w in ("hetero-design", "skew-design"):
                for c0 in range(0, a.design_sims, a.chunk):
                    sd += 1
                    tasks.append(("pilot", (key, "design", w, N, k, min(a.chunk, a.design_sims - c0), sd)))
    for N, k, Gn, C in omni:
        oplants[(N, Gn, C)] = omni_plants(N, Gn, C) if a.omnibus_plants == "all" else []
        for w in a.omnibus_worlds.split(","):
            for c0 in range(0, a.omnibus_sims, a.chunk):
                sd += 1
                tasks.append(("omnibus", (a.key[0], w, N, k, Gn, C, min(a.chunk, a.omnibus_sims - c0), sd)))
    for model in [m for m in a.bounded_null.split(",") if m]:
        for key in a.key:
            if "zq" not in blocks[key]:
                continue
            for c0 in range(0, a.bnull_sims, 25):
                sd += 1
                tasks.append(("bnull", (key, model, min(25, a.bnull_sims - c0), sd)))
    bdes = [tuple(int(x) for x in d.split(":")) for d in a.bounded_design.split(",") if d]
    for N, k in bdes:
        model = ([m for m in a.bounded_null.split(",") if m] or ["logistic"])[0]
        if "zq" not in blocks[a.key[0]]:
            raise SystemExit("--bounded-design needs endpoint units (zq) in the blocks file")
        for c0 in range(0, a.bdesign_sims, 10):
            sd += 1
            tasks.append(("bdesign", (a.key[0], model, N, k, min(10, a.bdesign_sims - c0), sd)))
    bank, bank_info, bank_plants, bank_label = None, None, [], "bank"
    if a.bank:
        bb = json.load(open(a.bank))
        spec = dict(BANK_SPEC)
        if a.bank_spec:
            spec.update(json.load(open(a.bank_spec)))
        for opt, fld in ((a.bank_frac, "frac"), (a.bank_G, "G")):
            if opt is not None and float(opt) != float(spec[fld]):
                spec[fld] = opt   # an explicit override is a different specification: exploratory only
                spec.setdefault("overridden", []).append(fld)
        plan_cells = [json.loads(ln) for ln in open(a.bank_plan) if ln.strip()] if a.bank_plan else None
        gnames, cnames, byk, bprobs = validate_bank(bb, spec, plan_cells, sha256(a.bank_plan) if a.bank_plan else None)
        if spec.get("overridden"):
            bprobs.append(f"--bank-frac / --bank-G override the frozen spec ({spec['overridden']})")
        if bprobs:
            msg = f"--bank {a.bank} is not the registered bank:\n  " + "\n  ".join(bprobs)
            if not a.bank_exploratory:
                print(msg + "\n(--bank-exploratory runs it anyway, labelled exploratory)", file=sys.stderr)
                return 2
            print("EXPLORATORY: " + msg, file=sys.stderr)
            bank_label = "bank (exploratory)"
        bank = []
        for g_ in gnames:
            bs_ = [byk[(g_, c_)] for c_ in cnames if (g_, c_) in byk]
            if any(b["names"] != bs_[0]["names"] or b["reps"] != bs_[0]["reps"] for b in bs_) or len(bs_) != len(cnames):
                raise SystemExit(f"bank group {g_}: conditions differ in items or replicates (units must align)")
            bank.append([b["z"] for b in bs_])
        if not bank:
            raise SystemExit(f"no primary blocks at {spec['frac']} / {spec['G']} in {a.bank}")
        Nb = len(bank[0][0])
        bank_plants = omni_plants(Nb, len(gnames), len(cnames)) if a.omnibus_plants == "all" else []
        bank_info = {"path": os.path.abspath(a.bank), "sha256": sha256(a.bank), "groups": gnames, "conditions": cnames,
                     "N": Nb, "K": len(bank[0][0][0]), "spec": spec, "problems": bprobs, "label": bank_label,
                     "plan": {"path": os.path.abspath(a.bank_plan), "sha256": sha256(a.bank_plan)} if a.bank_plan else None,
                     "status": {f"{g_}/{c_}": b["status"] for (g_, c_), b in byk.items()}}
        for w in a.bank_worlds.split(","):
            for c0 in range(0, a.bank_sims, a.chunk):
                sd += 1
                tasks.append(("bank", (w, a.bank_k, min(a.chunk, a.bank_sims - c0), -1, sd)))
        for o in range(a.bank_outer):
            for c0 in range(0, a.bank_inner, a.chunk):
                sd += 1
                tasks.append(("bank", ("bank", a.bank_k, min(a.chunk, a.bank_inner - c0), o, sd)))
    bank_zq = None
    if a.compound:
        Nc, kc, Gc = (int(x) for x in a.compound.split(":"))
        if bank is not None:   # the bank's own four primary blocks (groups x assays)
            if any("zq" not in byk[(g_, c_)] for g_ in gnames for c_ in cnames):
                raise SystemExit("--compound with --bank: the bank's primary blocks lack endpoint units (zq)")
            bank_zq = [[byk[(g_, c_)]["zq"] for c_ in cnames] for g_ in gnames]
            if Gc != len(gnames) or Nc != len(bank_zq[0][0]):
                raise SystemExit(f"--compound with --bank: use {len(bank_zq[0][0])}:k:{len(gnames)}")
            ckeys = None
        else:
            if any("zq" not in blocks[k_] for k_ in a.key):
                raise SystemExit("--compound needs endpoint units (zq) for every --key block")
            ckeys = list(a.key)
        for c0 in range(0, a.compound_sims, 10):
            sd += 1
            tasks.append(("compound", (ckeys, Nc, kc, Gc, min(10, a.compound_sims - c0), a.compound_variants, sd)))
    cfg = {"blocks": {k_: {"z": blocks[k_]["z"], "zq": blocks[k_].get("zq")} for k_ in a.key}, "kinds": kinds,
           "B": a.B, "design_B": a.design_B, "omnibus_B": a.omnibus_B, "bnull_B": a.bnull_B, "plants": plants,
           "omni_plants": oplants, "seed": a.seed, "pilot_k": a.pilot_k, "rho": rho, "bdesign_B": a.bdesign_B,
           "omni_tests": a.omnibus_tests, "bank": bank, "bank_plants": bank_plants, "bank_zq": bank_zq,
           "bank_label": bank_label}
    acc = {}
    with multiprocessing.Pool(a.workers, initializer=_init, initargs=(cfg,)) as pool:
        it = pool.imap_unordered(_dispatch, [(fn_name, args) for fn_name, args in tasks])
        for done, (gk, cnt, n, *st) in enumerate(it, 1):
            g = acc.setdefault(gk, [{}, 0, {}])
            for t, v in cnt.items():
                g[0][t] = g[0].get(t, 0) + v
            g[1] += n
            if st:
                merge_stats(g[2], st[0])
            if done % 20 == 0 or done == len(tasks):
                print(f"{done}/{len(tasks)} chunks", flush=True)
    rows, drows = [], []
    Bs = {"pilot": a.B, "design": a.design_B, "omnibus": a.omnibus_B, "bnull": a.bnull_B, "bdesign": a.bdesign_B,
          "bank": a.omnibus_B, "compound": 0}
    for (key, scale, w, N, k, Gn, C), (cnt, n, st) in sorted(acc.items()):
        for (test, effect, alpha), v in sorted(cnt.items()):
            rate = v / n
            lo, hi = hodge.clopper_pearson(v, n)
            rows.append({"key": key, "scale": scale, "world": w, "N": N, "k": k, "G": Gn, "C": C, "test": test,
                         "effect": effect, "alpha": alpha, "x": v, "n": n, "rate": rate, "cp_lo": lo, "cp_hi": hi,
                         "B": Bs[scale]})
        for (q, effect), (m_, s1, s2, mn, mx) in sorted(st.items()):
            mu_ = s1 / m_
            drows.append({"key": key, "scale": scale, "world": w, "N": N, "k": k, "G": Gn, "C": C, "quantity": q,
                          "effect": effect, "n": m_, "mean": mu_,
                          "sd": math.sqrt(max(0.0, (s2 - m_ * mu_ * mu_) / (m_ - 1))) if m_ > 1 else 0.0,
                          "min": mn, "max": mx})
    if not drows and os.path.exists(os.path.join(a.out, "diag.csv")):
        os.remove(os.path.join(a.out, "diag.csv"))   # (a stale one from an earlier run in OUTDIR)
    if drows:   # the compound world's diagnostics: what each alternative planted, how feasible its moments were
        with open(os.path.join(a.out, "diag.csv"), "w", newline="") as f:
            w_ = csv.DictWriter(f, fieldnames=list(drows[0]))
            w_.writeheader()
            for r in drows:
                w_.writerow({c: (repr(v) if isinstance(v, float) else v) for c, v in r.items()})
    with open(os.path.join(a.out, "calib.csv"), "w", newline="") as f:
        w_ = csv.DictWriter(f, fieldnames=list(rows[0]))
        w_.writeheader()
        for r in rows:
            w_.writerow({c: (repr(v) if isinstance(v, float) else v) for c, v in r.items()})
    md = report(a, bj, blocks, rows, plants, oplants, kinds, worlds, design, omni, rho)
    if drows:
        md.append("\n## Compound world diagnostics (diag.csv): what each variant planted, how feasible its moments were\n")
        md.append("d_add = RMS added circulation per pair (after clipping); d_res = the noiseless residual RMS per pair "
                  "after refitting the logistic model (the signal beyond the logistic family that H1b tests). "
                  "'nominal' plants are the old probability-scale ones (clipped to [0.002, 0.998]); 'feasible plant "
                  "d_res=x' plants a logit-scale cycle solved to d_res = x. Null means are never clipped.\n")
        md.append("| world | N:k:G:C | quantity | effect | n | mean | min | max |\n|---|---|---|---|---|---|---|---|")
        for r in drows:
            md.append(f"| {r['world']} | {r['N']}:{r['k']}:{r['G']}:{r['C']} | {r['quantity']} | {r['effect']} | {r['n']} | "
                      f"{r['mean']:.6g} | {r['min']:.6g} | {r['max']:.6g} |")
    if bank_info and bank_info["problems"]:
        md.append("\n**EXPLORATORY bank (not the registered specification):** " + "; ".join(bank_info["problems"]) + "\n")
    open(os.path.join(a.out, "calib.md"), "w").write("\n".join(md) + "\n")
    man = {"schema": "finfolk.invasion.calibration/1",
           "blocks": {"path": os.path.abspath(a.blocks), "sha256": blocks_sha,
                      "plan_sha256": bj.get("plan_sha256"), "analysis_sha256": bj.get("analysis_sha256"),
                      "keys": {k_: {"status": blocks[k_]["status"], "names": blocks[k_]["names"], "reps": blocks[k_]["reps"]}
                               for k_ in a.key}},
           "code": code,
           "primary": infer.PRIMARY, "args": vars(a), "seed": a.seed, "task_seeds": [t[1][-1] for t in tasks],
           "assay_corr": rho, "python": platform.python_version(), "wall_s": time.time() - t0, "bank": bank_info,
           "alpha_family": bounded.ALPHA_FAMILY,
           "outputs": {f: sha256(os.path.join(a.out, f)) for f in ("calib.csv", "calib.md", "diag.csv")
                       if os.path.exists(os.path.join(a.out, f))}}
    with open(os.path.join(a.out, "manifest.json"), "w") as f:
        f.write(json.dumps(man, indent=1, sort_keys=True, default=str) + "\n")
    print("\n".join(md))
    return 0


def _dispatch(x):
    fn_name, args = x
    return {"pilot": task_pilot, "omnibus": task_omnibus, "bnull": task_bnull, "bdesign": task_bdesign,
            "bank": task_bank, "compound": task_compound}[fn_name](args)


def _fmt_rate(r):
    return f"{r['rate']:.3f} [{r['cp_lo']:.3f}, {r['cp_hi']:.3f}]"


def report(a, bj, blocks, rows, plants, oplants, kinds, worlds, design, omni, rho):
    def get(**kw):
        return [r for r in rows if all(r[k_] == v for k_, v in kw.items())]

    def rate(sel, nd=3):
        return f"{sel[0]['rate']:.{nd}f}" if sel else "-"
    md = ["# Null calibration, coverage and power (calibrate.py)\n",
          f"blocks: `{a.blocks}` (sha256 {sha256(a.blocks)[:16]}; plan {bj.get('plan_sha256', '')[:16]}, analysis "
          f"{bj.get('analysis_sha256', '')[:16]}); pilot-scale sims {a.sims} x B {a.B}; design-scale sims "
          f"{a.design_sims} x B {a.design_B}; omnibus sims {a.omnibus_sims} x B {a.omnibus_B}; kinds {kinds} "
          f"(primary test {infer.PRIMARY['test']!r}, kind {infer.PRIMARY['kind']!r} = infer.PRIMARY); seed {a.seed}; "
          f"assay correlation {rho:.3f}. Rates: p <= alpha, [Clopper-Pearson 95%]. Provenance: manifest.json.\n"]
    for key in a.key:
        nul = [r for r in rows if r["key"] == key and r["scale"] == "pilot" and r["effect"] == "null"]
        if not nul:
            continue
        md.append(f"\n## {key}: null rejection rate (p <= alpha) and 95% ball coverage, pilot scale (N {nul[0]['N']}, k {nul[0]['k']})\n")
        tests = sorted({r["test"] for r in nul if not r["test"].startswith("ball")})
        md.append("| world | test | " + " | ".join(f"alpha {x}" for x in ALPHAS) + " |\n|---|---|" + "---|" * len(ALPHAS))
        for w in worlds:
            for t in tests:
                rr = {r["alpha"]: r for r in nul if (r["world"], r["test"]) == (w, t)}
                if rr:
                    md.append(f"| {w} | {t} | " + " | ".join(_fmt_rate(rr[x]) for x in ALPHAS if x in rr) + " |")
        md.append("\n| world | ball coverage (nominal 0.95) |\n|---|---|")
        for w in worlds:
            for r in nul:
                if r["world"] == w and r["test"].startswith("ball"):
                    md.append(f"| {w} | {r['test']}: {_fmt_rate(r)} |")
        eff = [p[0] for p in plants.get((key, "pilot", nul[0]["N"]), [])]
        if eff:
            md.append(f"\n## {key}: power (p <= alpha), pilot scale: bootstrap ({kinds[0]}) / sign-flip / superseded chi2\n")
            md.append(f"Largest planted directed shift {max_shift(plants[(key, 'pilot', nul[0]['N'])]):.4f} (a losing invader's "
                      "s cannot fall below -f ~ -0.05; check feasibility before interpreting large plants).\n")
            md.append("| world | effect | boot a=0.05 | boot a=0.0045 | flip a=0.05 | flip a=0.0045 | chi2 a=0.05 |\n|---|---|---|---|---|---|---|")
            for w in worlds:
                for e in eff:
                    base = dict(key=key, scale="pilot", world=w, effect=e)
                    md.append(f"| {w} | {e} | {rate(get(test=f'boot {kinds[0]} lof', alpha=0.05, **base))} | "
                              f"{rate(get(test=f'boot {kinds[0]} lof', alpha=0.0045, **base))} | "
                              f"{rate(get(test='sign-flip lof', alpha=0.05, **base))} | "
                              f"{rate(get(test='sign-flip lof', alpha=0.0045, **base))} | "
                              f"{rate(get(test='chi2 (superseded)', alpha=0.05, **base))} |")
        if design:
            md.append(f"\n## {key}: single-condition design scale (per-cell SDs drawn from this block), {kinds[0]} bootstrap\n")
            md.append("| world | N | k | effect | boot a=0.05 | boot a=0.0045 [CP 95%] | flip a=0.05 | flip a=0.0045 [CP 95%] |\n|---|---|---|---|---|---|---|---|")
            for N, k in design:
                eff = ["null"] + [p[0] for p in plants[(key, "design", N)]]
                for w in ("hetero-design", "skew-design"):
                    for e in eff:
                        base = dict(key=key, scale="design", world=w, N=N, k=k, effect=e)
                        bb = get(test=f"boot {kinds[0]} lof", alpha=0.0045, **base)
                        ff = get(test="sign-flip lof", alpha=0.0045, **base)
                        md.append(f"| {w} | {N} | {k} | {e} | {rate(get(test=f'boot {kinds[0]} lof', alpha=0.05, **base))} | "
                                  f"{_fmt_rate(bb[0]) if bb else '-'} | {rate(get(test='sign-flip lof', alpha=0.05, **base))} | "
                                  f"{_fmt_rate(ff[0]) if ff else '-'} |")
    if omni:
        md.append(f"\n## Omnibus design (G independent groups x C aligned conditions; per-cell SDs from {a.key[0]}; "
                  f"assay correlation {rho:.3f})\n")
        md.append("The stats spec's hypothesis 1: F = sum T_C / sum tau_C over every condition. Power = P(p <= alpha); "
                  "alpha 0.0045 = 0.05/11 (Holm's first step). [Clopper-Pearson 95%]; the spec's criterion is a lower "
                  "bound >= 0.80 at d_min = 0.01.\n")
        md.append("| world | N:k:G:C | effect | boot a=0.05 | boot a=0.0045 | sign-flip a=0.05 | sign-flip a=0.0045 |\n|---|---|---|---|---|---|---|")
        for N, k, Gn, C in omni:
            eff = ["null"] + [p[0] for p in oplants[(N, Gn, C)]]
            for w in a.omnibus_worlds.split(","):
                for e in eff:
                    base = dict(scale="omnibus", world=w, N=N, k=k, G=Gn, C=C, effect=e)
                    cells = []
                    for t in (f"omnibus boot {kinds[0]}", "omnibus sign-flip"):
                        for al in (0.05, 0.0045):
                            s_ = get(test=t, alpha=al, **base)
                            cells.append(_fmt_rate(s_[0]) if s_ else "-")
                    md.append(f"| {w} | {N}:{k}:{Gn}:{C} | {e} | " + " | ".join(cells) + " |")
            md.append(f"\nLargest planted directed shift at {N}:{k}:{Gn}:{C}: {max_shift(oplants[(N, Gn, C)]):.4f}.\n")
    for scale, title in (("bank", "Error bank: omnibus level / power from the bank's units (with replacement; assays joint, "
                                  "regimes independent; 'outerN' = an outer resample of the bank)"),
                         ("compound", "The frozen decision: H1, H1b and the claim (both <= alpha) in a transitive bounded "
                                      "world (logistic ladders, zero-inflated Beta endpoints)")):
        sel = [r for r in rows if r["scale"] == scale]
        if not sel:
            continue
        md.append(f"\n## {title}\n")
        md.append(f"alpha_family = 0.05/12 = {bounded.ALPHA_FAMILY:.5f}. Rates [Clopper-Pearson 95%].\n")
        md.append("| world | N:k:G:C | test | effect | a=0.05 | a=0.05/12 |\n|---|---|---|---|---|---|")
        for (w, N, k, Gn, C, t, e) in sorted({(r["world"], r["N"], r["k"], r["G"], r["C"], r["test"], r["effect"]) for r in sel}):
            rr = {r["alpha"]: r for r in sel if (r["world"], r["N"], r["k"], r["G"], r["C"], r["test"], r["effect"]) == (w, N, k, Gn, C, t, e)}
            cells_ = [(_fmt_rate(rr[al]) if al in rr else "-") for al in (0.05, bounded.ALPHA_FAMILY)]
            if 0.95 in rr:
                cells_ = [_fmt_rate(rr[0.95]), "(share)"]
            md.append(f"| {w} | {N}:{k}:{Gn}:{C} | {t} | {e} | " + " | ".join(cells_) + " |")
        if scale == "bank":
            outs = {}
            for r in sel:
                if "outer" in r["world"] and r["test"] == "omnibus sign-flip" and r["effect"] == "null" and r["alpha"] == 0.05:
                    outs[r["world"]] = r["rate"]
            if len(outs) >= 2:
                v = list(outs.values())
                mu_ = sum(v) / len(v)
                md.append(f"\nFinite-bank uncertainty (sign-flip level at 0.05 over {len(v)} outer resamples of the bank): "
                          f"mean {mu_:.4f}, SD {math.sqrt(sum((x - mu_) ** 2 for x in v) / (len(v) - 1)):.4f} "
                          "(includes the inner binomial noise).\n")
    for scale, title in (("bnull", "Bounded null: a transitive bounded ladder (the block's fitted model) plus the block's own endpoint noise"),
                         ("bdesign", "Bounded design scale: a transitive logistic ladder of pilot strength, hetero noise, diffuse cycles on top")):
        bn = [r for r in rows if r["scale"] == scale]
        if not bn:
            continue
        md.append(f"\n## {title}\n")
        md.append("A rejection by the raw-scale lack of fit under a bounded ladder is a 'cycle' that is only the bounded "
                  "scale; the bounded residual test should hold its level there and detect cycles planted on top.\n")
        md.append("| key | world | N | k | test | effect | a=0.05 | a=0.01 | a=0.0045 |\n|---|---|---|---|---|---|---|---|---|")
        for key in a.key:
            for (N, k, t, e) in sorted({(r["N"], r["k"], r["test"], r["effect"]) for r in bn if r["key"] == key}):
                rr = {r["alpha"]: r for r in bn if (r["key"], r["N"], r["k"], r["test"], r["effect"]) == (key, N, k, t, e)}
                r0 = next(iter(rr.values()))
                md.append(f"| {key} | {r0['world']} | {N} | {k} | {t} | {e} | " + " | ".join(_fmt_rate(rr[x]) for x in ALPHAS) + " |")
    return md


if __name__ == "__main__":
    sys.exit(main())

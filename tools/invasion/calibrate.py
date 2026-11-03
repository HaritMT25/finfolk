#!/usr/bin/env python3
"""calibrate.py: null rejection rate, confidence-ball coverage and planted-cycle power of
infer.py's (and bounded.py's) tests, by simulation.

    calibrate.py --blocks DIR/blocks.json --key off/0.05/5.0 [--key ...] --out OUTDIR
                 [--sims 1000] [--B 999] [--kinds residual[,wild]] [--pilot-k K]
                 [--worlds iso,hetero,pilotcov,empirical,skew,concentrated,skewfactor,mixture,rare1,bounded]
                 [--design 20:10,28:10] [--design-sims 500] [--design-B 499]
                 [--omnibus 12:10:2:2] [--omnibus-sims 2000] [--omnibus-B 999] [--omnibus-plants all|none]
                 [--assay-corr R] [--bounded-null logistic] [--bnull-sims 300] [--bnull-B 199]
                 [--workers 4] [--seed 1]

Every simulated dataset goes through exactly analyze.py's procedure (infer.block_stats,
infer's studentized unit bootstrap of kind --kinds, the replicate sign-flip), and the primary
configuration is infer.PRIMARY, the one analyze.py applies: the default bootstrap kind IS the
analysis default (review round 2: this tool used to default to the wild bootstrap). The
rejection rate at alpha is the fraction with p <= alpha; every rate carries its Clopper-Pearson
95% interval (the stats spec's binomial lower bound on power is its lower end).

PILOT SCALE (N, k of the block; --pilot-k K subsamples K of the block's units, without
replacement, in the 'empirical' world: the hook for a higher-replication real-engine null
block, where K real units out of many give a far better-identified error distribution than
six). Null worlds, built from the block (a pure ladder: neither the ladder nor any column
constant changes the tests, so most worlds carry noise only):
  iso          iid Gaussian, one SD for every cell (the old chi-square test's assumption)
  hetero       independent Gaussian with the block's own per-cell SDs (they differ ~50x)
  pilotcov     Gaussian with each column's sample covariance shrunk halfway to its diagonal
  empirical    the block's own centred, variance-restored units, resampled (real shapes)
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

Outputs in OUTDIR: calib.csv (one row per key, scale, world, N, k, G, C, test, effect, alpha:
rate, its Clopper-Pearson interval, n), calib.md, and manifest.json (review round 2, P3): the
SHA-256 of the blocks file and of every tool source, the full arguments and seeds, the Python
version, and the SHA-256 of calib.csv / calib.md.
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

ALPHAS = (0.05, 0.01, 0.0045)
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
        if name == "empirical" and self.k < self.k0:
            self.res = [[[x / math.sqrt(self.k0 / (self.k0 - 1.0)) for x in u] for u in col] for col in self.res]

    def draw(self, rnd):
        N, k, nm = self.N, self.k, self.name
        z = []
        for p in range(N):
            col = []
            if nm == "empirical" and k < self.k0:   # subsample k real units without replacement
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
                    u = list(self.res[p][picks[r]] if k < self.k0 else self.res[p][rnd.randrange(len(self.res[p]))])
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

    def hit(self, test, effect, p, alphas=ALPHAS):
        for a in alphas:
            k_ = (test, effect, a)
            self.cnt[k_] = self.cnt.get(k_, 0) + (1 if p is not None and p <= a + 1e-15 else 0)

    def cover(self, test, ok):
        k_ = (test, "null", 0.95)
        self.cnt[k_] = self.cnt.get(k_, 0) + (1 if ok else 0)


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
    for _ in range(n):
        groups = omni_draw(worlds, rnd, G["rho"])
        FC = boot_null(groups, B, rnd.randrange(1 << 30), kind)[0]

        def stat(gs):
            st = [infer.block_stats(z) for zs in gs for z in zs]
            return infer._ratio(sum(s["TC"] for s in st), sum(s["tauC"] for s in st))
        c.hit(f"omnibus boot {kind}", "null", p_from(FC, stat(groups)))
        c.hit("omnibus sign-flip", "null", infer.signflip_groups(groups, "curl"))
        for label, spec in plants:
            gp = [[(infer.plant(z, *spec[(g, ci)]) if (g, ci) in spec else z) for ci, z in enumerate(zs)]
                  for g, zs in enumerate(groups)]
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
    ap.add_argument("--assay-corr", type=float, default=None)
    ap.add_argument("--bounded-null", default="", help="bounded models for the bounded-null check, e.g. logistic")
    ap.add_argument("--bnull-sims", type=int, default=300)
    ap.add_argument("--bnull-B", type=int, default=199)
    ap.add_argument("--bounded-design", default="", help="N:k list for the bounded residual test at design scale "
                    "(model from --bounded-null, default logistic)")
    ap.add_argument("--bdesign-sims", type=int, default=200)
    ap.add_argument("--bdesign-B", type=int, default=499)
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
    cfg = {"blocks": {k_: {"z": blocks[k_]["z"], "zq": blocks[k_].get("zq")} for k_ in a.key}, "kinds": kinds,
           "B": a.B, "design_B": a.design_B, "omnibus_B": a.omnibus_B, "bnull_B": a.bnull_B, "plants": plants,
           "omni_plants": oplants, "seed": a.seed, "pilot_k": a.pilot_k, "rho": rho, "bdesign_B": a.bdesign_B}
    acc = {}
    with multiprocessing.Pool(a.workers, initializer=_init, initargs=(cfg,)) as pool:
        it = pool.imap_unordered(_dispatch, [(fn_name, args) for fn_name, args in tasks])
        for done, (gk, cnt, n) in enumerate(it, 1):
            g = acc.setdefault(gk, [{}, 0])
            for t, v in cnt.items():
                g[0][t] = g[0].get(t, 0) + v
            g[1] += n
            if done % 20 == 0 or done == len(tasks):
                print(f"{done}/{len(tasks)} chunks", flush=True)
    rows = []
    Bs = {"pilot": a.B, "design": a.design_B, "omnibus": a.omnibus_B, "bnull": a.bnull_B, "bdesign": a.bdesign_B}
    for (key, scale, w, N, k, Gn, C), (cnt, n) in sorted(acc.items()):
        for (test, effect, alpha), v in sorted(cnt.items()):
            rate = v / n
            lo, hi = hodge.clopper_pearson(v, n)
            rows.append({"key": key, "scale": scale, "world": w, "N": N, "k": k, "G": Gn, "C": C, "test": test,
                         "effect": effect, "alpha": alpha, "x": v, "n": n, "rate": rate, "cp_lo": lo, "cp_hi": hi,
                         "B": Bs[scale]})
    with open(os.path.join(a.out, "calib.csv"), "w", newline="") as f:
        w_ = csv.DictWriter(f, fieldnames=list(rows[0]))
        w_.writeheader()
        for r in rows:
            w_.writerow({c: (repr(v) if isinstance(v, float) else v) for c, v in r.items()})
    md = report(a, bj, blocks, rows, plants, oplants, kinds, worlds, design, omni, rho)
    open(os.path.join(a.out, "calib.md"), "w").write("\n".join(md) + "\n")
    man = {"schema": "finfolk.invasion.calibration/1",
           "blocks": {"path": os.path.abspath(a.blocks), "sha256": blocks_sha,
                      "plan_sha256": bj.get("plan_sha256"), "analysis_sha256": bj.get("analysis_sha256"),
                      "keys": {k_: {"status": blocks[k_]["status"], "names": blocks[k_]["names"], "reps": blocks[k_]["reps"]}
                               for k_ in a.key}},
           "code": code,
           "primary": infer.PRIMARY, "args": vars(a), "seed": a.seed, "task_seeds": [t[1][-1] for t in tasks],
           "assay_corr": rho, "python": platform.python_version(), "wall_s": time.time() - t0,
           "outputs": {f: sha256(os.path.join(a.out, f)) for f in ("calib.csv", "calib.md")}}
    with open(os.path.join(a.out, "manifest.json"), "w") as f:
        f.write(json.dumps(man, indent=1, sort_keys=True, default=str) + "\n")
    print("\n".join(md))
    return 0


def _dispatch(x):
    fn_name, args = x
    return {"pilot": task_pilot, "omnibus": task_omnibus, "bnull": task_bnull, "bdesign": task_bdesign}[fn_name](args)


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

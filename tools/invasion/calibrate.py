#!/usr/bin/env python3
"""calibrate.py: null rejection rate and planted-cycle power of infer.py's tests, by simulation.

    calibrate.py --blocks DIR/blocks.json --key off/0.05/5.0 [--key ...] --out OUTDIR
                 [--sims 2000] [--B 999] [--kinds wild,residual]
                 [--worlds iso,hetero,pilotcov,empirical,skew,concentrated]
                 [--design 20:3,20:5,20:8,20:10,28:8] [--design-sims 500] [--design-B 499]
                 [--workers 4] [--seed 1]

Each simulated dataset is a complete block of units z[p][r][i] (resident column p, replicate r,
invader i) with the null true (a pure ladder: the curl and the symmetric-interaction residual
are zero; neither the ladder nor any column constant can change those tests, so the datasets
carry noise only). It goes through exactly analyze.py's procedure: infer.block_stats for the
statistics, infer's studentized unit bootstrap (B draws, both kinds) and the exact replicate
sign-flip. The rejection rate at alpha is the fraction with p <= alpha.

Null worlds at the pilot block's own scale (N, k), built from that block:
  iso          iid Gaussian, one SD for every cell (the old chi-square test's assumption)
  hetero       independent Gaussian with the block's own per-cell SDs (they differ ~50x)
  pilotcov     Gaussian with each column's sample covariance shrunk halfway to its diagonal
  empirical    the block's own centred, variance-restored units, resampled (real shapes)
  skew         per-cell SDs as in hetero, centred exponential errors (skewness 2)
  concentrated per-cell SDs, plus a strong common factor within each unit (+-1 loadings):
               curl noise concentrated in few directions
Old tests are evaluated on the same datasets for comparison: chi2 = the superseded p_lof
(X = q ||curl||^2 / E||noise curl||^2 ~ chi2_q) and F = X/q ~ F(q, q(k-1)).

Planted-cycle power, on the same datasets (the bootstrap null does not depend on the planted
mean: residuals are unchanged), for the primary kind and the sign-flip: divergence-free
templates ('measured' = the block's own observed curl direction; 'diffuse' rank-2; 'random';
'triangle' = one local circulation) at RMS cyclic signal d_C per pair (0.0025 .. 0.02, and the
block's own noise-corrected d_C), the triangle also at a fixed per-edge amplitude.

Design scale (--design N:k): per-cell SDs drawn from the block's per-cell SD distribution,
Gaussian (hetero) and centred exponential (skew); power at d_C 0.0025 .. 0.02 and at the planted
shares 0.035 / 0.07 for the block's noise-corrected ladder strength.

Outputs in OUTDIR: calib.csv (one row per key, scale, world, N, k, test, effect, alpha) and
calib.md.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import multiprocessing
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hodge  # noqa: E402
import infer  # noqa: E402

ALPHAS = (0.05, 0.01, 0.0045)
D_GRID = (0.0025, 0.005, 0.01, 0.02)


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


class World:
    """Null generators built from one pilot block (see the module doc)."""

    def __init__(self, z, name, N=None, k=None, seed=0):
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
        if name == "pilotcov":
            self.L = []
            for p in range(self.N0):
                idx = [i for i in range(self.N0) if i != p]
                m = [sum(z[p][r][i] for r in range(self.k0)) / self.k0 for i in idx]
                C = [[sum((z[p][r][a] - m[x]) * (z[p][r][b] - m[y]) for r in range(self.k0)) / (self.k0 - 1)
                      for y, b in enumerate(idx)] for x, a in enumerate(idx)]
                C = [[C[x][y] * (1.0 if x == y else 0.5) for y in range(len(idx))] for x in range(len(idx))]
                self.L.append((idx, cholesky(C)))
        if name == "concentrated":
            self.lam = [[rnd.choice((-1.0, 1.0)) for _ in range(self.N)] for _ in range(self.N)]

    def draw(self, rnd):
        N, k, nm = self.N, self.k, self.name
        z = []
        for p in range(N):
            col = []
            for _ in range(k):
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
                elif nm == "empirical":
                    u = list(self.res[p][rnd.randrange(len(self.res[p]))])
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


def boot_p(z, B, seed, kind, st=None):
    """-> (null draws F_C*, F_S*, T_C0*), sorted, for p-values of any planted variant of z."""
    b = infer.bootstrap([z], B=B, seed=seed, kind=kind)
    return sorted(x["F_C"] for x in b), sorted(x["F_S"] for x in b), sorted(x["T_C0"] for x in b)


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


def task(args):
    """One chunk of simulated datasets. -> {(test, effect, alpha): rejections}, n."""
    key, scale, wname, N, k, n, seed = args
    z0 = G["blocks"][key]["z"]
    world = World(z0, wname, N if scale == "design" else None, k if scale == "design" else None, seed=G["seed"])
    rnd = random.Random(seed)
    kinds = G["kinds"] if scale == "pilot" else [G["kinds"][0]]
    B = G["B"] if scale == "pilot" else G["design_B"]
    plants = G["plants"][(key, scale, N)]
    cnt = {}

    def hit(test, effect, p):
        for a in ALPHAS:
            if p is not None and p <= a + 1e-15:
                cnt[(test, effect, a)] = cnt.get((test, effect, a), 0) + 1
            else:
                cnt.setdefault((test, effect, a), 0)
    for _ in range(n):
        z = world.draw(rnd)
        st = infer.block_stats(z)
        if scale == "pilot":
            pc, pf = old_tests(z)
            hit("chi2 (superseded)", "null", pc)
            hit("F(q,q(k-1)) (superseded)", "null", pf)
        hit("sign-flip lof", "null", infer.signflip([z], "curl"))
        hit("sign-flip sym", "null", infer.signflip([z], "sym") if N >= 4 else None)
        bs = rnd.randrange(1 << 30)
        nulls = {}
        for kind in kinds:
            FC, FS, TC0 = boot_p(z, B, bs, kind)
            nulls[kind] = FC
            hit(f"boot {kind} lof", "null", p_from(FC, infer._ratio(st["TC"], st["tauC"])))
            hit(f"boot {kind} sym", "null", p_from(FS, infer._ratio(st["TS"], st["tauS"])) if N >= 4 else None)
            if scale == "pilot":
                hit(f"boot {kind} lof unstudentized", "null", p_from(TC0, st["TC"]))
        prim = kinds[0]
        for label, v, d in plants:
            zp = infer.plant(z, v, d)
            sp = infer.block_stats(zp)
            hit(f"boot {prim} lof", label, p_from(nulls[prim], infer._ratio(sp["TC"], sp["tauC"])))
            hit("sign-flip lof", label, infer.signflip([zp], "curl"))
            if scale == "pilot":
                hit("chi2 (superseded)", label, old_tests(zp)[0])
    return (key, scale, wname, N, k), cnt, n


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
        dG = math.sqrt(max(0.0, inf["G_nc"]) / len(inf_A(z)))
        v = infer.cycle_template(N, "diffuse", seed=5)
        for rho in (0.035, 0.07):
            d = dG * math.sqrt(rho / (1 - rho))
            out.append((f"diffuse share={rho} (d_C={d:.4f})", v, d))
    return out


def inf_A(z):
    return infer.block_stats(z)["A"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--blocks", required=True)
    ap.add_argument("--key", action="append", required=True, help="cond/frac/G, e.g. off/0.05/5.0")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--B", type=int, default=999)
    ap.add_argument("--kinds", default="wild,residual", help="bootstrap kinds; the first is the primary one")
    ap.add_argument("--worlds", default="iso,hetero,pilotcov,empirical,skew,concentrated")
    ap.add_argument("--design", default="", help="design-scale N:k list, e.g. 20:5,20:8,28:8")
    ap.add_argument("--design-sims", type=int, default=500)
    ap.add_argument("--design-B", type=int, default=499)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--chunk", type=int, default=50)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    if not 1 <= a.workers <= 4:
        ap.error("--workers must be 1..4")
    os.makedirs(a.out, exist_ok=True)
    bj = json.load(open(a.blocks))
    blocks = {}
    for b in bj["blocks"]:
        blocks[f"{b['cond']}/{b['frac']}/{b['G']}"] = b
    for key in a.key:
        if key not in blocks:
            raise SystemExit(f"no block {key} in {a.blocks} (have {sorted(blocks)})")
        if blocks[key]["status"] != "formal":
            print(f"note: block {key} is {blocks[key]['status']}", file=sys.stderr)
    kinds = a.kinds.split(",")
    worlds = a.worlds.split(",")
    design = [tuple(int(x) for x in d.split(":")) for d in a.design.split(",") if d]
    plants, tasks = {}, []
    sd = a.seed * 1000003
    for key in a.key:
        z = blocks[key]["z"]
        N0, k0 = len(z), len(z[0])
        plants[(key, "pilot", N0)] = plant_list(z, "pilot", N0)
        for w in worlds:
            for c0 in range(0, a.sims, a.chunk):
                sd += 1
                tasks.append((key, "pilot", w, N0, k0, min(a.chunk, a.sims - c0), sd))
        for N, k in design:
            if (key, "design", N) not in plants:
                plants[(key, "design", N)] = plant_list(z, "design", N)
            for w in ("hetero-design", "skew-design"):
                for c0 in range(0, a.design_sims, a.chunk):
                    sd += 1
                    tasks.append((key, "design", w, N, k, min(a.chunk, a.design_sims - c0), sd))
    cfg = {"blocks": {k_: {"z": blocks[k_]["z"]} for k_ in a.key}, "kinds": kinds, "B": a.B,
           "design_B": a.design_B, "plants": plants, "seed": a.seed}
    acc = {}
    with multiprocessing.Pool(a.workers, initializer=_init, initargs=(cfg,)) as pool:
        for done, (gk, cnt, n) in enumerate(pool.imap_unordered(task, tasks), 1):
            g = acc.setdefault(gk, [{}, 0])
            for t, v in cnt.items():
                g[0][t] = g[0].get(t, 0) + v
            g[1] += n
            if done % 20 == 0 or done == len(tasks):
                print(f"{done}/{len(tasks)} chunks", flush=True)
    rows = []
    for (key, scale, w, N, k), (cnt, n) in sorted(acc.items()):
        for (test, effect, alpha), v in sorted(cnt.items()):
            rate = v / n
            rows.append({"key": key, "scale": scale, "world": w, "N": N, "k": k, "test": test, "effect": effect,
                         "alpha": alpha, "rate": rate, "se": math.sqrt(max(rate * (1 - rate), 1e-12) / n), "n": n,
                         "B": a.B if scale == "pilot" else a.design_B})
    with open(os.path.join(a.out, "calib.csv"), "w", newline="") as f:
        w_ = csv.DictWriter(f, fieldnames=list(rows[0]))
        w_.writeheader()
        for r in rows:
            w_.writerow({c: (repr(v) if isinstance(v, float) else v) for c, v in r.items()})
    md = [f"# Null calibration and planted-cycle power (calibrate.py)\n",
          f"blocks: `{a.blocks}` (plan {bj.get('plan_sha256', '')[:16]}, analysis {bj.get('analysis_sha256', '')[:16]}); "
          f"pilot-scale sims {a.sims} x B {a.B}; design-scale sims {a.design_sims} x B {a.design_B}; kinds {kinds}; "
          f"seed {a.seed}.\n"]
    for key in a.key:
        md.append(f"\n## {key}: null rejection rate (p <= alpha), pilot scale\n")
        tests = sorted({r["test"] for r in rows if r["key"] == key and r["scale"] == "pilot" and r["effect"] == "null"})
        md.append("| world | test | " + " | ".join(f"alpha {x}" for x in ALPHAS) + " |\n|---|---|" + "---|" * len(ALPHAS))
        for w in worlds:
            for t in tests:
                rr = {r["alpha"]: r for r in rows if (r["key"], r["scale"], r["world"], r["test"], r["effect"]) == (key, "pilot", w, t, "null")}
                if rr:
                    md.append(f"| {w} | {t} | " + " | ".join(f"{rr[x]['rate']:.4f} ({rr[x]['se']:.4f})" for x in ALPHAS) + " |")
        md.append(f"\n## {key}: power (p <= alpha) of the primary bootstrap ({kinds[0]}) / the sign-flip / the superseded chi2, pilot scale\n")
        eff = [p[0] for p in plants[(key, "pilot", len(blocks[key]["z"]))]]
        md.append("| world | effect | boot a=0.05 | boot a=0.0045 | flip a=0.05 | chi2 a=0.05 |\n|---|---|---|---|---|---|")
        for w in worlds:
            for e in eff:
                def rate(t, al):
                    v = [r["rate"] for r in rows if (r["key"], r["scale"], r["world"], r["test"], r["effect"], r["alpha"]) == (key, "pilot", w, t, e, al)]
                    return f"{v[0]:.3f}" if v else "-"
                md.append(f"| {w} | {e} | {rate(f'boot {kinds[0]} lof', 0.05)} | {rate(f'boot {kinds[0]} lof', 0.0045)} | "
                          f"{rate('sign-flip lof', 0.05)} | {rate('chi2 (superseded)', 0.05)} |")
        if design:
            md.append(f"\n## {key}: design scale (per-cell SDs drawn from this block), {kinds[0]} bootstrap\n")
            md.append("| world | N | k | effect | boot a=0.05 | boot a=0.0045 | flip a=0.05 |\n|---|---|---|---|---|---|---|")
            for N, k in design:
                eff = ["null"] + [p[0] for p in plants[(key, "design", N)]]
                for w in ("hetero-design", "skew-design"):
                    for e in eff:
                        def rate(t, al):
                            v = [r["rate"] for r in rows if (r["key"], r["scale"], r["world"], r["N"], r["k"], r["test"], r["effect"], r["alpha"]) == (key, "design", w, N, k, t, e, al)]
                            return f"{v[0]:.3f}" if v else "-"
                        md.append(f"| {w} | {N} | {k} | {e} | {rate(f'boot {kinds[0]} lof', 0.05)} | "
                                  f"{rate(f'boot {kinds[0]} lof', 0.0045)} | {rate('sign-flip lof', 0.05)} |")
    open(os.path.join(a.out, "calib.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())

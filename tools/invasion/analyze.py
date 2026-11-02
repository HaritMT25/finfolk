#!/usr/bin/env python3
"""analyze.py: invasion-matrix analysis and the Phase 0 pilot report (stdlib only).

    analyze.py --root DIR [--root DIR2 ...] --out OUTDIR [--windows 2.5,5,10]
               [--sims 1000] [--power-sims 400] [--no-power]

Reads every finished cell (DIR/cells/<id>/done.json + score.json) and writes
CSV tables plus summary.md to OUTDIR:

  gen.csv      generation length per (snapshot, condition): steps until the
               births reach k x the start population, from the sham runs
  runs.csv     one row per run and window: the score at the scored checkpoint
               nearest W = G x generation length of the RESIDENT (the same W for
               i->j and its sham j->j)
  groups.csv   per (condition, fraction, window, resident, invader, mode): mean,
               SD, SE of s over replicates; invader-lost and extinction counts
  paired.csv   per invade cell: s~ = mean_r [s(i->j, r) - s(j->j, r)] with the
               paired SD and the pairing gain G = (var_a + var_b) / var_(a-b)
  pairs.csv    both directions observed: A = s~(i->j) - s~(j->i),
               S = (s~(i->j) + s~(j->i)) / 2, their SE and z
  matrix.csv   when a resident x invader block is complete: the Hodge split
               (ratings, cyclic share, noise floor) per condition/fraction/window
  speed.csv    engine seconds per step against mean population (+ a fit)
  power.csv    noise floor and planted-cycle recovery at the measured noise
  cost.csv     seconds per cell and core-hours for N x replicates x settings
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hodge  # noqa: E402


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def sd(xs):
    if len(xs) < 2:
        return None
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def fmt(x, nd=4):
    if x is None:
        return ""
    if isinstance(x, float):
        if math.isnan(x):
            return "nan"
        return f"{x:.{nd}f}" if abs(x) < 1e4 else f"{x:.3g}"
    return str(x)


def write_csv(path, rows, cols):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([fmt(r.get(c)) if isinstance(r.get(c), float) else r.get(c, "") for c in cols])


def load(roots):
    recs = []
    for root in roots:
        cdir = os.path.join(root, "cells")
        for cid in sorted(os.listdir(cdir)):
            d = os.path.join(cdir, cid)
            if ".attempt" in cid or not os.path.exists(os.path.join(d, "done.json")):
                continue
            done = json.load(open(os.path.join(d, "done.json")))
            sc = json.load(open(os.path.join(d, "score.json")))
            c = done["cell"]
            iv = []   # (population, steps/s) per logged interval, for the speed fit
            with open(os.path.join(d, "run.csv")) as f:
                for row in csv.DictReader(f):
                    iv.append((int(row["population"]), float(row["steps_per_sec"])))
            recs.append({
                "id": cid, "root": root, "j": c["resident_name"], "i": c["invader_name"], "mode": c["mode"],
                "frac": c["fraction"], "cond": c["condition"], "rep": c["replicate"], "steps": c["steps"],
                "n0": sc["n0"], "m": sc["m"], "f0": sc["start_fraction"], "turnover": sc["turnover_steps"],
                "points": sc["points"], "wall": done["timing"]["engine_wall_s"],
                "user": done["timing"]["engine_user_s"], "build_s": done["timing"]["build_s"],
                "score_s": done["timing"]["score_s"], "pop_mean": done["population"]["mean"],
                "pop_min": done["population"]["min"], "pop_max": done["population"]["max"],
                "maxrss_kb": done["timing"]["engine_maxrss_kb"], "intervals": iv,
            })
    return recs


def gen_length(recs, definition="pop"):
    """Steps per generation per (j, cond), from the sham runs.

    g_n0  = steps until the births reach k x the START population (up to k = 10), / k
    g_pop = run steps x mean logged population / births over the run (turnover of
            the population at its time-averaged size)
    The start population is wherever the food cycle had the snapshot (the
    population swings ~3x over the 6,283-step cycle), so g_n0 depends on the
    snapshot's phase; g_pop does not. `definition` picks the window clock ('g')."""
    acc = {}
    for r in recs:
        if r["mode"] != "sham" or not r["turnover"]:
            continue
        K = min(10, len(r["turnover"]))
        last = r["points"][-1]
        gpop = last["steps"] * r["pop_mean"] / last["births"] if last["births"] else None
        acc.setdefault((r["j"], r["cond"]), []).append((r["turnover"][K - 1] / K, r["turnover"][0], K, gpop, r["n0"],
                                                         r["pop_mean"]))
    out = {}
    for k, v in acc.items():
        o = {"g_n0": mean([x[0] for x in v]), "g_n0_sd": sd([x[0] for x in v]), "gen1": mean([x[1] for x in v]),
             "gen1_sd": sd([x[1] for x in v]), "k_min": min(x[2] for x in v), "runs": len(v),
             "g_pop": mean([x[3] for x in v if x[3]]), "g_pop_sd": sd([x[3] for x in v if x[3]]),
             "n0": v[0][4], "pop_mean": mean([x[5] for x in v])}
        o["g"] = o["g_pop"] if definition == "pop" else o["g_n0"]
        out[k] = o
    return out


def pick(r, W):
    """The scored point nearest W steps (None if the run never got there)."""
    pts = r["points"]
    best = min(pts, key=lambda p: abs(p["steps"] - W))
    return best


def run_rows(recs, gens, windows):
    rows = []
    for r in recs:
        g = gens.get((r["j"], r["cond"]))
        if not g:
            continue
        for G in windows:
            W = G * g["g"]
            p = pick(r, W)
            rows.append({**{k: r[k] for k in ("id", "j", "i", "mode", "frac", "cond", "rep", "n0", "m")},
                         "G": G, "W": round(W), "steps_at": p["steps"], "over": W > r["points"][-1]["steps"] + 1000,
                         "s": p["score"], "n": p["n"], "births": p["births"], "gens": p["generations"],
                         "invader_lost": p["invader_lost"], "extinct": p["extinct"]})
    return rows


def groups(rows):
    acc = {}
    for x in rows:
        acc.setdefault((x["cond"], x["frac"], x["G"], x["j"], x["i"], x["mode"]), []).append(x)
    out = []
    for (cond, frac, G, j, i, mode), xs in sorted(acc.items()):
        s = [x["s"] for x in xs if x["s"] is not None]
        out.append({"cond": cond, "frac": frac, "G": G, "j": j, "i": i, "mode": mode, "k": len(s),
                    "mean": mean(s), "sd": sd(s), "se": (sd(s) / math.sqrt(len(s))) if len(s) > 1 else None,
                    "lost": sum(1 for x in xs if x["invader_lost"]), "extinct": sum(1 for x in xs if x["extinct"]),
                    "W": xs[0]["W"], "n_end": mean([x["n"] for x in xs]), "over": any(x["over"] for x in xs)})
    return out


def paired(rows):
    by = {}
    for x in rows:
        by[(x["cond"], x["frac"], x["G"], x["j"], x["i"], x["mode"], x["rep"])] = x
    keys = sorted({(x["cond"], x["frac"], x["G"], x["j"], x["i"]) for x in rows if x["mode"] == "invade"})
    reps = {}
    for x in rows:
        reps.setdefault((x["cond"], x["frac"], x["G"], x["j"]), set()).add(x["rep"])
    out = []
    for cond, frac, G, j, i in keys:
        a, b = [], []
        for rep in sorted(reps[(cond, frac, G, j)]):
            xa = by.get((cond, frac, G, j, i, "invade", rep))
            xb = by.get((cond, frac, G, j, j, "sham", rep))
            if xa and xb and xa["s"] is not None and xb["s"] is not None:
                a.append(xa["s"])
                b.append(xb["s"])
        if len(a) < 2:
            continue
        d = [p - q for p, q in zip(a, b)]
        va, vb, vd = sd(a) ** 2, sd(b) ** 2, sd(d) ** 2
        k = len(d)
        out.append({"cond": cond, "frac": frac, "G": G, "j": j, "i": i, "k": k,
                    "s_inv": mean(a), "s_sham": mean(b), "st": mean(d), "sd_d": math.sqrt(vd),
                    "se_paired": math.sqrt(vd / k), "se_unpaired": math.sqrt((va + vb) / k),
                    "sd_inv": math.sqrt(va), "sd_sham": math.sqrt(vb),
                    "gain": (va + vb) / vd if vd > 0 else None,
                    "corr": ((va + vb - vd) / (2 * math.sqrt(va * vb))) if va > 0 and vb > 0 else None,
                    "z": mean(d) / math.sqrt(vd / k) if vd > 0 else None})
    return out


def pair_table(prs):
    by = {(p["cond"], p["frac"], p["G"], p["j"], p["i"]): p for p in prs}
    out = []
    for (cond, frac, G, j, i), p in sorted(by.items()):
        # p is i invading j: p["st"] = s~(i->j). Each unordered pair once, a = i < b = j.
        if i >= j:
            continue
        q = by.get((cond, frac, G, i, j))   # j invading i: s~(j->i)
        if q is None:
            continue
        A = p["st"] - q["st"]
        S = 0.5 * (p["st"] + q["st"])
        se_A = math.sqrt(p["se_paired"] ** 2 + q["se_paired"] ** 2)
        out.append({"cond": cond, "frac": frac, "G": G, "a": i, "b": j,
                    "st_a_into_b": p["st"], "st_b_into_a": q["st"], "A_ab": A,
                    "S": S, "se_A": se_A, "se_S": 0.5 * se_A, "z_A": A / se_A if se_A > 0 else None,
                    "z_S": S / (0.5 * se_A) if se_A > 0 else None})
    return out


def speed_fit(recs):
    """seconds/step = c0 + c1 pop + c2 pop^2 (least squares over every logged interval of every run:
    the population swings ~150-1000 inside a run, which spreads the fit)."""
    pts = [(p, 1.0 / s) for r in recs for p, s in r["intervals"] if s > 0]
    if len(pts) < 5:
        return None, pts
    X = [[1.0, p, p * p] for p, _ in pts]
    y = [t for _, t in pts]
    XtX = [[sum(X[k][a] * X[k][b] for k in range(len(X))) for b in range(3)] for a in range(3)]
    Xty = [sum(X[k][a] * y[k] for k in range(len(X))) for a in range(3)]
    c = hodge.solve(XtX, Xty)
    return c, pts


def matrices(rows_paired, names_by_block):
    """Complete blocks only: the Hodge split of the observed A."""
    out = []
    keys = sorted({(p["cond"], p["frac"], p["G"]) for p in rows_paired})
    for cond, frac, G in keys:
        st = {(p["i"], p["j"]): p for p in rows_paired if (p["cond"], p["frac"], p["G"]) == (cond, frac, G)}
        names = sorted({n for ij in st for n in ij})
        if len(names) < 3:
            continue
        n = len(names)
        M = [[None] * n for _ in range(n)]
        for (i, j), p in st.items():
            M[names.index(i)][names.index(j)] = p["st"]
        A, S = hodge.antisym_sym(M)
        P = sum(1 for a in range(n) for b in range(a + 1, n) if A[a][b] is not None)
        if P < n * (n - 1) // 2:
            continue
        sp = hodge.split(A)
        v = mean([p["se_paired"] ** 2 for p in st.values()]) * 2
        _, floor95 = hodge.simulate_floor(n, math.sqrt(max(1e-12, sp["norm2"] / P - v)), math.sqrt(v), sims=500)
        out.append({"cond": cond, "frac": frac, "G": G, "n": n, "names": " ".join(names),
                    "ratings": " ".join(f"{x:.4f}" for x in sp["r"]), "cyclic_share": sp["cyclic_share"],
                    "debiased": hodge.debiased_share(A, v), "floor95": floor95})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--windows", default="2.5,5,10")
    ap.add_argument("--sims", type=int, default=1000)
    ap.add_argument("--power-sims", type=int, default=400)
    ap.add_argument("--no-power", action="store_true")
    ap.add_argument("--gen-def", default="pop", choices=["pop", "n0"],
                    help="window clock: turnover of the mean population (default) or of the start population")
    ap.add_argument("--power-cond", default=None, help="condition whose noise drives the power table (default all)")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    windows = [float(x) for x in a.windows.split(",")]
    recs = load(a.root)
    gens = gen_length(recs, a.gen_def)
    rows = run_rows(recs, gens, windows)
    grp = groups(rows)
    prs = paired(rows)
    pt = pair_table(prs)
    md = []
    md.append(f"# Invasion pilot analysis\n\n{len(recs)} finished runs from {', '.join(a.root)}.\n")

    # --- generation length
    grow = [{"j": j, "cond": c, **v} for (j, c), v in sorted(gens.items())]
    write_csv(os.path.join(a.out, "gen.csv"), grow,
              ["j", "cond", "n0", "pop_mean", "g_pop", "g_pop_sd", "g_n0", "g_n0_sd", "gen1", "gen1_sd", "k_min", "runs", "g"])
    md.append(f"## Generation length (sham runs; window clock = {'g_pop' if a.gen_def == 'pop' else 'g_n0'})\n")
    md.append("g_pop = steps x mean population / births; g_n0 = steps until births reach k x start population, / k "
              "(k <= 10); first gen = steps until births = start population.\n")
    md.append("| snapshot | condition | start pop | mean pop | g_pop | SD | g_n0 | SD | first gen | SD | runs |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for g in grow:
        md.append(f"| {g['j']} | {g['cond']} | {g['n0']} | {g['pop_mean']:.0f} | {g['g_pop']:.0f} | {fmt(g['g_pop_sd'], 0)} | "
                  f"{g['g_n0']:.0f} | {fmt(g['g_n0_sd'], 0)} | {g['gen1']:.0f} | {fmt(g['gen1_sd'], 0)} | {g['runs']} |")

    write_csv(os.path.join(a.out, "runs.csv"), rows,
              ["id", "j", "i", "mode", "frac", "cond", "rep", "n0", "m", "G", "W", "steps_at", "over", "s", "n",
               "births", "gens", "invader_lost", "extinct"])
    write_csv(os.path.join(a.out, "groups.csv"), grp,
              ["cond", "frac", "G", "j", "i", "mode", "k", "mean", "sd", "se", "lost", "extinct", "W", "n_end", "over"])
    write_csv(os.path.join(a.out, "paired.csv"), prs,
              ["cond", "frac", "G", "j", "i", "k", "s_inv", "s_sham", "st", "sd_d", "se_paired", "se_unpaired",
               "sd_inv", "sd_sham", "gain", "corr", "z"])
    write_csv(os.path.join(a.out, "pairs.csv"), pt,
              ["cond", "frac", "G", "a", "b", "st_a_into_b", "st_b_into_a", "A_ab", "S", "se_A", "se_S", "z_A", "z_S"])

    # --- per-cell noise: shams (and self) SD of s
    md.append("\n## Per-cell replicate SD of s (self-invasion j->j)\n")
    md.append("| condition | fraction | window (gens) | mode | k | mean s | pooled SD | min SD | max SD | lost/runs |\n|---|---|---|---|---|---|---|---|---|---|")
    noise = {}
    for cond in sorted({g["cond"] for g in grp}):
        for frac in sorted({g["frac"] for g in grp}):
            for G in windows:
                for mode in ("sham", "self"):
                    gs = [g for g in grp if (g["cond"], g["frac"], g["G"], g["mode"]) == (cond, frac, G, mode) and g["sd"] is not None]
                    if not gs:
                        continue
                    pooled = math.sqrt(mean([g["sd"] ** 2 for g in gs]))
                    noise[(cond, frac, G, mode)] = pooled
                    md.append(f"| {cond} | {frac} | {G} | {mode} | {gs[0]['k']} | {mean([g['mean'] for g in gs]):.4f} | {pooled:.4f} | "
                              f"{min(g['sd'] for g in gs):.4f} | {max(g['sd'] for g in gs):.4f} | {sum(g['lost'] for g in gs)}/{sum(g['k'] for g in gs)} |")

    # --- paired differences, pairing gain
    md.append("\n## Paired scores s~(i->j) and the sham pairing gain G = (var_a + var_b) / var_(a-b)\n")
    md.append("| condition | fraction | window | cells | pooled SD of s~ per replicate | median gain | mean corr(a, b) | mean |s~| | max |z| |\n|---|---|---|---|---|---|---|---|---|")
    dnoise = {}
    for cond in sorted({p["cond"] for p in prs}):
        for frac in sorted({p["frac"] for p in prs}):
            for G in windows:
                ps = [p for p in prs if (p["cond"], p["frac"], p["G"]) == (cond, frac, G)]
                if not ps:
                    continue
                pooled = math.sqrt(mean([p["sd_d"] ** 2 for p in ps]))
                dnoise[(cond, frac, G)] = pooled
                gains = sorted(p["gain"] for p in ps if p["gain"])
                md.append(f"| {cond} | {frac} | {G} | {len(ps)} | {pooled:.4f} | {gains[len(gains) // 2]:.2f} | "
                          f"{mean([p['corr'] for p in ps if p['corr'] is not None]):.2f} | {mean([abs(p['st']) for p in ps]):.4f} | "
                          f"{max(abs(p['z']) for p in ps if p['z'] is not None):.1f} |")

    md.append("\n## Effect sizes on real pairs (A = s~(a->b) - s~(b->a), S = mean of both)\n")
    md.append("| condition | fraction | window | a | b | s~(a->b) | s~(b->a) | A | z_A | S | z_S |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for p in pt:
        md.append(f"| {p['cond']} | {p['frac']} | {p['G']} | {p['a']} | {p['b']} | {p['st_a_into_b']:+.4f} | {p['st_b_into_a']:+.4f} | "
                  f"{p['A_ab']:+.4f} | {fmt(p['z_A'], 1)} | {p['S']:+.4f} | {fmt(p['z_S'], 1)} |")
    effect = {}
    for cond in sorted({p["cond"] for p in pt}):
        for frac in sorted({p["frac"] for p in pt}):
            for G in windows:
                ps = [p for p in pt if (p["cond"], p["frac"], p["G"]) == (cond, frac, G)]
                if ps:
                    ms = mean([p["A_ab"] ** 2 for p in ps])
                    nv = mean([p["se_A"] ** 2 for p in ps])
                    effect[(cond, frac, G)] = {"rms_obs": math.sqrt(ms), "rms_true": math.sqrt(max(0.0, ms - nv)),
                                               "rms_se": math.sqrt(nv), "pairs": len(ps)}
    md.append("\n| condition | fraction | window | pairs | RMS A observed | RMS SE(A) | RMS A noise-corrected |\n|---|---|---|---|---|---|---|")
    for (cond, frac, G), e in sorted(effect.items()):
        md.append(f"| {cond} | {frac} | {G} | {e['pairs']} | {e['rms_obs']:.4f} | {e['rms_se']:.4f} | {e['rms_true']:.4f} |")

    # --- complete blocks (if any)
    mats = matrices(prs, None)
    if mats:
        write_csv(os.path.join(a.out, "matrix.csv"), mats, ["cond", "frac", "G", "n", "names", "ratings", "cyclic_share", "debiased", "floor95"])
        md.append("\n## Complete blocks: Hodge split\n")
        md.append("| condition | fraction | window | N | cyclic share | debiased | noise floor 95% |\n|---|---|---|---|---|---|---|")
        for m in mats:
            md.append(f"| {m['cond']} | {m['frac']} | {m['G']} | {m['n']} | {m['cyclic_share']:.3f} | {m['debiased']:.3f} | {m['floor95']:.3f} |")

    # --- speed
    c, pts = speed_fit(recs)
    srows = [{"pop_mean": p, "sec_per_step": t} for p, t in pts]
    write_csv(os.path.join(a.out, "speed.csv"), srows, ["pop_mean", "sec_per_step"])
    overhead = mean([r["build_s"] + r["score_s"] for r in recs]) + 0.15   # + interpreter start
    md.append("\n## Engine speed (serial build, 4 concurrent workers at nice 19)\n")
    if c:
        md.append(f"seconds/step = {c[0]:.3e} + {c[1]:.3e} pop + {c[2]:.3e} pop^2 (fit over {len(pts)} runs; "
                  f"mean population over each run). Per-cell overhead (arena build + scoring) ~{overhead:.1f} s.\n")
        md.append("| mean population | steps/s |\n|---|---|")
        for pop in (200, 300, 400, 500, 600, 700, 900):
            t = c[0] + c[1] * pop + c[2] * pop * pop
            md.append(f"| {pop} | {1 / t:.0f} |")

    # --- power
    pw_rows = []
    if not a.no_power and dnoise and effect:
        md.append("\n## Noise floor and planted-cycle recovery (simulated at the measured noise)\n")
        md.append("Noise per A cell with k replicates = sqrt(2) x (pooled SD of s~ per replicate) / sqrt(k) "
                  "(A is the difference of two independent paired cells). True RMS of A = the pilot's noise-corrected "
                  "RMS (x0.5, x1, x2). Floor = 95th percentile of the cyclic share of pure ladders; power = "
                  "P(planted share > floor).\n")
        md.append("| condition | fraction | window | N | k | true RMS A | noise/cell | floor95 | share 0.1 | 0.2 | 0.3 | 0.5 | mean obs @0.3 | debiased @0.3 |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for key in sorted(dnoise):
            cond, frac, G = key
            if a.power_cond and cond != a.power_cond:
                continue
            if key not in effect:
                continue
            for mult in (0.5, 1.0, 2.0):
                rms = effect[key]["rms_true"] * mult
                if rms <= 0:
                    continue
                for N, ks in ((20, (3, 5, 10, 20)), (10, (10,)), (30, (10,))):
                    for k in ks:
                        if mult != 1.0 and (N != 20 or k not in (5, 10)):
                            continue
                        ns = math.sqrt(2) * dnoise[key] / math.sqrt(k)
                        _, f95 = hodge.simulate_floor(N, rms, ns, sims=a.sims, seed=11)
                        row = {"cond": cond, "frac": frac, "G": G, "N": N, "k": k, "rms": rms, "mult": mult,
                               "noise": ns, "floor95": f95}
                        for share in (0.1, 0.2, 0.3, 0.5):
                            r = hodge.simulate_power(N, rms, share, ns, f95, sims=a.power_sims, seed=13)
                            row[f"p{share}"] = r["power"]
                            if share == 0.3:
                                row["obs03"] = r["mean_share"]
                                row["deb03"] = r["mean_debiased"]
                        pw_rows.append(row)
                        md.append(f"| {cond} | {frac} | {G} | {N} | {k} | {rms:.4f} (x{mult}) | {ns:.4f} | {f95:.3f} | "
                                  f"{row['p0.1']:.2f} | {row['p0.2']:.2f} | {row['p0.3']:.2f} | {row['p0.5']:.2f} | "
                                  f"{row['obs03']:.3f} | {row['deb03']:.3f} |")
        write_csv(os.path.join(a.out, "power.csv"), pw_rows,
                  ["cond", "frac", "G", "N", "k", "rms", "mult", "noise", "floor95", "p0.1", "p0.2", "p0.3", "p0.5", "obs03", "deb03"])

    # --- cost
    if c:
        gbar = mean([g["g"] for g in gens.values()])
        cost = []
        md.append(f"\n## Cost (mean generation length {gbar:.0f} steps; one run per cell gives every shorter window "
                  "through its intermediate checkpoints, so a cell costs its longest window)\n")
        md.append("| window (gens) | mean pop | s/cell | N | k | fractions | runs (2 conditions) | core-h | wall-h on 4 cores |\n|---|---|---|---|---|---|---|---|---|")
        for G in (5, 10):
            for pop in (300, 500, 700):
                t = c[0] + c[1] * pop + c[2] * pop * pop
                sec = G * gbar * t + overhead + 0.05 * G   # + scoring one checkpoint per generation
                for N in (10, 20, 30):
                    for k in (5, 10, 20):
                        for nf in (1, 2):
                            runs = N * N * k * 2 * nf
                            ch = runs * sec / 3600
                            cost.append({"G": G, "pop": pop, "sec_per_cell": sec, "N": N, "k": k, "fractions": nf,
                                         "runs": runs, "core_h": ch, "wall_h_4": ch / 4})
                            if pop == 500 and nf in (1, 2) and k in (5, 10, 20):
                                md.append(f"| {G} | {pop} | {sec:.0f} | {N} | {k} | {nf} | {runs} | {ch:.0f} | {ch / 4:.0f} |")
        write_csv(os.path.join(a.out, "cost.csv"), cost,
                  ["G", "pop", "sec_per_cell", "N", "k", "fractions", "runs", "core_h", "wall_h_4"])

    with open(os.path.join(a.out, "summary.md"), "w") as f:
        f.write("\n".join(md) + "\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())

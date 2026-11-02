#!/usr/bin/env python3
"""analyze.py: invasion-matrix analysis and the Phase 0 pilot report (stdlib only).

    analyze.py --root DIR [--root DIR2 ...] --out OUTDIR --plan PLAN.jsonl [--meta META.json]
               [--windows 2.5,5,10] [--sims 1000] [--power-sims 400] [--no-power]

Reads every finished cell (DIR/cells/<id>/done.json + score.json), checks its
identity (cell spec == the registered plan entry, binary == the root's pinned
binary, score.json == the hash done.json recorded), and writes CSV tables plus
summary.md and inputs.json to OUTDIR. inputs.json binds the report to its
inputs: the plan's and the meta file's SHA-256, the analysis code's, the
engine binaries and pinned tool sets the cells ran with, the registered cells
still missing, and every identity problem; the CSVs carry the plan and
analysis hashes. Only a COMPLETE registered matrix (the largest name set whose
every ordered pair and sham is registered, on the replicates registered for
all of them, every one finished) gets formal decisions (floor, p_mc, p_lof);
without --plan, or with registered cells missing, matrices are descriptive.

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
    """Presentation formatting (Markdown only; the CSVs use csv_value)."""
    if x is None:
        return ""
    if isinstance(x, float):
        if math.isnan(x):
            return "nan"
        if x != 0 and abs(x) < 10 ** -nd:
            return f"{x:.2g}"
        return f"{x:.{nd}f}" if abs(x) < 1e4 else f"{x:.3g}"
    return str(x)


def csv_value(x):
    """Machine-readable cell: floats at round-trip precision (repr: the shortest string that
    parses back to the same double, scientific notation where that is shorter), lists as
    space-joined round-trip values. Rounding is for the Markdown tables only."""
    if x is None:
        return ""
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, float):
        return "nan" if math.isnan(x) else repr(x)
    if isinstance(x, (list, tuple)):
        return " ".join(csv_value(v) for v in x)
    return x


def write_csv(path, rows, cols):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([csv_value(r.get(c)) for c in cols])


def sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(roots, plan=None):
    """Finished cells, each checked against its root and (with a plan) the registered spec:
    done.json's cell == the plan entry, its binary == the root's pinned binary, its score.json
    hash == the one done.json recorded. -> (records, provenance problems)."""
    recs, problems = [], []
    for root in roots:
        cdir = os.path.join(root, "cells")
        pinned_bin = open(os.path.join(root, "bin", "evo_boids.sha256")).read().split()[0]
        for cid in sorted(os.listdir(cdir)):
            d = os.path.join(cdir, cid)
            if ".attempt" in cid or not os.path.exists(os.path.join(d, "done.json")):
                continue
            done = json.load(open(os.path.join(d, "done.json")))
            c = done["cell"]
            bad = []
            if c.get("id") != cid:
                bad.append("cell id differs from its directory")
            if done.get("binary_sha256") != pinned_bin:
                bad.append("binary differs from the root's pinned binary")
            if sha256(os.path.join(d, "score.json")) != done["outputs"].get("score.json"):
                bad.append("score.json does not match done.json")
            if plan is not None and cid in plan and plan[cid] != c:
                bad.append("done.json cell spec differs from the plan entry")
            if bad:
                problems.append(f"{root}/{cid}: " + "; ".join(bad))
                continue
            sc = json.load(open(os.path.join(d, "score.json")))
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
                "binary_sha256": done.get("binary_sha256"), "tools_sha256": done.get("tools_sha256"),
                "registered": plan is None or cid in plan,
            })
    return recs, problems


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
        if r["mode"] != "sham":
            continue
        t = r["turnover"]
        K = min(10, len(t))
        last = r["points"][-1]
        gpop = last["steps"] * r["pop_mean"] / last["births"] if last["births"] else None
        acc.setdefault((r["j"], r["cond"]), []).append((t[K - 1] / K if K else None, t[0] if t else None, K, gpop,
                                                         r["n0"], r["pop_mean"]))
    out = {}
    for k, v in acc.items():
        def col(i):
            return [x[i] for x in v if x[i] is not None]
        o = {"g_n0": mean(col(0)), "g_n0_sd": sd(col(0)), "gen1": mean(col(1)), "gen1_sd": sd(col(1)),
             "k_min": min(x[2] for x in v), "runs": len(v), "g_pop": mean(col(3)), "g_pop_sd": sd(col(3)),
             "n0": v[0][4], "pop_mean": mean(col(5))}
        o["g"] = o["g_pop"] if definition == "pop" else o["g_n0"]
        if o["g"] is not None:
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


def sham_vs_self(rows):
    """The swap procedure's own effect: sham (j's fish swapped into the slots) minus self (the
    slot fish marked in place). Same slots and reseed, so paired by replicate."""
    by = {(x["cond"], x["frac"], x["G"], x["j"], x["mode"], x["rep"]): x for x in rows}
    out = []
    for cond, frac, G, j in sorted({(x["cond"], x["frac"], x["G"], x["j"]) for x in rows if x["mode"] == "self"}):
        d, a, b = [], [], []
        for rep in sorted({x["rep"] for x in rows if (x["cond"], x["frac"], x["G"], x["j"]) == (cond, frac, G, j)}):
            xs, xm = by.get((cond, frac, G, j, "sham", rep)), by.get((cond, frac, G, j, "self", rep))
            if xs and xm and xs["s"] is not None and xm["s"] is not None:
                a.append(xs["s"])
                b.append(xm["s"])
                d.append(xs["s"] - xm["s"])
        if len(d) > 1:
            out.append({"cond": cond, "frac": frac, "G": G, "j": j, "k": len(d), "sham": mean(a), "self": mean(b),
                        "diff": mean(d), "se": sd(d) / math.sqrt(len(d))})
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


def category(ma, mb):
    """Pair relation from snapshot metadata {run, regime, family}: the similarity test's classes."""
    if not ma or not mb:
        return ""
    if ma.get("run") == mb.get("run"):
        return "same-run"
    if ma.get("family") and ma.get("family") == mb.get("family"):
        return "sisters"
    if ma.get("regime") == mb.get("regime"):
        return "same-regime"
    return "cross-regime"


def registry_from_plan(plan):
    """(condition, fraction) -> {(invader, resident, mode): {replicates}} for invade and sham cells."""
    reg = {}
    for c in plan.values():
        if c["mode"] not in ("invade", "sham"):
            continue
        inv = c["invader_name"] if c["mode"] == "invade" else c["resident_name"]
        reg.setdefault((c["condition"], c["fraction"]), {}).setdefault((inv, c["resident_name"], c["mode"]), set()).add(c["replicate"])
    return reg


def _largest_complete(names, has):
    """Drop the name with the most missing ordered pairs / shams until every one is present."""
    names = sorted(names)
    while len(names) >= 3:
        missing = {}
        for a_ in names:
            for b_ in names:
                if not has(a_, b_):
                    missing[a_] = missing.get(a_, 0) + 1
                    missing[b_] = missing.get(b_, 0) + 1
        if not missing:
            break
        names.remove(max(missing, key=lambda k_: (missing[k_], k_)))
    return names


def matrices(rows, meta=None, zmin=2.0, sims=1000, registry=None):
    """Complete blocks (every ordered pair + every sham, on common replicates): per condition,
    fraction and window, separately (pooling conditions can fake cycles).

    Per replicate r the paired matrix s~_r(i->j) = s_r(i->j) - s_r(j->j) gives A_r and its curl_r;
    the headline uses the replicate means. Noise comes from the replicate spread of each cell
    (var_r / k), taken separately for A and for its curl: with common random numbers (one slot
    seed and reseed per resident and replicate) the noise shared within a column is pure gradient,
    so it inflates ||A|| but never the curl.
      cyclic share         ||curl||^2 / ||A||^2
      noise-corrected      (||curl||^2 - E||noise curl||^2) / (||A||^2 - E||noise A||^2)
      lack of fit          X = ||curl||^2 / v_eff ~ chi2(df = P - N + 1) under ladder + noise,
                           v_eff = E||noise curl||^2 / df
      floor95, p_mc        Monte Carlo: pure ladders of the noise-corrected RMS + iid noise of v_eff
      two-way gamma        s~(i->j) = mu + a_i + b_j + gamma_ij; gamma - gamma^T == curl (checked);
                           S_gamma = (gamma_ij + gamma_ji) / 2: coexistence (> 0) vs priority (< 0)
      triads               directed 3-cycles of sign(A), all and with every edge |z| >= zmin
    -> (block rows, per-pair rows)."""
    out, detail = [], []
    keys = sorted({(x["cond"], x["frac"], x["G"]) for x in rows})
    for cond, frac, G in keys:
        cell = {}
        for x in rows:
            if (x["cond"], x["frac"], x["G"]) == (cond, frac, G) and x["mode"] in ("invade", "sham") and x["s"] is not None:
                cell.setdefault((x["i"], x["j"]), {})[x["rep"]] = x["s"]
        # The block and its replicates come from the REGISTERED design (the plan), never from which
        # runs happen to be finished: formal only when every registered cell of the registered
        # block, on the registered replicates, is present. Anything else is descriptive (the
        # largest complete sub-block of what is available, no floor / test decisions).
        status, names, reps = None, None, None
        reg = registry.get((cond, frac)) if registry is not None else None
        if reg:
            kind = lambda a_, b_: (a_, b_, "sham" if a_ == b_ else "invade")   # noqa: E731
            rnames = _largest_complete({x for key in reg for x in key[:2]}, lambda a_, b_: kind(a_, b_) in reg)
            if len(rnames) >= 3:
                R = sorted(set.intersection(*[reg[kind(a_, b_)] for a_ in rnames for b_ in rnames]))
                miss = [(a_, b_, r) for a_ in rnames for b_ in rnames for r in R if r not in cell.get((a_, b_), {})]
                if not miss and len(R) >= 2:
                    status, names, reps = "formal", rnames, R
                else:
                    status = (f"descriptive: {len(miss)} of {len(rnames) ** 2 * len(R)} registered cells "
                              f"of the {len(rnames)}-block missing")
            else:
                status = "descriptive: no complete matrix registered"
        else:
            status = "descriptive: no plan given" if registry is None else "descriptive: nothing registered"
        if status != "formal":
            names = _largest_complete({nm for ij in cell for nm in ij}, lambda a_, b_: (a_, b_) in cell)
            if len(names) < 3:
                continue
            reps = sorted(set.intersection(*[set(cell[(a_, b_)]) for a_ in names for b_ in names]))
        n = len(names)
        k = len(reps)
        if k < 2:
            continue

        def smat(get):
            M = [[None] * n for _ in range(n)]
            for p, a_ in enumerate(names):
                for q, b_ in enumerate(names):
                    if p != q:
                        M[p][q] = get(cell[(a_, b_)]) - get(cell[(b_, b_)])
            return M

        Ms = [smat(lambda d, r=r: d[r]) for r in reps]
        Mbar = smat(lambda d: mean([d[r] for r in reps]))
        A, _ = hodge.antisym_sym(Mbar)
        sp = hodge.split(A)
        A_r = [hodge.antisym_sym(M)[0] for M in Ms]
        C_r = [hodge.split(Ar)["curl"] for Ar in A_r]
        pairs = [(p, q) for p in range(n) for q in range(p + 1, n)]
        P = len(pairs)
        df = P - n + 1
        varA = {pq: sd([Ar[pq[0]][pq[1]] for Ar in A_r]) ** 2 / k for pq in pairs}
        varC = {pq: sd([Cr[pq[0]][pq[1]] for Cr in C_r]) ** 2 / k for pq in pairs}
        EnA, EnC = sum(varA.values()), sum(varC.values())
        curl2 = sp["cyclic_share"] * sp["norm2"]
        corrected = (curl2 - EnC) / (sp["norm2"] - EnA) if sp["norm2"] > EnA else float("nan")
        v_eff = EnC / df
        X = curl2 / v_eff if v_eff > 0 else float("inf")
        p_lof = hodge.chi2_sf(X, df)
        rms_true = math.sqrt(max(1e-12, (sp["norm2"] - EnA) / P))
        floors, f95 = hodge.simulate_floor(n, rms_true, math.sqrt(v_eff), sims=sims, seed=5)
        p_mc = (1 + sum(1 for x in floors if x >= sp["cyclic_share"])) / (1 + len(floors))
        # two-way model on the replicate means, and per replicate for the S_gamma noise
        mu, ea, eb, g = hodge.twoway(Mbar)
        chk = max(abs((g[p][q] - g[q][p]) - sp["curl"][p][q]) for p, q in pairs)
        g_r = [hodge.twoway(M)[3] for M in Ms]
        Sg = {pq: 0.5 * (g[pq[0]][pq[1]] + g[pq[1]][pq[0]]) for pq in pairs}
        varSg = {pq: sd([0.5 * (gr[pq[0]][pq[1]] + gr[pq[1]][pq[0]]) for gr in g_r]) ** 2 / k for pq in pairs}
        Z = [[None] * n for _ in range(n)]
        for p, q in pairs:
            Z[p][q] = Z[q][p] = abs(A[p][q]) / math.sqrt(varA[(p, q)]) if varA[(p, q)] > 0 else float("inf")
        tri = hodge.circular_triads(A, Z, zmin)
        mel = hodge.melo2k(sp["curl"], 1)
        if status != "formal":   # no decisions from a partial matrix
            f95 = p_mc = p_lof = None
        row = {"cond": cond, "frac": frac, "G": G, "status": status, "n": n, "k": k, "names": " ".join(names),
               "ratings": list(sp["r"]), "invader_effect": list(ea), "resident_effect": list(eb),
               "cyclic_share": sp["cyclic_share"], "noise_corrected": corrected, "floor95": f95, "p_mc": p_mc,
               "chi2": X, "df": df, "p_lof": p_lof, "rms_A": math.sqrt(sp["norm2"] / P),
               "noise_A": math.sqrt(EnA / P), "noise_curl": math.sqrt(v_eff), "gamma_check": chk,
               # (the MEAN of S_gamma is 0 by construction: gamma's rows sum to 0; its spread is the signal)
               "rms_Sg": math.sqrt(mean([v * v for v in Sg.values()])),
               "frac_Sg_pos": sum(1 for v in Sg.values() if v > 0) / P,
               "n_Sg_sig_pos": sum(1 for pq in pairs if varSg[pq] > 0 and Sg[pq] / math.sqrt(varSg[pq]) >= zmin),
               "n_Sg_sig_neg": sum(1 for pq in pairs if varSg[pq] > 0 and Sg[pq] / math.sqrt(varSg[pq]) <= -zmin),
               "triads_cyclic": tri["cyclic"], "triads": tri["triads"], "triads_sig": tri["cyclic_significant"],
               "melo_sigma": mel[0][0] if mel else None,
               # mElo2k embedding, flattened u_0 b_0 u_1 b_1 ... (sqrt(sigma)-scaled)
               "melo_xy": [math.sqrt(mel[0][0]) * v for u, b in zip(mel[0][1], mel[0][2]) for v in (u, b)] if mel else None}
        if meta:
            regs = sorted({meta.get(nm, {}).get("regime", "") for nm in names})
            row["regime_ratings"] = " ".join(
                f"{rg}:{mean([sp['r'][p] for p, nm in enumerate(names) if meta.get(nm, {}).get('regime', '') == rg])!r}"
                for rg in regs)
            cats = {}
            for p, q in pairs:
                c = category(meta.get(names[p]), meta.get(names[q]))
                cats.setdefault(c, []).append((abs(A[p][q]), abs(sp["curl"][p][q]), Sg[(p, q)]))
            row["by_category"] = "; ".join(
                f"{c}: n={len(v)} |A|={mean([x[0] for x in v]):.4f} |curl|={mean([x[1] for x in v]):.4f} "
                f"S_gamma={mean([x[2] for x in v]):+.4f}" for c, v in sorted(cats.items()))
        out.append(row)
        for p, q in pairs:
            detail.append({"cond": cond, "frac": frac, "G": G, "a": names[p], "b": names[q],
                           "category": category((meta or {}).get(names[p]), (meta or {}).get(names[q])),
                           "A": A[p][q], "se_A": math.sqrt(varA[(p, q)]), "grad": sp["grad"][p][q],
                           "curl": sp["curl"][p][q], "se_curl": math.sqrt(varC[(p, q)]),
                           "S_gamma": Sg[(p, q)], "se_S_gamma": math.sqrt(varSg[(p, q)])})
    return out, detail


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
    ap.add_argument("--power-windows", default="5,10", help="windows (gens) that get a power table")
    ap.add_argument("--meta", help="JSON {snapshot: {run, regime, family, time}} for pair relations / regimes")
    ap.add_argument("--plan", help="the registered plan (JSONL): every cell is validated against it, and only a "
                                   "complete registered matrix gets formal decisions")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    windows = [float(x) for x in a.windows.split(",")]
    plan = None
    if a.plan:
        plan = {}
        for ln in open(a.plan):
            if ln.strip():
                c = json.loads(ln)
                plan[c["id"]] = c
    recs, problems = load(a.root, plan)
    registry = registry_from_plan(plan) if plan is not None else None
    here = os.path.dirname(os.path.abspath(__file__))
    prov = {
        "schema": "finfolk.invasion.analysis/1",
        "roots": [os.path.abspath(r) for r in a.root],
        "plan": {"path": os.path.abspath(a.plan), "sha256": sha256(a.plan), "cells": len(plan)} if plan is not None else None,
        "meta": {"path": os.path.abspath(a.meta), "sha256": sha256(a.meta)} if a.meta else None,
        "analysis_code": {f: sha256(os.path.join(here, f)) for f in ("analyze.py", "hodge.py")},
        "binaries": sorted({r["binary_sha256"] for r in recs}),
        "tools": sorted({json.dumps(r["tools_sha256"], sort_keys=True) for r in recs if r["tools_sha256"]}),
        "cells_without_tool_hashes": sum(1 for r in recs if not r["tools_sha256"]),
        "args": vars(a),
        "finished": len(recs),
        "identity_problems": problems,
    }
    if plan is not None:
        have = {r["id"] for r in recs}
        prov["registered_missing"] = sorted(set(plan) - have)
        prov["unregistered_finished"] = sorted(have - set(plan))
    prov["complete"] = plan is not None and not prov["registered_missing"] and not problems
    invlib_json = json.dumps(prov, indent=1, sort_keys=True, default=str)
    with open(os.path.join(a.out, "inputs.json"), "w") as f:
        f.write(invlib_json + "\n")
    ident = {"plan_sha256": prov["plan"]["sha256"] if prov["plan"] else "",
             "analysis_sha256": prov["analysis_code"]["analyze.py"]}
    gens = gen_length(recs, a.gen_def)
    rows = run_rows(recs, gens, windows)
    grp = groups(rows)
    prs = paired(rows)
    pt = pair_table(prs)
    meta = json.load(open(a.meta)) if a.meta else None
    for p in pt:
        p["category"] = category(meta.get(p["a"]), meta.get(p["b"])) if meta else ""
        p.update(ident)
    md = []
    md.append(f"# Invasion pilot analysis\n\n{len(recs)} finished runs from {', '.join(a.root)}.\n")
    md.append("Inputs (also in inputs.json): plan " + (f"`{a.plan}` sha256 `{prov['plan']['sha256'][:16]}` "
              f"({prov['plan']['cells']} registered cells, {len(prov['registered_missing'])} missing, "
              f"{len(prov['unregistered_finished'])} finished but unregistered)" if plan is not None else "NONE (descriptive only)") +
              f"; analysis code analyze.py `{prov['analysis_code']['analyze.py'][:16]}`, hodge.py "
              f"`{prov['analysis_code']['hodge.py'][:16]}`; engine binaries {[b[:16] for b in prov['binaries']]}; "
              f"{len(prov['tools'])} pinned tool set(s), {prov['cells_without_tool_hashes']} cells from before tool pinning; "
              f"{len(problems)} identity problem(s).\n")
    md.append(f"**Status: {'COMPLETE (formal decisions allowed on registered complete matrices)' if prov['complete'] else 'INCOMPLETE or unregistered: matrices without a complete registered set are descriptive only'}**\n")
    for p in problems[:20]:
        md.append(f"- identity problem: {p}")

    # --- generation length
    grow = [{"j": j, "cond": c, **v} for (j, c), v in sorted(gens.items())]
    write_csv(os.path.join(a.out, "gen.csv"), grow,
              ["j", "cond", "n0", "pop_mean", "g_pop", "g_pop_sd", "g_n0", "g_n0_sd", "gen1", "gen1_sd", "k_min", "runs", "g"])
    md.append(f"## Generation length (sham runs; window clock = {'g_pop' if a.gen_def == 'pop' else 'g_n0'})\n")
    md.append("g_pop = steps x mean population / births; g_n0 = steps until births reach k x start population, / k "
              "(k <= 10); first gen = steps until births = start population.\n")
    md.append("| snapshot | condition | start pop | mean pop | g_pop | SD | g_n0 | SD | first gen | SD | runs |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for g in grow:
        md.append(f"| {g['j']} | {g['cond']} | {g['n0']} | {fmt(g['pop_mean'], 0)} | {fmt(g['g_pop'], 0)} | {fmt(g['g_pop_sd'], 0)} | "
                  f"{fmt(g['g_n0'], 0)} | {fmt(g['g_n0_sd'], 0)} | {fmt(g['gen1'], 0)} | {fmt(g['gen1_sd'], 0)} | {g['runs']} |")

    write_csv(os.path.join(a.out, "runs.csv"), rows,
              ["id", "j", "i", "mode", "frac", "cond", "rep", "n0", "m", "G", "W", "steps_at", "over", "s", "n",
               "births", "gens", "invader_lost", "extinct"])
    write_csv(os.path.join(a.out, "groups.csv"), grp,
              ["cond", "frac", "G", "j", "i", "mode", "k", "mean", "sd", "se", "lost", "extinct", "W", "n_end", "over"])
    write_csv(os.path.join(a.out, "paired.csv"), prs,
              ["cond", "frac", "G", "j", "i", "k", "s_inv", "s_sham", "st", "sd_d", "se_paired", "se_unpaired",
               "sd_inv", "sd_sham", "gain", "corr", "z"])
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

    svs = sham_vs_self(rows)
    if svs:
        md.append("\n## The swap procedure's own effect: sham minus self (paired: same slots, same reseed)\n")
        md.append("| condition | fraction | window | snapshot | k | mean s sham | mean s self | sham - self | SE |\n|---|---|---|---|---|---|---|---|---|")
        for x in svs:
            md.append(f"| {x['cond']} | {x['frac']} | {x['G']} | {x['j']} | {x['k']} | {x['sham']:+.4f} | {x['self']:+.4f} | "
                      f"{x['diff']:+.4f} | {x['se']:.4f} |")

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
                corrs = [p["corr"] for p in ps if p["corr"] is not None]
                zs = [abs(p["z"]) for p in ps if p["z"] is not None]
                med = gains[len(gains) // 2] if gains else None
                md.append(f"| {cond} | {frac} | {G} | {len(ps)} | {pooled:.4f} | {fmt(med, 2)} | "
                          f"{fmt(mean(corrs), 2)} | {mean([abs(p['st']) for p in ps]):.4f} | "
                          f"{fmt(max(zs) if zs else None, 1)} |")

    md.append("\n## Effect sizes on real pairs (A = s~(a->b) - s~(b->a), S = mean of both)\n")
    md.append("| condition | fraction | window | a | b | relation | s~(a->b) | s~(b->a) | A | z_A | S | z_S |\n|---|---|---|---|---|---|---|---|---|---|---|---|")
    for p in pt:
        md.append(f"| {p['cond']} | {p['frac']} | {p['G']} | {p['a']} | {p['b']} | {p['category']} | {p['st_a_into_b']:+.4f} | {p['st_b_into_a']:+.4f} | "
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
    write_csv(os.path.join(a.out, "pairs.csv"), pt,
              ["cond", "frac", "G", "a", "b", "category", "st_a_into_b", "st_b_into_a", "A_ab", "S", "se_A", "se_S",
               "z_A", "z_S", "plan_sha256", "analysis_sha256"])
    mats, mdet = matrices(rows, meta, sims=a.sims, registry=registry)
    for m in mats:
        m.update(ident)
    if mats:
        cols = ["cond", "frac", "G", "status", "plan_sha256", "analysis_sha256", "n", "k", "names", "ratings",
                "invader_effect", "resident_effect", "cyclic_share",
                "noise_corrected", "floor95", "p_mc", "chi2", "df", "p_lof", "rms_A", "noise_A", "noise_curl",
                "gamma_check", "rms_Sg", "frac_Sg_pos", "n_Sg_sig_pos", "n_Sg_sig_neg", "triads_cyclic", "triads",
                "triads_sig", "melo_sigma", "melo_xy", "regime_ratings", "by_category"]
        write_csv(os.path.join(a.out, "matrix.csv"), mats, cols)
        write_csv(os.path.join(a.out, "matrix_pairs.csv"), mdet,
                  ["cond", "frac", "G", "a", "b", "category", "A", "se_A", "grad", "curl", "se_curl", "S_gamma", "se_S_gamma"])
        md.append("\n## Complete blocks: ladder / cycle split (each condition separately)\n")
        md.append("cyclic share = ||curl||^2/||A||^2; noise-corrected = both norms minus their replicate-estimated noise "
                  "energy; chi2 = lack of fit of a pure ladder (df = P - N + 1); floor95 / p_mc = Monte Carlo pure "
                  "ladders with this block's noise; S_gamma = symmetric part of the two-way interaction (> 0 "
                  "coexistence, < 0 priority); triads = directed 3-cycles of sign(A) (all / every edge |z| >= 2).\n")
        md.append("| condition | fraction | window | status | N | k | RMS A | noise A | noise curl | cyclic share | noise-corrected | floor95 | p_mc | chi2 (df) | p_lof | RMS S_gamma | S_gamma sig +/- | triads cyclic/all (sig) |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for m in mats:
            pl = f"{m['p_lof']:.2g}" if m["p_lof"] is not None else "-"
            md.append(f"| {m['cond']} | {m['frac']} | {m['G']} | {m['status']} | {m['n']} | {m['k']} | {m['rms_A']:.4f} | {m['noise_A']:.4f} | "
                      f"{m['noise_curl']:.4f} | {m['cyclic_share']:.3f} | {fmt(m['noise_corrected'], 3)} | {fmt(m['floor95'], 3) or '-'} | "
                      f"{fmt(m['p_mc'], 3) or '-'} | {m['chi2']:.1f} ({m['df']}) | {pl} | {m['rms_Sg']:.4f} | "
                      f"{m['n_Sg_sig_pos']}/{m['n_Sg_sig_neg']} | {m['triads_cyclic']}/{m['triads']} ({m['triads_sig']}) |")
        md.append("\n| condition | fraction | window | names | ladder ratings | by home regime | by pair relation |\n|---|---|---|---|---|---|---|")
        for m in mats:
            regr = " ".join(f"{t.split(':')[0]}:{float(t.split(':')[1]):+.4f}" for t in m.get("regime_ratings", "").split())
            md.append(f"| {m['cond']} | {m['frac']} | {m['G']} | {m['names']} | {' '.join(f'{x:+.4f}' for x in m['ratings'])} | "
                      f"{regr} | {m.get('by_category', '')} |")

    # --- speed
    c, pts = speed_fit(recs)
    srows = [{"pop_mean": p, "sec_per_step": t} for p, t in pts]
    write_csv(os.path.join(a.out, "speed.csv"), srows, ["pop_mean", "sec_per_step"])
    overhead = mean([r["build_s"] + r["score_s"] for r in recs]) + 0.15   # + interpreter start
    md.append("\n## Engine speed (serial build, 4 concurrent workers at nice 19)\n")
    if c:
        md.append(f"seconds/step = {c[0]:.3e} + {c[1]:.3e} pop + {c[2]:.3e} pop^2 (fit over {len(pts)} logged "
                  f"1,000-step intervals of {len(recs)} runs: population at the interval's end vs its steps/s). "
                  f"Per-cell overhead (arena build + scoring) ~{overhead:.1f} s.\n")
        md.append("| mean population | steps/s |\n|---|---|")
        for pop in (200, 300, 400, 500, 600, 700, 900):
            t = c[0] + c[1] * pop + c[2] * pop * pop
            md.append(f"| {pop} | {1 / t:.0f} |")

    # --- power
    pw_rows = []
    blocks = {(m["cond"], m["frac"], m["G"]): m for m in mats}
    if not a.no_power and dnoise and effect:
        md.append("\n## Noise floor and planted-cycle recovery (simulated at the measured noise)\n")
        md.append("Noise per A cell for one replicate: from the complete block when there is one (the curl's own "
                  "replicate noise, sqrt(v_eff x k): under common random numbers the column-shared noise is pure "
                  "gradient and cannot fake cycles), else sqrt(2) x the pooled SD of s~ per replicate (conservative). "
                  "With k replicates it is that / sqrt(k). True RMS of A = the noise-corrected RMS of the block "
                  "(else of the pilot pairs), x0.5 / x1 / x2. Floor = 95th percentile of the cyclic share of pure "
                  "ladders; power = P(planted share > floor); 'obs' and 'corrected' = mean observed and "
                  "noise-corrected share at a planted 0.3.\n")
        md.append("| condition | fraction | window | noise source | N | k | true RMS A | noise/cell | floor95 | share 0.1 | 0.2 | 0.3 | 0.5 | obs @0.3 | corrected @0.3 |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        pwin = [float(x) for x in a.power_windows.split(",")]
        for key in sorted(dnoise):
            cond, frac, G = key
            if a.power_cond and cond != a.power_cond:
                continue
            if G not in pwin:
                continue
            if key not in effect:
                continue
            blk = blocks.get(key)
            if blk:
                sigma1 = blk["noise_curl"] * math.sqrt(blk["k"])
                rms0 = math.sqrt(max(0.0, blk["rms_A"] ** 2 - blk["noise_A"] ** 2))
                src = f"block N={blk['n']}"
            else:
                sigma1 = math.sqrt(2) * dnoise[key]
                rms0 = effect[key]["rms_true"]
                src = "pairs"
            for mult in (0.5, 1.0, 2.0):
                rms = rms0 * mult
                if rms <= 0:
                    continue
                for N, ks in ((20, (3, 5, 10, 20)), (10, (10,)), (30, (10,))):
                    for k in ks:
                        if mult != 1.0 and (N != 20 or k not in (5, 10)):
                            continue
                        ns = sigma1 / math.sqrt(k)
                        _, f95 = hodge.simulate_floor(N, rms, ns, sims=a.sims, seed=11)
                        row = {"cond": cond, "frac": frac, "G": G, "N": N, "k": k, "rms": rms, "mult": mult,
                               "noise": ns, "floor95": f95, "source": src, **ident}
                        for share in (0.1, 0.2, 0.3, 0.5):
                            r = hodge.simulate_power(N, rms, share, ns, f95, sims=a.power_sims, seed=13)
                            row[f"p{share}"] = r["power"]
                            if share == 0.3:
                                row["obs03"] = r["mean_share"]
                                row["deb03"] = r["mean_debiased"]
                        pw_rows.append(row)
                        md.append(f"| {cond} | {frac} | {G} | {src} | {N} | {k} | {rms:.4f} (x{mult}) | {ns:.4f} | {f95:.3f} | "
                                  f"{row['p0.1']:.2f} | {row['p0.2']:.2f} | {row['p0.3']:.2f} | {row['p0.5']:.2f} | "
                                  f"{row['obs03']:.3f} | {row['deb03']:.3f} |")
        # Assumption-light companion: the smallest cyclic component the lack-of-fit test detects with
        # 80% power at alpha 0.05, whatever the ladder looks like (the ladder does not enter the curl).
        md.append("\nMinimum detectable cycle (chi2 lack of fit, alpha 0.05, power 0.8; normal approximation to the "
                  "noncentral chi2): RMS of the curl per pair, against the per-cell noise of that row.\n")
        md.append("| condition | fraction | window | N | k | noise/cell | min detectable curl RMS per pair |\n|---|---|---|---|---|---|---|")
        seen = set()
        for row in pw_rows:
            key = (row["cond"], row["frac"], row["G"], row["N"], row["k"])
            if key in seen or row["mult"] != 1.0:
                continue
            seen.add(key)
            N = row["N"]
            df = (N - 1) * (N - 2) // 2
            crit = df + 1.6449 * math.sqrt(2 * df)
            lo, hi = 0.0, 50.0 * df
            for _ in range(100):   # solve df + lam - 0.8416 sqrt(2 (df + 2 lam)) = crit
                lam = 0.5 * (lo + hi)
                if df + lam - 0.8416 * math.sqrt(2 * (df + 2 * lam)) < crit:
                    lo = lam
                else:
                    hi = lam
            P = N * (N - 1) / 2
            row["min_curl_rms"] = math.sqrt(lam * row["noise"] ** 2 / P)
            md.append(f"| {row['cond']} | {row['frac']} | {row['G']} | {N} | {row['k']} | {row['noise']:.4f} | "
                      f"{row['min_curl_rms']:.4f} |")
        write_csv(os.path.join(a.out, "power.csv"), pw_rows,
                  ["cond", "frac", "G", "source", "N", "k", "rms", "mult", "noise", "floor95", "p0.1", "p0.2", "p0.3",
                   "p0.5", "obs03", "deb03", "min_curl_rms", "plan_sha256", "analysis_sha256"])

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
                            if pop == 500 and k in (5, 10):
                                md.append(f"| {G} | {pop} | {sec:.0f} | {N} | {k} | {nf} | {runs} | {ch:.0f} | {ch / 4:.0f} |")
        write_csv(os.path.join(a.out, "cost.csv"), cost,
                  ["G", "pop", "sec_per_cell", "N", "k", "fractions", "runs", "core_h", "wall_h_4"])

    with open(os.path.join(a.out, "summary.md"), "w") as f:
        f.write("\n".join(md) + "\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())

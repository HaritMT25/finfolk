#!/usr/bin/env python3
"""analyze.py: invasion-matrix analysis and the Phase 0 pilot report (stdlib only).

    analyze.py --root DIR [--root DIR2 ...] --out OUTDIR --plan PLAN.jsonl [--meta META.json]
               [--windows 2.5,5,10] [--sims 1000] [--power-sims 400] [--no-power]

Reads every finished cell (DIR/cells/<id>/done.json + score.json), checks its
identity (cell spec == the registered plan entry, binary == the root's pinned
binary, score.json / arena.manifest.json / run.csv == the hashes done.json
recorded, the snapshot files the arena read == the registered ones, ONE file
content per snapshot name across all cells), and writes CSV tables plus
summary.md and inputs.json to OUTDIR. inputs.json binds the report to its
inputs: the plan's and the meta file's SHA-256, the analysis code's, the
engine binaries and pinned tool sets the cells ran with, the snapshot
identities, cells.csv (every cell result used, by content hash), the
registered cells still missing, and every identity problem; the CSVs carry
the plan and analysis hashes. Only a COMPLETE registered matrix (the largest name set whose
every ordered pair and sham is registered, on the replicates registered for
all of them, every one finished) gets formal decisions (floor, p_mc, p_lof);
without --plan, or with registered cells missing, matrices are descriptive.

  cells.csv    every cell result the tables use: root, id, done.json / score.json /
               manifest / run.csv SHA-256, and the snapshot files it read
  gen.csv      generation length per (snapshot, condition): steps until the
               births reach k x the start population, from the sham runs
  runs.csv     one row per run and window: the score at the scored checkpoint
               nearest W = G x generation length of the RESIDENT (the same W for
               i->j and its sham j->j), with W, the steps actually read and the
               relative error; no score ("missed") when no checkpoint lies within
               --max-window-error x W (a run that ended early is never read at its
               final checkpoint instead), and a registered cell with a missed
               window makes its matrix descriptive
  groups.csv   per (condition, fraction, window, resident, invader, mode): mean,
               SD, SE of s over replicates; invader-lost and extinction counts
  paired.csv   per invade cell: s~ = mean_r [s(i->j, r) - s(j->j, r)] with the
               paired SD and the pairing gain G = (var_a + var_b) / var_(a-b)
  pairs.csv    both directions observed: A = s~(i->j) - s~(j->i),
               S = (s~(i->j) + s~(j->i)) / 2, their SE and z, and what the two
               directed scores support by their own bounds (reciprocal gain /
               reciprocal suppression / opposite directions / unresolved);
               S > 0 alone is never read as mutual invasibility or coexistence.
               s is the change in the invaders' founder PEDIGREE contribution
               (score.py), not genomic ancestry
  matrix.csv   when a resident x invader block is complete: the Hodge split
               (ratings, raw / noise-corrected cyclic share with its confidence
               range, lack-of-fit and symmetric-interaction tests from infer.py)
               per condition/fraction/window; matrix_joint.csv the omnibus over
               the assay conditions
               (only when every REGISTERED condition's block is formal), pooled
               and as the spec's home-regime sub-blocks x assays (regimes
               independent); sub-block p-values only under a formal parent
  scale.csv    bounded-scale sensitivity: the same split and tests on
               transformed endpoints (logit with a documented clip, asin)
  bounded.csv  bounded node-additive (transitive, non-additive) models of the
               expected endpoint, the curl they make and the cyclic energy left
               after them, with a refitting bootstrap test (bounded.py)
  blocks.json  every block's units z[p][r][i] (input to calibrate.py, which
               measures the null rejection rate and planted-cycle power of the
               same tests)

Windows: --clock gens (G generations of the resident's clock) or --clock steps
(one common fixed step count for every run, the stats spec's primary horizon;
T from horizon.py, calibrated on independent cells, and 2T).
  speed.csv    engine seconds per step against mean population (+ a fit)
  cost.csv     seconds per cell and core-hours for N x replicates x settings
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bounded  # noqa: E402
import hodge  # noqa: E402
import infer  # noqa: E402


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


def position(c):
    """The semantic position of a cell spec in the analysis: two cells at one position would
    overwrite each other in every table, so a position must be unique."""
    inv = c["resident_name"] if c["mode"] == "sham" else c["invader_name"]
    return (c["condition"], c["fraction"], c["mode"], inv, c["resident_name"], c["replicate"])


def plan_problems(plan):
    """Registered cells that share one semantic position (ambiguous by construction)."""
    seen = {}
    for cid, c in plan.items():
        seen.setdefault(position(c), []).append(cid)
    return {cid for ids in seen.values() if len(ids) > 1 for cid in ids}


def load(roots, plan=None):
    """Finished cells that may enter the analysis, and why the others may not.

    Each candidate is checked against its root and (with a plan) the registered spec: done.json's
    cell == the plan entry, its binary == the root's pinned binary, its score.json hash == the one
    done.json recorded. With a plan, ONLY registered cells are used, for every table (the
    generation clock and the costs included): an unregistered finished cell is listed and
    skipped, never allowed to stand in for a missing registered one. A cell id finished in more
    than one root, and two cells at one semantic position (condition, fraction, mode, invader,
    resident, replicate), are identity problems: all their copies are excluded, since nothing says
    which one is right. -> (records, provenance problems, unregistered ids)."""
    recs, problems, unregistered = [], [], []
    cands = []
    for root in roots:
        cdir = os.path.join(root, "cells")
        pinned_bin = open(os.path.join(root, "bin", "evo_boids.sha256")).read().split()[0]
        for cid in sorted(os.listdir(cdir)):
            d = os.path.join(cdir, cid)
            if ".attempt" in cid or not os.path.exists(os.path.join(d, "done.json")):
                continue
            cands.append((root, cid, d, pinned_bin))
    count = {}
    for _, cid, _, _ in cands:
        count[cid] = count.get(cid, 0) + 1
    ambiguous_plan = plan_problems(plan) if plan is not None else set()
    by_pos = {}
    for root, cid, d, pinned_bin in cands:
        done = json.load(open(os.path.join(d, "done.json")))
        c = done["cell"]
        if plan is not None and cid not in plan:
            unregistered.append(f"{root}/{cid}")
            continue
        bad = []
        if count[cid] > 1:
            bad.append(f"cell id finished in {count[cid]} roots")
        if cid in ambiguous_plan:
            bad.append("the plan registers another cell at the same position")
        if c.get("id") != cid:
            bad.append("cell id differs from its directory")
        if done.get("binary_sha256") != pinned_bin:
            bad.append("binary differs from the root's pinned binary")
        hashes = {"done.json": sha256(os.path.join(d, "done.json"))}
        for f in ("score.json", "arena.manifest.json", "run.csv"):   # every file the tables read
            hashes[f] = sha256(os.path.join(d, f)) if os.path.exists(os.path.join(d, f)) else "missing"
            if hashes[f] != done["outputs"].get(f):
                bad.append(f"{f} does not match done.json")
        ident = {}
        if not bad:
            man = json.load(open(os.path.join(d, "arena.manifest.json")))
            ident[c["resident_name"]] = man["resident"]["sha256"]
            if c["mode"] == "invade":
                ident[c["invader_name"]] = man["invader"]["sha256"]
            for role in ("resident", "invader"):   # plans from plan.py register the content too
                want = c.get(f"{role}_sha256")
                if want and ident.get(c[f"{role}_name"]) != want:
                    bad.append(f"the arena read a {role} file other than the registered one")
        if plan is not None and plan[cid] != c:
            bad.append("done.json cell spec differs from the plan entry")
        if bad:
            problems.append(f"{root}/{cid}: " + "; ".join(bad))
            continue
        by_pos.setdefault(position(c), []).append((root, cid, d, done, hashes, ident))
    # one source identity per item: the cells that read one snapshot name must all have read the
    # same file content, or the name covers two populations (a snapshot overwritten between batch
    # attempts) and none of its cells can be trusted
    seen = {}
    for group in by_pos.values():
        for _, cid, _, _, _, ident in group:
            for nm, h in ident.items():
                seen.setdefault(nm, {}).setdefault(h, []).append(cid)
    split = {nm for nm, hs in seen.items() if len(hs) > 1}
    for nm in sorted(split):
        problems.append(f"snapshot {nm} was read as {len(seen[nm])} different files ("
                        + ", ".join(f"{h[:12]} by {len(ids)} cells" for h, ids in sorted(seen[nm].items()))
                        + "): every cell using it is excluded")
    snapshots = {nm: next(iter(hs)) for nm, hs in sorted(seen.items()) if nm not in split}
    for pos, group in sorted(by_pos.items(), key=lambda kv: str(kv[0])):
        if len(group) > 1:
            ids = ", ".join(f"{g[0]}/{g[1]}" for g in group)
            problems.append(f"{len(group)} cells at one position {pos}: {ids} (all excluded)")
            continue
        root, cid, d, done, hashes, ident = group[0]
        c = done["cell"]
        if split & set(ident):
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
            "registered": plan is not None, "hashes": hashes, "sources": ident,
        })
    return recs, problems, unregistered, snapshots


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


def pick(r, W, tol):
    """The scored checkpoint nearest W steps, or None when no checkpoint lies within tol x W of
    it: the run ended before the window (or its checkpoints are too sparse there). A requested
    window is never silently read at an earlier or the final checkpoint."""
    pts = r["points"]
    best = min(pts, key=lambda p: abs(p["steps"] - W))
    return best if abs(best["steps"] - W) <= tol * W else None


def run_rows(recs, gens, windows, tol, clock="gens"):
    """One row per run and window: requested W, the checkpoint actually read (steps_at) and its
    relative timing error; s is None (window missed) when no checkpoint is within tol.

    clock 'gens': a window G is G x the RESIDENT's generation length (g_pop of its shams), so the
    two directions of a pair run for different numbers of steps. clock 'steps' (the stats spec's
    primary horizon): a window is one common fixed number of steps W = G for every run, read only
    at a checkpoint at exactly step W (tolerance 0, whatever --max-window-error says); the
    realized turnover g = births / start population at W is reported per run (column gens).

    Extinction (stats spec section 2): the live mean is undefined when no fish is left; the
    preregistered unconditional endpoint sets q = 0 there, so s = -f0 (and extinct = True). An
    extinct assay is never dropped."""
    rows = []
    for r in recs:
        g = gens.get((r["j"], r["cond"]))
        if clock == "gens" and not g:
            continue
        for G in windows:
            W = G * g["g"] if clock == "gens" else float(G)
            # a fixed-step window is read at exactly W or not at all (review round 3: the nearest
            # checkpoint within 10% gave every registered schedule its own exposure)
            p = pick(r, W, tol if clock == "gens" else 0.0)
            base = {**{k: r[k] for k in ("id", "j", "i", "mode", "frac", "cond", "rep", "n0", "m", "f0")},
                    "G": G, "W": W, "last_steps": r["points"][-1]["steps"]}
            if p is None:
                rows.append({**base, "steps_at": None, "rel_err": None, "missed": True, "s": None, "n": None,
                             "births": None, "gens": None, "invader_lost": None, "extinct": None})
                continue
            s = p["score"]
            if s is None and p["extinct"]:
                s = -r["f0"]   # q_ext = 0: no living ancestry remains (an explicit convention)
            rows.append({**base, "steps_at": p["steps"], "rel_err": (p["steps"] - W) / W, "missed": False,
                         "s": s, "n": p["n"], "births": p["births"], "gens": p["generations"],
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
                    "W": xs[0]["W"], "n_end": mean([x["n"] for x in xs if x["n"] is not None]),
                    "missed": sum(1 for x in xs if x["missed"])})
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


# Both directed bounds at once: two one-sided 97.5% bounds hold jointly at >= 95% (Bonferroni over
# the two directions of a pair; not adjusted across pairs: the column is descriptive). Each
# direction's statistic is a paired t with k - 1 degrees of freedom (its SD is estimated from k
# replicates), so its bound uses the Student-t quantile, t_.975(k - 1): 2.571 at k = 6, 2.262 at
# k = 10 (review round 2: the normal 1.96 does not give the claimed 95% at these k). The coverage
# is exact for Gaussian paired differences and approximate otherwise. Z_RECIPROCAL is only the
# large-k limit, used when k is unknown.
Z_RECIPROCAL = 1.959964
CONF_DIRECTION = 0.975


def direction_cutoff(k):
    """The one-sided 97.5% bound's cutoff for a paired t statistic from k replicates."""
    if k is None or k < 2:
        return Z_RECIPROCAL
    return hodge.t_quantile(CONF_DIRECTION, k - 1)


def reciprocal(z_ab, z_ba, k_ab=None, k_ba=None):
    """What the two DIRECTED sham-corrected scores of a pair support (stats spec section 7), each
    by its own one-sided 97.5% Student-t bound (k replicates -> t_.975(k - 1)); both bounds hold
    jointly at >= 95% for Gaussian paired differences. A positive symmetric part S does not need
    both directions to gain, so S never decides this.
      'reciprocal gain'        both directions' lower bounds > 0: excess founder-pedigree
                               introgression both ways, relative to self-invasion. Not by itself
                               coexistence (sexual mixing can do this; coexistence needs
                               persistence of distinct types)
      'reciprocal suppression' both upper bounds < 0: each resists the other's introgression
      'opposite directions'    one bounded above 0, the other below
      'unresolved'             at least one direction is not bounded away from 0"""
    if z_ab is None or z_ba is None:
        return "unresolved"
    ca, cb = direction_cutoff(k_ab), direction_cutoff(k_ba)
    if z_ab >= ca and z_ba >= cb:
        return "reciprocal gain"
    if z_ab <= -ca and z_ba <= -cb:
        return "reciprocal suppression"
    if (z_ab >= ca and z_ba <= -cb) or (z_ab <= -ca and z_ba >= cb):
        return "opposite directions"
    return "unresolved"


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
                    "z_S": S / (0.5 * se_A) if se_A > 0 else None,
                    "z_a_into_b": p["z"], "z_b_into_a": q["z"], "k_a_into_b": p.get("k"), "k_b_into_a": q.get("k"),
                    "cut_a_into_b": direction_cutoff(p.get("k")), "cut_b_into_a": direction_cutoff(q.get("k")),
                    "reciprocal": reciprocal(p["z"], q["z"], p.get("k"), q.get("k"))})
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
    """Pair relation from snapshot metadata {run, regime, family}, EXCLUSIVE classes in this order
    of precedence: same-run, sisters, same-regime (different runs and families), cross-regime.
    So 'same-regime' excludes same-run pairs; relation_groups adds the inclusive groups."""
    if not ma or not mb:
        return ""
    if ma.get("run") == mb.get("run"):
        return "same-run"
    if ma.get("family") and ma.get("family") == mb.get("family"):
        return "sisters"
    if ma.get("regime") == mb.get("regime"):
        return "same-regime"
    return "cross-regime"


def relation_groups(ma, mb):
    """Every summary group a pair belongs to: its exclusive category, plus 'within-regime (all)'
    for every pair whose two snapshots share a home regime (same-run and sister pairs included)."""
    c = category(ma, mb)
    if not c:
        return []
    return [c] + (["within-regime (all)"] if ma.get("regime") == mb.get("regime") else [])


def unit_curl_noise(z):
    """Per-edge noise variance of the curl of the edge MEANS, (Q V Q)_ee, from the units (the
    diagonal of infer's tau_C): sum over units of (Q B_p d)_e^2 / (k (k - 1))."""
    N, k = len(z), len(z[0])
    m = infer.column_means(z)
    P = N * (N - 1) // 2
    out = [0.0] * P
    for p in range(N):
        for zr in z[p]:
            d = [x - y for x, y in zip(zr, m[p])]
            unit = [[0.0] * N for _ in range(N)]
            unit[p] = d
            c = infer.curl_vec(infer.antisym(unit), N)[0]
            for e in range(P):
                out[e] += c[e] * c[e]
    return [x / (k * (k - 1)) for x in out]


def subblock(z, idx):
    """The units of the complete sub-block of items idx (positions in the block)."""
    return [[[z[p][r][i] for i in idx] for r in range(len(z[p]))] for p in idx]


def subgraph_summary(z, keep):
    """The comparison graph of the edges (p, q) with keep(p, q), all items, unit weights (an
    INCOMPLETE graph, e.g. the bipartite cross-regime pairs): gradient / local / harmonic energies
    of the edge means (hodge.decompose) and their unit-estimated noise energies, so the cyclic
    share can be noise-corrected. Descriptive (no test). -> dict."""
    N, k = len(z), len(z[0])

    def restrict(m):
        A = infer.antisym(m)
        M = [[None] * N for _ in range(N)]
        e = 0
        for p in range(N):
            for q in range(p + 1, N):
                if keep(p, q):
                    M[p][q], M[q][p] = A[e], -A[e]
                e += 1
        return M
    obs = hodge.decompose(restrict(infer.column_means(z)))
    basis, _ = hodge.triangle_basis(N, obs["edges"])
    m = infer.column_means(z)
    tau = {"E_A": 0.0, "E_grad": 0.0, "E_local": 0.0, "E_harm": 0.0}
    for p in range(N):
        for zr in z[p]:
            unit = [[0.0] * N for _ in range(N)]
            unit[p] = [x - y for x, y in zip(zr, m[p])]
            du = hodge.decompose(restrict(unit), basis)
            for x in tau:
                tau[x] += du[x]
    tau = {x: v / (k * (k - 1)) for x, v in tau.items()}
    cyc = obs["E_local"] + obs["E_harm"]
    tcyc = tau["E_local"] + tau["E_harm"]
    return {"edges": len(obs["edges"]), "q_cycle": obs["q_cycle"], "q_local": obs["q_local"],
            "triangles": obs["triangles"], "cyclic_share": cyc / obs["E_A"] if obs["E_A"] > 0 else float("nan"),
            "noise_corrected": (cyc - tcyc) / (obs["E_A"] - tau["E_A"]) if obs["E_A"] > tau["E_A"] else float("nan"),
            "local_nc": obs["E_local"] - tau["E_local"], "harmonic_nc": obs["E_harm"] - tau["E_harm"],
            "F_lof": cyc / tcyc if tcyc > 0 else float("nan"),
            "dC": math.sqrt(max(0.0, cyc - tcyc) / len(obs["edges"]))}


def genetic_dissimilarity(paths, samples=4000, seed=7):
    """Sensor-relevant genetic dissimilarity between snapshots (stats spec section 9):
    d_G(a, b) = 1 - mean genomeSimilarity over random fish pairs (u in a, v in b), with the
    engine's genomeSimilarity (genome.hpp): the fraction of aligned slots whose source-type and
    sink-type bits BOTH match (bits 15 and 7 of the checkpoint's packed wiring word,
    checkpoint_io.hpp). It is not full gene identity. Also the within-snapshot value (a diversity
    covariate). -> ({(a, b): d}, {a: d_within})."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import invlib
    types = {}
    for nm, path in sorted(paths.items()):
        cs = invlib.load_checkpoint(path)["creatures"]
        g, gi = [], 0
        for k in range(int(cs["count"])):
            L = int(cs["genomeLengths"][k])
            w = cs["genes"][gi:gi + 2 * L:2]
            gi += 2 * L
            if int(cs["alive"][k]):
                g.append([((int(x) >> 15) & 1) * 2 + ((int(x) >> 7) & 1) for x in w])
        types[nm] = g
    rnd = random.Random(seed)

    def dis(ga, gb, same):
        tot = 0.0
        for _ in range(samples):
            u = rnd.randrange(len(ga))
            v = rnd.randrange(len(gb))
            while same and v == u and len(gb) > 1:
                v = rnd.randrange(len(gb))
            x, y = ga[u], gb[v]
            n = min(len(x), len(y))
            tot += sum(1 for a_, b_ in zip(x, y) if a_ == b_) / n if n else 0.0
        return 1.0 - tot / samples
    names = sorted(types)
    between = {(a_, b_): dis(types[a_], types[b_], False) for i, a_ in enumerate(names) for b_ in names[i + 1:]}
    between.update({(b_, a_): v for (a_, b_), v in list(between.items())})
    return between, {a_: dis(types[a_], types[a_], True) for a_ in names}


def pearson(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((a_ - mx) ** 2 for a_ in x))
    sy = math.sqrt(sum((b_ - my) ** 2 for b_ in y))
    return sum((a_ - mx) * (b_ - my) for a_, b_ in zip(x, y)) / (sx * sy) if sx > 0 and sy > 0 else None


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


def _fit_diag_text(what, fd):
    """The fit classifier's reports for H1b (review of #49, round 4, P2-3): probed (the exact gain above the
    allowance) and probe-certified fits, the largest probe decrease, unresolved-block energy and flat-cell SSE."""
    if not fd or not fd.get("fits"):
        return ""
    def g_(v):
        return "-" if v is None else f"{v:.3g}"
    return (f"; {what}: {fd['fits']}, probed {fd['probed']}, probe-certified {fd['probe_certified']}, max probe decrease "
            f"{g_(fd['max_probe_decrease'])}, max unresolved-block energy {g_(fd['max_unresolved_gain'])}, max flat-cell "
            f"SSE {g_(fd['max_flat_sse'])}, min resolved Hessian eigenvalue {g_(fd['min_hess_min'])}")

def primary_p(d):
    """The p-value of the frozen primary lack-of-fit test (infer.PRIMARY) from a row's fields."""
    return d.get("p_lof_flip") if infer.PRIMARY["test"] == "signflip" else d.get("p_lof")


def matrices(rows, meta=None, zmin=2.0, sims=9999, registry=None, kind=infer.DEFAULT_KIND, seed=5, dG=None,
             cores=None, windows_registered=None):
    """Complete blocks (every ordered pair + every sham, on common replicates): per condition,
    fraction and window, separately (pooling conditions can fake cycles).

    Per replicate r the paired matrix s~_r(i->j) = s_r(i->j) - s_r(j->j); the headline uses the
    replicate means. Inference is infer.py's (see there): the units are the (resident column,
    replicate) blocks of common random numbers, so the noise model keeps each unit's joint,
    heteroscedastic noise and assumes only that distinct units are independent.
      cyclic share         ||curl||^2 / ||A||^2 (raw), and noise-corrected
                           (||curl||^2 - tau_C) / (||A||^2 - tau_A), tau = the units' unbiased
                           noise-energy estimates; share_ci95 / dC_ci95 from the bootstrap
                           confidence ball for the edge noise
      lack of fit          F_lof = ||curl||^2 / tau_C; p_lof = studentized unit bootstrap
                           (`kind`, `sims` draws; tau re-estimated in every draw); p_lof_flip =
                           exact replicate sign-flip (>= flip_min_p = 1/2^(k-1))
      floor95, p_mc        descriptive: raw cyclic share of a pure ladder of the noise-corrected
                           strength plus bootstrap noise
      two-way gamma        s~(i->j) = mu + a_i + b_j + gamma_ij; gamma - gamma^T == curl (checked);
                           S_gamma = (gamma_ij + gamma_ji) / 2, the symmetric interaction; F_sym /
                           p_sym / p_sym_flip test it as a whole (df N(N-3)/2)
      triads               directed 3-cycles of sign(A), all and with every edge |z| >= zmin
      by_category          DESCRIPTIVE per-pair means of the full-matrix decomposition by pair
                           relation (exclusive classes + 'within-regime (all)'); zC = the
                           noise-corrected cyclic energy of each edge
      sub-blocks           the complete sub-blocks of one home regime / one snapshot time,
                           decomposed on their own (their own ladder and noise)
    -> (block rows, per-pair rows, blocks {(cond, frac, G): names, reps, units z, status},
        joint rows, sub-block rows)."""
    out, detail, blocks, sub = [], [], {}, []
    keys = sorted({(x["cond"], x["frac"], x["G"]) for x in rows})
    for cond, frac, G in keys:
        cell = {}
        missed = {(x["i"], x["j"], x["rep"]) for x in rows
                  if (x["cond"], x["frac"], x["G"]) == (cond, frac, G) and x["missed"]}
        for x in rows:
            if (x["cond"], x["frac"], x["G"]) == (cond, frac, G) and x["mode"] in ("invade", "sham") and x["s"] is not None:
                reps_ij = cell.setdefault((x["i"], x["j"]), {})
                if x["rep"] in reps_ij:   # load() excludes duplicate positions; never overwrite silently
                    raise ValueError(f"two results for {x['i']}->{x['j']} replicate {x['rep']} ({cond}, {frac}, {G})")
                reps_ij[x["rep"]] = x["s"]
        # The block and its replicates come from the REGISTERED design (the plan), never from which
        # runs happen to be finished: formal only when every registered cell of the registered
        # block, on the registered replicates, is present. Anything else is descriptive (the
        # largest complete sub-block of what is available, no floor / test decisions).
        status, names, reps = None, None, None
        reg = registry.get((cond, frac)) if registry is not None else None
        if reg:
            rkind = lambda a_, b_: (a_, b_, "sham" if a_ == b_ else "invade")   # noqa: E731
            rnames = _largest_complete({x for key in reg for x in key[:2]}, lambda a_, b_: rkind(a_, b_) in reg)
            if len(rnames) >= 3:
                R = sorted(set.intersection(*[reg[rkind(a_, b_)] for a_ in rnames for b_ in rnames]))
                miss = [(a_, b_, r) for a_ in rnames for b_ in rnames for r in R if r not in cell.get((a_, b_), {})]
                if not miss and len(R) >= 2:
                    status, names, reps = "formal", rnames, R
                else:
                    nwin = sum(1 for t in miss if t in missed)
                    status = (f"descriptive: {len(miss)} of {len(rnames) ** 2 * len(R)} registered cells "
                              f"of the {len(rnames)}-block missing"
                              + (f" ({nwin} with no checkpoint within the window tolerance)" if nwin else ""))
            else:
                status = "descriptive: no complete matrix registered"
        else:
            status = "descriptive: no plan given" if registry is None else "descriptive: nothing registered"
        if status == "formal" and cores and set(names) != {x for key in reg for x in key[:2]}:
            # a plan of separate cores registers no pooled matrix: its largest complete clique is one
            # core, which primary_blocks() analyses with the others (review round 3)
            status = "descriptive: the plan registers separate cores (see the primary blocks)"
        if status == "formal" and windows_registered is not None and G not in windows_registered:
            status = "descriptive: window not in the horizon registration"
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
        # per-edge replicate SEs: descriptive per-pair z (triads, matrix_pairs.csv)
        varA = {pq: sd([Ar[pq[0]][pq[1]] for Ar in A_r]) ** 2 / k for pq in pairs}
        varC = {pq: sd([Cr[pq[0]][pq[1]] for Cr in C_r]) ** 2 / k for pq in pairs}
        # inference (infer.py): units z[p][r][i] = s_r(i -> p) - s_r(p -> p), one common-random-
        # number unit per resident column p and replicate r; studentized unit bootstrap + exact
        # replicate sign-flip; no chi-square, no isotropic noise
        z = [[[cell[(names[i], names[p])][r] - cell[(names[p], names[p])][r] if i != p else 0.0
               for i in range(n)] for r in reps] for p in range(n)]
        blocks[(cond, frac, G)] = {"names": names, "reps": reps, "z": z, "status": status}
        inf = infer.infer([z], B=sims, seed=seed, kind=kind)
        assert abs(inf["T_A"] - sp["norm2"]) < 1e-9 * max(1.0, sp["norm2"])   # same A as hodge.split
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
        dec = {x: inf[x] for x in ("floor95", "p_mc", "p_lof", "p_lof_flip", "p_sym", "p_sym_flip", "p_lof_unstud")}
        if status != "formal":   # no decisions from a partial matrix
            dec = {x: None for x in dec}
        dec["p_primary"] = primary_p(dec)
        row = {"cond": cond, "frac": frac, "G": G, "status": status, "n": n, "k": k, "names": " ".join(names),
               "ratings": list(sp["r"]), "invader_effect": list(ea), "resident_effect": list(eb),
               "cyclic_share": sp["cyclic_share"], "noise_corrected": inf["share_nc"],
               "share_ci95_lo": inf["share_ci95"][0], "share_ci95_hi": inf["share_ci95"][1],
               "dC": inf["dC"], "dC_ci95_lo": inf["dC_ci95"][0], "dC_ci95_hi": inf["dC_ci95"][1],
               "C_nc": inf["C_nc"], "G_nc": inf["G_nc"],
               "F_lof": inf["F_C"], "df": df, "F_sym": inf["F_S"], "df_sym": n * (n - 3) // 2,
               **dec, "flip_min_p": inf["flip_min_p"], "boot": f"{kind} x {sims}",
               "rms_A": math.sqrt(sp["norm2"] / P),
               "noise_A": math.sqrt(inf["tau_A"] / P), "noise_curl": math.sqrt(inf["tau_C"] / df), "gamma_check": chk,
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
        # noise-corrected cyclic energy per edge (stats spec section 9): curl_e^2 - (Q V Q)_ee
        cn = unit_curl_noise(z)
        zC = {pq: sp["curl"][pq[0]][pq[1]] ** 2 - cn[e] for e, pq in enumerate(pairs)}
        if meta:
            # DESCRIPTIVE per-pair averages of the FULL-matrix decomposition by pair relation (a pair's
            # residual depends on the whole matrix; this is not a decomposition within each group)
            cats = {}
            for p, q in pairs:
                for c in relation_groups(meta.get(names[p]), meta.get(names[q])):
                    cats.setdefault(c, []).append((abs(A[p][q]), abs(sp["curl"][p][q]), zC[(p, q)], Sg[(p, q)]))
            row["by_category"] = "; ".join(
                f"{c}: n={len(v)} mean|A|={mean([x[0] for x in v]):.4f} mean|curl residual|={mean([x[1] for x in v]):.4f} "
                f"mean noise-corrected curl^2={mean([x[2] for x in v]):+.2e} mean S_gamma={mean([x[3] for x in v]):+.4f}"
                for c, v in sorted(cats.items()))
            # balanced sub-blocks decomposed ON THEIR OWN (complete graphs of the items sharing a home
            # regime, or a snapshot time): their own ladder, cycle and noise. Their p-values are
            # published only when the parent block is formal (then the sub-block is complete on the
            # registered replicates); a descriptive parent gives descriptive sub-blocks, no p
            # (review round 2: they used to copy p-values unconditionally)
            for keyname in ("regime", "time"):
                for val in sorted({str(meta.get(nm, {}).get(keyname)) for nm in names}):
                    idx = [i for i, nm in enumerate(names) if str(meta.get(nm, {}).get(keyname)) == val]
                    if len(idx) < 3 or len(idx) == n:
                        continue
                    zsub = subblock(z, idx)
                    si = infer.infer([zsub], B=sims, seed=seed, kind=kind)
                    formal = status == "formal"
                    if keyname == "regime":
                        blocks[(cond, frac, G)].setdefault("regime_blocks", {})[val] = {
                            "names": [names[i] for i in idx], "z": zsub}
                    sub.append({"cond": cond, "frac": frac, "G": G, "status": status, "group": f"{keyname}={val}",
                                "names": " ".join(names[i] for i in idx), "n": len(idx), "k": k,
                                "cyclic_share": si["share_raw"], "noise_corrected": si["share_nc"],
                                "share_ci95_lo": si["share_ci95"][0], "share_ci95_hi": si["share_ci95"][1],
                                "dC": si["dC"], "F_lof": si["F_C"], "df": (len(idx) - 1) * (len(idx) - 2) // 2,
                                "p_lof": si["p_lof"] if formal else None,
                                "p_lof_flip": si["p_lof_flip"] if formal else None,
                                "local_harmonic": "complete graph: all cyclic energy local"})
            regs = [meta.get(nm, {}).get("regime") for nm in names]
            if len(set(regs)) == 2:
                # the cross-regime pairs alone: a bipartite graph, no triangle, so its whole cyclic
                # residual is harmonic (cycles of length >= 4 through both regimes)
                sg = subgraph_summary(z, lambda p_, q_: regs[p_] != regs[q_])
            if len(set(regs)) == 2 and sg["q_cycle"] > 0:   # (a tree has no cycle space to report)
                sub.append({"cond": cond, "frac": frac, "G": G, "status": status,
                            "group": "cross-regime pairs (bipartite, incomplete)", "names": " ".join(names), "n": n,
                            "k": k, "cyclic_share": sg["cyclic_share"], "noise_corrected": sg["noise_corrected"],
                            "share_ci95_lo": None, "share_ci95_hi": None, "dC": sg["dC"], "F_lof": sg["F_lof"],
                            "df": sg["q_cycle"], "p_lof": None, "p_lof_flip": None,
                            "local_harmonic": f"{sg['edges']} edges, {sg['triangles']} triangles; noise-corrected "
                                              f"local {sg['local_nc']:.3g}, harmonic {sg['harmonic_nc']:.3g}"})
            if dG:
                xs = [(dG[(names[p], names[q])], zC[(p, q)]) for p, q in pairs if (names[p], names[q]) in dG]
                row["corr_zC_dG"] = pearson([x for x, _ in xs], [y for _, y in xs])
        out.append(row)
        for e, (p, q) in enumerate(pairs):
            detail.append({"cond": cond, "frac": frac, "G": G, "a": names[p], "b": names[q],
                           "category": category((meta or {}).get(names[p]), (meta or {}).get(names[q])),
                           "A": A[p][q], "se_A": math.sqrt(varA[(p, q)]), "grad": sp["grad"][p][q],
                           "curl": sp["curl"][p][q], "se_curl": math.sqrt(varC[(p, q)]),
                           "zC": zC[(p, q)], "dG": (dG or {}).get((names[p], names[q])),
                           "S_gamma": Sg[(p, q)], "se_S_gamma": math.sqrt(varSg[(p, q)])})
    joint = omnibus(blocks, registry, meta, sims, seed, kind)
    return out, detail, blocks, joint, sub


def omnibus(blocks, registry, meta, sims, seed, kind):
    """Omnibus tests over the assay conditions of one (fraction, window).

    The condition set is the REGISTERED one (every condition the plan registers at that
    fraction), never whichever blocks happen to be formal: if any registered condition's block is
    not formal, or the blocks differ in items or replicates, the row is descriptive and carries no
    p-value (review round 2: a registered four-condition omnibus could silently become a
    three-condition test). Without a plan there is no registered set, so nothing is formal.

    'pooled block x assays': the full block of every condition; a unit (p, r) shares its slot and
    donor seeds across conditions, so units are resampled / sign-flipped JOINTLY: F = sum T_C /
    sum tau_C. The stats spec's primary structure (one matrix per home regime x assay, regimes
    independent) is primary_blocks(), built explicitly per regime."""
    joint = []
    for frac, G in sorted({(f_, g_) for _, f_, g_ in blocks}):
        have = {c_: b for (c_, f_, g_), b in blocks.items() if (f_, g_) == (frac, G)}
        if registry is None:
            required, why = sorted(have), "descriptive: no plan given (no registered condition set)"
        else:
            required = sorted({c_ for (c_, f_) in registry if f_ == frac})
            why = None
        missing = [c_ for c_ in required if c_ not in have or have[c_]["status"] != "formal"]
        if why is None and missing:
            why = f"descriptive: registered condition(s) {' '.join(missing)} not formal"
        fb = [(c_, have[c_]) for c_ in required if c_ in have]
        if why is None and any(b["names"] != fb[0][1]["names"] or b["reps"] != fb[0][1]["reps"] for _, b in fb):
            why = "descriptive: the conditions' blocks differ in items or replicates"
        if len(fb) < 2:
            continue
        status = why or "formal"
        base = {"frac": frac, "G": G, "status": status, "conditions": " ".join(c_ for c_, _ in fb),
                "required": " ".join(required), "boot": f"{kind} x {sims}"}
        if why is not None:   # report the configuration, decide nothing
            joint.append({**base, "structure": "pooled block x assays", "n": len(fb[0][1]["names"]),
                          "k": len(fb[0][1]["reps"])})
            continue
        inf = infer.infer([b["z"] for _, b in fb], B=sims, seed=seed, kind=kind)
        joint.append({**base, "structure": "pooled block x assays", "n": inf["N"], "k": inf["k"],
                      "F_lof": inf["F_C"], "p_lof": inf["p_lof"], "p_lof_flip": inf["p_lof_flip"],
                      "F_sym": inf["F_S"], "p_sym": inf["p_sym"], "p_sym_flip": inf["p_sym_flip"],
                      "flip_min_p": inf["flip_min_p"]})
    # (the home-regime x assay omnibus is primary_blocks(): explicit per-regime matrices, review
    # round 3, no longer sub-blocks of whichever pooled clique was complete)
    for j_ in joint:
        j_["p_primary"] = primary_p(j_)
    return joint


def cores_from_plan(plan):
    """{core: sorted items} from cells that carry a 'core' (plan.py "cores"), else None.
    plan.py tags a cell with its RESIDENT's core, and every core member is the resident of its own
    core's cells (its sham at least), so the registered membership is the residents. A secondary
    cross-home cell x1 -> y1 (core y) must not add its invader x1 to core y (review round 4: it did,
    and then the primary analysis demanded cross-home cells and lost formal eligibility)."""
    cores = {}
    for c in (plan or {}).values():
        if c.get("core"):
            cores.setdefault(c["core"], set()).add(c["resident_name"])
    return {k: sorted(v) for k, v in cores.items()} or None


def primary_registration(registry, groups, cores, strict=None):
    """The registered primary structure, frozen from the registration BEFORE any result is read
    (review round 4): for every registered (condition, fraction) and every group with a registered
    item there, the registered block - a core's items (which must be registered as a complete
    matrix), or for a legacy plan the largest complete registered clique within the home regime -
    and its common registered replicates; 'why' says why a registration defines no complete
    primary matrix (then that block can never be formal). -> (spec {(cond, frac): {group: {names,
    reps, why}}}, required {frac: sorted groups}): a group registered at a fraction is required
    in every registered condition there, whatever has finished.
    strict (the confirmation protocol, analyze.py --gate; review round 5 item 2): the frozen panel
    only - registered cores (no legacy clique), exactly strict['groups'] cores of strict['N'] items,
    the registered assays at the registered fraction, and EVERY primary cell registering exactly
    replicates 0..k-1: no intersection of replicate sets, no reduction (a 0-8 cell among 0-9 cells
    makes the block non-formal instead of a nine-replicate block)."""
    rk = lambda a_, b_: (a_, b_, "sham" if a_ == b_ else "invade")   # noqa: E731
    spec, required = {}, {}
    for (cond, frac), reg in sorted(registry.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        for gname in sorted(groups):
            items = sorted(groups[gname])
            inreg = [x for x in items if any(x in key[:2] for key in reg)]
            if not inreg:
                continue
            why, R = None, []
            if cores:
                names = items
                if any(rk(a_, b_) not in reg for a_ in names for b_ in names):
                    why = f"core {gname} is not registered as a complete matrix"
            else:
                names = _largest_complete(inreg, lambda a_, b_: rk(a_, b_) in reg)
            if strict is not None and why is None:
                k_ = strict["k"]
                if not cores:
                    why = "confirmation protocol: no registered cores (a legacy clique is a reduction)"
                elif len(groups) != strict["groups"] or len(names) != strict["N"]:
                    why = (f"confirmation protocol: {len(groups)} core(s) of {len(names)} items, the registration "
                           f"is {strict['groups']} x {strict['N']}")
                elif cond not in strict["assays"] or frac != strict["fraction"]:
                    why = f"confirmation protocol: {cond} / {frac} is not a registered assay / fraction"
                else:
                    off = [(a_, b_) for a_ in names for b_ in names if reg[rk(a_, b_)] != set(range(k_))]
                    if off:
                        a_, b_ = off[0]
                        why = (f"confirmation protocol: cell {a_} -> {b_} registers replicates "
                               f"{sorted(reg[rk(a_, b_)])[:3]}...({len(reg[rk(a_, b_)])}), not exactly 0..{k_ - 1} "
                               f"({len(off)} such cell(s); no intersection or reduction)")
                    else:
                        R = list(range(k_))
            if why is None and not R:
                if len(names) < 3:
                    why = "fewer than 3 registered items"
                else:
                    R = sorted(set.intersection(*[reg[rk(a_, b_)] for a_ in names for b_ in names]))
                    if len(R) < 2:
                        why = "fewer than 2 common registered replicates"
            spec.setdefault((cond, frac), {})[gname] = {"names": names, "reps": R, "why": why}
            required.setdefault(frac, set()).add(gname)
    if strict is not None:
        # review of #49, finding 1: the required primary design is the confirmation specification's group x assay
        # product, whatever the plan registers - an absent assay (or group) is a missing primary block, never a
        # smaller formal omnibus
        fr = strict["fraction"]
        for g_ in sorted(groups):
            required.setdefault(fr, set()).add(g_)
            for c_ in strict["assays"]:
                spec.setdefault((c_, fr), {}).setdefault(g_, {"names": [], "reps": [], "why":
                                                            f"confirmation protocol: assay {c_} is not registered "
                                                            f"for group {g_}"})
    return spec, {f: sorted(v) for f, v in required.items()}


def verify_gate(path, require_formal=True, receipt=None):
    """The calibration gate record the headline claim needs (review round 5 item 1; review of #49, finding 2):
    path = the gate's output directory. gate.verify_record checks the complete chain - a formal 'pass'
    decision, the manifest by hash and byte-identical to the one this code regenerates (the frozen protocol,
    the schedule and all six tool hashes), run.json and cell_laws.json bound to it, every scheduled task
    record present, valid and bound to this run, and the decision re-aggregated with the acceptance rule
    applied afresh; and the run's receipt equal to `receipt`, the hash recorded outside the directory (the
    approval record; review of #49, round 2). -> (summary dict, problems); any problem (missing evidence or
    receipt included) withholds the claim."""
    import gate
    return gate.verify_record(path, require_formal, receipt)


def primary_blocks(rows, meta, registry, cores, sims, seed=5, kind=infer.DEFAULT_KIND, windows_registered=None,
                   bsims=0, confirm=None):
    """The stats spec's primary matrices, built EXPLICITLY per home regime and condition (review
    round 3: they used to be sub-blocks of the one largest complete pooled clique, so two disjoint
    complete regime cores kept only one regime).

    Groups: the plan's registered cores (plan.py "cores") when it has them; for a legacy plan, the
    home regimes of --meta, each reduced to its largest complete registered clique WITHIN the
    regime (eligibility never depends on cross-home cells). A registered core must be registered
    as a complete matrix; a block is formal when every registered cell of it is finished on the
    registered replicates and its window is registered (fixed steps: the horizon file).

    The required group x condition set and each block's items and replicates are frozen from the
    registration (primary_registration), never from which cells have finished (review round 4).
    Per (fraction, window) the primary omnibus needs every registered condition x every group
    formal, with the same items and replicates across a group's conditions:
      H1   the raw grouped omnibus (infer.infer_groups: regimes independent, assays joint);
      H1b  the frozen co-primary, bounded.residual_omnibus: four separate logistic mean fits, the
           grouped sign-flip of the projected residual replicate vectors (and, with bsims > 0, the
           joint refitting bootstrap beside it);
      both_rejected  H1 and H1b both p <= bounded.ALPHA_FAMILY = a = 0.05/12 (the fixed conjunction at
           the twelve-slot allocation, two slots active; not full Holm): descriptive;
      claim_beyond_bounded  the preregistered headline ("cardinal circulation beyond the fitted
           logistic endpoint-mean family"): both_rejected, and ONLY with confirm (analyze.py --gate:
           the strict confirmation registration, a verified passed calibration gate record) and
           ONLY at the confirmatory horizon T (2T and other windows: None, descriptive); if a
           logistic fit did not converge (or a projection failed), H1b and the claim are INVALID
           (claim None, claim_status and h1b_diagnostics say why), never a rejection.
    confirm: {"strict": registration spec, "T": steps, "gate": summary, "gate_problems": [...]}.
    A group with k > 16 replicates is exported only (the enumeration of sign patterns is limited
    to 16; an error bank is resampled by calibrate.py, not tested). -> (rows, blocks, joint rows)."""
    if cores:
        groups, source = {g: list(v) for g, v in cores.items()}, "registered cores"
    elif meta:
        groups = {}
        for nm, m_ in meta.items():
            groups.setdefault(str(m_.get("regime")), []).append(nm)
        source = "legacy plan: the largest complete registered clique within each home regime"
    else:
        return [], {}, []
    # the required groups and their blocks come from the registration alone (review round 4: they
    # used to come from whichever blocks had results, so a legacy regime with no finished cell
    # silently left a formal two-block omnibus)
    spec, required = (primary_registration(registry, groups, cores, (confirm or {}).get("strict"))
                      if registry is not None else ({}, {}))
    prows, pblocks = [], {}
    keys = {(x["cond"], x["frac"], x["G"]) for x in rows}
    seenG = {}
    for _, f_, g_ in keys:
        seenG.setdefault(f_, set()).add(g_)
    keys |= {(c_, f_, g_) for (c_, f_) in spec for g_ in seenG.get(f_, ())}   # registered blocks without results too
    for cond, frac, G in sorted(keys, key=lambda t: (str(t[0]), t[1], t[2])):
        cell = {}
        for x in rows:
            if (x["cond"], x["frac"], x["G"]) == (cond, frac, G) and x["mode"] in ("invade", "sham") and x["s"] is not None:
                cell.setdefault((x["i"], x["j"]), {})[x["rep"]] = x
        reg = registry.get((cond, frac)) if registry is not None else None
        for gname in sorted(groups):
            items = sorted(groups[gname])
            status, names, reps = None, [], []
            sp = spec.get((cond, frac), {}).get(gname)
            if not reg:
                status = ("descriptive: no plan given" if registry is None else
                          f"descriptive: {sp['why']}" if sp and sp.get("why") else "descriptive: nothing registered")
            elif sp is None:
                if gname not in required.get(frac, ()):
                    continue   # not a primary group at this fraction
                status = f"descriptive: group {gname} has no registered item in {cond}"
            elif sp["why"]:
                status = f"descriptive: {sp['why']}"
            else:
                names, R = sp["names"], sp["reps"]
                miss = [(a_, b_, r) for a_ in names for b_ in names for r in R if r not in cell.get((a_, b_), {})]
                if not miss:
                    status, reps = "formal", R
                else:
                    status = f"descriptive: {len(miss)} of {len(names) ** 2 * len(R)} registered cells missing"
            if status == "formal" and windows_registered is not None and G not in windows_registered:
                status = "descriptive: window not in the horizon registration"
            if status != "formal":
                avail = [x for x in items if any(x in ij for ij in cell)]
                names = _largest_complete(avail, lambda a_, b_: (a_, b_) in cell)
                reps = sorted(set.intersection(*[set(cell[(a_, b_)]) for a_ in names for b_ in names])) \
                    if len(names) >= 3 else []
            base = {"cond": cond, "frac": frac, "G": G, "group": gname, "source": source, "status": status,
                    "n": len(names), "k": len(reps), "names": " ".join(names)}
            if len(names) < 3 or len(reps) < 2:
                prows.append(base)
                continue
            n = len(names)
            z = [[[cell[(names[i], names[p])][r]["s"] - cell[(names[p], names[p])][r]["s"] if i != p else 0.0
                   for i in range(n)] for r in reps] for p in range(n)]
            zq = [[[cell[(names[i], names[p])][r]["s"] + cell[(names[i], names[p])][r]["f0"] if i != p else 0.0
                    for i in range(n)] for r in reps] for p in range(n)]
            formal = status == "formal"
            row = dict(base)
            fitres = None
            if len(reps) <= 16:
                inf = infer.infer([z], B=sims, seed=seed, kind=kind)
                row.update({"cyclic_share": inf["share_raw"], "noise_corrected": inf["share_nc"],
                            "share_ci95_lo": inf["share_ci95"][0], "share_ci95_hi": inf["share_ci95"][1],
                            "dC": inf["dC"], "F_lof": inf["F_C"],
                            "p_lof": inf["p_lof"] if formal else None, "p_lof_flip": inf["p_lof_flip"] if formal else None})
                row["p_primary"] = primary_p(row)
                if n * (n - 1) - bounded.Model(bounded.CO_PRIMARY_MODEL, n).P >= (n - 1) * (n - 2) // 2:
                    fitres = bounded.fit_matrix(zq)
                    try:   # one invalid path (prereg gate): a failed projection is unavailable, not an abort
                        vecs = bounded.residual_replicate_vectors(zq, fitres=fitres)[0]
                        perr = None
                    except bounded.Unavailable as e:
                        vecs, perr = None, str(e)
                    R_C = bounded.energies(bounded._sub(bounded._means(zq), fitres["F"]))[1]
                    ok = bool(fitres["converged"]) and perr is None   # an unconverged fit decides nothing (review round 4)
                    row.update({"R_C_logistic": R_C, "F_res": infer._ratio(R_C, infer.block_stats(zq)["tauC"]),
                                "fit_converged": bool(fitres["converged"]),
                                "p_res_flip": infer.flip_p_vectors([vecs]) if formal and ok else None})
                    if not ok:
                        row["note"] = ("logistic fit not converged" if perr is None else perr) + ": H1b descriptive"
            else:
                row["note"] = "k > 16: exported (blocks.json), not tested"
            pblocks[(cond, frac, G, gname)] = {"cond": cond, "frac": frac, "G": G, "group": gname, "names": names,
                                               "reps": reps, "z": z, "zq": zq, "status": status, "fit": fitres}
            prows.append(row)
    pjoint = []
    for frac, G in sorted({(k_[1], k_[2]) for k_ in keys}):
        if registry is None:
            conds = sorted({k_[0] for k_ in pblocks if (k_[1], k_[2]) == (frac, G)})
            gnames = sorted({k_[3] for k_ in pblocks if (k_[1], k_[2]) == (frac, G)} | (set(cores) if cores else set()))
            why = "descriptive: no plan given (no registered condition set)"
        else:
            conds = sorted({c_ for (c_, f_) in registry if f_ == frac})
            gnames = required.get(frac, [])   # frozen from the registration (review round 4)
            why = None
            strict = (confirm or {}).get("strict")
            if strict is not None:   # review of #49, finding 1: the specification's product, not the plan's
                conds = sorted(set(conds) | (set(strict["assays"]) if frac == strict["fraction"] else set()))
                if frac != strict["fraction"]:
                    why = f"descriptive: fraction {frac} is not the confirmation fraction {strict['fraction']}"
                elif len(gnames) != strict["groups"]:
                    why = f"descriptive: {len(gnames)} group(s), the confirmation registers {strict['groups']}"
        if not gnames or not conds:
            continue
        miss = [f"{c_}/{g_}" for c_ in conds for g_ in gnames
                if (c_, frac, G, g_) not in pblocks or pblocks[(c_, frac, G, g_)]["status"] != "formal"]
        if why is None and miss:
            why = f"descriptive: primary block(s) {' '.join(miss)} not formal"
        if why is None and len(gnames) * len(conds) < 2:
            why = "descriptive: fewer than two primary blocks"
        if why is None:
            for g_ in gnames:
                bs = [pblocks[(c_, frac, G, g_)] for c_ in conds]
                if any(b["names"] != bs[0]["names"] or b["reps"] != bs[0]["reps"] for b in bs):
                    why = f"descriptive: group {g_}'s conditions differ in items or replicates"
                elif len(bs[0]["reps"]) > 16:
                    why = "export only: k > 16 (an error bank; calibrate.py resamples it)"
        row = {"frac": frac, "G": G, "structure": "primary: home-regime x assay matrices (regimes independent)",
               "groups": " | ".join(f"{g_}: {' '.join(pblocks[(conds[0], frac, G, g_)]['names']) if (conds and (conds[0], frac, G, g_) in pblocks) else '-'}" for g_ in gnames),
               "conditions": " ".join(conds), "required": " ".join(f"{c_}/{g_}" for c_ in conds for g_ in gnames),
               "status": why or "formal", "boot": f"{kind} x {sims}"}
        if why is None:
            gz = [[pblocks[(c_, frac, G, g_)]["z"] for c_ in conds] for g_ in gnames]
            ig = infer.infer_groups(gz, B=sims, seed=seed, kind=kind)
            gq = [[pblocks[(c_, frac, G, g_)]["zq"] for c_ in conds] for g_ in gnames]
            fits = [[pblocks[(c_, frac, G, g_)]["fit"] for c_ in conds] for g_ in gnames]
            ro = bounded.residual_omnibus(gq, B=bsims, seed=seed, kind=kind,
                                          fits=fits if all(f_ for fs in fits for f_ in fs) else None)
            row.update({"n": " ".join(str(x) for x in ig["N"]), "k": ig["k"][0], "F_lof": ig["F_C"],
                        "p_lof": ig["p_lof"], "p_lof_flip": ig["p_lof_flip"], "flip_min_p": ig["flip_min_p"],
                        "F_sym": ig["F_S"], "p_sym": ig["p_sym"], "p_sym_flip": ig["p_sym_flip"],
                        "F_res_joint": ro["F_res_joint"], "p_res_flip": ro["p_flip"], "p_res_boot": ro["p_boot"],
                        "h1b_valid": ro["valid"],
                        "h1b_diagnostics": (f"logistic fits converged {ro['fits_converged']}/{ro['conditions']}; "
                                            f"bootstrap draws with an unconverged refit {ro['boot_not_converged']}/{bsims}"
                                            + _fit_diag_text("fits", ro.get("fit_diag"))
                                            + _fit_diag_text("bootstrap refits", ro.get("boot_fit_diag"))
                                            + (f"; INVALID: {ro['invalid']} (descriptive p "
                                               + (f"{ro['p_flip_unconverged']:.5g}" if ro["p_flip_unconverged"] is not None
                                                  else "unavailable") + ")"
                                               if not ro["valid"] else ""))})
            row["p_primary"] = primary_p(row)
            row["claim_beyond_bounded"] = None
            if ro["p_flip"] is None or row["p_primary"] is None:
                # review round 4: an unconverged fit gives no decision, never a formal rejection
                row["both_rejected"] = None
                row["claim_status"] = f"invalid: {ro['invalid'] or 'H1 has no p-value'}"
            else:
                row["both_rejected"] = (row["p_primary"] <= bounded.ALPHA_FAMILY and ro["p_flip"] <= bounded.ALPHA_FAMILY)
                # review round 5 item 1: the headline needs the confirmation protocol, a verified passed
                # gate and the confirmatory horizon T; anything else is descriptive
                if confirm is None:
                    row["claim_status"] = "descriptive: no calibration gate record (the headline needs analyze.py --gate)"
                elif float(G) != float(confirm["T"]):
                    row["claim_status"] = f"descriptive: window {G:g} is not the confirmatory horizon T = {confirm['T']}"
                elif confirm.get("plan_problems"):
                    row["claim_status"] = ("descriptive: the plan is not the registered confirmation design: "
                                           + "; ".join(confirm["plan_problems"][:3]))
                elif confirm.get("gate_problems"):
                    row["claim_status"] = "descriptive: no passed gate: " + "; ".join(confirm["gate_problems"])
                else:
                    row["claim_beyond_bounded"] = row["both_rejected"]
                    row["claim_status"] = "formal (confirmation protocol, gate passed, T)"
        elif registry is not None and confirm is not None:
            row["claim_status"] = f"unavailable: {why}"
        pjoint.append(row)
    return prows, pblocks, pjoint


def _key_rows(rows, key):
    return [x for x in rows if (x["cond"], x["frac"], x["G"]) == key]


def _units(rows, names, reps, endpoint=False):
    """Units z[p][r][i] of the block names x reps from rows (one key): the sham-paired score
    s(i -> p) - s(p -> p), or with endpoint=True the invade cells' endpoint q = s + f0 (no sham:
    a column constant never reaches the cyclic part; the bounded models are fitted to q)."""
    v = {}
    for x in rows:
        if x["mode"] in ("invade", "sham") and x["s"] is not None:
            v[(x["i"], x["j"], x["rep"])] = x["s"] + (x["f0"] if endpoint else 0.0)
    n = len(names)

    def at(i, p, r):
        if endpoint:
            return v[(names[i], names[p], r)]
        return v[(names[i], names[p], r)] - v[(names[p], names[p], r)]
    return [[[at(i, p, r) if i != p else 0.0 for i in range(n)] for r in reps] for p in range(n)]


def scale_sensitivity(rows, blocks, scales, models, sims, bsims, seed=5, kind=infer.DEFAULT_KIND):
    """Bounded-scale sensitivity of every block (bounded.py): the same split and tests on
    transformed endpoints (scale rows; 'raw' reproduces matrix.csv), and the lack of fit of
    bounded node-additive (transitive, non-additive) models for the expected endpoint, with the
    cyclic energy left after them (model rows). Decisions only for formal blocks.
    -> (scale rows, model rows)."""
    srows, mrows = [], []
    for key, b in sorted(blocks.items(), key=lambda kv: str(kv[0])):
        cond, frac, G = key
        names, reps, status = b["names"], b["reps"], b["status"]
        formal = status == "formal"
        kr = [x for x in _key_rows(rows, key) if x["i"] in names and x["j"] in names and x["rep"] in reps]
        st_raw = infer.block_stats(b["z"])
        base = {"cond": cond, "frac": frac, "G": G, "status": status, "n": len(names), "k": len(reps)}
        for spec in ["raw"] + list(scales):
            if spec == "raw":
                z, nclip = b["z"], 0
            else:
                tr, nclip = bounded.transform_rows(kr, spec)
                z = _units(tr, names, reps)
            inf = infer.infer([z], B=sims, seed=seed, kind=kind)
            n = len(names)
            A = infer.antisym(infer.column_means(z))
            Am = [[None] * n for _ in range(n)]
            e = 0
            for p in range(n):
                for q in range(p + 1, n):
                    Am[p][q], Am[q][p] = A[e], -A[e]
                    e += 1
            tri = hodge.circular_triads(Am)
            row = {**base, "scale": spec, "clipped": nclip, "endpoints": len(kr),
                   "cyclic_share": inf["share_raw"], "noise_corrected": inf["share_nc"],
                   "share_ci95_lo": inf["share_ci95"][0], "share_ci95_hi": inf["share_ci95"][1],
                   "dC": inf["dC"], "dC_ci95_lo": inf["dC_ci95"][0], "dC_ci95_hi": inf["dC_ci95"][1],
                   "F_lof": inf["F_C"], "F_sym": inf["F_S"], "triads_cyclic": tri["cyclic"], "triads": tri["triads"]}
            for x in ("p_lof", "p_lof_flip", "p_sym", "p_sym_flip"):
                row[x] = inf[x] if formal else None
            row["p_primary"] = primary_p(row)
            srows.append(row)
        zq = _units(kr, names, reps, endpoint=True)
        b["zq"] = zq   # (blocks.json: calibrate.py's bounded worlds need the endpoint units)
        share_raw_nc = infer._ratio(st_raw["TC"] - st_raw["tauC"], st_raw["TA"] - st_raw["tauA"])
        P = len(names) * (len(names) - 1) // 2
        nn = len(names)
        for mname in models:
            if nn * (nn - 1) - bounded.Model(mname, nn).P < (nn - 1) * (nn - 2) // 2:
                continue   # fewer residual dimensions than cycle dimensions: the model cannot be tested here
            t = bounded.model_test(zq, mname, B=bsims, seed=seed, kind=kind, TA_pair=st_raw["TA"], tauA_pair=st_raw["tauA"])
            mrows.append({**base, "model": mname, "B": bsims, "converged": t["converged"],
                          "boot_not_converged": t["boot_not_converged"], "sse": t["sse"],
                          "params": json.dumps(t["params"], sort_keys=True),
                          "T_C": t["T_C"], "tau_C": t["tau_C"], "C_fit": t["C_fit"], "R_C": t["R_C"],
                          "R_C_null": t["R_C_null"], "R_C_nc": t["R_C_nc"], "share_nc_raw": share_raw_nc,
                          "share_res_nc": t["share_res_nc"], "survival": t["survival"],
                          "dC_raw": math.sqrt(max(0.0, st_raw["TC"] - st_raw["tauC"]) / P), "dC_res": t["dC_res"],
                          "F_res": t["F_res"], "p_res": t["p_res"] if formal else None,
                          "T_S": t["T_S"], "tau_S": t["tau_S"], "R_S": t["R_S"], "R_S_nc": t["R_S_nc"],
                          "F_res_S": t["F_res_S"], "p_res_S": t["p_res_S"] if formal else None})
    return srows, mrows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--windows", default=None,
                    help="comma list: generations of the resident's clock (--clock gens, default 2.5,5,10) or "
                         "steps (--clock steps; default T,2T from --horizon)")
    ap.add_argument("--sims", type=int, default=9999, help="bootstrap draws per test (default 9999)")
    ap.add_argument("--kind", default=infer.DEFAULT_KIND, choices=["wild", "residual"],
                    help=f"unit bootstrap: random-sign (wild) or resampled residual units (default {infer.DEFAULT_KIND}, "
                         "the one calibrate.py validated)")
    ap.add_argument("--no-power", action="store_true",
                    help="(kept for old command lines; null calibration and planted-cycle power are calibrate.py's, "
                         "through the same tests)")
    ap.add_argument("--max-window-error", type=float, default=0.10,
                    help="largest relative distance between a requested window and the checkpoint read for it "
                         "(default 0.10); a run with no checkpoint that close has no score for that window")
    ap.add_argument("--gen-def", default="pop", choices=["pop", "n0"],
                    help="window clock: turnover of the mean population (default) or of the start population")
    ap.add_argument("--clock", default="gens", choices=["gens", "steps"],
                    help="'gens' (default): a window is generations of the RESIDENT's clock; 'steps': a window is one "
                         "common fixed number of steps for every run (the stats spec's primary horizon), realized "
                         "turnover reported")
    ap.add_argument("--horizon", help="horizon.json (horizon.py: T calibrated on independent cells); with --clock steps "
                                      "and no --windows the windows are T and 2T; recorded in inputs.json")
    ap.add_argument("--scales", default=",".join(bounded.DEFAULT_SCALES),
                    help="endpoint transforms for the bounded-scale sensitivity (bounded.py), comma list; '' = none")
    ap.add_argument("--bounded", default=",".join(bounded.MODELS),
                    help="bounded node-additive models whose residual cyclic energy is reported; '' = none")
    ap.add_argument("--bounded-sims", type=int, default=1999,
                    help="parametric-residual bootstrap draws (each refits the model) for the bounded models")
    ap.add_argument("--meta", help="JSON {snapshot: {run, regime, family, time}} for pair relations / regimes")
    ap.add_argument("--no-genetic", action="store_true",
                    help="skip the sensor-relevant genetic dissimilarity of the snapshots (needs --meta and --plan)")
    ap.add_argument("--plan", help="the registered plan (JSONL): every cell is validated against it, and only a "
                                   "complete registered matrix gets formal decisions")
    ap.add_argument("--gate", help="the confirmation protocol: the calibration gate's output directory (gate.py run; "
                                   "its decision.json + manifest.json). The primary registration must be the frozen "
                                   "panel (2 cores x 12 items, off / predA4 at 0.05, replicates exactly 0..9 in every "
                                   "cell) and claim_beyond_bounded is reported only with a verified PASSED formal gate, "
                                   "at T = 13,500 only. Without it the claim column is None (both_rejected is "
                                   "descriptive)")
    ap.add_argument("--gate-receipt", help="the gate run's receipt (gate.py run prints it; the hash recorded in the "
                                           "approval record right after the run): required for the headline claim")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    horizon = json.load(open(a.horizon)) if a.horizon else None
    if a.windows is None:
        if a.clock == "gens":
            a.windows = "2.5,5,10"
        elif horizon:
            a.windows = f"{horizon['T']},{horizon['T2']}"
        else:
            ap.error("--clock steps needs --windows (in steps) or --horizon")
    windows = [float(x) for x in a.windows.split(",")]
    plan = None
    if a.plan:
        plan = {}
        for ln in open(a.plan):
            if ln.strip():
                c = json.loads(ln)
                plan[c["id"]] = c
    recs, problems, unregistered, snapshots = load(a.root, plan)
    registry = registry_from_plan(plan) if plan is not None else None
    # cells.csv: exactly which results (by content hash) every table below was computed from,
    # including the generation clock and the speed / cost fits; inputs.json carries its hash
    crows = [{"root": os.path.abspath(r["root"]), "id": r["id"], "done_sha256": r["hashes"]["done.json"],
              "score_sha256": r["hashes"]["score.json"], "manifest_sha256": r["hashes"]["arena.manifest.json"],
              "run_csv_sha256": r["hashes"]["run.csv"],
              "sources": " ".join(f"{nm}={h}" for nm, h in sorted(r["sources"].items()))} for r in recs]
    write_csv(os.path.join(a.out, "cells.csv"), crows,
              ["root", "id", "done_sha256", "score_sha256", "manifest_sha256", "run_csv_sha256", "sources"])
    here = os.path.dirname(os.path.abspath(__file__))
    prov = {
        "schema": "finfolk.invasion.analysis/1",
        "roots": [os.path.abspath(r) for r in a.root],
        "plan": {"path": os.path.abspath(a.plan), "sha256": sha256(a.plan), "cells": len(plan)} if plan is not None else None,
        "meta": {"path": os.path.abspath(a.meta), "sha256": sha256(a.meta)} if a.meta else None,
        "analysis_code": {f: sha256(os.path.join(here, f)) for f in ("analyze.py", "hodge.py", "infer.py", "bounded.py")},
        "primary": infer.PRIMARY,
        "clock": a.clock,
        "horizon": ({"path": os.path.abspath(a.horizon), "sha256": sha256(a.horizon), **horizon} if horizon else None),
        "binaries": sorted({r["binary_sha256"] for r in recs}),
        "tools": sorted({json.dumps(r["tools_sha256"], sort_keys=True) for r in recs if r["tools_sha256"]}),
        "cells_without_tool_hashes": sum(1 for r in recs if not r["tools_sha256"]),
        "cells_csv": {"path": os.path.abspath(os.path.join(a.out, "cells.csv")),
                      "sha256": sha256(os.path.join(a.out, "cells.csv")), "cells": len(recs)},
        "snapshots": snapshots,
        "args": vars(a),
        "finished": len(recs),
        "identity_problems": problems,
    }
    if plan is not None:
        have = {r["id"] for r in recs}
        # registered cells with no usable result (unfinished, or excluded by an identity problem)
        prov["registered_missing"] = sorted(set(plan) - have)
        # finished but not registered: listed, and excluded from EVERY table
        prov["unregistered_finished"] = sorted(unregistered)
    prov["complete"] = plan is not None and not prov["registered_missing"] and not problems
    ident = {"plan_sha256": prov["plan"]["sha256"] if prov["plan"] else "",
             "analysis_sha256": prov["analysis_code"]["analyze.py"]}
    gens = gen_length(recs, a.gen_def)
    rows = run_rows(recs, gens, windows, a.max_window_error, a.clock)
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
              f"({prov['plan']['cells']} registered cells, {len(prov['registered_missing'])} missing or excluded, "
              f"{len(prov['unregistered_finished'])} finished but unregistered: excluded from every table)"
              if plan is not None else "NONE (descriptive only)") +
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
              ["id", "j", "i", "mode", "frac", "cond", "rep", "n0", "m", "f0", "G", "W", "steps_at", "rel_err", "missed",
               "last_steps", "s", "n", "births", "gens", "invader_lost", "extinct"])
    write_csv(os.path.join(a.out, "groups.csv"), grp,
              ["cond", "frac", "G", "j", "i", "mode", "k", "mean", "sd", "se", "lost", "extinct", "W", "n_end",
               "missed"])
    unit = "gens of the resident's clock" if a.clock == "gens" else "steps, common to every run"
    md.append(f"\n## Window reads (requested W vs the checkpoint read; tolerance {a.max_window_error:.0%} of W)\n")
    if a.clock == "steps":
        md.append("Common fixed-step horizon (stats spec section 1): every run is read at the same step count. "
                  + (f"T = {horizon['T']} steps was calibrated on independent cells ({horizon.get('calibration', '')}); "
                     f"2T = {horizon['T2']} is the long-horizon sensitivity. " if horizon else "")
                  + "Realized turnover g = births / start population at the window.\n")
    md.append(f"| window ({unit}) | runs | requested W (steps) | max abs relative error | mean | missed (no checkpoint within tolerance) | realized turnover g, shams: mean (min-max) | all runs: mean (min-max) |\n|---|---|---|---|---|---|---|---|")
    for G in windows:
        xs = [x for x in rows if x["G"] == G]
        if not xs:
            continue
        errs = [abs(x["rel_err"]) for x in xs if x["rel_err"] is not None]
        gs = [x["gens"] for x in xs if x["gens"] is not None and x["mode"] == "sham"]
        ga = [x["gens"] for x in xs if x["gens"] is not None]
        md.append(f"| {G:g} | {len(xs)} | {min(x['W'] for x in xs):.0f}-{max(x['W'] for x in xs):.0f} | "
                  f"{fmt(max(errs) if errs else None, 3)} | {fmt(mean(errs), 3)} | {sum(1 for x in xs if x['missed'])} | "
                  + (f"{mean(gs):.2f} ({min(gs):.2f}-{max(gs):.2f})" if gs else "") + " | "
                  + (f"{mean(ga):.2f} ({min(ga):.2f}-{max(ga):.2f})" if ga else "") + " |")
    nex = sum(1 for x in rows if x["extinct"])
    md.append(f"\nExtinct reads: {nex} (scored by the preregistered unconditional endpoint q = 0, s = -f0; never dropped).\n")
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
    md.append("s~ = the change in the invaders' founder pedigree contribution minus the self-invasion baseline "
              "(a pedigree index, not genomic ancestry). S > 0 does not mean both directions gain; 'directions' "
              "classifies the two directed s~ by their own one-sided 97.5% Student-t bounds (paired t with k - 1 "
              f"df: |t| >= t_.975(k-1), e.g. {direction_cutoff(6):.3f} at k = 6, {direction_cutoff(10):.3f} at "
              "k = 10). Both bounds hold jointly at >= 95% if the paired differences are Gaussian (approximate "
              "otherwise); not adjusted across pairs. 'reciprocal gain' is excess pedigree introgression both "
              "ways, not coexistence.\n")
    md.append("| condition | fraction | window | a | b | relation | s~(a->b) (z) | s~(b->a) (z) | A | z_A | S | z_S | directions |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for p in pt:
        md.append(f"| {p['cond']} | {p['frac']} | {p['G']} | {p['a']} | {p['b']} | {p['category']} | {p['st_a_into_b']:+.4f} ({fmt(p['z_a_into_b'], 1)}) | "
                  f"{p['st_b_into_a']:+.4f} ({fmt(p['z_b_into_a'], 1)}) | "
                  f"{p['A_ab']:+.4f} | {fmt(p['z_A'], 1)} | {p['S']:+.4f} | {fmt(p['z_S'], 1)} | {p['reciprocal']} |")
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
               "z_A", "z_S", "z_a_into_b", "z_b_into_a", "k_a_into_b", "k_b_into_a", "cut_a_into_b", "cut_b_into_a",
               "reciprocal", "plan_sha256", "analysis_sha256"])
    dG = None
    if meta and plan is not None and not a.no_genetic:
        paths = {}
        for c in plan.values():
            paths.setdefault(c["resident_name"], c["resident"])
            if c["mode"] == "invade":
                paths.setdefault(c["invader_name"], c["invader"])
        paths = {nm: p_ for nm, p_ in paths.items() if nm in snapshots and os.path.exists(p_)
                 and sha256(p_) == snapshots[nm]}   # only the very files the cells read
        if len(paths) >= 2:
            dG, dW = genetic_dissimilarity(paths)
            prov["genetic_dissimilarity"] = {"snapshots": sorted(paths), "samples": 4000,
                                             "within": dW}
    cores = cores_from_plan(plan)
    # fixed steps: formal decisions only at the registered horizon (T and 2T of --horizon)
    windows_registered = None
    if a.clock == "steps":
        windows_registered = {float(horizon["T"]), float(horizon["T2"])} if horizon else set()
        prov["windows_registered"] = sorted(windows_registered)
    mats, mdet, blocks, joint, subs = matrices(rows, meta, sims=a.sims, registry=registry, kind=a.kind, dG=dG,
                                               cores=cores, windows_registered=windows_registered)
    confirm = None
    if a.gate:
        import gate as gate_
        gsum, gprobs = verify_gate(a.gate, receipt=a.gate_receipt)
        if a.clock != "steps":
            gprobs.append("the confirmation protocol reads fixed steps (--clock steps)")
        # review of #49, finding 1: the plan itself must be the approved confirmation design (seeds, assays,
        # horizon, snapshot times, home regimes) as far as the repository can check
        pprobs = gate_.confirmation_plan_problems(list(plan.values())) if plan else ["no --plan"]
        confirm = {"T": float(gate_.T_STEPS), "gate": gsum, "gate_problems": gprobs, "plan_problems": pprobs,
                   "strict": {"groups": 2, "N": gate_.CONFIRM["N"], "k": gate_.CONFIRM["k"],
                              "assays": gate_.CONFIRM["assays"], "fraction": gate_.CONFIRM["fraction"]}}
        prov["gate"] = {**gsum, "problems": gprobs, "plan_problems": pprobs, "strict_registration": confirm["strict"],
                        "T": confirm["T"]}
    prows, pblocks, pjoint = primary_blocks(rows, meta, registry, cores, a.sims, kind=a.kind,
                                            windows_registered=windows_registered, bsims=a.bounded_sims,
                                            confirm=confirm)
    prov["cores"] = cores
    if registry is not None and (cores or meta):
        pgroups = {g_: list(v) for g_, v in cores.items()} if cores else {}
        if not cores:
            for nm, m_ in meta.items():
                pgroups.setdefault(str(m_.get("regime")), []).append(nm)
        pspec, preq = primary_registration(registry, pgroups, cores, (confirm or {}).get("strict"))
        prov["primary_registration"] = {"required_groups": {str(f_): g_ for f_, g_ in preq.items()},
                                        "blocks": {f"{c_}/{f_}/{g_}": v for (c_, f_), gs in pspec.items()
                                                   for g_, v in gs.items()}}
    scales = [x for x in a.scales.split(",") if x]
    models = [x for x in a.bounded.split(",") if x]
    srows, mrows = scale_sensitivity(rows, blocks, scales, models, a.sims, a.bounded_sims, kind=a.kind) \
        if blocks and (scales or models) else ([], [])
    for m in mats + joint + subs + srows + mrows + prows + pjoint:
        m.update(ident)
    # the units of every block (for calibrate.py: null rejection and power through the same tests),
    # and of every primary (home-regime x condition) block: the error bank's export
    with open(os.path.join(a.out, "blocks.json"), "w") as f:
        json.dump({"schema": "finfolk.invasion.blocks/2", **ident, "clock": a.clock,
                   "blocks": [{"cond": c_, "frac": f_, "G": g_, **b} for (c_, f_, g_), b in sorted(blocks.items())],
                   "primary_blocks": [{k_: v for k_, v in b.items() if k_ != "fit"}
                                      for _, b in sorted(pblocks.items(), key=lambda kv: str(kv[0]))]}, f)
    if prows:
        write_csv(os.path.join(a.out, "primary.csv"), prows,
                  ["cond", "frac", "G", "group", "source", "status", "n", "k", "names", "cyclic_share",
                   "noise_corrected", "share_ci95_lo", "share_ci95_hi", "dC", "F_lof", "p_primary", "p_lof",
                   "p_lof_flip", "R_C_logistic", "F_res", "fit_converged", "p_res_flip", "note", "plan_sha256",
                   "analysis_sha256"])
    if pjoint:
        write_csv(os.path.join(a.out, "primary_joint.csv"), pjoint,
                  ["frac", "G", "structure", "status", "required", "conditions", "groups", "n", "k", "F_lof",
                   "p_primary", "p_lof", "p_lof_flip", "flip_min_p", "F_sym", "p_sym", "p_sym_flip", "F_res_joint",
                   "p_res_flip", "p_res_boot", "h1b_valid", "h1b_diagnostics", "both_rejected", "claim_beyond_bounded",
                   "claim_status", "boot", "plan_sha256", "analysis_sha256"])
    if prows or pjoint:
        md.append("\n## Primary matrices: one per home regime x condition (stats spec), built explicitly\n")
        md.append(f"Groups: {prows[0]['source'] if prows else ''}. A primary block is formal when every registered "
                  "cell of it is finished on the registered replicates (and, with fixed steps, its window is the "
                  "registered T or 2T, read exactly). The primary omnibus needs every registered condition x group "
                  "formal: H1 = the raw grouped sign-flip omnibus (primary test; bootstrap beside it), H1b = the "
                  "frozen co-primary (bounded.py: four separate logistic mean fits, grouped sign-flip of the "
                  "projected residual replicate vectors; joint refitting bootstrap beside it). 'both' = H1 and H1b "
                  f"both p <= a = 0.05/12 = {bounded.ALPHA_FAMILY:.5f}: the fixed conjunction at the twelve-slot "
                  "allocation (two slots active, ten unused; not full Holm). The headline claim - cardinal "
                  "circulation beyond the fitted logistic endpoint-mean family, for this fixed panel (not an ordinal "
                  "cycle, not every transitive model) - is reported only under the confirmation protocol "
                  "(analyze.py --gate: the strict registration and a passed calibration gate) at T only. Both "
                  "sign-flips are exact only under joint central symmetry; H1b also only to first order in the fit; "
                  "the level is screened by the calibration gate (gate.py).\n")
        md.append("| condition | fraction | window | group | status | items | cyclic share | noise-corrected | d_C | F lof | p sign-flip | p boot | logistic residual F | p residual flip |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r_ in prows:
            md.append(f"| {r_['cond']} | {r_['frac']} | {r_['G']} | {r_['group']} | {r_['status'][:40]} | {r_['names']} | "
                      f"{fmt(r_.get('cyclic_share'), 3)} | {fmt(r_.get('noise_corrected'), 3)} | {fmt(r_.get('dC'), 4)} | "
                      f"{fmt(r_.get('F_lof'), 2)} | {fmt(r_.get('p_lof_flip'), 4)} | {fmt(r_.get('p_lof'), 4)} | "
                      f"{fmt(r_.get('F_res'), 2)} | {fmt(r_.get('p_res_flip'), 4)} |")
        md.append("\n| fraction | window | status | groups | H1: F lof | H1 p sign-flip (floor) | H1 p boot | H1b: F_res joint | H1b p sign-flip | H1b p boot | both <= a | headline claim |\n|---|---|---|---|---|---|---|---|---|---|---|---|")
        for j_ in pjoint:
            md.append(f"| {j_['frac']} | {j_['G']} | {j_['status'][:60]} | {j_['groups']} | {fmt(j_.get('F_lof'), 2)} | "
                      f"{fmt(j_.get('p_lof_flip'), 5)} ({fmt(j_.get('flip_min_p'), 5)}) | {fmt(j_.get('p_lof'), 4)} | "
                      f"{fmt(j_.get('F_res_joint'), 2)} | {fmt(j_.get('p_res_flip'), 5)} | {fmt(j_.get('p_res_boot'), 4)} | "
                      f"{j_.get('both_rejected', '')} | {j_.get('claim_beyond_bounded', '')}"
                      + (f" ({j_['claim_status']})" if j_.get("claim_status") else "") + " |")
        for j_ in pjoint:
            if j_.get("h1b_diagnostics"):
                md.append(f"\nH1b at fraction {j_['frac']}, window {j_['G']}: {j_['h1b_diagnostics']}.")
    if mats:
        cols = ["cond", "frac", "G", "status", "plan_sha256", "analysis_sha256", "n", "k", "names", "ratings",
                "invader_effect", "resident_effect", "cyclic_share", "noise_corrected", "share_ci95_lo",
                "share_ci95_hi", "dC", "dC_ci95_lo", "dC_ci95_hi", "C_nc", "G_nc", "floor95", "p_mc",
                "F_lof", "df", "p_primary", "p_lof", "p_lof_flip", "p_lof_unstud", "F_sym", "df_sym", "p_sym", "p_sym_flip",
                "flip_min_p", "boot", "rms_A", "noise_A", "noise_curl",
                "gamma_check", "rms_Sg", "frac_Sg_pos", "n_Sg_sig_pos", "n_Sg_sig_neg", "triads_cyclic", "triads",
                "triads_sig", "melo_sigma", "melo_xy", "regime_ratings", "by_category", "corr_zC_dG"]
        write_csv(os.path.join(a.out, "matrix.csv"), mats, cols)
        write_csv(os.path.join(a.out, "matrix_pairs.csv"), mdet,
                  ["cond", "frac", "G", "a", "b", "category", "A", "se_A", "grad", "curl", "se_curl", "zC", "dG",
                   "S_gamma", "se_S_gamma"])
        if subs:
            write_csv(os.path.join(a.out, "subblocks.csv"), subs,
                      ["cond", "frac", "G", "status", "group", "names", "n", "k", "cyclic_share", "noise_corrected",
                       "share_ci95_lo", "share_ci95_hi", "dC", "F_lof", "df", "p_lof", "p_lof_flip",
                       "local_harmonic", "plan_sha256", "analysis_sha256"])
        if joint:
            write_csv(os.path.join(a.out, "matrix_joint.csv"), joint,
                      ["frac", "G", "structure", "status", "required", "conditions", "groups", "n", "k", "F_lof",
                       "p_primary", "p_lof", "p_lof_flip", "F_sym", "p_sym", "p_sym_flip", "flip_min_p", "boot",
                       "plan_sha256", "analysis_sha256"])
        md.append("\n## Complete blocks: ladder / cycle split (each condition separately)\n")
        md.append("cyclic share = ||curl||^2/||A||^2; noise-corrected = (||curl||^2 - tau_C) / (||A||^2 - tau_A) "
                  "with tau the unbiased noise energies of the (resident, replicate) units, and its 95% range "
                  "over the bootstrap confidence ball for the edge noise (approximate: the ball's radius is a "
                  "bootstrap percentile; calibrate.py measures its coverage); d_C = noise-corrected RMS cyclic "
                  "signal per pair. Lack of fit of a pure ladder: F = ||curl||^2 / tau_C (~1 under the null). "
                  f"p boot: studentized unit bootstrap ({a.kind}, {a.sims} draws; tau re-estimated in every draw), an "
                  "APPROXIMATE (asymptotic) test whose level is known only in calibrate.py's simulated worlds; "
                  "p sign-flip: replicate sign-flip, EXACT only if the replicate residual vectors are independent "
                  "and centrally symmetric (smallest attainable p = 1/2^(k-1)). The frozen primary test is "
                  f"'{infer.PRIMARY['test']}' (infer.PRIMARY). No chi-square. floor95 / p_mc: "
                  "descriptive, raw share of a pure ladder of the noise-corrected strength plus bootstrap noise. "
                  "Symmetric interaction (S_gamma, the symmetric part of the two-way gamma: a symmetric departure "
                  "from the additive invader + resident prediction, not by itself mutual invasibility or "
                  "coexistence): tested as a whole by F_sym / p_sym. triads = directed 3-cycles of sign(A) "
                  "(all / every edge |z| >= 2). The raw-scale cyclic residual is additive-scale lack of fit; on "
                  "a bounded score part of it can be a transitive bounded ladder (see the bounded-scale "
                  "sensitivity below).\n")
        md.append("| condition | fraction | window | status | N | k | RMS A | noise A | noise curl | cyclic share | noise-corrected (95% range) | d_C (95%) | floor95 | F lof (df) | p boot | p sign-flip | F sym (df) | p sym boot / flip | S_gamma sig +/- | triads cyclic/all (sig) |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for m in mats:
            md.append(f"| {m['cond']} | {m['frac']} | {m['G']} | {m['status']} | {m['n']} | {m['k']} | {m['rms_A']:.4f} | {m['noise_A']:.4f} | "
                      f"{m['noise_curl']:.4f} | {m['cyclic_share']:.3f} | {fmt(m['noise_corrected'], 3)} "
                      f"({m['share_ci95_lo']:.3f}-{m['share_ci95_hi']:.3f}) | {m['dC']:.4f} ({m['dC_ci95_lo']:.4f}-{m['dC_ci95_hi']:.4f}) | "
                      f"{fmt(m['floor95'], 3) or '-'} | {m['F_lof']:.2f} ({m['df']}) | {fmt(m['p_lof'], 4) or '-'} | "
                      f"{fmt(m['p_lof_flip'], 4) or '-'} | {m['F_sym']:.2f} ({m['df_sym']}) | "
                      f"{fmt(m['p_sym'], 4) or '-'} / {fmt(m['p_sym_flip'], 4) or '-'} | "
                      f"{m['n_Sg_sig_pos']}/{m['n_Sg_sig_neg']} | {m['triads_cyclic']}/{m['triads']} ({m['triads_sig']}) |")
        if joint:
            md.append("\nOmnibus over the assay conditions: F = sum ||curl||^2 / sum tau_C. The condition set is the "
                      "registered one; a row is formal only if every registered condition's block is formal on the "
                      "same items and replicates (otherwise descriptive, no p). 'pooled block x assays': units "
                      "resampled / flipped jointly (they share slot and donor seeds across conditions). 'home-regime "
                      "sub-blocks x assays': the stats spec's primary structure (both competitors from one home "
                      "regime), regimes independent groups (flipped and drawn independently, sign-flip resolution "
                      "1/2^(k-1) per group), assays joint within a group. The sign-flip is exact only under joint "
                      "central symmetry of the replicate residual vectors.\n")
            md.append("| fraction | window | structure | status | conditions | N | k | F lof | p boot | p sign-flip (min) | F sym | p sym boot / flip |\n|---|---|---|---|---|---|---|---|---|---|---|---|")
            for j_ in joint:
                f2 = lambda x, nd=2: f"{x:.{nd}f}" if isinstance(x, float) else ""   # noqa: E731
                md.append(f"| {j_['frac']} | {j_['G']} | {j_['structure']} | {j_['status']} | {j_['conditions']} | {j_['n']} | "
                          f"{j_['k']} | {f2(j_.get('F_lof'))} | {fmt(j_.get('p_lof'), 4)} | "
                          f"{fmt(j_.get('p_lof_flip'), 4)} ({fmt(j_.get('flip_min_p'), 4)}) | {f2(j_.get('F_sym'))} | "
                          f"{fmt(j_.get('p_sym'), 4)} / {fmt(j_.get('p_sym_flip'), 4)} |")
        md.append("\nLadder ratings, and per-pair means of the FULL-matrix decomposition by pair relation. These "
                  "are descriptive averages of residuals that depend on the whole matrix, not decompositions "
                  "within each group. The relation classes are exclusive (same-run before sisters before "
                  "same-regime), so 'same-regime' excludes same-run pairs; 'within-regime (all)' includes them. "
                  "'noise-corrected curl^2' = curl_e^2 minus its unit-estimated noise variance.\n")
        md.append("| condition | fraction | window | names | ladder ratings | by home regime | by pair relation | corr(noise-corrected curl^2, d_G) |\n|---|---|---|---|---|---|---|---|")
        for m in mats:
            regr = " ".join(f"{t.split(':')[0]}:{float(t.split(':')[1]):+.4f}" for t in m.get("regime_ratings", "").split())
            md.append(f"| {m['cond']} | {m['frac']} | {m['G']} | {m['names']} | {' '.join(f'{x:+.4f}' for x in m['ratings'])} | "
                      f"{regr} | {m.get('by_category', '')} | {fmt(m.get('corr_zC_dG'), 2)} |")
        if subs:
            md.append("\n### Balanced sub-blocks decomposed on their own (descriptive)\n")
            md.append("Each row is the complete sub-matrix of the items sharing one home regime or one snapshot time, "
                      "with its own ladder, cycle space ((n-1)(n-2)/2 dimensions) and unit noise. With two snapshots "
                      "per run there is no within-run triangle, and the regime blocks mix same-run time pairs with "
                      "cross-run pairs, so these are not the stats spec's matched within- vs between-run K3 "
                      "comparison (which needs >= 3 time points per run); inference over evolutionary runs needs "
                      "independent home runs per regime (a panel bootstrap), which two runs per regime cannot give.\n")
            md.append("p-values only for sub-blocks of a formal block (status column).\n")
            md.append("| condition | fraction | window | status | group | items | cyclic share | noise-corrected (95% range) | d_C | F lof (cycle dims) | p boot | p sign-flip | local / harmonic |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")
            for s_ in subs:
                ci = (f" ({s_['share_ci95_lo']:.3f}-{s_['share_ci95_hi']:.3f})" if s_["share_ci95_lo"] is not None else "")
                md.append(f"| {s_['cond']} | {s_['frac']} | {s_['G']} | {s_['status']} | {s_['group']} | {s_['names']} | {s_['cyclic_share']:.3f} | "
                          f"{fmt(s_['noise_corrected'], 3)}{ci} | {s_['dC']:.4f} | "
                          f"{s_['F_lof']:.2f} ({s_['df']}) | {fmt(s_['p_lof'], 4) or '-'} | {fmt(s_['p_lof_flip'], 4) or '-'} | "
                          f"{s_['local_harmonic']} |")
        if dG:
            md.append("\nSensor-relevant genetic dissimilarity d_G (1 - mean engine genomeSimilarity over 4,000 random "
                      "fish pairs: aligned slots whose source- and sink-type bits match; not full gene identity), "
                      "per pair in matrix_pairs.csv; within-snapshot values in inputs.json. The correlation above is "
                      "descriptive: pairs share snapshots and the residuals are coupled by the projection, so it is "
                      "not a test (the spec's distance slopes need a panel bootstrap over independent runs).\n")

    # --- bounded-scale sensitivity (bounded.py)
    if srows:
        write_csv(os.path.join(a.out, "scale.csv"), srows,
                  ["cond", "frac", "G", "status", "scale", "clipped", "endpoints", "n", "k", "cyclic_share",
                   "noise_corrected", "share_ci95_lo", "share_ci95_hi", "dC", "dC_ci95_lo", "dC_ci95_hi", "F_lof",
                   "p_primary", "p_lof", "p_lof_flip", "F_sym", "p_sym", "p_sym_flip", "triads_cyclic", "triads",
                   "plan_sha256", "analysis_sha256"])
    if mrows:
        write_csv(os.path.join(a.out, "bounded.csv"), mrows,
                  ["cond", "frac", "G", "status", "model", "n", "k", "B", "converged", "boot_not_converged", "sse",
                   "params", "T_C", "tau_C", "C_fit", "R_C", "R_C_null", "R_C_nc", "share_nc_raw", "share_res_nc",
                   "survival", "dC_raw", "dC_res", "F_res", "p_res", "T_S", "tau_S", "R_S", "R_S_nc", "F_res_S",
                   "p_res_S", "plan_sha256", "analysis_sha256"])
    if srows or mrows:
        md.append("\n## Bounded-scale sensitivity (is the cyclic residual a bounded ladder?)\n")
        md.append("The score is bounded (q in [0, 1]; a losing invader cannot fall below s = -f0), and a transitive but "
                  "non-additive bounded ladder makes Hodge residuals with no ordinal cycle (Bertrand, Czarnecki & Gidel "
                  "2023). (1) Transformed endpoints: each replicate's endpoint q and start fraction f are transformed, "
                  "s_h = h(q) - h(f), then the unchanged pipeline (logit clipped at EPS: exact zeros occur, so the "
                  "clip matters; asin = arcsine-sqrt, no clip). Descriptive: no scale is uniquely right, and the tests "
                  "test additivity on that scale. (2) Bounded node-additive models for the expected endpoint "
                  "qbar_ij (logistic sigma(mu + a_i + b_j); aoceil = a free asymmetric link with a ceiling; strength "
                  "= sigma(c + u_i - u_j)), each transitive by construction: C_fit = the curl the bounded ladder "
                  "itself makes, R_C = the cyclic energy left after it, residual share = (R_C - its bootstrap noise) "
                  "/ (T_A - tau_A) on the raw scale's signal, so it compares with the raw noise-corrected share; "
                  "p_res = parametric-residual bootstrap with the model refitted in every draw (approximate).\n")
        md.append("| condition | fraction | window | status | scale | clipped/endpoints | cyclic share | noise-corrected (95% range) | d_C | F lof | p boot | p sign-flip | F sym | triads cyclic |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for s_ in srows:
            md.append(f"| {s_['cond']} | {s_['frac']} | {s_['G']} | {s_['status'][:11]} | {s_['scale']} | "
                      f"{s_['clipped']}/{s_['endpoints']} | {s_['cyclic_share']:.3f} | {fmt(s_['noise_corrected'], 3)} "
                      f"({s_['share_ci95_lo']:.3f}-{s_['share_ci95_hi']:.3f}) | {s_['dC']:.4f} | {s_['F_lof']:.2f} | "
                      f"{fmt(s_['p_lof'], 4)} | {fmt(s_['p_lof_flip'], 4)} | {s_['F_sym']:.2f} | "
                      f"{s_['triads_cyclic']}/{s_['triads']} |")
        md.append("\n| condition | fraction | window | status | model | raw noise-corrected share | C_fit / T_C (curl made by the bounded ladder) | residual noise-corrected share | survival (of corrected cyclic energy) | d_C raw / residual | F_res | p_res | F_res sym | p_res sym |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for m_ in mrows:
            md.append(f"| {m_['cond']} | {m_['frac']} | {m_['G']} | {m_['status'][:11]} | {m_['model']} | "
                      f"{fmt(m_['share_nc_raw'], 3)} | {fmt(m_['C_fit'] / m_['T_C'] if m_['T_C'] > 0 else None, 3)} | "
                      f"{fmt(m_['share_res_nc'], 3)} | {fmt(m_['survival'], 3)} | {m_['dC_raw']:.4f} / {m_['dC_res']:.4f} | "
                      f"{m_['F_res']:.2f} | {fmt(m_['p_res'], 4)} | {m_['F_res_S']:.2f} | {fmt(m_['p_res_S'], 4)} |")

    # --- speed
    c, pts = speed_fit(recs)
    srows = [{"pop_mean": p, "sec_per_step": t} for p, t in pts]
    write_csv(os.path.join(a.out, "speed.csv"), srows, ["pop_mean", "sec_per_step"])
    overhead = (mean([r["build_s"] + r["score_s"] for r in recs]) + 0.15) if recs else None   # + interpreter start
    md.append("\n## Engine speed (serial build, 4 concurrent workers at nice 19)\n")
    if c:
        md.append(f"seconds/step = {c[0]:.3e} + {c[1]:.3e} pop + {c[2]:.3e} pop^2 (fit over {len(pts)} logged "
                  f"1,000-step intervals of {len(recs)} runs: population at the interval's end vs its steps/s). "
                  f"Per-cell overhead (arena build + scoring) ~{overhead:.1f} s.\n")
        md.append("| mean population | steps/s |\n|---|---|")
        for pop in (200, 300, 400, 500, 600, 700, 900):
            t = c[0] + c[1] * pop + c[2] * pop * pop
            md.append(f"| {pop} | {1 / t:.0f} |")

    # --- power: no longer here. The old table planted cycles into iid isotropic noise and judged
    # them against a chi-square / isotropic floor; calibrate.py now measures the null rejection
    # rate and the planted-cycle power of the SAME tests as above, from blocks.json.

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

    with open(os.path.join(a.out, "inputs.json"), "w") as f:
        f.write(json.dumps(prov, indent=1, sort_keys=True, default=str) + "\n")
    with open(os.path.join(a.out, "summary.md"), "w") as f:
        f.write("\n".join(md) + "\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())

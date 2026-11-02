#!/usr/bin/env python3
"""analyze.py: the seed-indexed analysis of an ALIFE 2027 run root.

    python3 tools/alife2027/analyze.py validate PROTOCOL ROOT
    python3 tools/alife2027/analyze.py report PROTOCOL ROOT OUTDIR [--reps N] [--phase P]

validate: every job of ROOT/plan.jsonl has a completed manifest whose
outputs still hash as recorded (runlib.verify); no (phase, seed, arm)
twice; main-phase seeds are the registered list and contain no development
or engineering ID.

report: one endpoint record per (seed, arm) (endpoints.csv), one record per
branch continuation (branches.csv), then protocol.json's inference:
  primary   the fixed sequence (H1, H2: paired t, one-sided; H3: the exact
            unconditional paired NI test, ni_exact.py), each formal only if
            every earlier test rejected; estimates, whole-seed bootstrap
            intervals and leave-one-seed-out ranges always
  secondary the Holm family (two-sided one-sample t on seed contrasts)
  pairing   r, G and 1 - 1/G with whole-seed bootstrap intervals
  branches  per source / checkpoint / continuation, all histories and by
            the pre-branch sweep stratum (food_h > 0.5), descriptive
  extension the registered np_companion, descriptive
written as CSV + JSON tables and report.md. Joins are by integer seed;
nothing depends on file or job order.

Bootstrap: whole-seed percentile, protocol.json's PCG32 (initstate, initseq
+ j) where j numbers the seed set a statistic uses (0 = all registered
seeds, then the subsets in the order first met) -- one stream per seed set,
so adding a statistic never changes another's interval.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finstats as fs  # noqa: E402
import ni_exact  # noqa: E402
import runlib  # noqa: E402

ENDPOINT_KEYS = ["phase", "seed", "seed_index", "arm", "base_arm", "steps", "L", "clearance_norm_90k", "clearance_norm_100k",
                 "late_clearance_raw", "late_speed", "late_food_mean", "L_zero_denominator", "A", "Y", "births_10k",
                 "births_20k", "births_30k", "min_pop", "min_pop_30k", "min_pop_pre_floor", "first_reseed_step",
                 "rescue_free_time", "rescue_censored", "reseeds", "reseed_steps", "late_pop", "pop_final", "deaths_pred",
                 "deaths_starve", "deaths_age", "pred_births", "pred_reseeds", "food_eaten", "food_expired",
                 "food_arrivals", "food_h_diff", "tracking", "fish_h_diff", "elapsed_s", "max_rss_kb", "extinct"]


def read_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(io.StringIO("".join(ln for ln in f if not ln.startswith("#")))))


def num(v):
    return None if v is None or v == "" else float(v)


def load_plan(root):
    return [json.loads(ln) for ln in open(os.path.join(root, "plan.jsonl")) if ln.strip()]


def behav_diff(path):
    if not os.path.exists(path):
        return None, None
    b = {r["genomes"]: r for r in read_rows(path)}
    fh = float(b["evolved"]["food_h"]) - float(b["random"]["food_h"])
    fi = (float(b["evolved"]["fish_h"]) - float(b["random"]["fish_h"])) if "fish_h" in b["evolved"] else None
    return fh, fi


def endpoint_record(proto, job, jdir, man):
    P = os.path.join(jdir, job["prefix"])
    steps = job["expect"]["steps"]
    rows = {int(r["step"]): r for r in read_rows(P + ".csv")}
    diag = {int(r["step"]): {k: int(v) for k, v in r.items()} for r in read_rows(P + ".diag.csv")}
    founders = diag[0]["pop"]
    ep = proto["endpoints"]
    rec = {"phase": job["phase"], "seed": job["seed"], "seed_index": job["seed_index"], "arm": job["arm"],
           "base_arm": job.get("base_arm", job["arm"]), "steps": steps}
    lr = ep["L"]["rows"]
    if all(s in rows for s in lr):
        cn = [float(rows[s]["clearance_norm"]) for s in lr]
        rec["L"] = sum(cn) / len(cn)
        rec["clearance_norm_90k"], rec["clearance_norm_100k"] = cn[0], cn[-1]
        rec["late_clearance_raw"] = sum(float(rows[s]["clearance"]) for s in lr) / len(lr)
        rec["late_speed"] = sum(float(rows[s]["speed_mean"]) for s in lr) / len(lr)
        rec["late_food_mean"] = sum(float(rows[s]["food_mean"]) for s in lr) / len(lr)
        # the driver's zero-denominator convention gives 0: flag it
        rec["L_zero_denominator"] = int(any(float(rows[s]["clearance_norm"]) == 0.0 and
                                            (float(rows[s]["speed_mean"]) == 0.0 or float(rows[s]["food_mean"]) == 0.0)
                                            for s in lr))
        rec["late_pop"] = sum(float(rows[s]["pop_mean"]) for s in lr) / len(lr)
    a_to = ep["A"]["through"]
    if a_to in diag:
        rec["A"] = diag[a_to]["auc_pop"] / (founders * a_to)
        rec["min_pop_30k"] = diag[a_to]["min_pop"]
    last = diag[steps]
    rec["Y"] = int(last["reseeds"] == 0)
    for s, k in ((10000, "births_10k"), (20000, "births_20k"), (30000, "births_30k")):
        if s in diag:
            rec[k] = diag[s]["births"]
    rec.update(min_pop=last["min_pop"], min_pop_pre_floor=last["min_pop_pre_floor"],
               first_reseed_step=last["first_reseed_step"] if last["first_reseed_step"] >= 0 else "",
               rescue_free_time=(last["first_reseed_step"] if last["first_reseed_step"] >= 0 else steps),
               rescue_censored=int(last["first_reseed_step"] < 0), reseeds=last["reseeds"],
               reseed_steps=last["reseed_steps"], pop_final=last["pop"], deaths_pred=last["deaths_pred"],
               deaths_starve=last["deaths_starve"], deaths_age=last["deaths_age"], pred_births=last["pred_births"],
               pred_reseeds=last["pred_reseeds"], food_eaten=last["food_eaten"], food_expired=last["food_expired"],
               food_arrivals=last["food_arrivals"], extinct=int(last["min_pop"] == 0))
    fh, fi = behav_diff(P + "_behav.csv")
    thr = proto["branches"]["sweep_strata"]["threshold"]
    rec["food_h_diff"], rec["fish_h_diff"] = fh, fi
    rec["tracking"] = int(fh > thr) if fh is not None else None
    rec["elapsed_s"] = man["process"].get("elapsed_s") if man else None
    rec["max_rss_kb"] = man["process"].get("max_rss_kb") if man else None
    return rec


def branch_records(proto, job, jdir):
    P = os.path.join(jdir, job["prefix"])
    if not job["expect"].get("branches"):
        return []
    out = []
    thr = proto["branches"]["sweep_strata"]["threshold"]
    steps = job["expect"]["steps"]
    for r in read_rows(P + ".branches.csv"):
        cp = int(r["checkpoint"])
        fh, _ = behav_diff(P + ("_behav.csv" if cp == steps else f"_behav_{cp}.csv"))
        rec = {"phase": job["phase"], "seed": job["seed"], "seed_index": job["seed_index"], "source": job["arm"],
               "checkpoint": cp, "branch": r["branch"], "changes": r["changes"],
               "pre_food_h_diff": fh, "stratum": ("sweep" if fh > thr else "no_sweep") if fh is not None else ""}
        for k in ("n0", "food0", "eaten", "eaten_per_n0", "eaten_per_fish_s", "clearance", "clearance_norm", "food_end",
                  "food_mean", "food_arrivals", "food_expired", "pop_end", "pop_mean", "births", "deaths", "reseeds",
                  "speed_end", "speed_mean", "eaten_early", "births_early", "speed_early", "pair_steps",
                  "encounters_ended", "encounter_steps_ended"):
            rec[k] = float(r[k]) if k in r and r[k] != "" else None
        rec["food_identity_residual"] = (rec["food0"] + rec["food_arrivals"] - rec["eaten"] - rec["food_expired"] -
                                         rec["food_end"])
        out.append(rec)
    return out


def collect(proto, root, phase=None):
    recs, brs, problems = [], [], []
    for job in load_plan(root):
        if phase and job["phase"] != phase:
            continue
        jdir = os.path.join(root, job["phase"], job["dir"])
        mp = os.path.join(jdir, job["prefix"] + ".manifest.json")
        if not os.path.exists(mp):
            problems.append(f"{job['id']}: not complete")
            continue
        try:
            man = runlib.verify(jdir, job["prefix"])
        except runlib.Invalid as e:
            problems.append(f"{job['id']}: {e}")
            continue
        recs.append(endpoint_record(proto, job, jdir, man))
        brs += branch_records(proto, job, jdir)
    keys = [(r["phase"], r["seed"], r["arm"]) for r in recs]
    if len(set(keys)) != len(keys):
        problems.append("duplicate (phase, seed, arm) records")
    return recs, brs, problems


# ---- inference -------------------------------------------------------------------
class Boot:
    """One PCG32 stream per seed set (see the module docstring)."""

    def __init__(self, proto, reps):
        b = proto["bootstrap"]
        self.initstate, self.initseq, self.reps = b["initstate"], b["initseq"], reps
        self.sets = {}

    def resamples(self, seeds):
        key = tuple(seeds)
        if key not in self.sets:
            j = len(self.sets)
            rng = fs.PCG32(self.initstate, self.initseq + j)
            n = len(seeds)
            self.sets[key] = (j, [[rng.bounded(n) for _ in range(n)] for _ in range(self.reps)])
        return self.sets[key][1]

    def interval(self, seeds, stat):
        finite, ninf, nund = [], 0, 0
        for idx in self.resamples(seeds):
            v = stat(idx)
            if v is None or (isinstance(v, float) and math.isnan(v)):
                nund += 1
            elif math.isinf(v):
                ninf += 1
            else:
                finite.append(v)
        finite.sort()
        out = {"infinite_mass": ninf / self.reps, "undefined_mass": nund / self.reps, "conditional": bool(ninf or nund)}
        out["low"] = fs.quantile(finite, 0.025) if finite else None
        out["high"] = fs.quantile(finite, 0.975) if finite else None
        return out


def table(recs, phase_seeds):
    """{arm: {seed: rec}} restricted to the registered seeds."""
    t = {}
    for r in recs:
        if r["seed"] in phase_seeds:
            t.setdefault(r["arm"], {})[r["seed"]] = r
    return t


def paired(t, a, b, ep, seeds):
    s = [x for x in seeds if x in t.get(a, {}) and x in t.get(b, {}) and t[a][x].get(ep) is not None
         and t[b][x].get(ep) is not None]
    return s, [float(t[a][x][ep]) for x in s], [float(t[b][x][ep]) for x in s]


def loo_range(d):
    if len(d) < 3:
        return None, None
    tot = math.fsum(d)
    m = [(tot - v) / (len(d) - 1) for v in d]
    return min(m), max(m)


def primary(proto, t, seeds, boot):
    pr = proto["primary"]
    alpha = pr["alpha_each"]
    out, gate_open = [], True
    for test in pr["sequence"]:
        a, b = test["contrast"]
        ep = test["endpoint"]
        s, va, vb = paired(t, a, b, ep, seeds)
        res = {"id": test["id"], "contrast": f"{a}-{b}", "endpoint": ep, "test": test["test"], "n": len(s),
               "formal": gate_open}
        if len(s) < 2:
            res.update(status="not computable (missing arms / endpoints)", reject=None)
            out.append(res)
            gate_open = False
            continue
        if test["test"] == "paired_t_one_sided":
            d = [x - y for x, y in zip(va, vb)]
            pt = fs.paired_t(d, conf=1 - 2 * alpha)
            g = fs.pairing_gain(va, vb)
            ci = boot.interval(s, lambda idx, d=d: fs.mean([d[i] for i in idx]))
            lo, hi = loo_range(d)
            reject = (not pt["degenerate"]) and pt["p_greater"] <= alpha
            res.update(mean_a=fs.mean(va), mean_b=fs.mean(vb), estimate=pt["mean"], sd_diff=pt["sd"], t=pt["t"], df=pt["df"],
                       p=pt["p_greater"], lower_one_sided=pt["lower_one_sided"], ci_low=pt["ci_low"], ci_high=pt["ci_high"],
                       boot_low=ci["low"], boot_high=ci["high"], loo_min=lo, loo_max=hi, r=g["corr"], G=g["G"],
                       degenerate=pt["degenerate"], reject=reject)
        elif test["test"] == "exact_unconditional_paired_ni":
            ya, yb = [int(v) for v in va], [int(v) for v in vb]
            c = fs.paired_binary_cells(ya, yb)
            m = Fraction(*test["margin_fraction"])
            fa = Fraction(alpha).limit_denominator(10 ** 6)
            order = test.get("ordering", "score")
            other = "difference" if order == "score" else "score"
            pv = ni_exact.p_value(c["n"], c["n10"], c["n01"], m, order)
            pv2 = ni_exact.p_value(c["n"], c["n10"], c["n01"], m, other)
            lo_b, hi_b = ni_exact.bounds(c["n"], c["n10"], c["n01"], fa, order)
            reject = pv["p_upper"] <= fa
            res.update(cells=c, estimate=c["diff"], margin=float(m), ordering=order, p=float(pv["p_upper"]),
                       p_gap=float(pv["gap"]), lower_one_sided=float(lo_b), upper_one_sided=float(hi_b),
                       reject=bool(reject), p_other_ordering=float(pv2["p_upper"]), other_ordering=other,
                       mcnemar_superiority_p=fs.mcnemar_greater(c["n10"], c["n01"]))
        else:
            raise SystemExit("unknown primary test " + test["test"])
        res["decision"] = ("reject H0" if res["reject"] else "do not reject") if gate_open else \
            "descriptive (an earlier test did not reject)"
        out.append(res)
        if not res["reject"]:
            gate_open = False
    return out


def contrast_values(proto, c, t, brs, seeds):
    """(seeds, values) of one secondary contrast, per seed."""
    if "weights" in c:
        ep = c["endpoint"]
        s = [x for x in seeds if all(x in t.get(a, {}) and t[a][x].get(ep) is not None for a in c["weights"])]
        return s, [math.fsum(w * float(t[a][x][ep]) for a, w in c["weights"].items()) for x in s]
    b = c["branch"]
    by = {}
    for r in brs:
        if r["source"] == b["source"] and r["checkpoint"] == b["checkpoint"] and r["seed"] in seeds:
            by.setdefault(r["seed"], {})[r["branch"]] = r
    s = [x for x in seeds if x in by and b["a"] in by[x] and b["b"] in by[x]]
    return s, [by[x][b["a"]][b["metric"]] - by[x][b["b"]][b["metric"]] for x in s]


def subset_seeds(seeds, c, proto):
    if "branch" in c:
        return seeds[:proto["subsets"]["branches"]["seeds_first"]]
    return seeds


def secondary(proto, t, brs, seeds, boot):
    sec = proto["secondary"]
    rows = []
    for c in sec["contrasts"]:
        ss = subset_seeds(seeds, c, proto)
        s, v = contrast_values(proto, c, t, brs, ss)
        row = {"id": c["id"], "name": c["name"], "n": len(s)}
        if len(s) < 2:
            row.update(status="not computable", p=None)
        else:
            pt = fs.paired_t(v, conf=1 - sec["alpha_two_sided"])
            ci = boot.interval(s, lambda idx, v=v: fs.mean([v[i] for i in idx]))
            row.update(estimate=pt["mean"], sd=pt["sd"], t=pt["t"], p=pt["p_two_sided"], ci_low=pt["ci_low"],
                       ci_high=pt["ci_high"], boot_low=ci["low"], boot_high=ci["high"], degenerate=pt["degenerate"])
        rows.append(row)
    comp = [i for i, r in enumerate(rows) if r.get("p") is not None]
    adj = fs.holm([rows[i]["p"] for i in comp])
    for i, a in zip(comp, adj):
        rows[i]["p_holm"] = a
        rows[i]["reject"] = a <= sec["alpha_two_sided"]
    if len(comp) < len(rows):
        for r in rows:
            r["holm_family"] = f"{len(comp)} of {len(rows)} computable (the registered family needs all {len(rows)})"
    return rows


def pairing(proto, t, seeds, boot):
    out = []
    for a, b in proto["pairing_efficiency"]["pairs"]:
        for ep in proto["pairing_efficiency"]["endpoints"]:
            s, va, vb = paired(t, a, b, ep, seeds)
            if len(s) < 3:
                continue
            g = fs.pairing_gain(va, vb)
            ci = boot.interval(s, lambda idx, va=va, vb=vb: fs.pairing_gain([va[i] for i in idx], [vb[i] for i in idx])["G"])
            out.append({"pair": f"{a}-{b}", "endpoint": ep, "n": len(s), "sd_a": g["sd_a"], "sd_b": g["sd_b"],
                        "sd_diff": g["sd_d"], "r": g["corr"], "G": g["G"], "G_state": g["G_state"],
                        "variance_reduction": g["variance_reduction"], "G_low": ci["low"], "G_high": ci["high"],
                        "G_infinite_mass": ci["infinite_mass"], "G_undefined_mass": ci["undefined_mass"],
                        "G_conditional": ci["conditional"]})
    return out


def binary_cells(proto, t, seeds):
    out = []
    for a, b in proto["pairing_efficiency"]["pairs"]:
        s, va, vb = paired(t, a, b, "Y", seeds)
        if not s:
            continue
        c = fs.paired_binary_cells([int(v) for v in va], [int(v) for v in vb])
        out.append({"pair": f"{a}-{b}", **c, "mcnemar_p_greater": fs.mcnemar_greater(c["n10"], c["n01"])})
    return out


def branch_summary(proto, brs, seeds):
    first = set(seeds[:proto["subsets"]["branches"]["seeds_first"]])
    groups = {}
    for r in brs:
        if r["seed"] not in first:
            continue
        for stratum in ("all", r["stratum"] or "unknown"):
            groups.setdefault((r["source"], r["checkpoint"], r["branch"], stratum), []).append(r)
    out = []
    for (src, cp, br, st), rs in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2], kv[0][3])):
        row = {"source": src, "checkpoint": cp, "branch": br, "stratum": st, "n": len(rs)}
        for k in ("eaten_per_n0", "clearance", "clearance_norm", "births", "pop_mean", "speed_end", "food_mean",
                  "food_expired", "eaten_early", "speed_early", "pair_steps"):
            v = [r[k] for r in rs if r[k] is not None]
            row[k + "_mean"] = fs.mean(v) if v else None
        row["identity_residual_max"] = max(abs(r["food_identity_residual"]) for r in rs)
        out.append(row)
    return out


def extension_summary(proto, recs):
    out = []
    for ext in proto.get("extensions", []):
        ph = "ext:" + ext["id"]
        er = [r for r in recs if r["phase"] == ph]
        core = {(r["seed"], r["arm"]): r for r in recs if r["phase"] == "main"}
        for arm in ext["arms"]:
            lab = arm + ext["label_suffix"]
            rs = [r for r in er if r["arm"] == lab]
            if not rs:
                continue
            row = {"extension": ext["id"], "arm": lab, "n": len(rs), "extinct": sum(r["extinct"] for r in rs)}
            for k in ("L", "A", "min_pop", "pop_final"):
                v = [r[k] for r in rs if r.get(k) is not None]
                row[k + "_mean"] = fs.mean(v) if v else None
            pairs = [(r, core.get((r["seed"], arm))) for r in rs]
            dA = [r["A"] - c["A"] for r, c in pairs if c and r.get("A") is not None and c.get("A") is not None]
            row["A_minus_core_mean"] = fs.mean(dA) if dA else None
            row["n_paired_with_core"] = len(dA)
            out.append(row)
    return out


def write_csv(path, rows, keys=None):
    if not rows:
        open(path, "w").close()
        return
    keys = keys or list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: (repr(v) if isinstance(v, float) else v) for k, v in r.items()})


def registered_seeds(proto, base, phase, recs):
    if phase == "main":
        return [int(x) for x in open(os.path.join(base, proto["seeds"]["main"])).read().split()]
    seen = {}
    for r in recs:
        if r["phase"] == phase:
            seen[r["seed"]] = r["seed_index"]
    return [s for s, _ in sorted(seen.items(), key=lambda kv: kv[1])]


def report(proto_path, root, outdir, reps, phase):
    proto = json.load(open(proto_path))
    base = os.path.dirname(os.path.abspath(proto_path))
    recs, brs, problems = collect(proto, root)
    os.makedirs(outdir, exist_ok=True)
    seeds = registered_seeds(proto, base, phase, recs)
    t = table([r for r in recs if r["phase"] == phase], set(seeds))
    tb = [b for b in brs if b["phase"] == phase]
    boot = Boot(proto, reps)
    res = {"phase": phase, "n_seeds": len(seeds), "problems": problems,
           "primary": primary(proto, t, seeds, boot),
           "secondary": secondary(proto, t, tb, seeds, boot),
           "pairing": pairing(proto, t, seeds, boot),
           "binary_cells": binary_cells(proto, t, seeds),
           "branches": branch_summary(proto, tb, seeds),
           "extensions": extension_summary(proto, recs),
           "bootstrap": {"reps": reps, "streams": {str(j): len(k) for k, (j, _) in boot.sets.items()}}}
    write_csv(os.path.join(outdir, "endpoints.csv"), sorted(recs, key=lambda r: (r["phase"], r["seed_index"], r["arm"])),
              ENDPOINT_KEYS)
    write_csv(os.path.join(outdir, "branches.csv"), sorted(brs, key=lambda r: (r["phase"], r["seed_index"], r["source"],
                                                                                 r["checkpoint"], r["branch"])))
    for k in ("secondary", "pairing", "binary_cells", "branches", "extensions"):
        write_csv(os.path.join(outdir, k + ".csv"), res[k])
    write_csv(os.path.join(outdir, "primary.csv"), [{k: v for k, v in r.items() if k != "cells"} for r in res["primary"]])
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(res, f, indent=1, default=str)
    arm_rows = []
    for arm, by in sorted(t.items()):
        row = {"arm": arm, "n": len(by)}
        for ep in ("L", "A", "Y", "births_30k", "min_pop", "late_pop", "elapsed_s"):
            v = [float(r[ep]) for r in by.values() if r.get(ep) is not None]
            row[ep + "_mean"] = fs.mean(v) if v else None
            row[ep + "_sd"] = fs.sd(v) if len(v) > 1 else None
        arm_rows.append(row)
    write_csv(os.path.join(outdir, "arms.csv"), arm_rows)
    md = [f"# ALIFE 2027 analysis ({phase})", "", f"{len(recs)} completed runs read from `{root}`; {len(seeds)} "
          f"registered seeds in this phase; problems: {len(problems)}.", ""]
    md += [f"- {p}" for p in problems[:20]]
    md += ["", "## Primary sequence", "", "| test | contrast | endpoint | n | estimate | p | decision |", "|---|---|---|---|---|---|---|"]
    for r in res["primary"]:
        md.append(f"| {r['id']} | {r['contrast']} | {r['endpoint']} | {r['n']} | {fs.fmt(r.get('estimate'))} | "
                  f"{fs.fmt(r.get('p'), 6)} | {r.get('decision', r.get('status'))} |")
    md += ["", "## Secondary family (Holm, two-sided)", "", "| id | contrast | n | estimate | p | p Holm |", "|---|---|---|---|---|---|"]
    for r in res["secondary"]:
        md.append(f"| {r['id']} | {r['name']} | {r['n']} | {fs.fmt(r.get('estimate'))} | {fs.fmt(r.get('p'))} | "
                  f"{fs.fmt(r.get('p_holm'))} |")
    md += ["", "## Pairing efficiency", "", "| pair | endpoint | n | r | G | 95 % CI |", "|---|---|---|---|---|---|"]
    for r in res["pairing"]:
        md.append(f"| {r['pair']} | {r['endpoint']} | {r['n']} | {fs.fmt(r['r'], 3)} | {fs.fmt(r['G'], 3)} | "
                  f"[{fs.fmt(r['G_low'], 2)}, {fs.fmt(r['G_high'], 2)}]{' conditional' if r['G_conditional'] else ''} |")
    md += ["", "Tables: endpoints.csv, branches.csv, arms.csv, primary.csv, secondary.csv, pairing.csv, binary_cells.csv, "
           "branches (summary) in branches.csv / results.json, extensions.csv."]
    open(os.path.join(outdir, "report.md"), "w").write("\n".join(md) + "\n")
    return res


def validate(proto_path, root):
    proto = json.load(open(proto_path))
    base = os.path.dirname(os.path.abspath(proto_path))
    recs, _brs, problems = collect(proto, root)
    excluded = set()
    for k in ("development", "engineering"):
        excluded |= {int(x) for x in open(os.path.join(base, proto["seeds"][k])).read().split()}
    main = [int(x) for x in open(os.path.join(base, proto["seeds"]["main"])).read().split()]
    for r in recs:
        if r["phase"] == "main" and (r["seed"] in excluded or r["seed"] not in main):
            problems.append(f"main-phase seed {r['seed']} is excluded or unregistered")
    return recs, problems


def main():
    a = sys.argv
    if len(a) >= 4 and a[1] == "validate":
        recs, problems = validate(a[2], a[3])
        for p in problems:
            print("PROBLEM:", p)
        print(f"{len(recs)} complete runs verified; {len(problems)} problems")
        return 1 if problems else 0
    if len(a) >= 5 and a[1] == "report":
        reps = int(a[a.index("--reps") + 1]) if "--reps" in a else json.load(open(a[2]))["bootstrap"]["replicates"]
        phase = a[a.index("--phase") + 1] if "--phase" in a else "main"
        res = report(a[2], a[3], a[4], reps, phase)
        print(f"report in {a[4]}: {len(res['problems'])} problems")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())

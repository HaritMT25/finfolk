#!/usr/bin/env python3
"""historical.py: the v2 endpoints recovered from the pre-registration runs
(experiment 2 `steer/main`, the cloaked-eye ablation `next2/abl`, experiment 3
`steer/exp3`, experiment 1 `eyeexp/main*`), per arm and seed, with paired
statistics. Exploratory: these runs motivate the protocol, they are not
confirmation data.

    python3 tools/alife2027/historical.py ROOT OUT_CSV OUT_MD [--reps 20000]

ROOT is the directory holding steer/, next2/ and eyeexp/ (~/wasm_parity).

What the legacy interval CSV (one row per 10,000 steps) allows:
  L  = mean(clearance_norm at rows 90000 and 100000)                  exact (4 dp printed)
  A  = mean(pop_mean at rows 10000, 20000, 30000) / 300               exact up to the 2-dp print:
       pop_mean is the per-step mean of the post-update population over the
       interval, so sum_{t=1}^{30000} N(t) = 10000 * (pm10k + pm20k + pm30k)
  Y  = 1{reseeds (cumulative totalReseeds) at row 100000 == 0}         exact
  births through 10k / 20k / 30k (cumulative `births`)                 exact
  first rescue: only the 10k interval that holds it (not the step)
  minimum population: only interval-end values (not every step, not pre-floor)
  tracking: behavioural food_h evolved - random > 0.5 (the historical threshold)
"""
from __future__ import annotations

import csv
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finstats as fs  # noqa: E402

SEEDS = list(range(1, 13))

# (world, label, relative dir, file arm, note)
DATASETS = [
    ("L12", "A0", "steer/main/L12", "A0", "experiment 2 main"),
    ("L12", "C0", "steer/main/L12", "C0", "experiment 2 main"),
    ("L12", "C1", "steer/main/L12", "C1", "experiment 2 main (= next2/abl/runs C1, state columns identical)"),
    ("L12", "D0", "steer/main/L12", "D0", "experiment 2 main"),
    ("L12", "D1", "steer/main/L12", "D1", "experiment 2 main (= next2/abl/runs D1, state columns identical)"),
    ("L12", "C1nf", "next2/abl/runs", "C1nf", "cloaked-eye ablation, eyeCode 8"),
    ("L12", "C1nd", "next2/abl/runs", "C1nd", "cloaked-eye ablation, eyeCode 16"),
    ("L12", "C1po", "next2/abl/runs", "C1po", "cloaked-eye ablation, eyeCode 24"),
    ("L12", "C1c2", "steer/exp3/L12c2", "C1", "experiment 3, eyeCode 2"),
    ("L12", "C1c3", "steer/exp3/L12c3", "C1", "experiment 3, eyeCode 3"),
    ("L12", "C1c7", "steer/exp3/L12c7", "C1", "experiment 3, eyeCode 7"),
    ("L16", "A0", "steer/main/L16", "A0", "experiment 2 main"),
    ("L16", "C0", "steer/main/L16", "C0", "experiment 2 main"),
    ("L16", "C1", "steer/main/L16", "C1", "experiment 2 main"),
    ("L16", "D0", "steer/main/L16", "D0", "experiment 2 main"),
    ("L16", "D1", "steer/main/L16", "D1", "experiment 2 main"),
    ("dense", "C1", "steer/main/dense", "C1", "experiment 2, experiment 1's world"),
    ("dense", "D1", "steer/main/dense", "D1", "experiment 2, experiment 1's world"),
    ("exp1", "A", "eyeexp/main", "A", "experiment 1 (dense, world frame)"),
    ("exp1", "B", "eyeexp/main", "B", "experiment 1"),
    ("exp1", "C", "eyeexp/main", "C", "experiment 1"),
    ("exp1", "D", "eyeexp/main", "D", "experiment 1"),
    ("exp1thrust", "A", "eyeexp/main_thrust", "A", "experiment 1, thrust variant"),
    ("exp1thrust", "B", "eyeexp/main_thrust", "B", "experiment 1, thrust variant"),
    ("exp1thrust", "C", "eyeexp/main_thrust", "C", "experiment 1, thrust variant"),
    ("exp1thrust", "D", "eyeexp/main_thrust", "D", "experiment 1, thrust variant"),
]

# Replicates of an existing arm (checked for identical state columns, not re-counted)
IDENTITY_CHECKS = [
    ("next2/abl/runs", "C1", "steer/main/L12", "C1"),
    ("next2/abl/runs", "D1", "steer/main/L12", "D1"),
    ("steer/exp3/L12c0", "C1", "steer/main/L12", "C1"),
]
STATE_COLS = 33   # arm .. genome_len: everything before the wall-clock ms_per_step

PAIRS = {
    "L12": [("C1", "D1"), ("C1", "A0"), ("C1", "C0"), ("D1", "D0"), ("C0", "D0"), ("A0", "D1"),
            ("C1", "C1nf"), ("C1", "C1nd"), ("C1", "C1po"), ("C1nd", "D1"), ("C1nf", "D1"), ("C1po", "D1"),
            ("C1nd", "C1po"), ("C1", "C1c2"), ("C1", "C1c3"), ("C1", "C1c7")],
    "L16": [("C1", "D1"), ("C1", "A0"), ("C1", "C0"), ("D1", "D0"), ("C0", "D0"), ("A0", "D1")],
    "dense": [("C1", "D1")],
    "exp1": [("C", "D"), ("A", "C"), ("B", "C"), ("A", "D")],
    "exp1thrust": [("C", "D"), ("A", "C"), ("B", "C"), ("A", "D")],
}
CONTRASTS = {   # seed-level linear contrasts (L12 only), as protocol v2 section 4 defines them
    "steering interaction (C1-D1)-(C0-D0)": {"C1": 1, "D1": -1, "C0": -1, "D0": 1},
    "food visibility (C1+C1nf-C1nd-C1po)/2": {"C1": .5, "C1nf": .5, "C1nd": -.5, "C1po": -.5},
    "fish visibility (C1+C1nd-C1nf-C1po)/2": {"C1": .5, "C1nd": .5, "C1nf": -.5, "C1po": -.5},
    "food x fish interaction C1-C1nf-C1nd+C1po": {"C1": 1, "C1nf": -1, "C1nd": -1, "C1po": 1},
}
ENDPOINTS = ["L", "A", "late_pop", "births_30k"]
Z975, Z95 = 1.959963984540054, 1.6448536269514722


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def run_record(root, world, label, rel, farm, seed):
    path = os.path.join(root, rel, f"{farm}_s{seed}.csv")
    rows = read_csv(path)
    steps = [int(r["step"]) for r in rows]
    if steps != list(range(10000, 100001, 10000)):
        raise SystemExit(f"{path}: unexpected rows {steps}")
    by = {int(r["step"]): r for r in rows}
    if int(by[10000]["seed"]) != seed:
        raise SystemExit(f"{path}: seed column {by[10000]['seed']}")
    f = lambda s, k: float(by[s][k])   # noqa: E731
    reseeds_100k = int(by[100000]["reseeds"])
    first_int = next((s for s in steps if int(by[s]["reseeds"]) > 0), None)
    rec = {
        "world": world, "arm": label, "seed": seed, "source": path,
        "L": 0.5 * (f(90000, "clearance_norm") + f(100000, "clearance_norm")),
        "A": (f(10000, "pop_mean") + f(20000, "pop_mean") + f(30000, "pop_mean")) / (3 * 300),
        "Y": int(reseeds_100k == 0),
        "reseeds_100k": reseeds_100k,
        "first_reseed_interval_end": first_int if first_int is not None else "",
        "births_10k": int(by[10000]["births"]), "births_20k": int(by[20000]["births"]),
        "births_30k": int(by[30000]["births"]),
        "late_pop": 0.5 * (f(90000, "pop_mean") + f(100000, "pop_mean")),
        "pop_20k": int(by[20000]["pop"]), "pop_30k": int(by[30000]["pop"]),
        "min_interval_end_pop": min(int(r["pop"]) for r in rows),
        "min_interval_pop_mean": min(float(r["pop_mean"]) for r in rows),
        "late_clearance_raw": 0.5 * (f(90000, "clearance") + f(100000, "clearance")),
        "late_food_mean": 0.5 * (f(90000, "food_mean") + f(100000, "food_mean")),
        "speed_100k": f(100000, "speed_mean"),
        "clearance_norm_90k": f(90000, "clearance_norm"), "clearance_norm_100k": f(100000, "clearance_norm"),
        "pop_mean_10k": f(10000, "pop_mean"), "pop_mean_20k": f(20000, "pop_mean"),
        "pop_mean_30k": f(30000, "pop_mean"),
    }
    bpath = os.path.join(root, rel, f"{farm}_s{seed}_behav.csv")
    if os.path.exists(bpath):
        b = {r["genomes"]: r for r in read_csv(bpath)}
        fh = float(b["evolved"]["food_h"]) - float(b["random"]["food_h"])
        rec["food_h_diff"] = fh
        rec["tracking"] = int(fh > 0.5)
    else:
        rec["food_h_diff"] = ""
        rec["tracking"] = ""
    return rec


def identity_check(root, rel_a, arm_a, rel_b, arm_b):
    """(seeds compared, seeds that differ); a seed absent from either side is not compared."""
    same, bad = [], []
    for s in SEEDS:
        pa = os.path.join(root, rel_a, f"{arm_a}_s{s}.csv")
        pb = os.path.join(root, rel_b, f"{arm_b}_s{s}.csv")
        if not (os.path.exists(pa) and os.path.exists(pb)):
            continue
        ra = [ln.split(",")[:STATE_COLS] for ln in open(pa).read().splitlines()]
        rb = [ln.split(",")[:STATE_COLS] for ln in open(pb).read().splitlines()]
        # the arm column may carry a different label; compare from column 2 on
        (same if [r[1:] for r in ra] == [r[1:] for r in rb] else bad).append(s)
    return same, bad


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    root, out_csv, out_md = sys.argv[1], sys.argv[2], sys.argv[3]
    reps = int(sys.argv[sys.argv.index("--reps") + 1]) if "--reps" in sys.argv else 20000

    recs, missing = [], []
    for world, label, rel, farm, note in DATASETS:
        for s in SEEDS:
            p = os.path.join(root, rel, f"{farm}_s{s}.csv")
            if not os.path.exists(p):
                missing.append(p)
                continue
            r = run_record(root, world, label, rel, farm, s)
            r["note"] = note
            recs.append(r)
    idchecks = [(a, b, c, d, identity_check(root, a, b, c, d)) for a, b, c, d in IDENTITY_CHECKS]

    keys = ["world", "arm", "seed", "L", "A", "Y", "reseeds_100k", "first_reseed_interval_end", "births_10k",
            "births_20k", "births_30k", "late_pop", "pop_20k", "pop_30k", "min_interval_end_pop",
            "min_interval_pop_mean", "late_clearance_raw", "late_food_mean", "speed_100k", "clearance_norm_90k",
            "clearance_norm_100k", "pop_mean_10k", "pop_mean_20k", "pop_mean_30k", "food_h_diff", "tracking",
            "source", "note"]
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(keys)
        for r in recs:
            w.writerow([repr(r[k]) if isinstance(r[k], float) else r[k] for k in keys])

    data = {}   # (world, arm) -> {seed: rec}
    for r in recs:
        data.setdefault((r["world"], r["arm"]), {})[r["seed"]] = r

    # one set of whole-seed resamples for everything (seed vectors resampled together)
    rng = fs.PCG32(20261101, 77)
    n = len(SEEDS)
    resamples = [[rng.bounded(n) for _ in range(n)] for _ in range(reps)]

    def boot(stat):
        finite, ninf, nund = [], 0, 0
        for idx in resamples:
            v = stat(idx)
            if v is None or (isinstance(v, float) and math.isnan(v)):
                nund += 1
            elif math.isinf(v):
                ninf += 1
            else:
                finite.append(v)
        finite.sort()
        lo = fs.quantile(finite, 0.025) if finite else None
        hi = fs.quantile(finite, 0.975) if finite else None
        return lo, hi, ninf / reps, nund / reps

    def vec(world, arm, ep):
        d = data.get((world, arm), {})
        if len(d) != n:
            return None
        return [float(d[s][ep]) for s in SEEDS]

    md = []
    P = md.append
    P("# Historical per-seed endpoints (protocol v2 definitions)")
    P("")
    P("Generated by `tools/alife2027/historical.py` (branch `alife-tooling`) from the raw run outputs in WSL "
      f"`{root}`. Exploratory only: these runs motivated protocol v2 and are excluded from confirmation "
      "(seeds 1-12 are the development seeds). Per-seed values: `historical_per_seed.csv` (one row per world, "
      "arm and seed, with its exact source file).")
    P("")
    P("## What the recorded columns allow")
    P("")
    P("The historical driver wrote one CSV row per 10,000 steps. From those rows:")
    P("")
    P("- **L** (late clearance) = mean of `clearance_norm` at the rows ending 90k and 100k: **exact**, the v2 "
      "definition (the historical \"last 20 %\" search efficiency used the same two rows).")
    P("- **A** (early population AUC) = (pop_mean@10k + pop_mean@20k + pop_mean@30k) / (3 x 300): **exact up to "
      "the 2-decimal print** (|error| <= 1.7e-5), because `pop_mean` is the per-step mean of the post-update "
      "population over each 10k interval, so these three rows sum the 30,000 per-step values.")
    P("- **Y** (no reseed) = cumulative `reseeds` (= totalReseeds, injected founders) at 100k equals 0: **exact**.")
    P("- Births through 10k/20k/30k: exact (cumulative column).")
    P("- **Not recoverable**: the exact first-rescue step (only the 10k interval that holds it), the per-step and "
      "pre-floor minimum population (only interval-end values), food arrivals and expiry (never logged), "
      "encounter diagnostics.")
    P("")
    P("## Sources")
    P("")
    P("| world | arm | directory | note |")
    P("|---|---|---|---|")
    for world, label, rel, farm, note in DATASETS:
        P(f"| {world} | {label} | `{os.path.join(root, rel)}/{farm}_s<seed>.csv` | {note} |")
    P("")
    P("Seeds 1-12 in every arm. World configurations: `steer/main/cfg_L12.json` / `cfg_L16.json` / "
      "`cfg_dense.json`, `next2/abl/cfg_L12{,nf,nd,po}.json`, `steer/exp3/cfg_L12c*.json`, `eyeexp/main/cfg.json`, "
      "`eyeexp/main_thrust/cfg.json`. L12 = v2's ecology (1 item/step x 15 energy, foodLife 12, predator economy).")
    P("")
    P("Identity checks (state columns 2-33, every row, all 12 seeds):")
    P("")
    for a, b, c, d, (same, bad) in idchecks:
        P(f"- `{a}/{b}` vs `{c}/{d}`: seeds {same + bad} compared: "
          + ("identical" if not bad else f"DIFFERENT in seeds {bad}")
          + ("" if len(same) + len(bad) == len(SEEDS) else " (the other seeds were not run there)"))
    if missing:
        P("")
        P("Missing files: " + ", ".join(missing))
    else:
        P("")
        P(f"Missing files: none ({len(recs)} runs read, each with exactly the 10 rows 10k..100k).")
    P("")

    for world in ["L12", "L16", "dense", "exp1", "exp1thrust"]:
        arms = [lab for (wd, lab) in data if wd == world]
        if not arms:
            continue
        P(f"## World {world}: per arm (n = 12 seeds)")
        P("")
        P("| arm | L mean | L SD | L median | A mean | A SD | A median | Y = 1 | late pop mean | births 0-30k mean "
          "| tracking |")
        P("|---|---|---|---|---|---|---|---|---|---|---|")
        for arm in arms:
            Lv, Av, Yv = vec(world, arm, "L"), vec(world, arm, "A"), vec(world, arm, "Y")
            lp, b30 = vec(world, arm, "late_pop"), vec(world, arm, "births_30k")
            tr = [data[(world, arm)][s]["tracking"] for s in SEEDS]
            trs = f"{sum(t for t in tr if t != '')}/{sum(1 for t in tr if t != '')}" if any(t != "" for t in tr) else "-"
            P(f"| {arm} | {fs.mean(Lv):.4f} | {fs.sd(Lv):.4f} | {fs.median(Lv):.4f} | {fs.mean(Av):.4f} | "
              f"{fs.sd(Av):.4f} | {fs.median(Av):.4f} | {int(sum(Yv))}/12 | {fs.mean(lp):.1f} | {fs.mean(b30):.0f} | "
              f"{trs} |")
        P("")
        P(f"### {world}: paired differences (same seed), whole-seed bootstrap {reps} resamples")
        P("")
        P("G = (s_a^2 + s_b^2) / s_(a-b)^2; G > 1 means pairing by seed reduced the variance of the difference "
          "(variance reduction 1 - 1/G); G < 1 means it increased it (negative within-pair correlation). "
          "p = paired t, one-sided (a > b). CI = 95 % percentile bootstrap.")
        P("")
        P("| pair | endpoint | mean diff | SD diff | 95 % CI mean diff | r | SD a | SD b | G | 95 % CI G | 1 - 1/G "
          "| p (a > b) |")
        P("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for a, b in PAIRS.get(world, []):
            for ep in ["L", "A", "late_pop"]:
                va, vb = vec(world, a, ep), vec(world, b, ep)
                if va is None or vb is None:
                    continue
                d = [x - y for x, y in zip(va, vb)]
                g = fs.pairing_gain(va, vb)
                t = fs.paired_t(d)

                def gstat(idx, va=va, vb=vb):
                    ra, rb = [va[i] for i in idx], [vb[i] for i in idx]
                    return fs.pairing_gain(ra, rb)["G"]

                def mstat(idx, d=d):
                    return fs.mean([d[i] for i in idx])

                glo, ghi, ginf, gund = boot(gstat)
                mlo, mhi, _, _ = boot(mstat)
                gci = f"[{fs.fmt(glo, 2)}, {fs.fmt(ghi, 2)}]"
                if ginf or gund:
                    gci += f" (inf {ginf:.3f}, undef {gund:.3f}; conditional)"
                dg = 3 if ep == "late_pop" else 4
                P(f"| {a}-{b} | {ep} | {t['mean']:.{dg}f} | {t['sd']:.{dg}f} | [{mlo:.{dg}f}, {mhi:.{dg}f}] | "
                  f"{fs.fmt(g['corr'], 3)} | {g['sd_a']:.{dg}f} | {g['sd_b']:.{dg}f} | {fs.fmt(g['G'], 3)} | {gci} | "
                  f"{fs.fmt(g['variance_reduction'], 3)} | {fs.fmt(t['p_greater'], 4)} |")
        P("")
        P(f"### {world}: binary Y (no reseed through 100k), paired cells")
        P("")
        P("| a vs b | both Y=1 | a only | b only | neither | p_a | p_b | diff | exact McNemar p (a > b) |")
        P("|---|---|---|---|---|---|---|---|---|")
        for a, b in PAIRS.get(world, []):
            ya, yb = vec(world, a, "Y"), vec(world, b, "Y")
            if ya is None or yb is None:
                continue
            c = fs.paired_binary_cells([int(v) for v in ya], [int(v) for v in yb])
            P(f"| {a} vs {b} | {c['n11']} | {c['n10']} | {c['n01']} | {c['n00']} | {c['p_x']:.3f} | {c['p_y']:.3f} | "
              f"{c['diff']:+.3f} | {fs.mcnemar_greater(c['n10'], c['n01']):.4f} |")
        P("")
        if world == "L12":
            P("### L12: seed-level factorial contrasts (v2 secondary definitions)")
            P("")
            P("| contrast | endpoint | mean | SD | 95 % CI (bootstrap) | p (two-sided t) |")
            P("|---|---|---|---|---|---|")
            for name, wts in CONTRASTS.items():
                for ep in ["L", "A", "births_30k"]:
                    vs = {arm: vec(world, arm, ep) for arm in wts}
                    if any(v is None for v in vs.values()):
                        continue
                    cv = [sum(wt * vs[arm][i] for arm, wt in wts.items()) for i in range(n)]
                    t = fs.paired_t(cv)
                    lo, hi, _, _ = boot(lambda idx, cv=cv: fs.mean([cv[i] for i in idx]))
                    dg = 1 if ep == "births_30k" else 4
                    P(f"| {name} | {ep} | {t['mean']:.{dg}f} | {t['sd']:.{dg}f} | [{lo:.{dg}f}, {hi:.{dg}f}] | "
                      f"{fs.fmt(t['p_two_sided'], 4)} |")
            P("")
            P("### L12: planning illustration from these 12 seeds (normal approximation, NOT a power guarantee)")
            P("")
            P("N95 = (1.95996 + 1.64485)^2 s_d^2 / delta^2 pairs for 95 % power at one-sided .025, taking the "
              "observed mean difference as delta and the observed paired SD as s_d. 'Unpaired N95' replaces s_d^2 "
              "by s_a^2 + s_b^2 (what the same allocation would need without the within-seed correlation). "
              "With n = 12 both SDs are themselves very uncertain (see the bootstrap intervals above).")
            P("")
            P("| pair | endpoint | delta | s_d | N95 paired | N95 unpaired | approx power at 128 | SE of mean diff at 128 |")
            P("|---|---|---|---|---|---|---|---|")
            for a, b in [("C1", "D1"), ("C1", "A0"), ("C1", "C0"), ("C1", "C1nf"), ("C1", "C1nd"), ("C1nd", "D1")]:
                for ep in ["L", "A"]:
                    va, vb = vec(world, a, ep), vec(world, b, ep)
                    if va is None or vb is None:
                        continue
                    d = [x - y for x, y in zip(va, vb)]
                    dl, sdd = fs.mean(d), fs.sd(d)
                    unp = math.sqrt(fs.var(va) + fs.var(vb))
                    if dl == 0 or sdd == 0:
                        continue
                    n95 = (Z975 + Z95) ** 2 * sdd ** 2 / dl ** 2
                    n95u = (Z975 + Z95) ** 2 * unp ** 2 / dl ** 2
                    zpow = math.sqrt(128) * abs(dl) / sdd - Z975
                    powr = 0.5 * (1 + math.erf(zpow / math.sqrt(2)))
                    P(f"| {a}-{b} | {ep} | {dl:+.4f} | {sdd:.4f} | {n95:.1f} | {n95u:.1f} | {powr:.4f} | "
                      f"{sdd / math.sqrt(128):.4f} |")
            P("")
            P("### L12: per-seed values of the principal arms")
            P("")
            P("| seed | L C1 | L D1 | L A0 | L C1-D1 | A C1 | A D1 | A A0 | A C1-D1 | Y C1 | Y D1 | Y A0 | reseeds C1/D1/A0 "
              "| tracking C1 |")
            P("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
            for s in SEEDS:
                c, d_, a0 = data[("L12", "C1")][s], data[("L12", "D1")][s], data[("L12", "A0")][s]
                P(f"| {s} | {c['L']:.4f} | {d_['L']:.4f} | {a0['L']:.4f} | {c['L'] - d_['L']:+.4f} | {c['A']:.4f} | "
                  f"{d_['A']:.4f} | {a0['A']:.4f} | {c['A'] - d_['A']:+.4f} | {c['Y']} | {d_['Y']} | {a0['Y']} | "
                  f"{c['reseeds_100k']}/{d_['reseeds_100k']}/{a0['reseeds_100k']} | {c['tracking']} |")
            P("")
    open(out_md, "w").write("\n".join(md) + "\n")
    print(f"{len(recs)} runs; wrote {out_csv} and {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

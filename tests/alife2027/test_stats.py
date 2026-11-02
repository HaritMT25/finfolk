#!/usr/bin/env python3
"""Tests for tools/alife2027/{finstats,ni_exact,analyze}.py (stdlib only):

    python3 tests/alife2027/test_stats.py [--quick]
"""
from __future__ import annotations

import itertools
import math
import os
import random
import sys
import time
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools", "alife2027"))
import analyze  # noqa: E402
import finstats as fs  # noqa: E402
import ni_exact as ni  # noqa: E402

QUICK = "--quick" in sys.argv
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"ok   {name}")
    else:
        FAIL += 1
        print(f"FAIL {name} {detail}")


# ---- finstats ------------------------------------------------------------------------
r = fs.PCG32(42, 54)
check("pcg32 reference vector (42, 54)",
      [r.next_u32() for _ in range(6)] == [0xa15c02b7, 0x7b47f409, 0xba1d3330, 0x83d2f293, 0xbfa4784b, 0xcbed606e])
r = fs.PCG32(1, 1)
draws = [r.bounded(7) for _ in range(7000)]
check("bounded draws in range, all values hit", set(draws) == set(range(7)))
check("t quantiles", abs(fs.t_ppf(0.975, 10) - 2.2281388519864) < 1e-9 and abs(fs.t_ppf(0.975, 127) - 1.978820) < 2e-6,
      f"{fs.t_ppf(0.975, 10)!r} {fs.t_ppf(0.975, 127)!r}")
check("t tail", abs(fs.t_sf(2.0, 5) - 0.050969739414929) < 1e-12)
check("holm", fs.holm([0.01, 0.04, 0.03, 0.005]) == [0.03, 0.06, 0.06, 0.02])
check("holm keeps order and caps at 1", fs.holm([0.9, 0.5]) == [1.0, 1.0])
check("mcnemar exact", fs.mcnemar_greater(7, 0) == 1 / 128 and fs.mcnemar_greater(0, 0) == 1.0)
g = fs.pairing_gain([1, 2, 3, 4], [1, 2, 3, 4])
check("G infinite when the difference is constant", g["G_state"] == "infinite" and math.isinf(g["G"]))
g = fs.pairing_gain([1, 1, 1], [2, 2, 2])
check("G undefined when everything is constant", g["G_state"] == "undefined" and g["G"] is None and math.isnan(g["corr"]))
a, b = [1.0, 2.0, 4.0, 7.0], [1.5, 1.0, 5.0, 6.0]
g = fs.pairing_gain(a, b)
d = [x - y for x, y in zip(a, b)]
check("G definition", abs(g["G"] - (fs.var(a) + fs.var(b)) / fs.var(d)) < 1e-12)
pt = fs.paired_t([0.1, 0.2, 0.3, 0.4, 0.5])
check("paired t", abs(pt["t"] - 0.3 / (fs.sd([0.1, 0.2, 0.3, 0.4, 0.5]) / math.sqrt(5))) < 1e-12)
check("constant contrast: p 1 + degeneracy", fs.paired_t([0.2, 0.2, 0.2])["p_two_sided"] == 1.0 and fs.paired_t([0.2] * 3)["degenerate"])
check("quantile type 7", fs.quantile([1, 2, 3, 4], 0.25) == 1.75)

# ---- ni_exact: the brief's fixtures ------------------------------------------------------
m = F(3, 20)
for n, dd, want, wantq in ((1, 1, F(17, 40), F(1)), (2, 1, F(289, 1200), F(43, 60)), (2, 2, F(289, 1600), F(1))):
    lo, hi, arg = ni.sup_tail(n, dd, -m, gap=F(1, 10 ** 14))
    q = m + (1 - m) * arg
    check(f"fixture n={n} d={dd}: sup = {want}", lo <= want <= hi and hi - lo <= F(1, 10 ** 14) and abs(q - wantq) < F(1, 10 ** 4),
          f"[{float(lo)}, {float(hi)}] at q {float(q)}")

# collapsed trinomial == four-cell enumeration; Bernstein form == the direct polynomial
ok4 = okb = True
for n in range(1, 6 if QUICK else 7):
    for p11, p10, p01 in ((F(1, 5), F(1, 10), F(3, 10)), (F(1, 3), F(1, 3), F(1, 6)), (F(0), F(1, 2), F(1, 4))):
        p00 = 1 - p11 - p10 - p01
        cells = [(p11, 0), (p10, 1), (p01, -1), (p00, 0)]
        for dd in range(-n, n + 1):
            tot = F(0)
            for seq in itertools.product(range(4), repeat=n):
                if sum(cells[c][1] for c in seq) >= dd:
                    pr = F(1)
                    for c in seq:
                        pr *= cells[c][0]
                    tot += pr
            ok4 &= tot == ni.trinomial_tail(n, dd, p10, p01)
    for dd in range(-n, n + 1):
        for delta in (-m, F(0), F(1, 4), F(-1, 2)):
            M, L = ni.tail_coefficients(n, dd, delta)
            for tt in (F(0), F(1, 3), F(7, 10), F(1)):
                q = abs(delta) + (1 - abs(delta)) * tt
                okb &= ni.bernstein_eval(M, L, tt) == ni.trinomial_tail(n, dd, (q + delta) / 2, (q - delta) / 2)
check("trinomial tail == four-cell enumeration (n <= 6, three parameter points, every d)", ok4)
check("Bernstein coefficients reproduce the tail exactly (every n, d, delta, t tested)", okb)

# certified sup vs a fine rational grid of the nuisance
okg = True
for n in range(1, 9):
    for dd in range(-n, n + 1):
        lo, hi, _ = ni.sup_tail(n, dd, -m, gap=F(1, 10 ** 12))
        M, L = ni.tail_coefficients(n, dd, -m)
        grid = max(ni.bernstein_eval(M, L, F(k, 200)) for k in range(201))
        okg &= grid <= hi and hi - grid < F(1, 10 ** 3) and lo <= hi and hi - lo <= F(1, 10 ** 12)
check("certified sup >= every grid point and within 1e-3 of the grid max (n <= 8, all d)", okg)

# both orderings, small n: exact size on the null boundary AND inside the null (the
# least-favourable argument), p-value monotone in the ordering statistic, closure,
# p-value nondecreasing in delta0 (the bisection's assumption), exact coverage
for ordering in ("score", "difference"):
    oks = okin = okp = okcl = okm = True
    for alpha in (F(1, 40), F(1, 5)):
        for n in range(1, 9 if not QUICK else 7):
            tables = [(u, v) for u in range(n + 1) for v in range(n - u + 1)]
            okcl &= all(ni.region_closed(n, ni.region(n, u, v, -m, ordering)) for u, v in tables)
            _, inS = ni.rejection_region(n, alpha, m, ordering)
            for k in range(0, 21):
                q = m + (1 - m) * F(k, 20)
                oks &= ni.region_prob(n, inS, (q - m) / 2, (q + m) / 2) <= alpha
                dl = -m - F(1, 10)   # inside the null
                if q >= -dl:
                    okin &= ni.region_prob(n, inS, (q + dl) / 2, (q - dl) / 2) <= alpha
            if alpha == F(1, 5) and n in (4, 6):
                stat = (lambda u, v: ni.score_z(n, u, v, -m)) if ordering == "score" else (lambda u, v: u - v)
                pv = sorted(((stat(u, v), ni.p_value(n, u, v, m, ordering, gap=F(1, 10 ** 12))["p_upper"]) for u, v in tables))
                okp &= all(pv[i][1] >= pv[i + 1][1] - F(1, 10 ** 11) for i in range(len(pv) - 1))
    nonmono = 0
    for n in (3, 5):
        for u, v in ((2, 0), (1, 1), (0, 2), (n, 0)):
            vals = [ni.null_sup(n, u, v, F(k, 10), ordering, gap=F(1, 10 ** 10))[1] for k in range(-9, 10)]
            nonmono += sum(1 for x, y in zip(vals, vals[1:]) if x > y + F(1, 10 ** 9))
    check(f"{ordering}: exact size <= alpha on the null boundary (alpha .025, .2; n <= 8)", oks)
    check(f"{ordering}: exact size <= alpha inside the null (delta = -m - .1)", okin)
    check(f"{ordering}: every region closed under (u, v) -> (u + 1, v - 1)", okcl)
    check(f"{ordering}: p-value nonincreasing in the ordering statistic (n = 4, 6)", okp)
    if ordering == "difference":
        check("difference: null supremum nondecreasing in delta0 (n = 3, 5)", nonmono == 0)
    else:
        print(f"     score: the null supremum decreases in delta0 at {nonmono} grid steps (n = 3, 5): bounds by scan, not bisection")
    n, alpha = 5, F(1, 10)
    tables = [(u, v) for u in range(n + 1) for v in range(n - u + 1)]
    Lb = {(u, v): ni.lower_bound(n, u, v, alpha, ordering, coarse=16, fine=256) for u, v in tables}
    okc = True
    for p10, p01 in ((F(1, 10), F(3, 10)), (F(2, 5), F(1, 10)), (F(1, 4), F(1, 4)), (F(0), F(1, 2)), (F(1, 20), F(1, 20))):
        cover = ni.region_prob(n, [[Lb[(u, v)] <= p10 - p01 for v in range(n - u + 1)] for u in range(n + 1)], p10, p01)
        okc &= cover >= 1 - alpha
    check(f"{ordering}: lower bound covers >= 1 - alpha exactly (n = 5, five parameter points)", okc)
    check(f"{ordering}: lower bound <= the estimate", all(Lb[(u, v)] <= F(u - v, n) for u, v in tables))

# n = 128, the study's size: certification time, closure, and v2's worked case
# (A1 never needs rescue, so the question is p_C1 > .85)
t0 = time.time()
r128 = ni.p_value(128, 0, 11, m)
t1 = time.time()
check("n = 128 score p-value certified to 1e-10 (region closed)", r128["gap"] <= F(1, 10 ** 10), f"{float(r128['gap'])}")
print(f"     n=128, b=0, c=11: score p <= {float(r128['p_upper']):.6g} (q* {float(r128['q_at_max']):.4f}) in {t1 - t0:.2f} s; "
      f"difference ordering p <= {float(ni.p_value(128, 0, 11, m, 'difference')['p_upper']):.6g}")
if not QUICK:
    for ordering in ("score", "difference"):
        t0 = time.time()
        tcrit, inS = ni.rejection_region(128, F(1, 40), m, ordering)
        maxc = max((v for v in range(129) if inS[0][v]), default=None)
        pw = {pc: float(ni.region_prob(128, inS, F(0), 1 - pc)) for pc in (F(11, 12), F(92, 100), F(95, 100))}
        print(f"     {ordering}: n=128 rejects (b=0) up to c = {maxc}; power with A1 always rescue-free: "
              + ", ".join(f"p_C1 {float(k):.3f} -> {v:.4f}" for k, v in pw.items()) + f" [{time.time() - t0:.1f} s]")
        check(f"{ordering}: n = 128 rejection region found", tcrit is not None or ordering == "difference")

# ---- analyze: synthetic records ------------------------------------------------------
proto = {
    "primary": {"alpha_each": 0.025, "sequence": [
        {"id": "H1", "contrast": ["C1", "D1"], "endpoint": "L", "test": "paired_t_one_sided"},
        {"id": "H2", "contrast": ["C1", "D1"], "endpoint": "A", "test": "paired_t_one_sided"},
        {"id": "H3", "contrast": ["C1", "A1"], "endpoint": "Y", "test": "exact_unconditional_paired_ni",
         "margin_fraction": [3, 20]}]},
    "secondary": {"alpha_two_sided": 0.025, "contrasts": [
        {"id": "S1", "name": "x", "endpoint": "L", "weights": {"C1": 1, "D1": -1}},
        {"id": "S2", "name": "y", "endpoint": "A", "weights": {"C1": 0.5, "A1": -0.5}},
        {"id": "S3", "name": "z", "branch": {"source": "C1", "checkpoint": 100, "a": "sham", "b": "blind", "metric": "clearance"}}]},
    "pairing_efficiency": {"pairs": [["C1", "D1"]], "endpoints": ["L", "A"]},
    "subsets": {"branches": {"seeds_first": 10}},
    "bootstrap": {"initstate": 20261102, "initseq": 55},
}
rnd = random.Random(5)
seeds = list(range(100, 140))
recs = []
for i, s in enumerate(seeds):
    base = rnd.gauss(0, 0.1)
    for arm, shift, ya in (("C1", 0.3, 1), ("D1", 0.0, int(rnd.random() < 0.4)), ("A1", 0.25, 1)):
        recs.append({"phase": "main", "seed": s, "seed_index": i, "arm": arm, "L": 1 + shift + base + rnd.gauss(0, 0.1),
                     "A": 0.5 + shift + rnd.gauss(0, 0.2), "Y": ya if arm != "C1" else int(rnd.random() < 0.97)})
brs = [{"phase": "main", "seed": s, "source": "C1", "checkpoint": 100, "branch": b, "clearance": 1.0 + (0.2 if b == "sham" else 0) + rnd.gauss(0, .05)}
       for s in seeds[:10] for b in ("sham", "blind")]


def run(recs_in):
    t = analyze.table(recs_in, set(seeds))
    boot = analyze.Boot(proto, 300)
    return analyze.primary(proto, t, seeds, boot), analyze.secondary(proto, t, brs, seeds, boot), analyze.pairing(proto, t, seeds, analyze.Boot(proto, 300))


p1, s1, g1 = run(recs)
shuffled = recs[:]
random.Random(9).shuffle(shuffled)
p2, s2, g2 = run(shuffled)
check("analysis invariant to record order (seed join)", str(p1) == str(p2) and str(s1) == str(s2) and str(g1) == str(g2))
check("H1 estimate = mean paired difference",
      abs(p1[0]["estimate"] - fs.mean([next(r["L"] for r in recs if r["seed"] == s and r["arm"] == "C1") -
                                       next(r["L"] for r in recs if r["seed"] == s and r["arm"] == "D1") for s in seeds])) < 1e-12)
check("H1 and H2 reject a large effect; H3 formal", p1[0]["reject"] and p1[1]["reject"] and p1[2]["formal"])
check("secondary Holm adjusted >= raw", all(r["p_holm"] >= r["p"] - 1e-15 for r in s1 if r.get("p") is not None))
check("branch contrast uses the first-10 subset", s1[2]["n"] == 10)
p3, _, _ = run([r for r in recs if r["arm"] != "D1"])
check("missing arm: not computable, later tests descriptive", p3[0]["reject"] is None and not p3[2]["formal"])
print(f"stats tests: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)

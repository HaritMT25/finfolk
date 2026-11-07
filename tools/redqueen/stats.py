#!/usr/bin/env python3
"""stats.py: the confirmatory backbone's resampling, exact H-C test, multiplicity and calibration
arithmetic (design v4 §8-9 as specified by Annex H, design/redqueen_annexH_codex.md, with the user's
decisions of 2026-11-07; (d) item 5). Pure Python, deterministic (rqlib.SplitMix64 streams).

CONVENTIONS (H.0.2, H.0.4). Time t in M = actual frame / 1e6 (F1 is 1e-6 M), x = t / 50. Streams: the
first eight SHA-256 bytes, little-endian, of "AnnexH/1/<hypothesis>/<stage>/<mode>/<panel-index>"
(summary simulations) or "AnnexH/1/<hypothesis>/<analysis-name>/bootstrap" (bootstraps). B = 9,999
draws, no adaptive increase. Q(u) = z_(min{B, max[1, ceil((B+1)u)]}) of the sorted draws. Tail ties
count with >=. A numerical or nonfinite failure is an unavailable result, never omitted.

H-P / H-Q (H.2). cluster_test: theta, se = est(records); T = (theta - null) / se; for each of B draws of
n worlds with replacement (complete records; duplicate copies are distinct bootstrap worlds; est refits
any pooled nuisance), T*_b = (theta_b - theta) / se_b, a draw with se_b = 0 RETAINED as 0 / +inf / -inf
by the sign of theta_b - theta; p = (1 + #{T*_b >= T}) / (B + 1). Original se = 0: unavailable.
Bootstrap-t intervals CI95, CI99 and the one-sided L99; material exceedance p_delta from T_delta =
(theta - delta) / se on the same draws; sensitivities: Student-t (n - 1 df) p-value and intervals,
leave-one-world-out range and the largest absolute influence. Detection: p <= 0.01 and theta > null.

H-C (H.5, the user's decision: one-sided positive intersection-union, no t / wild fallback). Per world
d_w = beta_N - beta_S; per usable block D_G,b = mean(d of its eligible C worlds) - d_G,b for G in {A, B}
(a block needs its A, its B and >= 1 eligible C world); blocks equally weighted. For each G, over every
e in {-1, +1}^n: p_G = #{sum e_b D_G,b >= sum D_G,b} / 2^n; p_C = max(p_A, p_B); reject iff p_C <= 0.01
and both estimates > 0. One-sided floor 2^-n: 8 blocks 0.0039, 7 blocks 0.0078 (can reject), 6 blocks
0.0156 (cannot). Material: p computed on D - 0.02. 99% lower bounds by exact inversion: L_G = the
(k+1)-th smallest nonempty-subset mean, k = floor(0.01 2^n) - 1 (-inf if k < 0); min(L_A, L_B) bounds
min(Delta_A, Delta_B). t_A, t_B are reported, never calibrated.

MULTIPLICITY (the user's decision: Holm step-down at familywise 0.05 over H-P, H-Q, H-F, H-T, H-C,
replacing H.6's fixed Bonferroni). An unavailable hypothesis keeps its row and enters as p = 1 (no
alpha reallocation). The reciprocal-directional headline needs both H-P and H-Q rejected under Holm;
its p is max(adjusted p_P, adjusted p_Q). Material claims are nested: only under a rejected parent.

CROSSED SOURCES (H.7). Bootstrap multiplicities m_w of the drawn root worlds: a within-world record
weighs m_w (not m_w^2), a cross-world record m_u m_v, a record against a frozen external reference
m_w (the reference: evolutionary multiplicity one). crossed_mean_draws returns resampled means only
(no studentized crossed test).

CALIBRATION ARITHMETIC (H.11, H.12). The one-sided Clopper-Pearson U95 = Beta^-1(0.95; k + 1, N - k)
(1 if k = N); a null rate passes iff U95 <= 0.02 (N = 1,000: at most 12 false positives). Development
critical value: the plus-one 0.99 order statistic. Model p-values (1 + #{null >= s}) / (N + 1), the
maximum over strata. CPU: 24,000 x 14.4 s = 96 CPU-h; target (96 - 6) x 3600 / 24,000 = 13.5 s/panel.
"""
from __future__ import annotations

import hashlib
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rqlib  # noqa: E402

B_BOOT = 9999
HYPOTHESES = ("H-P", "H-Q", "H-F", "H-T", "H-C")
FAMILY_ALPHA = 0.05
DETECT_ALPHA = 0.01
DELTA_P = math.log(1.10)
DELTA_Q = 0.02
DELTA_C = 0.02
CPU_CEILING_H = 96.0
CPU_RESERVE_H = 6.0
PANELS = 24_000


class StatsError(Exception):
    pass


# ================================================================== conventions
def t_of_frame(frame):
    """Time in M of an actual archived frame (F1 = frame 1 = 1e-6 M)."""
    return int(frame) / 1e6


def x_of_frame(frame):
    return t_of_frame(frame) / 50.0


def stream_seed(*parts):
    """The first eight SHA-256 bytes, little-endian, of "AnnexH/1/<parts...>"."""
    text = "AnnexH/1/" + "/".join(str(p) for p in parts)
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little")


def stream(*parts):
    return rqlib.SplitMix64(stream_seed(*parts))


def bootstrap_stream(hypothesis, analysis):
    return stream(hypothesis, analysis, "bootstrap")


def Q(sorted_vals, u):
    """Q(u) = z_(min{B, max[1, ceil((B + 1) u)]}) (1-based order statistic of the sorted draws)."""
    B = len(sorted_vals)
    k = min(B, max(1, math.ceil((B + 1) * u - 1e-12)))
    return sorted_vals[k - 1]


def projection(xs, ms):
    """The linear projection (equal weights) of a fitted mean response on x -> (slope, intercept at x = 0)."""
    n = len(xs)
    xb = sum(xs) / n
    mb = sum(ms) / n
    sxx = sum((x - xb) ** 2 for x in xs)
    if sxx <= 0:
        raise StatsError("a projection needs at least two distinct times")
    b = sum((x - xb) * m for x, m in zip(xs, ms)) / sxx
    return b, mb - b * xb


# ================================================================== distributions (no scipy)
def _betacf(a, b, x):
    tiny, eps = 1e-300, 3e-16
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 10000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            return h
    raise StatsError("betainc did not converge")


def betainc(a, b, x):
    """The regularized incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lb = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(lb) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lb) * _betacf(b, a, 1.0 - x) / b


def beta_ppf(q, a, b):
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if betainc(a, b, mid) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def t_sf(t, df):
    """P(T_df >= t)."""
    if math.isinf(t):
        return 0.0 if t > 0 else 1.0
    x = df / (df + t * t)
    tail = 0.5 * betainc(df / 2.0, 0.5, x)
    return tail if t >= 0 else 1.0 - tail


def t_ppf(u, df):
    lo, hi = -1e3, 1e3
    for _ in range(200):
        mid = (lo + hi) / 2
        if 1.0 - t_sf(mid, df) < u:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def clopper_pearson_upper(k, n, conf=0.95):
    """The one-sided Clopper-Pearson upper bound Beta^-1(conf; k + 1, n - k) (1 if k = n)."""
    return 1.0 if k >= n else beta_ppf(conf, k + 1, n - k)


def acceptance(k, n, limit=0.02):
    u = clopper_pearson_upper(k, n)
    return {"false_positives": k, "panels": n, "U95": u, "limit": limit, "pass": u <= limit}


def critical_value(null_scores, level=0.99):
    """The development critical value: the plus-one `level` order statistic ceil(level (n + 1))."""
    s = sorted(null_scores)
    return s[min(len(s), math.ceil(level * (len(s) + 1) - 1e-12)) - 1]


def model_p(s, strata):
    """max over strata of (1 + #{null >= s}) / (N + 1)."""
    return max((1 + sum(x >= s for x in v)) / (len(v) + 1) for v in strata.values())


def cpu_targets():
    return {"ceiling_cpu_s_per_panel": CPU_CEILING_H * 3600 / PANELS,
            "target_cpu_s_per_panel": (CPU_CEILING_H - CPU_RESERVE_H) * 3600 / PANELS}


# ================================================================== H-P / H-Q world resampling
def mean_se(values):
    """est() for a mean of per-world contributions: (mean, sd / sqrt(n))."""
    n = len(values)
    m = sum(values) / n
    v = sum((x - m) ** 2 for x in values) / (n - 1) if n > 1 else 0.0
    return m, math.sqrt(v / n)


def cluster_test(units, est, draws=B_BOOT, rng=None, null=0.0, delta=None, key=None):
    """The null-centred studentized world-cluster bootstrap of H.2 (see the module doc). units: one
    complete record per qualifying world; key(unit) -> its registry id (canonical order: results do
    not depend on the input order); est(list of units) -> (theta, se). -> the result record."""
    if key is not None:
        units = sorted(units, key=key)
    n = len(units)
    if n < 2:
        raise StatsError("world resampling needs at least two worlds")
    rng = rng or rqlib.SplitMix64(0)
    try:
        theta, se = est(units)
    except (ValueError, ArithmeticError, StatsError) as e:
        return {"available": False, "reason": f"estimation failed: {e}"}
    if not (math.isfinite(theta) and math.isfinite(se)):
        return {"available": False, "reason": "a nonfinite estimate"}
    if se == 0:
        return {"available": False, "reason": "the original standard error is 0", "estimate": theta}
    T = (theta - null) / se
    ts = []
    for _ in range(draws):
        th, s = est([units[rng.below(n)] for _ in range(n)])
        if s > 0:
            ts.append((th - theta) / s)
        else:
            ts.append(0.0 if th == theta else (math.inf if th > theta else -math.inf))
    srt = sorted(ts)
    out = {"available": True, "estimate": theta, "se": se, "n": n, "T": T, "null": null, "draws": draws,
           "retained": len(ts), "p": (1 + sum(t >= T for t in ts)) / (draws + 1),
           "CI95": [theta - Q(srt, 0.975) * se, theta - Q(srt, 0.025) * se],
           "CI99": [theta - Q(srt, 0.995) * se, theta - Q(srt, 0.005) * se],
           "L99": theta - Q(srt, 0.99) * se}
    out["detected"] = out["p"] <= DETECT_ALPHA and theta > null
    if delta is not None:
        Td = (theta - delta) / se
        out["delta"] = delta
        out["p_delta"] = (1 + sum(t >= Td for t in ts)) / (draws + 1)
        out["material_point"] = theta >= delta
        out["material_evidence"] = out["p_delta"] <= DETECT_ALPHA and theta > delta
    # sensitivities (never rescue a failed primary test)
    df = n - 1
    out["t_sensitivity"] = {"df": df, "p": t_sf(T, df),
                            "CI95": [theta - t_ppf(0.975, df) * se, theta + t_ppf(0.975, df) * se]}
    loo = [est(units[:i] + units[i + 1:])[0] for i in range(n)]
    out["leave_one_out"] = {"min": min(loo), "max": max(loo), "max_influence": max(abs(x - theta) for x in loo)}
    return out


def cluster_interval(units, est, draws=B_BOOT, rng=None, level=0.95):
    """Percentile and bootstrap-t intervals (the percentile one is secondary)."""
    n = len(units)
    rng = rng or rqlib.SplitMix64(0)
    theta, se = est(units)
    ths, ts = [], []
    for _ in range(draws):
        th, s = est([units[rng.below(n)] for _ in range(n)])
        ths.append(th)
        ts.append((th - theta) / s if s > 0 else (0.0 if th == theta else math.copysign(math.inf, th - theta)))
    a = (1.0 - level) / 2.0
    sth, sts = sorted(ths), sorted(ts)
    return {"estimate": theta, "se": se, "level": level, "percentile": [Q(sth, a), Q(sth, 1 - a)],
            "bootstrap_t": [theta - Q(sts, 1 - a) * se, theta - Q(sts, a) * se], "draws": draws}


# ================================================================== H-C
def hc_block_deltas(slopes, worlds):
    """slopes {world id: {"neural": beta_N, "scripted": beta_S}}; worlds: registry entries (id, treatment,
    block) -> (deltas {block: (D_A, D_B)} of the usable blocks, unusable {block: why}). d_w = beta_N -
    beta_S; D_G,b = mean(d of the block's eligible C worlds) - d_G,b."""
    by = {}
    for w in worlds:
        by.setdefault(w["block"], []).append(w)

    def d(w):
        s = slopes.get(w["id"])
        if not isinstance(s, dict):
            return None
        x, y = s.get("neural"), s.get("scripted")
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x, y)):
            return None
        return x - y
    deltas, unusable = {}, {}
    for b, ws in sorted(by.items()):
        cs = [d(w) for w in ws if w["treatment"] == "C" and d(w) is not None]
        g = {t: [d(w) for w in ws if w["treatment"] == t and d(w) is not None] for t in ("A", "B")}
        if not cs or len(g["A"]) != 1 or len(g["B"]) != 1:
            unusable[b] = (f"{len(cs)} eligible C, {len(g['A'])} A, {len(g['B'])} B worlds with both slopes "
                           "(needs >= 1 C and exactly one A and one B)")
            continue
        dc = sum(cs) / len(cs)
        deltas[b] = (dc - g["A"][0], dc - g["B"][0])
    return deltas, unusable


def t_stat(xs):
    """The one-sample t statistic (reported only)."""
    n = len(xs)
    m = sum(xs) / n
    v = sum((x - m) ** 2 for x in xs) / (n - 1) if n > 1 else 0.0
    if v <= 0.0:
        return 0.0 if m == 0 else math.copysign(math.inf, m)
    return m / math.sqrt(v / n)


def signflip_p(D):
    """The one-sided positive sign-flip p-value of sum(D): #{e: sum e_b D_b >= sum D_b} / 2^n, by
    enumeration (ties count)."""
    n = len(D)
    obs = sum(D)
    tol = 1e-12 * max(1.0, sum(abs(x) for x in D))
    k = 0
    for mask in range(2 ** n):
        s = sum(-x if mask >> i & 1 else x for i, x in enumerate(D))
        k += s >= obs - tol
    return k, 2 ** n, k / 2 ** n


def signflip_lower(D, alpha=DETECT_ALPHA):
    """The exact one-sided 1 - alpha lower bound: sup{a: p(D - a) <= alpha} = the (k+1)-th smallest
    nonempty-subset mean, k = floor(alpha 2^n) - 1; -inf if alpha is unattainable."""
    n = len(D)
    k = math.floor(alpha * 2 ** n + 1e-12) - 1
    if k < 0:
        return -math.inf
    means = sorted(sum(x for i, x in enumerate(D) if mask >> i & 1) / bin(mask).count("1")
                   for mask in range(1, 2 ** n))
    return means[k]


def hc_test(deltas, alpha=DETECT_ALPHA, delta=DELTA_C):
    """H-C's one-sided positive intersection-union sign-flip test (see the module doc)."""
    blocks = sorted(deltas)
    n = len(blocks)
    if n < 2:
        return {"available": False, "reason": f"{n} usable blocks", "n_blocks": n}
    DA = [deltas[b][0] for b in blocks]
    DB = [deltas[b][1] for b in blocks]
    kA, N, pA = signflip_p(DA)
    kB, _, pB = signflip_p(DB)
    eA, eB = sum(DA) / n, sum(DB) / n
    pC = max(pA, pB)
    mA = signflip_p([x - delta for x in DA])[2]
    mB = signflip_p([x - delta for x in DB])[2]
    LA, LB = signflip_lower(DA, alpha), signflip_lower(DB, alpha)
    floor = 1.0 / N
    return {"available": True, "blocks": blocks, "n_blocks": n, "patterns": N,
            "estimate_A": eA, "estimate_B": eB, "t_A": t_stat(DA), "t_B": t_stat(DB),
            "tail_A": kA, "tail_B": kB, "p_A": pA, "p_B": pB, "p": pC, "p_floor": floor,
            "alpha_attainable": floor <= alpha, "reject": pC <= alpha and eA > 0 and eB > 0,
            "material_points": {"A": eA >= delta, "B": eB >= delta},
            "p_material": max(mA, mB), "lower99": {"A": LA, "B": LB, "min": min(LA, LB)},
            "note": None if floor <= alpha else
            f"with {n} usable blocks the smallest attainable one-sided p is {floor:g} > {alpha}: H-C cannot reject"}


# ================================================================== multiplicity
def holm(pvals, alpha=FAMILY_ALPHA, family=HYPOTHESES):
    """Holm step-down over the five primary hypotheses. pvals {hypothesis: p or None (unavailable)};
    an unavailable hypothesis keeps its row and enters as p = 1 (no alpha reallocation) -> {"adjusted",
    "reject", "unavailable"}."""
    m = len(family)
    p = {h: (1.0 if pvals.get(h) is None else float(pvals[h])) for h in family}
    order = sorted(family, key=lambda h: (p[h], family.index(h)))
    adj, run = {}, 0.0
    for i, h in enumerate(order):
        run = max(run, min(1.0, (m - i) * p[h]))
        adj[h] = run
    return {"adjusted": adj, "reject": {h: adj[h] <= alpha for h in family},
            "unavailable": sorted(h for h in family if pvals.get(h) is None), "alpha": alpha}


def reciprocal_directional(h):
    """The headline needs both H-P and H-Q rejected under Holm; its p is max of their adjusted p."""
    return {"claim": h["reject"]["H-P"] and h["reject"]["H-Q"],
            "p": max(h["adjusted"]["H-P"], h["adjusted"]["H-Q"])}


# ================================================================== crossed sources (H.7)
def source_weight(m, u, v):
    """The bootstrap weight of a record between source worlds u and v (v None: a frozen reference):
    within-world m_u, cross-world m_u m_v, against a reference m_u."""
    if v is None or u == v:
        return m.get(u, 0)
    return m.get(u, 0) * m.get(v, 0)


def crossed_mean_draws(records, draws=B_BOOT, rng=None):
    """Resampled weighted means of records [(prey world, predator world or None, value)]: the union of
    root worlds drawn once per draw, each record weighted by source_weight -> (full mean, [means])."""
    ws = sorted({u for u, _, _ in records} | {v for _, v, _ in records if v is not None})
    full = sum(x for _, _, x in records) / len(records)
    rng = rng or rqlib.SplitMix64(0)
    out = []
    for _ in range(draws):
        m = {}
        for _i in range(len(ws)):
            w = ws[rng.below(len(ws))]
            m[w] = m.get(w, 0) + 1
        num = den = 0.0
        for u, v, x in records:
            wt = source_weight(m, u, v)
            num += wt * x
            den += wt
        if den > 0:
            out.append(num / den)
    return full, out

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

H-C (H.5, the user's decision: one-sided positive intersection-union, no t / wild fallback; USER
DECISIONS 2: precision weights). Per world d_w = beta_N - beta_S; per usable block D_G,b = mean(d of its
eligible C worlds) - mean(d of its eligible G worlds) for G in {A, B} (a block needs >= 1 eligible C, A
and B world; one or two controls per treatment), weight w_G,b = 1 / (1/n_C,b + 1/n_G,b) (normalized;
equal for balanced intact blocks, where the test is H.5's). For each G, over every e in {-1, +1}^n:
p_G = #{sum e_b w_G,b D_G,b >= sum w_G,b D_G,b} / 2^n; p_C = max(p_A, p_B); reject iff p_C is at most
H-C's ACTIVE Holm level and both weighted estimates > 0. One-sided floor 2^-n: 8 blocks 0.0039, 7 blocks
0.0078, 6 blocks 0.0156 (6 blocks cannot reject at 0.01, but can at an active Holm level >= 1/64, e.g.
0.05/3). Material: p computed on D - 0.02. Ties are exact (signflip_p). The REPORTED 99% lower bounds
(fixed 0.01, whatever the decision level) by exact inversion: L_G = the (k+1)-th smallest nonempty-subset
mean, k = floor(0.01 2^n) - 1 (-inf if k < 0); min(L_A, L_B) bounds min(Delta_A, Delta_B); the bounds at
the active decision level are reported beside them with their confidence. t_A, t_B are reported, never
calibrated.

MULTIPLICITY (the user's decision: Holm step-down at familywise 0.05 over H-P, H-Q, H-F, H-T, H-C,
replacing H.6's fixed Bonferroni). An unavailable hypothesis keeps its row and enters as p = 1 (no
alpha reallocation). The step-down runs on the RAW p-values (ties: the family order); each hypothesis's
active level alpha / (m - i) and whether the step-down reached it come from that order, never from the
plateaued adjusted values. family_decision is authoritative (nominal 0.01 flags never substitute). The
reciprocal-directional headline needs both H-P and H-Q rejected under Holm; its p is max(adjusted p_P,
adjusted p_Q). Material claims are nested: only under a rejected parent.

ELIGIBILITY (Annex H D6 rules 26-27, 33; D7 rules 36-38; eligibility / decide): the AUTHORITATIVE dispatcher. Q200
(every retained C history coexisting through the observed 200M endpoint, recomputed from worlds.py ecology's
export) with |Q200| >= 24 gates H-P, H-Q, H-F and H-T ONLY, all on that common population (a result computed on
another is refused); H-C independently by usable blocks (>= 1 eligible C, A and B: complete retained 200M
histories with complete coarse measurements), count weights, >= 2 blocks; technical gaps pending repair, never
dropped; unavailable rows enter Holm as p = 1; H-C decided at its reached active level; the ecological family
bound as primary descriptive (no alpha). calib.py --eligibility restricts H-F / H-T calibration to Q200.

NUMERICAL FAILURES. Every bootstrap draw is validated: a failed or nonfinite estimate or SE makes the
analysis unavailable (with the failing draw); only a genuine zero SE with a finite estimate takes the
0 / +inf / -inf convention. A constant sample has se 0 exactly (mean_se).

CROSSED SOURCES (H.7). Bootstrap multiplicities m_w of the drawn root worlds: a within-world record
weighs m_w (not m_w^2), a cross-world record m_u m_v, a record against a frozen external reference
m_w (the reference: evolutionary multiplicity one). crossed_mean_draws returns resampled means only
(no studentized crossed test).

CALIBRATION ARITHMETIC (H.11, H.12). The one-sided Clopper-Pearson U95 = Beta^-1(0.95; k + 1, N - k)
(1 if k = N); a null rate passes iff U95 <= 0.02 (N = 1,000: at most 12 false positives). Development
critical value: the plus-one 0.99 order statistic. Model p-values (1 + #{null >= s}) / (N + 1), the
maximum over strata. CPU (H.12 as amended by D5, compute only, 2026-11-08: the ceiling 96 -> 240 CPU-h, the rest
of H.12 unchanged, the ledger the record): 24,000 x 36 s = 240 CPU-h; target (240 - 6) x 3600 / 24,000 =
35.1 s/panel.
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
BOUND_ALPHA = 0.01           # H.5's reported one-sided 99% lower bounds (fixed, not the decision level)
CPU_CEILING_H = 240.0         # (Annex amendment D5: was 96)
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
    if any(isinstance(x, float) and math.isnan(x) for x in null_scores):
        raise StatsError("a NaN null score")
    s = sorted(null_scores)
    return s[min(len(s), math.ceil(level * (len(s) + 1) - 1e-12)) - 1]


def model_p(s, strata):
    """max over strata of (1 + #{null >= s}) / (N + 1). A NaN observed score or null score is a numerical
    failure (StatsError: the analysis is unavailable), never the minimum p-value (#68 review 3)."""
    if s is None or (isinstance(s, float) and math.isnan(s)):
        raise StatsError("a NaN (or missing) observed score has no model p-value")
    if any(isinstance(x, float) and math.isnan(x) for v in strata.values() for x in v):
        raise StatsError("a NaN null score")
    return max((1 + sum(x >= s for x in v)) / (len(v) + 1) for v in strata.values())


def cpu_targets():
    return {"ceiling_cpu_s_per_panel": CPU_CEILING_H * 3600 / PANELS,
            "target_cpu_s_per_panel": (CPU_CEILING_H - CPU_RESERVE_H) * 3600 / PANELS}


# ================================================================== H-P / H-Q world resampling
def mean_se(values):
    """est() for a mean of per-world contributions: (mean, sd / sqrt(n)). A CONSTANT sample (every
    value identical, exactly) has se 0 exactly (#68 review 2: a rounded mean must not invent a tiny
    positive spread); otherwise the two-pass variance on the correctly rounded mean (math.fsum)."""
    n = len(values)
    if n == 0:
        raise StatsError("no values")
    first = values[0]
    if all(x == first for x in values):
        return float(first), 0.0
    m = math.fsum(values) / n
    v = math.fsum((x - m) ** 2 for x in values) / (n - 1) if n > 1 else 0.0
    return m, math.sqrt(v / n)


def _draw_ok(th, s):
    return isinstance(th, (int, float)) and isinstance(s, (int, float)) and math.isfinite(th) and math.isfinite(s) \
        and s >= 0


def _tstar(th, s, theta):
    """The studentized draw; a genuine zero SE (finite estimate) by the registered convention."""
    if s > 0:
        return (th - theta) / s
    return 0.0 if th == theta else (math.inf if th > theta else -math.inf)


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
    for b in range(draws):
        try:
            th, s = est([units[rng.below(n)] for _ in range(n)])
        except (ValueError, ArithmeticError, StatsError) as e:
            return {"available": False, "reason": f"bootstrap draw {b}: estimation failed: {e}", "failed_draw": b,
                    "estimate": theta}
        if not _draw_ok(th, s):                 # (#68 review 3: a failure, never a non-exceedance)
            return {"available": False, "reason": f"bootstrap draw {b}: a nonfinite estimate or SE ({th}, {s})",
                    "failed_draw": b, "estimate": theta}
        ts.append(_tstar(th, s, theta))
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
    try:
        loo = [est(units[:i] + units[i + 1:])[0] for i in range(n)]
        if not all(math.isfinite(x) for x in loo):
            raise StatsError("a nonfinite leave-one-out estimate")
        out["leave_one_out"] = {"min": min(loo), "max": max(loo), "max_influence": max(abs(x - theta) for x in loo)}
    except (ValueError, ArithmeticError, StatsError) as e:      # (a sensitivity: reported, never deciding)
        out["leave_one_out"] = {"available": False, "reason": str(e)}
    return out


def cluster_interval(units, est, draws=B_BOOT, rng=None, level=0.95):
    """Percentile and bootstrap-t intervals (the percentile one is secondary). A failed or nonfinite
    estimate (original or drawn) makes the interval unavailable."""
    n = len(units)
    rng = rng or rqlib.SplitMix64(0)
    theta, se = est(units)
    if not _draw_ok(theta, se):
        return {"available": False, "reason": "a nonfinite estimate or SE"}
    ths, ts = [], []
    for b in range(draws):
        th, s = est([units[rng.below(n)] for _ in range(n)])
        if not _draw_ok(th, s):
            return {"available": False, "reason": f"bootstrap draw {b}: a nonfinite estimate or SE", "failed_draw": b}
        ths.append(th)
        ts.append(_tstar(th, s, theta))
    a = (1.0 - level) / 2.0
    sth, sts = sorted(ths), sorted(ts)
    return {"available": True, "estimate": theta, "se": se, "level": level, "percentile": [Q(sth, a), Q(sth, 1 - a)],
            "bootstrap_t": [theta - Q(sts, 1 - a) * se, theta - Q(sts, a) * se], "draws": draws}


# ================================================================== H-C
def hc_block_deltas(slopes, worlds, with_weights=False):
    """slopes {world id: {"neural": beta_N, "scripted": beta_S}}; worlds: registry entries (id, treatment,
    block) -> (deltas {block: (D_A, D_B)} of the usable blocks, unusable {block: why}) [, weights {block:
    (w_A, w_B)}]. d_w = beta_N - beta_S; D_G,b = mean(d of the block's eligible C worlds) - mean(d of its
    eligible G worlds) (one or two controls per treatment: USER DECISIONS 2); a usable block has >= 1 C,
    >= 1 A and >= 1 B eligible world. The precision weight w_G,b = 1 / (1/n_C,b + 1/n_G,b) (a known
    constant given the eligibility pattern)."""
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
    deltas, unusable, weights = {}, {}, {}
    for b, ws in sorted(by.items()):
        cs = [d(w) for w in ws if w["treatment"] == "C" and d(w) is not None]
        g = {t: [d(w) for w in ws if w["treatment"] == t and d(w) is not None] for t in ("A", "B")}
        if not cs or not g["A"] or not g["B"]:
            unusable[b] = (f"{len(cs)} eligible C, {len(g['A'])} A, {len(g['B'])} B worlds with both slopes "
                           "(needs >= 1 C, >= 1 A and >= 1 B)")
            continue
        dc = sum(cs) / len(cs)
        deltas[b] = (dc - sum(g["A"]) / len(g["A"]), dc - sum(g["B"]) / len(g["B"]))
        weights[b] = tuple(1.0 / (1.0 / len(cs) + 1.0 / len(g[t])) for t in ("A", "B"))
    if with_weights:
        return deltas, unusable, weights
    return deltas, unusable


def t_stat(xs):
    """The one-sample t statistic (reported only)."""
    n = len(xs)
    m = sum(xs) / n
    v = sum((x - m) ** 2 for x in xs) / (n - 1) if n > 1 else 0.0
    if v <= 0.0:
        return 0.0 if m == 0 else math.copysign(math.inf, m)
    return m / math.sqrt(v / n)


def signflip_p(D, w=None):
    """The one-sided positive (weighted) Fisher-Pitman sign-flip p-value of T = sum w_b D_b:
    #{e: sum e_b w_b D_b >= T} / 2^n, by enumeration (ties count). w None: equal weights.
    TIES ARE EXACT (#68 review 12): sum e x >= sum x  <=>  sum over the flipped set I of x_b <= 0, and the
    sign of that sum is read from math.fsum (correctly rounded: its sign is the exact sum's), x_b =
    w_b D_b; the inversion (signflip_lower) uses the same rule, so p and the bound agree exactly."""
    n = len(D)
    w = [1.0] * n if w is None else list(w)
    x = [wi * di for wi, di in zip(w, D)]
    k = sum(math.fsum(x[i] for i in range(n) if mask >> i & 1) <= 0.0 for mask in range(2 ** n))
    return k, 2 ** n, k / 2 ** n


def signflip_lower(D, alpha=DETECT_ALPHA, w=None):
    """The exact one-sided 1 - alpha lower bound: sup{a: p(D - a) <= alpha} = the (k+1)-th smallest
    nonempty-subset (weighted) mean sum_I w_b D_b / sum_I w_b, k = floor(alpha 2^n) - 1; -inf if alpha
    is unattainable."""
    n = len(D)
    w = [1.0] * n if w is None else list(w)
    k = math.floor(alpha * 2 ** n + 1e-12) - 1
    if k < 0:
        return -math.inf
    means = sorted(math.fsum(w[i] * x for i, x in enumerate(D) if mask >> i & 1)
                   / math.fsum(w[i] for i in range(n) if mask >> i & 1) for mask in range(1, 2 ** n))
    return means[k]


def hc_test(deltas, alpha=DETECT_ALPHA, delta=DELTA_C, weights=None):
    """H-C's one-sided positive intersection-union sign-flip test (see the module doc), precision
    weighted (USER DECISIONS 2): T_G = sum_b w_G,b D_G,b, the estimate the weighted mean (weights
    normalized: the p-value does not depend on their scale). weights None: equal (== the precision
    weights of balanced intact blocks). alpha: the ACTIVE Holm level of H-C (its decision is Holm's)."""
    blocks = sorted(deltas)
    n = len(blocks)
    if n < 2:
        return {"available": False, "reason": f"{n} usable blocks", "n_blocks": n}
    DA = [deltas[b][0] for b in blocks]
    DB = [deltas[b][1] for b in blocks]
    WA = [1.0] * n if weights is None else [weights[b][0] for b in blocks]
    WB = [1.0] * n if weights is None else [weights[b][1] for b in blocks]
    WA = [x * n / sum(WA) for x in WA]
    WB = [x * n / sum(WB) for x in WB]
    kA, N, pA = signflip_p(DA, WA)
    kB, _, pB = signflip_p(DB, WB)
    eA = sum(w * x for w, x in zip(WA, DA)) / n
    eB = sum(w * x for w, x in zip(WB, DB)) / n
    pC = max(pA, pB)
    mA = signflip_p([x - delta for x in DA], WA)[2]
    mB = signflip_p([x - delta for x in DB], WB)[2]
    # H.5's REPORTED bounds are 99% whatever the decision level (#68 review 9); bounds at the active
    # decision level are reported beside them, with their own confidence level
    LA, LB = signflip_lower(DA, BOUND_ALPHA, WA), signflip_lower(DB, BOUND_ALPHA, WB)
    AA, AB = signflip_lower(DA, alpha, WA), signflip_lower(DB, alpha, WB)
    floor = 1.0 / N
    return {"available": True, "blocks": blocks, "n_blocks": n, "patterns": N, "alpha": alpha,
            "weights": {"A": WA, "B": WB},
            "estimate_A": eA, "estimate_B": eB, "t_A": t_stat(DA), "t_B": t_stat(DB),
            "tail_A": kA, "tail_B": kB, "p_A": pA, "p_B": pB, "p": pC, "p_floor": floor,
            "alpha_attainable": floor <= alpha, "reject_at_alpha": pC <= alpha and eA > 0 and eB > 0,
            "reject": pC <= alpha and eA > 0 and eB > 0,
            "material_points": {"A": eA >= delta, "B": eB >= delta},
            "p_material": max(mA, mB), "lower99": {"A": LA, "B": LB, "min": min(LA, LB), "confidence": 0.99},
            "lower_at_alpha": {"A": AA, "B": AB, "min": min(AA, AB), "confidence": 1.0 - alpha},
            "note": None if floor <= alpha else
            f"with {n} usable blocks the smallest attainable one-sided p is {floor:g} > {alpha}: H-C cannot reject "
            "at this level"}


# ================================================================== multiplicity
def holm(pvals, alpha=FAMILY_ALPHA, family=HYPOTHESES):
    """Holm step-down over the five primary hypotheses. pvals {hypothesis: p or None (unavailable)};
    an unavailable hypothesis keeps its row and enters as p = 1 (no alpha reallocation) -> {"adjusted",
    "reject", "unavailable"}."""
    m = len(family)
    p = {h: (1.0 if pvals.get(h) is None else float(pvals[h])) for h in family}
    if any(math.isnan(v) for v in p.values()):
        raise StatsError("a NaN p-value in the Holm family")
    order = sorted(family, key=lambda h: (p[h], family.index(h)))        # (the RAW step-down order)
    adj, run = {}, 0.0
    level, reached, going = {}, {}, True
    for i, h in enumerate(order):
        run = max(run, min(1.0, (m - i) * p[h]))
        adj[h] = run
        level[h] = alpha / (m - i)
        reached[h] = going                       # (every hypothesis before it was rejected)
        going = going and p[h] <= level[h]
    return {"adjusted": adj, "reject": {h: adj[h] <= alpha for h in family}, "raw": p, "order": order,
            "level": level, "reached": reached,
            "unavailable": sorted(h for h in family if pvals.get(h) is None), "alpha": alpha}


def active_level(h, hyp):
    """The Holm level at which hyp is tested: alpha / (m - i), i = its position in the RAW p-value
    step-down order (#68 review 1: adjusted p-values plateau and lose that order). Whether the step-down
    reached it at all is h["reached"][hyp]; the decision is always Holm's (family_decision)."""
    return h["level"][hyp]


def family_decision(h, hc=None):
    """The authoritative primary decisions: Holm's rejections (no nominal 0.01 flag substitutes); H-C
    additionally needs both weighted estimates positive (its one-sided intersection-union direction)."""
    out = dict(h["reject"])
    if "H-C" in out:
        out["H-C"] = bool(out["H-C"] and hc is not None and hc.get("available")
                          and hc["estimate_A"] > 0 and hc["estimate_B"] > 0)
    return out


def reciprocal_directional(h):
    """The headline needs both H-P and H-Q rejected under Holm; its p is max of their adjusted p."""
    return {"claim": h["reject"]["H-P"] and h["reject"]["H-Q"],
            "p": max(h["adjusted"]["H-P"], h["adjusted"]["H-Q"])}


# ================================================================== eligibility (Annex H D6 rules 26-27, 33; D7 36-38)
MIN_Q200 = 24
Q200_FAMILY = ("H-P", "H-Q", "H-F", "H-T")
ECOLOGY_SCHEMA = "finfolk.redqueen.ecology/1"
ELIGIBILITY_SCHEMA = "finfolk.redqueen.eligibility/1"
MASK_SCHEMA = "finfolk.redqueen.graphmask/2"
COARSE_T = tuple(range(0, 201, 5))           # (graph.py's coarse times: H-C's required 200M coarse measurements)
HT_GUARD = math.log(6 / 0.01)                # (H-T's registered guard log 600: transition.GUARD, its minimum c_T)


def complete_history(slot):
    """A slot's RETAINED attempt is a complete retained 200M history: evidenced alive through the registered end
    (observation "administrative" in worlds.py ecology: no terminal boundary, no stop, no technical end) and no
    predator refill (nothing after a refill establishes natural coexistence)."""
    o = (slot.get("attempts") or [{}])[-1]
    return o.get("observation") == "administrative" and not o.get("refill")


def ecology_problems(eco, registry, registry_sha256=None):
    """Why an ecological export (worlds.py ecology, #75) is not this registry's, or its Q200 not its own slots'
    (recomputed: every retained C history complete through the observed 200M endpoint, D6 rule 26) -> ([problem],
    the recomputed Q200)."""
    probs = []
    if eco.get("schema") != ECOLOGY_SCHEMA:
        return [f"ecology schema {eco.get('schema')!r}, expected {ECOLOGY_SCHEMA}"], []
    if registry_sha256 is not None and eco.get("registry_sha256") != registry_sha256:
        probs.append("the ecological export was made from another registry (registry_sha256)")
    slots = eco.get("slots") or {}
    reg = {w["id"]: w for w in registry["worlds"]}
    if set(slots) != set(reg):
        probs.append(f"its slots are not the registry's worlds ({sorted(set(slots) ^ set(reg))[:5]})")
    for w in sorted(set(slots) & set(reg)):
        if (slots[w].get("treatment"), slots[w].get("block")) != (reg[w]["treatment"], reg[w]["block"]):
            probs.append(f"{w}: another treatment / block than the registry's")
    q = sorted(w for w, s in slots.items() if s.get("treatment") == "C" and complete_history(s))
    if (eco.get("Q200") or {}).get("worlds") != q:
        probs.append("its Q200 is not its own slots' (recomputed: retained C histories complete through 200M)")
    return probs, q


ALL_T = tuple(range(0, 201))                 # (every graph time: the fine and reference observations H-F / H-T use)


def snapshots_sha256(mask, worlds):
    """The digest of the given worlds' SNAPSHOT IDENTITIES in a graphmask/2 (Codex #68 D6 r2 P2-2): per world its
    slot uuid and attempt uuid, every unavailable snapshot (its snapshot uuid and cause) and every available
    snapshot's verified archive sha256 (the bytes the observations were measured from)."""
    W, S = mask.get("worlds") or {}, mask.get("snapshots") or {}
    miss = sorted(set(worlds) - set(W))
    if miss:
        raise StatsError(f"{len(miss)} world(s) not in the mask: {miss[:4]}")
    un = {}
    for k, s in S.items():
        un.setdefault(s.get("world"), {})[k] = [s.get("snapshot"), s.get("status")]
    return rqlib.canonical_sha({w: {"uuid": W[w].get("uuid"), "attempt_uuid": W[w].get("attempt_uuid"),
                                    "available_sha256": W[w].get("available_sha256"), "unavailable": un.get(w, {})}
                                for w in sorted(worlds)})


def observation_provenance(mask, mask_sha256, worlds):
    """THE PROVENANCE a producer of observations (slopes, per-world recurrence analyses, epoch designs) stamps on
    them, for the worlds it measured (Codex #68 D6 r2 P2-2): the graph (the mask's graph.edges_sha256), the mask
    (its bytes' sha256) and those worlds' snapshot identities (snapshots_sha256). The eligibility record carries the
    same for each hypothesis's population (its "binding"); require_population compares them."""
    return {"graph_edges_sha256": (mask.get("graph") or {}).get("edges_sha256"), "mask_sha256": mask_sha256,
            "snapshots_sha256": snapshots_sha256(mask, worlds)}


def mask_gaps(mask, worlds, times=ALL_T):
    """{world: [(t, cause, why)]}: the snapshots at the given graph times a graphmask/2 excludes, per world."""
    out = {}
    if mask is None:
        return out
    if mask.get("schema") != MASK_SCHEMA:
        raise StatsError(f"mask schema {mask.get('schema')!r}, expected {MASK_SCHEMA}")
    S = mask.get("snapshots") or {}
    for w in worlds:
        g = [(t, S[k]["status"], S[k].get("why")) for t in times
             for k in [f"{w}:{1 if t == 0 else t * 1_000_000}"] if k in S]
        if g:
            out[w] = g
    return out


def hc_fit_status(s):
    """(status, why) of one world's H-C coarse fit record {"neural", "scripted", "complete"} (Codex #68 D6 P2-1):
    "ok" (both slopes finite AND the record certifies its complete required 200M coarse measurements); "missing"
    (no record), "failed" (a nonfinite or absent slope: a numerical failure) or "incomplete" (finite slopes alone do
    not establish complete measurements): the last three are technical, PENDING REPAIR, never an exclusion."""
    if not isinstance(s, dict):
        return "missing", "no H-C fit record"
    if not all(isinstance(s.get(k), (int, float)) and not isinstance(s.get(k), bool) and math.isfinite(s[k])
               for k in ("neural", "scripted")):
        return "failed", "its H-C fit failed (a missing or nonfinite slope)"
    if s.get("complete") is not True:
        return "incomplete", "its required 200M coarse measurements are not certified complete"
    return "ok", None


def eligibility(eco, registry, hc_slopes, registry_sha256=None, mask=None, eco_sha256=None, min_q200=MIN_Q200,
                mask_sha256=None, hc_provenance=None):
    """THE AUTHORITATIVE ELIGIBILITY DISPATCHER (Annex H D6 rules 26-27 and 33; D7 rules 36-38) -> (the eligibility
    record, H-C's usable block deltas, their count weights), the last two STAMPED with the record's H-C binding
    (HCContrasts: decide refuses contrasts of another record, graph, mask or snapshots; Codex #68 D6 r3 P2-2).

      Q200 (D6 rule 26): every retained C history with continuous coexistence through the observed 200M endpoint
        (ecology_problems recomputes it from the export's slots). |Q200| >= min_q200 (24) is the availability
        safeguard of H-P, H-Q, H-F and H-T ONLY: below it their decisions are unavailable (their measurements and
        estimates stay descriptive); they all use the COMMON Q200 population (H-T in every epoch).
      H-C (D7 rules 36-38), independently of |Q200|: an ELIGIBLE world (any treatment) has a complete retained 200M
        history and a COMPLETE H-C fit (hc_fit_status "ok": finite slopes AND certified complete required 200M
        coarse measurements); a usable block has >= 1 eligible C, A and B (every eligible world averaged within its
        treatment; no control selected or replaced); the count-based precision weights a_G,b = (1/n_C,b +
        1/n_G,b)^-1, normalized per control type (hc_block_deltas, hc_test); >= 2 usable blocks, else unavailable;
        the lattice floor 2^-m. Its estimand is the weighted contrast conditional on the realized eligibility
        pattern.
      TECHNICAL gaps are reported and REPAIRED, never silently dropped (D6 rule 26; Codex #68 D6 P2-1 / P2-2): a
        complete-history world whose H-C fit is missing, failed or incomplete, or whose snapshots the bound mask
        excludes (H-C: at its coarse times; H-P/H-Q/H-F/H-T: at ANY graph time, the fine and reference
        observations included) makes the decisions that need it unavailable ("pending repair") until then.
      The MASK, when given, is bound by its bytes' sha256 (mask_sha256, required) and checked against its own
        evidence (graph.mask_evidence_problems) and the export's registry. Each hypothesis then carries its
        BINDING (observation_provenance of its population: the graph, the mask, the snapshot identities); the H-C
        fits must carry theirs (hc_provenance, required with a mask: observations of another graph, mask or
        snapshots with the same world ids are refused; Codex #68 D6 r2 P2-2), and every analysis result must be
        bound to the record (require_population; decide refuses an unbound result).
      The ecological family is a mandatory primary DESCRIPTIVE family (D6 rule 33): its export is bound here
        (eco_sha256, its 200M first-attempt survival per treatment) and consumes no alpha."""
    probs, q = ecology_problems(eco, registry, registry_sha256)
    if probs:
        raise StatsError("the ecological export is not this registry's: " + "; ".join(probs[:5]))
    mrec = None
    if mask is not None:
        import graph as graphlib                      # (the shared mask validator)
        if not (isinstance(mask_sha256, str) and len(mask_sha256) == 64):
            raise StatsError("a mask is bound by its bytes' sha256 (mask_sha256)")
        validator = getattr(graphlib, "mask_evidence_problems", None)
        if validator is None:                         # (#77's validator: never a half-checked mask)
            raise StatsError("binding a mask needs graph.mask_evidence_problems (#77's shared mask validator)")
        mp = validator(mask)
        if mp:
            raise StatsError("the mask is not consistent with its own evidence: " + "; ".join(mp[:3]))
        if (mask.get("registry") or {}).get("sha256") != eco.get("registry_sha256"):
            raise StatsError("the mask binds another registry than the ecological export")
        mrec = {"sha256": mask_sha256, "graph_edges_sha256": (mask.get("graph") or {}).get("edges_sha256"),
                "graph_namespace": (mask.get("graph") or {}).get("namespace"),
                "registry_sha256": (mask.get("registry") or {}).get("sha256")}
        if hc_provenance != observation_provenance(mask, mask_sha256, sorted(hc_slopes)):
            raise StatsError("the H-C fits' provenance is not the bound graph / mask / snapshot identities "
                             "(hc_provenance: observation_provenance of the fitted worlds)")
    slots = eco["slots"]
    reg = registry["worlds"]
    complete = {w["id"] for w in reg if complete_history(slots[w["id"]])}
    gaps_all = mask_gaps(mask, sorted(complete), ALL_T)
    gaps = mask_gaps(mask, sorted(complete), COARSE_T)
    fit = {w: hc_fit_status(hc_slopes.get(w)) for w in sorted(complete)}
    tech = {w: g for w, g in gaps_all.items() if any(c in ("technical", "pending") for _, c, _ in g)}
    eligible = {w for w in complete if fit[w][0] == "ok" and w not in gaps}
    why = {}
    for w in reg:
        o = (slots[w["id"]].get("attempts") or [{}])[-1]
        if w["id"] not in complete:
            why[w["id"]] = f"no complete retained 200M history (observation {o.get('observation')}" + (
                ", a refill)" if o.get("refill") else ")")
        elif w["id"] in gaps:
            why[w["id"]] = "its required coarse measurements are excluded by the mask: " + "; ".join(
                f"t {t} {c}" for t, c, _ in gaps[w["id"]][:3])
        elif fit[w["id"]][0] != "ok":
            why[w["id"]] = f"{fit[w['id']][1]}: pending repair"
    deltas, unusable, weights = hc_block_deltas({w: hc_slopes[w] for w in eligible}, reg, with_weights=True)
    counts = {}
    for w in reg:
        c = counts.setdefault(w["block"], {"C": 0, "A": 0, "B": 0})
        c[w["treatment"]] += w["id"] in eligible
    nq = len(q)
    q_tech = sorted(set(q) & set(tech))
    hyp = {}
    for h in Q200_FAMILY:
        r = None if nq >= min_q200 else (f"|Q200| = {nq} < {min_q200}: the decision is unavailable (its measurements "
                                         "and estimates stay descriptive; D6 rule 26)")
        if r is None and q_tech:
            r = f"technical gaps in {len(q_tech)} Q200 world(s) ({q_tech[:4]}): pending repair, never dropped"
        hyp[h] = {"population": "Q200", "worlds": q, "available": r is None, "reason": r,
                  "binding": None if mask is None else observation_provenance(mask, mask_sha256, q)}
    hc_tech = sorted(set(w for w, g in gaps.items() if any(c in ("technical", "pending") for _, c, _ in g))
                     | {w for w in complete if fit[w][0] != "ok"})
    m = len(deltas)
    r = None if m >= 2 else f"{m} usable block(s): the registered routine needs at least two (D7 rule 38)"
    if r is None and hc_tech:
        r = (f"technical gaps or missing / failed / incomplete H-C fits in {len(hc_tech)} otherwise complete world(s) "
             f"({hc_tech[:4]}): pending repair, never dropped")
    a = {b: {"A": weights[b][0], "B": weights[b][1]} for b in sorted(weights)}
    norm = {G: {b: a[b][G] / sum(x[G] for x in a.values()) for b in a} for G in ("A", "B")} if a else {}
    hyp["H-C"] = {"population": "usable blocks", "worlds": sorted(eligible), "available": r is None, "reason": r,
                  "binding": None if mask is None else observation_provenance(mask, mask_sha256, sorted(eligible)),
                  "usable_blocks": sorted(deltas),
                  "unusable_blocks": {str(b): v for b, v in sorted(unusable.items())}, "n_blocks": m,
                  "p_floor": (2.0 ** -m) if m else None, "counts": {str(b): c for b, c in sorted(counts.items())},
                  "fits": {w: s for w, (s, _) in sorted(fit.items()) if s != "ok"},
                  "weights_a": {str(b): v for b, v in a.items()},
                  "weights_normalized": {G: {str(b): v for b, v in d.items()} for G, d in norm.items()},
                  "estimand": "the count-weighted C - G contrast among eligible complete-history worlds of the usable "
                              "blocks, conditional on the realized eligibility pattern (D7 rule 37)"}
    T = eco.get("primary_horizon")
    eco_rec = {"sha256": eco_sha256, "registry_sha256": eco.get("registry_sha256"), "primary_horizon": T,
               "first_attempt_200M": {t: (((s.get("first_attempt") or {}).get("survival") or {}).get(str(T)))
                                      for t, s in sorted((eco.get("summary") or {}).items())},
               "alpha": "none: the ecological family is primary descriptive (D6 rule 33)"}
    rec = {"schema": ELIGIBILITY_SCHEMA, "ecology": eco_rec,
           "Q200": {"worlds": q, "count": nq, "minimum": min_q200, "available": nq >= min_q200},
           "eligible": {t: sorted(w["id"] for w in reg if w["treatment"] == t and w["id"] in eligible) for t in "CAB"},
           "ineligible": dict(sorted(why.items())),
           "technical_gaps": {w: [list(x) for x in g] for w, g in sorted(tech.items())},
           "mask": mrec, "hypotheses": hyp}
    return rec, _stamp_contrasts(rec, deltas), _stamp_contrasts(rec, weights)


def record_sha256(elig):
    """The eligibility record's identity: the sha256 of its canonical JSON (the same after a file round trip)."""
    return rqlib.canonical_sha(elig)


CONTRASTS_SCHEMA = "finfolk.redqueen.annexH.hc_contrasts/1"


class HCContrasts(dict):
    """H-C's block contrasts {block: (delta_A, delta_B)} or count weights {block: (a_A, a_B)} STAMPED at production
    (Codex #68 D6 r3 P2-2; r4): `binding` is the record's result_binding for H-C (the record's identity, the hypothesis
    and the bound graph / mask / snapshot provenance of its eligible worlds), `digest` the sha256 of the binding and
    the content as produced. Only stats.eligibility issues a stamp (_stamp_contrasts). A plain dict, a copy (dict(x))
    or json.dumps(x) carries none, so decide refuses it. to_json() is the serializable form: the content (string
    block keys) with the producer's stamp unchanged; restore_hc_contrasts validates it and returns it stamped."""
    binding = None
    digest = None

    def to_json(self):
        return {"schema": CONTRASTS_SCHEMA, "blocks": {str(b): list(v) for b, v in self.items()},
                "binding": self.binding, "digest": self.digest}


def contrasts_sha256(x, binding):
    """The digest of a stamped contrast set: the sha256 of the canonical JSON of its binding and its content
    ({block: [A, B]}), so a changed binding or changed values no longer match the stamp's digest."""
    return rqlib.canonical_sha({"binding": binding, "blocks": {str(b): list(v) for b, v in x.items()}})


def _stamp_contrasts(elig, x):
    """The PRODUCER's stamp (stats.eligibility only, for the record it has just built): x as HCContrasts stamped with
    elig's H-C binding and the digest of that binding and x. Private: a restoration never issues a stamp."""
    out = HCContrasts(x)
    out.binding = result_binding(elig, "H-C")
    out.digest = contrasts_sha256(x, out.binding)
    return out


def _check_contrasts(elig, name, x):
    """StatsError unless x (H-C's `name`) is an HCContrasts stamped with THIS record's H-C binding, whose digest still
    matches its binding and content, over exactly the record's usable blocks."""
    e = (elig.get("hypotheses") or {}).get("H-C") or {}
    if not isinstance(x, HCContrasts) or x.binding != result_binding(elig, "H-C"):
        raise StatsError(f"H-C's {name} are not bound to this eligibility record (computed without it, or from "
                         "another graph / mask / snapshot identities): stats.eligibility / restore_hc_contrasts")
    try:
        ok = x.digest == contrasts_sha256(x, x.binding)
    except (TypeError, ValueError):
        ok = False
    if not ok:
        raise StatsError(f"H-C's {name} changed after they were produced (the stamp's digest does not match)")
    if set(x) != set(e.get("usable_blocks") or []):
        raise StatsError(f"H-C's {name} are not over the record's usable blocks")


def require_contrasts(elig, deltas, weights):
    """The decision-side check of H-C's contrasts (Codex #68 D6 r3 P2-2): both the block deltas and the count weights
    must be stamped with THIS record's H-C binding (not another record's, graph's, mask's or snapshots'), unchanged
    since they were produced, and over exactly the record's usable blocks; StatsError otherwise. decide calls it
    before either hc_test."""
    for name, x in (("deltas", deltas), ("weights", weights)):
        _check_contrasts(elig, name, x)


def _block_key(k):
    """A block id as an int: an int, or the string json.dumps makes of one; None otherwise."""
    if isinstance(k, bool):
        return None
    if isinstance(k, int):
        return k
    return int(k) if isinstance(k, str) and k.isascii() and k.isdigit() and str(int(k)) == k else None


def _restore_contrasts(elig, name, saved):
    if isinstance(saved, HCContrasts):
        saved = saved.to_json()
    if not (isinstance(saved, dict) and saved.get("schema") == CONTRASTS_SCHEMA and isinstance(saved.get("blocks"), dict)):
        raise StatsError(f"H-C's {name} are not a stamped contrasts document (HCContrasts.to_json): a bare dict, or "
                         "json.dumps of one, carries no producer stamp")
    blocks = {}
    for k, v in saved["blocks"].items():
        b = _block_key(k)
        if b is None or b in blocks or not (isinstance(v, (list, tuple)) and len(v) == 2 and all(
                isinstance(y, (int, float)) and not isinstance(y, bool) and math.isfinite(y) for y in v)):
            raise StatsError(f"H-C's {name}: block {k!r} is not a block id with a finite (A, B) pair, or is repeated")
        blocks[b] = tuple(v)
    out = HCContrasts(blocks)
    out.binding, out.digest = saved.get("binding"), saved.get("digest")      # (the PRODUCER's stamp, retained)
    _check_contrasts(elig, name, out)
    return out


def restore_hc_contrasts(elig, deltas, weights):
    """Restore H-C contrasts from a cache -> (deltas, weights) as HCContrasts (Codex #68 D6 r4 P2-2). Each input is
    an HCContrasts or its serialized to_json() document, which carries the PRODUCER's binding and digest; the
    restoration RETAINS them and validates them against the record: the binding must be this record's H-C binding,
    the digest must still match the binding and the content (string block keys from a JSON round trip are
    normalized to ints first), the blocks must be the record's usable blocks. A conflicting or altered stamp, a bare
    dict or another record's contrasts is refused; no stamp is ever issued from the record's metadata."""
    return _restore_contrasts(elig, "deltas", deltas), _restore_contrasts(elig, "weights", weights)


def result_binding(elig, hyp):
    """The binding an analysis result of hyp must carry to enter decide: the record's identity, the hypothesis and
    its population's provenance (the graph, the mask, the snapshot identities; None without a bound mask)."""
    return {"eligibility_sha256": record_sha256(elig), "hypothesis": hyp,
            "provenance": ((elig.get("hypotheses") or {}).get(hyp) or {}).get("binding")}


def require_population(elig, hyp, worlds, provenance=None):
    """The analysis-side binding (Codex #68 D6 P2-2; r2): an analysis of `hyp` runs only when the dispatcher made it
    available, on EXACTLY its population (Q200 for H-P / H-Q / H-F / H-T, the eligible worlds for H-C), from
    observations whose PROVENANCE (observation_provenance: the graph, the mask, the population's snapshot
    identities) is the record's binding of hyp: observations of another graph, mask or snapshots with the same world
    ids are refused. An available hypothesis has no technical gap in any of its worlds at any graph time, so its
    observations are the bound mask's available ones. -> the result binding (result_binding) the analysis stamps on
    its result; StatsError otherwise. backbone.directional_test, recurrence.hf and transition.ht call it when given
    the eligibility record; decide refuses a result without it."""
    if elig.get("schema") != ELIGIBILITY_SCHEMA:
        raise StatsError("not an eligibility record (stats.eligibility)")
    e = (elig.get("hypotheses") or {}).get(hyp)
    if e is None or not e.get("available"):
        raise StatsError(f"{hyp} is unavailable under the eligibility record: {(e or {}).get('reason')}")
    if sorted(worlds) != sorted(e.get("worlds") or []):
        raise StatsError(f"{hyp}: the analysis's worlds are not its registered population ({len(worlds)} vs "
                         f"{len(e.get('worlds') or [])})")
    if provenance != e.get("binding"):
        raise StatsError(f"{hyp}: the observations' provenance is not the record's bound graph / mask / snapshot "
                         "identities (observation_provenance)")
    return result_binding(elig, hyp)


def family_p(h, r):
    """(p, why) of an ANALYSIS RESULT for the five-row family (Codex #68 D6 P2-4; p None: unavailable, p = 1 in Holm):
    the result must be available; H-P / H-Q: the cluster test's p (stats.cluster_test via backbone); H-F: hf_decision's
    calibrated result (c_F and p_F present), its p the model p-value p_F only when S_F exceeds the development
    critical value c_F (else 1: the critical-value requirement is preserved); H-T: transition.ht's result with its
    frozen critical value c_T (calibrated, AT LEAST the registered guard HT_GUARD = log 600: a smaller c_T is refused,
    Codex #68 D6 r2 P2-4) and p_model, its p p_model only when T_T exceeds c_T."""
    def num(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    if not isinstance(r, dict):
        return None, "no result (an unrun analysis: unavailable)"
    if r.get("available") is not True:
        return None, f"the analysis is unavailable: {r.get('reason') or r.get('reasons') or r.get('failure')}"
    if h in ("H-P", "H-Q"):
        p = r.get("p")
        return (float(p), None) if num(p) and 0 <= p <= 1 else (None, "no valid p-value")
    if h == "H-F":
        if not (num(r.get("c_F")) and num(r.get("p_F")) and num(r.get("S_F"))):
            return None, "the H-F result carries no calibrated critical value / model p-value (p = 1 in Holm)"
        return (float(r["p_F"]) if r["S_F"] > r["c_F"] else 1.0), None
    if h == "H-T":
        if not (num(r.get("c_T")) and num(r.get("p_model")) and num(r.get("T_T"))):
            return None, "the H-T result carries no frozen critical value / model p-value (p = 1 in Holm)"
        if r["c_T"] < HT_GUARD:
            return None, f"the H-T critical value {r['c_T']:g} is below the registered guard log 600 (p = 1 in Holm)"
        return (float(r["p_model"]) if r["T_T"] > r["c_T"] else 1.0), None
    return None, f"unknown hypothesis {h}"


def decide(elig, results, deltas, weights, alpha=FAMILY_ALPHA):
    """The five-row confirmatory decision from the dispatcher's record (D6 rule 33): results {h: the analysis's own
    result + "worlds" + "binding"} for H-P / H-Q / H-F / H-T enter ONLY when the dispatcher made h available, the
    result is BOUND to this record (its "binding" is result_binding: computed through require_population from
    observations of the bound graph / mask / snapshots; an unbound result is refused, Codex #68 D6 r2 P2-2), it is
    available with its calibration (family_p: H-F's critical value, H-T's frozen critical value and guard) and h
    was computed on exactly the common Q200 population (StatsError otherwise: a decision on another population is
    never accepted); every unavailable row keeps its row and enters Holm as p = 1 (holm); H-C's p is the
    count-weighted intersection-union test's (hc_test) of the block deltas and weights, which must be this record's
    stamped contrasts (require_contrasts, before either hc_test: contrasts of another graph / mask / snapshots, or
    unstamped or altered ones, are refused; Codex #68 D6 r3 P2-2), and H-C is then decided at its REACHED ACTIVE
    Holm level (its bounds at that level beside the fixed 99% ones); family_decision is authoritative."""
    pv, why = {}, {}
    for h in Q200_FAMILY:
        e, r = elig["hypotheses"][h], results.get(h)
        if not e["available"]:
            pv[h], why[h] = None, e["reason"]
            continue
        if isinstance(r, dict) and r.get("available") is True and sorted(r.get("worlds") or []) != elig["Q200"]["worlds"]:
            raise StatsError(f"{h} was computed on another population than the common Q200 ({len(r.get('worlds') or [])} "
                             f"worlds, Q200 has {elig['Q200']['count']})")
        if isinstance(r, dict) and r.get("available") is True and r.get("binding") != result_binding(elig, h):
            raise StatsError(f"{h}'s result is not bound to this eligibility record (computed without it, or from "
                             "another graph / mask / snapshot identities): require_population")
        pv[h], why_h = family_p(h, r)
        if why_h:
            why[h] = why_h
    e = elig["hypotheses"]["H-C"]
    if e["available"]:
        require_contrasts(elig, deltas, weights)        # (Codex #68 D6 r3 P2-2: before either hc_test)
    hc = hc_test(deltas, DETECT_ALPHA, weights=weights) if e["available"] else {"available": False, "reason": e["reason"]}
    if not hc.get("available"):
        pv["H-C"], why["H-C"] = None, hc.get("reason") or e["reason"]
    else:
        pv["H-C"] = hc["p"]
    hl = holm(pv, alpha)
    if hc.get("available"):
        hc = dict(hc_test(deltas, active_level(hl, "H-C"), weights=weights), reached=hl["reached"]["H-C"])
    return {"pvalues": pv, "unavailable": why, "holm": hl, "H-C": hc, "decision": family_decision(hl, hc),
            "reciprocal": reciprocal_directional(hl), "ecology": elig["ecology"], "Q200": elig["Q200"]}


# ================================================================== crossed sources (H.7)
def source_weight(m, u, v):
    """The bootstrap weight of a record between source worlds u and v (v None: a frozen reference):
    within-world m_u, cross-world m_u m_v, against a reference m_u."""
    if v is None or u == v:
        return m.get(u, 0)
    return m.get(u, 0) * m.get(v, 0)


def crossed_mean_draws(records, draws=B_BOOT, rng=None, undefined="fail"):
    """Resampled weighted means of records [(prey world, predator world or None, value)]: the union of
    root worlds drawn once per draw, each record weighted by source_weight -> (full mean, [means]).
    A draw whose records all weigh 0 (e.g. one edge w1 -> w2 and a draw of w1 twice) has NO mean: the
    draw vector is never silently shortened (#68 review 10). undefined="fail": StatsError (the analysis
    is unavailable); "-inf": the draw is kept as -inf (the prospectively registered treatment for a
    LOWER bound: an undefined draw can only lower it, as recovery.crossed_lb does)."""
    if undefined not in ("fail", "-inf"):
        raise StatsError(f"undefined={undefined!r}")
    ws = sorted({u for u, _, _ in records} | {v for _, v, _ in records if v is not None})
    full = sum(x for _, _, x in records) / len(records)
    rng = rng or rqlib.SplitMix64(0)
    out = []
    for b in range(draws):
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
        elif undefined == "-inf":
            out.append(-math.inf)
        else:
            raise StatsError(f"crossed draw {b}: every record weighs 0 (an undefined resampled mean)")
    return full, out

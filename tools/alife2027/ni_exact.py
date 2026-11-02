#!/usr/bin/env python3
"""ni_exact.py: the exact unconditional paired test for a difference of two
paired proportions (protocol v2, H3: C1 vs A1 no-rescue, margin 3/20).

Data: n seed pairs; b = #(C1 succeeds, reference fails), c = #(C1 fails,
reference succeeds). Parameters: p10, p01; delta = p10 - p01; q = p10 + p01
in [|delta|, 1]. H0: delta <= delta0 (NI: delta0 = -margin) vs H1: delta > delta0.

ORDERING. Tables (u, v) are ranked by a statistic T; the p-value is the
supremum over the composite null of P(T(U, V) >= T(b, c)), exact (no
asymptotics: T only orders the tables). Two orderings:
  "score"       (registered default) Tango's score statistic for delta0,
                (u - v - n delta0) / sqrt(n (2 p01~ + delta0 (1 - delta0))),
                p01~ the restricted MLE of p01 under delta = delta0
  "difference"  T = u - v (the v1 brief's choice). Kept for comparison: its
                region ignores the observed discordance, so the supremum is
                driven by q near 1 and the test has almost no power at the
                discordance rates this study expects (n = 128: it needs
                b - c >= 4 whatever c is).
Tables within 1e-9 of the observed score count as at least as extreme
(inclusive, conservative: floating ties can only enlarge the region).

LEAST FAVOURABLE NULL. At fixed q, raising delta moves discordant mass from V
to U. If the rejection region is closed under (u, v) -> (u + 1, v - 1) --
CHECKED for every region used (region_closed) -- every rejection probability
is nondecreasing in delta at fixed q, so the supremum over delta <= delta0
lies on delta = delta0 and only q in [|delta0|, 1] remains a nuisance.

CERTIFIED SUPREMUM. With q = |delta| + (1 - |delta|) t, t in [0, 1], the
rejection probability is a degree-n polynomial in t whose Bernstein
coefficients are exact probabilities (each pair "active" with probability t;
for delta <= 0 an active pair is U with probability (1 + delta)/2, else V; an
inactive one is V with probability |delta|, else concordant):
    beta_k = P((X, k - X + Y) in S),  X ~ Bin(k, (1 + delta)/2), Y ~ Bin(n - k, |delta|)
(delta > 0 by mirroring: swap u and v, delta -> -delta). The coefficients are
integers over one common denominator; branch-and-bound with exact de
Casteljau midpoint subdivision (dyadic, so they stay integers) bounds the
maximum from above (largest coefficient on each piece) and below (midpoint
values). No floating point enters the certificate; the reported p-value is
the upper bound (gap <= 1e-10 by default), so an unresolved threshold cannot
cause a rejection.

    python3 tools/alife2027/ni_exact.py pvalue N B C [--margin 3/20] [--ordering score|difference]
    python3 tools/alife2027/ni_exact.py bounds N B C [--alpha 1/40] [--ordering ...]
    python3 tools/alife2027/ni_exact.py power N P10 P01 [--alpha 1/40] [--margin 3/20] [--ordering ...]
"""
from __future__ import annotations

import heapq
import math
import sys
from fractions import Fraction

GAP = Fraction(1, 10 ** 10)
TIE = 1e-9


# ---- orderings and regions -----------------------------------------------------------
def score_z(n, u, v, d0):
    """Tango's score statistic for H0: p10 - p01 = d0 (float)."""
    d0 = float(d0)
    bq = (u + v) + d0 * (u - v - 2 * n)
    disc = bq * bq + 8.0 * n * v * d0 * (1.0 - d0)
    x = (bq + math.sqrt(max(disc, 0.0))) / (4.0 * n)   # restricted MLE of p01
    x = max(x, max(0.0, -d0))
    var = n * (2.0 * x + d0 * (1.0 - d0))
    num = (u - v) - n * d0
    if var <= 0.0:
        return 0.0 if num == 0 else math.copysign(math.inf, num)
    return num / math.sqrt(var)


def region(n, b, c, d0, ordering):
    """The tables at least as extreme as (b, c): inS[u][v] for u + v <= n."""
    if ordering == "difference":
        d = b - c
        return [[(u - v) >= d for v in range(n - u + 1)] for u in range(n + 1)]
    if ordering == "score":
        z = score_z(n, b, c, d0)
        return [[score_z(n, u, v, d0) >= z - TIE for v in range(n - u + 1)] for u in range(n + 1)]
    raise ValueError("ordering is score or difference")


def region_closed(n, inS):
    """S closed under (u, v) -> (u + 1, v - 1): the least-favourable-null condition."""
    for u in range(n):
        for v in range(1, n - u + 1):
            if inS[u][v] and not inS[u + 1][v - 1]:
                return False
    return True


def _intervals(n, inS):
    """Per u, the contiguous v-range [lo, hi] of S (None if empty); raises if not contiguous."""
    out = []
    for u in range(n + 1):
        vs = [v for v in range(n - u + 1) if inS[u][v]]
        if not vs:
            out.append(None)
            continue
        if vs[-1] - vs[0] + 1 != len(vs):
            raise ArithmeticError(f"region not contiguous in v at u = {u}")
        out.append((vs[0], vs[-1]))
    return out


def region_coefficients(n, delta, inS):
    """(M, L): the rejection probability's Bernstein coefficients beta_k = M[k] / L."""
    delta = Fraction(delta)
    if not -1 <= delta <= 1:
        raise ValueError("delta outside [-1, 1]")
    if delta > 0:   # mirror: (u, v) -> (v, u), delta -> -delta
        inS = [[inS[v][u] if u <= n - v else False for v in range(n - u + 1)] for u in range(n + 1)]
        delta = -delta
    iv = _intervals(n, inS)
    p, q = delta.numerator, delta.denominator   # p <= 0
    ap, am = q + p, q - p          # active: U w.p. ap / 2q, V w.p. am / 2q
    mp, mq = -p, q + p             # inactive: V w.p. mp / q, concordant w.p. mq / q
    L = (2 * q) ** n
    M = []
    for k in range(n + 1):
        r = n - k
        pre = [0]
        for y in range(r + 1):
            pre.append(pre[-1] + math.comb(r, y) * mp ** y * mq ** (r - y))
        tot = 0
        for x in range(k + 1):
            if iv[x] is None:
                continue
            xw = math.comb(k, x) * ap ** x * am ** (k - x)
            if xw == 0:
                continue
            lo = max(iv[x][0] - (k - x), 0)     # v = (k - x) + y in [lo_v, hi_v]
            hi = min(iv[x][1] - (k - x), r)
            if hi >= lo:
                tot += xw * (pre[hi + 1] - pre[lo])
        M.append(tot * (1 << r))   # beta_k = tot / ((2q)^k q^r) = tot 2^r / (2q)^n
    return M, L


def tail_coefficients(n, d, delta):
    """P(U - V >= d) in Bernstein form (the difference ordering's region)."""
    return region_coefficients(n, delta, [[(u - v) >= d for v in range(n - u + 1)] for u in range(n + 1)])


def bernstein_eval(M, L, t):
    n = len(M) - 1
    t = Fraction(t)
    return sum(Fraction(M[k], L) * math.comb(n, k) * t ** k * (1 - t) ** (n - k) for k in range(n + 1))


def _split(c):
    """de Casteljau at 1/2 on integer coefficients: (left, right) on scale x 2^n."""
    n = len(c) - 1
    left, right = [0] * (n + 1), [0] * (n + 1)
    row = list(c)
    left[0] = row[0] << n
    right[n] = row[n] << n
    for j in range(1, n + 1):
        row = [row[i] + row[i + 1] for i in range(n + 1 - j)]
        left[j] = row[0] << (n - j)
        right[n - j] = row[-1] << (n - j)
    return left, right


def sup_poly(M, L, gap=GAP, alpha=None):
    """Certified (lo, hi, t_at_lo) for max over [0, 1] of sum M[k]/L B_k,n(t);
    with alpha, stops once the comparison with alpha is decided."""
    n = len(M) - 1
    lo = max(Fraction(M[0], L), Fraction(M[n], L))
    arg = Fraction(0) if M[0] >= M[n] else Fraction(1)
    hi = Fraction(max(M), L)
    if n == 0:
        return lo, lo, arg
    heap = [(-hi, 0, Fraction(0), Fraction(1), M, 0)]
    count = 1
    while heap:
        negub, _, a, b, c, e = heapq.heappop(heap)
        hi = -negub
        if hi <= lo or hi - lo <= gap or (alpha is not None and (hi <= alpha or lo > alpha)):
            break
        left, right = _split(c)
        e2 = e + n
        den = L * (1 << e2)
        mid = (a + b) / 2
        vm = Fraction(left[n], den)
        if vm > lo:
            lo, arg = vm, mid
        for ia, ib, cc in ((a, mid, left), (mid, b, right)):
            ub = Fraction(max(cc), den)
            if ub > lo:
                heapq.heappush(heap, (-ub, count, ia, ib, cc, e2))
                count += 1
    else:
        hi = lo
    return lo, max(hi, lo), arg


def sup_tail(n, d, delta, gap=GAP, alpha=None):
    """Difference ordering: certified sup over q of P_delta(U - V >= d)."""
    M, L = tail_coefficients(n, d, delta)
    return sup_poly(M, L, gap, alpha)


def null_sup(n, b, c, d0, ordering="score", gap=GAP, alpha=None):
    """Certified bounds on sup over the null delta <= d0 of P(T >= T(b, c))."""
    d0 = Fraction(d0)
    inS = region(n, b, c, d0, ordering)
    if not region_closed(n, inS):
        raise ArithmeticError("rejection region not closed under (u, v) -> (u + 1, v - 1): boundary not least favourable")
    M, L = region_coefficients(n, d0, inS)
    return sup_poly(M, L, gap, alpha)


def p_value(n, b, c, margin=Fraction(3, 20), ordering="score", gap=GAP):
    lo, hi, arg = null_sup(n, b, c, -Fraction(margin), ordering, gap)
    m = Fraction(margin)
    return {"p_upper": min(Fraction(1), hi), "p_lower": lo, "gap": hi - lo, "q_at_max": m + (1 - m) * arg,
            "ordering": ordering}


def rejects(n, b, c, d0, alpha, ordering="score"):
    lo, hi, _ = null_sup(n, b, c, d0, ordering, alpha=Fraction(alpha))
    if hi <= alpha:
        return True
    if lo > alpha:
        return False
    raise ArithmeticError("undecided")


def lower_bound(n, b, c, alpha=Fraction(1, 40), ordering="score", coarse=32, fine=1024):
    """One-sided (1 - alpha) lower confidence bound for delta, by inverting the
    test: the last REJECTED grid value of delta0 below the first one that is not
    rejected, scanning upward from -1 (step 1/coarse, then 1/fine inside the
    cell). Under the score ordering the p-value need not be monotone in delta0
    (the region moves with delta0), so no bisection; the result is conservative
    to the grid (it is <= the smallest non-rejected grid value). Returns -1 when
    nothing is rejected."""
    def rej(d0):
        return d0 > -1 and rejects(n, b, c, d0, alpha, ordering)
    step = Fraction(1, coarse)
    d0 = Fraction(-1)
    while d0 + step < 1 and rej(d0 + step):
        d0 += step
    if d0 == -1 and not rej(Fraction(-1) + Fraction(1, fine)):
        return Fraction(-1)
    f = Fraction(1, fine)
    while d0 + f < 1 and rej(d0 + f):
        d0 += f
    return d0


def bounds(n, b, c, alpha=Fraction(1, 40), ordering="score"):
    """(lower, upper) one-sided (1 - alpha) bounds; together a two-sided (1 - 2 alpha) interval."""
    return lower_bound(n, b, c, alpha, ordering), -lower_bound(n, c, b, alpha, ordering)


def trinomial_tail(n, d, p10, p01):
    """Exact P(U - V >= d)."""
    return region_prob(n, [[(u - v) >= d for v in range(n - u + 1)] for u in range(n + 1)], p10, p01)


def region_prob(n, inS, p10, p01):
    p10, p01 = Fraction(p10), Fraction(p01)
    pc = 1 - p10 - p01
    tot = Fraction(0)
    for u in range(n + 1):
        for v in range(n - u + 1):
            if inS[u][v]:
                tot += Fraction(math.factorial(n), math.factorial(u) * math.factorial(v) * math.factorial(n - u - v)) * \
                    p10 ** u * p01 ** v * pc ** (n - u - v)
    return tot


def rejection_region(n, alpha=Fraction(1, 40), margin=Fraction(3, 20), ordering="score"):
    """The tables (b, c) the registered test rejects (the p-value is monotone in
    the ordering statistic: binary search over the distinct statistic values)."""
    d0 = -Fraction(margin)
    tables = [(u, v) for u in range(n + 1) for v in range(n - u + 1)]
    stat = (lambda u, v: score_z(n, u, v, d0)) if ordering == "score" else (lambda u, v: u - v)
    vals = sorted({stat(u, v) for u, v in tables})
    rep = {}
    for u, v in tables:
        rep.setdefault(stat(u, v), (u, v))
    if not rejects(n, *rep[vals[-1]], d0, alpha, ordering):
        return None, [[False] * (n - u + 1) for u in range(n + 1)]
    lo, hi = -1, len(vals) - 1   # vals[hi] rejects
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if rejects(n, *rep[vals[mid]], d0, alpha, ordering):
            hi = mid
        else:
            lo = mid
    tcrit = vals[hi]
    tol = TIE if ordering == "score" else 0
    return tcrit, [[stat(u, v) >= tcrit - tol for v in range(n - u + 1)] for u in range(n + 1)]


def power(n, p10, p01, alpha=Fraction(1, 40), margin=Fraction(3, 20), ordering="score"):
    tcrit, inS = rejection_region(n, alpha, margin, ordering)
    return tcrit, region_prob(n, inS, p10, p01)


def main():
    a = sys.argv
    opt = lambda k, dflt: Fraction(a[a.index(k) + 1]) if k in a else dflt  # noqa: E731
    margin, alpha = opt("--margin", Fraction(3, 20)), opt("--alpha", Fraction(1, 40))
    ordering = a[a.index("--ordering") + 1] if "--ordering" in a else "score"
    if len(a) >= 5 and a[1] == "pvalue":
        r = p_value(int(a[2]), int(a[3]), int(a[4]), margin, ordering)
        print(f"{ordering}: p <= {float(r['p_upper']):.12g} (lower {float(r['p_lower']):.12g}, gap {float(r['gap']):.2e}, "
              f"q* ~ {float(r['q_at_max']):.6f})")
        return 0
    if len(a) >= 5 and a[1] == "bounds":
        lo, hi = bounds(int(a[2]), int(a[3]), int(a[4]), alpha, ordering)
        print(f"{ordering}: {float(1 - alpha):.4g} lower {float(lo):.9f}  upper {float(hi):.9f}")
        return 0
    if len(a) >= 5 and a[1] == "power":
        n = int(a[2])
        tcrit, pw = power(n, Fraction(a[3]), Fraction(a[4]), alpha, margin, ordering)
        print(f"{ordering}: n {n}, reject when T >= {tcrit}; power {float(pw):.6f}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())

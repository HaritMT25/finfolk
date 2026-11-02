"""finstats.py: the statistics the ALIFE 2027 analysis uses, Python stdlib only.

Everything a registered number depends on lives here so it can be tested in
one place (tests/alife2027/test_finstats.py):

  PCG32            the reference PCG32 XSH-RR generator (seed lists, bootstrap)
  mean/var/sd/...  sample moments (ddof 1)
  t_cdf/t_ppf      Student t via the regularized incomplete beta function
  paired_t         one-sample t on seed-level differences / contrasts
  pairing_gain     G = (s_a^2 + s_b^2) / s_{a-b}^2 with explicit degeneracy
  bootstrap        whole-seed percentile bootstrap (linear interpolation)
  holm             Holm step-down adjusted p-values
  mcnemar_greater  exact one-sided McNemar (conditional binomial)

The exact unconditional paired non-inferiority test is in ni_exact.py.
No numpy / scipy: the analysis must run on a bare python3 (3.10+).
"""
from __future__ import annotations

import math
from fractions import Fraction
from typing import Callable, Iterable, Sequence

MASK64 = (1 << 64) - 1
MASK32 = (1 << 32) - 1


class PCG32:
    """pcg32 XSH-RR, as pcg_basic.c (pcg32_srandom_r / pcg32_random_r /
    pcg32_boundedrand_r). Reference vector: seed (42, 54) gives
    0xa15c02b7 0x7b47f409 0xba1d3330 0x83d2f293 0xbfa4784b 0xcbed606e."""

    def __init__(self, initstate: int, initseq: int):
        self.state = 0
        self.inc = ((initseq << 1) | 1) & MASK64
        self.next_u32()
        self.state = (self.state + (initstate & MASK64)) & MASK64
        self.next_u32()

    def next_u32(self) -> int:
        old = self.state
        self.state = (old * 6364136223846793005 + self.inc) & MASK64
        xorshifted = (((old >> 18) ^ old) >> 27) & MASK32
        rot = old >> 59
        return ((xorshifted >> rot) | (xorshifted << ((-rot) & 31))) & MASK32

    def bounded(self, bound: int) -> int:
        """Uniform in [0, bound): rejection below 2^32 mod bound, then modulo."""
        if not 0 < bound <= MASK32 + 1:
            raise ValueError("bound out of range")
        threshold = ((MASK32 + 1) - bound) % bound
        while True:
            r = self.next_u32()
            if r >= threshold:
                return r % bound


# ---- moments -----------------------------------------------------------------------
def mean(x: Sequence[float]) -> float:
    if not x:
        raise ValueError("mean of nothing")
    return math.fsum(x) / len(x)


def var(x: Sequence[float]) -> float:
    """Sample variance (n - 1); 0.0 for a single value is NOT returned: n < 2 -> nan."""
    n = len(x)
    if n < 2:
        return math.nan
    if max(x) == min(x):   # exactly constant: the mean's rounding must not make it positive
        return 0.0
    m = mean(x)
    return math.fsum((v - m) ** 2 for v in x) / (n - 1)


def sd(x: Sequence[float]) -> float:
    v = var(x)
    return math.sqrt(v) if v == v else math.nan


def cov(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    if n != len(y):
        raise ValueError("length mismatch")
    if n < 2:
        return math.nan
    mx, my = mean(x), mean(y)
    return math.fsum((a - mx) * (b - my) for a, b in zip(x, y)) / (n - 1)


def corr(x: Sequence[float], y: Sequence[float]) -> float:
    """Pearson r; nan (undefined) when either side is constant."""
    vx, vy = var(x), var(y)
    if not (vx > 0 and vy > 0):
        return math.nan
    return cov(x, y) / math.sqrt(vx * vy)


def median(x: Sequence[float]) -> float:
    s = sorted(x)
    n = len(s)
    if n == 0:
        raise ValueError("median of nothing")
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def quantile(sorted_x: Sequence[float], q: float) -> float:
    """Linear interpolation between order statistics (Hyndman-Fan type 7,
    numpy's default 'linear'); sorted_x must be sorted."""
    n = len(sorted_x)
    if n == 0:
        raise ValueError("quantile of nothing")
    h = (n - 1) * q
    lo = math.floor(h)
    hi = min(lo + 1, n - 1)
    return sorted_x[lo] + (h - lo) * (sorted_x[hi] - sorted_x[lo])


# ---- Student t -----------------------------------------------------------------------
def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta (modified Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 10000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < 1e-16:
            return h
    raise ArithmeticError("betacf did not converge")


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    bt = math.exp(lbt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_sf(t: float, df: float) -> float:
    """P(T > t) for Student t with df degrees of freedom."""
    if math.isnan(t):
        return math.nan
    if math.isinf(t):
        return 0.0 if t > 0 else 1.0
    x = df / (df + t * t)
    tail = 0.5 * betainc(0.5 * df, 0.5, x)
    return tail if t > 0 else 1.0 - tail


def t_cdf(t: float, df: float) -> float:
    return 1.0 - t_sf(t, df)


def t_ppf(p: float, df: float) -> float:
    """Quantile of Student t (bisection on t_cdf; |error| < 1e-12)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    if p == 0.5:
        return 0.0
    lo, hi = -1.0, 1.0
    while t_cdf(lo, df) > p:
        lo *= 2.0
    while t_cdf(hi, df) < p:
        hi *= 2.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-13:
            break
    return 0.5 * (lo + hi)


def paired_t(d: Sequence[float], conf: float = 0.95) -> dict:
    """One-sample t on seed-level differences d (H0: mean 0).

    Returns mean, sd, se, t, df, p_greater (one-sided, H1 mean > 0),
    p_two_sided, the two-sided `conf` interval and the one-sided lower bound
    at (1 + conf) / 2. A constant d gets t = nan, p = 1 and degenerate=True
    (the registered constant-contrast policy)."""
    n = len(d)
    m = mean(d)
    s = sd(d)
    out = {"n": n, "mean": m, "sd": s, "degenerate": False}
    if n < 2 or not (s > 0):
        out.update(se=0.0 if n >= 2 else math.nan, t=math.nan, df=n - 1, p_greater=1.0, p_two_sided=1.0,
                   ci_low=m, ci_high=m, lower_one_sided=m, degenerate=True)
        return out
    se = s / math.sqrt(n)
    t = m / se
    df = n - 1
    q = t_ppf(0.5 + conf / 2.0, df)
    out.update(se=se, t=t, df=df, p_greater=t_sf(t, df), p_two_sided=min(1.0, 2.0 * t_sf(abs(t), df)),
               ci_low=m - q * se, ci_high=m + q * se, lower_one_sided=m - q * se)
    return out


# ---- pairing efficiency ----------------------------------------------------------------
def pairing_gain(a: Sequence[float], b: Sequence[float]) -> dict:
    """G = (s_a^2 + s_b^2) / s_{a-b}^2 and 1 - 1/G, with the registered
    degeneracy rules: zero denominator with a positive numerator -> G = inf;
    zero / zero -> undefined (None); a constant arm -> correlation undefined."""
    if len(a) != len(b):
        raise ValueError("unpaired input")
    d = [x - y for x, y in zip(a, b)]
    va, vb, vd = var(a), var(b), var(d)
    num = va + vb
    if vd > 0:
        g = num / vd
        state = "finite"
    elif num > 0:
        g = math.inf
        state = "infinite"
    else:
        g = None
        state = "undefined"
    red = None
    if state == "finite":
        red = 1.0 - 1.0 / g if g > 0 else None
    elif state == "infinite":
        red = 1.0
    return {"var_a": va, "var_b": vb, "var_d": vd, "sd_a": math.sqrt(va) if va == va else math.nan,
            "sd_b": math.sqrt(vb) if vb == vb else math.nan, "sd_d": math.sqrt(vd) if vd == vd else math.nan,
            "cov": cov(a, b), "corr": corr(a, b), "G": g, "G_state": state, "variance_reduction": red}


# ---- whole-seed bootstrap -----------------------------------------------------------------
def bootstrap(n_units: int, stat: Callable[[list], float | None], reps: int, rng: PCG32,
              conf: float = 0.95) -> dict:
    """Percentile bootstrap over whole units (seeds). stat(idx) gets a list of
    n_units resampled unit indices and returns a float, math.inf, or None
    (undefined). The interval is over finite values only; the infinite and
    undefined masses are reported and the interval is labelled conditional
    whenever either is nonzero."""
    finite, n_inf, n_undef = [], 0, 0
    for _ in range(reps):
        idx = [rng.bounded(n_units) for _ in range(n_units)]
        v = stat(idx)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            n_undef += 1
        elif math.isinf(v):
            n_inf += 1
        else:
            finite.append(v)
    finite.sort()
    lo_q, hi_q = (1.0 - conf) / 2.0, 1.0 - (1.0 - conf) / 2.0
    out = {"reps": reps, "finite": len(finite), "infinite_mass": n_inf / reps, "undefined_mass": n_undef / reps,
           "conditional": (n_inf + n_undef) > 0}
    if finite:
        out.update(low=quantile(finite, lo_q), high=quantile(finite, hi_q), median=quantile(finite, 0.5))
    else:
        out.update(low=None, high=None, median=None)
    return out


def holm(pvalues: Sequence[float]) -> list:
    """Holm step-down adjusted p-values, in the input order (monotone, capped at 1)."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: (pvalues[i], i))
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        v = min(1.0, (m - rank) * pvalues[i])
        running = max(running, v)
        adj[i] = running
    return adj


# ---- exact binomial / McNemar -------------------------------------------------------------
def binom_sf_exact(k: int, n: int, p: Fraction) -> Fraction:
    """P(X >= k) for X ~ Bin(n, p), exact rational."""
    if k <= 0:
        return Fraction(1)
    if k > n:
        return Fraction(0)
    return sum((Fraction(math.comb(n, j)) * p ** j * (1 - p) ** (n - j) for j in range(k, n + 1)), Fraction(0))


def mcnemar_greater(b: int, c: int) -> float:
    """Exact one-sided McNemar: P(Bin(b + c, 1/2) >= b); 1.0 with no discordant pairs."""
    m = b + c
    if m == 0:
        return 1.0
    return float(binom_sf_exact(b, m, Fraction(1, 2)))


def paired_binary_cells(x: Sequence[int], y: Sequence[int]) -> dict:
    """The four paired cells for binary x (e.g. C1) and y (reference)."""
    n11 = sum(1 for a, b in zip(x, y) if a and b)
    n10 = sum(1 for a, b in zip(x, y) if a and not b)
    n01 = sum(1 for a, b in zip(x, y) if not a and b)
    n00 = sum(1 for a, b in zip(x, y) if not a and not b)
    n = n11 + n10 + n01 + n00
    return {"n": n, "n11": n11, "n10": n10, "n01": n01, "n00": n00, "discordant": n10 + n01,
            "p_x": (n11 + n10) / n if n else math.nan, "p_y": (n11 + n01) / n if n else math.nan,
            "diff": (n10 - n01) / n if n else math.nan}


def fmt(v, digits: int = 4) -> str:
    """Compact number for tables: None -> 'undef', inf -> 'inf'."""
    if v is None:
        return "undef"
    if isinstance(v, float):
        if math.isnan(v):
            return "nan"
        if math.isinf(v):
            return "inf" if v > 0 else "-inf"
        return f"{v:.{digits}f}"
    return str(v)


def iter_rows(rows: Iterable[dict], keys: Sequence[str]) -> Iterable[list]:
    for r in rows:
        yield [r.get(k, "") for k in keys]

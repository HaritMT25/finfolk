#!/usr/bin/env python3
"""infer.py: calibrated inference for complete invasion blocks (stdlib only).

The noise model follows the design, not an assumed distribution. For one
condition (assay, fraction, window) with N items and k replicates:

    z[p][r][i] = s_r(i -> p) - s_r(p -> p)      (i != p;  z[p][r][p] = 0)

is replicate r of resident column p: every i -> p arena and the sham p -> p of
one (p, r) share the slot seed and the engine reseed (plan.py: common random
numbers), so a column-replicate (p, r) is ONE randomization unit whose N - 1
paired scores are jointly, arbitrarily correlated and heteroscedastic. Distinct
units are independent (every seed differs). Within one (p, r) nothing is
assumed: the inference below resamples or sign-flips whole units.

Edge means (one orientation p < q, P = N(N-1)/2 edges), from the column means m:
    A_pq = m[q][p] - m[p][q]                 antisymmetric part (who beats whom)
    S_pq = (m[q][p] + m[p][q]) / 2           symmetric part
Complete graph, unit weights: the Hodge cycle projection Q (rank q_C =
(N-1)(N-2)/2) and the symmetric node-additive residual projection Q_S (S_pq =
eta_p + eta_q + G_pq; rank N(N-3)/2) have closed forms, so every quantity is
O(N^2 k):
    ||QA||^2  = ||A||^2 - ||div A||^2 / N,   (div A)_p = sum_q A_pq
    per-unit noise energies of a residual vector d (d[p] = 0, sum over i != p):
      A:     ||d||^2
      curl:  (N-1)/N ||d||^2 - (sum d)^2 / N
      sym:   (N-3)/(4(N-2)) (||d||^2 - (sum d)^2 / (N-1))
    tau_X = sum_p sum_r E_X(z[p][r] - m[p]) / (k (k-1))
          = an unbiased estimate of tr(X-projected covariance of the edge MEANS),
            using the independence of distinct units and nothing else
    (a column constant, e.g. the shared sham, is pure gradient / node-additive:
     it drops out of the curl and of Q_S S exactly, by these formulas.)

Statistics
    T_C = ||QA||^2, T_A = ||A||^2, T_S = ||Q_S S||^2
    lack of fit of a pure ladder   F_C = T_C / tau_C     (~1 under the null)
    symmetric interaction          F_S = T_S / tau_S
    noise-corrected cyclic share   (T_C - tau_C) / (T_A - tau_A)  (ratio not unbiased;
                                   negative / unidentified values are kept)

Null distributions (no chi-square, no isotropy). Neither is exact in general;
what each one assumes is part of every result it gives:
  * studentized unit bootstrap (APPROXIMATE): draw k residual units per column
    (with replacement, scaled by sqrt(k/(k-1)) to restore the variance; or,
    kind 'wild', each unit's residual times a random sign), recompute T AND tau
    from the draw with the same functions as for the data, p = (1 + #{F* >= F})
    / (B + 1). The denominator is re-estimated in every draw, so the
    uncertainty of the noise estimate is part of the null. This is an
    asymptotic bootstrap approximation (Bickel & Freedman 1981): it assumes the
    k units of a column are exchangeable draws that represent their
    distribution. k = 6 or 10 units cannot represent a rare large component
    (e.g. a factor that is -0.002 with probability 0.95 and +0.038 otherwise:
    absent from all k units with probability 0.95^k), and then the test is
    anti-conservative. Its level is known only where it was simulated
    (calibrate.py's worlds, including such stress worlds); the Monte Carlo
    p = 1/(B+1) for no exceedance is a resolution limit, not a tail bound.
  * replicate sign-flip: under the null E[QA_r] = 0 for every replicate matrix
    A_r, and replicates are independent. The test is EXACT only if the
    replicate residual vectors are, in addition, CENTRALLY SYMMETRIC (jointly
    over every condition of an omnibus); a zero mean is not enough (Hemerik &
    Goeman). Resolution: p >= 1/2^(k-1) per group of aligned units.
  * several conditions (e.g. both assays) whose (p, r) units share seeds are
    resampled / flipped JOINTLY: F_joint = sum T_C / sum tau_C. Conditions
    with no shared units (e.g. matrices of different home regimes: other
    snapshots, other seeds) are independent GROUPS: infer_groups draws and
    flips each group independently (sign-flip resolution prod_g 1/2^(k_g-1)).

Descriptive companions from the same draws: the raw-share floor (95th
percentile of the cyclic share of a pure ladder of the noise-corrected
strength plus bootstrap noise) and p_mc; a 95% confidence ball for the
edge-noise vector (Strang et al. section 5), which bounds the true cyclic
share and the RMS cyclic signal d_C.
"""
from __future__ import annotations

import math
import random

# The bootstrap analyze.py uses unless told otherwise. calibrate.py's null simulations at the
# pilot's scale (N = 8, k = 6; six null worlds incl. the blocks' own resampled units; 1,000 datasets
# each, B = 999) found the residual-unit bootstrap at or below nominal in THOSE worlds (alpha 0.05:
# 0.004-0.035; 0.0045: <= 0.002), while the wild (random-sign) one was closer to nominal at 0.05
# (0.029-0.066) but up to 2.4x liberal at 0.0045. That is evidence for these worlds, not a
# finite-sample guarantee: a rare-event stress world breaks both tests (calibrate.py 'rare1').
DEFAULT_KIND = "residual"

# The frozen inference configuration. analyze.py and calibrate.py both read it, so a level or
# power simulation assesses the procedure the analysis applies (review round 2, P1: calibration
# used to default to the wild bootstrap while analysis used the residual one).
#   test   the primary lack-of-fit decision: 'signflip' (grouped replicate sign-flip, exact under
#          independent, centrally symmetric replicate residual vectors) or 'bootstrap'
#   kind   the bootstrap kind (reported beside the primary test in every table)
#   B      bootstrap draws for reported p-values
PRIMARY = {"test": "signflip", "kind": DEFAULT_KIND, "B": 9999}


# ------------------------------------------------------------ block algebra
def column_means(z):
    return [[sum(v) / len(col) for v in zip(*col)] for col in z]


def antisym(m):
    """Edge vector A (p < q, row-major) from column means: A_pq = m[q][p] - m[p][q]."""
    N = len(m)
    return [m[q][p] - m[p][q] for p in range(N) for q in range(p + 1, N)]


def symm(m):
    N = len(m)
    return [0.5 * (m[q][p] + m[p][q]) for p in range(N) for q in range(p + 1, N)]


def div(A, N):
    d = [0.0] * N
    e = 0
    for p in range(N):
        for q in range(p + 1, N):
            d[p] += A[e]
            d[q] -= A[e]
            e += 1
    return d


def curl_vec(A, N):
    """QA: A minus the gradient of the ratings r = div A / N (complete graph, unit weights)."""
    r = [x / N for x in div(A, N)]
    out, e = [], 0
    for p in range(N):
        for q in range(p + 1, N):
            out.append(A[e] - (r[p] - r[q]))
            e += 1
    return out, r


def energies(A, N):
    """-> (||A||^2, ||QA||^2)."""
    TA = sum(x * x for x in A)
    return TA, TA - sum(x * x for x in div(A, N)) / N


def sym_resid(S, N):
    """Q_S S: S minus its symmetric node-additive fit eta_p + eta_q (needs N >= 4)."""
    R = [0.0] * N
    e = 0
    for p in range(N):
        for q in range(p + 1, N):
            R[p] += S[e]
            R[q] += S[e]
            e += 1
    T = sum(S)
    eta = [(R[i] - T / (N - 1)) / (N - 2) for i in range(N)]
    out, e = [], 0
    for p in range(N):
        for q in range(p + 1, N):
            out.append(S[e] - eta[p] - eta[q])
            e += 1
    return out, eta


def sym_energy(S, N):
    return sum(x * x for x in sym_resid(S, N)[0]) if N >= 4 else 0.0


def unit_energies(d, N):
    """Noise energies of one unit's residual vector d (d[p] = 0): (A, curl, sym)."""
    s2 = sum(x * x for x in d)
    s1 = sum(d)
    return (s2, (N - 1) / N * s2 - s1 * s1 / N,
            (N - 3) / (4.0 * (N - 2)) * (s2 - s1 * s1 / (N - 1)) if N >= 4 else 0.0)


def block_stats(z):
    """Everything the tests need from one condition's units z[p][r][i] (same k per column)."""
    N, k = len(z), len(z[0])
    m = column_means(z)
    A = antisym(m)
    TA, TC = energies(A, N)
    TS = sym_energy(symm(m), N)
    tA = tC = tS = 0.0
    for p, col in enumerate(z):
        mp = m[p]
        for zr in col:
            a, c, s = unit_energies([x - y for x, y in zip(zr, mp)], N)
            tA += a
            tC += c
            tS += s
    f = 1.0 / (k * (k - 1))
    return {"N": N, "k": k, "A": A, "TA": TA, "TC": TC, "TS": TS, "tauA": tA * f, "tauC": tC * f, "tauS": tS * f}


def residual_units(z):
    """Centered units, scaled by sqrt(k/(k-1)) so that a bootstrap draw restores the sample variance."""
    k = len(z[0])
    s = math.sqrt(k / (k - 1.0))
    m = column_means(z)
    return [[[s * (x - y) for x, y in zip(zr, m[p])] for zr in col] for p, col in enumerate(z)]


# ------------------------------------------------------------------ tests
def percentile(xs, q):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    lo = int(math.floor(k))
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _ratio(num, den):
    return num / den if den > 0 else (float("inf") if num > 0 else float("nan"))


def _draw_plan(rnd, kind, N, k):
    """One draw's choice: per column, k resampled unit indices ('residual') or k signs ('wild')."""
    if kind == "residual":
        return [[rnd.randrange(k) for _ in range(k)] for _ in range(N)]
    if kind == "wild":
        return [[rnd.random() < 0.5 for _ in range(k)] for _ in range(N)]
    raise ValueError(kind)


def _apply_plan(res, plan, kind):
    """The drawn units themselves (what the fast path below avoids building)."""
    if kind == "residual":
        return [[res[p][i] for i in plan[p]] for p in range(len(res))]
    return [[u if plan[p][r] else [-x for x in u] for r, u in enumerate(res[p])] for p in range(len(res))]


def _fast_stats(res, E, plan, kind):
    """block_stats(_apply_plan(res, plan, kind)), computed from the drawn column means only: for a
    quadratic form q, sum_m q(x_m - xbar) = sum_m q(x_m) - k q(xbar), and q(x_m) of a drawn unit
    is q of a residual unit (a sign flip does not change it), precomputed in E. Same numbers as
    block_stats up to rounding (selftest)."""
    N, k = len(res), len(res[0])
    means, sA, sC, sS = [], 0.0, 0.0, 0.0
    for p in range(N):
        if kind == "residual":
            rows = [res[p][i] for i in plan[p]]
            for i in plan[p]:
                sA += E[p][i][0]
                sC += E[p][i][1]
                sS += E[p][i][2]
        else:
            rows = [u if plan[p][r] else [-x for x in u] for r, u in enumerate(res[p])]
            for e in E[p]:
                sA += e[0]
                sC += e[1]
                sS += e[2]
        mp = [sum(v) / k for v in zip(*rows)]
        means.append(mp)
        a, c, s = unit_energies(mp, N)
        sA -= k * a
        sC -= k * c
        sS -= k * s
    A = antisym(means)
    TA, TC = energies(A, N)
    f = 1.0 / (k * (k - 1))
    return {"N": N, "k": k, "A": A, "TA": TA, "TC": TC, "TS": sym_energy(symm(means), N),
            "tauA": sA * f, "tauC": sC * f, "tauS": sS * f, "m": means}


def bootstrap(zs, B=9999, seed=1, kind=DEFAULT_KIND, ladder=None):
    """Null draws for conditions zs (a list; units p, r aligned across conditions are drawn
    jointly). -> list of dicts F_C, F_S (joint over conditions), and for zs[0]: T_C0 (the
    unstudentized curl energy), eA (norm of the edge-noise vector), share (raw cyclic share of
    the pure ladder `ladder`, an edge vector, plus the drawn noise; None without a ladder)."""
    return bootstrap_groups([zs], B, seed, kind, ladder)


def bootstrap_groups(groups, B=9999, seed=1, kind=DEFAULT_KIND, ladder=None):
    """Null draws for independent groups of aligned conditions: within a group every condition
    reuses one draw plan (their units share seeds); each group gets its own plan. One group is
    exactly bootstrap() (same random stream). T_C0 / eA / share are of groups[0][0]."""
    rnd = random.Random(seed)
    flat = [(g, z) for g, zs in enumerate(groups) for z in zs]
    res = [residual_units(z) for _, z in flat]
    E = [[[unit_energies(u, len(z)) for u in col] for col in rc] for rc, (_, z) in zip(res, flat)]
    shape = [(len(zs[0]), len(zs[0][0])) for zs in groups]
    out = []
    LL = sum(x * x for x in ladder) if ladder else 0.0
    for _ in range(B):
        plans = [_draw_plan(rnd, kind, N, k) for N, k in shape]
        st = [_fast_stats(res[c], E[c], plans[g], kind) for c, (g, _) in enumerate(flat)]
        d = {"F_C": _ratio(sum(s["TC"] for s in st), sum(s["tauC"] for s in st)),
             "F_S": _ratio(sum(s["TS"] for s in st), sum(s["tauS"] for s in st)),
             "T_C0": st[0]["TC"], "eA": math.sqrt(st[0]["TA"]), "share": None}
        if ladder:
            A = st[0]["A"]
            den = LL + 2 * sum(a * b for a, b in zip(ladder, A)) + st[0]["TA"]
            d["share"] = st[0]["TC"] / den if den > 0 else float("nan")
        out.append(d)
    return out


def _flip_p(vecs):
    """Exact sign-flip p for H0: E[u_r] = 0, from per-replicate vectors (per condition, already
    concatenated): T(delta) = ||sum_r delta_r u_r||^2 over all 2^(k-1) sign patterns (delta and
    -delta give the same T). Monte Carlo over 2^15 patterns when k > 16."""
    k = len(vecs)
    G = [[sum(a * b for a, b in zip(vecs[r], vecs[s])) for s in range(k)] for r in range(k)]
    tobs = sum(sum(row) for row in G)
    tol = 1e-12 * max(1.0, abs(tobs))

    def T(sg):
        return sum(sg[r] * sg[s] * G[r][s] for r in range(k) for s in range(k))
    if k <= 16:
        n = ge = 0
        for mask in range(1 << (k - 1)):
            sg = [1] + [(-1 if (mask >> b) & 1 else 1) for b in range(k - 1)]
            n += 1
            ge += T(sg) >= tobs - tol
        return ge / n
    rnd = random.Random(3)
    M = 1 << 15
    ge = sum(1 for _ in range(M) if T([1] + [rnd.choice((-1, 1)) for _ in range(k - 1)]) >= tobs - tol)
    return (1 + ge) / (M + 1)


def replicate_vectors(zs, which):
    """Per replicate r: concatenation over conditions of QA_r ('curl') or Q_S S_r ('sym'), with
    A_r, S_r built from replicate r of every column (units of one replicate are independent of
    every other replicate's)."""
    N, k = len(zs[0]), len(zs[0][0])
    out = []
    for r in range(k):
        v = []
        for z in zs:
            m = [z[p][r] for p in range(N)]
            v += curl_vec(antisym(m), N)[0] if which == "curl" else sym_resid(symm(m), N)[0]
        out.append(v)
    return out


def signflip(zs, which="curl"):
    return _flip_p(replicate_vectors(zs, which))


def _flip_all(vecs):
    """T(delta) for every one of the 2^(k-1) sign patterns (first sign fixed), and T(+1...).
    Gray-code order: one sign changes per step, T and h_r = sum_s delta_s G_rs updated in O(k)."""
    k = len(vecs)
    G = [[sum(a * b for a, b in zip(vecs[r], vecs[s])) for s in range(k)] for r in range(k)]
    sg = [1] * k
    h = [sum(row) for row in G]
    T = sum(h)
    out = [T]
    for i in range(1, 1 << (k - 1)):
        t = 1 + ((i & -i).bit_length() - 1)   # the sign that changes (never the first)
        st = sg[t]
        T -= 4.0 * st * (h[t] - st * G[t][t])
        for s in range(k):
            h[s] -= 2.0 * st * G[s][t]
        sg[t] = -st
        out.append(T)
    return out, out[0]


def signflip_groups(groups, which="curl", mc=1 << 16, seed=3):
    """Sign-flip p for independent groups of aligned conditions: whole replicates are flipped
    jointly within a group and independently across groups; T = sum over groups of
    ||sum_r delta_r u_r||^2 (the groups occupy disjoint coordinates). Exact enumeration for one
    or two groups (k <= 16 each), Monte Carlo over the per-group pattern lists otherwise.
    Exact under H0 only if every group's replicate residual vectors are independent and
    centrally symmetric. Resolution prod_g 1/2^(k_g - 1)."""
    import bisect
    per = []
    for zs in groups:
        vecs = replicate_vectors(zs, which)
        if len(vecs) > 16:
            raise ValueError("signflip_groups: k > 16 per group")
        per.append(_flip_all(vecs))
    tobs = sum(t for _, t in per)
    tol = 1e-12 * max(1.0, abs(tobs))
    if len(per) == 1:
        Ts = per[0][0]
        return sum(1 for t in Ts if t >= tobs - tol) / len(Ts)
    if len(per) == 2:
        T1, T2 = per[0][0], sorted(per[1][0])
        n2 = len(T2)
        ge = sum(n2 - bisect.bisect_left(T2, tobs - tol - t) for t in T1)
        return ge / (len(T1) * n2)
    rnd = random.Random(seed)
    ge = sum(1 for _ in range(mc) if sum(Ts[rnd.randrange(len(Ts))] for Ts, _ in per) >= tobs - tol)
    return (1 + ge) / (mc + 1)


def infer_groups(groups, B=9999, seed=1, kind=DEFAULT_KIND):
    """The omnibus over independent groups of aligned conditions (e.g. the stats spec's four
    primary matrices: two home regimes = two independent groups, each with its two assay
    conditions sharing units): F_C = sum T_C / sum tau_C over every condition, its
    studentized bootstrap p (each group drawn independently) and the grouped sign-flip p."""
    st = [block_stats(z) for zs in groups for z in zs]
    F_C = _ratio(sum(s["TC"] for s in st), sum(s["tauC"] for s in st))
    F_S = _ratio(sum(s["TS"] for s in st), sum(s["tauS"] for s in st))
    boot = bootstrap_groups(groups, B, seed, kind)
    sym = all(len(zs[0]) >= 4 for zs in groups)
    mn = 1.0
    for zs in groups:
        mn /= 1 << (len(zs[0][0]) - 1)
    return {"groups": len(groups), "conditions": len(st), "kind": kind, "B": B,
            "N": [len(zs[0]) for zs in groups], "k": [len(zs[0][0]) for zs in groups],
            "F_C": F_C, "F_S": F_S,
            "p_lof": (1 + sum(1 for b in boot if b["F_C"] >= F_C)) / (B + 1),
            "p_sym": (1 + sum(1 for b in boot if b["F_S"] >= F_S)) / (B + 1) if sym else None,
            "p_lof_flip": signflip_groups(groups, "curl"),
            "p_sym_flip": signflip_groups(groups, "sym") if sym else None,
            "flip_min_p": mn}


def confidence_ball(A, N, r95):
    """True cyclic share and RMS cyclic signal d_C over the ball ||x - A|| <= r95 (unit weights)."""
    TA, TC = energies(A, N)
    P = len(A)
    a = math.sqrt(TA)
    c = math.sqrt(max(0.0, TC))
    g = math.sqrt(max(0.0, TA - TC))
    dC = (max(0.0, c - r95) / math.sqrt(P), (c + r95) / math.sqrt(P))
    if r95 >= a:
        return (0.0, 1.0), dC, True
    phi = math.atan2(c, g)
    dl = math.asin(r95 / a)
    return (math.sin(max(0.0, phi - dl)) ** 2, math.sin(min(math.pi / 2, phi + dl)) ** 2), dC, False


def infer(zs, B=9999, seed=1, kind=DEFAULT_KIND):
    """Formal inference for one condition (zs = [z]) or several conditions with aligned units.
    -> dict: per-condition statistics of zs[0] and the joint p-values."""
    st = [block_stats(z) for z in zs]
    s0 = st[0]
    N = s0["N"]
    A = s0["A"]
    # pure-ladder null for the floor: the observed ratings shrunk to the noise-corrected gradient
    # energy (the gradient carries tau_A - tau_C of the noise)
    r = curl_vec(A, N)[1]
    Gobs = s0["TA"] - s0["TC"]
    Gcor = Gobs - (s0["tauA"] - s0["tauC"])
    sc = math.sqrt(Gcor / Gobs) if Gobs > 0 and Gcor > 0 else 0.0
    ladder = [sc * (r[p] - r[q]) for p in range(N) for q in range(p + 1, N)]
    boot = bootstrap(zs, B, seed, kind, ladder if len(zs) == 1 else None)
    F_C = _ratio(sum(s["TC"] for s in st), sum(s["tauC"] for s in st))
    F_S = _ratio(sum(s["TS"] for s in st), sum(s["tauS"] for s in st))
    out = {
        "N": N, "k": s0["k"], "conditions": len(zs), "kind": kind, "B": B,
        "T_A": s0["TA"], "T_C": s0["TC"], "T_S": s0["TS"],
        "tau_A": s0["tauA"], "tau_C": s0["tauC"], "tau_S": s0["tauS"],
        "share_raw": _ratio(s0["TC"], s0["TA"]),
        "share_nc": _ratio(s0["TC"] - s0["tauC"], s0["TA"] - s0["tauA"]) if s0["TA"] > s0["tauA"] else float("nan"),
        "C_nc": s0["TC"] - s0["tauC"], "G_nc": Gcor,
        "F_C": F_C, "F_S": F_S,
        "p_lof": (1 + sum(1 for b in boot if b["F_C"] >= F_C)) / (B + 1),
        "p_lof_unstud": (1 + sum(1 for b in boot if b["T_C0"] >= s0["TC"])) / (B + 1) if len(zs) == 1 else None,
        "p_sym": (1 + sum(1 for b in boot if b["F_S"] >= F_S)) / (B + 1) if N >= 4 else None,
        "p_lof_flip": signflip(zs, "curl"), "p_sym_flip": signflip(zs, "sym") if N >= 4 else None,
        "flip_min_p": 1.0 / (1 << (s0["k"] - 1)) if s0["k"] <= 16 else None,
    }
    if len(zs) == 1:
        shares = [b["share"] for b in boot]
        out["floor95"] = percentile(shares, 0.95)
        out["p_mc"] = (1 + sum(1 for x in shares if x >= out["share_raw"])) / (B + 1)
        r95 = percentile([b["eA"] for b in boot], 0.95)
        (lo, hi), (dlo, dhi), unident = confidence_ball(A, N, r95)
        out.update({"noise_radius95": r95, "share_ci95": (lo, hi), "dC": math.sqrt(max(0.0, out["C_nc"]) / len(A)),
                    "dC_ci95": (dlo, dhi), "share_unidentified": unident})
    return out


# --------------------------------------------------- simulation (calibrate.py)
def cycle_template(N, kind, seed=0):
    """A unit-RMS divergence-free edge vector (||v||^2 = P): 'diffuse' (rank-2 skew u b^T - b u^T,
    projected), 'random' (iid edges, projected), 'triangle' (one circulation 0 -> 1 -> 2 -> 0)."""
    rnd = random.Random(seed)
    P = N * (N - 1) // 2
    if kind == "triangle":
        v = [0.0] * P
        idx = {}
        e = 0
        for p in range(N):
            for q in range(p + 1, N):
                idx[(p, q)] = e
                e += 1
        v[idx[(0, 1)]] = 1.0
        v[idx[(1, 2)]] = 1.0
        v[idx[(0, 2)]] = -1.0
    elif kind == "diffuse":
        u = [rnd.gauss(0, 1) for _ in range(N)]
        b = [rnd.gauss(0, 1) for _ in range(N)]
        v = curl_vec([u[p] * b[q] - b[p] * u[q] for p in range(N) for q in range(p + 1, N)], N)[0]
    elif kind == "random":
        v = curl_vec([rnd.gauss(0, 1) for _ in range(P)], N)[0]
    else:
        raise ValueError(kind)
    n = math.sqrt(sum(x * x for x in v) / P)
    return [x / n for x in v]


def plant(z, v, d):
    """Add the antisymmetric edge signal d * v to every replicate: +d v_pq / 2 to p -> q (column
    q) and -d v_pq / 2 to q -> p (column p). Residuals, hence every null draw, are unchanged."""
    N = len(z)
    out = [[list(u) for u in col] for col in z]
    e = 0
    for p in range(N):
        for q in range(p + 1, N):
            x = 0.5 * d * v[e]
            for u in out[q]:
                u[p] += x
            for u in out[p]:
                u[q] -= x
            e += 1
    return out


# ----------------------------------------------------------------- self-test
def _direct_projection_energy(vec_edges, N, which):
    """Brute-force least squares (normal equations) for the selftest."""
    import hodge
    P = len(vec_edges)
    if which == "curl":
        M = [[None] * N for _ in range(N)]
        e = 0
        for p in range(N):
            for q in range(p + 1, N):
                M[p][q] = vec_edges[e]
                M[q][p] = -vec_edges[e]
                e += 1
        s = hodge.split(M)
        return s["cyclic_share"] * s["norm2"]
    # symmetric: fit eta by normal equations Z^T Z eta = Z^T S
    ZtZ = [[0.0] * N for _ in range(N)]
    ZtS = [0.0] * N
    e = 0
    for p in range(N):
        for q in range(p + 1, N):
            for a in (p, q):
                ZtS[a] += vec_edges[e]
                for b in (p, q):
                    ZtZ[a][b] += 1.0
            e += 1
    eta = hodge.solve(ZtZ, ZtS)
    res, e = 0.0, 0
    for p in range(N):
        for q in range(p + 1, N):
            res += (vec_edges[e] - eta[p] - eta[q]) ** 2
            e += 1
    return res


def selftest():
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    rnd = random.Random(11)
    for N in (4, 6, 9):
        # closed forms == direct projections, for whole blocks and for single units
        m = [[0.0 if i == p else rnd.gauss(0, 1) for i in range(N)] for p in range(N)]
        A, S = antisym(m), symm(m)
        assert abs(energies(A, N)[1] - _direct_projection_energy(A, N, "curl")) < 1e-9
        assert abs(sym_energy(S, N) - _direct_projection_energy(S, N, "sym")) < 1e-9
        p = rnd.randrange(N)
        d = [0.0 if i == p else rnd.gauss(0, 1) for i in range(N)]
        unit = [[0.0] * N for _ in range(N)]
        unit[p] = d
        eA, eC, eS = unit_energies(d, N)
        assert abs(eA - energies(antisym(unit), N)[0]) < 1e-9
        assert abs(eC - energies(antisym(unit), N)[1]) < 1e-9
        assert abs(eS - sym_energy(symm(unit), N)) < 1e-9
        # a column constant (the shared sham) is pure gradient and node-additive
        c = [[(0.0 if i == q else 0.7 * q) for i in range(N)] for q in range(N)]
        assert abs(energies(antisym(c), N)[1]) < 1e-9 and abs(sym_energy(symm(c), N)) < 1e-9
        # templates are divergence-free with RMS 1
        for kind in ("diffuse", "random", "triangle"):
            v = cycle_template(N, kind, 1)
            TA, TC = energies(v, N)
            assert abs(TA - TC) < 1e-9 and abs(TA - N * (N - 1) / 2) < 1e-9, (kind, TA, TC)
    # tau is unbiased for the curl noise energy of the means, whatever the per-cell variances
    N, k = 6, 4
    sds = [[0.0 if i == p else rnd.choice((0.2, 1.0, 3.0)) for i in range(N)] for p in range(N)]
    tc, ec = [], []
    for _ in range(3000):
        z = [[[rnd.gauss(0, sds[p][i]) if i != p else 0.0 for i in range(N)] for _ in range(k)] for p in range(N)]
        s = block_stats(z)
        tc.append(s["tauC"])
        ec.append(s["TC"])
    assert abs(sum(tc) / len(tc) / (sum(ec) / len(ec)) - 1) < 0.06, (sum(tc) / len(tc), sum(ec) / len(ec))
    # planting changes the means, not the residuals; a planted cycle is the curl energy
    z = [[[rnd.gauss(0, 0.01) if i != p else 0.0 for i in range(N)] for _ in range(k)] for p in range(N)]
    v = cycle_template(N, "diffuse", 2)
    s0, s1 = block_stats(z), block_stats(plant(z, v, 1.0))
    assert abs(s0["tauC"] - s1["tauC"]) < 1e-12 and abs(s1["TC"] - 15) < 1.0, (s1["TC"],)
    # the bootstrap's fast path is block_stats of the drawn units, for both kinds
    res = residual_units(z)
    E = [[unit_energies(u, N) for u in col] for col in res]
    for kind in ("wild", "residual"):
        for _ in range(5):
            plan = _draw_plan(rnd, kind, N, k)
            f_, b_ = _fast_stats(res, E, plan, kind), block_stats(_apply_plan(res, plan, kind))
            for x in ("TA", "TC", "TS", "tauA", "tauC", "tauS"):
                assert abs(f_[x] - b_[x]) < 1e-12 * max(1.0, abs(b_[x])) + 1e-15, (kind, x, f_[x], b_[x])
    # the sign-flip p of a strong planted cycle is the minimum 1/2^(k-1); of noise it is not tiny
    zz = plant(z, v, 1.0)
    assert abs(signflip([zz]) - 1 / 8) < 1e-12
    r = infer([zz], B=199, seed=3)
    assert r["p_lof"] == 1 / 200 and r["share_raw"] > 0.9, r
    # the Gray-code enumeration gives every pattern's T (brute force)
    vecs = [[rnd.gauss(0, 1) for _ in range(7)] for _ in range(6)]
    brute = []
    for mask in range(1 << 5):
        sg = [1] + [(-1 if (mask >> b) & 1 else 1) for b in range(5)]
        w = [sum(sg[r] * vecs[r][e] for r in range(6)) for e in range(7)]
        brute.append(sum(x * x for x in w))
    fast, t0 = _flip_all(vecs)
    assert abs(t0 - brute[0]) < 1e-9 and all(abs(x - y) < 1e-9 for x, y in zip(sorted(fast), sorted(brute)))
    # groups: one group is exactly the single-condition procedure; independent groups are flipped
    # and drawn independently (sign-flip resolution 1/2^(k1-1) / 2^(k2-1))
    assert signflip_groups([[zz]]) == signflip([zz])
    b1, b2 = bootstrap([zz], B=20, seed=4), bootstrap_groups([[zz]], B=20, seed=4)
    assert all(x["F_C"] == y["F_C"] and x["F_S"] == y["F_S"] for x, y in zip(b1, b2))
    z2 = plant([[[rnd.gauss(0, 0.01) if i != p else 0.0 for i in range(5)] for _ in range(5)] for p in range(5)],
               cycle_template(5, "diffuse", 3), 1.0)
    assert abs(signflip_groups([[zz], [z2]]) - 1 / 128) < 1e-12, signflip_groups([[zz], [z2]])
    assert signflip_groups([[zz], [z2], [zz]]) < 0.003
    g = infer_groups([[zz], [z2]], B=99, seed=1)
    assert g["flip_min_p"] == 1 / 128 and g["p_lof"] == 1 / 100 and g["conditions"] == 2, g
    # a group without signal next to one with signal: the pooled statistic still sees it
    zn = [[[rnd.gauss(0, 0.01) if i != p else 0.0 for i in range(5)] for _ in range(5)] for p in range(5)]
    assert infer_groups([[zz], [zn]], B=99, seed=1)["p_lof"] <= 0.02
    print("infer selftest: ok")


if __name__ == "__main__":
    selftest()

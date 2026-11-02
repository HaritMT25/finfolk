#!/usr/bin/env python3
"""hodge.py: ladder / cycle split of an invasion matrix (pure Python, stdlib only).

Matrices are lists of lists; a missing cell is None.

    s~[i][j]   paired invasion score of i into j (s(i->j) - s(j->j))
    A = s~ - s~^T          antisymmetric part: who beats whom
    S = (s~ + s~^T) / 2    symmetric part: > 0 mutual invasibility (coexistence),
                           < 0 priority effects (whoever is resident wins)

Hodge (combinatorial Helmholtz) split of A on the comparison graph
(Candogan et al. 2011; Balduzzi et al. 2018, "Re-evaluating evaluation"):
    A = grad r + curl,   grad r_ij = r_i - r_j,
with r the weighted least-squares ratings  min sum_{i<j} w_ij (A_ij - r_i + r_j)^2
(for a complete, unit-weight matrix r_i is the row mean of A). The headline
number is the cyclic share  ||curl||^2 / ||A||^2  over the observed pairs:
0 = a pure ladder, 1 = pure rock-paper-scissors.

Noise: with independent cell noise of variance v on each A_ij, E||noise||^2 =
v * P (P observed pairs) of which v * (P - (N - 1)) lands in the curl (the
cycle space has dimension P - N + 1 on a connected graph), so pure noise reads
as cyclic share (P - N + 1) / P, about (N - 2) / N for a complete matrix. A
measured share means nothing until it beats the noise floor (pure ladder +
the measured noise, 95th percentile) -- simulate_floor -- and a "ladder"
verdict means nothing until a planted cycle of realistic size is shown to be
recovered -- simulate_power.

mElo2k (Balduzzi et al. 2018): the curl's leading Schur pairs,
curl ~ sum_k s_k (u_k b_k^T - b_k u_k^T), give each item a 2k-dimensional
cyclic embedding.
"""
from __future__ import annotations

import math
import random


# ----------------------------------------------------------------- basics
def zeros(n):
    return [[0.0] * n for _ in range(n)]


def antisym_sym(st):
    """A and S from a paired-score matrix (None where either direction is missing)."""
    n = len(st)
    A = [[None] * n for _ in range(n)]
    S = [[None] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j and st[i][j] is not None and st[j][i] is not None:
                A[i][j] = st[i][j] - st[j][i]
                S[i][j] = 0.5 * (st[i][j] + st[j][i])
    return A, S


def solve(M, b):
    """Gaussian elimination with partial pivoting (small dense systems)."""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(M)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-300:
            raise ValueError("singular system (is the comparison graph connected?)")
        M[c], M[p] = M[p], M[c]
        for r in range(c + 1, n):
            f = M[r][c] / M[c][c]
            if f:
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (M[r][n] - sum(M[r][k] * x[k] for k in range(r + 1, n))) / M[r][r]
    return x


def ratings(A, W=None):
    """Weighted least-squares ratings (sum r = 0). W[i][j] = weight of pair (i, j), default 1
    for every observed pair; for a complete unit-weight matrix this is the row mean."""
    n = len(A)
    obs = [(i, j) for i in range(n) for j in range(i + 1, n) if A[i][j] is not None]
    if len(obs) == n * (n - 1) // 2 and W is None:
        return [sum(A[i][j] for j in range(n) if j != i) / n for i in range(n)]
    L = zeros(n)
    b = [0.0] * n
    for i, j in obs:
        w = 1.0 if W is None else W[i][j]
        L[i][i] += w
        L[j][j] += w
        L[i][j] -= w
        L[j][i] -= w
        b[i] += w * A[i][j]
        b[j] -= w * A[i][j]
    # the Laplacian is singular along 1: add the constraint sum r = 0 as + 1 1^T / n
    for i in range(n):
        for j in range(n):
            L[i][j] += 1.0 / n
    return solve(L, b)


def split(A, W=None):
    """-> dict(r, grad, curl, cyclic_share, ladder_share, P, norm2) over the observed pairs."""
    n = len(A)
    r = ratings(A, W)
    grad = [[None] * n for _ in range(n)]
    curl = [[None] * n for _ in range(n)]
    na = nc = ng = 0.0
    P = 0
    for i in range(n):
        for j in range(n):
            if i != j and A[i][j] is not None:
                g = r[i] - r[j]
                grad[i][j] = g
                curl[i][j] = A[i][j] - g
                if i < j:
                    w = 1.0 if W is None else W[i][j]
                    na += w * A[i][j] ** 2
                    nc += w * (A[i][j] - g) ** 2
                    ng += w * g * g
                    P += 1
    share = nc / na if na > 0 else float("nan")
    return {"r": r, "grad": grad, "curl": curl, "cyclic_share": share,
            "ladder_share": ng / na if na > 0 else float("nan"), "P": P, "norm2": na}


def debiased_share(A, noise_var, W=None):
    """Cyclic share with the expected noise energy removed from both norms (unit weights,
    connected graph): (||curl||^2 - v (P - N + 1)) / (||A||^2 - v P). Can leave [0, 1]."""
    s = split(A, W)
    n = len(A)
    P = s["P"]
    num = s["cyclic_share"] * s["norm2"] - noise_var * (P - n + 1)
    den = s["norm2"] - noise_var * P
    return num / den if den > 0 else float("nan")


# ------------------------------------------------------------------ mElo2k
def melo2k(curl, k=1, iters=500, seed=1):
    """Leading k Schur pairs of a complete skew-symmetric matrix (None -> 0).
    -> list of (sigma, u, b) with curl ~ sum sigma (u b^T - b u^T), and the embedding
    c_i = sqrt(sigma) (u_i, b_i) per pair."""
    n = len(curl)
    C = [[(curl[i][j] or 0.0) if i != j else 0.0 for j in range(n)] for i in range(n)]
    rnd = random.Random(seed)
    out = []
    for _ in range(k):
        x = [rnd.gauss(0, 1) for _ in range(n)]
        sigma = 0.0
        for _ in range(iters):
            y = [sum(C[i][j] * x[j] for j in range(n)) for i in range(n)]          # C x
            z = [-sum(C[i][j] * y[j] for j in range(n)) for i in range(n)]         # -C C x = C^T C x
            nz = math.sqrt(sum(v * v for v in z))
            if nz == 0:
                break
            x = [v / nz for v in z]
        w = [sum(C[i][j] * x[j] for j in range(n)) for i in range(n)]
        sigma = math.sqrt(sum(v * v for v in w))
        if sigma == 0:
            break
        b = [-v / sigma for v in w]   # C u = -sigma b
        u = x
        out.append((sigma, u, b))
        for i in range(n):
            for j in range(n):
                C[i][j] -= sigma * (u[i] * b[j] - b[i] * u[j])
    return out


# ------------------------------------------------------------- simulation
def _ladder(n, rnd, sd=1.0):
    r = [rnd.gauss(0, sd) for _ in range(n)]
    return [[(r[i] - r[j]) if i != j else None for j in range(n)] for i in range(n)]


def _random_curl(n, rnd):
    Z = [[None] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            v = rnd.gauss(0, 1)
            Z[i][j] = v
            Z[j][i] = -v
    return split(Z)["curl"]


def _norm2(M):
    n = len(M)
    return sum(M[i][j] ** 2 for i in range(n) for j in range(i + 1, n) if M[i][j] is not None)


def planted(n, rms, share, rnd):
    """A true antisymmetric matrix with RMS entry `rms` over pairs and cyclic share `share`."""
    P = n * (n - 1) / 2
    L = _ladder(n, rnd)
    C = _random_curl(n, rnd)
    nl, nc = _norm2(L), _norm2(C)
    tot = rms * rms * P
    a = math.sqrt(tot * (1 - share) / nl) if nl > 0 else 0.0
    c = math.sqrt(tot * share / nc) if nc > 0 else 0.0
    return [[(a * L[i][j] + c * C[i][j]) if i != j else None for j in range(n)] for i in range(n)]


def observe(T, noise_sd, rnd):
    """Add independent N(0, noise_sd^2) noise to each pair of an antisymmetric matrix."""
    n = len(T)
    A = [[None] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            v = T[i][j] + rnd.gauss(0, noise_sd)
            A[i][j] = v
            A[j][i] = -v
    return A


def percentile(xs, q):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    lo = int(math.floor(k))
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def simulate_floor(n, rms, noise_sd, sims=1000, seed=0):
    """Cyclic shares of pure-ladder matrices (true RMS `rms`) observed with noise `noise_sd`
    per A cell. -> (list of shares, 95th percentile)."""
    rnd = random.Random(seed)
    xs = [split(observe(planted(n, rms, 0.0, rnd), noise_sd, rnd))["cyclic_share"] for _ in range(sims)]
    return xs, percentile(xs, 0.95)


def simulate_power(n, rms, share, noise_sd, floor95, sims=500, seed=1):
    """Planted cycle of cyclic share `share` (true RMS `rms`), observed with noise.
    -> dict(power = P(observed share > floor95), mean observed share, mean debiased share)."""
    rnd = random.Random(seed)
    hit = 0
    obs, deb = [], []
    v = noise_sd * noise_sd
    for _ in range(sims):
        A = observe(planted(n, rms, share, rnd), noise_sd, rnd)
        s = split(A)["cyclic_share"]
        obs.append(s)
        deb.append(debiased_share(A, v))
        hit += s > floor95
    return {"power": hit / sims, "mean_share": sum(obs) / sims, "mean_debiased": sum(deb) / sims,
            "sd_share": math.sqrt(sum((x - sum(obs) / sims) ** 2 for x in obs) / max(1, sims - 1))}


# -------------------------------------------------------------- self-test
def selftest():
    rnd = random.Random(7)
    n = 8
    # a pure ladder is all gradient, and its ratings are recovered
    L = _ladder(n, rnd)
    s = split(L)
    assert s["cyclic_share"] < 1e-20, s["cyclic_share"]
    # a pure curl is all cycle
    C = _random_curl(n, rnd)
    assert abs(split(C)["cyclic_share"] - 1.0) < 1e-12
    # rock-paper-scissors on 3 items: share 1, ratings 0
    rps = [[None, 1.0, -1.0], [-1.0, None, 1.0], [1.0, -1.0, None]]
    s = split(rps)
    assert abs(s["cyclic_share"] - 1) < 1e-12 and max(abs(x) for x in s["r"]) < 1e-12
    # planted share is exact before noise
    T = planted(12, 0.05, 0.3, rnd)
    assert abs(split(T)["cyclic_share"] - 0.3) < 1e-9
    # WLS on a complete unit-weight matrix == row means; on an incomplete one it still
    # recovers a pure ladder exactly
    A = observe(T, 0.01, rnd)
    r1 = ratings(A)
    r2 = ratings(A, [[1.0] * 12 for _ in range(12)])
    assert max(abs(a - b) for a, b in zip(r1, r2)) < 1e-12
    Lr = _ladder(10, rnd)
    for i in range(10):
        for j in range(10):
            if i != j and (i + 2 * j) % 5 == 0:
                Lr[i][j] = Lr[j][i] = None
    assert split(Lr)["cyclic_share"] < 1e-18
    # pure noise reads as share ~ (P - N + 1) / P
    xs = [split(observe([[0.0 if i != j else None for j in range(10)] for i in range(10)], 1.0, rnd))["cyclic_share"]
          for _ in range(300)]
    m = sum(xs) / len(xs)
    assert abs(m - 36 / 45) < 0.03, m
    # mElo2k: a rank-2 curl is reconstructed by one Schur pair
    u = [rnd.gauss(0, 1) for _ in range(9)]
    b = [rnd.gauss(0, 1) for _ in range(9)]
    R = [[(u[i] * b[j] - b[i] * u[j]) if i != j else None for j in range(9)] for i in range(9)]
    (sig, uu, bb), = melo2k(R, 1)
    err = max(abs(R[i][j] - sig * (uu[i] * bb[j] - bb[i] * uu[j])) for i in range(9) for j in range(9) if i != j)
    assert err < 1e-8, err
    print("hodge selftest: ok")


if __name__ == "__main__":
    selftest()

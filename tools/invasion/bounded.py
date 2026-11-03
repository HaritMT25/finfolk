#!/usr/bin/env python3
"""bounded.py: bounded-scale sensitivity of the ladder / cycle split (stdlib only).

Why. The endpoint is bounded: q, the invaders' final mean founder-pedigree contribution, lies
in [0, 1], and a losing invader cannot go below q = 0 (s = -f). A transitive but non-additive
bounded ladder makes cardinal Hodge residuals with no ordinal cycle:
q_ij = logistic(logit(0.05) + u_i - u_j) is perfectly ordered, yet for strengths 0, 1, 2 its
antisymmetric part has triangle circulation -0.0606 (Bertrand, Czarnecki & Gidel 2023:
"transitive, not additive"). So a cyclic residual on the raw score scale is not by itself a
strategy cycle. Two complementary checks (review round 2):

1. Transformed endpoints. Each replicate's endpoint q and its start fraction f are transformed
   before the unchanged pipeline (sham pairing, units, infer.py): s_h = h(q) - h(f).
     logit:EPS  h(q) = logit(clip(q, EPS, 1 - EPS)). Exact zeros occur (the invader pedigree
                was lost), so the clip matters: EPS = 0.001 primary, 1e-6 sensitivity.
     asin       h(q) = asin(sqrt(q)), the angular (variance-stabilizing) transform; no clip.
   Descriptive sensitivity: no transformation is uniquely right, and the tests on a
   transformed scale test additivity ON THAT SCALE.

2. Bounded node-additive models for the EXPECTED endpoint, fitted per condition to the cell
   means qbar_ij (invader i, resident j, i != j; equal cell weights; least squares). The shams
   are column constants on the outcome scale and never reach the cyclic part, so they are not
   modelled.
     logistic   q_ij = sigma(mu + a_i + b_j)                                   2N - 1 params
     aoceil     q_ij = U * AO_lam(mu + a_i + b_j), AO_lam(x) = 1 - (1 + lam e^x)^(-1/lam)
                (Aranda-Ordaz: lam = 1 is logistic, lam -> 0 the complementary log-log) with a
                ceiling U in (0, 1): a free, asymmetric saturating link       2N + 1 params
     strength   q_ij = sigma(c + u_i - u_j): one strength per item, the resident effect minus
                the invader effect (the most restrictive; Codex's example)     N params
   Each is TRANSITIVE: sign(q_ij - q_ji) = sign(d_i - d_j) for one score d per item. None is
   additive in A = q - q^T. The question is whether the observed cyclic residual survives:
     T_C     ||Q A(qbar)||^2, the raw cyclic energy (infer.py's T_C)
     C_fit   ||Q A(fit)||^2, the curl the bounded ladder itself makes
     R_C     ||Q A(qbar - fit)||^2, the cyclic energy the model leaves
     F_res   R_C / tau_C, tau_C the units' curl noise energy (as in infer.py)
     p_res   parametric-residual bootstrap: qbar* = fit + the mean of k resampled residual units
             per column, the model REFITTED to every draw, F* = R_C* / tau_C*. Approximate in the
             same way as infer.py's bootstrap (asymptotic in k; see there).
     R_C_nc  R_C - mean(R_C*): noise-corrected (the bootstrap mean is the noise that survives
             the refit). share_res_nc = R_C_nc / (T_A - tau_A) with the raw scale's paired
             signal energy, so it compares directly with infer's share_nc; survival =
             R_C_nc / (T_C - tau_C), the fraction of the noise-corrected cyclic energy left.
   and the same for the symmetric interaction (T_S, R_S, F_res_S, p_res_S).
"""
from __future__ import annotations

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hodge  # noqa: E402
import infer  # noqa: E402

MODELS = ("logistic", "aoceil", "strength")
DEFAULT_SCALES = ("logit:0.001", "logit:1e-06", "asin")


# ------------------------------------------------------------ transforms
def sigmoid(x):
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def transform(spec):
    """-> (h, eps): the endpoint transform named by spec, and its clip (None if it has none)."""
    if spec == "raw":
        return (lambda q: q), None
    if spec.startswith("logit:"):
        eps = float(spec.split(":", 1)[1])
        if not 0.0 < eps < 0.5:
            raise ValueError(spec)

        def h(q):
            q = min(max(q, eps), 1.0 - eps)
            return math.log(q / (1.0 - q))
        return h, eps
    if spec == "asin":
        return (lambda q: math.asin(math.sqrt(min(max(q, 0.0), 1.0)))), None
    raise ValueError(f"unknown scale {spec!r} (raw, logit:EPS, asin)")


def transform_rows(rows, spec):
    """Rows (analyze.run_rows) with s replaced by h(q) - h(f), q = s + f the endpoint. -> (rows,
    number of endpoints at or beyond the clip)."""
    h, eps = transform(spec)
    out, clipped = [], 0
    for x in rows:
        y = dict(x)
        if x.get("s") is not None:
            q = x["s"] + x["f0"]
            if eps is not None and (q <= eps or q >= 1 - eps):
                clipped += 1
            y["s"] = h(q) - h(x["f0"])
        out.append(y)
    return out, clipped


# ------------------------------------------------------------ models
class Model:
    """q_ij = g(eta_ij; phi). Identifiable parameters: the last item's a / b / u is minus the
    sum of the others."""

    def __init__(self, name, N):
        if name not in MODELS:
            raise ValueError(name)
        self.name, self.N = name, N
        self.P = {"logistic": 2 * N - 1, "aoceil": 2 * N + 1, "strength": N}[name]

    def _expand(self, v):
        return list(v) + [-sum(v)]

    def eval(self, th, cells):
        """-> (predictions, Jacobian rows) over cells [(i, j)]."""
        N, P, nm = self.N, self.P, self.name
        preds, J = [], []
        if nm == "strength":
            c, u = th[0], self._expand(th[1:N])
        else:
            mu, a, b = th[0], self._expand(th[1:N]), self._expand(th[N:2 * N - 1])
        if nm == "aoceil":
            # lam = l^2 >= 0 and U = 1 / (1 + om^2) <= 1: the complementary log-log limit (lam = 0) and
            # 'no ceiling' (U = 1) are reached at finite parameters, so a fit that wants them converges
            ell, om = th[-2], th[-1]
            lam = ell * ell
            U = 1.0 / (1.0 + om * om)
            dU = -2.0 * om * U * U
        for i, j in cells:
            row = [0.0] * P
            if nm == "strength":
                eta = c + u[i] - u[j]
            else:
                eta = mu + a[i] + b[j]
            x = min(max(eta, -40.0), 40.0)
            if nm == "aoceil":
                e = math.exp(x)
                t = lam * e
                base = 1.0 + t
                # rr = log(1 + lam e) / lam (w = exp(-rr)); the series in t = lam e is used only where
                # t is small (review round 3: a series in lam alone diverges for lam e >= 1)
                if t < 1e-4:
                    rr = e * (1.0 - t / 2.0 + t * t / 3.0)
                    drr = e * e * (-0.5 + 2.0 * t / 3.0 - 0.75 * t * t)   # d rr / d lam
                else:
                    rr = math.log1p(t) / lam
                    drr = (e / base - rr) / lam
                w = math.exp(-rr)
                g = U * (1.0 - w)
                d = U * e * w / base
                row[-2] = U * w * drr * 2.0 * ell                  # d g / d l
                row[-1] = (1.0 - w) * dU                           # d g / d om
            else:
                g = sigmoid(x)
                d = g * (1.0 - g)
            row[0] = d
            if nm == "strength":
                for t, sgn in ((i, 1.0), (j, -1.0)):
                    if t < N - 1:
                        row[1 + t] += sgn * d
                    else:
                        for s_ in range(N - 1):
                            row[1 + s_] -= sgn * d
            else:
                for t, off in ((i, 1), (j, N)):
                    if t < N - 1:
                        row[off + t] += d
                    else:
                        for s_ in range(N - 1):
                            row[off + s_] -= d
            preds.append(g)
            J.append(row)
        return preds, J

    def describe(self, th):
        N = self.N
        if self.name == "strength":
            return {"c": th[0], "u": self._expand(th[1:N])}
        d = {"mu": th[0], "a": self._expand(th[1:N]), "b": self._expand(th[N:2 * N - 1])}
        if self.name == "aoceil":
            d.update(lam=th[-2] ** 2, U=1.0 / (1.0 + th[-1] ** 2))
        return d


GTOL = 1e-9   # stationarity at the iteration cap: max |J'r| <= GTOL x max(1, ||y||)


def lm(model, cells, y, th0, iters=200, tol=1e-11):
    """Levenberg-Marquardt least squares; stops when an accepted step improves the SSE by less
    than tol (relative). -> (theta, SSE, converged). At the iteration cap the fit counts as
    converged only if it is stationary, max |J'r| <= GTOL max(1, ||y||) (review round 4: such
    fits are boundary infima - a fitted cell mean creeping to 0, an effect drifting to -inf, the
    SSE flat to ~1e-9 relative; anything else is NOT converged and decides nothing)."""
    th = list(th0)
    g, J = model.eval(th, cells)
    r = [a - b for a, b in zip(y, g)]
    S = sum(x * x for x in r)
    lam = 1e-3
    P = model.P
    floor = 1e-26 * max(1e-30, sum(v * v for v in y))   # an exact fit: nothing left to improve
    for _ in range(iters):
        if S <= floor:
            return th, S, True
        JtJ = [[0.0] * P for _ in range(P)]
        Jtr = [0.0] * P
        for row, ri in zip(J, r):
            for a_ in range(P):
                ra = row[a_]
                if ra:
                    Jtr[a_] += ra * ri
                    Ja = JtJ[a_]
                    for b_ in range(a_, P):
                        Ja[b_] += ra * row[b_]
        for a_ in range(P):
            for b_ in range(a_):
                JtJ[a_][b_] = JtJ[b_][a_]
        while True:
            M = [[JtJ[a_][b_] + (lam * JtJ[a_][a_] + 1e-18 if a_ == b_ else 0.0) for b_ in range(P)] for a_ in range(P)]
            try:
                step = hodge.solve(M, Jtr)
            except ValueError:
                step = None
            if step is not None:
                if max(abs(s_) for s_ in step) <= 1e-12 * (1.0 + max(abs(t) for t in th)):
                    return th, S, True   # nothing left to move
                thn = [t + s_ for t, s_ in zip(th, step)]
                gn, Jn = model.eval(thn, cells)
                rn = [a - b for a, b in zip(y, gn)]
                Sn = sum(x * x for x in rn)
                if Sn <= S:
                    done = S - Sn <= tol * max(S, 1e-30) or Sn <= floor
                    th, J, r, S = thn, Jn, rn, Sn
                    lam = max(lam / 3.0, 1e-9)
                    if done:
                        return th, S, True
                    break
            lam *= 10.0
            if lam > 1e6:
                return th, S, True   # no descent along even a short gradient step: a (local) minimum
    grad = max(abs(sum(row[a_] * ri for row, ri in zip(J, r))) for a_ in range(P))
    return th, S, grad <= GTOL * max(1.0, math.sqrt(sum(v * v for v in y)))


def _cells(N):
    return [(i, j) for i in range(N) for j in range(N) if i != j]


def initial(model_name, M, base=None):
    """Starting parameters: a two-way additive fit on the clipped logit scale (logistic), the
    logistic fit with lam = 1, U ~ 1 (aoceil), or its (a - b) / 2 (strength)."""
    N = len(M)
    if model_name == "logistic" or base is None:
        h, _ = transform("logit:0.001")
        Z = [[h(M[i][j]) if i != j else None for j in range(N)] for i in range(N)]
        mu, a, b, _ = hodge.twoway(Z)
        th = [mu] + a[:N - 1] + b[:N - 1]
        if model_name == "logistic":
            return th
        base = th
    mu, a, b = base[0], list(base[1:N]) + [-sum(base[1:N])], list(base[N:2 * N - 1]) + [-sum(base[N:2 * N - 1])]
    if model_name == "aoceil":
        return list(base[:2 * N - 1]) + [1.0, 0.05]   # lam = 1 (logistic), U = 0.9975
    u = [0.5 * (x - y) for x, y in zip(a, b)]
    return [mu] + u[:N - 1]


def fit(M, model_name, th0=None):
    """Fit one model to the mean matrix M[i][j] (invader i into resident j, diagonal None).
    -> dict(theta, F (fitted matrix), sse, converged, params)."""
    N = len(M)
    model = Model(model_name, N)
    cells = _cells(N)
    y = [M[i][j] for i, j in cells]
    if th0 is None:
        th0 = initial(model_name, M, fit(M, "logistic")["theta"] if model_name != "logistic" else None)
    th, sse, ok = lm(model, cells, y, th0)
    g, _ = model.eval(th, cells)
    F = [[None] * N for _ in range(N)]
    for (i, j), v in zip(cells, g):
        F[i][j] = v
    return {"model": model_name, "theta": th, "F": F, "sse": sse, "converged": ok, "params": model.describe(th)}


# ------------------------------------------------------------ energies
def _colmeans(M):
    """Matrix M[i][j] (i into j) -> infer's column layout m[j][i]."""
    N = len(M)
    return [[(M[i][j] if i != j else 0.0) for i in range(N)] for j in range(N)]


def energies(M):
    """-> (T_A, T_C, T_S) of a directed matrix M[i][j], as infer.block_stats defines them."""
    N = len(M)
    m = _colmeans(M)
    TA, TC = infer.energies(infer.antisym(m), N)
    return TA, TC, infer.sym_energy(infer.symm(m), N)


def _sub(M, F):
    N = len(M)
    return [[(M[i][j] - F[i][j]) if i != j else None for j in range(N)] for i in range(N)]


def model_test(zq, model_name, B=1999, seed=1, kind=infer.DEFAULT_KIND, TA_pair=None, tauA_pair=None):
    """Lack of fit of a bounded node-additive model for one condition. zq[p][r][i] = the
    endpoint q of replicate r of i invading resident p (i != p; [p][r][p] = 0), one unit per
    (column, replicate) as in infer.py. TA_pair / tauA_pair: the raw paired block's T_A and
    tau_A (infer.block_stats of the sham-paired units) for the share denominator."""
    N, k = len(zq), len(zq[0])
    m = infer.column_means(zq)
    M = [[(m[j][i] if i != j else None) for j in range(N)] for i in range(N)]
    st = infer.block_stats(zq)
    f = fit(M, model_name)
    F = f["F"]
    _, C_fit, _ = energies(F)
    RA, RC, RS = energies(_sub(M, F))
    res = infer.residual_units(zq)
    E = [[infer.unit_energies(u, N) for u in col] for col in res]
    rnd = random.Random(seed)
    cells = _cells(N)
    model = Model(model_name, N)
    yfit = [F[i][j] for i, j in cells]
    FC, FS, RCs, RSs, bad = [], [], [], [], 0
    for _ in range(B):
        plan = infer._draw_plan(rnd, kind, N, k)
        sb = infer._fast_stats(res, E, plan, kind)
        mb = sb["m"]
        yb = [v + mb[j][i] for v, (i, j) in zip(yfit, cells)]
        th, _, ok = lm(model, cells, yb, f["theta"])
        bad += not ok
        gb, _ = model.eval(th, cells)
        Mb = [[None] * N for _ in range(N)]
        for (i, j), a_, b_ in zip(cells, yb, gb):
            Mb[i][j] = a_ - b_
        _, rc, rs = energies(Mb)
        RCs.append(rc)
        RSs.append(rs)
        FC.append(infer._ratio(rc, sb["tauC"]))
        FS.append(infer._ratio(rs, sb["tauS"]))
    F_res = infer._ratio(RC, st["tauC"])
    F_res_S = infer._ratio(RS, st["tauS"])
    nullC = sum(RCs) / B
    nullS = sum(RSs) / B
    RC_nc = RC - nullC
    den = (TA_pair - tauA_pair) if TA_pair is not None else None
    P = N * (N - 1) // 2
    # an unconverged fit decides nothing (review round 4): no p-value rests on it
    ok_fit, ok_boot = bool(f["converged"]), bad == 0
    return {"model": model_name, "N": N, "k": k, "B": B, "kind": kind, "converged": f["converged"],
            "boot_not_converged": bad, "sse": f["sse"], "params": f["params"],
            "T_C": st["TC"], "tau_C": st["tauC"], "C_fit": C_fit, "R_A": RA, "R_C": RC,
            "F_res": F_res,
            "p_res": (1 + sum(1 for x in FC if x >= F_res)) / (B + 1) if ok_fit and ok_boot else None,
            "R_C_null": nullC, "R_C_nc": RC_nc,
            "share_res_nc": RC_nc / den if den and den > 0 else float("nan"),
            "survival": RC_nc / (st["TC"] - st["tauC"]) if st["TC"] > st["tauC"] else float("nan"),
            "dC_res": math.sqrt(max(0.0, RC_nc) / P),
            "T_S": st["TS"], "tau_S": st["tauS"], "R_S": RS, "F_res_S": F_res_S,
            "p_res_S": (1 + sum(1 for x in FS if x >= F_res_S)) / (B + 1) if ok_fit and ok_boot else None,
            "R_S_null": nullS, "R_S_nc": RS - nullS,
            "p_res_flip": (infer.flip_p_vectors([residual_replicate_vectors(zq, model_name, f)[0]])
                           if ok_fit else None)}


# ------------------------------------------------------- the frozen co-primary (hypothesis 1b)
# Review round 3: the logistic residual test as a co-primary needs ONE joint statistic over the
# four primary matrices (two home regimes x two assays), four separate mean fits, paired resampling
# (the assays of one regime share their units; regimes are independent) and a fixed multiplicity
# family. Frozen here:
#   H1b  "the four primary matrices are bounded logistic ladders": for every condition c, fit
#        sigma(mu_c + a_ci + b_cj) to that matrix's endpoint means; project each replicate r's cell
#        residuals d_cr = y_cr - fit_c off the model's tangent space at the fit (P_perp = I -
#        J (J'J)^-1 J'), take their curl, v_cr = Q A(P_perp d_cr), and sign-flip whole replicates
#        jointly over a regime's assays and independently across regimes:
#        T = sum_g ||sum_r delta_r (v_gr concatenated over the group's conditions)||^2.
#        At the least-squares fit P_perp leaves the residual of the means unchanged, so
#        T(+1) = k^2 sum_c R_C,c. Under H0 the projected replicate vectors have mean ~0 (to first
#        order in the noise); the test is exact only for independent, centrally symmetric v_cr and
#        to first order in the fit (the fit is not redone per pattern) - its level is calibrated
#        (calibrate.py --compound). The joint refitting bootstrap (residual_omnibus(B > 0): every
#        draw refits all four models, paired plans) is reported beside it.
#   Family: hypotheses 1-11 of the stats spec plus H1b = 12 tests, Holm; planning threshold
#        ALPHA_FAMILY = 0.05 / 12.
#   Claim rule: "a cyclic component beyond bounded (logistic) transitivity" needs BOTH H1 (raw
#        grouped sign-flip omnibus) and H1b rejected by Holm over the 12-test family; for planning
#        and calibration, both p <= 0.05/12 (sufficient for both under Holm, whatever the order).
#   Fit failures (review round 4): if any of the four logistic mean fits did not converge, H1b is
#        INVALID: p_flip is None (the computed value is kept as p_flip_unconverged, a diagnostic),
#        so neither H1b nor the claim can reject; calibration counts such a dataset as a
#        non-rejection and keeps it in the denominator. Likewise the refitting bootstrap's p_boot is
#        None if any of its refits did not converge (boot_not_converged counts them).
CO_PRIMARY_MODEL = "logistic"
ALPHA_FAMILY = 0.05 / 12


def _inverse(Mx):
    n = len(Mx)
    return [list(col) for col in zip(*[hodge.solve(Mx, [1.0 if a == b else 0.0 for a in range(n)]) for b in range(n)])]


def residual_replicate_vectors(zq, model_name=CO_PRIMARY_MODEL, fitres=None):
    """Per replicate r: Q A(P_perp (y_r - fit)), the curl of replicate r's cell residuals after
    projecting off the fitted model's tangent space. -> (vectors, fit)."""
    N, k = len(zq), len(zq[0])
    m = infer.column_means(zq)
    M = [[(m[j][i] if i != j else None) for j in range(N)] for i in range(N)]
    f = fitres or fit(M, model_name)
    model = Model(model_name, N)
    cells = _cells(N)
    g, J = model.eval(f["theta"], cells)
    P = model.P
    JtJ = [[sum(row[a] * row[b] for row in J) for b in range(P)] for a in range(P)]
    for a in range(P):
        JtJ[a][a] += 1e-12 * max(JtJ[a][a], 1e-30)
    inv = _inverse(JtJ)
    out = []
    for r in range(k):
        d = [zq[j][r][i] - gv for (i, j), gv in zip(cells, g)]
        Jtd = [sum(row[a] * dv for row, dv in zip(J, d)) for a in range(P)]
        co = [sum(inv[a][b] * Jtd[b] for b in range(P)) for a in range(P)]
        mm = [[0.0] * N for _ in range(N)]
        for (i, j), dv, row in zip(cells, d, J):
            mm[j][i] = dv - sum(row[a] * co[a] for a in range(P))
        out.append(infer.curl_vec(infer.antisym(mm), N)[0])
    return out, f


def residual_omnibus(groups, model_name=CO_PRIMARY_MODEL, B=0, seed=1, kind=infer.DEFAULT_KIND, fits=None):
    """H1b over independent groups of aligned conditions (groups[g][c] = endpoint units zq).
    -> dict: F_res_joint = sum R_C / sum tau_C, p_flip (the frozen decision; None = INVALID when a
    mean fit did not converge, see above), p_boot (joint refitting bootstrap with paired plans, if
    B > 0; None if any refit did not converge), per-condition R_C / C_fit / T_C / converged, and
    'valid' / 'invalid' / 'diagnostics'."""
    fl = [[fit_matrix(zq, model_name) if fits is None else fits[g][c] for c, zq in enumerate(zs)]
          for g, zs in enumerate(groups)]
    gv = []
    per = []
    for g, zs in enumerate(groups):
        vec_c = [residual_replicate_vectors(zq, model_name, fl[g][c])[0] for c, zq in enumerate(zs)]
        k = len(vec_c[0])
        gv.append([[x for vc in vec_c for x in vc[r]] for r in range(k)])
        for c, zq in enumerate(zs):
            st = infer.block_stats(zq)
            M = _means(zq)
            per.append({"group": g, "cond": c, "T_C": st["TC"], "tau_C": st["tauC"],
                        "C_fit": energies(fl[g][c]["F"])[1], "R_C": energies(_sub(M, fl[g][c]["F"]))[1],
                        "converged": bool(fl[g][c]["converged"]), "sse": fl[g][c]["sse"]})
    F = infer._ratio(sum(x["R_C"] for x in per), sum(x["tau_C"] for x in per))
    bad = [f"{x['group']}/{x['cond']}" for x in per if not x["converged"]]
    p_flip = infer.flip_p_vectors(gv)
    out = {"model": model_name, "groups": len(groups), "conditions": len(per), "F_res_joint": F,
           "p_flip": None if bad else p_flip, "p_flip_unconverged": p_flip if bad else None,
           "valid": not bad, "invalid": (f"logistic mean fit(s) not converged: group/condition {' '.join(bad)}"
                                         if bad else None),
           "fits_converged": len(per) - len(bad), "per_condition": per, "B": B, "p_boot": None,
           "boot_not_converged": 0,
           "flip_min_p": math.prod(1.0 / (1 << (len(zs[0][0]) - 1)) for zs in groups)}
    if B > 0:
        rnd = random.Random(seed)
        shape = [(len(zs[0]), len(zs[0][0])) for zs in groups]
        prep = []
        for g, zs in enumerate(groups):
            for c, zq in enumerate(zs):
                res = infer.residual_units(zq)
                N = len(zq)
                prep.append((g, res, [[infer.unit_energies(u, N) for u in col] for col in res], fl[g][c],
                             Model(model_name, N), _cells(N)))
        ge = nbad = 0
        for _ in range(B):
            plans = [infer._draw_plan(rnd, kind, N_, k_) for N_, k_ in shape]
            num = den = 0.0
            ok_all = True
            for g, res, E, f, model, cells in prep:
                sb = infer._fast_stats(res, E, plans[g], kind)
                mb = sb["m"]
                yb = [f["F"][i][j] + mb[j][i] for i, j in cells]
                th, _, ok = lm(model, cells, yb, f["theta"])
                ok_all = ok_all and ok
                gb, _ = model.eval(th, cells)
                N = model.N
                Mb = [[None] * N for _ in range(N)]
                for (i, j), a_, b_ in zip(cells, yb, gb):
                    Mb[i][j] = a_ - b_
                num += energies(Mb)[1]
                den += sb["tauC"]
            nbad += not ok_all
            ge += infer._ratio(num, den) >= F
        out["boot_not_converged"] = nbad
        # a draw whose refit did not converge has no valid statistic: the bootstrap p is then not
        # reported (review round 4: never a rejection resting on an unfinished optimization)
        out["p_boot"] = (1 + ge) / (B + 1) if nbad == 0 and out["valid"] else None
    return out


def _means(zq):
    N = len(zq)
    m = infer.column_means(zq)
    return [[(m[j][i] if i != j else None) for j in range(N)] for i in range(N)]


def fit_matrix(zq, model_name=CO_PRIMARY_MODEL, th0=None):
    return fit(_means(zq), model_name, th0)


# ------------------------------------------------------------ self-test
def selftest():
    rnd = random.Random(5)
    # Codex's example: a perfectly ordered logistic ladder (strengths 0, 1, 2 from logit 0.05) has
    # reciprocal differences 0.10617 and 0.27293 and triangle circulation -0.0606, no ordinal cycle
    f0 = 0.05
    L0 = math.log(f0 / (1 - f0))
    u = [0.0, 1.0, 2.0]
    q = [[sigmoid(L0 + u[i] - u[j]) if i != j else None for j in range(3)] for i in range(3)]
    assert abs((q[1][0] - q[0][1]) - 0.10617) < 1e-4 and abs((q[2][0] - q[0][2]) - 0.27293) < 1e-4
    circ = (q[0][1] - q[1][0]) + (q[1][2] - q[2][1]) + (q[2][0] - q[0][2])
    assert abs(circ - 0.0606) < 1e-3, circ   # orientation 0 -> 1 -> 2 -> 0
    # a bounded transitive two-way world: raw cyclic energy > 0; every model that contains it
    # leaves (numerically) none; the strength model cannot fit separate invader / resident effects
    N = 7
    a = [rnd.gauss(0, 0.9) for _ in range(N)]
    b = [rnd.gauss(0, 0.6) for _ in range(N)]
    M = [[sigmoid(-2.5 + a[i] + b[j]) if i != j else None for j in range(N)] for i in range(N)]
    TA, TC, TS = energies(M)
    assert TC > 1e-4 * TA, (TC, TA)
    fr = fit(M, "logistic")
    assert fr["converged"] and energies(_sub(M, fr["F"]))[1] < 1e-14 * TC, energies(_sub(M, fr["F"]))
    fr = fit(M, "aoceil")   # (its optimum is on the boundary U -> 1, lam = 1: approached, not reached)
    assert energies(_sub(M, fr["F"]))[1] < 1e-8 * TC, energies(_sub(M, fr["F"]))
    # a free ceiling and asymmetric link is recovered
    lam0, U0 = 0.3, 0.4
    Mao = [[U0 * (1 - (1 + lam0 * math.exp(-1.0 + a[i] + b[j])) ** (-1 / lam0)) if i != j else None
            for j in range(N)] for i in range(N)]
    fr = fit(Mao, "aoceil")
    assert fr["sse"] < 1e-16 and abs(fr["params"]["lam"] - lam0) < 1e-4 and abs(fr["params"]["U"] - U0) < 1e-4, fr["params"]
    # a sign-reversing cycle planted on top survives every transitive model
    Mc = [row[:] for row in M]
    for (i, j) in ((0, 1), (1, 2), (2, 0)):
        Mc[i][j] += 0.08
        Mc[j][i] -= 0.08
    for nm in MODELS:
        fr = fit(Mc, nm)
        assert energies(_sub(Mc, fr["F"]))[1] > 0.25 * 3 * 0.16 ** 2, (nm, energies(_sub(Mc, fr["F"])))
    # the bootstrap test: units built from the logistic world with heteroscedastic noise; at this
    # scale a pure bounded ladder is not rejected but the planted cycle is, while the raw-scale
    # lack of fit flags both
    k = 6
    sds = [[0.0 if i == p else rnd.choice((0.004, 0.01, 0.02)) for i in range(N)] for p in range(N)]

    def units(Mx):
        return [[[Mx[i][p] + sds[p][i] * rnd.gauss(0, 1) if i != p else 0.0 for i in range(N)]
                 for _ in range(k)] for p in range(N)]
    z0 = units([[sigmoid(-2.0 + 1.6 * a[i] + b[j]) if i != j else None for j in range(N)] for i in range(N)])
    t0 = model_test(z0, "logistic", B=199, seed=2)
    assert t0["p_res"] > 0.01 and t0["C_fit"] > 0, t0
    assert infer.infer([z0], B=199, seed=2)["p_lof"] <= 0.01   # raw scale: "cycle"
    zc = units(Mc)
    tc = model_test(zc, "logistic", B=199, seed=2)
    assert tc["p_res"] <= 0.01 and tc["R_C_nc"] > 0, tc
    # the frozen co-primary H1b: projected replicate vectors reproduce the residual cyclic energy
    # (T(+1) = k^2 R_C), a pure bounded ladder is not flagged, a sign-reversing cycle is, and groups
    # flip independently (floor 1/2^(k-1) per group)
    N5, k5 = 5, 6
    a5 = [rnd.gauss(0, 0.9) for _ in range(N5)]
    b5 = [rnd.gauss(0, 0.6) for _ in range(N5)]

    def units5(cyc):
        Mx = [[sigmoid(-2.2 + a5[i] + b5[j]) if i != j else None for j in range(N5)] for i in range(N5)]
        for (i, j) in ((0, 1), (1, 2), (2, 0)):
            Mx[i][j] += cyc
            Mx[j][i] -= cyc
        return [[[Mx[i][p] + 0.004 * rnd.gauss(0, 1) if i != p else 0.0 for i in range(N5)] for _ in range(k5)]
                for p in range(N5)]
    zl = units5(0.0)
    vecs, f5 = residual_replicate_vectors(zl)
    tplus = sum(sum(v[e] for v in vecs) ** 2 for e in range(len(vecs[0])))
    want = k5 * k5 * energies(_sub(_means(zl), f5["F"]))[1]   # (exact at the LS optimum; up to its tolerance)
    assert abs(tplus - want) < 1e-6 * max(tplus, 1e-30), (tplus, want)
    om = residual_omnibus([[zl, units5(0.0)], [units5(0.0)]])
    assert om["p_flip"] > 0.01 and om["conditions"] == 3 and abs(om["flip_min_p"] - 1 / 32 ** 2) < 1e-15, om["p_flip"]
    oc = residual_omnibus([[units5(0.08), units5(0.08)], [units5(0.08)]], B=19, seed=3)
    assert oc["p_flip"] <= 1 / 32 ** 2 + 1e-12 and oc["p_boot"] == 1 / 20, (oc["p_flip"], oc["p_boot"])
    assert oc["valid"] and oc["fits_converged"] == 3 and oc["boot_not_converged"] == 0, oc["invalid"]
    # an unconverged mean fit makes H1b invalid (no p-value, the computed one kept as a diagnostic)
    zc5 = units5(0.08)
    fu = dict(fit_matrix(zc5), converged=False)
    ou = residual_omnibus([[zc5]], fits=[[fu]], B=5)
    assert ou["p_flip"] is None and ou["p_boot"] is None and not ou["valid"] and "not converged" in ou["invalid"]
    assert ou["p_flip_unconverged"] is not None and ou["fits_converged"] == 0, ou
    # the Aranda-Ordaz link is finite and accurate at every lam >= 0, also where lam e^eta is large for
    # tiny lam (review round 3: the old series overflowed at eta = 30, lam = 1e-10), and its Jacobian
    # matches finite differences in the series, the exact and the cloglog regime
    m3 = Model("aoceil", 3)
    cells3 = _cells(3)
    for eta, lam_ in ((30.0, 1e-10), (30.0, 0.0), (-3.0, 1e-12), (2.0, 0.7), (35.0, 1e-16), (-5.0, 4.0)):
        th = [eta, 0.0, 0.0, 0.0, 0.0, math.sqrt(lam_), 0.3]
        g, J = m3.eval(th, cells3)
        assert all(0.0 <= v <= 1.0 for v in g), (eta, lam_, g)
        exact = math.log1p(lam_ * math.exp(eta)) / lam_ if lam_ > 0 else math.exp(eta)
        U = 1.0 / 1.09
        assert abs(g[0] - U * (1.0 - math.exp(-exact))) < 1e-12, (eta, lam_)
        for pk in (0, 5, 6):
            hh = 1e-6 * max(1.0, abs(th[pk]))
            tp, tm = list(th), list(th)
            tp[pk] += hh
            tm[pk] -= hh
            num = (m3.eval(tp, cells3)[0][0] - m3.eval(tm, cells3)[0][0]) / (2 * hh)
            assert abs(num - J[0][pk]) < 1e-5 * max(1.0, abs(num)), (eta, lam_, pk, num, J[0][pk])
    # transforms
    h, eps = transform("logit:0.001")
    assert eps == 0.001 and abs(h(0.0) - math.log(0.001 / 0.999)) < 1e-12 and h(0.5) == 0.0
    h, eps = transform("asin")
    assert eps is None and abs(h(1.0) - math.pi / 2) < 1e-12
    rows = [{"s": -0.05, "f0": 0.05}, {"s": None, "f0": 0.05}, {"s": 0.1, "f0": 0.05}]
    tr, nclip = transform_rows(rows, "logit:0.001")
    assert nclip == 1 and tr[1]["s"] is None and abs(tr[2]["s"] - (math.log(0.15 / 0.85) - math.log(0.05 / 0.95))) < 1e-12
    print("bounded selftest: ok")


if __name__ == "__main__":
    selftest()

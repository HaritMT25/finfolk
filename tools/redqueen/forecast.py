#!/usr/bin/env python3
"""forecast.py: the Level-2 LINEAR forecasts and their limits (design v4 §10.6). Only three forecasters are
registered (the neural and nearest-trajectory / nonlinear families are removed):
  persistence  Z(t0 + H) = Z(t0);
  drift        the prefix-fitted linear drift: a GLS line through the window's profiles (each weighted by its
               measurement covariance), extrapolated to t0 + H;
  lss          regularized stochastic LINEAR state-space dynamics: z(s + 1) = A z(s) + B x(s) + c + w,
               w ~ N(0, Q); y(s) = z(s) + v(s), v ~ N(0, R(s)) (R the profile's posterior covariance: the
               snapshot-specific measurement noise is carried into the observation noise, v4 §10.1).
               Fitted by EM (Kalman filter + RTS smoother) on the TRAINING worlds' native 1M series, with a
               Q-weighted ridge pulling A toward I and B toward 0 (penalty LAMBDA); LAMBDA selected on the
               VALIDATION worlds' native series from the registered grid (the primary horizon's measurement-
               corrected MSE; ties to the larger LAMBDA); forecasts by filtering the window, then predicting H
               steps with the covariates held at their last value.
INPUTS (v4 §10.6): the WINDOW = 5 previous 1M profiles (t0 - 4 .. t0, all present and not extinct; else the
origin is unavailable), their covariances and the covariates (abundance of both guilds, energy summary,
turnover; standardized by the training worlds' means and SDs). Never future outcomes, features or seeds.
Extinction is an ABSORBING outcome treated separately: an extinct future enters no profile metric and is
counted per origin.
PREDICTIVE COVARIANCE: lss its model's; persistence and drift the training worlds' native H-step error
covariance, measurement-corrected (minus the mean target covariance) and PSD-clipped.

EVALUATION (`evaluate`) against the fork futures of every origin (forks.py: four independently reseeded
branches, primary; the original continuation a fifth, exchangeability-qualified sensitivity). Per origin and
forecaster, with y the measured futures (covariances R_f; shared measurement covariance S0 common to the
futures):
  MSE        mean over the reseeded futures of ||y_f - z_hat||^2, minus the mean tr R_f;
  V_fork     tr of the reseeds' sample covariance (ddof 1) minus (mean tr R_f - tr S0): the conditional
             (chance) variance given the saved state;
  REDUCIBLE  MSE - V_fork: the error reducible given the saved state under reseeding (never split into
             representation loss and learning error; negative finite-sample values retained);
  energy score (Monte Carlo, ES_DRAWS seeded draws from N(z_hat, P + R_f)) and calibration (the PIT of the
             Mahalanobis distance through the chi-square CDF; coverage of the 50% and 90% ellipsoids), as
             supporting assessments.
Pooled per horizon and forecaster: means over origins with a root-world cluster bootstrap (whole worlds
resampled with their origins; BOOT draws, percentile intervals). Twelve root worlds and 36 origins are not
144 independent replicates. Ten-million-step forks do not establish long-horizon predictability.
SEALING: `predict` fits (training), selects (validation) and writes every origin's forecasts; its plain
sha256 is what sealing.py commits (TEST_PRED_SHA). `evaluate` refuses predictions whose sha256 is not the
committed one given with --pred-sha.

    forecast.py predict --profiles profiles.json --futures futures.json --out forecasts.json
    forecast.py evaluate --predictions forecasts.json --pred-sha SHA --futures futures.json --out eval.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
import rqlib  # noqa: E402

PROFILES = "finfolk.redqueen.profiles/1"
FUTURES = "finfolk.redqueen.futures/1"
PRED = "finfolk.redqueen.forecasts/1"
EVAL = "finfolk.redqueen.forecast_eval/1"
FORECASTERS = ("persistence", "drift", "lss")
WINDOW = 5
HORIZONS = (1, 4, 10)
PRIMARY = 10
LAMBDAS = (0.1, 1.0, 10.0, 100.0)
COVARIATES = ("abundance_prey", "abundance_pred", "energy", "turnover")
EM_ITERS = 50
EM_TOL = 1e-8
ES_DRAWS = 2000
BOOT = 999
SEED_NS = "rq2026-forecast"
SPLITS = ("training", "validation", "test")


class ForecastError(Exception):
    pass


def _np():
    import numpy as np
    return np


# ================================================================== inputs
def load_profiles(doc):
    """Validate a profiles/1 document -> {world: {"split", "block", "t", "z" (n x d), "R" (n x d x d), "x"
    (n x k), "extinct" (n)}}, d."""
    np = _np()
    if doc.get("schema") != PROFILES:
        raise ForecastError(f"profiles schema {doc.get('schema')!r}")
    d = doc.get("dim")
    if not isinstance(d, int) or d < 1:
        raise ForecastError("profiles: dim must be a positive integer")
    out = {}
    for w, v in sorted(doc.get("worlds", {}).items()):
        if v.get("split") not in SPLITS:
            raise ForecastError(f"{w}: split {v.get('split')!r}")
        ser = sorted(v.get("series", []), key=lambda e: e["t"])
        ts = [e["t"] for e in ser]
        if any(not isinstance(t, int) for t in ts) or len(set(ts)) != len(ts):
            raise ForecastError(f"{w}: times must be distinct integers (M)")
        ext = np.array([bool(e.get("extinct")) for e in ser])
        if ext.any() and not ext[np.argmax(ext):].all():
            raise ForecastError(f"{w}: extinction is absorbing (a live profile after an extinct one)")
        z = np.full((len(ser), d), np.nan)
        R = np.zeros((len(ser), d, d))
        x = np.zeros((len(ser), len(COVARIATES)))
        for i, e in enumerate(ser):
            if ext[i]:
                continue
            zi, Ri = np.asarray(e["z"], float), np.asarray(e["cov"], float)
            if zi.shape != (d,) or Ri.shape != (d, d) or not np.all(np.isfinite(zi)) or not np.all(np.isfinite(Ri)):
                raise ForecastError(f"{w} t={e['t']}: z must be {d} finite values, cov {d} x {d}")
            if np.max(np.abs(Ri - Ri.T)) > 1e-12 * max(1.0, np.max(np.abs(Ri))) or np.min(np.linalg.eigvalsh(Ri)) < -1e-12:
                raise ForecastError(f"{w} t={e['t']}: cov is not symmetric PSD")
            cv = e.get("covariates") or {}
            if set(cv) != set(COVARIATES) or not all(isinstance(cv[k], (int, float)) and math.isfinite(cv[k]) for k in COVARIATES):
                raise ForecastError(f"{w} t={e['t']}: covariates must be exactly {COVARIATES}, finite")
            z[i], R[i], x[i] = zi, Ri, [cv[k] for k in COVARIATES]
        out[w] = {"split": v["split"], "block": v.get("block"), "t": np.array(ts, int), "z": z, "R": R, "x": x,
                  "extinct": ext}
    if not out:
        raise ForecastError("profiles: no worlds")
    return out, d


def window(W, t0):
    """The registered window (t0 - 4 .. t0, every 1M present and not extinct) -> row indices, or None."""
    np = _np()
    idx = []
    for t in range(t0 - WINDOW + 1, t0 + 1):
        k = np.flatnonzero(W["t"] == t)
        if not len(k) or W["extinct"][k[0]]:
            return None
        idx.append(int(k[0]))
    return idx


def at(W, t):
    np = _np()
    k = np.flatnonzero(W["t"] == t)
    return None if not len(k) or W["extinct"][k[0]] else int(k[0])


def native_origins(W, H):
    """Every native origin with a full window and a live, measured target t0 + H."""
    return [(int(t0), idx, at(W, int(t0) + H)) for t0 in W["t"].tolist()
            if (idx := window(W, int(t0))) is not None and at(W, int(t0) + H) is not None]


def standardizer(worlds):
    np = _np()
    X = np.vstack([W["x"][~W["extinct"]] for W in worlds.values() if W["split"] == "training"])
    if not len(X):
        raise ForecastError("no training profiles")
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd = np.where(sd > 0, sd, 1.0)
    return mu.tolist(), sd.tolist()


def psd_clip(M):
    np = _np()
    M = (M + M.T) / 2
    w, V = np.linalg.eigh(M)
    return (V * np.clip(w, 0.0, None)) @ V.T


# ================================================================== the forecasters
def persistence(W, idx, H):
    return W["z"][idx[-1]].copy()


def drift(W, idx, H):
    """The GLS line through the window's profiles (weights R^-1, jittered), extrapolated H steps."""
    np = _np()
    d = W["z"].shape[1]
    t = W["t"][idx].astype(float)
    tc = t - t.mean()
    A = np.zeros((2 * d, 2 * d))
    b = np.zeros(2 * d)
    for k, i in enumerate(idx):
        Ri = W["R"][i] + 1e-9 * max(1e-12, np.trace(W["R"][i]) / d) * np.eye(d)
        Wi = np.linalg.inv(Ri)
        X = np.hstack([np.eye(d), tc[k] * np.eye(d)])
        A += X.T @ Wi @ X
        b += X.T @ Wi @ W["z"][i]
    th = np.linalg.solve(A, b)
    return th[:d] + th[d:] * (t[-1] + H - t.mean())


class LSS:
    """The regularized stochastic linear state-space model (see the module docstring)."""

    def __init__(self, d, k, lam, mu, sd):
        np = _np()
        self.d, self.k, self.lam = d, k, lam
        self.mu, self.sd = np.asarray(mu, float), np.asarray(sd, float)
        self.Th = np.hstack([np.eye(d), np.zeros((d, k)), np.zeros((d, 1))])
        self.Q = 0.01 * np.eye(d)

    def phi(self, x):
        np = _np()
        return np.concatenate([(np.asarray(x, float) - self.mu) / self.sd, [1.0]])

    def _smooth(self, z, R, x):
        """Kalman filter + RTS smoother over one live segment -> smoothed means, covariances, lag-one
        cross-covariances, log-likelihood."""
        np = _np()
        n, d = z.shape
        A, Bc = self.Th[:, :d], self.Th[:, d:]
        mf, Pf, mp, Pp = np.zeros((n, d)), np.zeros((n, d, d)), np.zeros((n, d)), np.zeros((n, d, d))
        ll = 0.0
        m, P = z[0].copy(), R[0] + self.Q
        for s in range(n):
            if s:
                m, P = A @ mf[s - 1] + Bc @ self.phi(x[s - 1]), A @ Pf[s - 1] @ A.T + self.Q
            mp[s], Pp[s] = m, P
            S = P + R[s]
            Si = np.linalg.inv(S)
            r = z[s] - m
            sign, logdet = np.linalg.slogdet(S)
            ll += -0.5 * (r @ Si @ r + logdet + d * math.log(2 * math.pi))
            Kg = P @ Si
            mf[s], Pf[s] = m + Kg @ r, P - Kg @ S @ Kg.T
        ms, Ps, C = mf.copy(), Pf.copy(), np.zeros((n, d, d))
        for s in range(n - 2, -1, -1):
            J = Pf[s] @ A.T @ np.linalg.inv(Pp[s + 1])
            ms[s] = mf[s] + J @ (ms[s + 1] - mp[s + 1])
            Ps[s] = Pf[s] + J @ (Ps[s + 1] - Pp[s + 1]) @ J.T
            C[s + 1] = Ps[s + 1] @ J.T                          # Cov(z_{s+1}, z_s | all)
        return ms, Ps, C, ll

    def fit(self, segments):
        """EM over the live segments [(z, R, x)] (consecutive 1M rows)."""
        np = _np()
        d, k = self.d, self.k
        D = np.diag([1.0] * (d + k) + [0.0])
        Th0 = np.hstack([np.eye(d), np.zeros((d, k + 1))])
        prev = -math.inf
        for _ in range(EM_ITERS):
            S10 = np.zeros((d, d + k + 1))
            S00 = np.zeros((d + k + 1, d + k + 1))
            S11 = np.zeros((d, d))
            n, ll = 0, 0.0
            for z, R, x in segments:
                ms, Ps, C, l_ = self._smooth(z, R, x)
                ll += l_
                for s in range(len(z) - 1):
                    f = self.phi(x[s])
                    Ezz = Ps[s] + np.outer(ms[s], ms[s])
                    E00 = np.zeros((d + k + 1, d + k + 1))
                    E00[:d, :d] = Ezz
                    E00[:d, d:] = np.outer(ms[s], f[:])
                    E00[d:, :d] = E00[:d, d:].T
                    E00[d:, d:] = np.outer(f, f)
                    E10 = np.hstack([C[s + 1] + np.outer(ms[s + 1], ms[s]), np.outer(ms[s + 1], f)])
                    S00 += E00
                    S10 += E10
                    S11 += Ps[s + 1] + np.outer(ms[s + 1], ms[s + 1])
                    n += 1
            if not n:
                raise ForecastError("the state-space fit has no consecutive training profiles")
            self.Th = (S10 + self.lam * Th0 @ D) @ np.linalg.inv(S00 + self.lam * D)
            Qn = (S11 - self.Th @ S10.T - S10 @ self.Th.T + self.Th @ S00 @ self.Th.T) / n
            Qn = psd_clip(Qn)
            self.Q = Qn + 1e-8 * max(1e-12, np.trace(Qn) / d) * np.eye(d)
            if abs(ll - prev) <= EM_TOL * max(1.0, abs(ll)):
                break
            prev = ll
        self.loglik = ll
        return self

    def forecast(self, W, idx, H):
        """Filter the window, then predict H steps (covariates held at their last value) -> (mean, cov)."""
        np = _np()
        d = self.d
        ms, Ps, _, _ = self._smooth(W["z"][idx], W["R"][idx], W["x"][idx])
        m, P = ms[-1], Ps[-1]                                   # (the last smoothed = filtered state)
        A, Bc = self.Th[:, :d], self.Th[:, d:]
        u = Bc @ self.phi(W["x"][idx[-1]])
        for _ in range(H):
            m, P = A @ m + u, A @ P @ A.T + self.Q
        return m, psd_clip(P)


def segments(worlds, split):
    np = _np()
    out = []
    for W in worlds.values():
        if W["split"] != split:
            continue
        live = np.flatnonzero(~W["extinct"])
        if not len(live):
            continue
        run = [int(live[0])]
        for i in live[1:].tolist():
            if W["t"][i] == W["t"][run[-1]] + 1:
                run.append(i)
            else:
                if len(run) > 1:
                    out.append((W["z"][run], W["R"][run], W["x"][run]))
                run = [i]
        if len(run) > 1:
            out.append((W["z"][run], W["R"][run], W["x"][run]))
    return out


def corrected_mse(worlds, split, H, fc):
    """The measurement-corrected H-step MSE of a forecaster over a split's native origins."""
    np = _np()
    e = []
    for W in worlds.values():
        if W["split"] != split:
            continue
        for t0, idx, j in native_origins(W, H):
            zh = fc(W, idx, H)
            e.append(float(np.sum((W["z"][j] - zh) ** 2) - np.trace(W["R"][j])))
    return (float(np.mean(e)), len(e)) if e else (None, 0)


def error_cov(worlds, H, fc):
    """persistence / drift predictive covariance: the training native H-step error covariance minus the mean
    target covariance, PSD-clipped."""
    np = _np()
    E, Rt = [], []
    for W in worlds.values():
        if W["split"] != "training":
            continue
        for t0, idx, j in native_origins(W, H):
            E.append(W["z"][j] - fc(W, idx, H))
            Rt.append(W["R"][j])
    if len(E) < 2:
        raise ForecastError(f"fewer than two training native origins at H = {H}")
    E = np.array(E)
    return psd_clip(np.cov(E.T, ddof=1).reshape(E.shape[1], E.shape[1]) - np.mean(Rt, axis=0))


def fit_all(worlds, d, horizons=HORIZONS, primary=PRIMARY, lambdas=LAMBDAS):
    """Training fits, the LAMBDA selection on validation -> the model record."""
    mu, sd = standardizer(worlds)
    segs = segments(worlds, "training")
    sel = []
    for lam in lambdas:
        m = LSS(d, len(COVARIATES), lam, mu, sd).fit(segs)
        mse, n = corrected_mse(worlds, "validation", primary, lambda W, idx, H, m=m: m.forecast(W, idx, H)[0])
        if mse is None:
            raise ForecastError(f"no validation native origin at the primary horizon {primary}")
        sel.append((mse, -lam, m))
    mse, neg, model = min(sel, key=lambda r: (r[0], r[1]))
    covs = {fn.__name__: {H: error_cov(worlds, H, fn) for H in horizons} for fn in (persistence, drift)}
    return {"lss": model, "lambda": -neg, "selection": [{"lambda": -r[1], "validation_mse": r[0]} for r in sel],
            "covs": covs, "standardizer": {"mean": mu, "sd": sd}}


def predict(worlds, d, origins, model, horizons=HORIZONS):
    """Every origin's forecasts (all three forecasters) -> records."""
    out = []
    for o in origins:
        W = worlds.get(o["world"])
        H = o["horizon"]
        rec = {"world": o["world"], "t0": o["t0"], "horizon": H}
        idx = window(W, o["t0"]) if W is not None else None
        if idx is None or H not in horizons:
            rec.update(available=False, reason="no complete live window" if idx is None else f"horizon {H} unregistered")
            out.append(rec)
            continue
        m, P = model["lss"].forecast(W, idx, H)
        rec.update(available=True, forecasts={
            "persistence": {"z": persistence(W, idx, H).tolist(), "cov": model["covs"]["persistence"][H].tolist()},
            "drift": {"z": drift(W, idx, H).tolist(), "cov": model["covs"]["drift"][H].tolist()},
            "lss": {"z": m.tolist(), "cov": P.tolist()}})
        out.append(rec)
    return out


# ================================================================== evaluation
def _gammp(a, x):
    """The regularized lower incomplete gamma P(a, x) (series / continued fraction)."""
    if x <= 0:
        return 0.0
    gln = math.lgamma(a)
    if x < a + 1:
        ap, s, de = a, 1.0 / a, 1.0 / a
        for _ in range(1000):
            ap += 1
            de *= x / ap
            s += de
            if abs(de) < abs(s) * 1e-15:
                break
        return s * math.exp(-x + a * math.log(x) - gln)
    b, c, dd = x + 1 - a, 1e300, 1.0 / (x + 1 - a)
    h = dd
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2
        dd = an * dd + b
        dd = 1e-300 if abs(dd) < 1e-300 else dd
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        dd = 1.0 / dd
        de = dd * c
        h *= de
        if abs(de - 1) < 1e-15:
            break
    return 1.0 - math.exp(-x + a * math.log(x) - gln) * h


def chi2_cdf(q, d):
    return _gammp(d / 2.0, q / 2.0)


def energy_score(zh, P, y, rng, draws=ES_DRAWS):
    """ES of N(zh, P) at y (Monte Carlo: E||X - y|| - 1/2 E||X - X'||)."""
    np = _np()
    d = len(zh)
    L = np.linalg.cholesky(psd_clip(P) + 1e-12 * max(1e-12, np.trace(P) / d) * np.eye(d))
    X = zh + rng.standard_normal((draws, d)) @ L.T
    X2 = zh + rng.standard_normal((draws, d)) @ L.T
    return float(np.mean(np.linalg.norm(X - y, axis=1)) - 0.5 * np.mean(np.linalg.norm(X - X2, axis=1)))


def load_futures(doc, d):
    np = _np()
    if doc.get("schema") != FUTURES:
        raise ForecastError(f"futures schema {doc.get('schema')!r}")
    out = []
    for o in doc.get("origins", []):
        fs = []
        for f in o.get("futures", []):
            if f.get("kind") not in ("reseed", "original"):
                raise ForecastError(f"{o.get('world')}@{o.get('t0')}: future kind {f.get('kind')!r}")
            if f.get("extinct"):
                fs.append({"kind": f["kind"], "extinct": True})
                continue
            z, R = np.asarray(f["z"], float), np.asarray(f["cov"], float)
            if z.shape != (d,) or R.shape != (d, d) or not np.all(np.isfinite(z)) or not np.all(np.isfinite(R)):
                raise ForecastError(f"{o.get('world')}@{o.get('t0')}: a future's z / cov is not {d} / {d} x {d}")
            fs.append({"kind": f["kind"], "extinct": False, "z": z, "R": R})
        S0 = np.asarray(o.get("shared_cov", np.zeros((d, d))), float)
        if S0.shape != (d, d):
            raise ForecastError("shared_cov shape")
        if not isinstance(o.get("t0"), int) or not isinstance(o.get("horizon"), int):
            raise ForecastError("origins need integer t0 and horizon (M)")
        out.append({"world": o["world"], "t0": o["t0"], "horizon": o["horizon"], "futures": fs, "S0": S0})
    keys = [(o["world"], o["t0"], o["horizon"]) for o in out]
    if len(set(keys)) != len(keys):
        raise ForecastError("futures: an origin (world, t0, horizon) occurs twice")
    return out


def origin_metrics(fc, o, rng):
    """One origin x forecaster (see the module docstring); None values where unavailable."""
    np = _np()
    zh, P = np.asarray(fc["z"], float), np.asarray(fc["cov"], float)
    d = len(zh)
    live = [f for f in o["futures"] if not f["extinct"]]
    rs = [f for f in live if f["kind"] == "reseed"]
    rec = {"extinct": sum(1 for f in o["futures"] if f["extinct"]), "reseeds": len(rs), "futures": len(live)}

    def block(fs):
        if len(fs) < 2:
            return None, None
        Y = np.array([f["z"] for f in fs])
        mR = float(np.mean([np.trace(f["R"]) for f in fs]))
        mse = float(np.mean(np.sum((Y - zh) ** 2, axis=1))) - mR
        V = float(np.trace(np.cov(Y.T, ddof=1).reshape(d, d))) - (mR - float(np.trace(o["S0"])))
        return mse, V
    mse, V = block(rs)
    rec.update(mse=mse, v_fork=V, reducible=(mse - V) if mse is not None else None)
    m5, V5 = block(live)
    rec["with_original"] = {"mse": m5, "v_fork": V5, "reducible": (m5 - V5) if m5 is not None else None}
    if live:
        es, pit = [], []
        for f in live:
            S = P + f["R"]
            r = f["z"] - zh
            pit.append(chi2_cdf(float(r @ np.linalg.solve(S + 1e-12 * np.eye(d), r)), d))
            es.append(energy_score(zh, S, f["z"], rng))
        rec.update(energy=float(np.mean(es)), pit=pit, cover50=float(np.mean([p <= 0.5 for p in pit])),
                   cover90=float(np.mean([p <= 0.9 for p in pit])))
    return rec


def evaluate(pred, futures_doc, boot=BOOT):
    """The registered evaluation (see the module docstring) -> the eval document."""
    np = _np()
    d = pred["dim"]
    futs = {(o["world"], o["t0"], o["horizon"]): o for o in load_futures(futures_doc, d)}
    rng = np.random.default_rng(rqlib.derive_seed(SEED_NS, "energy"))
    per = []
    for p in pred["origins"]:
        o = futs.get((p["world"], p["t0"], p["horizon"]))
        if o is None:
            raise ForecastError(f"no futures for {p['world']}@{p['t0']}+{p['horizon']}")
        rec = {"world": p["world"], "t0": p["t0"], "horizon": p["horizon"]}
        if not p.get("available"):
            rec.update(available=False, reason=p.get("reason"))
        else:
            rec.update(available=True, metrics={k: origin_metrics(p["forecasts"][k], o, rng) for k in FORECASTERS})
        per.append(rec)
    pooled = {}
    brng = np.random.default_rng(rqlib.derive_seed(SEED_NS, "bootstrap"))
    for H in sorted({r["horizon"] for r in per}):
        for k in FORECASTERS:
            rows = [r for r in per if r["horizon"] == H and r.get("available") and r["metrics"][k]["mse"] is not None]
            ws = sorted({r["world"] for r in rows})
            if not rows:
                pooled[f"{k}@{H}"] = {"origins": 0}
                continue
            stat = {q: np.array([r["metrics"][k][q] for r in rows]) for q in ("mse", "v_fork", "reducible")}
            wid = np.array([ws.index(r["world"]) for r in rows])
            draws = {q: [] for q in stat}
            for _ in range(boot):
                pick = brng.integers(0, len(ws), len(ws))
                sel = np.concatenate([np.flatnonzero(wid == w) for w in pick])
                for q in stat:
                    draws[q].append(float(np.mean(stat[q][sel])))
            pooled[f"{k}@{H}"] = {"origins": len(rows), "worlds": len(ws),
                                  **{q: float(np.mean(stat[q])) for q in stat},
                                  "ci95": {q: [float(np.percentile(draws[q], 2.5)), float(np.percentile(draws[q], 97.5))]
                                           for q in stat}}
    return {"schema": EVAL, "predictions_sha256": None, "origins": per, "pooled": pooled, "boot": boot,
            "note": "reducible = MSE - V_fork: error reducible given the saved state under reseeding; negative "
                    "finite-sample values retained; not split into representation loss and learning error"}


# ================================================================== CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("predict")
    s.add_argument("--profiles", required=True)
    s.add_argument("--futures", required=True, help="the origins to forecast (their futures are not read)")
    s.add_argument("--out", required=True)
    s = sub.add_parser("evaluate")
    s.add_argument("--predictions", required=True)
    s.add_argument("--pred-sha", required=True, help="the committed TEST_PRED_SHA (sealing.py)")
    s.add_argument("--futures", required=True)
    s.add_argument("--boot", type=int, default=BOOT)
    s.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "predict":
            prof = rqlib.read_json(a.profiles)
            worlds, d = load_profiles(prof)
            fdoc = rqlib.read_json(a.futures)
            if fdoc.get("schema") != FUTURES:
                raise ForecastError(f"futures schema {fdoc.get('schema')!r}")
            origins = [{"world": o["world"], "t0": o["t0"], "horizon": o["horizon"]} for o in fdoc.get("origins", [])]
            model = fit_all(worlds, d)
            doc = {"schema": PRED, "dim": d, "profiles_sha256": rqlib.canonical_sha(prof),
                   "origins_sha256": rqlib.canonical_sha(origins), "window": WINDOW, "horizons": list(HORIZONS),
                   "lambda": model["lambda"], "lambda_selection": model["selection"],
                   "lss": {"Theta": model["lss"].Th.tolist(), "Q": model["lss"].Q.tolist()},
                   "standardizer": model["standardizer"],
                   "implementation_sha256": rqlib.sha256_file(os.path.abspath(__file__)),
                   "origins": predict(worlds, d, origins, model)}
            rqlib.write_json_durable(a.out, doc)
            print(f"{a.out}: sha256 {rqlib.sha256_file(a.out)} (commit it as TEST_PRED_SHA before evaluating)")
            return 0
        if rqlib.sha256_file(a.predictions) != a.pred_sha:
            raise ForecastError("the predictions' sha256 is not the committed one: refusing to evaluate")
        pred = rqlib.read_json(a.predictions)
        if pred.get("schema") != PRED:
            raise ForecastError(f"predictions schema {pred.get('schema')!r}")
        ev = evaluate(pred, rqlib.read_json(a.futures), a.boot)
        ev["predictions_sha256"] = a.pred_sha
        rqlib.write_json_durable(a.out, ev)
        for k, v in sorted(ev["pooled"].items()):
            print(k, {q: v.get(q) for q in ("origins", "mse", "v_fork", "reducible")})
        return 0
    except (ForecastError, OSError, ValueError, KeyError, TypeError) as e:
        what = "" if isinstance(e, ForecastError) else f"{type(e).__name__}: "
        print(f"forecast.py {a.cmd}: {what}{e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

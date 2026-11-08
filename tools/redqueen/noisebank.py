#!/usr/bin/env python3
"""noisebank.py: the independent noise bank (design v4 §7.4; Annex H.3.1's bank covariance, H.9.2's noise
model). The plan of its assays, their collection, and the estimator of the noise components that feed the
analysis covariance V, map.py's replicate-variance function and calib.py's generator noise block.

THE PLAN (design/2, registered here):
  worlds   the N_WORLDS = 8 C-treatment worlds of the worlds block (the validation run: val_block.py) whose
           TIMES = 20, 40, 60, 80M snapshots are all archived and valid (before the world's first zero), in
           the order of sha256("<seed namespace>|noisebank|<world uuid>"), the first 8; each world's partner
           is the next one in that order (cyclically);
  pairs    every prey snapshot (w, t) meets the predator snapshots of its own world at all four times
           (4 within-pilot pairs) and of its partner at all four times (4 cross-pilot pairs): 32 prey
           snapshots x 8 = 128 within-pilot + 128 cross-pilot pairs; every predator snapshot faces 8 prey
           snapshots (4 of its own world, 4 of the world whose partner it is): a CROSSED design, so the
           predator-donor component is identified apart from the prey row;
  controls one predator-free continuation per prey snapshot (32);
  assays   the production assay (frozen, K 6, the common 600-prey cohort, the production templates and age
           reference), 64 replicates, 20k steps scored at 5k, 10k and 20k, the PRODUCTION SEED SHARING of
           plan.py (sample / reseed per prey snapshot x replicate: the row; transplant per predator snapshot
           x replicate: the donor), its own seed namespace (rq2026-noisebank, plan namespace "noisebank"):
           256 x 64 = 16,384 predator trajectories and 32 x 64 = 2,048 predator-free ones, 18,432 in all;
           --avoid (the production reservations) and the age reference are mandatory, every engine seed
           checked against them.
COLLECT: through store.py's verified index, bound to the final plan (rows exact, the 600 cohort, every cell
collected or declared missing), the three horizons per cell.

THE ESTIMATOR (per horizon; on the empirical-logit scale z = logit((x + 1/2) / (n + 1)), x the capture count
of bound B(T) = K (1 + floor(T dt / cooldown)) or the survivors of 600). Model (H.9.2): z_ijr = mu_ij +
s(mu_ij) (rho_ir + delta_jr + eps_ijr) with rho the prey-row (snapshot x replicate), delta the predator-donor
(snapshot x replicate) and eps the cell component, the latent components normalized to unit total variance.
Deviations from the cell means over the R = 64 replicates, d_ijr, standardized by each cell's own SD (the
cell's total, s_ij), have E[d d'] = (component variance) x (1 - 1/R) for two cells sharing exactly the row
(same prey, different predators), exactly the donor (different prey, same predator), or the cell itself:
  row share     = mean over the row-sharing cell pairs and replicates of d~_ijr d~_ij'r / (1 - 1/R);
  donor share   = mean over the donor-sharing pairs of d~_ijr d~_i'jr / (1 - 1/R);
  cell share    = 1 - row - donor (unit total);
the same cross-products across channels (capture C, exposed survival S; the predator-free survival F shares
the prey row only) give SigmaR (3 x 3: C, S, F rows), SigmaD (2 x 2), SigmaE (2 x 2). The free channel's own
row variance SigmaR_FF is not separable from its cell (one control per row): it is set to the smallest
value keeping SigmaR positive semidefinite with the measured C-F and S-F row covariances (reported as a
lower bound). Heteroscedasticity (fit_scale): s(mu) per registered mean bin (H.9.2: capture [0,.35),
[.35,.70), [.70,1]; survival [0,.25), [.25,.75), [.75,1]) as the root mean of the cells' total variances in the
bin, AND a monotone function of the latent location logit(mu) (the isotonic fit, linear between its blocks;
the bins are its special case of a step function with knots at the edges), so either registration stays
open; the per-cell curve (mean, SD) is reported too. Saturated cells (mean outside [0.02, 0.98])
are excluded from the components and counted. map.py's shrinkage prior: the dispersion of the cells'
log variances around s(mu)^2 beyond the R - 1 df sampling dispersion (trigamma) gives the prior degrees of
freedom nu0 (inf: pool fully); a production cell's replicate-mean variance with R' replicates is then
(nu0 s(mu)^2 + (R' - 1) s_obs^2) / (nu0 + R' - 1) / R'. Uncertainty: a world-cluster bootstrap (the 8 worlds
resampled with their prey and predator snapshots), 999 draws, percentile intervals.

THE PRODUCTION V BUILDER (cov_parts; Annex H.3.1): one block's bank covariance diag(d) + U U' (for
recurrence.Cov) from the bank's components and s(mu) EVALUATED AT THE MEANS PASSED IN: raw replicate means or
null-model fitted means are the caller's (the registration's) choice, never the builder's. The construction
is calib.py's Panel.cov (capture: row + donor + cell; survival: the exposed cell minus its prey snapshot's
free control).

STATUS: plan and estimators only; no assay runs (the arena may still change: the plan records the
validation directory and the arena id it was made for).

    noisebank.py plan --block val_block.json --validation-dir ~/finfolk/validation --arena ARENA_ID \\
        --templates t.json ... --age-reference ages.json --avoid production_plan.jsonl ... --out nb_design.json
    noisebank.py collect --study STUDY --design noisebank_design.json --plan plan.jsonl [--declare-missing ...]
    noisebank.py estimate --obs noisebank_obs.json --out bank.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
import plan as planlib  # noqa: E402
import rqlib  # noqa: E402

SCHEMA = "finfolk.redqueen.noisebank/1"
OBS_SCHEMA = "finfolk.redqueen.noisebank.obs/1"
BANK_SCHEMA = "finfolk.redqueen.noisebank.bank/1"
SEED_NAMESPACE = "rq2026-noisebank"
PLAN_NAMESPACE = "noisebank"
TIMES = ("20M", "40M", "60M", "80M")
N_WORLDS = 8
TREATMENT = "C"
REPLICATES = 64
K = 6
N_PREY = 600
STEPS = 20000
HORIZONS = (5000, 10000, 20000)
DT, COOLDOWN = 0.016, 1.5          # (the engine step and the predator cooldown in seconds: the capture bound)
SATURATION = (0.02, 0.98)
BINS = {"C": (0.35, 0.70), "S": (0.25, 0.75), "F": (0.25, 0.75)}
BOOT = 999


class NoiseBankError(Exception):
    pass


def capture_bound(steps):
    """B(T) = K (1 + floor(T dt / cooldown)): 324 at 5k (recovery.py's B_COUNT), 642 at 10k, 1284 at 20k."""
    return K * (1 + int(math.floor(steps * DT / COOLDOWN + 1e-9)))


def frame_of(label):
    return int(label[:-1]) * 1_000_000


# ================================================================== the plan
def pick_worlds(block, ns=SEED_NAMESPACE, n=N_WORLDS):
    """The registered worlds and partners (see the module docstring)."""
    if block.get("schema") != "finfolk.redqueen.worldsblock/1":
        raise NoiseBankError(f"worlds block schema {block.get('schema')!r}")
    ws = block["worlds"]
    ok = []
    for w, v in ws.items():
        if v.get("treatment") != TREATMENT:
            continue
        good = True
        for lab in TIMES:
            fr = frame_of(lab)
            if block["times"].get(lab) != fr or fr not in v.get("archived", []) or \
                    (v.get("valid_before") is not None and fr >= v["valid_before"]):
                good = False
        if good:
            ok.append(w)
    if len(ok) < n:
        raise NoiseBankError(f"{len(ok)} eligible {TREATMENT} worlds (all of {list(TIMES)} archived and valid); "
                             f"{n} are registered")
    order = sorted(ok, key=lambda w: hashlib.sha256(f"{ns}|noisebank|{ws[w]['uuid']}".encode()).hexdigest())[:n]
    return order, {w: order[(k + 1) % n] for k, w in enumerate(order)}


def _collect_seeds(obj, out, hint=False):
    if isinstance(obj, dict):
        for k, v in obj.items():
            _collect_seeds(v, out, hint or "seed" in str(k).lower())
    elif isinstance(obj, list):
        for v in obj:
            _collect_seeds(v, out, hint)
    elif isinstance(obj, int) and not isinstance(obj, bool) and hint:
        out.add(obj)
    return out


def avoid_seeds(path):
    text = rqlib.read_text(path)
    try:
        doc = json.loads(text)
    except ValueError:
        doc = None
    if isinstance(doc, dict):
        return _collect_seeds(doc, set())
    rows = [json.loads(ln) for ln in text.split("\n") if ln.strip()]
    return planlib.plan_seeds(rows) | _collect_seeds(rows, set())


def make_design(block, templates, ages, avoid_paths, ns=SEED_NAMESPACE, validation_dir=None, arena=None):
    """The noise bank's design/2 (registered: see the module docstring), parameterized by the validation run
    it samples (validation_dir: the worlds block must have been read from it) and its arena id (recorded; the
    arena may still change before the bank runs)."""
    if not validation_dir or not arena:
        raise NoiseBankError("--validation-dir and --arena are mandatory (the bank samples one validation run of one arena)")
    if os.path.abspath(validation_dir) != os.path.abspath(block.get("root") or ""):
        raise NoiseBankError(f"the worlds block was read from {block.get('root')!r}, not {validation_dir!r}")
    if not isinstance(ages, str) or not os.path.isabs(ages) or not os.path.isfile(ages):
        raise NoiseBankError("--age-reference: the production age reference (an absolute path to a file) is mandatory")
    if not avoid_paths:
        raise NoiseBankError("--avoid: the production reservations are mandatory")
    order, partner = pick_worlds(block, ns)
    ws = block["worlds"]
    worlds = {w: {"uuid": ws[w]["uuid"], "pattern": ws[w]["pattern"], "paths": ws[w].get("paths", {})} for w in order}
    edges = []
    for w in order:
        for tq in TIMES:
            base = {"role": "diagnostic", "horizon": "long", "namespace": PLAN_NAMESPACE, "prey": {"world": w, "time": tq}}
            for fam, wp in (("nb-within", w), ("nb-cross", partner[w])):
                for tp in TIMES:
                    edges.append(dict(base, family=fam, predators={"world": wp, "time": tp}))
            edges.append(dict(base, family="nb-free", predators=None))
    for k, e in enumerate(edges, 1):
        e["edge"] = f"nb{k:05d}"
    design = {"schema": "finfolk.redqueen.design/2", "name": "noisebank", "seed_namespace": ns,
              "times": {lab: frame_of(lab) for lab in TIMES}, "worlds": worlds, "templates": list(templates),
              "age_reference": ages, "replicates": REPLICATES,
              "defaults": {"assay": "frozen", "k": K, "prey_policy": "common", "n_prey": N_PREY,
                           "long_steps": STEPS, "long_horizons": list(HORIZONS)},
              "long": {"fraction": 0.0}, "edges": edges}
    try:
        rows, _, _ = planlib.expand_v2(design, pending=True)
    except planlib.DesignError as e:
        raise NoiseBankError(f"plan.py refuses the design: {e}")
    seeds = planlib.plan_seeds(rows)
    checked = []
    for p in avoid_paths:
        hit = sorted(seeds & avoid_seeds(p))
        if hit:
            raise NoiseBankError(f"{len(hit)} noise-bank engine seed(s) are reserved in {p}: {hit[:5]}")
        checked.append({"path": os.path.abspath(p), "sha256": rqlib.sha256_file(p)})
    n_pred = sum(1 for r in rows if r.get("predators") is not None)
    design["noisebank"] = {"schema": SCHEMA, "validation_dir": os.path.abspath(validation_dir), "arena": str(arena),
                           "worlds": order, "partner": partner, "times": list(TIMES),
                           "registry_sha256": block.get("registry_sha256"), "avoid": checked, "cells": len(rows),
                           "predator_trajectories": n_pred, "free_trajectories": len(rows) - n_pred,
                           "horizons": list(HORIZONS), "capture_bounds": {str(h): capture_bound(h) for h in HORIZONS}}
    return design


# ================================================================== collect (bound to the final plan)
HASHED = ("prey", "predators", "template", "ages")


def _unhashed(row):
    r = json.loads(json.dumps(row))
    for k in HASHED:
        if isinstance(r.get(k), dict):
            r[k].pop("sha256", None)
    return r


def bind_plan(design, plan_path):
    exp, _, _ = planlib.expand_v2(design, pending=True)
    want = {r["id"]: r for r in exp}
    got = {}
    for ln in rqlib.read_text(plan_path).split("\n"):
        if ln.strip():
            r = json.loads(ln)
            if r.get("id") in got:
                raise NoiseBankError(f"plan {plan_path}: cell {r.get('id')} occurs twice")
            got[r.get("id")] = r
    if set(got) != set(want):
        raise NoiseBankError(f"plan {plan_path}: not the design's cells ({len(set(want) ^ set(got))} differ)")
    for cid, r in got.items():
        if _unhashed(r) != _unhashed(want[cid]):
            raise NoiseBankError(f"plan {plan_path}: cell {cid} differs from the design's expansion")
        for k in HASHED:
            x = r.get(k)
            if isinstance(x, dict) and x.get("path") and not (isinstance(x.get("sha256"), str) and len(x["sha256"]) == 64):
                raise NoiseBankError(f"plan {plan_path}: cell {cid} has no content hash for its {k} (a pending plan)")
    return got, rqlib.sha256_file(plan_path)


def collect(study, design, plan_path, declared_missing=()):
    """The bank's observations, bound to the final plan: per cell the prey and predator snapshots, the
    replicate and, per horizon, the captures and survivors of the 600 cohort."""
    import store
    rows, plan_sha = bind_plan(design, plan_path)
    _, cells = store.load_index(study)
    obs = []
    for cid in sorted(cells):
        b = json.loads(store.read_member(study, cid, cells=cells))
        c = b["cell"]
        if c.get("design") != design.get("name"):
            continue
        row = rows.get(cid)
        if row is None or rqlib.canonical(c) != rqlib.canonical(row):
            raise NoiseBankError(f"{cid}: not exactly a cell of the final plan")
        if b["score"].get("n_start") != N_PREY:
            raise NoiseBankError(f"{cid}: cohort {b['score'].get('n_start')}, not {N_PREY}")
        hz = {}
        for h in HORIZONS:
            x = [y for y in b["score"]["horizons"] if y["steps"] == h]
            if len(x) != 1:
                raise NoiseBankError(f"{cid}: no single {h}-step horizon")
            hz[str(h)] = {"captures": x[0].get("captures"), "survivors": x[0]["survivors"]}
        p = row["predators"]
        obs.append({"cell": cid, "prey": [row["prey"]["world"], row["prey"]["time"]],
                    "pred": None if p is None else [p["world"], p["time"]], "replicate": row["replicate"],
                    "horizons": hz})
    missing = sorted(set(rows) - {o["cell"] for o in obs})
    if missing != sorted(set(declared_missing)):
        raise NoiseBankError(f"{len(missing)} plan cells are not collected; a missing cell must be declared exactly")
    return {"schema": OBS_SCHEMA, "design_sha256": rqlib.canonical_sha(design), "plan_sha256": plan_sha,
            "missing": missing, "observations": obs}


# ================================================================== the estimator
def _elogit(x, n):
    import numpy as np
    x = np.asarray(x, float)
    return np.log((x + 0.5) / (n - x + 0.5))


def arrays(obs, horizon):
    """-> (prey keys, predator keys, C z (cells x R), S z, F z (prey x R), cell index (i, j), cell means
    (capture fraction, exposed survival), free means), complete cells only (all R replicates)."""
    import numpy as np
    B = capture_bound(horizon)
    h = str(horizon)
    by, free = {}, {}
    for o in obs:
        x = o["horizons"][h]
        if o["pred"] is None:
            free.setdefault(tuple(o["prey"]), {})[o["replicate"]] = x["survivors"]
        else:
            by.setdefault((tuple(o["prey"]), tuple(o["pred"])), {})[o["replicate"]] = (x["captures"], x["survivors"])
    reps = sorted({o["replicate"] for o in obs})
    R = len(reps)
    cells = sorted(k for k, v in by.items() if len(v) == R)
    prey = sorted({i for i, _ in cells})
    pred = sorted({j for _, j in cells})
    pi = {k: n for n, k in enumerate(prey)}
    pj = {k: n for n, k in enumerate(pred)}
    Cc = np.array([[by[c][r][0] for r in reps] for c in cells], float)
    Sc = np.array([[by[c][r][1] for r in reps] for c in cells], float)
    if np.any(Cc < 0) or np.any(Cc > B) or np.any(Sc < 0) or np.any(Sc > N_PREY):
        raise NoiseBankError(f"counts outside their bounds at {horizon} steps (captures <= {B}, survivors <= {N_PREY})")
    Fc = np.array([[free.get(i, {}).get(r, np.nan) for r in reps] for i in prey], float)
    return {"prey": prey, "pred": pred, "I": np.array([pi[i] for i, _ in cells]), "J": np.array([pj[j] for _, j in cells]),
            "zC": _elogit(Cc, B), "zS": _elogit(Sc, N_PREY), "zF": _elogit(Fc, N_PREY),
            "mC": Cc.mean(axis=1) / B, "mS": Sc.mean(axis=1) / N_PREY, "mF": np.nanmean(Fc, axis=1) / N_PREY, "R": R}


def _pairs(I, J):
    """Row-sharing (same prey, different predator) and donor-sharing (different prey, same predator) cell
    pairs, each unordered pair once."""
    import numpy as np
    n = len(I)
    a, b = np.triu_indices(n, 1)
    row = (I[a] == I[b]) & (J[a] != J[b])
    don = (J[a] == J[b]) & (I[a] != I[b])
    return (a[row], b[row]), (a[don], b[don])


def components(A, keep=None):
    """The standardized component estimates of one horizon (see the module docstring) -> dict with SigmaR (C,
    S, F), SigmaD (C, S), SigmaE (C, S), the shares and the cell counts. keep: a cell mask (the unsaturated)."""
    import numpy as np
    R = A["R"]
    I, J = A["I"], A["J"]
    keep = np.ones(len(I), bool) if keep is None else keep
    dev = {}
    for ch in ("C", "S"):
        z = A["z" + ch]
        d = z - z.mean(axis=1, keepdims=True)
        sd = np.sqrt(np.sum(d * d, axis=1) / (R - 1))
        dev[ch] = d / np.where(sd > 0, sd, np.nan)[:, None]
    zF = A["zF"]
    dF = zF - np.nanmean(zF, axis=1, keepdims=True)
    sF = np.sqrt(np.nansum(dF * dF, axis=1) / (R - 1))
    dF = dF / np.where(sF > 0, sF, np.nan)[:, None]
    idx = np.flatnonzero(keep & np.all(np.isfinite(dev["C"]), axis=1) & np.all(np.isfinite(dev["S"]), axis=1))
    Ik, Jk = I[idx], J[idx]
    (ra, rb), (da, db) = _pairs(Ik, Jk)
    f = 1.0 - 1.0 / R

    def cross(x, y, a, b):
        if not len(a):
            return float("nan")
        return float(np.mean(0.5 * (np.sum(x[a] * y[b], axis=1) + np.sum(x[b] * y[a], axis=1)) / R) / f)

    out = {"cells": int(len(idx)), "row_pairs": int(len(ra)), "donor_pairs": int(len(da))}
    dC, dS = dev["C"][idx], dev["S"][idx]
    SR = np.zeros((3, 3))
    SD = np.zeros((2, 2))
    SE = np.zeros((2, 2))
    for p, xp in enumerate((dC, dS)):
        for q, xq in enumerate((dC, dS)):
            SR[p, q] = cross(xp, xq, ra, rb)
            SD[p, q] = cross(xp, xq, da, db)
            same = float(np.mean(np.sum(xp * xq, axis=1) / R) / f)
            SE[p, q] = same - SR[p, q] - SD[p, q]
    # the free channel: its row covariance with the exposed rows of the same prey snapshot and replicate
    dFk = dF[Ik]
    for p, xp in enumerate((dC, dS)):
        ok = np.all(np.isfinite(dFk), axis=1)
        SR[p, 2] = SR[2, p] = float(np.mean(np.sum(xp[ok] * dFk[ok], axis=1) / R) / f) if ok.any() else float("nan")
    # SigmaR_FF: the smallest value keeping SigmaR PSD (a lower bound; one control per row cannot split it)
    sub = SR[:2, :2]
    v = SR[:2, 2]
    try:
        lb = float(v @ np.linalg.pinv(sub) @ v)
    except np.linalg.LinAlgError:
        lb = float("nan")
    SR[2, 2] = min(max(lb, 0.0), 1.0)
    out.update(SigmaR=SR.tolist(), SigmaD=SD.tolist(), SigmaE=SE.tolist(), SigmaR_FF_lower_bound=lb,
               shares={ch: {"row": SR[k, k], "donor": SD[k, k], "cell": SE[k, k]} for k, ch in enumerate("CS")})
    return out


def pava(x, w, increasing=True):
    """Weighted isotonic regression (pool adjacent violators) of x (in order) -> the fitted values."""
    import numpy as np
    vals = np.asarray(x, float) if increasing else -np.asarray(x, float)
    out = []
    for v, wt in zip(vals, np.asarray(w, float)):
        out.append([v, wt, 1])
        while len(out) > 1 and out[-2][0] > out[-1][0]:
            v2, w2, n2 = out.pop()
            v1, w1, n1 = out.pop()
            out.append([(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2, n1 + n2])
    fit = np.concatenate([np.full(n, v) for v, _, n in out]) if out else np.zeros(0)
    return fit if increasing else -fit


def fit_scale(mu, var, ch, mode="bins", direction="auto"):
    """s(mu) for one channel from the cells' means and total latent variances. mode "bins": H.9.2's
    registered bins (the root mean variance per bin, a step function). mode "monotone": a monotone function
    of the LATENT location logit(mu): the isotonic fit of the variances in logit(mu) (direction "increasing" /
    "decreasing" / "auto": the better of the two in squared error), linear between the fitted blocks'
    centres, constant beyond. The bins are the special case of a step function with knots at the bin
    edges, so either registration remains open. -> {"mode", knots / edges, "s", "eval": mu -> s}."""
    import numpy as np
    mu, var = np.asarray(mu, float), np.asarray(var, float)
    ok = np.isfinite(mu) & np.isfinite(var) & (mu > 0) & (mu < 1)
    mu, var = mu[ok], var[ok]
    if mode == "bins":
        lo, hi = BINS[ch]
        b = np.where(mu < lo, 0, np.where(mu < hi, 1, 2))
        s = [float(np.sqrt(np.mean(var[b == k]))) if np.any(b == k) else None for k in range(3)]

        def ev(m, s=s, lo=lo, hi=hi):
            m = np.asarray(m, float)
            return np.where(m < lo, s[0], np.where(m < hi, s[1], s[2]))
        return {"mode": "bins", "edges": [lo, hi], "s": s, "eval": ev}
    x = np.log(mu / (1 - mu))
    o = np.argsort(x, kind="stable")
    xs, vs = x[o], var[o]
    fits = {}
    for d in (("decreasing", "increasing") if direction == "auto" else (direction,)):
        f = pava(vs, np.ones(len(vs)), increasing=(d == "increasing"))
        fits[d] = (float(np.sum((vs - f) ** 2)), f)
    d = min(fits, key=lambda k: (fits[k][0], k))
    f = fits[d][1]
    ks, kv = [], []
    for v in np.unique(f):                                     # (each fitted block: its centre and value)
        sel = f == v
        ks.append(float(np.mean(xs[sel])))
        kv.append(float(np.sqrt(v)))
    order = np.argsort(ks)
    ks, kv = [ks[k] for k in order], [kv[k] for k in order]

    def ev(m, ks=ks, kv=kv):
        m = np.clip(np.asarray(m, float), 1e-12, 1 - 1e-12)
        return np.interp(np.log(m / (1 - m)), ks, kv)
    return {"mode": "monotone", "direction": d, "x": ks, "s": kv, "eval": ev}


def bins_scale(bank_noise):
    """s(ch, mu) from a bank noise block's binned s (the default registration)."""
    import numpy as np

    def sfun(ch, mu):
        s = bank_noise["s"][ch]
        lo, hi = BINS[ch]
        mu = np.asarray(mu, float)
        return np.where(mu < lo, s[0], np.where(mu < hi, s[1], s[2]))
    return sfun


def cov_parts(bank_noise, kind, structure, means, R=6, scale=None):
    """THE PRODUCTION V BUILDER (Annex H.3.1): the bank covariance of one block's replicate means as (d, U),
    V = diag(d) + U U' (recurrence.Cov(d, U)), from the bank's components and s(mu) evaluated at the means
    GIVEN EXPLICITLY. `means` is the registration's choice (the raw replicate means or the null-model fitted
    means): the builder never chooses. kind "C" / "RC" (capture: rows share a prey key and a predator key)
    or "Q" / "RQ" (exposed survival minus its prey snapshot's free control: rows share the prey snapshot's
    row and free components and the predator key). structure: {"prey": per-row prey-key index, "pred":
    per-row predator-key index, "n_prey", "n_pred"}; means: {"C": per row} or {"S": per row, "F": per prey
    key}; scale: s(ch, mu) (default: the bank's binned s). The construction is calib.Panel.cov's."""
    import numpy as np
    SR, SD = np.asarray(bank_noise["SigmaR"], float), np.asarray(bank_noise["SigmaD"], float)
    sfun = scale or bins_scale(bank_noise)
    pi, pj = np.asarray(structure["prey"], int), np.asarray(structure["pred"], int)
    rows = np.arange(len(pi))

    def g(ch, x, n):
        x = np.clip(np.asarray(x, float), 0.5 / n, 1 - 0.5 / n)
        return sfun(ch, x) * x * (1 - x)
    if kind in ("C", "RC"):
        gg = g("C", means["C"], bank_noise["capture_bound"])
        d = gg ** 2 * (1 - SR[0, 0] - SD[0, 0]) / R
        U1 = np.zeros((len(rows), structure["n_prey"]))
        U1[rows, pi] = gg * math.sqrt(SR[0, 0] / R)
        U2 = np.zeros((len(rows), structure["n_pred"]))
        U2[rows, pj] = gg * math.sqrt(SD[0, 0] / R)
        return d, np.hstack([U1, U2])
    gS = g("S", means["S"], N_PREY)
    gF = g("F", np.asarray(means["F"], float)[pi], N_PREY)
    L = np.linalg.cholesky(np.array([[SR[1, 1], SR[1, 2]], [SR[1, 2], SR[2, 2]]]) + 1e-15 * np.eye(2))
    eF = 1 - SR[2, 2]
    d = gS ** 2 * (1 - SR[1, 1] - SD[1, 1]) / R
    nuk = structure["n_prey"]
    M = np.zeros((len(rows), 3 * nuk))
    M[rows, 3 * pi] = (gS * L[0, 0] - gF * L[1, 0]) / math.sqrt(R)
    M[rows, 3 * pi + 1] = (-gF * L[1, 1]) / math.sqrt(R)
    M[rows, 3 * pi + 2] = (-gF * math.sqrt(eF)) / math.sqrt(R)
    Md = np.zeros((len(rows), structure["n_pred"]))
    Md[rows, pj] = gS * math.sqrt(SD[1, 1] / R)
    return d, np.hstack([M, Md])


def scales(A, keep=None):
    """s(mu) per registered mean bin and channel (the root mean of the cells' total latent variances in
    the bin), the per-cell (mean, SD) curve, and map.py's shrinkage prior nu0 per channel."""
    import numpy as np
    R = A["R"]
    out = {"s": {}, "curve": {}, "nu0": {}, "bins": {k: list(v) for k, v in BINS.items()}}
    for ch, m in (("C", A["mC"]), ("S", A["mS"]), ("F", A["mF"])):
        z = A["z" + ch]
        ok = np.isfinite(z).all(axis=1) & np.isfinite(m)
        if keep is not None and ch != "F":
            ok &= keep
        var = np.var(z[ok], axis=1, ddof=1)
        mm = m[ok]
        lo, hi = BINS[ch]
        b = np.where(mm < lo, 0, np.where(mm < hi, 1, 2))
        s = fit_scale(mm, var, ch, "bins")["s"]
        fm = fit_scale(mm, var, ch, "monotone")
        out["s"][ch] = s
        out.setdefault("monotone", {})[ch] = {"direction": fm["direction"], "logit_knots": fm["x"], "s": fm["s"]}
        out["curve"][ch] = sorted([float(a), float(math.sqrt(c))] for a, c in zip(mm, var))
        # nu0: the excess dispersion of log s^2 around its bin value over the (R - 1)-df sampling dispersion
        fit = np.array([s[k] ** 2 if s[k] else np.nan for k in b])
        lr = np.log(var / fit)
        good = np.isfinite(lr)
        samp = _trigamma((R - 1) / 2.0)
        excess = float(np.var(lr[good], ddof=1) - samp) if good.sum() > 2 else float("nan")
        out["nu0"][ch] = {"excess_log_variance": excess,
                          "nu0": (float("inf") if not excess > 0 else 2.0 / excess)}
    return out


def _trigamma(x):
    """psi'(x) for x > 0 (recurrence then the asymptotic series)."""
    acc = 0.0
    while x < 6.0:
        acc += 1.0 / (x * x)
        x += 1.0
    t = 1.0 / (x * x)
    return acc + 1.0 / x + t / 2.0 + t / x * (1.0 / 6.0 - t * (1.0 / 30.0 - t / 42.0))


def estimate(doc, boot=BOOT, seed=0):
    """The bank per horizon: components (all unsaturated cells), scales, saturation counts, the world-cluster
    bootstrap intervals of the shares, and the generator noise block / map prior at the production 5k
    horizon."""
    import numpy as np
    if doc.get("schema") != OBS_SCHEMA:
        raise NoiseBankError(f"observations schema {doc.get('schema')!r}")
    obs = doc["observations"]
    out = {"schema": BANK_SCHEMA, "obs_design_sha256": doc.get("design_sha256"), "plan_sha256": doc.get("plan_sha256"),
           "horizons": {}}
    for h in HORIZONS:
        A = arrays(obs, h)
        sat = (A["mC"] < SATURATION[0]) | (A["mC"] > SATURATION[1]) | (A["mS"] < SATURATION[0]) | (A["mS"] > SATURATION[1])
        keep = ~sat
        comp = components(A, keep)
        sc = scales(A, keep)
        worlds = sorted({p[0] for p in A["prey"]} | {p[0] for p in A["pred"]})
        rng = np.random.default_rng(seed)
        draws = []
        for _ in range(boot):
            pick = rng.choice(len(worlds), len(worlds), replace=True)
            w = {worlds[k] for k in pick}
            m = keep & np.array([A["prey"][i][0] in w and A["pred"][j][0] in w for i, j in zip(A["I"], A["J"])])
            c = components(A, m)
            draws.append([c["shares"][ch][k] for ch in "CS" for k in ("row", "donor", "cell")])
        D = np.array(draws, float)
        names = [f"{ch}.{k}" for ch in "CS" for k in ("row", "donor", "cell")]
        ci = {n: [float(np.nanpercentile(D[:, k], 2.5)), float(np.nanpercentile(D[:, k], 97.5))]
              for k, n in enumerate(names)}
        out["horizons"][str(h)] = dict(comp, scales=sc, saturated=int(sat.sum()), cells_total=int(len(sat)),
                                       capture_bound=capture_bound(h), bootstrap={"draws": boot, "ci95": ci,
                                                                                  "unit": "world cluster"})
    base = out["horizons"][str(HORIZONS[0])]
    out["generator_noise"] = {"s": base["scales"]["s"], "s_monotone": base["scales"]["monotone"],
                              "SigmaR": base["SigmaR"], "SigmaD": base["SigmaD"], "SigmaE": base["SigmaE"],
                              "horizon": HORIZONS[0], "capture_bound": capture_bound(HORIZONS[0])}
    out["map_variance"] = {"s": base["scales"]["s"], "bins": base["scales"]["bins"], "nu0": base["scales"]["nu0"],
                           "rule": "replicate-mean variance (nu0 s(mu)^2 + (R - 1) s_obs^2) / (nu0 + R - 1) / R"}
    return out


# ================================================================== CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan")
    s.add_argument("--block", required=True)
    s.add_argument("--templates", nargs="+", required=True)
    s.add_argument("--age-reference", required=True)
    s.add_argument("--avoid", nargs="+", default=[])
    s.add_argument("--seed-namespace", default=SEED_NAMESPACE)
    s.add_argument("--validation-dir", required=True)
    s.add_argument("--arena", required=True)
    s.add_argument("--out", required=True)
    s = sub.add_parser("collect")
    s.add_argument("--study", required=True)
    s.add_argument("--design", required=True)
    s.add_argument("--plan", required=True)
    s.add_argument("--declare-missing", nargs="*", default=[])
    s.add_argument("--out", required=True)
    s = sub.add_parser("estimate")
    s.add_argument("--obs", required=True)
    s.add_argument("--boot", type=int, default=BOOT)
    s.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":
            d = make_design(rqlib.read_json(a.block), [os.path.abspath(t) for t in a.templates],
                            os.path.abspath(a.age_reference), a.avoid, a.seed_namespace, a.validation_dir, a.arena)
            rqlib.write_json_durable(a.out, d)
            print(json.dumps({k: d["noisebank"][k] for k in ("worlds", "cells", "predator_trajectories",
                                                            "free_trajectories")}))
        elif a.cmd == "collect":
            doc = collect(a.study, rqlib.read_json(a.design), a.plan, a.declare_missing)
            rqlib.write_json_durable(a.out, doc)
            print(f"{len(doc['observations'])} observations, {len(doc['missing'])} declared missing")
        else:
            bank = estimate(rqlib.read_json(a.obs), boot=a.boot)
            rqlib.write_json_durable(a.out, bank)
            print(json.dumps(bank["generator_noise"]))
        return 0
    except NoiseBankError as e:
        print(f"noisebank.py {a.cmd}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

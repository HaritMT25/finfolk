#!/usr/bin/env python3
"""probes.py: the Level-3 EXPLORATORY observational probes (design v4 §11). Every finding is exploratory,
successful transfer included; associations cannot establish a feature's causal contribution, and no
intervention (ablation, clamping, sham, checkpoint surgery) is registered.

FEATURES (features/1): compact population summaries per world snapshot, each feature in one group:
  wiring      sensor-to-action connectivity, signs and weights; recurrence; controller size;
  behaviour   standardized stimulus responses; pursuit, evasion, speed, spacing, milling, polarization;
  energetics  food acquisition, reproduction, energetic surplus;
  diversity   genotype, lineage and wiring diversity: distinct_genomes and wiring_diversity are REQUIRED
              (polymorphism can generate population-level interaction rank).
Canonical functional summaries, never raw genome positions. Rows carry the world, time (M), split, block,
treatment, density, controller size, and whether the row is an F1 founder population.
TARGETS (probe_targets/1): fixed-reference profile coordinates or forecast residuals per world snapshot
(never unconstrained latent axes as mechanistic targets).

ADJUSTMENT: every feature and target is residualized on [1, density, time, controller size, treatment]
by OLS fitted on the TRAINING rows; features are then scaled by their training SD.
PROBES (per target), compared over the input sets wiring (wiring + diversity), behaviour (behaviour +
energetics) and combined (all):
  lasso     the sparse linear probe (elastic net, alpha 1), coordinate descent;
  enet      elastic net, alpha 0.5;
  additive  a small additive probe: per feature a centred cubic B-spline basis (knots at the training
            quartiles), ridge.
  The penalty grids are registered (LAMBDA_REL x lambda_max for the linear probes; ADD_LAMBDAS x n for the
  additive). Every (probe, set, penalty) is fitted on training and scored on validation (R^2); the best
  validation R^2 per target is selected (ties: the simpler probe, the smaller set, the larger penalty).
  Test predictions are written with every selected probe, on the targets' original scale (the training
  adjustment added back); their sha256 is committed (sealing.py) BEFORE evaluation, and `evaluate` refuses
  any other sha256 (test R^2 against the test rows' targets).
NEGATIVE CONTROL (v4 §11.2): own-world enrichment among the 32 C F1 founder populations (no history: no
coadaptation is possible). The statistic is mean(own-world pair values) - mean(cross-world pair values);
its null permutes the predator worlds' labels WITHIN BLOCKS (block-respecting), PERMUTATIONS draws, two-
sided plus-one p. p < AUDIT_ALPHA is unexpected F1 structure: an initializer, seed or measurement AUDIT is
triggered (reported, never a finding). The same statistic is reported for later snapshots (exploratory).

    probes.py fit --features features.json --targets targets.json --out probes.json --predictions test_pred.json
    probes.py evaluate --predictions test_pred.json --pred-sha SHA --targets targets.json --out probe_eval.json
    probes.py enrichment --pairs f1_pairs.json --out f1_enrichment.json
"""
from __future__ import annotations

import argparse
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
import rqlib  # noqa: E402

FEATURES = "finfolk.redqueen.features/1"
TARGETS = "finfolk.redqueen.probe_targets/1"
PRED = "finfolk.redqueen.probe_predictions/1"
GROUPS = ("wiring", "behaviour", "energetics", "diversity")
REQUIRED = ("distinct_genomes", "wiring_diversity")
SETS = {"wiring": ("wiring", "diversity"), "behaviour": ("behaviour", "energetics"), "combined": GROUPS}
SET_ORDER = ("wiring", "behaviour", "combined")
PROBES = ("lasso", "enet", "additive")
ALPHA = {"lasso": 1.0, "enet": 0.5}
LAMBDA_REL = (1.0, 0.3, 0.1, 0.03, 0.01)
ADD_LAMBDAS = (0.1, 1.0, 10.0, 100.0)
TREATMENTS = ("C", "A", "B")
CD_ITERS, CD_TOL = 2000, 1e-9
PERMUTATIONS = 9999
AUDIT_ALPHA = 0.01
SEED_NS = "rq2026-probes"


class ProbeError(Exception):
    pass


def _np():
    import numpy as np
    return np


# ================================================================== inputs and adjustment
def load(features, targets):
    """-> (rows meta, X (n x p), feature names, groups, Y (n x q), target names)."""
    np = _np()
    if features.get("schema") != FEATURES or targets.get("schema") != TARGETS:
        raise ProbeError("features/1 and probe_targets/1 documents are required")
    fg = features.get("features") or {}
    if any(g not in GROUPS for g in fg.values()):
        raise ProbeError(f"feature groups must be among {GROUPS}")
    missing = [f for f in REQUIRED if fg.get(f) != "diversity"]
    if missing:
        raise ProbeError(f"the diversity summaries {missing} are required (v4 §11.2)")
    names = sorted(fg)
    tnames = list(targets.get("targets") or [])
    if not tnames:
        raise ProbeError("no targets")
    ty = {(r["world"], r["t"]): r["y"] for r in targets.get("rows", [])}
    meta, X, Y = [], [], []
    for r in features.get("rows", []):
        if r.get("split") not in ("training", "validation", "test") or r.get("treatment") not in TREATMENTS:
            raise ProbeError(f"{r.get('world')}@{r.get('t')}: split / treatment")
        v = r.get("values") or {}
        if set(v) != set(names) or not all(isinstance(v[k], (int, float)) and math.isfinite(v[k]) for k in names):
            raise ProbeError(f"{r.get('world')}@{r.get('t')}: values must be exactly the registered features, finite")
        meta.append({k: r.get(k) for k in ("world", "t", "split", "block", "treatment", "density", "controller_size", "f1")})
        X.append([v[k] for k in names])
        y = ty.get((r["world"], r["t"]))
        Y.append([float(y[k]) if y is not None and k in y and y[k] is not None else math.nan for k in tnames])
    return meta, np.array(X, float), names, [fg[k] for k in names], np.array(Y, float), tnames


def design(meta):
    np = _np()
    return np.array([[1.0, float(m["density"]), float(m["t"]), float(m["controller_size"])]
                     + [1.0 * (m["treatment"] == t) for t in TREATMENTS[1:]] for m in meta])


def adjust(meta, X, Y):
    """Residualize on the covariates (OLS on training rows); scale features by their training SD."""
    np = _np()
    D = design(meta)
    tr = np.array([m["split"] == "training" for m in meta])
    if tr.sum() <= D.shape[1]:
        raise ProbeError("too few training rows for the adjustment")
    Dt = D[tr]
    keep = np.linalg.matrix_rank(Dt) == Dt.shape[1]
    if not keep:                                     # (e.g. one treatment in training: drop constant columns)
        cols = [k for k in range(D.shape[1]) if k == 0 or np.ptp(Dt[:, k]) > 0]
        D, Dt = D[:, cols], Dt[:, cols]
    Bx = np.linalg.lstsq(Dt, X[tr], rcond=None)[0]
    Xr = X - D @ Bx
    sd = Xr[tr].std(axis=0)
    Xr = Xr / np.where(sd > 0, sd, 1.0)
    Yr = np.full_like(Y, np.nan)
    By = np.full((Y.shape[1], D.shape[1]), np.nan)
    for j in range(Y.shape[1]):
        ok = tr & np.isfinite(Y[:, j])
        if ok.sum() > D.shape[1]:
            By[j] = np.linalg.lstsq(D[ok], Y[ok, j], rcond=None)[0]
            Yr[:, j] = Y[:, j] - D @ By[j]
    return Xr, Yr, D, By


# ================================================================== probes
def enet(X, y, lam, alpha):
    """min (1/2n)||y - X b||^2 + lam (alpha |b|_1 + (1 - alpha)/2 |b|^2), coordinate descent (X centred)."""
    np = _np()
    n, p = X.shape
    b = np.zeros(p)
    r = y.copy()
    cs = (X * X).sum(axis=0) / n
    for _ in range(CD_ITERS):
        mx = 0.0
        for j in range(p):
            if cs[j] == 0:
                continue
            g = X[:, j] @ r / n + cs[j] * b[j]
            nb = math.copysign(max(abs(g) - lam * alpha, 0.0), g) / (cs[j] + lam * (1 - alpha))
            if nb != b[j]:
                r -= X[:, j] * (nb - b[j])
                mx = max(mx, abs(nb - b[j]))
                b[j] = nb
        if mx < CD_TOL:
            break
    return b


def spline_basis(x, knots):
    """A cubic truncated-power basis with the given interior knots (x, x^2, x^3, (x - k)^3_+)."""
    np = _np()
    cols = [x, x ** 2, x ** 3] + [np.clip(x - k, 0, None) ** 3 for k in knots]
    return np.stack(cols, axis=1)


class Probe:
    def __init__(self, kind, cols, lam):
        self.kind, self.cols, self.lam = kind, cols, lam

    def _expand(self, X, fit=False):
        np = _np()
        Z = X[:, self.cols]
        if self.kind != "additive":
            return Z
        if fit:
            self.knots = [np.quantile(Z[:, j], [0.25, 0.5, 0.75]).tolist() for j in range(Z.shape[1])]
        B = np.hstack([spline_basis(Z[:, j], self.knots[j]) for j in range(Z.shape[1])])
        if fit:
            self.bm, self.bs = B.mean(axis=0), B.std(axis=0)
            self.bs = np.where(self.bs > 0, self.bs, 1.0)
        return (B - self.bm) / self.bs

    def fit(self, X, y):
        np = _np()
        B = self._expand(X, fit=True)
        self.ym = float(y.mean())
        Bc = B - (B.mean(axis=0) if self.kind != "additive" else 0.0)
        self.xm = B.mean(axis=0) if self.kind != "additive" else np.zeros(B.shape[1])
        if self.kind == "additive":
            n = len(y)
            self.b = np.linalg.solve(Bc.T @ Bc + self.lam * n * np.eye(Bc.shape[1]), Bc.T @ (y - self.ym))
        else:
            self.b = enet(Bc, y - self.ym, self.lam, ALPHA[self.kind])
        return self

    def predict(self, X):
        return self.ym + (self._expand(X) - self.xm) @ self.b


def r2(y, yh):
    np = _np()
    ss = float(np.sum((y - y.mean()) ** 2))
    return 1.0 - float(np.sum((y - yh) ** 2)) / ss if ss > 0 else None


def tune(Xr, Yr, meta, groups, tnames):
    """Every (probe, set, penalty) per target: fitted on training, scored on validation -> (report, the
    selected probes)."""
    np = _np()
    tr = np.array([m["split"] == "training" for m in meta])
    va = np.array([m["split"] == "validation" for m in meta])
    report, chosen = {}, {}
    for j, tn in enumerate(tnames):
        ok_t, ok_v = tr & np.isfinite(Yr[:, j]), va & np.isfinite(Yr[:, j])
        if ok_t.sum() < 5 or ok_v.sum() < 3:
            report[tn] = {"available": False, "reason": "too few training / validation rows with this target"}
            continue
        rows, best = [], None
        for ps, kind in enumerate(PROBES):
            for ss, sname in enumerate(SET_ORDER):
                cols = [k for k, g in enumerate(groups) if g in SETS[sname]]
                if kind == "additive":
                    lams = list(ADD_LAMBDAS)
                else:
                    Xc = Xr[ok_t][:, cols] - Xr[ok_t][:, cols].mean(axis=0)
                    lmax = float(np.max(np.abs(Xc.T @ (Yr[ok_t, j] - Yr[ok_t, j].mean())))) / ok_t.sum() / ALPHA[kind]
                    lams = [lmax * f for f in LAMBDA_REL]
                for ls, lam in enumerate(lams):
                    p = Probe(kind, cols, lam).fit(Xr[ok_t], Yr[ok_t, j])
                    sc = r2(Yr[ok_v, j], p.predict(Xr[ok_v]))
                    rows.append({"probe": kind, "set": sname, "lambda": lam, "validation_r2": sc,
                                 "nonzero": int(np.sum(np.abs(p.b) > 0))})
                    key = (-(sc if sc is not None else -math.inf), ps, ss, -lam)
                    if best is None or key < best[0]:
                        best = (key, p, rows[-1])
        report[tn] = {"available": True, "candidates": rows, "selected": best[2],
                      "best_by_set": {s: max((r["validation_r2"] for r in rows if r["set"] == s and r["validation_r2"] is not None),
                                             default=None) for s in SET_ORDER}}
        chosen[tn] = best[1]
    return report, chosen


# ================================================================== the F1 negative control
def enrichment(pairs, blocks, n_perm=PERMUTATIONS, seed_parts=("f1",)):
    """Own-world enrichment: mean(own) - mean(cross) over pair values; the block-respecting permutation null
    (predator-world labels permuted within blocks) -> record with the two-sided plus-one p and the audit flag."""
    np = _np()
    worlds = sorted(blocks)
    wi = {w: k for k, w in enumerate(worlds)}
    q = np.array([wi[p["prey_world"]] for p in pairs])
    r = np.array([wi[p["pred_world"]] for p in pairs])
    v = np.array([float(p["value"]) for p in pairs])
    if not np.all(np.isfinite(v)):
        raise ProbeError("enrichment: non-finite pair values")

    def stat(rr):
        own = q == rr
        if own.all() or not own.any():
            return None
        return float(v[own].mean() - v[~own].mean())
    obs = stat(r)
    if obs is None:
        return {"available": False, "reason": "no own-world or no cross-world pairs"}
    bl = {}
    for w in worlds:
        bl.setdefault(blocks[w], []).append(wi[w])
    rng = np.random.default_rng(rqlib.derive_seed(SEED_NS, "enrichment", *seed_parts))
    ge = 0
    for _ in range(n_perm):
        perm = np.arange(len(worlds))
        for members in bl.values():
            perm[members] = rng.permutation(members)
        s = stat(perm[r])
        ge += s is not None and abs(s) >= abs(obs) - 1e-15
    p = (1 + ge) / (n_perm + 1)
    return {"available": True, "statistic": obs, "p": p, "permutations": n_perm, "audit": p < AUDIT_ALPHA,
            "rule": "block-respecting permutation of predator-world labels; p < AUDIT_ALPHA triggers an "
                    "initializer / seed / measurement audit"}


# ================================================================== CLI
def main(argv=None):
    np = None
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("fit")
    s.add_argument("--features", required=True)
    s.add_argument("--targets", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--predictions", required=True)
    s = sub.add_parser("evaluate")
    s.add_argument("--predictions", required=True)
    s.add_argument("--pred-sha", required=True)
    s.add_argument("--targets", required=True)
    s.add_argument("--out", required=True)
    s = sub.add_parser("enrichment")
    s.add_argument("--pairs", required=True)
    s.add_argument("--permutations", type=int, default=PERMUTATIONS)
    s.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "fit":
            np = _np()
            feats, targs = rqlib.read_json(a.features), rqlib.read_json(a.targets)
            meta, X, names, groups, Y, tnames = load(feats, targs)
            Xr, Yr, D, By = adjust(meta, X, Y)
            report, chosen = tune(Xr, Yr, meta, groups, tnames)
            te = [k for k, m in enumerate(meta) if m["split"] == "test"]
            preds = {"schema": PRED, "features_sha256": rqlib.canonical_sha(feats), "targets": tnames,
                     "rows": [{"world": meta[k]["world"], "t": meta[k]["t"],
                               "yhat": {tn: float(chosen[tn].predict(Xr[k:k + 1])[0] + D[k] @ By[tnames.index(tn)])
                                        for tn in chosen}}
                              for k in te]}
            rqlib.write_json_durable(a.predictions, preds)
            out = {"schema": "finfolk.redqueen.probes/1", "exploratory": True, "features": names,
                   "groups": dict(zip(names, groups)), "targets": report,
                   "predictions_sha256": rqlib.sha256_file(a.predictions)}
            rqlib.write_json_durable(a.out, out)
            print(f"{a.predictions}: sha256 {out['predictions_sha256']} (commit it before evaluating)")
            return 0
        if a.cmd == "enrichment":
            doc = rqlib.read_json(a.pairs)
            rec = enrichment(doc["pairs"], doc["blocks"], a.permutations)
            rqlib.write_json_durable(a.out, dict(rec, exploratory=True))
            print(rec)
            return 0
        if rqlib.sha256_file(a.predictions) != a.pred_sha:
            raise ProbeError("the predictions' sha256 is not the committed one: refusing to evaluate")
        np = _np()
        preds, targs = rqlib.read_json(a.predictions), rqlib.read_json(a.targets)
        truth = {(r["world"], r["t"]): r for r in targs.get("rows", [])}
        res = {}
        for tn in preds["targets"]:
            yh = [r["yhat"].get(tn) for r in preds["rows"]]
            yt = [(truth.get((r["world"], r["t"])) or {}).get("y", {}).get(tn) for r in preds["rows"]]
            ok = [i for i, (p, t) in enumerate(zip(yh, yt)) if p is not None and t is not None]
            res[tn] = {"rows": len(ok), "test_r2": r2(np.array([yt[i] for i in ok]), np.array([yh[i] for i in ok]))
                       if len(ok) >= 3 else None}
        rqlib.write_json_durable(a.out, {"schema": "finfolk.redqueen.probe_eval/1", "exploratory": True,
                                         "predictions_sha256": a.pred_sha, "targets": res})
        print(res)
        return 0
    except (ProbeError, OSError, ValueError, KeyError, TypeError) as e:
        what = "" if isinstance(e, ProbeError) else f"{type(e).__name__}: "
        print(f"probes.py {a.cmd}: {what}{e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

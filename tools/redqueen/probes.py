#!/usr/bin/env python3
"""probes.py: the Level-3 EXPLORATORY observational probes (design v4 §11), as a staged pipeline in the
registration order of v4 §7.2 (staging.py; one commitment ROOT for the probes). Every finding is
exploratory, successful transfer included; associations cannot establish a feature's causal contribution,
and no intervention (ablation, clamping, sham, checkpoint surgery) is registered.

THE REGISTERED CONFIGURATION (ROOT/config/probes.json, finfolk.redqueen.probecfg/1, `register`: published
once, before any candidate): the split manifest's sha256; the FEATURES (name -> group: wiring, behaviour,
energetics, diversity; distinct_genomes and wiring_diversity are REQUIRED diversity summaries, v4 §11.2)
and the sha256 of their definition; the TARGETS (fixed-reference profile coordinates or forecast
residuals; never unconstrained latent axes) and the sha256 of their definition; the treatments; the input
SETS in tie-break order (wiring = wiring + diversity, behaviour = behaviour + energetics, combined = all);
the PROBES in tie-break order with their penalty grids in DESCENDING penalty order (lasso: elastic net
alpha 1, lambda = rel x lambda_max of the training data; enet: alpha 0.5; additive: a truncated-power cubic
basis per feature with knots at registered training quantiles, ridge lambda x n); the minimum rows per
stage; the coordinate-descent limits; the F1 control's permutations, audit level, seed namespace and
largest block.

ROWS. Features (features/2) and targets (probe_targets/2) name {world, t (M), uuid?, snapshot?}; their
ROLE comes from the split manifest (a training world's held-out snapshot takes its holdout role; a fork
branch its root's split); split / role labels are refused; each document carries the registered
"definition". Features also carry treatment (constant per root world), density, controller size, f1.

ADJUSTMENT: every feature and target is residualized on [1, density, time, controller size, treatment] by
OLS on the TRAINING rows (columns constant there are dropped and recorded); features are then scaled by
their training SD. The NUISANCE-ONLY prediction of a target is its training-fitted adjustment.

STAGES (sealing.py between them):
  register            publish the configuration.
  predict-candidates  features of TRAINING and VALIDATION rows only, targets of TRAINING rows only: the
                      adjustment, every (probe, set, penalty) fitted on training; the model state
                      (--model-out); for every validation row x target, the nuisance-only prediction and
                      every candidate's (sealing JSONL, one target_id per line).
  score-validation    the committed bytes (VAL_PRED_SHA) and VALIDATION targets only. PRIMARY METRIC: the
                      held-out RESIDUAL R^2 = 1 - SS(y - y_hat) / SS(y - y_nuisance) (the improvement over
                      the nuisance-only prediction; negative when the probe hurts); the original-scale R^2 is
                      a supporting metric. The selection per target: the largest validation residual R^2,
                      ties to the earlier probe, the earlier set, the larger penalty.
  predict-test        the recorded selection, the model state it names, features of TEST rows only.
  evaluate-test       sealing.require_test_freeze (eval script = this file), its verified bytes, TEST
                      targets only: residual R^2 (primary) and R^2 (supporting) per target.
NEGATIVE CONTROL (v4 §11.2, `enrichment`): own-world enrichment among the 32 C F1 founder populations (no
history: no coadaptation is possible). The statistic is mean(own-world pair values) - mean(cross-world pair
values); its null permutes the predator worlds' labels WITHIN BLOCKS, two-sided plus-one p. The design is
checked first, exactly (every block's permutations enumerated): it must give an own-world AND a cross-world
pair under EVERY block-respecting permutation, so no draw is undefined; an unsupported design is refused.
p < the registered audit level triggers an initializer, seed or measurement AUDIT (reported, never a finding).

    probes.py register --root ROOT --config probes.json
    probes.py predict-candidates --root ROOT --features fv.json --fit-targets ft.json --model-out model.json --out val.jsonl
    probes.py score-validation --root ROOT --predictions val.jsonl --targets vt.json --out val_scores.json
    probes.py predict-test --root ROOT --features ftest.json --model model.json --selection val_scores.json --out test.jsonl
    probes.py evaluate-test --root ROOT --predictions test.jsonl --targets tt.json --out probe_eval.json
    probes.py enrichment --root ROOT --pairs f1_pairs.json --out f1_enrichment.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
import rqlib  # noqa: E402
import sealing  # noqa: E402
import staging  # noqa: E402

CFG_SCHEMA = "finfolk.redqueen.probecfg/1"
CFG_NAME = "probes.json"
FEATURES = "finfolk.redqueen.features/2"
TARGETS = "finfolk.redqueen.probe_targets/2"
PRED = "finfolk.redqueen.probe_pred/2"
MODEL = "finfolk.redqueen.probe_model/1"
VALSCORES = "finfolk.redqueen.probe_valscores/1"
EVAL = "finfolk.redqueen.probe_eval/2"
GROUPS = ("wiring", "behaviour", "energetics", "diversity")
REQUIRED = ("distinct_genomes", "wiring_diversity")
KINDS = ("lasso", "enet", "additive")


class ProbeError(Exception):
    pass


def _np():
    import numpy as np
    return np


def _need(cond, msg):
    if not cond:
        raise ProbeError(f"configuration: {msg}")


def _int(x, lo=None):
    return isinstance(x, int) and not isinstance(x, bool) and (lo is None or x >= lo)


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# ================================================================== the registered configuration
def validate_config(root, cfg):
    _need(cfg.get("schema") == CFG_SCHEMA, f"schema {cfg.get('schema')!r}")
    for k in ("split_manifest_sha256", "feature_definition_sha256", "target_definition_sha256"):
        _need(rqlib.is_sha256(cfg.get(k)), f"{k} must be a sha256")
    fg = cfg.get("features")
    _need(isinstance(fg, dict) and fg and all(g in GROUPS for g in fg.values()), f"features: name -> one of {GROUPS}")
    miss = [f for f in REQUIRED if fg.get(f) != "diversity"]
    _need(not miss, f"the diversity summaries {miss} are required (v4 §11.2)")
    tn = cfg.get("targets")
    _need(isinstance(tn, list) and tn and all(isinstance(t, str) and t for t in tn) and len(set(tn)) == len(tn),
          "targets: distinct names")
    tr = cfg.get("treatments")
    _need(isinstance(tr, list) and tr and len(set(tr)) == len(tr) and all(isinstance(t, str) for t in tr), "treatments")
    sets = cfg.get("sets")
    _need(isinstance(sets, list) and sets and len({s.get("name") for s in sets}) == len(sets)
          and all(isinstance(s.get("name"), str) and s.get("groups") and set(s["groups"]) <= set(GROUPS) for s in sets),
          "sets: [{name, groups}] in tie-break order")
    pr = cfg.get("probes")
    kinds = [p.get("kind") for p in pr] if isinstance(pr, list) else []
    _need(kinds and len(set(kinds)) == len(kinds) and set(kinds) <= set(KINDS),
          f"probes: [{{kind, ...}}] of {KINDS}, each at most once, in tie-break order")
    for p in pr:
        grid = p.get("lambda_rel") if p["kind"] != "additive" else p.get("lambdas")
        _need(isinstance(grid, list) and grid and all(_num(x) and x > 0 for x in grid) and grid == sorted(set(grid), reverse=True),
              f"probes.{p['kind']}: a penalty grid of distinct positive values in DESCENDING order")
        if p["kind"] == "additive":
            kn = p.get("knots")
            _need(isinstance(kn, list) and kn and all(_num(x) and 0 < x < 1 for x in kn) and kn == sorted(set(kn)),
                  "probes.additive.knots: ascending training quantiles in (0, 1)")
        else:
            _need(_num(p.get("alpha")) and 0 < p["alpha"] <= 1, f"probes.{p['kind']}.alpha in (0, 1]")
    mr = cfg.get("min_rows") or {}
    _need(all(_int(mr.get(k), 2) for k in ("training", "validation", "test")), "min_rows: training, validation, test >= 2")
    cd = cfg.get("cd") or {}
    _need(_int(cd.get("iters"), 1) and _num(cd.get("tol")) and cd["tol"] > 0, "cd: iters >= 1, tol > 0")
    en = cfg.get("enrichment") or {}
    _need(_int(en.get("permutations"), 1), "enrichment.permutations: a positive integer")
    _need(_num(en.get("audit_alpha")) and 0 < en["audit_alpha"] < 1, "enrichment.audit_alpha in (0, 1)")
    _need(isinstance(en.get("seed_namespace"), str) and en["seed_namespace"], "enrichment.seed_namespace")
    _need(_int(en.get("max_block"), 2) and en["max_block"] <= 9, "enrichment.max_block in 2 .. 9 (exact enumeration)")
    p = os.path.join(root, "config", "splits.json")
    _need(os.path.isfile(p) and rqlib.sha256_file(p) == cfg["split_manifest_sha256"],
          f"{p} is not the registered split manifest")


def register(root, cfg_path):
    data = rqlib.canonical(rqlib.read_json(cfg_path))
    try:
        return staging.register_config(root, CFG_NAME, data, validate_config)
    except staging.StageError as e:
        raise ProbeError(str(e)) from None


def load_ctx(root):
    try:
        ctx = staging.load_root(root, CFG_NAME, CFG_SCHEMA, validate_config)
    except staging.StageError as e:
        raise ProbeError(str(e)) from None
    cfg = ctx["cfg"]
    ctx["names"] = sorted(cfg["features"])
    ctx["groups"] = [cfg["features"][k] for k in ctx["names"]]
    return ctx


# ================================================================== stage-filtered documents
def _ident(ctx, r, name, roles):
    try:
        i = staging.resolve_row(ctx["manifest"], r, name)
    except staging.StageError as e:
        raise ProbeError(str(e)) from None
    if i["role"] not in roles:
        raise ProbeError(f"{name} {i['world']}@{i['t']}: a {i['role']}-role row; this stage reads {sorted(roles)} only")
    return i


def load_features(ctx, path, roles, name="features"):
    """Feature rows of the permitted roles only -> (rows sorted by (world, t), sha256)."""
    np = _np()
    cfg = ctx["cfg"]
    _, doc, sha = staging.read_doc(path)
    if doc.get("schema") != FEATURES or doc.get("features") != cfg["features"]:
        raise ProbeError(f"{name}: a {FEATURES} document with the registered features")
    if rqlib.canonical_sha(doc.get("definition")) != cfg["feature_definition_sha256"]:
        raise ProbeError(f"{name}: its feature definition is not the registered one")
    out, seen, treat = [], set(), {}
    for k, r in enumerate(doc.get("rows") or []):
        i = _ident(ctx, r, f"{name} row {k + 1}", roles)
        key = (i["world"], i["t"])
        if key in seen:
            raise ProbeError(f"{name}: {key} occurs twice")
        seen.add(key)
        v = r.get("values") or {}
        if (r.get("treatment") not in cfg["treatments"] or not _num(r.get("density")) or not _num(r.get("controller_size"))
                or set(v) != set(ctx["names"]) or not all(_num(v[f]) for f in ctx["names"])):
            raise ProbeError(f"{name} {key}: treatment, density, controller_size and exactly the registered features, finite")
        if treat.setdefault(i["root"], r["treatment"]) != r["treatment"]:
            raise ProbeError(f"{name}: root world {i['root']} has two treatments")
        out.append({"id": i, "key": key, "treatment": r["treatment"], "density": float(r["density"]),
                    "controller_size": float(r["controller_size"]), "f1": bool(r.get("f1")),
                    "x": np.array([float(v[f]) for f in ctx["names"]])})
    return sorted(out, key=lambda e: e["key"]), sha


def load_targets(ctx, path, roles, name="targets"):
    """Target rows of the permitted roles only -> ({(world, t): {name: value | None}}, sha256)."""
    cfg = ctx["cfg"]
    _, doc, sha = staging.read_doc(path)
    if doc.get("schema") != TARGETS or doc.get("targets") != cfg["targets"]:
        raise ProbeError(f"{name}: a {TARGETS} document with the registered targets")
    if rqlib.canonical_sha(doc.get("definition")) != cfg["target_definition_sha256"]:
        raise ProbeError(f"{name}: its target definition is not the registered one")
    out = {}
    for k, r in enumerate(doc.get("rows") or []):
        i = _ident(ctx, r, f"{name} row {k + 1}", roles)
        key = (i["world"], i["t"])
        if key in out:
            raise ProbeError(f"{name}: {key} occurs twice")
        y = r.get("y")
        if not isinstance(y, dict) or set(y) != set(cfg["targets"]) or not all(y[t] is None or _num(y[t]) for t in y):
            raise ProbeError(f"{name} {key}: y must give every registered target (a number or null)")
        out[key] = {t: (None if y[t] is None else float(y[t])) for t in cfg["targets"]}
    return out, sha


# ================================================================== adjustment
def design(ctx, rows):
    np = _np()
    tr = ctx["cfg"]["treatments"]
    return np.array([[1.0, r["density"], float(r["key"][1]), r["controller_size"]] + [1.0 * (r["treatment"] == t) for t in tr[1:]]
                     for r in rows]).reshape(len(rows), 4 + len(tr) - 1)


def fit_adjustment(ctx, rows, Y):
    """OLS on the training rows (columns constant there dropped) -> the adjustment state."""
    np = _np()
    D = design(ctx, rows)
    X = np.array([r["x"] for r in rows])
    if len(rows) <= D.shape[1]:
        raise ProbeError("too few training rows for the adjustment")
    cols = [k for k in range(D.shape[1]) if k == 0 or np.ptp(D[:, k]) > 0]
    D = D[:, cols]
    if np.linalg.matrix_rank(D) < len(cols):
        raise ProbeError("the training design [1, density, time, controller size, treatment] is rank-deficient")
    Bx = np.linalg.lstsq(D, X, rcond=None)[0]
    sd = (X - D @ Bx).std(axis=0)
    sd = np.where(sd > 0, sd, 1.0)
    By = {}
    for j, t in enumerate(ctx["cfg"]["targets"]):
        ok = np.isfinite(Y[:, j])
        By[t] = np.linalg.lstsq(D[ok], Y[ok, j], rcond=None)[0].tolist() if ok.sum() > len(cols) else None
    return {"columns": cols, "Bx": Bx.tolist(), "sd": sd.tolist(), "By": By}


def adjusted(ctx, adj, rows):
    """-> (Xr: residualized, scaled features; D: the kept design columns)."""
    np = _np()
    D = design(ctx, rows)[:, adj["columns"]]
    X = np.array([r["x"] for r in rows]).reshape(len(rows), len(ctx["names"]))
    return (X - D @ np.asarray(adj["Bx"])) / np.asarray(adj["sd"]), D


# ================================================================== probes
def enet(X, y, lam, alpha, iters=2000, tol=1e-9):
    """min (1/2n)||y - X b||^2 + lam (alpha |b|_1 + (1 - alpha)/2 |b|^2), coordinate descent (X centred)."""
    np = _np()
    n, p = X.shape
    b = np.zeros(p)
    r = y.copy()
    cs = (X * X).sum(axis=0) / n
    for _ in range(iters):
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
        if mx < tol:
            break
    return b


def truncated_power_basis(x, knots):
    """The cubic truncated-power basis with the given interior knots: x, x^2, x^3, (x - k)^3_+."""
    np = _np()
    cols = [x, x ** 2, x ** 3] + [np.clip(x - k, 0, None) ** 3 for k in knots]
    return np.stack(cols, axis=1)


class Probe:
    def __init__(self, kind, cols, lam, alpha=None, quantiles=None):
        self.kind, self.cols, self.lam, self.alpha, self.quantiles = kind, list(cols), float(lam), alpha, quantiles

    def _expand(self, X, fit=False):
        np = _np()
        Z = X[:, self.cols]
        if self.kind != "additive":
            return Z
        if fit:
            self.knots = [np.quantile(Z[:, j], self.quantiles).tolist() for j in range(Z.shape[1])]
        B = np.hstack([truncated_power_basis(Z[:, j], self.knots[j]) for j in range(Z.shape[1])])
        if fit:
            self.bm, self.bs = B.mean(axis=0), B.std(axis=0)
            self.bs = np.where(self.bs > 0, self.bs, 1.0)
        return (B - self.bm) / self.bs

    def fit(self, X, y, cd):
        np = _np()
        B = self._expand(X, fit=True)
        self.ym = float(y.mean())
        self.xm = B.mean(axis=0) if self.kind != "additive" else np.zeros(B.shape[1])
        Bc = B - self.xm
        if self.kind == "additive":
            self.b = np.linalg.solve(Bc.T @ Bc + self.lam * len(y) * np.eye(Bc.shape[1]), Bc.T @ (y - self.ym))
        else:
            self.b = enet(Bc, y - self.ym, self.lam, self.alpha, cd["iters"], cd["tol"])
        return self

    def predict(self, X):
        return self.ym + (self._expand(X) - self.xm) @ self.b

    def state(self):
        s = {"kind": self.kind, "cols": self.cols, "lambda": self.lam, "alpha": self.alpha, "ym": self.ym,
             "xm": self.xm.tolist(), "b": self.b.tolist()}
        if self.kind == "additive":
            s.update(quantiles=self.quantiles, knots=self.knots, bm=self.bm.tolist(), bs=self.bs.tolist())
        return s

    @classmethod
    def from_state(cls, s):
        np = _np()
        p = cls(s["kind"], s["cols"], s["lambda"], s["alpha"], s.get("quantiles"))
        p.ym, p.xm, p.b = s["ym"], np.asarray(s["xm"]), np.asarray(s["b"])
        if p.kind == "additive":
            p.knots, p.bm, p.bs = s["knots"], np.asarray(s["bm"]), np.asarray(s["bs"])
        return p


def candidates(ctx, Xr, y):
    """Every registered (probe, set, penalty) fitted on the training rows -> [(cid, Probe)] in tie-break order."""
    np = _np()
    cfg, out = ctx["cfg"], []
    for p in cfg["probes"]:
        for s in cfg["sets"]:
            cols = [k for k, g in enumerate(ctx["groups"]) if g in s["groups"]]
            if not cols:
                continue
            if p["kind"] == "additive":
                lams = p["lambdas"]
            else:
                Xc = Xr[:, cols] - Xr[:, cols].mean(axis=0)
                lmax = float(np.max(np.abs(Xc.T @ (y - y.mean())))) / len(y) / p["alpha"]
                lams = [max(lmax, 1e-300) * f for f in p["lambda_rel"]]
            for k, lam in enumerate(lams):
                pr = Probe(p["kind"], cols, lam, p.get("alpha"), p.get("knots")).fit(Xr, y, cfg["cd"])
                out.append((f"{p['kind']}/{s['name']}/{k}", pr))
    return out


def r2(y, yh, base):
    """1 - SS(y - yh) / SS(y - base) (None when the denominator vanishes)."""
    np = _np()
    ss = float(np.sum((y - base) ** 2))
    return 1.0 - float(np.sum((y - yh) ** 2)) / ss if ss > 0 else None


def scores(y, yh, nuis):
    np = _np()
    y, yh, nuis = np.asarray(y), np.asarray(yh), np.asarray(nuis)
    return {"rows": len(y), "residual_r2": r2(y, yh, nuis), "r2": r2(y, yh, np.full(len(y), y.mean()))}


# ================================================================== the F1 negative control
def design_support(pairs, blocks, max_block):
    """Whether EVERY block-respecting permutation of the predator labels leaves at least one own-world and
    one cross-world pair (exact: each block's permutations enumerated) -> None, or why not."""
    by = {}
    for w, b in blocks.items():
        by.setdefault(b, []).append(w)
    if max(len(m) for m in by.values()) > max_block:
        return f"a block has more than {max_block} worlds (the exact check enumerates its permutations)"
    within = {b: [(p["prey_world"], p["pred_world"]) for p in pairs if blocks[p["pred_world"]] == b] for b in by}
    cross_block = any(blocks[p["prey_world"]] != blocks[p["pred_world"]] for p in pairs)
    own_always, cross_somewhere = False, cross_block
    for b, members in by.items():
        prs = within[b]
        own_all, all_own_some = True, False
        for perm in itertools.permutations(members):
            pi = dict(zip(members, perm))
            own = [q == pi[r] for q, r in prs]
            own_all &= any(own)
            all_own_some |= all(own)
        own_always |= own_all
        cross_somewhere |= bool(prs) and not all_own_some
    if not own_always:
        return "some block-respecting permutation leaves no own-world pair"
    if not cross_somewhere:
        return "some block-respecting permutation leaves no cross-world pair"
    return None


def enrichment(pairs, blocks, n_perm, seed_ns, alpha, max_block=8, seed_parts=("f1",)):
    """Own-world enrichment with the block-respecting permutation null (see the doc) -> record."""
    np = _np()
    if not _int(n_perm, 1):
        raise ProbeError(f"enrichment: permutations must be a positive integer, not {n_perm!r}")
    for p in pairs:
        if p.get("prey_world") not in blocks or p.get("pred_world") not in blocks:
            raise ProbeError(f"enrichment: pair {p} names a world without a block")
    worlds = sorted(blocks)
    wi = {w: k for k, w in enumerate(worlds)}
    q = np.array([wi[p["prey_world"]] for p in pairs])
    r = np.array([wi[p["pred_world"]] for p in pairs])
    v = np.array([float(p["value"]) for p in pairs])
    if not len(v) or not np.all(np.isfinite(v)):
        raise ProbeError("enrichment: no pairs, or non-finite pair values")
    why = design_support(pairs, blocks, max_block)
    if why:
        raise ProbeError(f"enrichment: unsupported design ({why}): an undefined permutation would count as a "
                         "non-exceedance; complete the design or register a conditioning")

    def stat(rr):
        own = q == rr
        if own.all() or not own.any():
            raise ProbeError("enrichment: an undefined permutation statistic in a supported design")
        return float(v[own].mean() - v[~own].mean())
    obs = stat(r)
    bl = {}
    for w in worlds:
        bl.setdefault(blocks[w], []).append(wi[w])
    rng = np.random.default_rng(rqlib.derive_seed(seed_ns, "enrichment", *seed_parts))
    ge = 0
    for _ in range(n_perm):
        perm = np.arange(len(worlds))
        for members in bl.values():
            perm[members] = rng.permutation(members)
        ge += abs(stat(perm[r])) >= abs(obs) - 1e-15
    p = (1 + ge) / (n_perm + 1)
    return {"available": True, "statistic": obs, "p": p, "permutations": n_perm, "audit": p < alpha, "audit_alpha": alpha,
            "rule": "block-respecting permutation of predator-world labels (every draw defined: the design is checked); "
                    "p < audit_alpha triggers an initializer / seed / measurement audit, never a finding"}


# ================================================================== stages
def line_identity(ctx, ln, role):
    i = staging.resolve_row(ctx["manifest"], {"world": ln.get("world"), "t": ln.get("t")}, ln.get("target_id"))
    if i["role"] != role:
        raise ProbeError(f"{ln.get('target_id')}: a {i['role']}-role row in the {role} predictions")
    return (i["world"], i["t"])


def predict_candidates(ctx, feat_path, fit_path, model_out, out):
    np = _np()
    cfg = ctx["cfg"]
    rows, fsha = load_features(ctx, feat_path, {"training", "validation"})
    yt, tsha = load_targets(ctx, fit_path, {"training"}, "fit targets")
    keys = {r["key"] for r in rows}
    extra = sorted(set(yt) - keys)
    if extra:
        raise ProbeError(f"fit targets without a feature row: {extra[:5]}")
    tr = [r for r in rows if r["id"]["role"] == "training"]
    va = [r for r in rows if r["id"]["role"] == "validation"]
    if len(tr) < cfg["min_rows"]["training"]:
        raise ProbeError(f"{len(tr)} training rows: fewer than the registered {cfg['min_rows']['training']}")
    Y = np.array([[np.nan if yt.get(r["key"], {}).get(t) is None else yt[r["key"]][t] for t in cfg["targets"]] for r in tr])
    adj = fit_adjustment(ctx, tr, Y)
    Xt, Dt = adjusted(ctx, adj, tr)
    Xv, Dv = adjusted(ctx, adj, va) if va else (None, None)
    states, avail = {}, {}
    for j, t in enumerate(cfg["targets"]):
        ok = np.isfinite(Y[:, j])
        if adj["By"][t] is None or ok.sum() < cfg["min_rows"]["training"]:
            avail[t] = "too few training rows with this target"
            continue
        yr = Y[ok, j] - Dt[ok] @ np.asarray(adj["By"][t])
        states[t] = {cid: p for cid, p in candidates(ctx, Xt[ok], yr)}
    model = {"schema": MODEL, "config_sha256": ctx["cfg_sha"],
             "fit": {"features_sha256": fsha, "targets_sha256": tsha, "training_rows": len(tr),
                     "ids_sha256": rqlib.canonical_sha(sorted([list(r["key"]) for r in tr])),
                     "target_ids_sha256": rqlib.canonical_sha(sorted([list(k) for k in yt]))},
             "adjustment": adj, "probes": {t: {cid: p.state() for cid, p in s.items()} for t, s in states.items()},
             "unavailable": avail, "environment": staging.environment(),
             "implementation": staging.implementation(os.path.abspath(__file__))}
    data = rqlib.canonical(model)
    rqlib.write_durable(model_out, data)
    prov = {"config_sha256": ctx["cfg_sha"], "split_manifest_sha256": ctx["manifest_sha"], "features_sha256": fsha,
            "fit_targets_sha256": tsha, "model_sha256": rqlib.sha256_bytes(data)}
    lines = []
    for k, r in enumerate(va):
        for t in cfg["targets"]:
            ln = {"schema": PRED, "target_id": f"probe:{t}:{r['key'][0]}:{r['key'][1]}", "world": r["key"][0],
                  "t": r["key"][1], "target": t, "stage": "validation", "provenance": prov}
            if t not in states:
                ln.update(available=False, reason=avail[t])
            else:
                nuis = float(Dv[k] @ np.asarray(adj["By"][t]))
                ln.update(available=True, nuisance=nuis,
                          candidates={cid: nuis + float(p.predict(Xv[k:k + 1])[0]) for cid, p in states[t].items()})
            lines.append(ln)
    if not lines:
        raise ProbeError("no validation rows: nothing to commit")
    rqlib.write_durable(out, staging.jsonl_bytes(lines))
    return lines


def collect(ctx, lines, truth, role):
    """The committed lines joined with exactly their stage's targets (extras and missing rows refused)."""
    want = {line_identity(ctx, ln, role) for ln in lines}
    extra = sorted(set(truth) - want)
    if extra:
        raise ProbeError(f"{len(extra)} target rows are not rows of the committed predictions: {extra[:5]}")
    missing = sorted(want - set(truth))
    if missing:
        raise ProbeError(f"{len(missing)} rows of the committed predictions have no target row (null values are "
                         f"explicit): {missing[:5]}")


def tie_key(cfg, cid):
    kind, sname, k = cid.split("/")
    return ([p["kind"] for p in cfg["probes"]].index(kind), [s["name"] for s in cfg["sets"]].index(sname), int(k))


def score_validation(ctx, lines, truth):
    cfg = ctx["cfg"]
    collect(ctx, lines, truth, "validation")
    out = {}
    for t in cfg["targets"]:
        ls = [ln for ln in lines if ln["target"] == t and ln["available"]
              and truth[(ln["world"], ln["t"])][t] is not None]
        if not any(ln["target"] == t and ln["available"] for ln in lines):
            out[t] = {"available": False, "reason": "no candidates (too few training rows)"}
            continue
        if len(ls) < cfg["min_rows"]["validation"]:
            out[t] = {"available": False, "reason": f"{len(ls)} validation rows with this target"}
            continue
        y = [truth[(ln["world"], ln["t"])][t] for ln in ls]
        nuis = [ln["nuisance"] for ln in ls]
        cands = {cid: scores(y, [ln["candidates"][cid] for ln in ls], nuis) for cid in sorted(ls[0]["candidates"])}
        ok = [c for c, s in cands.items() if s["residual_r2"] is not None]
        if not ok:
            out[t] = {"available": False, "reason": "the validation targets equal their nuisance prediction"}
            continue
        best = min(ok, key=lambda c: (-cands[c]["residual_r2"],) + tie_key(cfg, c))
        by_set = {s["name"]: max((v["residual_r2"] for c, v in cands.items() if c.split("/")[1] == s["name"]
                                  and v["residual_r2"] is not None), default=None) for s in cfg["sets"]}
        out[t] = {"available": True, "selected": best, "validation": cands[best], "candidates": cands,
                  "best_residual_r2_by_set": by_set}
    return out


def predict_test(ctx, feat_path, model, model_sha, sel, sel_sha, out):
    np = _np()
    cfg = ctx["cfg"]
    rows, fsha = load_features(ctx, feat_path, {"test"})
    adj = model["adjustment"]
    X, D = adjusted(ctx, adj, rows) if rows else (None, None)
    prov = {"config_sha256": ctx["cfg_sha"], "split_manifest_sha256": ctx["manifest_sha"], "features_sha256": fsha,
            "model_sha256": model_sha, "selection_sha256": sel_sha, "VAL_PRED_SHA": sel["VAL_PRED_SHA"]}
    lines = []
    for k, r in enumerate(rows):
        for t in cfg["targets"]:
            s = sel["targets"].get(t) or {}
            ln = {"schema": PRED, "target_id": f"probe:{t}:{r['key'][0]}:{r['key'][1]}", "world": r["key"][0],
                  "t": r["key"][1], "target": t, "stage": "test", "provenance": prov}
            if not s.get("available"):
                ln.update(available=False, reason=s.get("reason", "not selected"))
            else:
                p = Probe.from_state(model["probes"][t][s["selected"]])
                nuis = float(D[k] @ np.asarray(adj["By"][t]))
                ln.update(available=True, selected=s["selected"], nuisance=nuis, yhat=nuis + float(p.predict(X[k:k + 1])[0]))
            lines.append(ln)
    if not lines:
        raise ProbeError("no test rows: nothing to commit")
    rqlib.write_durable(out, staging.jsonl_bytes(lines))
    return lines


def evaluate_test(ctx, lines, truth):
    cfg = ctx["cfg"]
    collect(ctx, lines, truth, "test")
    res = {}
    for t in cfg["targets"]:
        ls = [ln for ln in lines if ln["target"] == t and ln["available"] and truth[(ln["world"], ln["t"])][t] is not None]
        if len(ls) < cfg["min_rows"]["test"]:
            res[t] = {"available": False, "rows": len(ls)}
            continue
        sc = scores([truth[(ln["world"], ln["t"])][t] for ln in ls], [ln["yhat"] for ln in ls], [ln["nuisance"] for ln in ls])
        res[t] = dict(sc, available=True, selected=ls[0]["selected"])
    return res


# ================================================================== CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("register")
    s.add_argument("--root", required=True)
    s.add_argument("--config", required=True)
    s = sub.add_parser("predict-candidates")
    s.add_argument("--root", required=True)
    s.add_argument("--features", required=True, help="training and validation rows only")
    s.add_argument("--fit-targets", required=True, help="training rows only")
    s.add_argument("--model-out", required=True)
    s.add_argument("--out", required=True)
    s = sub.add_parser("score-validation")
    s.add_argument("--root", required=True)
    s.add_argument("--predictions", required=True)
    s.add_argument("--targets", required=True, help="validation rows only")
    s.add_argument("--out", required=True)
    s = sub.add_parser("predict-test")
    s.add_argument("--root", required=True)
    s.add_argument("--features", required=True, help="test rows only")
    s.add_argument("--model", required=True)
    s.add_argument("--selection", required=True)
    s.add_argument("--out", required=True)
    s = sub.add_parser("evaluate-test")
    s.add_argument("--root", required=True)
    s.add_argument("--predictions", required=True)
    s.add_argument("--targets", required=True, help="test rows only")
    s.add_argument("--out", required=True)
    s = sub.add_parser("enrichment")
    s.add_argument("--root", required=True)
    s.add_argument("--pairs", required=True)
    s.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "register":
            print(f"{os.path.join(a.root, 'config', CFG_NAME)}: sha256 {register(a.root, a.config)}")
            return 0
        ctx = load_ctx(a.root)
        cfg = ctx["cfg"]
        if a.cmd == "enrichment":
            _, doc, sha = staging.read_doc(a.pairs)
            en = cfg["enrichment"]
            rec = enrichment(doc["pairs"], doc["blocks"], en["permutations"], en["seed_namespace"], en["audit_alpha"],
                             en["max_block"])
            rqlib.write_json_durable(a.out, dict(rec, exploratory=True, pairs_sha256=sha, config_sha256=ctx["cfg_sha"]))
            print({k: rec[k] for k in ("statistic", "p", "audit")})
            return 0
        if a.cmd == "predict-candidates":
            lines = predict_candidates(ctx, a.features, a.fit_targets, a.model_out, a.out)
            print(f"{a.out}: {len(lines)} validation candidate lines; commit them (sealing.py commit --stage validation)")
            return 0
        if a.cmd == "score-validation":
            lines, mk = staging.committed_rows(ctx["root"], "validation", a.predictions, ctx["cfg_sha"], {"validation"})
            truth, tsha = load_targets(ctx, a.targets, {"validation"})
            ms = {(ln.get("provenance") or {}).get("model_sha256") for ln in lines}
            if len(ms) != 1:
                raise ProbeError("the committed lines name several model states")
            doc = {"schema": VALSCORES, "exploratory": True, "VAL_PRED_SHA": mk, "config_sha256": ctx["cfg_sha"],
                   "model_sha256": ms.pop(), "targets_sha256": tsha, "metric": "residual_r2 (primary); r2 (supporting)",
                   "targets": score_validation(ctx, lines, truth)}
            rqlib.write_json_durable(a.out, doc)
            print({t: v.get("selected") for t, v in doc["targets"].items()})
            return 0
        if a.cmd == "predict-test":
            sel, sel_sha = staging.read_selection(ctx["root"], a.selection)
            if sel.get("config_sha256") != ctx["cfg_sha"]:
                raise ProbeError("the selection was made under another analysis configuration")
            mdata = rqlib.read_bytes(a.model)
            if rqlib.sha256_bytes(mdata) != sel.get("model_sha256"):
                raise ProbeError(f"{a.model} is not the model state the validation candidates were predicted with")
            lines = predict_test(ctx, a.features, json.loads(mdata.decode("utf-8")), sel["model_sha256"], sel, sel_sha, a.out)
            print(f"{a.out}: {len(lines)} test lines; commit them (sealing.py commit --stage test --eval-script probes.py), "
                  "then freeze, before evaluate-test")
            return 0
        lines, test_sha, freeze_sha = staging.test_gate(ctx["root"], a.predictions, os.path.abspath(__file__))
        for ln in lines:
            if (ln.get("provenance") or {}).get("config_sha256") != ctx["cfg_sha"] or ln.get("stage") != "test":
                raise ProbeError(f"{ln.get('target_id')}: not a test line of this analysis configuration")
        staging.check_selection_record(ctx["root"], lines)
        truth, tsha = load_targets(ctx, a.targets, {"test"})
        res = evaluate_test(ctx, lines, truth)
        rqlib.write_json_durable(a.out, {"schema": EVAL, "exploratory": True, "TEST_PRED_SHA": test_sha,
                                         "freeze_sha256": freeze_sha, "config_sha256": ctx["cfg_sha"], "targets_sha256": tsha,
                                         "metric": "residual_r2 (primary: improvement over the nuisance-only prediction); "
                                                   "r2 (supporting, original scale)", "targets": res})
        print({t: v.get("residual_r2") for t, v in res.items()})
        return 0
    except (ProbeError, staging.StageError, sealing.SealError, OSError, ValueError, KeyError, TypeError) as e:
        what = "" if isinstance(e, (ProbeError, staging.StageError, sealing.SealError)) else f"{type(e).__name__}: "
        print(f"probes.py {a.cmd}: {what}{e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""forecast.py: the Level-2 LINEAR forecasts and their limits (design v4 §10.6), as a STAGED pipeline in the
registration order of v4 §7.2, bound to the registered artifacts (§7.1) and the forward-time policy (§7.3).
Only three forecasters are registered (the neural and nearest-trajectory / nonlinear families are removed):
  persistence  Z(t0 + H) = Z(t0);
  drift        the prefix-fitted linear drift: a GLS line through the window's profiles (weights R^-1),
               extrapolated to t0 + H;
  lss          regularized stochastic LINEAR state-space dynamics z(s+1) = A z(s) + B x(s) + c + w,
               w ~ N(0, Q); y(s) = z(s) + v(s), v ~ N(0, R(s)) (R the profile's posterior covariance, v4 §10.1).

REGISTERED ARTIFACTS (staging.py: one commitment ROOT per analysis, each artifact read ONCE and built from
the verified bytes). ROOT/config/splits.json (the split manifest, built WITH the fork registry), ROOT/config/
forks.json (forks.py's registry) and ROOT/config/forecast.json, the ANALYSIS CONFIGURATION (finfolk.redqueen.
forecastcfg/1, `register`: published once, before any candidate): the sha256s of the manifest and the fork
registry; the profile "channels" (the outcome coordinates, d = their number) and the absorbing "events" (e.g.
extinction); the "covariates"; the "window" (5); the pilot-resolved "horizons" and the "primary" horizon (M;
the primary must be the fork registry's horizon); the "temporal" policy {fit_through 120, validation [141,
160], test [181, 200], separation 20, inputs_through {validation 150, test 190}}; the "map" provenance limits
{cutoff, reference_frame_max (null, or 120M for the references-at-or-before-120M repeat)}; "lss" {lambdas,
initial_state, em_iters, em_tol}; "evaluation" {bootstrap, energy_draws, seed_namespace}.

REGISTERED ORIGINS: TARGET-DISJOINT (outcome-free, derived by rule; `origins` prints them). FORK origins:
every main fork origin of the registry (root, t0) x every registered horizon, its panel the registered
branches k = 0 .. seeds-1 (identities bound to the manifest) plus the original continuation. NATIVE origins:
every native-panel world x horizon x t0 whose window ends at or before the period's inputs_through and whose
target lies after it, inside the registered validation or test period. EXCLUDED (recorded, never forecast):
a native origin whose window holds a fork origin's target row (the fork panels take precedence); an
in-sample origin (its target is a fitting row); a forward-time window crossing the separation; a training
world's target inside a separation. The registration is then VERIFIED target-disjoint: no stage's prefix row
is a target of that stage, no validation prefix row is a test target, no target is a fitting row; a
registration that is not is refused. So no stage ever reads one of its own targets before its commitment.
Each origin is CLASSIFIED: its time role (fit <= fit_through / validation / test / separation), its WORLD
role (the root's split), its TARGET role (the most held-out of the target rows' roles, holdouts included),
its STAGE (the most held-out of the target role, its window rows' roles and the time role of a forward-
time target) and its CATEGORY (v4 §7.3): world_transfer (a held-out world, target outside the forward
periods), forward_time (a training world, target in a forward period), intersection (both),
snapshot_transfer (a training world's held-out snapshot).

STAGES (each refuses what it may not read, identities checked before any value is used; sealing.py between):
  register            publish ROOT/config/forecast.json (validated; refused after VAL_PRED_SHA).
  predict-candidates  reads the FIT profiles (only training-role native rows at t <= fit_through) and the
                      validation stage's PREFIX profiles (exactly its registered window rows); never a target.
                      Fits (standardizer, dynamics, error covariances: fit rows only; every lambda), writes the
                      fitted model state (--model-out) and the candidate predictions of every validation-stage
                      origin (persistence, drift, lss at every lambda) as sealing JSONL (one target_id a line).
  (sealing.py commit --study ROOT --stage validation --predictions VAL.jsonl)
  score-validation    the committed bytes (VAL_PRED_SHA) and ONLY the validation stage's target rows;
                      selects lambda on the registered selection set (validation stage, target in the
                      validation period, primary horizon; ties to the larger lambda), scores everything.
  (sealing.py open-validation --study ROOT --scores VAL_SCORES.json)
  predict-test        the recorded selection, the model state it names (no refit) and the test stage's
                      prefix rows -> the test predictions.
  implementation      the evaluator's implementation manifest (staging.implementation_manifest: this script,
                      staging, sealing, rqlib as LOADED, the interpreter and numpy): commit and freeze it as
                      the evaluation script (sealing.py commit --stage test --eval-script IMPL.json; freeze).
  evaluate-test       sealing.require_test_freeze against the manifest recomputed in-process, then the
                      verified bytes (predictions and validation-evaluation record) and the test stage's
                      target rows only; the scoring environment is recorded.

PROFILES (finfolk.redqueen.profiles/2): "channels", "map" {cutoff, fit_sha256, references {sha256,
max_frame}} (one map for every document of an analysis), "measurement" {"shared": {group: S}} and "rows":
{world, t (M), uuid?, snapshot?} plus EXACTLY ONE of: a profile (z, cov; covariates for fit / prefix rows;
"meas_group"; no event true), an absorbing event ("events": {name: true}) or an explicit "unavailable"
reason. A fork branch's row is its own id at the target time. Split / role labels are refused.

THE MEASUREMENT SOURCE STRUCTURE. A profile's error v = u_g + e has covariance R; u_g is the component it
shares with every other profile of its measurement group g (covariance S_g: shared reference panel / donor
seeds, plan.py); e is its own; a null group is independent. Two structures are supported, and VERIFIED on
every prediction input and every target: (a) the group is absent from the fit (independent of the fitted
parameters); (b) the group is the fit's ONLY group (every fitting profile shares that one component). Then
the penalized fit is translation-equivariant: shifting every fitting profile by u moves only the intercept,
c -> c + (I - A) u, so lss's dependence on u through the fit is K = (d z_hat / d c)(I - A). Any other overlap
(a group shared with part of the fit) is refused. Every forecaster is affine in its window measurements
(gains G_s), so with L_g = sum over window rows in g of G_s (+ K for the fit's group, lss):
  Cov(z_hat, v_f) = L_g S_g for a target in group g (the recorded "cross");
  the latent forecast-error covariance under that structure (the recorded "cov"): lss: P_work + sum_g
  (L_g S_g L_g' - sum_{s in g} G_s S_g G_s'), with P_work the working filter's (independent-error)
  covariance; persistence / drift: P_state + sum_s G_s (R_s - S_g(s)) G_s' + sum_g L_g S_g L_g', with
  P_state their fit rows' native H-step state-error covariance (the empirical error covariance minus
  mean(R_T + measurement part - C - C'), PSD-clipped).
The lss FIT itself is a working model: its EM likelihood takes each profile's error as independent over
time; the structure above enters the forecast covariance and every scored quantity.

THE STATE-SPACE MODEL. Initial state: the registered prior, "diffuse" (the exact limit: z(0) | y(0) ~
N(y(0), R(0)); y(0) conditions once and its improper term leaves the likelihood) or "proper" N(m0, P0)
(conditioned on y(0) once). Fitted by penalized EM on the fit rows: the objective is the log-likelihood
minus lambda/2 tr[Q^-1 (Theta - Theta0) D (Theta - Theta0)'] (Theta = [A B c], Theta0 = [I 0 0], D = diag(1..1,
0): A toward I, B toward 0, the intercept free), maximized exactly by the M-step Theta = (S10 + lambda Theta0 D)
(S00 + lambda D)^-1, Q = (S11 - Theta S10' - S10 Theta' + Theta S00 Theta' + lambda (Theta - Theta0) D (Theta -
Theta0)') / n. NUMERICAL-FAILURE POLICY: a lambda whose EM does not converge in em_iters, or whose penalized
objective DECREASES at any iteration (by more than 1e-9 relative), is UNAVAILABLE (its diagnostic recorded);
it is never selected or forecast with. Forecast: filter the window, then H steps with the covariates held at
their last value.

EVALUATION (per origin and forecaster; y_f the measured futures, R_f their covariances, C_f the cross-
covariance with the forecast, S0 the mean shared covariance between distinct futures):
  MSE        mean_f ||y_f - z_hat||^2 - mean tr R_f + 2 mean tr C_f (one live reseed suffices);
  V_fork     tr of the reseeds' sample covariance (ddof 1) - (mean tr R_f - S0) (two or more reseeds);
  REDUCIBLE  MSE - V_fork: error reducible given the saved state under reseeding (negative values kept;
             never split into representation loss and learning error); the original continuation joins
             the reseeds in the exchangeability-qualified "with_original" sensitivity;
  supporting the energy score (seeded Monte Carlo from N(z_hat, cov + R_f - C_f - C_f')) and calibration
             (PIT of the Mahalanobis distance through the chi-square CDF; 50% / 90% coverage).
Fork panels are verified: every registered branch and the original continuation present exactly once
(a profile, an absorbing event or an explicit unavailable), identities bound, covariances valid.
POOLED per STAGE x WORLD ROLE x TARGET ROLE x TIME ROLE x CATEGORY x KIND x HORIZON x FORECASTER, never
across them (a validation-root world that fed the lambda selection never pools with a test-root world), with
a root-world cluster bootstrap (Annex H.0.4 quantiles). Twelve root worlds and 36 origins are not 144
independent replicates; ten-million-step forks do not establish long-horizon predictability.
PROVENANCE: every prediction line binds the configuration, manifest, fork registry, origins, map,
measurement table, fit rows (bytes, identities, groups), prefix, model state (with the implementation
manifest and the fitting environment) and, for test, the selection; every score records its scoring-input
fingerprint, the implementation manifest and the scoring environment.

    forecast.py register --root ROOT --config forecast.json
    forecast.py origins --root ROOT --out origins.json
    forecast.py predict-candidates --root ROOT --fit fit.json --prefix val_prefix.json --model-out model.json --out val.jsonl
    forecast.py score-validation --root ROOT --predictions val.jsonl --targets val_targets.json --out val_scores.json
    forecast.py predict-test --root ROOT --prefix test_prefix.json --model model.json --selection val_scores.json --out test.jsonl
    forecast.py implementation --out impl.json
    forecast.py evaluate-test --root ROOT --predictions test.jsonl --targets test_targets.json --out eval.json
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
import sealing  # noqa: E402
import staging  # noqa: E402

CFG_SCHEMA = "finfolk.redqueen.forecastcfg/1"
CFG_NAME = "forecast.json"
PROFILES = "finfolk.redqueen.profiles/2"
PRED = "finfolk.redqueen.forecast_pred/2"
MODEL = "finfolk.redqueen.forecast_model/1"
VALSCORES = "finfolk.redqueen.forecast_valscores/1"
EVAL = "finfolk.redqueen.forecast_eval/2"
ORIGINS = "finfolk.redqueen.forecast_origins/1"
FORKS_SCHEMA = "finfolk.redqueen.forks/1"
BASE = ("persistence", "drift")
CATEGORIES = ("world_transfer", "forward_time", "intersection", "snapshot_transfer", "in_sample")
PERIODS = ("validation", "test")
UNIT = staging.UNIT
LOG2PI = math.log(2 * math.pi)
MONO_TOL = 1e-9
LINE_KEYS = ("kind", "world", "t0", "horizon", "target_t", "primary", "window", "branches", "stage", "category",
             "world_role", "target_role", "time_role")


class ForecastError(Exception):
    pass


def _np():
    import numpy as np
    return np


def lss_name(lam):
    return f"lss[{lam!r}]"


# ================================================================== the registered configuration
def _need(cond, msg):
    if not cond:
        raise ForecastError(f"configuration: {msg}")


def _int(x, lo=None):
    return isinstance(x, int) and not isinstance(x, bool) and (lo is None or x >= lo)


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _names(x, allow_empty=False):
    return (isinstance(x, list) and (allow_empty or x) and all(isinstance(s, str) and s for s in x)
            and len(set(x)) == len(x))


def check_matrix(M, d, what, psd=True):
    """A finite, symmetric (PSD) d x d matrix -> ndarray (ForecastError otherwise)."""
    np = _np()
    try:
        A = np.asarray(M, float)
    except (TypeError, ValueError):
        raise ForecastError(f"{what}: not a numeric matrix") from None
    if A.shape != (d, d) or not np.all(np.isfinite(A)):
        raise ForecastError(f"{what}: must be a finite {d} x {d} matrix")
    sc = max(1.0, float(np.max(np.abs(A))))
    if np.max(np.abs(A - A.T)) > 1e-12 * sc:
        raise ForecastError(f"{what}: not symmetric")
    if psd and float(np.min(np.linalg.eigvalsh(A))) < -1e-12 * sc:
        raise ForecastError(f"{what}: not positive semidefinite")
    return (A + A.T) / 2


def validate_config(root, cfg, docs):
    """The configuration's own consistency, and its bindings checked against the registered artifacts as
    read once (docs: {name: (bytes, doc, sha256)})."""
    _need(cfg.get("schema") == CFG_SCHEMA, f"schema {cfg.get('schema')!r}")
    for k in ("split_manifest_sha256", "forks_sha256"):
        _need(rqlib.is_sha256(cfg.get(k)), f"{k} must be a sha256")
    _need(_names(cfg.get("channels")), "channels: distinct non-empty names (the profile coordinates)")
    _need(_names(cfg.get("events"), True), "events: distinct names of the absorbing outcomes")
    _need(_names(cfg.get("covariates"), True), "covariates: distinct names")
    d = len(cfg["channels"])
    W = cfg.get("window")
    _need(_int(W, 2), "window: an integer >= 2 (the drift needs two profiles)")
    hz = cfg.get("horizons")
    _need(isinstance(hz, list) and hz and all(_int(h, 1) for h in hz) and hz == sorted(set(hz)),
          "horizons: distinct positive integers (M), ascending (the pilot-resolved registration)")
    _need(cfg.get("primary") in hz, "primary: one of the horizons")
    tp = cfg.get("temporal") or {}
    _need(_int(tp.get("fit_through"), 0) and _int(tp.get("separation"), 0), "temporal: fit_through, separation")
    it = tp.get("inputs_through") or {}
    for p in PERIODS:
        v = tp.get(p)
        _need(isinstance(v, list) and len(v) == 2 and all(_int(x, 0) for x in v) and v[0] <= v[1],
              f"temporal.{p}: [first, last] (M)")
        _need(_int(it.get(p), 0) and v[0] + W - 1 <= it[p] and it[p] + cfg["primary"] <= v[1],
              f"temporal.inputs_through.{p}: a window fits before it and the primary horizon after it")
    ft, (vlo, vhi), (tlo, thi), sep = tp["fit_through"], tp["validation"], tp["test"], tp["separation"]
    _need(ft < vlo and vhi < tlo, "temporal: fit_through < validation < test")
    _need(vlo - ft - 1 >= sep and tlo - vhi - 1 >= sep, f"temporal: the registered {sep}M separation is violated")
    mp = cfg.get("map") or {}
    _need(_int(mp.get("cutoff"), 0) and mp["cutoff"] <= ft, "map.cutoff: the time-limited map's cutoff (<= fit_through)")
    _need(mp.get("reference_frame_max") is None or _int(mp["reference_frame_max"], 1), "map.reference_frame_max")
    ls = cfg.get("lss") or {}
    lam = ls.get("lambdas")
    _need(isinstance(lam, list) and lam and all(_num(x) and x > 0 for x in lam) and len(set(lam)) == len(lam),
          "lss.lambdas: distinct positive numbers")
    init = ls.get("initial_state") or {}
    _need(init.get("kind") in ("diffuse", "proper"), "lss.initial_state.kind: diffuse or proper")
    if init["kind"] == "proper":
        np = _np()
        m0 = init.get("mean")
        _need(isinstance(m0, list) and len(m0) == d and all(_num(x) for x in m0), "lss.initial_state.mean")
        P0 = check_matrix(init.get("cov"), d, "lss.initial_state.cov")
        _need(float(np.min(np.linalg.eigvalsh(P0))) > 0, "lss.initial_state.cov: positive definite")
    _need(_int(ls.get("em_iters"), 1) and _num(ls.get("em_tol")) and ls["em_tol"] > 0, "lss.em_iters, lss.em_tol")
    ev = cfg.get("evaluation") or {}
    _need(_int(ev.get("bootstrap"), 1) and _int(ev.get("energy_draws"), 1), "evaluation: bootstrap, energy_draws >= 1")
    _need(isinstance(ev.get("seed_namespace"), str) and ev["seed_namespace"], "evaluation.seed_namespace")
    _, man, msha = docs["splits.json"]
    _, forks, fsha = docs["forks.json"]
    _need(msha == cfg["split_manifest_sha256"], "config/splits.json is not the registered split manifest")
    _need(fsha == cfg["forks_sha256"], "config/forks.json is not the registered fork registry")
    _need(forks.get("schema") == FORKS_SCHEMA, f"forks.json: schema {forks.get('schema')!r}")
    _need(man.get("forks_sha256") == cfg["forks_sha256"],
          "the split manifest was not built with this fork registry (sealing.py manifest --forks)")
    _need(forks.get("horizon") == cfg["primary"] * UNIT,
          f"primary {cfg['primary']}M is not the fork registry's horizon ({forks.get('horizon')})")


def register(root, cfg_path):
    data = rqlib.canonical(rqlib.read_json(cfg_path))
    try:
        return staging.register_config(root, CFG_NAME, data, validate_config, files=("forks.json",))
    except staging.StageError as e:
        raise ForecastError(str(e)) from None


def load_ctx(root):
    """The commitment root's registered artifacts (each read once; the fork registry's verified bytes are
    the ones used) and the registered, verified target-disjoint origins."""
    try:
        ctx = staging.load_root(root, CFG_NAME, CFG_SCHEMA, validate_config, files=("forks.json",))
    except staging.StageError as e:
        raise ForecastError(str(e)) from None
    _, forks, fsha = ctx["docs"]["forks.json"]
    ctx.update(forks=forks, forks_sha=fsha, d=len(ctx["cfg"]["channels"]))
    ctx["fork_origins"] = fork_origins(ctx)
    ctx["origins"] = registered_origins(ctx)
    ctx["by_id"] = {o["target_id"]: o for o in ctx["origins"]}
    ctx["origins_sha"] = rqlib.canonical_sha(ctx["origins"])
    return ctx


# ================================================================== the registered origins
def fork_origins(ctx):
    """(root, t0) -> its registered main branches [{"id", "uuid", "k"}], k = 0 .. seeds-1, each bound to the
    split manifest's branch identities."""
    man, forks = ctx["manifest"], ctx["forks"]
    by = {}
    for b in forks.get("worlds") or []:
        if b.get("kind") != "main":
            continue
        mb = man.get("branches", {}).get(b["id"])
        if mb is None or mb["root"] != b["root"] or mb["uuid"] != b["uuid"]:
            raise ForecastError(f"fork branch {b['id']}: not the split manifest's branch identity")
        fr = b["origin"]["frame"]
        if not _int(fr, 1) or fr % UNIT:
            raise ForecastError(f"fork branch {b['id']}: origin frame {fr} is not a whole M")
        by.setdefault((b["root"], fr // UNIT), []).append({"id": b["id"], "uuid": b["uuid"], "k": b["origin"]["k"]})
    for key, bs in by.items():
        bs.sort(key=lambda x: x["k"])
        if [x["k"] for x in bs] != list(range(forks.get("seeds", -1))):
            raise ForecastError(f"fork origin {key}: branches k {[x['k'] for x in bs]}, registered seeds {forks.get('seeds')}")
    return by


def time_role(cfg, t):
    tp = cfg["temporal"]
    if t <= tp["fit_through"]:
        return "fit"
    for p in PERIODS:
        if tp[p][0] <= t <= tp[p][1]:
            return p
    return "separation"


def node_role(man, w, t):
    return staging.resolve_row(man, {"world": w, "t": t})["role"]


def classify(ctx, o):
    """An origin's window, target time, roles, stage, category and registered exclusion (see the doc)."""
    cfg, man = ctx["cfg"], ctx["manifest"]
    W, H, t0, w = cfg["window"], o["horizon"], o["t0"], o["world"]
    tt = t0 + H
    win = list(range(t0 - W + 1, t0 + 1))
    o.update(target_t=tt, window=win, primary=H == cfg["primary"])
    wr = man["worlds"][w]
    tr = time_role(cfg, tt)
    forward = tr in PERIODS
    excluded = None
    if win[0] < 0:
        excluded = "the window starts before F1"
        win_roles = []
    else:
        win_roles = [node_role(man, w, t) for t in win]
    if forward and win[0] < cfg["temporal"][tr][0]:
        excluded = f"the window crosses the registered separation into the {tr} period"
    elif tr == "separation" and wr == "training":
        excluded = "a training world's target inside the registered separation"
    rr = staging.most_held_out(node_role(man, w, tt), wr if o["kind"] == "fork" else None)
    stage = staging.most_held_out(rr, *win_roles, tr if forward else None)
    if wr != "training":
        cat = "intersection" if forward else "world_transfer"
    else:
        cat = "forward_time" if forward else ("snapshot_transfer" if rr != "training" else "in_sample")
    if cat == "in_sample" and not excluded:
        excluded = "in-sample: its target is a fitting row (a diagnostic, never a committed evaluation)"
    o.update(world_role=wr, target_role=rr, time_role=tr, stage=stage, category=cat, excluded=excluded)
    return o


def registered_origins(ctx):
    """Fork origins and the native origins of the target-disjoint rule (see the doc), then the fork panels'
    precedence and the disjointness verification."""
    cfg, man = ctx["cfg"], ctx["manifest"]
    tp = cfg["temporal"]
    out = []
    for (root, t0), bs in sorted(ctx["fork_origins"].items()):
        for H in cfg["horizons"]:
            out.append(classify(ctx, {"target_id": f"fork:{root}:{t0}:{H}", "kind": "fork", "world": root, "t0": t0,
                                      "horizon": H, "branches": [b["id"] for b in bs]}))
    for w in sorted(ctx["forks"].get("native_panel") or []):
        if w not in man["worlds"]:
            raise ForecastError(f"native panel world {w} is not in the split manifest")
        for p in PERIODS:
            lo, hi = tp[p]
            cut = tp["inputs_through"][p]
            for H in cfg["horizons"]:
                for t0 in range(lo + cfg["window"] - 1, cut + 1):
                    if cut < t0 + H <= hi:
                        out.append(classify(ctx, {"target_id": f"native:{w}:{t0}:{H}", "kind": "native", "world": w,
                                                  "t0": t0, "horizon": H, "branches": []}))
    fork_t = {(o["world"], o["target_t"]) for o in out if o["kind"] == "fork" and not o["excluded"]}
    for o in out:
        if o["kind"] == "native" and not o["excluded"] and any((o["world"], t) in fork_t for t in o["window"]):
            o["excluded"] = "its window holds a fork origin's target row (the fork panels take precedence)"
    probs = disjointness_problems(ctx, out)
    if probs:
        raise ForecastError("the registered origins are not target-disjoint: " + "; ".join(probs[:5]))
    return out


def disjointness_problems(ctx, origins):
    """Why the registration would let a stage read its own (or a later stage's) targets before its
    commitment: a stage's prefix row that is one of its targets, a validation prefix row that is a test
    target, a target that is a fitting row."""
    ft = ctx["cfg"]["temporal"]["fit_through"]
    pre, tgt = {}, {}
    for o in origins:
        if o["excluded"]:
            continue
        pre.setdefault(o["stage"], set()).update((o["world"], t) for t in o["window"])
        tgt.setdefault(o["stage"], set()).add((o["world"], o["target_t"]))
    probs = []
    for s in sorted(pre):
        bad = sorted(pre[s] & tgt.get(s, set()))
        if bad:
            probs.append(f"{len(bad)} {s} prefix rows are {s} targets ({bad[:3]})")
    bad = sorted(pre.get("validation", set()) & tgt.get("test", set()))
    if bad:
        probs.append(f"{len(bad)} validation prefix rows are test targets ({bad[:3]})")
    fitrows = sorted((w, t) for s in tgt for (w, t) in tgt[s]
                     if t <= ft and node_role(ctx["manifest"], w, t) == "training")
    if fitrows:
        probs.append(f"{len(fitrows)} targets are fitting rows ({fitrows[:3]})")
    return probs


def stage_rows(ctx, stages):
    """The prefix rows (window rows of the stages' registered origins) and the target rows (native target
    rows; fork branches' and original continuations' rows) -> (prefix {(world, t)}, targets {(world, t)})."""
    pre, tgt = set(), set()
    for o in ctx["origins"]:
        if o["stage"] not in stages or o["excluded"]:
            continue
        pre.update((o["world"], t) for t in o["window"])
        tgt.add((o["world"], o["target_t"]))
        tgt.update((b, o["target_t"]) for b in o["branches"])
    return pre, tgt


# ================================================================== profile documents
def load_profiles(ctx, doc, sha, name, admit):
    """Validate a profiles/2 document -> {"rows": {(world, t): row}, "map", "map_sha", "meas" {group: S},
    "meas_sha", "sha"}. FIRST every row's identity is resolved through the split manifest (labels refused) and
    admit(ident, key) -> None | why decides its membership: a row the stage may not read refuses the document
    before any of its values is converted. A row: "id", "z" / "R" (or None), "g", "x", "events", "unavailable"
    (exactly one of a profile, an absorbing event and an unavailable)."""
    np = _np()
    cfg, d = ctx["cfg"], ctx["d"]
    if doc.get("schema") != PROFILES:
        raise ForecastError(f"{name}: schema {doc.get('schema')!r}")
    raw = doc.get("rows") or []
    idents, seen, probs = [], set(), []
    for k, r in enumerate(raw):
        try:
            ident = staging.resolve_row(ctx["manifest"], r, f"{name} row {k + 1}")
        except staging.StageError as e:
            raise ForecastError(str(e)) from None
        key = (ident["world"], ident["t"])
        if key in seen:
            raise ForecastError(f"{name}: {key[0]}@{key[1]} occurs twice")
        seen.add(key)
        why = admit(ident, key)
        if why:
            probs.append(f"{key[0]}@{key[1]}: {why}")
        idents.append((ident, key))
    if probs:
        raise ForecastError(f"{len(probs)} rows of {name} may not be read at this stage: " + "; ".join(probs[:5]))
    if doc.get("channels") != cfg["channels"]:
        raise ForecastError(f"{name}: channels {doc.get('channels')} are not the registered {cfg['channels']}")
    mp = doc.get("map") or {}
    ref = mp.get("references") or {}
    if not (_int(mp.get("cutoff"), 0) and rqlib.is_sha256(mp.get("fit_sha256")) and rqlib.is_sha256(ref.get("sha256"))
            and _int(ref.get("max_frame"), 1)):
        raise ForecastError(f"{name}: the map provenance {{cutoff, fit_sha256, references {{sha256, max_frame}}}} is "
                            "required (forecast inputs need a time-limited map)")
    if mp["cutoff"] > cfg["map"]["cutoff"]:
        raise ForecastError(f"{name}: its map was fitted through {mp['cutoff']}M, after the registered cutoff "
                            f"{cfg['map']['cutoff']}M (a retrospective map cannot supply forecast inputs)")
    rmax = cfg["map"]["reference_frame_max"]
    if rmax is not None and ref["max_frame"] > rmax:
        raise ForecastError(f"{name}: its references reach frame {ref['max_frame']}, after the registered {rmax}")
    shared = (doc.get("measurement") or {}).get("shared")
    if not isinstance(shared, dict):
        raise ForecastError(f"{name}: measurement.shared (group -> shared covariance; may be empty) is required")
    meas = {g: check_matrix(S, d, f"{name}: shared measurement covariance {g}") for g, S in sorted(shared.items())}
    rows, ev_names, cv_names = {}, cfg["events"], cfg["covariates"]
    for r, (ident, key) in zip(raw, idents):
        ev = r.get("events") or {}
        if not isinstance(ev, dict) or any(e not in ev_names or not isinstance(v, bool) for e, v in ev.items()):
            raise ForecastError(f"{name} {key}: events must be registered names ({ev_names}) with booleans")
        kinds = [n for n, on in (("a profile", "z" in r), ("an absorbing event", any(ev.values())),
                                 ("an unavailable reason", r.get("unavailable") is not None)) if on]
        if len(kinds) != 1:
            raise ForecastError(f"{name} {key}: a row is exactly one of a profile, an absorbing event or an explicit "
                                f"unavailable, not {' and '.join(kinds) or 'none'}")
        row = {"id": ident, "z": None, "R": None, "g": None, "x": None, "events": ev, "unavailable": None}
        if "z" in r:
            try:
                z = np.asarray(r["z"], float)
            except (TypeError, ValueError):
                raise ForecastError(f"{name} {key}: z is not numeric") from None
            if z.shape != (d,) or not np.all(np.isfinite(z)):
                raise ForecastError(f"{name} {key}: z must be {d} finite values")
            R = check_matrix(r.get("cov"), d, f"{name} {key}: cov")
            g = r.get("meas_group")
            if g is not None:
                if g not in meas:
                    raise ForecastError(f"{name} {key}: measurement group {g!r} is not in the table")
                check_matrix(R - meas[g], d, f"{name} {key}: cov minus its shared component {g}")
            if "covariates" in r or not cv_names:
                cv = r.get("covariates") or {}
                if not isinstance(cv, dict) or set(cv) != set(cv_names) or not all(_num(cv[c]) for c in cv_names):
                    raise ForecastError(f"{name} {key}: covariates must be exactly {cv_names}, finite")
                row["x"] = np.array([float(cv[c]) for c in cv_names], float)
            row.update(z=z, R=R, g=g)
        elif r.get("unavailable") is not None:
            if not isinstance(r["unavailable"], str) or not r["unavailable"]:
                raise ForecastError(f"{name} {key}: unavailable is a reason (text)")
            row["unavailable"] = r["unavailable"]
        rows[key] = row
    first = {}
    for (w, t), row in sorted(rows.items()):
        for e, v in row["events"].items():
            if v:
                first.setdefault((w, e), t)
    for (w, e), t1 in first.items():
        if any(not rows[(w2, t)]["events"].get(e) for (w2, t) in rows if w2 == w and t > t1):
            raise ForecastError(f"{name}: {w}: event {e} is absorbing (a later row without it)")
    return {"rows": rows, "map": mp, "map_sha": rqlib.canonical_sha(mp), "meas": meas,
            "meas_sha": rqlib.canonical_sha({g: S.tolist() for g, S in meas.items()}), "sha": sha}


def read_profiles(ctx, path, name, admit):
    _, doc, sha = staging.read_doc(path)
    return load_profiles(ctx, doc, sha, name, admit)


def same_measurement(a, b, what):
    if a["map_sha"] != b["map_sha"]:
        raise ForecastError(f"{what}: another map (every document of an analysis comes from one time-limited map)")
    if a["meas_sha"] != b["meas_sha"]:
        raise ForecastError(f"{what}: another measurement table")


def fit_admit(ctx):
    ft = ctx["cfg"]["temporal"]["fit_through"]

    def admit(i, key):
        if i["branch"]:
            return "a fork branch's row is never a fitting row"
        if i["role"] != "training":
            return f"role {i['role']} (a {i['world_role']} world's snapshot) may not be fitted on"
        if key[1] > ft:
            return f"after the registered fitting cutoff {ft}M"
        return None
    return admit


def read_fit(ctx, path):
    F = read_profiles(ctx, path, "fit", fit_admit(ctx))
    bad = [k for k, r in F["rows"].items() if r["z"] is not None and r["x"] is None]
    if bad:
        raise ForecastError(f"fitting profiles without covariates: {sorted(bad)[:5]}")
    return F


def read_prefix(ctx, path, stages):
    """Exactly the stages' registered prefix rows (membership checked first), every one present."""
    want, _ = stage_rows(ctx, stages)
    P = read_profiles(ctx, path, "prefix", lambda i, key: None if key in want else
                      f"not a registered prefix row of the {'/'.join(sorted(stages))} stage (a target or another "
                      "stage's row is never a prediction input)")
    missing = sorted(want - set(P["rows"]))
    if missing:
        raise ForecastError(f"{len(missing)} registered prefix rows are missing (a profile, an absorbing event or an "
                            f"explicit unavailable): {missing[:5]}")
    bad = [k for k, r in P["rows"].items() if r["z"] is not None and r["x"] is None]
    if bad:
        raise ForecastError(f"prefix profiles without covariates: {sorted(bad)[:5]}")
    return P


def read_targets(ctx, path, lines):
    """Exactly the registered targets of the committed lines (membership checked first), every one present,
    from the predictions' map and measurement table, in a supported measurement-source structure."""
    want = set()
    for ln in lines:
        if ctx["by_id"][ln["target_id"]]["excluded"]:
            continue
        want.add((ln["world"], ln["target_t"]))
        want.update((b, ln["target_t"]) for b in ln["branches"])
    T = read_profiles(ctx, path, "targets", lambda i, key: None if key in want else
                      "not a target of the committed predictions (another stage's outcome, or a substituted future)")
    missing = sorted(want - set(T["rows"]))
    if missing:
        raise ForecastError(f"{len(missing)} registered targets are missing (a future is measured, absorbed or "
                            f"explicitly unavailable, never dropped): {missing[:5]}")
    prov = {(ln["provenance"]["map_sha256"], ln["provenance"]["measurement_sha256"]) for ln in lines}
    if len(prov) != 1:
        raise ForecastError("the predictions mix maps / measurement tables")
    mp, ms = prov.pop()
    if T["map_sha"] != mp or T["meas_sha"] != ms:
        raise ForecastError("the targets come from another map / measurement table than the predictions")
    fits = {json.dumps(ln.get("measurement"), sort_keys=True) for ln in lines}
    if len(fits) != 1:
        raise ForecastError("the predictions disagree on the fit's measurement groups")
    fm = lines[0]["measurement"] if lines else {"fit_groups": [], "fit_group": None}
    probs = source_problems(fm, [(k, r["g"]) for k, r in T["rows"].items() if r["z"] is not None])
    if probs:
        raise ForecastError("unsupported measurement-source structure: " + "; ".join(probs[:3]))
    return T


def source_problems(fit, keyed_groups):
    """Rows whose measurement group is shared with PART of the fit (neither absent from it nor its only
    group): their dependence on the fitted parameters is not identified."""
    return [f"{k[0]}@{k[1]}: group {g} is shared with part of the fit" for k, g in keyed_groups
            if g is not None and g in fit["fit_groups"] and g != fit["fit_group"]]


# ================================================================== numerics
def psd_clip(M):
    np = _np()
    M = (M + M.T) / 2
    w, V = np.linalg.eigh(M)
    return (V * np.clip(w, 0.0, None)) @ V.T


def persistence(Z, Rs, ts, H):
    """-> (z_hat, gains G_s)."""
    np = _np()
    d = Z.shape[1]
    G = [np.zeros((d, d)) for _ in range(len(Z) - 1)] + [np.eye(d)]
    return Z[-1].copy(), G


def drift(Z, Rs, ts, H):
    """The GLS line through the window's profiles (weights R^-1, jittered), extrapolated H steps -> (z_hat,
    gains G_s = L M^-1 X_s' W_s)."""
    np = _np()
    d = Z.shape[1]
    t = np.asarray(ts, float)
    tc = t - t.mean()
    M = np.zeros((2 * d, 2 * d))
    b = np.zeros(2 * d)
    XW = []
    for k in range(len(Z)):
        Ri = Rs[k] + 1e-9 * max(1e-12, float(np.trace(Rs[k])) / d) * np.eye(d)
        Wi = np.linalg.inv(Ri)
        X = np.hstack([np.eye(d), tc[k] * np.eye(d)])
        M += X.T @ Wi @ X
        b += X.T @ Wi @ Z[k]
        XW.append(X.T @ Wi)
    L = np.hstack([np.eye(d), (t[-1] + H - t.mean()) * np.eye(d)])
    LM = L @ np.linalg.inv(M)
    return LM @ b, [LM @ xw for xw in XW]


def measurement_parts(G, win, meas, extra=None):
    """Under the registered source structure, for gains G over the window rows (and extra {group: K}: the
    forecast's loading on a shared component through the fit) -> (V: Var of the forecast's measurement part,
    cross {g: L_g S_g}, own: sum G_s R_s G_s' as an independent-error filter assumes)."""
    np = _np()
    d = G[0].shape[0]
    V, own, L = np.zeros((d, d)), np.zeros((d, d)), {}
    for Gs, r in zip(G, win):
        own += Gs @ r["R"] @ Gs.T
        S = meas[r["g"]] if r["g"] is not None else 0.0
        V += Gs @ (r["R"] - S) @ Gs.T
        if r["g"] is not None:
            L[r["g"]] = L.get(r["g"], 0.0) + Gs
    for g, K in (extra or {}).items():
        L[g] = L.get(g, 0.0) + K
    for g, Lg in L.items():
        V += Lg @ meas[g] @ Lg.T
    return V, {g: Lg @ meas[g] for g, Lg in L.items()}, own


class LSS:
    """The regularized stochastic linear state-space model (see the module docstring)."""

    def __init__(self, d, k, lam, mu, sd, init):
        np = _np()
        self.d, self.k, self.lam, self.init = d, k, lam, init
        self.mu, self.sd = np.asarray(mu, float).reshape(k), np.asarray(sd, float).reshape(k)
        self.Th = np.hstack([np.eye(d), np.zeros((d, k + 1))])
        self.Q = np.eye(d)
        if init["kind"] == "proper":
            self.m0, self.P0 = np.asarray(init["mean"], float), np.asarray(init["cov"], float)

    def phi(self, x):
        """[(x - mu) / sd, 1] on the last axis."""
        np = _np()
        x = np.asarray(x, float)
        return np.concatenate([(x - self.mu) / self.sd, np.ones(x.shape[:-1] + (1,))], axis=-1)

    def filter(self, z, R, x, gains=False):
        """The Kalman filter over a batch of equal-length segments (z: b x n x d, R: b x n x d x d, x: b x n x
        k) -> filtered and one-step-predicted means / covariances, log-likelihoods (b), and the gains M
        (b x d x n d: d mf[-1] / d y) when asked."""
        np = _np()
        b, n, d = z.shape
        A, Bc = self.Th[:, :d], self.Th[:, d:]
        I = np.eye(d)
        U = self.phi(x) @ Bc.T
        mf, Pf = np.empty((b, n, d)), np.empty((b, n, d, d))
        mp, Pp = np.full((b, n, d), np.nan), np.full((b, n, d, d), np.nan)
        ll = np.zeros(b)
        M = np.zeros((b, d, n * d)) if gains else None
        for s in range(n):
            if s == 0 and self.init["kind"] == "diffuse":
                mf[:, 0], Pf[:, 0] = z[:, 0], R[:, 0]        # (the diffuse limit, conditioned once on y(0))
                if gains:
                    M[:, :, :d] = I
                continue
            if s == 0:
                m, P = np.broadcast_to(self.m0, (b, d)).copy(), np.broadcast_to(self.P0, (b, d, d)).copy()
                Mp = np.zeros((b, d, n * d)) if gains else None
            else:
                m = mf[:, s - 1] @ A.T + U[:, s - 1]
                P = A @ Pf[:, s - 1] @ A.T + self.Q
                Mp = A @ M if gains else None
            mp[:, s], Pp[:, s] = m, P
            S = P + R[:, s]
            Si = np.linalg.inv(S)
            r = z[:, s] - m
            _, logdet = np.linalg.slogdet(S)
            ll += -0.5 * (np.einsum("bi,bij,bj->b", r, Si, r) + logdet + d * LOG2PI)
            K = P @ Si
            IK = I - K
            mf[:, s] = m + np.einsum("bij,bj->bi", K, r)
            Pf[:, s] = IK @ P @ IK.transpose(0, 2, 1) + K @ R[:, s] @ K.transpose(0, 2, 1)
            if gains:
                M = IK @ Mp
                M[:, :, s * d:(s + 1) * d] += K
        return mf, Pf, mp, Pp, ll, M

    def smooth(self, z, R, x):
        """Filter + RTS smoother -> smoothed means, covariances, lag-one cross-covariances C[s+1] =
        Cov(z_{s+1}, z_s | all), log-likelihoods."""
        np = _np()
        mf, Pf, mp, Pp, ll, _ = self.filter(z, R, x)
        b, n, d = z.shape
        A = self.Th[:, :d]
        ms, Ps, C = mf.copy(), Pf.copy(), np.zeros((b, n, d, d))
        for s in range(n - 2, -1, -1):
            J = Pf[:, s] @ A.T @ np.linalg.inv(Pp[:, s + 1])
            ms[:, s] = mf[:, s] + np.einsum("bij,bj->bi", J, ms[:, s + 1] - mp[:, s + 1])
            Ps[:, s] = Pf[:, s] + J @ (Ps[:, s + 1] - Pp[:, s + 1]) @ J.transpose(0, 2, 1)
            C[:, s + 1] = Ps[:, s + 1] @ J.transpose(0, 2, 1)
        return ms, Ps, C, ll

    def penalty(self):
        np = _np()
        d, k = self.d, self.k
        D = np.diag([1.0] * (d + k) + [0.0])
        Th0 = np.hstack([np.eye(d), np.zeros((d, k + 1))])
        E = self.Th - Th0
        return 0.5 * self.lam * float(np.trace(np.linalg.solve(self.Q, E @ D @ E.T))), D, Th0

    def estep(self, groups):
        np = _np()
        d, k = self.d, self.k
        S00, S10, S11 = np.zeros((d + k + 1, d + k + 1)), np.zeros((d, d + k + 1)), np.zeros((d, d))
        n, ll = 0, 0.0
        for z, R, x in groups:
            ms, Ps, C, l_ = self.smooth(z, R, x)
            ll += float(np.sum(l_))
            F = self.phi(x[:, :-1])
            m0, m1 = ms[:, :-1], ms[:, 1:]
            S00[:d, :d] += np.sum(Ps[:, :-1], axis=(0, 1)) + np.einsum("bsi,bsj->ij", m0, m0)
            S00[:d, d:] += np.einsum("bsi,bsj->ij", m0, F)
            S00[d:, d:] += np.einsum("bsi,bsj->ij", F, F)
            S10[:, :d] += np.sum(C[:, 1:], axis=(0, 1)) + np.einsum("bsi,bsj->ij", m1, m0)
            S10[:, d:] += np.einsum("bsi,bsj->ij", m1, F)
            S11 += np.sum(Ps[:, 1:], axis=(0, 1)) + np.einsum("bsi,bsj->ij", m1, m1)
            n += m0.shape[0] * m0.shape[1]
        S00[d:, :d] = S00[:d, d:].T
        return S00, S10, S11, n, ll

    def mstep(self, S00, S10, S11, n):
        """The exact maximizer of the penalized expected complete-data objective (see the doc)."""
        np = _np()
        _, D, Th0 = self.penalty()
        Th = (S10 + self.lam * Th0 @ D) @ np.linalg.inv(S00 + self.lam * D)
        E = Th - Th0
        Qn = (S11 - Th @ S10.T - S10 @ Th.T + Th @ S00 @ Th.T + self.lam * E @ D @ E.T) / n
        Qn = (Qn + Qn.T) / 2
        w, V = np.linalg.eigh(Qn)
        floor = 1e-12 * max(float(np.mean(np.abs(w))), 1e-300)
        self.Th, self.Q = Th, (V * np.clip(w, floor, None)) @ V.T

    def fit(self, groups, iters, tol):
        """Penalized EM over the fit segments (groups of equal-length batches) -> self (objective trace and
        the numerical-failure diagnostic)."""
        np = _np()
        d = self.d
        inc = np.vstack([(z[:, 1:] - z[:, :-1]).reshape(-1, d) for z, _, _ in groups])
        if len(inc) < 2:
            raise ForecastError("the state-space fit has fewer than two consecutive fitting transitions")
        Q0 = np.atleast_2d(np.cov(inc.T, ddof=1))                # (start: the one-step increments' covariance)
        self.Q = Q0 + 1e-9 * max(float(np.trace(Q0)) / d, 1e-12) * np.eye(d)
        trace, prev, self.converged, it = [], None, False, 0
        for it in range(iters + 1):
            S00, S10, S11, n, ll = self.estep(groups)
            J = ll - self.penalty()[0]
            trace.append(J)
            if prev is not None and abs(J - prev) <= tol * max(1.0, abs(J)):
                self.converged = True
                break
            if it == iters:
                break
            self.mstep(S00, S10, S11, n)
            prev = J
        self.iterations, self.loglik, self.objective, self.trace = it, ll, trace[-1], trace
        drops = [(a - b, i + 1) for i, (a, b) in enumerate(zip(trace, trace[1:])) if b < a - MONO_TOL * max(1.0, abs(a))]
        self.monotone = not drops
        self.failure = None
        if drops:
            dec, at = max(drops)
            self.failure = f"the penalized objective decreased by {dec:.3g} at iteration {at} (non-monotone EM)"
        elif not self.converged:
            self.failure = f"the EM did not converge in {iters} iterations"
        return self

    @property
    def usable(self):
        return self.failure is None

    def forecast(self, Z, R, X, H):
        """Filter each window, then H steps with the covariates held at their last value -> (means b x d,
        working covariances b x d x d, gains b x d x (n d))."""
        np = _np()
        d = self.d
        mf, Pf, _, _, _, M = self.filter(Z, R, X, gains=True)
        A, Bc = self.Th[:, :d], self.Th[:, d:]
        u = self.phi(X[:, -1]) @ Bc.T
        m, P = mf[:, -1], Pf[:, -1]
        for _ in range(H):
            m, P, M = m @ A.T + u, A @ P @ A.T + self.Q, A @ M
        return m, P, M

    def fit_loading(self, Z, R, X, H):
        """K = (d z_hat / d c)(I - A) per window (b x d x d): the forecast's response to a shift u of EVERY
        fitting profile (the fit moves c by (I - A) u); exact, the forecast being affine in c."""
        np = _np()
        d = self.d
        m0 = self.forecast(Z, R, X, H)[0]
        dc = np.empty((len(Z), d, d))
        keep = self.Th.copy()
        for j in range(d):
            self.Th = keep.copy()
            self.Th[j, -1] += 1.0
            dc[:, :, j] = self.forecast(Z, R, X, H)[0] - m0
        self.Th = keep
        return dc @ (np.eye(d) - keep[:, :d])

    def state(self):
        return {"lambda": self.lam, "Theta": self.Th.tolist(), "Q": self.Q.tolist(), "converged": self.converged,
                "iterations": self.iterations, "objective": self.objective, "loglik": self.loglik,
                "monotone": self.monotone, "usable": self.usable, "failure": self.failure}


# ================================================================== fitting (fit rows only)
def series(P):
    """{world: sorted [(t, row)]} of a document's native rows."""
    out = {}
    for (w, t), r in P["rows"].items():
        out.setdefault(w, []).append((t, r))
    return {w: sorted(v, key=lambda e: e[0]) for w, v in out.items()}


def fit_segments(P):
    """Consecutive-time runs (>= 2) of fit profiles, grouped by length -> [(z, R, x) batches]."""
    np = _np()
    runs = []
    for w, ser in sorted(series(P).items()):
        run = []
        for t, r in ser:
            if r["z"] is not None and run and t == run[-1][0] + 1:
                run.append((t, r))
                continue
            if len(run) > 1:
                runs.append(run)
            run = [(t, r)] if r["z"] is not None else []
        if len(run) > 1:
            runs.append(run)
    groups = {}
    for run in runs:
        groups.setdefault(len(run), []).append(run)
    return [(np.array([[r["z"] for _, r in run] for run in g]), np.array([[r["R"] for _, r in run] for run in g]),
             np.array([[r["x"] for _, r in run] for run in g], float).reshape(len(g), n, len(g[0][0][1]["x"])))
            for n, g in sorted(groups.items())]


def window_rows(rows, w, ts):
    """The window's rows if every one carries a profile, else (None, reason)."""
    out = []
    for t in ts:
        r = rows.get((w, t))
        if r is None:
            return None, f"{w}@{t} missing"
        if r["z"] is None:
            return None, f"{w}@{t}: " + (r["unavailable"] or "absorbing event " + ",".join(e for e, v in r["events"].items() if v))
        out.append(r)
    return out, None


def state_error_cov(ctx, P, H, fc):
    """persistence / drift: the fit rows' native H-step STATE-error covariance: the empirical error covariance
    minus mean(R_T + the forecast's measurement part - C_T - C_T'), PSD-clipped."""
    np = _np()
    W, d = ctx["cfg"]["window"], ctx["d"]
    E, corr = [], []
    for w, ser in sorted(series(P).items()):
        for t0, _ in ser:
            win, _why = window_rows(P["rows"], w, range(t0 - W + 1, t0 + 1))
            tg = P["rows"].get((w, t0 + H))
            if win is None or tg is None or tg["z"] is None:
                continue
            zh, G = fc(np.array([r["z"] for r in win]), [r["R"] for r in win], list(range(t0 - W + 1, t0 + 1)), H)
            V, cross, _ = measurement_parts(G, win, P["meas"])
            C = cross.get(tg["g"], np.zeros((d, d))) if tg["g"] is not None else np.zeros((d, d))
            E.append(tg["z"] - zh)
            corr.append(tg["R"] + V - C - C.T)
    if len(E) < 2:
        raise ForecastError(f"fewer than two fitting native origins at H = {H}")
    E = np.array(E)
    return psd_clip(np.atleast_2d(np.cov(E.T, ddof=1)) - np.mean(corr, axis=0))


def fit_model(ctx, P):
    """The fit (standardizer, every lambda, the state-error covariances, the fit's measurement groups) ->
    the model state document."""
    np = _np()
    cfg, d = ctx["cfg"], ctx["d"]
    k = len(cfg["covariates"])
    prof = [r for r in P["rows"].values() if r["z"] is not None]
    if not prof:
        raise ForecastError("no fitting profiles")
    X = np.array([r["x"] for r in prof], float).reshape(len(prof), k)
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd = np.where(sd > 0, sd, 1.0)
    groups = fit_segments(P)
    if not groups:
        raise ForecastError("no two consecutive fitting profiles: the state-space model cannot be fitted")
    ls = cfg["lss"]
    fits = [LSS(d, k, lam, mu, sd, ls["initial_state"]).fit(groups, ls["em_iters"], ls["em_tol"]).state()
            for lam in ls["lambdas"]]
    covs = {fn.__name__: {str(H): state_error_cov(ctx, P, H, fn).tolist() for H in cfg["horizons"]}
            for fn in (persistence, drift)}
    ids = sorted([w, t] for (w, t), r in P["rows"].items() if r["z"] is not None)
    gs = {r["g"] for r in prof}
    fit_groups = sorted(g for g in gs if g is not None)
    return {"schema": MODEL, "config_sha256": ctx["cfg_sha"],
            "fit": {"sha256": P["sha"], "profiles": len(ids), "ids_sha256": rqlib.canonical_sha(ids),
                    "transitions": int(sum(z.shape[0] * (z.shape[1] - 1) for z, _, _ in groups)),
                    "map_sha256": P["map_sha"], "measurement_sha256": P["meas_sha"],
                    "measurement": {"fit_groups": fit_groups,
                                    "fit_group": fit_groups[0] if len(gs) == 1 and fit_groups else None}},
            "standardizer": {"mean": mu.tolist(), "sd": sd.tolist()}, "lss": fits, "state_covs": covs,
            "environment": staging.environment(),
            "implementation": json.loads(staging.implementation_manifest(os.path.abspath(__file__)))}


def model_lss(ctx, model, lam):
    np = _np()
    st = next((s for s in model["lss"] if s["lambda"] == lam), None)
    if st is None:
        raise ForecastError(f"the model state has no lambda {lam}")
    m = LSS(ctx["d"], len(ctx["cfg"]["covariates"]), lam, model["standardizer"]["mean"], model["standardizer"]["sd"],
            ctx["cfg"]["lss"]["initial_state"])
    m.Th, m.Q, m.failure = np.asarray(st["Theta"], float), np.asarray(st["Q"], float), st["failure"]
    return m


# ================================================================== predictions
def predict_lines(ctx, P, model, model_sha, stages, names, extra_prov):
    """Every registered origin of the stages -> sealing JSONL lines (one target_id each); names: lambda ->
    the lss forecaster's name (lss[lambda] for the validation candidates, lss for the selected one)."""
    np = _np()
    cfg, d = ctx["cfg"], ctx["d"]
    fitm = model["fit"]["measurement"]
    prov = {"config_sha256": ctx["cfg_sha"], "split_manifest_sha256": ctx["manifest_sha"], "forks_sha256": ctx["forks_sha"],
            "origins_sha256": ctx["origins_sha"], "map_sha256": P["map_sha"], "measurement_sha256": P["meas_sha"],
            "prefix_sha256": P["sha"], "fit_sha256": model["fit"]["sha256"], "fit_ids_sha256": model["fit"]["ids_sha256"],
            "model_sha256": model_sha, **extra_prov}
    lss = {lam: model_lss(ctx, model, lam) for lam in names}
    k = len(cfg["covariates"])
    lines, todo = [], []
    for o in ctx["origins"]:
        if o["stage"] not in stages:
            continue
        line = {"schema": PRED, "target_id": o["target_id"], **{q: o[q] for q in LINE_KEYS},
                "measurement": fitm, "provenance": prov}
        win, why = (None, o["excluded"]) if o["excluded"] else window_rows(P["rows"], o["world"], o["window"])
        if win is not None:
            probs = source_problems(fitm, [((o["world"], t), r["g"]) for t, r in zip(o["window"], win)])
            if probs:
                win, why = None, "unsupported measurement-source structure: " + "; ".join(probs[:2])
        if win is None:
            line.update(available=False, reason=why)
        else:
            line["available"] = True
            todo.append((line, win))
        lines.append(line)
    fg = fitm["fit_group"]
    for H in cfg["horizons"]:
        batch = [(ln, win) for ln, win in todo if ln["horizon"] == H]
        if not batch:
            continue
        Z = np.array([[r["z"] for r in win] for _, win in batch])
        R = np.array([[r["R"] for r in win] for _, win in batch])
        X = np.array([[r["x"] for r in win] for _, win in batch], float).reshape(len(batch), cfg["window"], k)
        outs = {lam: m.forecast(Z, R, X, H) + ((m.fit_loading(Z, R, X, H) if fg else None),)
                for lam, m in lss.items() if m.usable}
        for j, (ln, win) in enumerate(batch):
            fcs = {}
            for fn in (persistence, drift):
                zh, G = fn(Z[j], R[j], ln["window"], H)
                V, cross, _ = measurement_parts(G, win, P["meas"])
                fcs[fn.__name__] = {"z": zh.tolist(), "cov": psd_clip(np.asarray(model["state_covs"][fn.__name__][str(H)]) + V).tolist(),
                                    "cross": {g: c.tolist() for g, c in cross.items()}}
            for lam, name in names.items():
                if lam not in outs:
                    fcs[name] = {"unavailable": lss[lam].failure}
                    continue
                m_, P_, M_, K_ = outs[lam]
                G = [M_[j][:, s * d:(s + 1) * d] for s in range(cfg["window"])]
                V, cross, own = measurement_parts(G, win, P["meas"], {fg: K_[j]} if fg else None)
                fcs[name] = {"z": m_[j].tolist(), "cov": psd_clip(P_[j] - own + V).tolist(),
                             "cross": {g: c.tolist() for g, c in cross.items()}}
            ln["forecasts"] = fcs
    return lines


def check_lines(ctx, lines, stages):
    """Committed lines must be the registered origins of the stages, unmodified."""
    want = {o["target_id"] for o in ctx["origins"] if o["stage"] in stages}
    have = set()
    for ln in lines:
        o = ctx["by_id"].get(ln.get("target_id"))
        if o is None or o["stage"] not in stages or any(ln.get(q) != o[q] for q in LINE_KEYS):
            raise ForecastError(f"{ln.get('target_id')}: not a registered {'/'.join(sorted(stages))} origin as registered")
        have.add(o["target_id"])
    if have != want:
        raise ForecastError(f"the predictions omit {len(want - have)} registered origins: {sorted(want - have)[:3]}")


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


def energy_score(zh, S, y, rng, draws):
    """ES of N(zh, S) at y (Monte Carlo: E||X - y|| - 1/2 E||X - X'||)."""
    np = _np()
    d = len(zh)
    L = np.linalg.cholesky(psd_clip(S) + 1e-12 * max(1e-12, float(np.trace(S)) / d) * np.eye(d))
    X = zh + rng.standard_normal((draws, d)) @ L.T
    X2 = zh + rng.standard_normal((draws, d)) @ L.T
    return float(np.mean(np.linalg.norm(X - y, axis=1)) - 0.5 * np.mean(np.linalg.norm(X - X2, axis=1)))


def origin_futures(ln, T):
    """The registered futures of a line from the target rows: fork -> the branches (reseeds) and the
    original continuation; native -> the native target row."""
    tt = ln["target_t"]
    if ln["kind"] == "native":
        return [{"kind": "native", "row": T["rows"][(ln["world"], tt)]}]
    return ([{"kind": "reseed", "row": T["rows"][(b, tt)]} for b in ln["branches"]]
            + [{"kind": "original", "row": T["rows"][(ln["world"], tt)]}])


def shared_between(a, b, meas):
    return meas[a["g"]] if a["g"] is not None and a["g"] == b["g"] else None


def origin_metrics(fc, futures, meas, events, rng_of, draws):
    """One origin x forecaster (see the module docstring); None values where unavailable."""
    np = _np()
    rec = {"futures": len(futures), "unavailable": sum(1 for f in futures if f["row"]["unavailable"]),
           "events": {e: sum(1 for f in futures if f["row"]["events"].get(e)) for e in events}}
    live = [f for f in futures if f["row"]["z"] is not None]
    rec["live"] = len(live)
    if "z" not in fc:
        return dict(rec, forecast_unavailable=fc.get("unavailable"))
    zh, P = np.asarray(fc["z"], float), np.asarray(fc["cov"], float)
    d = len(zh)

    def C_of(f):
        g = f["row"]["g"]
        return np.asarray(fc["cross"][g], float) if g is not None and g in fc["cross"] else np.zeros((d, d))

    def block(fs):
        if not fs:
            return None, None
        Y = np.array([f["row"]["z"] for f in fs])
        mR = float(np.mean([np.trace(f["row"]["R"]) for f in fs]))
        mC = float(np.mean([np.trace(C_of(f)) for f in fs]))
        mse = float(np.mean(np.sum((Y - zh) ** 2, axis=1))) - mR + 2 * mC
        if len(fs) < 2:
            return mse, None
        sh = [np.trace(S) if (S := shared_between(a["row"], b["row"], meas)) is not None else 0.0
              for i, a in enumerate(fs) for j, b in enumerate(fs) if i != j]
        V = float(np.trace(np.atleast_2d(np.cov(Y.T, ddof=1)))) - (mR - float(np.mean(sh)))
        return mse, V
    if futures[0]["kind"] == "native":
        mse, _ = block(live)
        rec.update(mse=mse)
    else:
        rs = [f for f in live if f["kind"] == "reseed"]
        mse, V = block(rs)
        m5, V5 = block(live)
        rec.update(reseeds=len(rs), mse=mse, v_fork=V, reducible=(mse - V) if V is not None else None,
                   with_original={"mse": m5, "v_fork": V5, "reducible": (m5 - V5) if V5 is not None else None})
    if live:
        es, pit = [], []
        for j, f in enumerate(live):
            C = C_of(f)
            S = psd_clip(P + f["row"]["R"] - C - C.T)
            r = f["row"]["z"] - zh
            pit.append(chi2_cdf(float(r @ np.linalg.solve(S + 1e-12 * max(1e-12, float(np.trace(S))) * np.eye(d), r)), d))
            es.append(energy_score(zh, S, f["row"]["z"], rng_of(j), draws))
        rec.update(energy=float(np.mean(es)), pit=pit, cover50=float(np.mean([p <= 0.5 for p in pit])),
                   cover90=float(np.mean([p <= 0.9 for p in pit])))
    return rec


def quantile(sorted_vals, u):
    """Annex H.0.4: Q(u) = z_(min{B, max[1, ceil((B + 1) u)]})."""
    B = len(sorted_vals)
    return sorted_vals[min(B, max(1, math.ceil((B + 1) * u))) - 1]


POOL_KEYS = ("stage", "world_role", "target_role", "time_role", "category", "kind", "horizon")


def pool(ctx, per):
    """Means per STAGE / WORLD ROLE / TARGET ROLE / TIME ROLE / CATEGORY / KIND / H / FORECASTER (never across
    them), root-world cluster bootstrap."""
    np = _np()
    ev = ctx["cfg"]["evaluation"]
    groups = {}
    for r in per:
        if not r["available"]:
            continue
        for fc, m in r["metrics"].items():
            groups.setdefault(tuple(r[q] for q in POOL_KEYS) + (fc,), []).append((r["world"], m))
    out = {}
    for key, rows in sorted(groups.items()):
        name = "/".join([str(x) if q != "horizon" else f"H{x}" for q, x in zip(POOL_KEYS + ("forecaster",), key)])
        qs = {}
        for q in ("mse", "v_fork", "reducible", "energy", "cover50", "cover90"):
            qs[q] = [(w, m[q]) for w, m in rows if m.get(q) is not None]
        for q in ("mse", "v_fork", "reducible"):
            qs[q + "_with_original"] = [(w, m["with_original"][q]) for w, m in rows
                                        if (m.get("with_original") or {}).get(q) is not None]
        rng = np.random.default_rng(rqlib.derive_seed(ev["seed_namespace"], "bootstrap", name))
        rec = dict(zip(POOL_KEYS + ("forecaster",), key), primary=key[6] == ctx["cfg"]["primary"],
                   origins=len(rows), worlds=len({w for w, _ in rows}))
        ws = sorted({w for w, _ in rows})
        wi = {w: i for i, w in enumerate(ws)}
        picks = rng.integers(0, len(ws), (ev["bootstrap"], len(ws)))      # (whole root worlds, with their origins)
        for q, vals in qs.items():
            if not vals:
                rec[q] = None
                continue
            v = np.array([x for _, x in vals])
            s, c = np.zeros(len(ws)), np.zeros(len(ws))
            for (w, _), x in zip(vals, v):
                s[wi[w]] += x
                c[wi[w]] += 1
            num, den = s[picks].sum(axis=1), c[picks].sum(axis=1)
            draws = sorted((num[den > 0] / den[den > 0]).tolist())
            rec[q] = {"mean": float(np.mean(v)), "n": len(vals),
                      "ci95": [quantile(draws, 0.025), quantile(draws, 0.975)] if draws else None}
        out[name] = rec
    return out


def score_lines(ctx, lines, T):
    """Per-line metrics of every forecaster in the lines (registered roles and categories kept)."""
    cfg = ctx["cfg"]
    ev = cfg["evaluation"]
    per = []
    for ln in lines:
        rec = {q: ln[q] for q in ("target_id", "world", "t0", "target_t", "primary", "available") + POOL_KEYS}
        if not ln["available"]:
            rec["reason"] = ln.get("reason")
            per.append(rec)
            continue
        futs = origin_futures(ln, T)
        rec["metrics"] = {}
        for fc, f in sorted(ln["forecasts"].items()):
            def rng_of(j, fc=fc):
                return _np().random.default_rng(rqlib.derive_seed(ev["seed_namespace"], "energy", ln["target_id"], fc, j))
            rec["metrics"][fc] = origin_metrics(f, futs, T["meas"], cfg["events"], rng_of, ev["energy_draws"])
        per.append(rec)
    return per


def selection_rows(ctx, per):
    """The registered selection set: available validation-stage origins whose target lies in the validation
    period, at the primary horizon."""
    return [r for r in per if r["available"] and r["stage"] == "validation" and r["primary"]
            and r["time_role"] == "validation"]


def select_lambda(ctx, per):
    """lss[lambda]'s mean corrected MSE over the selection set; the minimum, ties to the larger lambda. A
    lambda the numerical-failure policy made unavailable is never selected."""
    np = _np()
    rows = selection_rows(ctx, per)

    def mean_mse(name):
        ms = [r["metrics"][name] for r in rows]
        if not rows:
            return None, 0, "no available validation-period origin at the primary horizon"
        bad = next((m["forecast_unavailable"] for m in ms if m.get("forecast_unavailable")), None)
        if bad:
            return None, 0, bad
        v = [m["mse"] for m in ms if m.get("mse") is not None]
        return (float(np.mean(v)) if v else None), len(v), None if v else "no live target"
    by = []
    for lam in ctx["cfg"]["lss"]["lambdas"]:
        mse, n, why = mean_mse(lss_name(lam))
        by.append(dict({"lambda": lam, "mse": mse, "origins": n}, **({"reason": why} if why else {})))
    ok = [b for b in by if b["mse"] is not None]
    if not ok:
        raise ForecastError("no lambda can be selected: " + "; ".join(sorted({b.get("reason", "") for b in by})))
    best = min(ok, key=lambda b: (b["mse"], -b["lambda"]))
    return {"rule": "validation stage, target in the validation period, primary horizon; minimum mean corrected "
                    "MSE, ties to the larger lambda; unavailable lambdas never selected", "candidates": by,
            "lambda": best["lambda"], "reference": {fc: mean_mse(fc)[0] for fc in BASE}}


# ================================================================== CLI
def uniform(lines, key):
    vals = {(ln.get("provenance") or {}).get(key) for ln in lines}
    if len(vals) != 1:
        raise ForecastError(f"the prediction lines disagree on {key}")
    return vals.pop()


def scoring_record(impl):
    return {"implementation_sha256": rqlib.sha256_bytes(impl), "implementation": json.loads(impl.decode("utf-8")),
            "environment": staging.environment()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("register")
    s.add_argument("--root", required=True)
    s.add_argument("--config", required=True)
    s = sub.add_parser("origins")
    s.add_argument("--root", required=True)
    s.add_argument("--out", required=True)
    s = sub.add_parser("predict-candidates")
    s.add_argument("--root", required=True)
    s.add_argument("--fit", required=True, help="training-role native profiles at t <= fit_through only")
    s.add_argument("--prefix", required=True, help="exactly the validation stage's registered window rows")
    s.add_argument("--model-out", required=True)
    s.add_argument("--out", required=True)
    s = sub.add_parser("score-validation")
    s.add_argument("--root", required=True)
    s.add_argument("--predictions", required=True)
    s.add_argument("--targets", required=True, help="exactly the validation stage's target rows")
    s.add_argument("--out", required=True)
    s = sub.add_parser("predict-test")
    s.add_argument("--root", required=True)
    s.add_argument("--prefix", required=True, help="exactly the test stage's registered window rows")
    s.add_argument("--model", required=True)
    s.add_argument("--selection", required=True)
    s.add_argument("--out", required=True)
    s = sub.add_parser("implementation")
    s.add_argument("--out", required=True)
    s = sub.add_parser("evaluate-test")
    s.add_argument("--root", required=True)
    s.add_argument("--predictions", required=True)
    s.add_argument("--targets", required=True, help="exactly the test stage's target rows")
    s.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    test_stages = {"test", "training"}
    try:
        if a.cmd == "register":
            sha = register(a.root, a.config)
            print(f"{os.path.join(a.root, 'config', CFG_NAME)}: sha256 {sha}")
            return 0
        if a.cmd == "implementation":
            impl = staging.implementation_manifest(os.path.abspath(__file__))
            rqlib.write_durable(a.out, impl)
            print(f"{a.out}: sha256 {rqlib.sha256_bytes(impl)} (commit and freeze it as the evaluation script)")
            return 0
        ctx = load_ctx(a.root)
        cfg = ctx["cfg"]
        if a.cmd == "origins":
            doc = {"schema": ORIGINS, "config_sha256": ctx["cfg_sha"], "origins_sha256": ctx["origins_sha"],
                   "origins": ctx["origins"], "rows": {}}
            for name, stages in (("validation", {"validation"}), ("test", test_stages)):
                pre, tgt = stage_rows(ctx, stages)
                doc["rows"][name] = {"prefix": sorted([w, t] for w, t in pre), "targets": sorted([w, t] for w, t in tgt)}
            rqlib.write_json_durable(a.out, doc)
            print(f"{a.out}: {len(ctx['origins'])} registered origins (no outcome)")
            return 0
        if a.cmd == "predict-candidates":
            F = read_fit(ctx, a.fit)
            P = read_prefix(ctx, a.prefix, {"validation"})
            same_measurement(F, P, "the prefix")
            model = fit_model(ctx, F)
            data = rqlib.canonical(model)
            rqlib.write_durable(a.model_out, data)
            lines = predict_lines(ctx, P, model, rqlib.sha256_bytes(data), {"validation"},
                                  {lam: lss_name(lam) for lam in cfg["lss"]["lambdas"]}, {})
            rqlib.write_durable(a.out, staging.jsonl_bytes(lines))
            print(f"{a.out}: {len(lines)} validation candidates; commit them (sealing.py commit --stage validation) "
                  "before score-validation")
            return 0
        if a.cmd == "score-validation":
            lines, mk = staging.committed_rows(ctx["root"], "validation", a.predictions, ctx["cfg_sha"], {"validation"})
            check_lines(ctx, lines, {"validation"})
            T = read_targets(ctx, a.targets, lines)
            per = score_lines(ctx, lines, T)
            impl = staging.implementation_manifest(os.path.abspath(__file__))
            doc = {"schema": VALSCORES, "VAL_PRED_SHA": mk, "config_sha256": ctx["cfg_sha"],
                   "model_sha256": uniform(lines, "model_sha256"), "targets_sha256": T["sha"],
                   "selection": select_lambda(ctx, per), "pooled": pool(ctx, per), "origins": per,
                   "scoring": scoring_record(impl)}
            rqlib.write_json_durable(a.out, doc)
            print(f"lambda = {doc['selection']['lambda']}; record the scores (sealing.py open-validation) before predict-test")
            return 0
        if a.cmd == "predict-test":
            sel, sel_sha = staging.read_selection(ctx["root"], a.selection)
            if sel.get("config_sha256") != ctx["cfg_sha"]:
                raise ForecastError("the selection was made under another analysis configuration")
            mdata = rqlib.read_bytes(a.model)
            if rqlib.sha256_bytes(mdata) != sel.get("model_sha256"):
                raise ForecastError(f"{a.model} is not the model state the validation candidates were predicted with")
            model = json.loads(mdata.decode("utf-8"))
            lam = sel["selection"]["lambda"]
            if not model_lss(ctx, model, lam).usable:
                raise ForecastError(f"the selected lambda {lam} is unavailable under the numerical-failure policy")
            P = read_prefix(ctx, a.prefix, test_stages)
            if P["map_sha"] != model["fit"]["map_sha256"] or P["meas_sha"] != model["fit"]["measurement_sha256"]:
                raise ForecastError("the prefix comes from another map / measurement table than the fit")
            lines = predict_lines(ctx, P, model, sel["model_sha256"], test_stages, {lam: "lss"},
                                  {"selection_sha256": sel_sha, "VAL_PRED_SHA": sel["VAL_PRED_SHA"], "lambda": lam})
            rqlib.write_durable(a.out, staging.jsonl_bytes(lines))
            print(f"{a.out}: {len(lines)} test-stage predictions (lambda {lam}); commit them with the implementation "
                  "manifest (sealing.py commit --stage test --eval-script IMPL.json), then freeze, before evaluate-test")
            return 0
        # evaluate-test: the gate against the implementation as loaded, then the verified bytes only
        impl = staging.implementation_manifest(os.path.abspath(__file__))
        g = staging.test_gate(ctx["root"], a.predictions, impl)
        lines = g["rows"]
        for ln in lines:
            if (ln.get("provenance") or {}).get("config_sha256") != ctx["cfg_sha"]:
                raise ForecastError(f"{ln.get('target_id')}: predicted under another analysis configuration")
        staging.check_selection_record(g["validation_evaluation"], lines)
        check_lines(ctx, lines, test_stages)
        T = read_targets(ctx, a.targets, lines)
        per = score_lines(ctx, lines, T)
        doc = {"schema": EVAL, "TEST_PRED_SHA": g["TEST_PRED_SHA"], "freeze_sha256": g["freeze_sha256"],
               "config_sha256": ctx["cfg_sha"], "selection_sha256": uniform(lines, "selection_sha256"),
               "lambda": uniform(lines, "lambda"), "targets_sha256": T["sha"], "pooled": pool(ctx, per), "origins": per,
               "scoring": scoring_record(impl),
               "note": "reducible = MSE - V_fork: error reducible given the saved state under reseeding; negative "
                       "finite-sample values retained; not split into representation loss and learning error; every "
                       "stage x world role x target role x time role x category is reported on its own (v4 §7.3)"}
        rqlib.write_json_durable(a.out, doc)
        for k, v in sorted(doc["pooled"].items()):
            if v["primary"]:
                print(k, {q: (v[q] or {}).get("mean") for q in ("mse", "v_fork", "reducible")})
        return 0
    except (ForecastError, staging.StageError, sealing.SealError, OSError, ValueError, KeyError, TypeError) as e:
        what = "" if isinstance(e, (ForecastError, staging.StageError, sealing.SealError)) else f"{type(e).__name__}: "
        print(f"forecast.py {a.cmd}: {what}{e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

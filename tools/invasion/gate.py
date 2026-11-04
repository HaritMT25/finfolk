#!/usr/bin/env python3
"""gate.py: the preregistered calibration gate of the Finfolk invasion study (preregistration draft
sha256 cf1518bc..., approved 2026-11-04T06:44Z; sections 3-4).

    gate.py freeze --out DIR [--counts COUNTS.json] [--bank-spec SPEC.json]
    gate.py run    --out DIR --bank BLOCKS.json --bank-plan PLAN.jsonl [--bank-inputs INPUTS.json]
                   [--workers 4] [--counts COUNTS.json] [--bank-spec SPEC.json]
    gate.py seeds  --out SEEDS.json [--avoid PLAN.jsonl ...] [--home-seeds-used 201,202,...]

freeze  writes DIR/manifest.json and nothing else; no bank is read. The manifest is the frozen gate:
        master seed 20271103, the ordered task schedule (index, world, variant, datasets, task seed),
        every count, the registered bank identity (approved plan sha256, item IDs, snapshot hashes,
        28,800 cells), the source hashes of every tool, the fitting freeze, the worlds, the marginal
        law, the plant, the effect definition and the acceptance rule. Its sha256 is what the
        approval record binds.
run     (1) writes DIR/manifest.json BEFORE any computation (if DIR already has one, the regenerated
        manifest must equal it byte for byte, or the run is refused: exit 2); (2) DIR/run.json, the
        hashes of the bank inputs; (3) validates the bank against the registration (refused, exit 2,
        if it is not the registered bank); (4) runs every scheduled task (DIR/tasks/NNNNN.json, one
        file per task, so an interrupted run resumes; results do not depend on the worker count);
        (5) writes DIR/decision.json (machine-readable) and DIR/gate.md. Exit 0 = pass, 1 = fail.
seeds   the confirmation assay seed manifest of section 2 (namespace confirm-v1, the indexed
        allocation, 5,760 trajectories) and the home seeds 430001-430012, checked for disjointness
        from every seed of the archived plans (--avoid) and the archived home seeds; exit 2 on a
        collision.

The worlds (N = 12 items per group, k = 10, G = 2 groups, C = 2 assays; preregistration section 4):
  L        each bank block's own fitted logistic means and own cell variances, independent endpoints
           from the registered bounded marginal law (calibrate.marginal)          level: H1b, claim
  E        the bank's centred, variance-restored units, k per column WITH replacement, assays jointly,
           regimes independently (calibrate.draw_bank_dataset 'bank')               level: H1
  G        Gaussian units with each column's joint cross-assay bank covariance ('bank-gauss') level: H1
  J0, J8   L's marginals through a Gaussian copula with column factors, latent cross-assay
           correlation 0 / 0.8 (calibrate.joint_column)                           level: H1b, claim
  R05-D, R05-C, R01-D, R01-C   J8 plus shared rare events (pi 0.05 / 0.01; distributed /
           concentrated; calibrate.JOINT_WORLDS)                                  level: H1b, claim
Counts: 10,000 null datasets in each of the nine worlds; 2,000 alternatives in each of the seven
bounded worlds (achieved d_res = 0.01 in all four conditions); diagnostics in L: 2,000 for each of
the four single-condition d_res = 0.02 placements and each of the four single-condition localized
triangles (nominal reciprocal edge amplitude 0.01); 100 outer resamples of the bank x 1,000 inner
H1 null datasets (world E). 104,000 gate datasets + 116,000 diagnostic datasets.

Acceptance (pass only if all hold):
  1. every applicable null decision's two-sided 95% Clopper-Pearson upper bound <= 2a = 0.0083333
     (a = 0.05/12), counting an unavailable decision as a REJECTION (the gate screen);
  2. in every bounded world, the conjunction's two-sided 95% Clopper-Pearson lower bound >= 0.80 at
     the achieved four-condition target, counting an unavailable decision as a FAILURE;
  3. validity: every source fit converged, every cell's law valid (exact moments), the target plant
     solved in all four conditions with converged noiseless refits, every scheduled gate dataset
     computed, and zero unavailable gate datasets.
The 2a ceiling is a screening tolerance: it does not certify nominal a-level control. Diagnostics
(placements, triangles, outer resamples, raw procedure rates) are reported, not gating.
A run with --counts or --bank-spec, or a bank that is not the registered one, is EXPLORATORY: its
decision is computed the same way but marked formal = false, and analyze.py --gate refuses it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing
import os
import platform
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bounded  # noqa: E402
import calibrate  # noqa: E402
import hodge  # noqa: E402
import infer  # noqa: E402

MASTER_SEED = 20271103
ALPHA = 0.05 / 12
CEILING = 2 * ALPHA
POWER_BOUND = 0.80
T_STEPS = 13500
GEOMETRY = {"N": 12, "k": 10, "G": 2, "C": 2}
COUNTS = {"null": 10000, "alt": 2000, "diag": 2000, "outer": 100, "outer_inner": 1000, "chunk": 50}
NULL_WORLDS = ("L", "E", "G", "J0", "J8", "R05-D", "R05-C", "R01-D", "R01-C")
BOUNDED_WORLDS = ("L", "J0", "J8", "R05-D", "R05-C", "R01-D", "R01-C")
LEVEL_TESTS = {w: (("H1",) if w in ("E", "G") else ("H1b", "claim")) for w in NULL_WORLDS}
PLACEMENTS = ((0, 0), (0, 1), (1, 0), (1, 1))
TARGET = 0.01          # the registered effect: achieved d_res in every condition
DIAG_TARGET = 0.02     # single-condition placements (diagnostic)
TRI_EDGE = 0.01        # localized triangle: nominal reciprocal edge amplitude (diagnostic)
TOOLS = ("gate.py", "calibrate.py", "bounded.py", "infer.py", "hodge.py", "analyze.py")
STAT_TOOLS = ("bounded.py", "infer.py", "hodge.py")   # the decision's implementation: analyze.py --gate checks them
PREREG = {"draft": "alife2027/preregistration_draft_codex.md",
          "sha256": "cf1518bc32abe4f003be9ce332e3b76975fe4b6ab173cc303bf207e0dfd5a8f3",
          "approved_utc": "2026-11-04T06:44Z", "approval_record": "alife2027/PREREG_APPROVAL_2026-11-04.md"}
CONFIRM = {"namespace": "confirm-v1", "N": 12, "k": 10, "assays": ["off", "predA4"], "fraction": 0.05,
           "T": T_STEPS, "T2": 2 * T_STEPS, "snapshot_steps": [500000, 3000000],
           "home_seeds": {"off": list(range(430001, 430007)), "predA4": list(range(430007, 430013))},
           "slot_base": 3000000000, "donor_base": 3100000000, "pred_base": 3200000000, "reseed_base": 3300000000}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canon(obj):
    return json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n"


def task_seed(index, world, variant):
    d = hashlib.sha256(f"finfolk-gate/{MASTER_SEED}/{index}/{world}/{variant}".encode()).digest()
    return int.from_bytes(d[:8], "big") >> 1


def outer_seed(o):
    d = hashlib.sha256(f"finfolk-gate/{MASTER_SEED}/outer/{o}".encode()).digest()
    return int.from_bytes(d[:8], "big") >> 1


def schedule(counts):
    """The ordered task list: (index, world, variant, datasets, seed, outer)."""
    out = []
    ch = counts["chunk"]

    def add(world, variant, total, outer=-1):
        for c0 in range(0, total, ch):
            i = len(out)
            out.append([i, world, variant, min(ch, total - c0), task_seed(i, world, variant), outer])
    for w in NULL_WORLDS:
        add(w, "null", counts["null"])
    for w in BOUNDED_WORLDS:
        add(w, "target", counts["alt"])
    for g, c in PLACEMENTS:
        add("L", f"place-g{g}c{c}", counts["diag"])
    for g, c in PLACEMENTS:
        add("L", f"tri-g{g}c{c}", counts["diag"])
    for o in range(counts["outer"]):
        add("E", f"outer{o}", counts["outer_inner"], o)
    return out


def protocol(counts=None, spec=None):
    """The frozen protocol (everything but the tool hashes and the schedule): what analyze.py --gate
    compares a gate record against."""
    counts = dict(COUNTS, **(counts or {}))
    spec = dict(calibrate.BANK_SPEC, **(spec or {}))
    gate_n = 9 * counts["null"] + 7 * counts["alt"]
    diag_n = 8 * counts["diag"] + counts["outer"] * counts["outer_inner"]
    return {
        "schema": "finfolk.invasion.gate-protocol/1",
        "preregistration": PREREG,
        "master_seed": MASTER_SEED,
        "seed_rule": ("task seed = the first 8 bytes (big-endian) of SHA-256('finfolk-gate/<master seed>/<task index>/"
                      "<world>/<variant>') >> 1; outer resample o: SHA-256('finfolk-gate/<master seed>/outer/<o>'); "
                      "one random.Random per task; a task's result depends on its seed and the inputs only"),
        "geometry": GEOMETRY, "T": T_STEPS,
        "alpha": ALPHA, "level_ceiling": CEILING, "power_bound": POWER_BOUND,
        "interval": "two-sided 95% Clopper-Pearson (hodge.clopper_pearson)",
        "tests": {"H1": "raw grouped sign-flip omnibus (infer.signflip_groups: replicates flipped jointly over a "
                        "group's assays, independently across groups; exact over 2^9 x 2^9 = 262,144 patterns)",
                  "H1b": "bounded.residual_omnibus: four separate logistic mean fits, projected residual replicate "
                         "vectors, the same grouped sign-flip; unavailable on an unconverged / non-finite fit or a "
                         "failed projection",
                  "claim": "the fixed conjunction max(p_H1, p_H1b) <= a (twelve fixed slots, two active)"},
        "worlds": {"L": "bank blocks' own fitted logistic means and own cell variances; independent endpoints "
                        "(calibrate.marginal / draw_marginal)",
                   "E": "centred, variance-restored bank units, k per column with replacement, assays joint, "
                        "regimes independent (calibrate.draw_bank_dataset 'bank')",
                   "G": "Gaussian units with each column's joint cross-assay bank covariance ('bank-gauss')",
                   **{w: dict(v, construction="L marginals, Gaussian copula with column factors "
                                              "(calibrate.joint_column)") for w, v in calibrate.JOINT_WORLDS.items()}},
        "level_tests": {w: list(v) for w, v in LEVEL_TESTS.items()},
        "bounded_worlds": list(BOUNDED_WORLDS),
        "marginal": {"zero_mass": f"p0 = min({calibrate.ZIB_PZ}, v / (2 (v + mu^2))) for 0 < mu < "
                                  f"{calibrate.ZIB_LOSING}, else 0",
                     "rest": "Beta with both moments matched exactly; a point mass at v = 0; Bernoulli at v = mu(1 - mu)",
                     "invalid": "v < 0 or v > mu (1 - mu): the world is not built (gate failure); no clipping",
                     "variance": "v = each cell's bank sample variance (K - 1 denominator) of the endpoint q",
                     "alternatives": "v / (mu (1 - mu)) held fixed as the mean changes",
                     "quantile": f"tabulated exact Beta quantile, interpolation error <= {calibrate.QTABLE_TOL} in "
                                 f"logit(x) at every interval midpoint; |logit u| > {calibrate.QTABLE_S} solved exactly"},
        "plant": {"templates": "infer.cycle_template(N, 'diffuse', seed = 5 + group)", "scale": "probability",
                  "clip": list(calibrate.PLANT_CLIP), "grid": f"0, 1/{calibrate.PLANT_GRID}, ..., 1 (first crossing)",
                  "bisection_tol_relative": calibrate.PLANT_TOL, "null_means": "exact (never clipped)",
                  "noiseless_refit": "bounded.fit logistic, warm-started from the previous evaluation; must converge"},
        "effect": {"definition": "d_res = ||Q A (M_c - logistic refit of M_c)|| / sqrt(66), separately in every "
                                 "condition (post-refit residual RMS; approved 2026-11-04)",
                   "target": TARGET, "tolerance": f"{calibrate.PLANT_TOL} relative", "diag_target": DIAG_TARGET,
                   "triangle_edge": TRI_EDGE},
        "counts": counts, "gate_datasets": gate_n, "diagnostic_datasets": diag_n,
        "acceptance": [
            {"criterion": "level", "rule": "for every null world w and every test in level_tests[w]: CP upper "
                                           "bound of (rejections + unavailable) / n <= level_ceiling"},
            {"criterion": "power", "rule": "for every bounded world: CP lower bound of conjunction rejections / n "
                                           "(unavailable = failure) at the 'target' alternative >= power_bound"},
            {"criterion": "validity", "rule": "source fits converged; every cell law valid; target plant solved in "
                                              "all four conditions; every gate task done; zero unavailable gate "
                                              "datasets"},
        ],
        "screening_note": "the 2a ceiling is a screening tolerance; it does not certify nominal a-level control",
        "fitting": bounded.FIT_FREEZE,
        "bank": spec,
    }


def manifest(counts=None, spec=None):
    sched = schedule(dict(COUNTS, **(counts or {})))
    return {"schema": "finfolk.invasion.gate-manifest/1",
            "protocol": protocol(counts, spec),
            "formal": not counts and not spec,
            "tools": {f: sha256_file(os.path.join(HERE, f)) for f in TOOLS},
            "python": platform.python_version(),
            "schedule_columns": ["index", "world", "variant", "datasets", "seed", "outer"],
            "schedule": sched,
            "schedule_sha256": hashlib.sha256(canon(sched).encode()).hexdigest(),
            "tasks": len(sched)}


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ------------------------------------------------------------------- the worker side
W = {}


def _init(cfg):
    try:
        os.nice(19 - os.nice(0))
    except OSError:
        pass
    W.clear()
    W.update(cfg)


def _bounded_state():
    """Per worker, once: the four source fits, the null laws, validity."""
    if "state" in W:
        return W["state"]
    zq = W["bank_zq"]
    Gn, C = len(zq), len(zq[0])
    N = len(zq[0][0])
    st = {"N": N, "G": Gn, "C": C, "fits": {}, "base": {}, "var": {}, "laws": {}, "problems": [], "fit_info": {}}
    for g in range(Gn):
        for c in range(C):
            f = bounded.fit_matrix(zq[g][c])
            st["fit_info"][f"{g}/{c}"] = {"converged": bool(f["converged"]), "reason": f.get("reason"),
                                          "grad": f.get("grad"), "stationarity": f.get("stationarity"), "sse": f["sse"]}
            if not f["converged"]:
                st["problems"].append(f"source fit {g}/{c} not converged ({f.get('reason')})")
            st["base"][(g, c)] = calibrate._ladder(f["params"], list(range(N)), N)
            sd = calibrate.cell_sds(zq[g][c])
            v = [[sd[p][i] ** 2 if i != p else 0.0 for i in range(N)] for p in range(N)]
            st["var"][(g, c)] = v
            mean0 = st["base"][(g, c)][1]
            laws = [[(calibrate.marginal(mean0[p][i], v[p][i]) if i != p else None) for i in range(N)] for p in range(N)]
            bad = [(p, i) for p in range(N) for i in range(N) if i != p and not laws[p][i]["valid"]]
            for p, i in bad[:3]:
                st["problems"].append(f"law {g}/{c} cell ({i} into {p}): {laws[p][i]['reason']}")
            if len(bad) > 3:
                st["problems"].append(f"law {g}/{c}: {len(bad)} invalid cells in all")
            st["laws"][("null", g, c)] = laws
    st["built"] = not st["problems"]
    W["state"] = st
    return st


def _variant(variant):
    """{(g, c): plant info} for the planted conditions of a variant, and the laws of every condition;
    cached per worker. -> (laws {(g, c): laws}, plants {(g, c): info}, problems)."""
    cache = W.setdefault("variants", {})
    if variant in cache:
        return cache[variant]
    st = _bounded_state()
    N, Gn, C = st["N"], st["G"], st["C"]
    tmpl = [infer.cycle_template(N, "diffuse", seed=5 + g) for g in range(Gn)]
    tri = infer.cycle_template(N, "triangle")
    P = N * (N - 1) // 2
    if variant == "null":
        where = {}
    elif variant == "target":
        where = {(g, c): ("target", TARGET) for g in range(Gn) for c in range(C)}
    elif variant.startswith("place-"):
        where = {(int(variant[7]), int(variant[9])): ("target", DIAG_TARGET)}
    elif variant.startswith("tri-"):
        where = {(int(variant[5]), int(variant[7])): ("triangle", TRI_EDGE)}
    else:
        raise ValueError(variant)
    laws, plants, probs = {}, {}, []
    for g in range(Gn):
        for c in range(C):
            if (g, c) not in where:
                laws[(g, c)] = st["laws"][("null", g, c)]
                continue
            eta, mean0, th0 = st["base"][(g, c)]
            fam, d = where[(g, c)]
            if fam == "target":
                x = calibrate.feasible_plant(eta, mean0, th0, tmpl[g], d)
            else:
                mean, ncl, tot, mx = calibrate.nominal_plant(mean0, tri, d * math.sqrt(3.0 / P))
                d_add, d_res, ok, _ = calibrate.plant_diagnostics(mean, mean0, th0)
                x = {"mean": mean, "c": d * math.sqrt(3.0 / P), "d_add": d_add, "d_res": d_res, "converged": ok,
                     "solved": ok, "evals": 1, "clipped": ncl, "clip_sum": tot, "clip_max": mx, "grid_m": None,
                     "d_res_clip0": None}
            info = {k_: x.get(k_) for k_ in ("c", "d_add", "d_res", "converged", "solved", "evals", "clipped",
                                             "clip_sum", "clip_max", "grid_m", "d_res_clip0")}
            plants[f"{g}/{c}"] = info
            if not x["solved"]:
                probs.append(f"plant {variant} {g}/{c} not solved (d_res {x['d_res']:.6g}, converged {x['converged']})")
            v = st["var"][(g, c)]
            lw = [[(calibrate.marginal_alt(mean0[p][i], v[p][i], x["mean"][p][i]) if i != p else None)
                   for i in range(N)] for p in range(N)]
            nb = sum(1 for p in range(N) for i in range(N) if i != p and not lw[p][i]["valid"])
            if nb:
                probs.append(f"plant {variant} {g}/{c}: {nb} invalid alternative laws")
            laws[(g, c)] = lw
    cache[variant] = (laws, plants, probs)
    return cache[variant]


def _draw_bounded(world, laws, st, rnd):
    N, Gn, C, k = st["N"], st["G"], st["C"], W["k"]
    groups = []
    if world == "L":
        for g in range(Gn):
            groups.append([[[[calibrate.draw_marginal(rnd, laws[(g, c)][p][i]) if i != p else 0.0 for i in range(N)]
                             for _ in range(k)] for p in range(N)] for c in range(C)])
        return groups
    jw = calibrate.JOINT_WORLDS[world]
    for g in range(Gn):
        zs = [[[None] * k for _ in range(N)] for _ in range(C)]
        for p in range(N):
            margs = [laws[(g, c)][p] for c in range(C)]
            for r in range(k):
                q = calibrate.joint_column(rnd, margs, p, jw["kappa"], jw["rare"])
                for c in range(C):
                    zs[c][p][r] = q[c]
        groups.append(zs)
    return groups


def _bank_state(outer):
    key = ("bank", outer)
    if key not in W:
        if len([k_ for k_ in W if isinstance(k_, tuple) and k_[0] == "bank"]) > 4:
            for k_ in [k_ for k_ in W if isinstance(k_, tuple) and k_[0] == "bank"]:
                del W[k_]
        g0 = calibrate._bank_groups(W["bank_z"], None if outer < 0 else outer_seed(outer))
        W[key] = (g0, [calibrate._bank_cov(rg) for rg in g0])
    return W[key]


def run_task(t):
    idx, world, variant, n, seed, outer = t
    t0 = time.time()
    rnd = random.Random(seed)
    res = {"index": idx, "world": world, "variant": variant, "n": n, "seed": seed, "outer": outer,
           "rej": {"H1": 0, "H1b": 0, "claim": 0}, "rej05": {"H1": 0, "H1b": 0, "claim": 0},
           "unavailable": {"H1": 0, "H1b": 0, "claim": 0}, "why": {}, "plants": None, "built": True, "problems": []}

    def count(dec, tests):
        for t_, p_ in (("H1", dec["p1"]), ("H1b", dec["p1b"]), ("claim", dec["conj"])):
            if t_ not in tests:
                continue
            if p_ is None:
                res["unavailable"][t_] += 1
            else:
                res["rej"][t_] += p_ <= ALPHA + 1e-15
                res["rej05"][t_] += p_ <= 0.05 + 1e-15
        if dec.get("why"):
            w_ = str(dec["why"])[:160]
            res["why"][w_] = res["why"].get(w_, 0) + 1
    if world in ("E", "G"):
        g0, covs = _bank_state(outer)
        for _ in range(n):
            groups = calibrate.draw_bank_dataset("bank" if world == "E" else "bank-gauss", g0, covs, W["k"], rnd)
            count(calibrate.decide(groups, h1b=False), ("H1",))
    else:
        st = _bounded_state()
        laws, plants, probs = _variant(variant)
        res["plants"] = plants
        res["problems"] = st["problems"] + probs
        res["built"] = st["built"] and not probs
        if not res["built"]:   # not built as registered: every dataset is unavailable (counted, never tested)
            for t_ in ("H1", "H1b", "claim"):
                res["unavailable"][t_] = n
            res["why"]["world not built as registered"] = n
        else:
            for _ in range(n):
                count(calibrate.decide(_draw_bounded(world, laws, st, rnd)), ("H1", "H1b", "claim"))
        res["fit_info"] = st["fit_info"]
    res["seconds"] = time.time() - t0
    return res


# ------------------------------------------------------------------- the parent side
def load_bank(a, spec):
    """-> (bank_z, bank_zq, info, problems)."""
    bb = json.load(open(a.bank))
    plan_cells = [json.loads(ln) for ln in open(a.bank_plan) if ln.strip()]
    inp = a.bank_inputs or os.path.join(os.path.dirname(os.path.abspath(a.bank)), "inputs.json")
    inputs = json.load(open(inp)) if os.path.exists(inp) else None
    gnames, cnames, byk, probs = calibrate.validate_bank(bb, spec, plan_cells, sha256_file(a.bank_plan), inputs)
    bank_z, bank_zq = [], []
    for g_ in gnames:
        bs = [byk.get((g_, c_)) for c_ in spec["assays"]]
        if any(b is None for b in bs):
            continue
        bank_z.append([b["z"] for b in bs])
        bank_zq.append([b["zq"] for b in bs])
    info = {"groups": gnames, "assays": spec["assays"],
            "blocks": {"path": os.path.abspath(a.bank), "sha256": sha256_file(a.bank)},
            "plan": {"path": os.path.abspath(a.bank_plan), "sha256": sha256_file(a.bank_plan)},
            "inputs": {"path": os.path.abspath(inp), "sha256": sha256_file(inp)} if inputs is not None else None}
    return bank_z, bank_zq, info, probs


def aggregate(results, sched):
    agg = {}
    for t in sched:
        r = results.get(t[0])
        key = (t[1], t[2])
        a = agg.setdefault(key, {"world": t[1], "variant": t[2], "n": 0, "planned": 0, "tasks": 0, "done": 0,
                                 "rej": {"H1": 0, "H1b": 0, "claim": 0}, "rej05": {"H1": 0, "H1b": 0, "claim": 0},
                                 "unavailable": {"H1": 0, "H1b": 0, "claim": 0}, "why": {}, "plants": None,
                                 "plants_consistent": True, "seconds": 0.0, "problems": []})
        a["planned"] += t[3]
        a["tasks"] += 1
        if r is None:
            continue
        a["done"] += 1
        a["n"] += r["n"]
        a["seconds"] += r["seconds"]
        for f in ("rej", "rej05", "unavailable"):
            for t_, v in r[f].items():
                a[f][t_] += v
        for w_, v in r["why"].items():
            a["why"][w_] = a["why"].get(w_, 0) + v
        if r.get("plants") is not None:
            if a["plants"] is None:
                a["plants"] = r["plants"]
            elif a["plants"] != r["plants"]:
                a["plants_consistent"] = False
        for p_ in r.get("problems", []):
            if p_ not in a["problems"]:
                a["problems"].append(p_)
        if r.get("fit_info") is not None:
            a["fit_info"] = r["fit_info"]
    return agg


def decide_gate(agg, counts, formal, bank_probs):
    crit, reasons = [], []
    for w in NULL_WORLDS:
        a = agg[(w, "null")]
        for t_ in LEVEL_TESTS[w]:
            x = a["rej"][t_] + a["unavailable"][t_]
            n = a["n"]
            lo, hi = hodge.clopper_pearson(x, n) if n else (0.0, 1.0)
            ok = n == a["planned"] and hi <= CEILING
            crit.append({"criterion": "level", "world": w, "test": t_, "x": x, "rejections": a["rej"][t_],
                         "unavailable": a["unavailable"][t_], "n": n, "planned": a["planned"], "rate": x / n if n else None,
                         "cp_lo": lo, "cp_hi": hi, "threshold": CEILING, "ok": ok,
                         "raw_rate": a["rej"][t_] / n if n else None})
            if not ok:
                reasons.append(f"level: {w} {t_}: {x}/{n} (incl. {a['unavailable'][t_]} unavailable), CP upper "
                               f"{hi:.6f} > {CEILING:.6f}" if n == a["planned"] else f"level: {w} {t_}: {n}/{a['planned']} done")
    for w in BOUNDED_WORLDS:
        a = agg[(w, "target")]
        x, n = a["rej"]["claim"], a["n"]
        lo, hi = hodge.clopper_pearson(x, n) if n else (0.0, 1.0)
        ok = n == a["planned"] and lo >= POWER_BOUND
        crit.append({"criterion": "power", "world": w, "test": "claim", "x": x, "unavailable": a["unavailable"]["claim"],
                     "n": n, "planned": a["planned"], "rate": x / n if n else None, "cp_lo": lo, "cp_hi": hi,
                     "threshold": POWER_BOUND, "ok": ok})
        if not ok:
            reasons.append(f"power: {w}: {x}/{n}, CP lower {lo:.4f} < {POWER_BOUND}" if n == a["planned"]
                           else f"power: {w}: {n}/{a['planned']} done")
    # validity
    vprobs = list(bank_probs)
    gate_keys = [(w, "null") for w in NULL_WORLDS] + [(w, "target") for w in BOUNDED_WORLDS]
    for key in gate_keys:
        a = agg[key]
        if a["done"] != a["tasks"] or a["n"] != a["planned"]:
            vprobs.append(f"{key[0]} {key[1]}: {a['n']} of {a['planned']} datasets computed")
        unav = max(a["unavailable"].values())
        if unav:
            vprobs.append(f"{key[0]} {key[1]}: {unav} unavailable dataset(s) ({sorted(a['why'].items(), key=lambda kv: -kv[1])[:2]})")
        for p_ in a["problems"]:
            if p_ not in vprobs:
                vprobs.append(p_)
        if not a["plants_consistent"]:
            vprobs.append(f"{key[0]} {key[1]}: workers built different plants")
    tgt = agg[("L", "target")]["plants"] or {}
    for gc, x in sorted(tgt.items()):
        if not (x["solved"] and abs(x["d_res"] - TARGET) <= calibrate.PLANT_TOL * TARGET):
            vprobs.append(f"target plant {gc}: d_res {x['d_res']:.8g} not within {calibrate.PLANT_TOL} relative of {TARGET}")
    crit.append({"criterion": "validity", "ok": not vprobs, "problems": vprobs})
    reasons += [f"validity: {p_}" for p_ in vprobs]
    return crit, reasons


def diagnostics(agg, counts):
    out = {"placements_and_triangles": [], "outer": None, "raw_procedure_rates": []}
    for g, c in PLACEMENTS:
        for v in (f"place-g{g}c{c}", f"tri-g{g}c{c}"):
            a = agg[("L", v)]
            row = {"variant": v, "n": a["n"], "unavailable": a["unavailable"]["claim"], "plants": a["plants"]}
            for t_ in ("H1", "H1b", "claim"):
                lo, hi = hodge.clopper_pearson(a["rej"][t_], a["n"]) if a["n"] else (0.0, 1.0)
                row[t_] = {"x": a["rej"][t_], "rate": a["rej"][t_] / a["n"] if a["n"] else None, "cp_lo": lo, "cp_hi": hi}
            out["placements_and_triangles"].append(row)
    rates, rates05, n_in = [], [], None
    for o in range(counts["outer"]):
        a = agg[("E", f"outer{o}")]
        if a["n"]:
            rates.append(a["rej"]["H1"] / a["n"])
            rates05.append(a["rej05"]["H1"] / a["n"])
            n_in = a["n"]
    if rates:
        def summ(v):
            m = sum(v) / len(v)
            sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1)) if len(v) > 1 else 0.0
            return {"mean": m, "sd": sd, "min": min(v), "max": max(v)}
        s, s05 = summ(rates), summ(rates05)
        # finite-bank variation beyond the inner binomial noise: var(outer rates) - mean p(1 - p) / n
        excess = s["sd"] ** 2 - s["mean"] * (1 - s["mean"]) / n_in if n_in else None
        out["outer"] = {"resamples": len(rates), "inner": n_in, "H1_level_at_a": s, "H1_level_at_0.05": s05,
                        "inner_binomial_sd_at_a": math.sqrt(s["mean"] * (1 - s["mean"]) / n_in) if n_in else None,
                        "finite_bank_sd_at_a": math.sqrt(max(0.0, excess)) if excess is not None else None,
                        "note": "H1 only; finite-bank variation with inner Monte Carlo noise; not compound-claim "
                                "uncertainty"}
    for (w, v), a in sorted(agg.items()):
        if v.startswith("outer"):
            continue
        out["raw_procedure_rates"].append({"world": w, "variant": v, "n": a["n"],
                                           **{f"{t_}_raw_at_a": (a["rej"][t_] / a["n"] if a["n"] else None)
                                              for t_ in ("H1", "H1b", "claim")},
                                           **{f"{t_}_unavailable": a["unavailable"][t_] for t_ in ("H1", "H1b", "claim")}})
    return out


def timing(agg, sched, counts_full):
    """Core-seconds per dataset by (world, variant family) and the full-count wall-time estimate."""
    per = {}
    for (w, v), a in agg.items():
        fam = "outer" if v.startswith("outer") else ("diag" if v.startswith(("place", "tri")) else v)
        p = per.setdefault((w, fam), [0.0, 0])
        p[0] += a["seconds"]
        p[1] += a["n"]
    rate = {f"{w}/{f}": (s / n if n else None) for (w, f), (s, n) in per.items()}
    full = schedule(counts_full)
    tot = 0.0
    missing = set()
    for t in full:
        fam = "outer" if t[2].startswith("outer") else ("diag" if t[2].startswith(("place", "tri")) else t[2])
        r = rate.get(f"{t[1]}/{fam}")
        if r is None:
            missing.add(f"{t[1]}/{fam}")
            continue
        tot += r * t[3]
    return {"core_seconds_per_dataset": rate, "full_counts_core_hours": tot / 3600,
            "full_counts_wall_hours": {"2 workers": tot / 3600 / 2, "4 workers": tot / 3600 / 4},
            "not_estimated": sorted(missing),
            "note": "excludes per-worker set-up (source fits, plants, quantile tables: ~1-2 min per worker)"}


def report_md(dec):
    md = [f"# Calibration gate: **{dec['decision'].upper()}**" + ("" if dec["formal"] else " (EXPLORATORY: not the "
          "registered gate)") + "\n",
          f"manifest sha256 `{dec['manifest_sha256']}`; run.json sha256 `{dec['run_sha256']}`; a = 0.05/12 = "
          f"{ALPHA:.10f}; level ceiling 2a = {CEILING:.10f} (a screening tolerance, not nominal a-level "
          f"certification); power bound {POWER_BOUND}. Intervals: two-sided 95% Clopper-Pearson.\n"]
    if dec["reasons"]:
        md.append("## Reasons\n")
        md += [f"- {r}" for r in dec["reasons"]]
    md.append("\n## Level (gate screen: unavailable = rejection)\n")
    md.append("| world | test | rejections | unavailable | n | rate | CP upper | ok |\n|---|---|---|---|---|---|---|---|")
    for c in dec["criteria"]:
        if c["criterion"] == "level":
            md.append(f"| {c['world']} | {c['test']} | {c['rejections']} | {c['unavailable']} | {c['n']} | "
                      f"{(c['rate'] or 0):.5f} | {c['cp_hi']:.5f} | {'yes' if c['ok'] else 'NO'} |")
    md.append("\n## Power of the conjunction at d_res = 0.01 in all four conditions (unavailable = failure)\n")
    md.append("| world | rejections | unavailable | n | rate | CP lower | ok |\n|---|---|---|---|---|---|---|")
    for c in dec["criteria"]:
        if c["criterion"] == "power":
            md.append(f"| {c['world']} | {c['x']} | {c['unavailable']} | {c['n']} | {(c['rate'] or 0):.4f} | "
                      f"{c['cp_lo']:.4f} | {'yes' if c['ok'] else 'NO'} |")
    v = [c for c in dec["criteria"] if c["criterion"] == "validity"][0]
    md.append(f"\n## Validity: {'ok' if v['ok'] else 'FAILED'}\n")
    md += [f"- {p_}" for p_ in v["problems"]]
    d = dec["diagnostics"]
    md.append("\n## Diagnostics (not gating)\n")
    md.append("| variant | n | H1 | H1b | claim [CP 95%] | planted (d_res / c / clipped) |\n|---|---|---|---|---|---|")
    for r in d["placements_and_triangles"]:
        pl = "; ".join(f"{gc}: {x['d_res']:.5f} / {x['c']:.5f} / {x['clipped']}" for gc, x in (r["plants"] or {}).items())
        md.append(f"| {r['variant']} | {r['n']} | {(r['H1']['rate'] or 0):.4f} | {(r['H1b']['rate'] or 0):.4f} | "
                  f"{(r['claim']['rate'] or 0):.4f} [{r['claim']['cp_lo']:.4f}, {r['claim']['cp_hi']:.4f}] | {pl} |")
    if d["outer"]:
        o = d["outer"]
        md.append(f"\nOuter bank resamples ({o['resamples']} x {o['inner']}, H1 in world E): level at a mean "
                  f"{o['H1_level_at_a']['mean']:.5f} (SD {o['H1_level_at_a']['sd']:.5f}, range "
                  f"{o['H1_level_at_a']['min']:.4f}-{o['H1_level_at_a']['max']:.4f}; inner binomial SD "
                  f"{o['inner_binomial_sd_at_a']:.5f}); at 0.05 mean {o['H1_level_at_0.05']['mean']:.4f}. "
                  "H1 only: not compound-claim uncertainty.\n")
    tm = dec["timing"]
    md.append(f"\nTiming: full counts ~{tm['full_counts_core_hours']:.2f} core-hours = "
              f"{tm['full_counts_wall_hours']['2 workers']:.2f} h on 2 workers, "
              f"{tm['full_counts_wall_hours']['4 workers']:.2f} h on 4 (from this run's per-dataset times).\n")
    return md


def cmd_freeze(a):
    counts = json.load(open(a.counts)) if a.counts else None
    spec = json.load(open(a.bank_spec)) if a.bank_spec else None
    os.makedirs(a.out, exist_ok=True)
    text = canon(manifest(counts, spec))
    path = os.path.join(a.out, "manifest.json")
    if os.path.exists(path) and open(path).read() != text:
        print(f"{path} exists and differs from this freeze: refused", file=sys.stderr)
        return 2
    write_atomic(path, text)
    print(f"manifest {path} sha256 {hashlib.sha256(text.encode()).hexdigest()}")
    return 0


def cmd_run(a):
    if not 1 <= a.workers <= 4:
        print("--workers must be 1..4 (the paper-experiment core budget)", file=sys.stderr)
        return 2
    counts = json.load(open(a.counts)) if a.counts else None
    spec_over = json.load(open(a.bank_spec)) if a.bank_spec else None
    os.makedirs(os.path.join(a.out, "tasks"), exist_ok=True)
    man = manifest(counts, spec_over)
    text = canon(man)
    mpath = os.path.join(a.out, "manifest.json")
    if os.path.exists(mpath):
        old = open(mpath).read()
        if old != text:
            try:
                o = json.loads(old)
                diff = sorted(k_ for k_ in set(o) | set(man) if o.get(k_) != json.loads(text).get(k_))
            except ValueError:
                diff = ["(unreadable)"]
            print(f"{mpath} differs from the regenerated manifest (keys {diff}): refused", file=sys.stderr)
            return 2
    else:
        write_atomic(mpath, text)   # BEFORE any computation
    man_sha = hashlib.sha256(text.encode()).hexdigest()
    counts_all = man["protocol"]["counts"]
    spec = man["protocol"]["bank"]
    # (2) the inputs' hashes, (3) the bank's validation
    bank_z, bank_zq, info, bprobs = load_bank(a, spec)
    run = {"schema": "finfolk.invasion.gate-run/1", "manifest_sha256": man_sha, "bank": info,
           "python": platform.python_version(), "platform": platform.platform()}
    rpath = os.path.join(a.out, "run.json")
    rtext = canon(run)
    if os.path.exists(rpath) and open(rpath).read() != rtext:
        print(f"{rpath} differs (other bank inputs than the interrupted run): refused", file=sys.stderr)
        return 2
    write_atomic(rpath, rtext)
    run_sha = hashlib.sha256(rtext.encode()).hexdigest()
    geo = man["protocol"]["geometry"]
    shape_ok = (len(bank_zq) == geo["G"] and all(len(x) == geo["C"] for x in bank_zq)
                and all(len(z) == geo["N"] for x in bank_zq for z in x))
    if bprobs or not shape_ok:
        msg = bprobs + ([] if shape_ok else [f"bank geometry is not N:G:C = {geo['N']}:{geo['G']}:{geo['C']}"])
        if man["formal"]:
            dec = {"schema": "finfolk.invasion.gate-decision/1", "decision": "refused", "formal": False,
                   "reasons": [f"bank: {p_}" for p_ in msg], "manifest_sha256": man_sha, "run_sha256": run_sha}
            write_atomic(os.path.join(a.out, "decision.json"), canon(dec))
            print("REFUSED: the bank is not the registered bank:\n  " + "\n  ".join(msg), file=sys.stderr)
            return 2
        if not shape_ok:
            print("REFUSED: " + msg[-1], file=sys.stderr)
            return 2
        print("EXPLORATORY bank: " + "; ".join(msg), file=sys.stderr)
    sched = man["schedule"]
    results = {}
    tdir = os.path.join(a.out, "tasks")
    for t in sched:
        p_ = os.path.join(tdir, f"{t[0]:05d}.json")
        if os.path.exists(p_):
            try:
                r = json.load(open(p_))
            except ValueError:
                continue
            if [r.get("index"), r.get("world"), r.get("variant"), r.get("n"), r.get("seed"), r.get("outer")] == t \
                    and r.get("manifest_sha256") == man_sha:
                results[t[0]] = r
    todo = [tuple(t) for t in sched if t[0] not in results]
    print(f"gate: {len(sched)} tasks, {len(results)} already done, {len(todo)} to run on {a.workers} worker(s)", flush=True)
    t0 = time.time()
    cfg = {"bank_z": bank_z, "bank_zq": bank_zq, "k": geo["k"]}
    if todo:
        with multiprocessing.Pool(a.workers, initializer=_init, initargs=(cfg,)) as pool:
            for done, r in enumerate(pool.imap_unordered(run_task, todo), 1):
                r["manifest_sha256"] = man_sha
                write_atomic(os.path.join(tdir, f"{r['index']:05d}.json"), json.dumps(r, sort_keys=True) + "\n")
                results[r["index"]] = r
                if done % 20 == 0 or done == len(todo):
                    el = time.time() - t0
                    print(f"{done}/{len(todo)} tasks, {el / 60:.1f} min, ETA {el / done * (len(todo) - done) / 60:.1f} min",
                          flush=True)
    agg = aggregate(results, sched)
    formal = man["formal"] and not bprobs
    crit, reasons = decide_gate(agg, counts_all, formal, bprobs)
    dec = {"schema": "finfolk.invasion.gate-decision/1",
           "decision": "pass" if not reasons else "fail",
           "formal": formal,
           "exploratory_because": ([] if man["formal"] else ["counts or bank spec overridden"]) + bprobs,
           "reasons": reasons, "criteria": crit,
           "manifest_sha256": man_sha, "run_sha256": run_sha, "tools": man["tools"],
           "protocol_sha256": hashlib.sha256(canon(man["protocol"]).encode()).hexdigest(),
           "source_fits": next((a_.get("fit_info") for a_ in agg.values() if a_.get("fit_info")), None),
           "target_plants": agg[("L", "target")]["plants"],
           "diagnostics": diagnostics(agg, counts_all),
           "timing": timing(agg, sched, COUNTS),
           "wall_seconds_this_session": time.time() - t0,
           "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    write_atomic(os.path.join(a.out, "decision.json"), canon(dec))
    md = report_md(dec)
    write_atomic(os.path.join(a.out, "gate.md"), "\n".join(md) + "\n")
    print("\n".join(md))
    return 0 if dec["decision"] == "pass" else 1


# ------------------------------------------------------------------- confirmation seeds (section 2)
def confirm_seeds():
    """The indexed allocation of section 2: u = 10 (12 h + j) + r; slot 3.0e9 + u; donor 3.1e9 + 12 u + i
    (i = j for the sham); predator 3.2e9 + u (predator-on only); engine reseed 3.3e9 + 2 u + a."""
    C = CONFIRM
    cells = []
    for h in range(2):
        for a_, assay in enumerate(C["assays"]):
            for j in range(C["N"]):
                for i in range(C["N"]):
                    for r in range(C["k"]):
                        u = C["k"] * (C["N"] * h + j) + r
                        cells.append({"h": h, "assay": assay, "j": j, "i": i, "r": r, "mode": "sham" if i == j else "invade",
                                      "slot_seed": C["slot_base"] + u, "donor_seed": C["donor_base"] + C["N"] * u + i,
                                      "pred_seed": C["pred_base"] + u if a_ == 1 else None,
                                      "reseed": C["reseed_base"] + len(C["assays"]) * u + a_})
    return cells


def cmd_seeds(a):
    cells = confirm_seeds()
    keys = ("slot_seed", "donor_seed", "pred_seed", "reseed")
    used = set()
    for p_ in a.avoid:
        for ln in open(p_):
            if ln.strip():
                c = json.loads(ln)
                used |= {c[k_] for k_ in keys if c.get(k_) is not None}
    homes_used = {int(x) for x in a.home_seeds_used.split(",") if x.strip()} if a.home_seeds_used else set()
    mine = {c[k_] for c in cells for k_ in keys if c[k_] is not None}
    homes = [s for v in CONFIRM["home_seeds"].values() for s in v]
    hit = sorted(mine & used)
    hit_h = sorted(set(homes) & (homes_used | used))
    out = {"schema": "finfolk.invasion.confirm-seeds/1", "protocol": CONFIRM,
           "trajectories": len(cells), "invasions": sum(c["mode"] == "invade" for c in cells),
           "shams": sum(c["mode"] == "sham" for c in cells),
           "plan_py_seed_scheme": {"type": "indexed", "namespace": CONFIRM["namespace"], "slot_base": CONFIRM["slot_base"],
                                   "donor_base": CONFIRM["donor_base"], "pred_base": CONFIRM["pred_base"],
                                   "reseed_base": CONFIRM["reseed_base"], "assays": CONFIRM["assays"]},
           "avoid": [{"path": os.path.abspath(p_), "sha256": sha256_file(p_)} for p_ in a.avoid],
           "home_seeds_used": sorted(homes_used), "collisions": hit, "home_collisions": hit_h,
           "distinct_seeds": len(mine), "seed_values_sha256": hashlib.sha256(canon(sorted(mine)).encode()).hexdigest(),
           "cells": cells}
    write_atomic(a.out, canon(out))
    print(f"{len(cells)} trajectories ({out['invasions']} invasions + {out['shams']} shams), {len(mine)} distinct seeds; "
          f"checked against {len(a.avoid)} archived plan(s) and {len(homes_used)} archived home seed(s): "
          f"{len(hit)} assay / {len(hit_h)} home collision(s)")
    return 2 if hit or hit_h else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--out", required=True)
    f.add_argument("--counts")
    f.add_argument("--bank-spec")
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--bank", required=True, help="the bank analysis' blocks.json (analyze.py export)")
    r.add_argument("--bank-plan", required=True, help="the bank's registered plan (JSONL)")
    r.add_argument("--bank-inputs", help="the bank analysis' inputs.json (default: beside --bank)")
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--counts", help="EXPLORATORY: JSON overriding counts (null, alt, diag, outer, outer_inner, chunk)")
    r.add_argument("--bank-spec", help="EXPLORATORY: JSON overriding the registered bank specification")
    s = sub.add_parser("seeds")
    s.add_argument("--out", required=True)
    s.add_argument("--avoid", action="append", default=[])
    s.add_argument("--home-seeds-used", default="")
    a = ap.parse_args(argv)
    return {"freeze": cmd_freeze, "run": cmd_run, "seeds": cmd_seeds}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())

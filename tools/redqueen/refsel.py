#!/usr/bin/env python3
"""refsel.py: reference selection by information content (design v4 §4.2): the candidate-grid plan, the
collection of its results, and the deterministic greedy / swap selection of EIGHT references per guild
on the registered information criterion, written as config/references.json (finfolk.redqueen.references/1,
the format sealing.py consumes). The criterion and the constraints are FROZEN in the plan (their sha256)
before any candidate outcome exists; main-world performance never enters (only the sentinel grid).

CANDIDATES. The four predetermined sentinels (default w01, w04, w05, w06 of the validation registry)
at F1, 20, 60, 100, 120, 140, 180, 200M, where the snapshot is archived and valid (before the world's
first zero): the same (sentinel, time) set for both guilds (a candidate prey reference is the
sentinel's prey snapshot, a candidate predator reference its predators). Four usable sentinels: 32 per
guild. Every sentinel's registry uuid must be uuid5(URL, "finfolk:redqueen:<sentinel namespace>:<id>")
(the references' identity recipe).

PLAN (`plan`): a design/2 for plan.py: every prey candidate against every predator candidate (family
refgrid) plus each prey candidate's predator-free control (refgrid-free), the production assay (frozen,
K 6, 600 common prey, 5k, the production age reference: mandatory), R = 6, role diagnostic, its own seed
namespace; every engine seed checked against every --avoid input (mandatory). 32 x 32 x 6 = 6,144 grid
trajectories (+ 192 controls).

COLLECT (`collect`): the packed cells through store.py's verified index, bound to the FINAL plan (every
bundle carries its plan row exactly; the 600 cohort; every cell collected or declared missing).

THE CRITERION (registered; CRITERION below, frozen in the plan). Per cell and replicate: the capture
logit l = logit((C + 1/2) / (B + 1)), B = the registered capture bound (324: K 6, the 1.5 s cooldown,
5k), and the survival contrast q = (S_exposed - S_free) / 600 (the same replicate's common prey). Per
readout X in {l, q}: the replicate means X (prey x predator candidates), double-centred (the map's
intercepts removed), its SVD U S V'; a predator candidate's rank-r embedding v_j = V_j,1..r S_1..r^(1/2)
(a prey candidate's u_i likewise). A predator-reference SET places a prey population from its responses:
its noise-weighted information for rank r is I_r = sum_{j in set} w_j [1, v_j][1, v_j]' (w_j = 1 / the
mean over prey candidates of the cell's variance of the mean: the replicate variance / R, floored at the
binomial count variance / R: 1 / (B p (1 - p)) for the capture logit at p = (C + 1/2) / (B + 1), and
(S (1 - S) + S0 (1 - S0)) / 600 for the survival contrast; a saturated cell's replicates barely vary
but it carries little information); likewise a prey-reference set for predators. The
objective of a set: sum over readouts and ranks 1..4 of log lambda_min(I_r + eps_r I) (the worst-placed
direction; eps_r = 1e-9 tr(I_r over all candidates) / ((r + 1) n): a fixed floor for partial sets) minus
the SATURATION PENALTY 2.0 x the sum over the set of each candidate's saturated share (the share of its
cells whose mean capture fraction C/B or exposed survival lies outside [0.02, 0.98], averaged over the
two readouts); a candidate whose saturated share exceeds 0.5 is not eligible at all (a mostly saturated
reference places nothing, and double-centring would give its flat responses a spurious embedding).
CONSTRAINTS (each guild): eight references; at least three distinct sentinels; at least four at times
<= 120M; at least two at times >= 140M.
PROCEDURE: greedy (add the best candidate whose addition keeps a constraint-satisfying completion
possible: an exact search over the (sentinel, early/late) attribute counts), then swaps (the best
improving exchange of a selected and an unselected candidate keeping the constraints, until none
improves; at most 200); every tie (relative 1e-12) broken by the order of
sha256("<criterion namespace>|refsel|<guild>|<world>|<frame>"). Slots: the selected references sorted by
(frame, that hash): RQ:0..7 (prey references), RP:0..7 (predator references).

    refsel.py plan --block worlds_block.json --sentinel-namespace NS --templates /abs/t.json ... \\
        --age-reference /abs/ages.json --avoid PRODUCTION/config/worlds.json [--avoid ...] --out grid.json
    refsel.py collect --study GRID_STUDY --design grid.json --plan FINAL_PLAN.jsonl --out obs.json
    refsel.py select obs.json --design grid.json --plan FINAL_PLAN.jsonl --out config/references.json \\
        --report refsel_report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
import plan as planlib  # noqa: E402
import rqlib  # noqa: E402

SCHEMA = "finfolk.redqueen.refsel/1"
REFS_SCHEMA = "finfolk.redqueen.references/1"
OBS_SCHEMA = "finfolk.redqueen.refsel.obs/1"
SEED_NAMESPACE = "rq2026-refgrid"
SENTINELS = ("w01", "w04", "w05", "w06")
TIMES = ("F1", "20M", "60M", "100M", "120M", "140M", "180M", "200M")
REPLICATES = 6
HORIZON = 5000
N_PREY = 600
K = 6
CRITERION = {
    "version": 1, "n_ref": 8, "min_sentinels": 3, "early_max_M": 120, "min_early": 4, "late_min_M": 140,
    "min_late": 2, "ranks": [1, 2, 3, 4], "readouts": ["capture_logit", "survival_contrast"],
    "capture_bound": 324, "saturation": [0.02, 0.98], "saturation_penalty": 2.0, "eps": 1e-9,
    "variance_floor": "binomial", "max_saturated_share": 0.5,
    "tie_namespace": "rq2026-refsel", "max_swaps": 200, "replicates": REPLICATES, "horizon": HORIZON,
}


class RefselError(Exception):
    pass


def frame_of(label):
    return 1 if label == "F1" else int(label[:-1]) * 1_000_000


def time_m(label):
    return frame_of(label) / 1e6


def tie_key(guild, world, frame, crit=CRITERION):
    return hashlib.sha256(f"{crit['tie_namespace']}|refsel|{guild}|{world}|{frame}".encode()).hexdigest()


# ================================================================== seeds (as rho_pilot.py)
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


# ================================================================== the plan
def candidates(block, sentinels, sentinel_ns):
    """The usable (sentinel, time) candidates, the same for both guilds."""
    ws = block["worlds"]
    out = []
    for w in sentinels:
        if w not in ws:
            raise RefselError(f"sentinel {w} is not in the worlds block")
        v = ws[w]
        want = str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:redqueen:{sentinel_ns}:{w}"))
        if v.get("uuid") != want:
            raise RefselError(f"sentinel {w}: its uuid is not the references' recipe in namespace {sentinel_ns} "
                              "(a restarted attempt or another registry)")
        for lab in TIMES:
            fr = frame_of(lab)
            if block["times"].get(lab) != fr:
                raise RefselError(f"the worlds block has no time {lab} = frame {fr}")
            ok = fr in v.get("archived", []) and (v.get("valid_before") is None or fr < v["valid_before"])
            if ok:
                out.append((w, lab))
    return out


def feasible(chosen, pool, crit=CRITERION):
    """Can `chosen` (a list of (world, label)) be completed from `pool` (the unchosen candidates) to a
    set meeting every constraint? Exact: a search over the counts of the (sentinel, early / late / other)
    attribute types."""
    need = crit["n_ref"] - len(chosen)
    if need < 0:
        return False

    def cls(lab):
        t = time_m(lab)
        return "E" if t <= crit["early_max_M"] else "L" if t >= crit["late_min_M"] else "O"
    avail = {}
    for w, lab in pool:
        avail[(w, cls(lab))] = avail.get((w, cls(lab)), 0) + 1
    types = sorted(avail)
    have_s = {w for w, _ in chosen}
    have_e = sum(1 for _, lab in chosen if cls(lab) == "E")
    have_l = sum(1 for _, lab in chosen if cls(lab) == "L")

    def ok(counts):
        s = have_s | {types[i][0] for i, c in enumerate(counts) if c}
        e = have_e + sum(c for i, c in enumerate(counts) if types[i][1] == "E")
        lt = have_l + sum(c for i, c in enumerate(counts) if types[i][1] == "L")
        return len(s) >= crit["min_sentinels"] and e >= crit["min_early"] and lt >= crit["min_late"]

    def rec(i, left, counts):
        if i == len(types):
            return left == 0 and ok(counts)
        for c in range(min(left, avail[types[i]]), -1, -1):
            if rec(i + 1, left - c, counts + [c]):
                return True
        return False
    return rec(0, need, [])


def make_design(block, sentinels, sentinel_ns, templates, ages, avoid_paths, ns=SEED_NAMESPACE):
    if block.get("schema") != "finfolk.redqueen.worldsblock/1":
        raise RefselError(f"worlds block schema {block.get('schema')!r}")
    if not isinstance(ages, str) or not os.path.isabs(ages) or not os.path.isfile(ages):
        raise RefselError("--age-reference: the production age reference (an absolute path to a file) is mandatory")
    if not avoid_paths:
        raise RefselError("--avoid: the production reservations are mandatory")
    cands = candidates(block, sentinels, sentinel_ns)
    if not feasible([], cands):
        raise RefselError(f"the usable candidates ({len(cands)}) cannot meet the registered constraints")
    ws = block["worlds"]
    worlds = {w: {"uuid": ws[w]["uuid"], "pattern": ws[w]["pattern"], "paths": ws[w].get("paths", {})}
              for w in sorted({w for w, _ in cands})}
    times = {lab: frame_of(lab) for lab in TIMES}
    edges = []
    for wq, tq in cands:
        prey = {"world": wq, "time": tq}
        base = {"role": "diagnostic", "horizon": "short", "prey": prey, "namespace": "refgrid"}
        for wp, tp in cands:
            edges.append(dict(base, family="refgrid", predators={"world": wp, "time": tp}))
        edges.append(dict(base, family="refgrid-free", predators=None))
    for n, e in enumerate(edges, 1):
        e["edge"] = f"ref{n:05d}"
    design = {"schema": "finfolk.redqueen.design/2", "name": "refgrid", "seed_namespace": ns, "times": times,
              "worlds": worlds, "templates": list(templates), "age_reference": ages, "replicates": REPLICATES,
              "defaults": {"assay": "frozen", "k": K, "prey_policy": "common", "n_prey": N_PREY,
                           "short_steps": HORIZON, "short_horizons": [HORIZON]},
              "long": {"fraction": 0.0}, "edges": edges}
    try:
        rows, _, _ = planlib.expand_v2(design, pending=True)
    except planlib.DesignError as e:
        raise RefselError(f"plan.py refuses the design: {e}")
    seeds = planlib.plan_seeds(rows)
    checked = []
    for p in avoid_paths:
        hit = sorted(seeds & avoid_seeds(p))
        if hit:
            raise RefselError(f"{len(hit)} grid engine seed(s) are reserved in {p}: {hit[:5]}")
        checked.append({"path": os.path.abspath(p), "sha256": rqlib.sha256_file(p)})
    design["refsel"] = {"schema": SCHEMA, "criterion": CRITERION, "criterion_sha256": rqlib.canonical_sha(CRITERION),
                        "sentinels": list(sentinels), "sentinel_namespace": sentinel_ns,
                        "candidates": [[w, t] for w, t in cands], "registry_sha256": block.get("registry_sha256"),
                        "avoid": checked, "cells": len(rows)}
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
                raise RefselError(f"plan {plan_path}: cell {r.get('id')} occurs twice")
            got[r.get("id")] = r
    if set(got) != set(want):
        raise RefselError(f"plan {plan_path}: not the design's cells ({len(set(want) ^ set(got))} differ)")
    for cid, r in got.items():
        if _unhashed(r) != _unhashed(want[cid]):
            raise RefselError(f"plan {plan_path}: cell {cid} differs from the design's expansion")
        for k in HASHED:
            x = r.get(k)
            if isinstance(x, dict) and x.get("path") and not (isinstance(x.get("sha256"), str) and len(x["sha256"]) == 64):
                raise RefselError(f"plan {plan_path}: cell {cid} has no content hash for its {k} (a pending plan)")
    return got, rqlib.sha256_file(plan_path)


def collect(study, design, plan_path, declared_missing=()):
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
            raise RefselError(f"{cid}: not exactly a cell of the final plan")
        if b["score"].get("n_start") != N_PREY:
            raise RefselError(f"{cid}: cohort {b['score'].get('n_start')}, not {N_PREY}")
        h = [x for x in b["score"]["horizons"] if x["steps"] == HORIZON]
        if len(h) != 1:
            raise RefselError(f"{cid}: no single {HORIZON}-step horizon")
        p = row["predators"]
        obs.append({"cell": cid, "prey": [row["prey"]["world"], row["prey"]["time"]],
                    "pred": None if p is None else [p["world"], p["time"]], "replicate": row["replicate"],
                    "captures": h[0].get("captures"), "survivors": h[0]["survivors"], "cohort": N_PREY})
    missing = sorted(set(rows) - {o["cell"] for o in obs})
    if missing != sorted(set(declared_missing)):
        raise RefselError(f"{len(missing)} plan cells are not collected; a missing cell must be declared exactly")
    return {"schema": OBS_SCHEMA, "design_sha256": rqlib.canonical_sha(design), "plan_sha256": plan_sha,
            "missing": missing, "observations": obs}


# ================================================================== the criterion
def matrices(obs, cands, crit=CRITERION):
    """Replicate-level readouts -> per readout the mean matrix (prey x predator candidates) and the cell
    variance of the mean, plus each cell's saturation flags."""
    import numpy as np
    n = len(cands)
    pos = {tuple(c): i for i, c in enumerate(cands)}
    R = crit["replicates"]
    B = crit["capture_bound"]
    free = {}
    cells = {}
    for o in obs:
        if not (isinstance(o.get("survivors"), int) and 0 <= o["survivors"] <= N_PREY):
            raise RefselError(f"{o.get('cell')}: survivors {o.get('survivors')!r}")
        q = pos.get(tuple(o["prey"]))
        if q is None:
            raise RefselError(f"{o.get('cell')}: prey {o['prey']} is not a candidate")
        if o["pred"] is None:
            if (q, o["replicate"]) in free:
                raise RefselError(f"free control {o['prey']} r{o['replicate']} twice")
            free[(q, o["replicate"])] = o["survivors"]
            continue
        p = pos.get(tuple(o["pred"]))
        if p is None:
            raise RefselError(f"{o.get('cell')}: predators {o['pred']} are not a candidate")
        c = o.get("captures")
        if not (isinstance(c, int) and 0 <= c):
            raise RefselError(f"{o.get('cell')}: captures {c!r}")
        cells.setdefault((q, p), {})
        if o["replicate"] in cells[(q, p)]:
            raise RefselError(f"cell {o['prey']} x {o['pred']} r{o['replicate']} twice")
        cells[(q, p)][o["replicate"]] = (c, o["survivors"])
    out = {k: np.full((n, n), np.nan) for k in ("l_mean", "l_var", "q_mean", "q_var", "cap_frac", "surv")}
    for (q, p), reps in cells.items():
        rs = sorted(r for r in reps if (q, r) in free)
        if len(rs) < 2:
            continue
        lv = [math.log((reps[r][0] + 0.5) / (B + 1 - reps[r][0] - 0.5)) if reps[r][0] < B + 0.5 else math.inf for r in rs]
        if not all(math.isfinite(x) for x in lv):
            raise RefselError(f"captures above the capture bound {B} in {cands[q]} x {cands[p]}")
        qv = [(reps[r][1] - free[(q, r)]) / N_PREY for r in rs]
        # the cell's variance of the mean: the replicate variance, floored at the binomial (count)
        # variance (a saturated cell's replicates barely vary, but it carries little information)
        pc = (np.mean([reps[r][0] for r in rs]) + 0.5) / (B + 1)
        ps = np.mean([reps[r][1] for r in rs]) / N_PREY
        p0 = np.mean([free[(q, r)] for r in rs]) / N_PREY
        lfloor = 1.0 / (B * pc * (1 - pc)) / len(rs)
        qfloor = (max(ps * (1 - ps), 0.25 / N_PREY) + max(p0 * (1 - p0), 0.25 / N_PREY)) / N_PREY / len(rs)
        out["l_mean"][q, p], out["l_var"][q, p] = np.mean(lv), max(np.var(lv, ddof=1) / len(rs), lfloor)
        out["q_mean"][q, p], out["q_var"][q, p] = np.mean(qv), max(np.var(qv, ddof=1) / len(rs), qfloor)
        out["cap_frac"][q, p] = np.mean([reps[r][0] / B for r in rs])
        out["surv"][q, p] = ps
    for k, v in out.items():
        if np.isnan(v).any():
            miss = int(np.isnan(v).sum())
            raise RefselError(f"the candidate grid is incomplete: {miss} cells without >= 2 complete replicates "
                              "(the criterion needs the full grid)")
    return out


def embeddings(mats, crit=CRITERION):
    """Per guild and readout: the candidates' rank-4 embeddings, noise weights; per guild the saturation
    shares. Guild "RP" (predator references, placing prey): the columns; "RQ": the rows."""
    import numpy as np
    lo, hi = crit["saturation"]
    rmax = max(crit["ranks"])
    out = {}
    for guild, axis in (("RP", 1), ("RQ", 0)):
        g = {"readouts": {}}
        for name, mk, vk in (("capture_logit", "l_mean", "l_var"), ("survival_contrast", "q_mean", "q_var")):
            M = mats[mk]
            Mc = M - M.mean(axis=1, keepdims=True) - M.mean(axis=0, keepdims=True) + M.mean()
            U, S, Vt = np.linalg.svd(Mc)
            Ssq = np.sqrt(S[:rmax])
            emb = (Vt[:rmax].T * Ssq) if axis == 1 else (U[:, :rmax] * Ssq)
            var = mats[vk].mean(axis=0) if axis == 1 else mats[vk].mean(axis=1)
            if np.any(var <= 0):
                raise RefselError(f"{guild} {name}: a candidate with zero replicate variance")
            g["readouts"][name] = {"emb": emb, "w": 1.0 / var, "sv": S[:rmax].tolist()}
        satC = ((mats["cap_frac"] < lo) | (mats["cap_frac"] > hi)).mean(axis=0 if axis == 1 else 1)
        satS = ((mats["surv"] < lo) | (mats["surv"] > hi)).mean(axis=0 if axis == 1 else 1)
        g["sat"] = (satC + satS) / 2
        out[guild] = g
    return out


def objective(g, idx, crit=CRITERION, detail=False):
    """The registered objective of a candidate index set for one guild (see the module doc)."""
    import numpy as np
    n = len(g["sat"])
    total, parts = 0.0, {}
    for name, rd in g["readouts"].items():
        for r in crit["ranks"]:
            X = np.hstack([np.ones((n, 1)), rd["emb"][:, :r]])
            Iall = (X * rd["w"][:, None]).T @ X
            eps = crit["eps"] * np.trace(Iall) / ((r + 1) * n)
            I = (X[idx] * rd["w"][idx][:, None]).T @ X[idx] + eps * np.eye(r + 1)
            lam = float(np.linalg.eigvalsh((I + I.T) / 2)[0])
            v = math.log(max(lam, 1e-300))
            parts[f"{name}/rank{r}"] = v
            total += v
    pen = crit["saturation_penalty"] * float(np.sum(g["sat"][idx]))
    total -= pen
    if detail:
        return total, dict(parts, saturation_penalty=pen)
    return total


def select_guild(g, cands, guild, crit=CRITERION):
    """Greedy, then the best improving swaps; ties by the registered hash order. -> (indices, log)."""
    order = sorted((i for i in range(len(cands)) if g["sat"][i] <= crit["max_saturated_share"]),
                   key=lambda i: tie_key(guild, cands[i][0], frame_of(cands[i][1]), crit))
    rank = {i: k for k, i in enumerate(order)}
    if not feasible([], [cands[i] for i in order], crit):
        raise RefselError(f"{guild}: the eligible (not mostly saturated) candidates cannot meet the constraints")
    chosen, log = [], []

    def better(a, b):            # (value, tie rank): a strictly better than b
        if b is None:
            return True
        if a[0] > b[0] + 1e-12 * max(1.0, abs(b[0])):
            return True
        return abs(a[0] - b[0]) <= 1e-12 * max(1.0, abs(b[0])) and a[1] < b[1]
    while len(chosen) < crit["n_ref"]:
        best = None
        for i in order:
            if i in chosen:
                continue
            S = chosen + [i]
            pool = [cands[j] for j in order if j not in S]
            if not feasible([cands[j] for j in S], pool, crit):
                continue
            cand = (objective(g, S, crit), rank[i], i)
            if better(cand, best):
                best = cand
        if best is None:
            raise RefselError(f"{guild}: no candidate keeps the constraints satisfiable")
        chosen.append(best[2])
        log.append({"add": list(cands[best[2]]), "objective": best[0]})
    cur = objective(g, chosen, crit)
    for _ in range(crit["max_swaps"]):
        best = None
        for s in sorted(chosen, key=lambda i: rank[i]):
            for c in order:
                if c in chosen:
                    continue
                S = [c if x == s else x for x in chosen]
                if not feasible([cands[j] for j in S], [], crit):
                    continue
                v = objective(g, S, crit)
                if v > cur + 1e-9 * max(1.0, abs(cur)):
                    cand = (v, rank[s] * len(cands) + rank[c], (s, c))
                    if better(cand, best):
                        best = cand
        if best is None:
            break
        s, c = best[2]
        chosen = [c if x == s else x for x in chosen]
        cur = best[0]
        log.append({"swap_out": list(cands[s]), "swap_in": list(cands[c]), "objective": cur})
    return chosen, log


def select(obs, design, plan_rows=None, crit=CRITERION):
    """The registered selection from the grid observations -> (references/1 document, report)."""
    rs = design["refsel"]
    if rs["criterion_sha256"] != rqlib.canonical_sha(crit) or rs["criterion"] != crit:
        raise RefselError("the criterion is not the one frozen in the plan (sha256 differs)")
    cands = [tuple(c) for c in rs["candidates"]]
    mats = matrices(obs, cands, crit)
    emb = embeddings(mats, crit)
    ns = rs["sentinel_namespace"]
    refs, report = {}, {"criterion_sha256": rs["criterion_sha256"], "guilds": {}}
    for guild in ("RQ", "RP"):
        idx, log = select_guild(emb[guild], cands, guild, crit)
        total, parts = objective(emb[guild], idx, crit, detail=True)
        sel = sorted((cands[i] for i in idx), key=lambda c: (frame_of(c[1]), tie_key(guild, c[0], frame_of(c[1]), crit)))
        for k, (w, lab) in enumerate(sel):
            fr = frame_of(lab)
            wu = design["worlds"][w]["uuid"]
            ent = {"world": w, "frame": fr, "uuid": wu, "snapshot": planlib.snapshot_uuid(wu, fr),
                   "archive": planlib.snapshot_path(design, w, lab)}
            ent["sha256"] = _archive_sha(plan_rows, w, lab, guild) if plan_rows else None
            refs[f"{guild}:{k}"] = ent
        report["guilds"][guild] = {"selected": [list(c) for c in sel], "objective": total, "parts": parts,
                                   "steps": log, "sentinels": sorted({w for w, _ in sel}),
                                   "early": sum(1 for _, t in sel if time_m(t) <= crit["early_max_M"]),
                                   "late": sum(1 for _, t in sel if time_m(t) >= crit["late_min_M"]),
                                   "singular_values": {k: v["sv"] for k, v in emb[guild]["readouts"].items()}}
    doc = {"schema": REFS_SCHEMA, "namespace": ns, "references": refs,
           "selection": {"refsel_schema": SCHEMA, "criterion_sha256": rs["criterion_sha256"],
                         "design_sha256": rqlib.canonical_sha(design)}}
    return doc, report


def _archive_sha(rows, world, label, guild):
    """The snapshot file's sha256 as the final plan registered it (the prey role for RQ, predators for RP)."""
    role = "prey" if guild == "RQ" else "predators"
    for r in rows.values():
        x = r.get(role)
        if isinstance(x, dict) and x.get("world") == world and x.get("time") == label and x.get("sha256"):
            return x["sha256"]
    raise RefselError(f"no plan row carries the {role} snapshot {world} {label}")


# ================================================================== CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan")
    s.add_argument("--block", required=True)
    s.add_argument("--sentinels", default=",".join(SENTINELS))
    s.add_argument("--sentinel-namespace", required=True)
    s.add_argument("--templates", nargs="+", required=True)
    s.add_argument("--age-reference", required=True)
    s.add_argument("--avoid", action="append", required=True)
    s.add_argument("--namespace", default=SEED_NAMESPACE)
    s.add_argument("--out", required=True)
    s = sub.add_parser("collect")
    s.add_argument("--study", required=True)
    s.add_argument("--design", required=True)
    s.add_argument("--plan", required=True)
    s.add_argument("--declare-missing")
    s.add_argument("--out", required=True)
    s = sub.add_parser("select")
    s.add_argument("obs")
    s.add_argument("--design", required=True)
    s.add_argument("--plan", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--report", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":
            d = make_design(rqlib.read_json(a.block), a.sentinels.split(","), a.sentinel_namespace, a.templates,
                            a.age_reference, a.avoid, a.namespace)
            rqlib.write_json_durable(a.out, d)
            print(f"{len(d['refsel']['candidates'])} candidates per guild; {d['refsel']['cells']} cells; "
                  f"criterion {d['refsel']['criterion_sha256'][:16]}")
            return 0
        design = rqlib.read_json(a.design)
        if a.cmd == "collect":
            miss = ([x.strip() for x in rqlib.read_text(a.declare_missing).split("\n") if x.strip()]
                    if a.declare_missing else [])
            doc = collect(a.study, design, a.plan, miss)
            rqlib.write_json_durable(a.out, doc)
            print(f"{len(doc['observations'])} observations; missing {len(doc['missing'])}")
            return 0
        doc = rqlib.read_json(a.obs)
        rows, plan_sha = bind_plan(design, a.plan)
        if doc.get("schema") != OBS_SCHEMA or doc.get("plan_sha256") != plan_sha \
                or doc.get("design_sha256") != rqlib.canonical_sha(design):
            raise RefselError("the observations were not collected under this design and final plan")
        refs, report = select(doc["observations"], design, rows)
        report["plan_sha256"] = plan_sha
        rqlib.write_json_durable(a.out, refs)
        rqlib.write_json_durable(a.report, report)
        for g in ("RQ", "RP"):
            print(g, report["guilds"][g]["selected"])
        return 0
    except RefselError as e:
        print(f"refsel.py {a.cmd}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

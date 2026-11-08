#!/usr/bin/env python3
"""rho_pilot.py: the H-C allocation pilot (USER DECISIONS 2, items 5-6, of Annex H; Gemini q32 §3).
The assay plan, the collection of its results and the estimator of rho = SD(d_w) / 0.02, with the
allocation rule FIXED before any pilot assay is run (this file's sha256 is recorded in statusB.log).

THE PILOT WORLDS: the floor-free validation run, 8 C + 2 A + 2 B worlds to 100M (worlds.py), its
archived checkpoints every 10M.

PLAN (`plan`): a design/2 for plan.py, from the validation study's worlds block (worlds.py
design-block), its own seed namespace (default rq2026-rho-pilot: never production seeds). For every
pilot world w (C, A and B) and every time t in 10, 20, ..., 100M at which w's prey snapshot is archived
and valid (before its first zero), the prey snapshot of w at t meets
  * a NEURAL panel: the predators of four C worlds of the pilot other than w, at the same time t: w's
    ranking of the other C worlds by sha256("<namespace>|rho-panel|<w>|<c>"), the first four whose
    snapshot at t is archived and valid (fewer than four: the (w, t) cell is not planned, recorded);
  * the SCRIPTED benchmark: one frozen scripted-predator checkpoint (--scripted), the same for all;
  * the PREDATOR-FREE control;
each R = 12 replicates, the production assay (frozen, K 6, 600 common prey, the 5k short horizon), role
"diagnostic", families rho-neural / rho-scripted / rho-free. The common prey of one (w, t, r) is shared
by every condition (plan.py's sharing groups), so the per-replicate contrasts are paired.

COLLECT (`collect`): reads the study's packed bundles (store.py chunks) and writes one observation
per cell: world, time, condition (neural:<world> | scripted | free), replicate, survivors at the
5000-step horizon, cohort size.

ESTIMATOR (`estimate`; the registered definitions):
  y_{w,t} = mean_r z_r, z_r = (1/4) sum_k S_{N_k, r} - S_{S, r} (S = survivors / cohort; the free
    control cancels exactly in the neural-minus-scripted difference, H.13 5; it is reported as the
    descriptive covariate only), v_{w,t} = Var_r(z_r) / R (paired replicates);
  increments over the nine 10M epochs after the 0-10M burn-in, in per-50M units:
    D_{w,j} = 5 (y_{w,t_j} - y_{w,t_{j-1}}), t_j = 10j M, j = 2..10 (J = 9); their assay covariance
    Sigma_w: 25 (v_j + v_{j-1}) on the diagonal, -25 v_j between consecutive increments;
  model D_{w,j} = mu_T + eta_j + u_w + e_{w,j} + xi_{w,j} (treatment means, common epoch effects, the
    persistent world velocity u_w ~ (0, s_u^2), the transient epoch drift e ~ (0, s_e^2), the known
    assay noise xi); complete worlds only (all ten times); method of moments, truncated at 0:
      s_e^2 = [Q1 - (1 - 1/N) sum_w tr(M Sigma_w)] / ((N - 1)(J - 1)), Q1 the two-way residual sum of
        squares, M = I - 11'/J;
      s_u^2 = [Q2 - sum_w (1 - 1/n_T) 1'Sigma_w 1 / J^2] / sum_T (n_T - 1) - s_e^2 / J, Q2 the
        within-treatment sum of squares of the world mean increments;
  the projection to the production H-C contrast (an OLS projection over the 41 coarse times of 200M):
      V = s_u^2 + gamma_OLS s_e^2 / 20 + 2 vbar / Sxx,
    gamma_OLS = 20 Var(OLS slope of a 10M-epoch random walk on the 41 coarse times) / s_e^2 (computed
    exactly; about 1.2), 2 vbar / Sxx the production assay term (R = 6: twice the pilot's mean
    per-snapshot variance, over Sxx = sum (x - xbar)^2 of x = t / 50 on the 41 coarse times);
  rho_hat = sqrt(V) / 0.02. 90% interval: the normal-theory parametric bootstrap of the two mean
    squares (chi-square draws, 20,000, stream AnnexH/1/H-C/rho-pilot/bootstrap), percentiles 5 / 95.
  Reported besides (never deciding): per-treatment components, the endpoint-window variant
    (gamma_EW), the correlation of d_w with the predator-free survival slope.
THE ALLOCATION RULE (fixed now; never tuned): rho_hat <= 0.85 -> 48 worlds, 8 x (4C+1A+1B);
0.85 < rho_hat <= 1.35 -> 56, 4 x (4C+2A+1B) + 4 x (4C+1A+2B); rho_hat > 1.35 -> 64, 8 x (4C+2A+2B).
An unavailable estimate (fewer than 2 between-world degrees of freedom or no within-world ones)
-> 64, the conservative allocation.

    rho_pilot.py plan --block worlds_block.json --scripted /abs/sb.json --templates /abs/t1.json ... \
        --age-reference /abs/ages.json --out design.json
    rho_pilot.py collect --study PILOT_STUDY --out obs.jsonl
    rho_pilot.py estimate obs.jsonl [--out rho.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import uuid
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rqlib  # noqa: E402

SCHEMA = "finfolk.redqueen.rhopilot/1"
NAMESPACE = "rq2026-rho-pilot"
TIMES_M = tuple(range(10, 101, 10))
REPLICATES = 12
PANEL = 4
HORIZON = 5000
DELTA = 0.02
THRESHOLDS = (0.85, 1.35)
ALLOCATIONS = {48: "8 x (4C+1A+1B)", 56: "4 x (4C+2A+1B) + 4 x (4C+1A+2B)", 64: "8 x (4C+2A+2B)"}
COARSE = [1e-6] + [5.0 * k for k in range(1, 41)]
BOOT = 20000
SCRIPTED = "scripted-bench"


class PilotError(Exception):
    pass


def allocation(rho):
    """The FIXED allocation rule (None: an unavailable estimate -> the conservative 64)."""
    if rho is None or not math.isfinite(rho):
        return 64
    if rho <= THRESHOLDS[0]:
        return 48
    if rho <= THRESHOLDS[1]:
        return 56
    return 64


# ================================================================== the plan
def panel_order(ns, w, cworlds):
    return sorted((c for c in cworlds if c != w),
                  key=lambda c: hashlib.sha256(f"{ns}|rho-panel|{w}|{c}".encode()).hexdigest())


def make_design(block, scripted, templates, ages, ns=NAMESPACE, scripted_frame=None):
    """worlds.py's worlds block -> (design/2 dict, notes)."""
    if block.get("schema") != "finfolk.redqueen.worldsblock/1":
        raise PilotError(f"worlds block schema {block.get('schema')!r}")
    if not os.path.isabs(scripted) or not os.path.isfile(scripted):
        raise PilotError("--scripted: the absolute path of the frozen scripted-benchmark checkpoint")
    labels = {f"{t}M": t * 1_000_000 for t in TIMES_M}
    for lab, fr in labels.items():
        if block["times"].get(lab) != fr:
            raise PilotError(f"the validation schedule does not archive {lab} (frame {fr})")
    ws = block["worlds"]
    cw = sorted(w for w, v in ws.items() if v["treatment"] == "C")
    sb_sha = rqlib.sha256_file(scripted)
    if scripted_frame is None:
        with open(scripted) as f:
            scripted_frame = int(json.load(f)["world"]["frame"])
    times = dict(labels, SB=int(scripted_frame))
    worlds = {w: {"uuid": v["uuid"], "pattern": v["pattern"], "paths": v.get("paths", {})} for w, v in ws.items()}
    worlds[SCRIPTED] = {"uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:scripted-benchmark:{sb_sha}")),
                        "paths": {"SB": scripted}}

    def valid(w, t):
        v = ws[w]
        fr = t * 1_000_000
        return fr in v.get("archived", []) and (v.get("valid_before") is None or fr < v["valid_before"])
    edges, notes = [], {"skipped": []}
    for w in sorted(ws):
        order = panel_order(ns, w, cw)
        for t in TIMES_M:
            lab = f"{t}M"
            if not valid(w, t):
                notes["skipped"].append({"world": w, "time": lab, "reason": "prey snapshot not archived or at/after a zero"})
                continue
            panel = [c for c in order if valid(c, t)][:PANEL]
            if len(panel) < PANEL:
                notes["skipped"].append({"world": w, "time": lab, "reason": f"only {len(panel)} neural predators valid"})
                continue
            prey = {"world": w, "time": lab}
            for c in panel:
                edges.append({"family": "rho-neural", "role": "diagnostic", "horizon": "short", "prey": prey,
                              "predators": {"world": c, "time": lab}})
            edges.append({"family": "rho-scripted", "role": "diagnostic", "horizon": "short", "prey": prey,
                          "predators": {"world": SCRIPTED, "time": "SB"}})
            edges.append({"family": "rho-free", "role": "diagnostic", "horizon": "short", "prey": prey,
                          "predators": None})
    for n, e in enumerate(edges, 1):
        e["edge"] = f"rho{n:05d}"
    design = {"schema": "finfolk.redqueen.design/2", "name": "rho-pilot", "seed_namespace": ns, "times": times,
              "worlds": worlds, "templates": list(templates), "age_reference": ages, "replicates": REPLICATES,
              "defaults": {"assay": "frozen", "k": 6, "prey_policy": "common", "n_prey": 600,
                           "short_steps": HORIZON, "short_horizons": [HORIZON]},
              "long": {"fraction": 0.0}, "edges": edges,
              "rho_pilot": {"schema": SCHEMA, "registry_sha256": block.get("registry_sha256"),
                            "scripted_sha256": sb_sha, "panel": PANEL, "times_M": list(TIMES_M)}}
    return design, notes


# ================================================================== collect
def collect(study):
    """Every packed cell of the pilot study -> observations (sorted)."""
    idx = os.path.join(study, "chunks", "index.jsonl")
    out = []
    for line in open(idx):
        if not line.strip():
            continue
        rec = json.loads(line)
        with zipfile.ZipFile(os.path.join(study, "chunks", rec["file"])) as z:
            for name in z.namelist():
                if not name.endswith("/bundle.json"):
                    continue
                b = json.loads(z.read(name))
                c = b["cell"]
                fam = c.get("primary_family") or (c.get("families") or [""])[0]
                if not fam.startswith("rho-"):
                    continue
                h = next(x for x in b["score"]["horizons"] if x["steps"] == HORIZON)
                cond = ("free" if c["kind"] == "nopred" else "scripted" if c["predators"]["world"] == SCRIPTED
                        else f"neural:{c['predators']['world']}")
                out.append({"world": c["prey"]["world"], "time": c["prey"]["time"], "condition": cond,
                            "replicate": c["replicate"], "survivors": h["survivors"], "cohort": b["score"]["n_start"]})
    return sorted(out, key=lambda o: (o["world"], TIMES_M.index(int(o["time"][:-1])), o["condition"], o["replicate"]))


# ================================================================== the estimator
def contrasts(obs):
    """-> {world: {t (M): (y, v, free survival mean)}}, the paired per-replicate neural-minus-scripted
    contrasts; a (w, t) without four neural predators, the scripted and every replicate is dropped."""
    cells = {}
    for o in obs:
        cells.setdefault((o["world"], int(o["time"][:-1])), []).append(o)
    out = {}
    for (w, t), lst in sorted(cells.items()):
        by = {}
        for o in lst:
            by.setdefault(o["replicate"], {})[o["condition"]] = o["survivors"] / o["cohort"]
        reps = sorted(by)
        z, free = [], []
        for r in reps:
            neu = [v for k, v in by[r].items() if k.startswith("neural:")]
            if len(neu) != PANEL or "scripted" not in by[r]:
                z = None
                break
            z.append(sum(neu) / PANEL - by[r]["scripted"])
            if "free" in by[r]:
                free.append(by[r]["free"])
        if z is None or len(z) < 2:
            continue
        m = sum(z) / len(z)
        v = sum((x - m) ** 2 for x in z) / (len(z) - 1) / len(z)
        out.setdefault(w, {})[t] = (m, v, sum(free) / len(free) if free else None)
    return out


def _ols_weights(xs):
    xb = sum(xs) / len(xs)
    sxx = sum((x - xb) ** 2 for x in xs)
    return [(x - xb) / sxx for x in xs], sxx


def gamma_ols():
    """20 Var(OLS slope per 50M over the 41 coarse times) / s_e^2 for a random walk whose 10M-epoch
    increments have variance s_e^2 / 25 (s_e^2: per-50M units), computed exactly."""
    c, _ = _ols_weights([t / 50.0 for t in COARSE])
    var = sum(ci * ck * min(ti, tk) / 10.0 / 25.0 for ci, ti in zip(c, COARSE) for ck, tk in zip(c, COARSE))
    return 20.0 * var


def gamma_endpoint():
    """The same for the endpoint-window contrast: mean over [175, 200] minus mean over [0, 25] (coarse
    times), divided by 3.5 (per 50M)."""
    lo = [t for t in COARSE if t <= 25.0]
    hi = [t for t in COARSE if t >= 175.0]
    c = {}
    for t in lo:
        c[t] = c.get(t, 0.0) - 1.0 / len(lo) / 3.5
    for t in hi:
        c[t] = c.get(t, 0.0) + 1.0 / len(hi) / 3.5
    var = sum(a * b * min(s, u) / 10.0 / 25.0 for s, a in c.items() for u, b in c.items())
    return 20.0 * var


def sxx_coarse():
    return _ols_weights([t / 50.0 for t in COARSE])[1]


def decompose(series, treatment):
    """Method-of-moments components from the complete worlds. series: {w: {t: (y, v, f)}}."""
    J = len(TIMES_M) - 1
    W = sorted(w for w in series if all(t in series[w] for t in TIMES_M))
    N = len(W)
    if N < 2:
        return None
    D, S = {}, {}
    for w in W:
        y = [series[w][t][0] for t in TIMES_M]
        v = [series[w][t][1] for t in TIMES_M]
        D[w] = [5.0 * (y[j] - y[j - 1]) for j in range(1, J + 1)]
        Sg = [[0.0] * J for _ in range(J)]
        for j in range(J):
            Sg[j][j] = 25.0 * (v[j + 1] + v[j])
            if j + 1 < J:
                Sg[j][j + 1] = Sg[j + 1][j] = -25.0 * v[j + 1]
        S[w] = Sg
    wm = {w: sum(D[w]) / J for w in W}
    em = [sum(D[w][j] for w in W) / N for j in range(J)]
    gm = sum(wm.values()) / N
    Q1 = sum((D[w][j] - wm[w] - em[j] + gm) ** 2 for w in W for j in range(J))
    trM = {w: sum(S[w][j][j] for j in range(J)) - sum(sum(r) for r in S[w]) / J for w in W}
    a = {w: sum(sum(r) for r in S[w]) / J ** 2 for w in W}
    df_w = (N - 1) * (J - 1)
    groups = {}
    for w in W:
        groups.setdefault(treatment[w], []).append(w)
    df_b = sum(len(g) - 1 for g in groups.values())
    Q2 = sum((wm[w] - sum(wm[x] for x in g) / len(g)) ** 2 for g in groups.values() for w in g)
    Ab = sum((1 - 1 / len(g)) * a[w] for g in groups.values() for w in g)
    Aw = (1 - 1 / N) * sum(trM.values())
    vbar = sum(series[w][t][1] for w in W for t in TIMES_M) / (N * len(TIMES_M))
    return {"worlds": W, "N": N, "J": J, "Q1": Q1, "Q2": Q2, "df_w": df_w, "df_b": df_b, "Aw": Aw, "Ab": Ab,
            "vbar": vbar, "world_mean_increment": wm,
            "per_treatment": {T: len(g) for T, g in groups.items()}}


def components(dec, MSb=None, MSw=None, gamma=None):
    """(s_u^2, s_e^2, V) from the decomposition's mean squares (or substituted ones)."""
    J = dec["J"]
    MSw = dec["Q1"] / dec["df_w"] if MSw is None else MSw
    MSb = dec["Q2"] / dec["df_b"] if MSb is None else MSb
    se2 = max(0.0, MSw - dec["Aw"] / dec["df_w"])
    su2 = max(0.0, MSb - dec["Ab"] / dec["df_b"] - se2 / J)
    g = gamma_ols() if gamma is None else gamma
    V = su2 + g * se2 / 20.0 + 2.0 * dec["vbar"] / sxx_coarse()
    return su2, se2, V


def _chi2(rng, df):
    s = 0.0
    for _ in range(df):
        u1 = 1.0 - rng.next64() / 2.0 ** 64
        u2 = rng.next64() / 2.0 ** 64
        z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2 * math.pi * u2)
        s += z * z
    return s


def estimate(obs, treatment, boot=BOOT):
    """The registered estimate, interval and allocation from observations and {world: treatment}."""
    series = contrasts(obs)
    dec = decompose(series, treatment)
    out = {"schema": SCHEMA, "thresholds": list(THRESHOLDS), "allocations": {str(k): v for k, v in ALLOCATIONS.items()},
           "gamma_ols": gamma_ols(), "gamma_endpoint": gamma_endpoint(), "sxx_coarse": sxx_coarse(),
           "worlds_observed": sorted(series)}
    if dec is None or dec["df_b"] < 2 or dec["df_w"] < 1:
        out.update(available=False, rho_hat=None, allocation=allocation(None),
                   reason="fewer than 2 between-world or no within-world degrees of freedom")
        return out
    su2, se2, V = components(dec)
    rho = math.sqrt(V) / DELTA
    rng = rqlib.SplitMix64(int.from_bytes(hashlib.sha256(b"AnnexH/1/H-C/rho-pilot/bootstrap").digest()[:8], "little"))
    MSb, MSw = dec["Q2"] / dec["df_b"], dec["Q1"] / dec["df_w"]
    rs = []
    for _ in range(boot):
        b = _chi2(rng, dec["df_b"]) / dec["df_b"]
        w = _chi2(rng, dec["df_w"]) / dec["df_w"]
        rs.append(math.sqrt(components(dec, MSb * b, MSw * w)[2]) / DELTA)
    rs.sort()
    q = lambda u: rs[min(len(rs) - 1, max(0, math.ceil(u * (len(rs) + 1)) - 1))]  # noqa: E731
    su2e, se2e, Ve = components(dec, gamma=gamma_endpoint())
    out.update(available=True, rho_hat=rho, allocation=allocation(rho), ci90=[q(0.05), q(0.95)],
               components={"s_u2": su2, "s_e2": se2, "assay_prod": 2.0 * dec["vbar"] / sxx_coarse(), "V": V},
               endpoint_variant={"rho": math.sqrt(Ve) / DELTA, "V": Ve},
               decomposition={k: v for k, v in dec.items() if k not in ("world_mean_increment",)},
               world_mean_increment=dec["world_mean_increment"])
    # descriptive: d_w (OLS over the pilot times, per 50M) vs the free-survival slope
    c, _ = _ols_weights([t / 50.0 for t in TIMES_M])
    dw, fw = {}, {}
    for w in dec["worlds"]:
        dw[w] = sum(ci * series[w][t][0] for ci, t in zip(c, TIMES_M))
        fs = [series[w][t][2] for t in TIMES_M]
        if all(f is not None for f in fs):
            fw[w] = sum(ci * f for ci, f in zip(c, fs))
    out["d_w_pilot"] = dw
    ks = sorted(set(dw) & set(fw))
    if len(ks) >= 3:
        mx, my = sum(dw[k] for k in ks) / len(ks), sum(fw[k] for k in ks) / len(ks)
        sxy = sum((dw[k] - mx) * (fw[k] - my) for k in ks)
        sx = math.sqrt(sum((dw[k] - mx) ** 2 for k in ks))
        sy = math.sqrt(sum((fw[k] - my) ** 2 for k in ks))
        out["corr_d_free_slope"] = sxy / (sx * sy) if sx > 0 and sy > 0 else None
    return out


# ================================================================== CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan")
    s.add_argument("--block", required=True)
    s.add_argument("--scripted", required=True)
    s.add_argument("--scripted-frame", type=int)
    s.add_argument("--templates", nargs="+", required=True)
    s.add_argument("--age-reference")
    s.add_argument("--namespace", default=NAMESPACE)
    s.add_argument("--out", required=True)
    s = sub.add_parser("collect")
    s.add_argument("--study", required=True)
    s.add_argument("--out", required=True)
    s = sub.add_parser("estimate")
    s.add_argument("obs")
    s.add_argument("--block", required=True, help="the worlds block (world -> treatment)")
    s.add_argument("--out")
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        design, notes = make_design(rqlib.read_json(a.block), a.scripted, a.templates, a.age_reference, a.namespace,
                                    a.scripted_frame)
        rqlib.write_json_durable(a.out, design)
        print(f"{len(design['edges'])} edges ({len(design['edges']) * REPLICATES} cells); skipped {len(notes['skipped'])}")
        for n in notes["skipped"]:
            print(f"  skipped {n['world']} {n['time']}: {n['reason']}")
        return 0
    if a.cmd == "collect":
        obs = collect(a.study)
        with open(a.out, "w") as f:
            for o in obs:
                f.write(json.dumps(o, sort_keys=True) + "\n")
        print(f"{len(obs)} observations")
        return 0
    with open(a.obs) as f:
        obs = [json.loads(ln) for ln in f if ln.strip()]
    tr = {w: v["treatment"] for w, v in rqlib.read_json(a.block)["worlds"].items()}
    res = estimate(obs, tr)
    txt = json.dumps(res, indent=1, sort_keys=True)
    if a.out:
        rqlib.write_json_durable(a.out, res)
    print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())

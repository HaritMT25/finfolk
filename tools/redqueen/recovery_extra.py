#!/usr/bin/env python3
"""Frozen, additive exact-graph recovery extensions.

prepare writes no simulated observations.
run verifies the frozen plan and starts at most two one-thread workers.
Scientific outputs are synthetic planning-noise diagnostics, not bank validation.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import math
import os
import signal
import subprocess
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

THREAD_VARS = (
    "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
    "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)
if __name__ == "__main__":
    for _name in THREAD_VARS:
        os.environ[_name] = "1"

import recovery as rec  # noqa: E402
import graph  # noqa: E402
import map as mapfit  # noqa: E402
import rqlib  # noqa: E402

np = rec.np

PLAN_SCHEMA = "finfolk.redqueen.recoveryextra.plan/1"
RESULT_SCHEMA = "finfolk.redqueen.recoveryextra.result/1"
CASE_SCHEMA = "finfolk.redqueen.recoverysyntheticcase/1"
SUMMARY_SCHEMA = "finfolk.redqueen.recoveryextra.summary/1"
OPTIONS = ("a", "interp", "fwd_all", "fwd_early")
CASES = (
    "intact", "biological_at", "biological_after", "technical",
    "pending_prefix", "pending_attempt", "mixed", "roots0", "roots1",
    "roots2",
)
FIT_KEYS = ("ranks", "lambdas", "iters", "start", "basis", "embedding", "center")
CRITERION = {
    "status": "prospective operationalization; coordinator adoption required",
    "case": "intact",
    "option": "a",
    "scenarios": ["r1_034", "r2_034"],
    "ranks": [0, 1, 2, 3, 4],
    "datasets_each": 20,
    "successes_each": 16,
    "unavailable": "unsuccessful; stays in denominator",
    "interval": "Wilson95; no lower-endpoint acceptance requirement",
    "scope": "scenario planning noise; not bank-calibrated recovery",
}


def clean(x):
    """Stable scientific JSON; legacy timing fields stay out of new results."""
    if isinstance(x, np.generic):
        return clean(x.item())
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items() if k != "seconds"}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, float) and not math.isfinite(x):
        if x == -math.inf:
            return "-Infinity"
        raise ValueError("NaN or positive infinity in a scientific result")
    return x


def csv(value, allowed):
    xs = value.split(",")
    if not xs or len(xs) != len(set(xs)) or any(x not in allowed for x in xs):
        raise SystemExit(f"{value!r}: distinct members of {tuple(allowed)} required")
    return xs


def source_hashes():
    return {
        name: rqlib.sha256_file(os.path.join(HERE, name))
        for name in sorted(os.listdir(HERE))
        if name.endswith(".py") and not name.startswith("test_")
    }


def ranked(namespace, category, worlds):
    return sorted(worlds, key=lambda w: (
        rqlib.derive64(namespace, "recovery-attrition-v1", category, w), w
    ))


def recipes(D, namespace):
    """All choices depend on identities/topology, never outcomes."""
    ordinary = [
        i for i, e in enumerate(D.g["edges"])
        if not D.within[i]
        and not D.qref[D.qi[i]]
        and not D.pref[D.pj[i]]
        and e[3] != "support"
    ]
    ordinary.sort(key=lambda i: (
        rqlib.derive64(
            namespace, "recovery-interpolation-v1",
            D.g["edges"][i][0], D.g["edges"][i][1],
        ),
        D.g["edges"][i][0], D.g["edges"][i][1],
    ))
    n = len(ordinary)
    ntrain, nval = 8 * n // 10, n // 10
    groups = []
    for k, i in enumerate(ordinary):
        role = "training" if k < ntrain else (
            "validation" if k < ntrain + nval else "test"
        )
        q, p = D.g["edges"][i][:2]
        groups.append([i, q, p, role])

    ct = ranked(namespace, "training-C", [
        w["id"] for w in D.g["worlds"]
        if w["treatment"] == "C" and D.g["split"][w["id"]] == "train"
    ])
    cv = ranked(namespace, "validation-C", [
        w["id"] for w in D.g["worlds"]
        if w["treatment"] == "C" and D.g["split"][w["id"]] == "val"
    ])
    roots = ranked(namespace, "test-roots", [
        D.worlds[int(w)] for w in np.unique(D.test_world)
    ])
    if len(ct) < 3 or not cv:
        raise SystemExit("the registered layout needs training/validation C worlds")

    def rule(world, cause, first, last=200_000_000):
        return {"world": world, "cause": cause, "first": first, "last": last}

    at = [rule(ct[0], "biological", 100_000_000)]
    after = [rule(ct[0], "biological", 100_005_000)]
    technical = [rule(ct[1], "technical", 50_000_000, 50_000_000)]
    pending = [rule(ct[2], "pending", 120_000_001)]
    attempt = [rule(cv[0], "pending", 1)]
    cases = {
        "intact": [],
        "biological_at": at,
        "biological_after": after,
        "technical": technical,
        "pending_prefix": pending,
        "pending_attempt": attempt,
        "mixed": at + technical + pending + attempt,
    }
    test_worlds = sorted(w for w, s in D.g["split"].items() if s == "test")
    for keep in (0, 1, 2):
        retained = set(roots[:keep])
        cases[f"roots{keep}"] = [
            rule(w, "pending", 1) for w in test_worlds if w not in retained
        ]
    return {
        "interpolation": {
            "schema": "finfolk.redqueen.recoveryinterpolation/1",
            "unit": "ordered population pair; all replicates/versions together",
            "eligible": "global ordinary non-support pairs",
            "calibration": "references and declared support remain fitted",
            "counts": {
                "training": ntrain, "validation": nval,
                "test": n - ntrain - nval,
            },
            "groups": groups,
        },
        "attrition": cases,
        "root_order": roots,
        "forward": {
            "main": "legacy main-outcome and target masks",
            "references": "external calibration, including reference grid",
            "all": "all selected references and their controls",
            "early": "reference endpoints and controls <=120M",
            "ordinary_controls": "<=120M only",
        },
    }


def mask_for(D, plan, case):
    rules = plan["recipe"]["attrition"][case]
    snaps = {}
    for rule in rules:
        for t in graph.TIMES:
            frame = graph.frame_of(t)
            if not rule["first"] <= frame <= rule["last"]:
                continue
            key = f"{rule['world']}:{frame}"
            old = snaps.get(key)
            cause = rule["cause"]
            if old and graph.EXCLUSION.index(old["status"]) <= graph.EXCLUSION.index(cause):
                continue
            snaps[key] = {
                "world": rule["world"], "time": t, "frame": frame,
                "status": cause, "why": f"frozen synthetic case {case}",
            }
    excluded, by = graph.edge_exclusions(D.g, snaps)
    keep = np.ones(len(D.qi), bool)
    causes = {}
    for cause, indices in excluded.items():
        keep[np.asarray(indices, dtype=int)] = False
        causes.update({i: cause for i in indices})
    worlds = {}
    for w in D.g["worlds"]:
        c = Counter(s["status"] for s in snaps.values() if s["world"] == w["id"])
        worlds[w["id"]] = {
            "treatment": w["treatment"], "block": w["block"],
            "available_snapshots": len(graph.TIMES) - sum(c.values()),
            "excluded_snapshots": {k: c[k] for k in graph.EXCLUSION},
        }
    return keep, {
        "schema": CASE_SCHEMA, "synthetic": True, "case": case,
        "rules": rules, "snapshots": snaps, "worlds": worlds,
        "excluded_edges": excluded, "by_family_role": by,
        "scheduled_pairs": len(keep), "retained_pairs": int(keep.sum()),
    }, causes


def view_for(D, plan, option, keep):
    """Keep the scheduled node numbering and observations; change access arrays."""
    v = copy.copy(D)
    v.role = D.role.copy()
    v.fit = {k: ix[keep[ix]] for k, ix in D.fit.items()}
    vt = keep[D.val_idx]
    tt = keep[D.test_idx]
    v.val_idx, v.val_world = D.val_idx[vt], D.val_world[vt]
    v.test_idx, v.test_world = D.test_idx[tt], D.test_world[tt]
    v.stest_idx = D.stest_idx[keep[D.stest_idx]]
    v.classes = {k: ix[keep[ix]] for k, ix in D.classes.items()}

    if option == "interp":
        eligible = np.zeros(len(D.qi), bool)
        for i, q, p, role in plan["recipe"]["interpolation"]["groups"]:
            if D.g["edges"][i][:2] != (q, p):
                raise ValueError("interpolation pair identity differs from graph")
            eligible[i] = True
            v.role[i] = rec.ROLES.index(role)
        fitrole = np.isin(v.role, [
            rec.ROLES.index("training"), rec.ROLES.index("support")
        ])
        v.fit["a"] = np.flatnonzero(~D.within & fitrole & keep)
        v.val_idx = np.flatnonzero(
            eligible & keep & (v.role == rec.ROLES.index("validation"))
        )
        v.test_idx = np.flatnonzero(
            eligible & keep & (v.role == rec.ROLES.index("test"))
        )
        v.val_world = D.qw[D.qi[v.val_idx]]
        v.test_world = D.qw[D.qi[v.test_idx]]
        v.stest_idx = np.zeros(0, dtype=int)
        v.classes = {"interpolation_test": v.test_idx}

    if option.startswith("fwd_"):
        qr, pr = D.qref[D.qi], D.pref[D.pj]
        refs = qr | pr
        main = np.zeros(len(D.qi), bool)
        old = D.forward["fit"]
        main[old[~refs[old]]] = True
        fitrole = np.isin(D.role, [
            rec.ROLES.index("training"), rec.ROLES.index("support")
        ])
        calibration = ~D.within & refs & fitrole
        if option == "fwd_early":
            calibration &= (
                (~qr | (D.qt[D.qi] <= rec.FORWARD_TMAX))
                & (~pr | (D.pt[D.pj] <= rec.FORWARD_TMAX))
            )
        idx = np.flatnonzero((main | calibration) & keep)
        ctrl = mapfit.control_access(v, idx)
        ctrl &= (
            (D.qt <= rec.FORWARD_TMAX)
            | (D.qref & (option == "fwd_all"))
        )
        vm = keep[D.forward["val"]]
        v.forward = {
            "fit": idx,
            "val": D.forward["val"][vm],
            "val_world": D.forward["val_world"][vm],
            "tests": {
                k: ix[keep[ix]] for k, ix in D.forward["tests"].items()
            },
            "ctrl": ctrl,
        }
        v.fit["a"] = idx

    v.test_qworld = D.qw[D.qi[v.test_idx]]
    v.test_pworld = D.pw[D.pj[v.test_idx]]
    return v


def branches(v, option):
    if not option.startswith("fwd_"):
        name = "interpolation" if option == "interp" else "world_transfer"
        return {name: (v.test_idx, v.test_world)}
    out = {}
    for name, ix in v.forward["tests"].items():
        qw, pw = v.qw[v.qi[ix]], v.pw[v.pj[ix]]
        split = "test" if name == "intersection" else "train"
        tw = np.where(
            (qw >= 0) & (v.wsplit[np.maximum(qw, 0)] == split), qw, pw
        )
        out[name] = (ix, tw)
    return out


def target_table(D, indices, anchors, keep, causes):
    worlds = {
        w["id"]: {
            "treatment": w["treatment"], "block": w["block"],
            "scheduled": 0, "evaluable": 0,
            "excluded": {c: 0 for c in graph.EXCLUSION},
        } for w in D.g["worlds"]
    }
    bytime = Counter()
    for i, root in zip(indices.tolist(), anchors.tolist()):
        wid = D.worlds[root]
        row = worlds[wid]
        row["scheduled"] += 1
        cause = "available" if keep[i] else causes[i]
        if keep[i]:
            row["evaluable"] += 1
        else:
            row["excluded"][cause] += 1
        bytime[(wid, int(D.qt[D.qi[i]]), int(D.pt[D.pj[i]]), cause)] += 1
    return {
        "worlds": worlds,
        "by_world_endpoint_times_cause": [
            [*key, n] for key, n in sorted(bytime.items())
        ],
    }


def diagnostics(D, plan):
    out = {"synthetic": True, "cases": {}}
    allkeep = np.ones(len(D.qi), bool)
    original = {
        op: branches(view_for(D, plan, op, allkeep), op)
        for op in plan["options"]
    }
    for case in plan["cases"]:
        keep, attr, causes = mask_for(D, plan, case)
        procs = {}
        for op in plan["options"]:
            v = view_for(D, plan, op, keep)
            forward = op.startswith("fwd_")
            fit = v.forward["fit"] if forward else v.fit["a"]
            val = v.forward["val"] if forward else v.val_idx
            ctrl = v.forward["ctrl"] if forward else mapfit.control_access(v, fit)
            onq = np.bincount(v.qi[fit], minlength=v.nQ) > 0
            onp = np.bincount(v.pj[fit], minlength=v.nP) > 0
            cq, cp = mapfit.center_sets(v, onq, onp, plan["fit"]["center"])
            tests = branches(v, op)
            access = {
                "fit": fit.tolist(), "validation": val.tolist(),
                "controls": np.flatnonzero(ctrl).tolist(),
                "tests": {k: ix.tolist() for k, (ix, _) in tests.items()},
            }
            procs[op] = {
                "access_sha256": rqlib.canonical_sha(access),
                "fit_pairs": len(fit), "validation_targets": len(val),
                "controls": int(ctrl.sum()),
                "centering": {
                    "prey": [v.qkey[int(i)] for i in cq],
                    "predators": [v.pkey[int(i)] for i in cp],
                },
                "tests": {
                    k: {
                        "targets": len(ix),
                        "test_roots": len(np.unique(tw)),
                        "attrition": target_table(
                            D, *original[op][k], keep, causes
                        ),
                    } for k, (ix, tw) in tests.items()
                },
                "conditioning": {
                    f"rank{rank}": rec.conditioning(v, rank, "a", rank)
                    for rank in (1, 2, 3, 4)
                },
            }
        out["cases"][case] = {"attrition": attr, "procedures": procs}
    return clean(out)


def make_plan(D, graph_path, refs_path, namespace, fit, scenarios,
              reps, options, cases, allow_toy=False):
    if graph.layout_of(D.g["worlds"]) != "64":
        raise SystemExit("a registered 64-world layout is required")
    toy = bool(D.g.get("recovery_toy"))
    if toy and not allow_toy:
        raise SystemExit("toy graph requires --allow-toy")
    if not toy:
        if D.g.get("train_matchings") is not True:
            raise SystemExit("registered recovery requires training-only matchings")
        problems = graph.check_quotas(D.g)
        if problems:
            raise SystemExit("scheduled graph quota failure: " + "; ".join(problems))
    if len({e[:2] for e in D.g["edges"]}) != len(D.g["edges"]):
        raise SystemExit("duplicate ordered population pair")
    if not namespace or "\x1f" in namespace or reps < 1:
        raise SystemExit("nonempty namespace without unit separator; reps >=1")
    if not 0 <= fit["ranks"] <= 4:
        raise SystemExit("registered search is ranks 0..4")
    if any(rec.SCENARIOS[s].get("noiseless") for s in scenarios):
        raise SystemExit("use legacy recovery.py for noiseless numerical checks")
    seeds = {}
    for sc in scenarios:
        for rep in range(reps):
            seed = rqlib.derive_seed(namespace, "recovery", sc, rep)
            if seed in seeds:
                raise SystemExit(f"recovery seed collision: {seeds[seed]} and {(sc, rep)}")
            seeds[seed] = (sc, rep)
    a = argparse.Namespace(
        **fit, namespace=namespace, fitter="registered", options="a",
        ab_cap=-1, references=refs_path,
    )
    rec.resolve(a)
    return {
        "schema": PLAN_SCHEMA,
        "synthetic": True,
        "toy": toy,
        "noise_source": "scenario_planning_only",
        "namespace": namespace,
        "fit": {k: getattr(a, k) for k in FIT_KEYS},
        "scenarios": scenarios, "reps": reps,
        "options": options, "cases": cases,
        "criterion": CRITERION,
        "inputs": {
            "graph_file_sha256": rqlib.sha256_file(graph_path),
            "meta_file_sha256": rqlib.sha256_file(os.path.join(
                os.path.dirname(os.path.abspath(graph_path)), "graph.meta.json"
            )),
            "references_file_sha256": (
                rqlib.sha256_file(refs_path) if refs_path else None
            ),
        },
        "legacy_config": rec.run_config(a, rec.graph_identity(D.g)),
        "sources_sha256": source_hashes(),
        "runtime": {
            "python": list(sys.version_info[:3]), "numpy": np.__version__,
        },
        "recipe": recipes(D, namespace),
    }


def validate_references(path, g):
    """Validate actual panels and refsel provenance; hashes alone are not admissibility."""
    import refsel
    import sealing

    doc = rqlib.read_json(path)
    try:
        registry = g.get("registry") or {}
        refs = sealing.load_references(
            path, registry.get("uuids", {}),
            main_namespace=registry.get("namespace", g["namespace"]),
        )
        frames = {refsel.frame_of(t) for t in refsel.TIMES}
        for guild in ("RQ", "RP"):
            panel = [refs[f"{guild}:{k}"] for k in range(8)]
            if any(type(v["frame"]) is not int or v["frame"] not in frames for v in panel):
                raise ValueError("reference frame is not a registered candidate time")
            if len({v["world"] for v in panel}) < 3:
                raise ValueError("at least three distinct registered sentinels per guild required")
            if sum(v["frame"] <= 120_000_000 for v in panel) < 4:
                raise ValueError("at least four early references per guild required")
            if sum(v["frame"] >= 140_000_000 for v in panel) < 2:
                raise ValueError("at least two late references per guild required")
        receipt = doc.get("selection") or {}
        if (doc.get("namespace") != refsel.VALIDATION_NAMESPACE
                or receipt.get("refsel_schema") != refsel.SCHEMA
                or receipt.get("criterion_sha256") != rqlib.canonical_sha(refsel.CRITERION)):
            raise ValueError("registered reference selection provenance required")
        for key in ("design_sha256", "plan_sha256", "observations_sha256", "block_sha256"):
            if not sealing.SHA.fullmatch(str(receipt.get(key, ""))):
                raise ValueError(f"reference selection needs {key}")
        implementation = receipt.get("implementation") or {}
        if (not sealing.SHA.fullmatch(str(implementation.get("refsel_sha256", "")))
                or not isinstance(implementation.get("numpy"), str)
                or type(receipt.get("observations")) is not int
                or receipt["observations"] <= 0):
            raise ValueError("reference selection implementation/observation provenance required")
        binding = receipt.get("binding") or {}
        checked = receipt.get("studies_checked")
        if (not isinstance(checked, list) or not checked
                or any(not isinstance(s, dict) or not isinstance(s.get("path"), str)
                       or not s["path"] for s in checked)):
            raise ValueError("reference selection study registries missing or changed")
        # Reconstruct the candidate membership from the recorded availability, then use
        # the protected selector's binding checks (including all main/fork identities).
        # Selection permits registry overrides. Recheck the selection-time records;
        # the original planning binding remains historical provenance in the receipt.
        sent = binding.get("sentinels", [])
        avail = receipt.get("availability") or {}
        candidates = [(w, t) for w in sent for t in refsel.TIMES
                      if refsel.availability_reason(avail[w], w, t) is None]
        design = {
            "times": {t: refsel.frame_of(t) for t in refsel.TIMES},
            "worlds": {w: {"uuid": refsel.recipe(doc["namespace"], w)} for w in sent},
            "refsel": dict(receipt, sentinel_namespace=doc["namespace"],
                           sentinels=sent, candidates=candidates,
                           binding=dict(binding, studies=checked)),
        }
        studies = refsel.rebind(design)
        if sorted(checked, key=rqlib.canonical) != sorted(studies, key=rqlib.canonical):
            raise ValueError("reference selection study registries missing or changed")
        if registry and not any(
            graph.registry_binding(s["path"]) == registry
            for s in studies if s.get("kind") != "forks"
        ):
            raise ValueError("reference selection did not exclude this graph's study registry")
        allowed = {(w, refsel.frame_of(t)) for w, t in candidates}
        for slot, v in refs.items():
            if (v["world"], v["frame"]) not in allowed:
                raise ValueError(f"{slot}: not an available registered sentinel candidate")
            raw = doc["references"][slot]
            if raw.get("attempt") != (avail[v["world"]].get("attempt") or 0):
                raise ValueError(f"{slot}: selection attempt differs from availability")
            if not isinstance(v["archive"], str) or not v["archive"]:
                raise ValueError(f"{slot}: archive provenance required")
    except (sealing.SealError, refsel.RefselError, ValueError, KeyError, TypeError, OSError) as e:
        raise SystemExit(f"{path}: invalid actual reference panel: {e}") from e


def data_from(graph_path, refs_path):
    g = graph.load(graph_path)
    if refs_path:
        validate_references(refs_path, g)
    refs = rec.reference_times(refs_path)[0] if refs_path else None
    return rec.Data(g, refs)


@contextlib.contextmanager
def locked(directory):
    import fcntl
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, ".lock"), "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def freeze_text(files):
    return "".join(
        f"{rqlib.sha256_bytes(raw)}  {name}\n"
        for name, raw in sorted(files.items())
    ).encode("ascii")


def publish(directory, files):
    for name, raw in files.items():
        path = os.path.join(directory, name)
        if os.path.exists(path) and rqlib.read_bytes(path) != raw:
            raise SystemExit(f"{path}: other bytes; use a new directory")
    for name, raw in files.items():
        graph._publish_exclusive(os.path.join(directory, name), raw)


def prepare(a):
    options = csv(a.options, OPTIONS)
    cases = list(CASES) if a.cases == "all" else csv(a.cases, CASES)
    scenarios = csv(a.scenarios, rec.SCENARIOS)
    fa = argparse.Namespace(
        **{k: getattr(a, k) for k in FIT_KEYS},
        fitter="registered", options="a", ab_cap=-1,
    )
    rec.resolve(fa)
    fit = {k: getattr(fa, k) for k in FIT_KEYS}
    D = data_from(a.graph, a.references)
    plan = make_plan(
        D, a.graph, a.references, a.namespace, fit, scenarios,
        a.reps, options, cases, a.allow_toy,
    )
    files = {
        "plan.json": rqlib.canonical(plan),
        "diagnostics.json": rqlib.canonical(diagnostics(D, plan)),
    }
    files["FROZEN.sha256"] = freeze_text(files)
    with locked(a.out):
        publish(a.out, files)
    print(rqlib.sha256_bytes(files["FROZEN.sha256"]), " FROZEN.sha256")
    return 0


def read_frozen(directory):
    files = {
        name: rqlib.read_bytes(os.path.join(directory, name))
        for name in ("plan.json", "diagnostics.json")
    }
    if rqlib.read_bytes(os.path.join(directory, "FROZEN.sha256")) != freeze_text(files):
        raise SystemExit("frozen plan/diagnostics hash mismatch")
    plan = rqlib.read_json(os.path.join(directory, "plan.json"))
    if plan.get("schema") != PLAN_SCHEMA or not plan.get("synthetic"):
        raise SystemExit("not a recovery-extra frozen plan")
    if files["plan.json"] != rqlib.canonical(plan):
        raise SystemExit("plan is not canonical JSON")
    return plan


def verified(directory, graph_path, refs_path):
    plan = read_frozen(directory)
    D = data_from(graph_path, refs_path)
    expected = make_plan(
        D, graph_path, refs_path, plan["namespace"], plan["fit"],
        plan["scenarios"], plan["reps"], plan["options"], plan["cases"],
        allow_toy=plan["toy"],
    )
    if rqlib.canonical(expected) != rqlib.canonical(plan):
        raise SystemExit("graph, references, sources, runtime or frozen recipe changed")
    return D, plan


def forward(v, data, fit, seed, option):
    """Registered fitter/score on the paired all/early reference access masks."""
    F = v.forward if option.startswith("fwd_") else {
        "fit": v.fit["a"], "val": v.val_idx, "val_world": v.val_world,
        "ctrl": mapfit.control_access(v, v.fit["a"]),
    }
    idx, val = F["fit"], F["val"]
    out = {
        "procedure": "forward", "reference_policy": option,
        "fitter": "registered", "score": rec.SCORE,
        "fit_pairs": len(idx), "val_pairs": len(val),
        "controls": int(F["ctrl"].sum()), "candidates": [],
    }
    if not len(idx) or not len(val):
        return dict(
            out, available=False, success=False,
            reason="no fitting pairs" if not len(idx) else "no validation targets",
        )
    models = {}
    cands = [(0, 0.0)] + [
        (rank, lam) for rank in range(1, fit["ranks"] + 1)
        for lam in map(float, fit["lambdas"].split(","))
    ]
    for rank, lam in cands:
        t0 = time.time()
        model = rec.any_fit(
            "registered", v, idx, data, rank, lam, False,
            fit["iters"], seed, start=fit["start"], ctrl=F["ctrl"],
            basis=fit["basis"], embedding=fit["embedding"], center=fit["center"],
        )
        score = rec.scorer(v, data, model, idx, "registered")
        record = rec._cand_record(
            v, data, model, rank, lam, "registered", score,
            val, F["val_world"], t0,
            {"controls": model["controls"], "centering": model["center"]},
        )
        out["candidates"].append(record)
        models[(rank, lam)] = (model, score)
    best = max(out["candidates"], key=lambda c: c["val_lpd"])
    selected = (best["rank"], best["lambda"])
    out["selected"] = {
        "rank": selected[0], "lambda": selected[1], "start": best["start"],
    }
    unres_val = rec._flagged(*(
        c["integration"]["validation"] for c in out["candidates"]
    ))
    if unres_val:
        out["selected"]["selection_unresolved"] = True
    out["integration_unresolved"] = {"validation": unres_val}
    score1, score0 = models[selected][1], models[(0, 0.0)][1]
    for name, (ix, tw) in branches(v, option).items():
        roots = len(np.unique(tw))
        base = {"targets": len(ix), "test_roots": roots, "worlds": roots}
        if not len(ix):
            out[name] = dict(
                base, available=False, decision_available=False, success=False,
                reason=f"fewer than {rec.MIN_TEST_ROOTS} contributing test roots",
            )
            continue
        if unres_val:
            out[name] = dict(
                base, available=False, success=False,
                integration_unresolved=unres_val,
                reason=rec._unresolved_why(unres_val, "validation"),
            )
            continue
        i1, i0 = {}, {}
        c1, g1 = score1(ix, i1)
        c0, g0 = score0(ix, i0)
        unresolved = rec._flagged(i1, *([i0] if selected != (0, 0.0) else []))
        if unresolved:
            out[name] = dict(
                base, available=False, success=False,
                integration={"selected": i1, "rank0": i0},
                integration_unresolved=unresolved,
                reason=rec._unresolved_why(unresolved, name),
            )
            continue
        if roots < rec.MIN_TEST_ROOTS:
            ws = np.unique(tw)
            per = [float((c1 - c0)[tw == w].mean()) for w in ws]
            gper = [float((g1 - g0)[tw == w].mean()) for w in ws]
            out[name] = dict(
                base, available=False, decision_available=False, success=False,
                descriptive=True, test_improvement=float(np.mean(per)),
                per_world=per, per_world_ids=[v.worlds[int(w)] for w in ws],
                test_improvement_gauss=float(np.mean(gper)),
                integration={"selected": i1, "rank0": i0},
                integration_unresolved=0,
                reason=f"fewer than {rec.MIN_TEST_ROOTS} contributing test roots",
            )
            continue
        qw, pw = v.qw[v.qi[ix]], v.pw[v.pj[ix]]
        bseed = seed + 11 + len(name)
        mean, lb, per = rec.crossed_lb(
            c1 - c0, tw, qw, pw, np.random.default_rng(bseed)
        )
        gmean, glb, _ = rec.crossed_lb(
            g1 - g0, tw, qw, pw, np.random.default_rng(bseed)
        )
        out[name] = dict(
            base, available=True, decision_available=True,
            success=bool(selected[0] > 0 and lb > 0),
            test_improvement=mean, test_lb=lb, per_world=per,
            integration={"selected": i1, "rank0": i0},
            integration_unresolved=0,
            test_improvement_gauss=gmean, test_lb_gauss=glb,
        )
    ft = out["forward_transfer"] if option.startswith("fwd_") else out[next(iter(branches(v, option)))]
    out["decision"] = {
        "available": bool(ft.get("available")),
        "reason": ft.get("reason"),
        "selection_unresolved": bool(unres_val),
        "integration_unresolved": max(
            unres_val, int(ft.get("integration_unresolved", 0))
        ),
    }
    out["success"] = ft.get("success", False)
    out["test_improvement"] = ft.get("test_improvement")
    out["test_lb"] = ft.get("test_lb")
    return out


def evaluate(v, data, plan, seed, option):
    fit = plan["fit"]
    if option.startswith("fwd_"):
        return forward(v, data, fit, seed, option)
    if (len(np.unique(v.test_world)) == 1
            and len(v.fit["a"]) and len(v.val_idx)):
        out = forward(v, data, fit, seed, option)
        branch = out[next(iter(branches(v, option)))]
        out.update(branch, procedure=option)
        out["per_test_world"] = branch.get("per_world", [])
        return out
    return rec.procedure(
        v, data, "a", fit["ranks"],
        list(map(float, fit["lambdas"].split(","))),
        fit["iters"], seed, fitter="registered", start=fit["start"],
        basis=fit["basis"], embedding=fit["embedding"], center=fit["center"],
    )


def tasks(plan):
    return [
        (case, scenario, rep)
        for case in plan["cases"]
        for scenario in plan["scenarios"]
        for rep in range(plan["reps"])
    ]


def task_name(task):
    case, scenario, rep = task
    return f"{case}.{scenario}.{rep:03d}.json"


def observation_hashes(data):
    out = {}
    for key in ("eta", "inter", "cnt", "z", "s", "s0"):
        value = np.ascontiguousarray(data[key], dtype="<f8")
        out[key] = {
            "shape": list(value.shape), "dtype": "<f8",
            "sha256": rqlib.sha256_bytes(value.tobytes(order="C")),
        }
    return out


def retained_energy(D, data, keep):
    if not keep.any():
        return None
    v = copy.copy(D)
    v.qi, v.pj = D.qi[keep], D.pj[keep]
    inter, eta = data["inter"][keep], data["eta"][keep]
    den = float(np.var(eta))
    if not den:
        return None
    residual = inter - rec.additive_projection(v, inter)
    return float(np.var(residual) / den)


def one(a):
    D, plan = verified(a.dir, a.graph, a.references)
    expected = {task_name(t): t for t in tasks(plan)}
    if a.task not in expected:
        raise SystemExit("task is not in the frozen schedule")
    case, scenario, rep = expected[a.task]
    seed = rqlib.derive_seed(plan["namespace"], "recovery", scenario, rep)
    data = rec.simulate(D, rec.SCENARIOS[scenario], seed)
    keep, _, _ = mask_for(D, plan, case)
    result = {
        "schema": RESULT_SCHEMA,
        "plan_sha256": rqlib.canonical_sha(plan),
        "case": case, "scenario": scenario, "rep": rep, "seed": seed,
        "noise_source": "scenario_planning_only",
        "observations": observation_hashes(data),
        "scheduled_energy": data["energy"],
        "retained_additive_projection_energy": retained_energy(D, data, keep),
        "options": {
            op: evaluate(view_for(D, plan, op, keep), data, plan, seed, op)
            for op in plan["options"]
        },
    }
    result = clean(result)
    result["body_sha256"] = rqlib.canonical_sha(result)
    directory = os.path.join(a.dir, "results")
    os.makedirs(directory, exist_ok=True)
    graph._publish_exclusive(
        os.path.join(directory, a.task), rqlib.canonical(result)
    )
    return 0


def read_results(directory, plan):
    expected = {task_name(t): t for t in tasks(plan)}
    found = {}
    result_dir = os.path.join(directory, "results")
    if not os.path.isdir(result_dir):
        return found
    for name in sorted(os.listdir(result_dir)):
        if not name.endswith(".json"):
            continue
        if name not in expected:
            raise SystemExit(f"stray recovery result: {name}")
        value = rqlib.read_json(os.path.join(result_dir, name))
        body = {k: v for k, v in value.items() if k != "body_sha256"}
        case, scenario, rep = expected[name]
        seed = rqlib.derive_seed(plan["namespace"], "recovery", scenario, rep)
        if (
            value.get("schema") != RESULT_SCHEMA
            or value.get("plan_sha256") != rqlib.canonical_sha(plan)
            or (value.get("case"), value.get("scenario"), value.get("rep"))
            != (case, scenario, rep)
            or value.get("seed") != seed
            or set(value.get("options", {})) != set(plan["options"])
            or value.get("body_sha256") != rqlib.canonical_sha(body)
        ):
            raise SystemExit(f"wrong identity, configuration or body hash: {name}")
        found[name] = value
    return found


def artifact_index(directory):
    files = {}
    for name in ("plan.json", "diagnostics.json", "FROZEN.sha256"):
        files[name] = rqlib.read_bytes(os.path.join(directory, name))
    rd = os.path.join(directory, "results")
    if os.path.isdir(rd):
        for name in sorted(os.listdir(rd)):
            if name.endswith(".json"):
                files["results/" + name] = rqlib.read_bytes(os.path.join(rd, name))
    rqlib.write_durable(
        os.path.join(directory, "ARTIFACTS.sha256"), freeze_text(files)
    )


@contextlib.contextmanager
def termination_signals():
    """Unwind through worker reaping while the directory lock is still held."""
    signals = (signal.SIGTERM, signal.SIGINT)
    previous = {s: signal.getsignal(s) for s in signals}

    def terminate(signum, _frame):
        for s in signals:
            signal.signal(s, signal.SIG_IGN)
        raise SystemExit(128 + signum)

    try:
        for s in signals:
            signal.signal(s, terminate)
        yield
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


def run(a):
    if a.jobs not in (1, 2):
        raise SystemExit("--jobs must be 1 or 2")
    with locked(a.dir), termination_signals():
        _, plan = verified(a.dir, a.graph, a.references)
        found = read_results(a.dir, plan)
        pending = [task_name(t) for t in tasks(plan) if task_name(t) not in found]
        logdir = os.path.join(a.dir, "logs")
        os.makedirs(logdir, exist_ok=True)
        env = dict(os.environ)
        env.update({name: "1" for name in THREAD_VARS})
        running = []
        failed = False
        try:
            while pending or running:
                while pending and len(running) < a.jobs:
                    task = pending.pop(0)
                    cmd = [
                        sys.executable, "-I", "-B", os.path.abspath(__file__),
                        "one", "--dir", a.dir, "--graph", a.graph, "--task", task,
                    ]
                    if a.references:
                        cmd += ["--references", a.references]
                    with open(os.path.join(logdir, task[:-5] + ".log"), "ab") as log:
                        # Do not deliver termination between spawning and tracking a child.
                        blocked = signal.pthread_sigmask(
                            signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT}
                        )
                        try:
                            if sys.platform.startswith("linux") and rqlib._LIBC is None:
                                raise SystemExit("Linux worker parent-death protection unavailable")
                            death_guard = rqlib.death_signal()

                            def worker_guard():
                                death_guard()
                                signal.pthread_sigmask(signal.SIG_SETMASK, blocked)

                            process = subprocess.Popen(
                                cmd, env=env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT,
                                preexec_fn=worker_guard,
                                restore_signals=True,
                            )
                            running.append((process, task))
                            # Popen returns only after preexec installed PDEATHSIG
                            # and exec succeeded. A child appearing in /proc can
                            # still be stopped before either has happened.
                            print(f"started {task}: guarded pid {process.pid}", flush=True)
                        finally:
                            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
                time.sleep(0.1)
                for item in list(running):
                    rc = item[0].poll()
                    if rc is not None:
                        running.remove(item)
                        failed |= rc != 0
                        print(f"{item[1]}: exit {rc}", flush=True)
        finally:
            for process, _ in running:
                if process.poll() is None:
                    process.terminate()
            for process, _ in running:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        read_results(a.dir, plan)
        artifact_index(a.dir)
    return int(failed)


def result_branch(value, option, branch):
    if value is None:
        return {"available": False, "success": False, "reason": "missing task"}
    out = value["options"][option]
    if option.startswith("fwd_"):
        row = dict(out.get(branch) or {
            "available": False, "success": False,
            "reason": out.get("reason", "unavailable forward comparison"),
        })
        row["selected"] = out.get("selected")
        return row
    return dict(out, available=rec._decided(out))


def summarize(directory):
    plan = read_frozen(directory)
    found = read_results(directory, plan)
    cells = []
    for case in plan["cases"]:
        for scenario in plan["scenarios"]:
            for option in plan["options"]:
                names = (
                    ("forward_transfer", "intersection")
                    if option.startswith("fwd_")
                    else ("interpolation",) if option == "interp"
                    else ("world_transfer",)
                )
                for branch in names:
                    values = [
                        found.get(task_name((case, scenario, rep)))
                        for rep in range(plan["reps"])
                    ]
                    rows = [result_branch(v, option, branch) for v in values]
                    decided = [r for r in rows if r.get("available")]
                    successes = sum(
                        bool(r.get("success")) for r in decided
                    )
                    ranks = Counter(
                        str(r["selected"]["rank"]) for r in decided
                        if r.get("selected")
                    )
                    bounds = [
                        r.get("test_lb") for r in decided
                        if isinstance(r.get("test_lb"), (int, float))
                        and math.isfinite(r["test_lb"])
                    ]
                    cell = {
                        "case": case, "scenario": scenario,
                        "option": option, "branch": branch,
                        "datasets": plan["reps"],
                        "completed": sum(v is not None for v in values),
                        "missing": sum(v is None for v in values),
                        "successes": successes,
                        **rec._rates(successes, plan["reps"], len(decided)),
                        "selected_ranks": dict(sorted(ranks.items())),
                        "median_finite_test_lb": rec._median(bounds),
                        "reasons": dict(Counter(
                            r.get("reason") or
                            (r.get("decision") or {}).get("reason") or "unavailable"
                            for r in rows if not r.get("available")
                        )),
                    }
                    if not option.startswith("fwd_"):
                        primary = [
                            (v["options"][option].get("selected_primary") or {})
                            if v else {} for v in values
                        ]
                        pd = [r for r in primary if r.get("available", False)]
                        pk = sum(bool(r.get("success")) for r in pd)
                        cell["restricted_ranks"] = {
                            **rec._rates(pk, plan["reps"], len(pd)),
                            "successes": pk,
                        }
                    cells.append(cell)
    applicable = (
        not plan["toy"] and plan["reps"] == 20
        and "intact" in plan["cases"] and "a" in plan["options"]
        and set(rec.SETS["main"]).issubset(plan["scenarios"])
        and plan["fit"] == {
            "ranks": 4, "lambdas": "0.01,0.02,0.05,0.2",
            "iters": 30, "start": "both", "basis": 6,
            "embedding": "shared", "center": "references",
        }
    )
    checks = {}
    if applicable:
        for scenario in CRITERION["scenarios"]:
            cell = next(c for c in cells if (
                c["case"], c["scenario"], c["option"], c["branch"]
            ) == ("intact", scenario, "a", "world_transfer"))
            checks[scenario] = {
                "successes": cell["successes"], "datasets": cell["datasets"],
                "wilson95": cell["wilson95"],
                "pass": cell["completed"] == 20 and cell["successes"] >= 16,
            }
    return {
        "schema": SUMMARY_SCHEMA,
        "plan_sha256": rqlib.canonical_sha(plan),
        "synthetic": True, "toy": plan["toy"],
        "noise_source": plan["noise_source"],
        "scheduled_tasks": len(tasks(plan)),
        "completed_tasks": len(found),
        "complete": len(found) == len(tasks(plan)),
        "cells": cells,
        "criterion": {
            "applicable": applicable, "checks": checks,
            "core_pass": (
                all(c["pass"] for c in checks.values()) if checks else None
            ),
            "scope": CRITERION,
            "sealing": "no automatic sealing or launch authorization",
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--graph", required=True)
    p.add_argument("--references")
    p.add_argument("--namespace", default="rq2026-d6d7-recovery-v1")
    p.add_argument("--options", default="a,interp,fwd_all,fwd_early")
    p.add_argument("--cases", default="intact")
    p.add_argument("--scenarios", default=",".join(rec.SETS["main"]))
    p.add_argument("--reps", type=int, default=20)
    p.add_argument("--ranks", type=int, default=4)
    p.add_argument("--lambdas", default=None)
    p.add_argument("--iters", type=int, default=None)
    p.add_argument("--start", choices=("both", "warm", "cold"), default=None)
    p.add_argument("--basis", type=int, choices=(4, 6, 8), default=None)
    p.add_argument("--embedding", choices=("shared", "separate"), default=None)
    p.add_argument("--center", choices=("references", "train_c"), default=None)
    p.add_argument("--allow-toy", action="store_true")
    p.add_argument("--out", required=True)
    for name in ("run", "one"):
        p = sub.add_parser(name)
        p.add_argument("--dir", required=True)
        p.add_argument("--graph", required=True)
        p.add_argument("--references")
        if name == "run":
            p.add_argument("--jobs", type=int, choices=(1, 2), default=2)
        else:
            p.add_argument("--task", required=True)
    p = sub.add_parser("summarize")
    p.add_argument("--dir", required=True)
    p.add_argument("--out")
    a = parser.parse_args(argv)
    try:
        if a.cmd == "prepare":
            return prepare(a)
        if a.cmd == "run":
            return run(a)
        if a.cmd == "one":
            return one(a)
        result = clean(summarize(a.dir))
        raw = rqlib.canonical(result)
        if a.out:
            rqlib.write_durable(a.out, raw)
        print(raw.decode("ascii"), end="")
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError, graph.GraphError) as error:
        print(f"recovery_extra.py {a.cmd}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

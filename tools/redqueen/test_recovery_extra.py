#!/usr/bin/env python3
"""Recovery extension tests; numpy is required when RQ_REQUIRE_NUMPY=1."""
from __future__ import annotations

import argparse
import copy
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
try:
    import numpy as np
except ImportError:
    np = None

if np is None and os.environ.get("RQ_REQUIRE_NUMPY"):
    raise SystemExit("RQ_REQUIRE_NUMPY is set, but numpy cannot be imported")

if np is not None:
    import recovery_extra as X
    import recovery as R
    import graph
    import map as M
    import rqlib
    import refsel
    import sealing


def reference_panel(root):
    """Synthetic selection receipt with real registry/identity validation, no grid claim."""
    ns = refsel.VALIDATION_NAMESPACE
    sent = [f"sentinel-{k}" for k in range(4)]
    vp = os.path.join(root, "validation.json")
    mp = os.path.join(root, "study.json")
    fp = os.path.join(root, "forks.json")
    rqlib.write_json_durable(vp, {
        "schema": refsel.WORLDS_SCHEMA, "namespace": ns,
        "worlds": [{"id": w, "uuid": refsel.recipe(ns, w), "treatment": "C"} for w in sent],
    })
    rqlib.write_json_durable(mp, {
        "namespace": "rq-extra-study", "worlds": [
            dict(w, uuid=refsel.recipe("rq-extra-study", w["id"])) for w in graph.synthetic_worlds()
        ],
    })
    rqlib.write_json_durable(fp, {"worlds": []})
    studies = refsel.study_exclusion([mp], fp)[2]
    avail = {w: {
        "uuid": refsel.recipe(ns, w), "attempt": 0, "burn_in": 0,
        "archived": [refsel.frame_of(t) for t in refsel.TIMES],
    } for w in sent}
    ts = (0, 20, 60, 100, 140, 140, 180, 200)
    return {
        "schema": R.REFS_SCHEMA, "namespace": ns,
        "references": {
            f"{guild}:{k}": {
                "world": sent[k % 4], "frame": 1 if t == 0 else t * 1_000_000,
                "uuid": refsel.recipe(ns, sent[k % 4]),
                "snapshot": sealing.snapshot_uuid(refsel.recipe(ns, sent[k % 4]), 1 if t == 0 else t * 1_000_000),
                "archive": "synthetic-not-an-engine-archive", "sha256": "a" * 64, "attempt": 0,
            } for guild in ("RQ", "RP") for k, t in enumerate(ts)
        },
        "selection": {
            "refsel_schema": refsel.SCHEMA,
            "criterion_sha256": rqlib.canonical_sha(refsel.CRITERION),
            **{k: "b" * 64 for k in ("design_sha256", "plan_sha256", "observations_sha256", "block_sha256")},
            "observations": 1, "availability": avail,
            "availability_sha256": rqlib.canonical_sha(avail), "omitted": [],
            "implementation": refsel.implementation(), "studies_checked": studies,
            "binding": {"namespace": ns, "sentinels": sent, "registry": vp,
                        "registry_sha256": rqlib.sha256_file(vp), "studies": studies},
        },
    }


def toy():
    worlds = graph.synthetic_worlds()
    split, fork, intensive, hold = graph.splits("rq-extra-toy64", worlds)
    cs = sorted(w["id"] for w in worlds if w["treatment"] == "C")
    train = [w for w in cs if split[w] == "train"]
    times = (0, 50, 100, 101, 150, 190)
    edges = []
    seen = set()

    def status(w, t):
        return split[w] if split[w] != "train" else hold.get((w, t), "train")

    def add(q, p, family, role):
        if (q, p) not in seen:
            seen.add((q, p))
            edges.append((q, p, family, role, "short"))

    for q in range(8):
        for p in range(8):
            add(f"RQ:{q}", f"RP:{p}", "ref_grid", "training")

    for w in worlds:
        wid = w["id"]
        for t in times:
            role = "training" if status(wid, t) == "train" else "support"
            for k in (0, 2, 5, 7):
                add(
                    graph.Q(wid, t), f"RP:{k}",
                    "ref_prey" if w["treatment"] == "C" else "ref_ab", role,
                )
                if w["treatment"] == "C":
                    add(f"RQ:{k}", graph.P(wid, t), "ref_pred", role)
            opponents = [p for p in train if p != wid][:2]
            for p in opponents:
                states = (status(wid, t), status(p, t))
                role = (
                    "test" if "test" in states else
                    "validation" if "val" in states else "training"
                )
                add(
                    graph.Q(wid, t), graph.P(p, t),
                    "cross" if w["treatment"] == "C" else "ab_to_c", role,
                )

    return {
        "schema": graph.GRAPH_SCHEMA,
        "namespace": "rq-extra-toy64",
        "recovery_toy": True,
        "train_matchings": False,
        "topups": {"snapshot": 0, "ab": 0, "ab_mode": "fitting"},
        "lag_probe": 0,
        "worlds": worlds, "split": split, "fork": fork, "intensive": intensive,
        "holdout": {f"{w}:{t}": s for (w, t), s in sorted(hold.items())},
        "edges": edges,
    }


@unittest.skipIf(np is None, "numpy unavailable")
class TestRecoveryExtra(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.gdir = os.path.join(self.root, "graph")
        graph.write(toy(), self.gdir)
        self.gpath = os.path.join(self.gdir, "graph.jsonl.gz")
        self.refs = os.path.join(self.root, "references.json")
        # Exactly four early references; slot 4 is late.
        rqlib.write_json_durable(self.refs, reference_panel(self.root))
        self.D = X.data_from(self.gpath, self.refs)
        self.fit = {
            "ranks": 1, "lambdas": "0.05", "iters": 2, "start": "warm",
            "basis": 4, "embedding": "shared", "center": "references",
        }
        self.plan = X.make_plan(
            self.D, self.gpath, self.refs, "rq-extra-tests",
            self.fit, ["r0"], 1, list(X.OPTIONS), list(X.CASES), True,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def command(self, *args, ok=True):
        cp = subprocess.run(
            [sys.executable, "-I", "-B", X.__file__, *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        if ok:
            self.assertEqual(cp.returncode, 0, cp.stdout[-8000:])
        else:
            self.assertNotEqual(cp.returncode, 0, cp.stdout)
        return cp

    def prepared(self, directory, cases="all", options=None):
        args = [
            "prepare", "--graph", self.gpath, "--references", self.refs,
            "--namespace", "rq-extra-tests", "--allow-toy",
            "--cases", cases, "--scenarios", "r0", "--reps", "1",
            "--ranks", "1", "--lambdas", "0.05", "--iters", "2",
            "--start", "warm", "--basis", "4", "--out", directory,
        ]
        if options:
            args += ["--options", options]
        self.command(*args)

    def test_production_requires_training_matchings(self):
        # The supported legacy configuration really passes the legacy quota check.
        g = graph.build("rq-no-matchings", train_matchings=False,
                        snapshot_topup=0, ab_topup=0, lag_probe=0)
        self.assertEqual(graph.check_quotas(g), [])
        self.assertFalse(any(e[2] == "train_match" for e in g["edges"]))
        directory = os.path.join(self.root, "no-matchings")
        graph.write(g, directory)
        with self.assertRaisesRegex(SystemExit, "requires training-only matchings"):
            X.make_plan(R.Data(g), os.path.join(directory, "graph.jsonl.gz"), None,
                        "rq-refusal", self.fit, ["r0"], 20, ["a"], ["intact"])
        # A true flag alone does not bypass the existing quota check.
        g["train_matchings"] = True
        with self.assertRaisesRegex(SystemExit, "train_match"):
            X.make_plan(R.Data(g), self.gpath, None, "rq-refusal", self.fit,
                        ["r0"], 20, ["a"], ["intact"])

    def test_actual_reference_panel_constraints_and_provenance(self):
        original = rqlib.read_json(self.refs)

        def assign(doc, slot, world=None, frame=None):
            v = doc["references"][slot]
            if world is not None:
                v["world"] = world
                v["uuid"] = refsel.recipe(doc["namespace"], world)
            if frame is not None:
                v["frame"] = frame
            v["snapshot"] = sealing.snapshot_uuid(v["uuid"], v["frame"])

        bad = []
        for fr in (1, 100_000_000):
            doc = copy.deepcopy(original)
            for slot in doc["references"]:
                assign(doc, slot, "sentinel-0", fr)
            # Reproduce the review: these assignments pass the protected reader.
            rqlib.write_json_durable(self.refs, doc)
            self.assertEqual(len(R.reference_times(self.refs)[0]["RQ"]), 8)
            bad.append(("same snapshot in one guild", doc))
        doc = copy.deepcopy(original)
        for k, fr in enumerate((1, 20, 60, 100, 140, 140, 180, 200)):
            assign(doc, f"RQ:{k}", f"sentinel-{k % 2}", fr if fr == 1 else fr * 1_000_000)
        bad.append(("three distinct", doc))
        for label, k, fr in (("four early", 3, 180_000_000), ("two late", 5, 120_000_000)):
            doc = copy.deepcopy(original)
            if label == "two late":
                for j in (4, 6):
                    assign(doc, f"RQ:{j}", frame=120_000_000)
            assign(doc, f"RQ:{k}", frame=fr)
            bad.append((label, doc))
        doc = copy.deepcopy(original)
        assign(doc, "RQ:0", frame=30_000_000)
        bad.append(("candidate time", doc))
        doc = copy.deepcopy(original)
        doc.pop("selection")
        bad.append(("selection provenance", doc))
        doc = copy.deepcopy(original)
        assign(doc, "RQ:0", "not-a-sentinel")
        bad.append(("registered sentinel candidate", doc))
        doc = copy.deepcopy(original)
        doc["references"]["RQ:0"]["uuid"] = refsel.recipe("rq-extra-study", "C01")
        bad.append(("uuid is not sentinel", doc))
        doc = copy.deepcopy(original)
        doc["selection"]["plan_sha256"] = None
        bad.append(("plan_sha256", doc))
        doc = copy.deepcopy(original)
        doc["selection"]["availability"]["sentinel-0"]["archived"].remove(1)
        doc["selection"]["availability_sha256"] = rqlib.canonical_sha(doc["selection"]["availability"])
        doc["selection"]["omitted"] = [{"world": "sentinel-0", "time": "F1", "reason": "not archived"}]
        bad.append(("registered sentinel candidate", doc))
        for why, doc in bad:
            with self.subTest(why=why):
                rqlib.write_json_durable(self.refs, doc)
                with self.assertRaisesRegex(SystemExit, why):
                    X.data_from(self.gpath, self.refs)
        # 120M is an allowed early boundary, and assumed-slot planning stays available.
        assign(original, "RQ:3", frame=120_000_000)
        rqlib.write_json_durable(self.refs, original)
        D = X.data_from(self.gpath, self.refs)
        self.assertEqual(D.ref_times["RQ"][3], 120)
        self.assertIsNotNone(X.data_from(self.gpath, None))

    def test_reference_study_exclusion_and_registry_binding(self):
        doc = rqlib.read_json(self.refs)
        binding = doc["selection"]["binding"]
        for kind in ("main", "forks", "namespace", "changed"):
            with self.subTest(kind=kind):
                path = next(s["path"] for s in binding["studies"]
                            if (s.get("kind") == "forks") == (kind == "forks"))
                raw = rqlib.read_bytes(path)
                reg = rqlib.read_json(path)
                if kind == "namespace":
                    reg["namespace"] = refsel.VALIDATION_NAMESPACE
                else:
                    reg["worlds"].append({"id": "collision", "uuid": (
                        doc["references"]["RQ:0"]["uuid"] if kind != "changed" else "changed"
                    )})
                rqlib.write_json_durable(path, reg)
                with self.assertRaisesRegex(SystemExit, "study identity|validation namespace|registries missing or changed"):
                    X.data_from(self.gpath, self.refs)
                rqlib.write_durable(path, raw)
        g = copy.deepcopy(self.D.g)
        g["registry"] = {"namespace": "another-study", "uuids": {}}
        with self.assertRaisesRegex(SystemExit, "this graph's study registry"):
            X.validate_references(self.refs, g)

    def test_selector_registry_overrides_and_integrity(self):
        # Use the unchanged selector's full plan, bound rows, observations and
        # selection path: synthetic receipts alone missed the review counterexample.
        import test_refsel as T

        root = os.path.join(self.root, "selector")
        os.makedirs(root)
        f = T.files(root)
        main = os.path.join(self.root, "study.json")
        design = refsel.make_design(
            T.block(f["vdir"]), [f["t.json"]], f["ages.json"], [f["worlds.json"]],
            validation_dir=f["vdir"], main_registries=[main, f["main"]], forks=f["forks"],
        )
        rows = T.final_rows(design)
        obs = T.simulate(rows, seed=3)
        main_copy, fork_copy = (os.path.join(root, n) for n in ("main-copy.json", "fork-copy.json"))
        shutil.copyfile(main, main_copy)
        shutil.copyfile(f["forks"], fork_copy)
        history = copy.deepcopy(design["refsel"]["binding"])
        g = dict(self.D.g, registry=graph.registry_binding(main))
        for label, mains, forks in (
            ("unchanged", [main, f["main"]], f["forks"]),
            ("reordered mains", [f["main"], main], f["forks"]),
            ("copied main", [main_copy, f["main"]], f["forks"]),
            ("copied main and forks", [main_copy, f["main"]], fork_copy),
        ):
            with self.subTest(override=label):
                studies = refsel.rebind(design, mains, forks)
                doc, _ = refsel.select(obs, design, rows, studies=studies,
                                       plan_sha=rqlib.canonical_sha(rows))
                self.assertEqual(doc["selection"]["binding"], history)
                self.assertEqual(doc["selection"]["studies_checked"], studies)
                if label != "unchanged":
                    self.assertNotEqual(history["studies"], studies)
                raw = rqlib.canonical(doc)
                rqlib.write_durable(self.refs, raw)
                X.validate_references(self.refs, g)  # includes graph-registry exclusion
                D = X.data_from(self.gpath, self.refs)
                X.make_plan(D, self.gpath, self.refs, "rq-selected-panel", self.fit,
                            ["r0"], 1, ["a"], ["intact"], True)
                self.assertEqual(rqlib.canonical(doc), raw)
                self.assertEqual(rqlib.read_bytes(self.refs), raw)
                self.assertEqual(design["refsel"]["binding"], history)

        # Historical study paths need not stay accessible after a supported override.
        os.unlink(main)
        os.unlink(f["forks"])
        X.validate_references(self.refs, g)
        # Reordering all recorded checks, including forks, changes no binding.
        doc["selection"]["studies_checked"].reverse()
        rqlib.write_json_durable(self.refs, doc)
        X.validate_references(self.refs, g)

        # Current selection records must still be accessible, byte-bound and disjoint.
        for path in (main_copy, fork_copy):
            raw = rqlib.read_bytes(path)
            for change in ("missing", "bytes", "identity"):
                with self.subTest(registry=path, change=change):
                    if change == "missing":
                        os.unlink(path)
                    elif change == "bytes":
                        rqlib.write_durable(path, raw + b"\n")
                    else:
                        reg = rqlib.read_json(path)
                        reg["worlds"].append({"id": "collision", "uuid":
                                              doc["references"]["RQ:0"]["uuid"]})
                        rqlib.write_json_durable(path, reg)
                    with self.assertRaisesRegex(SystemExit, "invalid actual reference panel"):
                        X.validate_references(self.refs, g)
                    rqlib.write_durable(path, raw)
        for checked in (None, [], [None], [{"sha256": "a" * 64}]):
            bad = copy.deepcopy(doc)
            bad["selection"]["studies_checked"] = checked
            rqlib.write_json_durable(self.refs, bad)
            with self.assertRaisesRegex(SystemExit, "study registries missing or changed"):
                X.validate_references(self.refs, g)
        # Excluding only unrelated registries cannot replace the graph's study check.
        bad = copy.deepcopy(doc)
        bad["selection"]["studies_checked"] = refsel.study_exclusion([f["main"]], fork_copy)[2]
        rqlib.write_json_durable(self.refs, bad)
        with self.assertRaisesRegex(SystemExit, "this graph's study registry"):
            X.validate_references(self.refs, g)

    def test_selector_omitted_fork_record_keeps_historical_fallback(self):
        # Both round-3 reviews delete only the fork check from a real selector
        # receipt. Main records still match; the historical fork remains required.
        import test_refsel as T

        root = os.path.join(self.root, "selector")
        os.makedirs(root)
        f = T.files(root)
        main = os.path.join(self.root, "study.json")
        design = refsel.make_design(
            T.block(f["vdir"]), [f["t.json"]], f["ages.json"], [f["worlds.json"]],
            validation_dir=f["vdir"], main_registries=[main, f["main"]], forks=f["forks"],
        )
        rows = T.final_rows(design)
        studies = refsel.rebind(design)
        doc, _ = refsel.select(T.simulate(rows, seed=3), design, rows,
                               studies=studies, plan_sha=rqlib.canonical_sha(rows))
        history = copy.deepcopy(doc["selection"]["binding"])
        g = dict(self.D.g, registry=graph.registry_binding(main))
        rqlib.write_json_durable(self.refs, doc)
        X.validate_references(self.refs, g)
        bad = copy.deepcopy(doc)
        bad["selection"]["studies_checked"] = [
            s for s in studies if s.get("kind") != "forks"
        ]
        self.assertEqual(len(bad["selection"]["studies_checked"]), 2)
        self.assertEqual(bad["selection"]["binding"], history)
        raw = rqlib.read_bytes(f["forks"])
        for change in ("unchanged", "missing", "bytes", "identity"):
            with self.subTest(fork=change):
                try:
                    if change == "missing":
                        os.unlink(f["forks"])
                    elif change == "bytes":
                        rqlib.write_durable(f["forks"], raw + b"\n")
                    elif change == "identity":
                        reg = rqlib.read_json(f["forks"])
                        reg["worlds"].append({"id": "collision", "uuid":
                                              doc["references"]["RQ:0"]["uuid"]})
                        rqlib.write_json_durable(f["forks"], reg)
                    rqlib.write_json_durable(self.refs, bad)
                    with self.assertRaisesRegex(SystemExit, "invalid actual reference panel"):
                        X.validate_references(self.refs, g)
                    self.assertEqual(rqlib.read_json(self.refs), bad)
                    self.assertEqual(design["refsel"]["binding"], history)
                finally:
                    rqlib.write_durable(f["forks"], raw)

    def test_partition_and_primary_immutability(self):
        D = self.D
        role = D.role.copy()
        fit = D.fit["a"].copy()
        val = D.val_idx.copy()
        test = D.test_idx.copy()
        recipe = X.recipes(D, "rq-extra-tests")
        self.assertEqual(recipe, X.recipes(D, "rq-extra-tests"))
        groups = recipe["interpolation"]["groups"]
        n = len(groups)
        counts = recipe["interpolation"]["counts"]
        self.assertEqual(counts, {
            "training": 8 * n // 10, "validation": n // 10,
            "test": n - 8 * n // 10 - n // 10,
        })
        keep = np.ones(len(D.qi), bool)
        v = X.view_for(D, self.plan, "interp", keep)
        fs, vs, ts = map(set, (v.fit["a"], v.val_idx, v.test_idx))
        self.assertFalse(fs & vs or fs & ts or vs & ts)
        self.assertEqual(len({(q, p) for _, q, p, _ in groups}), n)
        self.assertFalse(D.within[v.fit["a"]].any())
        for i, _, _, assigned in groups:
            self.assertEqual(v.role[i], R.ROLES.index(assigned))
        for actual, original in (
            (D.role, role), (D.fit["a"], fit),
            (D.val_idx, val), (D.test_idx, test),
        ):
            np.testing.assert_array_equal(actual, original)
        # Pair assignment does not depend on edge traversal order.
        reverse = copy.deepcopy(D.g)
        reverse["edges"] = list(reversed(reverse["edges"]))
        other = X.recipes(R.Data(reverse, D.ref_times), "rq-extra-tests")
        bypair = lambda r: {(q, p): role for _, q, p, role in r["interpolation"]["groups"]}
        self.assertEqual(bypair(recipe), bypair(other))

    def test_reference_and_control_masks_use_actual_times(self):
        D = self.D
        keep = np.ones(len(D.qi), bool)
        allv = X.view_for(D, self.plan, "fwd_all", keep)
        early = X.view_for(D, self.plan, "fwd_early", keep)
        self.assertTrue(set(early.forward["fit"]) < set(allv.forward["fit"]))
        for v, want in ((allv, 8), (early, 4)):
            idx = v.forward["fit"]
            onq = np.bincount(v.qi[idx], minlength=v.nQ) > 0
            onp = np.bincount(v.pj[idx], minlength=v.nP) > 0
            cq, cp = M.center_sets(v, onq, onp)
            self.assertEqual((len(cq), len(cp)), (want, want))
            self.assertFalse(v.forward["ctrl"][~D.qref & (D.qt > 120)].any())
            qr, pr = D.qref[D.qi[idx]], D.pref[D.pj[idx]]
            main = idx[~qr & ~pr]
            self.assertTrue((D.qt[D.qi[main]] <= 120).all())
            self.assertTrue((D.pt[D.pj[main]] <= 120).all())
        late = D.qref & (D.qt > 120)
        self.assertTrue(allv.forward["ctrl"][late].all())
        self.assertFalse(early.forward["ctrl"][late].any())
        self.assertEqual(
            R.reference_times(self.refs)[0]["RQ"][4], 140
        )

    def test_excluded_observations_do_not_fit(self):
        D = self.D
        seed = rqlib.derive_seed("rq-extra-tests", "recovery", "r0", 0)
        data = R.simulate(D, R.SCENARIOS["r0"], seed)
        keep = np.ones(len(D.qi), bool)
        for option in ("interp", "fwd_all", "fwd_early"):
            v = X.view_for(D, self.plan, option, keep)
            idx = v.fit["a"]
            ctrl = (
                v.forward["ctrl"] if option.startswith("fwd_")
                else M.control_access(v, idx)
            )
            bad = dict(data)
            outside = np.ones(len(D.qi), bool)
            outside[idx] = False
            for key, bar in (("z", "zbar"), ("s", "sbar")):
                x = data[key].copy()
                x[outside] += 17.0
                bad[key], bad[bar] = x, x.mean(axis=1)
            s0 = data["s0"].copy()
            s0[~ctrl] += 19.0
            bad["s0"], bad["s0bar"] = s0, s0.mean(axis=1)
            fits = [
                R.any_fit(
                    "registered", v, idx, d, 1, 0.05, False, 2, seed,
                    start="warm", ctrl=ctrl, basis=4,
                ) for d in (data, bad)
            ]
            self.assertEqual(fits[0]["objective"], fits[1]["objective"])
            for key in ("a", "b", "aS", "bS", "u", "v", "c", "DS", "covQ", "covP"):
                np.testing.assert_array_equal(fits[0][key], fits[1][key])
            moved = dict(data)
            s0 = data["s0"].copy()
            s0[ctrl] += 0.5
            moved["s0"], moved["s0bar"] = s0, s0.mean(axis=1)
            changed = R.any_fit(
                "registered", v, idx, moved, 1, 0.05, False, 2, seed,
                start="warm", ctrl=ctrl, basis=4,
            )
            self.assertNotEqual(changed["objective"], fits[0]["objective"])

    def test_attrition_boundaries_prefixes_and_root_counts(self):
        D = self.D
        at = self.plan["recipe"]["attrition"]["biological_at"][0]["world"]
        _, ma, _ = X.mask_for(D, self.plan, "biological_at")
        _, mb, _ = X.mask_for(D, self.plan, "biological_after")
        self.assertNotIn(f"{at}:99000000", ma["snapshots"])
        self.assertIn(f"{at}:100000000", ma["snapshots"])
        self.assertNotIn(f"{at}:100000000", mb["snapshots"])
        self.assertIn(f"{at}:101000000", mb["snapshots"])
        for case, cause in (
            ("technical", "technical"), ("pending_prefix", "pending"),
            ("pending_attempt", "pending"),
        ):
            _, report, _ = X.mask_for(D, self.plan, case)
            self.assertGreater(len(report["excluded_edges"][cause]), 0)
            self.assertEqual(report["schema"], X.CASE_SCHEMA)
            self.assertNotEqual(report["schema"], graph.MASK_SCHEMA)
        for k in (0, 1, 2):
            keep, _, _ = X.mask_for(D, self.plan, f"roots{k}")
            v = X.view_for(D, self.plan, "a", keep)
            self.assertEqual(len(np.unique(v.test_world)), k)
            why, roots = R.unavailable(
                v.fit["a"], v.val_idx, v.test_idx, v.test_world, v.val_world
            )
            self.assertEqual(roots, k)
            self.assertEqual(why is None, k == 2)

    def test_intact_primary_is_existing_procedure(self):
        D = self.D
        keep = np.ones(len(D.qi), bool)
        v = X.view_for(D, self.plan, "a", keep)
        seed = rqlib.derive_seed("rq-extra-tests", "recovery", "r0", 0)
        data = R.simulate(D, R.SCENARIOS["r0"], seed)
        original = R.procedure(
            D, data, "a", 1, [0.05], 2, seed,
            fitter="registered", start="warm", basis=4,
        )
        actual = X.evaluate(v, data, self.plan, seed, "a")
        self.assertEqual(
            rqlib.canonical(X.clean(original)),
            rqlib.canonical(X.clean(actual)),
        )

    def test_one_root_descriptive_scores_without_crossed_decision(self):
        seed = 41
        data = R.simulate(self.D, R.SCENARIOS["r0"], seed)
        keep, _, _ = X.mask_for(self.D, self.plan, "roots1")
        # Keep real fits and validation selection. A resolved scorer isolates the
        # root-count rule from the count-integral tolerance, with known scores.
        def resolved(v, _data, model, _idx, _fitter):
            def score(ix, info=None):
                if info is not None:
                    info["grid_unresolved"] = 0
                values = np.full(len(ix), 0.25 * model["u"].shape[1])
                return values, values * 2
            return score

        for op in ("a", "interp", "fwd_all", "fwd_early"):
            v = X.view_for(self.D, self.plan, op, keep)
            if op == "interp":
                # Interpolation repartitions training pairs independently of the
                # primary roots1 mask; retain one actual interpolation test root.
                chosen = v.test_world == v.test_world[0]
                v.test_idx, v.test_world = v.test_idx[chosen], v.test_world[chosen]
            if op.startswith("fwd_"):
                # Both forward branches get exactly one contributing root.
                v.forward["tests"] = {
                    name: ix[tw == tw[0]] for name, (ix, tw) in X.branches(v, op).items()
                }
            for _, tw in X.branches(v, op).values():
                self.assertEqual(len(np.unique(tw)), 1, op)
            with self.subTest(option=op), mock.patch.object(R, "scorer", side_effect=resolved), \
                    mock.patch.object(R, "crossed_lb", side_effect=AssertionError("one-root bootstrap")):
                out = X.evaluate(v, data, self.plan, seed, op)
                rows = [out[n] for n in X.branches(v, op)] if op.startswith("fwd_") else [out]
                for row in rows:
                    self.assertEqual(row["test_roots"], 1)
                    self.assertFalse(row["available"])
                    self.assertFalse(row["success"])
                    self.assertTrue(row["descriptive"])
                    self.assertAlmostEqual(row["test_improvement"], 0.25)
                    self.assertEqual(row["per_world"], [0.25])
                    self.assertEqual(len(row["per_world_ids"]), 1)
                    self.assertIsNone(row.get("test_lb"))
                self.assertFalse(out["decision"]["available"])

    def test_companion_attrition_masks_and_nominal_forward_availability(self):
        seed = 41
        data = R.simulate(self.D, R.SCENARIOS["r0"], seed)
        for op in ("interp", "fwd_all", "fwd_early"):
            keep, _, _ = X.mask_for(self.D, self.plan, "mixed")
            v = X.view_for(self.D, self.plan, op, keep)
            bad = dict(data)
            # No evaluation target or calibration row may read an attrited pair.
            for key, bar in (("z", "zbar"), ("s", "sbar")):
                x = data[key].copy()
                x[~keep] += 17
                bad[key], bad[bar] = x, x.mean(axis=1)
            ctrl = v.forward["ctrl"] if op.startswith("fwd_") else M.control_access(v, v.fit["a"])
            s0 = data["s0"].copy()
            s0[~ctrl] += 19
            bad["s0"], bad["s0bar"] = s0, s0.mean(axis=1)
            actual = [X.clean(X.evaluate(v, d, self.plan, seed, op)) for d in (data, bad)]
            self.assertEqual(actual[0], actual[1], op)
            if op.startswith("fwd_"):
                for branch in ("forward_transfer", "intersection"):
                    self.assertTrue(actual[0][branch]["available"], (op, branch, actual[0][branch]))

    def test_new_forward_test_only_unresolved_withholds_scores(self):
        seed = 41
        data = R.simulate(self.D, R.SCENARIOS["r0"], seed)
        v = X.view_for(self.D, self.plan, "fwd_all", np.ones(len(self.D.qi), bool))
        original = R.scorer

        def flagged(*args, **kwargs):
            score = original(*args, **kwargs)

            def wrapped(ix, info=None):
                result = score(ix, info)
                if np.array_equal(ix, v.forward["tests"]["intersection"]) and info is not None:
                    info["grid_unresolved"] = 1
                return result
            return wrapped

        with mock.patch.object(R, "scorer", side_effect=flagged):
            out = X.evaluate(v, data, self.plan, seed, "fwd_all")
        self.assertTrue(out["forward_transfer"]["available"])
        self.assertFalse(out["intersection"]["available"])
        self.assertNotIn("test_improvement", out["intersection"])
        self.assertNotIn("test_lb", out["intersection"])

    def test_supervisor_termination_reaps_workers_before_unlock_and_resumes(self):
        import fcntl

        directory = os.path.join(self.root, "termination")
        self.prepared(directory, cases="intact,roots1", options="a")
        argv = ["run", "--dir", directory, "--graph", self.gpath,
                "--references", self.refs, "--jobs", "2"]

        def children(pid):
            with open(f"/proc/{pid}/task/{pid}/children") as handle:
                return [int(p) for p in handle.read().split()]

        def active(pid):
            try:
                with open(f"/proc/{pid}/stat") as handle:
                    return handle.read().split()[2] != "Z"
            except (FileNotFoundError, ProcessLookupError):
                # A reaped worker can vanish between open() and read(): the read then raises ESRCH.
                return False

        for sig in (signal.SIGTERM, signal.SIGKILL):
            launch_log = os.path.join(self.root, f"supervisor-{sig}.log")
            with self.subTest(signal=sig), open(launch_log, "wb") as output, subprocess.Popen(
                [sys.executable, "-I", "-B", X.__file__, *argv],
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            ) as supervisor:
                workers = []
                try:
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        # A fork appears in /proc before its preexec guard runs.
                        # Only the post-exec acknowledgment identifies a worker
                        # that has completed guarded launch.
                        lines = rqlib.read_bytes(launch_log).decode().splitlines()
                        workers = [int(line.rsplit(" ", 1)[1]) for line in lines
                                   if line.startswith("started ") and ": guarded pid " in line]
                        if len(workers) == 2:
                            break
                        self.assertIsNone(supervisor.poll())
                        time.sleep(0.01)
                    self.assertEqual(len(workers), 2)
                    self.assertEqual(set(workers), set(children(supervisor.pid)))
                    for pid in workers:
                        with open(f"/proc/{pid}/cmdline", "rb") as handle:
                            self.assertIn(b"\0one\0", handle.read())
                        os.kill(pid, signal.SIGSTOP)
                    supervisor.send_signal(sig)
                    if sig == signal.SIGTERM:
                        # Stopped workers force the bounded-kill path. During reaping,
                        # a restart must still be refused by the supervisor's lock.
                        time.sleep(0.2)
                        with open(os.path.join(directory, ".lock"), "a") as lock:
                            with self.assertRaises(BlockingIOError):
                                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        supervisor.send_signal(signal.SIGTERM)  # repeated termination cannot skip cleanup
                    self.assertNotEqual(supervisor.wait(timeout=15), 0)
                    deadline = time.monotonic() + 5
                    while any(active(pid) for pid in workers) and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertFalse(any(active(pid) for pid in workers))
                    with X.locked(directory):
                        pass  # lock becomes available only once cleanup finishes
                finally:
                    if supervisor.poll() is None:
                        supervisor.kill()
                        supervisor.wait()
                    for pid in workers:
                        if active(pid):
                            os.kill(pid, signal.SIGKILL)
        self.command(*argv)
        plan = X.read_frozen(directory)
        found = X.read_results(directory, plan)
        self.assertEqual(len(found), 2)
        before = {n: rqlib.read_bytes(os.path.join(directory, "results", n)) for n in found}
        self.command(*argv)
        self.assertEqual(before, {n: rqlib.read_bytes(os.path.join(directory, "results", n)) for n in found})

    def test_fork_suite_refuses_one_worker_before_workdir_changes(self):
        directory = os.path.join(self.root, "keep")
        os.mkdir(directory)
        marker = os.path.join(directory, "marker")
        rqlib.write_durable(marker, b"keep")
        env = dict(os.environ, RQ_TEST_WORKERS="1")
        cp = subprocess.run(
            ["bash", os.path.join(HERE, "../../tests/redqueen_forks.sh"), "/unused/engine", directory],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        self.assertEqual(cp.returncode, 2, cp.stdout)
        self.assertIn("at least 2", cp.stdout)
        self.assertEqual(rqlib.read_bytes(marker), b"keep")

    def test_unresolved_validation_never_decides_new_forward(self):
        D = self.D
        keep = np.ones(len(D.qi), bool)
        v = X.view_for(D, self.plan, "fwd_all", keep)
        seed = 41
        data = R.simulate(D, R.SCENARIOS["r0"], seed)
        original = R.scorer

        def flagged(*args, **kwargs):
            score = original(*args, **kwargs)

            def wrapped(ix, info=None):
                out = score(ix, info)
                if np.array_equal(ix, v.forward["val"]) and info is not None:
                    info["grid_unresolved"] = info.get("grid_unresolved", 0) + 1
                return out
            return wrapped

        with mock.patch.object(R, "scorer", side_effect=flagged):
            out = X.forward(v, data, self.fit, seed, "fwd_all")
        self.assertFalse(out["decision"]["available"])
        self.assertTrue(out["selected"]["selection_unresolved"])
        for branch in ("forward_transfer", "intersection"):
            self.assertFalse(out[branch]["available"])
            self.assertFalse(out[branch]["success"])
            self.assertNotIn("test_lb", out[branch])

    def test_cli_end_to_end_resume_hashes_and_denominators(self):
        first = os.path.join(self.root, "parallel")
        second = os.path.join(self.root, "serial")
        for directory, jobs in ((first, "2"), (second, "1")):
            self.prepared(directory)
            self.command(
                "run", "--dir", directory, "--graph", self.gpath,
                "--references", self.refs, "--jobs", jobs,
            )
            self.command(
                "summarize", "--dir", directory,
                "--out", os.path.join(directory, "summary.json"),
            )
        p1, p2 = X.read_frozen(first), X.read_frozen(second)
        self.assertEqual(rqlib.canonical(p1), rqlib.canonical(p2))
        a = X.read_results(first, p1)
        b = X.read_results(second, p2)
        self.assertEqual(set(a), set(b))
        self.assertEqual(len(a), len(X.CASES))
        observation_sets = {
            rqlib.canonical(v["observations"]) for v in a.values()
        }
        self.assertEqual(len(observation_sets), 1)
        for name in a:
            self.assertEqual(
                rqlib.read_bytes(os.path.join(first, "results", name)),
                rqlib.read_bytes(os.path.join(second, "results", name)),
            )
        summary = X.summarize(first)
        self.assertTrue(summary["complete"])
        self.assertFalse(summary["criterion"]["applicable"])
        for case in ("roots0", "roots1"):
            row = next(c for c in summary["cells"] if (
                c["case"], c["option"], c["branch"]
            ) == (case, "a", "world_transfer"))
            self.assertEqual(
                (row["datasets"], row["successes"], row["unavailable"], row["rate"]),
                (1, 0, 1, 0.0),
            )
        before = {
            name: rqlib.read_bytes(os.path.join(first, "results", name))
            for name in a
        }
        self.command(
            "run", "--dir", first, "--graph", self.gpath,
            "--references", self.refs, "--jobs", "2",
        )
        for name, raw in before.items():
            self.assertEqual(
                raw, rqlib.read_bytes(os.path.join(first, "results", name))
            )
        # Missing work remains in the scheduled denominator.
        missing = next(iter(a))
        os.unlink(os.path.join(first, "results", missing))
        partial = X.summarize(first)
        self.assertFalse(partial["complete"])
        self.assertEqual(partial["scheduled_tasks"] - partial["completed_tasks"], 1)
        missing_case, missing_scenario, _ = (a[missing][k] for k in ("case", "scenario", "rep"))
        for cell in partial["cells"]:
            if (cell["case"], cell["scenario"]) == (missing_case, missing_scenario):
                self.assertEqual((cell["datasets"], cell["missing"], cell["unavailable"]), (1, 1, 1))
        # A copied result under another name is refused.
        shutil.copyfile(
            os.path.join(second, "results", missing),
            os.path.join(first, "results", "stray.json"),
        )
        with self.assertRaisesRegex(SystemExit, "stray"):
            X.summarize(first)

    def test_acceptance_boundary_separate_effects_and_fixed_denominators(self):
        plan = dict(self.plan, toy=False, reps=20, cases=["intact"], options=["a"],
                    scenarios=list(R.SETS["main"]), fit={
                        "ranks": 4, "lambdas": "0.01,0.02,0.05,0.2", "iters": 30,
                        "start": "both", "basis": 6, "embedding": "shared", "center": "references",
                    })
        for successes in ((15, 20), (20, 15), (16, 16)):
            found = {}
            for case, sc, rep in X.tasks(plan):
                n = successes[X.CRITERION["scenarios"].index(sc)] if sc in X.CRITERION["scenarios"] else 0
                found[X.task_name((case, sc, rep))] = {"options": {"a": {
                    "decision": {"available": rep != 19}, "success": rep < n,
                }}}
            # Keep failures and unavailable realizations in the 20-dataset denominator.
            with mock.patch.object(X, "read_frozen", return_value=plan), \
                    mock.patch.object(X, "read_results", return_value=found):
                summary = X.summarize(self.root)
            self.assertTrue(summary["criterion"]["applicable"])
            self.assertEqual(summary["criterion"]["core_pass"], successes == (16, 16))
            for sc, n in zip(X.CRITERION["scenarios"], successes):
                cell = next(c for c in summary["cells"] if c["scenario"] == sc)
                self.assertEqual(cell["datasets"], 20)
                self.assertEqual(cell["successes"], min(n, 19))
                self.assertEqual(cell["unavailable"], 1)
                self.assertEqual(cell["rate"], min(n, 19) / 20)
            # A missing realization is not silently removed, even with 16 successes.
            if successes == (16, 16):
                del found[X.task_name(("intact", "r1_034", 19))]
                with mock.patch.object(X, "read_frozen", return_value=plan), \
                        mock.patch.object(X, "read_results", return_value=found):
                    missing = X.summarize(self.root)
                self.assertFalse(missing["criterion"]["core_pass"])
                cell = next(c for c in missing["cells"] if c["scenario"] == "r1_034")
                self.assertEqual((cell["datasets"], cell["missing"], cell["successes"]), (20, 1, 16))

    def test_freeze_refuses_tampering_and_changed_references(self):
        directory = os.path.join(self.root, "frozen")
        self.prepared(directory, cases="intact", options="interp")
        path = os.path.join(directory, "plan.json")
        original = rqlib.read_bytes(path)
        value = rqlib.read_json(path)
        value["recipe"]["attrition"]["intact"] = [{
            "world": self.D.worlds[0], "cause": "pending",
            "first": 1, "last": 200_000_000,
        }]
        rqlib.write_json_durable(path, value)
        with self.assertRaisesRegex(SystemExit, "hash mismatch"):
            X.verified(directory, self.gpath, self.refs)
        rqlib.write_durable(path, original)
        refs = rqlib.read_json(self.refs)
        refs["references"]["RQ:4"]["frame"] = 120_000_000
        rqlib.write_json_durable(self.refs, refs)
        with self.assertRaises(SystemExit) as refused:
            X.verified(directory, self.gpath, self.refs)
        self.assertEqual(str(refused.exception),
                         f"{self.refs}: invalid actual reference panel: {self.refs}: "
                         "RQ:4's snapshot UUID is not sentinel-0@120000000's")
        refs["references"]["RQ:4"]["snapshot"] = sealing.snapshot_uuid(
            refs["references"]["RQ:4"]["uuid"], 120_000_000)
        rqlib.write_json_durable(self.refs, refs)
        with self.assertRaisesRegex(SystemExit, "changed"):
            X.verified(directory, self.gpath, self.refs)

    def test_completed_result_body_tampering_is_refused(self):
        directory = os.path.join(self.root, "corrupt-result")
        self.prepared(directory, cases="roots0", options="a")
        args = ["run", "--dir", directory, "--graph", self.gpath, "--references", self.refs]
        self.command(*args)
        plan = X.read_frozen(directory)
        path = os.path.join(directory, "results", X.task_name(X.tasks(plan)[0]))
        result = rqlib.read_json(path)
        result["options"]["a"]["success"] = True
        rqlib.write_json_durable(path, result)
        with self.assertRaisesRegex(SystemExit, "body hash"):
            X.read_results(directory, plan)
        self.assertIn("body hash", self.command(*args, ok=False).stdout)


if __name__ == "__main__":
    unittest.main()

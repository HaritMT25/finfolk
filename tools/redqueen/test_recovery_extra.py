#!/usr/bin/env python3
"""Recovery extension tests; numpy is required when RQ_REQUIRE_NUMPY=1."""
from __future__ import annotations

import argparse
import ast
import contextlib
import copy
import hashlib
import io
import json
import math
import os
import re
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


def toy(opponents=2):
    """The toy recovery graph; opponents: training C worlds each world's snapshots meet (cross / ab_to_c pairs). With
    the default 2 every test target's predator comes from the same two worlds, so more than 2.5% of crossed-bootstrap
    draws give every target zero weight and the lower bound is -inf (main's rule), which a legacy result cannot
    serialize; the bank-mode legacy tests use 12."""
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
            for p in [p for p in train if p != wid][:opponents]:
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


# ================================================================== bank mode (A_design_v5 3.2, 3.5-3.8, 4; WP4)
A1 = "rq2026-d8-recovery-A1"
REG_FIT = dict(fitter="registered", ranks=4, lambdas="0.01,0.02,0.05,0.2", iters=30, start="both", basis=6,
               embedding="shared", center="references")
WP5 = ("CARRIED FOR WP5 (A_design_v5 3.4: recovery_extra.py's bank mode). WP4 changes no recovery_extra.py line, so "
       "this is an expected failure until WP5 implements it.")


def legacy_ns(**kw):
    base = dict(graph=None, namespace="rq-bank-t7", fitter="registered", options="a", ranks=1, lambdas="0.05",
                iters=2, ab_cap=-1, start="warm", basis=4, embedding=None, center=None, set="main", scenarios="r0",
                reps=0, jobs=1, obs_model="bank", bank=None, obs_tables=None, allow_synthetic_bank=False)
    base.update(kw)
    return argparse.Namespace(**base)


def sha_tag(tag):
    return hashlib.sha256(tag.encode()).hexdigest()


def fabricated(cfg, sc, rep, success=True, options=("a", "fwd")):
    """A result of cfg's run for (sc, rep): its identity and labels consistent (check_result passes), synthetic option
    records (no fit; procedure-, forward- and numerical-shaped), observations hashed from (sc, rep) alone, so every
    directory carrying (sc, rep) shares them (pairing)."""
    om = cfg["observation_model"]
    noiseless = bool(R.SCENARIOS[sc].get("noiseless"))
    keys = R.OBS_KEYS + (R.BANK_OBS_KEYS if om["mode"] == "bank" else ())
    obsr = {k: {"shape": [100, 6], "dtype": "<f8", "sha256": sha_tag(f"{sc}:{rep}:{k}")} for k in keys}
    if noiseless:
        obsr["cnt"] = dict(R.ABSENT_CNT)
    opts = {}
    for o in options:
        if noiseless:
            opts[o] = dict(R.NUMERICAL_FWD) if o == "fwd" else {"rank": 1, "relative": 0.01, "relative_identified": 0.01}
            continue
        lb = 0.01 if success else -0.01
        rec_ = {"available": True, "selected": {"rank": 1, "lambda": 0.05, "start": "warm"}, "success": bool(success),
                "test_improvement": 0.1, "test_lb": lb, "fit_pairs": 100, "classes": None, "candidates": [],
                "start": "both", "decision": {"available": True, "test_worlds": 6, "selection_unresolved": False,
                                              "integration_unresolved": 0, "reason": None}}
        if o == "fwd":
            br = {"available": True, "success": bool(success), "worlds": 3, "test_improvement": 0.1, "test_lb": lb}
            rec_.update(procedure="forward", forward_transfer=dict(br), intersection=dict(br))
        opts[o] = rec_
    return {"schema": R.RESULT_SCHEMA, "scenario": sc, "rep": rep,
            "seed": rqlib.derive_seed(cfg["namespace"], "recovery", sc, rep), "settings": {},
            "config_sha256": rqlib.canonical_sha(cfg), "noise_source": om["noise_source"], "accepting": om["accepting"],
            "observation_model_sha256": rqlib.canonical_sha(om), "noiseless": noiseless, "observations": obsr,
            "options": opts, "reference_support": None, "fitter": "registered"}


def write_result(d, r):
    rqlib.write_json_durable(os.path.join(d, f"{r['scenario']}.{r['rep']:03d}.json"), r)


def extra_prepare(out, gpath, refs, *more, namespace="rq-extra-tests", options="a", cases="intact",
                  scenarios="r0", reps=1):
    """recovery_extra.py prepare (in process, the planning-mode tool of WP4) -> its exit code."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return X.main(["prepare", "--graph", gpath, "--references", refs, "--namespace", namespace, "--allow-toy",
                       "--options", options, "--cases", cases, "--scenarios", scenarios, "--reps", str(reps),
                       "--ranks", "1", "--lambdas", "0.05", "--iters", "2", "--start", "warm", "--basis", "4",
                       "--out", out, *more])


@unittest.skipIf(np is None, "numpy unavailable")
class TestRecoveryBankMode(unittest.TestCase):
    """recovery.py's bank mode through its procedures and directories (Red Queen recovery option A, A_design_v5.md;
    WP4), on a synthetic bank/3 (test_graph.bank_files: test_obslaw's fixture) and this module's toy graph: T6-1 (one
    variance model reaches every candidate, procedure, option and extra procedure through any_fit; none reaches a
    numerical fit), T7-1..T7-6 (the legacy tool's parts; each recovery_extra.py part is a separate expected failure
    carried for WP5)."""

    @classmethod
    def setUpClass(cls):
        import obslaw
        import test_graph as TG
        cls.TG, cls.ol = TG, obslaw
        cls.bp, cls.tp = TG.bank_files()
        cls.obs = obslaw.BankObservationModel(cls.bp, cls.tp)
        cls.tmpc = tempfile.TemporaryDirectory()
        root = cls.tmpc.name
        cls.gdir = os.path.join(root, "graph")
        graph.write(toy(opponents=12), cls.gdir)        # (finite crossed bounds: legacy results serialize; toy())
        cls.gpath = os.path.join(cls.gdir, "graph.jsonl.gz")
        cls.refs = os.path.join(root, "references.json")
        rqlib.write_json_durable(cls.refs, reference_panel(root))

    @classmethod
    def tearDownClass(cls):
        cls.tmpc.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def ns(self, **kw):
        return legacy_ns(**dict(dict(graph=self.gpath, bank=self.bp, obs_tables=self.tp), **kw))

    def bank_run(self, name, scenario="r0", rep=0, **kw):
        """A legacy run directory (bank mode unless kw says otherwise) with one real result (the registered map, ranks
        0..1, 2 sweeps, basis 4) -> (directory, result path)."""
        out = os.path.join(self.root, name)
        R.prepare_run(self.ns(out=out, scenarios=scenario, **kw))
        f = os.path.join(out, f"{scenario}.{rep:03d}.json")
        self.assertEqual(R.one(self.ns(out=f, scenario=scenario, rep=rep, **kw)), 0)
        return out, f

    def flipped_bank(self, key):
        """A bank/3 differing from the fixture in ONE byte (a placeholder receipt hash's last digit) and its tables."""
        doc = self.TG.bank_doc()
        h = doc["fit"]["noise"]["receipt_sha256"]
        doc["fit"]["noise"]["receipt_sha256"] = h[:-1] + ("0" if h[-1] != "0" else "1")
        return self.TG.bank_files(key, doc)

    # ---------------------------------------------------------------- T6-1
    def test_T6_1_one_bank_variance_model_reaches_every_candidate_procedure_and_option(self):
        """T6-1 (v2 P1): a spy on map.fit records, for ranks 0..4 and every lambda of the legacy procedure (option a),
        the forward procedure and the extra procedures (a, interp, fwd_all, fwd_early on their views), both starts,
        one and the same bank variance model: var_fn = W, rep_prior {nu0: nu0_C}, score_law = (A, L), tagged with the
        model's identity; every numerical fit (and any unweighted fit) gets None for all three; map.fit refuses a
        rep_prior or score_law without a var_fn."""
        D = X.data_from(self.gpath, self.refs)
        data = R.simulate(D, R.SCENARIOS["r1_034"], 61, obs=self.obs)
        calls, tag, real = [], ["a"], M.fit

        def spy(*a, **k):
            calls.append({"where": tag[0], "rank": a[3], "lam": a[4], "var_fn": k.get("var_fn"),
                          "rep_prior": k.get("rep_prior"), "score_law": k.get("score_law")})
            return real(*a, **k)
        fit = dict(ranks=4, lambdas="0.01,0.2", iters=2, start="both", basis=4, embedding="shared",
                   center="references")
        plan = X.make_plan(D, self.gpath, self.refs, "rq-extra-tests", fit, ["r1_034"], 1, list(X.OPTIONS),
                           ["intact"], True)
        keep = X.mask_for(D, plan, "intact")[0]
        kw = dict(fitter="registered", start="both", basis=4)
        with mock.patch.object(M, "fit", spy):
            R.procedure(D, data, "a", 4, [0.01, 0.2], 2, 61, **kw)
            tag[0] = "fwd"
            R.forward_procedure(D, data, 4, [0.01, 0.2], 2, 61, **kw)
            for op in X.OPTIONS:
                tag[0] = f"extra-{op}"
                X.evaluate(X.view_for(D, plan, op, keep), data, plan, 61, op)
        self.assertEqual({c["where"] for c in calls}, {"a", "fwd"} | {f"extra-{op}" for op in X.OPTIONS})
        self.assertEqual({c["rank"] for c in calls}, {0, 1, 2, 3, 4})
        self.assertEqual({c["lam"] for c in calls if c["rank"]}, {0.01, 0.2})
        tags = {(getattr(c["var_fn"], "identity", None), rqlib.canonical(c["rep_prior"]),
                 getattr(c["score_law"], "identity", None)) for c in calls}
        self.assertEqual(tags, {(self.obs.identity_sha, rqlib.canonical({"nu0": self.obs.nu0_C}), self.obs.identity_sha)})
        self.assertTrue(all(isinstance(c["var_fn"], self.ol.WorkingVariance) and isinstance(c["score_law"],
                                                                                            self.ol.ScoreLaw)
                            for c in calls))
        calls.clear()
        tag[0] = "numerical"
        dn = R.simulate(D, R.SCENARIOS["num_r2"], 62, obs=self.obs)
        self.assertNotIn("cnt", dn)
        with mock.patch.object(M, "fit", spy):
            R.numerical(D, dn, "a", 2, 2, 62, fitter="registered", basis=4)
            R.any_fit("registered", D, D.fit["a"], data, 1, 0.1, False, 2, 62, start="warm", basis=4, weighted=False)
            R.any_fit("registered", D, D.fit["a"], dn, 1, 0.1, False, 2, 62, start="warm", basis=4)   # (no counts)
        self.assertEqual(len(calls), len(R.REG_CONTINUATION) + 2)
        self.assertTrue(all(c["var_fn"] is None and c["rep_prior"] is None and c["score_law"] is None for c in calls))
        for bad in ({"rep_prior": {"nu0": 12.5}}, {"score_law": self.obs.score_law()}):
            with self.assertRaisesRegex(ValueError, "without a var_fn"):
                M.fit(D, D.fit["a"], data, 1, 0.1, **bad)

    # ---------------------------------------------------------------- T7-1
    def test_T7_1_changed_bank_or_table_bytes_refuse_run_and_another_model_is_refused_on_read(self):
        """T7-1 (legacy recovery.py): a run directory is bound to its bank and tables -- one changed byte of the artifact
        (its tables rebuilt) or a changed table array refuses `run`; a kept result of another observation model (its
        observation_model_sha256, noise_source or accepting label) is refused on read, by the summary and the resume."""
        out = os.path.join(self.root, "run")
        a = self.ns(out=out, scenarios="r0", reps=0)
        self.assertEqual(R.run(a), 0)
        cfg = rqlib.read_json(os.path.join(out, "config.json"))
        self.assertEqual(cfg["observation_model"]["bank_artifact_sha256"], rqlib.sha256_file(self.bp))
        bp2, tp2 = self.flipped_bank("t71")
        with self.assertRaisesRegex(SystemExit, "another configuration"):
            R.run(self.ns(out=out, scenarios="r0", reps=0, bank=bp2, obs_tables=tp2))
        import test_obslaw as TO
        data, _ = TO._rehashed_tables(rqlib.read_bytes(self.tp), {"fit_A": lambda x: x + np.where(np.arange(len(x)) == 9,
                                                                                                  1e-9, 0.0)})
        tp3 = os.path.join(self.root, "t3.npz")
        rqlib.write_durable(tp3, data)
        with self.assertRaisesRegex(SystemExit, "another configuration"):
            R.run(self.ns(out=out, scenarios="r0", reps=0, obs_tables=tp3))
        f = os.path.join(out, "r0.000.json")
        self.assertEqual(R.one(self.ns(out=f, scenario="r0", rep=0)), 0)
        good = rqlib.read_bytes(f)
        self.assertEqual(R.summarize(out)["datasets"], 1)
        for field, value in (("observation_model_sha256", "0" * 64), ("noise_source", "scenario_planning_only"),
                             ("accepting", False)):
            r = json.loads(good)
            r[field] = value
            rqlib.write_durable(f, rqlib.canonical(r))
            with self.subTest(field=field):
                with self.assertRaisesRegex(SystemExit, "another noise source or observation model"):
                    R.summarize(out)
                with self.assertRaisesRegex(SystemExit, "another noise source or observation model"):
                    R.prepare_run(self.ns(out=out, scenarios="r0", reps=0))
        rqlib.write_durable(f, good)
        self.assertEqual(R.summarize(out)["datasets"], 1)

    @unittest.expectedFailure
    def test_T7_1_WP5_recovery_extra_binds_the_bank(self):
        """T7-1, recovery_extra's part (v5 3.4: prepare loads the model, verified re-derives the plan with it, read_results
        refuses another observation model). """
        out = os.path.join(self.root, "extra")
        self.assertEqual(extra_prepare(out, self.gpath, self.refs, "--obs-model", "bank", "--bank", self.bp,
                                       "--obs-tables", self.tp), 0)
        self.assertEqual(X.read_frozen(out)["noise_source"], "bank_d8")

    # ---------------------------------------------------------------- T7-2
    def test_T7_2_paired_observations_and_pairing_refuses_a_doctored_pair(self):
        """T7-2 (legacy): two bank-mode directories of one namespace (the registered fit and its separate-embedding
        sensitivity) carry identical observations for the shared (scenario, rep); `pairing` (function and CLI) accepts
        them, refuses a doctored pair (one hash changed) and refuses planning input (v5 3.6, 3.7)."""
        d1, f1 = self.bank_run("main")
        d2, f2 = self.bank_run("separate", embedding="separate")
        r1, r2 = rqlib.read_json(f1), rqlib.read_json(f2)
        self.assertEqual(r1["observations"], r2["observations"])
        self.assertEqual(set(r1["observations"]), set(R.OBS_KEYS + R.BANK_OBS_KEYS))
        rep = R.pairing([d1, d2])
        self.assertEqual((rep["datasets"], rep["comparisons"]), (1, 1))
        with contextlib.redirect_stdout(io.StringIO()) as so:
            self.assertEqual(R.main(["pairing", "--dirs", f"{d1},{d2}"]), 0)
        self.assertEqual(json.loads(so.getvalue())["result"], "paired")
        good = rqlib.read_bytes(f2)
        r2["observations"]["z"]["sha256"] = "0" * 64
        rqlib.write_durable(f2, rqlib.canonical(r2))
        with self.assertRaisesRegex(SystemExit, r"\(r0, 0\) has different observations"):
            R.pairing([d1, d2])
        rqlib.write_durable(f2, good)
        dp, _ = self.bank_run("planning", obs_model="planning", bank=None, obs_tables=None)
        with self.assertRaisesRegex(SystemExit, "planning input is refused"):
            R.pairing([d1, dp])

    @unittest.expectedFailure
    def test_T7_2_WP5_extra_results_carry_the_legacy_observation_records(self):
        """T7-2, recovery_extra's part (v5 3.4 L779-787: observation_hashes moves to recovery.py, with mu_* and the
        absent-cnt record): an extra result's observations equal a legacy result's for the same (scenario, rep)."""
        D = X.data_from(self.gpath, self.refs)
        data = R.simulate(D, R.SCENARIOS["r0"], 5, obs=self.obs)
        self.assertEqual(X.observation_hashes(data), R.observation_hashes(data))

    # ---------------------------------------------------------------- T7-3
    def test_T7_3_forward_masks_root_guards_and_fixed_denominators_persist_in_bank_mode(self):
        """T7-3 (legacy): in bank mode the forward procedure fits its masked pairs with exactly the controls of prey at
        <= 120M (every fit's ctrl), a graph with one contributing test root leaves the procedure unavailable (D6 rule
        27), and the summary's acceptance rate keeps every dataset in its denominator (unavailable = unsuccessful)."""
        D = R.load_data(self.gpath)
        data = R.simulate(D, R.SCENARIOS["r1_017"], 71, obs=self.obs)
        ctrls, real = [], M.fit

        def spy(*a, **k):
            ctrls.append(k.get("ctrl"))
            return real(*a, **k)
        with mock.patch.object(M, "fit", spy):
            fw = R.forward_procedure(D, data, 1, [0.05], 2, 71, fitter="registered", start="warm", basis=4)
        idx = D.forward["fit"]
        want = M.control_access(D, idx, R.FORWARD_TMAX)
        self.assertFalse(want[D.qt > R.FORWARD_TMAX].any())
        self.assertEqual((fw["fit_pairs"], fw["controls"]), (len(idx), int(want.sum())))
        self.assertTrue(ctrls and all(np.array_equal(c, want) for c in ctrls))
        v = copy.copy(D)
        v.test_world = np.zeros_like(D.test_world)
        out = R.procedure(v, data, "a", 1, [0.05], 2, 71, fitter="registered", start="warm", basis=4)
        self.assertFalse(out["available"])
        self.assertIn("contributing test root", out["reason"])
        d, f = self.bank_run("den")
        r0 = rqlib.read_json(f)
        for rep in (1, 2, 3):
            r = copy.deepcopy(r0)
            r["rep"], r["seed"] = rep, rqlib.derive_seed("rq-bank-t7", "recovery", "r0", rep)
            o = r["options"]["a"]
            o.update(success=False, decision={"available": False, "selection_unresolved": True,
                                              "integration_unresolved": 1, "test_worlds": 6, "reason": "unresolved"})
            o["selected_primary"].update(available=False, success=False)
            write_result(d, r)
        cell = R.summarize(d)["cells"][0]
        k = int(r0["options"]["a"]["success"])
        self.assertEqual((cell["datasets"], cell["successes"], cell["unavailable"]), (4, k, 3))
        self.assertEqual(cell["rate"], round(k / 4, 3))
        self.assertEqual(cell["wilson95"], R.wilson(k, 4))

    @unittest.expectedFailure
    def test_T7_3_WP5_extra_partitions_masks_denominators_and_two_workers_in_bank_mode(self):
        """T7-3, recovery_extra's part: its partitions, access masks, root guards, fixed denominators and the
        1-or-2-worker limit, in bank mode (v5 3.4)."""
        out = os.path.join(self.root, "extra")
        self.assertEqual(extra_prepare(out, self.gpath, self.refs, "--obs-model", "bank", "--bank", self.bp,
                                       "--obs-tables", self.tp, options="a,interp,fwd_all,fwd_early",
                                       cases="intact,roots1"), 0)

    # ---------------------------------------------------------------- T7-4
    def test_T7_4_labels_and_mixed_mode_summaries_are_refused(self):
        """T7-4 (legacy): bank results and summaries carry noise_source bank_d8 (accepting with an accepted-form bank;
        never with a synthetic bank, which also needs the test flag); planning ones scenario_planning_only, accepting
        false and the label "PLANNING NOISE: NOT GATE-2 EVIDENCE"; a planning result in a bank directory, or a bank
        result relabelled, is refused (a mixed-mode summary); bank and planning arguments do not mix."""
        db, fb = self.bank_run("bank")
        rb, cfg = rqlib.read_json(fb), rqlib.read_json(os.path.join(db, "config.json"))
        om = cfg["observation_model"]
        self.assertEqual((rb["noise_source"], rb["accepting"], rb["observation_model_sha256"], rb["noiseless"]),
                         ("bank_d8", True, rqlib.canonical_sha(om), False))
        sb = R.summarize(db)
        self.assertEqual((sb["noise_source"], sb["accepting"], sb["scope"]), ("bank_d8", True, R.BANK_SCOPE))
        self.assertNotIn("label", sb)
        bps, tps = self.TG.bank_files("synthetic", self.TG.bank_doc(synthetic=True))
        with self.assertRaisesRegex(SystemExit, "synthetic: true is refused"):
            R.prepare_run(self.ns(out=os.path.join(self.root, "syn0"), bank=bps, obs_tables=tps))
        ds, fs = self.bank_run("syn", bank=bps, obs_tables=tps, allow_synthetic_bank=True)
        self.assertEqual((rqlib.read_json(fs)["accepting"], R.summarize(ds)["accepting"]), (False, False))
        dp, fp = self.bank_run("plan", obs_model="planning", bank=None, obs_tables=None)
        rp, sp = rqlib.read_json(fp), R.summarize(dp)
        self.assertEqual((rp["noise_source"], rp["accepting"], set(rp["observations"])),
                         ("scenario_planning_only", False, set(R.OBS_KEYS)))
        self.assertEqual((sp["noise_source"], sp["accepting"], sp["scope"], sp["label"]),
                         ("scenario_planning_only", False, R.PLANNING_LABEL, "PLANNING NOISE: NOT GATE-2 EVIDENCE"))
        good = rqlib.read_bytes(fb)
        shutil.copy(fp, os.path.join(db, "r0.001.json"))
        with self.assertRaisesRegex(SystemExit, "mixed summary"):
            R.summarize(db)
        os.remove(os.path.join(db, "r0.001.json"))
        rqlib.write_durable(fb, rqlib.canonical(dict(rb, noise_source="scenario_planning_only")))
        with self.assertRaisesRegex(SystemExit, "another noise source"):
            R.summarize(db)
        rqlib.write_durable(fb, good)
        with self.assertRaisesRegex(SystemExit, "bank mode's"):
            R.resolve(self.ns(obs_model="planning", obs_tables=None))
        with self.assertRaisesRegex(SystemExit, "needs --bank and --obs-tables"):
            R.resolve(self.ns(obs_tables=None))

    @unittest.expectedFailure
    def test_T7_4_WP5_extra_labels_in_bank_mode(self):
        """T7-4, recovery_extra's part: its plans, results and summaries labelled bank_d8 / planning (v5 3.4, 3.7)."""
        out = os.path.join(self.root, "extra")
        self.assertEqual(extra_prepare(out, self.gpath, self.refs, "--obs-model", "bank", "--bank", self.bp,
                                       "--obs-tables", self.tp), 0)
        self.assertEqual(X.summarize(out)["noise_source"], "bank_d8")

    # ---------------------------------------------------------------- T7-5
    def test_T7_5_cap_scenarios_and_a_zero_ceiling_are_refused_in_bank_mode(self):
        """T7-5 (legacy): the *_cap / *_cap15 planning approximations of the bank are refused in bank mode by run (before
        any file), one and simulate; planning still runs them; a configuration whose ceiling M_H is 0 is refused at the
        load (run: before any file) and by the generator (v5 1.10)."""
        D = R.load_data(self.gpath)
        for sc in ("r0_cap", "r2_034_cap15"):
            out = os.path.join(self.root, sc)
            with self.subTest(sc=sc):
                with self.assertRaisesRegex(SystemExit, "BANK_REFUSED"):
                    R.run(self.ns(out=out, scenarios=sc, reps=1))
                self.assertFalse(os.path.exists(out))
                with self.assertRaisesRegex(SystemExit, "BANK_REFUSED"):
                    R.one(self.ns(out=os.path.join(self.root, f"{sc}.json"), scenario=sc, rep=0))
                with self.assertRaisesRegex(ValueError, "_cap"):
                    R.simulate(D, R.SCENARIOS[sc], 1, obs=self.obs)
                self.assertIn("cnt", R.simulate(D, R.SCENARIOS[sc], 1))
        self.assertEqual(R.BANK_REFUSED, frozenset(n for n in R.SCENARIOS if n.endswith(("_cap", "_cap15"))))
        zero = copy.copy(self.obs)
        zero.M_H, zero.c_H = 0, 0.0
        with self.assertRaisesRegex(ValueError, "M_H is 0"):
            R.simulate(D, R.SCENARIOS["r0"], 1, obs=zero)
        real = self.ol.BankObservationModel.__init__

        def init(self_, *a, **k):
            real(self_, *a, **k)
            self_.M_H, self_.c_H = 0, 0.0
        out = os.path.join(self.root, "zero")
        with mock.patch.object(self.ol.BankObservationModel, "__init__", init):
            with self.assertRaisesRegex(SystemExit, "M_H is 0"):
                R.run(self.ns(out=out, scenarios="r0", reps=1))
            self.assertFalse(os.path.exists(out))
            with self.assertRaisesRegex(SystemExit, "M_H is 0"):
                R.one(self.ns(out=os.path.join(self.root, "z.json"), scenario="r0", rep=0))

    @unittest.expectedFailure
    def test_T7_5_WP5_extra_refuses_cap_scenarios_in_bank_mode(self):
        """T7-5, recovery_extra's part: prepare in bank mode refuses a *_cap scenario (v5 3.4)."""
        out = os.path.join(self.root, "extra")
        with self.assertRaisesRegex(SystemExit, "BANK_REFUSED"):
            extra_prepare(out, self.gpath, self.refs, "--obs-model", "bank", "--bank", self.bp, "--obs-tables",
                          self.tp, scenarios="r0_cap")

    # ---------------------------------------------------------------- T7-7's helper (v5 3.2 observation_hashes, 1.8)
    def test_T7_7_observation_hashes_absent_counts_record_and_refusals(self):
        """observation_hashes (v5 3.2, Codex P1): over eta, inter, cnt, z, s, s0 (+ mu_C, mu_S, mu_F in bank mode) each
        present key is {shape, dtype "<f8", sha256 of its little-endian float64 C-order bytes}; a noiseless dataset's
        absent cnt is the record {"absent": "noiseless"} (never a KeyError); any other absent key is refused."""
        D = R.load_data(self.gpath)
        noisy = R.simulate(D, R.SCENARIOS["r0"], 3, obs=self.obs)
        quiet = R.simulate(D, R.SCENARIOS["num_r1"], 3, obs=self.obs)
        h = R.observation_hashes(noisy)
        self.assertEqual(list(h), list(R.OBS_KEYS + R.BANK_OBS_KEYS))
        self.assertEqual(h["cnt"], {"shape": list(noisy["cnt"].shape), "dtype": "<f8", "sha256": hashlib.sha256(
            np.ascontiguousarray(noisy["cnt"], dtype="<f8").tobytes()).hexdigest()})
        self.assertEqual(h["mu_S"]["sha256"], hashlib.sha256(np.asarray(noisy["mu"]["S"], "<f8").tobytes()).hexdigest())
        self.assertEqual(R.observation_hashes(quiet)["cnt"], {"absent": "noiseless"})
        plan = R.simulate(D, R.SCENARIOS["num_r1"], 3)
        self.assertEqual(list(R.observation_hashes(plan)), list(R.OBS_KEYS))
        self.assertEqual(R.observation_hashes(plan)["cnt"], {"absent": "noiseless"})
        for key in ("z", "eta", "s0"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, f"{key} is absent"):
                R.observation_hashes({k: v for k, v in noisy.items() if k != key})
        with self.assertRaisesRegex(ValueError, "mu_F is absent"):
            R.observation_hashes(dict(noisy, mu={"C": noisy["mu"]["C"], "S": noisy["mu"]["S"]}))
        with self.assertRaisesRegex(ValueError, "cnt is absent"):
            R.observation_hashes(dict(noisy, cnt=None))

    # ---------------------------------------------------------------- T7-6
    def test_T7_6_no_recovery_module_opens_a_store_run_archive_or_production_root(self):
        """T7-6 (static G-2, a guard): recovery.py, recovery_extra.py, map.py and obslaw.py import none of the study's
        store / run / archive modules (store, run, cell, ckpt, staging, worlds, forks, probes, evidence, val_block),
        use no noisebank function that reads a bank store or writes bank results or accounting (collect*,
        provenance, estimate*, validate*, run_*, read_*, verify*, load_*, *store*, *bundle*, ledger*, reconcile*),
        and name no production root in any string (docstrings included)."""
        forbidden = {"store", "run", "cell", "ckpt", "staging", "worlds", "forks", "probes", "evidence", "val_block"}
        nb_bad = re.compile(r"^(collect\w*|provenance|estimate\w*|validate\w*|run_\w*|read_\w*|verify\w*|load_\w*|"
                            r"\w*store\w*|\w*bundle\w*|ledger\w*|reconcile\w*)$")
        roots = re.compile(r"/home/|~/finfolk|finfolk/work|wasm_parity|hs/hs|BANK_ROOT|/bank/results")
        for name in ("recovery.py", "recovery_extra.py", "map.py", "obslaw.py"):
            tree = ast.parse(rqlib.read_text(os.path.join(HERE, name)))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods = {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    mods = {(node.module or "").split(".")[0]}
                else:
                    mods = set()
                self.assertFalse(mods & forbidden, f"{name}:{getattr(node, 'lineno', '?')} imports {mods & forbidden}")
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and \
                        node.value.id in ("noisebank", "nb"):
                    self.assertIsNone(nb_bad.match(node.attr), f"{name}:{node.lineno} uses noisebank.{node.attr}")
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertIsNone(roots.search(node.value), f"{name}:{node.lineno} names {node.value[:60]!r}")


@unittest.skipIf(np is None, "numpy unavailable")
class TestRecoveryBankPacket(unittest.TestCase):
    """T7-7 and T7-8 (A_design_v5 3.8): the bank-mode command line end to end on the toy graph with a SYNTHETIC bank/3
    (the test flag), `obs-tables` -> `run` (subprocess workers) -> `summarize` -> `packet --mode diagnostic`; and
    `packet --mode acceptance`, which no schedule short of the frozen C2 matrix and no synthetic bank can satisfy,
    and whose C1 reads the C1-primary directory only."""

    @classmethod
    def setUpClass(cls):
        import test_graph as TG
        cls.TG = TG
        cls.tmpc = tempfile.TemporaryDirectory()
        cls.base = root = cls.tmpc.name
        graph.write(toy(opponents=12), os.path.join(root, "graph"))
        cls.gpath = os.path.join(root, "graph", "graph.jsonl.gz")
        cls.refs = os.path.join(root, "references.json")
        rqlib.write_json_durable(cls.refs, reference_panel(root))
        cls.bank = os.path.join(root, "bank_syn.json")
        rqlib.write_json_durable(cls.bank, TG.bank_doc(synthetic=True))
        cls.tables = os.path.join(root, "obs_tables.npz")
        cls.t_tables = time.time()
        cls.tables_cp = cls.cli("obs-tables", "--bank", cls.bank, "--noise-scales", "1", "--out", cls.tables,
                                "--allow-synthetic-bank")
        cls.t_tables = time.time() - cls.t_tables
        cls.num = os.path.join(root, "runs", "num")
        cls.run_cp = cls.cli("run", "--graph", cls.gpath, "--out", cls.num, "--obs-model", "bank", "--bank", cls.bank,
                             "--obs-tables", cls.tables, "--allow-synthetic-bank", "--fitter", "registered",
                             "--scenarios", "num_r1,num_r2,num_r3,num_r4", "--reps", "1", "--options", "a,fwd",
                             "--jobs", "2", "--namespace", "rq-t77", "--basis", "4")

    @classmethod
    def tearDownClass(cls):
        cls.tmpc.cleanup()

    @staticmethod
    def cli(*args):
        return subprocess.run([sys.executable, "-I", "-B", R.__file__, *args], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True)

    def schedule(self, path, dirs, om_sha=None, bank=None, tables=None):
        """A recoveryschedule/1 document at path (paths relative to its directory)."""
        rel = lambda p: os.path.relpath(p, os.path.dirname(path))  # noqa: E731
        doc = {"schema": R.SCHEDULE_SCHEMA, "observation_model_sha256": om_sha,
               "inputs": {"graph": rel(self.gpath), "references": None, "bank": rel(bank or self.bank),
                          "obs_tables": rel(tables or self.tables)},
               "directories": [dict(d, dir=rel(d["dir"])) for d in dirs]}
        rqlib.write_json_durable(path, doc)
        return path

    def legacy_entry(self, d, role, scenarios, reps, options):
        cfg = rqlib.read_json(os.path.join(d, "config.json"))
        return {"dir": d, "kind": "legacy", "role": role, "scenarios": list(scenarios), "reps": reps,
                "options": list(options), "expected_config_sha256": rqlib.canonical_sha(cfg)}

    def numerical_schedule(self):
        cfg = rqlib.read_json(os.path.join(self.num, "config.json"))
        return self.schedule(os.path.join(self.base, "SCHEDULE_num.json"),
                             [self.legacy_entry(self.num, "numerical", R.SETS["numerical"], 1, ("a", "fwd"))],
                             rqlib.canonical_sha(cfg["observation_model"]))

    def test_T7_7_bank_cli_numerical_cases_end_to_end_diagnostic_packet(self):
        """T7-7 (v2 P1, v3 mode): obs-tables builds and verifies the tables; `run --obs-model bank` writes every
        numerical result with observations.cnt = {"absent": "noiseless"}, a finite relative error and the fwd entry's
        registered not-defined record; `summarize` succeeds; `packet --mode diagnostic` on a schedule naming the four
        under role numerical passes identity, completeness and numerical, reports C1 not_evaluated ("no C1-primary
        directory scheduled"), scope "diagnostic (partial)", accepting false, no acceptance field, exit 0. Refused:
        the synthetic bank without the test flag; a noisy scenario carrying the absent-cnt record (summary and packet)."""
        self.assertEqual(self.tables_cp.returncode, 0, self.tables_cp.stderr[-3000:])
        rep = json.loads(self.tables_cp.stdout)
        self.assertEqual((rep["obs_tables_sha256"], rep["noise_scales"], rep["accepting"]),
                         (rqlib.sha256_file(self.tables), [1.0], False))
        self.assertEqual(self.run_cp.returncode, 0, self.run_cp.stdout[-3000:] + self.run_cp.stderr[-3000:])
        cfg = rqlib.read_json(os.path.join(self.num, "config.json"))
        self.assertEqual(cfg["observation_model"]["obs_tables_sha256"], rqlib.sha256_file(self.tables))
        for sc in R.SETS["numerical"]:
            r = rqlib.read_json(os.path.join(self.num, f"{sc}.000.json"))
            self.assertEqual((r["observations"]["cnt"], r["noiseless"], r["noise_source"], r["accepting"]),
                             ({"absent": "noiseless"}, True, "bank_d8", False), sc)
            self.assertTrue(math.isfinite(r["options"]["a"]["relative"]), sc)
            self.assertEqual(r["options"]["fwd"], R.NUMERICAL_FWD, sc)
        cp = self.cli("summarize", "--dir", self.num)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        self.assertEqual(json.loads(cp.stdout)["noise_source"], "bank_d8")
        sched = self.numerical_schedule()
        out = os.path.join(self.base, "PACKET_num.json")
        cp = self.cli("packet", "--mode", "diagnostic", "--schedule", sched, "--out", out, "--allow-synthetic-bank")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr[-3000:])
        p = rqlib.read_json(out)
        self.assertEqual({k: p["checks"][k]["status"] for k in ("identity", "completeness", "numerical", "pairing",
                                                                 "guards", "C1")},
                         {"identity": "pass", "completeness": "pass", "numerical": "pass", "pairing": "pass",
                          "guards": "pass", "C1": "not_evaluated"}, p["checks"])
        self.assertIn("no C1-primary directory scheduled", p["checks"]["C1"]["reason"])
        self.assertEqual((p["scope"], p["accepting"], p["exit"]), ("diagnostic (partial)", False, 0))
        self.assertNotIn("scientific_ACCEPTED", p)
        cp = self.cli("packet", "--mode", "diagnostic", "--schedule", sched, "--out", out + ".x")
        self.assertEqual(cp.returncode, 2)
        self.assertIn("synthetic: true is refused", cp.stderr)
        self.assertFalse(os.path.exists(out + ".x"))
        noisy = os.path.join(self.base, "runs", "noisy")
        a = legacy_ns(graph=self.gpath, bank=self.bank, obs_tables=self.tables, allow_synthetic_bank=True,
                      namespace="rq-t77", out=noisy)
        R.prepare_run(a)
        f = os.path.join(noisy, "r0.000.json")
        self.assertEqual(R.one(legacy_ns(**dict(vars(a), out=f, scenario="r0", rep=0))), 0)
        r = rqlib.read_json(f)
        r["observations"]["cnt"] = dict(R.ABSENT_CNT)
        rqlib.write_json_durable(f, r)
        with self.assertRaisesRegex(SystemExit, "a noisy scenario .r0. carries the absent-cnt record"):
            R.summarize(noisy)
        s2 = self.schedule(os.path.join(self.base, "SCHEDULE_noisy.json"),
                           [self.legacy_entry(noisy, "stress", ["r0"], 1, ["a"])],
                           rqlib.canonical_sha(cfg["observation_model"]))
        doc, code = R.packet(s2, "diagnostic", allow_synthetic=True)
        self.assertEqual((code, doc["checks"]["identity"]["status"]), (2, "fail"))
        self.assertIn("absent-cnt record", doc["checks"]["identity"]["reason"])
        # the numerical check: a non-finite (null) relative error, or an fwd entry that is not the registered record
        om_sha = rqlib.canonical_sha(cfg["observation_model"])
        f2 = os.path.join(self.num, "num_r2.000.json")
        good = rqlib.read_bytes(f2)
        for path, value in ((("a", "relative"), None), (("fwd", "reason"), "not the registered record")):
            r = json.loads(good)
            r["options"][path[0]][path[1]] = value
            rqlib.write_json_durable(f2, r)
            doc, code = R.packet(sched, "diagnostic", allow_synthetic=True)
            self.assertEqual((code, doc["checks"]["numerical"]["status"]), (2, "fail"), path)
            self.assertIn("num_r2.000", doc["checks"]["numerical"]["reason"])
        rqlib.write_durable(f2, good)
        # identity re-derives each configuration from the schedule's inputs and the current tools (read-only): another
        # graph (other metadata and edges) under the same directory is refused; so is a planning-mode directory
        g2 = os.path.join(self.base, "graph11")
        graph.write(toy(opponents=11), g2)
        s3 = os.path.join(self.base, "SCHEDULE_g11.json")
        doc3 = rqlib.read_json(sched)
        doc3["inputs"]["graph"] = os.path.relpath(os.path.join(g2, "graph.jsonl.gz"), self.base)
        rqlib.write_json_durable(s3, doc3)
        doc, code = R.packet(s3, "diagnostic", allow_synthetic=True)
        self.assertEqual((code, doc["checks"]["identity"]["status"]), (2, "fail"))
        self.assertIn("re-derived from the inputs and the current tools differs (['graph', 'graph_edges_sha256']",
                      doc["checks"]["identity"]["reason"])
        pl = os.path.join(self.base, "runs", "planning")
        a = legacy_ns(graph=self.gpath, namespace="rq-t77", out=pl, obs_model="planning")
        R.prepare_run(a)
        self.assertEqual(R.one(legacy_ns(**dict(vars(a), out=os.path.join(pl, "r0.000.json"), scenario="r0", rep=0))), 0)
        s4 = self.schedule(os.path.join(self.base, "SCHEDULE_plan.json"),
                           [self.legacy_entry(pl, "stress", ["r0"], 1, ["a"])], om_sha)
        doc, code = R.packet(s4, "diagnostic", allow_synthetic=True)
        self.assertEqual((code, doc["checks"]["identity"]["status"], doc["checks"]["pairing"]["status"]),
                         (2, "fail", "fail"))
        self.assertIn("planning input is refused", doc["checks"]["identity"]["reason"])

    def test_T7_8_acceptance_mode_cannot_be_weakened(self):
        """T7-8 (v3 re-review P2-3): `packet --mode acceptance` refuses T7-7's numerical-only schedule before any check
        (missing roles and C1-primary) and refuses a synthetic bank; on a schedule complete for (a toy version of) the
        C2 matrix -- an accepted-form bank, every role, a C1-primary directory and a sensitivity directory repeating
        its (scenario, rep) identities -- C1 counts the primary directory only: doctoring the sensitivity's results
        leaves C1 unchanged, doctoring the primary's changes it, and a primary whose config.json does not hash to
        expected_config_sha256 is refused. (Every legacy check is evaluated; the extra roles' directories are
        recovery_extra.py's planning-mode ones until WP5, so identity and completeness fail on them alone.)"""
        sched = self.numerical_schedule()
        cp = self.cli("packet", "--mode", "acceptance", "--schedule", sched, "--out", os.path.join(self.base, "P1.json"))
        self.assertEqual(cp.returncode, 2)
        self.assertIn("REFUSED before any check", cp.stderr)
        for gap in ("role C1-primary is not scheduled", "0 C1-primary directories", "role sensitivity is not scheduled"):
            self.assertIn(gap, cp.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.base, "P1.json")))
        cp = self.cli("packet", "--mode", "acceptance", "--schedule", sched, "--out", os.path.join(self.base, "P2.json"),
                      "--allow-synthetic-bank")
        self.assertEqual(cp.returncode, 2)
        self.assertIn("refuses --allow-synthetic-bank", cp.stderr)
        bp, tp = self.TG.bank_files()                       # (an accepted-form bank/3: synthetic false)
        tmp = tempfile.mkdtemp(dir=self.base)
        mk = lambda name, **kw: legacy_ns(**{**dict(graph=self.gpath, bank=bp, obs_tables=tp, namespace=A1,  # noqa: E731
                                                    out=os.path.join(tmp, name), options="a,fwd"), **REG_FIT, **kw})
        C1S = ("r1_034", "r2_034")
        dirs, cfgs = {}, {}
        for name, role, scen, reps, opts, kw in (("primary", "C1-primary", C1S, 20, ("a", "fwd"), {}),
                                                 ("basis8", "sensitivity", C1S, 20, ("a", "fwd"), {"basis": 8}),
                                                 ("stress", "stress", ("r0_asym",), 1, ("a", "fwd"), {}),
                                                 ("numerical", "numerical", ("num_r1",), 1, ("a",), {"options": "a"})):
            a = mk(name, scenarios=",".join(scen), **kw)
            R.prepare_run(a)
            cfg = rqlib.read_json(os.path.join(a.out, "config.json"))
            for sc in scen:
                for rep in range(reps):
                    win = not (name == "primary" and rep >= (16 if sc == "r1_034" else 17))
                    write_result(a.out, fabricated(cfg, sc, rep, success=win, options=opts))
            dirs[name] = self.legacy_entry(a.out, role, scen, reps, opts)
            cfgs[name] = cfg
        extra = []
        for op, cases, sc in (("interp", "intact", "r1_034"), ("fwd_all", "intact", "r1_034"),
                              ("fwd_early", "intact", "r1_034"), ("a", "roots0", "r0")):
            d = os.path.join(tmp, f"extra_{op}")
            self.assertEqual(extra_prepare(d, self.gpath, self.refs, namespace=A1, options=op, cases=cases,
                                           scenarios=sc), 0)
            extra.append({"dir": d, "kind": "extra", "role": "extra-attrition" if cases == "roots0" else f"extra-{op}",
                          "scenarios": [sc], "reps": 1, "options": [op], "cases": [cases],
                          "expected_plan_sha256": rqlib.canonical_sha(X.read_frozen(d))})
        toy_c2 = {"C1-primary": ({"scenarios": C1S, "reps": 20, "options": ("a", "fwd")},),
                  "stress": ({"scenarios": ("r0_asym",), "reps": 1, "options": ("a", "fwd")},),
                  "numerical": ({"scenarios": ("num_r1",), "reps": 1, "options": ("a",)},),
                  "sensitivity": ({"scenarios": C1S, "reps": 20, "options": ("a", "fwd")},),
                  **{f"extra-{op}": ({"cases": ("intact",), "scenarios": ("r1_034",), "reps": 1, "options": (op,)},)
                     for op in ("interp", "fwd_all", "fwd_early")},
                  "extra-attrition": ({"cases": ("roots0",), "scenarios": ("r0",), "reps": 1, "options": ("a",)},)}
        om_sha = rqlib.canonical_sha(cfgs["primary"]["observation_model"])
        entries = list(dirs.values()) + extra
        path = os.path.join(tmp, "SCHEDULE.json")
        with mock.patch.object(R, "C2_MATRIX", toy_c2):
            with self.assertRaisesRegex(R.Refused, "sensitivity"):
                R.packet(self.schedule(path, [e for e in entries if e["role"] != "sensitivity"], om_sha, bp, tp),
                         "acceptance")
            self.schedule(path, entries, om_sha, bp, tp)
            doc, code = R.packet(path, "acceptance")
            self.assertEqual((doc["scope"], doc["accepting"], doc["scientific_ACCEPTED"]),
                             ("bank/D8", True, "UNRESOLVED (review required, D8:327)"))
            ch = doc["checks"]
            self.assertTrue(all(c["status"] != "not_evaluated" for c in ch.values()), ch)
            self.assertEqual({k: ch[k]["status"] for k in ("numerical", "pairing", "guards", "C1")},
                             {"numerical": "pass", "pairing": "pass", "guards": "pass", "C1": "pass"}, ch)
            self.assertEqual({s: v["successes"] for s, v in ch["C1"]["scenarios"].items()}, {"r1_034": 16, "r2_034": 17})
            fails = ch["identity"]["failures"]
            self.assertEqual(len(fails), 4, fails)
            self.assertTrue(all("(extra-" in f and "planning input is refused" in f for f in fails), fails)
            self.assertEqual(code, 2)
            fr = os.path.join(dirs["stress"]["dir"], "r0_asym.000.json")     # (the guards: a decision with one root, a
            good = rqlib.read_bytes(fr)                                      #  decided unresolved forward comparison)
            for where, why in (("decision", "a decision with 1 contributing test root"),
                               ("forward", "an unresolved comparison decided")):
                r = json.loads(good)
                if where == "decision":
                    r["options"]["a"]["decision"]["test_worlds"] = 1
                else:
                    r["options"]["fwd"]["forward_transfer"]["integration_unresolved"] = 2
                rqlib.write_json_durable(fr, r)
                docg, _ = R.packet(path, "acceptance")
                self.assertEqual(docg["checks"]["guards"]["status"], "fail", where)
                self.assertIn(why, docg["checks"]["guards"]["reason"])
            rqlib.write_durable(fr, good)
            sens = dirs["basis8"]["dir"]
            for rep in range(20):                       # (the sensitivity: every r2_034 realization a failure)
                write_result(sens, fabricated(cfgs["basis8"], "r2_034", rep, success=False))
            doc2, _ = R.packet(path, "acceptance")
            self.assertEqual(doc2["checks"]["C1"], ch["C1"])
            prim = dirs["primary"]["dir"]
            write_result(prim, fabricated(cfgs["primary"], "r2_034", 0, success=False))   # (17 -> 16: still a pass)
            write_result(prim, fabricated(cfgs["primary"], "r2_034", 1, success=False))   # (16 -> 15: C1 fails)
            doc3, _ = R.packet(path, "acceptance")
            self.assertEqual(doc3["checks"]["C1"]["status"], "fail")
            self.assertEqual(doc3["checks"]["C1"]["scenarios"]["r2_034"]["successes"], 15)
            os.remove(os.path.join(prim, "r1_034.000.json"))         # (a missing realization: unsuccessful, not removed)
            doc4, _ = R.packet(path, "acceptance")
            self.assertEqual((doc4["checks"]["C1"]["scenarios"]["r1_034"]["successes"],
                              doc4["checks"]["C1"]["scenarios"]["r1_034"]["datasets"]), (15, 20))
            self.assertEqual(doc4["checks"]["completeness"]["status"], "fail")
            bad = [dict(e, expected_config_sha256="0" * 64) if e["role"] == "C1-primary" else e for e in entries]
            self.schedule(path, bad, om_sha, bp, tp)
            doc5, _ = R.packet(path, "acceptance")
            self.assertEqual(doc5["checks"]["C1"]["status"], "fail")
            self.assertIn("refused: the C1-primary config.json hashes to", doc5["checks"]["C1"]["reason"])
            self.assertIn("primary (C1-primary): config.json hashes to", doc5["checks"]["identity"]["reason"])

    @unittest.expectedFailure
    def test_T7_8_WP5_a_complete_bank_mode_schedule_passes_every_check(self):
        """T7-8's complete schedule with bank-mode recovery_extra directories passes every check (exit 0): needs
        recovery_extra.py's bank mode (v5 3.4)."""
        d = os.path.join(self.base, "extra_wp5")
        self.assertEqual(extra_prepare(d, self.gpath, self.refs, "--obs-model", "bank", "--bank", self.bank,
                                       "--obs-tables", self.tables, "--allow-synthetic-bank", namespace=A1,
                                       options="interp", scenarios="r1_034"), 0)


if __name__ == "__main__":
    unittest.main()

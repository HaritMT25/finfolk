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
import shlex
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
        import textwrap

        # Keep cleanup at an acknowledged wait until the parent has probed the
        # lock. A fixed sleep can resume after both five-second waits finish.
        ready = os.path.join(self.root, "cleanup-ready.json")
        release = os.path.join(self.root, "cleanup-release")
        unlocked = os.path.join(self.root, "cleanup-unlocked.json")
        shim = os.path.join(self.root, "supervisor-shim.py")
        with open(shim, "w") as handle:
            handle.write(textwrap.dedent("""\
                import fcntl, json, os, runpy, subprocess, sys, time
                ready, release, unlocked, script, *args = sys.argv[1:]
                original_init = subprocess.Popen.__init__
                original_wait = subprocess.Popen.wait
                original_flock = fcntl.flock
                workers = []
                acknowledged = False

                def init(self, *args, **kwargs):
                    cmd = args[0]
                    if len(cmd) > 4 and cmd[4] == "one":
                        # Stop after exec (Popen's guarded launch remains real),
                        # before the toy can finish or publish a result.
                        stop = ("import os,sys,signal,runpy,pathlib; "
                                "assert os.getppid()==int(sys.argv[1]); "
                                "assert b'one' in pathlib.Path('/proc/self/cmdline').read_bytes(); "
                                "os.kill(os.getpid(),signal.SIGSTOP); "
                                "sys.argv=sys.argv[2:]; "
                                "sys.path.insert(0,os.path.dirname(sys.argv[0])); "
                                "runpy.run_path(sys.argv[0],run_name='__main__')")
                        cmd = [cmd[0], "-I", "-B", "-c", stop, str(os.getpid()), *cmd[3:]]
                        args = (cmd, *args[1:])
                    original_init(self, *args, **kwargs)
                    workers.append(self)

                def wait(self, timeout=None):
                    global acknowledged
                    if timeout == 5 and not acknowledged:
                        acknowledged = True
                        with open(ready + ".tmp", "w") as out:
                            json.dump([p.pid for p in workers], out)
                        os.replace(ready + ".tmp", ready)
                        deadline = time.monotonic() + 60
                        while not os.path.exists(release):
                            if time.monotonic() >= deadline:
                                raise RuntimeError("test did not release cleanup")
                            time.sleep(0.01)
                    return original_wait(self, timeout=timeout)

                def flock(handle, operation):
                    if operation == fcntl.LOCK_UN and workers:
                        # Observe the real unlock, including a premature unlock
                        # after the parent's probe but before wait() returns.
                        with open(unlocked, "a") as out:
                            json.dump([{
                                "pid": p.pid, "returncode": p.returncode,
                                "exists": os.path.exists(f"/proc/{p.pid}"),
                            } for p in workers], out)
                            out.write("\\n")
                    return original_flock(handle, operation)

                subprocess.Popen.__init__ = init
                subprocess.Popen.wait = wait
                fcntl.flock = flock
                sys.argv = [script, *args]
                sys.path.insert(0, os.path.dirname(script))
                runpy.run_path(script, run_name="__main__")
                """))

        def stopped(pid):
            with open(f"/proc/{pid}/stat") as handle:
                return handle.read().rsplit(")", 1)[1].split()[0] == "T"

        def await_state(predicate, message):
            deadline = time.monotonic() + 30
            while not predicate():
                self.assertLess(time.monotonic(), deadline, message)
                time.sleep(0.01)

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
                [sys.executable, "-I", "-B", shim, ready, release, unlocked, X.__file__, *argv],
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
                        self.assertIn(pid, children(supervisor.pid))
                        os.kill(pid, signal.SIGSTOP)
                    await_state(lambda: all(stopped(pid) for pid in workers),
                                "workers did not acknowledge SIGSTOP")
                    supervisor.send_signal(sig)
                    if sig == signal.SIGTERM:
                        # The wait hook acknowledges that the handler has entered
                        # cleanup, and holds it there while we inspect the lock.
                        await_state(lambda: os.path.exists(ready), "cleanup did not start")
                        with open(ready) as handle:
                            self.assertEqual(json.load(handle), workers)
                        self.assertIsNone(supervisor.poll())
                        self.assertTrue(all(stopped(pid) for pid in workers))
                        with open(os.path.join(directory, ".lock"), "a") as lock:
                            with self.assertRaises(BlockingIOError):
                                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        supervisor.send_signal(signal.SIGTERM)  # repeated termination cannot skip cleanup
                        with open(release, "w"):
                            pass
                    status = supervisor.wait(timeout=30)
                    self.assertNotEqual(status, 0)
                    if sig == signal.SIGTERM:
                        self.assertEqual(status, 128 + signal.SIGTERM)
                        with open(unlocked) as handle:
                            unlocks = [json.loads(line) for line in handle]
                        self.assertTrue(unlocks)
                        for at_unlock in unlocks:
                            self.assertEqual([row["pid"] for row in at_unlock], workers)
                            self.assertTrue(all(row["returncode"] is not None and not row["exists"]
                                                for row in at_unlock), at_unlock)
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
        # (the candidate records the flags summarize, as the procedures store them: rank 0 and the validation winner,
        #  resolved; procedure's candidates also carry their test integration and comparison against rank 0)
        test = {} if o == "fwd" else {"test": {}}
        cands = [dict({"rank": r, "lambda": lam, "val_lpd": val, "integration": dict({"validation": {}}, **test)},
                      **({} if o == "fwd" else {"integration_unresolved": 0}))
                 for r, lam, val in ((0, 0.0, 0.0), (1, 0.05, 1.0))]
        rec_ = {"available": True, "selected": {"rank": 1, "lambda": 0.05, "start": "warm"}, "success": bool(success),
                "test_improvement": 0.1, "test_lb": lb, "fit_pairs": 100, "classes": None, "candidates": cands,
                "start": "both", "decision": {"available": True, "test_worlds": 6, "selection_unresolved": False,
                                              "integration_unresolved": 0, "reason": None}}
        if o == "fwd":                  # (forward_procedure's decided branch: available, decision_available, resolved)
            br = {"available": True, "success": bool(success), "worlds": 3, "decision_available": True,
                  "integration_unresolved": 0, "test_improvement": 0.1, "test_lb": lb, "per_world": [0.1] * 3,
                  "integration": {"selected": {}, "rank0": {}}}
            rec_.update(procedure="forward", forward_transfer=dict(br), intersection=dict(br))
        else:                           # (procedure's per-test-world comparison and restricted primary)
            rec_.update(per_test_world=[0.1] * 6, selected_primary={
                "ranks": [0, 1, 2], "rank": 1, "lambda": 0.05, "start": "warm", "available": True,
                "test_improvement": 0.1, "test_lb": lb, "success": bool(success)})
        opts[o] = rec_
    return {"schema": R.RESULT_SCHEMA, "scenario": sc, "rep": rep,
            "seed": rqlib.derive_seed(cfg["namespace"], "recovery", sc, rep), "settings": {},
            "config_sha256": rqlib.canonical_sha(cfg), "noise_source": om["noise_source"], "accepting": om["accepting"],
            "observation_model_sha256": rqlib.canonical_sha(om), "noiseless": noiseless, "observations": obsr,
            "options": opts, "reference_support": None, "fitter": "registered"}


def write_result(d, r):
    rqlib.write_json_durable(os.path.join(d, f"{r['scenario']}.{r['rep']:03d}.json"), r)


def fabricated_extra(d, case, sc, rep, success=True):
    """A recovery_extra result of d's frozen plan for (case, sc, rep), written under d/results: its identity, labels
    and body hash consistent (read_results passes), its observations hashed from (sc, rep) alone as fabricated()'s (so
    pairing compares it with every legacy directory carrying (sc, rep)), producer-shaped option records (the liveness
    matrix's states: a decided procedure for a / interp, a decided extra forward for fwd_*, the unavailable procedure
    in roots0) -> the result."""
    plan = X.read_frozen(d)
    keys = R.OBS_KEYS + (R.BANK_OBS_KEYS if plan["noise_source"] == "bank_d8" else ())
    states = TestRecoveryBankPacket.r5_states()
    opts = {}
    for op in plan["options"]:
        if case == "roots0" and not op.startswith("fwd_"):
            opts[op] = states["P7 procedure unavailable (roots)"][1]
        elif op.startswith("fwd_"):
            opts[op] = dict(states["X1 extra forward: both branches decided"][1], reference_policy=op)
        else:
            opts[op] = states["P1 decided, primary live, success" if success else
                              "P2 decided, primary live, unsuccessful"][1]
    body = X.clean({
        "schema": X.RESULT_SCHEMA, "plan_sha256": rqlib.canonical_sha(plan), "case": case, "scenario": sc, "rep": rep,
        "seed": rqlib.derive_seed(plan["namespace"], "recovery", sc, rep), "noise_source": plan["noise_source"],
        "accepting": plan["accepting"], "observation_model_sha256": plan["inputs"]["observation_model_sha256"],
        "noiseless": False,
        "observations": {k: {"shape": [100, 6], "dtype": "<f8", "sha256": sha_tag(f"{sc}:{rep}:{k}")} for k in keys},
        "scheduled_energy": 0.034, "retained_additive_projection_energy": 0.034, "options": opts})
    body["body_sha256"] = rqlib.canonical_sha(body)
    os.makedirs(os.path.join(d, "results"), exist_ok=True)
    rqlib.write_durable(os.path.join(d, "results", X.task_name((case, sc, rep))), rqlib.canonical(body))
    return body


FAST_FIT = ("--ranks", "1", "--lambdas", "0.05", "--iters", "2", "--start", "warm", "--basis", "4")
REG_EXTRA_FIT = ("--ranks", "4", "--lambdas", "0.01,0.02,0.05,0.2", "--iters", "30", "--start", "both", "--basis", "6",
                 "--embedding", "shared", "--center", "references")


def extra_prepare(out, gpath, refs, *more, namespace="rq-extra-tests", options="a", cases="intact",
                  scenarios="r0", reps=1, fit=FAST_FIT):
    """recovery_extra.py prepare (in process; planning mode unless more holds the bank flags; refs None: the assumed
    reference slots, as a legacy run without --references) -> its exit code."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return X.main(["prepare", "--graph", gpath, *(["--references", refs] if refs else []), "--namespace",
                       namespace, "--allow-toy", "--options", options, "--cases", cases, "--scenarios", scenarios,
                       "--reps", str(reps), *fit, "--out", out, *more])


def extra_one(d, gpath, task, *more, refs=None):
    """recovery_extra.py one (in process) -> its exit code."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return X.main(["one", "--dir", d, "--graph", gpath, *(["--references", refs] if refs else []), "--task", task,
                       *more])


def rewrite_extra_result(path, edit):
    """Edit a recovery_extra result in place with its body hash recomputed (a doctored but self-consistent file)."""
    r = rqlib.read_json(path)
    edit(r)
    body = {k: v for k, v in r.items() if k != "body_sha256"}
    r["body_sha256"] = rqlib.canonical_sha(body)
    rqlib.write_durable(path, rqlib.canonical(r))


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

    def test_T6_1_WP5_recovery_extra_one_routes_every_fit_through_the_bank_model(self):
        """T6-1, the extra procedures through recovery_extra's own command (v5 3.4 `one`, 3.5): a spy on map.fit while
        `recovery_extra.py one` evaluates bank-mode tasks (options a, interp, fwd_all and fwd_early; ranks 0..2, two
        lambdas, both starts; the intact case and roots2) records, for every fit, the bank's W tagged with the model's
        identity, rep_prior {nu0: nu0_C} and the score law (A, L); a planning-mode task's fits keep the planning
        variance model with no prior and no score law (planning unchanged)."""
        fit = ("--ranks", "2", "--lambdas", "0.05,0.2", "--iters", "2", "--start", "both", "--basis", "4")
        calls, real = [], M.fit

        def spy(*a, **k):
            calls.append((a[3], a[4], k.get("var_fn"), k.get("rep_prior"), k.get("score_law")))
            return real(*a, **k)
        for mode, flags in (("bank", self.bank_flags()), ("planning", ())):
            d = os.path.join(self.root, mode)
            self.assertEqual(extra_prepare(d, self.gpath, self.refs, *flags, options="a,interp,fwd_all,fwd_early",
                                           cases="intact,roots2", scenarios="r1_034", fit=fit), 0)
            calls.clear()
            with mock.patch.object(M, "fit", spy):
                for case in ("intact", "roots2"):
                    self.assertEqual(extra_one(d, self.gpath, f"{case}.r1_034.000.json", *flags, refs=self.refs), 0)
            with self.subTest(mode=mode):
                self.assertEqual({c[0] for c in calls}, {0, 1, 2})
                self.assertEqual({c[1] for c in calls if c[0]}, {0.05, 0.2})
                if mode == "bank":
                    self.assertEqual({(getattr(v, "identity", None), rqlib.canonical(p), getattr(s, "identity", None))
                                      for _, _, v, p, s in calls},
                                     {(self.obs.identity_sha, rqlib.canonical({"nu0": self.obs.nu0_C}),
                                       self.obs.identity_sha)})
                    self.assertTrue(all(isinstance(v, self.ol.WorkingVariance) and isinstance(s, self.ol.ScoreLaw)
                                        for _, _, v, _, s in calls))
                else:
                    self.assertTrue(all(callable(v) and not isinstance(v, self.ol.WorkingVariance) and p is None
                                        and s is None for _, _, v, p, s in calls))

    # ---------------------------------------------------------------- T6-5's extra branches (clarification 4 F2)
    # dc64646's recovery_extra observation code, frozen verbatim from
    # `git show dc64646:tools/redqueen/recovery_extra.py` (= 2f82515's: WP4 changed no recovery_extra.py line), each
    # text sha256-pinned and checked against git by
    # scripts_P2/wp5_main_text.sh; it runs on test_graph.main_reference()'s frozen dc64646 simulate and
    # additive_projection, with numpy, copy and hashlib the only shared modules (nothing resolves from HEAD).
    EXTRA_REF = (   # (first line, last line, sha256 of the text, the text)
        (779, 787, "15571f959630c8405f04e7bfadcc2ba119dba1fbe68fb27e755a25348bd737b1",
         '''def observation_hashes(data):
    out = {}
    for key in ("eta", "inter", "cnt", "z", "s", "s0"):
        value = np.ascontiguousarray(data[key], dtype="<f8")
        out[key] = {
            "shape": list(value.shape), "dtype": "<f8",
            "sha256": rqlib.sha256_bytes(value.tobytes(order="C")),
        }
    return out
'''),
        (790, 800, "43873f7fc4e350a7ad51379983ea62e2fa3738c046ecfe5eeb6c73609fd31370",
         '''def retained_energy(D, data, keep):
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
'''),
    )
    T65_EXTRA = ("r0", "r1_017_cap", "r0_asym", "r2_034", "r2_034_noisy")   # flat, capture-level, asym, rank 2, x2

    def extra_reference(self):
        """The frozen dc64646 extra observation code in a namespace holding the builtins, numpy, copy, an rqlib shim
        (hashlib's sha256) and an rec shim (main_reference's additive_projection) -> (namespace, main_reference)."""
        import builtins
        import types
        main = self.TG.main_reference()
        ns = {"__builtins__": builtins, "np": np, "copy": copy,
              "rqlib": types.SimpleNamespace(sha256_bytes=lambda b: hashlib.sha256(b).hexdigest()),
              "rec": types.SimpleNamespace(additive_projection=main["additive_projection"])}
        for lo, hi, sha, text in self.EXTRA_REF:
            self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), sha, f"recovery_extra.py@dc64646 L{lo}-{hi}")
            exec(compile(text, f"recovery_extra.py@dc64646:L{lo}-{hi}", "exec"), ns)
        return ns, main

    def test_T6_5_WP5_planning_extra_observation_branches_are_main_byte_for_byte(self):
        """T6-5's extra branches (v5 T6-5, 3.4, 3.7; clarification 4 F2): in planning mode, for every observation
        branch a recovery_extra plan can schedule (flat r0, capture-level r1_017_cap, asym r0_asym, rank 2 with D_S
        r2_034, doubled noise r2_034_noisy; survival in each; noiseless scenarios are refused by make_plan), the extra
        result's observation record (recovery.observation_hashes), its scheduled energy and its retained additive-
        projection energy under every case's mask (all ten) equal main dc64646's: recovery_extra's L779-787 and
        L790-800, frozen verbatim and pinned (EXTRA_REF), on dc64646's frozen simulate, in a namespace resolving nothing
        from HEAD; compared exactly (canonical JSON, floats by repr). recovery_extra one writes exactly those values."""
        ref, main = self.extra_reference()
        self.assertEqual(self.TG.reference_violations(main), [])
        D = X.data_from(self.gpath, self.refs)
        fit = dict(ranks=1, lambdas="0.05", iters=2, start="warm", basis=4, embedding="shared", center="references")
        plan = X.make_plan(D, self.gpath, self.refs, "rq-T6-5-extra", fit, ["r0"], 1, list(X.OPTIONS), list(X.CASES),
                           True)
        keeps = {case: X.mask_for(D, plan, case)[0] for case in X.CASES}
        self.assertTrue(any(not k.all() for k in keeps.values()))
        for sc in self.T65_EXTRA:
            seed = rqlib.derive_seed("rq-T6-5-extra", "recovery", sc, 0)
            head, old = R.simulate(D, R.SCENARIOS[sc], seed), main["simulate"](D, R.SCENARIOS[sc], seed)
            h = {"observations": X.observation_hashes(head), "scheduled_energy": repr(head["energy"]),
                 "retained": {c: repr(X.retained_energy(D, head, k)) for c, k in keeps.items()}}
            m = {"observations": ref["observation_hashes"](old), "scheduled_energy": repr(old["energy"]),
                 "retained": {c: repr(ref["retained_energy"](D, old, k)) for c, k in keeps.items()}}
            self.assertEqual(rqlib.canonical(h), rqlib.canonical(m), sc)
            self.assertEqual(list(h["observations"]), ["eta", "inter", "cnt", "z", "s", "s0"], sc)
        d = os.path.join(self.root, "planning")
        self.assertEqual(extra_prepare(d, self.gpath, self.refs, namespace="rq-T6-5-extra", cases="mixed"), 0)
        self.assertEqual(extra_one(d, self.gpath, "mixed.r0.000.json", refs=self.refs), 0)
        r = rqlib.read_json(os.path.join(d, "results", "mixed.r0.000.json"))
        old = main["simulate"](D, R.SCENARIOS["r0"], rqlib.derive_seed("rq-T6-5-extra", "recovery", "r0", 0))
        self.assertEqual(r["observations"], ref["observation_hashes"](old))
        self.assertEqual((repr(r["scheduled_energy"]), repr(r["retained_additive_projection_energy"])),
                         (repr(old["energy"]), repr(ref["retained_energy"](D, old, keeps["mixed"]))))

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

    def bank_flags(self, bank=None, tables=None):
        return ("--obs-model", "bank", "--bank", bank or self.bp, "--obs-tables", tables or self.tp)

    def test_T7_1_WP5_recovery_extra_binds_the_bank(self):
        """T7-1, recovery_extra's part (v5 3.4 make_plan / prepare / verified / read_results, 4.1, 4.3): a bank-mode
        plan records noise_source bank_d8, accepting, the bank artifact's, the tables' and the observation model's
        sha256 in its inputs, recovery.run_config's full observation_model as its legacy_config (the legacy record
        exactly), and
        the sources including obslaw, material, common, noisescale and the ages fixture; verified and run re-derive it
        with the model loaded from the given paths, so one changed byte of the artifact (its tables rebuilt) or a
        changed table array refuses both, as does a bank plan without its bank; a result of another observation model
        (its observation_model_sha256, noise_source or accepting label, its body hash recomputed) or with another
        mode's observations record is refused on read."""
        out = os.path.join(self.root, "extra")
        self.assertEqual(extra_prepare(out, self.gpath, self.refs, *self.bank_flags()), 0)
        plan = X.read_frozen(out)
        om = plan["legacy_config"]["observation_model"]
        self.assertEqual((plan["noise_source"], plan["accepting"], om["mode"]), ("bank_d8", True, "bank"))
        self.assertEqual(om, R.observation_model(argparse.Namespace(obs_model="bank"), self.obs))
        self.assertEqual(plan["inputs"]["bank_artifact_sha256"], rqlib.sha256_file(self.bp))
        self.assertEqual(plan["inputs"]["obs_tables_sha256"], rqlib.sha256_file(self.tp))
        self.assertEqual(plan["inputs"]["observation_model_sha256"], rqlib.canonical_sha(om))
        self.assertEqual(plan["criterion"], dict(X.CRITERION, scope="bank/D8-calibrated observation model "
                                                                    "(A_design_v5.md)"))
        for name in ("obslaw.py", "material.py", "common.py", "noisescale.py", "fixtures/registered_ages.json"):
            self.assertEqual(plan["sources_sha256"][name], rqlib.sha256_file(os.path.join(HERE, name)), name)
        self.assertEqual(X.verified(out, self.gpath, self.refs, self.bp, self.tp)[1], plan)
        import test_obslaw as TO
        bp2, tp2 = self.flipped_bank("t71x")
        data, _ = TO._rehashed_tables(rqlib.read_bytes(self.tp),
                                      {"fit_A": lambda x: x + np.where(np.arange(len(x)) == 9, 1e-9, 0.0)})
        tp3 = os.path.join(self.root, "t3.npz")
        rqlib.write_durable(tp3, data)
        for name, (b, t) in (("artifact byte", (bp2, tp2)), ("table array", (self.bp, tp3))):
            with self.subTest(changed=name):
                with self.assertRaisesRegex(SystemExit, "graph, references, sources, runtime or frozen recipe changed"):
                    X.verified(out, self.gpath, self.refs, b, t)
                with self.assertRaisesRegex(SystemExit, "graph, references, sources, runtime or frozen recipe changed"):
                    X.main(["run", "--dir", out, "--graph", self.gpath, "--references", self.refs, "--jobs", "1",
                            *self.bank_flags(b, t)])
                self.assertFalse(os.path.exists(os.path.join(out, "results")))
        with self.assertRaisesRegex(SystemExit, "a bank-mode plan: --obs-model bank --bank and --obs-tables"):
            X.verified(out, self.gpath, self.refs)
        task = "intact.r0.000.json"
        self.assertEqual(extra_one(out, self.gpath, task, *self.bank_flags(), refs=self.refs), 0)
        f = os.path.join(out, "results", task)
        good = rqlib.read_bytes(f)
        r = json.loads(good)
        self.assertEqual((r["noise_source"], r["accepting"], r["observation_model_sha256"], r["noiseless"]),
                         ("bank_d8", True, plan["inputs"]["observation_model_sha256"], False))
        self.assertEqual(list(X.read_results(out, plan)), [task])
        for field, value in (("observation_model_sha256", "0" * 64), ("noise_source", "scenario_planning_only"),
                             ("accepting", False)):
            with self.subTest(field=field):
                rewrite_extra_result(f, lambda r, field=field, value=value: r.update({field: value}))
                with self.assertRaisesRegex(SystemExit, "a result of another noise source or observation model"):
                    X.read_results(out, plan)
                rqlib.write_durable(f, good)
        rewrite_extra_result(f, lambda r: [r["observations"].pop(k) for k in R.BANK_OBS_KEYS])
        with self.assertRaisesRegex(SystemExit, "observations must hold exactly"):
            X.read_results(out, plan)
        rqlib.write_durable(f, good)
        self.assertEqual(list(X.read_results(out, plan)), [task])

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

    def test_T7_2_pairing_checks_each_directory_mode_before_any_result(self):
        """pairing (v5 3.6, 3.7; Codex WP4 P2-WP4-5) checks each directory's configuration (legacy) or frozen plan
        (extra) observation mode BEFORE reading any result: a planning run directory with no result (prepared, stopped
        before its first one), a planning run of zero repetitions, the populated planning directory and a planning-mode
        recovery_extra plan without results are each refused, alone or beside a bank directory, by the function and the
        command; an empty bank directory is accepted (nothing to compare)."""
        db, _ = self.bank_run("bank")
        plan = dict(obs_model="planning", bank=None, obs_tables=None)
        empty = os.path.join(self.root, "plan_empty")
        R.prepare_run(self.ns(out=empty, **plan))
        zero = os.path.join(self.root, "plan_zero")
        self.assertEqual(R.run(self.ns(out=zero, reps=0, **plan)), 0)
        full, _ = self.bank_run("plan_full", **plan)
        extra = os.path.join(self.root, "extra_plan")
        self.assertEqual(extra_prepare(extra, self.gpath, self.refs), 0)
        self.assertEqual((R._result_files(empty), R._result_files(zero), len(R._result_files(full))), ([], [], 1))
        for name, d in (("empty", empty), ("zero-rep", zero), ("populated", full), ("extra plan", extra)):
            with self.subTest(directory=name):
                for dirs in ([d], [db, d], [d, db]):
                    with self.assertRaisesRegex(SystemExit, "planning input is refused"):
                        R.pairing(dirs)
                with contextlib.redirect_stdout(io.StringIO()) as so:
                    with self.assertRaisesRegex(SystemExit, "planning input is refused"):
                        R.main(["pairing", "--dirs", d])
                self.assertEqual(so.getvalue(), "")
        de = os.path.join(self.root, "bank_empty")
        R.prepare_run(self.ns(out=de))
        self.assertEqual((R.pairing([de])["datasets"], R.pairing([db, de])["comparisons"]), (0, 0))

    def test_T7_3_production_records_satisfy_the_guards_and_c1_reads_their_success(self):
        """The guards' positive control (Codex WP4 P2-WP4-3): every record the procedures themselves produce in bank
        mode -- legacy option a (decided), the forward procedure (its branches), recovery_extra's a, interp, fwd_all
        and fwd_early on their views (intact and roots1), and the unavailable procedure of a one-root graph -- has no
        guard violation, and c1_success agrees with the record's success flag (a procedure's success is C1's rule)."""
        D = X.data_from(self.gpath, self.refs)
        data = R.simulate(D, R.SCENARIOS["r1_034"], 81, obs=self.obs)
        kw = dict(fitter="registered", start="both", basis=4)
        recs = {"a": R.procedure(D, data, "a", 2, [0.05, 0.2], 2, 81, **kw),
                "fwd": R.forward_procedure(D, data, 2, [0.05, 0.2], 2, 81, **kw)}
        fit = dict(ranks=2, lambdas="0.05,0.2", iters=2, start="both", basis=4, embedding="shared", center="references")
        plan = X.make_plan(D, self.gpath, self.refs, "rq-extra-tests", fit, ["r1_034"], 1, list(X.OPTIONS),
                           ["intact", "roots1"], True)
        for case in ("intact", "roots1"):
            keep = X.mask_for(D, plan, case)[0]
            for op in X.OPTIONS:
                recs[f"extra-{case}-{op}"] = X.evaluate(X.view_for(D, plan, op, keep), data, plan, 81, op)
        v = copy.copy(D)
        v.test_world = np.zeros_like(D.test_world)
        recs["one-root"] = R.procedure(v, data, "a", 1, [0.05], 2, 81, **kw)
        self.assertFalse(recs["one-root"]["available"])
        for name, o in recs.items():
            with self.subTest(record=name):
                self.assertEqual(R._guard_violations(o, name), [])
        self.assertEqual(R.c1_success(recs["a"]), recs["a"]["success"])
        self.assertFalse(R.c1_success(recs["one-root"]))

    def test_T7_2_WP5_extra_results_carry_the_legacy_observation_records(self):
        """T7-2, recovery_extra's part (v5 3.4 L779-787, 3.6): observation_hashes is recovery.py's one shared helper
        (with mu_* in bank mode); a bank-mode extra directory and a legacy bank run of one namespace carry identical
        observations for the shared (scenario, rep) -- in every case, since the masks apply after generation -- and
        `pairing` accepts the pair, compares every extra case, and refuses one doctored hash (body re-hashed)."""
        self.assertIs(X.observation_hashes, R.observation_hashes)
        d1, f1 = self.bank_run("legacy", scenario="r1_034")
        out = os.path.join(self.root, "extra")
        self.assertEqual(extra_prepare(out, self.gpath, None, *self.bank_flags(), namespace="rq-bank-t7",
                                       options="a,fwd_all", cases="intact,roots1", scenarios="r1_034"), 0)
        r1 = rqlib.read_json(f1)
        for case in ("intact", "roots1"):
            task = f"{case}.r1_034.000.json"
            self.assertEqual(extra_one(out, self.gpath, task, *self.bank_flags()), 0)
            r = rqlib.read_json(os.path.join(out, "results", task))
            self.assertEqual(r["observations"], r1["observations"], case)
        self.assertEqual(sorted(r1["observations"]), sorted(R.OBS_KEYS + R.BANK_OBS_KEYS))
        rep = R.pairing([d1, out])
        self.assertEqual((rep["datasets"], rep["comparisons"]), (1, 2))
        f = os.path.join(out, "results", "roots1.r1_034.000.json")
        rewrite_extra_result(f, lambda r: r["observations"]["mu_S"].update(sha256="0" * 64))
        self.assertEqual(len(X.read_results(out, X.read_frozen(out))), 2)    # (self-consistent: pairing alone sees it)
        with self.assertRaisesRegex(SystemExit, r"\(r1_034, 0\) has different observations"):
            R.pairing([d1, out])

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

    def test_T7_3_WP5_extra_partitions_masks_denominators_and_two_workers_in_bank_mode(self):
        """T7-3, recovery_extra's part (v5 3.4): in bank mode the 80/10/10 partition, the attrition recipes and root
        order (the plan's recipe) and every view's access sets, centring, target tables and conditioning (diagnostics)
        are the planning plan's byte for byte (observation-free); `run` accepts 1 or 2 workers only and, at 2, its
        subprocess workers receive the bank flags (every result is bank_d8: a worker without them is refused by the
        bank plan); one-root branches withhold their decisions (roots1) and every record passes the guards; a missing
        result stays in every cell's fixed denominator (unavailable = unsuccessful)."""
        kw = dict(options="a,interp,fwd_all,fwd_early", cases="intact,roots1", scenarios="r1_034", reps=2)
        pb, pp = os.path.join(self.root, "bank"), os.path.join(self.root, "plan")
        self.assertEqual(extra_prepare(pb, self.gpath, self.refs, *self.bank_flags(), **kw), 0)
        self.assertEqual(extra_prepare(pp, self.gpath, self.refs, **kw), 0)
        plan_b, plan_p = X.read_frozen(pb), X.read_frozen(pp)
        self.assertEqual(plan_b["recipe"], plan_p["recipe"])
        self.assertEqual(rqlib.read_bytes(os.path.join(pb, "diagnostics.json")),
                         rqlib.read_bytes(os.path.join(pp, "diagnostics.json")))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            X.main(["run", "--dir", pb, "--graph", self.gpath, "--references", self.refs, "--jobs", "3",
                    *self.bank_flags()])
        self.assertEqual(cm.exception.code, 2)                                    # (argparse: choices 1, 2)
        with self.assertRaisesRegex(SystemExit, "--jobs must be 1 or 2"):
            X.run(argparse.Namespace(dir=pb, graph=self.gpath, references=self.refs, jobs=3, obs_model="bank",
                                     bank=self.bp, obs_tables=self.tp, allow_synthetic_bank=False))
        with contextlib.redirect_stdout(io.StringIO()) as so:
            rc = X.main(["run", "--dir", pb, "--graph", self.gpath, "--references", self.refs, "--jobs", "2",
                         *self.bank_flags()])
        self.assertEqual(rc, 0, so.getvalue()[-2000:])
        found = X.read_results(pb, plan_b)
        self.assertEqual(sorted(found), sorted(X.task_name(t) for t in X.tasks(plan_b)))
        self.assertEqual(len(re.findall(r"^started ", so.getvalue(), re.M)), 4)
        for name, r in found.items():
            self.assertEqual((r["noise_source"], r["accepting"]), ("bank_d8", True), name)
            for op, o in r["options"].items():
                self.assertEqual(R._guard_violations(o, f"{name}:{op}"), [], (name, op))
        root1 = found["roots1.r1_034.000.json"]["options"]
        wt = root1["a"]["world_transfer"]
        self.assertEqual((wt["test_roots"], wt["available"], wt["decision_available"], wt["success"]),
                         (1, False, False, False))
        self.assertFalse(root1["a"]["decision"]["available"])
        os.remove(os.path.join(pb, "results", "intact.r1_034.001.json"))
        cells = X.summarize(pb)["cells"]
        for c in cells:
            self.assertEqual(c["datasets"], 2, c)
            if c["case"] == "intact":
                self.assertEqual((c["completed"], c["missing"]), (1, 1), c)
                self.assertEqual(c["rate"], round(c["successes"] / 2, 3), c)

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

    def test_T7_4_WP5_extra_labels_in_bank_mode(self):
        """T7-4, recovery_extra's part (v5 3.4, 3.7): bank plans, results and summaries carry noise_source bank_d8 and
        accepting (true with an accepted-form bank; false with a synthetic one, which also needs the test flag), the
        criterion scope "bank/D8-calibrated observation model (A_design_v5.md)" and no planning label; planning ones
        scenario_planning_only, accepting false, the criterion's unchanged text with accepting false, and the summary
        label "PLANNING NOISE: NOT GATE-2 EVIDENCE"; a planning result in a bank directory and a relabelled bank result
        are refused (a mixed-mode summary); bank and planning arguments do not mix."""
        task = "intact.r0.000.json"
        runs = {}
        bps, tps = self.TG.bank_files("synthetic", self.TG.bank_doc(synthetic=True))
        with self.assertRaisesRegex(SystemExit, "synthetic: true is refused"):
            extra_prepare(os.path.join(self.root, "syn0"), self.gpath, self.refs, *self.bank_flags(bps, tps))
        for name, flags in (("bank", self.bank_flags()), ("synthetic", self.bank_flags(bps, tps) +
                                                          ("--allow-synthetic-bank",)), ("planning", ())):
            d = os.path.join(self.root, name)
            self.assertEqual(extra_prepare(d, self.gpath, self.refs, *flags), 0, name)
            self.assertEqual(extra_one(d, self.gpath, task, *flags, refs=self.refs), 0, name)
            runs[name] = (d, X.read_frozen(d), rqlib.read_json(os.path.join(d, "results", task)), X.summarize(d))
        for name, (src, acc) in (("bank", ("bank_d8", True)), ("synthetic", ("bank_d8", False)),
                                 ("planning", ("scenario_planning_only", False))):
            d, plan, r, s = runs[name]
            with self.subTest(mode=name):
                self.assertEqual((plan["noise_source"], plan["accepting"]), (src, acc))
                self.assertEqual((r["noise_source"], r["accepting"], r["noiseless"]), (src, acc, False))
                self.assertEqual(r["observation_model_sha256"], plan["inputs"]["observation_model_sha256"])
                self.assertEqual((s["noise_source"], s["accepting"], s["criterion"]["scope"]),
                                 (src, acc, plan["criterion"]))
                if name == "planning":
                    self.assertEqual(plan["criterion"], dict(X.CRITERION, accepting=False))
                    self.assertEqual(s["label"], "PLANNING NOISE: NOT GATE-2 EVIDENCE")
                    self.assertEqual(sorted(r["observations"]), sorted(R.OBS_KEYS))
                    self.assertEqual(plan["inputs"]["observation_model_sha256"], rqlib.canonical_sha(
                        R.observation_model(argparse.Namespace(obs_model="planning"))))
                    self.assertEqual((plan["inputs"]["bank_artifact_sha256"], plan["inputs"]["obs_tables_sha256"]),
                                     (None, None))
                else:
                    self.assertEqual(plan["criterion"]["scope"], R.BANK_SCOPE)
                    self.assertNotIn("label", s)
                    self.assertEqual(sorted(r["observations"]), sorted(R.OBS_KEYS + R.BANK_OBS_KEYS))
        db, plan_b, rb, _ = runs["bank"]
        fb = os.path.join(db, "results", task)
        good = rqlib.read_bytes(fb)
        rp = runs["planning"][2]
        mixed = dict(rp, plan_sha256=rqlib.canonical_sha(plan_b))
        mixed["body_sha256"] = rqlib.canonical_sha({k: v for k, v in mixed.items() if k != "body_sha256"})
        rqlib.write_durable(fb, rqlib.canonical(mixed))
        with self.assertRaisesRegex(SystemExit, "a result of another noise source or observation model"):
            X.summarize(db)
        rqlib.write_durable(fb, good)
        rewrite_extra_result(fb, lambda r: r.update(noise_source="scenario_planning_only"))
        with self.assertRaisesRegex(SystemExit, "another noise source"):
            X.summarize(db)
        rqlib.write_durable(fb, good)
        self.assertTrue(X.summarize(db)["complete"])
        d = os.path.join(self.root, "mix")
        with self.assertRaisesRegex(SystemExit, "bank mode's"):
            extra_prepare(d, self.gpath, self.refs, "--bank", self.bp, "--obs-tables", self.tp)
        with self.assertRaisesRegex(SystemExit, "needs --bank and --obs-tables"):
            extra_prepare(d, self.gpath, self.refs, "--obs-model", "bank", "--bank", self.bp)
        with self.assertRaisesRegex(SystemExit, "a planning-mode plan"):
            extra_one(runs["planning"][0], self.gpath, task, *self.bank_flags(), refs=self.refs)
        self.assertFalse(os.path.exists(d))

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

    def test_T7_5_WP5_extra_refuses_cap_scenarios_in_bank_mode(self):
        """T7-5, recovery_extra's part (v5 3.4, 1.5 PC-4, 1.10): in bank mode prepare refuses a *_cap / *_cap15 scenario
        (BANK_REFUSED) before any file, and so does make_plan (the plan verified re-derives); planning mode still
        prepares them; a configuration whose ceiling M_H is 0 is refused at the load, before any file."""
        D = X.data_from(self.gpath, self.refs)
        fit = dict(ranks=1, lambdas="0.05", iters=2, start="warm", basis=4, embedding="shared", center="references")
        for sc in ("r0_cap", "r2_034_cap15"):
            out = os.path.join(self.root, sc)
            with self.subTest(sc=sc):
                with self.assertRaisesRegex(SystemExit, "BANK_REFUSED"):
                    extra_prepare(out, self.gpath, self.refs, *self.bank_flags(), scenarios=f"r0,{sc}")
                self.assertFalse(os.path.exists(out))
                with self.assertRaisesRegex(SystemExit, "BANK_REFUSED"):
                    X.make_plan(D, self.gpath, self.refs, "rq-t75", fit, [sc], 1, ["a"], ["intact"], True, obs=self.obs)
                self.assertEqual(extra_prepare(out, self.gpath, self.refs, scenarios=sc), 0)
                self.assertEqual(X.read_frozen(out)["noise_source"], "scenario_planning_only")
        real = self.ol.BankObservationModel.__init__

        def init(self_, *a, **k):
            real(self_, *a, **k)
            self_.M_H, self_.c_H = 0, 0.0
        out = os.path.join(self.root, "zero")
        with mock.patch.object(self.ol.BankObservationModel, "__init__", init):
            with self.assertRaisesRegex(SystemExit, "M_H is 0"):
                extra_prepare(out, self.gpath, self.refs, *self.bank_flags())
        self.assertFalse(os.path.exists(out))

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

    # ---------------------------------------------------------------- T7-8's complete toy schedule
    C1S = ("r1_034", "r2_034")
    VARIANTS = (("basis4", {"basis": 4}), ("basis8", {"basis": 8}), ("separate", {"embedding": "separate"}),
                ("train_c", {"center": "train_c"}))
    # (a toy version of the frozen C2 matrix: its roles, a few of its blocks, four sensitivity blocks)
    TOY_C2 = {"C1-primary": ({"scenarios": C1S, "reps": 20, "options": ("a", "fwd")},),
              "stress": ({"scenarios": ("r0_asym",), "reps": 1, "options": ("a", "fwd")},),
              "numerical": ({"scenarios": ("num_r1",), "reps": 1, "options": ("a",)},),
              "sensitivity": ({"scenarios": C1S, "reps": 20, "options": ("a", "fwd")},) * 4,
              **{f"extra-{op}": ({"cases": ("intact",), "scenarios": ("r1_034",), "reps": 1, "options": (op,)},)
                 for op in ("interp", "fwd_all", "fwd_early")},
              "extra-attrition": ({"cases": ("roots0",), "scenarios": ("r0",), "reps": 1, "options": ("a",)},)}
    _complete = None

    def legacy_dir(self, root, name, scen, reps, opts, wins=lambda sc, rep: True, **kw):
        """A bank-mode legacy directory under root: prepare_run with the accepted-form bank, the registered settings
        (REG_FIT, overridden by kw) and namespace A1, then fabricated results (wins(sc, rep): success) -> (dir, cfg)."""
        bp, tp = self.TG.bank_files()
        a = legacy_ns(**{**dict(graph=self.gpath, bank=bp, obs_tables=tp, namespace=A1, out=os.path.join(root, name),
                                options=",".join(opts), scenarios=",".join(scen)), **REG_FIT, **kw})
        R.prepare_run(a)
        cfg = rqlib.read_json(os.path.join(a.out, "config.json"))
        for sc in scen:
            for rep in range(reps):
                write_result(a.out, fabricated(cfg, sc, rep, success=wins(sc, rep), options=opts))
        return a.out, cfg

    def complete(self):
        """A fresh copy of T7-8's complete toy schedule (built once per class): an accepted-form bank; the C1-primary
        (r1_034 and r2_034 x 20, 16 and 17 successes); the four sensitivity variants (the same identities, every
        realization a success); stress (r0_asym x 1); numerical (num_r1, option a); every legacy directory with the
        registered settings and namespace A1; the four extra roles' BANK-MODE recovery_extra plans (WP5: prepared with
        --obs-model bank from the same bank and tables, the registered fit, namespace A1, the assumed reference slots
        as the legacy directories and the schedule) with one fabricated_extra result per scheduled task -> {path
        (SCHEDULE.json), entries, dirs (role key -> entry), cfgs, om_sha, bp, tp}."""
        cls = type(self)
        if cls._complete is None:
            root = tempfile.mkdtemp(dir=self.base)
            spec = [("primary", "C1-primary", self.C1S, 20, ("a", "fwd"),
                     lambda sc, rep: rep < (16 if sc == "r1_034" else 17), {}),
                    ("stress", "stress", ("r0_asym",), 1, ("a", "fwd"), lambda sc, rep: True, {}),
                    ("numerical", "numerical", ("num_r1",), 1, ("a",), lambda sc, rep: True, {"options": "a"})]
            spec += [(v, "sensitivity", self.C1S, 20, ("a", "fwd"), lambda sc, rep: True, kw)
                     for v, kw in self.VARIANTS]
            made = []
            for name, role, scen, reps, opts, wins, kw in spec:
                d, _ = self.legacy_dir(root, name, scen, reps, opts, wins, **kw)
                made.append((name, role, scen, reps, opts))
            bp, tp = self.TG.bank_files()
            for op, cases, sc in (("interp", "intact", "r1_034"), ("fwd_all", "intact", "r1_034"),
                                  ("fwd_early", "intact", "r1_034"), ("a", "roots0", "r0")):
                d = os.path.join(root, f"extra_{op}")
                self.assertEqual(extra_prepare(d, self.gpath, None, "--obs-model", "bank", "--bank", bp,
                                               "--obs-tables", tp, namespace=A1, options=op, cases=cases,
                                               scenarios=sc, fit=REG_EXTRA_FIT), 0)
                fabricated_extra(d, cases, sc, 0)
                made.append((f"extra_{op}", "extra-attrition" if cases == "roots0" else f"extra-{op}", (sc,), 1,
                             (op,), cases))
            cls._complete = (root, made)
        root, made = cls._complete
        new = tempfile.mkdtemp(dir=self.base)
        dirs, cfgs, entries = {}, {}, []
        for item in made:
            name, role, scen, reps, opts = item[:5]
            d = os.path.join(new, name)
            shutil.copytree(os.path.join(root, name), d)
            if name.startswith("extra_"):
                e = {"dir": d, "kind": "extra", "role": role, "scenarios": list(scen), "reps": reps,
                     "options": list(opts), "cases": [item[5]], "expected_plan_sha256": rqlib.canonical_sha(
                         X.read_frozen(d))}
            else:
                e = self.legacy_entry(d, role, scen, reps, opts)
                cfgs[name] = rqlib.read_json(os.path.join(d, "config.json"))
            dirs[name] = e
            entries.append(e)
        bp, tp = self.TG.bank_files()
        om_sha = rqlib.canonical_sha(cfgs["primary"]["observation_model"])
        path = self.schedule(os.path.join(new, "SCHEDULE.json"), entries, om_sha, bp, tp)
        return {"path": path, "entries": entries, "dirs": dirs, "cfgs": cfgs, "om_sha": om_sha, "bp": bp, "tp": tp,
                "root": new}

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
        C2 matrix (complete(): an accepted-form bank, every role, a C1-primary directory and the four sensitivity
        variants repeating its (scenario, rep) identities, the registered settings everywhere) C1 counts the primary
        directory only: doctoring a sensitivity's results leaves C1 unchanged, doctoring the primary's changes it, and
        a primary whose config.json does not hash to expected_config_sha256 is refused. (Every check is evaluated and,
        from WP5 on, with the extra roles' bank-mode plans and results, every check passes before the doctoring.)"""
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
        f = self.complete()
        path, entries, dirs, cfgs, om_sha, bp, tp = (f[k] for k in ("path", "entries", "dirs", "cfgs", "om_sha", "bp",
                                                                    "tp"))
        with mock.patch.object(R, "C2_MATRIX", self.TOY_C2):
            with self.assertRaisesRegex(R.Refused, "sensitivity"):
                R.packet(self.schedule(path, [e for e in entries if e["role"] != "sensitivity"], om_sha, bp, tp),
                         "acceptance")
            self.schedule(path, entries, om_sha, bp, tp)
            doc, code = R.packet(path, "acceptance")
            self.assertEqual((doc["scope"], doc["accepting"], doc["scientific_ACCEPTED"]),
                             ("bank/D8", True, "UNRESOLVED (review required, D8:327)"))
            ch = doc["checks"]
            self.assertTrue(all(c["status"] != "not_evaluated" for c in ch.values()), ch)
            self.assertEqual({k: ch[k]["status"] for k in ("numerical", "guards", "C1")},
                             {"numerical": "pass", "guards": "pass", "C1": "pass"}, ch)
            self.assertEqual({s: v["successes"] for s, v in ch["C1"]["scenarios"].items()}, {"r1_034": 16, "r2_034": 17})
            self.assertEqual({k: c["status"] for k, c in ch.items()}, dict.fromkeys(ch, "pass"), ch)    # (WP5)
            self.assertEqual(code, 0)
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
            for rep in range(20):                       # (a sensitivity: every r2_034 realization a failure)
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

    def refused(self, f, entries, *pattern):
        """packet --mode acceptance on f's schedule rewritten with entries (each with its own correct expected hash) ->
        asserts it is refused before any check with every pattern in the reason, with the toy C2 matrix's roles and
        blocks complete (schedule_gaps empty), so the refusal is the bound-settings check's; and through the CLI: exit
        2, REFUSED, no packet file."""
        path = self.schedule(f["path"], entries, f["om_sha"], f["bp"], f["tp"])
        with mock.patch.object(R, "C2_MATRIX", self.TOY_C2):
            base = os.path.dirname(path)
            self.assertEqual(R.schedule_gaps(R._schedule_entries(rqlib.read_json(path), base)), [])
            with self.assertRaises(R.Refused) as cm:
                R.packet(path, "acceptance")
        for p in pattern:
            self.assertRegex(str(cm.exception), p)
        return str(cm.exception)

    def test_T7_8_acceptance_refuses_sensitivities_that_are_not_the_four_variants(self):
        """P2-WP4-2 (Codex WP4; CRITERION C2: "Each of basis4, basis8, separate-embedding and train_c centering"):
        acceptance mode validates each sensitivity directory's BOUND configuration, so four distinct copies of the
        ordinary basis 6 / shared / references run scheduled as the sensitivities -- each with its correct expected
        configuration hash, the roles and blocks complete -- are refused before any check, and so are two copies of one
        variant with another missing, and a directory changing two settings at once (basis 4 and separate)."""
        f = self.complete()
        rest = [e for e in f["entries"] if e["role"] != "sensitivity"]
        copies = []
        for i in range(4):
            d, _ = self.legacy_dir(f["root"], f"copy{i}", self.C1S, 20, ("a", "fwd"))
            copies.append(self.legacy_entry(d, "sensitivity", self.C1S, 20, ("a", "fwd")))
        self.assertEqual(len({e["expected_config_sha256"] for e in copies}), 1)        # (the ordinary run's config)
        self.assertEqual(copies[0]["expected_config_sha256"], f["dirs"]["primary"]["expected_config_sha256"])
        msg = self.refused(f, rest + copies, r"bound settings do not satisfy the C2 matrix",
                           r"copy0 \(sensitivity\): basis / embedding / center .* is none of the four sensitivity",
                           r"sensitivity variant basis4: 0 directories", r"sensitivity variant train_c: 0 directories")
        self.assertEqual(msg.count("is none of the four sensitivity variants"), 4)
        sens = {k: f["dirs"][k] for k, _ in self.VARIANTS}
        dup, _ = self.legacy_dir(f["root"], "basis8_again", self.C1S, 20, ("a", "fwd"), basis=8)
        twice = [sens["basis8"], self.legacy_entry(dup, "sensitivity", self.C1S, 20, ("a", "fwd")), sens["separate"],
                 sens["train_c"]]
        self.refused(f, rest + twice, r"sensitivity variant basis8: 2 directories", r"basis4: 0 directories")
        two, _ = self.legacy_dir(f["root"], "basis4_separate", self.C1S, 20, ("a", "fwd"), basis=4,
                                 embedding="separate")
        both = [self.legacy_entry(two, "sensitivity", self.C1S, 20, ("a", "fwd")), sens["basis8"], sens["separate"],
                sens["train_c"]]
        self.refused(f, rest + both, r"basis4_separate \(sensitivity\): .* is none of the four",
                     r"sensitivity variant basis4: 0 directories")
        sched = self.schedule(f["path"], rest + copies, f["om_sha"], f["bp"], f["tp"])
        out = os.path.join(f["root"], "PACKET.json")
        with mock.patch.object(R, "C2_MATRIX", self.TOY_C2), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(R.main(["packet", "--mode", "acceptance", "--schedule", sched, "--out", out]), 2)
        self.assertIn("REFUSED before any check", err.getvalue())
        self.assertFalse(os.path.exists(out))

    def test_T7_8_acceptance_refuses_roles_without_their_registered_fit_settings(self):
        """P2-WP4-2 (Codex WP4; CRITERION C2: "All noisy fits use ranks 0..4, lambdas .01,.02,.05,.2, 30 sweeps, both
        starts; default basis6/shared/references"; "Numerical checks retain the source's own fixed true-rank
        continuation (.3,.1,.03,.01)", the registered map's): a stress directory with reduced ranks, penalties or
        sweeps, or another start, each with its own correct expected hash, is refused in acceptance mode before any
        check; so is a C1-primary or stress directory off the default surface, a numerical directory fitted by the
        minimal fitter (its continuation runs to .001), and (PROPOSED READING S6) an extra-role plan whose fit is not
        the registered one. Diagnostic mode still accepts reduced settings (tests)."""
        f = self.complete()
        rest = [e for e in f["entries"] if e["role"] != "stress"]
        for name, kw, want in (("ranks", {"ranks": 1}, r"'ranks': 1"),
                               ("lambdas", {"lambdas": "0.05"}, r"'lambdas': '0.05'"),
                               ("sweeps", {"iters": 2}, r"'iters': 2"),
                               ("start", {"start": "warm"}, r"'start': 'warm'"),
                               ("surface", {"embedding": "separate"}, r"not the default")):
            with self.subTest(stress=name):
                d, _ = self.legacy_dir(f["root"], f"stress_{name}", ("r0_asym",), 1, ("a", "fwd"), **kw)
                e = self.legacy_entry(d, "stress", ("r0_asym",), 1, ("a", "fwd"))
                self.refused(f, rest + [e], rf"stress_{name} \(stress\): ", want)
        d, _ = self.legacy_dir(f["root"], "primary_b4", self.C1S, 20, ("a", "fwd"), basis=4)
        prim = self.legacy_entry(d, "C1-primary", self.C1S, 20, ("a", "fwd"))
        self.refused(f, [e for e in f["entries"] if e["role"] != "C1-primary"] + [prim],
                     r"primary_b4 \(C1-primary\): basis / embedding / center .* not the default")
        d, _ = self.legacy_dir(f["root"], "numerical_minimal", ("num_r1",), 1, ("a",), fitter="minimal",
                               options="a", lambdas=None, iters=None, start=None, basis=None, embedding=None,
                               center=None)
        num = self.legacy_entry(d, "numerical", ("num_r1",), 1, ("a",))
        self.refused(f, [e for e in f["entries"] if e["role"] != "numerical"] + [num],
                     r"numerical_minimal \(numerical\): not the registered fit settings .*'fitter': 'minimal'")
        d = os.path.join(f["root"], "extra_interp_fast")
        self.assertEqual(extra_prepare(d, self.gpath, self.refs, namespace=A1, options="interp", cases="intact",
                                       scenarios="r1_034"), 0)
        ex = dict(f["dirs"]["extra_interp"], dir=d, expected_plan_sha256=rqlib.canonical_sha(X.read_frozen(d)))
        self.refused(f, [e for e in f["entries"] if e["role"] != "extra-interp"] + [ex],
                     r"extra_interp_fast \(extra-interp\): not the registered fit settings .*'ranks': 1")
        sd = self.schedule(os.path.join(f["root"], "SCHEDULE_diag.json"),
                           [self.legacy_entry(os.path.join(f["root"], "stress_ranks"), "stress", ("r0_asym",), 1,
                                              ("a", "fwd"))], f["om_sha"], f["bp"], f["tp"])
        doc, code = R.packet(sd, "diagnostic")
        self.assertEqual((code, doc["checks"]["identity"]["status"]), (0, "pass"), doc["checks"])

    def test_T7_8_c1_counts_only_available_resolved_successes(self):
        """P2-WP4-3 (Codex WP4; CRITERION C1: "selected rank > 0 AND ... lower bound > 0, with an available resolved
        comparison and at least two contributing test roots. Unavailable ... realizations are unsuccessful"): of the
        primary's 16 r1_034 successes, one whose success flag stays true is made unavailable (decision.available false,
        six roots, no integration flag: Codex's counterexample), unresolved (an integration flag, a selection flag),
        one-root, unavailable at the top level, or inconsistent with the rule (selected rank 0; a non-positive lower
        bound), or (round 3) unresolved only in its candidate records (the winner's stored comparison, its test
        integration, a validation flag) while every decision flag says resolved: each time C1 counts 15 (fail) and
        reports the uncounted flag; the guards fail where the record is internally inconsistent (a selected rank 0
        is not the validation winner, rank 1, of its candidates)."""
        f = self.complete()
        prim = f["dirs"]["primary"]["dir"]
        fr = os.path.join(prim, "r1_034.003.json")
        good = rqlib.read_bytes(fr)
        win = lambda o: o["candidates"][1]  # noqa: E731
        cases = (("decision unavailable", lambda o: o["decision"].update(available=False), True),
                 ("integration unresolved", lambda o: o["decision"].update(integration_unresolved=1), True),
                 ("selection unresolved", lambda o: o["decision"].update(selection_unresolved=True), True),
                 ("one test root", lambda o: o["decision"].update(test_worlds=1), True),
                 ("top-level unavailable", lambda o: o.update(available=False), True),
                 ("selected rank 0", lambda o: o["selected"].update(rank=0), True),
                 ("lower bound <= 0", lambda o: o.update(test_lb=-0.01), False),
                 ("winner's stored comparison unresolved", lambda o: win(o).update(integration_unresolved=1), True),
                 ("winner's test integration unresolved", lambda o: win(o)["integration"].update(
                     test={"grid_unresolved": 1}), True),
                 ("a candidate's validation unresolved", lambda o: o["candidates"][0]["integration"].update(
                     validation={"grid_unresolved": 1}), True))
        with mock.patch.object(R, "C2_MATRIX", self.TOY_C2):
            doc, _ = R.packet(f["path"], "acceptance")
            self.assertEqual(doc["checks"]["C1"]["scenarios"]["r1_034"]["successes"], 16)
            for name, edit, guard in cases:
                with self.subTest(case=name):
                    r = json.loads(good)
                    self.assertIs(r["options"]["a"]["success"], True)
                    edit(r["options"]["a"])
                    rqlib.write_json_durable(fr, r)
                    doc, code = R.packet(f["path"], "acceptance")
                    c1 = doc["checks"]["C1"]
                    self.assertEqual((c1["status"], c1["scenarios"]["r1_034"]["successes"]), ("fail", 15))
                    self.assertEqual(c1["scenarios"]["r1_034"]["success_flags_not_counted"], 1)
                    self.assertEqual(doc["checks"]["guards"]["status"], "fail" if guard else "pass", name)
                    self.assertEqual(code, 2)
            rqlib.write_durable(fr, good)

    def test_T7_8_guards_check_unsuccessful_decisions_branches_and_primary_selections(self):
        """P2-WP4-3 (Codex WP4; CRITERION C4, C6): the guards check availability and unresolved-state consistency of
        the top-level decision, every branch and the primary selection, SUCCESSFUL OR NOT. Reported: Codex's
        intersection branch (available, decision_available, unsuccessful, integration_unresolved 1), in a packet and
        alone; a branch decided while unavailable, or unresolved yet marked available; an unsuccessful top-level
        decision on an unresolved selection or while the record is unavailable; a success whose decision is
        unavailable; an unresolved primary selection marked available. Permitted (C4): unavailable branches, a one-root
        descriptive score, an unresolved branch left unavailable, an unavailable procedure."""
        f = self.complete()
        cfg = f["cfgs"]["stress"]
        ok = fabricated(cfg, "r0_asym", 0, success=False)["options"]
        self.assertEqual(R._guard_violations(ok["a"], "a") + R._guard_violations(ok["fwd"], "fwd"), [])

        def viol(opt, edit):
            o = copy.deepcopy(ok[opt])
            edit(o)
            return R._guard_violations(o, opt)
        bad = {"intersection decided though unresolved (Codex)":
               ("fwd", lambda o: o["intersection"].update(available=True, decision_available=True, success=False,
                                                          integration_unresolved=1)),
               "branch decided while unavailable": ("fwd", lambda o: o["forward_transfer"].update(available=False)),
               "branch unresolved yet available": ("fwd", lambda o: o["intersection"].update(
                   decision_available=False, integration_unresolved=2)),
               "unsuccessful decision on an unresolved selection": ("a", lambda o: o["decision"].update(
                   selection_unresolved=True)),
               "unsuccessful decision while unavailable": ("a", lambda o: o.update(available=False)),
               "success with an unavailable decision": ("a", lambda o: (o.update(success=True),
                                                                        o["decision"].update(available=False))),
               "unresolved primary selection available": ("a", lambda o: o.update(selected_primary={
                   "available": True, "success": False, "selection_unresolved": True}))}
        for name, (opt, edit) in bad.items():
            with self.subTest(bad=name):
                self.assertTrue(viol(opt, edit), name)
        fine = {"unavailable branch": ("fwd", lambda o: o.update(intersection={"available": False,
                                                                             "reason": "no targets"})),
                "one-root descriptive score": ("fwd", lambda o: o.update(intersection={
                    "available": False, "decision_available": False, "success": False, "descriptive": True,
                    "test_roots": 1, "worlds": 1, "integration_unresolved": 0, "test_improvement": 0.2})),
                "unresolved branch left unavailable": ("fwd", lambda o: o.update(intersection={
                    "available": False, "integration_unresolved": 2, "worlds": 3, "reason": "unresolved"})),
                "unavailable procedure": ("a", lambda o: (o.clear(), o.update(available=False, reason="1 root",
                                                                              test_roots=1)))}
        for name, (opt, edit) in fine.items():
            with self.subTest(fine=name):
                self.assertEqual(viol(opt, edit), [], name)
        fr = os.path.join(f["dirs"]["stress"]["dir"], "r0_asym.000.json")
        r = rqlib.read_json(fr)
        r["options"]["fwd"]["intersection"].update(available=True, decision_available=True, success=False,
                                                   integration_unresolved=1)
        rqlib.write_json_durable(fr, r)
        with mock.patch.object(R, "C2_MATRIX", self.TOY_C2):
            doc, code = R.packet(f["path"], "acceptance")
        self.assertEqual((doc["checks"]["guards"]["status"], code), ("fail", 2))
        self.assertIn("r0_asym.000.json:fwd.intersection: an unresolved comparison decided",
                      doc["checks"]["guards"]["reason"])

    def test_T7_8_the_schedule_is_clarification_4_F1s_representation(self):
        """Clarification 4 F1 (WP4 stop S1): the schedule holds exactly schema, observation_model_sha256, inputs and
        directories; inputs exactly graph, references (a path or null), bank, obs_tables; each directory exactly v5
        3.8's fields for its kind; reps a positive integer; every path relative to the schedule file's directory.
        Each extra key, missing key, non-positive or non-integer reps and absolute path is refused before any check;
        the valid numerical schedule passes from another working directory, and the same document moved into a
        subdirectory no longer finds its relative paths."""
        sched = self.numerical_schedule()
        good = rqlib.read_json(sched)
        doc, code = R.packet(sched, "diagnostic", allow_synthetic=True)
        self.assertEqual(code, 0)

        def refused(mutate, pattern, where=None):
            d = copy.deepcopy(good)
            mutate(d)
            p = where or os.path.join(self.base, "SCHEDULE_f1.json")
            rqlib.write_json_durable(p, d)
            with self.assertRaisesRegex(R.Refused, pattern):
                R.packet(p, "diagnostic", allow_synthetic=True)
        e0 = lambda d: d["directories"][0]  # noqa: E731
        cases = {"extra top-level key": (lambda d: d.update(note="x"), r"exactly .*extra \['note'\]"),
                 "missing top-level key": (lambda d: d.pop("observation_model_sha256"),
                                           r"missing \['observation_model_sha256'\]"),
                 "extra inputs key": (lambda d: d["inputs"].update(design="x"), r"inputs must hold exactly"),
                 "missing inputs key": (lambda d: d["inputs"].pop("references"), r"missing \['references'\]"),
                 "extra directory field": (lambda d: e0(d).update(variant="basis4"), r"extra \['variant'\]"),
                 "missing directory field": (lambda d: e0(d).pop("options"), r"missing \['options'\]"),
                 "reps 0": (lambda d: e0(d).update(reps=0), r"reps must be an integer >= 1"),
                 "reps -1": (lambda d: e0(d).update(reps=-1), r"reps must be an integer >= 1"),
                 "reps true": (lambda d: e0(d).update(reps=True), r"reps must be an integer >= 1"),
                 "reps 1.0": (lambda d: e0(d).update(reps=1.0), r"reps must be an integer >= 1"),
                 "absolute dir": (lambda d: e0(d).update(dir=self.num), r"is absolute"),
                 "absolute bank": (lambda d: d["inputs"].update(bank=self.bank), r"inputs.bank: .* is absolute")}
        for name, (mutate, pattern) in cases.items():
            with self.subTest(case=name):
                refused(mutate, pattern)
        cp = subprocess.run([sys.executable, "-I", "-B", R.__file__, "packet", "--mode", "diagnostic", "--schedule",
                             sched, "--out", os.path.join(self.base, "P_cwd.json"), "--allow-synthetic-bank"],
                            cwd=tempfile.mkdtemp(dir=self.base), stdin=subprocess.DEVNULL, capture_output=True,
                            text=True)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        sub = os.path.join(self.base, "moved")
        os.makedirs(sub, exist_ok=True)
        refused(lambda d: None, r"the scheduled bank / tables", os.path.join(sub, "SCHEDULE_num.json"))

    def test_T7_8_schedule_read_and_validation_failures_are_contextual_exit_2_refusals(self):
        """P3-WP4-6 (Codex WP4): every schedule read or validation failure -- a missing file, invalid or duplicate-key
        JSON, a non-object document, an object among the scenarios, a non-list scenarios or directories, a role that
        is a list, a non-string input path -- is a contextual REFUSED with exit 2 and no packet file, never an
        uncaught exception (in process through main, and as a command)."""
        good = rqlib.read_json(self.numerical_schedule())
        p = os.path.join(self.base, "SCHEDULE_p3.json")
        out = os.path.join(self.base, "P_p3.json")

        def doc(edit):
            d = copy.deepcopy(good)
            edit(d)
            return rqlib.canonical(d)
        e0 = lambda d: d["directories"][0]  # noqa: E731
        cases = {"missing file": (None, r"cannot be read"),
                 "invalid JSON": (b"{not json", r"is not strict JSON"),
                 "duplicate key": (b'{"schema": "a", "schema": "b"}', r"duplicate key"),
                 "a list document": (b"[]", r"is not a finfolk.redqueen.recoveryschedule/1 document"),
                 "an object in scenarios": (doc(lambda d: e0(d)["scenarios"].append({"x": 1})),
                                            r"scenarios must be distinct registered scenarios"),
                 "scenarios an object": (doc(lambda d: e0(d).update(scenarios={"num_r1": 1})),
                                         r"scenarios must be distinct registered scenarios"),
                 "directories an object": (doc(lambda d: d.update(directories={"a": 1})), r"names no directory"),
                 "role a list": (doc(lambda d: e0(d).update(role=["numerical"])), r"is not one of"),
                 "graph a number": (doc(lambda d: d["inputs"].update(graph=7)), r"inputs.graph: a non-empty path")}
        for name, (raw, pattern) in cases.items():
            with self.subTest(case=name):
                if os.path.exists(p):
                    os.remove(p)
                if raw is not None:
                    rqlib.write_durable(p, raw)
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    rc = R.main(["packet", "--mode", "diagnostic", "--schedule", p, "--out", out,
                                 "--allow-synthetic-bank"])
                self.assertEqual(rc, 2)
                self.assertIn("REFUSED before any check", err.getvalue())
                self.assertRegex(err.getvalue(), pattern)
                self.assertFalse(os.path.exists(out))
        for name in ("missing file", "an object in scenarios"):
            with self.subTest(command=name):
                if os.path.exists(p):
                    os.remove(p)
                if cases[name][0] is not None:
                    rqlib.write_durable(p, cases[name][0])
                cp = self.cli("packet", "--mode", "diagnostic", "--schedule", p, "--out", out, "--allow-synthetic-bank")
                self.assertEqual(cp.returncode, 2, cp.stderr[-2000:])
                self.assertNotIn("Traceback", cp.stderr)
                self.assertRegex(cp.stderr, cases[name][1])

    def test_T7_7_obs_tables_never_replaces_a_concurrent_publication(self):
        """P2-WP4-4 (Codex WP4): obs-tables publishes with no replacement. Two real processes race to the same absent
        --out with different scales (1 and 1,2). A FIFO stands in for each one's --bank and is fed only after BOTH
        processes are reading it, so both have passed the existence check and both build; exactly one publishes
        (exit 0), the other refuses ("published by another command", exit 1) and leaves the winner's bytes intact:
        the file is the winner's reported sha256 and holds the winner's scales; neither leaves a temporary file."""
        import errno
        import threading

        import obslaw
        if not hasattr(os, "mkfifo"):
            self.skipTest("no FIFOs on this platform")
        raw = rqlib.read_bytes(self.bank)
        d, fd_dir = tempfile.mkdtemp(dir=self.base), tempfile.mkdtemp(dir=self.base)
        out = os.path.join(d, "obs_tables.npz")
        barrier = threading.Barrier(2)
        procs, threads = [], []

        def feed(fifo, proc):
            fd = None
            while fd is None:                  # (opens once the process is reading --bank: past the existence check)
                try:
                    fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
                except OSError as e:
                    if e.errno != errno.ENXIO or proc.poll() is not None:
                        return
                    time.sleep(0.02)
            os.set_blocking(fd, True)
            try:
                barrier.wait(timeout=300)      # (both processes are past the existence check)
            except threading.BrokenBarrierError:
                pass
            with os.fdopen(fd, "wb") as w:
                w.write(raw)
            plain = fifo + ".plain"            # (--bank's later read, verifying the built tables, finds a plain
            rqlib.write_durable(plain, raw)    #  file of the same bytes; the process's open FIFO is unaffected)
            os.replace(plain, fifo)
        for i, scales in enumerate(("1", "1,2")):
            fifo = os.path.join(fd_dir, f"bank{i}.json")
            os.mkfifo(fifo)
            p = subprocess.Popen([sys.executable, "-I", "-B", R.__file__, "obs-tables", "--bank", fifo,
                                  "--noise-scales", scales, "--out", out, "--allow-synthetic-bank"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            procs.append((scales, p))
            threads.append(threading.Thread(target=feed, args=(fifo, p), daemon=True))
        for t in threads:
            t.start()
        res = [(scales, p.returncode, so, se) for scales, p in procs for so, se in [p.communicate(timeout=1200)]]
        for t in threads:
            t.join(timeout=60)
        self.assertEqual(sorted(rc for _, rc, _, _ in res), [0, 1], [(s, rc, se[-800:]) for s, rc, _, se in res])
        (wscales, _, wout, _), = [x for x in res if x[1] == 0]
        (_, _, _, lerr), = [x for x in res if x[1] == 1]
        self.assertIn("was published by another command while these tables were built", lerr)
        self.assertIn("left intact", lerr)
        self.assertNotIn("Traceback", lerr)
        rep = json.loads(wout)
        self.assertEqual(rep["obs_tables_sha256"], rqlib.sha256_file(out))
        self.assertEqual(rep["noise_scales"], [float(x) for x in wscales.split(",")])
        tabs = obslaw.ObsTables.load(out, sha256=rep["obs_tables_sha256"])
        self.assertEqual(sorted({g for _, g in tabs.location}), rep["noise_scales"])
        self.assertEqual(os.listdir(d), ["obs_tables.npz"])

    def test_T7_8_guards_check_the_restricted_primary_comparison_and_every_flag_against_its_records(self):
        """P2-WP4-3, round 3 (Codex WP4 r2): the guards derive each flag from the stored candidate and integration
        records, as procedure does. Codex's exact case: the full winner rank 3, resolved, six roots; the restricted
        winner rank 1 with integration_unresolved 1 (also when only the stored flag, or only its test integration, says
        so); the primary available, unsuccessful, no selection_unresolved -- is reported, alone and in a packet. The
        primary stays independent of higher-rank failures: a rank-3 validation flag or comparison leaves the full
        decision unavailable and an available rank-1 primary unreported. The audit's other paths are each reported:
        a decided full selection whose winner's comparison or a candidate's validation is unresolved in the records
        only, a selected candidate that is not the validation winner, a primary that is not the restricted winner, a
        decision without candidate records, a per-test-world record of the wrong length, a decided forward branch
        whose integration record is unresolved, a forward decision or success its decision branch does not carry."""
        f = self.complete()
        base = fabricated(f["cfgs"]["stress"], "r0_asym", 0, success=True)["options"]

        def cand(rank, lam, val, unres=0, vflag=0, tflag=0):
            return {"rank": rank, "lambda": lam, "val_lpd": val, "integration_unresolved": unres,
                    "integration": {"validation": {"grid_unresolved": vflag} if vflag else {},
                                    "test": {"grid_unresolved": tflag} if tflag else {}}}

        def proc(cands, selected, decision, success, primary, per=6):
            o = copy.deepcopy(base["a"])
            o.update(candidates=cands, selected=dict(selected, start="warm"), success=success,
                     per_test_world=[0.1] * per if per else [], decision=dict(
                         {"available": True, "test_worlds": 6, "selection_unresolved": False,
                          "integration_unresolved": 0, "reason": None}, **decision),
                     selected_primary=dict({"ranks": [0, 1, 2], "start": "warm", "test_improvement": 0.1,
                                            "test_lb": 0.01}, **primary))
            return o
        r13 = {"rank": 3, "lambda": 0.05}
        r1 = {"rank": 1, "lambda": 0.05}
        codex = {"stored and integration flags": (1, 1), "the stored flag only": (1, 0),
                 "the test integration only": (0, 1)}
        for name, (unres, tflag) in codex.items():
            with self.subTest(codex=name):
                o = proc([cand(0, 0.0, 0.0), cand(1, 0.05, 1.0, unres=unres, tflag=tflag), cand(3, 0.05, 2.0)], r13,
                         {}, True, dict(r1, available=True, success=False))
                self.assertNotIn("selection_unresolved", o["selected_primary"])
                self.assertIn("a.selected_primary: available or successful on an unresolved restricted selection or "
                              "comparison", "; ".join(R._guard_violations(o, "a")))
        for name, c3 in (("rank-3 validation flag", cand(3, 0.05, 2.0, vflag=1)),
                         ("rank-3 comparison unresolved", cand(3, 0.05, 2.0, unres=1, tflag=1))):
            with self.subTest(independent=name):
                o = proc([cand(0, 0.0, 0.0), cand(1, 0.05, 1.0), c3], r13,
                         {"available": False, "selection_unresolved": bool(c3["integration"]["validation"]),
                          "integration_unresolved": 1, "reason": "unresolved"}, False,
                         dict(r1, available=True, success=True), per=0)
                self.assertEqual(R._guard_violations(o, "a"), [])
        resolved = [cand(0, 0.0, 0.0), cand(1, 0.05, 1.0), cand(3, 0.05, 2.0)]
        self.assertEqual(R._guard_violations(proc(resolved, r13, {}, True, dict(r1, available=True, success=True)),
                                             "a"), [])
        bad = {"winner's comparison unresolved in the records only": (
                   proc([cand(0, 0.0, 0.0), cand(1, 0.05, 1.0), cand(3, 0.05, 2.0, unres=1)], r13, {}, False,
                        dict(r1, available=True, success=True)), "decided on an unresolved selection or comparison"),
               "a candidate's validation flag only": (
                   proc([cand(0, 0.0, 0.0), cand(1, 0.05, 1.0), cand(3, 0.05, 2.0, vflag=1)], r13, {}, False,
                        dict(r1, available=False, success=False)), "decided on an unresolved selection"),
               "selected is not the validation winner": (
                   proc(resolved, r1, {}, False, dict(r1, available=True, success=True)),
                   "the selected candidate (1, 0.05) is not the validation winner (3, 0.05)"),
               "primary is not the restricted winner": (
                   proc(resolved, r13, {}, False, dict(r13, available=True, success=True)),
                   "selected_primary: (3, 0.05) is not the restricted validation winner (1, 0.05)"),
               "a decision without candidate records": (
                   proc([], r13, {}, False, dict(r1, available=False, success=False)),
                   "a decision without its candidate records"),
               "per-test-world record of the wrong length": (
                   proc(resolved, r13, {}, False, dict(r1, available=True, success=True), per=5),
                   "5 per-world comparison(s) for 6 recorded contributing root(s)")}
        fw = copy.deepcopy(base["fwd"])
        fw["intersection"]["integration"] = {"selected": {"grid_unresolved": 1}, "rank0": {}}
        bad["a decided forward branch whose integration record is unresolved"] = (
            fw, "fwd.intersection: decided or available on an unresolved comparison")
        fw = copy.deepcopy(base["fwd"])
        fw["forward_transfer"].update(available=False, decision_available=False, success=False)
        bad["a forward decision its decision branch does not carry"] = (
            fw, "a decision whose decision branch is not decided")
        fw = copy.deepcopy(base["fwd"])
        fw["forward_transfer"]["success"] = False
        bad["a forward success its decision branch does not carry"] = (
            fw, "success whose decision branch is not successful")
        for name, (o, want) in bad.items():
            with self.subTest(audit=name):
                got = "; ".join(R._guard_violations(o, "fwd" if "forward" in name else "a"))
                self.assertIn(want, got)
        fr = os.path.join(f["dirs"]["stress"]["dir"], "r0_asym.000.json")
        r = rqlib.read_json(fr)
        r["options"]["a"] = proc([cand(0, 0.0, 0.0), cand(1, 0.05, 1.0, unres=1, tflag=1), cand(3, 0.05, 2.0)], r13,
                                 {}, True, dict(r1, available=True, success=False))
        rqlib.write_json_durable(fr, r)
        with mock.patch.object(R, "C2_MATRIX", self.TOY_C2):
            doc, code = R.packet(f["path"], "acceptance")
        self.assertEqual((doc["checks"]["guards"]["status"], code), ("fail", 2))
        self.assertIn("r0_asym.000.json:a.selected_primary: available or successful on an unresolved restricted",
                      doc["checks"]["guards"]["reason"])

    def doctored(self, f, name, role_key, edit):
        """A copy of f's role_key directory whose bound config.json (legacy) or frozen plan.json (extra, re-frozen:
        FROZEN.sha256 rewritten) is changed by edit, with its own correct expected sha256 -> its schedule entry."""
        e = f["dirs"][role_key]
        d = os.path.join(f["root"], name)
        shutil.copytree(e["dir"], d)
        if e["kind"] == "legacy":
            cfg = rqlib.read_json(os.path.join(d, "config.json"))
            edit(cfg)
            rqlib.write_durable(os.path.join(d, "config.json"), rqlib.canonical(cfg))
            return dict(e, dir=d, expected_config_sha256=rqlib.canonical_sha(cfg))
        plan = X.read_frozen(d)
        edit(plan)
        files = {"plan.json": rqlib.canonical(plan),
                 "diagnostics.json": rqlib.read_bytes(os.path.join(d, "diagnostics.json"))}
        rqlib.write_durable(os.path.join(d, "plan.json"), files["plan.json"])
        rqlib.write_durable(os.path.join(d, "FROZEN.sha256"), X.freeze_text(files))
        self.assertEqual(X.read_frozen(d), plan)
        return dict(e, dir=d, expected_plan_sha256=rqlib.canonical_sha(plan))

    def test_T7_8_acceptance_applies_clarification_4_F3_to_the_numerical_and_extra_roles(self):
        """Clarification 4 F3 (frozen 87053a80...; WP4 stops S5 / S6): in acceptance mode the numerical directory's
        bound configuration is fitter registered, basis 6, embedding shared, center references, ab_cap -1, recording
        ranks 4, lambdas 0.01,0.02,0.05,0.2, iters 30 and start both; each extra noisy role's plan fit is ranks 4,
        lambdas 0.01,0.02,0.05,0.2, iters 30, start both, basis 6, embedding shared, center references, and its
        legacy_config fitter registered and ab_cap -1. Each field's departure alone -- ab_cap included -- with its own
        correct expected hash is refused before any check, naming the field. Diagnostic mode still accepts a numerical
        directory with reduced settings. (The fields are F3's text, listed here, never read from recovery.py's
        constants: a field dropped from those constants is caught by its departure being admitted.)"""
        f = self.complete()
        surface = ("basis", "embedding", "center")
        num = {"fitter": "minimal", "basis": 4, "embedding": "separate", "center": "train_c", "ab_cap": 0,
               "ranks": 1, "lambdas": "0.05", "iters": 2, "start": "warm"}
        for k, val in num.items():
            with self.subTest(numerical=k):
                e = self.doctored(f, f"num_{k}", "numerical", lambda c, k=k, val=val: c.update({k: val}))
                want = (r"basis / embedding / center .* not the default" if k in surface else
                        rf"not the registered fit settings \(\{{'{k}': {val!r}\}}")
                self.refused(f, [x for x in f["entries"] if x["role"] != "numerical"] + [e],
                             rf"num_{k} \(numerical\): {want}")
        extra = {"ranks": 1, "lambdas": "0.05", "iters": 2, "start": "warm", "basis": 4, "embedding": "separate",
                 "center": "train_c"}
        legacy = {"fitter": "minimal", "ab_cap": 0}
        for part, fields in (("fit", extra), ("legacy_config", legacy)):
            for k, val in fields.items():
                with self.subTest(extra=f"{part}.{k}"):
                    e = self.doctored(f, f"ext_{k}", "extra_interp",
                                      lambda p, part=part, k=k, val=val: p[part].update({k: val}))
                    want = (r"basis / embedding / center .* not the default" if k in surface else
                            rf"not the registered fit settings \(\{{'{k}': {val!r}\}}")
                    self.refused(f, [x for x in f["entries"] if x["role"] != "extra-interp"] + [e],
                                 rf"ext_{k} \(extra-interp\): {want}")
        d, _ = self.legacy_dir(f["root"], "num_reduced", ("num_r1",), 1, ("a",), options="a", ranks=1, iters=2,
                               start="warm", basis=4)
        sd = self.schedule(os.path.join(f["root"], "SCHEDULE_num_diag.json"),
                           [self.legacy_entry(d, "numerical", ("num_r1",), 1, ("a",))], f["om_sha"], f["bp"], f["tp"])
        doc, code = R.packet(sd, "diagnostic")
        self.assertEqual((code, doc["checks"]["identity"]["status"]), (0, "pass"), doc["checks"])

    def test_T7_7_obs_tables_publication_failures_are_contextual_refusals(self):
        """P3-R2-1 (Codex WP4 r2): every publication OSError of obs-tables is a contextual refusal. A failed hard link
        (EPERM, as on a filesystem refusing links) publishes nothing and leaves no file; a failed directory fsync after
        the link says the verified tables ARE published (their sha256) and leaves exactly that file. Neither escapes
        as a traceback. (The tables are the class's own, loaded instead of rebuilt; validation and publication run.)"""
        import errno

        import obslaw
        built = obslaw.ObsTables.load(self.tables)
        sha = rqlib.sha256_bytes(built.to_bytes())
        d = tempfile.mkdtemp(dir=self.base)
        out = os.path.join(d, "obs_tables.npz")
        args = ["obs-tables", "--bank", self.bank, "--noise-scales", "1", "--out", out, "--allow-synthetic-bank"]
        with mock.patch.object(obslaw, "build_obs_tables", lambda bank, g: built), \
                mock.patch.object(R.os, "link", side_effect=OSError(errno.EPERM, "Operation not permitted")):
            with self.assertRaisesRegex(SystemExit, r"publishing .* by a hard link failed \(PermissionError: .*"
                                                    r"NOTHING was published"):
                R.main(args)
        self.assertEqual(os.listdir(d), [])
        real = rqlib.fsync_dir

        def fail(p):
            if os.path.abspath(p) == os.path.abspath(d):
                raise OSError(errno.EIO, "Input/output error")
            return real(p)
        with mock.patch.object(obslaw, "build_obs_tables", lambda bank, g: built), \
                mock.patch.object(R.rqlib, "fsync_dir", fail):
            with self.assertRaisesRegex(SystemExit, rf"IS PUBLISHED \(the verified tables, sha256 {sha}\), but the "
                                                    r"directory fsync after the link failed \(OSError: "):
                R.main(args)
        self.assertEqual(os.listdir(d), ["obs_tables.npz"])
        self.assertEqual(rqlib.sha256_file(out), sha)

    def test_T7_8_a_schedule_nested_beyond_the_parser_is_a_contextual_refusal(self):
        """P3-WP4-6, remaining (Codex WP4 r2): a RecursionError from the schedule's JSON parser is a contextual REFUSED
        (exit 2, "nested deeper than the parser's recursion limit", no packet file), never an escaping exception. The
        RecursionError is INJECTED at the parser packet calls (json.loads), so the check does not depend on how deep an
        interpreter's parser can go: in process through main, and in a separate process (python -c with the same
        patch) for the exit code and the absence of a traceback. A natural, very deep schedule (arrays, objects) is
        refused too -- exit 2, no packet file, no traceback -- by the depth refusal, or by the schema check where the
        interpreter parses that depth (Python 3.14 does: a20af4d's CI)."""
        p = os.path.join(self.base, "SCHEDULE_deep.json")
        out = os.path.join(self.base, "P_deep.json")
        depth = "nested deeper than the parser's recursion limit"
        rqlib.write_durable(p, b"[[[]]]")

        def too_deep(*a, **k):
            raise RecursionError("maximum recursion depth exceeded while decoding a JSON array from a unicode string")
        with mock.patch.object(R.json, "loads", too_deep), contextlib.redirect_stderr(io.StringIO()) as err:
            rc = R.main(["packet", "--mode", "diagnostic", "--schedule", p, "--out", out, "--allow-synthetic-bank"])
        self.assertEqual(rc, 2)
        self.assertIn(f"REFUSED before any check: the schedule {p} is not strict JSON ({depth})", err.getvalue())
        self.assertFalse(os.path.exists(out))
        code = ("import json, sys\nsys.path.insert(0, sys.argv[1])\nimport recovery\n"
                "def too_deep(*a, **k):\n    raise RecursionError('maximum recursion depth exceeded')\n"
                "json.loads = too_deep\nsys.exit(recovery.main(sys.argv[2:]))\n")
        cp = subprocess.run([sys.executable, "-I", "-B", "-c", code, HERE, "packet", "--mode", "acceptance",
                             "--schedule", p, "--out", out], stdin=subprocess.DEVNULL, capture_output=True, text=True)
        self.assertEqual(cp.returncode, 2, cp.stderr[-1500:])
        self.assertNotIn("Traceback", cp.stderr)
        self.assertIn(depth, cp.stderr)
        self.assertFalse(os.path.exists(out))
        for name, raw in (("arrays", b"[" * 100000 + b"]" * 100000),
                          ("objects", b'{"a":' * 100000 + b"1" + b"}" * 100000)):
            with self.subTest(nesting=name):
                rqlib.write_durable(p, raw)
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    rc = R.main(["packet", "--mode", "diagnostic", "--schedule", p, "--out", out,
                                 "--allow-synthetic-bank"])
                self.assertEqual(rc, 2)
                self.assertRegex(err.getvalue(), rf"REFUSED before any check: (the schedule .* \({depth}\)|the "
                                                 r"schedule is not a finfolk\.redqueen\.recoveryschedule/1 document)")
                self.assertFalse(os.path.exists(out))
                cp = self.cli("packet", "--mode", "acceptance", "--schedule", p, "--out", out)
                self.assertEqual(cp.returncode, 2, cp.stderr[-1500:])
                self.assertNotIn("Traceback", cp.stderr)
                self.assertIn("REFUSED before any check", cp.stderr)
                self.assertFalse(os.path.exists(out))

    # ---------------------------------------------------------------- round 4 (Codex WP4 r3)
    @staticmethod
    def without(rec, path):
        """A deep copy of rec with the field at path (a tuple of keys / list indices) deleted."""
        out = copy.deepcopy(rec)
        parent = out
        for k in path[:-1]:
            parent = parent[k]
        del parent[path[-1]]
        return out

    def r4_records(self):
        """A decided, successful selection-and-prediction record (option a: candidates rank 0, rank 1 -- the restricted
        winner -- and rank 3, the full winner; six roots; a live restricted primary) and a decided, successful forward
        record (fabricated's), both consistent: no guard violation, C1 counts the first."""
        f = self.complete()
        base = fabricated(f["cfgs"]["stress"], "r0_asym", 0, success=True)["options"]

        def cand(rank, lam, val):
            return {"rank": rank, "lambda": lam, "val_lpd": val, "integration_unresolved": 0,
                    "integration": {"validation": {}, "test": {}}}
        a = copy.deepcopy(base["a"])
        a.update(candidates=[cand(0, 0.0, 0.0), cand(1, 0.05, 1.0), cand(3, 0.05, 2.0)],
                 selected={"rank": 3, "lambda": 0.05, "start": "warm"},
                 selected_primary={"ranks": [0, 1, 2], "rank": 1, "lambda": 0.05, "start": "warm", "available": True,
                                   "test_improvement": 0.1, "test_lb": 0.01, "success": True})
        a.pop("available")                      # (as procedure writes an available record: no "available" key)
        fw = copy.deepcopy(base["fwd"])
        self.assertEqual((R._guard_violations(a, "a"), R._guard_violations(fw, "fwd"), R.c1_success(a)), ([], [], True))
        return f, a, fw

    def test_T7_8_guards_require_every_record_they_read_the_deletion_table(self):
        """P2, round 4 (Codex WP4 r3: missing integration records were read as resolved): every record field a live
        guard or C1 path reads must be present with the producer's shape -- deleting any one of them is a violation (C1
        then never counts the record), never zero flags. Codex's counterexample (integration and integration_unresolved
        stripped from every candidate of a successful option-a record) is reported and C1 refuses it, alone and in a
        packet; so is a forward branch without its integration object. The table deletes, in turn, every field of the
        TABLE below from a consistent decided record (option a with a live restricted primary; forward with two decided
        branches). Fields the producers write only conditionally (a record's "available" when false,
        selection_unresolved when true, a missing selected_primary, which claims nothing) are outside it. The
        restricted primary stays
        independent: a missing higher-rank record fails the full selection only, and nothing when only the primary is
        live. Empty integration objects, as the producers write them, are valid."""
        f, a, fw = self.r4_records()
        cands = range(3)
        table_a = ([("success",), ("selected",), ("selected", "rank"), ("selected", "lambda"), ("decision",),
                    ("decision", "available"), ("decision", "test_worlds"), ("decision", "selection_unresolved"),
                    ("decision", "integration_unresolved"), ("per_test_world",), ("candidates",)]
                   + [("candidates", i, k) for i in cands for k in ("rank", "lambda", "val_lpd", "integration")]
                   + [("candidates", i, "integration", "validation") for i in cands]
                   + [("candidates", i, "integration", "test") for i in (0, 1, 2)]          # (rank 0 and both winners)
                   + [("candidates", i, "integration_unresolved") for i in (1, 2)]         # (the two winners)
                   + [("selected_primary", k) for k in ("rank", "lambda", "available", "success")])
        table_fw = ([("success",), ("selected",), ("selected", "rank"), ("selected", "lambda"), ("decision",),
                     ("decision", "available"), ("decision", "selection_unresolved"),
                     ("decision", "integration_unresolved"), ("candidates",)]
                    + [("candidates", i, k) for i in range(2) for k in ("rank", "lambda", "val_lpd", "integration")]
                    + [("candidates", i, "integration", "validation") for i in range(2)]
                    + [(b, k) for b in ("forward_transfer", "intersection")
                       for k in ("available", "decision_available", "success", "worlds", "integration",
                                 "integration_unresolved", "per_world")]
                    + [(b, "integration", k) for b in ("forward_transfer", "intersection")
                       for k in ("selected", "rank0")])
        for name, rec, table in (("a", a, table_a), ("fwd", fw, table_fw)):
            for path in table:
                with self.subTest(record=name, delete=".".join(map(str, path))):
                    d = self.without(rec, path)
                    self.assertTrue(R._guard_violations(d, name), path)
                    if name == "a":
                        self.assertFalse(R.c1_success(d), path)
        with self.subTest(c1_only="test_lb"):
            self.assertFalse(R.c1_success(self.without(a, ("test_lb",))))
        stripped = copy.deepcopy(a)                 # (Codex's exact counterexample)
        for c in stripped["candidates"]:
            c.pop("integration")
            c.pop("integration_unresolved")
        got = "; ".join(R._guard_violations(stripped, "a"))
        self.assertIn("a.candidates[0]: integration.validation is absent", got)
        self.assertIn("a.candidates[2]: integration_unresolved is absent", got)
        self.assertFalse(R.c1_success(stripped))
        self.assertIn("fwd.intersection: integration.selected is absent",
                      "; ".join(R._guard_violations(self.without(fw, ("intersection", "integration")), "fwd")))
        hi = self.without(a, ("candidates", 2, "integration", "validation"))     # (a higher-rank record missing)
        got = R._guard_violations(hi, "a")
        self.assertTrue(got)
        self.assertFalse([x for x in got if "selected_primary" in x], got)
        only = copy.deepcopy(hi)                    # (only the primary live: the rank-3 record is not read at all)
        only.update(success=False, per_test_world=[],
                    decision=dict(only["decision"], available=False, selection_unresolved=True,
                                  integration_unresolved=1))
        self.assertEqual(R._guard_violations(only, "a"), [])
        prim = f["dirs"]["primary"]["dir"]
        fr = os.path.join(prim, "r1_034.003.json")
        r = rqlib.read_json(fr)
        for c in r["options"]["a"]["candidates"]:
            c.pop("integration")
            c.pop("integration_unresolved")
        rqlib.write_json_durable(fr, r)
        with mock.patch.object(R, "C2_MATRIX", self.TOY_C2):
            doc, code = R.packet(f["path"], "acceptance")
        self.assertEqual((doc["checks"]["guards"]["status"], doc["checks"]["C1"]["scenarios"]["r1_034"]["successes"],
                          doc["checks"]["C1"]["status"], code), ("fail", 15, "fail", 2))
        self.assertIn("r1_034.003.json:a.candidates[0]: integration.validation is absent",
                      doc["checks"]["guards"]["reason"])

    def test_T7_8_an_unrepresentable_number_is_a_contextual_failure(self):
        """P3-R3-1 (Codex WP4 r3): a JSON integer no float represents (1 followed by 400 zeros) as a candidate's
        val_lpd, the test_lb or a numerical relative error is a contextual violation / failed check -- never an
        OverflowError: the guards name the field, C1 does not count the record, the packet's guards / C1 / numerical checks fail with
        context. recovery_extra's "-Infinity" text stays a valid score."""
        huge = 10 ** 400
        f, a, fw = self.r4_records()
        bad = copy.deepcopy(a)
        bad["candidates"][1]["val_lpd"] = huge
        self.assertIn("a.candidates[1]: val_lpd is not a score", "; ".join(R._guard_violations(bad, "a")))
        self.assertFalse(R.c1_success(bad))
        self.assertFalse(R.c1_success(dict(a, test_lb=huge)))
        ninf = copy.deepcopy(a)                     # (rank 0 scored -inf, as recovery_extra stores it: valid)
        ninf["candidates"][0]["val_lpd"] = "-Infinity"
        self.assertEqual(R._guard_violations(ninf, "a"), [])
        self.assertTrue(R.c1_success(ninf))
        fr = os.path.join(f["dirs"]["primary"]["dir"], "r1_034.003.json")
        r = rqlib.read_json(fr)
        r["options"]["a"]["candidates"][1]["val_lpd"] = huge
        rqlib.write_json_durable(fr, r)
        self.assertIn(str(huge), rqlib.read_text(fr))
        with mock.patch.object(R, "C2_MATRIX", self.TOY_C2):
            doc, code = R.packet(f["path"], "acceptance")
        self.assertEqual((doc["checks"]["guards"]["status"], doc["checks"]["C1"]["scenarios"]["r1_034"]["successes"],
                          code), ("fail", 15, 2))
        self.assertIn("val_lpd is not a score", doc["checks"]["guards"]["reason"])
        d = os.path.join(f["root"], "num_huge")
        shutil.copytree(self.num, d)
        fn = os.path.join(d, "num_r2.000.json")
        r = rqlib.read_json(fn)
        r["options"]["a"]["relative"] = huge
        rqlib.write_json_durable(fn, r)
        cfg = rqlib.read_json(os.path.join(d, "config.json"))
        sched = self.schedule(os.path.join(f["root"], "SCHEDULE_huge.json"),
                              [self.legacy_entry(d, "numerical", R.SETS["numerical"], 1, ("a", "fwd"))],
                              rqlib.canonical_sha(cfg["observation_model"]))
        doc, code = R.packet(sched, "diagnostic", allow_synthetic=True)
        self.assertEqual((doc["checks"]["numerical"]["status"], code), ("fail", 2))
        self.assertIn("num_r2.000", doc["checks"]["numerical"]["reason"])

    def test_T7_8_recursion_in_any_packet_input_is_a_contextual_refusal_or_failed_check(self):
        """P3-R3-2 (Codex WP4 r3): a RecursionError from the parser at ANY packet input -- injected at json.loads for
        a document carrying a marker, so it does not depend on an interpreter's C stack -- is named: an input read
        before any check (the bank via load_model, the observation tables, a bound configuration or frozen plan in
        acceptance mode's settings check) is REFUSED (exit 2, no packet file); one read inside the checks (a result, a
        configuration in diagnostic mode) is a contextual failed check. Never an escaping exception, in process or
        (the bank) in a separate process."""
        import obslaw
        mark = "@@DEEP-INJECTED@@"
        real = json.loads

        def loads(s, *a, **k):
            t = s.decode("utf-8", "replace") if isinstance(s, (bytes, bytearray)) else s
            if mark in t:
                raise RecursionError("maximum recursion depth exceeded while decoding a JSON object")
            return real(s, *a, **k)
        deep = '{"x": "%s"}' % mark
        f = self.complete()

        def refused(entries, pattern, **inputs):
            path = self.schedule(f["path"], entries, f["om_sha"], inputs.get("bank", f["bp"]), f["tp"])
            out = os.path.join(f["root"], "P_deep.json")
            with mock.patch.object(R, "C2_MATRIX", self.TOY_C2), mock.patch.object(json, "loads", loads), \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                rc = R.main(["packet", "--mode", "acceptance", "--schedule", path, "--out", out])
            self.assertEqual(rc, 2)
            self.assertIn("REFUSED before any check", err.getvalue())
            self.assertRegex(err.getvalue(), pattern)
            self.assertIn("nested deeper than the parser's recursion limit", err.getvalue())
            self.assertFalse(os.path.exists(out))
        bank = os.path.join(f["root"], "bank_deep.json")
        rqlib.write_durable(bank, deep)
        with self.subTest(input="bank"):
            refused(f["entries"], r"the bank artifact .*bank_deep\.json is nested", bank=bank)
        with self.subTest(input="tables"), mock.patch.object(obslaw.ObsTables, "from_bytes",
                                                             side_effect=RecursionError("deep")):
            refused(f["entries"], r"the observation tables .* is nested")
        with self.subTest(input="bound configuration"):
            e = dict(f["dirs"]["stress"])
            d = os.path.join(f["root"], "stress_deep")
            shutil.copytree(e["dir"], d)
            rqlib.write_durable(os.path.join(d, "config.json"), deep)
            refused([x for x in f["entries"] if x["role"] != "stress"] + [dict(e, dir=d)],
                    r"stress_deep \(stress\): its bound configuration or plan cannot be read .*config\.json: nested")
        with self.subTest(input="frozen plan"):
            e = dict(f["dirs"]["extra_interp"])
            d = os.path.join(f["root"], "extra_deep")
            shutil.copytree(e["dir"], d)
            files = {"plan.json": deep.encode(),
                     "diagnostics.json": rqlib.read_bytes(os.path.join(d, "diagnostics.json"))}
            rqlib.write_durable(os.path.join(d, "plan.json"), files["plan.json"])
            rqlib.write_durable(os.path.join(d, "FROZEN.sha256"), X.freeze_text(files))
            refused([x for x in f["entries"] if x["role"] != "extra-interp"] + [dict(e, dir=d)],
                    r"extra_deep \(extra-interp\): its bound configuration or plan cannot be read .*nested")
        with self.subTest(input="a result, inside the checks"):
            fr = os.path.join(f["dirs"]["primary"]["dir"], "r1_034.003.json")
            good = rqlib.read_bytes(fr)
            rqlib.write_durable(fr, deep)
            path = self.schedule(f["path"], f["entries"], f["om_sha"], f["bp"], f["tp"])
            with mock.patch.object(R, "C2_MATRIX", self.TOY_C2), mock.patch.object(json, "loads", loads):
                doc, code = R.packet(path, "acceptance")
            ch = doc["checks"]
            self.assertEqual(code, 2)
            for k in ("identity", "completeness", "guards"):
                self.assertEqual(ch[k]["status"], "fail", k)
                self.assertIn("r1_034.003.json", ch[k]["reason"], k)
                self.assertIn("nested deeper than the parser's recursion limit", ch[k]["reason"], k)
            self.assertEqual(ch["C1"]["scenarios"]["r1_034"]["successes"], 15)
            # (this schedule's pairing stops first at the planning-mode extra plans; pairing reading the result:)
            with mock.patch.object(json, "loads", loads):
                with self.assertRaisesRegex(SystemExit, r"pairing: .*primary: a result cannot be read \(.*"
                                                        r"r1_034\.003\.json: nested deeper than the parser's"):
                    R.pairing([f["dirs"]["primary"]["dir"]])
            rqlib.write_durable(fr, good)
        with self.subTest(input="a configuration, inside the checks (diagnostic)"):
            d = os.path.join(f["root"], "num_deep")
            shutil.copytree(self.num, d)
            cfg = rqlib.read_json(os.path.join(d, "config.json"))
            entry = self.legacy_entry(d, "numerical", R.SETS["numerical"], 1, ("a", "fwd"))
            rqlib.write_durable(os.path.join(d, "config.json"), deep)
            sched = self.schedule(os.path.join(f["root"], "SCHEDULE_numdeep.json"), [entry],
                                  rqlib.canonical_sha(cfg["observation_model"]))
            with mock.patch.object(json, "loads", loads):
                doc, code = R.packet(sched, "diagnostic", allow_synthetic=True)
            self.assertEqual(code, 2)
            for k in ("identity", "pairing", "guards"):
                self.assertEqual(doc["checks"][k]["status"], "fail", k)
                self.assertIn("nested deeper than the parser's recursion limit", doc["checks"][k]["reason"], k)
        code = ("import json, sys\nsys.path.insert(0, sys.argv[1])\nimport recovery\nreal = json.loads\n"
                "def loads(s, *a, **k):\n"
                "    t = s.decode('utf-8', 'replace') if isinstance(s, (bytes, bytearray)) else s\n"
                f"    if {mark!r} in t:\n        raise RecursionError('maximum recursion depth exceeded')\n"
                "    return real(s, *a, **k)\n"
                "json.loads = loads\nsys.exit(recovery.main(sys.argv[2:]))\n")
        path = self.schedule(f["path"], f["entries"], f["om_sha"], bank, f["tp"])
        out = os.path.join(f["root"], "P_deep_cli.json")
        cp = subprocess.run([sys.executable, "-I", "-B", "-c", code, HERE, "packet", "--mode", "diagnostic",
                             "--schedule", path, "--out", out], stdin=subprocess.DEVNULL, capture_output=True,
                            text=True)
        self.assertEqual(cp.returncode, 2, cp.stderr[-1500:])
        self.assertNotIn("Traceback", cp.stderr)
        self.assertIn("the bank artifact", cp.stderr)
        self.assertFalse(os.path.exists(out))

    # ---------------------------------------------------------------- round 5 (Codex WP4 r4): the liveness matrix
    @staticmethod
    def r5_states():
        """Producer-shaped records, a REPRESENTATIVE set of the liveness states the producers emit (hand-built after the
        cited producer lines, not generated from them; recovery_extra's actually produced records are the WP5 matrix's,
        r5_real_states), plus two availability-only inputs the guards support -> {name: (kind, record, producer)}.
        Kinds: the selection-and-prediction procedure (recovery.py procedure, L989-1107: option a, and recovery_extra's
        a / interp with several test worlds, recovery_extra.py L864-869), the legacy forward procedure (recovery.py
        forward_procedure, L1110-1187), recovery_extra's forward (recovery_extra.py forward, L730-850) and its one-root
        merged record (recovery_extra.py evaluate, L857-863). Integration records carry grid_unresolved as the
        registered map writes them (map.py L1237: 0 when resolved). (Line numbers @WP5; R5_CITES checks them.)"""
        def info(g=0):
            return {"pairs": 4, "grid_unresolved": g}

        def pcand(rank, lam, val, vg=0, tg=0):           # (procedure's _cand_record, L949-964, and L1037-1044)
            return {"rank": rank, "lambda": lam, "val_lpd": val, "val_lpd_gauss": val, "start": "warm",
                    "integration": {"validation": info(vg), "test": info(tg)}, "test_rmse_truth": None,
                    "test_improvement": None if tg else 0.1, "test_lb": None if tg else 0.01,
                    "integration_unresolved": tg, "test_improvement_gauss": 0.1, "test_lb_gauss": 0.01}

        def fcand(rank, lam, val, vg=0):                 # (forward's _cand_record: validation integration only)
            return {"rank": rank, "lambda": lam, "val_lpd": val, "val_lpd_gauss": val, "start": "warm",
                    "integration": {"validation": info(vg)}}

        def proc(vg3=0, tg3=0, vg1=0, tg1=0, success=True, psuccess=True):
            cands = [pcand(0, 0.0, 0.0), pcand(1, 0.05, 1.0, vg=vg1, tg=tg1), pcand(3, 0.05, 2.0, vg=vg3, tg=tg3)]
            unres_val, unres_test = vg1 + vg3, tg3
            avail = not (unres_val or unres_test)
            unres_val_prim, prim_unres = vg1, tg1
            avail_prim = not unres_val_prim and not prim_unres
            ok = avail and success
            rec = {"candidates": cands, "fitter": "registered", "start": "both", "score": {}, "basis": 6,
                   "embedding": "shared", "center": "references",
                   "selected": dict({"rank": 3, "lambda": 0.05, "start": "warm"},
                                    **({"selection_unresolved": True} if unres_val else {})),
                   "test_improvement": 0.1 if avail else None, "test_lb": (0.02 if ok else -0.01) if avail else None,
                   "per_test_world": [0.1] * 6 if avail else [], "success": bool(ok),
                   "decision": {"available": bool(avail), "test_worlds": 6, "selection_unresolved": bool(unres_val),
                                "integration_unresolved": unres_val + unres_test, "reason": None if avail else "u"},
                   "selected_primary": dict({"ranks": [0, 1, 2], "rank": 1, "lambda": 0.05, "start": "warm",
                                             "available": bool(avail_prim), "test_improvement": 0.1,
                                             "test_lb": 0.01 if psuccess else -0.01,
                                             "success": bool(avail_prim and psuccess)},
                                            **({"selection_unresolved": True} if unres_val_prim else {})),
                   "fit_pairs": 100, "classes": None, "ab_cap": None}
            return rec

        def lbranch(state):                              # (forward_procedure's branches, L1148-1176)
            if state in ("decided", "available only"):   # (available only: an input the guards support, P3-R5-2;
                avail_only = state == "available only"   #  the producers never emit it, both minima being 2)
                return {"available": True, "test_improvement": 0.1, "test_lb": 0.01, "per_world": [0.1] * 3,
                        "success": not avail_only, "targets": 40, "worlds": 3, "decision_available": not avail_only,
                        "integration": {"selected": info(), "rank0": info()}, "integration_unresolved": 0,
                        "test_improvement_gauss": 0.1, "test_lb_gauss": 0.01}
            if state == "no targets":
                return {"available": False, "reason": "no targets"}
            if state == "one root":
                return {"available": False, "targets": 9, "test_roots": 1, "reason": "fewer than 2 roots"}
            return {"available": False, "integration_unresolved": 1, "targets": 40, "worlds": 3,
                    "integration": {"selected": info(), "rank0": info()}, "reason": "unresolved"}

        def lfwd(ft, inter, vg=0):
            b = {"forward_transfer": lbranch(ft), "intersection": lbranch(inter)}
            f = b["forward_transfer"]
            return dict({"procedure": "forward", "candidates": [fcand(0, 0.0, 0.0), fcand(1, 0.05, 1.0, vg=vg)],
                         "fitter": "registered", "fit_pairs": 90, "score": {}, "val_pairs": 30,
                         "test_pairs": {"forward_transfer": 40, "intersection": 40}, "controls": 50,
                         "selected": dict({"rank": 1, "lambda": 0.05, "start": "warm"},
                                          **({"selection_unresolved": True} if vg else {})),
                         "integration_unresolved": {"validation": vg},
                         "decision": {"available": bool(f.get("available") and f.get("decision_available")),
                                      "reason": f.get("reason"), "selection_unresolved": bool(vg),
                                      "integration_unresolved": max(vg, int(f.get("integration_unresolved", 0)))},
                         "success": f.get("success", False), "test_improvement": f.get("test_improvement"),
                         "test_lb": f.get("test_lb"), "classes": {}}, **b)

        def xbranch(state):                              # (recovery_extra.forward's branches, L780-837)
            if state in ("decided", "available only"):
                avail_only = state == "available only"
                return {"targets": 40, "test_roots": 3, "worlds": 3, "available": True,
                        "decision_available": not avail_only, "success": not avail_only, "test_improvement": 0.1,
                        "test_lb": 0.01, "per_world": [0.1] * 3,
                        "integration": {"selected": info(), "rank0": info()}, "integration_unresolved": 0,
                        "test_improvement_gauss": 0.1, "test_lb_gauss": 0.01}
            if state == "no targets":
                return {"targets": 0, "test_roots": 0, "worlds": 0, "available": False, "decision_available": False,
                        "success": False, "reason": "fewer than 2 contributing test roots"}
            return {"targets": 9, "test_roots": 1, "worlds": 1, "available": False, "decision_available": False,
                    "success": False, "descriptive": True, "test_improvement": 0.1, "per_world": [0.1],
                    "per_world_ids": ["w1"], "test_improvement_gauss": 0.1,
                    "integration": {"selected": info(), "rank0": info()}, "integration_unresolved": 0,
                    "reason": "fewer than 2 contributing test roots"}

        def xfwd(ft, inter):
            b = {"forward_transfer": xbranch(ft), "intersection": xbranch(inter)}
            f = b["forward_transfer"]
            return dict({"procedure": "forward", "reference_policy": "fwd_all", "fitter": "registered", "score": {},
                         "fit_pairs": 90, "val_pairs": 30, "controls": 50,
                         "candidates": [fcand(0, 0.0, 0.0), fcand(1, 0.05, 1.0)],
                         "selected": {"rank": 1, "lambda": 0.05, "start": "warm"},
                         "integration_unresolved": {"validation": 0},
                         "decision": {"available": bool(f.get("available")), "reason": f.get("reason"),
                                      "selection_unresolved": False,
                                      "integration_unresolved": int(f.get("integration_unresolved", 0))},
                         "success": f.get("success", False), "test_improvement": f.get("test_improvement"),
                         "test_lb": f.get("test_lb")}, **b)

        merged = xfwd("decided", "decided")              # (evaluate's one-root a / interp, L857-863)
        for k in ("forward_transfer", "intersection"):
            merged.pop(k)
        wt = xbranch("one root")
        merged.update(reference_policy="a", world_transfer=wt,
                      decision={"available": False, "reason": wt["reason"], "selection_unresolved": False,
                                "integration_unresolved": 0}, success=False, test_improvement=wt["test_improvement"],
                      test_lb=None)
        merged.update(dict(wt), procedure="a", per_test_world=wt["per_world"])
        return {
            "P1 decided, primary live, success": ("procedure", proc(), "L1035, L1055-1060, L1089-1091"),
            "P2 decided, primary live, unsuccessful": ("procedure", proc(success=False), "L1046-1047, L1090"),
            "P3 decided, primary unavailable (restricted comparison unresolved)": ("procedure", proc(tg1=1),
                                                                                   "L1040-1043, L1055"),
            "P4 full unavailable (rank-3 validation), primary live": ("procedure", proc(vg3=1),
                                                                      "L1032-1035, L1053-1055"),
            "P5 full unavailable (winner comparison), primary live": ("procedure", proc(tg3=1),
                                                                      "L1033-1035, L1063-1066"),
            "P6 full and primary unavailable": ("procedure", proc(vg1=1), "L1032, L1053-1062"),
            "P8 full unavailable (rank-3 validation), primary available, unsuccessful (Codex P3-R5-2)": (
                "procedure", proc(vg3=1, psuccess=False), "L1032-1035, L1053-1062"),
            "P7 procedure unavailable (roots)": ("procedure", {
                "available": False, "reason": "1 contributing test root(s)", "fitter": "registered",
                "fit_pairs": 100, "validation_targets": 20, "test_targets": 30, "test_roots": 1}, "L998-1001"),
            "L1 legacy forward: both branches decided": ("forward", lfwd("decided", "decided"), "L1172-1183"),
            "L2 legacy forward: forward_transfer decided, intersection one root": (
                "forward", lfwd("decided", "one root"), "L1157-1161, L1178"),
            "L3 legacy forward: forward_transfer no targets, intersection decided (Codex P2-R4-1)": (
                "forward", lfwd("no targets", "decided"), "L1149-1151, L1172-1179"),
            "L4 legacy forward: validation unresolved, no branch live": ("forward",
                                                                       lfwd("unresolved", "unresolved", vg=1),
                                                                       "L1146, L1164-1169, L1178-1180"),
            "L5 legacy forward: nothing to fit": ("forward", {
                "procedure": "forward", "candidates": [], "fitter": "registered", "fit_pairs": 0, "score": {},
                "val_pairs": 0, "test_pairs": {}, "controls": 0, "available": False,
                "reason": "no fitting pairs"}, "L1125-1130"),
            "L6 legacy forward: forward_transfer available only, intersection no targets (input, P3-R5-2)": (
                "forward", lfwd("available only", "no targets"), "the guards' input; L1172-1176 never emit it"),
            "X1 extra forward: both branches decided": ("extra forward", xfwd("decided", "decided"), "L822-850"),
            "X2 extra forward: forward_transfer no targets, intersection decided": (
                "extra forward", xfwd("no targets", "decided"), "L782-788, L822-850"),
            "X3 extra forward: forward_transfer decided, intersection one-root descriptive": (
                "extra forward", xfwd("decided", "one root"), "L808-821"),
            "X4 extra forward: intersection available only, forward_transfer no targets (input, P3-R5-2)": (
                "extra forward", xfwd("no targets", "available only"), "the guards' input; L830-837 never emit it"),
            "M1 extra a / interp, one test world (descriptive)": ("extra merged", merged, "L857-863, L808-821"),
        }

    # (documented ALTERNATIVES: a read whose deletion leaves a live claim standing is accepted only here)
    R5_ALTERNATIVES = (
        ("grid_unresolved", "a zero unresolved count: an absent grid_unresolved reads 0 and the registered map "
                            "writes 0 for a resolved record (map.py L1237); the minimal fitter writes none "
                            "(recovery.py L812). "
                            "Deleting a 0 hides no unresolved pair: a positive count is the only unresolved state, "
                            "and it also sets the stored integration_unresolved / decision flags the paths require"),
        ("test_roots|worlds", "recovery_extra writes a branch's test_roots and worlds from the same count "
                              "(recovery_extra.py L782; L675 at 2f82515, not L671 as round 5 cited), and a merged "
                              "record carries both at its top level as copies of its branch's (L861, "
                              "out.update(branch)): either one gives the root guard and the per-world length their "
                              "count, so a missing one cannot hide an under-rooted claim"),
        ("procedure|reference_policy", "recovery_extra marks a forward record twice, procedure 'forward' and "
                                       "reference_policy (recovery_extra.py L738), and a merged record carries "
                                       "reference_policy beside procedure 'a' / 'interp' (L861); the guards take the "
                                       "forward derivation when procedure is 'forward' OR reference_policy is present "
                                       "(recovery.py L2532), so deleting one marker while the other still selects it "
                                       "changes nothing"),
        ("merged copy", "a merged record's top-level available is its branch's (recovery_extra.py L861, "
                        "out.update(branch)); the decision it carries is checked against that branch itself (the "
                        "decision branch, recovery.py L2567-2571: available and decision_available required), so "
                        "deleting the copy hides nothing (WP5: first seen on a live merged record, M2)"),
    )
    # (every producer line this matrix cites, with the code it names: test_T7_8_WP5_the_matrix_cites_its_producers)
    R5_CITES = (("recovery_extra.py", 730, "def forward(v, data, fit, seed, option):"),
                ("recovery_extra.py", 738, '"procedure": "forward", "reference_policy": option,'),
                ("recovery_extra.py", 743, "if not len(idx) or not len(val):"),
                ("recovery_extra.py", 782, 'base = {"targets": len(ix), "test_roots": roots, "worlds": roots}'),
                ("recovery_extra.py", 783, "if not len(ix):"),
                ("recovery_extra.py", 789, "if unres_val:"),
                ("recovery_extra.py", 808, "if roots < rec.MIN_TEST_ROOTS:"),
                ("recovery_extra.py", 830, "out[name] = dict("),
                ("recovery_extra.py", 850, "return out"),
                ("recovery_extra.py", 853, "def evaluate(v, data, plan, seed, option):"),
                ("recovery_extra.py", 857, "if (len(np.unique(v.test_world)) == 1"),
                ("recovery_extra.py", 861, "out.update(branch, procedure=option)"),
                ("recovery_extra.py", 863, "return out"),
                ("recovery.py", 2532, 'fwd = o.get("procedure") == "forward" or "reference_policy" in o'),
                ("recovery.py", 2567, 'db = o.get("forward_transfer") if "forward_transfer" in o else next('),
                ("recovery.py", 2571, "a decision whose decision branch is not decided"),
                ("recovery_extra.py", 864, "return rec.procedure("),
                ("recovery.py", 991, "def procedure(D, data, option, ranks, lambdas, iters, seed"),
                ("recovery.py", 1057, "avail_prim = bool(nw >= MIN_TEST_WORLDS and not unres_val_prim"),
                ("recovery.py", 1112, "def forward_procedure(D, data, ranks, lambdas, iters, seed"),
                ("recovery.py", 812, 'info["exact"] = info.get("exact", 0) + int(len(ix))'),
                ("map.py", 1237, "grid_unresolved"))

    @staticmethod
    def r5_owner(path):
        """The claims a record field is evidence for (the comparison's own records, by the producers' layout). A
        branch's root count is evidence for its DECISION only (CRITERION C4 keeps available one-root descriptive
        scores; WP5: L6 / X4, branches available without a decision)."""
        k = path[0]
        if k in R.BRANCHES:
            if len(path) == 2 and path[1] in ("test_roots", "worlds"):
                return {f"branch-decision:{k}"}
            return {f"branch:{k}"}
        if k == "selected_primary":
            return {"primary"}
        if k == "candidates" or path in (("selected",), ("selected", "rank"), ("selected", "lambda")):
            return {"any"}
        if path in (("decision",), ("decision", "test_worlds")):
            return {"decision", "primary"}
        if path == ("test_lb",):         # (read by C1 alone; the guards never read it)
            return {"c1"}
        return {"decision"}

    @staticmethod
    def r5_live(rec):
        """The record's live claims, read from its flags (as the producers set them)."""
        out = set()
        dec = rec.get("decision") if isinstance(rec.get("decision"), dict) else {}
        if dec.get("available") is True or rec.get("success") or rec.get("decision_available") is True:
            out.add("decision")
        sp = rec.get("selected_primary")
        if isinstance(sp, dict) and (sp.get("available") is True or sp.get("success")):
            out.add("primary")
        for b in R.BRANCHES:
            br = rec.get(b)
            if isinstance(br, dict) and (br.get("decision_available") is True or br.get("success")
                                         or br.get("available") is True):
                out.add(f"branch:{b}")
            if isinstance(br, dict) and (br.get("decision_available") is True or br.get("success")):
                out.add(f"branch-decision:{b}")
        if R.c1_success(rec):           # (C1 counts the record: a claim of its own)
            out.add("c1")
        return out | ({"any"} if out else set())

    @staticmethod
    def r5_reads(rec):
        """Every key path the guards (_guard_violations) and C1 (c1_success) read on rec, tracked during a real
        evaluation -> (reads, violations, c1)."""
        log = set()

        class Tracked(dict):
            def __init__(self, data, path):
                super().__init__()
                self.path = path
                for k, x in data.items():
                    dict.__setitem__(self, k, track(x, path + (k,)))

            def get(self, k, default=None):
                log.add(self.path + (k,))
                return dict.get(self, k, default)

            def __getitem__(self, k):
                log.add(self.path + (k,))
                return dict.__getitem__(self, k)

            def __contains__(self, k):
                log.add(self.path + (k,))
                return dict.__contains__(self, k)

        def track(x, path):
            if isinstance(x, dict):
                return Tracked(x, path)
            if isinstance(x, list):
                return [track(y, path + (i,)) for i, y in enumerate(x)]
            return x
        t = track(rec, ())
        viol = R._guard_violations(t, "x")
        return log, viol, R.c1_success(t)

    @staticmethod
    def r5_present(rec, path):
        for k in path:
            if isinstance(rec, dict) and k in rec:
                rec = rec[k]
            elif isinstance(rec, list) and isinstance(k, int) and k < len(rec):
                rec = rec[k]
            else:
                return False, None
        return True, rec

    def r5_alternative(self, rec, path):
        """The documented alternative a path is, if any (R5_ALTERNATIVES)."""
        leaf = path[-1]
        if leaf == "grid_unresolved" and self.r5_present(rec, path)[1] == 0:
            return "grid_unresolved"
        if leaf in ("test_roots", "worlds") and (len(path) == 2 and path[0] in R.BRANCHES or len(path) == 1):
            other = "worlds" if leaf == "test_roots" else "test_roots"
            here, there = self.r5_present(rec, path), self.r5_present(rec, path[:-1] + (other,))
            if there[0] and there[1] == here[1]:
                return "test_roots|worlds"
        if (path == ("procedure",) and "reference_policy" in rec) or \
                (path == ("reference_policy",) and rec.get("procedure") == "forward"):
            return "procedure|reference_policy"
        if path == ("available",) and "reference_policy" in rec and rec.get("procedure") != "forward" and any(
                isinstance(rec.get(b), dict) and rec[b].get("available") == rec.get("available")
                for b in ("world_transfer", "interpolation")):
            return "merged copy"
        return None

    def r5_matrix(self, states):
        """Round 5's tracked-read deletion loop over states ({name: (kind, record, producer)}): each record must pass
        the guards; every key path the guards and C1 read on it is deleted, one at a time, while present; a deletion
        must be caught (a violation, or C1 no longer counting the record) unless the field is evidence only for claims
        not live, the deletion withdraws every live claim it is evidence for, or it is a documented alternative; no
        deletion may add a claim -> (the per-state table, the holes)."""
        holes, table = [], {}
        for name, (kind, rec, where) in states.items():
            reads, viol, c1 = self.r5_reads(rec)
            self.assertEqual(viol, [], f"{name}: the producer-shaped record must pass the guards")
            live = self.r5_live(rec)
            row = {"kind": kind, "producer": where, "live": sorted(live), "c1": c1, "caught": [], "not_live": [],
                   "withdrawn": [], "alternative": [], "absent_reads": []}
            for path in sorted(reads, key=str):
                present, _ = self.r5_present(rec, path)
                if not present:
                    row["absent_reads"].append(".".join(map(str, path)))
                    continue
                d = self.without(rec, path)
                dv, dc1 = R._guard_violations(d, "x"), R.c1_success(d)
                dlive = self.r5_live(d)
                label = ".".join(map(str, path))
                if not dlive <= live or (dc1 and not c1):
                    holes.append(f"{name}: deleting {label} ADDS a claim ({sorted(dlive - live)}, C1 {c1}->{dc1})")
                if dv or (c1 and not dc1):
                    row["caught"].append(label)
                    continue
                own = self.r5_owner(path) & live
                if not own:
                    row["not_live"].append(label)
                elif not own & dlive:
                    row["withdrawn"].append(label)
                elif self.r5_alternative(rec, path):
                    row["alternative"].append(f"{label} ({self.r5_alternative(rec, path)})")
                else:
                    holes.append(f"{name}: deleting {label} leaves {sorted(own & dlive)} live and is not caught")
            table[name] = row
        return table, holes

    @staticmethod
    def r5_counts(row):
        return [len(row[k]) for k in ("caught", "not_live", "withdrawn", "alternative", "absent_reads")]

    def test_T7_8_every_liveness_state_requires_every_record_its_live_claims_read(self):
        """P2-R4-1 / P2-R4-2 and their class (Codex WP4 r4): for every liveness state the producers emit (r5_states:
        the procedure with the full decision and the restricted primary each live or not; legacy and extra forward
        with each branch live or not, independently of the top-level decision; the early returns; the merged
        one-root record), the guards and C1 are evaluated on a tracked copy and every key path they READ is
        recorded. Then each read field present in the record is deleted, one at a time. A deletion must be caught --
        a guard violation, or C1 no longer counting a record it counted -- unless (a) the field is evidence only for
        claims that are not live in that state, (b) the deletion withdraws every live claim the field is evidence
        for, or (c) the field is one of the documented alternatives (R5_ALTERNATIVES); and no deletion may ever add a
        live claim or make C1 count a record it did not. Every read of a key ABSENT from the record (a conditional
        read) is reported too. With RQ_WP4_COVERAGE set, the full coverage table is written there (evidence).
        Codex's two inputs are in the matrix (L3's candidate integrations; P4's decision.test_worlds), with the
        absent candidate list beside a live branch. (WP5: P8, the available but unsuccessful restricted primary, and
        L6 / X4, branches live only through `available`, are states too; the classification counts are pinned,
        R5_COUNTS.)"""
        states = self.r5_states()
        table, holes = self.r5_matrix(states)
        if os.environ.get("RQ_WP4_COVERAGE"):
            rqlib.write_json_durable(os.environ["RQ_WP4_COVERAGE"], {"states": table, "holes": holes,
                                                                     "alternatives": dict(self.R5_ALTERNATIVES)})
        self.assertEqual(holes, [])
        self.assertTrue(all(table[n]["caught"] for n in table if table[n]["live"]))
        self.assertEqual({n: self.r5_counts(row) for n, row in table.items()}, self.R5_COUNTS)
        # (Codex's two inputs, explicitly; and the absent candidate list beside a live branch)
        _, l3, _ = states["L3 legacy forward: forward_transfer no targets, intersection decided (Codex P2-R4-1)"]
        stripped = copy.deepcopy(l3)
        for c in stripped["candidates"]:
            c.pop("integration")
        self.assertIn("x.candidates[0]: integration.validation is absent",
                      "; ".join(R._guard_violations(stripped, "x")))
        self.assertIn("x: a decision without its candidate records",
                      R._guard_violations(self.without(l3, ("candidates",)), "x"))
        _, p4, _ = states["P4 full unavailable (rank-3 validation), primary live"]
        self.assertIn("x: decision.test_worlds is absent",
                      "; ".join(R._guard_violations(self.without(p4, ("decision", "test_worlds")), "x")))
        low = copy.deepcopy(p4)
        low["decision"]["test_worlds"] = 1
        self.assertIn("x.selected_primary: decided with 1 contributing test root(s)",
                      R._guard_violations(low, "x"))

    # ---------------------------------------------------------------- WP5 (Codex WP4 r5's P3-R5-1 / P3-R5-2)
    P8 = "P8 full unavailable (rank-3 validation), primary available, unsuccessful (Codex P3-R5-2)"
    L6 = "L6 legacy forward: forward_transfer available only, intersection no targets (input, P3-R5-2)"
    X4 = "X4 extra forward: intersection available only, forward_transfer no targets (input, P3-R5-2)"
    # (the matrix's classification counts per state, [caught, not live, withdrawn, alternative, absent reads]: round
    #  5's 16 states as its coverage table reconciled them, and WP5's P8, L6 and X4; a classifier that misclassifies
    #  one exemption changes one of these)
    R5_COUNTS = {
        "P1 decided, primary live, success": [36, 0, 1, 6, 11],
        "P2 decided, primary live, unsuccessful": [34, 0, 2, 6, 11],
        "P3 decided, primary unavailable (restricted comparison unresolved)": [32, 3, 0, 5, 11],
        "P4 full unavailable (rank-3 validation), primary live": [26, 5, 1, 4, 10],
        "P5 full unavailable (winner comparison), primary live": [26, 4, 1, 4, 11],
        "P6 full and primary unavailable": [12, 13, 0, 0, 9],
        P8: [25, 5, 2, 4, 10],
        "P7 procedure unavailable (roots)": [0, 1, 0, 0, 11],
        "L1 legacy forward: both branches decided": [39, 1, 1, 6, 10],
        "L2 legacy forward: forward_transfer decided, intersection one root": [30, 4, 0, 4, 13],
        "L3 legacy forward: forward_transfer no targets, intersection decided (Codex P2-R4-1)": [23, 8, 1, 4, 14],
        "L4 legacy forward: validation unresolved, no branch live": [7, 17, 0, 0, 13],
        "L5 legacy forward: nothing to fit": [0, 1, 0, 0, 11],
        L6: [21, 9, 2, 4, 14],
        "X1 extra forward: both branches decided": [36, 1, 1, 11, 8],
        "X2 extra forward: forward_transfer no targets, intersection decided": [22, 12, 1, 6, 9],
        "X3 extra forward: forward_transfer decided, intersection one-root descriptive": [28, 8, 0, 7, 8],
        X4: [21, 14, 2, 4, 9],
        "M1 extra a / interp, one test world (descriptive)": [7, 19, 0, 0, 6],
    }

    def test_T7_8_WP5_availability_without_success_activates_the_requirements(self):
        """P3-R5-2 (Codex WP4 r5): a claim is live through availability alone. P8 -- the restricted primary available
        but unsuccessful while the full decision is unavailable (recovery.py L1057) -- requires its contributing-root
        count: deleting decision.test_worlds is caught, and so are 0 and 1 roots, while 2 (the minimum) and 6 pass
        (controls). L6 and X4 -- a branch available without a decision or a success (an input the guards support;
        the producers never emit it, both minima being 2) -- require the candidate list, every candidate's validation
        integration and the branch's own records; with the branch unavailable none is required (control)."""
        states = self.r5_states()
        _, p8, _ = states[self.P8]
        self.assertEqual((p8["decision"]["available"], p8["selected_primary"]["available"],
                          p8["selected_primary"]["success"]), (False, True, False))
        self.assertEqual(R._guard_violations(p8, "x"), [])
        self.assertIn("x: decision.test_worlds is absent",
                      "; ".join(R._guard_violations(self.without(p8, ("decision", "test_worlds")), "x")))
        for n, bad in ((0, True), (1, True), (2, False), (6, False)):
            o = copy.deepcopy(p8)
            o["decision"]["test_worlds"] = n
            with self.subTest(roots=n):
                v = R._guard_violations(o, "x")
                if bad:
                    self.assertIn(f"x.selected_primary: decided with {n} contributing test root(s)", v)
                else:
                    self.assertEqual(v, [])
        for key, b in ((self.L6, "forward_transfer"), (self.X4, "intersection")):
            _, rec, _ = states[key]
            with self.subTest(state=key):
                self.assertEqual((rec[b]["available"], rec[b]["decision_available"], rec[b]["success"],
                                  rec["decision"]["available"]), (True, False, False, False))
                self.assertEqual(R._guard_violations(rec, "x"), [])
                self.assertIn("x: a decision without its candidate records",
                              R._guard_violations(self.without(rec, ("candidates",)), "x"))
                stripped = copy.deepcopy(rec)
                for c in stripped["candidates"]:
                    c.pop("integration")
                self.assertIn("x.candidates[0]: integration.validation is absent",
                              "; ".join(R._guard_violations(stripped, "x")))
                self.assertIn(f"x.{b}: integration.selected is absent",
                              "; ".join(R._guard_violations(self.without(rec, (b, "integration", "selected")), "x")))
                off = copy.deepcopy(rec)
                off[b]["available"] = False
                self.assertEqual(R._guard_violations(self.without(off, ("candidates",)), "x"), [])

    def test_T7_8_WP5_the_matrix_reports_injected_guard_holes(self):
        """P3-R5-2's fault test of the matrix's exemption classifier (Codex WP4 r5): with the guards weakened in two
        known ways the matrix must REPORT the holes, none exempted as not live, withdrawn or an alternative -- (a) a
        live primary's root count no longer required (P2-R4-2 reverted: recovery._PRIMARY_ROOTS empty) leaves exactly
        the decision record and its test_worlds of P4, P5 and P8 (the primary live beside an unavailable full decision)
        and P2's decision record (deleting it leaves the unsuccessful decision withdrawn, the primary live); (b) a
        branch no longer live through `available` alone (_branch_live's availability arm dropped) leaves L6's and
        X4's availability-only branches unguarded, and only theirs.
        Unweakened the matrix reports none, with the pinned classification counts R5_COUNTS. A classifier that
        misclassifies one exemption therefore changes a pinned count or hides one of these holes (the WP5 classifier
        mutations show both)."""
        states = self.r5_states()
        table, holes = self.r5_matrix(states)
        self.assertEqual(holes, [])
        self.assertEqual({n: self.r5_counts(row) for n, row in table.items()}, self.R5_COUNTS)
        with mock.patch.object(R, "_PRIMARY_ROOTS", ()):
            _, holes = self.r5_matrix(states)
        p45 = [n for n in states if n.startswith(("P4 ", "P5 "))] + [self.P8]
        p2 = next(n for n in states if n.startswith("P2 "))
        self.assertEqual(sorted(holes), sorted([f"{n}: deleting {f} leaves ['primary'] live and is not caught"
                                                for n in p45 for f in ("decision", "decision.test_worlds")] +
                                               [f"{p2}: deleting decision leaves ['primary'] live and is not caught"]))

        def no_availability_arm(br):
            return isinstance(br, dict) and (br.get("decision_available") is True or bool(br.get("success")))
        with mock.patch.object(R, "_branch_live", no_availability_arm):
            _, holes = self.r5_matrix(states)
        self.assertEqual({h.split(": deleting")[0] for h in holes}, {self.L6, self.X4})
        for key, b in ((self.L6, "forward_transfer"), (self.X4, "intersection")):
            self.assertEqual(sorted(h.split(": deleting ")[1].split(" leaves")[0] for h in holes if h.startswith(key)),
                             sorted(["candidates", "candidates.0.val_lpd", f"{b}.decision_available",
                                     f"{b}.integration_unresolved", f"{b}.success"]), key)

    def test_T7_8_WP5_the_matrix_cites_its_producers(self):
        """Codex WP4 r5's citation note (the root-alternative producer was recovery_extra.py:675 at 2f82515, not :671)
        and every producer line the matrix cites at this head (R5_CITES): each cited line holds the cited code, so a
        citation cannot go stale silently."""
        for name, line, code in self.R5_CITES:
            lines = rqlib.read_text(os.path.join(HERE, name)).split("\n")
            self.assertIn(code, lines[line - 1], f"{name}:{line}")
        self.assertIn("L782", dict(self.R5_ALTERNATIVES)["test_roots|worlds"])

    @staticmethod
    def r5_signature(rec):
        """A produced record's liveness signature: (its kind, its live claims as r5_live reads them, C1's left out: a
        decided record's success is the data's, so whether C1 counts it is not part of the state)."""
        if not rec.get("candidates"):
            kind = "early return"
        elif "reference_policy" in rec and rec.get("procedure") != "forward":
            kind = "merged"
        elif rec.get("procedure") == "forward":
            kind = "extra forward"
        else:
            kind = "procedure"
        return kind, tuple(sorted(x for x in TestRecoveryBankPacket.r5_live(rec)
                                  if x != "c1" and not x.startswith("branch-decision:")))

    def r5_real_states(self):
        """Records PRODUCED by recovery_extra in bank mode (recovery_extra.evaluate on the views of a bank-mode plan:
        the toy graph, the accepted-form synthetic bank/3, r1_034 / r0 data, ranks 0..3) for the liveness states it
        emits; the rarer ones by test hooks on its INPUTS only (a mask; an integration diagnostic marked unresolved as
        the registered map records one; the root minimum lowered to 1, under which a merged record's branch can be
        live) -> {name: (signature wanted, record, how, context)}; the context also wraps the matrix's evaluation."""
        import obslaw
        bp, tp = self.TG.bank_files()
        obs = obslaw.BankObservationModel(bp, tp)
        D = X.data_from(self.gpath, None)
        fit = dict(ranks=3, lambdas="0.05", iters=2, start="warm", basis=4, embedding="shared", center="references")
        plan = X.make_plan(D, self.gpath, None, "rq-r5-real", fit, ["r1_034", "r0"], 1, list(X.OPTIONS),
                           list(X.CASES), True, obs=obs)
        seed = 91
        data = {sc: R.simulate(D, R.SCENARIOS[sc], seed, obs=obs) for sc in ("r1_034", "r0")}
        ones = np.ones(len(D.qi), bool)
        null = contextlib.nullcontext
        real_cand, real_scorer = R._cand_record, R.scorer

        def unresolved_validation(ranks):            # (an unresolved validation integral, as map records it)
            def cand(*a, **k):
                out = real_cand(*a, **k)
                if out["rank"] in ranks:
                    out["integration"]["validation"]["grid_unresolved"] = 1
                return out
            return mock.patch.object(R, "_cand_record", cand)

        def unresolved_comparison(target):            # (an unresolved test integral of one branch's targets)
            def scorer(*a):
                s = real_scorer(*a)

                def score(ix, info=None):
                    out = s(ix, info)
                    if info is not None and ix is target:
                        info["grid_unresolved"] = info.get("grid_unresolved", 0) + 1
                    return out
                return score
            return mock.patch.object(R, "scorer", scorer)

        def ev(op, keep, sc="r1_034", hook=null, view=None):
            v = view if view is not None else X.view_for(D, plan, op, keep)
            with hook():
                return X.evaluate(v, data[sc], plan, seed, op)
        states = {}
        want = {"intact a": ("procedure", ("any", "decision", "primary")),
                "intact interp": ("procedure", ("any", "decision", "primary")),
                "intact fwd_all": ("extra forward", ("any", "branch:forward_transfer", "branch:intersection",
                                                     "decision")),
                "roots0 a": ("early return", ()),
                "roots0 fwd_all": ("extra forward", ("any", "branch:forward_transfer", "decision")),
                "roots1 a": ("merged", ()),
                "roots1 fwd_all": ("extra forward", ("any", "branch:forward_transfer", "decision"))}
        for name in want:
            case, op = name.split()
            states[name] = (want[name], ev(op, X.mask_for(D, plan, case)[0]), f"evaluate, case {case}", null)
        k = ones.copy()
        k[D.forward["tests"]["forward_transfer"]] = False
        states["X2 forward_transfer's targets masked out"] = (
            ("extra forward", ("any", "branch:intersection")), ev("fwd_all", k), "evaluate, a mask", null)
        states["early return: no fitting pairs"] = (("early return", ()), ev("fwd_all", ~ones), "a mask", null)
        k = ones.copy()
        k[D.forward["val"]] = False
        states["early return: no validation targets"] = (("early return", ()), ev("fwd_all", k), "a mask", null)
        states["neither branch live: validation unresolved"] = (
            ("extra forward", ()), ev("fwd_all", ones, hook=lambda: unresolved_validation({0, 1, 2, 3})),
            "validation integral unresolved", null)
        v = X.view_for(D, plan, "fwd_all", ones)
        states["forward_transfer's comparison unresolved"] = (
            ("extra forward", ("any", "branch:intersection")),
            ev("fwd_all", ones, view=v, hook=lambda: unresolved_comparison(v.forward["tests"]["forward_transfer"])),
            "forward_transfer test integral unresolved", null)
        states["P6 full and primary unavailable"] = (
            ("procedure", ()), ev("a", ones, hook=lambda: unresolved_validation({1})), "rank-1 validation unresolved",
            null)
        states["P8 primary available, unsuccessful"] = (
            ("procedure", ("any", "primary")), ev("a", ones, sc="r0", hook=lambda: unresolved_validation({3})),
            "r0 data, rank-3 validation unresolved", null)
        lowered = lambda: mock.patch.object(R, "MIN_TEST_ROOTS", 1)   # noqa: E731
        states["M2 merged, its world_transfer live"] = (
            ("merged", ("any", "branch:world_transfer", "decision")),
            ev("a", X.mask_for(D, plan, "roots1")[0], hook=lowered), "the root minimum lowered to 1", lowered)
        return states

    def test_T7_8_WP5_the_liveness_matrix_on_real_bank_mode_extra_results(self):
        """P3-R5-1 and the WP4 r5 note (Codex WP4 r5): round 5's tracked-read deletion loop on records ACTUALLY PRODUCED
        by recovery_extra in bank mode (r5_real_states), REPRESENTATIVE coverage of the liveness states it emits, not a
        claim about every producer state: extra forward with both branches live (intact), a branch live with the
        top-level decision unavailable (X2: forward_transfer's targets masked out; and forward_transfer's comparison
        unresolved), forward_transfer live beside a dead intersection (roots0, roots1), neither branch live
        (validation unresolved, recovery_extra.py L789), the empty-candidate early returns (no fitting pairs, no
        validation targets, L743), the one-root merged record (M1, roots1 a), a merged record whose world_transfer is
        live (the root minimum lowered to 1: at 2 a merged record's one root can never decide), the procedure of
        recovery_extra's a / interp (decided; unavailable at roots0; both unavailable; the restricted primary
        available but unsuccessful beside an unavailable full decision, P3-R5-2). Every record passes the guards,
        every deletion is caught or exempt as in round 5 (0 holes), every live state has a caught deletion, and every
        state has its wanted liveness signature. With RQ_WP5_COVERAGE set, the table is written there (evidence)."""
        states = self.r5_real_states()
        table, holes, sigs = {}, [], {}
        for name, (wanted, rec, how, ctx) in states.items():
            sigs[name] = self.r5_signature(rec)
            with ctx():
                t, h = self.r5_matrix({name: (sigs[name][0], rec, how)})
            table.update(t)
            holes += h
        if os.environ.get("RQ_WP5_COVERAGE"):
            rqlib.write_json_durable(os.environ["RQ_WP5_COVERAGE"], {"states": table, "holes": holes,
                                                                     "signatures": sigs})
        self.assertEqual({n: [s[0], list(s[1])] for n, s in sigs.items()},
                         {n: [w[0], list(w[1])] for n, (w, _, _, _) in states.items()})
        self.assertEqual(holes, [])
        self.assertTrue(all(table[n]["caught"] for n in table if table[n]["live"]))
        p8 = states["P8 primary available, unsuccessful"][1]
        self.assertEqual((p8["decision"]["available"], p8["selected_primary"]["available"],
                          p8["selected_primary"]["success"]), (False, True, False))
        self.assertIn("x: decision.test_worlds is absent",
                      "; ".join(R._guard_violations(self.without(p8, ("decision", "test_worlds")), "x")))
        low = copy.deepcopy(p8)
        low["decision"]["test_worlds"] = 1
        self.assertIn("x.selected_primary: decided with 1 contributing test root(s)", R._guard_violations(low, "x"))

    def test_T7_8_WP5_packet_refuses_round_5s_branch_only_inputs(self):
        """Codex WP4 r5's note (no packet regression for round 5's branch-only inputs): in a complete schedule, a legacy
        fwd record shaped L3 (forward_transfer without targets, the intersection decided) and an extra fwd_all record
        shaped X2 pass the packet; with their candidates' integration records removed, or without their candidate
        list, each fails the packet's guards check naming the violation (exit 2), C1 unchanged."""
        f = self.complete()
        states = self.r5_states()
        l3 = states["L3 legacy forward: forward_transfer no targets, intersection decided (Codex P2-R4-1)"][1]
        x2 = dict(states["X2 extra forward: forward_transfer no targets, intersection decided"][1],
                  reference_policy="fwd_all")

        def stripped(rec):
            out = copy.deepcopy(rec)
            for c in out["candidates"]:
                c.pop("integration")
            return out
        fr = os.path.join(f["dirs"]["stress"]["dir"], "r0_asym.000.json")
        fx = os.path.join(f["dirs"]["extra_fwd_all"]["dir"], "results", "intact.r1_034.000.json")

        def put_legacy(rec):
            r = rqlib.read_json(fr)
            r["options"]["fwd"] = rec
            rqlib.write_json_durable(fr, r)

        def put_extra(rec):
            rewrite_extra_result(fx, lambda r: r["options"].update(fwd_all=rec))
        with mock.patch.object(R, "C2_MATRIX", self.TOY_C2):
            c1 = R.packet(f["path"], "acceptance")[0]["checks"]["C1"]
            for where, put, base in (("legacy", put_legacy, l3), ("extra", put_extra, x2)):
                for name, rec, why in (("intact", base, None),
                                       ("integration removed", stripped(base), "integration.validation is absent"),
                                       ("no candidates", self.without(base, ("candidates",)),
                                        "a decision without its candidate records")):
                    with self.subTest(where=where, input=name):
                        put(rec)
                        doc, code = R.packet(f["path"], "acceptance")
                        g = doc["checks"]["guards"]
                        self.assertEqual(doc["checks"]["C1"], c1)
                        if why is None:
                            self.assertEqual((g["status"], code), ("pass", 0), g)
                        else:
                            self.assertEqual((g["status"], code), ("fail", 2))
                            self.assertIn(why, g["reason"])
                put(base)

    def test_T7_8_WP5_a_complete_bank_mode_schedule_passes_every_check(self):
        """T7-8 with recovery_extra's bank mode (v5 3.4, 3.8; WP4's carried test): complete() -- its four extra roles'
        plans prepared with --obs-model bank (the registered fit, namespace A1) and their results -- passes `packet
        --mode acceptance` through the command line: exit 0, every check pass, scope bank/D8, accepting, the UNRESOLVED
        acceptance text. The identity check re-derives each extra plan with the schedule's OWN bank and tables
        (recovery_extra.verified, through _extra_call): a schedule naming other tables (one array changed, re-hashed)
        fails identity on every directory, each extra plan included ("changed"); an extra plan bound to another
        observation model fails it on that directory; an extra result relabelled planning (body re-hashed) is
        refused."""
        f = self.complete()
        for k in ("extra_interp", "extra_fwd_all", "extra_fwd_early", "extra_a"):
            plan = X.read_frozen(f["dirs"][k]["dir"])
            self.assertEqual((plan["noise_source"], plan["accepting"], plan["namespace"],
                              plan["inputs"]["observation_model_sha256"]), ("bank_d8", True, A1, f["om_sha"]), k)
        out = os.path.join(f["root"], "PACKET.json")
        with mock.patch.object(R, "C2_MATRIX", self.TOY_C2), contextlib.redirect_stdout(io.StringIO()) as so:
            self.assertEqual(R.main(["packet", "--mode", "acceptance", "--schedule", f["path"], "--out", out]), 0,
                             so.getvalue())
        p = rqlib.read_json(out)
        self.assertEqual({k: c["status"] for k, c in p["checks"].items()},
                         dict.fromkeys(("identity", "completeness", "numerical", "pairing", "guards", "C1"), "pass"),
                         p["checks"])
        self.assertEqual((p["scope"], p["accepting"], p["scientific_ACCEPTED"], p["exit"]),
                         ("bank/D8", True, "UNRESOLVED (review required, D8:327)", 0))
        self.assertEqual(p["checks"]["identity"]["directories"], len(f["entries"]))
        self.assertGreaterEqual(p["checks"]["pairing"]["comparisons"], 3 + 4)    # (3 extra intact + 4 sensitivities)
        import test_obslaw as TO
        data, _ = TO._rehashed_tables(rqlib.read_bytes(f["tp"]), {"fit_A": lambda x: x + np.where(
            np.arange(len(x)) == 9, 1e-9, 0.0)})
        tp3 = os.path.join(f["root"], "t3.npz")
        rqlib.write_durable(tp3, data)
        with mock.patch.object(R, "C2_MATRIX", self.TOY_C2):
            doc, code = R.packet(self.schedule(f["path"], f["entries"], f["om_sha"], f["bp"], tp3), "acceptance")
        fails = doc["checks"]["identity"]["failures"]
        self.assertEqual((code, doc["checks"]["identity"]["status"]), (2, "fail"))
        for k in ("extra_interp", "extra_fwd_all", "extra_fwd_early", "extra_a"):
            self.assertTrue(any(f["dirs"][k]["dir"].endswith(x.split(" (")[0]) and
                                "graph, references, sources, runtime or frozen recipe changed" in x for x in fails),
                            (k, fails))
        self.assertTrue(any("primary (C1-primary)" in x and "re-derived" in x for x in fails), fails)
        self.schedule(f["path"], f["entries"], f["om_sha"], f["bp"], f["tp"])
        e = self.doctored(f, "ext_om", "extra_fwd_all",
                          lambda p: p["inputs"].update(observation_model_sha256="0" * 64))
        with mock.patch.object(R, "C2_MATRIX", self.TOY_C2):
            doc, code = R.packet(self.schedule(f["path"], [x for x in f["entries"] if x["role"] != "extra-fwd_all"] +
                                               [e], f["om_sha"], f["bp"], f["tp"]), "acceptance")
        self.assertEqual(code, 2)
        self.assertIn("ext_om (extra-fwd_all): its plan's observation model is not the scheduled one",
                      doc["checks"]["identity"]["reason"])
        self.schedule(f["path"], f["entries"], f["om_sha"], f["bp"], f["tp"])
        fx = os.path.join(f["dirs"]["extra_interp"]["dir"], "results", "intact.r1_034.000.json")
        rewrite_extra_result(fx, lambda r: r.update(noise_source="scenario_planning_only"))
        with mock.patch.object(R, "C2_MATRIX", self.TOY_C2):
            doc, code = R.packet(f["path"], "acceptance")
        self.assertEqual((code, doc["checks"]["identity"]["status"]), (2, "fail"))
        self.assertIn("a result of another noise source or observation model", doc["checks"]["identity"]["reason"])


# ================================================================== the wrapper rec_A_v1 (A_design_v5 4.4; WP5)
REC_A_SH = os.path.join(HERE, "rec_A_v1.sh")
# (the wrapper's bindings as v5 4.4, 6.2 item 6 and T5-4 name them, written here, never read from rec_A_v1.py, so a
#  binding dropped from the wrapper's constants is caught; the benchmark's namespace, v5 7 step 8)
MEASURE_NS = "rq2026-d8-recovery-A1-measure"
D8_NAMES = ("bank_d8.json", "bank_d8.receipt.json", "provenance.json", "d8validation.spec.json",
            "d8validation.report.json", "d8validation.witness.receipt", "obs_tables.npz", "pr68_conformance.receipt",
            "observations.json", "ages.json", "bank.plan.jsonl", "bank.design.json")
AUTHORITY_NAMES = ("A_design_v5.md", "A_design_v5_clarification_1.md", "A_design_v5_clarification_2.md",
                   "A_design_v5_clarification_3.md", "A_design_v5_clarification_4.md",
                   "A_design_v5_clarification_4.freeze_addendum.md", "amendment_D8_v2.md",
                   "amendment_D9_launch_before_registration.md", "redqueen_study_design_v4_codex.md",
                   "redqueen_annexH_codex.md", "PRELAUNCH_GATES.md", "recovery_runbook_codex.md",
                   "recovery_tooling_plan_codex.md")
CRITERION_DRAFT = os.path.join(HERE, "..", "..", "docs", "redqueen_recovery_A", "CRITERION_rec_A_v1.draft.txt")


def rec_a_fixture(root, schedule):
    """A --test-fixture directory for rec_A_v1 (SYNTHETIC ONLY, never a real input): the toy graph; d8/ with an
    accepted-form synthetic bank/3 (test_obslaw's placeholder values, synthetic false, so acceptance mode admits it)
    whose inputs and receipt fields bind the placeholder provenance receipt, validation report and refit receipt written
    beside it, its gamma-1 tables, a witness receipt naming the placeholder validation spec, a #68 conformance receipt
    naming the bank artifact, and placeholders for the four bank inputs; placeholder authorities; the CRITERION draft;
    the schedule spec -> (the directory, the bank artifact's sha256)."""
    import rec_A_v1 as W
    import test_graph as TG
    fx = os.path.join(root, "fixture")
    graph.write(toy(opponents=12), os.path.join(fx, "graph"))
    d8 = os.path.join(fx, "d8")
    os.makedirs(d8)

    def put(name, data):
        rqlib.write_durable(os.path.join(d8, name), data)
        return hashlib.sha256(data).hexdigest()
    pv = put(W.PROVENANCE, b'{"test": "a placeholder provenance receipt (synthetic)"}\n')
    vr = put(W.VALIDATION_REPORT, b'{"test": "a placeholder validation report (synthetic)"}\n')
    rc = put(W.BANK_RECEIPT, b'{"test": "a placeholder refit receipt (synthetic)"}\n')
    spec = put(W.VALIDATION_SPEC, b'{"test": "a placeholder validation spec (synthetic)"}\n')
    put(W.VALIDATION_WITNESS, f"synthetic witness of {spec}\n".encode())
    for n in W.BANK_INPUTS:
        put(n, f"a placeholder for {n} (synthetic, not the registered bytes)\n".encode())
    doc = TG.bank_doc()
    doc["inputs"].update(provenance_sha256=pv, validation_report_sha256=vr)
    doc["fit"]["noise"].update(inputs_sha256=rqlib.canonical_sha(doc["inputs"]), receipt_sha256=rc)
    bp, tp = TG.bank_files("rec_a_v1", doc)
    shutil.copy(bp, os.path.join(d8, W.BANK_ARTIFACT))
    shutil.copy(tp, os.path.join(d8, W.OBS_TABLES))
    put(W.CONFORMANCE, f"synthetic #68 conformance of {rqlib.sha256_file(bp)}\n".encode())
    auth = os.path.join(fx, "authority")
    os.makedirs(auth)
    for n in W.AUTHORITIES:
        rqlib.write_durable(os.path.join(auth, n), f"a placeholder for {n}\n")
    shutil.copy(CRITERION_DRAFT, os.path.join(fx, "CRITERION.txt"))
    rqlib.write_json_durable(os.path.join(fx, "schedule.json"), schedule)
    return fx, rqlib.sha256_file(bp)


def procs_with(text):
    """Live processes whose command line contains text -> [(pid, command line)]."""
    out = []
    for pid in os.listdir("/proc"):
        if pid.isdigit() and int(pid) != os.getpid():
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace")
            except OSError:
                continue
            if text in cmd:
                out.append((int(pid), cmd))
    return out


def group_members(pgid):
    """The processes of process group pgid, zombies included (/proc/<pid>/stat's pgrp field) -> [pid]."""
    out = []
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                with open(f"/proc/{pid}/stat") as f:
                    fields = f.read().rsplit(")", 1)[1].split()
            except (OSError, IndexError):
                continue
            if int(fields[2]) == pgid:
                out.append(int(pid))
    return out


def toy_production(root):
    """A toy production study for rec_A_v1.production_inputs (SYNTHETIC ONLY: toy registry, reservation, bank-plan and
    fork metadata, never a real input) -> (PROD, BANK, the registry's sha256, the registry). PROD/config: a 64-world
    registry (worlds.register on test_worlds' toy arena, the registered 64 layout, one toy avoidance file; its namespace
    FIELD relabelled to the literal production_inputs checks, while its seeds and uuids stay the toy namespace's), its
    verification record and two placeholders; PROD/reservations: one seed-named toy reservation; BANK/config: an empty
    avoidance provenance, an 18,432-row plan of toy seeds outside the registry's, two placeholders. No PROD/graph and
    no PROD/config/forks.json: the graph is built and the forks registered inside P_REC (the intended, unpublished
    production graph's path)."""
    import worlds
    from test_worlds import ARENA
    prod, bank = os.path.join(root, "prod"), os.path.join(root, "bank")
    for d in (os.path.join(prod, "config"), os.path.join(prod, "reservations"), os.path.join(bank, "config"),
              os.path.join(root, "registry_avoid")):
        os.makedirs(d)
    arena, avoid = os.path.join(root, "arena.json"), os.path.join(root, "registry_avoid", "toy.avoid.json")
    rqlib.write_json_durable(arena, ARENA)
    rqlib.write_json_durable(avoid, {"seeds": [5]})
    reg = worlds.register(arena, "toy-rec-a-inventory", per_block=worlds.LAYOUTS["64"], avoid_paths=[avoid],
                          layout="64")
    reg["namespace"] = "finfolk-rq-production-2026-11-d6d7-v1"
    wpath = os.path.join(prod, "config", "worlds.json")
    rqlib.write_durable(wpath, rqlib.canonical(reg))
    regsha = rqlib.sha256_file(wpath)
    rqlib.write_json_durable(os.path.join(prod, "config", "registry.verify.json"),
                             {"ok": True, "registry_sha256": regsha})
    for n in ("reservation_sources.json", "arena.selected.json"):
        rqlib.write_json_durable(os.path.join(prod, "config", n), {"test": f"a placeholder {n} (synthetic)"})
    rqlib.write_json_durable(os.path.join(prod, "reservations", "toy.seeds.json"), {"seeds": [7]})
    rqlib.write_json_durable(os.path.join(bank, "config", "production_avoid_sources.json"), [])
    hist = {s for x in reg["reserved"] for s in x["seeds"]}
    seeds = [s for s in range(1_000_000, 1_100_000) if s not in hist][:18432]
    rqlib.write_durable(os.path.join(bank, "config", "bank.plan.jsonl"), "".join(
        json.dumps({"schema": "finfolk.redqueen.plan/2", "seed": s}) + "\n" for s in seeds))
    for n in ("bank.design.json", "readiness.json"):
        rqlib.write_json_durable(os.path.join(bank, "config", n), {"test": f"a placeholder {n} (synthetic)"})
    return prod, bank, regsha, reg


@unittest.skipIf(np is None or not sys.platform.startswith("linux") or not shutil.which("nice")
                 or not shutil.which("ps"), "numpy, Linux, nice and ps required")
class TestRecAV1Wrapper(unittest.TestCase):
    """The wrapper rec_A_v1.sh / rec_A_v1.py (A_design_v5 4.4; clarification 4 F1), end to end on the toy graph with a
    synthetic accepted-form bank/3 through its test fixture (CI-sized; never a real input): measure, prepare, the
    schedule and the freeze, the refusals, a run with 2 workers and its interruption, the acceptance packet."""
    FAST = {"namespace": A1, "fit": {"ranks": 1, "lambdas": "0.05", "iters": 2, "start": "warm", "basis": 4},
            "legacy": [dict(name="main", role="C1-primary", scenarios=["r1_034"], reps=1, options=["a", "fwd"],
                            basis=4, embedding="shared", center="references"),
                       dict(name="numerical_num_r1", role="numerical", scenarios=["num_r1"], reps=1, options=["a"],
                            basis=4, embedding="shared", center="references")],
            "extra": [dict(name="interp", role="extra-interp", options=["interp"], cases=["intact"],
                           scenarios=["r1_034"], reps=1),
                      dict(name="attrition", role="extra-attrition", options=["a", "fwd_all"], cases=["roots1"],
                           scenarios=["r0"], reps=1)]}

    def setUp(self):
        import rec_A_v1 as W
        self.W = W
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.prec = os.path.join(self.root, "P_REC")

    def tearDown(self):
        for pid, _ in procs_with(self.root):
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)
        for d, _, fs in os.walk(self.root):          # (the read-only copies: writable again for the cleanup)
            for n in fs:
                with contextlib.suppress(OSError):
                    os.chmod(os.path.join(d, n), 0o600)
        self.tmp.cleanup()

    def wrap(self, *args, jobs="2", nice=True, env=None, background=False, fixture=True):
        e = {k: v for k, v in os.environ.items() if k not in ("D8_DIR", "AUTHORITY_DIR", "CRITERION", "JOBS",
                                                                "RQ_REC_A_TEST_FIXTURE", "EXTRA_AVOID")}
        e.update(P_REC=self.prec, JOBS=jobs, PY=sys.executable, **(env or {}))
        if fixture:             # (fixture False: a production-mode invocation of a test root, refused by its mode)
            e["RQ_REC_A_TEST_FIXTURE"] = self.fx
        cmd = (["nice", "-n", "19"] if nice else []) + ["bash", REC_A_SH, *args]
        if background:
            return subprocess.Popen(cmd, env=e, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
        return subprocess.run(cmd, env=e, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=1800)

    def expected_schedule(self, spec):
        """clarification 4 F1's document, built here independently of the wrapper from the prepared directories."""
        dirs, oms = [], set()
        for x in spec["legacy"]:
            cfg = rqlib.read_json(os.path.join(self.prec, "runs", x["name"], "config.json"))
            oms.add(rqlib.canonical_sha(cfg["observation_model"]))
            dirs.append({"dir": f"runs/{x['name']}", "kind": "legacy", "role": x["role"], "scenarios": x["scenarios"],
                         "reps": x["reps"], "options": x["options"],
                         "expected_config_sha256": rqlib.canonical_sha(cfg)})
        for x in spec["extra"]:
            plan = X.read_frozen(os.path.join(self.prec, "extra", x["name"]))
            oms.add(plan["inputs"]["observation_model_sha256"])
            dirs.append({"dir": f"extra/{x['name']}", "kind": "extra", "role": x["role"], "scenarios": x["scenarios"],
                         "reps": x["reps"], "options": x["options"], "cases": x["cases"],
                         "expected_plan_sha256": rqlib.canonical_sha(plan)})
        self.assertEqual(len(oms), 1)
        return {"schema": "finfolk.redqueen.recoveryschedule/1", "observation_model_sha256": oms.pop(),
                "inputs": {"graph": "inputs/graph/graph.jsonl.gz", "references": None,
                           "bank": "inputs/bank/bank_d8.json", "obs_tables": "inputs/bank/obs_tables.npz"},
                "directories": dirs}

    def frozen(self):
        return dict(reversed(line.split("  ", 1)) for line in
                    rqlib.read_text(os.path.join(self.prec, "FROZEN.sha256")).splitlines())

    def test_rec_A_v1_end_to_end_measure_prepare_refusals_run_and_cleanup(self):
        """v5 4.4 end to end (toy graph, synthetic accepted-form bank/3, the test fixture; 2 workers):
        measure -- the measurement-only benchmark (r2_034, a and fwd, bank mode, namespace
        rq2026-d8-recovery-A1-measure, the registered fit) records completion, timing, RSS and unresolved counts only; a
        second benchmark is refused. prepare -- SCHEDULE.json is clarification 4 F1's document byte for byte (built
        here independently, and recovery.py's own F1 parser accepts it); FROZEN.sha256 binds every v5 4.4 input (the
        bank/D8 files as read-only copies of the fixture's bytes, the tool snapshot with obslaw, material, common,
        noisescale and the ages fixture, the wrapper pair and the criterion, every configuration and plan, the
        authorities, SCHEDULE.json) and the benchmark as measurement-only; every configuration and plan is bank mode
        in namespace rq2026-d8-recovery-A1 and binds the fixture bank; measure after the freeze is refused. Refused:
        JOBS 3 (the shell and the Python), the diagnostic mode (both), no nice 19 (where the test itself is not at nice
        19), a second concurrent wrapper (the lock), run without PRIOR.receipt, a changed bound input, a
        planning-mode configuration under P_REC. run -- interrupted by SIGTERM while a worker runs: exit 2, every
        process of P_REC reaped (process-group cleanup), status.json written; resumed: every scheduled result written
        in bank mode by commands that all carry --obs-model bank, the bank and the tables (never the synthetic-bank
        flag), at --jobs 2 and one stage at a time, then the acceptance packet through recovery.py packet --mode
        acceptance only, which refuses this toy schedule (not the frozen C2 matrix): exit 2, as it must."""
        W = self.W
        self.fx, bank_sha = rec_a_fixture(self.root, self.FAST)
        cp = self.wrap("measure")
        self.assertEqual(cp.returncode, 0, cp.stderr[-3000:])
        m = rqlib.read_json(os.path.join(self.prec, "measure", "MEASUREMENT.json"))
        self.assertEqual(sorted(m), sorted(["label", "namespace", "scenario", "options", "completed", "wall_s", "cpu_s",
                                            "max_rss_kib", "unresolved_integration_pairs"]))
        self.assertEqual((m["namespace"], m["scenario"], m["completed"]), (MEASURE_NS, "r2_034", True))
        mcfg = rqlib.read_json(os.path.join(self.prec, "measure", "r2_034", "config.json"))
        self.assertEqual((mcfg["namespace"], mcfg["observation_model"]["mode"], mcfg["ranks"], mcfg["iters"]),
                         (MEASURE_NS, "bank", 4, 30))
        self.assertNotEqual(MEASURE_NS, A1)
        cp = self.wrap("measure")
        self.assertEqual(cp.returncode, 2)
        self.assertIn("a single dataset", cp.stderr)
        cp = self.wrap("prepare")
        self.assertEqual(cp.returncode, 0, cp.stderr[-3000:])
        self.assertIn("PREPARED, no recovery observations generated. Witness:", cp.stdout)
        raw = rqlib.read_bytes(os.path.join(self.prec, "SCHEDULE.json"))
        self.assertEqual(raw, rqlib.canonical(self.expected_schedule(self.FAST)))
        entries = R._schedule_entries(json.loads(raw), self.prec)
        self.assertEqual([e["role"] for e in entries], ["C1-primary", "numerical", "extra-interp", "extra-attrition"])
        fz = self.frozen()
        want = (["SCHEDULE.json", "MEASUREMENT_ONLY.sha256", "measure/MEASUREMENT.json", "measure/r2_034/config.json",
                 "measure/r2_034/r2_034.000.json", "control/rec_A_v1.sh", "control/rec_A_v1.py",
                 "control/CRITERION.txt", "runs/main/config.json", "runs/numerical_num_r1/config.json",
                 "extra/interp/plan.json", "extra/interp/diagnostics.json", "extra/interp/FROZEN.sha256",
                 "extra/attrition/plan.json", "tools/redqueen/fixtures/registered_ages.json", "inputs/provenance.json",
                 "inputs/policy.json", "inputs/runtime_files.json", "inputs/graph/graph.jsonl.gz"]
                + [f"tools/redqueen/{n}" for n in ("obslaw.py", "material.py", "common.py", "noisescale.py",
                                                   "recovery.py", "recovery_extra.py", "map.py", "rec_A_v1.py")]
                + [f"inputs/bank/{n}" for n in D8_NAMES] + [f"authority/{n}" for n in AUTHORITY_NAMES])
        self.assertEqual((sorted(W.D8_FILES), sorted(W.AUTHORITIES)), (sorted(D8_NAMES), sorted(AUTHORITY_NAMES)))
        for name in want:
            with self.subTest(frozen=name):
                self.assertIn(name, fz)
                self.assertEqual(fz[name], rqlib.sha256_file(os.path.join(self.prec, name)))
        for n in D8_NAMES:
            p = os.path.join(self.prec, "inputs", "bank", n)
            self.assertEqual(rqlib.read_bytes(p), rqlib.read_bytes(os.path.join(self.fx, "d8", n)), n)
            self.assertEqual(os.stat(p).st_mode & 0o777, 0o444, n)
        self.assertIn("measure/r2_034/r2_034.000.json", rqlib.read_text(os.path.join(self.prec,
                                                                                      "MEASUREMENT_ONLY.sha256")))
        for x in self.FAST["legacy"]:
            cfg = rqlib.read_json(os.path.join(self.prec, "runs", x["name"], "config.json"))
            om = cfg["observation_model"]
            self.assertEqual((cfg["namespace"], om["mode"], om["accepting"], om["bank_artifact_sha256"]),
                             (A1, "bank", True, bank_sha), x["name"])
        for x in self.FAST["extra"]:
            plan = X.read_frozen(os.path.join(self.prec, "extra", x["name"]))
            self.assertEqual((plan["namespace"], plan["noise_source"], plan["inputs"]["bank_artifact_sha256"]),
                             (A1, "bank_d8", bank_sha), x["name"])
        cp = self.wrap("measure")
        self.assertEqual(cp.returncode, 2)
        self.assertIn("precedes the freeze", cp.stderr)
        # refusals before any run
        refusals = [(("run",), dict(jobs="3"), "JOBS must be 1 or 2"),
                    (("run", "--mode", "diagnostic"), {}, "takes the phase only"),
                    (("run",), {}, "witness receipt")]
        for args, kw, why in refusals:
            with self.subTest(refusal=why):
                cp = self.wrap(*args, **kw)
                self.assertEqual(cp.returncode, 2, cp.stderr[-1500:])
                self.assertIn(why, cp.stderr)
        py = ["nice", "-n", "19", sys.executable, "-I", "-B", os.path.join(HERE, "rec_A_v1.py")]
        for args, why in ((["run", "--root", self.prec, "--jobs", "3", "--test-fixture", self.fx], "at most 2"),
                          (["run", "--root", self.prec, "--test-fixture", self.fx, "--mode", "diagnostic"],
                           "never uses diagnostic mode")):
            cp = subprocess.run(py + args, stdin=subprocess.DEVNULL, capture_output=True, text=True)
            self.assertEqual(cp.returncode, 2, cp.stderr)
            self.assertIn(why, cp.stderr)
        if os.getpriority(os.PRIO_PROCESS, 0) != 19:
            cp = self.wrap("run", nice=False)
            self.assertEqual(cp.returncode, 2)
            self.assertIn("Launch with nice -n 19", cp.stderr)
        import fcntl
        with open(os.path.join(self.prec, ".lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            cp = self.wrap("run")
            fcntl.flock(lock, fcntl.LOCK_UN)
        self.assertEqual(cp.returncode, 2)
        self.assertIn("holds the P_REC lock", cp.stderr)
        digest = rqlib.sha256_file(os.path.join(self.prec, "FROZEN.sha256"))
        rqlib.write_durable(os.path.join(self.prec, "PRIOR.receipt"), f"synthetic witness of {digest}\n")
        tables = os.path.join(self.prec, "inputs", "bank", "obs_tables.npz")
        good = rqlib.read_bytes(tables)
        os.chmod(tables, 0o600)
        rqlib.write_durable(tables, good[:-1] + bytes([good[-1] ^ 1]))
        cp = self.wrap("run")
        self.assertEqual(cp.returncode, 2)
        self.assertIn("frozen input changed: inputs/bank/obs_tables.npz", cp.stderr)
        rqlib.write_durable(tables, good)
        os.chmod(tables, 0o444)
        stray = os.path.join(self.prec, "runs", "stray")
        os.makedirs(stray)
        cfg = rqlib.read_json(os.path.join(self.prec, "runs", "main", "config.json"))
        cfg["observation_model"] = R.observation_model(argparse.Namespace(obs_model="planning"))
        rqlib.write_durable(os.path.join(stray, "config.json"), rqlib.canonical(cfg))
        cp = self.wrap("run")
        self.assertEqual(cp.returncode, 2)
        self.assertIn("runs/stray/config.json: a planning-mode or non-accepting configuration", cp.stderr)
        shutil.rmtree(stray)
        self.assertEqual(rqlib.read_json(os.path.join(self.prec, "status.json"))["exit"], 2)
        # run, interrupted while a worker runs: every process under P_REC is reaped
        p = self.wrap("run", background=True)
        t0 = time.time()
        while time.time() - t0 < 300 and not any(" one " in c for _, c in procs_with(self.prec)):
            time.sleep(0.2)
        self.assertTrue(any(" one " in c for _, c in procs_with(self.prec)), "no worker started")
        p.send_signal(signal.SIGTERM)
        out, err = p.communicate(timeout=120)
        self.assertEqual(p.returncode, 2, err[-2000:])
        self.assertIn("FAILED: signal 15", err)
        time.sleep(0.5)
        self.assertEqual(procs_with(self.prec), [])
        self.assertEqual(rqlib.read_json(os.path.join(self.prec, "status.json"))["phase"], "run")
        # resumed to the end: every result in bank mode, the commands, the packet (acceptance only)
        cp = self.wrap("run")
        self.assertEqual(cp.returncode, 2, cp.stderr[-3000:])
        self.assertIn("the acceptance packet exits 2", cp.stderr)
        for x in self.FAST["legacy"]:
            for sc in x["scenarios"]:
                r = rqlib.read_json(os.path.join(self.prec, "runs", x["name"], f"{sc}.000.json"))
                self.assertEqual((r["noise_source"], r["observation_model_sha256"]),
                                 ("bank_d8", json.loads(raw)["observation_model_sha256"]), x["name"])
        for x in self.FAST["extra"]:
            d = os.path.join(self.prec, "extra", x["name"])
            self.assertEqual(len(X.read_results(d, X.read_frozen(d))), 1, x["name"])
        cmds = [ln for ln in cp.stdout.splitlines() if " -I -B " in ln]
        bank = ["--obs-model", "bank", "--bank", os.path.join(self.prec, "inputs", "bank", "bank_d8.json"),
                "--obs-tables", os.path.join(self.prec, "inputs", "bank", "obs_tables.npz")]
        stages = [shlex.split(c) for c in cmds if re.search(r"recovery(_extra)?\.py run ", c)]
        self.assertEqual(len(stages), len(self.FAST["legacy"]) + len(self.FAST["extra"]))
        for c in stages:
            k = c.index("--obs-model")
            self.assertEqual(c[k:k + 6], bank, c)
            self.assertEqual(c[c.index("--jobs") + 1], "2", c)
        self.assertNotIn("--allow-synthetic-bank", cp.stdout)
        packets = [shlex.split(c) for c in cmds if "recovery.py packet" in c]
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0][packets[0].index("--mode") + 1], "acceptance")
        self.assertNotIn("diagnostic", cp.stdout)
        attempt = rqlib.read_json(os.path.join(self.prec, "status.json"))["attempt"]
        log = os.path.join(self.prec, "logs", f"{attempt}.packet.log")
        self.assertIn("REFUSED before any check: --mode acceptance: the schedule is incomplete", rqlib.read_text(log))
        self.assertTrue(os.path.isfile(os.path.join(self.prec, "ARTIFACTS.sha256")))

    def test_rec_A_v1_run_produces_a_passing_acceptance_packet_on_a_complete_toy_matrix(self):
        """The wrapper's run phase on a complete schedule (the toy version of the frozen C2 matrix that T7-8 uses: every
        role, a C1-primary of r1_034 / r2_034 x 20, the four sensitivity variants, the registered fit): prepared by the
        real wrapper, every result fabricated as complete() fabricates them (a real C1-primary of 40 registered fits is
        not CI-sized, and C1's 16/20 is the data's), the witness installed; then run() -- every stage executes with
        nothing left to compute -- produces the packet through exactly `recovery.py packet --mode acceptance
        --schedule P_REC/SCHEDULE.json --out P_REC/acceptance.<attempt>.json` (the toy C2 matrix substituted in that
        child alone, as T7-8 substitutes it in process): exit 0, every check pass, so run returns normally."""
        W = self.W
        TP = TestRecoveryBankPacket
        surface = {"basis": 6, "embedding": "shared", "center": "references"}
        legacy = [dict(name="primary", role="C1-primary", scenarios=list(TP.C1S), reps=20, options=["a", "fwd"],
                       **surface),
                  dict(name="stress", role="stress", scenarios=["r0_asym"], reps=1, options=["a", "fwd"], **surface),
                  dict(name="numerical", role="numerical", scenarios=["num_r1"], reps=1, options=["a"], **surface)]
        legacy += [dict(name=v, role="sensitivity", scenarios=list(TP.C1S), reps=20, options=["a", "fwd"],
                        **dict(surface, **kw)) for v, kw in TP.VARIANTS]
        extra = [dict(name=op, role=f"extra-{op}", options=[op], cases=["intact"], scenarios=["r1_034"], reps=1)
                 for op in ("interp", "fwd_all", "fwd_early")]
        extra.append(dict(name="attrition", role="extra-attrition", options=["a"], cases=["roots0"], scenarios=["r0"],
                          reps=1))
        spec = {"namespace": A1, "legacy": legacy, "extra": extra}
        self.fx, _ = rec_a_fixture(self.root, spec)
        cp = self.wrap("prepare")
        self.assertEqual(cp.returncode, 0, cp.stderr[-3000:])
        for x in legacy:
            d = os.path.join(self.prec, "runs", x["name"])
            cfg = rqlib.read_json(os.path.join(d, "config.json"))
            for sc in x["scenarios"]:
                for rep in range(x["reps"]):
                    win = x["role"] != "C1-primary" or rep < (16 if sc == "r1_034" else 17)
                    write_result(d, fabricated(cfg, sc, rep, success=win, options=x["options"]))
        for x in extra:
            fabricated_extra(os.path.join(self.prec, "extra", x["name"]), x["cases"][0], x["scenarios"][0], 0)
        digest = rqlib.sha256_file(os.path.join(self.prec, "FROZEN.sha256"))
        rqlib.write_durable(os.path.join(self.prec, "PRIOR.receipt"), f"synthetic witness of {digest}\n")
        toy_c2 = {r: [{k: list(v) if isinstance(v, tuple) else v for k, v in b.items()} for b in bl]
                  for r, bl in TP.TOY_C2.items()}
        shim = ("import json, sys\nsys.path.insert(0, sys.argv[1])\nimport recovery\n"
                "recovery.C2_MATRIX = json.loads(sys.argv[2])\nsys.exit(recovery.main(sys.argv[3:]))\n")
        real, seen = W.call, []

        def call(args, label, check=True):
            if label == "packet":
                args = [str(x) for x in args]
                seen.append(args)
                return real(["-c", shim, os.path.dirname(args[0]), json.dumps(toy_c2), *args[1:]], label, check)
            return real(args, label, check)
        W.configure(argparse.Namespace(root=self.prec, jobs=2, d8=None, authority=None, criterion=None,
                                       test_fixture=self.fx))
        with mock.patch.object(W, "call", call), contextlib.redirect_stdout(io.StringIO()):
            W.run()
        tools = os.path.join(self.prec, "tools", "redqueen")
        out = os.path.join(self.prec, f"acceptance.{W.STAMP}.json")
        self.assertEqual(seen, [[os.path.join(tools, "recovery.py"), "packet", "--mode", "acceptance", "--schedule",
                                 os.path.join(self.prec, "SCHEDULE.json"), "--out", out]])
        p = rqlib.read_json(out)
        self.assertEqual({k: c["status"] for k, c in p["checks"].items()},
                         dict.fromkeys(("identity", "completeness", "numerical", "pairing", "guards", "C1"), "pass"),
                         p["checks"])
        self.assertEqual((p["mode"], p["scope"], p["accepting"], p["exit"]), ("acceptance", "bank/D8", True, 0))
        self.assertEqual({s: v["successes"] for s, v in p["checks"]["C1"]["scenarios"].items()},
                         {"r1_034": 16, "r2_034": 17})

    # ---------------------------------------------------------------- WP5 fix round 2 (Codex revWP5 at 9ce0f61)
    def witness(self):
        digest = rqlib.sha256_file(os.path.join(self.prec, "FROZEN.sha256"))
        rqlib.write_durable(os.path.join(self.prec, "PRIOR.receipt"), f"synthetic witness of {digest}\n")

    def refreeze(self, name, data):
        """Replace one frozen file of the prepared root by data, re-freeze FROZEN.sha256's entry and re-witness it
        (what a prepare of other inputs would have frozen)."""
        p = os.path.join(self.prec, name)
        os.chmod(p, 0o600)
        rqlib.write_durable(p, data)
        fz = os.path.join(self.prec, "FROZEN.sha256")
        lines = [f"{hashlib.sha256(data).hexdigest()}  {name}" if ln.split("  ", 1)[1] == name else ln
                 for ln in rqlib.read_text(fz).splitlines()]
        rqlib.write_durable(fz, "".join(ln + "\n" for ln in lines))
        self.witness()

    def test_rec_A_v1_production_inventory_restores_extra_avoid_on_a_toy_registry(self):
        """Codex WP5 P2-W5-1 and the line-by-line recheck of production_inputs against rec_C_v2.py, in process on a toy
        production study (toy_production: SYNTHETIC registry, reservation, bank-plan and fork metadata, never a real
        input; PROD, BANK and REGSHA pointed at it). EXTRA_AVOID (rec_C_v2.py:120-130): a listed file that is missing
        is refused; a listed reservation holding a proposed fork seed is refused by the fork registration, and one
        holding an actual production fork's seed, a history seed or an unrelated bank seed by the collision checks; a
        valid list is copied (inputs/extra_avoid.list), its file copied into inputs/reservations/ as a collision path,
        checked (avoid_checks.json), passed to forks.register and bound by FROZEN.sha256's manifest. In fixture mode
        EXTRA_AVOID is refused. The recheck's other restorations: the planning fork registry is re-derived by a second
        inventory and the planning graph even when a copy is already in P_REC (a changed copy is refused, as
        rec_C_v2's unconditional register through same() and build through graph.py's write refused it), and a
        reserved slot without exactly nine seeds is refused (rec_C_v2.py:157)."""
        import forks
        from pathlib import Path
        W = self.W
        prod, bank, regsha, reg = toy_production(self.root)
        hist = {s for x in reg["reserved"] for s in x["seeds"]}
        stamps = iter(range(1000))

        def inventory(name, extra=None, **patch):
            """production_inputs into P_REC.<name> with EXTRA_AVOID = extra (unset: None) -> the root."""
            root = os.path.realpath(os.path.join(self.root, f"P_REC.{name}"))
            for d in ("logs", "timing"):
                os.makedirs(os.path.join(root, d), exist_ok=True)
            W.configure(argparse.Namespace(root=root, jobs=2, d8=None, authority=None, criterion=None,
                                           test_fixture=None))
            kw = dict(PROD=Path(prod), BANK=Path(bank), REGSHA=regsha, T=Path(HERE), STAMP=f"inv{next(stamps)}")
            kw.update(patch)
            with mock.patch.multiple(W, **kw), mock.patch.dict(os.environ, {"EXTRA_AVOID": extra or ""}), \
                    contextlib.redirect_stdout(io.StringIO()):
                W.production_inputs()
            return root

        def reservation(name, seeds):
            p = os.path.join(self.root, "extra", f"{name}.seeds.json")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            rqlib.write_json_durable(p, {"seeds": sorted(seeds)})
            return p

        def listing(name, *files):
            p = os.path.join(self.root, f"{name}.extra_avoid.list")
            rqlib.write_durable(p, "".join(f"{f}\n" for f in files) + "\n")      # (a blank line is skipped)
            return p
        base = inventory("base")                     # (no EXTRA_AVOID: the planning forks this study proposes)
        fork_seed = rqlib.read_json(os.path.join(base, "inputs/study/config/forks.json"))["worlds"][0]["origin"]["seed"]
        bank_seed = json.loads(rqlib.read_text(os.path.join(bank, "config", "bank.plan.jsonl")).splitlines()[0])["seed"]
        self.assertNotIn(fork_seed, hist)
        fork_file = reservation("fork_collision", {fork_seed})
        cases = [("a listed file that is missing", [os.path.join(self.root, "extra", "absent.seeds.json")],
                  RuntimeError, "EXTRA_AVOID lists a missing reservation file: .*/extra/absent.seeds.json"),
                 ("a reserved seed colliding with a proposed fork seed", [fork_file], forks.ForkError,
                  rf"\({fork_seed}\) is a seed reserved in "
                  r".*/inputs/reservations/\d{3}\.fork_collision\.seeds\.json"),
                 ("a history seed", [reservation("history_collision", {min(hist)})], AssertionError,
                  r"history shares avoidance seeds: .*/inputs/reservations/\d{3}\.history_collision\.seeds\.json"),
                 ("an unrelated bank seed", [reservation("bank_collision", {bank_seed})], RuntimeError,
                  r"bank shares unrelated avoidance seeds: .*/inputs/reservations/\d{3}\.bank_collision\.seeds\.json")]
        for i, (case, files, exc, why) in enumerate(cases):
            with self.subTest(extra_avoid=f"{case}: refused"):
                with self.assertRaisesRegex(exc, why):
                    inventory(f"refused{i}", listing(f"refused{i}", *files))
        with self.subTest(extra_avoid="a reserved seed colliding with an actual production fork's seed: refused"):
            shutil.copy(os.path.join(base, "inputs/study/config/forks.json"),
                        os.path.join(prod, "config", "forks.json"))
            try:
                with self.assertRaisesRegex(AssertionError, r"/inputs/reservations/\d{3}\.fork_collision\.seeds\.json"):
                    inventory("actual", listing("actual", fork_file))
            finally:
                os.remove(os.path.join(prod, "config", "forks.json"))
        ok = reservation("extra_ok", {11, 13})
        lst = listing("valid", ok)
        with self.subTest(extra_avoid="a valid list: copied, checked, passed to forks.register, frozen"):
            seen, real = [], forks.register

            def spy(*a, **k):
                seen.append(list(k.get("avoid_paths", ())))
                return real(*a, **k)
            with mock.patch.object(forks, "register", spy):
                root = inventory("valid", lst)
            self.assertTrue(os.path.isfile(os.path.join(root, "inputs", "extra_avoid.list")),
                            "EXTRA_AVOID's list is not copied into P_REC")
            self.assertEqual(rqlib.read_bytes(os.path.join(root, "inputs", "extra_avoid.list")), rqlib.read_bytes(lst))
            copies = [n for n in sorted(os.listdir(os.path.join(root, "inputs", "reservations")))
                      if n.endswith(".extra_ok.seeds.json")]
            self.assertEqual(len(copies), 1, copies)
            cpath = os.path.join(root, "inputs", "reservations", copies[0])
            self.assertEqual(rqlib.read_bytes(cpath), rqlib.read_bytes(ok))
            self.assertIn(cpath, rqlib.read_json(os.path.join(root, "inputs", "avoid_paths.json")))
            self.assertIn(cpath, [x["path"] for x in rqlib.read_json(os.path.join(root, "inputs",
                                                                                     "avoid_checks.json"))["files"]])
            self.assertEqual(len(seen), 1)
            self.assertIn(cpath, seen[0])
            fz = dict(reversed(ln.split("  ", 1)) for ln in W.frozen_manifest().decode().splitlines())
            for name in ("inputs/extra_avoid.list", f"inputs/reservations/{copies[0]}"):
                self.assertEqual(fz.get(name), rqlib.sha256_file(os.path.join(root, name)), name)
        with self.subTest(recheck="the planning fork registry is re-derived by a second inventory"):
            p = os.path.join(self.root, "P_REC.valid", "inputs/study/config/forks.json")
            good = rqlib.read_bytes(p)
            rqlib.write_durable(p, rqlib.canonical(dict(json.loads(good), doctored=True)))
            try:
                with self.assertRaisesRegex(RuntimeError,
                                            r"conflicting immutable bytes: .*/inputs/study/config/forks\.json"):
                    inventory("valid", lst)
            finally:
                rqlib.write_durable(p, good)
        with self.subTest(recheck="the planning graph is re-derived, never trusted (a changed copy in P_REC before the "
                                  "first inventory)"):
            src = os.path.join(self.root, "P_REC.valid", "inputs", "graph")
            dst = os.path.join(self.root, "P_REC.planted", "inputs", "graph")
            os.makedirs(dst)
            shutil.copy(os.path.join(src, "graph.jsonl.gz"), dst)
            meta = rqlib.read_json(os.path.join(src, "graph.meta.json"))
            rqlib.write_durable(os.path.join(dst, "graph.meta.json"), rqlib.canonical(dict(meta, doctored=True)))
            with self.assertRaisesRegex(RuntimeError, "graph-build: exit 2"):
                inventory("planted", lst)
        with self.subTest(recheck="a reserved slot without exactly nine seeds: refused"):
            bad = copy.deepcopy(reg)
            bad["reserved"][0]["seeds"].append(bad["reserved"][1]["seeds"].pop())    # (10 and 8: still 576 seeds)
            prod9 = os.path.join(self.root, "prod9")
            shutil.copytree(prod, prod9)
            rqlib.write_durable(os.path.join(prod9, "config", "worlds.json"), rqlib.canonical(bad))
            sha9 = rqlib.sha256_file(os.path.join(prod9, "config", "worlds.json"))
            rqlib.write_json_durable(os.path.join(prod9, "config", "registry.verify.json"),
                                     {"ok": True, "registry_sha256": sha9})
            with self.assertRaisesRegex(AssertionError, "nine seeds"):
                inventory("nine", PROD=Path(prod9), REGSHA=sha9)
        with self.subTest(extra_avoid="fixture mode: refused (the fixture has no study inventory)"):
            root = os.path.join(self.root, "P_REC.fixture")
            W.configure(argparse.Namespace(root=root, jobs=2, d8=None, authority=None, criterion=None,
                                           test_fixture=os.path.join(self.root, "no-fixture")))
            with mock.patch.dict(os.environ, {"EXTRA_AVOID": lst}), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "EXTRA_AVOID is a production study input"):
                    W.all_inputs(freeze=False)
            self.assertFalse(os.path.exists(os.path.join(root, "inputs")))

    def test_rec_A_v1_a_killed_supervisor_s_group_is_gone_before_the_lock_is_released(self):
        """Codex WP5 P2-W5-2 (toy graph, synthetic accepted-form bank/3, the test fixture; CI-sized): the legacy
        `recovery.py run` SUPERVISOR is killed alone (SIGKILL) while its two workers fit. The wrapper's run exits 2,
        and at the moment it releases P_REC/.lock (polled) no process of the supervisor's group remains (on 9ce0f61
        the wrapper dropped the supervisor from its cleanup after wait4 and unlocked with the workers still fitting).
        Resumed, the run completes every scheduled dataset with at most 2 workers at any time and none of the old
        group, then reaches the acceptance packet, which refuses this toy schedule (as in the end-to-end test)."""
        import fcntl
        spec = {"namespace": A1, "fit": {"ranks": 2, "lambdas": "0.02,0.05,0.2", "iters": 20, "start": "both",
                                         "basis": 4},
                "legacy": [dict(name="main", role="C1-primary", scenarios=["r1_034"], reps=2, options=["a", "fwd"],
                                basis=4, embedding="shared", center="references")],
                "extra": []}
        self.fx, _ = rec_a_fixture(self.root, spec)
        cp = self.wrap("prepare")
        self.assertEqual(cp.returncode, 0, cp.stderr[-3000:])
        self.witness()

        def pgid(pid):
            try:
                return os.getpgid(pid)
            except ProcessLookupError:
                return None
        p = self.wrap("run", background=True)
        sup, t0 = None, time.time()
        while sup is None and time.time() - t0 < 300 and p.poll() is None:
            procs = procs_with(self.prec)
            for s in [pid for pid, c in procs if "recovery.py run " in c]:
                if sum("recovery.py one " in c and pgid(pid) == s for pid, c in procs) == 2:
                    sup = s
            time.sleep(0.05)
        self.assertIsNotNone(sup, "no legacy supervisor with two workers")
        time.sleep(1.0)                                   # (both workers fitting)
        workers = [pid for pid in group_members(sup) if pid != sup]
        self.assertEqual(len(workers), 2, workers)
        os.kill(sup, signal.SIGKILL)
        with open(os.path.join(self.prec, ".lock"), "a") as lock:
            deadline = time.time() + 120
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    self.assertLess(time.time(), deadline, "the wrapper never released its lock")
                    time.sleep(0.01)
            survivors = group_members(sup)                # (the instant the lock is free)
            fcntl.flock(lock, fcntl.LOCK_UN)
        out, err = p.communicate(timeout=120)
        self.assertEqual(survivors, [], f"processes of the killed supervisor's group outlived the wrapper's lock: "
                                        f"{survivors} (its workers {workers})")
        self.assertEqual(p.returncode, 2, err[-2000:])
        self.assertIn("legacy-main: exit -9; the rest of its process group stopped", err)
        q = self.wrap("run", background=True)
        peak, stray = 0, set()
        while q.poll() is None:
            peak = max(peak, sum("recovery.py one " in c for _, c in procs_with(self.prec)))
            stray.update(group_members(sup))
            time.sleep(0.05)
        out, err = q.communicate(timeout=120)
        self.assertEqual(q.returncode, 2, err[-3000:])
        self.assertIn("the acceptance packet exits 2", err)
        self.assertEqual(stray, set())
        self.assertLessEqual(peak, 2)
        for rep in range(2):
            r = rqlib.read_json(os.path.join(self.prec, "runs", "main", f"r1_034.{rep:03d}.json"))
            self.assertEqual(r["noise_source"], "bank_d8")

    def test_rec_A_v1_a_signal_between_spawn_and_tracking_still_stops_the_child(self):
        """Codex WP5 P2-W5-2, the spawn gap (in process, the wrapper's TERM handler installed): TERM sent after Popen
        has started the child but before call() tracks it (injected through subprocess.Popen) is delivered once the
        child is in CHILDREN, so the cleanup stops and reaps it (on 9ce0f61 the interrupt left an untracked child
        running). The child itself starts with TERM and INT unblocked (the wrapper's own mask, restored before exec)."""
        W = self.W
        for d in ("logs", "timing"):
            os.makedirs(os.path.join(self.prec, d))
        W.configure(argparse.Namespace(root=self.prec, jobs=2, d8=None, authority=None, criterion=None,
                                       test_fixture=None))
        real, spawned = subprocess.Popen, []

        def popen(*a, **k):
            child = real(*a, **k)
            spawned.append(child)
            os.kill(os.getpid(), signal.SIGTERM)          # (between the spawn and the tracking)
            return child
        status = os.path.join(self.root, "child.status")
        previous = signal.signal(signal.SIGTERM, W.interrupted)
        try:
            with mock.patch.object(W.subprocess, "Popen", popen), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(KeyboardInterrupt, "signal 15"):
                    W.call(["-c", "import time; time.sleep(120)", self.root], "gap")
            self.assertEqual(len(spawned), 1)
            left = W.stop_children()
            self.assertEqual(group_members(spawned[0].pid), [], "the untracked child still runs")
            self.assertEqual((left, spawned[0].returncode), ([], -signal.SIGTERM))
            with contextlib.redirect_stdout(io.StringIO()):
                W.call(["-c", "import sys; open(sys.argv[1], 'w').write(open('/proc/self/status').read())", status],
                       "mask")
        finally:
            signal.signal(signal.SIGTERM, previous)
        blocked = int(next(ln.split()[1] for ln in rqlib.read_text(status).splitlines() if ln.startswith("SigBlk:")),
                      16)
        self.assertEqual(blocked & (1 << (signal.SIGTERM - 1) | 1 << (signal.SIGINT - 1)), 0, f"SigBlk {blocked:x}")

    def test_rec_A_v1_an_exit_0_that_leaves_its_group_running_fails_the_stage(self):
        """Codex WP5 r2 P3-R2-2: a supervisor that exits 0 while a child of its own process group still runs is not a
        completed stage. call() stops the rest of the group while it is still tracked, then refuses the stage with
        check=True and with check=False alike. Nothing of the group survives and CHILDREN is empty. (The
        killed-supervisor test exits -9, so removing only the exit-0 refusal would pass it.)"""
        W = self.W
        for d in ("logs", "timing"):
            os.makedirs(os.path.join(self.prec, d))
        W.configure(argparse.Namespace(root=self.prec, jobs=2, d8=None, authority=None, criterion=None,
                                       test_fixture=None))
        supervisor = ("import os, subprocess, sys\n"
                      "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
                      "open(sys.argv[1], 'w').write(f'{os.getpid()} {c.pid}')\n"
                      "sys.exit(0)\n")
        for check in (True, False):
            with self.subTest(check=check):
                pids, label = os.path.join(self.root, f"straggler_{check}.pids"), f"straggler_{check}"
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(RuntimeError, "exit 0 with processes of its group still running"):
                        W.call(["-c", supervisor, pids], label, check=check)
                pgid, straggler = map(int, rqlib.read_text(pids).split())
                self.assertNotEqual(os.getpgid(os.getpid()), pgid, "the supervisor led its own group")
                self.assertEqual(group_members(pgid), [], f"the straggler {straggler} still runs")
                self.assertEqual(W.CHILDREN, set())
                timing = json.loads(rqlib.read_text(os.path.join(self.prec, "timing", f"{W.STAMP}.{label}.json")))
                self.assertEqual(timing["exit"], 0)

    def test_rec_A_v1_measurement_reports_the_branch_test_integrations_apart(self):
        """Codex WP5 P3-W5-1: MEASUREMENT.json's unresolved-integration counts report each forward branch's test
        comparison (its integration records stored under the branch, recovery.py forward_procedure, not among the
        candidates') apart from the candidates' records, labelled. The real measure() on the fixture, in process (FIT at
        the toy settings), whose benchmark dataset is produced by the real `recovery.py one` with ONE forward test
        comparison unresolved exactly as the registered map records one (grid_unresolved in the intersection branch's
        selected and rank-0 integration records) and every validation resolved: on 9ce0f61 it reported fwd 0."""
        W = self.W
        self.fx, _ = rec_a_fixture(self.root, self.FAST)
        for d in ("logs", "timing"):
            os.makedirs(os.path.join(self.prec, d))
        W.configure(argparse.Namespace(root=self.prec, jobs=1, d8=None, authority=None, criterion=None,
                                       test_fixture=self.fx))
        shim = ("import sys\nsys.path.insert(0, sys.argv[1])\nimport numpy as np\nimport recovery as R\n"
                "real = R.scorer\n\n\ndef flagged(D, *a, **k):\n    score = real(D, *a, **k)\n\n"
                "    def wrapped(ix, info=None):\n        out = score(ix, info)\n"
                "        if info is not None and np.array_equal(ix, D.forward['tests']['intersection']):\n"
                "            info['grid_unresolved'] = info.get('grid_unresolved', 0) + 1\n"
                "        return out\n    return wrapped\n\n\nR.scorer = flagged\nsys.exit(R.main(sys.argv[2:]))\n")
        real, seen = W.call, []

        def call(args, label, check=True):
            if label != "measure-r2_034":
                return real(args, label, check)
            a = [str(x) for x in args]
            seen.append(a)
            kv = dict(zip(a[2::2], a[3::2]))          # (run's flags -> one's, as recovery.py run builds a worker)
            out = kv.pop("--out")
            del kv["--jobs"], kv["--reps"]
            kv.update({"--scenario": kv.pop("--scenarios"), "--rep": "0", "--ab-cap": "-1",
                       "--out": os.path.join(out, "r2_034.000.json")})
            return real(["-c", shim, os.path.dirname(a[0]), "one", *(x for item in kv.items() for x in item)], label,
                        check)
        fit = {"ranks": 1, "lambdas": "0.05", "iters": 2, "start": "warm"}
        with mock.patch.object(W, "call", call), mock.patch.object(W, "FIT", fit), \
                contextlib.redirect_stdout(io.StringIO()):
            W.measure()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][1], "run")
        rec = rqlib.read_json(os.path.join(self.prec, "measure", "r2_034", "r2_034.000.json"))
        fwd = rec["options"]["fwd"]
        flags = {o: sum(int((c["integration"].get(s) or {}).get("grid_unresolved", 0))
                        for c in rec["options"][o]["candidates"] for s in ("validation", "test")) for o in ("a", "fwd")}
        self.assertEqual(flags, {"a": 0, "fwd": 0})       # (every validation resolved: the branch alone is unresolved)
        self.assertFalse(fwd["intersection"]["available"])
        self.assertTrue(fwd["intersection"]["integration_unresolved"] > 0)
        u = rqlib.read_json(os.path.join(self.prec, "measure", "MEASUREMENT.json"))["unresolved_integration_pairs"]
        self.assertIn("branch_tests", u, f"the forward branch's unresolved test comparison is not counted: {u}")
        self.assertEqual(u["candidates"], flags)
        self.assertEqual(u["branch_tests"]["a"], {})
        self.assertEqual(u["branch_tests"]["fwd"], {
            b: {k: int(fwd[b]["integration"][k].get("grid_unresolved", 0)) for k in ("selected", "rank0")}
            for b in ("forward_transfer", "intersection")})
        self.assertEqual(u["branch_tests"]["fwd"]["intersection"], {"selected": 1, "rank0": 1})
        self.assertEqual(u["branch_tests"]["fwd"]["forward_transfer"], {"selected": 0, "rank0": 0})
        self.assertIn("not summed", u["label"])

    def test_rec_A_v1_the_frozen_mode_binds_run_and_resume(self):
        """Codex WP5 P3-W5-2 (toy graph, synthetic accepted-form bank/3, the test fixture): prepare records the mode
        (inputs/mode.json, bound in FROZEN.sha256), and a run of the other mode is refused in both directions -- the
        fixture-frozen root run without --test-fixture, and a production-frozen root (the mode record a production
        prepare writes, re-frozen and re-witnessed) run with --test-fixture, whose resource preflight 9ce0f61 skipped
        without a toy graph; a fixture-frozen root whose frozen graph is not a recovery toy is refused before the
        preflight is skipped. No result is written."""
        spec = {"namespace": A1, "fit": self.FAST["fit"],
                "legacy": [dict(name="main", role="C1-primary", scenarios=["r1_034"], reps=1, options=["a"], basis=4,
                                embedding="shared", center="references")],
                "extra": []}
        self.fx, _ = rec_a_fixture(self.root, spec)
        cp = self.wrap("prepare")
        self.assertEqual(cp.returncode, 0, cp.stderr[-3000:])
        self.witness()
        cp = self.wrap("run", fixture=False)
        self.assertEqual(cp.returncode, 2, cp.stderr[-2000:])
        self.assertIn("P_REC was frozen in fixture mode and this invocation is production mode", cp.stderr)
        mode = os.path.join(self.prec, "inputs", "mode.json")
        self.assertIn("inputs/mode.json", self.frozen())
        self.assertEqual(rqlib.read_json(mode), {"mode": "fixture"})
        fixture_bytes = rqlib.read_bytes(mode)
        production = (json.dumps({"mode": "production"}, sort_keys=True, indent=2) + "\n").encode()
        self.refreeze("inputs/mode.json", production)
        cp = self.wrap("run")
        self.assertEqual(cp.returncode, 2, cp.stderr[-2000:])
        self.assertIn("P_REC was frozen in production mode and this invocation is fixture mode", cp.stderr)
        self.refreeze("inputs/mode.json", fixture_bytes)
        meta = rqlib.read_json(os.path.join(self.prec, "inputs", "graph", "graph.meta.json"))
        self.assertTrue(meta.pop("recovery_toy"))
        self.refreeze("inputs/graph/graph.meta.json", rqlib.canonical(meta))
        cp = self.wrap("run")
        self.assertEqual(cp.returncode, 2, cp.stderr[-2000:])
        self.assertIn("a fixture-frozen root must hold a recovery toy graph", cp.stderr)
        self.assertEqual([n for n in os.listdir(os.path.join(self.prec, "runs", "main")) if n != "config.json"], [])


if __name__ == "__main__":
    unittest.main()

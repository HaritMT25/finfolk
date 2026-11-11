#!/usr/bin/env python3
"""Recovery extension tests; numpy is required when RQ_REQUIRE_NUMPY=1."""
from __future__ import annotations

import argparse
import copy
import os
import shutil
import subprocess
import sys
import tempfile
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
        ts = (0, 20, 60, 100, 140, 140, 180, 200)
        rqlib.write_json_durable(self.refs, {
            "schema": R.REFS_SCHEMA,
            "namespace": "rq-extra-toy-sentinels",
            "references": {
                f"{guild}:{k}": {
                    "world": f"sentinel-{k % 4}",
                    "frame": 1 if t == 0 else t * 1_000_000,
                }
                for guild in ("RQ", "RP") for k, t in enumerate(ts)
            },
        })
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
        # A copied result under another name is refused.
        shutil.copyfile(
            os.path.join(second, "results", missing),
            os.path.join(first, "results", "stray.json"),
        )
        with self.assertRaisesRegex(SystemExit, "stray"):
            X.summarize(first)

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
        with self.assertRaisesRegex(SystemExit, "changed"):
            X.verified(directory, self.gpath, self.refs)


if __name__ == "__main__":
    unittest.main()

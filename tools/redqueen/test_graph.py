#!/usr/bin/env python3
"""test_graph.py: unit tests of graph.py (the map graph, stdlib) and recovery.py (the recovery
simulation; numpy: skipped without it unless RQ_REQUIRE_NUMPY=1, as in CI).

    python3 -I tools/redqueen/test_graph.py [-v]
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import sys
import tempfile
import unittest
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import graph  # noqa: E402
import rqlib  # noqa: E402

if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
try:
    import numpy as np  # noqa: E402
except ImportError:
    np = None
if np is None and os.environ.get("RQ_REQUIRE_NUMPY"):
    raise SystemExit("RQ_REQUIRE_NUMPY is set, but numpy cannot be imported")
NS = "rq-test-graph"
_G = {}


def full(ns=NS, tm=True):
    """The v4 graph alone (no top-ups): the registered families' checks."""
    if (ns, tm) not in _G:
        _G[(ns, tm)] = graph.build(ns, None, tm, snapshot_topup=0, ab_topup=0, lag_probe=0)
    return _G[(ns, tm)]


class TestGraph(unittest.TestCase):
    def setUp(self):
        self.g = full()
        self.split = self.g["split"]
        self.hold = {(k.rsplit(":", 1)[0], int(k.rsplit(":", 1)[1])): v for k, v in self.g["holdout"].items()}
        self.treat = {w["id"]: w["treatment"] for w in self.g["worlds"]}

    def status(self, n):
        g, w, t = graph.parse(n)
        if w is None:
            return "train"
        return self.split[w] if self.split[w] != "train" else self.hold.get((w, t), "train")

    def test_quotas_unique_deterministic(self):
        self.assertEqual(graph.check_quotas(self.g), [])
        self.assertEqual(len(self.g["edges"]), 237_884)
        self.assertEqual(sum(graph.QUOTAS.values()), 237_884)
        again = graph.build(NS, snapshot_topup=0, ab_topup=0, lag_probe=0)
        self.assertEqual(again["edges"], self.g["edges"])
        default = graph.build()          # the default namespace and the approved top-ups (v4 amendment)
        self.assertEqual(Counter(e[2] for e in default["edges"] if e[2] in graph.TOPUPS),
                         Counter(support_snap=1301, ab_train_c=3877))
        self.assertEqual(len(default["edges"]), 243_062 + 1_872)     # (+ the lag7_probe amendment)
        self.assertEqual(graph.check_quotas(default), [])
        self.check_lag_probe(default)

    def check_lag_probe(self, g):
        """The v4 amendment: +-7M within-world probes from every coarse prey time of the 24 non-intensive
        C worlds; roles by endpoint; the 1/8 long pool; never in the Level-1 fit."""
        lp = [e for e in g["edges"] if e[2] == "lag7_probe"]
        self.assertEqual(len(lp), 24 * 78)
        ws = set()
        for q, p, fam, role, hz in lp:
            _, wq, tq = graph.parse(q)
            _, wp, tp = graph.parse(p)
            self.assertEqual(wq, wp)
            self.assertNotIn(wq, g["intensive"])
            self.assertIn(tq, graph.COARSE)
            self.assertIn(tp - tq, (7, -7))
            self.assertIsNone(hz)
            self.assertIn(role, ("training", "validation", "test"))
            ws.add(wq)
        self.assertEqual(len(ws), 24)
        fit = graph.fitting(g, "v4")
        self.assertFalse(any(e[2] == "lag7_probe" for e in fit))
        self.assertNotEqual(full("rq-test-other")["edges"], self.g["edges"])
        no = full(NS, False)
        self.assertEqual(graph.check_quotas(no), [])
        self.assertEqual(len(no["edges"]), 237_884 - 14_480)

    def test_splits_and_holdouts(self):
        for t, want in (("C", (20, 6, 6)), ("A", (5, 1, 2)), ("B", (5, 1, 2))):
            c = Counter(self.split[w] for w in self.treat if self.treat[w] == t)
            self.assertEqual((c["train"], c["val"], c["test"]), want, t)
        self.assertEqual(len(self.hold), 400)
        per = defaultdict(Counter)
        for (w, t), v in self.hold.items():
            self.assertEqual((self.treat[w], self.split[w]), ("C", "train"))
            self.assertGreater(t, 0)                          # F1 is never held out
            per[w][v] += 1
        self.assertTrue(all(c == Counter({"val": 10, "test": 10}) for c in per.values()))
        res = Counter(t % 5 for (_, t) in self.hold)
        self.assertEqual(set(res.values()), {80})             # residues mod 5 balanced
        self.assertEqual([self.split[w] for w in self.g["fork"]].count("test"), 6)
        self.assertEqual(Counter(self.split[w] for w in self.g["fork"]), Counter({"test": 6, "val": 4, "train": 2}))
        self.assertTrue(set(self.g["intensive"]) <= set(self.g["fork"]))
        self.assertEqual(Counter(self.split[w] for w in self.g["intensive"]), Counter({"test": 4, "val": 2, "train": 2}))

    def test_roles(self):
        order = {"train": 0, "val": 1, "test": 2}
        name = {0: "training", 1: "validation", 2: "test"}
        for q, p, fam, role, hz in self.g["edges"]:
            sq, sp = self.status(q), self.status(p)
            if role == "support":
                self.assertTrue(sq != "train" or sp != "train", (q, p, fam))   # a held-out population's
                self.assertTrue(sq == "train" or sp == "train", (q, p, fam))   # ... with a permitted opponent
            else:
                self.assertEqual(role, name[max(order[sq], order[sp])], (q, p, fam))
            self.assertEqual(hz, graph.HORIZON.get(fam))
        self.assertTrue(all(r == "training" for *_, f, r, _ in self.g["edges"] if f == "train_match"))
        self.assertTrue(all(r == "support" for *_, f, r, _ in self.g["edges"] if f in ("support_c", "support_ab")))

    def test_matchings(self):
        cross = defaultdict(list)
        for q, p, fam, *_ in self.g["edges"]:
            if fam == "cross":
                cross[q].append(p)
        cs = [w for w in self.treat if self.treat[w] == "C"]
        self.assertEqual(len(cross), len(cs) * 201)
        for q, ps in cross.items():
            _, w, t = graph.parse(q)
            ws = [graph.parse(p)[1] for p in ps]
            self.assertEqual(len(set(ws)), 8)
            self.assertNotIn(w, ws)
            self.assertGreaterEqual(sum(graph.parse(p)[2] == t for p in ps), 2)   # two time-matched
        tm_q, tm_p = Counter(), Counter()
        for q, p, fam, *_ in self.g["edges"]:
            if fam == "train_match":
                self.assertEqual((self.status(q), self.status(p)), ("train", "train"))
                self.assertNotEqual(graph.parse(q)[1], graph.parse(p)[1])
                self.assertEqual(self.split[graph.parse(q)[1]], "train")
                tm_q[q] += 1
                tm_p[p] += 1
        self.assertEqual(len(tm_q), 3620)
        self.assertEqual(set(tm_q.values()) | set(tm_p.values()), {4})

    def test_support_and_references(self):
        sup = defaultdict(lambda: [0, 0])
        for q, p, fam, role, _ in self.g["edges"]:
            if role == "support":
                for x, y in ((q, p), (p, q)):
                    if self.status(x) != "train" and graph.parse(x)[1] is not None:
                        sup[x][graph.parse(y)[1] is not None] += 1
        short = 0
        for x, (nref, nopp) in sup.items():
            w = graph.parse(x)[1]
            self.assertEqual(nref, 4, x)
            if self.split[w] != "train":                       # world holdouts: 4 references + 6 opponents
                self.assertGreaterEqual(nopp, 4, x)            # (the four added ones at least)
                short += nopp < 6
            else:                                              # snapshot holdouts: existing matchings only
                self.assertTrue(1 <= nopp <= 6, x)
        self.assertLess(short, 20)                             # (the report counts the shortfall)
        cs = sorted(w for w in self.treat if self.treat[w] == "C")
        sh = self.g["cross_shifts"]["shifts"]
        for i, w in enumerate(cs):
            if self.split[w] != "train":
                for d in (1, -1):
                    self.assertGreaterEqual(sum(self.split[cs[(i + d * s) % 32]] == "train" for s in sh), 4)
        blocks = self.g["ref_subsets"]
        for key in ("predator_refs_of_block", "prey_refs_of_block"):
            use = Counter(k for b in blocks[key].values() for k in b)
            self.assertEqual(sorted(use), list(range(8)))
            self.assertEqual(set(use.values()), {4})

    def test_write_load_report(self):
        tmp = tempfile.mkdtemp()
        try:
            meta = graph.write(self.g, tmp)
            path = os.path.join(tmp, "graph.jsonl.gz")
            g2 = graph.load(path)
            self.assertEqual(g2["edges"], [tuple(e) for e in self.g["edges"]])
            self.assertEqual(meta["edges"], 237_884)
            rep = graph.report(g2)
            self.assertEqual(rep["quota_problems"], [])
            for rule, a in rep["access"].items():
                self.assertEqual(a["components"], 1, rule)
            self.assertLess(rep["access"]["no_new_matchings"]["pairs"], rep["access"]["v4"]["pairs"])
            self.assertGreater(rep["access"]["option_b"]["pairs"], rep["access"]["no_new_matchings"]["pairs"])
            self.assertEqual(rep["horizons"]["long"], 64)
            buf = gzip.decompress(rqlib.read_bytes(path)).replace(b'"training"', b'"support"', 1)
            rqlib.write_durable(path, gzip.compress(buf))
            with self.assertRaisesRegex(graph.GraphError, "does not hash"):
                graph.load(path)
            reg = os.path.join(tmp, "worlds.json")         # a registry's ids, treatments and blocks
            ws = [{"id": f"w{i + 1:02d}", "treatment": t, "block": b} for i, (b, t) in enumerate(
                (b, t) for b in range(1, 9) for t in ("C", "A", "C", "B", "C", "C"))]
            with open(reg, "w") as f:
                json.dump({"worlds": ws}, f)
            gr = graph.build(NS, graph.registry_worlds(reg))
            self.assertEqual(graph.check_quotas(gr), [])
            used = {graph.parse(x)[1] for e in gr["edges"] for x in e[:2]} - {None}
            self.assertEqual(used, {w["id"] for w in ws})
        finally:
            shutil.rmtree(tmp)

    def test_topups(self):
        """The optional top-ups: snapshot holdouts to six training opponents in their support (other
        worlds only), training A/B prey to eight fitting pairs or eight C opponents; the registered
        families are unchanged."""
        base = {(e[0], e[1]): e for e in self.g["edges"]}
        g7 = graph.build(NS, None, True, snapshot_topup=0, ab_topup=0, lag_probe=7)   # the amendment alone
        self.assertEqual([e for e in g7["edges"] if e[2] != "lag7_probe"], self.g["edges"])  # nothing else moves
        self.check_lag_probe(g7)
        for ab_mode in ("fitting", "c"):
            g = graph.build(NS, None, True, snapshot_topup=6, ab_topup=8, ab_topup_mode=ab_mode, lag_probe=0)
            self.assertEqual(graph.check_quotas(g), [])
            new = [e for e in g["edges"] if (e[0], e[1]) not in base]
            self.assertTrue(all(e[2] in graph.TOPUPS for e in new))
            self.assertEqual(len(g["edges"]) - len(new), len(base))
            self.assertTrue(all(base[(e[0], e[1])] == e for e in g["edges"] if (e[0], e[1]) in base))
            opp, fitp, copp = Counter(), Counter(), Counter()
            for q, p, fam, role, _ in g["edges"]:
                if role == "support":
                    for x, y in ((q, p), (p, q)):
                        if graph.parse(y)[1] is not None and (graph.parse(x)[1], graph.parse(x)[2]) in self.hold:
                            opp[x] += 1
                if fam == "support_snap":
                    self.assertEqual(role, "support")
                    self.assertNotEqual(graph.parse(q)[1], graph.parse(p)[1])
                if fam == "ab_train_c":
                    self.assertEqual((role, self.status(p)), ("training", "train"))
                if self.treat.get(graph.parse(q)[1]) in ("A", "B") and self.split[graph.parse(q)[1]] == "train" \
                        and role == "training":
                    fitp[q] += 1
                    copp[q] += graph.parse(p)[1] is not None
            self.assertEqual(len(opp), 800)
            self.assertGreaterEqual(min(opp.values()), 6)
            self.assertEqual(len(fitp), 10 * 201)
            self.assertGreaterEqual(min((fitp if ab_mode == "fitting" else copp).values()), 8)


@unittest.skipIf(np is None, "numpy is not installed (set RQ_PYLIB, or RQ_REQUIRE_NUMPY=1 to require it)")
class TestRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import recovery
        cls.rec = recovery
        cls.D = recovery.Data(full())

    def test_data_sets(self):
        D = self.D
        self.assertGreater(len(D.fit["a"]), len(D.fit["base"]))
        self.assertEqual(len(D.fit["a"]) - len(D.fit["base"]), 14_480)
        self.assertGreater(len(D.fit["b"]), len(D.fit["base"]))
        roles = D.role[D.test_idx]
        self.assertTrue((roles == self.rec.ROLES.index("test")).all())
        self.assertFalse(D.within[D.test_idx].any())
        self.assertTrue(all(D.wsplit[w] == "test" for w in np.unique(D.test_world)))
        self.assertEqual(len(np.unique(D.test_world)), 6)
        self.assertGreater(len(D.val_idx), 0)
        fitset = set(D.fit["b"].tolist())
        self.assertFalse(fitset & set(D.test_idx.tolist()))
        self.assertFalse(fitset & set(D.val_idx.tolist()))

    def test_energy_calibration(self):
        data = self.rec.simulate(self.D, self.rec.SCENARIOS["r1_034"], 11)
        self.assertAlmostEqual(data["energy"], 0.034, delta=0.002)
        self.assertEqual(data["z"].shape, (len(self.D.qi), self.rec.R_REPS))
        # the survival head's data: exposed cells and one predator-free control per prey x replicate
        self.assertEqual((data["s"].shape, data["s0"].shape), ((len(self.D.qi), 6), (self.D.nQ, 6)))
        again = self.rec.simulate(self.D, self.rec.SCENARIOS["r1_034"], 11)
        self.assertTrue(np.array_equal(again["z"], data["z"]) and np.array_equal(again["s0"], data["s0"]))

    def test_noiseless_identification(self):
        data = self.rec.simulate(self.D, self.rec.SCENARIOS["num_r2"], 12)
        out = self.rec.numerical(self.D, data, "a", 2, 60, 12)
        self.assertLess(out["relative"], 0.05, out)                # the graph identifies rank 2
        self.assertEqual(out["underdetermined_targets"], 0)

    def test_procedure(self):
        sc = dict(rank=1, energy=0.10)                       # strong specificity: found
        data = self.rec.simulate(self.D, sc, 13)
        out = self.rec.procedure(self.D, data, "a", 1, [0.1], 20, 13)
        self.assertEqual(out["selected"]["rank"], 1)
        self.assertTrue(out["success"], out)
        self.assertEqual(len(out["per_test_world"]), 6)
        data0 = self.rec.simulate(self.D, self.rec.SCENARIOS["r0"], 14)
        out0 = self.rec.procedure(self.D, data0, "base", 1, [0.5], 15, 14)
        self.assertIn(out0["selected"]["rank"], (0, 1))
        self.assertIsInstance(out0["success"], bool)

    def test_conditioning(self):
        rep = self.rec.conditioning(self.D, 2, "a")
        self.assertIn("prey:world-test", rep)
        self.assertIn("predators:snapshot-val", rep)
        self.assertEqual(rep["prey:world-test"]["singular"], 0)
        self.assertEqual(rep["prey:train"]["n"], 3620 + 2010)     # eligible C training states + A/B training prey

    def test_ab_cap(self):
        data = self.rec.simulate(self.D, self.rec.SCENARIOS["r2_034"], 15)
        m = self.rec.fit(self.D, self.D.fit["a"], data["zbar"], 3, 0.1, False, 5, 0, ab_cap=2)
        self.assertLess(float(np.abs(m["u"][self.D.qab, 2]).max()), 1e-6)
        self.assertGreater(float(np.abs(m["u"][~self.D.qab, 2]).max()), 1e-3)
        self.assertEqual(set(self.D.classes), {"world_test_ab_prey", "world_test_c_prey", "snapshot_test"})
        self.assertGreater(len(self.D.classes["world_test_ab_prey"]), 0)

    def test_helpers(self):
        rng = np.random.default_rng(1)
        mean, lb, per = self.rec.cluster_lb(np.array([1.0, 1.0, 2.0, 2.0]), np.array([0, 0, 1, 1]), rng)
        self.assertEqual((mean, per), (1.5, [1.0, 2.0]))
        self.assertGreaterEqual(lb, 1.0)
        self.assertEqual(self.rec.wilson(0, 0), None)
        lo, hi = self.rec.wilson(16, 20)
        self.assertTrue(lo < 0.8 < hi)


if __name__ == "__main__":
    unittest.main()

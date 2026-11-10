#!/usr/bin/env python3
"""test_graph.py: unit tests of graph.py (the map graph, stdlib) and recovery.py (the recovery
simulation; numpy: skipped without it unless RQ_REQUIRE_NUMPY=1, as in CI).

    python3 -I tools/redqueen/test_graph.py [-v]
"""
from __future__ import annotations

import contextlib
import gzip
import io
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
        for x, (nref, nopp) in sup.items():
            w = graph.parse(x)[1]
            self.assertEqual(nref, 4, x)
            if self.split[w] != "train":                       # world holdouts: 4 references + 2 existing + 4 added
                self.assertGreaterEqual(nopp, 6, x)
            else:                                              # snapshot holdouts: 2..6 from the existing matchings
                self.assertTrue(2 <= nopp <= 6, x)
        # #64 review 2: EVERY held-out C population has >= 2 eligible training opponents in the existing
        # (cross) matchings, after the snapshot masking (the deterministic repair swaps)
        elig = Counter()
        for q, p, fam, *_ in self.g["edges"]:
            if fam == "cross":
                for x, y in ((q, p), (p, q)):
                    if self.status(x) != "train" and self.status(y) == "train":
                        elig[x] += 1
        held = [x for w in self.treat if self.treat[w] == "C" for t in range(201)
                for x in (f"Q:{w}:{t}", f"P:{w}:{t}") if self.status(x) != "train"]
        self.assertEqual([x for x in held if elig[x] < 2], [])
        self.assertGreater(self.g["cross_shifts"]["repair_swaps"], 0)
        cs = sorted(w for w in self.treat if self.treat[w] == "C")
        sh = self.g["cross_shifts"]["shifts"]
        for i, w in enumerate(cs):
            for d in (1, -1):
                if self.split[w] != "train":
                    self.assertGreaterEqual(sum(self.split[cs[(i + d * s) % 32]] == "train" for s in sh), 4)
                self.assertGreaterEqual(sum(self.split[cs[(i + d * s) % 32]] == "train" for s in sh[2:]), 2)
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

    def test_registered_invocations_and_permuted_registry(self):
        """#64 review 5: the registered two-flag command `--snapshot-topup 0 --ab-topup 0` gives the pure v4
        graph (237,884 pairs: the lag probe is part of the top-up switch); P3: a permuted registry gives
        byte-identical artifacts."""
        tmp = tempfile.mkdtemp()
        try:
            d1 = os.path.join(tmp, "pure")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(graph.main(["build", "--out", d1, "--namespace", NS, "--snapshot-topup", "0",
                                             "--ab-topup", "0"]), 0)
            meta = json.loads(rqlib.read_text(os.path.join(d1, "graph.meta.json")))
            self.assertEqual((meta["edges"], meta["lag_probe"]), (237_884, 0))
            self.assertEqual(graph.build(NS, snapshot_topup=6, ab_topup=0)["lag_probe"], graph.LAG_PROBE)
            self.assertEqual(graph.build(NS, snapshot_topup=0, ab_topup=0, lag_probe=7)["lag_probe"], 7)
            ws = graph.synthetic_worlds()
            reg = os.path.join(tmp, "worlds.json")
            regp = os.path.join(tmp, "worlds_perm.json")
            with open(reg, "w") as f:
                json.dump({"worlds": ws}, f)
            with open(regp, "w") as f:
                json.dump({"worlds": list(reversed(ws[::2])) + ws[1::2]}, f)
            outs = []
            for k, r in enumerate((reg, regp)):
                d = os.path.join(tmp, f"g{k}")
                with contextlib.redirect_stderr(err):
                    self.assertEqual(graph.main(["build", "--out", d, "--namespace", NS, "--registry", r,
                                                 "--snapshot-topup", "0", "--ab-topup", "0"]), 0)
                outs.append([rqlib.read_bytes(os.path.join(d, f)) for f in ("graph.meta.json", "graph.jsonl.gz")])
            self.assertEqual(outs[0], outs[1])
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

    def test_crossed_bootstrap(self):
        """#64 review 1: the lower bound resamples BOTH source worlds of every target. Test-world prey
        facing predators of two shared source worlds with opposite effects: a test-world-only cluster
        bootstrap sees no spread, the crossed one does; references are never resampled; deterministic."""
        rec = self.rec
        tw, qw, pw, diff = [], [], [], []
        for t in range(6):
            for k in range(40):
                src = 100 + (k % 2)
                tw.append(t)
                qw.append(t)
                pw.append(src)
                diff.append((1.0 if src == 100 else -0.8) + 0.01 * ((k * 7 + t) % 5 - 2))
        tw, qw, pw, diff = map(np.array, (tw, qw, pw, diff))
        m1, lb1, per1 = rec.cluster_lb(diff, tw, np.random.default_rng(1))
        m2, lb2, per2 = rec.crossed_lb(diff, tw, qw, pw, np.random.default_rng(1))
        self.assertAlmostEqual(m1, m2, places=12)
        self.assertGreater(lb1, 0.05)                       # (the one-world assignment: falsely tight)
        self.assertLess(lb2, 0.0)                           # (the shared predator worlds' spread)
        self.assertEqual(rec.crossed_lb(diff, tw, qw, pw, np.random.default_rng(1))[1], lb2)
        ref = np.full_like(pw, -1)                          # against frozen references: only the prey world
        m3, lb3, _ = rec.crossed_lb(diff, tw, qw, ref, np.random.default_rng(1))
        self.assertGreater(lb3, lb2)

    def test_forward_sets(self):
        """#64 review 4: the forward-time sets (v4 §7.3)."""
        D, F = self.D, self.D.forward
        QT, PT = D.qt[D.qi], D.pt[D.pj]
        qr, pr = D.qref[D.qi], D.pref[D.pj]
        qs = np.where(D.qw[D.qi] >= 0, D.wsplit[np.maximum(D.qw[D.qi], 0)], "ref")
        ps = np.where(D.pw[D.pj] >= 0, D.wsplit[np.maximum(D.pw[D.pj], 0)], "ref")
        f = F["fit"]
        main = f[~qr[f] & ~pr[f]]
        self.assertTrue(len(main) and (QT[main] <= 120).all() and (PT[main] <= 120).all())
        self.assertTrue(((qs[main] == "train") & (ps[main] == "train")).all())
        refs = f[qr[f] ^ pr[f]]
        self.assertTrue(len(refs) and (np.where(qr[refs], QT[refs], PT[refs]) <= 120).all())
        self.assertGreater((np.where(qr[refs], PT[refs], QT[refs]) > 120).sum(), 0)    # future snapshots placed
        self.assertFalse(D.within[f].any())
        v = F["val"]
        self.assertTrue(len(v) and ((QT[v] >= 141) & (QT[v] <= 160) & (PT[v] >= 141) & (PT[v] <= 160)).all())
        ft, it = F["tests"]["forward_transfer"], F["tests"]["intersection"]
        for t in (ft, it):
            self.assertTrue(len(t) and ((QT[t] >= 181) & (PT[t] >= 181)).all())
        self.assertTrue(((qs[ft] == "train") & (ps[ft] == "train")).all())
        self.assertTrue(((qs[it] == "test") | (ps[it] == "test")).all())
        for a_, b_ in ((f, v), (f, ft), (f, it), (v, ft), (v, it), (ft, it)):
            self.assertFalse(set(a_.tolist()) & set(b_.tolist()))

    def test_forward_sets_keep_the_access_rules(self):
        """#64 round 2 (P2): the forward masks keep the graph's roles. Non-support pairs of snapshots held
        out for validation or test never enter the prefix fit, and snapshot-test outcomes never enter the
        validation selection. Both leaks are possible in this graph under the time and world masks alone,
        so the checks are not vacuous."""
        D, F = self.D, self.D.forward
        R = self.rec.ROLES
        QT, PT = D.qt[D.qi], D.pt[D.pj]
        qr, pr = D.qref[D.qi], D.pref[D.pj]
        qs = np.where(D.qw[D.qi] >= 0, D.wsplit[np.maximum(D.qw[D.qi], 0)], "ref")
        ps = np.where(D.pw[D.pj] >= 0, D.wsplit[np.maximum(D.pw[D.pj], 0)], "ref")
        glob, main = ~D.within, ~D.within & ~qr & ~pr
        held = (D.role == R.index("validation")) | (D.role == R.index("test"))
        snap = (D.qheld[D.qi] != "train") | (D.pheld[D.pj] != "train")      # (an endpoint held out)
        w = lambda lo, hi: (QT >= lo) & (QT <= hi) & (PT >= lo) & (PT <= hi)  # noqa: E731
        trainpair = (qs == "train") & (ps == "train")
        leak_fit = main & trainpair & w(0, 120) & held
        self.assertGreater(int((leak_fit & snap).sum()), 0)                  # (snapshot holdouts of training worlds)
        leak_val = main & (qs != "test") & (ps != "test") & w(141, 160) & (D.role == R.index("test"))
        self.assertGreater(int(leak_val.sum()), 0)
        f, v = F["fit"], F["val"]
        self.assertFalse(held[f].any())
        self.assertTrue(np.isin(D.role[f], [R.index("training"), R.index("support")]).all())
        self.assertFalse(set(np.flatnonzero(leak_fit).tolist()) & set(f.tolist()))
        self.assertFalse((D.role[v] == R.index("test")).any())
        self.assertFalse(set(np.flatnonzero(leak_val).tolist()) & set(v.tolist()))
        # the support pairs of a held-out snapshot (its placement) still enter the fit
        self.assertGreater(int(((D.role[f] == R.index("support")) & snap[f]).sum()), 0)
        self.assertTrue(glob[f].all())

    def test_forward_procedure(self):
        data = self.rec.simulate(self.D, dict(rank=1, energy=0.10), 17)
        out = self.rec.forward_procedure(self.D, data, 1, [0.1], 6, 17)
        self.assertEqual(out["procedure"], "forward")
        self.assertIn(out["selected"]["rank"], (0, 1))
        for k in ("forward_transfer", "intersection"):
            self.assertTrue(out[k]["available"], out[k])
            self.assertIn("test_lb", out[k])

    def test_forward_on_noiseless_and_summary_branches(self):
        """#64 round 2 P3s: fwd on a noiseless scenario is recorded unavailable (not a crash); the summary
        of fwd keeps both branches, the forward transfer and the intersection."""
        import argparse as ap_
        tmp = tempfile.mkdtemp()
        try:
            gdir = os.path.join(tmp, "g")
            graph.write(full(), gdir)
            out = os.path.join(tmp, "o")
            base = dict(graph=os.path.join(gdir, "graph.jsonl.gz"), namespace="ns", fitter="minimal", ranks=1,
                        lambdas="0.1", iters=4, ab_cap=-1, set="main", jobs=1)
            self.rec.prepare_run(ap_.Namespace(**base, options="fwd", out=out))     # (the run's config.json)
            nl = next(k for k, s in self.rec.SCENARIOS.items() if s.get("noiseless"))
            for sc, rep in ((nl, 0), ("r1_017", 0), ("r1_017", 1)):
                a = ap_.Namespace(**base, options="fwd", scenario=sc, rep=rep,
                                  out=os.path.join(out, f"{sc}.{rep:03d}.json"))
                self.assertEqual(self.rec.one(a), 0)
            r = rqlib.read_json(os.path.join(out, f"{nl}.000.json"))
            self.assertEqual(r["options"]["fwd"]["available"], False)
            cells = {c["scenario"]: c for c in self.rec.summarize(out)["cells"]}
            self.assertEqual(cells[nl]["available"], False)
            self.assertEqual(set(cells["r1_017"]["branches"]), {"forward_transfer", "intersection"})
            self.assertEqual(cells["r1_017"]["datasets"], 2)
        finally:
            shutil.rmtree(tmp)

    def test_config_manifest(self):
        """#64 review 3: a run is bound to its configuration: a resume of another one, or a summary over two,
        is refused."""
        import argparse as ap_
        tmp = tempfile.mkdtemp()
        try:
            gdir = os.path.join(tmp, "g")
            graph.write(full(), gdir)
            a = ap_.Namespace(graph=os.path.join(gdir, "graph.jsonl.gz"), namespace="ns", fitter="minimal",
                              options="a", ranks=1, lambdas="0.1", iters=5, ab_cap=-1, out=os.path.join(tmp, "o"),
                              set="main", scenarios="r0", reps=0, jobs=1)
            self.assertEqual(self.rec.run(a), 0)                  # (no datasets: the manifest only)
            self.assertTrue(os.path.isfile(os.path.join(a.out, "config.json")))
            b = ap_.Namespace(**dict(vars(a), iters=6))
            with self.assertRaisesRegex(SystemExit, "another configuration"):
                self.rec.run(b)
            for k, c in enumerate(("x" * 64, "y" * 64)):
                with open(os.path.join(a.out, f"r0.{k:03d}.json"), "w") as f:
                    json.dump({"scenario": "r0", "options": {}, "config_sha256": c}, f)
            with self.assertRaisesRegex(SystemExit, "mixed summary"):
                self.rec.summarize(a.out)
        finally:
            shutil.rmtree(tmp)

    def test_energy_calibration(self):
        data = self.rec.simulate(self.D, self.rec.SCENARIOS["r1_034"], 11)
        self.assertAlmostEqual(data["energy"], 0.034, delta=0.002)
        self.assertEqual(data["z"].shape, (len(self.D.qi), self.rec.R_REPS))
        # the survival head's data: exposed cells and one predator-free control per prey x replicate
        self.assertEqual((data["s"].shape, data["s0"].shape), ((len(self.D.qi), 6), (self.D.nQ, 6)))
        again = self.rec.simulate(self.D, self.rec.SCENARIOS["r1_034"], 11)
        self.assertTrue(np.array_equal(again["z"], data["z"]) and np.array_equal(again["s0"], data["s0"]))

    def test_capture_noise(self):
        """The measured 5k noise model: the per-replicate logit SD (binomial included) follows the capture
        level: about 0.6 below C/B 0.25, 0.15 above 0.45; x1.5 in _cap15; the flat scenarios unchanged."""
        for name, k in (("r0_cap", 1.0), ("r0_cap15", 1.5)):
            data = self.rec.simulate(self.D, self.rec.SCENARIOS[name], 31)
            p = 1.0 / (1.0 + np.exp(-data["eta"]))
            sd2 = data["z"].var(axis=1, ddof=1)
            lo, hi = (p > 0.18) & (p < 0.25), p > 0.47
            self.assertGreater(lo.sum(), 500)
            self.assertGreater(hi.sum(), 500)
            self.assertAlmostEqual(float(np.sqrt(sd2[lo].mean())), 0.6 * k, delta=0.1 * k)
            self.assertAlmostEqual(float(np.sqrt(sd2[hi].mean())), 0.15 * k, delta=0.05 * k)
        a = self.rec.simulate(self.D, self.rec.SCENARIOS["r0"], 31)
        self.assertEqual(self.rec.SCENARIOS["r0"].get("noise_model", "flat"), "flat")
        self.assertTrue(np.array_equal(a["z"], self.rec.simulate(self.D, dict(rank=0, noise_model="flat"), 31)["z"]))

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


@unittest.skipIf(np is None, "numpy is not installed (set RQ_PYLIB, or RQ_REQUIRE_NUMPY=1 to require it)")
class TestRecoveryRuns(unittest.TestCase):
    """#66 Codex r1 P2-7..9: each fitter's registered command-line defaults (incompatible choices refused
    before any worker starts), the configuration's binding of the graph metadata and every computational
    source, and the identity of every kept result on resume and in the summary."""

    @classmethod
    def setUpClass(cls):
        import recovery
        cls.rec = recovery
        cls.tmp = tempfile.mkdtemp()
        cls.gdir = os.path.join(cls.tmp, "g")
        graph.write(full(), cls.gdir)
        cls.gpath = os.path.join(cls.gdir, "graph.jsonl.gz")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def ns(self, **kw):
        import argparse as ap_
        base = dict(graph=self.gpath, namespace="ns", fitter="minimal", options=None, ranks=1, lambdas=None,
                    iters=None, ab_cap=-1, start=None, basis=None, embedding=None, center=None, set="main",
                    scenarios="r0", reps=0, jobs=1)
        base.update(kw)
        return ap_.Namespace(**base)

    def test_fitter_defaults_and_refusals(self):
        R = self.rec
        a = R.resolve(self.ns(fitter="registered"))
        self.assertEqual((a.options, a.lambdas, a.iters, a.start, a.basis, a.embedding, a.center),
                         ("a", "0.01,0.02,0.05,0.2", 30, "both", 6, "shared", "references"))
        self.assertEqual(tuple(float(x) for x in a.lambdas.split(",")), R.REGISTERED_LAMBDAS)
        m = R.resolve(self.ns())
        self.assertEqual((m.options, m.lambdas, m.iters), ("a,b,base", "0.02,0.1,0.5", 40))
        for bad in (dict(options="a,b"), dict(ab_cap=1), dict(lambdas="0,0.1"), dict(options="a,z"),
                    dict(options="a,a"), dict(basis=5)):
            with self.assertRaises(SystemExit, msg=bad):
                R.resolve(self.ns(fitter="registered", **bad))
        for bad in (dict(start="cold"), dict(basis=8), dict(embedding="separate"), dict(center="train_c")):
            with self.assertRaises(SystemExit, msg=bad):
                R.resolve(self.ns(**bad))
        # refused BEFORE any worker or file: the run directory stays empty
        out = os.path.join(self.tmp, "refused")
        with self.assertRaisesRegex(SystemExit, "option .b."):
            R.run(self.ns(fitter="registered", options="a,b", out=out))
        self.assertFalse(os.path.exists(out))
        with self.assertRaisesRegex(SystemExit, "option .b."):
            R.main(["run", "--graph", self.gpath, "--out", out, "--fitter", "registered", "--options", "a,b",
                    "--scenarios", "r0", "--reps", "1"])
        self.assertFalse(os.path.exists(out))
        # the command line's defaults are the fitter's (no datasets: the configuration only)
        out = os.path.join(self.tmp, "cli")
        self.assertEqual(R.main(["run", "--graph", self.gpath, "--out", out, "--fitter", "registered",
                                 "--scenarios", "r0", "--reps", "0"]), 0)
        cfg = rqlib.read_json(os.path.join(out, "config.json"))
        self.assertEqual((cfg["options"], cfg["lambdas"], cfg["iters"], cfg["start"]),
                         ("a", "0.01,0.02,0.05,0.2", 30, "both"))

    def test_config_binds_graph_metadata_and_sources(self):
        """P2-8: a change of the graph metadata alone (the edges unchanged) is another configuration; rqlib
        (the seed derivation) and noisebank (the count density's numerics) are bound sources."""
        R = self.rec
        tmp = tempfile.mkdtemp()
        try:
            gdir = os.path.join(tmp, "g")
            shutil.copytree(self.gdir, gdir)
            a = self.ns(graph=os.path.join(gdir, "graph.jsonl.gz"), out=os.path.join(tmp, "o"))
            R.prepare_run(a)
            cfg = rqlib.read_json(os.path.join(a.out, "config.json"))
            self.assertTrue({"rqlib.py", "noisebank.py", "map.py", "recovery.py", "graph.py"} <= set(cfg["tools_sha256"]))
            self.assertEqual(set(cfg["graph"]), {"edges_sha256", "meta_sha256"})
            mp = os.path.join(gdir, "graph.meta.json")
            meta = rqlib.read_json(mp)
            w = next(w for w in meta["worlds"] if w["treatment"] == "A")
            w["treatment"] = "B"                       # (a world treatment changed; the edges are the same)
            rqlib.write_durable(mp, rqlib.canonical(meta))
            self.assertEqual(R.graph_meta(a.graph)["edges_sha256"], cfg["graph"]["edges_sha256"])
            with self.assertRaisesRegex(SystemExit, "another configuration"):
                R.prepare_run(self.ns(graph=a.graph, out=a.out))
        finally:
            shutil.rmtree(tmp)

    def test_result_identity_on_resume_and_summary(self):
        """P2-9: a result copied under another name, one with a wrong seed, or a stray file is refused by the
        resume and the summary; a clean directory summarizes."""
        R = self.rec
        out = os.path.join(self.tmp, "ident")
        a = self.ns(options="a", lambdas="0.1", iters=3, out=out)
        R.prepare_run(a)
        f0 = os.path.join(out, "r0.000.json")
        self.assertEqual(R.one(self.ns(options="a", lambdas="0.1", iters=3, scenario="r0", rep=0, out=f0)), 0)
        self.assertEqual(R.summarize(out)["datasets"], 1)
        good = rqlib.read_bytes(f0)
        f1 = os.path.join(out, "r0.001.json")
        shutil.copy(f0, f1)                             # (a copy under another name: n would be inflated)
        for fn in (lambda: R.summarize(out), lambda: R.prepare_run(self.ns(options="a", lambdas="0.1", iters=3,
                                                                           out=out))):
            with self.assertRaisesRegex(SystemExit, "does not match its file name"):
                fn()
        os.remove(f1)
        r = json.loads(good)
        r["seed"] += 1
        rqlib.write_durable(f0, rqlib.canonical(r))
        with self.assertRaisesRegex(SystemExit, "derived seed"):
            R.summarize(out)
        rqlib.write_durable(f0, good)
        with open(os.path.join(out, "notes.json"), "w") as f:
            json.dump({}, f)
        with self.assertRaisesRegex(SystemExit, "not a recovery result"):
            R.summarize(out)
        os.remove(os.path.join(out, "notes.json"))
        cell = R.summarize(out)["cells"][0]
        self.assertIn("median_test_lb", cell)
        self.assertIn("selected_start", cell)
        self.assertEqual(cell["decision_unavailable"], 0)
        os.remove(os.path.join(out, "config.json"))
        with self.assertRaisesRegex(SystemExit, "no config.json"):
            R.summarize(out)


@unittest.skipIf(np is None, "numpy is not installed (set RQ_PYLIB, or RQ_REQUIRE_NUMPY=1 to require it)")
class TestMap(unittest.TestCase):
    """map.py, the registered map (item 7): the QP and its status, the monotone surface and its extension, the
    monotone-spline link, the count density, control access, reference centring, the SVD warm start, the
    joint fit (its rank-0 false-positive regression), the survival posterior, stage 2 for both heads, the
    sensitivities, and start selection against an independently recomputed objective."""

    @classmethod
    def setUpClass(cls):
        import map as mapfit
        import recovery
        cls.M, cls.rec = mapfit, recovery
        cls.D = recovery.Data(full())
        cls.cap = recovery.simulate(cls.D, recovery.SCENARIOS["r1_017_cap"], 41)
        cls.vf = staticmethod(recovery.var_model(cls.cap["settings"]))

    def test_monotone_qp(self):
        M = self.M
        A, c = np.eye(2), np.array([2.0, 1.0])
        C = np.array([[-1.0, 1.0]])                                # x1 >= x0
        x, st = M.monotone_qp(A, c, C, np.zeros(2))
        self.assertTrue(np.allclose(x, [1.5, 1.5]), x)            # the isotonic projection
        self.assertTrue(st["converged"] and st["stationarity"] < 1e-12 and st["min_multiplier"] >= 0, st)
        x, st = M.monotone_qp(A, np.array([1.0, 2.0]), C, np.zeros(2))
        self.assertTrue(np.allclose(x, [1.0, 2.0]) and st["converged"], x)    # feasible: unconstrained
        x, st = M.monotone_qp(A, c, C, np.array([0.0, 1.0]), d=np.array([1.0]))   # x1 - x0 >= 1
        self.assertTrue(np.allclose(x, [1.0, 2.0]) and st["converged"] and st["violation"] < 1e-12, x)
        x, st = M.monotone_qp(A, c, C, np.zeros(2), iters=1)      # (P3: the cap is reported, never silent)
        self.assertFalse(st["converged"])
        self.assertEqual(st["iterations"], 1)
        self.assertEqual(M.qp_summary([st, None])["unconverged"], 1)

    def test_surface_monotone(self):
        M = self.M
        rng = np.random.default_rng(3)
        a, b = rng.normal(size=4000), rng.normal(size=4000)
        y = np.tanh(a) - 0.5 * b + rng.normal(0, 0.3, 4000)         # nondecreasing in a, nonincreasing in b
        y[:200] = -y[:200]                                           # some contrary data
        for k in M.BASES:
            s = M.Surface(M._knots(a, k), M._knots(b, k), ("inc", "dec"))
            s.fit(a, b, y, np.ones(4000))
            self.assertTrue(s.status["converged"], s.status)
            self.assertGreaterEqual(float((M.surface_mats(k, ("inc", "dec"))[0] @ s.theta.ravel()).min()), -1e-9)
            grid = np.linspace(-6, 6, 49)                            # (well beyond the knots)
            va = s.value(grid, np.zeros(49))
            vb = s.value(np.zeros(49), grid)
            self.assertTrue((np.diff(va) >= -1e-9).all() and (np.diff(vb) <= 1e-9).all())
        with self.assertRaises(ValueError):
            M.Surface(np.arange(5.0), np.arange(5.0), ("inc", "dec"))

    def test_surface_extension_preserves_monotonicity(self):
        """P2-5: the review's terminal tile [[0, -2], [1, -1.9]] (both coefficient orders hold): bilinear
        extrapolation at prey-axis fraction 2 gives a predator-axis slope of -0.8; the registered extension
        keeps every slope's sign on a grid far outside the knots, is continuous at the box, and a fit with
        rows beyond the box reproduces a linear truth exactly (the extension's design rows)."""
        M = self.M
        kn = np.linspace(-1.0, 1.0, 4)
        s = M.Surface(kn, kn, ("inc", "dec"))
        s.theta = np.array([[0.0, -1.0, -2.5, -4.0], [0.2, -0.5, -1.0, -3.0], [0.5, 0.2, 0.0, -2.0],
                            [2.0, 1.5, 1.0, -1.9]])
        self.assertGreaterEqual(float((s.C @ s.theta.ravel()).min()), 0.0)
        t00, t10, t01, t11 = 0.0, 1.0, -2.0, -1.9                   # (the corner tile; tb = 2: the old rule)
        self.assertAlmostEqual((t10 - t00) * (1 - 2) + (t11 - t01) * 2, -0.8)
        g = np.linspace(-6.0, 6.0, 121)
        A_, B_ = np.meshgrid(g, g, indexing="ij")
        F = s.value(A_.ravel(), B_.ravel()).reshape(A_.shape)
        self.assertGreaterEqual(float(np.diff(F, axis=0).min()), -1e-12)    # nondecreasing in a everywhere
        self.assertLessEqual(float(np.diff(F, axis=1).max()), 1e-12)        # nonincreasing in b everywhere
        _, fa, fb = s.value(A_.ravel(), B_.ravel(), grads=True)
        self.assertTrue((fa >= -1e-12).all() and (fb <= 1e-12).all())
        a0 = np.full(9, 0.5)
        bs = np.linspace(-0.5, 0.5, 9)
        for e in (1e-9, -1e-9):                                       # continuous at the box's edges
            self.assertTrue(np.allclose(s.value(kn[-1] + abs(e) * np.sign(e) + 0 * bs, bs),
                                        s.value(np.full(9, kn[-1]), bs), atol=1e-8))
            self.assertTrue(np.allclose(s.value(a0, kn[0] + e + 0 * bs), s.value(a0, np.full(9, kn[0])), atol=1e-8))
        rng = np.random.default_rng(9)
        a, b = rng.normal(0, 2, 3000), rng.normal(0, 2, 3000)
        kn6 = np.linspace(-1.5, 1.5, 6)                              # (uniform: a plane has no 2nd differences)
        s2 = M.Surface(kn6, kn6, ("inc", "dec"))
        y = 2.0 * a - b
        self.assertGreater(int(((np.abs(a) > 1.6) | (np.abs(b) > 1.6)).sum()), 500)
        s2.fit(a, b, y, np.ones(3000))
        self.assertLess(float(np.max(np.abs(s2.value(a, b) - y))), 1e-5)
        self.assertTrue(np.allclose(s2.side_slopes(), (2.0, 2.0, -1.0, -1.0), atol=1e-6))

    def test_link_spline(self):
        """P1-2: the registered monotone-spline link: the identity at the start; fitted, it is strictly
        increasing everywhere (the minimum slope, the linear end extension), pinned at the end knots, bounded
        by the grid's asymptotes, and fits a bounded nonlogistic truth better than the logistic family alone;
        dG is G's derivative."""
        M = self.M
        rng = np.random.default_rng(7)
        base = rng.normal(0.0, 1.2, 20000)
        lk0 = M.Link()
        self.assertTrue(lk0.identity() and np.array_equal(lk0.G(base), base))
        w = np.ones(len(base))
        same = M.update_link(M.Link(), base, base.copy(), w)         # (an identity truth stays the identity)
        self.assertEqual((same.lo, same.hi), (0.0, 1.0))
        self.assertLess(float(np.max(np.abs(same.G(base) - base))), 1e-6)
        p = 0.03 + 0.77 / (1.0 + np.exp(-(base + 0.6 * np.tanh(2.0 * base))))
        z = np.log(p / (1 - p)) + rng.normal(0.0, 0.05, len(base))
        lk = M.update_link(M.update_link(M.Link(), base, z, w), base, z, w)
        self.assertEqual(len(lk.knots), M.K)
        self.assertEqual((lk.theta[0], lk.theta[-1]), (lk.knots[0], lk.knots[-1]))
        self.assertTrue((np.diff(lk.theta) >= M.LINK_MIN_SLOPE * np.diff(lk.knots) - 1e-9).all())
        self.assertTrue(lk.status["converged"])
        self.assertLess(lk.hi, 1.0)
        g = np.linspace(-10.0, 10.0, 4001)
        self.assertTrue((np.diff(lk.G(g)) > 0).all() and (lk.dG(g) > 0).all())
        lo_g, hi_g = M.Link(None, None, lk.lo, lk.hi).G(np.array([-50.0, 50.0]))
        self.assertTrue(lo_g < lk.G(g).min() and lk.G(g).max() < hi_g)
        sse = float(np.sum((z - lk.G(base)) ** 2))
        logistic = min(float(np.sum((z - M.Link(None, None, lo, hi).G(base)) ** 2)) for lo in M.LINK_LO for hi in M.LINK_HI)
        self.assertLess(sse, 0.8 * logistic)
        x = np.linspace(-3, 3, 301)
        x = x[np.min(np.abs(x[:, None] - lk.knots[None, :]), axis=1) > 1e-3]
        fd = (lk.G(x + 1e-6) - lk.G(x - 1e-6)) / 2e-6
        self.assertTrue(np.allclose(fd, lk.dG(x), rtol=1e-5, atol=1e-7))

    def test_count_lpd(self):
        """P1-3: the registered capture-count density (Annex H.9.2's rounded logit-normal): normalized over
        0..B in every regime, equal to a direct erfc computation, a mean over replicates, counts checked."""
        import math as m_
        M, N = self.M, self.rec.B_COUNT
        k = np.arange(N + 1)[:, None]
        for loc, var in ((-1.0, 0.36), (0.3, 0.0225), (-4.5, 0.5), (3.0, 0.1), (0.0, 1e-4)):
            lp = M.count_lpd(k, N, np.full(N + 1, loc), np.full(N + 1, var))
            self.assertAlmostEqual(float(np.exp(lp).sum()), 1.0, places=9)

        def ref(kk, loc, sd):
            Phi = lambda x: 0.5 * m_.erfc(-x / m_.sqrt(2.0))           # noqa: E731
            lo = -m_.inf if kk == 0 else m_.log((kk - 0.5) / (N - kk + 0.5))
            hi = m_.inf if kk == N else m_.log((kk + 0.5) / (N - kk - 0.5))
            if lo > loc:                                               # (the upper tail, by the upper tails)
                return m_.log(0.5 * m_.erfc((lo - loc) / sd / m_.sqrt(2)) - 0.5 * m_.erfc((hi - loc) / sd / m_.sqrt(2)))
            return m_.log(Phi((hi - loc) / sd) - Phi((lo - loc) / sd))
        for kk in (0, 3, 40, 87, 150, 300, 324):
            got = float(M.count_lpd(np.array([[kk]]), N, np.array([-1.0]), np.array([0.36]))[0])
            self.assertAlmostEqual(got, ref(kk, -1.0, 0.6), places=7)
        cnt = np.array([[10, 12, 9], [100, 90, 95]])
        lp = M.count_lpd(cnt, N, np.array([-3.4, -0.8]), np.array([0.2, 0.05]))
        one = [float(M.count_lpd(cnt[i][:, None], N, np.full(3, [-3.4, -0.8][i]), np.full(3, [0.2, 0.05][i])).mean())
               for i in range(2)]
        self.assertTrue(np.allclose(lp, one))
        for bad in (np.array([[N + 1]]), np.array([[-1]]), np.array([3])):
            with self.assertRaises(ValueError):
                M.count_lpd(bad, N, np.zeros(1), np.ones(1))

    def test_control_access_and_invariance(self):
        """P1-1: the controls a fit may read: none of a held-out snapshot's, none past the forward fit's 120M
        (the late references included); perturbing every excluded control, and every outcome outside the
        forward fit's pairs, leaves the fit bit-identical, while an accessible control moves it."""
        D, M, rec = self.D, self.M, self.rec
        prim = M.control_access(D, D.fit["a"])
        self.assertFalse(prim[D.qheld != "train"].any())
        self.assertTrue(prim[(D.qheld == "train") & (np.bincount(D.qi[D.fit["a"]], minlength=D.nQ) > 0)].any())
        idx = D.forward["fit"]
        ctrl = M.control_access(D, idx, rec.FORWARD_TMAX)
        self.assertFalse(ctrl[D.qt > rec.FORWARD_TMAX].any())
        late_ref = D.qref & (D.qt > rec.FORWARD_TMAX)
        self.assertTrue(late_ref.any() and ctrl.any())
        data = self.cap
        rng = np.random.default_rng(2)
        bad = dict(data)
        s0 = data["s0"].copy()
        s0[~ctrl] += rng.normal(0.0, 3.0, s0[~ctrl].shape)
        bad["s0"], bad["s0bar"] = s0, s0.mean(axis=1)
        out = np.ones(len(D.qi), bool)
        out[idx] = False                              # (and every outcome outside the forward fit's pairs)
        for key, bar in (("z", "zbar"), ("s", "sbar")):
            x = data[key].copy()
            x[out] += rng.normal(0.0, 2.0, x[out].shape)
            bad[key], bad[bar] = x, x.mean(axis=1)
        fits = [M.fit(D, idx, d_, 1, 0.05, False, 6, 1, var_fn=self.vf, ctrl=ctrl) for d_ in (data, bad)]
        self.assertEqual(fits[0]["objective"], fits[1]["objective"])
        for k in ("a", "b", "aS", "bS", "u", "v", "c", "DS", "covQ", "covP"):
            self.assertTrue(np.array_equal(fits[0][k], fits[1][k]), k)
        self.assertEqual(fits[0]["controls"]["accessible"], int(ctrl.sum()))
        moved = dict(data)
        s0 = data["s0"].copy()
        s0[ctrl] += 0.5                               # (non-vacuous: an accessible control moves it)
        moved["s0"], moved["s0bar"] = s0, s0.mean(axis=1)
        self.assertNotEqual(M.fit(D, idx, moved, 1, 0.05, False, 6, 1, var_fn=self.vf, ctrl=ctrl)["objective"],
                            fits[0]["objective"])

    def test_reference_centring(self):
        """P2-4: E_muQ[u] = 0 and E_muP[v] = 0 over the eight references hold for the FITTED embedding (both
        starts, the separate embedding); the forward fit centres on the early references it places; the
        second distribution centres on the training-C snapshots; the ladder against the references is the
        ordered part."""
        D, M, rec = self.D, self.M, self.rec
        data = rec.simulate(D, rec.SCENARIOS["r2_034"], 61)
        refq, refp = np.flatnonzero(D.qref), np.flatnonzero(D.pref)
        self.assertEqual((len(refq), len(refp)), (8, 8))
        for kw in (dict(), dict(start="cold"), dict(embedding="separate")):
            m = M.fit(D, D.fit["a"], data, 2, 0.05, False, 6, 1, **kw)
            self.assertEqual(m["center"], {"distribution": "references", "prey": 8, "pred": 8})
            embs = [("u", refq), ("v", refp)] + ([("uS", refq), ("vS", refp)] if kw.get("embedding") else [])
            for key, S in embs:
                self.assertLess(float(np.abs(m[key][S].mean(axis=0)).max()), 1e-10, (kw, key))
                self.assertGreater(float(np.abs(m[key][S]).max()), 1e-3)          # (not trivially zero)
        L = M.ladder(D, m, "prey")
        self.assertEqual(L["opponents"], 8)
        i = np.flatnonzero(np.bincount(D.qi[D.fit["a"]], minlength=D.nQ) > 0)[:5]
        for x in i:
            self.assertAlmostEqual(L["eta"][x], float(m["surfC"].value(m["a"][refp], np.full(8, m["b"][x])).mean()))
        F = D.forward
        mf = M.fit(D, F["fit"], data, 1, 0.05, False, 4, 1, ctrl=M.control_access(D, F["fit"], rec.FORWARD_TMAX))
        early = np.flatnonzero(D.qref & (D.qt <= rec.FORWARD_TMAX))
        self.assertEqual(mf["center"]["prey"], len(early))
        self.assertTrue(0 < len(early) < 8)
        self.assertLess(float(np.abs(mf["u"][early].mean(axis=0)).max()), 1e-10)
        mt = M.fit(D, D.fit["a"], data, 1, 0.05, False, 4, 1, center="train_c")
        self.assertGreater(mt["center"]["prey"], 8)
        self.assertLess(float(np.abs(mt["u"][mt["center_nodes"]["prey"]].mean(axis=0)).max()), 1e-10)
        with self.assertRaises(ValueError):
            M.fit(D, D.fit["a"], data, 1, 0.05, False, 1, 1, center="x")

    def test_svd_warm_start(self):
        M = self.M
        rng = np.random.default_rng(1)
        nQ, nP = 60, 50
        U0, V0 = rng.normal(size=(nQ, 2)), rng.normal(size=(nP, 2))
        mask = rng.random((nQ, nP)) < 0.3
        mask[7, :] = False                                           # a prey node without fitting pairs
        qi, pj = np.nonzero(mask)
        val = (U0 @ V0.T)[qi, pj]
        U, s, V = M.top_singular(qi, pj, val, nQ, nP, 2, seed=0, iters=30)
        Z = np.zeros((nQ, nP))
        Z[qi, pj] = val
        self.assertTrue(np.allclose(s, np.linalg.svd(Z, compute_uv=False)[:2], rtol=1e-6))
        u, v = M.svd_start(qi, pj, val, nQ, nP, 2, seed=0)
        self.assertEqual((u.shape, v.shape), ((nQ, 2), (nP, 2)))
        self.assertEqual(float(np.abs(u[7]).max()), 0.0)
        self.assertGreater(float(np.corrcoef((u[qi] * v[pj]).sum(axis=1), val)[0, 1]), 0.6)

    def test_fit_smoke_and_rank0_regression(self):
        """Both starts run and keep the surfaces monotone; on a noisy rank-0 two-way truth the joint
        fit does not prefer rank 1 under the registered count score (the false positive that head-specific
        survival qualities fixed)."""
        D, M, rec = self.D, self.M, self.rec
        idx = D.fit["a"]
        data = rec.simulate(D, rec.SCENARIOS["r0_twoway"], 101)
        with self.assertRaisesRegex(ValueError, "warm or cold"):
            M.fit(D, idx, data, 1, 0.1, False, 1, 1, start="hot")
        scores = {}
        for rank, start in ((0, "warm"), (1, "warm"), (1, "cold")):
            m = M.fit(D, idx, data, rank, 0.1, False, 30, 1, start=start)
            for surf, key in ((m["surfC"], ("inc", "dec")), (m["surfS"], ("dec", "inc"))):
                self.assertGreaterEqual(float((M.CONS[key] @ surf.theta.ravel()).min()), -1e-9)
            self.assertEqual(m["qp"]["unconverged"], 0)
            p = M.predict(D, m, idx)
            self.assertTrue(np.isfinite(p).all())
            c, g = rec.scorer(D, data, m, idx, "registered")(D.val_idx)
            self.assertTrue(np.isfinite(c).all() and np.isfinite(g).all())
            scores[(rank, start)] = rec.world_mean(c, D.val_world)[0]
        self.assertGreaterEqual(scores[(0, "warm")], scores[(1, "warm")], scores)
        self.assertGreaterEqual(scores[(0, "warm")], scores[(1, "cold")], scores)

    def test_survival_posterior(self):
        """P2-6: q_ij = E[sigma(c_i + eta^S) - sigma(c_i) | data] under the joint covariance: the 2-D
        quadrature matches Monte Carlo, reduces to the plug-in without uncertainty, the c_i covariance with
        the exposed logit is positive and shrinks the SD below the independent-error SD, and a prey without
        accessible controls has a wider c_i."""
        D, M = self.D, self.M
        m = M.fit(D, D.fit["a"], self.cap, 1, 0.05, False, 8, 1, var_fn=self.vf)
        t = D.test_idx[:4000]
        sp = M.survival_posterior(D, m, t)
        self.assertTrue(np.array_equal(M.survival_penalty(D, m, t), sp["q"]))
        self.assertTrue((sp["q_sd"] > 0).all() and (sp["var0"] > 0).all())
        self.assertGreater(float(np.abs(sp["cov01"]).min()), 0.0)                # (c_i enters both logits)
        self.assertTrue((sp["var0"] * sp["var1"] - sp["cov01"] ** 2 >= -1e-12).all())   # (a joint covariance)
        _, sd_ind = M._gh2(sp["logit0"], sp["logit1"], sp["var0"], np.zeros(len(t)), sp["var1"])
        self.assertGreater(float(np.max(np.abs(sp["q_sd"] - sd_ind))), 1e-4)     # (never independent bars)
        q0, sd0 = M._gh2(sp["logit0"], sp["logit1"], 0 * sp["var0"], 0 * sp["var0"], 0 * sp["var0"])
        self.assertTrue(np.allclose(q0, sp["q_plugin"]) and np.allclose(sd0, 0.0))
        rng = np.random.default_rng(4)
        mu, V = np.array([1.2, 0.4]), np.array([[0.3, 0.2], [0.2, 0.5]])
        x = rng.multivariate_normal(mu, V, 400000)
        sg = lambda y: 1 / (1 + np.exp(-y))                           # noqa: E731
        q, sd = M._gh2(mu[:1], mu[1:], V[:1, 0], V[:1, 1], V[1:, 1])
        mc = sg(x[:, 1]) - sg(x[:, 0])
        self.assertAlmostEqual(float(q[0]), float(mc.mean()), delta=2e-3)
        self.assertAlmostEqual(float(sd[0]), float(mc.std()), delta=2e-3)
        ctrl = M.control_access(D, D.fit["a"])
        qi = D.qi[t]
        self.assertGreater(float(np.median(m["covQ"][~ctrl, 0, 0])), 2 * float(np.median(m["covQ"][ctrl, 0, 0])))
        self.assertTrue((~ctrl[qi]).any())

    def test_own_world_stage2(self):
        """q30b: option (b) is refused inside the Level-1 fit; the cross-fitted stage-2 layer recovers a
        strong own-world lag effect on the within-world pairs out of fold (Level 1 untouched), for the
        capture head and (P2-6) the survival head; a world the layer never saw integrates its deviation."""
        D, M, rec = self.D, self.M, self.rec
        data = rec.simulate(D, rec.SCENARIOS["r0_ownworld"], 21)
        with self.assertRaisesRegex(ValueError, "option .b. is dropped"):
            M.fit(D, D.fit["a"], data, 0, 0.1, True, 1, 1)
        m = M.fit(D, D.fit["a"], data, 0, 0.1, False, 15, 1)
        idx_w = np.flatnonzero(D.within & (D.role == rec.ROLES.index("training")))
        before = {k: v.copy() for k, v in m.items() if isinstance(v, np.ndarray)}
        own = M.own_world_stage2(D, m, data, idx_w, folds=5)
        self.assertTrue(all(np.array_equal(before[k], m[k]) for k in before))
        truth = data["eta"][idx_w] - M.predict(D, m, idx_w)               # what Level 1 leaves out there
        self.assertGreater(float(np.corrcoef(own["oof"], truth)[0, 1]), 0.5)
        self.assertLess(float(np.mean((truth - own["oof"]) ** 2)), 0.5 * float(np.mean(truth ** 2)))
        self.assertEqual(sorted(np.unique(own["fold"]).tolist()), [0, 1, 2, 3, 4])
        p = M.predict(D, m, idx_w, own=own)
        terms = own["h"][D.lagbin[idx_w]] + own["hw"][D.ownw[idx_w], D.lagbin[idx_w]]
        self.assertTrue(np.allclose(p, m["link"].G(M._eta(D, m, idx_w) + terms)))
        with self.assertRaisesRegex(ValueError, "within-world pairs only"):
            M.own_world_stage2(D, m, data, D.fit["a"][:10])
        lag = (D.pt[D.pj] - D.qt[D.qi])[idx_w]
        eff = -0.5 * np.exp(-np.abs(lag) / 8.0)
        sdat = dict(data)
        s = data["s"].copy()
        s[idx_w] += eff[:, None]                      # (within pairs: outside the Level-1 fit, m unchanged)
        sdat["s"], sdat["sbar"] = s, s.mean(axis=1)
        own_s = M.own_world_stage2(D, m, sdat, idx_w, folds=5, head="survival")
        self.assertGreater(float(np.corrcoef(own_s["oof"], eff)[0, 1]), 0.5)
        ds = M.predict_survival(D, m, idx_w, own=own_s)[1] - M.predict_survival(D, m, idx_w)[1]
        self.assertTrue(np.allclose(ds, own_s["h"][D.lagbin[idx_w]] + own_s["hw"][D.ownw[idx_w], D.lagbin[idx_w]]))
        w0 = D.ownw[idx_w][0]
        part = M.own_world_stage2(D, m, data, idx_w[D.ownw[idx_w] != w0], folds=5)
        ov = M.own_var(D, part, idx_w)
        self.assertTrue(np.all(ov[D.ownw[idx_w] == w0] == part["world_var"]) and np.all(ov[D.ownw[idx_w] != w0] == 0))
        with self.assertRaises(ValueError):
            M.own_world_stage2(D, m, data, idx_w, head="x")

    def test_sensitivities(self):
        """P2-6: the separate-embedding and four- / eight-basis sensitivity fits run with their own
        constraints, bases and embeddings."""
        D, M = self.D, self.M
        idx = D.fit["a"]
        for kw in (dict(embedding="separate"), dict(basis=4), dict(basis=8)):
            m = M.fit(D, idx, self.cap, 1, 0.05, False, 6, 1, var_fn=self.vf, **kw)
            k = kw.get("basis", 6)
            for surf, key in ((m["surfC"], ("inc", "dec")), (m["surfS"], ("dec", "inc"))):
                self.assertEqual(surf.k, k)
                self.assertGreaterEqual(float((M.surface_mats(k, key)[0] @ surf.theta.ravel()).min()), -1e-9)
            self.assertEqual(len(m["link"].knots), k)
            self.assertEqual(m["qp"]["unconverged"], 0)
            if kw.get("embedding"):
                self.assertEqual((m["uS"].shape, m["vS"].shape), ((D.nQ, 1), (D.nP, 1)))
                self.assertFalse(np.abs(m["DS"]).any())
                x0, x1 = M.predict_survival(D, m, idx[:50])
                self.assertTrue(np.allclose(x1 - x0, m["surfS"].value(m["aS"][D.pj[idx[:50]]], m["bS"][D.qi[idx[:50]]])
                                            + (m["uS"][D.qi[idx[:50]]] * m["vS"][D.pj[idx[:50]]]).sum(axis=1)))
                self.assertEqual(M.survival_posterior(D, m, idx[:50])["q"].shape, (50,))
        for bad in (dict(basis=5), dict(embedding="x")):
            with self.assertRaises(ValueError):
                M.fit(D, idx, self.cap, 1, 0.05, False, 1, 1, **bad)

    def objective_of(self, m, data, idx, lam, lam_ab=1e-3):
        """The penalized training objective recomputed from a fit's returned parameters (independently of
        the fitter's own bookkeeping)."""
        D, M = self.D, self.M
        z = data["zbar"][idx]
        g = M.predict(D, m, idx)
        w = 1.0 / np.maximum(self.vf(np.clip(1 / (1 + np.exp(-g)), 1e-4, 1 - 1e-4)), 1e-8)
        obj = float(np.sum(w / w.mean() * (z - g) ** 2))
        nC = m["noise_C"]
        ctrl = M.control_access(D, idx)
        wS = nC / M._noise(data["s"][idx])
        wS0 = nC / M._noise(data["s0"][ctrl])
        wC0 = nC / m["controls"]["prior_var"]
        x0, x1 = M.predict_survival(D, m, idx)
        obj += wS * float(np.sum((data["sbar"][idx] - x1) ** 2))
        obj += wS0 * float(np.sum((data["s0"][ctrl].mean(axis=1) - m["c"][ctrl]) ** 2))
        obj += wC0 * float(np.sum((m["c"] - m["controls"]["cbar"]) ** 2))
        obj += m["surfC"].pen + m["surfS"].pen + m["link"].pen
        obj += lam * float(np.sum(m["u"] ** 2) + np.sum(m["v"] ** 2))
        obj += lam_ab * float(sum(np.sum(m[k] ** 2) for k in ("a", "b", "aS", "bS")))
        return obj

    def test_weights_starts_and_scoring(self):
        """The coordinator's item-7 decisions: capture cells weighted by 1 / V(p) from the registered
        variance function (the generator's in recovery); both starts run, the lower penalized training
        objective kept (never validation), checked against objectives recomputed from the returned
        parameters; the registered predictive variance phi V(p) + pair + posterior variance is
        heteroscedastic; the procedure decides by the count score."""
        D, M, rec = self.D, self.M, self.rec
        idx = D.fit["a"]
        data, vf = self.cap, self.vf
        self.assertAlmostEqual(float(vf(np.array([0.2]))[0]), 0.36)
        self.assertAlmostEqual(float(vf(np.array([0.5]))[0]), 0.0225)
        self.assertIsNone(rec.var_model(dict(rank=2, noiseless=True)))
        flat = rec.var_model(rec.SCENARIOS["r0"])
        self.assertAlmostEqual(float(flat(np.array([0.5]))[0]), 0.15 ** 2 + 0.15 ** 2 + 0.2 ** 2 + 1 / (rec.B_COUNT * 0.25))
        mw = M.fit(D, idx, data, 1, 0.05, False, 10, 1, var_fn=vf)
        mu = M.fit(D, idx, data, 1, 0.05, False, 10, 1)
        self.assertTrue(mw["weighted"] and not mu["weighted"])
        self.assertFalse(np.allclose(M.predict(D, mw, idx), M.predict(D, mu, idx)))
        single = {st: M.fit(D, idx, data, 1, 0.05, False, 10, 1, var_fn=vf, start=st) for st in ("warm", "cold")}
        recomputed = {st: self.objective_of(f, data, idx, 0.05) for st, f in single.items()}
        for st in single:
            self.assertAlmostEqual(recomputed[st], single[st]["objective"], delta=1e-8 * abs(recomputed[st]))
        best = M.fit_best(D, idx, data, 1, 0.05, 10, 1, var_fn=vf)
        want = min(recomputed, key=recomputed.get)
        self.assertEqual(best["start"], want)
        self.assertTrue(np.array_equal(best["u"], single[want]["u"]))
        self.assertEqual(set(M.fit_best(D, idx, data, 0, 0.0, 5, 1)["objectives"]), {"warm"})   # rank 0: one fit
        loc, var = M.pred_var(D, best, D.val_idx)
        self.assertEqual(var.shape, D.val_idx.shape)
        self.assertGreater(float(var.max()) / float(var.min()), 3.0)              # heteroscedastic
        rep = best["phi"] * vf(np.clip(1 / (1 + np.exp(-loc)), 1e-4, 1 - 1e-4))
        self.assertTrue((var >= rep + best["pair_var"] - 1e-12).all())            # (+ the posterior variance)
        self.assertGreater(float((var - rep).max()), 0.0)
        self.assertTrue(np.allclose(loc, M.predict(D, best, D.val_idx)))
        m0 = rec.fit(D, idx, data["zbar"], 0, 0.0, False, 5, 1)
        c0, g0 = rec.scorer(D, data, m0, idx, "minimal")(D.val_idx)
        self.assertTrue(np.isfinite(c0).all() and np.isfinite(g0).all())
        z = data["z"][D.val_idx[:5]]
        pr = M.predict(D, best, D.val_idx[:5])
        self.assertTrue(np.allclose(rec.lpd(z, pr, np.full(5, 0.3)), rec.lpd(z, pr, 0.3)))
        out = rec.procedure(D, data, "a", 1, [0.05], 8, 41, fitter="registered")
        self.assertEqual({c["start"] for c in out["candidates"] if c["rank"]} <= {"warm", "cold"}, True)
        self.assertEqual(out["score"], rec.SCORE)
        self.assertTrue(out["decision"]["available"])
        for c in out["candidates"]:
            self.assertTrue({"val_lpd", "val_lpd_gauss", "test_lb", "test_lb_gauss", "qp"} <= set(c))
            self.assertEqual(c["qp"]["unconverged"], 0)
        best_c = max(out["candidates"], key=lambda c: c["val_lpd"])
        self.assertEqual(out["selected"]["rank"], best_c["rank"])
        self.assertEqual(out["test_lb"], best_c["test_lb"])
        self.assertIn("selected_primary", out)
        self.assertIn("gauss_diagnostic", out)
        self.assertEqual(rec.REGISTERED_LAMBDAS, (0.01, 0.02, 0.05, 0.2))


if __name__ == "__main__":
    unittest.main()

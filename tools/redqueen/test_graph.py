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
        self.assertEqual(len(self.g["edges"]), 266_024)              # (Annex H D7 rule 40's base graph total)
        self.assertEqual(sum(graph.QUOTAS.values()), graph.BASE_TOTAL)
        self.assertEqual(graph.BASE_TOTAL, 266_024)
        self.assertEqual({f: graph.QUOTAS[f] for f in ("ref_ab", "ab_to_c", "support_ab")},
                         {"ref_ab": 25_728, "ab_to_c": 25_728, "support_ab": 4_824})   # (D7 rule 40's table)
        again = graph.build(NS, snapshot_topup=0, ab_topup=0, lag_probe=0)
        self.assertEqual(again["edges"], self.g["edges"])
        default = graph.build()          # the default namespace and the approved top-ups (v4 amendment)
        self.assertEqual(Counter(e[2] for e in default["edges"] if e[2] in graph.TOPUPS),
                         Counter(support_snap=1301, ab_train_c=8116))   # (recomputed on the 64-world graph)
        self.assertEqual(len(default["edges"]), 266_024 + 1_301 + 8_116 + 1_872)   # (+ the lag7_probe amendment)
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
        self.assertEqual(len(no["edges"]), 266_024 - 14_480)

    def test_registered_layout_only(self):
        """Annex H D7 rule 34: 8 blocks of 4C + 2A + 2B (64 worlds); any other layout (the withdrawn 48 / 56
        allocations, a block with three A) is refused."""
        ws = graph.synthetic_worlds()
        self.assertEqual((len(ws), graph.layout_problems(ws)), (64, []))
        self.assertEqual(Counter(w["treatment"] for w in ws), Counter(C=32, A=16, B=16))
        old48 = [w for w in ws if not (w["treatment"] in "AB" and int(w["id"][1:]) % 2 == 0)]
        bad = [dict(w, treatment="A") if w["id"] == "B01" else w for w in ws]
        for lst in (old48, bad, ws[:-8], ws + [dict(ws[0])]):
            with self.assertRaisesRegex(graph.GraphError, "registered 64-world layout"):
                graph.build(NS, lst, snapshot_topup=0, ab_topup=0, lag_probe=0)

    def test_frozen_48_world_graph_reports(self):
        """Codex #77 r1 P2-7: a FROZEN historical 48-world graph (8 x (4C + 1A + 1B), main 99b1e94's; rebuilt here
        bit-identically: its edges_sha256 is main's) is validated against ITS layout's quotas, not the doubled
        64-world ones; build itself still makes the 64-world layout only."""
        ws48 = []
        for b in range(1, 9):                                      # (main's synthetic ids)
            ws48 += [{"id": f"C{4 * (b - 1) + i + 1:02d}", "treatment": "C", "block": b} for i in range(4)]
            ws48 += [{"id": f"A{b}", "treatment": "A", "block": b}, {"id": f"B{b}", "treatment": "B", "block": b}]
        keep = (graph.LAYOUT, graph.SPLIT_SIZES)
        graph.LAYOUT, graph.SPLIT_SIZES = graph.HISTORICAL_LAYOUTS["48"], {"C": (20, 6, 6), "A": (5, 1, 2), "B": (5, 1, 2)}
        try:
            g48 = graph.build(NS, ws48, True, snapshot_topup=0, ab_topup=0, lag_probe=0)
        finally:
            graph.LAYOUT, graph.SPLIT_SIZES = keep
        tmp = tempfile.mkdtemp()
        try:
            meta = graph.write(g48, tmp)
            self.assertEqual((meta["edges_sha256"], meta["edges"]),
                             ("7e9bbf7242568ef3320e1f252db0badcbf89b10430741e447a45395dc7a1a1b8", 237_884))   # (main's)
            g = graph.load(os.path.join(tmp, "graph.jsonl.gz"))
            self.assertEqual((graph.layout_of(g["worlds"]), graph.check_quotas(g)), ("48", []))
            rep = graph.report(g)
            self.assertEqual(rep["quota_problems"], [])
            self.assertNotIn("executable_of", rep)                      # (P3: a scheduled report keeps its bytes)
            c = Counter(e[2] for e in g["edges"])
            self.assertEqual(sorted(f for f, n in graph.QUOTAS.items() if c[f] != n), ["ab_to_c", "ref_ab", "support_ab"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(graph.main(["report", "--graph", os.path.join(tmp, "graph.jsonl.gz")]), 0)
            self.assertEqual(graph.layout_of(g["worlds"][:-1]), None)
            self.assertIn("not a registered layout", graph.check_quotas(dict(g, worlds=g["worlds"][:-1]))[0])
        finally:
            shutil.rmtree(tmp)
        with self.assertRaisesRegex(graph.GraphError, "registered 64-world layout"):
            graph.build(NS, ws48, snapshot_topup=0, ab_topup=0, lag_probe=0)

    def test_splits_and_holdouts(self):
        for t, want in (("C", (20, 6, 6)), ("A", (10, 2, 4)), ("B", (10, 2, 4))):   # (D7 rule 40)
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
            self.assertEqual(meta["edges"], 266_024)
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
                (b, t) for b in range(1, 9) for t in ("C", "A", "C", "B", "C", "B", "A", "C"))]
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
        graph (266,024 pairs: the lag probe is part of the top-up switch); P3: a permuted registry gives
        byte-identical artifacts."""
        tmp = tempfile.mkdtemp()
        try:
            d1 = os.path.join(tmp, "pure")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(graph.main(["build", "--out", d1, "--namespace", NS, "--snapshot-topup", "0",
                                             "--ab-topup", "0"]), 0)
            meta = json.loads(rqlib.read_text(os.path.join(d1, "graph.meta.json")))
            self.assertEqual((meta["edges"], meta["lag_probe"]), (266_024, 0))
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
            self.assertEqual(len(fitp), 20 * 201)                      # (10 training A + 10 training B worlds)
            self.assertGreaterEqual(min((fitp if ab_mode == "fitting" else copp).values()), 8)

    def test_mask_and_executable(self):
        """Annex H D6 rule 27 (PR-C; Codex #77 r1): the immutable scheduled graph and a separate mask from a worlds
        block BOUND to the study's registry: biological at or after the evidenced first guild zero (a zero exactly
        at a snapshot's frame included), pending FIRST for an unsettled burn-in (an evidenced early zero awaiting
        its restart is pending, never biological), technical at or after a refill, for a missing / damaged /
        off-chain archive or not archived in an ended attempt, pending not archived yet in a running one; every
        edge's exclusion is its endpoints' first cause (references never masked); the executable graph keeps every
        role and refuses a mask whose exclusions are not its snapshots'; the scheduled graph is never overwritten."""
        tmp = tempfile.mkdtemp()
        try:
            gdir = os.path.join(tmp, "g")
            graph.write(self.g, gdir)
            gp = os.path.join(gdir, "graph.jsonl.gz")
            g = graph.load(gp)
            reg, rsha = test_registry(g)
            block = masked_block(g, reg, rsha)
            m = graph.mask(g, block, reg, rsha, "b" * 64)
            S, M = m["snapshots"], 1_000_000
            allf = [1] + [t * M for t in range(1, 201)]
            self.assertEqual((S[f"C01:{101 * M}"]["status"], S[f"C01:{101 * M}"]["valid_before"]), ("biological", 100 * M + 5000))
            self.assertNotIn(f"C01:{100 * M}", S)                           # (before the boundary: available)
            self.assertEqual((S[f"C05:{100 * M}"]["status"], f"C05:{99 * M}" in S), ("biological", False))   # (AT it)
            self.assertEqual(S[f"C02:{50 * M}"]["status"], "technical")     # (not archived, the attempt done)
            self.assertEqual(S[f"C04:{60 * M}"]["status"], "technical")     # (its archived object no longer hashes)
            self.assertIn("mismatch", S[f"C04:{60 * M}"]["why"])
            self.assertEqual(S[f"B01:{70 * M}"]["status"], "technical")     # (archived off the line of descent)
            self.assertIn("line of descent", S[f"B01:{70 * M}"]["why"])
            self.assertEqual((S[f"B02:{80 * M}"]["status"], f"B02:{79 * M}" in S), ("technical", False))  # (a refill)
            self.assertEqual(S["C03:1"]["status"], "pending")               # (the burn-in may still replace it)
            self.assertEqual(sum(1 for k in S if k.startswith("C03:")), 201)
            self.assertEqual({S[f"C06:{f}"]["status"] for f in allf}, {"pending"})     # (an early zero: restart due)
            self.assertEqual((S[f"A01:{121 * M}"]["status"], f"A01:{120 * M}" in S), ("pending", False))
            self.assertEqual(m["worlds"]["C01"]["unavailable_snapshots"], {"biological": 100, "technical": 0, "pending": 0})
            self.assertEqual(m["worlds"]["C01"]["first_unavailable_time"], 101)
            av = m["worlds"]["C01"]["available_sha256"]
            self.assertEqual((len(av), av[str(100 * M)]), (101, block["worlds"]["C01"]["archive"][str(100 * M)]["sha256"]))
            self.assertEqual((S[f"C01:{101 * M}"]["snapshot"], S[f"C01:{101 * M}"]["attempt"]),
                             (graph.snapshot_uuid("uuid-C01", 101 * M), 0))
            self.assertEqual((m["registry"]["sha256"], m["block"]["registry_sha256"], m["block"]["rederived"]), (rsha, rsha, False))
            e = m["edges"]
            self.assertEqual((e["scheduled"], e["executable"] + sum(e[k] for k in graph.EXCLUSION)), (266_024, 266_024))
            self.assertTrue(all(e[k] > 0 for k in graph.EXCLUSION))
            self.assertEqual(sum(c["scheduled"] for rs in m["by_family_role"].values() for c in rs.values()), 266_024)
            self.assertTrue(all(set(c) == {"scheduled", "executable", *graph.EXCLUSION}       # (P3: every cause column)
                                for rs in m["by_family_role"].values() for c in rs.values()))
            # every edge's exclusion recomputed independently: the first cause of its world endpoints
            unav = {(v["world"], v["time"]): v["status"] for v in S.values()}
            ex = {i: k for k, v in m["excluded_edges"].items() for i in v}
            for i, (q, p, *_) in enumerate(g["edges"]):
                sts = [unav[(w, t)] for _, w, t in map(graph.parse, (q, p)) if w is not None and (w, t) in unav]
                self.assertEqual(ex.get(i), min(sts, key=graph.EXCLUSION.index) if sts else None, (q, p))
            self.assertEqual(graph.mask(g, block, reg, rsha, "b" * 64), m)       # (deterministic: no clock)
            x = graph.executable(g, m, "m" * 64)
            self.assertEqual(x["edges"], [ed for i, ed in enumerate(g["edges"]) if i not in ex])   # (roles kept)
            xd = os.path.join(tmp, "x")
            graph.write(x, xd)
            gx = graph.load(os.path.join(xd, "graph.jsonl.gz"))
            self.assertEqual((len(gx["edges"]), gx["executable_of"]["edges_sha256"], gx["executable_of"]["mask"]["sha256"]),
                             (e["executable"], g["edges_sha256"], "m" * 64))
            rep = graph.report(gx)
            self.assertEqual((rep["quota_problems"], rep["executable_of"]["edges"]), ([], 266_024))
            # P2-5: a mask whose edge exclusions are not its snapshots' is refused (a missing, an extra, a duplicate,
            # an out-of-range index; a snapshot dropped; totals)
            bio, tec = m["excluded_edges"]["biological"], m["excluded_edges"]["technical"]
            x0 = next(i for i in range(len(g["edges"])) if i not in ex)
            for bad in (dict(m, excluded_edges=dict(m["excluded_edges"], biological=bio[1:])),
                        dict(m, excluded_edges=dict(m["excluded_edges"], technical=tec + [x0])),
                        dict(m, excluded_edges=dict(m["excluded_edges"], biological=bio + bio[:1])),
                        dict(m, excluded_edges=dict(m["excluded_edges"], biological=bio + [len(g["edges"]) + 3])),
                        dict(m, snapshots={k: v for k, v in S.items() if k != f"C01:{150 * M}"}),
                        dict(m, snapshots=dict(S, **{f"C01:{150 * M}": dict(S[f"C01:{150 * M}"], snapshot="x")})),
                        dict(m, edges=dict(e, executable=e["executable"] + 1))):
                with self.assertRaisesRegex(graph.GraphError, "does not describe this graph"):
                    graph.executable(g, bad)
            with self.assertRaisesRegex(graph.GraphError, "another graph"):
                graph.executable(g, dict(m, graph=dict(m["graph"], edges_sha256="0" * 64)))
            # the CLI: the same mask bytes, bound to the block file's and the registry's bytes
            bp, mp, rp = (os.path.join(tmp, f) for f in ("block.json", "mask.json", "worlds.json"))
            rqlib.write_durable(bp, rqlib.canonical(block))
            rqlib.write_durable(rp, rqlib.canonical(reg))
            before = {f: rqlib.sha256_file(os.path.join(gdir, f)) for f in sorted(os.listdir(gdir))}
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(graph.main(["mask", "--graph", gp, "--block", bp, "--registry", rp, "--no-rederive",
                                             "--out", mp]), 0)
                with self.assertRaises(SystemExit):                       # (neither --root nor --no-rederive)
                    graph.main(["mask", "--graph", gp, "--block", bp, "--registry", rp, "--out", mp + ".y"])
                self.assertEqual(graph.main(["executable", "--graph", gp, "--mask", mp, "--out", os.path.join(tmp, "x2")]), 0)
                # P2-8: never into the scheduled graph's own directory (however spelled); its bytes untouched
                for out in (gdir, gdir + os.sep, os.path.join(gdir, ".")):
                    self.assertEqual(graph.main(["executable", "--graph", gp, "--mask", mp, "--out", out]), 2)
            self.assertEqual({f: rqlib.sha256_file(os.path.join(gdir, f)) for f in sorted(os.listdir(gdir))}, before)
            with self.assertRaisesRegex(graph.GraphError, "never replaced"):
                graph.write(x, gdir)
            self.assertEqual({f: rqlib.sha256_file(os.path.join(gdir, f)) for f in sorted(os.listdir(gdir))}, before)
            graph.write(self.g, gdir)                                     # (the same bytes again: a no-op)
            self.assertEqual(rqlib.read_bytes(mp), rqlib.canonical(graph.mask(g, block, reg, rsha, rqlib.sha256_file(bp))))
            self.assertEqual(len(graph.load(os.path.join(tmp, "x2", "graph.jsonl.gz"))["edges"]), e["executable"])
        finally:
            shutil.rmtree(tmp)

    def test_mask_disposition_support(self):
        """Codex #77 r3 P1-2: the SHARED validator checks every disposition against the mask's REGISTERED burn-in rule
        and its evidence (disposition_support). Codex's case, C06's early zero at 3M with eight restarts left
        relabelled "exhausted" (decided, earlier frames pending, biological from 3M, nothing available), is refused
        (and executable refuses its mask); "exhausted" passes only at the final permitted attempt with every earlier
        attempt's early terminal evidenced; "established" with an early zero, a settled disposition under a registry
        without the rule, and a mask whose registry records no rule are refused."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        graph.write(self.g, tmp)
        g = graph.load(os.path.join(tmp, "graph.jsonl.gz"))
        reg, rsha = test_registry(g)
        m = graph.mask(g, masked_block(g, reg, rsha), reg, rsha)
        self.assertEqual(graph.mask_evidence_problems(m), [])
        M, W, S = 1_000_000, m["worlds"], m["snapshots"]
        u6 = W["C06"]["uuid"]

        def c06(disp, k=0, prior=(), late=False):
            w = dict(W["C06"], burn_in={"decided": graph.DISPOSITIONS[disp], "why": "relabelled", "disposition": disp},
                     burn_in_decided=graph.DISPOSITIONS[disp], attempt=k, attempt_uuid=graph.attempt_uuid(u6, k),
                     prior_attempts=[{"attempt": j, "first_terminal": {"frame": 6 * M if late and j == 3 else 2 * M,
                                                                       "kind": "prey"}} for j in prior])
            s = {k_: v for k_, v in S.items() if v["world"] != "C06"}
            for t in graph.TIMES:
                f = graph.frame_of(t)
                st = "biological" if f >= 3 * M else "pending"
                s[f"C06:{f}"] = dict({"world": "C06", "time": t, "frame": f, "status": st, "why": "relabelled", "uuid": u6,
                                      "attempt": k, "snapshot": graph.snapshot_uuid(u6, f)},
                                     **({"valid_before": 3 * M} if st == "biological" else {}))
            return dict(m, worlds=dict(W, C06=w), snapshots=s)
        codex = c06("exhausted")
        probs = graph.mask_evidence_problems(codex)
        self.assertTrue(any(p.startswith("C06:") and "8 remain" in p for p in probs), probs)
        with self.assertRaisesRegex(graph.GraphError, "does not describe this graph"):
            graph.executable(g, codex)
        self.assertEqual(graph.mask_evidence_problems(c06("exhausted", 8, range(8))), [])     # (earned: all used)
        probs = graph.mask_evidence_problems(c06("exhausted", 8, range(8), late=True))
        self.assertTrue(any("early terminals are not all evidenced" in p for p in probs), probs)
        probs = graph.mask_evidence_problems(c06("exhausted", 8, range(7)))
        self.assertTrue(any("early terminals are not all evidenced" in p for p in probs), probs)
        probs = graph.mask_evidence_problems(c06("established"))
        self.assertTrue(any("established, but its first terminal" in p for p in probs), probs)
        probs = graph.mask_evidence_problems(dict(m, registry=dict(m["registry"], burn_in_frame=0)))
        self.assertTrue(any("under no registered burn-in rule" in p for p in probs), probs)
        probs = graph.mask_evidence_problems(dict(m, registry={k: v for k, v in m["registry"].items() if k != "burn_in_frame"}))
        self.assertTrue(probs and "no burn-in frame" in probs[0], probs)
        blk = masked_block(g, reg, rsha)                                     # (the worlds block: the same rule)
        blk["worlds"]["C06"]["burn_in"] = {"decided": True, "why": "x", "disposition": "exhausted"}
        with self.assertRaisesRegex(graph.GraphError, "remain"):
            graph.mask(g, blk, reg, rsha)

    def test_exclusive_publication(self):
        """Codex #77 r2 P2-4: a graph is published EXCLUSIVELY, as one serialized transaction under the directory's
        lock: the same bytes again are a no-op; other bytes are refused before anything is written (both files
        checked first); a transaction interrupted after the edges completes with the same bytes; no temporary file
        is left; another graph never replaces an existing edge file or meta."""
        tmp = tempfile.mkdtemp()
        try:
            d = os.path.join(tmp, "g")
            meta = graph.write(self.g, d)
            files = lambda: {f: rqlib.sha256_file(os.path.join(d, f)) for f in sorted(os.listdir(d))}  # noqa: E731
            before = files()
            self.assertEqual(sorted(before), [".graph.lock", "graph.jsonl.gz", "graph.meta.json"])
            self.assertEqual(graph.write(self.g, d), meta)                   # (the same bytes: a no-op)
            other = dict(self.g, namespace="another")
            with self.assertRaisesRegex(graph.GraphError, "never replaced"):
                graph.write(other, d)
            self.assertEqual(files(), before)
            os.remove(os.path.join(d, "graph.meta.json"))                  # (interrupted after the edges)
            graph.write(self.g, d)
            self.assertEqual(files(), before)
            rqlib.write_durable(os.path.join(d, "graph.meta.json"), b"{}")
            with self.assertRaisesRegex(graph.GraphError, "graph.meta.json exists with other bytes"):
                graph.write(self.g, d)
            self.assertFalse([f for f in os.listdir(d) if ".tmp." in f])
            p = os.path.join(d, "x.bin")
            self.assertTrue(graph._publish_exclusive(p, b"a"))
            self.assertFalse(graph._publish_exclusive(p, b"a"))
            with self.assertRaisesRegex(graph.GraphError, "never replaced"):
                graph._publish_exclusive(p, b"b")
            self.assertEqual(rqlib.read_bytes(p), b"a")
        finally:
            shutil.rmtree(tmp)

    def test_mask_refuses_unbound_evidence(self):
        """Codex #77 r1 P1-1, P2-3: nothing is masked from evidence the study's registry does not bind: a block of
        ANOTHER registry with the same ids and allocation, another uuid, an unregistered attempt or another attempt
        identity, a legacy block or entry (no evidence record, no explicit burn-in disposition), a disposition its
        evidence contradicts, a valid_before that is not the evidenced first terminal, archived frames that are not
        verified objects, other burn-in settings, a graph built from another registry or recording other uuids."""
        g = self.g
        reg, rsha = test_registry(g)
        block = masked_block(g, reg, rsha)
        graph.mask(g, block, reg, rsha)
        other, osha = test_registry(g, "another-study")
        W, M = block["worlds"], 1_000_000

        def w(wid, **kw):
            return dict(block, worlds=dict(W, **{wid: dict(W[wid], **kw)}))
        cases = [(block, other, osha, "made from another registry"),
                 (w("C01", uuid="uuid-other"), reg, rsha, "uuid"),
                 (w("C01", attempt=9), reg, rsha, "reserves attempts 0..8"),
                 (w("C01", attempt=1), reg, rsha, "attempt identity"),
                 (w("C01", treatment="A"), reg, rsha, "the registry has"),
                 (dict(block, worlds={k: v for k, v in W.items() if k != "B16"}), reg, rsha, "missing"),
                 ({k: v for k, v in block.items() if k != "evidence"}, reg, rsha, "legacy worlds block"),
                 (w("C02", burn_in={"decided": True, "why": "ended done"}), reg, rsha, "no explicit burn-in disposition"),
                 (w("C06", burn_in=dict(W["C06"]["burn_in"], decided=True)), reg, rsha, "contradicts"),
                 (w("C06", burn_in={"decided": True, "why": "x", "disposition": "established"}), reg, rsha,
                  "not supported by its evidence"),
                 (w("C03", burn_in={"decided": True, "why": "x", "disposition": "established"}), reg, rsha,
                  "not supported by its evidence"),
                 (w("C01", valid_before=50 * M), reg, rsha, "first terminal"),
                 (w("C01", valid_before=None), reg, rsha, "first terminal"),
                 (w("C02", archived=W["C02"]["archived"] + [50 * M]), reg, rsha, "verified archive"),
                 (w("C04", archived=W["C04"]["archived"] + [60 * M]), reg, rsha, "verified archive"),
                 (dict(block, max_restarts=2), reg, rsha, "max restarts")]
        for blk, r, s, msg in cases:
            with self.assertRaisesRegex(graph.GraphError, msg):
                graph.mask(g, blk, r, s)
        with self.assertRaisesRegex(graph.GraphError, "graph was built from another registry"):
            graph.mask(dict(g, registry={"namespace": "another-study", "uuids": {}}), block, reg, rsha)
        gb = dict(g, registry={"namespace": reg["namespace"], "uuids": {x["id"]: x["uuid"] for x in reg["worlds"]}})
        self.assertEqual(graph.mask(gb, block, reg, rsha)["edges"], graph.mask(g, block, reg, rsha)["edges"])
        with self.assertRaisesRegex(graph.GraphError, "recorded another uuid"):
            graph.mask(dict(gb, registry=dict(gb["registry"], uuids=dict(gb["registry"]["uuids"], C01="x"))), block, reg, rsha)
        self.assertEqual(graph.attempt_uuid("u", 0), "u")
        self.assertNotEqual(graph.attempt_uuid("u", 1), graph.attempt_uuid("u", 2))


def test_registry(g, ns="rq-test-study"):
    """A registry of the synthetic graph's worlds (uuids uuid-<id>, the slot/1 burn-in rule at 5M, 8 restarts) and the
    sha256 of its canonical bytes."""
    reg = {"schema": "finfolk.redqueen.worlds/1", "namespace": ns, "seed_scheme": graph.SEED_SCHEME,
           "burn_in": 5_000_000, "max_restarts": 8, "worlds": [dict(w, uuid=f"uuid-{w['id']}") for w in g["worlds"]]}
    return reg, rqlib.sha256_bytes(rqlib.canonical(reg))


def masked_block(g, reg, rsha, pending=()):
    """worlds.py design-block's form for the synthetic graph, bound to reg: every world done, established and archived
    (verified) at every time, but C01 extinct (its first zero sampled just after 100M), C02 without its 50M archive,
    C03 unresolved (running at 2M, before the 5M burn-in), C04 with a damaged 60M archive, C05 extinct exactly at
    100M, C06 an early zero at 3M awaiting its restart, A01 running (evidenced and archived to 120M), B01 with an
    off-chain 70M archive, B02 with a refill at 80M; the worlds in `pending` unresolved."""
    M = 1_000_000
    allf = [1] + [t * M for t in range(1, 201)]
    rw = {w["id"]: w for w in reg["worlds"]}

    def entry(wid, status="done", frontier=200 * M, frames=allf, first=None, disp="established", refill=None, bad=None):
        arch = {str(f): {"label": "F1" if f == 1 else f"end.{f}", "sha256": rqlib.sha256_bytes(f"{wid}:{f}".encode()),
                         "path": f"/archive/{wid}/{f}.json", "status": "verified", "why": None} for f in frames}
        for f, st in (bad or {}).items():
            arch[str(f)].update(status=st, why=f"{st} (a test)")
        w = rw[wid]
        return {"uuid": w["uuid"], "attempt_uuid": graph.attempt_uuid(w["uuid"], 0), "treatment": w["treatment"],
                "block": w["block"], "status": status, "attempt": 0, "valid_before": first,
                "first_zeros": {"prey": first} if first else {},
                "burn_in": {"decided": graph.DISPOSITIONS[disp], "why": disp, "disposition": disp}, "prior_attempts": [],
                "archived": sorted(int(f) for f, a in arch.items() if a["status"] == "verified"), "archive": arch,
                "evidence": {"frontier": frontier, "accepted_through": frontier,
                             "first_terminal": {"frame": first, "kind": "prey"} if first else None, "refill": refill,
                             "stop": None, "observation": "event" if first else "administrative", "unsupported_ledger": []}}
    ws = {wid: entry(wid) for wid in rw}
    ws["C01"] = entry("C01", "extinct", 100 * M + 5000, first=100 * M + 5000)
    ws["C02"] = entry("C02", frames=[f for f in allf if f != 50 * M])
    ws["C03"] = entry("C03", "running", 2 * M, frames=[1, M, 2 * M], disp="unresolved")
    ws["C04"] = entry("C04", bad={60 * M: "mismatch"})
    ws["C05"] = entry("C05", "extinct", 100 * M, first=100 * M)
    ws["C06"] = entry("C06", "extinct", 3 * M, frames=[1, M, 2 * M, 3 * M], first=3 * M, disp="restart_pending")
    ws["A01"] = entry("A01", "running", 120 * M, frames=[f for f in allf if f <= 120 * M])
    ws["B01"] = entry("B01", bad={70 * M: "off_chain"})
    ws["B02"] = entry("B02", "done", 80 * M - 500, refill={"frame": 80 * M, "value": 1, "baseline": 0})
    for wid in pending:
        ws[wid] = entry(wid, "running", 2 * M, frames=[1, M, 2 * M], disp="unresolved")
    return {"schema": graph.BLOCK_SCHEMA, "registry_sha256": rsha, "namespace": reg["namespace"], "times": {},
            "burn_in_frame": 5 * M, "max_restarts": 8,
            "evidence": {"schema": graph.BLOCK_EVIDENCE_SCHEMA, "evidence_sha256": "e" * 64, "tool_sha256": "t" * 64,
                         "inputs": {}},
            "worlds": ws}


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

    def flag_scores(self, where, model=None):
        """recovery.scorer wrapped so that a score of a set for which where(ix) holds (and, with model, of a model
        for which model(m) holds) ALSO reports one finite UNRESOLVED pair (map.pred_count_lpd's grid_unresolved)
        in its integration diagnostics."""
        import unittest.mock as mock
        real = self.rec.scorer

        def scorer(D, data, m, idx, fitter):
            sc = real(D, data, m, idx, fitter)

            def score(ix, info=None):
                out = sc(ix, info)
                if info is not None and where(ix) and (model is None or model(m)):
                    info["grid_unresolved"] = info.get("grid_unresolved", 0) + 1
                return out
            return score
        return mock.patch.object(self.rec, "scorer", scorer)

    def test_unresolved_scores_never_decide_procedure(self):
        """r5 P2-1: a finite but unresolved score (grid_unresolved) in a selection (validation), a test or a
        snapshot comparison is reported, and the comparison is not decided on it: unavailable with its reason,
        no improvement or bound, success False; both models' diagnostics are kept beside the comparison."""
        D, R = self.D, self.rec
        data = R.simulate(D, dict(rank=1, energy=0.10), 13)
        run = lambda: R.procedure(D, data, "a", 1, [0.1], 8, 13)        # noqa: E731
        base = run()
        self.assertTrue(base["decision"]["available"] and base["success"] and base["selected"]["rank"] == 1)
        self.assertEqual(base["integration_comparison"]["unresolved"], {"validation": 0, "test": 0, "snapshot": 0})
        self.assertEqual(set(base["integration_comparison"]), {"selected", "rank0", "snapshot", "unresolved"})
        self.assertIsNotNone(base["snapshot_test_improvement"])
        with self.flag_scores(lambda ix: ix is D.test_idx):
            out = run()
        self.assertFalse(out["decision"]["available"])
        self.assertRegex(out["decision"]["reason"], "UNRESOLVED")
        self.assertFalse(out["success"])
        self.assertIsNone(out["test_improvement"])
        self.assertIsNone(out["test_lb"])
        self.assertFalse(out["selected_primary"]["success"])
        self.assertEqual(out["integration_comparison"]["unresolved"]["test"], 2)       # (selected and rank 0)
        self.assertEqual(out["integration_comparison"]["selected"]["grid_unresolved"], 1)
        self.assertEqual(out["integration_comparison"]["rank0"]["grid_unresolved"], 1)
        self.assertEqual(out["selected"], base["selected"])
        for c in out["candidates"]:
            self.assertIsNone(c["test_lb"])
        with self.flag_scores(lambda ix: ix is D.stest_idx):                            # (the snapshot only)
            out = run()
        self.assertTrue(out["decision"]["available"] and out["success"])
        self.assertIsNone(out["snapshot_test_improvement"])
        self.assertEqual(out["integration_comparison"]["unresolved"]["snapshot"], 2)
        self.assertEqual(out["integration_comparison"]["snapshot"]["selected"]["grid_unresolved"], 1)
        self.assertIsNotNone(out["snapshot_test_improvement_gauss"])
        self.assertTrue(base["selected_primary"]["available"] and base["selected_primary"]["test_lb"] > 0)
        self.assertIsNotNone(base["alignment_u1_b"])
        self.assertIsNotNone(base["classes"])
        with self.flag_scores(lambda ix: ix is D.val_idx):                              # (the selection)
            out = run()
        self.assertFalse(out["decision"]["available"])
        self.assertFalse(out["success"])
        self.assertGreater(out["integration_comparison"]["unresolved"]["validation"], 0)
        self.assertIn("in validation", out["decision"]["reason"])
        # r6 P2-1: an unresolved VALIDATION selection leaves every selection-dependent reported metric withheld, not
        # only the decision (the score arrays are untouched, so these were positive / present before the fix)
        self.assertTrue(out["decision"]["selection_unresolved"] and out["selected"]["selection_unresolved"])
        self.assertGreater(out["decision"]["integration_unresolved"], 0)
        for k in ("test_improvement", "test_lb", "snapshot_test_improvement", "snapshot_test_improvement_gauss",
                  "alignment_u1_b", "classes"):
            self.assertIsNone(out[k], k)
        self.assertEqual(out["per_test_world"], [])
        sp = out["selected_primary"]
        self.assertFalse(sp["available"] or sp["success"])
        self.assertTrue(sp["selection_unresolved"])
        self.assertIsNone(sp["test_improvement"])
        self.assertIsNone(sp["test_lb"])
        self.assertEqual({k: out["selected"][k] for k in ("rank", "lambda")},
                         {k: base["selected"][k] for k in ("rank", "lambda")})           # (the nominal pick, flagged)

    def test_primary_has_its_own_availability(self):
        """r7 P2-2: the primary result reads the validation scores of its rank <= PRIMARY_RANKS candidates only. A
        flag in a rank-3 candidate's validation leaves the FULL selection unresolved but the primary decided."""
        D, R = self.D, self.rec
        data = R.simulate(D, dict(rank=1, energy=0.10), 13)
        run = lambda: R.procedure(D, data, "a", 3, [0.1], 8, 13)        # noqa: E731
        base = run()
        with self.flag_scores(lambda ix: ix is D.val_idx, model=lambda m: m["u"].shape[1] >= 3):
            out = run()
        self.assertFalse(out["decision"]["available"])
        self.assertTrue(out["decision"]["selection_unresolved"] and out["selected"]["selection_unresolved"])
        self.assertIsNone(out["test_lb"])
        sp = out["selected_primary"]
        self.assertTrue(sp["available"])
        self.assertNotIn("selection_unresolved", sp)
        self.assertLessEqual(sp["rank"], R.PRIMARY_RANKS)
        for k in ("rank", "lambda", "test_improvement", "test_lb", "success"):
            self.assertEqual(sp[k], base["selected_primary"][k], k)                   # (the unflagged primary, kept)
        self.assertIsNotNone(sp["test_lb"])
        with self.flag_scores(lambda ix: ix is D.val_idx, model=lambda m: m["u"].shape[1] == 1):   # (a primary rank)
            out = run()
        self.assertFalse(out["selected_primary"]["available"])
        self.assertTrue(out["selected_primary"]["selection_unresolved"])

    def test_unresolved_scores_never_decide_forward(self):
        """r5 P2-1, the forward tests: a flagged score in a test set's two models (or in the validation
        selection) makes that branch unavailable (reason, counts, both diagnostics), never a success."""
        D, R = self.D, self.rec
        data = R.simulate(D, dict(rank=1, energy=0.10), 17)
        F = D.forward
        run = lambda: R.forward_procedure(D, data, 1, [0.1], 6, 17)     # noqa: E731
        base = run()
        for k in ("forward_transfer", "intersection"):
            self.assertTrue(base[k]["available"] and base[k]["integration_unresolved"] == 0, base[k])
            self.assertEqual(set(base[k]["integration"]), {"selected", "rank0"})
        self.assertTrue(base["decision"]["available"])
        with self.flag_scores(lambda ix: ix is F["tests"]["forward_transfer"]):
            out = run()
        ft = out["forward_transfer"]
        self.assertFalse(ft["available"])
        self.assertRegex(ft["reason"], "UNRESOLVED")
        self.assertEqual(ft["integration_unresolved"], 2 if base["selected"]["rank"] else 1)
        self.assertEqual(ft["integration"]["selected"]["grid_unresolved"], 1)
        self.assertTrue(out["intersection"]["available"])                               # (its own scores: fine)
        self.assertFalse(out["success"])
        self.assertFalse(out["decision"]["available"])
        self.assertIsNone(out["test_lb"])
        with self.flag_scores(lambda ix: ix is F["val"]):
            out = run()
        self.assertGreater(out["integration_unresolved"]["validation"], 0)
        for k in ("forward_transfer", "intersection"):
            self.assertFalse(out[k]["available"], k)
            self.assertIn("in validation", out[k]["reason"])
        self.assertFalse(out["success"])
        self.assertTrue(out["decision"]["selection_unresolved"] and out["selected"]["selection_unresolved"])
        self.assertEqual(out["decision"]["integration_unresolved"], out["integration_unresolved"]["validation"])
        self.assertIsNone(out["test_improvement"])
        self.assertIsNone(out["test_lb"])

    def test_conditioning(self):
        rep = self.rec.conditioning(self.D, 2, "a")
        self.assertIn("prey:world-test", rep)
        self.assertIn("predators:snapshot-val", rep)
        self.assertEqual(rep["prey:world-test"]["singular"], 0)
        self.assertEqual(rep["prey:train"]["n"], 3620 + 4020)     # eligible C training states + A/B training prey

    def test_executable_graph(self):
        """PR-C (Annex H D6 rule 27): recovery.py consumes an executable (masked) graph as it consumes a graph:
        its datasets are the executable pairs only, the scheduled roles intact."""
        tmp = tempfile.mkdtemp()
        try:
            gdir, xdir = os.path.join(tmp, "g"), os.path.join(tmp, "x")
            graph.write(full(), gdir)
            g = graph.load(os.path.join(gdir, "graph.jsonl.gz"))
            reg, rsha = test_registry(g)
            m = graph.mask(g, masked_block(g, reg, rsha), reg, rsha)
            graph.write(graph.executable(g, m), xdir)
            D = self.rec.Data(graph.load(os.path.join(xdir, "graph.jsonl.gz")))
            self.assertEqual(len(D.qi), m["edges"]["executable"])
            self.assertLess(len(D.qi), len(self.D.qi))
            self.assertIn("prey:train", self.rec.conditioning(D, 1, "a"))
        finally:
            shutil.rmtree(tmp)

    def test_masked_attrition_is_unavailable(self):
        """Codex #77 r1 P2-6: under a mask that removes EVERY test root, or all but one, the complete selection
        procedure reports itself UNAVAILABLE (its reason, no success, no bound from zero or one source) instead of
        reaching the crossed bootstrap; the unmasked graph passes the same guard with its six roots."""
        tmp = tempfile.mkdtemp()
        try:
            gdir = os.path.join(tmp, "g")
            graph.write(full(), gdir)
            g = graph.load(os.path.join(gdir, "graph.jsonl.gz"))
            reg, rsha = test_registry(g)
            roots = sorted(self.D.worlds[int(w)] for w in np.unique(self.D.test_world))
            self.assertEqual(self.rec.unavailable(self.D.fit["a"], self.D.val_idx, self.D.test_idx, self.D.test_world,
                                                  self.D.val_world), (None, 6))
            for keep, want in ((0, 0), (1, 1)):
                m = graph.mask(g, masked_block(g, reg, rsha, pending=roots[keep:]), reg, rsha)
                xdir = os.path.join(tmp, f"x{keep}")
                graph.write(graph.executable(g, m), xdir)
                D = self.rec.Data(graph.load(os.path.join(xdir, "graph.jsonl.gz")))
                r = self.rec.procedure(D, None, "a", 2, [0.1], 2, 0)
                self.assertEqual((r["available"], r["test_roots"], "success" in r), (False, want, False), r)
                self.assertIn("test root" if want else "test root(s)", r["reason"])
        finally:
            shutil.rmtree(tmp)

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

    def flag_validation(self, model=None):
        """recovery.scorer patched so that the VALIDATION scores (the second scoring of a model in procedure(): the
        test set is scored first) of a model with model(m) report one finite unresolved pair."""
        import unittest.mock as mock
        real = self.rec.scorer

        def scorer(D, data, m, idx, fitter):
            sc, calls = real(D, data, m, idx, fitter), []

            def score(ix, info=None):
                res = sc(ix, info)
                calls.append(1)
                if info is not None and len(calls) == 2 and (model is None or model(m)):
                    info["grid_unresolved"] = 1
                return res
            return score
        return mock.patch.object(self.rec, "scorer", scorer)

    def test_summary_excludes_unresolved_selections(self):
        """r6 P2-1: summarize() keeps a result whose selection or comparison is UNRESOLVED (a finite score that
        failed its integration check) out of every numeric aggregate and rank histogram, and counts it by itself.
        r7 P2-1: the acceptance rate (rate, wilson95) is successes / datasets, an unavailable dataset being
        unsuccessful; the conditional successes / decided rate is reported beside it, labelled. r7 P2-2: the primary
        block aggregates every dataset on the primary's own availability. Dataset 0 is an ordinary result; dataset 1
        is a real run whose validation scores are injected as flagged."""
        R = self.rec
        out = os.path.join(self.tmp, "unres")
        R.prepare_run(self.ns(options="a", lambdas="0.1", iters=3, out=out))
        for rep in (0, 1):
            f = os.path.join(out, f"r0.{rep:03d}.json")
            args = self.ns(options="a", lambdas="0.1", iters=3, scenario="r0", rep=rep, out=f)
            if rep == 0:
                self.assertEqual(R.one(args), 0)
                continue
            with self.flag_validation():
                self.assertEqual(R.one(args), 0)
        o0 = rqlib.read_json(os.path.join(out, "r0.000.json"))["options"]["a"]
        o1 = rqlib.read_json(os.path.join(out, "r0.001.json"))["options"]["a"]
        self.assertTrue(o0["decision"]["available"])
        self.assertFalse(o1["decision"]["available"])
        self.assertTrue(o1["decision"]["selection_unresolved"])
        for k in ("test_improvement", "test_lb", "snapshot_test_improvement", "alignment_u1_b", "classes"):
            self.assertIsNone(o1[k], k)
        self.assertFalse(o1["selected_primary"]["available"])
        cell = R.summarize(out)["cells"][0]
        self.assertEqual((cell["datasets"], cell["decided"], cell["decision_unavailable"]), (2, 1, 1))
        self.assertEqual((cell["unresolved_decisions"], cell["unresolved_selections"]), (1, 1))
        self.assertEqual(sum(cell["selected_ranks"].values()), 1)                     # (the decided one only)
        self.assertEqual(cell["selected_ranks"], {o0["selected"]["rank"]: 1})
        self.assertEqual(sum(cell["selected_start"].values()), 1)
        self.assertEqual(cell["successes"], int(o0["success"]))
        self.assertEqual(cell["rate"], round(int(o0["success"]) / 2, 3))              # (acceptance: / datasets)
        self.assertEqual(cell["wilson95"], R.wilson(int(o0["success"]), 2))
        self.assertEqual(cell["conditional"]["rate"], float(o0["success"]))           # (conditional: / decided)
        self.assertEqual(cell["conditional"]["wilson95"], R.wilson(int(o0["success"]), 1))
        self.assertEqual((cell["unavailable"], cell["decided_fraction"]), (1, 0.5))
        self.assertIn("acceptance", cell["rate_basis"])
        self.assertIn("NOT the acceptance", cell["conditional"]["basis"])
        self.assertEqual(cell["mean_test_lb"], o0["test_lb"])
        self.assertEqual(cell["mean_test_improvement"], o0["test_improvement"])
        pr = cell["primary"]
        self.assertEqual((pr["datasets"], pr["decided"], pr["unavailable"]), (2, 1, 1))   # (the unavailable one, counted)
        self.assertEqual(sum(pr["selected_ranks"].values()), 1)
        self.assertEqual(pr["rate"], round(int(o0["selected_primary"]["success"]) / 2, 3))
        self.assertEqual(pr["conditional"]["rate"], float(o0["selected_primary"]["success"]))
        self.assertEqual(cell["classes"], {k: {f: float(v[f]) for f in ("rmse_selected", "rmse_rank0", "interaction_sd")}
                                           for k, v in o0["classes"].items()})

    def test_acceptance_rate_counts_unavailable_datasets(self):
        """r7 P2-1: four successes, one decided failure and fifteen unavailable datasets are a 20% acceptance rate
        (Wilson interval over 20), and a conditional 80% over the 5 decided ones, labelled as such."""
        import copy
        R = self.rec
        out = os.path.join(self.tmp, "accept")
        R.prepare_run(self.ns(options="a", lambdas="0.1", iters=3, out=out))
        f0 = os.path.join(out, "r0.000.json")
        self.assertEqual(R.one(self.ns(options="a", lambdas="0.1", iters=3, scenario="r0", rep=0, out=f0)), 0)
        r0 = rqlib.read_json(f0)

        def make(rep, kind):
            r = copy.deepcopy(r0)
            r["rep"], r["seed"] = rep, rqlib.derive_seed("ns", "recovery", "r0", rep)
            o = r["options"]["a"]
            o["success"] = kind == "success"
            o["selected_primary"]["success"] = kind == "success"
            if kind == "unavailable":
                o["decision"] = {"available": False, "selection_unresolved": True, "integration_unresolved": 1,
                                 "test_worlds": 6, "reason": "unresolved"}
                o["selected_primary"]["available"] = False
            else:
                o["decision"] = {"available": True, "test_worlds": 6, "reason": None}
                o["selected_primary"]["available"] = True
            rqlib.write_durable(os.path.join(out, f"r0.{rep:03d}.json"), rqlib.canonical(r))
        kinds = ["success"] * 4 + ["failure"] + ["unavailable"] * 15
        for rep, kind in enumerate(kinds):
            make(rep, kind)
        cell = R.summarize(out)["cells"][0]
        self.assertEqual((cell["datasets"], cell["successes"], cell["decided"], cell["unavailable"]), (20, 4, 5, 15))
        self.assertEqual(cell["rate"], 0.2)
        self.assertEqual(cell["wilson95"], R.wilson(4, 20))
        self.assertEqual(cell["conditional"]["rate"], 0.8)
        self.assertEqual(cell["conditional"]["wilson95"], R.wilson(4, 5))
        self.assertEqual(cell["decided_fraction"], 0.25)
        self.assertEqual(cell["decision_unavailable"], 15)
        pr = cell["primary"]                                           # (the same on the primary result)
        self.assertEqual((pr["datasets"], pr["successes"], pr["decided"], pr["unavailable"]), (20, 4, 5, 15))
        self.assertEqual((pr["rate"], pr["conditional"]["rate"]), (0.2, 0.8))
        for rep in range(20):                                          # (none decides: the counts stay)
            make(rep, "unavailable")
        cell = R.summarize(out)["cells"][0]
        self.assertEqual((cell["decided"], cell["rate"], cell["conditional"]["rate"]), (0, 0.0, None))
        self.assertEqual((cell["primary"]["datasets"], cell["primary"]["unavailable"], cell["primary"]["decided"]),
                         (20, 20, 0))

    def test_summary_primary_independent_of_full_selection(self):
        """r7 P2-2: a rank-3-only validation flag leaves the full selection unavailable but the primary decided, and
        the summary keeps the primary result (success count, rank histogram) and counts the full one unavailable."""
        R = self.rec
        out = os.path.join(self.tmp, "prim")
        R.prepare_run(self.ns(options="a", ranks=3, lambdas="0.1", iters=3, out=out))
        f = os.path.join(out, "r0.000.json")
        with self.flag_validation(model=lambda m: m["u"].shape[1] >= 3):
            self.assertEqual(R.one(self.ns(options="a", ranks=3, lambdas="0.1", iters=3, scenario="r0", rep=0,
                                           out=f)), 0)
        o = rqlib.read_json(f)["options"]["a"]
        self.assertFalse(o["decision"]["available"])
        self.assertTrue(o["selected_primary"]["available"])
        cell = R.summarize(out)["cells"][0]
        self.assertEqual((cell["datasets"], cell["decided"], cell["unavailable"], cell["successes"]), (1, 0, 1, 0))
        self.assertEqual(cell["selected_ranks"], {})
        pr = cell["primary"]
        self.assertEqual((pr["datasets"], pr["decided"], pr["unavailable"]), (1, 1, 0))
        self.assertEqual(pr["selected_ranks"], {o["selected_primary"]["rank"]: 1})
        self.assertEqual(pr["successes"], int(o["selected_primary"]["success"]))
        self.assertEqual(pr["conditional"]["rate"], float(o["selected_primary"]["success"]))

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
        self.assertEqual(len(lk.statuses), 2 * 2 * M.LINK_STEPS)               # (r2 P3: every GN step's QP)
        self.assertTrue(all(st["converged"] for st in lk.statuses))
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
        # (the quadrature SD at zero variance is the sqrt of rounding noise ~1e-16: up to ~1e-8 on the merged graph)
        self.assertTrue(np.allclose(q0, sp["q_plugin"]) and np.allclose(sd0, 0.0, atol=1e-6))
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
        seen = idx_w[D.ownw[idx_w] != w0]
        part = M.own_world_stage2(D, m, data, seen, folds=5)
        self.assertEqual(part["world_var"].shape, (D.nbins,))
        ov = M.own_var(D, part, idx_w)
        un = D.ownw[idx_w] == w0
        self.assertTrue(np.array_equal(ov[un], part["world_var"][D.lagbin[idx_w][un]]) and not ov[~un].any())
        # r2 P2-3: the integration has a predictive path. An unseen world's within pairs carry the lag bin's
        # deviation variance inside the link (pred_eta, pred_var, pred_count_lpd); a seen world's do not.
        e0, s0_ = M.pred_eta(D, m, idx_w)
        e1, s1_ = M.pred_eta(D, m, idx_w, own=part)
        self.assertTrue(np.allclose(s1_ - s0_, ov) and np.allclose(e1 - e0, M._own_terms(D, part, idx_w)))
        cnt = data["cnt"][idx_w[un][:200]]
        lp = M.pred_count_lpd(D, m, idx_w[un][:200], cnt, rec.B_COUNT, own=part)
        self.assertTrue(np.isfinite(lp).all())
        with self.assertRaisesRegex(ValueError, "capture stage-2"):
            M.pred_eta(D, m, idx_w, own=own_s)
        parts = M.own_world_stage2(D, m, sdat, seen, folds=5, head="survival")
        sp0, sp1 = M.survival_posterior(D, m, idx_w), M.survival_posterior(D, m, idx_w, own=parts)
        self.assertTrue(np.allclose(sp1["var1"] - sp0["var1"], M.own_var(D, parts, idx_w)))
        self.assertTrue(np.array_equal(sp1["var0"], sp0["var0"]) and np.array_equal(sp1["cov01"], sp0["cov01"]))
        with self.assertRaisesRegex(ValueError, "survival stage-2"):
            M.survival_posterior(D, m, idx_w, own=part)
        with self.assertRaises(ValueError):
            M.own_world_stage2(D, m, data, idx_w, head="x")

    def test_unseen_world_lag_deviation_variance(self):
        """r2 P2-3: the variance of the LAG-DEPENDENT world deviations. Four worlds with opposite deviations
        (+d, -d) at two equally populated lag bins: every world's lag-averaged residual is 0 (the old
        estimate was 0), and each bin's between-world variance is var(+d, -d, +d, -d) = 4 d^2 / 3."""
        import types
        M = self.M
        nW, per, d = 4, 50, 0.3
        lw = np.repeat(np.arange(nW), 2 * per)
        lb = np.tile(np.repeat([0, 1], per), nW)
        n = len(lw)
        Dx = types.SimpleNamespace(qi=np.zeros(n, int), pj=np.zeros(n, int), within=np.ones(n, bool), lagbin=lb,
                                   ownw=lw, nbins=2, worlds=list(range(nW)))
        kn = np.linspace(-1.0, 1.0, 4)
        mx = {"surfC": M.Surface(kn, kn, ("inc", "dec")), "a": np.zeros(1), "b": np.zeros(1),
              "u": np.zeros((1, 0)), "v": np.zeros((1, 0)), "link": M.Link()}
        zbar = d * np.where(lw % 2 == 0, 1.0, -1.0) * np.where(lb == 0, 1.0, -1.0)
        for x in range(nW):
            self.assertAlmostEqual(float(zbar[lw == x].mean()), 0.0)          # (no world-average signal)
        own = M.own_world_stage2(Dx, mx, {"zbar": zbar}, np.arange(n), folds=5)
        self.assertTrue(np.allclose(own["world_var"], [4 * d * d / 3] * 2) and own["world_var_supported"].all())
        part = M.own_world_stage2(Dx, mx, {"zbar": zbar}, np.flatnonzero(lw != 3), folds=5)
        ov = M.own_var(Dx, part, np.arange(n))
        self.assertTrue(np.allclose(ov[lw == 3], part["world_var"][lb[lw == 3]]) and not ov[lw != 3].any())
        self.assertTrue((part["world_var"] > 0).all())
        one = M.own_world_stage2(Dx, mx, {"zbar": zbar}, np.flatnonzero(lw == 0), folds=5)
        self.assertFalse(one["world_var_supported"].any())                    # (one world: unsupported)

    def test_noise_scale_known_answer(self):
        """r2 P2-1: one absolute unit. A scalar linear block (a mean estimated from cells with variances phi V /
        R, equal numbers at V = 0.36 and 0.0225) has the GLS variance 1 / sum(R / (phi V)); the old scale (the
        unweighted mean replicate-mean variance) inflated it by mean(V) mean(1/V) = 4.52. In a fit, unit is
        phi / (R mean(1/V)) at the fitted fractions, every head is weighted in it, and a predator block's
        covariance equals the inverse of its ABSOLUTE-precision Hessian recomputed here."""
        D, M = self.D, self.M
        R, phi, n = 6, 1.3, 400
        V = np.repeat([0.36, 0.0225], n)
        w, unit, ph = M.capture_scale(V, phi * V, R)
        self.assertAlmostEqual(ph, phi)
        self.assertAlmostEqual(float(w.mean()), 1.0)
        self.assertTrue(np.allclose(unit / w, phi * V / R))                       # (each cell's absolute variance)
        cov = M._block_cov(np.zeros(2 * n, int), np.ones((2 * n, 1)), w, np.zeros(1), 1, unit)[0, 0, 0]
        gls = 1.0 / float(np.sum(R / (phi * V)))
        self.assertAlmostEqual(cov, gls, delta=1e-12 * gls)
        old = M._block_cov(np.zeros(2 * n, int), np.ones((2 * n, 1)), w, np.zeros(1), 1,
                           float(np.mean(phi * V)) / R)[0, 0, 0]
        self.assertAlmostEqual(old / gls, float(np.mean(V) * np.mean(1 / V)), places=9)
        self.assertGreater(old / gls, 4.5)
        w1, u1, p1 = M.capture_scale(None, np.full(5, 0.6), R)                   # (unweighted: unit = phi / R)
        self.assertTrue(np.array_equal(w1, np.ones(5)) and abs(u1 - 0.1) < 1e-15 and p1 == 0.6)
        idx, data, lam = D.fit["a"], self.cap, 0.05
        m = M.fit(D, idx, data, 1, lam, False, 6, 1, var_fn=self.vf)
        qi, pj = D.qi[idx], D.pj[idx]
        g = M.predict(D, m, idx)
        Vp = self.vf(np.clip(1 / (1 + np.exp(-g)), 1e-4, 1 - 1e-4))
        zrep = data["z"][idx].var(axis=1, ddof=1)
        phi_f = float(np.mean(zrep / Vp))
        unit_f = phi_f / (6 * float(np.mean(1 / Vp)))
        self.assertAlmostEqual(m["unit"], unit_f, delta=1e-12 * unit_f)
        nS = M._noise(data["s"][idx])
        self.assertAlmostEqual(m["weights"]["survival"], unit_f / nS, delta=1e-9 * unit_f / nS)
        j = int(np.bincount(pj, minlength=D.nP).argmax())                       # (a well-connected predator)
        e = np.flatnonzero(pj == j)
        eta = m["surfC"].value(m["a"][pj[e]], m["b"][qi[e]]) + (m["u"][qi[e]] * m["v"][pj[e]]).sum(axis=1)
        _, FCa, _ = m["surfC"].value(m["a"][pj[e]], m["b"][qi[e]], grads=True)
        dg = m["link"].dG(eta)
        _, FSa, _ = m["surfS"].value(m["aS"][pj[e]], m["bS"][qi[e]], grads=True)
        Xc = np.column_stack([dg * FCa, np.zeros(len(e)), dg[:, None] * m["u"][qi[e]]])
        Xs = np.column_stack([np.zeros(len(e)), FSa, m["u"][qi[e]] @ m["DS"]])
        prec_c = 6 / (phi_f * Vp[e])                                             # (absolute precisions)
        H = (Xc.T * prec_c) @ Xc + Xs.T @ Xs / nS + np.diag([1e-3, 1e-3, lam]) / unit_f
        self.assertTrue(np.allclose(m["covP"][j], np.linalg.inv(H), rtol=1e-6, atol=1e-14))

    def test_pair_residual_inside_link(self):
        """r2 P2-2: delta_ij sits inside the link. With a NON-identity bounded link, pair_variance recovers
        tau^2 on the predictor scale (the after-link moment estimates E[G'^2] tau^2 instead); the score
        integrates G(eta + e) (a dense quadrature reference agrees); pred_var's G'(eta)^2 s2 varies with the
        location; without predictor-scale uncertainty the score is the plain count density."""
        D, M, rec = self.D, self.M, self.rec
        kn = np.linspace(-3.0, 3.0, 6)
        lk = M.Link(kn, kn + np.array([0.0, 0.5, 0.8, 0.7, 0.4, 0.0]), 0.03, 0.8)
        rng = np.random.default_rng(12)
        eta = rng.uniform(-3.0, 3.0, 60000)
        tau2, v = 0.09, 0.01
        zbar = lk.G(eta + rng.normal(0.0, np.sqrt(tau2), len(eta))) + rng.normal(0.0, np.sqrt(v), len(eta))
        dg = lk.dG(eta)
        est = M.pair_variance((zbar - lk.G(eta)) / dg, v / dg ** 2)
        self.assertAlmostEqual(est, tau2, delta=0.012)
        after = float(np.mean((zbar - lk.G(eta)) ** 2 - v))                       # (the residual after G)
        self.assertGreater(abs(after - tau2), 0.03)
        self.assertEqual(M.pair_variance(rng.normal(0, 0.1, 1000), np.full(1000, 0.04)), 0.0)   # (floored)
        m = dict(M.fit(D, D.fit["a"], self.cap, 1, 0.05, False, 4, 1, var_fn=self.vf))
        m["link"], m["pair_var"] = lk, tau2
        t = D.test_idx[:300]
        e_, s2 = M.pred_eta(D, m, t)
        loc, var = M.pred_var(D, m, t)
        rep = M._rep_var(m, loc)
        self.assertTrue(np.allclose(var - rep, lk.dG(e_) ** 2 * s2))
        self.assertGreater(float(np.std(var - rep)), 0.1 * float(np.mean(var - rep)))   # (location-dependent)
        n_ = 40
        cnt = self.cap["cnt"][t[:n_]]
        x = np.linspace(-9.0, 9.0, 16001)                                         # (the dense reference)
        wq = np.exp(-0.5 * x * x)
        wq /= wq.sum()
        for tv in (tau2, 0.0):                                       # (with the pair residual; posterior only)
            m["pair_var"] = tv
            e_, s2 = M.pred_eta(D, m, t[:n_])
            lp = M.pred_count_lpd(D, m, t[:n_], cnt, rec.B_COUNT)
            ref = []
            for i in range(n_):
                locs = lk.G(e_[i] + np.sqrt(s2[i]) * x)
                P = np.exp(M.count_logp(np.repeat(cnt[i:i + 1], len(x), axis=0), rec.B_COUNT, locs,
                                        M._rep_var(m, locs)))
                ref.append(float(np.mean(np.log(wq @ P))))
            err = np.abs(lp - np.array(ref))
            self.assertLess(float(err.max()), 3e-3, tv)
            self.assertLess(float(np.median(err)), 2e-4, tv)
            fo = M.count_lpd(cnt, rec.B_COUNT, *M.pred_var(D, m, t[:n_]))       # (first order: not enough)
            self.assertGreater(float(np.abs(fo - np.array(ref)).max()), 10 * float(err.max()))
            # r3 P2-1: a grid too coarse at the start is caught by the a-posteriori check and refined
            old, M.TRAP_H = M.TRAP_H, 6.0
            try:
                inf = {}
                lp2 = M.pred_count_lpd(D, m, t[:n_], cnt, rec.B_COUNT, info=inf)
            finally:
                M.TRAP_H = old
            if tv:
                self.assertGreater(inf["refined"], 0, tv)
            self.assertLess(float(np.abs(lp2 - np.array(ref)).max()), 3e-3, tv)
            self.assertLessEqual(inf["max_check"], M.TRAP_TOL)
        g_ = np.linspace(-6.0, 6.0, 20001)
        self.assertGreaterEqual(lk.max_slope(-6.0, 6.0), float(lk.dG(g_).max()))   # (a conservative bound)
        m0 = dict(m, pair_var=0.0, covQ=0 * m["covQ"], covP=0 * m["covP"])
        l0, v0 = M.pred_var(D, m0, t[:n_])
        self.assertTrue(np.allclose(M.pred_count_lpd(D, m0, t[:n_], cnt, rec.B_COUNT),
                                    M.count_lpd(cnt, rec.B_COUNT, l0, v0)))

    def test_count_integral_never_capped(self):
        """r3 P2-1: the review's case: identity link, eta = 0, s2 = 1, a constant replicate SD 0.003, count 162
        of 324. The exact convolution is P = 0.00493; a 513-node grid (spacing 0.027) gives about 0.0105 (0.75
        nats off). The checked grid goes as far as its rule needs (here 24,577 nodes) and matches; with no
        variance function the identity link's Gaussian convolution is exact.
        r4 P2-1: no frozen variance. The review's heteroscedastic case (identity link, s2 = 1, replicate SD 0.003
        below p = .5 and 0.012 above, count 163/324): the registered integrand at every node matches a dense
        reference, where a variance frozen at the count's 0.012 is about 0.17 nats off.
        r4 P2-2: no silent -inf. The review's tail case (identity h, lo .02, hi .8, SD 0.003, count 324/324,
        beyond the link's reach): a finite log probability, the range extended to where the integrand peaks,
        matching a dense log-space reference; a non-finite score is refused."""
        import math
        import types
        M, N = self.M, self.rec.B_COUNT
        Dx = types.SimpleNamespace(qi=np.zeros(1, int), pj=np.zeros(1, int))
        kn = np.linspace(-1.0, 1.0, 4)
        sig2 = 0.003 ** 2
        mx = {"surfC": M.Surface(kn, kn, ("inc", "dec")), "a": np.zeros(1), "b": np.zeros(1),
              "u": np.zeros((1, 0)), "v": np.zeros((1, 0)), "rank": 0, "covQ": np.zeros((1, 3, 3)),
              "covP": np.zeros((1, 2, 2)), "pair_var": 1.0, "link": M.Link(), "phi": sig2,
              "var_fn": lambda p: np.ones_like(p)}                         # (constant V, but a variance function)
        cnt = np.array([[162]])
        exact = float(M.count_lpd(cnt, N, np.zeros(1), np.array([1.0 + sig2]))[0])
        self.assertAlmostEqual(float(np.exp(exact)), 0.00493, delta=2e-5)
        inf = {}
        got = float(M.pred_count_lpd(Dx, mx, np.array([0]), cnt, N, info=inf)[0])
        self.assertAlmostEqual(got, exact, delta=1e-4)
        self.assertEqual((inf["grid"], inf["grid_unresolved"]), (1, 0))
        capped = float(M._grid_pass(mx["link"], mx, cnt, np.zeros(1), np.ones(1), N, 513, np.ones(1))[0][0, 0])
        self.assertGreater(abs(capped - exact), 0.5)                           # (what a silent cap would score)
        step_v = lambda p: np.where(p < 0.5, 0.003 ** 2, 0.012 ** 2)          # noqa: E731
        mh = dict(mx, var_fn=step_v, phi=1.0)
        c163 = np.array([[163]])
        inf = {}
        got = float(M.pred_count_lpd(Dx, mh, np.array([0]), c163, N, info=inf)[0])
        e = np.linspace(-8.0, 8.0, 1_600_001)                                  # (step 1e-5: the reference)
        lw = -0.5 * e * e
        lw -= lw.max() + np.log(np.exp(lw - lw.max()).sum())
        lp = M.count_logp(np.repeat(c163, len(e), axis=0), N, e, M._rep_var(mh, e))[:, 0]
        ref = float(np.log(np.exp(lp + lw - (lp + lw).max()).sum()) + (lp + lw).max())
        self.assertAlmostEqual(got, ref, delta=2e-3)
        self.assertEqual(inf["grid_unresolved"], 0)
        frozen = float(M.count_lpd(c163, N, np.zeros(1), np.array([1.0 + 0.012 ** 2]))[0])
        self.assertGreater(abs(frozen - ref), 0.1)                             # (the frozen variance's error)
        mt = dict(mx, link=M.Link(None, None, 0.02, 0.8))
        c324 = np.array([[324]])
        inf = {}
        got = float(M.pred_count_lpd(Dx, mt, np.array([0]), c324, N, info=inf)[0])
        self.assertTrue(np.isfinite(got) and got < -1e5)
        self.assertGreater(inf["extended"], 0)
        e = np.linspace(-30.0, 30.0, 600_001)
        lw = -0.5 * e * e - 0.5 * math.log(2 * math.pi) + math.log(e[1] - e[0])
        terms = M.count_logp(np.repeat(c324, len(e), axis=0), N, mt["link"].G(e),
                             M._rep_var(mt, mt["link"].G(e)))[:, 0] + lw
        ref = float(terms.max() + np.log(np.exp(terms - terms.max()).sum()))
        self.assertAlmostEqual(got, ref, delta=1e-2)
        self.assertGreater(float(e[np.argmax(terms)]), 7.0)                    # (beyond the first +-7 SD range)
        mn = dict(mx, var_fn=lambda p: np.full_like(p, np.nan))
        with self.assertRaisesRegex(ValueError, "non-finite"):
            M.pred_count_lpd(Dx, mn, np.array([0]), cnt, N)
        my = dict(mx, var_fn=None)                                             # (the exact convolution case)
        inf = {}
        self.assertAlmostEqual(float(M.pred_count_lpd(Dx, my, np.array([0]), cnt, N, info=inf)[0]), exact, places=12)
        self.assertEqual(inf["exact"], 1)
        # the r3 smoke's pair: predictor SD 1.646 with the x1.5 capture-noise variance function (its SD varies
        # 0.23-0.9 along e). It needs more than 513 nodes; the larger grids resolve it against a dense reference
        vf = self.rec.var_model(self.rec.SCENARIOS["r2_017_cap15"])
        mz = dict(mx, var_fn=vf, phi=1.0, pair_var=1.646 ** 2)
        cz = np.array([[75, 111, 125, 137, 49, 87]])
        inf = {}
        got = M.pred_count_lpd(Dx, mz, np.array([0]), cz, N, info=inf)
        x = np.linspace(-9.0, 9.0, 200001)
        wq = np.exp(-0.5 * x * x)
        wq /= wq.sum()
        loc = 1.646 * x
        P = np.exp(M.count_logp(np.repeat(cz, len(x), axis=0), N, loc, M._rep_var(mz, loc)))
        ref = float(np.mean(np.log(wq @ P)))
        self.assertAlmostEqual(float(got[0]), ref, delta=2e-3)
        self.assertEqual((inf["grid_unresolved"], inf["grid"]), (0, 1))

    def test_unresolved_scores_flagged_and_beyond_rule_extended(self):
        """r5 P2-1: the review's case (identity G, eta = 0, predictor SD 1000, a constant callable replicate SD
        0.003, count 162/324): unresolved at the largest grid (spacing ~0.053, only the central node counts), yet
        FINITE and about 1.4 nats above the exact convolution -- so it is flagged (grid_unresolved), and the
        recovery scorer reports the flag to its callers. r5 P2-2: the bounded-link tail case with replicate SD
        0.0003: the initial rule needs 239,318 nodes (within the cap), the extended range more than 478,000:
        beyond_rule counts the pair once."""
        import math
        import types
        M, N = self.M, self.rec.B_COUNT
        Dx = types.SimpleNamespace(qi=np.zeros(1, int), pj=np.zeros(1, int))
        kn = np.linspace(-1.0, 1.0, 4)

        def model(sd_rep, sd_pred, link=None):
            return {"surfC": M.Surface(kn, kn, ("inc", "dec")), "a": np.zeros(1), "b": np.zeros(1),
                    "u": np.zeros((1, 0)), "v": np.zeros((1, 0)), "rank": 0, "covQ": np.zeros((1, 3, 3)),
                    "covP": np.zeros((1, 2, 2)), "pair_var": sd_pred ** 2, "link": link or M.Link(),
                    "phi": sd_rep ** 2, "var_fn": lambda p: np.ones_like(p)}
        cnt = np.array([[162]])
        mu = model(0.003, 1000.0)
        exact = float(M.count_lpd(cnt, N, np.zeros(1), np.array([1000.0 ** 2 + 0.003 ** 2]))[0])
        inf = {}
        got = float(M.pred_count_lpd(Dx, mu, np.array([0]), cnt, N, info=inf)[0])
        self.assertTrue(np.isfinite(got))
        self.assertGreater(got - exact, 1.0)                                   # (about 1.4 nats too high)
        self.assertLess(got - exact, 1.8)
        self.assertEqual((inf["grid_unresolved"], inf["grid"]), (1, 0))
        z = np.zeros((1, 1))
        info = {}
        self.rec.scorer(Dx, {"cnt": cnt, "z": z}, mu, np.array([0]), "registered")(np.array([0]), info)
        self.assertEqual(info["grid_unresolved"], 1)                           # (the scorer surfaces it)
        lk = M.Link(None, None, 0.02, 0.8)
        mt = model(0.0003, 1.0, lk)
        gmax = max(lk.max_slope(-M.TRAP_SD, M.TRAP_SD), 1e-12)
        smin = math.sqrt(float(M._rep_var(mt, M.VMIN_GRID).min()))
        need0 = math.ceil(2 * M.TRAP_SD / min(1.0, M.TRAP_H * smin / gmax)) + 1
        self.assertEqual(need0, 239318)
        self.assertLessEqual(need0, M.TRAP_KS[-1])                             # (the initial rule is within the cap)
        self.assertGreater(2 * need0, M.TRAP_KS[-1])                           # (the extended range's rule is not)
        inf = {}
        got = float(M.pred_count_lpd(Dx, mt, np.array([0]), np.array([[324]]), N, info=inf)[0])
        self.assertTrue(np.isfinite(got))
        self.assertGreater(inf["extended"], 0)
        self.assertEqual(inf["beyond_rule"], 1)                                # (once, not per extension)
        self.assertEqual(inf["grid_unresolved"], 0)
        ms = model(0.003, 1.0, lk)                                             # (rule within the cap in every range)
        inf = {}
        M.pred_count_lpd(Dx, ms, np.array([0]), np.array([[324]]), N, info=inf)
        self.assertEqual((inf["beyond_rule"], inf["grid_unresolved"]), (0, 0))
        self.assertGreater(inf["extended"], 0)

    def test_pair_variance_safeguarded(self):
        """r3 P2-2: the review's cycle. One cell (s2 0.01, r^2 1.01) and 100 cells (s2 1, r^2 0): the fixed point
        alternates 0.980 <-> 0 from 0 (it returned 0); the safeguarded solve finds the likelihood root 0.0896."""
        M = self.M
        r = np.concatenate([[np.sqrt(1.01)], np.zeros(100)])
        s2 = np.concatenate([[0.01], np.ones(100)])
        t, cyc = 0.0, []
        for _ in range(6):                                                     # (the old fixed point)
            w = 1.0 / (t + s2) ** 2
            t = max(0.0, float(np.sum(w * (r ** 2 - s2)) / np.sum(w)))
            cyc.append(round(t, 4))
        self.assertEqual(cyc[:4], [0.9802, 0.0, 0.9802, 0.0])
        out = M.pair_variance(r, s2, full=True)
        self.assertAlmostEqual(out["tau2"], 0.0896, delta=2e-4)
        self.assertTrue(out["converged"] and abs(out["score"]) < 1e-4)
        self.assertEqual(M.pair_variance(r, s2), out["tau2"])
        self.assertEqual(M.pair_variance(np.zeros(5), np.ones(5)), 0.0)      # (no excess: the floor)

    def test_world_deviation_var_unequal_cells(self):
        """r3 P2-3: unequal heteroscedastic cells. Two worlds in one lag bin, cells (n 2, variance 0.06) and (n 50,
        variance 0.00375), means +0.2 / -0.2: var of the means 0.08 minus the cells' own noise mean(0.06/2,
        0.00375/50) = 0.0150375 gives 0.0649625; the pooled rule (pooled variance x mean(1/n) = 0.0012675) gave
        0.0787325. Supplied row variances give the same."""
        M = self.M
        a = np.sqrt(0.03)
        z = np.random.default_rng(3).normal(size=50)
        z = (z - z.mean()) / z.std(ddof=1)
        e = np.concatenate([[0.2 + a, 0.2 - a], -0.2 + np.sqrt(0.00375) * z])
        lw = np.concatenate([np.zeros(2, int), np.ones(50, int)])
        lb = np.zeros(52, int)
        tau, ok, raw = M.world_deviation_var(e, lb, lw, 1)
        self.assertAlmostEqual(float(raw[0]), 0.08 - 0.0150375, places=12)
        self.assertTrue(ok[0] and tau[0] == raw[0])
        rv = np.concatenate([np.full(2, 0.06), np.full(50, 0.00375)])
        self.assertAlmostEqual(float(M.world_deviation_var(e, lb, lw, 1, row_var=rv)[2][0]), 0.08 - 0.0150375,
                               places=12)
        self.assertGreater(abs(float(raw[0]) - (0.08 - 0.0012675)), 0.01)

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
            # (r2 P3: EVERY solve counted: the warm start's surfaces, both surfaces each sweep, and each link
            #  update's 2 x LINK_STEPS Gauss-Newton QPs)
            want = 6 + 1 + 6 + (1 if kw.get("embedding") else 0) + (6 // M.LINK_EVERY) * 2 * M.LINK_STEPS
            self.assertEqual(m["qp"]["solves"], want, kw)
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
        V = self.vf(np.clip(1 / (1 + np.exp(-g)), 1e-4, 1 - 1e-4))
        zrep = data["z"][idx].var(axis=1, ddof=1)
        unit = float(np.mean(zrep / V)) / (data["z"].shape[1] * float(np.mean(1.0 / V)))   # (phi / (R mean 1/V))
        self.assertAlmostEqual(unit, m["unit"], delta=1e-12 * unit)
        ctrl = M.control_access(D, idx)
        wS = unit / M._noise(data["s"][idx])            # (every row's weight in the one absolute unit)
        wS0 = unit / M._noise(data["s0"][ctrl])
        wC0 = unit / m["controls"]["prior_var"]
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
        eta, s2 = M.pred_eta(D, best, D.val_idx)
        self.assertTrue((s2 >= best["pair_var"]).all() and float(s2.max()) > best["pair_var"])
        self.assertTrue(np.allclose(var, rep + best["link"].dG(eta) ** 2 * s2))   # (s2 enters through the link)
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


# ------------------------------------------------------------------ map.py in bank mode (A_design_v5.md 3.3)
# Red Queen recovery option A, work package 2: tests T6-2, T6-7, T6-8, T6-10, T6-11 of A_design_v5 section 5 (and
# T6-1's map.fit clause). Synthetic only (D9): fitter tables from synthetic curves, counts drawn from the law here.
import math  # noqa: E402
from unittest import mock  # noqa: E402

# The T6-10 REFERENCE INTEGRATOR (A_design_v5 T6-10 and PC-25, frozen; its refinement amended by A_design_v5
# clarification 2, D2). It shares no code with the scorer (map.pred_count_lpd, _grid_pass, _score_law, _tail_ok,
# _log_2sf, _interval_logp, noisebank): its own upper-tail function, interval probabilities, thresholds, link and table
# interpolation (numpy's interp). Budget: tail <= 1e-10 relative (rigorous), quadrature <= 1e-9 in log (the halving
# certificate: evidence, not a bound), total about 1.1e-9.
REF_TAIL = 1e-10            # the tail budget (v5; v4's 1e-6 is the negative control of T6-11)
REF_TAIL_V4 = 1e-6
REF_SPACING = 5e-5          # the first node spacing, prior SDs (400,001 nodes over +-10 SD, more as the range extends)
REF_START = 10.0            # the first range: +-10 SD
REF_STEP = 2.0              # each extension: 2 SD per side
REF_CAP = 60.0              # beyond +-60 SD a case is refused as unrepresentable
REF_CERT = 1e-9             # the certificate: two consecutive estimates within this (log units)
REF_HALVINGS = 4            # clarification 2 D2: at most four halvings (final spacing >= 3.125e-6 SD)
REF_CHUNK = 1 << 21         # (nodes evaluated per chunk when the spacing is halved)
REF_SF_SWITCH = 25.0        # the log upper tail: math.erfc below, the Laplace continued fraction at and above
REF_CF_TERMS = 60
_REF_LOG_SQRT2PI = 0.5 * math.log(2.0 * math.pi)
_REF_ERFC = []


def ref_log_sf(x):
    """log P(Z > x) for a standard normal Z, elementwise: log(erfc(x / sqrt 2) / 2) with math.erfc below 25, and at
    and above 25, -x^2/2 - log sqrt(2 pi) - log(x + 1/(x + 2/(x + 3/(x + ...)))) (Laplace's continued fraction, 60
    terms), so a far tail never underflows."""
    if not _REF_ERFC:
        _REF_ERFC.append(np.frompyfunc(math.erfc, 1, 1))
    x = np.asarray(x, float)
    out = np.empty(x.shape)
    lo = x < REF_SF_SWITCH
    if lo.any():
        xl = x[lo] / math.sqrt(2.0)
        e = np.empty(xl.shape)
        for k in range(0, xl.size, 1 << 20):
            e[k:k + (1 << 20)] = _REF_ERFC[0](xl[k:k + (1 << 20)]).astype(float)
        out[lo] = np.log(0.5 * e)
    hi = ~lo
    if hi.any():
        xh = x[hi]
        t = np.zeros(xh.shape)
        for k in range(REF_CF_TERMS, 0, -1):
            t = k / (xh + t)
        out[hi] = -0.5 * xh * xh - _REF_LOG_SQRT2PI - np.log(xh + t)
    return out


def ref_log_iprob(u1, u2):
    """log(Phi(u2) - Phi(u1)) for u1 < u2 (infinite ends allowed), from upper tails S only: both ends at or above 0
    -> S(u1) - S(u2); both at or below 0 -> S(-u2) - S(-u1); straddling 0 -> 1 - S(-u1) - S(u2)."""
    u1, u2 = np.broadcast_arrays(np.asarray(u1, float), np.asarray(u2, float))
    out = np.empty(u1.shape)
    up = u1 >= 0.0
    dn = u2 <= 0.0
    mid = ~(up | dn)
    for sel, a_, b_ in ((up, u1, u2), (dn, -u2, -u1)):
        if sel.any():
            la, lb = ref_log_sf(a_[sel]), ref_log_sf(b_[sel])
            out[sel] = la + np.log(-np.expm1(lb - la))
    if mid.any():
        out[mid] = np.log1p(-(np.exp(ref_log_sf(-u1[mid])) + np.exp(ref_log_sf(u2[mid]))))
    return out


def ref_count_logp(k, loc, var, B):
    """log P(K = k) of a capture count (scale = ceiling = B; Annex H.9.2's rounded logit-normal: the latent interval
    [logit((k - 1/2)/B), logit((k + 1/2)/B)), open at 0 and B) at latent locations loc and variances var."""
    sd = np.sqrt(np.asarray(var, float))
    lo = -math.inf if k == 0 else math.log((k - 0.5) / (B - k + 0.5))
    hi = math.inf if k == B else math.log((k + 0.5) / (B - k - 0.5))
    return ref_log_iprob((lo - loc) / sd, (hi - loc) / sd)


def ref_log_integral(loglik, sigma, tail=REF_TAIL, start=REF_START, cap=REF_CAP, halvings=REF_HALVINGS):
    """log of the integral of N(e; 0, sigma^2) L(e) de for a likelihood 0 <= L <= 1 given as loglik(e) = log L(e)
    (vectorized), by the frozen rule of A_design_v5 T6-10: the log-sum-exp trapezoid on nodes e = i h, exact integer
    multiples of h = 5e-5 sigma, over [-b, b], b = 10 sigma at first and extended symmetrically by 2 sigma until
    log(2 S(b / sigma)) <= log(tail) + log I^ (I^ the integral over the current range; rigorous because L <= 1: the
    omitted part is at most 2 S(b / sigma)); refused (ValueError) beyond +-60 sigma. Then (A_design_v5 clarification 2,
    D2, which replaces v5's single halving) the spacing is halved until two consecutive estimates differ by at most
    REF_CERT in log, at most `halvings` times (four: final spacing >= 3.125e-6 sigma); the finer of the last two is the
    reference and their |difference| its certificate (certified: <= REF_CERT); the tail criterion is re-asserted with
    the final estimate (fine_bound_ok). A case not certified is returned with certified False, for the caller to fail.
    -> {log_I, coarse (the estimate at 5e-5 sigma), estimates [(spacing in sigma units, log I^) per spacing],
    halvings, spacing (the final one, in sigma units), certificate, certified, b (in SD), trace [(b, log bound, log I^,
    stopped) per range step], fine_bound_ok}."""
    h = REF_SPACING * sigma
    lnorm = -math.log(sigma) - _REF_LOG_SQRT2PI

    def logf(e):
        return loglik(e) - 0.5 * (e / sigma) ** 2 + lnorm

    def trap(lf, hh):
        t = lf.copy()
        t[0] += math.log(0.5)
        t[-1] += math.log(0.5)
        mx = float(np.max(t))
        if not math.isfinite(mx):
            return mx
        return mx + math.log(float(np.sum(np.exp(t - mx)))) + math.log(hh)

    n, step, ncap = int(round(start / REF_SPACING)), int(round(REF_STEP / REF_SPACING)), int(round(cap / REF_SPACING))
    lf = logf(np.arange(-n, n + 1) * h)
    trace = []
    while True:
        log_i = trap(lf, h)
        b = n * REF_SPACING
        bound = math.log(2.0) + float(ref_log_sf(np.array([b]))[0])
        stop = bound <= math.log(tail) + log_i
        trace.append((b, bound, log_i, bool(stop)))
        if stop:
            break
        if n + step > ncap:
            raise ValueError(f"reference: the tail bound still fails at +-{b:g} SD (cap {cap:g}): unrepresentable")
        lf = np.concatenate([logf(np.arange(-n - step, -n) * h), lf, logf(np.arange(n + 1, n + step + 1) * h)])
        n += step
    ests = [(REF_SPACING, log_i)]
    for j in range(1, halvings + 1):          # (halve: the old nodes stay, the midpoints are new; all exact multiples)
        hj = h / 2.0 ** j
        nj = n * 2 ** j
        lf2 = np.empty(2 * nj + 1)
        lf2[0::2] = lf
        odd = np.arange(-nj + 1, nj, 2)
        new = np.empty(len(odd))
        for k in range(0, len(odd), REF_CHUNK):
            new[k:k + REF_CHUNK] = logf(odd[k:k + REF_CHUNK] * hj)
        lf2[1::2] = new
        lf = lf2
        ests.append((REF_SPACING / 2.0 ** j, trap(lf, hj)))
        if abs(ests[-1][1] - ests[-2][1]) <= REF_CERT:
            break
    final, cert = ests[-1][1], abs(ests[-1][1] - ests[-2][1])
    return {"log_I": final, "coarse": log_i, "estimates": ests, "halvings": len(ests) - 1, "spacing": ests[-1][0],
            "certificate": cert, "certified": bool(cert <= REF_CERT), "b": b, "trace": trace,
            "fine_bound_ok": bool(trace[-1][1] <= math.log(tail) + final)}


def ref_link(knots=None, theta=None, lo=0.0, hi=1.0):
    """The reference's own link G(eta) = logit(lo + (hi - lo) sigma(h(eta))), h the linear spline through (knots,
    theta) extended linearly beyond the end knots (knots None: the identity); no code shared with map.Link."""
    if knots is None:
        def hfun(e):
            return np.asarray(e, float)
    else:
        kn, th = np.asarray(knots, float), np.asarray(theta, float)

        def hfun(e):
            e = np.asarray(e, float)
            i = np.clip(np.searchsorted(kn, e, side="right") - 1, 0, len(kn) - 2)
            return th[i] + (e - kn[i]) * (th[i + 1] - th[i]) / (kn[i + 1] - kn[i])
    if lo == 0.0 and hi == 1.0:
        return hfun

    def G(e):
        hv = hfun(e)
        with np.errstate(over="ignore"):
            s, sc = 1.0 / (1.0 + np.exp(-hv)), 1.0 / (1.0 + np.exp(hv))
        return np.log(lo + (hi - lo) * s) - np.log((1.0 - hi) + (hi - lo) * sc)
    return G


# The main-branch code the hook-unset tests compare with byte for byte: map.py lines 530-547 and 951-1088 at main
# (@4991907 = @1555de5 = @dc64646, identical), verbatim (capture_scale; the scorer's constants, _logsumexp,
# _grid_pass, pred_count_lpd), executed against map.py's own unchanged helpers.
MAIN_CAPTURE_SCALE = '''
UNIT_FLOOR = 1e-6                       # (the absolute unit's floor: noiseless data)


def capture_scale(V, zrep, R):
    """The capture rows' working weights and their ABSOLUTE scale under the registered predictive model
    (Codex #66 r2 P2-1). Cell e's replicate-mean variance is v_e = phi V_e / R, with phi = mean(zrep / V)
    the replicate dispersion of the variance function V (zrep: the cells' replicate variances). The weights
    are w_e = (1 / V_e) / mean(1 / V) (mean 1, so the penalties keep their meaning), and one weight unit is
    unit = phi / (R mean(1 / V)), so unit / w_e = v_e exactly: a weighted Hessian times unit is the absolute
    covariance. V None (unweighted): w = 1, phi = mean(zrep), unit = phi / R. -> (w, unit, phi)."""
    zrep = np.asarray(zrep, float)
    if V is None:
        phi = float(np.mean(zrep))
        return np.ones(len(zrep)), max(phi / R, UNIT_FLOOR), phi
    V = np.maximum(np.asarray(V, float), 1e-8)
    M = float(np.mean(1.0 / V))
    phi = float(np.mean(zrep / V))
    return (1.0 / V) / M, max(phi / (R * M), UNIT_FLOOR), phi
'''

MAIN_SCORER = '''
TRAP_H = 0.25                            # (the grid step, in units of the narrowest replicate SD / steepest slope)
TRAP_SD = 7.0                            # (the grid covers +-TRAP_SD prior SDs)
TRAP_KS = (15, 23, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193,
           12289, 16385, 24577, 32769, 49153, 65537, 98305, 131073, 196609, 262145)   # (grid sizes: bucketed)
TRAP_CELLS = 1_000_000                   # (pairs x replicates x nodes per vectorized chunk)
TRAP_TOL = 1e-3                          # (the a-posteriori check, log units: full grid vs every other node)
TRAP_SPAN_MAX = 8                        # (the range may double up to +-TRAP_SD x 8 = +-56 prior SDs)
TRAP_EDGE = math.log(1e-10)              # (an end node's share of the integral above this: the range is extended)
VMIN_GRID = np.linspace(-20.0, 20.0, 20001)    # (the logit grid on which the variance function's minimum is taken)


def _logsumexp(a, axis):
    mx = np.max(a, axis=axis, keepdims=True)
    mx = np.where(np.isfinite(mx), mx, 0.0)
    with np.errstate(divide="ignore"):
        return np.squeeze(mx, axis=axis) + np.log(np.sum(np.exp(a - mx), axis=axis))


def _grid_pass(lk, m, cnt, eta, sd, N, K, span):
    """The e-order trapezoid, in log space, on K nodes over +-TRAP_SD x span prior SDs (span per pair), the same
    on every other node (the check), and the larger end node's log share of the integral (the range check) ->
    (log P, log P on the half grid, edge share), pairs x replicates. The integrand is the registered one at every
    node: the bounded count probability with the replicate variance phi V(G(eta + e)) at that node."""
    x = np.linspace(-1.0, 1.0, K)[None, :] * (TRAP_SD * span)[:, None]                      # (pairs x nodes, SDs)
    lw = -0.5 * x * x
    lwh = lw[:, ::2] - _logsumexp(lw[:, ::2], 1)[:, None]
    lw = lw - _logsumexp(lw, 1)[:, None]
    loc = lk.G(eta[:, None] + sd[:, None] * x)
    lp = _interval_logp(cnt[:, :, None], N, loc[:, None, :], _rep_var(m, loc)[:, None, :])
    terms = lp + lw[:, None, :]
    full = _logsumexp(terms, 2)
    with np.errstate(invalid="ignore"):
        edge = np.maximum(terms[..., 0], terms[..., -1]) - full
    return full, _logsumexp(lp[..., ::2] + lwh[:, None, :], 2), edge


def pred_count_lpd(D, m, idx, cnt, N, own=None, info=None):
    """THE registered score (v4 §7.6) of the capture head on pairs idx: the capture-count log predictive
    density per replicate observation, with the predictor-scale uncertainty (pred_eta: the posterior variance
    of eta and the pair residual delta_ij, both INSIDE the link) integrated through the link:
        P(K = k) = E_e[P(k | G(eta + e), phi V(G(eta + e)))],  e ~ N(0, s2),
    each P from Annex H.9.2's bounded model with the fresh replicate's variance (count_logp). Per observation
    (the marginal score: the mixture is not shared across a pair's replicates). -> one value per pair.
    THE INTEGRAL, by case (Codex #66 r3 P2-1, r4 P2-1/2: never silently capped, never a frozen variance,
    never a silent non-finite value):
      - s2 = 0: the plain density;
      - the identity link with a constant replicate variance (no var_fn): EXACT, Y ~ N(eta, phi + s2);
      - otherwise the e-order trapezoid IN LOG SPACE with the registered integrand at every node (the bounded
        count probability at the replicate variance phi V(G(eta + e)) of that node; the far tails of the
        interval probability are log-space continued fractions, so a count beyond the link's reach is a finite,
        very negative log probability). The grid covers +-TRAP_SD prior SDs; its step is at most one SD and at
        most TRAP_H x the narrowest replicate SD (the variance function's minimum on VMIN_GRID) / a
        CONSERVATIVE bound on the link's slope over the range (Link.max_slope), on the smallest of TRAP_KS
        (15 .. 262,145 nodes) that achieves it. Every observation is CHECKED a posteriori:
          * resolution: against the same grid's every other node; above TRAP_TOL its pair moves to the next grid;
          * range: if an end node carries more than 1e-10 of the integral (the integrand still rises at the edge,
            e.g. a count beyond the link's asymptote), the pair's range doubles, up to +-56 SDs;
        a pair failing a check on the largest grid or range keeps that value and is counted as grid_unresolved
        (a finite but UNRESOLVED score: reported, never hidden, and the callers' comparisons (recovery.py) refuse
        to decide on it); a pair whose rule needs more than the largest grid, in its initial range or in an
        extended one (Codex #66 r5 P2-2), is computed there, checked, and counted ONCE in beyond_rule.
      - any non-finite result is REFUSED (ValueError): it never reaches a model comparison.
    info (a dict): the counts per case are added to it (pairs, plain, exact, grid, refined, extended,
    beyond_rule, grid_unresolved) with the largest accepted check difference (max_check)."""
    eta, s2 = pred_eta(D, m, idx, own)
    lk = m["link"]
    cnt = np.asarray(cnt)
    out = np.empty(len(eta))
    sd = np.sqrt(s2)
    st = {"pairs": int(len(eta)), "plain": 0, "exact": 0, "grid": 0, "refined": 0, "extended": 0, "beyond_rule": 0,
          "grid_unresolved": 0, "max_check": 0.0}
    plain = sd <= 1e-9
    if plain.any():
        g0 = lk.G(eta[plain])
        out[plain] = count_lpd(cnt[plain], N, g0, _rep_var(m, g0))
        st["plain"] = int(plain.sum())
    q = np.flatnonzero(~plain)
    if len(q) and lk.identity() and m.get("var_fn") is None:
        out[q] = count_lpd(cnt[q], N, eta[q], m["phi"] + s2[q])
        st["exact"] = int(len(q))
    elif len(q):
        R = cnt.shape[1]
        lo_, hi_ = float((eta[q] - TRAP_SD * sd[q]).min()), float((eta[q] + TRAP_SD * sd[q]).max())
        gmax = max(lk.max_slope(lo_, hi_), 1e-12)
        smin = math.sqrt(max(float(_rep_var(m, VMIN_GRID).min()), 1e-300))
        h = np.minimum(sd[q], TRAP_H * smin / gmax)
        need0 = np.ceil(2 * TRAP_SD * sd[q] / np.maximum(h, 1e-300)) + 1          # (nodes at span 1)
        top = len(TRAP_KS) - 1
        bucket = np.searchsorted(TRAP_KS, need0)
        beyond = np.zeros(len(eta), bool)                         # (pairs whose rule exceeded the largest grid, once)
        beyond[q[bucket > top]] = True
        cur, cb, cs, n0 = q, np.minimum(bucket, top), np.ones(len(q)), need0
        while len(cur):
            nxt = []
            for b, s_ in sorted(set(zip(cb.tolist(), cs.tolist()))):
                sel = (cb == b) & (cs == s_)
                rows, need_r = cur[sel], n0[sel]
                Kb = TRAP_KS[int(b)]
                step = max(1, TRAP_CELLS // (R * Kb))
                for k0 in range(0, len(rows), step):
                    r_, nr_ = rows[k0:k0 + step], need_r[k0:k0 + step]
                    full, half, edge = _grid_pass(lk, m, cnt[r_], eta[r_], sd[r_], N, Kb, np.full(len(r_), s_))
                    with np.errstate(invalid="ignore"):
                        err = np.max(np.abs(full - half), axis=1)
                        res_ok = err <= TRAP_TOL                                   # (NaN: not ok)
                        edge_ok = np.all(edge <= TRAP_EDGE, axis=1)
                    fin = np.isfinite(full).all(axis=1)
                    ok = res_ok & edge_ok & fin
                    out[r_[ok]] = full[ok].mean(axis=1)
                    st["grid"] += int(ok.sum())
                    if ok.any():
                        st["max_check"] = max(st["max_check"], float(err[ok].max()))
                    for i in np.flatnonzero(~ok):
                        if fin[i] and not edge_ok[i] and s_ < TRAP_SPAN_MAX:          # (extend the range)
                            s2_ = 2 * s_
                            nb2 = max(int(b), int(np.searchsorted(TRAP_KS, nr_[i] * s2_)))
                            if nb2 > top:                                     # (the extended range's rule is beyond
                                beyond[r_[i]] = True                          #  the cap: counted, Codex #66 r5 P2-2)
                            nxt.append((r_[i], min(nb2, top), s2_, nr_[i]))
                            st["extended"] += 1
                        elif fin[i] and not res_ok[i] and b < top:                    # (refine the grid)
                            nxt.append((r_[i], int(b) + 1, s_, nr_[i]))
                            st["refined"] += 1
                        else:                                                        # (kept, flagged)
                            out[r_[i]] = full[i].mean()
                            st["grid_unresolved"] += 1
            cur = np.array([t[0] for t in nxt], int)
            cb = np.array([t[1] for t in nxt], int)
            cs = np.array([t[2] for t in nxt], float)
            n0 = np.array([t[3] for t in nxt], float)
        st["beyond_rule"] = int(beyond.sum())
    bad = ~np.isfinite(out)
    if bad.any():
        raise ValueError(f"pred_count_lpd: {int(bad.sum())} non-finite count scores: refused (never compared)")
    if info is not None:
        for k, v in st.items():
            info[k] = max(info.get(k, 0.0), v) if k == "max_check" else info.get(k, 0) + v
    return out
'''


def main_map():
    """main's capture_scale and scorer (MAIN_CAPTURE_SCALE, MAIN_SCORER) in a namespace over map.py's helpers."""
    import map as mapfit
    ns = dict(vars(mapfit))
    exec(compile(MAIN_CAPTURE_SCALE + "\n\n" + MAIN_SCORER, "map.py@main", "exec"), ns)
    return ns


VAL_SC = {"x": [-2.2, -0.6, 0.4], "s": [0.55, 0.30, 0.20]}      # A_design_v5 2.10's steep validation curve
CONST_SC = {"x": [0.0], "s": [0.2]}                             # T6-10's mandatory case: S_C = 0.2
T610_FRACS = (0.002, 0.01, 0.1, 0.5, 0.9, 0.99, 0.998)          # predicted capture fractions (T6-10: 0.002-0.998)
T610_SDS = (0.05, 0.3, 0.5, 1.0)                                # predictor SDs (T6-10: 0.05-1.0)
# Unrepresentable by v5's rule (the reference's tail bound still fails at +-60 SD): not T6-10 cases.
T610_UNREPRESENTABLE = {("val", 0.998, 0.05, 0), ("const", 0.998, 0.05, 0), ("const", 0.002, 0.05, 324)}
# The RANGE GAP (Codex WP2 review P1; closed by A_design_v5 clarification 2, D1): the steep curve's k = B at low
# predicted fractions. The integrand is bimodal -- an interior mode inside the first +-7 SD range, the dominant mode at
# +10..+15 SD -- and main's end-node check alone (TRAP_EDGE, an end node's share of the integral over the CURRENT range)
# never extends the range: at a4227b6 the score was wrong by 9.6-83 nats with no grid_unresolved flag. With the score
# law the tail bound (map._tail_ok) extends these ranges; the cases are part of T6-10's ordinary agreement set
# (t610_cases) and must record an extension (test_T6_10_gap_diagnosis, test_T6_10_gap_cases_agree).
T610_GAP = {("val", 0.002, 1.0, 324), ("val", 0.01, 1.0, 324), ("val", 0.1, 0.5, 324)}
# The reference's certificate (Codex WP2 review P2; clarification 2, D2): the score-law integrand is only piecewise
# smooth (the fitter table's kinks, segment slopes up to ~79), so one halving of 5e-5 SD left O(h^2) differences up to
# ~2.4e-8 on rare counts (the mandatory case 4.5e-9); the reference now halves until two consecutive estimates agree
# within 1e-9, at most four times, and a case not certified fails T6-10 with its diagnostics (never excluded).
# Codex's coverage gap (the controller's recomputation on a SECOND extension, with a changing non-identity link slope):
# (link knots, values, lo, hi), predicted fraction, SD, count -- two cases needing two range extensions on the steep
# curve (test_T6_10_second_extension_recomputes_on_a_nonidentity_link).
T610_TWO_EXT = [(((-8.0, -4.0, 4.0, 8.0), (-8.0, -6.0, -2.0, 8.0), 0.0, 1.0), 0.01, 0.2, 324),   # (slope 0.5, then 2.5)
                (((-12.0, -3.0, 3.0, 12.0), (-12.0, -1.0, 1.0, 12.0), 0.0, 1.0), 0.1, 0.2, 324)]
_BANK = {}
_T610_REF = {}


@unittest.skipIf(np is None, "numpy is not installed (set RQ_PYLIB, or RQ_REQUIRE_NUMPY=1 to require it)")
class TestMapBankMode(unittest.TestCase):
    """map.py in bank mode (Red Queen recovery option A, A_design_v5.md section 3.3, with clarification 2): the nu0
    shrinkage of capture_scale (T6-2) and its domain (overflow-safe form, refusals: D3), the working coordinate and nu0
    in it (T6-7), the score law (T6-8), the integrated score with the hook, its grid rule (per-pair H^max, recomputed
    on every range extension) and its range rule (the end-node check and the tail bound: D1) against the reference
    integrator, which halves until certified (T6-10, D2), the reference's self-test (T6-11), and the refusal of a
    variance model without a var_fn (T6-1's map.fit clause). With the hooks unset, capture_scale and the scorer are
    main's byte for byte."""

    @classmethod
    def setUpClass(cls):
        import map as mapfit
        import noisescale
        import obslaw
        import recovery
        cls.M, cls.ol, cls.rec, cls.nsc = mapfit, obslaw, recovery, noisescale
        cls.B = recovery.B_COUNT
        if not _BANK:
            _BANK["val"] = obslaw.build_fitter_table(VAL_SC, "0" * 64)
            _BANK["const"] = obslaw.build_fitter_table(CONST_SC, "0" * 64)
        cls.tabs = dict(_BANK)
        cls.tab = _BANK["val"]

    def hooks(self, tab, tag="wp2"):
        return self.ol.WorkingVariance(tab, tag), self.ol.ScoreLaw(tab, tag)

    def score(self, m, eta, s2, cnt, ns=None):
        """pred_count_lpd at given predictors (eta, s2) per pair (pred_eta replaced) -> (scores, info); ns: main's."""
        eta, s2 = np.asarray(eta, float), np.asarray(s2, float)

        def fake(D, m_, idx, own=None):
            return eta[idx], s2[idx]
        info = {}
        idx = np.arange(len(eta))
        if ns is None:
            with mock.patch.object(self.M, "pred_eta", fake):
                out = self.M.pred_count_lpd(None, m, idx, np.asarray(cnt), self.B, info=info)
        else:
            ns["pred_eta"] = fake
            out = ns["pred_count_lpd"](None, m, idx, np.asarray(cnt), self.B, info=info)
        return out, info

    def assert_main_bytes(self, cases):
        """Each case (m, eta, s2, cnt) has no score law: pred_count_lpd equals main's byte for byte, info included."""
        ns = main_map()
        for m, eta, s2, cnt in cases:
            self.assertIsNone(m.get("score_law"))
            got, info = self.score(m, eta, s2, cnt)
            want, info0 = self.score(m, eta, s2, cnt, ns=ns)
            self.assertEqual(got.tobytes(), want.tobytes())
            self.assertEqual(info, info0)

    def zmu(self, tab, mu):
        """The table's m_z at the fraction mu (its x -> m_z interpolant)."""
        return float(np.interp(math.log(mu / (1.0 - mu)), tab.x, tab.m))

    # ---------------------------------------------------------------- T6-1 (map.fit's clause), T6-2
    def test_T6_1_map_fit_refuses_a_variance_model_without_var_fn(self):
        """T6-1's map.fit clause (A_design_v5 3.3; the spy across candidates and procedures is recovery's, WP4): a
        rep_prior or score_law given with var_fn None is refused before D, idx or data is read (a numerical fit can
        never carry a variance model), also through fit_best; a malformed rep_prior or a score law without its
        frozen table is refused; the scorer refuses a score law without a var_fn."""
        M = self.M
        W, SL = self.hooks(self.tab)
        for kw in ({"rep_prior": {"nu0": 4.0}}, {"score_law": SL}, {"rep_prior": {"nu0": None}, "score_law": SL},
                   {"rep_prior": {"nu0": None}}):
            with self.assertRaisesRegex(ValueError, "without a var_fn"):
                M.fit(None, None, None, 1, 0.1, **kw)
            with self.assertRaisesRegex(ValueError, "without a var_fn"):
                M.fit_best(None, None, None, 1, 0.1, **kw)
        for bad in ({"nu0": -1.0}, {"nu0": 0.0}, {"nu0": float("nan")}, {"nu0": float("inf")}, {"nu0": True},
                    {"nu": 4.0}, {"nu0": 4.0, "rule": "x"}, [4.0]):
            with self.assertRaises(ValueError):
                M.fit(None, None, None, 1, 0.1, var_fn=W, rep_prior=bad)
        with self.assertRaisesRegex(ValueError, "frozen fitter table"):
            M.fit(None, None, None, 1, 0.1, var_fn=W, score_law=lambda p: (p, p))
        with self.assertRaisesRegex(ValueError, "without a var_fn"):
            self.score({"link": M.Link(), "phi": 1.0, "var_fn": None, "score_law": SL}, [0.0], [1.0], [[100]])

    def test_T6_2_capture_scale_nu0_known_answer(self):
        """T6-2 (A_design_v5 3.3): capture_scale(V, zrep, R, nu0): phi = mean(zrep / V), v~_e = (nu0 phi V_e + (R - 1)
        zrep_e) / (nu0 + R - 1), w = (1 / v~) / mean(1 / v~), unit = 1 / (R mean(1 / v~)), so unit / w = v~ / R --
        against exact rational arithmetic; the limits nu0 -> inf (full pooling) and nu0 -> 0 (the raw variances);
        the refusals (a nu0 that is not a positive finite number, nu0 without V, no replicate variance at all); nu0
        None is main's capture_scale byte for byte."""
        from fractions import Fraction as F
        M = self.M
        V = np.array([0.5, 0.25, 0.1, 0.04, 0.3, 0.0123])
        zrep = np.array([0.6, 0.2, 0.15, 0.01, 0.0, 0.031])
        R = 6
        for nu0 in (4.0, 0.37, 25.5, 7):
            w, unit, phi = M.capture_scale(V, zrep, R, nu0=nu0)
            fv, fz, fn = [F(float(v)) for v in V], [F(float(v)) for v in zrep], F(nu0)
            fphi = sum(z / v for z, v in zip(fz, fv)) / len(fv)
            vt = [(fn * fphi * v + (R - 1) * z) / (fn + R - 1) for z, v in zip(fz, fv)]
            mt = sum(1 / x for x in vt) / len(vt)
            self.assertAlmostEqual(phi, float(fphi), delta=1e-14 * float(fphi))
            self.assertTrue(np.allclose(w, [float((1 / x) / mt) for x in vt], rtol=1e-14, atol=0), w)
            self.assertAlmostEqual(unit, float(1 / (R * mt)), delta=1e-14 * float(1 / (R * mt)))
            self.assertTrue(np.allclose(unit / w, [float(x / R) for x in vt], rtol=1e-14, atol=0))
            self.assertAlmostEqual(float(w.mean()), 1.0, delta=1e-14)
        w, u, p = M.capture_scale(V, zrep, R, nu0=1e12)
        self.assertTrue(np.allclose(u / w, p * V / R, rtol=1e-9, atol=0))           # (nu0 -> inf: phi V / R)
        pos = zrep > 0
        w, u, p = M.capture_scale(V[pos], zrep[pos], R, nu0=1e-12)
        self.assertTrue(np.allclose(u / w, zrep[pos] / R, rtol=1e-9, atol=0))       # (nu0 -> 0: zrep / R)
        for bad in (0, 0.0, -1.0, float("nan"), float("inf"), True, "4", [4.0]):
            with self.assertRaises(ValueError):
                M.capture_scale(V, zrep, R, nu0=bad)
        with self.assertRaisesRegex(ValueError, "without a variance function"):
            M.capture_scale(None, zrep, R, nu0=4.0)
        with self.assertRaisesRegex(ValueError, "undefined"):
            M.capture_scale(V, np.zeros(len(V)), R, nu0=4.0)
        ns = main_map()
        rng = np.random.default_rng(11)
        cases = [(V, zrep), (rng.uniform(1e-10, 2.0, 500), rng.gamma(1.0, 0.3, 500)), (None, zrep),
                 (None, np.zeros(5)), (np.full(4, 1e-12), np.array([1e-3, 0.0, 2e-3, 0.0])), (V, np.zeros(len(V)))]
        for Vc, zc in cases:
            want = ns["capture_scale"](Vc, zc, R)
            for got in (M.capture_scale(Vc, zc, R), M.capture_scale(Vc, zc, R, nu0=None)):
                self.assertEqual(got[0].tobytes(), want[0].tobytes())
                self.assertEqual((type(got[1]), got[1], type(got[2]), got[2]),
                                 (type(want[1]), want[1], type(want[2]), want[2]))

    def test_T6_2_nu0_overflow_safe_and_domain(self):
        """T6-2 with A_design_v5 clarification 2 (D3 and its implementation note; Codex WP2 review P2): every positive
        finite nu0 gives the formula's value -- Codex's known answer nu0 = 1e308, V = [0.5, 0.25], zrep = [2, 1], R = 6
        (phi = 4): v~ = [2, 1], w = [2/3, 4/3], unit = 2/9 (at a4227b6 nu0 phi V overflowed: v~ = inf, unit 1/0) -- and
        the formula against exact rational arithmetic for nu0 from 1e-300 to the largest float; a non-finite V or
        zrep is refused with that context; no replicate variance in any cell (phi = 0, every v~ = 0) is refused with
        that context, never floored; a v~ that underflows to 0 is refused by the positivity check, never divided."""
        from fractions import Fraction as F
        import sys as sys_
        M = self.M
        R = 6
        with self.subTest("Codex's known answer, nu0 = 1e308"):
            w, unit, phi = M.capture_scale(np.array([0.5, 0.25]), np.array([2.0, 1.0]), R, nu0=1e308)
            self.assertEqual(phi, 4.0)
            self.assertTrue(np.allclose(w, [2.0 / 3.0, 4.0 / 3.0], rtol=1e-15, atol=0), w)
            self.assertAlmostEqual(unit, 2.0 / 9.0, delta=1e-16)
            self.assertTrue(np.allclose(R * unit / w, [2.0, 1.0], rtol=1e-15, atol=0))          # (v~ = R unit / w)
        V = np.array([0.5, 0.25, 0.1, 0.04, 0.3, 0.0123])
        zrep = np.array([0.6, 0.2, 0.15, 0.01, 0.0, 0.031])
        for nu0 in (1e-300, 1e-12, 0.37, 4.0, 1e12, 1e200, 1e300, 1e308, sys_.float_info.max):
            with self.subTest("the formula against exact rationals", nu0=nu0):
                w, unit, phi = M.capture_scale(V, zrep, R, nu0=nu0)
                fv, fz, fn = [F(float(v)) for v in V], [F(float(v)) for v in zrep], F(nu0)
                fphi = sum(z / v for z, v in zip(fz, fv)) / len(fv)
                vt = [(fn * fphi * v + (R - 1) * z) / (fn + R - 1) for z, v in zip(fz, fv)]
                mt = sum(1 / x for x in vt) / len(vt)
                self.assertTrue(np.allclose(w, [float((1 / x) / mt) for x in vt], rtol=1e-13, atol=0), (nu0, w))
                self.assertAlmostEqual(unit, float(1 / (R * mt)), delta=1e-13 * float(1 / (R * mt)))
                self.assertTrue(np.allclose(R * unit / w, [float(x) for x in vt], rtol=1e-13, atol=0))
        for label, Vb, zb in (("zrep inf", V, np.r_[np.inf, zrep[1:]]), ("zrep nan", V, np.r_[zrep[:-1], np.nan]),
                              ("V inf", np.r_[V[:-1], np.inf], zrep), ("V nan", np.r_[np.nan, V[1:]], zrep),
                              ("zrep -inf", V, np.r_[zrep[:2], -np.inf, zrep[3:]])):
            with self.subTest("a non-finite input is refused", input=label):
                with self.assertRaisesRegex(ValueError, "non-finite value in V or zrep"):
                    M.capture_scale(Vb, zb, R, nu0=4.0)
        for nu0 in (4.0, 1e308, 1e-300):
            with self.subTest("phi = 0 is refused with that context", nu0=nu0):
                with self.assertRaisesRegex(ValueError, r"every replicate variance is zero \(phi = 0\).*not floored"):
                    M.capture_scale(V, np.zeros(len(V)), R, nu0=nu0)
        with self.subTest("a shrunk variance that underflows to 0 is refused (positivity), never divided"):
            with self.assertRaisesRegex(ValueError, "not finite and positive"):
                M.capture_scale(V, zrep, R, nu0=5e-324)                  # (the zero-variance cell's v~ underflows)

    # ---------------------------------------------------------------- T6-7
    def bank_data(self, D, idx, seed, quantum=None, nu0_het=None):
        """A synthetic bank-mode capture data set on the toy graph (gamma 1, the steep validation curve): the
        scenario truth r1_017_cap's eta on idx, mapped affinely onto [logit 0.01, logit 0.99]; counts from the
        capture law (obslaw: exact locations, B = 324, R = 6) with independent latents (T6-7's claims are about each
        cell's own replicate variance, which cross-cell sharing does not change). quantum: the intended logit
        fractions rounded to this step, the location solved once per level; nu0_het: per-cell latent scale
        heterogeneity, s_e^2 = S_C(mu_e)^2 kappa_e with kappa_e = nu0 / chi2(nu0) (a scaled-inverse-chi2(nu0) of
        scale 1; test only), the location solved at each cell's scale. -> (data, mu, exact V_z) on idx."""
        ol, B, R = self.ol, self.B, self.rec.R_REPS
        eta = self.rec.simulate(D, self.rec.SCENARIOS["r1_017_cap"], seed)["eta"][idx]
        xmax = math.log(99.0)
        x = -xmax + (eta - eta.min()) / (eta.max() - eta.min()) * (2.0 * xmax)
        rng = np.random.default_rng([seed, 7])
        if nu0_het is None:
            lev, inv = np.unique(np.round(x / quantum) * quantum, return_inverse=True)
            mul = ol.sig(lev)
            sl = self.nsc.evaluate(VAL_SC, mul)
            al, _ = ol.solve_location(mul, sl, B, B)
            mu, s, a = mul[inv], sl[inv], al[inv]
        else:
            mu = ol.sig(x)
            s = self.nsc.evaluate(VAL_SC, mu) * np.sqrt(nu0_het / rng.chisquare(nu0_het, len(mu)))
            a, _ = ol.solve_location(mu, s, B, B)
        K = ol.rounded_count(a[:, None], s[:, None], rng.standard_normal((len(mu), R)), B, B)
        z = np.zeros((len(D.qi), R))
        z[idx] = ol.empirical_logit(K, B)
        return {"z": z, "zbar": z.mean(axis=1)}, mu, ol.logit_moments(a, s)[1]

    def test_T6_7_working_coordinate_and_nu0(self):
        """T6-7 (A_design_v5 PC-14, 1.7b). (a) On a bank-mode data set (gamma 1, the steep validation curve, intended
        capture fractions 0.01-0.99, every fitting pair of the toy graph), fitted with the bank hooks and binned by
        the fitted fraction sigma(z_fit): the mean of zrep_e / W(z_fit,e) is 1 within 4 Monte Carlo SE in every bin
        and phi^ is in [0.95, 1.05], while the v1 adapter S_C(sigma(z_fit))^2 is distorted beyond 4 SE in the lowest
        and the highest bin, and beyond 4 SE of its own pooled phi in at least one of them (a single phi cannot
        absorb it); the fit's unit and phi are capture_scale's at its fitted fractions with its nu0 (full pooling
        likewise), and it records rep_prior, score_law, var_fn.identity and table_extrapolated. (b) With per-cell
        latent scale heterogeneity kappa_e ~ scaled-inverse-chi2(nu0) (test only), the shrunk v~_e has a lower mean
        squared error against each cell's exact V_z than full pooling (phi W) and than the raw zrep_e."""
        import sys as sys_
        M, ol, rec, R = self.M, self.ol, self.rec, self.rec.R_REPS
        D = rec.Data(full())
        idx = D.fit["a"]
        data, mu, _ = self.bank_data(D, idx, 1000, quantum=0.005)
        self.assertTrue(0.0099 < float(mu.min()) < 0.011 and 0.989 < float(mu.max()) < 0.9901)
        zrep = data["z"][idx].var(axis=1, ddof=1)
        fits = {}
        for nu0 in (10.0, None):
            W, SL = self.hooks(self.tab, f"t6-7 {nu0}")
            m = M.fit(D, idx, data, 1, 0.05, False, 10, 1, var_fn=W, rep_prior={"nu0": nu0}, score_law=SL)
            p = np.clip(ol.sig(M.predict(D, m, idx)), 1e-4, 1.0 - 1e-4)
            Vp = self.tab.evaluate(np.log(p) - np.log1p(-p))["W"]
            w, unit, phi = M.capture_scale(Vp, zrep, R, nu0=nu0)
            self.assertAlmostEqual(m["phi"], phi, delta=1e-12 * phi)
            self.assertAlmostEqual(m["unit"], unit, delta=1e-12 * unit)
            self.assertEqual(m["rep_prior"], {"nu0": nu0})
            self.assertIs(m["score_law"], SL)
            self.assertEqual(m["var_fn_identity"], f"t6-7 {nu0}")
            self.assertIsInstance(m["table_extrapolated"], int)
            self.assertEqual(m["table_extrapolated"], W.extrapolated)     # (W fresh: every count is this fit's)
            fits[nu0] = (m, p, Vp)
        self.assertNotEqual(fits[10.0][0]["unit"], fits[None][0]["unit"])          # (the shrinkage is applied)
        m, p, Vp = fits[10.0]
        phi_hat = m["phi"]
        self.assertTrue(0.95 <= phi_hat <= 1.05, phi_hat)
        rw = zrep / Vp
        r1 = zrep / self.nsc.evaluate(VAL_SC, p) ** 2
        edges = (0.0, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 1.0)
        rows = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            sel = (p >= lo) & (p < hi)
            n = int(sel.sum())
            self.assertGreater(n, 500, (lo, hi))
            rows.append((lo, hi, n, rw[sel].mean(), rw[sel].std(ddof=1) / math.sqrt(n), r1[sel].mean(),
                         r1[sel].std(ddof=1) / math.sqrt(n)))
        for lo, hi, n, mw, sw, m1, s1 in rows:
            print(f"T6-7 [{lo}, {hi}) n={n}: zrep/W {mw:.4f} +- {sw:.4f} ({(mw - 1) / sw:+.1f} SE); v1 adapter "
                  f"{m1:.4f} ({(m1 - 1) / s1:+.1f} SE from 1, {(m1 - r1.mean()) / s1:+.1f} SE from its phi "
                  f"{r1.mean():.4f}); phi^ {phi_hat:.4f}", file=sys_.stderr)
            self.assertLessEqual(abs(mw - 1.0), 4.0 * sw, (lo, hi, mw, sw))
        for lo, hi, n, mw, sw, m1, s1 in (rows[0], rows[-1]):
            self.assertGreater(abs(m1 - 1.0), 4.0 * s1, (lo, hi, m1, s1))
        self.assertTrue(any(abs(m1 - r1.mean()) > 4.0 * s1 for lo, hi, n, mw, sw, m1, s1 in (rows[0], rows[-1])))
        # (b) nu0 in working coordinates
        nu0 = 10.0
        idx_b = idx[::8]
        data_b, _, Vz = self.bank_data(D, idx_b, 2000, nu0_het=nu0)
        W, SL = self.hooks(self.tab, "t6-7b")
        mb = M.fit(D, idx_b, data_b, 1, 0.05, False, 10, 1, var_fn=W, rep_prior={"nu0": nu0}, score_law=SL)
        pb = np.clip(ol.sig(M.predict(D, mb, idx_b)), 1e-4, 1.0 - 1e-4)
        Vb = self.tab.evaluate(np.log(pb) - np.log1p(-pb))["W"]
        zb = data_b["z"][idx_b].var(axis=1, ddof=1)
        w, unit, phi = M.capture_scale(Vb, zb, R, nu0=nu0)
        self.assertAlmostEqual(mb["unit"], unit, delta=1e-12 * unit)
        w0, unit0, _ = M.capture_scale(Vb, zb, R)
        mse = {"shrunk": float(np.mean((R * unit / w - Vz) ** 2)), "pooled": float(np.mean((R * unit0 / w0 - Vz) ** 2)),
               "raw": float(np.mean((zb - Vz) ** 2))}
        print(f"T6-7(b) nu0 {nu0}, {len(idx_b)} cells, phi^ {phi:.4f}: MSE against the exact V_z {mse}",
              file=sys_.stderr)
        self.assertLess(mse["shrunk"], mse["pooled"])
        self.assertLess(mse["shrunk"], mse["raw"])

    # ---------------------------------------------------------------- T6-8
    def test_T6_8_score_law(self):
        """T6-8 (A_design_v5 3.3, PC-17): at nodes with known predicted empirical logit z, _score_law returns
        (A(mu^), phi L(mu^)), mu^ = m_z^-1(z), from the frozen fitter table: exact at the table's nodes, its
        piecewise-linear interpolants between them (checked through numpy's interp, not obslaw's lookup), the end
        values beyond it; at phi = 1 the count law (A, phi L) has mean fraction mu^ within 2e-7 (at the nodes, the
        certification probes 1/4, 1/2, 3/4 of every segment, and random points); the deviation at phi != 1 is
        recorded; score_law None reproduces today's scores byte for byte (main's pred_count_lpd: plain, exact and
        grid cases, a refinement and a range extension included)."""
        import sys as sys_
        M, ol, tab, B = self.M, self.ol, self.tab, self.B
        W, SL = self.hooks(tab)
        rng = np.random.default_rng(8)
        zs = {"nodes": tab.m.copy(),
              "probes": np.concatenate([tab.m[:-1] + f * np.diff(tab.m) for f in (0.25, 0.5, 0.75)]),
              "random": rng.uniform(tab.m[0], tab.m[-1], 5000)}
        for phi in (1.0, 1.7):
            m = {"phi": phi, "score_law": SL, "var_fn": W}
            for label, z in zs.items():
                A, V = M._score_law(m, z)
                self.assertTrue(np.allclose(A, np.interp(z, tab.m, tab.A), rtol=0, atol=1e-10), label)
                self.assertTrue(np.allclose(V, phi * np.interp(z, tab.m, tab.L), rtol=1e-12, atol=0), label)
            A, V = M._score_law(m, tab.m)
            self.assertTrue(np.allclose(A, tab.A, rtol=0, atol=1e-10) and np.allclose(V, phi * tab.L, rtol=1e-12))
            far = np.array([tab.m[0] - 1.0, -20.0, -1e3, tab.m[-1] + 1.0, 20.0, 1e3])
            A, V = M._score_law(m, far)
            self.assertTrue(np.array_equal(A, np.repeat(tab.A[[0, -1]], 3)))
            self.assertTrue(np.allclose(V, phi * np.repeat(tab.L[[0, -1]], 3), rtol=1e-15, atol=0))
        self.assertTrue(np.allclose(tab.mu_hat(tab.m), ol.sig(tab.x), rtol=1e-12, atol=0))
        m1 = {"phi": 1.0, "score_law": SL, "var_fn": W}
        for label, z in zs.items():
            A, V = M._score_law(m1, z)
            muh = tab.mu_hat(z)
            dev = float(np.max(np.abs(ol.expected_fraction(A, np.sqrt(V), B, B) - muh)))
            self.assertLessEqual(dev, 2e-7, label)
            for phi in (0.5, 0.8, 1.25, 2.0):
                dv = np.abs(ol.expected_fraction(A, np.sqrt(phi * V), B, B) - muh)
                print(f"T6-8 recorded ({label}): phi = {phi}: max |E[K]/B - mu^| = {float(dv.max()):.3e} at mu^ = "
                      f"{float(muh[np.argmax(dv)]):.6f} (phi = 1: {dev:.2e})", file=sys_.stderr)
        # score_law None: today's scorer, byte for byte
        loc = np.linspace(-12.0, 12.0, 97)
        m0 = {"phi": 0.9, "var_fn": W}
        got = M._score_law(m0, loc)
        self.assertIs(got[0], loc)
        self.assertEqual(got[1].tobytes(), M._rep_var(m0, loc).tobytes())
        vf = self.rec.var_model(self.rec.SCENARIOS["r2_017_cap15"])
        one = lambda p: np.ones_like(p)                                         # noqa: E731
        self.assert_main_bytes([
            ({"link": M.Link(), "phi": 1.0, "var_fn": W}, [0.3, -2.0, 4.0, 0.0], [0.0, 0.0, 0.0, 0.25],
             [[200, 201], [10, 12], [300, 324], [150, 170]]),                              # (plain and grid)
            ({"link": M.Link(), "phi": 0.003 ** 2, "var_fn": one}, [0.0], [1.0], [[162]]),  # (24,577 nodes)
            ({"link": M.Link(), "phi": 1.0, "var_fn": None}, [0.0, 1.0], [1.0, 0.5], [[162], [200]]),   # (exact)
            ({"link": M.Link(None, None, 0.02, 0.8), "phi": 0.003 ** 2, "var_fn": one}, [0.0], [1.0], [[324]]),
            ({"link": M.Link(), "phi": 1.0, "var_fn": vf}, [0.0], [1.646 ** 2],
             [[75, 111, 125, 137, 49, 87]]),
            ({"link": M.Link(np.array([-3.0, -1.0, 1.0, 3.0]), np.array([-3.0, -1.5, 1.4, 3.0]), 0.01, 0.95),
              "phi": 1.2, "var_fn": W}, [-2.0, 0.5, 2.5], [0.4, 1.0, 0.09], [[3], [180], [320]])])

    # ---------------------------------------------------------------- T6-10
    def t610_cases(self):
        """(group key, table name, link spec, phi, predicted fraction, SD, count) for T6-10: identity G on both
        tables over T610_FRACS x T610_SDS x counts {0, the modal count, B} (the unrepresentable cases excluded; the
        three range-gap cases T610_GAP included since clarification 2), plus a spline link, a bounded link and
        phi = 1.5 on the steep curve: 195 observations."""
        B = self.B
        out = []
        for tname in ("val", "const"):
            for mu in T610_FRACS:
                for sd in T610_SDS:
                    for k in sorted({0, int(round(B * mu)), B}):
                        key = (tname, mu, sd, k)
                        if key not in T610_UNREPRESENTABLE:
                            out.append(((tname, None, 1.0), tname, None, 1.0, mu, sd, k))
        spline = ((-4.0, -1.0, 1.0, 4.0), (-4.0, -1.6, 0.4, 4.0), 0.0, 1.0)
        bounded = ((-3.0, 0.0, 3.0), (-3.0, 0.5, 3.0), 0.02, 0.9)
        for mu in (0.01, 0.5, 0.99):
            for sd in (0.3, 1.0):
                out.append((("val", "spline", 1.0), "val", spline, 1.0, mu, sd, int(round(B * mu))))
        for mu in (0.05, 0.5, 0.85):
            for sd in (0.3, 1.0):
                for k in (0, int(round(B * mu))):
                    out.append((("val", "bounded", 1.0), "val", bounded, 1.0, mu, sd, k))
        for mu in (0.1, 0.5, 0.9):
            for sd in (0.3, 1.0):
                for k in (0, int(round(B * mu))):
                    out.append((("val", None, 1.5), "val", None, 1.5, mu, sd, k))
        return out

    def t610_eta(self, tab, spec, mu):
        """The predictor whose G is the table's m_z at mu (the predicted empirical logit of fraction mu)."""
        z = self.zmu(tab, mu)
        if spec is None:
            return z
        G = ref_link(*spec)
        lo, hi = -60.0, 60.0
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            lo, hi = (mid, hi) if float(G(np.array([mid]))[0]) < z else (lo, mid)
        return 0.5 * (lo + hi)

    def t610_reference(self, tab, spec, phi, eta, sd, k):
        G = ref_link(*spec) if spec is not None else ref_link()
        m_, A_, L_ = tab.m, tab.A, tab.L

        def loglik(e):
            z = G(eta + e)
            return ref_count_logp(k, np.interp(z, m_, A_), phi * np.interp(z, m_, L_), self.B)
        return ref_log_integral(loglik, sd)

    def t610_refs(self, cases):
        """The reference of every case (computed once per test run: a module cache keyed by the case)."""
        out = []
        for g, tname, spec, phi, mu, sd, k in cases:
            key = (tname, spec, phi, mu, sd, k)
            if key not in _T610_REF:
                tab = self.tabs[tname]
                _T610_REF[key] = self.t610_reference(tab, spec, phi, self.t610_eta(tab, spec, mu), sd, k)
            out.append(_T610_REF[key])
        return out

    def t610_run(self, cases, rule=None, hook=True):
        """Score every case (one replicate per pair, so a pair's score is one observation's): grouped by table, link
        and phi -> ({case index: score}, {group: info}). rule: a replacement _score_need (the negative control);
        hook False: no score law (main's scorer, for the byte comparison)."""
        M = self.M
        groups = {}
        for i, c in enumerate(cases):
            groups.setdefault(c[0], []).append(i)
        out, infos, models = {}, {}, {}
        for g, ix in groups.items():
            tname, spec, phi = cases[ix[0]][1], cases[ix[0]][2], cases[ix[0]][3]
            tab = self.tabs[tname]
            W, SL = self.hooks(tab, "t6-10")
            lk = M.Link() if spec is None else M.Link(np.array(spec[0]), np.array(spec[1]), spec[2], spec[3])
            m = {"link": lk, "phi": phi, "var_fn": W}
            if hook:
                m["score_law"] = SL
            eta = [self.t610_eta(tab, spec, cases[i][4]) for i in ix]
            s2 = [cases[i][5] ** 2 for i in ix]
            cnt = [[cases[i][6]] for i in ix]
            if rule is None:
                sc, info = self.score(m, eta, s2, cnt)
            else:
                with mock.patch.object(M, "_score_need", rule):
                    sc, info = self.score(m, eta, s2, cnt)
            out.update(zip(ix, sc.tolist()))
            infos[g], models[g] = info, (m, eta, s2, cnt)
        return out, infos, models

    def mandatory(self):
        """T6-10's mandatory rare-count case (S_C = 0.2, phi 1, identity G, fraction 0.998, SD 1, k = 0, location
        m_z(0.998) from the exact location solve) -> (location, its reference; cached)."""
        if "mandatory" not in _T610_REF:
            B, ol = self.B, self.ol
            a, _ = ol.solve_location(np.array([0.998]), np.array([0.2]), B, B)
            loc = float(ol.logit_moments(a, np.array([0.2]))[0][0])
            _T610_REF["mandatory"] = (loc, self.t610_reference(self.tabs["const"], None, 1.0, loc, 1.0, 0))
        return _T610_REF["mandatory"]

    def assert_certified(self, labelled):
        """Every reference of labelled [(label, reference)] is certified within REF_HALVINGS halvings (A_design_v5
        clarification 2, D2): the halving stopped at the first two consecutive estimates within REF_CERT in log, the
        finer of them is the reference and their |difference| its certificate, the final spacing is 5e-5 / 2^halvings
        SD, and the tail criterion holds with the final estimate. Otherwise T6-10 fails with each such case's spacings,
        estimates and certificate (no case is excluded or given an allowance)."""
        bad = []
        for label, r in labelled:
            est = r["estimates"]
            ok = (r["certified"] and r["fine_bound_ok"] and 1 <= r["halvings"] == len(est) - 1 <= REF_HALVINGS
                  and r["spacing"] == est[-1][0] == REF_SPACING / 2.0 ** r["halvings"] and r["log_I"] == est[-1][1]
                  and r["certificate"] == abs(est[-1][1] - est[-2][1]) <= REF_CERT
                  and all(abs(y[1] - x[1]) > REF_CERT for x, y in zip(est[:-2], est[1:-1])))
            if not ok:
                bad.append((label, est, r["certificate"], r["fine_bound_ok"]))
        self.assertEqual(bad, [], "references not certified within four halvings (A_design_v5 clarification 2, D2): "
                                  "(case, [(spacing in SD, log I^), ...], certificate, tail criterion with the final)")

    @staticmethod
    def tail_holds(full, span):
        """The bank-mode tail bound of A_design_v5 clarification 2, D1, computed here independently of map (from the
        reference's ref_log_sf; TRAP_SD = 7, TRAP_TAIL = 1e-4): log(2 PhiBar(b)) <= log(1e-4) + full + log(1 - 2
        PhiBar(b)), b = 7 span, elementwise on a pass's normalized estimates full."""
        lt = math.log(2.0) + float(ref_log_sf(np.array([7.0 * span]))[0])
        return np.asarray(full, float) >= lt - math.log(1e-4) - math.log1p(-math.exp(lt))

    def brute_need(self, tab, lk, phi, eta, sd, span):
        """The grid rule's node requirement (A_design_v5 3.3, PC-24) computed independently of map._score_need: H^max
        by brute force over every table segment meeting [G(eta - Delta), G(eta + Delta)] (clipped like the score law's
        argument), Delta = TRAP_SD span sd, g_max = Link.max_slope over [eta - Delta, eta + Delta], s_lat = sqrt(phi
        min L), h = min(sd, TRAP_H s_lat / (g_max max(H^max, 1e-12))) -> (ceil(2 TRAP_SD span sd / h) + 1, H^max,
        g_max)."""
        M = self.M
        kappa = np.abs(np.diff(tab.A) / np.diff(tab.m))
        d_ = M.TRAP_SD * span * sd
        pz = np.clip(M._sig(lk.G(np.array([eta - d_, eta + d_]))), 1e-4, 1 - 1e-4)
        zlo, zhi = (np.log(pz) - np.log1p(-pz)).tolist()
        hit = (tab.m[:-1] <= zhi) & (tab.m[1:] >= zlo)
        hmax = float(kappa[hit].max()) if hit.any() else 0.0
        gmax = max(lk.max_slope(eta - d_, eta + d_), 1e-12)
        h = min(sd, M.TRAP_H * math.sqrt(max(phi * float(tab.L.min()), 1e-300)) / (gmax * max(hmax, 1e-12)))
        return math.ceil(2 * M.TRAP_SD * span * sd / max(h, 1e-300)) + 1, hmax, gmax

    def test_T6_10_integrated_score_with_the_hook(self):
        """T6-10 (A_design_v5 3.3, PC-24, PC-25, with clarification 2): pred_count_lpd with the score law equals the
        reference within 2 x TRAP_TOL per observation, with no grid_unresolved pair, for predicted capture fractions
        0.002-0.998 (the saturated ones, where the table's slopes kappa_j are largest, included), predictor SDs
        0.05-1.0 and counts 0, modal and B (the rarest at the extreme predictions), on the steep validation curve and
        S_C = 0.2, with identity, spline and bounded links and phi 1 and 1.5: 195 observations (every case but the
        three the reference refuses as unrepresentable at +-60 SD; the three range-gap cases T610_GAP included, which
        the tail bound of D1 now extends); every reference is certified within four halvings (D2: the case fails
        otherwise). The mandatory rare-count case (S_C = 0.2, phi 1, identity G, fraction 0.998, SD 1, k = 0,
        location m_z(0.998)): the reference extends beyond 10 SD and the scorer records a range extension and agrees.
        The v2 rule (main's step, no H^max) runs as the negative control and its misses are reported; with score_law
        unset the scores are main's byte for byte."""
        import sys as sys_
        M = self.M
        tol = 2 * M.TRAP_TOL
        for key in T610_UNREPRESENTABLE:
            tab = self.tabs[key[0]]
            with self.assertRaisesRegex(ValueError, "unrepresentable"):
                self.t610_reference(tab, None, 1.0, self.zmu(tab, key[1]), key[2], key[3])
        cases = self.t610_cases()
        self.assertEqual(len(cases), 195)
        self.assertTrue(T610_GAP <= {(c[1], c[4], c[5], c[6]) for c in cases if c[2] is None and c[3] == 1.0})
        got, infos, models = self.t610_run(cases)
        worst, misses = 0.0, []
        refs = {}
        rr = self.t610_refs(cases)
        self.assert_certified([(c[1:], r) for c, r in zip(cases, rr)])
        for i, r in enumerate(rr):
            refs[i] = r["log_I"]
            d = abs(got[i] - r["log_I"])
            worst = max(worst, d)
            if d > tol:
                misses.append((cases[i][1:], got[i], r["log_I"]))
        for g, info in infos.items():
            self.assertEqual(info["grid_unresolved"], 0, g)
            self.assertIsInstance(info["table_extrapolated"], int)
        ext = sum(info["extended"] for info in infos.values())
        certs = [r["certificate"] for r in rr]
        print(f"T6-10: {len(cases)} observations, worst |score - reference| {worst:.2e} (tolerance {tol}), {ext} range "
              f"extensions, misses {misses}; reference certificates: worst {max(certs):.2e}, all certified within "
              f"four halvings (halvings used: {sorted(Counter(r['halvings'] for r in rr).items())})",
              file=sys_.stderr)
        self.assertEqual(misses, [])
        self.assertGreater(ext, 10)
        # the mandatory rare-count case
        tabc = self.tabs["const"]
        loc, r = self.mandatory()
        self.assert_certified([("mandatory", r)])
        self.assertGreater(r["b"], REF_START)
        self.assertTrue(all(not t[3] for t in r["trace"][:-1]) and r["trace"][-1][3])
        W, SL = self.hooks(tabc)
        sc, info = self.score({"link": M.Link(), "phi": 1.0, "var_fn": W, "score_law": SL}, [loc], [1.0], [[0]])
        print(f"T6-10 mandatory case: score {float(sc[0]):.6f}, reference {r['log_I']:.6f} (b = {r['b']:g} SD), "
              f"scorer info {info}", file=sys_.stderr)
        self.assertGreaterEqual(info["extended"], 1)
        self.assertEqual(info["grid_unresolved"], 0)
        self.assertLessEqual(abs(float(sc[0]) - r["log_I"]), tol)

        # the negative control: the v2 rule (main's step: the working variance's floor, no H^max)
        def v2_rule(lk, m, eta, sd, span):
            smin = math.sqrt(max(float(M._rep_var(m, M.VMIN_GRID).min()), 1e-300))
            d_ = M.TRAP_SD * span * sd
            gmax = np.array([max(lk.max_slope(e - dd, e + dd), 1e-12) for e, dd in
                             zip(np.atleast_1d(eta), np.broadcast_to(d_, np.shape(np.atleast_1d(eta))))])
            h = np.minimum(sd, M.TRAP_H * smin / gmax)
            return np.ceil(2 * M.TRAP_SD * span * sd / np.maximum(h, 1e-300)) + 1
        got2, infos2, _ = self.t610_run(cases, rule=v2_rule)
        miss2 = [(cases[i][1:], round(got2[i] - refs[i], 6)) for i in refs if abs(got2[i] - refs[i]) > tol]
        unres2 = sum(info["grid_unresolved"] for info in infos2.values())
        print(f"T6-10 negative control (v2 rule): {len(miss2)} misses beyond {tol}, {unres2} unresolved, worst "
              f"{max(abs(got2[i] - refs[i]) for i in refs):.2e}; misses {miss2}", file=sys_.stderr)
        # score_law unset: main's scorer, byte for byte, on the same groups
        _, _, plain = self.t610_run(cases, hook=False)
        self.assert_main_bytes(list(plain.values()))

    def test_T6_10_grid_rule_per_pair_hmax_and_extension(self):
        """T6-10's grid rule (A_design_v5 3.3, PC-24) against an independent computation: H^max the largest |kappa_j|
        of the table segments meeting [G(eta - Delta), G(eta + Delta)] (brute force over every segment; 0 wholly beyond
        the table), Delta = TRAP_SD span sd, g_max the link's max_slope over [eta - Delta, eta + Delta] per pair,
        s_lat = sqrt(phi min L), h = min(sd, TRAP_H s_lat / (g_max max(H^max, 1e-12))): _score_need gives
        ceil(2 TRAP_SD span sd / h) + 1 for identity, spline and bounded links, spans 1-8 and phi 0.6-2.2. On a range
        extension (the steep curve, k = 0 at fraction 0.998, SD 1, where the extended range reaches the table's
        steepest segments) every grid used is at least the bucket of the requirement RECOMPUTED on its range, which
        main's span-scaled requirement does not reach there."""
        M, tab = self.M, self.tab
        W, SL = self.hooks(tab)
        kappa = np.abs(np.diff(tab.A) / np.diff(tab.m))

        def zc(g):
            p = np.clip(M._sig(np.asarray(g, float)), 1e-4, 1 - 1e-4)
            return np.log(p) - np.log1p(-p)

        def need(lk, phi, eta, sd, span):
            d_ = M.TRAP_SD * span * sd
            zlo, zhi = float(zc(lk.G(np.array([eta - d_])))[0]), float(zc(lk.G(np.array([eta + d_])))[0])
            hit = (tab.m[:-1] <= zhi) & (tab.m[1:] >= zlo)
            hmax = float(kappa[hit].max()) if hit.any() else 0.0
            gmax = max(lk.max_slope(eta - d_, eta + d_), 1e-12)
            slat = math.sqrt(max(phi * float(tab.L.min()), 1e-300))
            h = min(sd, M.TRAP_H * slat / (gmax * max(hmax, 1e-12)))
            return math.ceil(2 * M.TRAP_SD * span * sd / max(h, 1e-300)) + 1, hmax
        rng = np.random.default_rng(10)
        links = [M.Link(), M.Link(np.array([-4.0, -1.0, 1.0, 4.0]), np.array([-4.0, -1.6, 0.4, 4.0])),
                 M.Link(np.array([-3.0, 0.0, 3.0]), np.array([-3.0, 0.5, 3.0]), 0.02, 0.9)]
        zero_hmax = 0
        for lk in links:
            for phi in (1.0, 0.6, 2.2):
                m = {"link": lk, "phi": phi, "var_fn": W, "score_law": SL}
                eta = rng.uniform(-12.0, 12.0, 120)
                sd = np.exp(rng.uniform(math.log(0.005), math.log(3.0), 120))
                for span in (1.0, 2.0, 4.0, 8.0):
                    got = M._score_need(lk, m, eta, sd, span)
                    want = [need(lk, phi, e, s, span) for e, s in zip(eta, sd)]
                    self.assertTrue(np.array_equal(got, np.array([w[0] for w in want], float)), (span, phi))
                    zero_hmax += sum(w[1] == 0.0 for w in want)
                    one = M._score_need(lk, m, eta[:1], sd[:1], span)
                    self.assertEqual(float(one[0]), float(got[0]))
        self.assertGreater(zero_hmax, 0)                       # (intervals wholly in the constant extrapolation)
        # the extension: the grid used at every span is at least the recomputed requirement's bucket
        eta0 = self.zmu(tab, 0.998)
        calls = []
        real = M._grid_pass

        def spy(lk, m, cnt, eta, sd, N, K, span):
            calls.append((int(K), float(span[0])))
            return real(lk, m, cnt, eta, sd, N, K, span)
        m = {"link": M.Link(), "phi": 1.0, "var_fn": W, "score_law": SL}
        with mock.patch.object(M, "_grid_pass", spy):
            _, info = self.score(m, [eta0], [1.0], [[0]])
        self.assertGreaterEqual(info["extended"], 1)
        self.assertIn(2.0, [s for _, s in calls])
        top = len(M.TRAP_KS) - 1
        for K, span in calls:
            n_, _ = need(M.Link(), 1.0, eta0, 1.0, span)
            self.assertGreaterEqual(K, M.TRAP_KS[min(int(np.searchsorted(M.TRAP_KS, n_)), top)], (K, span))
        n1, h1 = need(M.Link(), 1.0, eta0, 1.0, 1.0)
        n2, h2 = need(M.Link(), 1.0, eta0, 1.0, 2.0)
        self.assertGreater(h2, h1)                             # (the extended range meets steeper segments)
        self.assertGreater(int(np.searchsorted(M.TRAP_KS, n2)), int(np.searchsorted(M.TRAP_KS, n1 * 2.0)))

    def test_T6_10_gap_diagnosis(self):
        """The T6-10 range gap (T610_GAP; Codex WP2 review P1), closed by the tail bound (A_design_v5 clarification 2,
        D1): for each case the scorer's own integrand (_score_law and the interval probability), integrated densely
        over +-25 SD, matches the reference within 1e-6 and peaks beyond +-TRAP_SD prior SDs (the dominant mode lies
        outside the first range); the first pass (span 1) passes main's end-node check but fails the tail bound
        (computed here independently, from the reference's tail function), so pred_count_lpd EXTENDS the range and
        the score agrees with the certified reference within 2 x TRAP_TOL, with no grid_unresolved pair (at a4227b6
        it extended nothing and missed by 9.6-83 nats, unflagged)."""
        import sys as sys_
        M, B = self.M, self.B
        for tname, mu, sd, k in sorted(T610_GAP):
            tab = self.tabs[tname]
            W, SL = self.hooks(tab)
            m = {"link": M.Link(), "phi": 1.0, "var_fn": W, "score_law": SL}
            eta = self.zmu(tab, mu)
            r = self.t610_refs([((tname, None, 1.0), tname, None, 1.0, mu, sd, k)])[0]
            passes = []
            real = M._grid_pass

            def spy(lk, m_, cnt, e_, s_, N, K, span, passes=passes, real=real):
                res = real(lk, m_, cnt, e_, s_, N, K, span)
                passes.append((float(span[0]), res[0].copy(), res[2].copy()))
                return res
            with mock.patch.object(M, "_grid_pass", spy):
                sc, info = self.score(m, [eta], [sd * sd], [[k]])
            x = np.linspace(-25.0, 25.0, 2_000_001)
            loc, var = M._score_law(m, eta + sd * x)
            t = (M._interval_logp(np.full((len(x), 1), k), B, loc[:, None], var[:, None])[:, 0] - 0.5 * x * x
                 - 0.5 * math.log(2 * math.pi) + math.log(x[1] - x[0]))
            dense = float(t.max() + math.log(float(np.exp(t - t.max()).sum())))
            span1, full1, edge1 = passes[0]
            print(f"T6-10 range gap {tname} mu^ {mu} SD {sd} k {k}: scorer {float(sc[0]):.6f}, reference "
                  f"{r['log_I']:.6f}, the scorer's integrand densely {dense:.6f} (peak at e = "
                  f"{float(x[np.argmax(t)]):+.2f} SD); first pass (span {span1:g}) {float(full1[0, 0]):.4f}, spans "
                  f"used {sorted({p[0] for p in passes})}; info {info}", file=sys_.stderr)
            self.assertLessEqual(abs(dense - r["log_I"]), 1e-6)
            self.assertGreater(float(x[np.argmax(t)]), M.TRAP_SD)
            self.assertEqual(span1, 1.0)
            self.assertTrue(np.all(edge1 <= M.TRAP_EDGE))                      # (main's end-node check passes ...)
            self.assertFalse(np.all(self.tail_holds(full1, 1.0)))              # (... the tail bound does not)
            self.assertGreaterEqual(info["extended"], 1)
            self.assertEqual(info["grid_unresolved"], 0)
            self.assertLessEqual(abs(float(sc[0]) - r["log_I"]), 2 * M.TRAP_TOL)
            self.assert_certified([((tname, mu, sd, k), r)])

    def test_T6_10_gap_cases_agree(self):
        """T6-10's requirement on the range-gap cases (T610_GAP), each scored alone: the scorer records a range
        extension and agrees with the certified reference within 2 x TRAP_TOL, with no grid_unresolved pair (an
        expected failure at a4227b6; A_design_v5 clarification 2, D1)."""
        cases = [((t, None, 1.0), t, None, 1.0, mu, sd, k) for t, mu, sd, k in sorted(T610_GAP)]
        refs = self.t610_refs(cases)
        self.assert_certified([(c[1:], r) for c, r in zip(cases, refs)])
        for c, r in zip(cases, refs):
            got, infos, _ = self.t610_run([c])
            self.assertGreaterEqual(infos[c[0]]["extended"], 1, c)
            self.assertEqual(infos[c[0]]["grid_unresolved"], 0, c)
            self.assertLessEqual(abs(got[0] - r["log_I"]), 2 * self.M.TRAP_TOL, c)

    def test_T6_10_reference_certificates(self):
        """T6-10's reference (A_design_v5 PC-25 with clarification 2, D2): every one of the 195 observations (v5's 192
        and the three range-gap cases) and the mandatory rare-count case certifies within four halvings of 5e-5 SD --
        the halving stops at the first two consecutive estimates within 1e-9 in log, the finer of them is the
        reference, and the tail criterion holds with it. Each case's final spacing and certificate are recorded, with
        the spacings' distribution. (At a4227b6 the reference halved once and 22 of 192 exceeded 1e-9, the mandatory
        case 4.5e-9: the halve-once mutation reproduces that.)"""
        import sys as sys_
        cases = self.t610_cases()
        labelled = [(c[1:], r) for c, r in zip(cases, self.t610_refs(cases))]
        labelled.append(("mandatory (S_C 0.2, 0.998, SD 1, k 0)", self.mandatory()[1]))
        self.assertEqual(len(labelled), 196)
        for label, r in labelled:
            print(f"T6-10 reference {label}: b = {r['b']:g} SD, {r['halvings']} halving(s), final spacing "
                  f"{r['spacing']:.4g} SD, certificate {r['certificate']:.3e}, log I^ {r['log_I']:.12f}",
                  file=sys_.stderr)
        dist = sorted(Counter(r["spacing"] for _, r in labelled).items(), reverse=True)
        worst = max(labelled, key=lambda x: x[1]["certificate"])
        print(f"T6-10 references: {len(labelled)} cases; final spacing (SD): count {dist}; worst certificate "
              f"{worst[1]['certificate']:.3e} ({worst[0]})", file=sys_.stderr)
        self.assert_certified(labelled)

    def test_T6_10_tail_bound_rule(self):
        """A_design_v5 clarification 2, D1, white box (pred_count_lpd's controller with a stub grid pass whose
        estimates are prescribed per span): with the score law a pass is range-adequate only if main's end-node check
        AND the tail bound log(2 PhiBar(b)) <= log(TRAP_TAIL) + log I^ hold for EVERY replicate, b = TRAP_SD span,
        log I^ = full + log(1 - 2 PhiBar(b)), TRAP_TAIL = 1e-4 (the bound fails below log I^ = -17.48, -91.66 and
        -386.3 at b = 7, 14 and 28: clarification 2's figures). 4e-13 either side of the exact threshold at b = 7 (where
        the normalized full and log I^ differ by 2.6e-12) the bound decides; one failing replicate is enough; either
        check alone extends the range, with the requirement recomputed on it (the grid at span 2 is at least the
        bucket of the brute-force requirement there); still failing at the cap (span 8, +-56 SD) the pair is kept and
        counted in grid_unresolved; a range-adequate pass that fails the resolution check refines; with the score law
        unset the same passes are main's (no tail bound: nothing extends)."""
        M, tab = self.M, self.tab
        W, SL = self.hooks(tab)

        def lt(span):                       # log(2 PhiBar(7 span)), independently of map
            return math.log(2.0) + float(ref_log_sf(np.array([7.0 * span]))[0])

        def thr(span):                      # the exact threshold of the bound on a pass's normalized estimate full
            return lt(span) - math.log(1e-4) - math.log1p(-math.exp(lt(span)))
        for span, want, places in ((1, -17.48, 2), (2, -91.66, 2), (4, -386.3, 1)):
            self.assertAlmostEqual(lt(span) - math.log(1e-4), want, places=places)
        self.assertGreater(-math.log1p(-math.exp(lt(1))), 2.5e-12)           # (log I^ vs full at b = 7)
        t1 = thr(1)

        def run(fulls, edges=None, hook=True, unresolved_first=False):
            """fulls / edges: {span: (replicate 1, replicate 2)} -> (score, info, [(K, span)])."""
            calls = []

            def stub(lk, m_, cnt, eta, sd, N, K, span):
                s = float(span[0])
                calls.append((int(K), s))
                f = np.tile(np.asarray(fulls[s], float), (len(eta), 1))
                e = np.tile(np.asarray((edges or {}).get(s, (-50.0, -50.0)), float), (len(eta), 1))
                h = f + (0.01 if unresolved_first and len(calls) == 1 else 0.0)
                return f, h, e
            m = {"link": M.Link(), "phi": 1.0, "var_fn": W}
            if hook:
                m["score_law"] = SL
            with mock.patch.object(M, "_grid_pass", stub):
                sc, info = self.score(m, [0.0], [1.0], [[100, 100]])
            return float(sc[0]), info, calls
        ok2 = {2.0: (-20.0, -20.0)}
        sc, info, calls = run({1.0: (t1 + 4e-13, t1 + 4e-13)})                  # (just inside: adequate)
        self.assertEqual((info["extended"], info["grid"], [s for _, s in calls]), (0, 1, [1.0]))
        self.assertEqual(sc, t1 + 4e-13)
        sc, info, calls = run({1.0: (t1 - 4e-13, t1 - 4e-13), **ok2})            # (just outside: extended)
        self.assertEqual((info["extended"], info["grid_unresolved"], [s for _, s in calls]), (1, 0, [1.0, 2.0]))
        self.assertEqual(sc, -20.0)
        need2 = self.brute_need(tab, M.Link(), 1.0, 0.0, 1.0, 2.0)[0]
        self.assertGreaterEqual(calls[1][0], M.TRAP_KS[min(int(np.searchsorted(M.TRAP_KS, need2)), len(M.TRAP_KS) - 1)])
        sc, info, calls = run({1.0: (t1 + 1.0, t1 - 4e-13), **ok2})              # (one replicate fails: extended)
        self.assertEqual((info["extended"], [s for _, s in calls]), (1, [1.0, 2.0]))
        sc, info, calls = run({1.0: (-1.0, -1.0), **ok2}, edges={1.0: (-50.0, -1.0)})   # (the end-node check alone)
        self.assertEqual((info["extended"], [s for _, s in calls]), (1, [1.0, 2.0]))
        cap = {s: (-2000.0, -2000.0) for s in (1.0, 2.0, 4.0, 8.0)}               # (below thr(8): fails at the cap)
        self.assertLess(-2000.0, thr(4))
        self.assertLess(-2000.0, thr(8))
        sc, info, calls = run(cap)
        self.assertEqual((info["extended"], info["grid_unresolved"], info["grid"], [s for _, s in calls]),
                         (3, 1, 0, [1.0, 2.0, 4.0, 8.0]))
        self.assertEqual(sc, -2000.0)
        sc, info, calls = run({1.0: (-1.0, -1.0)}, unresolved_first=True)        # (adequate, unresolved: refined)
        self.assertEqual((info["extended"], info["refined"], info["grid"], [s for _, s in calls]),
                         (0, 1, 1, [1.0, 1.0]))
        self.assertGreater(calls[1][0], calls[0][0])
        for fulls in ({1.0: (t1 - 4e-13, t1 - 4e-13)}, {1.0: (-2000.0, -2000.0)}):   # (score law unset: main's)
            sc, info, calls = run(fulls, hook=False)
            self.assertEqual((info["extended"], info["grid"], [s for _, s in calls]), (0, 1, [1.0]))
        self.assertEqual((M.TRAP_TAIL, M.TRAP_SD, M.TRAP_SPAN_MAX), (1e-4, 7.0, 8))

    def test_T6_10_second_extension_recomputes_on_a_nonidentity_link(self):
        """Codex's extension-coverage gap (WP2 review: the controller's recomputation was shown on one extension of an
        identity link only): T610_TWO_EXT, two cases on spline links (the steep curve, k = B at fractions 0.01 and 0.1,
        SD 0.2) whose ranges the tail bound (clarification 2, D1) extends twice, to span 4. Every grid used is at least
        the bucket of the requirement recomputed on its own range (g_max, H^max and h; v5 3.3 'on every range
        extension'), computed here by brute force; at span 4 that bucket exceeds the span-2 grid and what a
        controller recomputing only on the first extension would use (main's span-scaled span-1 requirement, or the
        span-2 requirement doubled), and on the first case the link's slope bound itself changes there (0.5 -> 2.5).
        Each score agrees with its certified reference within 2 x TRAP_TOL, with no grid_unresolved pair."""
        import sys as sys_
        M, tab = self.M, self.tab
        W, SL = self.hooks(tab)
        top = len(M.TRAP_KS) - 1

        def bkt(n):
            return min(int(np.searchsorted(M.TRAP_KS, n)), top)
        for i, (spec, mu, sd, k) in enumerate(T610_TWO_EXT):
            lk = M.Link(np.array(spec[0]), np.array(spec[1]), spec[2], spec[3])
            m = {"link": lk, "phi": 1.0, "var_fn": W, "score_law": SL}
            eta = self.t610_eta(tab, spec, mu)
            calls = []
            real = M._grid_pass

            def spy(lk_, m_, cnt, e_, s_, N, K, span, calls=calls, real=real):
                calls.append((int(K), float(span[0])))
                return real(lk_, m_, cnt, e_, s_, N, K, span)
            with mock.patch.object(M, "_grid_pass", spy):
                sc, info = self.score(m, [eta], [sd * sd], [[k]])
            need = {s: self.brute_need(tab, lk, 1.0, eta, sd, s) for s in (1.0, 2.0, 4.0)}
            r = self.t610_refs([(("val", spec, 1.0), "val", spec, 1.0, mu, sd, k)])[0]
            print(f"T6-10 two extensions, case {i} (link knots {spec[0]}, fraction {mu}, SD {sd}, k {k}): grids (K, "
                  f"span) {calls}, brute-force requirement per span {[(s, v[0]) for s, v in need.items()]}, g_max "
                  f"{[(s, v[2]) for s, v in need.items()]}; score {float(sc[0]):.6f}, reference {r['log_I']:.6f}; "
                  f"info {info}", file=sys_.stderr)
            self.assertEqual(info["extended"], 2)
            self.assertEqual(sorted({s for _, s in calls}), [1.0, 2.0, 4.0])
            for K, s in calls:
                self.assertGreaterEqual(K, M.TRAP_KS[bkt(need[s][0])], (i, K, s))
            k2 = max(K for K, s in calls if s == 2.0)
            self.assertGreater(bkt(need[4.0][0]), max(M.TRAP_KS.index(k2), bkt(need[1.0][0] * 4.0),
                                                       bkt(need[2.0][0] * 2.0)))
            if i == 0:
                self.assertEqual((need[1.0][2], need[2.0][2], need[4.0][2]), (0.5, 0.5, 2.5))
            self.assert_certified([(("two extensions", i), r)])
            self.assertEqual(info["grid_unresolved"], 0)
            self.assertLessEqual(abs(float(sc[0]) - r["log_I"]), 2 * M.TRAP_TOL)

    # ---------------------------------------------------------------- T6-11
    def test_T6_11_reference_self_test(self):
        """T6-11 (A_design_v5 PC-25; the ten fixtures frozen in v5), prior N(0, 1): (a) L = exp(-(e - d)^2 / (2 w^2)),
        w in {0.17, 1.0} x d in {0, 5, 15, 30}, log I = log w - log(1 + w^2) / 2 - d^2 / (2 (1 + w^2)); (b) L = 1,
        log I = 0; (c) L = Phi((-12 - e) / 0.5), I = Phi(-12 / sqrt 1.25). Each: |log I^ - log I| <= 1e-8 and the
        halving certificate <= 1e-9, by the same refinement as T6-10's (A_design_v5 clarification 2, D2: halved until
        certified, at most four times; these fixtures certify after one halving, as clarification 2 records, and each
        one's halvings and final spacing are recorded); the stopping bound is checked at every extension step (each
        earlier step fails it, the last meets it, with the final value too); stops within 10-32 SD. Negative controls:
        under v4's 1e-6
        budget (a) w = 0.17, d = 30 and (c) miss by more than 1e-8 (omitted fractions about 2.48e-7 and 2.8e-7) while
        their certificates read about 0; truncated at +-10 SD, (a) d = 15, 30 and (c) are refused. The log tail is
        continuous where it switches from erfc to the continued fraction."""
        import sys as sys_
        fixtures = [("a", w, d) for w in (0.17, 1.0) for d in (0.0, 5.0, 15.0, 30.0)] + [("b", None, None),
                                                                                        ("c", None, None)]

        def fixture(kind, w, d):
            if kind == "a":
                return ((lambda e: -(e - d) ** 2 / (2.0 * w * w)),
                        math.log(w) - 0.5 * math.log(1.0 + w * w) - d * d / (2.0 * (1.0 + w * w)))
            if kind == "b":
                return (lambda e: np.zeros(np.shape(e))), 0.0
            x = 12.0 / math.sqrt(1.25)
            return (lambda e: ref_log_sf((12.0 + e) / 0.5)), math.log(0.5 * math.erfc(x / math.sqrt(2.0)))
        self.assertAlmostEqual(12.0 / math.sqrt(1.25), 10.7331263, places=7)
        worst = 0.0
        for kind, w, d in fixtures:
            loglik, exact = fixture(kind, w, d)
            r = ref_log_integral(loglik, 1.0)
            err = abs(r["log_I"] - exact)
            worst = max(worst, err)
            print(f"T6-11 ({kind}) w={w} d={d}: |log I^ - log I| {err:.2e}, certificate {r['certificate']:.2e} after "
                  f"{r['halvings']} halving(s) (final spacing {r['spacing']:g} SD), stopped at b = {r['b']:g} SD after "
                  f"{len(r['trace'])} step(s)", file=sys_.stderr)
            self.assertLessEqual(err, 1e-8, (kind, w, d))
            self.assertLessEqual(r["certificate"], REF_CERT, (kind, w, d))
            self.assertTrue(all(not t[3] for t in r["trace"][:-1]) and r["trace"][-1][3] and r["fine_bound_ok"])
            for b, bound, log_i, stop in r["trace"]:
                self.assertEqual(stop, bound <= math.log(REF_TAIL) + log_i)
            self.assertTrue(10.0 <= r["b"] <= 32.0, r["b"])
        for kind, w, d in (("a", 0.17, 30.0), ("c", None, None)):
            loglik, exact = fixture(kind, w, d)
            r = ref_log_integral(loglik, 1.0, tail=REF_TAIL_V4)
            print(f"T6-11 negative control, v4 budget ({kind}) w={w} d={d}: log I^ - log I = "
                  f"{r['log_I'] - exact:+.4e}, certificate {r['certificate']:.1e}", file=sys_.stderr)
            self.assertGreater(abs(r["log_I"] - exact), 1e-8)
            self.assertLess(abs(r["log_I"] - exact), 1e-6)
            self.assertLessEqual(r["certificate"], 1e-12)
        for kind, w, d in (("a", 0.17, 15.0), ("a", 0.17, 30.0), ("a", 1.0, 15.0), ("a", 1.0, 30.0), ("c", None, None)):
            with self.assertRaisesRegex(ValueError, "unrepresentable"):
                ref_log_integral(fixture(kind, w, d)[0], 1.0, cap=REF_START)
        x = np.array([REF_SF_SWITCH * (1 - 1e-15), REF_SF_SWITCH])
        v = ref_log_sf(x)
        self.assertLess(abs(v[0] - v[1]) / abs(v[1]), 1e-12)
        self.assertTrue(np.all(np.isfinite(ref_log_sf(np.array([40.0, 1e3, 1e8])))))
        self.assertEqual(float(ref_log_sf(np.array([math.inf]))[0]), -math.inf)


if __name__ == "__main__":
    unittest.main()

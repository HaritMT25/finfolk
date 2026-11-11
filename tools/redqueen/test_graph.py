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
            os.makedirs(out)
            base = dict(graph=os.path.join(gdir, "graph.jsonl.gz"), namespace="ns", fitter="minimal", ranks=1,
                        lambdas="0.1", iters=4, ab_cap=-1, set="main", jobs=1, start="registered")
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


if __name__ == "__main__":
    unittest.main()

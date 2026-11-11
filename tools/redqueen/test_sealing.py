#!/usr/bin/env python3
"""test_sealing.py: unit tests of sealing.py (the split manifest and endpoint identities, role filters,
registered support exceptions, exclusive commitments, the public freeze record and the byte-bound
test-evaluation gate).

    python3 -I tools/redqueen/test_sealing.py [-v]
"""
from __future__ import annotations

import contextlib
import gzip
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rqlib  # noqa: E402
import sealing  # noqa: E402

M = 1_000_000
SPLIT = {"C01": "train", "C02": "train", "C03": "train", "C04": "train", "C05": "val", "C06": "test",
         "A1": "train", "A2": "test"}
UUIDS = {w: str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:redqueen:ns-main:{w}")) for w in sorted(SPLIT)}
BR = {b: str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:redqueen:ns-forks:{b}")) for b in ("C06.o30M.s0", "C01.o30M.s0")}
SENT = "rq-sentinel-test"


def ref_entry(ns, world, frame, k):
    u = str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:redqueen:{ns}:{world}"))
    return {"world": world, "frame": frame, "uuid": u, "archive": f"/refs/{world}.json", "sha256": f"{k:02x}" * 32}


def wr(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def fixture(d):
    """A graph.py-like graph (meta + edges with support pairs), its worlds registry and a fork registry."""
    meta = {"schema": "finfolk.redqueen.graph/1", "namespace": "ns", "edges_sha256": "e" * 64, "split": SPLIT,
            "holdout": {"C01:1": "val", "C01:7": "test", "C02:0": "val", "C02:200": "test"},
            "fork": ["C01", "C05", "C06"], "intensive": ["C06"]}
    g = os.path.join(d, "graph")
    wr(os.path.join(g, "graph.meta.json"), json.dumps(meta))
    edges = [{"family": "support_c", "prey": "Q:C06:5", "pred": "P:C03:9", "role": "support", "horizon": "short"},
             {"family": "ref_prey", "prey": "Q:C05:2", "pred": "RP:3", "role": "support", "horizon": None},
             {"family": "within", "prey": "Q:C03:9", "pred": "P:C04:9", "role": "training", "horizon": None}]
    with gzip.open(os.path.join(g, "graph.jsonl.gz"), "wt") as f:
        f.write("".join(json.dumps(e) + "\n" for e in edges))
    wp = os.path.join(d, "worlds.json")
    wr(wp, json.dumps({"worlds": [{"id": w, "uuid": UUIDS[w]} for w in sorted(SPLIT)]}))
    fp = os.path.join(d, "forks.json")
    wr(fp, json.dumps({"worlds": [{"id": "C06.o30M.s0", "uuid": BR["C06.o30M.s0"],
                                   "root": "C06", "root_uuid": UUIDS["C06"]},
                                  {"id": "C01.o30M.s0", "uuid": BR["C01.o30M.s0"],
                                   "root": "C01", "root_uuid": UUIDS["C01"]}]}))
    rp = os.path.join(d, "references.json")
    wr(rp, json.dumps({"schema": "finfolk.redqueen.references/1", "namespace": SENT, "references": REFS}))
    return os.path.join(g, "graph.meta.json"), wp, fp


REFS = {f"R{g}:{k}": ref_entry(SENT, f"s{g}{k}", (10 + k) * M, 16 * (g == "P") + k) for g in "QP" for k in range(8)}


def E(role, pw, pf, qw=None, qf=None, rid=None, pe=None, qe=None, pref=None):
    r = {"id": rid or f"{pw}.{pf}~{qw}.{qf}", "role": role, "prey": dict({"world": pw, "frame": pf}, **(pe or {})),
         "predators": None if qw is None else dict({"world": qw, "frame": qf}, **(qe or {}))}
    if pref:
        r["predators"] = {"ref": pref}
    return r


def bound_mask(m, g):
    """A graph.py mask /2 of manifest m's graph g that its own evidence supports (graph.mask_problems passes): every
    world established (C02 at attempt 1), C06's prey zero at 5M (its 5M snapshot biological), the edge exclusions
    computed from the snapshots."""
    import graph as graphlib
    rs = m["worlds_registry_sha256"]
    est = {"decided": True, "disposition": "established", "why": "alive at the burn-in frame"}
    W = {w: {"uuid": u, "attempt": 0, "attempt_uuid": u, "burn_in": est, "valid_before": None, "first_terminal": None,
             "frontier": 200 * M, "refill": None, "available_sha256": {}} for w, u in m["uuids"].items()}
    W["C02"] = dict(W["C02"], attempt=1, attempt_uuid=sealing.attempt_uuid(UUIDS["C02"], 1))
    W["C06"] = dict(W["C06"], valid_before=5 * M, first_terminal={"frame": 5 * M, "kind": "prey"}, frontier=5 * M)
    S = {f"C06:{5 * M}": {"world": "C06", "time": 5, "frame": 5 * M, "status": "biological", "why": "at or after its zero",
                         "uuid": UUIDS["C06"], "attempt": 0, "snapshot": sealing.snapshot_uuid(UUIDS["C06"], 5 * M),
                         "valid_before": 5 * M}}
    ex, by = graphlib.edge_exclusions(g, S)
    n, ne = len(g["edges"]), sum(len(v) for v in ex.values())
    return {"schema": sealing.MASK_SCHEMA, "graph": {"edges_sha256": g["edges_sha256"], "namespace": g["namespace"], "edges": n},
            "registry": {"sha256": rs, "burn_in_frame": 5 * M, "max_restarts": 8},
            "block": {"sha256": "b" * 64, "registry_sha256": rs, "rederived": True},
            "worlds": W, "snapshots": S, "edges": {"scheduled": n, "executable": n - ne, **{k: len(v) for k, v in ex.items()}},
            "by_family_role": by, "excluded_edges": ex}


class TestManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mp, self.wp, self.fp = fixture(self.tmp)
        self.rp = os.path.join(self.tmp, "references.json")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_manifest_and_roles(self):
        m = sealing.manifest(self.mp, self.wp, self.fp)
        self.assertEqual(rqlib.canonical(m), rqlib.canonical(sealing.manifest(self.mp, self.wp, self.fp)))
        self.assertEqual(m["worlds"]["C05"], "validation")
        self.assertEqual(m["snapshot_holdouts"]["C01"], {"1": "validation", "7": "test"})
        self.assertEqual(m["support_exceptions"], [["Q:C05:2", "RP:3"], ["Q:C06:5", "P:C03:9"]])
        self.assertEqual(sealing.node_role(m, "C01", 1 * M), "validation")       # a held-out training snapshot
        self.assertEqual(sealing.node_role(m, "C01", 2 * M), "training")
        self.assertEqual(sealing.node_role(m, "C02", 1), "validation")           # F1 is t = 0
        self.assertEqual(sealing.node_role(m, "C06", 5 * M), "test")
        self.assertEqual(sealing.node_role(m, "C06.o30M.s0", 31 * M), "test")   # a branch: its root's split
        self.assertEqual(sealing.node_role(m, "C01.o30M.s0", 31 * M), "training")
        self.assertEqual(sealing.edge_role(m, {"world": "C01", "frame": 2 * M}, {"world": "C05", "frame": 2 * M}), "validation")
        self.assertEqual(sealing.edge_role(m, {"world": "C05", "frame": 2 * M}, {"world": "C01", "frame": 7 * M}), "test")
        with self.assertRaisesRegex(sealing.SealError, "not a snapshot time"):
            sealing.node_role(m, "C01", 1500)
        with self.assertRaisesRegex(sealing.SealError, "not in the split manifest"):
            sealing.node_role(m, "C99", M)
        bad = json.loads(rqlib.read_text(self.mp))
        bad["holdout"]["C05:3"] = "val"
        wr(self.mp, json.dumps(bad))
        with self.assertRaisesRegex(sealing.SealError, "not a training world"):
            sealing.manifest(self.mp, self.wp)
        wr(self.wp, json.dumps({"worlds": [{"id": w, "uuid": UUIDS[w]} for w in sorted(SPLIT)][:-1]}))
        wr(self.mp, json.dumps(dict(bad, holdout={})))
        with self.assertRaisesRegex(sealing.SealError, "not the registry's"):
            sealing.manifest(self.mp, self.wp)

    def test_layout_and_availability_receipt(self):
        """PR-D (Annex H D7 rule 34, D6 rule 27): the manifest records whether the graph's worlds are the registered
        64-world layout (--layout 64 refuses any other); an availability mask of the manifest's graph and a plan
        reconciliation of that mask are bound by an exclusively published receipt; another graph's mask or another
        mask's reconciliation is refused."""
        m = sealing.manifest(self.mp, self.wp, self.fp)
        self.assertFalse(m["layout"]["registered_64"])
        with self.assertRaisesRegex(sealing.SealError, "registered 64-world layout"):
            sealing.manifest(self.mp, self.wp, self.fp, require_layout=True)
        ws64 = [{"id": f"{t}{b}{i}", "treatment": t, "block": b} for b in range(1, 9)
                for t, n in (("C", 4), ("A", 2), ("B", 2)) for i in range(n)]
        lay = sealing.layout_of(ws64)
        self.assertEqual((lay["registered_64"], lay["per_treatment"], lay["worlds"]), (True, {"C": 32, "A": 16, "B": 16}, 64))
        old = [w for w in ws64 if not (w["treatment"] in "AB" and w["id"].endswith("1"))]        # (the 48 layout)
        self.assertFalse(sealing.layout_of(old)["registered_64"])
        # (a real graph.py graph, so the mask is checked against its edges; Codex #78 r2 P2-2)
        import graph as graphlib
        cg = os.path.join(self.tmp, "cg")
        graphlib.write({"schema": "finfolk.redqueen.graph/1", "namespace": "ns", "split": SPLIT, "holdout": {},
                        "worlds": [{"id": w, "treatment": w[0], "block": 1} for w in sorted(SPLIT)],
                        "fork": ["C06"], "intensive": [],
                        "edges": [("Q:C06:5", "P:C03:9", "support_c", "support", "short"),
                                  ("Q:C03:9", "P:C04:9", "within", "training", None),
                                  ("Q:C05:2", "P:C01:2", "cross", "training", None)]}, cg)
        gp = os.path.join(cg, "graph.jsonl.gz")
        g = graphlib.load(gp)
        m = sealing.manifest(os.path.join(cg, "graph.meta.json"), self.wp, self.fp)
        study = os.path.join(self.tmp, "study")
        sealing.publish_manifest(study, rqlib.canonical(m))
        rs, ge = m["worlds_registry_sha256"], m["graph"]["graph_edges_sha256"]
        mask = bound_mask(m, g)
        kp, rp = os.path.join(self.tmp, "mask.json"), os.path.join(self.tmp, "recon.json")
        wr(kp, json.dumps(mask))
        recon = {"schema": "finfolk.redqueen.reconciliation/1", "mask": {"sha256": rqlib.sha256_file(kp), "registry": {"sha256": rs}},
                 "plan_sha256": "a" * 64, "pending_plan": {"sha256": "c" * 64}, "scheduled": 6, "executable": 4,
                 "excluded": {"biological": 2, "technical": 0, "pending": 0}}
        wr(rp, json.dumps(recon))
        r = sealing.availability_receipt(study, kp, rp, gp)
        out = os.path.join(sealing.reg_dir(study), "availability", f"{rqlib.sha256_file(kp)}.{rqlib.sha256_file(rp)}.json")
        self.assertEqual(rqlib.read_bytes(out), rqlib.canonical(r))
        self.assertEqual((r["split_manifest_sha256"], r["reconciliation"]["sha256"], r["reconciliation"]["excluded"]["biological"]),
                         (rqlib.sha256_file(os.path.join(study, "config", "splits.json")), rqlib.sha256_file(rp), 2))
        self.assertEqual((r["worlds_registry_sha256"], r["attempts"]["C02"]["attempt"], r["mask"]["rederived"]), (rs, 1, True))
        self.assertEqual(sealing.availability_receipt(study, kp, rp, gp), r)      # (the same bytes again: accepted)
        # (Codex #78 r2 P2-2) the mask must be CONSISTENT with its own evidence and the graph's edges
        S, W0 = mask["snapshots"], mask["worlds"]
        for bad, msg in (({k: v for k, v in mask.items() if k != "snapshots"}, "consistent availability mask"),
                         (dict(mask, snapshots={}), "excluded edges"),
                         (dict(mask, worlds=dict(W0, C06=dict(W0["C06"], first_terminal=None))), "first terminal"),
                         (dict(mask, snapshots={k: dict(v, status="technical") for k, v in S.items()}), "but technical"),
                         (dict(mask, excluded_edges={"biological": [], "technical": [], "pending": []}), "excluded edges")):
            wr(kp + ".y", json.dumps(bad))
            with self.assertRaisesRegex(sealing.SealError, msg):
                sealing.availability_receipt(study, kp + ".y", None, gp)
        with self.assertRaisesRegex(sealing.SealError, "needs --graph"):
            sealing.availability_receipt(study, kp, rp)
        with self.assertRaisesRegex(sealing.SealError, "not the manifest's graph"):
            sealing.availability_receipt(study, kp, rp, os.path.join(os.path.dirname(self.mp), "graph.jsonl.gz"))
        # (Codex #78 r1 P2-4) the same graph ids and topology, another study's registry / identities: refused
        W = mask["worlds"]
        for bad, msg in ((dict(mask, graph={"edges_sha256": "0" * 64}), "another graph"),
                         (dict(mask, registry={"sha256": "r" * 64}), "another histories registry"),
                         (dict(mask, block=dict(mask["block"], registry_sha256="r" * 64)), "another histories registry"),
                         (dict(mask, worlds=dict(W, C01=dict(W["C01"], uuid="u-other"))), "not the registered one"),
                         (dict(mask, worlds=dict(W, C02=dict(W["C02"], attempt=2))), "attempt identity"),
                         (dict(mask, worlds={k: v for k, v in W.items() if k != "C03"}), "not the manifest's"),
                         (dict(mask, schema="finfolk.redqueen.graphmask/1"), "not an availability mask")):
            wr(kp + ".x", json.dumps(bad))
            with self.assertRaisesRegex(sealing.SealError, msg):
                sealing.availability_receipt(study, kp + ".x", None, gp)
        for bad, msg in ((dict(recon, mask={"sha256": "0" * 64}), "another mask"),
                         (dict(recon, schema="x"), "not a plan reconciliation"),
                         (dict(recon, plan_sha256=None), "plan's and its pending plan's"),
                         (dict(recon, mask=dict(recon["mask"], registry={"sha256": "r" * 64})), "another histories registry")):
            wr(rp + ".x", json.dumps(bad))
            with self.assertRaisesRegex(sealing.SealError, msg):
                sealing.availability_receipt(study, kp, rp + ".x", gp)
        self.assertEqual(len(os.listdir(os.path.join(sealing.reg_dir(study), "availability"))), 1)   # (nothing else)
        # (P3) the production manifest needs its fork registry and reference assignment
        g64 = os.path.join(self.tmp, "g64")
        wr(os.path.join(g64, "graph.meta.json"), json.dumps({"worlds": ws64, "split": {w["id"]: "train" for w in ws64},
                                                            "holdout": {}, "edges_sha256": "e" * 64}))
        with open(os.path.join(g64, "graph.jsonl.gz"), "wb") as f:
            f.write(gzip.compress(b"", mtime=0))
        wp64 = os.path.join(self.tmp, "worlds64.json")
        wr(wp64, json.dumps({"worlds": [{"id": w["id"], "uuid": f"u-{w['id']}"} for w in ws64]}))
        self.assertTrue(sealing.manifest(os.path.join(g64, "graph.meta.json"), wp64)["layout"]["registered_64"])
        with self.assertRaisesRegex(sealing.SealError, "needs the fork registry"):
            sealing.manifest(os.path.join(g64, "graph.meta.json"), wp64, require_layout=True)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sealing.main(["availability", "--study", study, "--mask", kp, "--graph", gp]), 0)
        self.assertEqual(len(os.listdir(os.path.join(sealing.reg_dir(study), "availability"))), 2)

    def test_identity_binding(self):
        """#67 review 2: labels must agree with identities (the world's UUID, the snapshot UUID recipe; a
        branch binds to its own UUID and takes its root's split), refused before any role."""
        m = sealing.manifest(self.mp, self.wp, self.fp)
        ok = E("training", "C03", 9 * M, "C04", 9 * M, pe={"uuid": UUIDS["C03"],
                                                           "snapshot": sealing.snapshot_uuid(UUIDS["C03"], 9 * M)})
        self.assertEqual(sealing.record_problems(m, [ok]), [])
        alias = E("training", "C03", 9 * M, "C04", 9 * M, pe={"uuid": UUIDS["C06"]})      # C06's identity, C03's label
        self.assertTrue(any("is not C03's" in p for p in sealing.record_problems(m, [alias])))
        snap = E("training", "C03", 9 * M, "C04", 9 * M, pe={"snapshot": sealing.snapshot_uuid(UUIDS["C06"], 9 * M)})
        self.assertTrue(any("snapshot UUID" in p for p in sealing.record_problems(m, [snap])))
        br = E("training", "C06.o30M.s0", 31 * M, "C04", 9 * M,
               pe={"snapshot": sealing.snapshot_uuid(BR["C06.o30M.s0"], 31 * M)})
        self.assertTrue(any("makes it test" in p for p in sealing.record_problems(m, [br])))   # the root is test
        self.assertEqual(sealing.record_problems(m, [dict(br, role="test")]), [])

    def test_support_exceptions_and_filters(self):
        """#67 review 1: support only for registered exceptions; a target is never both evaluated and
        support; copies of one target keep one role; nuisance (H.8) takes training only."""
        m = sealing.manifest(self.mp, self.wp, refs_path=self.rp)
        rows = [E("training", "C03", 9 * M, "C04", 9 * M), E("validation", "C01", 1 * M, "C03", 9 * M),
                E("test", "C06", 6 * M, "C03", 9 * M), E("test", "C02", 200 * M),
                E("support", "C06", 5 * M, "C03", 9 * M), E("support", "C05", 2 * M, pref="RP:3"),
                E("audit", "C06", 7 * M, "C02", 3 * M), E("diagnostic", "C05", 50 * M)]
        self.assertEqual(sealing.record_problems(m, rows), [])
        self.assertEqual([r["role"] for r in sealing.stage_filter(m, rows, "fit")], ["training", "support", "support"])
        self.assertEqual([r["role"] for r in sealing.stage_filter(m, rows, "nuisance")], ["training"])
        self.assertEqual(len(sealing.stage_filter(m, rows, "test")), 2)
        collide = rows + [E("test", "C06", 5 * M, "C03", 9 * M, rid="leak")]   # the registered support pair as test
        probs = sealing.record_problems(m, collide)
        self.assertTrue(any("leak" in p and "support exception" in p for p in probs), probs)
        with self.assertRaisesRegex(sealing.SealError, "disagree"):
            sealing.stage_filter(m, collide, "fit")
        unreg = rows + [E("support", "C06", 6 * M, "C03", 9 * M, rid="sneak")]  # an unregistered support copy
        self.assertTrue(any("sneak" in p and "not a registered" in p for p in sealing.record_problems(m, unreg)))
        copies = rows + [E("training", "C05", 2 * M, pref="RP:3", rid="copy")]   # another copy, another role
        self.assertTrue(any("copy" in p for p in sealing.record_problems(m, copies)))
        wrong = rows + [E("training", "C05", 3 * M, "C03", 9 * M, rid="mislabel")]
        self.assertTrue(any("mislabel" in p and "validation" in p for p in sealing.record_problems(m, wrong)))
        # the CLI: the manifest is published once
        mf, rf, out = (os.path.join(self.tmp, x) for x in (os.path.join("st", "config", "splits.json"), "rows.jsonl",
                                                            "fit.jsonl"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(sealing.main(["manifest", "--graph-meta", self.mp, "--worlds", self.wp, "--references",
                                           self.rp, "--out", mf]), 0)
            wr(rf, "".join(json.dumps(r) + "\n" for r in rows))
            self.assertEqual(sealing.main(["filter", "--manifest", mf, "--records", rf, "--stage", "nuisance",
                                           "--out", out]), 0)
            wr(rf, "".join(json.dumps(r) + "\n" for r in collide))
            self.assertEqual(sealing.main(["check", "--manifest", mf, "--records", rf]), 2)
            g = json.loads(rqlib.read_text(self.mp))
            wr(self.mp, json.dumps(dict(g, fork=[])))
            self.assertEqual(sealing.main(["manifest", "--graph-meta", self.mp, "--worlds", self.wp, "--references",
                                           self.rp, "--out", mf]), 2)
            self.assertEqual(sealing.main(["manifest", "--graph-meta", self.mp, "--worlds", self.wp, "--references",
                                           self.rp, "--out", os.path.join(self.tmp, "elsewhere.json")]), 2)
        self.assertEqual(len(rqlib.read_text(out).splitlines()), 1)
        self.assertIn("never replaced", err.getvalue())

    def test_reference_assignment_and_random_source(self):
        """#67 review 2, finding 1: reference status only for a REGISTERED reference slot, never mixed with
        a world snapshot's identity (the test pair C06@6M x C03@9M relabelled with ref RQ:0 and declared
        training is refused); finding 2: the documented {"source": "random"} predator form."""
        m = sealing.manifest(self.mp, self.wp, refs_path=self.rp)
        self.assertEqual(sorted(m["references"]), sorted(REFS))
        test_pair = E("test", "C06", 6 * M, "C03", 9 * M, pe={"uuid": UUIDS["C06"],
                                                              "snapshot": sealing.snapshot_uuid(UUIDS["C06"], 6 * M)})
        self.assertEqual(sealing.record_problems(m, [test_pair]), [])
        leak = json.loads(json.dumps(test_pair))
        leak.update(id="relabelled", role="training")
        leak["prey"]["ref"] = "RQ:0"
        probs = sealing.record_problems(m, [test_pair, leak])
        self.assertTrue(any("relabelled" in p and "mixed with" in p for p in probs), probs)
        with self.assertRaisesRegex(sealing.SealError, "disagree"):
            sealing.stage_filter(m, [test_pair, leak], "fit")
        for bad_prey, why in (({"ref": "RQ:0", "world": "C06"}, "mixed with"), ({"ref": "RQ:0", "frame": 6 * M}, "mixed with"),
                              ({"ref": "RP:0"}, "not a Q reference"), ({"ref": "RQ:9"}, "not in the registered"),
                              ({"ref": "RQ:0", "uuid": UUIDS["C06"]}, "not the registered"),
                              ({"ref": "RQ:0", "source": "random"}, "mixed with")):
            r = {"id": "x", "role": "training", "prey": bad_prey, "predators": {"world": "C03", "frame": 9 * M}}
            self.assertTrue(any(why in p for p in sealing.record_problems(m, [r])), (bad_prey, sealing.record_problems(m, [r])))
        good = {"id": "g", "role": "training", "prey": {"ref": "RQ:0", "uuid": REFS["RQ:0"]["uuid"]},
                "predators": {"world": "C03", "frame": 9 * M}}
        self.assertEqual(sealing.record_problems(m, [good]), [])
        m0 = sealing.manifest(self.mp, self.wp)                            # no registered assignment
        self.assertTrue(any("not in the registered" in p for p in sealing.record_problems(m0, [good])))
        # the random-founder source: no held-out role of its own; world endpoints keep their checks
        rnd = [{"id": "r1", "role": "diagnostic", "prey": {"world": "C05", "frame": 50 * M}, "predators": {"source": "random"}},
               {"id": "r2", "role": "test", "prey": {"world": "C06", "frame": 6 * M}, "predators": {"source": "random"}},
               {"id": "r3", "role": "training", "prey": {"world": "C03", "frame": 9 * M}, "predators": {"source": "random"}}]
        self.assertEqual(sealing.record_problems(m, rnd), [])
        self.assertEqual([r["id"] for r in sealing.stage_filter(m, rnd + [test_pair], "fit")], ["r3"])
        self.assertEqual(sealing.edge_role(m, rnd[1]["prey"], rnd[1]["predators"]), "test")
        for bad in ({"id": "b1", "role": "training", "prey": {"world": "C06", "frame": 6 * M}, "predators": {"source": "random"}},
                    {"id": "b2", "role": "training", "prey": {"source": "random"}, "predators": None},
                    {"id": "b3", "role": "training", "prey": {"world": "C03", "frame": 9 * M},
                     "predators": {"source": "random", "world": "C04", "frame": 9 * M}}):
            self.assertTrue(sealing.record_problems(m, [bad]), bad)
        # the scripted Stage A benchmark source (Annex H D7, PR-A): like random, no held-out role of its own,
        # a predator source only and exactly that dict; a distinct identity from the random source (one prey
        # with random and with scripted predators is two targets, so their differing roles do not conflict)
        scr = [{"id": "s1", "role": "test", "prey": {"world": "C06", "frame": 6 * M}, "predators": {"source": "scripted"}},
               {"id": "s2", "role": "training", "prey": {"world": "C03", "frame": 9 * M}, "predators": {"source": "scripted"}},
               {"id": "s3", "role": "diagnostic", "prey": {"world": "C03", "frame": 9 * M}, "predators": {"source": "random"}}]
        self.assertEqual(sealing.record_problems(m, scr), [])
        self.assertEqual(sealing.resolve(m, {"source": "scripted"}, "P"), ("scripted", None))
        self.assertEqual(sealing.edge_role(m, scr[0]["prey"], scr[0]["predators"]), "test")
        self.assertEqual([r["id"] for r in sealing.stage_filter(m, scr + [test_pair], "fit")], ["s2"])
        for bad, why in (({"id": "c1", "role": "training", "prey": {"world": "C06", "frame": 6 * M},
                           "predators": {"source": "scripted"}}, "most held-out endpoint makes it test"),
                         ({"id": "c2", "role": "training", "prey": {"source": "scripted"}, "predators": None}, "only a predator"),
                         ({"id": "c3", "role": "training", "prey": {"world": "C03", "frame": 9 * M},
                           "predators": {"source": "scripted", "k": 4}}, "only a predator"),
                         ({"id": "c4", "role": "training", "prey": {"world": "C03", "frame": 9 * M},
                           "predators": {"source": "neural"}}, "only a predator")):
            probs = sealing.record_problems(m, [bad])
            self.assertTrue(any(why in p for p in probs), (bad, probs))
        # the assignment itself: eight per guild, distinct, from the sentinel namespace, never a study identity
        def refs_file(refs, ns=SENT):
            wr(self.rp, json.dumps({"schema": "finfolk.redqueen.references/1", "namespace": ns, "references": refs}))
        bad = dict(REFS)
        bad.pop("RP:7")
        refs_file(bad)
        with self.assertRaisesRegex(sealing.SealError, "eight RP"):
            sealing.manifest(self.mp, self.wp, refs_path=self.rp)
        # #67 round 3: Codex's counterexample, RQ:0 = the test fork branch C06.o30M.s0 at 31M (its uuid and
        # snapshot), with the fork registry: refused
        alias = dict(REFS, **{"RQ:0": dict(REFS["RQ:0"], uuid=BR["C06.o30M.s0"], frame=31 * M,
                                           snapshot=sealing.snapshot_uuid(BR["C06.o30M.s0"], 31 * M))})
        refs_file(alias)
        with self.assertRaises(sealing.SealError):
            sealing.manifest(self.mp, self.wp, self.fp, refs_path=self.rp)
        # ... and a sentinel-form reference that IS a study identity (the forks' or the main namespace's
        # world): the collision check itself
        for ns, world, frame, owner in (("ns-forks", "C06.o30M.s0", 31 * M, "fork branch C06.o30M.s0"),
                                        ("ns-main", "C01", 9 * M, "world C01")):
            allns = {f"R{g}:{k}": ref_entry(ns, f"s{g}{k}", (10 + k) * M, 16 * (g == "P") + k) for g in "QP" for k in range(8)}
            refs_file(dict(allns, **{"RQ:0": ref_entry(ns, world, frame, 0)}), ns=ns)
            with self.assertRaisesRegex(sealing.SealError, f"collides with a study identity \\({owner}"):
                sealing.manifest(self.mp, self.wp, self.fp, refs_path=self.rp)
        refs_file(dict(REFS, **{"RQ:1": dict(REFS["RQ:1"], uuid=REFS["RQ:2"]["uuid"])}))
        with self.assertRaisesRegex(sealing.SealError, "not sentinel world"):
            sealing.manifest(self.mp, self.wp, refs_path=self.rp)
        refs_file(REFS, ns="")
        with self.assertRaisesRegex(sealing.SealError, "sentinel namespace"):
            sealing.manifest(self.mp, self.wp, refs_path=self.rp)
        wr(self.wp, json.dumps({"namespace": SENT, "worlds": [{"id": w, "uuid": UUIDS[w]} for w in sorted(SPLIT)]}))
        refs_file(REFS)
        with self.assertRaisesRegex(sealing.SealError, "main registry's"):
            sealing.manifest(self.mp, self.wp, refs_path=self.rp)


COMPETE = """
import sys
sys.path.insert(0, sys.argv[1])
import sealing
try:
    r = sealing.commit(sys.argv[2], "validation", sys.argv[3])
    print("OK", r["sha256"])
except sealing.SealError as e:
    print("REFUSED", e)
"""


class TestCommitments(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.study = os.path.join(self.tmp, "study")
        mp, wp, _ = fixture(self.tmp)
        os.makedirs(os.path.join(self.study, "config"))
        rqlib.write_durable(os.path.join(self.study, "config", "splits.json"), rqlib.canonical(sealing.manifest(mp, wp)))
        self.val = os.path.join(self.tmp, "val.jsonl")
        self.test = os.path.join(self.tmp, "test.jsonl")
        self.scores = os.path.join(self.tmp, "val_scores.json")
        self.script = os.path.join(self.tmp, "evaluate.py")
        self.prereg = os.path.join(self.tmp, "prereg.pdf")
        wr(self.val, '{"target_id": "v1", "mean": 0.1}\n{"target_id": "v2", "mean": 0.2}\n')
        wr(self.test, '{"target_id": "t1", "mean": 0.3}\n')
        wr(self.scores, '{"val_lpd": -0.25}\n')
        wr(self.script, "print('score')\n")
        wr(self.prereg, "the preregistration\n")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def commit_all(self):
        sealing.commit(self.study, "validation", self.val)
        sealing.open_validation(self.study, self.scores)
        return sealing.commit(self.study, "test", self.test, self.script)

    def test_order_and_immutability(self):
        with self.assertRaisesRegex(sealing.SealError, "after the validation"):
            sealing.commit(self.study, "test", self.test, self.script)
        r = sealing.commit(self.study, "validation", self.val)
        reg = os.path.join(self.study, "registration")
        self.assertEqual(rqlib.read_text(os.path.join(reg, "VAL_PRED_SHA")), rqlib.sha256_file(self.val) + "\n")
        self.assertEqual(sealing.commit(self.study, "validation", self.val)["sha256"], r["sha256"])     # idempotent
        with self.assertRaisesRegex(sealing.SealError, "open-validation"):
            sealing.commit(self.study, "test", self.test, self.script)          # chronology: the evaluation first
        wr(self.val, '{"target_id": "v1", "mean": 0.9}\n')
        with self.assertRaisesRegex(sealing.SealError, "never replaced"):
            sealing.commit(self.study, "validation", self.val)
        sealing.open_validation(self.study, self.scores)
        with self.assertRaisesRegex(sealing.SealError, "eval-script"):
            sealing.commit(self.study, "test", self.test)
        dup = os.path.join(self.tmp, "dup.jsonl")
        wr(dup, '{"target_id": "a"}\n{"target_id": "a"}\n')
        with self.assertRaisesRegex(sealing.SealError, "twice"):
            sealing.commit(self.study, "test", dup, self.script)
        t = sealing.commit(self.study, "test", self.test, self.script)
        self.assertEqual((t["evaluation_script_sha256"], t["VAL_PRED_SHA"]), (rqlib.sha256_file(self.script), r["sha256"]))
        with self.assertRaisesRegex(sealing.SealError, "already committed"):
            sealing.open_validation(self.study, self.scores)

    def test_competing_writers(self):
        """#67 review 4: two processes committing different validation predictions at once: one wins,
        the other is refused, and the marker is bound to its record."""
        alt = os.path.join(self.tmp, "val2.jsonl")
        wr(alt, '{"target_id": "v1", "mean": 0.7}\n')
        ps = [subprocess.Popen([sys.executable, "-I", "-c", COMPETE, HERE, self.study, f], stdout=subprocess.PIPE,
                               text=True) for f in (self.val, alt)]
        outs = [p.communicate()[0].strip() for p in ps]
        self.assertEqual(sorted(o.split()[0] for o in outs), ["OK", "REFUSED"], outs)
        mk, rec = sealing._bound(self.study, "validation")
        self.assertEqual(mk, rec["sha256"])
        self.assertIn(mk, [rqlib.sha256_file(self.val), rqlib.sha256_file(alt)])
        self.assertEqual([f for f in os.listdir(os.path.join(self.study, "registration")) if ".tmp." in f], [])
        rp = os.path.join(self.study, "registration", "validation_predictions.json")
        os.remove(rp)                                            # a sidecar not bound to its marker is refused
        rqlib.write_durable(rp, rqlib.canonical(dict(rec, sha256="0" * 64)))
        with self.assertRaisesRegex(sealing.SealError, "not bound"):
            sealing._bound(self.study, "validation")
        with self.assertRaisesRegex(sealing.SealError, "exists with other bytes"):
            sealing.publish(rp, b"something else")

    def test_directories_fsynced_under_the_lock(self):
        """#67 review 2, finding 3: the directory setup happens inside registration/.lock and every
        directory from the study's parent down is fsync'd whoever created it (here: all pre-existing)."""
        os.makedirs(os.path.join(self.study, "registration"))
        calls = []
        orig = sealing.rqlib.fsync_dir
        sealing.rqlib.fsync_dir = lambda d: (calls.append(os.path.abspath(d)), orig(d))[1]
        try:
            sealing.commit(self.study, "validation", self.val)
        finally:
            sealing.rqlib.fsync_dir = orig
        reg = os.path.abspath(os.path.join(self.study, "registration"))
        for d in (reg, os.path.abspath(self.study), os.path.dirname(os.path.abspath(self.study))):
            self.assertIn(d, calls)
        # the manifest takes the same lock: a held lock blocks its publication
        import fcntl
        import threading
        mp, wp, _ = fixture(os.path.join(self.tmp, "g2"))
        st2 = os.path.join(self.tmp, "st2")
        os.makedirs(os.path.join(st2, "registration"))
        lk = open(os.path.join(st2, "registration", ".lock"), "a")
        fcntl.flock(lk, fcntl.LOCK_EX)
        done = []
        th = threading.Thread(target=lambda: done.append(sealing.publish_manifest(st2, rqlib.canonical(
            sealing.manifest(mp, wp)))))
        th.start()
        th.join(0.5)
        self.assertEqual(done, [])                                        # waiting for the lock
        fcntl.flock(lk, fcntl.LOCK_UN)
        lk.close()
        th.join(10)
        self.assertEqual(done, [True])
        self.assertTrue(os.path.isfile(os.path.join(st2, "config", "splits.json")))

    def test_missing_study_parent_fsynced(self):
        """#67 round 3, finding 2: a study whose parent does not exist yet: the whole missing chain is
        fsync'd through its existing parent."""
        st = os.path.join(self.tmp, "new-parent", "study")
        calls = []
        orig = sealing.rqlib.fsync_dir
        sealing.rqlib.fsync_dir = lambda d: (calls.append(os.path.abspath(d)), orig(d))[1]
        try:
            sealing.commit(st, "validation", self.val)
        finally:
            sealing.rqlib.fsync_dir = orig
        for d in (os.path.join(st, "registration"), st, os.path.join(self.tmp, "new-parent"), self.tmp):
            self.assertIn(os.path.abspath(d), calls)

    def test_freeze_and_byte_bound_gate(self):
        """#67 review 3, 5, 7: the freeze needs the manifest, the OSF identifier and its registration time;
        the gate compares the manifest unconditionally and hands scoring the verified bytes."""
        self.commit_all()
        kw = dict(osf_url="https://osf.io/abc12", doi="10.17605/OSF.IO/ABC12", registered_utc=rqlib.now_utc())
        for t, why in (("2026-02-30T12:00:00Z", "not a real date"), ("2099-01-01T00:00:00Z", "in the future"),
                       ("2020-01-01T00:00:00Z", "precedes the validation evaluation"), ("2026-11-08 12:00", "YYYY-MM-DD")):
            with self.assertRaisesRegex(sealing.SealError, why):
                sealing.freeze(self.study, self.prereg, self.script, **dict(kw, registered_utc=t))
        with self.assertRaisesRegex(sealing.SealError, "registered-utc"):
            sealing.freeze(self.study, self.prereg, self.script, osf_url="https://osf.io/abc12")
        mp = os.path.join(self.study, "config", "splits.json")
        keep = rqlib.read_bytes(mp)
        os.remove(mp)
        with self.assertRaisesRegex(sealing.SealError, "requires the split manifest"):
            sealing.freeze(self.study, self.prereg, self.script, **kw)
        rqlib.write_durable(mp, keep)
        for bad in ({"osf_url": "http://example.com/x", "registered_utc": kw["registered_utc"]},
                    {"doi": "doi:10/x", "registered_utc": kw["registered_utc"]}):
            with self.assertRaisesRegex(sealing.SealError, "expected"):
                sealing.freeze(self.study, self.prereg, self.script, **bad)
        f = sealing.freeze(self.study, self.prereg, self.script, **kw)
        self.assertEqual((f["osf"]["registered_utc"], f["split_manifest_sha256"]),
                         (kw["registered_utc"], rqlib.sha256_bytes(keep)))
        with self.assertRaisesRegex(sealing.SealError, "never replaced"):
            sealing.freeze(self.study, self.prereg, self.script, **dict(kw, osf_url="https://osf.io/zzz99"))
        got = sealing.require_test_freeze(self.study, self.test, self.script)
        self.assertEqual(got["freeze"], json.loads(got["freeze_bytes"]))      # the record checked is returned
        # the gate checks the registration chronology too: a time before the validation opening, or after
        # the freeze record was made, is refused at the gate
        fp_ = os.path.join(self.study, "registration", "freeze.json")
        keep_f = rqlib.read_bytes(fp_)
        for t in ("2020-01-01T00:00:00Z", "2099-01-01T00:00:00Z"):
            os.chmod(fp_, 0o644)
            rqlib.write_durable(fp_, rqlib.canonical(dict(json.loads(keep_f), osf=dict(json.loads(keep_f)["osf"],
                                                                                         registered_utc=t))))
            with self.assertRaisesRegex(sealing.SealError, "registration time"):
                sealing.require_test_freeze(self.study, self.test, self.script)
        rqlib.write_durable(fp_, keep_f)
        self.assertEqual(got["freeze_bytes"], rqlib.read_bytes(os.path.join(self.study, "registration", "freeze.json")))
        wr(self.test, '{"target_id": "t1", "mean": 0.99}\n')          # replaced after the gate ...
        self.assertEqual(rqlib.sha256_bytes(got["predictions"]), f["TEST_PRED_SHA"])   # ... scoring uses these
        self.assertEqual(got["manifest"], keep)
        with self.assertRaisesRegex(sealing.SealError, "committed test predictions"):
            sealing.require_test_freeze(self.study, self.test, self.script)
        wr(self.test, '{"target_id": "t1", "mean": 0.3}\n')
        wr(mp, '{"schema": "finfolk.redqueen.splits/2", "changed": 1}\n')
        with self.assertRaisesRegex(sealing.SealError, "split manifest"):
            sealing.require_test_freeze(self.study, self.test, self.script)
        os.remove(mp)
        with self.assertRaisesRegex(sealing.SealError, "split manifest"):
            sealing.require_test_freeze(self.study, self.test, self.script)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = sealing.main(["verify-test", "--study", self.study, "--predictions", self.test, "--eval-script", self.script])
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED", err.getvalue())


if __name__ == "__main__":
    unittest.main()

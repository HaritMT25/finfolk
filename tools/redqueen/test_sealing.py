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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rqlib  # noqa: E402
import sealing  # noqa: E402

M = 1_000_000
SPLIT = {"C01": "train", "C02": "train", "C03": "train", "C04": "train", "C05": "val", "C06": "test",
         "A1": "train", "A2": "test"}
UUIDS = {w: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, w in enumerate(sorted(SPLIT), 1)}


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
    wr(fp, json.dumps({"worlds": [{"id": "C06.o30M.s0", "uuid": "00000000-0000-4000-8000-0000000000f6",
                                   "root": "C06", "root_uuid": UUIDS["C06"]},
                                  {"id": "C01.o30M.s0", "uuid": "00000000-0000-4000-8000-0000000000f1",
                                   "root": "C01", "root_uuid": UUIDS["C01"]}]}))
    return os.path.join(g, "graph.meta.json"), wp, fp


def E(role, pw, pf, qw=None, qf=None, rid=None, pe=None, qe=None, pref=None):
    r = {"id": rid or f"{pw}.{pf}~{qw}.{qf}", "role": role, "prey": dict({"world": pw, "frame": pf}, **(pe or {})),
         "predators": None if qw is None else dict({"world": qw, "frame": qf}, **(qe or {}))}
    if pref:
        r["predators"] = {"ref": pref}
    return r


class TestManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mp, self.wp, self.fp = fixture(self.tmp)

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
               pe={"snapshot": sealing.snapshot_uuid("00000000-0000-4000-8000-0000000000f6", 31 * M)})
        self.assertTrue(any("makes it test" in p for p in sealing.record_problems(m, [br])))   # the root is test
        self.assertEqual(sealing.record_problems(m, [dict(br, role="test")]), [])

    def test_support_exceptions_and_filters(self):
        """#67 review 1: support only for registered exceptions; a target is never both evaluated and
        support; copies of one target keep one role; nuisance (H.8) takes training only."""
        m = sealing.manifest(self.mp, self.wp)
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
        mf, rf, out = (os.path.join(self.tmp, x) for x in ("splits.json", "rows.jsonl", "fit.jsonl"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(sealing.main(["manifest", "--graph-meta", self.mp, "--worlds", self.wp, "--out", mf]), 0)
            wr(rf, "".join(json.dumps(r) + "\n" for r in rows))
            self.assertEqual(sealing.main(["filter", "--manifest", mf, "--records", rf, "--stage", "nuisance",
                                           "--out", out]), 0)
            wr(rf, "".join(json.dumps(r) + "\n" for r in collide))
            self.assertEqual(sealing.main(["check", "--manifest", mf, "--records", rf]), 2)
            g = json.loads(rqlib.read_text(self.mp))
            wr(self.mp, json.dumps(dict(g, fork=[])))
            self.assertEqual(sealing.main(["manifest", "--graph-meta", self.mp, "--worlds", self.wp, "--out", mf]), 2)
        self.assertEqual(len(rqlib.read_text(out).splitlines()), 1)
        self.assertIn("never replaced", err.getvalue())


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

    def test_freeze_and_byte_bound_gate(self):
        """#67 review 3, 5, 7: the freeze needs the manifest, the OSF identifier and its registration time;
        the gate compares the manifest unconditionally and hands scoring the verified bytes."""
        self.commit_all()
        kw = dict(osf_url="https://osf.io/abc12", doi="10.17605/OSF.IO/ABC12", registered_utc="2026-11-11T12:00:00Z")
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

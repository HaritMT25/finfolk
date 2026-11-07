#!/usr/bin/env python3
"""test_sealing.py: unit tests of sealing.py (the split manifest, role filters, prediction
commitments, the public freeze record and the test-evaluation gate).

    python3 -I tools/redqueen/test_sealing.py [-v]
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rqlib  # noqa: E402
import sealing  # noqa: E402

M = 1_000_000


def wr(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def meta():
    """A graph.py-like meta: C01-C04 training, C05 validation, C06 test, A1 training, A2 test."""
    return {"schema": "finfolk.redqueen.graph/1", "namespace": "ns", "edges_sha256": "e" * 64,
            "split": {"C01": "train", "C02": "train", "C03": "train", "C04": "train", "C05": "val", "C06": "test",
                      "A1": "train", "A2": "test"},
            "holdout": {"C01:1": "val", "C01:7": "test", "C02:0": "val", "C02:200": "test"},
            "fork": ["C01", "C05", "C06"], "intensive": ["C06"]}


def E(role, pw, pf, qw=None, qf=None, rid=None):
    return {"id": rid or f"{pw}.{pf}~{qw}.{qf}", "role": role, "prey": {"world": pw, "frame": pf},
            "predators": None if qw is None else {"world": qw, "frame": qf}}


class TestManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mp = os.path.join(self.tmp, "graph.meta.json")
        wr(self.mp, json.dumps(meta()))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_manifest_and_roles(self):
        m = sealing.manifest(self.mp)
        self.assertEqual(rqlib.canonical(m), rqlib.canonical(sealing.manifest(self.mp)))
        self.assertEqual(m["worlds"]["C05"], "validation")
        self.assertEqual(m["snapshot_holdouts"]["C01"], {"1": "validation", "7": "test"})
        self.assertEqual(m["graph"]["sha256"], rqlib.sha256_file(self.mp))
        self.assertEqual(sealing.node_role(m, "C01", 1 * M), "validation")       # a held-out training snapshot
        self.assertEqual(sealing.node_role(m, "C01", 2 * M), "training")
        self.assertEqual(sealing.node_role(m, "C02", 1), "validation")           # F1 is t = 0
        self.assertEqual(sealing.node_role(m, "C06", 5 * M), "test")
        # an edge inherits its most held-out endpoint: test before validation before training
        self.assertEqual(sealing.edge_role(m, {"world": "C01", "frame": 2 * M}, {"world": "C05", "frame": 2 * M}), "validation")
        self.assertEqual(sealing.edge_role(m, {"world": "C05", "frame": 2 * M}, {"world": "C01", "frame": 7 * M}), "test")
        self.assertEqual(sealing.edge_role(m, {"world": "C03", "frame": 9 * M}, None), "training")
        with self.assertRaisesRegex(sealing.SealError, "not a snapshot time"):
            sealing.node_role(m, "C01", 1500)
        with self.assertRaisesRegex(sealing.SealError, "not in the split manifest"):
            sealing.node_role(m, "C99", M)
        bad = meta()
        bad["holdout"]["C05:3"] = "val"                                           # a holdout outside training
        wr(self.mp, json.dumps(bad))
        with self.assertRaisesRegex(sealing.SealError, "not a training world"):
            sealing.manifest(self.mp)
        wp = os.path.join(self.tmp, "worlds.json")
        wr(self.mp, json.dumps(meta()))
        wr(wp, json.dumps({"worlds": [{"id": w} for w in meta()["split"]][:-1]}))
        with self.assertRaisesRegex(sealing.SealError, "not the registry's"):
            sealing.manifest(self.mp, wp)

    def test_check_and_filters(self):
        m = sealing.manifest(self.mp)
        rows = [E("training", "C03", 9 * M, "C04", 9 * M), E("validation", "C01", 1 * M, "C03", 9 * M),
                E("test", "C06", 5 * M, "C03", 9 * M), E("test", "C02", 200 * M), E("support", "C06", 5 * M, "C03", 9 * M),
                E("audit", "C06", 5 * M, "C02", 3 * M), E("diagnostic", "C05", 50 * M)]
        self.assertEqual(sealing.record_problems(m, rows), [])
        fit = sealing.stage_filter(m, rows, "fit")
        self.assertEqual([r["role"] for r in fit], ["training", "support"])       # never validation/test/audit
        self.assertEqual(len(sealing.stage_filter(m, rows, "test")), 2)
        self.assertEqual([r["role"] for r in sealing.stage_filter(m, rows, "audit")], ["audit"])
        wrong = rows + [E("training", "C05", 2 * M, "C03", 9 * M, rid="leak")]    # a validation edge labelled training
        probs = sealing.record_problems(m, wrong)
        self.assertTrue(len(probs) == 1 and "leak" in probs[0] and "validation" in probs[0], probs)
        with self.assertRaisesRegex(sealing.SealError, "disagree"):
            sealing.stage_filter(m, wrong, "fit")
        self.assertTrue(sealing.record_problems(m, [dict(rows[0], role="secret")]))
        with self.assertRaisesRegex(sealing.SealError, "stage"):
            sealing.stage_filter(m, rows, "peek")
        # the CLI
        mf, rf, out = (os.path.join(self.tmp, x) for x in ("splits.json", "rows.jsonl", "fit.jsonl"))
        self.assertEqual(sealing.main(["manifest", "--graph-meta", self.mp, "--out", mf]), 0)
        wr(rf, "".join(json.dumps(r) + "\n" for r in rows))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(sealing.main(["filter", "--manifest", mf, "--records", rf, "--stage", "fit", "--out", out]), 0)
            self.assertEqual(sealing.main(["check", "--manifest", mf, "--records", rf]), 0)
            wr(rf, "".join(json.dumps(r) + "\n" for r in wrong))
            self.assertEqual(sealing.main(["check", "--manifest", mf, "--records", rf]), 2)
            wr(self.mp, json.dumps(dict(meta(), fork=[])))                    # a changed graph meta
            self.assertEqual(sealing.main(["manifest", "--graph-meta", self.mp, "--out", mf]), 2)
        self.assertEqual(len(rqlib.read_text(out).splitlines()), 2)
        self.assertIn("never replaced", err.getvalue())


class TestCommitments(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.study = os.path.join(self.tmp, "study")
        wr(os.path.join(self.study, "config", "splits.json"), "{}\n")
        self.val = os.path.join(self.tmp, "val.jsonl")
        self.test = os.path.join(self.tmp, "test.jsonl")
        self.script = os.path.join(self.tmp, "evaluate.py")
        self.prereg = os.path.join(self.tmp, "prereg.pdf")
        wr(self.val, '{"target_id": "v1", "mean": 0.1}\n{"target_id": "v2", "mean": 0.2}\n')
        wr(self.test, '{"target_id": "t1", "mean": 0.3}\n')
        wr(self.script, "print('score')\n")
        wr(self.prereg, "the preregistration\n")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_order_and_immutability(self):
        with self.assertRaisesRegex(sealing.SealError, "after the validation"):
            sealing.commit(self.study, "test", self.test, self.script)
        r = sealing.commit(self.study, "validation", self.val)
        reg = os.path.join(self.study, "registration")
        self.assertEqual(rqlib.read_text(os.path.join(reg, "VAL_PRED_SHA")), rqlib.sha256_file(self.val) + "\n")
        self.assertEqual((r["targets"], r["sha256"]), (2, rqlib.sha256_file(self.val)))
        self.assertEqual(sealing.commit(self.study, "validation", self.val)["sha256"], r["sha256"])   # idempotent
        wr(self.val, '{"target_id": "v1", "mean": 0.9}\n')
        with self.assertRaisesRegex(sealing.SealError, "never replaced"):
            sealing.commit(self.study, "validation", self.val)
        with self.assertRaisesRegex(sealing.SealError, "eval-script"):
            sealing.commit(self.study, "test", self.test)
        dup = os.path.join(self.tmp, "dup.jsonl")
        wr(dup, '{"target_id": "a"}\n{"target_id": "a"}\n')
        with self.assertRaisesRegex(sealing.SealError, "twice"):
            sealing.commit(self.study, "test", dup, self.script)
        t = sealing.commit(self.study, "test", self.test, self.script)
        self.assertEqual((t["evaluation_script_sha256"], t["VAL_PRED_SHA"]), (rqlib.sha256_file(self.script), r["sha256"]))

    def test_freeze_and_gate(self):
        with self.assertRaisesRegex(sealing.SealError, "not committed yet"):
            sealing.freeze(self.study, self.prereg, self.script, osf_url="https://osf.io/abc12")
        self.assertTrue(sealing.test_problems(self.study, self.test, self.script))          # no freeze record
        sealing.commit(self.study, "validation", self.val)
        sealing.commit(self.study, "test", self.test, self.script)
        with self.assertRaisesRegex(sealing.SealError, "public registration"):
            sealing.freeze(self.study, self.prereg, self.script)
        for kw in ({"osf_url": "http://example.com/x"}, {"doi": "doi:10/x"}):
            with self.assertRaisesRegex(sealing.SealError, "expected"):
                sealing.freeze(self.study, self.prereg, self.script, **kw)
        other = os.path.join(self.tmp, "other.py")
        wr(other, "print('another')\n")
        with self.assertRaisesRegex(sealing.SealError, "differs from the one"):
            sealing.freeze(self.study, self.prereg, other, osf_url="https://osf.io/abc12")
        f = sealing.freeze(self.study, self.prereg, self.script, osf_url="https://osf.io/abc12",
                           doi="10.17605/OSF.IO/ABC12", registered_utc="2026-11-11T12:00:00Z")
        self.assertEqual((f["osf"]["doi"], f["TEST_PRED_SHA"]), ("10.17605/OSF.IO/ABC12", rqlib.sha256_file(self.test)))
        self.assertEqual(sealing.test_problems(self.study, self.test, self.script), [])
        sealing.require_test_freeze(self.study, self.test, self.script)
        with self.assertRaisesRegex(sealing.SealError, "never replaced"):
            sealing.freeze(self.study, self.prereg, self.script, osf_url="https://osf.io/zzz99")
        # the gate refuses other predictions, another script, a changed manifest
        alt = os.path.join(self.tmp, "alt.jsonl")
        wr(alt, '{"target_id": "t1", "mean": 0.31}\n')
        self.assertTrue(any("committed test predictions" in p for p in sealing.test_problems(self.study, alt, self.script)))
        self.assertTrue(any("frozen evaluation script" in p for p in sealing.test_problems(self.study, self.test, other)))
        wr(os.path.join(self.study, "config", "splits.json"), '{"changed": 1}\n')
        self.assertTrue(any("split manifest" in p for p in sealing.test_problems(self.study, self.test, self.script)))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = sealing.main(["verify-test", "--study", self.study, "--predictions", self.test, "--eval-script", self.script])
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED", err.getvalue())


if __name__ == "__main__":
    unittest.main()

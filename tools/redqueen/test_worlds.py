#!/usr/bin/env python3
"""test_worlds.py: unit tests of worlds.py that need no engine (the end-to-end ones are
tests/redqueen_worlds.sh).

    python3 -I tools/redqueen/test_worlds.py [-v]
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rqlib  # noqa: E402
import worlds  # noqa: E402

ARENA = {"schema": worlds.ARENA_SCHEMA, "status": "selected",
         "common": {"population": 600, "min-pop": 0, "max-pop": 600, "food-patches": 0, "target-food": 2000,
                    "food-spawn": 12, "food-amp": 0, "current": 0, "move-cost": 7e-05, "gene-cost": 0},
         "treatments": {
             "C": {"predators": 6, "predator-economy": True, "predator-brain": True, "predator-min-pop": 0,
                   "predator-max-pop": 40, "predator-max-age": 240, "predator-cooldown": 1.5, "predator-meal": 16},
             "B": {"predators": 6, "predator-economy": True, "predator-min-pop": 0, "predator-max-pop": 40,
                   "predator-max-age": 240, "predator-cooldown": 1.5, "predator-meal": 16},
             "A": {"predators": 8}}}


def wr(path, text):
    with open(path, "w") as f:
        f.write(text)


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.arena = os.path.join(self.tmp, "arena.json")
        wr(self.arena, json.dumps(ARENA))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_48_worlds_in_8_blocks(self):
        reg = worlds.register(self.arena, "rq2026-founders")
        ws = reg["worlds"]
        self.assertEqual(len(ws), 48)
        self.assertEqual({t: sum(1 for w in ws if w["treatment"] == t) for t in "CAB"}, {"C": 32, "A": 8, "B": 8})
        for b in range(1, 9):
            blk = [w for w in ws if w["block"] == b]
            self.assertEqual(sorted(w["treatment"] for w in blk), ["A", "B", "C", "C", "C", "C"])
        self.assertGreater(len({tuple(w["treatment"] for w in ws if w["block"] == b) for b in range(1, 9)}), 1,
                           "the within-block order is randomized")
        self.assertEqual([w["id"] for w in ws], [f"w{i:02d}" for i in range(1, 49)])
        self.assertEqual(len({w["founder_seed"] for w in ws}), 48)
        self.assertEqual(len({w["uuid"] for w in ws}), 48)
        self.assertEqual(rqlib.canonical(reg), rqlib.canonical(worlds.register(self.arena, "rq2026-founders")))
        self.assertNotEqual(ws[0]["founder_seed"], worlds.register(self.arena, "other-ns")["worlds"][0]["founder_seed"])
        c = next(w for w in ws if w["treatment"] == "C")
        self.assertIn("--predator-brain", c["config_args"])
        self.assertEqual(c["config_args"][-2:], ["--seed", str(c["founder_seed"])])
        self.assertTrue(c["predator_log"])
        a = next(w for w in ws if w["treatment"] == "A")
        self.assertNotIn("--predator-economy", a["config_args"])
        self.assertFalse(a["predator_log"])
        self.assertEqual(reg["schedule"], worlds.DEFAULT_SCHEDULE)

    def test_avoid(self):
        reg = worlds.register(self.arena, "ns-a")
        s1 = reg["worlds"][0]["founder_seed"]
        av = os.path.join(self.tmp, "avoid.jsonl")
        wr(av, json.dumps({"id": "x", "seeds": {"reseed": s1, "other": 5}}) + "\n")
        self.assertEqual(worlds.read_avoid(av), {s1, 5})
        reg2 = worlds.register(self.arena, "ns-a", avoid_paths=[av])
        self.assertNotEqual(reg2["worlds"][0]["founder_seed"], s1)
        self.assertEqual(reg2["worlds"][0]["seed_rederived"], 1)
        self.assertEqual(reg2["avoid"][0]["seeds"], 2)
        ints = os.path.join(self.tmp, "ints.txt")
        wr(ints, "1\n2\n3\n")
        self.assertEqual(worlds.read_avoid(ints), {1, 2, 3})

    def refused(self, mutate, msg, **kw):
        bad = json.loads(json.dumps(ARENA))
        mutate(bad)
        p = os.path.join(self.tmp, "bad.json")
        wr(p, json.dumps(bad))
        with self.assertRaisesRegex(worlds.WorldsError, msg):
            worlds.register(p, "ns", **kw)

    def test_refusals(self):
        self.refused(lambda a: a["treatments"]["C"].update({"predator-max-pop": "SELECTED_CAP"}), "unresolved")
        self.refused(lambda a: a.update(status="placeholder"), "placeholder")
        self.refused(lambda a: a["common"].update({"min-pop": 20}), "prey floor")
        self.refused(lambda a: a["treatments"]["B"].update({"predator-min-pop": 2}), "predator floor")
        self.refused(lambda a: a["treatments"]["C"].update({"predator-primer": True}), "predator-primer")
        self.refused(lambda a: a["treatments"]["C"].pop("predator-max-age"), "positive --predator-max-age")
        self.refused(lambda a: a["treatments"]["B"].update({"predator-brain": True}), "B: scripted")
        self.refused(lambda a: a["treatments"]["A"].update({"predator-economy": True}), "A: scripted")
        self.refused(lambda a: a["treatments"]["A"].update({"predators": 0}), "fixed positive")
        self.refused(lambda a: a["common"].update({"seed": 5}), "set by worlds.py")
        self.refused(lambda a: a.update(schema="x"), "schema")
        with self.assertRaises(worlds.WorldsError):
            worlds.register(self.arena, "ns", schedule={"total_steps": 1000, "checkpoint_every": 300, "log_every": 100})
        ph = json.loads(json.dumps(ARENA))
        ph.update(status="placeholder")
        ph["treatments"]["C"]["predator-max-pop"] = "SELECTED_CAP"
        p = os.path.join(self.tmp, "ph.json")
        wr(p, json.dumps(ph))
        reg = worlds.register(p, "ns", allow_placeholder=True)
        self.assertEqual(reg["arena"]["status"], "placeholder")
        root = os.path.join(self.tmp, "root")
        os.makedirs(os.path.join(root, "config"))
        rqlib.write_durable(os.path.join(root, "config", "worlds.json"), rqlib.canonical(reg))
        with self.assertRaisesRegex(worlds.WorldsError, "placeholder"):
            worlds.load_registry(root)
        self.assertEqual(worlds.load_registry(root, allow_placeholder=True)["namespace"], "ns")

    def test_per_block(self):
        self.assertEqual(worlds.parse_per_block("C=1,A=1"), {"C": 1, "A": 1, "B": 0})
        with self.assertRaises(worlds.WorldsError):
            worlds.parse_per_block("D=1")
        reg = worlds.register(self.arena, "ns", blocks=2, per_block={"C": 1, "A": 0, "B": 1})
        self.assertEqual([w["treatment"] for w in reg["worlds"]].count("C"), 2)

    def test_flags_to_args(self):
        self.assertEqual(worlds.flags_to_args({"a": True, "b": False, "c": 3, "d": 7e-05, "e": "x"}),
                         ["--a", "--c", "3", "--d", "7e-05", "--e", "x"])

    def test_segment_args(self):
        reg = worlds.register(self.arena, "ns")
        c = next(w for w in reg["worlds"] if w["treatment"] == "C")
        s = reg["schedule"]
        fresh = worlds.segment_args(c, s, "seg000", 0)
        self.assertEqual(fresh[:len(c["config_args"])], c["config_args"])
        self.assertIn("--predator-log", fresh)
        self.assertEqual(fresh[fresh.index("--headless") + 1], "200000000")
        res = worlds.segment_args(c, s, "seg001", 3_000_000, "ckpt/end.3000000.json")
        self.assertEqual(res[:2], ["--load-checkpoint", "ckpt/end.3000000.json"])
        self.assertNotIn("--seed", res)        # never reseeded: the checkpoint's streams continue
        self.assertEqual(res[res.index("--headless") + 1], "197000000")
        self.assertEqual(res[res.index("--csv") + 1], "seg001/run.csv")


class TestLogs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_contiguous_and_tails(self):
        self.assertEqual(worlds._contiguous_until([500, 1000, 1500, 2500], 0, 500), 1500)
        self.assertEqual(worlds._contiguous_until([], 4000, 500), 4000)
        self.assertEqual(worlds._contiguous_until([4500, 5000], 4000, 500), 5000)
        p = os.path.join(self.tmp, "run.csv")
        wr(p, "step,population\n500,10\n1000,9\n15")        # a torn last line
        hdr, rows = worlds._rows(p)
        self.assertEqual((hdr, rows), (["step", "population"], [["500", "10"], ["1000", "9"]]))
        self.assertEqual(worlds._last_row(p), (["step", "population"], ["1000", "9"]))
        t = worlds.Tail(p)
        self.assertEqual(t.lines(), [["500", "10"], ["1000", "9"]])
        self.assertEqual(t.header, ["step", "population"])
        self.assertEqual(t.lines(), [])
        with open(p, "a") as f:
            f.write("00,8\n2000,7\n")
        self.assertEqual(t.lines(), [["1500", "8"], ["2000", "7"]])
        big = os.path.join(self.tmp, "big.csv")
        wr(big, "step,x\n" + "".join(f"{i * 500},{i}\n" for i in range(1, 20000)))
        self.assertEqual(worlds._last_row(big)[1], ["9999500", "19999"])

    def test_labels_and_records(self):
        self.assertEqual(worlds.label_of(1), "F1")
        self.assertEqual(worlds.label_of(3000000), "end.3000000")
        root = os.path.join(self.tmp, "root")
        os.makedirs(os.path.join(root, "worlds", "w01"))
        p = os.path.join(root, "worlds", "w01", "archive.jsonl")
        worlds._append_durable(p, {"label": "F1", "frame": 1, "sha256": "a" * 64})
        with open(p, "a") as f:
            f.write('{"label": "end.4')                    # a torn last record: that copy is redone
        self.assertEqual(list(worlds.archive_records(root, "w01")), ["F1"])


if __name__ == "__main__":
    unittest.main()

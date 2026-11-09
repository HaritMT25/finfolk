#!/usr/bin/env python3
"""test_val_block.py: val_block.py, the worlds block of the validation run's layout (runner_val.py): the
current attempt only (a distinct uuid for a restarted world), every checkpoint opened (a mismatched one is
not archived), the founding F1 snapshot only when it is frame 1, the first main-CSV zero over the attempt's
segments (a torn last line ignored), and the CLI. Extracted from #69 (Annex H D7 rule 39). Pure Python.

    python3 -I tools/redqueen/test_val_block.py [-v]
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
import uuid as uuidlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rqlib  # noqa: E402
import val_block  # noqa: E402


def layout(tmp):
    """A runner_val.py layout: twelve worlds; w05 restarted (attempt 1); w03 without a founding snapshot,
    w06's not at frame 1; w07's 40M checkpoint at another frame; w04's prey reach 0 at 63M."""
    root = os.path.join(tmp, "validation")
    ws = []
    for i, T in enumerate(["C", "A", "B", "C", "C", "C", "C", "B", "A", "C", "C", "C"]):
        ws.append({"id": f"w{i + 1:02d}", "uuid": f"00000000-0000-0000-0000-{i + 1:012d}", "treatment": T,
                   "block": i // 6 + 1})
    os.makedirs(os.path.join(root, "config"))
    with open(os.path.join(root, "config", "worlds.json"), "w") as f:
        json.dump({"worlds": ws}, f)
    for w in ws:
        k = 1 if w["id"] == "w05" else 0
        base = os.path.join(root, "worlds", w["id"])
        ad = os.path.join(base, f"a{k}")
        os.makedirs(os.path.join(ad, "runs"))
        with open(os.path.join(base, "state.json"), "w") as f:
            json.dump({"attempt": k}, f)
        if w["id"] != "w03":
            with open(os.path.join(ad, "F1.json"), "w") as f:
                json.dump({"world": {"frame": 1 if w["id"] != "w06" else 2}}, f)
        for t in range(1, 101):
            fr = t * 1_000_000 if not (w["id"] == "w07" and t == 40) else 1
            with open(os.path.join(ad, f"end.{t * 1_000_000}.json"), "w") as f:
                json.dump({"world": {"frame": fr}}, f)
        zero = 63_000_000 if w["id"] == "w04" else None
        with open(os.path.join(ad, "runs", "seg000.csv"), "w") as f:
            f.write("step,elapsed_s,population,predator_pop\n")
            for fr in range(5_000_000, 60_000_001, 5_000_000):
                f.write(f"{fr},1.0,500,10\n")
        with open(os.path.join(ad, "runs", "seg001.csv"), "w") as f:
            f.write("step,elapsed_s,population,predator_pop\n")
            for fr in range(60_000_000, 101_000_000, 1_000_000):
                f.write(f"{fr},1.0,{0 if zero and fr >= zero else 500},10\n")
            f.write("101000")                                     # (a torn last line)
        if w["id"] == "w04":
            open(os.path.join(ad, "extinct"), "w").close()
    return root, ws


class TestValBlock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root, self.ws = layout(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_block_from_the_validation_layout(self):
        b = val_block.block(self.root)
        v = b["worlds"]
        self.assertEqual(b["schema"], val_block.SCHEMA)
        self.assertEqual(b["registry_sha256"], rqlib.sha256_file(os.path.join(self.root, "config", "worlds.json")))
        self.assertEqual(v["w05"]["uuid"], str(uuidlib.uuid5(uuidlib.NAMESPACE_URL,
                                                             "finfolk:attempt:00000000-0000-0000-0000-000000000005:1")))
        self.assertEqual((v["w05"]["attempt"], v["w01"]["uuid"]), (1, self.ws[0]["uuid"]))
        self.assertEqual(v["w04"]["valid_before"], 63_000_000)
        self.assertEqual(v["w04"]["status"], "extinct")
        self.assertIsNone(v["w01"]["valid_before"])
        self.assertEqual(v["w01"]["status"], "running")
        self.assertNotIn(40_000_000, v["w07"]["archived"])
        self.assertEqual(len(v["w01"]["archived"]), 101)                  # (F1 and 1..100M)
        self.assertEqual(b["times"]["F1"], 1)
        self.assertEqual(b["times"]["200M"], 200_000_000)
        self.assertEqual(v["w01"]["paths"]["F1"], os.path.join(self.root, "worlds", "w01", "a0", "F1.json"))
        self.assertEqual(v["w01"]["archived"][0], 1)
        for bad in ("w03", "w06"):                                        # (missing / not frame 1)
            self.assertEqual((v[bad]["paths"], 1 in v[bad]["archived"]), ({}, False))
        self.assertTrue(v["w05"]["pattern"].endswith(os.path.join("w05", "a1", "end.{frame}.json")))
        self.assertEqual((v["w02"]["treatment"], v["w07"]["block"]), ("A", 2))

    def test_refusals_and_cli(self):
        bad = os.path.join(self.root, "worlds", "w02", "a0", "runs", "seg000.csv")
        with open(bad, "w") as f:
            f.write("step,elapsed_s,prey\n5000000,1.0,500\n")
        with self.assertRaisesRegex(val_block.BlockError, "no population / predator_pop"):
            val_block.block(self.root)
        os.remove(bad)
        shutil.rmtree(os.path.join(self.root, "worlds", "w09", "a0"))
        with self.assertRaisesRegex(val_block.BlockError, "w09: no directory for its attempt 0"):
            val_block.block(self.root)
        os.makedirs(os.path.join(self.root, "worlds", "w09", "a0"))
        out = os.path.join(self.tmp, "block.json")
        with contextlib.redirect_stdout(io.StringIO()) as so:
            self.assertEqual(val_block.main(["--root", self.root, "--out", out]), 0)
        self.assertEqual(rqlib.read_json(out)["worlds"]["w09"]["archived"], [])
        self.assertIn("w04 C a0 extinct", so.getvalue())


if __name__ == "__main__":
    unittest.main()

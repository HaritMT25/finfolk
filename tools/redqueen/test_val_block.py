#!/usr/bin/env python3
"""test_val_block.py: val_block.py, the worlds block of the validation run's layout (runner_val.py): the
current attempt only (a distinct uuid for a restarted world), every checkpoint opened (a mismatched one is
not archived), the founding F1 snapshot only when it is frame 1, and the OBSERVATION CHAIN (Codex #74 r1
P2-1/2; Annex H D6 rule 24): an unterminated trailing record is never evidence, superseded segment tails are
clipped by the resume frames of the segments' command lines, and a missing runs/ or CSV, interior damage,
short rows or a chain without a fresh segment end the observations (technical unavailability, never "no
zero"). Extracted from #69 (Annex H D7 rule 39). Pure Python.

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

M = 1_000_000
L = M                                       # (the fixtures log every 1M frames: small files, the same rules)
HEAD = "step,elapsed_s,population,predator_pop\n"


def rows(lo, hi, zero=None, prey_zero=False):
    """Main-CSV rows lo..hi (every L), a guild at 0 from `zero` on."""
    out = []
    for f in range(lo, hi + 1, L):
        z = zero is not None and f >= zero
        out.append(f"{f},1.0,{0 if z and prey_zero else 500},{0 if z and not prey_zero else 10}\n")
    return "".join(out)


def segment(ad, k, start, body, tail=""):
    """seg<k>.cmd (a resume from `start`, or fresh) and runs/seg<k>.csv (its header, body and a raw tail)."""
    load = f" --load-checkpoint end.{start}.json --headless {100 * M - start}" if start else f" --headless {100 * M}"
    with open(os.path.join(ad, f"seg{k:03d}.cmd"), "w") as f:
        f.write(f"/bin/evo_boids_fast --no-render --log-every 5000{load} --name seg{k:03d}\n")
    os.makedirs(os.path.join(ad, "runs"), exist_ok=True)
    with open(os.path.join(ad, "runs", f"seg{k:03d}.csv"), "w") as f:
        f.write(HEAD + body + tail)


def layout(tmp):
    """A runner_val.py layout: twelve worlds, each seg000 (fresh, 1M..60M) and seg001 (resumed from 60M,
    61M..100M, a torn last line); w05 restarted (attempt 1); w03 without a founding snapshot, w06's not at
    frame 1; w07's 40M checkpoint at another frame; w04's predators reach 0 at 63M."""
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
        os.makedirs(ad)
        with open(os.path.join(base, "state.json"), "w") as f:
            json.dump({"attempt": k}, f)
        if w["id"] != "w03":
            with open(os.path.join(ad, "F1.json"), "w") as f:
                json.dump({"world": {"frame": 1 if w["id"] != "w06" else 2}}, f)
        for t in range(1, 101):
            fr = t * M if not (w["id"] == "w07" and t == 40) else 1
            with open(os.path.join(ad, f"end.{t * M}.json"), "w") as f:
                json.dump({"world": {"frame": fr}}, f)
        zero = 63 * M if w["id"] == "w04" else None
        segment(ad, 0, 0, rows(L, 60 * M))
        segment(ad, 1, 60 * M, rows(61 * M, 100 * M, zero), tail="101000")      # (a torn last line)
        if w["id"] == "w04":
            open(os.path.join(ad, "extinct"), "w").close()
    return root, ws


def adir(root, w, k=0):
    return os.path.join(root, "worlds", w, f"a{k}")


class TestValBlock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root, self.ws = layout(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def block(self):
        return val_block.block(self.root, log_every=L)

    def test_block_from_the_validation_layout(self):
        b = self.block()
        v = b["worlds"]
        self.assertEqual(b["schema"], val_block.SCHEMA)
        self.assertEqual(b["registry_sha256"], rqlib.sha256_file(os.path.join(self.root, "config", "worlds.json")))
        self.assertEqual(v["w05"]["uuid"], str(uuidlib.uuid5(uuidlib.NAMESPACE_URL,
                                                             "finfolk:attempt:00000000-0000-0000-0000-000000000005:1")))
        self.assertEqual((v["w05"]["attempt"], v["w01"]["uuid"]), (1, self.ws[0]["uuid"]))
        self.assertEqual(v["w04"]["valid_before"], 63 * M)
        self.assertEqual(v["w04"]["status"], "extinct")
        self.assertIsNone(v["w01"]["valid_before"])
        self.assertEqual((v["w01"]["status"], v["w01"]["observed_through"], v["w01"]["technical"]),
                         ("running", 100 * M, []))
        self.assertEqual([(c["segment"], c["start_frame"], c["until"], c["through"]) for c in v["w01"]["chain"]],
                         [("seg000", 0, 60 * M, 60 * M), ("seg001", 60 * M, None, 100 * M)])
        raw = rqlib.read_bytes(os.path.join(adir(self.root, "w01"), "runs", "seg001.csv"))
        self.assertEqual(v["w01"]["chain"][1]["csv_sha256"], rqlib.sha256_bytes(raw[: raw.rfind(b"\n") + 1]))
        self.assertNotIn(40 * M, v["w07"]["archived"])
        self.assertEqual((len(v["w01"]["archived"]), v["w01"]["unobserved"]), (101, []))   # (F1 and 1..100M)
        self.assertEqual(b["times"]["F1"], 1)
        self.assertEqual(b["times"]["200M"], 200 * M)
        self.assertEqual(v["w01"]["paths"]["F1"], os.path.join(adir(self.root, "w01"), "F1.json"))
        self.assertEqual(v["w01"]["archived"][0], 1)
        for bad in ("w03", "w06"):                                        # (missing / not frame 1)
            self.assertEqual((v[bad]["paths"], 1 in v[bad]["archived"]), ({}, False))
        self.assertTrue(v["w05"]["pattern"].endswith(os.path.join("w05", "a1", "end.{frame}.json")))
        self.assertEqual((v["w02"]["treatment"], v["w07"]["block"]), ("A", 2))

    def test_an_unterminated_record_is_never_evidence(self):
        """P2-1: a torn zero of the header's width, in sequence, is no zero; once terminated, it is."""
        p = os.path.join(adir(self.root, "w01"), "runs", "seg001.csv")
        with open(p, "w") as f:
            f.write(HEAD + rows(61 * M, 100 * M) + "101000000,1.0,500,0")
        v = self.block()["worlds"]["w01"]
        self.assertEqual((v["valid_before"], v["observed_through"], v["technical"]), (None, 100 * M, []))
        with open(p, "a") as f:
            f.write("\n")
        self.assertEqual(self.block()["worlds"]["w01"]["valid_before"], 101 * M)

    def test_superseded_tails_are_clipped(self):
        """P2-2: seg000 ran past 60M and saw a zero at 62M, but seg001 resumed from 60M: that tail is no
        evidence. A later rollback (seg002 resumed from 40M) supersedes seg001 entirely, zero included."""
        ad = adir(self.root, "w08")
        segment(ad, 0, 0, rows(L, 62 * M, zero=62 * M, prey_zero=True))
        v = self.block()["worlds"]["w08"]
        self.assertEqual((v["valid_before"], v["observed_through"], v["technical"]), (None, 100 * M, []))
        segment(ad, 1, 60 * M, rows(61 * M, 75 * M, zero=70 * M))
        segment(ad, 2, 40 * M, rows(41 * M, 100 * M))
        v = self.block()["worlds"]["w08"]
        self.assertEqual((v["valid_before"], v["observed_through"], v["technical"]), (None, 100 * M, []))
        self.assertEqual([(c["segment"], c["until"]) for c in v["chain"]], [("seg000", 40 * M), ("seg002", None)])
        segment(ad, 2, 40 * M, rows(41 * M, 100 * M, zero=80 * M))     # (the chain's own zero is evidence)
        self.assertEqual(self.block()["worlds"]["w08"]["valid_before"], 80 * M)

    def test_gaps_are_technical_unavailability(self):
        """P2-2: interior damage, a missing CSV, missing runs/, rows short of the resume frame and a chain
        without a fresh segment end the observations; the checkpoints past them are unobserved."""
        p = os.path.join(adir(self.root, "w09"), "runs", "seg000.csv")
        with open(p) as f:
            text = f.read()
        with open(p, "w") as f:
            f.write(text.replace("30000000,1.0,500,10\n", "30000000,1.0,5x0,10\n"))
        os.remove(os.path.join(adir(self.root, "w10"), "runs", "seg001.csv"))
        shutil.rmtree(os.path.join(adir(self.root, "w11"), "runs"))
        segment(adir(self.root, "w02"), 0, 0, rows(L, 55 * M))
        os.remove(os.path.join(adir(self.root, "w12"), "seg000.cmd"))
        v = self.block()["worlds"]
        for w, through, why in (("w09", 29 * M, "damaged or out-of-sequence"), ("w10", 60 * M, "no main CSV"),
                                ("w11", 0, "no main CSV"), ("w02", 55 * M, "before frame 60000000"),
                                ("w12", 0, "does not reach a fresh segment")):
            self.assertEqual((v[w]["valid_before"], v[w]["observed_through"]), (None, through), w)
            self.assertTrue(v[w]["technical"] and why in v[w]["technical"][0], (w, v[w]["technical"]))
            self.assertEqual(max(v[w]["archived"]), max(through, 1), w)             # (F1 is the founding state)
            self.assertEqual(v[w]["unobserved"], list(range(through + M, 101 * M, M)), w)
        # an out-of-sequence row (a skipped sample) is a gap too
        with open(p, "w") as f:
            f.write(text.replace("30000000,1.0,500,10\n", ""))
        self.assertEqual(self.block()["worlds"]["w09"]["observed_through"], 29 * M)

    def test_refusals_and_cli(self):
        bad = os.path.join(adir(self.root, "w02"), "runs", "seg000.csv")
        with open(bad, "w") as f:
            f.write("step,elapsed_s,prey\n1000000,1.0,500\n")
        with self.assertRaisesRegex(val_block.BlockError, "no population / predator_pop"):
            self.block()
        segment(adir(self.root, "w02"), 0, 0, rows(L, 60 * M))
        shutil.rmtree(adir(self.root, "w09"))
        with self.assertRaisesRegex(val_block.BlockError, "w09: no directory for its attempt 0"):
            self.block()
        os.makedirs(adir(self.root, "w09"))
        out = os.path.join(self.tmp, "block.json")
        with contextlib.redirect_stdout(io.StringIO()) as so:
            self.assertEqual(val_block.main(["--root", self.root, "--out", out, "--log-every", str(L)]), 0)
        b = rqlib.read_json(out)
        self.assertEqual((b["worlds"]["w09"]["archived"], b["worlds"]["w09"]["technical"]),
                         ([], ["no segment command lines (segNNN.cmd)"]))
        self.assertIn("w04 C a0 extinct", so.getvalue())
        self.assertIn("TECHNICAL", so.getvalue())
        self.assertEqual(val_block.LOG_EVERY, 5000)                       # (runner_val.py's --log-every)


if __name__ == "__main__":
    unittest.main()

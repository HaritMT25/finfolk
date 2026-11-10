#!/usr/bin/env python3
"""test_evidence.py: evidence.py, the one evidence-chain rule val_block.py and worlds.py's ecology share (Annex H D6
rule 24; Codex #74 r1, #75 r1): complete records only, validated rows kept up to the first bad one, the newest line
of descent (never the longest continuation), the first absorbing terminal boundary, refills against the founder
baseline. Pure Python.

    python3 -I tools/redqueen/test_evidence.py [-v]
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import evidence as ev  # noqa: E402

H = "step,elapsed_s,population,predator_pop,predator_reseeds_cum\n"


def csv(rows, tail=""):
    return (H + "".join(f"{f},1.0,{q},{p},{r}\n" for f, q, p, r in rows) + tail).encode()


def alive(lo, hi, step=100):
    return [(f, 50, 8, 0) for f in range(lo, hi + 1, step)]


class TestEvidence(unittest.TestCase):
    def test_complete_records_only(self):
        raw = csv(alive(100, 300), tail="400,1.0,50,0,0")             # (a full-width zero, unterminated)
        rows, stop = ev.segment_rows(raw, 0, 100)
        self.assertEqual(([f for f, _ in rows], stop), ([100, 200, 300], None))
        self.assertEqual(ev.complete(b"a\nb"), b"a\n")
        rows, _ = ev.segment_rows(raw + b"\n", 0, 100)
        self.assertEqual(rows[-1], (400, {"population": 50, "predator_pop": 0}))

    def test_rows_keep_the_valid_prefix(self):
        raw = csv(alive(100, 200) + [(300, "5x", 8, 0)] + alive(400, 500))
        rows, stop = ev.segment_rows(raw, 0, 100, cols=("predator_reseeds_cum",))
        self.assertEqual([f for f, _ in rows], [100, 200])            # (the rows before the bad one kept)
        self.assertIn("line 4: a damaged or out-of-sequence row after frame 200", stop)
        self.assertEqual(rows[0][1]["predator_reseeds_cum"], 0)
        rows, stop = ev.segment_rows(csv(alive(100, 200) + alive(400, 500)), 0, 100)
        self.assertEqual(([f for f, _ in rows], stop[:6]), ([100, 200], "line 4"))      # (a skipped sample)
        rows, stop = ev.segment_rows(csv(alive(100, 900)), 0, 100, upto=500)
        self.assertEqual(([f for f, _ in rows][-1], stop), (500, None))                # (clipped at the resume)
        rows, stop = ev.segment_rows(csv(alive(100, 300)), 0, 100, upto=500)
        self.assertIn("before frame 500", stop)
        rows, _ = ev.segment_rows(csv(alive(600, 900)), 500, 100)       # (a resumed segment from 500)
        self.assertEqual(rows[0][0], 600)
        self.assertEqual(ev.segment_rows(H.encode(), 0, 100), ([], None))
        self.assertEqual(ev.segment_rows(b"", 0, 100), ([], "an empty main CSV"))
        with self.assertRaisesRegex(ev.EvidenceError, "no population / predator_pop"):
            ev.segment_rows(b"step,prey\n100,5\n", 0, 100)

    def test_chain_is_the_newest_line_of_descent(self):
        self.assertEqual(ev.chain_cuts([("s0", 0), ("s1", 600), ("s2", 1200)]),
                         ([("s0", 0, 600), ("s1", 600, 1200), ("s2", 1200, None)], None))
        # a rollback: s2 resumed from 400, before s1's start: s1 is superseded, s0 covers to 400
        self.assertEqual(ev.chain_cuts([("s0", 0), ("s1", 600), ("s2", 400)])[0], [("s0", 0, 400), ("s2", 400, None)])
        # two continuations of one checkpoint: the NEWER one is the line of descent, whatever their lengths
        self.assertEqual(ev.chain_cuts([("s0", 0), ("s1", 600), ("s2", 600)])[0], [("s0", 0, 600), ("s2", 600, None)])
        # a fresh replay supersedes everything before it
        self.assertEqual(ev.chain_cuts([("s0", 0), ("s1", 600), ("s2", 0)])[0], [("s2", 0, None)])
        self.assertIn("does not reach a fresh segment", ev.chain_cuts([("s1", 600)])[1])
        self.assertEqual(ev.chain_cuts([]), ([], "no segment"))
        self.assertEqual(ev.chain_cuts([("b0", 3000), ("b1", 4000)], base=3000)[1], None)   # (a branch's origin)

    def test_first_absorbing_terminal(self):
        rows, _ = ev.segment_rows(csv(alive(100, 200) + [(300, 0, 8, 0), (400, 0, 0, 0)]), 0, 100)
        o = ev.terminal(rows)                                          # (prey first, predators overshoot after)
        self.assertEqual((o["first_terminal"], o["events"]["predators"], o["frontier"]),
                         ({"frame": 300, "kind": "prey"}, None, 300))
        self.assertEqual(o["events"]["prey"], {"frame": 300, "previous_sample": 200})
        rows, _ = ev.segment_rows(csv(alive(100, 200) + [(300, 0, 0, 0)]), 0, 100)
        o = ev.terminal(rows)
        self.assertEqual((o["joint"], o["first_terminal"]["kind"], o["events"]["predators"]["frame"]), (True, "joint", 300))
        rows, _ = ev.segment_rows(csv([(100, 0, 8, 0)]), 0, 100)       # (the first sample: before it, the base)
        self.assertEqual(ev.terminal(rows)["events"]["prey"]["previous_sample"], 0)
        rows, _ = ev.segment_rows(csv([(100, 50, 0, 0), (200, 0, 0, 0)]), 0, 100)
        self.assertEqual(ev.terminal(rows, guilds=(("prey", "population"),))["first_terminal"]["frame"], 200)   # (A)

    def test_refills_end_the_observation(self):
        rows, _ = ev.segment_rows(csv(alive(100, 300) + [(400, 50, 8, 1), (500, 0, 8, 1)]), 0, 100,
                                  cols=(ev.REFILL_COL,))
        o = ev.terminal(rows)
        self.assertEqual((o["refill"], o["frontier"], o["first_terminal"]),
                         ({"frame": 400, "value": 1, "baseline": 0}, 300, None))
        self.assertEqual(ev.terminal(rows, refill_base=None)["first_terminal"]["frame"], 500)  # (no baseline)
        self.assertIsNone(ev.terminal(rows, refill_base=1)["refill"])                       # (a branch's own baseline)


if __name__ == "__main__":
    unittest.main()

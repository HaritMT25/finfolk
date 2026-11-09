#!/usr/bin/env python3
"""test_worlds.py: unit tests of worlds.py that need no engine (the end-to-end ones are
tests/redqueen_worlds.sh).

    python3 -I tools/redqueen/test_worlds.py [-v]
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ckpt  # noqa: E402
import rqlib  # noqa: E402
import worlds  # noqa: E402
from test_redqueen import mk_cp  # noqa: E402

ARENA = {"schema": worlds.ARENA_SCHEMA, "status": "selected",
         "common": {"population": 600, "min-pop": 0, "predator-min-pop": 0, "max-pop": 600, "food-patches": 0,
                    "target-food": 2000, "food-spawn": 12, "food-amp": 0, "current": 0, "move-cost": 7e-05,
                    "gene-cost": 0},
         "treatments": {
             "C": {"predators": 6, "predator-economy": True, "predator-brain": True, "predator-max-pop": 40,
                   "predator-max-age": 240, "predator-cooldown": 1.5, "predator-meal": 16},
             "B": {"predators": 6, "predator-economy": True, "predator-max-pop": 40, "predator-max-age": 240,
                   "predator-cooldown": 1.5, "predator-meal": 16},
             "A": {"predators": 8, "predator-cooldown": 1.5}}}
SCHED = {"total_steps": 3000, "checkpoint_every": 1000, "log_every": 100}
EXE_SHA = "e" * 64


def wr(path, text, mode="w"):
    with open(path, mode) as f:
        f.write(text)


def rm_tree(path):
    for d, dirs, files in os.walk(path):
        os.chmod(d, 0o755)
        for f in files:
            os.chmod(os.path.join(d, f), 0o644)
    shutil.rmtree(path)


def cfg_for(flags):
    """The checkpoint config a world with these flags carries (what the engine writes)."""
    out = {}
    for k, v in flags.items():
        typ, key = worlds.FLAGS[k]
        if key:
            out[key] = (1 if v == "gyre" else 0) if typ == worlds.ENUM else v
    return out


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.arena = os.path.join(self.tmp, "arena.json")
        wr(self.arena, json.dumps(ARENA))

    def tearDown(self):
        rm_tree(self.tmp)

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
        self.assertFalse(reg["taint"]["tainted"])
        for w in ws:     # P1 (1): both floors are always passed, as explicit zeros
            i, j = w["config_args"].index("--min-pop"), w["config_args"].index("--predator-min-pop")
            self.assertEqual((w["config_args"][i + 1], w["config_args"][j + 1]), ("0", "0"))

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
        C, B, A, com = (lambda a: a["treatments"]["C"]), (lambda a: a["treatments"]["B"]), \
            (lambda a: a["treatments"]["A"]), (lambda a: a["common"])
        self.refused(lambda a: C(a).update({"predator-max-pop": "SELECTED_CAP"}), "unresolved")
        self.refused(lambda a: a.update(status="placeholder"), "placeholder")
        self.refused(lambda a: com(a).update({"min-pop": 20}), "prey floor")
        self.refused(lambda a: B(a).update({"predator-min-pop": 2}), "predator floor")
        self.refused(lambda a: C(a).update({"predator-primer": True}), "predator-primer")
        self.refused(lambda a: B(a).update({"predator-brain": True}), "B: scripted")
        self.refused(lambda a: A(a).update({"predator-economy": True}), "A: scripted")
        self.refused(lambda a: A(a).update({"predators": 0}), "--predators must be positive")
        self.refused(lambda a: com(a).update({"seed": 5}), "set by worlds.py")
        self.refused(lambda a: a.update(schema="x"), "schema")
        with self.assertRaises(worlds.WorldsError):
            worlds.register(self.arena, "ns", schedule={"total_steps": 1000, "checkpoint_every": 300, "log_every": 100})

    def test_floors_explicit_and_typed(self):
        """P1 (1): an omitted floor (the engine's prey default is 50) or a bool floor is refused."""
        self.refused(lambda a: a["common"].pop("min-pop"), "--min-pop must be given explicitly")
        self.refused(lambda a: a["common"].pop("predator-min-pop"), "--predator-min-pop must be given explicitly")
        self.refused(lambda a: a["common"].update({"min-pop": False}), "--min-pop False must be an integer")
        self.refused(lambda a: a["common"].update({"min-pop": 0.0}), "--min-pop 0.0 must be an integer")
        self.refused(lambda a: a["common"].update({"population": True}), "--population True must be an integer")

    def test_typed_production_schema(self):
        """P2 (11): explicit selected parameters, the C founder count, C/B (and A kinematic) equality."""
        self.refused(lambda a: a["treatments"]["B"].pop("predator-max-age"), "B: needs an explicit --predator-max-age")
        self.refused(lambda a: a["treatments"]["C"].pop("predator-max-age"), "C: needs an explicit --predator-max-age")
        self.refused(lambda a: a["treatments"]["C"].pop("predator-cooldown"), "C: needs an explicit --predator-cooldown")
        self.refused(lambda a: a["treatments"]["C"].update({"predators": 5}), "6 founders are registered")
        self.refused(lambda a: a["treatments"]["B"].update({"predator-meal": 18}), "C and B must share")
        self.refused(lambda a: a["treatments"]["B"].update({"predator-speed": 120}), "C and B must share")
        self.refused(lambda a: a["treatments"]["A"].update({"predator-cooldown": 3}), "A must share the predator kin")
        self.refused(lambda a: a["treatments"]["A"].update({"predator-max-age": 30}), "A: --predator-max-age needs")
        # N6: the refusals name the canonical form
        self.refused(lambda a: a["treatments"]["A"].update({"predator-max-age": 0, "predator-economy": False}),
                     "A's canonical form leaves every economy flag out")
        self.refused(lambda a: (a["treatments"]["C"].update({"predator-speed": 110})), "canonical form gives a shared")
        self.refused(lambda a: a["treatments"]["C"].update({"population": 500}), "common environment differs")
        self.refused(lambda a: a["common"].pop("move-cost"), "--move-cost must be given explicitly")
        self.refused(lambda a: a["common"].update({"food-spwan": 3}), "not an engine flag")
        self.refused(lambda a: a["common"].update({"current": float("nan")}), "must be a number")
        self.refused(lambda a: a["common"].update({"current-mode": "vortex"}), "must be one of")
        self.refused(lambda a: a["treatments"]["B"].update({"predator-mutation": 1}), "needs the neural predators")
        reg = worlds.register(self.arena, "ns", c_founders=6)
        self.assertEqual(reg["c_founders"], 6)
        p = os.path.join(self.tmp, "c5.json")
        c5 = json.loads(json.dumps(ARENA))
        c5["treatments"]["C"]["predators"] = 5
        c5["treatments"]["B"]["predators"] = 5
        wr(p, json.dumps(c5))
        self.assertEqual(worlds.register(p, "ns", c_founders=5)["c_founders"], 5)   # a disclosed change

    def test_placeholder_taint(self):
        """P2 (12): a 'selected' arena holding a SELECTED_* value, registered with --allow-placeholder,
        is tainted; loading it without the flag is refused."""
        ph = json.loads(json.dumps(ARENA))
        ph["treatments"]["C"]["predator-max-pop"] = "SELECTED_CAP"
        ph["treatments"]["B"]["predator-max-pop"] = "SELECTED_CAP"
        p = os.path.join(self.tmp, "ph.json")
        wr(p, json.dumps(ph))
        reg = worlds.register(p, "ns", allow_placeholder=True)
        self.assertEqual(reg["arena"]["status"], "selected")
        self.assertTrue(reg["taint"]["tainted"])
        root = os.path.join(self.tmp, "root")
        worlds.write_registry(os.path.join(root, "config", "worlds.json"), rqlib.canonical(reg))
        with self.assertRaisesRegex(worlds.WorldsError, "unresolved values.*SELECTED_CAP"):
            worlds.load_registry(root)
        self.assertEqual(worlds.load_registry(root, allow_placeholder=True)[0]["namespace"], "ns")
        st = json.loads(json.dumps(ARENA))
        st.update(status="placeholder")
        wr(p, json.dumps(st))
        root2 = os.path.join(self.tmp, "root2")
        worlds.write_registry(os.path.join(root2, "config", "worlds.json"),
                              rqlib.canonical(worlds.register(p, "ns", allow_placeholder=True)))
        with self.assertRaisesRegex(worlds.WorldsError, "placeholder"):
            worlds.load_registry(root2)
        # a registry edited by hand after registration is refused on load
        reg = worlds.register(self.arena, "ns")
        reg["worlds"][0]["flags"]["min-pop"] = 50
        root3 = os.path.join(self.tmp, "root3")
        worlds.write_registry(os.path.join(root3, "config", "worlds.json"), rqlib.canonical(reg))
        with self.assertRaisesRegex(worlds.WorldsError, "prey floor"):
            worlds.load_registry(root3)

    def test_registry_immutable_and_root_bound(self):
        """P1 (2): register never replaces other bytes; the root is bound to its registry's hash."""
        root = os.path.join(self.tmp, "root")
        out = os.path.join(root, "config", "worlds.json")
        reg = rqlib.canonical(worlds.register(self.arena, "ns"))
        self.assertTrue(worlds.write_registry(out, reg))
        self.assertFalse(worlds.write_registry(out, reg))                   # the same bytes: unchanged
        av = os.path.join(self.tmp, "avoid.txt")
        wr(av, "17\n")
        with self.assertRaisesRegex(worlds.WorldsError, "never replaced"):
            worlds.write_registry(out, rqlib.canonical(worlds.register(self.arena, "ns", avoid_paths=[av])))
        r, sha = worlds.load_registry(root)
        with self.assertRaisesRegex(worlds.WorldsError, "not bound"):
            worlds.bind_root(root, sha)
        ar = worlds.bind_root(root, sha, create=True)
        self.assertEqual(ar, os.path.join(root, "archive"))
        self.assertEqual(worlds.bind_root(root, sha), ar)
        with self.assertRaisesRegex(worlds.WorldsError, "bound to the archive root"):
            worlds.bind_root(root, sha, os.path.join(self.tmp, "elsewhere"))
        os.chmod(out, 0o644)
        wr(out, rqlib.canonical(worlds.register(self.arena, "ns", avoid_paths=[av])).decode())  # by hand
        r2, sha2 = worlds.load_registry(root)
        with self.assertRaisesRegex(worlds.WorldsError, "is bound to the registry"):
            worlds.bind_root(root, sha2, create=True)
        root2 = os.path.join(self.tmp, "root2")
        worlds.write_registry(os.path.join(root2, "config", "worlds.json"), reg)
        os.makedirs(os.path.join(root2, "worlds", "w01"))
        with self.assertRaisesRegex(worlds.WorldsError, "artifacts"):
            worlds.bind_root(root2, sha, create=True)

    def test_per_block(self):
        self.assertEqual(worlds.parse_per_block("C=1,A=1"), {"C": 1, "A": 1, "B": 0})
        with self.assertRaises(worlds.WorldsError):
            worlds.parse_per_block("D=1")
        reg = worlds.register(self.arena, "ns", blocks=2, per_block={"C": 1, "A": 0, "B": 1})
        self.assertEqual([w["treatment"] for w in reg["worlds"]].count("C"), 2)

    def test_flags_to_args(self):
        self.assertEqual(worlds.flags_to_args({"a": True, "b": False, "c": 3, "d": 7e-05, "e": "x", "z": 0}),
                         ["--a", "--c", "3", "--d", "7e-05", "--e", "x", "--z", "0"])

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

    def test_verify_config(self):
        """P1 (1): the effective configuration in a checkpoint is checked against the registry."""
        flags = dict(ARENA["common"], **ARENA["treatments"]["A"])
        cp = mk_cp(frame=1, cfg_extra=cfg_for(flags))
        self.assertEqual(worlds.verify_config(cp, flags), [])
        cp["config"]["minPopulation"] = 50                     # the engine's default prey floor
        self.assertTrue(any("minPopulation 50" in p for p in worlds.verify_config(cp, flags)))
        cp = mk_cp(frame=1, cfg_extra=dict(cfg_for(flags), predatorCooldown=3.0))
        self.assertTrue(any("predator-cooldown" in p for p in worlds.verify_config(cp, flags)))


class TestLogs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        rm_tree(self.tmp)

    def test_contiguous_and_tails(self):
        self.assertEqual(worlds._contiguous_until([500, 1000, 1500, 2500], 0, 500), 1500)
        self.assertEqual(worlds._contiguous_until([], 4000, 500), 4000)
        p = os.path.join(self.tmp, "run.csv")
        wr(p, "step,population\n500,10\n1000,9\n15")        # a torn last line
        hdr, rows = worlds._rows(p)
        self.assertEqual((hdr, rows), (["step", "population"], [["500", "10"], ["1000", "9"]]))
        self.assertEqual(worlds._last_row(p), (["step", "population"], ["1000", "9"]))
        t = worlds.Tail(p)
        self.assertEqual(t.lines(), [["500", "10"], ["1000", "9"]])
        self.assertEqual(t.header, ["step", "population"])
        self.assertEqual(t.lines(), [])
        wr(p, "00,8\n2000,7\n", "a")
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
        wr(p, '{"label": "end.4', "a")                     # a torn last record: that copy is redone
        self.assertEqual(list(worlds.archive_records(root, "w01")), ["F1"])

    def test_dense_rows_and_headers(self):
        """N4: acceptance checks a dense log's header and every row's width (a short final row, a
        long row or a bad header is never accepted); the cut carries the header's hash."""
        p = os.path.join(self.tmp, "w.csv")
        wr(p, "step,A,B\n100,1,2\n200\n")                       # a short final row, newline-terminated
        self.assertIsNone(worlds.dense_cut(p, "frame", 0, 200, 100))
        wr(p, "step,A,B\n100,1,2\n200,1,2,3\n")
        self.assertIsNone(worlds.dense_cut(p, "frame", 0, 200, 100))
        wr(p, "x,A,B\n100,1,2\n200,1,2\n")
        self.assertIsNone(worlds.dense_cut(p, "frame", 0, 200, 100))
        wr(p, "step,A,B\n100,1,2\n200,1,2\n")
        a = worlds.dense_cut(p, "frame", 0, 100, 100)
        self.assertEqual((a["columns"], a["header_sha256"]), (3, rqlib.sha256_bytes(b"step,A,B")))
        b = worlds.dense_cut(p, "frame", 0, 200, 100, a)
        self.assertEqual(b["header_sha256"], a["header_sha256"])
        e = os.path.join(self.tmp, "e.csv")
        wr(e, "frame,event,id\n0,F,1\n")
        self.assertEqual(worlds.events_cut(e, 10)["header_sha256"], rqlib.sha256_bytes(b"frame,event,id"))
        t = worlds.Tail(p)
        self.assertEqual(t.lines(), [["100", "1", "2"], ["200", "1", "2"]])
        self.assertEqual(t.ends, [len("step,A,B\n100,1,2\n"), len("step,A,B\n100,1,2\n200,1,2\n")])

    def test_dense_cuts(self):
        p = os.path.join(self.tmp, "run.csv")
        wr(p, "step,x\n" + "".join(f"{f},1\n" for f in range(100, 1601, 100)))
        a = worlds.dense_cut(p, "frame", 0, 500, 100)
        self.assertEqual(a["last_frame"], 500)
        b = worlds.dense_cut(p, "frame", 0, 1000, 100, a)
        self.assertEqual((b["from"], b["last_frame"]), (a["bytes"], 1000))
        self.assertIsNone(worlds.dense_cut(p, "frame", 0, 2000, 100, b))       # not there yet
        self.assertTrue(worlds.verify_delta(p, a) and worlds.verify_delta(p, b))
        with open(p, "r+b") as f:
            f.truncate(b["bytes"] - 3)                                          # a lost tail
        self.assertTrue(worlds.verify_delta(p, a))
        self.assertFalse(worlds.verify_delta(p, b))
        g = os.path.join(self.tmp, "gap.csv")
        wr(g, "step,x\n100,1\n200,1\n400,1\n")
        self.assertIsNone(worlds.dense_cut(g, "frame", 0, 400, 100))            # a gap is never accepted
        w = os.path.join(self.tmp, "wiring.csv")                                # segment-relative steps
        wr(w, "step,x\n" + "".join(f"{s},1\n" for s in range(100, 1001, 100)))
        self.assertEqual(worlds.dense_cut(w, "steps", 4000, 5000, 100)["last_frame"], 5000)

    def test_lineage_cuts_and_counts(self):
        """P1 (3): the lineage log's rows through a checkpoint must add up to its counters."""
        p = os.path.join(self.tmp, "run.predlog.csv")
        hdr = "frame,event,id,parent,lineage\n"
        rows = ["0,F,1,0,1", "0,F,2,0,2", "0,F,3,0,3", "40,B,4,1,1", "90,A,2,0,2", "120,B,5,4,1"]
        wr(p, hdr + "\n".join(rows) + "\n")
        a = worlds.events_cut(p, 100)
        self.assertEqual(a["events"], {"F": 3, "B": 1, "A": 1})
        b = worlds.events_cut(p, 200, a)
        self.assertEqual(b["events"], {"F": 3, "B": 2, "A": 1})
        cp = mk_cp(frame=100, n_pred=3)
        cp["counters"].update(totalPredatorBirths=1, totalPredatorDeathsAge=1)
        self.assertEqual(worlds.lineage_problems(a["events"], None, cp, 0), [])
        lost = worlds.events_cut(p, 100)
        lost["events"] = {"F": 3, "B": 1}                                      # the death row never reached disk
        probs = worlds.lineage_problems(lost["events"], None, cp, 0)
        self.assertTrue(any("0 A rows, the counters say 1" in x for x in probs), probs)
        self.assertTrue(any("alive" in x for x in probs), probs)
        wr(p, "0,F\n", "a")                                                     # a short row: malformed
        self.assertIsNone(worlds.events_cut(p, 10 ** 9, b))


def make_root(tmp, treatment="A", sched=None, burn_in=0, max_restarts=8):
    """(burn_in 0: the burn-in rule off, as the tests before it expect)"""
    arena = os.path.join(tmp, "arena.json")
    wr(arena, json.dumps(ARENA))
    reg = worlds.register(arena, "ns-unit", blocks=1, per_block={t: int(t == treatment) for t in "CAB"},
                          schedule=sched or SCHED, burn_in=burn_in, max_restarts=max_restarts)
    root = os.path.join(tmp, "root")
    worlds.write_registry(os.path.join(root, "config", "worlds.json"), rqlib.canonical(reg))
    reg, sha = worlds.load_registry(root)
    return root, reg, worlds.bind_root(root, sha, create=True)


def supervisor(root, reg, ar, **kw):
    a = argparse.Namespace(on_extinction="stop", prune_local=False, retry_failed=False, retries=3, workers=1,
                           mem_min_mb=0, poll=0.1)
    for k, v in kw.items():
        setattr(a, k, v)
    msgs = []
    return worlds.Supervisor(root, reg, ar, "/bin/false", EXE_SHA, a, msgs.append), msgs


class TestSupervisor(unittest.TestCase):
    """The supervisor's recovery on synthetic worlds (treatment A: no lineage log)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        worlds.release_archives()
        rm_tree(self.tmp)

    def world(self, total=3000, status="interrupted", logs_to=3000, ckpts=(1000, 2000, 3000), zero_at=None):
        root, reg, ar = make_root(self.tmp, "A", dict(SCHED, total_steps=total))
        w = reg["worlds"][0]
        wid = w["id"]
        d = worlds.wdir(root, wid)
        os.makedirs(os.path.join(d, "seg000"))
        os.makedirs(os.path.join(d, "ckpt"))
        cfg = cfg_for(w["flags"])
        f1p = os.path.join(self.tmp, "F1.json")
        wr(f1p, ckpt.dumps(mk_cp(frame=1, cfg_extra=cfg)))
        worlds.archive_one(root, wid, ar, 1, f1p, lambda m: None, extra={"binary_sha256": EXE_SHA})
        wr(os.path.join(d, "seg000", "run.csv"), "step,population,predator_pop\n" + "".join(
            f"{f},{0 if zero_at and f >= zero_at else 50},8\n" for f in range(100, logs_to + 1, 100)))
        wr(os.path.join(d, "seg000", "run.wiring.csv"), "step,PREY_FWD\n" + "".join(
            f"{f},0.5\n" for f in range(100, logs_to + 1, 100)))
        for f in ckpts:
            wr(os.path.join(d, "ckpt", f"end.{f}.json"), ckpt.dumps(mk_cp(frame=f, cfg_extra=cfg)))
        worlds.write_state(root, wid, {"schema": worlds.STATE_SCHEMA, "id": wid, "status": status, "failures": 0,
                                       "segments": [{"name": "seg000", "start_frame": 0, "resumed_from": None,
                                                     "resumed_accept": None, "args": []}]})
        return root, reg, ar, wid

    def test_final_frame_is_finalized_without_a_segment(self):
        """P2 (8) and P1 (4): a world whose final checkpoint and logs are complete is accepted
        through the final frame and finalized at startup, with no new segment."""
        root, reg, ar, wid = self.world()
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        st = worlds.read_state(root, wid)
        self.assertEqual((st["status"], len(st["segments"])), ("done", 1), msgs)
        self.assertEqual([r["frame"] for r in worlds.accept_records(root, wid)], [1000, 2000, 3000])
        ad = worlds.adir(ar, wid)
        self.assertTrue(os.path.isfile(os.path.join(ad, "FINALIZED")))
        self.assertEqual(os.stat(ad).st_mode & 0o777, 0o555)
        man = worlds.stitch(root, wid, reg)
        self.assertEqual((man["endpoint"], man["complete"], man["files"]["run.csv"]["rows"]), (3000, True, 30))

    def test_short_log_is_not_complete(self):
        """P1 (4): a log that ends before the final frame (engine exit 0 or not): the world is not
        done; it resumes from the last frame every log reaches, and stitch refuses the shortfall."""
        root, reg, ar, wid = self.world(logs_to=3000)
        p = os.path.join(worlds.wdir(root, wid), "seg000", "run.wiring.csv")
        wr(p, "step,PREY_FWD\n" + "".join(f"{f},0.5\n" for f in range(100, 2501, 100)))   # lost its tail
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        st = worlds.read_state(root, wid)
        self.assertEqual(st["status"], "interrupted")
        self.assertEqual([r["frame"] for r in worlds.accept_records(root, wid)], [1000, 2000])
        self.assertEqual(worlds.resume_point(root, wid, st, "A")[0], 2000)
        self.assertEqual(s.next_action(wid), ("verify", None))  # a resume needs the verified F1 first
        with self.assertRaisesRegex(worlds.WorldsError, "not done"):
            worlds.stitch(root, wid, reg)
        self.assertEqual(worlds.stitch(root, wid, reg, partial=True)["endpoint"], 2000)
        st["status"] = "done"                                   # even if marked done: the endpoint is enforced
        worlds.write_state(root, wid, st)
        with self.assertRaisesRegex(worlds.WorldsError, "accepted logs end at frame 2000, not 3000"):
            worlds.stitch(root, wid, reg)

    def test_lost_log_tail_moves_the_resume_back(self):
        """P1 (3): an accepted log part that no longer verifies (a host crash lost it) sends the
        resume back to the last checkpoint the surviving bytes fully cover."""
        root, reg, ar, wid = self.world(total=4000)
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        recs = worlds.accept_records(root, wid)
        self.assertEqual([r["frame"] for r in recs], [1000, 2000, 3000])
        st = worlds.read_state(root, wid)
        self.assertEqual(worlds.resume_point(root, wid, st, "A")[0], 3000)
        with open(os.path.join(worlds.wdir(root, wid), "seg000", "run.csv"), "r+b") as f:
            f.truncate(recs[1]["logs"]["run.csv"]["bytes"] + 5)
        self.assertEqual(worlds.resume_point(root, wid, st, "A")[0], 2000)

    def test_torn_checkpoint_is_quarantined(self):
        """P2 (7): a torn local checkpoint is quarantined, not a world failure; the world resumes
        from its last accepted checkpoint."""
        root, reg, ar, wid = self.world(total=4000, ckpts=(1000, 2000))
        p = os.path.join(worlds.wdir(root, wid), "ckpt", "end.3000.json")
        good = ckpt.dumps(mk_cp(frame=3000, cfg_extra=cfg_for(reg["worlds"][0]["flags"])))
        wr(p, good[: len(good) // 2])
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        st = worlds.read_state(root, wid)
        self.assertEqual(st["status"], "interrupted", msgs)
        self.assertFalse(os.path.exists(p))
        q = worlds.read_jsonl(os.path.join(worlds.wdir(root, wid), "quarantine.jsonl"))
        self.assertEqual([(r["frame"], os.path.basename(r["to"])) for r in q], [(3000, "end.3000.json.1")])
        self.assertTrue(os.path.isfile(q[0]["to"]))
        self.assertEqual([r["frame"] for r in worlds.accept_records(root, wid)], [1000, 2000])
        self.assertEqual(worlds.resume_point(root, wid, st, "A")[0], 2000)

    def test_extinction_found_in_an_earlier_segment(self):
        """P2 (5): a zero the previous supervisor missed (it died before reading those rows) is
        recovered with its earliest frame, superseding a later record; the world ends extinct
        without being advanced."""
        root, reg, ar, wid = self.world(total=4000, logs_to=2500, ckpts=(1000, 2000), zero_at=1500)
        d = worlds.wdir(root, wid)
        st = worlds.read_state(root, wid)
        st["segments"].append({"name": "seg001", "start_frame": 2000, "resumed_from": "ckpt/end.2000.json",
                               "resumed_accept": None, "args": []})
        worlds.write_state(root, wid, st)
        os.makedirs(os.path.join(d, "seg001"))
        head = "step,population,predator_pop\n2100,0,8\n"
        wr(os.path.join(d, "seg001", "run.csv"), head + "2200,0,8\n")
        worlds._append_durable(os.path.join(root, "availability.jsonl"), {      # (with its evidence)
            "schema": worlds.AVAIL_SCHEMA, "world": wid, "guild": "prey", "first_zero_frame": 2100,
            "segment": "seg001", "csv_bytes": len(head), "csv_sha256": rqlib.sha256_bytes(head.encode())})
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        led = worlds.read_jsonl(os.path.join(root, "availability.jsonl"))
        self.assertEqual(worlds.first_zeros(led, wid), {"prey": 1500})
        self.assertEqual((led[-1]["recovered"], led[-1]["supersedes"]), (True, 2100))
        st = worlds.read_state(root, wid)
        self.assertEqual((st["status"], len(st["segments"])), ("extinct", 2), msgs)
        self.assertTrue(os.path.isfile(os.path.join(worlds.adir(ar, wid), "FINALIZED")))

    def test_finalization_is_reconciled(self):
        """P2 (10): a terminal world whose finalization was interrupted (no marker; or a marker but
        a writable directory) is finalized at the next start; a marker that does not describe the
        archive is an error."""
        root, reg, ar, wid = self.world()
        s, _ = supervisor(root, reg, ar)
        s.startup()
        ad = worlds.adir(ar, wid)
        os.chmod(ad, 0o755)
        os.remove(os.path.join(ad, "FINALIZED"))
        s, _ = supervisor(root, reg, ar)
        s.startup()
        self.assertTrue(os.path.isfile(os.path.join(ad, "FINALIZED")))
        self.assertEqual(os.stat(ad).st_mode & 0o777, 0o555)
        os.chmod(ad, 0o755)                                     # the marker made, the chmod lost
        s, _ = supervisor(root, reg, ar)
        s.startup()
        self.assertEqual(os.stat(ad).st_mode & 0o777, 0o555)
        os.chmod(ad, 0o755)
        m = os.path.join(ad, "FINALIZED")
        os.chmod(m, 0o644)
        wr(m, json.dumps({"world": wid, "status": "done", "frames": [1]}))
        with self.assertRaisesRegex(worlds.WorldsError, "does not describe"):
            worlds.finalize_archive(root, wid, ar, "done")

    def test_archive_copy_verified_and_repaired(self):
        """P2 (9): an archived copy found damaged or writable is repaired from verified local bytes
        before it is relied on (refused once finalized)."""
        root, reg, ar, wid = self.world(total=4000, ckpts=(1000,))
        msgs = []
        loc = os.path.join(worlds.wdir(root, wid), "ckpt", "end.1000.json")
        rec, _ = worlds.archive_one(root, wid, ar, 1000, loc, msgs.append)
        os.chmod(rec["path"], 0o644)
        wr(rec["path"], "garbage")
        worlds.archive_one(root, wid, ar, 1000, loc, msgs.append)
        self.assertEqual(rqlib.sha256_file(rec["path"]), rec["sha256"])
        self.assertEqual(os.stat(rec["path"]).st_mode & 0o777, 0o444)
        self.assertTrue(any("REPAIRED" in m for m in msgs), msgs)
        os.chmod(rec["path"], 0o644)                              # writable, bytes intact: made 0444 again
        worlds.archive_one(root, wid, ar, 1000, loc, msgs.append)
        self.assertEqual(os.stat(rec["path"]).st_mode & 0o777, 0o444)
        worlds.finalize_archive(root, wid, ar, "done")
        os.chmod(rec["path"], 0o644)
        wr(rec["path"], "garbage")
        with self.assertRaisesRegex(worlds.WorldsError, "finalized archive"):
            worlds.archive_one(root, wid, ar, 1000, loc, msgs.append)

    # ---------------------------------------------------------------- review round 2
    def test_archive_ownership(self):
        """N1 (P1): an archive root belongs to one study: a second study root naming it (finalized or
        not), or a nonempty unowned one, is refused; nothing new is published into a finalized
        directory; a destination file without this study's record is never replaced."""
        root, reg, ar, wid = self.world()
        study = rqlib.read_json(os.path.join(root, "study.json"))
        owner = rqlib.read_json(os.path.join(ar, worlds.OWNER))
        self.assertEqual((owner["study_id"], owner["study_root"]), (study["study_id"], root))
        root2 = os.path.join(self.tmp, "root2")
        worlds.write_registry(os.path.join(root2, "config", "worlds.json"),
                              rqlib.read_bytes(os.path.join(root, "config", "worlds.json")))
        _, sha = worlds.load_registry(root2)
        with self.assertRaisesRegex(worlds.WorldsError, "belongs to another study"):
            worlds.bind_root(root2, sha, ar, create=True)
        self.assertFalse(os.path.exists(os.path.join(root2, "study.json")))
        other = os.path.join(self.tmp, "other")
        os.makedirs(os.path.join(other, "x"))
        with self.assertRaisesRegex(worlds.WorldsError, "not empty and has no owner"):
            worlds.bind_root(root2, sha, other, create=True)
        s, _ = supervisor(root, reg, ar)
        s.startup()                                             # done and finalized
        ad = worlds.adir(ar, wid)
        before = {f: rqlib.sha256_file(os.path.join(ad, f)) for f in os.listdir(ad)}
        p = os.path.join(worlds.wdir(root, wid), "ckpt", "end.4000.json")
        wr(p, ckpt.dumps(mk_cp(frame=4000, cfg_extra=cfg_for(reg["worlds"][0]["flags"]))))
        with self.assertRaisesRegex(worlds.WorldsError, "finalized"):
            worlds.archive_one(root, wid, ar, 4000, p, lambda m: None)
        self.assertEqual({f: rqlib.sha256_file(os.path.join(ad, f)) for f in os.listdir(ad)}, before)
        self.assertEqual(os.stat(ad).st_mode & 0o777, 0o555)
        # an unfinalized directory holding a file this study has no record of
        ad2 = worlds.adir(ar, "w99")
        os.chmod(ar, 0o755)
        os.makedirs(ad2)
        wr(os.path.join(ad2, "end.1000.json"), "someone else's")
        with self.assertRaisesRegex(worlds.WorldsError, "exists with other bytes"):
            worlds.archive_one(root, "w99", ar, 1000, os.path.join(worlds.wdir(root, wid), "ckpt", "end.1000.json"),
                               lambda m: None)
        # read-only commands verify the owner; a bound root completes an interrupted claim
        os.chmod(os.path.join(ar, worlds.OWNER), 0o644)
        os.remove(os.path.join(ar, worlds.OWNER))
        with self.assertRaisesRegex(worlds.WorldsError, "no ownership marker"):
            worlds.bind_root(root, study["registry_sha256"], readonly=True)

    def test_terminal_done_world_reverified(self):
        """R1 (P1): a done world whose accepted logs were damaged after it finished is reopened at
        the next start (recovered from its verified evidence), not kept done."""
        root, reg, ar, wid = self.world()
        s, _ = supervisor(root, reg, ar)
        s.startup()
        self.assertEqual(worlds.read_state(root, wid)["status"], "done")
        p = os.path.join(worlds.wdir(root, wid), "seg000", "run.wiring.csv")
        with open(p, "r+b") as f:
            f.truncate(os.path.getsize(p) - 20)                 # a lost tail, after "done"
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        st = worlds.read_state(root, wid)
        self.assertEqual(st["status"], "interrupted", msgs)
        self.assertIn("not 3000", st["reopened"])
        self.assertTrue(any("REOPENED" in m for m in msgs), msgs)
        self.assertEqual(s.next_action(wid), ("verify", None))  # a replay, from the last verified frame

    def test_terminal_archive_rehashed(self):
        """R2: same-size damage inside a finalized archive is found at the next start (every object
        rehashed); it fails the world (nothing inside a finalized directory is replaced)."""
        root, reg, ar, wid = self.world()
        s, _ = supervisor(root, reg, ar)
        s.startup()
        rec = worlds.archive_records(root, wid)["end.2000"]
        n = os.path.getsize(rec["path"])
        os.chmod(rec["path"], 0o644)
        wr(rec["path"], "x" * n)
        os.chmod(rec["path"], 0o444)
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        st = worlds.read_state(root, wid)
        self.assertEqual(st["status"], "failed", msgs)
        self.assertIn("damaged", st["end_reason"])

    def test_terminal_extinct_world_reconciled(self):
        """R3: an extinct world's earliest zero is reconciled at every start (a lost ledger is
        recovered from the CSVs); a zero whose evidence is lost does not count, and the world is
        reopened to find it again."""
        root, reg, ar, wid = self.world(total=4000, logs_to=2500, ckpts=(1000, 2000), zero_at=1500)
        s, _ = supervisor(root, reg, ar)
        s.startup()
        self.assertEqual(worlds.read_state(root, wid)["status"], "extinct")
        led = worlds.read_jsonl(os.path.join(root, "availability.jsonl"))
        self.assertEqual([(e["first_zero_frame"], e["segment"]) for e in led], [(1500, "seg000")])
        self.assertTrue(worlds.zero_supported(root, led[0]))
        os.remove(os.path.join(root, "availability.jsonl"))     # the ledger lost; the world still extinct
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        led = worlds.read_jsonl(os.path.join(root, "availability.jsonl"))
        self.assertEqual(worlds.first_zeros(led, wid, root), {"prey": 1500})
        self.assertEqual(worlds.read_state(root, wid)["status"], "extinct", msgs)
        p = os.path.join(worlds.wdir(root, wid), "seg000", "run.csv")
        keep = rqlib.read_bytes(p)
        cut = keep.index(b"\n1500,") + 1
        wr(p, keep[:cut].decode())                              # the zero row's evidence lost
        self.assertFalse(worlds.zero_supported(root, led[0]))
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        st = worlds.read_state(root, wid)
        self.assertEqual(st["status"], "interrupted", msgs)
        self.assertIn("no zero whose evidence", st["reopened"])

    def test_prune_keeps_what_a_replay_needs(self):
        """N2: --prune-local deletes only checkpoints of the currently verified chain up to the
        active segment's last acceptance: a replay after a log loss keeps the old frames it rewrites."""
        root, reg, ar, wid = self.world(total=6000, logs_to=5000, ckpts=(1000, 2000, 3000, 4000, 5000))
        s, _ = supervisor(root, reg, ar)
        s.startup()
        recs = worlds.accept_records(root, wid)
        self.assertEqual([r["frame"] for r in recs], [1000, 2000, 3000, 4000, 5000])
        d = worlds.wdir(root, wid)
        with open(os.path.join(d, "seg000", "run.csv"), "r+b") as f:
            f.truncate(recs[0]["logs"]["run.csv"]["bytes"] + 5)    # the chain now ends at 1000
        st = worlds.read_state(root, wid)
        st["segments"].append({"name": "seg001", "start_frame": 1000, "resumed_from": "ckpt/end.1000.json",
                               "resumed_accept": {"segment": "seg000", "frame": 1000, "sha256": recs[0]["sha256"]},
                               "args": []})
        worlds.write_state(root, wid, st)
        os.makedirs(os.path.join(d, "seg001"))
        wr(os.path.join(d, "seg001", "run.csv"), "step,population,predator_pop\n" + "".join(
            f"{f},50,8\n" for f in range(1100, 2501, 100)))
        wr(os.path.join(d, "seg001", "run.wiring.csv"), "step,PREY_FWD\n" + "".join(
            f"{f},0.5\n" for f in range(100, 1501, 100)))
        s, msgs = supervisor(root, reg, ar, prune_local=True)
        s.startup()
        s.archive_pass(wid, alive=False)
        mine = [r["frame"] for r in worlds.accept_records(root, wid) if r["segment"] == "seg001"]
        self.assertEqual(mine, [2000], msgs)
        self.assertEqual(s.chain[wid], {1000, 2000})
        left = sorted(worlds.local_ckpts(root, wid))
        self.assertEqual(left, [1000, 2000, 3000, 4000, 5000])   # 3000-5000: the replay rewrites them

    def test_segment_directory_durable_before_acceptance(self):
        """N3: a segment's directory (its log entries) is fsync'd before its first acceptance."""
        root, reg, ar, wid = self.world()
        calls = []
        real_dir, real_append = worlds.rqlib.fsync_dir, worlds._append_durable
        worlds.rqlib.fsync_dir = lambda p: (calls.append(("dir", os.path.abspath(p))), real_dir(p))[1]
        worlds._append_durable = lambda p, r: (calls.append(("append", os.path.basename(p))), real_append(p, r))[1]
        try:
            s, _ = supervisor(root, reg, ar)
            s.startup()
        finally:
            worlds.rqlib.fsync_dir, worlds._append_durable = real_dir, real_append
        seg = os.path.abspath(os.path.join(worlds.wdir(root, wid), "seg000"))
        self.assertLess(calls.index(("dir", seg)), calls.index(("append", "accept.jsonl")))

    # ---------------------------------------------------------------- review round 3
    def sub_world(self, **kw):
        sub = tempfile.mkdtemp(dir=self.tmp)
        self.tmp, keep = sub, self.tmp
        try:
            return self.world(**kw)
        finally:
            self.tmp = keep

    def quarantined(self, root, wid):
        return worlds.read_jsonl(os.path.join(worlds.wdir(root, wid), "quarantine.jsonl"))

    def test_commitment_rule_uncommitted(self):
        """Round 3, 3 (a): an uncommitted checkpoint (no archive record) that is not a valid checkpoint
        of its frame, for ANY reason, is quarantined (evidence kept) and the world replays: cut inside
        a literal, a number or an escape, a corrupted closing quote with the suffix intact, another
        frame, duplicate ids, interior garbage, empty. No parse-position guess."""
        flags = None
        for name in ("literal", "number", "escape", "quote", "frame", "invalid", "garbage", "empty"):
            root, reg, ar, wid = self.sub_world(total=4000, ckpts=(1000,))
            flags = reg["worlds"][0]["flags"]
            good = ckpt.dumps(mk_cp(frame=2000, cfg_extra=cfg_for(flags)))
            i = good.rindex('"genes":')
            data = {"literal": good[: good.index('"fastTanh":false') + len('"fastTanh":fal')],
                    "number": good[: good.index("-1546") + 1],
                    "escape": good[: good.index('"rngState":"') + len('"rngState":"12')] + "\\",
                    "quote": good[: i + 6] + "x" + good[i + 7:],               # same length, suffix intact
                    "frame": ckpt.dumps(mk_cp(frame=1500, cfg_extra=cfg_for(flags))),
                    "garbage": '{"format": 1 xx}', "empty": ""}.get(name)
            if name == "invalid":
                cp = mk_cp(frame=2000, cfg_extra=cfg_for(flags))
                cp["predators"]["id"][1] = cp["predators"]["id"][0]             # duplicate predator ids
                data = ckpt.dumps(cp)
            p = os.path.join(worlds.wdir(root, wid), "ckpt", "end.2000.json")
            wr(p, data)
            s, msgs = supervisor(root, reg, ar)
            s.startup()
            st = worlds.read_state(root, wid)
            self.assertEqual(st["status"], "interrupted", (name, msgs))
            self.assertFalse(os.path.exists(p), name)
            q = self.quarantined(root, wid)
            self.assertEqual([(r["frame"], r["committed"]) for r in q], [(2000, False)], name)
            self.assertEqual(rqlib.read_bytes(q[0]["to"]), data.encode(), name)     # the evidence kept
            self.assertEqual(worlds.resume_point(root, wid, st, "A")[0], 1000, name)

    def test_commitment_rule_regeneration_fails_closed(self):
        """Round 3, 3 (b): the replay regenerating an invalid file at a frame quarantined before (its
        writer finished it: the main CSV has a row past it) fails the world, the file kept; a file
        whose writer did not finish it is quarantined again (another interrupted write)."""
        root, reg, ar, wid = self.world(total=4000, ckpts=(1000,))       # seg000's CSV reaches 3000
        good = ckpt.dumps(mk_cp(frame=2000, cfg_extra=cfg_for(reg["worlds"][0]["flags"])))
        p = os.path.join(worlds.wdir(root, wid), "ckpt", "end.2000.json")
        bad = good[: good.index('"fastTanh":false') + len('"fastTanh":fal')]
        wr(p, bad)
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        self.assertEqual(len(self.quarantined(root, wid)), 1, msgs)
        wr(p, bad)                                                         # regenerated, finished, invalid
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        st = worlds.read_state(root, wid)
        self.assertEqual(st["status"], "failed", msgs)
        self.assertIn("regenerated an invalid checkpoint of frame 2000", st["end_reason"])
        self.assertTrue(os.path.isfile(p))
        self.assertEqual(len(self.quarantined(root, wid)), 1)
        # unfinished writes at the same frame: quarantined each time, never a failure
        root, reg, ar, wid = self.sub_world(total=4000, logs_to=1500, ckpts=(1000,))
        p = os.path.join(worlds.wdir(root, wid), "ckpt", "end.2000.json")
        for k in (1, 2):
            wr(p, bad)
            s, msgs = supervisor(root, reg, ar)
            s.startup()
            self.assertEqual(worlds.read_state(root, wid)["status"], "interrupted", msgs)
            self.assertEqual(len(self.quarantined(root, wid)), k)

    def test_commitment_rule_committed(self):
        """Round 3, 3 (c): a committed checkpoint (archive record) whose local bytes differ fails
        closed when its writer finished it (here: a corrupted closing quote, suffix intact, that a
        parse-position rule would have called torn); a local copy whose rewrite was cut short is
        restored from the verified archived copy (the bad bytes quarantined)."""
        root, reg, ar, wid = self.world(total=4000, ckpts=(1000, 2000))   # seg000's CSV reaches 3000
        s, _ = supervisor(root, reg, ar)
        s.startup()
        rec = worlds.archive_records(root, wid)["end.2000"]
        p = os.path.join(worlds.wdir(root, wid), "ckpt", "end.2000.json")
        good = rqlib.read_text(p)
        i = good.rindex('"genes":')
        wr(p, good[: i + 6] + "x" + good[i + 7:])
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        st = worlds.read_state(root, wid)
        self.assertEqual(st["status"], "failed", msgs)
        self.assertIn("not deterministic", st["end_reason"])
        self.assertTrue(os.path.isfile(p))
        self.assertEqual(self.quarantined(root, wid), [])
        # a committed frame whose writer never finished it (the CSV stops before it): restored
        root, reg, ar, wid = self.sub_world(total=4000, logs_to=1500, ckpts=(1000, 2000))
        s, _ = supervisor(root, reg, ar)
        s.startup()
        rec = worlds.archive_records(root, wid)["end.2000"]
        p = os.path.join(worlds.wdir(root, wid), "ckpt", "end.2000.json")
        good = rqlib.read_bytes(p)
        wr(p, good[: len(good) // 2].decode())
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        self.assertEqual(worlds.read_state(root, wid)["status"], "interrupted", msgs)
        self.assertEqual(rqlib.sha256_file(p), rec["sha256"])
        self.assertTrue(any("RESTORED" in m for m in msgs), msgs)
        self.assertEqual([(r["frame"], r["committed"]) for r in self.quarantined(root, wid)], [(2000, True)])
        # no verified archived copy to restore from: fails closed
        wr(p, good[: len(good) // 2].decode())
        os.chmod(rec["path"], 0o644)
        wr(rec["path"], "damaged")
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        st = worlds.read_state(root, wid)
        self.assertEqual(st["status"], "failed", msgs)
        self.assertIn("does not verify", st["end_reason"])

    def extinct_world(self):
        """An extinct world: acceptances 1000 and 2000, the prey's zero at 2500 (stopped)."""
        root, reg, ar, wid = self.world(total=4000, logs_to=2600, ckpts=(1000, 2000), zero_at=2500)
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        self.assertEqual(worlds.read_state(root, wid)["status"], "extinct", msgs)
        return root, reg, ar, wid

    def damage_wiring(self, root, wid, frame=2000):
        """Flip a byte of seg000's wiring log inside the part the record of `frame` accepted."""
        r = [x for x in worlds.accept_records(root, wid) if x["frame"] == frame][0]["logs"]["run.wiring.csv"]
        p = os.path.join(worlds.wdir(root, wid), "seg000", "run.wiring.csv")
        raw = bytearray(rqlib.read_bytes(p))
        k = (r["from"] + r["bytes"]) // 2                         # (from, bytes: the part's byte offsets)
        raw[k] = ord("7") if raw[k] != ord("7") else ord("8")
        wr(p, raw.decode())

    def replay_segment(self, root, wid, wiring_to):
        """The replay a reopened world gets: seg001 from seg000's 1000, through the zero again."""
        d = worlds.wdir(root, wid)
        r1000 = [x for x in worlds.accept_records(root, wid) if x["frame"] == 1000][0]
        st = worlds.read_state(root, wid)
        st["segments"].append({"name": "seg001", "start_frame": 1000, "resumed_from": "ckpt/end.1000.json",
                               "resumed_accept": {"segment": "seg000", "frame": 1000, "sha256": r1000["sha256"]},
                               "args": []})
        st["status"] = "running"
        worlds.write_state(root, wid, st)
        os.makedirs(os.path.join(d, "seg001"))
        wr(os.path.join(d, "seg001", "run.csv"), "step,population,predator_pop\n" + "".join(
            f"{f},{0 if f >= 2500 else 50},8\n" for f in range(1100, 2601, 100)))
        wr(os.path.join(d, "seg001", "run.wiring.csv"), "step,PREY_FWD\n" + "".join(
            f"{f},0.5\n" for f in range(100, wiring_to + 1, 100)))

    def test_reopened_extinct_world_replays_through_the_zero(self):
        """Round 3, 2 (P1): an extinct world whose accepted wiring bytes between two acceptances were
        damaged, its zero evidence intact, under --on-extinction stop: reopened, and the extinction
        shortcut does NOT apply (it replays from its latest verified record instead); the replay
        through the zero repairs the accepted logs and the world is extinct again."""
        root, reg, ar, wid = self.extinct_world()
        self.damage_wiring(root, wid)
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        st = worlds.read_state(root, wid)
        self.assertEqual(st["status"], "interrupted", msgs)
        self.assertIn("frame 2000", st["reopened"])
        self.assertEqual(s.first_zero(wid), 2500)                       # the zero still supported
        self.assertNotEqual(s.next_action(wid)[0], "extinct")
        self.assertEqual(worlds.resume_point(root, wid, st, "A")[0], 1000)
        self.replay_segment(root, wid, wiring_to=1600)
        s, msgs = supervisor(root, reg, ar)
        s.tails[wid] = worlds.Tail(os.path.join(worlds.wdir(root, wid), "seg001", "run.csv"))
        s.zeros[wid] = {"prey": 2500}
        s.reap_segment(wid, "seg001", 0)
        st = worlds.read_state(root, wid)
        self.assertEqual(st["status"], "extinct", msgs)
        good = worlds.verified_records(root, wid, st, "A")
        self.assertIn(("seg001", 2000), good)
        self.assertTrue(worlds.audit_archive(root, wid, ar, "extinct"))
        s, msgs = supervisor(root, reg, ar)                             # and it stays extinct
        s.startup()
        self.assertEqual(worlds.read_state(root, wid)["status"], "extinct", msgs)

    def test_reopened_extinct_world_unrepaired_fails(self):
        """Round 3, 2 (P1): a replay through the zero that does not repair the accepted logs fails
        the world explicitly (exit 1), instead of finalizing it as extinct again."""
        root, reg, ar, wid = self.extinct_world()
        self.damage_wiring(root, wid)
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        self.replay_segment(root, wid, wiring_to=900)                    # its wiring log stops short
        s, msgs = supervisor(root, reg, ar)
        s.tails[wid] = worlds.Tail(os.path.join(worlds.wdir(root, wid), "seg001", "run.csv"))
        s.zeros[wid] = {"prey": 2500}
        s.reap_segment(wid, "seg001", 0)
        st = worlds.read_state(root, wid)
        self.assertEqual(st["status"], "failed", msgs)
        self.assertIn("could not be repaired", st["end_reason"])

    def test_finalized_archive_audited_before_recovery(self):
        """Round 3, 2: at a start the finalized archive is audited in full before a reopened world's
        recovery begins: damaged archived bytes fail it even when its logs would reopen it."""
        root, reg, ar, wid = self.extinct_world()
        self.damage_wiring(root, wid)
        rec = worlds.archive_records(root, wid)["end.1000"]
        n = os.path.getsize(rec["path"])
        os.chmod(rec["path"], 0o644)
        wr(rec["path"], "x" * n)
        os.chmod(rec["path"], 0o444)
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        st = worlds.read_state(root, wid)
        self.assertEqual(st["status"], "failed", msgs)
        self.assertIn("finalized archive", st["end_reason"])
        self.assertFalse(any("REOPENED" in m for m in msgs), msgs)

    def test_archive_claim_exclusive(self):
        """Round 3, 1 (P1): two study roots claiming one empty archive at once: one wins, the other
        refuses with nothing written (a second command is refused while the archive lock is held)."""
        reg_bytes = None
        roots = []
        arena = os.path.join(self.tmp, "arena.json")
        wr(arena, json.dumps(ARENA))
        reg = worlds.register(arena, "ns-unit", blocks=1, per_block={"A": 1, "B": 0, "C": 0}, schedule=SCHED)
        reg_bytes = rqlib.canonical(reg)
        for k in range(2):
            r = os.path.join(self.tmp, f"root{k}")
            worlds.write_registry(os.path.join(r, "config", "worlds.json"), reg_bytes)
            roots.append(r)
        ar = os.path.join(self.tmp, "shared_archive")
        code = ("import sys; sys.path.insert(0, %r); import worlds\n"
                "root, ar = sys.argv[1], sys.argv[2]\n"
                "_, sha = worlds.load_registry(root)\n"
                "try:\n"
                "    worlds.bind_root(root, sha, ar, create=True); print('WON', flush=True)\n"
                "except worlds.WorldsError as e:\n"
                "    print('REFUSED', e, flush=True)\n"
                "sys.stdin.read()\n") % worlds.HERE
        import subprocess
        ps = [subprocess.Popen([sys.executable, "-I", "-c", code, r, ar], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True) for r in roots]
        outs = [p.stdout.readline().strip() for p in ps]                 # both decided, both still running
        for p in ps:
            p.stdin.close()
            p.wait()
            p.stdout.close()
        won = [k for k, o in enumerate(outs) if o.startswith("WON")]
        self.assertEqual(len(won), 1, outs)
        lost = 1 - won[0]
        self.assertTrue(outs[lost].startswith("REFUSED"), outs)
        self.assertFalse(os.path.exists(os.path.join(roots[lost], "study.json")))   # nothing written
        owner = rqlib.read_json(os.path.join(ar, worlds.OWNER))
        self.assertEqual(owner["study_id"], rqlib.read_json(os.path.join(roots[won[0]], "study.json"))["study_id"])
        self.assertEqual(sorted(os.listdir(ar)), sorted([worlds.ARCHIVE_LOCK, worlds.OWNER]))
        # a command holding the archive lock refuses another root's binding outright
        worlds.release_archives()
        root3 = os.path.join(self.tmp, "root3")
        worlds.write_registry(os.path.join(root3, "config", "worlds.json"), reg_bytes)
        _, sha = worlds.load_registry(root3)
        ar2 = os.path.join(self.tmp, "archive2")
        held = worlds._flock(os.path.join(ar2, worlds.ARCHIVE_LOCK))
        try:
            with self.assertRaisesRegex(worlds.WorldsError, "another worlds.py holds"):
                worlds.bind_root(root3, sha, ar2, create=True)
        finally:
            held.close()
        self.assertFalse(os.path.exists(os.path.join(root3, "study.json")))
        self.assertEqual(os.listdir(ar2), [worlds.ARCHIVE_LOCK])
        # the marker's publication is exclusive even past every check (a hard link, not a rename): a
        # rival marker published between this claim's checks and its link wins, this one is refused
        worlds.bind_root(root3, sha, ar2, create=True)
        mine = rqlib.read_json(os.path.join(ar2, worlds.OWNER))
        ar3 = os.path.join(self.tmp, "archive3")
        os.makedirs(ar3)
        rival = os.path.join(self.tmp, "rival.json")
        wr(rival, json.dumps(mine))
        intruder = dict(mine, study_id="00000000-0000-4000-8000-00000000beef")
        real_link = os.link

        def racing_link(src, dst):
            real_link(rival, dst)                                  # the rival publishes first
            return real_link(src, dst)
        os.link = racing_link
        try:
            with self.assertRaisesRegex(worlds.WorldsError, "claimed by another study"):
                worlds.claim_archive(ar3, intruder)
        finally:
            os.link = real_link
        self.assertEqual(rqlib.read_json(os.path.join(ar3, worlds.OWNER))["study_id"], mine["study_id"])
        self.assertNotIn(worlds.OWNER + ".tmp", os.listdir(ar3))

    def test_interrupted_claim_resumed(self):
        """Round 3, 1: a crash between the marker's tmp and its link: the same study's next command
        completes the claim; another study's or an unreadable tmp is refused."""
        root, reg, ar = make_root(self.tmp, "A")
        study = rqlib.read_json(os.path.join(root, "study.json"))
        sha = study["registry_sha256"]
        owner = os.path.join(ar, worlds.OWNER)
        rec = rqlib.read_bytes(owner)
        for tmp_bytes, ok in ((rec, True), (rec.replace(study["study_id"].encode(),
                                                         b"00000000-0000-4000-8000-00000000beef"), False),
                              (b"", False)):
            worlds.release_archives()
            os.chmod(owner, 0o644)
            os.remove(owner)
            wr(owner + ".tmp", tmp_bytes.decode())
            if ok:
                self.assertEqual(worlds.bind_root(root, sha), ar)
                self.assertEqual(rqlib.read_json(owner)["study_id"], study["study_id"])
                self.assertNotIn(worlds.OWNER + ".tmp", os.listdir(ar))
            else:
                with self.assertRaisesRegex(worlds.WorldsError, "interrupted claim"):
                    worlds.bind_root(root, sha)
                self.assertFalse(os.path.exists(owner))
                os.remove(owner + ".tmp")
                wr(owner, rec.decode())

    def test_bootstrap_and_quarantine_durability(self):
        """Round 3, 4: directories are created with mkdirs_durable (every new ancestor's parent
        fsync'd), every bootstrap path included; a quarantine fsyncs the moved file and both
        directories before its record."""
        calls = []
        real_dir, real_file, real_append = worlds.rqlib.fsync_dir, worlds.rqlib.fsync_file, worlds._append_durable
        worlds.rqlib.fsync_dir = lambda p: (calls.append(("dir", os.path.abspath(p))), real_dir(p))[1]
        worlds.rqlib.fsync_file = lambda p: (calls.append(("file", os.path.abspath(p))), real_file(p))[1]
        worlds._append_durable = lambda p, r: (calls.append(("append", os.path.basename(p))), real_append(p, r))[1]
        try:
            base = os.path.join(self.tmp, "a")
            worlds.mkdirs_durable(os.path.join(base, "b", "c"))
            for d in (self.tmp, base, os.path.join(base, "b")):
                self.assertIn(("dir", os.path.abspath(d)), calls)
            # f1 on a freshly bound root (a stand-in engine that writes a prepared checkpoint)
            root, reg, ar = make_root(self.tmp, "A")
            wid = reg["worlds"][0]["id"]
            src = os.path.join(self.tmp, "F1src.json")
            wr(src, ckpt.dumps(mk_cp(frame=1, cfg_extra=cfg_for(reg["worlds"][0]["flags"]))))
            exe = os.path.join(self.tmp, "fake_engine")
            wr(exe, '#!/bin/sh\nout=""; prev=""\nfor a in "$@"; do\n  if [ "$prev" = "--save-checkpoint" ]; '
                    'then out="$a"; fi\n  prev="$a"\ndone\ncp "%s" "$out"\n' % src)
            os.chmod(exe, 0o755)
            worlds.release_archives()
            del calls[:]
            a = argparse.Namespace(root=root, allow_placeholder=False, archive_root=None, binary=exe, world=None)
            self.assertEqual(worlds.f1(a, lambda m: None), 0)
            self.assertIn("F1", worlds.archive_records(root, wid))
            wd = worlds.wdir(root, wid)
            for d in (os.path.join(root, "bin"), os.path.join(root, "worlds"), wd, os.path.join(wd, "f1")):
                self.assertIn(("dir", os.path.dirname(d)), calls, d)
            self.assertLess(calls.index(("dir", os.path.join(root, "worlds"))), calls.index(("append", "archive.jsonl")))
            # a quarantine
            sub = tempfile.mkdtemp(dir=self.tmp)
            self.tmp, keep = sub, self.tmp
            try:
                root, reg, ar, wid = self.world(total=4000, ckpts=(1000,))
            finally:
                self.tmp = keep
            p = os.path.join(worlds.wdir(root, wid), "ckpt", "end.2000.json")
            wr(p, "")
            del calls[:]
            s, msgs = supervisor(root, reg, ar)
            s.startup()
            q = self.quarantined(root, wid)[0]
            qd = os.path.dirname(q["to"])
            k = calls.index(("append", "quarantine.jsonl"))
            for c in (("file", q["to"]), ("dir", qd), ("dir", os.path.dirname(p))):
                self.assertLess(calls.index(c), k, c)
        finally:
            worlds.rqlib.fsync_dir, worlds.rqlib.fsync_file, worlds._append_durable = real_dir, real_file, real_append
        # no plain os.makedirs left on a bootstrap path (the helper itself and the throwaway probe only)
        src = rqlib.read_text(os.path.join(worlds.HERE, "worlds.py")).splitlines()
        plain = [ln.strip() for ln in src if "os.makedirs(" in ln]
        self.assertEqual(plain, ["os.makedirs(path, exist_ok=True)", "os.makedirs(d)"], plain)

    def test_non_serial_checkpoint_refused(self):
        """P2 (6): a checkpoint that declares a non-exact resume is never archived or accepted."""
        root, reg, ar, wid = self.world(total=4000, ckpts=())
        cp = mk_cp(frame=1000, cfg_extra=cfg_for(reg["worlds"][0]["flags"]))
        cp["determinism"] = "openmp-build (resume is NOT bit-exact)"
        p = os.path.join(worlds.wdir(root, wid), "ckpt", "end.1000.json")
        wr(p, ckpt.dumps(cp))
        with self.assertRaisesRegex(worlds.TornCheckpoint, "serial build"):
            worlds.archive_one(root, wid, ar, 1000, p, lambda m: None)


class TestBinary(unittest.TestCase):
    """P2 (6): the pinned engine must be the serial build; the F1 verification is bound to it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        rm_tree(self.tmp)

    def fake_engine(self, name, determinism):
        p = os.path.join(self.tmp, name)
        wr(p, "#!/bin/sh\nout=\nwhile [ $# -gt 0 ]; do [ \"$1\" = --save-checkpoint ] && out=$2; shift; done\n"
              f"printf '{{\"determinism\": \"{determinism}\", \"engineVersion\": \"fake\"}}' > \"$out\"\n")
        os.chmod(p, 0o755)
        return p

    def test_identity(self):
        r1 = os.path.join(self.tmp, "r1")
        with self.assertRaisesRegex(worlds.WorldsError, "serial"):
            worlds.pin_binary(r1, self.fake_engine("omp", "openmp-build (resume is NOT bit-exact)"))
        r2 = os.path.join(self.tmp, "r2")
        exe = self.fake_engine("serial", worlds.SERIAL)
        path, sha = worlds.pin_binary(r2, exe)
        self.assertEqual(sha, rqlib.sha256_file(exe))
        ident = rqlib.read_json(os.path.join(r2, "bin", "identity.json"))
        self.assertEqual((ident["sha256"], ident["determinism"]), (sha, worlds.SERIAL))
        self.assertEqual(worlds.pin_binary(r2), (path, sha))           # the pinned one, rechecked
        with self.assertRaisesRegex(worlds.WorldsError, "another engine"):
            worlds.pin_binary(r2, self.fake_engine("other", worlds.SERIAL + " "))
        # the F1 verification counts only with the pinned engine's hash and the archived bytes
        os.makedirs(os.path.join(r2, "worlds", "w01"))
        for lab, fr in (("F1", 1), ("end.1000", 1000)):
            worlds._append_durable(os.path.join(r2, "worlds", "w01", "archive.jsonl"),
                                   {"label": lab, "frame": fr, "sha256": lab[0] * 64})
        v = {"identical": True, "binary_sha256": sha, "f1_sha256": "F" * 64, "first_checkpoint_sha256": "e" * 64}
        rqlib.write_json_durable(os.path.join(r2, "worlds", "w01", "f1_verify.json"), v)
        self.assertTrue(worlds.f1_verified(r2, "w01", sha, 1000))
        self.assertFalse(worlds.f1_verified(r2, "w01", "0" * 64, 1000))
        rqlib.write_json_durable(os.path.join(r2, "worlds", "w01", "f1_verify.json"), dict(v, identical=False))
        self.assertFalse(worlds.f1_verified(r2, "w01", sha, 1000))


class TestBurnIn(unittest.TestCase):
    """USER DECISIONS 2, items 5-6: seed slots reserved for up to 2A + 2B per block; a world extinct before
    the burn-in frame restarts from its slot's next reserved seed (ledger, moves, fresh attempt)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        worlds.release_archives()
        rm_tree(self.tmp)

    def test_slot_seeds_and_reservations(self):
        arena = os.path.join(self.tmp, "arena.json")
        wr(arena, json.dumps(ARENA))
        regs = {n: worlds.register(arena, "ns-slots", blocks=2, per_block=pb, schedule=SCHED)
                for n, pb in ((48, {"C": 4, "A": 1, "B": 1}), (56, {"C": 4, "A": 2, "B": 1}),
                              (64, {"C": 4, "A": 2, "B": 2}))}
        for r in regs.values():
            self.assertEqual((r["seed_scheme"], r["burn_in"], r["max_restarts"]), ("slot/1", 5_000_000, 8))
            self.assertEqual(r["reserve_per_block"], {"C": 4, "A": 2, "B": 2})
            self.assertEqual(len(r["reserved"]), 2 * 8)
            seeds = [x for slot in r["reserved"] for x in slot["seeds"]]
            self.assertEqual(len(seeds), 2 * 8 * 9)
            self.assertEqual(len(set(seeds)), len(seeds))                     # all distinct
            self.assertEqual(r["reserved"], regs[48]["reserved"])            # the reservation is allocation-free
        by = {n: {w["seed_slot"]: w["founder_seed"] for w in r["worlds"]} for n, r in regs.items()}
        for slot, seed in by[48].items():
            self.assertEqual(by[56][slot], seed)
            self.assertEqual(by[64][slot], seed)
        self.assertEqual(len(by[64]), 16)
        self.assertIn("b1:A:1", by[56])
        self.assertNotIn("b1:B:1", by[56])
        res = {x["slot"]: x["seeds"][0] for x in regs[48]["reserved"]}
        self.assertEqual(res["b2:B:1"], by[64]["b2:B:1"])                    # the 64-allocation's extra B
        # a reserved seed is refused when it is avoided elsewhere: re-derived
        av = os.path.join(self.tmp, "avoid.txt")
        wr(av, f"{res['b1:A:1']}\n")
        r2 = worlds.register(arena, "ns-slots", blocks=2, per_block={"C": 4, "A": 1, "B": 1}, schedule=SCHED,
                             avoid_paths=[av])
        new = {x["slot"]: x["seeds"][0] for x in r2["reserved"]}
        self.assertNotEqual(new["b1:A:1"], res["b1:A:1"])
        self.assertEqual(new["b1:A:0"], res["b1:A:0"])

    def world(self, zero_at=2500, burn_in=3000, max_restarts=8):
        root, reg, ar = make_root(self.tmp, "A", dict(SCHED, total_steps=3000), burn_in=burn_in, max_restarts=max_restarts)
        w = reg["worlds"][0]
        wid = w["id"]
        d = worlds.wdir(root, wid)
        os.makedirs(os.path.join(d, "seg000"))
        os.makedirs(os.path.join(d, "ckpt"))
        cfg = cfg_for(w["flags"])
        f1p = os.path.join(self.tmp, "F1.json")
        wr(f1p, ckpt.dumps(mk_cp(frame=1, cfg_extra=cfg)))
        worlds.archive_one(root, wid, ar, 1, f1p, lambda m: None, extra={"binary_sha256": EXE_SHA})
        wr(os.path.join(d, "seg000", "run.csv"), "step,population,predator_pop\n" + "".join(
            f"{f},{0 if f >= zero_at else 50},8\n" for f in range(100, 3001, 100)))
        wr(os.path.join(d, "seg000", "run.wiring.csv"), "step,PREY_FWD\n" + "".join(
            f"{f},0.5\n" for f in range(100, 3001, 100)))
        for f in (1000, 2000):
            wr(os.path.join(d, "ckpt", f"end.{f}.json"), ckpt.dumps(mk_cp(frame=f, cfg_extra=cfg)))
        worlds.write_state(root, wid, {"schema": worlds.STATE_SCHEMA, "id": wid, "status": "interrupted", "failures": 0,
                                       "segments": [{"name": "seg000", "start_frame": 0, "resumed_from": None,
                                                     "resumed_accept": None, "args": []}]})
        return root, reg, ar, wid

    def test_restart_before_burn_in(self):
        root, reg, ar, wid = self.world(zero_at=2500, burn_in=3000)
        seeds = reg["reserved"][[x["slot"] for x in reg["reserved"]].index(reg["worlds"][0]["seed_slot"])]["seeds"]
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        led = worlds.restart_records(root)
        self.assertEqual(len(led), 1, msgs)
        r = led[0]
        self.assertEqual((r["world"], r["attempt"], r["failed_seed"], r["seed"], r["zero_frame"]),
                         (wid, 1, seeds[0], seeds[1], 2500))
        old = os.path.join(root, "restarts", "worlds", f"{wid}.a0")
        self.assertTrue(os.path.isfile(os.path.join(old, "seg000", "run.csv")))      # the failed attempt kept
        self.assertTrue(os.path.isfile(os.path.join(ar, "restarts", f"{wid}.a0", "F1.json")))
        self.assertFalse(os.path.exists(os.path.join(worlds.adir(ar, wid), "FINALIZED")))
        self.assertEqual(worlds.attempt_of(root, wid), 1)
        st = worlds.read_state(root, wid)
        self.assertEqual((st["status"], st["segments"], st["attempt"]), ("pending", [], 1))
        self.assertEqual(s.worlds[wid]["config_args"][-2:], ["--seed", str(seeds[1])])
        self.assertEqual(s.next_action(wid), ("f1", None))                       # its F1 first
        a = worlds.segment_args(s.worlds[wid], reg["schedule"], "seg000", 0)
        self.assertEqual(a[a.index("--seed") + 1], str(seeds[1]))
        av = worlds.read_jsonl(os.path.join(root, "availability.jsonl"))
        self.assertTrue(av and not any(worlds.zero_supported(root, e) for e in av))   # not the new attempt's zero
        rep_ = worlds.burn_in_report(root, reg)
        self.assertEqual(rep_["per_treatment"]["A"], {"worlds": 1, "restarts": 1, "attempts_started": 1,
                                                      "early_failures": 1, "established": 0, "pending": 1,
                                                      "unresolved": 0, "failed": 0, "failed_before_start": 0,
                                                      "early_failure_rate": 1.0})
        # the retained attempt's archive index resolves to its own relocated bytes (#70 review 3)
        recs = worlds.attempt_archive_records(root, wid, 0)
        self.assertTrue(recs and all(r["path"].startswith(os.path.join(ar, "restarts", f"{wid}.a0") + os.sep)
                                     for r in recs.values()))
        self.assertEqual(worlds.audit_attempt(root, wid, 0), [])
        self.assertEqual(rqlib.read_json(os.path.join(old, "relocated.json"))["archive_to"],
                         os.path.join(ar, "restarts", f"{wid}.a0"))
        # a new supervisor sees the attempt (the ledger), and the f1 command would use its seed
        s2, _ = supervisor(root, reg, ar)
        self.assertEqual(s2.worlds[wid]["founder_seed"], seeds[1])
        self.assertEqual(worlds.effective_worlds(root, reg)[wid]["attempt"], 1)

    def test_extinction_after_burn_in_is_data(self):
        root, reg, ar, wid = self.world(zero_at=2500, burn_in=2000)
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        self.assertEqual(worlds.read_state(root, wid)["status"], "extinct", msgs)
        self.assertEqual(worlds.restart_records(root), [])

    def test_restarts_exhausted(self):
        root, reg, ar, wid = self.world(zero_at=2500, burn_in=3000, max_restarts=1)
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        self.assertEqual(worlds.attempt_of(root, wid), 1)
        f1p = os.path.join(self.tmp, "F1b.json")                           # (attempt 1's F1, as reap_f1 would)
        wr(f1p, ckpt.dumps(mk_cp(frame=1, seed=7, cfg_extra=cfg_for(reg["worlds"][0]["flags"]))))
        worlds.archive_one(root, wid, ar, 1, f1p, lambda m: None, extra={"binary_sha256": EXE_SHA})
        s.zeros[wid] = {"prey": 1500}
        s.end_world(wid, "extinct", "the prey reached 0 at frame 1500")
        st = worlds.read_state(root, wid)
        self.assertEqual(st["status"], "extinct", msgs)
        self.assertIn("restarts exhausted", st["end_reason"])
        self.assertEqual(len(worlds.restart_records(root)), 1)

    def test_recorded_restart_completed_after_a_crash(self):
        """The restart record is the commitment: a crash before the moves is completed at the next start;
        a second start changes nothing."""
        root, reg, ar, wid = self.world(zero_at=2500, burn_in=3000)
        w = reg["worlds"][0]
        seeds = next(x["seeds"] for x in reg["reserved"] if x["slot"] == w["seed_slot"])
        worlds._append_durable(os.path.join(root, "restarts.jsonl"), {
            "schema": worlds.RESTART_SCHEMA, "world": wid, "treatment": "A", "slot": w["seed_slot"], "attempt": 1,
            "failed_attempt": 0, "failed_seed": seeds[0], "seed": seeds[1], "zero_frame": 2500})
        s, msgs = supervisor(root, reg, ar)
        self.assertEqual(s.worlds[wid]["attempt"], 1)
        s.startup()
        self.assertTrue(any("completed" in m for m in msgs), msgs)
        self.assertTrue(os.path.isdir(os.path.join(root, "restarts", "worlds", f"{wid}.a0")))
        self.assertEqual((worlds.attempt_of(root, wid), worlds.read_state(root, wid)["status"]), (1, "pending"))
        s2, msgs2 = supervisor(root, reg, ar)
        s2.startup()
        self.assertFalse(any("completed" in m for m in msgs2), msgs2)
        self.assertEqual(len(os.listdir(os.path.join(root, "restarts", "worlds"))), 1)

    def test_evidence_durable_before_the_commitment(self):
        """#70 review 1 (P1): the failed attempt's evidence (its run.csv, its segment directory, every file and
        directory of the attempt and its archive) is fsync'd BEFORE the restart record."""
        root, reg, ar, wid = self.world(zero_at=2500, burn_in=3000)
        ev = []
        of, od, oa = worlds.rqlib.fsync_file, worlds.rqlib.fsync_dir, worlds._append_durable
        worlds.rqlib.fsync_file = lambda q: (ev.append(("file", os.path.abspath(q))), of(q))[1]
        worlds.rqlib.fsync_dir = lambda q: (ev.append(("dir", os.path.abspath(q))), od(q))[1]
        worlds._append_durable = lambda q, rec: (ev.append(("append", os.path.basename(q))), oa(q, rec))[1]
        try:
            s, msgs = supervisor(root, reg, ar)
            s.startup()
        finally:
            worlds.rqlib.fsync_file, worlds.rqlib.fsync_dir, worlds._append_durable = of, od, oa
        commit = ev.index(("append", "restarts.jsonl"))
        d = worlds.wdir(root, wid)
        for e in (("file", os.path.join(d, "seg000", "run.csv")), ("dir", os.path.join(d, "seg000")), ("dir", d),
                  ("file", os.path.join(worlds.adir(ar, wid), "F1.json")), ("dir", worlds.adir(ar, wid))):
            self.assertIn(e, ev[:commit], e)

    def test_exhausted_and_pending_in_the_rate(self):
        """#70 review 5: an exhausted early failure counts; a not-yet-started attempt is outside the rate."""
        root, reg, ar, wid = self.world(zero_at=2500, burn_in=3000, max_restarts=0)
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        st = worlds.read_state(root, wid)
        self.assertEqual(st["status"], "extinct", msgs)
        self.assertIn("restarts exhausted", st["end_reason"])
        p = worlds.burn_in_report(root, reg)["per_treatment"]["A"]
        self.assertEqual((p["restarts"], p["attempts_started"], p["early_failures"], p["early_failure_rate"]), (0, 1, 1, 1.0))

    def test_continue_does_not_bypass_the_burn_in(self):
        """#70 review 8: under --on-extinction continue an early zero still restarts the world."""
        root, reg, ar, wid = self.world(zero_at=2500, burn_in=3000)
        s, msgs = supervisor(root, reg, ar, on_extinction="continue")
        s.startup()
        self.assertEqual(len(worlds.restart_records(root)), 1, msgs)

    def test_malformed_rows_are_no_evidence(self):
        """#70 review 9: a non-integral count, a short row or a frame off the sequence is not a zero (and no
        evidence is read past it); a valid zero row is."""
        root, reg, ar, wid = self.world(zero_at=10 ** 9, burn_in=3000)
        d = os.path.join(worlds.wdir(root, wid), "seg000", "run.csv")
        st = worlds.read_state(root, wid)
        hdr = "step,population,predator_pop\n"
        for bad in ("100,50,8\n200,0.5,8\n", "100,50,8\n200,0\n", "100,50,8\n300,0,8\n", "100,50,8\n200,x,8\n300,0,8\n"):
            wr(d, hdr + bad)
            self.assertEqual(worlds.scan_zeros(root, wid, st, "A", 100), {}, bad)
        wr(d, hdr + "100,50,8\n200,0,8\n")
        self.assertEqual(worlds.scan_zeros(root, wid, st, "A", 100)["prey"][0], 200)

    def test_layouts_and_slots(self):
        """#70 review 6: the real 56 layout (4C+2A+1B and 4C+1A+2B blocks alternating: 32C, 12A, 12B), and
        48 / 64; slots keep their seeds across them."""
        arena = os.path.join(self.tmp, "arena.json")
        wr(arena, json.dumps(ARENA))
        regs = {n: worlds.register(arena, "ns-lay", blocks=8, per_block=worlds.LAYOUTS[n], schedule=SCHED, layout=n)
                for n in ("48", "56", "64")}
        self.assertEqual((regs["56"]["layout"], regs["56"]["block_allocations"]["2"]), ("56", {"C": 4, "A": 1, "B": 2}))
        self.assertIn("exchangeable", regs["56"]["allocation_note"])
        for n, want in (("48", (32, 8, 8)), ("56", (32, 12, 12)), ("64", (32, 16, 16))):
            c = Counter(w["treatment"] for w in regs[n]["worlds"])
            self.assertEqual((c["C"], c["A"], c["B"]), want, n)
        by_block = Counter((w["block"], w["treatment"]) for w in regs["56"]["worlds"])
        for b in range(1, 9):
            self.assertEqual((by_block[(b, "A")], by_block[(b, "B")]), (2, 1) if b % 2 else (1, 2), b)
        seeds = {n: {w["seed_slot"]: w["founder_seed"] for w in r["worlds"]} for n, r in regs.items()}
        for slot, seed in seeds["56"].items():
            self.assertEqual(seeds["64"][slot], seed)
        self.assertEqual(regs["56"]["reserved"], regs["48"]["reserved"])
        self.assertEqual(worlds.parse_per_block("C=4,A=2,B=1;C=4,A=1,B=2"), worlds.LAYOUTS["56"])

    def test_reserved_universe_avoidable(self):
        """#70 review 7: a worlds registry given to plan.py --avoid yields every reserved history seed."""
        import plan
        root, reg, ar, wid = self.world(zero_at=10 ** 9, burn_in=3000)
        res = {x for slot in reg["reserved"] for x in slot["seeds"]}
        got = plan.avoid_seeds(os.path.join(root, "config", "worlds.json"))
        self.assertTrue(res <= got)

    def test_f1_reconciles_before_writing(self):
        """#70 review 4: f1 (and verify-f1) complete an interrupted restart before anything else."""
        root, reg, ar, wid = self.world(zero_at=2500, burn_in=3000)
        w = reg["worlds"][0]
        seeds = next(x["seeds"] for x in reg["reserved"] if x["slot"] == w["seed_slot"])
        worlds._append_durable(os.path.join(root, "restarts.jsonl"), {
            "schema": worlds.RESTART_SCHEMA, "world": wid, "treatment": "A", "slot": w["seed_slot"], "attempt": 1,
            "failed_attempt": 0, "failed_seed": seeds[0], "seed": seeds[1], "zero_frame": 2500})

        class Stop(Exception):
            pass
        orig = worlds.pin_binary
        worlds.pin_binary = lambda *a_, **k_: (_ for _ in ()).throw(Stop())
        try:
            for cmd in (worlds.f1, worlds.verify_f1):
                with self.assertRaises(Stop):
                    cmd(argparse.Namespace(root=root, allow_placeholder=False, archive_root=None, binary=None,
                                           world=None), lambda m: None)
                self.assertEqual(worlds.attempt_of(root, wid), 1)
        finally:
            worlds.pin_binary = orig

    def test_decided_needs_survival_without_an_early_zero(self):
        """#70 round 2, 1 (P1): an attempt with an evidenced zero before the burn-in frame is never decided
        alive, even with an acceptance at or past the burn-in frame; without the zero it is."""
        for zero_at, want in ((1500, False), (10 ** 9, True)):
            worlds.release_archives()
            rm_tree(self.tmp)
            os.makedirs(self.tmp)
            root, reg, ar, wid = self.world(zero_at=zero_at, burn_in=2000)
            s, msgs = supervisor(root, reg, ar)
            s.archive_pass(wid, alive=False)
            s.accept_pass(wid, alive=False)
            s.recover_zeros(wid)
            self.assertIn(2000, [r["frame"] for r in worlds.accept_records(root, wid)])
            got, why = worlds.burn_in_decided(root, reg, wid)
            self.assertEqual(got, want, why)
            if not want:
                self.assertIn("will be restarted", why)

    def test_decided_from_the_rows_before_the_zero_is_published(self):
        """#70 round 3 (P1): the pre-publication window. A main-CSV zero at 1500 and an acceptance at 2000,
        the admission BEFORE recover_zeros (no zero in the ledger yet): not decided (the verified rows show
        the zero); a zero exactly at the burn-in frame is data (decided); no zero: decided alive; a chain
        whose rows end before the burn-in frame: not decided."""
        for zero_at, want, word in ((1500, False, "will be restarted"), (2000, True, "(data)"),
                                    (10 ** 9, True, "nonzero through frame 2000")):
            worlds.release_archives()
            rm_tree(self.tmp)
            os.makedirs(self.tmp)
            root, reg, ar, wid = self.world(zero_at=zero_at, burn_in=2000)
            s, msgs = supervisor(root, reg, ar)
            s.archive_pass(wid, alive=False)
            s.accept_pass(wid, alive=False)                 # (no recover_zeros: nothing published)
            self.assertIn(2000, [r["frame"] for r in worlds.accept_records(root, wid)])
            self.assertFalse(os.path.isfile(os.path.join(root, "availability.jsonl")))
            got, why = worlds.burn_in_decided(root, reg, wid)
            self.assertEqual(got, want, why)
            self.assertIn(word, why)
        worlds.release_archives()
        rm_tree(self.tmp)
        os.makedirs(self.tmp)
        root, reg, ar, wid = self.world(zero_at=10 ** 9, burn_in=2500)
        s, msgs = supervisor(root, reg, ar)
        s.archive_pass(wid, alive=False)
        s.accept_pass(wid, alive=False)                     # (the chain ends at 2000 < 2500)
        got, why = worlds.burn_in_decided(root, reg, wid)
        self.assertFalse(got, why)
        self.assertIn("not passed the burn-in frame", why)

    def test_startup_publishes_zeros_before_accepting(self):
        """#70 round 3 (belt and braces): at startup a world's zeros are recovered (published) before its
        acceptance pass, so no acceptance past an early zero exists while the zero is unpublished."""
        root, reg, ar, wid = self.world(zero_at=1500, burn_in=2000)
        s, msgs = supervisor(root, reg, ar)
        seen = []
        orig = s.accept_pass

        def spy(w, alive):
            seen.append(any(e["world"] == w for e in worlds.read_jsonl(os.path.join(root, "availability.jsonl"))))
            return orig(w, alive)
        s.accept_pass = spy
        s.startup()
        self.assertTrue(seen and seen[0], (seen, msgs))

    def test_live_invalid_row_barrier_persists(self):
        """#70 round 2, 2: once a segment shows an invalid row, no later row of it is evidence (the tail has
        moved past the batch): 100,50,8 / 150,50,8 (off the sequence) / later 200,0,8: no zero."""
        root, reg, ar, wid = self.world(zero_at=10 ** 9, burn_in=3000)
        p = os.path.join(worlds.wdir(root, wid), "seg000", "run.csv")
        wr(p, "step,population,predator_pop\n100,50,8\n150,50,8\n")
        s, msgs = supervisor(root, reg, ar)
        s.tails[wid] = worlds.Tail(p)
        self.assertIsNone(s.watch(wid))
        with open(p, "a") as f:
            f.write("200,0,8\n")
        self.assertIsNone(s.watch(wid))
        self.assertEqual(s.zeros.get(wid), None)
        self.assertFalse(os.path.isfile(os.path.join(root, "availability.jsonl")))

    def test_report_keeps_an_established_attempt_through_a_technical_failure(self):
        """#70 round 2, 3: one exhausted early failure and one established attempt that later failed
        technically: 50 %; the technical failure is reported separately."""
        arena = os.path.join(self.tmp, "arena.json")
        wr(arena, json.dumps(ARENA))
        reg = worlds.register(arena, "ns-rep", blocks=1, per_block={"A": 2, "B": 0, "C": 0}, schedule=SCHED,
                              burn_in=2000)
        root = os.path.join(self.tmp, "root")
        worlds.write_registry(os.path.join(root, "config", "worlds.json"), rqlib.canonical(reg))
        w1, w2 = (w["id"] for w in reg["worlds"])
        seg = [{"name": "seg000", "start_frame": 0, "resumed_from": None, "resumed_accept": None, "args": []}]
        worlds.write_state(root, w1, {"schema": worlds.STATE_SCHEMA, "id": w1, "status": "extinct", "failures": 0,
                                      "segments": seg, "end_reason": "the prey reached 0; the restarts exhausted (0)"})
        d = os.path.join(worlds.wdir(root, w2), "seg000")
        os.makedirs(d)
        head = "step,population,predator_pop\n2500,0,8\n"
        wr(os.path.join(d, "run.csv"), head)
        worlds._append_durable(os.path.join(root, "availability.jsonl"), {
            "schema": worlds.AVAIL_SCHEMA, "world": w2, "guild": "prey", "first_zero_frame": 2500,
            "segment": "seg000", "csv_bytes": len(head), "csv_sha256": rqlib.sha256_bytes(head.encode())})
        worlds.write_state(root, w2, {"schema": worlds.STATE_SCHEMA, "id": w2, "status": "failed", "failures": 3,
                                      "segments": seg, "end_reason": "exit 1, no progress"})
        p = worlds.burn_in_report(root, reg)["per_treatment"]["A"]
        self.assertEqual((p["early_failures"], p["established"], p["failed"], p["early_failure_rate"]), (1, 1, 1, 0.5))
        self.assertEqual(worlds.audit_attempt(root, w1, 3)[0][:9], "attempt 3")        # (P3: no such attempt)

    def test_burn_in_off_for_old_registries(self):
        """A registry without seed reservations (scheme before slot/1) keeps the old behaviour."""
        root, reg, ar, wid = self.world(zero_at=2500, burn_in=3000)
        reg2 = {k: v for k, v in reg.items() if k not in ("seed_scheme", "reserved")}
        s, msgs = supervisor(root, reg2, ar)
        self.assertEqual(s.burn_in, 0)


def tree_state(path):
    """{relative path: (sha256 or None for a directory, mode)} of everything under path."""
    out = {}
    for d, dirs, files in os.walk(path):
        out[os.path.relpath(d, path)] = (None, os.stat(d).st_mode)
        for f in files:
            p = os.path.join(d, f)
            out[os.path.relpath(p, path)] = (rqlib.sha256_file(p), os.stat(p).st_mode)
    return out


class TestEcology(unittest.TestCase):
    """Annex H AMENDMENT D6 (rules 22-25, 29-30): the read-only ecological export over EVERY attempt (the
    first evidenced sampled zero, competing prey-terminal events, technical censoring, restarts kept,
    exhausted reservations, rolled-back segments, evidence hashes) and the monitoring indicators. Worlds
    are built through the supervisor's own startup (acceptance, the zero ledger, restarts)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        worlds.release_archives()
        rm_tree(self.tmp)

    def world(self, tr="B", pred=lambda f: 8, prey=lambda f: 50, energy=lambda f: 150.0, burn_in=0, max_restarts=8,
              ckpts=(1000, 2000)):
        root, reg, ar = make_root(self.tmp, tr, dict(SCHED, total_steps=3000), burn_in=burn_in, max_restarts=max_restarts)
        w = reg["worlds"][0]
        wid = w["id"]
        d = worlds.wdir(root, wid)
        os.makedirs(os.path.join(d, "seg000"))
        os.makedirs(os.path.join(d, "ckpt"))
        cfg = cfg_for(w["flags"])
        f1p = os.path.join(self.tmp, "F1.json")
        wr(f1p, ckpt.dumps(mk_cp(frame=1, cfg_extra=cfg)))
        worlds.archive_one(root, wid, ar, 1, f1p, lambda m: None, extra={"binary_sha256": EXE_SHA})
        wr(os.path.join(d, "seg000", "run.csv"), "step,population,predator_pop,predator_avg_energy\n" + "".join(
            f"{f},{prey(f)},{pred(f)},{energy(f)}\n" for f in range(100, 3001, 100)))
        wr(os.path.join(d, "seg000", "run.wiring.csv"), "step,PREY_FWD\n" + "".join(
            f"{f},0.5\n" for f in range(100, 3001, 100)))
        for f in ckpts:
            wr(os.path.join(d, "ckpt", f"end.{f}.json"), ckpt.dumps(mk_cp(frame=f, cfg_extra=cfg)))
        worlds.write_state(root, wid, {"schema": worlds.STATE_SCHEMA, "id": wid, "status": "interrupted", "failures": 0,
                                       "segments": [{"name": "seg000", "start_frame": 0, "resumed_from": None,
                                                     "resumed_accept": None, "args": []}]})
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        return root, reg, ar, wid, msgs

    def test_predator_extinction_is_the_first_sampled_zero(self):
        root, reg, ar, wid, msgs = self.world(pred=lambda f: 0 if f >= 2500 else 8, burn_in=2000)
        self.assertEqual(worlds.read_state(root, wid)["status"], "extinct", msgs)
        doc = worlds.ecology(root, reg, [1000, 2500, 3000])
        o = doc["slots"][wid]["attempts"][0]
        self.assertEqual(o["events"], {"predators": {"frame": 2500, "previous_sample": 2400}, "prey": None})
        self.assertEqual((o["first_terminal"], o["observation"], o["burn_in"], o["establishment"]),
                         ({"frame": 2500, "kind": "predators"}, "event", "established", "established"))
        self.assertEqual((o["accepted_through"], o["frontier"], o["integrity"], o["unsupported_ledger"]), (2000, 2500, [], []))
        ev = o["evidence"]
        d = worlds.wdir(root, wid)
        self.assertEqual(ev["state_sha256"], rqlib.sha256_file(os.path.join(d, "state.json")))
        self.assertEqual(ev["accept_sha256"], rqlib.sha256_file(os.path.join(d, "accept.jsonl")))
        raw = rqlib.read_bytes(os.path.join(d, "seg000", "run.csv"))
        self.assertEqual([(e["segment"], e["through"], e["csv_sha256"]) for e in ev["segments"]],
                         [("seg000", 2000, rqlib.sha256_bytes(raw[:ev["segments"][0]["csv_bytes"]]))])
        self.assertEqual(ev["tail"]["csv_sha256"], rqlib.sha256_bytes(raw[:ev["tail"]["csv_bytes"]]))
        self.assertTrue(raw[:ev["tail"]["csv_bytes"]].endswith(b"2500,50,0,150.0\n"))     # (the prefix through the zero)
        surv = doc["summary"]["B"]["first_attempt"]["survival"]
        self.assertEqual((surv["1000"]["estimate"], surv["2500"]["estimate"], surv["3000"]["counts"]["predator_extinct"]),
                         (1.0, 0.0, 1))                                    # (a zero sampled AT a horizon is extinct there)
        self.assertEqual(doc["summary"]["B"]["first_attempt"]["extinction_times"]["predators"][0]["frame"], 2500)
        self.assertEqual(doc["summary"]["B"]["retained_attempt"]["survival"], surv)
        self.assertEqual(doc["registry_sha256"], rqlib.sha256_file(os.path.join(root, "config", "worlds.json")))

    def test_prey_terminal_is_a_competing_event(self):
        root, reg, ar, wid, msgs = self.world(prey=lambda f: 0 if f >= 2500 else 50)
        doc = worlds.ecology(root, reg, [2500, 3000])
        o = doc["slots"][wid]["attempts"][0]
        self.assertEqual((o["first_terminal"]["kind"], o["events"]["predators"]), ("prey", None))
        surv = doc["summary"]["B"]["first_attempt"]["survival"]
        self.assertEqual(surv["2500"]["estimate"], 1.0)                    # (the predators were seen alive at 2500)
        self.assertEqual((surv["3000"]["counts"]["prey_terminal"], surv["3000"]["complete"], surv["3000"]["bounds"]),
                         (1, False, [0.0, 1.0]))                           # (never predator extinction)
        self.assertNotIn("estimate", surv["3000"])
        self.assertEqual(doc["summary"]["B"]["first_attempt"]["first_terminal_events"]["prey"], 1)
        # both guilds at zero in one sample: a joint event (predator extinct; their order unresolved)
        rm_tree(self.tmp)
        self.tmp = tempfile.mkdtemp()
        root, reg, ar, wid, msgs = self.world(prey=lambda f: 0 if f >= 2500 else 50, pred=lambda f: 0 if f >= 2500 else 8)
        o = worlds.ecology(root, reg, [3000])["slots"][wid]["attempts"][0]
        self.assertEqual((o["joint"], o["first_terminal"]["kind"], worlds.at_horizon(o, 3000)), (True, "joint", "predator_extinct"))

    def test_first_attempt_kept_across_a_restart(self):
        root, reg, ar, wid, msgs = self.world(pred=lambda f: 0 if f >= 1500 else 8, burn_in=2000)
        self.assertEqual(worlds.attempt_of(root, wid), 1, msgs)
        doc = worlds.ecology(root, reg, [3000])
        a0, a1 = doc["slots"][wid]["attempts"]
        seeds = next(x["seeds"] for x in reg["reserved"] if x["slot"] == reg["worlds"][0]["seed_slot"])
        self.assertEqual((a0["source"], a0["seed"], a0["dir"]),
                         ("retained", seeds[0], os.path.join(root, "restarts", "worlds", f"{wid}.a0")))
        self.assertEqual((a0["events"]["predators"]["frame"], a0["burn_in"], a0["establishment"]),
                         (1500, "early_failure", "restarted"))
        self.assertEqual((a0["restart_record"]["zero_frame"], a0["integrity"]), (1500, []))
        self.assertEqual(a0["evidence"]["relocated_sha256"],
                         rqlib.sha256_file(os.path.join(a0["dir"], "relocated.json")))
        self.assertEqual((a1["source"], a1["seed"], a1["observation"], a1["establishment"]),
                         ("current", seeds[1], "ongoing", "unresolved"))
        s = doc["summary"]["B"]
        self.assertEqual(s["first_attempt"]["survival"]["3000"]["estimate"], 0.0)     # (the failure is not erased)
        self.assertEqual(s["retained_attempt"]["survival"]["3000"]["counts"]["not_yet_observed"], 1)
        self.assertEqual((s["attempts"]["early_failures"], s["attempts"]["resolved"], s["attempts"]["early_failure_rate"]),
                         (1, 1, 1.0))
        self.assertEqual((s["establishment_conditional"]["survival"]["3000"]["N"],
                          s["establishment_conditional"]["excluded_unresolved"]), (0, 1))

    def test_exhausted_reservation_is_an_establishment_failure(self):
        root, reg, ar, wid, msgs = self.world(pred=lambda f: 0 if f >= 1500 else 8, burn_in=2000, max_restarts=0)
        self.assertIn("restarts exhausted", worlds.read_state(root, wid)["end_reason"], msgs)
        doc = worlds.ecology(root, reg, [3000])
        o = doc["slots"][wid]["attempts"][0]
        self.assertEqual((o["establishment"], doc["slots"][wid]["exhausted"], o["censor"]), ("exhausted", True, None))
        self.assertEqual(doc["summary"]["B"]["attempts"]["exhausted_slots"], 1)
        self.assertEqual(doc["summary"]["B"]["first_attempt"]["survival"]["3000"]["counts"]["predator_extinct"], 1)

    def test_technical_censoring_rollback_and_unsupported_ledger(self):
        root, reg, ar, wid, msgs = self.world(pred=lambda f: 0 if f >= 2500 else 8, burn_in=2000)
        d = worlds.wdir(root, wid)
        p = os.path.join(d, "seg000", "run.csv")
        raw = rqlib.read_bytes(p)
        os.chmod(p, 0o644)
        wr(p, raw.replace(b"1500,50,8,", b"1500,50,9,").decode())        # (an accepted row damaged: same length)
        o = worlds.ecology(root, reg, [1000, 3000])["slots"][wid]["attempts"][0]
        self.assertEqual((o["accepted_through"], o["frontier"], o["events"]["predators"]), (1000, 1000, None))
        self.assertEqual([u["why"][:22] for u in o["unsupported_ledger"]], ["its main-CSV prefix no"])
        self.assertEqual((o["observation"], o["censor"]), ("technical", {"kind": "technical", "frame": 1000}))
        self.assertTrue(any("says extinct" in x for x in o["integrity"]), o["integrity"])
        doc = worlds.ecology(root, reg, [1000, 3000])
        self.assertEqual((doc["summary"]["B"]["first_attempt"]["survival"]["1000"]["counts"]["alive"],
                          doc["summary"]["B"]["first_attempt"]["survival"]["3000"]["counts"]["technical"]), (1, 1))
        # a technically failed world: censored at its last verified observation
        wr(p, raw.decode())
        st = worlds.read_state(root, wid)
        worlds.write_state(root, wid, dict(st, status="failed"))
        rm = os.path.join(root, "availability.jsonl")
        os.remove(rm)                                                       # (no zero evidenced any more)
        o = worlds.ecology(root, reg, [3000])["slots"][wid]["attempts"][0]
        self.assertEqual((o["observation"], o["censor"], o["frontier"]), ("technical", {"kind": "technical", "frame": 2000}, 2000))

    def test_done_world_alive_through_the_end_and_read_only(self):
        root, reg, ar, wid, msgs = self.world(ckpts=(1000, 2000, 3000))
        self.assertEqual(worlds.read_state(root, wid)["status"], "done", msgs)
        before = tree_state(root)
        doc = worlds.ecology(root, reg)
        self.assertEqual(doc["horizons"], [3000])                          # (the registered end within the schedule)
        o = doc["slots"][wid]["attempts"][0]
        self.assertEqual((o["observation"], o["censor"]), ("administrative", {"kind": "administrative", "frame": 3000}))
        row = doc["summary"]["B"]["first_attempt"]["survival"]["3000"]
        self.assertEqual((row["estimate"], row["complete"]), (1.0, True))
        self.assertAlmostEqual(row["ci95"][0], 0.025, places=6)
        out = os.path.join(self.tmp, "eco.json")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(worlds.main(["ecology", "--root", root, "--out", out, "--horizons", "1000,3000"]), 0)
            self.assertEqual(worlds.main(["monitor", "--root", root, "--out", out + ".m", "--window", "500",
                                          "--step", "100"]), 0)
            self.assertEqual(worlds.main(["monitor", "--root", root, "--out", out + ".x", "--window", "550"]), 2)
        self.assertEqual(rqlib.read_json(out)["horizons"], [1000, 3000])
        self.assertEqual(tree_state(root), before)                         # (nothing under the study root changed)

    def test_q200_counts_only_coexisting_c_histories(self):
        root, reg, ar = make_root(self.tmp, "C", dict(SCHED, total_steps=3000))
        doc = worlds.ecology(root, reg)
        self.assertEqual((doc["Q200"]["count"], doc["Q200"]["h_pqft_available"]), (0, False))
        self.assertEqual(doc["summary"]["C"]["first_attempt"]["survival"]["3000"]["counts"]["not_yet_observed"], 1)

    def test_clopper_pearson(self):
        cp = worlds.clopper_pearson
        self.assertAlmostEqual(cp(0, 10)[1], 1 - 0.025 ** 0.1, places=9)
        self.assertAlmostEqual(cp(10, 10)[0], 0.025 ** 0.1, places=9)
        lo, hi = cp(5, 10)
        self.assertAlmostEqual(lo, 0.187086, places=5)
        self.assertAlmostEqual(hi, 0.812914, places=5)
        self.assertEqual(cp(0, 10)[0], 0.0)

    def test_monitor_windows_breeders_and_energy(self):
        samples = [(f, {"predator_pop": 20, "predator_avg_energy": 150.0}) for f in range(100, 3001, 100)]
        ev = [(1200, "B", 10, False, True), (2300, "S", 1, True, True), (2350, "S", 2, False, True)]
        rows = worlds.monitor_windows(samples, ev, 500, 100, 100, 2000, lineage_through=3000)
        self.assertEqual([r["to"] for r in rows], list(range(2500, 3001, 100)))
        r = rows[0]                                                        # (2000, 2500]
        self.assertAlmostEqual(r["predator_seconds"], 20 * 500 * 0.016)
        self.assertEqual((r["starvation"], r["breeder_starvation"], r["nonbreeder_starvation"]), (2, 1, 1))
        self.assertAlmostEqual(r["breeder_starvation_rate"], 1 / 160 * 1000)
        self.assertAlmostEqual(r["mean_energy"], 150.0)
        self.assertEqual([x["deterioration"] for x in rows], [True, True, True, False, False, False])
        (ep,) = worlds._episodes(rows, 100)
        self.assertEqual((ep["first_to"], ep["last_to"], ep["windows"]), (2500, 2700, 3))
        self.assertAlmostEqual(ep["max_rate"], 6.25)
        self.assertAlmostEqual(ep["min_energy"], 150.0)
        hi = [(f, {"predator_pop": 20, "predator_avg_energy": 200.0}) for f in range(100, 3001, 100)]
        self.assertFalse(any(x["deterioration"] for x in worlds.monitor_windows(hi, ev, 500, 100, 100, 2000, 3000)))
        # a starved predator without known ancestry: the breeder indicator unavailable for its windows
        bad = worlds.monitor_windows(samples, ev + [(2600, "S", 99, False, False)], 500, 100, 100, 2000, 3000)
        self.assertEqual([x["breeder_indicator"][:11] for x in bad if x["to"] in (2600, 3000)], ["unavailable"] * 2)
        self.assertEqual(bad[1]["deterioration"], False)
        # past the lineage log's accepted frame, and B (no lineage log): unavailable, never a zero
        late = worlds.monitor_windows(samples, ev, 500, 100, 100, 2000, lineage_through=2600)
        self.assertEqual((late[1]["breeder_indicator"], late[2]["breeder_starvation_rate"]),
                         ("available", None))
        self.assertIsNone(worlds.monitor_windows(samples, None, 500, 100, 100, 2000)[0]["breeder_starvation_rate"])

    def test_monitor_acute_flag_in_b(self):
        root, reg, ar, wid, msgs = self.world(pred=lambda f: 12 if f >= 2100 else 20, burn_in=2000, ckpts=(1000, 2000, 3000))
        m = worlds.monitor(root, reg, 500, 100)
        v = m["worlds"][wid]
        self.assertEqual(v["acute"], {"first_frame": 2100, "samples": 10, "min_predator_pop": 12})
        self.assertEqual((v["breeder_indicator"], v["deterioration"]), ("unavailable: no individual lineage log (B)", []))
        self.assertEqual(v["latest_window"]["to"], 3000)
        self.assertEqual([s_["to"] for s_ in v["summaries"]], [3000])
        rm_tree(self.tmp)
        self.tmp = tempfile.mkdtemp()
        root, reg, ar, wid, msgs = self.world(tr="A", pred=lambda f: 8, burn_in=2000, ckpts=(1000, 2000, 3000))
        self.assertFalse(worlds.monitor(root, reg, 500, 100)["worlds"][wid]["monitored"])   # (A: not 12 <= 15)

    def test_monitor_c_breeders_from_the_accepted_lineage_log(self):
        """A C world accepted through its lineage log: founder 1 buds (a proven breeder) and starves at 1500,
        founder 2 starves at 1600 without budding; the breeder's death flags its windows (E 150 < 180)."""
        root, reg, ar = make_root(self.tmp, "C", dict(SCHED, total_steps=3000))
        w = reg["worlds"][0]
        wid = w["id"]
        d = worlds.wdir(root, wid)
        os.makedirs(os.path.join(d, "seg000"))
        os.makedirs(os.path.join(d, "ckpt"))
        cfg = cfg_for(w["flags"])
        f1p = os.path.join(self.tmp, "F1.json")
        wr(f1p, ckpt.dumps(mk_cp(frame=1, n_pred=6, cfg_extra=cfg)))
        worlds.archive_one(root, wid, ar, 1, f1p, lambda m: None, extra={"binary_sha256": EXE_SHA})
        npred = lambda f: 6 if f < 500 else 7 if f < 1500 else 6 if f < 1600 else 5  # noqa: E731
        fr = range(100, 3001, 100)
        s0 = os.path.join(d, "seg000")
        wr(os.path.join(s0, "run.csv"), "step,population,predator_pop,predator_avg_energy\n"
           + "".join(f"{f},50,{npred(f)},150.0\n" for f in fr))
        wr(os.path.join(s0, "run.wiring.csv"), "step,PREY_FWD\n" + "".join(f"{f},0.5\n" for f in fr))
        wr(os.path.join(s0, "run.predators.csv"), "step,predator_pop\n" + "".join(f"{f},{npred(f)}\n" for f in fr))
        wr(os.path.join(s0, "run.pwiring.csv"), "step,PREY\n" + "".join(f"{f},0.5\n" for f in fr))
        wr(os.path.join(s0, "run.predlog.csv"), "frame,event,id,parent,lineage\n"
           + "".join(f"0,F,{i},0,{i}\n" for i in range(1, 7)) + "500,B,7,1,1\n1500,S,1,0,1\n1600,S,2,0,2\n")
        for f, n, births, starv in ((1000, 7, 1, 0), (2000, 5, 1, 2)):
            cp = mk_cp(frame=f, n_pred=n, cfg_extra=cfg)
            cp["counters"].update(totalPredatorBirths=births, totalPredatorDeathsStarvation=starv)
            wr(os.path.join(d, "ckpt", f"end.{f}.json"), ckpt.dumps(cp))
        worlds.write_state(root, wid, {"schema": worlds.STATE_SCHEMA, "id": wid, "status": "interrupted", "failures": 0,
                                       "segments": [{"name": "seg000", "start_frame": 0, "resumed_from": None,
                                                     "resumed_accept": None, "args": []}]})
        s, msgs = supervisor(root, reg, ar)
        s.startup()
        self.assertEqual(max(r["frame"] for r in worlds.accept_records(root, wid)), 2000, msgs)
        v = worlds.monitor(root, reg, 500, 100)["worlds"][wid]
        self.assertEqual((v["breeder_indicator"], v["lineage_through"]), ("available", 2000))
        self.assertEqual(v["acute"], {"first_frame": 100, "samples": 20, "min_predator_pop": 5})   # (5-7 <= 15)
        self.assertEqual([(e["first_to"], e["last_to"], e["windows"]) for e in v["deterioration"]], [(1500, 1900, 5)])
        self.assertEqual(v["evidence"]["segments"][0]["predlog_sha256"],
                         rqlib.sha256_file(os.path.join(s0, "run.predlog.csv")))
        s2k = next(x for x in v["summaries"] if x["to"] == 2000)               # (1000, 2000]: both deaths
        self.assertEqual((s2k["starvation"], s2k["breeder_starvation"], s2k["nonbreeder_starvation"]), (2, 1, 1))
        self.assertEqual(s2k["births_minus_deaths"], -2)

    def test_layout_64_note_and_older_bytes(self):
        arena = os.path.join(self.tmp, "arena.json")
        wr(arena, json.dumps(ARENA))
        r64 = worlds.register(arena, "ns-d7", blocks=8, per_block=worlds.LAYOUTS["64"], schedule=SCHED, layout="64")
        self.assertIn("D7 rule 34", r64["allocation_note"])
        r48 = worlds.register(arena, "ns-d7", blocks=8, schedule=SCHED)
        self.assertIn("the 56 layout", r48["allocation_note"])               # (older registries keep their bytes)
        self.assertEqual(sum(len(x["seeds"]) for x in r64["reserved"]), 576)


if __name__ == "__main__":
    unittest.main()

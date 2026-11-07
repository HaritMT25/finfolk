#!/usr/bin/env python3
"""test_worlds.py: unit tests of worlds.py that need no engine (the end-to-end ones are
tests/redqueen_worlds.sh).

    python3 -I tools/redqueen/test_worlds.py [-v]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest

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


def make_root(tmp, treatment="A", sched=None):
    arena = os.path.join(tmp, "arena.json")
    wr(arena, json.dumps(ARENA))
    reg = worlds.register(arena, "ns-unit", blocks=1, per_block={t: int(t == treatment) for t in "CAB"},
                          schedule=sched or SCHED)
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

    def test_complete_invalid_checkpoints_fail_closed(self):
        """N5: only a demonstrably interrupted write is torn (quarantined); a complete file that is
        not a valid checkpoint, or holds another frame, is kept and fails the world."""
        self.assertTrue(worlds.incomplete_write(b""))
        self.assertTrue(worlds.incomplete_write(b'{"a": [1, 2'))
        self.assertTrue(worlds.incomplete_write(b'{"a": "abc'))
        self.assertTrue(worlds.incomplete_write('{"a": "é'.encode()[:-1]))
        self.assertFalse(worlds.incomplete_write(b'{"a": 1 xx}'))
        self.assertFalse(worlds.incomplete_write(b'{"a": 1}'))
        flags = None
        for name, data in (("wrong frame", "frame"), ("invalid", "invalid"), ("garbage", "garbage")):
            sub = tempfile.mkdtemp(dir=self.tmp)
            self.tmp, keep = sub, self.tmp
            try:
                root, reg, ar, wid = self.world(total=4000, ckpts=(1000,))
            finally:
                self.tmp = keep
            flags = reg["worlds"][0]["flags"]
            p = os.path.join(worlds.wdir(root, wid), "ckpt", "end.2000.json")
            if data == "frame":
                wr(p, ckpt.dumps(mk_cp(frame=1500, cfg_extra=cfg_for(flags))))
            elif data == "invalid":
                cp = mk_cp(frame=2000, cfg_extra=cfg_for(flags))
                cp["predators"]["id"][1] = cp["predators"]["id"][0]           # duplicate predator ids
                wr(p, ckpt.dumps(cp))
            else:
                wr(p, '{"format": 1 xx}')
            s, msgs = supervisor(root, reg, ar)
            s.startup()
            st = worlds.read_state(root, wid)
            self.assertEqual(st["status"], "failed", (name, msgs))
            self.assertTrue(os.path.isfile(p), name)                 # the evidence kept
            self.assertFalse(os.path.exists(os.path.join(worlds.wdir(root, wid), "quarantine.jsonl")), name)

    def test_non_serial_checkpoint_refused(self):
        """P2 (6): a checkpoint that declares a non-exact resume is never archived or accepted."""
        root, reg, ar, wid = self.world(total=4000, ckpts=())
        cp = mk_cp(frame=1000, cfg_extra=cfg_for(reg["worlds"][0]["flags"]))
        cp["determinism"] = "openmp-build (resume is NOT bit-exact)"
        p = os.path.join(worlds.wdir(root, wid), "ckpt", "end.1000.json")
        wr(p, ckpt.dumps(cp))
        with self.assertRaisesRegex(worlds.WorldsError, "serial build"):
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


if __name__ == "__main__":
    unittest.main()

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
        self.assertEqual(rep_["per_treatment"]["A"], {"worlds": 1, "restarts": 1, "attempts": 2, "early_failure_rate": 0.5})
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

    def test_burn_in_off_for_old_registries(self):
        """A registry without seed reservations (scheme before slot/1) keeps the old behaviour."""
        root, reg, ar, wid = self.world(zero_at=2500, burn_in=3000)
        reg2 = {k: v for k, v in reg.items() if k not in ("seed_scheme", "reserved")}
        s, msgs = supervisor(root, reg2, ar)
        self.assertEqual(s.burn_in, 0)


if __name__ == "__main__":
    unittest.main()

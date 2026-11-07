#!/usr/bin/env python3
"""test_forks.py: unit tests of forks.py and of worlds.py's branch generalization that need no engine
(the end-to-end ones are tests/redqueen_forks.sh).

    python3 -I tools/redqueen/test_forks.py [-v]
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ckpt  # noqa: E402
import forks  # noqa: E402
import rqlib  # noqa: E402
import worlds  # noqa: E402
from test_redqueen import mk_cp  # noqa: E402
from test_worlds import ARENA, EXE_SHA, SCHED, cfg_for, make_root, rm_tree, supervisor, wr  # noqa: E402

M = 1_000_000


def splits_for(reg):
    """A graph-like split: C worlds 20 / 6 / 6, fork worlds 2 / 4 / 6."""
    cs = sorted(w["id"] for w in reg["worlds"] if w["treatment"] == "C")
    split = {w: "train" if i < 20 else "val" if i < 26 else "test" for i, w in enumerate(cs)}
    return {"split": split, "fork": cs[:2] + cs[20:24] + cs[26:32]}


class TestRegister(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        arena = os.path.join(self.tmp, "arena.json")
        wr(arena, json.dumps(ARENA))
        self.hreg = worlds.register(arena, "ns-forks")
        self.study = os.path.join(self.tmp, "study")
        worlds.write_registry(os.path.join(self.study, "config", "worlds.json"), rqlib.canonical(self.hreg))
        self.splits = os.path.join(self.tmp, "splits.json")
        wr(self.splits, json.dumps(splits_for(self.hreg)))

    def tearDown(self):
        worlds.release_archives()
        rm_tree(self.tmp)

    def test_register(self):
        reg = forks.register(self.study, self.splits, "ns-f")
        self.assertEqual(rqlib.canonical(reg), rqlib.canonical(forks.register(self.study, self.splits, "ns-f")))
        main = [b for b in reg["worlds"] if b["kind"] == "main"]
        pilot = [b for b in reg["worlds"] if b["kind"] == "pilot"]
        self.assertEqual((len(main), len(pilot)), (144, 6))           # 12 x 3 x 4, and 6 pilot seeds
        self.assertEqual(len({b["id"] for b in reg["worlds"]}), 150)
        self.assertEqual(len({b["origin"]["seed"] for b in reg["worlds"]}), 150)
        sp = splits_for(self.hreg)
        self.assertEqual({b["split"] for b in main}, {"training", "validation", "test"})
        self.assertEqual(sorted({b["root"] for b in main}), sorted(sp["fork"]))
        self.assertEqual(sorted({b["origin"]["frame"] for b in main}), [30 * M, 100 * M, 185 * M])
        self.assertTrue(all(b["total_steps"] == b["origin"]["frame"] + 10 * M for b in main))
        pw = reg["pilot"]["world"]                                     # an independent validation world
        self.assertEqual(sp["split"][pw], "val")
        self.assertNotIn(pw, sp["fork"])
        self.assertTrue(all(b["root"] == pw and b["origin"]["frame"] == 50 * M and b["hold_at"] == 54 * M
                            and b["total_steps"] == 60 * M and b["split"] == "diagnostic" for b in pilot))
        by = {w["id"]: w for w in self.hreg["worlds"]}
        b = main[0]
        self.assertEqual((b["flags"], b["predator_log"], b["treatment"]), (by[b["root"]]["flags"], True, "C"))
        self.assertEqual(b["origin"]["seed"], rqlib.derive_seed("ns-f", "fork", by[b["root"]]["uuid"],
                                                                b["origin"]["frame"], b["origin"]["k"]))
        self.assertEqual(reg["worlds_registry"]["sha256"], rqlib.sha256_file(os.path.join(self.study, "config",
                                                                                          "worlds.json")))
        self.assertEqual(len(reg["native_panel"]), 32)

    def test_refusals(self):
        with self.assertRaisesRegex(forks.ForkError, "multiples of the checkpoint"):
            forks.register(self.study, self.splits, "ns-f", origins=[30 * M + 5])
        sp = splits_for(self.hreg)
        a = next(w["id"] for w in self.hreg["worlds"] if w["treatment"] == "A")
        wr(self.splits, json.dumps(dict(sp, fork=sp["fork"][:-1] + [a])))
        with self.assertRaisesRegex(forks.ForkError, "not a C world"):
            forks.register(self.study, self.splits, "ns-f")
        real = rqlib.derive_seed
        try:
            forks.rqlib.derive_seed = lambda *parts: 42 if parts[1] == "fork" else real(*parts)
            wr(self.splits, json.dumps(sp))
            with self.assertRaisesRegex(forks.ForkError, "collide"):
                forks.register(self.study, self.splits, "ns-f")
        finally:
            forks.rqlib.derive_seed = real

    def test_profile_design(self):
        reg = forks.register(self.study, self.splits, "ns-f")
        worlds.write_registry(os.path.join(self.study, "config", "forks.json"), rqlib.canonical(reg))
        rqlib.write_json_durable(os.path.join(self.study, "study.json"), {"archive_root": os.path.join(self.tmp, "ar")})
        cs = sorted(w["id"] for w in self.hreg["worlds"] if w["treatment"] == "C")
        refs = {"prey": [{"world": cs[i], "frame": 20 * M} for i in range(8)],
                "predators": [{"world": cs[8 + i], "frame": 60 * M} for i in range(8)]}
        out = forks.profile_design(self.study, refs)
        self.assertEqual(out["counts"], {"fork_branch": 144 * 3 * 17, "fork_original": 12 * 3 * 2 * 17,
                                         "native_panel": 32 * 3 * 17, "pilot_branch": 6 * 2 * 17,
                                         "pilot_original": 2 * 17})
        self.assertEqual(out["deduplicated"], 0)
        keys = [(json.dumps(e["prey"], sort_keys=True), json.dumps(e["predators"], sort_keys=True)) for e in out["edges"]]
        self.assertEqual(len(keys), len(set(keys)))
        def states(fam):                                               # (a measured state: its control edge)
            return {(e["prey"]["world"], e["prey"]["time"]) for e in out["edges"]
                    if e["family"] == fam and e["predators"] is None}
        nat, orig = states("native_panel"), states("fork_original")
        self.assertFalse(nat & orig)                                   # the primary horizon measured once
        self.assertEqual({out["times"][t] for _, t in nat}, {40 * M, 110 * M, 195 * M})
        b = next(e for e in out["edges"] if e["family"] == "fork_branch")
        self.assertIn(b["role"], ("training", "validation", "test"))
        self.assertTrue(out["worlds"][b["prey"]["world"]]["pattern"].endswith("end.{frame}.json"))
        self.assertEqual(sum(1 for e in out["edges"] if e["predators"] is None), out["edges"].__len__() // 17)
        with self.assertRaisesRegex(forks.ForkError, "8 prey and 8 predator"):
            forks.profile_design(self.study, dict(refs, prey=refs["prey"][:7]))
        out10 = forks.profile_design(self.study, refs, with_pilot_10m=True)
        self.assertEqual(out10["counts"]["pilot_branch"], 6 * 3 * 17)


class TestBranches(unittest.TestCase):
    """worlds.py's Supervisor on a fork branch (treatment A: no lineage log): its root segment starts at
    the origin, reseeds once, its chain and stitch start there; a hold; the origin states."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        worlds.release_archives()
        rm_tree(self.tmp)

    def setup_branch(self, logs_to=3000, ckpts=(2000, 3000), hold=None):
        study, reg, ar = make_root(self.tmp, "A", dict(SCHED, total_steps=3000))
        w = reg["worlds"][0]
        flags = w["flags"]
        o = os.path.join(self.tmp, "o1000.json")
        cp = mk_cp(frame=1000, cfg_extra=cfg_for(flags))
        wr(o, ckpt.dumps(cp))
        b = {"id": f"{w['id']}.o1000.s0", "uuid": "u-branch", "kind": "main", "root": w["id"], "root_uuid": w["uuid"],
             "split": "test", "treatment": "A", "block": 1, "flags": flags, "predator_log": False, "config_args": None,
             "origin": {"frame": 1000, "label": "end.1000", "seed": 77, "k": 0}, "total_steps": 3000}
        if hold:
            b["hold_at"] = hold
        freg = {"schema": forks.SCHEMA, "schedule": dict(SCHED, total_steps=3000), "worlds": [b]}
        fr = forks.froot(study)
        os.makedirs(fr)
        far = worlds.bind_root(fr, rqlib.canonical_sha(freg), create=True)
        self.assertEqual(forks.origin_status(study, b)[0], "waiting")
        os.makedirs(worlds.wdir(study, w["id"]), exist_ok=True)
        worlds.archive_one(study, w["id"], ar, 1000, o, lambda m: None)        # the history archives its origin
        kind, rec = forks.origin_status(study, b)
        self.assertEqual(kind, "available")
        local, sha = forks.freeze_origin(fr, b, rec)
        self.assertEqual((os.stat(local).st_mode & 0o777, sha), (0o444, rec["sha256"]))
        self.assertEqual(forks.freeze_origin(fr, b, rec), (local, sha))         # once
        rt = dict(freg, worlds=[dict(b, origin=dict(b["origin"], local=local, sha256=sha))])
        d = worlds.wdir(fr, b["id"])
        os.makedirs(os.path.join(d, "seg000"))
        os.makedirs(os.path.join(d, "ckpt"))
        hdr = "step,population,predator_pop," + ",".join(c for c, _ in worlds.INTERVAL_FIX)
        wr(os.path.join(d, "seg000", "run.csv"), hdr + "\n" + "".join(
            f"{f},50,8," + ",".join(["100"] * len(worlds.INTERVAL_FIX)) + "\n" for f in range(1100, logs_to + 1, 100)))
        wr(os.path.join(d, "seg000", "run.wiring.csv"), "step,PREY_FWD\n" + "".join(
            f"{f},0.5\n" for f in range(100, logs_to - 1000 + 1, 100)))
        for f in ckpts:
            wr(os.path.join(d, "ckpt", f"end.{f}.json"), ckpt.dumps(mk_cp(frame=f, cfg_extra=cfg_for(flags))))
        worlds.write_state(fr, b["id"], {"schema": worlds.STATE_SCHEMA, "id": b["id"], "status": "interrupted",
                                         "failures": 0, "segments": [{"name": "seg000", "start_frame": 1000,
                                                                      "resumed_from": "origin.json",
                                                                      "resumed_accept": None, "args": []}]})
        return study, fr, far, rt, b, cp

    def test_branch_runs_from_its_origin(self):
        study, fr, far, rt, b, cp = self.setup_branch()
        s, msgs = supervisor(fr, rt, far)
        self.assertEqual((s.base(b["id"]), s.Tw(b["id"])), (1000, 3000))
        s.startup()                                    # no F1 needed: the chain starts at the origin
        st = worlds.read_state(fr, b["id"])
        self.assertEqual(st["status"], "done", msgs)
        self.assertEqual([r["frame"] for r in worlds.accept_records(fr, b["id"])], [2000, 3000])
        self.assertTrue(os.path.isfile(os.path.join(worlds.adir(far, b["id"]), "FINALIZED")))
        man = worlds.stitch(fr, b["id"], rt)
        self.assertEqual((man["endpoint"], man["complete"], man["files"]["run.csv"]["rows"]), (3000, True, 20))
        rows = rqlib.read_text(os.path.join(worlds.wdir(fr, b["id"]), "stitched", "run.csv")).splitlines()
        first = dict(zip(rows[0].split(","), rows[1].split(",")))
        self.assertEqual(first["step"], "1100")
        self.assertEqual(int(first["births_interval"]), 100 - cp["counters"]["totalBirths"])   # the origin's counters
        # a damaged log part sends the resume back to the origin (not to frame 0, not to F1)
        with open(os.path.join(worlds.wdir(fr, b["id"]), "seg000", "run.wiring.csv"), "r+b") as f:
            f.truncate(30)
        self.assertEqual(s.resume(b["id"], st)[:2], (1000, rt["worlds"][0]["origin"]["local"]))

    def test_root_segment_reseeds_once(self):
        study, fr, far, rt, b, cp = self.setup_branch()
        w = rt["worlds"][0]
        a = worlds.segment_args(w, rt["schedule"], "seg000", 1000, "origin.json", reseed=77)
        self.assertEqual(a[:4], ["--load-checkpoint", "origin.json", "--reseed-after-load", "77"])
        self.assertEqual(a[a.index("--headless") + 1], "2000")
        a = worlds.segment_args(w, rt["schedule"], "seg001", 2000, "ckpt/end.2000.json")
        self.assertNotIn("--reseed-after-load", a)
        # the supervisor spawns the root segment with the reseed, a technical resume without it
        worlds.write_state(fr, b["id"], {"schema": worlds.STATE_SCHEMA, "id": b["id"], "status": "pending",
                                         "failures": 0, "segments": []})
        s, _ = supervisor(fr, rt, far)
        s.spawn_segment(b["id"], 1000, rt["worlds"][0]["origin"]["local"], None)
        st = worlds.read_state(fr, b["id"])
        self.assertEqual(st["segments"][0]["args"][:4], ["--load-checkpoint", "origin.json", "--reseed-after-load", "77"])
        s.running[b["id"]][0].wait()
        rec = {"segment": "seg000", "frame": 2000, "sha256": "x"}
        s.spawn_segment(b["id"], 2000, os.path.join(worlds.wdir(fr, b["id"]), "ckpt", "end.2000.json"), rec)
        st = worlds.read_state(fr, b["id"])
        self.assertNotIn("--reseed-after-load", st["segments"][1]["args"])
        s.running[b["id"]][0].wait()

    def test_hold(self):
        study, fr, far, rt, b, cp = self.setup_branch(hold=2000)
        s, msgs = supervisor(fr, rt, far)
        s.hold = {b["id"]: 2000}
        s.startup()
        st = worlds.read_state(fr, b["id"])
        self.assertEqual(st["status"], "held", msgs)
        self.assertEqual([r["frame"] for r in worlds.accept_records(fr, b["id"])], [2000])
        self.assertFalse(os.path.exists(os.path.join(worlds.adir(far, b["id"]), "FINALIZED")))
        self.assertEqual(s.next_action(b["id"])[0], "held")
        s2, msgs = supervisor(fr, rt, far)                 # the hold lifted: a technical resume
        s2.startup()
        self.assertEqual(worlds.read_state(fr, b["id"])["status"], "done", msgs)
        self.assertTrue(any("hold is lifted" in m for m in msgs), msgs)

    def test_origin_unavailable_and_changed(self):
        study, fr, far, rt, b, cp = self.setup_branch()
        hw = b["root"]
        d = worlds.wdir(study, hw)
        os.makedirs(os.path.join(d, "seg000"), exist_ok=True)
        head = "step,population,predator_pop\n900,0,8\n"
        wr(os.path.join(d, "seg000", "run.csv"), head)
        worlds._append_durable(os.path.join(study, "availability.jsonl"), {
            "schema": worlds.AVAIL_SCHEMA, "world": hw, "guild": "prey", "first_zero_frame": 900,
            "segment": "seg000", "csv_bytes": len(head), "csv_sha256": rqlib.sha256_bytes(head.encode())})
        kind, why = forks.origin_status(study, b)
        self.assertEqual(kind, "unavailable")
        self.assertIn("reached 0 at frame 900", why)
        # an origin frozen once is never replaced: a different archived origin is refused
        rec = dict(worlds.archive_records(study, hw)["end.1000"], sha256="0" * 64)
        with self.assertRaisesRegex(forks.ForkError, "changed since it was frozen"):
            forks.freeze_origin(fr, b, rec)


if __name__ == "__main__":
    unittest.main()

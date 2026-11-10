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


def zero_rec(root, wid, guild, frame):
    """A supported availability record: the segment's main-CSV prefix through the zero row, bound by sha256."""
    d = os.path.join(worlds.wdir(root, wid), "seg000")
    os.makedirs(d, exist_ok=True)
    text = "step,population,predator_pop\n" + f"{frame},{0 if guild == 'prey' else 50},{0 if guild == 'predators' else 5}\n"
    wr(os.path.join(d, "run.csv"), text)
    worlds._append_durable(os.path.join(root, "availability.jsonl"), {
        "schema": worlds.AVAIL_SCHEMA, "world": wid, "guild": guild, "first_zero_frame": frame, "segment": "seg000",
        "csv_bytes": len(text), "csv_sha256": rqlib.sha256_bytes(text.encode())})


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

    def test_reserved_history_seeds(self):
        """#70 review 7: a fork seed equal to ANY reserved history seed (a restart seed, an unused slot's) is
        refused."""
        target = next(x["seeds"][3] for x in self.hreg["reserved"] if x["treatment"] == "B" and x["k"] == 1)
        orig = rqlib.derive_seed
        rqlib.derive_seed = lambda ns, kind, *a: target if kind == "fork" else orig(ns, kind, *a)
        try:
            with self.assertRaisesRegex(forks.ForkError, "history seed slot"):
                forks.register(self.study, self.splits, "ns-f")
        finally:
            rqlib.derive_seed = orig

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
        with self.assertRaisesRegex(forks.ForkError, "8 DISTINCT prey"):
            forks.profile_design(self.study, dict(refs, prey=refs["prey"][:7]))
        with self.assertRaisesRegex(forks.ForkError, "8 DISTINCT predators"):       # (P3) repeated entries
            forks.profile_design(self.study, dict(refs, predators=[refs["predators"][0]] * 8))
        out10 = forks.profile_design(self.study, refs, with_pilot_10m=True)
        self.assertEqual(out10["counts"]["pilot_branch"], 6 * 3 * 17)
        self.assertEqual((out["omitted"], out["omitted_counts"]), ([], {}))

    def test_profile_omissions_and_outcomes(self):
        """PR-D (Annex H D6 rule 27, §§10.1-10.4): states that will never exist are omitted EXPLICITLY, with
        their cause, never emitted as paths: a fork root's prey zero at 50M (its 100M and 185M origins are then
        unavailable, its later native-panel and original targets absent), a branch's own predator zero at 32M,
        an invalidated branch; the branches' outcomes are exported independently of any profile."""
        reg = forks.register(self.study, self.splits, "ns-f")
        worlds.write_registry(os.path.join(self.study, "config", "forks.json"), rqlib.canonical(reg))
        rqlib.write_json_durable(os.path.join(self.study, "study.json"), {"archive_root": os.path.join(self.tmp, "ar")})
        cs = sorted(w["id"] for w in self.hreg["worlds"] if w["treatment"] == "C")
        refs = {"prey": [{"world": cs[i], "frame": 20 * M} for i in range(8)],
                "predators": [{"world": cs[8 + i], "frame": 60 * M} for i in range(8)]}
        full = forks.profile_design(self.study, refs)
        R = sorted(reg["fork_worlds"])[0]
        other = next(b for b in reg["worlds"] if b["kind"] == "main" and b["root"] != R and b["origin"]["frame"] == 30 * M)
        inval = next(b for b in reg["worlds"] if b["kind"] == "main" and b["root"] != R and b["id"] != other["id"])
        fr = forks.froot(self.study)
        zero_rec(self.study, R, "prey", 50 * M)
        zero_rec(fr, other["id"], "predators", 32 * M)
        worlds.write_state(fr, inval["id"], {"schema": worlds.STATE_SCHEMA, "id": inval["id"], "status": "invalidated",
                                             "end_reason": "its origin changed", "failures": 0, "segments": []})
        out = forks.profile_design(self.study, refs)
        om = {(o["family"], o["state"]["world"], o["state"]["frame"]): o["why"] for o in out["omitted"]}
        gone_r = [b["id"] for b in reg["worlds"] if b["root"] == R and b["origin"]["frame"] in (100 * M, 185 * M)]
        want = ({("fork_branch", b, f) for b in gone_r for f in
                 [next(x for x in reg["worlds"] if x["id"] == b)["origin"]["frame"] + h for h in (M, 4 * M, 10 * M)]}
                | {("fork_original", R, o + h) for o in (100 * M, 185 * M) for h in (M, 4 * M)}
                | {("native_panel", R, f) for f in (110 * M, 195 * M)}
                | {("fork_branch", other["id"], 30 * M + h) for h in (4 * M, 10 * M)}
                | {("fork_branch", inval["id"], inval["origin"]["frame"] + h) for h in (M, 4 * M, 10 * M)})
        self.assertEqual(set(om), want)
        self.assertTrue(om[("native_panel", R, 110 * M)].startswith("biological"))
        self.assertTrue(om[("fork_branch", gone_r[0], next(x for x in reg["worlds"] if x["id"] == gone_r[0])
                            ["origin"]["frame"] + M)].startswith("an unavailable origin"))
        self.assertIn("invalidated", om[("fork_branch", inval["id"], inval["origin"]["frame"] + M)])
        self.assertEqual(len(out["edges"]), len(full["edges"]) - 17 * len(want))       # (nothing else moves)
        self.assertNotIn(("fork_original", R, 31 * M), om)                 # (before the zero: kept)
        self.assertTrue(all(o["pairs"] == 17 for o in out["omitted"]))
        oc = forks.outcomes(self.study)
        b1 = oc["branches"]
        self.assertEqual(b1[other["id"]]["at"], {str(M): "not_yet_observed", str(4 * M): "predator_extinct",
                                                 str(10 * M): "predator_extinct"})
        self.assertEqual(set(b1[gone_r[0]]["at"].values()), {"unavailable_origin"})
        self.assertEqual(set(b1[inval["id"]]["at"].values()), {"technical"})
        self.assertEqual(b1[other["id"]]["first_zeros"], {"predators": 32 * M})
        self.assertEqual(sum(sum(c.values()) for k in oc["counts"].values() for s in k.values() for c in s.values()),
                         150 * 3)


    def test_profile_roles_and_references(self):
        """#65 review 2, 6, 7: an edge's role is its most held-out endpoint (a training branch against a
        test-world reference is test; a training world's snapshot holdout counts); a pair needed twice
        keeps the most held-out role; external (sentinel) references carry their own UUID and archive,
        identity conflicts are refused; frame 1 is F1 (F1.json)."""
        sp = splits_for(self.hreg)
        cs = sorted(w["id"] for w in self.hreg["worlds"] if w["treatment"] == "C")
        train_w = cs[5]                                     # a training world outside the fork set
        sp["holdout"] = {f"{train_w}:20": "test"}
        wr(self.splits, json.dumps(sp))
        reg = forks.register(self.study, self.splits, "ns-f")
        worlds.write_registry(os.path.join(self.study, "config", "forks.json"), rqlib.canonical(reg))
        rqlib.write_json_durable(os.path.join(self.study, "study.json"), {"archive_root": os.path.join(self.tmp, "ar")})
        test_w = next(w for w in cs if sp["split"][w] == "test")
        refs = {"prey": [{"world": cs[i], "frame": 60 * M} for i in range(6, 13)]
                + [{"world": "S1", "frame": 1, "uuid": "uuid-s1", "archive": os.path.join(self.tmp, "sentinels", "S1")}],
                "predators": [{"world": test_w, "frame": 60 * M}] + [{"world": cs[i], "frame": 70 * M} for i in range(6, 12)]
                + [{"world": train_w, "frame": 20 * M}]}
        out = forks.profile_design(self.study, refs)
        role = {(e["prey"]["world"], e["prey"]["time"], (e["predators"] or {}).get("world"),
                 (e["predators"] or {}).get("time")): e["role"] for e in out["edges"]}
        tb = next(b for b in reg["worlds"] if b["kind"] == "main" and b["split"] == "training")
        lab = f"f{tb['origin']['frame'] + 1 * M}"
        self.assertEqual(role[(tb["id"], lab, test_w, "f60000000")], "test")           # the test-world reference
        self.assertEqual(role[(tb["id"], lab, train_w, "f20000000")], "test")          # a snapshot holdout (test)
        self.assertEqual(role[(tb["id"], lab, cs[6], "f70000000")], "training")
        self.assertEqual(out["worlds"]["S1"]["uuid"], "uuid-s1")
        self.assertEqual(out["worlds"]["S1"]["paths"]["F1"], os.path.join(self.tmp, "sentinels", "S1", "F1.json"))
        self.assertEqual(out["times"]["F1"], 1)
        self.assertTrue(any(e["prey"] == {"world": "S1", "time": "F1"} for e in out["edges"]))
        self.assertEqual(forks.merge_role("training", "test"), "test")
        self.assertEqual(forks.merge_role("diagnostic", "training"), "training")
        self.assertEqual(forks.merge_role("validation", "diagnostic"), "validation")
        # a pilot measurement is diagnostic unless an endpoint outside the pilot is held out
        pb = next(b for b in reg["worlds"] if b["kind"] == "pilot")
        plab = f"f{pb['origin']['frame'] + 1 * M}"
        self.assertEqual(role[(pb["id"], plab, cs[6], "f70000000")], "diagnostic")
        self.assertEqual(role[(pb["id"], plab, test_w, "f60000000")], "test")
        arch = os.path.join(self.tmp, "sentinels", "S1")
        for guild, bad, msg in (
                ("predators", {"world": "S1", "frame": 5 * M, "uuid": "other", "archive": arch}, "another identity"),
                ("predators", {"world": "S9", "frame": 5 * M, "uuid": "uuid-s1", "archive": arch}, "names two worlds"),
                ("prey", dict(refs["prey"][0], frame=65 * M, uuid="not-the-registry's"), "conflict"),
                ("prey", {"world": "S2", "frame": 5 * M}, "not a main history")):
            lst = list(refs[guild])
            lst[1] = bad
            with self.assertRaisesRegex(forks.ForkError, msg):
                forks.profile_design(self.study, dict(refs, **{guild: lst}))

    def test_reserved_seeds(self):
        """#65 review 5: a fork seed equal to a history's founder seed or to a reserved seed is refused."""
        reg = forks.register(self.study, self.splits, "ns-f")
        seed = reg["worlds"][3]["origin"]["seed"]
        av = os.path.join(self.tmp, "reserved.json")
        wr(av, json.dumps({"seeds": [seed]}))
        with self.assertRaisesRegex(forks.ForkError, "reserved in"):
            forks.register(self.study, self.splits, "ns-f", avoid_paths=[av])
        founder = self.hreg["worlds"][0]["founder_seed"]
        real = rqlib.derive_seed
        try:
            forks.rqlib.derive_seed = lambda *parts: founder if parts[1] == "fork" else real(*parts)
            with self.assertRaisesRegex(forks.ForkError, "founder seed"):
                forks.register(self.study, self.splits, "ns-f")
        finally:
            forks.rqlib.derive_seed = real
        self.assertEqual(forks.register(self.study, self.splits, "ns-f")["avoid"], [])


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

    def test_frozen_origin_verified_at_every_use(self):
        """#65 review 1: a branch crashes before its first acceptance; a schema-valid edit of its frozen
        origin is then refused at the relaunch (the root replay never runs on it), by the fork refresh
        and by the Supervisor itself."""
        study, fr, far, rt, b, cp = self.setup_branch(ckpts=())
        st = worlds.read_state(fr, b["id"])
        worlds.write_state(fr, b["id"], dict(st, status="running"))      # (crashed before any acceptance)
        local = rt["worlds"][0]["origin"]["local"]
        doc = ckpt.load(local)
        doc["creatures"]["genes"][0] = int(doc["creatures"]["genes"][0]) + 1   # schema-valid, different
        os.chmod(local, 0o644)
        wr(local, ckpt.dumps(doc))
        os.chmod(local, 0o444)
        s, msgs = supervisor(fr, rt, far)
        s.startup()
        st = worlds.read_state(fr, b["id"])
        self.assertEqual(st["status"], "failed", msgs)
        self.assertIn("does not match its recorded digest", st["end_reason"])
        self.assertEqual(len(st["segments"]), 1)                          # no root replay was spawned
        freg = dict(rt, worlds=[dict(b)])
        worlds.write_state(fr, b["id"], dict(st, status="interrupted"))
        logs = []
        out = forks.refresh_origins(study, freg, logs.append)
        self.assertEqual(worlds.read_state(fr, b["id"])["status"], "failed")
        self.assertNotIn("local", out["worlds"][0]["origin"])
        ev = worlds.read_jsonl(os.path.join(fr, "origins.jsonl"))
        self.assertTrue(any(e["status"] == "origin_changed" for e in ev), ev)

    def test_eligibility_and_ledger(self):
        """#65 review 3, 4: admission and re-checks use the CURRENT evidence (a root zero recorded later at
        or before the origin invalidates an admitted branch, its artifacts kept); the origins ledger's torn
        tail is repaired before appending; a state written before a crash without its ledger event is
        reconciled once (idempotent)."""
        study, fr, far, rt, b, cp = self.setup_branch()
        freg = dict(rt, worlds=[dict(b)])
        lp = os.path.join(fr, "origins.jsonl")
        out = forks.refresh_origins(study, freg, lambda m: None)
        self.assertEqual(out["worlds"][0]["origin"]["sha256"], rt["worlds"][0]["origin"]["sha256"])
        wr(lp, rqlib.read_text(lp) + '{"branch": "torn')                    # a crash mid-append
        forks.refresh_origins(study, freg, lambda m: None)
        ev = worlds.read_jsonl(lp)                                          # every line parses
        self.assertEqual([e["status"] for e in ev], ["available"])
        hw = b["root"]
        d = worlds.wdir(study, hw)
        os.makedirs(os.path.join(d, "seg000"), exist_ok=True)
        head = "step,population,predator_pop\n900,0,8\n"
        wr(os.path.join(d, "seg000", "run.csv"), head)
        worlds._append_durable(os.path.join(study, "availability.jsonl"), {
            "schema": worlds.AVAIL_SCHEMA, "world": hw, "guild": "prey", "first_zero_frame": 900,
            "segment": "seg000", "csv_bytes": len(head), "csv_sha256": rqlib.sha256_bytes(head.encode())})
        logs = []
        forks.refresh_origins(study, freg, logs.append)
        st = worlds.read_state(fr, b["id"])
        self.assertEqual((st["status"], st["invalidated_from"]), ("invalidated", "interrupted"))
        self.assertTrue(os.path.isfile(rt["worlds"][0]["origin"]["local"]))   # artifacts kept
        self.assertEqual([e["status"] for e in worlds.read_jsonl(lp)], ["available", "invalidated"])
        # the crash between an "unavailable" state and its ledger event: reconciled exactly once
        b2 = dict(b, id=b["id"] + "x")
        worlds.write_state(fr, b2["id"], {"schema": worlds.STATE_SCHEMA, "id": b2["id"], "status": "unavailable",
                                          "end_reason": "its root ended", "failures": 0, "segments": []})
        f2 = dict(freg, worlds=[dict(b), b2])
        forks.refresh_origins(study, f2, lambda m: None)
        forks.refresh_origins(study, f2, lambda m: None)
        ev = [e for e in worlds.read_jsonl(lp) if e["branch"] == b2["id"]]
        self.assertEqual([e["status"] for e in ev], ["unavailable"])

    def test_roots_under_the_burn_in_rule(self):
        """#70 review 2 (P1): a root whose attempt can still be restarted is WAITING whatever its early
        zeros (never unavailable); a branch frozen from a discarded attempt is invalidated; the fork registry
        refuses a seed equal to any reserved history seed (restart seeds, unused slots)."""
        study, reg, ar = make_root(self.tmp, "A", dict(SCHED, total_steps=3000), burn_in=3000)
        w = reg["worlds"][0]
        b = {"id": f"{w['id']}.o1000.s0", "root": w["id"], "treatment": "A",
             "origin": {"frame": 1000, "label": "end.1000", "seed": 77, "k": 0}}
        d = worlds.wdir(study, w["id"])
        os.makedirs(os.path.join(d, "seg000"), exist_ok=True)
        head = "step,population,predator_pop\n900,0,8\n"
        wr(os.path.join(d, "seg000", "run.csv"), head)
        worlds._append_durable(os.path.join(study, "availability.jsonl"), {
            "schema": worlds.AVAIL_SCHEMA, "world": w["id"], "guild": "prey", "first_zero_frame": 900,
            "segment": "seg000", "csv_bytes": len(head), "csv_sha256": rqlib.sha256_bytes(head.encode())})
        kind, why = forks.origin_status(study, b)
        self.assertEqual(kind, "waiting", why)                   # (an early zero of a replaceable attempt)
        self.assertIn("burn-in", why)
        # a branch frozen from attempt 0, then the root restarted: invalid
        fr = forks.froot(study)
        os.makedirs(worlds.wdir(fr, b["id"]))
        rqlib.write_json_durable(os.path.join(worlds.wdir(fr, b["id"]), "origin.rec.json"),
                                 {"schema": forks.ORIGIN_SCHEMA, "sha256": "0" * 64, "prey": 8, "predators": 3,
                                  "root_attempt": 0})
        os.makedirs(os.path.join(study, "restarts"), exist_ok=True)
        os.rename(d, d + ".gone")
        os.makedirs(d)
        rqlib.write_json_durable(os.path.join(d, "attempt.json"), {"attempt": 1})
        self.assertIn("discarded attempt", forks.branch_invalid(study, b))

    def test_restart_during_the_copy(self):
        """#70 round 2, 1: the frozen origin is bound to the root attempt admitted; a restart between the
        admission and the copy is detected: nothing frozen, the branch waits."""
        study, reg, ar = make_root(self.tmp, "A", dict(SCHED, total_steps=3000))
        w = reg["worlds"][0]
        flags = w["flags"]
        o = os.path.join(self.tmp, "o1000.json")
        wr(o, ckpt.dumps(mk_cp(frame=1000, cfg_extra=cfg_for(flags))))
        os.makedirs(worlds.wdir(study, w["id"]), exist_ok=True)
        worlds.archive_one(study, w["id"], ar, 1000, o, lambda m: None)
        b = {"id": f"{w['id']}.o1000.s0", "uuid": "u-branch", "kind": "main", "root": w["id"], "root_uuid": w["uuid"],
             "split": "test", "treatment": "A", "block": 1, "flags": flags, "predator_log": False, "config_args": None,
             "origin": {"frame": 1000, "label": "end.1000", "seed": 77, "k": 0}, "total_steps": 3000}
        freg = {"schema": forks.SCHEMA, "schedule": dict(SCHED, total_steps=3000), "worlds": [b]}
        fr = forks.froot(study)
        os.makedirs(fr)
        worlds.bind_root(fr, rqlib.canonical_sha(freg), create=True)
        seq = iter([0, 1, 1, 1, 1, 1])
        orig = worlds.attempt_of
        worlds.attempt_of = lambda root, wid: next(seq) if wid == w["id"] else orig(root, wid)
        logs = []
        try:
            forks.refresh_origins(study, freg, logs.append)
        finally:
            worlds.attempt_of = orig
        self.assertTrue(any("restarted while the origin was copied" in m for m in logs), logs)
        d = worlds.wdir(fr, b["id"])
        self.assertFalse(os.path.exists(os.path.join(d, "origin.json")))
        self.assertFalse(os.path.exists(os.path.join(d, "origin.rec.json")))
        self.assertEqual(worlds.read_state(fr, b["id"])["status"], "waiting")
        forks.refresh_origins(study, freg, logs.append)                 # (no race: frozen, bound to attempt 0)
        self.assertEqual(rqlib.read_json(os.path.join(d, "origin.rec.json"))["root_attempt"], 0)

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

    # ---------------------------------------------------------------- #65 review 2, finding 3
    def root_zero(self, study, b, frame=900):
        """The branch's root records a supported prey zero at `frame` (the histories' ledger)."""
        d = worlds.wdir(study, b["root"])
        os.makedirs(os.path.join(d, "seg000"), exist_ok=True)
        head = f"step,population,predator_pop\n{frame},0,8\n"
        wr(os.path.join(d, "seg000", "run.csv"), head)
        worlds._append_durable(os.path.join(study, "availability.jsonl"), {
            "schema": worlds.AVAIL_SCHEMA, "world": b["root"], "guild": "prey", "first_zero_frame": frame,
            "segment": "seg000", "csv_bytes": len(head), "csv_sha256": rqlib.sha256_bytes(head.encode())})

    def records(self, seq, calls, side=None):
        """A stand-in for worlds.archive_records whose successive calls return seq's records (the last one
        repeated): a history re-archiving its origin label between two reads."""
        def f(root, wid, repair=False):
            calls.append(wid)
            if side:
                side()
            return {"end.1000": dict(seq[min(len(calls), len(seq)) - 1])}
        return f

    def test_admission_validates_the_record_it_freezes(self):
        """3(a): the archive record is fetched ONCE; that exact record's guild counts and bytes are checked
        and it is the one frozen; the availability ledger is read AFTER the record was obtained."""
        study, fr, far, rt, b, cp = self.setup_branch()
        good = worlds.archive_records(study, b["root"])["end.1000"]
        o2 = os.path.join(self.tmp, "o1000b.json")                       # other bytes, a verifying record
        wr(o2, ckpt.dumps(mk_cp(frame=1000, seed=5, cfg_extra=cfg_for(b["flags"]))))
        zero = dict(good, path=o2, sha256=rqlib.sha256_file(o2), prey=0)
        b2 = dict(b, id=b["id"] + "y")
        freg = dict(rt, worlds=[b2])
        orig = worlds.archive_records
        try:
            # checked good, then re-read as the zero-prey record: the checked record is the one admitted
            calls = []
            worlds.archive_records = self.records([good, zero], calls)
            kind, rec = forks.origin_status(study, b2)
            self.assertEqual((kind, rec["sha256"], rec["prey"], len(calls)), ("available", good["sha256"], 8, 1))
            calls = []
            worlds.archive_records = self.records([good, zero], calls)
            out = forks.refresh_origins(study, freg, lambda m: None)
            frec = rqlib.read_json(os.path.join(worlds.wdir(fr, b2["id"]), "origin.rec.json"))
            self.assertEqual((frec["sha256"], frec["prey"], frec["predators"]), (good["sha256"], 8, 3))
            self.assertEqual(out["worlds"][0]["origin"]["sha256"], good["sha256"])
            # the zero-prey record first: refused, nothing frozen, whatever a later read would say
            b3 = dict(b, id=b["id"] + "z")
            calls = []
            worlds.archive_records = self.records([zero, good], calls)
            out = forks.refresh_origins(study, dict(rt, worlds=[b3]), lambda m: None)
            self.assertEqual(worlds.read_state(fr, b3["id"])["status"], "unavailable")
            self.assertFalse(os.path.exists(os.path.join(worlds.wdir(fr, b3["id"]), "origin.json")))
            self.assertNotIn("local", out["worlds"][0]["origin"])
            # a root zero recorded while the record was being fetched is seen (the ledger is read after)
            b4 = dict(b, id=b["id"] + "w")
            calls = []
            worlds.archive_records = self.records([good], calls, side=lambda: self.root_zero(study, b) if len(calls) == 1 else None)
            kind, why = forks.origin_status(study, b4)
            self.assertEqual(kind, "unavailable")
            self.assertIn("reached 0 at frame 900", why)
        finally:
            worlds.archive_records = orig

    def test_admission_refused_on_guild_counts_alone(self):
        """3: a verifying record, no zero in the ledger, its root still running: refused solely because the
        record holds no prey (any treatment) or no predators (C and B; A has none)."""
        study, fr, far, rt, b, cp = self.setup_branch()
        good = worlds.archive_records(study, b["root"])["end.1000"]
        self.assertEqual(worlds.first_zeros(worlds.read_jsonl(os.path.join(study, "availability.jsonl")),
                                            b["root"], study), {})
        orig = worlds.archive_records
        try:
            for treat, prey, pred, want in (("A", 0, 3, "unavailable"), ("A", 8, 0, "available"),
                                            ("C", 8, 0, "unavailable"), ("B", 8, 0, "unavailable"),
                                            ("C", 0, 3, "unavailable"), ("C", 8, 3, "available")):
                worlds.archive_records = self.records([dict(good, prey=prey, predators=pred)], [])
                kind, info = forks.origin_status(study, dict(b, id=b["id"] + treat, treatment=treat))
                self.assertEqual(kind, want, (treat, prey, pred, info))
                if want == "unavailable":
                    self.assertIn(f"holds {prey} prey and {pred} predators", info)
            b2 = dict(b, id=b["id"] + "q")
            worlds.archive_records = self.records([dict(good, prey=0)], [])
            logs = []
            forks.refresh_origins(study, dict(rt, worlds=[b2]), logs.append)
        finally:
            worlds.archive_records = orig
        st = worlds.read_state(fr, b2["id"])
        self.assertEqual(st["status"], "unavailable")
        self.assertIn("holds 0 prey", st["end_reason"])
        self.assertFalse(os.path.exists(os.path.join(worlds.wdir(fr, b2["id"]), "origin.json")))
        ev = [e for e in worlds.read_jsonl(os.path.join(fr, "origins.jsonl")) if e["branch"] == b2["id"]]
        self.assertEqual([e["status"] for e in ev], ["unavailable"])

    def test_failed_branch_rechecked_before_retry(self):
        """3(b): a FAILED branch whose root later records a zero at or before its origin is invalidated by
        the fork refresh, and the Supervisor re-checks every branch before a --retry-failed retry and
        before every resume (it never spawns a segment for it)."""
        # the refresh
        study, fr, far, rt, b, cp = self.setup_branch(ckpts=())
        st = worlds.read_state(fr, b["id"])
        worlds.write_state(fr, b["id"], dict(st, status="failed", end_reason="exit 1, no progress"))
        self.root_zero(study, b)
        forks.refresh_origins(study, dict(rt, worlds=[dict(b)]), lambda m: None)
        st = worlds.read_state(fr, b["id"])
        self.assertEqual((st["status"], st["invalidated_from"]), ("invalidated", "failed"))
        ev = worlds.read_jsonl(os.path.join(fr, "origins.jsonl"))
        self.assertEqual([e["status"] for e in ev], ["available", "invalidated"])
        # the Supervisor, without a refresh: a --retry-failed retry
        worlds.write_state(fr, b["id"], dict(st, status="failed"))
        s, msgs = supervisor(fr, rt, far, retry_failed=True)
        s.ineligible = lambda wid: forks.branch_invalid(study, b)
        s.startup()
        st = worlds.read_state(fr, b["id"])
        self.assertEqual((st["status"], st["invalidated_from"], len(st["segments"])), ("invalidated", "failed", 1), msgs)
        self.assertFalse(any("retrying a failed world" in m for m in msgs), msgs)
        # ... and a resume of an interrupted branch, in the loop (no segment spawned)
        worlds.write_state(fr, b["id"], dict(st, status="interrupted"))
        s, msgs = supervisor(fr, rt, far)
        s.ineligible = lambda wid: forks.branch_invalid(study, b)
        self.assertEqual(s.next_action(b["id"])[0], "invalidated")
        self.assertEqual(s.run(), 0, msgs)
        st = worlds.read_state(fr, b["id"])
        self.assertEqual((st["status"], len(st["segments"])), ("invalidated", 1), msgs)
        # the same branch with an eligible origin is retried as before
        worlds.write_state(fr, b["id"], dict(st, status="failed"))
        s, msgs = supervisor(fr, rt, far, retry_failed=True)
        s.ineligible = lambda wid: None
        s.startup()
        self.assertTrue(any("retrying a failed world" in m for m in msgs), msgs)


if __name__ == "__main__":
    unittest.main()

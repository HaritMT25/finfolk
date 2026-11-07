#!/usr/bin/env python3
"""test_redqueen.py: unit tests of tools/redqueen that need no engine (stdlib unittest).

    python3 -I tools/redqueen/test_redqueen.py [-v]

The end-to-end tests against the real engine are tests/redqueen_tooling.sh (ctest).
"""
from __future__ import annotations

import copy
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ckpt  # noqa: E402
import common  # noqa: E402
import plan  # noqa: E402
import rqlib  # noqa: E402
import run  # noqa: E402
import store  # noqa: E402
import cell  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))
NPC, BLEN = 3, 2


def wr(path, data, mode=None):
    """Write (or with mode "ab" append) str / bytes to path, closing the file."""
    if isinstance(data, str):
        data = data.encode()
    with open(path, mode or "wb") as f:
        f.write(data)


def mk_cp(n_prey=8, n_pred=3, version=2, frame=100, seed=1, cfg_extra=None):
    """A small, self-consistent synthetic checkpoint (not engine output: the layout only)."""
    rng = rqlib.SplitMix64(seed)
    u = lambda: rng.below(10 ** 6) / 10 ** 6  # noqa: E731
    cfg = {"genomeMinLength": 1, "genomeMaxLength": 12, "minPopulation": 0, "maxPopulation": 50,
           "fastTanh": False, "bodyModel": False, "predatorCount": n_pred, "predatorSpeed": 110}
    if version == 2:
        cfg.update(predatorBrain=True, predatorMutation=1, predatorTurnRate=4, predatorMinSpeed=0,
                   predatorPrimer=False, predatorFrozen=False)
    cfg.update(cfg_extra or {})
    glen = [1 + rng.below(5) for _ in range(n_prey)]
    cs = {"count": n_prey, "neuronsPerCreature": NPC, "bodyLen": BLEN,
          "id": [10 + 3 * i for i in range(n_prey)], "lineageId": [10 + 3 * (i // 2) for i in range(n_prey)],
          "alive": [1] * n_prey, "generation": [i % 4 for i in range(n_prey)]}
    for k in ("posX", "posY", "velX", "velY", "lastMoveDirX", "lastMoveDirY", "oscPhase"):
        cs[k] = [u() for _ in range(n_prey)]
    for k, v in (("speed", 70.5), ("age", 12.25), ("foodReserves", 44.0), ("reproTimer", 1.5),
                 ("interactTimer", 0.25), ("responsiveness", 0.75), ("oscPeriod", 30.0)):
        cs[k] = [v + i for i in range(n_prey)]
    cs["bodySize"] = [1.0] * n_prey
    cs["bodyElong"] = [1.0] * n_prey
    cs["neuronOutputs"] = [u() for _ in range(n_prey * NPC)]
    cs["body"] = [u() for _ in range(n_prey * BLEN * 2)]
    cs["genomeLengths"] = glen
    cs["genes"] = [rng.below(1 << 16) if j % 2 == 0 else rng.below(8000) - 4000 for j in range(2 * sum(glen))]
    pglen = [2] * n_pred
    jp = {"count": n_pred}
    for k in ("posX", "posY", "velX", "velY", "digestTimer", "energy", "age"):
        jp[k] = [u() for _ in range(n_pred)]
    jp.update(alive=[1] * n_pred, speedFactor=[1.0] * n_pred, buddingFactor=[1.0] * n_pred, generation=[0] * n_pred)
    if version == 2:
        jp.update(sensorSet=1, neuronsPerPredator=NPC, id=[5 + i for i in range(n_pred)],
                  lineageId=[5] * n_pred, parentId=[0] * n_pred, speed=[100.0] * n_pred, captures=[1] * n_pred,
                  neuronOutputs=[0.5] * (n_pred * NPC), genomeLengths=pglen, genes=[7, 100] * sum(pglen))
    cp = {"format": ckpt.FORMAT_ID, "formatVersion": version, "engineVersion": "0.27.0",
          "determinism": "serial build (resume is bit-exact)",
          "world": {"width": 400, "height": 300, "frame": frame, "nextId": 10 + 3 * n_prey},
          "counters": {"totalBirths": 9, "totalDeaths": 4, "totalDeathsPredation": 1, "totalDeathsStarvation": 2,
                       "totalDeathsAge": 1, "totalPredatorBirths": 0, "totalPredatorReseeds": 0,
                       "clusterStride": 2, "reproStride": 3},
          "rngState": "123 456", "config": cfg, "currentVortices": [], "foodPatchCenters": [],
          "signals": {"cols": 4, "rows": 3, "cellSize": 100, "rle": [0, 5, 7, 1, 0, 6]},
          "food": {"count": 2, "x": [1.5, 2.5], "y": [3.5, 4.5], "alive": [1, 0]},
          "predators": jp, "creatures": cs}
    if version == 2:
        cp["world"]["nextPredatorId"] = 5 + n_pred + 2
        cp["predatorRngState"] = "9 9"
    return cp


class TestRng(unittest.TestCase):
    def test_splitmix_reference_vector(self):
        # the reference splitmix64.c (Vigna) from state 1234567
        r = rqlib.SplitMix64(1234567)
        self.assertEqual([r.next64() for _ in range(3)],
                         [6457827717110365317, 3203168211198807973, 9817491932198370423])

    def test_below_sample_shuffle(self):
        r = rqlib.SplitMix64(5)
        xs = [r.below(7) for _ in range(2000)]
        self.assertEqual(set(xs), set(range(7)))
        s = rqlib.SplitMix64(9).sample(50, 20)
        self.assertEqual(len(set(s)), 20)
        self.assertEqual(s, rqlib.SplitMix64(9).sample(50, 20))
        self.assertEqual(sorted(rqlib.SplitMix64(3).shuffle(list(range(30)))), list(range(30)))
        with self.assertRaises(ValueError):
            rqlib.SplitMix64(1).sample(3, 4)

    def test_derive_seed(self):
        self.assertEqual(rqlib.derive_seed("a", 1), rqlib.derive_seed("a", 1))
        self.assertNotEqual(rqlib.derive_seed("a", 1), rqlib.derive_seed("a", 2))
        self.assertLess(rqlib.derive_seed("x"), 2 ** 32)


class TestTemplateValues(unittest.TestCase):
    def test_agent_core_defaults(self):
        """common.AGENT_DEFAULTS are agent_core.hpp's member defaults, and 0.5 genome.hpp's neuron output."""
        src = rqlib.read_text(os.path.join(REPO, "src", "core", "agent_core.hpp"))
        for k, v in common.AGENT_DEFAULTS.items():
            m = re.search(r"float\s+" + k + r"\s*=\s*([0-9.]+)f\s*;", src)
            self.assertIsNotNone(m, k)
            self.assertEqual(float(m.group(1)), v, k)
        g = rqlib.read_text(os.path.join(REPO, "src", "core", "genome.hpp"))
        self.assertRegex(g, r"float output = 0\.5f;")
        self.assertEqual(common.NEURON_BIRTH_OUTPUT, 0.5)


class TestCkpt(unittest.TestCase):
    def test_valid(self):
        for v in (1, 2):
            cp = mk_cp(version=v)
            ckpt.validate(cp)
            self.assertEqual(json.loads(ckpt.dumps(cp)), cp)

    def bad(self, mut, msg):
        cp = mk_cp()
        mut(cp)
        with self.assertRaisesRegex(ckpt.CheckpointError, msg):
            ckpt.validate(cp)

    def test_refusals(self):
        self.bad(lambda c: c.update(formatVersion=3), "format version")
        self.bad(lambda c: c["config"].pop("predatorBrain"), "predatorBrain")
        self.bad(lambda c: c.pop("predatorRngState"), "predatorRngState")
        self.bad(lambda c: c["world"].update(nextPredatorId=0), "nextPredatorId")
        self.bad(lambda c: c["predators"]["id"].__setitem__(0, 99), "nextPredatorId")
        self.bad(lambda c: c["predators"]["lineageId"].__setitem__(1, 99), "lineageId")
        self.bad(lambda c: c["predators"]["id"].__setitem__(1, c["predators"]["id"][0]), "unique")
        self.bad(lambda c: c["predators"]["genes"].pop(), "genes")
        self.bad(lambda c: c["predators"].update(sensorSet=2), "sensor set")
        self.bad(lambda c: c["predators"]["speedFactor"].__setitem__(0, 3.0), "trait")
        self.bad(lambda c: c["creatures"]["genes"].pop(), "genes")
        self.bad(lambda c: c["world"].update(nextId=1), "nextId")
        self.bad(lambda c: c["creatures"]["posX"].__setitem__(0, float("nan")), "non-finite")
        self.bad(lambda c: c["creatures"]["bodySize"].__setitem__(0, 0.1), "bodySize")
        self.bad(lambda c: c["creatures"]["id"].__setitem__(1, c["creatures"]["id"][0]), "duplicate")
        self.bad(lambda c: c["creatures"]["neuronOutputs"].pop(), "neuron")
        v1 = mk_cp(version=1)
        v1["config"]["predatorBrain"] = True
        with self.assertRaises(ckpt.CheckpointError):
            ckpt.validate(v1)

    def test_rows_and_meta(self):
        cp = mk_cp(n_prey=5, n_pred=2)
        cp["creatures"]["alive"][2] = 0
        rows = ckpt.prey(cp)
        self.assertEqual(len(rows), 5)
        self.assertEqual(len(ckpt.prey(cp, alive_only=True)), 4)
        cp2 = copy.deepcopy(cp)
        ckpt.set_prey(cp2, rows)
        self.assertEqual(cp2["creatures"], cp["creatures"])
        pr = ckpt.predators(cp)
        self.assertEqual([p["id"] for p in pr], [5, 6])
        self.assertEqual(pr[0]["sourceId"], 0)
        self.assertEqual(len(pr[1]["genes"]), 4)
        m = ckpt.meta(cp)
        self.assertEqual((m["prey"], m["prey_alive"], m["predators"], m["format_version"]), (5, 4, 2, 2))
        self.assertEqual(ckpt.genome_sha([1, 2]), ckpt.genome_sha([1.0, 2.0]))
        self.assertEqual(ckpt.loads("[-0]"), [-0.0])


class TestCommon(unittest.TestCase):
    def test_sampling_hybrid(self):
        """The design's law (review round 2): without replacement when the pool suffices, otherwise
        independent draws with replacement (no guaranteed copy of every genotype)."""
        p, s = common.sample_indices(50, 20, 7, "hybrid")
        self.assertEqual(len(set(p)), 20)
        self.assertEqual(p, rqlib.SplitMix64(7).sample(50, 20))
        self.assertFalse(s["with_replacement"])
        self.assertEqual((s["policy"], s["distinct"], s["max_copies"], s["duplicated_slots"]), ("hybrid", 20, 1, 0))
        p, s = common.sample_indices(20, 20, 7, "hybrid")
        self.assertEqual(sorted(p), list(range(20)))
        r = rqlib.SplitMix64(9)
        p, s = common.sample_indices(30, 60, 9, "hybrid")
        self.assertEqual(p, [r.below(30) for _ in range(60)])     # iid draws once the pool is short
        self.assertTrue(s["with_replacement"] and s["distinct"] == len(set(p)) and s["distinct"] < 30)
        self.assertEqual(s["duplicated_slots"], 60 - s["distinct"])
        # over many seeds, a pool of 30 for 60 slots misses individuals (balanced duplication never does)
        missed = sum(common.sample_indices(30, 60, k, "hybrid")[1]["distinct"] < 30 for k in range(50))
        self.assertGreater(missed, 40)
        self.assertTrue(all(common.sample_indices(30, 60, k, "wor-balanced")[1]["distinct"] == 30 for k in range(10)))
        self.assertIn("hybrid", common.POLICIES)        # (an explicit option; wor-balanced is the v3 default)
        self.assertIn("hybrid", plan.SAMPLINGS)

    def test_sampling(self):
        p, s = common.sample_indices(50, 20, 7, "wor-balanced")
        self.assertEqual(len(set(p)), 20)
        self.assertFalse(s["with_replacement"])
        p, s = common.sample_indices(7, 20, 7, "wor-balanced")
        counts = [p.count(i) for i in range(7)]
        self.assertEqual(sorted(set(counts)), [2, 3])     # 20 = 2*7 + 6: floor or ceil copies each
        self.assertEqual(sum(counts), 20)
        self.assertTrue(s["with_replacement"] and s["max_copies"] == 3 and s["distinct"] == 7)
        self.assertEqual(s["duplicated_slots"], 13)
        p2, _ = common.sample_indices(7, 20, 7, "wor-balanced")
        self.assertEqual(p, p2)
        self.assertNotEqual(p, common.sample_indices(7, 20, 8, "wor-balanced")[0])
        p, s = common.sample_indices(10, 10, 3, "iid")
        self.assertTrue(s["with_replacement"])
        with self.assertRaises(common.CommonError):
            common.sample_indices(0, 5, 1, "wor-balanced")
        with self.assertRaises(common.CommonError):
            common.sample_indices(5, 5, 1, "bogus")

    def test_build(self):
        tpl = mk_cp(n_prey=10, n_pred=2, frame=7, seed=2)
        src = mk_cp(n_prey=6, n_pred=3, frame=5000, seed=3)
        src["creatures"]["alive"][0] = 0
        out, man = common.build(tpl, src, 8, 99, "wor-balanced", "T", "S", "tsha", "ssha", {"world": "w1"})
        ckpt.validate(out)
        cs = out["creatures"]
        self.assertEqual(cs["id"], list(range(1, 9)))
        self.assertEqual(cs["lineageId"], list(range(1, 9)))
        self.assertEqual(set(cs["generation"]), {0})
        for k, v in common.AGENT_DEFAULTS.items():
            self.assertEqual(set(cs[k]), {v}, k)
        self.assertEqual(set(cs["neuronOutputs"]), {0.5})
        trows = ckpt.prey(tpl)
        for i, r in enumerate(ckpt.prey(out)):
            for k in common.SLOT_COLS:
                self.assertEqual(r[k], trows[i][k], k)
            self.assertEqual(r["body"], trows[i]["body"])
        pool = ckpt.prey(src, alive_only=True)
        for i, r in enumerate(ckpt.prey(out)):
            p = man["slots"]["source_index"][i]
            self.assertEqual(r["genes"], pool[p]["genes"])
            self.assertEqual(man["slots"]["source_id"][i], pool[p]["id"])
            self.assertEqual(man["slots"]["source_lineage"][i], pool[p]["lineageId"])
        self.assertEqual(man["sampling"]["pool"], 5)
        self.assertTrue(man["sampling"]["with_replacement"])
        self.assertEqual(out["world"]["nextId"], 9)
        self.assertEqual(out["world"]["nextPredatorId"], 1)
        self.assertEqual(out["world"]["frame"], 7)
        self.assertEqual(out["predators"]["count"], 0)
        self.assertEqual(out["predators"]["genes"], [])
        self.assertEqual(out["signals"]["rle"], [0, 12])
        self.assertEqual(out["food"], tpl["food"])
        self.assertEqual(out["rngState"], tpl["rngState"])
        self.assertEqual(set(out["counters"].values()) - {0, 1}, set())
        self.assertEqual(out["counters"]["reproStride"], 1)
        self.assertEqual(out["config"], tpl["config"])
        self.assertEqual(man["source"]["meta"], {"world": "w1"})
        self.assertEqual(man["predator_config_differences"], {"predatorCount": [3, 2]})
        # determinism
        out2, man2 = common.build(tpl, src, 8, 99, "wor-balanced", "T", "S", "tsha", "ssha", {"world": "w1"})
        self.assertEqual(ckpt.dumps(out), ckpt.dumps(out2))
        self.assertEqual(rqlib.canonical(man), rqlib.canonical(man2))
        # a version-1 (Stage A / B) source in a version-2 template
        v1 = mk_cp(n_prey=6, n_pred=1, version=1, seed=4)
        out3, man3 = common.build(tpl, v1, 4, 1)
        self.assertEqual(out3["formatVersion"], 2)
        self.assertIn("predatorBrain", man3["predator_config_differences"])

    def test_build_refusals(self):
        tpl = mk_cp(n_prey=10, seed=2)
        src = mk_cp(n_prey=6, seed=3, cfg_extra={"maxPopulation": 60})
        with self.assertRaisesRegex(common.CommonError, "prey configs differ"):
            common.build(tpl, src, 4, 1)
        out, man = common.build(tpl, src, 4, 1, allow_config_mismatch=True)
        self.assertEqual(man["config_differences"], {"maxPopulation": [60, 50]})
        with self.assertRaisesRegex(common.CommonError, "fewer than"):
            common.build(tpl, mk_cp(seed=3), 11, 1)
        dead = mk_cp(seed=3)
        dead["creatures"]["alive"] = [0] * 8
        with self.assertRaisesRegex(common.CommonError, "no living prey"):
            common.build(tpl, dead, 4, 1)
        long_ = mk_cp(seed=3, cfg_extra={"genomeMaxLength": 12})
        tpl2 = mk_cp(n_prey=10, seed=2, cfg_extra={"genomeMaxLength": 1})
        long_["config"]["genomeMaxLength"] = 1
        with self.assertRaisesRegex(common.CommonError, "genome length"):
            common.build(tpl2, long_, 8, 1)


def design(tmp, **kw):
    d = {"schema": plan.DESIGN_SCHEMA, "name": "t", "seed_namespace": "ns1",
         "times": {"F1": 1, "T1": 1000, "T2": 2000},
         "worlds": {"A": {"uuid": "uA", "pattern": f"{tmp}/A.{{frame}}.json", "paths": {"F1": f"{tmp}/A.F1.json"}},
                    "B": {"uuid": "uB", "pattern": f"{tmp}/B.{{label}}.json"}},
         "templates": [f"{tmp}/T0.json", f"{tmp}/T1.json"],
         "defaults": {"assay": "frozen", "k": 3, "prey_policy": "common", "n_prey": 4, "sampling": "hybrid",
                      "steps": 600, "horizons": [200, 600], "log_every": 100, "checkpoint_every": 200},
         "blocks": [{"name": "coarse", "prey_worlds": ["A", "B"], "prey_times": ["F1", "T2"], "predators": "same",
                     "predator_times": ["F1", "T2"], "replicates": 2, "with_nopred": True},
                    {"name": "dense", "prey_worlds": ["A"], "prey_times": ["T1", "T2"], "predators": "same",
                     "predator_times": ["T1", "T2"], "replicates": 2}]}
    d.update(kw)
    return d


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_expand(self):
        rows, _ = plan.expand(design(self.tmp), pending=True)
        rows2, _ = plan.expand(design(self.tmp), pending=True)
        self.assertEqual(b"".join(map(rqlib.canonical, rows)), b"".join(map(rqlib.canonical, rows2)))
        ids = [r["id"] for r in rows]
        self.assertEqual(ids, sorted(ids))
        # coarse: 2 worlds x 2 times x 2 times x 2 reps = 16 assays + 8 forks; dense adds A: (2x2 - 1) x 2 = 6
        self.assertEqual(len(rows), 16 + 8 + 6)
        both = [r for r in rows if r["id"] == "A.T2~A.T2.common.frozen.k3.r00"]
        self.assertEqual(both[0]["blocks"], ["coarse", "dense"])
        by = {r["id"]: r for r in rows}
        a = by["A.T2~A.F1.common.frozen.k3.r01"]
        b = by["A.T2~A.T2.common.frozen.k3.r01"]
        f = by["A.T2~none.common.frozen.k0.r01"]
        self.assertEqual(a["seeds"], b["seeds"])
        self.assertEqual(a["seeds"], f["seeds"])          # the fork shares the group's seeds
        self.assertEqual(a["template"]["path"], f"{self.tmp}/T1.json")
        self.assertEqual(a["prey"]["path"], f"{self.tmp}/A.2000.json")
        self.assertEqual(by["A.F1~A.F1.common.frozen.k3.r00"]["prey"]["path"], f"{self.tmp}/A.F1.json")
        self.assertEqual(by["B.T2~B.T2.common.frozen.k3.r00"]["prey"]["path"], f"{self.tmp}/B.T2.json")
        c = by["A.F1~A.T2.common.frozen.k3.r01"]
        self.assertEqual(c["seeds"]["transplant"], a["seeds"]["transplant"])   # one matrix replicate
        self.assertNotEqual(c["seeds"]["reseed"], a["seeds"]["reseed"])
        self.assertNotEqual(by["A.T2~A.F1.common.frozen.k3.r00"]["seeds"]["sample"], a["seeds"]["sample"])
        self.assertEqual(f["kind"], "nopred")
        self.assertIsNone(f["predators"])
        self.assertEqual(a["prey"]["sha256"], "pending")
        for kind in plan.SEED_KINDS:      # unique within a kind across groups
            per = {}
            for r in rows:
                per.setdefault(r["seeds"][kind], set()).add(r["groups"][kind])
            self.assertTrue(all(len(g) == 1 for g in per.values()), kind)
        self.assertEqual(a["expected"]["checkpoint_steps"], [200, 400, 600])

    def test_conflicts_and_settings(self):
        d = design(self.tmp)
        d["blocks"][1]["steps"] = 800
        d["blocks"][1]["checkpoint_every"] = 200
        with self.assertRaisesRegex(plan.DesignError, "different content"):
            plan.expand(d, pending=True)
        d = design(self.tmp)
        d["defaults"]["horizons"] = [250]
        with self.assertRaises(plan.DesignError):
            plan.expand(d, pending=True)
        d = design(self.tmp)
        d["worlds"]["A_x"] = {"uuid": "x", "pattern": "/x"}
        with self.assertRaises(plan.DesignError):
            plan.expand(d, pending=True)
        d = design(self.tmp, blocks=[{"name": "r", "prey_worlds": ["A"], "prey_times": ["T1"], "predators": "random",
                                      "replicates": 1}, {"name": "x", "prey_worlds": ["B"], "prey_times": ["T1"],
                                      "predators": {"partner": {"B": "A"}}, "predator_times": ["T2"],
                                      "replicates": 1, "prey_policy": "native"}])
        rows, _ = plan.expand(d, pending=True)
        self.assertEqual([r["id"] for r in rows], ["A.T1~random.common.frozen.k3.r00",
                                                   "B.T1~A.T2.native.frozen.k3.r00"])
        self.assertEqual(rows[0]["predators"], {"source": "random"})
        self.assertIsNone(rows[1]["template"])
        self.assertIsNone(rows[1]["seeds"]["sample"])

    def test_pending_binding(self):
        rows, _ = plan.expand(design(self.tmp), pending=True)
        reg = json.loads(json.dumps(rows))
        final = json.loads(json.dumps(rows))
        for r in final:
            for role in ("prey", "predators", "template"):
                if isinstance(r.get(role), dict) and "sha256" in r[role]:
                    r[role]["sha256"] = "a" * 64
        self.assertEqual(plan.pending_problems(final, reg), [])
        final[3]["steps"] = 999
        self.assertTrue(plan.pending_problems(final, reg))
        self.assertTrue(plan.pending_problems(final[:-1], reg))
        self.assertTrue(plan.pending_problems(reg, final))     # a final plan is not a pending one
        self.assertEqual(plan.plan_seeds([{"slot_seed": 4, "reseed": 5, "donor_seed": None}]), {4, 5})


class TestStore(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        store.allow_links(False)       # the default policy (a link test turns it on for its process)
        store._VERIFIED.clear()

    def tearDown(self):
        shutil.rmtree(self.root)

    def mk_cell(self, cid, group="g1", csha="c" * 64, payload="x"):
        d = os.path.join(self.root, store.WORK, cid)
        os.makedirs(d)
        b = rqlib.canonical({"id": cid, "payload": payload})
        wr(os.path.join(d, "bundle.json"), b)
        rqlib.write_json_durable(os.path.join(d, "done.json"), {
            "schema": run.DONE_SCHEMA, "id": cid, "kind": "assay", "bundle_sha256": rqlib.sha256_bytes(b),
            "row_sha256": "r" * 64, "common_group": group, "common_sha256": csha})
        wr(os.path.join(d, "end.json"), "big")

    def test_objects(self):
        sha = store.put_bytes(self.root, b'{"a":1}', compress=True)
        self.assertTrue(store.has(self.root, sha).endswith(".gz"))
        self.assertEqual(store.get_bytes(self.root, sha), b'{"a":1}')
        p = os.path.join(self.root, "src.json")
        with open(p, "w") as f:
            f.write("snapshot")
        s2 = store.put_file(self.root, p)
        self.assertEqual(store.get_bytes(self.root, s2), b"snapshot")
        self.assertEqual(store.put_file(self.root, p), s2)
        with self.assertRaises(store.StoreError):
            store.put_file(self.root, p, want="0" * 64)
        store.sync_objects(self.root, [sha, s2])
        self.assertIsNone(store.has(self.root, "f" * 64))
        self.assertEqual([f for _, _, fs in os.walk(os.path.join(self.root, store.OBJECTS)) for f in fs
                          if ".tmp" in f], [])

    def test_sources_are_independent_copies(self):
        """Review round 2, P1-1: by default a source becomes an independent, verified, read-only
        object; rewriting the archive file in place afterwards cannot change it."""
        p = os.path.join(self.root, "arch.json")
        with open(p, "w") as f:
            f.write("archive v1")
        sha = store.put_file(self.root, p, want=rqlib.sha256_bytes(b"archive v1"))
        obj = store.has(self.root, sha)
        st = os.stat(obj)
        self.assertEqual(st.st_nlink, 1)
        self.assertEqual(st.st_mode & 0o777, 0o444)
        self.assertNotEqual(st.st_ino, os.stat(p).st_ino)
        with open(p, "r+") as f:          # an in-place rewrite of the archive file
            f.write("ARCHIVE v2")
        self.assertEqual(store.get_bytes(self.root, sha), b"archive v1")

    def test_link_session_start(self):
        """Review round 4: a READ-ONLY legacy hard link into an archive without FINALIZED, in a root
        resumed with --link-sources, is migrated to an independent copy at the start (the copy
        policy runs first); a mismatched one is reported and never served; the session's policy
        is the requested one afterwards."""
        arch = os.path.join(self.root, "archive")
        os.makedirs(arch)                                    # no FINALIZED, writable directory
        objs = {}
        for name, text in (("good", "legacy world"), ("bad", "legacy world two")):
            p = os.path.join(arch, name + ".json")
            wr(p, text)
            sha = rqlib.sha256_bytes(text.encode())
            o = os.path.join(self.root, store.OBJECTS, sha[:2], sha)
            os.makedirs(os.path.dirname(o), exist_ok=True)
            os.link(p, o)
            objs[name] = (p, sha, o)
        p_bad = objs["bad"][0]
        wr(p_bad, "LEGACY WORLD TWO")                        # rewritten through the shared inode ...
        for p, _, _ in objs.values():
            os.chmod(p, 0o444)                               # ... and both read-only now
        try:
            n, probs = store.start_session(self.root, True, log=lambda m: None)
            self.assertEqual(n, 1)
            self.assertTrue(len(probs) == 1 and objs["bad"][1][:12] in probs[0], probs)
            p, sha, o = objs["good"]
            self.assertEqual((os.stat(o).st_nlink, os.stat(o).st_mode & 0o777), (1, 0o444))
            self.assertNotEqual(os.stat(o).st_ino, os.stat(p).st_ino)
            self.assertTrue(store._LINKS_ALLOWED)            # the session's policy, set afterwards
            self.assertIsNone(store.has(self.root, objs["bad"][1]))   # still never served
        finally:
            for p, _, _ in objs.values():
                os.chmod(p, 0o644)
            store.allow_links(False)

    def test_link_contract(self):
        """--link-sources: refused for a writable file, a writable directory or no FINALIZED marker;
        accepted (one shared inode) for a finalized read-only archive."""
        arch = os.path.join(self.root, "archive")
        os.makedirs(arch)
        p = os.path.join(arch, "w.1000.json")
        with open(p, "w") as f:
            f.write("final snapshot")
        try:
            self.assertIn("writable", store.link_contract_problem(p))
            with self.assertRaisesRegex(store.StoreError, "link-sources refused"):
                store.put_file(self.root, p, link=True)
            os.chmod(p, 0o444)
            self.assertIn("directory", store.link_contract_problem(p))
            with open(os.path.join(arch, store.FINALIZED), "w") as f:
                f.write("done\n")
            os.chmod(arch, 0o555)
            if os.access(p, os.W_OK):      # running as root: permissions do not bind, the test cannot
                return
            self.assertIsNone(store.link_contract_problem(p))
            sha = store.put_file(self.root, p, link=True)
            self.assertEqual(os.stat(store.has(self.root, sha)).st_ino, os.stat(p).st_ino)
            os.chmod(arch, 0o755)
            os.remove(os.path.join(arch, store.FINALIZED))
            os.chmod(arch, 0o555)
            self.assertIn(store.FINALIZED, store.link_contract_problem(p))
        finally:
            os.chmod(arch, 0o755)

    def test_recover_keeps_working_copies_when_a_chunk_is_bad(self):
        """Review round 2, P1-2: an interrupted pack (committed, working directories not yet deleted)
        whose ZIP is then missing or damaged keeps every working directory and reports; a good ZIP
        lets recover delete them."""
        for i in range(3):
            self.mk_cell(f"k{i}")
        store.pack(self.root, log=lambda m: None)
        recs, cells = store.load_index(self.root)
        chunk = os.path.join(self.root, store.CHUNKS, recs[0]["chunk"])
        good = rqlib.read_bytes(chunk)

        with zipfile.ZipFile(io.BytesIO(good)) as z:      # the state of a pack interrupted after its commit
            for cid in ("k0", "k1", "k2"):
                d = os.path.join(self.root, store.WORK, cid)
                os.makedirs(d)
                for m in ("bundle.json", "done.json"):
                    with open(os.path.join(d, m), "wb") as f:
                        f.write(z.read(f"{cid}/{m}"))
        os.remove(chunk)                                    # the ZIP missing
        acts, probs = store.recover(self.root, log=lambda m: None)
        self.assertTrue(probs and "missing" in probs[0], probs)
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, store.WORK))), ["k0", "k1", "k2"])
        bad = bytearray(good)
        bad[len(bad) // 3] ^= 0xFF                          # the ZIP damaged (same size)
        with open(chunk, "wb") as f:
            f.write(bytes(bad))
        for deep in (True, False):                          # even --quick-resume checks it in full
            acts, probs = store.recover(self.root, log=lambda m: None, deep=deep)
            self.assertTrue(probs, deep)
            self.assertEqual(sorted(os.listdir(os.path.join(self.root, store.WORK))), ["k0", "k1", "k2"])
        wr(chunk, good)
        # (review round 3) the chunk is fine but ONE leftover bundle differs: nothing is deleted,
        # not even the leftovers that do match (they are all checked before any deletion)
        k2 = os.path.join(self.root, store.WORK, "k2", "bundle.json")
        k2_good = rqlib.read_bytes(k2)
        wr(k2, b" ", "ab")
        acts, probs = store.recover(self.root, log=lambda m: None, deep=False)
        self.assertTrue(probs and "k2" in probs[0], probs)
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, store.WORK))), ["k0", "k1", "k2"])
        wr(k2, k2_good)
        acts, probs = store.recover(self.root, log=lambda m: None, deep=False)
        self.assertEqual(probs, [])
        self.assertEqual(os.listdir(os.path.join(self.root, store.WORK)), [])
        self.assertEqual(sum("deleted the packed cell" in x for x in acts), 3)

    def test_legacy_objects_migrated(self):
        """Review round 3, P1-1: an object a pre-round-2 root holds as a WRITABLE HARD LINK to an
        archive file (or as a writable copy) is replaced by an independent read-only copy before it
        is served (has, put_file's shortcut, the start-of-run sweep); the archive's inode is not
        touched (no chmod); a later in-place rewrite of the archive cannot reach the object; an
        object whose content no longer matches its name is not served."""
        store.allow_links(False)
        arch = os.path.join(self.root, "a.json")
        wr(arch, "the archived world")
        os.chmod(arch, 0o644)
        sha = rqlib.sha256_bytes(b"the archived world")
        obj = os.path.join(self.root, store.OBJECTS, sha[:2], sha)
        os.makedirs(os.path.dirname(obj))
        os.link(arch, obj)                                   # the legacy object
        self.assertEqual(store.put_file(self.root, arch, want=sha), sha)   # the shortcut migrates
        st, sa = os.stat(obj), os.stat(arch)
        self.assertEqual((st.st_nlink, st.st_mode & 0o777), (1, 0o444))
        self.assertNotEqual(st.st_ino, sa.st_ino)
        self.assertEqual(sa.st_mode & 0o777, 0o644)          # the archive file was not chmod'ed
        with open(arch, "r+") as f:
            f.write("THE ARCHIVED WORLD")                    # rewritten in place
        self.assertEqual(store.get_bytes(self.root, sha), b"the archived world")
        # the sweep at a runner's start: a writable copy and another shared link
        sha2 = store.put_bytes(self.root, b"tool v1")
        o2 = store.has(self.root, sha2)
        os.chmod(o2, 0o644)
        arch3 = os.path.join(self.root, "b.json")
        wr(arch3, "another world")
        sha3 = rqlib.sha256_bytes(b"another world")
        o3 = os.path.join(self.root, store.OBJECTS, sha3[:2], sha3)
        os.makedirs(os.path.dirname(o3), exist_ok=True)
        os.link(arch3, o3)
        store._VERIFIED.clear()
        n, probs = store.migrate_all(self.root, log=lambda m: None)
        self.assertEqual((n, probs), (2, []))
        for o in (o2, o3):
            self.assertEqual((os.stat(o).st_nlink, os.stat(o).st_mode & 0o777), (1, 0o444))
        # a legacy link whose archive has ALREADY been rewritten cannot be saved, and is not served
        arch4 = os.path.join(self.root, "c.json")
        wr(arch4, "world four")
        sha4 = rqlib.sha256_bytes(b"world four")
        o4 = os.path.join(self.root, store.OBJECTS, sha4[:2], sha4)
        os.makedirs(os.path.dirname(o4), exist_ok=True)
        os.link(arch4, o4)
        wr(arch4, "WORLD FOUR")
        self.assertIsNone(store.has(self.root, sha4))
        n, probs = store.migrate_all(self.root, log=lambda m: None)
        self.assertEqual(n, 0)
        self.assertTrue(any(sha4[:12] in p for p in probs), probs)
        # under --link-sources a read-only shared link is accepted as it is
        store.allow_links(True)
        try:
            os.chmod(arch3, 0o444)
            arch5 = os.path.join(self.root, "d.json")
            wr(arch5, "world five")
            os.chmod(arch5, 0o444)
            sha5 = rqlib.sha256_bytes(b"world five")
            o5 = os.path.join(self.root, store.OBJECTS, sha5[:2], sha5)
            os.makedirs(os.path.dirname(o5), exist_ok=True)
            os.link(arch5, o5)
            self.assertEqual(os.stat(store.has(self.root, sha5)).st_ino, os.stat(arch5).st_ino)
        finally:
            store.allow_links(False)

    def test_pack_verify_recover(self):
        for i in range(5):
            self.mk_cell(f"c{i}", group=f"g{i % 2}", csha=("a" if i % 2 else "b") * 64)
        name, n = store.pack(self.root, ids=["c0", "c1", "c2"], log=lambda m: None)
        self.assertEqual((name, n), ("chunk_000001.zip", 3))
        self.assertFalse(os.path.exists(os.path.join(self.root, store.WORK, "c0")))
        self.assertTrue(os.path.exists(os.path.join(self.root, store.WORK, "c3")))
        recs, cells = store.load_index(self.root)
        self.assertEqual(sorted(cells), ["c0", "c1", "c2"])
        self.assertEqual(json.loads(store.read_member(self.root, "c1", cells=cells)), {"id": "c1", "payload": "x"})
        self.assertEqual(store.verify_all(self.root), [])
        # an orphan chunk (crash after the rename, before the index line) and a truncated index line
        name2, _ = store.pack(self.root, ids=["c3"], log=lambda m: None)
        ip = os.path.join(self.root, store.INDEX)
        raw = rqlib.read_bytes(ip)
        wr(ip, raw[:-40])            # the second line torn
        self.mk_cell("c3", group="g1", csha="a" * 64)   # its cell directory is back (deleted after the commit)
        acts, probs = store.recover(self.root, log=lambda m: None)
        self.assertEqual(probs, [])
        self.assertTrue(any("chunk_000002.zip" in a for a in acts), acts)
        recs, cells = store.load_index(self.root)
        self.assertEqual(len(recs), 1)
        self.assertNotIn("c3", cells)
        self.assertTrue(rqlib.read_bytes(ip).endswith(b"\n"))
        # a packed cell's leftover directory is deleted at recover (after its bundle is checked)
        os.makedirs(os.path.join(self.root, store.WORK, "c0"))
        wr(os.path.join(self.root, store.WORK, "c0", "bundle.json"),
            rqlib.canonical({"id": "c0", "payload": "x"}))
        self.assertEqual(store.recover(self.root, log=lambda m: None)[1], [])
        self.assertFalse(os.path.exists(os.path.join(self.root, store.WORK, "c0")))
        # the rest packs; a common group with two different checkpoints is refused, nothing deleted
        store.pack(self.root, log=lambda m: None)
        self.mk_cell("c9", group="g1", csha="e" * 64)
        with self.assertRaisesRegex(store.StoreError, "nondeterministic"):
            store.pack(self.root, log=lambda m: None)
        self.assertTrue(os.path.exists(os.path.join(self.root, store.WORK, "c9", "bundle.json")))
        # a damaged chunk is found
        recs, _ = store.load_index(self.root)
        cp = os.path.join(self.root, store.CHUNKS, recs[0]["chunk"])
        b = bytearray(rqlib.read_bytes(cp))
        b[40] ^= 1
        wr(cp, bytes(b))
        self.assertTrue(store.verify_all(self.root))
        # a bundle that does not match its done record is refused
        wr(os.path.join(self.root, store.WORK, "c9", "bundle.json"), b" ", "ab")
        with self.assertRaisesRegex(store.StoreError, "does not match"):
            store.pack(self.root, ids=["c9"], log=lambda m: None)

    def test_chunk_members(self):
        self.mk_cell("z1")
        store.pack(self.root, log=lambda m: None)
        recs, _ = store.load_index(self.root)
        with zipfile.ZipFile(os.path.join(self.root, store.CHUNKS, recs[0]["chunk"])) as z:
            self.assertEqual(sorted(z.namelist()), ["z1/bundle.json", "z1/done.json"])


class TestFork(unittest.TestCase):
    """Review round 2, P2-5: a predator-free continuation with predators, captures, births or refills
    at any time is refused."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        arena = mk_cp(n_prey=6, n_pred=0, frame=100)
        with open(os.path.join(self.d, "arena.json"), "w") as f:
            f.write(ckpt.dumps(arena))
        self.end = mk_cp(n_prey=6, n_pred=0, frame=300)
        self.rows = [{"step": s, "predator_pop": 0, "prey_pop": 6, "captures_interval": 0, "births_interval": 0,
                      "deaths_starv_interval": 0, "deaths_age_interval": 0, "reseeds_interval": 0,
                      "pursuit_frac": 0, "virtual_buds_interval": 0} for s in (200, 300)]

    def tearDown(self):
        shutil.rmtree(self.d)

    def write(self, rows=None, end=None):
        rows = rows or self.rows
        with open(os.path.join(self.d, "run.predators.csv"), "w") as f:
            f.write(",".join(rows[0]) + "\n" + "".join(",".join(str(r[k]) for k in rows[0]) + "\n" for r in rows))
        with open(os.path.join(self.d, "end.300.json"), "w") as f:
            f.write(ckpt.dumps(end or self.end))

    def test_fork(self):
        import score
        for assay in ("frozen", "live"):
            self.write()
            s = score.score(self.d, 0, 200, [200], 100, assay, fork=True)
            self.assertTrue(s["checks"]["fork_predator_free"] and s["horizons"][0]["captures"] == 0)
            rows = copy.deepcopy(self.rows)
            rows[1]["predator_pop"] = 1          # a refilled predator at a sample
            rows[1]["reseeds_interval"] = 1
            self.write(rows)
            with self.assertRaisesRegex(score.ScoreError, "predator-free fork"):
                score.score(self.d, 0, 200, [200], 100, assay, fork=True)
            end = copy.deepcopy(self.end)       # a refill between the samples, seen in the counters
            end["counters"]["totalPredatorReseeds"] = 1
            self.write(end=end)
            with self.assertRaisesRegex(score.ScoreError, "predator-free fork"):
                score.score(self.d, 0, 200, [200], 100, assay, fork=True)
            self.write()
            with self.assertRaises(score.ScoreError):
                score.score(self.d, 1, 200, [200], 100, assay, fork=True)

    def test_prey_replenishment(self):
        """Review round 3, P2-5: prey injected by a floor are refused in every cell (fork or not): a
        founder outside the initial cohort, or a living count beyond start + births - deaths (an
        injected prey that died again before the horizon)."""
        import score
        for fork in (True, False):
            for assay in ("frozen", "live"):
                self.write()
                score.score(self.d, 0, 200, [200], 100, assay, fork=fork)
                end = copy.deepcopy(self.end)            # an injected founder, alive at the horizon
                rows = ckpt.prey(end)
                new = dict(rows[0], id=999, lineageId=999, generation=0)
                ckpt.set_prey(end, rows + [new])
                end["world"]["nextId"] = 1000
                end["counters"]["totalBirths"] += 1      # (even if it were counted as a birth)
                self.write(end=end)
                with self.assertRaisesRegex(score.ScoreError, "prey replenished"):
                    score.score(self.d, 0, 200, [200], 100, assay, fork=fork)
                end = copy.deepcopy(self.end)            # one injected and dead again: the count shows it
                end["counters"]["totalDeaths"] += 1
                end["counters"]["totalDeathsStarvation"] += 1
                self.write(end=end)
                with self.assertRaisesRegex(score.ScoreError, "prey replenished"):
                    score.score(self.d, 0, 200, [200], 100, assay, fork=fork)


class TestProcesses(unittest.TestCase):
    PARENT = ("import os, subprocess, sys, time\n"
              "sys.path.insert(0, sys.argv[1])\n"
              "import rqlib\n"
              "child = subprocess.Popen([sys.executable, '-I', '-c', sys.argv[2]], preexec_fn=rqlib.death_signal())\n"
              "sys.stdout.write(f'{child.pid}\\n'); sys.stdout.flush()\n"
              "time.sleep(120)\n")

    @unittest.skipUnless(rqlib._LIBC is not None and os.path.isdir("/proc/self"), "needs Linux")
    def test_parent_death_kills_a_stopped_worker(self):
        """Review round 3: the parent-death signal is SIGKILL, so a STOPPED child that handles SIGTERM
        (a worker) still dies with its parent (with SIGTERM it would stay pending, the worker and
        its engine running on)."""
        import signal
        import subprocess
        import time
        par = subprocess.Popen([sys.executable, "-I", "-c", self.PARENT, HERE, self.WORKER],
                               stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, start_new_session=True)
        lines = sorted([par.stdout.readline(), par.stdout.readline()])   # the child's pid, and its "ready"
        par.stdout.close()
        self.assertEqual(lines[1], b"ready\n")                 # the child's handler is in place
        child = int(lines[0])
        os.kill(child, signal.SIGSTOP)
        deadline = time.monotonic() + 10
        while self._state(child) != "T":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        os.kill(par.pid, signal.SIGKILL)
        par.wait()
        deadline = time.monotonic() + 10
        while True:
            try:
                st = self._state(child)
            except FileNotFoundError:
                break
            if st in ("Z", "X"):
                break
            self.assertLess(time.monotonic(), deadline, f"the stopped child outlived its parent (state {st})")
            time.sleep(0.02)

    @unittest.skipUnless(rqlib._LIBC is not None, "PR_SET_PDEATHSIG needs Linux libc")
    def test_death_signal_parent_check(self):
        """Review round 2, P2-8: a child whose spawning parent is already gone (getppid differs from the
        pid captured before the fork) exits before running anything."""
        import subprocess
        out = subprocess.run([sys.executable, "-c", "print('ran')"], capture_output=True,
                             preexec_fn=rqlib.death_signal(expected_parent=os.getpid() + 999999))
        self.assertEqual((out.returncode, out.stdout), (1, b""))
        out = subprocess.run([sys.executable, "-c", "print('ran')"], capture_output=True,
                             preexec_fn=rqlib.death_signal())
        self.assertEqual((out.returncode, out.stdout.strip()), (0, b"ran"))

    # A stand-in worker: it HANDLES SIGTERM (as a real worker does, cell.forward_signals: stop the
    # engine, exit), says "ready" once the handler is installed, then waits. A process that leaves
    # SIGTERM at its default action can be killed by the kernel even while stopped (a fatal signal
    # wakes a stopped task: round 2's CI failure), so it cannot model the hang; a HANDLED SIGTERM
    # stays pending while the process is stopped, which is the case the escalation exists for.
    WORKER = ("import os, signal, sys, time\n"
              "signal.signal(signal.SIGTERM, lambda s, f: os._exit(0))\n"
              "sys.stdout.write('ready\\n'); sys.stdout.flush()\n"
              "time.sleep(120)\n")

    def _worker(self):
        import subprocess
        p = subprocess.Popen([sys.executable, "-I", "-c", self.WORKER], start_new_session=True,
                             stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
        self.assertEqual(p.stdout.readline(), b"ready\n")    # the handler is in place
        p.stdout.close()
        return p

    @staticmethod
    def _state(pid):
        """The kernel's process state letter (/proc/<pid>/stat): 'S', 'T' (stopped), 'Z', ..."""
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0]

    @unittest.skipUnless(os.path.isdir("/proc/self"), "needs /proc")
    def test_stop_groups_stopped_worker(self):
        """Review round 2, P2-7: a SIGSTOPped worker cannot act on SIGTERM; the bounded wait escalates
        to SIGKILL after the grace instead of hanging. Deterministic: the worker handles SIGTERM, and
        the test waits until the kernel reports it stopped before it stops the group."""
        import signal
        import time
        p = self._worker()
        os.kill(p.pid, signal.SIGSTOP)
        deadline = time.monotonic() + 10
        while self._state(p.pid) != "T":
            self.assertLess(time.monotonic(), deadline, "the worker never reached the stopped state")
            time.sleep(0.01)
        grace = 1.0
        t0 = time.monotonic()
        killed = run.stop_groups([p], grace=grace)
        dt = time.monotonic() - t0
        self.assertEqual(killed, [p.pid])                    # it needed the SIGKILL ...
        self.assertEqual(p.returncode, -signal.SIGKILL)      # ... and that is what ended it
        self.assertGreaterEqual(dt, grace)                   # after the grace, not before
        self.assertLess(dt, grace + 10)                      # and within the bound
        # contrast: the same worker, running, honours SIGTERM and gets no SIGKILL
        q = self._worker()
        self.assertEqual(run.stop_groups([q], grace=grace), [])
        self.assertEqual(q.returncode, 0)


class TestRunner(unittest.TestCase):
    def test_bio_ledger(self):
        root = tempfile.mkdtemp()
        led_p = os.path.join(root, run.BIO_LEDGER)
        try:
            self.assertEqual(run.read_bio_ledger(root), [])
            self.assertEqual(run.recover_bio_ledger(root), ([], b""))
            run.append_bio_ledger(root, {"cell": "c", "role": "predators", "sha256": "a" * 64})
            wr(led_p, '{"torn', "ab")                       # a crash while appending
            led = run.read_bio_ledger(root)
            self.assertEqual(len(led), 1)
            self.assertEqual(led[0]["schema"], run.BIO_SCHEMA)
            self.assertTrue(run.bio_match({"predators": {"sha256": "a" * 64}}, led))
            self.assertFalse(run.bio_match({"prey": {"sha256": "a" * 64}, "predators": None}, led))   # role-specific
        finally:
            shutil.rmtree(root)

    def test_bio_ledger_recovery(self):
        """Review round 3: a torn tail is cut under the lock before the next append, so an acknowledged
        record is never swallowed; a complete record without its newline counts as torn; a restart
        sees exactly the acknowledged records; a malformed interior record is refused."""
        root = tempfile.mkdtemp()
        led_p = os.path.join(root, run.BIO_LEDGER)
        try:
            run.append_bio_ledger(root, {"cell": "c1", "role": "prey", "sha256": "1" * 64})
            wr(led_p, '{"torn', "ab")
            recs, torn = run.recover_bio_ledger(root)
            self.assertEqual(([r["cell"] for r in recs], torn), (["c1"], b'{"torn'))
            run.append_bio_ledger(root, {"cell": "c2", "role": "predators", "sha256": "2" * 64})
            self.assertEqual([r["cell"] for r in run.read_bio_ledger(root)], ["c1", "c2"])
            self.assertEqual([r["cell"] for r in run.recover_bio_ledger(root)[0]], ["c1", "c2"])   # a restart
            self.assertTrue(rqlib.read_bytes(led_p).endswith(b"\n"))
            whole = rqlib.canonical({"cell": "c3", "schema": run.BIO_SCHEMA})[:-1]   # complete JSON, no newline
            wr(led_p, whole, "ab")
            recs, torn = run.recover_bio_ledger(root)
            self.assertEqual(([r["cell"] for r in recs], torn), (["c1", "c2"], whole))
            wr(led_p, b"garbage\n" + rqlib.read_bytes(led_p))           # damage before acknowledged records
            with self.assertRaises(run.LedgerError):
                run.recover_bio_ledger(root)
            with self.assertRaises(run.LedgerError):
                run.read_bio_ledger(root)
        finally:
            shutil.rmtree(root)

    def test_bio_ledger_partial_write(self):
        """Review round 4: a write error after a PARTIAL record blocks every further append of the
        session (the next failure stays unacknowledged instead of landing on the partial bytes); the
        restart's recovery cuts the partial record and keeps every acknowledged one."""
        import errno
        root = tempfile.mkdtemp()
        try:
            led = run.BioLedger(root)
            led.append({"cell": "c1", "role": "prey", "sha256": "1" * 64})       # acknowledged

            def partial(f, data):
                f.write(data[: len(data) // 2])
                raise OSError(errno.ENOSPC, "No space left on device")
            led._write = partial
            with self.assertRaises(OSError):
                led.append({"cell": "c2", "role": "prey", "sha256": "2" * 64})   # partly written, failed
            del led._write
            with self.assertRaises(run.LedgerError):                           # blocked for the session
                led.append({"cell": "c3", "role": "predators", "sha256": "3" * 64})
            self.assertFalse(rqlib.read_bytes(os.path.join(root, run.BIO_LEDGER)).endswith(b"\n"))
            recs, torn = run.recover_bio_ledger(root)                          # the restart
            self.assertEqual([r["cell"] for r in recs], ["c1"])
            self.assertTrue(torn)
            run.BioLedger(root).append({"cell": "c4", "role": "prey", "sha256": "4" * 64})
            self.assertEqual([r["cell"] for r in run.recover_bio_ledger(root)[0]], ["c1", "c4"])
        finally:
            shutil.rmtree(root)

    def test_live_floor_refused_at_planning(self):
        tmp = tempfile.mkdtemp()
        try:
            for name, frame, extra in (("A.F1", 1, {}), ("T0", 7, {"predatorMinPopulation": 2}),
                                       ("T1", 7, {"predatorMinPopulation": 0}),
                                       ("T2", 7, {"predatorMinPopulation": 0, "minPopulation": 50}),
                                       ("B.F1", 1, {"minPopulation": 50})):
                wr(os.path.join(tmp, name + ".json"), ckpt.dumps(mk_cp(n_prey=8, frame=frame, cfg_extra=extra)))
            d = design(tmp, times={"F1": 1}, templates=[f"{tmp}/T0.json"],
                       blocks=[{"name": "l", "prey_worlds": ["A"], "prey_times": ["F1"], "predators": "same",
                                "predator_times": ["F1"], "replicates": 1, "with_nopred": True, "assay": "live"}])
            with self.assertRaisesRegex(plan.DesignError, "predatorMinPopulation 0"):
                plan.expand(d)
            d["templates"] = [f"{tmp}/T2.json"]             # (review round 3) a prey floor, common prey
            with self.assertRaisesRegex(plan.DesignError, "prey minPopulation of 0"):
                plan.expand(d)
            d["templates"] = [f"{tmp}/T1.json"]
            rows, _ = plan.expand(d)
            self.assertEqual([r["kind"] for r in rows], ["assay", "nopred"])
            self.assertTrue(all(rqlib.is_sha256(r["template"]["sha256"]) for r in rows))
            nat = dict(d, blocks=[dict(d["blocks"][0], prey_worlds=["B"], predators={"world": "A"},
                                       prey_policy="native")])
            with self.assertRaisesRegex(plan.DesignError, "prey minPopulation of 0"):   # a prey floor, native prey
                plan.expand(nat)
            nat["blocks"][0]["assay"] = "frozen"            # frozen arenas get no floor (the transplant)
            self.assertEqual(len(plan.expand(nat)[0]), 2)
        finally:
            shutil.rmtree(tmp)


    def test_memory_and_disk_readings(self):
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(f"{tmp}/cg/a/b")
            wr(f"{tmp}/meminfo", "MemTotal: 9000000 kB\nMemAvailable: 8000000 kB\n")
            wr(f"{tmp}/proc_cgroup", "0::/a/b\n")
            wr(f"{tmp}/cg/a/b/memory.max", "1073741824\n")
            wr(f"{tmp}/cg/a/b/memory.current", "536870912\n")
            wr(f"{tmp}/cg/a/memory.max", "max\n")
            os.environ.update(RQ_MEMINFO=f"{tmp}/meminfo", RQ_PROC_CGROUP=f"{tmp}/proc_cgroup",
                              RQ_CGROUP_ROOT=f"{tmp}/cg")
            self.assertEqual(run.mem_headroom_mb(), 512)
            wr(f"{tmp}/cg/a/b/memory.max", "max\n")
            self.assertEqual(run.mem_headroom_mb(), 7812)
            wr(f"{tmp}/cg/a/b/memory.max", "1073741824\n")
            wr(f"{tmp}/cg/a/b/memory.current", "oops\n")
            self.assertIsNone(run.mem_headroom_mb())
            os.environ["RQ_MEMINFO"] = f"{tmp}/none"
            self.assertIsNone(run.mem_headroom_mb())
        finally:
            for k in ("RQ_MEMINFO", "RQ_PROC_CGROUP", "RQ_CGROUP_ROOT"):
                os.environ.pop(k, None)
            shutil.rmtree(tmp)
        self.assertEqual(run.disk_guards(["none"], "/r"), [])
        self.assertEqual(run.disk_guards(["/x:5", "/y:7"], "/r"), [("/x", 5), ("/y", 7)])
        with self.assertRaises(SystemExit):
            run.disk_guards(["nope"], "/r")
        self.assertIsNotNone(run.disk_problem([("/", 10 ** 12)]))
        self.assertIsNone(run.disk_problem([("/", 0)]))

    def test_plan_loading(self):
        tmp = tempfile.mkdtemp()
        try:
            rows, _ = plan.expand(design(tmp), pending=True)
            p = os.path.join(tmp, "p.jsonl")
            plan.write_plan(rows, p)
            with self.assertRaises(SystemExit):     # a pending plan never runs
                run.load_plan(p)
            for r in rows:
                for role in ("prey", "predators", "template"):
                    if isinstance(r.get(role), dict):
                        r[role]["sha256"] = "a" * 64
            plan.write_plan(rows + rows[:1], p)
            with self.assertRaises(SystemExit):     # duplicate ids
                run.load_plan(p)
            plan.write_plan(rows, p)
            self.assertEqual(len(run.load_plan(p)), len(rows))
        finally:
            shutil.rmtree(tmp)

    def test_cell_commands(self):
        rows, _ = plan.expand(design("/x"), pending=True)
        by = {r["id"]: r for r in rows}
        t, a = cell.commands(by["A.T2~A.F1.common.frozen.k3.r01"], "common.json")
        r = by["A.T2~A.F1.common.frozen.k3.r01"]
        self.assertEqual(t, ["--load-checkpoint", "common.json", "--predators-from", "pred.json", "--transplant-count",
                             "3", "--transplant-seed", str(r["seeds"]["transplant"]), "--assay", "frozen",
                             "--transplant-out", "arena.json"])
        self.assertEqual(a, ["--load-checkpoint", "arena.json", "--reseed-after-load", str(r["seeds"]["reseed"]),
                             "--headless", "600", "--no-render", "--log-every", "100", "--checkpoint-every", "200",
                             "--save-checkpoint", "end.json", "--csv", "run.csv"])
        t, _ = cell.commands(by["A.T2~none.common.frozen.k0.r01"], "common.json")
        self.assertEqual(t[3:6], ["random", "--transplant-count", "0"])
        self.assertEqual(cell.normalize_run_csv("step,elapsed_s,pop,steps_per_sec\n1,0.5,9,100\n"), "step,pop\n1,9\n")
        self.assertEqual(run.OUTPUT_TOOLS, cell.OUTPUT_TOOLS)


def design2(tmp, edges, **kw):
    d = {"schema": plan.DESIGN_SCHEMA_V2, "name": "t2", "seed_namespace": "ns2",
         "times": {"F1": 1, "T1": 1000, "T2": 2000},
         "worlds": {"A": {"uuid": "uA", "pattern": f"{tmp}/A.{{frame}}.json", "paths": {"F1": f"{tmp}/A.F1.json"}},
                    "B": {"uuid": "uB", "pattern": f"{tmp}/B.{{frame}}.json", "paths": {"F1": f"{tmp}/B.F1.json"}}},
         "templates": [f"{tmp}/T0.json"], "age_reference": f"{tmp}/ages.json", "replicates": 2,
         "defaults": {"n_prey": 4, "short_steps": 400, "long_steps": 800, "short_horizons": [400],
                      "long_horizons": [400, 800], "log_every": 100, "checkpoint_every": 200, "k": 3},
         "long": {"fraction": 0.25, "strata": ["family"]},
         "edges": edges}
    d.update(kw)
    return d


def E(fam, role, pw, pt, qw=None, qt=None, **kw):
    e = {"family": fam, "role": role, "prey": {"world": pw, "time": pt},
         "predators": None if qw is None else ({"source": "random"} if qw == "random" else {"world": qw, "time": qt})}
    e.update(kw)
    return e


class TestV3Common(unittest.TestCase):
    """Design v3 §3.1-3.2: wor-balanced is the default; reference ages, permuted per snapshot x replicate."""

    def test_defaults_and_diversity(self):
        self.assertEqual(common.POLICIES[0], "wor-balanced")
        tpl, src = mk_cp(n_prey=10, seed=2), mk_cp(n_prey=6, seed=3)
        out, man = common.build(tpl, src, 8, 5)
        s = man["sampling"]
        self.assertEqual(s["policy"], "wor-balanced")
        self.assertEqual((s["distinct_individuals"], s["pool"]), (6, 6))     # 8 slots from 6: every one, 2 twice
        self.assertLessEqual(s["distinct_genomes"], 6)
        self.assertGreater(s["effective_genomes"], 1)
        self.assertGreater(s["effective_lineages"], 1)
        self.assertEqual(len(man["slots"]["genome_sha16"]), 8)
        self.assertEqual(man["schema"], common.SCHEMA)
        self.assertEqual(set(out["creatures"]["age"]), {0.0})

    def test_reference_ages(self):
        srcs = [mk_cp(n_prey=6, seed=k) for k in (1, 2)]
        for k, cp in enumerate(srcs):
            cp["creatures"]["age"] = [float(10 * k + j) for j in range(6)]
            cp["config"]["maxAge"] = 120.0
        ref = common.reference_ages(srcs, 4, ["s0", "s1"])
        pooled = sorted([float(j) for j in range(6)] + [float(10 + j) for j in range(6)])
        self.assertEqual(ref["ages"], [pooled[int((i + 0.5) / 4 * 12)] for i in range(4)])
        self.assertEqual((ref["n"], ref["pooled"], ref["max_age"]), (4, 12, 120.0))
        common.load_age_reference(ref)
        bad = dict(ref, ages=list(reversed(ref["ages"])))
        with self.assertRaises(common.CommonError):
            common.load_age_reference(bad)
        tpl, src = mk_cp(n_prey=10, seed=2, cfg_extra={"maxAge": 120.0}), mk_cp(n_prey=6, seed=3, cfg_extra={"maxAge": 120.0})
        out, man = common.build(tpl, src, 4, 5, age_reference=ref, age_seed=77, ages_label="AGES", ages_sha="s")
        ages = out["creatures"]["age"]
        self.assertEqual(sorted(ages), ref["ages"])
        perm = rqlib.SplitMix64(77).shuffle(list(range(4)))
        self.assertEqual(ages, [ref["ages"][perm[i]] for i in range(4)])
        self.assertEqual(man["schema"], common.SCHEMA_AGES)
        self.assertEqual((man["ages"]["permutation_seed"], man["ages"]["label"]), (77, "AGES"))
        out2, _ = common.build(tpl, src, 4, 5, age_reference=ref, age_seed=77)
        self.assertEqual(out2["creatures"]["age"], ages)                    # one realization per seed
        out3, _ = common.build(tpl, src, 4, 5, age_reference=ref, age_seed=78)
        self.assertNotEqual(out3["creatures"]["age"], ages)
        for kw, msg in (({"age_seed": None}, "permutation seed"),):
            with self.assertRaisesRegex(common.CommonError, msg):
                common.build(tpl, src, 4, 5, age_reference=ref, **kw)
        with self.assertRaisesRegex(common.CommonError, "slots"):
            common.build(tpl, src, 5, 5, age_reference=ref, age_seed=1)
        tpl_other = mk_cp(n_prey=10, seed=2, cfg_extra={"maxAge": 60.0})
        src_other = mk_cp(n_prey=6, seed=3, cfg_extra={"maxAge": 60.0})
        with self.assertRaisesRegex(common.CommonError, "maxAge"):
            common.build(tpl_other, src_other, 4, 5, age_reference=ref, age_seed=1)


class TestPlanV2(unittest.TestCase):
    """Design v3 §3.5 / §4.6 / §7.1: explicit edge lists with roles, global snapshot x replicate seeds,
    the pre-randomized long subset, schema /2."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.edges = [E("within", "training", "A", "F1", "A", "F1"), E("within", "training", "A", "F1", "A", "T2"),
                      E("within", "training", "A", "T2", "A", "T2"), E("within", "training", "A", "T2", "A", "F1"),
                      E("cross", "training", "A", "T2", "B", "T2"), E("cross", "test", "B", "T2", "B", "T2"),
                      E("nopred", "training", "A", "T2"), E("random", "training", "A", "T2", "random"),
                      E("reference", "training", "A", "T2", "B", "T2"),               # the same pair, another family
                      E("audit", "audit", "A", "T2", "B", "T2", namespace="audit"),
                      E("grid", "training", "B", "F1", "A", "F1", horizon="long")]

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_expand(self):
        rows, _, man = plan.expand_v2(design2(self.tmp, self.edges), pending=True)
        rows2, _, _ = plan.expand_v2(design2(self.tmp, self.edges), pending=True)
        self.assertEqual(b"".join(map(rqlib.canonical, rows)), b"".join(map(rqlib.canonical, rows2)))
        self.assertEqual(len(rows), 10 * 2)                       # 11 edges, one pair listed twice, x R
        self.assertTrue(all(r["schema"] == plan.PLAN_SCHEMA_V2 for r in rows))
        by = {r["id"]: r for r in rows}
        merged = by["A.T2~B.T2.common.frozen.k3.r00"]
        self.assertEqual(merged["families"], ["cross", "reference"])
        a1, a2 = by["A.T2~A.T2.common.frozen.k3.r01"], by["A.T2~A.F1.common.frozen.k3.r01"]
        fork, rnd = by["A.T2~none.common.frozen.k0.r01"], by["A.T2~random.common.frozen.k3.r01"]
        cross = by["A.T2~B.T2.common.frozen.k3.r01"]
        for x in (a2, fork, rnd, cross):                          # one prey snapshot x replicate: one key
            for k in ("sample", "ages", "reseed"):
                self.assertEqual(x["seeds"][k], a1["seeds"][k], (x["id"], k))
        self.assertNotEqual(a1["seeds"]["sample"], by["A.T2~A.T2.common.frozen.k3.r00"]["seeds"]["sample"])
        bb = by["B.T2~B.T2.common.frozen.k3.r01"]                 # one predator snapshot x replicate: one key
        self.assertEqual(bb["seeds"]["transplant"], cross["seeds"]["transplant"])
        self.assertNotEqual(bb["seeds"]["reseed"], cross["seeds"]["reseed"])
        self.assertEqual(a1["prey"]["snapshot"], plan.snapshot_uuid("uA", 2000))
        self.assertEqual(a2["predators"]["snapshot"], plan.snapshot_uuid("uA", 1))
        audit = by["A.T2~B.T2.common.frozen.k3.audit.r01"]       # an independent namespace
        for k in ("sample", "ages", "reseed", "transplant"):
            self.assertNotEqual(audit["seeds"][k], cross["seeds"][k], k)
        self.assertEqual((audit["role"], audit["namespace"]), ("audit", "audit"))
        self.assertEqual((bb["role"], fork["kind"], fork["predators"], fork["k"]), ("test", "nopred", None, 0))
        self.assertEqual(rnd["predators"], {"source": "random"})
        self.assertEqual(a1["sampling"], "wor-balanced")
        self.assertEqual(a1["ages"], {"path": f"{self.tmp}/ages.json", "sha256": "pending"})
        # every replicate of a pair has one horizon; the explicit long edge is long; the long subset is exact
        units = {}
        for r in rows:
            units.setdefault(r["unit"], set()).add((r["horizon"], r["steps"], tuple(r["horizons"])))
        self.assertTrue(all(len(v) == 1 for v in units.values()))
        grid = by["B.F1~A.F1.common.frozen.k3.r00"]
        self.assertEqual((grid["horizon"], grid["steps"], grid["horizons"]), ("long", 800, [400, 800]))
        free = 9      # the pairs without a fixed horizon
        self.assertEqual(man["units"], free)
        self.assertEqual(man["long"], int(0.25 * free + 0.5))
        self.assertEqual(sum(1 for u, v in units.items() if next(iter(v))[0] == "long"), man["long"] + 1)
        self.assertEqual(sum(s["long"] for s in man["per_stratum"]), man["long"])
        short = next(r for r in rows if r["horizon"] == "short")
        self.assertEqual((short["steps"], short["horizons"], short["expected"]["checkpoint_steps"]), (400, [400], [200, 400]))
        # seeds unique within a kind across groups
        for kind in plan.SEED_KINDS_V2:
            per = {}
            for r in rows:
                if r["groups"].get(kind):
                    per.setdefault(r["seeds"][kind], set()).add(r["groups"][kind])
            self.assertTrue(all(len(g) == 1 for g in per.values()), kind)

    def test_conflicts(self):
        bad = self.edges + [E("cross", "validation", "A", "T2", "B", "T2")]     # another role for one pair
        with self.assertRaisesRegex(plan.DesignError, "different content or roles"):
            plan.expand_v2(design2(self.tmp, bad), pending=True)
        bad = self.edges + [E("grid", "training", "B", "F1", "A", "F1", horizon="short")]
        with self.assertRaisesRegex(plan.DesignError, "two horizons"):
            plan.expand_v2(design2(self.tmp, bad), pending=True)
        with self.assertRaisesRegex(plan.DesignError, "role"):
            plan.expand_v2(design2(self.tmp, [E("x", "nonsense", "A", "F1")]), pending=True)
        with self.assertRaisesRegex(plan.DesignError, "first horizon"):
            plan.expand_v2(design2(self.tmp, self.edges, defaults={"short_steps": 400, "long_steps": 800,
                                   "short_horizons": [400], "long_horizons": [800], "log_every": 100,
                                   "checkpoint_every": 200}), pending=True)

    def test_final_binding_with_ages(self):
        for name, frame in (("A.F1", 1), ("A.2000", 2000), ("B.F1", 1), ("B.2000", 2000), ("T0", 7)):
            wr(os.path.join(self.tmp, name + ".json"), ckpt.dumps(mk_cp(n_prey=8, frame=frame)))
        src = mk_cp(n_prey=8, seed=9)
        ref = common.reference_ages([src], 4)
        wr(os.path.join(self.tmp, "ages.json"), rqlib.canonical(ref))
        d = design2(self.tmp, self.edges)
        pend, _, m1 = plan.expand_v2(d, pending=True)
        final, _, m2 = plan.expand_v2(d)
        self.assertEqual(m1, m2)
        self.assertEqual(plan.pending_problems(final, pend), [])
        a = next(r for r in final if r["ages"])
        self.assertEqual(a["ages"]["sha256"], rqlib.sha256_file(os.path.join(self.tmp, "ages.json")))
        wr(os.path.join(self.tmp, "ages.json"), rqlib.canonical(common.reference_ages([src], 5)))
        with self.assertRaisesRegex(plan.DesignError, "reference ages"):
            plan.expand_v2(d)
        p = os.path.join(self.tmp, "plan.jsonl")
        plan.write_plan(final, p)
        self.assertEqual(len(run.load_plan(p)), len(final))      # the runner reads plan/2 rows
        bad = [dict(final[0])]
        del bad[0]["role"]
        plan.write_plan(bad, p)
        with self.assertRaises(SystemExit):
            run.load_plan(p)

    def test_cli(self):
        p = os.path.join(self.tmp, "design.json")
        wr(p, json.dumps(design2(self.tmp, self.edges)))
        out, lm = os.path.join(self.tmp, "p.jsonl"), os.path.join(self.tmp, "long.json")
        self.assertEqual(plan.main([p, "--pending", "--out", out, "--long-manifest", lm]), 0)
        self.assertEqual(rqlib.read_json(lm)["long"], int(0.25 * 9 + 0.5))


if __name__ == "__main__":
    unittest.main()

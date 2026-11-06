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
        src = open(os.path.join(REPO, "src", "core", "agent_core.hpp")).read()
        for k, v in common.AGENT_DEFAULTS.items():
            m = re.search(r"float\s+" + k + r"\s*=\s*([0-9.]+)f\s*;", src)
            self.assertIsNotNone(m, k)
            self.assertEqual(float(m.group(1)), v, k)
        g = open(os.path.join(REPO, "src", "core", "genome.hpp")).read()
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
        self.assertEqual(common.POLICIES[0], "hybrid")
        self.assertEqual(plan.SAMPLINGS[0], "hybrid")

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

    def tearDown(self):
        shutil.rmtree(self.root)

    def mk_cell(self, cid, group="g1", csha="c" * 64, payload="x"):
        d = os.path.join(self.root, store.WORK, cid)
        os.makedirs(d)
        b = rqlib.canonical({"id": cid, "payload": payload})
        open(os.path.join(d, "bundle.json"), "wb").write(b)
        rqlib.write_json_durable(os.path.join(d, "done.json"), {
            "schema": run.DONE_SCHEMA, "id": cid, "kind": "assay", "bundle_sha256": rqlib.sha256_bytes(b),
            "row_sha256": "r" * 64, "common_group": group, "common_sha256": csha})
        open(os.path.join(d, "end.json"), "w").write("big")

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
        with open(chunk, "wb") as f:
            f.write(good)
        acts, probs = store.recover(self.root, log=lambda m: None, deep=False)
        self.assertEqual(probs, [])
        self.assertEqual(os.listdir(os.path.join(self.root, store.WORK)), [])
        self.assertEqual(sum("deleted the packed cell" in x for x in acts), 3)

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
        raw = open(ip, "rb").read()
        open(ip, "wb").write(raw[:-40])            # the second line torn
        self.mk_cell("c3", group="g1", csha="a" * 64)   # its cell directory is back (deleted after the commit)
        acts, probs = store.recover(self.root, log=lambda m: None)
        self.assertEqual(probs, [])
        self.assertTrue(any("chunk_000002.zip" in a for a in acts), acts)
        recs, cells = store.load_index(self.root)
        self.assertEqual(len(recs), 1)
        self.assertNotIn("c3", cells)
        self.assertTrue(open(ip, "rb").read().endswith(b"\n"))
        # a packed cell's leftover directory is deleted at recover (after its bundle is checked)
        os.makedirs(os.path.join(self.root, store.WORK, "c0"))
        open(os.path.join(self.root, store.WORK, "c0", "bundle.json"), "wb").write(
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
        b = bytearray(open(cp, "rb").read())
        b[40] ^= 1
        open(cp, "wb").write(bytes(b))
        self.assertTrue(store.verify_all(self.root))
        # a bundle that does not match its done record is refused
        open(os.path.join(self.root, store.WORK, "c9", "bundle.json"), "ab").write(b" ")
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


class TestProcesses(unittest.TestCase):
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

    def test_stop_groups_stopped_worker(self):
        """Review round 2, P2-7: a SIGSTOPped worker cannot act on SIGTERM; the bounded wait escalates
        to SIGKILL instead of hanging."""
        import signal
        import subprocess
        import time
        p = subprocess.Popen(["sleep", "60"], start_new_session=True)
        os.kill(p.pid, signal.SIGSTOP)
        t0 = time.monotonic()
        killed = run.stop_groups([p], grace=0.5)
        self.assertLess(time.monotonic() - t0, 8)
        self.assertEqual(killed, [p.pid])
        self.assertEqual(p.returncode, -signal.SIGKILL)


class TestRunner(unittest.TestCase):
    def test_bio_ledger(self):
        root = tempfile.mkdtemp()
        try:
            self.assertEqual(run.read_bio_ledger(root), [])
            run.append_bio_ledger(root, {"cell": "c", "role": "predators", "sha256": "a" * 64})
            with open(os.path.join(root, run.BIO_LEDGER), "a") as f:
                f.write('{"torn')                 # a crash while appending
            led = run.read_bio_ledger(root)
            self.assertEqual(len(led), 1)
            self.assertEqual(led[0]["schema"], run.BIO_SCHEMA)
            self.assertTrue(run.bio_match({"predators": {"sha256": "a" * 64}}, led))
            self.assertFalse(run.bio_match({"prey": {"sha256": "a" * 64}, "predators": None}, led))   # role-specific
        finally:
            shutil.rmtree(root)

    def test_live_floor_refused_at_planning(self):
        tmp = tempfile.mkdtemp()
        try:
            for name, frame, extra in (("A.F1", 1, {}), ("T0", 7, {"predatorMinPopulation": 2}),
                                       ("T1", 7, {"predatorMinPopulation": 0})):
                with open(os.path.join(tmp, name + ".json"), "w") as f:
                    f.write(ckpt.dumps(mk_cp(n_prey=8, frame=frame, cfg_extra=extra)))
            d = design(tmp, times={"F1": 1}, templates=[f"{tmp}/T0.json"],
                       blocks=[{"name": "l", "prey_worlds": ["A"], "prey_times": ["F1"], "predators": "same",
                                "predator_times": ["F1"], "replicates": 1, "with_nopred": True, "assay": "live"}])
            with self.assertRaisesRegex(plan.DesignError, "predatorMinPopulation 0"):
                plan.expand(d)
            d["templates"] = [f"{tmp}/T1.json"]
            rows, _ = plan.expand(d)
            self.assertEqual([r["kind"] for r in rows], ["assay", "nopred"])
            self.assertTrue(all(rqlib.is_sha256(r["template"]["sha256"]) for r in rows))
        finally:
            shutil.rmtree(tmp)


    def test_memory_and_disk_readings(self):
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(f"{tmp}/cg/a/b")
            open(f"{tmp}/meminfo", "w").write("MemTotal: 9000000 kB\nMemAvailable: 8000000 kB\n")
            open(f"{tmp}/proc_cgroup", "w").write("0::/a/b\n")
            open(f"{tmp}/cg/a/b/memory.max", "w").write("1073741824\n")
            open(f"{tmp}/cg/a/b/memory.current", "w").write("536870912\n")
            open(f"{tmp}/cg/a/memory.max", "w").write("max\n")
            os.environ.update(RQ_MEMINFO=f"{tmp}/meminfo", RQ_PROC_CGROUP=f"{tmp}/proc_cgroup",
                              RQ_CGROUP_ROOT=f"{tmp}/cg")
            self.assertEqual(run.mem_headroom_mb(), 512)
            open(f"{tmp}/cg/a/b/memory.max", "w").write("max\n")
            self.assertEqual(run.mem_headroom_mb(), 7812)
            open(f"{tmp}/cg/a/b/memory.max", "w").write("1073741824\n")
            open(f"{tmp}/cg/a/b/memory.current", "w").write("oops\n")
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


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""test_redqueen.py: unit tests of tools/redqueen that need no engine (stdlib unittest).

    python3 -I tools/redqueen/test_redqueen.py [-v]

The end-to-end tests against the real engine are tests/redqueen_tooling.sh (ctest).
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import unittest
import zipfile
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ckpt  # noqa: E402
import common  # noqa: E402
import plan  # noqa: E402
import rqlib  # noqa: E402
import run  # noqa: E402
import store  # noqa: E402
import cell  # noqa: E402
import score  # noqa: E402

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


def _r32(x):
    """Exact rational x (0, or positive in binary32's normal range) rounded to the nearest binary32,
    ties to even: an oracle that uses neither struct nor a C cast."""
    if x == 0:
        return Fraction(0)
    e = x.numerator.bit_length() - x.denominator.bit_length()
    if Fraction(2) ** e > x:
        e -= 1
    ulp = Fraction(2) ** (e - 23)
    q, r = divmod(x, ulp)
    if 2 * r > ulp or (2 * r == ulp and q % 2):
        q += 1
    return q * ulp


def _oracle_clock(start, steps, max_age=120.0, stop=False):
    """The engine's age law by exact rationals (D8 v2 rule 46): A_0 = binary32(start), A_{k+1} =
    round32(A_k + 0.016f), the literal rounded from its decimal -> (A after `steps` frames, or at the
    age death if stop, as a float; the first frame with A_k > binary32(max_age), or None)."""
    a, d, m = _r32(Fraction(start)), _r32(Fraction("0.016")), _r32(Fraction(max_age))
    death = None
    for k in range(1, steps + 1):
        a = _r32(a + d)
        if death is None and a > m:
            death = k
            if stop:
                break
    return float(a), death


def mk_age_score(horizons=(5000,), ages=(0.0,), alive=None, f0=100):
    """A synthetic score (no engine) whose horizons carry complete age summaries (score.age_strata):
    the initial cohort ids 7, 8, ... with start `ages`, all alive at every horizon unless alive =
    {horizon: set of ids}."""
    start = {7 + i: a for i, a in enumerate(ages)}
    hs = []
    for h in horizons:
        live = set(start) if alive is None else set(alive.get(h, ()))
        hs.append({"steps": h, "frame": f0 + h, "survivors": len(live),
                   "age_strata": score.age_strata(start, live, 120.0, h, f0 + h, score.DT, len(start), len(live))})
    return {"schema": score.SCHEMA, "n_start": len(start), "dt": score.DT, "horizons": hs}


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

    def test_age_clock_mirrors_the_engine_source(self):
        """D8 v2 rule 46: common's age clock is the engine's arithmetic: a binary32 age loaded by a
        (float) cast, += the 0.016f fixed step every frame, age death when the UPDATED age is strictly
        greater than the binary32 maxAge (starvation tested first), and no floating-point contraction."""
        rd = lambda *p: rqlib.read_text(os.path.join(REPO, *p))  # noqa: E731
        self.assertRegex(rd("src", "core", "agent_core.hpp"), r"\n\s*float age = 0\.0f;")
        k = rd("src", "core", "kernel.hpp")
        self.assertRegex(k, r"inline void stepMetabolism\(AgentCore& c, const SimConfig& cfg, float dt\) \{\s*"
                            r"c\.age \+= dt;")
        self.assertRegex(k, r"if \(c\.foodReserves <= 0\.0f\) return 's';\s*if \(c\.age > cfg\.maxAge\) return 'a';")
        self.assertRegex(rd("src", "core", "config.hpp"), r"float maxAge\s*= 120\.0f;")
        self.assertEqual(set(re.findall(r"const float fixedDt = ([0-9.]+)f;", rd("src", "app", "main.cpp"))), {"0.016"})
        j = rd("src", "core", "json_min.hpp")
        self.assertIn("out.push_back((float)e.num);", j)
        self.assertIn("(float)v->num", j)
        self.assertIn("add_compile_options(-ffp-contract=off)", rd("CMakeLists.txt"))
        self.assertEqual((common.ENGINE_DT, score.DT), (0.016, 0.016))


class TestAgeClock(unittest.TestCase):
    """D8 v2 rule 46 (Codex review of 870daa6, P2-1): common's binary32 age clock against an
    exact-rational oracle. Synthetic ages only (no study, bank or validation data)."""

    def setUp(self):
        common._CLOCKS.clear()

    def test_dt_and_rounding(self):
        self.assertEqual(common.binary32(0.016), float(_r32(Fraction("0.016"))))   # = the literal 0.016f
        self.assertEqual(common.binary32(0.016), 0.01600000075995922)
        for x in (0.0320000015, 11.999, 40.001, 119.999, 120.0, 1e-3):
            self.assertEqual(common.binary32(x), float(_r32(Fraction(x))), x)

    def test_rule46_boundary_is_feasible(self):
        """Rule 46's counterexample: 40.00001907348633 (the age after 2,500 additions from zero) reaches
        119.99422454833984 after 5,000 more and is feasible; the exact formula says 120.00002 > 120."""
        self.assertEqual(_oracle_clock(0.0, 2500), (40.00001907348633, None))
        self.assertEqual(_oracle_clock(40.00001907348633, 5000), (119.99422454833984, None))
        self.assertGreater(40.00001907348633 + 5000 * 0.016, 120.0)           # (what a + H dt <= 120 concludes)
        self.assertTrue(common.age_feasible(40.00001907348633, 5000, 120.0))
        # the review's case: start 40.001 (binary32 40.0009994506836) ends at 119.99520111083984
        self.assertEqual(_oracle_clock(40.001, 5000), (119.99520111083984, None))
        self.assertTrue(common.age_feasible(40.001, 5000, 120.0))
        # one clock: from zero, the age death comes exactly 2,500 frames after the death from its 2,500th age
        self.assertEqual(common.age_death_frame(0.0, 120.0, 20000),
                         2500 + common.age_death_frame(40.00001907348633, 120.0, 20000))

    def test_boundary_and_death_frames_match_the_oracle(self):
        """The 5k boundary between adjacent binary32 start ages, and death frames, agree with the oracle."""
        bits = lambda x: struct.unpack("<I", struct.pack("<f", x))[0]  # noqa: E731
        flt = lambda b: struct.unpack("<f", struct.pack("<I", b))[0]   # noqa: E731
        lo, hi = bits(30.0), bits(50.0)                       # (positive binary32 order = bit order)
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if common.age_feasible(flt(mid), 5000, 120.0) else (lo, mid)
        self.assertGreater(flt(lo), 40.00001907348633)
        self.assertIsNone(_oracle_clock(flt(lo), 5000)[1])
        self.assertEqual(_oracle_clock(flt(hi), 5000)[1], 5000)
        for a in (0.0, 12.25, 47.999, 119.99):
            self.assertEqual(common.age_death_frame(a, 120.0, 8000), _oracle_clock(a, 8000, stop=True)[1], a)

    def test_strictly_greater_and_frame_count(self):
        m = float(2 * _r32(Fraction("0.016")))                    # A_2 from zero, exactly
        self.assertEqual(common.age_death_frame(0.0, m, 10), 3)   # A_2 == maxAge lives; A_3 > maxAge dies
        self.assertEqual((common.age_feasible(0.0, 2, m), common.age_feasible(0.0, 3, m)), (True, False))
        self.assertEqual(common.age_death_frame(120.0, 120.0, 5), 1)
        self.assertTrue(common.age_feasible(120.0, 0, 120.0))     # (no frame yet, no age death)
        self.assertEqual(common.age_feasible_count([0.0, 40.0, 40.001, 47.999, 120.0], 5000, 120.0), 3)

    def test_cache_resumes_exactly(self):
        ages, hs = (0.0, 11.5, 40.001, 47.999), (20000, 5000, 7500, 7501, 1, 0)
        fresh = {}
        for h in hs:
            for a in ages:
                common._CLOCKS.clear()
                fresh[a, h] = common.age_death_frame(a, 120.0, h)
        common._CLOCKS.clear()
        for h in (1, 5000, 7501, 0, 20000, 7500, 5000):
            for a in ages:
                self.assertEqual(common.age_death_frame(a, 120.0, h), fresh[a, h], (a, h))

    def test_invalid_inputs(self):
        for args in ((float("nan"), 120.0, 5), (1.0, float("inf"), 5), (True, 120.0, 5), (1.0, 120.0, -1),
                     (1.0, 120.0, 2.5), (1.0, 1e39, 5), ("1", 120.0, 5)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                common.age_death_frame(*args)
        for dt in (0.0, -0.016):
            with self.assertRaises(ValueError):
                common.age_death_frame(1.0, 120.0, 5, dt=dt)

    @unittest.skipUnless(os.environ.get("RQ_FROZEN_AGES"), "RQ_FROZEN_AGES (the frozen config ages.json) not set")
    def test_frozen_age_reference_counts(self):
        """Rule 46's registered values for the frozen ages (rule 43; config, not outcomes): M_5000 = 247
        of 600, M_10000 = M_20000 = 0."""
        p = os.environ["RQ_FROZEN_AGES"]
        self.assertEqual(rqlib.sha256_file(p), "6ffb99ec4062801b68c462ab08208e8367d128ca820e0a9e84752f4403a717d5")
        ref = common.load_age_reference(p)
        self.assertEqual((ref["n"], ref["max_age"]), (600, 120.0))
        self.assertEqual([common.age_feasible_count(ref["ages"], h, ref["max_age"]) for h in (5000, 10000, 20000)],
                         [247, 0, 0])


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

    def mk_cell(self, cid, group="g1", csha="c" * 64, payload="x", transplant=None, sharing=True, role="training",
                done_role=None, done_tg=None, done_extra=None):
        """A finished cell (a /1 bundle; transplant (predator key, sha): a /2 bundle with its sharing
        record) whose done.json summaries are the bundle's, as run.py writes them (done_*: altered)."""
        d = os.path.join(self.root, store.WORK, cid)
        os.makedirs(d)
        cell_ = {"id": cid, "schema": run.PLAN_SCHEMA, "kind": "assay", "prey_policy": "common", "assay": "frozen",
                 "k": 6, "groups": {"common": group, "reseed": f"rs-{cid}"}, "seeds": {"reseed": 5}}
        bundle = {"schema": "finfolk.redqueen.bundle/1", "payload": payload, "cell": cell_,
                  "files": {"common.json": csha}, "arena_prey_config_sha256": "p" * 64}
        if transplant:
            cell_.update(schema=plan.PLAN_SCHEMA_V2, role=role, families=["f"])
            cell_["groups"]["transplant"] = transplant[0]
            cell_["seeds"]["transplant"] = 7
            bundle["schema"] = store.BUNDLE_V2
            if sharing:
                bundle["sharing"] = {"schema": store.SHARING_SCHEMA, "keys": cell_["groups"], "seeds": cell_["seeds"],
                                     "realized": {"common_sha256": csha, "transplant_realized_sha256": transplant[1]}}
        done = dict(store.summary_of(bundle), schema=run.DONE_SCHEMA, id=cid)
        if transplant:
            done.update(transplant_group=done_tg or f"{transplant[0]}|k6", transplant_realized_sha256=transplant[1],
                        role=done_role or role, families=["f"])
        done.update(done_extra or {})
        b = rqlib.canonical(bundle)
        wr(os.path.join(d, "bundle.json"), b)
        done["bundle_sha256"] = rqlib.sha256_bytes(b)
        rqlib.write_json_durable(os.path.join(d, "done.json"), done)
        wr(os.path.join(d, "end.json"), "big")
        return b

    def test_transplant_groups(self):
        """Design v4 §3.5: one transplant group (a predator snapshot x replicate x K) realizes one donor
        draw and placement; a disagreement is refused at packing (within a pack and against the index)."""
        self.mk_cell("t1", group="g1", transplant=("P.w01.t5|r00", "d" * 64))
        self.mk_cell("t2", group="g2", csha="b" * 64, transplant=("P.w01.t5|r00", "d" * 64))
        self.mk_cell("t3", group="g3", csha="e" * 64, transplant=("P.w02.t5|r00", "f" * 64))
        store.pack(self.root, log=lambda m: None)
        recs, cells = store.load_index(self.root)
        self.assertEqual(cells["t1"][1]["transplant_group"], "P.w01.t5|r00|k6")
        self.assertEqual(store.transplant_groups(cells), {"P.w01.t5|r00|k6": "d" * 64, "P.w02.t5|r00|k6": "f" * 64})
        self.mk_cell("t4", group="g4", csha="9" * 64, transplant=("P.w01.t5|r00", "0" * 64))
        with self.assertRaisesRegex(store.StoreError, "transplant group P.w01.t5.r00.k6 realized"):
            store.pack(self.root, log=lambda m: None)
        self.assertTrue(os.path.exists(os.path.join(self.root, store.WORK, "t4", "bundle.json")))

    def test_v2_completions_checked(self):
        """Review of 03a608b, P2 1: packing (and resume) require a /2 completion's sharing record and
        cross-check done.json's role and transplant summary against the hash-valid bundle; a /2 bundle
        without sharing records (completed before 03a608b) is refused, never mixed in."""
        for cid, kw, msg in (("old", {"sharing": False}, "before 03a608b"),
                             ("role", {"done_role": "test"}, "role / families"),
                             ("tg", {"done_tg": "P.w09.t5|r00|k6"}, "transplant group")):
            self.mk_cell(cid, group=f"g{cid}", csha=rqlib.sha256_bytes(cid.encode()),
                         transplant=("P.w01.t5|r00", "d" * 64), **kw)
            with self.assertRaisesRegex(store.StoreError, msg):
                store.pack(self.root, ids=[cid], log=lambda m: None)
            shutil.rmtree(os.path.join(self.root, store.WORK, cid))
        self.mk_cell("ok", transplant=("P.w01.t5|r00", "d" * 64))
        self.assertEqual(store.pack(self.root, log=lambda m: None)[1], 1)
        _, cells = store.load_index(self.root)
        self.assertEqual(cells["ok"][1]["role"], "training")
        b1 = json.loads(self.mk_cell("v1"))                                       # a consistent /1 completion
        self.assertEqual(store.completion_problems(rqlib.read_json(os.path.join(self.root, store.WORK, "v1",
                                                                                "done.json")), b1), [])

    # ---------------------------------------------------------------- review of d4dc4b7
    def test_altered_summaries_refused(self):
        """Review of d4dc4b7, P2 1: every done.json summary is checked against the bundle at packing:
        a common checkpoint hash changed to the one already indexed for its group (hiding another
        bundled common checkpoint), a pair group, prey settings, kind, row hash: each refused."""
        self.mk_cell("a0", group="g1", csha="a" * 64)
        store.pack(self.root, log=lambda m: None)
        for cid, extra, field in (("x1", {"common_sha256": "a" * 64}, "common_sha256"),
                                  ("x2", {"pair_group": "rs-a0|common|frozen"}, "pair_group"),
                                  ("x3", {"prey_config_sha256": "q" * 64}, "prey_config_sha256"),
                                  ("x4", {"kind": "nopred"}, "kind"),
                                  ("x5", {"row_sha256": "r" * 64}, "row_sha256")):
            self.mk_cell(cid, group="g1", csha="b" * 64, done_extra=extra)    # its bundle built "b..."
            with self.assertRaisesRegex(store.StoreError, field):
                store.pack(self.root, ids=[cid], log=lambda m: None)
            self.assertTrue(os.path.exists(os.path.join(self.root, store.WORK, cid, "bundle.json")))
            shutil.rmtree(os.path.join(self.root, store.WORK, cid))
        # the /2 sharing record's realized common checkpoint must be the bundle's too
        d = os.path.join(self.root, store.WORK, "x6")
        self.mk_cell("x6", group="g6", csha="6" * 64, transplant=("P.w01.t5|r00", "d" * 64))
        b = json.loads(rqlib.read_bytes(os.path.join(d, "bundle.json")))
        b["sharing"]["realized"]["common_sha256"] = "7" * 64
        self.assertTrue(any("realized common" in x for x in store.completion_problems(
            rqlib.read_json(os.path.join(d, "done.json")), b)))

    def legacy_root(self):
        """A root holding a /2 completion packed before 03a608b: no sharing record in its bundle, no
        bundle schema or transplant summary in its index entry."""
        self.mk_cell("old", group="g1", transplant=("P.w01.t5|r00", "d" * 64), sharing=False)
        real = store.completion_problems
        store.completion_problems = lambda done, bundle: []
        try:
            store.pack(self.root, log=lambda m: None)
        finally:
            store.completion_problems = real
        ip = os.path.join(self.root, store.INDEX)
        recs = [json.loads(ln) for ln in rqlib.read_text(ip).splitlines() if ln.strip()]
        for r in recs:
            for e in r["cells"].values():
                for k in ("bundle_schema", "transplant_group", "transplant_realized_sha256", "role"):
                    e.pop(k, None)
        rqlib.write_durable(ip, b"".join(rqlib.canonical(r) for r in recs))

    def test_legacy_packed_cell_refuses_extension(self):
        """Review of d4dc4b7, P2 1: a root holding a legacy /2 completion (packed without sharing
        records) is refused whatever plan extends it: a disjoint cell is not packed next to it, and
        the runner refuses the root at its start (before any plan row is looked at)."""
        self.legacy_root()
        probs = store.index_problems(self.root)
        self.assertTrue(any("old" in x and "sharing record" in x for x in probs), probs)
        self.mk_cell("new", group="g2", csha="b" * 64, transplant=("P.w02.t5|r00", "f" * 64))   # disjoint
        with self.assertRaisesRegex(store.StoreError, "cannot be extended"):
            store.pack(self.root, log=lambda m: None)
        self.assertTrue(os.path.exists(os.path.join(self.root, store.WORK, "new", "bundle.json")))
        p = os.path.join(self.root, "disjoint.jsonl")
        wr(p, "")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = run.main(["--root", self.root, "--plan", p, "--binary", "/nonexistent/evo_boids"])
        self.assertEqual(rc, 2, err.getvalue())
        self.assertIn("rerun the study in a new root", err.getvalue())
        # an index entry that names a group without its realized draw (or a /2 assay without either)
        rec = {"chunk": "x"}
        for e in ({"transplant_group": "g|k6", "transplant_realized_sha256": None},
                  {"bundle_schema": store.BUNDLE_V2, "kind": "assay", "transplant_group": None}):
            with self.assertRaisesRegex(store.StoreError, "without its group or realized draw"):
                store.transplant_groups({"c": (rec, e)})

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
        self.assertEqual(json.loads(store.read_member(self.root, "c1", cells=cells))["cell"]["id"], "c1")
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
        c0 = store.read_member(self.root, "c0")
        os.makedirs(os.path.join(self.root, store.WORK, "c0"))
        wr(os.path.join(self.root, store.WORK, "c0", "bundle.json"), c0)
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


class TestSharing(unittest.TestCase):
    def test_sharing_record(self):
        """Design v4 §3.5: a plan/2 bundle records its group keys, seeds and realized draws."""
        arena = mk_cp(n_pred=3)
        man = {"predators": {"source": "pred.json", "seed": 77, "pool": 6, "count": 3, "withReplacement": False,
                             "picked": [{"sourceIndex": 5, "sourceId": 6, "lineageId": 6, "id": 7},
                                        {"sourceIndex": 1, "sourceId": 2, "lineageId": 2, "id": 8},
                                        {"sourceIndex": 0, "sourceId": 1, "lineageId": 1, "id": 9}]}}
        c = {"groups": {"common": "pk", "transplant": "qk"}, "seeds": {"sample": 1, "transplant": 77}}
        files = {"common.json": "c" * 64, "common.manifest.json": "m" * 64}
        a = cell.sharing_record(c, arena, man, files)
        self.assertEqual(a["schema"], cell.SHARING_SCHEMA)
        self.assertEqual((a["keys"], a["seeds"]), (c["groups"], c["seeds"]))
        self.assertEqual(a["realized"]["transplant"]["picked"], [[5, 6, 6], [1, 2, 2], [0, 1, 1]])
        self.assertEqual(a["realized"]["common_sha256"], "c" * 64)
        self.assertEqual(a, cell.sharing_record(c, copy.deepcopy(arena), copy.deepcopy(man), files))
        moved = copy.deepcopy(arena)
        moved["predators"]["posX"][0] += 1.0            # another placement: another realized transplant
        b = cell.sharing_record(c, moved, man, files)
        self.assertEqual(b["realized"]["transplant_draw_sha256"], a["realized"]["transplant_draw_sha256"])
        self.assertNotEqual(b["realized"]["transplant_realized_sha256"], a["realized"]["transplant_realized_sha256"])
        other = copy.deepcopy(man)
        other["predators"]["picked"][0]["sourceIndex"] = 4    # another donor
        self.assertNotEqual(cell.sharing_record(c, arena, other, files)["realized"]["transplant_draw_sha256"],
                            a["realized"]["transplant_draw_sha256"])
        self.assertEqual(cell.sharing_record(c, mk_cp(n_pred=0), {}, files)["realized"]["transplant"]["picked"], [])


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


class TestScripted(unittest.TestCase):
    """Codex #74 r1 P2-4: score.py --scripted verifies the scripted (Stage A) mode from its inputs: the arena and
    every horizon checkpoint version 1, brain and economy off, K hunters, no predators.csv; captures are the
    predation-death counter's difference from a NONZERO loaded baseline."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.arena = mk_cp(n_prey=6, n_pred=3, version=1, frame=100)
        self.arena["counters"].update(totalDeathsPredation=5, totalDeaths=8, totalPredatorBirths=4,
                                      totalPredatorDeathsStarvation=3)          # (the loaded world's history)
        self.end = mk_cp(n_prey=6, n_pred=3, version=1, frame=300)
        self.end["counters"] = dict(self.arena["counters"], totalDeathsPredation=7, totalDeaths=10)
        self.end["creatures"]["alive"][0] = self.end["creatures"]["alive"][1] = 0     # (two eaten)

    def tearDown(self):
        shutil.rmtree(self.d)

    def write(self, arena=None, end=None):
        for name, cp in (("arena.json", arena or self.arena), ("end.300.json", end or self.end)):
            with open(os.path.join(self.d, name), "w") as f:
                f.write(ckpt.dumps(cp))

    def score(self, k=3):
        import score
        return score.score(self.d, k, 200, [200], 100, "frozen", scripted=True)

    def test_scripted_inputs_verified(self):
        import score
        self.write()
        s = self.score()
        h = s["horizons"][0]
        self.assertEqual((h["captures"], h["deaths_predation"], h["survivors"], h["predators"]), (2, 2, 4, 3))
        self.assertAlmostEqual(h["predator_seconds"], 3 * 200 * score.DT)
        self.assertEqual((s["scripted"], s["checks"]["rows"], s["checks"]["predation_deaths_equal_captures"]),
                         (True, None, "by construction (scripted)"))
        neural = mk_cp(n_prey=6, n_pred=3, version=2, frame=100)          # (brains: version 2, predatorBrain on)
        neural["counters"] = dict(self.arena["counters"])
        neural_end = mk_cp(n_prey=6, n_pred=3, version=2, frame=300)
        neural_end["counters"] = dict(self.end["counters"])
        econ = copy.deepcopy(self.arena)
        econ["config"]["predatorEconomy"] = True
        for arena, end, msg in ((neural, None, "format version 2"), (neural, None, "predatorBrain on"),
                                (econ, None, "predatorEconomy on"), (None, neural_end, "end.300.json is format version"),
                                (None, dict(self.end, config=dict(self.end["config"], predatorEconomy=True)),
                                 "end.300.json has predatorEconomy on")):
            self.write(arena, end)
            with self.assertRaisesRegex(score.ScoreError, msg):
                self.score()
        self.write()
        with self.assertRaisesRegex(score.ScoreError, "K = 4"):
            self.score(k=4)
        with open(os.path.join(self.d, "run.predators.csv"), "w") as f:         # (a neural metrics file)
            f.write("step,predator_pop\n200,3\n300,3\n")
        with self.assertRaisesRegex(score.ScoreError, "neural metrics file"):
            self.score()
        os.remove(os.path.join(self.d, "run.predators.csv"))
        bud = copy.deepcopy(self.end)                                          # (a predator birth: not fixed)
        bud["counters"]["totalPredatorBirths"] += 1
        self.write(end=bud)
        with self.assertRaisesRegex(score.ScoreError, "predator counter changes"):
            self.score()


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


BINDING = {"graph_edges_sha256": "g" * 64, "registry_sha256": "r" * 64, "max_restarts": 8, "burn_in_frame": 0}


def plan_mask(tmp, design, snaps, frames=(1, 2000)):
    """A graph.py mask /2 of design2's worlds (attempt 0) bound to BINDING: snaps {"W:frame": (status, why,
    valid_before)}; every other frame in `frames` whose file exists is available with its bytes' sha256."""
    b = design["availability"]
    ws, S = {}, {}
    for wn in ("A", "B"):
        u = design["worlds"][wn]["uuid"]
        vb = next((v[2] for k, v in snaps.items() if k.split(":")[0] == wn and v[0] == "biological"), None)
        av = {}
        for f in frames:
            p = os.path.join(tmp, f"{wn}.F1.json" if f == 1 else f"{wn}.{f}.json")
            if f"{wn}:{f}" not in snaps and os.path.isfile(p):
                av[str(f)] = rqlib.sha256_file(p)
        # (the mask's own evidence, as graph.py mask writes it: a settled disposition, the first terminal boundary
        #  at valid_before, the frontier; Codex #77 r2 P1-2)
        ws[wn] = {"uuid": u, "attempt": 0, "attempt_uuid": plan.attempt_uuid(u, 0), "valid_before": vb,
                  "first_terminal": {"frame": vb, "kind": "prey"} if vb else None, "frontier": vb or max(frames),
                  "refill": None, "burn_in": {"decided": True, "disposition": "no_rule", "why": "no burn-in rule"},
                  "prior_attempts": [],
                  "available_sha256": av}
    for k, (st, why, vb) in snaps.items():
        wn, f = k.split(":")[0], int(k.split(":")[1])
        S[k] = {"world": wn, "frame": f, "status": st, "why": why, "uuid": ws[wn]["uuid"], "attempt": 0,
                "snapshot": plan.snapshot_uuid(ws[wn]["uuid"], f), "valid_before": vb}
    return {"schema": plan.MASK_SCHEMA, "graph": {"edges_sha256": b["graph_edges_sha256"]},
            "registry": {"sha256": b["registry_sha256"], "max_restarts": b["max_restarts"],
                         "burn_in_frame": b["burn_in_frame"]},
            "block": {"sha256": "b" * 64, "registry_sha256": b["registry_sha256"]}, "worlds": ws, "snapshots": S}


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
        # (review of d4dc4b7, P3) at an exact CDF jump ((i + 0.5) M / N an integer) the UPPER order
        # statistic: M = 4 pooled ages, N = 2 -> ranks 1 and 3 (the lower convention would give 0, 2)
        one = mk_cp(n_prey=4, seed=5)
        one["creatures"]["age"] = [0.0, 10.0, 20.0, 30.0]
        one["config"]["maxAge"] = 120.0
        self.assertEqual(common.reference_ages([one], 2)["ages"], [10.0, 30.0])
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

    def test_source_endpoints_are_exact(self):
        """Codex #74 r1 P2-3: a predator source is exactly {source: random} or {source: scripted}: mixed with a
        world / time (which would fall through to a neural donor and lose the source) or unknown, it is refused;
        scripted hunters are never live (P3)."""
        S = lambda p, **kw: dict(E("scripted", "training", "A", "T2"), predators=p, **kw)  # noqa: E731
        rows, _, _ = plan.expand_v2(design2(self.tmp, [S({"source": "scripted"})]), pending=True)
        self.assertEqual([r["predators"] for r in rows], [{"source": "scripted"}] * 2)
        self.assertTrue(all(r["groups"]["transplant"].endswith(f"|scripted-k3|r{r['replicate']:02d}") for r in rows))
        for p in ({"source": "scripted", "world": "B", "time": "T2"}, {"source": "random", "world": "B", "time": "T2"},
                  {"source": "neural"}, {"source": "neural", "world": "B", "time": "T2"}, {"source": "scripted", "k": 3}):
            with self.assertRaisesRegex(plan.DesignError, "exactly"):
                plan.expand_v2(design2(self.tmp, [S(p)]), pending=True)
        with self.assertRaisesRegex(plan.DesignError, "never live"):
            plan.expand_v2(design2(self.tmp, [S({"source": "scripted"}, assay="live")]), pending=True)
        rows, _, _ = plan.expand_v2(design2(self.tmp, [S({"source": "scripted"}, assay="frozen-newborn")]), pending=True)
        self.assertEqual({r["assay"] for r in rows}, {"frozen-newborn"})

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
        with self.assertRaisesRegex(plan.DesignError, "keeps one role"):
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

    # ---------------------------------------------------------------- review of 03a608b
    def test_audit_namespace(self):
        """P2 2: an audit edge (its control too) defaults to an independent namespace; "main" is refused."""
        edges = [E("cross", "training", "A", "T2", "B", "T2"), E("audit", "audit", "A", "T2", "B", "T2"),
                 E("audit", "audit", "A", "T2")]
        rows, _, _ = plan.expand_v2(design2(self.tmp, edges), pending=True)
        by = {r["id"]: r for r in rows}
        prod, aud = by["A.T2~B.T2.common.frozen.k3.r00"], by["A.T2~B.T2.common.frozen.k3.audit.r00"]
        ctl = by["A.T2~none.common.frozen.k0.audit.r00"]
        self.assertEqual((aud["namespace"], ctl["namespace"]), ("audit", "audit"))
        for k in ("sample", "ages", "reseed", "transplant"):
            self.assertNotEqual(prod["seeds"][k], aud["seeds"][k], k)
        self.assertEqual(ctl["seeds"]["reseed"], aud["seeds"]["reseed"])
        with self.assertRaisesRegex(plan.DesignError, "independent namespace"):
            plan.expand_v2(design2(self.tmp, [E("audit", "audit", "A", "T2", namespace="main")]), pending=True)

    def test_seed_collisions_refused(self):
        """P2 3: a 32-bit collision between two groups is refused (never re-derived per plan), and a
        joint check finds a seed shared across plans (an audit against production)."""
        real = rqlib.derive_seed
        try:
            plan.rqlib.derive_seed = lambda ns, kind, *rest: 42 if kind == "reseed" else real(ns, kind, *rest)
            with self.assertRaisesRegex(plan.DesignError, "reseed seeds of groups .* collide"):
                plan.expand_v2(design2(self.tmp, self.edges), pending=True)
        finally:
            plan.rqlib.derive_seed = real
        prod, _, _ = plan.expand_v2(design2(self.tmp, [E("cross", "training", "A", "T2", "B", "T2")]), pending=True)
        aud, _, _ = plan.expand_v2(design2(self.tmp, [E("audit", "audit", "A", "T2", "B", "T2")]), pending=True)
        self.assertEqual(plan.joint_seed_problems(prod, aud), [])
        bad = json.loads(json.dumps(aud))
        bad[0]["seeds"]["reseed"] = prod[0]["seeds"]["reseed"]
        self.assertTrue(any("shared by groups" in p for p in plan.joint_seed_problems(prod, bad)))
        p1, p2 = os.path.join(self.tmp, "prod.jsonl"), os.path.join(self.tmp, "aud.jsonl")
        plan.write_plan(prod, p1)
        plan.write_plan(bad, p2)
        d = os.path.join(self.tmp, "d.json")
        wr(d, json.dumps(design2(self.tmp, [E("cross", "training", "A", "T2", "B", "T2")])))
        self.assertEqual(plan.main([d, "--pending", "--out", os.path.join(self.tmp, "x.jsonl"), "--joint", p2]), 2)
        self.assertEqual(plan.main([d, "--pending", "--out", os.path.join(self.tmp, "x.jsonl"), "--joint", p1]), 0)

    def test_joint_is_one_seed_universe(self):
        """Review of d4dc4b7, new P2: repeated --joint plans and the generated rows are ONE seed
        universe: an external-file-versus-external-file collision (production 42, audit 42) is refused
        although neither file collides with the generated plan alone."""
        new, _, _ = plan.expand_v2(design2(self.tmp, [E("random", "training", "A", "F1", "random")]), pending=True)
        prod, _, _ = plan.expand_v2(design2(self.tmp, [E("cross", "training", "A", "T2", "B", "T2")]), pending=True)
        aud, _, _ = plan.expand_v2(design2(self.tmp, [E("audit", "audit", "B", "T2", "A", "T2")]), pending=True)
        for r in prod + aud:                         # one reseed group of each file gets the seed 42
            if r["groups"]["reseed"].endswith("|r00"):
                r["seeds"]["reseed"] = 42
        self.assertEqual(plan.joint_seed_problems(new, prod), [])
        self.assertEqual(plan.joint_seed_problems(new, aud), [])
        p1, p2 = os.path.join(self.tmp, "prod.jsonl"), os.path.join(self.tmp, "aud.jsonl")
        plan.write_plan(prod, p1)
        plan.write_plan(aud, p2)
        d = os.path.join(self.tmp, "d.json")
        wr(d, json.dumps(design2(self.tmp, [E("random", "training", "A", "F1", "random")])))
        out = os.path.join(self.tmp, "x.jsonl")
        for files in ([p1], [p2]):
            self.assertEqual(plan.main([d, "--pending", "--out", out] + [x for f in files for x in ("--joint", f)]), 0)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = plan.main([d, "--pending", "--out", out, "--joint", p1, "--joint", p2])
        self.assertEqual(rc, 2)
        self.assertIn("reseed seed 42 is shared by groups", err.getvalue())

    def test_canonical_pairs_and_condition_roles(self):
        """P2 4: two labels of one snapshot merge into one pair (aliases recorded); one endpoint pair
        keeps one role across condition versions, but an explicit support exception."""
        edges = [E("cross", "training", "A", "T2", "B", "T2"), E("reference", "training", "A", "T2b", "B", "T2")]
        d = design2(self.tmp, edges, times={"F1": 1, "T1": 1000, "T2": 2000, "T2b": 2000})
        rows, _, _ = plan.expand_v2(d, pending=True)
        self.assertEqual(len(rows), 2)                          # one pair x R
        self.assertEqual((rows[0]["unit"], rows[0]["aliases"]), ("A.T2b~B.T2.common.frozen.k3", ["A.T2~B.T2.common.frozen.k3"]))
        self.assertEqual(rows[0]["families"], ["cross", "reference"])
        live = edges[:1] + [E("cross", "test", "A", "T2", "B", "T2", assay="live")]
        with self.assertRaisesRegex(plan.DesignError, "keeps one role"):
            plan.expand_v2(design2(self.tmp, live), pending=True)
        ok = edges[:1] + [E("cross", "support", "A", "T2", "B", "T2", assay="live", support_exception=True)]
        rows, _, _ = plan.expand_v2(design2(self.tmp, ok), pending=True)
        self.assertEqual(sorted({r["role"] for r in rows}), ["support", "training"])
        with self.assertRaisesRegex(plan.DesignError, "support_exception"):
            plan.expand_v2(design2(self.tmp, [E("cross", "test", "A", "T2", "B", "T2", support_exception=True)]),
                           pending=True)

    def test_primary_stratum_order_independent(self):
        """P2 5: a merged pair's stratum is its primary family (registered priority, then name), so
        reordering the edge list changes nothing."""
        lg = {"fraction": 0.5, "strata": ["family"], "family_priority": ["reference"]}
        edges = [dict(e, edge=f"e{i:02d}") for i, e in enumerate(self.edges)]
        a, _, ma = plan.expand_v2(design2(self.tmp, edges, long=lg), pending=True)
        b, _, mb = plan.expand_v2(design2(self.tmp, list(reversed(edges)), long=lg), pending=True)
        self.assertEqual(b"".join(map(rqlib.canonical, a)), b"".join(map(rqlib.canonical, b)))
        self.assertEqual(ma, mb)
        merged = next(r for r in a if r["unit"] == "A.T2~B.T2.common.frozen.k3")
        self.assertEqual(merged["primary_family"], "reference")

    def test_mixed_plans_and_manifest(self):
        """P2 6: a plan mixing /1 and /2 rows is refused; P3 7: the long manifest is written only for
        an accepted plan and names its sha256; P3 8: the snapshot UUID's fixed test vector."""
        rows, _, _ = plan.expand_v2(design2(self.tmp, self.edges), pending=True)
        for r in rows:                                   # (as if final: no pending hash)
            for k in ("prey", "predators", "template", "ages"):
                if isinstance(r.get(k), dict) and r[k].get("sha256") == "pending":
                    r[k]["sha256"] = "a" * 64
        one = dict(rows[0], schema=run.PLAN_SCHEMA, id="legacy")
        p = os.path.join(self.tmp, "mixed.jsonl")
        wr(p, rqlib.canonical(rows[0]) + rqlib.canonical(one))
        with self.assertRaisesRegex(SystemExit, "one schema"):
            run.load_plan(p)
        d = os.path.join(self.tmp, "d.json")
        wr(d, json.dumps(design2(self.tmp, self.edges)))
        pend, man = os.path.join(self.tmp, "pend.jsonl"), os.path.join(self.tmp, "long.json")
        self.assertEqual(plan.main([d, "--pending", "--out", pend, "--long-manifest", man]), 0)
        self.assertEqual(rqlib.read_json(man)["plan_sha256"], rqlib.sha256_file(pend))
        before = rqlib.read_bytes(man)
        for name, frame in (("A.F1", 1), ("A.2000", 2000), ("B.F1", 1), ("B.2000", 2000), ("T0", 7)):
            wr(os.path.join(self.tmp, name + ".json"), ckpt.dumps(mk_cp(n_prey=8, frame=frame)))
        wr(os.path.join(self.tmp, "ages.json"), rqlib.canonical(common.reference_ages([mk_cp(n_prey=8, seed=9)], 4)))
        wr(d, json.dumps(design2(self.tmp, self.edges[:-1])))              # a changed design (final inputs exist)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = plan.main([d, "--against", pend, "--out", os.path.join(self.tmp, "f.jsonl"), "--long-manifest", man])
        self.assertEqual(rc, 2)
        self.assertIn(f"not the registered pending plan {pend}", err.getvalue())   # refused AT --against
        self.assertEqual(rqlib.read_bytes(man), before)                     # untouched by the refused plan
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "f.jsonl")))
        self.assertEqual(plan.snapshot_uuid("00000000-0000-4000-8000-000000000001", 1000000),
                         "be3bbb37-f696-572c-b70c-5afcfaa9686d")

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
        # (review of d4dc4b7, P3) final planning checks the reference's maxAge against the template's
        wr(os.path.join(self.tmp, "ages.json"),
           rqlib.canonical(common.reference_ages([mk_cp(n_prey=8, seed=9, cfg_extra={"maxAge": 60.0})], 4)))
        with self.assertRaisesRegex(plan.DesignError, "maxAge 60.0"):
            plan.expand_v2(d)
        wr(os.path.join(self.tmp, "ages.json"), rqlib.canonical(ref))
        p = os.path.join(self.tmp, "plan.jsonl")
        plan.write_plan(final, p)
        self.assertEqual(len(run.load_plan(p)), len(final))      # the runner reads plan/2 rows
        bad = [dict(final[0])]
        del bad[0]["role"]
        plan.write_plan(bad, p)
        with self.assertRaises(SystemExit):
            run.load_plan(p)

    def test_exclusions_and_reconciliation(self):
        """PR-C (Annex H D6 rule 27; Codex #77 r1 P1-2): the final plan against the registered pending plan with an
        availability mask BOUND to the registered intent: the cells of an unavailable snapshot (B at T2: its
        world's first zero came before it, and its file is gone) are left out with a receipt; every executable
        cell is the pending one with its hashes filled (seeds, groups, long-subset membership unchanged) and reads
        the bytes the mask verified; nothing else is omitted; without the mask the missing file is an error, never
        a silent deletion. A mask with the SAME world names but another graph, registry, uuid or attempt, an
        unsupported biological exclusion, a design without its binding, or bytes the mask did not verify: refused."""
        for name, frame in (("A.F1", 1), ("A.2000", 2000), ("B.F1", 1), ("B.2000", 2000), ("T0", 7)):
            wr(os.path.join(self.tmp, name + ".json"), ckpt.dumps(mk_cp(n_prey=8, frame=frame)))
        wr(os.path.join(self.tmp, "ages.json"), rqlib.canonical(common.reference_ages([mk_cp(n_prey=8, seed=9)], 4)))
        dd = design2(self.tmp, self.edges, availability=BINDING)
        d = os.path.join(self.tmp, "d.json")
        wr(d, json.dumps(dd))
        pend = os.path.join(self.tmp, "pend.jsonl")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(plan.main([d, "--pending", "--out", pend]), 0)
        prow = {json.loads(ln)["id"]: json.loads(ln) for ln in rqlib.read_text(pend).splitlines() if ln}
        mask = plan_mask(self.tmp, dd, {"B:2000": ("biological", "at or after the world's first guild zero (frame 1500)", 1500)})
        os.remove(os.path.join(self.tmp, "B.2000.json"))
        mp, out, rec = (os.path.join(self.tmp, f) for f in ("mask.json", "exec.jsonl", "recon.json"))
        wr(mp, json.dumps(mask))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(plan.main([d, "--against", pend, "--exclusions", mp, "--reconciliation", rec, "--out", out]),
                             0, err.getvalue())
        R = rqlib.read_json(rec)
        rows = {json.loads(ln)["id"]: json.loads(ln) for ln in rqlib.read_text(out).splitlines() if ln}
        hit = {i for i, r in prow.items() if any(isinstance(r.get(k), dict) and r[k].get("world") == "B"
                                                 and r[k].get("frame") == 2000 for k in ("prey", "predators"))}
        self.assertEqual(len(hit), 6)                                   # (3 pairs x R = 2)
        self.assertEqual((R["scheduled"], R["executable"], R["excluded"]),
                         (len(prow), len(prow) - 6, {"biological": 6, "technical": 0, "pending": 0}))
        self.assertEqual(set(rows), set(prow) - hit)
        self.assertEqual({x["id"] for x in R["rows"]}, hit)
        self.assertTrue(all((x["status"], x["world"], x["frame"]) == ("biological", "B", 2000) for x in R["rows"]))
        for i, r in rows.items():                                       # (the registered cell, hashes filled)
            self.assertEqual(plan._masked(r), prow[i])
            self.assertNotEqual(r["prey"]["sha256"], rqlib.SHA_PENDING)
        self.assertEqual((R["plan_sha256"], R["mask"]["sha256"], R["pending_plan"]["sha256"]),
                         (rqlib.sha256_file(out), rqlib.sha256_file(mp), rqlib.sha256_file(pend)))
        self.assertEqual((R["binding"], R["mask"]["attempts"]["B"]["attempt_uuid"]), (BINDING, "uB"))
        self.assertEqual(R["by_role"]["test"]["biological"], 2)        # (B.T2 x B.T2, the test pair)

        def refused(m, design=None, why=""):
            wr(mp, json.dumps(m))
            dp = d
            if design is not None:
                dp = os.path.join(self.tmp, "d2.json")
                wr(dp, json.dumps(design))
            e = io.StringIO()
            with contextlib.redirect_stderr(e):
                self.assertEqual(plan.main([dp, "--against", pend, "--exclusions", mp, "--reconciliation", rec,
                                            "--out", out + ".bad"]), 2, why)
            self.assertFalse(os.path.exists(out + ".bad"), why)
            return e.getvalue()
        W = mask["worlds"]
        self.assertIn("another graph", refused(dict(mask, graph={"edges_sha256": "h" * 64}), why="graph"))
        self.assertIn("another registry", refused(dict(mask, registry=dict(mask["registry"], sha256="s" * 64)), why="reg"))
        self.assertIn("another registry", refused(dict(mask, block=dict(mask["block"], registry_sha256="s" * 64)), why="blk"))
        self.assertIn("uuid is not the design's", refused(dict(mask, worlds=dict(W, B=dict(W["B"], uuid="uZ"))), why="uuid"))
        self.assertIn("not a registered attempt", refused(dict(mask, worlds=dict(W, B=dict(W["B"], attempt=9))), why="k"))
        self.assertIn("attempt identity", refused(dict(mask, worlds=dict(W, B=dict(W["B"], attempt=1))), why="k uuid"))
        S = mask["snapshots"]
        # (Codex #77 r2 P1-2: the mask's evidence through the SHARED validator, graph.mask_evidence_problems)
        self.assertIn("first terminal", refused(dict(mask, worlds=dict(W, B=dict(W["B"], valid_before=None))), why="bio"))
        self.assertIn("first terminal", refused(dict(mask, worlds=dict(W, B=dict(W["B"], first_terminal=None))), why="ft"))
        self.assertIn("frontier", refused(dict(mask, worlds=dict(W, B=dict(W["B"], frontier=1000))), why="frontier"))
        # (Codex #77 r3 P1-2) a disposition the registered burn-in rule does not support: a mask claiming a 5M rule
        # (the design registers none), or an "exhausted" attempt 0 with every restart left
        self.assertIn("burn-in frame", refused(dict(mask, registry=dict(mask["registry"], burn_in_frame=5_000_000)),
                                               why="burn-in"))
        exh = dict(W["B"], burn_in={"decided": True, "disposition": "exhausted", "why": "restarts used up"})
        self.assertIn("not supported", refused(dict(mask, worlds=dict(W, B=exh)), why="exhausted"))
        unsettled = dict(W["B"], burn_in={"decided": False, "disposition": "restart_pending", "why": "a restart is due"})
        self.assertIn("unsettled attempt", refused(dict(mask, worlds=dict(W, B=unsettled)), why="unsettled"))
        self.assertIn("self-consistent burn-in", refused(dict(mask, worlds=dict(W, B=dict(W["B"], burn_in=None))), why="bi"))
        both = dict(W["B"], available_sha256=dict(W["B"]["available_sha256"], **{"2000": "0" * 64}))
        self.assertIn("both excluded and available", refused(dict(mask, worlds=dict(W, B=both)), why="both"))
        self.assertIn("identity", refused(dict(mask, snapshots={"B:2000": dict(S["B:2000"], snapshot="x")}), why="snap"))
        self.assertIn("cover (by uuid)", refused(dict(mask, worlds={"B": W["B"]}), why="cover"))
        self.assertIn("not a design world", refused(dict(mask, worlds=dict(W, Z=W["B"])), why="Z"))
        self.assertIn("no well-formed availability binding",
                      refused(mask, design={k: v for k, v in dd.items() if k != "availability"}))
        # (Codex #77 r2 P1-1) a SUBSTITUTED binding (another registry), with a mask that matches it: the binding is
        # part of every registered row, so --against refuses it
        sub = dict(BINDING, registry_sha256="s" * 64)
        msub = dict(mask, registry=dict(mask["registry"], sha256="s" * 64), block=dict(mask["block"], registry_sha256="s" * 64))
        self.assertIn("availability", refused(msub, design=dict(dd, availability=sub), why="substituted"))
        self.assertTrue(all(r["availability"] == BINDING for r in prow.values()))
        bad = dict(W["A"], available_sha256=dict(W["A"]["available_sha256"], **{"2000": "0" * 64}))
        self.assertIn("does not hash to the mask's verified", refused(dict(mask, worlds=dict(W, A=bad)), why="bytes"))
        bad = dict(W["A"], available_sha256={"1": W["A"]["available_sha256"]["1"]})
        self.assertIn("neither available nor excluded", refused(dict(mask, worlds=dict(W, A=bad)), why="unsupported"))
        self.assertIn("not an availability mask", refused(dict(mask, schema="finfolk.redqueen.graphmask/1"), why="v1"))
        with contextlib.redirect_stderr(io.StringIO()):                 # (no mask: the missing file is an error)
            self.assertEqual(plan.main([d, "--against", pend, "--out", out + ".x"]), 2)
            with self.assertRaises(SystemExit):
                plan.main([d, "--exclusions", mp, "--reconciliation", rec, "--out", out + ".z"])
        with self.assertRaisesRegex(plan.DesignError, "never to the pending"):
            plan.expand_v2(design2(self.tmp, self.edges), pending=True, exclusions={})

    def test_exclusions_follow_snapshot_aliases(self):
        """Codex #77 r1 P2-4: exclusions match the CANONICAL snapshot identity. An alias world A9 sharing B's uuid
        (and files) merges with B's pairs and becomes their display label; the mask's B:2000 exclusion still leaves
        those cells out (they are never read: the file is gone), recorded under the alias's display."""
        for name, frame in (("A.F1", 1), ("A.2000", 2000), ("B.F1", 1), ("B.2000", 2000), ("T0", 7)):
            wr(os.path.join(self.tmp, name + ".json"), ckpt.dumps(mk_cp(n_prey=8, frame=frame)))
        wr(os.path.join(self.tmp, "ages.json"), rqlib.canonical(common.reference_ages([mk_cp(n_prey=8, seed=9)], 4)))
        dd = design2(self.tmp, self.edges + [E("cross", "test", "A9", "T2", "A9", "T2")], availability=BINDING)
        dd["worlds"]["A9"] = dict(dd["worlds"]["B"])                    # (the alias: B's uuid, pattern and paths)
        d, pend = os.path.join(self.tmp, "d.json"), os.path.join(self.tmp, "pend.jsonl")
        wr(d, json.dumps(dd))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(plan.main([d, "--pending", "--out", pend]), 0)
        prow = {json.loads(ln)["id"]: json.loads(ln) for ln in rqlib.read_text(pend).splitlines() if ln}
        alias = [i for i in prow if i.startswith("A9.T2~A9.T2")]
        self.assertEqual(len(alias), 2)                                 # (B.T2 x B.T2 displayed as the alias)
        mask = plan_mask(self.tmp, dd, {"B:2000": ("biological", "at or after the world's first guild zero", 1500)})
        os.remove(os.path.join(self.tmp, "B.2000.json"))
        mp, out, rec = (os.path.join(self.tmp, f) for f in ("mask.json", "exec.jsonl", "recon.json"))
        wr(mp, json.dumps(mask))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(plan.main([d, "--against", pend, "--exclusions", mp, "--reconciliation", rec, "--out", out]),
                             0, err.getvalue())
        R = rqlib.read_json(rec)
        self.assertTrue(set(alias) <= {x["id"] for x in R["rows"]})
        self.assertEqual({(x["status"], x["frame"]) for x in R["rows"]}, {("biological", 2000)})
        self.assertEqual({x["world"] for x in R["rows"] if x["id"] in alias}, {"A9"})
        sb = plan.snapshot_uuid("uB", 2000)
        self.assertEqual({x["id"] for x in R["rows"]},
                         {i for i, r in prow.items() if any((r.get(k) or {}).get("snapshot") == sb for k in ("prey", "predators"))})

    def test_exclusions_with_registered_references(self):
        """Codex #77 r2 P2-3: a production plan reads external (sentinel) references, design worlds outside the main
        mask. They are covered by the REGISTERED reference assignment (references/1, its bytes' sha256 in the
        design's binding) and every reference cell must read the archive bytes it registers; without the
        assignment, with another one, or with other bytes the plan is refused."""
        for name, frame in (("A.F1", 1), ("A.2000", 2000), ("B.F1", 1), ("B.2000", 2000), ("S.2000", 2000), ("T0", 7)):
            wr(os.path.join(self.tmp, name + ".json"), ckpt.dumps(mk_cp(n_prey=8, frame=frame)))
        wr(os.path.join(self.tmp, "ages.json"), rqlib.canonical(common.reference_ages([mk_cp(n_prey=8, seed=9)], 4)))
        sp = os.path.join(self.tmp, "S.2000.json")

        def refs_doc(sha):
            return rqlib.canonical({"schema": plan.REFS_SCHEMA, "namespace": "sent", "references": {
                "RP:0": {"world": "s01", "frame": 2000, "uuid": "uS", "archive": sp, "sha256": sha}}})

        def setup(tag, refs_raw):
            rp = os.path.join(self.tmp, f"refs.{tag}.json")
            with open(rp, "wb") as f:
                f.write(refs_raw)
            dd = design2(self.tmp, self.edges + [E("reference", "training", "A", "T2", "S", "T2")],
                         availability=dict(BINDING, references_sha256=rqlib.sha256_bytes(refs_raw)))
            dd["worlds"]["S"] = {"uuid": "uS", "pattern": f"{self.tmp}/S.{{frame}}.json"}
            d, pend = os.path.join(self.tmp, f"d.{tag}.json"), os.path.join(self.tmp, f"pend.{tag}.jsonl")
            wr(d, json.dumps(dd))
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(plan.main([d, "--pending", "--out", pend]), 0)
            mp = os.path.join(self.tmp, f"mask.{tag}.json")
            wr(mp, json.dumps(plan_mask(self.tmp, dd, {})))
            return d, pend, mp, rp

        def final(d, pend, mp, *extra):
            err = io.StringIO()
            out = os.path.join(self.tmp, f"exec.{os.path.basename(d)}.{len(extra)}.jsonl")
            with contextlib.redirect_stderr(err):
                rc = plan.main([d, "--against", pend, "--exclusions", mp, "--reconciliation", out + ".recon",
                                "--out", out, *extra])
            return rc, err.getvalue(), out
        d, pend, mp, rp = setup("ok", refs_doc(rqlib.sha256_file(sp)))
        rc, err, out = final(d, pend, mp, "--references", rp)
        self.assertEqual(rc, 0, err)
        rows = [json.loads(ln) for ln in rqlib.read_text(out).splitlines() if ln]
        ref = [r for r in rows if (r.get("predators") or {}).get("world") == "S"]
        self.assertTrue(ref and all(r["predators"]["sha256"] == rqlib.sha256_file(sp) for r in ref))
        rc, err, _ = final(d, pend, mp)
        self.assertEqual(rc, 2)
        self.assertIn("give --references", err)
        other = os.path.join(self.tmp, "refs.other.json")
        with open(other, "wb") as f:
            f.write(refs_doc("0" * 64))
        rc, err, _ = final(d, pend, mp, "--references", other)
        self.assertEqual(rc, 2)
        self.assertIn("not the registered reference assignment", err)
        d2, pend2, mp2, rp2 = setup("badhash", refs_doc("0" * 64))       # (registered, but not the archive's bytes)
        rc, err, _ = final(d2, pend2, mp2, "--references", rp2)
        self.assertEqual(rc, 2)
        self.assertIn("does not hash", err)

    def test_long_fraction_half_unit(self):
        """(Review of d4dc4b7, P3) the default 1/8: floor(N / 8 + 0.5) long units, a half unit rounding up."""
        for n, want in ((3, 0), (4, 1), (11, 1), (12, 2), (20, 3)):
            units = [{"id": f"u{i:02d}", "attrs": {"family": "f"}} for i in range(n)]
            chosen, man = plan.select_long(units, 0.125, ["family"], "ns")
            self.assertEqual((len(chosen), man["long"]), (want, want), n)
        d = design2(self.tmp, self.edges)
        del d["long"]                                                            # the default: 1/8
        _, _, man = plan.expand_v2(d, pending=True)
        self.assertEqual((man["fraction"], man["units"], man["long"]), (0.125, 9, 1))

    def test_cli(self):
        p = os.path.join(self.tmp, "design.json")
        wr(p, json.dumps(design2(self.tmp, self.edges)))
        out, lm = os.path.join(self.tmp, "p.jsonl"), os.path.join(self.tmp, "long.json")
        self.assertEqual(plan.main([p, "--pending", "--out", out, "--long-manifest", lm]), 0)
        self.assertEqual(rqlib.read_json(lm)["long"], int(0.25 * 9 + 0.5))


if __name__ == "__main__":
    unittest.main()

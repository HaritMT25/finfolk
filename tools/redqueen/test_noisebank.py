#!/usr/bin/env python3
"""test_noisebank.py: the independent noise bank (noisebank.py, design v4 §7.4). Covers:
  * the plan: the registered worlds / partners, the crossed 256-pair design and its 32 controls (18,432
    trajectories), the production seed sharing, the mandatory inputs (validation directory, arena, age
    reference, reservations) and the seed check;
  * the estimator on simulated banks with KNOWN components: the row / donor / cell shares, the cross-channel
    covariances, the free channel's row covariance, s(mu) by bin;
  * s(mu): the bins and the monotone fit on the latent scale (the bins a special case), the isotonic fit;
  * the production V builder against the covariance of replicate means written out term by term, with the
    means it is evaluated at given explicitly;
  * collection bound to the final plan; the CLI.
numpy required for the estimator (RQ_REQUIRE_NUMPY=1 makes a missing numpy a failure).

    python3 -I tools/redqueen/test_noisebank.py [-v]
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import os
import shutil
import sys
import tempfile
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
import noisebank as nb  # noqa: E402
import plan  # noqa: E402
import rqlib  # noqa: E402
try:
    import numpy as np  # noqa: E402
except ImportError:
    if os.environ.get("RQ_REQUIRE_NUMPY"):
        raise SystemExit("RQ_REQUIRE_NUMPY is set, but numpy cannot be imported")
    np = None

NS = "ns-validation"


def block(root, valid_before=None, n=12):
    ws = {}
    for i in range(1, n + 1):
        w = f"w{i:02d}"
        ws[w] = {"uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:redqueen:{NS}:{w}")), "treatment": "C",
                 "block": 1, "status": "running", "pattern": os.path.join(root, w, "end.{frame}.json"), "paths": {},
                 "valid_before": (valid_before or {}).get(w), "archived": [t * 1_000_000 for t in range(1, 101)]}
    return {"schema": "finfolk.redqueen.worldsblock/1", "registry_sha256": "r" * 64, "root": root,
            "times": {f"{t}M": t * 1_000_000 for t in range(1, 101)}, "worlds": ws}


def files(tmp):
    out = {}
    for name, txt in (("t.json", "{}"), ("ages.json", "{}"), ("prod.json", json.dumps({"reserved": []}))):
        out[name] = os.path.join(tmp, name)
        with open(out[name], "w") as f:
            f.write(txt)
    return out


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "validation")
        self.f = files(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def design(self, b=None, **kw):
        args = dict(validation_dir=self.root, arena="arena-7")
        args.update(kw)
        return nb.make_design(b or block(self.root), [self.f["t.json"]], self.f["ages.json"], [self.f["prod.json"]], **args)

    def test_the_registered_crossed_design(self):
        d = self.design()
        meta = d["noisebank"]
        self.assertEqual(len(meta["worlds"]), nb.N_WORLDS)
        self.assertEqual((meta["arena"], meta["validation_dir"]), ("arena-7", os.path.abspath(self.root)))
        self.assertEqual(sorted(meta["partner"].values()), sorted(meta["worlds"]))        # (a cyclic partnering)
        self.assertTrue(all(meta["partner"][w] != w for w in meta["worlds"]))
        self.assertEqual((meta["predator_trajectories"], meta["free_trajectories"], meta["cells"]),
                         (16384, 2048, 18432))
        pairs = {(e["prey"]["world"], e["prey"]["time"], e["predators"]["world"], e["predators"]["time"])
                 for e in d["edges"] if e["predators"]}
        self.assertEqual(len(pairs), 256)
        fam = [e["family"] for e in d["edges"]]
        self.assertEqual((fam.count("nb-within"), fam.count("nb-cross"), fam.count("nb-free")), (128, 128, 32))
        faced = {}
        for _, _, wp, tp in pairs:
            faced[(wp, tp)] = faced.get((wp, tp), 0) + 1
        self.assertEqual(set(faced.values()), {8})                              # (every predator snapshot: 8 prey)
        self.assertEqual(meta["capture_bounds"], {"5000": 324, "10000": 642, "20000": 1284})
        rows, _, _ = plan.expand_v2(d, pending=True)
        r0 = [r for r in rows if r["predators"] is not None]
        self.assertTrue(all(r["horizon"] == "long" and r["namespace"] == "noisebank" for r in rows))
        # production seed sharing: the sample seed per prey snapshot x replicate, the transplant seed per predator
        # snapshot x replicate
        by_prey = {}
        for r in r0:
            by_prey.setdefault((r["prey"]["world"], r["prey"]["time"], r["replicate"]), set()).add(r["seeds"]["sample"])
        self.assertEqual({len(v) for v in by_prey.values()}, {1})
        by_pred = {}
        for r in r0:
            by_pred.setdefault((r["predators"]["world"], r["predators"]["time"], r["replicate"]), set()).add(
                r["seeds"]["transplant"])
        self.assertEqual({len(v) for v in by_pred.values()}, {1})

    def test_refusals(self):
        with self.assertRaises(nb.NoiseBankError):
            self.design(validation_dir=None)
        with self.assertRaises(nb.NoiseBankError):
            self.design(arena=None)
        with self.assertRaises(nb.NoiseBankError):
            self.design(validation_dir=os.path.join(self.tmp, "elsewhere"))
        vb = {f"w{i:02d}": 70_000_000 for i in range(1, 6)}                       # (5 worlds lose 80M: 7 left)
        with self.assertRaises(nb.NoiseBankError):
            self.design(block(self.root, vb))
        with self.assertRaises(nb.NoiseBankError):
            nb.make_design(block(self.root), [self.f["t.json"]], "ages.json", [self.f["prod.json"]],
                           validation_dir=self.root, arena="a")
        with self.assertRaises(nb.NoiseBankError):
            nb.make_design(block(self.root), [self.f["t.json"]], self.f["ages.json"], [], validation_dir=self.root, arena="a")
        rows, _, _ = plan.expand_v2(self.design(), pending=True)
        seed = next(iter(plan.plan_seeds(rows)))
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w") as f:
            json.dump({"engine_seed": seed}, f)
        with self.assertRaises(nb.NoiseBankError):
            nb.make_design(block(self.root), [self.f["t.json"]], self.f["ages.json"], [bad], validation_dir=self.root,
                           arena="a")

    def test_cli_plan(self):
        bp, out = os.path.join(self.tmp, "block.json"), os.path.join(self.tmp, "d.json")
        with open(bp, "w") as f:
            json.dump(block(self.root), f)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(nb.main(["plan", "--block", bp, "--templates", self.f["t.json"], "--age-reference",
                                      self.f["ages.json"], "--avoid", self.f["prod.json"], "--validation-dir", self.root,
                                      "--arena", "a1", "--out", out]), 0)
        self.assertEqual(rqlib.read_json(out)["noisebank"]["arena"], "a1")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(nb.main(["plan", "--block", bp, "--templates", self.f["t.json"], "--age-reference",
                                      self.f["ages.json"], "--avoid", self.f["prod.json"], "--validation-dir",
                                      self.tmp, "--arena", "a1", "--out", out]), 2)


def sigm(x):
    return 1.0 / (1.0 + np.exp(-x))


TRUE = {"SigmaR": [[0.25, 0.08, 0.06], [0.08, 0.30, 0.12], [0.06, 0.12, 0.40]],
        "SigmaD": [[0.20, 0.05], [0.05, 0.15]], "SigmaE": [[0.55, 0.10], [0.10, 0.55]],
        "s": {"C": [0.60, 0.30, 0.20], "S": [0.35, 0.25, 0.30], "F": [0.35, 0.25, 0.30]}}


def simulate(seed=3, R=64, true=TRUE):
    """A bank with KNOWN components on the latent scale (the 32 x 8 crossed design of the plan), its counts
    rounded from the latent logits: per horizon an independent draw."""
    rng = np.random.default_rng(seed)
    worlds = [f"w{i}" for i in range(8)]
    snaps = [(w, t) for w in worlds for t in nb.TIMES]
    partner = {w: worlds[(k + 1) % 8] for k, w in enumerate(worlds)}
    pairs = [(q, (wp, tp)) for q in snaps for wp in (q[0], partner[q[0]]) for tp in nb.TIMES]
    a = {q: rng.normal(-0.4, 0.9) for q in snaps}
    b = {p: rng.normal(0.0, 0.6) for p in snaps}
    c = {q: rng.normal(1.6, 0.4) for q in snaps}
    SR, SD, SE = (np.array(true[k]) for k in ("SigmaR", "SigmaD", "SigmaE"))
    LR, LD, LE = np.linalg.cholesky(SR), np.linalg.cholesky(SD), np.linalg.cholesky(SE)
    eF = 1 - SR[2, 2]

    def s_of(ch, m):
        lo, hi = nb.BINS[ch]
        s = true["s"][ch]
        return np.where(m < lo, s[0], np.where(m < hi, s[1], s[2]))
    obs = []
    for h in nb.HORIZONS:
        Bh = nb.capture_bound(h)
        row = {(q, r): LR @ rng.standard_normal(3) for q in snaps for r in range(R)}
        don = {(p, r): LD @ rng.standard_normal(2) for p in snaps for r in range(R)}
        for q in snaps:
            mF = sigm(c[q] + 0.3)
            for r in range(R):
                zF = math.log(mF / (1 - mF)) + float(s_of("F", mF)) * (row[(q, r)][2] + math.sqrt(eF) * rng.standard_normal())
                obs.append({"prey": list(q), "pred": None, "replicate": r, "h": h, "survivors": int(round(600 * sigm(zF)))})
        for q, p in pairs:
            mC, mS = sigm(a[q] + b[p]), sigm(c[q] - 0.6 * b[p])
            for r in range(R):
                e = LE @ rng.standard_normal(2)
                zC = math.log(mC / (1 - mC)) + float(s_of("C", mC)) * (row[(q, r)][0] + don[(p, r)][0] + e[0])
                zS = math.log(mS / (1 - mS)) + float(s_of("S", mS)) * (row[(q, r)][1] + don[(p, r)][1] + e[1])
                obs.append({"prey": list(q), "pred": list(p), "replicate": r, "h": h,
                            "captures": int(round(Bh * sigm(zC))), "survivors": int(round(600 * sigm(zS)))})
    cells = {}
    for o in obs:
        key = (tuple(o["prey"]), None if o["pred"] is None else tuple(o["pred"]), o["replicate"])
        x = cells.setdefault(key, {"cell": f"{key}", "prey": o["prey"], "pred": o["pred"], "replicate": o["replicate"],
                                   "horizons": {}})
        x["horizons"][str(o["h"])] = {"captures": o.get("captures"), "survivors": o["survivors"]}
    return {"schema": nb.OBS_SCHEMA, "design_sha256": "d", "plan_sha256": "p", "missing": [],
            "observations": list(cells.values())}


@unittest.skipIf(np is None, "numpy is not installed")
class TestEstimator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = simulate()
        cls.bank = nb.estimate(cls.doc, boot=19)

    def test_components_recovered(self):
        """The row / donor / cell shares, the cross-channel covariances and the free row covariances of a
        simulated bank with known components are recovered (64 replicates, the crossed 256-cell design)."""
        for h in nb.HORIZONS:
            e = self.bank["horizons"][str(h)]
            SR, SD, SE = (np.array(e[k]) for k in ("SigmaR", "SigmaD", "SigmaE"))
            tR, tD, tE = (np.array(TRUE[k]) for k in ("SigmaR", "SigmaD", "SigmaE"))
            self.assertLess(float(np.max(np.abs(SR[:2, :2] - tR[:2, :2]))), 0.05, (h, SR))
            self.assertLess(float(np.max(np.abs(SD - tD))), 0.05, (h, SD))
            self.assertLess(float(np.max(np.abs(SE - tE))), 0.06, (h, SE))
            self.assertLess(float(np.max(np.abs(SR[:2, 2] - tR[:2, 2]))), 0.05, (h, SR))
            self.assertGreaterEqual(SR[2, 2], e["SigmaR_FF_lower_bound"] - 1e-12)
            for ch in "CS":
                sh = e["shares"][ch]
                self.assertAlmostEqual(sh["row"] + sh["donor"] + sh["cell"], 1.0, delta=1e-9)
            self.assertEqual(e["bootstrap"]["draws"], 19)

    def test_scales_by_bin(self):
        e = self.bank["horizons"]["5000"]["scales"]
        for ch in "CS":
            for k, (est, tru) in enumerate(zip(e["s"][ch], TRUE["s"][ch])):
                if est is not None:
                    self.assertLess(abs(est - tru) / tru, 0.15, (ch, k, est, tru))
        g = self.bank["generator_noise"]
        self.assertEqual((g["horizon"], g["capture_bound"]), (5000, 324))
        self.assertIn("C", g["s_monotone"])
        self.assertIn("rule", self.bank["map_variance"])

    def test_scale_fits(self):
        """Bins: the root mean variance per bin; monotone: the isotonic fit on the latent scale, linear between
        its blocks; a step function with knots at the bin edges is recovered (the bins a special case)."""
        rng = np.random.default_rng(5)
        mu = rng.uniform(0.05, 0.95, 4000)
        true = np.where(mu < 0.35, 0.6, np.where(mu < 0.70, 0.3, 0.2))
        var = true ** 2 * rng.chisquare(63, len(mu)) / 63
        fb = nb.fit_scale(mu, var, "C", "bins")
        self.assertTrue(np.allclose(fb["s"], [0.6, 0.3, 0.2], rtol=0.03))
        fm = nb.fit_scale(mu, var, "C", "monotone")
        self.assertEqual(fm["direction"], "decreasing")
        self.assertTrue(np.all(np.diff(fm["s"]) <= 1e-12))
        for m, want in ((0.1, 0.6), (0.5, 0.3), (0.9, 0.2)):
            self.assertAlmostEqual(float(fm["eval"](m)), want, delta=0.03)
        self.assertTrue(np.allclose(nb.pava([3, 1, 2, 5, 4], [1] * 5), [2, 2, 2, 4.5, 4.5]))
        self.assertTrue(np.allclose(nb.pava([1, 3, 2], [1, 1, 1], increasing=False), [2, 2, 2]))

    def test_v_builder(self):
        """cov_parts against the covariance of replicate means written out term by term (capture: row + donor
        + cell; survival: the exposed cell minus its prey snapshot's free control), at explicitly given means
        (raw or null-fit: the builder never chooses)."""
        noise = {"SigmaR": TRUE["SigmaR"], "SigmaD": TRUE["SigmaD"], "SigmaE": TRUE["SigmaE"], "s": TRUE["s"],
                 "capture_bound": 324}
        st = {"prey": [0, 0, 1, 1, 2], "pred": [0, 1, 0, 1, 1], "n_prey": 3, "n_pred": 2}
        R = 6
        SR, SD = np.array(TRUE["SigmaR"]), np.array(TRUE["SigmaD"])
        sf = nb.bins_scale(noise)
        for means in ({"C": np.array([0.2, 0.4, 0.5, 0.8, 0.33])}, {"C": np.array([0.36, 0.36, 0.36, 0.36, 0.36])}):
            d, U = nb.cov_parts(noise, "C", st, means, R)
            g = sf("C", means["C"]) * means["C"] * (1 - means["C"])
            want = np.zeros((5, 5))
            for i in range(5):
                for j in range(5):
                    v = SR[0, 0] * (st["prey"][i] == st["prey"][j]) + SD[0, 0] * (st["pred"][i] == st["pred"][j])
                    v += (1 - SR[0, 0] - SD[0, 0]) * (i == j)
                    want[i, j] = g[i] * g[j] * v / R
            self.assertTrue(np.allclose(np.diag(d) + U @ U.T, want, atol=1e-15))
        mS, mF = np.array([0.7, 0.8, 0.6, 0.9, 0.75]), np.array([0.85, 0.9, 0.8])
        d, U = nb.cov_parts(noise, "Q", st, {"S": mS, "F": mF}, R)
        gS = sf("S", mS) * mS * (1 - mS)
        gF = sf("F", mF[st["prey"]]) * mF[st["prey"]] * (1 - mF[st["prey"]])
        want = np.zeros((5, 5))
        for i in range(5):
            for j in range(5):
                sp, sd = st["prey"][i] == st["prey"][j], st["pred"][i] == st["pred"][j]
                v = gS[i] * gS[j] * (SR[1, 1] * sp + SD[1, 1] * sd + (1 - SR[1, 1] - SD[1, 1]) * (i == j))
                v -= (gS[i] * gF[j] + gF[i] * gS[j]) * SR[1, 2] * sp
                v += gF[i] * gF[j] * (SR[2, 2] + (1 - SR[2, 2])) * sp
                want[i, j] = v / R
        self.assertTrue(np.allclose(np.diag(d) + U @ U.T, want, atol=1e-15))

    def test_saturation_and_bounds(self):
        doc = json.loads(json.dumps(self.doc))
        doc["observations"][-1]["horizons"]["5000"]["captures"] = 10 ** 6
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(doc, boot=2)
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(dict(doc, schema="x"), boot=2)


class TestCollect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "validation")
        self.f = files(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_collect_bound_to_the_final_plan(self):
        import store
        import zipfile
        d = nb.make_design(block(self.root), [self.f["t.json"]], self.f["ages.json"], [self.f["prod.json"]],
                           validation_dir=self.root, arena="a")
        rows, _, _ = plan.expand_v2(d, pending=True)
        for r in rows:
            for k in nb.HASHED:
                if isinstance(r.get(k), dict) and r[k].get("path"):
                    r[k]["sha256"] = rqlib.sha256_bytes(f"{k}|{r[k]['path']}".encode())
        pp = os.path.join(self.tmp, "plan.jsonl")
        plan.write_plan(rows, pp)
        pick = rows[:3]

        def bundle(r, n=600):
            return {"cell": r, "score": {"n_start": n, "horizons": [{"steps": h, "survivors": 400, "captures": 50}
                                                                     for h in nb.HORIZONS]}}

        def study(bundles):
            root = os.path.join(self.tmp, "study")
            shutil.rmtree(root, ignore_errors=True)
            os.makedirs(os.path.join(root, store.CHUNKS))
            cells = {}
            with zipfile.ZipFile(os.path.join(root, store.CHUNKS, "c0001.zip"), "w") as z:
                for cid, bd in bundles.items():
                    data = json.dumps(bd).encode()
                    z.writestr(f"{cid}/bundle.json", data)
                    cells[cid] = {"bundle_sha256": rqlib.sha256_bytes(data)}
            with open(os.path.join(root, store.INDEX), "w") as f:
                f.write(json.dumps({"chunk": "c0001.zip", "cells": cells}) + "\n")
            return root
        rest = sorted({r["id"] for r in rows} - {r["id"] for r in pick})
        doc = nb.collect(study({r["id"]: bundle(r) for r in pick}), d, pp, rest)
        self.assertEqual(len(doc["observations"]), 3)
        self.assertEqual(sorted(doc["observations"][0]["horizons"]), ["10000", "20000", "5000"])
        with self.assertRaises(nb.NoiseBankError):
            nb.collect(study({r["id"]: bundle(r) for r in pick}), d, pp)                      # (undeclared missing)
        with self.assertRaises(nb.NoiseBankError):
            nb.collect(study({pick[0]["id"]: bundle(pick[0], 599)}), d, pp, sorted(set(rest) | {r["id"] for r in pick[1:]}))
        bad = dict(bundle(pick[0]))
        bad["score"] = {"n_start": 600, "horizons": [{"steps": 5000, "survivors": 1, "captures": 1}]}
        with self.assertRaises(nb.NoiseBankError):
            nb.collect(study({pick[0]["id"]: bad}), d, pp, sorted(set(rest) | {r["id"] for r in pick[1:]}))


if __name__ == "__main__":
    unittest.main()

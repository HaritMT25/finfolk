#!/usr/bin/env python3
"""test_refsel.py: reference selection (refsel.py, design v4 §4.2). Covers:
  * the candidates, the constraint feasibility search and the plan (design/2, seeds, mandatory inputs);
  * the frozen criterion;
  * the greedy / swap selection: the constraints, determinism, the hash tie-breaks, the saturation
    penalty, the information criterion's preference;
  * the references/1 output against sealing.py's identity recipes.
numpy required (RQ_REQUIRE_NUMPY=1 makes a missing numpy a failure).

    python3 -I tools/redqueen/test_refsel.py [-v]
"""
from __future__ import annotations

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
import plan  # noqa: E402
import refsel as rs  # noqa: E402
import rqlib  # noqa: E402
try:
    import numpy as np  # noqa: E402
except ImportError:
    if os.environ.get("RQ_REQUIRE_NUMPY"):
        raise SystemExit("RQ_REQUIRE_NUMPY is set, but numpy cannot be imported")
    np = None

NS = "ns-validation"


def block(tmp, valid_before=None, sentinels=rs.SENTINELS):
    ws = {}
    for i in range(1, 13):
        w = f"w{i:02d}"
        ws[w] = {"uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:redqueen:{NS}:{w}")), "treatment": "C",
                 "block": 1, "status": "running", "pattern": os.path.join(tmp, w, "end.{frame}.json"),
                 "paths": {"F1": os.path.join(tmp, w, "F1.json")}, "valid_before": (valid_before or {}).get(w),
                 "archived": [1] + [t * 1_000_000 for t in range(1, 201)]}
    times = {"F1": 1}
    times.update({f"{t}M": t * 1_000_000 for t in range(1, 201)})
    return {"schema": "finfolk.redqueen.worldsblock/1", "registry_sha256": "r" * 64, "times": times, "worlds": ws}


def files(tmp):
    out = {}
    for n, txt in (("t.json", "{}"), ("ages.json", "{}"), ("worlds.json", json.dumps({"reserved": []}))):
        out[n] = os.path.join(tmp, n)
        with open(out[n], "w") as f:
            f.write(txt)
    return out


def final_rows(design):
    rows, _, _ = plan.expand_v2(design, pending=True)
    for r in rows:
        for k in rs.HASHED:
            if isinstance(r.get(k), dict) and r[k].get("path"):
                r[k]["sha256"] = rqlib.sha256_bytes(f"{k}|{r[k]['path']}".encode())
    return {r["id"]: r for r in rows}


def simulate(cands, seed=1, rank=2, saturate=(), noise=0.15, B=324):
    """Grid observations from a low-rank logistic model: capture logit a_i + b_j + u_i v_j, survival
    with a predator effect; saturate: candidates whose predators capture almost everything."""
    rng = np.random.default_rng(seed)
    n = len(cands)
    a, b = rng.normal(-0.8, 0.4, n), rng.normal(0.0, 0.4, n)
    U, V = rng.normal(0, 0.6, (n, rank)), rng.normal(0, 0.6, (n, rank))
    s0, c = rng.normal(1.6, 0.3, n), rng.normal(-0.5, 0.2, n)
    for k, cnd in enumerate(cands):
        if tuple(cnd) in saturate:             # (both readouts saturated: capture ~1, exposed survival ~0)
            b[k], c[k] = 7.0, -8.0
    obs = []
    for i, ci in enumerate(cands):
        for r in range(rs.REPLICATES):
            obs.append({"cell": f"free.{i}.{r}", "prey": list(ci), "pred": None, "replicate": r,
                        "survivors": int(round(600 / (1 + math.exp(-(s0[i] + rng.normal(0, 0.1)))))), "cohort": 600})
        for j, cj in enumerate(cands):
            for r in range(rs.REPLICATES):
                lc = a[i] + b[j] + U[i] @ V[j] + rng.normal(0, noise)
                ls = s0[i] + c[j] - 0.3 * (U[i] @ V[j]) + rng.normal(0, 0.1)
                obs.append({"cell": f"{i}.{j}.{r}", "prey": list(ci), "pred": list(cj), "replicate": r,
                            "captures": int(round(B / (1 + math.exp(-lc)))),
                            "survivors": int(round(600 / (1 + math.exp(-ls)))), "cohort": 600})
    return obs


@unittest.skipIf(np is None, "numpy is not installed")
class TestRefsel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.f = files(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def design(self, blk=None):
        return rs.make_design(blk or block(self.tmp), list(rs.SENTINELS), NS, [self.f["t.json"]], self.f["ages.json"],
                              [self.f["worlds.json"]])

    def test_plan(self):
        """32 candidates per guild (4 sentinels x 8 times), the 32 x 32 grid and 32 free controls at R = 6;
        an invalid late snapshot leaves the candidate set; the criterion frozen with its sha256."""
        d = self.design()
        self.assertEqual(len(d["refsel"]["candidates"]), 32)
        rows, _, _ = plan.expand_v2(d, pending=True)
        self.assertEqual(len(rows), (32 * 32 + 32) * 6)
        self.assertEqual(d["refsel"]["criterion_sha256"], rqlib.canonical_sha(rs.CRITERION))
        self.assertEqual({r["role"] for r in rows}, {"diagnostic"})
        self.assertTrue(all(r["ages"]["path"] == self.f["ages.json"] for r in rows))
        d2 = self.design(block(self.tmp, valid_before={"w06": 150_000_000}))
        self.assertEqual(len(d2["refsel"]["candidates"]), 30)               # (w06 at 180, 200M invalid)
        for bad in (None, "ages.json"):
            with self.assertRaises(rs.RefselError):
                rs.make_design(block(self.tmp), list(rs.SENTINELS), NS, [self.f["t.json"]], bad, [self.f["worlds.json"]])
        with self.assertRaises(rs.RefselError):                         # (another namespace: not the recipe)
            rs.make_design(block(self.tmp), list(rs.SENTINELS), "other", [self.f["t.json"]], self.f["ages.json"],
                           [self.f["worlds.json"]])
        # a reserved seed is refused
        s = sorted(plan.plan_seeds(rows))[3]
        res = os.path.join(self.tmp, "prod.json")
        with open(res, "w") as f:
            json.dump({"reserved": [{"slot": "b1:C:0", "seeds": [s]}]}, f)
        with self.assertRaises(rs.RefselError):
            rs.make_design(block(self.tmp), list(rs.SENTINELS), NS, [self.f["t.json"]], self.f["ages.json"], [res])
        # constraints that cannot be met: two usable sentinels; no late snapshot anywhere
        dead = {w: 1 for w in ("w05", "w06")}
        with self.assertRaises(rs.RefselError):
            self.design(block(self.tmp, valid_before=dead))
        early = {w: 130_000_000 for w in rs.SENTINELS}
        with self.assertRaises(rs.RefselError):
            self.design(block(self.tmp, valid_before=early))

    def test_feasibility(self):
        cands = [(w, t) for w in rs.SENTINELS for t in rs.TIMES]
        self.assertTrue(rs.feasible([], cands))
        four_late = [("w01", "140M"), ("w01", "180M"), ("w01", "200M"), ("w04", "140M")]
        pool = [c for c in cands if c not in four_late]
        self.assertTrue(rs.feasible(four_late, pool))                      # (4 slots left, 4 early possible)
        five = four_late + [("w04", "180M")]
        self.assertFalse(rs.feasible(five, [c for c in pool if c not in five]))   # (3 slots left: 4 early needed)
        full = [("w01", "F1"), ("w01", "20M"), ("w04", "60M"), ("w05", "100M"), ("w06", "140M"), ("w06", "200M"),
                ("w04", "120M"), ("w05", "180M")]
        self.assertTrue(rs.feasible(full, []))
        three_early = [("w01", "F1"), ("w01", "20M"), ("w04", "60M"), ("w05", "140M"), ("w06", "140M"),
                       ("w06", "200M"), ("w04", "180M"), ("w05", "180M")]
        self.assertFalse(rs.feasible(three_early, []))                      # (3 early only)
        two_sent = [("w01", t) for t in rs.TIMES[:4]] + [("w04", t) for t in rs.TIMES[4:]]
        self.assertFalse(rs.feasible(two_sent, []))                        # (two sentinels)

    def test_selection(self):
        """Eight per guild meeting every constraint; deterministic whatever the observation order; a fully
        saturating sentinel's predators are never chosen; the frozen criterion is enforced; the output
        passes sealing.py's identity recipes."""
        d = self.design()
        rows = final_rows(d)
        cands = [tuple(c) for c in d["refsel"]["candidates"]]
        sat = {("w05", t) for t in rs.TIMES}
        obs = simulate(cands, seed=3, saturate=sat)
        doc, rep = rs.select(obs, d, rows)
        doc2, rep2 = rs.select(list(reversed(obs)), d, rows)
        self.assertEqual(json.dumps(doc, sort_keys=True), json.dumps(doc2, sort_keys=True))
        for g in ("RQ", "RP"):
            sel = rep["guilds"][g]["selected"]
            self.assertEqual(len(sel), 8)
            self.assertEqual(len({tuple(x) for x in sel}), 8)
            self.assertGreaterEqual(len({w for w, _ in sel}), 3)
            self.assertGreaterEqual(sum(1 for _, t in sel if rs.time_m(t) <= 120), 4)
            self.assertGreaterEqual(sum(1 for _, t in sel if rs.time_m(t) >= 140), 2)
        self.assertFalse(any(tuple(x) in sat for x in rep["guilds"]["RP"]["selected"]), rep["guilds"]["RP"]["selected"])
        # sealing.py's recipes: references/1, the sentinel namespace, uuid and snapshot, eight per guild
        self.assertEqual((doc["schema"], doc["namespace"]), ("finfolk.redqueen.references/1", NS))
        self.assertEqual(sorted(doc["references"]), [f"RP:{k}" for k in range(8)] + [f"RQ:{k}" for k in range(8)])
        for slot, v in doc["references"].items():
            self.assertEqual(v["uuid"], str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:redqueen:{NS}:{v['world']}")))
            self.assertEqual(v["snapshot"], plan.snapshot_uuid(v["uuid"], v["frame"]))
            self.assertRegex(v["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(os.path.isabs(v["archive"]))
        frames = [doc["references"][f"RQ:{k}"]["frame"] for k in range(8)]
        self.assertEqual(frames, sorted(frames))                           # (slots by frame)
        # the objective is the registered one, and the selection beats every single exchange
        cr = rs.CRITERION
        emb = rs.embeddings(rs.matrices(obs, cands))
        for g in ("RQ", "RP"):
            idx = [cands.index(tuple(x)) for x in rep["guilds"][g]["selected"]]
            v = rs.objective(emb[g], idx)
            self.assertAlmostEqual(v, rep["guilds"][g]["objective"], places=9)
            for s in idx:
                for c in range(len(cands)):
                    if c in idx or emb[g]["sat"][c] > cr["max_saturated_share"]:      # (eligible only)
                        continue
                    S = [c if x == s else x for x in idx]
                    if rs.feasible([cands[j] for j in S], [], cr):
                        self.assertLessEqual(rs.objective(emb[g], S), v + 1e-9 * max(1.0, abs(v)))
        bad = json.loads(json.dumps(d))
        bad["refsel"]["criterion"]["saturation_penalty"] = 0.0
        with self.assertRaises(rs.RefselError):
            rs.select(obs, bad, rows)

    def test_information_prefers_spread(self):
        """With no saturation, a reference set whose embeddings span the rank-2 space beats one whose
        embeddings collapse onto a line (the information criterion), and ties fall to the hash order."""
        d = self.design()
        cands = [tuple(c) for c in d["refsel"]["candidates"]]
        emb = rs.embeddings(rs.matrices(simulate(cands, seed=5), cands))
        g = emb["RP"]
        X = g["readouts"]["capture_logit"]["emb"][:, :2]
        order = np.argsort(X[:, 1])
        spread = [int(i) for i in order[:4]] + [int(i) for i in order[-4:]]
        mid = [int(i) for i in order[12:20]]
        self.assertGreater(rs.objective(g, spread), rs.objective(g, mid))
        keys = [rs.tie_key("RP", w, rs.frame_of(t)) for w, t in cands]
        self.assertEqual(len(set(keys)), len(keys))

    def test_incomplete_grid_and_bad_counts(self):
        d = self.design()
        cands = [tuple(c) for c in d["refsel"]["candidates"]]
        obs = simulate(cands, seed=7)
        with self.assertRaises(rs.RefselError):
            rs.matrices([o for o in obs if not (o["pred"] and tuple(o["pred"]) == cands[0])], cands)
        o = dict(next(x for x in obs if x["pred"]), captures=10 ** 6)
        with self.assertRaises(rs.RefselError):
            rs.matrices([o if x["cell"] == o["cell"] else x for x in obs], cands)
        with self.assertRaises(rs.RefselError):
            rs.matrices(obs + [dict(obs[-1])], cands)                       # (a duplicate)


@unittest.skipIf(np is None, "numpy is not installed")
class TestCollectAndCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.f = files(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def study(self, bundles):
        import store
        import zipfile
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

    def test_collect_bound_to_the_final_plan(self):
        d = rs.make_design(block(self.tmp), list(rs.SENTINELS), NS, [self.f["t.json"]], self.f["ages.json"],
                           [self.f["worlds.json"]])
        rows = final_rows(d)
        pp = os.path.join(self.tmp, "plan.jsonl")
        plan.write_plan(list(rows.values()), pp)
        pick = [r for r in rows.values() if r["prey"]["world"] == "w01" and r["prey"]["time"] == "60M"
                and r["replicate"] == 0]
        self.assertEqual(len(pick), 33)                                   # (32 predator candidates + free)

        def bundle(r, n=600):
            return {"cell": r, "score": {"n_start": n, "horizons": [{"steps": 5000, "survivors": 400, "captures": 50}]}}
        rest = sorted(set(rows) - {r["id"] for r in pick})
        doc = rs.collect(self.study({r["id"]: bundle(r) for r in pick}), d, pp, rest)
        self.assertEqual(len(doc["observations"]), 33)
        self.assertEqual(sum(1 for o in doc["observations"] if o["pred"] is None), 1)
        with self.assertRaises(rs.RefselError):                            # (undeclared missing cells)
            rs.collect(self.study({r["id"]: bundle(r) for r in pick}), d, pp)
        with self.assertRaises(rs.RefselError):                            # (another cohort)
            rs.collect(self.study({pick[0]["id"]: bundle(pick[0], 599)}), d, pp, sorted(set(rows) - {pick[0]["id"]}))
        x = dict(pick[0], seeds=dict(pick[0]["seeds"], transplant=1))
        with self.assertRaises(rs.RefselError):                            # (not the plan's row)
            rs.collect(self.study({x["id"]: bundle(x)}), d, pp, sorted(set(rows) - {x["id"]}))

    def test_cli_plan(self):
        import contextlib
        import io
        bp, dp = os.path.join(self.tmp, "block.json"), os.path.join(self.tmp, "grid.json")
        with open(bp, "w") as f:
            json.dump(block(self.tmp), f)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(rs.main(["plan", "--block", bp, "--sentinel-namespace", NS, "--templates", self.f["t.json"],
                                      "--age-reference", self.f["ages.json"], "--avoid", self.f["worlds.json"],
                                      "--out", dp]), 0)
        self.assertEqual(rqlib.read_json(dp)["refsel"]["criterion_sha256"], rqlib.canonical_sha(rs.CRITERION))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(rs.main(["plan", "--block", bp, "--sentinel-namespace", "wrong", "--templates",
                                      self.f["t.json"], "--age-reference", self.f["ages.json"], "--avoid",
                                      self.f["worlds.json"], "--out", dp]), 2)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""test_refsel.py: reference selection (refsel.py, design v4 §4.2). Covers:
  * the binding to the VALIDATION registry (its sha256, namespace and the four predetermined sentinel
    identities; no override), the exclusion of every main-study and fork identity, at plan and again at
    selection;
  * the candidates, the extinction fallback (omissions and reasons recorded; a 6.9M extinction), the
    constraint feasibility search and the plan (design/2, seeds, mandatory inputs);
  * exact replicates with matched controls; observations bound to the final plan; the provenance receipt;
  * the frozen criterion; tied singular subspaces (basis invariance);
  * the greedy / swap selection: the constraints, determinism, the hash tie-breaks, the saturation
    penalty, the information criterion's preference, the convergence record;
  * the references/1 output through sealing.py's REAL loader with the fork registry (uniqueness by guild
    and snapshot), and recovery.py's forward mask on the ACTUAL selected frames;
  * the CLI's normalized refusals.
numpy required (RQ_REQUIRE_NUMPY=1 makes a missing numpy a failure).

    python3 -I tools/redqueen/test_refsel.py [-v]
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
import plan  # noqa: E402
import refsel as rs  # noqa: E402
import rqlib  # noqa: E402
import sealing  # noqa: E402
try:
    import numpy as np  # noqa: E402
except ImportError:
    if os.environ.get("RQ_REQUIRE_NUMPY"):
        raise SystemExit("RQ_REQUIRE_NUMPY is set, but numpy cannot be imported")
    np = None

NS = rs.VALIDATION_NAMESPACE
MAIN_NS = "finfolk-rq-main-2026"
LAYOUT = {"w04": "A", "w07": "A", "w05": "B", "w09": "B"}           # (arena #1's validation; the rest C)
SENT = ("w01", "w02", "w03", "w06")                                  # (the rule: the first four C worlds)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f)
    return path


def registry(ns, n=12, layout=None):
    return {"schema": rs.WORLDS_SCHEMA, "namespace": ns,
            "worlds": [{"id": f"w{i:02d}", "uuid": rs.recipe(ns, f"w{i:02d}"),
                        "treatment": (layout or {}).get(f"w{i:02d}", "C")} for i in range(1, n + 1)]}


def block(root, valid_before=None, attempts=None, attempt_uuids=False, status=None):
    """worlds.py design-block's form (no root) of the validation registry at <root>/config/worlds.json."""
    rp = os.path.join(root, "config", "worlds.json")
    if not os.path.isfile(rp):
        write_json(rp, registry(NS, layout=LAYOUT))
    ws = {}
    for i in range(1, 13):
        w = f"w{i:02d}"
        k = (attempts or {}).get(w, 0)
        u = rs.recipe(NS, w)
        ws[w] = {"uuid": u if not k or not attempt_uuids else rs.attempt_uuid(u, k),     # (worlds.py keeps the uuid)
                 "attempt": k, "treatment": LAYOUT.get(w, "C"), "block": 1, "status": "running",
                 "pattern": os.path.join(root, w, "end.{frame}.json"), "paths": {"F1": os.path.join(root, w, "F1.json")},
                 "valid_before": (valid_before or {}).get(w), "archived": [1] + [t * 1_000_000 for t in range(1, 201)]}
        if status and w in status:
            ws[w]["status"] = status[w]
    times = {"F1": 1}
    times.update({f"{t}M": t * 1_000_000 for t in range(1, 201)})
    return {"schema": "finfolk.redqueen.worldsblock/1", "registry_sha256": rqlib.sha256_file(rp), "times": times,
            "worlds": ws}


def files(tmp):
    out = {}
    for n, txt in (("t.json", "{}"), ("ages.json", "{}"), ("worlds.json", json.dumps({"reserved": []}))):
        out[n] = os.path.join(tmp, n)
        with open(out[n], "w") as f:
            f.write(txt)
    main = registry(MAIN_NS, 48)
    out["main"] = write_json(os.path.join(tmp, "study", "config", "worlds.json"), main)
    out["forks"] = write_json(os.path.join(tmp, "study", "config", "forks.json"), {"worlds": [
        {"id": "w03.o30M.s0", "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, "fork:w03:30")), "root": "w03",
         "root_uuid": main["worlds"][2]["uuid"]}]})
    out["vdir"] = os.path.join(tmp, "validation")
    return out


def final_rows(design):
    """The final plan with REAL content hashes: every endpoint's snapshot archive is created (its bytes name
    the world and frame) and hashed; templates / ages likewise."""
    rows, _, _ = plan.expand_v2(design, pending=True)
    for r in rows:
        for k in rs.HASHED:
            x = r.get(k)
            if isinstance(x, dict) and x.get("path"):
                if not os.path.isfile(x["path"]):
                    os.makedirs(os.path.dirname(x["path"]), exist_ok=True)
                    with open(x["path"], "w") as f:
                        f.write(json.dumps({"world": x.get("world"), "frame": x.get("frame"), "role": k}))
                x["sha256"] = rqlib.sha256_file(x["path"])
    return {r["id"]: r for r in rows}


def simulate(rows, seed=1, rank=2, saturate=(), noise=0.15, B=324):
    """Grid observations for the final plan's rows from a low-rank logistic model: capture logit a_i + b_j +
    u_i v_j, survival with a predator effect; saturate: candidates whose predators capture almost
    everything."""
    rng = np.random.default_rng(seed)
    cands = sorted({(r["prey"]["world"], r["prey"]["time"]) for r in rows.values()})
    pos = {c: k for k, c in enumerate(cands)}
    n = len(cands)
    a, b = rng.normal(-0.8, 0.4, n), rng.normal(0.0, 0.4, n)
    U, V = rng.normal(0, 0.6, (n, rank)), rng.normal(0, 0.6, (n, rank))
    s0, c = rng.normal(1.6, 0.3, n), rng.normal(-0.5, 0.2, n)
    for k, cnd in enumerate(cands):
        if cnd in saturate:                   # (both readouts saturated: capture ~1, exposed survival ~0)
            b[k], c[k] = 7.0, -8.0
    obs = []
    for cid, r in sorted(rows.items()):
        i = pos[(r["prey"]["world"], r["prey"]["time"])]
        o = {"cell": cid, "prey": [r["prey"]["world"], r["prey"]["time"]], "replicate": r["replicate"], "cohort": 600}
        if r["predators"] is None:
            o.update(pred=None, survivors=int(round(600 / (1 + math.exp(-(s0[i] + rng.normal(0, 0.1)))))))
        else:
            j = pos[(r["predators"]["world"], r["predators"]["time"])]
            lc = a[i] + b[j] + U[i] @ V[j] + rng.normal(0, noise)
            ls = s0[i] + c[j] - 0.3 * (U[i] @ V[j]) + rng.normal(0, 0.1)
            o.update(pred=[r["predators"]["world"], r["predators"]["time"]],
                     captures=int(round(B / (1 + math.exp(-lc)))), survivors=int(round(600 / (1 + math.exp(-ls)))))
        obs.append(o)
    return obs


def graphlib_load(path):
    import graph
    return graph.load(path)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.f = files(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def design(self, blk=None, **kw):
        args = dict(validation_dir=self.f["vdir"], main_registries=[self.f["main"]], forks=self.f["forks"])
        args.update(kw)
        return rs.make_design(blk or block(self.f["vdir"]), [self.f["t.json"]], self.f["ages.json"],
                              [self.f["worlds.json"]], **args)


@unittest.skipIf(np is None, "numpy is not installed")
class TestPlanAndBinding(Base):
    def test_plan(self):
        """32 candidates per guild (4 sentinels x 8 times), the 32 x 32 grid and 32 free controls at R = 6; the
        criterion frozen with its sha256; the binding, the availability and the block recorded."""
        d = self.design()
        r = d["refsel"]
        self.assertEqual(len(r["candidates"]), 32)
        self.assertEqual(r["omitted"], [])
        rows, _, _ = plan.expand_v2(d, pending=True)
        self.assertEqual(len(rows), (32 * 32 + 32) * 6)
        self.assertEqual(r["criterion_sha256"], rqlib.canonical_sha(rs.CRITERION))
        self.assertEqual((r["sentinels"], r["sentinel_namespace"]), (list(SENT), NS))
        self.assertEqual(r["binding"]["registry_sha256"], rqlib.sha256_file(os.path.join(self.f["vdir"], "config", "worlds.json")))
        self.assertEqual(r["availability_sha256"], rqlib.canonical_sha(r["availability"]))
        self.assertEqual({x.get("kind", "main") for x in r["binding"]["studies"]}, {"main", "forks"})
        self.assertEqual({x["role"] for x in rows}, {"diagnostic"})
        for bad in (None, "ages.json"):
            with self.assertRaises(rs.RefselError):
                rs.make_design(block(self.f["vdir"]), [self.f["t.json"]], bad, [self.f["worlds.json"]],
                               self.f["vdir"], [self.f["main"]])
        s = sorted(plan.plan_seeds(rows))[3]
        res = write_json(os.path.join(self.tmp, "prod.json"), {"reserved": [{"slot": "b1:C:0", "seeds": [s]}]})
        with self.assertRaises(rs.RefselError):
            rs.make_design(block(self.f["vdir"]), [self.f["t.json"]], self.f["ages.json"], [res], self.f["vdir"],
                           [self.f["main"]])

    def test_extinction_fallback(self):
        """The registered fallback: a sentinel is never replaced; its unusable snapshots are OMITTED with their
        reasons (recorded in the plan). A 6.9M extinction leaves F1 as that sentinel's sole candidate; a
        restarted attempt is another history (all its candidates omitted); the constraints (three sentinels,
        four early, two late) must still be satisfiable."""
        d = self.design(block(self.f["vdir"], valid_before={"w06": 6_900_000}))
        r = d["refsel"]
        self.assertEqual(len(r["candidates"]), 25)
        self.assertEqual([c for c in r["candidates"] if c[0] == "w06"], [["w06", "F1"]])
        om = [o for o in r["omitted"] if o["world"] == "w06"]
        self.assertEqual(len(om), 7)
        self.assertTrue(all("first zero" in o["reason"] for o in om))
        for au in (False, True):                       # (Codex #71 r3 P2-3: an ESTABLISHED restart is kept)
            d2 = self.design(block(self.f["vdir"], attempts={"w03": 1}, attempt_uuids=au))
            self.assertEqual(sum(1 for c in d2["refsel"]["candidates"] if c[0] == "w03"), 8)
            self.assertEqual(d2["refsel"]["availability"]["w03"]["attempt"], 1)
            self.assertEqual(len(rs.rebind(d2)), 2)
            # (Codex #71 r4 P2-2: the plan is expanded on the REGISTERED identity, so selection emits exactly
            # the assayed endpoints' identities, whatever uuid the block carried)
            self.assertEqual(d2["worlds"]["w03"]["uuid"], rs.recipe(NS, "w03"))
            rows2 = final_rows(d2)
            doc2, _ = rs.select(simulate(rows2, seed=2), d2, rows2)
            ends = {(e["world"], e["frame"]): (e["uuid"], e["snapshot"]) for r_ in rows2.values()
                    for e in (r_["prey"], r_["predators"]) if isinstance(e, dict)}
            for v in doc2["references"].values():
                self.assertEqual(ends[(v["world"], v["frame"])], (v["uuid"], v["snapshot"]))
        # (Codex #71 r4 P2-1: establishment is the evidenced burn-in decision, not the technical status)
        d3 = self.design(block(self.f["vdir"], attempts={"w03": 2}, valid_before={"w03": 3_000_000}))
        self.assertFalse(any(c[0] == "w03" for c in d3["refsel"]["candidates"]))   # (a zero before 5M: not established)
        self.assertTrue(all("not established" in o["reason"] for o in d3["refsel"]["omitted"]))
        d4 = self.design(block(self.f["vdir"], attempts={"w03": 1}, status={"w03": "failed"}))
        self.assertEqual(sum(1 for c in d4["refsel"]["candidates"] if c[0] == "w03"), 8)   # (failed later: kept)
        self.assertEqual(rs.establishment({"valid_before": None, "archived": [1, 2_000_000]})[0], False)
        # (Codex #71 r5 P2-1: survived past 5M, failed technically at 6M: archives F1, 1..6M -> ESTABLISHED, its
        # F1 a candidate; the decision uses the FULL archive, not its projection on the candidate times)
        b5 = block(self.f["vdir"], attempts={"w03": 1}, status={"w03": "failed"})
        b5["worlds"]["w03"]["archived"] = [1] + [t * 1_000_000 for t in range(1, 7)]
        d5 = self.design(b5)
        self.assertEqual(d5["refsel"]["availability"]["w03"]["archived_through"], 6_000_000)
        self.assertIn(["w03", "F1"], d5["refsel"]["candidates"])
        self.assertEqual(len(rs.rebind(d5)), 2)
        # (Codex #71 r5 P2-2: an explicit burn_in = 0 is "no burn-in rule", never the 5M default)
        v0 = os.path.join(self.tmp, "v0")
        write_json(os.path.join(v0, "config", "worlds.json"), dict(registry(NS, layout=LAYOUT), burn_in=0))
        d0 = self.design(block(v0, attempts={"w03": 1}, valid_before={"w03": 3_000_000}), validation_dir=v0)
        self.assertEqual(d0["refsel"]["availability"]["w03"]["burn_in"], 0)
        self.assertIn(["w03", "F1"], d0["refsel"]["candidates"])        # (no rule: the early-zero attempt counts)
        self.assertEqual(rs.establishment({"valid_before": 7_000_000, "archived": [1]})[0], True)
        with self.assertRaises(rs.RefselError):                         # (two usable sentinels)
            self.design(block(self.f["vdir"], valid_before={"w03": 1, "w06": 1}))
        with self.assertRaises(rs.RefselError):                         # (no late snapshot anywhere)
            self.design(block(self.f["vdir"], valid_before={w: 130_000_000 for w in SENT}))

    def test_binding(self):
        """Codex #71 r1 P1: the validation registry (its sha256 and namespace), the predetermined sentinel
        identities, and NO study identity: a main registry containing a sentinel's identity, a fork branch
        that IS a sentinel's identity, a main registry under the validation namespace, or no main registry
        at all are refused; the CLI has no --sentinels override; the binding is checked again at
        selection (a changed registry is refused)."""
        b = block(self.f["vdir"])
        with self.assertRaises(rs.RefselError):
            self.design(dict(b, registry_sha256="0" * 64))
        other = os.path.join(self.tmp, "other")
        write_json(os.path.join(other, "config", "worlds.json"), registry(MAIN_NS))
        with self.assertRaises(rs.RefselError):
            self.design(block(other), validation_dir=other)
        with self.assertRaises(rs.RefselError):
            self.design(main_registries=[])
        bad_main = registry(MAIN_NS, 4)
        bad_main["worlds"].append({"id": "w99", "uuid": rs.recipe(NS, "w02"), "treatment": "C"})
        with self.assertRaises(rs.RefselError):
            self.design(main_registries=[write_json(os.path.join(self.tmp, "m2", "worlds.json"), bad_main)])
        with self.assertRaises(rs.RefselError):
            self.design(main_registries=[write_json(os.path.join(self.tmp, "m3", "worlds.json"), registry(NS, 2))])
        fk = {"worlds": [{"id": "w01.o30M.s0", "uuid": rs.recipe(NS, "w01"), "root": "w01"}]}
        with self.assertRaises(rs.RefselError):
            self.design(forks=write_json(os.path.join(self.tmp, "fk", "forks.json"), fk))
        bad_reg = registry(NS, layout=LAYOUT)
        bad_reg["worlds"][0]["sentinel"] = True                           # (flags must agree with the rule)
        bad_reg["worlds"][3]["sentinel"] = True
        vd2 = os.path.join(self.tmp, "v2")
        write_json(os.path.join(vd2, "config", "worlds.json"), bad_reg)
        with self.assertRaises(rs.RefselError):
            self.design(block(vd2), validation_dir=vd2)
        self.assertEqual(rs.sentinels_of(registry(NS, layout=LAYOUT)), list(SENT))       # (the rule)
        moved = registry(NS, layout=dict(LAYOUT, w02="A"))
        self.assertEqual(rs.sentinels_of(moved), ["w01", "w03", "w06", "w08"])
        bp = write_json(os.path.join(self.tmp, "block.json"), b)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            rs.main(["plan", "--block", bp, "--sentinels", "w01,w02,w03,w04", "--validation-dir", self.f["vdir"],
                     "--main-registry", self.f["main"], "--templates", self.f["t.json"], "--age-reference",
                     self.f["ages.json"], "--avoid", self.f["worlds.json"], "--out", os.path.join(self.tmp, "g.json")])
        d = self.design()
        self.assertEqual(len(rs.rebind(d)), 2)
        rp = os.path.join(self.f["vdir"], "config", "worlds.json")
        reg = rqlib.read_json(rp)
        reg["note"] = "edited"
        write_json(rp, reg)
        with self.assertRaises(rs.RefselError):
            rs.rebind(d)

    def test_rebind_validates_the_pool(self):
        """Codex #71 r2 P1: at selection every candidate must be a registered sentinel at a registered time,
        consistent with the recorded availability; the registry's CONTENT (namespace, C registrations) is
        re-validated; the study exclusion covers all four sentinel identities, omitted ones included."""
        d = self.design()
        self.assertEqual(len(rs.rebind(d)), 2)
        for bad in (["w08", "20M"], ["w01", "30M"], ["w01", "20M"]):           # (not a sentinel / time; a duplicate)
            x = json.loads(json.dumps(d))
            x["refsel"]["candidates"].append(bad)
            x["worlds"].setdefault("w08", dict(x["worlds"]["w01"], uuid=rs.recipe(NS, "w08")))
            with self.assertRaises(rs.RefselError):
                rs.rebind(x)
        x = json.loads(json.dumps(d))                                       # (Codex's pruned pool: 31 + a foreign omission)
        x["refsel"]["candidates"] = [c for c in x["refsel"]["candidates"] if c != ["w02", "20M"]]
        x["refsel"]["omitted"] = [{"world": "w08", "time": "20M", "reason": "not archived"}]
        with self.assertRaises(rs.RefselError):
            rs.rebind(x)
        x["refsel"]["omitted"] = [{"world": "w02", "time": "20M", "reason": "not archived"}]   # (archived and valid)
        with self.assertRaises(rs.RefselError):
            rs.rebind(x)
        x = json.loads(json.dumps(d))                                       # (120M mapped to 160M: Codex's P1)
        x["times"]["120M"] = 160_000_000
        with self.assertRaises(rs.RefselError):
            rs.rebind(x)
        x = json.loads(json.dumps(d))
        x["refsel"]["availability"]["w02"]["valid_before"] = 50_000_000      # (the record's sha no longer matches)
        with self.assertRaises(rs.RefselError):
            rs.rebind(x)
        x["refsel"]["availability_sha256"] = rqlib.canonical_sha(x["refsel"]["availability"])
        with self.assertRaises(rs.RefselError):                              # (60M+ of w02 now inconsistent)
            rs.rebind(x)
        d6 = self.design(block(self.f["vdir"], valid_before={"w06": 6_900_000}))
        clash = registry(MAIN_NS, 4)
        clash["worlds"].append({"id": "w99", "uuid": rs.recipe(NS, "w06"), "treatment": "C"})
        with self.assertRaises(rs.RefselError):                              # (w06's omitted snapshots count too)
            rs.rebind(d6, [write_json(os.path.join(self.tmp, "m6", "worlds.json"), clash)])
        rp = os.path.join(self.f["vdir"], "config", "worlds.json")
        reg = rqlib.read_json(rp)
        reg["worlds"][1]["treatment"] = "A"                                    # (w02 no longer C: the rule moves)
        write_json(rp, reg)
        x = json.loads(json.dumps(d))
        x["refsel"]["binding"]["registry_sha256"] = rqlib.sha256_file(rp)
        with self.assertRaises(rs.RefselError):
            rs.rebind(x)

    def test_feasibility(self):
        cands = [(w, t) for w in SENT for t in rs.TIMES]
        self.assertTrue(rs.feasible([], cands))
        four_late = [("w01", "140M"), ("w01", "180M"), ("w01", "200M"), ("w04", "140M")]
        pool = [c for c in cands if c not in four_late]
        self.assertTrue(rs.feasible(four_late, pool))
        five = four_late + [("w04", "180M")]
        self.assertFalse(rs.feasible(five, [c for c in pool if c not in five]))
        three_early = [("w01", "F1"), ("w01", "20M"), ("w04", "60M"), ("w05", "140M"), ("w06", "140M"),
                       ("w06", "200M"), ("w04", "180M"), ("w05", "180M")]
        self.assertFalse(rs.feasible(three_early, []))
        two_sent = [("w01", t) for t in rs.TIMES[:4]] + [("w04", t) for t in rs.TIMES[4:]]
        self.assertFalse(rs.feasible(two_sent, []))


@unittest.skipIf(np is None, "numpy is not installed")
class TestSelection(Base):
    def setUp(self):
        super().setUp()
        self.d = self.design()
        self.rows = final_rows(self.d)
        self.cands = [tuple(c) for c in self.d["refsel"]["candidates"]]

    def test_selection_and_receipt(self):
        """Eight per guild meeting every constraint; deterministic whatever the observation order; a fully
        saturating sentinel's predators are never chosen; every swap is non-improving at the end (converged);
        the provenance receipt (observations, plan, availability, omissions, binding, implementation); the
        frozen criterion is enforced."""
        sat = {("w03", t) for t in rs.TIMES}
        obs = simulate(self.rows, seed=3, saturate=sat)
        doc, rep = rs.select(obs, self.d, self.rows, studies=rs.rebind(self.d), plan_sha="p" * 64)
        doc2, _ = rs.select(list(reversed(obs)), self.d, self.rows, studies=rs.rebind(self.d), plan_sha="p" * 64)
        self.assertEqual(json.dumps(doc, sort_keys=True), json.dumps(doc2, sort_keys=True))
        for g in ("RQ", "RP"):
            sel = rep["guilds"][g]["selected"]
            self.assertEqual(len({tuple(x) for x in sel}), 8)
            self.assertGreaterEqual(len({w for w, _ in sel}), 3)
            self.assertGreaterEqual(sum(1 for _, t in sel if rs.time_m(t) <= 120), 4)
            self.assertGreaterEqual(sum(1 for _, t in sel if rs.time_m(t) >= 140), 2)
            self.assertEqual(rep["guilds"][g]["search"]["converged"], True)
        self.assertFalse(any(tuple(x) in sat for x in rep["guilds"]["RP"]["selected"]))
        rc = doc["selection"]
        self.assertEqual(rc["observations_sha256"], rqlib.canonical_sha(sorted(obs, key=lambda o: o["cell"])))
        self.assertEqual((rc["plan_sha256"], rc["observations"]), ("p" * 64, len(obs)))
        self.assertEqual(rc["availability_sha256"], rqlib.canonical_sha(rc["availability"]))
        self.assertEqual(rc["block_sha256"], self.d["refsel"]["block_sha256"])
        self.assertEqual(rc["implementation"]["refsel_sha256"], rqlib.sha256_file(rs.__file__))
        self.assertIn("numpy", rc["implementation"])
        self.assertEqual(rep["receipt_sha256"], rqlib.canonical_sha(rc))
        changed = [dict(o) for o in obs]
        k = next(i for i, o in enumerate(changed) if o["pred"])
        changed[k]["captures"] += 1
        self.assertNotEqual(rs.select(changed, self.d, self.rows)[0]["selection"]["observations_sha256"],
                            rc["observations_sha256"])
        bad = json.loads(json.dumps(self.d))
        bad["refsel"]["criterion"]["saturation_penalty"] = 0.0
        with self.assertRaises(rs.RefselError):
            rs.select(obs, bad, self.rows)

    def test_observations_bound_to_the_plan_and_exact_replicates(self):
        """Codex #71 r1 P2-2 / P2-3: an observation that is not a plan cell, disagrees with its row or occurs
        twice is refused; a missing replicate, a missing matched control or an unregistered replicate number
        is refused (no fallback to fewer replicates)."""
        obs = simulate(self.rows, seed=7)
        with self.assertRaises(rs.RefselError):
            rs.select(obs + [dict(obs[0], cell="nope")], self.d, self.rows)
        moved = [dict(o) for o in obs]
        k = next(i for i, o in enumerate(moved) if o["pred"])
        moved[k]["replicate"] = (moved[k]["replicate"] + 1) % 6
        with self.assertRaises(rs.RefselError):
            rs.select(moved, self.d, self.rows)
        with self.assertRaises(rs.RefselError):
            rs.select(obs + [obs[0]], self.d, self.rows)
        two = [o for o in obs if o["replicate"] < 2]                   # (Codex's two-replicate counterexample)
        with self.assertRaises(rs.RefselError):
            rs.matrices(two, self.cands)
        nofree = [o for o in obs if not (o["pred"] is None and tuple(o["prey"]) == self.cands[3] and o["replicate"] == 4)]
        with self.assertRaises(rs.RefselError):
            rs.matrices(nofree, self.cands)
        for r_ in (6, -1, "1", True):
            extra = [dict(obs[-1], replicate=r_)] + obs[:-1]
            with self.assertRaises(rs.RefselError):
                rs.matrices(extra, self.cands)
        o = dict(next(x for x in obs if x["pred"]), captures=10 ** 6)
        with self.assertRaises(rs.RefselError):
            rs.matrices([o if x["cell"] == o["cell"] else x for x in obs], self.cands)
        for coh in (300, None, True):                                         # (Codex #71 r2 P2: survival / 600)
            o = dict(obs[5], cohort=coh)
            with self.assertRaises(rs.RefselError):
                rs.matrices([o if x["cell"] == o["cell"] else x for x in obs], self.cands)

    def test_information_prefers_spread(self):
        """With no saturation, a reference set whose embeddings span the rank-2 space beats one whose
        embeddings collapse onto a line (the information criterion); the tie keys are unique."""
        emb = rs.embeddings(rs.matrices(simulate(self.rows, seed=5), self.cands))
        g = emb["RP"]
        X = g["readouts"]["capture_logit"]["emb"][:, :2]
        order = np.argsort(X[:, 1])
        spread = [int(i) for i in order[:4]] + [int(i) for i in order[-4:]]
        mid = [int(i) for i in order[12:20]]
        self.assertGreater(rs.objective(g, spread), rs.objective(g, mid))
        keys = [rs.tie_key("RP", w, rs.frame_of(t)) for w, t in self.cands]
        self.assertEqual(len(set(keys)), len(keys))

    def test_tied_singular_subspaces(self):
        """Codex #71 r1 P2-6: with repeated singular values, a rank that would split the tied group is extended
        to its end, and the objective does not depend on the SVD's basis inside the group (a random rotation of
        the tied singular vectors gives the same value)."""
        S = np.array([3.0, 2.0, 2.0, 2.0 * (1 + 1e-12), 1.0, 0.5])
        self.assertEqual(rs.tied_ranks(S), {1: 1, 2: 4, 3: 4, 4: 4})
        n = 12
        rng = np.random.default_rng(3)
        Q1, _ = np.linalg.qr(rng.standard_normal((n, n)))
        Q2, _ = np.linalg.qr(rng.standard_normal((n, n)))
        sv = np.array([3.0, 2.0, 2.0, 2.0, 1.0] + [0.0] * (n - 5))
        X = Q1 @ np.diag(sv) @ Q2.T
        U, Sx, Vt = np.linalg.svd(X)
        reff = rs.tied_ranks(Sx)
        self.assertEqual(reff[2], 4)
        k = max(reff.values())
        emb = Vt[:k].T * np.sqrt(Sx[:k])
        R3, _ = np.linalg.qr(rng.standard_normal((3, 3)))
        rot = emb.copy()
        rot[:, 1:4] = emb[:, 1:4] @ R3                                # (another basis of the tied group)
        w = rng.uniform(0.5, 2.0, n)
        g = {"readouts": {"x": {"emb": emb, "w": w, "reff": reff}}, "sat": np.zeros(n)}
        g2 = {"readouts": {"x": {"emb": rot, "w": w, "reff": reff}}, "sat": np.zeros(n)}
        for idx in ([0, 1, 2, 3, 4, 5, 6, 7], [2, 4, 6, 8, 9, 10, 11, 0]):
            self.assertAlmostEqual(rs.objective(g, idx), rs.objective(g2, idx), places=9)

    def test_rank_cap_refuses_structural_degeneracy(self):
        """Codex #71 r2 P2: a tie group is followed to its end only up to rank 6; the fully symmetric centred
        matrix (31 equal singular values) is a structural degeneracy and is refused."""
        self.assertEqual(rs.tied_ranks(np.array([3.0, 2, 2, 2, 2, 2, 1.0]))[2], 6)
        with self.assertRaises(rs.RefselError):
            rs.tied_ranks(np.array([3.0, 2, 2, 2, 2, 2, 2, 1.0]))
        n = 32
        X = np.eye(n) - np.ones((n, n)) / n
        self.assertEqual(int(np.sum(np.abs(np.linalg.svd(X)[1] - 1) < 1e-9)), 31)
        mats = {k: np.zeros((n, n)) for k in ("l_mean", "q_mean", "cap_frac", "surv")}
        mats.update(l_mean=X, q_mean=0.01 * X, l_var=np.full((n, n), 0.01), q_var=np.full((n, n), 0.001),
                    cap_frac=np.full((n, n), 0.3), surv=np.full((n, n), 0.8))
        with self.assertRaises(rs.RefselError):
            rs.embeddings(mats)

    def test_swap_limit_is_reported(self):
        """Codex #71 r1 P3: the search record says whether it converged or stopped at the limit (max_swaps 0:
        converged exactly when no improving exchange of the greedy set exists)."""
        obs = simulate(self.rows, seed=11)
        emb = rs.embeddings(rs.matrices(obs, self.cands))
        crit = dict(rs.CRITERION, max_swaps=0)
        for g in ("RQ", "RP"):
            idx, log = rs.select_guild(emb[g], self.cands, g, crit)
            rec = log[-1]
            self.assertEqual((rec["max_swaps"], rec["swaps"]), (0, 0))
            v = rs.objective(emb[g], idx, crit)
            improving = False
            for s in idx:
                for c in range(len(self.cands)):
                    if c in idx or emb[g]["sat"][c] > crit["max_saturated_share"]:
                        continue
                    S = [c if x == s else x for x in idx]
                    if rs.feasible([self.cands[j] for j in S], [], crit) and \
                            rs.objective(emb[g], S, crit) > v + 1e-9 * max(1.0, abs(v)):
                        improving = True
            self.assertEqual(rec["converged"], not improving)

    def test_sealing_loader_and_recovery_integration(self):
        """Codex #71 r1 P2-4 / P2-5: the selected references/1 passes sealing.py's REAL loader with the main
        and fork registries, although one sentinel world gives several references per guild (uniqueness is
        by guild and SNAPSHOT); one snapshot twice in a guild is refused. recovery.py reads the ACTUAL frames
        per guild and slot: a reference whose slot the assumed table calls 120M but which is actually late is
        excluded from the forward fit."""
        obs = simulate(self.rows, seed=5)
        doc, _ = rs.select(obs, self.d, self.rows)
        rp = write_json(os.path.join(self.tmp, "config", "references.json"), doc)
        main = rqlib.read_json(self.f["main"])
        uuids = {w["id"]: w["uuid"] for w in main["worlds"]}
        fk = rqlib.read_json(self.f["forks"])
        branches = {b["id"]: {"uuid": b["uuid"], "root": b["root"]} for b in fk["worlds"]}
        refs = sealing.load_references(rp, uuids, branches, MAIN_NS)
        self.assertEqual(len(refs), 16)
        for g in "QP":
            worlds = [v["world"] for s_, v in refs.items() if s_[1] == g]
            self.assertLess(len(set(worlds)), 8)                         # (a sentinel world repeats in a guild)
        dup = json.loads(json.dumps(doc))
        dup["references"]["RQ:1"] = dict(dup["references"]["RQ:2"])
        with self.assertRaisesRegex(sealing.SealError, "one reference"):
            sealing.load_references(write_json(rp, dup), uuids, branches, MAIN_NS)
        import graph
        import recovery
        pick = [("w01", "F1"), ("w01", "20M"), ("w02", "60M"), ("w03", "100M"), ("w01", "140M"), ("w02", "180M"),
                ("w03", "200M"), ("w06", "140M")]                   # (exactly four early: slot 4 is 140M)
        refs4 = {"schema": rs.REFS_SCHEMA, "namespace": NS, "references": {}}
        for g in ("RQ", "RP"):
            sel = sorted(pick, key=lambda c: (rs.frame_of(c[1]), rs.tie_key(g, c[0], rs.frame_of(c[1]))))
            for k, (w, lab) in enumerate(sel):
                fr = rs.frame_of(lab)
                u = self.d["worlds"][w]["uuid"]
                refs4["references"][f"{g}:{k}"] = {"world": w, "frame": fr, "uuid": u,
                                                   "snapshot": plan.snapshot_uuid(u, fr),
                                                   "archive": plan.snapshot_path(self.d, w, lab),
                                                   "sha256": rs._archive_sha(self.rows, w, lab, g)}
        p4 = write_json(os.path.join(self.tmp, "refs4.json"), refs4)
        for v in refs4["references"].values():                           # (REAL archives: their bytes' hash)
            self.assertEqual(rqlib.sha256_file(v["archive"]), v["sha256"])
        self.assertEqual(len(sealing.load_references(p4, uuids, branches, MAIN_NS)), 16)   # (a VALID assignment)
        times, sha = recovery.reference_times(p4)
        self.assertEqual((times["RQ"][4], times["RP"][4]), (140, 140))
        gdir = os.path.join(self.tmp, "g")
        g_ = graph.build("rq-test-refsel")                          # (the default graph: lag7 probes included)
        self.assertEqual(g_["lag_probe"], graph.LAG_PROBE)
        graph.write(g_, gdir)
        gp = os.path.join(gdir, "graph.jsonl.gz")
        assumed, actual = recovery.Data(graphlib_load(gp)), recovery.load_data(gp, p4)
        for D in (assumed, actual):
            f = D.forward["fit"]
            ref = D.qref[D.qi][f] | D.pref[D.pj][f]
            reft = np.where(D.qref[D.qi][f], D.qt[D.qi][f], D.pt[D.pj][f])[ref]
            self.assertTrue((reft <= 120).all())
        slot4 = lambda D: int(sum(1 for i in D.forward["fit"]                                  # noqa: E731
                                  if (D.qref[D.qi[i]] and D.qkey[D.qi[i]].endswith(":4"))
                                  or (D.pref[D.pj[i]] and D.pkey[D.pj[i]].endswith(":4"))))
        self.assertGreater(slot4(assumed), 0)
        self.assertEqual(slot4(actual), 0)
        sup = actual.forward["reference_support"]
        self.assertEqual((sup["times"], assumed.forward["reference_support"]["times"]), ("actual", "assumed"))
        for side in ("prey", "pred"):                               # (per block x readout, persisted)
            self.assertGreater(sup[side]["populations"], 0)
            self.assertEqual(sum(v["populations"] for v in sup[side]["blocks"].values()), sup[side]["populations"])
        out = os.path.join(self.tmp, "cond.json")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(recovery.main(["conditioning", "--graph", gp, "--references", p4, "--out", out]), 0)
        cond = rqlib.read_json(out)
        self.assertEqual(cond["references"]["sha256"], sha)
        self.assertIn("fwd", cond)                                        # (the forward panel's conditioning)
        # (Codex #71 r3 P2-5: the simulated reference histories follow the ACTUAL sentinels: regrouping the same
        # slot times across other sentinels changes the data for a fixed seed; one sentinel = one history)
        self.assertEqual({int(actual.qsent[i]) for i in range(actual.nQ) if actual.qref[i]} <= set(range(4)), True)
        regroup = json.loads(json.dumps(refs4))
        for k in range(8):
            for g in ("RQ", "RP"):
                regroup["references"][f"{g}:{k}"]["world"] = ("w01", "w02", "w03", "w06")[k % 4]
        p5 = write_json(os.path.join(self.tmp, "refs5.json"), regroup)
        D5 = recovery.load_data(gp, p5)
        self.assertTrue(np.array_equal(D5.qt, actual.qt))
        sim4 = recovery.simulate(actual, recovery.SCENARIOS["r2_034"], 7)
        sim5 = recovery.simulate(D5, recovery.SCENARIOS["r2_034"], 7)
        self.assertFalse(np.allclose(sim4["zbar"], sim5["zbar"]))
        self.assertEqual(cond["reference_support"], json.loads(json.dumps(sup)))


@unittest.skipIf(np is None, "numpy is not installed")
class TestCollectAndCli(Base):
    def study(self, bundles):
        import store
        import zipfile
        root = os.path.join(self.tmp, "gstudy")
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
        d = self.design()
        rows = final_rows(d)
        pp = os.path.join(self.tmp, "plan.jsonl")
        plan.write_plan(list(rows.values()), pp)
        pick = [r for r in rows.values() if r["prey"]["world"] == "w01" and r["prey"]["time"] == "60M"
                and r["replicate"] == 0]
        self.assertEqual(len(pick), 33)

        def bundle(r, n=600):
            return {"cell": r, "score": {"n_start": n, "horizons": [{"steps": 5000, "survivors": 400, "captures": 50}]}}
        rest = sorted(set(rows) - {r["id"] for r in pick})
        doc = rs.collect(self.study({r["id"]: bundle(r) for r in pick}), d, pp, rest)
        self.assertEqual(len(doc["observations"]), 33)
        with self.assertRaises(rs.RefselError):
            rs.collect(self.study({r["id"]: bundle(r) for r in pick}), d, pp)
        with self.assertRaises(rs.RefselError):
            rs.collect(self.study({pick[0]["id"]: bundle(pick[0], 599)}), d, pp, sorted(set(rows) - {pick[0]["id"]}))

    def test_cli(self):
        """The plan CLI (the binding arguments); every refusal is a normalized exit 2 (a missing file, bad
        JSON, a refused binding), never a traceback."""
        bp, dp = os.path.join(self.tmp, "block.json"), os.path.join(self.tmp, "grid.json")
        write_json(bp, block(self.f["vdir"]))
        args = ["plan", "--block", bp, "--templates", self.f["t.json"], "--age-reference", self.f["ages.json"],
                "--avoid", self.f["worlds.json"], "--out", dp]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(rs.main(args + ["--validation-dir", self.f["vdir"], "--main-registry", self.f["main"],
                                             "--forks", self.f["forks"]]), 0)
        self.assertEqual(rqlib.read_json(dp)["refsel"]["criterion_sha256"], rqlib.canonical_sha(rs.CRITERION))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(rs.main(args + ["--validation-dir", self.f["vdir"]]), 2)          # (no main registry)
            self.assertEqual(rs.main(["plan", "--block", os.path.join(self.tmp, "none.json"), "--templates",
                                      self.f["t.json"], "--age-reference", self.f["ages.json"], "--avoid",
                                      self.f["worlds.json"], "--validation-dir", self.f["vdir"], "--main-registry",
                                      self.f["main"], "--out", dp]), 2)
            with open(os.path.join(self.tmp, "bad.json"), "w") as f:
                f.write("{not json")
            self.assertEqual(rs.main(["select", os.path.join(self.tmp, "bad.json"), "--design", dp, "--plan",
                                      os.path.join(self.tmp, "none.jsonl"), "--out", os.path.join(self.tmp, "r.json"),
                                      "--report", os.path.join(self.tmp, "rep.json")]), 2)
            with open(os.path.join(self.tmp, "arr.json"), "w") as f:
                f.write("[1, 2]")
            self.assertEqual(rs.main(["select", os.path.join(self.tmp, "arr.json"), "--design", dp, "--plan",
                                      os.path.join(self.tmp, "none.jsonl"), "--out", os.path.join(self.tmp, "r.json"),
                                      "--report", os.path.join(self.tmp, "rep.json")]), 2)
        self.assertNotIn("Traceback", err.getvalue())


if __name__ == "__main__":
    unittest.main()

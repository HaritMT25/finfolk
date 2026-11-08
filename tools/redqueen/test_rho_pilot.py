#!/usr/bin/env python3
"""test_rho_pilot.py: the H-C allocation pilot (rho_pilot.py, schema rhopilot/2). Covers:
  * the fixed allocation rule and the decision statistic;
  * the projection constants and the decision variance;
  * the exact moment expectations (against dense matrices);
  * the per-group estimator's known answers on simulated pilots, and unbalanced data;
  * the validation of observations against the plan;
  * the fixed panel, the per-snapshot namespaces and the seed checks of the plan;
  * the store-based collection.
Pure Python.

    python3 -I tools/redqueen/test_rho_pilot.py [-v]
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plan  # noqa: E402
import rho_pilot as rp  # noqa: E402
import rqlib  # noqa: E402
import store  # noqa: E402

PANEL = ["p1", "p2", "p3", "p4"]


def meta(treat, skipped=()):
    """The plan registration the estimator reads (a synthetic pilot of any size)."""
    return {"rho_pilot": {"per_world_panel": {w: list(PANEL) for w in treat}, "treatment": dict(treat),
                          "skipped": list(skipped), "replicates": rp.REPLICATES, "times_M": list(rp.TIMES_M)}}


class Rng:
    def __init__(self, seed):
        self.r = rqlib.SplitMix64(seed)

    def nrm(self):
        u1 = 1.0 - self.r.next64() / 2.0 ** 64
        u2 = self.r.next64() / 2.0 ** 64
        return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)


def simulate(treat, par, s_rep=0.02, seed=1, mu=None, times=None, free=False):
    """Pilot observations from the registered model, as integer counts of 600:
    - y_w(t) = u_w t/50 + a 10M-epoch random walk (per-50M increment SD s_e: a step SD s_e / 5) + common
      epoch effects;
    - per replicate, four panel survivals 0.5 + y + noise and a scripted 0.3 + noise (SD s_rep each);
    - par = {"C": (s_u, s_e), "K": (s_u, s_e)}."""
    g = Rng(seed)
    eta = [0.01 * math.sin(j) for j in range(len(rp.TIMES_M))]
    obs = []
    for w, T in sorted(treat.items()):
        su, se = par["C" if T == "C" else "K"]
        u = su * g.nrm() + (mu or {}).get(T, 0.0)
        walk = 0.0
        for j, t in enumerate(rp.TIMES_M):
            if j:
                walk += se / 5.0 * g.nrm()
            if times is not None and t not in times.get(w, rp.TIMES_M):
                continue
            y = u * t / 50.0 + walk + eta[j]
            for r in range(rp.REPLICATES):
                for c in PANEL:
                    s = round((0.5 + y + s_rep * g.nrm()) * 600)
                    obs.append({"world": w, "time": f"{t}M", "condition": f"neural:{c}", "replicate": r,
                                "survivors": min(600, max(0, s)), "cohort": 600})
                s = round((0.3 + s_rep * g.nrm()) * 600)
                obs.append({"world": w, "time": f"{t}M", "condition": "scripted", "replicate": r,
                            "survivors": min(600, max(0, s)), "cohort": 600})
                if free:
                    obs.append({"world": w, "time": f"{t}M", "condition": "free", "replicate": r,
                                "survivors": 480, "cohort": 600})
    return obs


PILOT = dict([(f"C{i}", "C") for i in range(8)] + [("A0", "A"), ("A1", "A"), ("B0", "B"), ("B1", "B")])
BIG = {f"w{i:03d}": "CCAB"[i % 4] for i in range(240)}     # (120 C, 60 A, 60 B)


class TestRule(unittest.TestCase):
    def test_fixed_allocation_rule(self):
        cases = [(0.0, 48), (0.85, 48), (0.8500001, 56), (1.0, 56), (1.35, 56), (1.3500001, 64), (3.0, 64),
                 (None, 64), (math.nan, 64)]
        for rho, n in cases:
            self.assertEqual(rp.allocation(rho), n, rho)
        self.assertEqual(rp.THRESHOLDS, (0.85, 1.35))
        self.assertEqual(sorted(rp.ALLOCATIONS), [48, 56, 64])
        self.assertEqual(rp.DECISION, "q75")
        self.assertEqual((rp.REPLICATES, rp.PANEL, rp.TIMES_M[0], rp.TIMES_M[-1], rp.DELTA, rp.PANEL_TIME_M),
                         (12, 4, 10, 100, 0.02, 100))
        self.assertEqual((rp.MIN_C, rp.MIN_CTRL, rp.MIN_INCREMENTS), (4, 3, 4))

    def test_projection_constants(self):
        """gamma_OLS of a random walk on the 41 coarse times is near Gemini's continuous 1.2; Sxx of x =
        t/50 on the coarse times."""
        self.assertAlmostEqual(rp.gamma_ols(), 1.2, delta=0.04)
        xs = [t / 50 for t in rp.COARSE]
        xb = sum(xs) / len(xs)
        self.assertAlmostEqual(rp.sxx_coarse(), sum((x - xb) ** 2 for x in xs), places=12)

    def test_decision_variance(self):
        """Homoskedastic: V_dec = V. Noisy controls: the block contrast governs, (V_C/4 + V_ctrl)/1.25."""
        self.assertAlmostEqual(rp.decision_variance(4e-4, 4e-4, 4e-4), 4e-4, places=18)
        self.assertAlmostEqual(rp.decision_variance(1e-4, 1e-3, 4e-4), (1e-4 / 4 + 1e-3) / 1.25, places=18)
        self.assertEqual(rp.decision_variance(1e-3, 0.0, 9e-4), 9e-4)


class TestMoments(unittest.TestCase):
    def test_exact_expectations_against_dense_matrices(self):
        """tr(P A P V) and tr(P A) by the low-rank closed forms equal the dense computation, on an
        unbalanced layout (gaps, unequal J, three treatments); the sums of squares equal r'Ar."""
        g = Rng(11)
        treat = {"c1": "C", "c2": "C", "c3": "C", "a1": "A", "a2": "A", "b1": "B"}
        epochs = {"c1": [1, 2, 3, 4, 5], "c2": [2, 3, 4, 6, 7, 8], "c3": [1, 2, 3, 4, 5, 6, 7, 8, 9],
                  "a1": [1, 3, 4, 5], "a2": [5, 6, 7, 8, 9], "b1": [1, 2, 3, 4, 5, 6]}
        inc, sig = {}, {}
        for w, js in epochs.items():
            inc[w] = [(j, g.nrm()) for j in js]
            J = len(js)
            S = [[0.0] * J for _ in range(J)]
            for a in range(J):
                S[a][a] = 1 + abs(g.nrm())
                if a + 1 < J and js[a + 1] == js[a] + 1:
                    S[a][a + 1] = S[a + 1][a] = -0.3 * abs(g.nrm())
            sig[w] = S
        lay = rp.Layout(inc, sig, treat)
        n = lay.n

        def dense(op, arg):
            cols = [op(arg, [1.0 if i == k else 0.0 for i in range(n)]) for k in range(n)]
            return [[cols[k][i] for k in range(n)] for i in range(n)]

        def mm(X, Y):
            return [[math.fsum(X[i][k] * Y[k][j] for k in range(n)) for j in range(n)] for i in range(n)]
        P = [[(1.0 if i == j else 0.0) - math.fsum(q[i] * q[j] for q in lay.Q) for j in range(n)] for i in range(n)]
        m = rp.moments(lay)
        for fi, f in enumerate(rp.FORMS):
            A = dense(lay.A, f)
            PAP = mm(mm(P, A), P)
            for bi, b in enumerate(rp.BASES + [("S", None)]):
                V = dense(lay.V, b)
                want = math.fsum(PAP[i][k] * V[k][i] for i in range(n) for k in range(n))
                got = m["K"][fi][bi] if bi < 4 else m["c"][fi]
                self.assertAlmostEqual(got, want, places=10, msg=(f, b))
            self.assertAlmostEqual(m["df"][fi], math.fsum(PAP[i][i] for i in range(n)), places=10)
            r = lay.r
            self.assertAlmostEqual(m["q"][fi], math.fsum(r[i] * A[i][k] * r[k] for i in range(n) for k in range(n)),
                                   places=12)


class TestEstimator(unittest.TestCase):
    def test_known_answers_per_group(self):
        """Large simulated pilots (assay noise SD 0.005, so the test is sharp; the estimator's bias was
        checked over 40 seeds at 0.02, within 1 SE for every component): each group's components are
        recovered with the assay noise removed (tolerances ~3 SE of a 3-seed mean); the projection, the
        envelope and rho are the registered formulas."""
        par = {"C": (0.02, 0.03), "K": (0.012, 0.02)}
        runs = [rp.estimate(simulate(BIG, par, s_rep=0.005, seed=sd), meta(BIG), boot=20) for sd in (3, 5, 7)]
        self.assertTrue(all(r["available"] for r in runs))
        for grp, key in (("C", "C"), ("controls", "K")):
            su = sum(r["components"][grp]["s_u2"] for r in runs) / 3
            se = sum(r["components"][grp]["s_e2"] for r in runs) / 3
            self.assertAlmostEqual(su, par[key][0] ** 2, delta=0.3 * par[key][0] ** 2, msg=grp)
            self.assertAlmostEqual(se, par[key][1] ** 2, delta=0.15 * par[key][1] ** 2, msg=grp)
        res = runs[0]
        g = rp.gamma_ols()
        V = {}
        for grp in ("C", "controls"):
            c = res["components"][grp]
            V[grp] = c["s_u2"] + g * c["s_e2"] / 20 + c["assay_prod"]
            self.assertAlmostEqual(c["V"], V[grp], places=15)
        Vd = max(res["pooled"]["V"], (V["C"] / 4 + V["controls"]) / 1.25)
        self.assertAlmostEqual(res["decision_variance"]["V_dec"], Vd, places=15)
        self.assertAlmostEqual(res["rho_point"], math.sqrt(Vd) / 0.02, places=12)

    def test_pure_assay_noise_and_treatment_means(self):
        """No world-level variation: both groups' components near zero (the assay noise is removed);
        treatment means are not between-world variance."""
        res0 = rp.estimate(simulate(BIG, {"C": (0, 0), "K": (0, 0)}, seed=4), meta(BIG), boot=20)
        for grp in ("C", "controls"):
            self.assertLess(res0["components"][grp]["s_e2"], 0.25 * 0.03 ** 2, grp)
            self.assertLess(res0["components"][grp]["s_u2"], 0.25 * 0.015 ** 2, grp)
        par = {"C": (0.02, 0.03), "K": (0.012, 0.02)}
        a = rp.estimate(simulate(BIG, par, seed=6), meta(BIG), boot=20)
        b = rp.estimate(simulate(BIG, par, seed=6, mu={"A": 0.2, "B": -0.2, "C": 0.05}), meta(BIG), boot=20)
        for grp in ("C", "controls"):
            for k in ("s_u2", "s_e2"):
                self.assertAlmostEqual(a["components"][grp][k], b["components"][grp][k], delta=0.02 * par["C"][1] ** 2)

    def test_registered_pilot_and_decision(self):
        """The registered 8C + 2A + 2B pilot: the degrees of freedom (between 7 and 2; within below 64
        and 32 by the epoch effects' share); the decision is the bootstrap q75; deterministic whatever the
        observation order."""
        obs = simulate(PILOT, {"C": (0.02, 0.03), "K": (0.02, 0.03)}, seed=9, free=True)
        r1 = rp.estimate(obs, meta(PILOT), boot=300)
        r2 = rp.estimate(list(reversed(obs)), meta(PILOT), boot=300)
        self.assertEqual(json.dumps(r1, sort_keys=True), json.dumps(r2, sort_keys=True))
        self.assertTrue(r1["available"])
        c, k = r1["components"]["C"], r1["components"]["controls"]
        self.assertAlmostEqual(c["df_between"], 7.0, delta=0.5)
        self.assertAlmostEqual(k["df_between"], 2.0, delta=0.5)
        self.assertTrue(56 < c["df_within"] < 64 and 26 < k["df_within"] < 32, (c, k))
        self.assertEqual(r1["rho_decision"], r1["rho_q75"])
        self.assertEqual(r1["allocation"], rp.allocation(r1["rho_q75"]))
        lo, hi = r1["ci90"]
        self.assertLessEqual(lo, r1["rho_q75"])
        self.assertLessEqual(r1["rho_q75"], hi)
        self.assertEqual(r1["report"]["replicates_without_free"], 0)

    def test_no_complete_case_dropping(self):
        """A world extinct after 60M keeps its 5 increments; a world with 3 is excluded (reported); a
        replicate missing a panel cell drops that replicate only."""
        times = {"C0": [10, 20, 30, 40, 50, 60], "C1": [10, 20, 30, 40]}
        skipped = [{"world": "C0", "time": f"{t}M", "reason": "biological: at or after ..."} for t in (70, 80, 90, 100)]
        obs = simulate(PILOT, {"C": (0.02, 0.03), "K": (0.02, 0.03)}, seed=5, times=times)
        obs = [o for o in obs if not (o["world"] == "C2" and o["time"] == "50M" and o["replicate"] == 3
                                      and o["condition"] == "neural:p2")]
        m = meta(PILOT, skipped)
        series, rep = rp.contrasts(obs, m["rho_pilot"])
        self.assertEqual(rep["dropped_replicates"], [{"world": "C2", "time": "50M", "replicate": 3}])
        self.assertEqual(series["C2"][4][2], 11)
        self.assertEqual(series["C2"][3][2], 12)
        self.assertEqual(rep["missing_snapshots"], [{"world": "C1", "time": f"{t}M"} for t in (50, 60, 70, 80, 90, 100)])
        res = rp.estimate(obs, m, boot=50)
        self.assertTrue(res["available"])
        self.assertIn("C0", res["entered"]["C"])
        self.assertEqual(res["excluded_worlds"], {"C1": "3 increments (< 4)"})
        self.assertEqual(len(res["post_burn_in_extinctions"]), 4)

    def test_unavailable(self):
        """Fewer than 4 C worlds, or no B control: unavailable -> the conservative 64."""
        few = {"C0": "C", "C1": "C", "C2": "C", "A0": "A", "A1": "A", "B0": "B"}
        r = rp.estimate(simulate(few, {"C": (0.02, 0.03), "K": (0.02, 0.03)}), meta(few), boot=10)
        self.assertEqual((r["available"], r["allocation"], r["rho_decision"]), (False, 64, None))
        nob = {"C0": "C", "C1": "C", "C2": "C", "C3": "C", "A0": "A", "A1": "A", "A2": "A"}
        r = rp.estimate(simulate(nob, {"C": (0.02, 0.03), "K": (0.02, 0.03)}), meta(nob), boot=10)
        self.assertEqual((r["available"], r["allocation"]), (False, 64))
        self.assertIn("1 B", r["reason"])


class TestValidation(unittest.TestCase):
    def test_observations_against_the_plan(self):
        """Duplicates (whatever their values), unregistered conditions, replicates, counts, worlds and
        snapshots outside the plan are refused."""
        m = meta(PILOT, [{"world": "C0", "time": "100M", "reason": "biological"}])["rho_pilot"]
        base = [o for o in simulate({"C0": "C"}, {"C": (0.02, 0.03), "K": (0.02, 0.03)}) if o["time"] != "100M"]
        self.assertEqual(len(rp.validate(base, m)), len(base))
        o = dict(base[0])
        bad = [
            ([o, dict(o, survivors=o["survivors"] - 1)], "occurs twice"),
            ([o, dict(o)], "occurs twice"),
            ([dict(o, condition="neural:C5")], "registered"),
            ([dict(o, replicate=12)], "replicate"),
            ([dict(o, replicate=True)], "replicate"),
            ([dict(o, survivors=300.0)], "survivors"),
            ([dict(o, survivors=601)], "survivors"),
            ([dict(o, survivors=-1)], "survivors"),
            ([dict(o, cohort=0, survivors=0)], "survivors"),
            ([dict(o, world="Z9")], "not a pilot world"),
            ([dict(o, time="15M")], "not planned"),
            ([dict(o, time="100M")], "not planned"),
        ]
        for obs, word in bad:
            with self.assertRaises(rp.PilotError) as cm:
                rp.validate(obs, m)
            self.assertIn(word, str(cm.exception))


def make_block(tmp, valid_before=None):
    ws = {}
    for i, T in enumerate(["C"] * 8 + ["A", "A", "B", "B"]):
        w = f"w{i + 1:02d}"
        ws[w] = {"uuid": f"00000000-0000-0000-0000-{i + 1:012d}", "treatment": T, "block": 0, "status": "done",
                 "pattern": os.path.join(tmp, w, "end.{frame}.json"), "paths": {},
                 "valid_before": (valid_before or {}).get(w), "archived": [t * 1_000_000 for t in rp.TIMES_M]}
    return {"schema": "finfolk.redqueen.worldsblock/1", "registry_sha256": "x" * 64,
            "times": {f"{t}M": t * 1_000_000 for t in range(5, 101, 5)}, "worlds": ws}


def files(tmp):
    out = {}
    for n, txt in (("t.json", "{}"), ("ages.json", "{}"), ("worlds.json", json.dumps({"reserved": []}))):
        out[n] = os.path.join(tmp, n)
        with open(out[n], "w") as f:
            f.write(txt)
    return out


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.f = files(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def design(self, block, avoid=None):
        return rp.make_design(block, [self.f["t.json"]], self.f["ages.json"], avoid or [self.f["worlds.json"]])

    def test_fixed_panel_and_namespaces(self):
        """The panel: five C worlds in hash order, valid at 100M, the same at every time; a panel world
        meets the fifth instead of itself; one namespace per prey snapshot; every cell its own
        transplant group; the conditions of one (w, t, r) share their common prey; deterministic."""
        cw = sorted([f"w{i:02d}" for i in range(1, 9)],
                    key=lambda c: hashlib.sha256(f"{rp.NAMESPACE}|rho-panel|{c}".encode()).hexdigest())
        first = cw[0]
        block = make_block(self.tmp, valid_before={first: 95_000_000, "w10": 55_000_000})
        d1, notes = self.design(block)
        d2, _ = self.design(block)
        self.assertEqual(json.dumps(d1, sort_keys=True), json.dumps(d2, sort_keys=True))
        panel = d1["rho_pilot"]["panel"]
        self.assertEqual(panel, cw[1:6])                     # (the first is not valid at 100M)
        why = "biological: at or after the world's first zero (frame {})"
        self.assertEqual(notes["skipped"], [{"world": first, "time": "100M", "reason": why.format(95000000)}]
                         + [{"world": "w10", "time": f"{t}M", "reason": why.format(55000000)}
                            for t in (60, 70, 80, 90, 100)])
        for w in block["worlds"]:
            want = [c for c in panel if c != w][:4]
            self.assertEqual(d1["rho_pilot"]["per_world_panel"][w], want)
            for t in ("10M", "50M"):
                es = [e for e in d1["edges"] if e["prey"] == {"world": w, "time": t}]
                self.assertEqual([e["predators"]["world"] for e in es if e["family"] == "rho-neural"], want)
                self.assertTrue(all(e["predators"]["time"] == "100M" for e in es if e["family"] == "rho-neural"))
                self.assertEqual([e["predators"] for e in es if e["family"] != "rho-neural"],
                                 [{"source": "scripted"}, None])
                self.assertEqual({e["namespace"] for e in es}, {f"rho-{w}-{t[:-1]}m"})
        self.assertEqual(d1["rho_pilot"]["per_world_panel"][panel[0]], panel[1:5])
        rows, _, _ = plan.expand_v2(d1, pending=True)
        self.assertEqual(len(rows), (12 * 10 - 6) * 6 * 12)
        self.assertEqual(d1["rho_pilot"]["cells"], len(rows))
        self.assertEqual(len({r["groups"]["transplant"] for r in rows}), len(rows))     # (every cell its own draw)
        self.assertEqual(len({r["seeds"]["transplant"] for r in rows}), len(rows))
        g = {}
        for r in rows:
            g.setdefault((r["prey"]["world"], r["prey"]["time"], r["replicate"]), set()).add(r["groups"]["common"])
        self.assertTrue(all(len(v) == 1 for v in g.values()))
        self.assertEqual(len(g), (12 * 10 - 6) * 12)
        self.assertEqual({r["role"] for r in rows}, {"diagnostic"})
        self.assertTrue(all(r["ages"]["path"] == self.f["ages.json"] for r in rows))

    def test_refusals(self):
        """Mandatory age reference and --avoid; a reserved seed (nested, as in a worlds registry) or a
        plan's seed is refused; fewer than five valid panel candidates are refused."""
        block = make_block(self.tmp)
        for ages in (None, "ages.json", os.path.join(self.tmp, "none.json")):
            with self.assertRaises(rp.PilotError):
                rp.make_design(block, [self.f["t.json"]], ages, [self.f["worlds.json"]])
        with self.assertRaises(rp.PilotError):
            rp.make_design(block, [self.f["t.json"]], self.f["ages.json"], [])
        d, _ = self.design(block)
        rows, _, _ = plan.expand_v2(d, pending=True)
        s = sorted(plan.plan_seeds(rows))[7]
        reg = os.path.join(self.tmp, "prod.json")
        with open(reg, "w") as f:
            json.dump({"worlds": [{"founder_seed": 1}], "reserved": [{"slot": "b1:C:0", "seeds": [5, s]}]}, f)
        with self.assertRaises(rp.PilotError) as cm:
            self.design(block, [self.f["worlds.json"], reg])
        self.assertIn("reserved", str(cm.exception))
        pl = os.path.join(self.tmp, "plan.jsonl")
        with open(pl, "w") as f:
            for r in rows[:3]:
                f.write(json.dumps(r) + "\n")
        with self.assertRaises(rp.PilotError):
            self.design(block, [pl])
        dead = {f"w{i:02d}": 50_000_000 for i in range(1, 5)}
        with self.assertRaises(rp.PilotError) as cm:
            self.design(make_block(self.tmp, valid_before=dead))
        self.assertIn("panel needs 5", str(cm.exception))


def final_plan(design, path):
    """The final plan as plan.py --against writes it: the expansion with every content hash filled."""
    rows, _, _ = plan.expand_v2(design, pending=True)
    for r in rows:
        for k in rp.HASHED:
            if isinstance(r.get(k), dict) and r[k].get("path"):
                r[k]["sha256"] = hashlib.sha256(f"{k}|{r[k]['path']}".encode()).hexdigest()
    plan.write_plan(rows, path)
    return {r["id"]: r for r in rows}


class TestCli(unittest.TestCase):
    def test_plan_and_estimate(self):
        """The CLI: plan writes the design; estimate reads the bound observation document (the plan's own
        cells and seeds) and writes the result with its provenance; refusals exit 2; --age-reference is
        required."""
        tmp = tempfile.mkdtemp()
        try:
            f = files(tmp)
            bp, dp, pp, op, rpth = (os.path.join(tmp, n) for n in
                                    ("block.json", "design.json", "plan.jsonl", "obs.json", "rho.json"))
            with open(bp, "w") as fh:
                json.dump(make_block(tmp), fh)
            args = ["plan", "--block", bp, "--templates", f["t.json"], "--age-reference", f["ages.json"],
                    "--avoid", f["worlds.json"], "--out", dp]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(rp.main(args), 0)
            d = rqlib.read_json(dp)
            rows = final_plan(d, pp)
            g = Rng(2)
            ys = {}
            obs = []
            for cid in sorted(rows):
                r = rows[cid]
                key = rp._key(r)
                y = ys.setdefault((key["world"], key["time"]), 0.01 * g.nrm())
                sv = round((0.5 + (y if key["condition"].startswith("neural") else 0) + 0.02 * g.nrm()) * 600)
                obs.append(dict(key, survivors=sv, cohort=600, cell=cid, seeds=r["seeds"]))
            doc = {"schema": rp.OBS_SCHEMA, "design_sha256": rqlib.canonical_sha(d),
                   "plan_sha256": rqlib.sha256_file(pp), "plan_cells": len(rows), "collected": len(obs),
                   "missing": [], "observations": obs}
            rqlib.write_json_durable(op, doc)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(rp.main(["estimate", op, "--design", dp, "--plan", pp, "--boot", "40",
                                          "--out", rpth]), 0)
            res = rqlib.read_json(rpth)
            self.assertTrue(res["available"])
            self.assertEqual(res["allocation"], rp.allocation(res["rho_decision"]))
            self.assertEqual(res["provenance"]["plan_sha256"], rqlib.sha256_file(pp))
            bad = dict(doc, observations=obs[:-1])                     # (a cell neither collected nor declared)
            rqlib.write_json_durable(op, bad)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(rp.main(["estimate", op, "--design", dp, "--plan", pp, "--boot", "5"]), 2)
                with self.assertRaises(SystemExit):
                    rp.main([a for a in args if a not in ("--age-reference", f["ages.json"])])
        finally:
            shutil.rmtree(tmp)


class TestCollect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.f = files(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def study(self, bundles):
        root = os.path.join(self.tmp, "study")
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(os.path.join(root, store.CHUNKS))
        cells = {}
        with zipfile.ZipFile(os.path.join(root, store.CHUNKS, "c0001.zip"), "w") as z:
            for cid, b in bundles.items():
                data = json.dumps(b).encode()
                z.writestr(f"{cid}/bundle.json", data)
                cells[cid] = {"bundle_sha256": rqlib.sha256_bytes(data)}
        with open(os.path.join(root, store.INDEX), "w") as f:
            f.write(json.dumps({"chunk": "c0001.zip", "cells": cells}) + "\n")
        return root

    def test_collect_bound_to_the_final_plan(self):
        """#69 round 2, P1-5: collection is bound to the FINAL plan: every bundle carries its plan row
        exactly and the registered cohort; every plan cell is collected or declared missing, exactly; the
        plan itself must be the design's expansion with every hash filled; the document's binding is
        re-checked by estimate; a tampered bundle is refused by the index."""
        d, _ = rp.make_design(make_block(self.tmp), [self.f["t.json"]], self.f["ages.json"], [self.f["worlds.json"]])
        pp = os.path.join(self.tmp, "plan.jsonl")
        rows = final_plan(d, pp)
        pick = [r for r in rows.values() if r["prey"]["world"] == "w09" and r["prey"]["time"] == "20M"
                and r["replicate"] == 0]
        self.assertEqual(len(pick), 6)
        rest = sorted(set(rows) - {r["id"] for r in pick})

        def bundle(r, surv=400, n=600):
            return {"cell": r, "score": {"n_start": n, "horizons": [{"steps": 5000, "survivors": surv}]}}
        bs = {r["id"]: bundle(r, 300 + i) for i, r in enumerate(pick)}
        bs["other.r00"] = {"cell": {"design": "production"}, "score": {}}
        doc = rp.collect(self.study(bs), d, pp, rest)
        self.assertEqual((doc["collected"], doc["plan_cells"], len(doc["missing"])), (6, len(rows), len(rest)))
        self.assertEqual(doc["plan_sha256"], rqlib.sha256_file(pp))
        obs = doc["observations"]
        self.assertEqual(sorted(o["condition"] for o in obs),
                         sorted([f"neural:{c}" for c in d["rho_pilot"]["per_world_panel"]["w09"]] + ["scripted", "free"]))
        self.assertEqual(sorted(o["survivors"] for o in obs), list(range(300, 306)))
        self.assertEqual(rp.bound_observations(doc, d, pp)[1]["collected"], 6)
        root = self.study(bs)
        with self.assertRaises(rp.PilotError):                           # (missing cells, undeclared)
            rp.collect(root, d, pp)
        with self.assertRaises(rp.PilotError):                           # (a declaration that does not match)
            rp.collect(root, d, pp, rest[:-1])
        cases = [dict(pick[0], id="w09.20M~nope.r00"),                     # (not a plan cell)
                 dict(pick[0], seeds=dict(pick[0]["seeds"], transplant=1)),
                 dict(pick[0], ages={"path": "/other/ages.json", "sha256": "a" * 64}),
                 dict(pick[0], template=dict(pick[0]["template"], sha256="b" * 64))]
        for c in cases:
            with self.assertRaises(rp.PilotError):
                rp.collect(self.study({c["id"]: bundle(c)}), d, pp, sorted(set(rows) - {c["id"]}))
        with self.assertRaises(rp.PilotError):                           # (the registered cohort)
            rp.collect(self.study({pick[0]["id"]: bundle(pick[0], n=599)}), d, pp,
                       sorted(set(rows) - {pick[0]["id"]}))
        root = self.study({pick[0]["id"]: bundle(pick[0])})
        idx = os.path.join(root, store.INDEX)
        with open(idx) as f:
            rec = json.loads(f.read())
        rec["cells"][pick[0]["id"]]["bundle_sha256"] = "0" * 64
        with open(idx, "w") as f:
            f.write(json.dumps(rec) + "\n")
        with self.assertRaises(store.StoreError):
            rp.collect(root, d, pp, sorted(set(rows) - {pick[0]["id"]}))
        # the plan itself: a pending one, a row that differs from the design, another design (ages file)
        pend, _, _ = plan.expand_v2(d, pending=True)
        plan.write_plan(pend, os.path.join(self.tmp, "pending.jsonl"))
        with self.assertRaises(rp.PilotError):
            rp.bind_plan(d, os.path.join(self.tmp, "pending.jsonl"))
        other_ages = os.path.join(self.tmp, "ages2.json")
        with open(other_ages, "w") as f:
            f.write("{}")
        d2, _ = rp.make_design(make_block(self.tmp), [self.f["t.json"]], other_ages, [self.f["worlds.json"]])
        with self.assertRaises(rp.PilotError):
            rp.bind_plan(d2, pp)
        with self.assertRaises(rp.PilotError):                           # (the document under another design)
            rp.bound_observations(doc, d2, pp)


class TestBootstrap(unittest.TestCase):
    def test_fitted_model_simulation(self):
        """#69 round 2, P1-1: the bootstrap simulates whole data sets from the FITTED Gaussian model at the
        replicate level and reruns the complete estimator. The assay terms via the linear coefficients
        equal the trace route; simulated data at known components re-estimate them (the pipeline at the
        fitted parameters is consistent); the replicate variances are re-estimated in every draw."""
        par = {"C": (0.02, 0.03), "K": (0.012, 0.02)}
        obs = simulate(BIG, par, s_rep=0.01, seed=21)
        rpm = meta(BIG)["rho_pilot"]
        series, _ = rp.contrasts(obs, rpm)
        core = rp.Core(series, BIG, sorted(series))
        est = core.evaluate(series)
        for a, b in zip(est["c"], core.m["c"]):
            self.assertAlmostEqual(a, b, delta=1e-10 * max(1.0, abs(b)))
        truth = dict(est, comp=((0.02 ** 2, 0.03 ** 2), (0.012 ** 2, 0.02 ** 2), (0.0, 0.0)))
        rng = rqlib.SplitMix64(5)
        acc = {k: [] for k in ("uC", "eC", "uK", "eK")}
        vdiff = 0.0
        for _ in range(6):
            sim = core.simulate(rng, truth, series)
            e = core.evaluate(sim)
            (uc, ec), (uk, ek), _ = e["comp"]
            for k, v in zip(acc, (uc, ec, uk, ek)):
                acc[k].append(v)
            vdiff += sum(abs(sim[w][j][1] - series[w][j][1]) for w in sim for j in sim[w])
        mean = {k: sum(v) / len(v) for k, v in acc.items()}
        self.assertAlmostEqual(mean["uC"], 0.02 ** 2, delta=0.25 * 0.02 ** 2)
        self.assertAlmostEqual(mean["eC"], 0.03 ** 2, delta=0.12 * 0.03 ** 2)
        self.assertAlmostEqual(mean["uK"], 0.012 ** 2, delta=0.35 * 0.012 ** 2)
        self.assertAlmostEqual(mean["eK"], 0.02 ** 2, delta=0.15 * 0.02 ** 2)
        self.assertGreater(vdiff, 0.0)
        self.assertEqual({w: sorted(v) for w, v in sim.items()}, {w: sorted(v) for w, v in series.items()})
        r1 = rp.estimate(obs[:20000], meta(BIG), boot=30)
        r2 = rp.estimate(list(reversed(obs[:20000])), meta(BIG), boot=30)
        self.assertEqual(r1["rho_q75"], r2["rho_q75"])


class TestValBlock(unittest.TestCase):
    def test_block_from_the_validation_layout(self):
        """val_block.py: the worlds block of runner_val.py's layout: the current attempt only (another
        uuid for a restarted world), every checkpoint opened (a mismatched one is not archived), the first
        main-CSV zero over the attempt's segments; rho_pilot plans from it."""
        import uuid as uuidlib
        import val_block
        tmp = tempfile.mkdtemp()
        try:
            root = os.path.join(tmp, "validation")
            ws = []
            for i, T in enumerate(["C", "A", "B", "C", "C", "C", "C", "B", "A", "C", "C", "C"]):
                ws.append({"id": f"w{i + 1:02d}", "uuid": f"00000000-0000-0000-0000-{i + 1:012d}", "treatment": T,
                           "block": i // 6 + 1})
            os.makedirs(os.path.join(root, "config"))
            with open(os.path.join(root, "config", "worlds.json"), "w") as f:
                json.dump({"worlds": ws}, f)
            for w in ws:
                k = 1 if w["id"] == "w05" else 0
                base = os.path.join(root, "worlds", w["id"])
                ad = os.path.join(base, f"a{k}")
                os.makedirs(os.path.join(ad, "runs"))
                with open(os.path.join(base, "state.json"), "w") as f:
                    json.dump({"attempt": k}, f)
                if w["id"] != "w03":                                    # (w03: no founding snapshot)
                    with open(os.path.join(ad, "F1.json"), "w") as f:
                        json.dump({"world": {"frame": 1 if w["id"] != "w06" else 2}}, f)   # (w06's is wrong)
                for t in range(1, 101):
                    fr = t * 1_000_000 if not (w["id"] == "w07" and t == 40) else 1
                    with open(os.path.join(ad, f"end.{t * 1_000_000}.json"), "w") as f:
                        json.dump({"world": {"frame": fr}}, f)
                zero = 63_000_000 if w["id"] == "w04" else None
                with open(os.path.join(ad, "runs", "seg000.csv"), "w") as f:
                    f.write("step,elapsed_s,population,predator_pop\n")
                    for fr in range(5_000_000, 60_000_001, 5_000_000):
                        f.write(f"{fr},1.0,500,10\n")
                with open(os.path.join(ad, "runs", "seg001.csv"), "w") as f:
                    f.write("step,elapsed_s,population,predator_pop\n")
                    for fr in range(60_000_000, 101_000_000, 1_000_000):
                        f.write(f"{fr},1.0,{0 if zero and fr >= zero else 500},10\n")
                    f.write("101000")                                     # (a torn last line)
            b = val_block.block(root)
            v = b["worlds"]
            self.assertEqual(v["w05"]["uuid"], str(uuidlib.uuid5(uuidlib.NAMESPACE_URL,
                                                                 "finfolk:attempt:00000000-0000-0000-0000-000000000005:1")))
            self.assertEqual(v["w01"]["uuid"], ws[0]["uuid"])
            self.assertEqual(v["w04"]["valid_before"], 63_000_000)
            self.assertIsNone(v["w01"]["valid_before"])
            self.assertNotIn(40_000_000, v["w07"]["archived"])
            self.assertEqual(len(v["w01"]["archived"]), 101)                  # (F1 and 1..100M)
            self.assertEqual(b["times"]["F1"], 1)
            self.assertEqual(v["w01"]["paths"]["F1"], os.path.join(root, "worlds", "w01", "a0", "F1.json"))
            self.assertEqual(v["w01"]["archived"][0], 1)
            for bad in ("w03", "w06"):                                        # (missing / not frame 1)
                self.assertEqual((v[bad]["paths"], 1 in v[bad]["archived"]), ({}, False))
            self.assertTrue(v["w05"]["pattern"].endswith(os.path.join("w05", "a1", "end.{frame}.json")))
            f = files(tmp)
            d, notes = rp.make_design(b, [f["t.json"]], f["ages.json"], [f["worlds.json"]])
            sk = {(x["world"], x["time"]): x["reason"] for x in notes["skipped"]}
            self.assertEqual(sorted(t for w, t in sk if w == "w04"), ["100M", "70M", "80M", "90M"])
            self.assertTrue(sk[("w07", "40M")].startswith("technical"))
            self.assertTrue(sk[("w04", "70M")].startswith("biological"))
            self.assertNotIn("w04", d["rho_pilot"]["panel"])
            self.assertTrue(d["edges"][0]["prey"]["world"].startswith("w"))
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()

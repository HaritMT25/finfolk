#!/usr/bin/env python3
"""test_rho_pilot.py: the H-C allocation pilot (rho_pilot.py): the fixed allocation rule, the projection
constants, the estimator's known answers on simulated pilots, the plan (panels, exclusions, plan.py's
design/2 expansion), determinism. Pure Python.

    python3 -I tools/redqueen/test_rho_pilot.py [-v]
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plan  # noqa: E402
import rho_pilot as rp  # noqa: E402
import rqlib  # noqa: E402


def simulate(treat, s_u, s_e, s_rep, seed=1, mu=None):
    """Pilot observations from the registered model: y_w(t) = u_w t/50 + a 10M-epoch random walk (per-
    50M increment SD s_e: a raw step SD s_e / 5) + common epoch effects; per replicate z = y + noise
    (SD s_rep), realised as four equal neural survivals 0.5 + z and a scripted 0.5."""
    rng = rqlib.SplitMix64(seed)

    def nrm():
        u1 = 1.0 - rng.next64() / 2.0 ** 64
        u2 = rng.next64() / 2.0 ** 64
        return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
    eta = [0.01 * math.sin(j) for j in range(len(rp.TIMES_M))]
    obs = []
    for w, T in sorted(treat.items()):
        u = s_u * nrm() + (mu or {}).get(T, 0.0)
        walk = 0.0
        for j, t in enumerate(rp.TIMES_M):
            if j:
                walk += s_e / 5.0 * nrm()
            y = u * t / 50.0 + walk + eta[j]
            for r in range(rp.REPLICATES):
                z = y + s_rep * nrm()
                for k in range(rp.PANEL):
                    obs.append({"world": w, "time": f"{t}M", "condition": f"neural:c{k}", "replicate": r,
                                "survivors": (0.5 + z) * 600, "cohort": 600})
                obs.append({"world": w, "time": f"{t}M", "condition": "scripted", "replicate": r,
                            "survivors": 300.0, "cohort": 600})
                obs.append({"world": w, "time": f"{t}M", "condition": "free", "replicate": r,
                            "survivors": 480.0, "cohort": 600})
    return obs


class TestRhoPilot(unittest.TestCase):
    def test_fixed_allocation_rule(self):
        cases = [(0.0, 48), (0.85, 48), (0.8500001, 56), (1.0, 56), (1.35, 56), (1.3500001, 64), (3.0, 64),
                 (None, 64), (math.nan, 64)]
        for rho, n in cases:
            self.assertEqual(rp.allocation(rho), n, rho)
        self.assertEqual(rp.THRESHOLDS, (0.85, 1.35))
        self.assertEqual(sorted(rp.ALLOCATIONS), [48, 56, 64])
        self.assertEqual((rp.REPLICATES, rp.PANEL, rp.TIMES_M[0], rp.TIMES_M[-1], rp.DELTA), (12, 4, 10, 100, 0.02))

    def test_projection_constants(self):
        """gamma_OLS of a random walk on the 41 coarse times is near Gemini's continuous 1.2; the endpoint
        window is cheaper; Sxx of x = t/50 on the coarse times."""
        g = rp.gamma_ols()
        self.assertAlmostEqual(g, 1.2, delta=0.04)
        self.assertLess(rp.gamma_endpoint(), g)
        xs = [t / 50 for t in rp.COARSE]
        xb = sum(xs) / len(xs)
        self.assertAlmostEqual(rp.sxx_coarse(), sum((x - xb) ** 2 for x in xs), places=12)

    def test_estimator_known_answers(self):
        """Large simulated pilots: the components are recovered (assay noise removed), and the
        projection is the registered formula."""
        treat = {f"w{i:03d}": "CAB"[i % 3] for i in range(240)}
        runs = [rp.estimate(simulate(treat, s_u=0.015, s_e=0.03, s_rep=0.02, seed=sd), treat, boot=50)
                for sd in (3, 5, 7)]
        self.assertTrue(all(r["available"] for r in runs))
        su = sum(r["components"]["s_u2"] for r in runs) / 3
        se = sum(r["components"]["s_e2"] for r in runs) / 3
        self.assertAlmostEqual(su, 0.015 ** 2, delta=0.15 * 0.015 ** 2)    # (unbiased: 3 x 240 worlds)
        self.assertAlmostEqual(se, 0.03 ** 2, delta=0.08 * 0.03 ** 2)
        res = runs[0]
        c = res["components"]
        V = c["s_u2"] + rp.gamma_ols() * c["s_e2"] / 20 + c["assay_prod"]
        self.assertAlmostEqual(c["V"], V, places=15)
        self.assertAlmostEqual(res["rho_hat"], math.sqrt(V) / 0.02, places=12)
        # pure assay noise: both components near zero
        res0 = rp.estimate(simulate(treat, 0.0, 0.0, 0.02, seed=4), treat, boot=50)
        self.assertLess(res0["components"]["s_e2"], 0.25 * 0.03 ** 2)     # (~3 SE of the moment estimate)
        self.assertLess(res0["components"]["s_u2"], 0.25 * 0.015 ** 2)
        # treatment means are not between-world variance
        res1 = rp.estimate(simulate(treat, 0.015, 0.03, 0.02, seed=3, mu={"A": 0.2, "B": -0.2}), treat, boot=50)
        self.assertAlmostEqual(res1["components"]["s_u2"], c["s_u2"], delta=0.05 * c["s_u2"])

    def test_pilot_size_and_interval(self):
        """The registered 8C + 2A + 2B pilot: 9 between-world and 88 within-world degrees of freedom; the
        90% interval brackets the estimate; deterministic."""
        treat = {f"C{i}": "C" for i in range(8)}
        treat.update({"A0": "A", "A1": "A", "B0": "B", "B1": "B"})
        obs = simulate(treat, 0.02, 0.03, 0.02, seed=9)
        r1 = rp.estimate(obs, treat, boot=2000)
        r2 = rp.estimate(list(reversed(obs)), treat, boot=2000)
        self.assertEqual(json.dumps(r1, sort_keys=True), json.dumps(r2, sort_keys=True))
        d = r1["decomposition"]
        self.assertEqual((d["df_b"], d["df_w"], d["N"], d["J"]), (9, 88, 12, 9))
        lo, hi = r1["ci90"]
        self.assertLessEqual(lo, r1["rho_hat"])
        self.assertGreaterEqual(hi, r1["rho_hat"])
        self.assertEqual(r1["allocation"], rp.allocation(r1["rho_hat"]))

    def test_incomplete_worlds_and_unavailable(self):
        """A world missing a time leaves the decomposition (complete worlds only); a (w, t) missing a
        neural predator is dropped; too few worlds -> unavailable -> the conservative 64."""
        treat = {f"C{i}": "C" for i in range(8)}
        treat.update({"A0": "A", "A1": "A", "B0": "B", "B1": "B"})
        obs = [o for o in simulate(treat, 0.02, 0.03, 0.02, seed=5)
               if not (o["world"] == "C0" and o["time"] == "100M")]
        obs = [o for o in obs if not (o["world"] == "C1" and o["time"] == "50M" and o["condition"] == "neural:c0")]
        res = rp.estimate(obs, treat, boot=100)
        self.assertNotIn("C0", res["decomposition"]["worlds"])
        self.assertNotIn("C1", res["decomposition"]["worlds"])
        self.assertEqual(res["decomposition"]["N"], 10)
        two = {"C0": "C", "A0": "A"}
        r = rp.estimate(simulate(two, 0.02, 0.03, 0.02), two, boot=10)
        self.assertEqual((r["available"], r["allocation"]), (False, 64))

    def test_plan(self):
        """The design: per (w, t) four neural predators from OTHER C worlds at the same time (w's hash
        order, valid ones only), the scripted benchmark and the free control, R = 12; exclusions recorded;
        plan.py expands it; deterministic."""
        tmp = tempfile.mkdtemp()
        try:
            sb = os.path.join(tmp, "sb.json")
            with open(sb, "w") as f:
                json.dump({"world": {"frame": 3000000}}, f)
            tpl = os.path.join(tmp, "t.json")
            with open(tpl, "w") as f:
                f.write("{}")
            ws = {}
            for i, T in enumerate(["C"] * 8 + ["A", "A", "B", "B"]):
                ws[f"w{i + 1:02d}"] = {"uuid": f"00000000-0000-0000-0000-{i + 1:012d}", "treatment": T, "block": 0,
                                       "status": "done", "pattern": os.path.join(tmp, f"w{i + 1:02d}", "end.{frame}.json"),
                                       "paths": {}, "valid_before": None,
                                       "archived": [t * 1_000_000 for t in rp.TIMES_M]}
            ws["w03"]["valid_before"] = 55_000_000            # its zero: 60M.. are not valid (prey or challenger)
            block = {"schema": "finfolk.redqueen.worldsblock/1", "registry_sha256": "x" * 64,
                     "times": {f"{t}M": t * 1_000_000 for t in range(5, 101, 5)}, "worlds": ws}
            d1, notes = rp.make_design(block, sb, [tpl], None)
            d2, _ = rp.make_design(block, sb, [tpl], None)
            self.assertEqual(json.dumps(d1, sort_keys=True), json.dumps(d2, sort_keys=True))
            self.assertEqual(len(notes["skipped"]), 5)                     # w03 at 60..100M
            self.assertEqual(len(d1["edges"]), (12 * 10 - 5) * 6)
            cw = sorted(w for w, v in ws.items() if v["treatment"] == "C")
            for w in ws:
                for t in ("10M", "70M"):
                    neu = [e["predators"]["world"] for e in d1["edges"]
                           if e["family"] == "rho-neural" and e["prey"] == {"world": w, "time": t}]
                    if w == "w03" and t == "70M":
                        self.assertEqual(neu, [])
                        continue
                    self.assertEqual(len(neu), 4)
                    self.assertNotIn(w, neu)
                    self.assertTrue(all(c in cw for c in neu))
                    if t == "70M":
                        self.assertNotIn("w03", neu)                       # (no longer a valid challenger)
                    self.assertTrue(all(e["predators"]["time"] == t for e in d1["edges"]
                                        if e["family"] == "rho-neural" and e["prey"] == {"world": w, "time": t}))
            rows, warns, man = plan.expand_v2(d1, pending=True)          # (the archives come later)
            self.assertEqual(len(rows), len(d1["edges"]) * 12)
            self.assertEqual({r["role"] for r in rows}, {"diagnostic"})
            self.assertEqual({r["horizon"] for r in rows}, {"short"})
            self.assertTrue(all(r["namespace"] == "main" for r in rows))
            # the common prey of one (w, t, r) is shared by every condition (paired contrasts)
            g = {}
            for r in rows:
                g.setdefault((r["prey"]["world"], r["prey"]["time"], r["replicate"]), set()).add(r["groups"]["common"])
            self.assertTrue(all(len(v) == 1 for v in g.values()))
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()

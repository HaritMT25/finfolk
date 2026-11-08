#!/usr/bin/env python3
"""test_probes.py: the Level-3 exploratory probes (probes.py, design v4 §11): the inputs (the required
diversity summaries), the covariate adjustment, the elastic-net coordinate descent (exact soft-thresholding on
an orthonormal design), the probe comparison over the wiring / behaviour / combined inputs and its validation
selection, the sealing contract (evaluation only under the committed sha256), and the F1 negative control
(own-world enrichment with block-respecting permutations; an audit only for real own-world structure, never
for block effects). numpy required.

    python3 -I tools/redqueen/test_probes.py [-v]
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
import probes as pb  # noqa: E402
import rqlib  # noqa: E402
try:
    import numpy as np  # noqa: E402
except ImportError:
    if os.environ.get("RQ_REQUIRE_NUMPY"):
        raise SystemExit("RQ_REQUIRE_NUMPY is set, but numpy cannot be imported")
    np = None

FEATS = {"w_sensor_action": "wiring", "w_recurrence": "wiring", "w_signs": "wiring", "controller_nodes": "wiring",
         "pursuit": "behaviour", "evasion": "behaviour", "polarization": "behaviour", "food_rate": "energetics",
         "distinct_genomes": "diversity", "wiring_diversity": "diversity"}


def simulate(seed=1, n_worlds=36, times=(10, 20, 30, 40, 50, 60), target="wiring"):
    """Feature rows and targets: the target depends on two wiring features (or only on density: "density")."""
    rng = np.random.default_rng(seed)
    rows, trows = [], []
    for k in range(n_worlds):
        w = f"w{k:02d}"
        split = "training" if k < 20 else "validation" if k < 28 else "test"
        tr = "C" if k % 6 else ("A" if k % 12 else "B")
        for t in times:
            v = {f: float(rng.normal()) for f in FEATS}
            dens = float(rng.uniform(300, 600))
            rows.append({"world": w, "t": t, "split": split, "block": k % 4, "treatment": tr, "density": dens,
                         "controller_size": float(rng.integers(8, 20)), "f1": False, "values": v})
            y = 0.002 * dens + 0.01 * t + 0.2 * rng.normal()
            if target == "wiring":
                y += 1.0 * v["w_sensor_action"] - 0.8 * v["w_recurrence"]
            trows.append({"world": w, "t": t, "y": {"profile_1": y}})
    return ({"schema": pb.FEATURES, "features": FEATS, "rows": rows},
            {"schema": pb.TARGETS, "targets": ["profile_1"], "rows": trows})


@unittest.skipIf(np is None, "numpy is not installed")
class TestProbes(unittest.TestCase):
    def test_inputs_and_enet(self):
        f, t = simulate()
        bad = json.loads(json.dumps(f))
        bad["features"].pop("wiring_diversity")
        for r in bad["rows"]:
            r["values"].pop("wiring_diversity")
        with self.assertRaises(pb.ProbeError):
            pb.load(bad, t)
        bad = json.loads(json.dumps(f))
        bad["rows"][3]["values"]["pursuit"] = float("nan")
        with self.assertRaises(pb.ProbeError):
            pb.load(bad, t)
        n = 64                                               # (orthonormal design: exact soft-thresholding)
        Q, _ = np.linalg.qr(np.random.default_rng(2).standard_normal((n, 3)))
        X = Q * math.sqrt(n)
        X -= X.mean(axis=0)
        Q2, _ = np.linalg.qr(X)
        X = Q2 * math.sqrt(n)
        y = X @ np.array([0.8, -0.3, 0.05])
        g = X.T @ y / n
        b = pb.enet(X, y, 0.1, 1.0)
        self.assertTrue(np.allclose(b, np.sign(g) * np.clip(np.abs(g) - 0.1, 0, None), atol=1e-8))

    def test_selection_and_adjustment(self):
        """A wiring-driven target: the wiring and combined inputs beat behaviour-only on validation, the
        selected probe uses wiring inputs, and the lasso keeps the two true features. A target driven only
        by the adjustment covariates (density, time) leaves nothing to probe after the adjustment."""
        f, t = simulate()
        meta, X, names, groups, Y, tn = pb.load(f, t)
        Xr, Yr, D, By = pb.adjust(meta, X, Y)
        rep, chosen = pb.tune(Xr, Yr, meta, groups, tn)
        r = rep["profile_1"]
        self.assertGreater(r["best_by_set"]["wiring"], 0.8)
        self.assertGreater(r["best_by_set"]["combined"], 0.8)
        self.assertLess(r["best_by_set"]["behaviour"], 0.2)
        self.assertIn(r["selected"]["set"], ("wiring", "combined"))
        lasso = pb.Probe("lasso", [k for k, g in enumerate(groups) if g in pb.SETS["wiring"]], 0.05)
        tr = np.array([m["split"] == "training" for m in meta])
        lasso.fit(Xr[tr], Yr[tr, 0])
        cols = [names[k] for k, g in enumerate(groups) if g in pb.SETS["wiring"]]
        big = {cols[k] for k in np.flatnonzero(np.abs(lasso.b) > 0.3)}
        self.assertEqual(big, {"w_sensor_action", "w_recurrence"})
        f2, t2 = simulate(target="density")
        meta2, X2, _, groups2, Y2, tn2 = pb.load(f2, t2)
        Xr2, Yr2, _, _ = pb.adjust(meta2, X2, Y2)
        rep2, _ = pb.tune(Xr2, Yr2, meta2, groups2, tn2)
        self.assertLess(max(v for v in rep2["profile_1"]["best_by_set"].values()), 0.1)

    def test_cli_sealing(self):
        tmp = tempfile.mkdtemp()
        try:
            f, t = simulate(seed=3)
            fp, tp = os.path.join(tmp, "f.json"), os.path.join(tmp, "t.json")
            out, pp, ev = (os.path.join(tmp, n) for n in ("probes.json", "pred.json", "ev.json"))
            for p, o in ((fp, f), (tp, t)):
                with open(p, "w") as fh:
                    json.dump(o, fh)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(pb.main(["fit", "--features", fp, "--targets", tp, "--out", out, "--predictions", pp]), 0)
                sha = rqlib.sha256_file(pp)
                self.assertEqual(rqlib.read_json(out)["predictions_sha256"], sha)
                self.assertTrue(rqlib.read_json(out)["exploratory"])
                self.assertEqual(pb.main(["evaluate", "--predictions", pp, "--pred-sha", "0" * 64, "--targets", tp,
                                          "--out", ev]), 2)
                self.assertEqual(pb.main(["evaluate", "--predictions", pp, "--pred-sha", sha, "--targets", tp,
                                          "--out", ev]), 0)
                self.assertEqual(pb.main(["fit", "--features", os.path.join(tmp, "none"), "--targets", tp, "--out", out,
                                          "--predictions", pp]), 2)
            self.assertGreater(rqlib.read_json(ev)["targets"]["profile_1"]["test_r2"], 0.8)
        finally:
            shutil.rmtree(tmp)


@unittest.skipIf(np is None, "numpy is not installed")
class TestF1Control(unittest.TestCase):
    def pairs(self, own=0.0, block_effect=0.0, seed=4):
        rng = np.random.default_rng(seed)
        worlds = [f"C{k:02d}" for k in range(32)]
        blocks = {w: k // 4 for k, w in enumerate(worlds)}
        out = []
        for a in worlds:
            for b in worlds:
                if blocks[a] != blocks[b] and rng.random() > 0.15:
                    continue                                  # (within-block pairs, plus some across)
                v = rng.normal(0, 0.1) + own * (a == b) + block_effect * (blocks[a] + blocks[b])
                out.append({"prey_world": a, "pred_world": b, "value": v})
        return out, blocks

    def test_enrichment(self):
        """No own-world effect: no audit; an own-world effect: the audit is triggered; strong BLOCK effects
        alone never produce enrichment under the block-respecting permutations."""
        p, bl = self.pairs()
        r = pb.enrichment(p, bl, 999)
        self.assertFalse(r["audit"])
        self.assertGreater(r["p"], 0.01)
        p, bl = self.pairs(own=0.2)
        r = pb.enrichment(p, bl, 999)
        self.assertTrue(r["audit"])
        self.assertLess(r["p"], 0.01)
        p, bl = self.pairs(block_effect=0.5, seed=6)
        r = pb.enrichment(p, bl, 999)
        self.assertFalse(r["audit"])
        self.assertEqual(pb.enrichment([{"prey_world": "C00", "pred_world": "C01", "value": 1.0}],
                                       {"C00": 0, "C01": 0}, 9)["available"], False)


if __name__ == "__main__":
    unittest.main()

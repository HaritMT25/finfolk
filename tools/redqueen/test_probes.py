#!/usr/bin/env python3
"""test_probes.py: the Level-3 exploratory probes (probes.py, design v4 §11).

The registered configuration (the required diversity summaries; registered definitions; grids in penalty
order); the elastic-net coordinate descent (exact soft-thresholding on an orthonormal design) and the
truncated-power basis; the staged pipeline against a real split manifest (holdouts, fork branches) and
sealing's commitments and freeze: register -> predict-candidates -> commit -> score-validation ->
open-validation -> predict-test -> commit -> freeze -> evaluate-test. KNOWN ANSWERS (P2-11): a wiring-driven
target has a large held-out RESIDUAL R^2 for the wiring and combined inputs and none for behaviour-only, the
lasso keeps the two true features; a target explained by density and time has a high original-scale R^2 and
NO residual R^2. GUARDS: roles from the manifest (test rows in the candidate stage, held-out snapshots and
validation-root branches as fit targets, labels, aliased UUIDs, other stages' targets, missing targets,
another definition); the commitments (no marker, other bytes, no selection record, another model, no
freeze). The F1 control (P2-12): an audit only for real own-world structure, never for block effects; a
design in which some block-respecting permutation has no own-world or no cross-world pair is refused (it
would bias p downward); non-positive permutation counts are refused. numpy required.

    python3 -I tools/redqueen/test_probes.py [-v]
"""
from __future__ import annotations

import contextlib
import gzip
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
import probes as pb  # noqa: E402
import rqlib  # noqa: E402
import sealing  # noqa: E402
try:
    import numpy as np  # noqa: E402
except ImportError:
    if os.environ.get("RQ_REQUIRE_NUMPY"):
        raise SystemExit("RQ_REQUIRE_NUMPY is set, but numpy cannot be imported")
    np = None

M = 1_000_000
FEATS = {"w_sensor_action": "wiring", "w_recurrence": "wiring", "w_signs": "wiring", "controller_nodes": "wiring",
         "pursuit": "behaviour", "evasion": "behaviour", "polarization": "behaviour", "food_rate": "energetics",
         "distinct_genomes": "diversity", "wiring_diversity": "diversity"}
WORLDS = [f"w{k:02d}" for k in range(36)]
SPLIT = {w: ("train" if k < 20 else "val" if k < 28 else "test") for k, w in enumerate(WORLDS)}
HOLD = {"w00:30": "val", "w01:40": "test"}
UUIDS = {w: str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:redqueen:ns-main:{w}")) for w in WORLDS}
BRANCHES = {"w05.o30M.s0": "w05", "w21.o30M.s0": "w21"}
TIMES = (10, 20, 30, 40, 50, 60)
FDEF, TDEF = {"extractor": "summaries v1", "sha256": "1" * 64}, {"kind": "fixed-reference profile", "map": "2" * 64}
TARGETS = ["wired", "density_only"]


def wr(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))


def config(**over):
    cfg = {"schema": pb.CFG_SCHEMA, "features": FEATS, "targets": TARGETS, "treatments": ["C", "A", "B"],
           "feature_definition_sha256": rqlib.canonical_sha(FDEF), "target_definition_sha256": rqlib.canonical_sha(TDEF),
           "sets": [{"name": "wiring", "groups": ["wiring", "diversity"]}, {"name": "behaviour", "groups": ["behaviour", "energetics"]},
                    {"name": "combined", "groups": ["wiring", "behaviour", "energetics", "diversity"]}],
           "probes": [{"kind": "lasso", "alpha": 1.0, "lambda_rel": [1.0, 0.3, 0.1, 0.03, 0.01]},
                      {"kind": "enet", "alpha": 0.5, "lambda_rel": [1.0, 0.3, 0.1, 0.03, 0.01]},
                      {"kind": "additive", "lambdas": [100.0, 10.0, 1.0, 0.1], "knots": [0.25, 0.5, 0.75]}],
           "min_rows": {"training": 5, "validation": 3, "test": 3}, "cd": {"iters": 2000, "tol": 1e-9},
           "enrichment": {"permutations": 999, "audit_alpha": 0.01, "seed_namespace": "test-probes", "max_block": 8}}
    cfg.update(over)
    return cfg


def make_root(tmp, **over):
    g = os.path.join(tmp, "graph")
    wr(os.path.join(g, "graph.meta.json"), {"schema": "finfolk.redqueen.graph/1", "namespace": "ns", "edges_sha256": "e" * 64,
                                            "split": SPLIT, "holdout": HOLD, "fork": ["w05", "w21"], "intensive": []})
    with gzip.open(os.path.join(g, "graph.jsonl.gz"), "wt") as f:
        f.write(json.dumps({"family": "within", "prey": "Q:w03:9", "pred": "P:w04:9", "role": "training"}) + "\n")
    wr(os.path.join(tmp, "worlds.json"), {"namespace": "ns-main", "worlds": [{"id": w, "uuid": UUIDS[w]} for w in WORLDS]})
    wr(os.path.join(tmp, "forks.json"), {"worlds": [{"id": b, "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, b)), "root": r,
                                                     "root_uuid": UUIDS[r]} for b, r in BRANCHES.items()]})
    root = os.path.join(tmp, "root")
    man = rqlib.canonical(sealing.manifest(os.path.join(g, "graph.meta.json"), os.path.join(tmp, "worlds.json"),
                                           os.path.join(tmp, "forks.json")))
    sealing.publish_manifest(root, man)
    m = json.loads(man)
    founders = {"cohort": "C", "frame": 1, "worlds_registry_sha256": m["worlds_registry_sha256"], "size": len(CWORLDS),
                "panel": {w: {"uuid": UUIDS[w], "treatment": "C", "block": BLOCK[w]} for w in CWORLDS}}
    cp = os.path.join(tmp, "probes_cfg.json")
    wr(cp, config(split_manifest_sha256=rqlib.sha256_bytes(man), **dict({"founders": founders}, **over)))
    pb.register(root, cp)
    return root, cp, m


CWORLDS = [w for k, w in enumerate(WORLDS) if k % 6]                 # (the fixture's C worlds: the founder panel)
BLOCK = {w: int(w[1:]) // 6 for w in CWORLDS}                       # (six blocks of five)


def simulate(seed=1):
    """Feature rows and targets per (world, t): "wired" depends on two wiring features (plus density and time);
    "density_only" on density and time only."""
    rng = np.random.default_rng(seed)
    rows, ys = {}, {}
    for k, w in enumerate(WORLDS):
        tr = "C" if k % 6 else ("A" if k % 12 else "B")
        for t in TIMES:
            v = {f: float(rng.normal()) for f in FEATS}
            dens = float(rng.uniform(300, 600))
            rows[(w, t)] = {"world": w, "t": t, "uuid": UUIDS[w], "treatment": tr, "density": dens,
                            "controller_size": float(rng.integers(8, 20)), "f1": False, "values": v}
            base = 0.002 * dens + 0.01 * t + 0.2 * rng.normal()
            ys[(w, t)] = {"wired": base + 1.0 * v["w_sensor_action"] - 0.8 * v["w_recurrence"],
                          "density_only": 0.004 * dens + 0.03 * t + 0.2 * rng.normal()}
    for b, r in BRANCHES.items():
        rows[(b, 31)] = dict(rows[(r, 30)], world=b, t=31, uuid=str(uuid.uuid5(uuid.NAMESPACE_URL, b)))
        ys[(b, 31)] = ys[(r, 30)]
    return rows, ys


def fdoc(rows):
    return {"schema": pb.FEATURES, "features": FEATS, "definition": FDEF, "rows": rows}


def tdoc(rows, ys):
    return {"schema": pb.TARGETS, "targets": TARGETS, "definition": TDEF,
            "rows": [{"world": r["world"], "t": r["t"], "uuid": r["uuid"], "y": ys[(r["world"], r["t"])]} for r in rows]}


def run(args):
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        rc = pb.main(args)
    return rc, err.getvalue()


@unittest.skipIf(np is None, "numpy is not installed")
class TestBasics(unittest.TestCase):
    def test_config_enet_and_basis(self):
        """The required diversity summaries and the grids' penalty order are registration requirements;
        exact soft-thresholding on an orthonormal design; the truncated-power cubic basis (P3: so named)."""
        tmp = tempfile.mkdtemp()
        try:
            f = dict(FEATS)
            f.pop("wiring_diversity")
            with self.assertRaisesRegex(pb.ProbeError, "wiring_diversity"):
                make_root(os.path.join(tmp, "a"), features=f)
            with self.assertRaisesRegex(pb.ProbeError, "DESCENDING"):
                make_root(os.path.join(tmp, "b"), probes=[{"kind": "lasso", "alpha": 1.0, "lambda_rel": [0.1, 1.0]}])
            with self.assertRaisesRegex(pb.ProbeError, "permutations"):
                make_root(os.path.join(tmp, "c"), enrichment=dict(config()["enrichment"], permutations=0))
        finally:
            shutil.rmtree(tmp)
        n = 64
        Q, _ = np.linalg.qr(np.random.default_rng(2).standard_normal((n, 3)))
        X = Q * math.sqrt(n)
        X -= X.mean(axis=0)
        Q2, _ = np.linalg.qr(X)
        X = Q2 * math.sqrt(n)
        y = X @ np.array([0.8, -0.3, 0.05])
        g = X.T @ y / n
        self.assertTrue(np.allclose(pb.enet(X, y, 0.1, 1.0), np.sign(g) * np.clip(np.abs(g) - 0.1, 0, None), atol=1e-8))
        B = pb.truncated_power_basis(np.array([-1.0, 0.0, 2.0]), [0.5])
        self.assertTrue(np.allclose(B[:, 3], [0.0, 0.0, 1.5 ** 3]))
        self.assertFalse(hasattr(pb, "spline_basis"))


@unittest.skipIf(np is None, "numpy is not installed")
class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root, cls.cfg_path, cls.man = make_root(cls.tmp)
        cls.rows, cls.ys = simulate()
        role = {k: sealing.node_role(cls.man, k[0], k[1] * M) for k in cls.rows}
        cls.role = role

        def put(name, obj):
            p = os.path.join(cls.tmp, name)
            wr(p, obj)
            return p
        sel = lambda roles: [cls.rows[k] for k in sorted(cls.rows) if role[k] in roles]  # noqa: E731
        cls.f_cand = put("f_cand.json", fdoc(sel({"training", "validation"})))
        cls.t_fit = put("t_fit.json", tdoc(sel({"training"}), cls.ys))
        cls.t_val = put("t_val.json", tdoc(sel({"validation"}), cls.ys))
        cls.f_test = put("f_test.json", fdoc(sel({"test"})))
        cls.t_test = put("t_test.json", tdoc(sel({"test"}), cls.ys))
        cls.val, cls.model, cls.scores = (os.path.join(cls.tmp, n) for n in ("val.jsonl", "model.json", "val_scores.json"))
        cls.test, cls.eval = os.path.join(cls.tmp, "test.jsonl"), os.path.join(cls.tmp, "eval.json")
        cls.rc = [run(["predict-candidates", "--root", cls.root, "--features", cls.f_cand, "--fit-targets", cls.t_fit,
                       "--model-out", cls.model, "--out", cls.val])]
        cls.precommit = os.path.join(cls.tmp, "precommit")
        shutil.copytree(cls.root, cls.precommit)
        sealing.commit(cls.root, "validation", cls.val)
        cls.committed = os.path.join(cls.tmp, "committed")
        shutil.copytree(cls.root, cls.committed)
        cls.rc.append(run(["score-validation", "--root", cls.root, "--predictions", cls.val, "--targets", cls.t_val,
                           "--out", cls.scores]))
        sealing.open_validation(cls.root, cls.scores)
        cls.opened = os.path.join(cls.tmp, "opened")
        shutil.copytree(cls.root, cls.opened)
        cls.rc.append(run(["predict-test", "--root", cls.root, "--features", cls.f_test, "--model", cls.model,
                           "--selection", cls.scores, "--out", cls.test]))
        cls.impl = os.path.join(cls.tmp, "impl.json")
        cls.rc.append(run(["implementation", "--out", cls.impl]))
        sealing.commit(cls.root, "test", cls.test, cls.impl)
        cls.unfrozen = os.path.join(cls.tmp, "unfrozen")
        shutil.copytree(cls.root, cls.unfrozen)
        pr = put("prereg.pdf", "the preregistration\n")
        sealing.freeze(cls.root, pr, cls.impl, osf_url="https://osf.io/abc12", registered_utc=rqlib.now_utc())
        cls.rc.append(run(["evaluate-test", "--root", cls.root, "--predictions", cls.test, "--targets", cls.t_test,
                           "--out", cls.eval]))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def copy(self, which):
        dst = os.path.join(tempfile.mkdtemp(dir=self.tmp), "root")
        shutil.copytree(which, dst)
        return dst

    def put(self, name, obj):
        p = os.path.join(tempfile.mkdtemp(dir=self.tmp), name)
        wr(p, obj)
        return p

    def test_end_to_end_and_residual_r2(self):
        """P2-11 known answers through the staged pipeline: "wired" has a large residual R^2 for wiring and
        combined inputs and none for behaviour-only (validation and test); "density_only" has a high
        original-scale R^2 but no residual R^2. Roles come from the manifest (the held-out snapshot w00@30 is a
        validation row; w01@40 a test row); provenance binds the inputs; the scores record the fingerprint.
        Codex r2 P1-4: every score is per registered group (world role / row role): the training world's
        snapshot holdouts never pool with the held-out roots."""
        self.assertEqual([r[0] for r in self.rc], [0, 0, 0, 0, 0], [r[1] for r in self.rc])
        self.assertEqual((self.role[("w00", 30)], self.role[("w01", 40)], self.role[("w21.o30M.s0", 31)]),
                         ("validation", "test", "validation"))
        val = [json.loads(x) for x in rqlib.read_text(self.val).splitlines()]
        self.assertIn("probe:wired:w00:30", {ln["target_id"] for ln in val})
        self.assertEqual(val[0]["provenance"]["model_sha256"], rqlib.sha256_file(self.model))
        self.assertEqual(val[0]["provenance"]["fit_targets_sha256"], rqlib.sha256_file(self.t_fit))
        sc = rqlib.read_json(self.scores)
        self.assertEqual(sc["targets_sha256"], rqlib.sha256_file(self.t_val))
        w = sc["targets"]["wired"]
        self.assertGreater(w["best_residual_r2_by_set"]["wiring"], 0.8)
        self.assertGreater(w["best_residual_r2_by_set"]["combined"], 0.8)
        self.assertLess(w["best_residual_r2_by_set"]["behaviour"], 0.2)
        self.assertIn(w["selected"].split("/")[1], ("wiring", "combined"))
        d = sc["targets"]["density_only"]
        self.assertLess(max(v for v in d["best_residual_r2_by_set"].values()), 0.1)
        self.assertGreater(d["selection_set"]["r2"], 0.5)                    # (the nuisance explains it: not the probe)
        self.assertEqual(sorted(w["groups"]), ["training/validation", "validation/validation"])
        self.assertEqual(w["groups"]["training/validation"], {"available": False, "rows": 1})   # (w00@30 alone)
        self.assertGreater(w["groups"]["validation/validation"]["residual_r2"], 0.8)
        mod = rqlib.read_json(self.model)
        lasso = mod["probes"]["wired"]["lasso/wiring/2"]
        names = sorted(FEATS)
        cols = [names[c] for c in lasso["cols"]]
        big = {cols[j] for j, b in enumerate(lasso["b"]) if abs(b) > 0.3}
        self.assertEqual(big, {"w_sensor_action", "w_recurrence"})
        ev = rqlib.read_json(self.eval)
        self.assertEqual((ev["TEST_PRED_SHA"], ev["targets_sha256"]), (rqlib.sha256_file(self.test), rqlib.sha256_file(self.t_test)))
        self.assertEqual(sorted(ev["targets"]["wired"]["groups"]), ["test/test", "training/test"])
        self.assertEqual(ev["targets"]["wired"]["groups"]["training/test"], {"available": False, "rows": 1})  # (w01@40)
        self.assertGreater(ev["targets"]["wired"]["groups"]["test/test"]["residual_r2"], 0.8)
        dt = ev["targets"]["density_only"]["groups"]["test/test"]
        self.assertLess(dt["residual_r2"], 0.2)
        self.assertGreater(dt["r2"], 0.5)
        self.assertTrue(ev["exploratory"])
        self.assertEqual(ev["scoring"]["implementation_sha256"], rqlib.sha256_file(self.impl))

    def test_role_guards(self):
        """P1-2 / P1-3: every stage reads only its roles (computed from the manifest)."""
        root = self.copy(self.root)
        mo, out = os.path.join(self.tmp, "m.json"), os.path.join(self.tmp, "o.jsonl")
        fc = rqlib.read_json(self.f_cand)
        ft = rqlib.read_json(self.t_fit)
        cases = [("features", dict(fc, rows=fc["rows"] + [self.rows[("w30", 10)]]), "test-role row"),
                 ("fit", tdoc(ft["rows"] + [self.rows[("w22", 10)]], self.ys), "validation-role row"),
                 ("fit", tdoc(ft["rows"] + [self.rows[("w00", 30)]], self.ys), "validation-role row"),     # (holdout)
                 ("fit", tdoc(ft["rows"] + [self.rows[("w21.o30M.s0", 31)]], self.ys), "validation-role row"),  # (branch)
                 ("fit", dict(ft, rows=ft["rows"] + [dict(tdoc([self.rows[("w03", 10)]], self.ys)["rows"][0], t=70,
                                                              split="training")]), "roles come from the split manifest"),
                 ("fit", dict(ft, rows=[dict(ft["rows"][0], uuid=UUIDS["w30"])] + ft["rows"][1:]), "UUID"),
                 ("fit", dict(ft, definition={"kind": "latent axis"}), "target definition"),
                 ("features", dict(fc, definition={"other": 1}), "feature definition")]
        for which, d, why in cases:
            p = self.put("x.json", d)
            args = ["predict-candidates", "--root", root, "--features", p if which == "features" else self.f_cand,
                    "--fit-targets", p if which == "fit" else self.t_fit, "--model-out", mo, "--out", out]
            rc, err = run(args)
            self.assertEqual(rc, 2, why)
            self.assertIn(why, err)
        root = self.copy(self.committed)
        tv = rqlib.read_json(self.t_val)
        sc = os.path.join(self.tmp, "sc.json")
        for d, why in ((tdoc(tv["rows"] + [self.rows[("w30", 10)]], self.ys), "test-role row"),
                       (dict(tv, rows=tv["rows"][1:]), "no target row")):
            rc, err = run(["score-validation", "--root", root, "--predictions", self.val, "--targets", self.put("t.json", d),
                           "--out", sc])
            self.assertEqual(rc, 2, why)
            self.assertIn(why, err)
        root = self.copy(self.opened)
        rc, err = run(["predict-test", "--root", root, "--features", self.f_cand, "--model", self.model,
                       "--selection", self.scores, "--out", out])
        self.assertIn("training-role row", err)

    def test_commitment_guards(self):
        """P1-4 / P1-5: no scoring without the committed bytes, no test prediction without the recorded
        selection and its model, no test evaluation without the freeze and the committed test predictions."""
        sc = os.path.join(self.tmp, "sc2.json")
        rc, err = run(["score-validation", "--root", self.copy(self.precommit), "--predictions", self.val,
                       "--targets", self.t_val, "--out", sc])
        self.assertIn("no VAL_PRED_SHA", err)
        v2 = self.put("val.jsonl", rqlib.read_text(self.val).replace('"available":true', '"available":true ', 1))
        rc, err = run(["score-validation", "--root", self.copy(self.committed), "--predictions", v2, "--targets",
                       self.t_val, "--out", sc])
        self.assertIn("not the committed validation predictions", err)
        out = os.path.join(self.tmp, "t2.jsonl")
        rc, err = run(["predict-test", "--root", self.copy(self.committed), "--features", self.f_test, "--model", self.model,
                       "--selection", self.scores, "--out", out])
        self.assertIn("not recorded", err)
        s2 = self.put("s.json", dict(rqlib.read_json(self.scores), targets={}))
        rc, err = run(["predict-test", "--root", self.copy(self.opened), "--features", self.f_test, "--model", self.model,
                       "--selection", s2, "--out", out])
        self.assertIn("not the validation scores recorded", err)
        m2 = self.put("m.json", rqlib.read_text(self.model).replace('"schema"', ' "schema"', 1))
        rc, err = run(["predict-test", "--root", self.copy(self.opened), "--features", self.f_test, "--model", m2,
                       "--selection", self.scores, "--out", out])
        self.assertIn("not the model state", err)
        ev = os.path.join(self.tmp, "ev2.json")
        rc, err = run(["evaluate-test", "--root", self.copy(self.unfrozen), "--predictions", self.test, "--targets",
                       self.t_test, "--out", ev])
        self.assertIn("no public freeze record", err)
        fresh = self.put("t.jsonl", rqlib.read_text(self.test).replace('"available":true', '"available":true ', 1))
        rc, err = run(["evaluate-test", "--root", self.copy(self.root), "--predictions", fresh, "--targets", self.t_test,
                       "--out", ev])
        self.assertIn("not the committed test predictions", err)
        tt = rqlib.read_json(self.t_test)
        rc, err = run(["evaluate-test", "--root", self.copy(self.root), "--predictions", self.test, "--targets",
                       self.put("t.json", tdoc(tt["rows"] + [self.rows[("w22", 10)]], self.ys)), "--out", ev])
        self.assertIn("validation-role row", err)
        root = self.copy(self.root)                                  # (Codex r2 P1-3: the record, before the gate)
        vp = os.path.join(root, "registration", "validation_evaluation.json")
        os.chmod(vp, 0o644)
        rqlib.write_durable(vp, rqlib.canonical(dict(rqlib.read_json(vp), scores_sha256="0" * 64)))
        rc, err = run(["evaluate-test", "--root", root, "--predictions", self.test, "--targets", self.t_test, "--out", ev])
        self.assertIn("not the validation evaluation the freeze recorded", err)
        root = self.copy(self.unfrozen)                              # (Codex r2 P1-2: another frozen implementation)
        imp = self.put("impl.json", rqlib.read_text(self.impl).replace('"machine"', ' "machine"', 1))
        sealing.freeze(root, self.put("prereg.pdf", "the preregistration\n"), self.impl, osf_url="https://osf.io/abc12",
                       registered_utc=rqlib.now_utc())
        fp = os.path.join(root, "registration", "freeze.json")
        os.chmod(fp, 0o644)
        rqlib.write_durable(fp, rqlib.canonical(dict(rqlib.read_json(fp), evaluation_script_sha256=rqlib.sha256_file(imp))))
        rc, err = run(["evaluate-test", "--root", root, "--predictions", self.test, "--targets", self.t_test, "--out", ev])
        self.assertIn("not the frozen evaluation script", err)

    def test_founder_binding(self):
        """Codex r2 P2-8: the F1 control is bound to the registered founder panel: its pairs name registered
        founders at the founder frame (identities checked); blocks come from the registration; a later
        snapshot, a world outside the panel, another world's UUID, or caller-supplied blocks are refused."""
        rng = np.random.default_rng(9)
        pairs = []
        for a in CWORLDS:
            for b in CWORLDS:
                if BLOCK[a] == BLOCK[b] or rng.random() < 0.1:
                    pairs.append({"prey": {"world": a, "t": 0, "uuid": UUIDS[a]}, "predators": {"world": b, "t": 0},
                                  "value": float(rng.normal(0, 0.1))})
        doc = {"schema": pb.PAIRS, "pairs": pairs}
        out = os.path.join(self.tmp, "f1.json")
        rc, err = run(["enrichment", "--root", self.root, "--pairs", self.put("p.json", doc), "--out", out])
        self.assertEqual(rc, 0, err)
        rec = rqlib.read_json(out)
        self.assertFalse(rec["audit"])
        self.assertEqual(rec["founder_panel_sha256"], rqlib.canonical_sha(rqlib.read_json(self.cfg_path)["founders"]))
        bad_cases = [(dict(doc, blocks={w: 0 for w in CWORLDS}), "registered founder panel"),
                     (dict(doc, pairs=pairs + [dict(pairs[0], prey={"world": CWORLDS[0], "t": 10})]), "founder snapshot"),
                     (dict(doc, pairs=pairs + [dict(pairs[0], prey={"world": "w00", "t": 0})]), "not a registered founder"),
                     (dict(doc, pairs=pairs + [dict(pairs[0], prey={"world": CWORLDS[0], "t": 0, "uuid": UUIDS["w00"]})]), "UUID"),
                     (dict(doc, pairs=pairs + [dict(pairs[0], prey={"world": "w05.o30M.s0", "t": 0})]), "not a registered founder")]
        for d, why in bad_cases:
            rc, err = run(["enrichment", "--root", self.root, "--pairs", self.put("p.json", d), "--out", out])
            self.assertEqual(rc, 2, why)
            self.assertIn(why, err)


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
                    continue                                  # (every within-block pair, plus some across)
                v = rng.normal(0, 0.1) + own * (a == b) + block_effect * (blocks[a] + blocks[b])
                out.append({"prey_world": a, "pred_world": b, "value": v})
        return out, blocks

    def test_enrichment(self):
        """No own-world effect: no audit; an own-world effect: the audit; strong BLOCK effects alone: none."""
        en = lambda p, bl, n=999: pb.enrichment(p, bl, n, "test", 0.01)  # noqa: E731
        p, bl = self.pairs()
        r = en(p, bl)
        self.assertFalse(r["audit"])
        self.assertGreater(r["p"], 0.01)
        p, bl = self.pairs(own=0.2)
        r = en(p, bl)
        self.assertTrue(r["audit"])
        self.assertLess(r["p"], 0.01)
        p, bl = self.pairs(block_effect=0.5, seed=6)
        self.assertFalse(en(p, bl)["audit"])

    def test_unsupported_designs_and_counts(self):
        """P2-12: a sparse design in which some block-respecting permutation has no own-world pair (each block
        holds one off-diagonal pair) or no cross-world pair (only own pairs) is refused before any draw; a
        sparse but supported design (one block complete) runs; P3: non-positive counts are refused."""
        worlds = [f"C{k:02d}" for k in range(8)]
        blocks = {w: k // 4 for k, w in enumerate(worlds)}
        sparse = [{"prey_world": "C00", "pred_world": "C01", "value": 1.0}, {"prey_world": "C01", "pred_world": "C01", "value": 2.0},
                  {"prey_world": "C04", "pred_world": "C05", "value": 0.5}, {"prey_world": "C05", "pred_world": "C05", "value": 0.7}]
        self.assertIn("no own-world", pb.design_support(sparse, blocks, 8))
        with self.assertRaisesRegex(pb.ProbeError, "unsupported design"):
            pb.enrichment(sparse, blocks, 99, "t", 0.01)
        single = {"C00": 0, "C01": 1}                           # (singleton blocks of own pairs: never a cross pair)
        diag = [{"prey_world": w, "pred_world": w, "value": float(k)} for k, w in enumerate(single)]
        self.assertIn("no cross-world", pb.design_support(diag, single, 8))
        with self.assertRaisesRegex(pb.ProbeError, "unsupported design"):
            pb.enrichment(diag, single, 99, "t", 0.01)
        complete0 = [{"prey_world": a, "pred_world": b, "value": 0.1 * (a == b)} for a in worlds[:4] for b in worlds[:4]]
        ok = complete0 + sparse[2:]
        self.assertIsNone(pb.design_support(ok, blocks, 8))
        self.assertTrue(pb.enrichment(ok, blocks, 99, "t", 0.01)["available"])
        for n in (0, -5, 2.5):
            with self.assertRaisesRegex(pb.ProbeError, "positive integer"):
                pb.enrichment(ok, blocks, n, "t", 0.01)


if __name__ == "__main__":
    unittest.main()

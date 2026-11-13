#!/usr/bin/env python3
"""test_noisebank.py: the independent noise bank (noisebank.py, design v4 §7.4, Annex H.9.2, D4). Covers:
  * the plan:
    - the registered worlds / partners, the crossed 256-pair design and its 32 controls (18,432 trajectories);
    - the production seed sharing, the mandatory inputs, the seed check;
    - the binding to the VALIDATION registry, for both block producers (worlds.py design-block: no "root";
      val_block.py: "root", attempts), and the main-study disjointness;
  * the numerics: the bivariate normal (Genz) against quadrature and closed forms; the interval-censored
    marginal MLE and its degenerate refusals;
  * the composite likelihood:
    - each group's maximum against the realized correlation of the TRUE latent values over the same pairs
      (a tight machinery check);
    - the components of a simulated bank with KNOWN components, drawn by H.9.2's generator (rounded counts,
      the expected-rounded-mean location solve);
  * feasibility: infeasible unconstrained maxima give a PSD constrained fit; unidentified / missing groups
    are refused with reasons; the saturation masks are per channel;
  * s(mu): tie pooling, blocks, knots, constant tails, the documented non-nesting of the bins; nu0's explicit
    encoding and the exact trigamma inversion;
  * the crossed world bootstrap's multiplicities and source keys;
  * the production V builder: the term-by-term formula through the shared evaluator (noisescale), the
    simulated covariance of replicate means at small s, refusals;
  * collection bound to the final plan; the CLI (plan; estimate: canonical JSON, never Infinity / NaN).
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
import noisescale  # noqa: E402
import plan  # noqa: E402
import rqlib  # noqa: E402
try:
    import numpy as np  # noqa: E402
except ImportError:
    if os.environ.get("RQ_REQUIRE_NUMPY"):
        raise SystemExit("RQ_REQUIRE_NUMPY is set, but numpy cannot be imported")
    np = None

NS = nb.VALIDATION_NAMESPACE
M = 60                           # (a coarse dependence grid for the tests: 61 nodes in atanh(rho); registered 240)


def write_registry(path, ns, n=12, treatment="C"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    reg = {"schema": nb.WORLDS_SCHEMA, "namespace": ns,
           "worlds": [{"id": f"w{i:02d}", "uuid": nb.registry_uuid(ns, f"w{i:02d}"), "treatment": treatment}
                      for i in range(1, n + 1)]}
    with open(path, "w") as f:
        json.dump(reg, f)
    return reg


def block(root, valid_before=None, n=12, style="design_block"):
    """A worlds block as worlds.py design-block writes it (no "root"), or as val_block.py does ("root",
    "attempt"); its registry_sha256 is the registry file's."""
    rp = os.path.join(root, "config", "worlds.json")
    if not os.path.isfile(rp):
        write_registry(rp, NS, n)
    ws = {}
    for i in range(1, n + 1):
        w = f"w{i:02d}"
        ws[w] = {"uuid": nb.registry_uuid(NS, w), "treatment": "C", "block": 1, "status": "running",
                 "pattern": os.path.join(root, w, "end.{frame}.json"), "paths": {},
                 "valid_before": (valid_before or {}).get(w), "archived": [t * 1_000_000 for t in range(1, 101)]}
        if style == "val_block":
            ws[w]["attempt"] = 0
    b = {"schema": "finfolk.redqueen.worldsblock/1", "registry_sha256": rqlib.sha256_file(rp),
         "times": {f"{t}M": t * 1_000_000 for t in range(1, 101)}, "worlds": ws}
    if style == "val_block":
        b.update(root=root, source="runner_val")
    return b


def files(tmp):
    out = {}
    for name, txt in (("t.json", "{}"), ("ages.json", "{}"), ("prod.json", json.dumps({"reserved": []}))):
        out[name] = os.path.join(tmp, name)
        with open(out[name], "w") as f:
            f.write(txt)
    out["main"] = os.path.join(tmp, "main", "config", "worlds.json")
    write_registry(out["main"], "finfolk-rq-main-2026", n=48)
    return out


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "validation")
        self.f = files(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def design(self, b=None, **kw):
        args = dict(validation_dir=self.root, arena="arena-7", main_registries=[self.f["main"]])
        args.update(kw)
        return nb.make_design(b or block(self.root), [self.f["t.json"]], self.f["ages.json"], [self.f["prod.json"]], **args)

    def test_the_registered_crossed_design(self):
        d = self.design()
        meta = d["noisebank"]
        self.assertEqual(len(meta["worlds"]), nb.N_WORLDS)
        self.assertEqual((meta["arena"], meta["validation_dir"]), ("arena-7", os.path.abspath(self.root)))
        self.assertEqual(meta["validation"]["namespace"], NS)
        self.assertEqual(meta["validation"]["main_registries"][0]["namespace"], "finfolk-rq-main-2026")
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
        by_prey, by_pred = {}, {}
        for r in r0:
            by_prey.setdefault((r["prey"]["world"], r["prey"]["time"], r["replicate"]), set()).add(r["seeds"]["sample"])
            by_pred.setdefault((r["predators"]["world"], r["predators"]["time"], r["replicate"]), set()).add(
                r["seeds"]["transplant"])
        self.assertEqual({len(v) for v in by_prey.values()}, {1})
        self.assertEqual({len(v) for v in by_pred.values()}, {1})

    def test_both_block_producers_and_the_validation_binding(self):
        """Codex #72 r1 P2-8: worlds.py design-block's block (no "root") and val_block.py's ("root", attempts)
        are both accepted when bound to the validation registry. A mismatched root, registry, namespace,
        identity or treatment, a missing main registry, and any overlap with a main-study registry are
        refused."""
        self.design(block(self.root, style="design_block"))
        self.design(block(self.root, style="val_block"))
        b = block(self.root, style="val_block")
        w = "w03"
        b["worlds"][w]["attempt"] = 2
        b["worlds"][w]["uuid"] = nb.attempt_uuid(nb.registry_uuid(NS, w), 2)
        self.design(b)                                                          # (a restarted attempt)
        with self.assertRaises(nb.NoiseBankError):
            self.design(dict(block(self.root, style="val_block"), root=os.path.join(self.tmp, "elsewhere")))
        with self.assertRaises(nb.NoiseBankError):
            self.design(dict(block(self.root), registry_sha256="0" * 64))
        bad = block(self.root)
        bad["worlds"]["w02"]["uuid"] = str(uuid.uuid4())
        with self.assertRaises(nb.NoiseBankError):
            self.design(bad)
        bad = block(self.root)
        bad["worlds"]["w02"]["treatment"] = "A"
        with self.assertRaises(nb.NoiseBankError):
            self.design(bad)
        with self.assertRaises(nb.NoiseBankError):
            self.design(main_registries=[])                                     # (the main registry: mandatory)
        clash = os.path.join(self.tmp, "clash", "config", "worlds.json")
        reg = write_registry(clash, "finfolk-rq-main-2026", n=4)
        reg["worlds"].append({"id": "w99", "uuid": nb.registry_uuid(NS, "w05"), "treatment": "C"})
        with open(clash, "w") as f:
            json.dump(reg, f)
        with self.assertRaises(nb.NoiseBankError):
            self.design(main_registries=[self.f["main"], clash])               # (a validation identity in main)
        same = os.path.join(self.tmp, "same", "config", "worlds.json")
        write_registry(same, NS, n=0)
        with self.assertRaises(nb.NoiseBankError):
            self.design(main_registries=[same])                                 # (the validation namespace itself)
        other = os.path.join(self.tmp, "other")                                 # (another namespace's registry)
        write_registry(os.path.join(other, "config", "worlds.json"), "finfolk-rq-main-2026")
        with self.assertRaises(nb.NoiseBankError):
            self.design(block(other), validation_dir=other)

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
                           validation_dir=self.root, arena="a", main_registries=[self.f["main"]])
        with self.assertRaises(nb.NoiseBankError):
            nb.make_design(block(self.root), [self.f["t.json"]], self.f["ages.json"], [], validation_dir=self.root,
                           arena="a", main_registries=[self.f["main"]])
        rows, _, _ = plan.expand_v2(self.design(), pending=True)
        seed = next(iter(plan.plan_seeds(rows)))
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w") as f:
            json.dump({"engine_seed": seed}, f)
        with self.assertRaises(nb.NoiseBankError):
            nb.make_design(block(self.root), [self.f["t.json"]], self.f["ages.json"], [bad], validation_dir=self.root,
                           arena="a", main_registries=[self.f["main"]])

    def test_cli_plan(self):
        bp, out = os.path.join(self.tmp, "block.json"), os.path.join(self.tmp, "d.json")
        with open(bp, "w") as f:
            json.dump(block(self.root), f)
        args = ["plan", "--block", bp, "--templates", self.f["t.json"], "--age-reference", self.f["ages.json"],
                "--avoid", self.f["prod.json"], "--arena", "a1", "--out", out]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(nb.main(args + ["--validation-dir", self.root, "--main-registry", self.f["main"]]), 0)
        self.assertEqual(rqlib.read_json(out)["noisebank"]["arena"], "a1")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(nb.main(args + ["--validation-dir", self.tmp, "--main-registry", self.f["main"]]), 2)
            self.assertEqual(nb.main(args + ["--validation-dir", self.root]), 2)


# ================================================================== simulation (H.9.2's generator)
def sigm(x):
    return 1.0 / (1.0 + np.exp(-x))


def location(mu, s, N):
    """a with E[floor(N sigma(a + s Z) + 1/2)] / N = mu (H.9.2's expected-rounded-mean solve; bisection)."""
    mu, s = np.asarray(mu, float), np.asarray(s, float)
    k = np.arange(1, N + 1)
    lk = np.log((k - 0.5) / (N - k + 0.5))
    lo, hi = np.full(mu.shape, -30.0), np.full(mu.shape, 30.0)
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        ef = nb._Q((lk[None, :] - mid.ravel()[:, None]) / s.ravel()[:, None]).sum(axis=1).reshape(mu.shape) / N
        up = ef < mu
        lo, hi = np.where(up, mid, lo), np.where(up, hi, mid)
    return 0.5 * (lo + hi)


TRUE = {"SigmaR": [[0.25, 0.08, 0.06], [0.08, 0.30, 0.12], [0.06, 0.12, 0.40]],
        "SigmaD": [[0.20, 0.05], [0.05, 0.15]], "SigmaE": [[0.55, 0.10], [0.10, 0.55]]}


def s_true(ch, mu):
    mu = np.asarray(mu, float)
    return 0.30 + 0.30 * (1 - mu) if ch == "C" else 0.10 + 0.30 * mu


def all_horizons(doc):
    """A single-horizon (5k) simulated doc with that horizon's counts copied to the other two."""
    doc["observations"] = [dict(o, horizons={str(h): o["horizons"]["5000"] for h in nb.HORIZONS})
                           for o in doc["observations"]]
    return doc


def simulate(seed=3, W=6, T=2, R=48, true=TRUE, horizons=nb.HORIZONS, cross=True, surv_shift=0.0):
    """A bank with KNOWN components drawn by H.9.2's generator: per channel K = floor(N sigma(a + s(mu) u) +
    1/2) with a solved for E[K/N] = mu and u the sharing components. W worlds x T times; each prey snapshot
    meets its own world's and (cross) its partner's predator snapshots. -> (obs doc, latents {(h, channel,
    key, r): u})."""
    rng = np.random.default_rng(seed)
    worlds = [f"w{i}" for i in range(W)]
    times = nb.TIMES[:T]
    snaps = [(w, t) for w in worlds for t in times]
    partner = {w: worlds[(k + 1) % W] for k, w in enumerate(worlds)}
    pairs = [(q, (wp, tp)) for q in snaps for wp in ((q[0], partner[q[0]]) if cross else (q[0],)) for tp in times]
    a = {q: rng.normal(-0.4, 0.6) for q in snaps}
    b = {p: rng.normal(0.0, 0.4) for p in snaps}
    c = {q: rng.normal(1.1, 0.6) + surv_shift for q in snaps}
    SR, SD, SE = (np.array(true[k]) for k in ("SigmaR", "SigmaD", "SigmaE"))
    LR, LD, LE = (nb._psd_factor(M) for M in (SR, SD, SE))
    eF = 1 - SR[2, 2]
    cells, lat = {}, {}
    for h in horizons:
        Bh = nb.capture_bound(h)
        row = {q: rng.standard_normal((R, 3)) @ LR.T for q in snaps}
        don = {p: rng.standard_normal((R, 2)) @ LD.T for p in snaps}
        mF = np.array([sigm(c[q] + 0.3) for q in snaps])
        uF = np.array([row[q][:, 2] + math.sqrt(eF) * rng.standard_normal(R) for q in snaps])
        aF = location(mF, s_true("F", mF), nb.N_PREY)
        KF = np.floor(nb.N_PREY * sigm(aF[:, None] + s_true("F", mF)[:, None] * uF) + 0.5)
        for k, q in enumerate(snaps):
            for r in range(R):
                lat[(h, "F", q, r)] = uF[k, r]
                x = cells.setdefault((q, None, r), {"cell": f"{q}|free|{r}", "prey": list(q), "pred": None,
                                                    "replicate": r, "horizons": {}})
                x["horizons"][str(h)] = {"captures": None, "survivors": int(KF[k, r])}
        mC = np.array([sigm(a[q] + b[p]) for q, p in pairs])
        mS = np.array([sigm(c[q] - 0.6 * b[p]) for q, p in pairs])
        E = rng.standard_normal((len(pairs), R, 2)) @ LE.T
        uC = np.array([row[q][:, 0] + don[p][:, 0] for q, p in pairs]) + E[:, :, 0]
        uS = np.array([row[q][:, 1] + don[p][:, 1] for q, p in pairs]) + E[:, :, 1]
        aC, aS = location(mC, s_true("C", mC), Bh), location(mS, s_true("S", mS), nb.N_PREY)
        KC = np.floor(Bh * sigm(aC[:, None] + s_true("C", mC)[:, None] * uC) + 0.5)
        KS = np.floor(nb.N_PREY * sigm(aS[:, None] + s_true("S", mS)[:, None] * uS) + 0.5)
        for k, (q, p) in enumerate(pairs):
            for r in range(R):
                lat[(h, "C", (q, p), r)], lat[(h, "S", (q, p), r)] = uC[k, r], uS[k, r]
                x = cells.setdefault((q, p, r), {"cell": f"{q}|{p}|{r}", "prey": list(q), "pred": list(p),
                                                 "replicate": r, "horizons": {}})
                x["horizons"][str(h)] = {"captures": int(KC[k, r]), "survivors": int(KS[k, r])}
    doc = {"schema": nb.OBS_SCHEMA, "design_sha256": "d", "plan_sha256": "p", "missing": [],
           "observations": list(cells.values())}
    return doc, lat


# ================================================================== numerics
@unittest.skipIf(np is None, "numpy is not installed")
class TestNumerics(unittest.TestCase):
    def test_bivariate_normal(self):
        """Genz's BVNU against quadrature over both branches (|r| < 0.925 and above, both signs) and the
        closed form at the origin; infinite bounds; the rectangles of a partition sum to one."""
        def brute(h, k, r):
            x = np.linspace(h, h + 14, 100001)
            f = np.exp(-x * x / 2) / math.sqrt(2 * math.pi) * nb._Q((k - r * x) / math.sqrt(1 - r * r))
            return float(np.sum((f[1:] + f[:-1]) / 2 * np.diff(x)))
        for r in (-0.99, -0.93, -0.5, 0.0, 0.3, 0.924, 0.93, 0.995):
            for h, k in ((0.0, 0.0), (1.3, -0.4), (-2.1, 0.7), (2.5, 2.2), (0.4, 0.41)):
                self.assertAlmostEqual(float(nb.bvn_upper(np.array([h]), np.array([k]), r)[0]), brute(h, k, r),
                                       delta=1e-8, msg=(h, k, r))
            self.assertAlmostEqual(float(nb.bvn_upper(np.array([0.0]), np.array([0.0]), r)[0]),
                                   0.25 + math.asin(r) / (2 * math.pi), delta=1e-14)
        inf = math.inf
        self.assertEqual(nb.bvn_upper(np.array([-inf, inf]), np.array([-inf, 0.0]), 0.4).tolist(), [1.0, 0.0])
        self.assertAlmostEqual(float(nb.bvn_upper(np.array([-inf]), np.array([0.3]), 0.4)[0]), float(nb._Q(0.3)),
                               delta=1e-15)
        edges = [-inf, -0.7, 0.2, 1.1, inf]
        tot = sum(float(nb.bvn_rect(np.array([edges[i]]), np.array([edges[i + 1]]), np.array([edges[j]]),
                                    np.array([edges[j + 1]]), 0.6)[0]) for i in range(4) for j in range(4))
        self.assertAlmostEqual(tot, 1.0, delta=1e-13)

    def test_log_rect_is_tail_stable(self):
        """Codex #72 r2 P1: log_rect agrees with differenced tails where those are accurate (moderate
        rectangles), stays exact where they cancel (a thin discordant rectangle at rho = +-0.995: the density
        limit, where differencing gives 0), is unchanged by a 16x panel refinement (LOG_RECT_TOL), handles
        infinite ends, and never floors."""
        rng = np.random.default_rng(0)
        n = 600
        c1, c2 = rng.normal(0, 1.5, n), rng.normal(0, 1.5, n)
        w1, w2 = rng.uniform(0.01, 0.6, n), rng.uniform(0.01, 0.6, n)
        for r in (-0.9, 0.0, 0.5, 0.95):
            a = nb.log_rect(c1, c1 + w1, c2, c2 + w2, r)
            b = nb.bvn_rect(c1, c1 + w1, c2, c2 + w2, r)
            ok = b > 1e-8
            self.assertLess(float(np.max(np.abs(a[ok] - np.log(b[ok])))), 1e-6, r)
        for r, y in ((0.995, 1.0), (-0.995, -1.0)):
            x, w = -1.0, 1e-4
            lr = float(nb.log_rect(np.array([x]), np.array([x + w]), np.array([y]), np.array([y + w]), r)[0])
            s_ = math.sqrt(1 - r * r)
            xm, ym = x + w / 2, y + w / 2
            dens = math.log(w * w) - math.log(2 * math.pi * s_) - (xm * xm - 2 * r * xm * ym + ym * ym) / (2 * s_ * s_)
            self.assertAlmostEqual(lr, dens, delta=1e-3)
            self.assertLess(lr, -200)
            self.assertLessEqual(float(nb.bvn_rect(np.array([x]), np.array([x + w]), np.array([y]),
                                                   np.array([y + w]), r)[0]), 1e-80)       # (the cancellation)
        l1 = np.where(rng.random(n) < 0.15, -np.inf, c1)
        h2 = np.where(rng.random(n) < 0.15, np.inf, c2 + w2)
        old, oldmax = nb.PANEL_EFOLDS, nb.MAX_PANELS
        for r in (-0.995, -0.99, 0.0, 0.99, 0.995):
            a = nb.log_rect(l1, c1 + w1, c2, h2, r)
            nb.PANEL_EFOLDS, nb.MAX_PANELS = old / 8, 1 << 16             # (a refinement, never capped)
            try:
                b = nb.log_rect(l1, c1 + w1, c2, h2, r)
            finally:
                nb.PANEL_EFOLDS, nb.MAX_PANELS = old, oldmax
            self.assertTrue(np.all(np.isfinite(a)))
            self.assertLess(float(np.max(np.abs(a - b))), nb.LOG_RECT_TOL, r)
        for bad in (([41.0], [41.5], [0.0], [0.1], 0.5), ([0.0], [0.0 + 1e-7], [0.0], [0.1], 0.5),
                    ([0.0], [0.1], [0.0], [0.1], 0.996), ([np.inf], [np.inf], [0.0], [0.1], 0.5)):
            with self.assertRaises(nb.NoiseBankError):                     # (outside the registered domain)
                nb.log_rect(*(np.array(v, float) for v in bad[:4]), bad[4])
        rs_ = np.random.default_rng(7)
        A1 = np.where(rs_.random(300) < 0.2, -np.inf, rs_.uniform(-37, 37, 300))
        A2 = rs_.uniform(-37, 37, 300)
        B1 = np.where(np.isfinite(A1), A1 + rs_.uniform(1e-5, 2, 300), rs_.uniform(-37, 37, 300))
        B2 = np.where(rs_.random(300) < 0.2, np.inf, A2 + rs_.uniform(1e-5, 2, 300))
        for r in (-0.995, -0.6, 0.3, 0.995):                           # (argument order never matters)
            self.assertLess(float(np.max(np.abs(nb.log_rect(A1, B1, A2, B2, r) - nb.log_rect(A2, B2, A1, B1, r)))), 1e-8)
        a = nb.log_rect(np.array([-np.inf]), np.array([0.3]), np.array([-0.2]), np.array([np.inf]), 0.4)
        self.assertAlmostEqual(float(a[0]), math.log(float(nb.bvn_upper(np.array([-0.3]), np.array([-0.2]), -0.4)[0])),
                               delta=1e-9)
        self.assertAlmostEqual(float(nb._log_iprob(np.array([40.0]), np.array([40.5]))[0]),
                               float(nb._logQ(np.array([40.0]))[0]) + math.log1p(-math.exp(
                                   float(nb._logQ(np.array([40.5]))[0] - nb._logQ(np.array([40.0]))[0]))), delta=1e-12)
        self.assertTrue(float(nb._logQ(np.array([60.0]))[0]) < -1800)              # (no underflow to -inf)

    def test_log_rect_against_an_independent_reference(self):
        """Codex #72 r3 P2-1: log_rect against an INDEPENDENT reference (math.erfc and the asymptotic tail
        series for log Q; log-space conditional probabilities; the mode by golden section and a FIXED 8,000-interval
        composite Simpson rule) on the REGISTERED TEST SET spanning the admissible domain (centres to
        +-39, widths 1e-5 .. 2 and half-infinite, rho to +-0.995), with Codex's counterexamples: a thin
        discordant rectangle at the limits, the broad [0, 39]^2 quadrant at rho 0, X > 0 and Y > 39, and a
        tiny central interval. Max |log error| <= LOG_RECT_TOL."""
        cases = []
        for cx in (-37.0, -7.0, 0.0, 1.0, 37.0):
            for cy in (-37.0, 0.0, 7.0, 37.0):
                for wx, wy in ((1e-5, 0.05), (0.05, 2.0), (None, 0.05), (2.0, None)):
                    for r in (-0.995, -0.5, 0.0, 0.5, 0.995):
                        lx, hx = (cx, cx + wx) if wx else (-math.inf, cx) if cx < 0 else (cx, math.inf)
                        ly, hy = (cy, cy + wy) if wy else (-math.inf, cy) if cy < 0 else (cy, math.inf)
                        cases.append((lx, hx, ly, hy, r))
        cases += [(-1.0, -1.0 + 1e-4, 1.0, 1.0 + 1e-4, 0.995), (-1.0, -1.0 + 1e-4, -1.0, -1.0 + 1e-4, -0.995),
                  (0.0, 39.0, 0.0, 39.0, 0.0), (0.0, math.inf, 39.0, math.inf, 0.995), (0.0, math.inf, 39.0, math.inf, -0.5),
                  (-5e-6, 5e-6, -5e-6, 5e-6, 0.3), (-7.0, -6.99, 7.0, 7.01, 0.995)]
        worst = 0.0
        arr = [np.array([c[k] for c in cases]) for k in range(4)]
        for r in sorted({c[4] for c in cases}):
            sel = [i for i, c in enumerate(cases) if c[4] == r]
            got = nb.log_rect(*(a_[sel] for a_ in arr), r)
            for g_, i in zip(got, sel):
                ref = _ref_log_rect(*cases[i])
                worst = max(worst, abs(float(g_) - ref))
        self.assertLess(worst, nb.LOG_RECT_TOL, worst)

    def test_grid_tolerances_near_the_limits(self):
        """Codex #72 r2 P2 / r3: on the registered grid (z = atanh(rho), refined edges) every pair's
        interpolated contribution is within GRID_LL_TOL of the exact one OFF the grid near both limits, for
        thin concordant and discordant rectangles and Codex's (-7, 7) thin rectangle; a group objective's
        interpolated maximizer near 0.99 is within GRID_RHO_TOL of the exact maximizer; the certification
        inserts exact columns where the interpolant misses."""
        rng = np.random.default_rng(3)
        n = 40
        x = rng.normal(0, 1.2, n)
        y = np.concatenate([x[: n // 2] + rng.normal(0, 0.1, n // 2), -x[n // 2:] + rng.normal(0, 0.1, n - n // 2)])
        x, y = np.append(x, [-7.0, -7.0]), np.append(y, [7.0, -7.0])
        w1 = np.append(rng.uniform(0.02, 0.2, n), [0.01, 0.01])
        w2 = np.append(rng.uniform(0.02, 0.2, n), [0.01, 0.01])
        l1, h1, l2, h2 = x, x + w1, y, y + w2
        base = nb._log_iprob(l1, h1) + nb._log_iprob(l2, h2)
        zn = nb.z_nodes()
        vals = np.array([nb.log_rect(l1, h1, l2, h2, float(np.tanh(z))) - base for z in zn])     # (nodes x pairs)
        for r in (0.9937, 0.9811, 0.9502, -0.9502, -0.9811, -0.9937, 0.9949, -0.9949):
            exact = nb.log_rect(l1, h1, l2, h2, r) - base
            interp = np.array([float(nb.obj_rho(zn, vals[:, k], r)[0][0]) for k in range(len(x))])
            self.assertLess(float(np.max(np.abs(interp - exact))), nb.GRID_LL_TOL, r)
        z = rng.multivariate_normal([0, 0], [[1, 0.99], [0.99, 1]], 300)
        L1, L2 = z[:, 0] - 0.03, z[:, 1] - 0.03
        b2 = nb._log_iprob(L1, L1 + 0.06) + nb._log_iprob(L2, L2 + 0.06)
        F = lambda r: float(np.sum(nb.log_rect(L1, L1 + 0.06, L2, L2 + 0.06, r) - b2))  # noqa: E731
        f = np.array([F(float(np.tanh(v))) for v in zn])
        r_int, _ = nb._argmax(zn, f)
        a, b = 0.9, 0.995                                         # (golden section on the EXACT objective)
        g = (math.sqrt(5) - 1) / 2
        c, d = b - g * (b - a), a + g * (b - a)
        fc, fd = F(c), F(d)
        for _ in range(60):
            if fc > fd:
                b, d, fd = d, c, fc
                c = b - g * (b - a)
                fc = F(c)
            else:
                a, c, fc = c, d, fd
                d = a + g * (b - a)
                fd = F(d)
        self.assertLess(abs(r_int - (a + b) / 2), nb.GRID_RHO_TOL)
        # local objective-value validation: a coarse table misses; exact columns are inserted, deduplicated
        zc = np.linspace(-nb.Z_MAX, nb.Z_MAX, 12)
        blocks = [(L1, L1 + 0.06, L2, L2 + 0.06, np.zeros(len(L1), int))]
        T = np.array([[F(float(np.tanh(v))) for v in zc]])
        tab = {gg: {"z": zc.copy(), "T": T.copy(), "keys": [((0,), (0,))], "pairs": len(L1), "blocks": blocks}
               for gg in nb.GROUPS}
        ins, worst = nb.validate_grid(tab, {gg: 0.99 for gg in nb.GROUPS})
        self.assertTrue(ins and worst > nb.GRID_LL_TOL)
        self.assertGreater(len(tab["R_CC"]["z"]), 12)
        # (Codex #72 r4 P2-2: a fitted value AT a bracket midpoint is inserted once, never twice)
        zc2 = np.linspace(-nb.Z_MAX, nb.Z_MAX, 12)
        mid = 0.5 * (zc2[9] + zc2[10])
        tab2 = {gg: {"z": zc2.copy(), "T": T.copy(), "keys": [((0,), (0,))], "pairs": len(L1), "blocks": blocks}
                for gg in nb.GROUPS}
        nb.validate_grid(tab2, {gg: float(np.tanh(mid)) for gg in nb.GROUPS})
        zz = tab2["R_CC"]["z"]
        self.assertTrue(np.all(np.diff(zz) >= nb.MIN_KNOT))
        self.assertEqual(int(np.sum(np.abs(zz - mid) < 1e-9)), 1)

    def test_marginal_mle(self):
        """The interval-censored marginal MLE recovers (a, sigma) of rounded logistic-normal counts (the
        empirical-logit moments only start it), with calibrated observed-information errors; constant counts,
        two adjacent values and all-zero counts are refused (degenerate)."""
        rng = np.random.default_rng(1)
        N = 324
        a, s = rng.normal(-0.5, 0.8, 300), rng.uniform(0.15, 0.8, 300)
        K = np.floor(N * sigm(a[:, None] + s[:, None] * rng.standard_normal((300, 64))) + 0.5)
        f = nb.fit_marginals(K, N)
        self.assertTrue(f["ok"].all())
        z = np.log(f["sigma"] / s) / np.sqrt(f["var_t"])                         # (standardized log-scale errors)
        self.assertLess(abs(float(np.mean(z))), 0.25)
        self.assertLess(abs(float(np.std(z)) - 1), 0.2)
        self.assertLess(float(np.median(np.abs(f["a"] - a))), 0.06)
        D = np.full((3, 64), 5.0)
        D[1, :32] = 6
        D[2] = 0
        self.assertFalse(nb.fit_marginals(D, N)["ok"].any())


# ================================================================== an independent reference for log_rect
def _ref_logQ(z):
    if z == math.inf:
        return -math.inf
    if z == -math.inf:
        return 0.0
    if z <= 25.0:
        return math.log(0.5 * math.erfc(z / math.sqrt(2.0))) if z > -8.0 else math.log1p(-0.5 * math.erfc(-z / math.sqrt(2.0)))
    t = 1.0 / (z * z)
    ser = 1 - t + 3 * t ** 2 - 15 * t ** 3 + 105 * t ** 4 - 945 * t ** 5 + 10395 * t ** 6
    return -0.5 * z * z - math.log(z * math.sqrt(2 * math.pi)) + math.log(ser)


def _ref_log_iprob(a, b):
    if b - a < 1e-6:
        m, w = 0.5 * (a + b), b - a
        return -0.5 * m * m - 0.5 * math.log(2 * math.pi) + math.log(w) + math.log1p(w * w * (m * m - 1) / 24)
    if a > 0:
        la, lb = _ref_logQ(a), _ref_logQ(b)
        return la + math.log(-math.expm1(lb - la))
    if b < 0:
        lb, la = _ref_logQ(-b), _ref_logQ(-a)
        return lb + math.log(-math.expm1(la - lb))
    return math.log1p(-(math.exp(_ref_logQ(b)) + math.exp(_ref_logQ(-a))))


def _ref_log_rect(l1, h1, l2, h2, r):
    """An independent reference: the conditional integral over X in [l1, h1] (truncated at +-60) of
    phi(x) P(l2 < Y < h2 | x), with log Q from math.erfc and the asymptotic series, the mode by golden section,
    the range where log f is within 60 of it by bisection, and composite Simpson on 8,000 uniform intervals in
    log-sum-exp form."""
    s = math.sqrt(1 - r * r)
    lo, hi = max(l1, -60.0), min(h1, 60.0)

    def F(x):
        return -0.5 * x * x - 0.5 * math.log(2 * math.pi) + _ref_log_iprob((l2 - r * x) / s, (h2 - r * x) / s)
    a, b = lo, hi
    g = (math.sqrt(5) - 1) / 2
    c, d = b - g * (b - a), a + g * (b - a)
    fc, fd = F(c), F(d)
    for _ in range(120):
        if fc > fd:
            b, d, fd = d, c, fc
            c = b - g * (b - a)
            fc = F(c)
        else:
            a, c, fc = c, d, fd
            d = a + g * (b - a)
            fd = F(d)
    xm = max(((x, F(x)) for x in (lo, hi, 0.5 * (a + b))), key=lambda t: t[1])[0]
    fm = F(xm)

    def cut(x_in, x_out):                     # (F(x_in) >= fm - 60 > F(x_out), concave)
        if F(x_out) >= fm - 60:
            return x_out
        for _ in range(100):
            mid = 0.5 * (x_in + x_out)
            x_in, x_out = (mid, x_out) if F(mid) >= fm - 60 else (x_in, mid)
        return x_out
    xl, xh = cut(xm, lo), cut(xm, hi)
    n = 8000
    hstep = (xh - xl) / n
    v = [F(xl + k * hstep) for k in range(n + 1)]
    wts = [1.0 if k in (0, n) else (4.0 if k % 2 else 2.0) for k in range(n + 1)]
    mx = max(v)
    tot = sum(w_ * math.exp(f_ - mx) for w_, f_ in zip(wts, v)) * hstep / 3
    return mx + math.log(tot)


# ================================================================== the composite likelihood
def group_rho_from_latents(A, U, lat, h):
    """An INDEPENDENT construction of the nine groups' pairs (from the cell keys, not group_pairs) and the
    realized correlation of the TRUE latent values over them."""
    cells = [(A["prey"][i], A["pred"][j]) for i, j in zip(A["I"], A["J"])]
    ok = {ch: U[ch]["ok"] for ch in "CSF"}
    acc = {g: ([], []) for g in nb.GROUPS}
    R = A["R"]

    def push(g, k1, k2):
        acc[g][0].extend(lat[k1[:3] + (r,)] for r in range(R))
        acc[g][1].extend(lat[k2[:3] + (r,)] for r in range(R))
    for m, (q, p) in enumerate(cells):
        if ok["C"][m] and ok["S"][m]:
            push("T_CS", (h, "C", (q, p)), (h, "S", (q, p)))
        i = A["prey"].index(q)
        for ch, g in (("C", "R_CF"), ("S", "R_SF")):
            if ok[ch][m] and ok["F"][i]:
                push(g, (h, ch, (q, p)), (h, "F", q))
        for n in range(m + 1, len(cells)):
            q2, p2 = cells[n]
            kind = "R" if (q == q2 and p != p2) else ("D" if (p == p2 and q != q2) else None)
            if kind is None:
                continue
            for c1, c2, g in (("C", "C", kind + "_CC"), ("S", "S", kind + "_SS"), ("C", "S", kind + "_CS"),
                              ("S", "C", kind + "_CS")):
                if ok[c1][m] and ok[c2][n]:
                    push(g, (h, c1, (q, p)), (h, c2, (q2, p2)))
    out = {}
    for g, (x, y) in acc.items():
        x, y = np.array(x), np.array(y)
        out[g] = (float(np.mean(x * y) / math.sqrt(np.mean(x * x) * np.mean(y * y))), len(x))
    return out


@unittest.skipIf(np is None, "numpy is not installed")
class TestEstimator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc, cls.lat = simulate()
        cls.bank = nb.estimate(cls.doc, boot=29, m=M)

    def test_groups_track_the_true_latent_correlations(self):
        """The machinery check: at every horizon each group's composite-likelihood maximum equals the realized
        correlation of the TRUE latent values over the same pairs (constructed independently) within 0.03,
        and the pair counts agree."""
        for h in nb.HORIZONS:
            A = nb.arrays(self.doc["observations"], h)
            U = nb.usable(A)
            want = group_rho_from_latents(A, U, self.lat, h)
            got = self.bank["horizons"][str(h)]["groups"]
            for g in nb.GROUPS:
                self.assertEqual(got[g]["pairs"], want[g][1], (h, g))
                self.assertLess(abs(got[g]["rho_max"] - want[g][0]), 0.03, (h, g, got[g]["rho_max"], want[g][0]))

    def test_components_recovered(self):
        """The components of a bank with KNOWN components (H.9.2's generator), within sampling error of this
        6-world, 48-replicate bank: the shares, the cross-channel and the free-row covariances. The free row
        variance is the CONVENTION (the minimal feasible value, never above 1); the unit totals hold; every
        component is PSD; the bootstrap interval covers the estimate."""
        for h in nb.HORIZONS:
            e = self.bank["horizons"][str(h)]
            self.assertEqual(e["status"], "ok", e.get("reasons"))
            c = e["components"]
            SR, SD, SE = (np.array(c[k]) for k in ("SigmaR", "SigmaD", "SigmaE"))
            tR, tD, tE = (np.array(TRUE[k]) for k in ("SigmaR", "SigmaD", "SigmaE"))
            self.assertLess(float(np.max(np.abs(SR[:2, :2] - tR[:2, :2]))), 0.08, (h, SR))
            self.assertLess(float(np.max(np.abs(SD - tD))), 0.08, (h, SD))
            self.assertLess(float(np.max(np.abs(SE - tE))), 0.10, (h, SE))
            self.assertLess(float(np.max(np.abs(SR[:2, 2] - tR[:2, 2]))), 0.08, (h, SR))
            self.assertEqual(c["SigmaR_FF"]["status"], "convention")
            A, v = SR[:2, :2], SR[:2, 2]
            self.assertAlmostEqual(SR[2, 2], float(v @ np.linalg.pinv(A) @ v), delta=1e-12)
            self.assertLessEqual(SR[2, 2], 1.0)
            for ch in "CS":
                sh = c["shares"][ch]
                self.assertAlmostEqual(sh["row"] + sh["donor"] + sh["cell"], 1.0, delta=1e-12)
            for Mx in (SR, SD, SE):
                self.assertGreaterEqual(float(np.min(np.linalg.eigvalsh(Mx))), -1e-12)
            bs = e["bootstrap"]
            self.assertEqual(bs["draws"], 29)
            lo, hi = bs["ci95"]["R_CC"]
            self.assertTrue(lo <= SR[0, 0] <= hi)

    def test_scales_and_the_generator_block(self):
        """s(mu): monotone, the right directions (capture decreasing, survival increasing), the true curve
        recovered inside the support. The generator / map blocks serialize as canonical JSON (no Infinity or
        NaN) and pass the shared evaluator's checks."""
        sc = self.bank["horizons"]["5000"]["scales"]
        self.assertEqual((sc["C"]["direction"], sc["S"]["direction"]), ("decreasing", "increasing"))
        for ch in "CS":
            cv = sc[ch]
            lo, hi = cv["support"]
            for x in np.linspace(lo, hi, 7)[1:-1]:
                mu = float(sigm(x))
                self.assertLess(abs(float(noisescale.evaluate(cv, mu)) / float(s_true(ch, mu)) - 1), 0.2, (ch, mu))
        g = self.bank["generator_noise"]
        self.assertTrue(g["available"])
        noisescale.check_set(g["s_logit"])
        self.assertEqual((g["horizon"], g["capture_bound"]), (5000, 324))
        rqlib.canonical(self.bank)                                              # (allow_nan=False: no Inf / NaN)
        nu = self.bank["map_variance"]["nu0"]
        self.assertEqual(set(nu), {"C", "S", "F"})
        for v in nu.values():
            self.assertIn(v["status"], ("estimated", "full_pooling", "unavailable"))

    def test_channels_are_masked_separately(self):
        """Codex #72 r1 P2-5: a saturated survival removes that cell's survival only; its capture stays."""
        doc, _ = simulate(seed=5, W=4, T=2, R=24, horizons=(5000,), surv_shift=3.5)
        A = nb.arrays(doc["observations"], 5000)
        U = nb.usable(A)
        self.assertGreater(U["S"]["counts"]["saturated"], 0)
        self.assertEqual(U["C"]["counts"]["saturated"], 0)
        self.assertEqual(U["C"]["counts"]["usable"], len(A["I"]))


@unittest.skipIf(np is None, "numpy is not installed")
class TestFeasibilityAndRefusals(unittest.TestCase):
    def quad(self, centre, curv=500.0):
        zn = nb.z_nodes(M)
        return {k: (zn, -curv * (np.tanh(zn) - centre[k]) ** 2) for k in nb.GROUPS}

    def test_feasible_maxima_are_the_fit(self):
        r = {"R_CC": 0.3, "R_SS": 0.25, "R_CS": 0.1, "D_CC": 0.2, "D_SS": 0.15, "D_CS": 0.05, "T_CS": 0.3,
             "R_CF": 0.1, "R_SF": 0.2}
        f = nb.fit_dependence(self.quad(r), M)
        self.assertEqual(f["fit"], "unconstrained")
        for k in nb.GROUPS:
            self.assertAlmostEqual(f["rho"][k], r[k], delta=0.005)
        with self.assertRaises(nb.NoiseBankError):
            nb.rho_grid(4)                                                      # (too coarse)

    def test_infeasible_maxima_give_a_psd_fit(self):
        """Codex #72 r1 P1-2: maxima with row + donor > 1, a too-large cross-channel row correlation and a free
        row loading outside the unit disk are fitted over the PSD parametrization: every component PSD, the
        unit totals, the free convention <= 1, and a better composite likelihood than the projected start.
        Every point of the parametrization is feasible."""
        r = {"R_CC": 0.6, "R_SS": 0.05, "R_CS": 0.4, "D_CC": 0.6, "D_SS": 0.2, "D_CS": 0.1, "T_CS": 0.9,
             "R_CF": 0.5, "R_SF": -0.6}
        _, _, _, feas, prob = nb.components_of(r)
        self.assertFalse(feas)
        self.assertTrue(prob)
        obj = self.quad(r)
        f = nb.fit_dependence(obj, M)
        self.assertEqual(f["fit"], "constrained")
        SR, SD, SE = f["SigmaR"], f["SigmaD"], f["SigmaE"]
        for Mx in (SR, SD, SE):
            self.assertGreaterEqual(float(np.min(np.linalg.eigvalsh(Mx))), -1e-12)
        self.assertAlmostEqual(SR[0, 0] + SD[0, 0] + SE[0, 0], 1.0, delta=1e-12)
        self.assertAlmostEqual(SR[1, 1] + SD[1, 1] + SE[1, 1], 1.0, delta=1e-12)
        self.assertLessEqual(SR[2, 2], 1.0 + 1e-12)
        start = nb._theta_map(nb._theta_start(f["unconstrained"]))
        ll0 = sum(float(nb.obj_rho(*obj[g], start[g])[0][0]) for g in nb.GROUPS)
        self.assertGreater(f["loglik"], ll0)
        for th in ([0.1] * 9, [1.0, 2.0, -0.5, 0.3, 1.4, -1.2, 0.7, 1.5, 2.5]):
            self.assertTrue(nb.components_of(nb._theta_map(th))[3])

    def test_constrained_domain_and_certification(self):
        """The constrained fit stays inside the evaluable domain (maxima beyond it give |rho| <= RHO_MAX, the
        reported matrices being the evaluated ones); a non-converged optimizer and disagreeing starts are
        refused, never accepted."""
        r = {"R_CC": 0.999, "R_SS": 0.05, "R_CS": 0.3, "D_CC": 0.3, "D_SS": 0.2, "D_CS": 0.1, "T_CS": 0.99,
             "R_CF": 0.999, "R_SF": -0.6}
        zn = nb.z_nodes(M)
        obj = {k: (zn, -500.0 * (np.tanh(zn) - min(max(r[k], -0.9999), 0.9999)) ** 2) for k in nb.GROUPS}
        f = nb.fit_dependence(obj)
        self.assertEqual(f["fit"], "constrained")
        self.assertTrue(all(abs(v) <= nb.RHO_MAX for v in f["rho"].values()))
        self.assertLessEqual(f["starts"]["parameter_spread"], nb.PARAM_TOL)
        self.assertGreaterEqual(f["starts"]["reaching_best"], nb.MIN_AGREE)
        self.assertEqual(f["starts"]["label"], "multi-start validated, not a global certificate")
        self.assertTrue(set(f["at_box"]) <= set(nb.GROUPS))
        self.assertAlmostEqual(f["loglik"], sum(float(nb.obj_rho(*obj[k], f["rho"][k])[0][0]) for k in nb.GROUPS),
                               delta=1e-9)
        ip = nb._interior
        nb._interior = lambda *a, **k: (lambda x, L, ok, res, mu: (x, L, False, res, mu))(*ip(*a, **k))
        try:
            with self.assertRaises(nb.NoiseBankError):
                nb.fit_dependence(obj)                                       # (non-convergence propagates)
        finally:
            nb._interior = ip
        old = nb.PARAM_TOL
        nb.PARAM_TOL = -1.0
        try:
            with self.assertRaises(nb.NoiseBankError):
                nb.fit_dependence(obj)                                       # (disagreeing runs: refused)
        finally:
            nb.PARAM_TOL = old
        with self.assertRaises(nb.NoiseBankError):
            nb.obj_rho(*obj["R_CC"], 0.999)                                    # (never clamped)

    def test_constrained_fit_against_a_dense_reference(self):
        """Codex #72 r3 P2-3: validated against an independent reference optimum. Only the row and donor
        capture shares compete (their maxima 0.7 + 0.6 exceed the unit total; the rest feasible at their
        maxima): a dense search over the feasible (r, d) triangle of the exact quadratic objective agrees
        with the interior-point fit."""
        zn = nb.z_nodes(M)
        c = {"R_CC": 0.7, "R_SS": 0.25, "R_CS": 0.05, "D_CC": 0.6, "D_SS": 0.2, "D_CS": 0.02, "T_CS": 0.1,
             "R_CF": 0.05, "R_SF": 0.1}
        curv = {"R_CC": 400.0, "D_CC": 250.0}
        obj = {k: (zn, -curv.get(k, 300.0) * (np.tanh(zn) - c[k]) ** 2) for k in nb.GROUPS}
        f = nb.fit_dependence(obj)
        self.assertEqual(f["fit"], "constrained")
        best, arg = -math.inf, None
        for r_ in np.linspace(0.2, 0.9, 701):
            for d_ in np.linspace(0.1, 0.8, 141):
                x = dict(c, R_CC=float(r_), D_CC=float(d_))
                if not nb.components_of(x)[3]:
                    continue
                v = -400 * (r_ - 0.7) ** 2 - 250 * (d_ - 0.6) ** 2
                if v > best:
                    best, arg = v, (r_, d_)
        self.assertAlmostEqual(f["rho"]["R_CC"], arg[0], delta=2e-3)
        self.assertAlmostEqual(f["rho"]["D_CC"], arg[1], delta=6e-3)

    def test_refined_table_identification(self):
        """Codex #72 r5: when the local validation refines a table, identification is re-checked on the
        REFINED table before the refit is accepted; a group that is unidentified there makes the horizon
        unavailable (the shift itself never refuses)."""
        doc = all_horizons(simulate(seed=12, W=4, T=2, R=16, horizons=(5000,))[0])
        A = nb.arrays(doc["observations"], 5000)
        real = nb.validate_grid

        def flatten(tab, fitrho):
            tab["R_CC"]["T"] = np.zeros_like(tab["R_CC"]["T"])        # (a flat objective: no curvature)
            return True, 0.0
        nb.validate_grid = flatten
        try:
            e = nb.horizon_estimate(A, boot=2, seed=0, m=M)
        finally:
            nb.validate_grid = real
        self.assertEqual(e["status"], "unavailable")
        self.assertTrue(any("unidentified on the refined grid" in r for r in e["reasons"]), e["reasons"])

    def test_unidentified_and_missing_groups_are_refused(self):
        """One time and no crossing: no row-sharing and no donor-sharing pairs, refused with reasons; the
        generator block is unavailable; the CLI exits 2 and still writes canonical JSON. An impossible
        curvature floor makes every group unidentified. Bad counts, schemas and draw counts are refused."""
        doc, _ = simulate(seed=7, W=4, T=1, R=16, cross=False)
        bank = nb.estimate(doc, boot=3, m=M)
        e = bank["horizons"]["5000"]
        self.assertEqual(e["status"], "unavailable")
        self.assertIn("no R_CC pairs", e["reasons"])
        self.assertIn("no D_CC pairs", e["reasons"])
        self.assertFalse(bank["generator_noise"]["available"])
        rqlib.canonical(bank)
        tmp = tempfile.mkdtemp()
        old = nb.REPLICATES
        try:
            p, out = os.path.join(tmp, "obs.json"), os.path.join(tmp, "bank.json")
            with open(p, "w") as f:
                json.dump(doc, f)
            nb.REPLICATES = 16
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(nb.main(["estimate", "--obs", p, "--boot", "2", "--out", out]), 2)
            self.assertFalse(rqlib.read_json(out)["generator_noise"]["available"])
        finally:
            nb.REPLICATES = old
            shutil.rmtree(tmp)
        doc2 = all_horizons(simulate(seed=8, W=4, T=2, R=16, horizons=(5000,))[0])
        old = nb.INFO_MIN
        nb.INFO_MIN = 1e9
        try:
            e2 = nb.estimate(doc2, boot=2, m=M)["horizons"]["5000"]
        finally:
            nb.INFO_MIN = old
        self.assertEqual(e2["status"], "unavailable")
        self.assertTrue(any("unidentified" in r for r in e2["reasons"]))
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(doc2, boot=0)
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(doc2, boot=2, m=M, replicates=64)
        bad = json.loads(json.dumps(doc2))
        bad["observations"][-1]["horizons"]["5000"]["survivors"] = 10 ** 6
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(bad, boot=2, m=M)
        bad["observations"][-1]["horizons"]["5000"]["survivors"] = 1.5
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(bad, boot=2, m=M)
        bad["observations"][-1]["horizons"]["5000"]["survivors"] = 1
        bad["observations"][-1]["replicate"] = 99
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(bad, boot=2, m=M)
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(dict(doc2, schema="x"), boot=2)


# ================================================================== s(mu), nu0, bootstrap
@unittest.skipIf(np is None, "numpy is not installed")
class TestScaleNu0Bootstrap(unittest.TestCase):
    def test_tie_pooling_blocks_and_tails(self):
        """Codex #72 r1 P2-4 / P3: tied locations are pooled first (the fit cannot depend on their order); one
        knot per PAVA block at its weighted mean location; linear between, constant beyond. The bins are NOT
        a special case: a step function becomes ramps between block centres."""
        rng = np.random.default_rng(4)
        mu = np.repeat(rng.uniform(0.05, 0.95, 60), 3)
        var = rng.uniform(0.01, 0.2, len(mu))
        a = nb.fit_scale(mu, var)
        perm = rng.permutation(len(mu))
        b = nb.fit_scale(mu[perm], var[perm])
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertTrue(all(y > x for x, y in zip(a["x"], a["x"][1:])))
        d = np.diff(a["s"])
        self.assertTrue(np.all(d <= 0) or np.all(d >= 0))
        self.assertEqual(float(noisescale.evaluate(a, sigm(a["x"][0] - 5))), a["s"][0])
        self.assertEqual(float(noisescale.evaluate(a, sigm(a["x"][-1] + 5))), a["s"][-1])
        x = np.linspace(-2, 2, 400)                                             # (a noiseless step function)
        mu2 = sigm(x)
        step = np.where(mu2 < 0.35, 0.36, np.where(mu2 < 0.70, 0.09, 0.04))
        c = nb.fit_scale(mu2, step)
        self.assertEqual((c["blocks"], c["direction"]), (3, "decreasing"))
        self.assertAlmostEqual(c["x"][0], float(np.mean(x[mu2 < 0.35])), delta=1e-12)
        self.assertGreater(abs(float(noisescale.evaluate(c, 0.30)) - 0.6), 0.01)   # (a ramp inside the plateau)
        self.assertIsNone(nb.fit_scale([], []))
        fit, blocks = nb.pava([3, 1, 2, 5, 4], [1] * 5)
        self.assertTrue(np.allclose(fit, [2, 2, 2, 4.5, 4.5]))
        self.assertEqual(blocks, [(0, 2), (2, 3), (3, 5)])

    def test_nu0_encoding(self):
        """Codex #72 r1 P2-7 / P3: full pooling and unavailability are explicit, serializable statuses; an
        estimated nu0 inverts trigamma exactly."""
        cv = {"x": [0.0], "s": [0.3]}
        mu = np.full(50, 0.4)
        flat = nb.nu0_of(mu, np.full(50, 0.3), np.full(50, 0.01), cv)
        self.assertEqual(flat["status"], "full_pooling")
        self.assertEqual(nb.nu0_of(mu[:2], np.full(2, 0.3), np.full(2, 0.01), cv)["status"], "unavailable")
        self.assertEqual(nb.nu0_of(mu, np.full(50, 0.3), np.full(50, 0.01), None)["status"], "unavailable")
        rng = np.random.default_rng(2)
        sig = 0.3 * np.exp(rng.normal(0, 0.3, 400))
        est = nb.nu0_of(np.full(400, 0.4), sig, np.full(400, 0.001), cv)
        self.assertEqual(est["status"], "estimated")
        self.assertAlmostEqual(nb._trigamma(est["nu0"] / 2), est["excess_log_variance"], delta=1e-9)
        for x in (0.3, 2.0, 40.0, 900.0, 1e8, 1e20):
            self.assertAlmostEqual(nb.inv_trigamma(nb._trigamma(x)) / x, 1.0, delta=1e-9)
        self.assertAlmostEqual(nb._trigamma(nb.inv_trigamma(1e-25)) / 1e-25, 1.0, delta=1e-9)      # (tiny excess)
        with self.assertRaises(nb.NoiseBankError):
            nb.inv_trigamma(0.0)
        for rec in (flat, est):
            rqlib.canonical(rec)

    def test_crossed_bootstrap_multiplicities(self):
        """Codex #72 r1 P2-6: a pair's weight multiplies the multiplicities of its distinct sources (prey role
        m, predator role m'); two draws with the SAME distinct worlds but different multiplicities give
        different estimates; the source keys have the registered shapes (free pairs follow the prey)."""
        self.assertEqual(nb.pick_weights([((0,), (1, 2)), ((0, 1), (2,)), ((2,), (1,)), ((0,), (1, 1))],
                                         [2, 1, 0], [1, 3, 2]).tolist(),
                         [2 * 3 * 2, 2 * 1 * 2, 0, 2 * 3])                     # (a world counts once: not 2 x 3^2)
        doc, _ = simulate(seed=9, W=4, T=2, R=16, horizons=(5000,))
        A = nb.arrays(doc["observations"], 5000)
        U = nb.usable(A)
        G, worlds = nb.group_pairs(A, U)
        tab = nb.group_tables(A, U, G, M)
        shapes = {g: {(len(kp), len(kq)) for kp, kq in tab[g]["keys"]} for g in nb.GROUPS}
        for g in ("R_CC", "R_SS", "R_CS"):              # (two predators of one world: ONE predator world)
            self.assertEqual(shapes[g], {(1, 1), (1, 2)})
        for g in ("D_CC", "D_SS", "D_CS"):
            self.assertEqual(shapes[g], {(1, 1), (2, 1)})
        for g in nb.GROUPS:
            self.assertTrue(all(len(set(kp)) == len(kp) and len(set(kq)) == len(kq) for kp, kq in tab[g]["keys"]))
        rec = nb.interval_record(np.zeros((90, len(nb.BOOT_NAMES))), 10, 100)        # (10% failed: > 5%)
        self.assertEqual((rec["status"], rec["ci95"]), ("unavailable", None))
        rec = nb.interval_record(np.zeros((97, len(nb.BOOT_NAMES))), 3, 100)
        self.assertEqual((rec["status"], rec["failure_rate"]), ("ok", 0.03))
        self.assertIn("conditional on identification", rec["label"])
        for g in ("T_CS", "R_CF", "R_SF"):
            self.assertEqual(shapes[g], {(1, 1)})

        def fit(m, mp):
            return nb._entries(nb.fit_dependence({g: (tab[g]["z"], nb.pick_weights(tab[g]["keys"], m, mp) @ tab[g]["T"])
                                                  for g in nb.GROUPS}))
        a = fit([2, 1, 1, 0], [1, 1, 1, 1])
        b = fit([1, 2, 1, 0], [1, 1, 1, 1])                                   # (the same distinct prey worlds)
        self.assertGreater(max(abs(x - y) for x, y in zip(a, b)), 1e-6)
        D, failed, unident = nb.bootstrap(tab, len(worlds), 5, 0)
        self.assertEqual(D.shape[0] + failed, 5)
        self.assertLessEqual(unident, failed)
        old = nb.INFO_MIN
        nb.INFO_MIN = 1e9                                   # (every weighted refit unidentified: all counted)
        try:
            D2, f2, u2 = nb.bootstrap(tab, len(worlds), 4, 0)
        finally:
            nb.INFO_MIN = old
        self.assertEqual((len(D2), f2, u2), (0, 4, 4))
        self.assertEqual(nb.interval_record(D2, f2, 4, u2)["status"], "unavailable")


# ================================================================== the V builder
CURVES = {"C": {"x": [-2.0, 0.0, 2.0], "s": [0.6, 0.4, 0.3]}, "S": {"x": [-1.0, 2.0], "s": [0.2, 0.3]},
          "F": {"x": [0.0, 3.0], "s": [0.22, 0.3]}}


@unittest.skipIf(np is None, "numpy is not installed")
class TestVBuilder(unittest.TestCase):
    st = {"prey": [0, 0, 1, 1, 2], "pred": [0, 1, 0, 1, 1], "n_prey": 3, "n_pred": 2}

    def setUp(self):
        self.noise = {"SigmaR": TRUE["SigmaR"], "SigmaD": TRUE["SigmaD"], "SigmaE": TRUE["SigmaE"],
                      "s_logit": CURVES, "capture_bound": 324}

    def test_term_by_term(self):
        """cov_parts against the covariance written out term by term (capture: row + donor + cell; survival: the
        exposed cell minus its prey snapshot's free control), s(mu) through the shared evaluator, at explicitly
        given means; also with the free row variance at its minimal-feasible convention."""
        R, st = 6, self.st
        SR, SD = np.array(TRUE["SigmaR"]), np.array(TRUE["SigmaD"])

        def s(ch, m):
            return noisescale.evaluate(CURVES[ch], m)
        for means in ({"C": np.array([0.2, 0.4, 0.5, 0.8, 0.33])}, {"C": np.full(5, 0.36)}):
            d, U = nb.cov_parts(self.noise, "C", st, means, R)
            g = s("C", means["C"]) * means["C"] * (1 - means["C"])
            want = np.zeros((5, 5))
            for i in range(5):
                for j in range(5):
                    v = SR[0, 0] * (st["prey"][i] == st["prey"][j]) + SD[0, 0] * (st["pred"][i] == st["pred"][j])
                    v += (1 - SR[0, 0] - SD[0, 0]) * (i == j)
                    want[i, j] = g[i] * g[j] * v / R
            self.assertTrue(np.allclose(np.diag(d) + U @ U.T, want, atol=1e-15))
        conv = SR.copy()
        conv[2, 2] = float(SR[:2, 2] @ np.linalg.inv(SR[:2, :2]) @ SR[:2, 2])
        for SRx in (SR, conv):
            noise = dict(self.noise, SigmaR=SRx.tolist())
            mS, mF = np.array([0.7, 0.8, 0.6, 0.9, 0.75]), np.array([0.85, 0.9, 0.8])
            d, U = nb.cov_parts(noise, "Q", st, {"S": mS, "F": mF}, R)
            gS = s("S", mS) * mS * (1 - mS)
            mFi = mF[st["prey"]]
            gF = s("F", mFi) * mFi * (1 - mFi)
            want = np.zeros((5, 5))
            for i in range(5):
                for j in range(5):
                    sp, sd = st["prey"][i] == st["prey"][j], st["pred"][i] == st["pred"][j]
                    v = gS[i] * gS[j] * (SRx[1, 1] * sp + SD[1, 1] * sd + (1 - SRx[1, 1] - SD[1, 1]) * (i == j))
                    v -= (gS[i] * gF[j] + gF[i] * gS[j]) * SRx[1, 2] * sp
                    v += gF[i] * gF[j] * 1.0 * sp                               # (the total free variance)
                    want[i, j] = v / R
            self.assertTrue(np.allclose(np.diag(d) + U @ U.T, want, atol=1e-15))

    def test_against_the_generator(self):
        """The linearized builder against the simulated covariance of replicate means from H.9.2's rounded
        logistic-normal generator at small s (where the delta method is accurate): capture and the survival
        difference, 6,000 simulated blocks, relative Frobenius error < 8%."""
        small = {ch: {"x": cv["x"], "s": [v / 6 for v in cv["s"]]} for ch, cv in CURVES.items()}
        noise = dict(self.noise, s_logit=small)
        R, st, n = 6, self.st, 6000
        rng = np.random.default_rng(11)
        SR, SD, SE = (np.array(TRUE[k]) for k in ("SigmaR", "SigmaD", "SigmaE"))
        LR, LD, LE = (nb._psd_factor(M) for M in (SR, SD, SE))
        mC = np.array([0.2, 0.4, 0.5, 0.8, 0.33])
        mS, mF = np.array([0.7, 0.8, 0.6, 0.9, 0.75]), np.array([0.85, 0.9, 0.8])
        pi, pj = np.array(st["prey"]), np.array(st["pred"])
        sC, sS, sF = (noisescale.evaluate(small[ch], m) for ch, m in (("C", mC), ("S", mS), ("F", mF)))
        aC, aS, aF = location(mC, sC, 324), location(mS, sS, 600), location(mF, sF, 600)
        row = rng.standard_normal((n, R, 3, 3)) @ LR.T                          # (sims, reps, prey keys, C S F)
        don = rng.standard_normal((n, R, 2, 2)) @ LD.T
        E = rng.standard_normal((n, R, 5, 2)) @ LE.T
        eF = math.sqrt(1 - SR[2, 2]) * rng.standard_normal((n, R, 3))
        uC = row[:, :, pi, 0] + don[:, :, pj, 0] + E[:, :, :, 0]
        uS = row[:, :, pi, 1] + don[:, :, pj, 1] + E[:, :, :, 1]
        uF = row[:, :, :, 2] + eF
        YC = np.floor(324 * sigm(aC + sC * uC) + 0.5).mean(axis=1) / 324
        YQ = (np.floor(600 * sigm(aS + sS * uS) + 0.5).mean(axis=1) / 600
              - (np.floor(600 * sigm(aF + sF * uF) + 0.5).mean(axis=1) / 600)[:, pi])
        for kind, Y, means in (("C", YC, {"C": mC}), ("Q", YQ, {"S": mS, "F": mF})):
            d, U = nb.cov_parts(noise, kind, st, means, R)
            V = np.diag(d) + U @ U.T
            self.assertLess(float(np.linalg.norm(np.cov(Y.T) - V) / np.linalg.norm(V)), 0.08, kind)

    def test_refusals(self):
        """Codex #72 r1 P3: unknown kinds, non-positive or non-integer replicate counts, a bank without valid
        s(mu) curves (no binned default), and malformed structures or means are refused."""
        with self.assertRaises(nb.NoiseBankError):
            nb.cov_parts(self.noise, "X", self.st, {"C": np.full(5, 0.3)})
        for R in (0, -1, 2.5, True):
            with self.assertRaises(nb.NoiseBankError):
                nb.cov_parts(self.noise, "C", self.st, {"C": np.full(5, 0.3)}, R)
        with self.assertRaises(nb.NoiseBankError):
            nb.cov_parts(dict(self.noise, s_logit=None), "C", self.st, {"C": np.full(5, 0.3)})
        with self.assertRaises(nb.NoiseBankError):
            nb.cov_parts(dict(self.noise, s_logit=dict(CURVES, C={"x": [0.0, 1.0], "s": [0.3, 0.2, 0.1]})), "C",
                         self.st, {"C": np.full(5, 0.3)})
        with self.assertRaises(nb.NoiseBankError):
            nb.cov_parts(self.noise, "C", dict(self.st, prey=[0, 0, 1, 1, 7]), {"C": np.full(5, 0.3)})
        with self.assertRaises(nb.NoiseBankError):
            nb.cov_parts(self.noise, "Q", self.st, {"S": np.full(5, 0.8), "F": np.full(2, 0.8)})


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
                           validation_dir=self.root, arena="a", main_registries=[self.f["main"]])
        rows, _, _ = plan.expand_v2(d, pending=True)
        for r in rows:
            for k in nb.HASHED:
                if isinstance(r.get(k), dict) and r[k].get("path"):
                    r[k]["sha256"] = rqlib.sha256_bytes(f"{k}|{r[k]['path']}".encode())
        pp = os.path.join(self.tmp, "plan.jsonl")
        plan.write_plan(rows, pp)
        pick = rows[:3]

        def bundle(r, n=600):
            return {"schema": "finfolk.redqueen.bundle/2", "cell": r,
                    "score": {"n_start": n, "horizons": [{"steps": h, "survivors": 400 if h == 5000 else 0,
                                                         "captures": 50}
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
        # Collection reads legacy bundles without diagnostics and /3 bundles identically.
        import score

        def v3(r):
            b = bundle(r)
            b["schema"] = "finfolk.redqueen.bundle/3"
            b["score"]["dt"] = score.DT
            start = dict.fromkeys(range(600), 0.0)
            for h in b["score"]["horizons"]:
                alive = set(range(400)) if h["steps"] == 5000 else set()
                h["frame"] = 1000 + h["steps"]
                h["age_strata"] = score.age_strata(start, alive, 120.0, h["steps"], h["frame"], score.DT, 600,
                                                   len(alive))
            return b
        newer = {r["id"]: v3(r) for r in pick}
        self.assertEqual(nb.collect(study(newer), d, pp, rest), doc)
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

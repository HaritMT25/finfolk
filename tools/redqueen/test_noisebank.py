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
  * the D8 bank refit (A_design_v5.md section 2; test IDs of its section 5), synthetic data only (D9):
    - T4-1 / T4-2 the capped interval map and marginal MLE near the ceiling; T4-7 the D8-only minimum-categories
      screen; the ceilings threaded through arrays;
    - T4-3 population recovery under capping (20 banks) and log_rect on capped rectangles; T4-4 the zero-ceiling
      capture-only fit (structural zeros, C4.2's maxima, infeasible maxima, refused bootstrap draws); the D8
      bootstrap streams;
    - a registered-size synthetic store through provenance and estimate-d8 into obslaw's strict loader (the round
      trip; every single-field corruption refused), the receipt written first and bound, the D5 ledger charged;
      T5-1 every binding of 2.1; T4-5 support counts only; R4 the clock's ceilings; R7; clarification 2 D3;
    - T5-2 / T5-6 provenance on a small synthetic store: one engine, ages, cell set, reconstruction, verify_all
      (a repacked chunk, no manifest), verify_chunk (an extra member), a manifest (conflicting duplicate
      declarations refused in both orders and every spelling), the registered root by path;
    - the validation of 2.10: the spec, banks on the D8 validation streams, independent known answers for the
      means / latent draw order and V3's grid, V1-V5, clarification 3 E1's bootstrap stream (V1-V5 take nothing
      from it), an end-to-end run at a test size; A's assembly of a generator artifact (2.8) and T5-4 against the
      pinned #68 commit (adoption gate: RQ_PR68_DIR; skipped without it, the only permitted skip);
    - the D5 ledger and the attempt records (2.11): every entry validated, no implicit ledger, the durable
      in-progress attempt and its refreshes, a late failure charged as one, a SIGKILLed run refused until
      reconciled and then charged once (its last durable CPU + 60 s).
numpy required for the estimator (RQ_REQUIRE_NUMPY=1 makes a missing numpy a failure).

    python3 -I tools/redqueen/test_noisebank.py [-v]
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
import material  # noqa: E402
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
if np is not None:
    import obslaw as ol  # noqa: E402  (the D8 law, streams and strict bank/3 loader; numpy)

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
    for name, txt in (("t.json", "{}"), ("ages.json", "{}"), ("prod.json", json.dumps({"reserved_seeds": [101]}))):
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
        self.assertEqual(meta["avoid"], [rqlib.load_reservations(self.f["prod.json"])[1]])
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
        cls.bank = nb.estimate(cls.doc, descriptive=True, boot=29, m=M)

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
        self.assertFalse(g["available"])
        self.assertEqual(self.bank["purpose"], "descriptive")
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
        bank = nb.estimate(doc, descriptive=True, boot=3, m=M)
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
                self.assertEqual(nb.main(["estimate", "--descriptive", "--obs", p, "--boot", "2", "--out", out]), 2)
            self.assertFalse(rqlib.read_json(out)["generator_noise"]["available"])
        finally:
            nb.REPLICATES = old
            shutil.rmtree(tmp)
        doc2 = all_horizons(simulate(seed=8, W=4, T=2, R=16, horizons=(5000,))[0])
        old = nb.INFO_MIN
        nb.INFO_MIN = 1e9
        try:
            e2 = nb.estimate(doc2, descriptive=True, boot=2, m=M)["horizons"]["5000"]
        finally:
            nb.INFO_MIN = old
        self.assertEqual(e2["status"], "unavailable")
        self.assertTrue(any("unidentified" in r for r in e2["reasons"]))
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(doc2, descriptive=True, boot=0)
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(doc2, descriptive=True, boot=2, m=M, replicates=64)
        bad = json.loads(json.dumps(doc2))
        bad["observations"][-1]["horizons"]["5000"]["survivors"] = 10 ** 6
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(bad, descriptive=True, boot=2, m=M)
        bad["observations"][-1]["horizons"]["5000"]["survivors"] = 1.5
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(bad, descriptive=True, boot=2, m=M)
        bad["observations"][-1]["horizons"]["5000"]["survivors"] = 1
        bad["observations"][-1]["replicate"] = 99
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(bad, descriptive=True, boot=2, m=M)
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(dict(doc2, schema="x"), descriptive=True, boot=2)


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
            # (Codex re-review of 6407f80, P2) compressed as pack() writes chunks (store.PACK_METHOD, DEFLATE):
            # collection now refuses any other method before decoding (store.read_packed)
            with zipfile.ZipFile(os.path.join(root, store.CHUNKS, "c0001.zip"), "w",
                                 compression=store.PACK_METHOD) as z:
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
        # Collection reads legacy bundles without diagnostics and /3 bundles identically (the same
        # observation bytes); D8 v2 rule 48 at ingestion (Codex review of 870daa6, P2-3): the /3 age
        # summaries go to the separately versioned diagnostics output, where /1 and /2 bundles are
        # explicitly unavailable, and a /3 bundle without a complete summary is refused.
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
        got, ages = nb.collect_with_age_diagnostics(study(newer), d, pp, rest)
        self.assertEqual(rqlib.canonical(got), rqlib.canonical(doc))
        self.assertEqual(nb.collect(study(newer), d, pp, rest), doc)
        self.assertEqual((ages["schema"], ages["observations_sha256"], ages["missing"], ages["available"],
                          ages["unavailable"]), (store.AGE_DIAGNOSTICS_SCHEMA, rqlib.canonical_sha(doc), rest, 3, 0))
        for c in ages["cells"]:
            self.assertEqual(c["horizons"], {str(h["steps"]): h["age_strata"]
                                             for h in newer[c["cell"]]["score"]["horizons"]})
        _, old = nb.collect_with_age_diagnostics(study({r["id"]: bundle(r) for r in pick}), d, pp, rest)
        self.assertEqual((old["available"], old["unavailable"]), (0, 3))
        self.assertTrue(all(not c["available"] and "predates" in c["reason"] and "horizons" not in c
                            for c in old["cells"]))
        for corrupt in (lambda b: b["score"]["horizons"][2].pop("age_strata"),       # a missing summary
                        lambda b: b["score"]["horizons"].pop(),                        # a registered horizon
                        lambda b: b["score"]["horizons"][0].update(survivors=399)):    # unreconciled
            broken = {r["id"]: v3(r) for r in pick}
            corrupt(broken[pick[1]["id"]])
            with self.assertRaisesRegex(nb.NoiseBankError, "age summary"):
                nb.collect(study(broken), d, pp, rest)
        # the CLI writes the diagnostics only where asked, beside the unchanged observations
        dp, op, ap = (os.path.join(self.tmp, x) for x in ("design.json", "obs.json", "age_diagnostics.json"))
        rqlib.write_json_durable(dp, d)
        args = ["collect", "--study", study(newer), "--design", dp, "--plan", pp, "--declare-missing", *rest,
                "--out", op]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(nb.main(args), 0)
            self.assertFalse(os.path.exists(ap))
            self.assertEqual(nb.main(args + ["--age-diagnostics", ap]), 0)
        self.assertEqual((rqlib.read_json(op), rqlib.read_json(ap)), (doc, ages))
        with self.assertRaises(nb.NoiseBankError):
            nb.collect(study({r["id"]: bundle(r) for r in pick}), d, pp)                      # (undeclared missing)
        with self.assertRaises(nb.NoiseBankError):
            nb.collect(study({pick[0]["id"]: bundle(pick[0], 599)}), d, pp, sorted(set(rest) | {r["id"] for r in pick[1:]}))
        bad = dict(bundle(pick[0]))
        bad["score"] = {"n_start": 600, "horizons": [{"steps": 5000, "survivors": 1, "captures": 1}]}
        with self.assertRaises(nb.NoiseBankError):
            nb.collect(study({pick[0]["id"]: bad}), d, pp, sorted(set(rest) | {r["id"] for r in pick[1:]}))

    def test_method_byte_collect_refused(self):
        """Codex re-review of 6407f80, P2: collection reads every indexed bundle (a cell's design is recorded
        only inside it) through store.read_packed. A packed bundle whose central-directory compression method
        is one the packer never writes (test_redqueen.METHODS: STORED, BZIP2, LZMA, Zstandard, unknown; a
        large, poorly compressible bundle, the size kept) refuses the WHOLE collection, whether it is a cell
        of this plan ("plan") or another design's (a plan/1 cell, "p1"; a plan/2 cell of another design,
        "p2": never skipped, its design being in the unreadable bundle). collect raises NoiseBankError naming
        the root, the chunk, the cell, the method ("refused before decoding") and whose cell it is; the CLI
        exits 2 with that one line, no traceback, writing neither --out nor --age-diagnostics; the bundle is
        never opened (no decoder ran on it) and every byte of the root is kept. (6407f80 decoded it: LZMAError,
        ZstdError on 3.14 and NotImplementedError escaped as tracebacks; a CRC or bzip2 error was an exit 2
        naming no cell.) The controls (every member DEFLATE) collect, a foreign cell skipped: the same
        observations as without it."""
        import store
        import zipfile
        from test_redqueen import METHODS, POOR_PAYLOAD, members_opened, set_chunk_member_method, tree_bytes
        d = nb.make_design(block(self.root), [self.f["t.json"]], self.f["ages.json"], [self.f["prod.json"]],
                           validation_dir=self.root, arena="a", main_registries=[self.f["main"]])
        rows, _, _ = plan.expand_v2(d, pending=True)
        for r in rows:
            for k in nb.HASHED:
                if isinstance(r.get(k), dict) and r[k].get("path"):
                    r[k]["sha256"] = rqlib.sha256_bytes(f"{k}|{r[k]['path']}".encode())
        pp, dp = os.path.join(self.tmp, "plan.jsonl"), os.path.join(self.tmp, "design.json")
        plan.write_plan(rows, pp)
        rqlib.write_json_durable(dp, d)
        pick = rows[:3]
        rest = sorted({r["id"] for r in rows} - {r["id"] for r in pick})
        foreign = {"p1": lambda cid: {"id": cid, "schema": "finfolk.redqueen.plan/1", "kind": "assay"},
                   "p2": lambda cid: {"id": cid, "schema": plan.PLAN_SCHEMA_V2, "kind": "assay",
                                      "design": "another-design"}}

        def bundle(cell_, payload="x"):
            return {"schema": "finfolk.redqueen.bundle/2", "cell": cell_, "payload": payload,
                    "score": {"n_start": 600, "horizons": [{"steps": h, "survivors": 400 if h == 5000 else 0,
                                                            "captures": 50} for h in nb.HORIZONS]}}

        def study(whose, name):
            """The picked cells packed DEFLATE as pack() writes chunks (plus whose's foreign cell), the target's
            bundle large and poorly compressible, then (name != "complete") its method byte set -> (root, target)."""
            root = os.path.join(self.tmp, f"study-{whose}-{name}")
            os.makedirs(os.path.join(root, store.CHUNKS))
            target = pick[1]["id"] if whose == "plan" else f"{name}-{whose}"
            bundles = {r["id"]: bundle(r, POOR_PAYLOAD if r["id"] == target else "x") for r in pick}
            if whose != "plan":
                bundles[target] = bundle(foreign[whose](target), POOR_PAYLOAD)
            chunk, cells = os.path.join(root, store.CHUNKS, "chunk_000001.zip"), {}
            with zipfile.ZipFile(chunk, "w", compression=store.PACK_METHOD) as z:
                for cid in sorted(bundles):
                    data = json.dumps(bundles[cid]).encode()
                    z.writestr(f"{cid}/bundle.json", data)
                    cells[cid] = {"bundle_sha256": rqlib.sha256_bytes(data)}
            with open(os.path.join(root, store.INDEX), "w") as f:
                f.write(json.dumps({"chunk": "chunk_000001.zip", "cells": cells}) + "\n")
            if name != "complete":
                set_chunk_member_method(chunk, f"{target}/bundle.json", METHODS[name])
            return root, target
        ref = nb.collect(study("plan", "complete")[0], d, pp, rest)
        self.assertEqual(len(ref["observations"]), 3)
        bound = nb.bind_plan(d, pp)

        def bind(design, plan_path):        # (the binding is upstream of the reads under test: bound once)
            self.assertEqual((rqlib.canonical(design), plan_path), (rqlib.canonical(d), pp))
            return bound
        for whose, name in [(w, n) for w in ("plan", "p1", "p2") for n in METHODS] + [("p1", "complete"),
                                                                                    ("p2", "complete")]:
            root, target = study(whose, name)
            if name == "complete":
                with self.subTest(cid=target), mock.patch.object(nb, "bind_plan", bind):
                    self.assertEqual(nb.collect(root, d, pp, rest), ref)        # (intact: the foreign cell skipped)
                continue
            before = tree_bytes(root)
            m = METHODS[name]
            with mock.patch.object(nb, "bind_plan", bind):
                with self.subTest(cid=target, method=name, whose=whose, path="collect"):
                    with members_opened() as opened, self.assertRaises(nb.NoiseBankError) as cm:
                        nb.collect(root, d, pp, rest)
                    msg = str(cm.exception)
                    self.assertIn(f"collection refused: {target} (packed in chunk_000001.zip of {root}): its packed "
                                  "bundle.json cannot be read (", msg)
                    self.assertIn(f"compression method {m}, not the DEFLATE (8) pack() writes: refused before "
                                  "decoding", msg)
                    self.assertIn("(a cell of this plan)" if whose == "plan" else "not one of this plan's cell ids",
                                  msg)
                    self.assertNotIn(f"{target}/bundle.json", opened)
                    self.assertEqual(tree_bytes(root), before)
                with self.subTest(cid=target, method=name, whose=whose, path="cli"):
                    op, ap = (os.path.join(self.tmp, f"{x}-{whose}-{name}.json") for x in ("obs", "ages"))
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()), \
                            members_opened() as opened:
                        rc = nb.main(["collect", "--study", root, "--design", dp, "--plan", pp, "--declare-missing",
                                      *rest, "--out", op, "--age-diagnostics", ap])
                    self.assertEqual(rc, 2, err.getvalue())
                    self.assertNotIn("Traceback", err.getvalue())
                    self.assertTrue(err.getvalue().startswith(
                        f"noisebank.py collect: collection refused: {target} (packed in chunk_000001.zip of {root}): "),
                        err.getvalue())
                    self.assertIn(f"compression method {m}, not the DEFLATE (8) pack() writes", err.getvalue())
                    self.assertEqual(err.getvalue().count("\n"), 1, err.getvalue())
                    self.assertNotIn(f"{target}/bundle.json", opened)
                    self.assertFalse(os.path.exists(op) or os.path.exists(ap))
                    self.assertEqual(tree_bytes(root), before)



@unittest.skipIf(np is None, "numpy is not installed")
class TestBankCoverage(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        fixture = TestPlan()
        fixture.setUp()
        try:
            Path(fixture.f['prod.json']).write_text('{"reserved_seeds":[101]}')
            cls.design = fixture.design()
        finally:
            fixture.tearDown()
        rows, _, _ = plan.expand_v2(cls.design, pending=True)
        cls.doc = {
            'schema': nb.OBS_SCHEMA, 'design': cls.design,
            'design_sha256': rqlib.canonical_sha(cls.design), 'plan_sha256': 'b' * 64, 'missing': [],
            'observations': [
                {'cell': row['id'], 'prey': [row['prey']['world'], row['prey']['time']],
                 'pred': None if row['predators'] is None else
                         [row['predators']['world'], row['predators']['time']],
                 'replicate': row['replicate'],
                 'horizons': {str(h): {'captures': 50, 'survivors': 400} for h in nb.HORIZONS}}
                for row in rows]
        }

    def fitted(self, doc, **kw):
        curve = {'x': [-1.0, 1.0], 's': [0.2, 0.3], 'direction': 'increasing'}
        h = {'status': 'ok', 'reasons': [], 'scales': {c: curve for c in 'CSF'}, 'nu0': {},
             'components': {c: [[1.0, 0.0], [0.0, 1.0]] for c in ('SigmaR', 'SigmaD', 'SigmaE')}}
        with mock.patch.object(nb, 'horizon_estimate', return_value=h):
            return nb.estimate(doc, boot=1, **kw)

    def test_complete_registered_bank_available_and_provenance(self):
        self.assertEqual(len(self.doc['observations']), 18432)
        bank = self.fitted(self.doc)
        self.assertTrue(bank['generator_noise']['available'])
        import numpy as np
        self.assertEqual(bank['provenance']['numpy_version'], np.__version__)
        self.assertEqual(bank['provenance']['estimator_sha256'], rqlib.sha256_file(nb.__file__))
        self.assertEqual(bank['provenance']['observations_sha256'], rqlib.canonical_sha(self.doc))

    def test_missing_and_duplicate_coverage(self):
        mutations = ('declared',
         'whole_pair',
         'one_rep',
         'whole_free',
         'whole_replicate',
         'duplicate_free',
         'duplicate_exposed',
         'wrong_endpoint',
         'no_design',
         'wrong_design_hash',
         'reduced_design')
        for mutate in mutations:
            doc = copy.deepcopy(self.doc)
            obs = doc['observations']
            free = next((o for o in obs if o['pred'] is None))
            exposed = next((o for o in obs if o['pred'] is not None))
            if mutate == 'declared':
                doc['missing'] = ['lost-cell']
            if mutate == 'whole_pair':
                doc['observations'] = [o for o in obs if (o['prey'], o['pred']) != (exposed['prey'], exposed['pred'])]
            if mutate == 'one_rep':
                obs.remove(exposed)
            if mutate == 'whole_free':
                doc['observations'] = [o for o in obs if (o['prey'], o['pred']) != (free['prey'], None)]
            if mutate == 'whole_replicate':
                doc['observations'] = [o for o in obs if o['replicate'] != 63]
            if mutate.startswith('duplicate'):
                obs.append(copy.deepcopy(free if mutate == 'duplicate_free' else exposed))
            if mutate == 'wrong_endpoint':
                exposed['pred'] = ['wrong', '20M']
            if mutate == 'no_design':
                doc.pop('design')
            if mutate == 'wrong_design_hash':
                doc['design_sha256'] = '0' * 64
            if mutate == 'reduced_design':
                doc['design']['edges'].pop()
                doc['design_sha256'] = rqlib.canonical_sha(doc['design'])
            with self.subTest(mutate=mutate):
                with self.assertRaises(nb.NoiseBankError):
                    self.fitted(doc)

    def test_descriptive_cannot_be_production_available(self):
        doc = copy.deepcopy(self.doc)
        doc['observations'].pop()
        doc['missing'] = ['lost']
        bank = self.fitted(doc, descriptive=True)
        self.assertFalse(bank['generator_noise']['available'])
        self.assertEqual(bank['purpose'], 'descriptive')
        for pred in (None, 'exposed'):
            o = next((o for o in doc['observations'] if (o['pred'] is None) == (pred is None)))
            duplicate = copy.deepcopy(o)
            duplicate['cell'] += '.duplicate'
            doc['observations'].append(duplicate)
            with self.assertRaises(nb.NoiseBankError):
                self.fitted(doc, descriptive=True)
            doc['observations'].pop()

    def test_empty_expanded_bank_design(self):
        doc = copy.deepcopy(self.doc)
        doc['design']['edges'] = []
        doc['design_sha256'] = rqlib.canonical_sha(doc['design'])
        rows, _, _ = plan.expand_v2(doc['design'], pending=True)
        self.assertEqual(rows, [])
        with self.assertRaisesRegex(nb.NoiseBankError, 'empty.*allocation'):
            self.fitted(doc)

    def test_exactly_one_missing_free_control(self):
        doc = copy.deepcopy(self.doc)
        free = next(o for o in doc['observations'] if o['pred'] is None)
        doc['observations'].remove(free)
        self.assertEqual(len(doc['observations']), 18431)
        with self.assertRaisesRegex(nb.NoiseBankError, r'1 missing, 0 extra'):
            self.fitted(doc)

    def test_cli_requires_descriptive_flag_for_partial_bank(self):
        doc = copy.deepcopy(self.doc)
        doc['observations'].pop()
        doc['missing'] = ['lost']
        with tempfile.TemporaryDirectory() as directory:
            source, output = (Path(directory) / 'obs.json', Path(directory) / 'bank.json')
            source.write_bytes(rqlib.canonical(doc))
            args = ['estimate', '--obs', str(source), '--out', str(output), '--boot', '1']
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with mock.patch.object(nb, 'horizon_estimate', return_value={'reasons': ['test unavailable'], 'scales': dict.fromkeys('CSF'), 'nu0': {}}):
                    self.assertEqual(nb.main(args), 2)
                    self.assertFalse(output.exists())
                    self.assertEqual(nb.main(args + ['--descriptive']), 2)
            result = rqlib.read_json(output)
            self.assertEqual(result['purpose'], 'descriptive')
            self.assertFalse(result['generator_noise']['available'])

    def test_older_observations_can_bind_explicit_design(self):
        doc = copy.deepcopy(self.doc)
        doc.pop('design')
        bank = self.fitted(doc, design=self.design)
        self.assertTrue(bank['generator_noise']['available'])

    def test_arrays_refuse_duplicate_free_control(self):
        free = next((o for o in self.doc['observations'] if o['pred'] is None))
        with self.assertRaises(nb.NoiseBankError):
            nb.arrays([free, copy.deepcopy(free)], 5000)

    def test_cli_hashes_exact_input_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p, out = (Path(d) / 'obs.json', Path(d) / 'bank.json')
            p.write_text(json.dumps(self.doc, indent=1))
            with mock.patch.object(nb, 'horizon_estimate', return_value={'reasons': ['test unavailable'], 'scales': dict.fromkeys('CSF'), 'nu0': {}}):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(nb.main(['estimate', '--obs', str(p), '--out', str(out), '--boot', '1']), 2)
            result = rqlib.read_json(out)
            self.assertEqual(result['provenance']['observations_sha256'], rqlib.sha256_file(p))
            self.assertNotEqual(rqlib.sha256_file(p), rqlib.canonical_sha(self.doc))


# ================================================================== the D8 refit (A_design_v5.md section 2; WP3)
# Synthetic data only (D9): the banks below are drawn by obslaw's generator (the capped law, v5 1.4-1.6) from the
# declared synthetic parameters of v5 2.10 (typed here from v5, not read from noisebank); the registered-size world is a
# synthetic store whose design, plan and observations are bound by TEST bindings (whatever non-registered bindings
# produce is synthetic). Test IDs are v5 5's: T4-1..T4-5, T4-7, T5-1, T5-2, T5-4 (adoption gate), T5-6; the round trip
# through obslaw's strict loader; V1-V5's machinery (T4-6 itself runs on the server).
VAL_SR = [[0.25, 0.05, 0.05], [0.05, 0.25, 0.15], [0.05, 0.15, 0.50]]   # v5 2.10 L789 (then [F][F] by the convention)
VAL_FF = 0.0055 / 0.06                     # v' A^-1 v, A = [[.25, .05], [.05, .25]], v = (.05, .15): the convention
VAL_SD = [[0.25, 0.05], [0.05, 0.25]]
VAL_SE = [[0.50, 0.10], [0.10, 0.50]]
VAL_CURVES = {"C": {"x": [-2.2, -0.6, 0.4], "s": [0.55, 0.30, 0.20]},
              "S": {"x": [-2.5, -1.2, -0.5], "s": [0.35, 0.25, 0.22]},
              "F": {"x": [-2.5, -1.2, -0.5], "s": [0.35, 0.25, 0.22]}}
GROUP_TRUTH = {"R_CC": 0.25, "R_SS": 0.25, "R_CS": 0.05, "D_CC": 0.25, "D_SS": 0.25, "D_CS": 0.05,
               "T_CS": 0.05 + 0.05 + 0.10, "R_CF": 0.05, "R_SF": 0.15}
THETA_TRUTH = {"R_CC": 0.25, "R_SS": 0.25, "R_CS": 0.05, "R_CF": 0.05, "R_SF": 0.15, "D_CC": 0.25, "D_SS": 0.25,
               "D_CS": 0.05, "E_CC": 0.50, "E_SS": 0.50, "E_CS": 0.10}
CEIL = {"5000": 247, "10000": 0, "20000": 0}                             # D8:154
C247 = 247 / 600
AGES_FIXTURE = os.path.join(HERE, "fixtures", "registered_ages.json")


def val_components():
    SR = [list(r) for r in VAL_SR]
    SR[2][2] = VAL_FF
    return SR, VAL_SD, VAL_SE


def capped_counts(mu, u, N, M, curve):
    """obslaw's capped count law at exact locations (v5 1.6)."""
    return ol.generate_counts(mu, u, N, M, lambda x: ol.scale(curve, x),
                              lambda x, i: ol.solve_location(x, ol.scale(curve, x), N, M)[0])[0]


def capped_obs(seed, W=4, T=2, R=16, horizons=(5000,), keep=None):
    """A small bank under the capped law, drawn by obslaw from v5 2.10's declared components, curves and means (capture
    sigma(-0.6 + 0.4 z), free survival c sigma(eta), exposed c sigma(eta - Delta): F crowds the ceiling): W worlds x T
    times, each prey snapshot meeting its own world's and its partner's predator snapshots; M = 247 at 5k and 0 at
    10k / 20k (every survivor 0 there). keep: only these (prey, pred) pairs and their prey's controls are usable, every
    other count is 0 (saturated). -> observations in noisebank's encoding."""
    rng = np.random.default_rng(seed)
    worlds = [f"w{i}" for i in range(W)]
    times = nb.TIMES[:T]
    prey = sorted((w, t) for w in worlds for t in times)
    partner = {w: worlds[(k + 1) % W] for k, w in enumerate(worlds)}
    pairs = sorted((q, (wp, tp)) for q in prey for wp in (q[0], partner[q[0]]) for tp in times)
    pred = sorted({p for _, p in pairs})
    qi = np.array([prey.index(q) for q, _ in pairs])
    pj = np.array([pred.index(p) for _, p in pairs])
    fac = ol.psd_factors(*val_components())
    eta = rng.uniform(0.5, 3.5, len(prey))
    zc, dl = rng.uniform(-2, 2, len(pairs)), rng.uniform(0, 1, len(pairs))
    cells = {}
    for h in horizons:
        M, B = CEIL[str(h)], nb.capture_bound(h)
        c = M / 600
        mu = {"C": 1 / (1 + np.exp(0.6 - 0.4 * zc)), "S": c / (1 + np.exp(-(eta[qi] - dl))),
              "F": c / (1 + np.exp(-eta))}
        if keep is not None:
            kp = np.array([(q, p) in keep for q, p in pairs])
            kq = np.array([q in {a for a, _ in keep} for q in prey])
            mu = {"C": np.where(kp, mu["C"], 0.0), "S": np.where(kp, mu["S"], 0.0), "F": np.where(kq, mu["F"], 0.0)}
        lat = ol.latent(ol.standard_normals(rng, len(prey), len(pred), len(pairs), R), fac, qi, pj)
        K = {ch: capped_counts(mu[ch], lat[ch], n, m, VAL_CURVES[ch])
             for ch, n, m in (("C", B, B), ("S", 600, M), ("F", 600, M))}
        for e, (q, p) in enumerate(pairs):
            for r in range(R):
                x = cells.setdefault((q, p, r), {"cell": f"{q}|{p}|{r}", "prey": list(q), "pred": list(p),
                                                 "replicate": r, "horizons": {}})
                x["horizons"][str(h)] = {"captures": int(K["C"][e, r]), "survivors": int(K["S"][e, r])}
        for i, q in enumerate(prey):
            for r in range(R):
                x = cells.setdefault((q, None, r), {"cell": f"{q}|free|{r}", "prey": list(q), "pred": None,
                                                    "replicate": r, "horizons": {}})
                x["horizons"][str(h)] = {"captures": None, "survivors": int(K["F"][i, r])}
    return list(cells.values())


def survival_paths(node, path=""):
    """Paths of every key naming a survival quantity (obslaw.SURVIVAL_KEYS) below node."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}"
            if k in ol.SURVIVAL_KEYS:
                out.append(p)
            out += survival_paths(v, p)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += survival_paths(v, f"{path}[{i}]")
    return out


@unittest.skipIf(np is None, "numpy is not installed")
class TestD8CeilingAndScreen(unittest.TestCase):
    """T4-1, T4-2, T4-7 and the ceiling threading of v5 2.5 items 1-3."""

    def test_T4_1_interval_bounds_capped_at_the_ceiling(self):
        """interval_bounds(k, 600, 247): +inf upper end at 247, the old map below it, k > 247 refused; capture (and
        every default caller) unchanged."""
        k = np.arange(0, 248, dtype=float)
        lo, hi = nb.interval_bounds(k, 600, 247)
        lo0, hi0 = nb.interval_bounds(k, 600)
        self.assertEqual(hi[247], math.inf)
        self.assertEqual(lo[247], math.log(246.5 / 353.5))                     # (t_247 = logit(246.5 / 600))
        self.assertTrue(np.array_equal(lo, lo0) and np.array_equal(hi[:247], hi0[:247]))
        self.assertEqual(hi0[247], math.log(247.5 / 352.5))                     # (the old map: an interior interval)
        self.assertEqual(lo[0], -math.inf)
        for bad in (248, 600):
            with self.subTest(k=bad), self.assertRaisesRegex(nb.NoiseBankError, "above the ceiling 247"):
                nb.interval_bounds(np.array([3.0, bad]), 600, 247)
        kc = np.arange(0, 325, dtype=float)
        a, b = nb.interval_bounds(kc, 324)
        a2, b2 = nb.interval_bounds(kc, 324, 324)
        self.assertTrue(np.array_equal(a, a2) and np.array_equal(b, b2))
        self.assertEqual((b[324], b[323]), (math.inf, math.log(323.5 / 0.5)))
        with self.assertRaises(nb.NoiseBankError):
            nb.interval_bounds(np.array([325.0]), 324)
        lo, hi = nb.interval_bounds(np.zeros(3), 600, 0)                        # (M = 0: the single category)
        self.assertTrue(np.all(lo == -math.inf) and np.all(hi == math.inf))

    def test_T4_2_capped_marginal_mle_near_the_ceiling(self):
        """The capped marginal MLE recovers sigma on near-ceiling synthetic cells (s = 0.35, 64 replicates, mu in
        [0.30, 0.405] of c = 0.4117, v5 2.4's prototype setting; median within 10%, and within 15% for mu > 0.39); the
        old map on the same data is biased low by more than 25% where the cap binds (mu > 0.39)."""
        rng = np.random.default_rng(42)
        mu = rng.uniform(0.30, 0.405, 300)
        a = ol.solve_location(mu, 0.35, 600, 247)[0]
        K = ol.rounded_count(a[:, None], 0.35, rng.standard_normal((300, 64)), 600, 247).astype(float)
        near = mu > 0.39
        self.assertGreater(float(np.mean(K[near] == 247)), 0.5)                 # (the cap binds there)
        new, old = nb.fit_marginals(K, 600, 247), nb.fit_marginals(K, 600)
        self.assertGreater(int(new["ok"].sum()), 250)
        self.assertGreater(int((new["ok"] & near).sum()), 10)
        s_all = float(np.median(new["sigma"][new["ok"]]))
        s_near = float(np.median(new["sigma"][new["ok"] & near]))
        s_old = float(np.median(old["sigma"][old["ok"] & near]))
        self.assertLess(abs(s_all / 0.35 - 1), 0.10, s_all)
        self.assertLess(abs(s_near / 0.35 - 1), 0.15, s_near)
        self.assertLess(s_old, 0.75 * 0.35, s_old)
        with self.assertRaises(nb.NoiseBankError):
            nb.fit_marginals(K + 1, 600, 247)

    def test_T2_3_the_bank_code_derives_no_age_arithmetic(self):
        """v5 1.3 / T2-3, for the bank code: the ceilings come from #90's clock through material.cohort_ceiling (once);
        noisebank's CODE (comments and strings blanked) has no age arithmetic of its own."""
        import tokenize
        src = rqlib.read_text(os.path.join(HERE, "noisebank.py"))
        drop = {tokenize.COMMENT, tokenize.STRING} | {getattr(tokenize, n) for n in ("FSTRING_MIDDLE", "TSTRING_MIDDLE")
                                                      if hasattr(tokenize, n)}
        starts = [0]
        for line in src.splitlines(keepends=True):
            starts.append(starts[-1] + len(line))
        chars = list(src)
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in drop:
                for i in range(starts[tok.start[0] - 1] + tok.start[1], starts[tok.end[0] - 1] + tok.end[1]):
                    if chars[i] != "\n":
                        chars[i] = " "
        code = "".join(chars)
        self.assertEqual(len(re.findall(r"material\.cohort_ceiling\(", code)), 1)
        for pat in (r"\bcommon\.", r"age_feasible", r"age_death_frame", r"binary32\(", r"_CLOCKS",
                    r"\bages\b.*\*\s*(DT|0\.016)", r"max_age\s*[-+*/<>]", r"^\s*(import|from)\s+common\b"):
            self.assertIsNone(re.search(pat, code, re.M), pat)

    def test_arrays_thread_the_ceilings(self):
        """arrays(obs, h, ceilings): A["M"] = {C: B, S: M_h, F: M_h} and the survivors' range is 0..M_h (a violation
        refused with its count only); without ceilings M = N (the legacy map)."""
        obs = capped_obs(3, horizons=(5000, 10000))
        A = nb.arrays(obs, 5000, CEIL)
        self.assertEqual(A["M"], {"C": 324, "S": 247, "F": 247})
        self.assertEqual(nb.arrays(obs, 10000, CEIL)["M"], {"C": 642, "S": 0, "F": 0})
        self.assertEqual(nb.arrays(obs, 5000)["M"], {"C": 324, "S": 600, "F": 600})
        bad = copy.deepcopy(obs)
        frees = [o for o in bad if o["pred"] is None]
        frees[0]["horizons"]["5000"]["survivors"] = 248
        frees[1]["horizons"]["5000"]["survivors"] = 300
        with self.assertRaisesRegex(nb.NoiseBankError, r"^2 free survivors observation\(s\) above the survivor "
                                                       r"ceiling M = 247 at 5000 steps") as cm:
            nb.arrays(bad, 5000, CEIL)
        self.assertNotIn("248", str(cm.exception))
        self.assertNotIn("300", str(cm.exception))
        nb.arrays(bad, 5000)                                                    # (legacy: up to 600)

    def test_T4_7_the_D8_minimum_categories_screen(self):
        """PC-18 / R10: in the D8 path an all-247 cell, a {246, 247} cell and a separated two-category capture cell
        (counts 100 and 200: its interval-normal MLE exists, it is excluded BY POLICY) are excluded as unidentified
        and counted (screened <= unidentified); a three-category near-ceiling cell is fitted. Without the screen
        (the legacy path) the same cells reach the Newton fit and no "screened" key exists."""
        obs = capped_obs(5)
        cells = sorted({(tuple(o["prey"]), tuple(o["pred"])) for o in obs if o["pred"] is not None})
        pat = {cells[0]: ("S", [247] * 16), cells[1]: ("S", [246, 247] * 8), cells[2]: ("C", [100, 200] * 8),
               cells[3]: ("S", ([238, 243, 247] * 6)[:16]), cells[4]: ("S", [245, 246, 247, 247] * 4)}
        for o in obs:
            k = (tuple(o["prey"]), None if o["pred"] is None else tuple(o["pred"]))
            if k in pat:
                ch, vals = pat[k]
                o["horizons"]["5000"]["captures" if ch == "C" else "survivors"] = vals[o["replicate"]]
        A = nb.arrays(obs, 5000, CEIL)
        idx = {c: i for i, c in enumerate((tuple(A["prey"][i]), tuple(A["pred"][j])) for i, j in zip(A["I"], A["J"]))}
        U = nb.usable(A, screen=True)
        L = nb.usable(A)
        for ch in "CSF":
            self.assertIn("screened", U[ch]["counts"])
            self.assertLessEqual(U[ch]["counts"]["screened"], U[ch]["counts"]["unidentified"])
            self.assertNotIn("screened", L[ch]["counts"])
            self.assertEqual(U[ch]["counts"]["rows"], sum(U[ch]["counts"][k] for k in
                                                          ("incomplete", "saturated", "unidentified", "usable")))
        self.assertEqual((U["S"]["counts"]["screened"], U["C"]["counts"]["screened"]), (2, 1))
        for c, ch in ((cells[0], "S"), (cells[1], "S"), (cells[2], "C")):
            self.assertFalse(U[ch]["ok"][idx[c]], c)
            self.assertTrue(np.isnan(U[ch]["sigma"][idx[c]]), "a screened cell never reaches the Newton fit")
        self.assertTrue(U["S"]["ok"][idx[cells[3]]], "three categories near the ceiling: fitted")
        row3 = A["S"][idx[cells[3]]][None, :]                   # (fitted at the ceiling: the capped map, 2.5 item 3)
        self.assertEqual(float(U["S"]["sigma"][idx[cells[3]]]), float(nb.fit_marginals(row3, 600, 247)["sigma"][0]))
        self.assertNotEqual(float(U["S"]["sigma"][idx[cells[3]]]), float(nb.fit_marginals(row3, 600)["sigma"][0]))
        rows = np.array([idx[cells[3]]])
        lo, hi = nb._std_bounds(A, U, "S", rows)                # (the standardized bounds of stage 2: +inf at 247)
        self.assertTrue(np.all(np.isinf(hi[A["S"][rows] == 247])) and np.all(np.isfinite(hi[A["S"][rows] < 247])))
        row = A["S"][idx[cells[4]]][None, :]                    # (three categories, barely informative: the screen
        self.assertFalse(np.isnan(U["S"]["sigma"][idx[cells[4]]]))   # passes it; the identification rules decide)
        self.assertEqual(bool(U["S"]["ok"][idx[cells[4]]]), bool(nb.fit_marginals(row, 600, 247)["ok"][0]))
        f = nb.fit_marginals(np.array([[100, 200] * 8], float), 324)
        self.assertTrue(f["ok"][0] and 0.5 < f["sigma"][0] < 3, "the separated two-category MLE exists")
        self.assertTrue(L["C"]["ok"][idx[cells[2]]], "legacy: the two-category capture cell is fitted (no screen)")
        self.assertFalse(np.isnan(L["S"]["sigma"][idx[cells[0]]]), "legacy: the all-247 cell reaches the Newton fit")
        rec = nb.horizon_estimate(A, boot=1, m=M)
        self.assertNotIn("screened", json.dumps(rec), "the legacy record carries no screen count")


_T43_WORKER = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import noisebank as nb
import test_noisebank as tn
out = {}
for s in json.loads(sys.argv[2]):
    rec = nb.horizon_estimate_d8(nb.arrays(tn.capped_obs(s), 5000, tn.CEIL), 5000, boot=1, m=tn.M)
    out[s] = {"status": rec["status"], "reasons": rec["reasons"],
              "rho": {g: rec["groups"][g]["rho_max"] for g in nb.GROUPS} if rec["status"] == "ok" else None}
print(json.dumps(out))
'''


def t43_fits(seeds):
    """T4-3's bank fits (capped_obs(seed), the D8 5k fit, boot 1, the test grid) in RQ_TEST_WORKERS (default: up to 4,
    the CPUs) plain subprocesses -> {seed: {status, reasons, rho: {group: rho_max}}}."""
    import subprocess
    seeds = list(seeds)
    n = max(1, min(len(seeds), int(os.environ.get("RQ_TEST_WORKERS") or min(4, os.cpu_count() or 1))))
    procs = [subprocess.Popen([sys.executable, "-I", "-c", _T43_WORKER, HERE, json.dumps(seeds[k::n])],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for k in range(n)]
    out = {}
    for p in procs:
        so, se = p.communicate()
        if p.returncode:
            raise AssertionError(f"T4-3 worker failed: {se[-3000:]}")
        out.update({int(k): v for k, v in json.loads(so).items()})
    return out


@unittest.skipIf(np is None, "numpy is not installed")
class TestD8Horizons(unittest.TestCase):
    """T4-3 (population recovery under capping), T4-4 (the zero-ceiling capture-only fit), the D8 bootstrap streams."""

    def test_T4_3_population_parameter_recovery(self):
        """20 small synthetic banks (4 worlds x 2 times, R = 16) under the capped law from known components: every 5k
        D8 fit ok, and each group's mean maximum within 3 sd / sqrt(20) + 0.03 of its true correlation (0.03: v5's
        allowance for the fixed-R IFM bias at R = 16). Plus the independent capped-likelihood check: log_rect against
        the independent Simpson reference on exactly 200 admissible random rectangles built from the capped interval
        map (half-infinite capped categories included; drawn until 200 have been checked) within 1e-8. (The capped
        categories make log_rect take its restricted half-infinite path often, about a minute per bank: the 20 banks
        are fitted in RQ_TEST_WORKERS plain subprocesses.)"""
        rng = np.random.default_rng(8)
        worst, capped, n, tries = 0.0, 0, 0, 0

        def count(Mx):                          # (a third the capped category, a third near it, a third anywhere)
            u = rng.random()
            if u < 0.35:
                return Mx
            return int(rng.integers(max(0, Mx - 6), Mx)) if u < 0.7 else int(rng.integers(0, Mx + 1))
        while n < 200:                          # (sampled until exactly 200 admissible rectangles are checked)
            tries += 1
            self.assertLess(tries, 2000, f"only {n} admissible rectangles in {tries} draws")
            N, Mx = (600, 247) if rng.random() < 0.7 else (324, 324)
            k1, k2 = count(Mx), count(Mx)
            (l1,), (h1,) = nb.interval_bounds(np.array([k1]), N, Mx)
            (l2,), (h2,) = nb.interval_bounds(np.array([k2]), N, Mx)
            a1, a2 = rng.normal(np.log(Mx / (N - Mx + 1)) - 0.3, 0.3, 2)
            s1, s2 = rng.uniform(0.25, 0.6, 2)
            box = [(l1 - a1) / s1, (h1 - a1) / s1, (l2 - a2) / s2, (h2 - a2) / s2]
            if any(abs(v) > nb.E_MAX for v in box if math.isfinite(v)) or box[1] - box[0] < nb.W_MIN or \
                    box[3] - box[2] < nb.W_MIN:
                continue
            capped += (h1 == math.inf and N == 600) or (h2 == math.inf and N == 600)
            n += 1
            r = float(rng.uniform(-0.9, 0.9))
            got = float(nb.log_rect(*[np.array([v]) for v in box], r)[0])
            worst = max(worst, abs(got - _ref_log_rect(*box, r)))
        self.assertEqual(n, 200)
        self.assertGreater(capped, 40)
        self.assertLessEqual(worst, nb.LOG_RECT_TOL)
        recs = t43_fits(range(1000, 1020))
        est = {g: [] for g in nb.GROUPS}
        for k, rec in recs.items():
            self.assertEqual(rec["status"], "ok", (k, rec["reasons"]))
            for g in nb.GROUPS:
                est[g].append(rec["rho"][g])
        self.assertEqual(len(recs), 20)
        for g in nb.GROUPS:
            x = np.array(est[g])
            tol = 3 * float(x.std(ddof=1)) / math.sqrt(20) + 0.03
            print(f"T4-3 {g}: mean {float(x.mean()):.4f} true {GROUP_TRUTH[g]:.4f} sd {float(x.std(ddof=1)):.4f} "
                  f"tolerance {tol:.4f}", file=sys.stderr)
            self.assertLessEqual(abs(float(x.mean()) - GROUP_TRUTH[g]), tol, (g, float(x.mean()), tol))

    def test_T4_4_zero_ceiling_capture_only_fit(self):
        """M = 0 (10k): S and F are the structural-zero declarations, the capture-only fit is ok with no survival
        parameter anywhere; its components ARE the group maxima (C4.2) and the record is what obslaw's strict loader
        admits at a zero-ceiling horizon (C4.1, C7, C8)."""
        obs = capped_obs(11, W=4, T=2, R=24, horizons=(5000, 10000))
        rec = nb.horizon_estimate_d8(nb.arrays(obs, 10000, CEIL), 10000, boot=999, m=M)
        self.assertEqual(rec["status"], "ok", rec["reasons"])
        for ch in "SF":
            self.assertEqual(rec["channels"][ch], {"status": "structural_zero", "M_H": 0, "reason":
                                                   "D8 rule 46: no age-feasible initial individual at this horizon"})
        self.assertEqual(survival_paths(dict(rec, channels={"C": rec["channels"]["C"]})), [])
        self.assertEqual(sorted(rec["groups"]), ["D_CC", "R_CC"])
        rR, rD = rec["groups"]["R_CC"]["rho_max"], rec["groups"]["D_CC"]["rho_max"]
        c = rec["components"]
        self.assertEqual((c["SigmaR"], c["SigmaD"], c["SigmaE"], c["fit"]), ([[rR]], [[rD]], [[1.0 - rR - rD]],
                                                                             "unconstrained"))
        self.assertEqual(rec["bootstrap"]["draws"], 999)
        if rec["bootstrap"]["status"] == "ok":
            self.assertEqual(sorted(rec["bootstrap"]["ci95"]), ["D_CC", "E_CC", "R_CC"])
        self.assertIn("screened", rec["channels"]["C"])
        for g, want in (("R_CC", 0.25), ("D_CC", 0.25)):
            self.assertLess(abs(rec["groups"][g]["rho_max"] - want), 0.2)
        ol.BankArtifact._horizon_record(rec, "10000", "horizons.10000", zero=True)

    def test_T4_4_infeasible_maxima_and_refused_draws(self):
        """Infeasible capture-only maxima: status unavailable with the groups kept as diagnostics (C4.2), never a
        barrier fit; in the bootstrap an infeasible reduced fit is a refused fit, i.e. a failed draw."""
        obs = capped_obs(11, W=4, T=2, R=24, horizons=(5000, 10000))
        A = nb.arrays(obs, 10000, CEIL)

        def peaked(zn, at):                     # (an objective whose maximum is at rho = at)
            return zn, -50.0 * (np.tanh(zn) - at) ** 2
        for bad in ({"R_CC": -0.2, "D_CC": 0.3}, {"R_CC": 0.3, "D_CC": -0.05}, {"R_CC": 0.6, "D_CC": 0.5}):
            objs = {g: peaked(nb.z_nodes(M), bad[g]) for g in ("R_CC", "D_CC")}
            with self.subTest(objective=bad), self.assertRaisesRegex(nb.NoiseBankError, "infeasible"):
                nb.capture_only_fit(objs)
        ok = nb.capture_only_fit({g: peaked(nb.z_nodes(M), v) for g, v in (("R_CC", 0.2), ("D_CC", 0.3))})
        self.assertEqual(ok["SigmaE"], [[1.0 - ok["SigmaR"][0][0] - ok["SigmaD"][0][0]]])
        self.assertLess(abs(ok["SigmaR"][0][0] - 0.2) + abs(ok["SigmaD"][0][0] - 0.3), 1e-3)   # (spline maxima)
        real = nb.capture_only_fit
        for bad in ({"R_CC": -0.1, "D_CC": 0.3}, {"R_CC": 0.7, "D_CC": 0.4}):
            def shifted(objs, pairs=None, _b=bad):          # (the real rule on objectives peaked where _b says)
                return real({g: peaked(objs[g][0], _b[g]) for g in objs})
            with self.subTest(point_estimate=bad), mock.patch.object(nb, "capture_only_fit", shifted):
                rec = nb.horizon_capture_only(A, boot=3, m=M)
                self.assertEqual(rec["status"], "unavailable")
                self.assertIn("infeasible", rec["reasons"][0])
                self.assertIsNone(rec["components"])
                self.assertEqual(sorted(rec["groups"]), ["D_CC", "R_CC"])
                self.assertTrue(all("nodes" not in g for g in rec["groups"].values()))
                ol.BankArtifact._horizon_record(rec, "10000", "horizons.10000", zero=True)
        tab_obs = nb.arrays(obs, 10000, CEIL)
        U = nb.usable(tab_obs, screen=True, channels=("C",))
        Uc = dict(U, S={"ok": np.zeros(len(tab_obs["S"]), bool)}, F={"ok": np.zeros(len(tab_obs["F"]), bool)})
        G, worlds = nb.group_pairs(tab_obs, Uc)
        tab = nb.group_tables(tab_obs, Uc, G, M, ("R_CC", "D_CC"))

        def refuse(objs, pairs=None):
            raise nb.NoiseBankError("the capture-only group maxima are infeasible")
        D, failed, unident = nb.bootstrap(tab, len(worlds), 6, 0, draws=nb.d8_draws("AnnexH/D8/1/test/x")(len(worlds)),
                                          groups=("R_CC", "D_CC"), fit=refuse, entries=nb._capture_entries,
                                          names=("R_CC", "D_CC", "E_CC"))
        self.assertEqual((len(D), failed), (0, 6))

    def test_D8_bootstrap_draws_are_the_registered_splitmix_streams(self):
        """v5 2.5 item 5 (PC-9): per draw n_worlds below(n_worlds) for the prey role, then n_worlds for the predator
        role, from rqlib.SplitMix64 seeded by the horizon's AnnexH/D8/1 text (an independent SplitMix64 here)."""
        text = "AnnexH/D8/1/noisebank/D8-refit/h10000/bootstrap"
        draw = nb.d8_draws(text)(8)
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little")
        ref = rqlib.SplitMix64(seed)
        for _ in range(5):
            mm, mp = draw()
            want_m = np.bincount([ref.below(8) for _ in range(8)], minlength=8)
            want_p = np.bincount([ref.below(8) for _ in range(8)], minlength=8)
            self.assertEqual((mm.tolist(), mp.tolist()), (want_m.tolist(), want_p.tolist()))
        rec = nb.d8_streams()
        self.assertEqual(rec["texts"], [f"AnnexH/D8/1/noisebank/D8-refit/h{h}/bootstrap" for h in (5000, 10000, 20000)])
        self.assertEqual(rec["seeds"][1], seed)
        g = rqlib.SplitMix64(seed)
        self.assertEqual(rec["first_outputs"][1], [g.next64(), g.next64()])
        with mock.patch.object(nb, "d8_draws", wraps=nb.d8_draws) as spy:
            nb.horizon_estimate_d8(nb.arrays(capped_obs(2), 5000, CEIL), 5000, boot=2, m=M)
        spy.assert_called_once_with("AnnexH/D8/1/noisebank/D8-refit/h5000/bootstrap")


def _hashed_rows(design, ages_sha):
    rows, _, _ = plan.expand_v2(design, pending=True)
    for r in rows:
        for k in nb.HASHED:
            if isinstance(r.get(k), dict) and r[k].get("path"):
                r[k]["sha256"] = ages_sha if k == "ages" else rqlib.sha256_bytes(f"{k}|{r[k]['path']}".encode())
    return rows


def _write_store(root, bundles, per_chunk=64):
    """A synthetic packed store (store.py's layout): chunks of bundle.json + done.json members and their index."""
    import store
    import zipfile
    os.makedirs(os.path.join(root, store.CHUNKS))
    ids = sorted(bundles)
    lines = []
    for n, k in enumerate(range(0, len(ids), per_chunk), 1):
        name = f"chunk_{n:06d}.zip"
        path = os.path.join(root, store.CHUNKS, name)
        cells = {}
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for cid in ids[k:k + per_chunk]:
                data = rqlib.canonical(bundles[cid])
                done = rqlib.canonical({"bundle_sha256": rqlib.sha256_bytes(data)})
                z.writestr(f"{cid}/bundle.json", data)
                z.writestr(f"{cid}/done.json", done)
                cells[cid] = {"bundle_sha256": rqlib.sha256_bytes(data), "done_sha256": rqlib.sha256_bytes(done)}
        lines.append(rqlib.canonical({"schema": store.CHUNK_SCHEMA, "chunk": name, "sha256": rqlib.sha256_file(path),
                                      "bytes": os.path.getsize(path), "cells": cells}))
    with open(os.path.join(root, store.INDEX), "wb") as f:
        f.write(b"".join(lines))


ENGINE = rqlib.sha256_bytes(b"synthetic engine")


class D8World:
    """A synthetic bank world in a temporary directory: a design (the registered planner, a synthetic validation
    registry), its hashed plan (ages: the registered fixture's bytes), synthetic bundles packed in a store, the
    observations collected from it, and TEST bindings. small: a reduced design (a few edges, 2 replicates) for the
    provenance tests; otherwise the registered 18,432-cell allocation with only a few usable cells (the rest
    saturated at 0), cheap to fit."""

    def __init__(self, tmp, small=False, seed=7):
        self.tmp = tmp
        root = os.path.join(tmp, "validation")
        f = files(tmp)
        self.ages = os.path.join(tmp, "ages.json")
        shutil.copyfile(AGES_FIXTURE, self.ages)
        d = nb.make_design(block(root), [f["t.json"]], self.ages, [f["prod.json"]], validation_dir=root, arena="a",
                           main_registries=[f["main"]])
        if small:
            d["edges"] = [e for e in d["edges"] if e["prey"]["world"] == d["noisebank"]["worlds"][0]][:6]
            d["replicates"] = 2
        self.design_doc = d
        self.design = os.path.join(tmp, "design.json")
        rqlib.write_json_durable(self.design, d)
        self.rows = _hashed_rows(d, material.AGES_SHA256)
        self.plan = os.path.join(tmp, "plan.jsonl")
        plan.write_plan(self.rows, self.plan)
        w = d["noisebank"]["worlds"][0]
        P = [(w, "20M"), (w, "40M")]
        self.keep = {(p, q) for p in P for q in P}
        self.counts = self._counts(seed)
        self.bundles = {r["id"]: self.bundle(r) for r in self.rows}
        self.root = os.path.realpath(os.path.join(tmp, "bank"))
        _write_store(self.root, self.bundles, per_chunk=4 if small else 64)
        self.obs = os.path.join(tmp, "obs.json")
        rqlib.write_json_durable(self.obs, nb.collect(self.root, d, self.plan))
        self.ledger = os.path.join(tmp, "ledger.jsonl")
        with open(self.ledger, "x"):           # (an empty test ledger, created explicitly: no D8 command creates one)
            pass
        self.bindings = self.bind()

    def _counts(self, seed):
        """(prey, pred or None, replicate) -> {h: (captures, survivors)}: obslaw's capped law on the kept cells."""
        rng = np.random.default_rng(seed)
        R = self.design_doc["replicates"]
        out = {}
        cells = sorted(self.keep)
        prey = sorted({p for p, _ in cells})
        pred = sorted({q for _, q in cells})
        qi = np.array([prey.index(p) for p, _ in cells])
        pj = np.array([pred.index(q) for _, q in cells])
        fac = ol.psd_factors(*val_components())
        for h in nb.HORIZONS:
            M, B = CEIL[str(h)], nb.capture_bound(h)
            lat = ol.latent(ol.standard_normals(rng, len(prey), len(pred), len(cells), R), fac, qi, pj)
            muC = np.full(len(cells), 0.3)
            muS, muF = np.full(len(cells), 0.75 * M / 600), np.full(len(prey), 0.92 * M / 600)
            KC = capped_counts(muC, lat["C"], B, B, VAL_CURVES["C"])
            KS = capped_counts(muS, lat["S"], 600, M, VAL_CURVES["S"])
            KF = capped_counts(muF, lat["F"], 600, M, VAL_CURVES["F"])
            for e, (p, q) in enumerate(cells):
                for r in range(R):
                    out.setdefault((p, q, r), {})[h] = (int(KC[e, r]), int(KS[e, r]))
            for i, p in enumerate(prey):
                for r in range(R):
                    out.setdefault((p, None, r), {})[h] = (None, int(KF[i, r]))
        return out

    def bundle(self, row, engine=ENGINE):
        p = (row["prey"]["world"], row["prey"]["time"])
        q = None if row["predators"] is None else (row["predators"]["world"], row["predators"]["time"])
        got = self.counts.get((p, q, row["replicate"]), {})
        hz = [{"steps": h, "captures": got.get(h, (None if q is None else 0, 0))[0],
               "survivors": got.get(h, (0, 0))[1]} for h in nb.HORIZONS]
        return {"cell": row, "score": {"n_start": 600, "horizons": hz}, "binary_sha256": engine,
                "tools_sha256": {"run.py": rqlib.sha256_bytes(b"run"), "cell.py": rqlib.sha256_bytes(b"cell")}}

    def bind(self, **over):
        b = {"observations_sha256": rqlib.sha256_file(self.obs), "plan_sha256": rqlib.sha256_file(self.plan),
             "design_file_sha256": rqlib.sha256_file(self.design), "ages_sha256": material.AGES_SHA256,
             "bank_root": self.root}
        b.update(over)
        return b

    def path(self, name):
        return os.path.join(self.tmp, name)


def _walk(node, path=()):
    """Every (path, value) below node: dict keys and the first element of each list."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield path + (k,), v
            yield from _walk(v, path + (k,))
    elif isinstance(node, list) and node:
        yield path + (0,), node[0]
        yield from _walk(node[0], path + (0,))


def _edit(doc, path, value=None, delete=False):
    d = copy.deepcopy(doc)
    x = d
    for k in path[:-1]:
        x = x[k]
    if delete:
        del x[path[-1]]
    else:
        x[path[-1]] = value
    return d


@unittest.skipIf(np is None, "numpy is not installed")
class TestD8Refit(unittest.TestCase):
    """The registered-size synthetic world through provenance and estimate-d8 (receipt, ledger) into obslaw's strict
    loader (the round trip); T5-1 (every binding of v5 2.1), T4-5 (support), R4 (ceilings), R7, D3's nu0 domain."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.w = D8World(cls.tmp)
        w = cls.w
        cls.prov = w.path("prov.json")
        nb.run_provenance(w.root, w.design, w.plan, w.obs, None, cls.prov, w.ledger, bindings=w.bindings)
        cls.val = w.path("val.json")
        rqlib.write_json_durable(cls.val, {"schema": nb.D8_REPORT_SCHEMA, "synthetic_banks": True, "test": True})
        cls.out, cls.receipt = w.path("bank3.json"), w.path("receipt.json")
        cls.art = nb.run_estimate_d8(w.obs, w.ages, w.design, w.plan, cls.prov, cls.val, cls.out, cls.receipt, w.ledger,
                                     ["estimate-d8", "(test)"], bindings=w.bindings)
        cls.inputs = {k: cls.art["inputs"][k] for k in ol.REGISTERED_INPUTS}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def load(self, doc=None):
        """obslaw's strict loader with this world's four input hashes as the registered ones (test bindings)."""
        path = self.out
        if doc is not None:
            path = os.path.join(self.tmp, "variant.json")
            rqlib.write_json_durable(path, doc)
        with mock.patch.dict(ol.REGISTERED_INPUTS, self.inputs):
            return ol.BankArtifact(path, sha256=rqlib.sha256_file(path), allow_synthetic=True)

    def refit(self, **over):
        w = self.w
        kw = dict(obs_path=w.obs, ages_path=w.ages, design_path=w.design, plan_path=w.plan,
                  provenance_path=self.prov, validation_path=self.val, bindings=w.bindings, boot=1)
        kw.update(over)
        return nb.estimate_d8(**kw)

    def test_round_trip_the_strict_loader_accepts_what_estimate_d8_writes(self):
        """What estimate-d8 writes on the synthetic store, obslaw's strict loader (v5 4.2, clarification 1) accepts:
        bank/3, synthetic (test bindings), no estimator.seed (C1), C2's streams, C5's rule, C4's declarations and
        C7's screen counts; noise and map_variance built from the 5k record (C9)."""
        bank = self.load()
        a = self.art
        self.assertEqual((a["schema"], a["status"], a["synthetic"]), ("finfolk.redqueen.noisebank.bank/3",
                                                                      "d8-fitted", True))
        self.assertNotIn("engine_sha256", a)
        self.assertEqual(a["fit"]["noise"]["engine_sha256"], ENGINE)
        self.assertNotIn("seed", a["estimator"])
        self.assertEqual(a["estimator"]["boot"], 999)
        self.assertEqual(a["map_variance"]["rule"], ol.MAP_VARIANCE_RULE)
        self.assertEqual(a["fit"]["streams"]["bootstrap"]["texts"],
                         [f"AnnexH/D8/1/noisebank/D8-refit/h{h}/bootstrap" for h in (5000, 10000, 20000)])
        for h in ("10000", "20000"):
            for ch in "SF":
                self.assertEqual(a["horizons"][h]["channels"][ch]["status"], "structural_zero")
            self.assertEqual(survival_paths(dict(a["horizons"][h], channels={})), [])
        for ch in "CSF":
            self.assertIn("screened", a["horizons"]["5000"]["channels"][ch])
        self.assertEqual(a["map_variance"]["nu0"], a["horizons"]["5000"]["nu0"])
        self.assertEqual(bank.M_H, 247)
        self.assertEqual(a["inputs"]["provenance_sha256"], rqlib.sha256_file(self.prov))
        self.assertEqual(a["fit"]["noise"]["inputs_sha256"], rqlib.canonical_sha(a["inputs"]))
        self.assertEqual(a["fit"]["noise"]["implementation_sha256"], rqlib.canonical_sha(
            {f: rqlib.sha256_file(os.path.join(HERE, f)) for f in
             ("noisebank.py", "noisescale.py", "obslaw.py", "common.py", "material.py", "plan.py", "store.py",
              "rqlib.py", "fixtures/registered_ages.json")}))
        with self.assertRaisesRegex(ol.ObsLawError, "synthetic: true is refused"):
            with mock.patch.dict(ol.REGISTERED_INPUTS, self.inputs):
                ol.BankArtifact(self.out)

    def test_round_trip_every_single_field_corruption_is_refused(self):
        """Each single-field corruption of the written artifact is refused by the loader: every key deleted at every
        level, and every scalar (and each list's first element) replaced by null."""
        doc = rqlib.read_json(self.out)
        self.load(doc)
        admitted = {("deleted", ("horizons", h, "groups")) for h, r in doc["horizons"].items()   # (C4.1: both
                    if r["status"] == "unavailable" and "groups" in r}                       # unavailable shapes)
        accepted = []
        n = 0
        for path, v in list(_walk(doc)):
            variants = [("null", _edit(doc, path, None))] if v is not None and not isinstance(v, (dict, list)) else []
            if isinstance(path[-1], str):
                variants.append(("deleted", _edit(doc, path, delete=True)))
            for how, d in variants:
                if (how, path) in admitted:
                    continue
                n += 1
                try:
                    self.load(d)
                except ol.ObsLawError:
                    continue
                accepted.append((how, path))
        self.assertGreater(n, 500)
        self.assertEqual(accepted, [], f"{len(accepted)} of {n} corruptions accepted")

    def test_receipt_written_first_and_bound_and_the_ledger_charged(self):
        """v5 2.8 L755-757, 2.11: the receipt (command line, tool and input hashes, Python / NumPy, host, UTC, CPU
        seconds, the ledger entry) is written durably BEFORE the artifact, which binds its sha256; the run is charged
        to the D5 ledger once (calib.ledger_add's line format) with its attempt id, each run's attempt is closed with
        its steps recorded (Codex revWP3 P2-2), and a failed run is charged too."""
        rc = rqlib.read_json(self.receipt)
        self.assertEqual(self.art["fit"]["noise"]["receipt_sha256"], rqlib.sha256_file(self.receipt))
        self.assertEqual(rc["schema"], "finfolk.redqueen.noisebank.d8refitreceipt/1")
        self.assertEqual(rc["inputs"], self.art["inputs"])
        self.assertEqual(rc["implementation_sha256"], self.art["fit"]["noise"]["implementation_sha256"])
        for k in ("command", "tools", "python", "numpy", "host", "utc_start", "utc_end", "cpu_s", "ledger_entry"):
            self.assertIn(k, rc)
        led = [json.loads(x) for x in rqlib.read_text(self.w.ledger).splitlines()]
        kinds = [e["kind"] for e in led]
        self.assertEqual(kinds.count("D8-noisebank-refit"), 1)
        self.assertEqual(kinds.count("D8-noisebank-provenance"), 1)
        e = led[kinds.index("D8-noisebank-refit")]
        self.assertEqual({k: v for k, v in e.items() if k != "utc"}, rc["ledger_entry"])
        self.assertEqual(json.dumps(e, sort_keys=True), rqlib.read_text(self.w.ledger).splitlines()[kinds.index(
            "D8-noisebank-refit")])
        self.assertGreater(e["cpu_s"], 0)
        st = nb.attempts_state(self.w.ledger)
        self.assertEqual(sorted(a["open"]["kind"] for a in st.values()), ["D8-noisebank-provenance",
                                                                           "D8-noisebank-refit"])
        a = st[e["attempt"]]
        self.assertEqual((a["open"]["kind"], a["close"]["status"], a["close"]["cpu_s"]), ("D8-noisebank-refit", "ok",
                                                                                         e["cpu_s"]))
        self.assertEqual(a["steps"], ["estimate-d8: inputs verified"] + [f"estimate-d8: horizon {h}"
                                                                        for h in nb.HORIZONS])
        order = []
        real = rqlib.write_json_durable
        tmp = tempfile.mkdtemp()
        try:
            led2 = os.path.join(tmp, "ledger.jsonl")
            with open(led2, "x"):
                pass
            with mock.patch.object(rqlib, "write_json_durable", lambda p, o: (order.append(os.path.basename(p)),
                                                                             real(p, o))):
                w = self.w
                nb.run_estimate_d8(w.obs, w.ages, w.design, w.plan, self.prov, self.val, os.path.join(tmp, "a.json"),
                                   os.path.join(tmp, "r.json"), led2, ["x"], bindings=w.bindings, boot=1)
            self.assertEqual(order, ["r.json", "a.json"])
            with self.assertRaises(nb.NoiseBankError):
                nb.run_estimate_d8(w.obs, w.ages, w.design, w.plan, self.prov, self.val, os.path.join(tmp, "b.json"),
                                   os.path.join(tmp, "s.json"), led2, ["x"],
                                   bindings=w.bind(plan_sha256="0" * 64), boot=1)
            self.assertFalse(os.path.exists(os.path.join(tmp, "s.json")))
            led = [json.loads(x) for x in rqlib.read_text(led2).splitlines()]
            self.assertEqual([x["status"] for x in led], ["ok", "failed"])
        finally:
            shutil.rmtree(tmp)

    def test_T5_1_every_binding_of_2_1_is_refused(self):
        """estimate_d8 refuses each wrong binding of v5 2.1 (R1, the four file hashes BEFORE parsing; R5 the
        provenance receipt), the obs schema / missing / plan / design identities, the parsed ages, a plan row's ages
        hash, a missing allocation (R2) and an unmatched control."""
        w = self.w
        junk = w.path("junk.json")
        with open(junk, "wb") as f:
            f.write(b"not json at all")
        for key, arg in (("observations_sha256", "obs_path"), ("plan_sha256", "plan_path"),
                         ("design_file_sha256", "design_path"), ("ages_sha256", "ages_path")):
            with self.subTest(file=key), self.assertRaisesRegex(nb.NoiseBankError, "refused before parsing"):
                self.refit(**{arg: junk})
            with self.subTest(binding=key), self.assertRaisesRegex(nb.NoiseBankError, "is not the bound"):
                self.refit(bindings=w.bind(**{key: "0" * 64}))
        doc = rqlib.read_json(w.obs)

        def obs_variant(name, d):
            p = w.path(name)
            rqlib.write_json_durable(p, d)
            return {"obs_path": p, "bindings": w.bind(observations_sha256=rqlib.sha256_file(p))}
        cases = [
            ("schema", obs_variant("o1.json", dict(doc, schema="finfolk.redqueen.noisebank.obs/0")), "schema"),
            ("missing", obs_variant("o2.json", dict(doc, missing=["x"])), "complete bank"),
            ("plan_sha256", obs_variant("o3.json", dict(doc, plan_sha256="1" * 64)), "plan_sha256"),
            ("design_sha256", obs_variant("o4.json", dict(doc, design_sha256="2" * 64)), "design_sha256"),
        ]
        ages2 = w.path("ages2.json")
        rqlib.write_json_durable(ages2, dict(material.registered_ages(), max_age=121.0))
        cases.append(("ages content", {"ages_path": ages2, "bindings": w.bind(ages_sha256=rqlib.sha256_file(ages2))},
                      "registered_ages"))
        rows = copy.deepcopy(w.rows)
        rows[5]["ages"]["sha256"] = "3" * 64
        p2 = w.path("plan2.jsonl")
        plan.write_plan(rows, p2)
        d2 = dict(doc, plan_sha256=rqlib.sha256_file(p2))
        ov = obs_variant("o5.json", d2)
        cases.append(("plan row ages", dict(ov, plan_path=p2, bindings=dict(ov["bindings"],
                                                                             plan_sha256=rqlib.sha256_file(p2))),
                      "ages.sha256"))
        prov = rqlib.read_json(self.prov)
        for k, v in (("bank_root", "/elsewhere"), ("observations_sha256", "4" * 64), ("cells", 18431),
                     ("engine_sha256", "x"), ("schema", "finfolk.redqueen.noisebank.provenance/0"),
                     ("reconstruction", dict(prov["reconstruction"], equals_frozen=False))):
            p = w.path(f"prov_{k}.json")
            rqlib.write_json_durable(p, dict(prov, **{k: v}))
            cases.append((f"provenance {k}", {"provenance_path": p}, "provenance receipt"))
        pv = w.path("val0.json")
        rqlib.write_json_durable(pv, {"schema": "something else"})
        cases.append(("validation report", {"validation_path": pv}, "validation report"))
        lost = dict(doc, observations=doc["observations"][:-1])
        cases.append(("missing allocation", obs_variant("o6.json", lost), "incomplete registered bank allocation"))
        moved = copy.deepcopy(doc)
        ex = next(o for o in moved["observations"] if o["pred"] is not None)
        ex["replicate"] = 64
        cases.append(("unmatched control", obs_variant("o7.json", moved), "allocation"))
        for name, kw, msg in cases:
            with self.subTest(case=name), self.assertRaisesRegex(nb.NoiseBankError, msg):
                self.refit(**kw)
        obs = copy.deepcopy(doc["observations"])
        o = next(x for x in obs if x["pred"] is not None)
        same = [x for x in obs if x["prey"] == o["prey"]]                    # (this prey snapshot's observations)
        nb.d8_matched_controls(same)
        lost = sum(1 for x in same if x["pred"] is not None and x["replicate"] == o["replicate"])
        self.assertEqual(lost, 8)                                           # (its 8 predators at that replicate)
        same = [x for x in same if not (x["pred"] is None and x["replicate"] == o["replicate"])]
        with self.assertRaisesRegex(nb.NoiseBankError, f"^{lost} exposed observations have no matched free control"):
            nb.d8_matched_controls(same)

    def test_T4_5_support_violation_refuses_with_counts_only(self):
        """A survivor count 248 at 5k and 1 at 10k refuse the whole refit (R3); the refusal reports only the number
        of violating observations per horizon and channel."""
        doc = rqlib.read_json(self.w.obs)
        frees = [o for o in doc["observations"] if o["pred"] is None]
        ex = [o for o in doc["observations"] if o["pred"] is not None]
        frees[0]["horizons"]["5000"]["survivors"] = 248
        ex[0]["horizons"]["10000"]["survivors"] = 1
        ex[1]["horizons"]["20000"]["captures"] = 1285
        p = self.w.path("o_support.json")
        rqlib.write_json_durable(p, doc)
        with self.assertRaises(nb.NoiseBankError) as cm:
            self.refit(obs_path=p, bindings=self.w.bind(observations_sha256=rqlib.sha256_file(p)))
        msg = str(cm.exception)
        self.assertIn('{"10000": {"S": 1}, "20000": {"C": 1}, "5000": {"F": 1}}', msg)
        for v in ("248", "1285", frees[0]["cell"], ex[0]["cell"]):
            self.assertNotIn(v, msg)
        self.assertIn("the whole refit is refused", msg)

    def test_R4_ceilings_from_the_clock(self):
        """The ceilings come from #90's clock through material.cohort_ceiling and must be 247 / 0 / 0 (R4); a changed
        clock helper changes them and refuses."""
        self.assertEqual(nb.d8_ceilings(), {"5000": 247, "10000": 0, "20000": 0})
        with mock.patch.object(material, "cohort_ceiling", lambda ages, h, dt: 246 if h == 5000 else 0):
            with self.assertRaisesRegex(nb.NoiseBankError, "R4"):
                self.refit()
        import common
        with mock.patch.object(common, "age_feasible_count", lambda *a, **k: 3):
            with self.assertRaisesRegex(nb.NoiseBankError, "R4"):
                nb.d8_ceilings()

    def test_R7_unavailable_artifact_and_D3_nu0_domain(self):
        """R7: no 5k curve, or nu0_C unavailable, or a 5k fit not ok -> status unavailable and noise.available false,
        which the loader refuses. Clarification 2 D3: an estimated nu0 must be finite and > 0 to be emitted."""
        fit = {"inputs": self.art["inputs"], "horizons": copy.deepcopy(self.art["horizons"]), "engine_sha256": ENGINE,
               "ceilings": dict(CEIL), "boot": 999, "z_intervals": nb.Z_INTERVALS, "synthetic": True}
        for name, change in (("no S curve", lambda h: h["scales"].update(S=None)),
                             ("nu0 C unavailable",
                              lambda h: h["nu0"].update(C={"status": "unavailable", "reason": "x"})),
                             ("5k unavailable", lambda h: h.update(status="unavailable", reasons=["x"]))):
            f = copy.deepcopy(fit)
            change(f["horizons"]["5000"])
            art = nb.d8_artifact(f, "5" * 64)
            with self.subTest(case=name):
                self.assertEqual((art["status"], art["noise"]["available"]), ("unavailable", False))
                with self.assertRaisesRegex(ol.ObsLawError, "status 'unavailable'"):
                    self.load(art)
        for bad in (0.0, -1.0, -5e-324, math.inf, float("nan"), True, "1"):
            f = copy.deepcopy(fit)
            f["horizons"]["5000"]["nu0"]["C"] = {"status": "estimated", "nu0": bad, "excess_log_variance": 0.1,
                                                 "sampling_log_variance": 0.1, "cells": 4}
            with self.subTest(nu0=bad), self.assertRaisesRegex(nb.NoiseBankError, "D3"):
                nb.d8_artifact(f, "5" * 64)


@unittest.skipIf(np is None, "numpy is not installed")
class TestD8Provenance(unittest.TestCase):
    """T5-2 and T5-6 on a small synthetic store (v5 2.2): the binding by reconstruction and the store integrity
    checks, each refusal by its own cause."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.w = D8World(self.tmp, small=True)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def prov(self, **kw):
        w = self.w
        args = dict(study=w.root, design_path=w.design, plan_path=w.plan, obs_path=w.obs, manifest_path=None,
                    bindings=w.bindings)
        args.update(kw)
        return nb.provenance(**args)

    def rebuild(self, bundles):
        shutil.rmtree(self.w.root)
        _write_store(self.w.root, bundles, per_chunk=4)

    def test_T5_6_passes_on_an_intact_store_and_emits_no_score(self):
        rec = self.prov()
        self.assertEqual(rec["schema"], "finfolk.redqueen.noisebank.provenance/1")
        self.assertEqual(rec["reconstruction"]["equals_frozen"], True)
        self.assertEqual(rec["reconstruction"]["canonical_sha256"], rqlib.sha256_file(self.w.obs))
        self.assertEqual((rec["engine_sha256"], rec["cells"], rec["ages_sha256"]), (ENGINE, 12, material.AGES_SHA256))
        self.assertEqual(rec["store"], {"index_sha256": rqlib.sha256_file(os.path.join(self.w.root, "chunks",
                                                                                         "index.jsonl")),
                                        "chunks_verified_all": 3, "chunks_verified_members": 3})
        self.assertEqual(rec["manifest"], {"sha256": None, "covers_chunks": False, "chunks_checked": 0})
        text = json.dumps(rec)
        for k in ("score", "survivors", "captures", "horizons"):
            self.assertNotIn(f'"{k}"', text, "the receipt reports no score field")
        self.assertEqual(set(rec), {"schema", "bank_root", "observations_sha256", "store", "reconstruction",
                                    "plan_sha256", "design_sha256", "manifest", "cells", "engine_sha256",
                                    "tools_sha256", "ages_sha256"})

    def test_T5_2_two_engine_binaries_are_refused(self):
        b = dict(self.w.bundles)
        cid = sorted(b)[3]
        b[cid] = self.w.bundle(next(r for r in self.w.rows if r["id"] == cid), engine=rqlib.sha256_bytes(b"other"))
        self.rebuild(b)
        with self.assertRaisesRegex(nb.NoiseBankError, "2 engine binaries"):
            self.prov()

    def test_T5_2_a_wrong_ages_hash_is_refused(self):
        w = self.w
        rows = copy.deepcopy(w.rows)
        rows[0]["ages"]["sha256"] = "3" * 64
        plan.write_plan(rows, w.plan)
        self.rebuild({r["id"]: dict(w.bundle(r)) for r in rows})
        rqlib.write_json_durable(w.obs, nb.collect(w.root, w.design_doc, w.plan))
        with self.assertRaisesRegex(nb.NoiseBankError, "ages.sha256 is not the registered"):
            self.prov(bindings=w.bind())

    def test_T5_2_a_cell_set_mismatch_is_refused(self):
        w = self.w
        doc = rqlib.read_json(w.obs)
        doc["observations"][0]["cell"] = "someone-else"
        rqlib.write_json_durable(w.obs, doc)
        with self.assertRaisesRegex(nb.NoiseBankError, "stored cell set differs"):
            self.prov(bindings=w.bind())

    def test_T5_6_one_changed_score_breaks_the_reconstruction(self):
        b = copy.deepcopy(self.w.bundles)
        cid = sorted(b)[2]
        b[cid]["score"]["horizons"][0]["survivors"] += 1
        self.rebuild(b)
        with self.assertRaisesRegex(nb.NoiseBankError, "reconstruction's canonical sha256 .* is not the frozen"):
            self.prov()

    def test_T5_6_a_repacked_chunk_is_refused_by_the_index_alone(self):
        """A chunk repacked (deflated as pack() writes, at another level and in reverse member order) with every
        bundle.json member identical: store.verify_all(deep) reports its size / sha256 against the index, with no
        manifest."""
        import store
        import zipfile
        name = "chunk_000002.zip"
        p = os.path.join(self.w.root, store.CHUNKS, name)
        old = rqlib.sha256_file(p)
        with zipfile.ZipFile(p) as z:
            members = [(i.filename, z.read(i.filename)) for i in z.infolist()]
        with zipfile.ZipFile(p, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as z:
            for n, data in reversed(members):
                z.writestr(n, data)
        self.assertNotEqual(rqlib.sha256_file(p), old)
        _, cells = store.load_index(self.w.root)
        self.assertEqual([store.read_member(self.w.root, c, cells=cells) for c in sorted(cells)
                          if cells[c][0]["chunk"] == name],
                         [rqlib.canonical(self.w.bundles[c]) for c in sorted(cells) if cells[c][0]["chunk"] == name])
        with self.assertRaisesRegex(nb.NoiseBankError, r"verify_all\(deep=True\) reports 1 problem"):
            self.prov()

    def test_T5_6_an_extra_member_is_refused_by_verify_chunk(self):
        import store
        import zipfile
        name = "chunk_000001.zip"
        p = os.path.join(self.w.root, store.CHUNKS, name)
        with zipfile.ZipFile(p, "a", compression=zipfile.ZIP_DEFLATED) as z:     # (deflated, as pack() writes)
            z.writestr("intruder/bundle.json", b"{}")
        ip = os.path.join(self.w.root, store.INDEX)
        recs = [json.loads(x) for x in rqlib.read_text(ip).splitlines()]
        recs[0].update(sha256=rqlib.sha256_file(p), bytes=os.path.getsize(p))
        with open(ip, "wb") as f:
            f.write(b"".join(rqlib.canonical(r) for r in recs))
        self.assertEqual(store.verify_all(self.w.root, deep=True), [])
        with self.assertRaisesRegex(nb.NoiseBankError, r"verify_chunk\(chunk_000001.zip\) reports .*members differ "
                                                       r"from the record"):
            self.prov()

    def test_T5_6_the_manifest_when_given(self):
        """A manifest covering every chunk is checked and recorded (covers_chunks); one that disagrees refuses; one
        that lists no chunk is recorded as not covering (the store checks ran anyway)."""
        import store
        root = self.w.root
        chunks = sorted(os.listdir(os.path.join(root, store.CHUNKS)))
        chunks = [c for c in chunks if c.endswith(".zip")]
        good = "".join(f"{rqlib.sha256_file(os.path.join(root, store.CHUNKS, c))}  chunks/{c}\n" for c in chunks)
        mp = self.w.path("continue.sha256")
        with open(mp, "w") as f:
            f.write(good)
        rec = self.prov(manifest_path=mp)
        self.assertEqual(rec["manifest"], {"sha256": rqlib.sha256_file(mp), "covers_chunks": True,
                                           "chunks_checked": len(chunks)})
        with open(mp, "w") as f:
            f.write(good.replace(good[:64], "f" * 64, 1))
        with self.assertRaisesRegex(nb.NoiseBankError, "differs from the manifest"):
            self.prov(manifest_path=mp)
        with open(mp, "w") as f:
            f.write(f"{'a' * 64}  config/other.json\n")
        self.assertEqual(self.prov(manifest_path=mp)["manifest"]["covers_chunks"], False)

    def test_T5_6_conflicting_manifest_declarations_are_refused(self):
        """R9 (Codex revWP3 P2-3): two declarations of one chunk with different sha256 are refused naming both lines,
        in both orders and for every pair of equivalent spellings (chunks/x.zip, ./chunks/x.zip, the absolute path
        under the root), never resolved last-wins; duplicates with the same sha256 in all three spellings are
        admitted, and every declaration is verified."""
        import store
        root = self.w.root
        chunks = sorted(c for c in os.listdir(os.path.join(root, store.CHUNKS)) if c.endswith(".zip"))
        sha = {c: rqlib.sha256_file(os.path.join(root, store.CHUNKS, c)) for c in chunks}
        c0 = chunks[0]
        spell = {"relative": f"chunks/{c0}", "dot": f"./chunks/{c0}", "absolute": os.path.join(root, store.CHUNKS, c0)}
        rest = [f"{sha[c]}  chunks/{c}" for c in chunks[1:]]
        mp = self.w.path("continue.sha256")
        norm = re.escape(os.path.normpath(spell["absolute"]))
        for wrong_first in (True, False):
            for sw in spell:
                for sr in spell:
                    decl = [f"{'f' * 64}  {spell[sw]}", f"{sha[c0]}  {spell[sr]}"]
                    if not wrong_first:
                        decl.reverse()
                    with open(mp, "w") as f:
                        f.write("\n".join(rest[:1] + decl + rest[1:]) + "\n")
                    with self.subTest(wrong_first=wrong_first, wrong=sw, right=sr), \
                            self.assertRaisesRegex(nb.NoiseBankError, rf"lines 2 and 3 declare {norm} with different "
                                                                      "sha256"):
                        self.prov(manifest_path=mp)
        with open(mp, "w") as f:
            f.write("\n".join([f"{sha[c0]}  {s}" for s in spell.values()] + rest) + "\n")
        rec = self.prov(manifest_path=mp)
        self.assertEqual(rec["manifest"], {"sha256": rqlib.sha256_file(mp), "covers_chunks": True,
                                           "chunks_checked": len(chunks)})
        with open(mp, "w") as f:                # (a mismatch names its line)
            f.write("\n".join(rest + [f"{'e' * 64}  ./chunks/{c0}"]) + "\n")
        with self.assertRaisesRegex(nb.NoiseBankError, rf"chunk {re.escape(c0)} differs from the manifest .* line "
                                                       rf"{len(rest) + 1} \(R9\)"):
            self.prov(manifest_path=mp)

    def test_T5_6_a_non_registered_root_is_refused_by_path(self):
        copy_root = self.w.path("copy_of_bank")
        shutil.copytree(self.w.root, copy_root)
        with self.assertRaisesRegex(nb.NoiseBankError, "is not the registered bank root"):
            self.prov(study=copy_root)
        link = self.w.path("link_to_bank")
        os.symlink(self.w.root, link)
        with self.assertRaisesRegex(nb.NoiseBankError, "is not the registered bank root"):
            self.prov(study=link)
        self.assertEqual(nb.d8_bindings()["bank_root"], "/home/harit/finfolk/redqueen_noisebank_2026")

    def test_the_cli_charges_the_ledger_and_keeps_the_starting_guard(self):
        """provenance through the CLI: the D5 ledger is charged (kind D8-noisebank-provenance); with fewer than 25
        CPU-h left it is refused before any work (v5 2.11 / 7's starting guard); a nonexistent ledger path is refused,
        and never created (Codex revWP3 P2-1)."""
        w = self.w
        out = w.path("p.json")
        args = ["provenance", "--study", w.root, "--design", w.design, "--plan", w.plan, "--obs", w.obs, "--out", out,
                "--ledger", w.ledger]
        with mock.patch.object(nb, "d8_bindings", return_value=w.bindings), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(nb.main(args), 0)
            led = [json.loads(x) for x in rqlib.read_text(w.ledger).splitlines()]
            self.assertEqual([(e["kind"], e["status"]) for e in led], [("D8-noisebank-provenance", "ok")])
            os.remove(out)
            with open(w.ledger, "a") as f:
                f.write(json.dumps({"kind": "calibration", "cpu_s": 216.5 * 3600}) + "\n")
            self.assertEqual(nb.main(args), 2)
        self.assertFalse(os.path.exists(out))
        self.assertEqual(len(rqlib.read_text(w.ledger).splitlines()), 2)
        missing = w.path("mistyped-ledger.jsonl")
        err = io.StringIO()
        with mock.patch.object(nb, "d8_bindings", return_value=w.bindings), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(nb.main(args[:-1] + [missing]), 2)
        self.assertIn("no such file", err.getvalue())
        self.assertFalse(os.path.exists(missing) or os.path.exists(out))


@unittest.skipIf(np is None, "numpy is not installed")
class TestD8Validation(unittest.TestCase):
    """v5 2.10's machinery (T4-6 itself is the server's registered-size run): the spec, the synthetic banks on the
    D8 validation streams, V1-V5, an end-to-end run at a test size."""

    def small(self):
        """A test-size structure (4 worlds x 2 times, crossed with the partner) and a design file bound by hash."""
        worlds = [f"w{i}" for i in range(4)]
        prey = sorted((w, t) for w in worlds for t in nb.TIMES[:2])
        partner = {w: worlds[(k + 1) % 4] for k, w in enumerate(worlds)}
        pairs = sorted((q, (wp, tp)) for q in prey for wp in (q[0], partner[q[0]]) for tp in nb.TIMES[:2])
        return pairs, prey, sorted({p for _, p in pairs})

    def test_the_spec_is_v5s_declared_parameters(self):
        spec = nb.d8_validation_spec("a" * 64)
        SR, SD, SE = val_components()
        self.assertTrue(np.allclose(spec["parameters"]["SigmaR"], SR, atol=1e-15, rtol=0))
        self.assertEqual((spec["parameters"]["SigmaD"], spec["parameters"]["SigmaE"]), (SD, SE))
        self.assertEqual(spec["parameters"]["curves"], VAL_CURVES)
        self.assertEqual(spec["size"], {"R": 64, "B": 324, "N": 600, "M": 247, "horizon": 5000})
        self.assertEqual(spec["streams"]["banks"], [f"bank{k}" for k in range(1, 11)])
        self.assertEqual(spec["streams"]["purposes"], ["means", "rows", "donors", "cells", "free"])
        self.assertEqual(spec["streams"]["text"], "AnnexH/D8/1/noisebank/D8-validation/{bank}/{purpose}")
        self.assertEqual(nb.d8_validation_spec("a" * 64, 2)["streams"]["banks"],
                         [f"bank{k}-r2" for k in range(1, 11)])
        self.assertEqual((spec["acceptance"]["V2"]["floor"], spec["acceptance"]["V2"]["se_multiplier"]), (0.02, 2.6))
        self.assertEqual((spec["acceptance"]["V3"]["points"], spec["acceptance"]["V3"]["dev_max"],
                          spec["acceptance"]["V3"]["avg"]), (201, 0.10, [0.95, 1.05]))
        th = nb.d8_validation_truth()[3]
        for k, v in THETA_TRUTH.items():
            self.assertAlmostEqual(th[k], v, places=15)

    def test_banks_are_drawn_on_the_D8_validation_streams(self):
        """Each bank's purposes are distinct D8 streams (seed = the text's first 8 sha256 bytes, recorded with its
        first two outputs); the means lie in v5's declared ranges; survival is capped at 247 (and 0 for M = 0); the
        draw is deterministic."""
        spec = nb.d8_validation_spec("a" * 64)
        st = self.small()
        obs, recs = nb.d8_validation_bank(spec, "bank3", st, R=8)
        obs2, _ = nb.d8_validation_bank(spec, "bank3", st, R=8)
        self.assertEqual(obs, obs2)
        seeds = set()
        for p in ("means", "rows", "donors", "cells", "free"):
            t = f"AnnexH/D8/1/noisebank/D8-validation/bank3/{p}"
            s = int.from_bytes(hashlib.sha256(t.encode()).digest()[:8], "little")
            g = rqlib.SplitMix64(s)
            self.assertEqual((recs[p]["text"], recs[p]["seed"], recs[p]["first_outputs"]), (t, s, [g.next64(),
                                                                                                  g.next64()]))
            seeds.add(s)
        self.assertEqual(len(seeds), 5)
        surv = [o["horizons"]["5000"]["survivors"] for o in obs]
        self.assertLessEqual(max(surv), 247)
        self.assertGreater(sum(v == 247 for v in surv), 10)
        g = rqlib.SplitMix64(recs["means"]["seed"])
        u = [(g.next64() >> 11) * 2.0 ** -53 for _ in range(2 * len(st[0]) + len(st[1]))]
        z0 = -2 + 4 * u[0]
        self.assertTrue(-2 <= z0 < 2)
        obs0, _ = nb.d8_validation_bank(spec, "bank11", st, M=0, R=8)
        self.assertEqual({o["horizons"]["5000"]["survivors"] for o in obs0}, {0})
        self.assertNotEqual(nb.d8_validation_bank(spec, "bank4", st, R=8)[0], obs)

    def test_V1_to_V5_criteria(self):
        """V1-V5 as v5 2.10 defines them, at their boundaries (crafted per-bank results)."""
        spec = nb.d8_validation_spec("a" * 64)
        names = spec["streams"]["banks"]

        def bank(dth=0.0, dev=0.05, avg=1.0, status="ok"):
            return {"status": status, "curves": {ch: VAL_CURVES[ch] for ch in "CSF"},
                    "theta": {k: v + dth for k, v in THETA_TRUTH.items()},
                    "v3": {ch: {"dev": dev, "avg": avg} for ch in "CSF"}}
        v5ok = {"status": "ok", "channels": {"C": {}, "S": dict(ol.STRUCTURAL_ZERO), "F": dict(ol.STRUCTURAL_ZERO)},
                "scales": {"C": VAL_CURVES["C"]}, "components": {"fit": "unconstrained"}}
        good = {b: bank() for b in names}
        c = nb.d8_validation_criteria(spec, good, {}, v5ok)
        self.assertTrue(c["accepted"])
        cases = {
            "V1 status": ({**good, names[3]: bank(status="unavailable")}, "V1"),
            "V1 curve": ({**good, names[0]: dict(bank(), curves={"C": VAL_CURVES["C"], "S": None,
                                                                 "F": VAL_CURVES["F"]})}, "V1"),
            "V2 bias 0.021": ({b: bank(dth=0.021) for b in names}, "V2"),
            "V3 dev": ({b: bank(dev=0.11) for b in names}, "V3"),
            "V3 avg low": ({b: bank(avg=0.94) for b in names}, "V3"),
            "V3 avg high": ({b: bank(avg=1.06) for b in names}, "V3"),
        }
        for name, (banks, which) in cases.items():
            with self.subTest(case=name):
                c = nb.d8_validation_criteria(spec, banks, {}, v5ok)
                self.assertFalse(c[which]["pass"])
                self.assertFalse(c["accepted"])
        c = nb.d8_validation_criteria(spec, {b: bank(dth=0.019) for b in names}, {}, v5ok)
        self.assertTrue(c["V2"]["pass"])
        spread = {b: bank(dth=(0.03 if k % 2 else -0.03) + 0.02) for k, b in enumerate(names)}
        c = nb.d8_validation_criteria(spec, spread, {}, v5ok)
        self.assertTrue(c["V2"]["pass"], "2.6 SE above the floor admits a larger bias")
        self.assertTrue(nb.d8_validation_criteria(spec, {b: bank(dev=0.10, avg=1.05) for b in names}, {}, v5ok)["V3"]
                        ["pass"])
        half = {b: bank(dev=0.2 if k < 4 else 0.05) for k, b in enumerate(names)}
        self.assertTrue(nb.d8_validation_criteria(spec, half, {}, v5ok)["V3"]["pass"], "the median over banks")
        sz = dict(ol.STRUCTURAL_ZERO)
        for bad in (dict(v5ok, status="unavailable"), dict(v5ok, channels={"C": {}, "S": {}, "F": {}}),
                    dict(v5ok, channels={"C": {}, "S": {}, "F": sz}),        # (S alone not a structural zero)
                    dict(v5ok, channels={"C": {}, "S": sz, "F": {}}),        # (F alone)
                    dict(v5ok, scales={"C": {}, "S": {}}), dict(v5ok, components=None),
                    dict(v5ok, components={"fit": "constrained"})):
            with self.subTest(v5=bad):
                c = nb.d8_validation_criteria(spec, good, {}, bad)
                self.assertFalse(c["V5"]["pass"] or c["accepted"])
        leg = {names[0]: {"S": {"dev": 0.4, "avg": 0.7}, "F": {"dev": 0.05, "avg": 1.0}}}
        c = nb.d8_validation_criteria(spec, good, leg, v5ok)
        self.assertTrue(c["V4"]["shows_bias"] and c["accepted"], "V4 is reported, not an acceptance rule")

    def test_one_validation_bank_fits_as_estimate_d8_does(self):
        """A validation bank (test size: the 4 x 2 structure, R = 12; the registered size is the server's) fitted at
        5k on its own `bootstrap` purpose: ok with all three curves, and V3's statistics computed from its usable
        cells."""
        spec = nb.d8_validation_spec("a" * 64)
        obs, _ = nb.d8_validation_bank(spec, "bank1", self.small(), R=12)
        text = "AnnexH/D8/1/noisebank/D8-validation/bank1/bootstrap"
        rec = nb.horizon_estimate_d8(nb.arrays(obs, 5000, CEIL), 5000, 1, M, text=text)
        res = nb._bank_result(rec)
        self.assertEqual(res["status"], "ok", rec["reasons"])
        self.assertTrue(all(res["curves"][ch] is not None for ch in "CSF"))
        for ch in "CSF":
            st = nb._v3_stats([p[0] for p in rec["curve_points"][ch]], res["curves"][ch], VAL_CURVES[ch], spec)
            self.assertTrue(st["dev"] >= 0 and 0.5 < st["avg"] < 2, (ch, st))

    def test_draw_order_known_answers(self):
        """Independent known answers for the spec's draw order on a hand-sized bank (2 exposed pairs sharing one
        predator snapshot, 2 prey snapshots, R = 2), from a SplitMix64 and #68's Box-Muller written out here: the means
        uniforms in the spec's order (per exposed pair u_C then u_S, then per prey snapshot u_F; z = -2 + 4 u_C,
        Delta = u_S, eta = 0.5 + 3 u_F) reach the count law as mu_C = sigma(-0.6 + 0.4 z), mu_S = c sigma(eta - Delta),
        mu_F = c sigma(eta); the latent normals of rows / donors / cells / free reach obslaw.latent in the 1.4 shapes,
        C-order ((q, r, k) <- normal (q R + r) K + k). The first means uniform and mu_C of pair 0 are pinned
        literals."""
        mask = (1 << 64) - 1

        def splitmix(text):
            state = [int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little")]

            def nxt():
                state[0] = (state[0] + 0x9E3779B97F4A7C15) & mask
                z = state[0]
                z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & mask
                z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & mask
                return z ^ (z >> 31)
            return nxt

        def uniform(nxt):
            return (nxt() >> 11) * 2.0 ** -53

        def normals(text, n):
            nxt, out = splitmix(text), []
            for _ in range(n):
                u1 = 1.0 - uniform(nxt)
                u2 = uniform(nxt)
                out.append(math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2))
            return out

        def sig(x):
            return 1.0 / (1.0 + math.exp(-x))
        prey, pred = [("w0", "20M"), ("w1", "20M")], [("w9", "40M")]
        structure = ([(prey[0], pred[0]), (prey[1], pred[0])], prey, pred)
        R, text = 2, "AnnexH/D8/1/noisebank/D8-validation/bank5/{}"
        seen = {"mu": []}
        real_latent, real_counts = ol.latent, ol.generate_counts

        def latent(Z, factors, qi, pj):
            seen.update(Z={k: np.array(v) for k, v in Z.items()}, qi=list(qi), pj=list(pj))
            return real_latent(Z, factors, qi, pj)

        def counts(mu, u, N, Mx, s_of, locate):
            seen["mu"].append((N, Mx, np.array(mu, float)))
            return real_counts(mu, u, N, Mx, s_of, locate)
        with mock.patch.object(ol, "latent", latent), mock.patch.object(ol, "generate_counts", counts):
            nb.d8_validation_bank(nb.d8_validation_spec("a" * 64), "bank5", structure, R=R)
        nxt = splitmix(text.format("means"))
        u = [uniform(nxt) for _ in range(2 * 2 + 2)]
        self.assertEqual(u[0], 0.12710031055144355)
        c = 247 / 600
        z, delta, eta = [-2 + 4 * u[0], -2 + 4 * u[2]], [u[1], u[3]], [0.5 + 3 * u[4], 0.5 + 3 * u[5]]
        want = {"C": [sig(-0.6 + 0.4 * z[e]) for e in (0, 1)], "S": [c * sig(eta[e] - delta[e]) for e in (0, 1)],
                "F": [c * sig(eta[q]) for q in (0, 1)]}
        self.assertAlmostEqual(want["C"][0], 0.2320735695909446, places=15)
        self.assertEqual([(N, Mx) for N, Mx, _ in seen["mu"]], [(324, 324), (600, 247), (600, 247)])
        for (_, _, got), ch in zip(seen["mu"], "CSF"):
            np.testing.assert_allclose(got, want[ch], rtol=1e-14, atol=0, err_msg=ch)
        self.assertEqual((seen["qi"], seen["pj"]), ([0, 1], [0, 0]))
        for key, purpose, n0, K in (("R", "rows", 2, 3), ("D", "donors", 1, 2), ("E", "cells", 2, 2),
                                    ("EF", "free", 2, 1)):
            flat = normals(text.format(purpose), n0 * R * K)
            want_z = [[[flat[(q * R + r) * K + k] for k in range(K)] for r in range(R)] for q in range(n0)]
            got = seen["Z"][key] if key != "EF" else seen["Z"][key][:, :, None]
            np.testing.assert_allclose(got, want_z, rtol=1e-14, atol=1e-15, err_msg=key)

    def test_V3_grid_known_answers(self):
        """V3's construction (v5 2.10, PC-22) on hand-checkable cases: usable-cell logits -2, -1, 0, 1, 4 (unsorted
        here) give the type-7 quantiles q05 = -2 + 0.2 (1) = -1.8 and q95 = 1 + 0.8 (3) = 3.4 on the logit scale and the
        201 points x_j = -1.8 + 0.026 j. (a) S_hat = 0.25 + 0.01 x against S = 0.25 (knots -5, 0, 5): r = 1 + 0.04 x,
        dev = 0.04 (3.4) = 0.136, avg = 1 + 0.04 (0.8) = 1.032; (b) the curves swapped: r = 1 / (1 + 0.04 x), dev =
        0.136 / 1.136 at x = 3.4 and avg the mean of the 201 values (not of 200: they differ by 1.7e-7)."""
        spec = nb.d8_validation_spec("a" * 64)
        mu = [1.0 / (1.0 + math.exp(-x)) for x in (4.0, -1.0, 0.0, -2.0, 1.0)]
        lin = {"x": [-5.0, 0.0, 5.0], "s": [0.20, 0.25, 0.30], "direction": "increasing"}
        flat = {"x": [-5.0, 0.0, 5.0], "s": [0.25, 0.25, 0.25], "direction": "decreasing"}
        a = nb._v3_stats(mu, lin, flat, spec)
        self.assertAlmostEqual(a["dev"], 0.136, places=12)
        self.assertAlmostEqual(a["avg"], 1.032, places=12)
        b = nb._v3_stats(mu, flat, lin, spec)
        grid = [-1.8 + 5.2 * j / 200 for j in range(201)]
        self.assertAlmostEqual(b["dev"], 0.136 / 1.136, places=12)
        self.assertAlmostEqual(b["avg"], sum(1.0 / (1.0 + 0.04 * x) for x in grid) / 201, places=12)
        self.assertAlmostEqual(b["avg"], 0.9723258353401766, places=12)
        self.assertNotAlmostEqual(b["avg"], 0.9723260022211615, places=9)     # (the mean over 200 points)
        self.assertIsNone(nb._v3_stats([], lin, flat, spec))
        self.assertIsNone(nb._v3_stats(mu, None, flat, spec))

    def test_E1_validation_bootstrap_stream_and_V1_to_V5_take_nothing_from_it(self):
        """Clarification 3 E1: each validation fit runs boot = 1 on AnnexH/D8/1/noisebank/D8-validation/{bank}/bootstrap
        with the complete bank key (round 2 here: bank<k>-r2, and bank11-r2 for V5), recorded with its seed and first
        two outputs (an independent SplitMix64 derivation), never a D8-refit stream; and V1-V5 take nothing from the
        bootstrap results: the fits' records carry different bootstrap payloads and a read of their "bootstrap" key
        raises, yet the two reports are byte-identical."""
        tmp = tempfile.mkdtemp()

        class Guarded(dict):
            def __getitem__(self, k):
                if k == "bootstrap":
                    raise AssertionError("V1-V5 read a bootstrap result")
                return super().__getitem__(k)

            def get(self, k, default=None):
                if k == "bootstrap":
                    raise AssertionError("V1-V5 read a bootstrap result")
                return super().get(k, default)

        def stubber(payload, calls):
            def stub(A, horizon, boot=nb.BOOT, m=nb.Z_INTERVALS, text=None):
                calls.append((text, boot))
                if A["M"]["S"] == 0:
                    rec = {"status": "ok", "reasons": [], "scales": {"C": VAL_CURVES["C"]},
                           "channels": {"C": {}, "S": dict(ol.STRUCTURAL_ZERO), "F": dict(ol.STRUCTURAL_ZERO)},
                           "components": {"fit": "unconstrained"}}
                else:
                    mu = {ch: np.nanmean(A[ch], axis=1) / A["N"][ch] for ch in "CSF"}
                    SR, SD, SE = val_components()
                    rec = {"status": "ok", "reasons": [], "scales": VAL_CURVES, "channels": {},
                           "curve_points": {ch: [[float(x), 0.3] for x in mu[ch] if 0.02 < x < 0.98] for ch in "CSF"},
                           "components": {"SigmaR": SR, "SigmaD": SD, "SigmaE": SE}}
                return Guarded(rec, bootstrap=payload)
            return stub
        try:
            dp = os.path.join(tmp, "design.json")
            rqlib.write_json_durable(dp, {"test": "design"})
            b = {"observations_sha256": "0" * 64, "plan_sha256": "0" * 64, "design_file_sha256": rqlib.sha256_file(dp),
                 "ages_sha256": material.AGES_SHA256, "bank_root": tmp}
            spec = nb.d8_validation_spec(rqlib.sha256_file(dp), 2)
            self.assertEqual((spec["streams"]["fit_bootstrap_purpose"], spec["fit"]["boot"]), ("bootstrap", 1))
            reps, calls = [], []
            for payload in ({"status": "ok", "draws": 1, "failed": 0, "ci95": {k: [0.0, 1.0] for k in nb.BOOT_NAMES}},
                            {"status": "unavailable", "draws": 1, "failed": 1, "ci95": None}):
                got = []
                with mock.patch.object(nb, "horizon_estimate_d8", stubber(payload, got)):
                    reps.append(nb.validate_d8(spec, dp, b, m=M, structure=self.small(), R=4))
                calls.append(got)
            self.assertEqual(rqlib.canonical(reps[0]), rqlib.canonical(reps[1]))
            want = [f"AnnexH/D8/1/noisebank/D8-validation/bank{k}-r2/bootstrap" for k in range(1, 12)]
            self.assertEqual(calls, [[(t, 1) for t in want]] * 2)
            for k, t in enumerate(want, 1):
                seed = int.from_bytes(hashlib.sha256(t.encode()).digest()[:8], "little")
                g = rqlib.SplitMix64(seed)
                self.assertEqual(reps[0]["streams"][f"bank{k}-r2"]["bootstrap"],
                                 {"text": t, "seed": seed, "generator": "rqlib.SplitMix64",
                                  "first_outputs": [g.next64(), g.next64()]})
            self.assertNotIn("D8-refit", json.dumps(reps[0]["streams"]))
        finally:
            shutil.rmtree(tmp)

    def test_end_to_end_orchestration_and_the_spec_binding(self):
        """validate_d8 (through run_validate_d8, which charges the D5 ledger) on a test-size structure with the 5k fit
        stubbed by a recorder returning the true parameters (the real fit is tested above and runs on the server):
        the 10 banks and the M = 0 bank (bank11) are drawn and fitted once each on their own bootstrap streams, every
        stream recorded, V4's legacy contrast on bank1 and bank2, V1-V5 computed (the stub's exact parameters pass);
        a changed spec, another round or another design are refused. The run's attempt record is durable before the
        first fit and refreshed after every bank (Codex revWP3 P2-2)."""
        tmp = tempfile.mkdtemp()
        calls, opened = [], []

        def stub(A, horizon, boot=nb.BOOT, m=nb.Z_INTERVALS, text=None):
            if not calls:
                opened.append(sorted(a["open"]["kind"] for a in nb.open_attempts(led).values()))
            calls.append((A["M"]["S"], text, boot, A["R"]))
            if A["M"]["S"] == 0:
                return {"status": "ok", "reasons": [], "scales": {"C": VAL_CURVES["C"]},
                        "channels": {"C": {}, "S": dict(ol.STRUCTURAL_ZERO), "F": dict(ol.STRUCTURAL_ZERO)},
                        "components": {"fit": "unconstrained"}}
            mu = {ch: np.nanmean(A[ch], axis=1) / A["N"][ch] for ch in "CSF"}
            SR, SD, SE = val_components()
            return {"status": "ok", "reasons": [], "scales": VAL_CURVES, "channels": {},
                    "curve_points": {ch: [[float(x), 0.3] for x in mu[ch] if 0.02 < x < 0.98] for ch in "CSF"},
                    "components": {"SigmaR": SR, "SigmaD": SD, "SigmaE": SE}}
        try:
            dp = os.path.join(tmp, "design.json")
            rqlib.write_json_durable(dp, {"test": "design"})
            b = {"observations_sha256": "0" * 64, "plan_sha256": "0" * 64, "design_file_sha256": rqlib.sha256_file(dp),
                 "ages_sha256": material.AGES_SHA256, "bank_root": tmp}
            sp = os.path.join(tmp, "spec.json")
            rqlib.write_json_durable(sp, nb.d8_validation_spec(rqlib.sha256_file(dp)))
            out, led = os.path.join(tmp, "report.json"), os.path.join(tmp, "ledger.jsonl")
            with open(led, "x"):
                pass
            with mock.patch.object(nb, "horizon_estimate_d8", stub):
                rep = nb.run_validate_d8(sp, dp, out, led, bindings=b, m=M, structure=self.small(), R=8)
            want = [(247, f"AnnexH/D8/1/noisebank/D8-validation/bank{k}/bootstrap", 1, 8) for k in range(1, 11)]
            self.assertEqual(calls, want + [(0, "AnnexH/D8/1/noisebank/D8-validation/bank11/bootstrap", 1, 8)])
            self.assertEqual(rep["schema"], "finfolk.redqueen.noisebank.d8validation.report/1")
            self.assertEqual(sorted(rep["streams"]), sorted([f"bank{k}" for k in range(1, 12)]))
            self.assertEqual(sorted(rep["streams"]["bank1"]), ["bootstrap", "cells", "donors", "free", "means", "rows"])
            self.assertEqual(rep["streams"]["bank7"]["rows"]["text"], "AnnexH/D8/1/noisebank/D8-validation/bank7/rows")
            self.assertEqual(sorted(rep["legacy_V4"]), ["bank1", "bank2"])
            self.assertEqual({ch for bk in ("bank1", "bank2") for ch in rep["legacy_V4"][bk]}, {"S", "F"})
            self.assertTrue(rep["acceptance"]["accepted"], rep["acceptance"])
            self.assertEqual(rep["acceptance"]["V2"]["entries"]["R_SF"]["bias"], 0.0)
            self.assertEqual(rqlib.read_json(out)["ledger_entry"]["kind"], "D8-noisebank-validation")
            self.assertEqual([json.loads(x)["kind"] for x in rqlib.read_text(led).splitlines()],
                             ["D8-noisebank-validation"])
            self.assertEqual(opened, [["D8-noisebank-validation"]])
            a = nb.attempts_state(led)[rqlib.read_json(out)["ledger_entry"]["attempt"]]
            self.assertEqual(a["steps"], [f"validate-d8: bank{k}" for k in range(1, 11)] + ["validate-d8: bank11 (V5)"])
            self.assertEqual(a["close"]["status"], "ok")
            spec = rqlib.read_json(sp)
            for name, d in (("SigmaD", _edit(spec, ("parameters", "SigmaD", 0, 1), 0.06)),
                            ("banks", _edit(spec, ("streams", "banks", 0), "bank0")),
                            ("round", dict(spec, round=2))):
                with self.subTest(spec=name), self.assertRaisesRegex(nb.NoiseBankError, "registered validation spec"):
                    nb.validate_d8(d, dp, b, m=M, structure=self.small(), R=4)
            with self.assertRaisesRegex(nb.NoiseBankError, "is not the bound"):
                nb.validate_d8(spec, dp, dict(b, design_file_sha256="1" * 64), m=M, structure=self.small(), R=4)
        finally:
            shutil.rmtree(tmp)


_KILL_CHILD = r'''
import sys
sys.path.insert(0, sys.argv[1])
import noisebank as nb
nb.ATTEMPT_REFRESH_CPU_S = 0.2           # (a test-speed refresh: the registered 30 s is checked with a fake clock)
nb.ATTEMPT_POLL_S = 0.02


def burn(*args, **kw):                   # (CPU-bound until SIGKILLed; no major step: only the refresher writes)
    x = 0
    while True:
        x += 1


nb.validate_d8 = burn
nb.run_validate_d8(sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[2], bindings={})
'''


@unittest.skipIf(np is None, "numpy is not installed")
class TestD8Ledger(unittest.TestCase):
    """The cumulative D5 ledger and the attempt records (v5 2.11: failed and interrupted runs are charged; Codex
    revWP3 P2-1, P2-2): fail-closed reading, no implicit ledger, the durable in-progress attempt record and its
    refreshes, the late-failure status, a SIGKILLed run refused until reconciled and then charged once."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def ledger(self, text="", name="ledger.jsonl"):
        p = os.path.join(self.tmp, name)
        with open(p, "x") as f:                 # (a test ledger, created explicitly)
            f.write(text)
        return p

    def spec(self):
        p = os.path.join(self.tmp, "spec.json")
        if not os.path.exists(p):
            rqlib.write_json_durable(p, {})
        return p

    def test_P2_1_every_entry_is_validated_and_a_missing_ledger_is_refused(self):
        """Every ledger entry is validated with the file and line (cpu_s present, a number, finite, >= 0; a JSON
        object; a string kind; a terminating newline): NaN, +-inf, a negative, a missing cpu_s, non-numeric values, a
        malformed JSON line, a blank line... are refused, never skipped or read as 0, and the starting guard refuses
        before any work. A nonexistent ledger is refused by the total, the guard and ledger_add, and never created;
        ledger_add never writes a bad charge; ledger_init_empty is the explicit initialization."""
        good = '{"cpu_s": 3600.0, "kind": "fitting", "utc": "2026-11-01T00:00:00Z"}\n'
        bad = {"NaN": '{"cpu_s": NaN, "kind": "x"}', "+inf": '{"cpu_s": Infinity, "kind": "x"}',
               "-inf": '{"cpu_s": -Infinity, "kind": "x"}', "1e999": '{"cpu_s": 1e999, "kind": "x"}',
               "negative": '{"cpu_s": -7200.0, "kind": "x"}', "missing cpu_s": '{"kind": "x"}',
               "string NaN": '{"cpu_s": "NaN", "kind": "x"}', "numeric string": '{"cpu_s": "3600", "kind": "x"}',
               "boolean": '{"cpu_s": true, "kind": "x"}', "null": '{"cpu_s": null, "kind": "x"}',
               "malformed JSON": '{"cpu_s": 12, "kind": ', "not an object": "[3600]", "blank line": "",
               "kind not a string": '{"cpu_s": 1.0, "kind": 5}'}
        out = os.path.join(self.tmp, "out.json")
        for k, (name, line) in enumerate(bad.items()):
            p = self.ledger(good + line + "\n" + good, f"bad{k}.jsonl")
            with self.subTest(case=name):
                with self.assertRaisesRegex(nb.NoiseBankError, rf"D5 ledger {re.escape(p)} line 2: "):
                    nb.ledger_total([p])
                with mock.patch.object(nb, "provenance") as work, \
                        self.assertRaisesRegex(nb.NoiseBankError, rf"{re.escape(p)} line 2: "):
                    nb.run_provenance("root", "d", "p", "o", None, out, p, bindings={})
                work.assert_not_called()
        p = self.ledger(good + good.rstrip("\n"), "torn.jsonl")
        with self.assertRaisesRegex(nb.NoiseBankError, "line 2: no terminating newline"):
            nb.ledger_total([p])
        with self.assertRaisesRegex(nb.NoiseBankError, "no terminating newline"):
            nb.ledger_add(p, {"kind": "x", "cpu_s": 1.0})
        self.assertEqual(rqlib.read_text(p), good + good.rstrip("\n"))
        missing = os.path.join(self.tmp, "mistyped-ledger.jsonl")
        with self.assertRaisesRegex(nb.NoiseBankError, "no such file"):
            nb.ledger_total([missing])
        with mock.patch.object(nb, "provenance") as work, self.assertRaisesRegex(nb.NoiseBankError, "no such file"):
            nb.run_provenance("root", "d", "p", "o", None, out, missing, bindings={})
        work.assert_not_called()
        with self.assertRaisesRegex(nb.NoiseBankError, "no such file"):
            nb.ledger_add(missing, {"kind": "x", "cpu_s": 1.0})
        self.assertFalse(os.path.exists(missing))
        ok = self.ledger(good, "ok.jsonl")
        for v in (math.nan, math.inf, -1.0, "1", None, True):
            with self.subTest(add=v), self.assertRaises(nb.NoiseBankError):
                nb.ledger_add(ok, {"kind": "x", "cpu_s": v})
        self.assertEqual(rqlib.read_text(ok), good)
        nb.ledger_add(ok, {"kind": "D8-noisebank-test", "cpu_s": 1800})
        t = nb.ledger_total([ok])
        self.assertEqual((t["entries"], t["cpu_h"], t["remaining_h"], t["by_kind_h"]),
                         (2, 1.5, 238.5, {"D8-noisebank-test": 0.5, "fitting": 1.0}))
        new = os.path.join(self.tmp, "new.jsonl")
        nb.ledger_init_empty(new)
        self.assertEqual((rqlib.read_text(new), nb.ledger_total([new])["remaining_h"]), ("", 240.0))
        with self.assertRaisesRegex(nb.NoiseBankError, "exists"):
            nb.ledger_init_empty(new)

    def test_P2_2_the_attempt_is_durable_before_the_work_and_refreshed_under_60_cpu_s(self):
        """The in-progress record (attempt id, kind, command, UTC start, pid, host) is in the attempts file beside the
        ledger, never in the ledger, from the attempt's start; its cumulative cpu_s is refreshed durably at each major
        step and, by the refresher's poll, whenever 30 CPU-s have passed, so the durable value never lags the CPU by
        60 s (a fake CPU clock); finalization appends one entry with the attempt id, once, and closes the attempt."""
        import platform
        led = self.ledger()
        clock = [100.0]
        with mock.patch.object(nb, "_cpu_s", lambda: clock[0]):
            att = nb._Attempt(led, "D8-noisebank-validation", "validate-d8", refresher=False)
            a = nb.attempts_state(led)[att.id]
            self.assertEqual({k: a["open"][k] for k in ("kind", "command", "pid", "host", "cpu_s")},
                             {"kind": "D8-noisebank-validation", "command": "validate-d8", "pid": os.getpid(),
                              "host": platform.node(), "cpu_s": 0.0})
            self.assertRegex(a["open"]["utc_start"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
            self.assertIsNone(a["close"])
            self.assertEqual((rqlib.read_text(led), nb.attempts_path(led)), ("", led + ".attempts.jsonl"))
            lag = 0.0
            for _ in range(300):
                clock[0] += 1.7
                att.tick()
                lag = max(lag, att.cpu() - nb.attempts_state(led)[att.id]["cpu_s"])
            self.assertLess(lag, 60.0)
            self.assertGreater(lag, 25.0)       # (a refresh per ~30 CPU-s, not per poll)
            clock[0] += 5.0
            att.step("validate-d8: bank1")
            a = nb.attempts_state(led)[att.id]
            self.assertEqual((a["cpu_s"], a["steps"]), (att.cpu(), ["validate-d8: bank1"]))
            att.measure("ok")
            att.charge()
            att.charge()
            att.__exit__(None, None, None)
        (e,) = nb.ledger_entries(led)
        self.assertEqual((e["kind"], e["status"], e["attempt"], e["cpu_s"]),
                         ("D8-noisebank-validation", "ok", att.id, clock[0] - 100.0))
        self.assertEqual(nb.attempts_state(led)[att.id]["close"]["status"], "ok")
        self.assertEqual(nb.open_attempts(led), {})

    def test_P2_2_a_write_failure_after_measure_ok_is_charged_failed(self):
        """At the transition (Codex revWP3 P2-2): estimate-d8's receipt write and validate-d8's report write fail
        AFTER measure("ok"): the charge says failed, never ok. estimate-d8's artifact write failing AFTER the charge
        leaves the one "ok" entry (the refit and its receipt completed; the receipt records exactly that entry) and
        closes the attempt failed."""
        led = self.ledger()
        fit = {"inputs": {"observations_sha256": "0" * 64}, "boot": 1, "synthetic": True}
        nowhere = os.path.join(self.tmp, "no-such-dir", "x.json")
        rc = os.path.join(self.tmp, "receipt.json")
        with mock.patch.object(nb, "estimate_d8", lambda *a, **k: fit):
            with self.assertRaises(OSError):
                nb.run_estimate_d8("o", "a", "d", "p", "v", "r", os.path.join(self.tmp, "a.json"), nowhere, led, ["x"],
                                   bindings={})
            with mock.patch.object(nb, "d8_artifact", lambda f, sha: {"receipt_sha256": sha}), \
                    self.assertRaises(OSError):
                nb.run_estimate_d8("o", "a", "d", "p", "v", "r", nowhere, rc, led, ["x"], bindings={})
        with mock.patch.object(nb, "validate_d8", lambda *a, **k: {"acceptance": {"accepted": True}}), \
                self.assertRaises(OSError):
            nb.run_validate_d8(self.spec(), "d", nowhere, led, bindings={})
        ent = [json.loads(x) for x in rqlib.read_text(led).splitlines()]
        self.assertEqual([(e["kind"], e["status"]) for e in ent], [("D8-noisebank-refit", "failed"),
                                                                    ("D8-noisebank-refit", "ok"),
                                                                    ("D8-noisebank-validation", "failed")])
        self.assertEqual(rqlib.read_json(rc)["ledger_entry"], {k: v for k, v in ent[1].items() if k != "utc"})
        self.assertEqual([(a["close"]["status"], a["close"]["ledger_status"]) for a in nb.attempts_state(led).values()],
                         [("failed", "failed"), ("failed", "ok"), ("failed", "failed")])

    def test_P2_2_only_a_dead_attempt_is_reconciled_and_never_charged_twice(self):
        """Finalization is idempotent by attempt id; an attempt whose finalization stopped between the ledger append
        and the close is reconciled by closing it, without a second charge; an attempt reconciled (as if its process
        were gone) and then finalized by its process is charged once (the id prevents a double charge) and closed
        once; reconciliation refuses while the attempt's process runs (this process: same host, boot and start time);
        a reused pid (another start time), another boot or a zombie is not the attempt's process; another host is
        refused."""
        import platform
        led = self.ledger()
        att = nb._Attempt(led, "D8-noisebank-provenance", "provenance", refresher=False)
        att.measure("ok")
        att.charge()
        att.charge()
        self.assertEqual(len(nb.ledger_entries(led)), 1)
        self.assertEqual(list(nb.open_attempts(led)), [att.id])          # (stopped before the close)
        with self.assertRaisesRegex(nb.NoiseBankError, "still running"):
            nb.reconcile_attempts(led)
        with mock.patch.object(nb, "_attempt_alive", return_value=False):
            (r,) = nb.reconcile_attempts(led)
        self.assertEqual((r["attempt"], r["charged_cpu_s"]), (att.id, None))
        self.assertEqual((len(nb.ledger_entries(led)), nb.open_attempts(led), nb.reconcile_attempts(led)), (1, {}, []))
        att2 = nb._Attempt(led, "D8-noisebank-validation", "validate-d8", refresher=False)
        with mock.patch.object(nb, "_attempt_alive", return_value=False):
            (r2,) = nb.reconcile_attempts(led)
        att2.measure("ok")
        att2.charge()
        att2.__exit__(None, None, None)
        self.assertEqual([e["attempt"] for e in nb.ledger_entries(led)], [att.id, att2.id])
        self.assertEqual((r2["charged_by"], nb.ledger_entries(led)[1]["kind"], nb.open_attempts(led)),
                         ("reconcile", "D8-noisebank-interrupted", {}))
        o = dict(nb.attempts_state(led)[att.id]["open"])
        if o["boot_id"] is not None and o["start_ticks"] is not None:      # (Linux /proc)
            self.assertTrue(nb._attempt_alive(o))
            self.assertFalse(nb._attempt_alive(dict(o, start_ticks=o["start_ticks"] + 1)))
            self.assertFalse(nb._attempt_alive(dict(o, boot_id="another-boot")))
            with mock.patch.object(nb, "_proc_stat", return_value=("Z", o["start_ticks"])):
                self.assertFalse(nb._attempt_alive(o))
        with self.assertRaisesRegex(nb.NoiseBankError, "recorded on host"):
            nb._attempt_alive(dict(o, host=platform.node() + "-elsewhere"))

    def test_P2_2_a_SIGKILLed_run_is_refused_until_reconciled_and_charged_once(self):
        """A validate-d8 child SIGKILLed mid-run (CPU-bound; only the refresher writes, at a test-speed 0.2 CPU-s)
        leaves its attempt open with durable progress and charges nothing; every budget-dependent command then refuses
        before its work; d8-reconcile charges the last durable cpu_s + 60 s once, in the registered line format with
        kind D8-noisebank-interrupted, and closes the attempt; a second reconcile charges nothing; the commands run
        again."""
        import platform
        import signal
        import subprocess
        import time
        led = self.ledger()
        out = os.path.join(self.tmp, "report.json")
        records = led + ".attempts.jsonl"
        child = subprocess.Popen([sys.executable, "-I", "-c", _KILL_CHILD, HERE, led, self.spec(),
                                  os.path.join(self.tmp, "design.json"), out],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        recs, alive = [], False
        try:
            deadline = time.time() + 120
            while time.time() < deadline and child.poll() is None:
                if os.path.exists(records):
                    recs = [json.loads(x) for x in rqlib.read_text(records).split("\n")[:-1]]
                    if sum(r["event"] == "progress" for r in recs) >= 3:
                        break
                time.sleep(0.05)
            alive = child.poll() is None
        finally:
            if child.poll() is None:
                os.kill(child.pid, signal.SIGKILL)
            _, err = child.communicate(timeout=60)
        self.assertTrue(alive, f"the child ended before the kill: {err[-2000:]}")
        self.assertEqual(child.returncode, -signal.SIGKILL)
        self.assertGreaterEqual(sum(r["event"] == "progress" for r in recs), 3,
                                "no durable in-progress attempt record (or refresh) before the kill")
        ((aid, a),) = nb.attempts_state(led).items()
        self.assertIsNone(a["close"])
        self.assertEqual((a["open"]["kind"], a["open"]["pid"], a["open"]["host"]),
                         ("D8-noisebank-validation", child.pid, platform.node()))
        self.assertGreater(a["cpu_s"], 0.4)
        self.assertEqual(rqlib.read_text(led), "")              # (the kill charged nothing by itself)
        work = mock.Mock()
        with mock.patch.object(nb, "validate_d8", work), mock.patch.object(nb, "provenance", work), \
                mock.patch.object(nb, "estimate_d8", work):
            for name, run in (("validate-d8", lambda: nb.run_validate_d8(self.spec(), "d", out, led, bindings={})),
                              ("provenance", lambda: nb.run_provenance("r", "d", "p", "o", None, out, led,
                                                                       bindings={})),
                              ("estimate-d8", lambda: nb.run_estimate_d8("o", "a", "d", "p", "v", "r", out,
                                                                         os.path.join(self.tmp, "rc.json"), led,
                                                                         ["x"], bindings={}))):
                with self.subTest(command=name), self.assertRaisesRegex(nb.NoiseBankError, "unclosed D8 attempt"):
                    run()
        work.assert_not_called()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(nb.main(["d8-reconcile", "--ledger", led]), 0)
        lines = rqlib.read_text(led).splitlines()
        self.assertEqual(len(lines), 1)
        e = json.loads(lines[0])
        self.assertEqual(lines[0], json.dumps(e, sort_keys=True))
        self.assertEqual((e["kind"], e["status"], e["attempt"], e["attempt_kind"], e["cpu_s"]),
                         ("D8-noisebank-interrupted", "interrupted", aid, "D8-noisebank-validation", a["cpu_s"] + 60.0))
        self.assertEqual(nb.attempts_state(led)[aid]["close"]["charged_by"], "reconcile")
        self.assertEqual(nb.reconcile_attempts(led), [])
        self.assertEqual(len(rqlib.read_text(led).splitlines()), 1)
        with mock.patch.object(nb, "validate_d8", lambda *x, **k: {"acceptance": {"accepted": True}}):
            nb.run_validate_d8(self.spec(), "d", out, led, bindings={})
        self.assertEqual([x["kind"] for x in nb.ledger_entries(led)], ["D8-noisebank-interrupted",
                                                                       "D8-noisebank-validation"])


@unittest.skipIf(np is None, "numpy is not installed")
class TestD8Assembly(unittest.TestCase):
    """v5 2.8's assembly contract in A (the T5-4 conformance with #68 itself is the adoption gate below)."""

    def setUp(self):
        import test_obslaw as tob
        self.tmp = tempfile.mkdtemp()
        self.bank = os.path.join(self.tmp, "bank3.json")
        rqlib.write_json_durable(self.bank, tob.bank3_doc(synthetic=False))
        self.mean = {"schema": "finfolk.redqueen.annexH.generator/1", "fitted": True, "theta": [[0.0] * 98] * 2,
                     "ar": {"rho": [0.7] * 5, "Sigma": np.eye(5).tolist(), "step": 5.0}, "capture_bound": 324,
                     "replicates": 6, "engine_sha256": "e" * 64,
                     "fit": {"mean_head": "c_H*sigmoid(eta)",
                             "mean": {k: "f" * 64 for k in ("implementation_sha256", "inputs_sha256", "receipt_sha256",
                                                            "engine_sha256")}}}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_the_bank_fields_are_copied_verbatim_with_one_added_key(self):
        raw = rqlib.read_bytes(self.bank)
        bank = json.loads(raw)
        p = nb.assemble_generator(self.bank, self.mean)
        self.assertEqual(rqlib.canonical(p["noise"]), rqlib.canonical(bank["noise"]))
        self.assertEqual(set(p["fit"]["noise"]) - set(bank["fit"]["noise"]), {"source_artifact_sha256"})
        self.assertEqual({k: v for k, v in p["fit"]["noise"].items() if k != "source_artifact_sha256"},
                         bank["fit"]["noise"])
        self.assertEqual(p["fit"]["noise"]["source_artifact_sha256"], rqlib.sha256_bytes(raw))
        self.assertEqual(p["fit"]["noise_likelihood"], bank["fit"]["noise_likelihood"])
        for k in ("cohort", "cohort_sha256", "horizon", "dt", "support_law", "age_clock", "survivor_ceiling"):
            self.assertEqual(p[k], bank[k])
        self.assertEqual((p["engine_sha256"], p["fit"]["mean"]["engine_sha256"]), ("e" * 64, "f" * 64))
        self.assertNotIn("streams", p["fit"])

    def test_refusals(self):
        for k in ("noise", "cohort", "survivor_ceiling"):
            with self.subTest(mean_carries=k), self.assertRaisesRegex(nb.NoiseBankError, "bank-supplied"):
                nb.assemble_generator(self.bank, dict(self.mean, **{k: 1}))
        with self.assertRaisesRegex(nb.NoiseBankError, "bank-supplied"):
            nb.assemble_generator(self.bank, dict(self.mean, fit=dict(self.mean["fit"], noise={})))
        import test_obslaw as tob
        rqlib.write_json_durable(self.bank, tob.bank3_doc(synthetic=True))
        with self.assertRaisesRegex(ol.ObsLawError, "synthetic"):
            nb.assemble_generator(self.bank, self.mean)


_GATE_T5_4 = r'''
import copy, json, sys
sys.path.insert(0, sys.argv[1])
import calib
req = json.load(sys.stdin)
bank = open(req["bank"], "rb").read()
out = {}
for name, p in req["cases"].items():
    try:
        calib.check_params(p, production=True)
        calib.check_noise_source(p, bank if name != "altered bank bytes" else bank + b" ")
        out[name] = "pass"
    except calib.CalibError as e:
        out[name] = "refused: " + str(e)
print(json.dumps(out))
'''
_MEAN_68 = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import calib
p = calib.placeholder_params(n_train=4)
print(json.dumps({k: p[k] for k in ("schema", "theta", "ar", "capture_bound", "replicates")}))
'''


@unittest.skipIf(np is None, "numpy is not installed")
@unittest.skipUnless(os.environ.get("RQ_PR68_DIR"), "adoption gate: RQ_PR68_DIR (the root of a read-only extraction "
                     "of the pinned #68 commit with the engine-field change) not set")
class TestAdoptionGateT5_4(unittest.TestCase):
    """T5-4 (v5 2.8, mandatory #68 conformance; adoption gate): A's assembly of a bank/3 artifact plus a synthetic mean
    block (#68's placeholder parameters, marked fitted for the check) passes #68's check_params(production=True) and
    check_noise_source at the pinned commit with the engine-field change (the extraction authenticated as in
    test_obslaw); overwriting fit.noise.engine_sha256, a top-level engine_sha256 other than fit.mean.engine_sha256,
    one altered SigmaD entry and altered bank bytes each fail. No name-only fallback."""

    def test_T5_4_assembly_conforms_to_pinned_68(self):
        import subprocess
        import test_obslaw as tob
        root = os.environ["RQ_PR68_DIR"]
        commit, n = tob.pr68_pinned_commit(root)
        tools = os.path.join(root, "tools", "redqueen")
        print(f"\nadoption gate T5-4: #68 PINNED_COMMIT {commit} ({n} files match its trusted MANIFEST)",
              file=sys.stderr)
        r = subprocess.run([sys.executable, "-I", "-B", "-c", _MEAN_68, tools], capture_output=True, text=True,
                           timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        mean = json.loads(r.stdout)
        mean.update(fitted=True, engine_sha256="e" * 64,
                    fit={"mean_head": "c_H*sigmoid(eta)",
                         "mean": {k: "f" * 64 for k in ("implementation_sha256", "inputs_sha256", "receipt_sha256")}})
        mean["fit"]["mean"]["engine_sha256"] = "e" * 64
        tmp = tempfile.mkdtemp()
        try:
            bank = os.path.join(tmp, "bank3.json")
            rqlib.write_json_durable(bank, tob.bank3_doc(synthetic=False))
            p = nb.assemble_generator(bank, mean)
            cases = {"assembly": p}
            q = copy.deepcopy(p)
            q["fit"]["noise"]["engine_sha256"] = "9" * 64
            cases["overwritten fit.noise.engine_sha256"] = q
            q = copy.deepcopy(p)
            q["engine_sha256"] = "8" * 64
            cases["top-level engine != fit.mean.engine"] = q
            q = copy.deepcopy(p)
            q["noise"]["SigmaD"][0][1] = q["noise"]["SigmaD"][1][0] = q["noise"]["SigmaD"][0][1] + 1e-3
            cases["altered SigmaD"] = q
            cases["altered bank bytes"] = p
            r = subprocess.run([sys.executable, "-I", "-B", "-c", _GATE_T5_4, tools], capture_output=True, text=True,
                               timeout=600, input=json.dumps({"bank": bank, "cases": cases}))
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            got = json.loads(r.stdout)
            print(f"adoption gate T5-4 results: {json.dumps(got, sort_keys=True)}", file=sys.stderr)
            self.assertEqual(got["assembly"], "pass")
            for k in cases:
                if k != "assembly":
                    self.assertTrue(got[k].startswith("refused"), (k, got[k]))
        finally:
            shutil.rmtree(tmp)

if __name__ == "__main__":
    unittest.main()

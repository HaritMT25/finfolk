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
STEP = 0.0199                    # (a coarse dependence grid for the tests: 101 nodes; registered 0.005)


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
        cls.bank = nb.estimate(cls.doc, boot=29, step=STEP)

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
            for M in (SR, SD, SE):
                self.assertGreaterEqual(float(np.min(np.linalg.eigvalsh(M))), -1e-12)
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
        g = nb.rho_grid(STEP)
        return {k: -curv * (g - centre[k]) ** 2 for k in nb.GROUPS}

    def test_feasible_maxima_are_the_fit(self):
        r = {"R_CC": 0.3, "R_SS": 0.25, "R_CS": 0.1, "D_CC": 0.2, "D_SS": 0.15, "D_CS": 0.05, "T_CS": 0.3,
             "R_CF": 0.1, "R_SF": 0.2}
        f = nb.fit_dependence(self.quad(r), STEP)
        self.assertEqual(f["fit"], "unconstrained")
        for k in nb.GROUPS:
            self.assertAlmostEqual(f["rho"][k], r[k], delta=STEP / 40)
        with self.assertRaises(nb.NoiseBankError):
            nb.rho_grid(0.02)                                                   # (does not divide the grid)

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
        f = nb.fit_dependence(obj, STEP)
        self.assertEqual(f["fit"], "constrained")
        SR, SD, SE = f["SigmaR"], f["SigmaD"], f["SigmaE"]
        for M in (SR, SD, SE):
            self.assertGreaterEqual(float(np.min(np.linalg.eigvalsh(M))), -1e-12)
        self.assertAlmostEqual(SR[0, 0] + SD[0, 0] + SE[0, 0], 1.0, delta=1e-12)
        self.assertAlmostEqual(SR[1, 1] + SD[1, 1] + SE[1, 1], 1.0, delta=1e-12)
        self.assertLessEqual(SR[2, 2], 1.0 + 1e-12)
        start = nb._theta_map(nb._theta_start(f["unconstrained"]))
        ll0 = sum(float(nb._cubic(obj[g], start[g], STEP)) for g in nb.GROUPS)
        self.assertGreater(f["loglik"], ll0)
        for th in ([0.1] * 9, [1.0, 2.0, -0.5, 0.3, 1.4, -1.2, 0.7, 1.5, 2.5]):
            self.assertTrue(nb.components_of(nb._theta_map(th))[3])

    def test_unidentified_and_missing_groups_are_refused(self):
        """One time and no crossing: no row-sharing and no donor-sharing pairs, refused with reasons; the
        generator block is unavailable; the CLI exits 2 and still writes canonical JSON. An impossible
        curvature floor makes every group unidentified. Bad counts, schemas and draw counts are refused."""
        doc, _ = simulate(seed=7, W=4, T=1, R=16, cross=False)
        bank = nb.estimate(doc, boot=3, step=STEP)
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
            e2 = nb.estimate(doc2, boot=2, step=STEP)["horizons"]["5000"]
        finally:
            nb.INFO_MIN = old
        self.assertEqual(e2["status"], "unavailable")
        self.assertTrue(any("unidentified" in r for r in e2["reasons"]))
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(doc2, boot=0)
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(doc2, boot=2, step=STEP, replicates=64)
        bad = json.loads(json.dumps(doc2))
        bad["observations"][-1]["horizons"]["5000"]["survivors"] = 10 ** 6
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(bad, boot=2, step=STEP)
        bad["observations"][-1]["horizons"]["5000"]["survivors"] = 1.5
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(bad, boot=2, step=STEP)
        bad["observations"][-1]["horizons"]["5000"]["survivors"] = 1
        bad["observations"][-1]["replicate"] = 99
        with self.assertRaises(nb.NoiseBankError):
            nb.estimate(bad, boot=2, step=STEP)
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
        for x in (0.3, 2.0, 40.0, 900.0):
            self.assertAlmostEqual(nb.inv_trigamma(nb._trigamma(x)) / x, 1.0, delta=1e-9)
        for rec in (flat, est):
            rqlib.canonical(rec)

    def test_crossed_bootstrap_multiplicities(self):
        """Codex #72 r1 P2-6: a pair's weight multiplies the multiplicities of its distinct sources (prey role
        m, predator role m'); two draws with the SAME distinct worlds but different multiplicities give
        different estimates; the source keys have the registered shapes (free pairs follow the prey)."""
        self.assertEqual(nb.pick_weights([((0,), (1, 2)), ((0, 1), (2,)), ((2,), (1,))], [2, 1, 0], [1, 3, 2]).tolist(),
                         [2 * 3 * 2, 2 * 1 * 2, 0])
        doc, _ = simulate(seed=9, W=4, T=2, R=16, horizons=(5000,))
        A = nb.arrays(doc["observations"], 5000)
        U = nb.usable(A)
        G, worlds = nb.group_pairs(A, U)
        tab = nb.group_tables(A, U, G, STEP)
        shapes = {g: {(len(kp), len(kq)) for kp, kq in tab[g]["keys"]} for g in nb.GROUPS}
        for g in ("R_CC", "R_SS", "R_CS"):
            self.assertEqual(shapes[g], {(1, 2)})
        for g in ("D_CC", "D_SS", "D_CS"):
            self.assertEqual(shapes[g], {(2, 1)})
        for g in ("T_CS", "R_CF", "R_SF"):
            self.assertEqual(shapes[g], {(1, 1)})

        def fit(m, mp):
            return nb._entries(nb.fit_dependence({g: nb.pick_weights(tab[g]["keys"], m, mp) @ tab[g]["T"]
                                                  for g in nb.GROUPS}, STEP))
        a = fit([2, 1, 1, 0], [1, 1, 1, 1])
        b = fit([1, 2, 1, 0], [1, 1, 1, 1])                                   # (the same distinct prey worlds)
        self.assertGreater(max(abs(x - y) for x, y in zip(a, b)), 1e-6)
        D, failed = nb.bootstrap(tab, len(worlds), 5, 0, STEP)
        self.assertEqual(D.shape[0] + failed, 5)


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

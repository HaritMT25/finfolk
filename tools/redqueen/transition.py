#!/usr/bin/env python3
"""transition.py: H-T, one complete epoch-transition maximum (Annex H.4; design v4 §8.4; (d) item 5,
part 4), with the user's decision 3 (2026-11-07): FSD dominance also requires directional equivalence;
material directional + material recurrent structure is "mixed". numpy; deterministic.

EPOCHS E1 = [F1, 50], E2 = [75, 125], E3 = [150, 200] M; the epoch period set recurrence.EPOCH_PERIODS
({4..20} M; 25M dropped provisionally); the same qualifying worlds in every epoch. Per epoch e
(recurrence.py on the epoch's own designs, the phase-conditional rule 6 at the fitted phase included):
  S_e, the reversal-gated selected energies E^F_{C,e}, E^F_{Q,e} (H.3.4-H.3.6);
  the UNGATED, conservatively searched energies E^U_{h,e} = (1/n) sum_w max_P r_hw,e(P)^2 (no
    reversal, return, reciprocal or material gate); every candidate of every world must be supported,
    else E^U = +inf and the epoch cannot be ARD-certified;
  the directional slopes beta_{P,e}, beta_{Q,e} (backbone.py, focal times restricted to the epoch, the
    complete 41-member opponent panels; per-world values, cached: unpooled fits).

BOOTSTRAP (H.4.2). 9,999 PAIRED whole-world draws (one index vector selects a world's three epochs
together; stream AnnexH/1/H-T/<analysis>/bootstrap), and once per draw one zero-mean reference-source
error vector xi ~ N(0, I_k) (stream .../reference-source), propagated jointly through every world,
readout and epoch through its loading (the bank's shared-reference component; world resampling carries
the local errors, no new local noise). Per draw the reference projections, phases, windows, gates and
period selections are recomputed (vectorized: linear operators of the responses, rule 6 through
recurrence.ChainTable); E^U's candidate set is the observed one (its +inf is decided on the measured
support). Component tails: p_m = (1 + #{m*_b - m >= m}) / 10,000 (centred, unstudentized); basic
bounds L_{1-a} = theta - Q_{1-a}(theta* - theta), U_{1-a} = theta - Q_a(theta* - theta).

CANDIDATES (H.4.4-H.4.5). For the ordered pairs (1,2), (1,3), (2,3), ARD->FSD (ARD the earlier epoch)
then FSD->ARD: the FSD epoch's calibrated recurrence gate, and all fourteen margins strictly positive:
  beta_{P,a}, beta_{Q,a}; d_C^2 - E^U_{C,a}, d_Q^2 - E^U_{Q,a}; E^F_{C,f} - d_C^2, E^F_{Q,f} - d_Q^2;
  delta_P -+ beta_{P,f} (two), delta_Q -+ beta_{Q,f} (two); beta_{P,a} - beta_{P,f},
  beta_{Q,a} - beta_{Q,f}; E^F_{C,f} - E^U_{C,a}, E^F_{Q,f} - E^U_{Q,a}
(d_C = 0.10, d_Q = 0.04, delta_P = log 1.10, delta_Q = 0.02); T_{a,f} = -log max_j p_j, else -inf.
T_T = the maximum over the six (ties: the earlier pair, then ARD->FSD). Reject iff T_T > c_T and the
model p-value <= 0.01, c_T = max(log 600, the development critical value).

CLASSIFICATION (reporting; bounds at a = 1/600, the guard's component level). ARD: L(beta_P),
L(beta_Q) > 0 and U(E^U_C) < d_C^2, U(E^U_Q) < d_Q^2. FSD: the epoch gate, L(E^F_C) > d_C^2,
L(E^F_Q) > d_Q^2 AND directional equivalence (-delta < L, U < delta for both slopes). "mixed" needs
AFFIRMATIVE evidence of both: material recurrence (the bounds and the epoch gate) and material
directional change (a bound outside the equivalence band). Everything else, including recurrence
with directional bounds spanning the band, or bounds without a passed gate, is "unresolved".

IDENTITIES. Worlds are paired across epochs BY ID: every epoch holds the same unique world ids
(WorldDesign.id), the slopes and the reference-source loadings are keyed by id; all are put in one
canonical (sorted) order before the paired draws. A NaN draw or margin is a numerical failure: the
analysis is unavailable with its error, never a non-exceedance; ht() marks it failure = "numerical"
(a calibration panel with one is a FAILED panel, repaired and rerun: never a non-rejection), apart from
the registered unavailability (a gate without a frozen calibration, failure None). Every window
intermediate (cumulative sums, window means, contrasts, ranges, energies) is checked finite before it
is compared: overflow is a failure, distinct from the registered +inf energies.
"""
from __future__ import annotations

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("RQ_PYLIB"):
    sys.path.insert(0, os.environ["RQ_PYLIB"])
import numpy as np  # noqa: E402

import recurrence  # noqa: E402
import rqlib  # noqa: E402
import stats  # noqa: E402

EPOCHS = ("E1", "E2", "E3")
PAIRS = (("E1", "E2"), ("E1", "E3"), ("E2", "E3"))
D_C, D_Q = recurrence.D_C, recurrence.D_Q
DELTA_P, DELTA_Q = stats.DELTA_P, stats.DELTA_Q
GUARD = math.log(6 / 0.01)
LEVEL = 1 / 600
KEYS = ("beta_P", "beta_Q", "EU_C", "EU_Q", "EF_C", "EF_Q")
MASK64 = (1 << 64) - 1


class TransitionError(Exception):
    pass


# ================================================================== vectorized SplitMix64
class VecSplitMix64:
    """rqlib.SplitMix64's exact sequence, vectorized (the generator is counter-based)."""
    GAMMA = np.uint64(0x9E3779B97F4A7C15)

    def __init__(self, seed):
        self.s = int(seed) & MASK64

    def next64(self, count):
        i = np.arange(1, count + 1, dtype=np.uint64)
        with np.errstate(over="ignore"):
            z = np.uint64(self.s) + i * self.GAMMA
            z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
            z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        self.s = (self.s + count * 0x9E3779B97F4A7C15) & MASK64
        return z ^ (z >> np.uint64(31))

    def below(self, n, count):
        """count draws of rqlib's unbiased below(n): the same outputs in the same order (a rejection,
        probability (2^64 mod n) / 2^64 per draw, falls back to the scalar generator)."""
        limit = (1 << 64) - ((1 << 64) % n)
        s0 = self.s
        x = self.next64(count)
        if limit < (1 << 64) and bool(np.any(x >= np.uint64(limit))):
            rng = rqlib.SplitMix64(s0)
            vals = [rng.below(n) for _ in range(count)]
            self.s = rng.s
            return np.array(vals, dtype=np.int64)
        return (x % np.uint64(n)).astype(np.int64)

    def normals(self, count):
        """count standard normals (Box-Muller cosine branch on two 53-bit uniforms per normal)."""
        x = self.next64(2 * count)
        u = (x >> np.uint64(11)).astype(np.float64) * (1.0 / (1 << 53))
        u1, u2 = 1.0 - u[0::2], u[1::2]
        return np.sqrt(-2.0 * np.log(u1)) * np.cos(2 * math.pi * u2)


def draw_streams(analysis, n, k, draws):
    """-> (world indices (draws, n), reference-source vectors (draws, k)): the paired resampling."""
    idx = VecSplitMix64(stats.stream_seed("H-T", analysis, "bootstrap")).below(n, draws * n).reshape(draws, n)
    xi = (VecSplitMix64(stats.stream_seed("H-T", analysis, "reference-source")).normals(draws * k).reshape(draws, k)
          if k else np.zeros((draws, 0)))
    return idx, xi


# ================================================================== per-world epoch quantities
def _bad(x, where, what, B):
    """TransitionError on any nonfinite entry of x (last axis: the B draws)."""
    bad = ~np.isfinite(np.asarray(x, float))
    if bad.any():
        cols_ = np.flatnonzero(bad.reshape(-1, B).any(axis=0))
        raise TransitionError(f"{where}: a nonfinite {what} in {len(cols_)} draw(s), first {int(cols_[0])}")
    return x


def cumulative(rho, where):
    """The per-draw cumulative sums of the window residuals (rows: chain positions, columns: draws),
    checked (#68 round 3 P2: finite residuals can overflow their cumulative sum, and inf - inf would then
    make every window comparison false, i.e. a failed selection read as zero energy)."""
    B = rho.shape[1]
    with np.errstate(over="ignore", invalid="ignore"):
        cs = np.vstack([np.zeros((1, B)), np.cumsum(rho, axis=0)])
    return _bad(cs, where, "window cumulative sum", B)


def windows(cs, lo, hi, kk, Rf, where):
    """Rule 6 per draw from the cumulative sums: the five chain-window means, the reversal test (signed
    consecutive contrasts) and the return test (|v_k+2 - v_k| <= R_fit / 2), every intermediate checked
    finite before any comparison (#68 round 3 P2). -> (rev, ret), B booleans each."""
    B = cs.shape[1]
    cols = np.arange(B)[:, None]
    cnt = np.maximum(hi - lo, 1)
    with np.errstate(over="ignore", invalid="ignore"):
        v = (cs[hi, cols] - cs[lo, cols]) / cnt                             # B x 5
        d1 = v[:, 1:] - v[:, :-1]
        d2 = v[:, 2:] - v[:, :-2]
    _bad(np.asarray(Rf, float), where, "recurrent range", B)
    for x, what in ((v, "window mean"), (d1, "window contrast"), (d2, "window return contrast")):
        _bad(x.T, where, what, B)
    e = np.where((kk[:, None] + np.arange(5)[None, :]) % 2 == 0, 1.0, -1.0)
    rev = np.all(np.sign(e[:, 1:] - e[:, :-1]) * d1 > 0, axis=1)
    ret = np.all(np.abs(d2) <= np.asarray(Rf, float)[:, None] / 2, axis=1)
    return rev, ret


def energy(dbar, den, h, where):
    """r_h^2 per draw from the recurrent component dbar (m x B): its mean square, relative to the capture
    denominator squared for capture; a capture denominator <= 0 is the registered +inf. Overflow (of the
    squares, the range or the ratio) is a numerical failure, never the registered +inf (#68 round 3 P2)."""
    B = dbar.shape[1]
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        ms = np.mean(dbar ** 2, axis=0) if len(dbar) else np.zeros(B)
        Rf = np.ptp(dbar, axis=0) if len(dbar) else np.zeros(B)
    _bad(ms, where, "squared recurrent component", B)
    _bad(Rf, where, "recurrent range", B)
    if h != "C":
        return ms, Rf
    pos = den > 0
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        r2 = ms / np.where(pos, den, 1.0) ** 2
    _bad(np.where(pos, r2, 0.0), where, "capture energy", B)
    return np.where(pos, r2, np.inf), Rf


def eu_observed(obs):
    """A world's observed E^U contribution from its epoch analysis: (max_P r_C^2, max_P r_Q^2) when every
    candidate period is supported, else (+inf, +inf) (the epoch cannot be ARD-certified), with the
    unsupported periods."""
    if obs["periods"] and all(r["supported"] for r in obs["periods"]):
        return (max(r["r_C"] ** 2 for r in obs["periods"]), max(r["r_Q"] ** 2 for r in obs["periods"])), []
    return (math.inf, math.inf), [r["P"] for r in obs["periods"] if not r["supported"]]


def world_epoch(wd, y, loads, xi):
    """One world, one epoch: observed analysis (recurrence.analyze_world) plus, over the bootstrap draws,
    per-candidate G_C, G_Q (rule 6 at each draw's phase) and r_C^2, r_Q^2 under the common reference-
    source draw xi (draws x k). loads: {"C": L (n_ref_obs x k), "Q": ...} on the full reference vectors
    (None: no shared-reference uncertainty). -> dict of observed values and per-draw arrays."""
    obs = recurrence.analyze_world(wd, y)
    B = xi.shape[0]
    P_all = [r["P"] for r in obs["periods"]]
    static = [set(r["fails"]) <= {"6-windows", "capture-denominator"} for r in obs["periods"]]
    G = {h: np.zeros((len(P_all), B), bool) for h in "CQ"}
    r2 = {h: np.full((len(P_all), B), np.nan) for h in "CQ"}
    for h in "CQ":
        rd = wd.ref[h]
        if not hasattr(rd, "proj") or not any(static):
            continue
        yh = np.asarray(y["ref"][h], float)[rd.mask]
        Lh = loads.get(h) if loads else None
        Lm = np.asarray(Lh, float)[rd.mask] if Lh is not None else None
        where = f"world {wd.id} ({wd.scope}, readout {h})"
        if not np.all(np.isfinite(yh)) or (Lm is not None and not np.all(np.isfinite(Lm))) \
                or not np.all(np.isfinite(xi)):
            raise TransitionError(f"{where}: a nonfinite response, loading or reference-source draw")

        def lin(op):                       # op y + (op L) xi_b for every draw b -> (..., B)
            base = op @ yh
            if Lm is None:
                return np.repeat(np.asarray(base, float)[..., None], B, axis=-1)
            return np.asarray(base, float)[..., None] + np.asarray(op @ Lm) @ xi.T

        def finite(x, what, P=None):       # (#68 round 2: a failed perturbation is a failure, BEFORE any gate)
            bad = ~np.isfinite(x)
            if bad.any():
                cols_ = np.flatnonzero(bad.reshape(-1, B).any(axis=0))
                raise TransitionError(f"{where}{'' if P is None else f' P={P:g}'}: a nonfinite perturbed {what} "
                                      f"in {len(cols_)} draw(s), first {int(cols_[0])}")
            return x
        rho, den = finite(lin(rd.rbar), "window residual"), finite(lin(rd.mean_op), "capture denominator")
        cs = cumulative(rho, where)
        for i, P in enumerate(P_all):
            if not static[i]:
                continue
            hm = rd.harm[P]
            b = finite(hm.Sqinv @ lin(hm.WQ.T), "harmonic coordinate", P)     # 2 x B (the stable basis)
            a = finite(hm.Rinv @ b, "harmonic coefficient", P)
            dbar = finite(hm.avgQ @ b, "recurrent component", P)
            with np.errstate(over="ignore"):
                A = np.hypot(a[0], a[1])
            finite(A, "harmonic amplitude", P)
            phi = np.arctan2(a[1], a[0])
            r2[h][i], Rf = energy(dbar, den, h, f"{where} P={P:g}")
            lo, hi, kk, ok = rd.tables[P].lookup(phi)                         # B x 5 (chain() exactly)
            rev, ret = windows(cs, lo, hi, kk, Rf, f"{where} P={P:g}")
            g = ok & (A > 0) & rev & ret
            if h == "C":
                g &= den > 0
            G[h][i] = g
    for h in "CQ":                         # (every evaluated draw: a value or the registered +inf, never NaN)
        ev = np.array(static, bool)
        if np.isnan(r2[h][ev]).any():
            raise TransitionError(f"world {wd.id} ({wd.scope}): a NaN {h} energy draw")
    JC = np.array([r.get("J_C", 0.0) for r in obs["periods"]])
    JQ = np.array([r.get("J_Q", 0.0) for r in obs["periods"]])
    s = (G["C"] & G["Q"]) * np.minimum(JC, JQ)[:, None]                         # nP x B
    best = s.max(axis=0) if len(P_all) else np.zeros(B)
    sel = s.argmax(axis=0) if len(P_all) else np.zeros(B, int)                 # (first max: the smaller P)
    g = best > 0
    cols = np.arange(B)
    out = {"obs": obs, "periods": P_all,
           "selC": np.where(g, r2["C"][sel, cols], 0.0), "selQ": np.where(g, r2["Q"][sel, cols], 0.0)}
    out["EU_obs"], unsup = eu_observed(obs)
    if obs["periods"] and not unsup:
        out["maxC"] = np.max(r2["C"], axis=0)
        out["maxQ"] = np.max(r2["Q"], axis=0)
    else:
        out["maxC"] = out["maxQ"] = np.full(B, np.inf)
        out["EU_unsupported"] = unsup
    return out


def epoch_components(per_world, betas, idx=None):
    """Observed epoch components from per-world records (world_epoch) and slopes {"P": [...], "Q": [...]}
    (same world order); with idx (draws x n) also their paired bootstrap draws."""
    n = len(per_world)
    res = recurrence.hf([dict(w["obs"], id=str(i)) for i, w in enumerate(per_world)])
    bP, bQ = np.asarray(betas["P"], float), np.asarray(betas["Q"], float)
    obs = {"beta_P": float(bP.mean()), "beta_Q": float(bQ.mean()),
           "EU_C": float(np.mean([w["EU_obs"][0] for w in per_world])),
           "EU_Q": float(np.mean([w["EU_obs"][1] for w in per_world])),
           "EF_C": res["E_C"], "EF_Q": res["E_Q"], "S": res["S_F"], "available": res["available"]}
    if idx is None:
        return obs, None, res
    B = idx.shape[0]
    cols = np.arange(B)[:, None]

    def boot(mat):                     # mat: n x B -> mean over the drawn worlds per draw
        return np.mean(mat[idx, cols], axis=1)
    draws = {"beta_P": np.mean(bP[idx], axis=1), "beta_Q": np.mean(bQ[idx], axis=1),
             "EU_C": boot(np.vstack([w["maxC"] for w in per_world])),
             "EU_Q": boot(np.vstack([w["maxQ"] for w in per_world])),
             "EF_C": boot(np.vstack([w["selC"] for w in per_world])),
             "EF_Q": boot(np.vstack([w["selQ"] for w in per_world]))}
    return obs, draws, res


# ================================================================== the complete maximum
def margins(c, a, f):
    """The fourteen (name, value) margins of candidate ARD = a, FSD = f from component records c[e]
    (scalars, or arrays of draws: the same linear functions)."""
    A, F = c[a], c[f]
    return [("beta_P[a]", A["beta_P"]), ("beta_Q[a]", A["beta_Q"]),
            ("dC2-EU_C[a]", D_C ** 2 - A["EU_C"]), ("dQ2-EU_Q[a]", D_Q ** 2 - A["EU_Q"]),
            ("EF_C[f]-dC2", F["EF_C"] - D_C ** 2), ("EF_Q[f]-dQ2", F["EF_Q"] - D_Q ** 2),
            ("dP-beta_P[f]", DELTA_P - F["beta_P"]), ("dP+beta_P[f]", DELTA_P + F["beta_P"]),
            ("dQ-beta_Q[f]", DELTA_Q - F["beta_Q"]), ("dQ+beta_Q[f]", DELTA_Q + F["beta_Q"]),
            ("beta_P[a]-beta_P[f]", A["beta_P"] - F["beta_P"]), ("beta_Q[a]-beta_Q[f]", A["beta_Q"] - F["beta_Q"]),
            ("EF_C[f]-EU_C[a]", F["EF_C"] - A["EU_C"]), ("EF_Q[f]-EU_Q[a]", F["EF_Q"] - A["EU_Q"])]


def candidates():
    """The six candidates in tie-break order: (ARD epoch, FSD epoch, direction)."""
    out = []
    for e, f in PAIRS:
        out.append((e, f, "ARD->FSD"))
        out.append((f, e, "FSD->ARD"))
    return out


def tail_p(m, draws):
    """p_m = (1 + #{m*_b - m >= m}) / (B + 1) (ties count). A NaN draw (or observed margin) is a
    numerical failure, never a non-exceedance (#68 review 3): TransitionError (the analysis is then
    unavailable). Signed infinities are values (an unsupported E^U draw is +inf by definition)."""
    d = np.asarray(draws, float)
    if not math.isfinite(m) or np.isnan(d).any():
        raise TransitionError(f"a nonfinite margin or NaN bootstrap draw ({int(np.isnan(d).sum())} of {len(d)})")
    with np.errstate(invalid="ignore"):
        x = d - m
    if np.isnan(x).any():                      # (inf - inf cannot arise: m is finite)
        raise TransitionError("a NaN centred draw")
    return (1 + int(np.sum(x >= m))) / (len(d) + 1)


def candidate_scores(obs, draws, gates):
    """-> [per-candidate records] with T = -log max p, or -inf when the FSD gate or an observed margin
    fails (draws needed only for the eligible ones)."""
    out = []
    for a, f, direction in candidates():
        ms = margins(obs, a, f)
        rec = {"ARD": a, "FSD": f, "direction": direction, "margins": {k: float(v) for k, v in ms},
               "gate": bool(gates.get(f, False)), "T": -math.inf}
        if rec["gate"] and all(v > 0 for _, v in ms):
            if draws is None:
                raise TransitionError("an eligible candidate needs the bootstrap draws")
            md = dict(margins(draws, a, f))
            rec["p"] = {k: tail_p(v, md[k]) for k, v in ms}
            rec["T"] = -math.log(max(rec["p"].values()))
        out.append(rec)
    return out


def ht_statistic(obs, draws, gates):
    """T_T, the winning candidate (ties: earlier pair, then ARD->FSD), all six candidates."""
    cands = candidate_scores(obs, draws, gates)
    best = None
    for c in cands:
        if c["T"] > -math.inf and (best is None or c["T"] > best["T"]):
            best = c
    return {"T_T": best["T"] if best else -math.inf, "winner": best, "candidates": cands}


def basic_bounds(theta, draws, a=LEVEL):
    """(L_{1-a}, U_{1-a}) one-sided basic bootstrap bounds."""
    if not math.isfinite(theta):                  # (an unsupported E^U: no finite bound)
        return theta, theta
    d = np.sort(np.asarray(draws, float) - theta)
    return theta - stats.Q(d, 1 - a), theta - stats.Q(d, a)


def canonical_ids(epochs, betas, loads=None):
    """The world ids of an H-T analysis, validated (#68 review 11): unique within every epoch, the same
    set in every epoch, slopes keyed by exactly those ids, loadings only for them -> sorted ids."""
    sets = {}
    for e in EPOCHS:
        ws = [wd.id for wd, _ in epochs[e]]
        if len(set(ws)) != len(ws):
            raise TransitionError(f"{e}: a world id occurs twice")
        sets[e] = set(ws)
    ids = sorted(sets[EPOCHS[0]], key=str)
    for e in EPOCHS:
        if sets[e] != set(ids):
            raise TransitionError(f"{e}: the same qualifying worlds (by id) must enter every epoch")
        for h in ("P", "Q"):
            b = betas[e][h]
            if not isinstance(b, dict) or set(b) != set(ids):
                raise TransitionError(f"{e}: the {h} slopes must be keyed by exactly the epoch's world ids")
    if loads is not None and not set(loads) <= set(ids):
        raise TransitionError("reference-source loadings for worlds that are not in the analysis")
    return ids


def classify(obs_e, draws_e, gate, a=LEVEL):
    """An epoch's dominance class (reporting): "ARD", "FSD", "mixed" or "unresolved"."""
    if draws_e is None:
        return {"class": "unresolved", "reason": "no bootstrap draws"}
    if any(np.isnan(np.asarray(draws_e[k], float)).any() for k in KEYS):
        return {"class": "unresolved", "reason": "a NaN bootstrap draw (a numerical failure)"}
    b = {k: basic_bounds(obs_e[k], draws_e[k], a) for k in KEYS}
    ard = b["beta_P"][0] > 0 and b["beta_Q"][0] > 0 and b["EU_C"][1] < D_C ** 2 and b["EU_Q"][1] < D_Q ** 2
    rec = b["EF_C"][0] > D_C ** 2 and b["EF_Q"][0] > D_Q ** 2
    equiv = (-DELTA_P < b["beta_P"][0] and b["beta_P"][1] < DELTA_P
             and -DELTA_Q < b["beta_Q"][0] and b["beta_Q"][1] < DELTA_Q)
    material_dir = (b["beta_P"][0] > DELTA_P or b["beta_P"][1] < -DELTA_P
                    or b["beta_Q"][0] > DELTA_Q or b["beta_Q"][1] < -DELTA_Q)
    out = {"bounds": {k: list(v) for k, v in b.items()},
           "rms_bounds": {k: [math.sqrt(max(v[0], 0.0)), math.sqrt(max(v[1], 0.0)) if math.isfinite(v[1]) else math.inf]
                          for k, v in b.items() if k.startswith("E")},
           "recurrent": bool(rec and gate), "recurrence_bounds": bool(rec), "gate": bool(gate),
           "directional": "equivalent" if equiv else "material" if material_dir else "unresolved"}
    if ard:
        out["class"] = "ARD"
    elif rec and gate and equiv:
        out["class"] = "FSD"
    elif rec and gate and material_dir:        # (#68 review 8: AFFIRMATIVE recurrent and directional evidence)
        out["class"] = "mixed"
    else:
        out["class"] = "unresolved"
    return out


def ht(epochs, betas, gates, loads=None, k=0, analysis="main", draws=stats.B_BOOT, c_T=GUARD, p_model=None,
       report=True):
    """The complete H-T analysis. epochs: {e: [(WorldDesign for e, responses y)]} (the same unique world
    ids in every epoch, any order); betas: {e: {"P": {world id: slope}, "Q": {world id: slope}}}; gates:
    {e: the epoch's calibrated recurrence-detection gate (bool)}; loads: {world id: {"C": L, "Q": L}}
    reference-source loadings (k columns). Bootstrap draws are computed when a candidate is eligible or
    report is set."""
    ids = canonical_ids(epochs, betas, loads)
    n = len(ids)
    missing = [e for e in EPOCHS if gates.get(e) is None]
    if missing:                                        # (H.12: every gate H-T requires needs a passing calibration)
        return {"available": False, "reject": False, "T_T": None, "winner": None, "candidates": [], "worlds": ids,
                "error": f"the recurrence gate of {missing} lacks a passing frozen calibration", "failure": None,
                "c_T": max(GUARD, c_T),
                "p_model": p_model, "phase_support": {}, "EU_unsupported": {}}
    for e in EPOCHS:                                   # (canonical order: one index = one world everywhere)
        by = {wd.id: (wd, y) for wd, y in epochs[e]}
        epochs = dict(epochs, **{e: [by[w] for w in ids]})
    bet = {e: {h: [float(betas[e][h][w]) for w in ids] for h in ("P", "Q")} for e in EPOCHS}
    bad = [f"{e}/{h}/{w}" for e in EPOCHS for h in ("P", "Q") for w, v in zip(ids, bet[e][h]) if not math.isfinite(v)]
    if bad:
        return {"available": False, "reject": False, "T_T": None, "error": f"nonfinite slopes: {bad[:5]}",
                "failure": "numerical",
                "winner": None, "candidates": [], "worlds": ids, "c_T": max(GUARD, c_T), "p_model": p_model,
                "phase_support": {}, "EU_unsupported": {}}
    idx, xi = draw_streams(analysis, n, k, draws)
    obs, dr, res = {}, {}, {}
    try:
        per = {e: [world_epoch(wd, y, (loads or {}).get(w), xi) for w, (wd, y) in zip(ids, epochs[e])]
               for e in EPOCHS}
        for e in EPOCHS:
            obs[e], dr[e], res[e] = epoch_components(per[e], bet[e], idx)
        stat = ht_statistic(obs, dr, gates)
    except TransitionError as err:          # (a numerical failure anywhere: unavailable, never a rejection)
        return {"available": False, "reject": False, "T_T": None, "error": str(err), "failure": "numerical",
                "winner": None,
                "candidates": [], "components": obs, "c_T": max(GUARD, c_T), "p_model": p_model, "worlds": ids,
                "phase_support": {e: res[e]["phase_support"] for e in res}, "EU_unsupported": {}}
    c_T = max(GUARD, c_T)
    out = {"T_T": stat["T_T"], "c_T": c_T, "p_model": p_model, "winner": stat["winner"], "worlds": ids,
           "candidates": stat["candidates"], "components": obs, "available": all(res[e]["available"] for e in EPOCHS),
           "reject": stat["T_T"] > c_T and p_model is not None and p_model <= stats.DETECT_ALPHA,
           "phase_support": {e: res[e]["phase_support"] for e in EPOCHS},
           "EU_unsupported": {e: {str(i): w["EU_unsupported"] for i, w in enumerate(per[e]) if "EU_unsupported" in w}
                              for e in EPOCHS}}
    if stat["winner"]:
        w = stat["winner"]
        out["bracket"] = {("E1", "E2"): "F1-125M", ("E2", "E3"): "75-200M",
                          ("E1", "E3"): "F1-200M"}[tuple(sorted((w["ARD"], w["FSD"])))]
    if report:
        out["classes"] = {e: classify(obs[e], dr[e], gates.get(e, False)) for e in EPOCHS}
    if not out["available"]:
        out["reject"] = False
        out["reasons"] = {e: res[e]["reasons"] for e in EPOCHS if not res[e]["available"]}
    return out

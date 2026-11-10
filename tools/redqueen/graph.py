#!/usr/bin/env python3
"""graph.py: the Red Queen map graph of design v4 (§4.1-4.5, §5.1, §7.1; Annex H D7 rules 34, 40) and its
pre-seal reports, availability masks and executable graphs (Annex H D6 rule 27).

    graph.py build --out DIR [--namespace NS] [--registry STUDY/config/worlds.json]
                   [--no-train-matchings] [--snapshot-topup 6] [--ab-topup 8 [--ab-topup-mode fitting|c]]
    graph.py report --graph DIR/graph.jsonl.gz [--out report.json]
    graph.py mask --graph DIR/graph.jsonl.gz --block worlds_block.json --registry STUDY/config/worlds.json
                  (--root STUDY [--archive-root AR] | --no-rederive) --out mask.json
    graph.py executable --graph DIR/graph.jsonl.gz --mask mask.json --out DIR2   (DIR2 != DIR)

The graph is the set of (prey population, predator population) pairs the assays measure for the
map, with each pair's family, split role (the roles of plan.py's design /2 edges: training,
validation, test, support) and horizon class. Populations are snapshots "Q:<world>:<t>" (prey) and
"P:<world>:<t>" (predators; C worlds only), t = 0 (F1) .. 200 (200M steps), and the external
references "RQ:<k>", "RP:<k>" (eight per guild: registered reference slots; the selected sentinel
snapshots are a deterministic relabelling, §4.2). Worlds: a registry's (worlds.json: ids,
treatments, blocks; its sha256 is recorded) or the registered layout's synthetic ids. THE LAYOUT is
the registered one only (D7 rule 34): eight blocks of 4C + 2A + 2B (64 worlds: 32 C, 16 A, 16 B);
any other is refused. Everything is derived from --namespace: the same inputs give the same bytes.

SPLITS (§7.1, §5.1; D7 rule 40). C worlds 20 training / 6 validation / 6 test; A and B 10/2/4 each
(the same frozen, outcome-independent permutation per treatment). In every
training C world 20 joint snapshot times are held out (10 snapshot-validation, 10 snapshot-test;
two per 20M bin, residues mod 5 balanced, F1 never). 12 fork worlds (2 training, 4 validation, all
6 test) and among them 8 intensive worlds (2, 2, 4).

FAMILIES (v4 §4.5 with D7 rule 40's 64-world quotas; quotas checked; no pair twice).
  within      every C world's coarse matrix (F1, 5M, ..., 200M: 41 x 41), its fine windows (F1-20M,
              90-110M, 180-200M: offsets 0, +-1, +-2, +-4) and the intensive worlds' complete fine
              windows: 72,992
  ref_prey    C prey x the four predator references of its block: 25,728
  ref_pred    C predators x the four prey references of its block: 25,728
  ref_ab      A/B prey x the block's four predator references: 25,728
  ref_grid    the 8 x 8 reference grid: 64
  cross       eight edge-disjoint C matchings (prey world w -> predator world w + s_m, a distinct
              shift per matching; two at the same time, six at a per-world random time permutation):
              51,456
  ab_to_c     A/B prey x four C predators (distinct worlds; held-out A/B worlds: training C
              predators outside the snapshot holdouts): 25,728
  support_c   four more training opponents (eligible training states) for every held-out-world C
              population, both guilds: 19,296
  support_ab  two more training C predators for every held-out A/B prey snapshot: 4,824
  train_match four edge-disjoint matchings of the 3,620 eligible training states (20 training C
              worlds x 201 - 400 snapshot holdouts), across worlds, new pairs only (v4 §4.4): 14,480
  total 266,024 (251,544 with --no-train-matchings; D7 rule 40's base graph total), and the default
  top-ups (no fixed quota: their counts are what the generated graph gives):
  support_snap every snapshot-holdout population up to six training opponents in its support,
              new support pairs to eligible training states of other worlds: 1,301
  ab_train_c  every training A/B prey snapshot up to eight fitting pairs (its four references
              included; --ab-topup-mode c: eight training C opponents) with new training pairs to
              eligible training C predators: 8,116 (20 training A/B worlds; 3,877 on the former 48)
  The top-ups are the recovery comparison's choice on the former 48-world graph (rank 4 identifiable
  for every population, the noisy A/B and snapshot-test errors down; there +5,178 pairs); on the 64-world
  graph they add 9,417 pairs (about 0.44 production days at 5k), and its exact-graph recovery is to be
  re-run (D7 rule 40: recompute the top-ups and support reports on the generated graph);
  --snapshot-topup 0 --ab-topup 0 gives the v4 graph alone (266,024 pairs: the lag7 probe below is
  part of the registered top-up switch). They come after every registered family, which they leave
  unchanged.
  lag7_probe  (v4 amendment, 2026-11-07) every NON-intensive C world's coarse prey snapshots (F1, 5M,
              ..., 200M) against its own predators 7M later and 7M earlier, where they exist: 78 per
              world, 24 x 78 = 1,872 within-world pairs (about 11,200 5k trajectories at R = 6, about
              2 nominal hours). Why: Annex H.3.3's support rule 4 (lag phases in all four quadrants,
              largest circular gap <= pi/2) fails for P = 15M in every non-intensive world (its lags
              mod 15 miss 6-9: a 120-degree gap); +-7M lags close it (largest gap 48 degrees), so the
              15M candidate is supported in all 32 C worlds, with statistical weight. Within-world
              pairs: never in the Level-1 fit (as "within"); roles by endpoint; the randomized 1/8
              long pool. It is on with the top-ups and off without them (--lag-probe M overrides:
              0 gives the top-ups without it). It comes after every other family, which it leaves
              unchanged.

ROLES. A pair is "support" when it is declared placement support of a held-out population: its four
reference pairs, two of its existing matching pairs with an eligible training opponent (world
holdouts) or up to six (snapshot holdouts), every ab_to_c pair of a held-out A/B world, and the
support_c / support_ab / support_snap pairs. Otherwise a pair inherits its most held-out endpoint:
test before validation before training (references count as training).

HORIZONS (§4.6): the reference grid "long"; support_c, support_ab, train_match and the top-ups
"short"; every other family is in the randomized 1/8 long pool (no horizon: plan.py's
pre-randomized long subset).

AVAILABILITY (mask, executable; Annex H D6 rule 27). The built graph is the IMMUTABLE scheduled
topology (a graph built with --registry records the registry's namespace and uuids, order-independent;
write never replaces a published graph's bytes). `mask` reads it (verified against its edges_sha256), the
study's REGISTRY and a worlds block (worlds.py design-block: per world its retained attempt's evidence
under evidence.py's rules, the first terminal boundary valid_before, the frontier, the explicit burn-in
disposition and every archived object checked against the line of descent and re-hashed). The block
must be the registry's (its hash; the graph's, registry's and block's world ids, treatments, blocks and
uuids equal; every attempt registered and its identity attempt_uuid; its evidence consistent: refused
otherwise), and with --root it is RE-DERIVED from the study's evidence and must be the same. The mask
is separate and deterministic: every unavailable snapshot (world x time; F1 = frame 1, t = t x 1M) with
its cause, uuid, attempt and snapshot uuid: pending FIRST for an unsettled burn-in disposition, then
biological (at or after the attempt's evidenced first guild zero), technical (at or after a refill, a
missing or damaged archive, or not archived / not evidenced in an ended attempt: repair it if possible)
or pending (not archived yet in a running one); every edge's exclusion (its endpoints' first of
biological, technical, pending; references are refsel.py's business, never masked here); counts by
family x role (scheduled, executable, biological, technical, pending), the attrition by world and the
verified sha256 of every available snapshot. `executable` RECOMPUTES the edge exclusions from the
mask's snapshots (refused if they differ) and writes the graph minus them into a new directory, roles,
families and horizons unchanged, its meta bound to the source graph and the mask (recovery.py, report
and plans consume it as they consume a graph). No endpoint is ever replaced by another world or time,
and a recovery or support failure never authorizes replacement edges.

The report (graph.py report) gives: family quotas, role x family counts, uniqueness, the support
counts of every held-out population, the fitting degree of every population and the connected
components of the fitting graph under four access rules (v4 with the new matchings; without them;
without them but with training within-world pairs, option (b); the forward-time rule, outcomes
through 120M), and the horizon pools.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import uuid
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rqlib  # noqa: E402

GRAPH_SCHEMA = "finfolk.redqueen.graph/1"
TIMES = tuple(range(201))
COARSE = tuple(range(0, 201, 5))
WINDOWS = ((0, 20), (90, 110), (180, 200))
OFFSETS = (0, 1, -1, 2, -2, 4, -4)
# (D7 rule 40: the 64-world quotas; ref_ab, ab_to_c and support_ab doubled with 16 A and 16 B worlds)
QUOTAS = {"within": 72_992, "ref_prey": 25_728, "ref_pred": 25_728, "ref_ab": 25_728, "ref_grid": 64,
          "cross": 51_456, "ab_to_c": 25_728, "support_c": 19_296, "support_ab": 4_824, "train_match": 14_480}
BASE_TOTAL = 266_024                # D7 rule 40's base graph total (with the training matchings)
LAYOUT = {"C": 4, "A": 2, "B": 2}   # per block, eight blocks (D7 rule 34)
BLOCKS = 8
SPLIT_SIZES = {"C": (20, 6, 6), "A": (10, 2, 4), "B": (10, 2, 4)}   # training / validation / test (D7 rule 40)
# (Codex #77 r1 P2-7) the HISTORICAL registered layouts an existing artifact may have, for re-validating frozen
# graphs (build makes the 64-world layout only): the 48-world graph of main 99b1e94, 8 x (4C + 1A + 1B)
HISTORICAL_LAYOUTS = {"48": {"C": 4, "A": 1, "B": 1}}
HISTORICAL_QUOTAS = {"48": {"within": 72_992, "ref_prey": 25_728, "ref_pred": 25_728, "ref_ab": 12_864, "ref_grid": 64,
                            "cross": 51_456, "ab_to_c": 12_864, "support_c": 19_296, "support_ab": 2_412,
                            "train_match": 14_480}}
# optional top-ups (no registered quota: their counts are what the options generate)
TOPUPS = ("support_snap", "ab_train_c")
LAG_PROBE = 7                       # (v4 amendment: the lag7_probe family; 0 = none)
FAMILIES = tuple(QUOTAS) + TOPUPS + ("lag7_probe",)
WITHIN = ("within", "lag7_probe")   # within-world families: never in the Level-1 (option a) fit
GLOBAL = ("ref_prey", "ref_pred", "ref_ab", "ref_grid", "cross", "ab_to_c", "support_c", "support_ab", "train_match") \
    + TOPUPS
HORIZON = {"ref_grid": "long", "support_c": "short", "support_ab": "short", "train_match": "short",
           "support_snap": "short", "ab_train_c": "short"}
REF_BASE = (0, 1, 2, 4)            # cyclic 4-of-8 subsets: every reference in exactly four blocks
FORWARD_LAST = 120                 # the forward-time rule's last fitted time (120M, §7.3)


class GraphError(Exception):
    pass


def Q(w, t):
    return f"Q:{w}:{t}"


def P(w, t):
    return f"P:{w}:{t}"


def parse(n):
    """'Q:C07:12' -> ('Q', 'C07', 12); 'RQ:3' -> ('RQ', None, 3)."""
    p = n.split(":")
    return (p[0], None, int(p[1])) if len(p) == 2 else (p[0], p[1], int(p[2]))


class Rng:
    def __init__(self, ns, *parts):
        self.r = rqlib.SplitMix64(rqlib.derive64(ns, *parts))

    def perm(self, items):
        items = list(items)
        self.r.shuffle(items)
        return items

    def below(self, n):
        return self.r.below(n)


def synthetic_worlds():
    """The registered layout's synthetic ids: per block b, C worlds C01.., A worlds A01.., B worlds B01.."""
    out = []
    for b in range(1, BLOCKS + 1):
        for t in ("C", "A", "B"):
            n = LAYOUT[t]
            out += [{"id": f"{t}{n * (b - 1) + i + 1:02d}", "treatment": t, "block": b} for i in range(n)]
    return out


def registry_worlds(path):
    reg = rqlib.read_json(path)
    return [{"id": w["id"], "treatment": w["treatment"], "block": w["block"]} for w in reg["worlds"]]


def registry_binding(path):
    """The identity a graph built from a registry records (Codex #77 r1 P1-1): its namespace and every world's uuid,
    ORDER-INDEPENDENT (a permuted registry still gives byte-identical artifacts); mask() checks the study's
    registry against it (the registry's bytes bind the worlds block and the mask)."""
    reg = rqlib.read_json(path)
    return {"namespace": reg.get("namespace"), "uuids": {w["id"]: w.get("uuid") for w in reg["worlds"]}}


def layout_problems(worlds, layout=None):
    """Why a world list is not the registered 64-world layout (D7 rule 34): 8 blocks of 4C + 2A + 2B (layout: another
    per-block allocation, a historical one)."""
    layout = layout or LAYOUT
    per = defaultdict(Counter)
    for w in worlds:
        per[w["block"]][w["treatment"]] += 1
    probs = []
    if sorted(per) != list(range(1, BLOCKS + 1)):
        probs.append(f"blocks {sorted(per)}, the registered layout has 1..{BLOCKS}")
    for b, c in sorted(per.items()):
        if dict(c) != layout:
            probs.append(f"block {b}: {dict(sorted(c.items()))}, the registered layout has {layout}")
    if len({w["id"] for w in worlds}) != len(worlds):
        probs.append("a world id twice")
    return probs


def layout_of(worlds):
    """"64" (the registered layout), a HISTORICAL_LAYOUTS name, or None."""
    if not layout_problems(worlds):
        return "64"
    return next((n for n, lay in HISTORICAL_LAYOUTS.items() if not layout_problems(worlds, lay)), None)


def splits(ns, worlds):
    """{world: "train" | "val" | "test"}, the fork and intensive sets, the snapshot holdouts."""
    probs = layout_problems(worlds)
    if probs:
        raise GraphError("not the registered 64-world layout (Annex H D7 rule 34): " + "; ".join(probs[:4]))
    by_t = defaultdict(list)
    for w in worlds:
        by_t[w["treatment"]].append(w["id"])
    split = {}
    for t, ids in sorted(by_t.items()):
        n = SPLIT_SIZES[t]
        if len(ids) != sum(n):
            raise GraphError(f"{len(ids)} {t} worlds, the layout needs {sum(n)}")
        ids = Rng(ns, "split", t).perm(sorted(ids))
        for i, wid in enumerate(ids):
            split[wid] = "train" if i < n[0] else "val" if i < n[0] + n[1] else "test"
    cs = sorted(by_t["C"])
    fork, intensive = [], []
    for s, nf, ni in (("train", 2, 2), ("val", 4, 2), ("test", 6, 4)):
        pool = Rng(ns, "fork", s).perm([w for w in cs if split[w] == s])
        fork += pool[:nf]
        intensive += pool[:ni]
    holdout = {}                   # (world, t) -> "val" | "test", training C worlds
    for w in cs:
        if split[w] != "train":
            continue
        r = Rng(ns, "snapshot-holdout", w)
        h = r.below(5)
        for k in range(10):        # 20M bins 1-20, 21-40, ...; two times with residues 2 apart mod 5
            ts = range(20 * k + 1, 20 * k + 21)
            picks = []
            for res in ((k + h) % 5, (k + h + 2) % 5):
                c = [t for t in ts if t % 5 == res]
                picks.append(c[r.below(len(c))])
            a, b = ("val", "test") if k % 2 == 0 else ("test", "val")
            holdout[(w, picks[0])] = a
            holdout[(w, picks[1])] = b
    return split, sorted(fork), sorted(intensive), holdout


SNAPSHOT_TOPUP, AB_TOPUP = 6, 8     # the recommended top-ups (the recovery comparison: 5,178 pairs)


def build(ns="rq2026-graph", worlds=None, train_matchings=True, snapshot_topup=SNAPSHOT_TOPUP, ab_topup=AB_TOPUP,
          ab_topup_mode="fitting", lag_probe=None):
    """-> the graph: {"schema", "namespace", "worlds", "split", "fork", "intensive", "holdout",
    "edges": [(prey, pred, family, role, horizon)], ...}.
    snapshot_topup N: every snapshot-holdout population with fewer than N training opponents among
    its support gets new support pairs to eligible training states of other worlds (support_snap).
    ab_topup N: every training A/B prey snapshot gets new training pairs to eligible training C
    predators (ab_train_c) until it has N fitting pairs (mode "fitting": its four reference pairs
    included) or N training C opponents (mode "c"). Both come after every registered family, which
    they leave unchanged. lag_probe None: part of the registered top-up switch (LAG_PROBE with any
    top-up, 0 with none: --snapshot-topup 0 --ab-topup 0 is the pure v4 graph); an int sets it."""
    if lag_probe is None:
        lag_probe = LAG_PROBE if (snapshot_topup or ab_topup) else 0
    worlds = sorted((dict(w) for w in (worlds or synthetic_worlds())), key=lambda w: w["id"])
    split, fork, intensive, holdout = splits(ns, worlds)
    block = {w["id"]: w["block"] for w in worlds}
    treat = {w["id"]: w["treatment"] for w in worlds}
    cs = sorted(w for w in treat if treat[w] == "C")
    abs_ = sorted(w for w in treat if treat[w] in ("A", "B"))
    train_c = [w for w in cs if split[w] == "train"]

    def status(n):
        g, w, t = parse(n)
        if w is None:
            return "train"
        if split[w] != "train":
            return split[w]
        return holdout.get((w, t), "train")

    def eligible(w, t):
        return treat[w] == "C" and split[w] == "train" and (w, t) not in holdout

    pairs = {}                    # (prey, pred) -> family
    support = set()

    def add(q, p, fam):
        if (q, p) in pairs:
            return False
        pairs[(q, p)] = fam
        return True

    # within-world backbone
    for w in cs:
        for s in COARSE:
            for t in COARSE:
                add(Q(w, s), P(w, t), "within")
        for lo, hi in WINDOWS:
            for s in range(lo, hi + 1):
                for o in OFFSETS:
                    t = s + o
                    if lo <= t <= hi:
                        add(Q(w, s), P(w, t), "within")
                if w in intensive:
                    for t in range(lo, hi + 1):
                        add(Q(w, s), P(w, t), "within")
    # references: cyclic 4-of-8 subsets per block, the slot labels permuted per guild
    labq, labp = Rng(ns, "ref-labels", "Q").perm(range(8)), Rng(ns, "ref-labels", "P").perm(range(8))
    sub_p = {b: [labp[(x + b) % 8] for x in REF_BASE] for b in range(1, 9)}
    sub_q = {b: [labq[(x + b + 3) % 8] for x in REF_BASE] for b in range(1, 9)}
    for w in cs + abs_:
        for t in TIMES:
            for k in sub_p[block[w]]:
                add(Q(w, t), f"RP:{k}", "ref_prey" if treat[w] == "C" else "ref_ab")
            if treat[w] == "C":
                for k in sub_q[block[w]]:
                    add(f"RQ:{k}", P(w, t), "ref_pred")
    for k in range(8):
        for m in range(8):
            add(f"RQ:{k}", f"RP:{m}", "ref_grid")
    # eight C cross-world matchings; the shifts are redrawn until every held-out C world meets at
    # least four training worlds in each direction; then EVERY held-out C population (world and
    # snapshot holdouts) must have at least two ELIGIBLE training opponents (training world, not a
    # held-out snapshot) in the existing matchings: a deterministic repair swaps time pairings inside
    # the time-randomized matchings (m >= 2; the two time-aligned ones untouched), each swap only
    # adding eligible opponents (shift redraws alone cannot reach zero shortfalls: about 8-18 per
    # attempt); a population that cannot be repaired fails the build
    nc = len(cs)
    for attempt in range(1000):
        shifts = Rng(ns, "cross-shifts", attempt).perm(range(1, nc))[:8]
        if (all(sum(split[cs[(i + d * s) % nc]] == "train" for s in shifts) >= 4
                for i, w in enumerate(cs) if split[w] != "train" for d in (1, -1))
                and all(sum(split[cs[(i + d * s) % nc]] == "train" for s in shifts[2:]) >= 2   # (the repairable ones)
                        for i, w in enumerate(cs) for d in (1, -1))):
            break
    else:
        raise GraphError("no cross-matching shifts give every held-out world four training opponents and every "
                         "C world two training partners among the time-randomized matchings")
    taus = {(m, w): (list(TIMES) if m < 2 else Rng(ns, "cross-time", m, w).perm(TIMES))
            for m in range(len(shifts)) for w in cs}
    partner = {(m, w): cs[(i + s) % nc] for m, s in enumerate(shifts) for i, w in enumerate(cs)}
    cnt = Counter()
    for (m, w), tw in taus.items():
        o = partner[(m, w)]
        for t in TIMES:
            q, p = Q(w, t), P(o, tw[t])
            sq, sp = status(q), status(p)
            if sq != "train" and sp == "train":
                cnt[q] += 1
            if sp != "train" and sq == "train":
                cnt[p] += 1
    heldpop = sorted(x for w in cs for t in TIMES for x in (Q(w, t), P(w, t)) if status(x) != "train")
    repairs = []

    def gains(q, p):                         # the eligible opponent each held-out endpoint of (q, p) gains
        d = defaultdict(int)
        sq, sp = status(q), status(p)
        if sq != "train" and sp == "train":
            d[q] += 1
        if sp != "train" and sq == "train":
            d[p] += 1
        return d
    for x in heldpop:
        g_, w, t = parse(x)
        while cnt[x] < 2:
            done = False
            for m in range(2, len(shifts)):
                if g_ == "Q":
                    v, o = w, partner[(m, w)]
                    tw = taus[(m, v)]
                    t0 = t
                    other = o
                else:
                    v = next(y for y in cs if partner[(m, y)] == w)
                    o = w
                    tw = taus[(m, v)]
                    t0 = tw.index(t)
                    other = v
                if split[other] != "train" or gains(Q(v, t0), P(o, tw[t0]))[x] > 0:
                    continue                     # (no training partner here, or already eligible here)
                for u in Rng(ns, "cross-repair", m, v, t0).perm(TIMES):
                    if u == t0:
                        continue
                    a, b = tw[t0], tw[u]
                    d = defaultdict(int)
                    for k, dv in gains(Q(v, t0), P(o, b)).items():
                        d[k] += dv
                    for k, dv in gains(Q(v, u), P(o, a)).items():
                        d[k] += dv
                    for k, dv in gains(Q(v, t0), P(o, a)).items():
                        d[k] -= dv
                    for k, dv in gains(Q(v, u), P(o, b)).items():
                        d[k] -= dv
                    if d[x] <= 0 or any(dv < 0 and cnt[y] + dv < 2 for y, dv in d.items() if y != x):
                        continue                 # (x must gain; nobody else may fall below two)
                    tw[t0], tw[u] = b, a
                    for k, dv in d.items():
                        cnt[k] += dv
                    repairs.append([m, v, t0, u])
                    done = True
                    break
                if done:
                    break
            if not done:
                raise GraphError(f"{x}: fewer than two eligible training opponents in the existing matchings, "
                                 "and no repair swap")
    matched = defaultdict(list)   # population -> [(matching, other endpoint)]
    for m, s in enumerate(shifts):
        for i, w in enumerate(cs):
            o = cs[(i + s) % len(cs)]
            tau = taus[(m, w)]
            for t in TIMES:
                q, p = Q(w, t), P(o, tau[t])
                if not add(q, p, "cross"):
                    raise GraphError(f"matching {m}: {q} x {p} twice")
                matched[q].append((m, p))
                matched[p].append((m, q))
    # A/B prey x four C predators
    held_ab = [w for w in abs_ if split[w] != "train"]
    elig_t = {w: [t for t in TIMES if eligible(w, t)] for w in train_c}
    for n, w in enumerate(abs_):
        pool = train_c if w in held_ab else cs
        for k in range(4):
            c = pool[(4 * n + k) % len(pool)]
            tau = Rng(ns, "ab-time", w, k).perm(TIMES)
            for t in TIMES:
                tt = elig_t[c][tau[t] % len(elig_t[c])] if w in held_ab else tau[t]
                if not add(Q(w, t), P(c, tt), "ab_to_c"):
                    raise GraphError(f"ab_to_c {w} {t} twice")
                if w in held_ab:
                    support.add((Q(w, t), P(c, tt)))
    # declared support of held-out populations: references and existing matchings
    for (q, p), fam in pairs.items():
        if fam.startswith("ref_") and fam != "ref_grid" and status(q if fam != "ref_pred" else p) != "train":
            support.add((q, p))
    for x, lst in matched.items():
        g, w, t = parse(x)
        sx = status(x)
        if sx == "train":
            continue
        quota = 2 if split[w] != "train" else 6
        if sum(status(y) == "train" for _, y in lst) < 2:
            raise GraphError(f"{x}: fewer than two eligible existing training opponents (v4 §4.4)")
        for m, y in sorted(lst):
            if quota and status(y) == "train":
                support.add((x, y) if g == "Q" else (y, x))
                quota -= 1
    # four more training opponents for every held-out-world C population; two for held-out A/B prey
    elig = [(w, t) for w in train_c for t in TIMES if eligible(w, t)]

    def new_opponents(x, guild, n, fam, tag, as_support=True):
        r = Rng(ns, "support", tag, x)
        own = parse(x)[1]
        got, tries = 0, 0
        while got < n:
            tries += 1
            if tries > 10_000:
                raise GraphError(f"{x}: no new support opponent")
            w2, t2 = elig[r.below(len(elig))]
            if w2 == own:                    # (another world's: never an own-world pair)
                continue
            q, p = (x, P(w2, t2)) if guild == "Q" else (Q(w2, t2), x)
            if add(q, p, fam):
                if as_support:
                    support.add((q, p))
                got += 1
    for w in cs:
        if split[w] == "train":
            continue
        for t in TIMES:
            new_opponents(Q(w, t), "Q", 4, "support_c", "c")
            new_opponents(P(w, t), "P", 4, "support_c", "c")
    for w in held_ab:
        for t in TIMES:
            new_opponents(Q(w, t), "Q", 2, "support_ab", "ab")
    # four training-only cross-world matchings of the eligible training states
    if train_matchings:
        n = len(elig)

        def ok(i, j):
            (w1, t1), (w2, t2) = elig[i], elig[j]
            return w1 != w2 and (Q(w1, t1), P(w2, t2)) not in pairs
        for m in range(4):
            r = Rng(ns, "train-match", m)
            perm = r.perm(range(n))
            bad = [i for i in range(n) if not ok(i, perm[i])]
            while bad:               # repair by swaps that leave both positions valid
                i = bad.pop()
                if ok(i, perm[i]):
                    continue
                for _ in range(10_000):
                    j = r.below(n)
                    if j != i and ok(i, perm[j]) and ok(j, perm[i]):
                        perm[i], perm[j] = perm[j], perm[i]
                        break
                else:
                    raise GraphError(f"train_match {m}: no valid opponent for {elig[i]}")
            for i in range(n):
                (w1, t1), (w2, t2) = elig[i], elig[perm[i]]
                if not add(Q(w1, t1), P(w2, t2), "train_match"):
                    raise GraphError("train_match: a pair twice")
    if snapshot_topup:                       # snapshot holdouts up to N training opponents in support
        have = Counter()
        for q, p in support:
            for x, y in ((q, p), (p, q)):
                if parse(y)[1] is not None and parse(x)[1] is not None and split[parse(x)[1]] == "train" \
                        and status(x) != "train":
                    have[x] += 1
        for (w, t) in sorted(holdout):
            for x, guild in ((Q(w, t), "Q"), (P(w, t), "P")):
                if snapshot_topup > have[x]:
                    new_opponents(x, guild, snapshot_topup - have[x], "support_snap", "snap")
    if ab_topup:                             # training A/B prey up to N fitting pairs / C opponents
        c_opp = Counter(q for (q, p), fam in pairs.items()
                        if fam == "ab_to_c" and eligible(parse(p)[1], parse(p)[2]))
        for w in abs_:
            if split[w] != "train":
                continue
            for t in TIMES:
                x = Q(w, t)
                need = ab_topup - c_opp[x] - (4 if ab_topup_mode == "fitting" else 0)
                if need > 0:
                    new_opponents(x, "Q", need, "ab_train_c", "ab-train", as_support=False)
    if lag_probe:                            # (v4 amendment) the +-lag_probe M within-world probes
        for w in cs:
            if w in intensive:
                continue
            for s_ in COARSE:
                for t in (s_ + lag_probe, s_ - lag_probe):
                    if TIMES[0] <= t <= TIMES[-1] and not add(Q(w, s_), P(w, t), "lag7_probe"):
                        raise GraphError(f"lag7_probe {w} {s_}->{t}: the pair exists")
    order = {"test": 2, "val": 1, "train": 0}
    role_name = {2: "test", 1: "validation", 0: "training"}
    edges = []
    for (q, p), fam in pairs.items():
        if (q, p) in support:
            role = "support"
        else:
            role = role_name[max(order[status(q)], order[status(p)])]
        edges.append((q, p, fam, role, HORIZON.get(fam)))
    edges.sort(key=lambda e: (FAMILIES.index(e[2]), e[0], e[1]))
    return {"schema": GRAPH_SCHEMA, "namespace": ns, "train_matchings": train_matchings,
            "topups": {"snapshot": snapshot_topup, "ab": ab_topup, "ab_mode": ab_topup_mode},
            "lag_probe": lag_probe,
            "worlds": worlds, "split": split, "fork": fork, "intensive": intensive,
            "holdout": {f"{w}:{t}": v for (w, t), v in sorted(holdout.items())},
            "ref_subsets": {"predator_refs_of_block": sub_p, "prey_refs_of_block": sub_q},
            "cross_shifts": {"shifts": shifts, "attempt": attempt, "repair_swaps": len(repairs),
                             "repairs": repairs},
            "edges": edges}


def check_quotas(g):
    """The registered quotas of the graph's OWN layout (Codex #77 r1 P2-7: a frozen historical 48-world graph is
    checked against its layout's, the 64-world one against D7 rule 40's)."""
    lay = layout_of(g["worlds"])
    if lay is None:
        return ["not a registered layout (64, or a historical " + ", ".join(HISTORICAL_LAYOUTS) + "): "
                + "; ".join(layout_problems(g["worlds"])[:3])]
    table = QUOTAS if lay == "64" else HISTORICAL_QUOTAS[lay]
    c = Counter(e[2] for e in g["edges"])
    probs = [f"{f}: {c.get(f, 0)} pairs, the design has {n}" for f, n in table.items()
             if (f != "train_match" or g["train_matchings"]) and c.get(f, 0) != n]
    if len({(e[0], e[1]) for e in g["edges"]}) != len(g["edges"]):
        probs.append("a pair occurs twice")
    if g.get("lag_probe"):                   # 78 per non-intensive C world (41 coarse times, +-7M where they fit)
        n = sum(1 for w in g["worlds"] if w["treatment"] == "C" and w["id"] not in g["intensive"])
        want = n * sum((0 <= s + d <= 200) for s in COARSE for d in (g["lag_probe"], -g["lag_probe"]))
        if c.get("lag7_probe", 0) != want:
            probs.append(f"lag7_probe: {c.get('lag7_probe', 0)} pairs, the amendment has {want}")
    return probs


def write(g, d):
    """Write a graph into d. A published graph is IMMUTABLE (Codex #77 r1 P2-8): existing files with other bytes
    are never replaced (GraphError, nothing written); the same bytes again are a no-op."""
    meta = {k: v for k, v in g.items() if k != "edges"}
    meta["edges"] = len(g["edges"])
    buf = "".join(json.dumps({"prey": e[0], "pred": e[1], "family": e[2], "role": e[3], "horizon": e[4]},
                             sort_keys=True, separators=(",", ":")) + "\n" for e in g["edges"]).encode()
    raw = gzip.compress(buf, mtime=0)
    meta["edges_sha256"] = rqlib.sha256_bytes(buf)
    meta["tool_sha256"] = rqlib.sha256_file(os.path.abspath(__file__))
    files = {"graph.jsonl.gz": raw, "graph.meta.json": rqlib.canonical(meta)}
    for name, data in files.items():
        p = os.path.join(d, name)
        if os.path.exists(p) and rqlib.read_bytes(p) != data:
            raise GraphError(f"{p} exists with other bytes: a published graph is never replaced (write elsewhere)")
    os.makedirs(d, exist_ok=True)
    for name, data in files.items():
        rqlib.write_durable(os.path.join(d, name), data)
    return meta


def load(path):
    """-> the graph (meta + edges) of a graph.jsonl.gz written by build."""
    d = os.path.dirname(os.path.abspath(path))
    g = rqlib.read_json(os.path.join(d, "graph.meta.json"))
    buf = gzip.decompress(rqlib.read_bytes(path))
    if rqlib.sha256_bytes(buf) != g["edges_sha256"]:
        raise GraphError(f"{path} does not hash to its meta's edges_sha256")
    g["edges"] = [(r["prey"], r["pred"], r["family"], r["role"], r["horizon"])
                  for r in map(json.loads, buf.decode().splitlines())]
    return g


# ------------------------------------------------------------------ availability (Annex H D6 rule 27)
MASK_SCHEMA = "finfolk.redqueen.graphmask/2"        # (/2: registry-, identity- and evidence-bound; Codex #77 r1 P1)
BLOCK_SCHEMA = "finfolk.redqueen.worldsblock/1"
BLOCK_EVIDENCE_SCHEMA = "finfolk.redqueen.blockevidence/1"
EXCLUSION = ("biological", "technical", "pending")      # an edge takes its endpoints' first in this order
ENDED = ("done", "extinct", "failed", "invalidated")
DISPOSITIONS = {"no_rule": True, "established": True, "exhausted": True,      # disposition -> settled
                "restart_pending": False, "unresolved": False, "not_installed": False}
ARCHIVE_STATUS = ("verified", "off_chain", "missing", "mismatch")
SEED_SCHEME = "slot/1"              # (worlds.py's: its burn-in rule applies to registries of this seed scheme)


def frame_of(t):
    """A graph time (0 = F1, else t x 1M) -> its archive frame."""
    return 1 if t == 0 else t * 1_000_000


def attempt_uuid(base, k):
    """worlds.py's (and val_block.py's) identity of attempt k: the registry uuid for 0, else uuid5(NAMESPACE_URL,
    "finfolk:attempt:<registry uuid>:<k>")."""
    return base if not k else str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:attempt:{base}:{k}"))


def snapshot_uuid(world_uuid, frame):
    """plan.py's global key of one archived snapshot: uuid5(NAMESPACE_URL, "finfolk:snapshot:<world uuid>:<frame>")."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:snapshot:{world_uuid}:{int(frame)}"))


def registry_burn_in(reg):
    return int(reg.get("burn_in") or 0) if reg.get("seed_scheme") == SEED_SCHEME else 0


def _int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _sha(x):
    return isinstance(x, str) and len(x) == 64 and all(c in "0123456789abcdef" for c in x)


def world_problems(bw, r, bi, maxr):
    """Contradictory or unsupported evidence in one world's worlds-block entry against its registry world r (the
    burn-in frame bi and max restarts maxr: the registry's) -> [problem] (Codex #77 r1 P1-1, P2-3)."""
    p = []
    if bw.get("uuid") != r.get("uuid"):
        p.append(f"its uuid {bw.get('uuid')!r} is not the registry's")
    if (bw.get("treatment"), bw.get("block")) != (r.get("treatment"), r.get("block")):
        p.append(f"{bw.get('treatment')} in block {bw.get('block')}, the registry has {r.get('treatment')} in block "
                 f"{r.get('block')}")
    k = bw.get("attempt")
    if not _int(k) or not 0 <= k <= maxr:
        return p + [f"attempt {k!r}: the registry reserves attempts 0..{maxr}"]
    if bw.get("attempt_uuid") != attempt_uuid(r.get("uuid"), k):
        p.append(f"its attempt identity is not attempt {k}'s")
    b = bw.get("burn_in")
    if not isinstance(b, dict) or b.get("disposition") not in DISPOSITIONS:
        return p + ["no explicit burn-in disposition (a legacy entry: regenerate the block)"]
    d = b["disposition"]
    if b.get("decided") is not DISPOSITIONS[d]:
        p.append(f"decided {b.get('decided')!r} contradicts its disposition {d}")
    ev = bw.get("evidence")
    if not isinstance(ev, dict) or not _int(ev.get("frontier")):
        return p + ["no evidence record (frontier)"]
    fr, ft, vb, zeros = ev["frontier"], ev.get("first_terminal"), bw.get("valid_before"), bw.get("first_zeros") or {}
    if ft is None:
        if vb is not None or zeros:
            p.append("valid_before / first_zeros without an evidenced first terminal boundary")
    elif not isinstance(ft, dict) or not _int(ft.get("frame")) or vb != ft["frame"]:
        p.append("valid_before is not its evidenced first terminal boundary's frame")
    elif not zeros or min(zeros.values()) != vb or any(not _int(z) or z < vb for z in zeros.values()):
        p.append("its first_zeros contradict its first terminal boundary")
    elif vb > fr:
        p.append(f"its first terminal boundary {vb} lies past its evidence's frontier {fr}")
    early = vb is not None and vb < bi
    want = {"no_rule": not bi, "established": bool(bi) and not early and fr >= bi,
            "exhausted": bool(bi) and early and k >= maxr, "restart_pending": bool(bi) and early and k < maxr,
            "unresolved": bool(bi) and vb is None and fr < bi, "not_installed": True}
    if not want[d]:
        p.append(f"its disposition {d} is not supported by its evidence (first terminal {vb}, frontier {fr}, burn-in "
                 f"frame {bi}, attempt {k} of {maxr} restarts)")
    rf = ev.get("refill")
    if rf is not None and (not isinstance(rf, dict) or not _int(rf.get("frame"))):
        p.append("a malformed refill record")
    arch = bw.get("archive")
    if not isinstance(arch, dict):
        return p + ["no archive evidence"]
    for fs, e in arch.items():
        if not isinstance(e, dict) or e.get("status") not in ARCHIVE_STATUS or not fs.isdigit():
            p.append(f"archive {fs}: a malformed entry")
        elif e["status"] == "verified" and not _sha(e.get("sha256")):
            p.append(f"archive {fs}: verified without its sha256")
    ver = sorted(int(f) for f, e in arch.items() if isinstance(e, dict) and e.get("status") == "verified" and f.isdigit())
    if sorted(bw.get("archived") or []) != ver:
        p.append("its archived frames are not its verified archive objects")
    return p


def block_problems(g, block, registry, registry_sha256):
    """Why a worlds block is not THIS graph's registered study's evidence (Codex #77 r1 P1-1) -> [problem]: the
    block's registry hash must be the registry's bytes (and the graph's, when it recorded one), the graph's,
    the registry's and the block's worlds must be the same (ids, treatments, blocks, uuids), each entry's attempt
    and identity registered, and its evidence consistent (world_problems)."""
    probs = []
    if block.get("schema") != BLOCK_SCHEMA:
        probs.append(f"block schema {block.get('schema')!r}, expected {BLOCK_SCHEMA}")
    if block.get("registry_sha256") != registry_sha256:
        probs.append("the block was made from another registry (its registry_sha256 is not the registry's)")
    gr = g.get("registry")
    if gr is not None and gr.get("namespace") != registry.get("namespace"):
        probs.append("the graph was built from another registry (its namespace)")
    ev = block.get("evidence")
    if not isinstance(ev, dict) or ev.get("schema") != BLOCK_EVIDENCE_SCHEMA:
        return probs + [f"a legacy worlds block without its evidence record ({BLOCK_EVIDENCE_SCHEMA}): regenerate it "
                        "with worlds.py design-block"]
    bi, maxr = registry_burn_in(registry), int(registry.get("max_restarts") or 0)
    if (block.get("burn_in_frame"), block.get("max_restarts")) != (bi, maxr):
        probs.append(f"the block's burn-in frame / max restarts ({block.get('burn_in_frame')}, "
                     f"{block.get('max_restarts')}) are not the registry's ({bi}, {maxr})")
    regw = {w["id"]: w for w in registry.get("worlds", [])}
    gw = {w["id"]: w for w in g["worlds"]}
    ws = block.get("worlds") or {}
    for what, ids in (("graph", gw), ("block", ws)):
        if set(ids) != set(regw):
            extra, miss = sorted(set(ids) - set(regw)), sorted(set(regw) - set(ids))
            probs.append(f"the {what}'s worlds are not the registry's (extra {extra[:3]}, missing {miss[:3]})")
    for wid in sorted(set(gw) & set(regw)):
        r, w = regw[wid], gw[wid]
        if (r.get("treatment"), r.get("block")) != (w["treatment"], w["block"]):
            probs.append(f"{wid}: the graph has {w['treatment']} in block {w['block']}, the registry {r.get('treatment')} "
                         f"in block {r.get('block')}")
        if gr is not None and (gr.get("uuids") or {}).get(wid) != r.get("uuid"):
            probs.append(f"{wid}: the graph recorded another uuid")
        if wid in ws:
            probs += [f"{wid}: {x}" for x in world_problems(ws[wid], r, bi, maxr)]
    return probs


def snapshot_status(bw, t):
    """(status, why) of a world's snapshot at graph time t from its (validated) worlds-block entry, in this order
    (Codex #77 r1 P2-3: an unsettled attempt is pending FIRST, whatever its zeros): pending (the burn-in rule may
    still replace the attempt); biological (at or after its evidenced first guild zero: no valid population, design
    §2.3); technical (at or after a predator refill: a protocol-integrity event); available (archived on the line
    of descent, re-hashed, within the evidence's frontier; F1 the founder); technical (a missing or damaged
    archived object, or not archived / not evidenced in an ended attempt or a broken evidence chain: repair it if
    possible); pending (not archived or not evidenced yet in a running attempt)."""
    f, b, ev, k = frame_of(t), bw["burn_in"], bw["evidence"], bw["attempt"]
    if not b["decided"]:
        return "pending", f"attempt {k}'s burn-in disposition is not settled ({b.get('disposition')}: {b.get('why')})"
    vb = bw.get("valid_before")
    if vb is not None and f >= vb:
        return "biological", f"at or after attempt {k}'s evidenced first guild zero (frame {vb})"
    rf = ev.get("refill")
    if rf and f >= rf["frame"]:
        return "technical", (f"at or after a predator refill (frame {rf['frame']}): a protocol-integrity event, no "
                             "natural coexistence after it")
    a = bw["archive"].get(str(f))
    stop = ev.get("stop")
    ended = bw.get("status") in ENDED or bool(stop)
    tail = f" ({stop})" if stop else ""
    if a and a["status"] == "verified":
        if f == 1 or f <= ev["frontier"]:
            return "available", None
        return ("technical" if ended else "pending"), f"archived, but its evidence reaches frame {ev['frontier']}{tail}"
    if a and a["status"] in ("missing", "mismatch"):
        return "technical", f"its archived object is {a['status']} ({a.get('why')}): repair it"
    what = "not archived on its line of descent" if a else "not archived"
    if ended:
        return "technical", f"{what}, and attempt {k} is {bw.get('status')}{tail} (repair it if possible)"
    return "pending", f"{what} yet (attempt {k} is {bw.get('status')})"


def edge_exclusions(g, snaps):
    """Every edge's exclusion from a mask's snapshots (its endpoints' first of biological, technical, pending;
    references are not masked here: refsel.py's candidate pool decides them) -> ({cause: [edge index]},
    {family: {role: {scheduled, executable, biological, technical, pending}}}). The ONE derivation both mask and
    executable use (Codex #77 r1 P2-5)."""
    by = defaultdict(dict)
    excluded = {k: [] for k in EXCLUSION}
    for i, (q, p, fam, role, _) in enumerate(g["edges"]):
        st = "available"
        for x in (q, p):
            _, w, t = parse(x)
            if w is None:
                continue
            s_ = snaps.get(f"{w}:{frame_of(t)}", {}).get("status", "available")
            if s_ != "available" and (st == "available" or EXCLUSION.index(s_) < EXCLUSION.index(st)):
                st = s_
        c = by[fam].setdefault(role, {"scheduled": 0, "executable": 0, **{k: 0 for k in EXCLUSION}})
        c["scheduled"] += 1
        c["executable" if st == "available" else st] += 1
        if st != "available":
            excluded[st].append(i)
    return excluded, {f: dict(sorted(rs.items())) for f, rs in sorted(by.items())}


def mask(g, block, registry, registry_sha256, block_sha256=None, rederived=False):
    """The evidence-bound availability mask of an IMMUTABLE graph (its edges and roles never change) from a worlds
    block (worlds.py design-block) bound to the study's REGISTRY (its bytes' sha256; Codex #77 r1 P1-1): the block
    is refused unless it is this registry's (block_problems: identities, attempts, the burn-in disposition and the
    evidence consistent); then every unavailable snapshot (world x time) with its cause, the world's slot uuid,
    attempt and snapshot uuid (plan.py's key), every edge's exclusion, counts by family x role, the attrition by
    world and every AVAILABLE snapshot's verified archive sha256 (plan.py checks the bytes it reads against them).
    rederived: the CLI re-derived the block from the study root. Deterministic: no clock."""
    probs = block_problems(g, block, registry, registry_sha256)
    if probs:
        raise GraphError(f"the worlds block is not this graph's registered evidence ({len(probs)} problems): "
                         + "; ".join(probs[:6]))
    ws = block["worlds"]
    snaps, worlds = {}, {}
    for w in g["worlds"]:
        bw = ws[w["id"]]
        exc, first, shas = Counter(), None, {}
        for t in TIMES:
            st, why = snapshot_status(bw, t)
            f = frame_of(t)
            if st == "available":
                shas[str(f)] = bw["archive"][str(f)]["sha256"]
                continue
            s = {"world": w["id"], "time": t, "frame": f, "status": st, "why": why, "uuid": bw["uuid"],
                 "attempt": bw["attempt"], "snapshot": snapshot_uuid(bw["uuid"], f)}
            if st == "biological":
                s["valid_before"] = bw["valid_before"]
            snaps[f"{w['id']}:{f}"] = s
            exc[st] += 1
            first = t if first is None else first
        ev = bw["evidence"]
        worlds[w["id"]] = {"treatment": w["treatment"], "block": w["block"], "status": bw.get("status"),
                           "uuid": bw["uuid"], "attempt": bw["attempt"], "attempt_uuid": bw["attempt_uuid"],
                           "valid_before": bw.get("valid_before"), "first_terminal": ev.get("first_terminal"),
                           "frontier": ev["frontier"], "refill": ev.get("refill"), "stop": ev.get("stop"),
                           "burn_in": bw["burn_in"], "burn_in_decided": bw["burn_in"]["decided"],
                           "unavailable_snapshots": {k: exc.get(k, 0) for k in EXCLUSION},
                           "first_unavailable_time": first, "available_sha256": shas}
    excluded, by = edge_exclusions(g, snaps)
    n = len(g["edges"])
    ne = sum(len(v) for v in excluded.values())
    return {"schema": MASK_SCHEMA,
            "graph": {"edges_sha256": g.get("edges_sha256"), "namespace": g.get("namespace"), "edges": n},
            "registry": {"sha256": registry_sha256, "namespace": registry.get("namespace"),
                         "burn_in_frame": registry_burn_in(registry), "max_restarts": int(registry.get("max_restarts") or 0)},
            "block": {"schema": block.get("schema"), "sha256": block_sha256, "registry_sha256": block.get("registry_sha256"),
                      "evidence": block["evidence"], "rederived": bool(rederived)},
            "snapshots": snaps, "worlds": worlds,
            "edges": {"scheduled": n, "executable": n - ne, **{k: len(v) for k, v in excluded.items()}},
            "by_family_role": by, "excluded_edges": excluded,
            "rules": "Annex H D6 rule 27: the scheduled graph and its roles are preserved; only pairs whose source "
                     "snapshots are valid before the first guild-zero boundary (archived on the line of descent and "
                     "re-hashed, within the evidence's frontier, from a settled attempt) execute; every excluded pair "
                     "keeps its cause; no endpoint is replaced by another world or time, and recovery or support "
                     "failure never authorizes replacement edges"}


def mask_problems(g, m):
    """Why a mask does not describe this graph consistently (Codex #77 r1 P2-5) -> [problem]: its schema, graph
    digest and count, registry (the graph's, if recorded), every snapshot entry well-formed (a graph world, its
    frame its time's, a cause, its snapshot uuid), and the edge exclusions, totals and family x role counts
    exactly the ones its snapshots give (recomputed: no missing, extra, duplicate or out-of-range index)."""
    if m.get("schema") != MASK_SCHEMA:
        return [f"mask schema {m.get('schema')!r}, expected {MASK_SCHEMA}"]
    probs = []
    mg = m.get("graph") or {}
    if (mg.get("edges_sha256"), mg.get("edges")) != (g["edges_sha256"], len(g["edges"])):
        return ["the mask was made for another graph (its edges_sha256 or edge count differs)"]
    gr = g.get("registry")
    if gr is not None and gr.get("namespace") != (m.get("registry") or {}).get("namespace"):
        probs.append("the mask binds another registry than the graph's (namespace)")
    gw = {w["id"] for w in g["worlds"]}
    snaps = m.get("snapshots")
    if not isinstance(snaps, dict):
        return probs + ["no snapshots"]
    for key, s in snaps.items():
        if not (isinstance(s, dict) and s.get("world") in gw and _int(s.get("time")) and s["time"] in TIMES
                and s.get("frame") == frame_of(s["time"]) and key == f"{s['world']}:{s['frame']}"
                and s.get("status") in EXCLUSION and s.get("snapshot") == snapshot_uuid(s.get("uuid"), s["frame"])):
            probs.append(f"snapshot {key}: malformed (world, time, frame, cause or snapshot uuid)")
    if probs:
        return probs
    excluded, by = edge_exclusions(g, snaps)
    n, ne = len(g["edges"]), sum(len(v) for v in excluded.values())
    if m.get("excluded_edges") != excluded:
        probs.append("its excluded edges are not the ones its snapshots give (recomputed from the graph)")
    if m.get("by_family_role") != by:
        probs.append("its family x role counts are not its snapshots'")
    if m.get("edges") != {"scheduled": n, "executable": n - ne, **{k: len(v) for k, v in excluded.items()}}:
        probs.append("its edge totals are not its snapshots'")
    return probs


def executable(g, m, mask_sha256=None):
    """The executable graph: the immutable graph's edges minus the mask's exclusions, roles, families and
    horizons unchanged, its meta bound to the source graph and the mask (mask_sha256: its file's bytes). The mask
    is validated first (mask_problems: its exclusions RECOMPUTED from its snapshots)."""
    probs = mask_problems(g, m)
    if probs:
        raise GraphError("the mask does not describe this graph: " + "; ".join(probs[:5]))
    out = {i for v in m["excluded_edges"].values() for i in v}
    meta = {k: v for k, v in g.items() if k not in ("edges", "edges_sha256", "tool_sha256")}
    meta["executable_of"] = {"edges_sha256": g["edges_sha256"], "edges": len(g["edges"]),
                             "mask": {"sha256": mask_sha256, "block": m["block"], "registry": m.get("registry"),
                                      "excluded": {k: len(v) for k, v in m["excluded_edges"].items()}}}
    meta["edges"] = [e for i, e in enumerate(g["edges"]) if i not in out]
    return meta


def rederive_block(root, archive_root, registry_path):
    """The worlds block RE-DERIVED from a study root's evidence (worlds.py design-block, read-only) -> (block,
    registry, its sha256); the registry must be the root's own config/worlds.json (the same bytes)."""
    import worlds as worldslib                         # (lazy: worlds.py's evidence stack, only for this command)
    root = os.path.abspath(root)
    reg, sha = worldslib.load_registry(root, allow_placeholder=True)
    if rqlib.sha256_file(registry_path) != sha:
        raise GraphError(f"--registry {registry_path} is not {root}'s registry (other bytes)")
    blk = worldslib.design_block(root, reg, worldslib.bind_root(root, sha, archive_root, readonly=True))
    return json.loads(rqlib.canonical(blk).decode("utf-8")), reg, sha


# ------------------------------------------------------------------ report
ACCESS = {
    "v4": "training and support pairs of the global families (the new matchings included)",
    "no_new_matchings": "the same without train_match",
    "option_b": "no train_match, plus the training within-world pairs (fitted with an own-world layer)",
    "forward_time": "v4's, with every non-reference endpoint at or before 120M (§7.3)",
}


def fitting(g, rule):
    """The pairs a rule fits on."""
    out = []
    for e in g["edges"]:
        q, p, fam, role, _ = e
        if role not in ("training", "support"):
            continue
        if fam == "train_match" and rule in ("no_new_matchings", "option_b"):
            continue
        if fam in WITHIN and rule != "option_b":
            continue
        if rule == "forward_time" and any(parse(x)[1] is not None and parse(x)[2] > FORWARD_LAST for x in (q, p)):
            continue
        out.append(e)
    return out


def _components(edges):
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for q, p, *_ in edges:
        a, b = find(q), find(p)
        if a != b:
            parent[a] = b
    sizes = Counter(find(x) for x in parent)
    return sorted(sizes.values(), reverse=True)


def _dist(xs):
    xs = sorted(xs)
    if not xs:
        return {"n": 0}
    q = lambda f: xs[min(len(xs) - 1, int(f * len(xs)))]  # noqa: E731
    return {"n": len(xs), "min": xs[0], "p10": q(0.10), "median": q(0.5), "p90": q(0.9), "max": xs[-1],
            "mean": round(sum(xs) / len(xs), 3)}


def report(g):
    split = g["split"]
    holdout = {tuple(k.rsplit(":", 1)): v for k, v in g["holdout"].items()}
    holdout = {(w, int(t)): v for (w, t), v in holdout.items()}
    treat = {w["id"]: w["treatment"] for w in g["worlds"]}

    def cls(n):
        gg, w, t = parse(n)
        if w is None:
            return "reference"
        kind = "C" if treat[w] == "C" else "AB"
        if split[w] != "train":
            return f"{kind}-{split[w]}-world"
        return f"{kind}-snapshot-{holdout[(w, t)]}" if (w, t) in holdout else f"{kind}-train"
    ex = g.get("executable_of")             # (an executable graph: its attrition is the mask's, not a quota error)
    out = {"schema": "finfolk.redqueen.graphreport/1", "namespace": g["namespace"],
           "quota_problems": [] if ex else check_quotas(g), "pairs": len(g["edges"]),
           "families": dict(Counter(e[2] for e in g["edges"])),
           "roles": {f: dict(Counter(e[3] for e in g["edges"] if e[2] == f)) for f in FAMILIES
                     if f in QUOTAS or any(e[2] == f for e in g["edges"])}}
    if ex:                                  # (only an executable graph's: a scheduled report keeps its bytes, P3)
        out["executable_of"] = ex
    # support of held-out populations: references and training opponents among their support pairs
    sup = defaultdict(lambda: [0, 0])
    for q, p, fam, role, _ in g["edges"]:
        if role != "support":
            continue
        for x, y in ((q, p), (p, q)):
            if not cls(x).endswith("train") and cls(x) != "reference":
                sup[x][0 if parse(y)[1] is None else 1] += 1
    by = defaultdict(list)
    for x, (nref, nopp) in sup.items():
        by[cls(x) + ":" + parse(x)[0]].append((nref, nopp))
    out["support"] = {k: {"references": _dist([a for a, _ in v]), "training_opponents": _dist([b for _, b in v]),
                          "below_six_opponents": sum(1 for _, b in v if b < 6)} for k, v in sorted(by.items())}
    out["access"] = {}
    for rule, what in ACCESS.items():
        ed = fitting(g, rule)
        deg = Counter()
        for q, p, *_ in ed:
            deg[q] += 1
            deg[p] += 1
        dcls = defaultdict(list)
        for x, d in deg.items():
            dcls[cls(x) + ":" + parse(x)[0]].append(d)
        comps = _components(ed)
        out["access"][rule] = {"rule": what, "pairs": len(ed), "components": len(comps),
                               "largest_component": comps[0] if comps else 0,
                               "degree": {k: _dist(v) for k, v in sorted(dcls.items())}}
    pool = Counter(e[2] for e in g["edges"] if e[4] is None)
    out["horizons"] = {"long": sum(1 for e in g["edges"] if e[4] == "long"),
                       "short": sum(1 for e in g["edges"] if e[4] == "short"),
                       "randomized_pool": dict(pool), "randomized_long_1_8": {f: round(n / 8) for f, n in pool.items()}}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", required=True)
    b.add_argument("--namespace", default="rq2026-graph")
    b.add_argument("--registry")
    b.add_argument("--no-train-matchings", action="store_true")
    b.add_argument("--snapshot-topup", type=int, default=SNAPSHOT_TOPUP, metavar="N", help="0: none (pure v4)")
    b.add_argument("--ab-topup", type=int, default=AB_TOPUP, metavar="N", help="0: none (pure v4)")
    b.add_argument("--ab-topup-mode", choices=("fitting", "c"), default="fitting")
    b.add_argument("--lag-probe", type=int, default=None, metavar="M",
                   help="the lag7_probe family's lag (v4 amendment; default: 7 with the top-ups, 0 without them)")
    r = sub.add_parser("report")
    r.add_argument("--graph", required=True)
    r.add_argument("--out")
    mk = sub.add_parser("mask", help="the availability mask of a graph from a worlds block (read-only on both)")
    mk.add_argument("--graph", required=True)
    mk.add_argument("--block", required=True, help="worlds.py design-block's worlds block")
    mk.add_argument("--registry", required=True, help="the study's registry (config/worlds.json): the block, the graph "
                                                      "and every world's identity and attempt are bound to its bytes")
    src = mk.add_mutually_exclusive_group(required=True)
    src.add_argument("--root", help="the study root: the block is RE-DERIVED from its evidence (worlds.py design-block, "
                                    "read-only) and must be exactly --block")
    src.add_argument("--no-rederive", action="store_true",
                     help="check the block's bindings and consistency only (recorded in the mask: block.rederived false)")
    mk.add_argument("--archive-root", help="(with --root) the archive root, as worlds.py design-block's")
    mk.add_argument("--out", required=True)
    ex = sub.add_parser("executable", help="the graph minus a mask's exclusions (roles unchanged)")
    ex.add_argument("--graph", required=True)
    ex.add_argument("--mask", required=True)
    ex.add_argument("--out", required=True, help="a NEW directory (never the scheduled graph's)")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "mask":
            raw = rqlib.read_bytes(a.block)
            blk = json.loads(raw.decode("utf-8"))
            rraw = rqlib.read_bytes(a.registry)
            reg, rsha = json.loads(rraw.decode("utf-8")), rqlib.sha256_bytes(rraw)
            if a.root:
                fresh, _, _ = rederive_block(a.root, a.archive_root, a.registry)
                if fresh != blk:
                    raise GraphError(f"{a.block} is not {a.root}'s current evidence (re-derived: it differs); make the "
                                     "block again with worlds.py design-block")
            m = mask(load(a.graph), blk, reg, rsha, rqlib.sha256_bytes(raw), rederived=bool(a.root))
            rqlib.write_durable(a.out, rqlib.canonical(m))
            print(f"{m['edges']['executable']} of {m['edges']['scheduled']} pairs executable; excluded "
                  f"{ {k: m['edges'][k] for k in EXCLUSION} } -> {a.out}", file=sys.stderr)
            return 0
        if a.cmd == "executable":
            gd = os.path.dirname(os.path.abspath(a.graph))
            if os.path.realpath(os.path.abspath(a.out)) == os.path.realpath(gd):
                raise GraphError(f"--out {a.out} is the scheduled graph's own directory: the immutable input is never "
                                 "overwritten (Codex #77 r1 P2-8)")
            raw = rqlib.read_bytes(a.mask)
            meta = write(executable(load(a.graph), json.loads(raw.decode("utf-8")), rqlib.sha256_bytes(raw)), a.out)
            print(f"{meta['edges']} executable pairs -> {a.out}/graph.jsonl.gz", file=sys.stderr)
            return 0
        if a.cmd == "build":
            g = build(a.namespace, registry_worlds(a.registry) if a.registry else None, not a.no_train_matchings,
                      a.snapshot_topup, a.ab_topup, a.ab_topup_mode, a.lag_probe)
            if a.registry:                     # (Codex #77 r1 P1-1: the registry's provenance, for mask's binding)
                g["registry"] = registry_binding(a.registry)
            probs = check_quotas(g)
            if probs:
                raise GraphError("; ".join(probs))
            meta = write(g, a.out)
            print(f"{meta['edges']} pairs -> {a.out}/graph.jsonl.gz (edges sha256 {meta['edges_sha256'][:16]})",
                  file=sys.stderr)
            return 0
        rep = report(load(a.graph))
        text = json.dumps(rep, indent=1, sort_keys=True)
        if a.out:
            rqlib.write_durable(a.out, text.encode() + b"\n")
        else:
            print(text)
        return 1 if rep["quota_problems"] else 0
    except (GraphError, OSError, ValueError, KeyError) as e:
        print(f"graph.py {a.cmd}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

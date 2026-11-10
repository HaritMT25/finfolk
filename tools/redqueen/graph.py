#!/usr/bin/env python3
"""graph.py: the Red Queen map graph of design v4 (§4.1-4.5, §5.1, §7.1; Annex H D7 rules 34, 40) and its
pre-seal reports, availability masks and executable graphs (Annex H D6 rule 27).

    graph.py build --out DIR [--namespace NS] [--registry STUDY/config/worlds.json]
                   [--no-train-matchings] [--snapshot-topup 6] [--ab-topup 8 [--ab-topup-mode fitting|c]]
    graph.py report --graph DIR/graph.jsonl.gz [--out report.json]
    graph.py mask --graph DIR/graph.jsonl.gz --block worlds_block.json --out mask.json
    graph.py executable --graph DIR/graph.jsonl.gz --mask mask.json --out DIR2

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
topology. `mask` reads it (verified against its edges_sha256) and a worlds block (worlds.py design-block:
per world its first-guild-zero boundary valid_before, archived frames, status, attempt and burn-in
disposition; its world ids, treatments and blocks must be the graph's) and writes a separate,
deterministic mask: every unavailable snapshot (world x time; F1 = frame 1, t = t x 1M) with its cause:
biological (at or after the world's first guild zero), pending (an unsettled burn-in disposition, or
not archived yet in a running world) or technical (not archived in an ended world: repair it if
possible); every edge's exclusion (its endpoints' first of biological, technical, pending; references
are refsel.py's business, never masked here); counts by family x role (scheduled, executable,
biological, technical, pending) and the attrition by world. `executable` writes the graph minus the
exclusions, roles, families and horizons unchanged, its meta bound to the source graph and the mask
(recovery.py, report and plans consume it as they consume a graph). No endpoint is ever replaced by
another world or time, and a recovery or support failure never authorizes replacement edges.

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


def layout_problems(worlds):
    """Why a world list is not the registered 64-world layout (D7 rule 34): 8 blocks of 4C + 2A + 2B."""
    per = defaultdict(Counter)
    for w in worlds:
        per[w["block"]][w["treatment"]] += 1
    probs = []
    if sorted(per) != list(range(1, BLOCKS + 1)):
        probs.append(f"blocks {sorted(per)}, the registered layout has 1..{BLOCKS}")
    for b, c in sorted(per.items()):
        if dict(c) != LAYOUT:
            probs.append(f"block {b}: {dict(sorted(c.items()))}, the registered layout has {LAYOUT}")
    if len({w["id"] for w in worlds}) != len(worlds):
        probs.append("a world id twice")
    return probs


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
    c = Counter(e[2] for e in g["edges"])
    probs = [f"{f}: {c.get(f, 0)} pairs, the design has {n}" for f, n in QUOTAS.items()
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
    os.makedirs(d, exist_ok=True)
    meta = {k: v for k, v in g.items() if k != "edges"}
    meta["edges"] = len(g["edges"])
    buf = "".join(json.dumps({"prey": e[0], "pred": e[1], "family": e[2], "role": e[3], "horizon": e[4]},
                             sort_keys=True, separators=(",", ":")) + "\n" for e in g["edges"]).encode()
    raw = gzip.compress(buf, mtime=0)
    rqlib.write_durable(os.path.join(d, "graph.jsonl.gz"), raw)
    meta["edges_sha256"] = rqlib.sha256_bytes(buf)
    meta["tool_sha256"] = rqlib.sha256_file(os.path.abspath(__file__))
    rqlib.write_durable(os.path.join(d, "graph.meta.json"), rqlib.canonical(meta))
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
MASK_SCHEMA = "finfolk.redqueen.graphmask/1"
EXCLUSION = ("biological", "technical", "pending")      # an edge takes its endpoints' first in this order
ENDED = ("done", "extinct", "failed", "invalidated")


def frame_of(t):
    """A graph time (0 = F1, else t x 1M) -> its archive frame."""
    return 1 if t == 0 else t * 1_000_000


def snapshot_status(bw, t):
    """(status, why) of a world's snapshot at graph time t from its worlds-block entry: available; biological
    (at or after its first guild zero: no valid population, design §2.3); pending (the burn-in may still
    replace the attempt, or not yet archived in a running world); technical (not archived in an ended world)."""
    f = frame_of(t)
    vb = bw.get("valid_before")
    if vb is not None and f >= vb:
        return "biological", f"at or after the world's first guild zero (frame {vb})"
    bi = bw.get("burn_in")
    if isinstance(bi, dict) and not bi.get("decided"):
        return "pending", f"its attempt's burn-in disposition is not settled ({bi.get('why')})"
    if f in set(bw.get("archived") or ()):
        return "available", None
    if bw.get("status") in ENDED:
        return "technical", f"not archived, and the world is {bw.get('status')} (repair it if possible)"
    return "pending", f"not archived yet (the world is {bw.get('status')})"


def mask(g, block, block_sha256=None):
    """The evidence-bound availability mask of an IMMUTABLE graph (its edges and roles never change) from a
    worlds block (worlds.py design-block: per world valid_before, archived frames, status, attempt, burn-in):
    every unavailable snapshot (world x time) with its cause, every edge's exclusion (its endpoints' first
    of biological, technical, pending; references are not masked here: refsel.py's candidate pool decides
    them), counts by family x role, and the attrition by world. Deterministic: no clock."""
    ws = block.get("worlds") or {}
    probs = []
    for w in g["worlds"]:
        bw = ws.get(w["id"])
        if bw is None:
            probs.append(f"{w['id']}: not in the worlds block")
        elif (bw.get("treatment"), bw.get("block")) not in ((w["treatment"], w["block"]), (None, None)):
            probs.append(f"{w['id']}: the block has {bw.get('treatment')} in block {bw.get('block')}, the graph "
                         f"{w['treatment']} in block {w['block']}")
    if probs:
        raise GraphError("the worlds block is not this graph's registry: " + "; ".join(probs[:5]))
    snaps, worlds = {}, {}
    for w in g["worlds"]:
        bw = ws[w["id"]]
        exc = Counter()
        first = None
        for t in TIMES:
            st, why = snapshot_status(bw, t)
            if st != "available":
                snaps[f"{w['id']}:{frame_of(t)}"] = {"world": w["id"], "time": t, "frame": frame_of(t),
                                                    "status": st, "why": why}
                exc[st] += 1
                first = t if first is None else first
        worlds[w["id"]] = {"treatment": w["treatment"], "block": w["block"], "status": bw.get("status"),
                           "attempt": bw.get("attempt"), "valid_before": bw.get("valid_before"),
                           "burn_in_decided": (bw["burn_in"].get("decided") if isinstance(bw.get("burn_in"), dict)
                                               else None),
                           "unavailable_snapshots": dict(exc), "first_unavailable_time": first}
    by = defaultdict(lambda: defaultdict(Counter))
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
        c = by[fam][role]
        c["scheduled"] += 1
        c["executable" if st == "available" else st] += 1
        if st != "available":
            excluded[st].append(i)
    n = len(g["edges"])
    ne = sum(len(v) for v in excluded.values())
    return {"schema": MASK_SCHEMA,
            "graph": {"edges_sha256": g.get("edges_sha256"), "namespace": g.get("namespace"), "edges": n},
            "block": {"schema": block.get("schema"), "sha256": block_sha256, "registry_sha256": block.get("registry_sha256")},
            "snapshots": snaps, "worlds": worlds,
            "edges": {"scheduled": n, "executable": n - ne, **{k: len(v) for k, v in excluded.items()}},
            "by_family_role": {f: {r: dict(c) for r, c in sorted(rs.items())} for f, rs in sorted(by.items())},
            "excluded_edges": excluded,
            "rules": "Annex H D6 rule 27: the scheduled graph and its roles are preserved; only pairs whose source "
                     "snapshots are valid before the first guild-zero boundary (and archived, from a settled attempt) "
                     "execute; every excluded pair keeps its cause; no endpoint is replaced by another world or time, "
                     "and recovery or support failure never authorizes replacement edges"}


def executable(g, m, mask_sha256=None):
    """The executable graph: the immutable graph's edges minus the mask's exclusions, roles, families and
    horizons unchanged, its meta bound to the source graph and the mask (mask_sha256: its file's bytes)."""
    if m.get("schema") != MASK_SCHEMA:
        raise GraphError(f"mask schema {m.get('schema')!r}, expected {MASK_SCHEMA}")
    if (m["graph"]["edges_sha256"], m["graph"]["edges"]) != (g["edges_sha256"], len(g["edges"])):
        raise GraphError("the mask was made for another graph (its edges_sha256 or edge count differs)")
    out = {i for v in m["excluded_edges"].values() for i in v}
    meta = {k: v for k, v in g.items() if k not in ("edges", "edges_sha256", "tool_sha256")}
    meta["executable_of"] = {"edges_sha256": g["edges_sha256"], "edges": len(g["edges"]),
                             "mask": {"sha256": mask_sha256, "block": m["block"],
                                      "excluded": {k: len(v) for k, v in m["excluded_edges"].items()}}}
    meta["edges"] = [e for i, e in enumerate(g["edges"]) if i not in out]
    return meta


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
           "executable_of": ex,
           "families": dict(Counter(e[2] for e in g["edges"])),
           "roles": {f: dict(Counter(e[3] for e in g["edges"] if e[2] == f)) for f in FAMILIES
                     if f in QUOTAS or any(e[2] == f for e in g["edges"])}}
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
    mk.add_argument("--block", required=True, help="worlds.py design-block's (or val_block.py's) worlds block")
    mk.add_argument("--out", required=True)
    ex = sub.add_parser("executable", help="the graph minus a mask's exclusions (roles unchanged)")
    ex.add_argument("--graph", required=True)
    ex.add_argument("--mask", required=True)
    ex.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "mask":
            raw = rqlib.read_bytes(a.block)
            m = mask(load(a.graph), json.loads(raw.decode("utf-8")), rqlib.sha256_bytes(raw))
            rqlib.write_durable(a.out, rqlib.canonical(m))
            print(f"{m['edges']['executable']} of {m['edges']['scheduled']} pairs executable; excluded "
                  f"{ {k: m['edges'][k] for k in EXCLUSION} } -> {a.out}", file=sys.stderr)
            return 0
        if a.cmd == "executable":
            raw = rqlib.read_bytes(a.mask)
            meta = write(executable(load(a.graph), json.loads(raw.decode("utf-8")), rqlib.sha256_bytes(raw)), a.out)
            print(f"{meta['edges']} executable pairs -> {a.out}/graph.jsonl.gz", file=sys.stderr)
            return 0
        if a.cmd == "build":
            g = build(a.namespace, registry_worlds(a.registry) if a.registry else None, not a.no_train_matchings,
                      a.snapshot_topup, a.ab_topup, a.ab_topup_mode, a.lag_probe)
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

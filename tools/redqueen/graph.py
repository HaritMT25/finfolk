#!/usr/bin/env python3
"""graph.py: the Red Queen map graph of design v4 (§4.1-4.5, §5.1, §7.1) and its pre-seal reports.

    graph.py build --out DIR [--namespace NS] [--registry STUDY/config/worlds.json]
                   [--no-train-matchings] [--snapshot-topup 6] [--ab-topup 8 [--ab-topup-mode fitting|c]]
    graph.py report --graph DIR/graph.jsonl.gz [--out report.json]

The graph is the set of (prey population, predator population) pairs the assays measure for the
map, with each pair's family, split role (the roles of plan.py's design /2 edges: training,
validation, test, support) and horizon class. Populations are snapshots "Q:<world>:<t>" (prey) and
"P:<world>:<t>" (predators; C worlds only), t = 0 (F1) .. 200 (200M steps), and the external
references "RQ:<k>", "RP:<k>" (eight per guild: registered reference slots; the selected sentinel
snapshots are a deterministic relabelling, §4.2). Worlds: a registry's (worlds.json: ids,
treatments, blocks) or the registered layout's synthetic ids (8 blocks of C x4, A, B). Everything is
derived from --namespace: the same inputs give the same bytes.

SPLITS (§7.1, §5.1). C worlds 20 training / 6 validation / 6 test; A and B 5/1/2 each. In every
training C world 20 joint snapshot times are held out (10 snapshot-validation, 10 snapshot-test;
two per 20M bin, residues mod 5 balanced, F1 never). 12 fork worlds (2 training, 4 validation, all
6 test) and among them 8 intensive worlds (2, 2, 4).

FAMILIES (v4 §4.5; quotas checked; no pair twice).
  within      every C world's coarse matrix (F1, 5M, ..., 200M: 41 x 41), its fine windows (F1-20M,
              90-110M, 180-200M: offsets 0, +-1, +-2, +-4) and the intensive worlds' complete fine
              windows: 72,992
  ref_prey    C prey x the four predator references of its block: 25,728
  ref_pred    C predators x the four prey references of its block: 25,728
  ref_ab      A/B prey x the block's four predator references: 12,864
  ref_grid    the 8 x 8 reference grid: 64
  cross       eight edge-disjoint C matchings (prey world w -> predator world w + s_m, a distinct
              shift per matching; two at the same time, six at a per-world random time permutation):
              51,456
  ab_to_c     A/B prey x four C predators (distinct worlds; held-out A/B worlds: training C
              predators outside the snapshot holdouts): 12,864
  support_c   four more training opponents (eligible training states) for every held-out-world C
              population, both guilds: 19,296
  support_ab  two more training C predators for every held-out A/B prey snapshot: 2,412
  train_match four edge-disjoint matchings of the 3,620 eligible training states (20 training C
              worlds x 201 - 400 snapshot holdouts), across worlds, new pairs only (v4 §4.4): 14,480
  total 237,884 (223,404 with --no-train-matchings), and the default top-ups (no fixed quota):
  support_snap every snapshot-holdout population up to six training opponents in its support,
              new support pairs to eligible training states of other worlds: 1,301
  ab_train_c  every training A/B prey snapshot up to eight fitting pairs (its four references
              included; --ab-topup-mode c: eight training C opponents) with new training pairs to
              eligible training C predators: 3,877
  The top-ups are the recovery comparison's choice (rank 4 identifiable for every population, the
  noisy A/B and snapshot-test errors down; +5,178 pairs, about 0.24 production days at 5k);
  --snapshot-topup 0 --ab-topup 0 gives the v4 graph alone. They come after every registered
  family, which they leave unchanged.

ROLES. A pair is "support" when it is declared placement support of a held-out population: its four
reference pairs, two of its existing matching pairs with an eligible training opponent (world
holdouts) or up to six (snapshot holdouts), every ab_to_c pair of a held-out A/B world, and the
support_c / support_ab / support_snap pairs. Otherwise a pair inherits its most held-out endpoint:
test before validation before training (references count as training).

HORIZONS (§4.6): the reference grid "long"; support_c, support_ab, train_match and the top-ups
"short"; every other family is in the randomized 1/8 long pool (no horizon: plan.py's
pre-randomized long subset).

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
QUOTAS = {"within": 72_992, "ref_prey": 25_728, "ref_pred": 25_728, "ref_ab": 12_864, "ref_grid": 64,
          "cross": 51_456, "ab_to_c": 12_864, "support_c": 19_296, "support_ab": 2_412, "train_match": 14_480}
# optional top-ups (no registered quota: their counts are what the options generate)
TOPUPS = ("support_snap", "ab_train_c")
FAMILIES = tuple(QUOTAS) + TOPUPS
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
    out = []
    for b in range(1, 9):
        out += [{"id": f"C{4 * (b - 1) + i + 1:02d}", "treatment": "C", "block": b} for i in range(4)]
        out += [{"id": f"A{b}", "treatment": "A", "block": b}, {"id": f"B{b}", "treatment": "B", "block": b}]
    return out


def registry_worlds(path):
    reg = rqlib.read_json(path)
    return [{"id": w["id"], "treatment": w["treatment"], "block": w["block"]} for w in reg["worlds"]]


def splits(ns, worlds):
    """{world: "train" | "val" | "test"}, the fork and intensive sets, the snapshot holdouts."""
    by_t = defaultdict(list)
    for w in worlds:
        by_t[w["treatment"]].append(w["id"])
    want = {"C": (20, 6, 6), "A": (5, 1, 2), "B": (5, 1, 2)}
    split = {}
    for t, ids in sorted(by_t.items()):
        n = want[t]
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
          ab_topup_mode="fitting"):
    """-> the graph: {"schema", "namespace", "worlds", "split", "fork", "intensive", "holdout",
    "edges": [(prey, pred, family, role, horizon)], ...}.
    snapshot_topup N: every snapshot-holdout population with fewer than N training opponents among
    its support gets new support pairs to eligible training states of other worlds (support_snap).
    ab_topup N: every training A/B prey snapshot gets new training pairs to eligible training C
    predators (ab_train_c) until it has N fitting pairs (mode "fitting": its four reference pairs
    included) or N training C opponents (mode "c"). Both come after every registered family, which
    they leave unchanged."""
    worlds = worlds or synthetic_worlds()
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
    # least four training worlds in each direction (so its two support opponents from the existing
    # matchings exist, whatever the snapshot holdouts)
    nc = len(cs)
    for attempt in range(1000):
        shifts = Rng(ns, "cross-shifts", attempt).perm(range(1, nc))[:8]
        if all(sum(split[cs[(i + d * s) % nc]] == "train" for s in shifts) >= 4
               for i, w in enumerate(cs) if split[w] != "train" for d in (1, -1)):
            break
    else:
        raise GraphError("no cross-matching shifts give every held-out world four training opponents")
    matched = defaultdict(list)   # population -> [(matching, other endpoint)]
    for m, s in enumerate(shifts):
        for i, w in enumerate(cs):
            o = cs[(i + s) % len(cs)]
            tau = list(TIMES) if m < 2 else Rng(ns, "cross-time", m, w).perm(TIMES)
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
            "worlds": worlds, "split": split, "fork": fork, "intensive": intensive,
            "holdout": {f"{w}:{t}": v for (w, t), v in sorted(holdout.items())},
            "ref_subsets": {"predator_refs_of_block": sub_p, "prey_refs_of_block": sub_q},
            "cross_shifts": {"shifts": shifts, "attempt": attempt},
            "edges": edges}


def check_quotas(g):
    c = Counter(e[2] for e in g["edges"])
    probs = [f"{f}: {c.get(f, 0)} pairs, the design has {n}" for f, n in QUOTAS.items()
             if (f != "train_match" or g["train_matchings"]) and c.get(f, 0) != n]
    if len({(e[0], e[1]) for e in g["edges"]}) != len(g["edges"]):
        probs.append("a pair occurs twice")
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
        if fam == "within" and rule != "option_b":
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
    out = {"schema": "finfolk.redqueen.graphreport/1", "namespace": g["namespace"],
           "quota_problems": check_quotas(g), "pairs": len(g["edges"]),
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
    r = sub.add_parser("report")
    r.add_argument("--graph", required=True)
    r.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            g = build(a.namespace, registry_worlds(a.registry) if a.registry else None, not a.no_train_matchings,
                      a.snapshot_topup, a.ab_topup, a.ab_topup_mode)
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

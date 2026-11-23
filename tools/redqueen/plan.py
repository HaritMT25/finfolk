#!/usr/bin/env python3
"""plan.py: expand a Red Queen design (JSON) into a runner plan (JSONL, schema finfolk.redqueen.plan/1 or /2).

    plan.py DESIGN.json --pending --out PLAN.pending.jsonl [--long-manifest LONG.json]
    plan.py DESIGN.json [--against PLAN.pending.jsonl] [--avoid OLD_PLAN.jsonl ...] --out PLAN.jsonl
            [--long-manifest LONG.json] [--exclusions MASK.json --reconciliation RECEIPT.json]

A design of schema finfolk.redqueen.design/1 (blocks; below) gives plan/1 rows, as phase A;
one of schema finfolk.redqueen.design/2 (design v3: an explicit edge list; "Design /2" at the
end) gives plan/2 rows.

--pending: before the archives exist (the plan a preregistration binds): every source and
    template hash is "pending" and nothing is read. Such a plan cannot run (run.py refuses it).
--against: the final plan, once the files exist, must be the pending plan with only the
    "pending" hashes filled in: the same cells in the same order, every other field equal
    (refused, exit 2, otherwise). The final plan reads every file once, hashes and validates
    that one buffer (ckpt.py), and checks every snapshot's actual frame against its registered
    one, that predator snapshots have brains (format 2), that templates have enough slots, and
    that every live challenge (and its predator-free control) runs on a prey world without a
    predator floor (a live arena keeps its prey world's config: a floor would refill predators).
--avoid: refuse (exit 2) if an engine seed (transplant, reseed) of this plan also occurs in an
    archived plan (this tooling's or tools/invasion's).
--exclusions (design /2, with --against; Annex H D6 rule 27): graph.py mask's availability mask (its
    "snapshots": world x frame -> biological / technical / pending, evidence-bound). The mask must
    describe the REGISTERED intent (Codex #77 r1 P1-2, r2): the design's "availability" binding names the
    scheduled graph's edges_sha256, the registry's sha256, its burn-in rule (max restarts, burn-in
    frame: every disposition is checked against it) and, with external
    (sentinel) references, the registered reference assignment's sha256 (references_sha256, read with
    --references); the binding is part of EVERY generated row, so --against refuses a substituted one;
    the mask's own evidence must be consistent (graph.mask_evidence_problems, the validator graph.py and
    sealing.py share: explicit settled dispositions, valid_before its first terminal and within its
    frontier, an unsettled attempt all pending, biological exclusions exactly at or after the zero,
    excluded and available frames disjoint); its graph, registry and block registry the binding's,
    every design world covered (by uuid) by the mask with the design's uuid, a registered attempt and
    that attempt's identity, or by a registered reference (whose cells must read the archive bytes the
    assignment registers); refused otherwise. EVERY registered cell is still generated and checked against the pending plan (seeds,
    groups and long-subset membership from the registered intent: the surviving long pool is never
    re-randomized); the cells with an unavailable prey or predator snapshot, matched by SNAPSHOT UUID
    (an alias display label excludes as its canonical world does, P2-4), are never read and are left
    out of the written (executable) plan; every snapshot an executable cell reads must hash to the
    mask's verified archive sha256 for it; and --reconciliation writes the receipt: the pending plan's
    and the mask's sha256, the binding, the scheduled, executable and excluded counts (by role,
    primary family, horizon) and every excluded cell with its cause. Without a mask, a missing file
    stays an error: no cell is ever deleted silently.
Expansion is deterministic: the same design gives the same bytes (rows sorted by id).

DESIGN.json:
{
  "schema": "finfolk.redqueen.design/1",
  "name": "rq-main",
  "seed_namespace": "rq-main-1",           # seeds derive from it (changing "name" does not move them)
  "times": {"F1": 1, "5M": 5000000, ...},  # label -> frame (the archive clock)
  "worlds": {
    "w01": {"uuid": "...", "pattern": "/abs/w01/ckpt.{frame}.json",   # {frame} and {label} expand
            "paths": {"F1": "/abs/w01/F1.json"}}, ...                  # per-label overrides
  },
  "templates": ["/abs/template_a.json", ...],   # replicate r uses templates[r % len]
  "defaults": {"assay": "frozen", "k": 6, "prey_policy": "common", "n_prey": 600,
               "sampling": "hybrid", "steps": 20000, "horizons": [5000, 10000, 20000],
               "log_every": 500, "checkpoint_every": 5000},
  "blocks": [
    {"name": "coarse", "prey_worlds": ["w01", ...], "prey_times": ["F1", "5M", ...],
     "predators": "same",                  # the prey world's own archive, at predator_times
                | {"world": "s01"}          # one fixed archive (a sentinel benchmark)
                | {"partner": {"w01": "w02", ...}}   # one other world per prey world (cross-world)
                | "random"                  # K random-genome founders (--predators-from random)
                | "none",                   # only the predator-free fork
     "predator_times": ["F1", "5M", ...], "replicates": 8, "with_nopred": true,
     ... any "defaults" key, overriding it for this block}
  ]
}

Cells. kind "assay" (predators from an archive or random) or "nopred" (the predator-free fork:
the transplant with K = 0, scored for initial-cohort survival). A cell's id names its content:
  <prey world>.<prey time>~<pred world>.<pred time>|random|none.<prey policy>.<assay>.k<K>.r<NN>
and a cell several blocks produce (a dense window's overlap with the coarse grid) appears once,
listing every block; the same id with different content is refused.

Seeds and sharing groups (design section 2: replicate r shares its template and seeds across
historical opponents and matched assay conditions; the whole replicated matrix is a correlated
unit). Each seed is a function of its group only:
  sample      group (prey world, prey time, replicate): the common checkpoint, shared by every
              predator time, the fork, every assay mode and K of that group;
  reseed      group (prey world, prey time, replicate): the engine's --reseed-after-load R;
  transplant  group (prey world, replicate): the transplant seed S, so predator placements are
              the same across the whole replicate matrix (transplant.hpp: the layout is a
              function of S, K and the world size only);
  matrix      group (prey world, replicate): the correlated randomization unit.
Seeds are SHA-256 derivations of (namespace, kind, group), 32-bit (the engine's limit), made
unique within each kind across groups (a collision is re-derived with a counter, in sorted
group order, so two groups never share a seed by accident).

Design /2 (design v3 §3.5, §4, §4.6, §7.1):
{
  "schema": "finfolk.redqueen.design/2", "name": ..., "seed_namespace": ...,
  "times": {...}, "worlds": {...},           # as /1 (worlds.py design-block writes this block)
  "templates": [...], "age_reference": "/abs/config/age_reference.json" | null,
  "replicates": 6,
  "defaults": {"assay": "frozen", "k": 6, "prey_policy": "common", "n_prey": 600,
               "sampling": "wor-balanced", "short_steps": 5000, "long_steps": 20000,
               "short_horizons": [5000], "long_horizons": [5000, 10000, 20000],
               "log_every": 500, "checkpoint_every": 5000},
  "long": {"fraction": 0.125, "strata": ["family", "prey_world"],    # (STRATA lists the keys)
           "family_priority": ["reference", "cross", ...]},          # (a merged pair's primary family)
  "edges": "/abs/config/edges.jsonl" | [...],
  "availability": {"graph_edges_sha256": ..., "registry_sha256": ..., "max_restarts": 8,
                   "burn_in_frame": 5000000}
}                                            # (the registered binding --exclusions verifies)
An EDGE (one line): {"edge": "e000001", "family": "within", "role": "training" | "validation" |
"test" | "support" | "audit" | "diagnostic", "prey": {"world", "time"}, "predators": {"world",
"time"} | {"source": "random"} | {"source": "scripted"} (K fresh scripted Stage A hunters: the H-C
scripted benchmark; the engine's --predators-from scripted) | null (the predator-free continuation),
and optionally "assay",
"k", "prey_policy", "horizon": "short" | "long" (absent: the pre-randomized long subset decides),
"namespace": "main" | "audit" | ... (an independently seeded re-measurement; an audit edge, its
controls included, defaults to "audit" and may not use "main"), "support_exception": true (a
support edge whose role may differ from the pair's other condition versions, v4 §7.1)}.
A PAIR is canonical: (prey snapshot UUID, opponent snapshot UUID | random | none, prey policy,
assay, K, namespace); display labels that alias one snapshot merge into it (its row id is the
smallest label, the others are recorded as "aliases"; aliases with different files are refused).
A pair becomes R cells, all with one role and one horizon: the same pair listed by several
families appears once (its families merged; its "primary_family", the stratum it is drawn in, is
the first in long.family_priority, then the smallest name, so the edge order cannot move it);
with different roles or horizons it is refused. Split roles are per endpoint pair across condition
versions (policy, assay, K): two versions with different roles are refused unless one is a support
edge marked support_exception. The long subset: of the pairs whose horizon is not fixed, exactly
floor(fraction x N + 0.5) are long (the nearest whole unit: "1/8" is floor(N / 8 + 0.5)),
apportioned over the strata by largest remainder and chosen within a stratum by a hash order;
--long-manifest writes it only after every check passed, with the accepted plan's sha256.
A long cell runs long_steps with its long_horizons (its first is the short horizon: a long
trajectory includes its short measurement).
SEEDS are global per snapshot x replicate, whatever the edge's family: sample, ages and reseed
from (namespace, prey snapshot UUID, r); transplant (donor draw and placement) from (namespace,
predator snapshot UUID, r), or (namespace, random, K, r); the fork's from its prey key. Each is
derive_seed(seed_namespace, kind, group key) and a 32-bit collision between two groups is refused
(never re-derived per plan), so a group's seed is the same in every plan; --joint (repeatable)
checks the generated rows and every other plan given (an audit's, production's family plans)
together as ONE seed universe. The SNAPSHOT UUID is exactly
uuid5(uuid.NAMESPACE_URL, "finfolk:snapshot:<world uuid>:<frame>") (the world UUID as text, the
frame as a decimal integer; a fixed test vector is in test_redqueen.py). The age reference
(common.py ages) is the upper order statistic at the empirical CDF's jumps: sorted pooled ages
at floor((i + 0.5) M / N) for i = 0 .. N - 1; the final plan also checks its maxAge against every
template's (as the construction does). Rows (plan/2) carry the pair ("unit"), its aliases,
families and primary family, role, namespace, horizon, both snapshot UUIDs, the age reference
and every group. A plan's rows all have one schema (run.py refuses /1 and /2 mixed).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rqlib  # noqa: E402

PLAN_SCHEMA = "finfolk.redqueen.plan/1"
DESIGN_SCHEMA = "finfolk.redqueen.design/1"
ASSAYS = ("frozen", "frozen-newborn", "live")
POLICIES = ("common", "native")
SAMPLINGS = ("hybrid", "wor-balanced", "iid")   # hybrid: design section 2
DEFAULT_KEYS = ("assay", "k", "prey_policy", "n_prey", "sampling", "steps", "horizons", "log_every",
                "checkpoint_every")
NAME_RE = re.compile(r"^[A-Za-z0-9-]+$")
SEED_KINDS = ("sample", "reseed", "transplant")
ENGINE_SEEDS = ("reseed", "transplant")
SHA_PATHS = (("prey", "sha256"), ("predators", "sha256"), ("template", "sha256"), ("ages", "sha256"))


class DesignError(Exception):
    pass


def _name(kind, s):
    if not isinstance(s, str) or not NAME_RE.match(s):
        raise DesignError(f"{kind} name {s!r}: letters, digits and '-' only")
    return s


def snapshot_path(design, world, label):
    w = design["worlds"][world]
    if label in (w.get("paths") or {}):
        p = w["paths"][label]
    elif w.get("pattern"):
        p = w["pattern"].replace("{frame}", str(design["times"][label])).replace("{label}", label)
    else:
        raise DesignError(f"world {world}: no path for time {label}")
    if not os.path.isabs(p):
        raise DesignError(f"world {world} time {label}: path {p!r} must be absolute")
    return p


def settings(design, block):
    s = dict(design.get("defaults") or {})
    s.update({k: v for k, v in block.items() if k in DEFAULT_KEYS})
    miss = [k for k in DEFAULT_KEYS if k not in s and not (k in ("n_prey", "sampling") and s.get("prey_policy") == "native")]
    if miss:
        raise DesignError(f"block {block.get('name')}: no value for {miss}")
    if s["assay"] not in ASSAYS:
        raise DesignError(f"assay {s['assay']!r}: one of {ASSAYS}")
    if s["prey_policy"] not in POLICIES:
        raise DesignError(f"prey_policy {s['prey_policy']!r}: one of {POLICIES}")
    if s["prey_policy"] == "common":
        if s.get("sampling") not in SAMPLINGS:
            raise DesignError(f"sampling {s.get('sampling')!r}: one of {SAMPLINGS}")
        if not isinstance(s.get("n_prey"), int) or s["n_prey"] < 1:
            raise DesignError("n_prey must be a whole number >= 1")
    else:
        s["n_prey"], s["sampling"] = None, None
    for k in ("k", "steps", "log_every", "checkpoint_every"):
        if not isinstance(s[k], int) or s[k] < (0 if k == "k" else 1):
            raise DesignError(f"{k} must be a whole number ({'>= 0' if k == 'k' else '>= 1'})")
    if s["steps"] % s["checkpoint_every"] or s["steps"] % s["log_every"]:
        raise DesignError("steps must be a multiple of checkpoint_every and of log_every")
    hs = s["horizons"]
    if not hs or any(not isinstance(h, int) or not 0 < h <= s["steps"] or h % s["checkpoint_every"]
                     or h % s["log_every"] for h in hs) or sorted(set(hs)) != hs:
        raise DesignError("horizons: increasing multiples of checkpoint_every and log_every within steps")
    return s


def expand(design, pending=False):
    """-> (rows sorted by id, warnings). Reads nothing with pending."""
    if design.get("schema") != DESIGN_SCHEMA:
        raise DesignError(f"design schema {design.get('schema')!r}, expected {DESIGN_SCHEMA}")
    ns = design.get("seed_namespace")
    if not isinstance(ns, str) or not ns:
        raise DesignError("seed_namespace is required")
    times = design.get("times") or {}
    for lab, fr in times.items():
        _name("time", lab)
        if not isinstance(fr, int) or fr < 0:
            raise DesignError(f"time {lab}: frame must be a whole number >= 0")
    for wn, w in (design.get("worlds") or {}).items():
        _name("world", wn)
        if not isinstance(w.get("uuid"), str) or not w["uuid"]:
            raise DesignError(f"world {wn}: uuid is required")
    templates = design.get("templates") or []
    if any(not isinstance(t, str) or not os.path.isabs(t) for t in templates):
        raise DesignError("templates: absolute paths")

    cells = {}

    def add(row):
        old = cells.get(row["id"])
        if old is None:
            cells[row["id"]] = row
            return
        a, b = dict(old), dict(row)
        a.pop("blocks"), b.pop("blocks")
        if a != b:
            raise DesignError(f"cell {row['id']} is produced twice with different content "
                              f"({sorted(k for k in a if a.get(k) != b.get(k))})")
        old["blocks"] = sorted(set(old["blocks"]) | set(row["blocks"]))

    def world_ref(wn, label):
        if wn not in design["worlds"]:
            raise DesignError(f"unknown world {wn}")
        if label not in times:
            raise DesignError(f"unknown time {label}")
        return {"world": wn, "uuid": design["worlds"][wn]["uuid"], "time": label, "frame": times[label],
                "path": snapshot_path(design, wn, label)}

    for block in design.get("blocks") or []:
        bname = _name("block", block.get("name"))
        s = settings(design, block)
        reps = block.get("replicates")
        if not isinstance(reps, int) or reps < 1:
            raise DesignError(f"block {bname}: replicates must be >= 1")
        if s["prey_policy"] == "common" and not templates:
            raise DesignError(f"block {bname}: the common prey policy needs 'templates'")
        preds = block.get("predators", "same")
        for pw in block.get("prey_worlds") or []:
            for pt in block.get("prey_times") or []:
                prey = world_ref(pw, pt)
                for r in range(reps):
                    tpl = None
                    if s["prey_policy"] == "common":
                        ti = r % len(templates)
                        tpl = {"index": ti, "path": templates[ti]}
                    groups = {"common": f"{pw}.{pt}.r{r:02d}" if s["prey_policy"] == "common" else None,
                              "sample": f"{pw}.{pt}.r{r:02d}", "reseed": f"{pw}.{pt}.r{r:02d}",
                              "transplant": f"{pw}.r{r:02d}", "matrix": f"{pw}.r{r:02d}"}
                    base = {"schema": PLAN_SCHEMA, "design": design.get("name", ""), "blocks": [bname],
                            "prey": prey, "template": tpl, "prey_policy": s["prey_policy"],
                            "n_prey": s["n_prey"], "sampling": s["sampling"], "assay": s["assay"],
                            "steps": s["steps"], "horizons": list(s["horizons"]), "log_every": s["log_every"],
                            "checkpoint_every": s["checkpoint_every"], "replicate": r, "groups": groups,
                            "expected": {"checkpoint_steps": list(range(s["checkpoint_every"], s["steps"] + 1,
                                                                        s["checkpoint_every"]))}}
                    tail = f".{s['prey_policy']}.{s['assay']}"
                    if preds == "random":
                        add(dict(base, kind="assay", predators={"source": "random"}, k=s["k"],
                                 id=f"{pw}.{pt}~random{tail}.k{s['k']}.r{r:02d}"))
                    elif preds != "none":
                        if preds == "same":
                            yw = pw
                        elif isinstance(preds, dict) and "world" in preds:
                            yw = preds["world"]
                        elif isinstance(preds, dict) and "partner" in preds:
                            yw = preds["partner"].get(pw)
                            if yw is None:
                                raise DesignError(f"block {bname}: no partner for prey world {pw}")
                        else:
                            raise DesignError(f"block {bname}: predators {preds!r}")
                        for yt in block.get("predator_times") or []:
                            if s["k"] < 1:
                                raise DesignError(f"block {bname}: an archive challenge needs k >= 1")
                            add(dict(base, kind="assay", predators=world_ref(yw, yt), k=s["k"],
                                     id=f"{pw}.{pt}~{yw}.{yt}{tail}.k{s['k']}.r{r:02d}"))
                    if preds == "none" or block.get("with_nopred"):
                        add(dict(base, kind="nopred", predators=None, k=0, id=f"{pw}.{pt}~none{tail}.k0.r{r:02d}"))

    rows = [cells[k] for k in sorted(cells)]
    assign_seeds(rows, ns)
    warnings = []
    for row in rows:
        for role in ("prey", "predators", "template"):
            x = row.get(role)
            if isinstance(x, dict) and x.get("path"):
                x["sha256"] = rqlib.SHA_PENDING
    if not pending:
        warnings = fill_hashes(rows)
    return rows, warnings


def assign_seeds(rows, ns, kinds=SEED_KINDS, reject_collisions=False):
    """Every group's seed of each kind: derive_seed(ns, kind, group). Design /1 re-derives a
    collision with a counter (in sorted group order); design /2 (reject_collisions) refuses it, so a
    group's seed is a function of its namespace and key alone, the same in every plan (v4 §3.5)."""
    for kind in kinds:
        gkey = kind
        groups = sorted({r["groups"][gkey] for r in rows if r["groups"].get(gkey)})
        used, val = {}, {}
        for g in groups:
            k = 0
            while True:
                s = rqlib.derive_seed(ns, kind, g, *([k] if k else []))
                if s not in used:
                    break
                if reject_collisions:
                    raise DesignError(f"{kind} seeds of groups {used[s]} and {g} collide ({s}): a global seed cannot "
                                      "be re-derived per plan; change the seed namespace")
                k += 1
            used[s] = g
            val[g] = s
        for r in rows:
            r.setdefault("seeds", {})[kind] = val[r["groups"][gkey]] if r["groups"].get(gkey) else None
    for r in rows:
        if r["prey_policy"] != "common":
            r["seeds"]["sample"] = None


def fill_hashes(rows):
    """The final plan: every file read ONCE, its SHA-256 computed from that buffer and the same
    buffer parsed and validated (review round 2, P2-4: a file replaced between two reads can no
    longer pass the checks as one checkpoint and be registered as another); then frames,
    versions, template slots, and zero predator floors in every live challenge's prey world."""
    import ckpt
    import common
    cache, warnings = {}, []

    def ages_info(p):
        if p not in cache:
            if not os.path.isfile(p):
                raise DesignError(f"{p}: missing (a final plan needs every file)")
            raw = rqlib.read_bytes(p)
            try:
                ref = common.load_age_reference(json.loads(raw.decode("utf-8")))
            except (common.CommonError, ValueError, UnicodeDecodeError) as e:
                raise DesignError(f"{p}: {e}")
            cache[p] = (rqlib.sha256_bytes(raw), ref)
        return cache[p]

    def info(p):
        if p not in cache:
            if not os.path.isfile(p):
                raise DesignError(f"{p}: missing (a final plan needs every file; --pending plans before they exist)")
            raw = rqlib.read_bytes(p)
            try:
                cp = ckpt.loads(raw.decode("utf-8"), p)
                ckpt.validate(cp, p)
            except (ckpt.CheckpointError, UnicodeDecodeError) as e:
                raise DesignError(str(e))
            m = ckpt.meta(cp)
            m["predator_min_population"] = int((cp.get("config") or {}).get("predatorMinPopulation", 0))
            m["min_population"] = int((cp.get("config") or {}).get("minPopulation", 0))
            m["max_age"] = float((cp.get("config") or {}).get("maxAge", 120.0))
            cache[p] = (rqlib.sha256_bytes(raw), m)
        return cache[p]

    for row in rows:
        # a live arena keeps its prey world's config, both floors included (transplant.hpp; the
        # frozen modes set them to 0): a predator floor would refill predators into the
        # predator-free control, a prey floor (review round 3) would replenish the prey a
        # challenge removes
        if row["assay"] == "live":
            x = row["template"] if row["prey_policy"] == "common" else row["prey"]
            m = info(x["path"])[1]
            if m["predator_min_population"] != 0:
                raise DesignError(f"{row['id']}: a live challenge (or its control) needs predatorMinPopulation 0 in "
                                  f"its prey world {x['path']}")
            if m["min_population"] != 0:
                raise DesignError(f"{row['id']}: a live challenge (or its control) needs a prey minPopulation of 0 "
                                  f"in its prey world {x['path']} (it is {m['min_population']})")
        ax = row.get("ages")
        if isinstance(ax, dict) and ax.get("path"):
            ax["sha256"], ref = ages_info(ax["path"])
            if ref["n"] != row["n_prey"]:
                raise DesignError(f"{ax['path']}: {ref['n']} reference ages, the cells sample {row['n_prey']} prey")
            # (also at final planning, not only at construction: the reference's maxAge is the template's)
            tm = info(row["template"]["path"])[1] if row.get("template") else None
            if tm and ref.get("max_age") is not None and float(ref["max_age"]) != tm["max_age"]:
                raise DesignError(f"{ax['path']}: estimated under prey maxAge {ref['max_age']}, the template "
                                  f"{row['template']['path']} has {tm['max_age']}")
        for role in ("prey", "predators", "template"):
            x = row.get(role)
            if not (isinstance(x, dict) and x.get("path")):
                continue
            sha, m = info(x["path"])
            x["sha256"] = sha
            if role in ("prey", "predators") and m["frame"] != x["frame"]:
                raise DesignError(f"{x['path']}: frame {m['frame']}, registered {x['frame']} ({x['world']} {x['time']})")
            if role == "predators" and m["format_version"] != 2:
                raise DesignError(f"{x['path']}: predator source without brains (format version {m['format_version']})")
            if role == "predators" and m["predators"] == 0:
                warnings.append(f"{x['path']}: no predators (its cells will fail as biological)")
            if role == "prey" and m["prey_alive"] == 0:
                warnings.append(f"{x['path']}: no living prey (its cells will fail as biological)")
            if role == "template" and row["n_prey"] and m["prey_alive"] < row["n_prey"]:
                raise DesignError(f"template {x['path']}: {m['prey_alive']} slots, cells need {row['n_prey']}")
    return sorted(set(warnings))


def _masked(row):
    r = json.loads(json.dumps(row))
    for role, key in SHA_PATHS:
        if isinstance(r.get(role), dict) and key in r[role]:
            r[role][key] = rqlib.SHA_PENDING
    return r


def pending_problems(rows, registered):
    probs = []
    if any(isinstance(r.get(role), dict) and r[role].get(key) not in (None, rqlib.SHA_PENDING)
           for r in registered for role, key in SHA_PATHS):
        probs.append("the registered plan carries real hashes: it is not a pending plan")
    if len(rows) != len(registered):
        return probs + [f"{len(rows)} cells, the registered pending plan has {len(registered)}"]
    for n, (c, r) in enumerate(zip(rows, registered), 1):
        if _masked(c) != r:
            keys = sorted(k for k in set(c) | set(r) if _masked(c).get(k) != r.get(k))
            probs.append(f"line {n} ({c.get('id')}): differs from the registered pending plan in {keys}")
            if len(probs) >= 10:
                probs.append("(further differences not listed)")
                break
    return probs


def plan_seeds(rows, kinds=ENGINE_SEEDS):
    """Engine seeds of a plan, this tooling's rows or tools/invasion's."""
    out = set()
    for r in rows:
        if isinstance(r.get("seeds"), dict):
            out |= {v for k, v in r["seeds"].items() if k in kinds and v is not None}
        for k in ("slot_seed", "donor_seed", "pred_seed", "reseed"):   # an invasion plan row
            if isinstance(r.get(k), int):
                out.add(r[k])
    return out


def avoid_seeds(path):
    """Validated reservations shared with worlds registration and the noise bank."""
    try:
        return rqlib.load_reservations(path)[0]
    except rqlib.ReservationError as exc:
        raise DesignError(str(exc)) from exc


def read_joint_plan(path):
    """--joint accepts assay plan/2 JSONL, with sharing groups; registries go in --avoid."""
    try:
        rows = [json.loads(line) for line in rqlib.read_text(path).splitlines() if line.strip()]
    except (ValueError, OSError) as exc:
        raise DesignError(f"{path}: cannot read --joint assay plan: {exc}") from exc
    if not rows:
        raise DesignError(f"{path}: empty --joint assay plan")
    for number, row in enumerate(rows, 1):
        if not isinstance(row, dict) or row.get("schema") != PLAN_SCHEMA_V2:
            raise DesignError(f"{path}: row {number}: --joint requires assay plan/2 rows; registries go in --avoid")
        groups, seeds = row.get("groups"), row.get("seeds")
        if not isinstance(groups, dict) or not isinstance(seeds, dict):
            raise DesignError(f"{path}: row {number}: --joint plan requires seed/group fields")
        for kind in SEED_KINDS_V2:
            if kind not in groups or kind not in seeds:
                raise DesignError(f"{path}: row {number}: --joint plan requires {kind} seed/group fields")
            group, seed = groups.get(kind), seeds.get(kind)
            if kind != "reseed" and group is None and seed is None:
                continue           # native prey / absent age reference / no donor draw
            if not isinstance(group, str) or not group or type(seed) is not int or seed < 0:
                raise DesignError(f"{path}: row {number}: --joint plan has invalid {kind} seed/group fields")
    return rows


def joint_seed_problems(rows, other):
    """Two plan/2 row sets checked as one seed universe: within each kind, one seed per group key
    and no seed shared by two group keys (an audit plan against production, family plans)."""
    probs = []
    for kind in SEED_KINDS_V2:
        by_group, by_seed = {}, {}
        for r in list(rows) + list(other):
            g = (r.get("groups") or {}).get(kind)
            s = (r.get("seeds") or {}).get(kind)
            if not g or s is None:
                continue
            if by_group.setdefault(g, s) != s:
                probs.append(f"{kind} group {g} has two seeds ({by_group[g]}, {s})")
            if by_seed.setdefault(s, g) != g:
                probs.append(f"{kind} seed {s} is shared by groups {by_seed[s]} and {g}")
    return sorted(set(probs))


def write_plan(rows, path):
    data = b"".join(rqlib.canonical(r) for r in rows)
    rqlib.write_durable(path, data)
    return rqlib.sha256_bytes(data)


# ======================================================================= design /2 (v3)
PLAN_SCHEMA_V2 = "finfolk.redqueen.plan/2"
DESIGN_SCHEMA_V2 = "finfolk.redqueen.design/2"
SPLIT_ROLES = ("training", "validation", "test", "support", "audit", "diagnostic")
SEED_KINDS_V2 = ("sample", "ages", "reseed", "transplant")
V2_DEFAULTS = {"assay": "frozen", "k": 6, "prey_policy": "common", "n_prey": 600, "sampling": "wor-balanced",
               "short_steps": 5000, "long_steps": 20000, "short_horizons": [5000],
               "long_horizons": [5000, 10000, 20000], "log_every": 500, "checkpoint_every": 5000}
STRATA = ("family", "role", "kind", "assay", "prey_world", "pred_world", "prey_time", "pred_time", "lag")


def snapshot_uuid(world_uuid, frame):
    """The global key of one archived snapshot (design v3 §3.5), exactly
    uuid5(NAMESPACE_URL, "finfolk:snapshot:<world uuid>:<frame>") (the frame a decimal integer)."""
    import uuid
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:snapshot:{world_uuid}:{int(frame)}"))


def _v2_settings(design):
    s = dict(V2_DEFAULTS)
    s.update(design.get("defaults") or {})
    for k in ("k", "short_steps", "long_steps", "log_every", "checkpoint_every", "n_prey"):
        if not isinstance(s[k], int) or isinstance(s[k], bool) or s[k] < (0 if k == "k" else 1):
            raise DesignError(f"defaults.{k} must be a whole number")
    if s["sampling"] not in SAMPLINGS:
        raise DesignError(f"sampling {s['sampling']!r}: one of {SAMPLINGS}")
    for kind in ("short", "long"):
        st, hs = s[f"{kind}_steps"], s[f"{kind}_horizons"]
        if st % s["checkpoint_every"] or st % s["log_every"] or not hs or sorted(set(hs)) != hs or any(
                not isinstance(h, int) or not 0 < h <= st or h % s["checkpoint_every"] or h % s["log_every"] for h in hs):
            raise DesignError(f"{kind}: steps and increasing horizons must be multiples of checkpoint_every and "
                              "log_every within the steps")
    if s["short_horizons"][0] != s["long_horizons"][0]:
        raise DesignError("a long cell includes the short measurement: its first horizon must be the short one")
    return s


def read_edges(design):
    """The edge list: design["edges"] inline, or the absolute path of a JSONL file (one edge per line)."""
    e = design.get("edges")
    if isinstance(e, list):
        return e
    if not isinstance(e, str) or not os.path.isabs(e):
        raise DesignError("edges: a list, or the absolute path of a JSONL edge list")
    return [json.loads(ln) for ln in rqlib.read_text(e).split("\n") if ln.strip()]


def select_long(units, fraction, strata, ns):
    """Pre-randomized long subset (design v3 §4.6): of the units whose horizon is not fixed, exactly
    round(fraction x N) are long, apportioned over the strata by largest remainder (ties by a hash
    of the stratum), and within each stratum by a hash order of the unit id. -> (set of long unit
    ids, manifest)."""
    by = {}
    for u in units:
        by.setdefault(tuple(str(u["attrs"].get(k)) for k in strata), []).append(u["id"])
    N = len(units)
    total = int(fraction * N + 0.5)
    exact = {s_: fraction * len(ids) for s_, ids in by.items()}
    quota = {s_: int(x) for s_, x in exact.items()}
    left = total - sum(quota.values())
    order = sorted(by, key=lambda s_: (-(exact[s_] - quota[s_]), rqlib.sha256_bytes(f"{ns}|long-stratum|{s_}".encode())))
    for s_ in order[:max(0, left)]:
        quota[s_] += 1
    chosen = set()
    for s_, ids in by.items():
        ids = sorted(ids, key=lambda i: rqlib.sha256_bytes(f"{ns}|long|{i}".encode()))
        chosen |= set(ids[:quota[s_]])
    man = {"fraction": fraction, "strata": list(strata), "units": N, "long": len(chosen),
           "per_stratum": [{"stratum": list(s_), "units": len(by[s_]), "long": quota[s_]} for s_ in sorted(by)],
           "long_units": sorted(chosen)}
    return chosen, man


MASK_SCHEMA = "finfolk.redqueen.graphmask/2"
RECON_SCHEMA = "finfolk.redqueen.reconciliation/1"
EXCLUSION = ("biological", "technical", "pending")


def attempt_uuid(base, k):
    """worlds.py's (graph.py's, val_block.py's) identity of attempt k of a registry world."""
    import uuid
    return base if not k else str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:attempt:{base}:{k}"))


def _int(x):
    return isinstance(x, int) and not isinstance(x, bool)


REFS_SCHEMA = "finfolk.redqueen.references/1"


def binding_problems(b):
    """Why a design's "availability" binding is malformed (None: well formed): graph_edges_sha256, registry_sha256,
    the registry's burn-in rule (max_restarts, burn_in_frame: 0 for none; Codex #77 r3: the dispositions are checked
    against them) and, when the design reads external (sentinel) references, references_sha256."""
    if not (isinstance(b, dict) and all(isinstance(b.get(k), str) and len(b[k]) == 64
                                        for k in ("graph_edges_sha256", "registry_sha256"))
            and _int(b.get("max_restarts")) and _int(b.get("burn_in_frame")) and b["burn_in_frame"] >= 0
            and set(b) <= {"graph_edges_sha256", "registry_sha256", "max_restarts", "burn_in_frame", "references_sha256"}
            and (b.get("references_sha256") is None or (isinstance(b["references_sha256"], str)
                                                         and len(b["references_sha256"]) == 64))):
        return ("the design registers no well-formed availability binding (availability: graph_edges_sha256, "
                "registry_sha256, max_restarts, burn_in_frame[, references_sha256])")
    return None


def references_index(refs_raw, b):
    """The registered reference assignment (sealing.py's references/1; Codex #77 r2 P2-3) bound by the design's
    binding (its bytes' sha256 = references_sha256) -> {snapshot uuid: its archive sha256} of every registered
    reference snapshot, and the set of their uuids (design worlds the main mask does not cover)."""
    if b.get("references_sha256") is None:
        if refs_raw is not None:
            raise DesignError("--references given, but the design's availability binding registers none")
        return {}, set()
    if refs_raw is None:
        raise DesignError("the design's availability binding registers references: give --references (references/1)")
    if rqlib.sha256_bytes(refs_raw) != b["references_sha256"]:
        raise DesignError("--references is not the registered reference assignment (references_sha256)")
    refs = json.loads(refs_raw.decode("utf-8"))
    if refs.get("schema") != REFS_SCHEMA or not isinstance(refs.get("references"), dict):
        raise DesignError(f"--references: not a reference assignment ({REFS_SCHEMA})")
    snaps, uuids = {}, set()
    for slot, e in sorted(refs["references"].items()):
        if not (isinstance(e, dict) and isinstance(e.get("uuid"), str) and _int(e.get("frame"))
                and isinstance(e.get("sha256"), str) and len(e["sha256"]) == 64):
            raise DesignError(f"--references {slot}: needs its uuid, frame and archive sha256")
        snaps[snapshot_uuid(e["uuid"], e["frame"])] = e["sha256"]
        uuids.add(e["uuid"])
    return snaps, uuids


def mask_binding_problems(design, m, ref_uuids=frozenset()):
    """Why a mask does not describe THIS design's registered intent (Codex #77 r1 P1-2, r2 P1-1 / P1-2 / P2-3) ->
    [problem] (see the module doc, --exclusions): the binding well formed (and, through the generated rows, the
    pending plan's: --against), the mask's own evidence consistent (graph.mask_evidence_problems, the validator
    graph.py and sealing.py share), the mask's graph / registry / block the binding's, every design world covered
    by the mask or a registered reference (ref_uuids), uuids, registered attempts and their identities."""
    import graph as graphlib                   # (the shared mask validator)
    if m.get("schema") != MASK_SCHEMA or not isinstance(m.get("snapshots"), dict) or not isinstance(m.get("worlds"), dict):
        return [f"not an availability mask ({MASK_SCHEMA})"]
    b = design.get("availability")
    why = binding_problems(b)
    if why:
        return [why + ": a mask cannot be checked against its intent"]
    probs = list(graphlib.mask_evidence_problems(m))
    if (m.get("graph") or {}).get("edges_sha256") != b["graph_edges_sha256"]:
        probs.append("the mask was made for another graph than the registered one (edges_sha256)")
    reg, blk = m.get("registry") or {}, m.get("block") or {}
    if reg.get("sha256") != b["registry_sha256"] or blk.get("registry_sha256") != b["registry_sha256"]:
        probs.append("the mask (or its worlds block) binds another registry than the registered one")
    if reg.get("max_restarts") != b["max_restarts"]:
        probs.append(f"the mask's registry allows {reg.get('max_restarts')} restarts, the design {b['max_restarts']}")
    if reg.get("burn_in_frame") != b["burn_in_frame"]:
        probs.append(f"the mask's registry burn-in frame {reg.get('burn_in_frame')} is not the design's {b['burn_in_frame']}")
    dw, mw = design.get("worlds") or {}, m["worlds"]
    covered = set()
    for wn, w in sorted(mw.items()):
        if wn not in dw:
            probs.append(f"the mask's world {wn} is not a design world (another registry)")
            continue
        if w.get("uuid") != dw[wn].get("uuid"):
            probs.append(f"{wn}: the mask's uuid is not the design's")
        k = w.get("attempt")
        if not _int(k) or not 0 <= k <= b["max_restarts"]:
            probs.append(f"{wn}: attempt {k!r} is not a registered attempt (0..{b['max_restarts']})")
        elif w.get("attempt_uuid") != attempt_uuid(w.get("uuid"), k):
            probs.append(f"{wn}: its attempt identity is not attempt {k}'s")
        covered.add(w.get("uuid"))
    if covered & set(ref_uuids):
        probs.append("a registered reference's uuid is also a main-study world of the mask")
    miss = sorted(wn for wn, w in dw.items() if w.get("uuid") not in covered and w.get("uuid") not in ref_uuids)
    if miss:
        probs.append(f"design worlds neither the mask nor the registered references cover (by uuid): {miss[:5]}")
    return probs


def mask_index(m, ref_snaps=None):
    """A (bound) mask -> ({snapshot uuid: its exclusion}, {snapshot uuid: the verified archive sha256 of an
    available snapshot}, the registered references' snapshots included: ref_snaps, references_index's)."""
    out = {s["snapshot"]: s for s in m["snapshots"].values()}
    avail = {snapshot_uuid(w["uuid"], int(f)): sha for w in m["worlds"].values()
             for f, sha in (w.get("available_sha256") or {}).items()}
    avail.update(ref_snaps or {})
    return out, avail


def exclusion_of(row, snaps):
    """(status, endpoint, world, frame, why) of a row whose prey or predator snapshot a mask makes unavailable
    (snaps: {snapshot uuid: {"status", "why"}}, mask_index's; its endpoints' first of biological, technical,
    pending), else None. Matched by the CANONICAL snapshot identity, never the display label (Codex #77 r1 P2-4:
    an alias's rows are excluded as its world's)."""
    best = None
    for role in ("prey", "predators"):
        x = row.get(role)
        if not (isinstance(x, dict) and x.get("world") is not None):
            continue                          # (a random / scripted source, or the predator-free control)
        s = snaps.get(x.get("snapshot"))
        if s and (best is None or EXCLUSION.index(s["status"]) < EXCLUSION.index(best[0])):
            best = (s["status"], role, x["world"], x["frame"], s.get("why"))
    return best


def available_problems(rows, excluded, avail):
    """Every snapshot an EXECUTABLE row reads must be one the mask verified, with the bytes it verified (its
    archive sha256) -> [problem]."""
    probs = []
    for r in rows:
        if r["id"] in excluded:
            continue
        for role in ("prey", "predators"):
            x = r.get(role)
            if not (isinstance(x, dict) and x.get("world") is not None):
                continue
            want = avail.get(x.get("snapshot"))
            if want is None:
                probs.append(f"{r['id']}: its {role} snapshot {x['world']}:{x['frame']} is neither available nor "
                             "excluded in the mask (unsupported)")
            elif x.get("sha256") != want:
                probs.append(f"{r['id']}: its {role} snapshot {x['world']}:{x['frame']} does not hash to the mask's "
                             "verified archive object")
    return probs


def reconciliation(rows, excluded, pending_path, pending_sha, mask_path, mask_raw, m, plan_sha, design_binding=None):
    """The reconciliation receipt (Annex H D6 rule 27): the scheduled cells (the registered pending plan's,
    every one), the executable ones (written: exactly those rows, hashes filled) and every excluded cell
    with its evidence-backed cause; counts by role, primary family and horizon; the design's registered
    availability binding and the mask's graph, registry, block and every world's attempt identity."""
    def tally(key):
        out = {}
        for r in rows:
            c = out.setdefault(str(r.get(key)), {"scheduled": 0, "executable": 0, **{k: 0 for k in EXCLUSION}})
            c["scheduled"] += 1
            c[excluded[r["id"]][0] if r["id"] in excluded else "executable"] += 1
        return out
    n_ex = {k: sum(1 for v in excluded.values() if v[0] == k) for k in EXCLUSION}
    return {"schema": RECON_SCHEMA,
            "pending_plan": {"path": os.path.abspath(pending_path), "sha256": pending_sha},
            "mask": {"path": os.path.abspath(mask_path), "sha256": rqlib.sha256_bytes(mask_raw),
                     "graph": m.get("graph"), "registry": m.get("registry"), "block": m.get("block"),
                     "attempts": {w: {"uuid": v.get("uuid"), "attempt": v.get("attempt"),
                                      "attempt_uuid": v.get("attempt_uuid")} for w, v in sorted(m["worlds"].items())}},
            "binding": design_binding,
            "scheduled": len(rows), "executable": len(rows) - len(excluded), "excluded": n_ex,
            "by_role": tally("role"), "by_primary_family": tally("primary_family"), "by_horizon": tally("horizon"),
            "rows": [{"id": r["id"], "unit": r["unit"], "role": r["role"], "primary_family": r["primary_family"],
                      "horizon": r["horizon"], "status": e[0], "endpoint": e[1], "world": e[2], "frame": e[3],
                      "why": e[4]} for r in rows for e in [excluded.get(r["id"])] if e],
            "plan_sha256": plan_sha,
            "rules": "every executable cell is the registered pending cell with its hashes filled (seeds, groups, "
                     "long-subset membership and every other field unchanged: the surviving long pool is never "
                     "re-randomized); every other scheduled cell is listed with its cause; nothing else is omitted. "
                     "A technical exclusion is to be repaired where possible; none is a biological exclusion"}


def expand_v2(design, pending=False, exclusions=None, excluded_out=None):
    """design /2 -> (rows, warnings, long-subset manifest). See the module doc ("Design /2").
    exclusions (final plans only): a bound mask's exclusions by snapshot uuid (mask_index); the rows it makes
    unavailable are generated as registered (pending hashes) but never read, and recorded in excluded_out
    {row id: exclusion_of}."""
    ns = design.get("seed_namespace")
    if not isinstance(ns, str) or not ns:
        raise DesignError("seed_namespace is required")
    times = design.get("times") or {}
    for lab, fr in times.items():
        _name("time", lab)
        if not isinstance(fr, int) or fr < 0:
            raise DesignError(f"time {lab}: frame must be a whole number >= 0")
    for wn, w in (design.get("worlds") or {}).items():
        _name("world", wn)
        if not isinstance(w.get("uuid"), str) or not w["uuid"]:
            raise DesignError(f"world {wn}: uuid is required")
    templates = design.get("templates") or []
    if any(not isinstance(t, str) or not os.path.isabs(t) for t in templates):
        raise DesignError("templates: absolute paths")
    ages = design.get("age_reference")
    if ages is not None and (not isinstance(ages, str) or not os.path.isabs(ages)):
        raise DesignError("age_reference: an absolute path (or null for newborn ages)")
    R = design.get("replicates")
    if not isinstance(R, int) or R < 1:
        raise DesignError("replicates: a whole number >= 1")
    s = _v2_settings(design)
    lg = design.get("long") or {}
    fraction = lg.get("fraction", 0.125)
    strata = lg.get("strata", ["family", "prey_world"])
    if not 0 <= fraction <= 1 or any(k not in STRATA for k in strata):
        raise DesignError(f"long: fraction in [0, 1], strata among {STRATA}")

    def ref(wn, label):
        if wn not in design["worlds"]:
            raise DesignError(f"unknown world {wn}")
        if label not in times:
            raise DesignError(f"unknown time {label}")
        wu = design["worlds"][wn]["uuid"]
        return {"world": wn, "uuid": wu, "snapshot": snapshot_uuid(wu, times[label]), "time": label,
                "frame": times[label], "path": snapshot_path(design, wn, label)}

    priority = lg.get("family_priority") or []
    if not isinstance(priority, list) or any(not isinstance(f, str) for f in priority):
        raise DesignError("long.family_priority: a list of family names (the primary stratum of a merged pair)")
    units, endpoints = {}, {}
    for n, e in enumerate(read_edges(design), 1):
        if not isinstance(e, dict) or not isinstance(e.get("prey"), dict):
            raise DesignError(f"edge {n}: needs prey {{world, time}}")
        role = e.get("role")
        if role not in SPLIT_ROLES:
            raise DesignError(f"edge {n}: role {role!r}, one of {SPLIT_ROLES}")
        fam = _name("family", e.get("family"))
        space = e.get("namespace")
        if role == "audit":            # (v4 §7.5: an independently seeded remeasurement, controls too)
            space = space or "audit"
            if space == "main":
                raise DesignError(f"edge {n}: an audit edge needs an independent namespace, not 'main'")
        space = _name("namespace", space or "main")
        exception = e.get("support_exception", False)
        if exception not in (True, False) or (exception and role != "support"):
            raise DesignError(f"edge {n}: support_exception is for a support edge only (v4 §7.1)")
        policy = e.get("prey_policy", s["prey_policy"])
        assay = e.get("assay", s["assay"])
        if policy not in POLICIES or assay not in ASSAYS:
            raise DesignError(f"edge {n}: prey_policy / assay")
        prey = ref(e["prey"].get("world"), e["prey"].get("time"))
        p = e.get("predators")
        if p is None:
            kind, preds, K, ptag = "nopred", None, 0, "none"
        elif isinstance(p, dict) and "source" in p:
            # (Codex #74 r1 P2-3) a source endpoint is EXACTLY one permitted dict: never mixed with a world or
            # time (it would fall through to a neural donor and lose its source), never an unknown source
            if p not in ({"source": "random"}, {"source": "scripted"}):
                raise DesignError(f"edge {n}: a predator source is exactly {{source: random}} or {{source: scripted}}, "
                                  f"never mixed with other keys or another source (got {p})")
            if p["source"] == "scripted" and assay == "live":
                raise DesignError(f"edge {n}: scripted hunters are fixed Stage A predators: assay frozen or "
                                  "frozen-newborn, never live (the engine refuses it)")
            K = e.get("k", s["k"])                    # (scripted: K fresh Stage A hunters, the H-C benchmark)
            kind, preds, ptag = "assay", {"source": p["source"]}, p["source"]
        elif isinstance(p, dict):
            K = e.get("k", s["k"])
            kind, preds = "assay", ref(p.get("world"), p.get("time"))
            ptag = f"{preds['world']}.{preds['time']}"
        else:
            raise DesignError(f"edge {n}: predators must be {{world, time}}, {{source: random | scripted}} or null")
        if kind == "assay" and (not isinstance(K, int) or K < 1):
            raise DesignError(f"edge {n}: k must be >= 1")
        hz = e.get("horizon")
        if hz not in (None, "short", "long"):
            raise DesignError(f"edge {n}: horizon short, long or absent (the pre-randomized long subset)")
        if policy == "common" and not templates:
            raise DesignError("the common prey policy needs 'templates'")
        label = (f"{prey['world']}.{prey['time']}~{ptag}.{policy}.{assay}.k{K}"
                 + ("" if space == "main" else f".{space}"))
        # the pair's identity is canonical: snapshot UUIDs, not display labels (aliases merge)
        pkey = preds["snapshot"] if preds and preds.get("snapshot") else ptag
        ukey = (prey["snapshot"], pkey, policy, assay, K, space)
        lag = (preds["frame"] - prey["frame"]) if preds and preds.get("world") == prey["world"] else "cross"
        attrs = {"role": role, "kind": kind, "assay": assay, "prey_world": prey["world"],
                 "pred_world": preds.get("world") if preds else ptag, "prey_time": prey["time"],
                 "pred_time": preds.get("time") if preds else ptag, "lag": lag}
        content = {"prey": prey["snapshot"], "prey_path": prey["path"], "predators": pkey,
                   "pred_path": preds.get("path") if preds else None, "policy": policy, "assay": assay, "k": K,
                   "role": role, "space": space, "kind": kind}
        # split roles are per endpoint pair, across condition versions (v4 §7.1), but explicit
        # support exceptions
        if not exception:
            ek = (prey["snapshot"], pkey, space)
            if endpoints.setdefault(ek, (role, label))[0] != role:
                raise DesignError(f"edge {n}: {label} is {role}, but {endpoints[ek][1]} (the same endpoints) is "
                                  f"{endpoints[ek][0]}: every condition version of a pair keeps one role "
                                  "(mark a support exception with support_exception)")
        if ukey in units:
            u = units[ukey]
            if u["content"] != content:
                raise DesignError(f"edge {n}: pair {label} (= {u['label']}) appears twice with different content, "
                                  "files or roles (all replicates, horizons and modes of a pair stay together)")
            if hz is not None and u["horizon"] not in (None, hz):
                raise DesignError(f"edge {n}: pair {label} has two horizons")
            u["horizon"] = u["horizon"] or hz
            u["families"].add(fam)
            u["edges"].add(e.get("edge", f"line{n}"))
            u["labels"].add(label)
            if (label, prey["world"], prey["time"]) < (u["label"], u["prey"]["world"], u["prey"]["time"]):
                u.update(label=label, prey=prey, preds=preds, attrs=attrs)    # (the canonical display)
            continue
        units[ukey] = {"label": label, "labels": {label}, "content": content, "prey": prey, "preds": preds,
                       "horizon": hz, "families": {fam}, "attrs": attrs, "edges": {e.get("edge", f"line{n}")}}
    # the primary stratum of a pair listed by several families: registered priority, then name
    rank = {f: i for i, f in enumerate(priority)}
    byid = {}
    for u in units.values():
        u["id"] = u["label"]
        u["primary_family"] = min(u["families"], key=lambda f: (rank.get(f, len(rank)), f))
        u["attrs"]["family"] = u["primary_family"]
        if u["id"] in byid:
            raise DesignError(f"pair label {u['id']} names two different pairs")
        byid[u["id"]] = u
    free = [u for u in byid.values() if u["horizon"] is None]
    long_ids, long_man = select_long(free, fraction, strata, ns)
    rows = []
    for uid in sorted(byid):
        u = byid[uid]
        c = dict(u["content"], prey=u["prey"], predators=u["preds"])
        is_long = u["horizon"] == "long" or (u["horizon"] is None and uid in long_ids)
        for r in range(R):
            pk = f"{c['space']}|{c['prey']['snapshot']}|r{r:02d}"
            if c["kind"] == "nopred":
                qk = f"{pk}|none"
            elif c["predators"].get("source") in ("random", "scripted"):
                qk = f"{c['space']}|{c['predators']['source']}-k{c['k']}|r{r:02d}"
            else:
                qk = f"{c['space']}|{c['predators']['snapshot']}|r{r:02d}"
            common = c["policy"] == "common"
            groups = {"common": pk if common else None, "sample": pk if common else None,
                      "ages": pk if (common and ages) else None, "reseed": pk, "transplant": qk,
                      "prey": pk, "pred": None if c["kind"] == "nopred" else qk}
            rows.append({
                "schema": PLAN_SCHEMA_V2, "id": f"{uid}.r{r:02d}", "design": design.get("name", ""),
                "unit": uid, "edges": sorted(u["edges"]), "families": sorted(u["families"]),
                "primary_family": u["primary_family"], "aliases": sorted(u["labels"] - {uid}), "role": c["role"],
                "namespace": c["space"], "kind": c["kind"], "prey": dict(c["prey"]),
                "predators": dict(c["predators"]) if c["predators"] else None,
                "template": {"index": r % len(templates), "path": templates[r % len(templates)]} if common else None,
                "ages": {"path": ages} if (common and ages) else None,
                "prey_policy": c["policy"], "n_prey": s["n_prey"] if common else None,
                "sampling": s["sampling"] if common else None, "assay": c["assay"], "k": c["k"],
                "horizon": "long" if is_long else "short",
                "steps": s["long_steps"] if is_long else s["short_steps"],
                "horizons": list(s["long_horizons"] if is_long else s["short_horizons"]),
                "log_every": s["log_every"], "checkpoint_every": s["checkpoint_every"], "replicate": r,
                "groups": groups,
                "expected": {"checkpoint_steps": list(range(s["checkpoint_every"],
                                                            (s["long_steps"] if is_long else s["short_steps"]) + 1,
                                                            s["checkpoint_every"]))},
                # (Codex #77 r2 P1-1: the registered availability binding is part of every registered row, so
                #  --against compares it: a substituted registry / graph / restart allowance is refused)
                **({"availability": design["availability"]} if design.get("availability") is not None else {})})
    assign_seeds(rows, ns, SEED_KINDS_V2, reject_collisions=True)
    for row in rows:
        for role in ("prey", "predators", "template", "ages"):
            x = row.get(role)
            if isinstance(x, dict) and x.get("path"):
                x["sha256"] = rqlib.SHA_PENDING
    excluded = {} if excluded_out is None else excluded_out
    if exclusions is not None:
        if pending:
            raise DesignError("exclusions apply to a final plan, never to the pending (registered) one")
        for row in rows:                    # (exclusions: mask_index's, by snapshot uuid: aliases included)
            e = exclusion_of(row, exclusions)
            if e:
                excluded[row["id"]] = e
    warnings = [] if pending else fill_hashes([r for r in rows if r["id"] not in excluded])
    long_man["design"] = design.get("name", "")
    return rows, warnings, long_man


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("design")
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--against")
    ap.add_argument("--avoid", action="append", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--long-manifest", help="(design /2) write the pre-randomized long subset's manifest here "
                                            "(after every check passed; it names the plan's sha256)")
    ap.add_argument("--joint", action="append", default=[], metavar="PLAN",
                    help="(design /2) another plan (an audit's, production's) checked jointly: no seed value "
                         "shared by two different groups, no group with two seeds (repeatable: the generated "
                         "rows and every --joint plan form ONE seed universe, checked once)")
    ap.add_argument("--exclusions", metavar="MASK.json",
                    help="(design /2, with --against and --reconciliation) graph.py mask's availability mask: the "
                         "registered cells it makes unavailable are left out of the executable plan, with a receipt")
    ap.add_argument("--reconciliation", metavar="OUT.json", help="the reconciliation receipt (with --exclusions)")
    ap.add_argument("--references", metavar="REFS.json",
                    help="(with --exclusions) the registered reference assignment (references/1) the design's binding "
                         "names (references_sha256): its sentinel snapshots and their archive sha256")
    a = ap.parse_args(argv)
    if a.pending and a.against:
        ap.error("--pending and --against exclude each other")
    if (a.exclusions is None) != (a.reconciliation is None) or (a.exclusions and not a.against):
        ap.error("--exclusions needs --against and --reconciliation (and --reconciliation needs --exclusions)")
    long_man, excluded, mask_raw, m, snaps, avail = None, {}, None, None, None, None
    try:
        design = json.loads(rqlib.read_text(a.design))
        if a.exclusions:
            mask_raw = rqlib.read_bytes(a.exclusions)
            m = json.loads(mask_raw.decode("utf-8"))
            if design.get("schema") != DESIGN_SCHEMA_V2:
                raise DesignError("--exclusions needs a design /2")
            why = binding_problems(design.get("availability"))
            if why:
                raise DesignError(why)
            ref_snaps, ref_uuids = references_index(rqlib.read_bytes(a.references) if a.references else None,
                                                    design["availability"])
            probs = mask_binding_problems(design, m, ref_uuids)   # (Codex #77 r1 P1-2, r2: BEFORE any exclusion)
            if probs:
                raise DesignError(f"{a.exclusions} does not describe the registered intent: " + "; ".join(probs[:5]))
            snaps, avail = mask_index(m, ref_snaps)
        if design.get("schema") == DESIGN_SCHEMA_V2:
            rows, warnings, long_man = expand_v2(design, pending=a.pending, exclusions=snaps, excluded_out=excluded)
            if avail is not None:
                probs = available_problems(rows, excluded, avail)
                if probs:
                    raise DesignError(f"{len(probs)} executable cells read snapshots the mask does not verify: "
                                      + "; ".join(probs[:5]))
        else:
            rows, warnings = expand(design, pending=a.pending)
        if a.joint:           # ONE seed universe: the generated rows and every --joint plan together
            other = []
            for p in a.joint:
                other += read_joint_plan(p)
            probs = joint_seed_problems(rows, other)
            if probs:
                raise DesignError(f"jointly with {', '.join(a.joint)}: " + "; ".join(probs[:5]))
    except (DesignError, OSError, ValueError, KeyError) as e:
        print(f"plan.py: {e}", file=sys.stderr)
        return 2
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if a.against:
        reg_raw = rqlib.read_bytes(a.against)
        reg = [json.loads(ln) for ln in reg_raw.decode("utf-8").split("\n") if ln.strip()]
        probs = pending_problems(rows, reg)        # (EVERY scheduled cell, the excluded ones included)
        if probs:
            print(f"not the registered pending plan {a.against}:", file=sys.stderr)
            for p in probs:
                print(f"  {p}", file=sys.stderr)
            return 2
        print(f"the registered pending plan {a.against} with its {len(rows) - len(excluded)} executable cells' "
              f"hashes filled in" + (f" ({len(excluded)} excluded by {a.exclusions})" if a.exclusions else ""),
              file=sys.stderr)
    if a.avoid:
        old = set()
        for p in a.avoid:
            try:
                reserved, record = rqlib.load_reservations(p)
            except rqlib.ReservationError as exc:
                print(f"plan.py: {exc}", file=sys.stderr)
                return 2
            old |= reserved
            print(f"reservations: {rqlib.canonical(record).decode().strip()}", file=sys.stderr)
        hit = sorted(plan_seeds(rows) & old)
        if hit:
            print(f"{len(hit)} engine seed(s) also used by {a.avoid}: {hit[:10]}", file=sys.stderr)
            return 2
        print(f"engine seeds checked against {len(a.avoid)} archived plan(s): no overlap", file=sys.stderr)
    sha = write_plan([r for r in rows if r["id"] not in excluded], a.out)
    if a.exclusions:
        rqlib.write_durable(a.reconciliation, rqlib.canonical(reconciliation(
            rows, excluded, a.against, rqlib.sha256_bytes(reg_raw), a.exclusions, mask_raw, m, sha,
            design.get("availability"))))
        rows = [r for r in rows if r["id"] not in excluded]
    if a.long_manifest and long_man is not None:      # (only for a plan that passed every check)
        rqlib.write_durable(a.long_manifest, rqlib.canonical(dict(long_man, plan_sha256=sha, plan=os.path.abspath(a.out))))
    kinds = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    print(f"{'pending ' if a.pending else ''}plan {a.out}: {len(rows)} cells ({kinds}), sha256 {sha}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

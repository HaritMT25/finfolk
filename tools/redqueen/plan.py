#!/usr/bin/env python3
"""plan.py: expand a Red Queen design (JSON) into a runner plan (JSONL, schema finfolk.redqueen.plan/1).

    plan.py DESIGN.json --pending --out PLAN.pending.jsonl
    plan.py DESIGN.json [--against PLAN.pending.jsonl] [--avoid OLD_PLAN.jsonl ...] --out PLAN.jsonl

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
SHA_PATHS = (("prey", "sha256"), ("predators", "sha256"), ("template", "sha256"))


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


def assign_seeds(rows, ns):
    for kind in SEED_KINDS:
        gkey = kind
        groups = sorted({r["groups"][gkey] for r in rows if r["groups"].get(gkey)})
        used, val = set(), {}
        for g in groups:
            k = 0
            while True:
                s = rqlib.derive_seed(ns, kind, g, *([k] if k else []))
                if s not in used:
                    break
                k += 1
            used.add(s)
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
    cache, warnings = {}, []

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
            cache[p] = (rqlib.sha256_bytes(raw), m)
        return cache[p]

    for row in rows:
        # a live arena keeps its prey world's config, predator floor included (transplant.hpp): a
        # floor would refill predators into the predator-free control and change the challenge's K
        if row["assay"] == "live":
            x = row["template"] if row["prey_policy"] == "common" else row["prey"]
            if info(x["path"])[1]["predator_min_population"] != 0:
                raise DesignError(f"{row['id']}: a live challenge (or its control) needs predatorMinPopulation 0 in "
                                  f"its prey world {x['path']}")
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


def write_plan(rows, path):
    data = b"".join(rqlib.canonical(r) for r in rows)
    rqlib.write_durable(path, data)
    return rqlib.sha256_bytes(data)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("design")
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--against")
    ap.add_argument("--avoid", action="append", default=[])
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.pending and a.against:
        ap.error("--pending and --against exclude each other")
    try:
        design = json.loads(rqlib.read_text(a.design))
        rows, warnings = expand(design, pending=a.pending)
    except (DesignError, OSError, ValueError, KeyError) as e:
        print(f"plan.py: {e}", file=sys.stderr)
        return 2
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if a.against:
        reg = [json.loads(ln) for ln in rqlib.read_text(a.against).split("\n") if ln.strip()]
        probs = pending_problems(rows, reg)
        if probs:
            print(f"not the registered pending plan {a.against}:", file=sys.stderr)
            for p in probs:
                print(f"  {p}", file=sys.stderr)
            return 2
        print(f"the registered pending plan {a.against} with its {len(rows)} cells' hashes filled in", file=sys.stderr)
    if a.avoid:
        old = set()
        for p in a.avoid:
            old |= plan_seeds(json.loads(ln) for ln in rqlib.read_text(p).split("\n") if ln.strip())
        hit = sorted(plan_seeds(rows) & old)
        if hit:
            print(f"{len(hit)} engine seed(s) also used by {a.avoid}: {hit[:10]}", file=sys.stderr)
            return 2
        print(f"engine seeds checked against {len(a.avoid)} archived plan(s): no overlap", file=sys.stderr)
    sha = write_plan(rows, a.out)
    kinds = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    print(f"{'pending ' if a.pending else ''}plan {a.out}: {len(rows)} cells ({kinds}), sha256 {sha}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

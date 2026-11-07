#!/usr/bin/env python3
"""worlds.py: register the Red Queen study's 48 evolutionary histories and run them (design v3 §2, §13).

    worlds.py register --arena config/arena.selected.json --namespace NS --out STUDY/config/worlds.json
                       [--blocks 8] [--per-block C=4,A=1,B=1] [--c-founders 6] [--avoid FILE ...]
                       [--total-steps N] [--checkpoint-every N] [--log-every N] [--allow-placeholder]
    worlds.py f1 --root STUDY --binary EVO_BOIDS [--archive-root DIR] [--world ID ...]
    worlds.py launch --root STUDY --binary EVO_BOIDS [--archive-root DIR] [--workers 10]
                     [--mem-min-mb 8192] [--disk-min PATH:MB ...] [--retries 3]
                     [--on-extinction stop|continue] [--prune-local] [--retry-failed] [--poll 30]
    worlds.py verify-f1 --root STUDY [--world ID ...]
    worlds.py stitch --root STUDY --world ID [--partial]
    worlds.py status --root STUDY
    worlds.py design-block --root STUDY --out worlds_block.json

THE REGISTRY (register; deterministic: the same inputs give the same bytes; an existing registry
is never replaced by other bytes: changed seeds, treatments or schedule need a new study root).
Eight randomized blocks of four C, one A and one B history (48 worlds; --per-block for tests).
Within each block the treatment order is a seeded permutation (namespace, "block-order", block),
so a world's id does not reveal its treatment by position. Each world has an id (w01..w48), a
UUID (uuid5 of the namespace and id), and a founder seed derived from (namespace, "founder", id),
unique, and refused if it occurs in any --avoid file (integers, or any JSON / JSONL whose keys
contain "seed": the archived plans and reservations of other streams).

THE ARENA (config/arena.selected.json, schema finfolk.redqueen.arena/1: {"status": "selected" |
"placeholder", "common": {...}, "treatments": {"C": {...}, "A": {...}, "B": {...}}}, engine flag
name -> value). A world's flags are "common" overlaid with its treatment's block, checked against
a typed table of the engine's flags (an unknown flag, a bool or string for a number, a non-finite
number: refused). Required explicitly, never left to an engine default: the environment
(population, min-pop, predator-min-pop, max-pop, target-food, food-spawn, food-amp, food-patches,
current, move-cost, gene-cost: equal in every treatment), and for C and B the economy (predators,
predator-economy, predator-max-pop, predator-max-age, predator-cooldown, predator-meal). Both
floors must be the integer 0 (design §2.2; the engine's own prey floor default is 50) and are
always passed. C: --predator-brain and exactly --c-founders (6) founders; B: no brain, and the
same economics and kinematics as C; A: a fixed positive --predators count, no economy, the same
kinematics (speed, perception, capture radius, cooldown). --predator-primer, --predator-inherit
and --body-model stay off, and flags this tool sets itself (seed, schedule, logging, checkpoints)
are refused. An unresolved "SELECTED_*" value or a placeholder arena is refused unless
--allow-placeholder; the registry then records the taint, and every later command refuses it
unless it is given --allow-placeholder again (tests only).

THE STUDY ROOT. The first f1 or launch binds STUDY to its registry: STUDY/study.json records the
registry's sha256 and the archive root (default STUDY/archive); every later command refuses a
different registry or archive root. The engine is pinned in STUDY/bin (its sha256) and probed
once: it must be the serial build (its checkpoints say "resume is bit-exact").

THE HISTORIES (launch: a resumable supervisor; one runner per root, flock). Every world runs as a
sequence of SEGMENTS in STUDY/worlds/<id>/: seg000 from the founder seed (only once its F1 is
archived by the pinned engine), and after an interruption the next segment resumes the latest
ACCEPTED checkpoint without reseeding (the random streams continue from the checkpoint, so the
history is the uninterrupted one, bit for bit, in the serial build). Before a world's first resume
its F1 must have passed the F1 verification (below) with the pinned engine; the supervisor runs it
as a job of its own if it has not. Engine flags: the registry's, plus --headless (total - start),
--no-render, --log-every, --flush-every 1, --checkpoint-every, --save-checkpoint ckpt/end.json,
--csv segNNN/run.csv, --wiring-log, and for C --predator-log (its lineage log, never overwritten:
each segment has its own). Up to --workers engines run at once, each in its own process group with
PR_SET_PDEATHSIG = SIGKILL (none outlives the supervisor), at nice 19, admitted only while the
memory and disk guards pass (as run.py's, fail closed). A segment that ends without progress (the
same resume point as after its previous failure) --retries times in a row makes the world
"failed". STOP (STUDY/STOP) stops admission; SIGTERM stops every engine (they resume at the next
start) and exits 130.

ACCEPTANCE (STUDY/worlds/<id>/accept.jsonl, append-only, fsync'd). Checkpoint F of a segment is
accepted, in frame order, once it is complete (the main CSV has a row past F, or the engine has
ended), parses and validates, declares the serial build, carries the registered configuration
(both floors 0, every registered flag), is archived (below), and every log of its segment reaches
F: the main CSV, the prey wiring log, and for C predators.csv and pwiring contiguous every
log_every through F, and the lineage log's rows through F agree with the checkpoint's counters
(buds, starvation and age deaths, refills, founders or loaded predators, and the predators alive).
The logs are fsync'd, then the record binds the checkpoint's sha256 to each log's new bytes (the
offsets and sha256 of the part since the previous acceptance). A resume starts from the latest
record whose log bytes still verify, in a segment whose own start is such a record (back to the
founder segment); a lost or damaged log tail therefore sends the history back to the last point
it fully covers, to be redone. A world is "done" only when the final frame is accepted; a world
found at its final accepted frame is finalized without another segment. A local checkpoint that
does not parse or is not at its frame (a torn write) is moved to ckpt/quarantine/ and recorded in
quarantine.jsonl, and the world resumes from its last accepted checkpoint.

ARCHIVE. Every complete periodic checkpoint (and F1) is copied verified into ARCHIVE/worlds/<id>/
(a temporary file, fsync'd, hashed, read-only 0444, renamed, directory fsync'd) and recorded in
STUDY/worlds/<id>/archive.jsonl. A checkpoint rewritten by a resumed segment must have its
archived bytes (determinism; a difference stops the world as "failed"). An archived copy found
missing, damaged or writable is repaired from verified local bytes (refused once finalized).
When a world ends ("done" or "extinct"), its archive is audited and finalized: a FINALIZED marker
(published atomically: the world, its status and archived frames), every file 0444, the directory
0555, both fsync'd: the contract run.py --link-sources checks. Every start reconciles the
finalization of the terminal worlds. --prune-local deletes local copies of accepted checkpoints
except the two latest, after verifying their archived copies.

BIOLOGY. A guild that reaches zero in the main CSV (prey: population; predators of C and B:
predator_pop) is recorded in STUDY/availability.jsonl (append-only, fsync'd: world, guild, first
frame, the archived frames before it); a guild's first zero is the minimum over its records. A
restart first scans every segment's main CSV, so a zero the previous supervisor did not see is
recorded with its earliest frame ("recovered"). Extinction is absorbing (both floors are zero);
--on-extinction stop (default) then ends the world as "extinct" without advancing it (its valid
pre-extinction snapshots stay archived; nothing is refilled or replaced).

F1 (f1, verify-f1). F1 is the first step of an identically seeded founder replay (the same flags,
--headless 1) by the pinned engine, with the registered configuration, archived as F1.json (its
record names the engine's sha256). verify-f1 resumes it for checkpoint_every - 1 steps and
requires the result to be byte-identical to the history's archived first periodic checkpoint: F1
then lies on the history's own trajectory, and the engine resumes exactly. Its record
(f1_verify.json) names the engine's sha256.

STITCH. The logs of the chain of segments that leads to the latest accepted checkpoint, joined
into the uninterrupted run's logs: each segment contributes its accepted log bytes up to the
checkpoint the next one resumed (the last one up to the endpoint), every byte verified against
the acceptance records; a resumed segment's lineage log loses its L rows (the predators it
loaded, already in the earlier log). Corrections: the main CSV's first row of a resumed segment
carries the loaded world's history in its eight interval columns (a v0.26 convention), so the
counters of the checkpoint it resumed are subtracted; the prey wiring log's step column is
segment-relative and becomes the frame. Every log is required; the dense logs must be contiguous
every log_every up to the endpoint and the lineage log in frame order; a "done" world's endpoint
must be the final frame (other worlds: "extinct", or any with --partial). The stitched files equal
the uninterrupted run's except the main CSV's two timing columns and repro_components (a trailing
pairing window that restarts empty on a resume), as stitched/manifest.json records.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ckpt  # noqa: E402
import rqlib  # noqa: E402
import run as runlib  # noqa: E402

# (worlds/1, worldstate/1 and availability/1 kept, as design v4 (d) asks: the new fields are additive;
#  an availability reader takes a guild's first zero as the minimum over its records)
WORLDS_SCHEMA = "finfolk.redqueen.worlds/1"
ARENA_SCHEMA = "finfolk.redqueen.arena/1"
STUDY_SCHEMA = "finfolk.redqueen.study/1"
STATE_SCHEMA = "finfolk.redqueen.worldstate/1"
AVAIL_SCHEMA = "finfolk.redqueen.availability/1"
ACCEPT_SCHEMA = "finfolk.redqueen.accept/1"
BINARY_SCHEMA = "finfolk.redqueen.binary/1"
QUARANTINE_SCHEMA = "finfolk.redqueen.quarantine/1"
SERIAL = "serial build (resume is bit-exact)"
TREATMENTS = ("C", "A", "B")
C_FOUNDERS = 6
DEFAULT_SCHEDULE = {"total_steps": 200_000_000, "checkpoint_every": 1_000_000, "log_every": 5000}
# flags this tool sets itself, never taken from the arena
RESERVED = {"seed", "headless", "no-render", "log-every", "flush-every", "checkpoint-every", "save-checkpoint",
            "load-checkpoint", "csv", "name", "predator-log", "wiring-log", "reseed-after-load", "predators-from",
            "transplant-count", "transplant-seed", "transplant-out", "assay", "repro-log", "repro-log-max",
            "death-log", "cluster-map", "profile", "transplant-allow-mismatch", "cluster-max", "cluster-epoch",
            "cluster-pca", "cluster-color", "version", "help"}

# The engine's flags (src/app/main.cpp): type, and the checkpoint config key the value lands in.
INT, NUM, SWITCH, ENUM = "an integer", "a number", "a switch (true / false)", "one of"
FLAGS = {
    "population": (INT, None), "min-pop": (INT, "minPopulation"), "max-pop": (INT, "maxPopulation"),
    "target-food": (INT, "targetFood"), "food-spawn": (NUM, "foodSpawnBase"), "food-amp": (NUM, "foodSpawnAmp"),
    "food-energy": (NUM, "foodEnergy"), "pickup-radius": (NUM, "pickupRadius"), "metabolism": (NUM, "metabolicRate"),
    "gene-cost": (NUM, "geneCost"), "move-cost": (NUM, "moveCost"), "max-age": (NUM, "maxAge"),
    "repro-energy": (NUM, "reproEnergy"), "newborn-energy": (NUM, "newbornEnergy"),
    "perception": (NUM, "perceptionRadius"), "interact-radius": (NUM, "interactRadius"),
    "max-neighbors": (INT, "maxNeighbors"), "topological": (SWITCH, None), "fast-tanh": (SWITCH, "fastTanh"),
    "repro-cooldown": (NUM, "reproCooldown"), "interact-cooldown": (NUM, "interactCooldown"),
    "min-speed": (NUM, "minSpeed"), "max-speed": (NUM, "maxSpeed"), "toroidal": (SWITCH, "toroidal"),
    "triangular-motion": (SWITCH, "triangularMotion"), "max-turn-rate": (NUM, "maxTurnRate"),
    "genome-min": (INT, "genomeMinLength"), "genome-max": (INT, "genomeMaxLength"),
    "genome-init-min": (INT, "genomeInitMin"), "genome-init-max": (INT, "genomeInitMax"),
    "mutation": (NUM, "mutationMultiplier"), "repro-max-distance": (NUM, "reproMaxDistance"),
    "repro-soft-width": (NUM, "reproSoftWidth"), "repro-grace": (NUM, "reproGracePeriod"),
    "repro-window": (INT, "reproWindow"), "repro-min-cluster": (INT, "reproMinCluster"),
    "body-model": (SWITCH, "bodyModel"), "body-mutation": (NUM, "bodyMutation"),
    "current": (NUM, "currentStrength"), "current-mode": (ENUM, "currentMode"),
    "current-eddies": (INT, "currentEddies"), "current-core": (NUM, "currentCore"),
    "current-drift": (NUM, "currentDrift"), "gyre-eps": (NUM, "currentGyreEps"),
    "food-patches": (INT, "foodPatches"), "food-patch-radius": (NUM, "foodPatchRadius"),
    "food-drift": (SWITCH, "foodDrift"),
    "predators": (INT, "predatorCount"), "predator-perception": (NUM, "predatorPerception"),
    "predator-speed": (NUM, "predatorSpeed"), "predator-capture-radius": (NUM, "predatorCaptureRadius"),
    "predator-cooldown": (NUM, "predatorCooldown"), "predator-economy": (SWITCH, "predatorEconomy"),
    "predator-metabolism": (NUM, "predatorMetabolism"), "predator-move-cost": (NUM, "predatorMoveCost"),
    "predator-repro-energy": (NUM, "predatorReproEnergy"),
    "predator-newborn-energy": (NUM, "predatorNewbornEnergy"), "predator-meal": (NUM, "predatorMeal"),
    "predator-max-age": (NUM, "predatorMaxAge"), "predator-min-pop": (INT, "predatorMinPopulation"),
    "predator-max-pop": (INT, "predatorMaxPopulation"), "predator-inherit": (SWITCH, "predatorInheritance"),
    "predator-trait-mutation": (NUM, "predatorTraitMutation"), "predator-brain": (SWITCH, "predatorBrain"),
    "predator-mutation": (NUM, "predatorMutation"), "predator-turn-rate": (NUM, "predatorTurnRate"),
    "predator-min-speed": (NUM, "predatorMinSpeed"), "predator-primer": (SWITCH, "predatorPrimer"),
}
ENUMS = {"current-mode": ("eddies", "gyre")}
ENV_REQUIRED = ("population", "min-pop", "predator-min-pop", "max-pop", "target-food", "food-spawn", "food-amp",
                "food-patches", "current", "move-cost", "gene-cost")
ECONOMY_REQUIRED = ("predators", "predator-economy", "predator-max-pop", "predator-max-age", "predator-cooldown",
                    "predator-meal")
ECONOMY_ONLY = ("predator-max-pop", "predator-max-age", "predator-meal", "predator-metabolism", "predator-move-cost",
                "predator-repro-energy", "predator-newborn-energy", "predator-inherit", "predator-trait-mutation")
BRAIN_ONLY = ("predator-mutation", "predator-turn-rate", "predator-min-speed", "predator-primer")
FORBIDDEN = ("predator-primer", "predator-inherit", "body-model")
ZERO = ("min-pop", "predator-min-pop")
POSITIVE = ("population", "max-pop", "predators", "predator-max-pop", "predator-max-age", "predator-cooldown",
            "predator-meal")
NONNEGATIVE = ("target-food", "food-spawn", "food-amp", "food-patches", "current", "move-cost", "gene-cost")
SAME_CB = ("predators", "predator-economy", "predator-min-pop", "predator-max-pop", "predator-max-age",
           "predator-cooldown", "predator-meal", "predator-metabolism", "predator-move-cost", "predator-repro-energy",
           "predator-newborn-energy", "predator-speed", "predator-perception", "predator-capture-radius")
SAME_KINEMATICS = ("predator-speed", "predator-perception", "predator-capture-radius", "predator-cooldown")
# main CSV interval columns and the checkpoint counters a resumed segment's first row must lose
INTERVAL_FIX = (("births_interval", "totalBirths"), ("deaths_interval", "totalDeaths"),
                ("kills_interval", "totalDeathsPredation"), ("deaths_starvation", "totalDeathsStarvation"),
                ("deaths_age", "totalDeathsAge"), ("predator_births_interval", "totalPredatorBirths"),
                ("predator_deaths_starv", "totalPredatorDeathsStarvation"),
                ("predator_deaths_age", "totalPredatorDeathsAge"))
NON_CONTINUABLE = ("elapsed_s", "steps_per_sec", "repro_components")
# lineage-log events and the checkpoint counters they must add up to
LINEAGE_COUNTERS = (("B", "totalPredatorBirths"), ("S", "totalPredatorDeathsStarvation"),
                    ("A", "totalPredatorDeathsAge"), ("R", "totalPredatorReseeds"))
GUILDS = (("prey", "population"), ("predators", "predator_pop"))
CKPT_RE = re.compile(r"^end\.(\d+)\.json$")
_MISSING = object()


class WorldsError(Exception):
    pass


class TornCheckpoint(WorldsError):
    """A local checkpoint that does not parse or is not at its frame: an interrupted write."""


# ================================================================== registry
def _placeholder(v):
    return isinstance(v, str) and v.startswith("SELECTED_")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def flags_to_args(flags):
    """{"population": 600, "predator-brain": True, ...} -> ["--population", "600", "--predator-brain", ...]
    (in flag order; a false switch is left out; integers, including 0, are always passed)."""
    out = []
    for k, v in sorted(flags.items()):
        if v is True:
            out.append("--" + k)
        elif v is False or v is None:
            continue
        elif isinstance(v, float):
            out += ["--" + k, repr(v)]
        else:
            out += ["--" + k, str(v)]
    return out


def treatment_flags(arena, t):
    f = dict(arena.get("common") or {})
    f.update((arena.get("treatments") or {}).get(t) or {})
    return f


def world_flag_problems(f, t, c_founders=C_FOUNDERS):
    """-> (problems, unresolved placeholders) of one treatment's effective flags (the typed table)."""
    probs, unresolved = [], []
    for k, v in f.items():
        if k in RESERVED:
            probs.append(f"{t}: --{k} is set by worlds.py, not the arena")
            continue
        if k not in FLAGS:
            probs.append(f"{t}: --{k} is not an engine flag worlds.py knows")
            continue
        if _placeholder(v):
            unresolved.append(f"{t}: --{k} {v}")
            continue
        typ = FLAGS[k][0]
        ok = {INT: _is_int, NUM: _is_num, SWITCH: lambda x: isinstance(x, bool),
              ENUM: lambda x: x in ENUMS.get(k, ())}[typ](v)
        if not ok:
            probs.append(f"{t}: --{k} {v!r} must be {typ}" + (f" {ENUMS[k]}" if typ == ENUM else ""))

    def num(k):
        v = f.get(k)
        return v if _is_num(v) else None
    for k in ENV_REQUIRED:
        if k not in f:
            probs.append(f"{t}: --{k} must be given explicitly (no engine default)")
    for k, what in (("min-pop", "the prey floor"), ("predator-min-pop", "the predator floor")):
        if num(k) is not None and f[k] != 0:
            probs.append(f"{t}: {what} --{k} must be 0 (design §2.2)")
    for k in POSITIVE:
        if num(k) is not None and f[k] <= 0:
            probs.append(f"{t}: --{k} must be positive")
    for k in NONNEGATIVE:
        if num(k) is not None and f[k] < 0:
            probs.append(f"{t}: --{k} must not be negative")
    for k in FORBIDDEN:
        if f.get(k) is True:
            probs.append(f"{t}: --{k} must stay off (design §2.1)")
    if t in ("C", "B"):
        for k in ECONOMY_REQUIRED:
            if k not in f:
                probs.append(f"{t}: needs an explicit --{k} (the selected economy)")
        if "predator-economy" in f and f["predator-economy"] is not True:
            probs.append(f"{t}: needs --predator-economy")
    if t == "C":
        if f.get("predator-brain") is not True:
            probs.append("C: needs --predator-brain")
        if _is_int(f.get("predators")) and f["predators"] != c_founders:
            probs.append(f"C: --predators {f['predators']}, but {c_founders} founders are registered "
                         "(a different count is a disclosed change: --c-founders)")
    else:
        if f.get("predator-brain"):
            probs.append(f"{t}: scripted predators (no --predator-brain)")
        for k in BRAIN_ONLY:
            if k in f and k not in FORBIDDEN:
                probs.append(f"{t}: --{k} needs the neural predators")
    if t == "A":
        if f.get("predator-economy"):
            probs.append("A: scripted, immortal, fixed-count predators (no --predator-economy)")
        if "predators" not in f:
            probs.append("A: needs a fixed positive --predators count")
        for k in ECONOMY_ONLY:
            if k in f and k not in FORBIDDEN:
                probs.append(f"A: --{k} needs the economy")
    return probs, unresolved


def _norm(v):
    return ("num", float(v)) if _is_num(v) else ("v", repr(v))


def arena_problems(arena, treatments_used, allow_placeholder=False, c_founders=C_FOUNDERS):
    """-> (problems, unresolved placeholders) of an arena for the treatments a registry uses."""
    probs, unresolved = [], []
    if arena.get("schema") != ARENA_SCHEMA:
        probs.append(f"arena schema {arena.get('schema')!r}, expected {ARENA_SCHEMA}")
    if arena.get("status") not in ("selected", "placeholder"):
        probs.append("arena status must be 'selected' or 'placeholder'")
    if arena.get("status") == "placeholder" and not allow_placeholder:
        probs.append("the arena is a placeholder (the sweep has not selected it): --allow-placeholder only for tests")
    eff = {}
    for t in treatments_used:
        if t not in (arena.get("treatments") or {}):
            probs.append(f"the arena has no treatment {t}")
            continue
        eff[t] = treatment_flags(arena, t)
        p, u = world_flag_problems(eff[t], t, c_founders)
        probs += p
        unresolved += u

    def differ(keys, ts):
        out = []
        for k in keys:
            vals = {t: eff[t].get(k, _MISSING) for t in ts}
            if len({_norm(v) if v is not _MISSING else ("missing",) for v in vals.values()}) > 1:
                out.append(k + " " + ", ".join(f"{t}={'(engine default)' if v is _MISSING else v}"
                                               for t, v in vals.items()))
        return out
    env = sorted({k for f in eff.values() for k in f if not k.startswith("predator")})
    for d in differ(env, list(eff)):
        probs.append(f"the common environment differs across treatments: --{d}")
    if "C" in eff and "B" in eff:
        for d in differ(SAME_CB, ["C", "B"]):
            probs.append(f"C and B must share the selected economics and kinematics: --{d}")
    if "A" in eff:
        for o in [t for t in ("C", "B") if t in eff][:1]:
            for d in differ(SAME_KINEMATICS, ["A", o]):
                probs.append(f"A must share the predator kinematics: --{d}")
    if unresolved and not allow_placeholder:
        probs += [f"{u} is unresolved" for u in unresolved]
    return probs, unresolved


def collect_seeds(obj, out=None, key_hint=False):
    """Every integer at or below a key containing "seed" (recursively: {"seeds": {"x": 5}} counts 5)."""
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            collect_seeds(v, out, key_hint or "seed" in str(k).lower())
    elif isinstance(obj, list):
        for v in obj:
            collect_seeds(v, out, key_hint)
    elif isinstance(obj, int) and not isinstance(obj, bool) and key_hint:
        out.add(obj)
    return out


def read_avoid(path):
    """Seeds reserved elsewhere: a file of integers (one per line), a JSON document or JSONL lines."""
    text = rqlib.read_text(path)
    seeds = set()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines and all(re.fullmatch(r"\d+", ln) for ln in lines):
        return {int(ln) for ln in lines}
    try:
        collect_seeds(json.loads(text), seeds)
    except ValueError:
        for ln in lines:
            collect_seeds(json.loads(ln), seeds)
    return seeds


def parse_per_block(spec):
    out = {}
    for part in spec.split(","):
        t, _, n = part.partition("=")
        if t not in TREATMENTS or not n.isdigit():
            raise WorldsError(f"--per-block {spec!r}: expected e.g. C=4,A=1,B=1")
        out[t] = int(n)
    return {t: out.get(t, 0) for t in TREATMENTS}


def register(arena_path, namespace, blocks=8, per_block=None, avoid_paths=(), schedule=None,
             allow_placeholder=False, c_founders=C_FOUNDERS):
    per_block = per_block or {"C": 4, "A": 1, "B": 1}
    schedule = dict(DEFAULT_SCHEDULE, **(schedule or {}))
    if not namespace or not re.fullmatch(r"[A-Za-z0-9._-]+", namespace):
        raise WorldsError("--namespace: letters, digits, '.', '_' and '-'")
    s = schedule
    if s["total_steps"] % s["checkpoint_every"] or s["checkpoint_every"] % s["log_every"]:
        raise WorldsError("the schedule needs total_steps % checkpoint_every == 0 == checkpoint_every % log_every")
    raw = rqlib.read_bytes(arena_path)
    arena = json.loads(raw.decode("utf-8"))
    used = [t for t in TREATMENTS if per_block[t] > 0]
    probs, unresolved = arena_problems(arena, used, allow_placeholder, c_founders)
    if probs:
        raise WorldsError("arena refused: " + "; ".join(probs))
    avoid, avoid_rec = set(), []
    for p in avoid_paths:
        a = read_avoid(p)
        avoid |= a
        avoid_rec.append({"path": os.path.abspath(p), "sha256": rqlib.sha256_file(p), "seeds": len(a)})
    worlds, used_seeds, idx = [], set(), 0
    for b in range(1, blocks + 1):
        order = [t for t in TREATMENTS for _ in range(per_block[t])]
        rqlib.SplitMix64(rqlib.derive64(namespace, "block-order", b)).shuffle(order)
        for slot, t in enumerate(order):
            idx += 1
            wid = f"w{idx:02d}"
            k = 0
            while True:
                seed = rqlib.derive_seed(namespace, "founder", wid, *([k] if k else []))
                if seed not in used_seeds and seed not in avoid and seed != 0:
                    break
                k += 1
            used_seeds.add(seed)
            flags = treatment_flags(arena, t)
            worlds.append({
                "id": wid, "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:redqueen:{namespace}:{wid}")),
                "index": idx, "block": b, "slot": slot, "treatment": t, "founder_seed": seed,
                "seed_rederived": k, "flags": flags, "config_args": flags_to_args(flags) + ["--seed", str(seed)],
                "predator_log": t == "C"})
    tainted = arena.get("status") != "selected" or bool(unresolved)
    return {"schema": WORLDS_SCHEMA, "namespace": namespace, "blocks": blocks, "per_block": per_block,
            "c_founders": c_founders, "schedule": schedule,
            "arena": {"path": os.path.abspath(arena_path), "sha256": rqlib.sha256_bytes(raw),
                      "status": arena.get("status")},
            "taint": {"tainted": tainted, "unresolved": unresolved},
            "avoid": avoid_rec, "tool_sha256": rqlib.sha256_file(os.path.abspath(__file__)), "worlds": worlds}


def _flock(path):
    """An exclusive, non-blocking flock on path (created) -> the open file; WorldsError if held."""
    import fcntl
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        raise WorldsError(f"another worlds.py holds {path}")
    return f


def write_registry(out, data):
    """Write the registry bytes to `out`, under the study root's lock (out = STUDY/config/worlds.json)
    or a lock beside it; an existing file with other bytes is never replaced."""
    out = os.path.abspath(out)
    d = os.path.dirname(out)
    lockp = os.path.join(os.path.dirname(d), ".worlds.lock") if os.path.basename(d) == "config" else out + ".lock"
    lk = _flock(lockp)
    try:
        if os.path.exists(out):
            if rqlib.read_bytes(out) == data:
                return False
            raise WorldsError(f"{out} exists with other bytes: a study's registry is never replaced (changed "
                              "seeds, treatments or schedule need a new study root)")
        os.makedirs(d, exist_ok=True)
        rqlib.write_durable(out, data)
        return True
    finally:
        lk.close()


def load_registry(root, allow_placeholder=False):
    """-> (registry, its sha256): revalidated (every world's flags against the typed table, its
    command line against its flags); a tainted registry only with allow_placeholder."""
    p = os.path.join(root, "config", "worlds.json")
    raw = rqlib.read_bytes(p)
    reg = json.loads(raw.decode("utf-8"))
    if reg.get("schema") != WORLDS_SCHEMA:
        raise WorldsError(f"config/worlds.json schema {reg.get('schema')!r}, expected {WORLDS_SCHEMA}")
    probs, unresolved = [], []
    for w in reg["worlds"]:
        p_, u_ = world_flag_problems(w["flags"], w["treatment"], reg.get("c_founders", C_FOUNDERS))
        probs += [f"{w['id']} {x}" for x in p_]
        unresolved += [f"{w['id']} {x}" for x in u_]
        if w["config_args"] != flags_to_args(w["flags"]) + ["--seed", str(w["founder_seed"])]:
            probs.append(f"{w['id']}: its command line does not match its flags")
    if probs:
        raise WorldsError("config/worlds.json is not a valid registry: " + "; ".join(probs[:6]))
    tainted = reg["arena"]["status"] != "selected" or bool(unresolved) or bool(reg.get("taint", {}).get("tainted"))
    if tainted and not allow_placeholder:
        raise WorldsError("the registry was made from a placeholder arena or holds unresolved values "
                          f"({'; '.join(unresolved[:3]) or reg['arena']['status']}): --allow-placeholder only for tests")
    return reg, rqlib.sha256_bytes(raw)


def bind_root(root, reg_sha, archive_root=None, create=False):
    """The study root's binding (STUDY/study.json: the registry's sha256 and the archive root) ->
    the archive root. create: bind an unbound root (refused if it already holds artifacts)."""
    p = os.path.join(root, "study.json")
    if os.path.isfile(p):
        rec = rqlib.read_json(p)
        if rec.get("schema") != STUDY_SCHEMA:
            raise WorldsError(f"{p}: schema {rec.get('schema')!r}")
        if rec["registry_sha256"] != reg_sha:
            raise WorldsError(f"{root} is bound to the registry {rec['registry_sha256'][:12]}, but config/worlds.json "
                              f"is now {reg_sha[:12]}: a changed registry needs a new study root")
        if archive_root and os.path.abspath(archive_root) != rec["archive_root"]:
            raise WorldsError(f"{root} is bound to the archive root {rec['archive_root']}, not {archive_root}")
        return rec["archive_root"]
    if not create:
        raise WorldsError(f"{root} is not bound to its registry yet (worlds.py f1 or launch binds it)")
    present = [x for x in ("worlds", "bin", "availability.jsonl") if os.path.exists(os.path.join(root, x))]
    if present:
        raise WorldsError(f"{root} holds study artifacts ({', '.join(present)}) but no study.json: not binding it")
    ar = os.path.abspath(archive_root or os.path.join(root, "archive"))
    rqlib.write_json_durable(p, {"schema": STUDY_SCHEMA, "registry_sha256": reg_sha, "archive_root": ar,
                                 "created_utc": rqlib.now_utc(),
                                 "tool_sha256": rqlib.sha256_file(os.path.abspath(__file__))})
    return ar


# ================================================================== layout
def wdir(root, wid):
    return os.path.join(root, "worlds", wid)


def adir(archive_root, wid):
    return os.path.join(archive_root, "worlds", wid)


def read_state(root, wid):
    p = os.path.join(wdir(root, wid), "state.json")
    if os.path.isfile(p):
        return rqlib.read_json(p)
    return {"schema": STATE_SCHEMA, "id": wid, "status": "pending", "segments": [], "failures": 0}


def write_state(root, wid, st):
    os.makedirs(wdir(root, wid), exist_ok=True)
    rqlib.write_json_durable(os.path.join(wdir(root, wid), "state.json"), st)


def read_jsonl(path, repair=False):
    """The records of an append-only JSONL file: every newline-terminated line must parse (a
    malformed interior line is damage: WorldsError); bytes after the last newline are a torn
    final record (an append the crash interrupted: never acknowledged), ignored, and with repair
    (under the root lock, before any further append) cut off durably."""
    if not os.path.isfile(path):
        return []
    raw = rqlib.read_bytes(path)
    cut = raw.rfind(b"\n") + 1
    out = []
    for k, ln in enumerate(raw[:cut].split(b"\n")[:-1], 1):
        try:
            out.append(json.loads(ln.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            raise WorldsError(f"{path}: line {k} is malformed (not a torn tail): repair by hand")
    if repair and cut < len(raw):
        rqlib.write_durable(path, raw[:cut])
    return out


def archive_records(root, wid, repair=False):
    """{label: record} of a world's archive.jsonl (a re-archived label keeps its first record)."""
    out = {}
    for r in read_jsonl(os.path.join(wdir(root, wid), "archive.jsonl"), repair):
        out.setdefault(r["label"], r)
    return out


def accept_records(root, wid, repair=False):
    return read_jsonl(os.path.join(wdir(root, wid), "accept.jsonl"), repair)


def _append_durable(path, rec):
    with open(path, "ab") as f:
        f.write(rqlib.canonical(rec))
        f.flush()
        os.fsync(f.fileno())
    rqlib.fsync_dir(os.path.dirname(path))


def label_of(frame):
    return "F1" if frame == 1 else f"end.{frame}"


def first_zeros(ledger, wid):
    """{guild: the earliest recorded first-zero frame} of a world (the ledger's minimum)."""
    out = {}
    for e in ledger:
        if e["world"] == wid:
            out[e["guild"]] = min(out.get(e["guild"], e["first_zero_frame"]), e["first_zero_frame"])
    return out


# ================================================================== logs
def _rows(path):
    """(header, [rows as lists]) of a CSV; a torn last line (no newline) is dropped."""
    if not os.path.isfile(path):
        return None, []
    raw = rqlib.read_text(path)
    if raw and not raw.endswith("\n"):
        raw = raw[: raw.rfind("\n") + 1]
    rows = list(csv.reader(io.StringIO(raw)))
    return (rows[0], rows[1:]) if rows else (None, [])


def _last_row(path, tail=65536):
    """(header, last complete row) of a CSV, reading only its first line and last `tail` bytes."""
    if not os.path.isfile(path):
        return None, None
    with open(path, "rb") as f:
        head = f.readline().decode("utf-8", "replace").rstrip("\n")
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - tail))
        data = f.read().decode("utf-8", "replace")
    lines = data.split("\n")[:-1]          # the part after the last newline is torn or empty
    if size > tail:
        lines = lines[1:]                  # the first piece may be a partial line
    hdr = next(csv.reader([head])) if head else None
    for ln in reversed(lines):
        if ln and ln != head:
            return hdr, next(csv.reader([ln]))
    return hdr, None


class Tail:
    """New complete lines of a growing file since the last call (a torn last line waits)."""

    def __init__(self, path):
        self.path, self.offset, self.header = path, 0, None

    def lines(self):
        if not os.path.isfile(self.path):
            return []
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            data = f.read()
        cut = data.rfind(b"\n")
        if cut < 0:
            return []
        self.offset += cut + 1
        out = data[:cut].decode("utf-8").split("\n")
        if self.header is None and out:
            self.header = next(csv.reader([out[0]]))
            out = out[1:]
        return [next(csv.reader([ln])) for ln in out if ln]


def _contiguous_until(frames, start, step):
    """The last frame of the run start + step, start + 2 step, ... that `frames` contains in order."""
    last = start
    for f in frames:
        if f != last + step:
            break
        last = f
    return last


def log_kinds(treatment):
    """The logs of a segment: (file, kind); kind frame / steps (dense, segment-relative steps) / events."""
    k = [("run.csv", "frame"), ("run.wiring.csv", "steps")]
    if treatment == "C":
        k += [("run.predators.csv", "frame"), ("run.pwiring.csv", "frame"), ("run.predlog.csv", "events")]
    return k


def _read_from(path, offset):
    with open(path, "rb") as f:
        f.seek(offset)
        return f.read()


def dense_cut(path, kind, start, frame, step, prev=None):
    """The next accepted part of a dense log: from the end of `prev` (or the start of the file,
    header included) through the row of `frame`, every `step` without a gap -> {"from", "bytes",
    "sha256", "last_frame"}; None while the file does not reach `frame` (or has a gap)."""
    if not os.path.isfile(path):
        return None
    off = prev["bytes"] if prev else 0
    last = prev["last_frame"] if prev else start
    data = _read_from(path, off)
    pos = 0
    if prev is None:
        nl = data.find(b"\n")
        if nl < 0:
            return None
        pos = nl + 1
    while last < frame:
        nl = data.find(b"\n", pos)
        if nl < 0:
            return None
        try:
            v = int(data[pos:nl].split(b",", 1)[0])
        except ValueError:
            return None
        fr = start + v if kind == "steps" else v
        if fr != last + step:
            return None
        last, pos = fr, nl + 1
    return {"from": off, "bytes": off + pos, "sha256": rqlib.sha256_bytes(data[:pos]), "last_frame": frame}


def events_cut(path, frame, prev=None):
    """The next accepted part of the lineage log: from the end of `prev` (or the header) through its
    last row at or before `frame` -> {"from", "bytes", "sha256", "last_frame", "events" (cumulative
    counts per event in the segment), "columns", "max_frame"}; None if missing or malformed."""
    if not os.path.isfile(path):
        return None
    off = prev["bytes"] if prev else 0
    counts = dict(prev["events"]) if prev else {}
    data = _read_from(path, off)
    pos = 0
    if prev is None:
        nl = data.find(b"\n")
        if nl < 0:
            return None
        ncol, maxf = data[:nl].count(b",") + 1, -1
        pos = nl + 1
    else:
        ncol, maxf = prev["columns"], prev["max_frame"]
    while True:
        nl = data.find(b"\n", pos)
        if nl < 0:
            break
        parts = data[pos:nl].split(b",")
        try:
            fr = int(parts[0])
        except ValueError:
            return None
        if len(parts) != ncol or fr < maxf:
            return None
        if fr > frame:
            break
        maxf = fr
        ev = parts[1].decode("utf-8", "replace")
        counts[ev] = counts.get(ev, 0) + 1
        pos = nl + 1
    return {"from": off, "bytes": off + pos, "sha256": rqlib.sha256_bytes(data[:pos]), "last_frame": frame,
            "events": counts, "columns": ncol, "max_frame": maxf}


def lineage_problems(events, start_cp, cp, start_frame):
    """How a segment's lineage-log events through checkpoint `cp` disagree with its counters
    (relative to the checkpoint the segment started from; seg000: the founders)."""
    c0 = (start_cp or {}).get("counters") or {}
    c1 = cp.get("counters") or {}
    probs = []
    for ev, key in LINEAGE_COUNTERS:
        want = int(c1.get(key, 0)) - int(c0.get(key, 0))
        if events.get(ev, 0) != want:
            probs.append(f"{events.get(ev, 0)} {ev} rows, the counters say {want}")
    first = "F" if start_frame == 0 else "L"
    n0 = int(cp["config"].get("predatorCount", 0)) if start_frame == 0 else \
        len(ckpt.predators(start_cp, alive_only=True))
    if events.get(first, 0) != n0:
        probs.append(f"{events.get(first, 0)} {first} rows, expected {n0}")
    alive = (events.get(first, 0) + events.get("B", 0) + events.get("R", 0)
             - events.get("S", 0) - events.get("A", 0))
    have = len(ckpt.predators(cp, alive_only=True))
    if alive != have:
        probs.append(f"the rows leave {alive} predators alive, the checkpoint has {have}")
    other = sorted(set(events) - {"F", "L", "B", "S", "A", "R"})
    if other:
        probs.append(f"unexpected events {other} in a history")
    return probs


def verify_delta(path, d):
    """The bytes [from, bytes) of `path` still hash to the record's sha256."""
    try:
        with open(path, "rb") as f:
            f.seek(d["from"])
            data = f.read(d["bytes"] - d["from"])
    except OSError:
        return False
    return len(data) == d["bytes"] - d["from"] and rqlib.sha256_bytes(data) == d["sha256"]


def verify_config(cp, flags):
    """How a checkpoint's configuration differs from a world's registered flags (and both floors 0)."""
    cfg = cp.get("config") or {}
    probs = []
    if cfg.get("minPopulation") != 0:
        probs.append(f"minPopulation {cfg.get('minPopulation')!r} (the prey floor must be 0)")
    if cfg.get("predatorMinPopulation", 0) != 0:
        probs.append(f"predatorMinPopulation {cfg.get('predatorMinPopulation')!r} (the predator floor must be 0)")
    for k, v in flags.items():
        typ, key = FLAGS.get(k, (None, None))
        if _placeholder(v) or typ is None:
            continue
        if k == "topological":
            if v is True and cfg.get("maxNeighbors") != 7:
                probs.append(f"--topological: maxNeighbors {cfg.get('maxNeighbors')!r}")
            continue
        if key is None:
            continue
        have = cfg.get(key, False if typ == SWITCH else None)
        if typ == SWITCH:
            ok = isinstance(have, bool) and have == bool(v)
        elif typ == ENUM:
            ok = have == (1 if v == "gyre" else 0)
        elif typ == INT:
            want = max(0, v) if k == "repro-window" else max(1, v) if k == "repro-min-cluster" else v
            ok = _is_num(have) and have == want
        else:
            ok = _is_num(have) and math.isclose(have, v, rel_tol=1e-6, abs_tol=1e-12)
        if not ok:
            probs.append(f"--{k} {v!r}: the checkpoint's {key} is {cfg.get(key)!r}")
    return probs


# ================================================================== archive
def local_ckpts(root, wid):
    d = os.path.join(wdir(root, wid), "ckpt")
    out = {}
    for f in os.listdir(d) if os.path.isdir(d) else []:
        m = CKPT_RE.match(f)
        if m:
            out[int(m.group(1))] = os.path.join(d, f)
    return out


def _copy_verified(raw, dst, sha):
    d = os.path.dirname(dst)
    if not os.access(d, os.W_OK):
        os.chmod(d, 0o755)
    tmp = dst + f".tmp.{os.getpid()}"
    with open(tmp, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o444)
    if rqlib.sha256_file(tmp) != sha:
        os.remove(tmp)
        raise WorldsError(f"{dst}: the archived copy does not hash to its source")
    os.replace(tmp, dst)
    rqlib.fsync_dir(d)


def ensure_archived(wid, rec, raw, log, verified=None):
    """The archived copy of `rec` exists, holds its bytes and is 0444; else it is repaired from the
    verified local bytes `raw` (refused once the archive is finalized)."""
    dst = rec["path"]
    try:
        s = os.stat(dst)
    except FileNotFoundError:
        s = None
    key = (s.st_mtime_ns, s.st_size) if s else None
    if s and verified is not None and verified.get(dst) == key and s.st_mode & 0o777 == 0o444:
        return
    good = s is not None and s.st_size == rec["bytes"] and rqlib.sha256_file(dst) == rec["sha256"]
    if good and s.st_mode & 0o777 == 0o444:
        if verified is not None:
            verified[dst] = key
        return
    if os.path.isfile(os.path.join(os.path.dirname(dst), "FINALIZED")):
        raise WorldsError(f"{wid}: the archived {os.path.basename(dst)} is {'missing' if s is None else 'damaged'} "
                          "in a finalized archive (the local copy is kept)")
    if good:
        os.chmod(dst, 0o444)
        log(f"{wid}: the archived {os.path.basename(dst)} was writable: made read-only again")
    else:
        if rqlib.sha256_bytes(raw) != rec["sha256"]:
            raise WorldsError(f"{wid}: no verified bytes to repair the archived {os.path.basename(dst)}")
        _copy_verified(raw, dst, rec["sha256"])
        log(f"{wid}: REPAIRED the archived {os.path.basename(dst)} ({'missing' if s is None else 'damaged'}) "
            "from the verified local copy")
    if verified is not None:
        s = os.stat(dst)
        verified[dst] = (s.st_mtime_ns, s.st_size)


def archive_one(root, wid, archive_root, frame, src, log, extra=None, verified=None):
    """Verified copy of checkpoint `src` (at `frame`) into the archive -> (its record, the parsed
    checkpoint). TornCheckpoint: it does not parse or is not at its frame; WorldsError: it is not
    the serial build's, or its bytes differ from an earlier archived copy of the frame."""
    raw = rqlib.read_bytes(src)
    sha = rqlib.sha256_bytes(raw)
    try:
        cp = ckpt.loads(raw.decode("utf-8"), src)
        ckpt.validate(cp, src)
    except (ckpt.CheckpointError, UnicodeDecodeError, ValueError, KeyError, TypeError) as e:
        raise TornCheckpoint(f"{src} is not a complete checkpoint ({str(e)[:120]})")
    if int(cp["world"]["frame"]) != frame:
        raise TornCheckpoint(f"{src} is at frame {cp['world']['frame']}, not {frame}")
    if cp.get("determinism") != SERIAL:
        raise WorldsError(f"{src} declares {cp.get('determinism')!r}: a history needs the serial build's exact resume")
    lab = label_of(frame)
    recs = archive_records(root, wid)
    if lab in recs:
        if recs[lab]["sha256"] != sha:
            raise WorldsError(f"{wid} {lab}: rewritten with other bytes than its archived copy "
                              f"({sha[:12]} != {recs[lab]['sha256'][:12]}): the history is not deterministic")
        ensure_archived(wid, recs[lab], raw, log, verified)
        return recs[lab], cp
    ad = adir(archive_root, wid)
    os.makedirs(ad, exist_ok=True)
    name = "F1.json" if frame == 1 else f"end.{frame}.json"
    dst = os.path.join(ad, name)
    _copy_verified(raw, dst, sha)
    m = ckpt.meta(cp)
    rec = {"label": lab, "frame": frame, "sha256": sha, "bytes": len(raw), "path": os.path.abspath(dst),
           "prey": m["prey_alive"], "predators": m["predators"], "utc": rqlib.now_utc()}
    rec.update(extra or {})
    _append_durable(os.path.join(wdir(root, wid), "archive.jsonl"), rec)
    if verified is not None:
        s = os.stat(dst)
        verified[dst] = (s.st_mtime_ns, s.st_size)
    log(f"{wid}: archived {name} ({len(raw) / 1e6:.2f} MB, prey {m['prey_alive']}, predators {m['predators']})")
    return rec, cp


def finalize_archive(root, wid, archive_root, status, log=lambda m: None):
    """Audit and finalize a terminal world's archive (idempotent: it also completes or checks an
    earlier, interrupted finalization): every record's file present, its bytes (repaired from a
    verified local copy if need be) and 0444; the FINALIZED marker (world, status, frames)
    published atomically and 0444; the directory 0555; both fsync'd."""
    ad = adir(archive_root, wid)
    os.makedirs(ad, exist_ok=True)
    recs = archive_records(root, wid)
    want = {"world": wid, "status": status, "frames": sorted(r["frame"] for r in recs.values())}
    marker = os.path.join(ad, "FINALIZED")
    if os.path.isfile(marker):
        try:
            have = json.loads(rqlib.read_text(marker))
        except ValueError:
            have = {}
        if {k: have.get(k) for k in want} != want:
            raise WorldsError(f"{wid}: {marker} does not describe its archive ({ {k: have.get(k) for k in want} })")
        for r in recs.values():
            s = os.stat(r["path"]) if os.path.isfile(r["path"]) else None
            if s is None or s.st_size != r["bytes"] or s.st_mode & 0o777 != 0o444:
                raise WorldsError(f"{wid}: the finalized archive's {os.path.basename(r['path'])} is missing, "
                                  "resized or writable")
    else:
        if not os.access(ad, os.W_OK):
            os.chmod(ad, 0o755)
        loc = local_ckpts(root, wid)
        for r in recs.values():
            ok = os.path.isfile(r["path"]) and rqlib.sha256_file(r["path"]) == r["sha256"]
            if ok and os.stat(r["path"]).st_mode & 0o777 == 0o444:
                continue
            src = loc.get(r["frame"]) if r["frame"] > 1 else os.path.join(wdir(root, wid), "f1", "F1.json")
            src = src if src and os.path.isfile(src) else None
            raw = rqlib.read_bytes(src) if src else (rqlib.read_bytes(r["path"]) if ok else b"")
            ensure_archived(wid, r, raw, log)
        tmp = marker + ".tmp"
        if os.path.exists(tmp):
            os.remove(tmp)
        with open(tmp, "wb") as f:
            f.write(rqlib.canonical(dict(want, utc=rqlib.now_utc())))
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o444)
        os.replace(tmp, marker)
        rqlib.fsync_dir(ad)
    if os.stat(marker).st_mode & 0o777 != 0o444:
        os.chmod(marker, 0o444)
    if os.stat(ad).st_mode & 0o777 != 0o555:
        os.chmod(ad, 0o555)
    rqlib.fsync_file(marker)
    rqlib.fsync_dir(ad)
    rqlib.fsync_dir(os.path.dirname(ad))


# ================================================================== acceptance and resume
def good_copy(root, wid, frame, sha, arecs=None):
    """A path holding the checkpoint of `frame` with these bytes: the local copy, else the archived one."""
    arecs = archive_records(root, wid) if arecs is None else arecs
    lab = label_of(frame)
    for p in [x for x in (local_ckpts(root, wid).get(frame), arecs.get(lab, {}).get("path")) if x]:
        try:
            if rqlib.sha256_file(p) == sha:
                return p
        except OSError:
            continue
    return None


def verified_records(root, wid, st, treatment):
    """{(segment, frame): acceptance record} of the records whose log parts still verify (each
    segment's parts in order, without a gap), in segments whose start is itself such a record
    (back to the founder segment)."""
    by_seg = {}
    for r in accept_records(root, wid):
        by_seg.setdefault(r["segment"], []).append(r)
    segs = {s["name"]: s for s in st["segments"]}
    kinds = log_kinds(treatment)
    good = {}
    for name, rs in by_seg.items():
        if name not in segs:
            continue
        ends = {f: 0 for f, _ in kinds}
        for r in sorted(rs, key=lambda x: x["frame"]):
            ok = r["start_frame"] == segs[name]["start_frame"] and all(
                f in r["logs"] and r["logs"][f]["from"] == ends[f]
                and verify_delta(os.path.join(wdir(root, wid), name, f), r["logs"][f]) for f, _ in kinds)
            if not ok:
                break
            good[(name, r["frame"])] = r
            ends = {f: r["logs"][f]["bytes"] for f, _ in kinds}
    memo = {}

    def chained(name):
        if name not in memo:
            s = segs[name]
            ra = s.get("resumed_accept")
            memo[name] = s["start_frame"] == 0 or bool(
                ra and ra["frame"] == s["start_frame"] and (ra["segment"], ra["frame"]) in good
                and good[(ra["segment"], ra["frame"])]["sha256"] == ra["sha256"] and chained(ra["segment"]))
        return memo[name]
    return {k: r for k, r in good.items() if chained(k[0])}


def _seg_index(name):
    return int(name[3:])


def resume_point(root, wid, st, treatment, good=None):
    """-> (frame, checkpoint path, acceptance record) the next segment starts from: the latest
    verified record with a good copy of its checkpoint; (0, None, None) for the founder seed."""
    good = verified_records(root, wid, st, treatment) if good is None else good
    arecs = archive_records(root, wid)
    for (name, f), r in sorted(good.items(), key=lambda kv: (kv[0][1], _seg_index(kv[0][0])), reverse=True):
        p = good_copy(root, wid, f, r["sha256"], arecs)
        if p:
            return f, p, r
    return 0, None, None


def f1_bound(root, wid, exe_sha):
    return archive_records(root, wid).get("F1", {}).get("binary_sha256") == exe_sha


def f1_verified(root, wid, exe_sha, first):
    p = os.path.join(wdir(root, wid), "f1_verify.json")
    if not os.path.isfile(p):
        return False
    v = rqlib.read_json(p)
    recs = archive_records(root, wid)
    return bool(v.get("identical") and v.get("binary_sha256") == exe_sha and "F1" in recs
                and label_of(first) in recs and v.get("f1_sha256") == recs["F1"]["sha256"]
                and v.get("first_checkpoint_sha256") == recs[label_of(first)]["sha256"])


def verify_args(f1_path, first):
    return ["--load-checkpoint", f1_path, "--no-render", "--headless", str(first - 1),
            "--log-every", str(first - 1), "--save-checkpoint", "v.json"]


def record_verify(root, wid, rc, d, first, exe_sha):
    """Write the F1 verification's result (f1_verify.json) -> the record."""
    recs = archive_records(root, wid)
    v = os.path.join(d, "v.json")
    same = rc == 0 and os.path.isfile(v) and rqlib.sha256_file(v) == recs[label_of(first)]["sha256"]
    rec = {"world": wid, "f1_sha256": recs["F1"]["sha256"], "first_checkpoint": first,
           "first_checkpoint_sha256": recs[label_of(first)]["sha256"], "engine_rc": rc, "identical": same,
           "binary_sha256": exe_sha, "utc": rqlib.now_utc()}
    rqlib.write_json_durable(os.path.join(wdir(root, wid), "f1_verify.json"), rec)
    return rec


def scan_zeros(root, wid, st, treatment):
    """{guild: the earliest frame at which it is 0 in any segment's main CSV}."""
    out = {}
    for s in st["segments"]:
        hdr, rows = _rows(os.path.join(wdir(root, wid), s["name"], "run.csv"))
        if not hdr:
            continue
        for guild, col in GUILDS:
            if (guild == "predators" and treatment == "A") or col not in hdr:
                continue
            i = hdr.index(col)
            for r in rows:
                if int(float(r[i])) == 0:
                    out[guild] = min(out.get(guild, int(r[0])), int(r[0]))
                    break
    return out


# ================================================================== engine
def segment_args(world, sched, seg, start, ckpt_path=None):
    args = ["--no-render", "--headless", str(sched["total_steps"] - start), "--log-every", str(sched["log_every"]),
            "--flush-every", "1", "--checkpoint-every", str(sched["checkpoint_every"]),
            "--save-checkpoint", "ckpt/end.json", "--csv", f"{seg}/run.csv", "--wiring-log"]
    if world["predator_log"]:
        args.append("--predator-log")
    if ckpt_path is None:
        return world["config_args"] + args
    return ["--load-checkpoint", ckpt_path] + args


def probe_binary(exe, bdir):
    """One step of a tiny world by `exe` -> its identity (the determinism its checkpoint declares)."""
    d = os.path.join(bdir, f"probe.{os.getpid()}")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    try:
        with open(os.path.join(d, "stdout.log"), "w") as so, open(os.path.join(d, "stderr.log"), "w") as se:
            r = subprocess.call([exe, "--seed", "1", "--population", "8", "--no-render", "--headless", "1",
                                 "--save-checkpoint", "probe.json"], cwd=d, stdout=so, stderr=se,
                                stdin=subprocess.DEVNULL, preexec_fn=rqlib.death_signal())
        p = os.path.join(d, "probe.json")
        if r != 0 or not os.path.isfile(p):
            raise WorldsError(f"the engine probe failed (exit {r})")
        cp = json.loads(rqlib.read_text(p))
        return {"schema": BINARY_SCHEMA, "determinism": cp.get("determinism"),
                "engine_version": cp.get("engineVersion"), "utc": rqlib.now_utc()}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def pin_binary(root, binary=None):
    """Pin the engine in STUDY/bin (or, binary=None, check the pinned one) -> (path, sha256);
    refused unless it is the serial build (probed once, bin/identity.json)."""
    bdir = os.path.join(root, "bin")
    os.makedirs(bdir, exist_ok=True)
    pinned = os.path.join(bdir, "evo_boids")
    want = None
    if binary is not None:
        want = rqlib.sha256_file(binary)
        if not os.path.exists(pinned):
            tmp = pinned + ".tmp"
            shutil.copy2(binary, tmp)
            rqlib.fsync_file(tmp)
            os.replace(tmp, pinned)
            rqlib.write_durable(pinned + ".sha256", f"{want}  {os.path.abspath(binary)}\n")
    if not os.path.exists(pinned + ".sha256"):
        raise WorldsError(f"{root} has no pinned engine (worlds.py f1 --binary pins it)")
    have = rqlib.read_text(pinned + ".sha256").split()[0]
    if (want is not None and have != want) or rqlib.sha256_file(pinned) != have:
        raise WorldsError(f"{root} runs another engine ({have[:12]})" +
                          (f"; this one is {want[:12]}" if want is not None else ": the pinned copy changed"))
    idp = os.path.join(bdir, "identity.json")
    ident = rqlib.read_json(idp) if os.path.isfile(idp) else None
    if not ident or ident.get("sha256") != have:
        ident = dict(probe_binary(pinned, bdir), sha256=have)
        rqlib.write_json_durable(idp, ident)
    if ident.get("determinism") != SERIAL:
        raise WorldsError(f"the pinned engine declares {ident.get('determinism')!r}: the histories need the serial "
                          "build's bit-exact resume (-DEVO_NO_OPENMP=ON)")
    return pinned, have


# ================================================================== supervisor
class Supervisor:
    """The resumable history runner of one study root (see the module doc)."""

    def __init__(self, root, reg, archive_root, exe, exe_sha, a, log):
        self.root, self.reg, self.sched = root, reg, reg["schedule"]
        self.archive_root, self.exe, self.exe_sha, self.a, self.log = archive_root, exe, exe_sha, a, log
        self.T = self.sched["total_steps"]
        self.ce = self.sched["checkpoint_every"]
        self.worlds = {w["id"]: w for w in reg["worlds"]}
        self.avail_p = os.path.join(root, "availability.jsonl")
        self.running = {}     # wid -> (Popen, job name, "segment" | "verify")
        self.tails = {}       # wid -> Tail of the running segment's main CSV
        self.last_frame = {}  # wid -> the last main-CSV frame seen
        self.extinct = {}     # wid -> the reason we stopped it
        self.seen = {}        # (wid, frame) -> (mtime_ns, size) of a local checkpoint already archived / compared
        self.verified = {}    # archived path -> (mtime_ns, size) once its bytes were verified
        self.start_cps = {}   # (wid, segment) -> the checkpoint the segment started from
        self.warned = set()
        self.zeros = {}       # wid -> {guild: first-zero frame} (the ledger's minimum)

    # ---------------------------------------------------------------- state
    def state(self, wid):
        return read_state(self.root, wid)

    def set_status(self, wid, status, **kw):
        st = self.state(wid)
        st["status"] = status
        st.update(kw)
        write_state(self.root, wid, st)
        return st

    def end_world(self, wid, status, reason):
        self.set_status(wid, status, end_reason=reason)
        if status in ("done", "extinct"):
            try:
                finalize_archive(self.root, wid, self.archive_root, status, self.log)
            except (WorldsError, OSError) as e:
                self.set_status(wid, "failed", end_reason=f"finalizing its archive: {e}")
                self.log(f"FAILED {wid}: finalizing its archive: {e}")

    def warn_once(self, key, msg):
        if key not in self.warned:
            self.warned.add(key)
            self.log(msg)

    # ---------------------------------------------------------------- biology
    def note_zero(self, wid, guild, frame, recovered=False):
        z = self.zeros.setdefault(wid, {})
        if guild in z and z[guild] <= frame:
            return
        w = self.worlds[wid]
        arecs = archive_records(self.root, wid)
        rec = {"schema": AVAIL_SCHEMA, "world": wid, "uuid": w["uuid"], "treatment": w["treatment"], "guild": guild,
               "first_zero_frame": frame, "detected_utc": rqlib.now_utc(),
               "archived_frames_before": sorted(x["frame"] for x in arecs.values() if x["frame"] < frame)}
        if recovered:
            rec.update(recovered=True, supersedes=z.get(guild))
        _append_durable(self.avail_p, rec)
        z[guild] = frame
        self.log(f"BIOLOGICAL: {wid} ({w['treatment']}): the {guild} reached 0 at frame {frame} (availability ledger"
                 + (", recovered from an earlier segment" if recovered else "") + ")")

    def recover_zeros(self, wid):
        for guild, f in scan_zeros(self.root, wid, self.state(wid), self.worlds[wid]["treatment"]).items():
            self.note_zero(wid, guild, f, recovered=True)

    def zero_reason(self, wid):
        z = self.zeros.get(wid) or {}
        return "; ".join(f"the {g} reached 0 at frame {f}" for g, f in sorted(z.items())) or None

    def watch(self, wid):
        """New main-CSV rows of a running segment: the frame reached; a guild at zero -> (guild, frame)."""
        t = self.tails[wid]
        found = None
        for r in t.lines():
            fr = int(r[0])
            self.last_frame[wid] = fr
            row = dict(zip(t.header, r))
            for guild, col in GUILDS:
                if guild == "predators" and self.worlds[wid]["treatment"] == "A":
                    continue
                if int(float(row[col])) == 0:
                    self.note_zero(wid, guild, fr)
                    found = found or (guild, fr)
        return found

    # ---------------------------------------------------------------- archive and acceptance
    def quarantine(self, wid, frame, path, reason):
        qd = os.path.join(wdir(self.root, wid), "ckpt", "quarantine")
        os.makedirs(qd, exist_ok=True)
        n = 1
        while os.path.exists(os.path.join(qd, f"{os.path.basename(path)}.{n}")):
            n += 1
        dst = os.path.join(qd, f"{os.path.basename(path)}.{n}")
        raw = rqlib.read_bytes(path)
        os.rename(path, dst)
        rqlib.fsync_dir(os.path.dirname(path))
        _append_durable(os.path.join(wdir(self.root, wid), "quarantine.jsonl"), {
            "schema": QUARANTINE_SCHEMA, "world": wid, "frame": frame, "from": path, "to": dst, "bytes": len(raw),
            "sha256": rqlib.sha256_bytes(raw), "reason": reason, "utc": rqlib.now_utc()})
        self.seen.pop((wid, frame), None)
        self.log(f"{wid}: QUARANTINED {os.path.basename(path)} ({reason}); not used to resume")

    def archive_pass(self, wid, alive):
        """Archive every complete local checkpoint (a rewritten one is compared with its archive);
        quarantine a torn one; with --prune-local drop old local copies of accepted checkpoints."""
        loc = local_ckpts(self.root, wid)
        for f in sorted(loc):
            if alive and self.last_frame.get(wid, -1) <= f:
                continue              # (the main CSV's row past f shows checkpoint f complete)
            try:
                s_ = os.stat(loc[f])
            except FileNotFoundError:
                continue
            key = (s_.st_mtime_ns, s_.st_size)
            if self.seen.get((wid, f)) == key:
                continue
            try:
                archive_one(self.root, wid, self.archive_root, f, loc[f], self.log, verified=self.verified)
            except TornCheckpoint as e:
                self.quarantine(wid, f, loc[f], str(e))
                continue
            self.seen[(wid, f)] = key
        if self.a.prune_local:
            acc = sorted({r["frame"] for r in accept_records(self.root, wid)})
            keep = set(acc[-2:])
            arecs = archive_records(self.root, wid)
            for f, p in local_ckpts(self.root, wid).items():
                r = arecs.get(label_of(f))
                if f in acc and f not in keep and r and rqlib.sha256_file(r["path"]) == r["sha256"] \
                        and rqlib.sha256_file(p) == r["sha256"]:
                    os.remove(p)
                    self.seen.pop((wid, f), None)

    def start_checkpoint(self, wid, seg):
        if seg["start_frame"] == 0:
            return None
        k = (wid, seg["name"])
        if k not in self.start_cps:
            ra = seg["resumed_accept"]
            p = good_copy(self.root, wid, ra["frame"], ra["sha256"])
            if p is None:
                raise WorldsError(f"{wid}: the checkpoint {seg['name']} resumed (frame {ra['frame']}) is gone")
            self.start_cps[k] = ckpt.load(p)
        return self.start_cps[k]

    def accept_pass(self, wid, alive):
        """Accept the last segment's complete checkpoints, in frame order (see ACCEPTANCE)."""
        st = self.state(wid)
        if not st["segments"]:
            return
        seg = st["segments"][-1]
        name, s0 = seg["name"], seg["start_frame"]
        w = self.worlds[wid]
        d = os.path.join(wdir(self.root, wid), name)
        mine = sorted((r for r in accept_records(self.root, wid) if r["segment"] == name), key=lambda r: r["frame"])
        prev = mine[-1] if mine else None
        last = prev["frame"] if prev else s0
        while last + self.ce <= self.T:
            F = last + self.ce
            p = local_ckpts(self.root, wid).get(F)
            if p is None or (alive and self.last_frame.get(wid, -1) <= F):
                return
            try:
                arec, cp = archive_one(self.root, wid, self.archive_root, F, p, self.log, verified=self.verified)
            except TornCheckpoint as e:
                self.quarantine(wid, F, p, str(e))
                return
            probs = verify_config(cp, w["flags"])
            if probs:
                raise WorldsError(f"{wid} end.{F}: the configuration differs from the registry: " + "; ".join(probs))
            logs = {}
            for lname, kind in log_kinds(w["treatment"]):
                pv = prev["logs"][lname] if prev else None
                path = os.path.join(d, lname)
                cut = events_cut(path, F, pv) if kind == "events" else \
                    dense_cut(path, kind, s0, F, self.sched["log_every"], pv)
                if cut is None:
                    if not alive:
                        self.warn_once((wid, name, F, lname), f"{wid}: {name}/{lname} does not reach frame {F}: "
                                                              f"end.{F} is not accepted")
                    return
                logs[lname] = cut
            if w["treatment"] == "C":
                probs = lineage_problems(logs["run.predlog.csv"]["events"], self.start_checkpoint(wid, seg), cp, s0)
                if probs:
                    self.warn_once((wid, name, F, "lineage"), f"{wid}: {name}'s lineage log is incomplete at frame "
                                                              f"{F} ({'; '.join(probs)}): end.{F} is not accepted")
                    return
            for lname in logs:
                rqlib.fsync_file(os.path.join(d, lname))
            rec = {"schema": ACCEPT_SCHEMA, "world": wid, "segment": name, "start_frame": s0, "frame": F,
                   "label": label_of(F), "sha256": arec["sha256"], "binary_sha256": self.exe_sha, "logs": logs,
                   "utc": rqlib.now_utc()}
            _append_durable(os.path.join(wdir(self.root, wid), "accept.jsonl"), rec)
            prev, last = rec, F

    # ---------------------------------------------------------------- what next
    def next_action(self, wid):
        """-> ("extinct" | "done", reason) | ("verify", None) | ("segment", (start, checkpoint path, record))."""
        if self.a.on_extinction == "stop" and self.zero_reason(wid):
            return "extinct", self.zero_reason(wid)
        st = self.state(wid)
        frame, path, rec = resume_point(self.root, wid, st, self.worlds[wid]["treatment"])
        if frame >= self.T:
            return "done", f"{self.T} steps (its final checkpoint and logs accepted)"
        if frame > 0 and not f1_verified(self.root, wid, self.exe_sha, self.ce):
            return "verify", None
        return "segment", (frame, path, rec)

    def spawn_segment(self, wid, start, cpath, rec):
        w = self.worlds[wid]
        st = self.state(wid)
        seg = f"seg{len(st['segments']):03d}"
        d = wdir(self.root, wid)
        if os.path.exists(os.path.join(d, seg)):      # (a segment directory the state never recorded)
            os.rename(os.path.join(d, seg), os.path.join(d, f"{seg}.orphan.{time.time_ns()}"))
        os.makedirs(os.path.join(d, seg))
        os.makedirs(os.path.join(d, "ckpt"), exist_ok=True)
        if cpath and os.path.abspath(cpath).startswith(d + os.sep):
            cpath = os.path.relpath(os.path.abspath(cpath), d)
        args = segment_args(w, self.sched, seg, start, cpath)
        st["segments"].append({"name": seg, "start_frame": start, "resumed_from": cpath,
                               "resumed_accept": ({"segment": rec["segment"], "frame": rec["frame"],
                                                   "sha256": rec["sha256"]} if rec else None),
                               "started_utc": rqlib.now_utc(), "args": args})
        st["status"] = "running"
        write_state(self.root, wid, st)
        p = self._popen(args, d, os.path.join(d, seg))
        self.running[wid] = (p, seg, "segment")
        self.tails[wid] = Tail(os.path.join(d, seg, "run.csv"))
        self.last_frame[wid] = start
        self.log(f"{wid} ({w['treatment']}): {seg} from frame {start}" + (f" ({cpath})" if cpath else " (founder seed)"))

    def spawn_verify(self, wid):
        recs = archive_records(self.root, wid)
        d = os.path.join(wdir(self.root, wid), "f1verify")
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        self.set_status(wid, "running")
        p = self._popen(verify_args(recs["F1"]["path"], self.ce), d, d)
        self.running[wid] = (p, "f1verify", "verify")
        self.log(f"{wid}: verifying F1 with the pinned engine before its first resume")

    def _popen(self, args, cwd, logdir):
        so = open(os.path.join(logdir, "stdout.log"), "w")
        se = open(os.path.join(logdir, "stderr.log"), "w")
        try:
            return subprocess.Popen([self.exe] + args, cwd=cwd, stdout=so, stderr=se, stdin=subprocess.DEVNULL,
                                    start_new_session=True, preexec_fn=rqlib.death_signal())
        finally:
            so.close()
            se.close()

    # ---------------------------------------------------------------- reaping
    def reap_verify(self, wid, rc):
        d = os.path.join(wdir(self.root, wid), "f1verify")
        v = record_verify(self.root, wid, rc, d, self.ce, self.exe_sha)
        if v["identical"]:
            shutil.rmtree(d, ignore_errors=True)
            self.set_status(wid, "interrupted")
            self.log(f"{wid}: F1 lies on the history's trajectory (resumed to frame {self.ce}: identical)")
        else:
            self.end_world(wid, "failed", f"the F1 verification failed (engine exit {rc}, or the resumed F1 differs "
                                          f"at frame {self.ce}): this engine does not resume exactly")
            self.log(f"FAILED {wid}: {self.state(wid)['end_reason']}")

    def reap_segment(self, wid, seg, rc):
        a = self.a
        ext = self.watch(wid)
        if ext and a.on_extinction == "stop" and wid not in self.extinct:   # (it ended before we could stop it)
            self.extinct[wid] = f"the {ext[0]} reached 0 at frame {ext[1]}"
        st = self.state(wid)
        st["segments"][-1].update(ended_utc=rqlib.now_utc(), rc=rc)
        write_state(self.root, wid, st)
        try:
            self.archive_pass(wid, alive=False)
            self.accept_pass(wid, alive=False)
        except (WorldsError, ckpt.CheckpointError, OSError, ValueError) as e:
            self.end_world(wid, "failed", str(e))
            self.log(f"FAILED {wid}: {e}")
            return
        if wid in self.extinct:
            self.end_world(wid, "extinct", self.extinct.pop(wid))
            self.log(f"{wid}: ended as extinct ({self.state(wid)['end_reason']})")
            return
        nxt = resume_point(self.root, wid, self.state(wid), self.worlds[wid]["treatment"])[0]
        if nxt >= self.T:
            self.end_world(wid, "done", f"{self.T} steps")
            self.log(f"{wid}: history complete ({self.T} steps, every log accepted through the final frame)")
            return
        st = self.state(wid)
        st["failures"] = st.get("failures", 0) + 1 if st.get("last_failed_resume") == nxt else 1
        st["last_failed_resume"] = nxt
        st["status"] = "failed" if st["failures"] > a.retries else "interrupted"
        if st["status"] == "failed":
            st["end_reason"] = f"{seg} ended with exit {rc}, no progress past frame {nxt} after {a.retries} retries"
        write_state(self.root, wid, st)
        self.log(f"{wid}: {seg} ended with exit {rc}, accepted through frame {nxt}; "
                 + ("FAILED (no progress after retries)" if st["status"] == "failed" else "it will resume"))

    # ---------------------------------------------------------------- startup
    def startup(self):
        """Repair torn ledger tails, reconcile terminal worlds' finalization, and recover what the
        previous supervisor left: acceptances, quarantines, zeros, worlds already at an end."""
        a = self.a
        for e in read_jsonl(self.avail_p, repair=True):
            z = self.zeros.setdefault(e["world"], {})
            z[e["guild"]] = min(z.get(e["guild"], e["first_zero_frame"]), e["first_zero_frame"])
        missing_f1 = []
        for wid, w in self.worlds.items():
            archive_records(self.root, wid, repair=True)
            accept_records(self.root, wid, repair=True)
            read_jsonl(os.path.join(wdir(self.root, wid), "quarantine.jsonl"), repair=True)
            st = self.state(wid)
            if st["status"] == "running" or (st["status"] == "failed" and a.retry_failed):
                if st["status"] == "failed":
                    self.log(f"{wid}: retrying a failed world (--retry-failed; it was: {st.get('end_reason')})")
                    st["failures"] = 0
                st["status"] = "interrupted"
                write_state(self.root, wid, st)
            if st["status"] in ("done", "extinct"):
                try:
                    finalize_archive(self.root, wid, self.archive_root, st["status"], self.log)
                except (WorldsError, OSError) as e:
                    self.set_status(wid, "failed", end_reason=f"finalizing its archive: {e}")
                    self.log(f"FAILED {wid}: finalizing its archive: {e}")
                continue
            if st["status"] not in ("pending", "interrupted"):
                continue
            if not f1_bound(self.root, wid, self.exe_sha):
                missing_f1.append(wid)
            if st["segments"]:
                try:
                    self.archive_pass(wid, alive=False)
                    self.accept_pass(wid, alive=False)
                    self.recover_zeros(wid)
                    kind, info = self.next_action(wid)
                except (WorldsError, ckpt.CheckpointError, OSError, ValueError) as e:
                    self.end_world(wid, "failed", str(e))
                    self.log(f"FAILED {wid}: {e}")
                    continue
                if kind in ("done", "extinct"):
                    self.end_world(wid, kind, info)
                    self.log(f"{wid}: already at its end ({kind}: {info}); finalized without another segment")
        if missing_f1:
            raise WorldsError(f"no F1 archived by the pinned engine for {', '.join(missing_f1)}: run worlds.py f1 first")

    # ---------------------------------------------------------------- the loop
    def run(self):
        a, log = self.a, self.log
        self.startup()
        stop_reason, mem_bad = None, 0

        def terminate(signum, frame):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            runlib.stop_groups([p for p, _, _ in self.running.values()], log)
            for wid in list(self.running):
                self.set_status(wid, "interrupted")
            log(f"signal {signum}: stopped {len(self.running)} jobs (they resume at the next start)")
            sys.exit(130)
        signal.signal(signal.SIGTERM, terminate)
        signal.signal(signal.SIGINT, terminate)

        while True:
            for wid in list(self.running):
                p, name, kind = self.running[wid]
                rc = p.poll()
                if rc is None:
                    continue
                del self.running[wid]
                if kind == "verify":
                    self.reap_verify(wid, rc)
                else:
                    self.reap_segment(wid, name, rc)
            for wid in list(self.running):
                p, name, kind = self.running[wid]
                if kind != "segment":
                    continue
                ext = self.watch(wid)
                try:
                    self.archive_pass(wid, alive=True)
                    self.accept_pass(wid, alive=True)
                except (WorldsError, ckpt.CheckpointError, ValueError) as e:
                    log(f"FAILED {wid}: {e}; stopping it")
                    runlib.stop_groups([self.running.pop(wid)[0]], log)
                    self.end_world(wid, "failed", str(e))
                    continue
                if ext and a.on_extinction == "stop" and wid not in self.extinct:
                    self.extinct[wid] = f"the {ext[0]} reached 0 at frame {ext[1]}"
                    try:
                        os.killpg(p.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            if os.path.exists(os.path.join(self.root, "STOP")) and stop_reason is None:
                stop_reason = "STOP"
                log(f"STOP file: no new segments; {len(self.running)} jobs keep running")
            todo = [wid for wid in self.worlds
                    if wid not in self.running and self.state(wid)["status"] in ("pending", "interrupted")]
            while stop_reason is None and todo and len(self.running) < a.workers:
                why = runlib.disk_problem(self.guards)
                if why:
                    stop_reason = f"disk guard: {why}"
                    log(stop_reason)
                    break
                head = runlib.mem_headroom_mb()
                if head is None:
                    mem_bad += 1
                    if mem_bad >= 20 and not self.running:
                        log("memory reading unavailable with nothing running: exiting (fail closed)")
                        return 2
                    break
                mem_bad = 0
                if head < a.mem_min_mb + 300:
                    break
                wid = todo.pop(0)
                try:
                    kind, info = self.next_action(wid)
                    if kind in ("done", "extinct"):
                        self.end_world(wid, kind, info)
                        log(f"{wid}: at its end ({kind}: {info})")
                    elif kind == "verify":
                        self.spawn_verify(wid)
                    else:
                        start, cpath, rec = info
                        self.spawn_segment(wid, start, cpath, rec)
                except (WorldsError, ckpt.CheckpointError, OSError, ValueError, subprocess.SubprocessError) as e:
                    self.end_world(wid, "failed", str(e))
                    log(f"FAILED {wid}: {e}")
            if not self.running and (stop_reason or not todo):
                break
            t_end = time.monotonic() + a.poll
            while time.monotonic() < t_end and all(p.poll() is None for p, _, _ in self.running.values()):
                time.sleep(min(0.2, a.poll))
        states = {wid: self.state(wid)["status"] for wid in self.worlds}
        counts = {s: sum(1 for v in states.values() if v == s) for s in sorted(set(states.values()))}
        log(f"supervisor exits: {counts}")
        if stop_reason:
            return 75
        return 1 if counts.get("failed") else 0


def launch(a, log):
    root = os.path.abspath(a.root)
    reg, sha = load_registry(root, a.allow_placeholder)
    archive_root = bind_root(root, sha, a.archive_root, create=True)
    exe, exe_sha = pin_binary(root, a.binary)
    sup = Supervisor(root, reg, archive_root, exe, exe_sha, a, log)
    sup.guards = runlib.disk_guards(a.disk_min, root)
    return sup.run()


# ================================================================== F1
def f1(a, log):
    root = os.path.abspath(a.root)
    reg, sha = load_registry(root, a.allow_placeholder)
    archive_root = bind_root(root, sha, a.archive_root, create=True)
    exe, exe_sha = pin_binary(root, a.binary)
    sched = reg["schedule"]
    rc = 0
    for w in reg["worlds"]:
        if a.world and w["id"] not in a.world:
            continue
        recs = archive_records(root, w["id"], repair=True)
        if "F1" in recs:
            if recs["F1"].get("binary_sha256") != exe_sha:
                log(f"{w['id']}: its F1 was archived by another engine")
                rc = 1
            continue
        d = os.path.join(wdir(root, w["id"]), "f1")
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d)
        args = segment_args(w, sched, "f1", 0)
        args[args.index("--headless") + 1] = "1"
        args[args.index("--save-checkpoint") + 1] = "f1/F1.json"
        args[args.index("--csv") + 1] = "f1/f1.csv"
        with open(os.path.join(d, "stdout.log"), "w") as so, open(os.path.join(d, "stderr.log"), "w") as se:
            r = subprocess.call([exe] + args, cwd=wdir(root, w["id"]), stdout=so, stderr=se,
                                stdin=subprocess.DEVNULL, preexec_fn=rqlib.death_signal())
        if r != 0:
            log(f"{w['id']}: the F1 replay exited {r}")
            rc = 1
            continue
        p = os.path.join(d, "F1.json")
        probs = verify_config(ckpt.load(p), w["flags"])
        if probs:
            log(f"{w['id']}: F1's configuration differs from the registry ({'; '.join(probs)}): not archived")
            rc = 1
            continue
        archive_one(root, w["id"], archive_root, 1, p, log, extra={"binary_sha256": exe_sha})
    return rc


def verify_f1(a, log):
    root = os.path.abspath(a.root)
    reg, sha = load_registry(root, a.allow_placeholder)
    bind_root(root, sha, a.archive_root)
    exe, exe_sha = pin_binary(root)
    first = reg["schedule"]["checkpoint_every"]
    rc = 0
    for w in reg["worlds"]:
        if a.world and w["id"] not in a.world:
            continue
        recs = archive_records(root, w["id"])
        if "F1" not in recs or label_of(first) not in recs:
            log(f"{w['id']}: F1 or the first checkpoint ({first}) is not archived yet")
            rc = rc or 3
            continue
        d = os.path.join(wdir(root, w["id"]), "f1verify")
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d)
        with open(os.path.join(d, "stdout.log"), "w") as so, open(os.path.join(d, "stderr.log"), "w") as se:
            r = subprocess.call([exe] + verify_args(recs["F1"]["path"], first), cwd=d, stdout=so, stderr=se,
                                stdin=subprocess.DEVNULL, preexec_fn=rqlib.death_signal())
        same = record_verify(root, w["id"], r, d, first, exe_sha)["identical"]
        log(f"{w['id']}: F1 {'lies on' if same else 'DOES NOT lie on'} the history's trajectory "
            f"(resumed to frame {first}: {'identical' if same else 'different'})")
        if same:
            shutil.rmtree(d)
        else:
            rc = 1
    return rc


# ================================================================== stitch
def stitch(root, wid, reg, partial=False):
    """Join the accepted chain of a world's segments (see the module doc) into
    STUDY/worlds/<id>/stitched/ -> manifest."""
    w = {x["id"]: x for x in reg["worlds"]}[wid]
    sched = reg["schedule"]
    T, L = sched["total_steps"], sched["log_every"]
    st = read_state(root, wid)
    if st["status"] not in ("done", "extinct") and not partial:
        raise WorldsError(f"{wid} is {st['status']}, not done or extinct: --partial for a partial stitch")
    good = verified_records(root, wid, st, w["treatment"])
    if not good:
        raise WorldsError(f"{wid}: no accepted checkpoint")
    end = max(good.values(), key=lambda r: (r["frame"], _seg_index(r["segment"])))
    endpoint = end["frame"]
    if st["status"] == "done" and endpoint != T:
        raise WorldsError(f"{wid} is done, but its accepted logs end at frame {endpoint}, not {T}")
    segs = {s["name"]: s for s in st["segments"]}
    chain, cur = [], end
    while True:
        s = segs[cur["segment"]]
        chain.append((s, cur))
        if s["start_frame"] == 0:
            break
        ra = s["resumed_accept"]
        cur = good[(ra["segment"], ra["frame"])]
    chain.reverse()
    d = wdir(root, wid)
    out = os.path.join(d, "stitched")
    os.makedirs(out, exist_ok=True)
    arecs = archive_records(root, wid)
    man = {"world": wid, "status": st["status"], "endpoint": endpoint, "complete": endpoint == T, "files": {}}
    for name, kind in log_kinds(w["treatment"]):
        header, rows_out = None, []
        for s, rec in chain:
            n = rec["logs"][name]["bytes"]
            path = os.path.join(d, s["name"], name)
            with open(path, "rb") as f:
                data = f.read(n)
            if len(data) != n:
                raise WorldsError(f"{wid}: {s['name']}/{name} is shorter than its accepted {n} bytes")
            rows = list(csv.reader(io.StringIO(data.decode("utf-8"))))
            hdr, rows = rows[0], rows[1:]
            if header is None:
                header = hdr
            elif hdr != header:
                raise WorldsError(f"{wid}: {s['name']}/{name} has another header")
            if kind == "events" and s["start_frame"] > 0:
                rows = [r for r in rows if r[1] != "L"]
            if kind == "steps":
                rows = [[str(int(r[0]) + s["start_frame"])] + r[1:] for r in rows]
            if name == "run.csv" and s["start_frame"] > 0 and rows:
                # the resumed segment's first row counts the loaded world's history in its interval columns
                ra = s["resumed_accept"]
                src = good_copy(root, wid, ra["frame"], ra["sha256"], arecs)
                if src is None:
                    raise WorldsError(f"{wid}: the checkpoint {s['name']} resumed (frame {ra['frame']}) is gone")
                ctr = ckpt.load(src)["counters"]
                first = list(rows[0])
                for col, key in INTERVAL_FIX:
                    i = hdr.index(col)
                    first[i] = str(int(first[i]) - int(ctr.get(key, 0)))
                rows[0] = first
            rows_out += rows
        frames = [int(r[0]) for r in rows_out]
        if any(len(r) != len(header) for r in rows_out):
            raise WorldsError(f"{wid} {name}: a stitched row has the wrong number of fields")
        if kind == "events":
            if frames != sorted(frames) or (frames and frames[-1] > endpoint):
                raise WorldsError(f"{wid} {name}: the stitched lineage log is out of frame order")
        elif frames != list(range(L, endpoint + 1, L)):
            raise WorldsError(f"{wid} {name}: the stitched rows are not contiguous every {L} steps through {endpoint}")
        buf = io.StringIO()
        wr = csv.writer(buf, lineterminator="\n")
        wr.writerow(header)
        wr.writerows(rows_out)
        data = buf.getvalue().encode()
        rqlib.write_durable(os.path.join(out, name), data)
        man["files"][name] = {"sha256": rqlib.sha256_bytes(data), "rows": len(rows_out),
                              "last_frame": frames[-1] if frames else None}
    man["segments"] = [{"name": s["name"], "start_frame": s["start_frame"], "until": rec["frame"]} for s, rec in chain]
    man["unused_segments"] = sorted(set(segs) - {s["name"] for s, _ in chain})
    man["corrections"] = {"run.csv": f"the first row of every resumed segment: {[c for c, _ in INTERVAL_FIX]} minus "
                                     "the counters of the checkpoint it resumed", "run.wiring.csv": "step -> frame",
                          "run.predlog.csv": "a resumed segment's L rows dropped"}
    man["not_continuable"] = {"run.csv": list(NON_CONTINUABLE)}
    rqlib.write_json_durable(os.path.join(out, "manifest.json"), man)
    return man


# ================================================================== design block, status
def design_block(root, reg, archive_root):
    s = reg["schedule"]
    times = {"F1": 1}
    for f in range(s["checkpoint_every"], s["total_steps"] + 1, s["checkpoint_every"]):
        times[f"{f // 1_000_000}M" if f % 1_000_000 == 0 else f"f{f}"] = f
    ws = {}
    led = read_jsonl(os.path.join(root, "availability.jsonl"))
    for w in reg["worlds"]:
        ad = adir(archive_root, w["id"])
        zeros = first_zeros(led, w["id"])
        st = read_state(root, w["id"])
        ws[w["id"]] = {"uuid": w["uuid"], "treatment": w["treatment"], "block": w["block"], "status": st["status"],
                       "pattern": os.path.join(ad, "end.{frame}.json"), "paths": {"F1": os.path.join(ad, "F1.json")},
                       # snapshots at or after a guild's first zero are not valid challengers (design §2.3)
                       "valid_before": min(zeros.values()) if zeros else None,
                       "archived": sorted(r["frame"] for r in archive_records(root, w["id"]).values())}
    return {"schema": "finfolk.redqueen.worldsblock/1", "registry_sha256": rqlib.sha256_file(
        os.path.join(root, "config", "worlds.json")), "times": times, "worlds": ws}


def status(root):
    reg, sha = load_registry(root, allow_placeholder=True)
    out = {"root": root, "worlds": {}}
    try:
        out["archive_root"] = bind_root(root, sha)
    except WorldsError as e:
        out["binding"] = str(e)
    for w in reg["worlds"]:
        st = read_state(root, w["id"])
        recs = archive_records(root, w["id"])
        acc = [r["frame"] for r in accept_records(root, w["id"])]
        last = None
        if st["segments"]:
            hdr, row = _last_row(os.path.join(wdir(root, w["id"]), st["segments"][-1]["name"], "run.csv"))
            if row:
                r = dict(zip(hdr, row))
                last = {k: r.get(k) for k in ("step", "population", "predator_pop", "steps_per_sec")}
        out["worlds"][w["id"]] = {"treatment": w["treatment"], "status": st["status"], "segments": len(st["segments"]),
                                  "archived": len(recs), "accepted_through": max(acc) if acc else None,
                                  "last_row": last}
    counts = {}
    for v in out["worlds"].values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    out["counts"] = counts
    out["availability"] = read_jsonl(os.path.join(root, "availability.jsonl"))
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0


# ================================================================== CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register")
    r.add_argument("--arena", required=True)
    r.add_argument("--namespace", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--blocks", type=int, default=8)
    r.add_argument("--per-block", default="C=4,A=1,B=1")
    r.add_argument("--c-founders", type=int, default=C_FOUNDERS)
    r.add_argument("--avoid", action="append", default=[])
    r.add_argument("--total-steps", type=int, default=DEFAULT_SCHEDULE["total_steps"])
    r.add_argument("--checkpoint-every", type=int, default=DEFAULT_SCHEDULE["checkpoint_every"])
    r.add_argument("--log-every", type=int, default=DEFAULT_SCHEDULE["log_every"])
    r.add_argument("--allow-placeholder", action="store_true")
    for name in ("f1", "launch", "verify-f1", "stitch", "status", "design-block"):
        s = sub.add_parser(name)
        s.add_argument("--root", required=True)
        s.add_argument("--allow-placeholder", action="store_true")
        s.add_argument("--archive-root")
        if name in ("f1", "launch"):
            s.add_argument("--binary", required=True)
        if name in ("f1", "verify-f1"):
            s.add_argument("--world", action="append")
        if name == "stitch":
            s.add_argument("--world", required=True)
            s.add_argument("--partial", action="store_true")
        if name == "design-block":
            s.add_argument("--out", required=True)
        if name == "launch":
            s.add_argument("--workers", type=int, default=10)
            s.add_argument("--mem-min-mb", type=int, default=8192)
            s.add_argument("--disk-min", action="append", metavar="PATH:MB")
            s.add_argument("--retries", type=int, default=3)
            s.add_argument("--on-extinction", choices=("stop", "continue"), default="stop")
            s.add_argument("--prune-local", action="store_true")
            s.add_argument("--retry-failed", action="store_true",
                           help="put the worlds marked failed back in the queue (after the cause is fixed)")
            s.add_argument("--poll", type=float, default=30.0)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "register":
            reg = register(a.arena, a.namespace, a.blocks, parse_per_block(a.per_block), a.avoid,
                           {"total_steps": a.total_steps, "checkpoint_every": a.checkpoint_every,
                            "log_every": a.log_every}, a.allow_placeholder, a.c_founders)
            new = write_registry(a.out, rqlib.canonical(reg))
            n = {t: sum(1 for w in reg["worlds"] if w["treatment"] == t) for t in TREATMENTS}
            print(f"registered {len(reg['worlds'])} worlds {n} in {a.blocks} blocks -> {a.out} "
                  f"({'written' if new else 'unchanged'}; sha256 {rqlib.sha256_file(a.out)})"
                  + ("; TAINTED (placeholder): tests only" if reg["taint"]["tainted"] else ""), file=sys.stderr)
            return 0
        root = os.path.abspath(a.root)
        if a.cmd == "status":
            return status(root)
        if a.cmd == "design-block":
            reg, sha = load_registry(root, allow_placeholder=True)
            blk = design_block(root, reg, bind_root(root, sha, a.archive_root))
            rqlib.write_durable(a.out, rqlib.canonical(blk))
            return 0
        if a.cmd == "stitch":
            reg, sha = load_registry(root, a.allow_placeholder)
            bind_root(root, sha, a.archive_root)
            man = stitch(root, a.world, reg, a.partial)
            print(json.dumps(man["files"], indent=1, sort_keys=True))
            return 0
        lock = _flock(os.path.join(root, ".worlds.lock"))
        os.nice(19 - os.nice(0))
        with lock, open(os.path.join(root, "supervisor.log"), "a") as logf:
            def log(msg):
                line = f"{rqlib.now_utc()} {msg}"
                for o in (sys.stdout, logf):
                    try:
                        o.write(line + "\n")
                        o.flush()
                    except (OSError, ValueError):
                        pass
            if a.cmd == "f1":
                return f1(a, log)
            if a.cmd == "verify-f1":
                return verify_f1(a, log)
            return launch(a, log)
    except (WorldsError, ckpt.CheckpointError, OSError, KeyError, ValueError) as e:
        print(f"worlds.py {a.cmd}: {e}", file=sys.stderr)
        return 73 if isinstance(e, WorldsError) and "another worlds.py holds" in str(e) else 2


if __name__ == "__main__":
    sys.exit(main())

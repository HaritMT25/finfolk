#!/usr/bin/env python3
"""worlds.py: register the Red Queen study's 48 evolutionary histories and run them (design v3 §2, §13).

    worlds.py register --arena config/arena.selected.json --namespace NS --out STUDY/config/worlds.json
                       [--blocks 8] [--per-block C=4,A=1,B=1] [--c-founders 6] [--avoid FILE ...]
                       [--burn-in 5000000] [--max-restarts 8]
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
Eight randomized blocks of four C, one A and one B history (48 worlds; --per-block, up to 4C + 2A + 2B
per block: the 56 / 64-world allocations of the H-C pilot rule; any count for tests). Within each
block the treatment order is a seeded permutation (namespace, "block-order", block), so a world's id
does not reveal its treatment by position. Each world has an id (w01..), a UUID (uuid5 of the
namespace and id) and a SEED SLOT "b<block>:<treatment>:<k>" (k: its index among its block's
worlds of that treatment). SEED RESERVATIONS (seed scheme "slot/1"): every slot of up to 4C + 2A + 2B
per block (more if --per-block asks) reserves 1 + --max-restarts seeds, derived from (namespace,
"founder", "b<b>", treatment, "k<k>"[, "a<attempt>"]), unique and refused if they occur in any --avoid
file (integers, or any JSON / JSONL whose keys contain "seed": the archived plans and reservations of
other streams); a world's founder seed is its slot's first, so a slot keeps its seeds whatever the
allocation (48, 56 or 64 worlds need no re-registration logic).

THE BURN-IN RULE (USER DECISIONS 2, item 6; registries of seed scheme slot/1, --burn-in frames, 0
disables). A world (C, A or B) that goes extinct (any guild's evidenced first zero) BEFORE the burn-in
frame (5M) is not ended: it is RESTARTED from its slot's next reserved seed. The restart is first
recorded durably in STUDY/restarts.jsonl (world, slot, the attempt, the failed seed and the new one,
the zero), then the failed attempt's directory is moved to STUDY/restarts/worlds/<id>.a<n> and its
(unfinalized) archive to ARCHIVE/restarts/<id>.a<n>, and the world starts afresh (attempt.json: its
attempt and seed; state pending): its F1 is made by the supervisor itself with the pinned engine, then
the usual history (F1 verification before its first resume). A crash between the record and the moves
is completed at the next start; availability records carry their attempt and count only for the
current one. After --max-restarts restarts the world ends extinct (the restarts exhausted). Extinction
at or after the burn-in frame is data, as before. status reports every restart and the early-
establishment failure rate per treatment (restarts / attempts started).

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

THE STUDY ROOT. The first f1 or launch binds STUDY to its registry: STUDY/study.json records a
study id, the registry's sha256 and the archive root (default STUDY/archive); every later command
refuses a different registry or archive root. The archive root belongs to its study: it must be
new or empty when the study is bound, and ARCHIVE/OWNER.json names the study id; an archive root
owned by another study, or not empty and unowned, is refused, so a new study can never publish
into another's archive. Every writing command (f1, launch, verify-f1) holds, besides the study
root's lock, an flock on ARCHIVE/.archive.lock for its whole run: two roots naming one archive
never run at once. The claim is exclusive: OWNER.json.tmp is written and fsync'd, then hard-linked
to OWNER.json (which fails if any marker exists), the directory fsync'd, the tmp removed; a
leftover tmp carrying this study's id (a claim a crash interrupted) is completed, another study's
or an unreadable one is refused. Every directory the tool creates is made durable with its
ancestors. The engine is pinned in STUDY/bin (its sha256) and probed once: it must be the serial
build (its checkpoints say "resume is bit-exact").

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
found at its final accepted frame is finalized without another segment. Local checkpoints follow
a COMMITMENT rule (never a guess from where a parse fails): a checkpoint is committed once it has
an archive record. An uncommitted one that is not a valid serial-build checkpoint of its frame,
for any reason, is moved to ckpt/quarantine/ (its bytes, the move and both directories fsync'd,
then recorded in quarantine.jsonl) and the world replays from its last accepted checkpoint; if the
replay regenerates an invalid file at a frame quarantined before (its writer finished it: the
main CSV has a row past it), the world fails closed. A committed one with other bytes than its
record fails closed when its last writer finished it (a deterministic regeneration must reproduce
the record); otherwise (a rewrite cut short, or damage to a copy no running segment writes) the
local copy is restored from the verified archived copy, its bad bytes quarantined. The dense logs'
header and every row's width are checked at acceptance; a resumed segment's headers must equal
those of the segment it resumed. A new segment's directory is made durable at creation and again
(its log entries) before its first acceptance. At every start a finalized archive is audited in
full (every indexed object rehashed) before anything else, its damage failing the world (exit 1).
A done or extinct world then keeps its status only while its evidence holds: a done world's
verified chain must reach the final frame; an extinct world needs a zero whose evidence holds and
its latest acceptance at or before the first zero must verify; otherwise it is reopened and
recovered from its verified evidence.

ARCHIVE. Every complete periodic checkpoint (and F1) is copied verified into ARCHIVE/worlds/<id>/
(a temporary file, fsync'd, hashed, read-only 0444, renamed, directory fsync'd) and recorded in
STUDY/worlds/<id>/archive.jsonl. A checkpoint rewritten by a resumed segment must have its
archived bytes (determinism; a difference stops the world as "failed"). An archived copy found
missing, damaged or writable is repaired from verified local bytes (refused once finalized).
When a world ends ("done" or "extinct"), its archive is audited and finalized: a FINALIZED marker
(published atomically: the world, its status and archived frames), every file 0444, the directory
0555, both fsync'd: the contract run.py --link-sources checks. Every start audits each
finalized archive (rehashing every indexed object) and reconciles the finalization of the
terminal worlds. No checkpoint is ever published or replaced inside a finalized directory (only
the marker's and directory's modes are reconciled), and a destination file without this study's
record is never replaced. --prune-local deletes local copies of the checkpoints of the currently
verified acceptance chain, up to the active segment's last acceptance (a replay keeps every later
one), except the two latest, after verifying their archived copies.

BIOLOGY. A guild that reaches zero in the main CSV (prey: population; predators of C and B:
predator_pop) is recorded in STUDY/availability.jsonl (append-only, fsync'd: world, guild, first
frame, the archived frames before it) with its evidence: the segment's main-CSV prefix through the
zero row is fsync'd first and the record binds its byte count and sha256. A guild's first zero is
the minimum over the records whose evidence still holds; a record whose evidence is lost does not
count (the replay finds the zero again). Every restart, terminal worlds included, scans every
segment's main CSV, so a zero the previous supervisor did not see is recorded with its earliest
frame ("recovered"). Extinction is absorbing (both floors are zero);
--on-extinction stop (default) then ends the world as "extinct" without advancing it (its valid
pre-extinction snapshots stay archived; nothing is refilled or replaced), but only while the stop
is evidenced (above): a world at its zero whose accepted logs through the zero no longer verify
replays from its latest verified record through the zero, which stops it again; if that replay
did not repair them, it fails (exit 1). Such a replay's checkpoints past the zero are not
published into a finalized archive (not part of the history).

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
OWNER_SCHEMA = "finfolk.redqueen.archiveowner/1"
OWNER = "OWNER.json"
SERIAL = "serial build (resume is bit-exact)"
TREATMENTS = ("C", "A", "B")
C_FOUNDERS = 6
DEFAULT_SCHEDULE = {"total_steps": 200_000_000, "checkpoint_every": 1_000_000, "log_every": 5000}
SEED_SCHEME = "slot/1"
RESERVE = {"C": 4, "A": 2, "B": 2}       # seed slots reserved per block (USER DECISIONS 2: up to 2A + 2B)
BURN_IN = 5_000_000                      # frames: an extinction before it restarts the world
MAX_RESTARTS = 8
RESTART_SCHEMA = "finfolk.redqueen.restart/1"
ATTEMPT_SCHEMA = "finfolk.redqueen.attempt/1"
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
    """An UNCOMMITTED local checkpoint (no archive record) that is not a valid serial-build
    checkpoint of its frame, for any reason: quarantined, and the world replays."""


class CommittedMismatch(WorldsError):
    """A local checkpoint of a COMMITTED label (it has an archive record) with other bytes."""

    def __init__(self, msg, rec):
        super().__init__(msg)
        self.rec = rec


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
                probs.append(f"A: --{k} needs the economy (A's canonical form leaves every economy flag out, "
                             "--predator-economy included; with the economy off they would be inert)")
    return probs, unresolved


CANONICAL = ("the canonical form gives a shared setting the same explicit value in every treatment (best in "
             "'common'); an omitted flag is not taken as equal to an explicit engine default")


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
        probs.append(f"the common environment differs across treatments: --{d} ({CANONICAL})")
    if "C" in eff and "B" in eff:
        for d in differ(SAME_CB, ["C", "B"]):
            probs.append(f"C and B must share the selected economics and kinematics: --{d} ({CANONICAL})")
    if "A" in eff:
        for o in [t for t in ("C", "B") if t in eff][:1]:
            for d in differ(SAME_KINEMATICS, ["A", o]):
                probs.append(f"A must share the predator kinematics (cooldown included: v4 makes A's predator count "
                             f"its pressure knob): --{d} ({CANONICAL})")
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
             allow_placeholder=False, c_founders=C_FOUNDERS, burn_in=BURN_IN, max_restarts=MAX_RESTARTS):
    per_block = per_block or {"C": 4, "A": 1, "B": 1}
    if burn_in < 0 or max_restarts < 0:
        raise WorldsError("--burn-in and --max-restarts are >= 0")
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
    # every reserved slot's seeds first (block, treatment, k, attempt order): a slot's seeds never depend
    # on the allocation actually registered
    reserve = {t: max(RESERVE[t], per_block[t]) for t in TREATMENTS}
    used_seeds, reserved, slot_seeds = set(), [], {}
    for b in range(1, blocks + 1):
        for t in TREATMENTS:
            for k in range(reserve[t]):
                seeds, redo = [], []
                for att in range(max_restarts + 1):
                    j = 0
                    while True:
                        parts = [f"b{b}", t, f"k{k}"] + ([f"a{att}"] if att else []) + ([j] if j else [])
                        seed = rqlib.derive_seed(namespace, "founder", *parts)
                        if seed not in used_seeds and seed not in avoid and seed != 0:
                            break
                        j += 1
                    used_seeds.add(seed)
                    seeds.append(seed)
                    redo.append(j)
                key = f"b{b}:{t}:{k}"
                slot_seeds[key] = (seeds, redo)
                reserved.append({"slot": key, "block": b, "treatment": t, "k": k, "seeds": seeds})
    worlds, idx = [], 0
    for b in range(1, blocks + 1):
        order = [(t, k) for t in TREATMENTS for k in range(per_block[t])]
        rqlib.SplitMix64(rqlib.derive64(namespace, "block-order", b)).shuffle(order)
        for slot, (t, k) in enumerate(order):
            idx += 1
            wid = f"w{idx:02d}"
            key = f"b{b}:{t}:{k}"
            seed = slot_seeds[key][0][0]
            flags = treatment_flags(arena, t)
            worlds.append({
                "id": wid, "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:redqueen:{namespace}:{wid}")),
                "index": idx, "block": b, "slot": slot, "seed_slot": key, "treatment": t, "founder_seed": seed,
                "seed_rederived": slot_seeds[key][1][0], "flags": flags,
                "config_args": flags_to_args(flags) + ["--seed", str(seed)], "predator_log": t == "C"})
    tainted = arena.get("status") != "selected" or bool(unresolved)
    return {"schema": WORLDS_SCHEMA, "namespace": namespace, "blocks": blocks, "per_block": per_block,
            "c_founders": c_founders, "schedule": schedule, "seed_scheme": SEED_SCHEME, "burn_in": burn_in,
            "max_restarts": max_restarts, "reserve_per_block": reserve, "reserved": reserved,
            "arena": {"path": os.path.abspath(arena_path), "sha256": rqlib.sha256_bytes(raw),
                      "status": arena.get("status")},
            "taint": {"tainted": tainted, "unresolved": unresolved},
            "avoid": avoid_rec, "tool_sha256": rqlib.sha256_file(os.path.abspath(__file__)), "worlds": worlds}


def _flock(path):
    """An exclusive, non-blocking flock on path (created) -> the open file; WorldsError if held."""
    import fcntl
    mkdirs_durable(os.path.dirname(path))
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
        mkdirs_durable(d)
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


ARCHIVE_LOCK = ".archive.lock"
_HELD = {}     # archive root -> its lock file, held for the whole command


def lock_archive(ar):
    """An exclusive flock on ARCHIVE/.archive.lock, held until the process ends (with the root lock:
    one command at a time per archive root, whatever study root names it)."""
    if ar not in _HELD:
        mkdirs_durable(ar)
        _HELD[ar] = _flock(os.path.join(ar, ARCHIVE_LOCK))
    return _HELD[ar]


def release_archives():
    """Release the archive locks this process holds (the end of a command; tests)."""
    while _HELD:
        _HELD.popitem()[1].close()


def _owner_tmp(ar):
    """The study id of a leftover OWNER.json.tmp (an interrupted claim): None if there is none;
    "?" if it is unreadable."""
    p = os.path.join(ar, OWNER + ".tmp")
    if not os.path.exists(p):
        return None
    try:
        return rqlib.read_json(p).get("study_id") or "?"
    except (OSError, ValueError):
        return "?"


def _archive_free(ar, study_id=None):
    """Why the archive root `ar` cannot be claimed by a new study (None: it can: absent, empty but
    for its lock file, or holding only this study's interrupted claim)."""
    if not os.path.exists(ar):
        return None
    if not os.path.isdir(ar):
        return f"{ar} is not a directory"
    owner = os.path.join(ar, OWNER)
    if os.path.isfile(owner):
        o = rqlib.read_json(owner)
        if o.get("study_id") == study_id:
            return None
        return f"the archive root {ar} belongs to another study ({o.get('study_root')}, study {o.get('study_id')})"
    tmp = _owner_tmp(ar)
    if tmp not in (None, study_id):
        return f"the archive root {ar} holds another study's interrupted claim (OWNER.json.tmp: {tmp})"
    entries = sorted(set(os.listdir(ar)) - {ARCHIVE_LOCK, OWNER + ".tmp"})
    if entries:
        return f"the archive root {ar} is not empty and has no owner ({', '.join(entries[:3])})"
    return None


def claim_archive(ar, study, write=True):
    """The archive root's ownership marker (OWNER.json: the study's id, root and registry). An
    existing one must name this study. A claim (write; under the archive lock) is exclusive: the
    marker is written to OWNER.json.tmp, fsync'd, and hard-linked to OWNER.json (which fails if any
    marker exists), the directory fsync'd, the tmp removed. A leftover tmp of this study (a claim a
    crash interrupted) is completed; another study's, or an unreadable one, is refused."""
    owner = os.path.join(ar, OWNER)
    if os.path.isfile(owner):
        o = rqlib.read_json(owner)
        if o.get("study_id") != study["study_id"]:
            raise WorldsError(f"the archive root {ar} belongs to another study ({o.get('study_root')}, study "
                              f"{o.get('study_id')}): every study needs its own archive root")
        if write and _owner_tmp(ar) == study["study_id"]:
            os.remove(owner + ".tmp")
            rqlib.fsync_dir(ar)
        return
    if not write:
        raise WorldsError(f"the archive root {ar} carries no ownership marker of this study")
    lock_archive(ar)
    why = _archive_free(ar, study["study_id"])
    if why:
        raise WorldsError(why)
    tmp = owner + ".tmp"
    mine = _owner_tmp(ar) is None
    if mine:
        rec = {"schema": OWNER_SCHEMA, "study_id": study["study_id"], "study_root": study["study_root"],
               "registry_sha256": study["registry_sha256"], "claimed_utc": rqlib.now_utc()}
        with open(tmp, "xb") as f:
            f.write(rqlib.canonical(rec))
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o444)
        rqlib.fsync_dir(ar)
    try:
        os.link(tmp, owner)                        # exclusive: fails if any marker exists
    except FileExistsError:
        o = rqlib.read_json(owner)
        if o.get("study_id") != study["study_id"]:
            if mine:
                os.remove(tmp)
                rqlib.fsync_dir(ar)
            raise WorldsError(f"the archive root {ar} was claimed by another study ({o.get('study_id')}) first")
    rqlib.fsync_dir(ar)
    os.remove(tmp)
    rqlib.fsync_dir(ar)


def bind_root(root, reg_sha, archive_root=None, create=False, readonly=False):
    """The study root's binding (STUDY/study.json: a study id, the registry's sha256 and the archive
    root, which the study owns: ARCHIVE/OWNER.json names the study) -> the archive root. create:
    bind an unbound root (refused if it already holds artifacts, or if the archive root is another
    study's or not empty)."""
    p = os.path.join(root, "study.json")
    if os.path.isfile(p):
        rec = rqlib.read_json(p)
        if rec.get("schema") != STUDY_SCHEMA or not rec.get("study_id"):
            raise WorldsError(f"{p}: schema {rec.get('schema')!r}, study id {rec.get('study_id')!r}")
        if rec["registry_sha256"] != reg_sha:
            raise WorldsError(f"{root} is bound to the registry {rec['registry_sha256'][:12]}, but config/worlds.json "
                              f"is now {reg_sha[:12]}: a changed registry needs a new study root")
        if archive_root and os.path.abspath(archive_root) != rec["archive_root"]:
            raise WorldsError(f"{root} is bound to the archive root {rec['archive_root']}, not {archive_root}")
        if not readonly:
            lock_archive(rec["archive_root"])
        claim_archive(rec["archive_root"], rec, write=not readonly)   # (completes an interrupted claim)
        return rec["archive_root"]
    if not create:
        raise WorldsError(f"{root} is not bound to its registry yet (worlds.py f1 or launch binds it)")
    present = [x for x in ("worlds", "bin", "availability.jsonl") if os.path.exists(os.path.join(root, x))]
    if present:
        raise WorldsError(f"{root} holds study artifacts ({', '.join(present)}) but no study.json: not binding it")
    ar = os.path.abspath(archive_root or os.path.join(root, "archive"))
    why = _archive_free(ar)
    if why:
        raise WorldsError(why + ": a new study needs a new (or empty) archive root")
    lock_archive(ar)                                # (refused while another command holds it)
    why = _archive_free(ar)
    if why:
        raise WorldsError(why + ": a new study needs a new (or empty) archive root")
    rec = {"schema": STUDY_SCHEMA, "study_id": str(uuid.uuid4()), "study_root": os.path.abspath(root),
           "registry_sha256": reg_sha, "archive_root": ar, "created_utc": rqlib.now_utc(),
           "tool_sha256": rqlib.sha256_file(os.path.abspath(__file__))}
    mkdirs_durable(root)
    rqlib.write_json_durable(p, rec)
    claim_archive(ar, rec)
    return ar


# ================================================================== layout
def base_frame(w):
    """The frame a world's root segment starts from: 0 for a founder history, the origin frame for a
    fork branch (forks.py: w["origin"] = {"frame", "path", "sha256", "seed"})."""
    return int((w.get("origin") or {}).get("frame", 0))


def total_steps(w, sched):
    """The frame a world ends at: its own total_steps (a fork branch: origin + horizon) or the schedule's."""
    return int(w.get("total_steps") or sched["total_steps"])


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
    mkdirs_durable(wdir(root, wid))
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


def attempt_of(root, wid):
    """A world directory's attempt (attempt.json; 0 without it)."""
    p = os.path.join(wdir(root, wid), "attempt.json")
    return int(rqlib.read_json(p)["attempt"]) if os.path.isfile(p) else 0


def restart_records(root, wid=None, repair=False):
    led = read_jsonl(os.path.join(root, "restarts.jsonl"), repair)
    return [r for r in led if wid is None or r.get("world") == wid]


def effective_world(reg, w, attempt):
    """A registry world at an attempt: attempt n > 0 runs its slot's n-th reserved seed."""
    if not attempt:
        return w
    slot = next((r for r in reg.get("reserved", []) if r["slot"] == w.get("seed_slot")), None)
    if slot is None or attempt >= len(slot["seeds"]):
        raise WorldsError(f"{w['id']}: attempt {attempt} has no reserved seed")
    seed = slot["seeds"][attempt]
    return dict(w, founder_seed=seed, config_args=flags_to_args(w["flags"]) + ["--seed", str(seed)], attempt=attempt)


def effective_worlds(root, reg):
    """{id: the registry world at its current attempt (the restart ledger's count)}."""
    n = {}
    for r in restart_records(root):
        n[r["world"]] = max(n.get(r["world"], 0), int(r["attempt"]))
    return {w["id"]: effective_world(reg, w, n.get(w["id"], 0)) for w in reg["worlds"]}


def zero_supported(root, e):
    """An availability record's evidence still holds: the prefix of its segment's main CSV that
    contains the zero row (its byte count and sha256, fsync'd before the record) is intact, and it
    belongs to the world's current attempt (a restarted world's earlier zeros are not its own)."""
    seg, n, sha = e.get("segment"), e.get("csv_bytes"), e.get("csv_sha256")
    if not (seg and n and sha):
        return False
    try:
        if int(e.get("attempt", 0)) != attempt_of(root, e["world"]):
            return False
    except (OSError, ValueError, KeyError):
        return False
    try:
        with open(os.path.join(wdir(root, e["world"]), seg, "run.csv"), "rb") as f:
            data = f.read(n)
    except OSError:
        return False
    return len(data) == n and rqlib.sha256_bytes(data) == sha


def first_zeros(ledger, wid, root=None):
    """{guild: the earliest recorded first-zero frame} of a world (the ledger's minimum; with root,
    over the records whose evidence still holds)."""
    out = {}
    for e in ledger:
        if e["world"] == wid and (root is None or zero_supported(root, e)):
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
    """New complete lines of a growing file since the last call (a torn last line waits); `ends`
    holds each returned row's end offset in the file (the prefix that supports it)."""

    def __init__(self, path):
        self.path, self.offset, self.header, self.ends = path, 0, None, []

    def lines(self):
        self.ends = []
        if not os.path.isfile(self.path):
            return []
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            data = f.read()
        cut = data.rfind(b"\n")
        if cut < 0:
            return []
        base = self.offset
        self.offset += cut + 1
        rows, pos = [], 0
        for ln in data[:cut + 1].split(b"\n")[:-1]:
            pos += len(ln) + 1
            if self.header is None:
                self.header = next(csv.reader([ln.decode("utf-8")]))
                continue
            if ln:
                rows.append(next(csv.reader([ln.decode("utf-8")])))
                self.ends.append(base + pos)
        return rows


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


def _header(line):
    """(columns, header sha256) of a log's header line; None if it is not one (its first column must
    be step or frame, and it needs a second)."""
    names = line.split(b",")
    if len(names) < 2 or names[0].strip() not in (b"step", b"frame") or any(not n.strip() for n in names):
        return None
    return len(names), rqlib.sha256_bytes(line)


def dense_cut(path, kind, start, frame, step, prev=None):
    """The next accepted part of a dense log: from the end of `prev` (or the start of the file, its
    header included and checked) through the row of `frame`, every `step` without a gap, every row
    as wide as the header -> {"from", "bytes", "sha256", "last_frame", "columns", "header_sha256"};
    None while the file does not reach `frame` (or has a gap, a short or long row, a bad header)."""
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
        h = _header(data[:nl])
        if h is None:
            return None
        ncol, hsha = h
        pos = nl + 1
    else:
        ncol, hsha = prev["columns"], prev["header_sha256"]
    while last < frame:
        nl = data.find(b"\n", pos)
        if nl < 0:
            return None
        parts = data[pos:nl].split(b",")
        if len(parts) != ncol:
            return None
        try:
            v = int(parts[0])
        except ValueError:
            return None
        fr = start + v if kind == "steps" else v
        if fr != last + step:
            return None
        last, pos = fr, nl + 1
    return {"from": off, "bytes": off + pos, "sha256": rqlib.sha256_bytes(data[:pos]), "last_frame": frame,
            "columns": ncol, "header_sha256": hsha}


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
        h = _header(data[:nl])
        if h is None:
            return None
        (ncol, hsha), maxf = h, -1
        pos = nl + 1
    else:
        ncol, maxf, hsha = prev["columns"], prev["max_frame"], prev["header_sha256"]
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
            "events": counts, "columns": ncol, "max_frame": maxf, "header_sha256": hsha}


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


def mkdirs_durable(path):
    """os.makedirs, then every directory it created is made durable (its parent fsync'd)."""
    path = os.path.abspath(path)
    missing = []
    p = path
    while not os.path.isdir(p):
        missing.append(p)
        p = os.path.dirname(p)
    os.makedirs(path, exist_ok=True)
    for d in reversed(missing):
        rqlib.fsync_dir(os.path.dirname(d))


def _copy_verified(raw, dst, sha):
    d = os.path.dirname(dst)
    if os.path.isfile(os.path.join(d, "FINALIZED")):
        raise WorldsError(f"{d} is finalized: nothing is published into it")
    mkdirs_durable(d)
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
    checkpoint), under the COMMITMENT rule (no guess from where a parse fails). A label with an
    archive record is committed: the local bytes must be the record's (else CommittedMismatch: the
    caller fails closed, or restores the local copy from the verified archived one, see
    Supervisor.archive_ckpt) and its archived copy is checked (ensure_archived). An uncommitted file
    that is not a valid serial-build checkpoint of `frame`, for ANY reason (cut short, corrupt,
    another frame, another build), is TornCheckpoint: the caller quarantines it (the evidence kept)
    and the world replays. WorldsError: a new label's destination this study does not own (a
    finalized archive, a foreign file)."""
    raw = rqlib.read_bytes(src)
    sha = rqlib.sha256_bytes(raw)
    lab = label_of(frame)
    recs = archive_records(root, wid)
    if lab in recs:
        if recs[lab]["sha256"] != sha:
            raise CommittedMismatch(f"{wid} {lab}: the local {os.path.basename(src)} has other bytes than its "
                                    f"committed record ({sha[:12]} != {recs[lab]['sha256'][:12]})", recs[lab])
        ensure_archived(wid, recs[lab], raw, log, verified)
        return recs[lab], ckpt.loads(raw.decode("utf-8"), src)
    try:
        cp = ckpt.loads(raw.decode("utf-8"), src)
        ckpt.validate(cp, src)
        if int(cp["world"]["frame"]) != frame:
            raise ValueError(f"it holds frame {cp['world']['frame']}")
        if cp.get("determinism") != SERIAL:
            raise ValueError(f"it declares {cp.get('determinism')!r}, not the serial build's exact resume")
    except (ckpt.CheckpointError, UnicodeDecodeError, ValueError, KeyError, TypeError) as e:
        raise TornCheckpoint(f"{os.path.basename(src)} has no record and is not a valid checkpoint of frame "
                             f"{frame} ({str(e)[:120]})")
    ad = adir(archive_root, wid)
    name = "F1.json" if frame == 1 else f"end.{frame}.json"
    dst = os.path.join(ad, name)
    if os.path.isfile(os.path.join(ad, "FINALIZED")):
        raise WorldsError(f"{wid}: {name} has no record, but {ad} is finalized: nothing is published into it")
    if os.path.exists(dst):
        if rqlib.sha256_file(dst) != sha:
            raise WorldsError(f"{dst} exists with other bytes and no record of this study: not replacing it")
        # (this study's copy, published before a crash that lost its record)
    else:
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


def audit_archive(root, wid, archive_root, status=None):
    """The full audit of a finalized archive (no-op without a FINALIZED marker; nothing written):
    the marker describes it (world, archived frames; with status, the status too) and every indexed
    object is present, 0444, of its size and rehashes to its record. WorldsError otherwise."""
    ad = adir(archive_root, wid)
    marker = os.path.join(ad, "FINALIZED")
    if not os.path.isfile(marker):
        return False
    recs = archive_records(root, wid)
    want = {"world": wid, "frames": sorted(r["frame"] for r in recs.values())}
    if status is not None:
        want["status"] = status
    try:
        have = json.loads(rqlib.read_text(marker))
    except ValueError:
        have = {}
    if {k: have.get(k) for k in want} != want:
        raise WorldsError(f"{wid}: {marker} does not describe its archive ({ {k: have.get(k) for k in want} })")
    for r in recs.values():
        s = os.stat(r["path"]) if os.path.isfile(r["path"]) else None
        if s is None or s.st_size != r["bytes"] or s.st_mode & 0o777 != 0o444 \
                or rqlib.sha256_file(r["path"]) != r["sha256"]:
            raise WorldsError(f"{wid}: the finalized archive's {os.path.basename(r['path'])} is missing, "
                              "damaged or writable")
    return True


def finalize_archive(root, wid, archive_root, status, log=lambda m: None, audited=False):
    """Audit and finalize a terminal world's archive (idempotent: it also completes or checks an
    earlier, interrupted finalization): every record's file present, its bytes (repaired from a
    verified local copy if need be) and 0444; the FINALIZED marker (world, status, frames)
    published atomically and 0444; the directory 0555; both fsync'd. An existing marker is checked
    against the archive and every indexed object is rehashed (nothing inside a finalized directory
    is ever replaced: damage there is an error)."""
    ad = adir(archive_root, wid)
    mkdirs_durable(ad)
    recs = archive_records(root, wid)
    want = {"world": wid, "status": status, "frames": sorted(r["frame"] for r in recs.values())}
    marker = os.path.join(ad, "FINALIZED")
    if os.path.isfile(marker):
        if not audited:                       # (audited: by the caller, just before)
            audit_archive(root, wid, archive_root, status)
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


def verified_records(root, wid, st, treatment, base=0):
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
            memo[name] = s["start_frame"] == base or bool(
                ra and ra["frame"] == s["start_frame"] and (ra["segment"], ra["frame"]) in good
                and good[(ra["segment"], ra["frame"])]["sha256"] == ra["sha256"] and chained(ra["segment"]))
        return memo[name]
    return {k: r for k, r in good.items() if chained(k[0])}


def _seg_index(name):
    return int(name[3:])


def resume_point(root, wid, st, treatment, good=None, base=0, origin=None):
    """-> (frame, checkpoint path, acceptance record) the next segment starts from: the latest
    verified record with a good copy of its checkpoint; (0, None, None) for the founder seed, (base,
    origin, None) for a fork branch's origin."""
    good = verified_records(root, wid, st, treatment, base) if good is None else good
    arecs = archive_records(root, wid)
    for (name, f), r in sorted(good.items(), key=lambda kv: (kv[0][1], _seg_index(kv[0][0])), reverse=True):
        p = good_copy(root, wid, f, r["sha256"], arecs)
        if p:
            return f, p, r
    return base, origin, None


def verified_chain(st, good, base=0):
    """The records of the chain that ends at the latest verified record: each segment's records up
    to the frame the next segment resumed from (the last one's up to its end)."""
    if not good:
        return []
    end = max(good.values(), key=lambda r: (r["frame"], _seg_index(r["segment"])))
    segs = {s["name"]: s for s in st["segments"]}
    out, seg, upto = [], end["segment"], end["frame"]
    while True:
        out += [r for (sg, f), r in good.items() if sg == seg and f <= upto]
        s = segs[seg]
        if s["start_frame"] == base:
            return sorted(out, key=lambda r: r["frame"])
        ra = s["resumed_accept"]
        seg, upto = ra["segment"], ra["frame"]


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
    """{guild: (the earliest frame at which it is 0 in any segment's main CSV, that segment, the
    byte count of the CSV prefix through the row)}."""
    out = {}
    for s in st["segments"]:
        p = os.path.join(wdir(root, wid), s["name"], "run.csv")
        if not os.path.isfile(p):
            continue
        raw = rqlib.read_bytes(p)
        lines = raw[: raw.rfind(b"\n") + 1].split(b"\n")[:-1]
        if not lines:
            continue
        hdr = next(csv.reader([lines[0].decode("utf-8")]))
        pos = len(lines[0]) + 1
        found = {}
        for ln in lines[1:]:
            pos += len(ln) + 1
            if not ln:
                continue
            r = next(csv.reader([ln.decode("utf-8")]))
            for guild, col in GUILDS:
                if (guild == "predators" and treatment == "A") or col not in hdr or guild in found:
                    continue
                if int(float(r[hdr.index(col)])) == 0:
                    found[guild] = (int(r[0]), s["name"], pos)
        for g, v in found.items():
            if g not in out or v[0] < out[g][0]:
                out[g] = v
    return out


# ================================================================== engine
def segment_args(world, sched, seg, start, ckpt_path=None, reseed=None):
    args = ["--no-render", "--headless", str(total_steps(world, sched) - start), "--log-every", str(sched["log_every"]),
            "--flush-every", "1", "--checkpoint-every", str(sched["checkpoint_every"]),
            "--save-checkpoint", "ckpt/end.json", "--csv", f"{seg}/run.csv", "--wiring-log"]
    if world["predator_log"]:
        args.append("--predator-log")
    if ckpt_path is None:
        return world["config_args"] + args
    if reseed is not None:      # (a fork branch's root segment only: technical resumes never reseed)
        return ["--load-checkpoint", ckpt_path, "--reseed-after-load", str(int(reseed))] + args
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
    mkdirs_durable(bdir)
    pinned = os.path.join(bdir, "evo_boids")
    want = None
    if binary is not None:
        want = rqlib.sha256_file(binary)
        if not os.path.exists(pinned):
            tmp = pinned + ".tmp"
            shutil.copy2(binary, tmp)
            rqlib.fsync_file(tmp)
            os.replace(tmp, pinned)
            rqlib.fsync_dir(bdir)
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
        self.T = self.sched["total_steps"]       # (a history's; a fork branch has its own: self.Tw)
        self.ce = self.sched["checkpoint_every"]
        restart_records(root, repair=True)
        self.worlds = effective_worlds(root, reg)  # (each at its attempt: the burn-in rule's reserved seeds)
        self.burn_in = int(reg.get("burn_in") or 0) if reg.get("seed_scheme") == SEED_SCHEME else 0
        self.max_restarts = int(reg.get("max_restarts") or 0)
        self.avail_p = os.path.join(root, "availability.jsonl")
        self.running = {}     # wid -> (Popen, job name, "segment" | "verify")
        self.tails = {}       # wid -> Tail of the running segment's main CSV
        self.last_frame = {}  # wid -> the last main-CSV frame seen
        self.extinct = {}     # wid -> the reason we stopped it
        self.seen = {}        # (wid, frame) -> (mtime_ns, size) of a local checkpoint already archived / compared
        self.verified = {}    # archived path -> (mtime_ns, size) once its bytes were verified
        self.start_cps = {}   # (wid, segment) -> the checkpoint the segment started from
        self.warned = set()
        self.zeros = {}       # wid -> {guild: first-zero frame} (the minimum over the supported records)
        self.chain = {}       # wid -> frames of the currently verified acceptance chain (pruning may use)
        self.chain_active = {}  # wid -> the active segment's last accepted frame (or its start)
        self.hold = {}          # wid -> a frame it stops at for now ("held": forks.py, the pilot's first horizon)
        self.ineligible = None  # wid -> why it may no longer run (None: it may): forks.py's origin re-check,
        #                         asked before EVERY segment (a resume, a retry, a replay)

    # ---------------------------------------------------------------- per world
    def base(self, wid):
        return base_frame(self.worlds[wid])

    def Tw(self, wid):
        return total_steps(self.worlds[wid], self.sched)

    def Teff(self, wid):
        """Where the world's engines stop now: its end, or an earlier hold."""
        return min(self.Tw(wid), self.hold.get(wid, self.Tw(wid)))

    def origin_path(self, wid):
        """A fork branch's frozen origin checkpoint (None for a history), VERIFIED against its durable
        digest at every use (a root replay, the lineage counters' start, any resume decision): a
        missing file or changed bytes fail closed (WorldsError)."""
        o = self.worlds[wid].get("origin")
        if not o:
            return None
        p = o.get("local")
        if not p or not o.get("sha256"):
            raise WorldsError(f"{wid}: its origin was never frozen")
        if not os.path.isfile(p) or rqlib.sha256_file(p) != o["sha256"]:
            raise WorldsError(f"{wid}: its frozen origin {p} does not match its recorded digest {o['sha256'][:12]}")
        return p

    def good(self, wid, st):
        return verified_records(self.root, wid, st, self.worlds[wid]["treatment"], self.base(wid))

    def resume(self, wid, st, good=None):
        return resume_point(self.root, wid, st, self.worlds[wid]["treatment"], good, self.base(wid),
                            self.origin_path(wid))

    # ---------------------------------------------------------------- state
    def state(self, wid):
        return read_state(self.root, wid)

    def set_status(self, wid, status, **kw):
        st = self.state(wid)
        st["status"] = status
        st.update(kw)
        write_state(self.root, wid, st)
        return st

    def invalidate(self, wid, why):
        """A fork branch whose origin is no longer valid: it stops for good (its artifacts kept)."""
        st = self.state(wid)
        self.set_status(wid, "invalidated", end_reason=why, invalidated_from=st["status"])
        self.log(f"INVALIDATED {wid}: {why}")

    def end_world(self, wid, status, reason):
        if status == "extinct" and self.burn_in:
            zf = min((self.zeros.get(wid) or {}).values(), default=None)
            if zf is not None and zf < self.burn_in:
                if self.restart(wid, reason, zf):
                    return
                reason = f"{reason}; before the burn-in frame {self.burn_in}, its {self.max_restarts} restarts exhausted"
        self.set_status(wid, status, end_reason=reason)
        if status in ("done", "extinct"):
            try:
                finalize_archive(self.root, wid, self.archive_root, status, self.log)
            except (WorldsError, OSError) as e:
                self.set_status(wid, "failed", end_reason=f"finalizing its archive: {e}")
                self.log(f"FAILED {wid}: finalizing its archive: {e}")

    # ---------------------------------------------------------------- the burn-in rule
    def restart(self, wid, reason, zero_frame):
        """An extinction before the burn-in frame: record the restart, then move the failed attempt aside
        and start the world afresh from its slot's next reserved seed. -> False when exhausted."""
        w = self.worlds[wid]
        n = int(w.get("attempt", 0)) + 1
        if n > self.max_restarts:
            return False
        nxt = effective_world(self.reg, next(x for x in self.reg["worlds"] if x["id"] == wid), n)
        rec = {"schema": RESTART_SCHEMA, "world": wid, "uuid": w["uuid"], "treatment": w["treatment"],
               "block": w.get("block"), "slot": w.get("seed_slot"), "attempt": n, "failed_attempt": n - 1,
               "failed_seed": w["founder_seed"], "seed": nxt["founder_seed"], "zero_frame": zero_frame,
               "reason": reason, "burn_in": self.burn_in, "utc": rqlib.now_utc()}
        _append_durable(os.path.join(self.root, "restarts.jsonl"), rec)      # (the commitment point)
        self.complete_restart(wid, rec)
        self.log(f"BURN-IN: {wid} ({w['treatment']}) went extinct before frame {self.burn_in} ({reason}): restarted "
                 f"as attempt {n} from its slot's next reserved seed {nxt['founder_seed']}")
        return True

    def complete_restart(self, wid, rec):
        """The moves and the fresh start of a recorded restart (idempotent: a crash after the record is
        completed at the next start)."""
        n = int(rec["attempt"])
        src = wdir(self.root, wid)
        dst = os.path.join(self.root, "restarts", "worlds", f"{wid}.a{n - 1}")
        asrc = adir(self.archive_root, wid)
        adst = os.path.join(self.archive_root, "restarts", f"{wid}.a{n - 1}")
        if os.path.isdir(src) and attempt_of(self.root, wid) == n - 1:
            for a_, b_ in ((src, dst), (asrc, adst)):
                if not os.path.isdir(a_):
                    continue
                if os.path.exists(b_):
                    raise WorldsError(f"{wid}: restart {n}: {b_} already exists")
                mkdirs_durable(os.path.dirname(b_))
                os.rename(a_, b_)
                rqlib.fsync_dir(os.path.dirname(a_))
                rqlib.fsync_dir(os.path.dirname(b_))
        elif os.path.isdir(asrc) and not os.path.isdir(src) and attempt_of(self.root, wid) != n:
            if os.path.exists(adst):
                raise WorldsError(f"{wid}: restart {n}: {adst} already exists")
            mkdirs_durable(os.path.dirname(adst))
            os.rename(asrc, adst)
            rqlib.fsync_dir(os.path.dirname(asrc))
            rqlib.fsync_dir(os.path.dirname(adst))
        if attempt_of(self.root, wid) != n:
            if os.path.isdir(src):
                raise WorldsError(f"{wid}: restart {n}: {src} is neither attempt {n - 1} nor {n}")
            new = f"{src}.new"                          # (made whole, then renamed into place)
            shutil.rmtree(new, ignore_errors=True)
            mkdirs_durable(new)
            rqlib.write_durable(os.path.join(new, "attempt.json"), rqlib.canonical(
                {"schema": ATTEMPT_SCHEMA, "world": wid, "attempt": n, "seed": rec["seed"], "slot": rec.get("slot")}))
            os.rename(new, src)
            rqlib.fsync_dir(os.path.dirname(src))
            write_state(self.root, wid, {"schema": STATE_SCHEMA, "id": wid, "status": "pending", "failures": 0,
                                         "segments": [], "attempt": n})
        self.worlds[wid] = effective_world(self.reg, next(x for x in self.reg["worlds"] if x["id"] == wid), n)
        for cache in (self.zeros, self.extinct, self.chain, self.chain_active, self.tails, self.last_frame):
            cache.pop(wid, None)
        for k in [k for k in self.seen if k[0] == wid]:
            del self.seen[k]
        for k in [k for k in self.start_cps if k[0] == wid]:
            del self.start_cps[k]
        ad = adir(self.archive_root, wid) + os.sep
        for k in [k for k in self.verified if str(k).startswith(ad)]:
            del self.verified[k]

    def spawn_f1(self, wid):
        """A restarted attempt's F1, by the pinned engine (the f1 command's run), as a supervisor job."""
        w = self.worlds[wid]
        d = os.path.join(wdir(self.root, wid), "f1")
        shutil.rmtree(d, ignore_errors=True)
        mkdirs_durable(d)
        args = segment_args(w, self.sched, "f1", 0)
        args[args.index("--headless") + 1] = "1"
        args[args.index("--save-checkpoint") + 1] = "f1/F1.json"
        args[args.index("--csv") + 1] = "f1/f1.csv"
        self.set_status(wid, "running")
        self.running[wid] = (self._popen(args, wdir(self.root, wid), d), "f1", "f1")
        self.log(f"{wid}: attempt {w.get('attempt', 0)}: its F1 by the pinned engine (seed {w['founder_seed']})")

    def reap_f1(self, wid, rc):
        w = self.worlds[wid]
        p = os.path.join(wdir(self.root, wid), "f1", "F1.json")
        try:
            if rc != 0 or not os.path.isfile(p):
                raise WorldsError(f"the F1 replay exited {rc}")
            probs = verify_config(ckpt.load(p), w["flags"])
            if probs:
                raise WorldsError(f"F1's configuration differs from the registry ({'; '.join(probs)})")
            archive_one(self.root, wid, self.archive_root, 1, p, self.log, extra={"binary_sha256": self.exe_sha})
        except (WorldsError, ckpt.CheckpointError, OSError, ValueError) as e:
            self.end_world(wid, "failed", f"attempt {w.get('attempt', 0)}: its F1: {e}")
            self.log(f"FAILED {wid}: {self.state(wid)['end_reason']}")
            return
        self.set_status(wid, "pending")

    def warn_once(self, key, msg):
        if key not in self.warned:
            self.warned.add(key)
            self.log(msg)

    # ---------------------------------------------------------------- biology
    def note_zero(self, wid, guild, frame, seg, csv_bytes, recovered=False):
        """Record a guild's first zero, bound to its evidence: the segment's main-CSV prefix through
        the zero row is fsync'd, then the record (its byte count and sha256) is appended durably. Only
        a record whose evidence still holds counts (zero_supported: a stop is irreversible only then)."""
        z = self.zeros.setdefault(wid, {})
        if guild in z and z[guild] <= frame:
            return
        w = self.worlds[wid]
        p = os.path.join(wdir(self.root, wid), seg, "run.csv")
        rqlib.fsync_file(p)
        with open(p, "rb") as f:
            data = f.read(csv_bytes)
        arecs = archive_records(self.root, wid)
        rec = {"schema": AVAIL_SCHEMA, "world": wid, "uuid": w["uuid"], "treatment": w["treatment"], "guild": guild,
               "first_zero_frame": frame, "detected_utc": rqlib.now_utc(), "segment": seg,
               "csv_bytes": len(data), "csv_sha256": rqlib.sha256_bytes(data),
               "archived_frames_before": sorted(x["frame"] for x in arecs.values() if x["frame"] < frame)}
        if w.get("attempt"):
            rec["attempt"] = w["attempt"]
        if recovered:
            rec.update(recovered=True, supersedes=z.get(guild))
        _append_durable(self.avail_p, rec)
        z[guild] = frame
        self.log(f"BIOLOGICAL: {wid} ({w['treatment']}): the {guild} reached 0 at frame {frame} (availability ledger"
                 + (", recovered from an earlier segment" if recovered else "") + ")")

    def recover_zeros(self, wid):
        for guild, (f, seg, n) in scan_zeros(self.root, wid, self.state(wid), self.worlds[wid]["treatment"]).items():
            self.note_zero(wid, guild, f, seg, n, recovered=True)

    def zero_reason(self, wid):
        z = self.zeros.get(wid) or {}
        return "; ".join(f"the {g} reached 0 at frame {f}" for g, f in sorted(z.items())) or None

    def watch(self, wid):
        """New main-CSV rows of a running segment: the frame reached; a guild at zero -> (guild, frame)."""
        t = self.tails[wid]
        seg = self.running[wid][1] if wid in self.running else self.state(wid)["segments"][-1]["name"]
        found = None
        for r, end in zip(t.lines(), t.ends):
            fr = int(r[0])
            self.last_frame[wid] = fr
            row = dict(zip(t.header, r))
            for guild, col in GUILDS:
                if guild == "predators" and self.worlds[wid]["treatment"] == "A":
                    continue
                if int(float(row[col])) == 0:
                    self.note_zero(wid, guild, fr, seg, end)
                    found = found or (guild, fr)
        return found

    # ---------------------------------------------------------------- archive and acceptance
    def completed(self, wid, f):
        """Whether checkpoint f's last writer finished it: the last segment started before f and its
        main CSV has a row past f (the engine saves a checkpoint before it steps on)."""
        st = self.state(wid)
        if not st["segments"] or st["segments"][-1]["start_frame"] >= f:
            return False
        if wid in self.running:
            return self.last_frame.get(wid, -1) > f
        row = _last_row(os.path.join(wdir(self.root, wid), st["segments"][-1]["name"], "run.csv"))[1]
        try:
            return row is not None and int(row[0]) > f
        except (ValueError, IndexError):
            return False

    def first_zero(self, wid):
        z = self.zeros.get(wid) or {}
        return min(z.values()) if z else None

    def archive_ckpt(self, wid, f, path):
        """archive_one under the COMMITMENT rule -> (record, checkpoint), or None (not usable: it was
        quarantined, or it is past the zero of a world whose archive is finalized).
        - uncommitted and invalid for any reason: quarantined, the world replays; but if the replay
          regenerated an invalid file at a frame quarantined before (its writer finished it), the
          world fails closed (the engine does not reproduce a valid checkpoint there);
        - committed with other bytes: fails closed if its last writer finished it (a deterministic
          regeneration must reproduce the committed bytes); else (a rewrite cut short, or damage to a
          copy no running segment writes) the local copy is restored from the verified archived
          copy, the bad bytes kept in quarantine; no verified archived copy: fails closed."""
        if self.past_finalized_zero(wid, f):
            self.warn_once((wid, f, "pastzero"), f"{wid}: end.{f} lies past its zero and its archive is finalized: "
                                                 "not archived (not part of its history)")
            return None
        try:
            return archive_one(self.root, wid, self.archive_root, f, path, self.log, verified=self.verified)
        except TornCheckpoint as e:
            if self.completed(wid, f) and any(q.get("frame") == f and not q.get("committed") for q in
                                              read_jsonl(os.path.join(wdir(self.root, wid), "quarantine.jsonl"))):
                raise WorldsError(f"{wid}: the replay regenerated an invalid checkpoint of frame {f} (an earlier one "
                                  f"was quarantined): {e}")
            self.quarantine(wid, f, path, str(e))
            return None
        except CommittedMismatch as e:
            if self.completed(wid, f):
                raise WorldsError(f"{e}, and its writer finished it: the history is not deterministic")
            rec = e.rec
            try:
                ok = os.path.isfile(rec["path"]) and rqlib.sha256_file(rec["path"]) == rec["sha256"]
            except OSError:
                ok = False
            if not ok:
                raise WorldsError(f"{e}, and its archived copy does not verify either")
            self.quarantine(wid, f, path, f"{e}; restored from the archived copy", committed=True)
            rqlib.write_durable(path, rqlib.read_bytes(rec["path"]))
            self.log(f"{wid}: RESTORED {os.path.basename(path)} from its verified archived copy")
            return archive_one(self.root, wid, self.archive_root, f, path, self.log, verified=self.verified)

    def past_finalized_zero(self, wid, f):
        """An uncommitted checkpoint past the first zero of a world whose archive is finalized (a
        reopened world's replay ran on past the zero): not part of its history, nothing to publish."""
        fz = self.first_zero(wid)
        return fz is not None and f > fz and label_of(f) not in archive_records(self.root, wid) \
            and os.path.isfile(os.path.join(adir(self.archive_root, wid), "FINALIZED"))

    def quarantine(self, wid, frame, path, reason, committed=False):
        qd = os.path.join(wdir(self.root, wid), "ckpt", "quarantine")
        mkdirs_durable(qd)
        n = 1
        while os.path.exists(os.path.join(qd, f"{os.path.basename(path)}.{n}")):
            n += 1
        dst = os.path.join(qd, f"{os.path.basename(path)}.{n}")
        raw = rqlib.read_bytes(path)
        rqlib.fsync_file(path)                # the evidence's bytes, then both directory entries,
        os.rename(path, dst)                  # before the quarantine record that points at it
        rqlib.fsync_file(dst)
        rqlib.fsync_dir(qd)
        rqlib.fsync_dir(os.path.dirname(path))
        _append_durable(os.path.join(wdir(self.root, wid), "quarantine.jsonl"), {
            "schema": QUARANTINE_SCHEMA, "world": wid, "frame": frame, "from": path, "to": dst, "bytes": len(raw),
            "sha256": rqlib.sha256_bytes(raw), "committed": committed, "reason": reason, "utc": rqlib.now_utc()})
        self.seen.pop((wid, frame), None)
        self.log(f"{wid}: QUARANTINED {os.path.basename(path)} ({reason}); not used to resume")

    def archive_pass(self, wid, alive):
        """Archive every complete local checkpoint under the commitment rule (archive_ckpt: a
        committed one is compared with its record, an invalid uncommitted one quarantined); with
        --prune-local drop old local copies of accepted checkpoints."""
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
            if self.archive_ckpt(wid, f, loc[f]) is not None or os.path.exists(loc[f]):
                self.seen[(wid, f)] = key
        if self.a.prune_local and wid in self.chain:
            # only checkpoints of the currently verified chain, at or before the active segment's last
            # acceptance (a replay still needs every later one), but its two latest
            chain = sorted(self.chain[wid])
            done_upto = self.chain_active.get(wid, -1)
            keep = set(chain[-2:])
            arecs = archive_records(self.root, wid)
            for f, p in local_ckpts(self.root, wid).items():
                r = arecs.get(label_of(f))
                if f in self.chain[wid] and f <= done_upto and f not in keep and r \
                        and rqlib.sha256_file(r["path"]) == r["sha256"] and rqlib.sha256_file(p) == r["sha256"]:
                    os.remove(p)
                    self.seen.pop((wid, f), None)

    def start_checkpoint(self, wid, seg):
        if seg["start_frame"] == 0:
            return None
        k = (wid, seg["name"])
        if k not in self.start_cps and seg["start_frame"] == self.base(wid):    # a branch's origin
            self.start_cps[k] = ckpt.load(self.origin_path(wid))
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
        while last + self.ce <= self.Teff(wid):
            F = last + self.ce
            p = local_ckpts(self.root, wid).get(F)
            if p is None or (alive and self.last_frame.get(wid, -1) <= F):
                return
            got = self.archive_ckpt(wid, F, p)
            if got is None:
                return
            arec, cp = got
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
            if prev is None and seg.get("resumed_accept"):     # a resumed segment's logs: the same headers
                ra = seg["resumed_accept"]
                base = next((r for r in accept_records(self.root, wid)
                             if r["segment"] == ra["segment"] and r["frame"] == ra["frame"]), None)
                bad = [n for n in logs if base and base["logs"].get(n, {}).get("header_sha256")
                       not in (None, logs[n]["header_sha256"])]
                if bad:
                    self.warn_once((wid, name, "header"), f"{wid}: {name}'s {bad} headers differ from the "
                                                          f"segment it resumed: not accepted")
                    return
            for lname in logs:
                rqlib.fsync_file(os.path.join(d, lname))
            if prev is None:                  # the logs' directory entries, before their first acceptance
                rqlib.fsync_dir(d)
            rec = {"schema": ACCEPT_SCHEMA, "world": wid, "segment": name, "start_frame": s0, "frame": F,
                   "label": label_of(F), "sha256": arec["sha256"], "binary_sha256": self.exe_sha, "logs": logs,
                   "utc": rqlib.now_utc()}
            _append_durable(os.path.join(wdir(self.root, wid), "accept.jsonl"), rec)
            self.chain.setdefault(wid, set()).add(F)
            self.chain_active[wid] = F
            prev, last = rec, F

    def extinct_problems(self, wid, st, good=None):
        """Why an extinction stop is not evidenced (None if it is): it needs a zero whose evidence
        holds, and the latest acceptance record at or before the first zero must verify (the
        accepted logs through the zero intact, back to the founder seed)."""
        fz = self.first_zero(wid)
        if fz is None:
            return "no zero whose evidence still holds"
        good = self.good(wid, st) if good is None else good
        names = {s["name"] for s in st["segments"]}
        recs = [r for r in accept_records(self.root, wid) if r["segment"] in names and r["frame"] <= fz]
        if recs:
            last = max(recs, key=lambda r: (r["frame"], _seg_index(r["segment"])))
            if (last["segment"], last["frame"]) not in good:
                return f"its acceptance record of frame {last['frame']} ({last['segment']}) no longer verifies"
        return None

    def terminal_problems(self, wid, st):
        """Why a done / extinct world's status no longer stands (None if it does): a done world's
        verified acceptance chain must reach the final frame; an extinct world's stop must still be
        evidenced (extinct_problems). (Its finalized archive was audited before: audit_archive.)"""
        good = self.good(wid, st)
        frame = self.resume(wid, st, good)[0]
        if st["status"] == "done" and frame != self.Tw(wid):
            return f"its verified logs end at frame {frame}, not {self.Tw(wid)}"
        if st["status"] == "extinct":
            return self.extinct_problems(wid, st, good)
        return None

    def refresh_chain(self, wid, st=None):
        """The currently verified chain's frames, and how far the active (last) segment has accepted
        (its start if it accepted nothing, provided it resumed from the chain; else nothing to prune)."""
        st = st or self.state(wid)
        good = self.good(wid, st)
        recs = verified_chain(st, good, self.base(wid))
        self.chain[wid] = {r["frame"] for r in recs}
        last = st["segments"][-1] if st["segments"] else None
        mine = [r["frame"] for r in recs if last and r["segment"] == last["name"]]
        ra = (last or {}).get("resumed_accept")
        if mine:
            self.chain_active[wid] = max(mine)
        elif last and (last["start_frame"] == self.base(wid) or (ra and (ra["segment"], ra["frame"]) in good)):
            self.chain_active[wid] = last["start_frame"]
        else:
            self.chain_active[wid] = -1

    # ---------------------------------------------------------------- what next
    def next_action(self, wid):
        """-> ("extinct" | "done" | "held" | "invalidated", reason) | ("verify" | "f1", None)
        | ("segment", (start, checkpoint path, record)).
        The extinction shortcut applies only while the stop is evidenced (extinct_problems); else the
        world replays from its latest verified record, through the zero, which stops it again (and
        reap_segment fails it if the replay did not repair the accepted logs)."""
        st = self.state(wid)
        why = self.ineligible(wid) if self.ineligible else None
        if why:
            return "invalidated", why
        if self.worlds[wid].get("attempt") and not f1_bound(self.root, wid, self.exe_sha):
            return "f1", None                            # (a restarted attempt: its F1 first)
        if self.a.on_extinction == "stop" and self.zero_reason(wid):
            why = self.extinct_problems(wid, st)
            if not why:
                return "extinct", self.zero_reason(wid)
            self.warn_once((wid, "unevidenced"), f"{wid}: at its zero, but {why}: replaying through the zero to "
                                                 "repair its accepted logs")
        frame, path, rec = self.resume(wid, st)
        if frame >= self.Tw(wid):
            return "done", f"{self.Tw(wid)} steps (its final checkpoint and logs accepted)"
        if frame >= self.Teff(wid):
            return "held", f"held at frame {self.Teff(wid)} (its hold; it resumes when the hold is lifted)"
        if frame > 0 and not self.base(wid) and not f1_verified(self.root, wid, self.exe_sha, self.ce):
            return "verify", None
        return "segment", (frame, path, rec)

    def spawn_segment(self, wid, start, cpath, rec):
        w = self.worlds[wid]
        st = self.state(wid)
        seg = f"seg{len(st['segments']):03d}"
        d = wdir(self.root, wid)
        if os.path.exists(os.path.join(d, seg)):      # (a segment directory the state never recorded)
            os.rename(os.path.join(d, seg), os.path.join(d, f"{seg}.orphan.{time.time_ns()}"))
        mkdirs_durable(os.path.join(d, seg))
        mkdirs_durable(os.path.join(d, "ckpt"))
        if cpath and os.path.abspath(cpath).startswith(d + os.sep):
            cpath = os.path.relpath(os.path.abspath(cpath), d)
        b = self.base(wid)
        args = segment_args(dict(w, total_steps=self.Teff(wid)), self.sched, seg, start, cpath,
                            reseed=w["origin"]["seed"] if b and start == b and rec is None else None)
        st["segments"].append({"name": seg, "start_frame": start, "resumed_from": cpath,
                               "resumed_accept": ({"segment": rec["segment"], "frame": rec["frame"],
                                                   "sha256": rec["sha256"]} if rec else None),
                               "started_utc": rqlib.now_utc(), "args": args})
        st["status"] = "running"
        write_state(self.root, wid, st)
        self.refresh_chain(wid, st)
        p = self._popen(args, d, os.path.join(d, seg))
        self.running[wid] = (p, seg, "segment")
        self.tails[wid] = Tail(os.path.join(d, seg, "run.csv"))
        self.last_frame[wid] = start
        self.log(f"{wid} ({w['treatment']}): {seg} from frame {start}" + (f" ({cpath})" if cpath else " (founder seed)"))

    def spawn_verify(self, wid):
        recs = archive_records(self.root, wid)
        d = os.path.join(wdir(self.root, wid), "f1verify")
        shutil.rmtree(d, ignore_errors=True)
        mkdirs_durable(d)
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
            reason = self.extinct.pop(wid)
            why = self.extinct_problems(wid, self.state(wid))
            if why:                           # (a replay through the zero that did not repair its logs)
                self.end_world(wid, "failed", f"stopped at its zero ({reason}), but {why}: its accepted logs "
                                              "through the zero could not be repaired")
                self.log(f"FAILED {wid}: {self.state(wid)['end_reason']}")
                return
            self.end_world(wid, "extinct", reason)
            st = self.state(wid)
            if st["status"] == "extinct":                # (else: restarted by the burn-in rule)
                self.log(f"{wid}: ended as extinct ({st['end_reason']})")
            return
        try:
            nxt = self.resume(wid, self.state(wid))[0]
        except (WorldsError, OSError) as e:
            self.end_world(wid, "failed", str(e))
            self.log(f"FAILED {wid}: {e}")
            return
        if nxt >= self.Tw(wid):
            self.end_world(wid, "done", f"{self.Tw(wid)} steps")
            self.log(f"{wid}: history complete ({self.Tw(wid)} steps, every log accepted through the final frame)")
            return
        if nxt >= self.Teff(wid):
            self.set_status(wid, "held", end_reason=f"held at frame {self.Teff(wid)}")
            self.log(f"{wid}: held at frame {self.Teff(wid)} (accepted through it; not finalized)")
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
        for wid in self.worlds:                              # (a restart recorded, its moves interrupted)
            led = restart_records(self.root, wid)
            if led and attempt_of(self.root, wid) != max(int(r["attempt"]) for r in led):
                self.complete_restart(wid, max(led, key=lambda r: int(r["attempt"])))
                self.log(f"{wid}: its recorded restart (attempt {self.worlds[wid]['attempt']}) completed")
        for e in read_jsonl(self.avail_p, repair=True):     # (only records whose evidence still holds)
            if e["world"] in self.worlds and zero_supported(self.root, e):
                z = self.zeros.setdefault(e["world"], {})
                z[e["guild"]] = min(z.get(e["guild"], e["first_zero_frame"]), e["first_zero_frame"])
        missing_f1 = []
        for wid, w in self.worlds.items():
            archive_records(self.root, wid, repair=True)
            accept_records(self.root, wid, repair=True)
            read_jsonl(os.path.join(wdir(self.root, wid), "quarantine.jsonl"), repair=True)
            st = self.state(wid)
            if st["status"] == "held" and self.Teff(wid) > (self.resume(wid, st)[0] if st["segments"] else 0):
                self.log(f"{wid}: its hold is lifted: it resumes (no reseed)")
                st["status"] = "interrupted"
                write_state(self.root, wid, st)
            if st["status"] == "running" or (st["status"] == "failed" and a.retry_failed):
                why = self.ineligible(wid) if self.ineligible else None
                if why:                                   # (never retried, never resumed)
                    self.invalidate(wid, why)
                    continue
                if st["status"] == "failed":
                    self.log(f"{wid}: retrying a failed world (--retry-failed; it was: {st.get('end_reason')})")
                    st["failures"] = 0
                st["status"] = "interrupted"
                write_state(self.root, wid, st)
            audited = False
            if st["status"] in ("done", "extinct", "pending", "interrupted"):
                # a finalized archive is audited in full (every object rehashed) before anything else,
                # in particular before a reopened world's recovery starts
                try:
                    audited = audit_archive(self.root, wid, self.archive_root,
                                            st["status"] if st["status"] in ("done", "extinct") else None)
                except (WorldsError, OSError) as e:
                    self.set_status(wid, "failed", end_reason=f"its finalized archive: {e}")
                    self.log(f"FAILED {wid}: its finalized archive: {e}")
                    continue
            if st["status"] in ("done", "extinct"):
                # a terminal world keeps its status only while its evidence holds: its audited archive,
                # the acceptance chain through its endpoint, its earliest zero
                try:
                    self.recover_zeros(wid)
                    why = self.terminal_problems(wid, st)
                    if not why:
                        finalize_archive(self.root, wid, self.archive_root, st["status"], self.log, audited)
                        continue
                except (WorldsError, OSError) as e:
                    self.set_status(wid, "failed", end_reason=f"its terminal evidence: {e}")
                    self.log(f"FAILED {wid}: its terminal evidence: {e}")
                    continue
                self.log(f"{wid}: REOPENED ({st['status']}, but {why}): recovering from its verified evidence")
                st = self.set_status(wid, "interrupted", reopened=why, failures=0)
            if st["status"] not in ("pending", "interrupted"):
                continue
            if not w.get("origin") and not w.get("attempt") and not f1_bound(self.root, wid, self.exe_sha):
                missing_f1.append(wid)
            if st["segments"]:
                try:
                    self.archive_pass(wid, alive=False)
                    self.accept_pass(wid, alive=False)
                    self.recover_zeros(wid)
                    self.refresh_chain(wid)
                    kind, info = self.next_action(wid)
                except (WorldsError, ckpt.CheckpointError, OSError, ValueError) as e:
                    self.end_world(wid, "failed", str(e))
                    self.log(f"FAILED {wid}: {e}")
                    continue
                if kind in ("done", "extinct"):
                    self.end_world(wid, kind, info)
                    if self.state(wid)["status"] == kind:
                        self.log(f"{wid}: already at its end ({kind}: {info}); finalized without another segment")
                elif kind == "held":
                    self.set_status(wid, "held", end_reason=info)
                elif kind == "invalidated":
                    self.invalidate(wid, info)
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
                elif kind == "f1":
                    self.reap_f1(wid, rc)
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
                        if self.state(wid)["status"] == kind:
                            log(f"{wid}: at its end ({kind}: {info})")
                    elif kind == "held":
                        self.set_status(wid, "held", end_reason=info)
                        log(f"{wid}: {info}")
                    elif kind == "invalidated":
                        self.invalidate(wid, info)
                    elif kind == "verify":
                        self.spawn_verify(wid)
                    elif kind == "f1":
                        self.spawn_f1(wid)
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
    eff = effective_worlds(root, reg)
    for w in reg["worlds"]:
        if a.world and w["id"] not in a.world:
            continue
        w = eff[w["id"]]                     # (a restarted world at its attempt)
        recs = archive_records(root, w["id"], repair=True)
        if "F1" in recs:
            if recs["F1"].get("binary_sha256") != exe_sha:
                log(f"{w['id']}: its F1 was archived by another engine")
                rc = 1
            continue
        d = os.path.join(wdir(root, w["id"]), "f1")
        if os.path.isdir(d):
            shutil.rmtree(d)
        mkdirs_durable(d)                    # (the worlds/, world and f1 directories, with their ancestors)
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
        mkdirs_durable(d)
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
    T, L = total_steps(w, sched), sched["log_every"]
    base = base_frame(w)
    st = read_state(root, wid)
    if st["status"] not in ("done", "extinct") and not partial:
        raise WorldsError(f"{wid} is {st['status']}, not done or extinct: --partial for a partial stitch")
    good = verified_records(root, wid, st, w["treatment"], base)
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
        if s["start_frame"] == base:
            break
        ra = s["resumed_accept"]
        cur = good[(ra["segment"], ra["frame"])]
    chain.reverse()
    d = wdir(root, wid)
    out = os.path.join(d, "stitched")
    mkdirs_durable(out)
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
            if kind == "events" and s["start_frame"] > base:     # (a branch's root keeps the origin's L rows)
                rows = [r for r in rows if r[1] != "L"]
            if kind == "steps":
                rows = [[str(int(r[0]) + s["start_frame"])] + r[1:] for r in rows]
            if name == "run.csv" and s["start_frame"] > 0 and rows:
                # the resumed segment's first row counts the loaded world's history in its interval columns
                ra = s["resumed_accept"]
                if s["start_frame"] == base:                    # a branch's root: its origin
                    src = (w.get("origin") or {}).get("local")
                    if not (src and os.path.isfile(src) and rqlib.sha256_file(src) == w["origin"]["sha256"]):
                        raise WorldsError(f"{wid}: its origin checkpoint is gone or changed")
                else:
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
        elif frames != list(range(base + L, endpoint + 1, L)):
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
        zeros = first_zeros(led, w["id"], root)
        st = read_state(root, w["id"])
        ws[w["id"]] = {"uuid": w["uuid"], "treatment": w["treatment"], "block": w["block"], "status": st["status"],
                       "attempt": attempt_of(root, w["id"]),
                       "pattern": os.path.join(ad, "end.{frame}.json"), "paths": {"F1": os.path.join(ad, "F1.json")},
                       # snapshots at or after a guild's first zero are not valid challengers (design §2.3)
                       "valid_before": min(zeros.values()) if zeros else None,
                       "archived": sorted(r["frame"] for r in archive_records(root, w["id"]).values())}
    return {"schema": "finfolk.redqueen.worldsblock/1", "registry_sha256": rqlib.sha256_file(
        os.path.join(root, "config", "worlds.json")), "times": times, "worlds": ws}


def burn_in_report(root, reg):
    """The burn-in rule's restarts and the early-establishment failure rate per treatment (restarts /
    attempts started = restarts + worlds)."""
    led = restart_records(root)
    per = {}
    for w in reg["worlds"]:
        p = per.setdefault(w["treatment"], {"worlds": 0, "restarts": 0})
        p["worlds"] += 1
    for r in led:
        per.setdefault(r["treatment"], {"worlds": 0, "restarts": 0})["restarts"] += 1
    for p in per.values():
        att = p["worlds"] + p["restarts"]
        p["attempts"] = att
        p["early_failure_rate"] = p["restarts"] / att if att else None
    return {"burn_in": reg.get("burn_in") if reg.get("seed_scheme") == SEED_SCHEME else None,
            "max_restarts": reg.get("max_restarts"), "restarts": led, "per_treatment": per}


def status(root):
    reg, sha = load_registry(root, allow_placeholder=True)
    out = {"root": root, "worlds": {}}
    try:
        out["archive_root"] = bind_root(root, sha, readonly=True)
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
                                  "last_row": last, "attempt": attempt_of(root, w["id"])}
    counts = {}
    for v in out["worlds"].values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    out["counts"] = counts
    out["burn_in"] = burn_in_report(root, reg)
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
    r.add_argument("--burn-in", type=int, default=BURN_IN, help="frames (0: no burn-in restarts)")
    r.add_argument("--max-restarts", type=int, default=MAX_RESTARTS)
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
                            "log_every": a.log_every}, a.allow_placeholder, a.c_founders, a.burn_in,
                           a.max_restarts)
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
            blk = design_block(root, reg, bind_root(root, sha, a.archive_root, readonly=True))
            rqlib.write_durable(a.out, rqlib.canonical(blk))
            return 0
        if a.cmd == "stitch":
            reg, sha = load_registry(root, a.allow_placeholder)
            bind_root(root, sha, a.archive_root, readonly=True)
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

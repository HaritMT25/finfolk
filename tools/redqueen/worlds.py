#!/usr/bin/env python3
"""worlds.py: register the Red Queen study's 64 evolutionary histories and run them (design v3 §2, §13;
Annex H AMENDMENTS D6 / D7).

    worlds.py register --arena config/arena.selected.json --namespace NS --out STUDY/config/worlds.json
                       [--blocks 8] [--layout 64 | --per-block C=4,A=2,B=2] [--c-founders 6] [--avoid FILE ...]
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
    worlds.py ecology --root STUDY --out ecology.json [--horizons F,F,...]
    worlds.py monitor --root STUDY --out monitor.json [--window 25000] [--step 5000] [--windows-out W.jsonl.gz]

THE REGISTRY (register; deterministic: the same inputs give the same bytes; an existing registry
is never replaced by other bytes: changed seeds, treatments or schedule need a new study root).
The registered allocation is FIXED (Annex H D7 rule 34): --layout 64, eight randomized blocks of 4C +
2A + 2B (64 worlds: 32 C, 16 A, 16 B); both A (both B) controls of a block keep A's (B's) definition and
neither is a technical replicate or another block. The default --per-block C=4,A=1,B=1 (48) and any
other count remain for tests and older registries only. Within each
block the treatment order is a seeded permutation (namespace, "block-order", block), so a world's id
does not reveal its treatment by position. Each world has an id (w01..), a UUID (uuid5 of the
namespace and id) and a SEED SLOT "b<block>:<treatment>:<k>" (k: its index among its block's
worlds of that treatment). SEED RESERVATIONS (seed scheme "slot/1"): every slot of up to 4C + 2A + 2B
per block (more if --per-block asks) reserves 1 + --max-restarts seeds, derived from (namespace,
"founder", "b<b>", treatment, "k<k>"[, "a<attempt>"]), unique and refused if they occur in any --avoid
file (integers, or any JSON / JSONL whose keys contain "seed": the archived plans and reservations of
other streams); a world's founder seed is its slot's first, so a slot keeps its seeds whatever the
allocation. Every --avoid file is recorded (path, sha256, seed count) in the registry.

THE PRODUCTION REGISTRATION (Annex H D6/D7 checklist item 6; the operator's step, after the builder
changes): --layout 64 --blocks 8 --c-founders 6 --total-steps 200000000 --checkpoint-every 1000000
--log-every 5000 --burn-in 5000000 --max-restarts 8 (576 reserved founder / restart seeds) under the
production namespace (finfolk-rq-production-2026-11-d6d7-v1), with --avoid naming BOTH arenas' pilot
seed reservations (arena #1's, sha256 fd538f03...; arena #2's, sha256 8293f579...) and every other
existing plan or reservation of the seed inventory: the validation run's reservations/seeds.json,
reservations/home_seeds_used.json, reservations/reserved_pilot_seeds.txt and config/seeds.json, and
validation_arena2's config/seeds.json. One --avoid per file (the option repeats); the registry
records each file's sha256, and the operator hashes the complete avoidance inventory with it.

THE BURN-IN RULE (USER DECISIONS 2, item 6; registries of seed scheme slot/1, --burn-in frames, 0
disables). A world (C, A or B) that goes extinct BEFORE the burn-in frame (5M) is not ended: it is
RESTARTED from its slot's next reserved seed. "Before 5M" means: the earliest EVIDENCED SAMPLED zero of
any guild in the current attempt's main CSVs (a validated row: the header's width, integral counts,
the segment's frame sequence) is at a frame < burn-in. The CSV is sampled every log_every frames, so a
true extinction at frame 4,999,999 is first sampled at 5,000,000 (log_every 5000) and is NOT
restarted: the boundary is the first sampled zero, not the exact extinction step. The rule applies
under either --on-extinction (an early zero always stops and restarts; continuation applies after the
burn-in). Before the restart is committed the failed attempt's evidence is made durable (every file
and directory of the attempt and of its archive fsync'd, bottom up); the restart is then recorded in
STUDY/restarts.jsonl (world, slot, the attempt, the failed seed and the new one, the zero), a
relocation manifest is written into the attempt, the attempt is moved to STUDY/restarts/worlds/
<id>.a<n> and its (unfinalized) archive to ARCHIVE/restarts/<id>.a<n> (attempt_archive_records and
audit_attempt resolve a retained attempt's index to its own relocated bytes), and the world starts
afresh (attempt.json: its attempt and seed; state pending): its F1 is made by the supervisor itself
with the pinned engine, then the usual history. A crash between the record and the moves is completed
before anything is written by EVERY writing entry point (launch, f1, verify-f1: reconcile_restarts);
availability records carry their attempt and count only for the current one. After --max-restarts
restarts the world ends extinct (the restarts exhausted). Extinction at or after the burn-in frame is
data. status reports every restart and, per treatment, the attempts started, the early failures (the
restarts and the exhausted final attempts), the established attempts, the pending and unresolved ones,
and the early-establishment failure rate (early failures / resolved attempts). burn_in_decided tells
the fork registry whether a root's current attempt can still be replaced (forks.py admits origins
only from a decided attempt and binds each frozen origin to its root's attempt).

ALLOCATION. --per-block takes one allocation (every block) or a ';'-separated list cycled over the
blocks; --layout names one: 64 = 8 x (4C+2A+2B), the registered allocation (D7 rule 34). The 48 (8 x
(4C+1A+1B)) and 56 (4C+2A+1B and 4C+1A+2B alternating) layouts belonged to USER DECISIONS 2 item 5's
rule of choosing the allocation from an estimate, WITHDRAWN by D7 rule 35 before any estimate existed;
they remain only so older registries and tests keep their bytes.

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

ECOLOGY (ecology; Annex H D6 rules 22-26; READ-ONLY: no lock, nothing written but --out). Every
attempt of every registered slot, DISCOVERED read-only from the restart ledger, the retained
(relocated) directories STUDY/restarts/worlds/<id>.a<k> and the current attempt.json (its bytes
bound), so an interrupted restart never loses a recorded failure; each with its (slot, attempt,
seed) identity and its own frame-zero origin (time is never concatenated across attempts). An
attempt's EVIDENCE-BOUND sequence follows evidence.py's rules (the one implementation val_block.py
shares): the chain is the NEWEST line of descent of its segments (a rollback supersedes a segment
wholly; each later chain segment must resume its predecessor's acceptance record at its start); each
chain segment's main-CSV bytes are those its acceptance records cover (re-verified part by part, a
part that no longer verifies ending the coverage there, the earlier parts kept); only the newest
segment may extend past its last acceptance, by its own availability-ledger prefix that binds a zero
and extends the covered bytes (a continuation is never chosen by its length); rows are complete
records of the header's width, integral counts, on the log_every sequence, the evidence stopping at
the first bad row with the earlier rows kept (technical censoring at the last verified
observation); the FIRST sampled zero of either guild ends the observation (later overshoot rows
never resolve the other guild: a prey-terminal stop stays unresolved for the predators); a predator
refill above the founders' baseline (predator_reseeds_cum > 0) ends it at the sample before it (a
protocol-integrity event: no later row establishes natural coexistence; such a history is never in
Q200). Every other ledger entry is listed as unsupported, with why, and superseded segments are
listed. Per attempt: each guild's FIRST EVIDENCED SAMPLED ZERO and the sample before it (the
extinction lies in between; A's predators are structural), a joint event when both guilds' first
zeros are one sample, the first terminal event, the observation (event; administrative: alive
through the registered end; ongoing; technical: failed, invalidated, broken evidence, a refill, or a
done / extinct state its evidence does not support), the burn-in disposition (a zero AT the burn-in
frame is data, not an early failure) and establishment (established; restarted; exhausted: an
establishment failure, not censoring; restart pending; unresolved), coexistence THROUGH the burn-in
frame, integrity events, and the evidence hashes (state, acceptance ledger, each segment's verified
main-CSV prefix, the tail, the relocation manifest, attempt.json). At each
horizon (5, 20, 30, 50, 100, 150, 200M within the schedule; the end is primary) and per treatment,
with the registered slots as the FIXED denominator: known alive, predator extinct (a zero sampled
at the horizon counts), prey-terminal (prey first, the run stopped: a competing event, later predator
status unobserved), technical, not yet observed; with complete ascertainment the proportion and its
exact (Clopper-Pearson) pointwise 95% interval, otherwise the identification bounds [alive / N,
(alive + unresolved) / N]. Three estimands, separately labelled: the PRIMARY first founder attempt of
every slot (establishment failures included), the retained attempt, and survival conditional on
evidenced coexistence THROUGH the burn-in frame (its own denominator: a zero exactly at the burn-in
frame is excluded here, though data elsewhere). The registered end is always a horizon (a custom
--horizons keeps it). Also the observed event times, the
first-terminal-event frequencies, the attempt accounting (early failures / resolved attempts,
established and exhausted slots, unresolved technical cases) and Q200: the retained C histories
coexisting through the registered end (>= 24 is H-P/H-Q/H-F/H-T's availability safeguard only).

MONITORING (monitor; Annex H D6 rules 29-30; READ-ONLY). Every C and B world's current attempt over
its evidence-bound sequence, armed after the burn-in frame: rolling --window (25,000-frame) windows
every --step (5,000) frames and complete non-overlapping checkpoint_every (1M) summaries, each with
its predator-seconds (the trapezoid of the sampled predator abundance x 0.016 s per frame), the
exposure-weighted mean energy (predator_avg_energy), and for C (its lineage logs along the accepted
chain, through the last accepted frame) the starvation deaths of PROVEN BREEDERS (the parent of at
least one realized B event before the death, carried across segments), of the others and in total
per 1,000 predator-seconds, their mean age at death, the lifespan-normalized starvation hazard
(starvation per predator-second x the registered predator max age), and births minus deaths; every
window has the captures (the corrected kills_interval) and captures per predator-second, and
expenditure is explicitly unavailable (not logged); a starved predator without lineage ancestry
makes the breeder indicator unavailable for its window, and B has no breeder indicator or age at
death (no individual lineage log; its births and deaths are the main CSV's intervals, a resumed
segment's first row corrected by its checkpoint's counters). Each 1M summary has the range of the 5k
births-minus-deaths series; the latest accepted checkpoint's individual-energy lower tail (min,
p05, p10) is reported; --windows-out writes EVERY rolling window and the full 5k series (gzipped
JSON lines, bound by sha256 in the document). The windows are a chronological sweep. The document
binds the tool's and evidence.py's sha256 and each world's attempt.json. Flags: DETERIORATION (breeder starvation > 0.1
per 1,000 predator-s AND mean energy < 180 in one window; consecutive windows merged into
episodes) and ACUTE (any sampled predator population <= 15 in C or B after the burn-in; not A,
whose count is 12). Flags are diagnostics: they are recorded, verified and notified, and never
trigger rescue, reseeding, treatment, horizon or allocation changes, extra worlds or selective assay
omission.

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
import evidence  # noqa: E402
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
RELOC_SCHEMA = "finfolk.redqueen.relocated/1"
LAYOUTS = {"48": [{"C": 4, "A": 1, "B": 1}], "56": [{"C": 4, "A": 2, "B": 1}, {"C": 4, "A": 1, "B": 2}],
           "64": [{"C": 4, "A": 2, "B": 2}]}
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
    """"C=4,A=1,B=1" -> one allocation; "C=4,A=2,B=1;C=4,A=1,B=2" -> a list cycled over the blocks."""
    allocs = []
    for one in spec.split(";"):
        out = {}
        for part in one.split(","):
            t, _, n = part.partition("=")
            if t not in TREATMENTS or not n.isdigit():
                raise WorldsError(f"--per-block {spec!r}: expected e.g. C=4,A=1,B=1 (';' between block allocations)")
            out[t] = int(n)
        allocs.append({t: out.get(t, 0) for t in TREATMENTS})
    return allocs[0] if len(allocs) == 1 else allocs


def block_allocations(per_block, blocks):
    """The allocation of every block 1..blocks (a list is cycled)."""
    lst = per_block if isinstance(per_block, list) else [per_block]
    return [dict(lst[(b - 1) % len(lst)]) for b in range(1, blocks + 1)]


def register(arena_path, namespace, blocks=8, per_block=None, avoid_paths=(), schedule=None,
             allow_placeholder=False, c_founders=C_FOUNDERS, burn_in=BURN_IN, max_restarts=MAX_RESTARTS, layout=None):
    per_block = per_block or {"C": 4, "A": 1, "B": 1}
    allocs = block_allocations(per_block, blocks)
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
    used = [t for t in TREATMENTS if any(al[t] > 0 for al in allocs)]
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
    reserve = {t: max([RESERVE[t]] + [al[t] for al in allocs]) for t in TREATMENTS}
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
        order = [(t, k) for t in TREATMENTS for k in range(allocs[b - 1][t])]
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
            "layout": layout, "block_allocations": {str(b): allocs[b - 1] for b in range(1, blocks + 1)},
            # (the registered 64 layout's note is D7's; any other keeps its earlier note, and so its bytes)
            "allocation_note": ("Annex H D7 rule 34: the fixed allocation, eight randomized blocks of 4C + 2A + 2B "
                                "(32 C, 16 A, 16 B); both A and both B controls of a block keep their treatment's "
                                "definition, neither a technical replicate nor another block" if layout == "64" else
                                "blocks are randomized and exchangeable: which blocks take which allocation is "
                                "immaterial (the 56 layout: odd blocks 4C+2A+1B, even blocks 4C+1A+2B)"),
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


def fsync_tree(path):
    """Every file and directory under path, bottom up, then path itself and its parent (durable
    evidence before an irreversible decision)."""
    if not os.path.isdir(path):
        return
    for d, dirs, files in os.walk(path, topdown=False):
        for f in files:
            fp = os.path.join(d, f)
            if os.path.isfile(fp) and not os.path.islink(fp):
                rqlib.fsync_file(fp)
        rqlib.fsync_dir(d)
    rqlib.fsync_dir(os.path.dirname(os.path.abspath(path)))


def burn_in_of(reg):
    return int(reg.get("burn_in") or 0) if reg.get("seed_scheme") == SEED_SCHEME else 0


def burn_in_decided(root, reg, wid):
    """-> (decided, why): whether the world's CURRENT attempt can no longer be replaced by the burn-in
    rule: the rule is off; the world ended (done, extinct: final); its acceptance chain reached the
    burn-in frame alive; or its earliest supported zero is at or after the burn-in frame (data)."""
    bi = burn_in_of(reg)
    if not bi:
        return True, "no burn-in rule"
    st = read_state(root, wid)
    if st["status"] in ("done", "extinct"):        # (final: data, or the restarts exhausted)
        return True, f"ended {st['status']}"
    led = read_jsonl(os.path.join(root, "availability.jsonl"))
    z = first_zeros(led, wid, root)                # (the current attempt's supported zeros)
    if z and min(z.values()) < bi:                 # FIRST: an early zero means a restart is coming,
        return False, (f"attempt {attempt_of(root, wid)} has an evidenced zero at frame {min(z.values())} before "
                       f"the burn-in frame {bi}: it will be restarted")      # whatever was accepted past it
    if z:
        return True, f"its first zero {min(z.values())} is at or after the burn-in frame"
    # no published zero: survival is established from the BIOLOGICAL rows themselves (a zero may sit in
    # verified logs before recovery publishes it), never from the ledger's silence
    w = next((x for x in reg["worlds"] if x["id"] == wid), None)
    tr = w["treatment"] if w else "C"
    good = verified_records(root, wid, st, tr) if st["segments"] else {}
    how, f = chain_rows_through(root, wid, st, tr, good, bi, reg["schedule"]["log_every"])
    if how == "zero":
        return False, (f"attempt {attempt_of(root, wid)}'s verified main CSV has a zero at frame {f} before the "
                       f"burn-in frame {bi}: it will be restarted")
    if how == "zero-at":
        return True, f"its verified main CSV's first zero is at frame {f}, at or after the burn-in frame (data)"
    if how == "alive":
        return True, f"its verified main-CSV rows are nonzero through frame {f} >= the burn-in frame {bi}"
    return False, f"attempt {attempt_of(root, wid)} has not passed the burn-in frame {bi} yet (rows to {f})"


def chain_rows_through(root, wid, st, treatment, good, bi, log_every):
    """The VALIDATED main-CSV rows of the verified acceptance chain, through the burn-in frame: each chain
    segment's verified prefix (the bytes its last chain record covers), its rows from its start frame on
    the log_every sequence (valid_row), up to the frame the chain leaves it; the segments contiguous.
    -> ("zero", f): a guild at 0 at f < bi; ("zero-at", f): the first zero at the first row f >= bi;
    ("alive", f): every row before bi nonzero and a row at f >= bi; ("short", f): the rows end at f < bi."""
    chain = verified_chain(st, good)
    segs = {s["name"]: s for s in st["segments"]}
    last, order = {}, []
    for r in chain:                                     # (frame order = segment order along the chain)
        if r["segment"] not in last:
            order.append(r["segment"])
        last[r["segment"]] = r
    reached = 0
    for name in order:
        s, cut = segs[name], last[name]
        if s["start_frame"] != reached:                 # (not contiguous with the rows before it)
            return "short", reached
        n = cut["logs"]["run.csv"]["bytes"]
        try:
            with open(os.path.join(wdir(root, wid), name, "run.csv"), "rb") as fh:
                raw = fh.read(n)
        except OSError:
            return "short", reached
        if len(raw) != n:
            return "short", reached
        lines = raw[: raw.rfind(b"\n") + 1].split(b"\n")[:-1]
        if not lines:
            return "short", reached
        hdr = next(csv.reader([lines[0].decode("utf-8")]))
        prev = s["start_frame"]
        for ln in lines[1:]:
            r = next(csv.reader([ln.decode("utf-8")]))
            if not valid_row(hdr, r, prev, log_every) or int(r[0]) > cut["frame"]:
                break
            prev = int(r[0])
            zero = any(int(r[hdr.index(col)]) == 0 for g, col in GUILDS
                       if col in hdr and not (g == "predators" and treatment == "A"))
            if zero:
                return ("zero" if prev < bi else "zero-at"), prev
            if prev >= bi:
                return "alive", prev
        if prev != cut["frame"]:                        # (its rows do not reach the frame the chain leaves it)
            return "short", prev
        reached = prev
    return "short", reached


def attempt_dir(root, wid, attempt):
    """A world's attempt directory: the current one, or a retained (restarted) one."""
    if attempt == attempt_of(root, wid):
        return wdir(root, wid)
    return os.path.join(root, "restarts", "worlds", f"{wid}.a{attempt}")


def attempt_archive_records(root, wid, attempt):
    """A retained attempt's archive index resolved to its own (relocated) bytes: {label: record}."""
    d = attempt_dir(root, wid, attempt)
    out = {}
    for r in read_jsonl(os.path.join(d, "archive.jsonl")):
        out.setdefault(r["label"], dict(r))
    rp = os.path.join(d, "relocated.json")
    if os.path.isfile(rp):
        rel = rqlib.read_json(rp)
        a0, a1 = rel["archive_from"].rstrip(os.sep) + os.sep, rel["archive_to"].rstrip(os.sep) + os.sep
        for r in out.values():
            if r["path"].startswith(a0):
                r["original_path"] = r["path"]
                r["path"] = a1 + r["path"][len(a0):]
    return out


def audit_attempt(root, wid, attempt):
    """Problems of a retained attempt's archive (empty: every recorded object resolves to its bytes)."""
    d = attempt_dir(root, wid, attempt)
    if not os.path.isfile(os.path.join(d, "archive.jsonl")):
        return [f"attempt {attempt} of {wid}: no archive index at {d}"]
    probs = []
    for lab, r in sorted(attempt_archive_records(root, wid, attempt).items()):
        if not os.path.isfile(r["path"]):
            probs.append(f"{lab}: {r['path']} is missing")
        elif rqlib.sha256_file(r["path"]) != r["sha256"]:
            probs.append(f"{lab}: {r['path']} does not hash to its record")
    return probs


def complete_restart(root, archive_root, reg, wid, rec):
    """The moves and the fresh start of a RECORDED restart (idempotent; the record is the commitment):
    the relocation manifest into the failed attempt, the attempt and its archive moved aside, a fresh
    attempt directory (made whole, then renamed into place) and its pending state."""
    n = int(rec["attempt"])
    src = wdir(root, wid)
    dst = os.path.join(root, "restarts", "worlds", f"{wid}.a{n - 1}")
    asrc = adir(archive_root, wid)
    adst = os.path.join(archive_root, "restarts", f"{wid}.a{n - 1}")
    cur = attempt_of(root, wid)
    if os.path.isdir(src) and cur == n - 1:
        rp = os.path.join(src, "relocated.json")
        if not os.path.isfile(rp):
            rqlib.write_durable(rp, rqlib.canonical({
                "schema": RELOC_SCHEMA, "world": wid, "attempt": n - 1, "world_from": src, "world_to": dst,
                "archive_from": asrc, "archive_to": adst, "restart": rec, "utc": rqlib.now_utc()}))
        for a_, b_ in ((src, dst), (asrc, adst)):
            if not os.path.isdir(a_):
                continue
            if os.path.exists(b_):
                raise WorldsError(f"{wid}: restart {n}: {b_} already exists")
            mkdirs_durable(os.path.dirname(b_))
            os.rename(a_, b_)
            rqlib.fsync_dir(os.path.dirname(a_))
            rqlib.fsync_dir(os.path.dirname(b_))
    elif os.path.isdir(asrc) and not os.path.isdir(src) and cur != n:
        if os.path.exists(adst):
            raise WorldsError(f"{wid}: restart {n}: {adst} already exists")
        mkdirs_durable(os.path.dirname(adst))
        os.rename(asrc, adst)
        rqlib.fsync_dir(os.path.dirname(asrc))
        rqlib.fsync_dir(os.path.dirname(adst))
    if attempt_of(root, wid) != n:
        if os.path.isdir(src):
            raise WorldsError(f"{wid}: restart {n}: {src} is neither attempt {n - 1} nor {n}")
        new = f"{src}.new"                          # (made whole, then renamed into place)
        shutil.rmtree(new, ignore_errors=True)
        mkdirs_durable(new)
        rqlib.write_durable(os.path.join(new, "attempt.json"), rqlib.canonical(
            {"schema": ATTEMPT_SCHEMA, "world": wid, "attempt": n, "seed": rec["seed"], "slot": rec.get("slot")}))
        os.rename(new, src)
        rqlib.fsync_dir(os.path.dirname(src))
        write_state(root, wid, {"schema": STATE_SCHEMA, "id": wid, "status": "pending", "failures": 0,
                                "segments": [], "attempt": n})


def reconcile_restarts(root, reg, archive_root, log=None):
    """Complete every recorded restart whose moves a crash interrupted (before anything else writes):
    -> the worlds completed."""
    done = []
    for w in reg["worlds"]:
        led = restart_records(root, w["id"])
        if led:
            last = max(led, key=lambda r: int(r["attempt"]))
            if attempt_of(root, w["id"]) != int(last["attempt"]):
                complete_restart(root, archive_root, reg, w["id"], last)
                done.append(w["id"])
                if log:
                    log(f"{w['id']}: its recorded restart (attempt {last['attempt']}) completed")
    return done


def valid_row(hdr, r, prev_frame, log_every):
    """A main-CSV row as biological evidence: the header's width, an integral frame on the segment's
    sequence (prev + log_every), integral non-negative guild counts."""
    if len(r) != len(hdr) or not re.fullmatch(r"\d+", r[0] or ""):
        return False
    if prev_frame is not None and log_every and int(r[0]) != prev_frame + log_every:
        return False
    for _, col in GUILDS:
        if col in hdr and not re.fullmatch(r"\d+", r[hdr.index(col)] or ""):
            return False
    return True


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


def verified_records(root, wid, st, treatment, base=0, d=None, recs=None):
    """{(segment, frame): acceptance record} of the records whose log parts still verify (each
    segment's parts in order, without a gap), in segments whose start is itself such a record
    (back to the founder segment). d: the attempt's directory (default the world's current one; a
    retained attempt's for the ecology export); recs: its acceptance records already read."""
    d = d or wdir(root, wid)
    by_seg = {}
    for r in (accept_records(root, wid) if recs is None else recs):
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
                and verify_delta(os.path.join(d, name, f), r["logs"][f]) for f, _ in kinds)
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


def scan_zeros(root, wid, st, treatment, log_every=None):
    """{guild: (the earliest frame at which it is 0 in any segment's main CSV, that segment, the
    byte count of the CSV prefix through the row)}; only VALID rows count (valid_row: the header's
    width, integral counts, the segment's frame sequence from its start frame)."""
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
        prev = s.get("start_frame") if log_every else None
        for ln in lines[1:]:
            pos += len(ln) + 1
            if not ln:
                continue
            r = next(csv.reader([ln.decode("utf-8")]))
            if not valid_row(hdr, r, prev, log_every):
                break                                    # (no evidence past an invalid row)
            prev = int(r[0])
            for guild, col in GUILDS:
                if (guild == "predators" and treatment == "A") or col not in hdr or guild in found:
                    continue
                if int(r[hdr.index(col)]) == 0:
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
        self.bad_rows = set()   # (wid, segment) whose main CSV had an invalid row (no later evidence)
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
        fsync_tree(wdir(self.root, wid))                 # (the failed attempt's evidence durable FIRST)
        fsync_tree(adir(self.archive_root, wid))
        _append_durable(os.path.join(self.root, "restarts.jsonl"), rec)      # (the commitment point)
        self.complete_restart(wid, rec)
        self.log(f"BURN-IN: {wid} ({w['treatment']}) went extinct before frame {self.burn_in} ({reason}): restarted "
                 f"as attempt {n} from its slot's next reserved seed {nxt['founder_seed']}")
        return True

    def complete_restart(self, wid, rec):
        complete_restart(self.root, self.archive_root, self.reg, wid, rec)
        self.after_restart(wid)

    def after_restart(self, wid):
        """The world at its new attempt; every per-world cache of the old one dropped."""
        n = attempt_of(self.root, wid)
        self.worlds[wid] = effective_world(self.reg, next(x for x in self.reg["worlds"] if x["id"] == wid), n)
        for cache in (self.zeros, self.extinct, self.chain, self.chain_active, self.tails, self.last_frame):
            cache.pop(wid, None)
        for k in [k for k in self.seen if k[0] == wid]:
            del self.seen[k]
        for k in [k for k in self.start_cps if k[0] == wid]:
            del self.start_cps[k]
        self.bad_rows = {k for k in self.bad_rows if k[0] != wid}
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
        rqlib.fsync_dir(os.path.dirname(p))              # (its directory entries: the evidence's path)
        rqlib.fsync_dir(wdir(self.root, wid))
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

    def early_zero(self, wid, frame=None):
        """An evidenced zero before the burn-in frame (the rule applies under either --on-extinction)."""
        z = min((self.zeros.get(wid) or {}).values(), default=None) if frame is None else frame
        return bool(self.burn_in and z is not None and z < self.burn_in)

    def stops_at(self, wid, frame=None):
        return self.a.on_extinction == "stop" or self.early_zero(wid, frame)

    def recover_zeros(self, wid):
        for guild, (f, seg, n) in scan_zeros(self.root, wid, self.state(wid), self.worlds[wid]["treatment"],
                                             self.sched["log_every"]).items():
            self.note_zero(wid, guild, f, seg, n, recovered=True)

    def zero_reason(self, wid):
        z = self.zeros.get(wid) or {}
        return "; ".join(f"the {g} reached 0 at frame {f}" for g, f in sorted(z.items())) or None

    def watch(self, wid):
        """New main-CSV rows of a running segment: the frame reached; a guild at zero -> (guild, frame)."""
        t = self.tails[wid]
        seg = self.running[wid][1] if wid in self.running else self.state(wid)["segments"][-1]["name"]
        found = None
        rows = t.lines()
        if (wid, seg) in self.bad_rows:            # (an invalid row seen: nothing later in this segment counts)
            return None
        for r, end in zip(rows, t.ends):
            prev = self.last_frame.get(wid)
            if prev is None:
                prev = next((x["start_frame"] for x in self.state(wid)["segments"] if x["name"] == seg), None)
            if not valid_row(t.header, r, prev, self.sched["log_every"]):
                self.bad_rows.add((wid, seg))
                self.warn_once((wid, seg, "invalid-row"), f"{wid}: {seg}'s main CSV has an invalid row after frame "
                                                         f"{prev}: no biological evidence is read past it")
                break
            fr = int(r[0])
            self.last_frame[wid] = fr
            row = dict(zip(t.header, r))
            for guild, col in GUILDS:
                if guild == "predators" and self.worlds[wid]["treatment"] == "A":
                    continue
                if int(row[col]) == 0:
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
        if self.stops_at(wid) and self.zero_reason(wid):
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
        if ext and self.stops_at(wid, ext[1]) and wid not in self.extinct:   # (it ended before we could stop it)
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
        for wid in reconcile_restarts(self.root, self.reg, self.archive_root, self.log):
            self.after_restart(wid)                        # (a restart recorded, its moves interrupted)
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
                    self.recover_zeros(wid)                # (FIRST: an early zero is published before any
                    self.archive_pass(wid, alive=False)    # acceptance past it is made)
                    self.accept_pass(wid, alive=False)
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
                if ext and self.stops_at(wid, ext[1]) and wid not in self.extinct:
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
    reconcile_restarts(root, reg, archive_root, log)     # (an interrupted restart completed before any write)
    exe, exe_sha = pin_binary(root, a.binary)
    sup = Supervisor(root, reg, archive_root, exe, exe_sha, a, log)
    sup.guards = runlib.disk_guards(a.disk_min, root)
    return sup.run()


# ================================================================== F1
def f1(a, log):
    root = os.path.abspath(a.root)
    reg, sha = load_registry(root, a.allow_placeholder)
    archive_root = bind_root(root, sha, a.archive_root, create=True)
    reconcile_restarts(root, reg, archive_root, log)     # (an interrupted restart completed before any write)
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
    archive_root = bind_root(root, sha, a.archive_root)
    reconcile_restarts(root, reg, archive_root, log)     # (an interrupted restart completed before any write)
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


# ================================================================== ecology and monitoring (Annex H D6)
ECOLOGY_SCHEMA = "finfolk.redqueen.ecology/1"
MONITOR_SCHEMA = "finfolk.redqueen.monitor/1"
ECO_HORIZONS_M = (5, 20, 30, 50, 100, 150, 200)    # D6 rule 22 (200M primary; the others secondary)
FRAME_DT = 0.016                                   # seconds per frame (D6 rule 29's exposure)
MON_WINDOW, MON_STEP = 25_000, 5_000               # D6 rule 29: rolling windows, evaluated every 5k
MON_BREEDER_RATE, MON_ENERGY, MON_ACUTE = 0.1, 180.0, 15
SEQ_COLS = ("predator_avg_energy", "predator_reseeds_cum", "predator_births_interval", "predator_deaths_starv",
            "predator_deaths_age", "kills_interval")
AT_HORIZON = ("alive", "predator_extinct", "prey_terminal", "technical", "not_yet_observed")
UNRESOLVED = ("prey_terminal", "technical", "not_yet_observed")
ATTEMPT_DIR_RE = re.compile(r"^(?P<w>.+)\.a(?P<k>\d+)$")


def _read_once(path, n=None):
    """(bytes, sha256) of a file (its first n bytes), read once; (None, None) when it cannot be read."""
    try:
        with open(path, "rb") as f:
            raw = f.read() if n is None else f.read(n)
    except OSError:
        return None, None
    return raw, rqlib.sha256_bytes(raw)


def _jsonl_bytes(raw, path):
    """read_jsonl's records from bytes already read (a torn tail ignored; a malformed interior line refused)."""
    out = []
    if not raw:
        return out
    for k, ln in enumerate(raw[: raw.rfind(b"\n") + 1].split(b"\n")[:-1], 1):
        try:
            out.append(json.loads(ln.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            raise WorldsError(f"{path}: line {k} is malformed (not a torn tail)")
    return out


def _covered(path, recs, log):
    """The bytes of a segment's log its acceptance records cover, read ONCE and re-verified part by part
    (parts {from, bytes, sha256} contiguous from 0, in frame order) -> (bytes, the last covered record): the
    verification stops at the first part that no longer verifies, keeping the earlier parts (Codex #75 r1 P2-5)."""
    recs = sorted(recs, key=lambda r: r["frame"])
    if not recs:
        return b"", None
    raw, _ = _read_once(path, recs[-1]["logs"][log]["bytes"])
    raw = raw or b""
    pos, last = 0, None
    for r in recs:
        p = r["logs"][log]
        if p["from"] != pos or len(raw) < p["bytes"] or rqlib.sha256_bytes(raw[p["from"]:p["bytes"]]) != p["sha256"]:
            break
        pos, last = p["bytes"], r
    return raw[:pos], last


def _lineage_rows(raw, upto):
    """[(frame, event, id, parent, age)] of a lineage-log prefix (bytes), through frame `upto` (age None if absent)."""
    lines = evidence.complete(raw).split(b"\n")[:-1]
    if not lines:
        return []
    hdr = lines[0].decode("ascii", "replace").strip().split(",")
    ia = hdr.index("age") if "age" in hdr else None
    out = []
    for ln in lines[1:]:
        p = ln.split(b",")
        try:
            f, ev, i, par = int(p[0]), p[1].decode("ascii"), int(p[2]), int(p[3])
            age = float(p[ia]) if ia is not None else None
        except (IndexError, ValueError, UnicodeDecodeError):
            return None                                   # (the acceptance validated it: damage)
        if f > upto:
            break
        out.append((f, ev, i, par, age))
    return out


def attempt_sequence(root, wid, d, w, attempt, ledger, log_every, lineage=False):
    """One attempt's EVIDENCE-BOUND sample sequence under evidence.py's rules (shared with val_block.py; Annex H D6
    rule 24): the chain is the NEWEST line of descent of the attempt's segments (each chain segment after the
    first must resume its predecessor's acceptance record at its start); each chain segment's main-CSV bytes are
    those its acceptance records cover (re-verified part by part; a part that no longer verifies ends the
    coverage there, the earlier parts kept); the newest chain segment may extend past its last acceptance by the
    availability-ledger prefix of THAT segment that binds a zero (its bytes hashing to the record and extending
    the covered bytes; a continuation is never chosen by its length). Rows are validated as evidence.py's, the
    first absorbing terminal ends the observation, and a refill above the founders' baseline (0; a branch's is
    unknown here: unchecked) ends it before. Every other ledger entry of the attempt is listed as unsupported,
    with why. With lineage (C), the chain's lineage events (acceptance-covered, through each segment's cut)."""
    base = base_frame(w)
    tr = w["treatment"]
    st_raw, st_sha = _read_once(os.path.join(d, "state.json")) if d else (None, None)
    try:
        st = json.loads(st_raw.decode("utf-8")) if st_raw else {"status": "pending", "segments": []}
    except (ValueError, UnicodeDecodeError):
        st = {"status": "unreadable", "segments": []}
    acc_raw, acc_sha = _read_once(os.path.join(d, "accept.jsonl")) if d else (None, None)
    recs = _jsonl_bytes(acc_raw, os.path.join(d or "", "accept.jsonl"))
    by = {}
    for r in recs:
        by.setdefault(r["segment"], []).append(r)
    segs = st.get("segments", [])
    segmap = {s["name"]: s for s in segs}
    # (#75 r2 P2-1) the newest segment's line of descent through its RECORDED parent links (resumed_accept)
    chain, stop = evidence.chain_links([(s["name"], s["start_frame"], (s.get("resumed_accept") or {}).get("segment"))
                                        for s in segs], base) if segs else ([], None)
    mine = [e for e in ledger if e.get("world") == wid and int(e.get("attempt", 0) or 0) == attempt]
    samples, evid, events, accepted, tail_ev = [], [], [], base, None
    lin_through, lin_open, ckpts = base, lineage, []
    if stop:
        chain = []
    for i, (name, start, upto) in enumerate(chain):
        s = segmap[name]
        if i:                                          # (its ancestry: the predecessor's record at its start)
            prev = chain[i - 1][0]
            ra = s.get("resumed_accept") or {}
            rec = next((r for r in by.get(prev, []) if r["frame"] == start), None)
            if (ra.get("segment"), ra.get("frame")) != (prev, start) or rec is None or ra.get("sha256") != rec["sha256"]:
                stop = f"{name} does not resume {prev}'s acceptance record at frame {start}"
                break
        raw, cov = _covered(os.path.join(d, name, "run.csv"), by.get(name, []), "run.csv")
        use, newest = raw, i == len(chain) - 1
        if newest:
            for e in mine:                             # (this segment's ledger prefix extending the covered bytes)
                n = e.get("csv_bytes")
                if e.get("segment") != name or not isinstance(n, int) or n <= len(raw):
                    continue
                pre, sha = _read_once(os.path.join(d, name, "run.csv"), n)
                if pre and len(pre) == n and sha == e.get("csv_sha256") and pre[:len(raw)] == raw and len(pre) > len(use):
                    use, tail_ev = pre, {"segment": name, "csv_bytes": n, "csv_sha256": sha, "ledger_guild": e.get("guild")}
        try:
            if not use and newest:                     # (a newest segment with nothing covered yet: still running)
                rows, why = [], None
            else:
                rows, why = evidence.segment_rows(use, start, log_every, upto, cols=SEQ_COLS)
        except evidence.EvidenceError as ex:
            rows, why = [], str(ex)
        if cov is not None:
            accepted = max(accepted, min(cov["frame"], upto) if upto is not None else cov["frame"])
            # (#75 r2 P2-5) the checkpoints on the line of descent: covered, and at or before this segment's cut
            ckpts += [(r["frame"], r["sha256"]) for r in sorted(by.get(name, []), key=lambda r: r["frame"])
                      if r["frame"] <= cov["frame"] and (upto is None or r["frame"] <= upto)]
        evid.append({"segment": name, "start_frame": start, "until": upto, "through": rows[-1][0] if rows else start,
                     "csv_bytes": len(use), "csv_sha256": rqlib.sha256_bytes(use),
                     "checkpoint_frame": cov["frame"] if cov else None,
                     "checkpoint_sha256": cov["sha256"] if cov else None})
        if lin_open and cov is not None:
            # (#75 r2 P2-3) the lineage history must be CONTIGUOUS from the base: a segment's lineage covered short
            # of its cut (or a segment without it) ends the coverage; nothing after a gap is admitted
            lraw, lcov = _covered(os.path.join(d, name, "run.predlog.csv"), by.get(name, []), "run.predlog.csv")
            lc = (lcov or {}).get("frame", start)
            reach = min(lc, upto) if upto is not None else lc
            lrows = _lineage_rows(lraw, reach)
            if lrows is None:
                stop = f"{name}/run.predlog.csv no longer parses"
                break
            if start != lin_through:
                lin_open = False
            else:
                events.append((name, start, lrows, reach))
                lin_through = reach
                if upto is not None and lc < upto:
                    lin_open = False
            evid[-1].update(predlog_bytes=len(lraw), predlog_sha256=rqlib.sha256_bytes(lraw), predlog_through=reach)
        elif lin_open and not newest:
            lin_open = False
        samples += rows
        if why:
            stop = f"{name}: {why}"
            break
    guilds = tuple(gc for gc in evidence.GUILD_COLS if not (gc[0] == "predators" and tr == "A"))
    obs = evidence.terminal(samples, guilds, base, refill_base=0 if base == 0 else None)
    names = {c[0] for c in chain}
    unsupported = []
    for e in mine:
        g, zf = e.get("guild"), e.get("first_zero_frame")
        z = (obs["events"].get(g) or {}).get("frame") if g in dict(guilds) else None
        if e.get("segment") not in names:
            why = "its segment is not on the newest line of descent (a superseded continuation)"
        elif z == zf:
            continue
        elif obs["first_terminal"] and isinstance(zf, int) and zf > obs["first_terminal"]["frame"]:
            why = (f"after the first absorbing terminal boundary (frame {obs['first_terminal']['frame']}): it does not "
                   "resolve the competing outcome")
        else:
            why = "not the evidenced first sampled zero of its guild (its prefix does not hash, or it is not first)"
        unsupported.append({"guild": g, "first_zero_frame": zf, "segment": e.get("segment"), "why": why})
    used = {e["segment"] for e in evid}
    return {"state": st, "obs": obs, "samples": obs["samples"], "accepted_through": accepted, "stop": stop,
            "lineage": events, "lineage_through": lin_through if lineage else None, "checkpoints": ckpts,
            "evidence": {"state_sha256": st_sha, "accept_bytes": len(acc_raw or b""), "accept_sha256": acc_sha,
                         "segments": evid, "tail": tail_ev, "superseded_segments": sorted(set(segmap) - used)},
            "unsupported_ledger": unsupported}


def attempt_outcome(seq, w, total, burn_in):
    """An attempt's ecological record from its evidence-bound sequence (D6 rules 23-25): each guild's first evidenced
    sampled zero and the sample before it (A's predators are structural), the joint flag and the first terminal
    event (the first absorbing boundary: later overshoot rows never resolve the other guild), the observation
    (event; administrative: alive through the registered end; ongoing; technical: failed, invalidated, broken
    evidence, a refill, or a done / extinct state the evidence does not support), the censor record, the burn-in
    disposition (a zero AT the burn-in frame is data: not an early failure), coexistence THROUGH the burn-in frame
    (the establishment-conditional set: evidenced alive at it, no terminal event at or before it), protocol-
    integrity events (a refill above the founders' baseline: nothing after it establishes natural coexistence)."""
    base, tr = base_frame(w), w["treatment"]
    obs = seq["obs"]
    status = seq["state"].get("status", "pending")
    events = dict(obs["events"])
    if tr == "A":
        events["predators"] = "structural"
    first, frontier, integrity = obs["first_terminal"], obs["frontier"], []
    if obs["refill"]:
        r = obs["refill"]
        integrity.append(f"a predator refill at frame {r['frame']} (predator_reseeds_cum {r['value']} > the founders' "
                         f"{r['baseline']}): a protocol-integrity event to investigate; the observation ends at {frontier}")
    if base and seq["samples"] is not None:
        integrity.append("a fork branch: its refill baseline (the origin's counter) is not checked here")
    if first:
        kind = "event"
    elif obs["refill"]:
        kind = "technical"
    elif frontier >= total and not seq["stop"]:
        kind = "administrative"
    elif status in ("failed", "invalidated", "unreadable", "done", "extinct") or seq["stop"]:
        kind = "technical"
        if status == "extinct":
            integrity.append("its state says extinct, but no zero is evidenced (recover it from its evidence)")
        elif status == "done":
            integrity.append(f"its state says done, but its evidence ends at frame {frontier}")
    else:
        kind = "ongoing"
    if not burn_in:
        bi = "no rule"
    elif first and first["frame"] < burn_in:
        bi = "early_failure"
    elif first or frontier >= burn_in:
        bi = "established"
    else:
        bi = "unresolved"
    through_bi = bool(burn_in) and frontier >= burn_in and (first is None or first["frame"] > burn_in)
    censor = None
    if kind == "administrative":
        censor = {"kind": "administrative", "frame": total}
    elif kind in ("technical", "ongoing"):
        censor = {"kind": kind, "frame": frontier}
    return {"status": status, "end_reason": seq["state"].get("end_reason"), "frontier": frontier,
            "accepted_through": seq["accepted_through"], "samples": len(seq["samples"]), "events": events,
            "joint": obs["joint"], "first_terminal": first, "observation": kind, "censor": censor, "burn_in": bi,
            "coexisting_through_burn_in": through_bi, "refill": obs["refill"], "integrity": integrity,
            "stop": seq["stop"], "evidence": seq["evidence"], "unsupported_ledger": seq["unsupported_ledger"]}


def at_horizon(o, H):
    """An attempt's predator status at horizon H (frames; D6 rule 25): predator_extinct (its first zero at or before
    H: a zero sampled exactly at H counts), alive (evidenced through H), prey_terminal (the prey's zero first, the
    observation ended before H: later predator status unobserved, a competing event, not predator extinction),
    not_yet_observed (still running) or technical."""
    zp = o["events"].get("predators")
    if isinstance(zp, dict) and zp["frame"] <= H:
        return "predator_extinct"
    if o["frontier"] >= H:
        return "alive"
    zq = o["events"].get("prey")
    if isinstance(zq, dict) and zq["frame"] <= H:
        return "prey_terminal"
    return "not_yet_observed" if o["observation"] == "ongoing" else "technical"


def clopper_pearson(x, n, alpha=0.05):
    """The exact (Clopper-Pearson) two-sided 1 - alpha binomial interval for x of n (bisection on the tails)."""
    def cdf(k, p):
        return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))

    def solve(g):                                         # g increasing in p, root in [0, 1]
        lo, hi = 0.0, 1.0
        for _ in range(200):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if g(mid) < 0 else (lo, mid)
        return (lo + hi) / 2
    lower = 0.0 if x == 0 else solve(lambda p: (1 - cdf(x - 1, p)) - alpha / 2)
    upper = 1.0 if x == n else solve(lambda p: alpha / 2 - cdf(x, p))
    return [lower, upper]


def survival_table(outcomes, N, horizons):
    """Per horizon: the counts (AT_HORIZON) over a FIXED denominator N, and either the empirical proportion with
    its pointwise exact 95% interval (complete ascertainment) or the identification bounds [alive / N, (alive +
    unresolved) / N] (D6 rule 25; never a complete-case proportion or an independence-assuming Kaplan-Meier)."""
    out = {}
    for H in horizons:
        c = {k: 0 for k in AT_HORIZON}
        for o in outcomes:
            c[at_horizon(o, H)] += 1
        c["unlisted"] = N - len(outcomes)                # (a registered slot without a record: unresolved)
        unres = sum(c[k] for k in UNRESOLVED) + c["unlisted"]
        row = {"N": N, "counts": c, "unresolved": unres, "complete": unres == 0 and N > 0}
        if N and unres == 0:
            row.update(estimate=c["alive"] / N, ci95=clopper_pearson(c["alive"], N))
        elif N:
            row["bounds"] = [c["alive"] / N, (c["alive"] + unres) / N]
        out[str(H)] = row
    return out


def _times(outcomes):
    """Observed event times and first-terminal-event frequencies (reported separately from survival)."""
    ext = {"predators": [], "prey": []}
    freq = {"predators": 0, "prey": 0, "joint": 0, "none": 0}
    for o in outcomes:
        for g in ext:
            z = o["events"].get(g)
            if isinstance(z, dict):
                ext[g].append({"world": o["world"], "attempt": o["attempt"], "frame": z["frame"],
                               "previous_sample": z["previous_sample"], "joint": o["joint"]})
        freq[o["first_terminal"]["kind"] if o["first_terminal"] else "none"] += 1
    for g in ext:
        ext[g].sort(key=lambda x: (x["frame"], x["world"]))
    return {"extinction_times": ext, "first_terminal_events": freq}


def attempt_index(root, wid, restarts):
    """Every attempt of a world, discovered READ-ONLY (Codex #75 r1 P2-4) from the restart ledger (each record: its
    failed attempt and its new one), the retained (relocated) directories restarts/worlds/<id>.a<k> and the
    current directory's attempt.json (its bytes bound) -> ({k: (directory or None, source)}, the current marker's
    attempt or None, its sha256). A restart recorded but interrupted before its new attempt was installed leaves
    the new attempt "not installed" and the failed one wherever it is (current, awaiting relocation, or moved)."""
    cur = wdir(root, wid)
    raw, sha = _read_once(os.path.join(cur, "attempt.json"))
    marker = None
    if raw:
        try:
            marker = int(json.loads(raw.decode("utf-8"))["attempt"])
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            marker = None
    elif os.path.isdir(cur):
        marker = 0                                        # (a first attempt has no attempt.json)
    recs = [r for r in restarts if r.get("world") == wid]
    ks = {int(r["failed_attempt"]) for r in recs if "failed_attempt" in r} | {int(r["attempt"]) for r in recs}
    rd = os.path.join(root, "restarts", "worlds")
    try:
        for name in os.listdir(rd):
            m = ATTEMPT_DIR_RE.match(name)
            if m and m.group("w") == wid:
                ks.add(int(m.group("k")))
    except OSError:
        pass
    if marker is not None:
        ks.add(marker)
    if not ks:
        return {0: (cur, "current")}, None, sha
    newest = max(ks)
    out = {}
    for k in sorted(ks):
        moved = os.path.join(rd, f"{wid}.a{k}")
        if marker == k:
            out[k] = (cur, "current" if k == newest else "awaiting relocation (its restart is recorded)")
        elif os.path.isdir(moved):
            out[k] = (moved, "retained")
        else:
            out[k] = (None, "not installed (its restart is recorded)" if k == newest else "missing")
    return out, marker, sha


def ecology(root, reg, horizons=None, reg_sha=None):
    """The read-only ecological export (Annex H D6 rules 22-26) over EVERY attempt of every registered slot (see
    the module doc). reg_sha: the sha256 of the registry bytes the caller loaded. -> the document."""
    sched = reg["schedule"]
    T, L = sched["total_steps"], sched["log_every"]
    bi = burn_in_of(reg)
    maxr = int(reg.get("max_restarts") or 0)
    if horizons is None:
        horizons = [h * 1_000_000 for h in ECO_HORIZONS_M if h * 1_000_000 <= T]
    horizons = sorted(set(int(h) for h in horizons) | {T})       # (the registered end is always the primary)
    inputs = {}
    for name in ("restarts.jsonl", "availability.jsonl"):
        p = os.path.join(root, name)
        raw, sha = _read_once(p)
        inputs[name] = {"bytes": len(raw or b""), "sha256": sha, "records": _jsonl_bytes(raw, p)}
    restarts, ledger = inputs["restarts.jsonl"]["records"], inputs["availability.jsonl"]["records"]
    slots = {}
    for w in reg["worlds"]:
        wid = w["id"]
        idx, marker, msha = attempt_index(root, wid, restarts)
        newest = max(idx)
        seeds = next((x["seeds"] for x in reg.get("reserved", []) if x["slot"] == w.get("seed_slot")), [w["founder_seed"]])
        atts = []
        for k in sorted(idx):
            d, src = idx[k]
            seq = attempt_sequence(root, wid, d, w, k, ledger, L)
            o = attempt_outcome(seq, w, total_steps(w, sched), bi)
            o.update(world=wid, attempt=k, seed=seeds[k] if k < len(seeds) else None, source=src, dir=d)
            rs = [r for r in restarts if r.get("world") == wid and int(r.get("failed_attempt", -1)) == k]
            if d is None and k == newest:                # (recorded, not yet installed: it will start)
                o.update(observation="ongoing", censor={"kind": "ongoing", "frame": base_frame(w)})
            if k < newest:
                rp = os.path.join(d, "relocated.json") if d else None
                rraw, rsha = _read_once(rp) if rp else (None, None)
                rel = {}
                try:
                    rel = json.loads(rraw.decode("utf-8")) if rraw else {}
                except (ValueError, UnicodeDecodeError):
                    pass
                o["evidence"]["relocated_sha256"] = rsha
                if src == "retained" and (rel.get("world") != wid or int(rel.get("attempt", -1)) != k):
                    o["integrity"].append(f"retained attempt {k}: its relocation manifest is missing or names another attempt")
                if d is None:
                    o["integrity"].append(f"attempt {k}: its directory is missing (neither current nor relocated)")
                o["restart_record"] = rs[0] if rs else None
                if not rs:
                    o["integrity"].append(f"attempt {k} was superseded without a restart record")
                if o["burn_in"] == "early_failure":
                    o["establishment"] = "restarted"
                    if rs and int(rs[0].get("zero_frame", -1)) != o["first_terminal"]["frame"]:
                        o["integrity"].append(f"its restart record's zero {rs[0].get('zero_frame')} is not the evidenced "
                                              f"first zero {o['first_terminal']['frame']}")
                else:
                    o["establishment"] = "restarted (no evidenced early zero)"
                    o["integrity"].append("restarted, but its evidence shows no zero before the burn-in frame")
                    if o["observation"] != "event":
                        o.update(observation="technical", censor={"kind": "technical", "frame": o["frontier"]})
            elif o["burn_in"] == "early_failure":
                o["establishment"] = "exhausted" if k >= maxr else "restart_pending"
            else:
                o["establishment"] = o["burn_in"]
            atts.append(o)
        slots[wid] = {"uuid": w["uuid"], "treatment": w["treatment"], "block": w.get("block"),
                      "seed_slot": w.get("seed_slot"), "retained_attempt": newest, "attempt_marker": marker,
                      "attempt_json_sha256": msha, "attempts": atts,
                      "exhausted": atts[-1]["establishment"] == "exhausted"}
    summary = {}
    for t in TREATMENTS:
        ws = [s for s in slots.values() if s["treatment"] == t]
        if not ws:
            continue
        N = len(ws)
        first = [s["attempts"][0] for s in ws]
        kept = [s["attempts"][-1] for s in ws]
        est = [o for o in kept if o["coexisting_through_burn_in"]]
        allatt = [o for s in ws for o in s["attempts"]]
        early = sum(1 for o in allatt if o["burn_in"] == "early_failure")
        resolved = early + sum(1 for o in allatt if o["burn_in"] == "established")
        summary[t] = {
            "registered_slots": N,
            "first_attempt": dict(survival=survival_table(first, N, horizons), **_times(first),
                                  label="PRIMARY: closed-population survival of every slot's first founder attempt "
                                        "(establishment failures included)"),
            "retained_attempt": dict(survival=survival_table(kept, N, horizons), **_times(kept),
                                     label="secondary: the retained attempt under the registered restart protocol"),
            "establishment_conditional": (None if not bi else dict(
                survival=survival_table(est, len(est), horizons), **_times(est),
                excluded=sum(1 for o in kept if not o["coexisting_through_burn_in"]),
                label="secondary: retained attempts evidenced coexisting THROUGH the burn-in frame (alive at it, no "
                      "terminal event at or before it; a zero exactly at it is data elsewhere, excluded here); "
                      "denominator: those attempts")),
            "attempts": {"started": sum(1 for o in allatt if o["samples"] or o["status"] != "pending"),
                         "early_failures": early, "resolved": resolved,
                         "early_failure_rate": early / resolved if resolved else None,
                         "established_slots": sum(1 for o in kept if o["establishment"] == "established"),
                         "exhausted_slots": sum(1 for s in ws if s["exhausted"]),
                         "unresolved_technical": sum(1 for o in allatt if o["observation"] == "technical"),
                         "unresolved_establishment": sum(1 for o in kept if o["burn_in"] == "unresolved"),
                         "refills": sum(1 for o in allatt if o["refill"])}}
        if t == "A":
            summary[t]["note"] = ("A's predators are fixed and immortal: their survival is structural, not evidence of "
                                  "demographic resilience comparable to C or B (D6 rule 22)")
    q200 = sorted(wid for wid, s in slots.items() if s["treatment"] == "C"
                  and s["attempts"][-1]["observation"] == "administrative" and not s["attempts"][-1]["refill"])
    return {"schema": ECOLOGY_SCHEMA,
            "registry_sha256": reg_sha or rqlib.sha256_file(os.path.join(root, "config", "worlds.json")),
            "tool_sha256": rqlib.sha256_file(os.path.abspath(__file__)),
            "evidence_sha256": rqlib.sha256_file(os.path.abspath(evidence.__file__)),
            "inputs": {k: {"bytes": v["bytes"], "sha256": v["sha256"]} for k, v in inputs.items()},
            "schedule": sched, "burn_in": bi or None, "max_restarts": maxr, "horizons": horizons, "primary_horizon": T,
            "slots": slots, "summary": summary,
            "Q200": {"worlds": q200, "count": len(q200), "h_pqft_available": len(q200) >= 24,
                     "note": "retained C histories coexisting through the observed registered end, without a refill; "
                             ">= 24 is the availability safeguard for H-P, H-Q, H-F and H-T only, not for H-C (D6 rule 26)"},
            "definitions": {
                "event": "the first evidenced SAMPLED zero (every log_every frames) over the newest line of descent's "
                         "validated, contiguous main-CSV samples (evidence.py); the extinction lies after previous_sample; "
                         "the first such zero is the first absorbing terminal boundary",
                "censoring": "administrative at the registered end; technical at the last verified observation; a "
                             "prey-terminal stop is a competing event, never predator extinction",
                "attempts": "each (slot, attempt, seed) has its own frame-zero origin; time is never concatenated across "
                            "attempts; an exhausted reservation is an establishment failure, not censoring"}}


def lineage_events(segments):
    """The chain's lineage events in order (evidence for C's breeder indicator; Annex H D6 rule 29), the breeder
    history CARRIED ACROSS SEGMENTS: segments [(name, start, rows [(frame, event, id, parent, age)], through)] ->
    [(frame, event, id, proven_breeder_at_the_event, ancestry_known, age)]. A proven breeder is the parent of at
    least one realized B event before the event; ancestry is known for a founder (F), a loaded (L), a refilled
    (R) or a born (B) id."""
    known, breeders, out = set(), set(), []
    for _, _, rows, _ in segments:
        for fr, ev, i, par, age in rows:
            if ev in ("F", "L", "R"):
                known.add(i)
            elif ev == "B":
                known.add(i)
                if par:
                    breeders.add(par)
            out.append((fr, ev, i, i in breeders, i in known, age))
    return out


def monitor_windows(samples, events, window, step, log_every, arm, lineage_through=None, dt=FRAME_DT, max_age=None):
    """D6 rule 29's rolling windows (a, b], b every `step`, a = b - window >= arm, by a chronological sweep: predator-
    seconds (the trapezoid of the sampled predator abundance x dt), exposure-weighted mean energy, captures (the
    corrected main-CSV kills_interval) and per predator-second, starvation deaths (C: from the lineage events, of
    PROVEN BREEDERS and of the others, per 1,000 predator-seconds; their mean age at death; the lifespan-
    normalized starvation hazard: starvation per predator-second x the registered max age), births minus deaths
    (C: lineage; B: the corrected main-CSV intervals), and the deterioration flag (breeder starvation > 0.1 per
    1,000 predator-s AND mean energy < 180). events: lineage_events or None (no lineage: the breeder indicator
    unavailable); lineage_through: the last frame they cover. -> [window rows]."""
    import bisect
    byf = {f: v for f, v in samples}
    out = []
    if not samples:
        return out
    ef = [e[0] for e in events] if events is not None else []
    first, last = samples[0][0], samples[-1][0]
    b = max(arm + window, first + window)
    b += (-b) % step                                      # (window ends on the step grid from frame 0)
    while b <= last:
        a = b - window
        pts = [byf.get(f) for f in range(a, b + 1, log_every)]
        if any(p is None for p in pts):
            b += step
            continue
        N = [p.get("predator_pop") or 0 for p in pts]
        E = [p.get("predator_avg_energy") for p in pts]
        expo = sum((N[i] + N[i + 1]) / 2 for i in range(len(N) - 1)) * log_every * dt
        ne = [N[i] * (E[i] if E[i] is not None else 0) for i in range(len(N))]
        energy = (sum((ne[i] + ne[i + 1]) / 2 for i in range(len(ne) - 1)) * log_every * dt / expo) if expo else None
        if any(E[i] is None and N[i] for i in range(len(N))):
            energy = None
        iv = pts[1:]
        caps = (sum(p["kills_interval"] for p in iv) if all(p.get("kills_interval") is not None for p in iv) else None)
        row = {"from": a, "to": b, "predator_seconds": expo, "mean_energy": energy, "captures": caps,
               "captures_per_predator_s": (caps / expo) if (caps is not None and expo) else None,
               "expenditure": None}
        if events is not None and lineage_through is not None and b <= lineage_through:
            ev = events[bisect.bisect_right(ef, a):bisect.bisect_right(ef, b)]
            starv = [e for e in ev if e[1] == "S"]
            unknown = any(not e[4] for e in starv)
            br = sum(1 for e in starv if e[3])
            ages = [e[5] for e in ev if e[1] in ("S", "A") and e[5] is not None]
            row.update(starvation=len(starv), breeder_starvation=None if unknown else br,
                       nonbreeder_starvation=None if unknown else len(starv) - br,
                       births_minus_deaths=sum(1 for e in ev if e[1] == "B") - sum(1 for e in ev if e[1] in ("S", "A")),
                       mean_age_at_death=(sum(ages) / len(ages)) if ages else None, deaths_with_age=len(ages))
            rate = (br / expo * 1000) if (expo and not unknown) else None
            row.update(breeder_starvation_rate=rate,
                       starvation_rate=(len(starv) / expo * 1000) if expo else None,
                       breeder_indicator="available" if rate is not None else
                       ("unavailable: a starved predator without lineage ancestry" if unknown else "unavailable: no exposure"))
            row["deterioration"] = bool(rate is not None and energy is not None and rate > MON_BREEDER_RATE
                                        and energy < MON_ENERGY)
        else:
            if all(p.get("predator_births_interval") is not None and p.get("predator_deaths_starv") is not None
                   and p.get("predator_deaths_age") is not None for p in iv):
                st_ = sum(p["predator_deaths_starv"] for p in iv)
                row.update(starvation=st_, starvation_rate=(st_ / expo * 1000) if expo else None,
                           births_minus_deaths=sum(p["predator_births_interval"] - p["predator_deaths_starv"]
                                                   - p["predator_deaths_age"] for p in iv))
            row.update(breeder_starvation_rate=None, deterioration=None, mean_age_at_death=None,
                       breeder_indicator="unavailable: no individual lineage log" if events is None
                       else "unavailable: past the lineage log's accepted frame")
        sr = row.get("starvation_rate")
        row["lifespan_normalized_starvation"] = (sr / 1000 * max_age) if (sr is not None and max_age) else None
        out.append(row)
        b += step
    return out


def bmd_5k(samples, events, log_every, lineage_through=None):
    """The 5k births-minus-deaths series (D6 rule 29): per sample interval (f - log_every, f], from the lineage
    events within their VERIFIED coverage (f <= lineage_through: #75 r2 P2-4, never a zero for missing events),
    else the corrected main-CSV intervals, else None (unavailable) -> [(frame, value)]."""
    import bisect
    ef = [e[0] for e in events] if events is not None else []
    out = []
    for f, v in samples:
        if events is not None and lineage_through is not None and f <= lineage_through:
            ev = events[bisect.bisect_right(ef, f - log_every):bisect.bisect_right(ef, f)]
            out.append((f, sum(1 for e in ev if e[1] == "B") - sum(1 for e in ev if e[1] in ("S", "A"))))
        elif all(v.get(c) is not None for c in ("predator_births_interval", "predator_deaths_starv", "predator_deaths_age")):
            out.append((f, v["predator_births_interval"] - v["predator_deaths_starv"] - v["predator_deaths_age"]))
        else:
            out.append((f, None))
    return out


def _episodes(rows, step):
    """Consecutive flagged windows merged: [{"first_to", "last_to", "windows", "max_rate", "min_energy"}]."""
    eps = []
    for r in rows:
        if not r.get("deterioration"):
            continue
        if eps and r["to"] - eps[-1]["last_to"] <= step:
            e = eps[-1]
            e.update(last_to=r["to"], windows=e["windows"] + 1, max_rate=max(e["max_rate"], r["breeder_starvation_rate"]),
                     min_energy=min(e["min_energy"], r["mean_energy"]))
        else:
            eps.append({"first_to": r["to"], "last_to": r["to"], "windows": 1, "max_rate": r["breeder_starvation_rate"],
                        "min_energy": r["mean_energy"]})
    return eps


def energy_tails(root, wid, frame, sha):
    """The archived individual predator energies' lower tail (D6 rule 29) at an accepted checkpoint (its bytes
    verified against its acceptance sha256) -> {"frame", "n", "min", "p05", "p10", "sha256"} or the reason."""
    p = good_copy(root, wid, frame, sha) if frame else None
    if not p:
        return {"frame": frame, "unavailable": "no verified copy of the latest accepted checkpoint"}
    try:
        cp = ckpt.load(p)
    except (ckpt.CheckpointError, OSError, ValueError) as e:
        return {"frame": frame, "unavailable": f"the checkpoint does not load: {e}"}
    en = sorted(float(x) for x, a in zip((cp.get("predators") or {}).get("energy") or [],
                                         (cp.get("predators") or {}).get("alive") or []) if int(a))
    if not en:
        return {"frame": frame, "unavailable": "no living predators", "sha256": sha}
    q = lambda u: en[min(len(en) - 1, int(u * len(en)))]  # noqa: E731
    return {"frame": frame, "n": len(en), "min": en[0], "p05": q(0.05), "p10": q(0.10), "sha256": sha}


def monitor(root, reg, window=MON_WINDOW, step=MON_STEP, reg_sha=None, windows_out=None):
    """The read-only production monitoring indicators (Annex H D6 rules 29-30) of every C and B world's current
    attempt over its evidence-bound sequence (see the module doc). windows_out: every rolling window and the 5k
    births-minus-deaths series of every world, as gzipped JSON lines (bound by sha256 in the document). -> doc."""
    import gzip
    sched = reg["schedule"]
    L = sched["log_every"]
    if window % L or step % L or window <= 0 or step <= 0:
        raise WorldsError(f"--window {window} and --step {step} must be positive multiples of log_every {L}")
    arm = burn_in_of(reg)
    p = os.path.join(root, "availability.jsonl")
    raw, sha = _read_once(p)
    ledger = _jsonl_bytes(raw, p)
    rraw, _ = _read_once(os.path.join(root, "restarts.jsonl"))
    restarts = _jsonl_bytes(rraw, os.path.join(root, "restarts.jsonl"))
    out, lines = {}, []
    for w in reg["worlds"]:
        wid, tr = w["id"], w["treatment"]
        if tr == "A":
            out[wid] = {"treatment": "A", "monitored": False,
                        "why": "A's predators are fixed (12, immortal): the <= 15 rule and the breeder indicator do not apply"}
            continue
        idx, marker, msha = attempt_index(root, wid, restarts)
        k = max(idx)
        d = idx[k][0]
        lin = tr == "C"
        seq = attempt_sequence(root, wid, d, w, k, ledger, L, lineage=lin)
        sm = [(f, dict(v)) for f, v in seq["samples"]]
        segs = {s["name"]: s for s in seq["state"].get("segments", [])}
        fixed = {}
        for e in seq["evidence"]["segments"]:            # (a resumed segment's first row: its loaded counters)
            s = segs.get(e["segment"])
            if s and s["start_frame"] > base_frame(w):
                ra = s.get("resumed_accept") or {}
                src = good_copy(root, wid, ra.get("frame"), ra.get("sha256")) if (ra and d == wdir(root, wid)) else None
                try:
                    fixed[s["start_frame"] + L] = ckpt.load(src)["counters"] if src else None
                except (ckpt.CheckpointError, OSError, ValueError):
                    fixed[s["start_frame"] + L] = None
        for i, (f, v) in enumerate(sm):
            if f in fixed:
                ctr = fixed[f]
                for col, key in INTERVAL_FIX:
                    if col in v:
                        v[col] = (v[col] - int(ctr.get(key, 0))) if (ctr and v[col] is not None) else None
        events, lt = None, None
        if lin and seq["lineage"]:
            events = lineage_events(seq["lineage"])
            lt = min(seq["accepted_through"], seq["lineage_through"])    # (the CONTIGUOUS verified lineage coverage)
        max_age = (w.get("flags") or {}).get("predator-max-age")
        rows = monitor_windows(sm, events, window, step, L, arm, lt, max_age=max_age)
        acute = [(f, v.get("predator_pop")) for f, v in sm if f > arm and v.get("predator_pop") is not None
                 and v["predator_pop"] <= MON_ACUTE]
        ce = sched["checkpoint_every"]
        summ = monitor_windows(sm, events, ce, ce, L, arm, lt, max_age=max_age)
        series = bmd_5k(sm, events, L, lt)
        for r in summ:                                   # (the 5k births-minus-deaths range inside each 1M)
            vals = [x for f, x in series if r["from"] < f <= r["to"] and x is not None]
            r["bmd_5k"] = {"min": min(vals), "max": max(vals), "n": len(vals)} if vals else None
        # (#75 r2 P2-5) the latest checkpoint ELIGIBLE under the line of descent, its cuts and the observation's
        # frontier (the first terminal, a refill or a stop): never a superseded or overshoot checkpoint
        fr_ = seq["obs"]["frontier"]
        elig = [c for c in seq["checkpoints"] if c[0] <= fr_]
        tails = (energy_tails(root, wid, elig[-1][0], elig[-1][1]) if (elig and d == wdir(root, wid))
                 else {"unavailable": "no accepted checkpoint of the current attempt within its observation"})
        if windows_out:
            lines += [rqlib.canonical(dict(r, world=wid, kind="window")) for r in rows]
            lines += [rqlib.canonical({"world": wid, "kind": "bmd_5k", "frame": f, "value": x}) for f, x in series]
        out[wid] = {"treatment": tr, "monitored": True, "attempt": k, "attempt_json_sha256": msha,
                    "frontier": seq["obs"]["frontier"], "lineage_through": lt,
                    "breeder_indicator": ("available" if lin and lt else
                                          ("unavailable: no accepted lineage log yet" if lin else
                                           "unavailable: no individual lineage log (B)")),
                    "acute": ({"first_frame": acute[0][0], "samples": len(acute), "min_predator_pop": min(x for _, x in acute)}
                              if acute else None),
                    "deterioration": _episodes(rows, step), "windows": len(rows),
                    "latest_window": rows[-1] if rows else None, "summaries": summ, "energy_tail": tails,
                    "expenditure": "unavailable: the engine does not log predator energy expenditure",
                    "age_at_death": "lineage events (C): mean_age_at_death per window" if lin else
                                    "unavailable: no individual lineage log (B)",
                    "refill": seq["obs"]["refill"], "evidence": seq["evidence"], "unsupported_ledger": seq["unsupported_ledger"]}
    wrec = None
    if windows_out:
        data = gzip.compress(b"".join(lines), mtime=0)
        rqlib.write_durable(windows_out, data)
        wrec = {"path": os.path.abspath(windows_out), "sha256": rqlib.sha256_bytes(data), "lines": len(lines)}
    return {"schema": MONITOR_SCHEMA,
            "registry_sha256": reg_sha or rqlib.sha256_file(os.path.join(root, "config", "worlds.json")),
            "tool_sha256": rqlib.sha256_file(os.path.abspath(__file__)),
            "evidence_sha256": rqlib.sha256_file(os.path.abspath(evidence.__file__)),
            "availability_sha256": sha, "window": window, "step": step, "armed_after": arm, "dt": FRAME_DT,
            "thresholds": {"breeder_starvation_per_1000_predator_s": MON_BREEDER_RATE, "mean_energy_below": MON_ENERGY,
                           "acute_predator_pop_at_most": MON_ACUTE},
            "windows_out": wrec,
            "consequences": "diagnostics, not calibrated extinction probabilities: a flag is recorded, verified and "
                            "notified; it never triggers rescue, reseeding, treatment, horizon or allocation changes, "
                            "extra worlds or selective assay omission (D6 rule 30)",
            "worlds": out}


# ================================================================== design block, status
BLOCK_EVIDENCE_SCHEMA = "finfolk.redqueen.blockevidence/1"
DISPOSITIONS = ("no_rule", "established", "exhausted", "restart_pending", "unresolved", "not_installed")
SETTLED = ("no_rule", "established", "exhausted")
ARCHIVE_STATUS = ("verified", "off_chain", "missing", "mismatch")


def attempt_uuid(base, k):
    """A restarted attempt's identity (as val_block.py's, refsel.py's and noisebank.py's): the registry uuid for
    attempt 0, else uuid5(NAMESPACE_URL, "finfolk:attempt:<registry uuid>:<k>") (another history)."""
    return base if not k else str(uuid.uuid5(uuid.NAMESPACE_URL, f"finfolk:attempt:{base}:{k}"))


def disposition(o, k, maxr, bi):
    """(decided, why, disposition) of a retained attempt's burn-in from its evidence (attempt_outcome; None: recorded
    but not installed): settled (no_rule, established: evidenced alive at the burn-in frame or its first zero at or
    after it, exhausted: an early failure with the restarts used up, the slot's final attempt) or not (a restart is
    due, unresolved: not yet evidenced alive at the burn-in frame, not_installed)."""
    if o is None:
        return False, f"attempt {k} is recorded but not installed (its restart is in progress)", "not_installed"
    b, first = o["burn_in"], o["first_terminal"]
    if b == "no rule":
        return True, "no burn-in rule", "no_rule"
    if b == "established":
        return True, (f"its first zero (frame {first['frame']}) is at or after the burn-in frame {bi}" if first else
                      f"evidenced alive at the burn-in frame {bi}"), "established"
    if b == "early_failure":
        if k >= maxr:
            return True, (f"an early failure (frame {first['frame']}) with its {maxr} restarts exhausted: the slot's "
                          "final attempt"), "exhausted"
        return False, (f"an evidenced zero at frame {first['frame']} before the burn-in frame {bi}: it will be "
                       "restarted"), "restart_pending"
    return False, (f"not yet evidenced alive at the burn-in frame {bi} (its evidence reaches frame {o['frontier']}, "
                   f"{o['observation']})"), "unresolved"


def archive_evidence(root, wid, k, d, seq):
    """An attempt's archive index, every object checked against the attempt's NEWEST LINE OF DESCENT and RE-HASHED
    (Codex #77 r1 P1-1) -> ({frame: {"label", "sha256", "path", "status", "why"}}, a problem or None). status:
    verified (F1, or a checkpoint whose acceptance record on the line of descent, within its cut, binds this
    sha256; its bytes hash to it), off_chain (archived, but no acceptance record on the line of descent binds it:
    a superseded continuation's, or not accepted yet), missing, mismatch (its bytes no longer hash to the record).
    F1 also records whether its replay verification (f1_verify.json) binds it to the first checkpoint."""
    if d is None:
        return {}, f"attempt {k} is recorded but not installed"
    try:
        recs = attempt_archive_records(root, wid, k)
    except (WorldsError, OSError, KeyError) as e:
        return {}, f"its archive index is unreadable ({e})"
    chain = {}
    for f, sha in seq["checkpoints"]:
        chain.setdefault(f, sha)
    fv_raw, _ = _read_once(os.path.join(d, "f1_verify.json"))
    try:
        fv = json.loads(fv_raw.decode("utf-8")) if fv_raw else {}
    except (ValueError, UnicodeDecodeError):
        fv = {}
    out, probs = {}, []
    for lab, r in recs.items():
        f, sha, p = r.get("frame"), r.get("sha256"), r.get("path")
        if not isinstance(f, int) or label_of(f) != lab or not isinstance(sha, str):
            probs.append(f"{lab}: a malformed archive record")
            continue
        e = {"label": lab, "sha256": sha, "path": p}
        if f == 1:
            e["replay"] = ("verified" if fv.get("identical") and fv.get("f1_sha256") == sha
                           and chain.get(fv.get("first_checkpoint")) == fv.get("first_checkpoint_sha256") else
                           "not recorded")
        elif chain.get(f) != sha:
            e.update(status="off_chain", why=("no acceptance record on the line of descent binds it (a superseded "
                                              "continuation's, or not accepted yet)" if f not in chain else
                                              "its record's sha256 is not the accepted checkpoint's"))
        if "status" not in e:
            got = None
            try:
                got = rqlib.sha256_file(p) if isinstance(p, str) and os.path.isfile(p) else None
            except OSError:
                pass
            if got is None:
                e.update(status="missing", why=f"{p} is missing")
            elif got != sha:
                e.update(status="mismatch", why=f"{p} does not hash to its record")
            else:
                e.update(status="verified", why=None)
        out[f] = e
    return dict(sorted(out.items())), ("; ".join(probs) if probs else None)


def design_block(root, reg, archive_root):
    """The worlds block (finfolk.redqueen.worldsblock/1, read-only) a design and graph.py mask bind: per registered
    slot its RETAINED attempt's EVIDENCE under evidence.py's rules (Annex H D6 rules 24 and 27; Codex #77 r1 P1-1;
    the same sequence as the ecological export): the registry uuid and the attempt's identity (attempt_uuid), the
    first absorbing terminal boundary (valid_before: the first evidenced sampled guild zero; snapshots at or after
    it are not valid challengers, design §2.3) and each guild's, the observation's frontier (first terminal,
    refill, stop), the explicit burn-in disposition (disposition: an unsettled attempt's snapshots are pending),
    every archived object checked against the line of descent and re-hashed (archive; "archived": the verified
    frames), and the bytes of the inputs read (registry, restart and availability ledgers, evidence.py)."""
    s = reg["schedule"]
    times = {"F1": 1}
    for f in range(s["checkpoint_every"], s["total_steps"] + 1, s["checkpoint_every"]):
        times[f"{f // 1_000_000}M" if f % 1_000_000 == 0 else f"f{f}"] = f
    L, bi, maxr = s["log_every"], burn_in_of(reg), int(reg.get("max_restarts") or 0)
    inputs = {}
    for name in ("restarts.jsonl", "availability.jsonl"):
        p = os.path.join(root, name)
        raw, sha = _read_once(p)
        inputs[name] = {"bytes": len(raw or b""), "sha256": sha, "records": _jsonl_bytes(raw, p)}
    restarts, ledger = inputs["restarts.jsonl"]["records"], inputs["availability.jsonl"]["records"]
    ws = {}
    for w in reg["worlds"]:
        wid = w["id"]
        idx, marker, msha = attempt_index(root, wid, restarts)
        k = max(idx)
        d, src = idx[k]
        seq = attempt_sequence(root, wid, d, w, k, ledger, L) if d else None
        o = attempt_outcome(seq, w, total_steps(w, s), bi) if seq else None
        arch, aprob = archive_evidence(root, wid, k, d, seq) if seq else ({}, f"attempt {k} is recorded but not installed")
        decided, why, disp = disposition(o, k, maxr, bi)
        first = o["first_terminal"] if o else None
        zeros = {g: z["frame"] for g, z in (o["events"] if o else {}).items() if isinstance(z, dict)}
        ad = adir(archive_root, wid)
        ws[wid] = {"uuid": w["uuid"], "attempt_uuid": attempt_uuid(w["uuid"], k), "treatment": w["treatment"],
                   "block": w["block"], "status": o["status"] if o else "pending", "attempt": k, "attempt_source": src,
                   "attempt_marker": marker, "attempt_json_sha256": msha,
                   "pattern": os.path.join(ad, "end.{frame}.json"), "paths": {"F1": os.path.join(ad, "F1.json")},
                   "valid_before": first["frame"] if first else None, "first_zeros": dict(sorted(zeros.items())),
                   "burn_in": {"decided": decided, "why": why, "disposition": disp},
                   "archived": [f for f, e in arch.items() if e["status"] == "verified"],
                   "archive": {str(f): e for f, e in arch.items()}, "archive_problem": aprob,
                   "evidence": {"frontier": o["frontier"] if o else base_frame(w),
                                "accepted_through": o["accepted_through"] if o else base_frame(w),
                                "first_terminal": first, "refill": o["refill"] if o else None,
                                "stop": o["stop"] if o else None, "observation": o["observation"] if o else "ongoing",
                                "unsupported_ledger": o["unsupported_ledger"] if o else [],
                                "sequence": o["evidence"] if o else None}}
    return {"schema": "finfolk.redqueen.worldsblock/1",
            "registry_sha256": rqlib.sha256_file(os.path.join(root, "config", "worlds.json")),
            "namespace": reg.get("namespace"), "times": times, "burn_in_frame": bi, "max_restarts": maxr,
            "evidence": {"schema": BLOCK_EVIDENCE_SCHEMA,
                         "evidence_sha256": rqlib.sha256_file(os.path.abspath(evidence.__file__)),
                         "tool_sha256": rqlib.sha256_file(os.path.abspath(__file__)),
                         "inputs": {n: {"bytes": v["bytes"], "sha256": v["sha256"]} for n, v in inputs.items()}},
            "worlds": ws}


def burn_in_report(root, reg):
    """The burn-in rule's restarts and, per treatment, the attempts and their outcomes: every restart is
    an early failure of the attempt it ended; a final attempt is an early failure when it ended extinct
    before the burn-in frame (its restarts exhausted), established when burn_in_decided says so (alive past
    the burn-in frame, or its first zero after it, or done), technically failed, pending (not started:
    outside every rate) or unresolved (running before the burn-in frame). The early-establishment
    failure rate = early failures / (early failures + established)."""
    led = restart_records(root)
    bi = burn_in_of(reg)
    per = {}
    for w in reg["worlds"]:
        p = per.setdefault(w["treatment"], {"worlds": 0, "restarts": 0, "attempts_started": 0, "early_failures": 0,
                                            "established": 0, "pending": 0, "unresolved": 0, "failed": 0,
                                            "failed_before_start": 0})
        p["worlds"] += 1
        r = sum(1 for x in led if x["world"] == w["id"])
        p["restarts"] += r
        p["attempts_started"] += r
        p["early_failures"] += r
        st = read_state(root, w["id"])
        if st["status"] == "failed":               # (technical status, reported separately)
            p["failed"] += 1
        if not st["segments"]:
            p["pending" if st["status"] != "failed" else "failed_before_start"] += 1
            continue
        p["attempts_started"] += 1
        # the establishment outcome first: it survives a later technical failure
        if st["status"] == "extinct" and "restarts exhausted" in str(st.get("end_reason")):
            p["early_failures"] += 1
        elif burn_in_decided(root, reg, w["id"])[0]:
            p["established"] += 1
        else:
            p["unresolved"] += 1
    for p in per.values():
        res = p["early_failures"] + p["established"]
        p["early_failure_rate"] = p["early_failures"] / res if res else None
    return {"burn_in": bi or None, "max_restarts": reg.get("max_restarts"), "restarts": led, "per_treatment": per,
            "definition": "an early failure: the earliest evidenced SAMPLED zero (log_every) before the burn-in frame"}


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
    r.add_argument("--layout", choices=sorted(LAYOUTS),
                   help="a named allocation (overrides --per-block): 64 is the registered one (Annex H D7 rule 34)")
    r.add_argument("--max-restarts", type=int, default=MAX_RESTARTS)
    for name in ("f1", "launch", "verify-f1", "stitch", "status", "design-block", "ecology", "monitor"):
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
        if name in ("design-block", "ecology", "monitor"):
            s.add_argument("--out", required=True)
        if name == "ecology":
            s.add_argument("--horizons", help="comma-separated frames (default: 5,20,30,50,100,150,200M within the "
                                              "schedule, and its end)")
        if name == "monitor":
            s.add_argument("--window", type=int, default=MON_WINDOW)
            s.add_argument("--step", type=int, default=MON_STEP)
            s.add_argument("--windows-out", help="every rolling window and the 5k births-minus-deaths series "
                                                 "(gzipped JSON lines; bound by sha256 in the document)")
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
            reg = register(a.arena, a.namespace, a.blocks,
                           LAYOUTS[a.layout] if a.layout else parse_per_block(a.per_block), a.avoid,
                           {"total_steps": a.total_steps, "checkpoint_every": a.checkpoint_every,
                            "log_every": a.log_every}, a.allow_placeholder, a.c_founders, a.burn_in,
                           a.max_restarts, a.layout)
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
        if a.cmd in ("ecology", "monitor"):              # (read-only: no lock; only --out is written)
            reg, sha = load_registry(root, allow_placeholder=a.allow_placeholder)
            if a.cmd == "ecology":
                hz = [int(x) for x in a.horizons.split(",")] if a.horizons else None
                doc = ecology(root, reg, hz, sha)
                for t, s in sorted(doc["summary"].items()):
                    prim = s["first_attempt"]["survival"][str(doc["primary_horizon"])]
                    print(f"{t}: {s['registered_slots']} slots; first-attempt predator survival at {doc['primary_horizon']}: "
                          + (f"{prim['estimate']:.3f}" if "estimate" in prim else f"bounds {prim['bounds']}")
                          + f" (counts {prim['counts']})", file=sys.stderr)
            else:
                doc = monitor(root, reg, a.window, a.step, sha, a.windows_out)
                for wid, v in sorted(doc["worlds"].items()):
                    if v.get("monitored") and (v["acute"] or v["deterioration"]):
                        print(f"FLAG {wid} ({v['treatment']}): acute {v['acute']}; deterioration episodes "
                              f"{len(v['deterioration'])}", file=sys.stderr)
            rqlib.write_durable(a.out, rqlib.canonical(doc))
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

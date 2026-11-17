# rec_A_v1: exact-graph recovery under the bank/D8 observation model (DRAFT)

DRAFT FOR OWNER/COORDINATOR ADOPTION, NOT FROZEN: A_design_v5.md §6.2's changes applied to
rec_C_v2's `recovery_runbook_v2.md` (94369c2c…); the coordinator adopts and freezes it with
the rec_A_v1 CRITERION. Its base text below describes rec_C_v2's verified server state
(main 7253fdf) where it is not changed.

Prepared for the coordinator. The old 2026-11-11 runbook is preserved in `ref/`.
This is a planning/measurement deliverable, NOT an accepted recovery result.
No production recovery was run. All created files are in this git-excluded BUILD.
No directional trend of any outcome across history time/snapshot age was
computed, inspected or reported; no bank assay outcomes were read.

## Verified state and ordering

See `verified_inputs.md` for the complete FOUND/MISSING/CHANGED table (full
paths and SHA-256), with `verified_inputs.json` as the machine-readable ledger.
The production registry is exactly
`1193b562fd7c6a202b1b4bd12edbc8ce3855ea60f39458e38845e8d359c61dde`:
64 worlds, eight 4C+2A+2B blocks, nine attempt seeds per slot, 576 unique
history-attempt seeds. `registry.verify.json` is present and agrees. The
registry avoidance hashes and nonempty seed sets were independently rechecked.

There is NO `~/finfolk/redqueen_2026/graph`, production `config/forks.json`,
production `config/references.json`, or production `registration/` directory.
The `rq_recovery/g*` graphs are historical graphs in another namespace, without
the current production-registry binding; other worktrees contain toy/test
fixtures. None is accepted as the missing production artifact.

For measurement only we built the intended production graph from copied
production registry bytes with the old runbook's exact topology choices:

```bash
PY="$PWD/build_recrun/venv/bin/python3"
T="$PWD/tools/redqueen"
nice -n 19 "$PY" -I -B "$T/graph.py" build \
  --registry "$PWD/build_recrun/inputs/worlds.json" \
  --namespace rq2026-d6d7-graph --snapshot-topup 6 --ab-topup 8 \
  --ab-topup-mode fitting --lag-probe 7 \
  --out "$PWD/build_recrun/inputs/graph"
```

It has 276,748 pairs and logical-edge SHA-256
`1eb07f3b61b47cc3d0ba4203c426cdfc2e297f11d79c1f11debe7ddb17560a03`.
Gzip SHA-256:
`459104bf062935e4eaacf1d4adc7d429fdf8929cb35ec3cb6b806707504affa8`.
Metadata SHA-256:
`5d8f18a195226ad307818c1a0156a3a318c6c55b37d529345b75532e733cef16`.
Production-root publication was not authorized and was not done. The coordinator
must adopt this intended graph before treating it as the production graph.
`prepare` reproduces it in P_REC, or copies/rechecks the production graph if
one has meanwhile been published. A changed graph needs a new freeze and a
revised resource estimate.

The old bank-plan path `plans/noisebank.pending.jsonl` is absent. The actual
reservation input is
`~/finfolk/redqueen_noisebank_2026/config/bank.plan.jsonl`, byte-identical to
`plans/2ce2bb7a71d01129a0c5317a159f91bfe3fcc1dc8a2edb51c40ba806fbae31f5.jsonl`.
There are 18,432 rows and 10,240 distinct extracted seeds, disjoint from all
576 history-attempt seeds. All 10,240 intentionally overlap the registry's
`reservations/noisebank.seeds.json` reservation; unrelated registry avoidance
sets have zero overlap. The old blanket assertion of bank/avoidance disjointness
would fail on these valid inputs. Bind and retain the bank's own reservation;
do not reject it or delete it to make the check pass.

## Bank/D8 inputs (A_design_v5 §7 steps 1-7; before prepare)

These server steps precede `rec_A_v1.sh prepare` (step 9). Record every command, its
exit and the sha256 of every output beside the step. All run with nice 19, one BLAS
thread and at most 2 workers in total beside the 64 histories; every output goes into
`$P_A/inputs/bank/` under the names `rec_A_v1.py` binds (D8_FILES), never into the
production root or the bank root (which `provenance` only reads).

```bash
P_A=${P_REC:-/home/harit/finfolk/work/recovery_A_v1}
PY="$PWD/build_recrun/venv/bin/python3"
T="$PWD/tools/redqueen"                  # the merged A tools (the snapshot prepare binds)
BANK_ROOT=/home/harit/finfolk/redqueen_noisebank_2026
IN="$P_A/inputs/bank"
LEDGER=...                               # the existing cumulative D5 CPU ledger (D8:289)
AGES=...                                 # the registered config/ages.json (6ffb99ec…, D8:51)
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export BLIS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1

# 1. The four bank inputs: read-only copies, re-hashed (= v5 §0.3: 64b113ce…,
#    6ffb99ec…, 2ce2bb7a…, 6559a8da…).
install -D -m 0444 "$BANK_ROOT/results/observations.json" "$IN/observations.json"
install -D -m 0444 "$AGES" "$IN/ages.json"
install -D -m 0444 "$BANK_ROOT/config/bank.plan.jsonl" "$IN/bank.plan.jsonl"
install -D -m 0444 "$BANK_ROOT/config/bank.design.json" "$IN/bank.design.json"
sha256sum "$IN/observations.json" "$IN/ages.json" "$IN/bank.plan.jsonl" "$IN/bank.design.json"

# 2. The provenance receipt (reconstruction-bound, v5 §2.2; charged to the D5 ledger).
nice -n 19 "$PY" -I -B "$T/noisebank.py" provenance --study "$BANK_ROOT" \
  --design "$IN/bank.design.json" --plan "$IN/bank.plan.jsonl" \
  --obs "$IN/observations.json" --out "$IN/provenance.json" --ledger "$LEDGER"
  # (add --manifest M when gate 8's verified continue.sha256 is available, v5 §2.2 item 4)

# 3. The validation spec (v5 §2.10); witness its digest, with the tool hashes, in an
#    authentic immutable dated external log BEFORE step 4; keep the receipt as
#    $IN/d8validation.witness.receipt (rec_A_v1 checks that it names the digest).
nice -n 19 "$PY" -I -B "$T/noisebank.py" d8-validation-spec \
  --design "$IN/bank.design.json" --out "$IN/d8validation.spec.json"
sha256sum "$IN/d8validation.spec.json" "$T"/*.py

# 4. The prospective validation V1-V5 (10 banks + 2 contrasts + V5; ≈14.5 CPU-h).
nice -n 19 "$PY" -I -B "$T/noisebank.py" validate-d8 --spec "$IN/d8validation.spec.json" \
  --design "$IN/bank.design.json" --out "$IN/d8validation.report.json" --ledger "$LEDGER"
# 4b. Recheck ledger_total with step 4's measured cost; re-project the refit and the
#     remaining D5 work before step 5 (v5 §7 step 4b).

# 5. The D8 refit: bank_d8.json and its receipt (the receipt is written first).
nice -n 19 "$PY" -I -B "$T/noisebank.py" estimate-d8 --obs "$IN/observations.json" \
  --ages "$IN/ages.json" --design "$IN/bank.design.json" --plan "$IN/bank.plan.jsonl" \
  --provenance "$IN/provenance.json" --validation-report "$IN/d8validation.report.json" \
  --out "$IN/bank_d8.json" --receipt "$IN/bank_d8.receipt.json" --ledger "$LEDGER" --boot 999

# 6. Adoption: the noise-fit review (Codex, read-only) and the mandatory #68 conformance
#    gate T5-4 / T1-6 / T5-5 against the pinned #68 commit with the engine-field change
#    (pr68_engine_field_spec_v2.md). Keep the gate's receipt (commit, outputs; it names
#    bank_d8.json's sha256) as $IN/pr68_conformance.receipt and record the adoption.

# 7. The observation tables (v5 §1.7, §1.7b; with the certification record).
nice -n 19 "$PY" -I -B "$T/recovery.py" obs-tables --bank "$IN/bank_d8.json" \
  --noise-scales 1,2 --out "$IN/obs_tables.npz"
sha256sum "$IN"/*
```

Two operational qualifications (WP3's review of the D8 commands) bind these steps:

- **Ledger ordering is set here.** The D8 accounting lock (an exclusive flock on the
  ledger file, held for each D8 command's whole transaction) serializes D8 commands
  only: #68's `ledger_add` takes no lock. Budget-sensitive D5 (#68) work and the D8
  steps 2, 4 and 5 on the shared ledger are therefore ordered by this runbook and
  never run concurrently; run `noisebank.py d8-reconcile --ledger "$LEDGER"` after any
  hard interruption before the next budget-dependent command.
- **The refresh spacing is not established at R = 64.** The D8 commands refresh their
  in-progress attempt record every 30 CPU-s; the spacing was measured (maximum
  31.04 CPU-s) on R = 6 / 16 banks only, not at the registered R = 64.

Step 8, the measurement-only benchmark, is `rec_A_v1.sh measure` (below, Execution);
step 9 adopts the rec_A_v1 CRITERION with the CPU plan re-derived from it and runs
`rec_A_v1.sh prepare`.

## Prepare and the witness

Before prepare:

1. Coordinator/owner adopts the draft criterion, interpolation/reference-grid
   policy, nine-case attrition allocation, graph topology and planning-reference
   qualification. Resolve the bank/D8 scope blocker below for any unqualified
   ACCEPTED claim. Criteria may be edited prospectively, never after outcomes.
2. The registry, its verification/avoidance inputs, actual bank plan and bank
   provenance files must exist with their verified bytes. Optional `EXTRA_AVOID`
   is a file listing additional absolute reservation paths, one per line.
   rec_A_v1 copies the list to `inputs/extra_avoid.list` and every listed file
   into `inputs/reservations/`, binds them in `FROZEN.sha256`, includes them in
   the collision checks and passes them to the fork registration; a listed file
   that is missing is refused. Export the same `EXTRA_AVOID` for `measure` and
   `prepare`: the copied inventory is immutable, so a different one is refused.
   #84's general reservation-loader fix is a separate tracked gate; this job
   does not certify it or replace its required owner review.
3. The offline Python/NumPy runtime, main-7253fdf tools, this wrapper/helper,
   criterion and supplied design/Annex/D8/gate documents must remain available.
4. A production graph/fork registry need NOT be written outside P_REC first:
   absent inputs are generated as explicitly labelled intended graph and fork
   PLANNING registry inside P_REC, using the copied registry and actual
   reservation files. These are not registered production evidence. Later
   production registration must use identical topology and fork identities.
   If actual forks already exist, they are copied and rechecked instead.
5. References are currently absent. The script freezes assumed slot times
   `(0,20,60,100,120,140,180,200)` and sentinel identities. This is allowed by
   design:404 only subject to deterministic later relabelling. A topology or
   support change requires recovery/refreezing. If actual references appear,
   this server-specific wrapper refuses prepare rather than incompletely bind
   their selection-time `studies_checked` dependencies; inventory those inputs
   in a newly reviewed wrapper. The merged CLI itself supports actual panels.

The fork-planning API call has this exact supported CLI equivalent (after
snapshots/avoidance checks, all outputs still inside P_REC):

```bash
AVOID=(--avoid "$C/inputs/bank/bank.plan.jsonl"
       --avoid "$C/inputs/study/config/worlds.json")
while IFS= read -r p; do AVOID+=(--avoid "$p"); done < <(
  "$PY" -I -B -c 'import json,sys; print(*json.load(open(sys.argv[1])),sep="\n")' \
    "$C/inputs/avoid_paths.json")
nice -n 19 "$PY" -I -B "$T/forks.py" register \
  --study "$C/inputs/study" --splits "$C/inputs/graph/graph.meta.json" \
  --namespace rq2026-d6d7-replay "${AVOID[@]}" \
  --out "$C/inputs/study/config/forks.json"
```

Here C/PY/T mean the same paths defined below. This produces 144 main branches
plus six pilot branches. It plans seeds/identities, never launches branches.

`prepare` then snapshots all non-test `tools/redqueen/*.py`, copies raw inputs
and all reservation provenance, derives graph/fork planning inputs, freezes
legacy configurations using `recovery.prepare_run` (no observations), and calls
companion `prepare` for all extra cases. It binds wrapper/helper/criterion,
all authorities, graph raw+logical identities, registry/verification, forks,
reference slots, reservations, runtime versions, Python executable and installed
NumPy/library bytes in the top-level `FROZEN.sha256`. rec_A_v1 also copies the
bank/D8 inputs read-only into `P_REC/inputs/bank/` and binds them, snapshots the
tools with `obslaw.py`, `material.py`, `common.py`, `noisescale.py` and
`fixtures/registered_ages.json`, prepares every legacy configuration and extra
plan in bank mode, and writes the frozen `SCHEDULE.json` (A_design_v5 §3.8,
clarification 4 F1). Nothing is generated in the
production root or noise bank. Existing conflicting bytes require a NEW P_REC.

Only after prepare may the coordinator witness the digest of the TOP-LEVEL
`FROZEN.sha256` in an authentic immutable dated external log, retaining the
receipt as `P_REC/PRIOR.receipt`. A local digest or hand-written receipt does
not independently prove chronology. Nested extra freezes are already bound by
the top-level freeze. Run never manufactures the receipt. The top-level
`FROZEN.sha256` binds the bank inputs, the D8 artifact (with its receipt, the
provenance receipt, the validation spec, report and witness receipt, and the
observation tables), the #68 conformance receipt and the measurement-only
benchmark (its inputs and outputs, listed in `MEASUREMENT_ONLY.sha256`). Its
deadline is before the first ACCEPTANCE dataset (namespace
rq2026-d8-recovery-A1): the one dataset generated before it is the
measurement-only benchmark (A_design_v5 §7 step 8; CRITERION C6).

## Source-checked commands: all cases

Use the FROZEN copies, not tools from a moving checkout:

```bash
C=${P_REC:-/home/harit/finfolk/work/recovery_A_v1}
PY="$PWD/build_recrun/venv/bin/python3"
T="$C/tools/redqueen"
G="$C/inputs/graph/graph.jsonl.gz"
NS=rq2026-d8-recovery-A1
JOBS=${JOBS:-2}                         # two workers in total beside the 64 histories
REFARGS=()                             # this server: assumed slots, explicitly frozen
FIT=(--ranks 4 --lambdas 0.01,0.02,0.05,0.2 --iters 30 --start both)
BANK=(--obs-model bank --bank "$C/inputs/bank/bank_d8.json" --obs-tables "$C/inputs/bank/obs_tables.npz")
COMMON=(--graph "$G" "${REFARGS[@]}" --namespace "$NS" --fitter registered)
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export BLIS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
```

The literal commands below are the expansion of the wrapper's frozen
`SCHEDULE.json`; loops enumerate every named case, not unspecified datasets.
Run all commands with nice 19 (the wrapper enforces it). The wrapper uses
`--scenarios` to avoid implicit stress-halving rules.

```bash
nice -n 19 "$PY" -I -B "$T/recovery.py" conditioning \
  --graph "$G" "${REFARGS[@]}" --out "$C/conditioning.json"

# Main: five scenarios x20, both legacy procedures (100 datasets, 200 procedures).
nice -n 19 "$PY" -I -B "$T/recovery.py" run "${COMMON[@]}" "${FIT[@]}" \
  --options a,fwd --basis 6 --embedding shared --center references \
  --scenarios r0,r1_017,r1_034,r2_017,r2_034 --reps 20 --jobs "$JOBS" "${BANK[@]}" \
  --out "$C/runs/main"

# Each stress case is exactly 10 datasets, both legacy procedures.
for s in r0_asym r2_034_asym r0_twoway r2_034_clustered r0_ownworld \
         r2_034_noisy r1_017_noisy r2_017_noisy; do
  nice -n 19 "$PY" -I -B "$T/recovery.py" run "${COMMON[@]}" "${FIT[@]}" \
    --options a,fwd --basis 6 --embedding shared --center references \
    --scenarios "$s" --reps 10 --jobs "$JOBS" "${BANK[@]}" --out "$C/runs/stress_$s"
done

# Four noiseless numerical cases, option a; source chooses true-rank continuation.
for s in num_r1 num_r2 num_r3 num_r4; do
  nice -n 19 "$PY" -I -B "$T/recovery.py" run "${COMMON[@]}" "${FIT[@]}" \
    --options a --basis 6 --embedding shared --center references \
    --scenarios "$s" --reps 1 --jobs "$JOBS" "${BANK[@]}" --out "$C/runs/numerical_$s"
done

# Four sensitivities: complete five-scenario x20 main ensemble for each.
for b in 4 8; do
  nice -n 19 "$PY" -I -B "$T/recovery.py" run "${COMMON[@]}" "${FIT[@]}" \
    --options a,fwd --basis "$b" --embedding shared --center references \
    --scenarios r0,r1_017,r1_034,r2_017,r2_034 --reps 20 --jobs "$JOBS" "${BANK[@]}" \
    --out "$C/runs/basis$b"
done
nice -n 19 "$PY" -I -B "$T/recovery.py" run "${COMMON[@]}" "${FIT[@]}" \
  --options a,fwd --basis 6 --embedding separate --center references \
  --scenarios r0,r1_017,r1_034,r2_017,r2_034 --reps 20 --jobs "$JOBS" "${BANK[@]}" \
  --out "$C/runs/separate"
nice -n 19 "$PY" -I -B "$T/recovery.py" run "${COMMON[@]}" "${FIT[@]}" \
  --options a,fwd --basis 6 --embedding shared --center train_c \
  --scenarios r0,r1_017,r1_034,r2_017,r2_034 --reps 20 --jobs "$JOBS" "${BANK[@]}" \
  --out "$C/runs/train_c"

# Summaries are outside legacy result directories.
for id in main basis4 basis8 separate train_c \
          stress_r0_asym stress_r2_034_asym stress_r0_twoway \
          stress_r2_034_clustered stress_r0_ownworld stress_r2_034_noisy \
          stress_r1_017_noisy stress_r2_017_noisy \
          numerical_num_r1 numerical_num_r2 numerical_num_r3 numerical_num_r4; do
  nice -n 19 "$PY" -I -B "$T/recovery.py" summarize \
    --dir "$C/runs/$id" --out "$C/summaries/$id.json"
done
```

Each new intact procedure gets its own frozen directory. These `prepare`
commands execute BEFORE the top-level freeze and generate no observations.
They share the legacy main namespace/scenario/rep identities. `run` and
`summarize` execute only AFTER the external witness:

```bash
for op in interp fwd_all fwd_early; do
  nice -n 19 "$PY" -I -B "$T/recovery_extra.py" prepare \
    --graph "$G" "${REFARGS[@]}" --namespace "$NS" --options "$op" \
    --cases intact --scenarios r0,r1_017,r1_034,r2_017,r2_034 --reps 20 \
    "${FIT[@]}" --basis 6 --embedding shared --center references "${BANK[@]}" \
    --out "$C/extra/$op"
done
# AFTER WITNESS. Each invocation accepts only 1 or 2 workers.
for op in interp fwd_all fwd_early; do
  nice -n 19 "$PY" -I -B "$T/recovery_extra.py" run \
    --dir "$C/extra/$op" --graph "$G" "${REFARGS[@]}" --jobs 2 "${BANK[@]}"
  nice -n 19 "$PY" -I -B "$T/recovery_extra.py" summarize \
    --dir "$C/extra/$op" --out "$C/summaries/extra-$op.json"
done
```

The shell loop above is the wrapper's order: at most 2 concurrent workers in
total beside the 64 histories (JOBS=1 or 2). Legacy runs are sequential
invocations with at most JOBS workers; they never overlap the extra stage. The
extra stages run one directory at a time at `--jobs 2` (JOBS=1: `--jobs 1`),
attrition last. Any other bank/recovery job must fit within the same two workers.

```bash
# BEFORE FREEZE: nine synthetic attrition recipes, one r0 replicate per case.
nice -n 19 "$PY" -I -B "$T/recovery_extra.py" prepare \
  --graph "$G" "${REFARGS[@]}" --namespace "$NS" \
  --options a,interp,fwd_all,fwd_early \
  --cases biological_at,biological_after,technical,pending_prefix,pending_attempt,mixed,roots0,roots1,roots2 \
  --scenarios r0 --reps 1 "${FIT[@]}" --basis 6 --embedding shared \
  --center references "${BANK[@]}" --out "$C/extra/attrition"
# AFTER WITNESS:
nice -n 19 "$PY" -I -B "$T/recovery_extra.py" run \
  --dir "$C/extra/attrition" --graph "$G" "${REFARGS[@]}" --jobs 2 "${BANK[@]}"
nice -n 19 "$PY" -I -B "$T/recovery_extra.py" summarize \
  --dir "$C/extra/attrition" --out "$C/summaries/extra-attrition.json"
```

Cases use the source's identity-only selected worlds: biological exclusions
from 100M / 100.005M, technical loss only at 50M, pending prefix after 120M,
validation pending attempt, combined case, and zero/one/two primary test roots.
These are diagnostics on identical synthetic observations, not observations of
production attrition or attrition power experiments. The fixture names refer
to primary test roots. On this graph roots0/1/2 retain 46/47/48 interpolation
roots and 40 forward-transfer roots; their forward intersections have 0/1/2.
The script enforces withholding wherever a BRANCH has fewer than two roots,
not indiscriminately by fixture name.

Counts: legacy 580 noisy datasets with two procedures +4 numerical datasets;
extra 300 intact single-procedure tasks +9 attrition tasks with four options.
Total 893 task files, 1,500 nominal procedure-equivalents, including four
numerical procedures. Main/sensitivities and the extra procedures reuse the
same synthetic identities; these are NOT 893 independent noise realizations.

## Every merged-tool flag checked at 7253fdf

| Tool/behavior | Source locations (repository-relative, unchanged main bytes) |
|---|---|
| graph build: `--out --namespace --registry --snapshot-topup --ab-topup --ab-topup-mode --lag-probe`; no layout flag | `tools/redqueen/graph.py:1217–1225`; registry binding `:196–206`; deterministic gzip `:619–632` |
| graph report: `--graph --out` | `graph.py:1226–1228` |
| fork register: `--study --splits --namespace --out --avoid` | `forks.py:794–807`; defaults/planning generation `:102–174` |
| recovery conditioning: `--graph --out --references` | `recovery.py:1413–1417` |
| recovery bench: `--graph --iters --references` | `recovery.py:1411–1423`; bench implementation `:1395–1405` |
| legacy run: `--graph --namespace --fitter --options --ranks --lambdas --iters --start --basis --embedding --center --out` | `recovery.py:1419–1442` |
| legacy `--scenarios --set --reps --jobs` | `recovery.py:1443–1447`; explicit scenario reps and numeric singleton `:1172–1184` |
| legacy summarize `--dir --out` | `recovery.py:1451–1453`; identities `:1134–1167`; denominator `:1247–1257` |
| no-observation legacy config freeze (Python API, not an invented CLI flag) | `recovery.py:1150–1167` (`prepare_run`) |
| numerical continuation (CLI grid does not override it) | `recovery.py:960–993` |
| extra prepare: `--graph --references --namespace --options --cases --scenarios --reps --ranks --lambdas --iters --start --basis --embedding --center --out` | `recovery_extra.py:1088–1104`; prepare `:569–592` |
| extra run: `--dir --graph --references --jobs` | `recovery_extra.py:1105–1113`; 1/2 cap `:898–900` |
| extra summarize: `--dir --out` | `recovery_extra.py:1114–1116`; full scheduled denominator `:984–1082` |
| interpolation; attrition; all/early masks and branches | `recovery_extra.py:101–185`, `:227–311`, `:623–743` |
| primary criterion, unavailable and unresolved decisions | `recovery.py:745–867`, `:1247–1257`; extra criterion `recovery_extra.py:50–62`, `:1050–1082` |

Line intervals above identify flag declarations, not nonexistent combined
flags. The runbook passes `--obs-model bank --bank --obs-tables` to every
`recovery.py run` and `recovery_extra.py prepare` / `run` (A_design_v5 §3.2,
§3.4; the line citations above are rec_C_v2's at 7253fdf), and uses no graph
`--layout`, no new legacy interpolation flag and no companion `--jobs` above 2.

## Criterion, D8 and unresolved acceptance scope

`CRITERION.txt` is the complete adoption draft; read it in full before prepare.
It quotes the design verbatim and labels C1–C6 as coordinator choices.
Core: >=16/20 SEPARATELY in r1_034 and r2_034, option a, ranks0..4; unavailable
is unsuccessful. Report Wilson95, do not demand its lower endpoint exceed .80.
The separate {0,1,2} results do not replace the frozen full-rank criterion.
Interpolation/all-reference/early-reference runs must all complete and be
reported separately. No new 80% threshold for them is asserted to be registered.
Sensitivity realization counts and one-r0 attrition allocation are prospective
choices. Numerical finite-error completion is checked, but no undocumented
quantitative numerical-RMSE pass tolerance is invented; scientific review must
assess the retained numerical/conditioning diagnostics before ACCEPTED status.

D8 file SHA-256 is
`566966e9c42952ab1699c47c520b2f61f91afd0228d9f0185be7cd7d027f92c9`, matching
the gate tracker prefix. Rules43–45 change survival materiality/calibration
scales, not the 1.7/3.4% capture-recovery scenarios or the 16/20 operational
choice. Rule46 changes generated calibration survival support/law; rules48/51
change recording/provenance; rule52 preserves the retained w12 diagnostic
world, not authority to exclude it from recovery. Rule53 explicitly keeps
accepted actual-production-graph recovery PRELAUNCH; the later numerical
calibration deadline is no waiver. The amendment's own candidate heading is
historical; the supplied coordinator instruction and tracker establish its
frozen status. Bind full bytes, not a guessed new text.

Timing and seal: D9 (`amendment_D9_launch_before_registration.md`, sha256
6bff8134…) launched the 64 histories before registration, so accepted
exact-graph recovery is a gate before outcome access (D9:21), its evidence
requirement unchanged (D8:327; D9:33). The seal, in full (CRITERION, TIMING AND
SEAL): tooling tests, performance measurements and program existence do not
substitute. Until the registration is deposited and its timestamp verified, no
assay of any history checkpoint is run (time-shift, bank-style or any other
scoring of capture, survival, q, C/B) and no outcome of any kind is computed,
inspected or reported (D9:22-26). Permitted meanwhile: engine-health and protocol
monitoring as the design's monitoring rules define it, and the
prospective-integrity guard (no directional time trend of any outcome). This
recovery reads no history outcome: only synthetic truths, the bank by hash, and
frozen graph/registry metadata; no bank or recovery quantity is reported by
snapshot time. Failures delay outcome access; preserve all failed runs, immutable
inputs and receipts; do not inspect main outcomes to choose a repair (D:713).

Bank/D8 scope implemented and frozen (A_design_v5.md); planning mode is refused by
the wrapper.

The acceptance packet is produced by `recovery.py packet --mode acceptance
--schedule SCHEDULE.json` (A_design_v5 §3.8), not by wrapper code; the wrapper
writes and freezes `SCHEDULE.json` at prepare.

## Execution, resume and logs

Use `tools/redqueen/rec_A_v1.sh` together with `rec_A_v1.py`, the adopted
CRITERION, the authorities and this worktree's merged tools. P_REC defaults
outside production to `/home/harit/finfolk/work/recovery_A_v1`. Every write goes there, including tmp,
locks, logs, configs, results and manifests. Protected production/bank and
repo/src/bin/validation*/fable roots are refused, as are output symlinks.
The venv itself lives in BUILD as explicitly requested for this job.

```bash
cd /home/harit/finfolk/work/trees/rq-recovery-run
export PY="$PWD/build_recrun/venv/bin/python3"
export P_REC=/home/harit/finfolk/work/recovery_A_v1
export AUTHORITY_DIR=...   # the authorities rec_A_v1.py binds (AUTHORITIES)
# export EXTRA_AVOID=...   # optional (Before prepare, item 2); the same for measure and prepare
# Step 8 (before the criterion's adoption): the measurement-only benchmark.
JOBS=1 nice -n 19 bash tools/redqueen/rec_A_v1.sh measure
# Step 9: adopt the criterion/graph/scope with the re-derived CPU plan and retain
# the dated adoption record, then:
export CRITERION=...       # the adopted rec_A_v1 CRITERION text
JOBS=2 nice -n 19 bash tools/redqueen/rec_A_v1.sh prepare
sha256sum "$P_REC/FROZEN.sha256"
# Step 10: witness this digest externally before any acceptance dataset in P_REC.
# Set WITNESS_RECEIPT to the authentic downloaded/log receipt path, then:
install -m 0444 "$WITNESS_RECEIPT" "$P_REC/PRIOR.receipt"
# Step 11: beside the histories; ends with recovery.py packet --mode acceptance.
JOBS=2 nice -n 19 bash tools/redqueen/rec_A_v1.sh run
```

These are coordinator commands, not commands run in this measurement job.
With other bank/recovery workers active, reduce JOBS so the combined total is
<=2. All BLAS libraries are capped at1 thread. Preflight conservatively requires
8GiB headroom +4GiB per worker, and 50GiB free disk +10GiB recovery allowance;
compare the measured plan and actual server load first.

Reissue the identical phase command to resume. Prepare checks an existing
freeze; it does not refreeze changed inputs. Legacy results retain their tool
configuration/identity checks; companion results also verify canonical body
hashes and scheduled tasks. The wrapper's retained-result hash manifest rejects
changed previously retained bytes. Per-invocation logs and `wait4` timing
records (JSON: exit, wall and user/system CPU seconds, maximum RSS) are under
`logs/` and `timing/`; status records the attempt and exit code;
`ARTIFACTS.sha256` inventories produced files. A process-group cleanup reaps
workers on TERM/INT, and a child that exits abnormally (a recovery supervisor
killed alone, say) has the rest of its process group stopped before the wrapper
goes on or releases its lock. An exclusive P_REC lock prevents overlapping invocations.
That cleanup is bounded, and two cases escape it. If members of a group survive
SIGKILL past the wait, the wrapper reports an INTEGRITY error naming the group,
exits 2 and still releases its lock. If the wrapper itself is hard-killed
(SIGKILL), its legacy supervisor and workers can keep running: legacy workers
have no parent-death protection. An available lock or an exit 2 is therefore not
evidence that earlier workers are gone. Before resuming after a wrapper hard kill
or an exit-2 integrity error, confirm that no recovery supervisor or worker
started for this P_REC is still running (`ps -eo pid,pgid,args | grep -F
"$P_REC"`, and the groups the error names), and stop any that are before
reissuing the command.
Do not change runtime/tools/criterion or share an output root between freezes.
A reboot or power loss leaves no worker running, but resume after one, like resume
after a wrapper hard kill, still depends on durable files and the merged tools'
checks; the external witness and immutable failed attempts must be preserved.

## Measurements and resources

The measurement-only benchmark (A_design_v5 §7 step 8; CRITERION C6's exception)
replaces rec_C_v2's 622.28 CPU-s figure: `rec_A_v1.sh measure` runs one complete
r2_034 dataset (options a,fwd) in bank mode with the frozen tools and the adopted
artifact, in namespace rq2026-d8-recovery-A1-measure, and records only
completion, timing, RSS and unresolved-integration counts
(`P_REC/measure/MEASUREMENT.json`, bound by prepare as measurement-only). The CPU
plan is re-derived from it at JOBS=2 (A_design_v5 §7: 1,500 procedure units, two
workers in total beside the 64 histories) before the CRITERION is adopted. The
48CPU-hour design allowance and old 193CPU-hour guess are not bounds on this
expanded matrix. Extra procedures/variant-specific runtimes and contention beside
the histories remain unmeasured and must be labelled as extrapolation, not
observed capacity.

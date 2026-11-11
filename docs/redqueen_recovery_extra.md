# Frozen recovery extensions

`tools/redqueen/recovery_extra.py` is an additive companion to the registered
recovery tooling. It preserves `recovery.py`, `map.py`, `graph.py`, `sealing.py`,
`forks.py`, `refsel.py`, and `rqlib.py`, including their provenance hashes,
defaults, serializers, and RNG behavior. No engine or Wasm rebuild is required
for these Python, shell-test, and documentation additions.

This tool uses scenario planning noise. It does not implement or claim
production-bank calibration. The partition algorithm, reference-grid access,
attrition recipes, and acceptance operationalization below are prospective
operational choices requiring coordinator adoption before scientific recovery.
Implementation tests establish mechanical coverage only.

## Operational rules

1. Keep the historical runbook and its frozen artifacts unchanged.
2. Keep graph build without `--layout`; retain `sealing.py manifest --layout 64` with complete forks/references.
3. Freeze the new interpolation rule, reference-grid access policy, attrition schedule, acceptance operationalization, tools, and inputs before scientific recovery.
4. Witness the digest of the new `FROZEN.sha256` in the coordinator’s immutable dated log before `run`. Local hashes alone do not establish chronology.
5. Continue the existing numerical checks through legacy `recovery.py`; the companion intentionally refuses noiseless scenarios. Their registered continuation remains unchanged.
6. Use separate output directories for every basis/embedding/centring sensitivity.
7. Report assumed reference slots versus actual reference assignments and planning noise versus bank calibration explicitly.
8. Do not remove the old runbook’s deliberate failure exit merely because code exists. Replace its missing-tooling blocker list only after the required new runs are frozen, completed, summarized, and reviewed.
9. Failure delays sealing; it does not weaken the acceptance criterion.
10. Completing these implementation gates establishes tooling readiness, not empirical recovery success or permission to seal/launch.

These rules follow design v4 sections cited in the implementation plan
(reference provenance 404; sensitivity 604, 651, 674; recovery 695–715;
chronology 768; forward analysis 785), Annex H 1638 and 1671–1675, the historical
recovery runbook 15–17, 57–60, 306–323, and 418–432, and PR body map 119.
The graph itself already enforces eight randomized blocks of 4C + 2A + 2B;
there is no missing graph-build layout flag.

## Interface

```bash
python3 -I -B tools/redqueen/recovery_extra.py prepare \
  --graph GRAPH/graph.jsonl.gz \
  --namespace rq2026-d6d7-recovery-v1 \
  --options a,interp,fwd_all,fwd_early --cases intact \
  --scenarios r0,r1_017,r1_034,r2_017,r2_034 --reps 20 \
  --ranks 4 --lambdas 0.01,0.02,0.05,0.2 --iters 30 --start both \
  --basis 6 --embedding shared --center references --out RUN

# Witness FROZEN.sha256 before run.
python3 -I -B tools/redqueen/recovery_extra.py run \
  --dir RUN --graph GRAPH/graph.jsonl.gz --jobs 2
python3 -I -B tools/redqueen/recovery_extra.py summarize \
  --dir RUN --out RUN/summary.json
```

Supply `--references references.json` to both `prepare` and `run` when actual
assignments are available. Otherwise the legacy configuration records assumed
slot times, with the same prelaunch qualification and deterministic later
relabelling requirement. The plan binds actual reference bytes and times when
supplied; identities must be sentinel references, separate from main/fork
identities.

`prepare` generates no observations. It freezes scientific settings, the pair
partition, attrition recipes, graph and reference identities, production Python
source hashes, runtime versions, resolved legacy configuration, and scheduled
task identities. A registered 64-world layout and production graph quotas are
required. A graph explicitly marked `recovery_toy` additionally requires
`--allow-toy`; its reduced topology cannot supply production recovery evidence.

`run` accepts no scientific overrides. It verifies graph, metadata, references,
sources, runtime, and frozen recipe before starting one or two workers. Each
worker uses one BLAS thread. An advisory directory lock serializes prepare/run.
Completed result identities and body hashes are verified before resume; valid
results are retained byte-for-byte, missing tasks are run, and changed inputs,
stray results, or mismatched result identities/body hashes are refused. Existing
conflicting frozen/output bytes require a new directory. Operational timing
stays in logs; legacy elapsed-time behavior is unchanged.

`summarize` retains missing and unavailable realizations in scheduled
acceptance denominators, reports Wilson 95% intervals, availability, selected
ranks, restricted-rank availability, and reasons, and never authorizes sealing.
It may summarize incomplete runs, which are explicitly marked incomplete.

## Procedures and access

- `a` calls the existing registered `recovery.procedure` on retained indices.
  The intact case is the existing procedure.
- `interp` is a separate 80/10/10 fit over ordinary global non-support ordered
  population pairs. SHA-256 identity ordering assigns floor(0.8N) to training,
  floor(0.1N) to validation, and the remainder to test. All replicates, horizons,
  and condition versions of a pair stay together. References and declared
  support remain fitted calibration; within-world families remain outside the
  Level-1 fit. Primary world/snapshot access arrays remain unchanged.
- `fwd_all` and `fwd_early` use the same new forward procedure and preserve the
  legacy main-outcome, validation, and test time/world masks. Reference rows,
  including the reference grid, are external calibration. `fwd_all` accesses
  all selected references. `fwd_early` accesses only reference rows whose
  reference endpoints are all at most 120M. This grid-access choice is
  prospective. Legacy `fwd` remains unchanged and separately identifiable.
- Both forward procedures restrict ordinary prey controls to at most 120M.
  `fwd_all` also permits late external prey-reference controls; `fwd_early`
  excludes them. Explicit control masks pass through `any_fit(..., ctrl=...)`.
- Existing guards and unresolved-integral handling remain in force. Zero or
  one contributing test root cannot succeed. Two roots meet only the count
  guard; they do not establish identifiability or power. Unresolved validation
  or selected/rank-zero test integrals withhold a decision.

## Frozen synthetic attrition

Cases use `finfolk.redqueen.recoverysyntheticcase/1`. They never manufacture a
production worlds block, graph mask, archive hash, or evidence record. Those
production formats require registry bindings and evidence absent from synthetic
fixtures. World choices use identities/topology only, never observations.

| Case | Frozen rule |
| --- | --- |
| `intact` | No exclusions |
| `biological_at` | Chosen training-C world: exclude frames ≥100,000,000 |
| `biological_after` | Same world: exclude frames ≥100,005,000 |
| `technical` | Second chosen training-C world: exclude only its 50M snapshot |
| `pending_prefix` | Third chosen training-C world: retain through 120M; later snapshots pending |
| `pending_attempt` | Chosen validation-C world: every snapshot pending |
| `mixed` | Combine biological_at, technical, pending_prefix, pending_attempt |
| `roots0` | All test worlds pending |
| `roots1` | Retain one deterministically chosen contributing test root; other test worlds pending |
| `roots2` | Retain two such roots; other test worlds pending |

At the first guild-zero boundary the snapshot is excluded; only snapshots
before it remain valid. Biological, technical, and pending exclusions use the
existing precedence. Diagnostics report treatment, world, endpoint times,
cause, scheduled/evaluable targets, access, centering, conditioning, and roots.

Every scenario/replicate/case task simulates the entire scheduled graph with
the same observation seed. Cases therefore receive identical underlying
observations for that scenario/replicate. Masks remove access without changing
RNG draws or node indices. Results hash the common observations and report both
scheduled interaction energy and retained additive-projection energy. Attrition
can change retained energy; these are not re-normalized effect-size power
experiments.

The attrition realization count is not registered. Freeze it prospectively.
One `r0` realization per case using all four procedures is a bounded mechanical
check allocation, not attrition power validation. A larger attrition-power
allocation requires its own frozen count and measured budget. The design's
48 CPU-hours is an estimate; historical smoke timings used a different graph
and tool version. Budget claims must use measured fresh-implementation timings.

## Seeds, artifacts, and acceptance

| Stream | Rule |
| --- | --- |
| Observations | `derive_seed(namespace, "recovery", scenario, rep)` |
| Survival | Existing `default_rng([seed, 2])` |
| Interpolation order | `derive64(namespace, "recovery-interpolation-v1", prey_key, predator_key)` |
| Attrition identity order | `derive64(namespace, "recovery-attrition-v1", category, world_id)` |
| Fit starts/bootstrap | Existing recovery seed and offsets |

The two new subkeys are prospective synthetic-analysis namespace extensions,
not engine reservations. Founder, replay, reference, and assay reservations
remain separate.

```text
RUN/plan.json
RUN/diagnostics.json
RUN/FROZEN.sha256
RUN/results/<case>.<scenario>.<rep:03d>.json
RUN/logs/<case>.<scenario>.<rep:03d>.log
RUN/ARTIFACTS.sha256
RUN/summary.json                         # when requested
```

Scientific JSON uses `rqlib.canonical`: sorted keys, ASCII, finite JSON numbers,
trailing newline. New outputs omit legacy `seconds` fields. A negative-infinite
crossed bound becomes the string `"-Infinity"` and cannot succeed; NaN or
positive infinity fails the task. Each result embeds the SHA-256 of its canonical
body. `FROZEN.sha256` indexes plan/diagnostics. The plan binds raw graph, metadata,
and reference hashes, logical graph identity, all production Python sources,
and resolved legacy configuration. `ARTIFACTS.sha256` indexes completed results
and frozen inputs. Record actual generated digests; local hashing alone cannot
prove that a freeze preceded scientific work.

The prospective acceptance operationalization is at least 16/20 successes
separately for `r1_034` and `r2_034`, intact case, option `a`, ranks 0–4, with
unavailable realizations unsuccessful. Success retains the existing positive
selected-rank and positive crossed-lower-bound rule. Wilson intervals are
reported; their lower endpoint need not exceed 0.80. This is a prospective
operational choice requiring coordinator adoption, not a verbatim design rule.
The companion marks this criterion applicable only on a non-toy graph with 20
realizations, all main scenarios, and the complete registered settings shown
above. Passing mechanical tests does not test this scientific criterion.

## Missing intact-graph procedures

Use the same namespace and scenario/replicate identities as the legacy runs.
`REFARGS` is either empty or `(--references references.json)`.

```bash
"$PY" -I -B "$T/recovery_extra.py" prepare \
  --graph "$G" "${REFARGS[@]}" \
  --namespace rq2026-d6d7-recovery-v1 \
  --options interp,fwd_all,fwd_early \
  --cases intact \
  --scenarios r0,r1_017,r1_034,r2_017,r2_034 \
  --reps 20 --ranks 4 \
  --lambdas 0.01,0.02,0.05,0.2 --iters 30 --start both \
  --basis 6 --embedding shared --center references \
  --out "$C/extra/main"

# Witness the frozen digest before this command.
"$PY" -I -B "$T/recovery_extra.py" run \
  --dir "$C/extra/main" --graph "$G" "${REFARGS[@]}" --jobs 2

"$PY" -I -B "$T/recovery_extra.py" summarize \
  --dir "$C/extra/main" --out "$C/extra/main/summary.json"
```

## Implementation gates

Use a fresh native-serial `evo_boids`, an offline venv whose isolated Python can
import NumPy, one BLAS thread, nice 19, and at most two parallel jobs. Run every
`tools/redqueen/test_*.py` sequentially with `-I -B -W error::ResourceWarning -v`.
Require NumPy via `RQ_REQUIRE_NUMPY=1`; graph, recovery_extra, refsel, noisebank,
forecast, and probes must not silently skip. Then sequentially run
`tests/redqueen_tooling.sh`, `tests/redqueen_worlds.sh`, and
`tests/redqueen_forks.sh` with `PYTHON` pointing to that venv and
`RQ_TEST_WORKERS=2`. Worlds/forks preserve their historical default worker
counts (3/4), and tooling preserves its default 10. Fixed one/two-worker
launches remain unchanged. Finish with `git diff --check` and verify all seven
protected production modules unchanged against `82ba348`. Leave changes
uncommitted for the coordinator. Stop at the first failing gate; a
multiprocessing socket restriction is SANDBOX-BLOCKED for outside rerun.

The new tests use the registered 64-world allocation/splits with deliberately
reduced assay topology, actual reference times 0,20,60,100,140,140,180,200M,
and explicit toy metadata. They check partition disjointness and primary
immutability; all/early centering and control access; observation perturbation
invariance; attrition boundaries and root guards; intact-primary equivalence;
unresolved-score withholding; serial/two-worker byte identity; hash validation,
resume, tampering, changed references, stray results, and acceptance denominators.

Brief 01, PR 1: exact Ocean FlowState extraction

Base: `e3c46aeff27dea8ceade9747eb1ec0f43957005c`, branch `brief01-pr1`.
Changes are intentionally uncommitted for the coordinator. All required acceptance gates passed; the table below records commands, exits, elapsed validation time and logs.

`src/ocean/ocean_transport.hpp` owns `FlowState` (`CurrentField`, three wave trains and `FlowCache`), the copied `TransportParams`, explicit-frame clock/cache preparation, and the extracted flow evaluators and synchronous food transport kernel. `OceanWorld` retains its readers and transport probes as wrappers, with public `Flow`, `Taper` and `FoodSteps` aliases. Its canonical flow state remains owned by the world. Preview fish/predator current reads also use the explicit-state wrappers.

The transport kernel accepts equal-sized input/output spans and caller-owned index scratch. In-place and disjoint buffers share the same implementation. Walls retain four-lane batches and scalar tails; E1 retains sample/wrap/clamp even for zero velocity; preview retains its original additions and wrap. Eye output starts with input contrast and changes it only when depth compares unequal. Expiry, spawning, grids, fish work, compaction and RNG draw order retain their original positions.

The 58 moved function bodies were mechanically compared against BASE after substituting the explicit state/parameters/frame and removing whitespace/comments: no arithmetic or branch differences. This supports the identity proof; the every-step fingerprints and unchanged baseline matrix are the numerical gate. `CurrentField` is copied as a complete C++ value, including `gyreA_`, `gyreOmega_`, `gyreT_`, vortices and centres. Mutable cache vectors have independent storage. Only existing immutable static flow tables are shared. Helper prewarming belongs to PR 2; this PR launches no helper.

`tools/ocean_fingerprint.hpp` changes private-member access and layout mirrors only. Existing current/wave tags still work, the new state has its own layout tripwire, and hash field order/version/contents are unchanged. The existing scalar flow-lane test reads its cache through the new state. No scheduling, helper, browser source, configuration, preset, numerical lineage or fingerprint change was introduced.

`tests/ocean_transport_tests.hpp` adds first-reader checks at frame zero, first enable after an update, on/off/on with direct wave speed/band/gravity edits, explicit future and frame-zero advancement, construction/assignment copy isolation for every mutable cache vector, whole-current gyre copying, and in-place/separate scalar-reference food transport (empty stock, 1–9 and 15–17 items, eligibility holes, both current modes, walls/E1/preview/off, multiple timesteps, changed/unchanged eye contrast). The original non-wall gyre `currentAt()` early return intentionally does not prepare waves. `tests/ocean_transport_fault.py` plants defects only in disposable source copies, requires successful compilation before counting detection, restores clean sources and reruns the clean suite.

Heavy commands run at nice 19; compiler concurrency is capped at two. The requested FAST command uses `JOBS=2`. The final full run uses `JOBS=1 BUILD_JOBS=2`: this harness runs native and Wasm simultaneously inside each case job, so one pair bounds active simulation processes to two. Emscripten commands first source `~/opt/emsdk/emsdk_env.sh`, then export a writable cache copied to `build_b01/em_cache`, set `EMCC_CORES=1`, and run with `LDFLAGS`, `CMAKE_PREFIX_PATH`, `SFML_DIR`, `CPPFLAGS`, and `CXXFLAGS` unset. No network, Git mutation, rebaseline or performance measurement is part of this work. Gate durations below are validation elapsed time only.

**Gate results**

| Command | Exit | Seconds | Local log |
|---|---:|---:|---|
| `python3 build_b01/audit_extraction.py` | 0 | 0.469 | `build_b01/extraction-audit.log` |
| `g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I build_b01/base/src build_b01/base/tools/ocean_parity_driver.cpp -o build_b01/base_driver` | 0 | 30.589 | `build_b01/identity-build-base-plain.log` |
| `g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -DEVO_OCEAN_EYE -I build_b01/base/src build_b01/base/tools/ocean_parity_driver.cpp -o build_b01/base_driver_eye` | 0 | 30.441 | `build_b01/identity-build-base-eye.log` |
| `g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I ./src ./tools/ocean_parity_driver.cpp -o build_b01/head_driver` | 0 | 27.346 | `build_b01/identity-build-head-plain.log` |
| `g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -DEVO_OCEAN_EYE -I ./src ./tools/ocean_parity_driver.cpp -o build_b01/head_driver_eye` | 0 | 29.957 | `build_b01/identity-build-head-eye.log` |
| `IDENTITY_JOBS=1 python3 build_b01/identity.py` | 0 | 826.791 | `build_b01/identity.log` |
| `bash build_b01/head_freshness.sh` | 0 | 59.916 | `build_b01/head-final-binary-equality-r2.log` |
| `python3 tests/ocean_transport_fault.py --out build_b01/mutations-plain` | 1 | 479.268 | `build_b01/mutations-plain.log` |
| `python3 tests/ocean_transport_fault.py --only waves_off --only cur_advanced --out build_b01/mutations-clocks` | 0 | 285.925 | `build_b01/mutations-clocks.log` |
| `python3 tests/ocean_transport_fault.py --eye --only eye_contrast --out build_b01/mutations-eye` | 0 | 271.240 | `build_b01/mutations-eye.log` |
| `FAST=1 JOBS=2 BUILD_JOBS=2 KEEP_OUT=1 bash wasm/ocean_parity.sh` | 0 | 1588.371 | `build_b01/parity-fast.log` |
| `bash build_b01/module_repeat.sh` | 0 | 35.389 | `build_b01/ocean-module-repeat.log` |
| `node tests/ocean_turbo_handoff.js` | 0 | 311.277 | `build_b01/turbo.log` |
| `npm ci --offline --cache "$PWD/build_b01/npm_cache" --no-audit --no-fund && npx --offline tsc -p tsconfig.json` | 0 | 6.773 | `build_b01/offline-types.log` |
| `bash wasm/build_site.sh` | 0 | 1.044 | `build_b01/site.log` |
| `git diff --exit-code e3c46ae -- src/core src/app src/render wasm/evo_wasm.cpp wasm/build_wasm.sh wasm/wasm.cmake CMakeLists.txt CMakePresets.json 'web/evo_boids*'` | 0 | 0.009 | `build_b01/classic-untouched.log` |
| `git diff --exit-code e3c46ae -- tests/ocean_baseline tests/fixtures` | 0 | 0.010 | `build_b01/baselines-fixtures-untouched.log` |
| `git diff --check` | 0 | 0.023 | `build_b01/diff-check.log` |
| `APP_TWINS=all BODY_TWINS="all cases except life_cap_fixture_s1" JOBS=2 BUILD_JOBS=2 bash wasm/ocean_parity.sh` (initial run) | interrupted; no exit receipt | unrecorded | `build_b01/parity-full.log` |
| `APP_TWINS=all BODY_TWINS="all cases except life_cap_fixture_s1" JOBS=1 BUILD_JOBS=2 bash wasm/ocean_parity.sh` (expanded by `build_b01/full_parity.sh`) | 0 | 4437.534 | `build_b01/parity-full-r2.log` |
| `bash build_b01/final_scope_checks.sh` (Classic/baseline/fixture diffs, source/artifact checksums, whitespace, status) | 0 | 0.051 | `build_b01/final-scope.log` |

The full command receipts, including the unsetting of narrowing variables and all earlier test/harness corrections, are in `build_b01/gates.jsonl`. The first mutation runner exit 1 is its own anchor error after six successful defect detections; see the mutation table and correction record.

FAST passed: 49/49 baseline cases, 15/15 appearance twins, 7/7 body-plan twins, 166/166 refused-config checks, 26/26 live refusal checks, both removed-nonfinite guards, and fixture parity. Artifacts are retained at `/tmp/ocean_parity.3AyCXk`.

Full parity passed: 124/124 baseline cases, 124/124 appearance twins, 122/122 eligible body-plan twins, all config/refusal/non-finite guards, repeatability, and body fixture parity. Body selection names every case except `life_cap_fixture_s1`; the harness also automatically skips `app_patterns_s1`, whose appearance mode cannot support body preview. The fixture is unchanged: 127 bodies, 572 samples, digest `b9f6510154e9b597`. All four unit runs passed: 94 plain tests and 101 eye tests, each with byte-identical native/Wasm printed output. These include `flow_readers` (616 checks), `flow_state` (118), `transport_food` (11,173 plain / 11,174 eye), and the existing `wall_advect4`. Full artifacts are retained at `/tmp/ocean_parity.diMp3b`.

The initial full run stopped after reporting all 124 baseline cases and all 124 appearance twins passing, with only part of the body-twin stage complete; its incomplete artifacts remain at `/tmp/ocean_parity.Ll3jNX`. It is not counted as a passing gate. The fresh full run above completed with exit 0.

**Mutation results**

Every mutant compiled successfully and its focused native test exited 1. All mutations were confined to disposable source copies. Clean controls exited 0; the clock and eye batches also reran the restored clean suite afterward. The real worktree was never mutated by this runner.

| Planted defect | Failing detector | Failures | Local log |
|---|---|---:|---|
| Evaluator reads live `OceanWorld::frame` through an injected bridge instead of target 123 | `flow_state` | 10 / 118 | `build_b01/mutations-plain/live_frame.log` |
| Zero sampled E1 velocity skips transport | `transport_food` wrap/clamp fixture | 1 / 11173 | `build_b01/mutations-plain/zero_e1.log` |
| Mutable `yRot` vector has shared storage | `flow_state` copy isolation | 6 / 118 | `build_b01/mutations-plain/shallow_yrot.log` |
| Current copy drops `gyreA_` | `flow_state` actual derived gyre values/flow | 2 / 118 | `build_b01/mutations-plain/drop_gyreA.log` |
| Current copy drops `gyreOmega_` | `flow_state` actual derived gyre values/flow | 2 / 118 | `build_b01/mutations-plain/drop_gyreOmega.log` |
| Current copy drops `gyreT_` | `flow_state` actual derived gyre values/flow | 2 / 118 | `build_b01/mutations-plain/drop_gyreT.log` |
| Waves advance while disabled | `flow_readers` paused-clock checks | 31 / 616 | `build_b01/mutations-clocks/waves_off.log` |
| Omit `curAdvanced` | `flow_state` explicit-target/frame-zero checks | 20 / 118 | `build_b01/mutations-clocks/cur_advanced.log` |
| Keep stale eye contrast after depth changes | `transport_food`, eye build | 1821 / 11174 | `build_b01/mutations-eye/eye_contrast.log` |

The first six executions and their clean control are in `build_b01/mutations-plain.log`. That runner invocation exited 1 on its subsequent ambiguous wave-clock anchor (a harness error, detailed below). After fixing that anchor, the remaining two clock mutants and clean controls passed the mutation protocol in `build_b01/mutations-clocks.log` (runner exit 0). The eye mutation and clean controls passed in `build_b01/mutations-eye.log` (runner exit 0). Source copies were restored between mutants and at the end.

**BASE versus HEAD identity**

29 workloads compare initialization and every update, without `--sparse`: 104,000 simulated updates per variant. Full stdout is identical, including fingerprint sections, RNG, chains, appearance/body sections when present, counters, final diagnostics and non-finite scans. The run uses separate processes, so each owner has its own RNG stream.

The unchanged `walls_bigtank_s9` recipe ran for 1,000 steps with 2,000 founders in 3840 × 2160 × 240. Additional seed-9 and seed-42 Big-tank runs each ran 10,000 steps. The spread includes default preview, food-drifting eddies and gyre, E1 preset with bounded and toroidal sensing, live waves/deep-current edits, wall eddies/gyre/shallow/small worlds, lifetime, eye capture/eye-only, codes 0/4/7/16/31 and cloak toggles. Every recipe is frozen in `build_b01/identity/recipes.json`; each BASE/HEAD trace and result is beside it. Summary: `build_b01/identity.log`.

The final source was recompiled with the original identity build's exact source-path spellings; both plain and eye executables are byte-identical to the executables used for these traces (`build_b01/head-final-binary-equality-r2.log`). An initial extra binary comparison used different include/source path spellings, changing embedded assertion paths and the ELF build ID; correcting the validation command made the full binaries identical, without a source change.

**Test-only corrections during development**

The first incomplete-extraction compile identified the existing `flow_lanes` test's private `OceanWorld::flow_` accessor; it now reads the same cache through `FlowState`. Before acceptance runs, a new generic copy-test assignment (`a[0] = {}`) was corrected to an explicitly typed value for GCC vector aggregates. The focused runtime gate then needed two test-only corrections: (1) its fixture used out-of-range `currentDrift=300`; it now uses 30 and immediately throws on refused initialization; (2) its expectation incorrectly required non-wall gyre `currentAt()` to prepare waves; the BASE implementation's early return does not, and the expectation now checks that original behavior. The failed logs are retained. No simulation change was made to accommodate these expectations. The mutation runner also stopped on an ambiguous wave-clock anchor after six mutants had been caught; the anchor was restricted to `advanceFlowClock`, and the remaining clock mutants were rerun with clean controls before and after.

**Committed Ocean artifacts**

Two clean-environment `bash wasm/build_ocean.sh` invocations produced identical bytes (`sha256sum -c` and `cmp`, both files). No pin file was edited.

| Artifact | SHA-256, both builds |
|---|---|
| `web/evo_ocean.wasm` | `709023fe385e348f7d8b7211fd27adae480562d64cfd50a0dd1e12d60a170702` |
| `web/evo_ocean.js` | `8bdce72bd8991c6e88768712b60cec9b7dd0cf22335d82ebe67f40cef6d91059` |

Toolchain: GCC 15.2.0, Emscripten 6.0.4 (`fe5be6afdff43ad58860d821fcc8572a23f92d19`), Node 26.13.0, npm 11.20.0, pinned TypeScript 5.6.3. See `build_b01/toolchain.log` and `build_b01/ocean-first.sha256`.

**Proposed coordinator commit split**

1. Source: `src/ocean/ocean_transport.hpp`, `src/ocean/ocean_world.hpp`, `tools/ocean_fingerprint.hpp`, `tests/ocean_tests.cpp`, `tests/ocean_transport_tests.hpp`, `tests/ocean_transport_fault.py`, and this report. Suggested subject: `ocean: extract explicit flow state and synchronous transport`.
2. Generated ST module: `web/evo_ocean.js` and `web/evo_ocean.wasm`. Suggested subject: `wasm: rebuild Ocean after FlowState extraction`.

The coordinator supplies the repository's required attribution trailer when committing. Do not commit `build_b01/`, other build outputs, or `dist/`; do not edit any pin file. Logs, reference documents, scripts and full trace outputs remain local under `build_b01/` for review.

**Review round 1 (against committed `533a841`)**

Both P3 findings are fixed. `checkCopy` now accepts `FlowState&`; an explicitly constructed copy tests construction, and the assigned object is inspected directly. Diagnostics identify the operation. The new `assignment_yrot` mutant preserves deep copy construction but shares mutable `yRot` storage on assignment. It compiled and failed `flow_state` (4/118 checks, first: `assignment yRot aliases or was dropped`); clean controls passed before and after. Disposable sources were restored, and all 77 C++ source files matched the current tree afterward.

A whole-tree caller search, including `tools/` and `wasm/`, supported removing 28 unused private forwarders, their private vector alias, and the world's unused `kWallFoodMaxSubsteps`. Execution helpers and `kPiF` remain; both public sections are byte-identical to `533a841`. Audit logs: `build_b01/review_round1/{forwarder-usage,public-compatibility}.txt`.

The requested gates passed in order. Commands ran at nice 19, with at most two jobs and four threads; Wasm shells sourced emsdk before setting the in-tree `EM_CACHE`, with native variables unset and `EMCC_CORES=1`. Logs below are under `build_b01/review_round1/`; exact commands/exits/durations are in `build_b01/gates.jsonl`.

| Command / check | Result | Seconds | Log |
|---|---|---:|---|
| `python3 tests/ocean_transport_fault.py --only assignment_yrot --out build_b01/review_round1/mutation-plain` | exit 0; mutant caught, restored controls pass | 191.141 | `mutation-plain.log` |
| `bash build_b01/review_round1/units.sh` | exit 0; 94 plain / 101 eye tests, native == Wasm full output | 1401.382 | `units.log` |
| `FAST=1 JOBS=2 BUILD_JOBS=2 KEEP_OUT=1 bash wasm/ocean_parity.sh` | exit 0; 49/49 baselines, 15/15 appearance twins, 7/7 body twins, all guards, fixture and four unit runs | 1570.880 | `parity-fast-r2.log` |
| `bash build_b01/review_round1/modules.sh` (two `build_ocean.sh` builds) | exit 0; both files repeat exactly and equal `533a841` | 40.578 | `modules.log` |
| `node tests/ocean_turbo_handoff.js` | exit 0; 556/556 checks | 318.928 | `turbo.log` |
| `python3 build_b01/review_round1/identity.py` (initial) | exit 1; own harness compared host timings on stderr | 125.374 | `identity.log` |
| Same identity command, corrected once | exit 0; 10/29 workloads, 30,000 updates per revision | 290.289 | `identity-r2.log` |

The earlier incomplete FAST log had no exit receipt and is not counted; the complete rerun is retained at `/tmp/ocean_parity.P46LE9`. The identity harness's first failure had identical deterministic stdout; only elapsed time and steps/second differed. One own-test correction normalizes those two stderr fields, retaining step/population counts and every other diagnostic. The rerun rebuilt BASE `e3c46ae` and the fixed worktree, compared full stdout from initialization and every step (`--trace`, no `--sparse`), and compared stderr with only timing normalized. All matched. Recipes/results/traces are retained beside the logs. Workloads: `def_s1`, `eddies_s11`, `e1_preset_s42`, `e1_live_s21`, `e1_gyre_s13`, `walls_e1_s42`, `walls_gyre_s13`, `walls_live_s21`, `eye_e1_capture_s17`, `eye_walls_e1_capture_s17`; these cover plain/eye, walls, E1 waves and deep current.

Ocean JS/Wasm hashes remain the values recorded above; no generated artifact, pin or baseline change is needed. Proposed single coordinator commit: `ocean: check assignment isolation directly and remove unused private wrappers`, containing `src/ocean/ocean_world.hpp`, `tests/ocean_transport_tests.hpp`, `tests/ocean_transport_fault.py`, and this report, with the coordinator's attribution trailer. No commit was made.

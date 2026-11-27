Genome v2 PR 2 builder report — 2026-11-23

## Round 5 — 2026-11-27

Status: **COMPLETE with recorded environment exclusions.** Integration base is now `4bafeb25bca62c4c3a628d97ed70d781f79a6168`, supplied pristine at `build_g2pr2/base_4bafeb2/`. Earlier rounds below retain their historical bases and stopped results. All Round 5 work remains uncommitted; no network, baseline, pin, backup, external tree, or supervisor operation is authorized or performed.

**Integration audit (file:line).** `build_g2pr2/logs/r5_integration_audit.json` records passing byte comparisons:

- `tests/ocean_turbo_handoff.js:5430` retains `genomeV2World`; `:5463` retains its registration and both v2 Turbo profiles. Removing only these additions reproduces the approved base suite byte for byte, including main's new `ocean_inspector.js` / `ocean_tour.js` loader at `:686`.
- `web/types.d.ts:131` retains the four optional actual-policy exports; `:260` retains `WorldNow.policy`. Removing only these additions reproduces all of main's declarations, including Inspector (`:1216`) and Tour (`:1291`), byte for byte.
- `web/ocean_inspector.js:353` correctly handles `n.kind === "Bias"` as `Bias (+1)` before the existing Sense/Action/hidden cases. Reverting only this label reproduces main's Inspector exactly. `web/ocean.js` and `web/ocean_tour.js` are byte-identical to main.
- `web/ocean_inspector.js:46` declares `netNodes` as `UiBrainNode[]`; `web/types.d.ts:1183` already declares `UiBrainNode.kind: string`, so `Bias` is accepted under `@ts-check` (`web/ocean_inspector.js:1`). No extra type edit is needed.
- PR additions in `web/renderer.js:885` use the shared node kind; `web/ui_common.js:274` / `:304` decode and draw the shared bias node; `web/ocean_handoff.js:577`, `:724`, `:811`, `:863`, `:875` use only header/config/module data; policy types at `web/types.d.ts:131` / `:260`, added Turbo tests at `tests/ocean_turbo_handoff.js:5430`, and standalone header tests (`tests/genome_v2_header_tests.cjs:1`) reference no moved Tour/Inspector internals. Main's explicit loader references remain intact. No integration breakage requiring an additional source edit was found.

**TS2454 fix ledger.** The builder's only Round 5 product fix, in addition to the coordinator's Bias-label port, is in `web/ui_common.js:254–268`:

```diff
+    var biasPos;
     if (wide) {
       var yIn = 26, yOut = h - 40, yHid = (yIn + yOut) / 2;
+      biasPos = [w - 18, (yIn + yOut) / 2 - 18];
       // existing layout loops unchanged
     } else {
       var yTop = 26, yBot = h - 12, xS = 18, xA = w - gut, xH = (xS + xA) / 2;
+      biasPos = [(xS + xA) / 2 + 18, 14];
       // existing layout loops unchanged
     }
-    var hasBias = false, biasPos = wide ? [w - 18, (yIn + yOut) / 2 - 18] : [(xS + xA) / 2 + 18, 14];
+    var hasBias = false;
```

Both exhaustive branches now assign `biasPos` immediately after initializing their operands. The original conditional evaluated exactly one of these same expressions under the same `wide` condition; operands, arithmetic order and resulting array values are unchanged. The intervening loops only populate local `pos` arrays and never change these operands. No rendering, simulation, layout threshold, node, or old-key behavior changes. TypeScript can now prove assignment on both branches. The diff above abbreviates only unchanged loops.

**Environment and recipe ledger.** Frozen `build_g2pr2/gate.sh` remains byte-identical (SHA-256 `7ae97ab9be3151b399d95ace8cfc39a9fc71dd1a7077feabb7c711717abc8858`). The sole scratch `env.sh` edit changes `BASE="$WORK/base"` to `BASE="$WORK/base_4bafeb2"`; `base.sha` is updated to `4bafeb2` for site/final audits. All Round 2–4 resource settings remain: nice 19, two jobs/two threads, `RQ_TEST_WORKERS=2`, `EMCC_CORES=1`, `BINARYEN_CORES=2`, FIFO LTO jobserver, CTest `--stop-on-failure -j 1 -E '^invasion_tooling$'`, explicit installed SFML paths, offline npm cache. Before/after frozen hashes are `r5_start_frozen.sha256` / `r5_run_frozen.sha256` under `build_g2pr2/logs/`. Each gate command runs through `bash build_g2pr2/gate.sh LABEL COMMAND...`; receipts are `build_g2pr2/logs/LABEL.{command,exit,time,log}`. Fresh base Turbo/site runs use the new pristine source and separate outputs; engine gates use source-equivalent Round 4 results under the coordinator decision below. Browser-only checks are skipped.

Gate 1 **PASS** (`r5_01_native`, exit 0): serial 14/14 selected CTests (559.61 s), OpenMP 7/7 (30.24 s), thread-pool 7/7 (51.41 s), focused plain/eye Ocean 66 checks each. The sole exclusion remains the owner-authorized `invasion_tooling`. Gate 2 completion follows the coordinator-authorized mixed reuse/fresh rule below.

**Round 5b completion and coordinator decision (2026-11-27).** The owner-delegated coordinator authorized reuse of Round 4 passes when gate inputs are byte-identical. This supersedes the original instruction to recompute every gate. The changed set was independently recomputed as `git diff --name-only 6bc66a9 4bafeb2` union `{web/ocean_inspector.js, web/ui_common.js}`: **31 unique paths**. Full main delta, Round 5 edits, union and input SHA-256 inventories are in `build_g2pr2/logs/r5_changed_set.json` and `r5_gate_reuse_audit.json`. No backup was accessed.

The Round 4 final deliverable snapshot differs only at `tests/ocean_turbo_handoff.js`, `web/ocean.js`, `web/types.d.ts`, and `web/ui_common.js`, all within that union. The new Inspector file is independently covered by the integration audit. Unmodified tracked inputs were compared to Git `6bc66a9`; PR inputs were compared to `r4_stop_deliverables.sha256`. The 73-path pristine-base proof is `r5_base_engine_equivalence.json`. Main's engine/build/parity/identity sources are identical at `6bc66a9` and `4bafeb2`, so the retained base results apply to the new approved base by source equivalence. No additional base engine build or parity run was necessary. Gate 3 calls `tools/identity_base_head.sh` and the unchanged arena fixture directly; it does not execute changed Red Queen tooling. CMake's registration of tests does not execute their Python tools during a target-only engine build.

**Gate-result reuse.** Input families below are expanded to individual paths and hashes in `r5_gate_reuse_audit.json`. Engine/test C++ inventories deliberately include all headers and helpers; web/site inventories conservatively include additional files in those families. Generated parity/focused drivers derive exclusively from the listed sources. The six production modules are checked against both Round 4 build manifests for every reuse decision. Wrapper/environment identities are in `r5_run_frozen.sha256`; the previously ledgered BASE-path change points to identical engine source. Toolchain/resource settings remain unchanged.

| Gate | Inputs | Intersection with CHANGED SET | REUSED or RERUN | Receipt |
|---|---|---|---|---|
| 2 native | `src/**`, `wasm/*.{cpp,hpp}`, C++ tests/helpers, `tools/ocean*.{cpp,hpp}`, generator, four mutant scripts, original wrapper | empty | REUSED: inputs byte-identical | `r4_02_mutants.{command,exit,time,log}` |
| 2 Node/header/UI | `tests/genome_v2_fault.py`, `tests/genome_v2_header_tests.cjs`, `web/ocean_handoff.js`, `web/ui_common.js` | `web/ui_common.js` | RERUN, both named mutants and before/after controls | `r5_02_web_mutants.*` |
| 3 | engine sources, CMake/presets/toolchain, image copy inputs, `comparison_builds.sh`, `identity_gates.sh`, `tools/identity_base_head.sh`, `tests/redqueen_arena_selected.json`, pinned source `e90cbf3` | empty | REUSED: inputs byte-identical | `r4_03_builds.*`, `r4_03_identity.*` |
| 4 | engine/wasm sources, focused C++ tests/helpers, log-table generator and identity, `wasm_focused.sh` | empty | REUSED: inputs byte-identical | `r4_04_focused.*` |
| 5 | engine sources, `wasm/parity_driver.cpp`, `wasm/parity.sh` | empty | REUSED: inputs byte-identical | `r4_05_classic.*` |
| 6 | engine/wasm sources, C++ Ocean tests/helpers, parity/fingerprint/body/hydro/probe/eye tools, `tests/ocean_baseline/*`, `tests/fixtures/*`, `wasm/ocean_parity.sh`, `ocean_v2.py` | empty | REUSED: inputs byte-identical | `r4_06_ocean.*`, `r4_06_v2.*` |
| 7 | engine/wasm sources, CMake/presets/toolchain, `wasm/build_{wasm,ocean}.sh`, `module_gates.sh`; six output modules | empty | REUSED: inputs byte-identical; both forced builds match retained modules | `r4_07_modules.*`, `r4_modules_{first,second}.sha256`, `r5_modules_retained.sha256` |
| 8 | original web gate suite, UI parity helper/fixtures and `tools/ocean_render_perf/*`, source config readers, `web/**` including six modules/vendor, package/lock, `tsconfig.json`, types | `tests/ocean_render_browser.mjs`, `tests/ocean_render_query_tests.cjs`, `tests/ocean_turbo_handoff.js`, `tests/ui_common_tests.cjs`, `tests/ui_inspector_tests.cjs`, `tsconfig.json`, `web/ocean.html`, `web/ocean.js`, `web/ocean_inspector.js`, `web/ocean_tour.js`, `web/types.d.ts`, `web/ui_common.js` | RERUN | `r5_08_base.*`, `r5_08_web.*`, `r5_08_remaining.*`; harness ENVIRONMENT-BLOCKED |
| 9 | `wasm/build_site.sh`, its web/image/fixture inventory, six modules, base site, site comparison, immutability script and protected tracked files | `.github/workflows/ci.yml`, `tools/redqueen/ANALYSIS_CONTRACT.md`, `tools/redqueen/analysis.py`, `tools/redqueen/backbone.py`, `tools/redqueen/calib.py`, `tools/redqueen/recurrence.py`, `tools/redqueen/stats.py`, `tools/redqueen/test_analysis.py`, `tools/redqueen/test_backbone.py`, `tools/redqueen/test_calib.py`, `tools/redqueen/test_material.py`, `tools/redqueen/test_recovery_extra.py`, `tools/redqueen/test_recurrence.py`, `tools/redqueen/test_stats.py`, `tools/redqueen/test_transition.py`, `tools/redqueen/transition.py`, `wasm/build_site.sh`, `web/ocean.html`, `web/ocean.js`, `web/ocean_inspector.js`, `web/ocean_tour.js`, `web/types.d.ts`, `web/ui_common.js` | RERUN | `r5_09_base.*`, `r5_09_site.*`, `r5_09_compare.*`, `r5_immutability.json` |

The earlier `r5_02_mutants` aggregate exited 1 after all **36 named mutants passed**: transport mutant `cur_advanced` could not finish compilation (`g++: fatal error: Terminated signal terminated program cc1plus`). The unchanged native portion ended at that compiler termination; its cause is not established by the receipt. This is retained as an incomplete failed aggregate attempt, never as a full pass or mutant catch. The later coordinator decision explicitly replaces that unchanged portion with passing Round 4 evidence. Round 4's complete passing native suites supply that evidence. `r5_native_mutant_reuse_checks.json` additionally verifies all 34 named native mutant compilations succeeded, every exit-1 log contains its required assertion, and all 12 native clean controls exited 0. Both Node/header mutants were then rerun explicitly with the original runner's `--only header_trust --only header_duplicate` selectors, including its clean before/after controls and deliberate runner-refusal probes. The complete current UI/Inspector suites run in gate 8. No own-test repair or implementation fix occurred during 5b; no retry budget was consumed. Sixteen generated Red Queen Python caches created during gate 1 were removed (they were absent from the Round 5 start inventory); no source file changed. `r5_cache_cleanup.json` lists them.

**Gate receipts.** Every command below is the exact argument list after `bash build_g2pr2/gate.sh LABEL`. Receipts are under `build_g2pr2/logs/`, with `.command`, `.exit`, `.time`, and `.log` sharing the label. Reused exits and walls belong to Round 4, not a newly executed run.

| Gate | Command | Exit | Wall | Evidence | Log |
|---|---|---:|---|---|---|
| 1 | `bash build_g2pr2/native_gates.sh` | 0 | 20:43.59 | fresh | `r5_01_native.log` |
| 2 native | `bash build_g2pr2/mutant_gates.sh` | 0 | 55:07.27 | REUSED | `r4_02_mutants.log` |
| 2 web mutants | `python3 tests/genome_v2_fault.py --only header_trust --only header_duplicate` | 0 | 0:00.74 | fresh | `r5_02_web_mutants.log` |
| 3 builds | `bash build_g2pr2/comparison_builds.sh` | 0 | 0:00.90 | REUSED | `r4_03_builds.log` |
| 3 identity | `bash build_g2pr2/identity_gates.sh` | 0 | 5:31.69 | REUSED | `r4_03_identity.log` |
| 4 | `bash build_g2pr2/wasm_focused.sh` | 0 | 1:39.84 | REUSED | `r4_04_focused.log` |
| 5 | `env KEEP_OUT=1 PARITY_DIR=/home/harit/finfolk/work/trees/genome-v2-pr2/build_g2pr2/classic_parity bash wasm/parity.sh` | 0 | 3:32.63 | REUSED | `r4_05_classic.log` |
| 6 full | `env APP_TWINS=all JOBS=2 BUILD_JOBS=2 KEEP_OUT=1 bash wasm/ocean_parity.sh` | 0 | 40:13.97 | REUSED | `r4_06_ocean.log` |
| 6 v2 | `python3 build_g2pr2/ocean_v2.py /tmp/ocean_parity.eT0ET8` | 0 | 2:38.63 | REUSED | `r4_06_v2.log` |
| 7 | `bash build_g2pr2/module_gates.sh` | 0 | 1:39.68 | REUSED | `r4_07_modules.log` |
| 8 base | `node build_g2pr2/base_4bafeb2/tests/ocean_turbo_handoff.js` | 0 | 5:35.03 | fresh | `r5_08_base.log` |
| 8 head through blocked harness | `bash build_g2pr2/web_gates.sh` | 1 | 6:14.57 | fresh; ENVIRONMENT-BLOCKED harness | `r5_08_web.log` |
| 8 remaining | `bash build_g2pr2/r5_web_remaining.sh` | 0 | 0:37.34 | fresh; exact-name exclusion | `r5_08_remaining.log` |
| 9 base | `env SITE_DIR=/home/harit/finfolk/work/trees/genome-v2-pr2/build_g2pr2/site_base_4bafeb2 bash build_g2pr2/base_4bafeb2/wasm/build_site.sh` | 0 | 0:00.72 | fresh | `r5_09_base.log` |
| 9 head/audit | `bash build_g2pr2/site_audit.sh` | 0 | 0:01.61 | fresh | `r5_09_site.log` |
| 9 comparison | `python3 build_g2pr2/r5_supplement.py site` | 0 | 0:00.09 | fresh | `r5_09_compare.log` |

**ENVIRONMENT-BLOCKED / owner exclusion.** `invasion_tooling` remains excluded by exact name, and is not a pass. Its original sandbox forkserver socket was denied (`PermissionError: [Errno 1] Operation not permitted`); coordinator runs outside the sandbox on candidate and pristine main reached the same owner-excluded pre-existing Python 3.14 check-50 failure. No workaround was applied. Exact requested command against the final native engine outside the sandbox:

```bash
cd /home/harit/finfolk/work/trees/genome-v2-pr2
bash build_g2pr2/gate.sh coord_r5_final_invasion_tooling \
  ctest --test-dir build_serial --output-on-failure --stop-on-failure -j 1 \
  -R '^invasion_tooling$'
```

**Additional ENVIRONMENT-BLOCKED existing test: `tests/ui_parity_harness_tests.mjs`.** Gate 8's original command exited 1 here after Turbo/save **646/646** passed (base **604/604**), offline npm, TypeScript (the TS2454 stop is fixed), the Genome v2 header/UI checks and shared UI **107/107** all completed successfully. The harness then reported 122/132 failures because its synchronous child-process capture is denied. The read-only `r5_08_spawn_diagnostic` shows `spawnSync ... EPERM` and empty stdout/stderr for a trivial child, the valid plan, and an invalid plan (statuses still 0/0/2). The same valid plan invoked directly passes with 10 runs / 41 captures (`r5_08_direct_plan`). No product/test change or workaround was applied. The exact test was excluded by name under the environment rule; `r5_08_remaining` runs the original six subsequent commands, preserving the completed gate-8 evidence instead of rerunning Turbo/type/UI. This test is not a pass. The exact outside-sandbox rerun is:

```bash
cd /home/harit/finfolk/work/trees/genome-v2-pr2
bash build_g2pr2/gate.sh coord_r5_ui_parity_harness \
  node tests/ui_parity_harness_tests.mjs
```

These diagnostic invocations only inspect child-process status/capture and the browser-free plan; they do not replace the blocked full suite. The environment exclusion/continuation is not an own-test repair or retry. Browser-only checks remain intentionally unrun, not passes:

```bash
node tests/ocean_render_browser.mjs --base http://localhost:8123
node tests/ocean_body_gpu.mjs --base http://localhost:8123
```

**Module SHA-256s for the owner's Classic pin decision.** Base is `4bafeb25bca62c4c3a628d97ed70d781f79a6168`. Head modules are the retained Round 4 outputs. Every head hash equals both `r4_modules_first.sha256` and `r4_modules_second.sha256` (forced second compile/link), rechecked against the current tree in `r5_modules_retained.sha256`. No Round 5 module rebuild is claimed; gate 7's proven result is reused. No pin was edited.

| Artifact | Base 4bafeb2 SHA-256 | Head SHA-256 | Forced second build (Round 4) |
|---|---|---|---|
| `web/evo_boids.js` | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` | `d6bb9272dff5e730e908be03128db1b697757e976571448b9f074839ae698733` | byte-identical |
| `web/evo_boids.wasm` | `d05c4442e15d6850aeece60e52c2a69289d10a2d39fd17538b2347123be0a99b` | `1afc01039a1d45ac3528529e06ee48069277d9a6f6f964f3edc9797f5f32d7ea` | byte-identical |
| `web/evo_boids_mt.js` | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` | `c415499ac0d5acb0cb9b332bf794b32348473fc77624f0689cb0c85fc3b18c9e` | byte-identical |
| `web/evo_boids_mt.wasm` | `1c86e3d2a8c043e17ab1e75004ad37d9d20a70ce5498a80e4ae4bf4fdd8a703b` | `a203d8474fddc568f08c4dc12cff7b8199bb729890b52cdf77c318727dfa73f1` | byte-identical |
| `web/evo_ocean.js` | `8bdce72bd8991c6e88768712b60cec9b7dd0cf22335d82ebe67f40cef6d91059` | `f4a017ab30c7803df50eca752e8851b81ce17f7e4791ff1b2648c579be8355d8` | byte-identical |
| `web/evo_ocean.wasm` | `e55a4fcb2e7c2e737c6f0cc838c783237ba138336f1162ab4ddf037468b5f2f1` | `8502a36ba40d31c59a5d8f42d38a6dda60f61f01a42dfe6414b228893259de70` | byte-identical |

Final current native serial engine SHA-256: `2da8e12bb41891275a3fd907cb9961d3bebc8f8a0e6c030a70b3ab227538edcd`. Gate 1 rebuilt this executable; identity workload receipts retain their original executable bindings and normalized build-time metadata.

**Plan §7 coordinator commit split — all 57 changed/new files assigned exactly once.** Validated against the final Git inventory. Files stay whole in their assigned stage; generated caches/builds/logs/dist are excluded. No staging or commits.

1. **Add the versioned log-weight codec and canonical brain primitives**

   `src/core/genome.hpp`, `src/core/weight_log.hpp`, `src/core/weight_log_table.hpp`, `src/core/weight_log_table.identity.json`, `tests/genome_v2_codec.cpp`, `tools/gen_log_weight_table.cpp`, `tools/gen_log_weight_table.py`.

2. **Wire opt-in H12 genomes through both engines and persistence**

   `CMakeLists.txt`, `src/app/main.cpp`, `src/core/brain_conversion.hpp`, `src/core/checkpoint_io.hpp`, `src/core/cluster_projection.hpp`, `src/core/config.hpp`, `src/core/connectivity.hpp`, `src/core/creature.hpp`, `src/core/genome_color.hpp`, `src/core/genome_v2_conversion.hpp`, `src/core/isolation.hpp`, `src/core/predator_brain.hpp`, `src/core/predator_stats.hpp`, `src/core/stats.hpp`, `src/core/transplant.hpp`, `src/core/world.hpp`, `src/core/world_common.hpp`, `src/ocean/fish.hpp`, `src/ocean/ocean_config.hpp`, `src/ocean/ocean_world.hpp`, `tests/genome_v2_cli.sh`, `tests/genome_v2_frontend.cpp`, `tests/genome_v2_reach.cpp`, `tests/genome_v2_test_helpers.hpp`, `tests/genome_v2_tests.cpp`, `tests/ocean_genome_v2_tests.hpp`, `tests/ocean_tests.cpp`, `tools/genome_v2_convert.cpp`, `tools/ocean_eye_exp.cpp`, `tools/ocean_fingerprint.hpp`, `wasm/evo_wasm.cpp`, `wasm/ocean_wasm.cpp`.

3. **Verify Genome v2 policy across inspectors and Ocean handoffs**

   `docs/genome_v2_pr2_report.md`, `src/render/sfml_renderer.cpp`, `tests/genome_v2_fault.py`, `tests/genome_v2_header_tests.cjs`, `tests/ocean_turbo_handoff.js`, `wasm/parity.sh`, `wasm/parity_driver.cpp`, `web/ocean_handoff.js`, `web/ocean_inspector.js`, `web/renderer.js`, `web/types.d.ts`, `web/ui_common.js`.

4. **Rebuild Classic and Ocean Wasm for Genome v2**

   `web/evo_boids.js`, `web/evo_boids.wasm`, `web/evo_boids_mt.js`, `web/evo_boids_mt.wasm`, `web/evo_ocean.js`, `web/evo_ocean.wasm`.

**Gate 9 result.** Both sites assemble with 37 hashed assets; exactly the ten expected assets differ. Both Ocean pages reference the hashed Tour and Inspector. All **219 protected tracked files** match approved base `4bafeb2`.

**Final status.** Gates 1–7 and 9 PASS (gate 1 fresh, gate 2 mixed reuse/fresh, gates 3–7 reused, gate 9 fresh). Gate 8 executable checks pass; its existing UI parity harness is ENVIRONMENT-BLOCKED and excluded by exact name, not passed. The remaining original gate-8 checks ran fresh. No other required gate remains unrun. `invasion_tooling`, the environment-blocked UI parity harness, and browser-only checks retain the exclusions above. No network, Git write, commit, pin edit, rebaseline, merge, deployment, backup access, or study/supervisor operation occurred. Site assembly only creates local static artifacts. Full final protected-path proof is in `r5_immutability.json`; frozen-input checks and final deliverable hashes are preserved with the Round 5 receipts.



**Round 1 status (superseded by the Round 2 section below): stopped at gate 1; incomplete and not ready for integration.** The existing `invasion_tooling` CTest failed in `calibrate.py` because Python 3.14's multiprocessing forkserver could not bind its socket (`PermissionError: [Errno 1] Operation not permitted`). This is the first observed existing-test failure. No implementation fix, test bypass, later acceptance gate, rebaseline, pin edit, commit, or network operation followed the failure. The implementation and added acceptance tooling remain an uncommitted draft. Production modules have **not** been rebuilt and must not be treated as fresh.

The approved integration base is `6bc66a9156d67b62053972b6bc351a5400f3b47a`, branch `genome-v2-pr2`, with the coordinator's pristine source at `build_g2pr2/base`. The builder read the refreshed plan, independent check, reconciled PR-2 scope, Step A move map, and v1 generator/gate procedure. The change keeps H12, cap80, full-reset rewiring, legacy insertion/deletion/duplication order, and linear prey gene charging. It introduces no mixed rewiring, balanced length mutation, size-scaled cost, H24, cap160, Ocean preset, or study runner.

The working tree contains these changes:

| Area | Files and behavior |
|---|---|
| Normative table/codec | `tools/gen_log_weight_table.{cpp,py}`, generated `src/core/weight_log_table.{hpp,identity.json}`, `src/core/weight_log.hpp`: portable float32 generator, canonical-byte identity, valid signed-log words, exact bit reconstruction, nearest-magnitude quantization with lower ties, magnitude saturation. |
| Brain primitives | `src/core/genome.hpp`: schema-carrying vector, v2-only tagged four-byte execution records, actual-domain sampling and canonical validation/building, ordinary constant source 127, synchronous evaluator source scratch, schema crossover, v2 mutation dispatch before the retained legacy body. Unversioned vector/list assignments explicitly reset interpretation to v1; Genome copy/move carries it. |
| Creation/config | `config.hpp`, Classic/Ocean organism factories and founder sites, `predator_brain.hpp`, `ocean_config.hpp`, Classic CLI and shim: explicit coherent opt-in policy, H12/cap80, strict raw v2 inputs, predator-domain sampling/primers/mutation. Existing birth policy plumbing is retained. |
| Persistence | `checkpoint_io.hpp`, `transplant.hpp`: separate metadata-revision-2 descriptor, unsigned v2 weight words, canonical preflight before destination preparation, strict provenance, schema restoration, hard transplant schema equality. Revision-1 descriptor writer is retained separately. |
| Explicit conversion | `brain_conversion.hpp`, `genome_v2_conversion.hpp`, `WorldCommon::brainConversion`, init resets, `tools/genome_v2_convert.cpp`: copied populations, decoded endpoint canonicalization, quantization, recurrent state/IDs/maternal lineage retained, separate numerical provenance. No implicit conversion path. |
| Consumers | Connectivity bias row and separately seeded projection coefficients; color/sketch/spread/isolation/predator-fold changes; bounded bias reachability; decoded inspector weights; constant-node rendering in SFML and shared web drawing; eye diagnostic v2 refusal. Historical projection headers are untouched. |
| Ocean handoff/fingerprint | Four actual-policy exports, policy tokens checked against saved images, repeated policy header rejection, type declarations, conditional schema/table/provenance hashing/dumps. Existing module SHA guard remains. |
| Tests/tooling | New codec, integration, frontend, CLI, Ocean feature, reachability, header/UI, and named-mutant sources; CMake registration; Classic v2 parity cases; real Turbo/save extensions. Only the serial CTests listed below have executed. |

Step A was integrated by retained method names. `ocean::sensorReachesAction`, `OceanWorld::init`, `addFounder`, and `doInteraction` are still defined in `src/ocean/ocean_world.hpp`; none of the required PR-2 body edits was found in a moved member definition. The six extracted implementation headers and their include structure were not replaced or restored to a pre-split class body.

The independent check's corrections were applied as follows:

1. `checkpoint::rawBrainConfigValid` runs at the start of `readConfig`, before any accessor assignments. New schema keys are checked on every occurrence for duplicates/types/integrality/range; requested v2 startup validates all existing integer config keys, including all four lengths, before `intOr` can narrow or default them. Classic startup checks policy before swaps/clamps for non-v1 requests. The CLI retains every raw length token until the final version is known and validates complete v2 tokens with `from_chars`, including earlier malformed tokens overwritten later. Legacy and saturation-only length parsing remain on the old path. New frontend refusal tests preserve serialized destination state and both RNG streams; CLI tests check refusal and absence of a destination file in both option orders.
2. `build_g2pr2/env.sh` defines the approved base and absolute base/pinned comparison paths, sources `/home/harit/opt/emsdk/emsdk_env.sh` first, then selects a writable copy of the specified fable-perf cache. It unsets `LDFLAGS`, `CMAKE_PREFIX_PATH`, `SFML_DIR`, `CPPFLAGS`, and `CXXFLAGS`. Compiler jobs are bounded at two; Emscripten uses one core, OpenMP is bounded at two threads, and the wrapper runs commands at nice 19. The omitted Red Queen worker override is a resource-limit deviation recorded below. `gate.sh` uses `set -euo pipefail`, records command/exit/time/output, and propagates failure. `comparison_builds.sh` explicitly builds the supplied base with native-serial and archived `e90cbf3` plus head with native-serial-fast. `identity_gates.sh` supplies both CI comparisons, arena identity, and a concrete full-workload base/head saturation-only comparison by injecting that policy into every engine invocation of a scratch copy of the identity script. `wasm_focused.sh` checks each native/Wasm program's successful exit before comparing outputs. These later recipes are **prepared, not executed or validated**; a complete end-to-end acceptance run was not reached.
3. The P3 anchors are recorded by symbol: contact evaluations are the two `feedForward` calls in `kernel::interactionVote` (the base's lines 180–181), rather than the similarity-input setup. The bool insertion belongs to `kSimConfigBoolKeys` (base line 409), not its explanatory comments. The inventory includes `evo_set_param`'s accepted-update validation and `oceanSimConfigError`'s general validation. Both already called the shared policy validator; the extended validator supplies their new policy checks. The Classic live path also receives v2 validation before clamping.

Evidence is local and excluded from Git under `build_g2pr2/logs/`. Every executed gate wrapper writes `<label>.command`, `.exit`, `.time` (GNU time), and `.log`. The serial CTest detail is also in `build_serial/Testing/Temporary/LastTest.log`, and the underlying failure traceback is `build_serial/invasion_tooling_work/cal3.log`. `stop-source.sha256` records the source/artifact snapshot at the stop, excluding Python cache files; this report was written afterward.

| Gate / attempt | Command through `bash build_g2pr2/gate.sh LABEL ...` | Exit / wall | Result |
|---|---|---|---|
| Setup `00_setup` | Recorded setup/toolchain/cache/base/hash checks; full command in receipt | 0 / 0.77 s | Passed; SDK 6.0.4, GCC 15.2.0, CMake 3.28.3, Node 26.13.0, Python 3.14.4. |
| 0 `00_table` | `bash build_g2pr2/table_bootstrap.sh` | 0 / 3.36 s | Native/Wasm generator outputs agree; bootstrap `--write`, then native and Wasm `--check` pass. |
| 1 first attempt `01_native` | `bash build_g2pr2/native_gates.sh` | 2 / 59.64 s | Gate-script setup mistake: SFML's Xrandr/Xcursor dependencies were outside the default linker search path. |
| 1 rerun `01_native_r1` | Same | 2 / 48.48 s | Own-test compile typo: nonexistent `cfg.deathLog`; corrected to `cfg.clusterMap`. |
| 1 second rerun `01_native_r2` | Same | 130 / interrupted; timestamp-derived wall bound in receipt | Native serial build succeeded; existing `invasion_tooling` failed. **Stop.** OpenMP, pool, and focused Ocean portions were not reached. |
| 2 | Named new mutants, existing transport plain/eye, label-mask plain/eye, hydro reference mutants | Unrun | No mutant has been planted or counted as caught. |
| 3 | Explicit comparison builds, approved-base/head v1, production-pinned/head v1, base/head saturation-only identity | Unrun | Identity is not established. |
| 4 | Exhaustive codec and focused native/Wasm tests, generator checks | Unrun | Gate 0 proves generator agreement only, not codec or engine parity. |
| 5 | Full Classic parity including new v2 cases and continuation coverage; pin review | Unrun | No new Classic module hash available for an owner decision. |
| 6 | `APP_TWINS=all JOBS=2 BUILD_JOBS=2 KEEP_OUT=1 bash wasm/ocean_parity.sh`, plus separate v2 comparisons | Unrun | No claim of 124-case historical coverage, twins, fixtures, or v2 engine parity. Separate full v2 Ocean comparison recipes remain to be completed. |
| 7 | Production Classic ST/MT and Ocean builds and second-build byte comparison | Unrun | Modules are stale relative to these sources. No pin file edited. |
| 8 | Real Turbo/save handoff, type check, shared UI and render checks | Unrun | Added JS tests and save extensions are unvalidated. No npm/network operation was attempted. |
| 9 | Site assembly and final combined immutability gate | Unrun | Read-only inspection shows no tracked baseline/fixture/module/workflow diff, but this is not the final acceptance gate. |

Before the first existing failure, serial CTest reported these passes: `core_tests` (75.73 s), `weight_policy_frontend` (0.11 s), `checkpoint_v3_validation` (1.96 s), `genome_v2_codec` (0.02 s), `genome_v2_tests` (0.12 s), `genome_v2_frontend` (0.10 s), `predator_smoke` (19.10 s), `reseed_after_load` (0.83 s), `stagec_cli` (5.82 s), `genome_v2_cli` (0.27 s), and `weight_policy_cli` (0.14 s). `invasion_tooling` failed after 67.62 s. CTest's already-running invocation also reported `redqueen_tooling` passed (250.10 s); the task's own gate session was then interrupted during `redqueen_worlds`, with shell exit 130. `redqueen_forks`, OpenMP/pool variants, and the focused Ocean runs were not reached. No later gate was started. GNU time could not flush its report after interruption; `01_native_r2.interrupted.json` records command-start file time, post-interruption receipt time, and the resulting wall upper bound. This is not an exact wall-time measurement.

During that CTest invocation, two test-only refinements were made before the failure was observed: the continuation identity test was restricted to the serial build, as required by the repository's determinism contract, and the legacy packing oracle was frozen to six bits instead of reading the implementation's constant. **The serial new-test executable reported above predates those two refinements.** Those final test-source bytes require rebuilding/rechecking on resume. The new mutant/header/reach test sources were prepared but never run. No further test/script repairs or reruns were made after the existing-test failure.

The named-mutant inventory is present in `tests/genome_v2_fault.py`: `table_bit`, `table_hash`, `negative_zero`, `q_overflow`, `decoder_exponent`, `quantize_tie`, `legacy_codec`, `legacy_packing`, `tag_sink`, `canonical_modulo`, `bias_disabled`, `bias_ticket`, `bias_value`, `zero_not_driven`, `unstable_sum`, `same_step_hidden`, `undriven_reset`, `contact_no_advance`, `point_wrap`, `zero_revival`, `duplicate_zero_draw`, `conditional_gate`, `mutation_order`, `early_pr3_rewire`, `schema_lost`, `mask_stale`, `signed_v2_json`, `late_preflight`, `analysis_reset`, `transplant_override`, `conversion_rng`, `conversion_state`, `bias_reach_oob`, `header_trust`, and `header_duplicate`. **Results: 0 run, 0 claimed catches.** The disposable-copy runner and its anchors/assertion matching need validation; compilation failures and unrelated crashes must not count as catches. No mutant has modified the working implementation.

The only cross-target identity evidence obtained is the table generator. The table SHA-256, computed from 1024 little-endian uint32 words with no prefix, is:

`695bf69728c263e2f888e9c7faa4b37eababd3c3cb3a29c523f1ef50acdd2553`

Decoder version 2 / table version 1 and the exact float32 expression are recorded in the generated identity file. Existing serial tests provide compatibility checks, but neither those checks nor the generator result proves approved-base/head, production-pin, saturation-only, historical fingerprint, checkpoint, config-dump, or native/Wasm engine identity. No historical baseline divergence was observed because the historical parity gate was not run; no baseline was altered.

All six checked-in modules still have their **base bytes**. These are also the current unrebuilt working-tree hashes; a rebuilt head hash is unavailable:

| Artifact | Base SHA-256 / current unrebuilt bytes |
|---|---|
| `web/evo_boids.js` | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` |
| `web/evo_boids.wasm` | `d05c4442e15d6850aeece60e52c2a69289d10a2d39fd17538b2347123be0a99b` |
| `web/evo_boids_mt.js` | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` |
| `web/evo_boids_mt.wasm` | `1c86e3d2a8c043e17ab1e75004ad37d9d20a70ce5498a80e4ae4bf4fdd8a703b` |
| `web/evo_ocean.js` | `8bdce72bd8991c6e88768712b60cec9b7dd0cf22335d82ebe67f40cef6d91059` |
| `web/evo_ocean.wasm` | `e55a4fcb2e7c2e737c6f0cc838c783237ba138336f1162ab4ddf037468b5f2f1` |

The installed SFML dependency was selected with an explicit CMake `-DSFML_DIR=/home/harit/opt/SFML-2.6.2/lib/cmake/SFML`, while the environment variable remained unset as requested. The scratch environment's second attempt adds `LD_LIBRARY_PATH=/home/harit/opt/sfmldeps/lib:/home/harit/opt/SFML-2.6.2/lib`. These are dependency-discovery deviations from the literal plan commands, not source or system changes. The two own-test reruns are preserved rather than overwritten. The existing multiprocessing failure was not worked around or used to narrow the gate.

**Resource-limit deviation:** the scratch environment omitted `RQ_TEST_WORKERS=2`. The existing `redqueen_tooling` test defaults to ten workers and completed that path while CTest continued after the earlier failure. Thus the requested two-job limit cannot be claimed for the whole gate invocation. This was a builder wrapper mistake. The own gate session was cancelled; external jobs/supervisors were not signalled. A resumed procedure must explicitly constrain this test's workers and should use CTest's stop-on-failure option. No further rerun was attempted. Initially absent Python cache files created under `tools/redqueen/__pycache__` were removed as test residue.

The proposed coordinator commit split remains the plan's four dependency stages, after completion and acceptance:

1. Add the versioned log-weight codec and canonical brain primitives: generator/table/identity, schema, tagged records, factories/builders/evaluator/mutation, primitive tests.
2. Wire opt-in H12 genomes through both engines and persistence: config/frontends, founders/births/predators, revision 2, explicit conversion/provenance, transplants, numerical consumers/fingerprint extensions, native/Ocean tests.
3. Verify Genome v2 across inspectors and Ocean handoffs: constant rendering/types/exports/header checks, save/Turbo tests, validated planted faults, parity extensions, policy documentation, final report.
4. Rebuild Classic ST/MT and Ocean Wasm: six generated artifacts only, reproduced by a second build, with rebuilt hashes presented for the owner's Classic pin decision.

No commits were made. Resumption needs a permitted native-test environment for the existing multiprocessing check, rebuilding the final test sources, completing/validating the remaining acceptance tooling, and then gates 1–9 in order. The owner must still decide the Classic pins after the modules are actually rebuilt; there is no new pin recommendation in this stopped run.


## Round 2 — 2026-11-23 / 2026-11-24

Status: **STOP at gate 6, existing Ocean unit-test failures; incomplete and not ready for integration.** Gates 1–5 passed with the authorized `invasion_tooling` exclusion. The full Ocean command passed its 124 historical comparisons and twins/fixtures, then failed the existing config-key inventory unit tests. The original command completed with exit 1; separate v2 Ocean comparisons and gates 7–9 were not run. Round 1 evidence above is historical, not a claim about final gate completion.

The coordinator established that the original socket denial was a sandbox limitation. Outside the sandbox, `invasion_tooling` runs but fails only check 50 (`tests/invasion_tooling.sh:2804`, formal receipt over fabricated cached counters), on the second `gate.cmd_run`, with Python 3.14 forkserver `ConnectionResetError: [Errno 104] Connection reset by peer`. Pristine main `6bc66a9` has the same sole failure. Receipts: `build_g2pr2/logs/coord_invasion_tooling.{command,exit,time,log}` (exit 8, 423 s), `coord_invasion_tooling.engine.sha256`, and `coord_base_invasion.{build.log,engine.sha256,log,exit,time}` (exit 1, 413 s). Per the owner's instruction, this existing test is excluded by exact name in Round 2; its source and `tools/invasion/` remain unchanged. It is not counted as passing.

Every Round 2 gate runs through `bash build_g2pr2/gate.sh LABEL ...`, which sources the SDK and writable cache, applies nice 19, records `.command`, `.exit`, `.time`, and `.log` under `build_g2pr2/logs/`, and propagates errors. The environment now includes `RQ_TEST_WORKERS=2`, compiler/job bounds of two, `EMCC_CORES=1`, `OMP_NUM_THREADS=2`, `OMP_THREAD_LIMIT=2`, and `OPENBLAS_NUM_THREADS=2`. CTest uses `--stop-on-failure -j 1 -E '^invasion_tooling$'`. The native pool variant is compiled with `-DEVO_POOL_MAX_THREADS=2` to enforce the requested thread bound; this is a resource-only difference from the literal plan command. No existing test is edited for the environment.


Gate 1 progress: final-source serial CTest passed 14/14 selected tests (540.44 s), including `redqueen_tooling` (253.05 s), `redqueen_worlds` (111.76 s), and `redqueen_forks` (66.12 s). OpenMP passed 7/7 (30.88 s); pool passed 7/7 (28.73 s). The focused Ocean runs are pending in the same wrapper. The Red Queen graph suite reported 77 skipped cases; they are not represented as executed assertions. No additional ENVIRONMENT-BLOCKED test has been observed.

Acceptance tooling completed while gate 1 ran: Classic parity now has a `--resume-at` test-driver path restoring into a fresh `World`, and each of the four v2 cases compares uninterrupted native against resumed native and resumed Wasm at its midpoint. The separate Ocean v2 recipe is `build_g2pr2/ocean_v2.py`, covering plain/eye × bias on/off with capture, asserted births, repeat-native output, appearance-off native/Wasm twins, and body-preview native/Wasm twins with asserted founders/offspring. Neither later recipe has run yet. No implementation changes were made during this preparation.


Round 2 own-wrapper error: `r2_01_native` ultimately exited 127 with `build_g2pr2/gate.sh: line 8: me: command not found`. The builder moved command-receipt emission earlier in `gate.sh` while the original shell was still running its long native command. Bash subsequently read from the changed file offset, corrupting the trailing wrapper commands and overwriting the combined log. This is an acceptance-wrapper mistake, not an implementation/test failure; the combined receipt is invalid. Surviving CTest logs were copied to `build_g2pr2/logs/r2_01_native_surviving/{serial,openmp,pool}.LastTest.log`. The corrected wrapper is frozen during execution, and all of gate 1 is rerun as `r2_01_native_r1` (first Round 2 own-wrapper rerun). The earlier progress observations remain historical only until reproduced.


Gate 1 final rerun: **PASS** (`r2_01_native_r1`, exit 0). Serial 14/14, OpenMP 7/7, pool 7/7; focused plain Ocean (46 senses/13 actions) and eye Ocean (64/13) each passed 22 assertions. The serial test total was 523.09 s, OpenMP 31.27 s, pool 30.91 s. Complete command/exit/wall/log are in `build_g2pr2/logs/r2_01_native_r1.{command,exit,time,log}`. No additional ENVIRONMENT-BLOCKED test was observed. Gate 2 has started.


Gate 2 own-test correction 1: `r2_02_mutants` exited 1 after 0:01.20 in `control_before_header`. The new UI fixture omitted `actShort` and `actLabels`, which are required drawing inputs. `drawBrain` therefore raised `TypeError: Cannot read properties of undefined (reading '0')` at `web/ui_common.js:323` before any mutant ran. Added the two arrays to the fixture; no product code changed. The three meta-controls correctly rejected a deliberate compiler failure, SIGSEGV, and a different assertion with exit 1; none was counted as a mutant catch. Gate 2 rerun is `r2_02_mutants_r1`; original evidence remains in `build_g2pr2/genome_v2_fault.ek0_22_p` and the gate's `.command/.exit/.time/.log` receipts.


Gate 2 own-runner correction 2: `r2_02_mutants_r1` caught `table_bit`, `table_hash`, `negative_zero`, `q_overflow`, and `decoder_exponent`, then refused to credit `quantize_tie` because its actual exact failure was `FAIL positive legacy quantization line 50`, while the runner required the later midpoint assertion. The clean codec passes; the planted comparison change affects exact ties among legacy inputs too, so this is a runner assertion-order mistake, not a product failure. The runner now compiles the same focused, independent adjacent-midpoint fixture for clean-before, mutant, and clean-after, checks both signs at all 25,601 boundaries, and requires `FAIL midpoint lower magnitude`. No implementation or existing test changed. Evidence: `build_g2pr2/genome_v2_fault.do0hyz8w`; final permitted gate-2 rerun is `r2_02_mutants_r2`.


Named-mutant result from the final gate-2 attempt: **35/35 caught**, with clean controls before/after for codec, focused midpoints, native integration, bounded reachability, table identity, and header/UI targets. Evidence: `build_g2pr2/genome_v2_fault.nma0txhb/` (per invocation `.command`, `.log`, `.result`; compile results are separate). All 33 native mutant builds compiled successfully. The two header mutants ran through Node and failed their named assertions. `bias_reach_oob` produced the required bounds diagnostic; unrelated crashes are not accepted. The runner explicitly rejected its deliberate compile-failure, SIGSEGV, and unrelated-assertion probes; their `.rejected` receipts are preserved and they are not counted among the 35 catches. The full gate 2 is still running the existing fault suites; this result alone is not a full gate-2 pass.


Round 2 continuation audit (2026-11-24): the saved report already contains completed final-source gate 1 and the 35/35 named-mutant result. The `r2_02_mutants_r2` receipt has no `.exit` and an empty `.time`; its log ends at transport-suite setup. It is an interrupted partial invocation, not a gate pass or an observed test failure. The named-mutant per-command results and clean controls survive in `genome_v2_fault.nma0txhb`. Remaining gate-2 suites are rerun in order as `r2_02_remaining`, without repeating or counting the partial transport attempt. The final-source gate-1 receipt is complete (exit 0, wall 12:52.38). No product code, existing test, or pin was changed at this continuation.


The saved named-mutant evidence was independently audited at continuation: all 35 `.result` records have exit 1 with their required assertion text; all 33 native mutant `.compile.result` records have exit 0; the two remaining mutants are Node/header checks; all 12 before/after controls have exit 0; all three deliberate non-catch probes have `.rejected` receipts. The per-mutant assertion summary is `build_g2pr2/logs/r2_named_mutants_summary.json`.

Supported profile: v2 is explicit opt-in, `genomeVersion=2`, `brainEvalVersion=2`, `hiddenNeurons=12`, `weightMutationMode="saturating"`, with `biasGenes` either false or true and both prey/predator length bounds at most 80. Classic CLI equivalents are `--genome-version 2 --brain-eval-version 2 --hidden-neurons 12 --weight-mutation-mode saturating`, plus optional `--bias-genes`. Defaults remain v1. Existing checkpoints require explicit conversion with `build_serial/genome_v2_convert INPUT OUTPUT SOURCE_SHA256 BIAS(0|1)` into a new output path; conversion records numerical provenance and does not promise legacy trajectories after quantization. Ocean uses the same policy in its config; real saved images remain module-specific.


Before gate 3, the comparison-build wrapper now exports `MAKEFLAGS=--jobserver-style=fifo`; all CMake builds still use `--parallel 2`. GNU Make 4.4.1 emits a two-slot FIFO jobserver and GCC 15's LTO wrapper recognizes FIFO jobserver authentication. This constrains `-flto=auto` inside the unchanged `native-serial-fast` recipe without changing arithmetic/codegen flags. The check was a scratch Makefile only; no production source or preset changed.


Continuation gate-2 progress: complete existing plain transport suite passed (9/9 defects; clean-before/clean-after pass), followed by complete eye transport suite (10/10 including `eye_contrast`; clean-before/clean-after pass). Their disposable evidence directories are `build_g2pr2/tmp/ocean_transport_fault.95ona6w9` and `.6pqd31rz`; each retains separate build/runtime logs. The `r2_02_remaining` combined command is still running the label-mask and hydro suites; this paragraph is not yet a whole-gate pass.


Gate 2 final result: **PASS**. `r2_02_remaining` exited 0; its command/exit/wall/log receipts are complete. Both label-mask variants caught all three faults, then their clean controls passed (2,991 plain and 3,186 eye assertions). Both hydro mutants (`drop_A04`, `scale_Fc_x`) compiled successfully and failed the required entrywise cubature assertion. Together with the audited 35/35 named Genome v2 mutants and 9/9 + 10/10 transport mutants/controls above, this completes gate 2. No additional ENVIRONMENT-BLOCKED test occurred and no product-code change was needed. Gates 3–9 are now running sequentially through `build_g2pr2/remaining_gates.sh`, which stops at the first nonzero gate.


Gate 3: **PASS**, comparison builds (`r2_03_builds`) and all three identity workloads (`r2_03_identity`) exited 0. Approved-base/head serial v1, pinned `e90cbf3`/head `native-serial-fast` v1, and approved-base/head serial saturation-only each report **268 files in 27 scenarios: IDENTICAL**. Each `identity.json` has `identical: true`, empty differences, and equal base/head manifests. The workloads include legacy format-1/format-2 and revision-1 policy checkpoints, RNG state, resumed histories, transplants, manifests/logs, and CSV/config files with only the existing timing/build-date normalization. The arena SHA is `3efeab747a72150c24bcb541f84284691d4b45823cff45e95d71d8563fc8a838`. Bound binaries, manifest hashes and counts are in `build_g2pr2/logs/r2_identity_summary.json`; full manifests are `build_g2pr2/identity_{base,pinned,saturation}/identity.json`. Rebuilt pinned binary bytes are recorded rather than claimed to equal the server's production-binary SHA.


Gate 4: **PASS** (`r2_04_focused`, exit 0). Native/Wasm stdout is byte-identical for `genome_v2_codec`, `genome_v2_tests`, `genome_v2_frontend`, `weight_policy_frontend`, `checkpoint_v3_validation`, and plain/eye `genome_v2_reach`; each program independently exited 0 before `cmp`. Codec output is `accepted=51203 rejected=14333 digest=ebb6ca6dfa1db0a5`; its independent oracle covers all words, all legacy quantizations and adjacent midpoint boundaries/both signs. Deterministic recurrence/mutation and frontend assertions pass in both targets. Native and Wasm generator `--check` both return table SHA `695bf69728c263e2f888e9c7faa4b37eababd3c3cb3a29c523f1ef50acdd2553`. Per-target paired outputs are retained as `build_g2pr2/logs/<target>.{native,wasm}.txt`.


Gate 5: **PASS** (`r2_05_classic`, exit 0). Full Classic matrix: **35 final-checkpoint comparisons**, including all retained historical/PR-1 saturation cases and the four v2 cases (bias on, bias off, neural predator/primer, inheritance/floor/refill). Each v2 case also passes uninterrupted native == fresh-World resumed native == fresh-World resumed Wasm at its midpoint (steps 1,000 or 2,000). All checkpoint bytes match. Driver binaries, paired checkpoints and runtime logs remain in `build_g2pr2/classic_parity`. Pin review awaits the production rebuild in gate 7; no pin file was edited.


Gate 6 historical matrix completed: **124/124 native == Wasm == committed baseline** (every step chained), with no reported FAIL line. Both repeat-native controls (`def_s1`, `eye_off_s1`) are identical. Preflight passed 124 accepted configs, 170 invalid-config refusals, preset/key-list guards, both non-finite-state checks, and 26 live refusals with state preservation. Evidence directory is `/tmp/ocean_parity.zZFD1q`. The same full invocation is still running all appearance twins, default body twins, fixtures/reference and units; this is not yet a whole-gate pass.


Gate 6 STOP condition: the existing `ot::testShimInts` / `ot::testShimBools` coverage inventories fail in the full plain native unit run. Exact output in `/tmp/ocean_parity.zZFD1q/tests.native.txt`:

```text
FAIL shim_ints      1 of 405 checks failed; first: kSimConfigIntKeys has 19 keys, the member table 16
FAIL shim_bools     1 of 702 checks failed; first: the bool-key lists and the member tables differ in size
OCEAN TESTS: 106 passed, 2 failed
```

The implementation extends `kSimConfigIntKeys` with `genomeVersion`, `hiddenNeurons`, and `brainEvalVersion`, and the bool list with `biasGenes`. The existing hard-coded member tables in `tests/ocean_tests.cpp` (the `shim_ints` and `shim_bools` functions) retain their old 16-int / 10-bool SimConfig inventories. Those test bodies are unchanged in this PR; the file diff only adds the new test header, focused mode and full-suite call. This is an existing-test integration failure, **not ENVIRONMENT-BLOCKED** and not an own-new-test/runner error. Per the explicit STOP rule, no test update, implementation workaround, rerun, exclusion, or later acceptance gate follows it. The original full gate command is allowed to finish collecting its native/Wasm plain/eye unit results; its nonzero exit stops the sequential wrapper before the separate v2 Ocean comparison or gate 7.

Before that failure, all **124/124 appearance twins** and **22/22 default body-preview twins** passed. Body fixture: 127 bodies / 572 samples, digest `b9f6510154e9b597`; hydro fixture: 137 bodies, digest `055461f8a8792567`; both native == Wasm == committed fixtures. Offline hydro reference passed. These successful components do not turn gate 6 into a pass.


Stop artifact receipt: `build_g2pr2/logs/r2_stop_artifacts.sha256`. Final serial engine is `ea4f6d9c998640a1f9f3cbfd371382e3e85b8198d1952ce20a1b670ff6666a3e`. All six web module hashes still equal the base hashes in the Round 1 artifact table. They are **unrebuilt/stale head files**, not generated head results. Gate 7 and its forced second build were not reached, so no rebuilt Classic hash or owner pin-decision recommendation exists. No pin file was edited. Read-only stop inspection shows no tracked diff in `tests/ocean_baseline`, `tests/fixtures`, `.github/workflows`, `tools/invasion`, or `tests/invasion_tooling.sh`; the final combined immutability/site gate remains **unrun**. The task-created untracked Red Queen `.pyc` cache was removed; no study/noise-bank data was touched.

Coordinator final rerun, **outside the sandbox**, against the final serial engine above:

```bash
cd /home/harit/finfolk/work/trees/genome-v2-pr2
bash build_g2pr2/gate.sh coord_final_invasion_tooling \
  ctest --test-dir build_serial --output-on-failure --stop-on-failure -j 1 \
  -R '^invasion_tooling$'
```

The wrapper applies nice 19, the two-worker/thread environment and explicit SFML runtime paths, and records command/exit/wall/log. There are **no additional ENVIRONMENT-BLOCKED tests** requiring an outside rerun. `invasion_tooling` remains excluded by the owner, not passed: the coordinator's candidate and pristine-main control receipts both report the same existing Python 3.14 check-50 failure. Do not exclude `shim_ints` or `shim_bools`: their failures are unrelated to sandbox system calls. Browser-only checks remain delegated to the coordinator and were never started.


Gate 6 final receipt is complete: `r2_06_ocean` **exit 1**; the original command completed all unit invocations and then stopped the outer sequence. Plain native/Wasm: **106 passed / 2 failed**, both exit 1, stdout byte-identical. Eye native/Wasm: **113 passed / 2 failed**, both exit 1, stdout byte-identical. In all four runs the only failures are the same `shim_ints` and `shim_bools` existing member-inventory assertions. The full parity command reports 2,392 seconds internally; the exact GNU time wall is in the consolidated table and `.time` receipt. No `r2_06_v2`, `r2_07_modules`, `r2_08_web`, or `r2_09_site` invocation was started. No repair/rerun/exclusion was applied to either failing test.


<!-- ROUND2_FINAL_TABLES -->

**Round 2 consolidated gate table** (all commands run through the frozen `gate.sh` wrapper; `.command`, `.exit`, `.time`, `.log` share the label under `build_g2pr2/logs`). Earlier own-wrapper/test attempts and their two gate-2 corrections are preserved above.

| Gate | Recorded command (prepared command if UNRUN) | Exit | Wall | Log / result |
|---|---|---|---|---|
| 1 | `bash build_g2pr2/native_gates.sh` | 0 | 12:52.38 | `r2_01_native_r1.log` — Passed; only invasion_tooling excluded (coordinator receipts above) |
| 2, named | `bash build_g2pr2/mutant_gates.sh` | interrupted | aggregate unavailable; each named invocation has wall/exit receipts | `r2_02_mutants_r2.log` — 35/35 catches and 12 controls pass; wrapper interrupted during subsequent transport setup |
| 2, remaining | `bash -c 'set -euo pipefail; python3 tests/ocean_transport_fault.py; python3 tests/ocean_transport_fault.py --eye; bash tests/label_mask_fault.sh; EYE=1 bash tests/label_mask_fault.sh; python3 tests/ocean_hydro_reference_mutants.py'` | 0 | 45:07.66 | `r2_02_remaining.log` — Passed transport plain/eye, label-mask plain/eye, hydro mutants |
| 3, builds | `bash build_g2pr2/comparison_builds.sh` | 0 | 1:01.91 | `r2_03_builds.log` — Passed approved-base/pinned/candidate comparison builds |
| 3, identity | `bash build_g2pr2/identity_gates.sh` | 0 | 5:45.07 | `r2_03_identity.log` — Passed all three 268-file / 27-scenario comparisons |
| 4 | `bash build_g2pr2/wasm_focused.sh` | 0 | 1:45.38 | `r2_04_focused.log` — Passed exhaustive/focused native == Wasm and generator checks |
| 5 | `env KEEP_OUT=1 PARITY_DIR=/home/harit/finfolk/work/trees/genome-v2-pr2/build_g2pr2/classic_parity bash wasm/parity.sh` | 0 | 3:17.16 | `r2_05_classic.log` — Passed 35 cases + 4 v2 midpoint continuation comparisons |
| 6, full | `env APP_TWINS=all JOBS=2 BUILD_JOBS=2 KEEP_OUT=1 bash wasm/ocean_parity.sh` | 1 | 39:52.01 | `r2_06_ocean.log` — FAILED existing shim_ints / shim_bools inventory assertions; STOP |
| 6, separate v2 | `python3 build_g2pr2/ocean_v2.py /tmp/ocean_parity.zZFD1q` | — | — | UNRUN after STOP |
| 7 | `bash build_g2pr2/module_gates.sh` | — | — | UNRUN after STOP; production modules stale |
| 8 | `bash build_g2pr2/web_gates.sh` | — | — | UNRUN after STOP; Turbo/save/type/UI checks not established |
| 9 | `bash build_g2pr2/site_audit.sh` | — | — | UNRUN after STOP; final site/immutability gate not established |

The named-suite aggregate wrapper is interrupted, not counted as a successful combined gate invocation. Its completed named checks are established by the audited per-command results and controls in `genome_v2_fault.nma0txhb` plus `r2_named_mutants_summary.json`; the remaining original gate-2 commands then completed in `r2_02_remaining`. No compilation error or unrelated crash is a catch.

**Identity receipts.** Each row has `identical: true`, equal base/head manifests and no differences. Registered arena SHA: `3efeab747a72150c24bcb541f84284691d4b45823cff45e95d71d8563fc8a838`.

| Comparison | Files / scenarios | identity.json SHA-256 |
|---|---|---|
| base | 268 / 27 | `6d1f2a6b70d9c8b9d78c8da8c8ee6b3985f9353427fb23d85e49da4c1d2d9282` |
| pinned | 268 / 27 | `2a7c91f7dc8c8869f570541918e096cae56ee9f1c5fe7f5f7453a36682ad24dc` |
| saturation | 268 / 27 | `2748cddbb03c0b88a87fba445e908c18b5b51a44f252e13fea6381c70ce9d288` |

Exact rebuilt binary bindings are in `r2_identity_summary.json` and each full manifest. Table SHA (gate 4 native/Wasm check): `695bf69728c263e2f888e9c7faa4b37eababd3c3cb3a29c523f1ef50acdd2553`.

**Module hash status at STOP.** Base hashes are independently read from the approved Git commit. Current unrebuilt head files have the same bytes. Generated head hashes and second-build match are **UNAVAILABLE / UNRUN**, because the existing-test failure stopped work before gate 7; these are not freshness results and cannot support a new Classic pin decision.

| Artifact | Base SHA-256 = current stale head-file SHA-256 | Generated head / second build |
|---|---|---|
| `web/evo_boids.js` | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` | unavailable / unrun |
| `web/evo_boids.wasm` | `d05c4442e15d6850aeece60e52c2a69289d10a2d39fd17538b2347123be0a99b` | unavailable / unrun |
| `web/evo_boids_mt.js` | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` | unavailable / unrun |
| `web/evo_boids_mt.wasm` | `1c86e3d2a8c043e17ab1e75004ad37d9d20a70ce5498a80e4ae4bf4fdd8a703b` | unavailable / unrun |
| `web/evo_ocean.js` | `8bdce72bd8991c6e88768712b60cec9b7dd0cf22335d82ebe67f40cef6d91059` | unavailable / unrun |
| `web/evo_ocean.wasm` | `e55a4fcb2e7c2e737c6f0cc838c783237ba138336f1162ab4ddf037468b5f2f1` | unavailable / unrun |

Passed: gates 1–5 with the owner's exact invasion exclusion, and the separately identified successful parts of gate 6. Failed: full gate 6's existing Ocean inventory units. Unrun: separate v2 Ocean comparisons; gates 7–9; browser-only checks. No new environment-only exclusion was introduced. No implementation/test repair or acceptance run followed the STOP condition; only the already-running full command collected its remaining unit results, and read-only reporting/receipt inspection followed.

Deviations/limits: explicit local SFML discovery/runtime paths; pool build cap of two; two-slot FIFO jobserver for the unchanged fast-serial LTO recipe; offline npm recipe prepared but never executed; interrupted wrapper evidence is not a whole-gate pass. Ocean retains the exact requested `JOBS=2 BUILD_JOBS=2` command: two case jobs, each launching native/Wasm as a pair. No claim of at most two total OS processes is made for those paired phases. No browser, network, pin change, rebaseline, merge, deployment or commit occurred. Gate 9's full immutability proof remains unrun even though stop-time read-only inspection found protected paths unchanged.

Proposed coordinator commit split remains plan §7, after the remaining work is accepted:

1. Versioned log-weight codec and canonical brain primitives: generator/table/identity, schema/tagged records, factories/builders/evaluator/mutation, primitive tests.
2. Opt-in H12 integration and persistence: both engines/frontends, founders/births/predators, metadata revision 2, conversion/provenance, transplants, numerical consumers/fingerprints and native/Ocean tests.
3. Inspectors and Ocean handoffs: constant rendering/types/exports/header validation, real save/Turbo tests, validated mutants, parity extensions, supported-profile documentation and report.
4. Six generated Classic ST/MT and Ocean artifacts only, reproduced by a second build, with hashes for the owner's Classic pin decision.

Everything remains uncommitted. This run is incomplete and must not be presented as integration-ready.


## Round 3 — 2026-11-25

Resumed at gate 6 under the coordinator's 2026-11-25 authorization. Round 2 gates 1–5 and their receipts are retained unchanged. The Round 2 environment and frozen `gate.sh` remain unchanged; wrapper hashes are in `build_g2pr2/logs/r3_frozen_wrappers.sha256`.

**existing-test inventory extension, coordinator-authorized 2026-11-25.** Four member rows register `genomeVersion`, `hiddenNeurons`, `brainEvalVersion`, and `biasGenes`. New policy-only branches test supported values in coherent policy objects and refuse other generic whole integers with unchanged config and a nonempty error. Existing generic malformed-value checks remain; added checks cover both repeat orders and full policy-field preservation. The old 16 integer, 10 SimConfig bool, and 8 Ocean bool rows, assertions, value lists, loops, messages, and size checks are preserved byte for byte: a line-level audit confirms the Round 3 diff contains additions only. Exact diff follows.

```diff
--- tests/ocean_tests.cpp.round2
+++ tests/ocean_tests.cpp
@@ -3552,6 +3552,7 @@
         {"predatorBrain", &SimConfig::predatorBrain}, {"predatorPrimer", &SimConfig::predatorPrimer},   // v0.27.0
         {"predatorFrozen", &SimConfig::predatorFrozen},
         {"fastTanh", &SimConfig::fastTanh},
+        {"biasGenes", &SimConfig::biasGenes},
     };
     const struct { const char* key; bool OceanConfig::*m; } oceans[] = {
         {"deepCurrent", &OceanConfig::deepCurrent}, {"lightEnabled", &OceanConfig::lightEnabled},
@@ -3572,6 +3573,19 @@
     // One checker for both tables: get(sc, oc) is the key's stored bool.
     auto check = [&](const char* key, const Good& good, const std::vector<const char*>& bad, auto get, auto set) {
         t.expect(isSimConfigBoolKey(key) || isOceanBoolKey(key), "%s is in neither bool-key list", key);
+        // Only the new policy bool needs a coherent v2 object for acceptance.
+        if (std::strcmp(key, "biasGenes") == 0) {
+            for (const auto& g : good) {
+                SimConfig sc;
+                OceanConfig oc;
+                set(sc, oc, !g.second);
+                std::string err;
+                const std::string j = std::string("{\"genomeVersion\":2,\"brainEvalVersion\":2,\"hiddenNeurons\":12,") +
+                                      "\"weightMutationMode\":\"saturating\",\"biasGenes\":" + g.first + "}";
+                accepted += t.expect(readOceanJson(j.c_str(), sc, oc, err) && get(sc, oc) == g.second,
+                                     "%s: policy bool refused or not stored (%s)", j.c_str(), err.c_str());
+            }
+        } else
         for (const auto& g : good) {
             SimConfig sc;
             OceanConfig oc;
@@ -3586,12 +3600,18 @@
                 SimConfig sc;
                 OceanConfig oc;
                 const bool before = get(sc, oc);
+                const SimConfig policyBefore = sc;
                 std::string err;
                 const std::string kb = std::string("\"") + key + "\":" + b, kg = std::string("\"") + key + "\":true";
                 const std::string j = "{" + (form == 0 ? kb : form == 1 ? kg + "," + kb : kb + "," + kg) + "}";
                 refused += t.expect(!readOceanJson(j.c_str(), sc, oc, err) && get(sc, oc) == before &&
                                         err.find(key) != std::string::npos,
                                     "%s: accepted, or the error does not name the key (%s)", j.c_str(), err.c_str());
+                if (std::strcmp(key, "biasGenes") == 0)
+                    t.expect(sc.dump() == policyBefore.dump() && sc.genomeVersion == policyBefore.genomeVersion &&
+                                 sc.biasGenes == policyBefore.biasGenes && sc.hiddenNeurons == policyBefore.hiddenNeurons &&
+                                 sc.brainEvalVersion == policyBefore.brainEvalVersion,
+                             "%s: refused policy bool changed the config", j.c_str());
             }
     };
     for (const auto& k : sims)
@@ -3640,17 +3660,51 @@
         {"foodPatches", &SimConfig::foodPatches}, {"predatorCount", &SimConfig::predatorCount},
         {"predatorMinPopulation", &SimConfig::predatorMinPopulation},
         {"predatorMaxPopulation", &SimConfig::predatorMaxPopulation},
+        {"genomeVersion", &SimConfig::genomeVersion},
+        {"hiddenNeurons", &SimConfig::hiddenNeurons},
+        {"brainEvalVersion", &SimConfig::brainEvalVersion},
     };
     t.expect(sizeof(ints) / sizeof(ints[0]) == sizeof(kSimConfigIntKeys) / sizeof(kSimConfigIntKeys[0]),
              "kSimConfigIntKeys has %zu keys, the member table %zu", sizeof(kSimConfigIntKeys) / sizeof(kSimConfigIntKeys[0]),
              sizeof(ints) / sizeof(ints[0]));
     for (const auto& k : ints) {
         t.expect(isSimConfigIntKey(k.key), "%s is not in kSimConfigIntKeys", k.key);
+        const bool policyInt = k.m == &SimConfig::genomeVersion || k.m == &SimConfig::hiddenNeurons ||
+                               k.m == &SimConfig::brainEvalVersion;
+        auto checkPolicyInt = [&](const char* token, int value) {
+            SimConfig sc, before;
+            OceanConfig oc;
+            std::string err;
+            const bool accepted = k.m == &SimConfig::hiddenNeurons ? value == 12 : value == 1 || value == 2;
+            // Supply companions only when selecting the supported v2 policy.
+            const bool v2 = k.m != &SimConfig::hiddenNeurons && value == 2;
+            const std::string companions = !v2 ? "" : k.m == &SimConfig::genomeVersion
+                ? "\"brainEvalVersion\":2,\"hiddenNeurons\":12,\"weightMutationMode\":\"saturating\","
+                : "\"genomeVersion\":2,\"hiddenNeurons\":12,\"weightMutationMode\":\"saturating\",";
+            const std::string j = "{" + companions + "\"" + k.key + "\":" + token + "}";
+            const bool read = readOceanJson(j.c_str(), sc, oc, err);
+            if (accepted)
+                t.expect(read && sc.*k.m == value && !brainPolicyConfigError(sc),
+                         "%s: supported policy int refused or not stored (%s)", j.c_str(), err.c_str());
+            else
+                t.expect(!read && !err.empty() && sc.dump() == before.dump() &&
+                             sc.genomeVersion == before.genomeVersion && sc.biasGenes == before.biasGenes &&
+                             sc.hiddenNeurons == before.hiddenNeurons && sc.brainEvalVersion == before.brainEvalVersion,
+                         "%s: unsupported policy int accepted or refusal changed the config (%s)", j.c_str(), err.c_str());
+        };
+        if (policyInt) {
+            checkPolicyInt("1", 1);
+            checkPolicyInt("12", 12);
+        }
         // The reader really reads it; whole numbers to the range ends read
         // exactly; a fraction, or one past either end, is refused before the
         // cast, the config untouched.
         for (const auto& v : {std::pair<const char*, int>{"3", 3}, {"-3", -3}, {"2.0", 2}, {"1e3", 1000}, {"-0", 0},
                               {"2147483647", 2147483647}, {"-2147483648", -2147483647 - 1}}) {
+            if (policyInt) {
+                checkPolicyInt(v.first, v.second);
+                continue;
+            }
             SimConfig sc;
             OceanConfig oc;
             std::string err;
@@ -3667,6 +3721,27 @@
             t.expect(!readOceanJson(j.c_str(), sc, oc, err) && sc.*k.m == before.*k.m && !err.empty(), "%s accepted", j.c_str());
         }
     }
+    // The new policy ints also reject every malformed occurrence, in either
+    // order, and repeated valid occurrences, without changing the config.
+    for (const auto& k : ints) {
+        if (k.m != &SimConfig::genomeVersion && k.m != &SimConfig::hiddenNeurons && k.m != &SimConfig::brainEvalVersion) continue;
+        const char* good = k.m == &SimConfig::hiddenNeurons ? "12" : "1";
+        for (const char* v : {"0.5", "3.75", "-3.75", "1e-300", "2147483647.5", "-2147483648.5", "2147483648", "-2147483649",
+                              "1e300", "-1e300", "1e999", good}) {
+            for (int form = 0; form < 2; ++form) {
+                SimConfig sc, before;
+                OceanConfig oc;
+                std::string err;
+                const std::string kg = std::string("\"") + k.key + "\":" + good;
+                const std::string kb = std::string("\"") + k.key + "\":" + v;
+                const std::string j = "{" + (form == 0 ? kg + "," + kb : kb + "," + kg) + "}";
+                t.expect(!readOceanJson(j.c_str(), sc, oc, err) && !err.empty() && sc.dump() == before.dump() &&
+                             sc.genomeVersion == before.genomeVersion && sc.biasGenes == before.biasGenes &&
+                             sc.hiddenNeurons == before.hiddenNeurons && sc.brainEvalVersion == before.brainEvalVersion,
+                         "%s: repeated policy int accepted or refusal changed the config (%s)", j.c_str(), err.c_str());
+            }
+        }
+    }
     // A repeated key: every occurrence is checked, not only the one the reader takes.
     // A number past a double's range (1e400: strtod's ±inf) in either occurrence,
     // as the page now passes it on (web/ocean_handoff.js cfgJson), SimConfig's int
```

**STOP: the authorized inventory extension exposed a real product defect.** The member-size failures are resolved, but the correct new `shim_ints` checks fail because policy refusal mutates the supplied config. The first failure is `{"genomeVersion":12}`: `readOceanJson` returns false with `genomeVersion must be 1 or 2`, after `checkpoint::readConfig` has already assigned 12 to the formerly default-1 field. The plain native result is `FAIL shim_ints 28 of 540 checks failed`; `shim_bools` passes all 783 checks. No product change, test weakening, exclusion, or retry follows this finding. The already-running original gate command finished collecting its four unit outputs and final receipt, as in Round 2, and exited 1. No subsequent gate was started.

Source cause: `src/core/checkpoint_io.hpp:246–250` sets a genome-version sentinel on invalid raw input, or writes the schema fields directly; `src/ocean/ocean_config.hpp:481–484` then validates the already-modified config and returns false without restoring it. This affects unsupported whole-number policy values and repeated otherwise-valid policy integers. It is an implementation refusal-state defect, not an environment limitation and not a mistake in the new test. The assertions require false return, nonempty error, and unchanged config, exactly as authorized.


**Round 3 gate table.** Commands use the unchanged `bash build_g2pr2/gate.sh LABEL ...`; command/exit/GNU-time/log receipts share the label under `build_g2pr2/logs/`. Gates 1–5 retain their Round 2 receipts and passes, including the owner's exact `invasion_tooling` exclusion; they were not rerun.

| Gate | Command | Exit | Wall | Log / result |
|---|---|---|---|---|
| 6, full | `env APP_TWINS=all JOBS=2 BUILD_JOBS=2 KEEP_OUT=1 bash wasm/ocean_parity.sh` | 1 | 41:32.14 | `build_g2pr2/logs/r3_06_ocean.log` — STOP: policy refusal changes config |
| 6, separate v2 | `python3 build_g2pr2/ocean_v2.py /tmp/ocean_parity.wNIuzY` | — | — | UNRUN after product-defect STOP |
| 7 | `bash build_g2pr2/module_gates.sh` | — | — | UNRUN; no production rebuild or forced second build |
| 8 | `bash build_g2pr2/web_gates.sh` | — | — | UNRUN; Turbo/save/type/UI checks not established |
| 9 | `bash build_g2pr2/site_audit.sh` | — | — | UNRUN; site assembly/final combined immutability gate not established |

Successful gate-6 components before STOP: all **124 historical cases** match native == Wasm == committed baselines at every chained step; both repeat-native controls are identical; all **124 appearance twins** and **22 default body-preview twins** pass. Body fixture: 127 bodies / 572 samples, digest `b9f6510154e9b597`; hydro fixture: 137 bodies, digest `055461f8a8792567`; both match native == Wasm == committed fixtures. Offline hydro reference passes. Preflight passes 124 accepted configs, 170 invalid-config refusals, preset/int/bool guards (19 / 11 / 8 keys), two nonfinite-state controls, and 26 live refusals with state preservation. These component passes do not make the full gate pass. Evidence directory: `/tmp/ocean_parity.wNIuzY`.

**Environment and coordinator reruns.** No additional ENVIRONMENT-BLOCKED test was observed in Round 3. `invasion_tooling` remains owner-excluded, not passed: Round 2 records both candidate and pristine-main coordinator receipts for the same pre-existing Python 3.14 check-50 failure. The final production build was not reached. The existing serial engine remains SHA-256 `ea4f6d9c998640a1f9f3cbfd371382e3e85b8198d1952ce20a1b670ff6666a3e`. Against that current engine, the exact outside-sandbox rerun is:

```bash
cd /home/harit/finfolk/work/trees/genome-v2-pr2
bash build_g2pr2/gate.sh coord_r3_final_invasion_tooling \
  ctest --test-dir build_serial --output-on-failure --stop-on-failure -j 1 \
  -R '^invasion_tooling$'
```

No other ENVIRONMENT-BLOCKED rerun command is needed. Browser-only checks remain skipped and delegated to the coordinator's laptop; they are not environment-blocked passes. No browser or network operation ran.

**Module hashes and Classic pin decision.** All six current module files still equal the approved-base bytes; these head-worktree hashes are stale outputs, **not generated-head results**. Gate 7's first and forced second production builds were not reached. New Classic hashes and second-build agreement are unavailable, so this run provides no new pin-decision evidence. No pin file was edited.

| Artifact | Approved base SHA-256 = current stale head-file SHA-256 | Rebuilt head / second-build match |
|---|---|---|
| `web/evo_boids.js` | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` | unavailable / UNRUN |
| `web/evo_boids.wasm` | `d05c4442e15d6850aeece60e52c2a69289d10a2d39fd17538b2347123be0a99b` | unavailable / UNRUN |
| `web/evo_boids_mt.js` | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` | unavailable / UNRUN |
| `web/evo_boids_mt.wasm` | `1c86e3d2a8c043e17ab1e75004ad37d9d20a70ce5498a80e4ae4bf4fdd8a703b` | unavailable / UNRUN |
| `web/evo_ocean.js` | `8bdce72bd8991c6e88768712b60cec9b7dd0cf22335d82ebe67f40cef6d91059` | unavailable / UNRUN |
| `web/evo_ocean.wasm` | `e55a4fcb2e7c2e737c6f0cc838c783237ba138336f1162ab4ddf037468b5f2f1` | unavailable / UNRUN |

Passed: Round 2 gates 1–5, retained unchanged, and the individually stated Round 3 gate-6 components. Failed: full gate 6, real policy-refusal mutation. Unrun: separate v2 Ocean comparisons, production rebuild/forced second build, gates 8–9, and browser-only checks. No own-test repair or gate retry was needed in Round 3. The only source change in Round 3 is the coordinator-authorized additions-only inventory extension; this report is also updated. All implementation files remain as received. Round 2 environment details, bounded jobs/threads, nice 19, frozen wrapper, and two-slot FIFO jobserver recipe are retained without modification. No pin, baseline, fixture, workflow, study reader, transport/physical law, or Step A header was edited. A stop-time read-only audit is evidence of unchanged bytes only; it does not count as running gate 9.

**Plan §7 coordinator commit split — exact file assignment.** This is a proposed split for eventual acceptance; no files are staged or committed. Each changed/untracked deliverable is assigned exactly once below. Files containing related edits for multiple stages stay whole in the earliest integration commit that needs them. Commit 4's six generated files remain planned and unchanged at STOP.

1. **Add the versioned log-weight codec and canonical brain primitives**

   `src/core/genome.hpp`, `src/core/weight_log.hpp`, `src/core/weight_log_table.hpp`, `src/core/weight_log_table.identity.json`, `tests/genome_v2_codec.cpp`, `tools/gen_log_weight_table.cpp`, `tools/gen_log_weight_table.py`.

2. **Wire opt-in H12 genomes through both engines and persistence**

   `CMakeLists.txt`, `src/app/main.cpp`, `src/core/brain_conversion.hpp`, `src/core/checkpoint_io.hpp`, `src/core/cluster_projection.hpp`, `src/core/config.hpp`, `src/core/connectivity.hpp`, `src/core/creature.hpp`, `src/core/genome_color.hpp`, `src/core/genome_v2_conversion.hpp`, `src/core/isolation.hpp`, `src/core/predator_brain.hpp`, `src/core/predator_stats.hpp`, `src/core/stats.hpp`, `src/core/transplant.hpp`, `src/core/world.hpp`, `src/core/world_common.hpp`, `src/ocean/fish.hpp`, `src/ocean/ocean_config.hpp`, `src/ocean/ocean_world.hpp`, `tests/genome_v2_cli.sh`, `tests/genome_v2_frontend.cpp`, `tests/genome_v2_reach.cpp`, `tests/genome_v2_test_helpers.hpp`, `tests/genome_v2_tests.cpp`, `tests/ocean_genome_v2_tests.hpp`, `tests/ocean_tests.cpp`, `tools/genome_v2_convert.cpp`, `tools/ocean_eye_exp.cpp`, `tools/ocean_fingerprint.hpp`, `wasm/evo_wasm.cpp`, `wasm/ocean_wasm.cpp`.

3. **Verify Genome v2 policy across inspectors and Ocean handoffs**

   `docs/genome_v2_pr2_report.md`, `src/render/sfml_renderer.cpp`, `tests/genome_v2_fault.py`, `tests/genome_v2_header_tests.cjs`, `tests/ocean_turbo_handoff.js`, `wasm/parity.sh`, `wasm/parity_driver.cpp`, `web/ocean.js`, `web/ocean_handoff.js`, `web/renderer.js`, `web/types.d.ts`, `web/ui_common.js`.

4. **Rebuild Classic and Ocean Wasm for Genome v2**

   `web/evo_boids.js`, `web/evo_boids.wasm`, `web/evo_boids_mt.js`, `web/evo_boids_mt.wasm`, `web/evo_ocean.js`, `web/evo_ocean.wasm`.

Everything remains uncommitted. Integration is blocked by the reported product defect; resumption requires a new instruction before changing product code.


**Final Round 3 receipt.** `r3_06_ocean` exited **1**, GNU-time wall **41:32.14** (the script reports 2,492 seconds internally). Plain native/Wasm each report **107 passed / 1 failed**; eye native/Wasm each report **114 passed / 1 failed**. Within both builds the entire printed unit output is byte-identical native == Wasm. Each invocation has exactly one failing test, `shim_ints`, with **28 of 540 checks failed**; `shim_bools` passes **783 checks** in all four invocations. The size assertions now pass: the remaining failures expose the product defect above. Unit-output hashes and summaries are in `build_g2pr2/logs/r3_unit_summary.json`; full unit logs are `tests{,_eye}.{native,wasm}.txt` in `/tmp/ocean_parity.wNIuzY`.

Stop-time read-only evidence: `build_g2pr2/logs/r3_stop_protected.json` records **205 protected tracked paths** equal to approved base `6bc66a9156d67b62053972b6bc351a5400f3b47a`. A separate comparison against the original stop snapshot confirms **115 product/source files** unchanged. The final serial engine and all six production artifacts pass `sha256sum -c build_g2pr2/logs/r2_stop_artifacts.sha256`; both frozen wrapper/environment files pass `sha256sum -c build_g2pr2/logs/r3_frozen_wrappers.sha256`. The authorized test diff remains additions only. These reporting audits are not later acceptance gates. Round 2 gate receipts are retained, and no pin, module, baseline, fixture, existing assertion, or product source was changed in Round 3.


## Round 4 — 2026-11-25

Status: **STOP at gate 8 (TypeScript); gates 1–7 passed, incomplete and not ready for integration**. The coordinator authorized fixing the PR's policy-refusal state defect and restarting gates 1–9. All changes remain uncommitted; no network, pin edit, baseline update, merge or deployment is authorized or performed.

**Fix and choice.** `readOceanJson` now reads into scratch SimConfig/OceanConfig objects when any of the four new schema keys is present, and commits both only after all existing checks succeed. This is smaller than changing the shared void `checkpoint::readConfig` API and its callers, and follows the existing shim pattern. The internal raw-reader invalid sentinel stays confined to the scratch config. Inputs containing only pre-existing keys retain their original direct-read behavior. No existing check is moved or reordered; no pre-existing key's acceptance, refusal, or load behavior changes. `weightMutationMode` is a pre-existing PR-1 key: its handling stays intact, while a refused new-policy read preserves its original value along with every other field. `src/core/checkpoint_io.hpp` therefore needs no Round 4 change. All gates nevertheless restart at gate 1 as requested.

```diff
--- src/ocean/ocean_config.hpp (Round 3)
+++ src/ocean/ocean_config.hpp (Round 4)
@@ -435,11 +435,20 @@
 // range (checked before the reader casts it, every occurrence of the key), a
 // SimConfig bool key that is not a JSON true / false, or an Ocean bool key
 // that is not true / false / 0 / 1 (every occurrence of either).
-inline bool readOceanJson(const char* json, SimConfig& sc, OceanConfig& oc, std::string& err) {
+inline bool readOceanJson(const char* json, SimConfig& simConfig, OceanConfig& oceanConfig, std::string& err) {
     if (!json || !json[0]) return true;
     const std::string wrapped = std::string("{\"config\":") + json + "}";
     jsonm::Value root;
     if (!jsonm::Parser::parse(wrapped, root, err)) { err = "config parse error: " + err; return false; }
+    const auto* config = root.find("config");
+    const bool policyInput = config && (config->find("genomeVersion") || config->find("biasGenes") ||
+                                       config->find("hiddenNeurons") || config->find("brainEvalVersion"));
+    // New policy reads commit both configs only on success. Keep the older
+    // keys' read/check order and refusal behavior when no new policy is supplied.
+    SimConfig nextSim = simConfig;
+    OceanConfig nextOcean = oceanConfig;
+    SimConfig& sc = policyInput ? nextSim : simConfig;
+    OceanConfig& oc = policyInput ? nextOcean : oceanConfig;
     using T = jsonm::Value::Type;
     if (const jsonm::Value* o = root.find("config"); o && o->isObject())
         for (const auto& kv : o->obj) {
@@ -485,6 +494,10 @@
     }
     if (const jsonm::Value* o = root.find("config"))
         if (!readOceanConfig(*o, oc, &err)) return false;
+    if (policyInput) {
+        simConfig = nextSim;
+        oceanConfig = nextOcean;
+    }
     return true;
 }
 
```

**Entry-point audit (line numbers in the Round 4 working tree).**

| Entry point | Location | Result / action |
|---|---|---|
| Ocean JSON | `src/ocean/ocean_config.hpp:438` (`readOceanJson`), shared raw read/validation at 490–500 | FIXED: explicit new-policy input selects two scratch configs; every false return leaves both original objects untouched, including policy, mutation mode, analysis fields and Ocean fields. |
| Ocean startup | `wasm/ocean_wasm.cpp:346` (`oc_init`), local configs at 349–352, commit at 374–380 | Already safe: refusal discards local configs before RNG seeding or replacing the world. No change. |
| Ocean live | `wasm/ocean_wasm.cpp:654` (`oc_set_param`), allowlist refusal at 705; copies/validation/commit at 726–739 | Already safe: all five policy settings are restart-only and absent from live allowlists. Accepted old keys modify copies, then validate before commit. No change. |
| Ocean general validator | `src/ocean/ocean_config.hpp:715` (`oceanSimConfigError`), `src/core/config.hpp:490` (`brainPolicyConfigError`) | Const-reference validation only; cannot mutate either config. No change. |
| Classic raw JSON reader | `src/core/checkpoint_io.hpp:243` (`readConfig`), raw guard/sentinel at 246 and schema assignments at 247–250 | Internal void decoder, not a refusing public API. It intentionally marks invalid policy for its caller. Every Classic JSON caller uses a disposable local config; changing sentinel behavior would risk accepting invalid inputs. Left alone. Ocean now isolates its result. |
| Classic JSON startup | `wasm/evo_wasm.cpp:374` (`evo_init`), local/read at 380–388, validation at 390–425 | Already safe: invalid candidate is discarded before destination creation/replacement and RNG writes. No change. |
| Classic checkpoint | `src/core/checkpoint_io.hpp:568` (v3 config preflight), 1360–1385 (format dispatch/old-format policy guards), 1394–1400 (destination config read) | Already safe for new-policy refusal: v3 preflights local policy config before world preparation; formats 1/2 check raw policy and a disposable defaults config before destination writes. Later direct destination decoding sees an already-approved policy. No change to old-format load behavior. |
| Classic CLI | `src/app/main.cpp:314` (policy parsing), 444–457 (strict lengths/pre-clamp policy check), later general validation | On refusal the process aborts the whole startup and its local config is discarded; no world/save is published. Left alone as instructed. |
| Classic live | `wasm/evo_wasm.cpp:478` (`evo_set_param`), 490–493 (restart refusal), 507–517 (copy/check/commit) | Already safe: five policy fields are outside allowlist; old-key updates use a local copy and commit after validation. No change. |
| Transplant | `src/core/transplant.hpp:147` (receiver reference), 150–184 (local donor decode/preflight/policy comparison) | Already safe: donor config `yc` is local, discarded on refusal; schema equality is checked before population reading/selection. No receiver config assignment. No change. |
| Conversion | `src/core/genome_v2_conversion.hpp:7` (`convertWorldToGenomeV2`), 22–31 (target config), 33–67 (temporary populations), 74–77 (commit); `tools/genome_v2_convert.cpp` | Already safe: source/target policy validation and population conversion precede all swaps/config assignment. Utility aborts before output writing on refusal. No change. |

**Tests.** The Round 3 `tests/ocean_tests.cpp` inventory extension is unchanged (hash recorded before edits in `build_g2pr2/logs/r4_frozen_inputs.sha256`). The added `testGenomeV2` regression in `tests/ocean_genome_v2_tests.hpp` snapshots the live original objects' raw bytes and SimConfig dump, checks false/nonempty error, and compares every original byte after unsupported values, repeated integers/bool, incoherent policy, invalid/repeated mutation mode and combined Ocean/policy input. It starts from both v1/legacy and v2/bias/saturating configs, with analysis and Ocean sentinel fields set. No other entry point required a fix, so no other fix-specific test is needed. Existing Classic/Ocean startup/live/checkpoint/transplant/conversion regressions remain in the full gates.

The new named mutant is `policy_assign_then_validate` in `tests/genome_v2_fault.py`: bypass the scratch SimConfig reference, reintroducing raw assignment before policy validation. It must compile, exit 1 with `policy refusal preserves all config bytes`, and have passing clean Ocean controls before and after. Inventory grows from 35 to 36 named mutants. Results are pending gate 2. During pre-run source review, the new combined invalid-Ocean test used `eye:{}`, which the historical reader intentionally ignores; it was corrected to `deepCurrent:{}` before that test was compiled/run. No gate failure or product change resulted from this test-authoring correction.

**Environment.** Frozen `gate.sh` and `env.sh` are unchanged. Every gate runs through `bash build_g2pr2/gate.sh LABEL COMMAND...`, at nice 19 with at most two jobs/two threads, `RQ_TEST_WORKERS=2`, `EMCC_CORES=1`, `BINARYEN_CORES=2`, and CTest `--stop-on-failure -j 1 -E '^invasion_tooling$'`. Gate 3 retains the two-slot FIFO jobserver for LTO. The owner-excluded pre-existing Python 3.14 `invasion_tooling` failure is not a pass. Browser-only checks remain skipped. Final receipts, hashes, exact outside-sandbox command and commit split will be recorded after gates finish or stop.

Gate 1 **PASS**: `bash build_g2pr2/gate.sh r4_01_native bash build_g2pr2/native_gates.sh`, exit 0, wall **15:14.30**, maximum RSS 811,920 KiB. Serial 14/14 selected tests, OpenMP 7/7, pool 7/7; focused plain and eye Ocean each pass **66 checks** (44 new refusal-state checks plus the existing feature checks). The only exclusion is the owner's `invasion_tooling`. Gate 2 started with the complete 36-mutant inventory and all original subsequent fault suites. No own-test failure or environment-only failure has been observed in Round 4.

Gate 2 named-suite component **PASS**: all **36/36** named mutants caught, all 34 native mutant builds exit 0, both Node mutants fail their named assertions, and all 14 clean controls before/after pass. Evidence: `build_g2pr2/genome_v2_fault.8gmq9bdg/`. The new mutant's compile exits 0 (55.838 s); runtime exits 1 with `FAIL genome_v2 ... first: policy refusal preserves all config bytes: {"genomeVersion":12,"targetFood":321,"waveSpeed":9}`. Compile failure, unrelated crash, and unrelated assertion probes were rejected and are not catches. The complete gate 2 is still running the original plain/eye transport, label-mask, and hydro fault suites; this component result is not yet a full gate-2 pass.

Continuation audit: the first Round 4 gate-2 invocation has no exit receipt and its last evidence was written at 2026-11-25 20:28 UTC (15:28 EST); it was no longer progressing when work resumed at 2026-11-26 00:14 UTC. Its partial command/log/time receipts are preserved as `r4_02_mutants_interrupted.*`. No completed full gate-2 result is claimed from that invocation. Gate 1 and frozen-input hashes were verified; gate 2 restarts in full before gates 3–9, using the unchanged scripts/environment. This is an interrupted run, not a test failure or an own-test repair.

Completed gate 2: `r4_02_mutants` exit 0, wall **55:07.27**. Restarted named-suite evidence is `build_g2pr2/genome_v2_fault.ip7y6lbk/`: 36/36 catches, 34 successful native mutant compilations, 2 Node catches, 14 passing clean controls, and all three invalid-runner probes rejected. `policy_assign_then_validate` compiles with exit 0 (55.407 s), then exits 1 on the named byte-preservation assertion. Plain/eye transport suites pass every mutant and both clean controls; plain/eye label-mask untouched controls pass 2,991 / 3,186 checks; both hydro-reference mutants are caught. Gate 3 comparison builds exit 0 (0.90 s), including the FIFO jobserver recipe; unchanged native Classic dependencies were already up to date. The three complete identity workloads are now running. No own-test repair or new environment-only failure has occurred.

Gates 3–5 completed successfully. Gate 3 reports `IDENTICAL` for **268 files / 27 scenarios × 3** (approved base/head serial, production-pinned/head fast serial, approved base/head explicit saturation-only v1). Gate 4 native/Wasm exhaustive codec and focused outputs agree, and both generator checks retain the canonical table hash. Gate 5 passes every Classic case and all four v2 midpoint continuation checks (uninterrupted native == resumed native == resumed Wasm). Full Ocean gate 6 has started with all historical cases, `APP_TWINS=all`, default body twins and unit tests. Detailed final receipt table follows when complete.

Full gate 6 **PASS**: `r4_06_ocean` exit 0, wall **40:13.97**, evidence `/tmp/ocean_parity.eT0ET8`. All 124 historical cases match native == Wasm == committed baseline, both repeat-native controls pass, all 124 appearance twins and 22 default body-preview twins pass. Body/hydro fixtures retain digests `b9f6510154e9b597` / `055461f8a8792567`, and the offline hydro reference passes. Plain native/Wasm each pass **108 tests / 0 failures**; eye native/Wasm each pass **115 / 0**; complete printed output matches within each build. In all four unit runs, the unchanged Round 3 inventory passes (`shim_ints`: 540; `shim_bools`: 783), and the new regression passes 66 checks. The separate v2 Ocean recipe is now running; later gates remain pending.

Separate v2 Ocean gate **PASS**: `r4_06_v2` exit 0, wall **2:38.63**; all plain/eye × bias-off/on cases match native == Wasm == repeat-native, with capture, asserted births, appearance-off native/Wasm twins, and body-preview native/Wasm twins with asserted founders/offspring. Production gate 7 **PASS**: `r4_07_modules` exit 0, wall **1:39.68**. All six generated modules match a forced second compile/link byte for byte. The unchanged module wrapper retains its historical `r2_modules_{first,second}.sha256` evidence filenames; copies named `r4_modules_{first,second}.sha256` preserve the Round 4 provenance. No pin file is edited. Gate 8 is running.

**Final Round 4 status: STOP at gate 8, existing TypeScript gate failure; incomplete and not ready for integration.** Gates 1–7 pass on the Round 4 source, including both parts of gate 6 and the forced second production build. No later gate or implementation repair follows the failure.
Gate 8 first passed the complete real Turbo/save suite (**646 / 646 checks**, 353.8 s), including the new v2 main save/open, setup metadata, actual-policy exports, forged/repeated policy-header refusal, and Turbo/back continuation cases. Offline `npm ci` succeeded. The next command, `npx --no-install --offline --cache "$WORK/npm-cache" tsc -p tsconfig.json`, exited **2**:
```text
web/ui_common.js(265,53): error TS2454: Variable 'yIn' is used before being assigned.
web/ui_common.js(265,59): error TS2454: Variable 'yOut' is used before being assigned.
web/ui_common.js(265,79): error TS2454: Variable 'xS' is used before being assigned.
web/ui_common.js(265,84): error TS2454: Variable 'xA' is used before being assigned.
```
The PR's added `biasPos` expression at `web/ui_common.js:265` uses variables initialized in the preceding layout branches (`yIn`/`yOut` at 255; `xS`/`xA` at 260). TypeScript does not establish definite assignment through the later conditional expression. This is an existing acceptance check failing on this PR's implementation, not an own-test/script mistake or a sandbox-blocked call. No runtime defect beyond the failed static check is claimed. Under the STOP rule, the source is left unchanged and no retry is made.
**Final gate receipts.** Every command below was invoked as `bash build_g2pr2/gate.sh LABEL COMMAND...`; the table shows COMMAND. The frozen wrapper records the command, exit, GNU-time wall/RSS, and log under `build_g2pr2/logs/LABEL.{command,exit,time,log}`.
| Gate | Command | Exit | Wall | Log |
|---|---|---:|---|---|
| 1 | `bash build_g2pr2/native_gates.sh` | 0 | 15:14.30 | `build_g2pr2/logs/r4_01_native.log` |
| 2 | `bash build_g2pr2/mutant_gates.sh` | 0 | 55:07.27 | `build_g2pr2/logs/r4_02_mutants.log` |
| 3, builds | `bash build_g2pr2/comparison_builds.sh` | 0 | 0:00.90 | `build_g2pr2/logs/r4_03_builds.log` |
| 3, identity | `bash build_g2pr2/identity_gates.sh` | 0 | 5:31.69 | `build_g2pr2/logs/r4_03_identity.log` |
| 4 | `bash build_g2pr2/wasm_focused.sh` | 0 | 1:39.84 | `build_g2pr2/logs/r4_04_focused.log` |
| 5 | `env KEEP_OUT=1 PARITY_DIR=/home/harit/finfolk/work/trees/genome-v2-pr2/build_g2pr2/classic_parity bash wasm/parity.sh` | 0 | 3:32.63 | `build_g2pr2/logs/r4_05_classic.log` |
| 6, full | `env APP_TWINS=all JOBS=2 BUILD_JOBS=2 KEEP_OUT=1 bash wasm/ocean_parity.sh` | 0 | 40:13.97 | `build_g2pr2/logs/r4_06_ocean.log` |
| 6, separate v2 | `python3 build_g2pr2/ocean_v2.py /tmp/ocean_parity.eT0ET8` | 0 | 2:38.63 | `build_g2pr2/logs/r4_06_v2.log` |
| 7 | `bash build_g2pr2/module_gates.sh` | 0 | 1:39.68 | `build_g2pr2/logs/r4_07_modules.log` |
| 8 | `bash build_g2pr2/web_gates.sh` | 2 | 5:58.61 | `build_g2pr2/logs/r4_08_web.log` |
| 9 | `bash build_g2pr2/site_audit.sh` | — | — | UNRUN after gate-8 STOP |

The gate-2 interrupted invocation is preserved separately and is not counted as passing. The full restart of gate 2 passed. No own-test repair/retry was needed during completed Round 4 gates. The pre-compilation `eye:{}` test-authoring correction is recorded above. Gate 1 is its completed Round 4 invocation, with unchanged source thereafter; its receipt was verified on continuation.
**Passed versus unrun.** Passed: gate 1 serial 14/14 selected CTests, OpenMP 7/7, pool 7/7, focused plain/eye regression; all gate-2 suites; all three 268-file/27-scenario identity comparisons; gate-4 exhaustive codec (51,203 accepted words / 14,333 rejected, digest `ebb6ca6dfa1db0a5`) and focused native/Wasm parity; all 35 Classic parity cases and four v2 midpoint continuations; full Ocean and four separate v2 profiles; all six production artifacts reproduced by forced second build. Gate 8 component passes: real Turbo/save 646/646 and offline package installation. Failed: gate-8 TypeScript check. Unrun after that failure: gate-8 header, UI and renderer checks listed below, and all of gate 9 (site assembly and final combined acceptance audit).
```bash
node tests/genome_v2_header_tests.cjs
node tests/ui_common_tests.cjs
node tests/ui_parity_harness_tests.mjs
node tests/ui_inspector_tests.cjs
node tests/ocean_shader_slots_tests.cjs
node tests/ocean_materials_tests.cjs
node tests/ocean_render_opt_tests.cjs
node tests/ocean_mock_three_tests.mjs
node tests/ocean_appearance_slots_tests.cjs
bash build_g2pr2/site_audit.sh
```
The header test did execute successfully as clean controls in gate 2; its separate gate-8 invocation above is still unrun. Browser-only `ocean_render_browser.mjs` and `ocean_body_gpu.mjs` remain intentionally skipped, not passes. No browser or network operation was attempted.
**ENVIRONMENT-BLOCKED / owner exclusion.** No additional Round 4 test failed because this sandbox blocked a system call. `invasion_tooling` remains excluded by exact name (`ctest --stop-on-failure -j 1 -E '^invasion_tooling$'`), not passed: its original sandbox failure was forkserver socket creation denied with `PermissionError: [Errno 1] Operation not permitted`; the coordinator's outside-sandbox candidate and pristine-main reruns both reached the same owner-excluded pre-existing Python 3.14 check-50 failure. No workaround was applied to the existing test. The exact coordinator command against the final native engine is:
```bash
cd /home/harit/finfolk/work/trees/genome-v2-pr2
bash build_g2pr2/gate.sh coord_r4_final_invasion_tooling \
  ctest --test-dir build_serial --output-on-failure --stop-on-failure -j 1 \
  -R '^invasion_tooling$'
```
The final native serial engine SHA-256 is `ea4f6d9c998640a1f9f3cbfd371382e3e85b8198d1952ce20a1b670ff6666a3e` (`build_g2pr2/logs/r4_final_serial.engine.sha256`). No further ENVIRONMENT-BLOCKED command needs a coordinator rerun. The type-check failure is not environment-blocked.
**Generated modules and pin decision.** Base is `6bc66a9156d67b62053972b6bc351a5400f3b47a`. Head hashes below are generated Round 4 bytes; each matches both the first build and the forced second compile/link. Full receipts are `build_g2pr2/logs/r4_modules_{first,second}.sha256`. These hashes are evidence for the owner's Classic pin decision; no pin file is edited, and the failed type gate still prevents acceptance.
| Artifact | Base SHA-256 | Rebuilt head SHA-256 | Forced second build |
|---|---|---|---|
| `web/evo_boids.js` | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` | `d6bb9272dff5e730e908be03128db1b697757e976571448b9f074839ae698733` | byte-identical |
| `web/evo_boids.wasm` | `d05c4442e15d6850aeece60e52c2a69289d10a2d39fd17538b2347123be0a99b` | `1afc01039a1d45ac3528529e06ee48069277d9a6f6f964f3edc9797f5f32d7ea` | byte-identical |
| `web/evo_boids_mt.js` | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` | `c415499ac0d5acb0cb9b332bf794b32348473fc77624f0689cb0c85fc3b18c9e` | byte-identical |
| `web/evo_boids_mt.wasm` | `1c86e3d2a8c043e17ab1e75004ad37d9d20a70ce5498a80e4ae4bf4fdd8a703b` | `a203d8474fddc568f08c4dc12cff7b8199bb729890b52cdf77c318727dfa73f1` | byte-identical |
| `web/evo_ocean.js` | `8bdce72bd8991c6e88768712b60cec9b7dd0cf22335d82ebe67f40cef6d91059` | `f4a017ab30c7803df50eca752e8851b81ce17f7e4791ff1b2648c579be8355d8` | byte-identical |
| `web/evo_ocean.wasm` | `e55a4fcb2e7c2e737c6f0cc838c783237ba138336f1162ab4ddf037468b5f2f1` | `8502a36ba40d31c59a5d8f42d38a6dda60f61f01a42dfe6414b228893259de70` | byte-identical |

**Deviations and stop-time read-only evidence.** The prescribed Round 2/3 environment, nice 19, two-job/two-thread limits, `RQ_TEST_WORKERS=2`, FIFO LTO jobserver, CTest stop-on-failure/exclusion, and frozen `gate.sh`/`env.sh` were retained. Gate 3 invoked every comparison build explicitly; unchanged native Classic dependencies were up to date. Gate 8 used the established offline npm cache to honor the no-network rule. The interrupted partial gate-2 attempt was preserved and restarted in full; no failing implementation gate was retried. Untracked Python bytecode produced by native tests was removed. No baseline, fixture, pin, study reader, workflow, physical/transport law, or Step A extracted header changed.
A read-only stop snapshot confirms all **205 protected tracked files** still equal the approved base (`build_g2pr2/logs/r4_stop_protected.json`). The frozen inventory and wrappers pass their original SHA-256 check. `r4_stop_deliverables.sha256` records the 56 deliverables other than this subsequently finalized report; `r4_stop_status.txt` and `r4_commit_split.json` record all 57 changed/untracked deliverables. These reporting snapshots are not gate 9 and do not claim site assembly or final acceptance.
**Plan §7 coordinator commit split — each file assigned exactly once.** Validated against all 57 changed/untracked deliverables; no staging or commits. Files with related edits across stages stay whole in the earliest integration stage that needs them.

1. **Add the versioned log-weight codec and canonical brain primitives**

   `src/core/genome.hpp`, `src/core/weight_log.hpp`, `src/core/weight_log_table.hpp`, `src/core/weight_log_table.identity.json`, `tests/genome_v2_codec.cpp`, `tools/gen_log_weight_table.cpp`, `tools/gen_log_weight_table.py`.

2. **Wire opt-in H12 genomes through both engines and persistence**

   `CMakeLists.txt`, `src/app/main.cpp`, `src/core/brain_conversion.hpp`, `src/core/checkpoint_io.hpp`, `src/core/cluster_projection.hpp`, `src/core/config.hpp`, `src/core/connectivity.hpp`, `src/core/creature.hpp`, `src/core/genome_color.hpp`, `src/core/genome_v2_conversion.hpp`, `src/core/isolation.hpp`, `src/core/predator_brain.hpp`, `src/core/predator_stats.hpp`, `src/core/stats.hpp`, `src/core/transplant.hpp`, `src/core/world.hpp`, `src/core/world_common.hpp`, `src/ocean/fish.hpp`, `src/ocean/ocean_config.hpp`, `src/ocean/ocean_world.hpp`, `tests/genome_v2_cli.sh`, `tests/genome_v2_frontend.cpp`, `tests/genome_v2_reach.cpp`, `tests/genome_v2_test_helpers.hpp`, `tests/genome_v2_tests.cpp`, `tests/ocean_genome_v2_tests.hpp`, `tests/ocean_tests.cpp`, `tools/genome_v2_convert.cpp`, `tools/ocean_eye_exp.cpp`, `tools/ocean_fingerprint.hpp`, `wasm/evo_wasm.cpp`, `wasm/ocean_wasm.cpp`.

3. **Verify Genome v2 policy across inspectors and Ocean handoffs**

   `docs/genome_v2_pr2_report.md`, `src/render/sfml_renderer.cpp`, `tests/genome_v2_fault.py`, `tests/genome_v2_header_tests.cjs`, `tests/ocean_turbo_handoff.js`, `wasm/parity.sh`, `wasm/parity_driver.cpp`, `web/ocean.js`, `web/ocean_handoff.js`, `web/renderer.js`, `web/types.d.ts`, `web/ui_common.js`.

4. **Rebuild Classic and Ocean Wasm for Genome v2**

   `web/evo_boids.js`, `web/evo_boids.wasm`, `web/evo_boids_mt.js`, `web/evo_boids_mt.wasm`, `web/evo_ocean.js`, `web/evo_ocean.wasm`.

All work remains uncommitted. Integration is blocked by the gate-8 TypeScript failure. Gate 9 and the later gate-8 checks remain unrun; the coordinator's outside-sandbox invasion rerun and owner's pin decision remain outstanding.

# Ocean world split, Step A

Base: `c5b6b42ac0bbb8b585423a579aebaf69083b0c61`, tree
`8be688e5e7ba4d7a44bff53185ea111f08018a1d`, branch `ocean-split-a`.
The pristine `build_splitA/base/` copy matched all 443 available tracked files
before extraction. Changes are uncommitted for the coordinator.

Status: the builder ran the move map's gates 1–7 on the server, except gate 7's
SFML-dependent Classic checks, plus the performance comparison (gate 9); its
"gate 8" below is that performance report. The map's **browser gate 8** and the
rest of gate 7 were run afterwards by the coordinator; see "Coordinator gates"
at the end. The extraction and gates 1–4 were retained from the earlier run; no
production source or existing test was changed during this continuation.
All 352 recorded source/test/tool hashes still match the handoff. The saved gate 5
and production rebuild receipts were independently checked before continuing.
All changes remain uncommitted. Commands and wall times are recorded in
`build_splitA/logs/gates.jsonl`.

## Extraction

The v2 map is followed exactly: 68 member definitions move, 41 definitions
remain in class, and two complete top-level entity types move. Every field,
nested type, access region, declaration position and Brief 01 transport wrapper
remains in `OceanWorld`. No component or sensing subdivision is introduced.

| Destination | Moved definitions |
|---|---:|
| `src/ocean/ocean_entities.hpp` | 2 whole types: `OceanFood`, `OceanPredator` |
| `src/ocean/ocean_world_util.hpp` | 10 members |
| `src/ocean/ocean_walls.hpp` | 4 members |
| `src/ocean/ocean_eye.hpp` | 10 members, eye guarded |
| `src/ocean/ocean_side_tracks.hpp` | 35 members |
| `src/ocean/ocean_sensing.hpp` | 6 members, including the complete scans/templates |
| `src/ocean/ocean_predators.hpp` | 3 members |

The six implementation headers follow the complete class in the mapped order.
Ordinary definitions have explicit `inline`; static identity stays on the class
declarations. Template defaults occur only on declarations, and the private
`FoodSeen*` return is qualified. Entities include `../core/predator.hpp` and are
self-contained. No navigation comment was added. Existing comments retain their
text; the two signature comments `/*R*/` necessarily also occur in the new
declarations. The only test-script change is the `ENGINE` path in
`tests/label_mask_fault.sh`, from `ocean_world.hpp` to `ocean_sensing.hpp`.

## Map deviations

None. All mapped spans applied, and the exact projected line counts were obtained.

## Extraction audit

`build_splitA/audit.py` lexes definitions independently of the extraction's body
replacement, checks every qualified signature exactly once, and compares all 68
moved brace-delimited bodies both byte-for-byte and token-for-token. All 41
retained definitions are byte-identical. Both complete entity definitions match.
Replacing every body with its declaration yields identical class tokens,
including fields, nested types, guards, access labels and member order. Pre-class
helpers, existing dependencies and the implementation-include order also match.
The comment multiset matches after accounting for the two repeated parameter
comments. The fingerprint header, transport/flow headers and protected test files
are byte-identical.

The first two audit runs failed only because of mistakes in this task's script:
its qualifier counter expected joined `::` after tokenizing colons separately;
then its comment counter did not account for the two parameter comments repeated
in declarations. Each check was corrected and rerun, twice total. The third run
passed. Neither correction changed production code or an existing test.

All seven consuming translation units passed syntax checking and object-code
compilation in 26 applicable combinations: plain/eye × profiler off/on, except
the eye-only experiment's two applicable combinations. Both
`OCEAN_TESTS_NO_SHIM` syntax configurations passed too. Objects use `-O0`; the
standalone plain and eye test executables use `-O3`. All use C++20,
`-ffp-contract=off`, and `EVO_WORLD_OCEAN`.

## Gates

Commands run at nice 19, with at most two jobs and two threads per job.
Emscripten uses 6.0.4, a copied writable cache, `EMCC_CORES=1`, and no network.
The full parity invocation sources emsdk before selecting the cache, unsets
`LDFLAGS`, `CMAKE_PREFIX_PATH`, `SFML_DIR`, `CPPFLAGS`, `CXXFLAGS`, `FAST`,
`ONLY`, `NO_EYE`, `NO_TESTS`, `BODY_TWINS`, `NATIVE_CXXFLAGS` and
`OCEAN_PARITY_DIR`, and sets `APP_TWINS=all JOBS=2 BUILD_JOBS=2 KEEP_OUT=1`.
Its script is `build_splitA/phase4.sh`.

Full parity exited 0 in 2518.091 seconds: **124/124 baseline cases**,
**124/124 appearance twins**, **22/22 default body twins**, 170 refused-config
checks, 26 live refusals, both removed-nonfinite checks, repeatability, both
fixtures and the hydro reference. All four full unit runs passed: **107 plain**
and **114 eye** tests, with native/Wasm printed output identical. Artifacts
remain at `/tmp/ocean_parity.cdQIXn`. The body fixture digest is
`b9f6510154e9b597`; the hydro fixture digest is `055461f8a8792567`.
No baseline, fixture or fingerprint was changed.

All six focused modes and two `--accepts` invocations passed in each native
plain/eye executable. The full parity gate also ran the complete native/Wasm
units.

| Command | Exit | Wall seconds | Log under `build_splitA/logs/` |
|---|---:|---:|---|
| `bash build_splitA/base_record.sh` | 0 | 1.212 | `base-record.log` |
| `python3 build_splitA/audit.py` | 1 | 0.191 | `extraction-audit.log` |
| `python3 build_splitA/audit.py` | 1 | 1.352 | `extraction-audit-r2.log` |
| `python3 build_splitA/audit.py` | 0 | 1.241 | `extraction-audit-r3.log` |
| `source build_splitA/emsdk.sh; test "$EMCC_CORES" = 1; test -d "$EM_CACHE/sysroot"; du -sh "$EM_CACHE"` | 0 | 1.691 | `prepare-em-cache.log` |
| `python3 build_splitA/compile_consumers.py` | 0 | 126.350 | `compile-consumers.log` |
| `g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tests/ocean_tests.cpp -o build_splitA/bin/ocean_tests` | 0 | 100.594 | `units-build-plain.log` |
| `g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -DEVO_OCEAN_EYE -I src tests/ocean_tests.cpp -o build_splitA/bin/ocean_tests_eye` | 0 | 128.051 | `units-build-eye.log` |
| `python3 build_splitA/compile_consumers.py --codegen` | 0 | 287.016 | `codegen-consumers.log` |
| `bash build_splitA/focused.sh` | 0 | 65.844 | `focused-units.log` |
| `python3 build_splitA/audit.py` | 0 | 1.222 | `extraction-confirm.log` |
| `python3 tests/ocean_transport_fault.py --out build_splitA/logs/transport-fault-plain-r2` | 0 | 820.058 | `transport-fault-plain-r2.log` |
| `python3 tests/ocean_transport_fault.py --eye --out build_splitA/logs/transport-fault-eye` | 0 | 1115.185 | `transport-fault-eye.log` |
| `bash tests/label_mask_fault.sh` | 0 | 371.723 | `label-mask-fault-plain.log` |
| `EYE=1 bash tests/label_mask_fault.sh` | 0 | 448.420 | `label-mask-fault-eye.log` |
| `g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_reference.cpp -o build_splitA/bin/hydro_reference && build_splitA/bin/hydro_reference && python3 tests/ocean_hydro_reference_mutants.py && build_splitA/bin/hydro_reference` | 0 | 44.009 | `hydro-mutants.log` |
| `bash build_splitA/phase4.sh` | 0 | 2518.091 | `parity-full.log` |
| `bash build_splitA/scope.sh` | 0 | 2.229 | `handoff-scope-audit.log` |
| `python3 build_splitA/identity_build.py` | 0 | 116.193 | `identity-build.log` |
| `python3 build_splitA/identity.py` | 0 | 782.845 | `identity-whole-run.log` |
| `bash build_splitA/phase6.sh` | 0 | 37.243 | `production-rebuild.log` |
| `python3 build_splitA/verify_saved.py && python3 build_splitA/continuation_final.py` | 0 | 0.305 | `saved-evidence-verification.log` |
| `node tests/ocean_turbo_handoff.js` | 0 | 316.234 | `turbo-handoff-r2.log` |
| `build_splitA/bin/ocean_tests` | 0 | 195.910 | `native-ocean-plain.log` |
| `build_splitA/bin/ocean_tests_eye` | 0 | 233.459 | `native-ocean-eye.log` |
| `bash build_splitA/classic.sh` | 0 | 213.373 | `native-classic.log` |
| `bash wasm/build_site.sh` | 0 | 0.552 | `site.log` |
| `npm ci --offline --cache "$PWD/build_splitA/npm_cache" --no-audit --no-fund && npx --offline --cache "$PWD/build_splitA/npm_cache" tsc -p tsconfig.json` | 0 | 4.706 | `offline-types.log` |
| `node tests/ocean_appearance_slots_tests.cjs && node tests/ocean_shader_slots_tests.cjs && node tests/ocean_materials_tests.cjs && node tests/ocean_render_opt_tests.cjs && node tests/ocean_mock_three_tests.mjs` | 0 | 33.019 | `web-pure-checks.log` |
| `bash build_splitA/scope.sh` | 0 | 0.134 | `scope-checks.log` |
| `python3 build_splitA/perf.py` | 0 | 430.457 | `perf-native.log` |
| `source build_splitA/emsdk.sh && env -u LDFLAGS -u CMAKE_PREFIX_PATH -u SFML_DIR -u CPPFLAGS -u CXXFLAGS python3 build_splitA/perf.py --wasm` | 0 | 208.254 | `perf-wasm.log` |
| `bash build_splitA/final_scope.sh` | 0 | 0.265 | `final-scope.log` |

The native Ocean reruns passed 107 plain and 114 eye tests. The serial native
Classic build and its four core test targets passed; SFML was unavailable, so
the window application and its dependent tests were not built. Site assembly,
offline npm installation/type checking, the five Node appearance/shader/material/
render checks, and final scope checks passed. Browser checks remain reserved for
the coordinator.

The earlier Turbo log had no completion receipt and is not counted as a pass.
The complete rerun against the rebuilt production bytes has its own exit-0
receipt and log: **597/597 checks passed**. The final scope audit repeats the
protected-path byte checks and `git diff --check`; its stat includes the
generated Ocean Wasm change.

Final tracked diff against the base (new headers/report are untracked):

```text
 src/ocean/ocean_world.hpp | 1284 +++------------------------------------------
 tests/label_mask_fault.sh |    2 +-
 web/evo_ocean.wasm        |  Bin 349424 -> 349745 bytes
 3 files changed, 78 insertions(+), 1208 deletions(-)
```

The final scope audit confirms 33 Classic source files, 125 baseline files,
four fixture files and all four Classic module artifacts unchanged. The seven
new headers and this report are untracked, so Git's tracked diff stat excludes
them; they are listed in the final log's status and the tables in this report.
No Classic, baseline or fixture path appears in the diff.

## Mutation results

All 27 planted mutants compiled and failed their intended assertions: nine
plain transport, ten eye transport, three plain label-mask, three eye label-mask,
and two hydro reference mutants. Every clean control passed. Transport copies
retain individual build and assertion logs under
`build_splitA/logs/transport-fault-plain-r2/` and
`build_splitA/logs/transport-fault-eye/`. The first plain transport attempt had
no completion receipt (seven detections logged); the full rerun passed.

| Mutant | Plain failing check/count | Eye failing check/count |
|---|---|---|
| `live_frame` | `flow_state`, 10/118 | `flow_state`, 10/118 |
| `zero_e1` | `transport_food`, 1/11173 | `transport_food`, 2/11174 |
| `shallow_yrot` | `flow_state`, 6/118 | `flow_state`, 6/118 |
| `assignment_yrot` | direct assignment isolation, 4/118 | direct assignment isolation, 4/118 |
| `drop_gyreA` | `flow_state`, 2/118 | `flow_state`, 2/118 |
| `drop_gyreOmega` | `flow_state`, 2/118 | `flow_state`, 2/118 |
| `drop_gyreT` | `flow_state`, 2/118 | `flow_state`, 2/118 |
| `waves_off` | `flow_readers`, 31/616 | `flow_readers`, 31/616 |
| `cur_advanced` | `flow_state`, 20/118 | `flow_state`, 20/118 |
| `eye_contrast` | eye-only mutant | `transport_food`, 1821/11174 |
| label `offset_y` | `label_mask`, 8/318 | `label_mask`, 13/434 |
| label `heading_x` | `label_mask`, 12/239 | `label_mask`, 11/481 |
| label `food_x` | `label_mask`, 7/333 | `label_mask`, 9/508 |

Hydro `drop_A04` and `scale_Fc_x` each exited 1 on the entrywise
`Abody: input-matched cubature (per entry)` assertion. The unmodified native
reference passed before and after the mutant suite. Label-mask clean controls
passed 2991 plain / 3186 eye checks.

## Whole-run identity

**29/29 frozen workloads passed; 104,000 updates per revision**, plus
initialization for each workload (104,029 trace records per revision).
`build_splitA/identity.py` adapts Brief 01's runner only for the frozen recipe
input and the existing BASE/HEAD driver paths. Every recipe string is unchanged;
the frozen file's SHA-256 is
`e6534ef361e092698d330940c492373477dd8a33d33ac608c48df15a80f4ab37`.
The runner uses `--trace`, never `--sparse`, and checks exactly steps + 1
fingerprint lines. All complete stdout files are byte-identical, including
fingerprints, RNG, chains and counters. Both exits are 0 for every workload.

Stderr is also identical after the exact `without_timing` function from
`identity_review_round1.py`: only the footer's elapsed seconds and steps/s are
normalized; its step/pop counts and all other diagnostics are retained. The
continuation independently rechecked every saved stdout/stderr pair and verified
that the normalization function's AST matches the review runner. No discrepancy
required `--dump-step` diagnosis.

`build_splitA/identity_build.py` compiled the four existing drivers using
identical `g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src`
flags (plus `-DEVO_OCEAN_EYE` for eye), with the same relative source paths and
each revision as its working directory. Build commands/times, all raw and
normalized outputs, recipes and per-workload JSON results are under
`build_splitA/logs/identity/`.

| Frozen workload | Variant | Updates/revision | Stdout / normalized stderr |
|---|---|---:|---|
| `walls_bigtank_s9` | plain | 1,000 | PASS / PASS |
| `def_s1` | plain | 3,000 | PASS / PASS |
| `eddies_s11` | plain | 3,000 | PASS / PASS |
| `gyre_toro_s13` | plain | 3,000 | PASS / PASS |
| `e1_preset_s42` | plain | 3,000 | PASS / PASS |
| `e1_live_s21` | plain | 3,000 | PASS / PASS |
| `e1_gyre_s13` | plain | 3,000 | PASS / PASS |
| `walls_e1_s42` | plain | 3,000 | PASS / PASS |
| `walls_gyre_s13` | plain | 3,000 | PASS / PASS |
| `walls_live_s21` | plain | 3,000 | PASS / PASS |
| `walls_x_shallow_s4` | plain | 3,000 | PASS / PASS |
| `walls_x_small_s6` | plain | 3,000 | PASS / PASS |
| `eye_def_s1` | eye | 3,000 | PASS / PASS |
| `eye_e1_capture_s17` | eye | 3,000 | PASS / PASS |
| `eye_cloak_food_capture_s17` | eye | 3,000 | PASS / PASS |
| `eye_cloak_live_s21` | eye | 3,000 | PASS / PASS |
| `eye_walls_e1_capture_s17` | eye | 3,000 | PASS / PASS |
| `life_live_s21` | plain | 3,000 | PASS / PASS |
| `bigtank_10k_s9` | plain | 10,000 | PASS / PASS |
| `bigtank_10k_s42` | plain | 10,000 | PASS / PASS |
| `eye_code4_capture_s17` | eye | 3,000 | PASS / PASS |
| `eye_code4_rich_toro_s7` | eye | 3,000 | PASS / PASS |
| `eye_code7_only_capture_s17` | eye | 3,000 | PASS / PASS |
| `eye_code7_steer_only_exp_s3` | eye | 5,000 | PASS / PASS |
| `eye_code7_life_steer_only_s3` | eye | 5,000 | PASS / PASS |
| `eye_code7_big_s42` | eye | 2,000 | PASS / PASS |
| `eye_cloak_food_only_steer_l12_s3` | eye | 5,000 | PASS / PASS |
| `e1_preset_toro_s42` | plain | 3,000 | PASS / PASS |
| `eye_e1_code31_s42` | eye | 3,000 | PASS / PASS |

## Production artifacts and toolchain

Toolchain recorded before extraction: GCC 15.2.0, CMake 3.28.3, Emscripten 6.0.4
(`fe5be6afdff43ad58860d821fcc8572a23f92d19`), Node 26.13.0, npm 11.20.0.

| Artifact | Base SHA-256 | Head SHA-256 |
|---|---|---|
| `web/evo_ocean.wasm` | `01e363ae03334e19a0244211355c380306987886f161f042b6e8ada5b8e33b25` | `e55a4fcb2e7c2e737c6f0cc838c783237ba138336f1162ab4ddf037468b5f2f1` |
| `web/evo_ocean.js` | `8bdce72bd8991c6e88768712b60cec9b7dd0cf22335d82ebe67f40cef6d91059` | `8bdce72bd8991c6e88768712b60cec9b7dd0cf22335d82ebe67f40cef6d91059` |
| `web/evo_boids.wasm` | `d05c4442e15d6850aeece60e52c2a69289d10a2d39fd17538b2347123be0a99b` | `d05c4442e15d6850aeece60e52c2a69289d10a2d39fd17538b2347123be0a99b` |
| `web/evo_boids_mt.wasm` | `1c86e3d2a8c043e17ab1e75004ad37d9d20a70ce5498a80e4ae4bf4fdd8a703b` | `1c86e3d2a8c043e17ab1e75004ad37d9d20a70ce5498a80e4ae4bf4fdd8a703b` |
| `web/evo_boids.js` | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` |
| `web/evo_boids_mt.js` | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` |

`build_splitA/phase6.sh` first sourced `~/opt/emsdk/emsdk_env.sh`, then copied
the permitted read-only fable-perf cache into `build_splitA/production-em-cache`.
Both production builds ran with `EMCC_CORES=1`, a frozen writable cache, and
`LDFLAGS`, `CMAKE_PREFIX_PATH`, `SFML_DIR`, `CPPFLAGS`, `CXXFLAGS` unset.
There was no network use or optimization-flag change. The two builds matched
byte-for-byte (sha256 and cmp); the continuation rechecked the current artifacts
against the first-build copies. Ocean Wasm grew from 349,424 to 349,745 bytes
(321 bytes); JS is unchanged. The rebuilt Wasm remains in place. Turbo passed
against these bytes. All four Classic artifacts remain byte-identical to base;
no pin file was edited.

## Performance

The existing `tools/ocean_eye_block.cpp` and lockstep hosts were used by
`build_splitA/perf.py`, with identical build flags on BASE and HEAD. A scratch
copy adds the same walls/waves/deep-current preset to both revisions; no tracked
tool was changed. Each session runs four snapshots in rotating five-step chunks:
BASE A, BASE A, HEAD A, HEAD A. Every repetition restarts from its snapshot,
warms for ten steps, and excludes a full warm-up round. RNG state belongs to each
snapshot. Seed 42, 300 founders and a 1920×1080 world are used throughout.

Native: nine measured repetitions × 500 steps, after 3,000 evolution steps.
Wasm: five × 200 steps, after 1,000 evolution steps, using the same block method
with `-msimd128` and Node. The short Wasm comparison is required because the
production Wasm bytes changed; it measures the engine blocks, not browser render
or JS API overhead. Builds and sessions ran sequentially at nice 19 on the busy
study host. These are observations, not an acceptance threshold.

Times below are median milliseconds/update for the first BASE/HEAD copies.
Percentages are medians of per-repetition ratios minus one; brackets give the
minimum and maximum paired percentage. Positive HEAD/BASE means slower.

| Runtime / build / workload | BASE ms | HEAD ms | HEAD/BASE % [range] | BASE A/A % [range] | HEAD A/A % [range] |
|---|---:|---:|---|---|---|
| native-plain-default | 1.2367 | 1.2416 | +0.33 [-0.83, +1.64] | +0.15 [-0.66, +1.77] | +0.03 [-0.21, +0.80] |
| native-plain-walls-e1 | 4.8729 | 4.8795 | -0.45 [-1.18, +0.26] | +0.49 [+0.24, +0.93] | +0.03 [-0.83, +0.86] |
| native-eye-default | 1.4047 | 1.4045 | +0.08 [-1.64, +0.90] | -0.15 [-0.84, +1.49] | -0.04 [-1.63, +1.36] |
| native-eye-walls-e1 | 4.7957 | 4.8166 | +0.25 [-0.23, +1.00] | -0.05 [-0.65, +0.51] | +0.42 [-0.11, +0.94] |
| wasm-plain-default | 1.1243 | 1.1227 | -0.13 [-0.61, +0.30] | -0.34 [-0.58, +0.08] | -0.06 [-0.62, +1.36] |
| wasm-plain-walls-e1 | 8.0481 | 8.0350 | -0.27 [-0.69, +0.17] | -0.08 [-0.40, +0.19] | +0.20 [-0.26, +0.83] |
| wasm-eye-default | 1.3274 | 1.3352 | -0.64 [-0.83, +0.59] | -0.43 [-0.79, -0.25] | -0.04 [-0.73, +0.32] |
| wasm-eye-walls-e1 | 8.2169 | 8.2103 | -0.08 [-0.17, +0.14] | -0.07 [-0.36, +0.04] | +0.03 [-0.12, +0.22] |

Native paired medians range from −0.45% to +0.33%, with mixed signs; short
Wasm medians range from −0.64% to −0.08%. These differences are small alongside
the recorded A/A variation. Absolute native and Wasm times use differently
evolved snapshots and are not a comparison of runtime speeds.

Raw per-repetition timings, complete commands, population summaries, build logs,
artifact hashes and JSON ratios are retained in `build_splitA/logs/perf/`.
A/A ranges quantify scheduling/allocation noise on this host; the short runs do
not establish a general speedup or regression across other workloads.

## Line counts

| File | Map projection | Actual |
|---|---:|---:|
| `ocean_world.hpp` | 1,250 | 1,250 |
| `ocean_entities.hpp` | 20 | 20 |
| `ocean_world_util.hpp` | 112 | 112 |
| `ocean_walls.hpp` | 71 | 71 |
| `ocean_eye.hpp` | 94 | 94 |
| `ocean_side_tracks.hpp` | 175 | 175 |
| `ocean_sensing.hpp` | 595 | 595 |
| `ocean_predators.hpp` | 168 | 168 |
| World plus seven extracted headers | 2,485 | 2,485 |
| Existing `ocean_transport.hpp` | 1,008 | 1,008 |
| Existing `ocean_flow.hpp` | 460 | 460 |
| Omitted `ocean_world_flow.hpp` / `ocean_flow_field.hpp` | 0 | 0 |

## Proposed coordinator commit split

1. Source extraction: `src/ocean/ocean_world.hpp`, the seven new headers,
   `tests/label_mask_fault.sh`, and this report. Suggested subject:
   `ocean: extract member definitions into topic headers`.
2. Generated `web/evo_ocean.wasm` (its bytes changed; JS is unchanged).
   Suggested subject:
   `wasm: rebuild Ocean after definition-only extraction`.

The coordinator supplies the required attribution trailer. Local scripts, caches,
logs, binaries and traces under `build_splitA/`, plus `dist/` and `node_modules/`,
are excluded from the commits.

## Coordinator gates (laptop, 2026-11-23)

These ran after review round 1 (Codex rev98: extraction independently verified;
one P2, which was this report claiming gates 1–8 before the browser gate had run).
They used the branch with main 294fc8b merged in (#94, #97; no file overlap) and
the navigation comment added beside the implementation includes (comment only).

| Gate | Command | Result |
|---|---|---|
| Independent module freshness | `bash wasm/build_ocean.sh` (laptop `~/emsdk`, Emscripten 6.0.4 fe5be6af), before and after the comment | `web/evo_ocean.wasm` and `web/evo_ocean.js` byte-identical to the committed server build (`e55a4fcb…`, `8bdce72b…`) both times |
| Map gate 8: render correctness | `node tests/ocean_render_browser.mjs --base http://localhost:8182 --parts correctness,faults,slots,noperf,missing,timer,beam,iframe,gate` (headless Brave, Intel Iris Xe, D3D11; `web/` served by `wasm/serve.py`) | exit 0, **137/137** checks |
| Map gate 8: body GPU | `node tests/ocean_body_gpu.mjs --base http://localhost:8183 --page /web/ocean_bodyplan.html` (repository root served) | exit 0, **20/20**: "BODY GPU CHECK: all passed" |
| Map gate 8: page smoke | `node tools/ocean_render_perf/smoke.mjs --web http://localhost:8182 --root http://localhost:8183` | exit 0, **5/5** |
| Map gate 7, remainder | the PR's CI: native serial/OpenMP/thread-pool, Classic module freshness/parity, engine identity base vs head and vs the pinned engine, Ocean module freshness + FAST parity + Turbo, web checks | see the PR's checks for the merged head |

Each browser job took the machine-wide browser lock itself. Logs are kept
outside the repository (`fish runs/ocean_handoff/splitA/gate8/`). After deploy,
the live checks (both hosts, Turbo, frame rate) run as for every deploy.

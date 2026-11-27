> **Coordinator decision on Gate 7 (2026-11-27).** The component timing gate is accepted as *informational* for this PR. 11 of 12 internal groups and all 12 base groups pass the 3 % A/A screen. The one rejected group, Wasm/eye held flow, has an A/A spread of 6.44 % on a server busy with the study. That spread cannot change the conclusion every group shows: the internal mechanics cost far more than the legacy step (H/T ≈ 15× Wasm/eye, up to ≈ 56× native), so H alone exceeds the 448 ns/fish-step allowance. This PR activates nothing: the six generated modules are byte-identical to main, and the mechanics are reachable only from tests and tools. **PR 3 must therefore optimise the mechanics and pass a complete-world paired Wasm M2/legacy ≤ 1.25 before any activation.** That is now a precondition of PR 3, not a measurement owed by PR 2. The Wasm/eye flow row stays "unestablished".

# M2b1 PR 2 — Round 7: timing rejected; remaining gates audited

**Not release-ready.** On approved main **4bafeb25bca62c4c3a628d97ed70d781f79a6168**, the full timing matrix was measured, but Wasm/eye held-flow A/A deviation **6.44338448032%** exceeds the unchanged **3%** screen. That group is rejected and **Gate7 timing does not pass**. No retiming or threshold change was attempted; this is not an own-tool failure eligible for a rerun. The coordinator accepted Round6 Gates2–6, freeze/fixtures, memory/stack/stress and three native/plain base-comparison groups; they were retained. Round7 retains every raw timing window and runs independent Gates8–12; their results do not waive the Gate7 failure. All changes remain **uncommitted**. Production activation and complete-world performance acceptance remain PR3 obligations.

## Protocol root cause and correction

The untimed probe reproduced the empty response before timing: Python sent and flushed `0\n`, keeping stdin open. Node's first `fs.readSync` returned both request bytes. Emscripten's default TTY adapter tried to fill the C stdio buffer with another read, encountered `EAGAIN` on the nonblocking pipe, translated it to `EIO` (errno29), and discarded the partial read. `scanf` returned−1 with `ferror=1`, **`feof=0`**. The C++ `while(scanf(...)==1)` therefore ended and returned0. Python observed stdout EOF. This was a scratch transport defect, not an actual input EOF or a blocked sandbox syscall.

Request framing (decimal ID/newline) and Python flush were correct. C++ already newline-terminated and flushed its sample. No sample was printed on the failed path, so Node stdout drain was not the original cause. The scratch Wasm controls now use `-sNODERAWFS=1`, which returns a partial host read immediately, plus `blocking.cjs`: stdin blocks between requests, and stdout drains before synchronous input resumes. Parent closes stdin only after the last response, drains trailing stdout and waits for exit0. World/RNG restore and all timing windows are unchanged. No production source changed this round.

The fixed untimed probe passed (`scanf=1`, value0, no error). The real **single-request smoke passed before the matrix**, printing exactly one `LEGACY_SAMPLE,request=0,scenario=still,pop=2000`, initial/final `c33e3218c80bb0ad`/`91ea81370d856d62`, zero births/deaths/reseeds, then exit0, empty stderr and no trailing stdout after input closure. The base-comparison matrix subsequently tested the persistent request loop successfully. The later component A/A instability is separate from the fixed transport protocol. [Root-cause record](../build_m2b1_pr2/round7/protocol_root_cause.md), [original probe](../build_m2b1_pr2/round7/logs/protocol_probe_original.log), [fixed probe](../build_m2b1_pr2/round7/logs/protocol_probe_fixed.log), [single-request smoke](../build_m2b1_pr2/round7/logs/protocol_single_request_smoke.log).

## Full timing matrix

All timing is sequential, affinity **CPU1**, nice19, population2000, initialized immutable snapshots with world and RNG restored per repetition, **100 warm /200 measured /seven recorded /one discarded**, rotating A/B/A. No build overlaps a timed window. Native uses GCC15.2.0; Wasm Emscripten6.0.4; Node26.13.0, V8 pool1; Intel i5-10500T. The accepted Round6 native/plain base groups are retained verbatim; all other groups are fresh. Ratio columns are medians of paired ratios, not ratios of medians. Times are ns/fish-step; A/A columns show absolute percentage deviation.

| Target / scenario | Base T | Current/base paired | Base A/A % | Legacy T | H internal | H/T paired | Internal A/A % | R / L | Net H−R+L | 448−H before R,L | A/A status |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---|
| native_plain / still | 2721.014 | 0.997342 | 0.1389 | 2735.612 | 50932.088 | 18.595729 | 0.3344 | unmeasured / unmeasured | unestablished | -50484.088 | pass |
| native_plain / flow | 2920.300 | 0.994340 | 0.3788 | 2981.041 | 51382.573 | 16.689253 | 0.3989 | unmeasured / unmeasured | unestablished | -50934.573 | pass |
| native_plain / boundary | 2252.403 | 1.006616 | 0.0825 | 2341.344 | 132246.748 | 56.447666 | 0.0910 | unmeasured / unmeasured | unestablished | -131798.748 | pass |
| wasm_plain / still | 3292.814 | 0.995128 | 0.0711 | 3301.416 | 63178.082 | 19.174745 | 0.0496 | unmeasured / unmeasured | unestablished | -62730.082 | pass |
| wasm_plain / flow | 3526.700 | 0.997017 | 0.0555 | 3591.309 | 63972.461 | 17.551844 | 0.4703 | unmeasured / unmeasured | unestablished | -63524.461 | pass |
| wasm_plain / boundary | 2786.817 | 1.004200 | 0.2404 | 2749.121 | 181603.556 | 66.198962 | 0.0390 | unmeasured / unmeasured | unestablished | -181155.556 | pass |
| native_eye / still | 3157.924 | 1.001118 | 0.8610 | 3108.645 | 51103.106 | 16.460116 | 0.1958 | unmeasured / unmeasured | unestablished | -50655.106 | pass |
| native_eye / flow | 3264.260 | 1.005295 | 0.8567 | 3185.980 | 50227.894 | 15.829352 | 0.0484 | unmeasured / unmeasured | unestablished | -49779.894 | pass |
| native_eye / boundary | 2652.517 | 0.999215 | 0.6751 | 2663.615 | 131411.025 | 48.956503 | 0.0341 | unmeasured / unmeasured | unestablished | -130963.025 | pass |
| wasm_eye / still | 3739.786 | 1.007135 | 0.0843 | 3736.935 | 63480.826 | 16.972071 | 0.1414 | unmeasured / unmeasured | unestablished | -63032.826 | pass |
| wasm_eye / flow | 3967.859 | 0.991455 | 0.0845 | 3890.907 | 59892.662 | 15.322931 | 6.4434 | unmeasured / unmeasured | unestablished | -59444.662 | REJECTED |
| wasm_eye / boundary | 3134.180 | 1.000474 | 0.6153 | 3103.284 | 179952.508 | 57.871473 | 0.0048 | unmeasured / unmeasured | unestablished | -179504.508 | pass |

The usage-limit interruption also left `gate07_resume_timing_wasm_plain.log` incomplete during boundary repetition4, without an exit receipt. The coordinator resume preserved that log and reran only this incomplete command, using the exact unchanged binary under `gate07_continued_timing_wasm_plain`; it did not repeat the completed native/plain command or any base comparison. These interruptions are not numerical failures. The pre-existing Round7 internal timing attempt ended during native/plain flow with no exit receipt. Its log is preserved, but none of those partial samples is mixed into this complete restart. All12 completed base-comparison groups remain retained. The restart uses unchanged Round6 binaries and the same CPU1 affinity and windows; conservatively it is charged as the first of this round's two own-test reruns. After the complete native/plain benchmark exited0, the scratch validator split the embedded comma in `outer=[100,300)` and raised ValueError while counting raw windows. Splitting only before `key=` fixes that parser; the completed native/plain measurement is revalidated from its passing receipt, with no timing repetition. Continuation consumes the second/final own-test rerun. The earlier parser-failure wrapper exit1 is retained separately from its native/plain benchmark exit0. The later completed Wasm/eye benchmark and coordinator continuation each exit1 for the genuine A/A failure, with no parser error or transport failure. A resume setup command also failed before any test ran because the round7 directory already existed; the following diagnostic launcher found no diagnostic file and exited2. Those accidental setup receipts are retained and are not timing evidence. [Resume audit](../build_m2b1_pr2/round7/resume_note.md), [interrupted component log](../build_m2b1_pr2/round7/logs/gate07_timing_native_plain.log).

**R** (actually measured removable legacy work) is **unavailable**, not zero. **L** (remaining production lifecycle/ownership/contact increment not already in H) is **unmeasured**, not zero. Contact work exercised by the isolated harness is already in H. Auxiliary construction/transaction/compaction timings cannot be converted into L without production event frequencies. Thus **net=H−R+L** and **remaining allowance=448−H+R−L**, numerically unestablished. The `448−H` column supplies the measured known term of that allowance, not a certified net budget. No profiled movement interval is subtracted. H alone greatly exceeds448ns; the component results expose a substantial PR3 performance obligation and do not establish complete-world Wasm M2/legacy≤1.25. No acceptance threshold, law, constant or source was changed to improve these numbers.

All12 base groups and **11/12 internal scenario groups** meet the3% A/A screen. **Wasm/eye held flow fails**: seven paired A/A ratios are .932466999,1.282071079,1.551962297,1.011134331,1.064433845,1.083063493,.999641674; their median is1.0644338448. This shows inconsistent A/A timing; its cause is not established. No new diagnostic timing or retry was run. All three Wasm/eye scenario rows are retained from the same exit1 command; still-water and boundary rows individually pass the screen, but do not turn the complete command into a pass. Rejected-row H, ratios and allowance terms are raw observations, not accepted estimates. Legacy lifecycle windows retain2000 fish, zero births/deaths/reseeds. Base/current initial/final fingerprints match, including native/Wasm cross-checks. [Base samples/statistics](../build_m2b1_pr2/round7/gate07_baseAA.json), [component summaries](../build_m2b1_pr2/round7/gate07_components.json), [complete-window/lifecycle audit](../build_m2b1_pr2/round7/timing_complete_audit.json), [raw logs](../build_m2b1_pr2/round7/logs/), [hardware/flags/windows](../build_m2b1_pr2/round7/timing_environment.json), [retained affinity choice](../build_m2b1_pr2/round6/timing_affinity.json). Round6's accepted memory/stack/stress evidence remains unchanged: charged native plain/eye1266.864/1266.544 B/fish, Wasm plain/eye1260.024, all below1404. No separate memory rerun was needed.

## Gate table and reuse audit

The reuse rule was audited against exact inputs, not gate names. Comparing Round6's start inventory to this round's inventory changes only `docs/m2b1_pr2.md` and `tools/ocean_hydro_bench.hpp`; both are the accepted Round6 edits. Round7 changes only this report among repository sources. The native/plain base runner and all its production/header dependencies are unchanged; the three accepted receipts stand. Gates8–12 had **no passing receipt from this tree state**, so all run fresh. [Input paths, changed set, decisions and retained binary hashes](../build_m2b1_pr2/round7/reuse_audit.json), [timing input hashes](../build_m2b1_pr2/round7/timing_inputs.json), [start inventory](../build_m2b1_pr2/round7/before.json).

| Gate | Result / evidence |
|---|---|
| 2–6 | Coordinator-accepted Round6 passes; no reproduction requested |
| 7 memory/stack/stress | Coordinator-accepted four Round6 passes |
| 7 native/plain base groups | Retained three accepted Round6 paired A/A passes |
| 7 remaining base comparisons | Fresh pass; all12 base/current groups pass |
| 7 full H/internal matrix | **FAIL: Wasm/eye held-flow A/A6.4434% >3%; no retiming** |
| 8 Ocean build/freshness | Fresh pass, unchanged JS/Wasm |
| 9 Classic build/freshness | Fresh pass, all four files byte-identical |
| 10 native repository configure/build/ctest | Pass,4/4 registered tests; SFML-dependent tests unavailable |
| 11 module consumers | Pass, all five executed commands exit0 |
| 11 TypeScript | Pass, local pinned5.6.3 check exits0 |
| 12 final audit | Scope/identity audit passes; Gate7 failure retained, no release-readiness; all36 files assigned once |

`R` below is `build_m2b1_pr2/round7`. Every invocation is nice19, with builds≤2 jobs and≤2 threads/job, EMCC/Binaryen1, ctest sequential, and `RQ_TEST_WORKERS=2`. No network, .git write, rebaseline, merge or deployment. An overbroad initial AGENTS discovery listed sibling-tree pathnames; no sibling file contents were opened or changed. Subsequent inspection stayed in this tree and the named instruction files. Full command/environment/wall/exit records, including the persistent timing servers, are in [commands.jsonl](../build_m2b1_pr2/round7/commands.jsonl); nested timing-server durations overlap and must not be summed.

| Command | Exit | Wall s | Log |
|---|---:|---:|---|
| `nice -n 19 em++ -O3 -sENVIRONMENT=node -sEXIT_RUNTIME=1 build_m2b1_pr2/round7/stdio_probe.cpp -o build_m2b1_pr2/round7/stdio_probe.js` | 0 | 113.310 | [protocol_probe_build](../build_m2b1_pr2/round7/logs/protocol_probe_build.log) |
| `nice -n 19 python3 build_m2b1_pr2/round7/probe_protocol.py` | 0 | 0.132 | [protocol_probe_original](../build_m2b1_pr2/round7/logs/protocol_probe_original.log) |
| `nice -n 19 em++ -O3 -sENVIRONMENT=node -sEXIT_RUNTIME=1 -sNODERAWFS=1 build_m2b1_pr2/round7/stdio_probe.cpp -o build_m2b1_pr2/round7/stdio_probe_raw.js` | 0 | 3.715 | [protocol_probe_raw_build](../build_m2b1_pr2/round7/logs/protocol_probe_raw_build.log) |
| `nice -n 19 python3 build_m2b1_pr2/round7/probe_protocol.py` | 0 | 0.218 | [protocol_probe_fixed](../build_m2b1_pr2/round7/logs/protocol_probe_fixed.log) |
| `nice -n 19 python3 build_m2b1_pr2/round7/build_servers.py` | 0 | 97.572 | [protocol_servers_build](../build_m2b1_pr2/round7/logs/protocol_servers_build.log) |
| `nice -n 19 python3 build_m2b1_pr2/round7/smoke.py` | 0 | 2.521 | [protocol_single_request_smoke](../build_m2b1_pr2/round7/logs/protocol_single_request_smoke.log) |
| `nice -n 19 python3 build_m2b1_pr2/round7/protocol_diagnose.py` | 2 | 0.036 | [protocol_diagnose](../build_m2b1_pr2/round7/logs/protocol_diagnose.log) |
| `nice -n 19 /home/harit/finfolk/work/trees/m2b1-pr2/build_m2b1_pr2/round6/bench_plain --mechanics-components` | 0 | 2299.737 | [gate07_resume_timing_native_plain](../build_m2b1_pr2/round7/logs/gate07_resume_timing_native_plain.log) |
| `nice -n 19 python3 build_m2b1_pr2/round7/resume_components.py` | 1 | 2299.991 | [gate07_resume_protocol](../build_m2b1_pr2/round7/logs/gate07_resume_protocol.log) |
| `nice -n 19 node --single-threaded --v8-pool-size=1 /home/harit/finfolk/work/trees/m2b1-pr2/build_m2b1_pr2/round6/bench_plain.js --mechanics-components` | 0 | 3021.153 | [gate07_continued_timing_wasm_plain](../build_m2b1_pr2/round7/logs/gate07_continued_timing_wasm_plain.log) |
| `nice -n 19 /home/harit/finfolk/work/trees/m2b1-pr2/build_m2b1_pr2/round6/bench_eye --mechanics-components` | 0 | 2209.087 | [gate07_resume_timing_native_eye](../build_m2b1_pr2/round7/logs/gate07_resume_timing_native_eye.log) |
| `nice -n 19 node --single-threaded --v8-pool-size=1 /home/harit/finfolk/work/trees/m2b1-pr2/build_m2b1_pr2/round6/bench_eye.js --mechanics-components` | 1 | 2972.152 | [gate07_resume_timing_wasm_eye](../build_m2b1_pr2/round7/logs/gate07_resume_timing_wasm_eye.log) |
| `nice -n 19 python3 build_m2b1_pr2/round7/continue_components.py` | 1 | 8202.740 | [gate07_coordinator_continuation](../build_m2b1_pr2/round7/logs/gate07_coordinator_continuation.log) |
| `nice -n 19 bash wasm/build_ocean.sh` | 0 | 21.885 | [gate08_ocean_rebuild](../build_m2b1_pr2/round7/logs/gate08_ocean_rebuild.log) |
| `nice -n 19 git diff --exit-code -- web/evo_ocean.js web/evo_ocean.wasm` | 0 | 0.010 | [gate08_ocean_freshness](../build_m2b1_pr2/round7/logs/gate08_ocean_freshness.log) |
| `nice -n 19 bash wasm/build_wasm.sh` | 0 | 265.672 | [gate09_classic_rebuild](../build_m2b1_pr2/round7/logs/gate09_classic_rebuild.log) |
| `nice -n 19 git diff --exit-code -- web/evo_boids.js web/evo_boids.wasm web/evo_boids_mt.js web/evo_boids_mt.wasm` | 0 | 0.013 | [gate09_classic_freshness](../build_m2b1_pr2/round7/logs/gate09_classic_freshness.log) |
| `nice -n 19 cmake --preset native-serial` | 0 | 0.348 | [gate10_native_configure](../build_m2b1_pr2/round7/logs/gate10_native_configure.log) |
| `nice -n 19 cmake --build --preset native-serial --parallel 2` | 0 | 69.435 | [gate10_native_build](../build_m2b1_pr2/round7/logs/gate10_native_build.log) |
| `nice -n 19 ctest --test-dir build_serial --output-on-failure` | 0 | 96.866 | [gate10_native_ctest](../build_m2b1_pr2/round7/logs/gate10_native_ctest.log) |
| `nice -n 19 node tests/ocean_turbo_handoff.js` | 0 | 324.859 | [gate11_ocean_turbo_handoff](../build_m2b1_pr2/round7/logs/gate11_ocean_turbo_handoff.log) |
| `nice -n 19 node tests/ocean_shader_slots_tests.cjs` | 0 | 0.185 | [gate11_ocean_shader_slots_tests](../build_m2b1_pr2/round7/logs/gate11_ocean_shader_slots_tests.log) |
| `nice -n 19 node tests/ocean_materials_tests.cjs` | 0 | 0.415 | [gate11_ocean_materials_tests](../build_m2b1_pr2/round7/logs/gate11_ocean_materials_tests.log) |
| `nice -n 19 node tests/ocean_render_opt_tests.cjs` | 0 | 0.097 | [gate11_ocean_render_opt_tests](../build_m2b1_pr2/round7/logs/gate11_ocean_render_opt_tests.log) |
| `nice -n 19 node tests/ocean_mock_three_tests.mjs` | 0 | 30.715 | [gate11_ocean_mock_three_tests](../build_m2b1_pr2/round7/logs/gate11_ocean_mock_three_tests.log) |
| `nice -n 19 node /home/harit/finfolk/work/trees/m2b1-pr2/build_m2b1_pr2/round5/typescript/package/lib/tsc.js -p tsconfig.json` | 0 | 3.424 | [gate11_typescript](../build_m2b1_pr2/round7/logs/gate11_typescript.log) |
| `nice -n 19 python3 build_m2b1_pr2/round7/gates08_11.py` | 0 | 814.668 | [gates08_11_protocol](../build_m2b1_pr2/round7/logs/gates08_11_protocol.log) |
| `nice -n 19 python3 build_m2b1_pr2/round7/gate12_audit.py` | 0 | 0.317 | [gate12_final_audit](../build_m2b1_pr2/round7/logs/gate12_final_audit.log) |

Native-serial configure/build/ctest all exit0. CTest passed **4/4**: `core_tests`, `weight_policy_frontend`, `checkpoint_v3_validation`, `predator_smoke`. CMake reports **SFML2.6 not found**; the app and its dependent `reseed_after_load`, `stagec_cli`, `weight_policy_cli`, `invasion_tooling`, `redqueen_tooling`, `redqueen_worlds`, `redqueen_forks` tests were **unavailable**, not passed or ENVIRONMENT-BLOCKED. No existing test failed because of a blocked syscall, and no workaround was applied. All five executed module-consumer commands and the existing local pinned TypeScript5.6.3 check exit0. No dependency fetch or browser run was performed. PR3 live rendering/checkpoint/export checks remain outstanding.

## Module hashes, freeze and final audit

Fresh Ocean and Classic rebuilds match the committed artifacts and the Round7 start inventory byte for byte. Classic pins are unchanged. No module artifact commit is needed.

| Module | SHA256 |
|---|---|
| `web/evo_boids.js` | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` |
| `web/evo_boids.wasm` | `d05c4442e15d6850aeece60e52c2a69289d10a2d39fd17538b2347123be0a99b` |
| `web/evo_boids_mt.js` | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` |
| `web/evo_boids_mt.wasm` | `1c86e3d2a8c043e17ab1e75004ad37d9d20a70ce5498a80e4ae4bf4fdd8a703b` |
| `web/evo_ocean.js` | `8bdce72bd8991c6e88768712b60cec9b7dd0cf22335d82ebe67f40cef6d91059` |
| `web/evo_ocean.wasm` | `e55a4fcb2e7c2e737c6f0cc838c783237ba138336f1162ab4ddf037468b5f2f1` |

Frozen stage4 header SHA256 remains `05400c4e22c62965c2c95e952db028e0fd23c5234f22a0e55a443fd1e21897c7`; constant/reference digest `d532fc22992356ab`/`34f5953354409576`, frozen powers `0x472e2e4d`/`0x47a8c544`, conversion `0x3761c066`. Coordinator-accepted Round6 assays and all150 predicates remain the authority. Fixtures retain these exact generated identities:

| Fixture | SHA256 |
|---|---|
| `tests/fixtures/ocean_hydro_fixture.json` | `464d48b63a2b7c417b453fa9ffb727b70a485d588358f6673f1a8ed37aae19d7` |
| `tests/fixtures/ocean_hydro_step_fixture.json` | `5df21311a807ffecafbedbe6f8be34af30faef28d3ef9e2dbe627f101f42b1ce` |
| `tests/fixtures/ocean_hydro_calibration.json` | `ba4e9b9a788b1d20275986c5eb0c258ce78c429cf928f172e65797511db6faae` |

The final audit confirms HEAD/branch, no Round7 source drift, historical baselines and `src/core`, production world/config/checkpoint/fingerprint/rendering paths and module APIs unchanged against4bafeb2, installed header identical to accepted stage4, fixture hashes unchanged, clean whitespace, and exact coverage of all changed paths. [Final audit](../build_m2b1_pr2/round7/final_audit.json). Earlier rounds' report bytes and raw evidence are retained. Protected backups and stash were not accessed.

Known limitations remain exactly as disclosed in Round6: the four-sweep contact solver can choose dynamic friction despite feasible aggregate static balance; radius-near31 is non-gating, turns have reduced speed/large slip and six disclosed local partial-yaw reversals; free-cruise motor .592894793954 E/s is accepted under corrected D-M2b1-7 with independent accounting, body pitch+1.38075° and steady depth86.1398 versus target120 remain limitations. No upright-attitude or target-depth tracking certification is added. D3 stays unadopted. PR3 still owns public activation, lifecycle/ownership and ordinary births/deaths/reseeds/compaction, checkpoint/export/rendering/live checks, and complete-world paired Wasm≤1.25 performance; component cost now gives a concrete optimization concern. Gate7 also remains an immediate PR2 timing-acceptance obligation: the rejected Wasm/eye held-flow group requires a coordinator decision before any further measurement; no additional retry authorization is inferred.

## Final coordinator commit split

Every changed/new repository file appears once below. Build directories, raw scratch evidence and `/tmp` stay uncommitted. The generated calibration header is in the first commit because the kernels include it; the second commit supplies its generator/assay evidence. No third artifact commit is proposed because rebuilt modules are unchanged. No commits were created.

**`Add internal Ocean mechanics and fuel accounting`**

- `src/ocean/hydro_calibration.hpp`
- `src/ocean/hydro_coefficients.hpp`
- `src/ocean/hydro_contact.hpp`
- `src/ocean/hydro_step.hpp`
- `src/ocean/ocean_energy.hpp`
- `tests/ocean_hydro_step_tests.hpp`
- `tests/ocean_hydro_tests.hpp`
- `tests/ocean_tests.cpp`

**`Freeze Ocean mechanics assays and deterministic fixtures`**

- `docs/_ref/check_m2b2_gate2_diag_codex.md`
- `docs/_ref/m2b1_brief_codex.md`
- `docs/_ref/m2b1_pr2_plan_codex.md`
- `docs/_ref/m2b2_gate4_diag_check_codex.md`
- `docs/m2b1_pr2.md`
- `docs/m2b2_gate2_diag.md`
- `docs/m2b2_gate4_diag.md`
- `docs/m2b3_assay3_diag.md`
- `docs/m2b3_assay3_diag2.md`
- `tests/fixtures/ocean_hydro_calibration.json`
- `tests/fixtures/ocean_hydro_fixture.json`
- `tests/fixtures/ocean_hydro_step_fixture.json`
- `tests/ocean_hydro_accounting.sh`
- `tests/ocean_hydro_measurements.cpp`
- `tests/ocean_hydro_measurements.sh`
- `tools/ocean_eye_bench.cpp`
- `tools/ocean_hydro_assay.cpp`
- `tools/ocean_hydro_bench.hpp`
- `tools/ocean_hydro_calibration_io.hpp`
- `tools/ocean_hydro_calorimetry.hpp`
- `tools/ocean_hydro_fixture.cpp`
- `tools/ocean_hydro_harness.hpp`
- `tools/ocean_hydro_measurements.hpp`
- `tools/ocean_hydro_memory.hpp`
- `tools/ocean_hydro_reference.cpp`
- `tools/ocean_hydro_step_fixture.hpp`
- `tools/ocean_hydro_trajectory_reference.hpp`
- `wasm/ocean_parity.sh`

---

# M2b1 PR 2 — Round 6: stopped at Gate 7

**Not release-ready.** On approved main **4bafeb25bca62c4c3a628d97ed70d781f79a6168** (`m2b1-pr2`), integration checks and Gates2–6 pass; every frozen bit and generated fixture reproduces Round5. The original Gate7 population failure is diagnosed and fixed as **(a), benchmark-harness defect**. All four memory/stack/stress runs pass. Timing remains incomplete: the final permitted own-test rerun failed in my new scratch Wasm request protocol. **Gates8–12 remain unrun.** No environment exception applies and no release-readiness claim is made.

The two Gate7 protocol reruns are consumed. No further benchmark edit, diagnostic run or measurement was attempted after the final failure. All sources remain uncommitted; the coordinator owns commits. Backups and `stash@{0}` were not accessed. Raw evidence is under [round6](../build_m2b1_pr2/round6/); earlier reports and evidence remain intact. [Final stop record](../build_m2b1_pr2/round6/gate07_stop.md).

## Integration audit

No production integration breakage was found and no simulation integration change was needed. All modified/new C++ sources and headers compile through focused optimized/UBSan tests, native reference, native/Wasm plain/eye full suites, assay/fixture drivers and all four component-benchmark builds. The coordinator's merged usage list is retained. Round6 changes only `tools/ocean_hydro_bench.hpp` among source files, plus this report: benchmark-only failure/setup/lifecycle logs and `interactRadius:0` for its fixed-population legacy control. A warning in the new log's initial successful compile was corrected to print the64-bit frame with `%llu` before any diagnostic execution; both build logs are retained. This is a logging development correction, not a production interface change.

The protected-path comparison is `integration_initial.log`. No production integration edits are needed. The sole merged registration conflict retains both dispatch lists. Build/run evidence is appended to commands.jsonl; compile success alone is distinguished from release gates.

| Scope | File:line and finding |
|---|---|
| Moved entities/topic definitions | src/ocean/ocean_world.hpp:287 includes ocean_entities.hpp; :1255–1260 includes the util/walls/eye/side-track/sensing/predator topics. The benchmark includes the unchanged tools/ocean_fingerprint.hpp, which owns the full OceanWorld include. No copied forward declaration or old topic definition exists in the hydro code. |
| FlowState extraction | src/ocean/ocean_world.hpp:542, :547, :663, :882: public flow access and clock update delegate to the owned oceantransport::FlowState. src/ocean/hydro_step.hpp:25 and :42 receive the same held water vector explicitly; the assay intentionally uses no OceanWorld/private flow access. tools/ocean_hydro_bench.hpp uses only legacy.update/config/counters, never flowState_. |
| Four-lane food transport | src/ocean/ocean_world.hpp:921 delegates transport to oceantransport; src/ocean/ocean_transport.hpp:941 and :961 own transportFood and its wallAdvect4 call. No hydro internal interface bypasses it. |
| Activation batch/type masks | src/ocean/ocean_world.hpp:1015–1023 uses the refactored sensor mask/feedForward; src/ocean/ocean_sensing.hpp:463 uses genomeSimilarityMasked; src/core/genome.hpp:327 and :430 contain activation and type-mask implementations. No hydro code accesses the net layout; tools/ocean_hydro_harness.hpp:42 uses Fish::id, foodReserves, bodyBuoy, size and elongation; :68 uses genome.size(). The benchmark legacy variant exercises the exact main path. |
| Internal core | src/ocean/hydro_coefficients.hpp:95 adds only the generated calibration dependency; :104/:108 publish the internal reference/mechanics laws. src/ocean/hydro_contact.hpp:4 includes ocean_energy.hpp; src/ocean/ocean_energy.hpp:102 owns atomic sole-ledger reserve transactions; src/ocean/hydro_step.hpp:4–6 uses unchanged contact/actions/random interfaces and its own config/held inputs. src/ocean/hydro_calibration.hpp:8 remains frozen through 4. |
| Focused tests | tests/ocean_tests.cpp:4962 includes hydro_step tests; :5014 dispatches --only hydro_step; :5020 preserves main's transport/wall_transport_food/type_masks list; :5149 runs the suite in the full tests. tests/ocean_hydro_tests.hpp version checks use current laws, and tests/ocean_hydro_step_tests.hpp:461 registers all step tests. |
| Fixtures/reference | tools/ocean_hydro_fixture.cpp:131 requires frozen4; tools/ocean_hydro_reference.cpp:47 includes the native trajectory reference and :832 gates its result; tools/ocean_hydro_trajectory_reference.hpp:342 gates the independent checks. No world-private structure is consumed. |
| Tools/measurements | tools/ocean_hydro_assay.cpp:11–15 includes step fixture/harness/calibration I/O/measurements/calorimetry; tools/ocean_hydro_calibration_io.hpp:31 emits only after authority checks; tools/ocean_hydro_calorimetry.hpp:30 independently reconstructs work; tools/ocean_hydro_step_fixture.hpp:23 reconstructs actual binary32 unpaid rounding. tools/ocean_hydro_measurements.hpp uses HydroState explicitly. |
| Fault/unit scripts | tests/ocean_hydro_accounting.sh:12 locates the exact production limitMotor call in a scratch header; :43 runs real cumulative measurement/emission and :63 --check-all. tests/ocean_hydro_measurements.cpp and tests/ocean_hydro_measurements.sh remain the standalone measurement unit gate. |
| Bench/memory | tools/ocean_eye_bench.cpp:106 dispatches the new mode before unchanged old option handling; tools/ocean_hydro_bench.hpp:7–8 includes harness and canonical fingerprint/init path; tools/ocean_hydro_memory.hpp:14 uses SDK/native allocator APIs; :39 probes touched stack. Logging added in Round6 is confined to the benchmark header. |
| Parity registration | wasm/ocean_parity.sh:241–242 registers assay builds with existing bounded bgbuild; :1148–1166 compares step and calibration native==wasm==installed fixtures; unchanged full suites include hydro_step. tests/fixtures/ocean_hydro_fixture.json:1, ocean_hydro_step_fixture.json:1 and ocean_hydro_calibration.json:1 are generated evidence, rerun before any installation. |
| Documentation | docs/_ref contains the retained approved plan, brief and diagnoses; docs/m2b1_pr2.md and the four diagnostic reports are evidence only. No code path consumes these files. |

The hydro internal state uses ground velocity, material angular momentum, gas/fatigue and the sole foodReserves ledger, exactly as before main's engine refactors. There is no claim of production M2 activation; that remains PR3.

## Complete changed-file coverage

| File:line | Validation route |
|---|---|
| `src/ocean/hydro_coefficients.hpp:1` | Optimized and UBSan focused suites (gate2), final native/Wasm plain/eye suites (gate6); assay/reference builds as applicable. |
| `src/ocean/hydro_contact.hpp:1` | Optimized and UBSan focused suites (gate2), final native/Wasm plain/eye suites (gate6); assay/reference builds as applicable. |
| `src/ocean/hydro_step.hpp:1` | Optimized and UBSan focused suites (gate2), final native/Wasm plain/eye suites (gate6); assay/reference builds as applicable. |
| `src/ocean/ocean_energy.hpp:1` | Optimized and UBSan focused suites (gate2), final native/Wasm plain/eye suites (gate6); assay/reference builds as applicable. |
| `tests/ocean_hydro_step_tests.hpp:1` | Optimized and UBSan focused suites (gate2), final native/Wasm plain/eye suites (gate6); assay/reference builds as applicable. |
| `tests/ocean_hydro_tests.hpp:1` | Optimized and UBSan focused suites (gate2), final native/Wasm plain/eye suites (gate6); assay/reference builds as applicable. |
| `tests/ocean_tests.cpp:1` | Optimized and UBSan focused suites (gate2), final native/Wasm plain/eye suites (gate6); assay/reference builds as applicable. |
| `docs/_ref/check_m2b2_gate2_diag_codex.md:1` | Evidence/accepted instructions only; no runtime dependency. |
| `docs/_ref/m2b1_brief_codex.md:1` | Evidence/accepted instructions only; no runtime dependency. |
| `docs/_ref/m2b1_pr2_plan_codex.md:1` | Evidence/accepted instructions only; no runtime dependency. |
| `docs/_ref/m2b2_gate4_diag_check_codex.md:1` | Evidence/accepted instructions only; no runtime dependency. |
| `docs/m2b1_pr2.md:1` | Evidence/accepted instructions only; no runtime dependency. |
| `docs/m2b2_gate2_diag.md:1` | Evidence/accepted instructions only; no runtime dependency. |
| `docs/m2b2_gate4_diag.md:1` | Evidence/accepted instructions only; no runtime dependency. |
| `docs/m2b3_assay3_diag.md:1` | Evidence/accepted instructions only; no runtime dependency. |
| `docs/m2b3_assay3_diag2.md:1` | Evidence/accepted instructions only; no runtime dependency. |
| `src/ocean/hydro_calibration.hpp:1` | Optimized and UBSan focused suites (gate2), final native/Wasm plain/eye suites (gate6); assay/reference builds as applicable. |
| `tests/fixtures/ocean_hydro_calibration.json:1` | Documentation/fixture data; no compiled definition. Generated JSON is compared native/Wasm/repeat in gate5 and registered in gate6. |
| `tests/fixtures/ocean_hydro_fixture.json:1` | Documentation/fixture data; no compiled definition. Generated JSON is compared native/Wasm/repeat in gate5 and registered in gate6. |
| `tests/fixtures/ocean_hydro_step_fixture.json:1` | Documentation/fixture data; no compiled definition. Generated JSON is compared native/Wasm/repeat in gate5 and registered in gate6. |
| `tests/ocean_hydro_accounting.sh:1` | Five fresh end-to-end fault builds, emission refusals and final check-all negatives (gate4). |
| `tests/ocean_hydro_measurements.cpp:1` | Standalone measurement-unit build/run (gate3). |
| `tests/ocean_hydro_measurements.sh:1` | Standalone measurement-unit build/run (gate3). |
| `tools/ocean_eye_bench.cpp:1` | Native/Wasm plain/eye benchmark builds and gate7 runs. |
| `tools/ocean_hydro_assay.cpp:1` | Native/Wasm fixture/assay builds and cumulative assays (gates4–6). |
| `tools/ocean_hydro_bench.hpp:1` | Native/Wasm plain/eye benchmark builds and gate7 runs. |
| `tools/ocean_hydro_calibration_io.hpp:1` | Native/Wasm fixture/assay builds and cumulative assays (gates4–6). |
| `tools/ocean_hydro_calorimetry.hpp:1` | Native/Wasm fixture/assay builds and cumulative assays (gates4–6). |
| `tools/ocean_hydro_fixture.cpp:1` | Native/Wasm fixture/assay builds and cumulative assays (gates4–6). |
| `tools/ocean_hydro_harness.hpp:1` | Native/Wasm fixture/assay builds and cumulative assays (gates4–6). |
| `tools/ocean_hydro_measurements.hpp:1` | Native/Wasm fixture/assay builds and cumulative assays (gates4–6). |
| `tools/ocean_hydro_memory.hpp:1` | Native/Wasm plain/eye benchmark builds and gate7 runs. |
| `tools/ocean_hydro_reference.cpp:1` | Native independent reference build/run (gate3 and gate6). |
| `tools/ocean_hydro_step_fixture.hpp:1` | Native/Wasm fixture/assay builds and cumulative assays (gates4–6). |
| `tools/ocean_hydro_trajectory_reference.hpp:1` | Native independent reference build/run (gate3 and gate6). |
| `wasm/ocean_parity.sh:1` | Full gate6 execution; bounded assay builds and fixture comparisons retained. |

## Reproduced freeze, assays and corrected D-M2b1-7

The corrected D-M2b1-7 text quoted in the retained Round5 report and `docs/_ref` remains governing, unchanged. Rebuilt Gates2–3 pass, including separate optimized and UBSan hydro/hydro_step suites, standalone measurement tests and the independent reference. Starting from the previously emitted stage3 header, `--assay 4` reruns assays1→2→3→4 cumulatively before emission. Re-emitted stage4 is **byte-identical** to `round5/stage4.hpp` and the installed header. Every frozen stage1/2/3 constant and measured power is identical; the bit-identity stop was not triggered.

Rebuilt native positive `--check-all` passes150/150 predicates (33+32+62+23). All150 raw result records, constant bits and power bits equal Round5's final check-all. Wasm positive passes150/150 and matches the prescribed deterministic serialization. Fresh ±1% conversion, `.591`, `.609` and in-band `.0005 E/s` undercharge faults all exercise the actual measurement/debit path, exit1, refuse emission, and also exit1 under genuine `--check-all`. The in-band fault passes the motor performance band but fails independent motor/fatigue accounting and exact rounded-ledger subtraction. No accounting tolerance was borrowed from the motor band.

| Identity | Reproduced value |
|---|---|
| Stage4 header SHA256 | `05400c4e22c62965c2c95e952db028e0fd23c5234f22a0e55a443fd1e21897c7` |
| Constant digest / reference digest | `d532fc22992356ab` / `34f5953354409576` |
| Neutral coefficient / support digest | `3e8bfae4938384af` / `44931eb40f7ec2ef` |
| Frozen motor power82 | 44590.30078125, `0x472e2e4d` |
| Frozen motor power108 | 86410.53125, `0x47a8c544` |
| Work conversion | 1.34558413265e-5, `0x3761c066` |
| Laws geometry/material/expression/reference/mechanics/energy | 1/1/1/2/1/1 |
| Coefficient/support/state ABI | 1/1/1 |

All other constant values/bits in Round5's table below remain valid. D3 remains unadopted. [Freeze identity](../build_m2b1_pr2/round6/precision_freeze_identity.json), [native final results](../build_m2b1_pr2/round6/precision_final_check_all.json), [Wasm final results](../build_m2b1_pr2/round6/precision_final_wasm_check_all.json), [actual fault evidence](../build_m2b1_pr2/round6/precision_faults/).

Fresh restrained motor is exactly `.60 E/s` (zero error against the8*epsilon*.60 screen). Free motor remains **.592894793954 E/s**, deviation **−.00710520604625 E/s (−1.18420100771%)**; lower-bound margin **.000894793953747 E/s**, or **.149132325624 percentage points**. Total/debit remain **1.49297714233 E/s /179.157257080 E**. Each actual ledger subtraction matches binary32 reconstruction exactly; the disclosed accumulated subtraction-rounding difference is+.00987754901871 E, not an accepted accounting error.

The accepted limitations also reproduce: actual horizontal speed82.0059509278, signed pitch+1.38074980601°, depth86.1397781372 versus target120, mean/max upward velocity+.00034661841346, integrated displacement+.0415942115908 over120s, stored depth drift0. Regulator remains active every measurement substep at−.0000371932983398/s; integrated requested gas change−.00446319601277 while stored gas remains24.9419345856. Paid cruise pump work.0000193609988875 E (preparation.0767674281856 E) is counted once. The same600s preparation and unchanged120s window were used. Fin-centroid thrust/trim, loaded geometry and regulator/representability mechanisms remain diagnosed limitations, not an exhaustive explanation of the motor deficit. Acceptance certifies neither upright body attitude nor target-depth tracking. The four-sweep contact limitation, reduced-speed/large-slip turn limitations and six disclosed local partial-yaw reversals remain as in the preserved report.

## Fixtures and full Ocean parity

Gate5 retained Round5's two own-test corrections: exact binary32 ledger/unpaid reconstruction, and binary32 encoding of only deterministic fixture `result.value` while preserving binary64 raw measurements/predicates. No new Gate5 correction or rerun was needed. All three native==Wasm==native-repeat emissions matched **before installation**, then installed hashes were rechecked. The step fixture retains140 cases/52,448 substeps,150 assay predicates and43 windows. All fixture bytes equal Round5.

| Fixture | SHA256 |
|---|---|
| `tests/fixtures/ocean_hydro_fixture.json` | `464d48b63a2b7c417b453fa9ffb727b70a485d588358f6673f1a8ed37aae19d7` |
| `tests/fixtures/ocean_hydro_step_fixture.json` | `5df21311a807ffecafbedbe6f8be34af30faef28d3ef9e2dbe627f101f42b1ce` |
| `tests/fixtures/ocean_hydro_calibration.json` | `ba4e9b9a788b1d20275986c5eb0c258ce78c429cf928f172e65797511db6faae` |

Gate6 exact requested full command passed exit0 in **2583.829580s**: `nice -n 19 env -u FAST -u ONLY -u NO_TESTS -u NO_EYE APP_TWINS=all JOBS=2 BUILD_JOBS=2 KEEP_OUT=1 OCEAN_PARITY_DIR=R/full_ocean_parity bash wasm/ocean_parity.sh`. All124 ordinary cases match native==Wasm==historical baseline with per-step chains;124/124 appearance-off twins and22/22 default body-preview twins pass; all config/live guards, fixtures and reference pass. Full plain119/0 and eye126/0 suites have byte-identical native/Wasm printed output. `BODY_TWINS=all` was not selected by this requested command; no full-body-twin expansion is claimed. No rebaseline or exception was used. [Full raw log](../build_m2b1_pr2/round6/logs/gate06_full_ocean_parity.log).

## Gate7 diagnosis, corrections and final stop

The logging-only reproduction exited2 after the first discarded internal sample. Its original config/path was preserved for diagnosis:

```text
POPULATION_FAILURE,scenario=still,rep=-1,variant=1/legacy,completed_outer_steps=126,phase=measured,population=1994,expected=2000,frame=126,births=0,deaths=6,starvation=6,age=0,predation=0,grace_births=0,soft_births=0,reseeds=0,last_step_births=0,last_step_deaths=6,food=0,predators=0
POPULATION_CONFIG,metabolicRate=0,moveCost=0,geneCost=0,maxAge=120,reproEnergy=1000000,minPopulation=0,maxPopulation=2000,interactRadius=36,interactCooldown=2,cHold=0,cPress=0,toroidal=1
```

**Classification(a): benchmark-harness defect.** `src/core/agent_core.hpp:43` supplies30 E for legacy founders, preserved by `src/ocean/fish.hpp:72`; `src/core/kernel.hpp:203` describes the15 E fight transfer and `:116` tests reserves≤0 for starvation. `src/ocean/ocean_world.hpp:1220` selects the unchanged Fight path, and `:745` records its resulting starvation in the serial pass. Two losses reach0; the observed step126 is2.016s, consistent with the2s cooldown. Recurring costs, births, age deaths, predation and reseeding are absent. Share cannot create a negative reserve from nonnegative inputs. The internal hydro clones use25 E, a separate input; my initial commentary confused these, and the source-checked30 E correction is retained in the ledger.

The benchmark had excluded metabolic depletion but left social fights enabled. This is not an invariant invalidated by M2b1 mechanics: the legacy world does not activate those kernels. Round5's malloc declaration fixes concern only allocation measurement and do not alter the legacy init/config/update path. The minimal fix adds **only `interactRadius:0`** to this benchmark config (`tools/ocean_hydro_bench.hpp:150`); no reserve, seed, law, frozen constant or production path changes. Failure logs at`:19`, initial reserve/config logs at`:160`, and lifecycle totals at`:175` are tool-only; checks at`:170–173` retain2000 fish and identify the first failing step, including warm-up. [Diagnosis](../build_m2b1_pr2/round6/gate07_diagnosis.md), [reproduction log](../build_m2b1_pr2/round6/logs/gate07_diagnostic_reproduction.log).

**Retry1:** all four component builds and memory/stack/stress runs passed. The new external base-comparison script then failed the A/A screen: **1.1284243122310456**, deviation **12.8424% >3%**. Its apparent paired current/base.7719947281793474 is rejected performance evidence. All24 initial/final fingerprints and population/lifecycle checks matched. The scratch method initialized a fresh process/world per sample instead of following the prescribed immutable initialization and snapshot/RNG restore procedure. Raw rejected data is retained in [gate07_baseAA.json](../build_m2b1_pr2/round6/gate07_baseAA.json).

**Retry2, final permitted:** corrected scratch controls retain initialized snapshots and restore world/RNG before each repetition; both targets use the same recorded CPU1 affinity, with nice19 and the unchanged100 warm/200 measured/seven recorded/one discarded windows. All eight corrected controls build. Three native/plain groups pass the prescribed paired A/A screen:

| Scenario | Base ns/fish-step | Paired current/base | A/A deviation |
|---|---:|---:|---:|
| still | 2721.0143175 | 0.997342154424 | 0.138851015% |
| flow | 2920.30012 | 0.994339941173 | 0.378836541% |
| boundary | 2252.403035 | 1.00661577265 | 0.082515271% |

These72 samples retain2000 fish with zero births/deaths/reseeds and identical current/base initial/final fingerprints. They are **partial native/plain evidence**, with visibly bimodal raw timing retained; use the paired statistic, not a ratio of medians. [Raw samples/statistics](../build_m2b1_pr2/round6/gate07_retry2_baseAA.json), [affinity record](../build_m2b1_pr2/round6/timing_affinity.json).

The first Wasm/plain/still request then yielded EOF instead of a `LEGACY_SAMPLE` line: `gate07_retry2.py:55` asserted `('current', None, '')`. Both new scratch Wasm controls exited0, empty stderr, and no sample. The outer protocol exited **1**, wall **284.350742s**. This is **my scratch tool/protocol failure**; the stdin/request root cause was not established. There is no demonstrated blocked syscall and this is not an ENVIRONMENT-BLOCKED existing test. No more benchmark fixes or runs were attempted after this final permitted retry. [Final protocol log](../build_m2b1_pr2/round6/logs/gate07_retry2_protocol.log), [current Wasm command/no-sample log](../build_m2b1_pr2/round6/logs/gate07_retry2_server_wasm_plain_still_current.log), [base log](../build_m2b1_pr2/round6/logs/gate07_retry2_server_wasm_plain_still_base.log), [own-test ledger](../build_m2b1_pr2/round6/own_test_corrections.md).

Complete corrected H/internal-versus-legacy timing was never reached, and Wasm/eye base timing is incomplete. The initial discarded H sample is not acceptance evidence. R and L, net H−R+L and remaining numerical allowance are unestablished; the supplied+448 ns/fish-step engineering allowance is unchanged. Complete-world paired Wasm M2/legacy≤1.25 remains a PR3 obligation and is not claimed here.

## Completed memory, stack and stress evidence

All four `--mechanics-components --memory-only` commands exit0. These measure resident physics/gene/owner payload1260 B/fish (916+240+76+20+8), exact capacities2000, usable allocation and all six columns' measured allocator overhead, conservatively charging even existing-Fish column overhead to the physics increment. Existing Fish payload is reported separately. Both per-live and per-slot capacity are1260 B; all charged totals remain below1404.

| Target | Charged B/fish | Construction touched stack B | Diagnostic/export touched stack B | Snapshot+working usable physics B |
|---|---:|---:|---:|---:|
| native_plain | 1266.864 | 42696 | 42696 | 5059856 |
| wasm_plain | 1260.024 | 67272 | 67272 | 5040040 |
| native_eye | 1266.544 | 42808 | 42808 | 5059856 |
| wasm_eye | 1260.024 | 67592 | 67592 | 5040040 |

Snapshot+working capacity is5,040,000 physics bytes. Native touched-stack probes include their painted pthread worker entry/exit; Wasm probes use painted unused data-stack space. Every run measures construction, streamed diagnostics/export (916-byte record plus1924-byte diagnostics), reserve loss/co-moving refill, and64-death/64-birth-shaped stable aligned compaction returning to2000 owners, without overcapacity growth. Workspace sizes and auxiliary timings are in the raw memory logs. [Structured memory evidence](../build_m2b1_pr2/round6/gate07_memory.json).

Memory ran before timing in separate processes, an ordering deviation made explicit here; no build overlapped a timed window. This completed memory portion does not turn the incomplete Gate7 timing protocol into a pass.

## Gates, commands and status

| Gate | Round6 result |
|---|---|
| Integration audit / protected scope | Pass; no production integration change |
| 2 focused optimized + separate UBSan | Pass |
| 3 independent native reference + measurement units | Pass |
| 4 cumulative assays, identical freeze, rebuilt positive/faulted check-all | Pass |
| 5 deterministic native/Wasm/repeat fixtures before installation | Pass |
| 6 full requested Ocean parity | Pass, exit0 |
| 7 memory, stack high-water, stress | Pass for native/Wasm plain/eye |
| 7 complete timing with A/A versus4bafeb2 | **Incomplete; final own-tool retry failed** |
| 8 Ocean rebuild/freshness | Unrun |
| 9 Classic rebuild/freshness | Unrun |
| 10 native repository configure/build/ctest | Unrun |
| 11 module consumers and TypeScript | Unrun; existing offline TypeScript5.6.3 was only identified, not executed |
| 12 final release audit | Unrun; separate read-only stop-state check below is not this gate |

No existing test was environment-blocked. Gates2–6 needed no own-test rerun this round. Gate7 used its two protocol reruns after diagnosis; the successful initial diagnostic compilation's formatting warning/rebuild preceded any diagnostic execution and remains visible. No third protocol retry is available this round. Browser/live enabled-world rendering/checkpoint/export checks remain PR3, as the plan specifies.

Every executed gated command is recorded below with raw exit, wall and log; expected fault exits1 and failed own-test attempts are not relabeled. `R` abbreviates the absolute `build_m2b1_pr2/round6` directory; `B` is `build_m2b1_pr2/base_4bafeb2`. Full argument/environment records, including all per-window control commands, are in [commands.jsonl](../build_m2b1_pr2/round6/commands.jsonl). Nested protocol/server wall times overlap and must not be summed. All execution uses nice19; builds ≤2 jobs×2 threads, EMCC/Binaryen each1; final timing affinity1 is recorded. No network, .git write, browser, supervisor, rebaseline, merge or deployment.

| Command | Exit | Wall s | Log |
|---|---:|---:|---|
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tests/ocean_tests.cpp -o R/precision_tests` | 0 | 110.301 | [precision_gate02_build](../build_m2b1_pr2/round6/logs/precision_gate02_build.log) |
| `nice -n 19 R/precision_tests --only hydro` | 0 | 1.953 | [precision_gate02_hydro](../build_m2b1_pr2/round6/logs/precision_gate02_hydro.log) |
| `nice -n 19 R/precision_tests --only hydro_step` | 0 | 3.180 | [precision_gate02_hydro_step](../build_m2b1_pr2/round6/logs/precision_gate02_hydro_step.log) |
| `nice -n 19 g++ -O1 -g0 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -fsanitize=undefined -fno-sanitize-recover=all tests/ocean_tests.cpp -o R/precision_tests_ubsan` | 0 | 57.061 | [precision_gate02_ubsan_build](../build_m2b1_pr2/round6/logs/precision_gate02_ubsan_build.log) |
| `nice -n 19 R/precision_tests_ubsan --only hydro` | 0 | 3.078 | [precision_gate02_ubsan_hydro](../build_m2b1_pr2/round6/logs/precision_gate02_ubsan_hydro.log) |
| `nice -n 19 R/precision_tests_ubsan --only hydro_step` | 0 | 8.386 | [precision_gate02_ubsan_hydro_step](../build_m2b1_pr2/round6/logs/precision_gate02_ubsan_hydro_step.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_reference.cpp -o R/precision_reference` | 0 | 16.863 | [precision_gate03_build](../build_m2b1_pr2/round6/logs/precision_gate03_build.log) |
| `nice -n 19 R/precision_reference` | 0 | 0.395 | [precision_gate03_reference](../build_m2b1_pr2/round6/logs/precision_gate03_reference.log) |
| `nice -n 19 bash tests/ocean_hydro_measurements.sh` | 0 | 5.543 | [precision_measurement_units](../build_m2b1_pr2/round6/logs/precision_measurement_units.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_assay.cpp -o R/precision_stage3` | 0 | 20.425 | [precision_stage3_build](../build_m2b1_pr2/round6/logs/precision_stage3_build.log) |
| `nice -n 19 R/precision_stage3 --assay 4 --trace R/precision_assays1234.stage3.csv --manifest R/precision_assays1234.stage3.json --emit-calibration R/precision_stage4.hpp --build-id 4bafeb2-round6-stage3` | 0 | 9.457 | [precision_assays1234_stage3](../build_m2b1_pr2/round6/logs/precision_assays1234_stage3.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_assay.cpp -o R/precision_final_assay` | 0 | 20.557 | [precision_stage4_rebuild](../build_m2b1_pr2/round6/logs/precision_stage4_rebuild.log) |
| `nice -n 19 R/precision_final_assay --check-all --manifest R/precision_final_check_all.json --build-id 4bafeb2-round6-stage4` | 0 | 7.665 | [precision_final_check_all](../build_m2b1_pr2/round6/logs/precision_final_check_all.log) |
| `nice -n 19 python3 R/freeze.py` | 0 | 58.378 | [gate04_freeze](../build_m2b1_pr2/round6/logs/gate04_freeze.log) |
| `nice -n 19 env HYDRO_ACCOUNTING_OUT=R/precision_faults bash tests/ocean_hydro_accounting.sh` | 0 | 179.372 | [gate04_faults](../build_m2b1_pr2/round6/logs/gate04_faults.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_fixture.cpp -o R/corrected_hydro` | 0 | 10.600 | [gate05_retry2_hydro_native_build](../build_m2b1_pr2/round6/logs/gate05_retry2_hydro_native_build.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sNODERAWFS=1 -sEXIT_RUNTIME=1 tools/ocean_hydro_fixture.cpp -o R/corrected_hydro.js` | 0 | 8.140 | [gate05_retry2_hydro_wasm_build](../build_m2b1_pr2/round6/logs/gate05_retry2_hydro_wasm_build.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sNODERAWFS=1 -sEXIT_RUNTIME=1 tools/ocean_hydro_assay.cpp -o R/precision_final_assay.js` | 0 | 18.262 | [gate05_retry2_assay_wasm_build](../build_m2b1_pr2/round6/logs/gate05_retry2_assay_wasm_build.log) |
| `nice -n 19 node R/precision_final_assay.js --check-all --manifest R/precision_final_wasm_check_all.json --target wasm` | 0 | 9.027 | [precision_final_wasm_check_all](../build_m2b1_pr2/round6/logs/precision_final_wasm_check_all.log) |
| `nice -n 19 R/precision_faults/conversion_minus --check-all --manifest R/precision_final_fault_conversion_minus.json` | 1 | 7.613 | [precision_final_fault_conversion_minus](../build_m2b1_pr2/round6/logs/precision_final_fault_conversion_minus.log) |
| `nice -n 19 R/precision_faults/conversion_plus --check-all --manifest R/precision_final_fault_conversion_plus.json` | 1 | 7.612 | [precision_final_fault_conversion_plus](../build_m2b1_pr2/round6/logs/precision_final_fault_conversion_plus.log) |
| `nice -n 19 R/precision_faults/free_low --check-all --manifest R/precision_final_fault_free_low.json` | 1 | 7.858 | [precision_final_fault_free_low](../build_m2b1_pr2/round6/logs/precision_final_fault_free_low.log) |
| `nice -n 19 R/precision_faults/free_high --check-all --manifest R/precision_final_fault_free_high.json` | 1 | 7.660 | [precision_final_fault_free_high](../build_m2b1_pr2/round6/logs/precision_final_fault_free_high.log) |
| `nice -n 19 R/precision_faults/in_band_undercharge --check-all --manifest R/precision_final_fault_in_band_undercharge.json` | 1 | 7.715 | [precision_final_fault_in_band_undercharge](../build_m2b1_pr2/round6/logs/precision_final_fault_in_band_undercharge.log) |
| `nice -n 19 python3 R/fixture_gate_retry2.py` | 0 | 161.580 | [gate05_fixtures](../build_m2b1_pr2/round6/logs/gate05_fixtures.log) |
| `nice -n 19 env -u FAST -u ONLY -u NO_TESTS -u NO_EYE APP_TWINS=all JOBS=2 BUILD_JOBS=2 KEEP_OUT=1 OCEAN_PARITY_DIR=R/full_ocean_parity bash wasm/ocean_parity.sh` | 0 | 2583.830 | [gate06_full_ocean_parity](../build_m2b1_pr2/round6/logs/gate06_full_ocean_parity.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -pthread tools/ocean_eye_bench.cpp -o R/bench_diagnostic` | 0 | 31.241 | [gate07_diagnostic_build](../build_m2b1_pr2/round6/logs/gate07_diagnostic_build.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -pthread tools/ocean_eye_bench.cpp -o R/bench_diagnostic` | 0 | 31.402 | [gate07_diagnostic_build_formatfix](../build_m2b1_pr2/round6/logs/gate07_diagnostic_build_formatfix.log) |
| `nice -n 19 R/bench_diagnostic --mechanics-components` | 2 | 32.973 | [gate07_diagnostic_reproduction](../build_m2b1_pr2/round6/logs/gate07_diagnostic_reproduction.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -pthread tools/ocean_eye_bench.cpp -o R/bench_plain` | 0 | 25.916 | [gate07_retry1_build_native_plain](../build_m2b1_pr2/round6/logs/gate07_retry1_build_native_plain.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sEXIT_RUNTIME=1 -sSTACK_SIZE=8388608 tools/ocean_eye_bench.cpp -o R/bench_plain.js` | 0 | 21.602 | [gate07_retry1_build_wasm_plain](../build_m2b1_pr2/round6/logs/gate07_retry1_build_wasm_plain.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I B/src -I B/tools R/legacy_sample.cpp -o R/legacy_base_native_plain` | 0 | 24.939 | [gate07_build_legacy_base_native_plain](../build_m2b1_pr2/round6/logs/gate07_build_legacy_base_native_plain.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I B/src -I B/tools -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sEXIT_RUNTIME=1 -sSTACK_SIZE=8388608 R/legacy_sample.cpp -o R/legacy_base_wasm_plain.js` | 0 | 21.855 | [gate07_build_legacy_base_wasm_plain](../build_m2b1_pr2/round6/logs/gate07_build_legacy_base_wasm_plain.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -I tools R/legacy_sample.cpp -o R/legacy_current_native_plain` | 0 | 23.137 | [gate07_build_legacy_current_native_plain](../build_m2b1_pr2/round6/logs/gate07_build_legacy_current_native_plain.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -I tools -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sEXIT_RUNTIME=1 -sSTACK_SIZE=8388608 R/legacy_sample.cpp -o R/legacy_current_wasm_plain.js` | 0 | 20.355 | [gate07_build_legacy_current_wasm_plain](../build_m2b1_pr2/round6/logs/gate07_build_legacy_current_wasm_plain.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -DEVO_OCEAN_EYE -pthread tools/ocean_eye_bench.cpp -o R/bench_eye` | 0 | 33.484 | [gate07_retry1_build_native_eye](../build_m2b1_pr2/round6/logs/gate07_retry1_build_native_eye.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -DEVO_OCEAN_EYE -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sEXIT_RUNTIME=1 -sSTACK_SIZE=8388608 tools/ocean_eye_bench.cpp -o R/bench_eye.js` | 0 | 26.035 | [gate07_retry1_build_wasm_eye](../build_m2b1_pr2/round6/logs/gate07_retry1_build_wasm_eye.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I B/src -I B/tools -DEVO_OCEAN_EYE R/legacy_sample.cpp -o R/legacy_base_native_eye` | 0 | 26.465 | [gate07_build_legacy_base_native_eye](../build_m2b1_pr2/round6/logs/gate07_build_legacy_base_native_eye.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I B/src -I B/tools -DEVO_OCEAN_EYE -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sEXIT_RUNTIME=1 -sSTACK_SIZE=8388608 R/legacy_sample.cpp -o R/legacy_base_wasm_eye.js` | 0 | 24.929 | [gate07_build_legacy_base_wasm_eye](../build_m2b1_pr2/round6/logs/gate07_build_legacy_base_wasm_eye.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -I tools -DEVO_OCEAN_EYE R/legacy_sample.cpp -o R/legacy_current_native_eye` | 0 | 26.681 | [gate07_build_legacy_current_native_eye](../build_m2b1_pr2/round6/logs/gate07_build_legacy_current_native_eye.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -I tools -DEVO_OCEAN_EYE -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sEXIT_RUNTIME=1 -sSTACK_SIZE=8388608 R/legacy_sample.cpp -o R/legacy_current_wasm_eye.js` | 0 | 24.882 | [gate07_build_legacy_current_wasm_eye](../build_m2b1_pr2/round6/logs/gate07_build_legacy_current_wasm_eye.log) |
| `nice -n 19 R/bench_plain --mechanics-components --memory-only` | 0 | 5.153 | [gate07_retry1_memory_native_plain](../build_m2b1_pr2/round6/logs/gate07_retry1_memory_native_plain.log) |
| `nice -n 19 node --single-threaded --v8-pool-size=1 R/bench_plain.js --mechanics-components --memory-only` | 0 | 6.114 | [gate07_retry1_memory_wasm_plain](../build_m2b1_pr2/round6/logs/gate07_retry1_memory_wasm_plain.log) |
| `nice -n 19 R/bench_eye --mechanics-components --memory-only` | 0 | 5.084 | [gate07_retry1_memory_native_eye](../build_m2b1_pr2/round6/logs/gate07_retry1_memory_native_eye.log) |
| `nice -n 19 node --single-threaded --v8-pool-size=1 R/bench_eye.js --mechanics-components --memory-only` | 0 | 6.214 | [gate07_retry1_memory_wasm_eye](../build_m2b1_pr2/round6/logs/gate07_retry1_memory_wasm_eye.log) |
| `nice -n 19 python3 R/gate07.py` | 1 | 359.053 | [gate07_retry1_protocol](../build_m2b1_pr2/round6/logs/gate07_retry1_protocol.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I B/src -I B/tools R/legacy_server.cpp -o R/server_base_native_plain` | 0 | 21.242 | [gate07_retry2_build_server_base_native_plain](../build_m2b1_pr2/round6/logs/gate07_retry2_build_server_base_native_plain.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I B/src -I B/tools -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sEXIT_RUNTIME=1 -sSTACK_SIZE=8388608 R/legacy_server.cpp -o R/server_base_wasm_plain.js` | 0 | 17.033 | [gate07_retry2_build_server_base_wasm_plain](../build_m2b1_pr2/round6/logs/gate07_retry2_build_server_base_wasm_plain.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -I tools R/legacy_server.cpp -o R/server_current_native_plain` | 0 | 25.375 | [gate07_retry2_build_server_current_native_plain](../build_m2b1_pr2/round6/logs/gate07_retry2_build_server_current_native_plain.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -I tools -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sEXIT_RUNTIME=1 -sSTACK_SIZE=8388608 R/legacy_server.cpp -o R/server_current_wasm_plain.js` | 0 | 17.055 | [gate07_retry2_build_server_current_wasm_plain](../build_m2b1_pr2/round6/logs/gate07_retry2_build_server_current_wasm_plain.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I B/src -I B/tools -DEVO_OCEAN_EYE R/legacy_server.cpp -o R/server_base_native_eye` | 0 | 20.875 | [gate07_retry2_build_server_base_native_eye](../build_m2b1_pr2/round6/logs/gate07_retry2_build_server_base_native_eye.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I B/src -I B/tools -DEVO_OCEAN_EYE -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sEXIT_RUNTIME=1 -sSTACK_SIZE=8388608 R/legacy_server.cpp -o R/server_base_wasm_eye.js` | 0 | 24.403 | [gate07_retry2_build_server_base_wasm_eye](../build_m2b1_pr2/round6/logs/gate07_retry2_build_server_base_wasm_eye.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -I tools -DEVO_OCEAN_EYE R/legacy_server.cpp -o R/server_current_native_eye` | 0 | 26.005 | [gate07_retry2_build_server_current_native_eye](../build_m2b1_pr2/round6/logs/gate07_retry2_build_server_current_native_eye.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -I tools -DEVO_OCEAN_EYE -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sEXIT_RUNTIME=1 -sSTACK_SIZE=8388608 R/legacy_server.cpp -o R/server_current_wasm_eye.js` | 0 | 24.077 | [gate07_retry2_build_server_current_wasm_eye](../build_m2b1_pr2/round6/logs/gate07_retry2_build_server_current_wasm_eye.log) |
| `nice -n 19 R/server_base_native_plain still '{"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"predatorCount":0,"minPopulation":0,"maxPopulation":2000,"metabolicRate":0,"moveCost":0,"geneCost":0,"reproEnergy":1000000,"interactRadius":0,"toroidal":true}'` | 0 | 36.730 | [gate07_retry2_server_native_plain_still_base](../build_m2b1_pr2/round6/logs/gate07_retry2_server_native_plain_still_base.log) |
| `nice -n 19 R/server_current_native_plain still '{"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"predatorCount":0,"minPopulation":0,"maxPopulation":2000,"metabolicRate":0,"moveCost":0,"geneCost":0,"reproEnergy":1000000,"interactRadius":0,"toroidal":true}'` | 0 | 36.730 | [gate07_retry2_server_native_plain_still_current](../build_m2b1_pr2/round6/logs/gate07_retry2_server_native_plain_still_current.log) |
| `nice -n 19 R/server_base_native_plain flow '{"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"predatorCount":0,"minPopulation":0,"maxPopulation":2000,"metabolicRate":0,"moveCost":0,"geneCost":0,"reproEnergy":1000000,"interactRadius":0,"toroidal":true,"currentStrength":5,"currentMode":1}'` | 0 | 42.047 | [gate07_retry2_server_native_plain_flow_base](../build_m2b1_pr2/round6/logs/gate07_retry2_server_native_plain_flow_base.log) |
| `nice -n 19 R/server_current_native_plain flow '{"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"predatorCount":0,"minPopulation":0,"maxPopulation":2000,"metabolicRate":0,"moveCost":0,"geneCost":0,"reproEnergy":1000000,"interactRadius":0,"toroidal":true,"currentStrength":5,"currentMode":1}'` | 0 | 42.047 | [gate07_retry2_server_native_plain_flow_current](../build_m2b1_pr2/round6/logs/gate07_retry2_server_native_plain_flow_current.log) |
| `nice -n 19 R/server_base_native_plain boundary '{"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"predatorCount":0,"minPopulation":0,"maxPopulation":2000,"metabolicRate":0,"moveCost":0,"geneCost":0,"reproEnergy":1000000,"interactRadius":0,"toroidal":false}'` | 0 | 28.735 | [gate07_retry2_server_native_plain_boundary_base](../build_m2b1_pr2/round6/logs/gate07_retry2_server_native_plain_boundary_base.log) |
| `nice -n 19 R/server_current_native_plain boundary '{"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"predatorCount":0,"minPopulation":0,"maxPopulation":2000,"metabolicRate":0,"moveCost":0,"geneCost":0,"reproEnergy":1000000,"interactRadius":0,"toroidal":false}'` | 0 | 28.735 | [gate07_retry2_server_native_plain_boundary_current](../build_m2b1_pr2/round6/logs/gate07_retry2_server_native_plain_boundary_current.log) |
| `nice -n 19 node --single-threaded --v8-pool-size=1 R/server_base_wasm_plain.js still '{"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"predatorCount":0,"minPopulation":0,"maxPopulation":2000,"metabolicRate":0,"moveCost":0,"geneCost":0,"reproEnergy":1000000,"interactRadius":0,"toroidal":true}'` | 0 | 0.255 | [gate07_retry2_server_wasm_plain_still_base](../build_m2b1_pr2/round6/logs/gate07_retry2_server_wasm_plain_still_base.log) |
| `nice -n 19 node --single-threaded --v8-pool-size=1 R/server_current_wasm_plain.js still '{"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"predatorCount":0,"minPopulation":0,"maxPopulation":2000,"metabolicRate":0,"moveCost":0,"geneCost":0,"reproEnergy":1000000,"interactRadius":0,"toroidal":true}'` | 0 | 0.254 | [gate07_retry2_server_wasm_plain_still_current](../build_m2b1_pr2/round6/logs/gate07_retry2_server_wasm_plain_still_current.log) |
| `nice -n 19 taskset -c 1 python3 R/gate07_retry2.py` | 1 | 284.351 | [gate07_retry2_protocol](../build_m2b1_pr2/round6/logs/gate07_retry2_protocol.log) |
| `nice -n 19 python3 R/gate12_audit.py` | 0 | 0.101 | [stop_scope_audit](../build_m2b1_pr2/round6/logs/stop_scope_audit.log) |
| `nice -n 19 python3 R/stop_report_verify.py` | 0 | 0.265 | [stop_report_verify](../build_m2b1_pr2/round6/logs/stop_report_verify.log) |

## Module identities and stop-state audit

These are current-main/start-of-round hashes, still unchanged. **Rebuild/freshness Gates8–9 were not executed**, so unchanged bytes are not a fresh-build pass. Round5 module hashes predate main4bafeb2 and are historical only.

| Module | SHA256 |
|---|---|
| `web/evo_boids.js` | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` |
| `web/evo_boids.wasm` | `d05c4442e15d6850aeece60e52c2a69289d10a2d39fd17538b2347123be0a99b` |
| `web/evo_boids_mt.js` | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` |
| `web/evo_boids_mt.wasm` | `1c86e3d2a8c043e17ab1e75004ad37d9d20a70ce5498a80e4ae4bf4fdd8a703b` |
| `web/evo_ocean.js` | `8bdce72bd8991c6e88768712b60cec9b7dd0cf22335d82ebe67f40cef6d91059` |
| `web/evo_ocean.wasm` | `e55a4fcb2e7c2e737c6f0cc838c783237ba138336f1162ab4ddf037468b5f2f1` |

The read-only stop-state audit exits0: HEAD/branch match the approved base; historical baselines, src/core, production world/topic/config/checkpoint/module/fingerprint/rendering paths remain unchanged against4bafeb2; all internal kernel/reference/assay/harness/calorimetry sources match the pre-Round6 hashes; header and fixture identities match; all changed paths are accounted for. It is called `stop_scope_audit` in the command record and does **not** complete release Gate12. [Stop-state audit](../build_m2b1_pr2/round6/stop_scope_audit.json). Post-report whitespace/identity verification also passed exit0 in0.265s, confirming only the benchmark header/report changed this round, historical report preservation and all36 paths assigned once. [Verification](../build_m2b1_pr2/round6/stop_report_verify.json).

## Remaining work and proposed coordinator commits

A new round must repair and validate the scratch Wasm request protocol, complete the entire Gate7 timing matrix against4bafeb2, then run Ocean rebuild/freshness, Classic rebuild/freshness with unchanged bytes, repository checks, module consumers, TypeScript and the final release audit. None may be inferred from the stopped run. Existing calibrated limitations and PR3's public activation/lifecycle/ownership/checkpoint/export/rendering and whole-world performance obligations remain unchanged.

Proposed split, **not commit-ready as a completed release**. The stop-state inventory validates36 changed files, each assigned exactly once below. Scratch build outputs/raw evidence under `build_m2b1_pr2` are not committed. No module-artifact commit is proposed now; required freshness remains unrun.

**1. Add internal Ocean mechanics and fuel accounting**

- `src/ocean/hydro_coefficients.hpp`
- `src/ocean/hydro_contact.hpp`
- `src/ocean/hydro_step.hpp`
- `src/ocean/ocean_energy.hpp`
- `tests/ocean_hydro_step_tests.hpp`
- `tests/ocean_hydro_tests.hpp`
- `tests/ocean_tests.cpp`

**2. Freeze Ocean mechanics assays and deterministic fixtures**

- `docs/_ref/check_m2b2_gate2_diag_codex.md`
- `docs/_ref/m2b1_brief_codex.md`
- `docs/_ref/m2b1_pr2_plan_codex.md`
- `docs/_ref/m2b2_gate4_diag_check_codex.md`
- `docs/m2b1_pr2.md`
- `docs/m2b2_gate2_diag.md`
- `docs/m2b2_gate4_diag.md`
- `docs/m2b3_assay3_diag.md`
- `docs/m2b3_assay3_diag2.md`
- `src/ocean/hydro_calibration.hpp`
- `tests/fixtures/ocean_hydro_calibration.json`
- `tests/fixtures/ocean_hydro_fixture.json`
- `tests/fixtures/ocean_hydro_step_fixture.json`
- `tests/ocean_hydro_accounting.sh`
- `tests/ocean_hydro_measurements.cpp`
- `tests/ocean_hydro_measurements.sh`
- `tools/ocean_eye_bench.cpp`
- `tools/ocean_hydro_assay.cpp`
- `tools/ocean_hydro_bench.hpp`
- `tools/ocean_hydro_calibration_io.hpp`
- `tools/ocean_hydro_calorimetry.hpp`
- `tools/ocean_hydro_fixture.cpp`
- `tools/ocean_hydro_harness.hpp`
- `tools/ocean_hydro_measurements.hpp`
- `tools/ocean_hydro_memory.hpp`
- `tools/ocean_hydro_reference.cpp`
- `tools/ocean_hydro_step_fixture.hpp`
- `tools/ocean_hydro_trajectory_reference.hpp`
- `wasm/ocean_parity.sh`

---

The complete prior report follows unchanged as historical evidence.

# M2b1 PR 2 — Round 5

Gates 1–6 pass under corrected D-M2b1-7. Gate 7 stopped at the fixed-population timing invariant after both permitted own-test retries; timing, memory and release gates 8–12 remain incomplete.

Gate 7 stopped on its final permitted own-test retry. Four benchmark builds passed, but `bench_plain --mechanics-components` exited **2** after its first discarded internal sample. The following legacy variant failed its population==2000 invariant (`tools/ocean_hydro_bench.hpp:149–150`); exact count, step and cause were not logged. No A/A result exists, so timing is **not passed**. The original public-symbol link failure and my subsequent declaration-conflict fix consumed the two allowed retries. No further timing run or benchmark fix was attempted. [Stop record](../build_m2b1_pr2/round5/gate07_stop.md).

The native plain allocation prefix measured **1,266.864 B/fish** including all six columns' allocator overhead (payload **1,260**, usable physics allocation **1,264.964**). This is **partial evidence**, not a completed memory gate: Wasm/eye measurements, stack high-water and stress checks were not reached. Gates **8–11 were not started**; release gate **12 remains incomplete**. A separate read-only stop-state audit verifies protected scope and artifact identities. This invariant failure is not an environment-blocked test. No release-readiness claim is made.

All work remains uncommitted; the coordinator owns commits. Earlier raw records and the prior report are retained.

## Corrected acceptance decision

> **D-M2b1-7 — PR-2 assay-4 acceptance amendment, under the recorded owner delegation (coordinator, 2026-11-25; corrected after an independent check).**
>
> **Unchanged:** `workConversion=.60/PmotorNeutral(82)`, the frozen denominator `44590.30078125` (`0x472e2e4d`), and every stage-1/2/3 constant and freeze. D3 remains not adopted.
>
> **Restrained reference.** Gate a freshly exercised restrained neutral reference at request 82 at `.60 E/s`, with absolute error at most `8*float_epsilon*.60`. Use the production conversion and measured work. Multiplying the two stored calibration values alone is not sufficient evidence.
>
> **Free cruise.** After the unchanged 600 s free-cruise preparation, measure the prescribed 120 s with metered incoming 25 E, `geneCost=0` and unchanged requests. Gate the finite measured motor component inclusively at `.592` through `.608 E/s`. This is a newly authorized component performance tolerance: the total's relative tolerance applied to the nominal motor share.
>
> **Attitude and depth.** This amendment accepts the reproduced PR-2 calorimetry state's essentially level trajectory, together with its disclosed body pitch and target-depth bias. It does not certify upright body attitude or target-depth tracking. Keep the existing straightness and settling checks. Report:
> - actual speed;
> - signed attitude;
> - depth versus target;
> - vertical velocity;
> - integrated vertical displacement;
> - stored drift;
> - regulator activity;
> - paid pump work.
>
> **Accounting.** Keep all other assay predicates and accounting tolerances. Independently reconstruct channel and pump work at the actual state, and include pump work once. Apply the prescribed motor/fatigue formula, and check every actual ledger subtraction using the prescribed binary32 arithmetic. The ±.008 performance band must never act as an accounting-error tolerance. These stay gating:
> - basal and maintenance;
> - total/debit;
> - metering;
> - extra work;
> - blocked thrust;
> - excess power;
> - free recovery.
>
> **Planted faults.** Exercise the ACTUAL measurement and predicate paths (end to end, not synthetic inputs to threshold helpers) with:
> - conversion errors of ±1%;
> - both out-of-band free-cruise values, `.591` and `.609 E/s`;
> - a cruise-only accounting fault that stays INSIDE the motor band, for example a `.0005 E/s` undercharge at the reproduced state. This fault must fail an independent accounting predicate.
>
> Each must exit nonzero and refuse to emit stage 4.
>
> **Disclosure.** Gate the free-cruise motor measurement, and also disclose its signed deviation from `.60`. Report the measured 1.38° driven pitch and the depth of 86.1 versus a target of 120 as known limitations, with the diagnosed trim, load and regulator mechanisms. Do not claim that these exhaustively account for the deficit.
>
> **Acceptance.** Reproducing `.592894794 E/s` satisfies only the amended motor performance predicate. Stage 4 may be emitted only after every required predicate passes. After that come the rebuild, the positive and faulted `--check-all`, and the prescribed final native/Wasm checks. Otherwise, stop under the plan's stop rule.
>
> **Margin.** Report the lower-bound margin: about `.000894794 E/s`, or `.149132` percentage points. Determinism supports repeatability for a fixed build and fixed inputs. After any change, acceptance is established by final-build parity and reruns.

## Step-1 audit and corrections

1. **Restrained reference — yes.** `tools/ocean_hydro_assay.cpp:544` freshly calls production `planActuators` at request 82 and tow velocity −82, then production `limitMotor` with the production conversion; `:546` gates its measured fuel rate and the next check verifies frozen work bits. This was already a measured production path.
2. **Original free-cruise faults — no.** They only supplied synthetic threshold-helper inputs. `tests/ocean_hydro_accounting.sh:12` now finds the real motor call in a scratch kernel header, injects the charge fault before the actual reserve debit, and `tools/ocean_hydro_assay.cpp:479` activates it only during the measured cruise. `tests/ocean_hydro_accounting.sh:43` runs cumulative assays with a header-emission request; `:47` verifies no header, `:53`/`:55` verify the actual failed predicates, and `:63` exercises genuine `--check-all`. Both conversion signs exercise the fresh restrained measurement.
3. **Original independent accounting — no for an in-band undercharge.** It trusted the receipt's motor fuel. Exact post-source state is now captured at `tools/ocean_hydro_harness.hpp:85` and passed at `tools/ocean_hydro_assay.cpp:115`. `tools/ocean_hydro_calorimetry.hpp:30` independently rebuilds channel work at actual local velocities; `:44` rebuilds pump work from the incoming loaded state and regulator; `:55` adds pump once. `:66` reconstructs the binary32 motor/fatigue formula without calling `limitMotor`; `:81` independently forms requested debit and `:83` checks each actual binary32 ledger subtraction, unpaid field and basal/maintenance/gene receipts. `tools/ocean_hydro_assay.cpp:504` gates independent motor/fatigue accounting. The .008 performance tolerance is absent from accounting.
4. **Straightness and settling.** Restored the unchanged settled-wrapper screens from `build_m2b1_pr2/diag4/diagnostic_settled.cpp:87–89` at `tools/ocean_hydro_assay.cpp:493`: max |vertical|<.01, |stored drift|<.1, |heading change|<1e-5. Corrected D-M2b1-7 explicitly requires retaining these trajectory checks. They do not certify upright attitude or target-depth tracking.

Details: [resume audit](../build_m2b1_pr2/round5/resume_audit.md). Own-test corrections, with retained failed logs and the two-rerun limit: [record](../build_m2b1_pr2/round5/own_test_corrections.md). Gate 5 correction 1 preserves exact binary32 ledger/unpaid reconstruction. Correction 2 addresses native/Wasm libm differences in 11 binary64 diagnostic result values (largest difference below 6e-15). Both pre-correction invariant suites passed and simulation windows/chains matched exactly. Deterministic fixtures now explicitly encode **only result.value as binary32**; raw manifests and predicate calculations retain binary64. No simulation, law, constant or acceptance tolerance was changed. Gate-5 retry 2 is the final permitted own-test retry.

## Constants and freeze

All stage-1/2/3 constants and measured power bits are unchanged. Stage 4 freezes the existing maintenance allocation (.04/.04/.02), confirms workConversion, and changes only the generated frozen-through integer to 4. D3 remains unadopted. Every re-emitted stage4 header is byte-identical to the pre-resume `stage4.hpp`.

| Constant | Binary32 value | Bits |
|---|---:|---|
| `kGravity` | 400 | `0x43c80000` |
| `kPressureDepthFraction` | 0.5 | `0x3f000000` |
| `kMetacentricFraction` | 2 | `0x40000000` |
| `kDepthGain` | 0.0799999982119 | `0x3da3d70a` |
| `kVerticalGain` | 0.20000000298 | `0x3e4ccccd` |
| `kRegulatorTau` | 2 | `0x40000000` |
| `kGasRateFraction` | 0.019999999553 | `0x3ca3d70a` |
| `kPumpEfficiency` | 0.25 | `0x3e800000` |
| `kStaticFriction` | 0.800000011921 | `0x3f4ccccd` |
| `kDynamicFriction` | 0.600000023842 | `0x3f19999a` |
| `kContactSlopPerSize` | 0.00499999988824 | `0x3ba3d70a` |
| `kPenetrationLimitPerSize` | 0.00999999977648 | `0x3c23d70a` |
| `kControllerTau` | 0.25 | `0x3e800000` |
| `kHeaveGain` | 1 | `0x3f800000` |
| `kPitchGain` | 1 | `0x3f800000` |
| `kPairedYawGain` | 3 | `0x40400000` |
| `kTailYawGain` | 1.02999997139 | `0x3f83d70a` |
| `kTailStiffSpeed` | 108 | `0x42d80000` |
| `kPairedInducedEfficiency` | 0.75 | `0x3f400000` |
| `kBrakeCd` | 1.10000002384 | `0x3f8ccccd` |
| `kMaintFin` | 0.04 | `0x3d23d70a` |
| `kMaintWall` | 0.04 | `0x3d23d70a` |
| `kMaintLipid` | 0.02 | `0x3ca3d70a` |
| `workConversion` | 1.34558413265e-05 | `0x3761c066` |
| `PmotorNeutral(82)` | 44590.3007812 | `0x472e2e4d` |
| `PmotorNeutral(108)` | 86410.53125 | `0x47a8c544` |

Unchanged anchors Uref/Usus/Uact=82/108/150, paired rowing efficiency=.35, tauBurst=2, gamma=.5. Law versions geometry/material/expression/reference/mechanics/energy=1/1/1/2/1/1; coefficient/support/state ABI=1/1/1. Base `ba6f29c6ee4a04b1ce41b27ab49e81443802968d`, branch `m2b1-pr2`; original prerequisite and stage-3 guard/no-change evidence remains under round5. Kernel, contact, energy, authority and independent-reference sources match the pre-resume hashes.

Generated header SHA256: `05400c4e22c62965c2c95e952db028e0fd23c5234f22a0e55a443fd1e21897c7`. Constants digest `d532fc22992356ab`; reference `34f5953354409576`; neutral coefficients/support `3e8bfae4938384af` / `44931eb40f7ec2ef`. No new constant bits were introduced at stage 4.

## Assays and final check-all

Final cumulative assays and rebuilt stage-4 native/Wasm positives pass **150/150** predicates: assay1 **33**, assay2 **32**, assay3 **62**, assay4 **23**. The first 127 assay1–3 predicates are preserved. The low-slip fixture exercises both geometry checks (total eligible course=5, heading=1); original five turns retain course=4, heading=0, explicitly not exercised for the latter. All preceding turn/release, rail, metering, fatigue and body-ordering checks remain gating.

| Assay-4 measurement, after unchanged 600 s preparation | Actual | Result |
|---|---:|---|
| Restrained neutral request82 motor | .60 E/s; error 0 | Pass, error ≤8*float_epsilon*.60 |
| Free cruise motor / nominal 120 s | .592894793954 E/s | Pass, inclusive [.592,.608] |
| Signed deviation from .60 | −.00710520604625 E/s, −1.18420100771% | Disclosed |
| Lower-bound margin | .000894793953747 E/s, .149132325624 percentage points | Disclosed |
| Basal / maintenance | .800000037998 / .099999997474 E/s | Pass |
| Actual ledger total / debit | 1.49297714233 E/s / 179.157257080 E | Pass |
| Metered incoming / geneCost | 25 E before each of 15,000 substeps / zero | Pass |
| Independent channel/pump price error / fuel error | 0 / 0 | Pass |
| Turning / blocked motor work (10 s) | 18.6036390103 / 18.5989525625 E | Pass |
| 3× excess-power charge / free recovery | Formula passes / zero fuel, fatigue falls | Pass |
| Maximum abs(vertical) / stored depth drift / heading change | .00034661841346 / 0 / 0 | Pass preserved screens |

Every ledger subtraction matches prescribed binary32 arithmetic exactly. Accumulated requested-component sum differs from actual debit by **+.00987754901871 E**, explained by rounded subtraction from incoming 25 E. The ledger predicate's printed value is that disclosed accumulated rounding amount, not an error compared with its zero sentinel. Actual debit drives total/debit gates; independent motor/fatigue and ledger comparisons use exact binary32 values, never the ±.008 performance band.

The five planted faults each exit **1**, refuse stage4 emission, and also exit 1 through `--check-all`. Conversion −1%/+1% fails the freshly measured restrained predicate. Free .591/.609 fails the measured motor band and independent accounting. The **.0005 E/s undercharge** gives approximately **.592394790146 E/s**, inside the motor band; both independent motor/fatigue and exact-ledger predicates reject it (per-substep fuel error `4.00003045797e-6 E`). Fresh final binaries were built after the serialization/trajectory corrections; all negatives were rerun after the stage4 rebuild. Evidence: `precision_faults/`, `precision_final_fault_*.json`, `precision_final_check_all.json` and `precision_final_wasm_check_all.json` in [round5](../build_m2b1_pr2/round5/).

## Attitude, depth and known limitations

Actual horizontal speed **82.0059509278 u/s**, body-forward **81.982170105**, body-vertical **−1.975693703**. Signed pitch **+1.38074980601°**, roll **+.00001366434475°**. Depth **86.1397781372** versus target **120**. Mean/max vertical velocity **+.00034661841346 u/s**; integrated upward displacement **+.0415942115908 u** over nominal120 s, while stored depth drift is zero. Regulator is active in every measurement substep at gas rate **−.0000371932983398/s**, lambda=1; integrated requested gas change **−.00446319601277**, stored gas remains **24.9419345856**. Paid pump work is **.0000193609988875 E** in cruise and **.0767674281856 E** during preparation, included once in motor fuel.

Fin-centroid forward thrust produces driven pitch. Gas compression and the regulator-biased gas volume change the loaded geometry, drag and actuator levers relative to the restrained reference. Tilted thrust and passive force coupling balance regulator-created negative buoyancy at a biased depth. Depth/gas increments on the plateau fall below binary32 representability, explaining stored zero drift despite residual velocity and paid regulation. These diagnosed trim/load/regulator mechanisms **do not exhaustively account for the motor deficit**. Corrected acceptance covers this reproduced essentially level trajectory; it certifies neither upright body attitude nor target-depth tracking. Determinism establishes fixed-build repeatability; after changes, final-build parity and reruns establish acceptance.

Other limitations remain: prescribed four-sweep local contact may select dynamic friction despite feasible aggregate static balance; COM-floor-projection load is sampled once per outer step and held over substeps; stage1 restoring stiffness is ~16.7× its start (neutral lever ~8.07u); large-slip reduced-speed turns meet the amended heading gate without proving speed82/radius31; six partial-yaw local reversals near exhaustion remain disclosed in the preserved Round4 tables. No solver redesign, D3, RNG reorder or production activation occurred.

## Fixtures, release gates and scope
All three deterministic emissions matched **native == Wasm == native repeat before installation**; installed files were then hash-checked. Step fixture has 140 invariant cases / 52,448 substeps plus the full 150-predicate assay and 43 windows.

| Fixture | SHA256 |
|---|---|
| `tests/fixtures/ocean_hydro_fixture.json` | `464d48b63a2b7c417b453fa9ffb727b70a485d588358f6673f1a8ed37aae19d7` |
| `tests/fixtures/ocean_hydro_step_fixture.json` | `5df21311a807ffecafbedbe6f8be34af30faef28d3ef9e2dbe627f101f42b1ce` |
| `tests/fixtures/ocean_hydro_calibration.json` | `ba4e9b9a788b1d20275986c5eb0c258ce78c429cf928f172e65797511db6faae` |

Raw commands, exact environments, exits, wall times and logs are retained in [commands.jsonl](../build_m2b1_pr2/round5/commands.jsonl). `R` below denotes the absolute round5 directory. Negative controls deliberately exit1; failed own-test attempts are retained, not relabeled. Every executed command is prefixed nice19; builds use at most2 jobs and runtime threading is bounded as recorded. No network, .git mutation, browser, merge, deployment or rebaseline.

| Command | Exit | Seconds | Log |
|---|---:|---:|---|
| `nice -n 19 git diff --exit-code ba6f29c -- src/core src/ocean/ocean_world.hpp src/ocean/ocean_config.hpp src/ocean/fish.hpp src/ocean/body_plan.hpp src/ocean/body_material.hpp src/ocean/hydro_math.hpp src/ocean/hydro_state.hpp wasm web tests/ocean_baseline tests/fixtures` | 0 | 0.062 | [gate01_scope](../build_m2b1_pr2/round5/logs/gate01_scope.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_assay.cpp -o R/guard` | 0 | 18.853 | [guard_build](../build_m2b1_pr2/round5/logs/guard_build.log) |
| `nice -n 19 R/guard --assay 3 --manifest R/guard_unchanged.json --trace R/guard_unchanged.csv --build-id round5-guard` | 0 | 5.503 | [guard_unchanged](../build_m2b1_pr2/round5/logs/guard_unchanged.log) |
| `nice -n 19 python3 R/verify_guard.py` | 0 | 0.212 | [guard_verify](../build_m2b1_pr2/round5/logs/guard_verify.log) |
| `nice -n 19 bash tests/ocean_hydro_measurements.sh` | 0 | 5.903 | [measurements](../build_m2b1_pr2/round5/logs/measurements.log) |
| `nice -n 19 python3 R/gate01.py` | 0 | 0.290 | [gate01_identity](../build_m2b1_pr2/round5/logs/gate01_identity.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tests/ocean_tests.cpp -o R/tests` | 0 | 110.491 | [gate02_optimized_build](../build_m2b1_pr2/round5/logs/gate02_optimized_build.log) |
| `nice -n 19 R/tests --only hydro` | 0 | 2.006 | [gate02_hydro](../build_m2b1_pr2/round5/logs/gate02_hydro.log) |
| `nice -n 19 R/tests --only hydro_step` | 0 | 3.189 | [gate02_hydro_step](../build_m2b1_pr2/round5/logs/gate02_hydro_step.log) |
| `nice -n 19 g++ -O1 -g0 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -fsanitize=undefined -fno-sanitize-recover=all tests/ocean_tests.cpp -o R/tests_ubsan` | 0 | 55.307 | [gate02_ubsan_build](../build_m2b1_pr2/round5/logs/gate02_ubsan_build.log) |
| `nice -n 19 R/tests_ubsan --only hydro` | 0 | 3.046 | [gate02_ubsan_hydro](../build_m2b1_pr2/round5/logs/gate02_ubsan_hydro.log) |
| `nice -n 19 R/tests_ubsan --only hydro_step` | 0 | 8.464 | [gate02_ubsan_hydro_step](../build_m2b1_pr2/round5/logs/gate02_ubsan_hydro_step.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_reference.cpp -o R/reference` | 0 | 17.519 | [gate03_build](../build_m2b1_pr2/round5/logs/gate03_build.log) |
| `nice -n 19 R/reference` | 0 | 0.399 | [gate03_reference](../build_m2b1_pr2/round5/logs/gate03_reference.log) |
| `nice -n 19 R/guard --assay 4 --trace R/assays1234.stage3.csv --manifest R/assays1234.stage3.json --emit-calibration R/stage4.hpp --build-id ba6f29c-round5-stage3` | 0 | 9.407 | [assays1234_stage3](../build_m2b1_pr2/round5/logs/assays1234_stage3.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -DPLANT_CAL4_CONVERSION_FAULT -I src tools/ocean_hydro_assay.cpp -o R/assay_fault` | 0 | 23.266 | [stage4_fault_build](../build_m2b1_pr2/round5/logs/stage4_fault_build.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_assay.cpp -o R/assay` | 0 | 23.602 | [stage4_build](../build_m2b1_pr2/round5/logs/stage4_build.log) |
| `nice -n 19 R/assay --check-all --manifest R/check_all.json --build-id ba6f29c-round5-stage4` | 0 | 7.639 | [check_all](../build_m2b1_pr2/round5/logs/check_all.log) |
| `nice -n 19 cp -a /home/harit/opt/emsdk/upstream/emscripten/cache R/em_cache` | 0 | 0.948 | [emcache_prepare](../build_m2b1_pr2/round5/logs/emcache_prepare.log) |
| `nice -n 19 R/assay_fault --check-all --manifest R/check_all_fault.json --build-id ba6f29c-round5-stage4` | 1 | 7.703 | [check_all_fault](../build_m2b1_pr2/round5/logs/check_all_fault.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sNODERAWFS=1 -sEXIT_RUNTIME=1 tools/ocean_hydro_fixture.cpp -o R/hydro.js` | 0 | 10.134 | [gate05_hydro_wasm_build](../build_m2b1_pr2/round5/logs/gate05_hydro_wasm_build.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_fixture.cpp -o R/hydro` | 0 | 11.393 | [gate05_hydro_native_build](../build_m2b1_pr2/round5/logs/gate05_hydro_native_build.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sNODERAWFS=1 -sEXIT_RUNTIME=1 tools/ocean_hydro_assay.cpp -o R/assay.js` | 0 | 20.528 | [gate05_assay_wasm_build](../build_m2b1_pr2/round5/logs/gate05_assay_wasm_build.log) |
| `nice -n 19 python3 R/emit_compare.py` | 1 | 8.340 | [gate05_emit_compare](../build_m2b1_pr2/round5/logs/gate05_emit_compare.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src R/fixture_probe.cpp -o R/fixture_probe` | 1 | 0.026 | [fixture_probe_build](../build_m2b1_pr2/round5/logs/fixture_probe_build.log) |
| `nice -n 19 R/fixture_probe` | 127 | 0.007 | [fixture_probe](../build_m2b1_pr2/round5/logs/fixture_probe.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src R/fixture_probe.cpp -o R/fixture_probe` | 0 | 12.612 | [fixture_probe_build_retry1](../build_m2b1_pr2/round5/logs/fixture_probe_build_retry1.log) |
| `nice -n 19 R/fixture_probe` | 1 | 0.016 | [fixture_probe_retry1](../build_m2b1_pr2/round5/logs/fixture_probe_retry1.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_assay.cpp -o R/corrected_assay` | 1 | 2.450 | [corrected_assay_build](../build_m2b1_pr2/round5/logs/corrected_assay_build.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_assay.cpp -o R/corrected_assay` | 0 | 21.178 | [corrected_assay_build_retry1](../build_m2b1_pr2/round5/logs/corrected_assay_build_retry1.log) |
| `nice -n 19 R/corrected_assay --check-all --manifest R/corrected_probe.json` | 0 | 7.684 | [corrected_positive_probe](../build_m2b1_pr2/round5/logs/corrected_positive_probe.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tests/ocean_tests.cpp -o R/corrected_tests` | 0 | 114.137 | [corrected_gate02_build](../build_m2b1_pr2/round5/logs/corrected_gate02_build.log) |
| `nice -n 19 R/corrected_tests --only hydro` | 0 | 1.970 | [corrected_gate02_hydro](../build_m2b1_pr2/round5/logs/corrected_gate02_hydro.log) |
| `nice -n 19 R/corrected_tests --only hydro_step` | 0 | 3.163 | [corrected_gate02_hydro_step](../build_m2b1_pr2/round5/logs/corrected_gate02_hydro_step.log) |
| `nice -n 19 env HYDRO_ACCOUNTING_OUT=R/corrected_faults bash tests/ocean_hydro_accounting.sh` | 0 | 186.331 | [corrected_e2e_faults](../build_m2b1_pr2/round5/logs/corrected_e2e_faults.log) |
| `nice -n 19 g++ -O1 -g0 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -fsanitize=undefined -fno-sanitize-recover=all tests/ocean_tests.cpp -o R/corrected_tests_ubsan` | 0 | 53.846 | [corrected_gate02_ubsan_build](../build_m2b1_pr2/round5/logs/corrected_gate02_ubsan_build.log) |
| `nice -n 19 R/corrected_tests_ubsan --only hydro` | 0 | 3.038 | [corrected_gate02_ubsan_hydro](../build_m2b1_pr2/round5/logs/corrected_gate02_ubsan_hydro.log) |
| `nice -n 19 R/corrected_tests_ubsan --only hydro_step` | 0 | 8.348 | [corrected_gate02_ubsan_hydro_step](../build_m2b1_pr2/round5/logs/corrected_gate02_ubsan_hydro_step.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_reference.cpp -o R/corrected_reference` | 0 | 16.900 | [corrected_gate03_build](../build_m2b1_pr2/round5/logs/corrected_gate03_build.log) |
| `nice -n 19 R/corrected_reference` | 0 | 0.404 | [corrected_gate03_reference](../build_m2b1_pr2/round5/logs/corrected_gate03_reference.log) |
| `nice -n 19 bash tests/ocean_hydro_measurements.sh` | 0 | 5.530 | [corrected_measurement_units](../build_m2b1_pr2/round5/logs/corrected_measurement_units.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_assay.cpp -o R/corrected_stage3` | 0 | 20.308 | [corrected_stage3_build](../build_m2b1_pr2/round5/logs/corrected_stage3_build.log) |
| `nice -n 19 R/corrected_stage3 --assay 4 --trace R/corrected_assays1234.stage3.csv --manifest R/corrected_assays1234.stage3.json --emit-calibration R/corrected_stage4.hpp --build-id ba6f29c-round5-corrected-stage3` | 0 | 9.368 | [corrected_assays1234_stage3](../build_m2b1_pr2/round5/logs/corrected_assays1234_stage3.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_assay.cpp -o R/corrected_final_assay` | 0 | 20.579 | [corrected_stage4_rebuild](../build_m2b1_pr2/round5/logs/corrected_stage4_rebuild.log) |
| `nice -n 19 R/corrected_final_assay --check-all --manifest R/corrected_final_check_all.json --build-id ba6f29c-round5-corrected-stage4` | 0 | 7.622 | [corrected_final_check_all](../build_m2b1_pr2/round5/logs/corrected_final_check_all.log) |
| `nice -n 19 python3 R/corrected_freeze.py` | 0 | 58.150 | [corrected_gate04_freeze](../build_m2b1_pr2/round5/logs/corrected_gate04_freeze.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_fixture.cpp -o R/corrected_hydro` | 0 | 10.751 | [corrected_gate05_hydro_native_build](../build_m2b1_pr2/round5/logs/corrected_gate05_hydro_native_build.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sNODERAWFS=1 -sEXIT_RUNTIME=1 tools/ocean_hydro_fixture.cpp -o R/corrected_hydro.js` | 0 | 8.672 | [corrected_gate05_hydro_wasm_build](../build_m2b1_pr2/round5/logs/corrected_gate05_hydro_wasm_build.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sNODERAWFS=1 -sEXIT_RUNTIME=1 tools/ocean_hydro_assay.cpp -o R/corrected_final_assay.js` | 0 | 18.866 | [corrected_gate05_assay_wasm_build](../build_m2b1_pr2/round5/logs/corrected_gate05_assay_wasm_build.log) |
| `nice -n 19 node R/corrected_final_assay.js --check-all --manifest R/corrected_final_wasm_check_all.json --target wasm` | 0 | 9.034 | [corrected_final_wasm_check_all](../build_m2b1_pr2/round5/logs/corrected_final_wasm_check_all.log) |
| `nice -n 19 python3 R/corrected_fixture_gate.py` | 1 | 47.774 | [corrected_gate05_fixtures](../build_m2b1_pr2/round5/logs/corrected_gate05_fixtures.log) |
| `nice -n 19 bash -c 'R/corrected_final_assay --fixture > R/corrected_step_probe.native.json'` | 0 | 11.596 | [corrected_gate05_native_diagnostic](../build_m2b1_pr2/round5/logs/corrected_gate05_native_diagnostic.log) |
| `nice -n 19 bash -c 'node R/corrected_final_assay.js --fixture > R/corrected_step_probe.wasm.json'` | 0 | 14.618 | [corrected_gate05_wasm_diagnostic](../build_m2b1_pr2/round5/logs/corrected_gate05_wasm_diagnostic.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tests/ocean_tests.cpp -o R/precision_tests` | 0 | 110.208 | [precision_gate02_build](../build_m2b1_pr2/round5/logs/precision_gate02_build.log) |
| `nice -n 19 R/precision_tests --only hydro` | 0 | 1.971 | [precision_gate02_hydro](../build_m2b1_pr2/round5/logs/precision_gate02_hydro.log) |
| `nice -n 19 R/precision_tests --only hydro_step` | 0 | 3.173 | [precision_gate02_hydro_step](../build_m2b1_pr2/round5/logs/precision_gate02_hydro_step.log) |
| `nice -n 19 g++ -O1 -g0 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -fsanitize=undefined -fno-sanitize-recover=all tests/ocean_tests.cpp -o R/precision_tests_ubsan` | 0 | 57.013 | [precision_gate02_ubsan_build](../build_m2b1_pr2/round5/logs/precision_gate02_ubsan_build.log) |
| `nice -n 19 R/precision_tests_ubsan --only hydro` | 0 | 3.183 | [precision_gate02_ubsan_hydro](../build_m2b1_pr2/round5/logs/precision_gate02_ubsan_hydro.log) |
| `nice -n 19 R/precision_tests_ubsan --only hydro_step` | 0 | 8.445 | [precision_gate02_ubsan_hydro_step](../build_m2b1_pr2/round5/logs/precision_gate02_ubsan_hydro_step.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_reference.cpp -o R/precision_reference` | 0 | 16.893 | [precision_gate03_build](../build_m2b1_pr2/round5/logs/precision_gate03_build.log) |
| `nice -n 19 R/precision_reference` | 0 | 0.396 | [precision_gate03_reference](../build_m2b1_pr2/round5/logs/precision_gate03_reference.log) |
| `nice -n 19 bash tests/ocean_hydro_measurements.sh` | 0 | 5.547 | [precision_measurement_units](../build_m2b1_pr2/round5/logs/precision_measurement_units.log) |
| `nice -n 19 python3 R/precision_gates23.py` | 0 | 207.374 | [precision_gates23](../build_m2b1_pr2/round5/logs/precision_gates23.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_assay.cpp -o R/precision_stage3` | 0 | 20.411 | [precision_stage3_build](../build_m2b1_pr2/round5/logs/precision_stage3_build.log) |
| `nice -n 19 R/precision_stage3 --assay 4 --trace R/precision_assays1234.stage3.csv --manifest R/precision_assays1234.stage3.json --emit-calibration R/precision_stage4.hpp --build-id ba6f29c-round5-precision-stage3` | 0 | 9.378 | [precision_assays1234_stage3](../build_m2b1_pr2/round5/logs/precision_assays1234_stage3.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_assay.cpp -o R/precision_final_assay` | 0 | 20.631 | [precision_stage4_rebuild](../build_m2b1_pr2/round5/logs/precision_stage4_rebuild.log) |
| `nice -n 19 R/precision_final_assay --check-all --manifest R/precision_final_check_all.json --build-id ba6f29c-round5-precision-stage4` | 0 | 7.532 | [precision_final_check_all](../build_m2b1_pr2/round5/logs/precision_final_check_all.log) |
| `nice -n 19 python3 R/precision_freeze.py` | 0 | 58.225 | [precision_gate04_freeze](../build_m2b1_pr2/round5/logs/precision_gate04_freeze.log) |
| `nice -n 19 env HYDRO_ACCOUNTING_OUT=R/precision_faults bash tests/ocean_hydro_accounting.sh` | 0 | 177.184 | [precision_final_e2e_faults](../build_m2b1_pr2/round5/logs/precision_final_e2e_faults.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_fixture.cpp -o R/corrected_hydro` | 0 | 10.717 | [gate05_retry2_hydro_native_build](../build_m2b1_pr2/round5/logs/gate05_retry2_hydro_native_build.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sNODERAWFS=1 -sEXIT_RUNTIME=1 tools/ocean_hydro_fixture.cpp -o R/corrected_hydro.js` | 0 | 8.343 | [gate05_retry2_hydro_wasm_build](../build_m2b1_pr2/round5/logs/gate05_retry2_hydro_wasm_build.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sNODERAWFS=1 -sEXIT_RUNTIME=1 tools/ocean_hydro_assay.cpp -o R/precision_final_assay.js` | 0 | 18.955 | [gate05_retry2_assay_wasm_build](../build_m2b1_pr2/round5/logs/gate05_retry2_assay_wasm_build.log) |
| `nice -n 19 node R/precision_final_assay.js --check-all --manifest R/precision_final_wasm_check_all.json --target wasm` | 0 | 9.105 | [precision_final_wasm_check_all](../build_m2b1_pr2/round5/logs/precision_final_wasm_check_all.log) |
| `nice -n 19 R/precision_faults/conversion_minus --check-all --manifest R/precision_final_fault_conversion_minus.json` | 1 | 7.643 | [precision_final_fault_conversion_minus](../build_m2b1_pr2/round5/logs/precision_final_fault_conversion_minus.log) |
| `nice -n 19 R/precision_faults/conversion_plus --check-all --manifest R/precision_final_fault_conversion_plus.json` | 1 | 7.662 | [precision_final_fault_conversion_plus](../build_m2b1_pr2/round5/logs/precision_final_fault_conversion_plus.log) |
| `nice -n 19 R/precision_faults/free_low --check-all --manifest R/precision_final_fault_free_low.json` | 1 | 7.623 | [precision_final_fault_free_low](../build_m2b1_pr2/round5/logs/precision_final_fault_free_low.log) |
| `nice -n 19 R/precision_faults/free_high --check-all --manifest R/precision_final_fault_free_high.json` | 1 | 7.616 | [precision_final_fault_free_high](../build_m2b1_pr2/round5/logs/precision_final_fault_free_high.log) |
| `nice -n 19 R/precision_faults/in_band_undercharge --check-all --manifest R/precision_final_fault_in_band_undercharge.json` | 1 | 7.583 | [precision_final_fault_in_band_undercharge](../build_m2b1_pr2/round5/logs/precision_final_fault_in_band_undercharge.log) |
| `nice -n 19 python3 R/fixture_gate_retry2.py` | 0 | 161.734 | [gate05_retry2_fixtures](../build_m2b1_pr2/round5/logs/gate05_retry2_fixtures.log) |
| `nice -n 19 python3 R/precision_finish.py` | 0 | 397.344 | [precision_final_pipeline](../build_m2b1_pr2/round5/logs/precision_final_pipeline.log) |
| `nice -n 19 env -u FAST -u ONLY -u NO_TESTS -u NO_EYE APP_TWINS=all JOBS=2 BUILD_JOBS=2 KEEP_OUT=1 OCEAN_PARITY_DIR=R/full_ocean_parity bash wasm/ocean_parity.sh` | 0 | 2532.897 | [gate06_full_ocean_parity](../build_m2b1_pr2/round5/logs/gate06_full_ocean_parity.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -pthread tools/ocean_eye_bench.cpp -o R/bench_plain` | 0 | 31.270 | [gate07_build_native_plain](../build_m2b1_pr2/round5/logs/gate07_build_native_plain.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sEXIT_RUNTIME=1 -sSTACK_SIZE=8388608 tools/ocean_eye_bench.cpp -o R/bench_plain.js` | 1 | 15.291 | [gate07_build_wasm_plain](../build_m2b1_pr2/round5/logs/gate07_build_wasm_plain.log) |
| `nice -n 19 python3 R/gate07.py` | 1 | 46.725 | [gate07_components](../build_m2b1_pr2/round5/logs/gate07_components.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -pthread tools/ocean_eye_bench.cpp -o R/bench_plain` | 0 | 30.614 | [gate07_retry1_build_native_plain](../build_m2b1_pr2/round5/logs/gate07_retry1_build_native_plain.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sEXIT_RUNTIME=1 -sSTACK_SIZE=8388608 tools/ocean_eye_bench.cpp -o R/bench_plain.js` | 1 | 5.739 | [gate07_retry1_build_wasm_plain](../build_m2b1_pr2/round5/logs/gate07_retry1_build_wasm_plain.log) |
| `nice -n 19 python3 R/gate07_retry1.py` | 1 | 36.508 | [gate07_components_retry1](../build_m2b1_pr2/round5/logs/gate07_components_retry1.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -pthread tools/ocean_eye_bench.cpp -o R/bench_plain` | 0 | 30.374 | [gate07_retry2_build_native_plain](../build_m2b1_pr2/round5/logs/gate07_retry2_build_native_plain.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sEXIT_RUNTIME=1 -sSTACK_SIZE=8388608 tools/ocean_eye_bench.cpp -o R/bench_plain.js` | 0 | 23.774 | [gate07_retry2_build_wasm_plain](../build_m2b1_pr2/round5/logs/gate07_retry2_build_wasm_plain.log) |
| `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -DEVO_OCEAN_EYE -pthread tools/ocean_eye_bench.cpp -o R/bench_eye` | 0 | 33.766 | [gate07_retry2_build_native_eye](../build_m2b1_pr2/round5/logs/gate07_retry2_build_native_eye.log) |
| `nice -n 19 em++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src -DEVO_OCEAN_EYE -msimd128 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=node -sEXIT_RUNTIME=1 -sSTACK_SIZE=8388608 tools/ocean_eye_bench.cpp -o R/bench_eye.js` | 0 | 27.898 | [gate07_retry2_build_wasm_eye](../build_m2b1_pr2/round5/logs/gate07_retry2_build_wasm_eye.log) |
| `nice -n 19 R/bench_plain --mechanics-components` | 2 | 32.800 | [gate07_retry2_timing_native_plain](../build_m2b1_pr2/round5/logs/gate07_retry2_timing_native_plain.log) |
| `nice -n 19 python3 R/gate07_retry2.py` | 2 | 148.920 | [gate07_components_retry2](../build_m2b1_pr2/round5/logs/gate07_components_retry2.log) |
| `nice -n 19 python3 R/gate12_audit.py` | 0 | 5.974 | [stop_scope_audit](../build_m2b1_pr2/round5/logs/stop_scope_audit.log) |

`gate06_full_ocean_parity`:

```text
== E1 preset: the harness's copy == kE1PresetJson
== Big tank preset: the harness's copy == web/ocean_config.js BIG_TANK
== int keys: kSimConfigIntKeys == checkpoint::readConfig's intOr keys (16)
== bool keys: kSimConfigBoolKeys == readConfig's boolOr keys (10), kOceanBoolKeys == readOceanConfig's readBool keys (8)
== non-finite state removed within a step: 2 of 2 nf_* runs caught, native and wasm (--unchecked)
== live refusals through the harness's --set: 26 of 26 r_live_* refused by both drivers, the state untouched
== running 124 case(s), 2 at a time (native and wasm side by side) in /home/harit/finfolk/work/trees/m2b1-pr2/build_m2b1_pr2/round5/full_ocean_parity
== appearance is cosmetic: 124 of 124 case(s) with appearance off == with it on minus its app* fields (every section, all, chain, counters, final line)
== the body-plan preview is diagnostic: 22 of 22 case(s) with it on: native == wasm (body sections included), and minus their body* fields == the case (every section, all, chain, counters, final line)
== body-plan fixture: native == wasm == tests/fixtures/ocean_body_fixture.json (ocean_body_fixture: 127 bodies, 572 samples, digest b9f6510154e9b597)
== birth-physics fixture: native == wasm == tests/fixtures/ocean_hydro_fixture.json (ocean_hydro_fixture: 137 bodies, 916 + 240 + 76 B a fish, references 34f5953354409576, digest 055461f8a8792567)
== offline reference (tools/ocean_hydro_reference.cpp): ocean_hydro_reference: PASS
== hydro step fixture: native == wasm == committed
== hydro calibration fixture: native == wasm == committed
== unit checks (tests/ocean_tests.cpp), plain build, native
== unit checks, plain build, wasm (node)
== unit checks (tests/ocean_tests.cpp), eye build, native
== unit checks, eye build, wasm (node)
== 2533 s total
== ALL 124 OCEAN PARITY CASES PASS: native == wasm == baseline, bit for bit, every step; expectations met; unit checks pass in both builds
```

`gate07_retry2_timing_native_plain.log`:

```text
MEM_ALLOCATOR,all_six_column_requested_B=3528000,allocated_delta_B=3541728,overhead_B=13728,physics_ceiling_charges_all_six_overhead=true
MEM_COLUMN,name=coefficients,sizeof=916,size=2000,capacity=2000,capacity_B=1832000,allocator_usable_B=1834984,slack_B=2984
MEM_COLUMN,name=support,sizeof=240,size=2000,capacity=2000,capacity_B=480000,allocator_usable_B=483304,slack_B=3304
MEM_COLUMN,name=state,sizeof=76,size=2000,capacity=2000,capacity_B=152000,allocator_usable_B=155624,slack_B=3624
MEM_COLUMN,name=genes,sizeof=20,size=2000,capacity=2000,capacity_B=40000,allocator_usable_B=40008,slack_B=8
MEM_COLUMN,name=owner,sizeof=8,size=2000,capacity=2000,capacity_B=16000,allocator_usable_B=16008,slack_B=8
MEM_COLUMN,name=existing_Fish_excluded_from_physics_increment,sizeof=504,size=2000,capacity=2000,capacity_B=1008000,allocator_usable_B=1011688,slack_B=3688
MEM_TOTAL,live=2000,slots=2000,capacity_B=2520000,capacity_B_per_live=1260,capacity_B_per_slot=1260,allocator_usable_B=2529928,usable_B_per_live=1264.964,snapshot_plus_working_capacity_B=5040000,copy_reset_peak_usable_B=5059856,allocator_headers=reported_by_separate_allocator_probe,ceiling=1404
MEM_WORKSPACE,Loaded=520,LDL6=196,ActuatorPlan=324,ContactReceipt=5292,SubstepReceipt=5876,StepReceipt=11760,Diagnostics=1924,BirthCoefficients=904,Points=6864,Cells2=8960,Material=768,allocationScratch=1792,construction_stack=see_compiler_stack_usage_and_Wasm_stack_highwater,export_peak=one_diagnostic_and_one_serialized_record
```

The component evidence does not establish PR3's whole-world performance gate. H is internal complete mechanics/energy time; T is matched legacy whole-world time. R (actually removable legacy work) and L (remaining lifecycle/ownership increment) are unmeasured, so H−R+L and the remaining +448ns/fish-step allowance cannot be certified by subtracting profiled intervals.

Module SHA256 values (freshness and final audit status are recorded in gate logs):

| Module | SHA256 |
|---|---|
| `web/evo_boids.js` | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` |
| `web/evo_boids.wasm` | `c1fc4c7a87c6271a4240533fbc3e51400c8028f7a9ec12e976a537448203732b` |
| `web/evo_boids_mt.js` | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` |
| `web/evo_boids_mt.wasm` | `8c7f31ca638a041600bebbf70e12dbef3c2ced9f2004377b574198a247efe268` |
| `web/evo_ocean.js` | `77bd5db9cd78973b77921e67f4df946e50655eb3d0318b630231f4fa08d257e3` |
| `web/evo_ocean.wasm` | `6167f939264bc5ba0f74499ef3eb25bdf523321a13a015e775bd4bbecde58f77` |

Read-only stop-state scope audit (does not complete release gate 12): base unchanged; 5592 earlier evidence records retain size, SHA256 and nanosecond mtime, with zero mismatches. Protected paths, Classic bytes, world/config/checkpoint/fingerprint/rendering paths and historical baselines are unchanged. All generated calibration/fixture identities and changed files are recorded in [final_audit.json](../build_m2b1_pr2/round5/final_audit.json).

## PR3 obligations and proposed commit split

PR3 still owns production activation after action capture, lifecycle/ownership, births/deaths/reseeding/compaction, complete checkpoint/export/render validation, and population2000 whole-world native/Wasm measurement with paired median Wasm M2/legacy≤1.25. The current internal calibration is not a production model selector or a coexistence claim. The disclosed contact/attitude/depth/turn limitations remain follow-up work.

Proposed commits (coordinator writes them; no .git writes here):

1. **Add internal Ocean mechanics and fuel accounting.** `src/ocean/hydro_coefficients.hpp`, `src/ocean/hydro_contact.hpp`, `src/ocean/hydro_step.hpp`, `src/ocean/ocean_energy.hpp`, `tests/ocean_hydro_tests.hpp`, `tests/ocean_hydro_step_tests.hpp`, `tests/ocean_tests.cpp`.
2. **Freeze Ocean mechanics assays and deterministic fixtures.** Every remaining changed file: generated `src/ocean/hydro_calibration.hpp`; all `tools/ocean_hydro_*` files and `tools/ocean_eye_bench.cpp`; `tests/ocean_hydro_accounting.sh`, `tests/ocean_hydro_measurements.cpp`, `tests/ocean_hydro_measurements.sh`; `tests/fixtures/ocean_hydro_fixture.json`, `tests/fixtures/ocean_hydro_step_fixture.json`, `tests/fixtures/ocean_hydro_calibration.json`; `wasm/ocean_parity.sh`; `docs/m2b1_pr2.md`, the four `docs/_ref/*.md` files, `docs/m2b2_gate2_diag.md`, `docs/m2b2_gate4_diag.md`, `docs/m2b3_assay3_diag.md`, `docs/m2b3_assay3_diag2.md`. The final audit's changed-file inventory is authoritative. Scratch build outputs and raw evidence under build_m2b1_pr2 are not committed.

No module-artifact commit if all rebuilt bytes remain identical. Any unexplained module change blocks completion.

---

The complete prior report follows verbatim as historical evidence.

# M2b1 PR 2 — Round 4: stopped at assay 4; partial freeze through stage 3

**Incomplete; not ready as a completed PR.** Gates 1–3 pass. Assays 1→2→3 pass
127/127 before stage-3 emission and again after rebuilding the generated
`kFrozenThrough=3` header. The implemented assay 4 fails its separate `.60 E/s`
motor anchor: **.592894793954 E/s**. Total **1.49297714233 E/s** and debit
**179.157257080 E** pass their stated bounds; they do not waive the motor anchor.
The prescribed conversion still prices the restrained 82 reference at `.60`.
No stage-4 header, final frozen calibration/step fixture, or successful
`--check-all` was emitted. Gates 5–12 remain unrun after the stop, apart from the
explicitly identified stopped-state scope/preservation audit below.

## Round 4 — 2026-11-24 (owner decisions dated 2026-11-23)

### Owner decisions and acceptance amendments

The round-4 instruction says (quoted):

> **D-M2b1-3: release = D1 plus D2.**

> **D-M2b1-4: "radius near 31" is a NON-GATING design goal for PR 2.**

> **D-M2b1-5: the D5 geometry amendment, with both checks.**

> **D-M2b1-6: stage-3 authority guard** = patch 04, with its refusal checks and a no-change rerun.

> **D3 is NOT adopted.** The forward-thrust lines stay at the fin centroids, as the plan specifies. Diagnosis 2 shows assay 4's total and debit bounds pass without it.

> **Stage-3 candidate:** paired yaw gain 0x40400000 (3), tail yaw gain 0x3f83d70a (1.03), stiffening speed 0x42d80000 (108, unchanged).

> **Contact solver:** D-M2b1-2 remains in force; there is no solver change in this PR.

The exact adopted acceptance texts below come from diagnosis 2's
[“D1–D5 rewritten consistently”](m2b3_assay3_diag2.md), using its weaker D4
clarification elected by the owner. They are now installed verbatim next to the
amended assay-3 rows in both [plan](_ref/m2b1_pr2_plan_codex.md) and
[brief](_ref/m2b1_brief_codex.md). These are owner-authorized changes to acceptance,
not retrospective reinterpretations of round 3's failed manifests.

**D1:**

> For the righting release, set speed, yaw, dive and forward-bias requests to zero for 625 outer steps; preserve filtered tail state and keep the paid gas regulator and passive braking active. Roll/pitch must return within 1° of upright after those 10 s, including after the finite-120 burst.

**D2:**

> In addition to the command-release upright check, run a separate driven yaw-release diagnostic from the same post-turn state: set yaw, dive and forward-bias requests to zero, retain the pre-turn speed request, and use 82 after the finite-120 burst. Keep all filters, regulator, passive brake and fuel pricing unchanged. Compare signed roll and pitch after 625 outer steps with the same body's 60 s, metered-25 E, no-yaw/no-dive straight control at that retained request, after aligning horizontal headings. Require each angle within 1° of its matched control. Report the control's absolute roll/pitch, actual speed, depth, vertical velocity, gas expenditure and remaining settling separately. Passing this relative-trim diagnostic does not replace D1's absolute upright requirement or establish assay-4 acceptance.

**D4:**

> The 40/82/120 labels name pre-turn straight-speed requests, and 120 names a finite burst. Always report actual turn speed, recorded-position radius and sideslip. Radius near 31 is a non-gating design goal for PR 2; the neutral-82 numeric heading target remains 2.60±.15 rad/s. Large-slip, reduced-speed turns may satisfy that numeric target and are not evidence of the 82-speed/radius-31 goal. Preserve the selected release checks and D5's separately eligible geometry checks.

**D5:**

> Fit the horizontal circle radius from actual torus-unwrapped recorded positions using a measurement-only fit; never substitute a speed/rate prediction for the fitted radius. Independently unwrap horizontal velocity course and horizontal forward heading over the same fit samples. Report mean horizontal speed U, speed range divided by mean U, absolute unwrapped course rotation, mean course rate, mean heading rate, their difference, sideslip, and both predicted radii and relative errors for every turn.
>
> For every resolved turn with absolute unwrapped course rotation at least 5° and speed range at most 2% of mean U, require the fitted radius to agree with U/|mean course rate| within 5%, regardless of sideslip. This course-rate check exercises position-fit geometry independently of body heading.
>
> Apply the separate fitted-radius versus U/|mean heading rate| identity only when the same resolution/speed conditions hold, maximum absolute sideslip is below 5°, and |mean course rate−mean heading rate| is at most 2% of |mean heading rate|. Require agreement within 5%. Preserve the finite-120 burst window; do not replace it with steady swimming.
>
> Print each check's eligibility, exclusion reason and total eligible count. An ineligible check is not exercised, not passed. Report its measurements without asserting the identity. Zero steady low-slip eligible cases require explicit owner acceptance of that coverage or an additional fixed eligible fixture before stage-3 freezing. Include a planted radius-measurement fault rejected by the course check, while unchanged simulation traces prove that the fault and the measurement amendment do not alter mechanics.

**Stage-3 authority:**

> Stage 3 may change only kPairedYawGain, kTailYawGain and kTailStiffSpeed. kHeaveGain, kPitchGain and kPairedInducedEfficiency remain fixed by the declared law and are not stage-3 calibration variables. An emitter accepting an override does not grant tuning authority. Refuse both changed and no-op --set requests for those extra constants before opening the output header. Preserve emitted values, ordering, digests and frozen-through stage for an unchanged authorized candidate, and prove its rerun unchanged.

The coordinator's preparation instruction (quoted):

> PREPARATION: diagnosis 2 found that 60 s leaves vertical/regulator settling. Use a 600 s straight preparation at the same requests, disclose it, and measure the prescribed 120 s after it. The texts specify no preparation length, and this is the coordinator's choice.

The stop and authority instruction (quoted):

> The free-cruise motor came out at .5929 E/s with the restrained reference exactly .60. Try to meet the motor anchor using ONLY assay-4 constants. If that requires changing any stage-1/2 constant or the law, or the anchor has no tolerance you can justify from the texts, STOP and report it as an owner decision. Do NOT borrow the total tolerance for the motor component.

> STOP RULE: if an assay cannot meet its target without changing the law or an earlier freeze, stop and report the discrepancy (plan:1075). Do not stamp a frozen manifest.

### Base, prerequisites, preservation and scope

HEAD remains `ba6f29c6ee4a04b1ce41b27ab49e81443802968d`, branch `m2b1-pr2`.
Gate 1 rechecked all five fixed-PR-1 requirements: legal declared-field traversal;
finite/atomic inverse, scaled solve and load refusal; finite LDL factors;
independent double loaded/body/rotational construction; and tensor-block units.
No prerequisite was repaired. See [gate01_prerequisites.md](../build_m2b1_pr2/round4/gate01_prerequisites.md).

The starting header was stage 2. Patches 01, 02 and 04 were applied, followed by
exact-bit candidate emission and rebuild. Stage-3 emission changes only the stage
integer; stage-1/2 constants and measured power bits remain unchanged. D3 was not
applied. No changes were made to the mechanics/energy/contact kernels, independent
reference or existing unit-suite sources during this round. Their hashes match
the independently checked diagnosis-2 inventory of the preserved round-3 sources.

The stopped-state audit checked **5,494 pre-existing evidence files**, SHA256,
size and nanosecond mtime, with **zero mismatches**. Both diagnoses, all previous
raw runs and the previous report remain intact. The prior report is reproduced
verbatim after this section and is also saved under `round4/before/`. All new
scratch outputs are under `build_m2b1_pr2/round4/`. Git was read-only; nothing was
committed, fetched, downloaded, deployed, merged or rebaselined. Commands use
nice 19, at most two concurrent jobs, and at most two threads per job; native
executables here are serial. No browser or study workload was started.

### Constants and identities

The installed header is **partially frozen through 3**, not a final stage-4
calibration. All generated constants are binary32 bit literals:

| Constant | Binary32 value | Bits |
|---|---:|---|
| `kGravity` | 400 | `0x43c80000` |
| `kPressureDepthFraction` | 0.5 | `0x3f000000` |
| `kMetacentricFraction` | 2 | `0x40000000` |
| `kDepthGain` | 0.0799999982119 | `0x3da3d70a` |
| `kVerticalGain` | 0.20000000298 | `0x3e4ccccd` |
| `kRegulatorTau` | 2 | `0x40000000` |
| `kGasRateFraction` | 0.019999999553 | `0x3ca3d70a` |
| `kPumpEfficiency` | 0.25 | `0x3e800000` |
| `kStaticFriction` | 0.800000011921 | `0x3f4ccccd` |
| `kDynamicFriction` | 0.600000023842 | `0x3f19999a` |
| `kContactSlopPerSize` | 0.00499999988824 | `0x3ba3d70a` |
| `kPenetrationLimitPerSize` | 0.00999999977648 | `0x3c23d70a` |
| `kControllerTau` | 0.25 | `0x3e800000` |
| `kHeaveGain` | 1 | `0x3f800000` |
| `kPitchGain` | 1 | `0x3f800000` |
| `kPairedYawGain` | 3 | `0x40400000` |
| `kTailYawGain` | 1.02999997139 | `0x3f83d70a` |
| `kTailStiffSpeed` | 108 | `0x42d80000` |
| `kPairedInducedEfficiency` | 0.75 | `0x3f400000` |
| `kBrakeCd` | 1.10000002384 | `0x3f8ccccd` |
| `kMeasuredCruisePowerBits` (measured power) | 44590.3007812 | `0x472e2e4d` |
| `kMeasuredSustainedPowerBits` (measured power) | 86410.53125 | `0x47a8c544` |

Unchanged anchors: Uref=82 (`0x42a40000`), Usus=108 (`0x42d80000`),
Uact=150 (`0x43160000`), rowing efficiency=.35 (`0x3eb33333`), tauBurst=2
(`0x40000000`), gamma=.5 (`0x3f000000`), maintenance fin/wall/lipid=.04/.04/.02
(`0x3d23d70a`/`0x3d23d70a`/`0x3ca3d70a`). The .75 induced efficiency is fixed
by the declared law and is not a stage-3 tuning variable; this corrects the
older report's authority wording. It remains distinct from rowing and tail
efficiency. Work conversion is `1.3455841326504014e-5`, bits `0x3761c066`.

The accepted stage-1 fraction=2 restoring constant remains about 16.7× its starting
value, with neutral lever about 8.07 u; no invented geometric cap was added.
The floor-force wrench remains sampled at COM's floor projection once per outer
step and held in body coordinates across both substeps. This is not continuous
world-frame force application. D-M2b1-1 and D-M2b1-2 remain as quoted in round 3.

| Compiled evidence | Constants digest | Reference digest | Freeze |
|---|---|---|---:|
| Guard/candidate | `66b5b28e6e06a84d` | `34f5953354409576` | 2 |
| Rebuilt stage 3 and failed assay 4 | `898434f17b29f8a0` | `34f5953354409576` | 3 |

Laws are geometry/material/expression/reference/mechanics/energy = **1/1/1/2/1/1**;
coefficient/support/state ABIs **1/1/1**. Neutral coefficient digest
`3e8bfae4938384af`, support `44931eb40f7ec2ef`; initial reference gas
42.48379135131836, E=25, torus 1920×1080×240, target depth 120.

Generated stage-2 candidate SHA256:
`b49140bc2ccd5099d7034f0592c24531dd384b10066efa6503a3ed5c96c91388`.
Installed/generated stage-3 header SHA256:
`3fc8d837c7d2ecebc63b6a139d797218ae6aac713f64373172df1b91dea1a11f`.
Full manifest/trace/source identities are in [final_audit.json](../build_m2b1_pr2/round4/final_audit.json).

### Gates 2–3 and authority regression

Optimized and separate UBSan runs each pass **11 hydro + 12 hydro-step groups**;
their respective printed outputs match byte for byte. The 40,000-substep chain is
`d5f0227c843e77c7`; sampled 85-body chain `facfefda729cec0c`. These were rebuilt
with the candidate at stage 2; the later stage-only freeze changes digest-bearing
chains, not physical arithmetic.

The independent reference passes all unchanged tolerances: 11,508 independent
one-step increments, worst **3.46788345e-6**; residual **3.94250924e-7**;
5,754 force/location/power/gas checks, worst **1.27231878e-5**, against **2e-5**.
Nine fixed-load trajectories finish without internal error. Sequential-patch
model differences remain reported comparisons, without a new percentage gate.

Patch 04 rejects changed and no-op overrides for `kHeaveGain`, `kPitchGain` and
`kPairedInducedEfficiency`: all six exit 2 before creating an output header.
No-override and exact authorized no-op emissions reproduce the stage-2 candidate
byte for byte. The guard rerun passes **97/97**, reproducing diagnosis 2's
**116,066 rows / 31,077,176 bytes** exactly, SHA256
`caf03f2ffb977f97f7b38b004ebfac6ad1cdd8d4f2bf46a578d2ee74fd230a52`.
See [guard_cli.json](../build_m2b1_pr2/round4/guard_cli.json), [guard_verified.json](../build_m2b1_pr2/round4/guard_verified.json).

### Assays 1–2 retained; assay 3 implemented and frozen

Each cumulative candidate/rebuilt run retains the **33 assay-1 + 32 assay-2**
predicates, their values and physical trace rows. Every reference-load incoming
substep has exactly 25 E through metered reserve transactions, with subsidy,
actual debit, pump work and chained receipts recorded. Assay 2 still measures
44590.30078125 / 86410.53125 at 82/108 and retains the 150-anchored force ceiling
648.991821289. No measured reference, actuator capacity or earlier constant was
re-anchored.

Assay 3 adds 62 predicates, including metering/completion checks for the new
windows, D1 signed roll/pitch, D2 relative signed roll/pitch, D5 and explicit
low-slip coverage. **127/127** pass before stage-3 emission; the emitter reruns
1→2→3 before writing stage 3; its rebuild again passes **127/127**. The stage-2
and rebuilt-stage-3 state/ledger traces are **144,816 rows**, byte-identical,
SHA256 `31f4780151158f79b94432b023f0839edbe98fd6598e3f52779a8c2521e888ab`.
Receipt chains correctly change because they include the frozen-stage constant
digest. See [stage2_verified.json](../build_m2b1_pr2/round4/stage2_verified.json), [stage3_verified.json](../build_m2b1_pr2/round4/stage3_verified.json).

D4 measurements below use the original five windows: 60 s straight preparation,
625 outer-step turn, fit [500,625) at 40/82; recovered kinematic 120 initialization,
62-step (.992 s) finite turn, fit [31,62) at 120. Labels are **pre-turn requests**.
The heading target uses the recorded horizontal heading derivative; D5 separately
uses independently unwrapped heading/course over the fit samples. No radius is
substituted from a prediction.

| Body / request | Actual horizontal speed | Heading rad/s | Fitted radius | Slip mean / max ° | Min lambda | End fatigue |
|---|---:|---:|---:|---|---:|---:|
| neutral / 40 | 12.787075 | 4.37413202 | 2.92379611 | 85.9069318 / 85.9100767 | 0.284736186 | 172821.062 |
| neutral / 82 | 37.2461383 | 2.59936243 | 14.3291649 | 53.0955781 / 53.1062811 | 0.239714622 | 172821.062 |
| neutral / 120 | 98.7000183 | 1.13490328 | 93.2509962 | 21.165774 / 22.0374082 | 0.460642606 | 85719.2188 |
| manoeuvrer / 40 | 13.3281023 | 5.3835409 | 2.47651551 | 96.7150178 / 96.7529765 | 0.197991461 | 202085.656 |
| cruiser / 40 | 25.3947175 | 2.00120576 | 12.6893412 | 48.4662309 / 48.4775008 | 0.34499386 | 158881.656 |

Neutral 82's **37.246138 u/s**, **14.329165 u radius** and **53.106281° max slip**
are not evidence of the 82-speed/radius-31 design goal. Large-slip, reduced-speed
turns satisfy this PR-2 numeric heading target under the owner's weaker D4 scope.
The 40-speed radius ordering passes; cruiser/manoeuvrer ratio is **5.123869033**.
All measured total angular speeds stay below configured and absolute 12 rad/s
rails; maximum across the original turns is **7.342400551 rad/s**. Finite-120
speed variation and fatigue are retained, not replaced by steady swimming.

D1 clears speed/yaw/dive/forward bias on a copy of the post-turn state; D2 starts
from a separate copy of that same state, retaining speed (82 after finite 120).
Neither clears filters, regulator, braking or pricing. Signed bank/pitch computed
relative to the horizon are invariant under horizontal-heading alignment; the
independent signed-angle tests exercise this explicitly. D1 checks each angle
against upright; D2 checks each against its matched 60 s control.

| Case | D1 roll / pitch ° at 10 s | D2 roll / pitch absolute errors ° | Control absolute roll / pitch ° |
|---|---|---|---|
| steer_neutral_40 | -1.36603767e-05 / -0.0194135251 | 1.02454474e-05 / 0.0032796097 | 0 / 0.320704455 |
| steer_neutral_82 | 0 / 0.00177926431 | 1.70803529e-05 / 0.00556563511 | 1.02482518e-05 / 1.37901424 |
| steer_neutral_120 | 1.36603767e-05 / 0.0020114902 | 1.02482518e-05 / 0.0199643173 | 1.02482518e-05 / 1.37901424 |
| steer_manoeuvrer_40 | -0.000505433999 / -0.00456427399 | 2.40078225e-05 / 0.00995649608 | 0 / 5.29759177 |
| steer_cruiser_40 | -0.00199441547 / -0.0328651614 | 2.39056621e-05 / 0.0775483622 | 0 / 0.0977742597 |

Every D1/D2 angle meets its own unchanged 1° bound. D2 does not establish upright
driven trim: the manoeuvrer control remains about **5.29759°** pitch. Control
state and remaining settling are disclosed separately below. Gas expenditure is
actual allocated paid pump fuel over the control preparation; remaining gas rate
is an end-state load-25 evaluation, not an assertion of equilibrium.

| Control | Actual horizontal speed | Depth | Vertical velocity | Paid gas E / 60 s | End requested gas rate |
|---|---:|---:|---:|---:|---:|
| steer_neutral_40 | 40.0000877 | 117.436638 | 0.000288722222 | 0.0124936136 | 3.43322754e-05 |
| steer_neutral_82 | 82.0046616 | 87.8008652 | 0.0776311681 | 0.0739278199 | -0.0299091339 |
| steer_neutral_120 | 82.0046616 | 87.8008652 | 0.0776311681 | 0.0739278199 | -0.0299091339 |
| steer_manoeuvrer_40 | 40.1613884 | 88.491066 | 0.105670139 | 0.085945681 | -0.0506000519 |
| steer_cruiser_40 | 39.9999962 | 119.078651 | -0.00036419899 | 0.00471335723 | 0.00023651123 |

The neutral-82 and manoeuvrer controls still have .0776/.1057 u/s upward motion;
60 s is not exact regulator/vertical settling. This is why assay 4 uses the
separately authorized longer preparation.

### D5 eligibility, independent fit and planted faults

Every turn prints actual mean U, speed range/mean U, absolute course rotation,
independently unwrapped course/heading rates and difference, slip, fitted radius,
both predictions/errors, eligibility and exclusion reasons. The 5° resolution,
2% speed/rate eligibility, 5° slip and 5% radius tolerances are unchanged from the
owner's amendment. Ineligible means **not exercised**, never a passing predicate.

| Turn | Course arc ° | Speed range / U | Course eligible | Heading eligible | Course fit error | Heading fit error |
|---|---:|---:|---|---|---:|---:|
| steer_neutral_40 | 499.178262 | 2.35625982e-05 | yes | no | 4.50106764e-05 | 5.02743569e-05 |
| steer_neutral_82 | 296.679927 | 0.000495736817 | yes | no | 3.63968407e-05 | 2.54804285e-05 |
| steer_neutral_120 | 29.2146858 | 0.0568487133 | no | no | 0.0128230841 | 0.072579291 |
| steer_manoeuvrer_40 | 614.281252 | 0.000613486807 | yes | no | 6.44970971e-05 | 0.000107978628 |
| steer_cruiser_40 | 228.412694 | 8.83080335e-05 | yes | no | 9.06315469e-06 | 5.04727557e-05 |
| geometry_low_slip_turn | 21.6851314 | 8.01220258e-07 | yes | yes | 1.24599284e-05 | 1.15491942e-05 |

Original five: **4 course / 0 heading eligible**; the heading identity is **not
exercised** there. Finite-120 is excluded by its 5.68487% speed range, while the
other four are excluded from the heading check by sideslip.

Before calibration acceptance, an additional fixed fixture was declared in the
source: neutral body, request 40, yaw `.01f` (`0x3c23d70a`), 60 s straight
preparation, 60 s turn, last 10 s ([3125,3750)) fit. It resolves **21.68513°** of
course, speed range **8.0122e-7**, and max slip **4.003667°**. Both checks are
eligible and pass: fitted radius **1058.060721**, course prediction **1058.047538**,
heading prediction **1058.048502**. Full assay counts are therefore **5 course /
1 heading**, avoiding an unapproved zero-coverage stage-3 freeze. This extra
fixture does not replace the finite-120 window or demonstrate radius near 31.

`bash tests/ocean_hydro_measurements.sh` passes 13 analytic/signed-angle checks
and verifies an intentionally failing 1.25× radius fit. It covers resolved arcs,
clockwise/wrapped angles, transient-speed and unresolved arcs, high slip, and a
small-slip rate-mismatch exclusion. The fault changes only returned fit radii:
resolved checks fail while transient/unresolved exclusions stay not exercised.

In the real assay driver the planted fault fails all **six** exercised radius
checks (five course, one heading), about **25.00%** error, exit **1**; it emits no
header. All physical rows and receipt chains remain identical to the good run.
All **31** prior simulation cases also match the preserved guard trace exactly,
proving that D2's extra windows and D5's measurement code do not change those
mechanics. See [stage2_verified.json](../build_m2b1_pr2/round4/stage2_verified.json).

### D4 partial-yaw disclosure retained from diagnosis 2

The following requested partial-yaw table and six local reversals are reproduced
from the independently checked [diagnosis 2](m2b3_assay3_diag2.md), with its original
[partial data](../build_m2b1_pr2/diag4/partial_summary.json) and
[dense reversals](../build_m2b1_pr2/diag4/dense_reversals.json) left in place.
They were not rerun as new round-4 acceptance counts. Each group starts from its
same cloned preparation; 40/82 fit [500,625), finite 120 fits [31,62).

| Body | Request | Yaw | Heading rad/s | Actual horizontal u/s | Radius u | Slip mean/max ° | Lambda min | Course-radius error % / eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| neutral | 40 | 0.25 | 2.396317063 | 39.177561 | 16.350003 | 50.1882/50.1894 | 1.000000 | 0.001533 / yes |
| neutral | 40 | 0.50 | 3.481218697 | 23.862531 | 6.855506 | 69.0150/69.0202 | 0.496219 | 0.003880 / yes |
| neutral | 40 | 0.75 | 4.050081868 | 16.547482 | 4.086185 | 79.3804/79.3851 | 0.356483 | 0.001171 / yes |
| neutral | 82 | 0.25 | 0.685527472 | 83.040438 | 121.135086 | 17.6796/17.6797 | 1.000000 | 0.000358 / yes |
| neutral | 82 | 0.50 | 0.984146633 | 70.089805 | 71.220641 | 23.9683/23.9689 | 0.499241 | 0.000707 / yes |
| neutral | 82 | 0.75 | 1.484097134 | 58.579406 | 39.472104 | 32.9576/32.9578 | 0.330314 | 0.000499 / yes |
| neutral | 120 | 0.25 | 0.330040475 | 120.419379 | 390.290135 | 8.5293/8.7017 | 1.000000 | 0.846489 / yes |
| neutral | 120 | 0.50 | 0.608238652 | 111.747392 | 191.842322 | 13.5955/13.8186 | 0.706451 | 0.920893 / yes |
| neutral | 120 | 0.75 | 0.873948861 | 104.657445 | 126.244041 | 17.6004/18.0581 | 0.554668 | 1.138064 / no |
| manoeuvrer | 40 | 0.25 | 0.985901320 | 42.027354 | 42.632842 | 42.7711/42.7741 | 0.599987 | 0.000783 / yes |
| manoeuvrer | 40 | 0.50 | 1.994631332 | 36.439919 | 18.270007 | 61.2163/61.2167 | 0.344173 | 0.000539 / yes |
| manoeuvrer | 40 | 0.75 | 4.560951917 | 18.559303 | 4.070384 | 89.2604/89.3022 | 0.243952 | 0.004132 / yes |
| manoeuvrer | 82 | 0.25 | 0.268031210 | 44.808943 | 167.243616 | 21.6929/21.6976 | 0.326450 | 0.001434 / yes |
| manoeuvrer | 82 | 0.50 | 0.679955531 | 43.355672 | 63.776967 | 35.3546/35.3618 | 0.265170 | 0.002470 / yes |
| manoeuvrer | 82 | 0.75 | 1.143097505 | 41.424771 | 36.244746 | 46.1408/46.1482 | 0.222388 | 0.000936 / yes |
| manoeuvrer | 120 | 0.25 | 0.456787332 | 58.979538 | 142.756652 | 23.3005/23.6383 | 0.300726 | 2.036086 / yes |
| manoeuvrer | 120 | 0.50 | 1.084241443 | 56.850542 | 55.088144 | 37.4933/37.9054 | 0.239883 | 1.305917 / yes |
| manoeuvrer | 120 | 0.75 | 1.744008943 | 54.080986 | 32.708801 | 48.2020/48.6729 | 0.199517 | 1.356316 / yes |
| cruiser | 40 | 0.25 | 1.135410197 | 40.185589 | 35.390227 | 28.9457/28.9492 | 1.000000 | 0.001154 / yes |
| cruiser | 40 | 0.50 | 1.732622132 | 36.002139 | 20.767840 | 38.2790/38.2928 | 0.718732 | 0.059786 / yes |
| cruiser | 40 | 0.75 | 1.879769579 | 30.228251 | 16.080312 | 43.3494/43.3578 | 0.454519 | 0.000473 / yes |
| cruiser | 82 | 0.25 | 0.460318412 | 82.074030 | 178.274693 | 10.7608/10.7618 | 1.000000 | 0.000376 / yes |
| cruiser | 82 | 0.50 | 0.731370132 | 76.831769 | 105.013108 | 15.3101/15.3125 | 0.668475 | 0.009143 / yes |
| cruiser | 82 | 0.75 | 0.861258862 | 70.355771 | 81.681728 | 17.8992/17.9037 | 0.444952 | 0.000387 / yes |
| cruiser | 120 | 0.25 | 0.234481635 | 119.933088 | 662.333417 | 4.1472/4.7911 | 1.000000 | 1.914819 / no |
| cruiser | 120 | 0.50 | 0.502137234 | 119.581063 | 290.845077 | 7.8044/8.9093 | 1.000000 | 1.905554 / yes |
| cruiser | 120 | 0.75 | 0.705650380 | 117.386309 | 189.815370 | 10.6077/11.5706 | 0.828108 | 1.657346 / no |

All nine groups are ordered at **0, .25, .5, .75, 1**. That is a spot-check result, not global monotonicity or smoothness. The **369-turn sweep** uses commands 0…1 in increments .025 (41 per body/request), with the same initial states/windows. It has no sampled reversals in the three finite-120 groups or manoeuvrer-82. The remaining five groups contain these six reversals:

| Body / request | Command increase | Heading before→after rad/s |
|---|---|---:|
| neutral / 40 | 0.300→0.325 | 2.966215208→2.799334538 |
| neutral / 82 | 0.275→0.300 | 0.780272522→0.669082359 |
| manoeuvrer / 40 | 0.150→0.175 | 0.708770534→0.705377354 |
| cruiser / 40 | 0.450→0.475 | 1.882826193→1.714816217 |
| cruiser / 82 | 0.400→0.425 | 0.804302915→0.721204902 |
| cruiser / 82 | 0.425→0.450 | 0.721204902→0.703725326 |

A targeted native replay of all 11 distinct commands continues the turns to 60 s and compares **[8,10)** with **[58,60)**. Every listed reversed pair becomes ordered in the latter window. For example neutral-40 .300/.325 changes from **2.966215/2.799335** to **2.686450/2.798516 rad/s**; fatigue exhausts at **11.456/7.336 s**. Neutral-82 .275/.300 exhausts at **9.968/7.360 s**. Cruiser-82 .400/.425/.450 exhausts at **11.096/8.376/6.768 s**, and its late heading rates are **.677345/.691172/.704900**. This directly links the observed finite-window reversals to different positions in the burst-to-sustained transition. It does not change or erase the required early-window results, prove monotonicity everywhere after settling, or prove a mathematical discontinuity in the actuator law. Speed loss, slip and lambda remain strongly nonlinear. The maximum sampled local heading increment is about **.45564 rad/s for .025 command**, manoeuvrer-40 .600→.625; a blanket smooth-response claim is unwarranted.

These are disclosed behaviour, not a gate: ordered quarter-command samples do
not establish global command monotonicity or smooth steering. The six reversals
are near fatigue exhaustion in the specified finite measurement window; the
later replay does not erase the early-window results.

### Assay 4: measured failure and authority-limited stop

The real driver now implements assay 4 after cumulative 1→2→3. It ran a
**37,500-outer-step / nominal 600 s** straight preparation at request 82, then a
fresh **7,500-outer-step / nominal 120 s** measurement with metered 25 E before
every mechanical substep, `geneCost=0`, yaw=dive=forwardBias=0, and no pose,
velocity, depth, regulator or gas clamp. Preparation subsidy **896.341341019 E**
and debit **896.353284836 E** are separate from cruise; the difference is the
boundary's outstanding last-substep debit. Cruise subsidy and actual debit are
both **179.157257080 E**. This is a funded test source, not ordinary no-food
survival on a 25 E reserve.

| Requirement | Measurement | Outcome |
|---|---:|---|
| 120 s, each incoming substep E=25 | 7,500 outer / 15,000 mechanical steps | Pass |
| Basal .80 E/s | .800000037998 | Binary32 roundoff only |
| Maintenance .10 E/s | .099999997474 | Binary32 roundoff only |
| **Motor .60 E/s** | **.592894793954** | **FAIL: −.007105206046 E/s, −1.184201%** |
| Total 1.50±.02 E/s | 1.49297714233 | Pass |
| Debit 180±2.4 E | 179.157257080 | Pass |
| geneCost / gene debit | 0 / 0 | Pass |
| Channel/pump price reconstruction | worst relative error 1.72480074e-8 | Pass at existing 2e-5 oracle tolerance |
| Every actual debit equals the prescribed rounded ledger subtraction | all 15,000 receipts | Pass |
| Unexplained control/contact/rail expenditure | no paired commands, control E=0, contact/rail count=0 | None identified |
| Cruise gas expenditure | .000019360999 E | Accounted within motor total |
| Additional turning work charged | 18.603639010 E motor / 10 s; 10.747664936 E control | Pass |
| Exact zero-motion blocked thrust charged | 18.598952563 E / 1,250 price evaluations / 10 s | Pass |
| 3× excess-power charge | error −6.585734319e-10 E/substep | Pass |
| Free recovery | motor fuel 0, fatigue decreases | Pass |

The cumulative run has **143/144 passing predicates**, with **only the motor
anchor failing**, raw exit **1**. Its preceding 127 results and trace prefix
match the rebuilt stage-3 run. The 34 simulation cases shared with diagnosis 2,
including warm/cruise/turn, match its physical trace rows exactly. The blocked
case starts from the static reference with zero initial filtered drive, so its
startup work differs slightly from diagnosis 2's initialized-drive price oracle;
pose/load/zero motion are held for every price evaluation, and filters/fatigue
advance. No outer-step-reset approximation substitutes for this block.

**No motor tolerance was borrowed or approved.** The failing
`motor_.60_roundoff_only` screen uses `8*float_epsilon*.60 = 5.72204589844e-7`
solely to distinguish arithmetic roundoff from a material mismatch; this is not
an owner-authorized model tolerance. The .007105 gap is far larger. The text
states no independent component tolerance that would justify accepting it.

Only maintenance allocation and work conversion are assay-4 authority. At the
fixed neutral incoming load, any allocation still satisfying maintenance .10
provides the same maintenance demand; it cannot relabel .007105 of maintenance
or total burn as motor. The accepted conversion formula is
`workConversion=.60/PmotorNeutral(82)`, and assay 2 froze its measured denominator
at **44590.30078125** (`0x472e2e4d`). Rechecking that restrained reference prices
it at **.60 E/s** with the unchanged conversion. There is no independently
authorized conversion multiplier in this formula.

A scalar sensitivity calculation on the measured free-cruise receipts requires
**1.01198392382×** conversion: approximately `1.36170947371e-5`
(`0x376474fa`) instead of `0x3761c066`. This would price the same restrained
reference at **.607190338 E/s** and violate the stated normalization. It is a
reported price calculation, not an installed candidate or a rerun claiming a
pass. Changing that formula, changing its frozen denominator, or accepting a
1.1842% motor deficit needs an **owner decision**. I stopped rather than silently
redefining the reference or component tolerance. No assay-4 constants were
installed and no earlier freeze was changed.

Settled state disclosures, without invented assay-4 numeric body/depth bounds:

- Mean body pitch **1.380749806°**, roll **.0000136643°**; horizontal speed
  **82.005950928**, body-forward **81.982170105**, body-vertical **−1.975693703**.
- Mean/max path climb **.000346618413 u/s**; integrated climb **.041594212 u**
  over 120 s, stored depth drift **0**. The path is essentially level after the
  longer preparation; the body is pitched and target-depth tracking is biased.
- Steady stored depth **86.139778137 u** versus target **120 u**, not 120.
  This is disclosed, not a newly invented numerical rejection or acceptance.
- Preparation gas content **42.483791→24.941935**, paid pump **.076767428 E**.
  During measurement the residual requested gas rate is **−.0000371932983/s**,
  lambda=1, and the tiny pump cost is included once in motor fuel. Depth/gas
  increments fall below half a binary32 ULP on the plateau; stored zero drift
  does not mean zero velocity or a free regulator.
- The sum of named requested basal/maintenance/motor debits is **.009877549 E**
  below actual ledger debit because of binary32 subtraction from 25 E. Every
  actual receipt is checked against that exact rounded subtraction. The
  printed `every_debit_matches_rounded_ledger` value is this explained cumulative
  rounding amount, not an error tested against its displayed zero sentinel.
  Total/debit gates use actual ledger debit.
- Diagnosis 2's balance explanation remains applicable to the identical cruise
  trace: tilted thrust, passive force coupling and regulator-created negative
  buoyancy balance; no unpriced trim-fin command is used. No D3 force-line
  change is needed for the stated total/debit bounds or adopted here.

The source has a genuine four-assay `--check-all` path, gated on compiled stage 4;
its positive execution is **not validated**. At stage 3 it correctly exits 2.
Fixture mode is still unimplemented/refused. The failed `--assay 4
--emit-calibration stage4.hpp` creates **no stage4.hpp** and leaves the generated
stage-3 header installed. See [stop_verified.json](../build_m2b1_pr2/round4/stop_verified.json), [assays1234.stage3.json](../build_m2b1_pr2/round4/assays1234.stage3.json).

### Gate table and command journal

Every recorded invocation below includes its exact argv, environment, UTC times,
raw exit, elapsed seconds and log in [commands.jsonl](../build_m2b1_pr2/round4/commands.jsonl). All commands
below begin with `nice -n 19`; `R` abbreviates `build_m2b1_pr2/round4` only in the
display. `guard_unchanged` is the required regression proof of the authority
patch, not a substituted final assay acceptance. Expected planted-fault exit 1
is retained as such.

| Recorded operation | Command | Exit | Seconds | Log |
|---|---|---:|---:|---|
| gate01_scope | `nice -n 19 git diff --exit-code ba6f29c -- src/core src/ocean/ocean_world.hpp src/ocean/ocean_config.hpp src/ocean/fish.hpp src/ocean/body_plan.hpp src/ocean/body_material.hpp src/ocean/hydro_math.hpp src/ocean/hydro_state.hpp wasm web tests/ocean_baseline tests/fixtures` | 0 | 0.008 | [log](../build_m2b1_pr2/round4/logs/gate01_scope.log) |
| gate01_identity_retry1 | `nice -n 19 python3 R/prepare.py` | 0 | 5.643 | [log](../build_m2b1_pr2/round4/logs/gate01_identity_retry1.log) |
| patch01 | `nice -n 19 patch -p1 -i build_m2b1_pr2/diag3/01_stage3_candidate.patch` | 2 | 0.005 | [log](../build_m2b1_pr2/round4/logs/patch01.log) |
| patch01_retry1 | `nice -n 19 patch -p1 -i build_m2b1_pr2/diag3/01_yaw_calibration_candidate.patch` | 0 | 0.021 | [log](../build_m2b1_pr2/round4/logs/patch01_retry1.log) |
| patch02 | `nice -n 19 patch -p1 -i build_m2b1_pr2/diag3/02_release_stimulus_OWNER_DECISION.patch` | 0 | 0.005 | [log](../build_m2b1_pr2/round4/logs/patch02.log) |
| patch04 | `nice -n 19 patch -p1 -i build_m2b1_pr2/diag4/04_stage3_authority_guard.patch` | 0 | 0.005 | [log](../build_m2b1_pr2/round4/logs/patch04.log) |
| guard_build | `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_assay.cpp -o R/guard` | 0 | 16.520 | [log](../build_m2b1_pr2/round4/logs/guard_build.log) |
| guard_cli | `nice -n 19 python3 R/check_guard.py` | 0 | 0.079 | [log](../build_m2b1_pr2/round4/logs/guard_cli.log) |
| guard_unchanged | `nice -n 19 R/guard --assay 3 --manifest R/guard_unchanged.json --trace R/guard_unchanged.csv --build-id round4-guard` | 0 | 4.452 | [log](../build_m2b1_pr2/round4/logs/guard_unchanged.log) |
| measurements_build | `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -I src tests/ocean_hydro_measurements.cpp -o R/measurements` | 1 | 0.618 | [log](../build_m2b1_pr2/round4/logs/measurements_build.log) |
| amend_refs | `nice -n 19 python3 R/amend_refs.py` | 0 | 0.046 | [log](../build_m2b1_pr2/round4/logs/amend_refs.log) |
| measurements_build_retry1 | `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -I src tests/ocean_hydro_measurements.cpp -o R/measurements` | 0 | 1.116 | [log](../build_m2b1_pr2/round4/logs/measurements_build_retry1.log) |
| measurements | `nice -n 19 R/measurements` | 0 | 0.006 | [log](../build_m2b1_pr2/round4/logs/measurements.log) |
| candidate_emit | `nice -n 19 R/guard --candidate --set kPairedYawGain=0x40400000 --set kTailYawGain=0x3f83d70a --set kTailStiffSpeed=0x42d80000 --emit-calibration R/stage2_candidate.hpp` | 0 | 0.006 | [log](../build_m2b1_pr2/round4/logs/candidate_emit.log) |
| gate02_ubsan_build | `nice -n 19 g++ -O1 -g0 -std=c++20 -ffp-contract=off -fsanitize=undefined -fno-sanitize-recover=all -DEVO_WORLD_OCEAN -I src tests/ocean_tests.cpp -o R/tests_ubsan` | 0 | 55.781 | [log](../build_m2b1_pr2/round4/logs/gate02_ubsan_build.log) |
| verify_guard | `nice -n 19 python3 R/verify_guard.py` | 0 | 0.322 | [log](../build_m2b1_pr2/round4/logs/verify_guard.log) |
| gate02_ubsan_hydro | `nice -n 19 R/tests_ubsan --only hydro` | 0 | 3.047 | [log](../build_m2b1_pr2/round4/logs/gate02_ubsan_hydro.log) |
| gate02_ubsan_hydro_step | `nice -n 19 R/tests_ubsan --only hydro_step` | 0 | 8.458 | [log](../build_m2b1_pr2/round4/logs/gate02_ubsan_hydro_step.log) |
| gate02_optimized_build | `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tests/ocean_tests.cpp -o R/tests` | 0 | 109.837 | [log](../build_m2b1_pr2/round4/logs/gate02_optimized_build.log) |
| gate02_hydro | `nice -n 19 R/tests --only hydro` | 0 | 1.949 | [log](../build_m2b1_pr2/round4/logs/gate02_hydro.log) |
| gate02_hydro_step | `nice -n 19 R/tests --only hydro_step` | 0 | 3.181 | [log](../build_m2b1_pr2/round4/logs/gate02_hydro_step.log) |
| gate03_build | `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_reference.cpp -o R/reference` | 0 | 17.055 | [log](../build_m2b1_pr2/round4/logs/gate03_build.log) |
| gate03_reference | `nice -n 19 R/reference` | 0 | 0.398 | [log](../build_m2b1_pr2/round4/logs/gate03_reference.log) |
| measurement_good_fault | `nice -n 19 bash tests/ocean_hydro_measurements.sh` | 0 | 2.256 | [log](../build_m2b1_pr2/round4/logs/measurement_good_fault.log) |
| assay_stage2_build | `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_assay.cpp -o R/assay_stage2` | 0 | 17.475 | [log](../build_m2b1_pr2/round4/logs/assay_stage2_build.log) |
| assay_fault_build | `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -DPLANT_RADIUS_FAULT -I src tools/ocean_hydro_assay.cpp -o R/assay_fault` | 0 | 17.499 | [log](../build_m2b1_pr2/round4/logs/assay_fault_build.log) |
| assays123_candidate | `nice -n 19 R/assay_stage2 --assay 3 --trace R/assays123.stage2.csv --manifest R/assays123.stage2.json --build-id ba6f29c-round4-stage2 --target native` | 0 | 5.489 | [log](../build_m2b1_pr2/round4/logs/assays123_candidate.log) |
| assays123_radius_fault | `nice -n 19 R/assay_fault --assay 3 --trace R/assays123.fault.csv --manifest R/assays123.fault.json --emit-calibration R/must_not_emit_fault_stage3.hpp --build-id ba6f29c-round4-fault --target native` | 1 | 5.486 | [log](../build_m2b1_pr2/round4/logs/assays123_radius_fault.log) |
| verify_stage2 | `nice -n 19 python3 R/verify_stage2.py` | 0 | 0.582 | [log](../build_m2b1_pr2/round4/logs/verify_stage2.log) |
| stage3_emit | `nice -n 19 R/assay_stage2 --assay 3 --manifest R/stage3_emission.json --emit-calibration R/stage3.hpp --build-id ba6f29c-round4-stage2-freeze3 --target native` | 0 | 4.487 | [log](../build_m2b1_pr2/round4/logs/stage3_emit.log) |
| stage3_install | `nice -n 19 python3 R/install_stage3.py` | 0 | 0.058 | [log](../build_m2b1_pr2/round4/logs/stage3_install.log) |
| assay_stage3_build | `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_assay.cpp -o R/assay_stage3` | 0 | 17.942 | [log](../build_m2b1_pr2/round4/logs/assay_stage3_build.log) |
| assays123_frozen | `nice -n 19 R/assay_stage3 --assay 3 --trace R/assays123.stage3.csv --manifest R/assays123.stage3.json --build-id ba6f29c-round4-stage3 --target native` | 0 | 5.503 | [log](../build_m2b1_pr2/round4/logs/assays123_frozen.log) |
| verify_stage3 | `nice -n 19 python3 R/verify_stage3.py` | 0 | 0.320 | [log](../build_m2b1_pr2/round4/logs/verify_stage3.log) |
| assays1234 | `nice -n 19 R/assay_stage3 --assay 4 --trace R/assays1234.stage3.csv --manifest R/assays1234.stage3.json --emit-calibration R/stage4.hpp --build-id ba6f29c-round4-stage3-assay4 --target native` | 1 | 9.272 | [log](../build_m2b1_pr2/round4/logs/assays1234.log) |
| verify_stop | `nice -n 19 python3 R/verify_stop.py` | 0 | 0.587 | [log](../build_m2b1_pr2/round4/logs/verify_stop.log) |
| stopped_scope | `nice -n 19 git diff --exit-code ba6f29c -- src/core src/ocean/ocean_world.hpp src/ocean/ocean_config.hpp src/ocean/fish.hpp src/ocean/body_plan.hpp src/ocean/body_material.hpp src/ocean/physical_genome.hpp src/ocean/hydro_math.hpp src/ocean/hydro_state.hpp wasm web tests/ocean_baseline tests/fixtures` | 0 | 0.008 | [log](../build_m2b1_pr2/round4/logs/stopped_scope.log) |
| whitespace | `nice -n 19 git diff --check` | 0 | 0.016 | [log](../build_m2b1_pr2/round4/logs/whitespace.log) |
| final_audit | `nice -n 19 python3 R/final_audit.py` | 1 | 4.968 | [log](../build_m2b1_pr2/round4/logs/final_audit.log) |
| final_audit_retry1 | `nice -n 19 python3 R/final_audit.py` | 1 | 4.932 | [log](../build_m2b1_pr2/round4/logs/final_audit_retry1.log) |
| final_audit_retry2 | `nice -n 19 python3 R/final_audit.py` | 0 | 5.844 | [log](../build_m2b1_pr2/round4/logs/final_audit_retry2.log) |

Own-script corrections are disclosed, with no acceptance threshold changes:
initial setup used the wrong installed emsdk path (`~/emsdk` instead of
`~/opt/emsdk`); the initial direct command exited 1 (5.517 s, session tool output,
not journaled), then `gate01_identity_retry1` passed. `patch01` used an incorrect
patch filename and exited 2 before modifying anything; its one corrected retry
passed. The new measurement test initially called `restState` with the wrong
signature; its compile exited 1, one correction/rebuild passed. The final audit
initially assumed the scratch candidate included tests; it does not. The first
text-replacement repair missed the one-space-indented line, so retry 1 repeated
that path failure. The actual inventory-hash repair passed on **retry 2**, within
the two-retry limit. These are tool/test/audit mistakes, not calibration passes
created by changing a predicate. Raw failed invocations remain in the journal.
No existing test was run that needed the sandbox system-call exclusion; no
ENVIRONMENT-BLOCKED claim or workaround was made.

The owner's remaining gate instructions are preserved here verbatim:

> Gates 5–12 exactly as in round 3's instructions (quoted in your report):
> - fixtures native vs Wasm before installing them;
> - full Ocean parity (`APP_TWINS=all JOBS=2 BUILD_JOBS=2 KEEP_OUT=1 bash wasm/ocean_parity.sh`), guards, suites and twins;
> - sequential timing with an A/A control;
> - actual memory against 1,404 B/fish;
> - Ocean/Classic rebuild and freshness (Classic bytes must stay unchanged);
> - repository checks;
> - module consumers;
> - the TypeScript gate;
> - the final audit against the base, with module hashes and the calibration/fixture identities.

| Gate | Round-4 disposition |
|---|---|
| 1: base/fixed-PR-1/frozen scope | Pass |
| 2: optimized and separate UBSan focused suites | Pass, 11+12 groups in each; measurement/signed-angle tests separately pass |
| 3: independent reference | Pass at unchanged tolerances |
| 4: calibration 1→2→3→4 | Partial: 1–3 pass/frozen through 3; **assay 4 FAIL; stopped** |
| 5: native/Wasm hydro/step/calibration fixtures before installation | **NOT RUN**, gate 4 stops advancement; no new fixtures installed |
| 6: full Ocean parity/suites/guards/expanded twins | **NOT RUN**; no narrowed run claimed as full |
| 7: sequential component timing/A/A and actual allocated memory | **NOT RUN**; no A/A/performance/memory acceptance claim |
| 8: Ocean rebuild/freshness | **NOT RUN**; bytes audited against base only |
| 9: Classic ST/MT rebuild/freshness | **NOT RUN**; bytes audited unchanged only |
| 10: native serial repository build/ctest/SFML-dependent tests | **NOT RUN**; availability not newly assessed |
| 11: module consumers and local TypeScript | **NOT RUN**; no network dependency installation |
| 12: final release audit | **Incomplete as a release gate**; stopped-state scope/hash/preservation audit passes |

The later full gate must preserve the exact known `life_cap_fixture_s1` body-twin
harness exception procedure from the plan: raw full exit, ordinary comparison,
both body exits 5, identical body output, only `bodyFounders>0` failed, body
section exists, stripped comparison equals ordinary, and every other case/check
passes. It was not reached or used to excuse this motor failure. Sequential
native/Wasm plain/eye timing still needs the A/A ≤3% control and raw samples;
actual vector capacities/construction/export peaks still need measurement
against 1,404 B/fish. Printed sizeof arithmetic (1,260 B/fish) is not that gate.

### Module hashes and stopped-state audit

All six modules equal the fixed base and their initial round-4 hashes; this proves
preservation, not an unrun rebuild/freshness gate:

| Module | SHA256 |
|---|---|
| `web/evo_boids.js` | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` |
| `web/evo_boids.wasm` | `c1fc4c7a87c6271a4240533fbc3e51400c8028f7a9ec12e976a537448203732b` |
| `web/evo_boids_mt.js` | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` |
| `web/evo_boids_mt.wasm` | `8c7f31ca638a041600bebbf70e12dbef3c2ced9f2004377b574198a247efe268` |
| `web/evo_ocean.js` | `77bd5db9cd78973b77921e67f4df946e50655eb3d0318b630231f4fa08d257e3` |
| `web/evo_ocean.wasm` | `6167f939264bc5ba0f74499ef3eb25bdf523321a13a015e775bd4bbecde58f77` |

| Preserved fixture | SHA256 |
|---|---|
| `tests/fixtures/ocean_hydro_fixture.json` | `e2c080dee4b0de9731bd4f38f5d50241bcb68cc04cc6de1c47b669ed6183db05` |
| `tests/fixtures/ocean_body_fixture.json` | `309071b412405cc4ea3bd2848f360c859f041e8e7ae31428817d3de20d02b5b9` |

No new step/calibration JSON exists. The old hydro fixture remains untouched;
it is not represented as matching the unfinished new reference/mechanics law.
`src/core`, historical Ocean baselines, production world/config, geometry,
physical genes, fingerprint/checkpoint/export paths, wasm and web all have zero
diff from base. Independent read-only scope commands and `git diff --check`
exit 0. All uncommitted earlier source changes remain. The final inventory and
source identities are in [final_audit.json](../build_m2b1_pr2/round4/final_audit.json); nothing under `.git`
was written.

### Known limitations, remaining obligations and proposed commit split

The immediate owner decision is the **separate .60 free-cruise motor anchor**:
resolve the reference/conversion definition or provide an explicit component
acceptance tolerance, with the affected freeze/law authority stated. No such
change is presumed. Body pitch/target-depth bias, residual regulator plateau,
large-slip reduced-speed turns and finite-window command reversals remain
measured limitations. The accepted four-sweep local friction solver still can
choose dynamic friction while aggregate static balance is feasible; the old
`contact_both_loads` counterexample remains diagnostic. No solver redesign or
extra sweeps were introduced.

After that decision: emit/rebuild only an authorized assay-4 candidate; rerun
1→2→3→4, the focused suites and independent reference for any changed law or
constants; only after every predicate passes emit stage 4, rebuild and validate
positive `--check-all`. Implement deterministic fixture emission with invariant
checks and native/Wasm comparison before installation. Integrate fixture and
measurement tests in the complete parity gate. Then perform gates 5–12 exactly
as required, with all raw failures and any narrowly identified sandbox-blocked
existing tests disclosed. No successful native/Wasm proof is claimed for the
new D2/low-slip/assay-4 driver in this round; diagnosis 2's scratch parity remains
its own preserved, failing-motor diagnostic evidence.

PR 3 still owns production lifecycle/activation, funded births and integration,
queries and mouth envelope, pose/render/export/checkpoint/fingerprint integration,
whole-world performance and lifecycle memory, and enabled live rendering/Turbo
validation. None was spliced into production here.

Proposed coordinator commit split (all work remains **uncommitted**):

1. `Add internal Ocean mechanics and sole-ledger energetics`: round-3 kernels,
   harness, focused tests and independent reference; public activation refused.
2. `Calibrate Ocean assays with owner-approved recovery and geometry checks`:
   exact owner amendments, authority guard, measurement/signed-angle tests,
   assay driver and calorimetry accounting, generated calibration header and
   report. Current evidence is **partial through stage 3**; do not title or
   present it as a completed four-assay freeze.
3. After owner resolution and successful gates, `Freeze Ocean mechanics fixtures
   and validation tooling`: stage-4 calibration, generated native/Wasm-equal
   fixtures, parity/timing/memory integration and complete release evidence.
   This commit's work is outstanding and is not fabricated in this stop.

---

The complete report through round 3 follows verbatim as historical evidence.

# M2b1 PR 2 — Round 3: stopped at assay 3, partial freeze through stage 2

**Incomplete; not ready to commit as a completed PR.** Gates 1–3 and assay 1
pass. Assay 1 was emitted at stage 0, passed 33/33, emitted as stage 1,
rebuilt, and passed 33/33 again. Assay 2 passed, installed measured 82/108
power bits without reducing force capacity, and passed cumulative assays 1–2
after the reference-law transition. Assay 3 fails. The last passed generated
stage-2 header is restored; no stage-3/4 header or final calibration fixture
was emitted. Assay 4 and gates 5–11 were not reached. A final read-only scope
and preservation audit is recorded, without calling the unfinished gate 12 complete.

## Round 3 — 2026-11-23

### Decisions, base, and preserved evidence

Owner decisions recorded 2026-11-23 (quoted from the round-3 instruction):

> **D-M2b1-1. Friction-test load point:** for assay 1's floor hold/slip checks, the horizontal force acts at COM's projection onto the floor, not at COM height. That is patch 3's stimulus. Document the sampling convention exactly: the wrench is sampled once per outer step and held across the mechanical substeps. Do not claim continuous world-frame application. Keep the COM-height case as a reported DIAGNOSTIC (it still slides at about 9.26 u/s), not an acceptance check.

> **D-M2b1-2. Contact solver:** keep the prescribed four-sweep local static/dynamic contact solver (plan:878–917) unchanged, with its known limitation: it can select dynamic friction while an aggregate static balance is feasible. Record the limitation in the report and in a short comment at the solver. Keep the feasible-static counterexample (`contact_both_loads`) as a reported diagnostic. Do NOT redesign the solver in this PR; a follow-up will handle it.

> The three calibration constants (metacentric fraction 2, vertical gain .2, regulator tau 2 s) are within assay 1's authority (plan:1066–1075, brief:660). Disclose their magnitude: about 16.7× the starting restoring stiffness, with a neutral lever of about 8.07 u. Don't invent a geometric cap. Apply the check's two P3 corrections in your wording.

The prescribed torque law is unchanged. A hypothetical inside-hull cap would exclude this tested candidate and require further authorized calibration, or a separately approved law/acceptance change; the fraction-1 experiment does not prove impossibility under such a cap. No cap is imposed here. The floor-plane wrench is transformed to body coordinates once at the start of an outer step and reused for both mechanical substeps. Rotation can change its world-frame force/application point during the second substep; no continuous world-frame application is claimed.

Existing feasible-static diagnostic (retained unchanged): build_m2b1_pr2/diag2/audit_20261123/contact_both_loads.log and contact_probe2.cpp. At bootstrap calibration its floor-plane wrench has a feasible proportional tangential balance with |T_i|/N_i=.72 < .8; the local solver instead selects approximately .6 Jn at all three contacts. This remains diagnostic evidence of the explicitly accepted solver limitation, not a repaired acceptance case.


Fixed PR-1 base remains `ba6f29c6ee4a04b1ce41b27ab49e81443802968d`, branch
`m2b1-pr2`. The five prerequisites are present: legal array traversal; finite,
atomic load/scaled-solve refusal and finite LDL factors; independent double
loaded/body/rotational assembly; SPD/finite atomic inverse; block-specific tensor
units. No prerequisite repair was made. See
[gate01_prerequisites.md](../build_m2b1_pr2/round3/gate01_prerequisites.md).

This continuation found the retained round-3 journal and successful stage-0,
stage-1, and stage-2 artifacts already in the worktree. It preserved and checked
them before extending the driver to assay 3. Gate-2/3 results below are the
actual-worktree invocations recorded in that journal, not the diagnosis's scratch
candidate checks. The original round-2 report is retained verbatim below, and its
source snapshots and all earlier raw evidence remain under `round3/before/` and
their original paths. The final hash audit checked **3,015 pre-existing evidence
files with zero mismatches**, including the supplied diagnosis patches/audit.
Nothing was committed, fetched, installed from the network, deployed or rebaselined.

### Generated constants and partial freeze

`tools/ocean_hydro_calibration_io.hpp` emits `std::bit_cast<float>(uint32_t{...})`
declarations, including unchanged constants. Candidate emission precedes calibrated
builds. `--set` accepts exact bits only and refuses constants assigned to another
or already frozen stage; acceptance never applies runtime overrides. The stage-0
verification compared every generated float bit with the old header plus the
three approved replacements. Stage 1 changes only the stage integer. Stage 2
changes only that integer and the two measured power fields. Manifests retain
their actual compiled stage; no stage-0 manifest was relabeled.

The installed header is **partially frozen through 2**, not a completed frozen
calibration. Stage-3 gains below are restored starting values, still unfrozen.

| Constant | Value (short decimal display) | Binary32 bits |
|---|---:|---|
| `kGravity` | 400 | `0x43c80000` |
| `kPressureDepthFraction` | 0.5 | `0x3f000000` |
| `kMetacentricFraction` | 2 | `0x40000000` |
| `kDepthGain` | 0.0799999982 | `0x3da3d70a` |
| `kVerticalGain` | 0.200000003 | `0x3e4ccccd` |
| `kRegulatorTau` | 2 | `0x40000000` |
| `kGasRateFraction` | 0.0199999996 | `0x3ca3d70a` |
| `kPumpEfficiency` | 0.25 | `0x3e800000` |
| `kStaticFriction` | 0.800000012 | `0x3f4ccccd` |
| `kDynamicFriction` | 0.600000024 | `0x3f19999a` |
| `kContactSlopPerSize` | 0.00499999989 | `0x3ba3d70a` |
| `kPenetrationLimitPerSize` | 0.00999999978 | `0x3c23d70a` |
| `kControllerTau` | 0.25 | `0x3e800000` |
| `kHeaveGain` | 1 | `0x3f800000` |
| `kPitchGain` | 1 | `0x3f800000` |
| `kPairedYawGain` | 1 | `0x3f800000` |
| `kTailYawGain` | 0.25 | `0x3e800000` |
| `kTailStiffSpeed` | 108 | `0x42d80000` |
| `kPairedInducedEfficiency` | 0.75 | `0x3f400000` |
| `kBrakeCd` | 1.10000002 | `0x3f8ccccd` |
| `kMeasuredCruisePowerBits` | 44590.30078125 | `0x472e2e4d` |
| `kMeasuredSustainedPowerBits` | 86410.53125 | `0x47a8c544` |

The invariant anchors in digest order remain Uref=82 (`0x42a40000`), Usus=108
(`0x42d80000`), Uact=150 (`0x43160000`), paired rowing efficiency=.35
(`0x3eb33333`), tauBurst=2 (`0x40000000`), gamma=.5 (`0x3f000000`),
and maintenance .04/.04/.02 (`0x3d23d70a`/`0x3d23d70a`/`0x3ca3d70a`).
Reduced induced efficiency .75 is a starting modeling constant assigned to assay
3; it is distinct from .35 rowing efficiency and the geometry-derived tail efficiency.

| Compiled stage | Laws: geometry/material/expression/reference/mechanics/energy | Constants digest | Reference digest |
|---|---|---|---|
| Candidate 0 | 1/1/1/1/1/1 | `5d945ba28512aed4` | `7a56fddda191de89` |
| Rebuilt 1 | 1/1/1/1/1/1 | `67a028f7f1f11b9d` | `7a56fddda191de89` |
| Rebuilt 2, restored | 1/1/1/2/1/1 | `ee915bdf07ddf37f` | `34f5953354409576` |

Coefficient/support/state ABIs remain 1/1/1. Neutral coefficient digest remains
`3e8bfae4938384af`, support `44931eb40f7ec2ef`. Initial reference gas content is
42.48379135131836 at depth 120, E=25 in a 1920×1080×240 toroidal tank.

### Focused gates and assay 1

Optimized and separate UBSan suites pass **11 hydro + 12 hydro-step groups**;
their respective outputs match byte for byte. The calibrated stage-0 long-run
chain is `38e92bfe59ce6839` (40,000 substeps), sampled 85-body chain
`fc30c6fa54db87a4`. These differ from round 2 because the calibrated law differs.
The independent reference passes at unchanged tolerances: 11,508 increments,
worst relative error **3.46972549e-6**; RHS residual **3.94250924e-7**;
5,754 actuator checks, worst **1.27231878e-5**, all below **2e-5**. All nine
fixed-load trajectories complete with zero internal errors. Sequential-patch
model differences remain reported comparisons, without an invented percentage gate.
These suite/reference builds precede the power freeze; they are not a final
stage-4 regression result or native/Wasm proof.

Assay 1 passes **33/33** both before and after stage-1 emission/rebuild. Each run
contains 37,192 completed substeps. Every incoming substep has exactly 25 E,
funded through the metered reserve transaction. Key rebuilt-stage-1 results:

| Subcase | Measurement | Acceptance |
|---|---:|---|
| Relative neutral buoyancy error | 1.52213909e-8 | ≤1e-5 |
| Vertical speed / 60 s depth drift | 4.40524e-13 / 0 | <.01 / <.1 |
| Roll / pitch / combined tilt at 10 s | 0 / .0969133° / .100871° | ≤1° each; no tumbling |
| Depth 96 / 144 final error | .00144958 / .00450134 | ≤1 u each |
| Floor rest speed / penetration | 4.21086e-6 / 1.52588e-5 | <.01 / <.01 S |
| .9 μs N sampled floor-projection load speed | 5.03124e-5 | <.01 |
| 1.1 μs N sampled floor-projection load speed | 14.8317814 | >.01 |
| Positive buoyancy / paid-fin release gap | .831070 / 34.7579193 | >.005 each |
| Paid-fin fuel | 4.79425553 E | >0 |
| Terminal sink force-balance relative error | .00434883106 | ≤.02 |

The COM-height diagnostic was rerun separately: **9.25995349884 u/s**, still
sliding, never counted as an acceptance check. The preserved feasible-static
`contact_both_loads` probe remains a diagnostic, with the .72-required versus
.8-static proportional balance and the solver's approximately .6 Jn local
dynamic selection. No new contact algorithm, extra sweeps or altered threshold
was introduced. Very small printed tilt zeroes reflect the existing binary32
quaternion/up-vector angle measurement; they are not exact mathematical zeros.

### Assay 2

The starting stage-1 candidate passes cumulative **65/65** (33 assay-1 and
32 assay-2 predicates); after measured-power emission and rebuild, stage 2 again
passes **65/65** over 74,692 completed substeps. Full tow drag wrenches, channel
force/lever/prices, pump prices and six-component trim restraints are in
`logs/gate04_assays12_frozen.log`. Tow speeds are 40/82/108/120/150. The tow is
kinematically restrained at the assay-1 load/pose; its printed trim reactions
must not be mistaken for a freely sustained level swimming trim.

Measured powers are 44590.30078125 at 82 and 86410.53125 at 108. The explicit
force-cap check remains **648.991821289 = 2 Dneutral(150)**; it was not re-anchored
at 82. The rebuild activates reference law 2, measured power bits and work
conversion, while the neutral coefficient/support digests stay unchanged.

| Free-drive request | Terminal body-forward speed | Force-balance prediction | Relative error |
|---|---:|---:|---:|
| 40 | 39.9994659 | 40 | .0000133514 |
| 82 | 81.9828272 | 82 | .000209425 |
| 108 | 107.9233801 | 107.9999976 | .000709421 |
| 150 | 109.5590738 | 107.9999976 | .0144358912 |

All errors satisfy 2%; sustained 109.5590738 is within 108±5%. Actual peak is
**142.564056396**, reported against the starting 130–150 window without imposing
a speed clamp. Peak fatigue fills in **2.00800014 s** for fibre 0 and .5; neutral
recovery is **4.00800037 s**, white-fibre recovery **14.552001 s** against its
14.545453 s law, at the unchanged .016 s tolerance. All-red has zero capacity;
shared-lambda/opposed-channel/pump, exhaustion and bounds checks pass.

The free runs expose nonlevel driven trim and depth migration: neutral 82 ends
near depth 87.80086 and tilt 1.37871°, despite its passing speed predicate;
108 ends near depth 26.48722 and tilt 2.44537°. Assay 2 does not establish assay
4's level-trim calorimetry or absence of extra regulator expenditure.

### Assay 3 and the stop

The new driver uses the plan's fixed neutral/manoeuvrer/cruiser bodies. It records
horizontal speed, actual heading derivative, `-omegaBody.z`, unwrapped positions,
an independent centered least-squares circle fit, sideslip, 90° response,
lambda/fatigue and maximum total angular speed. The 40/82 cases begin after
3,750 paid straight outer steps, turn for 625 and fit [500,625). The 120 case
starts from a recovered kinematic straight 120 release, turns for **62 outer
steps (.992 s)** and fits [31,62). It is explicitly a finite burst, not a steady
120 turn; its fatigue and speed changes are reported. A response of -1 means
90° was not observed in the finite window. Low-slip radius checks apply when
the complete fit window stays below 5° sideslip; every observed omega stays
below configured and absolute 12 rad/s rails.

The release experiment sets **yaw=0 while retaining forward drive**, for 625
outer steps. After the finite 120 burst it returns to sustained 82 for that
release. This convention is explicit; the brief does not spell out release
thrust. The result below must be reviewed as a release/trim discrepancy, not
silently replaced with a full-motor shutdown or a changed one-degree bound.

| Stage-3 candidate (paired yaw / tail yaw) | Neutral 82 heading yaw | Neutral 82 actual speed | 40 radii: manoeuvrer / neutral / cruiser | Cumulative predicates |
|---|---:|---:|---|---|
| Starting 1 / .25 | .656404965 | 83.0813381 | 41.629265 / 17.083533 / 36.464363 | **91/97**, exit 1 |
| Paired-heavy 20 / .01 | -.0587430133 | 62.5594510 | 45.867371 / 1090.001436 / 3586.813985 | **94/99**, exit 1 |
| Tail-heavy 1 / 2 | 4.31116521 | 15.8498275 | 1.583032 / 1.441195 / 6.450447 | **92/97**, exit 1 |

The tail-heavy point demonstrates why request 82 must not be reported as actual
82. Each candidate was emitted before its build, retained stage 2, reran all
65 preceding checks successfully, and failed before any stage-3 output was
written. The paired-heavy candidate additionally fails the finite-120 low-slip
radius check: .09894665 relative error versus .05. Conditional low-slip predicates
explain the different total predicate counts. No own-test/script repair or
threshold change was used; these are calibration trials, not own-test retries.
The paired-heavy bits are `0x41a00000` / `0x3c23d70a`; tail-heavy bits are
`0x3f800000` / `0x40000000`, in paired/tail order. Each generated candidate
header and failed manifest/trace remains alongside the last passed header.

**Blocking discrepancy:** driven yaw release retains a nonzero pitching torque
from forward channels. Neutral at 82 is already at **1.37899°** after the
60-second straight control, before yaw is injected; the manoeuvrer at 40 is at
**5.29753°**. In the tail-heavy diagnostic, after 10 / 30 seconds of yaw release,
the angles are **1.36945° / 1.37615°** and **5.29176° / 5.29450°**. This is
persisting driven trim rather than a missing ten-second settling interval.
Neutral active/drag/righting pitch torque at the straight control is approximately
75.13986 / -9.04393 / -84.18098; manoeuvrer is 760.80951 / 10.07834 / -750.69800.
Pitch angular speeds are near 1e-6 rad/s. The same prescribed mechanics law is
balancing a nonzero forward-thrust pitching moment.

At zero yaw and dive, the stage-3 paired commands and their induced drag are
exactly zero. Heave/pitch gains multiply zero dive; paired yaw gain multiplies
zero yaw; tail yaw decays away. Tail yaw gain/stiffening do not remove the
forward-thrust lever. Thus those calibration constants do not change the
no-yaw/no-dive driven straight trim. Righting stiffness and forward allocation
are outside assay 3's tuning authority. The three trials are **not a proof that
every possible yaw calibration is impossible**; they establish the reported
failures and expose this separate driven-release constraint. The actual
heading-yaw and body-ordering calibration is also still unresolved.

As a separately labeled diagnostic, clearing speed as well as yaw brings both
reported angles below 1° at 10 seconds. That changes the release stimulus; it
is not substituted for a pass. A trim/release definition or separately approved
law change is needed before this case can be accepted. Per the stop rule,
calibration stopped here; the failed stage-3 candidates are not installed.
See [release_probe.cpp](../build_m2b1_pr2/round3/release_probe.cpp) and
[release_probe.log](../build_m2b1_pr2/round3/logs/release_probe.log).

A post-stop read-only Python reconstruction independently solves a three-unknown
circle-fit system from the raw state-word traces. All 15 fitted radii agree with
the printed driver fits within 6e-12 relative difference. The 21 preceding-assay
and straight-control trace cases are byte-identical across all three candidates,
including their full state words, energy and metering columns. This directly
confirms the unchanged no-yaw straight controls as well as preceding-assay
compatibility; it is not another acceptance run. See
[measurement_verification.json](../build_m2b1_pr2/round3/measurement_verification.json).

Assay 4 is **NOT RUN / not implemented**. The driver continues to refuse
`--check-all` and `--fixture`; genuine four-assay checking and deterministic
fixture modes remain obligations. No final frozen calibration JSON exists.

### Gate table and raw command journal

Every row below names a recorded command in
[commands.jsonl](../build_m2b1_pr2/round3/commands.jsonl), which includes its full
argv, start/end UTC timestamps, raw exit, environment and duration. Commands
use nice 19; OMP threads ≤2, compiler scheduling ≤2 jobs, EMCC cores=1. No
timing workload or later-gate build was started. `CXX` below abbreviates
`g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src`; UBSan uses
`-O1 -g0 -fsanitize=undefined -fno-sanitize-recover=all`. Paths are abbreviated
relative to `build_m2b1_pr2/round3/`; the linked logs and journal are authoritative.

| Gate / recorded operation | Command (abbreviated) | Raw exit | Seconds | Log |
|---|---|---:|---:|---|
| `gate01_identity` | `Python: base/branch/tool/CPU/module identity` | **0** | 0.274 | [gate01_identity.log](../build_m2b1_pr2/round3/logs/gate01_identity.log) |
| `gate01_scope` | `git diff --exit-code BASE -- frozen paths` | **0** | 0.006 | [gate01_scope.log](../build_m2b1_pr2/round3/logs/gate01_scope.log) |
| `emitter_build` | `CXX tools/ocean_hydro_assay.cpp -o emitter` | **0** | 13.788 | [emitter_build.log](../build_m2b1_pr2/round3/logs/emitter_build.log) |
| `candidate_emit` | `emitter --candidate --set kMetacentricFraction=0x40000000 --set kVerticalGain=0x3e4ccccd --set kRegulatorTau=0x40000000 --emit-calibration stage0.hpp` | **0** | 0.015 | [candidate_emit.log](../build_m2b1_pr2/round3/logs/candidate_emit.log) |
| `candidate_verify_install` | `Python: verify candidate verify install` | **0** | 0.049 | [candidate_verify_install.log](../build_m2b1_pr2/round3/logs/candidate_verify_install.log) |
| `gate02_ubsan_build` | `CXX+UBSan tests/ocean_tests.cpp -o tests_ubsan` | **0** | 55.673 | [gate02_ubsan_build.log](../build_m2b1_pr2/round3/logs/gate02_ubsan_build.log) |
| `gate02_ubsan_hydro` | `tests_ubsan --only hydro` | **0** | 3.056 | [gate02_ubsan_hydro.log](../build_m2b1_pr2/round3/logs/gate02_ubsan_hydro.log) |
| `gate02_ubsan_hydro_step` | `tests_ubsan --only hydro_step` | **0** | 8.799 | [gate02_ubsan_hydro_step.log](../build_m2b1_pr2/round3/logs/gate02_ubsan_hydro_step.log) |
| `gate02_optimized_build` | `CXX tests/ocean_tests.cpp -o tests` | **0** | 109.043 | [gate02_optimized_build.log](../build_m2b1_pr2/round3/logs/gate02_optimized_build.log) |
| `gate02_hydro` | `tests --only hydro` | **0** | 1.941 | [gate02_hydro.log](../build_m2b1_pr2/round3/logs/gate02_hydro.log) |
| `gate02_hydro_step` | `tests --only hydro_step` | **0** | 3.312 | [gate02_hydro_step.log](../build_m2b1_pr2/round3/logs/gate02_hydro_step.log) |
| `gate03_reference_build` | `CXX tools/ocean_hydro_reference.cpp -o reference` | **0** | 16.668 | [gate03_reference_build.log](../build_m2b1_pr2/round3/logs/gate03_reference_build.log) |
| `gate03_reference` | `reference ` | **0** | 0.396 | [gate03_reference.log](../build_m2b1_pr2/round3/logs/gate03_reference.log) |
| `gate04_stage0_build` | `CXX tools/ocean_hydro_assay.cpp -o assay_stage0` | **0** | 15.194 | [gate04_stage0_build.log](../build_m2b1_pr2/round3/logs/gate04_stage0_build.log) |
| `gate04_assay1_candidate` | `assay_stage0 --assay 1 --trace assay1.stage0.csv --manifest assay1.stage0.json --emit-calibration stage1.hpp --build-id ba6f29c-round3-stage0 --target native` | **0** | 1.468 | [gate04_assay1_candidate.log](../build_m2b1_pr2/round3/logs/gate04_assay1_candidate.log) |
| `stage1_verify_install` | `Python: verify stage1 verify install` | **0** | 0.047 | [stage1_verify_install.log](../build_m2b1_pr2/round3/logs/stage1_verify_install.log) |
| `gate04_stage1_build` | `CXX tools/ocean_hydro_assay.cpp -o assay_stage1` | **0** | 15.980 | [gate04_stage1_build.log](../build_m2b1_pr2/round3/logs/gate04_stage1_build.log) |
| `gate04_assay1_frozen` | `assay_stage1 --assay 1 --trace assay1.stage1.csv --manifest assay1.stage1.json --build-id ba6f29c-round3-stage1 --target native` | **0** | 1.465 | [gate04_assay1_frozen.log](../build_m2b1_pr2/round3/logs/gate04_assay1_frozen.log) |
| `contact_diagnostics` | `assay_stage1 --contact-diagnostics` | **0** | 0.331 | [contact_diagnostics.log](../build_m2b1_pr2/round3/logs/contact_diagnostics.log) |
| `stage2_candidate_emit` | `assay_stage1 --candidate --emit-calibration stage2_candidate.hpp` | **0** | 0.006 | [stage2_candidate_emit.log](../build_m2b1_pr2/round3/logs/stage2_candidate_emit.log) |
| `stage2_candidate_verify` | `cmp src/ocean/hydro_calibration.hpp stage2_candidate.hpp` | **0** | 0.005 | [stage2_candidate_verify.log](../build_m2b1_pr2/round3/logs/stage2_candidate_verify.log) |
| `gate04_assay2_build` | `CXX tools/ocean_hydro_assay.cpp -o assay2_candidate` | **0** | 16.133 | [gate04_assay2_build.log](../build_m2b1_pr2/round3/logs/gate04_assay2_build.log) |
| `gate04_assay2_candidate` | `assay2_candidate --assay 2 --trace assay2.candidate.csv --manifest assay2.candidate.json --emit-calibration stage2.hpp --build-id ba6f29c-round3-assay2-candidate --target native` | **0** | 2.859 | [gate04_assay2_candidate.log](../build_m2b1_pr2/round3/logs/gate04_assay2_candidate.log) |
| `stage2_verify_install` | `Python: verify stage2 verify install` | **0** | 0.045 | [stage2_verify_install.log](../build_m2b1_pr2/round3/logs/stage2_verify_install.log) |
| `gate04_stage2_build` | `CXX tools/ocean_hydro_assay.cpp -o assay_stage2` | **0** | 15.621 | [gate04_stage2_build.log](../build_m2b1_pr2/round3/logs/gate04_stage2_build.log) |
| `gate04_assays12_frozen` | `assay_stage2 --assay 2 --trace assays12.stage2.csv --manifest assays12.stage2.json --build-id ba6f29c-round3-stage2 --target native` | **0** | 2.856 | [gate04_assays12_frozen.log](../build_m2b1_pr2/round3/logs/gate04_assays12_frozen.log) |
| `stage3_starting_candidate_emit` | `assay_stage2 --candidate --emit-calibration stage3_starting_candidate.hpp` | **0** | 0.009 | [stage3_starting_candidate_emit.log](../build_m2b1_pr2/round3/logs/stage3_starting_candidate_emit.log) |
| `stage3_starting_candidate_verify` | `cmp src/ocean/hydro_calibration.hpp stage3_starting_candidate.hpp` | **0** | 0.006 | [stage3_starting_candidate_verify.log](../build_m2b1_pr2/round3/logs/stage3_starting_candidate_verify.log) |
| `gate04_assay3_starting_build` | `CXX tools/ocean_hydro_assay.cpp -o assay3_starting` | **0** | 16.228 | [gate04_assay3_starting_build.log](../build_m2b1_pr2/round3/logs/gate04_assay3_starting_build.log) |
| `gate04_assay3_starting` | `assay3_starting --assay 3 --trace assays123.starting.csv --manifest assays123.starting.json --emit-calibration stage3.hpp --build-id ba6f29c-round3-assay3-starting --target native` | **1** | 3.752 | [gate04_assay3_starting.log](../build_m2b1_pr2/round3/logs/gate04_assay3_starting.log) |
| `stage3_paired_candidate_emit` | `assay3_starting --candidate --set kPairedYawGain=0x41a00000 --set kTailYawGain=0x3c23d70a --emit-calibration stage3_paired_candidate.hpp` | **0** | 0.005 | [stage3_paired_candidate_emit.log](../build_m2b1_pr2/round3/logs/stage3_paired_candidate_emit.log) |
| `stage3_paired_candidate_install` | `cp stage3_paired_candidate.hpp src/ocean/hydro_calibration.hpp` | **0** | 0.005 | [stage3_paired_candidate_install.log](../build_m2b1_pr2/round3/logs/stage3_paired_candidate_install.log) |
| `gate04_assay3_paired_build` | `CXX tools/ocean_hydro_assay.cpp -o assay3_paired` | **0** | 16.039 | [gate04_assay3_paired_build.log](../build_m2b1_pr2/round3/logs/gate04_assay3_paired_build.log) |
| `gate04_assay3_paired` | `assay3_paired --assay 3 --trace assays123.paired.csv --manifest assays123.paired.json --emit-calibration stage3_paired.hpp --build-id ba6f29c-round3-assay3-paired --target native` | **1** | 4.333 | [gate04_assay3_paired.log](../build_m2b1_pr2/round3/logs/gate04_assay3_paired.log) |
| `stage3_tail_candidate_emit` | `assay3_paired --candidate --set kPairedYawGain=0x3f800000 --set kTailYawGain=0x40000000 --emit-calibration stage3_tail_candidate.hpp` | **0** | 0.005 | [stage3_tail_candidate_emit.log](../build_m2b1_pr2/round3/logs/stage3_tail_candidate_emit.log) |
| `stage3_tail_candidate_install` | `cp stage3_tail_candidate.hpp src/ocean/hydro_calibration.hpp` | **0** | 0.006 | [stage3_tail_candidate_install.log](../build_m2b1_pr2/round3/logs/stage3_tail_candidate_install.log) |
| `gate04_assay3_tail_build` | `CXX tools/ocean_hydro_assay.cpp -o assay3_tail` | **0** | 16.194 | [gate04_assay3_tail_build.log](../build_m2b1_pr2/round3/logs/gate04_assay3_tail_build.log) |
| `release_probe_build` | `CXX build_m2b1_pr2/round3/release_probe.cpp -o release_probe` | **0** | 10.605 | [release_probe_build.log](../build_m2b1_pr2/round3/logs/release_probe_build.log) |
| `gate04_assay3_tail` | `assay3_tail --assay 3 --trace assays123.tail.csv --manifest assays123.tail.json --emit-calibration stage3_tail.hpp --build-id ba6f29c-round3-assay3-tail --target native` | **1** | 4.434 | [gate04_assay3_tail.log](../build_m2b1_pr2/round3/logs/gate04_assay3_tail.log) |
| `release_probe` | `release_probe ` | **0** | 0.784 | [release_probe.log](../build_m2b1_pr2/round3/logs/release_probe.log) |
| `restore_last_passed_stage2` | `cp stage2.hpp src/ocean/hydro_calibration.hpp` | **0** | 0.005 | [restore_last_passed_stage2.log](../build_m2b1_pr2/round3/logs/restore_last_passed_stage2.log) |
| `stopped_scope_identity` | `python3 build_m2b1_pr2/round3/final_audit.py` | **0** | 1.847 | [stopped_scope_identity.log](../build_m2b1_pr2/round3/logs/stopped_scope_identity.log) |
| `stopped_measurement_review` | `python3 build_m2b1_pr2/round3/check_measurements.py` | **0** | 5.099 | [stopped_measurement_review.log](../build_m2b1_pr2/round3/logs/stopped_measurement_review.log) |

| Remaining gate | Status / reason |
|---|---|
| 4: assay 3, then assay 4 and genuine stage-4 `--check-all` | **BLOCKED at assay 3**; no stage-3/4 freeze |
| 5: native/Wasm generators, pre-install comparison, installed fixture comparison | NOT RUN; no fixtures installed |
| 6: full Ocean parity, suites/guards/expanded twins | NOT RUN; no exception invoked |
| 7: sequential component timing, A/A, actual allocations and peaks | NOT RUN; no allowance/ceiling claim |
| 8: Ocean rebuild/freshness | NOT RUN; unchanged hashes alone do not prove freshness |
| 9: Classic rebuild/freshness | NOT RUN; no pins edited |
| 10: native-serial configure/build/ctest | NOT RUN; SFML test availability not established here |
| 11: module consumers and installed local TypeScript | NOT RUN; offline availability not inferred |
| 12: final release audit | Partial read-only stopped-state audit only; completion blocked by earlier gates |

### Identities, modules, and fixed-scope audit

The final read-only audit against the fixed base exits 0 for `src/core`,
production Ocean world/config, all `wasm/` and `web/`, historical baselines,
all existing fixtures, geometry/material/state/math foundations. No RNG draw
order, public activation/refusal, fingerprint/checkpoint API or rendering path
was changed. `git diff --check` exits 0. These results describe scope, not
unrun release-gate acceptance. Source hashes, all seven manifest/trace hashes,
and the full changed-file status are in
[final_audit.json](../build_m2b1_pr2/round3/final_audit.json).

| Artifact | SHA256 |
|---|---|
| `src/ocean/hydro_calibration.hpp` | `20baf77251063a5d8feeb85655b5e290a5a74a6bc0fb6014b35e691288ff7ebe` |
| `stage1.hpp` | `55bfeeccc70cd584841361f20cc5191b9104003975d617276bea110f3ea3ef0c` |
| `assay1.stage1.json` | `3cce3f6e457a7a426192f7a40951e09fcf0f764552c2478b455c90c318baad6a` |
| `assays12.stage2.json` | `2f91e5404d3b69f43774daab2c2497d0775db89e828bfe4729ef7f6846ad0996` |
| `assays12.stage2.csv` | `449b4ccfb4d8fc425919c524548f5d783f6064b87e5366606f133b70ae4c7450` |
| `tests/fixtures/ocean_hydro_fixture.json` | `e2c080dee4b0de9731bd4f38f5d50241bcb68cc04cc6de1c47b669ed6183db05` |
| `tests/fixtures/ocean_body_fixture.json` | `309071b412405cc4ea3bd2848f360c859f041e8e7ae31428817d3de20d02b5b9` |
| `web/evo_boids_mt.js` | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` |
| `web/evo_boids.wasm` | `c1fc4c7a87c6271a4240533fbc3e51400c8028f7a9ec12e976a537448203732b` |
| `web/evo_ocean.js` | `77bd5db9cd78973b77921e67f4df946e50655eb3d0318b630231f4fa08d257e3` |
| `web/evo_boids.js` | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` |
| `web/evo_boids_mt.wasm` | `8c7f31ca638a041600bebbf70e12dbef3c2ced9f2004377b574198a247efe268` |
| `web/evo_ocean.wasm` | `6167f939264bc5ba0f74499ef3eb25bdf523321a13a015e775bd4bbecde58f77` |

No new mechanics/calibration fixture identity exists; the old hydro fixture
still describes the earlier version and must be regenerated only after stage 4
and native/Wasm pre-install equality. No historical Ocean baseline, Classic pin,
M2a fixture or committed module was changed by hand or by a build in this round.

### Known limitations, remaining obligations, proposed commit split

The accepted local contact solver can select dynamic friction despite aggregate
static feasibility. The sampled body-frame floor wrench is held across substeps
and need not remain continuously floor-tangential in world space. Stronger
metacentric calibration preserves the declared torque law but increases starting
stiffness about 16.7×; no geometric COB interpretation or invented cap is claimed.
Assay 2's speed success does not establish level paid trim. Assay 3's driven
righting, yaw and body-ordering requirements remain unresolved; recorded trial
points do not establish an exhaustive calibration search. New assay-3 measurement
code has native candidate results only, with no completed frozen or Wasm evidence.

Resolve that discrepancy before continuing the ordered stage-3/4 freeze.
Implement assay 4, real `--check-all`, refusal/invariant checks and deterministic
fixture emission; then do gates 5–12 in order, including actual allocated memory,
native/Wasm timing with A/A, full parity and module rebuilds/freshness. Do not
reuse the old 1,260 B payload printout as proof of the 1,404 B resident ceiling.
Neither the +448 ns/fish-step engineering allowance nor any timing/memory gate
is established. Retain all candidate failures. No parity exception is claimed.

PR 3 still owns production activation/lifecycle splice, reproduction and carried
fuel transactions, feeding/fighting/sharing/reseeding, mouth queries, aligned
ownership/compaction integration, pose/export/checkpoint/fingerprint continuation,
enabled full-world parity, complete-world 2,000-fish paired Wasm ≤1.25 timing,
lifecycle memory, and live rendering/Turbo/checkpoint/export validation.

Proposed coordinator commits **after successful completion**, not an instruction
to commit this incomplete state:

1. `Add internal Ocean mechanics and fuel accounting` — internal energy,
   mechanics/contact, the previously authorized fuel-domain clarification,
   action adapter/source hook and focused tests.
2. `Freeze Ocean mechanics assays and deterministic fixtures` — independent
   reference, assay harness/measurements, exact-bit emitter, actually completed
   calibration/fixtures, parity and timing/memory tooling, and final report.

Commit 2 is not ready. No module-artifact commit is proposed without the required
rebuild/freshness evidence. The coordinator supplies attribution trailers; all
changes remain uncommitted and `.git` was used read-only. Forbidden trees,
noise bank, external study data and supervisors were not accessed.

---

## Preserved round-2 and round-1 reports (historical; superseded by Round 3 above)

# M2b1 PR 2 — round 2 stopped at gate 4

**Incomplete; not ready to commit as a completed PR.** The coordinator-authorized
capacity and recovery corrections, plus both checker changes, are applied.
Gates 2 and 3 pass. Gate 4's initial assay 1 fails six acceptance checks at the
unchanged starting constants. Work stopped there under the requested first-failure
rule. No calibration, fixture update, module rebuild, or timing/memory gate was
performed after that failure. The preserved round-1 report follows this section.

## Round 2 — 2026-11-22 (local)

### Authorization, arithmetic domain, and tests

Base and branch remain `ba6f29c6ee4a04b1ce41b27ab49e81443802968d`,
`m2b1-pr2`. Refreshed identity and the five-fix prerequisite source audit are in
`build_m2b1_pr2/logs/round2_identity.json`, `round2_emsdk_identity.log`,
`round2_gate01_prerequisites.md`, and `round2_prerequisite_source.txt`.
All five fixed-PR-1 prerequisites remain present; no prerequisite repair was made.

Applied the two supplied patches with the coordinator's explicit authorization:

- The existing exact `energy / 500.0f` conversion now lives in
  `hydro_coefficients.hpp` and is shared by the ledger and load endpoint.
  `fuelCapacity(c)` is
  `max(c.reserveCapacity*(bodymat::kRhoLipid*rhoWater()), fuelMass(c.energyCapacity))`.
  Both capacities must be finite and nonnegative. Both rounded endpoints are
  accepted; the first representable mass above their envelope is refused and
  clears the complete output.
- Recovery observes up to 2,000 substeps, checks each call succeeds, requires
  `fatigue == 0`, and retains the strict **0.016 s** timing tolerance and free
  recovery check. The expected fibre-dependent law is unchanged.

This is an **explicit clarification of the binary32 acceptance domain**, with
one ULP outward at the boundary for some bodies. It is **not bit-for-bit
preservation of the old refusal contract**. For the neutral body, 45/500 has bits
`0x3db851ec`, while the old physical endpoint has bits `0x3db851eb`; both are now
inside the admissible envelope. This does not add an arbitrary nextafter margin
or silently clamp a submitted load. The compiled capacities and coefficient
values are unchanged.

Both checker requirements are implemented across the 137-body fixture set:

1. The regrouped total-mass oracle was removed. `loadAt` is compared bit for bit,
   field by field, with `evalLoad` receiving the independently written required
   division. It covers `fuelVolume`, all scalar/vector fields, all three S3
   tensors, all four S6 tensors, and both K arrays. It compares the loader's
   complete result without reconstructing or regrouping its mass addition.
   Loads include zero, half, the predecessor of Ecap, and Ecap, with three gas
   contents. `fuelMass(5)` is independently pinned to **`0x3c23d70a`**, which
   distinguishes division from rounded reciprocal multiplication.
2. The early NaN refusal remains. The new late refusal starts at Ecap/4 and
   credits Ecap/4 using finite perpendicular position/velocity of magnitude
   `1e30`. It proves the initial load is legal and the candidate orbital cross
   product overflows, then checks the refusal preserves ledger, physical state,
   status, and every declared receipt word. The receipt sentinel gives nonzero,
   distinct values to every field, including the removed parcel.

Focused coverage was also expanded for rotated steering frames, lower speed
clamp, separate channel power, analytic limiter/exhaustion/blocked work, shared
motor/pump lambda, contact response/impulse closure and dynamic friction,
inflation at a glass/floor corner, additional refusals, and completed-step
long-run load/state/hull legality. Final optimized and UBSan outputs both show
**11 hydro groups and 12 hydro-step groups passing**. The reserve group contains
3,025 checks. The 40,000-substep chain remains `2ef1dabecb54c7d2`; the 85-body
chain remains `a64067c3c08f85e5`.

### Own-test corrections and retries

Two self-authored test mistakes were corrected, once each; neither changed a
physical law or the required LDL/recovery tolerances. All original nonzero exits
are retained in `logs/gates.jsonl` and the individual raw logs.

- Initial gate 2: my added long-run hull check inspected the state **after** the
  harness's later fuel refill. The completed step at outer index 6,611 had wall
  gap exactly zero; the refill changed inflation from 1.03700709 to 1.03703058,
  making the subsequent gap -0.000122070312. The test now checks the completed
  step before that refill, with the same `1e-4` check. The independent diagnostic
  is `round2_longrun_probe.cpp` and `logs/round2_longrun_probe.log`. Gate 2 retry 1
  passed. The normal step/ledger behavior and both chains stayed identical.
- Initial gate 3: my total actuator-price error used the nearly zero pump
  residual as its reference scale for a no-fin, almost neutrally buoyant load.
  The resulting ill-conditioned metric was 0.000296265344. The corrected metric
  uses at least full-rate pump power as its physical scale; material/load values
  remain independently integrated. Pump-rate and pump-price checks remain, and
  their physical scales are explicit. No production code was changed for this
  correction. Gate 3 retry 1 passed. The LDL tolerance is still **2e-5**.

The subsequent source-hook regression builds are fresh checks of changed code,
not further attempts to repair either test failure.

### Gate 3: independent reference and model comparison

The native reference preserves all fixed-PR-1 compound, tensor, cubature,
asymmetry and planted-fault checks. The added reference uses independently
transformed material parts and directly integrated hull/fin tensors; production
Meff, damping, active wrench and RHS are not fed into the double physical oracle.
Birth scalar parameters such as tail tau/efficiency and the frozen global force
ceiling are declared inputs. Dense double solves pivot independently.

Final output, after the harness source-hook refactor:

| Independent check | Result | Limit |
|---|---:|---:|
| Original passive double Gauss vs binary32 LDL | 3.042e-7 | 2e-5 |
| 11,508 passive/active one-step increments, including tilted righting | 1.09008442e-6 | 2e-5 |
| Independent full RHS residual | 3.17218811e-7 | 2e-5 |
| 5,754 actuator force/location/power/gas comparisons | 5.09006984e-6 | 2e-5 |
| Bodies / loads / asymmetric-only probes | 137 / 411 / 3 | complete |
| Fixed-load comparison trajectories | 9 complete, no internal errors | complete |

The sequential comparator performs the body damping/righting solve, then the
seven fin patches in caudal/dorsal/anal/pectoral R/L/pelvic R/L order. Each patch
recomputes current slip and applies its implicit rank-one response. It exists
only in the offline native tool. Tow drag/work at 40/82/108/120/150 and tow,
open-loop turn and relaxation paths are reported for neutral, no-appendage and
random19 bodies. Each trajectory is 1,250 mechanical substeps; circle fits use
positions from substeps [625,1250). Both fitted radius and U/body-yaw are printed.
These are fixed-load kernel comparisons with a prescribed common external
wrench, without fuel updates, gas regulation, contacts or rails; they do not
substitute for the paid free-drive/steering assays or production-world behavior.

Model differences are **reported, not acceptance gates**. For example, neutral
82 tow drag is 93.8496484 vs 93.7031998 and work rate 7695.67117 vs 7683.66239
(tensor vs patch). In its open-loop turn, fitted radii are 578.549639 vs
216.851365; the patch reaches 90 degrees at 3.92000019 s, while the tensor does
not reach it within the 10 s observation. Random19 fitted turn radii are
460.223724 vs 177.572007, with 90-degree times 8.64000041 vs 3.38400016 s.
No under-3% model-comparison gate was invented. `inf` response/relaxation entries
mean that the event was not observed in the finite window. Straight-line circle
fits can be singular or ill-conditioned and are not physical finite-radius
claims. Full output: `logs/round2_gate04_source_regression_reference.log`.

### Gate 4: metered assay 1 and the substantive stop

The internal step now has a templated before-substep source hook. Its ordinary
wrapper supplies a no-op, preserving the exactly two-substep path. The harness's
`stepFixed` injects only through `changeReserve`, on the kernel's local copies,
and records both source receipts and incoming energies. Metering publishes only
when the entire outer step succeeds; age/timers advance once. No resident
per-fish record or column was added. Production world/module paths do not use it.

Because this changed an internal kernel header, both focused suites were rebuilt
and rerun in optimized and UBSan builds before running assay 1; the reference was
also rebuilt/rerun. All pass on the final source, with identical focused outputs
and chains. Those are the `round2_gate04_source_regression_*` logs.

The new assay-1 driver uses integer windows and the starting constants. Its
trace contains **37,192 completed substep rows across 12 windows**, with exactly
25 E at every incoming mechanical substep. It records subsidies, debits, motor
fuel, gas requests/lambda, and all 19 declared state words. No source was an
unmetered ledger assignment. The manifest carries config, laws/ABIs, reference
load/gas, digests, exact constant bit fields, target/build, results and windows.

Command (through `run_gate.py`, nice 19):

```bash
build_m2b1_pr2/ocean_hydro_assay --assay 1 \
  --trace build_m2b1_pr2/round2_assay1.trace.csv \
  --manifest build_m2b1_pr2/round2_assay1.manifest.json \
  --build-id ba6f29c-round2 --target native
```

**Raw exit 1, 27/33 checks passing.** All 12 scripted windows completed; this
failure is not a truncated run, missing tool, or incoming-fuel shortage.

| Assay-1 acceptance | Observed | Required | Status |
|---|---:|---:|---|
| Static relative buoyancy error | 1.52213908522e-8 | <=1e-5 | PASS |
| Static vertical speed / 60 s depth drift | 1.5557e-13 / 0 | <.01 / <.1 u | PASS |
| 10-degree roll release, 10 s | 1.02144151696 degrees | <=1 degree | **FAIL** |
| 10-degree pitch release, 10 s | 5.00155253348 degrees | <=1 degree | **FAIL** |
| Combined release, 10 s | 4.40935532850 degrees | <=1 degree | **FAIL** |
| Target depth 96, 60 s | depth 70.2301254; error 25.7698746 | error <=1 u | **FAIL** |
| Target depth 144, 60 s | depth 166.328400; error 22.3283997 | error <=1 u | **FAIL** |
| Bladder-less floor rest speed / penetration, 60 s | .000494557 / .0000305176 u | <.01 / <.01*S | PASS |
| .9*muStatic*N floor load, 10 s | tangential speed 9.03187943 | holds (<.01) | **FAIL** |
| 1.1*muStatic*N floor load, 10 s | tangential speed 14.7301083 | slips (>.01) | PASS |
| Positive-buoyancy floor release, .512 s | floor gap .830352783 u | releases | PASS |
| Separately paid upward-fin release, 1.024 s | gap 25.1194153 u; motor debit 4.79437748 E | releases and pays | PASS |
| Terminal sinking, last 2 s of 6 s window | 9.37257058 vs predicted 9.41368737 u/s; .436777% error | <=2% | PASS |

All three righting releases remain below 90 degrees, with no tumbling. The
below-threshold friction load is a world-horizontal force at COM, converted to
the current body frame each outer step; its normal-load scale is 14.2666339874.
Terminal sinking uses the declared loaded vertical quadratic drag balance; the
approximate starting expectation of 12 u/s was not made a hard acceptance gate.

No constants were tuned after this failure and no calibration was emitted.
`kFrozenThrough` is still **0**, measured-power bits are zero, and reference law
is still provisional law 1. Assays 2–4, calibration emission/freeze and mechanics
fixture mode remain unfinished. The draft driver's later-stage and fixture
options refuse rather than claim completion. This is an implementation handoff,
not a stage-1 or release freeze. Next work needs to address the measured righting,
depth settling/overshoot and static-friction behavior within the authorized
calibration/law rules, then rerun earlier gates affected by any change.

Raw output is `logs/round2_gate04_assay1.log`; the parsed, read-only trace summary
is `logs/round2_assay1_trace_summary.json`. The failure manifest is evidence of
an unsuccessful candidate, not a frozen calibration manifest.

### Round-2 gates and command receipts

Every command/status/duration is retained in
`build_m2b1_pr2/logs/gates.jsonl`; each row below uses the named `.log` there.
Native flags: `-O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src`.
The separate UBSan build uses `-O1 -g0 -fsanitize=undefined
-fno-sanitize-recover=all` and the same language/floating-point flags.

| Gate | Round-2 outcome | Evidence |
|---|---|---|
| 1: refreshed base/five-fix audit | PASS by inspection | `round2_identity.json`, `round2_gate01_prerequisites.md` |
| 2: focused native + separate UBSan | PASS after one own-test retry; revalidated after source-hook change | `round2_gate04_source_regression_{hydro,hydro_step,ubsan_hydro,ubsan_hydro_step}.log` |
| 3: independent reference + comparator | PASS after one own-oracle retry; revalidated on final source | `round2_gate04_source_regression_reference.log` |
| 4: calibration 1 -> 2 -> 3 -> 4 | **FAIL at initial assay 1; stop** | `round2_gate04_assay1.log`, trace and unsuccessful manifest |
| 5: native/wasm hydro and mechanics fixtures | NOT RUN | gate 4 blocks |
| 6: full plain/eye parity and all twins | NOT RUN | gate 4 blocks; body-twin exception not reached |
| 7: population-2,000 paired/A/A timing and capacity/peak memory | NOT RUN | gate 4 blocks |
| 8: Ocean rebuild/freshness | NOT RUN | gate 4 blocks |
| 9: Classic ST/MT rebuild/freshness | NOT RUN | gate 4 blocks |
| 10: native serial build/ctest/SFML availability | NOT RUN | gate 4 blocks |
| 11: module consumers/local TypeScript | NOT RUN | gate 4 blocks |
| 12: final release scope audit | NOT RUN as a release gate | post-stop read-only scope/whitespace audit only |

Measured command receipts (seconds are execution wall time, not component
performance evidence):

| Log stem / command receipt | Exit | Seconds |
|---|---:|---:|
| `round2_emsdk_identity` | 0 | 0.532 |
| `round2_gate02_build` | 0 | 108.777 |
| `round2_gate02_hydro` | 0 | 1.981 |
| `round2_gate02_hydro_step` | 1 | 1.049 |
| `round2_longrun_probe_build` | 0 | 11.219 |
| `round2_longrun_probe` | 0 | 0.928 |
| `round2_gate02_retry1_build` | 0 | 109.138 |
| `round2_gate02_retry1_hydro` | 0 | 1.968 |
| `round2_gate02_retry1_hydro_step` | 0 | 3.228 |
| `round2_gate02_ubsan_build` | 0 | 56.446 |
| `round2_gate02_ubsan_hydro` | 0 | 3.092 |
| `round2_gate02_ubsan_hydro_step` | 0 | 8.866 |
| `round2_gate03_build` | 0 | 16.465 |
| `round2_gate03_reference` | 1 | 0.403 |
| `round2_gate03_retry1_build` | 0 | 16.701 |
| `round2_gate03_retry1_reference` | 0 | 0.419 |
| `round2_gate04_source_regression_build` | 0 | 113.148 |
| `round2_gate04_source_regression_hydro` | 0 | 2.017 |
| `round2_gate04_assay_build` | 0 | 14.820 |
| `round2_gate04_source_regression_hydro_step` | 0 | 3.412 |
| `round2_gate04_source_regression_reference_build` | 0 | 17.768 |
| `round2_gate04_source_regression_ubsan_build` | 0 | 55.977 |
| `round2_gate04_source_regression_ubsan_hydro` | 0 | 3.091 |
| `round2_gate04_source_regression_ubsan_hydro_step` | 0 | 8.938 |
| `round2_gate04_source_regression_reference` | 0 | 0.412 |
| `round2_gate04_assay1` | 1 | 1.507 |
| `round2_stop_scope_audit` | 0 | 0.031 |

GCC 15.2.0, Emscripten 6.0.4, Node v26.13.0, CMake 3.28.3;
Intel i5-10500T. Commands ran at nice 19, with at most two concurrent compiler
jobs and `OMP_NUM_THREADS=4`. Native override variables were unset by the runner.
The only wasm-shell operation reached was toolchain identity: it sourced
`~/opt/emsdk/emsdk_env.sh` first, then set the in-tree EM_CACHE, unset native
variables, and set `EMCC_CORES=1`. No dependency fetch or network operation was
performed. No receipt skip or browser was used.

### Evidence hashes, unchanged scope, performance, and handoff

Full SHA256 inventory (sources, patches, evidence, existing modules and fixtures):
`build_m2b1_pr2/logs/round2_artifact_sha256.json`. Selected hashes:

| Artifact | SHA256 |
|---|---|
| `src/ocean/hydro_coefficients.hpp` | `b2ee82f4892e5996ced526e9b94bb025a2430a404f86cc7ea6dec9c4014c4703` |
| `src/ocean/ocean_energy.hpp` | `91f6e2083fb2c18a06dc85ceeaaf89af819be03bb1194db4c05c7411eb3391e8` |
| `src/ocean/hydro_step.hpp` | `a9150680c49318fdceff17a228e67804698c959cbdcc7479cd00175563731cec` |
| `tests/ocean_hydro_step_tests.hpp` | `0994b672393a4d4a9db72a2efdbf6805ad81b4ae0b4fe0dc68e7ca69c935f683` |
| `tools/ocean_hydro_reference.cpp` | `a7b6cfd6b3264309504677fb5dafb2bd4b0946973d8919c9ec9c1ac5e55bd0b1` |
| `tools/ocean_hydro_trajectory_reference.hpp` | `0e27103a4f6f0b999f25c3282af93cdd55ead554bcd3884c150d8402a60ae4de` |
| `tools/ocean_hydro_harness.hpp` | `cb0cbb9fcd1a49b7f065ab857450e49dd5845da8fea81b456db63e613f518410` |
| `tools/ocean_hydro_assay.cpp` | `27a3b612048200122071b8cddc89af73902dcd3fdc02df8f8c8cd1c01a39aa4b` |
| `build_m2b1_pr2/logs/round2_gate04_source_regression_reference.log` | `cad7d28e055b044e1db46a8eed5437c2da8986cb77579f6229a2d6c5ce76f1ff` |
| `build_m2b1_pr2/round2_assay1.manifest.json` | `779d460f686886b3c3f4d1df9d98f31c8098eb91eba0ba6eb19c66360fe72c52` |
| `build_m2b1_pr2/round2_assay1.trace.csv` | `202334e77ee3798b95f1230960ec42bce8c754cda1873775f6b0f8637e5cf2fa` |

The post-stop read-only diff against the base and `git diff --check` both exit 0
for the preserved paths; details are in `logs/round2_stop_scope_audit.log`.
Production stepping/lifecycle, public refusal/configuration, module shims,
fingerprints/checkpoints, renderer/web files, `src/core`, historical Ocean
baselines and all existing fixtures are unchanged. The supplied diagnosis and
both proposed patch files are also unchanged. All six committed module hashes
still equal the starting values listed in the preserved round-1 report and the
round-2 identity/inventory. **Unchanged bytes are not rebuild/freshness evidence**;
those gates were not reached. No fixture, pin or baseline was generated/replaced.

No population-2,000 timing, paired ratio, A/A stability, component allowance,
actual vector-capacity, allocator, transient or peak construction/copy/reset/
export memory result exists. Neither the **+448 ns/fish-step** allowance nor the
**1,404 B resident ceiling** is established or inferred from the one-fish assay,
its short runtime, or the unchanged 1,260 B element payload. Final complete-world
performance and lifecycle accounting remain PR 3, as do production activation,
ownership/lifecycle splice, reproduction/feeding/fighting/sharing/reseeding,
pose/export/checkpoint integration and enabled live-page/Turbo verification.

All changes remain uncommitted; `.git` was read-only. Forbidden external trees,
the noise bank and the running study were not accessed. Scratch evidence and
cache files remain under `build_m2b1_pr2/`. Supplied `docs/_ref/` material is
reference input, not an intended implementation commit.

The proposed coordinator split, **after completion and validation**, remains:

1. `Add internal Ocean mechanics and fuel accounting` — energy/mechanics/contact
   kernels, the explicitly clarified boundary, action adapter and focused tests.
2. `Freeze Ocean mechanics assays and deterministic fixtures` — independent
   reference/comparator, completed assay/source harness, actual frozen constants,
   generated fixtures, parity integration, timing/memory tooling and final report.

The second commit is not ready: assay 1 fails; later assays/emitter/fixtures,
parity integration, timing/memory and release checks remain. No module-artifact
commit is proposed without a successful rebuild and understood source-related
byte change. The coordinator supplies commit attribution; no commit, merge,
deploy or rebaseline was performed.

---

## Preserved round-1 report (historical; superseded above)

# M2b1 PR 2 — stopped at gate 2; bootstrap work, not release evidence

The implementation is **incomplete and not ready to commit as a completed PR**.
The requested gate sequence stopped at gate 2 on a correct new full-capacity
reserve test. No calibration was frozen and no fixtures were generated or replaced.
The stop follows the owner's explicit rule to stop when the implementation or a
correct new test fails a gate. Diagnostics after the stop only characterize that
failure; they do not advance the gate sequence.

## Base and prerequisites

Base: `ba6f29c6ee4a04b1ce41b27ab49e81443802968d` (branch `m2b1-pr2`).
The supplied fixed PR 1 includes `d771738` and `de44c8a`.

Gate 1 source audit verified all five required fixes:

1. Coefficient/support traversal copies into real `std::array` objects with
   `std::bit_cast`, without cross-member pointer indexing.
2. LDL checks finite pivots, reciprocals and lower factors; scaled solves validate
   input/output and publish atomically; `evalLoad` validates its whole result and
   clears it on refusal.
3. The double reference independently constructs loaded material, body added mass
   and rotational resistance; its entrywise controls and asymmetric probe remain.
4. `invS3` checks the leading SPD minors and a complete finite inverse atomically.
5. Tensor field metadata declares block-specific TT/TR/RR units.

The audit did not find a missing prerequisite fix and made no PR 1 repair.
Evidence: `build_m2b1_pr2/logs/gate01_prerequisites.md` and
`build_m2b1_pr2/logs/base_identity.json`.

## Gate-2 failure and exact diagnosis

The existing hydro suite passed: **11 test groups, zero failures**.
The new hydro-step suite returned **exit 1: 10 groups passed, two failed**.

The correct `hydro_reserve_transactions` overflow check fails because the neutral
full-capacity energy load lies outside the PR 1 fuel-mass domain by one binary32
ULP:

| Quantity | Binary32 value | Bits |
|---|---:|---|
| `c.energyCapacity` | 45 | `0x42340000` |
| `fuelMass(c.energyCapacity)` = `45/500` | 0.0900000036 | `0x3db851ec` |
| `evalLoad` maximum = `reserveCapacity*(.90*rhoWater)` | 0.0899999961 | `0x3db851eb` |

`evalLoad(c,0,fuelMass(45),L)` refuses. `changeReserve` from 25 E with a
+100 E request consequently refuses instead of accepting 20 E and reporting 80 E
waste. It leaves state, the 25 E ledger and the receipt unchanged, as its atomic
failure contract requires. This is a capacity-domain incompatibility between
PR 1's separately rounded capacity expressions and the required new load path;
it is not a missing one of the five reviewed fixes. No clamp, changed acceptance
bound, capacity-law edit or foundation repair was made after finding it.

A second failure is in a test written during this task: the white-fibre recovery
loop stops after 1,800 substeps, too early for the declared law. The diagnostic
run with a larger observation window establishes:

| Fibre | Peak fill | Zero-work recovery | Analytic recovery |
|---|---:|---:|---:|
| 0 | 251 substeps / 2.00800014 s | 1,819 / 14.552001 s | 14.5454531 s |
| .5 | 251 / 2.00800014 s | 501 / 4.00800037 s | 4 s |
| 1 | no burst capacity | no fatigue to recover | 0 s |

These are **kernel diagnostics, not assay-2 acceptance evidence**. The white-fibre
loop bound needs correction. No own-test retry was taken: the gate did not fail
only because of that test mistake; the correct reserve test also failed. No test
or implementation correction was made after the stop.

The passing new groups include the coupled solve residual, world momentum,
actuators, gas, contact, loaded boundaries, refusals, long run, and printed body
chains. The long run completed 20,000 outer / 40,000 mechanical steps with chain
`2ef1dabecb54c7d2`; the sampled body-number chain was `a64067c3c08f85e5` (85
successfully initialized bodies). These native-only checks are not substitutes
for the prescribed complete fixture case set or native/wasm comparison.

Diagnostic source: `build_m2b1_pr2/diagnose_gate02.cpp`.
Raw failure: `build_m2b1_pr2/logs/gate02_native_hydro_step.log`.
Exact boundary/fatigue output: `build_m2b1_pr2/logs/stop_diagnosis_identity.log`.

## Scope and current implementation

New internal code provides a bootstrap calibration header, reserve parcels and
atomic energy transactions, the analytic motor limiter, pressure/load validation,
outer action adaptation, actuator and gas requests, two mechanical substeps,
coupled angular rails, deterministic hull manifolds, friction and geometric
boundary resolution. The harness owns separate coefficient/support/state/gene/
owner columns and existing Fish ledgers; it retains no Loaded or cold-diagnostic
column and adds no resident per-fish fields.

The focused tests and harness are draft work. Required test coverage is not yet
complete. The trajectory-reference header and its invocation from the PR 1 tool
are also draft, uncompiled and unvalidated; the full independent actuator,
trajectory and sequential-patch comparison obligations remain. The harness's
current refill runs at outer-step boundaries; it does not yet provide exact
25 E maintenance at each incoming mechanical substep for fixed-load assays.

The public `kHydrodynamicsKey` refusal, production OceanWorld stepping/lifecycle,
module includes, `src/core`, rendering, exports, checkpoints, fingerprints,
historical baselines, M2a fixture, and Classic are unchanged. Neither
`ocean_world.hpp` nor `ocean_wasm.cpp` includes the new kernel headers. Read-only
scope checks found no differences in those paths. This is not gate-12 completion.

## Laws and digests (bootstrap, not frozen)

Geometry/material/expression/reference/mechanics/energetics:
**1 / 1 / 1 / 1 / 1 / 1**. Coefficient/support/state ABIs: **1 / 1 / 1**.
`kFrozenThrough = 0`; measured cruise/sustained power bit fields remain zero.
Reference law stays provisional law 1 until an actual assay-2 freeze.

| Digest | Value |
|---|---|
| Constants | `8b9da3b83df66f68` |
| Provisional references | `7a56fddda191de89` |
| Neutral coefficients | `3e8bfae4938384af` |
| Neutral support | `44931eb40f7ec2ef` |
| Existing suite's 117-body coefficient chain | `4de32d320f38bec8` |

No starting constant was calibrated or changed. The new reduced-law paired
induced efficiency is `.75`; it is an explicit starting modeling choice, distinct
from `.35` paired rowing efficiency and the geometry-dependent tail efficiency.
It has not been measured or frozen by assay 3. No geometry, basal anchor, force
ceiling, speed rail or assay acceptance bound was tuned.

## Calibration, fixtures and determinism

All assay results and subcases are **NOT RUN**:

- Assay 1: static buoyancy error <=1e-5, vertical speed <.01, drift <.1 over
  60 s; separate/combined tilts within 1 degree in 10 s; depth targets 96/144
  within 1 u in 60 s; floor rest/friction/release and sinking within 2% of force
  balance. None has acceptance evidence.
- Assay 2: tow at 40/82/108/120/150, free-drive balance within 2%, sustained
  108 +/-5%, actual peak, all fibre/shared-lambda/exhaustion cases. No measured
  sustained or peak speed. The existing suite's analytic peak near 143 u/s is
  provisional, not a free-drive measurement. The fatigue diagnostics above do
  not freeze assay 2.
- Assay 3: steering at 40/82/120, 82 yaw 2.60 +/- .15, fitted radius/sideslip,
  90-degree response, body ordering and >=3 cruiser/manoeuvrer ratio, release
  righting, rail and finite 120 burst windows. No measurements.
- Assay 4: .80 basal, .10 maintenance, .60 motor, 1.50 +/- .02 E/s and 180 +/-
  2.4 E over 120 s; turning/blocked-thrust charges, explained trim/gas work and
  metered subsidies. No calorimetry or fixed-load subsidy windows were run.

No candidate/final calibration manifests or assay windows exist. There is no
`ocean_hydro_assay.cpp` yet and no stage-4 evidence. No new/changed fixture SHA256s
exist. The existing fixtures were left untouched:

| Fixture | SHA256 |
|---|---|
| `tests/fixtures/ocean_hydro_fixture.json` | `e2c080dee4b0de9731bd4f38f5d50241bcb68cc04cc6de1c47b669ed6183db05` |
| `tests/fixtures/ocean_body_fixture.json` | `309071b412405cc4ea3bd2848f360c859f041e8e7ae31428817d3de20d02b5b9` |

The old hydro fixture is not updated to the draft new metadata. No hydro or
mechanics fixture native/wasm/committed equality is claimed. No new independent
reference result, patch-model difference, plain/eye full-suite equality or full
historical matrix/twin counts were measured. The known `life_cap_fixture_s1`
body-twin exception was not reached or verified; it is not used to excuse gate 2.
No OFF baseline was changed.

## Performance and memory

No component timing windows were run; A/A stability and ns/fish-step are
**NOT ESTABLISHED**. No matched whole-world T, replacement H, removed R or
additional lifecycle L was measured. The approximate +448 ns/fish-step allowance
is neither spent nor established by this work. Complete-world median paired
wasm M2/legacy <=1.25 at population 2,000 still belongs to PR 3.

The existing focused suite printed 916 B coefficients, 240 B support, 76 B state,
20 B genes and 8 B owner = **1,260 B element payload**, within the respective
1,024/256/96 and total 1,404 B ceilings. No resident layouts were changed. Actual
vector capacities, allocator overhead, transient workspace sizes, construction,
copy/reset and diagnostic/export peaks have not been measured. Payload alone is
not a memory-gate pass. Timing/memory tooling and benchmark dispatch are not yet
implemented.

Identity: GCC 15.2.0, Emscripten 6.0.4, Node v26.13.0, CMake 3.28.3;
Intel Core i5-10500T, 12 logical CPUs. Native focused flags:
`-O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src`.
Builds ran at nice 19 with no more than two jobs; no timing overlap occurred
because no timing windows were started. The installed offline emsdk was inspected
at `~/opt/emsdk/emsdk_env.sh`; no wasm build/cache population was reached.

## Gate table and logs

All paths below are relative to `build_m2b1_pr2/logs/`. The initial native build
was not timed; that limitation is explicit rather than an estimated duration.
Machine-readable measured commands: `gates.jsonl`.

| Gate / command | Exit/status | Seconds | Log |
|---|---|---:|---|
| 1: five-fix source audit and base/tool identity | PASS by inspection | not timed | `gate01_prerequisites.md`, `base_identity.json` |
| 2 build: `nice -n 19 g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tests/ocean_tests.cpp -o build_m2b1_pr2/ocean_tests_native` | 0 | not timed | `gate02_build.log` |
| 2: `build_m2b1_pr2/ocean_tests_native --only hydro` | 0 | 1.949 | `gate02_native_hydro.log` |
| 2: `build_m2b1_pr2/ocean_tests_native --only hydro_step` | **1** | 3.063 | `gate02_native_hydro_step.log` |
| 2: separate UBSan focused build/runs | NOT RUN after failure | — | — |
| 3: native independent reference | NOT RUN | — | — |
| 4: calibration 1 -> 2 -> 3 -> 4 | NOT RUN | — | — |
| 5: native/wasm hydro fixtures | NOT RUN | — | — |
| 6: full `APP_TWINS=all BODY_TWINS=all` matrix | NOT RUN | — | — |
| 7: component timing/memory | NOT RUN | — | — |
| 8: Ocean rebuild/freshness | NOT RUN | — | — |
| 9: Classic rebuild/freshness | NOT RUN | — | — |
| 10: native serial SFML build/ctest | NOT RUN | — | — |
| 11: module consumers/local TypeScript | NOT RUN | — | — |
| 12: final frozen-scope gate | NOT RUN | — | — |
| Failure diagnostic native build | 0 | 6.109 | `stop_diagnosis_build.log` |
| Failure diagnostic run | 0 | .009 | `stop_diagnosis_run.log` |
| Diagnostic with explicit versions/digest: native build | 0 | 6.728 | `stop_diagnosis_identity_build.log` |
| Diagnostic with explicit versions/digest: run | 0 | .009 | `stop_diagnosis_identity.log` |
| Post-stop read-only frozen-path diff / whitespace inspection | 0 | .022 | `stop_readonly_scope_audit.log` |

The diagnostic build command is the same focused native flags on
`build_m2b1_pr2/diagnose_gate02.cpp`, output `build_m2b1_pr2/diagnose_gate02`.
Commands after the initial build used `run_gate.py`, which unsets native build
variables and places TMPDIR under the scratch root. The extra diagnostic builds
are not retries of gate 2 and did not change functional code.

## Release checks and unchanged modules

Module bytes match the starting hashes below; no module rebuild/freshness pass is
claimed. No pin file was edited.

| File | SHA256 |
|---|---|
| `web/evo_ocean.js` | `77bd5db9cd78973b77921e67f4df946e50655eb3d0318b630231f4fa08d257e3` |
| `web/evo_ocean.wasm` | `6167f939264bc5ba0f74499ef3eb25bdf523321a13a015e775bd4bbecde58f77` |
| `web/evo_boids.js` | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` |
| `web/evo_boids.wasm` | `c1fc4c7a87c6271a4240533fbc3e51400c8028f7a9ec12e976a537448203732b` |
| `web/evo_boids_mt.js` | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` |
| `web/evo_boids_mt.wasm` | `8c7f31ca638a041600bebbf70e12dbef3c2ced9f2004377b574198a247efe268` |

Native ctest/SFML test availability was not established. The prescribed host
Python 3.14 `invasion_tooling` exclusion was not exercised. Module consumers and
existing local npm/TypeScript availability were not checked after the gate stop.
No dependency fetch, network operation or browser was used. No tests are labeled
unavailable offline merely because they were not reached. Live rendering,
checkpoint, exports and Turbo enabled-path checks remain PR 3 obligations.

## Changed files and coordinator handoff

Modified tracked files:

- `src/ocean/hydro_coefficients.hpp`
- `tests/ocean_hydro_tests.hpp`
- `tests/ocean_tests.cpp`
- `tools/ocean_hydro_reference.cpp`

New intended source/documentation files:

- `src/ocean/hydro_calibration.hpp`
- `src/ocean/ocean_energy.hpp`
- `src/ocean/hydro_contact.hpp`
- `src/ocean/hydro_step.hpp`
- `tools/ocean_hydro_harness.hpp`
- `tools/ocean_hydro_trajectory_reference.hpp`
- `tests/ocean_hydro_step_tests.hpp`
- `docs/m2b1_pr2.md`

Scratch evidence and supplied references remain under `build_m2b1_pr2/`; do not
include that directory in coordinator commits. All changes are uncommitted;
`.git` was only read. No other tree, forbidden directory or noise bank was touched.

Before completing PR 2, resolve the legal full-capacity load domain without
silently relaxing a law or refusal; correct the white-fibre test observation
limit; complete focused coverage and UBSan; finish the independent reference and
trajectory/patch comparator; implement exact metered assay load support, the
assay executable, staged emission/freeze and all subcases; generate fixtures only
after the required checks; integrate parity and timing/memory tooling; then run
gates 2–12 in order. Nothing beyond gate 2 is acceptance evidence yet.

PR 3 still owns production activation/configuration, aligned lifecycle ownership,
funded reproduction, feeding/fighting/sharing/reseeding integration, physical
mouth envelope and queries, pose/render/export integration, checkpoint formats
and continuation, enabled fingerprints/full matrix, complete-world performance
and lifecycle memory, and live rendering/checkpoint/export/Turbo verification.
The full PR 3 plan remains the authority for that work; no part was implemented
here.

The proposed coordinator split remains the plan's two commits **after completion
and validation**, not a recommendation to commit this failed bootstrap state:

1. `Add internal Ocean mechanics and fuel accounting` — kernels, contact,
   transactions, action adapter, test support and focused suites.
2. `Freeze Ocean mechanics assays and deterministic fixtures` — completed
   reference/assays, actual frozen constants, generated fixtures, parity,
   timing/memory tooling and final evidence documentation.

No artifact commit is proposed: module rebuilds were not reached and their bytes
are unchanged. The coordinator supplies attribution trailers. No commit, merge,
deploy or rebaseline was performed or authorized by this report.

# Ocean controller split: PR 3, Readouts

Controller-only extraction from main **4bafeb25bca62c4c3a628d97ed70d781f79a6168** (PR #101 merged), on branch `ocean-js-split-3`. All changes remain uncommitted for the coordinator. The pristine base is `build_jsplit3/base/`. No network, browser, C++/Wasm build, merge, deployment, rebaseline, other worktree or running study was involved.

## Inventory and current-base mapping

`web/ocean_readouts.js` registers `window.EvoOceanReadouts = { create: create }`. It owns exactly the requested histograms, HUD, rate history, sampling, wiring-source choice and dashboard attachment. Root retains startup, transactions, frame sequencing and layer coordination.

The plan cites pre-Tour main 294fc8b. All base columns below refer to **current base 4bafeb2 `web/ocean.js`**, mapped by name/content. Destination columns refer to `web/ocean_readouts.js`.

There are **six named inventory functions**, **eight function bodies including their two nested callbacks**, **three rate methods**, and **eight attachment callbacks including the nested family-colour fence callback**: **19 moved function-like bodies total**. `setDrawer` is an existing function reference in the attachment object, not a moved callback. There are **zero moved listener registrations**. The new module has **32 function-like nodes total**: those 19 moved bodies, four phase wrappers, one factory, seven accessors, and the registration IIFE. These counts do not add the nested callbacks twice.

| Function / method / callback | Current base | Readouts |
| --- | ---: | ---: |
| `buildHist` | 2378–2392 | 22–36 |
| `labelHist` | 2393–2396 | 37–40 |
| `rates.reset` | 2401–2401 | 46–46 |
| `rates.push` | 2402–2407 | 47–52 |
| `rates.perSec` | 2408–2413 | 53–58 |
| `updateHud` | 2441–2496 | 62–117 |
| `dash` | 2505–2505 | 122–122 |
| `takeSample` | 2509–2515 | 127–133 |
| `wiringNow` | 2518–2526 | 136–144 |
| `depth` | 3577–3577 | 147–147 |
| `familyColor` | 3579–3579 | 149–149 |
| `colourMode` | 3582–3582 | 152–152 |
| `showFamilyColours` | 3583–3583 | 153–153 |
| `wiring` | 3584–3584 | 154–154 |
| `onOpen` | 3587–3587 | 157–157 |
| `setRecEvery` | 3588–3590 | 158–160 |

The nested HUD callbacks (`g`, the rows mapper) stay inside `updateHud`; the nested engine fence stays inside `familyColor`.

| Owned state / fragment | Current base | Initialization / destination |
| --- | ---: | --- |
| `summary/summaryT` | 2238 | `create()` runs at the original summary declaration; initializers remain `null/0`, Readouts line 8. |
| `dirtyHud/hudT/histRows` | 2377 | `initHud()` at the original declaration; slots declared inertly, assignments stay ordered `true/0/[]`. |
| Complete rate object and its description | 2397–2414 (object 2399–2414) | `initRates()` constructs the same object at the original point, after HUD initialization and before root format helpers/layer state. |
| `sampleBucket` | 2504 | `initRecorder()` at the original position after Inspector's network registration; assigns `-1`. Recorder description, sampling/wiring comments and functions move whole. |
| Complete dashboard attachment | 3576–3591 | `attach()` at the same startup point, after `applyClarity()` and before public handles. Callbacks and `setDrawer` reference retain order. |

Histogram creation remains the existing startup call at base 3457; startup labels remain at 3570; world-size-change labels remain at 638. The ordered root frame remains step → sync → snapshot → sample/fresh → fallback velocity → selection/movement → render → card/fresh → HUD. No allocation/read/fresh order changed.

## What stays in root

The plan's mixed readout/statistics section is not moved as a block:

| Retained unit | Current base | Reason / allowed edit |
| --- | ---: | --- |
| `fmtInt` | 2415 | Shared root formatter; byte-identical. |
| `fmtTime` | 2416 | Shared root formatter; byte-identical. |
| `setHtml` | 2417 | Shared root DOM-write helper; byte-identical. |
| `setTxt` | 2418 | Shared root DOM-write helper; byte-identical. |
| `statOpen` | 2419 | Layers state; declaration unchanged. Readouts reads it through a getter. |
| Card/stat-panel precedence comment and `cardNewer/cardHeld` | 2420–2425 | Layers ownership; unchanged. |
| `setStatPanel` | 2426–2440 | Layers coordination. Only `dash` calls and the HUD flag qualify through Readouts. Its DOM operations, drawer/popover/coach order stay unchanged. |
| Mixed section heading | 2376 | Still describes the root's remaining layer work. |

The first 79 root header lines and every unledgered root byte remain unchanged. Inspector's four card/network phase calls retain their positions after the extracted HUD and before recorder initialization.

## Move ledger

`build_jsplit3/move_ledger.json` records seven complete base fragments (135 source lines), every root edit at its original character offset, and all moved free-variable substitutions with base line and column. It contains **89 moved-body port occurrences**, **64 root identifier qualifications**, **71 root edits total** (the 64 qualifications plus seven fragment replacements), and **four ordered follow-up substitutions** (Inspector owner port, Tour owner port, removal of Tour's summary bridge, and factory wiring). `function_mapping.json` records the table above; `type_edits.json` records every exact type-only replacement.

The following table exhausts the moved-body port substitutions. Repeated line numbers denote separate lexical occurrences. Root's immutable constants and hoisted functions pass by reference; every replaceable binding uses a getter. No getter syncs, refreshes, or invokes another controller.

| Base identifier → port | Count | Current base lines | Access |
| --- | ---: | --- | --- |
| `D` → `ports.D` | 5 | 2394, 2478, 2478, 2480, 3577 | Live root getter |
| `DT` → `ports.DT` | 2 | 2411, 2468 | Original function / immutable value |
| `HO` → `ports.HO` | 2 | 2448, 2514 | Live root getter |
| `M` → `ports.M` | 10 | 2448, 2448, 2448, 2514, 2519, 2521, 2522, 2525, 2525, 3579 | Live root getter |
| `STATS` → `ports.STATS` | 3 | 2452, 2452, 2486 | Original function / immutable value |
| `cString` → `ports.cString` | 2 | 2525, 2525 | Original function / immutable value |
| `colourMode` → `ports.colourMode` | 1 | 3582 | Live root getter |
| `el` → `ports.el` | 2 | 2379, 2460 | Original function / immutable value |
| `engineCall` → `ports.engineCall` | 2 | 3579, 3584 | Original function / immutable value |
| `fmtInt` → `ports.fmtInt` | 12 | 2456, 2465, 2466, 2468, 2470, 2471, 2472, 2475, 2475, 2475, 2477, 2482 | Original function / immutable value |
| `fmtTime` → `ports.fmtTime` | 1 | 2468 | Original function / immutable value |
| `fps` → `ports.fps` | 4 | 2459, 2460, 2460, 2483 | Live root getter |
| `fresh` → `ports.fresh` | 1 | 2450 | Original function / immutable value |
| `has` → `ports.has` | 4 | 2447, 2510, 2519, 3579 | Original function / immutable value |
| `heap` → `ports.heap` | 1 | 2522 | Original function / immutable value |
| `initArgs` → `ports.initArgs` | 2 | 2469, 2469 | Live root getter |
| `inspector` → `ports.inspector` | 1 | 2521 | Stable Inspector instance |
| `lastSteps` → `ports.lastSteps` | 1 | 2481 | Live root getter |
| `lightOn` → `ports.lightOn` | 1 | 2494 | Original function / immutable value |
| `paused` → `ports.paused` | 2 | 2481, 2492 | Live root getter |
| `scene` → `ports.scene` | 2 | 2494, 2494 | Live root getter |
| `setColourMode` → `ports.setColourMode` | 1 | 3583 | Original function / immutable value |
| `setDrawer` → `ports.setDrawer` | 1 | 3585 | Original function / immutable value |
| `setHtml` → `ports.setHtml` | 1 | 2484 | Original function / immutable value |
| `setPop` → `ports.setPop` | 1 | 3587 | Original function / immutable value |
| `setTxt` → `ports.setTxt` | 5 | 2456, 2457, 2458, 2459, 2495 | Original function / immutable value |
| `showSpeedCap` → `ports.showSpeedCap` | 1 | 2461 | Original function / immutable value |
| `speed` → `ports.speed` | 1 | 2481 | Original function / immutable value |
| `statOpen` → `ports.statOpen` | 1 | 2462 | Live root getter |
| `statsLen` → `ports.statsLen` | 1 | 2514 | Live root getter |
| `tankShowsFamily` → `ports.tankShowsFamily` | 1 | 3582 | Original function / immutable value |
| `tour.hideCoach` → `ports.hideCoach` | 1 | 3587 | Lazy Tour call |
| `turboState` → `ports.turboState` | 6 | 2446, 2493, 2520, 3584, 3589, 3589 | Live root getter |
| `turboStats` → `ports.turboStats` | 2 | 2482, 2482 | Live root getter |
| `turboView` → `ports.turboView` | 1 | 2446 | Live root getter |
| `turboWiring` → `ports.turboWiring` | 1 | 2520 | Original function / immutable value |
| `turboWorker` → `ports.turboWorker` | 2 | 3589, 3589 | Live root getter |
| `updateKeysLegend` → `ports.updateKeysLegend` | 1 | 2461 | Original function / immutable value |

Root's exact identifier qualifications are enumerated here; property keys such as `summary`, `rates` and `sampleBucket` in transaction objects remain literal.

| Root identifier → Readouts member | Count | Current base lines |
| --- | ---: | --- |
| `buildHist` → `readouts.buildHist` | 1 | 3457 |
| `dash` → `readouts.dash` | 39 | 475, 475, 475, 485, 485, 485, 1969, 1969, 1969, 2342, 2342, 2342, 2368, 2435, 2435, 2435, 2694, 2694, 2750, 2750, 2782, 2782, 2782, 2832, 2832, 2832, 2832, 2913, 2913, 2925, 2925, 2952, 2952, 3083, 3083, 3642, 3642, 3659, 3659 |
| `dirtyHud` → `readouts.dirtyHud` | 8 | 394, 394, 659, 2253, 2258, 2439, 2606, 2919 |
| `labelHist` → `readouts.labelHist` | 2 | 638, 3570 |
| `rates` → `readouts.rates` | 3 | 475, 486, 657 |
| `sampleBucket` → `readouts.sampleBucket` | 4 | 475, 486, 656, 2750 |
| `summary` → `readouts.summary` | 5 | 433, 476, 487, 2369, 2747 |
| `takeSample` → `readouts.takeSample` | 1 | 2898 |
| `updateHud` → `readouts.updateHud` | 1 | 2922 |

The qualifications initially include the old Inspector and Tour bridge lines; the four recorded follow-ups replace those bridges:

- Inspector's root `dirtyHud` getter/setter becomes `get readouts() { return readouts; }`. Inspector is created at base 375, before Readouts at 2238, so this owner-reference getter defers the lookup without changing either construction point. Its only consumer write becomes `ports.readouts.dirtyHud = true` at Inspector line 101. There is no copied HUD flag or transitional flag port.
- Tour receives `readouts: readouts`; `get summary()` and the separate `dash` function port are removed. Its two summary reads and two dashboard calls at Tour lines 19/22 become `p.readouts.summary` / `p.readouts.dash()`. The rest of Tour and Inspector is character-identical to base.
- Readouts' `summary`, `dirtyHud` and `sampleBucket` have live getter/setter pairs; `rates` has a live object getter. Root transaction capture/restore retains `q.slice()` and summary's reference semantics, assignment order, and the existing choices about which timestamps are reset. There is no generic context/capture object.
- The new module uses the same engine fence, receiver calls, fallback values, callback laziness and worker phase guard. Family colour reads the current `M`; `setRecEvery` reads the current worker; `wiringNow` checks the current Turbo phase and uses that phase's source.

Concrete owner, factory, ports, rate, wiring and dashboard types are declared in `web/types.d.ts`; the new file carries `// @ts-check` and is listed in `tsconfig.json`. The new namespace is the only additional controller global.

Type-only normalizations, exhaustively encoded in the audit:

- Histogram label assignment retains the original numeric value and browser DOM coercion. `Math.round(ports.D * i / 8)` gains the inert cast `/** @type {string} */ (/** @type {unknown} */ (EXPRESSION))`; it does not call `String` or change the assigned value.
- The two already-guarded Turbo `su[0]/su[1]` reads cast `su` to `number[]`, since TypeScript does not correlate it with `tv` across the earlier conditional assignment.
- The four already-guarded repeated `dash()` expressions for `.every()`, `.push()`, `.famK` and `.attach()` cast to `OceanDashboard`. They retain call counts, receivers and short-circuiting.
- JSDoc types annotate the private slots, factory signature, `updateHud` parameters and `takeSample` parameter. Initializer bodies and moved code otherwise remain character-for-character after the ledgered ports.

Both controller VM loaders, Turbo's private `wiringNow` seam, the common HTML dependency consumer list and the render evidence hash manifest include Readouts. The existing source scanners for start-door restrictions, memory installation and URL metadata still inspect unchanged root implementations. No scanner for a moved function remains aimed at root. Mock-three's scene-only script list and entire file/GOLDEN remain unchanged. A separate exact-delta check confirms that existing test assertions, the Turbo section registry, runner, cleanup and rejection check are unchanged.

## Plan deviations

- No behavioral inventory deviation. Four explicit phase helpers and the summary-position factory preserve the existing initializer and attachment points. Inspector's owner-reference getter is needed because Inspector is constructed first; it replaces its transitional flag port.
- Checked JavaScript needs the finite inert casts and annotations above, following PRs 1–2. No blanket `any`, suppression, cleanup, UI change or lifecycle redesign was added.
- Only introduced globals/APIs are declared, without speculative future-owner declarations. Ownership spans are mapped by content; root's header and unassigned separators remain intact.
- No preparation commit is needed. Existing test loaders/private seams are updated atomically with extraction; the prior PRs already supplied the corrected off-image query support.

## Server gate record

The pre-extraction base record is `build_jsplit3/logs/base.json`: commit above, Node **v26.13.0**, npm **11.20.0**, branch, six SHA-256 values and equality with the pristine base. Commands run through `python3 build_jsplit3/run_gate.py NAME CWD COMMAND...`, which executes at **nice 19**, `JOBS=2`, `BUILD_JOBS=2`, `OMP_NUM_THREADS=2`, `OPENBLAS_NUM_THREADS=2`, `MKL_NUM_THREADS=2`, `UV_THREADPOOL_SIZE=2`, and `NODE_OPTIONS=--v8-pool-size=2`. Turbo runs are sequential. At most two top-level jobs/at most two threads per job were allowed; the unchanged lock unit test internally launches its existing lightweight contender processes. No browser was started.

The extraction audit checks all 19 moved bodies through complete-function/phase character and token equality, all seven slots, four phase bodies, exact registration/factory/API shells, the exact root edit ledger, Tour/Inspector owner substitutions, no orphaned or duplicate names, and all 15 live root getters. A throwing-host VM verifies registration/construction without DOM, timer, storage, randomness, performance or port access; small owner probes replace the engine and worker, switch wiring sources, and exercise the early throttled HUD return. Root's exact ledger also preserves every retained listener/timer registration and phase. This is source/targeted-owner evidence, not a substitute for browser integration.

| Command | Exit / status | Wall seconds | Log |
| --- | --- | ---: | --- |
| Pre-extraction Python record (`git rev-parse HEAD`, branch, `node --version`, `npm --version`, six hashes) | 0 | 0.191 | `build_jsplit3/logs/base.json` |
| `node build_jsplit3/audit.cjs` | 0 | 2.254 | `build_jsplit3/logs/audit.log` |
| `node tests/ui_common_tests.cjs` | 0 | 0.115 | `build_jsplit3/logs/ui_common_tests.log` |
| `node tests/ui_parity_harness_tests.mjs` | 1 ENVIRONMENT-BLOCKED | 10.37 | `build_jsplit3/logs/ui_parity_harness_tests.log` |
| `node build_jsplit3/environment.cjs` | 1 ENVIRONMENT-BLOCKED | 0.127 | `build_jsplit3/logs/ui-parity-environment.log` |
| `node tests/ui_inspector_tests.cjs` | 0 | 3.676 | `build_jsplit3/logs/ui_inspector_tests.log` |
| `node tests/ocean_appearance_slots_tests.cjs` | 0 | 0.68 | `build_jsplit3/logs/ocean_appearance_slots_tests.log` |
| `node tests/ocean_shader_slots_tests.cjs` | 0 | 0.253 | `build_jsplit3/logs/ocean_shader_slots_tests.log` |
| `node tests/ocean_materials_tests.cjs` | 0 | 0.458 | `build_jsplit3/logs/ocean_materials_tests.log` |
| `node tests/ocean_render_opt_tests.cjs` | 0 | 0.112 | `build_jsplit3/logs/ocean_render_opt_tests.log` |
| `node tests/ocean_mock_three_tests.mjs` | 0 | 32.586 | `build_jsplit3/logs/ocean_mock_three_tests.log` |
| `node tests/ocean_perf_tests.cjs` | 0 | 0.086 | `build_jsplit3/logs/ocean_perf_tests.log` |
| `node tests/ocean_render_perf_lock_tests.mjs` | 0 | 15.566 | `build_jsplit3/logs/ocean_render_perf_lock_tests.log` |
| `node tests/ocean_render_query_tests.cjs` | 0 | 0.06 | `build_jsplit3/logs/ocean_render_query_tests.log` |
| `npm ci --offline --cache $ROOT/build_jsplit3/npm_cache --no-audit --no-fund` | 0 | 0.762 | `build_jsplit3/logs/npm-ci.log` |
| `npx --offline --cache $ROOT/build_jsplit3/npm_cache tsc -p tsconfig.json` | 0 | 4.173 | `build_jsplit3/logs/types.log` |
| `node tests/ocean_turbo_handoff.js` (cwd `build_jsplit3/base`) | 0 | 326.354 | `build_jsplit3/logs/turbo-base.log` |
| `node tests/ocean_turbo_handoff.js` | 0 | 329.081 | `build_jsplit3/logs/turbo-head.log` |
| `bash wasm/build_site.sh` | 0 | 0.711 | `build_jsplit3/logs/site-build.log` |
| `python3 build_jsplit3/check_site.py` | 0 | 0.141 | `build_jsplit3/logs/site-check.log` |
| `python3 build_jsplit3/verify_unchanged.py` | 0 | 0.122 | `build_jsplit3/logs/unchanged.log` |
| `python3 build_jsplit3/verify_test_deltas.py` | 0 | 0.05 | `build_jsplit3/logs/test-deltas.log` |
| `python3 build_jsplit3/verify_evidence.py` | 0 | 0.054 | `build_jsplit3/logs/turbo-evidence.log` |
| `node --check tests/ocean_render_browser.mjs` | 0 | 0.058 | `build_jsplit3/logs/browser-manifest-syntax.log` |
| `node $ROOT/build_jsplit3/audit.cjs $ROOT/build_jsplit3/mutants/a-stale-engine` | 1 expected rejection | 1.229 | `build_jsplit3/logs/mutant-a-stale-engine.log` |
| `node $ROOT/build_jsplit3/audit.cjs $ROOT/build_jsplit3/mutants/b-stale-worker` | 1 expected rejection | 1.178 | `build_jsplit3/logs/mutant-b-stale-worker.log` |
| `node $ROOT/build_jsplit3/audit.cjs $ROOT/build_jsplit3/mutants/c-live-wiring-only` | 1 expected rejection | 1.182 | `build_jsplit3/logs/mutant-c-live-wiring-only.log` |
| `node $ROOT/build_jsplit3/audit.cjs $ROOT/build_jsplit3/mutants/d-early-rates` | 1 expected rejection | 1.154 | `build_jsplit3/logs/mutant-d-early-rates.log` |
| `node $ROOT/build_jsplit3/audit.cjs $ROOT/build_jsplit3/mutants/e-no-hud-throttle` | 1 expected rejection | 0.928 | `build_jsplit3/logs/mutant-e-no-hud-throttle.log` |
| `python3 $ROOT/build_jsplit3/check_site.py $ROOT/build_jsplit3/mutants/f-missing-built-tag` | 1 expected rejection | 0.214 | `build_jsplit3/logs/mutant-f-missing-built-tag.log` |
| `python3 build_jsplit3/mutations.py` | 0 | 6.266 | `build_jsplit3/logs/mutations.log` |
| `node build_jsplit3/audit.cjs` | 0 | 2.189 | `build_jsplit3/logs/audit-final.log` |
| `python3 build_jsplit3/verify_unchanged.py` | 0 | 0.117 | `build_jsplit3/logs/unchanged-final.log` |

`$ROOT` means this worktree's absolute path. Full raw command arrays, actual cwd and wall times are retained in `build_jsplit3/logs/gates.jsonl`.

The UI parity harness unit command is **ENVIRONMENT-BLOCKED, not a pass**. The exact original command is `node tests/ui_parity_harness_tests.mjs`. The diagnostic records `spawnSync /home/harit/opt/node-v26.13.0-linux-x64/bin/node EPERM` (errno −1), empty child stdout/stderr, for `node tests/ui_parity_browser.mjs --plan --sets S0,S2`. No workaround or test modification was applied; rerun the original command outside this sandbox.

Development tooling corrections before acceptance: the first draft extraction range included the first line of the following root comment, corrected before any acceptance gate; the draft mapping initially overwrote attachment `colourMode` with the later benchmark member, corrected to retain the first occurrence before report generation. The development type checker exposed the numeric DOM write and nullable repeated reads, addressed only by the finite casts above. No acceptance gate failed because of an own-script mistake. The audit was subsequently strengthened to make performance/randomness access throw during registration/construction; its final positive run is included. No production code changed after the initial Node/type gates.

## Turbo, built site and protected artifacts

- **Base: 604/604**, runner 326.1 s; full command, no subset arguments.

- **Head: 604/604**, runner 328.8 s; full command, no subset arguments.

The final evidence verifies identical section-heading sequences (79), exit 0 on both sides, all sections/cleanup and the final successful `no unhandled promise rejection` check. Scene recording is **59/59**, unchanged SHA prefix **ff2f626dc192c801** (465 frames); the whole scene test including GOLDEN is protected.

Site assembly adds Readouts to `SRC`, publishes `OCREADOUTS`, rewrites its literal script tag and raises Ocean **21 → 22**; Classic/body viewer stay **13/6**. Source/built synchronous order is dashboard → Readouts → Inspector → Tour → root → guide. No new `EVO_ASSETS` entry is needed.

The built-site checker verifies a single `assets/ocean_readouts.<12 lowercase hex>.js` tag in each Ocean alias, source/built order, bytes equal to source, every published asset's SHA-256 prefix matching its name, no bare controller URLs, byte-identical `index.html/ocean.html`, Classic/body routes and the Classic redirect, plus local script/style/image/engine/worker/helper/Three/body-fixture resolution. Existing `data:` resources and development-only `mock: ocean_mock.js` are handled explicitly. Runtime loading, HTTP status and headers remain laptop work.

Protected-path verification checks `git diff --check`, six module hashes against the base record and zero diff in `src/` (including plane headers), Wasm C++ wrappers, baselines, fixtures and the entire mock-three scene test. No generated engine module was edited or rebuilt.

| Module | Base = head SHA-256 |
| --- | --- |
| `web/evo_boids.js` | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` |
| `web/evo_boids.wasm` | `d05c4442e15d6850aeece60e52c2a69289d10a2d39fd17538b2347123be0a99b` |
| `web/evo_boids_mt.js` | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` |
| `web/evo_boids_mt.wasm` | `1c86e3d2a8c043e17ab1e75004ad37d9d20a70ce5498a80e4ae4bf4fdd8a703b` |
| `web/evo_ocean.js` | `8bdce72bd8991c6e88768712b60cec9b7dd0cf22335d82ebe67f40cef6d91059` |
| `web/evo_ocean.wasm` | `e55a4fcb2e7c2e737c6f0cc838c783237ba138336f1162ab4ddf037468b5f2f1` |

Published Readouts asset: `assets/ocean_readouts.4227ab530831.js`, full SHA-256 `4227ab53083149102f00c0de57411e7e5928a55cdc3e128249b0474d953248d2`.

Line counts: `ocean.js` **3692 → 3580** (−112); new `ocean_readouts.js` **171**; Inspector **457 → 457**; Tour **189 → 189**. Root + Readouts is **3692 → 3751** (+59); all four controller files together are **4338 → 4397** (+59). The extra lines provide the factory, phases, ports, accessors and types.

## Mutation sensitivity

`python3 build_jsplit3/mutations.py` mutates six independent disposable copies only under `build_jsplit3/mutants/`; head/base files stay untouched. Each expected nonzero gate exit is recorded individually in the table and `build_jsplit3/logs/mutation-results.json`.

| Requested mutation | Rejecting server gate | Diagnostic |
| --- | --- | --- |
| (a) Family colour uses `capturedM` taken at attachment | Extraction audit | Complete attachment phase differs. |
| (b) Recording interval uses `capturedWorker` taken at attachment | Extraction audit | Complete attachment phase differs. |
| (c) Remove the worker branch, always read live wiring | Extraction audit | `wiringNow` token-body mismatch. |
| (d) Construct rate-history object during module registration, reuse it in `initRates` | Extraction audit | Complete rate-initialization phase differs; registration shell also prohibits it. |
| (e) Delete HUD dirty/throttle guard and timestamp update | Extraction audit | `updateHud` token-body mismatch. |
| (f) Remove Readouts' hashed script tag from both built aliases | Built-site checker | Readouts missing/repeated/bare tag. |

All six requested categories are rejected by established server gates. These are source/packaging sensitivity results; they do not claim that existing runtime Node tests alone observe every interaction. No requested mutant escapes a server gate, so no uncaught-mutant browser finding remains. Required browser acceptance is still pending.

## Scratch tooling adaptations

- `extract.cjs` adapts PR 2's symbol-aware TypeScript qualification/range ledger to six Readouts functions, seven current-base fragments, the explicit HUD/rates/recorder/attachment phases and current owner ports. No PR 2 line offset was reused.
- `audit.cjs` adapts the exact-body/root/owner/VM strategy for rates, attachment and the four phases; it adds concrete replaced-engine/worker, dual-wiring and HUD-throttle probes, plus full module shell/count checks. `type_edits.py/json` isolates the finite normalizations.
- `mapping.cjs` adds rate methods and attachment callback ranges; `wire.py` covers HTML, publishing, loaders and owner-port/type rewiring. `readouts_types.txt` supplies this owner's concrete declarations. The cached TypeScript compiler/libraries were unpacked into `tmp/` for development only before the required offline npm gate.
- `run_gate.py` changes only the scratch prefix. `node_gates.py` retains the plan's ten commands plus the existing render-query regression command; after the UI harness EPERM diagnostic, it resumes at the remaining commands rather than classifying a generic failure as blocked. `turbo_gates.py` changes only the scratch prefix.
- `check_site.py` adds Readouts before Inspector, changes the assertions to 22/13/6 and checks `OCREADOUTS/n22`. `verify_unchanged.py` changes the scratch prefix; `verify_test_deltas.py` adds exact test-loader/private-seam/manifest delta checking. `environment.cjs` is reused unchanged.
- `mutations.py` uses this owner's six requested faults on copies. `write_report.py` generates this report from the measured records and mapping. PR 2's report writers/types scripts were not reused as evidence for this owner.

## Laptop commands and interactions (not run on this server)

Use the candidate's same harness/fixtures for both sides. Configure the laptop's `PLAYWRIGHT`, `BRAVE_EXE` and machine-wide `BROWSER_LOCK` as usual. Use fresh output folders when rerunning; do not deploy. Serve base, head and assembled site in separate terminals:

```bash
python3 wasm/serve.py build_jsplit3/base 8261
python3 wasm/serve.py . 8262
python3 wasm/serve.py dist 8263

# Rerun the environment-blocked server unit command outside the sandbox.
node tests/ui_parity_harness_tests.mjs

# UI identity: strict comparison, including S3 responsive Inspector cases.
node tests/ui_parity_browser.mjs --base http://localhost:8261 --layout source --sets S0,S2,S3 --expect record --out build_jsplit3/laptop/ui-before
node tests/ui_parity_browser.mjs --base http://localhost:8262 --layout source --sets S0,S2,S3 --out build_jsplit3/laptop/ui-after
node tests/ui_parity_browser.mjs --compare build_jsplit3/laptop/ui-before build_jsplit3/laptop/ui-after --sets S0,S2,S3 --out build_jsplit3/laptop/ui-diff

# Site-layout smoke takes the lock internally.
node tests/ui_parity_browser.mjs --base http://localhost:8263 --layout site --smoke --out build_jsplit3/laptop/site-smoke
```

Render-browser and body GPU need the external lock; do not wrap internally locking tools:

```bash
locked_node() {
  node --input-type=module -e 'import { acquire } from "./tools/ocean_render_perf/lock.mjs"; import { spawn } from "node:child_process"; const release = await acquire("ocean.js split PR3 checks"); try { const code = await new Promise((resolve, reject) => { const child = spawn(process.execPath, process.argv.slice(1), { stdio: "inherit" }); child.on("error", reject); child.on("exit", c => resolve(c ?? 1)); }); process.exitCode = code; } finally { release(); }' "$@"
}

# A/A first: base vs the same base; reference policy explicitly on both roles.
locked_node tests/ocean_render_browser.mjs --base http://localhost:8261/web --main-base http://localhost:8261/web --parts offimage --query renderOpt=0 --main-query renderOpt=0 --out build_jsplit3/laptop/offimage-aa

# Then base vs head, retaining both explicit policy queries and all tolerances.
locked_node tests/ocean_render_browser.mjs --base http://localhost:8262/web --main-base http://localhost:8261/web --parts offimage --query renderOpt=0 --main-query renderOpt=0 --out build_jsplit3/laptop/offimage-ab

locked_node tests/ocean_render_browser.mjs --base http://localhost:8262/web --parts correctness,slots,noperf,missing,faults,timer,beam,iframe,gate --out build_jsplit3/laptop/render

# Record the known reference-command failures on base, then compare head.
locked_node tests/ocean_render_browser.mjs --base http://localhost:8261/web --parts correctness,iframe,gate --query renderOpt=0 --out build_jsplit3/laptop/reference-base
locked_node tests/ocean_render_browser.mjs --base http://localhost:8262/web --parts correctness,iframe,gate --query renderOpt=0 --out build_jsplit3/laptop/reference-head

locked_node tests/ocean_body_gpu.mjs --base http://localhost:8262

# Source-layout page smoke takes the lock internally.
node tools/ocean_render_perf/smoke.mjs --web http://localhost:8262/web --root http://localhost:8262
```

The coordinator reports that the reference command has three **live decoded texture** failures identically on main: reference policy never builds the decoded cache. Compare that command against base; do not attribute those existing failures to this extraction or relax the checks. Off-image A/A and A/B still require matching reference policies. Body GPU's real-controller bridge uses source `/web/ocean.html`; site-layout smoke covers built routes. Plan §5 E–I is skipped on this server; no deployment is requested.

Readouts interaction list for the coordinator:

- HUD numbers and all histograms while running and paused; verify dirty updates and half-second throttling.
- Stats panel and dashboard with a live recording; family colours remain current.
- Change recording interval while live and during Turbo; new interval reaches the current worker.
- Turbo in/out: Brains wiring switches between worker/live sources; numbers and recording follow the owned world.
- New world and Replay: engine replacement leaves family colours and readouts attached to the current engine. New world draws a `Math.random` seed, so subsequent live readings are not comparable between independent runs; use fixed/replay setups for identity captures.
- Phone layout, stats/card precedence, drawer/dashboard transitions and touch controls.

## Proposed commit split (coordinator only)

1. **Atomic extraction:** new Readouts module; root delegations/phases; Inspector/Tour owner ports; concrete types and checked-file entry; HTML and hashed publisher; both VM loaders/private seam; dependency consumer list and render hash manifest.
2. **Documentation:** `docs/ocean_js_split_pr3_report.md`.

No preparation commit is needed. Keep `build_jsplit3/`, logs, disposable mutants, node_modules and dist excluded. The coordinator supplies the attribution trailer and makes commits; this work leaves `.git` untouched. All laptop/browser acceptance remains pending; this report does not claim merge readiness.

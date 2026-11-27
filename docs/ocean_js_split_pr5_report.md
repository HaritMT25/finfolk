# Ocean controller split: PR 5, Layers

Controller-only extraction from main **33f36d40c1165cf5c03ff71e85fe8048b6ef924f** on `ocean-js-split-5`. Server Node **v26.13.0**, npm **11.20.0**. The coordinator's pristine base is `build_jsplit5/base/`. All changes are uncommitted; the coordinator owns commits and laptop acceptance. No network, browser, C++/Wasm build, merge, deployment, rebaseline, other worktree or running study was involved.

## Inventory and current-base mapping

`web/ocean_layers.js` registers `window.EvoOceanLayers = { create: create }`. It owns popovers and their focus-return object, stats/card arbitration, drawer/insets and responsive listeners, the complete private sheet-drag IIFE, the readout toggle, and shared tooltips. The plan cites pre-Tour main 294fc8b; every base span below is current **33f36d4** `web/ocean.js`, matched by name/content rather than by an offset.

| Function | Plan (294fc8b) | Current base | Layers |
| --- | --- | --- | --- |
| `setPop` | 2367–2382 | 2352–2367 | 30–45 |
| `closePop` | 2383–2386 | 2368–2371 | 46–49 |
| `togglePop` | 2387 | 2372 | 50 |
| `placePop` | 2390–2396 | 2375–2381 | 53–59 |
| `setStatPanel` | 2484–2498 | 2410–2424 | 74–88 |
| `updateInsets` | 3415–3429 | 2969–2983 | 92–106 |
| `setDrawer` | 3433–3441 | 2987–2995 | 111–119 |
| `onWideChange` | 3449–3456 | 3003–3010 | 127–134 |
| `hideTip` | 3499 | 3053 | 180 |
| `showTip` | 3500–3515 | 3054–3069 | 181–196 |
| `attachTip` | 3516–3531 | 3070–3085 | 197–212 |

| State / listener / IIFE | Current base | Layers phase / treatment |
| --- | --- | --- |
| `POPS/openPop/popOpener` and description | 2342–2344 | `initPop`, 23–25; factory and phase called at this original point |
| Popover outside-pointer | 2382–2384 | `registerPopOutside`, 60–64 |
| `statOpen`, `cardNewer/cardHeld` and description | 2403–2409 | `initStats`, 65–73 |
| `drawerEl/menuBtn` | 2986 | `initDrawer`, 108–110 |
| Wide-query change; menu/close clicks | 3011–3014 | `registerDrawer`, 135–169; statements in original order |
| Complete sheet-drag IIFE with `down/move/up` and `forEach` | 3015–3039 | IIFE 140–164 inside `registerDrawer`; `start/grip/head` stay local to that installation |
| Readout toggle and stats outside-pointer | 3040–3043 | End of `registerDrawer`, 165–168 |
| Tooltip DOM creation and `tipTimer/tipFor` | 3045–3052 | `initTips`, 171–179; no earlier host operation |
| Tooltip scroll and outside-pointer | 3086–3089 | `registerTips`, 213–218 |

The factory reads no port and performs no host operation. Its typed slots have no initializers. The root calls `initPop` immediately after constructing it, at the original popover-state declaration; `UI.returnPoint()` therefore runs at its original point. Other initializer and listener phases replace precisely their original statements. Assignment phases retain declarator order. The drag IIFE is installed exactly once by root, and its state remains inside that IIFE.

## What stayed and why

Root retains `pointerBlur` (base 2345–2347), shared formatting/DOM writers (2399–2402), keyboard handling and the resize listener inside `wireInput`, controls and popover trigger registrations, Setup, start questions/menu, startup and frame sequencing. Calls/references to moved names are qualified at their existing sites. The source header, separators and every other root byte are unchanged apart from the exact delegation/port ledger. Setup keeps all #94 text in `CFG.TIPS`; `makeField` calls `layers.attachTip(row, key)`. No second tooltip table exists. The local row tip captured *by each attachTip call* stays as in base; the table is looked up live on each call.

Inspector, Readouts, Display and Tour retain their logic and initialization order. Inspector, Display and Readouts are constructed before Layers, so each receives `get layers() { return layers; }`. Tour is constructed after Layers and receives `layers: layers`. Transitional root Layers state getters/function ports are removed. Owner APIs expose the same current state; no getter syncs, allocates or refreshes.

## Move ledger

The reviewable mechanical record is `build_jsplit5/move_ledger.json`: seven base fragments, all base offsets/ranges, moved-body port occurrences with original line/column, root edits and nine ordered follow-ups, plus existing-owner substitutions. `function_mapping.json` contains named function, phase and listener mappings; `wire_ledger.json` records all other file substitutions; `type_edits.json` is the finite normalization list.

There are **51 moved-body port substitutions**, **48 provisional root identifier qualifications**, **55 base-offset root edits** (48 qualifications + 7 fragment replacements), **9 ordered root follow-ups**, and **17 existing-owner port occurrences**. The follow-ups replace transitional qualified getters/function ports with owner access; provisional qualifications inside those removed lines are included in the 48.

| Moved identifier → port | Count | Base lines (repeated = distinct occurrences) | Access |
| --- | --- | --- | --- |
| `CFG` → `ports.CFG` | 1 | 3071 | Live getter |
| `UI` → `ports.UI` | 1 | 2344 | Original function / immutable binding |
| `asking` → `ports.asking` | 1 | 2992 | Live getter |
| `compactMQ` → `ports.compactMQ` | 1 | 2973 | Original function / immutable binding |
| `el` → `ports.el` | 15 | 2356, 2357, 2365, 2376, 2378, 2413, 2414, 2974, 2975, 2986, 2986, 3007, 3014, 3016, 3040 | Original function / immutable binding |
| `hideAsk` → `ports.hideAsk` | 1 | 2992 | Original function / immutable binding |
| `lastPointer` → `ports.lastPointer` | 3 | 3074, 3078, 3081 | Live getter |
| `panelsEl` → `ports.panelsEl` | 1 | 3086 | Live getter |
| `readouts` → `ports.readouts` | 9 | 2362, 2362, 2362, 2419, 2419, 2419, 2423, 2988, 2988 | Live getter |
| `scene` → `ports.scene` | 3 | 2970, 2982, 2994 | Live getter |
| `setStartMenu` → `ports.setStartMenu` | 1 | 2992 | Original function / immutable binding |
| `tour` → `ports.tour` | 3 | 2364, 2421, 2993 | Live getter |
| `wideMQ` → `ports.wideMQ` | 11 | 2363, 2379, 2420, 2977, 3004, 3011, 3011, 3012, 3012, 3018, 3059 | Original function / immutable binding |

`scene`, `asking`, `lastPointer`, `panelsEl`, `CFG`, `readouts` and `tour` are all supplied by live getters. The last two defer owner lookup and retain live access to `dirtyHud` and dashboard methods. Immutable `UI`, `wideMQ`, `compactMQ` and the root's original `el/setStartMenu/hideAsk` functions pass by reference. There is no generic context object.

Exact root identifier qualifications before removal of transitional lines:

| Identifier → `layers` member | Count | Current base lines |
| --- | --- | --- |
| `POPS` → `layers.POPS` | 3 | 2902, 2903, 3155 |
| `attachTip` → `layers.attachTip` | 1 | 772 |
| `cardHeld` → `layers.cardHeld` | 2 | 402, 402 |
| `cardNewer` → `layers.cardNewer` | 2 | 401, 401 |
| `closePop` → `layers.closePop` | 2 | 2873, 3160 |
| `drawerEl` → `layers.drawerEl` | 6 | 1292, 1332, 1582, 2390, 2876, 2906 |
| `hideTip` → `layers.hideTip` | 1 | 1084 |
| `openPop` → `layers.openPop` | 2 | 2389, 2873 |
| `placePop` → `layers.placePop` | 1 | 2962 |
| `setDrawer` → `layers.setDrawer` | 7 | 298, 1582, 2262, 2274, 2388, 2876, 2906 |
| `setPop` → `layers.setPop` | 7 | 2262, 2274, 2905, 2906, 2907, 3162, 3163 |
| `setStatPanel` → `layers.setStatPanel` | 3 | 385, 2877, 2907 |
| `statOpen` → `layers.statOpen` | 5 | 392, 2281, 2390, 2877, 2907 |
| `togglePop` → `layers.togglePop` | 3 | 2902, 2903, 3157 |
| `updateInsets` → `layers.updateInsets` | 3 | 2960, 2962, 3371 |

| Existing owner file | Exact substitution | Occurrences |
| --- | --- | --- |
| `web/ocean_inspector.js` | `ports.statOpen` → `ports.layers.statOpen` | 2 |
| `web/ocean_inspector.js` | `ports.cardNewer` → `ports.layers.cardNewer` | 2 |
| `web/ocean_inspector.js` | `ports.cardHeld` → `ports.layers.cardHeld` | 3 |
| `web/ocean_inspector.js` | `ports.setStatPanel` → `ports.layers.setStatPanel` | 1 |
| `web/ocean_readouts.js` | `ports.statOpen` → `ports.layers.statOpen` | 1 |
| `web/ocean_readouts.js` | `ports.setDrawer` → `ports.layers.setDrawer` | 1 |
| `web/ocean_readouts.js` | `ports.setPop` → `ports.layers.setPop` | 1 |
| `web/ocean_display.js` | `ports.setDrawer` → `ports.layers.setDrawer` | 1 |
| `web/ocean_display.js` | `ports.setPop` → `ports.layers.setPop` | 1 |
| `web/ocean_tour.js` | `p.openPop` → `p.layers.openPop` | 1 |
| `web/ocean_tour.js` | `p.statOpen` → `p.layers.statOpen` | 1 |
| `web/ocean_tour.js` | `p.drawerEl` → `p.layers.drawerEl` | 1 |
| `web/ocean_tour.js` | `p.setDrawer` → `p.layers.setDrawer` | 1 |

The moved named functions use no `this` of their own; owner-member calls and unbound callback references preserve behavior. Ordinary DOM callbacks retain their receiver. In particular `setDrawer` still calls `updateInsets()` immediately, then `setTimeout(updateInsets, 320)`; `closePop` still restores its return point with the supplied keyboard flag. No timer, event phase or focus rule changes.

Concrete owner/port/tooltip types and the global are in `web/types.d.ts`. `OceanScene.setInsets` is declared with its four numeric sides. The new module starts with `// @ts-check` and is in `tsconfig.json`. The opaque `asking` port is used only for its existing truthiness check.

Type-only body edits, all reversed by the audit before character/token comparison:

- Five dashboard-result casts to `OceanDashboard`, on base's guarded repeated `dash()` calls; no call is added, cached or removed.
- Five casts of `e.target` to `Element`, preserving the original `.closest` expressions and short-circuit checks.
- One cast of `.sheet-head` to `HTMLElement`, preserving the original query in the drag IIFE.
- One `@this {HTMLElement}` annotation on the menu-button callback; it remains an ordinary function.

Loaders/scanners updated: Turbo VM loader and its injected live `openPop/statOpen` accessors; Inspector real-page VM loader; common HTML dependency list; render-browser evidence hash manifest. The Turbo URL-import slice, memory-install and start-door scanners and section registry/runner/cleanup stay unchanged. Mock-three's scene-only script list, whole file and GOLDEN stay unchanged. `wire_ledger.json` and the full tracked-file audit prove the test changes are limited to these load/access/manifest lines; no assertion or threshold changes.

## Plan deviations and tooling corrections

- Explicit initializer phases preserve the original state/DOM timing. `create()` precedes `initPop()` at the old declaration; the other six phases run at their old statements. The plan names the timing but does not prescribe this mechanism.
- Checked JavaScript needs the finite type-only edits above. There is no behavioral deviation from the Layers inventory, no preparation commit, no naming cleanup, UI change, dead-code removal or lifecycle redesign.
- The current UI has **View** and **Help and keys** popovers, not a third Keys popover: `POPS` remains the exact two-entry base object. The requested Keys interactions below refer to Help's key content.
- PR 4's scripts were copied/adapted into `build_jsplit5/`: all base/scratch paths, inventory ranges, phase specifications, ports, owner updates, rewrite count/order and module name changed; the gate runner retains nice 19 and the two-thread limits. The audit adds exact full-module reconstruction, all tracked surrounding files and explicit document-call sequence checks. The site checker now requires Layers, 24/13/6 and 20 source tags. Mutation tooling uses Layers regressions. Turbo evidence expects the current 637 checks, not the old plan's 604.
- TypeScript 5.6.3 was unpacked from the provided offline cache into scratch for extraction/audit before gate B; no install or network was needed for that step. Gate B subsequently ran the requested full offline install.
- The initial extractor's line-end assertion included one blank line after stats; corrected 2425 → 2424 before extraction completed. The audit initially tried Node `execFileSync(git ls-files)`, which hit sandbox EPERM. It now reads the unchanged manifest produced by shell `git ls-files`; its first retry passed. This is an own-script adaptation, not a workaround to an existing test.
- The first type run correctly found missing inert DOM/dashboard assertions. A type-edit script initially asserted four target occurrences instead of five and aborted before writing; the next audit/type commands consequently still checked the uncast file. Correcting that count applied the finite edits; the final audit and type check pass. Both failed type runs are retained below. No runtime logic was changed to satisfy typing.

## Gate record

Commands run through `python3 build_jsplit5/run_gate.py NAME CWD COMMAND...`, which applies nice 19 and `JOBS=2`, `BUILD_JOBS=2`, `OMP_NUM_THREADS=2`, `OPENBLAS_NUM_THREADS=2`, `MKL_NUM_THREADS=2`, `UV_THREADPOOL_SIZE=2`, `NODE_OPTIONS=--v8-pool-size=2`. Gates and Turbo sides run sequentially. No browser was launched. `$ROOT` denotes this worktree. Raw records: `build_jsplit5/logs/gates.jsonl`.

The audit verifies every inventory function and all nested callbacks/listeners/IIFEs character- and token-equal after only the finite ledgered ports/casts, the complete phase bodies and module shell, exactly one controller, absence of root orphans, exact remaining root and other owners, every tracked file outside the ledger, live getters, and a throwing-host VM for registration/construction. Exact phase/body/root reconstruction preserves all host operations at their original points and proves listener target/order/options. This is source/timing evidence, not browser acceptance.

| Command | Exit / status | Wall s | Log |
| --- | --- | --- | --- |
| `python3 build_jsplit5/record_base.py` | 0 | 0.314 | `build_jsplit5/logs/base-record.log` |
| `node build_jsplit5/audit.cjs` | 1 / own-script EPERM | 1.366 | `build_jsplit5/logs/audit.log` |
| `node build_jsplit5/audit.cjs` | 0 | 2.839 | `build_jsplit5/logs/audit-retry1.log` |
| `node tests/ui_common_tests.cjs` | 0 | 0.127 | `build_jsplit5/logs/ui_common_tests.log` |
| `node tests/ui_parity_harness_tests.mjs` | 1 / ENVIRONMENT-BLOCKED | 10.086 | `build_jsplit5/logs/ui_parity_harness_tests.log` |
| `node build_jsplit5/probe_spawn.cjs` | 0 | 0.125 | `build_jsplit5/logs/harness-spawn-diagnostic.log` |
| `node tests/ui_inspector_tests.cjs` | 0 | 3.643 | `build_jsplit5/logs/ui_inspector_tests.log` |
| `node tests/ocean_appearance_slots_tests.cjs` | 0 | 0.614 | `build_jsplit5/logs/ocean_appearance_slots_tests.log` |
| `node tests/ocean_shader_slots_tests.cjs` | 0 | 0.234 | `build_jsplit5/logs/ocean_shader_slots_tests.log` |
| `node tests/ocean_materials_tests.cjs` | 0 | 0.442 | `build_jsplit5/logs/ocean_materials_tests.log` |
| `node tests/ocean_render_opt_tests.cjs` | 0 | 0.107 | `build_jsplit5/logs/ocean_render_opt_tests.log` |
| `node tests/ocean_mock_three_tests.mjs` | 0 | 32.124 | `build_jsplit5/logs/ocean_mock_three_tests.log` |
| `node tests/ocean_perf_tests.cjs` | 0 | 0.089 | `build_jsplit5/logs/ocean_perf_tests.log` |
| `node tests/ocean_render_perf_lock_tests.mjs` | 0 | 15.563 | `build_jsplit5/logs/ocean_render_perf_lock_tests.log` |
| `node tests/ocean_render_query_tests.cjs` | 0 | 0.058 | `build_jsplit5/logs/ocean_render_query_tests.log` |
| `npm ci --offline --cache $ROOT/build_jsplit5/npm_cache --no-audit --no-fund` | 0 | 0.686 | `build_jsplit5/logs/npm-ci.log` |
| `npx --offline --cache $ROOT/build_jsplit5/npm_cache tsc -p tsconfig.json` | 2 | 4.188 | `build_jsplit5/logs/types.log` |
| `node build_jsplit5/audit.cjs` | 0 | 2.832 | `build_jsplit5/logs/audit-typed.log` |
| `npx --offline --cache $ROOT/build_jsplit5/npm_cache tsc -p tsconfig.json` | 2 | 3.977 | `build_jsplit5/logs/types-corrected.log` |
| `node build_jsplit5/audit.cjs` | 0 | 2.843 | `build_jsplit5/logs/audit-typed-final.log` |
| `npx --offline --cache $ROOT/build_jsplit5/npm_cache tsc -p tsconfig.json` | 0 | 3.861 | `build_jsplit5/logs/types-final.log` |
| `[cwd: build_jsplit5/base] node tests/ocean_turbo_handoff.js` | 0 | 326.626 | `build_jsplit5/logs/turbo-base.log` |
| `node tests/ocean_turbo_handoff.js` | 0 | 328.95 | `build_jsplit5/logs/turbo-head.log` |
| `python3 build_jsplit5/verify_evidence.py` | 0 | 0.055 | `build_jsplit5/logs/turbo-evidence.log` |
| `bash wasm/build_site.sh` | 0 | 0.741 | `build_jsplit5/logs/site-build.log` |
| `python3 build_jsplit5/check_site.py` | 0 | 0.152 | `build_jsplit5/logs/site-check.log` |
| `python3 build_jsplit5/verify_unchanged.py` | 0 | 0.257 | `build_jsplit5/logs/unchanged.log` |
| `node --check tests/ocean_render_browser.mjs` | 0 | 0.05 | `build_jsplit5/logs/browser-manifest-syntax.log` |
| `node --check $ROOT/build_jsplit5/mutants/a-focus/web/ocean_layers.js` | 0 | 0.05 | `build_jsplit5/logs/mutant-a-focus-syntax.log` |
| `node build_jsplit5/audit.cjs $ROOT/build_jsplit5/mutants/a-focus` | 1 / rejected as expected | 0.777 | `build_jsplit5/logs/mutant-a-focus.log` |
| `node --check $ROOT/build_jsplit5/mutants/b-sync/web/ocean_layers.js` | 0 | 0.058 | `build_jsplit5/logs/mutant-b-sync-syntax.log` |
| `node build_jsplit5/audit.cjs $ROOT/build_jsplit5/mutants/b-sync` | 1 / rejected as expected | 1.044 | `build_jsplit5/logs/mutant-b-sync.log` |
| `node --check $ROOT/build_jsplit5/mutants/b-drop/web/ocean_layers.js` | 0 | 0.055 | `build_jsplit5/logs/mutant-b-drop-syntax.log` |
| `node build_jsplit5/audit.cjs $ROOT/build_jsplit5/mutants/b-drop` | 1 / rejected as expected | 1.169 | `build_jsplit5/logs/mutant-b-drop.log` |
| `node --check $ROOT/build_jsplit5/mutants/c-shared/web/ocean_layers.js` | 0 | 0.054 | `build_jsplit5/logs/mutant-c-shared-syntax.log` |
| `node build_jsplit5/audit.cjs $ROOT/build_jsplit5/mutants/c-shared` | 1 / rejected as expected | 1.334 | `build_jsplit5/logs/mutant-c-shared.log` |
| `node --check $ROOT/build_jsplit5/mutants/c-twice/web/ocean_layers.js` | 0 | 0.055 | `build_jsplit5/logs/mutant-c-twice-syntax.log` |
| `node build_jsplit5/audit.cjs $ROOT/build_jsplit5/mutants/c-twice` | 1 / rejected as expected | 1.274 | `build_jsplit5/logs/mutant-c-twice.log` |
| `node --check $ROOT/build_jsplit5/mutants/d-eager-tip/web/ocean_layers.js` | 0 | 0.049 | `build_jsplit5/logs/mutant-d-eager-tip-syntax.log` |
| `node build_jsplit5/audit.cjs $ROOT/build_jsplit5/mutants/d-eager-tip` | 1 / rejected as expected | 1.601 | `build_jsplit5/logs/mutant-d-eager-tip.log` |
| `node --check $ROOT/build_jsplit5/mutants/e-order/web/ocean_layers.js` | 0 | 0.073 | `build_jsplit5/logs/mutant-e-order-syntax.log` |
| `node build_jsplit5/audit.cjs $ROOT/build_jsplit5/mutants/e-order` | 1 / rejected as expected | 1.266 | `build_jsplit5/logs/mutant-e-order.log` |
| `node --check $ROOT/build_jsplit5/mutants/f-captured-tips/web/ocean_layers.js` | 0 | 0.053 | `build_jsplit5/logs/mutant-f-captured-tips-syntax.log` |
| `node build_jsplit5/audit.cjs $ROOT/build_jsplit5/mutants/f-captured-tips` | 1 / rejected as expected | 1.276 | `build_jsplit5/logs/mutant-f-captured-tips.log` |
| `node --check $ROOT/build_jsplit5/mutants/g-missing-site-script/web/ocean_layers.js` | 0 | 0.059 | `build_jsplit5/logs/mutant-g-missing-site-script-syntax.log` |
| `python3 build_jsplit5/check_site.py $ROOT/build_jsplit5/mutants/g-missing-site-script` | 1 / rejected as expected | 0.203 | `build_jsplit5/logs/mutant-g-missing-site-script.log` |
| `python3 build_jsplit5/mutations.py` | 0 | 13.563 | `build_jsplit5/logs/mutations.log` |
| `node build_jsplit5/audit.cjs` | 0 | 2.265 | `build_jsplit5/logs/audit-final.log` |
| `python3 build_jsplit5/verify_unchanged.py` | 0 | 0.255 | `build_jsplit5/logs/unchanged-final.log` |
| `python3 build_jsplit5/verify_unchanged.py` | 0 | 0.258 | `build_jsplit5/logs/report-protected-final.log` |

`node tests/ui_parity_harness_tests.mjs` is **ENVIRONMENT-BLOCKED**, not a pass: 122 of 132 checks fail because its `harness()` helper drops `spawnSync`'s error field and returns empty output. `node build_jsplit5/probe_spawn.cjs` reproduces the same child invocation and records `spawnSync /home/harit/opt/node-v26.13.0-linux-x64/bin/node EPERM`, empty stdout/stderr. The test itself is unchanged; no workaround was used. The coordinator must rerun the exact unit command outside the sandbox.

The scene recording remains `ff2f626dc192c801` (465 recorded frames), 59/59 checks. Other passing unit totals: common UI 107/107, Inspector 95/95, appearance slots 91/91, shader slots 155/155, materials 153/153, render optimization 39/39, profiler 82/82, browser lock 40/40, and extra render-query check 12/12.

## Turbo, built site and protected artifacts

| Side | Result | Section headings | Runner s | Wall s |
| --- | --- | --- | --- | --- |
| base | 637/637 PASS | 80 | 326.3 | 326.626 |
| head | 637/637 PASS | 80 | 328.4 | 328.95 |

Both full commands retain every section, worker/probe cleanup and the final no-unhandled-promise-rejection check; heading sequences are identical.

Built-site checker: Ocean/Classic/body rewrite assertions **24/13/6**, **20** source script tags, exact source/hashed load order (dash → Readouts → Inspector → Display → Layers → Tour → root → guide), one `assets/ocean_layers.0974470f1aad.js` per alias, bytes equal to source, full SHA-256 `0974470f1aade60307df0c081329b0191bdbd8760f9af3afac5ee64b21383021`. Every published asset name equals its SHA prefix; no bare controller URL survives; index/ocean aliases are byte-identical; Classic/body routes, redirect and helper/worker resources resolve. This does not establish HTTP headers or browser loading.

`git diff --check` and protected-path checks compare against HEAD (the recorded base). Six generated module hashes, all `src/` including plane headers, both Wasm C++ wrappers, baselines, fixtures and the entire scene recording test remain unchanged. No C++/Wasm build was made.

| Generated file under `web/` | Unchanged SHA-256 |
| --- | --- |
| evo_boids.js | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` |
| evo_boids.wasm | `d05c4442e15d6850aeece60e52c2a69289d10a2d39fd17538b2347123be0a99b` |
| evo_boids_mt.js | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` |
| evo_boids_mt.wasm | `1c86e3d2a8c043e17ab1e75004ad37d9d20a70ce5498a80e4ae4bf4fdd8a703b` |
| evo_ocean.js | `8bdce72bd8991c6e88768712b60cec9b7dd0cf22335d82ebe67f40cef6d91059` |
| evo_ocean.wasm | `e55a4fcb2e7c2e737c6f0cc838c783237ba138336f1162ab4ddf037468b5f2f1` |

## Listener order

All seven document listeners owned by the current root/controller composition are bubble listeners (two arguments, no capture option). The installation order for successful startup is below. The three `wireInput` listeners occur late in startup, although their source definitions precede drawer initialization. The audit also records/checks that lexical list with original scope, event and phase. Root's unchanged input installation, guide and dashboard phases preserve their registrations relative to this sequence.

| Runtime order | Listener | Base line | Head location |
| --- | --- | --- | --- |
| 1 | document pointerdown: popover outside | 2382 | Layers 61, `registerPopOutside` at original root point |
| 2 | document pointerdown: stats outside | 3041 | Layers 166, end of `registerDrawer` |
| 3 | document pointerdown: tooltip outside | 3087 | Layers 215, `registerTips` |
| 4 | document pointerdown: Start menu outside | 3149 | Root 2978, unchanged phase |
| 5 | document keyup: held keys | 2860 | Root `wireInput`, startup call at original point |
| 6 | document visibilitychange: release movement | 2866 | Root `wireInput` |
| 7 | document focusin: release movement while typing | 2867 | Root `wireInput` |

Within Layers the remaining registration order is unchanged: wide media-query change (`addEventListener`, or Safari `addListener` fallback), menu click, drawer-close click, the intact drag IIFE (grip then head; pointerdown → pointermove → pointerup → pointercancel for each), readout click, stats outside pointer, tooltip DOM creation, panel scroll, tooltip outside pointer. Each `attachTip` still registers mouseenter → mouseleave → optional label click when called by field construction. Every event-listener registration is bubble phase. The page's window pointer-type listeners retain capture `true`, the Escape capture retains `true`, and late resize/debounce listeners stay inside `wireInput` with their existing timing and options.

## Mutation sensitivity

All mutations are made only in full disposable copies under `build_jsplit5/mutants/`; the working page and pristine base are untouched. Each uses the same audit or built-site checker as the unmutated gate.

| Mutant | Change | Catching server gate | Exit | Log |
| --- | --- | --- | --- | --- |
| a-focus | closePop drops opener focus return | Extraction audit | 1 | `build_jsplit5/logs/mutant-a-focus.log` |
| b-sync | setDrawer runs delayed inset update synchronously | Extraction audit | 1 | `build_jsplit5/logs/mutant-b-sync.log` |
| b-drop | setDrawer drops delayed inset update | Extraction audit | 1 | `build_jsplit5/logs/mutant-b-drop.log` |
| c-shared | sheet drag start shared at module scope | Extraction audit | 1 | `build_jsplit5/logs/mutant-c-shared.log` |
| c-twice | sheet drag IIFE installed twice | Extraction audit | 1 | `build_jsplit5/logs/mutant-c-twice.log` |
| d-eager-tip | tooltip nodes and initial state created at module registration | Extraction audit | 1 | `build_jsplit5/logs/mutant-d-eager-tip.log` |
| e-order | popover and stat document pointer listeners swapped | Extraction audit | 1 | `build_jsplit5/logs/mutant-e-order.log` |
| f-captured-tips | attachTip reads a captured table from initTips | Extraction audit | 1 | `build_jsplit5/logs/mutant-f-captured-tips.log` |
| g-missing-site-script | built Ocean aliases omit Layers script | Built-site checker | 1 | `build_jsplit5/logs/mutant-g-missing-site-script.log` |

All **9 mutants** covering the seven requested categories are rejected. These are source/packaging sensitivity results; no claim is made that the pre-existing Node runtime tests alone observe every regression. No requested mutant escapes a server gate. The browser interaction checks remain required.

## Exact line and body counts

Counts below use newline-terminated physical source lines, including comments, blank lines, annotations and wrappers; no header or blank separator is silently excluded.

- Base root: **3476** lines. Head root: **3305** lines, a reduction of **171**.
- New Layers module: **247** lines. Combined root + Layers: **3552** lines. These are physical file counts, not a claim that the total code shrank.
- **184** complete base lines in seven moved fragments, including their comments; the retained `pointerBlur` fragment is excluded. Phase/delegation/factory lines account for the difference from the net root reduction.
- **11** named inventory functions; **27** moved function-like bodies total, counting each nested callback/helper and the sheet-drag IIFE once.
- **44** function-like nodes in Layers: those 27 moved bodies + 7 phase wrappers + factory + registration IIFE + 8 API getter/setter bodies.
- **13** owned state bindings from eight base var statements; no root state copy remains.
- **15** lexical `addEventListener` call sites plus one legacy `addListener` fallback in Layers. The four drag call sites execute for each of grip/head; `attachTip`'s three call sites execute per field, the last only when a label exists. These are call-site counts, not a fixed runtime listener total.

## Laptop commands and interactions (not run on this server)

Use the candidate's same harness/fixtures for both sides. Configure the laptop's `PLAYWRIGHT`, `BRAVE_EXE` and machine-wide `BROWSER_LOCK` as usual. Use fresh output folders when rerunning; do not deploy. Serve base, head and assembled site in separate terminals:

```bash
python3 wasm/serve.py build_jsplit5/base 8261
python3 wasm/serve.py . 8262
python3 wasm/serve.py dist 8263

# Rerun the environment-blocked server unit command outside the sandbox.
node tests/ui_parity_harness_tests.mjs

# UI identity: strict comparison, including S3 responsive Inspector cases.
node tests/ui_parity_browser.mjs --base http://localhost:8261 --layout source --sets S0,S2,S3 --expect record --out build_jsplit5/laptop/ui-before
node tests/ui_parity_browser.mjs --base http://localhost:8262 --layout source --sets S0,S2,S3 --out build_jsplit5/laptop/ui-after
node tests/ui_parity_browser.mjs --compare build_jsplit5/laptop/ui-before build_jsplit5/laptop/ui-after --sets S0,S2,S3 --out build_jsplit5/laptop/ui-diff

# Site-layout smoke takes the lock internally.
node tests/ui_parity_browser.mjs --base http://localhost:8263 --layout site --smoke --out build_jsplit5/laptop/site-smoke
```

Render-browser and body GPU need the external lock; do not wrap internally locking tools:

```bash
locked_node() {
  node --input-type=module -e 'import { acquire } from "./tools/ocean_render_perf/lock.mjs"; import { spawn } from "node:child_process"; const release = await acquire("ocean.js split PR5 checks"); try { const code = await new Promise((resolve, reject) => { const child = spawn(process.execPath, process.argv.slice(1), { stdio: "inherit" }); child.on("error", reject); child.on("exit", c => resolve(c ?? 1)); }); process.exitCode = code; } finally { release(); }' "$@"
}

# A/A first: base vs the same base; reference policy explicitly on both roles.
locked_node tests/ocean_render_browser.mjs --base http://localhost:8261/web --main-base http://localhost:8261/web --parts offimage --query renderOpt=0 --main-query renderOpt=0 --out build_jsplit5/laptop/offimage-aa

# Then base vs head, retaining both explicit policy queries and all tolerances.
locked_node tests/ocean_render_browser.mjs --base http://localhost:8262/web --main-base http://localhost:8261/web --parts offimage --query renderOpt=0 --main-query renderOpt=0 --out build_jsplit5/laptop/offimage-ab

locked_node tests/ocean_render_browser.mjs --base http://localhost:8262/web --parts correctness,slots,noperf,missing,faults,timer,beam,iframe,gate --out build_jsplit5/laptop/render

# Record the known reference-command failures on base, then compare head.
locked_node tests/ocean_render_browser.mjs --base http://localhost:8261/web --parts correctness,iframe,gate --query renderOpt=0 --out build_jsplit5/laptop/reference-base
locked_node tests/ocean_render_browser.mjs --base http://localhost:8262/web --parts correctness,iframe,gate --query renderOpt=0 --out build_jsplit5/laptop/reference-head

locked_node tests/ocean_body_gpu.mjs --base http://localhost:8262

# Source-layout page smoke takes the lock internally.
node tools/ocean_render_perf/smoke.mjs --web http://localhost:8262/web --root http://localhost:8262
```

The coordinator reports that the reference command has three **live decoded texture** failures identically on main: reference policy never builds the decoded cache. Compare that command against base; do not attribute those existing failures to this extraction or relax the checks. Off-image A/A and A/B still require matching reference policies. Body GPU's real-controller bridge uses source `/web/ocean.html`; site-layout smoke covers built routes. Plan §5 E–I is skipped on this server; no deployment is requested.

Layers interaction list for the coordinator (paired base/head, with matching pointer type and viewport):

- View, Help and its Keys content: open/close with pointer and keyboard, outside click, Esc, trigger shortcut and focus return. The current base has two popovers; do not invent a third Keys surface.
- Stats panel against the fish card: opening numbers over an overlapping card holds/hides it; closing numbers restores it; choosing a new fish over numbers closes numbers (`cardNewer/cardHeld`).
- Drawer opening/closing and wide → narrow → wide resize with layers open. Insets follow immediately and after the unchanged 320 ms delayed update; focus follows the original rules.
- Phone sheet drag through both grip and header; drag below/above close threshold; pointer cancel; wide-screen drag remains inactive.
- Readout toggle and outside-pointer dismissal.
- Tooltips: mouse hover delay, leave, panel scroll-hide, touch label toggle, outside-pointer hide and a #94 Setup tip using the live `CFG.TIPS` text.

New world draws a `Math.random` seed, so post-New-world live readings are not comparable across independent runs. Use fixed or replay setups for comparisons. All browser gates are pending coordinator/laptop acceptance.

## Proposed commit split (coordinator only)

1. **Atomic extraction:** Layers module; root delegations and explicit phases; Inspector/Readouts/Display/Tour owner ports; concrete types and checked-file entry; source HTML and hashed publication/rewrite 24; both VM loaders/private getters; dependency-order list and render evidence manifest.
2. **Documentation:** `docs/ocean_js_split_pr5_report.md`.

No preparation commit was needed. Leave `build_jsplit5/`, generated `dist/` and installed development dependencies excluded. The coordinator commits; this task leaves all changes uncommitted.

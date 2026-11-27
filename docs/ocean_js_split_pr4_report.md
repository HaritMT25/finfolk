# Ocean controller split: PR 4, Display

Controller-only extraction from **b8337343d64b831fd6878c48a110302ada67c3da** (PR 3's branch head, draft PR #102), on branch `ocean-js-split-4`, stacked on PR 3. The pristine base is the detached worktree `jsplit4_base` at the same commit. Everything ran on the laptop: Node unit, type, Turbo, site and mutation gates in WSL (Node v20.20.2, npm 10.8.2); browser gates in Windows Node v26.1.0 with headless Brave under the machine-wide lock. There was no C++/Wasm build, merge, push, deployment or rebaseline.

## Inventory and current-base mapping

`web/ocean_display.js` registers `window.EvoOceanDisplay = { create: create }`. It owns the colour mode, the flashlight and "Light while following", the water's clarity, the shim's display switches and the modeline, exactly the plan §2 inventory. Root keeps startup, transactions, frame sequencing, input and layer coordination.

The plan cites pre-Tour main 294fc8b. Every base column below is **current base b833734 `web/ocean.js`**, mapped by name and content. Every base span has the same length as the plan's span. Destination columns are `web/ocean_display.js` lines.

Exact counts, each saying what it includes:

- **12 moved named functions** (the plan's list). Counting their **2 nested callbacks** (`showColourMode`'s `forEach` callback and `tankShowsFamily`'s `engineCall` callback), that is **14 function-like nodes**.
- **6 requested fragments**. Between them they hold **6 listener registrations**, each with one listener callback, **2 IIFEs**, and one property write (the follow-light switch's initial `checked`). That is **8 function-like nodes**.
- **22 moved function-like bodies** in total (14 + 8). No nested callback is counted twice.
- **7 owned bindings in 4 base declarations.** One declaration, line 2237, also declares root's `governorOn`.
- **18 base comments** move with their code, in order.
- The new module has **36 function-like nodes**: the 22 moved bodies, 9 phase wrappers, the factory, the registration IIFE and 3 API accessors.

| Function | Plan (294fc8b) | Current base | Display |
| --- | ---: | ---: | ---: |
| `applyDisplaySwitches` | 647–655 | 668–676 | 21–29 |
| `onFollowChange` (complete) | 2308–2319 | 2291–2302 | 30–41 |
| `lightOn` | 2342 | 2325 | 51 |
| `updateLight` | 2343–2350 | 2326–2333 | 52–59 |
| `toggleLight` | 2351–2355 | 2334–2338 | 60–64 |
| `showColourMode` (its `forEach` callback 3249 → 102) | 3702–3704 | 3248–3250 | 101–103 |
| `setColourMode` | 3709–3718 | 3255–3264 | 108–117 |
| `parseClarity` | 3737–3746 | 3283–3292 | 140–149 |
| `clarityLabel` | 3747 | 3293 | 150 |
| `applyClarity` | 3748–3754 | 3294–3300 | 151–157 |
| `tankShowsFamily` (its `engineCall` callback 3315 → 176) | 3767–3770 | 3313–3316 | 174–177 |
| `updateModeline` | 3772–3805 | 3318–3351 | 181–214 |

| Fragment / owned state | Plan | Current base | Display phase (lines) | Root call (head line) |
| --- | ---: | ---: | --- | ---: |
| `colourBrain/colourMode` (shares the declaration with root's `governorOn`) | 2224 | 2237 | `create()` initializers, line 8 | `create` at 2223 |
| `followLight/lightNow/lightBeforeFollow` and the **follow-light preference read** | 2341 | 2324 | `initLight` 48–50 | 2302 |
| Direct light checkbox (`#lightnow` change) | 3591–3595 | 3143–3147 | `wireLightSwitch` 65–71 | 3107 |
| Follow-light preference listener and initial checkbox | 3677–3684 | 3223–3230 | `wireFollowLight` 72–81 | 3183 |
| Initial colour preference IIFE | 3692–3699 | 3238–3245 | `initColourMode` 89–98 | 3184 |
| Colour controls (`#colourMode` and `#colourwhy` clicks) | 3719–3730 | 3265–3276 | `wireColourControls` 118–131 | 3185 |
| `clarity` | 3736 | 3282 | `initClarity` 137–139 | 3186 |
| Initial clarity preference IIFE | 3755–3759 | 3301–3305 | `loadClarity` 158–164 | 3187 |
| Clarity listeners (`input`, then `pointerup`) | 3760–3765 | 3306–3311 | `wireClarity` 165–172 | 3188 |
| `modelineDetail` | 3771 | 3317 | `initModeline` 178–180 | 3189 |

Each requested fragment is one phase. Each phase body is its base statements verbatim, with their original indentation and the two IIFEs kept whole. The three owned-state declarations that execute between other root statements (2324, 3282, 3317) become assignment phases at their original points, as PR 3 did for `dirtyHud` and `sampleBucket`. A `var` declarator list becomes the same comma assignment. `initLight` keeps the preference read at base line 2324's point. The colour and clarity preference reads stay inside their IIFEs at 3238 and 3301.

The factory runs at base line 2237, the earliest owned declaration. It evaluates only `colourBrain = false, colourMode = "family"`, as base did there, after root's `governorOn = !BENCH`. It reads no port. Every other slot is declared without an initializer until its phase runs.

## What stays in root

| Retained unit | Current base | Reason / allowed edit |
| --- | ---: | --- |
| `governorOn` | 2237 | Playback/governor state. Its declaration is split from Display's two declarators, evaluation order unchanged. |
| Governor change listener | 3218–3222 | Root (plan "Governor change listener"); unchanged, still immediately before Display's follow-light phase. |
| `restoreDetail` | 2762 | Governor; only `updateModeline` is qualified. |
| `updateKeysLegend` | 2304–2316 | Input (PR 6). Display calls it through a function port at the same point in `onFollowChange`. |
| `pointerBlur`, popovers (`POPS`, `setPop` …) | 2340–2382 | Layers (PR 5); unchanged; Display uses `pointerBlur`/`setPop` through function ports. |
| `btn("lightbtn", …)`, the `L` key, `followbtn`/`viewbtn` | 3131, 2908, 3150, 3148 | Input registrations; only the callee is qualified (`display.toggleLight`). |
| Startup's scene setup, appearance, light, modeline, clarity | 3459–3478 | Startup sequencing; the four Display calls are qualified at the same positions. |
| `EvoOcean.state()`, `EvoOcean.set`, the benchmark adapter | 3482–3547 | Public API; `colourMode`/`colourBrain`/`setColourMode`/`updateModeline` read through Display. Property keys unchanged. |
| `afterNewWorld`, `liveApplied` | 631–661, 912–927 | Transactions; only the `applyDisplaySwitches`/`updateModeline` calls are qualified, in place. |
| Mixed section headings, the blank separators | — | Unchanged. The plan's `Ordered initial painting` (setPaused … hideAsk) stays root, right after `display.initModeline()`. |

The first 79 header lines and every unledgered root byte are unchanged.

## Move ledger

`build_jsplit4/move_ledger.json` records everything below.

- **9 base fragments**: 8 complete line ranges, 182 lines in all, plus the split of line 2237.
- **83 moved-body port occurrences** over **26 distinct ports**: 17 stable function or immutable-value ports and 9 live getters. Each carries its base line and column.
- **34 root edits**: **25 root identifier qualifications**, plus the 8 fragment replacements and the 1 state split.
- **7 ordered follow-up substitutions** on root: 6 owner-port changes in the three existing controllers' constructions, and the factory call.
- **11 owner-port qualifications** inside Inspector (3), Tour (4) and Readouts (4).

`function_mapping.json` holds the tables above. `type_edits.json` holds the two type-only casts.

The moved-body port substitutions, in full (repeated line numbers are separate lexical occurrences). Root's functions and immutable values go by reference; every replaceable binding goes through a getter. No getter syncs, refreshes, allocates or calls a controller.

| Base identifier → port | Count | Current base lines | Access |
| --- | ---: | --- | --- |
| `BENCH` → `ports.BENCH` | 1 | 3259 | Immutable value (set once at 88) |
| `changedKeys` → `ports.changedKeys` | 1 | 3328 | Original function |
| `coarseMQ` → `ports.coarseMQ` | 1 | 2295 | Immutable value |
| `D` → `ports.D` | 1 | 3338 | Live root getter |
| `el` → `ports.el` | 17 | 2292, 2293, 2329, 2332, 3143, 3223, 3230, 3249, 3265, 3271, 3274, 3295, 3298, 3306, 3311, 3328, 3343 | Original function |
| `engineCall` → `ports.engineCall` | 3 | 3261, 3262, 3315 | Original function |
| `H` → `ports.H` | 1 | 3338 | Live root getter |
| `has` → `ports.has` | 4 | 669, 671, 3315, 3320 | Original function |
| `HAS_APP` → `ports.HAS_APP` | 4 | 3315, 3320, 3323, 3345 | Live root getter |
| `HAS_EYE` → `ports.HAS_EYE` | 1 | 3332 | Live root getter |
| `historyUnknown` → `ports.historyUnknown` | 3 | 3330, 3331, 3336 | Live root getter |
| `inspector` → `ports.inspector` | 3 | 672, 674, 2294 | Stable Inspector instance (created at 375, before Display) |
| `M` → `ports.M` | 6 | 669, 673, 3261, 3315, 3320, 3342 | Live root getter |
| `P` → `ports.P` | 2 | 3239, 3302 | Immutable value |
| `pointerBlur` → `ports.pointerBlur` | 3 | 3146, 3228, 3269 | Original function |
| `scene` → `ports.scene` | 16 | 670, 670, 670, 2328, 2328, 2336, 2336, 3226, 3226, 3299, 3299, 3299, 3329, 3329, 3340, 3340 | Live root getter |
| `setDrawer` → `ports.setDrawer` | 1 | 3273 | Original function |
| `setHtml` → `ports.setHtml` | 1 | 3344 | Original function |
| `setPop` → `ports.setPop` | 1 | 3273 | Original function |
| `setSheetTab` → `ports.setSheetTab` | 1 | 3273 | Original function |
| `store` → `ports.store` | 6 | 2324, 3225, 3239, 3259, 3302, 3308 | Original function |
| `syncedFrame` → `ports.syncedFrame` | 1 | 674 | Original function |
| `toast` → `ports.toast` | 2 | 2295, 2336 | Original function |
| `updateKeysLegend` → `ports.updateKeysLegend` | 1 | 2301 | Original function |
| `W` → `ports.W` | 1 | 3338 | Live root getter |
| `WALLS` → `ports.WALLS` | 1 | 3339 | Live root getter |

The extractor resolves every identifier with the TypeScript checker. A moved body may reference a root binding only if it is Display-owned or a declared port; anything else fails the extraction. Every declared port is used. Local names that shadow root names (`want`, `saved`, `on`, `b`, `row` …) are untouched.

Root's exact identifier qualifications. Property keys (`colourMode:`, `onFollowChange:`, `setColourMode:`) stay literal.

| Root identifier → Display member | Count | Current base lines |
| --- | ---: | --- |
| `applyClarity` → `display.applyClarity` | 1 | 3478 |
| `applyDisplaySwitches` → `display.applyDisplaySwitches` | 1 | 647 |
| `colourBrain` → `display.colourBrain` | 2 | 2389, 3527 |
| `colourMode` → `display.colourMode` | 6 | 382, 2253, 2389, 3472, 3527, 3546 |
| `lightOn` → `display.lightOn` | 1 | 2239 |
| `modelineDetail` → `display.modelineDetail` | 1 | 2823 |
| `onFollowChange` → `display.onFollowChange` | 1 | 3463 |
| `setColourMode` → `display.setColourMode` | 2 | 2239, 3546 |
| `tankShowsFamily` → `display.tankShowsFamily` | 1 | 2239 |
| `toggleLight` → `display.toggleLight` | 2 | 2908, 3131 |
| `updateLight` → `display.updateLight` | 1 | 3476 |
| `updateModeline` → `display.updateModeline` | 6 | 651, 925, 2762, 2823, 3477, 3503 |

Root calls a moved function either as an owner member (`display.updateModeline()`) or passes it unbound (`engineCall(display.updateModeline)`, `btn("lightbtn", display.toggleLight)`, the scene's `onFollowChange`, the benchmark's `setColourMode`). None of the 12 moved functions uses `this` of its own; the audit checks it. Receivers are therefore immaterial, exactly as for base's bare calls. The six listener callbacks keep their `this` (the element).

Transitional root getters removed, in the 7 follow-ups:

- **Inspector**, constructed at base 375 before Display: `get colourMode()` becomes the owner getter `get display() { return display; }`, which defers the lookup exactly as PR 3's `get readouts()` did. Its three reads become `ports.display.colourMode` (lines 195, 196, 233). All three run only from the card at frame time.
- **Readouts**, constructed right after Display: the `lightOn`, `tankShowsFamily` and `setColourMode` function ports and the `get colourMode()` getter are replaced by `display: display`. Its four uses become `ports.display.lightOn()`, `ports.display.tankShowsFamily()`, `ports.display.colourMode` and `ports.display.setColourMode("family")` (lines 115, 152, 152, 153).
- **Tour**, constructed after Display: `get colourMode()` and `get colourBrain()` are replaced by `display: display`. Its reads become `p.display.colourMode` (×2) and `p.display.colourBrain` (×2) (lines 60, 62, 159, 160).
- The factory call: `var display = EvoOceanDisplay.create({...})` with the 17 stable ports by reference and the 9 live getters.

No generic context object is passed. The rest of Inspector, Tour and Readouts is character-identical to base.

**`onFollowChange`** stays one synchronous function: button state, `ports.inspector.wantFollow = false` on release, the toast, the light hand-over, `updateLight()` and then `ports.updateKeysLegend()`, in base order. The scene calls it directly. There is no timer, microtask or event.

Concrete owner, port and element types are in `web/types.d.ts` (`OceanDisplayElements`, `OceanDisplayPorts`, `OceanDisplay`, `EvoOceanDisplayApi`, `declare var EvoOceanDisplay`). Inspector, Readouts and Tour ports now take `Pick<OceanDisplay, …>` owner references. `OceanScene` gains the three members Display calls: `setFlashlight`, plus the feature-detected `setAppearance?` and `setClarity?`. The new file carries `// @ts-check` and is listed in `tsconfig.json`.

Type-only normalizations, exhaustively encoded in the audit:

- The `#colourMode` click: `e.target` is cast `/** @type {Element} */` and the found button `/** @type {HTMLElement | null} */`, so `.closest` and `.dataset` type-check.
- The `#colourwhy` click: `e.target` is cast `/** @type {Element} */`.
- JSDoc types annotate the factory signature and the declared-but-uninitialized slots.

No call, value, receiver or evaluation order changed. There is no `any` and no suppression.

Loaders and scanners updated:

- the Turbo VM loader (`run('ocean_display.js')`);
- the Inspector real-page loader;
- the common HTML dependency list;
- the render evidence hash manifest.

The Turbo `__oceanPage` adapter and the URL-import slice reference no Display name and are unchanged. The start-door, memory-install, `OCEAN_KEYS` and parameter scanners inspect root implementations that did not move. Mock-three's scene-only list and the whole scene test file, including GOLDEN, are unchanged. `verify_test_deltas.py` proves the four test files differ from base only by these exact additions and that no other test file changed.

## Plan deviations

- **Builder comment count**: the comment above the Ocean rewrites becomes "its nineteen `<script src>` tags", the source page's real count, which the site checker now asserts. PR 1 updated it (fifteen to sixteen); PRs 2 and 3 left "sixteen" while adding tags 17 and 18. The plan says to update it as tags are added. This is comment-only.
- **Owned-state phases**: `followLight…` (with its preference read), `clarity` and `modelineDetail` get their own assignment phases at their original points, rather than being initialized at construction. The plan names their declaration lines but not a mechanism; this keeps every initialization point exact.
- **Inspector's `get display()` owner getter**: Inspector is constructed before Display. This replaces its transitional `colourMode` getter, following PR 3's `get readouts()`.
- **Type-only edits**: checked JavaScript needs the two casts and the scene members above. No behavioural deviation from the plan's inventory; no preparation commit (no loader or scanner needed generalising).

## Gate record

WSL gates run through `python3 build_jsplit4/run_gate.py NAME CWD COMMAND...` (nice 19, two threads per job, as PR 3); the raw records are `build_jsplit4/logs/gates.jsonl`. Browser gates run through `node build_jsplit4/browser_gate.mjs NAME ARGS...` (Windows Node, cwd = the worktree); records `build_jsplit4/laptop/gates.jsonl`. `$ROOT` is this worktree.

| Command | Exit | Wall s | Log |
| --- | ---: | ---: | --- |
| `python3 build_jsplit4/record_base.py` (commit, branch, Node/npm, six hashes, equality with `jsplit4_base`) | 0 | 0.114 | `build_jsplit4/logs/base-record.log` |
| `node build_jsplit4/audit.cjs` | 0 | 3.483 | `build_jsplit4/logs/audit.log` |
| `node tests/ui_common_tests.cjs` (107/107) | 0 | 0.354 | `build_jsplit4/logs/ui_common_tests.log` |
| `node tests/ui_parity_harness_tests.mjs` (132/132) | 0 | 8.958 | `build_jsplit4/logs/ui_parity_harness_tests.log` |
| `node tests/ui_inspector_tests.cjs` (95/95) | 0 | 5.43 | `build_jsplit4/logs/ui_inspector_tests.log` |
| `node tests/ocean_appearance_slots_tests.cjs` (91/91) | 0 | 0.663 | `build_jsplit4/logs/ocean_appearance_slots_tests.log` |
| `node tests/ocean_shader_slots_tests.cjs` (155/155) | 0 | 0.235 | `build_jsplit4/logs/ocean_shader_slots_tests.log` |
| `node tests/ocean_materials_tests.cjs` (153/153) | 0 | 0.426 | `build_jsplit4/logs/ocean_materials_tests.log` |
| `node tests/ocean_render_opt_tests.cjs` (39/39) | 0 | 0.115 | `build_jsplit4/logs/ocean_render_opt_tests.log` |
| `node tests/ocean_mock_three_tests.mjs` (59/59) | 0 | 30.359 | `build_jsplit4/logs/ocean_mock_three_tests.log` |
| `node tests/ocean_perf_tests.cjs` (82/82) | 0 | 0.159 | `build_jsplit4/logs/ocean_perf_tests.log` |
| `node tests/ocean_render_perf_lock_tests.mjs` (40/40; its own temp lock file) | 0 | 15.817 | `build_jsplit4/logs/ocean_render_perf_lock_tests.log` |
| `node tests/ocean_render_query_tests.cjs` (12/12; PR 1's, beyond §5 A) | 0 | 0.04 | `build_jsplit4/logs/ocean_render_query_tests.log` |
| `npm ci --no-audit --no-fund` | 0 | 1.175 | `build_jsplit4/logs/npm-ci.log` |
| `npx --no-install tsc -p tsconfig.json` | 0 | 5.052 | `build_jsplit4/logs/types.log` |
| `node tests/ocean_turbo_handoff.js` (cwd `jsplit4_base`) | 0 | 325.131 | `build_jsplit4/logs/turbo-base.log` |
| `node tests/ocean_turbo_handoff.js` | 0 | 296.285 | `build_jsplit4/logs/turbo-head.log` |
| `bash wasm/build_site.sh` | 0 | 0.306 | `build_jsplit4/logs/site-build.log` |
| `python3 build_jsplit4/check_site.py` | 0 | 0.076 | `build_jsplit4/logs/site-check.log` |
| `python3 build_jsplit4/verify_unchanged.py` | 0 | 0.108 | `build_jsplit4/logs/unchanged.log` |
| `python3 build_jsplit4/verify_test_deltas.py` | 0 | 0.039 | `build_jsplit4/logs/test-deltas.log` |
| `python3 build_jsplit4/verify_evidence.py` | 0 | 0.039 | `build_jsplit4/logs/turbo-evidence.log` |
| `node --check tests/ocean_render_browser.mjs` | 0 | 0.025 | `build_jsplit4/logs/browser-manifest-syntax.log` |
| `python3 build_jsplit4/mutations.py` (31 sub-gates, below) | 0 | 64.087 | `build_jsplit4/logs/mutations.log` |
| `node build_jsplit4/audit.cjs` (final) | 0 | 1.037 | `build_jsplit4/logs/audit-final.log` |
| `python3 build_jsplit4/verify_unchanged.py` (final) | 0 | 0.137 | `build_jsplit4/logs/unchanged-final.log` |
| `python3 build_jsplit4/verify_unchanged.py b8337343…` (after commit 1: `git diff --check` covers the new file) | 0 | 0.057 | `build_jsplit4/logs/unchanged-committed.log` |
| `node build_jsplit4/audit.cjs` (after commit 1) | 0 | 0.899 | `build_jsplit4/logs/audit-committed.log` |
| `node tests/ui_parity_browser.mjs --base http://localhost:8281 --layout source --sets S0,S2,S3 --expect record --out build_jsplit4/laptop/ui-before --clean` | 0 | 1524.4 | `build_jsplit4/laptop/logs/ui-before.log` |
| the same with `--base http://localhost:8282 … --out build_jsplit4/laptop/ui-after` | 0 | 1373.44 | `build_jsplit4/laptop/logs/ui-after.log` |
| `node tests/ui_parity_browser.mjs --compare …/ui-before …/ui-after --sets S0,S2,S3 --out …/ui-diff` | 1 (2 Classic pictures over their noise budget; noise, below) | 11.7 | `build_jsplit4/laptop/logs/ui-compare.log` |
| base rerun of those 2 cases (`--cases s3_card_390x844_canvas,s3_card_390x844_dpr2_flat --worlds classic`) | 0 | 1146.72 | `build_jsplit4/laptop/logs/ui-before-rerun.log` |
| head rerun of those 2 cases | 0 | 1168.29 | `build_jsplit4/laptop/logs/ui-after-rerun.log` |
| `--compare` base vs base rerun (2 cases) | 1 (the canvas card differs base vs base) | 2.05 | `build_jsplit4/laptop/logs/ui-compare-aa.log` |
| `--compare` head vs head rerun (2 cases) | 1 (the dpr2-flat card differs head vs head) | 2.22 | `build_jsplit4/laptop/logs/ui-compare-aa-head.log` |
| `--compare` base rerun vs head (2 cases) | 1 (the dpr2-flat card, as head's first run) | 2.19 | `build_jsplit4/laptop/logs/ui-compare-rerun-ab.log` |
| `--compare` base rerun vs head rerun (2 cases) | **0 (PASS, 4/4 identical)** | 0.78 | `build_jsplit4/laptop/logs/ui-compare-rerun-bb2.log` |
| `node tests/ui_parity_browser.mjs --base http://localhost:8283 --layout site --smoke --out …/site-smoke` | 0 | 227.54 | `build_jsplit4/laptop/logs/site-smoke.log` |
| `locked_node tests/ocean_render_browser.mjs --base http://localhost:8281/web --main-base http://localhost:8281/web --parts offimage --query renderOpt=0 --main-query renderOpt=0 --out …/offimage-aa` | 0 | 431.28 | `build_jsplit4/laptop/logs/offimage-aa.log` |
| the same with `--base http://localhost:8282/web` (A/B), `--out …/offimage-ab` | 0 | 302.13 | `build_jsplit4/laptop/logs/offimage-ab.log` |
| `locked_node tests/ocean_render_browser.mjs --base http://localhost:8282/web --parts correctness,slots,noperf,missing,faults,timer,beam,iframe,gate --out …/render` | 0 | 1183.8 | `build_jsplit4/laptop/logs/render-head.log` |
| `locked_node tests/ocean_render_browser.mjs --base http://localhost:8282/web --parts correctness,iframe,gate --query renderOpt=0 --out …/reference-head` | 1 (the 3 known failures only) | 2640.44 | `build_jsplit4/laptop/logs/reference-head.log` |
| the same with `--base http://localhost:8281/web --out …/reference-base` | 1 (the same 3) | 109.85 | `build_jsplit4/laptop/logs/reference-base.log` |
| `locked_node tests/ocean_body_gpu.mjs --base http://localhost:8282` | 0 | 46.9 | `build_jsplit4/laptop/logs/body-gpu.log` |
| `node tools/ocean_render_perf/smoke.mjs --web http://localhost:8282/web --root http://localhost:8282` | 0 | 327.99 | `build_jsplit4/laptop/logs/perf-smoke.log` |
| `locked_node build_jsplit4/display_check.mjs http://localhost:8281 …/display-base.json` | 0 | 114.59 | `build_jsplit4/laptop/logs/display-base.log` |
| the same on `http://localhost:8282` → `display-head.json` | 0 | 115.17 | `build_jsplit4/laptop/logs/display-head.log` |
| the same on `http://localhost:8281` again → `display-base2.json` | 0 | 128.19 | `build_jsplit4/laptop/logs/display-base2.log` |
| `node build_jsplit4/compare_display.mjs display-base.json display-head.json` | **0 (0 of 2200 differ)** | 0.17 | `build_jsplit4/laptop/logs/display-compare-ab.log` |
| `… display-base.json display-base2.json` (A/A) | 1 (1 animation-timing leaf) | 0.13 | `build_jsplit4/laptop/logs/display-compare-aa.log` |
| `… display-head.json display-base2.json` | 1 (the same leaf) | 0.13 | `build_jsplit4/laptop/logs/display-compare-ba2.log` |

Browser wall seconds include waiting for the shared lock. `locked_node` is `scratchpad/locked_node.mjs`, the plan's external-lock wrapper; the UI harness and the page smoke lock themselves. The browser runs set `BROWSER_LOCK_POLL_MS=1000`, a faster poll of the same lock: it still only waits and never deletes. Raw records: `build_jsplit4/laptop/gates.jsonl`.

The extraction audit (`build_jsplit4/audit.cjs`) checks the following. It is source and owner-probe evidence; the browser gates below are the integration evidence.

- **Moved bodies.** All 12 moved functions are token- and character-equal to base after the ledgered ports and the two casts, and none uses `this` of its own.
- **Phases.** All 9 phase bodies equal their base statements, with the 2 IIFEs kept whole.
- **Comments.** All 18 base comments are present, in order, and no other comment was added (JSDoc annotations aside).
- **Module shell.** The factory's exact statement sequence is in base order. Only the colour-state initializers run at construction. The API is exact; registration is a single factory; there are 36 function-like nodes.
- **Listeners.** The 6 listener registrations are in base order, all in the bubble phase (no options argument), as in base.
- **Root and controllers.** Root equals base plus the exact ledger. Inspector, Tour and Readouts equal base plus their 11 owner qualifications. No owned name remains bare anywhere (no orphan or duplicate), and there is exactly one owner. The 17 stable ports are by reference and the 9 live getters are exact. Inspector holds the owner getter; Readouts and Tour hold `display: display` and no transitional port.
- **Inert registration and construction.** A VM whose `window`, `document`, `performance`, `localStorage`, `sessionStorage`, `location`, timers, `queueMicrotask`, `requestAnimationFrame`, `Math`, `Promise`, `URLSearchParams` and `crypto` all throw shows that registration and construction touch none of them, nor any port.
- **Behavioural probes,** run in the page's phase order:
  - `initLight` performs exactly the one follow-light preference read.
  - `initColourMode` and `loadClarity` read their preferences when called and paint the same DOM writes.
  - The follow-light switch takes its value from the preference.
  - `onFollowChange(true/false)` is one synchronous call with base's exact operation sequence, ending in the keys legend, and schedules no timer or microtask. A stored `"0"` keeps the light off; the default turns it on.
  - After replacing the engine and the scene, a colour click and a clarity input reach the **current** engine and scene, not the old ones.

## Turbo, built site and protected artifacts

- **Base: 604/604**, runner 325.0 s (wall 325.131 s), full command, no subset arguments, cwd `jsplit4_base`.
- **Head: 604/604**, runner 296.2 s (wall 296.285 s), the same.

`verify_evidence.py` confirms exit 0 on both, identical sequences of the 79 section headings, and the final `no unhandled promise rejection` check on both. Scene recording **59/59**, unchanged: 465 frames, sha256 prefix **ff2f626dc192c801**, the same as PR 3.

Site assembly:

- adds Display to `SRC`, publishes `OCDISPLAY`, rewrites its literal script tag (`n23`) and raises Ocean **22 → 23**; Classic and the body viewer stay **13 / 6**.
- Source and built synchronous order: dashboard → Readouts → Inspector → **Display** → Tour → root → guide.
- No new `EVO_ASSETS` entry is needed.

The built-site checker verifies:

- one `assets/ocean_display.<12 lowercase hex>.js` tag in each Ocean alias, with the source and built order;
- 19 script tags on each built page, all under `assets/`;
- bytes equal to source;
- every published asset's name equal to its SHA-256 prefix;
- no bare controller URL;
- byte-identical `index.html` and `ocean.html`;
- the Classic and body routes, the Classic redirect, and resolution of every local script, style, image, engine, worker, helper, Three and body-fixture resource;
- the builder comment's tag count against the real count.

Published Display asset: `assets/ocean_display.6efa14cf9980.js`, full SHA-256 `6efa14cf998081bed1ba019cfc7d356cf4801027a12d2bafaf3d1f162aa04faa`.

Protected paths: `verify_unchanged.py` checks `git diff --check` (rerun against b833734 after the commit, so the new file is covered) and the six module hashes against the base record. It also checks zero diff in:

- `src/` (plane headers included);
- the Wasm C++ wrappers;
- `tests/ocean_baseline/`;
- `tests/fixtures/`;
- `tests/ocean_mock_three_tests.mjs`, including GOLDEN.

| Module | Base = head SHA-256 |
| --- | --- |
| `web/evo_boids.js` | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` |
| `web/evo_boids.wasm` | `d05c4442e15d6850aeece60e52c2a69289d10a2d39fd17538b2347123be0a99b` |
| `web/evo_boids_mt.js` | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` |
| `web/evo_boids_mt.wasm` | `1c86e3d2a8c043e17ab1e75004ad37d9d20a70ce5498a80e4ae4bf4fdd8a703b` |
| `web/evo_ocean.js` | `8bdce72bd8991c6e88768712b60cec9b7dd0cf22335d82ebe67f40cef6d91059` |
| `web/evo_ocean.wasm` | `e55a4fcb2e7c2e737c6f0cc838c783237ba138336f1162ab4ddf037468b5f2f1` |

## Mutation sensitivity

`python3 build_jsplit4/mutations.py` builds **11 disposable mutants** under `build_jsplit4/mutants/` only, one per requested fault plus variants. Each source mutant tree is a real copy of `web/`, real copies of the two runtime test files, and symlinks for the rest; head and base files stay untouched.

Each of the 10 source mutants runs through three gates:

- the extraction audit, which must reject it with the named diagnostic;
- `node tests/ui_inspector_tests.cjs`;
- `node tests/ocean_turbo_handoff.js pageColourBench pageFollowBack pageModelineDetail` (the Turbo page sections on colour, follow and modeline: 21 checks).

The site mutant runs through the built-site checker. That makes 31 sub-gates in all; every result is in `build_jsplit4/logs/mutation-results.json`.

| Mutant | Fault | Audit (diagnostic) | Inspector page test | Turbo colour/follow/modeline |
| --- | --- | --- | --- | --- |
| (a1) `a1-follow-settimeout` | `onFollowChange` body deferred with `setTimeout(0)` | **rejects** (`onFollowChange token body`) | passes 95/95 | **fails** 19/21 (the lamp after a follow across Turbo) |
| (a2) `a2-follow-microtask` | `onFollowChange` body deferred to a microtask | **rejects** (`onFollowChange token body`) | passes 95/95 | **fails** 20/21 |
| (b1) `b1-stale-engine` | the colour switch tests an engine captured when the controls were wired | **rejects** (`setColourMode token body`) | **fails** 94/95 (capture not set again) | **fails** 19/21 (the scene's skin stays in Appearance) |
| (b2) `b2-stale-scene` | the display switches use a scene captured when the colour controls were wired | **rejects** (`applyDisplaySwitches token body`) | passes 95/95 | **fails** 19/21 |
| (c1) `c1-clarity-order` | `pointerup` registered before `input` | **rejects** (`complete phase tokens wireClarity`) | passes | passes 21/21 |
| (c2) `c2-clarity-capture` | `pointerup` registered in the capture phase | **rejects** (`complete phase tokens wireClarity`) | passes | passes |
| (c3) `c3-clarity-early` | the clarity listeners registered at the light phase (root order) | **rejects** (`root differs beyond exact phase/delegation/port ledger`) | passes | passes |
| (d1) `d1-colour-registration` | the colour preference read at module registration | **rejects** (`complete phase tokens initColourMode`) | passes | passes |
| (d2) `d2-colour-construction` | the colour IIFE run at construction (2237) instead of 3238 | **rejects** (`factory statement sequence`) | passes | passes |
| (e1) `e1-followlight-default` | `followLight` not read from its preference | **rejects** (`complete phase tokens initLight`) | passes | passes |
| (f) `f-missing-built-tag` | the Display tag removed from both built aliases | n/a | n/a | built-site checker **rejects** (`missing/repeated/bare tag`, `ocean_display.js`) |

All 11 mutants are rejected by an established gate, so **no mutant escapes and there is no finding**. The runtime columns show where the existing Node tests also notice:

- they catch the deferred follow callback and the stale engine/scene;
- they do not observe listener order or phase, preference-read timing, or the follow-light preference (c, d, e). Those rest on the audit's exact-body/phase/probe checks.

The laptop display interaction script exercises the follow-light preference after a reload in a real browser (below).

## Laptop browser gates

Setup:

- **Servers** (WSL, `python3 wasm/serve.py`): base `jsplit4_base` on **8281**, the head repository root on **8282**, the head `dist/` on **8283**. All three are stopped now.
- **Browser**: Windows Node v26.1.0, Playwright from `C:/Users/harit/gemini_bridge/node_modules/playwright`, Brave headless.
- **Lock**: every run held the machine-wide lock, one browser job at a time. Outputs are under `build_jsplit4/laptop/`.
- **Harness**: the head's harness was used for both sides of each comparison, as PR 3's commands did, so only the served page differs. The render evidence manifest hashes the local checkout, so its `hashes` are the head's even on base-origin runs.

**Interruptions** (no gate result was affected):

- During the usage-limit pause the harness reaped the first server set and the first queued base capture for low memory. That capture had not yet got the lock, so nothing was captured. Both were restarted (`--clean` on the untouched output).
- From about 5:07 to 5:47 AM ET the lock was held by a deadlocked process of another job: `locked_node.mjs` wrapping `tools/ocean_render_perf/smoke.mjs` for port 8302 (PID 11760; its child smoke, PID 14092, waited for its parent's lock). Its owner cleared it, and the queued reference run then proceeded. I did not touch it.

| Gate | Result |
| --- | --- |
| UI parity S0, S2, S3 | Base and head each: **38 case runs, 99 captures**, complete. Strict `--compare`: **97 identical, 2 beyond policy** (both Classic pictures, explained below). After the base-vs-base and head-vs-head reruns, **base rerun vs head rerun: PASS, 4/4 identical**. |
| Site smoke (8283, `--layout site --smoke`) | **3 smoke runs ok**: `classic.html`, Ocean `/` and alias `/ocean.html`. No console error or warning, page error, failed request or HTTP error. |
| Off-image A/A (base vs base, reference policy on both roles) | **all passed (71 checks)** |
| Off-image A/B (head vs base, the same policies) | **all passed (71 checks)**, the same 71 as A/A, with the existing tolerances (its differing-pixel figures are the same on A/A and A/B, max 114403 in the checks that expect a difference) |
| Render parts on head (`correctness,slots,noperf,missing,faults,timer,beam,iframe,gate`) | **all passed (137 checks)** |
| Reference command (`correctness,iframe,gate`, `?renderOpt=0`) | Head **58/61**, base **58/61**. The same 3 failures on both: `live decoded texture, family / brain / appearance colours … {"checked":false,"reason":"the decoded cache is not asked for"}` (the reference policy never builds the decoded cache). The two runs' 61 check names and statuses are identical (numbers normalized). Head fails exactly those 3 and nothing else. |
| Body GPU (head 8282) | **BODY GPU CHECK: all passed (20 checks)**, including the real controller's preview-off/preview-on checks |
| Page smoke (source layout, head) | **ok: 5 pages without a console message** (Ocean default, `?renderOpt=0`, family colours, Classic, body plan) |
| Display interactions (base, head, base) | **base vs head: 0 of 2200 recorded leaves differ.** Base vs base: 1 (noise, below). |

**UI parity differences.** Two pictures differ in the first base/head comparison: `s3_card_390x844_canvas__classic__card.png` (91 pixels) and `s3_card_390x844_dpr2_flat__classic__card.png` (2929 pixels).

Both are **Classic** pages, which load none of the changed files: `web/index.html` and every Classic script are byte-identical between base and head. In both pictures every differing pixel is off by at most one channel level: 0 beyond the tolerance of 1, over only the policy's 32-pixel noise budget.

The reruns show each picture flipping between two renderings on the same commit:

- the canvas card differs **base vs base** by the same 91 pixels;
- the dpr2-flat card differs **head vs head** by the same 2929 pixels;
- **the base rerun and the head rerun are identical** for all 4 pictures of the 2 cases.

So these are GPU/compositor rendering noise in Classic, not an effect of this extraction. The other 97 of 99 pictures (all 37 Ocean pictures and 60 of the 62 Classic ones) are identical.

**Display interaction script.** `build_jsplit4/display_check.mjs` uses a fresh headless profile per scenario; reloads within a scenario keep its storage. It records 2200 leaves of state per run.

It records:

- the colour mode, colour brain and the scene's skin;
- the pressed buttons and the colour explanation line;
- the flashlight button, switch and scene state, and the follow state and button;
- the "Light while following" switch;
- the clarity value, ARIA text, label and scene clarity;
- the modeline text and its `data-replay`/`data-why`;
- the keys legend and stat notes;
- the View/Help state and the View rect;
- the focused element, the stored preferences, and every toast as it appears.

The six scenarios:

1. **Colour.** The View popover by pointer (Family, Brain, Appearance); then by keyboard (V, Tab to Family plus Space, Tab to Brain plus Enter, Escape returns focus to the View button). The remembered choice survives a reload; `?colour=family` wins without being stored.
2. **Flashlight and "Light while following".** L on/off; the dock button; following with the default preference (light on, off again on release). The preference is switched off (stored `"0"`); following keeps the light off; L while following; release restores the pre-follow light. The preference switched back on while following applies at once. The View light switch is used while following. The preference stays off after a reload, and following then keeps the light off.
3. **Clarity.** Arrow keys (to 80 %), values 35, 0 (Realistic) and 60, then `pointerup` blur. The value is remembered after a reload; `?clarity=realistic` and `?clarity=25` win without being stored.
4. **Modeline and display switches.** Help's modeline; a live change (`EvoOcean.set("maxAge", 150)`, so the modeline says a setting was changed live, `data-replay="no"`). Colour changes with a fish picked (card shown, selection kept). Replay (Shift+R, confirmed) re-applies the display switches to the new world and resets the modeline.
5. **Turbo in and out.** Brain is kept into Turbo; changed to Family during Turbo; Family is kept out of Turbo (skin off); then L.
6. **Phone layout** (390×844, touch). The View popover and its position, Family, the light switch, clarity 50, close, the dock light button, and a reload.

Base and head match in every one of the 2200 leaves.

The A/A run (base vs base) differs in exactly one leaf: `phone.viewOpened.viewRect.1` (the View popover's top edge, 244 vs 252 px, read while its open animation runs). Head vs the second base run differs in the same leaf only. That is animation-timing noise in the measurement, which the A/A run exhibits.

There were no console errors or warnings and no page errors in any scenario of any run.

## Line counts

| File | Base | Head | Δ |
| --- | ---: | ---: | ---: |
| `web/ocean.js` | 3580 | 3418 | −162 |
| `web/ocean_display.js` | — | 222 | +222 |
| `web/ocean_inspector.js` | 457 | 457 | 0 |
| `web/ocean_tour.js` | 189 | 189 | 0 |
| `web/ocean_readouts.js` | 171 | 171 | 0 |
| `web/types.d.ts` | 1525 | 1578 | +53 |

- Root + Display: **3580 → 3640** (+60).
- All five controller files together: **4397 → 4457** (+60). The extra lines are the factory, its 9 phases, the slots, the ports and the API.
- Other files, each changed by one or a few lines: `wasm/build_site.sh` +6/−4, `tsconfig.json` +1, `web/ocean.html` +1, and the four test files +1/−1 each.

## Scratch tooling adaptations (all in `build_jsplit4/`, git-excluded)

- `run_gate.py`, `turbo_gates.py`, `node_gates.py`, `finish_gates.py`, `verify_evidence.py`: PR 3's, with the scratch prefix changed. The base side is the `jsplit4_base` worktree. There is no EPERM branch: the laptop runs the parity-harness unit test's child process.
- `record_base.py` (new): gate 1's record, including equality with the pristine base worktree.
- `extract.cjs`: PR 3's symbol-aware qualification and line-range ledger, adapted. Changes:
  - a strict top-level test (function declarations and `var` statements directly in the root IIFE; PR 3's three-level test would also have matched top-level functions' parameters);
  - an automatic free-variable check;
  - content-checked line ranges;
  - the partial-line state split;
  - exactly-once follow-ups;
  - owner edits derived from the pristine copies.
- `audit.cjs`: PR 3's strategy, adapted to this owner. Added: the comment-sequence check, the factory statement-sequence check, listener order and phase, the no-`this` check, a broader throwing host, and the behavioural probes.
- `wire.py`: exact once-only edits on pristine copies (HTML, builder, tsconfig, loaders, manifest, types). `display_types.txt` holds the owner's declarations. `type_edits.py`/`.json` hold the casts.
- `check_site.py`: Display added, 23/13/6, `OCDISPLAY`/`n23`, the 19-tag and comment checks.
- `verify_unchanged.py` takes the comparison ref. `verify_test_deltas.py` has this owner's edits and asserts that no other test file changed.
- `mutations.py`: this owner's faults and variants, with runtime gates on mutant trees.
- `mapping.cjs`, `ledger_tables.cjs`: the report's tables.
- `browser_gate.mjs`, `display_check.mjs`, `compare_display.mjs` (new): the Windows-side gate recorder, the display interaction script and its comparator.

Development corrections before acceptance:

- The extractor's first run stopped on two phase markers written in unqualified form; this was fixed before any output was used.
- The audit's first draft had a function-like count of 52 and a mislabelled listener count; both were corrected to the hand-checked 36 and 6 before its gate run.
- A first background launch of the Turbo gate died with its WSL session before running anything; it was relaunched in the foreground of a background task.

No acceptance gate failed because of an own-script mistake. No production code changed after the Node and type gates.

## Commit split

1. **`ab74528` `web: move the display controls out of ocean.js`** (atomic extraction): the new module; root delegations and phases; the Inspector, Readouts and Tour owner ports; concrete types and the checked-file entry; HTML and the hashed publisher; both VM loaders, the dependency list and the render hash manifest.
2. **`docs: ocean.js split PR 4 (Display) report`**: this file (the commit after `ab74528`).

No preparation commit was needed. `build_jsplit4/`, logs, mutants, `node_modules/` and `dist/` stay out of Git. No push, merge or deployment.

# Ocean controller split: PR 2, Inspector

Controller-only extraction from main **05b0a97349141819d7e5487b3d814cb07d5b63c8** (PR #100 merged). All changes are uncommitted on `ocean-js-split-2`; the coordinator owns commits and laptop acceptance. No network, browser, C++/Wasm build, merge, deployment or rebaseline was performed.

## Inventory and current-base mapping

`web/ocean_inspector.js` registers `window.EvoOceanInspector = { create: create }`. It owns selection/follow intent, the fish card and its portraits, brain and body views, the activation clock, and selection return after Turbo. `ocean.js` retains world transactions, playback, frame sequencing, input and ordered startup. `updateCard(s)` still returns the refreshed snapshot. The body cache key remains exactly `s.worldEpoch + ":" + id`.

The plan's citations refer to pre-Tour main 294fc8b. The following mapping was obtained by named function/content matching against the pristine **current base** in `build_jsplit2/base/`, not by subtracting a blanket offset. Inspector destinations include typing and factory/phase wrappers; the base columns are `web/ocean.js` lines.

| Function | Current base | `ocean_inspector.js` |
| --- | ---: | ---: |
| `pickedNow` | 1689–1692 | 70–73 |
| `indexOfId` | 2256–2260 | 75–79 |
| `randomFish` | 2261–2266 | 81–86 |
| `select` | 2278–2290 | 90–102 |
| `follow` | 2292–2303 | 104–115 |
| `unfollow` | 2304–2307 | 116–119 |
| `prettyName` | 2539–2539 | 128–128 |
| `brainShape` | 2540–2548 | 129–137 |
| `cardText` | 2549–2549 | 138–138 |
| `setBar` | 2550–2559 | 140–149 |
| `showCard` | 2560–2566 | 150–156 |
| `hideCard` | 2567–2573 | 157–163 |
| `placeCard` | 2574–2581 | 164–171 |
| `drawSwatch` | 2590–2599 | 183–192 |
| `keyTitle` | 2601–2605 | 194–198 |
| `inspect` | 2607–2619 | 201–213 |
| `overlap` | 2620–2623 | 214–217 |
| `updateCard` | 2624–2678 | 219–273 |
| `drawBody` | 2686–2737 | 284–335 |
| `drawBrain` | 2739–2750 | 338–349 |
| `updateSenseLine` | 2751–2765 | 350–364 |
| `nearestNode` | 2766–2771 | 366–371 |
| `returnPoint` | 3076–3086 | 387–398 |
| `restoreAfterTurbo` | 3087–3101 | 399–413 |
| `nearestOfFamily` | 3103–3121 | 416–435 |

| Owned state / callback | Current base lines | Treatment |
| --- | ---: | --- |
| `turboReturn` | 375 | Factory constructed at this exact root position; initializes its local slot to null. |
| `selectedId/wantFollow/everSelected` | 2221 | `initSelection()` at the original position. |
| Activation-clock comment and `brainClock` | 2267–2272 | `initBrainClock()` at the original position. |
| Card/context/portrait references, expansion/cache/placement, initial ARIA, names/nodes/hover/font/freshness | 2534–2538 | `initCard()` at the original position. |
| `swatchEl/skinEl` | 2589 | `initSwatch()`, after card initialization. |
| Body references and `bodyFor` | 2685 | `initBody()`, after swatch initialization. |
| Network pointer callbacks/listeners | 2772–2774 | `registerNetwork()`, after body initialization; move → down → leave, same target, no options (bubble phase). |
| Expand-button callback | 3581–3587 | Whole callback body becomes `toggleExpanded`; registration remains at the original control position. |

Comments describing the functions move with them, including the return-selection description at 3067–3075 and body-preview description at 2679–2684. Root header lines 1–79 remain byte-identical.

## Move ledger

The excluded, reviewable mechanical record is `build_jsplit2/move_ledger.json`: complete base fragments with current spans, every root replacement at its original character offset, the ordered post-replacements for phase/API wiring, and moved-body port substitutions. `build_jsplit2/port_occurrences.json` records the individual base line/column substitutions (190 lexical records: 121 in the inventory fragments, two in the expansion callback, 67 root identifier qualifications; later coalescing of reset statements and removal of transitional Tour ports is separately explicit in `move_ledger.json`). `function_mapping.json` supplies both function line maps. These scratch records are not committed.

| Boundary | Exact substitution / operation |
| --- | --- |
| Root → Inspector functions | Calls/references to the moved functions become `inspector.NAME`; export `inspect` also preserves the existing VM private-access seam. No root forwarding functions remain. |
| Root → current selection | Reads become `inspector.selectedId`, `inspector.everSelected`, `inspector.wantFollow`, `inspector.turboReturn`; `sensorNames/actionNames` likewise read live owner accessors. |
| Transaction reset | Each `selectedId = null; wantFollow = false;` becomes `inspector.resetSelection()`, whose body performs exactly those two assignments. Capture/restore of selection and `turboReturn` retains the existing copy/reference choices and statement order. |
| Follow intent and Turbo return | Explicit `wantFollow` and `turboReturn` getter/setter pairs retain individual writes. Changes to the return object's `follow` field still mutate that same object at the same sites. No generic state/context or restore-object API was introduced. |
| Clock calls | Root `brainClock.reset` / `.capture` become `inspector.resetBrainClock` / `.captureBrainClock`; wrappers call the owned clock with unchanged arguments. |
| Inspector → root stable operations/data | `el`, `has`, `syncedFrame`, `turboPictureHint`, `engineCall`, `fresh`, `setStatPanel`, `cfgVal`, `STATS`, `ACTION_SHORT`, `ACTION_LABELS`, `coarseMQ`, `heap`, `cString`, `toast` become `ports.NAME`. Local `drawSwatch` W/H remain local. |
| Inspector → replaceable/current root bindings | `M`, `engineState`, `turboState`, `lastS`, `scene`, `colourMode`, `statOpen`, `paused`, `BODY_LAYOUT`, `HO`, `worldEpoch`, `WALLS`, `W/H/D` use explicit live getters. No getter syncs or refreshes. Engine/scene operations retain their existing ready-world preconditions, documented on the concrete port type. |
| Inspector → root writes | `cardNewer/cardHeld/dirtyHud` use explicit getter/setter ports; assignment order stays literal. Those layer/readout flags stay root-owned in this PR. |
| Inspector → Tour | `tour.hideCoach()` becomes `ports.hideCoach()`; the port calls the current Tour method. |
| Tour → Inspector | `p.selectedId`, `p.cardEl`, `p.select(...)` become `p.inspector.selectedId`, `p.inspector.cardEl`, `p.inspector.select(...)`. Root passes the Inspector instance directly. Transitional root selection/card getters and the old select port are removed; the concrete Tour port is a `Pick` of the three owner members. |
| Initialization | Lift declarations into private typed slots; original declaration initializers become assignment statements inside explicit phases. No initializer moves across an executable host operation. Card → swatch → body → network order is unchanged. |
| Expand control | `btn("iexpand", function () { BODY })` becomes `btn("iexpand", inspector.toggleExpanded)`; BODY is unchanged except the two `el` qualifications. |

`OceanInspectorPorts`, owner/result/selection/body-layout types and the Inspector global are in `web/types.d.ts`; the scene's existing following/setFollow/project methods are declared there. The new file starts with `// @ts-check` and is listed in `tsconfig.json`. No blanket `any` port or type-check suppression was added.

Type-only additions in moved bodies are JSDoc annotations and the exact casts below. Parentheses group the same expression; no branch, value, call count or argument changes. The audit erases only this finite cast list before token comparison:

- `inetCanvas.getContext("2d")`, `swatchEl.getContext("2d")` → `CanvasRenderingContext2D`.
- `bar.firstElementChild`, `inetCanvas.parentNode`, `ports.el("isense").querySelector("b")` → `HTMLElement`.
- `bar.querySelector(".tick")` → `HTMLElement | null`.
- `sensorNames`, `actionNames` at their already-initialized uses → `string[]`.
- `r.id` initializing a variable later allowed to hold null → `number | null`; nullable `best` in the existing distance tie expression → `number`.

Both controller VM loaders, common HTML dependency-order list and render evidence hash manifest include Inspector. Turbo's injected selection getter, read/write `turboReturn` seam and `inspect` reference point at the owner. The start-door, memory-install and URL source scanners continue to inspect unchanged root implementations; no scanner generalized for a future owner. Mock-three's scene-only load list, file and GOLDEN are untouched. No existing assertion or Turbo section/runner/cleanup code was removed.

## Plan deviations

- The executable inventory omits the expand-button callback, which writes Inspector-owned expansion/cache state. Moved that complete body as `toggleExpanded`; kept its button registration in root at the original position. Exposing writable cache/DOM state to root would widen the boundary unnecessarily.
- Strict checked JavaScript needs the inert casts listed above and annotations for lifted slots/results. This follows PR 1's documented type-only treatment; the finite normalization list is part of the audit.
- Declare only the introduced Inspector global/types, not speculative APIs for later PRs.
- The plan's span tables are ownership inventories. Match by content and retain untouched header/separators outside the explicitly ledgered moves.

No preparation change or preparation commit is needed: PR 1 already supplied the off-image `--main-query` fix and policy assertions. There is no lifecycle redesign, UI change, cleanup or simulation change.

## Server gate record

Base record: `build_jsplit2/logs/base.json`, Node **v26.13.0**, npm **11.20.0**, full commit above and six hashes below, checked against the pristine copy before extraction. The initial record command used `git rev-parse HEAD`, `node --version`, `npm --version` and Python SHA-256 reads (exit 0; tool wall time 0.158 s).

Gates run through `python3 build_jsplit2/run_gate.py NAME CWD COMMAND...`, at **nice 19**, with `JOBS=2`, `BUILD_JOBS=2`, `OMP_NUM_THREADS=2`, `OPENBLAS_NUM_THREADS=2`, `MKL_NUM_THREADS=2`, `UV_THREADPOOL_SIZE=2`, `NODE_OPTIONS=--v8-pool-size=2`. Full Turbo runs are sequential. At most two top-level jobs overlap; the unmodified lock unit test itself starts its existing lightweight contender processes. No browser was started. `$ROOT` in the table means this worktree's absolute path; the offline cache is `$ROOT/build_jsplit2/npm_cache`.

The extraction audit compares all **25 inventory functions and 31 recursively nested functions/callbacks**, plus the three network callbacks/listener statements and expansion callback. It also checks character equality after only the finite ledgered casts/annotations and qualifications, all 55 resulting functions/callbacks/accessors and the exact construction statement forms. It checks six initialization/registration phases, the exact remaining root against base plus the substitution ledger, Tour against only its three qualified ports, absence of root orphan bindings/functions, live owner accessors, and Inspector/Tour registration/construction in a VM whose port reads and DOM/timer/storage/randomness operations throw. It does not replace real browser integration evidence.

| Command | Exit / status | Wall seconds | Log |
| --- | --- | ---: | --- |
| Inline Python pre-extraction base record (`git rev-parse HEAD`, `node --version`, `npm --version`, six SHA-256 reads) | 0 | 0.158 | `build_jsplit2/logs/base.json` |
| `node build_jsplit2/audit.cjs` | 0 | 1.878 | `build_jsplit2/logs/audit.log` |
| `node tests/ui_common_tests.cjs` | 0 | 0.157 | `build_jsplit2/logs/ui_common_tests.log` |
| `node tests/ui_parity_harness_tests.mjs` | 1 ENVIRONMENT-BLOCKED | 13.498 | `build_jsplit2/logs/ui_parity_harness_tests.log` |
| `node tests/ui_inspector_tests.cjs` | 0 | 3.692 | `build_jsplit2/logs/ui_inspector_tests.log` |
| `node tests/ocean_appearance_slots_tests.cjs` | 0 | 0.738 | `build_jsplit2/logs/ocean_appearance_slots_tests.log` |
| `node tests/ocean_shader_slots_tests.cjs` | 0 | 0.256 | `build_jsplit2/logs/ocean_shader_slots_tests.log` |
| `node tests/ocean_materials_tests.cjs` | 0 | 0.471 | `build_jsplit2/logs/ocean_materials_tests.log` |
| `node tests/ocean_render_opt_tests.cjs` | 0 | 0.156 | `build_jsplit2/logs/ocean_render_opt_tests.log` |
| `node tests/ocean_mock_three_tests.mjs` | 0 | 32.834 | `build_jsplit2/logs/ocean_mock_three_tests.log` |
| `node tests/ocean_perf_tests.cjs` | 0 | 0.118 | `build_jsplit2/logs/ocean_perf_tests.log` |
| `node tests/ocean_render_perf_lock_tests.mjs` | 0 | 15.625 | `build_jsplit2/logs/ocean_render_perf_lock_tests.log` |
| `node tests/ocean_render_query_tests.cjs` | 0 | 0.083 | `build_jsplit2/logs/ocean_render_query_tests.log` |
| `node build_jsplit2/environment.cjs` | 1 ENVIRONMENT-BLOCKED | 0.144 | `build_jsplit2/logs/ui-parity-environment.log` |
| `npm ci --offline --cache $ROOT/build_jsplit2/npm_cache --no-audit --no-fund` | 0 | 0.842 | `build_jsplit2/logs/npm-ci.log` |
| `npx --offline --cache $ROOT/build_jsplit2/npm_cache tsc -p tsconfig.json` | 0 | 4.383 | `build_jsplit2/logs/types.log` |
| `node build_jsplit2/audit.cjs` | 0 | 2.036 | `build_jsplit2/logs/audit-api.log` |
| `node build_jsplit2/audit.cjs` | 0 | 1.897 | `build_jsplit2/logs/audit-shell.log` |
| `node tests/ocean_turbo_handoff.js` (cwd `build_jsplit2/base`) | 0 | 336.524 | `build_jsplit2/logs/turbo-base.log` |
| `node build_jsplit2/audit.cjs` | 0 | 1.993 | `build_jsplit2/logs/audit-final.log` |
| `npx --offline --cache $ROOT/build_jsplit2/npm_cache tsc -p tsconfig.json` | 0 | 4.409 | `build_jsplit2/logs/types-final.log` |
| `node build_jsplit2/audit.cjs` | 0 | 2.851 | `build_jsplit2/logs/audit-characters.log` |
| `node tests/ocean_turbo_handoff.js` | 0 | 326.174 | `build_jsplit2/logs/turbo-head.log` |
| `bash wasm/build_site.sh` | 0 | 0.701 | `build_jsplit2/logs/site-build.log` |
| `python3 build_jsplit2/check_site.py` | 0 | 0.143 | `build_jsplit2/logs/site-check.log` |
| `python3 build_jsplit2/verify_unchanged.py` | 0 | 0.539 | `build_jsplit2/logs/unchanged.log` |
| `node $ROOT/build_jsplit2/audit.cjs $ROOT/build_jsplit2/mutants/a-stale-selectedId` (cwd `$ROOT`) | 1 expected rejection | 2.382 | `build_jsplit2/logs/mutant-a-stale-selectedId.log` |
| `node $ROOT/build_jsplit2/audit.cjs $ROOT/build_jsplit2/mutants/b-network-order` (cwd `$ROOT`) | 1 expected rejection | 2.423 | `build_jsplit2/logs/mutant-b-network-order.log` |
| `node $ROOT/build_jsplit2/audit.cjs $ROOT/build_jsplit2/mutants/b-network-phase` (cwd `$ROOT`) | 1 expected rejection | 2.338 | `build_jsplit2/logs/mutant-b-network-phase.log` |
| `node $ROOT/build_jsplit2/audit.cjs $ROOT/build_jsplit2/mutants/c-missing-restore` (cwd `$ROOT`) | 1 expected rejection | 2.446 | `build_jsplit2/logs/mutant-c-missing-restore.log` |
| `node $ROOT/build_jsplit2/audit.cjs $ROOT/build_jsplit2/mutants/d-body-without-epoch` (cwd `$ROOT`) | 1 expected rejection | 1.939 | `build_jsplit2/logs/mutant-d-body-without-epoch.log` |
| `python3 $ROOT/build_jsplit2/check_site.py $ROOT/build_jsplit2/mutants/e-missing-built-tag` (cwd `$ROOT`) | 1 expected rejection | 0.215 | `build_jsplit2/logs/mutant-e-missing-built-tag.log` |
| `python3 build_jsplit2/mutations.py` | 0 | 12.221 | `build_jsplit2/logs/mutations.log` |
| `node build_jsplit2/audit.cjs` | 0 | 2.893 | `build_jsplit2/logs/audit-complete.log` |
| `node --check tests/ocean_render_browser.mjs` | 0 | 0.053 | `build_jsplit2/logs/browser-manifest-syntax.log` |
| `python3 build_jsplit2/verify_unchanged.py` | 0 | 0.552 | `build_jsplit2/logs/unchanged-final.log` |

Full Turbo results (no subset arguments):

- **Base: 604/604**, exit 0; runner 336.1 s, measured wall 336.524 s.
- **Head: 604/604**, exit 0; runner 325.8 s, measured wall 326.174 s.

Both logs contain the same full sequence of section headings (79), all sections' existing cleanup, and the final successful `no unhandled promise rejection` check. The section registry and runner are unchanged. Scene recording: **59/59**, unchanged reference recording prefix **ff2f626dc192c801** (465 frames, 6170 draws, 9231 uploads, 16 programs); GOLDEN was not edited. All runnable Node/type/site/protected-path checks pass; the UI harness unit gate remains environment-blocked.

The UI harness unit command is **ENVIRONMENT-BLOCKED**, not passed: `node tests/ui_parity_harness_tests.mjs` cannot validate its child invocations in this sandbox. The separate diagnostic records `spawnSync /home/harit/opt/node-v26.13.0-linux-x64/bin/node EPERM` (errno -1), empty child stdout/stderr, for the exact child command `node tests/ui_parity_browser.mjs --plan --sets S0,S2`. No workaround or modification to that test was applied. Rerun the original unit command outside the sandbox. The acceptance table includes the diagnostic command and log.

Development-only tooling corrections before acceptance: renamed a scratch CJS variable that collided with `module`, supplied the cached TypeScript library declarations to the scratch development checker, and removed an unused repeated parse from the draft audit. These did not change production behavior. No acceptance gate failed because of an own-script mistake; no gate failure was bypassed or reclassified as a pass. The draft audit was strengthened with live-accessor, construction-shell and character comparisons; its positive reruns are recorded. A final type-only DOM query cast was made explicit as `HTMLElement | null`, and audit/types reran successfully before the head Turbo evidence.

## Built site and protected artifacts

The atomic builder change adds Inspector to `SRC`, publishes `OCINSPECTOR` with the existing publisher, adds one literal tag rewrite and increments Ocean **20 → 21**; Classic/body viewer remain **13/6**. The synchronous source order is dashboard → Inspector → Tour → root → guide. The new controllers need no `EVO_ASSETS` entry.

The built-site checker verifies one correctly shaped `assets/ocean_inspector.<12 lowercase SHA-256 hex>.js` tag per Ocean alias, source/built script order, source bytes, hash prefixes for every published asset, no bare new-controller URL, byte-identical `index.html`/`ocean.html`, Classic and body-viewer pages, the Classic redirect, and resolution of local script/style/image and engine/worker/helper/Three/body-fixture references. Inline `data:` resources and the existing development-only `mock: ocean_mock.js` value are treated explicitly. HTTP responses, headers and runtime loading remain laptop checks.

`verify_unchanged.py` checks the six hashes against the pre-extraction record, `git diff --check`, and zero protected diff for `src/` (including plane headers), Wasm C++ wrappers, generated modules, baselines, fixtures and the whole mock-three file containing GOLDEN. No generated file was hand-edited or rebuilt.

| Module | Base = head SHA-256 |
| --- | --- |
| `web/evo_boids.js` | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` |
| `web/evo_boids.wasm` | `d05c4442e15d6850aeece60e52c2a69289d10a2d39fd17538b2347123be0a99b` |
| `web/evo_boids_mt.js` | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` |
| `web/evo_boids_mt.wasm` | `1c86e3d2a8c043e17ab1e75004ad37d9d20a70ce5498a80e4ae4bf4fdd8a703b` |
| `web/evo_ocean.js` | `8bdce72bd8991c6e88768712b60cec9b7dd0cf22335d82ebe67f40cef6d91059` |
| `web/evo_ocean.wasm` | `e55a4fcb2e7c2e737c6f0cc838c783237ba138336f1162ab4ddf037468b5f2f1` |

Line counts: root `ocean.js` **4026 → 3692** (−334); new `ocean_inspector.js` **457**; Tour **189 → 189**. Root + Inspector: **4026 → 4149** (+123 factory/phase/port/type lines); including Tour: **4215 → 4338**. Extra lines implement boundaries and typing, not new UI behavior.

## Mutation sensitivity

`python3 build_jsplit2/mutations.py` makes independent disposable copies under `build_jsplit2/mutants/` only. Expected nonzero gate exits are mutant rejections, not head failures. The original base/head files are not mutated.

| Requested mutation | Rejecting established server gate | Diagnostic |
| --- | --- | --- |
| (a) Capture `selectedId` in a Tour port object during construction instead of passing Inspector's live accessor | Extraction audit (gate 2) | Root differs from exact delegation/port ledger. |
| (b) Reverse network pointermove/pointerdown registration order | Extraction audit | `phase registerNetwork` ordered-fragment mismatch. |
| (b), second variant: pointerdown uses capture phase | Extraction audit | `phase registerNetwork` options mismatch. |
| (c) Drop `restoreAfterTurbo` from ordinary Turbo hand-back | Extraction audit | Root differs from exact delegation/port ledger. |
| (d) Omit world epoch from body cache key | Extraction audit | `drawBody body` token mismatch. |
| (e) Remove the new hashed tag from both built Ocean aliases | Built-site checker (gate 6) | Inspector missing/repeated/bare tag. |

**All six disposable mutants were rejected** (five requested categories). Per-mutant commands, exits, times and logs are in the gate table; `build_jsplit2/logs/mutation-results.json` records the results and `build_jsplit2/logs/mutations.log` is the overall passing runner. These are source/packaging sensitivity results; they do not claim existing runtime Node tests alone observe every interaction. No requested mutant escapes a server gate, so there is no uncaught-mutant browser finding. The laptop acceptance work below remains required.

## Laptop commands and interactions (not run on this server)

Use the candidate's same harness/fixtures for both sides. Configure the laptop's `PLAYWRIGHT`, `BRAVE_EXE` and machine-wide `BROWSER_LOCK` as usual. Use fresh output folders when rerunning; do not deploy. Serve base, head and assembled site in separate terminals:

```bash
python3 wasm/serve.py build_jsplit2/base 8261
python3 wasm/serve.py . 8262
python3 wasm/serve.py dist 8263

# Rerun the environment-blocked server unit command outside the sandbox.
node tests/ui_parity_harness_tests.mjs

# UI identity: strict comparison, including S3 responsive Inspector cases.
node tests/ui_parity_browser.mjs --base http://localhost:8261 --layout source --sets S0,S2,S3 --expect record --out build_jsplit2/laptop/ui-before
node tests/ui_parity_browser.mjs --base http://localhost:8262 --layout source --sets S0,S2,S3 --out build_jsplit2/laptop/ui-after
node tests/ui_parity_browser.mjs --compare build_jsplit2/laptop/ui-before build_jsplit2/laptop/ui-after --sets S0,S2,S3 --out build_jsplit2/laptop/ui-diff

# Site-layout smoke takes the lock internally.
node tests/ui_parity_browser.mjs --base http://localhost:8263 --layout site --smoke --out build_jsplit2/laptop/site-smoke
```

Render-browser and body GPU need the external lock; do not wrap internally locking tools:

```bash
locked_node() {
  node --input-type=module -e 'import { acquire } from "./tools/ocean_render_perf/lock.mjs"; import { spawn } from "node:child_process"; const release = await acquire("ocean.js split PR2 checks"); try { const code = await new Promise((resolve, reject) => { const child = spawn(process.execPath, process.argv.slice(1), { stdio: "inherit" }); child.on("error", reject); child.on("exit", c => resolve(c ?? 1)); }); process.exitCode = code; } finally { release(); }' "$@"
}

# A/A first: base vs the same base; reference policy explicitly on both roles.
locked_node tests/ocean_render_browser.mjs --base http://localhost:8261/web --main-base http://localhost:8261/web --parts offimage --query renderOpt=0 --main-query renderOpt=0 --out build_jsplit2/laptop/offimage-aa

# Then base vs head, retaining both explicit policy queries and all tolerances.
locked_node tests/ocean_render_browser.mjs --base http://localhost:8262/web --main-base http://localhost:8261/web --parts offimage --query renderOpt=0 --main-query renderOpt=0 --out build_jsplit2/laptop/offimage-ab

locked_node tests/ocean_render_browser.mjs --base http://localhost:8262/web --parts correctness,slots,noperf,missing,faults,timer,beam,iframe,gate --out build_jsplit2/laptop/render

# Record the known reference-command failures on base, then compare head.
locked_node tests/ocean_render_browser.mjs --base http://localhost:8261/web --parts correctness,iframe,gate --query renderOpt=0 --out build_jsplit2/laptop/reference-base
locked_node tests/ocean_render_browser.mjs --base http://localhost:8262/web --parts correctness,iframe,gate --query renderOpt=0 --out build_jsplit2/laptop/reference-head

locked_node tests/ocean_body_gpu.mjs --base http://localhost:8262

# Source-layout page smoke takes the lock internally.
node tools/ocean_render_perf/smoke.mjs --web http://localhost:8262/web --root http://localhost:8262
```

The coordinator reports that the reference command has three **live decoded texture** failures identically on main: reference policy never builds the decoded cache. Compare that command against base; do not attribute those existing failures to this extraction or relax the checks. Off-image A/A and A/B still require matching reference policies. Body GPU's real-controller bridge uses source `/web/ocean.html`; site-layout smoke covers built routes. Plan §5 E–I is skipped on this server; no deployment is requested.

Retain first-visit and inspection interaction coverage alongside pictures:

- Fresh visitor/storage; first hint, coach timing/suppression, Tour and Turbo intro from Help; lazy coarse-input content and Escape/focus return.
- Select fish, follow/unfollow, fish death/handover, close/release; pause and single step; card expand/collapse; brain mouse hover and touch node selection.
- Body view off/on, same fish ID reused in a new world (epoch cache invalidation), correct body ownership and fixture link.
- Turbo enter/return with selected/followed fish, death/nearest-family return, Escape/C while away, failed hand-back/recovery and queued starts.
- Phone/coarse-pointer card, short iframe, crossing 600/960 px with layers open, card/stat-panel precedence, blocked scene/no WebGL and engine recovery.

## Proposed commit split (coordinator only)

1. **Atomic extraction:** `web/ocean_inspector.js`, root delegation/phase calls, Tour owner-port changes, concrete types and checked-file list, HTML and hashed builder, both VM loaders/private seams, common dependency order and render evidence hash. All belong together; no preparation commit is needed.
2. **Documentation:** `docs/ocean_js_split_pr2_report.md`.

Leave `build_jsplit2/`, logs, disposable mutants, node_modules and dist excluded. The coordinator supplies the required attribution trailer and makes the commits; this work leaves `.git` untouched.

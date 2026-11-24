# Ocean controller split — PR 1: Tour

This is a controller-only extraction against main `6bc66a9156d67b62053972b6bc351a5400f3b47a` (#99), branch `ocean-js-split-1`. Changes are uncommitted for the coordinator. No engine rebuild, rebaseline, browser launch, deployment or Git mutation was performed. The pristine comparison tree is `build_jsplit1/base/`.

## Inventory and execution phases

| Original `web/ocean.js` span | Destination / inventory |
| --- | --- |
| 2401–2432 | Coach comment; `COACH_KEY`, `coachTimer`, `coachHideT`; `coachDone`, `startCoach`, `hideCoach`, `placeCoach`, including the interval callback (5 function bodies). |
| 3811–3922 | Tour comment; `guideFish`; complete `EvoGuideConfig`, including `steps`, `tap`, all twelve steps' content/target/enter callbacks, and `intro` with its content/target callbacks (27 function bodies). |
| 3923–3951 | Complete `EvoApp`: 12 function bodies including nested inspection/release callbacks; `setDrawer` and `setSheetTab` remain the original function references. |

`web/ocean_tour.js` registers only `EvoOceanTour.create`. The root creates `tour` where the coach state was initialized. Creating the controller initializes only private state and functions; it reads no ports, installs no globals/listeners, schedules no timers, and draws no randomness. `tour.installGuide()` occupies the original guide block and initializes `guideFish` and both guide globals there. Content remains lazy. Root still sets `EvoApp.ready` immediately before `evo:ready`, schedules the 9000 ms fish hint, then calls `tour.startCoach()` at the original startup point. Coach timing remains 1000 ms polling, 60 seconds or generation 1 after at least 25 seconds, with a 25000 ms hide timer.

There are no listener registrations in the moved inventory. Existing root listener registrations, targets, options and order stay byte-identical apart from the listed function references. Scene, rendering and simulation code are unchanged.

The source HTML sequence is `ocean_dash.js`, `ocean_tour.js`, `ocean.js`, `guide.js`, synchronously. The Turbo and inspector VM loaders include Tour before the root. `ui_common_tests.cjs` includes Tour in the load-order consumer list. The render evidence manifest includes its hash. The existing start-door, URL classification, memory-install scanners and private accessors remain valid: they reference root-owned code/state untouched by this PR. The scene-only mock loader and GOLDEN are untouched. `tsconfig.json` includes Tour with `// @ts-check`; concrete port, owner, factory, guide-content and adapter types are in `web/types.d.ts`.

## Move ledger

Every free-variable substitution inside the moved fragments is listed below. Numbers refer to verified base `web/ocean.js` lines; repeated numbers denote separate occurrences. `p` is the explicit, typed `OceanTourPorts` argument, not a generic controller context. Immutable objects and hoisted functions are passed by reference; all replaceable root bindings use synchronous getters, with no refresh or sync in those getters.

| Substitution | Occurrences | Base lines | Access |
| --- | ---: | --- | --- |
| `store` → `p.store` | 3 | 2408, 2408, 2418 | Original function/object reference |
| `P` → `p.P` | 2 | 2410, 2410 | Original function/object reference |
| `summary` → `p.summary` | 2 | 2413, 2413 | Live root getter |
| `turboState` → `p.turboState` | 4 | 2415, 3930, 3932, 3938 | Live root getter |
| `openPop` → `p.openPop` | 1 | 2415 | Live root getter |
| `statOpen` → `p.statOpen` | 1 | 2415 | Live root getter |
| `selectedId` → `p.selectedId` | 4 | 2415, 3939, 3947, 3950 | Live root getter |
| `drawerEl` → `p.drawerEl` | 1 | 2416 | Live root getter |
| `dash` → `p.dash` | 2 | 2416, 2416 | Original function/object reference |
| `el` → `p.el` | 4 | 2419, 2424, 2426, 2428 | Original function/object reference |
| `colourMode` → `p.colourMode` | 2 | 3829, 3929 | Live root getter |
| `HAS_APP` → `p.HAS_APP` | 1 | 3829 | Live root getter |
| `colourBrain` → `p.colourBrain` | 2 | 3831, 3928 | Live root getter |
| `coarseMQ` → `p.coarseMQ` | 1 | 3925 | Original function/object reference |
| `M` → `p.M` | 1 | 3930 | Live root getter |
| `enterTurbo` → `p.enterTurbo` | 1 | 3930 | Original function/object reference |
| `setDrawer` → `p.setDrawer` | 1 | 3933 | Original function/object reference |
| `setSheetTab` → `p.setSheetTab` | 1 | 3934 | Original function/object reference |
| `engineCall` → `p.engineCall` | 2 | 3936, 3947 | Original function/object reference |
| `fresh` → `p.fresh` | 1 | 3937 | Original function/object reference |
| `lastS` → `p.lastS` | 1 | 3937 | Live root getter |
| `scene` → `p.scene` | 1 | 3940 | Live root getter |
| `select` → `p.select` | 2 | 3942, 3947 | Original function/object reference |
| `cardEl` → `p.cardEl` | 2 | 3950, 3950 | Live root getter |

Root substitutions, and only those:

- Replace the coach span with the explicit `EvoOceanTour.create` port wiring at that phase; replace the guide span with `tour.installGuide()` at that phase.
- `hideCoach` → `tour.hideCoach` at base lines 2281, 2379, 2495, 3161, 3439, 3564, 3565, 4084 (including the direct `coachx` callback reference).
- `placeCoach` → `tour.placeCoach` at 3408; `startCoach` → `tour.startCoach` at 4164.
- At 3161, `store(COACH_KEY, "1")` → `tour.markCoachSeen()`. Its new method performs exactly `p.store(COACH_KEY, "1")`; the immediately following hide call stays separate and in order.

Required type-only additions: `guideFish` has `number | null` JSDoc. The second `dash()` call at base 2416 has a non-null JSDoc cast with grouping parentheses, because TypeScript cannot narrow a repeated call from the preceding short-circuit test. The call count and runtime expression are unchanged. `create` has the concrete parameter/result JSDoc. No other moved expression, branch, string, Promise boundary, timer, random draw or callback was edited.

`build_jsplit1/audit.py` compares the complete moved fragments and all 44 recursively nested function bodies, reversing only these port qualifications and the exact ledgered JSDoc grouping. It checks the root byte-for-byte against base plus precisely the allowed delegation lines, retains the first 79 lines, rejects orphaned names, and evaluates registration and construction in a VM whose DOM, timer, storage, performance, port access and random operations throw. `port_occurrences.json` records every individual lexical substitution.

## Plan deviations and independent-check corrections

- Retained root lines 1–79 exactly. The plan's spans are ownership inventories, not a file partition. Included each moved block's preceding comment (coach starts at 2401, tour at 3811).
- The inventory does not enumerate the root's Turbo-entry `COACH_KEY` write. The minimal fix is `markCoachSeen()`, documented above, so Tour owns its key while the action stays at the original point.
- Added only the newly introduced Tour namespace, rather than declaring factories for the eleven future PRs. No speculative files or APIs were added.
- The nullable-call cast is the only type-required grouping change in a moved body. It has no runtime effect.
- Applied the independent check's pinpoint citations: `Cfg` is at base types line 24; scene `SCRIPTS` at 54 (GOLDEN at 46); `guide.js` captures config at 21; the scene parity snapshot contract is at 1036–1038. Those code/contracts are unchanged.
- Laptop paired UI commands below include S3 as well as S0/S2, addressing the check's responsive-inspector selection item. Actual coarse-pointer/touch interaction still requires the plan's manual coverage.

## Preparation change (separate proposed commit)

`tests/ocean_render_browser.mjs` accepts `--main-query`. `benchUrl` accepts an explicit side query, so even same-URL A/A runs select the intended query for each role. Off-image captures record the actual scene's effective policy, record both queries, assert valid matching reference policies (`lod: quality`, `decoded: false`, `barbels: body`) on all sides including `mainFresh`, and stop with a failed check before pixel comparison on mismatch or absent diagnostics. Existing pixel thresholds and tolerances are untouched.

`tests/ocean_render_query_tests.cjs` exercises the real URL/policy functions through their browser-independent source seam: both URLs, explicit same-URL override, empty query, matching policies, each policy-field mismatch, missing diagnostics and invalid diagnostics (12 checks). Browser A/A is deliberately left to the coordinator. The preparation-only browser file is retained at `build_jsplit1/preparation_ocean_render_browser.mjs`, with `build_jsplit1/preparation.patch`; the later one-line Tour hash addition belongs to extraction.

## Server gate record

The base record is `build_jsplit1/logs/base.json`: full commit and six module SHA-256 values recorded before extraction audit, Node **v26.13.0**, npm **11.20.0**. Shell orchestration ran at nice 19, with `JOBS=2`, `BUILD_JOBS=2`, `OMP_NUM_THREADS=2`, `OPENBLAS_NUM_THREADS=2`, `MKL_NUM_THREADS=2`; full Turbo runs are sequential. The unmodified lock unit gate internally creates eight lightweight contender processes; there was one top-level gate at a time during that gate. No browsers were started. No network was used.

Commands below are run through `python3 build_jsplit1/run_gate.py NAME CWD COMMAND...`, which supplies nice 19 and the thread/job environment and captures output. Time is measured wall time in seconds. All log paths are relative to this worktree; scratch scripts/logs remain git-excluded. `cache` below means the absolute `$PWD/build_jsplit1/npm_cache` path expanded by the runner.

| Gate / command | Exit | Wall seconds | Log / result |
| --- | ---: | ---: | --- |
| Pre-extraction Python base record (`git rev-parse HEAD`, `node --version`, `npm --version`, SHA-256 of all six base/candidate modules) | 0 | 0.081 | `build_jsplit1/logs/base.json` |
| `python3 build_jsplit1/audit.py` (cwd `.`) | 0 | 0.229 | `build_jsplit1/logs/audit.log` |
| `node tests/ui_common_tests.cjs` (cwd `.`) | 0 | 0.121 | `build_jsplit1/logs/ui_common_tests.log` |
| `node tests/ui_parity_harness_tests.mjs` (cwd `.`) | 1 ENVIRONMENT-BLOCKED | 10.504 | `build_jsplit1/logs/ui_parity_harness_tests.log` |
| `Node spawnSync diagnostic for tests/ui_parity_browser.mjs --plan --sets S0,S2` (cwd `.`) | 1 ENVIRONMENT-BLOCKED | 0.134 | `build_jsplit1/logs/ui_parity_environment.log` |
| `node tests/ui_inspector_tests.cjs` (cwd `.`) | 0 | 3.693 | `build_jsplit1/logs/ui_inspector_tests.log` |
| `node tests/ocean_appearance_slots_tests.cjs` (cwd `.`) | 0 | 0.674 | `build_jsplit1/logs/ocean_appearance_slots_tests.log` |
| `node tests/ocean_shader_slots_tests.cjs` (cwd `.`) | 0 | 0.244 | `build_jsplit1/logs/ocean_shader_slots_tests.log` |
| `node tests/ocean_materials_tests.cjs` (cwd `.`) | 0 | 0.540 | `build_jsplit1/logs/ocean_materials_tests.log` |
| `node tests/ocean_render_opt_tests.cjs` (cwd `.`) | 0 | 0.101 | `build_jsplit1/logs/ocean_render_opt_tests.log` |
| `python3 build_jsplit1/audit.py` (cwd `.`) | 1 | 0.200 | `build_jsplit1/logs/audit-typed.log` |
| `python3 build_jsplit1/audit.py` (cwd `.`) | 0 | 0.263 | `build_jsplit1/logs/audit-typed-rerun.log` |
| `node tests/ocean_mock_three_tests.mjs` (cwd `.`) | 0 | 33.225 | `build_jsplit1/logs/ocean_mock_three_tests.log` |
| `node tests/ocean_perf_tests.cjs` (cwd `.`) | 0 | 0.108 | `build_jsplit1/logs/ocean_perf_tests.log` |
| `node tests/ocean_render_perf_lock_tests.mjs` (cwd `.`) | 0 | 15.582 | `build_jsplit1/logs/ocean_render_perf_lock_tests.log` |
| `node tests/ocean_render_query_tests.cjs` (cwd `.`) | 0 | 0.058 | `build_jsplit1/logs/ocean_render_query_tests.log` |
| `npm ci --offline --cache "$PWD/build_jsplit1/npm_cache" --no-audit --no-fund` (cwd `.`) | 0 | 0.891 | `build_jsplit1/logs/npm-ci.log` |
| `npx --offline --cache "$PWD/build_jsplit1/npm_cache" tsc -p tsconfig.json` (cwd `.`) | 0 | 4.359 | `build_jsplit1/logs/types.log` |
| `node tests/ocean_render_query_tests.cjs` (cwd `.`) | 0 | 0.076 | `build_jsplit1/logs/render-query-final.log` |
| `node tests/ocean_turbo_handoff.js` (cwd `build_jsplit1/base`) | 0 | 324.883 | `build_jsplit1/logs/turbo-base.log` |
| `node tests/ocean_turbo_handoff.js` (cwd `.`) | 0 | 331.762 | `build_jsplit1/logs/turbo-head.log` |
| `bash wasm/build_site.sh` (cwd `.`) | 0 | 0.719 | `build_jsplit1/logs/site-build.log` |
| `python3 build_jsplit1/check_site.py` (cwd `.`) | 1 | 0.193 | `build_jsplit1/logs/site-check.log` |
| `python3 build_jsplit1/check_site.py` (cwd `.`) | 0 | 0.110 | `build_jsplit1/logs/site-check-rerun.log` |
| `python3 build_jsplit1/verify_unchanged.py` (cwd `.`) | 0 | 0.120 | `build_jsplit1/logs/unchanged.log` |
| `python3 /home/harit/finfolk/work/trees/ocean-js-split-1/build_jsplit1/audit.py /home/harit/finfolk/work/trees/ocean-js-split-1/build_jsplit1/mutants/a-late-guide` (cwd `/home/harit/finfolk/work/trees/ocean-js-split-1`) | 1 expected rejection | 0.252 | `build_jsplit1/logs/mutant-a-audit.log` |
| `python3 /home/harit/finfolk/work/trees/ocean-js-split-1/build_jsplit1/check_site.py /home/harit/finfolk/work/trees/ocean-js-split-1/build_jsplit1/mutants/b-missing-built-tag` (cwd `/home/harit/finfolk/work/trees/ocean-js-split-1`) | 1 expected rejection | 0.179 | `build_jsplit1/logs/mutant-b-site.log` |
| `python3 /home/harit/finfolk/work/trees/ocean-js-split-1/build_jsplit1/audit.py /home/harit/finfolk/work/trees/ocean-js-split-1/build_jsplit1/mutants/c-coach-at-load` (cwd `/home/harit/finfolk/work/trees/ocean-js-split-1`) | 1 expected rejection | 0.254 | `build_jsplit1/logs/mutant-c-audit.log` |
| `node /home/harit/finfolk/work/trees/ocean-js-split-1/node_modules/typescript/bin/tsc -p tsconfig.json` (cwd `/home/harit/finfolk/work/trees/ocean-js-split-1/build_jsplit1/mutants/d-dropped-callback`) | 2 expected rejection | 3.691 | `build_jsplit1/logs/mutant-d-types.log` |
| `python3 /home/harit/finfolk/work/trees/ocean-js-split-1/build_jsplit1/audit.py /home/harit/finfolk/work/trees/ocean-js-split-1/build_jsplit1/mutants/d-dropped-callback` (cwd `/home/harit/finfolk/work/trees/ocean-js-split-1`) | 1 expected rejection | 0.189 | `build_jsplit1/logs/mutant-d-audit.log` |
| `python3 build_jsplit1/mutations.py` (cwd `.`) | 0 | 5.058 | `build_jsplit1/logs/mutations.log` |
| `node --check tests/ocean_render_browser.mjs` (cwd `.`) | 0 | 0.077 | `build_jsplit1/logs/browser-harness-syntax.log` |
| `python3 build_jsplit1/audit.py` (cwd `.`) | 0 | 0.238 | `build_jsplit1/logs/audit-final.log` |
| `python3 build_jsplit1/verify_unchanged.py` (cwd `.`) | 0 | 0.146 | `build_jsplit1/logs/unchanged-final.log` |

The UI parity harness unit command `node tests/ui_parity_harness_tests.mjs` could not validate its child runs in this sandbox: Node `spawnSync /home/harit/opt/node-v26.13.0-linux-x64/bin/node` returned `EPERM` with empty child output. The test consequently reported 122 failed assertions out of 132; this is **ENVIRONMENT-BLOCKED**, not a pass. `ui_parity_environment.log` records the exact spawn arguments, errno -1, code EPERM and empty output. No workaround or test modification was applied. Rerun that exact unit command outside the sandbox.

Own-test corrections (one successful rerun each, no production change to satisfy either failure):

- The first typed audit attempt rejected the added parentheses of the documented JSDoc cast. The audit initially erased comments but did not erase that cast's grouping. Fixed only its normalization for that exact cast (`audit-typed.log` → `audit-typed-rerun.log`).
- The first built-site checker treated the existing inline SVG `data:` favicon as a filesystem path. Fixed only the checker to distinguish inline data from file references (`site-check.log` → `site-check-rerun.log`). Every actual local file reference remains checked.

The final preparation seam gained missing/invalid-policy cases, so its final run has 12 checks rather than the initial 10. Final registration/construction audit and whole-browser-harness syntax check both pass.

## Full Turbo totals

- **turbo-base:** 604 / 604 checks passed in 324.5 s (`build_jsplit1/logs/turbo-base.log`).
- **turbo-head:** 604 / 604 checks passed in 331.4 s (`build_jsplit1/logs/turbo-head.log`).

The measured base total is the reference; the plan's 604 figure is not substituted for an actual run. Both full commands finished **604/604, exit 0**, with all sections, the existing per-section worker/probe cleanup, and the final successful unhandled-rejection check. The runner/section registry and cleanup code were not edited.

## Built site and protected artifacts

`wasm/build_site.sh` publishes `OCTOUR` through the unchanged SHA-256 publisher and rewrites its literal tag. Ocean substitution assertion is 20; Classic remains 13 and body viewer 6. `build_jsplit1/check_site.py` checks source/built tag ordering, one correctly shaped Tour URL per Ocean alias, every asset filename against its SHA-256 prefix, no bare Tour URL, all script/style/published-asset references, byte-identical Ocean aliases, Classic/redirect/bodyplan routes, and engine/worker/handoff/Three/fixture resolution. These are filesystem checks; HTTP loading and headers remain laptop smoke work. The intentional `mock: ocean_mock.js` development-only value is not a published asset.

`build_jsplit1/verify_unchanged.py` checks all six module hashes against the pre-extraction record, `git diff --check`, and zero protected-path diff for all `src/` (including plane headers), Wasm C++ wrappers, modules, baselines, fixtures and the scene golden. Its log includes `git diff --stat HEAD` and separately lists new untracked files because an unstaged new file does not appear in that Git stat. No C++/Wasm build was made.

| Module | Base = candidate SHA-256 |
| --- | --- |
| `web/evo_boids.js` | `2c5bcab233be2965130bbbfdd5f24f8a1a94b9f691d7eb3ef79ffc4d2f82bde3` |
| `web/evo_boids.wasm` | `d05c4442e15d6850aeece60e52c2a69289d10a2d39fd17538b2347123be0a99b` |
| `web/evo_boids_mt.js` | `09af9f5d1f3c46f64e1cee3668e5b215f951a20ca7ccf192e177462e05037b11` |
| `web/evo_boids_mt.wasm` | `1c86e3d2a8c043e17ab1e75004ad37d9d20a70ce5498a80e4ae4bf4fdd8a703b` |
| `web/evo_ocean.js` | `8bdce72bd8991c6e88768712b60cec9b7dd0cf22335d82ebe67f40cef6d91059` |
| `web/evo_ocean.wasm` | `e55a4fcb2e7c2e737c6f0cc838c783237ba138336f1162ab4ddf037468b5f2f1` |

Line counts: `ocean.js` **4189 → 4026** (−163); new `ocean_tour.js` **189**. Combined controller lines: 4189 → 4215; the extra lines are factory/phase/API/port wiring and typing. Root header lines 1–79 are unchanged.

Tracked diff stat against the base commit (protected files have no diff):

```text
 tests/ocean_render_browser.mjs |  39 +++++---
 tests/ocean_turbo_handoff.js   |   2 +-
 tests/ui_common_tests.cjs      |   2 +-
 tests/ui_inspector_tests.cjs   |   2 +-
 tsconfig.json                  |   1 +
 wasm/build_site.sh             |   9 +-
 web/ocean.html                 |   1 +
 web/ocean.js                   | 203 ++++-------------------------------------
 web/types.d.ts                 |  87 ++++++++++++++++++
 9 files changed, 146 insertions(+), 200 deletions(-)
```

New unstaged files, shown separately because Git does not include them in that stat: `web/ocean_tour.js`, `tests/ocean_render_query_tests.cjs`, `docs/ocean_js_split_pr1_report.md`.

## Mutation sensitivity

`python3 build_jsplit1/mutations.py` creates independent copies under `build_jsplit1/mutants/`, never modifies base/candidate files, and requires each already-established gate to reject its mutant. Nonzero exits in this section are expected results, not gate failures of the candidate.

| Mutation | Gate that rejects it | Expected diagnostic |
| --- | --- | --- |
| (a) Defer `installGuide()` until window load, installing globals after `guide.js` capture | Extraction audit (gate 2) | Root differs from exact delegation/phase ledger. |
| (b) Remove the hashed Tour script tag from both built Ocean aliases | Built-site inspection (gate 6) | Tour tag missing / repeated / bare. |
| (c) Call `create({}).startCoach()` during registration and remove the startup invocation | Extraction audit (gate 2) | Root startup differs from ledger; also violates the factory-only host-operation contract. |
| (d) Drop `EvoApp.inspectSomeFish`, including its nested callback | Existing TypeScript gate (gate 4), and extraction audit | Required `OceanGuideApp.inspectSomeFish` missing; guide fragment differs. |

These source/packaging/type gates cover the four planted mutants. This does not claim that existing Node runtime tests alone observe all first-visit lifecycle timing; the laptop must still exercise first visits and the tour. No mutant requires weakening a tolerance or changing GOLDEN.

## Laptop work (not run on this server)

Run all commands from the candidate worktree using its prepared browser harness, for both comparison sides. Configure the laptop's existing `PLAYWRIGHT`, `BRAVE_EXE` and machine-wide `BROWSER_LOCK` as usual. Preserve output directories as evidence and use fresh names if rerunning. Do not deploy.

Serve these in separate terminals (source layout needs repository roots, built-site smoke needs `dist/`):

```bash
python3 wasm/serve.py build_jsplit1/base 8261
python3 wasm/serve.py . 8262
python3 wasm/serve.py dist 8263
```

First rerun the environment-blocked unit gate and preparation seam:

```bash
node tests/ui_parity_harness_tests.mjs
node tests/ocean_render_query_tests.cjs
```

Paired UI identity, using the same harness and S0/S2/**S3** fixture selection, then deployed-layout smoke (these commands take the browser lock internally):

```bash
node tests/ui_parity_browser.mjs --base http://localhost:8261 --layout source --sets S0,S2,S3 --expect record --out build_jsplit1/laptop/ui-before
node tests/ui_parity_browser.mjs --base http://localhost:8262 --layout source --sets S0,S2,S3 --out build_jsplit1/laptop/ui-after
node tests/ui_parity_browser.mjs --compare build_jsplit1/laptop/ui-before build_jsplit1/laptop/ui-after --sets S0,S2,S3 --out build_jsplit1/laptop/ui-diff
node tests/ui_parity_browser.mjs --base http://localhost:8263 --layout site --smoke --out build_jsplit1/laptop/site-smoke
```

For render-browser and body GPU commands, use the plan's external browser lock wrapper (Bash function; do not wrap tools that already take the lock):

```bash
locked_node() {
  node --input-type=module -e 'import { acquire } from "./tools/ocean_render_perf/lock.mjs"; import { spawn } from "node:child_process"; const release = await acquire("ocean.js split PR1 checks"); try { const code = await new Promise((resolve, reject) => { const child = spawn(process.execPath, process.argv.slice(1), { stdio: "inherit" }); child.on("error", reject); child.on("exit", c => resolve(c ?? 1)); }); process.exitCode = code; } finally { release(); }' "$@"
}

# Required preparation A/A: pristine base vs the same pristine base, both reference.
locked_node tests/ocean_render_browser.mjs --base http://localhost:8261/web --main-base http://localhost:8261/web --parts offimage --query renderOpt=0 --main-query renderOpt=0 --out build_jsplit1/laptop/offimage-aa

# Then base vs candidate, both reference, with unchanged pixel thresholds.
locked_node tests/ocean_render_browser.mjs --base http://localhost:8262/web --main-base http://localhost:8261/web --parts offimage --query renderOpt=0 --main-query renderOpt=0 --out build_jsplit1/laptop/offimage-ab

locked_node tests/ocean_render_browser.mjs --base http://localhost:8262/web --parts correctness,slots,noperf,missing,faults,timer,beam,iframe,gate --out build_jsplit1/laptop/render
locked_node tests/ocean_render_browser.mjs --base http://localhost:8262/web --parts correctness,iframe,gate --query renderOpt=0 --out build_jsplit1/laptop/reference
locked_node tests/ocean_body_gpu.mjs --base http://localhost:8262

# Source-layout smoke takes the browser lock internally.
node tools/ocean_render_perf/smoke.mjs --web http://localhost:8262/web --root http://localhost:8262
```

These render commands select the non-default slots/missing/gate/iframe parts explicitly. Body GPU still uses its source-layout real-controller bridge; the site-layout smoke covers deployed routes. Keep the plan's interaction matrix alongside images: fresh visitor/no prior storage, tour and Turbo intro from Help, lazy colour/coarse-input content, inspection/release, first fish hint and coach timing/suppression, keyboard/focus/Escape, actual coarse pointer/phone, responsive transitions, paused/live/Turbo transitions, blocked scene/no WebGL and engine recovery. Browser E–H and authorized-deployment I are not server passes; I is skipped entirely.

## Proposed commit split (coordinator only)

1. **Preparation:** browser harness `--main-query`, effective reference-policy recording/assertions/refusal, and `tests/ocean_render_query_tests.cjs`. Use the preparation-only patch/snapshot to exclude the later Tour manifest hash line. Establish laptop A/A before accepting extraction evidence.
2. **Atomic extraction:** `web/ocean_tour.js`, root delegations, source HTML, builder, concrete types, checked-file manifest, both VM loader edits, common load-order list, and the one-line render evidence hash addition. Include all these together; no generated modules, baselines, fixtures or GOLDEN change.
3. **Documentation:** this report. Scratch audit scripts/logs and all `build_jsplit1/` contents remain excluded. Use the repository's required attribution trailer when the coordinator commits.

# AGENTS.md - Finfolk (repo: evo_boids)

Instructions for coding agents (Codex, Claude Code, others). `CLAUDE.md` just points here.

## What this is

A deterministic artificial-life simulation: neural-net fish evolve, hunt, breed and die.
Two worlds share one engine style: **Classic** (2-D, `src/core`) and the **3-D Ocean**
(`src/ocean`, the site's main page). Header-only C++20, built natively and as WebAssembly;
the site is static three.js/JS in `web/` (no JS build step). Python tools run experiments.

## Directory map

- `src/core/` Classic engine (world, genome, kernel, sensors/actions, checkpoint I/O). Shared by Ocean.
- `src/ocean/` 3-D Ocean: `ocean_world.hpp` (the world), `ocean_config.hpp` (OceanConfig, E1 preset),
  `ocean_flow.hpp`, `fish.hpp`, `appearance_*.hpp` (cosmetic genome), `plane_data_ocean*.hpp` (generated).
- `src/app/main.cpp` native SFML app; `src/render/` its renderer.
- `wasm/` module builds and parity scripts: `build_wasm.sh` (Classic), `build_ocean.sh` (Ocean),
  `build_site.sh` (assemble `dist/`), `parity.sh` (Classic), `ocean_parity.sh` (Ocean), `serve.py`,
  `evo_wasm.cpp`, `ocean_wasm.cpp` (the module APIs).
- `web/` the site. Committed build outputs (never hand-edit): `evo_boids*.{js,wasm}`, `evo_ocean.{js,wasm}`
  (from `wasm/build_*.sh`), `vendor/three.bundle.min.js` (from `tools/three_bundle/build.sh`).
  Hand-written: `ocean.html` (Ocean page), `index.html` (Classic), `ocean.js`, `ocean_scene.js`, `ocean_reef.js` (the opt-in Reef look),
  `ocean_config.js`, `ocean_handoff.js`, `ocean_worker.js` (Turbo), `ocean_dash.js`, `dashboard.js`, `charts.js`.
- `tests/` `core_tests.cpp`, `ocean_tests.cpp` (+ `ocean_*_tests.hpp`), `ocean_turbo_handoff.js`,
  `ocean_render_browser.mjs`, `ocean_baseline/` (committed fingerprints), `fixtures/`, `*.sh` end-to-end tests.
- `tools/` `ocean_parity_driver.cpp` + `ocean_fingerprint.hpp` (the parity harness), `ocean_eye_*`,
  `gen_planes*.{cpp,sh}` (regenerate plane headers), `invasion/` (invasion-matrix study: plan/run/score/analyze),
  `alife2027/` (ALIFE 2027 study runner: plan/run/analyze), `three_bundle/`.
- `.github/workflows/` `ci.yml` (every push/PR), `ocean-full.yml` (full Ocean matrix, weekly/on demand).
- `docs/`, `experiments/`, `img/` notes and artefacts.

## The big files (find things by name, not line number)

- `src/ocean/ocean_world.hpp`: `update` (the step), `computeSensors`, `doInteraction`, flow/wave caches
  (`ensureWaves`, `ensureFlow`), glass walls (`wallAvoid`, `wallFlowOn`), appearance maintenance
  (`appearance*`), the compound eye (`#ifdef EVO_OCEAN_EYE` sections). Sections are marked `// ---- ... ----`.
- `web/ocean.js`: the page controller: setup form (`readForm`, `pendingDiff`, `renderStartBar`, `askStart`,
  `saveSetup`, `importWorld`), the frame loop (`stepsThisFrame`, `follow`), cards/dashboards (`showCard`,
  `updateCard`), Turbo (`enterTurbo`, `paintTurbo`, `turboBack`), colour modes (`showColourMode`).
- `web/ocean_scene.js`: three.js scene: `load`, GPU gene texture (`genesRows`), CPU appearance mirror
  (`appWorldCPU`), the production self-checks (`appearanceTextureParity`), `setQuality`, camera (`resetView`).
- `tests/ocean_tests.cpp`: hand-built small worlds first, then one `test*` function per feature, run from
  `main`; ends with `testPreflight`. Feature checks live in the `ocean_*_tests.hpp` headers it includes.
- `tests/ocean_turbo_handoff.js`: node-only (no npm, no browser) checks of the Turbo hand-off against the real
  module and worker: helpers `ok`, `waitFor`, `stageFile`, `pageTurboFraction`, `randomize`.

## Build

```bash
cmake --preset native-serial && cmake --build --preset native-serial --parallel 2   # build_serial/ (the bit-exact one)
cmake --preset native && cmake --build --preset native --parallel 2                 # build/ (OpenMP)
(cd build_serial && ctest --output-on-failure)                             # core_tests, predator_smoke, ...
source ~/emsdk/emsdk_env.sh                                                # emsdk 6.0.4 matches CI
bash wasm/build_ocean.sh        # -> web/evo_ocean.{js,wasm}
bash wasm/build_wasm.sh         # -> web/evo_boids*.{js,wasm} (Classic, ST + MT)
bash wasm/build_site.sh         # -> dist/ (SITE_DIR=/x to build elsewhere)
python3 wasm/serve.py web 8123   # local server (production isolation headers) with web/ as its root; ROOT/PORT optional (default: repo root, 8123, so pages are under /web/)
```

Presets: `native`, `native-serial`, `wasm-st`, `wasm-mt`. The window app needs SFML; without it CMake skips it.
Memory is tight on the maintainer's PC: use `JOBS`/`BUILD_JOBS`, `nice -n 19`, and do not start browsers casually.

## Gates (what each proves)

- `FAST=1 JOBS=2 BUILD_JOBS=2 bash wasm/ocean_parity.sh`: CI's subset. Builds the plain and eye drivers
  native + wasm; every case must print identical fingerprints native == wasm == `tests/ocean_baseline/<case>.txt`,
  plus config guards, appearance-off twins (only a default subset of the selected cases), unit checks native and
  under node. Without `FAST` it runs every case, but twins are still the default subset; the weekly `ocean-full.yml`
  equivalent is `APP_TWINS=all bash wasm/ocean_parity.sh` (`APP_TWINS=all` EXPANDS twin coverage).
  `ONLY=<regex>`, `NO_TESTS=1`, `NO_EYE=1` NARROW the run (guards/unit checks/cases are skipped): a narrowed run is
  not evidence for the whole gate; an empty selection is an error. `--help` lists all knobs.
  Each run writes to its own `/tmp/ocean_parity.XXXXXX` (printed at start), so concurrent runs do not collide; it is
  removed when the run passes (`KEEP_OUT=1` keeps it) and kept when it fails (delete failed dirs by hand). An explicit
  `OCEAN_PARITY_DIR` is cleared at start, never removed, and must not be shared by two runs.
  `BUILD_JOBS` (default min(JOBS,2)) bounds concurrent compiler jobs per invocation (two runs = twice that);
  the printed per-command RSS is indicative, not a memory ceiling. `wasm/parity.sh` and `wasm/bench.sh` follow the
  same dir policy (`PARITY_DIR`, `BENCH_DIR`, `KEEP_OUT`).
- `wasm/parity.sh`: Classic native serial == wasm, byte-identical FINAL checkpoints (not a per-step chain).
- `ctest` (serial, OpenMP, thread-pool builds): `core_tests`, `predator_smoke`, plus `reseed_after_load`,
  `invasion_tooling` in the serial build with SFML.
- `build_ocean.sh` / `build_wasm.sh` then `git diff --quiet -- web/` (exit 0 = unchanged; CI also uses `git diff --quiet -- web/evo_ocean.js web/evo_ocean.wasm`
  for the Ocean): the rebuilt committed modules match their sources. If `web/` shows changes, the modules were stale.
- `node tests/ocean_turbo_handoff.js`: Turbo hand-off, exit 0 = pass.
- `node tests/ocean_render_browser.mjs --base http://localhost:8123` (serve with `python3 wasm/serve.py web 8123`; it appends `/ocean.html`; headless Brave, Playwright; see its header):
  render and shader checks on the real page. Browser-only; not in CI. Cases in `tests/fixtures/ocean_render_cases.json`.
- Classic sha pin: any `src/core` change changes the Classic wasm; the committed `web/evo_boids*.wasm` hashes are
  pinned by the maintainer (a change needs a rebuild and an explicit decision).
- CI jobs: `native` (3 variants), `wasm` (build, freshness, `parity.sh`, `build_site.sh`), `ocean` (freshness,
  turbo hand-off, FAST parity, `app_live_s21` twin).

## Determinism contract

- Ocean: native == wasm == committed baselines (`tests/ocean_baseline`), compared via the per-step chained fingerprints.
  Classic: native SERIAL == wasm final checkpoints. OpenMP, thread-pool and threaded-wasm Classic runs are NOT
  seed-reproducible and carry no such guarantee. Compile with
  `-ffp-contract=off` (no FMA); no `-ffast-math`; use `portable_math.hpp` / `ocean_math.hpp`, not libm
  transcendentals, in simulation code. Same draws in the same order: adding or reordering an RNG draw changes behaviour.
- Never rebaseline (`ocean_parity.sh --rebaseline --overwrite --reason ...`) without the owner's explicit approval;
  a baseline failure is a regression to find (`--trace`, `--dump-step`), not to re-record.
- Cosmetic features (appearance) must not change the simulation; the twin checks prove it.
- Edit a `web/evo_*.wasm`-affecting source (`src/**`, `wasm/*.cpp`) and you must rebuild and commit the modules.

## Conventions

- Branch per change, PR to `main`, **merge commits (no rebase/squash)**. Never merge, deploy or rebaseline
  unless the owner says so explicitly.
- Commit messages: short subject, explain why; end with the attribution trailer your tool gives you
  (e.g. `Co-Authored-By: ...`). PR bodies list changes, evidence and gates run.
- Don't commit build output dirs (`build*/`, `dist/`) or `/tmp` scratch. Keep generated files generated.
- Python tools run with `python3`. Tests: `tests/invasion_tooling.sh` (tools/invasion, via ctest in the serial SFML build);
  `tests/alife2027/test_runner.sh` and `tests/alife2027/test_stats.py` (tools/alife2027, run directly).
- Prefer small, scoped edits; don't touch baselines, `web/*.wasm` or plane headers by hand.

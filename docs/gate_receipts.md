# Gate receipts

A receipt is a local record of a passed gate run, so an unchanged candidate is not re-gated for hours.
It is a trusted local speed-up, not an attestation: CI runs every gate unconditionally, and `CI` /
`GITHUB_ACTIONS` disable all reuse inside the wrapper (including `gate_check`).

```bash
source tools/gate_receipts.sh                 # functions only; run from the repository root
source ~/emsdk/emsdk_env.sh                   # parity profiles need em++ on PATH before keying
FAST=1 JOBS=2 BUILD_JOBS=2 gate_run ocean-fast -- bash wasm/ocean_parity.sh
FAST=1 JOBS=2 BUILD_JOBS=2 gate_check ocean-fast          # lookup only, one JSON line
```

`gate_run` reuses a fresh receipt or executes and records, under a per-key `flock`, so two coordinators cannot
both act on the same miss. It returns the gate's exit code; `2` = invalid invocation (wrong command, conflicting
knob), `125` = a required identity could not be collected or the receipt could not be published.
`GATE_FORCE=1` executes despite a match (lookup policy, not part of the key). A hit prints
`ocean-fast: fresh; tested abc123; candidate def456; identical tree; 312 s; log ...` to stderr: it is the old
observation, never relabelled as a new run. `gate_check` exits `0` fresh, `1` no usable receipt
(`reason`: `missing running failed dirty nonreusable malformed evidence ci forced`), `2` identity error.

## What a key contains

SHA-256 of canonical JSON of: schema, profile definition digest, repository id, gate, object format, **the HEAD
tree** (the whole tracked tree: docs edits invalidate too, on purpose, so hidden inputs cannot be missed), exact
argv, the closed child environment and gate knobs, tool identity (resolved path, executable hash, version
probes; Emscripten config hash; installed-package inventory), the Classic pin bytes and artifact hashes, and
OS/arch. The tested commit is recorded separately: a rebase or merge with an identical tree is a hit and keeps the
original tested SHA.

| Profile | Exact requirement |
|---|---|
| `classic-parity` | `bash wasm/parity.sh` (`PARITY_DIR`, `KEEP_OUT` are keyed) |
| `ocean-fast` | `FAST=1`, no `ONLY` / `NO_EYE` / `NO_TESTS` / `APP_TWINS` |
| `ocean-full` | none of those set (`FAST=0` is still FAST in the script, so it is refused) |
| `ocean-all-twins` | as full, `APP_TWINS=all` |
| `ocean-app-live-twin` | CI's focused call: `APP_TWINS=all ONLY=app_live_s21 NO_TESTS=1 NO_EYE=1` |
| `turbo` | `node tests/ocean_turbo_handoff.js`, no section arguments |
| `classic-sha` | `sha256sum -c PIN` where PIN names exactly `web/evo_boids.wasm` and `web/evo_boids_mt.wasm` |

Ocean profiles also key the effective `JOBS` (default 4), `BUILD_JOBS` (default min(JOBS,2)), `KEEP_OUT` and
the canonical `OCEAN_PARITY_DIR` (unset = `auto`; the random scratch dir is run metadata only). An explicit
output dir is guarded by its own lock, so different keys sharing it run one at a time. Any other command, flag
(`--help`, `--rebaseline`, `--overwrite`), pipeline or knob value for a registered profile is refused, never run.
No profile satisfies another (full does not satisfy all-twins; FAST does not satisfy full).

The child runs with a closed environment: `PATH`, `HOME`, `USER`, `LOGNAME`, `TMPDIR`, `EMSDK*`, `EM_CONFIG`,
`EM_CACHE`, the profile's knobs, fixed `LC_ALL=C.UTF-8`, `TZ=UTC`; `BASH_ENV`, `NODE_OPTIONS`, `CPATH`,
`LD_PRELOAD`, `EMCC_CFLAGS` etc. are dropped. Missing em++ is exit `125`; a missing Emscripten config, package
inventory or a bad pin makes the run record-only.

Reuse is refused (the command still runs, receipt marked non-reusable) unless the checkout is exactly its HEAD
tree: no staged/unstaged edits, untracked files, symlinks, or ignored files other than `build*/`, `dist/`,
`.vercel/`, `runs/` and two ignored local docs. Checked again after the run; an edit reverted before the gate
finishes cannot be detected.

## Store

`~/wasm_parity/receipts_store/finfolk/v1/` (override: `GATE_RECEIPTS_DIR`): `locks/`, `keys/<key>.json`
(`running` or `done` + run id), `runs/<id>.json|.stdout|.stderr`. The key file is replaced atomically and set to
`running` before execution, so a failed or killed run supersedes an older pass; lookup never searches backward.
Only an intact terminal success (key, schema, evidence hashes) is a hit. No TTL, GC or age-based lock reclamation.

## Browser and deploy: record only

`browser`, `merged-smoke`, `native-parallel`, `deploy` always execute and log (`BASE`, `PLAYWRIGHT`,
`BRAVE_EXE` recorded); a source-tree match cannot prove served bytes, headers, GPU or production state.
`merged-smoke` also parses stdout: `merged_smoke.cjs` exits 0 on a failed assertion, so `{"ok":true}` is required.

## Integration notes (inspected 2026-11-03; nothing outside the repo was edited)

`~/wasm_parity/deploy_main.sh` today runs, in `~/evo_boids`: `sha256sum -c ~/wasm_parity/eco/classic_wasm.sha256`,
then `bash wasm/build_ocean.sh`, a `cmp` against the committed module, `node tests/ocean_turbo_handoff.js 2>&1 | tail -1`
and `build_site.sh`. It runs no parity gate. The two replacements, everything else unchanged:

```bash
source ~/evo_boids/tools/gate_receipts.sh
gate_run classic-sha -- sha256sum -c ~/wasm_parity/eco/classic_wasm.sha256
gate_run turbo -- node tests/ocean_turbo_handoff.js 2>&1 | tail -1
```

The pin is relative (`web/evo_boids.wasm`, `web/evo_boids_mt.wasm`, resolved against the repo root) and passes the
entry check; `classic_wasm_ocean.sha256` has the same names, `classic_wasm_877ebc3.sha256` holds older hashes.
A pin with absolute or foreign entries is record-only. The Turbo call runs after `build_ocean.sh`: if the rebuilt
module differs from the committed one the tree is dirty and it simply executes. `| tail -1` hides the exit status
(no `pipefail`) before and after this change. `emsdk_env.sh` changes `PATH`/`EMSDK`, so receipts made before and
after sourcing it are different keys. The keeper's Classic and Ocean parity calls are the `gate_run classic-parity`
and `gate_run ocean-fast` lines above, after sourcing emsdk. `merged_smoke.cjs` becomes
`BASE=... gate_run merged-smoke -- node merged_smoke.cjs` (record-only).
Excluded: dependency scanning, per-path caching, artifact restore, remote stores, retries, GC, sharding.

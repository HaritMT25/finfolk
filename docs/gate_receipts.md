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
probes), for parity profiles also the Emscripten config, the binaries that config selects (`em-config`: clang,
wasm-ld, llvm-ar/nm, wasm-opt, node, the emscripten Python sources and version), the shell helpers the scripts call
(`sed`, `grep`, `sort`, `xargs`, `/usr/bin/time`, ...) and the installed-package inventory, the Classic pin bytes and
artifact hashes, OS/arch, and the bytes of the helper that is executing. The Emscripten sysroot/cache is not
hashed: a versioned emsdk install is treated as trusted and immutable (custom `EM_CACHE` locations or hand-modified
sysroots are outside that assumption). A config that sets `COMPILER_WRAPPER`, `CLANG_ADD_VERSION` or
`LLVM_ADD_VERSION`, or a `NODE_JS` with more than the executable (e.g. `--require` hooks), is record-only. The tested commit is recorded separately: a rebase or merge with an identical
tree is a hit and keeps the original tested SHA.

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

The child runs with a closed environment, and every retained value is keyed: `PATH`, `HOME`, `USER`, `LOGNAME`,
`TMPDIR`, `EMSDK*`, `EM_CONFIG`, `EM_CACHE`, the profile's knobs, fixed `LC_ALL=C.UTF-8`, `TZ=UTC`; `BASH_ENV`,
`NODE_OPTIONS`, `CPATH`, `LD_PRELOAD`, `EMCC_CFLAGS` etc. are dropped. Missing em++ is exit `125`. A run is
record-only (executes, never reused) when anything unverifiable remains: Emscripten config or SDK tools that
`em-config` cannot resolve, no package inventory, a bad pin, case-colliding tracked paths, or a filesystem other
than the plain local ext4 one holding your home: the repository (every tracked directory and each ancestor up to the repository root),
the store and the output dir must share the home device, which must be ext4, with no casefold directory on that path (a relative `GATE_RECEIPTS_DIR` is made absolute). 9p/DrvFs/NFS,
tmpfs and `/mnt/*` therefore never give reuse. A pass whose log could not be written or mirrored, whose output
pipes outlived it, or that was cancelled (SIGINT/SIGTERM/SIGHUP are forwarded to the gate) is a failure (`125` if
the gate itself passed), never reusable. Processes a gate leaves in its own process group are killed when it
exits; a daemon that escapes with `setsid` and keeps the inherited lock descriptors would hold the lock until it
exits, so gates must not start such servers (none of the registered scripts do).

Reuse is refused (the command still runs, receipt marked non-reusable) unless the checkout is exactly its HEAD
tree: no staged/unstaged edits, untracked files, symlinks, or ignored files other than `build*/`, `dist/`,
`.vercel/`, `runs/` and two ignored local docs. Everything is collected again after every lock wait (a
waiting caller never accepts a hit for inputs that changed meanwhile) and after the run; an edit reverted before
the gate finishes cannot be detected. The helper that runs is always the candidate's own `tools/gate_receipts.py`
(resolved per call, not from where the shell file was sourced); its bytes are hashed once at process start, and an
invocation whose helper file changes underneath it exits `125` instead of adopting the new bytes.

## Store

`~/wasm_parity/receipts_store/finfolk/v1/` (override: `GATE_RECEIPTS_DIR`): `locks/`, `keys/<key>.json`
(`running` or `done` + run id), `runs/<id>.json|.stdout|.stderr`. The key file is replaced atomically and set to
`running` before execution, so a failed or killed run supersedes an older pass; lookup never searches backward.
Files and their directories are fsynced; logs and run receipt are durable before the terminal key reference.
Only an intact terminal success (integer schema, `done` state, every field `gate_check` prints, evidence hashes)
is a hit; unreadable records are storage errors, not misses. The gate
inherits the lock descriptors, so killing only the coordinator does not free the key or output-dir lock until the
gate's processes exit (output dirs are identified by device and inode). Storage errors exit `125` (`gate_check`:
`2` with a `reason: error` status). No TTL, GC or age-based lock reclamation.

## Browser and deploy: record only

`browser`, `merged-smoke`, `native-parallel`, `deploy` always execute and log (`BASE`, `PLAYWRIGHT`,
`BRAVE_EXE` recorded); a source-tree match cannot prove served bytes, headers, GPU or production state.
`merged-smoke` also parses stdout: `merged_smoke.cjs` exits 0 on a failed assertion, so `{"ok":true}` is required,
and its `base` must equal the URL passed last on the command line. Provenance is minimal (argv, three env
values): Node/Playwright/Brave versions, GPU, served bytes and headers are not collected.

## Integration notes (inspected 2026-11-03; nothing outside the repo was edited)

`~/wasm_parity/deploy_main.sh` today runs, in `~/evo_boids`: `sha256sum -c ~/wasm_parity/eco/classic_wasm.sha256`,
then `bash wasm/build_ocean.sh`, a `cmp` against the committed module, `node tests/ocean_turbo_handoff.js 2>&1 | tail -1`
and `build_site.sh`. It runs no parity gate. The two replacements, everything else unchanged:

```bash
source ~/evo_boids/tools/gate_receipts.sh
gate_run classic-sha -- sha256sum -c ~/wasm_parity/eco/classic_wasm.sha256
gate_run turbo -- node tests/ocean_turbo_handoff.js     # no `| tail -1`: see below
```

The pin is relative (`web/evo_boids.wasm`, `web/evo_boids_mt.wasm`, resolved against the repo root) and passes the
entry check; `classic_wasm_ocean.sha256` has the same names, `classic_wasm_877ebc3.sha256` holds older hashes.
A pin with absolute or foreign entries is record-only. The Turbo call runs after `build_ocean.sh`: if the rebuilt
module differs from the committed one the tree is dirty and it simply executes. The existing `2>&1 | tail -1` hides
the exit status (the script has `set -e` but no `pipefail`), including new wrapper failures (125): drop it, or add
`set -o pipefail`, before treating the script as validation. `emsdk_env.sh` changes `PATH`/`EMSDK`, so receipts made before and
after sourcing it are different keys. The keeper's Classic and Ocean parity calls are the `gate_run classic-parity`
and `gate_run ocean-fast` lines above, after sourcing emsdk. `merged_smoke.cjs` takes its URL as `argv[2]` (not
`BASE`) and is a Windows script (Windows Playwright and Brave paths): from WSL,
`gate_run merged-smoke -- node.exe 'C:\Users\harit\Downloads\fish runs\ocean_handoff\tools\merged_smoke.cjs' http://localhost:8161`
(record-only; the URL must be the last argument).
Excluded: dependency scanning, per-path caching, artifact restore, remote stores, retries, GC, sharding.

# Experiment throughput (tools/invasion)

How many invasion cells an hour the machine can run, where a cell's time goes, what was changed to run
more of them, and how a faster engine binary may enter a study without changing a single result.

Measured 2026-11-04/05 on the maintainer's i7-1165G7 (4 cores, 8 threads), WSL Ubuntu 24.04, g++ 13.3.0,
on AC power. Branch `throughput`. The scratch harness (profiler, A/B and throughput scripts) lives in
`~/wasm_parity/thru/`.

## 1. Where a cell's time goes

A cell is `run.py --_cell`: arena.py builds the arena, the serial engine runs it, score.py scores it, and
run.py finalizes it (hashes, fsyncs, and with `--prune` a gzip of the birth log). The engine dominates.

One pilot1 cell's inputs in bank1's configuration (13,500 steps, checkpoints every 4,500, log every
1,000), with the pinned binary, timers around each part (median of 3, measured while bank1 ran):

| part | off, invade (14.45 s) | predA4, invade (12.25 s) |
|---|---:|---:|
| Python start and imports | 0.6% | 0.6% |
| arena.py: load J and I, swap, dump, write and fsync, hash | 2.9% | 2.4% |
| engine start and checkpoint parse | 0.4% | 0.4% |
| **engine stepping** | **93.4%** | **94.4%** |
| stats samples and CSV rows (14 at ~1 ms each) | 0.1% | 0.1% |
| checkpoint saves (3 periodic + end.json, ~20 ms each) | 0.7% | 0.6% |
| score.py (arena, 3 checkpoints, birth log) | 2.0% | 1.6% |

The whole runner adds 0.12–0.45 s per cell, measured from `attempts.tsv` and `done.json`. That time covers
the worker's Python start, finalization, the prune and the runner's poll. Across 25 end-to-end runner
runs (§2), everything outside the engine (Python, JSON, hashing, fsync, gzip, scheduling) was 5–6% of a
cell at 1 worker. At 4 workers it was 7–8% with origin/main's runner and 5.5–6.5% with this branch's.
The engine is the other 92–95%.

Gemini's estimate (q28) of ~40% Python/JSON overhead does not hold. It assumed the cells sit on `/mnt/c`
(9P), but bank1 sits on WSL's own ext4; the pilot's "1126 steps/s" was the right clue. The one heavier
Python piece is score.py on a 36,000-step pilot cell, at 4.1% (18 checkpoints). With Python at 5–8%, well
under the 15% bar, a batch mode or fork server (step 3 of the brief) is not worth its risk: it could save
at most about 6%. It was not built.

## 2. What was changed, and what it buys

**Build flags (CMakeLists.txt `EVO_NATIVE_ARCH`, `EVO_LTO`, `EVO_PGO`; preset `native-serial-fast`).**
All are off by default. With them off, the build is byte for byte the pinned binary (below). Engine
speed is measured per change by running the two binaries of a pair AT THE SAME TIME, each pinned to its
own physical core (`taskset`, CPUs swapped every rep), so the machine's noise hits both alike. Each pair
ran 12 times (3 pilot arenas, bank command, 4 reps). The table gives the ratio of user CPU times; > 1
means faster.

| change | vs | speed | IQR |
|---|---|---:|---:|
| A/A control (pinned twice) | pinned | 1.002 | 0.999–1.005 |
| `-march=x86-64-v3 -mno-fma` | pinned | **1.103** | 1.093–1.113 |
| LTO alone | pinned | 0.999 | 0.997–1.006 |
| `-march=x86-64-v3 -mno-fma` + LTO | pinned | **1.122** | 1.112–1.132 |
| LTO on top of x86-64-v3 | x86-64-v3 | 1.020 | 1.016–1.023 |
| PGO on top of v3 + LTO | v3 + LTO | 0.935 | 0.930–0.944 |

PGO was dropped for two reasons. Trained on two other arenas, it made the engine 6.5% slower. And it is
not reproducible: two builds from the same commit, flags, epoch, work path and training inputs gave
different binaries (the profile records run-time values). A study binary has to be rebuildable from its
recipe. `build_engine.sh --pgo` stays for experiments.

**The candidate study binary is x86-64-v3 (no FMA) + LTO**: `tools/invasion/build_engine.sh OUT --arch
x86-64-v3 --lto`. With the pin's epoch it is sha256 `4e39ed8a…`, from any commit whose `src/` and
CMakeLists.txt match this branch's: no commit hash goes into the binary.

**Runner (tools/invasion/run.py).** The admission loop slept a fixed 0.5 s, so a finished cell's slot sat
idle for 0.25 s on average. It now returns as soon as a cell worker exits. The runner's overhead per cell
(the time not spent in arena.py, the engine or score.py) was 0.36–0.41 s with origin/main's run.py and
0.17–0.29 s with this branch's, at 2 workers. That is about 0.2 s, or 1.5–2% of a cell. It changes
scheduling only.

**Cells per hour, end to end.** These are real runner runs (`run.py --prune`, as bank1 runs) on bank-like
cells: pilot1 inputs at 13,500 steps with checkpoints every 4,500, 16 cells per worker. "Steady" is
workers × 3600 / mean per-cell time. Single runs of a few minutes swing by 6–12% on this laptop
(turbo, thermals, the Windows host). The 1-worker comparison therefore ran both binaries' runners at the
same time on their own cores. The 4-worker runs ran in the order A B B A while nothing else was running.

| | 1 worker | 4 workers, session 1 (origin/main runner) | 4 workers, session 2 (this runner) |
|---|---:|---:|---:|
| pinned binary | 493, 440 (mean 467) | 1321, 1174 (mean 1248) | 1057, 1025 (mean 1041) |
| x86-64-v3 + LTO | 545, 486 (mean 516) | 1376, 1395 (mean 1386) | 1314, 1292 (mean 1303) |
| gain | **+10.6%** | **+11%** | **+25%** |

The other changes, as cells/hour, follow from the engine ratios above and the measured split of a cell
(engine 95% at 1 worker, 94% at 4):

- x86-64-v3 alone: +9.7%;
- LTO alone: ±0;
- v3 + LTO: +11.5% expected, against +10.6% to +25% measured;
- the runner fix: about +1.5–2% more.

**For a bank.** bank1 ran its 28,800 cells at 1,136 cells/h on 4 workers (its own session rate), so about
25.4 h. With the new binary and the runner fix, the conservative estimate (engine 1.12×, runner +1.5%)
is about 1,290 cells/h: **about 22 h for the same bank**. At session 2's +25% it would be about 20 h.
Bigger wins would have to come from the engine's own step (the local perf ledger,
`docs/evo_boids_perf.md`) or from the statistical design (fewer cells), not from the Python around it.

## 3. Proof that nothing changed

**The default build is untouched.** The default serial build of this tree (all new options off, the pin's
`SOURCE_DATE_EPOCH`) is byte for byte `evo_boids_main_62b18b1` (sha256 `78a39337dd2237f8…`). So is
`build_engine.sh --rev 62b18b1`. The pinned binary is reproducible from its commit, and the CMake
change is a no-op when its options are off.

**240 real cells, every file identical.** `identity.py --root pilot1/root --sample 240 --seed 2027`
replayed 240 finished pilot1 cells from their own inputs with the pinned binary and with the x86-64-v3 +
LTO binary (`4e39ed8a…`). The cells were 36,000 steps each, with checkpoints every 2,000:

- composition: off / predA4 (4 predators) × invade 50 + 50, sham 50 + 50, self 20 + 20 (every self cell
  pilot1 has); designs pilot1A 173, pilot1B 45, pilot1S 22; 8.64 M steps per binary;
- per cell, 27 files hashed per binary: arena.json, all 18 end.<frame>.json and end.json, run.births.csv,
  score.json, the manifest, run.csv, run.config.txt, stdout.log (the last four normalized as the tool
  says), stderr.log. **6,480 files per binary, all identical** (`IDENTICAL: 240/240`);
- the pinned replay also matches what pilot1 itself recorded. Pilot1 ran with another build, `0e13a113…`
  from the invasion tree. The comparison covers arena.json, end.json, the birth log and 17 intermediate
  checkpoints per cell: **4,800 recorded hashes, 0 mismatches**. score.json was not compared with the
  record, because pilot1 ran an older score.py. Three binaries agree.

Evidence: `~/wasm_parity/thru/id240/identity.json` (sha256 `e5391b88…`). Over the same 240 cells the engine's
total user time was 6,932 s for the pinned binary and 6,086 s for the new one (1.14×).

**native == wasm still holds with the new flags.** Both parity gates were run with
`NATIVE_CXXFLAGS="-march=x86-64-v3 -mno-fma -flto=auto"` on the native side:

- `wasm/parity.sh`: 23/23 cases PASS, native serial == wasm, bit for bit;
- `FAST=1 wasm/ocean_parity.sh`: 49/49 cases PASS, native == wasm == baseline at every step, with every
  guard and the unit checks of both builds.

Neither native driver contains an FMA instruction (`objdump`; 1,637 and 3,848 ymm instructions, so the
flags took effect). `tests/invasion_tooling.sh` passes with the pinned binary (92 s), including its new
section 5b.

**Why this is exact, and how far the proof reaches.** Under `-ffp-contract=off` without `-ffast-math`, the
compiler may not reassociate, contract or approximate a float operation. The transformations x86-64-v3 and
LTO add are wider vectors, VEX encodings, inlining and code layout, and none of them changes an IEEE-754
result. FMA, the one instruction that would, is compiled out. The src tree has no ISA-specific intrinsics or
`#ifdef __AVX__` paths, and libm calls go to the same shared glibc in both binaries. That glibc picks its
own code paths by host CPU, for the pinned binary as much as for the new one, so a replay on another host
is a question for any binary, not one this change adds. The 240 cells are the
empirical check on that argument: about 4 billion fish-steps per binary, in a chaotic system where one
flipped bit diverges a run within a few hundred steps. Each new compiler, commit or flag set needs its own
identity run. That is the registration rule below.

## 4. Registering a new engine binary

A study's results are a function of its plan, its snapshots, its scoring tools and its engine binary.
`run.py` already pins the binary per study root: the first start copies it to `ROOT/bin/evo_boids` with
its SHA-256, every cell checks that hash before it launches, `done.json` records it, a later start with
any other binary is refused (exit 2), and `--replay` uses `ROOT/bin/evo_boids`. That rule is what keeps
a running or finished study unchanged, and this branch does not touch it.

**bank1 is unchanged by construction.** Its root pins `evo_boids_main_62b18b1` (sha256 `78a39337…`).
Nothing here writes under `bank1/`, changes its pinned tools, or changes run.py's pin rule. A new binary
cannot enter that root (the runner refuses it), and bank1's replays keep using its own `bin/evo_boids`.
The faster binary is for a NEW root only: the confirmatory matrix.

To register a new binary for a study, do these steps in order, at the gate freeze or at the latest
before the study's first cell:

1. **Build it reproducibly.**
   `tools/invasion/build_engine.sh ~/wasm_parity/invasion/bin/evo_boids_<commit>_v3lto --rev <commit> --arch x86-64-v3 --lto --epoch <E>`.
   This builds from `git archive <commit>`, so no uncommitted edit can reach it. It refuses to overwrite
   an existing file and refuses a binary with an FMA instruction. It writes `<binary>.build.json`, which
   holds the commit, flags, compiler, `SOURCE_DATE_EPOCH` and sha256. The same inputs give the same bytes:
   this script with `--rev 62b18b1` and the pin's epoch rebuilds the bank's binary bit for bit.
2. **Prove it identical on real cells.** Run
   `tools/invasion/identity.py --root <a closed study> --out <new dir> --binary pinned=<the reference binary> --binary new=<candidate> --sample 240 --workers 4`.
   It must print `IDENTICAL`. Then the parity gates must pass with the candidate's flags:
   `NATIVE_CXXFLAGS="<flags>" bash wasm/parity.sh` and
   `NATIVE_CXXFLAGS="<flags>" FAST=1 bash wasm/ocean_parity.sh`.
   Prove it on cells that are already open (pilot1). identity.py refuses a root while its runner holds
   it. A replay of a blind bank's cells would write their scores to disk, so do not run it on bank1
   while bank1 must stay blind.
3. **Record it in the preregistration.** Record the binary's sha256, its `build.json`, the sha256 and
   verdict of `identity.json` (with N cells, and the reference binary's sha256 it was proven against),
   and the two parity logs. The claim this supports is: "the confirmatory cells were run by a binary
   whose outputs were byte-identical to the bank's binary on N real cells, and whose flags keep
   native == wasm".
4. **Run it.** Start the confirmatory root with `--binary <candidate>`; run.py pins it for the life of the
   root. Never swap a root's binary mid-study. A different binary needs a new root and a new
   registration.
5. **Portability.** The AVX2 binary dies with SIGILL on hosts older than Haswell. A replay elsewhere copies
   the root, `bin/` included. On a host that cannot run it, use the default build of the same commit
   (`build_engine.sh` without options, reproducible byte for byte). Step 2 shows its outputs equal the
   fast binary's on the tested cells.

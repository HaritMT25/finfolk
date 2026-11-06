# Finfolk — evo_boids CLI reference (v0.27.0)

Headless runner for the evolutionary boids simulation. Defaults reproduce the
original behaviour, so any flag is an opt-in change.

> **v0.27.0 — neural predators (Stage C)** (`--predator-brain`, `--predator-mutation`,
> `--predator-turn-rate`, `--predator-min-speed`, `--predator-primer`, `--predator-log`,
> and the transplant `--predators-from` … `--transplant-out`; see the section after the
> predator floor): the hunt becomes a network built from each predator's genome, a bud
> inherits its parent's genome with a mutation, and two checkpoints can be combined into
> a time-shift assay arena (prey of one, predators of another). Off by default, and off
> **every output is byte-identical to v0.26.0's** apart from the version string: no CSV
> column, no sidecar line and no checkpoint key is added. Brain runs write their own
> `<name>.predators.csv` and checkpoints in format version 2.

> **v0.26.0 — predator floor, ceiling and heritable traits** (`--predator-min-pop`,
> `--predator-max-pop`, `--predator-inherit`, `--predator-trait-mutation`; see the
> section after the predator economy): the predators' own `--min-pop` and `--max-pop`,
> and two heritable predator traits (speed and budding threshold) passed to each bud
> with a mutation. Four CSV columns appended (35–38). All off by default and
> byte-identical to v0.25.0 when off. Measured: **the ceiling is what keeps both
> populations alive** (it fixes the predators' catch rate); the floor stops extinction
> but not a crash; inheritance does not stabilise anything on its own.

> **v0.25.0 — browser build** (no new CLI flags): a threaded WebAssembly module
> alongside the single-threaded one, a static Vercel deploy, and a per-creature
> `generation` count (founders 0, a newborn is max(source records) + 1; shown in the
> HUD and the inspector, written to checkpoints, not to the CSV). Simulation output
> is byte-identical to v0.24.0 apart from that one checkpoint column. See README.md.

> **v0.24.0 — gate mitigations** (`--repro-soft-width`, `--repro-grace`; see the
> reproduction section): the match-distance cliff becomes a linear acceptance ramp,
> and young founders — the initial spawn and every `--min-pop` reseed — get a
> gate-free window so an injected genome can enter the pool instead of pinning the
> population to the floor. Two attribution CSV columns (33/34) say which mitigation
> carried each birth. **v0.23.0 — tier-1 body model** (`--body-model`,
> `--body-mutation`): heritable size and elongation modulating the existing
> speed/turn/metabolism model. **v0.21.0–v0.22.0** — the match-distance gate
> (`--repro-max-distance`) and the pairing graph (`repro_components`,
> `--repro-log`). **v0.18.0–v0.20.0** — the WebAssembly build with native == wasm
> byte-identical checkpoints (`wasm/parity.sh`, 19 cases), toroidal perception and
> frontend parity. Every one of these is opt-in and fingerprint-verified
> byte-identical when off; the per-version history with measurements is kept in the
> project's research log (not published with the repository).

> **v0.17.0 — checkpoint / resume** (`--save-checkpoint`, `--load-checkpoint`,
> `--checkpoint-every`). A checkpoint is the complete world: config, frame counter and
> cumulative counters, **the rng engine state**, every creature (genome, position,
> velocity, energy, timers, and the recurrent neuron outputs), food, predators, the
> pheromone layer, and the rng-seeded ocean vortices and food-patch centres.
>
> **A resume continues the run bit-for-bit** in the serial build. Verified two ways:
> `core_tests` runs 220 steps → checkpoint → 140 more, then reloads and runs 140, and
> compares a deep fingerprint of every creature, predator, food item and pheromone cell;
> and end to end through the CLI, where 600 steps in one go produces a byte-identical
> final checkpoint to 300 + resume + 300. In an OpenMP build a resume is valid but not
> bit-exact (per-thread rngs), and the binary says so on load.
>
> **Format is JSON**, chosen because the planned wasm build needs the browser to read
> these and `JSON.parse` is built in. Floats are written `%.9g`, which round-trips every
> float32 exactly, so it is as lossless as a binary dump while staying diffable and
> hand-editable. **Editing the `config` block and resuming is the supported way to
> intervene mid-run** — change the predator economy, metabolic rate or perception at
> step 300 and watch whether the regime shifts. ~1.2 KB per creature.

> **v0.16.0 — a perf cycle that actually shipped, plus reproducible floating point.**
> Unlike the reverted v0.14.0 attempt, this one is measured: **1.17–1.47× faster at
> every one of 30 (population × perception) grid points, mean 1.29×**, and
> **bit-for-bit identical output** — verified by fingerprinting whole 500- and
> 2000-step runs against the pre-change build across 7 seeds, and by a `core_tests`
> oracle that re-implements the old `feedForward` and asserts exact equality over
> 400 nets × 6 steps.
>
> *What changed:* the net's connections are stored once, flattened into two index
> spaces (sensor/neuron sources, action/neuron sinks) and grouped by sink with a
> **stable** counting sort — so each accumulator still sums in genome order and
> rounds identically — which removes two unpredictable branches per connection.
> Two things mattered as much as the branch removal, and both were found by
> measurement, not reasoning: the flat entry must stay **4 bytes** (an 8-byte
> version was *net slower* despite a faster `feedForward`), and the old
> genome-ordered array must be **deleted, not kept alongside** (keeping both was
> ~0.97× — the duplicate competed for cache with the neighbour scan). `asGene()`
> decodes an entry for the wiring log and inspector.
>
> *Also:* `-ffp-contract=off` is now a build flag. Without it the compiler fuses
> multiply-adds into FMAs wherever it likes, so results depend on `-march`,
> compiler version and target — and **wasm has no scalar FMA at all**, meaning a
> native build could never reproduce a browser build. This is a **one-time results
> shift** (old binaries used FMA), and it is what makes a fixed `--seed` mean the
> same run everywhere: the premise of deterministic replay, checkpoint resume, and
> verifying a result by re-running it. Never add `-ffast-math`.
>
> New flags: `--max-neighbors N` / `--topological` (biology), `--fast-tanh` (speed).
> `CMakeLists.txt` is 0.16.0.

> **v0.15.0 — triangular action space** (`--triangular-motion`, off by default). The
> net commands a forward DRIVE and a TURN, and the feasible turn is throttled by drive
> (`turnEff = turn * (1 - drive)`): a fast strike can't also turn; a slow reorient turns
> freely. This forced trade-off is what the hunting paper (Malik/Singh/Harpaz/Engert/
> Rajan 2025) found produces clean fast-straight vs slow-turning bouts — which the old
> decoupled steer/speed axes could not. `--max-turn-rate F` sets the turn ceiling (rad/s)
> at zero drive (default 4.0). Default off ⇒ byte-for-byte identical to before (verified).
> `CMakeLists.txt` is 0.15.0.
>
> *Earlier this session a v0.14.0 perf cycle investigated three optimizations and shipped
> none (all reverted) — see the changelog in the context doc; the build skipped from 0.13.0
> to 0.15.0 for that reason. The `--profile` profiler from 0.13.0 remains.*

> **v0.12.0 extends the death-cluster map and adds lineage + wiring analysis** (all
> opt-in, dynamics-neutral). `--cluster-pca` gives per-run variance-aligned axes (vs
> the fixed random map); `--cluster-color lineage` colours points by clade; the map
> now draws **epoch-centroid drift arrows** and a **top-lineage summary** (share +
> epoch span = how long a clade dominated); the deaths CSV gains a `lineage` column;
> and `--wiring-log` writes `<name>.wiring.csv` — the fraction of the population
> wiring each sensor as a source, per log interval (watch selection recruit sensors).
> Creatures now carry a founder `lineageId` (maternal line). `CMakeLists.txt` is 0.12.0.

> **v0.11.0 adds two inspection/analysis features** (both opt-in, zero effect on
> dynamics or existing CSVs). (1) **Live neural inspector** — LEFT-CLICK a fish in
> the window to watch its neural net fire in a translucent top-right panel (sensor →
> hidden → action nodes, lit by live activation; connections tinted by
> weight×signal). (2) **Death-cluster map** (`--cluster-map`) — every death logs a
> 2-D projection of that creature's network; at end of run it writes
> `<name>.deaths.csv` + `<name>.cluster.svg`, points coloured by epoch (a new colour
> band every `--cluster-epoch` deaths, default 1000) so you can read how the
> population's networks drift over the run. `CMakeLists.txt` is at 0.11.0.

> **v0.9.0 adds a predator (Stage A).** It is **off by default** (`--predators 0`):
> with no predators the world is byte-for-byte the old behaviour *except* that the
> three new prey threat-sensors bump `NUM_SENSES` 38→41, which reseeds the genome
> baseline (see the NUM_SENSES note below).
>
> **v0.9.1 adds schooling instrumentation** — two CSV columns, `neighbor_align` and
> `neighbor_count` (see CSV columns). No new flags, no behaviour change; it only
> *measures*. It exists because `predator_align` assumes prey flee individually and
> is blind to evasion-by-schooling.
>
> **v0.9.2 is perf-only** — the schooling-metric neighbour lookup is now O(n) (temp
> spatial grid) instead of O(n²). No result or CSV-format change.
>
> **v0.10.0 adds the predator energy economy (Stage B).** It is **off by default**
> (`--predator-economy` not given): predators stay Stage-A immortal/fixed-count and
> the energy machinery is inert, so all §10 runs and tests are unchanged. With the
> switch ON, predators gain energy per capture, burn metabolism + a kinetic
> move-cost, reproduce above a threshold and **starve** below 0 — `predator_pop`
> becomes time-varying (the coupled oscillator). **No new sensors**, so `NUM_SENSES`
> stays 41 and 0.9.x predator runs remain comparable. **4 CSV columns appended**
> (27→31): `predator_births_interval, predator_deaths_starv, predator_deaths_age,
> predator_avg_energy`. A new build option **`-DEVO_NO_OPENMP=ON`** produces a
> deterministic serial binary for reproducible single runs. `CMakeLists.txt` is at
> 0.10.0, so `--version` matches the code.

Check what you're running at any time:

```
./evo_boids --version          # e.g. "evo_boids 0.9.2 (built ...)"
./evo_boids --help             # same reference as below
```

---

## Workflow

```bash
# 1) Build (after pulling new code). Do not rebuild while a sim from this build
#    directory is running.
cmake -S . -B build && cmake --build build -j

# 2) Run (no rebuild needed between runs — just change flags).
cd build
./evo_boids --headless 1000000 --name evolved_1M --log-every 2000 --gene-cost 0.02 --no-render

# 3) Copy a run's data elsewhere (safe mid-run; the CSV stays current to ~5 rows).
cp runs/evolved_1M.csv runs/evolved_1M.config.txt /path/to/analysis/
```

`--name X` writes `runs/X.csv` plus `runs/X.config.txt` (a sidecar recording the
version, seed, step count, and every parameter — so a CSV is never an orphan).

**Tip on `--no-render`:** without it, a headless run **opens the SFML window** after
finishing (and does not exit). Use `--no-render` for unattended/long runs. To *watch*
the result, omit it — but note the renderer currently shows only the top-left corner
of the world (see the context file's renderer-bug note) and the flow overlay only
draws with a current active. Predators draw as **red discs** (dimmed while digesting)
and the HUD gains a `Pred: N` field when any are alive.

**Backslash gotcha:** a line-continuation `\` must be the **last** character before
the newline. Pasting a multi-line command can turn `\`+newline into `\`+space, which
bash reads as a literal space → the next token becomes `" --flag"` (leading space) →
`Unknown option:  --flag` (note the double space). Run commands on a single line, or
ensure no trailing spaces after `\`.

---

## Run / logging

| Flag | Default | Meaning |
|---|---|---|
| `--headless N` | 0 | Run N steps headless, then open the window. |
| `--no-render` | off | Exit after the headless run instead of opening a window. Use for long/unattended runs or piping output. |
| `--name X` | — | Log to `runs/X.csv` (+ `runs/X.config.txt`). |
| `--csv PATH` | — | Explicit CSV path (overrides `--name`). |
| `--log-every N` | 1000 | Sample/print interval in steps. |
| `--flush-every N` | 5 | Flush the CSV to disk every N logged rows. Header flushes immediately, so `tail -f` works from t=0; a Ctrl-C loses at most N rows. |
| `--seed S` | random | Seed the RNG for repeatable runs (see note). |
| `--version` | — | Print version + build time, then exit. |
| `--help`, `-h` | — | Show usage. |

## Population

| Flag | Default | Meaning |
|---|---|---|
| `--population N` | 300 | Starting creature count. |
| `--min-pop N` | 50 | Reseed floor: random creatures injected below this. |
| `--max-pop N` | 0 | Hard birth cap (0 = unlimited). Birth *ceiling*, not a culler. |

## Food

| Flag | Default | Meaning |
|---|---|---|
| `--target-food N` | 600 | Baseline food count (hard cap is 2×). |
| `--food-spawn F` | 3 | Mean food spawned per step. |
| `--food-amp F` | 2 | Sinusoidal abundance swing around the base (0 removes the external food rhythm). |
| `--food-energy F` | 5 | Energy gained per food eaten. |
| `--pickup-radius F` | 10 | Distance within which food is eaten. |

## Predator (Stage A)

**Off by default** (`--predators 0`). Stage A predators are **scripted, immortal,
and fixed-count**: no genome, no neural net, no energy economy yet. They spawn at
random positions, chase the nearest prey they can see, and capture on contact. The
*only* things under test in Stage A are the **chase kinematics** — predator speed vs
prey speed, the capture radius, and the digestion cooldown. (Stage B will give them
an energy economy / starvation+reproduction; Stage C makes them neural like prey.)

| Flag | Default | Meaning |
|---|---|---|
| `--predators N` | 0 | Number of predators (0 = none → the no-predator baseline). **Suggested start: 6.** |
| `--predator-perception F` | 150 | Predator's prey-detection radius. **Larger than prey perception (80) on purpose** — the sight gap *is* the ambush asymmetry. Set `=80` for a symmetric-sight experiment. |
| `--predator-speed F` | 110 | Predator cruise speed. Prey calm cruise is ≈82 under `--move-cost 0.00007`, so a predator out-cruises a *foraging* prey but a prey sprinting to its max (150) can pull away — at a quadratic kinetic cost. That tension is the point. |
| `--predator-capture-radius F` | 14 | Contact distance at which a prey is caught (instant kill; no meal energy yet — that's Stage B). |
| `--predator-cooldown F` | 3 | Digestion cooldown (seconds) after a capture: a predator can't catch again until it elapses. **Caps each predator's kill rate — your first anti-spiral knob.** |

**Reading a predator run:**
- The console line gains a `pred N  kills K  pAlign X` segment **only when predators
  are active** (no predators → the line is unchanged).
- `kills` there is the per-interval predation count (same as the `kills_interval`
  CSV column).
- See `predator_align` under CSV columns for the evasion instrument.

**Two failure modes to watch (this is the Stage-A tuning target):**
1. **Extinction spiral** — prey `population` rides the `--min-pop` floor (50) and the
   reseed keeps injecting fresh random genomes (which never get to evolve evasion).
   Ease it with *more food* / `--food-patches 0` (uniform), fewer/slower predators
   (`--predators`, `--predator-speed`), or a longer `--predator-cooldown`.
2. **Perfect evasion / predator irrelevance** — `kills_interval` stuck at 0 and
   `predator_align` flat: the predator is too slow or too blind to matter. Raise
   `--predator-speed`, `--predator-perception`, or `--predator-capture-radius`.

## Predator energy economy (Stage B)

**Off by default** (omit `--predator-economy`). When ON, the scripted hunter from
Stage A also runs an **energy economy**: it gains energy by capturing prey, burns
**metabolism + a kinetic move-cost** each second, **reproduces** (buds a child)
above an energy threshold, and **starves** below 0 energy (and optionally dies of
old age). `predator_pop` becomes time-varying — this is the whole point: the coupled
(Lotka–Volterra-ish) oscillator where prey crash → predators starve → predator
decline → prey rebound → predators recover. By default there is **no predator reseed
floor** — predator extinction is a legitimate, observable failure mode, not something
masked. (v0.26.0 adds an opt-in floor that masks it on purpose and counts every
predator it adds; see the next section.)

| Flag | Default | Meaning |
|---|---|---|
| `--predator-economy` | off | Master switch. Off ⇒ Stage A (immortal/fixed-count, energy inert). On ⇒ the economy below. |
| `--predator-metabolism F` | 2.0 | Predator fixed energy burn/sec (prey burn 1.5). Higher ⇒ predators need to eat more often to survive. |
| `--predator-move-cost F` | reuse | Predator kinetic cost coefficient (`F·speed²`/sec). **<0 ⇒ reuse the prey `--move-cost`** (the default); ≥0 ⇒ a predator-specific coefficient. |
| `--predator-repro-energy F` | 60 | Energy a predator needs to bud a child. Higher ⇒ slower breeding. |
| `--predator-newborn-energy F` | 30 | A child's (and the initial predators') starting energy. The parent pays this on each birth, so budding **conserves energy**. |
| `--predator-meal F` | absorb | Energy gained per capture. **<0 ⇒ absorb the victim's `foodReserves`** (the default; carnivory is calorie-dense — biological, but spiral-prone and unbounded when prey are fat). ≥0 ⇒ a fixed meal value (gentler, robust across arenas). |
| `--predator-max-age F` | 0 | Predator death age. **0 ⇒ immortal-until-starved** (the default); >0 ⇒ predators also age out. |

**The tuning target (this is a real-run, replicate task — see the reproducibility
note and context §11):** find the band where **neither population's trough hits
zero**. A useful starting heuristic from the energy balance: a predator that eats
once per cooldown breaks even at `meal ≈ cooldown · (metabolism + move_cost·speed²)`
(≈ 8.5 at the defaults), and needs roughly **1.4×** that for a breeding surplus when
fed. Below break-even ⇒ predators starve out (irrelevance); far above ⇒ they explode
until prey are pinned at the reseed floor (a degenerate "spiral" equilibrium where
the reseed feeds the predators). **The chase (Stage-A `--predators`/`-speed`/
`-cooldown`) is usually the binding constraint** — too many fast predators over-eat
prey to a crash *before* the economy can throttle them, so easing the chase
(fewer predators, longer cooldown) is the first diagnostic, exactly as in Stage A.

**Reading a Stage-B run:**
- The console gains `pE <energy>  p+<births> p-<deaths>` after the existing
  `pred/kills/pAlign` segment (only when predators are alive and the economy is on).
- `predator_avg_energy` (CSV) is the quantity to keep **above zero** — a population
  can look fine while its mean energy slides toward a crash, so watch it, not just
  `predator_pop`.
- `predator_births_interval` vs `predator_deaths_starv` (+ `_age`) read the
  oscillator directly: births>deaths ⇒ predators rising, the reverse ⇒ falling.
- **Judge across replicates over long runs.** Short runs land in different attractors
  (predators explode / persist / go extinct) under OpenMP non-determinism — use
  `-DEVO_NO_OPENMP=ON` for deterministic single runs, or run 5–10 replicates.

The win condition is the band in between: evasion evolves (it shows up as **schooling**
— rising `neighbor_align`, *not* `predator_align`; see CSV columns) **and neither side
goes extinct**. Note schooling is a **stochastic phase transition** (~1.2M+ steps, not
every run) — judge it across **replicates**, not one run (see the reproducibility note).

## Predator floor, ceiling and heritable traits (v0.26.0)

Three opt-in additions to the Stage-B economy, **all off by default** (and inert
without `--predator-economy`). Off, a run is byte-identical to v0.25.0: step-by-step
fingerprints and checkpoints match a pre-change build across 4 seeds × 7 modes, apart
from the new checkpoint fields; native == wasm parity holds on 23 cases, 4 of them
with these flags on.

| Flag | Default | Meaning |
|---|---|---|
| `--predator-min-pop N` | 0 | **The predators' `--min-pop`.** After each step's buds and deaths, fresh scripted predators are added until at least N are alive: random position and heading, `--predator-newborn-energy`, generation 0, traits 1.0. 0 = off (extinction is final). Draws nothing unless it refills. Every refill is counted in `predator_reseeds_cum` — **a run the floor holds up is not evidence of coexistence**, and that column says how much holding up it did. |
| `--predator-max-pop N` | 0 | **The predators' `--max-pop`.** A predator at its budding threshold does not bud while N are alive (counted with this step's buds, as the prey cap is); it keeps its energy and buds once there is room. 0 = no cap. Draws nothing. The floor is not capped: a floor above the ceiling wins. |
| `--predator-inherit` | off | **Heritable predator traits.** Each predator carries two multipliers, `speedFactor` (× `--predator-speed`) and `buddingFactor` (× `--predator-repro-energy`), both in [0.5, 2]. A bud copies its parent's and adds one uniform draw to each: `clamp(parent + U(−m, m), 0.5, 2)`. Off, every trait stays 1.0 and nothing is drawn. Spawned and floor-refilled predators start at 1.0. |
| `--predator-trait-mutation F` | 0.1 | The half-width `m` above (the `--body-mutation` default). Must be finite and ≥ 0. |

**What the traits cost.** Speed buys catches, and the kinetic burn is quadratic in it
(`metabolism + move_cost · (speed · speedFactor)²`), so **speed is only priced when the
kinetic cost is non-zero** (`--predator-move-cost`, or a `--move-cost` it reuses): with
both at 0, faster is free and selection walks it to the clamp. A lower budding threshold
breeds sooner and leaves the parent a thinner reserve (it still pays
`--predator-newborn-energy` per bud). These are two heritable numbers, not a genome or a
brain: the hunt is still scripted (a neural predator is Stage C).

**Reading it.** The console's economy segment gains ` pR<n>` (refills so far) with the
floor on and `pSpd <x>` (mean speed factor) with inheritance on. The CSV gains four
columns (35–38, below). Checkpoints carry the traits, each predator's generation and the
refill count; older checkpoints load at 1.0/1.0/0.

**Measured (6 seeds × 30k steps per setting, serial build; two worlds: the Stage-B
arena above and the web page's defaults).**
- **A meal at break-even never breeds predators**; they starve one by one. Breeding
  needs about 1.2× break-even, and uncapped that is a one-shot boom and crash in the
  arena (extinct 6/6 at 1.4×) and a settle onto the prey floor in the page's world at
  1.5× and above (6/6). At 1.2× the page's food-limited world coexists with no new
  knob at all (5/6).
- **The ceiling keeps both alive.** A capped predator catches about once per cooldown,
  so the cap fixes the catch rate at `cap ÷ cooldown` per second. Keep that under the
  prey's birth rate (read it off `births_interval`) with margin. In the arena (prey
  replace up to ~15–18/s) caps 12, 25 and 40 held both sides in all 96 runs at 1.2×
  and 1.4×, with 50–85 % of prey deaths being catches, and cap 60 crashed 2/6 at 1.4×.
  In the page's world (~9/s) cap 15 held both at the cap in 17/18 runs (in the 18th
  the predators dwindled to 1), and cap 30 did not hold at 1.5× and above. Capped
  predators bank their surplus energy.
- **The floor stops extinction, not the crash.** After a crash, prey stayed at their
  own floor for the rest of 90k-step runs, with the floor's predators living off the
  prey reseeds.
- **Inheritance alone makes things worse**, and needs a kinetic cost. Uncapped, it
  raised extinctions from 1/6 to 4/6 (arena, 1.2×), because buds that bud sooner boom
  faster. With no kinetic cost, speed walked to ×1.65–1.79 and predators exploded.
  Under a cap, nothing buds unless predators die, so the traits stay put. **With turnover
  they do evolve:** cap 40 + floor 2 + `--predator-max-age 120`, 60k steps, meal 1.2×:
  speed ×0.83 and budding ×0.85 (medians, 6/6 seeds), so a cheaper cruise and an earlier
  bud. That evolved population filled the cap and caught twice as many prey. At 1.4×
  the traits barely moved. Use it with a kinetic cost, a lifespan and a cap.

## Neural predators (Stage C, v0.27.0)

**Off by default.** `--predator-brain` replaces the scripted hunt with a network built
from each predator's own genome, made with the prey's machinery (the same genes, mutation
operators and network evaluation) but with the predator's own inputs and outputs:

- **21 inputs** (frozen; checkpoints carry the sensor-set version, 1): the nearest prey
  within `--predator-perception` (bearing forward / right, proximity, its heading forward
  / right), the prey in range (count, centroid forward / right), the nearest other
  predator (forward / right / proximity), own state (energy relative to the budding
  threshold, digesting, speed, age), the prey's pheromone (here, forward, right),
  the current (forward, right), and noise.
- **2 outputs:** TURN (up to `--predator-turn-rate` rad/s) and THRUST (speed ±50/s², between
  `--predator-min-speed` and `--predator-speed` × speedFactor). The kinetic cost is paid
  at the current speed, so slowing down saves energy.
- **Capture, the cooldown and the meal are Stage B's**: the nearest prey within the
  capture radius dies if the predator is not digesting. The cap rule above still holds.
- **Reproduction:** with `--predator-economy`, a predator buds as in Stage B, and the bud
  gets its parent's genome with a mutation (the prey's operators and per-birth rate
  lottery, × `--predator-mutation`). Each predator has an id, a lineage (its founder's id)
  and a parent id. A floor refill is a **random-genome founder of a new lineage**.
- **Without `--predator-economy`** the brain still runs: a fixed number of immortal neural
  hunters that never bud (the *frozen* mode a time-shift assay runs in).
- **Random draws:** the predators' genomes, mutations and noise input come from their own
  stream, seeded by one draw at the end of the world's set-up; every draw Stage B made
  stays where it was. A `--seed` reproduces a run in the serial build, and native == wasm.

| Flag | Default | Effect |
|---|---|---|
| `--predator-brain` | off | Neural predators. |
| `--predator-mutation F` | 1 | Multiplies the per-bud mutation rate. Must be finite and ≥ 0. |
| `--predator-turn-rate F` | 4 | rad/s at full TURN (the prey's `--max-turn-rate` default). |
| `--predator-min-speed F` | 0 | THRUST's floor. 0 lets a predator stop and wait (ambush). |
| `--predator-primer` | off | Founders start with two pursuit genes (PREY_LR → TURN, PREY_PROX → THRUST) written over their first two genes. Off = random genomes. |
| `--predator-log` | off | Stream every predator founding (F), floor refill (R), bud (B) and death (S starved, A aged) to `<name>.predlog.csv` (frame, event, id, parent, lineage, generation, age, captures, energy, genome length, traits). Never decimated. |

**The Stage C recipe (an evolving run):** `--predators 6 --predator-economy
--predator-brain --predator-max-pop N --predator-min-pop 2 --predator-max-age 120` plus a
meal of 1.2–1.5× break-even. **Use a max age with a cap:** predators at the cap neither die
nor bud, so without turnover evolution stops (the CLI warns).

**Outputs with the brain on** (the main CSV is unchanged):

- `<name>.predators.csv`, one row per `--log-every`: predator and prey counts; this
  interval's births, starvations, deaths of age, refills and captures; captures per
  predator-second; `pursuit_frac` (predator-steps with a prey in range);
  `captures_per_pursuit_s`; **`pursuit_align`** (mean cosine of heading against the bearing to
  the nearest prey — the hunter's mirror of `predator_align`); speed mean, CV and the share
  at ≥ 95 % of top speed; mean energy, age and generation, max generation; lineages alive;
  mean genome length; `genome_dist_mean` (mean pairwise distance of the folded networks, first
  64 predators); the share of predators wiring prey / rival / pheromone / own-state inputs;
  deaths this interval and their mean lifetime captures and age.
- `<name>.pwiring.csv` with `--wiring-log`: per predator input, the share wiring it.
- Console: ` pGen  pLen  pAln` (mean generation, genome length, pursuit alignment).
- Checkpoints are **format version 2** (a v0.26 binary refuses them): predator ids,
  lineages, parents, speed, captures, recurrent outputs and genomes, the predators' stream
  and id counter. Brain-off checkpoints stay version 1, byte for byte.

## Transplant: time-shift assay arenas (Stage C, v0.27.0)

```bash
# the arena: X's whole world, K of Y's predators (written, not run)
./build/evo_boids --load-checkpoint X.json --predators-from Y.json --transplant-count 6 \
    --transplant-seed 1 --assay frozen --transplant-out arena.json
# the assay: an ordinary resume, one per replicate seed R
./build/evo_boids --load-checkpoint arena.json --reseed-after-load R --headless 20000 \
    --csv runs/assay_R.csv --no-render
```

- **Kept from X**: the prey (genomes, brain state, ids), food, pheromones, patches, currents,
  the frame (and with it the food cycle's phase), counters, the random stream, the config.
  X's predators are dropped.
- **From Y**: K predators sampled with `--transplant-seed` (all of them by default; with
  replacement if K > |Y|), carrying only their genome, lineage, generation and traits.
  `--predators-from random` makes K random-genome founders instead (how to start Stage C on
  an evolved prey world).
- **Reset**: energy (newborn), age, digest, captures, speed (top), recurrent outputs (0.5),
  ids (fresh; Y's are in `arena.manifest.json`), positions and headings (drawn from the
  transplant seed, never from the world's stream).
- **Config**: X's. The predator physics (perception, speed, capture radius, cooldown,
  metabolism, move costs, meal, repro and newborn energy, turn rate, min speed) must match Y's,
  or the transplant is refused (`--transplant-allow-mismatch` keeps X's).
  `--predator-mutation` / `--predator-primer` come from Y.
- **`--assay frozen`** (default): economy off (K immortal predators that neither bud nor
  mutate), no predator floor or cap, prey `--min-pop 0`. **`--assay live`**: X's config.
- **Deterministic**: the arena is a function of (X, Y, K, seed, assay) byte for byte, and the
  assay a function of (arena, R) in the serial build. Score from `<name>.predators.csv`
  (captures per predator-second) and the main CSV (predation deaths).

## Environment — currents & spatial food

Off by default (`--current 0`, `--food-patches 0`). Currents only *matter* when food
is spatial, so use them together.

| Flag | Default | Meaning |
|---|---|---|
| `--current F` | 0 | Peak ocean-flow speed (world units/sec). 0 = no current. Compare to **cruise speed** (≈82 with `--move-cost 0.00007`), not max-speed: at `--current 80` they *fight*, at `--current 150` they *ride* (see context §3). |
| `--current-mode M` | eddies | `eddies` = moving vortices → many small pockets. `gyre` = double-gyre → two counter-rotating basins + oscillating divider (cleaner two-region isolation). |
| `--current-eddies N` | 5 | [eddies] Number of vortices. |
| `--current-core F` | 150 | [eddies] Eddy radius (peak-speed distance). |
| `--current-drift F` | 1.0 | How fast the field evolves (0 = static). For gyre, the separatrix oscillation rate. |
| `--gyre-eps F` | 0.25 | [gyre] How far the dividing line swings (0 = fixed vertical split). |
| `--food-patches N` | 0 | Cluster food into N spatial patches (0 = uniform). Patchy food is what makes a current consequential. |
| `--food-patch-radius F` | 120 | Spread of food around each patch centre. |
| `--food-drift` | off | Advect food *with* the current → drifting filaments (no-op if `--current 0`). |

Both current modes are divergence-free (velocity = curl of a streamfunction) — no
sinks, matter stretches into filaments. Two sensors (`CURRENT_FWD`, `CURRENT_LR`) let
evolution perceive the flow. Predators are advected by the current too, so phase-2
(current on) stays kinematically consistent between hunter and hunted. The GUI draws
a faint flow overlay when a current is active (currently only visible in the world's
top-left corner — see context renderer note).

## Genes

| Flag | Default | Meaning |
|---|---|---|
| `--genome-min N` | 16 | Hard lower bound on gene count. |
| `--genome-max N` | 80 | Hard upper bound on gene count. |
| `--genome-init-min N` | 24 | Initial gene-count range (low). |
| `--genome-init-max N` | 48 | Initial gene-count range (high). |
| `--mutation F` | 1.0 | Multiplier on the per-birth mutation rate. |
| **`--repro-max-distance F`** | **off (<0)** | **Match distance** (v0.21.0). A pair farther apart than `F` in the folded **(source,sink) connectivity space** emits no successor record; every other precondition is unchanged, and an out-of-threshold pair burns its interaction cooldown exactly as an under-energised pair already does. Uses `genomeDistanceSq()` (`src/core/isolation.hpp`) — **not** `genomeSimilarity()`, which is positionally aligned and collapses on a single indel. **Measured scale** (so the number means something): unrelated random genomes ≈ **19.5** apart; in-run pairs within `--interact-radius` sit at median **18–20** (p05 ≈ 13–17); a mutated clone ≈ **0**. So the live window is roughly **12–22** — above ~23 the gate is inert, below ~12 essentially nothing pairs and the live count falls to the `--min-pop` floor. Off ⇒ byte-identical to before (fingerprint-verified, 4 seeds × 5 modes). Costs nothing when off (one float compare, no RNG draw). Requires `--genome-max ≤ 1024`. Non-finite values are refused at the CLI and `evo_init` (v0.24.0): a NaN threshold would silently *arm* a gate that rejects every pair (`NaN < 0` is false, `d² ≤ NaN²` is false), pinning the run to the `--min-pop` floor with no diagnostic. |
| **`--repro-soft-width F`** | **off (≤0)** | **Soft gate** (v0.24.0). Widens `--repro-max-distance` from a cliff into a **linear acceptance ramp `F` wide**, in the *same* folded-connectivity units as the threshold. With `T` = threshold and `W` = `F`, a pair at distance `d` is admitted iff `u·W < (T + W) − d` for one fresh uniform draw `u`: **`d ≤ T` always breeds, `d ≥ T + W` never does**, and acceptance falls linearly in between. `≤0` = off = the exact hard comparison, which is why archived `--repro-max-distance` runs stay byte-identical (fingerprint-verified against v0.23.0, 4 seeds × 6 modes — the modes include a hard-gated one, since the gate code was restructured under both knobs). **Inert without `--repro-max-distance ≥ 0`** (there is no cliff to soften). Why: the measured window is narrow and collapse is bistable at `T ≈ 16` and total below `≈14`, so a hard threshold there admits nothing at all — measured at 2000 steps, seed 42, `T=16`: **1** insertion hard vs **55** with `W=5`, **53** of them above the hard threshold (`soft_births_cum`). **RNG stream note:** with `W > 0` the gate draws **exactly one** `rng.unit()` per evaluation, **unconditionally** — the same draw whether the pair is inside the threshold, in the ramp or far outside it — so the draw count never depends on a value and native == wasm holds (parity case `soft_s42`). This **is** a new random stream: an `F > 0` run is not comparable bit-for-bit with the same seed at `F ≤ 0`. The hard path, the grace bypass and the gate-off path draw nothing at all. Non-finite values are **refused by the CLI and the browser's `evo_init`**; the checkpoint reader deliberately does *not* re-validate the gate knobs (unlike `--body-mutation`) — a non-finite width cannot poison creature state, it can only deterministically refuse (NaN) or admit (inf) pairs. Negative simply means off. **Sweep verdict (20k steps × 6 seeds, v0.24.0):** at `T=16`, `W=4` is the one mitigation that fully clears the bistable collapse — tail-median pop **434 [372–479]** vs **228 [50–440]** hard, at ~75% of the no-gate birth rate and a 0.48 mitigated share, so the gate still bites; at `T=14` it stays bistable (some seeds still hit the floor). |
| **`--repro-grace F`** | **off (≤0)** | **Refill grace** (v0.24.0). A **founder** younger than `F` seconds **bypasses the gate entirely** — no distance fold, no draw — if *either* partner qualifies. Founder means the creature's lineage starts at itself (`lineageId == id`): the initial spawn **and every `--min-pop` reseed**, never a child (it inherits the maternal line). No new creature state and no new checkpoint column: `lineageId` and `age` were already serialized. `≤0` = off, and **`≤5` is inert too** — reproduction already requires `age > 5`, so only the window `(5, F)` does anything. **Inert without `--repro-max-distance ≥ 0`.** Why: under a tight gate the reseed floor becomes a *diversity pump that cannot reproduce* — refilled creatures sit ≈19.5 from everyone, so they eat, never pair, and pin the population on the floor (§7.1 of the plan; the effect is measured in the v0.21.0 sweep). Grace lets an injected genome enter the pool once; its descendants are gated from birth. Measured at 2000 steps, seed 999, `T=13`: **0** insertions without it vs **197** with `--repro-grace 60`, all 197 via the bypass (`grace_births_cum`). **Draws nothing on any path**, so unlike the soft ramp it does not move the random stream — it changes *which* pairs breed, which is enough to change the run. Non-finite values are **refused by the CLI and the browser's `evo_init`** (the checkpoint reader does not re-validate the gate knobs — see the soft-width row for why that is safe). Negative simply means off. **Sweep verdict (20k steps × 6 seeds, v0.24.0):** grace alone does **not** stabilize — at `T=16` it trades collapse for boom-bust around a low population (tail-median **117 [61–274]**), and at `T=14` it carries **0.94** of all births, the inert-gate failure mode. Use it as an entry valve for injected genomes alongside the soft ramp, not as the stabilizer. |
| **`--body-model`** | **off** | **Tier-1 body model** (v0.23.0). Two heritable per-creature parameters — `bodySize` and `bodyElong`, both clamped to **[0.5, 2.0]** — that modulate the *existing* speed/turn/metabolism model. No new physics, no new sensor, no format break. **Factors** (`src/core/body_model.hpp`, plain float arithmetic, no transcendentals, no RNG): speed ceiling × `2/(1+bodySize)`, turn rate × `2/(1+bodyElong)`, metabolism × `bodySize`. So a **bigger** body is slower *and* dearer to run; a **longer** body turns worse. All three are exactly **1.0** at the default body, and `x·1.0f` is IEEE-exact, so off ⇒ byte-identical to before (fingerprint-verified, 4 seeds × 5 modes). Deliberately a **separate parameter vector, not derived from the neural genome** — attribution ("body or brain?") and future body-gating need the body to vary independently of the wiring. The turn factor only bites under `--triangular-motion`, the only mode that reads `--max-turn-rate`. `bodySize`/`bodyElong` also scale the drawn body-segment spacing (`4·size·elong`), which is **visual only** — no sensor reads `body[]`. **`--max-speed` becomes the ceiling of a *default* body, not a hard world cap**: at the small rail the ceiling is `1.333 × --max-speed` (200 at the stock 150), at the large rail `0.667 ×` (100) — measured, a seed-42 run peaks at 159.7 with the flag on vs exactly 150.0 with it off. **`OWN_SPEED` is deliberately left normalised by `--max-speed`, not by the creature's own ceiling**: a speed-capped big body reads a permanently lower `OWN_SPEED`, and a small body can read *above* 1.0. That asymmetry is information the brain can evolve to use, which is why the sensor is untouched (adding one would re-base `geneCell` and break the genome corpus). **Founders start at 1.0/1.0 and draw nothing**, including reseeded ones — diversity comes from mutation, and it keeps the `--min-pop` reseed floor from injecting extreme bodies into a collapsing population. **RNG stream note:** with the flag on, each successful insertion draws **exactly two** `rng.range` values, `bodySize` then `bodyElong`, with no rejection loop and no Gaussian, so the draw count is input-independent (this is what keeps native == wasm bit-exact). With the flag **off** the body path draws nothing at all, so every archived run stays reproducible. Checkpoints carry both config keys and two always-written creature columns; pre-0.23 checkpoints load with the gate off and every body at 1.0. **MEASURED, and it matters before you use this flag: bodies do not grow — they shrink, monotonically, to the 0.5 rail, and 2.0 is unreachable at any usable mutation rate.** Two independent reasons: blending inheritance (`mean(parents) + jitter`) pins the standing spread at `sd = 0.816 × --body-mutation` — 12 sd short of the top rail at the default — and size is a pure tax (slower *and* dearer) with no compensating benefit anywhere in the sim, so the only stable outcome is the smallest legal body. Raising `--body-mutation` makes them shrink *faster*. Treat this flag as a measurement of the **cost** of size, not as morphological evolution; full numbers in the research log's "The tier-1 body model cannot evolve size" entry. |
| **`--body-mutation F`** | **0.1** | [`--body-model` only] Uniform mutation **half-width per parameter per birth**: `child = clamp(mean(parents) + U(−F, +F), 0.5, 2.0)`. Must be **finite and ≥ 0** — negative and non-finite values are refused, not reinterpreted, and all three entry points agree: the CLI, the browser's `evo_init`, and the checkpoint reader (so a hand-edited config block cannot smuggle one in either). `0` = inheritance with no drift: a uniform founder body is passed down bit-for-bit forever, while the two draws still happen — the draw *count* never depends on `F`. Larger `F` explores morphology faster and reaches the clamps sooner. Inert when `--body-model` is off. |

## Selection pressure

| Flag | Default | Meaning |
|---|---|---|
| `--metabolism F` | 1.5 | Fixed energy burned per second, per creature. |
| `--gene-cost F` | 0 | Extra energy/sec **per gene** (parsimony pressure). >0 selects against bloat. (Note: 0.01 does **not** meaningfully tame bloat under currents — don't read genome length as fitness.) |
| **`--move-cost F`** | **0** | **Kinetic cost: extra energy/sec = `F · speed²`.** 0 = off (speed is free, reproducing prior behaviour). >0 makes thrust expensive → an **interior optimal cruise speed** and makes fighting a current costly. **Calibrated value: `0.00007`** → cruise ≈82 (half of max), population healthy. Robust optimum (3e-5 and 7e-5 both land ~82). **This is foundational** (the predator needs it) and is in the frozen baseline. |
| `--max-age F` | 120 | Death age. |
| `--repro-energy F` | 20 | Energy each parent needs to reproduce. |
| `--newborn-energy F` | 25 | Starting energy of a child. |

## Sensing / movement / cooldowns

| Flag | Default | Meaning |
|---|---|---|
| `--toroidal` | off | **Wrap-around senses** (v0.19.0). Positions have always wrapped; this makes perception wrap too: neighbour/food/predator queries and offsets use minimum-image distances across the seam, pheromone deposits/reads wrap, the long probe looks through the seam, and the `BOUNDARY_*` sensors read saturated no-wall (a torus has no walls). Cures the seam's sensory cliff (an edge-band creature otherwise perceives ~half its true neighbours — measured 3.0 vs 5.8) and the wall-hugger / seam-oscillator phenotypes it breeds. Currents stay a bounded basin (small flow discontinuity when crossing the seam); `LOC_X`/`LOC_Y` stay absolute position. Off ⇒ byte-identical to before (fingerprint-verified). ~1 % throughput cost. |
| `--perception F` | 80 | Neighbour/food sensing radius (also the spatial-grid cell size). Also the radius at which a prey *sees* a predator (the `PREDATOR_*` sensors). |
| `--interact-radius F` | 20 | Social-interaction range (also the `INTERACT_FIGHT` adjacency range). |
| `--max-neighbors N` | 0 (all) | **Topological interaction**: attend to only the `N` *nearest* neighbours inside `--perception`, instead of averaging over every one of them. 0 = the historical metric rule, preserved byte-for-byte. Real animals are topological, not metric — starlings track ~6–7 nearest regardless of flock density (Ballerini et al., PNAS 2008), and fish studies find fewer still (Katz et al. / Herbert-Read et al., PNAS 2011). Under the metric rule a fish in a dense school averages over ~150 neighbours, which no real animal does. Only the *interaction* percepts are capped (`AVG_NEIGHBOR_*`, `POPULATION_FWD/LR`); `NEIGHBOR_COUNT` and `POPULATION_DENSITY` still report the true count in range, since crowding is a real percept. Max 64. Roughly throughput-neutral (−7 % to +8 %) — this is a **model** change, not a speed knob. |
| `--topological` | — | Shorthand for `--max-neighbors 7`, the Ballerini number. |
| `--min-speed F` | 30 | Minimum speed. **Set 0** when `--move-cost` is on, so drifting (speed 0, zero kinetic cost) is an available strategy. |
| `--max-speed F` | 150 | Maximum speed. |
| `--triangular-motion` | off | Couple the action space: the net commands a forward **drive** and a **turn**, and feasible turn is throttled by drive (`turnEff = turn·(1−drive)`). Fast strike ⇒ can't turn; slow reorient ⇒ full turn authority. Replaces the decoupled steer/speed model. Off ⇒ byte-identical to original. Motivated by the hunting paper's finding that this forced trade-off produces clean strike-vs-reorient bouts. |
| `--max-turn-rate F` | 4.0 | [triangular only] Max heading change (rad/s) at zero forward drive; drive scales it down to 0 at full speed. |
| `--repro-cooldown F` | 3 | Seconds between reproductions. |
| `--interact-cooldown F` | 2 | Seconds between social interactions. |

---

## Analysis / inspection (v0.11.0)

Both features are opt-in and do **not** affect the simulation, the metrics CSV, or
any existing run — they only observe.

**Live neural inspector (windowed runs).** LEFT-CLICK a fish to select it; a
translucent panel appears top-right showing its neural network firing live:
- three node columns — **sensors** (left, 41 inputs) → **hidden** neurons (middle,
  up to 12) → **actions** (right, 12 outputs); each node's fill is its current
  activation (blue = negative, grey = idle, red = positive; brighter = stronger);
- **connections** are tinted by weight (green = excitatory, red = inhibitory) with
  opacity scaled by weight × source activation, so live signal flow is visible;
- the selected fish gets a yellow ring in the world; click empty water to deselect,
  click another fish to switch. Action nodes are labelled (steerX, moveFwd, …).

Driven by per-step captured activations, enabled automatically only when a window is
open (headless runs pay nothing for it).

| Flag | Default | Meaning |
|---|---|---|
| `--cluster-map` | off | At end of run, write `<name>.deaths.csv` + `<name>.cluster.svg` (below). Off ⇒ nothing logged, no allocation. |
| `--cluster-epoch N` | 1000 | Deaths per colour band. Each band is one step along the cool→warm ramp, so colour encodes *when* (in death order) a network died. |
| `--cluster-max N` | 20000 | Max points kept in RAM. Past this the log is uniformly decimated (keep every other point, double the stride), so a multi-million-death run stays bounded and the SVG renderable while remaining an even sample across the run. |
| `--cluster-pca` | off | Map axes = **PCA** over the death sketches (per-run, variance-aligned, fills the frame) instead of the fixed random projection. The deaths CSV keeps the stable random `x,y`; PCA is a view choice for the SVG only. |
| `--cluster-color M` | `epoch` | `epoch` colours points by death order (the ramp); `lineage` colours by clade (hashed founder id) so selective sweeps show as large same-colour clusters. |
| `--wiring-log` | off | Headless: write `<name>.wiring.csv`, one row per log interval — the fraction of the live population wiring each of the 41 sensors as a source. Reveals which inputs selection recruits over the run. |
| `--repro-log` | off | Headless: write `<name>.births.csv`, one row per kept pairing event — `index,frame,parent1,parent2,lineage1,lineage2`. This is the **pairing graph**: an edge means those two creatures actually produced a successor record. Bounded and uniformly decimated exactly like the cluster map, so `index` is the true event ordinal and the stride is reported in the file header. |
| `--repro-log-max N` | 20000 | Max pairing records kept in RAM; uniformly decimated above this. |
| `--repro-window N` | 2000 | Trailing pairing events behind the always-on `repro_components` CSV column (0 disables the column). Undecimated on purpose — dropping edges fragments a connected graph and would inflate the very count being measured, which is why this is a separate ring buffer from the archive above. |
| `--repro-min-cluster N` | 3 | Ignore pairing-graph components smaller than N. A one-off pairing is not a group; without this the count is dominated by isolated pairs. |
| `--profile` | off | Headless: accumulate per-phase timings and print a build / parallel{sensor-gather, feedForward, apply} / serial split at end. Diagnostic only; gated so it never affects dynamics. Run it at your real N and core count before optimizing. |
| `--save-checkpoint FILE` | — | Write the complete world state to `FILE` (JSON) at the end of the headless run. ~1.2 KB per creature (a 233-creature world is 270 KB; gzips to ~40 %). |
| `--load-checkpoint FILE` | — | Resume from `FILE` instead of starting fresh. **In a serial build the continuation is bit-for-bit identical to the run that was interrupted** — verified end to end: 600 steps in one go produces the same bytes as 300 + resume + 300. Adopts the checkpoint's world size and config, so simulation flags on the resume command line are ignored (edit the file instead). |
| `--reseed-after-load S` | off | Needs `--load-checkpoint` (refused without it). After the load, seed the rng with `S` instead of continuing the checkpoint's saved stream, so replicate continuations of one checkpoint differ (`--seed` is ignored on resume: the saved rng state overwrites it). Same `S` reproduces bit for bit in a serial build; different `S` diverge from the first draw. Everything else is the checkpoint's. CLI-only (not a config field, not in the wasm module); the end checkpoint records the reseeded stream's state, so it still resumes exactly. Used by `tools/invasion/` for replicate arena runs. |
| `--checkpoint-every N` | 0 (off) | Also write `<base>.<frame>.json` every N steps, so a long run leaves a trail you can rewind to. Base is `--save-checkpoint`'s path if given, else `runs/<name>`. |
| `--fast-tanh` | off | Replace `std::tanh` in the net with a Padé (7,6) rational, worst error 1.1e-4. Worth **1.2–1.3×** end-to-end, because every creature makes 24 `tanh` calls per step regardless of genome size — over half of `feedForward`'s cost. **Changes the numbers**: a chaotic system amplifies 1e-4 into different trajectories, so runs made with it are a separate numerical lineage and won't match the existing corpus. Measured over 12 seeds × 4000 steps, with and without predators, the outcome *distributions* (population, schooling, genome length, genetic diversity, species) are statistically indistinguishable — so it's sound for exploratory sweeps; re-confirm headline findings with it off. Recorded in the run sidecar. |

**Death-cluster map.** Every time a creature dies, its network is projected (a fixed
random sketch is stored; the SVG plots either the fixed 2-D random map or, with
`--cluster-pca`, a PCA of the sketches). At end of run:
- `<name>.cluster.svg` — every logged death as a point, coloured by epoch (ramp) or
  lineage; **epoch centroids joined by arrows** show the population's drift direction
  through projection space; a **top-lineage summary** (id, % of deaths, epoch span)
  reads selective sweeps directly. Self-contained; opens in any browser. Reading it: a
  tight single-colour clump = a converged population then; the centroid track moving =
  networks drifting under selection; one lineage colour dominating a region/epoch span
  = a sweep.
- `<name>.deaths.csv` — `index,x,y,epoch,lineage,age,genome_len,cause` per kept death
  (`cause` ∈ p/s/a). Re-plot or analyse freely (PCA over x,y, group by lineage, etc.).

**Pairing graph.** `--repro-log` → `<name>.births.csv`, plus the always-on
`repro_components` CSV column (32nd, appended in v0.22.0 — every earlier column keeps
its index). The column is the number of connected components with ≥ `--repro-min-cluster`
members in the graph of which records paired with which, over the last `--repro-window`
pairing events.

Read it **instead of** `species`, not alongside it, when the question is group
separation. `species` is a SimHash of the same folded connectivity vector that
`--repro-max-distance` thresholds, so it cannot evaluate that gate without
circularity — and it is **saturated** regardless: measured across every arm of the
v0.21.0 sweep including the ungated control, it tracks the live-set count almost
one-to-one (475 buckets for 480 creatures), i.e. at 16 hash bits it is counting
individuals. `repro_components` is mechanism-level: an edge exists because an insertion
happened, so it cannot be circular with a `Genome`-space gate. `0` means no edges in the
window — the honest report for a live set that has stopped pairing; read it with
`births_interval`.

**Sensor-wiring frequency.** `--wiring-log` → `<name>.wiring.csv`: `step` plus one
column per sensor (named), each the fraction of the population whose genome wires that
sensor as a source. Plotting a column over time shows recruitment — e.g. the
`PREDATOR_*`/neighbour sensors climbing once predation selects for evasion, or unused
sensors sitting near their random-chance baseline.

> Projections are **lossy shadows** of a ~1272-dim space. The fixed random map is
> reproducible/comparable across runs and coherent with the genome colour; PCA is
> per-run and variance-aligned (better for one run's legibility, not comparable across
> runs because the axes are data-dependent). Lineage = founder of the **maternal**
> line (parent1 at each birth); crossover means a clade's genomes still recombine.

## CSV columns (one row per `--log-every` interval) — **38 cols as of v0.26.0**

`step, elapsed_s, steps_per_sec, population, food, births_cum, deaths_cum,
births_interval, deaths_interval, avg_age, max_age, avg_energy, avg_speed,
avg_genome_len, genome_len_std, avg_responsiveness, avg_osc_period,
genetic_diversity, species, flow_align,
predator_pop, kills_interval, deaths_starvation, deaths_age, predator_align,
neighbor_align, neighbor_count,
predator_births_interval, predator_deaths_starv, predator_deaths_age, predator_avg_energy,
repro_components, grace_births_cum, soft_births_cum,
predator_reseeds_cum, predator_speed_factor, predator_budding_factor, predator_generation`

- `genetic_diversity`: RMS distance from the population mean in connectivity space
  (~14 scale, exact). Coupled to genome length. Not comparable to pre-rework CSVs.
- `species`: distinct SimHash buckets — collapses toward 1 on convergence, rises
  toward population size when diverse. Cleaner convergence signal. **Blind to
  non-connectivity traits** (e.g. a future body-size gene).
- `flow_align`: mean cosine of heading vs local flow. **+1** ride/surf, **−1** fight
  upstream, **0** crosswise *or* no current. **Read with `avg_speed`** (low speed =
  drifting; high+positive = surfing; high+negative = fighting).
- `repro_components` (32nd, appended in v0.22.0): connected components with ≥
  `--repro-min-cluster` members in the pairing graph over the last `--repro-window`
  events — see the *Pairing graph* section above. **Restarts empty on checkpoint
  resume** (the window is per-run state, like the death log), so the column needs up
  to `--repro-window` post-resume pairing events before it is comparable to an
  uninterrupted run's.
- `grace_births_cum` / `soft_births_cum` (33rd/34th, appended in v0.24.0): cumulative
  counts of the insertions that `--repro-grace` and `--repro-soft-width` are
  responsible for — both **subsets of `births_cum`**, both **0** on every run with the
  mitigations off (including a plain `--repro-max-distance` run). `soft_births_cum`
  counts only the insertions the hard gate at the same threshold would have
  **refused**; a pair already inside the threshold that the ramp happened to accept is
  not counted, because it needed no help. Unlike `repro_components` these are world
  counters, so they **survive a checkpoint resume**. To read them against the birth
  rate, **difference them between rows first** — e.g.
  `(grace_births_cum[i] − grace_births_cum[i−1]) / births_interval[i]` — and take the
  per-interval delta as a share of `births_interval` (dividing the raw cumulative
  column by a per-interval column yields a "share" that grows without bound). A
  mitigation that is carrying the whole birth rate at equilibrium has made the gate
  inert, which is the failure mode to watch for.
- `predator_reseeds_cum` (35th, appended in v0.26.0): predators the
  `--predator-min-pop` floor has added, cumulative. **Not** a subset of the predator
  births — a refilled predator was not born. 0 with the floor off. Survives a
  checkpoint resume.
- `predator_speed_factor` / `predator_budding_factor` / `predator_generation`
  (36th–38th, v0.26.0): the live predators' mean speed trait, budding-threshold trait
  and generation (buds since a spawned or refilled founder), instantaneous. **0 when no
  predator is alive** (the `predator_avg_energy` convention), exactly 1.000 for the two
  traits with inheritance off; the generation counts buds either way.

**New in v0.9.0 (5 columns, appended last → existing column-by-name parsing is
unaffected):**

- **`predator_pop`** — instantaneous predator count. Constant in Stage A (predators
  are immortal/fixed-count); it's a column now so Stage B (where it varies) needs no
  format change.
- **`kills_interval`** — predation deaths this interval (diffed from a cumulative
  total, like births/deaths). Identical to the console `kills` field.
- **`deaths_starvation`** / **`deaths_age`** — the other two death causes this
  interval. Together with predation they **partition** the deaths:
  `deaths_interval == kills_interval + deaths_starvation + deaths_age` (exact, every
  row). This is what lets you tell *how* a population is dying — predator pressure vs
  starvation (food too scarce) vs old age (a calm, food-rich run).
- **`predator_align`** — the evasion instrument, mirroring `flow_align`: mean cosine
  between a prey's heading and the **away-from-nearest-predator** direction, gated to
  prey that actually have a predator within their own perception (80). **+1** fleeing
  straight away, **−1** swimming right at it, **0** crosswise *or* no threat in range.
  **Read it WITH `avg_speed`:** fleeing only matters if they're also moving — without
  the speed context you can't distinguish "evasion evolved" from "the slow ones just
  got eaten." Expect ~0 early (a fresh genome baseline hasn't evolved evasion yet);
  a sustained climb is the signal you're tuning for.

**New in v0.9.1 — schooling instruments (2 columns, appended last):**

- **`neighbor_align`** — local polarization: for each prey, the cosine between its
  heading and the **mean heading of prey within its perception (80)**, averaged over
  prey that have ≥1 neighbour. **+1** = locally aligned (a school), **0** = neighbours'
  headings cancel (disordered foraging). It is **local on purpose** — several schools
  pointing different ways each read high, whereas a *global* polarization (whole-pop
  mean heading) would cancel them to ~0 and hide the schooling. **This is the schooling
  metric — use it, not `predator_align`.** Measured empirically: **0.97 in a schooled
  run vs 0.06 in a non-schooled one.** Two caveats: (a) it measures *polarization*, so
  a school that **mills** (up-and-down a common axis, bidirectional) reads ~0 even
  though it looks coherent; (b) schooling is **stochastic** — the *same command* gave
  0.06 and 0.97 on different runs (OpenMP non-determinism), and it only appears after
  ~1.2M steps, so **judge it across replicates over long runs**, never one run.
- **`predator_align`** is the *wrong* axis for this sim (kept for completeness): it
  assumes prey flee individually/radially, but they evade by **schooling**, so it sits
  near a culling-artifact floor (~0.2) even mid-schooling. Don't read evasion off it.
- **`neighbor_count`** — mean number of prey within perception (local crowding). A
  school is aligned **and** clumped, so read the two together: high align + high count
  = a tight school (saw ~27); high align + low count = a loose comigration; low align =
  no polarized school regardless of count.

**New in v0.10.0 — predator energy economy (4 columns, appended last):**

- **`predator_births_interval`** — predators budded this interval (diffed from a
  cumulative total). 0 in Stage A.
- **`predator_deaths_starv`** / **`predator_deaths_age`** — predator deaths this
  interval by cause (starvation / old age). Together with births they read the
  oscillator: births > (starv+age) ⇒ predators rising. Both 0 in Stage A.
- **`predator_avg_energy`** — instantaneous mean energy over the live predators
  (0 when no predators, and **0 in Stage A** where the field is inert). This is the
  quantity to keep **above zero** when tuning — a predator population can look stable
  while its mean energy slides toward a crash. Read it the way you read prey
  `avg_energy`.

**How to use them (the experiment that found the schools):** run the same config
**with and without predators** (`--predators N` vs `--predators 0`, everything else
identical). If `neighbor_align` (and `neighbor_count`) are markedly higher *with*
predators, the schooling is predator-induced — i.e. it's collective evasion — rather
than baseline flocking. **Run several replicates of each** (≥1.5M steps): a *single*
run is not representative — schooling is a stochastic phase transition, so one
predator run may read 0.06 (didn't tip) and another 0.97 (tipped). The contrast you
trust is *with-predator replicates vs without-predator replicates*, not one vs one.
(Full move-by-move experiment log, with every run's command + CSV name + result, is in
the context file, §10.)

> Note: creature **colour** is a locality-preserving 3-D projection of the
> connectivity genome (similar genomes → similar colours; lineages drift smoothly).
> It's a visualisation aid and a *shadow* of the `species` metric — not an independent
> measure, and it does not affect sim RNG/dynamics.

---

## Notes

- **This is evolution, not learning.** Neural-net weights are fixed at birth (parent
  crossover + mutation) and never change during life. Adaptation is cross-generational.
  (Stage-A predators don't even have a net — they're scripted.)
- **`--seed`, OpenMP & reproducibility (READ THIS before drawing conclusions):**
  with an OpenMP build, `--seed` pins only the **single-threaded** parts (spawning,
  interactions, deaths, predator hunt + economy, init); the **parallel** sensor/
  movement phase uses **per-thread RNGs**, so runs are **not reproducible** at a
  fixed seed. This bit *qualitatively* in Stage A: the **same command** gave
  `neighbor_align` 0.06 on one run and 0.97 on another (loose mill vs tight school).
  ⇒ **Operating rule: use replicates, not single runs** — run a command 5–10× and
  report the distribution; **or build the serial target** for deterministic single
  runs: `cmake -S . -B build-serial -DEVO_NO_OPENMP=ON && cmake --build build-serial`
  (slower, but a fixed `--seed` reproduces byte-for-byte — verified). Emergent
  collective behaviour also needs **≥1.5M steps** to appear. This matters **more in
  Stage B**, where the coupled oscillator adds its own sensitivity on top of the RNG
  non-determinism. (Older noise-floor note still holds: genome-length / species swing
  run-to-run even at fixed seed — don't over-read small deltas.)
- **Build type & speed:** the binary is built **`-O3`** (Release). (Note: a *blank*
  `CMAKE_BUILD_TYPE` in `CMakeCache.txt` is cosmetic — the CMakeLists defaults to
  Release via a normal variable and still emits `-O3`.) If a run is unexpectedly slow,
  it's almost always **(a)** the config (≈4000 food at `--target-food 2000` ⇒ ~6× more
  food-grid scanning than 600-food) or **(b)** thermal throttling on a laptop after a
  long all-core session (CPU pegged at 800% but clocked down) — **not** the metric
  code (which runs once per `--log-every`, ~negligible).
- **`--name` is just a label** — `--headless N` sets the step count.
- **Not yet flags** (code changes): **predator Stage C** (neural predators — their
  own evolving genome/net population). **Now flags as of 0.10.0:** the predator
  Stage B energy economy (`--predator-economy` + the meal/metabolism/repro/age/
  move-cost knobs). Still code changes: logistic/density-dependent food regrowth,
  mutation-operator rebalancing, camouflage / spatially-varying background, a
  body-size trait, a per-creature spatial-structure snapshot / Moran's I, the
  renderer `setView` fix, and in-life (Hebbian/NEAT) learning.
- **NUM_SENSES history:** v0.6.0 changed it 36→38; v0.9.0 changes it **38→41** (three
  `PREDATOR_*` prey sensors). So **0.9.0 runs are a fresh baseline** — their
  genomes/diversity are *not* mutually comparable with 0.6–0.8 runs (and pre-0.6 even
  less so). This holds **even with `--predators 0`**: the sensors exist regardless;
  predators just never populate them. Re-establish a baseline on 0.9.0 before reading
  cross-version deltas.

## Examples

```bash
# === SCHOOLING / ISOLATION ARENA (the runs that produced the Stage-A result) ===
# Superabundant food + pop cap => starvation ~0 => predation is the main selection.
# Run BOTH and several replicates of each (schooling is stochastic; needs >=1.5M steps).
# WITH predators (schooling emerged here, as a phase transition ~1.2M steps):
./evo_boids --headless 2000000 --name school_pred --predators 6 --food-patches 0 --target-food 2000 --food-spawn 12 --max-pop 350 --current 0 --current-mode gyre --gene-cost 0.01 --move-cost 0.00007 --min-speed 0 --seed 42 --log-every 2000 --no-render
# WITHOUT predators (control — no schooling, high colour diversity):
./evo_boids --headless 2000000 --name school_ctrl --predators 0 --food-patches 0 --target-food 2000 --food-spawn 12 --max-pop 350 --current 0 --current-mode gyre --gene-cost 0.01 --move-cost 0.00007 --min-speed 0 --seed 42 --log-every 2000 --no-render
# Read: neighbor_align (0.97 schooled vs ~0.06 not) + neighbor_count (tight ~27 vs ~3.3)
# across replicates. NOT predator_align (wrong axis). Lighter/faster variant: drop
# --target-food to 800 and --max-pop to 200 (still no starvation, ~2x faster).

# === PREDATOR Stage A — the older "frozen baseline" start (food patches) ===
# NOTE: this patchy config SPIRALED at --predators 6 (prey crashed to the floor).
# It's kept for continuity with §3/§5; for behaviour studies use the isolation arena above.
./evo_boids --headless 1000000 --name pred6 --predators 6 \
  --current 0 --current-mode gyre --food-patches 6 --food-drift \
  --gene-cost 0.01 --move-cost 0.00007 --min-speed 0 --seed 42 --log-every 2000 --no-render

# Dial sweep examples (one knob at a time):
#   easier on prey:   --predator-cooldown 5     (fewer kills/predator)  or  --predators 4
#   harder on prey:   --predator-speed 130       or  --predator-capture-radius 20
#   symmetric sight:  --predator-perception 80   (removes the ambush asymmetry)

# === FROZEN BASELINE (no predator; calm-water start) ===
./evo_boids --headless 1000000 --name base --current 0 --current-mode gyre \
  --food-patches 6 --food-drift --gene-cost 0.01 --move-cost 0.00007 \
  --min-speed 0 --seed 42 --log-every 2000 --no-render
# (--food-drift is a no-op at current 0, kept so phase-2 is a one-flag change)

# === PREDATOR Stage B — the energy economy (the ACTIVE tuning frontier) ===
# Turn the economy on with --predator-economy. The defaults (absorb-reserves meal,
# metabolism 2, repro 60) are a STARTING POINT, not a tuned oscillator: in short
# sandbox runs the absorb-reserves default lets predators explode until prey pin at
# the reseed floor. A fixed meal is more controllable. TUNE on long runs +
# replicates (or the serial build) until NEITHER population troughs to zero.
#
# Isolation arena, fixed meal, max-pop relaxed so prey can oscillate (not pin at a cap):
./evo_boids --headless 2000000 --name predB_iso --predators 6 --predator-economy \
  --predator-meal 14 --predator-metabolism 2 --predator-repro-energy 60 \
  --food-patches 0 --target-food 2000 --food-spawn 12 --max-pop 600 --min-pop 20 \
  --current 0 --current-mode gyre --gene-cost 0.01 --move-cost 0.00007 --min-speed 0 \
  --seed 42 --log-every 2000 --no-render
# Watch predator_avg_energy (keep > 0) and predator_births vs predator_deaths_starv.
# First knobs if it spirals/collapses (one at a time): --predator-meal,
# --predator-metabolism, --predator-repro-energy; then EASE THE CHASE
# (--predators 4, --predator-cooldown 5) — the chase is usually the binding constraint.
#
# Deterministic single run for definitive cause-and-effect (build the serial target):
#   cmake -S . -B build-serial -DEVO_NO_OPENMP=ON && cmake --build build-serial -j
#   ./build-serial/evo_boids ... (a fixed --seed reproduces byte-for-byte)

# Phase 2 once the predator is stable: turn the current on (the "ride" regime)
./evo_boids --headless 1000000 --name pred6_c150 --predators 6 --current 150 --current-mode gyre \
  --food-patches 6 --food-drift --gene-cost 0.01 --move-cost 0.00007 \
  --min-speed 0 --seed 42 --log-every 2000 --no-render

# THE KEY currents result — pricing thrust unmasks the current (fight vs ride):
#   current 80  + move-cost 7e-5 -> flow_align ~ -0.09 (fights upstream)
#   current 150 + move-cost 7e-5 -> flow_align ~ +0.07 (rides) [needed current 300 without move-cost]
./evo_boids --headless 1000000 --name gyre_c80_mc  --current 80  --current-mode gyre \
  --food-patches 6 --food-drift --gene-cost 0.01 --move-cost 0.00007 --min-speed 0 --seed 42 --log-every 2000 --no-render
./evo_boids --headless 1000000 --name gyre_c150_mc --current 150 --current-mode gyre \
  --food-patches 6 --food-drift --gene-cost 0.01 --move-cost 0.00007 --min-speed 0 --seed 42 --log-every 2000 --no-render

# move-cost calibration (current 0): finds the interior cruise speed (~82) without flooring pop
./evo_boids --headless 1000000 --name gyre_c0_mc --current 0 --current-mode gyre \
  --food-patches 6 --food-drift --gene-cost 0.01 --move-cost 0.00007 --min-speed 0 --seed 42 --log-every 2000 --no-render
```

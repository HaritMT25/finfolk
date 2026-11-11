# Architecture and design notes

The detail behind the [README](../README.md)'s overview of how Finfolk works. Moved here from the README; the text is
unchanged except where a statement needed to say whether it describes Classic or the Ocean.

## What it simulates

Every creature has a **genome**: a list of 16–80 genes, where each gene is one weighted connection in a small neural network. A connection runs from one of Classic's 41 sensors (the Ocean has 46) (nearby creatures, food, pheromone, own energy, age, an internal oscillator, …) or one of 12 hidden neurons to a hidden neuron or one of Classic's 12 actions (the Ocean adds depth steering, for 13) (steer, speed up, emit a signal, reproduce, share food, fight, …). The genome fixes the network at birth, and the network never learns during the creature's life.

**Nothing scores the creatures. There is no fitness function and no training loop.** Each creature burns energy every second, and it dies when its energy runs out, when it reaches its maximum age, or when a predator catches it (predators are optional). When two creatures meet, their networks' outputs are summed. The pair then shares food, reproduces, fights, or ignores each other, depending on which option scores highest. Reproduction also needs enough energy in both. The child gets a crossover of the two genomes plus random mutation. So selection is only this: genomes whose behaviour finds food and partners leave copies, and the rest don't.

**What a fish's colour means.** The 3-D Ocean (the landing page) opens on **Appearance**: every fish wears the skin pattern and body shape it inherited from its parents. They are looks only; the simulation never reads them. Its **View → Fish colours** turns the skin to the family or brain colour below, and the fish keep their inherited body shapes. In Classic, each fish is coloured by its **family line** by default: everyone descended from the same starting fish shares one colour, the same one the line has in the dashboards, so you can watch families spread and take over. A line's colour comes from its id, so it stays the same across restarts and checkpoint loads; deep reds are left out so that only predators are red. **Settings → Run → Colour by brain similarity** switches to the genome colour, which the native app always draws. The genome colour is computed from the genome, not assigned to the family. Each connection adds its weight times a fixed amount to red, green and blue (`src/core/genome_color.hpp`; the table is frozen, the same in every version and build). So similar brains get similar colours, and a family drifts in colour as it evolves. Long runs often end blue, and that has a cause. Evolution keeps rediscovering two rules: "share food depending on how full you are" (`FOOD_RESERVES → SHARE`, nearly always with the same sign) and "breed when well fed" (`FOOD_RESERVES → REPRODUCE`). By the luck of the frozen table, both point at blue. Measured over 8 runs of 160,000 steps: the sharing rule was the strongest pull on the colour in 5. Two winning families ended deep blue, one pale blue-grey, and the rest green, teal or maroon. In those two runs the share of blue-dominant fish climbed steadily, to 86–90%. So blue roughly means "this family reads its own energy before breeding and sharing".

The question the project asks is which environmental pressures (food scarcity, a cost on movement, ocean currents, predators) are enough to produce a collective behaviour such as schooling.

Optional mechanisms, all off by default: predators that eat, breed and starve (with an optional floor and cap on their numbers, and heritable speed and budding threshold); food in patches; ocean currents; heritable body size and elongation; a genetic-distance limit on who can pair with whom.

## Architecture

```
src/core/      the simulation: header-only, no rendering, no OS calls (evo_core)
src/ocean/     the Ocean world: flow, appearance, diagnostic body plans (header-only too)
src/render/    SFML window frontend (native only)
src/app/       native entry point: headless runs, CLI flags, CSV logging
wasm/          C API for JavaScript, Emscripten builds, benchmarks, parity tests
web/           browser frontend: renderers, module loader, dashboards, Turbo workers
tests/         core_tests, predator_smoke, core_bench, Ocean tests and baselines (no SFML needed)
```

- **Spatial index.** Creatures and food go into uniform grids (`spatial_grid.hpp`), with cell size equal to the perception radius. Each grid is one array sorted by cell, rebuilt every step without reallocating, and a neighbour query scans each row of the cells overlapping its radius as one contiguous run.
- **What doesn't depend on geometry.** Three headers hold the parts a world with a different shape could reuse unchanged:
  - `agent_core.hpp`: a creature without its position: identity, energy, timers, body parameters, genome and network. `Creature` adds position, heading and the body trail.
  - `kernel.hpp`: the steps that need no position: the child's genome, metabolism, the death test, the own-state sensors, and the interaction between two creatures (the vote, sharing, fighting, the pairing gate, what a child inherits).
  - `world_common.hpp`: the config, birth and death counters, the death and birth logs, ids and the profiler. `World` adds the grids, food, currents, pheromones and predators.
- **One step.**
  - The per-creature phase (sense, run the network, move) only writes to the creature being updated, so it runs in parallel.
  - Eating, interactions, births and deaths change shared state, so they run on one thread.
- **Parallelism.**
  - Native: OpenMP.
  - Browser: the same loop runs on a small thread pool (`thread_pool.hpp`) over Emscripten pthreads.
  - Both threaded paths give each thread its own random generator, so a threaded run cannot be replayed from its seed.
- **Determinism.**
  - The single-threaded build reproduces a run exactly from its seed.
  - Floating point is compiled with `-ffp-contract=off` and never `-ffast-math`, and the core uses its own copies of the math functions it needs.
  - With that, the native single-threaded build and the single-threaded WebAssembly module write byte-identical checkpoints for the same seed and step count. `wasm/parity.sh` checks this across 28 seed/config cases. The Ocean has its own parity matrix (`wasm/ocean_parity.sh`), which compares state fingerprints instead.
  - Vectorised code changes nothing: each lane does the same IEEE operations. The neural network's `tanh` runs as `evomath::tanhfArray`, which computes every case of musl's `tanhf` and selects the answer rather than branching to it, so the compiler can vectorise it; it matches `tanhf` on all 2^32 inputs.
- **Browser module.**
  - JavaScript calls a small C API (`wasm/evo_wasm.cpp`): `evo_init`, `evo_step(n)`, `evo_reset`, `evo_set_param`, `evo_sync`, plus getters.
  - The getters return pointers into the wasm heap, and the renderer reads them as typed-array views every frame. No copies, no JSON.
  - Classic's checkpoints are JSON and load in both the native build and the browser. The Ocean saves its setup as JSON and its worlds as a separate, engine-checked file format (see the README).
- **Two browser builds.**
  - `evo_boids_mt` uses pthreads. It needs `SharedArrayBuffer`, which browsers allow only on cross-origin-isolated pages (COOP `same-origin` + COEP `require-corp`).
  - `evo_boids` is single-threaded.
  - `web/loader.js` checks `self.crossOriginIsolated` and picks one. Inside an iframe on a page without those headers, it always gets the single-threaded build.
- **Drawing.** With WebGL2, the background, food, fish and predators are drawn with one instanced draw call per kind (`web/gl_renderer.js`). The result is copied onto a 2D canvas, which draws the HUD and the neural inspector on top, the way the native SFML window does. Without WebGL2, everything is drawn with canvas 2D, at one fill per body segment. The controls around the world (a live readout, a playback dock, the settings, Turbo) are HTML, outside the canvas. Classic's **tank view**, the default, draws the same 2-D world as a tank in perspective instead (see [the browser frontend notes](web_frontend.md)); the flat view is the native window's picture. Neither is the 3-D Ocean, a separate world with depth (see [the browser frontend notes](web_frontend.md)).
- **Frame budget (Classic).** The Ocean's own Hold 60 fps lowers the speed and then the drawing detail, and never changes the world. In Classic, when a frame takes too long, the page first lowers the simulation speed (in the tank view, it first draws the tank with less detail). Then it removes creatures uniformly at random and caps births, so the agent count drops instead of the frame rate. A message says when this happens, and the readout keeps an orange dot for the rest of the run, because a run changed this way can no longer be replayed from its seed. It can be switched off ("hold 60 fps").

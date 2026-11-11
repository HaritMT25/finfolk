# The browser frontend: reference notes

The detail behind the [README](../README.md)'s overview of the two web pages: their page options and keyboard,
browser support, the touch layout, Classic's tank view and fish shapes, Randomize and the first-visit guide, and the
dashboards. Moved here from the README; the text is unchanged except where a statement needed to say whether it
describes Classic or the Ocean.

## Classic's page options, browser requirements and tested browsers

`web/` keeps its own names, Classic at `index.html`; the deploy build gives the site its own ("The site", below, which also lists the Ocean's page options).

Classic's page options:

| Option | Effect |
|---|---|
| `?threads=0` | forces the single-threaded module |
| `?nthreads=N` | sets the thread count |
| `?bench` | runs the frame-rate benchmark below |
| `?gl=0` | forces canvas 2D drawing instead of WebGL2 |
| `?guide=0` / `?guide=1` | never start the first-visit Turbo card and tour / always start the tour on load |
| `?intro=1` | always show the first-visit Turbo card |
| `?view=3d` / `?view=flat` | starts in the tank view / the flat view (otherwise the visitor's last choice; the tank the first time, and the flat view under `?bench`, so its numbers compare with the tables in [`benchmarks.md`](benchmarks.md)) |
| `?fish=1` / `?fish=0` | draws the flat view's fish as fish shapes / as circles (otherwise remembered; circles the first time) |
| `?colour=brain` / `?colour=family` | colours the fish by brain similarity / by family line (otherwise the visitor's last choice, family when that was the Ocean's appearance; family the first time) |

Keyboard: <kbd>Space</kbd> pause · <kbd>↑</kbd> <kbd>↓</kbd> speed · <kbd>R</kbd> a fresh world · <kbd>Esc</kbd> closes what is open (the settings, the live numbers, then the selected fish). Click a fish to inspect it, empty water to let it go. In the tank view also <kbd>F</kbd> follow the selected fish · <kbd>C</kbd> fit the view; drag to pan, scroll to zoom (towards the pointer), right-drag to tilt and turn.

Browser requirements:
- **WebAssembly with SIMD**: Chrome 91+, Firefox 89+, Safari 16.4+. Both modules are built with it, so the neural network's activations are computed four at a time. Without it the page says so instead of starting.
- **WebGL2**: optional for Classic (without it the fish are drawn with canvas 2D, which is slower at high counts). The Ocean needs it: when it cannot start WebGL2 it says so and offers Classic.
- **Cross-origin isolation** for the threaded module: Chrome 92+, Firefox 79+ and Safari 15.2+ support it. Anywhere else, the page runs the single-threaded module.

Tested on Windows 11 in:
- Chrome 155
- Playwright's Firefox 155 build
- Playwright's WebKit 26.6 build, which is Safari's engine but not Safari itself

Checks run in each:
- the threaded module and WebGL2 drawing on the isolated page
- `?threads=0` and `?gl=0`
- the single-threaded fallback without isolation headers
- running inside a cross-origin iframe
- Turbo on and off
- checkpoint download

Safari on macOS/iOS has not been tested.

## The site: the 3-D Ocean and 2-D Classic

Two worlds, each on its own page with the same controls:

| URL | page | what it is |
|---|---|---|
| `/` | `web/ocean.html` | **3-D Ocean**, the landing page: the fish sense depth and steer in it, in a deep tank. Its own engine (`web/evo_ocean.*`), single-threaded, reproducible from its seed |
| `/classic.html` | `web/index.html` | **2-D Classic**: the original flat world, the one the native app runs, threaded where the page is cross-origin isolated; drawn as a tank in perspective (the default) or flat |
| `/ocean.html` | `web/ocean.html` | the same page as `/`, for links from before the Ocean moved to the root |

A **3-D | 2-D** switch beside the live readout, on both pages, moves between them ("3-D Ocean | 2-D Classic", or "3-D | 2-D" under 760 px). The current world is highlighted and is not a link, so pressing it never restarts the run; each world runs on its own, so switching starts the other one fresh. Classic's tank and flat views stay a setting of Classic (Settings → Run → Tank view): both are pictures of the 2-D world. Both tours point at the switch.

**Links from before.** Until 2026-10-28 the root was Classic. A query on `/` (or `/ocean.html`) with one of the keys only Classic reads (`view`, `fish`, `gl`, `bench`, `threads`, `nthreads`) and none of the keys only the Ocean reads (`seed`, `pop`, `depth`, `w`, `h`, `cfg`, `speed`, `e1`, `mock`, `walls`) goes to `/classic.html` with its query and hash, before the Ocean starts (a script at the top of `web/ocean.html`). So `/?view=flat`, `/?threads=0` and `/?bench` open Classic as they did, and the Ocean's own links, which carry `?seed=` from the first restart on, stay. Keys both pages read the same way (`colour`, `guide`, `intro`) decide nothing: `/?guide=0` is the Ocean. Classic reads no `seed` and no `cfg`, so no key means one thing on one page and another on the other. A query with keys of both, which neither page writes, stays on the Ocean.

**Embedded.** Both pages run inside an iframe on a page without COOP/COEP (the portfolio site's demo window frames `/` at about 890×453): Classic then runs single-threaded, the Ocean as always. Windows 560 px tall or less, such as that one, get each page's compact layout; there the Ocean's fish card drops its bars and sizes the brain to fit between the top bar and the dock.

The Ocean's page options (`web/ocean.js` lists them):

| Option | Effect |
|---|---|
| `?seed=N` `&pop=N` `&depth=D` | the world's seed, starting population and depth; a restart writes them back, so the address replays the world |
| `?cfg={...}` | settings as JSON (the config keys the settings show) |
| `?w=` `&h=` | the tank's size (1920×1080, or on its side on a portrait screen; any whole number from 100 to 100000, as the settings' Tank width / length) |
| `?walls=1` / `0` | glass walls (fish turn back at the glass) or wrapping sides (a fish swimming out of one comes back through the opposite one). A bare address starts with glass walls; a link from before walls existed (no `walls=`) keeps wrapping; every restart writes it |
| `?speed=N` | steps per frame |
| `?e1=1` | the E1 physics preset, under `?cfg` |
| `?colour=appearance` / `family` / `brain` | each fish's inherited skin pattern / its family line's colour / its brain colour, always on its inherited body shape (otherwise the visitor's last choice; appearance the first time). The choice is shared with Classic, which shows family for appearance |
| `?guide=`, `?intro=1` | as Classic's, above |

A value outside the engine's limits makes the page refuse the link with the reason (and offer the default settings) rather than quietly changing it.

**A bigger tank.** Settings → World holds the tank's size and its sides, and **Start the Big tank**: 3840 × 2160 × 240 (four times the standard volume) with 2,000 fish, glass walls, four times the food, the tuned water and a 2,000-fish birth cap. Over 100,000 steps (3 seeds, and a fourth from 500 founders) it never reaches its reseed floor of 200: after one dip to 590–740 fish around step 8,000, when the founders (all born together, and capped at 2,000) reach their 120 s lifespan, it climbs back and stays near 2,000 (at least 1,880 from step 20,000 on). The cap is what holds it there: the same food without a cap carries about 2,300 fish on average, but in boom-and-bust cycles of about 25,000 steps between roughly 800 and 4,200 fish, nine deaths in ten by starvation (2 seeds, 100,000 steps). Randomize keeps the tank's size and sides and scales its recipe to the volume.

## Phones and touch screens

Every screen gets the same controls around the world: the live readout at the top left (fish, generation, frame rate; tap it for the rest; a phone narrower than 480 px leaves the frame rate to that panel) with the 3-D | 2-D switch beside it, the dashboards and settings buttons at the top right, and a playback dock at the bottom (pause, speed and Turbo, plus Randomize in Classic; the Ocean's dock also has the flashlight, View and fit-the-tank buttons, and its Setup button sits at the top right). On a desktop with a mouse they sit around the world, not over it, and the flat view draws the world exactly as before: the canvas is pixel-identical to the previous page's for a fixed checkpoint, HUD and inspector included. Small and touch screens, and windows 560 px tall or less (such as an embed), differ:

- **World shape.** In portrait, or on any touch screen, a start or restart creates a world with the area of 1920×1080 but the shape of the screen, so it fills the screen instead of a 16:9 strip. Food density and crowding stay the same. Rotating the device keeps the running world, and a "fit to screen" button restarts it with a fitted one. A checkpoint keeps its own size, and `?bench` always uses 1920×1080. The controls float over the world here.
- **The selected fish.** On screens 700 px wide or less, windows 560 px tall or less, and touch screens, the inspector is a card instead of a canvas panel: energy (with the breeding threshold marked), age and speed, and the live network below, where tapping a node names it. The card sits at the bottom of a phone (on the right of a wider screen) and moves to the other side when the fish swims under it. The on-canvas HUD is left out there; the readout carries the essentials.
- **Settings** open as a bottom sheet you can drag down to close; on screens 960 px wide or more they sit beside the world instead.
- **Touch.** A tap selects the nearest fish within about 24 CSS px. Tapping a setting's name shows its explanation. Inputs use 16 px text, so iOS does not zoom the page on focus, and buttons and rows are at least 44 px tall.
- **Load.** Touch devices start with 200 creatures (single-threaded) or 400 (threaded), on at most 4 threads; `?nthreads=N` overrides the thread count. The threaded module still pre-spawns min(cores, 8) − 1 workers. The frame-budget governor works as everywhere else.

So far this is measured in emulation only: Playwright's iPhone 13 profile in WebKit 26.6 and its Pixel 7 profile in Chrome 155, portrait and landscape. The world covers 99.7–99.8% of the screen in all four cases, of which the top bar and the dock float over about 11% (Pixel 7, portrait); the fish card with its network open covers 43% (Pixel 7) and 49% (iPhone 13). No real phone has been tested, so frame rate, battery use, memory, and whether the threaded module starts on iOS are unmeasured.

## Classic's tank view (the default)

Classic draws its 2-D world as a shallow tank seen at an angle, made with three.js (`web/scene3d.js`, by techy-Nik). It changes nothing in the simulation, only the picture; the world with real depth is the 3-D Ocean, a different page. A first visit gets the tank; the Tank view switch in the settings' Run tab (or `?view=flat`) turns it off, and the page remembers the choice. The flat view shows the world as the simulation sees it, as the native app does; the tank is for looks, and takes liberties:

- **What is drawn from the simulation:** every fish's six spine points (bent through with a spline), colour (its family line, or its genome with the brain switch on) and body size; food positions; predator positions and whether they are hunting or digesting; the current's flow grid.
- **What is added for looks:** a tail beat, a fixed swim height per fish (±4 world units), lighting, shading and fog (a fish's back is drawn darker than its colour, distant fish fade toward the water), shadows, caustic light, drifting specks of "marine snow" that are not food, and each predator's recent path used as its spine.
- **What the perspective changes:** distant fish look smaller and distances aren't uniform across the screen. The tank has walls, but the world still wraps, so fish swim through one wall and come back at the opposite one.

The selected fish is shown as the card on every screen in the tank view (there is no canvas inspector), and the camera pans, zooms, tilts and follows a fish. three.js ships as a trimmed bundle, `web/vendor/three.bundle.min.js` (561 KB minified; about 115 KB brotli by #7's measurement), loaded with the tank, so a first visit downloads it; the flat view never does. `tools/three_bundle/build.sh` rebuilds it, and the rebuilt file is byte-identical to the committed one (three 0.186.1, esbuild 0.28.2). Without WebGL2 the switch says so and stays off.

Cost, as measured in #7 on the benchmark machine ([`benchmarks.md`](benchmarks.md)) (Chrome with the Iris Xe GPU, threaded × 8, 1440×900): the tank holds a stable 60 fps up to 10,000 agents (52.2 fps at 12,000), against 12,000 for the flat view, and spends about 1.2 ms per frame drawing 2,000 agents against 0.8 ms. Re-measured on the same laptop in a windowed Chrome 155 (AC power, 2 rounds alternating the views): the flat view held the display's rate up to 12,000 agents and the tank up to 10,000, as in #7, and drawing took 0.70 against 1.06–1.11 ms at 2,000 and 0.87–0.88 against 2.18–2.19 ms at 8,000. Headless (2026-10-20, 2 rounds): drawing took 0.79–0.80 ms flat against 1.10–1.11 ms in the tank at 2,000 agents, 1.41–1.44 against 2.75–2.92 ms at 8,000, and 1.51–1.54 against 2.42–2.74 ms at 12,000. Both held a stable 60 fps up to 6,000 there, because on that run the simulation step (12.5–13 ms at 8,000) set the limit, not the drawing. In a windowed Firefox 155 (Playwright's build), drawing took 1.26–2.34 ms flat against 0.8–2.12 ms in the tank, at every count up to 12,000 (see [`benchmarks.md`](benchmarks.md)). That cost is only paid with the tank on; the governor's first step there is to draw it with less detail.

## Fish shapes (opt-in)

A second switch in the Run tab (or `?fish=1`) draws each fish in the flat view as one body instead of six circles. The shape is a skin over the same skeleton, so it shows body size and elongation the way the circles do:

- **Length** is the spine the core keeps, six points `4 × bodySize × bodyElong` apart at most (`Creature::updateBody`), bent through with a Catmull-Rom curve.
- **Width:** the half-width at each spine point is that point's circle radius, `RADII[i] × bodyScale(bodySize)` with the same floor, and runs linearly between them. The head is the head circle.
- **The tail fin** is the one addition: 6 world px long and 9 across (tip to tip) at body scale 1, scaled by the same `bodyScale`, at 55% opacity.
- **At the world's edge** a fish is drawn as its six circles for a moment. The core wraps a creature's position and then pulls its trail by plain, unwrapped distance (`World::update`, `Creature::updateBody`), so right after crossing an edge the trail lies ahead of the head, on the new side, until the head swims through it. Circles show that as overlapping dots; a fish shape would swim backwards. So, until the fish has travelled 260 px past the crossing, while any segment of its trail points along its motion, it is drawn as circles, exactly as with the switch off. A test that replays the core's trail rule over 8 crossings (edges, a corner, slow and fast, short and long fish, up to 50 steps a frame) finds every backwards frame drawn as circles and no other, and a fish circling far from the edges never drawn as circles.
- **Colour:** body and head are drawn opaque in the fish's colour; the circles fade toward the tail instead.
- **Drawing:** WebGL2 only. Every fish is one instanced draw of a 55-vertex template, bent in the vertex shader, in the same creature order. The canvas-2D fallback (no WebGL2, or `?gl=0`) keeps the circles, and the switch says so: in Chrome, canvas 2D filled the outlines at less than half the frame rate of circles (250 bent fish in a test page: 20 against 45 fps in a windowed Chrome 155, 22 against 60 headless; Firefox filled both at about 60), because each filled polygon costs far more there than an arc. Splitting the outline into convex pieces made it slower, not faster. The native app still draws circles.

**Measured faithfulness.** A test world holds 15 isolated, straight fish: body size 0.5, 0.75, 1, 1.5 and 2, each at elongation 0.5, 1 and 2. Differencing it against the same world without them gives each fish's pixels. With fish shapes, each fish is exactly as wide as its circles, and its length is within 1 px of the geometry (five spine segments, plus the head radius, plus the fin), in all 15 cases. That holds in Chrome 155, Playwright's WebKit build (installed 2026-10-20, Playwright 1.63) and Playwright's Firefox 155. As with circles, body sizes 1.5 and 2 draw the same width, because `bodyScale` levels off at 1.4×; their lengths still differ.

**Across browsers** (same machine, same GPU through ANGLE): the WebGL path's fish pixels are identical in all three engines, circles and fish shapes alike. The canvas-2D circles differ only in anti-aliasing (WebKit by at most 4/255; Firefox on 0.06% of fish pixels), and agree with the WebGL circles on 99.9% or more of fish pixels in each browser.

**Cost** (`?bench`, the laptop's Iris Xe, threaded × 8; circles and fish shapes alternated in one browser). Chrome 155, two headless sets of 3 rounds each and one windowed set of 2:

| set | draw at 2,000: circles | fish shapes | draw at 8,000: circles | fish shapes | stable 60 fps up to |
|---|---:|---:|---:|---:|---|
| 2026-10-20 | 0.89–1.24 ms | 1.24–1.34 ms | 2.75–3.14 ms | 3.38–3.79 ms | 3,000–4,000 / 3,000 |
| 2026-10-22, on battery | 1.03–1.06 ms | 1.22–1.29 ms | 2.57–2.82 ms | 3.23–3.46 ms | 4,000 / 3,000–4,000 |
| 2026-10-22, windowed, AC (2 rounds) | 0.69–0.71 ms | 0.90–0.92 ms | 0.86–0.87 ms | 1.25–1.26 ms | 10,000–12,000 / 10,000–12,000 |

So fish shapes add about 0.2 ms of drawing at 2,000 agents, and 0.4 ms (windowed) to 0.75 ms (headless) at 8,000. In the windowed runs, where the display's 56.6 Hz sets the pace, circles and fish shapes each held it up to 10,000 agents in one round and 12,000 in the other, so the stable limit didn't separate them. In both headless sets the step took 6–7.5 ms at 2,000 agents, against 3.9 ms in the flat-vs-tank rounds on AC power, so the step, not the drawing, set the stable-60 limit. A control run showed the fish branch with the switch off drawing exactly like the branch before it (1.075 vs 1.06 ms at 2,000). In headless Firefox 155 (2 rounds) both drew in 17–19 ms at 2,000 agents, which is headless Firefox's fixed copy cost (see [`benchmarks.md`](benchmarks.md)), and fish shapes added nothing measurable on top.

## Randomize and the first-visit guide

**Randomize** (Classic: the dice in the dock, or the top of the settings' Run tab; the Ocean's equivalent is the **Surprise me** card in Setup → Run) draws a whole setup, restarts, and lists what it picked. Every value also lands in the settings, so you can tweak it and press Restart.

Each value is drawn from a range. The range comes from the experiments (`docs/evo_boids_flags.md`, the research log) where one exists, and otherwise from the "try:" suggestions in the settings' explanations. `web/randomizer.js` lists every range next to its source. Knobs that only work together are drawn together:
- **Currents** come with patchy, drifting food and a thrust cost. Fish only fight or ride a current when food is patchy and swimming costs energy.
- **Predators** come in the experiments' arena: abundant uniform food and a population cap, so predation, not starvation, does the selecting.
- **The predator economy's meal** is set relative to what a hunt costs, using the break-even formula from the flags doc: 1.2–1.4× break-even, enough for the hunters to breed. It comes with a **predator cap** of 8 × the digesting time (24–40) and a **floor** of 2, because without the cap a breeding economy booms and crashes (below).
- **The match gate** only comes with its soft ramp; hard, it collapses the population below a threshold of ~16.

Measured headless: the single-threaded module under Node, 20,000–30,000 steps per setup (about 5.5–8 simulated minutes). A setup counts as healthy when the fish never sink to the reseed floor and, with predators, the predators are still alive at the end.

1. **First check, 48 random setups.** Predators were the weak spot. Drawing the meal on its own (12–16, the docs' values) left 9 of 13 economy setups unhealthy: they boomed then crashed, or the predators starved. One setup with 4 scripted hunters also collapsed. Every setup without predators was healthy (34/34).
2. **Two sweeps, 4 setups per value, 30,000 steps:**

   | meal ÷ break-even | result |
   |---|---|
   | 0.9 | predators starve (4/4) |
   | 1.0, 1.1 | both sides alive (8/8) |
   | 1.2 | boom, then crash (predators gone in 2/4; prey crashed in 1) |
   | 1.3 | prey collapse (3/4) |

   Scripted hunters in the arena: 3, 4 and 5 all healthy (12/12).
3. **Final check of the shipped ranges, 48 fresh setups:** all healthy. Predators were alive in all 28 predator worlds, with 3–70 economy predators at the end.
4. **Re-checked in v0.26.0, with the predator cap.** Native runs, 6 seeds × 30,000 steps per setting (`docs/evo_boids_flags.md`, predator floor and ceiling section) showed that at 1.0–1.1× break-even the predators never bud: "both sides alive" in step 2 was predators fading out. A meal that breeds them, 1.2× and up, booms and crashes unless their number is capped. A capped hunter catches about once per digesting time, so the cap sets the catch rate, and both sides persist while it stays under the fish's birth rate. Randomize now draws 1.2–1.4× with a cap of 8 × the digesting time and a floor of 2. **21 fresh economy setups, 30,000 steps:** both sides alive in 21/21, the fish never at their floor, the predators at their cap at the end in all 21. In two of them, the fish were held well below their own cap (a median of 178 of 600; dips to 213 of 400).

Uncapped rich-food setups reached ~2,400 fish headless; in the browser, the frame-budget governor sizes that to the device.

**Turbo, first.** A first visit opens with one card that points at the Turbo button and says what it does: evolution is slow to watch, and Turbo runs the simulation headless, many times faster, and keeps going in a background tab. **Try Turbo** starts it; **Cancel** (or Escape) closes the card, and then the tour below offers itself. The card is remembered in `localStorage` (`?intro=1` shows it again).

**First-visit guide.** After that card, a first visit is offered a one-minute spotlight tour:
- what you're looking at, a fish's brain, the live readout, and the 3-D | 2-D switch between the two worlds
- the keyboard (with a mouse only)
- the playback dock (including what Turbo's "headless" means), the dashboards, the settings, Randomize, your own settings, and checkpoints

**Settings.** They are grouped in tabs: Run (Randomize, hold 60 fps, save and load), World, Food, Life, Predators and Ocean. Each setting shows its config key under its name, and a dot on a tab means something in it differs from the default. On screens 960 px wide or more, the open settings sit beside the world rather than over it, so a change can be watched. Settings that only matter while another one is on, such as patch radius without food patches or eddy count without a current, are dimmed with the reason. Changes other than the ones marked *live* turn the Restart button into **Restart to apply**. That button is pinned to the bottom edge of the settings, so it stays in reach from any tab.

The tour's text adapts to touch screens. The page stays usable during the tour. "Tour" in the settings replays it, and it's remembered in `localStorage`; `?guide=0` keeps it and the Turbo card from starting on their own, `?guide=1` always starts it.

## Dashboards (Classic)

The chart button beside the settings button opens charts of the running world. This section describes Classic's dashboards. The Ocean has its own tabs (Population, Depth, Family lines, Bodies, Brains), records into a bounded history of its own (1,200 rows, halving its sampling when full), and exports CSV only. Each chart says in one sentence what to look for, and charts that need a feature (predators, a current, the body model) say how to turn it on.

| tab | charts |
|---|---|
| Population | fish and food; predators (and how many a predator floor has put back); births and deaths per second; causes of death; the boom-and-bust loop as a phase plot (fish vs food, and fish vs predators) |
| Evolution | generations; genetic diversity; genome length, swim speed, body size and age as median with 50% / 80% bands; the hunters' inherited speed and budding threshold (with predator inheritance on) |
| Family lines | Muller plot of the founder lines (`lineageId`), each in its fish's family colour, the lines still alive, breeding groups (`reproComponents`) |
| Family tree | up to 300 living fish traced back through each one's first parent, with their most recent common ancestor |
| Similarity | 150 fish sampled evenly: the match-distance matrix ordered by a UPGMA tree, a classical-MDS genome map, the distance histogram with the breeding gate marked |
| Brains | which senses reach which actions (directly or through hidden neurons) across the population; each sense's use over time |
| Behaviour | schooling alignment, neighbours in sight, riding the current, fleeing predators |

**Where the numbers come from.** A recorder in the wasm shim (`wasm/evo_wasm.cpp`, "Dashboard recorder") reads the world inside the step loop. Every 60 frames (about one simulated second) it takes a sample row: `computeStats` plus generations, quantiles, family-line counts and sensor use. It also pairs each newborn's id with its two sources. World assigns newborn ids consecutively right after the step, in the order their pairs enter `reproWindow_`, so this needs no change to `src/core`. The recorder is read-only: no random draws, no writes the simulation reads. Checkpoints from a recording build match `main`'s for the same runs, through odd chunk sizes, a governor cull and a save/load round trip. One sample costs about 1% of the step time it covers (3 ms at 2,000 fish, 10 ms at 6,000, single-threaded). Turbo records in its worker and hands the rows back, so the charts carry on through it.

**The family tree** follows one parent per fish: the first source, whose family line a child carries, as mitochondrial DNA does in people. With both parents, every past fish with living descendants would soon be an ancestor of everyone, and the tree would grow without bound. Following one parent, a dead fish with no living descendants is dropped, and one with a single surviving branch is spliced out. That keeps the tree to about twice the live set (measured: 1.2–1.34×).

**Storage.** Everything stays in this browser tab, in memory; nothing is uploaded. At 4,096 rows the history drops every other row and samples half as often, so a session of any length fits in about 5 MB and covers the whole run evenly. Restart or loading a checkpoint file starts a new recording. **⤓ CSV** saves every row; **⤓ Tree** saves the family tree as Newick, for tree viewers such as FigTree or iTOL.

**Cost while open.** Charts redraw at most twice a second, only while the dashboard is open, and the world is not drawn behind it. The similarity tab refreshes every 10 s, with one ~80 ms computation; the other tabs measured no long tasks.

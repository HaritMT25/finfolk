# UI parity: one interface for both worlds

Classic (`web/index.html`) and the Ocean (`web/ocean.html`) grew the same interface twice. The UI parity plan
(`ui_parity_plan_codex.md`, kept with the owner's decisions outside the repository) lists every difference between them (U01 to U62)
and the pull requests that remove them (P01 to P21). The target is one shared design with explicit capabilities for each world: what
both worlds do lives in small shared modules, and what only one world can do (depth, waves, Classic's flat views) stays its own.
This file describes the shared pieces as they land and the browser harness that pictures both worlds side by side. Display only:
no simulation module, hash or baseline is involved.

## The shared focus primitives: `web/ui_common.js` (`window.EvoUI`)

Both pages load `ui_common.js` (and `ui_common.css`) before their own scripts; `wasm/build_site.sh` publishes both and asserts the
rewrite of each tag. These are the rules the Ocean page had grown for keyboard users (P02: the plan's U37 and the reusable part of
U58), now one contract:

| primitive | rule |
|---|---|
| `keyboardFocused(n)` | `n` has the focus and its ring shows (`:focus-visible`: the keyboard put it there) |
| `pressedByKeyboard(n, e)` | the ring showing, or a click no pointer made (Enter / Space on a button give `detail` 0) |
| `pointerBlur(n)` | after a press: a pointer's lets the focus go (Space pauses again, letters are the page's); the keyboard's keeps it |
| `typingIn(t)` | a focused field takes every key: text inputs, selects, text areas, editable text (not a switch, slider or button) |
| `ownsKey(t, key)` | the keys a focused control acts on itself: a button's Space / Enter, a switch's Space, a link's Enter, a slider's arrows, Home, End, Page Up / Down, a tab's arrows, Home and End. Every other key stays the page's |
| `tabIndexFor(key, i, n)` | Left / Right round the ends, Home, End; -1 for any other key |
| `tabs(list, o)` | one tablist (the WAI-ARIA tabs pattern): roving tabindex (Tab lands on the selected tab), the keys of `tabIndexFor` with the focus going with the selection, modified arrows left to the browser, a press that selects (a pointer's lets the focus go, the keyboard's keeps it) |
| `returnPoint()` | where the focus goes back when something the keyboard opened closes: the opener is remembered only when the keyboard opened it, and the focus returns only when the keyboard closes it |

Where they are used:

- **Every tablist on both pages** goes through `EvoUI.tabs`: the dashboards' (`dashboard.js`, `ocean_dash.js`) and the setup sheets'
  (`renderer.js`, `ocean.js`). Classic's dashboards had no keys and blurred on every press (U37); both setup sheets had Left / Right
  only and kept a pointer's focus. All four now behave as the Ocean's dashboards did.
- **The Ocean page's** View / Help popovers keep their opener in a `returnPoint`, its buttons that may ask a question (`askBtn`, From a
  file) use `pressedByKeyboard`, its key router uses `typingIn` / `ownsKey`. Same behaviour, now shared code.
- `ui_common.css`: a tab's focus ring is drawn just inside its edge (`.ui-tablist [role="tab"]:focus-visible`), because the tablists
  scroll sideways and clip the page's ring, drawn 2 px outside.

Not shared yet, on purpose: which keys are shortcuts and what they do (Classic's router still ignores every key while a button or field
has the focus; the common command vocabulary is P05), and Classic's popovers, sheets and confirmations (P04).

Tests: `node tests/ui_common_tests.cjs` (CI's "web ui" job): the predicates, the tablist on a small DOM (roving focus, wrapping,
Home / End, modified keys, the pointer / keyboard press), the return point, both dashboards' tabs with the same assertions, and both
pages' script order. `tests/ocean_turbo_handoff.js` runs the Ocean page with `ui_common.js` as `ocean.html` loads it (its key router,
popovers and tab keys during the tour).

## The paired browser harness: `tests/ui_parity_browser.mjs`

Every UI parity PR pictures both worlds before and after, in the same state. The harness does that: one case at a time, each world in a
fresh headless Brave with a temporary profile (clean storage), under the machine-wide browser lock (`tools/ocean_render_perf/lock.mjs`:
it waits, never breaks it), full-page screenshots that include the DOM chrome. It is a local tool: CI has no browser.

### Running it

Serve the repository root with the production isolation headers, then run the harness from Windows node (Playwright and Brave are
Windows-side; `PLAYWRIGHT` and `BRAVE_EXE` override their paths):

```bash
python3 wasm/serve.py . 8262                     # in WSL: the root, so Classic finds ../img/rocks.jpg
```
```powershell
node tests\ui_parity_browser.mjs --base http://localhost:8262 --out OUT\after --sets S0,S2 --name "builder-ui-pNN"
node tests\ui_parity_browser.mjs --list                                   # the cases
node tests\ui_parity_browser.mjs --base http://localhost:8262 --out OUT --cases s2_tabs --worlds classic
```

- `--layout source` (default): Classic is `/web/index.html`, the Ocean `/web/ocean.html`. `--layout site`: `--base` serves a built
  site (`SITE_DIR=/x bash wasm/build_site.sh`, then `python3 wasm/serve.py /x PORT`): Classic is `/classic.html`, the Ocean `/`.
  The routes are explicit: never `/index.html` for Classic (on the site that is the Ocean).
- `--smoke`: each route loaded as a visitor would, its ready state, no console error / warning, page error, failed request or HTTP
  error; on the site layout also the Ocean's old name `/ocean.html`.
- **Before / after**: serve a copy of main (`git archive origin/main web img | tar -x -C DIR`, then `serve.py DIR PORT`) and the
  branch on another port, run the same harness against each, then
  `node tests\ui_parity_browser.mjs --compare OUT\before OUT\after --out OUT\diff` (pixel counts, the largest difference, the box of
  the differences, a x16 difference picture for each picture that differs).
- Memory: one browser at a time (the lock already enforces it), closed after each case and world.

### The state

The plan's capture rules, so that any commit gives the same picture:

- **The world**: seed 42 and 300 founders on both pages. Classic ignores setup URL parameters, so the harness uses its real form
  (`#seed`, `#population`) and its Restart; the Ocean takes them from its link (`seed=42&pop=300`). Classic runs its single-threaded
  module (`?threads=0`: the reproducible one); neither runs the tour (`?guide=0&intro=0`). The harness checks tick 0, 300 fish and
  (Ocean) seed 42 before a case starts.
- **The tick**: the pages' animation frames are held from the start, so the new world waits at tick 0. A `run` step lets the page's
  own frame loop go at speed 1 (one step a frame) and, right after the frame that reaches the tick (600), presses the page's own Pause
  button (`then: pause`) or holds the frames there (`then: freeze`: the live UI, still at that tick). The world is never stepped from
  outside the page. Between steps the frames stay held; `settle` (and each step that needs the page to draw) lets an exact number
  of frames run, so every run of a case draws the same frames (the live numbers' half-second refresh included).
- **The clock**: `performance.now()` and the frames' timestamps advance exactly 1/60 s per animation frame. The frame rate reads 60,
  no governor (Hold 60 fps, Classic's detail and cap) ever acts, and camera eases end the same way on every run.
- **Animation time**: each scene's `render` gets a fixed `animT` (both scenes' `create()` are wrapped as they register, as
  `tools/ocean_render_perf/shots.mjs` freezes the Ocean's).
- **Visual randomness**: `Math.random` is a seeded xorshift32 (snow, streaks).
- **The picture**: fonts loaded, CSS animations and transitions finished (`animations: "disabled"`), the caret hidden, the 9-second
  "click a fish" hint and every toast gone (a shot's `"toasts": "keep"` keeps them); locale en-US, timezone UTC, 1440 x 900 at DPR 1
  unless the case says otherwise.

Screenshots establish appearance and access. Numerical claims (counts, ticks, identity) belong in node tests.

### Cases: `tests/fixtures/ui_parity_cases.json`

A case has an `id`, its screenshot `set` (S0 to S9, the plan's), a `title`, its `worlds`, an optional `query` (one string, or
`{classic, ocean}`) and `steps`. A step with `"world"` runs on that world only; a `"sel"` is a selector or `{classic, ocean}`.

| step | what it does |
|---|---|
| `run {tick, then}` | the frame loop to the tick, then `pause` (the page's Pause) or `freeze` (frames held: the live UI) |
| `pause` | the page's Pause pressed if it runs, then `settle` |
| `release` / `freeze` | the frames let go with no count (not reproducible: not before a shot) / held |
| `settle {frames}` | exactly that many frames (default 45), then held |
| `select` | a fish selected through the page: Classic's `EvoApp.inspectSomeFish()` (nearest (0.4 W, 0.45 H)), the Ocean's `EvoOcean.select` of the fish nearest the same point |
| `click {sel}` | a real pointer click at the element (no focus ring) |
| `press {sel}` | `element.click()`: a click no pointer made (`detail` 0) |
| `key {key, times}` | a key where the focus is |
| `tabTo {sel, max}` | Tab pressed until the focus is on the element: the keyboard's way there (its ring shows) |
| `focus {sel}` / `blur` | `element.focus()` / the focused element's `blur()` |
| `wait {ms}` | real time (a CSS transition) |
| `shot {name, toasts}` | the picture `CASE__WORLD__NAME.png` and the page's state then |

Output: the PNGs, `summary.json` (per case and world: the URL, the page's script names, each shot's state: tick, paused, the focused
element and whether its ring shows, the dashboards' and the setup's selected and tabbable tabs, the speed label, toasts, and every page
error), and `index.md` (case, world, shot, file, state). A run fails on any page error or a step that cannot be done.

A later PR adds its sets' cases here (for example S1's setup states or S3's sizes with a case `viewport` and `dpr`), runs the harness
on main and on its branch, and indexes the pictures in its PR.

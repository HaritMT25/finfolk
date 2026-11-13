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
| `tabs(list, o)` | one tablist, with the WAI-ARIA tabs pattern's keyboard model: roving tabindex (Tab lands on the selected tab), the keys of `tabIndexFor` with the focus going with the selection, modified arrows left to the browser, a press that selects (a pointer's lets the focus go, the keyboard's keeps it) |
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
has the focus; the common command vocabulary is P05), and Classic's popovers, sheets and confirmations (P04). Not done here: the
dashboards' tab / panel association for screen readers (their tabs have no `aria-controls` and `#dgrid` no `role="tabpanel"`; the
setup sheets' have both), inherited from before. Both pages now need `ui_common.js`: a page whose copy fails to load stops at its
loading screen (renderer.js and ocean.js use it before their start-up's error handling), which the script-failure coverage (P10) is
to include.

Tests: `node tests/ui_common_tests.cjs` (CI's "web ui" job): the predicates, the tablist on a small DOM (roving focus, wrapping,
Home / End, modified keys, the pointer / keyboard press), the return point, both dashboards' tabs with the same assertions, Classic's
setup sheet through `renderer.js` itself (the page's script run on a small DOM up to its module's load: built, the keys, a pointer's
press, the stored tab), and both pages' script order. `tests/ocean_turbo_handoff.js` runs the Ocean page with `ui_common.js` as
`ocean.html` loads it: its setup sheet's tabs (`pageSetupTabs`), its key router, popovers and tab keys during the tour.

## The paired browser harness: `tests/ui_parity_browser.mjs`

Every UI parity PR pictures both worlds before and after, in the same state, and compares the two runs. The harness does that: one
case at a time, each world in a fresh headless Brave with a temporary profile (clean storage), under the machine-wide browser lock
(`tools/ocean_render_perf/lock.mjs`: it waits, never breaks it; taken for each case and world, so other jobs can run between them),
full-page screenshots that include the DOM chrome. The browser runs are a local tool (CI has no browser); the selection checks and
the comparison gate need no browser and run in CI (`tests/ui_parity_harness_tests.mjs`, the "web ui" job).

### Running it

Serve the repository root with the production isolation headers, then run the harness from Windows node (Playwright and Brave are
Windows-side; `PLAYWRIGHT` and `BRAVE_EXE` override their paths):

```bash
python3 wasm/serve.py . 8262                     # in WSL: the root, so Classic finds ../img/rocks.jpg
```
```powershell
node tests\ui_parity_browser.mjs --list                                   # the cases
node tests\ui_parity_browser.mjs --plan --sets S0,S2                      # what a run would take, or why it is refused (no browser)
node tests\ui_parity_browser.mjs --base http://localhost:8262 --out OUT\after --sets S0,S2 --name "builder-ui-pNN"
```

- `--layout source` (default): Classic is `/web/index.html`, the Ocean `/web/ocean.html`. `--layout site`: `--base` serves a built
  site (`SITE_DIR=/x bash wasm/build_site.sh`, then `python3 wasm/serve.py /x PORT`): Classic is `/classic.html`, the Ocean `/`.
  The routes are explicit: never `/index.html` for Classic (on the site that is the Ocean).
- `--smoke`: each route loaded as a visitor would (no held clock), its ready state, no console error / warning, page error, failed
  request or HTTP error; on the site layout also the Ocean's old name `/ocean.html`. Alone it runs only these; with `--sets` /
  `--cases` those cases too. Smoke pictures are never compared.
- **The selection is checked before any browser starts** (exit 2): every `--worlds` name must be a world, every `--sets` and
  `--cases` entry must exist, and the case x world list must not be empty, with `--smoke` too (`--cases s0_classic_flat --worlds
  ocean` is refused: it would test nothing). The cases file is checked first: unique case ids, unique shot names in each case and
  world (a duplicate would overwrite a picture), known steps, step keys and expectations, a selector for every world a step runs on,
  a shot on every world of a case, a policy with its why. Unknown flags are refused.
- **`--out` must be new or empty**: a run never mixes with an older run's pictures. `--clean` empties it first, but only of the files
  an earlier run's `manifest.json` lists (its captures, the captures it was to take, a failed step's picture) and `manifest.json`,
  `summary.json`, `index.md`: a folder without such a manifest (say, one of your own PNGs) or with any file it does not list is
  refused, and nothing is removed. A comparison's `--out --clean` likewise removes only what its `compare.json` says it wrote.
- Memory: one browser at a time (the lock already enforces it), closed after each case and world.

### What a run writes, and when it fails

- The PNGs, `CASE__WORLD__SHOT.png`.
- **`manifest.json`**, the run's evidence, written before the first case and kept current after each: the harness's and the cases
  file's sha256, the selection, the barrier's timing (`barrierTiming`), every capture the run was to take (`expected`), every one it
  took (`captures`: its sha256, size, case, set, world, shot, and the difference policy the cases file gives it), each run's
  outcome. `complete` is true only at a clean
  end with every run passed and every expected capture taken; an interrupted run (Ctrl+C: the lock is released and Playwright
  closes its browser as the process exits) leaves `complete: false`.
- `summary.json` (per case and world: the URL, the page's script names, the renderer's state after the barrier and the frames it
  ran, each shot's state: tick, the page's frame count, paused, held, the focused element and whether its ring shows, the
  dashboards' and the setup's selected and tabbable tabs, the speed label, toasts; every page error) and `index.md` (case, world,
  shot, file, state).
- A run fails (exit 1) on any page error or warning, a step that cannot be done, a shot whose state is not its `expect`, a shot with
  a toast showing (unless `"toasts": "keep"`), a shot while the frames run free, the renderer not in its full state, or timers that
  never settle; each failure names the case, world and shot.

### Before / after: the comparison gate

Serve a copy of main (`git archive origin/main web img | tar -x -C DIR`, then `serve.py DIR PORT`) and the branch on another port,
run the same harness file with the same cases file against each into new directories (main with `--expect record`: the branch's
cases claim the behaviour the PR brings, which main does not have; the run keeps what it missed instead of stopping), then:

```powershell
node tests\ui_parity_browser.mjs --base http://localhost:8261 --sets S0,S2 --expect record --out OUT\before   # main
node tests\ui_parity_browser.mjs --base http://localhost:8262 --sets S0,S2 --out OUT\after                    # the branch: expectations checked
node tests\ui_parity_browser.mjs --compare OUT\before OUT\after --sets S0 --out OUT\diff_s0           # must PASS: unchanged by the PR
node tests\ui_parity_browser.mjs --compare OUT\before OUT\after --sets S2 --report --out OUT\diff_s2  # the PR's intended changes, listed
node tests\ui_parity_browser.mjs --compare OUT\after OUT\after_repeat                                # two runs of one commit: must PASS
```

`--compare` reads the two runs' manifests, never just the PNGs two directories happen to share, and it is bound to **this harness
file and the cases file it reads itself** (`--cases-file F`, or the committed `tests/fixtures/ui_parity_cases.json`, as for a run),
never to what the two manifests say of each other. The comparison's own selection (`--sets` / `--cases` / `--worlds`; none: every
case of that cases file) is checked as a run's is (exit 2: an unknown set or case, or a selection that compares nothing), and every
capture it plans must be in both runs. **INVALID** (exit 1, both modes, nothing compared):

- the evidence: a directory without a manifest, a run that is not complete, a capture missing or changed since its run (its
  sha256), a PNG the run did not write (stale);
- the identities: a manifest without a valid harness or cases-file sha256, a run taken by another harness file than the one
  comparing, a run of another cases file than the comparison's (so two retained runs of P02's cases file cannot pass against a later
  PR's, which plans a new shot);
- the inventory: the selection a run recorded, run through the cases file, must give exactly its expected captures, and each
  capture must be recorded with its case, set, world and shot and with the policy the cases file gives it (every field in range and
  its why, as the cases file's own policies are checked); BEFORE and AFTER must record the same policy for a picture;
- the coverage: a capture the comparison plans that one run did not take (its selection left it out: narrow the comparison, or take
  the run again).

To look at two runs of an older harness (say, a PR's earlier pictures), `--report --archival --cases-file F` (F the cases file both
used, e.g. `git show COMMIT:tests/fixtures/ui_parity_cases.json > F`) runs every check but the binding to this harness file; the two
runs must still share one. It is a record, never a gate: REPORT at best. Then each picture under its policy: the cases file's `defaults.compare`,
overridden by a case's or a shot's `compare` (a whole policy: `{tolerance, maxPixels, maxNoisePixels, why}`): a pixel differs when a
channel differs by more than `tolerance`; the picture passes with at most `maxPixels` such pixels **and** at most `maxNoisePixels`
pixels that differ by no more than the tolerance, so a shift of one level over the whole picture (every pixel off by 1, none beyond
the tolerance) is a change, not noise. In check mode (the default) a picture beyond its policy or of
another size is a **FAIL** (exit 1); otherwise **PASS** (exit 0). `--report` is for a PR that changes the UI on purpose: the evidence
is checked the same way, differences and size changes are listed, and it exits 0 (**REPORT**) when the evidence is valid. Every
picture that differs at all is listed (`noise` within the policy, `DIFF` beyond it, `SIZE`), and `--out` (new or empty, or
`--clean`) gets a x16 difference picture of each and `compare.json` (mode, verdict, problems, unmet expectations, each file's
result). The expectations BEFORE missed are listed (`unmet`: what the PR brings); AFTER may miss only what BEFORE missed too, the
same way (two runs of main), else the comparison is INVALID.

The default policy, tolerance 1, at most 8 pixels beyond it and at most 32 within it, comes from two runs of one commit with the
first version of the harness (PR #89 at 729b5ba): the compositor's anti-aliasing of rounded edges over the canvas moved a channel by 1 in up to ~21
pixels of a picture, and once 3 pixels at a rounded bar's end differed by up to 17. Since the renderer barrier, the queued idle
callbacks and the sRGB / no-partial-raster flags, two runs of one commit have been identical, every pixel (41 of 41 pictures, main
and the branch, PR #89's fix rounds). These are one machine's measurements (its GPU, driver and compositor); they do not show
that another machine repeats as well. On a new machine, compare two runs of one commit first (`--compare OUT\after
OUT\after_repeat`) before trusting a gate there. A case that needs another policy says so in the cases file, with its why; both
runs then record it, and the comparison checks that they do.

### The state: what is controlled

The plan's capture rules, so that the same picture comes out of every run of a commit:

- **The world**: seed 42 and 300 founders on both pages. Classic ignores setup URL parameters, so the harness uses its real form
  (`#seed`, `#population`) and its Restart; the Ocean takes them from its link (`seed=42&pop=300`). Classic runs its single-threaded
  module (`?threads=0`: the reproducible one); neither runs the tour (`?guide=0&intro=0`). The harness checks tick 0, 300 fish and
  (Ocean) seed 42 before a case starts.
- **The tick**: the pages' animation frames are held from the start, so the new world waits at tick 0. A `run` step lets the page's
  own frame loop go at speed 1 (one step a frame) and, right after the frame that reaches the tick (600), presses the page's own Pause
  button (`then: pause`) or holds the frames there (`then: freeze`: the live UI, still at that tick). The world is never stepped from
  outside the page. Between steps the frames stay held; `settle` (and each step that needs the page to draw) lets an exact number of
  frames run, so every run of a case draws the same frames. A shot while the frames run free (`release` with no `settle` after it)
  fails.
- **The clock**: `performance.now()` and the frames' timestamps advance exactly 1/60 s per animation frame. The frame rate reads 60,
  no governor (Hold 60 fps, Classic's detail and cap) ever acts, and camera eases end the same way on every run.
- **Idle callbacks**: `requestIdleCallback` (both scenes build their caustic texture in one) is queued and run by the harness before
  any frame, never by the browser's idle time, so the caustics fade in over the same frames on every run.
- **The renderer barrier**, after the world is set and before the first step: Classic's script-loaded images (the background,
  `img/rocks.jpg`) decoded; the Ocean's polished fish programs compiled ahead (its swim polish ungated for one frame so the warm-up is
  asked at once, then its setting back) and its decoded programs in effect, else the run fails naming why; the page's one-time
  "click a fish" hint (9 s after ready) waited out, so it always shows with nothing selected and is gone before any step; then a fixed
  number of frames (`barrierFrames`, 90: the caustics' 1.4 s fade and the polish's 30-frame hold end inside it). Each shot checks the
  renderer is still in that state. So no picture is taken while a shader compiles, whatever the GPU's speed: a normal visit draws a
  newly lit fish plain until its programs compile; the harness's pictures always have them compiled. The frames the barrier runs
  depend on the page's settings only: the polish frame runs whenever the polish is drawn (its setting not off, detail 2 up),
  whether the programs were compiled during the world's set-up already (a fast GPU) or not yet, so the clock and every frame
  count after it are the same either way; the barrier checks its own count (1 + `barrierFrames` on the Ocean, `barrierFrames` on
  Classic). `UI_PARITY_READY_FIRST=1` makes a run wait, with the frames held, until the programs are compiled before the barrier
  starts (the fast GPU's timing, on purpose; the manifest's `barrierTiming` says `ready-first`): its pictures must equal a run
  without it.
- **The page's own timers stay real time but are waited out**: before frames run, until no one-shot `setTimeout` of up to 1 s is
  pending (the setup sheet's insets 320 ms after its slide, a tip's 200 ms, a resize's 250 ms), so each lands before the frames and
  never among them; before a shot, every one-shot timer of up to 10 s (a toast's life) as well, then `#toasts` must be empty.
  Intervals (`setInterval`) stay real time and are not waited on, because no S0 / S2 picture depends on one: the charts draw when
  they open and at each tab change (`showTab` calls `update(true)` at once, in both `dashboard.js` and `ocean_dash.js`), and their
  500 ms interval's `update()` redraws only when the recorded data, the tab or the grid's width changed, or (Classic's Similarity,
  either page's Brains) when the page's clock has moved 10 s / 3 s past that analysis's cache; with the world paused and the frames held, none of these happens, so a tick of it
  before or after a picture changes nothing. The tour's and the Turbo coach's intervals are off (`?guide=0`); the Ocean's 50 ms one
  runs only while a Turbo start can be cancelled. A future case that depends on an interval or a longer timer (a running world
  with the charts open, the tour, Turbo) must wait for it explicitly, or the harness must control intervals as it does frames.
- **Animation time**: each scene's `render` gets a fixed `animT` (both scenes' `create()` are wrapped as they register, as
  `tools/ocean_render_perf/shots.mjs` freezes the Ocean's).
- **Visual randomness**: `Math.random` is a seeded xorshift32 (snow, streaks).
- **The picture**: fonts loaded, CSS animations and transitions finished (`animations: "disabled"`), the caret hidden; locale en-US,
  timezone UTC, the sRGB colour profile, no partial raster, 1440 x 900 at DPR 1 unless the case says otherwise.

Not controlled, hence the policy: the GPU's and the compositor's anti-aliasing. Screenshots establish appearance and access;
numerical claims (counts, ticks, identity) belong in node tests.

### Cases: `tests/fixtures/ui_parity_cases.json`

A case has an `id`, its screenshot `set` (S0 to S9, the plan's), a `title`, its `worlds`, an optional `query` (one string, or
`{classic, ocean}`), an optional `compare` policy and `steps`. A step with `"world"` runs on that world only; a `"sel"` is a selector
or `{classic, ocean}`.

| step | what it does |
|---|---|
| `run {tick, then}` | the frame loop to the tick, then `pause` (the page's Pause) or `freeze` (frames held: the live UI) |
| `pause` | the page's Pause pressed if it runs, then `settle` |
| `release` / `freeze` | the frames let go with no count (no shot until a `settle`) / held |
| `settle {frames}` | exactly that many frames (default 45), then held |
| `select` | a fish selected through the page: Classic's `EvoApp.inspectSomeFish()` (nearest (0.4 W, 0.45 H)), the Ocean's `EvoOcean.select` of the fish nearest the same point |
| `click {sel}` | a real pointer click at the element (no focus ring) |
| `press {sel}` | `element.click()`: a click no pointer made (`detail` 0) |
| `key {key, times}` | a key where the focus is |
| `tabTo {sel, max}` | Tab pressed until the focus is on the element: the keyboard's way there (its ring shows) |
| `focus {sel}` / `blur` | `element.focus()` / the focused element's `blur()` |
| `wait {ms}` | real time |
| `shot {name, toasts, expect, compare}` | the picture `CASE__WORLD__NAME.png` and the page's state then |

A shot's `expect` is the state it must find, else the run fails: `tick`, `paused`, `held`, `speed` (the dock's label, e.g. `"2×"`),
`dashOpen`, `sheetOpen`, `toasts` (a count), `focus` (`null`: nothing focused, or `{id, role, text, tag, ring}`: `ring` is whether
`:focus-visible` matches), `dash` / `setup` (`{selected, tabbable}`: the tab ids); per world under `"classic"` / `"ocean"`. A case
that claims a focus, a selected tab or a speed says so here, so the pictures cannot drift from the claim unnoticed. With `--expect
record` a missed expectation is kept with its capture (`unmet` in the manifest and summary) and the run goes on: for main's run
before a PR that brings the behaviour; a PR's own run checks them (the default).

A later PR appends its sets' cases here (for example S1's setup states or S3's sizes with a case `viewport` and `dpr`), runs the
harness on main and on its branch, gates the sets it must not change with `--compare` and reports the ones it changes with
`--report`, and indexes the pictures in its PR.

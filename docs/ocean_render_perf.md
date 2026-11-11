# The Ocean page's render optimization

Display only: nothing here reaches the simulation, the Wasm modules or any baseline (`git diff --stat -- src wasm tests/ocean_baseline`
is empty, and `web/evo_*.wasm` are the committed bytes). The page draws its fish through one of two pipelines: the **reference** one, main's as
it was (one instanced body draw of the detail setting's template, every gene decoded in every vertex, barbel strips for every fish
whenever any fish has barbels), and the **optimized** one, now the default. `?renderOpt=0` (or `renderOptimization: false` to
`EvoOceanScene.create`) draws through the reference pipeline, byte for byte (`tests/ocean_mock_three_tests.mjs` keeps its committed recording
of it), for an A/B link and as the pipeline the optimization is measured against.

## Why

`ocean_handoff/render_perf/report.md` (measurement only, main 1712d98) found the 3-D Ocean page GPU-bound, and vertex-bound: 2,000 fish
cost 20.3 ms of GPU time a frame at 1400 x 900 in Appearance colour (13.1 ms in Family colour, the site's saved-preference default), of which
about 16 ms were the fish passes, 1.0 million vertices a frame (body 190 x 2,000, shadow 190 x 2,000, barbels 120 x 2,000), each running the
whole decode of the fish's genes. The three biggest, independent costs, and what this change does about them:

| | the cost | what is done |
|---|---|---|
| 1 | every body drew the 190-vertex medium template, though almost every fish is a few pixels across | **screen LOD**: two instanced body draws, medium for the fish at least 7 px across (5 px to leave it), the 89-vertex coarse one for the rest |
| 2 | every vertex of every pass fetched 16 gene texels and re-ran `mDecode` (and in Appearance colour `patternDecode`, ten flat `vec4`s) for constants that never change under a fish's id | **decoded constants**: decoded once at the fish's birth into a second texture, read by the shaders (8 texel reads a vertex; the skin's 10 in the fragment stage; 13 varying components, not 51) |
| 3 | the barbel strips (120 vertices a fish) were drawn for every fish at every distance whenever any fish had barbels | **gated barbels**: strips only for fish that have them (gene above float32 0.2), are in the medium template and at least 6 px across |

Out of scope, listed apart (the report's 4 and 5): coarse shadows (the shadow draw stays the detail setting's template for every
fish, in snapshot order, so overlapping translucent shadows keep their depth-write order) and a DPR cap.

## The policy

`scene.setRenderOptimization({ lod, decoded, barbels })` -> `Promise` of `{ ok, requested, effective, error }`;
`scene.renderOptimization()` -> the requested and effective policy, the buckets of the last frame (fish per body bucket, barbel
instances, body vertices a frame), the decoded cache's counters and allocations, and a failure list. Default `{ lod: "screen",
decoded: true, barbels: "gated" }`.

- `lod`: `"quality"` (the reference: the detail setting's template for every fish), `"screen"`, or `"medium"` / `"coarse"` (every fish
  in that bucket: forced-equivalence checks and measurements). Detail 1 and 2 draw every body coarse as before; the selected and the hovered
  fish are medium at detail 3 whatever their size; a fish wholly out of view (behind the camera, or outside a side plane of the frustum)
  is coarse (nothing of it shows, and its vertices are the cost).
- `decoded`: `false` or `true`. The decoded programs take effect only once every reachable variant (plain, polished, shadow, lit-split
  skip) compiled (`binder.setRender`, the binder's atomic activation, as a Look's); until then, and on any failure (no texture room, a
  compile error, a Look that did not declare `appearanceCache: 1`), the raw programs draw, the reason is kept in `failures` and said once on
  the console.
- `barbels`: `"body"` (the reference: every fish of the draw), `"gated"`, `"off"`.
- The lit split (`setLitSplit(true)`, off by default, measured slower) is drawn by the reference pipeline while it is on.

## How it works

- **Buckets.** `fillApp` projects every fish once (`posePx`'s formula, kept bit for bit; the size weight reuses it), `bodyLod`
  (web/ocean_pose.js) picks its bucket with a hysteresis kept by gene slot (reset by the slot store's owner hooks, so a slot's state is its
  owner's), and `commit` compacts each bucket into instance buffers of its own: the fish's 21 floats, gene slot included, in snapshot order
  within the bucket. The canonical staging (snapshot order) stays: the shadow draw, picking, the probes, `poseOf` and `geneSlots` read it, and
  batch indices never reach them. Template-dependent fins (`mFacet` puts a fin on the template's own rings) need each draw's ring
  uniforms: every optimized mesh sets its own just before its draw (`onBeforeRender`, `uniformsNeedUpdate`).
- **Decoded constants.** `EvoAppearance.writeDecoded` packs a row with the existing line-for-line CPU mirrors (`morphDecode`,
  `patternVaryings`): 18 RGBA32F texels (72 floats) a slot, 32 slots a texture row (576 texels wide); texels 0-7 the 32 body-plan
  values, 8-15 the pattern's `vG0..vG7`, 16-17 `vAux.xyz` and `vMeta.xy`; lambda is not cached. The slot store's `onInstall` writes
  it once per birth; the upload reuses the raw plan's ranges (the same slots: 72 floats there, 64 here), and both textures are flushed
  with `renderer.initTexture` before the draws (the decoded programs sample no raw genes, so nothing else would consume the raw upload).
  Seven new named slots in `ocean_shaders.js` (`app.cache.vs`, `app.pattern.vs`, `app.fetch.body`, `app.fetch.shadow`, `app.morph`,
  `app.pattern.fs`, `app.pattern.load`) are each the program's own text when the feature is off, so every digest pin holds byte for byte;
  the feature `render.decoded` fills them and composes with the swim polish.
- **Barbels.** Their own compacted draw over their own buffers, medium rings; independent of the body buckets (it also gates under
  `lod: "quality"`).

## Method

`tools/ocean_render_perf/cycle.mjs`, headless Chromium 157 (Brave) under Playwright on an Intel Iris Xe (ANGLE / D3D11, EXT_disjoint_timer_query),
a laptop with other applications running, one page per cell, the benchmark case of `tests/fixtures/ocean_render_cases.json` (seed 42,
1920 x 1080 x 240 world, glass walls, paused at tick 0, no predators alive, governor off) at 1400 x 900, DPR 1 unless said, detail 3.
The arms are policies set by page code, run in 5 s blocks after a 1.5 s settle and cycled (the order reversed on odd cycles) with the reference
arm `q3` at the start and `q3z` at the end of every cycle; each arm is compared with **that cycle's** reference (the mean of the two), and the
table gives the median over 6 cycles with the IQR of the cycles' paired differences. Per block: the GPU frame time (a timer query round
the whole submission every 4th frame, p50 of the block), the CPU frame time (p50), and a draw census (every instanced draw's index
count and instance count, so the vertices and draws a frame are counted, not assumed). The GPU clock drifts between runs and phases (the
reference arm of the same cell read 17.1 ms in one session and 19.5 in another), so compare arms inside a cell, never absolutes across
cells or sessions. The reference arm is this build's reference pipeline: the page as on main (it draws main's pixels exactly, below; the
fresh baseline on main 82ba348 itself, `render_perf/b0`, read 19.5 / 14.4 ms for Appearance / Family 2000 whole in a slower GPU state, with the
same 1.000 M vertices and 3 fish draws, and the report's breakdown: the shadow pass 0.9 to 1.9 ms, the barbel draw 2.0 to 3.2, the medium
to coarse change 4.4 to 9.0, in the cells it measured). The 2,000-fish Appearance fit cell was disturbed in its first
run (another application on the GPU: the reference anchor spread over the cycles 17.5 to 63.8 ms) and repeated; the table shows the repeat.

Arms (cumulative policies are the point; `all` is the default): `lod` the screen LOD alone, `cache` the decoded constants alone, `barb` the
gated barbels alone, `lodCache` both of the first two, `all` all three. `reference` is `{ lod: "quality", decoded: false, barbels: "body" }`.

## Results (GPU frame, ms; verts: body + shadow + barbel vertices a frame)

| cell | arm | GPU p50 ms | paired change vs the reference (median; IQR) | ratio | verts / frame | fish draws | CPU frame p50 ms |
|---|---|---|---|---|---|---|---|
| Appearance 2000 fish whole | reference | 17.12 | - | 1 | 1.000M | 3.0 | 2.03 |
|  | lod | 10.69 | -6.44 (-6.72..-6.25) | 0.624 | 0.558M | 2.0 | 2.50 |
|  | cache | 10.85 | -6.29 (-6.58..-6.20) | 0.633 | 1.000M | 3.0 | 2.22 |
|  | barb | 13.97 | -3.15 (-3.17..-3.14) | 0.816 | 0.760M | 2.0 | 2.25 |
|  | **all** | **9.91** | **-7.22 (-7.55..-7.17)** | **0.579** | 0.558M | 2.0 | 2.43 |
| Appearance 2000 fish fit | reference | 16.92 | - | 1 | 1.000M | 3.0 | 2.17 |
|  | lod | 10.76 | -6.30 (-6.81..-6.07) | 0.631 | 0.558M | 2.0 | 2.36 |
|  | cache | 10.63 | -6.23 (-6.42..-5.45) | 0.630 | 1.000M | 3.0 | 2.34 |
|  | barb | 13.75 | -3.14 (-3.18..-3.09) | 0.814 | 0.760M | 2.0 | 2.46 |
|  | **all** | **9.44** | **-7.57 (-7.74..-7.26)** | **0.556** | 0.558M | 2.0 | 2.55 |
| Appearance 2000 fish close-up (dense) | reference | 19.90 | - | 1 | 1.000M | 3.0 | 3.12 |
|  | lod | 12.63 | -6.75 (-7.29..-6.49) | 0.652 | 0.602M | 4.0 | 3.20 |
|  | cache | 12.65 | -6.27 (-7.41..-5.82) | 0.667 | 1.000M | 3.0 | 2.32 |
|  | barb | 16.60 | -2.73 (-3.00..-2.41) | 0.858 | 0.813M | 3.0 | 3.02 |
|  | **all** | **8.72** | **-10.30 (-10.64..-9.45)** | **0.466** | 0.583M | 4.0 | 3.00 |
| Appearance 2000 fish follow | reference | 18.65 | - | 1 | 1.000M | 3.0 | 3.69 |
|  | lod | 12.88 | -7.60 (-7.99..-5.38) | 0.629 | 0.630M | 4.0 | 4.15 |
|  | cache | 10.81 | -8.40 (-8.74..-7.69) | 0.560 | 1.000M | 3.0 | 3.21 |
|  | barb | 15.95 | -2.64 (-3.47..-1.82) | 0.855 | 0.812M | 3.0 | 3.65 |
|  | **all** | **7.88** | **-10.47 (-11.55..-9.67)** | **0.417** | 0.600M | 4.0 | 3.24 |
| Appearance 2000 fish whole, DPR 2 (2800 x 1800) | reference | 28.44 | - | 1 | 1.000M | 3.0 | 2.79 |
|  | lod | 18.88 | -9.43 (-9.78..-9.34) | 0.664 | 0.558M | 2.0 | 3.66 |
|  | cache | 21.32 | -7.24 (-7.42..-6.41) | 0.750 | 1.000M | 3.0 | 3.51 |
|  | barb | 24.22 | -3.72 (-4.74..-3.12) | 0.867 | 0.760M | 2.0 | 2.94 |
|  | **all** | **17.54** | **-11.14 (-11.92..-10.69)** | **0.615** | 0.558M | 2.0 | 3.85 |
| Appearance 300 fish whole | reference | 6.09 | - | 1 | 0.150M | 3.0 | 0.99 |
|  | lod | 4.43 | -1.47 (-1.68..-1.15) | 0.757 | 0.084M | 2.0 | 0.99 |
|  | cache | 4.43 | -1.42 (-1.52..-1.25) | 0.763 | 0.150M | 3.0 | 0.88 |
|  | barb | 5.09 | -1.29 (-1.80..-0.20) | 0.786 | 0.114M | 2.0 | 0.89 |
|  | **all** | **4.19** | **-2.00 (-2.39..-1.39)** | **0.685** | 0.084M | 2.0 | 0.94 |
| Family 2000 fish whole | reference | 11.09 | - | 1 | 1.000M | 3.0 | 2.13 |
|  | lod | 10.21 | -0.86 (-1.22..-0.47) | 0.923 | 0.558M | 2.0 | 2.45 |
|  | cache | 10.36 | -0.82 (-0.99..-0.66) | 0.925 | 1.000M | 3.0 | 2.21 |
|  | barb | 9.90 | -1.29 (-1.68..-1.12) | 0.885 | 0.760M | 2.0 | 2.35 |
|  | **all** | **9.91** | **-1.30 (-1.53..-1.08)** | **0.883** | 0.558M | 2.0 | 2.61 |
| Family 2000 fish fit | reference | 13.36 | - | 1 | 1.000M | 3.0 | 1.66 |
|  | lod | 9.03 | -4.44 (-5.35..-3.74) | 0.671 | 0.558M | 2.0 | 1.93 |
|  | cache | 12.35 | -0.25 (-1.18..0.71) | 0.977 | 1.000M | 3.0 | 1.82 |
|  | barb | 11.91 | -0.43 (-1.09..0.02) | 0.965 | 0.760M | 2.0 | 1.94 |
|  | **all** | **8.71** | **-3.90 (-4.64..-3.34)** | **0.679** | 0.558M | 2.0 | 2.04 |
| Family 300 fish whole | reference | 4.83 | - | 1 | 0.150M | 3.0 | 0.91 |
|  | **all** | **4.03** | **-0.51 (-0.79..-0.23)** | **0.889** | 0.084M | 2.0 | 0.97 |

(`lodCache` rows and every cell's raw blocks: `render_perf/a1`, `a2` and `tables_final.md`.)

What the arms say:

- **The fixes overlap** (they attack the same vertices), so the arms do not add: in the whole views `lod` alone and `cache` alone each take
  about 6.3 ms of Appearance's 17 (37 %), both together 7.5, and the gated barbels add nothing once the LOD has taken every fish
  to the coarse template (no medium fish, no strips); they pay in the close-up and follow cells, where `all` is 0.7 ms under `lodCache` in
  both (the medium fish's strips are the ones that matter), and in Family 2000 whole (1.0 ms, IQR -1.2..0.3). `all - lodCache` is inside
  the IQR in most cells: take the barbel gate as a close-up saving, not a whole-view one.
- **Where the time that is left goes.** The fish passes (`all` minus the same arm with every fish hidden) fell from 13.2 to 6.0 ms in
  the Appearance whole cell (and are 5.5 and 4.8 ms after, in the close-up and follow cells), the fixed cost (floor and caustics, about 3.9 ms; 9 ms at DPR 2) is untouched. Family
  colour has no pattern decode to remove: its whole-view gain is 1.3 ms of 11 (12 %), 3.9 of 13.4 in the fit view (32 %), and its fish passes are now
  about 6 ms, as Appearance's: what is left is the shadow draw (190 vertices x 2,000, the next candidate, report item 4), the coarse bodies and
  the fragments.
- **DPR 2** gains as much (-11.1 ms of 28.4): the decoded pattern's per-fragment texel reads cost nothing visible against the vertices
  they replace (`cache` alone: -7.2 ms at DPR 2, -6.3 at DPR 1).
- **CPU:** +0.4 ms a frame in the 2,000-fish cells (the projection and bucketing of every fish, two copies of 21 floats, the barbel
  compaction; 2.0 to 2.4 ms in the whole view), about +0.0 to 0.1 ms at 300 fish; the frame is GPU-bound (17 ms) and the saving is
  an order of magnitude more than the CPU cost.
- **Births:** a fish is decoded once when it is first seen: 4.9 us (node, V8; `EvoAppearance.writeDecoded`), so a whole 2,000-fish
  turnover (a new world, a Turbo return) costs 9.7 ms once and 20 births a frame 0.1 ms; the upload is the births' ranges (72 floats a
  slot, the raw upload's ranges). A live (one step a frame) cell was run but its population fell while the arms ran, so its arms are not
  comparable and it is not tabled.

## The thresholds

Body: medium from 7 px of projected body radius, back to coarse at 5 (`LOD_MEDIUM_ENTER_CSS` / `EXIT_CSS`, web/ocean_pose.js); barbels from
6 px, kept down to 4.5. They are the code-level plan's starting values and the measurement kept them (`tools/ocean_render_perf/lodstudy.mjs`,
`render_perf/lodstudy1`): ten fish (the ones with barbels first) side-on at a ladder of distances, forced medium against forced coarse
(barbels off) and forced medium with barbels against none, the pixels that differ by 24 / 255 or more in a window round the fish (median over the fish):

| projected radius, px | 3 | 4 | 5 | 6 | 7 | 8 | 10 | 12 | 16 |
|---|---|---|---|---|---|---|---|---|---|
| body: pixels differing by >= 24 | 10 | 22 | 36 | 53 | 71 | 103 | 178 | 250 | 449 |
| body: largest difference (of 255) | 55 | 80 | 86 | 96 | 108 | 116 | 128 | 129 | 169 |
| barbels: pixels differing by >= 24 | 3 | 4 | 5 | 6 | 9 | 7 | 9 | 14 | 20 |

The medium and the coarse body never stop differing: the difference is a constant share of the silhouette's edge (1.1 to 1.8 pixels per squared
pixel of radius), so there is no size at which it vanishes, only one at which it is small in absolute terms: 36 pixels spread over a
fish's edge at 5 px, 71 at 7. The pictures (`docs/media/render/lod_pair_5px.png`, `_7px`, `_12px`: medium | coarse | difference x8 |
with barbels | difference x8) look alike to the eye even at 12 px, the barbel strips are a handful of pixels at any of these sizes, and the
hysteresis (7 in, 5 out) means a fish near a threshold never flips between frames. A higher threshold would save more (the share of fish that
is medium falls) at a visible cost nobody measured; the conservative reading (fidelity first) keeps the plan's.

## Before / after pictures (`render_perf/shots1`, `tools/ocean_render_perf/shots.mjs`)

The same paused world (seed 42), camera and frozen animation clock under every arm; the framebuffer read back after the page's own frame
and compared pixel for pixel with the reference arm, for 300 and 2,000 fish, Appearance and Family colours, the whole, fit, close-up (dense) and follow
cameras (16 cells):

- **The body buckets alone are exact**: `medium` (every fish in the medium bucket, decoded off, barbels as the reference) differs from the
  reference in **0 pixels in all 16 cells**, which proves the compaction, the per-draw ring uniforms and the draw order.
- **The decoded constants** (`cache`; the same with every fish medium: `mediumCache`) differ in 0.003 to 0.12 % of the pixels (37 to 1,557 of 1.26 M),
  by at most 38 / 255, always isolated edge pixels: the CPU decodes in doubles and rounds to float32, the shader computed in float32 with its own
  transcendentals (the GPU checks hold the decoded programs to the same tolerances as the raw ones: below).
- **The screen LOD** differs where, and only where, a fish is coarse that was medium: whole 2,000 views 10.9 % of the pixels (Family 10.5 %; mean
  1.0 / 255 per channel: a few-pixel fish's edge), fit 6.8 %, 300 fish 1.9 % and 1.2 %; **close-up (dense) 2,000 fish: 0 pixels**; follow: the followed
  fish and every near one identical, the distant band at the top differs (0.6 %, 7,758 pixels, in the region of the far fish). Figures:
  `docs/media/render/whole2000.png` (Appearance, whole), `fit2000_family.png`, `dense2000.png` (identical), `follow2000_subject.png` (the
  followed fish), `follow2000_far.png` (distant fish): reference | optimized | difference x16.
- **The gated barbels**: 0.3 % of the pixels in the 2,000 whole views (the strips of the small fish that lost them, up to 222 / 255 on a
  pixel or two of each), 0.26 % fit, 0.007 % follow, none in the close-up.

The visible differences are the intended ones and are justified by the table above: the coarse template on a fish a few pixels across, the
absent strips on a fish a few pixels across. Close-up and follow subjects look the same (0 differing pixels in the close-up, none on the followed
fish).

## What was run (all green on the final head)

- Node: `ocean_appearance_slots_tests.cjs` (the owner hooks, `eachOwner`), `ocean_shader_slots_tests.cjs` (the seven new slots, each
  its own fallback byte for byte; every digest pin unchanged; the feature in every program and polish variant), `ocean_materials_tests.cjs`
  (the binder's render features: refusals, a planted compile failure and assembly error, Looks), `ocean_render_opt_tests.cjs` (bodyLod,
  barbelVisible, writeDecoded against the CPU mirrors), `ocean_mock_three_tests.mjs` (the reference recording unchanged: `GOLDEN`; the policy
  API; sessions through the real scene for the buckets, the barbels' gate and the decoded cache with a model of the GPU's copy of both textures,
  and planted faults each must see), `ocean_perf_tests.cjs`, `npx tsc -p tsconfig.json`.
- Browser (headless Brave, one at a time under the lock): `tests/ocean_render_browser.mjs` parts correctness, slots, noperf, missing, faults,
  timer, beam, iframe, gate; its new checks hold the decoded vertex stages (plain, full and lite polish, permuted and sparse slot maps), the
  decoded texels as the GPU reads them (bit for bit against the CPU's decode) and the decoded fragment stages to the raw checks' tolerances
  (world 0.02 / material 0.005 / margin 0.005 / decode 0.0005, none relaxed: measured world 0.0013 to 0.0018), and the planted faults they must see; `offimage` with
  `--query renderOpt=0` (the reference pipeline draws main's pixels exactly in every state: whole and close, selected and hovered, the flashlight, predators);
  `tools/ocean_render_perf/smoke.mjs`: no console, page or network message on the Ocean page (default policy, the reference pipeline, Family colours), the
  Classic page and the body plan's check page.
- Unchanged: `src/`, `wasm/`, the committed Wasm modules and their hashes (`web/evo_boids*.wasm` equal `classic_wasm.sha256`), the baselines, the
  governor's logic and the DPR caps.

## Deviations from the code-level plan (render_plan_codex.md), where the code disagreed or a simpler reading was kept

- The plan's baseline note: the report measured 1712d98, this PR's fresh baseline is main 82ba348 (and every measurement sets the colour mode explicitly).
- **The lit split** (`setLitSplit(true)`, off by default, measured slower) is drawn by the reference pipeline while it is on, instead of partitioning each
  LOD batch into plain and full batches: the body buckets and the barbel compaction are off then. Its behaviour and tests are unchanged.
- **A fish wholly out of view is coarse** (a rule the plan did not have): `posePx` clamps the depth at the near plane, so a fish behind the camera reads
  as huge; its vertices are the cost and none of it shows, so it takes the coarse bucket (poseVisibleQ, the polish's own visibility test).
- **No paired upload acknowledgement.** The plan acknowledged the raw slot plan only after both textures' `onUpdate`; here the decoded ranges are
  derived from the raw plan every frame until it is acknowledged, and both textures are flushed together with `renderer.initTexture` (the decoded first,
  the raw acknowledgement after), so the decoded copy is never behind the raw plan's acknowledgement and a skipped frame loses nothing.
- **The decoded programs switch on only after they compiled**: the first frames after the appearance fish appear draw the raw programs (the binder's atomic
  activation, `binder.setRender`); a failure keeps them and says why (`renderOptimization().failures`, once on the console).
- The per-draw rings take a getter (the canonical, shadow and lit meshes follow the detail setting), not a fixed template.
- The decoder check reads the texels back through transform feedback (one `vec4` a point, 18 a fish) as the plan asked; the oracle for the pattern's constants
  is the CPU mirror that the raw GLSL is already held to (`decode` 0.0005), and the body plan's through every template vertex's position.

## Not done (listed apart, out of scope)

Coarse shadows (the shadow draw is the detail setting's template for every fish; ~1 ms of the 6 ms that is left), a DPR cap, a frustum compaction of
the instance buffers, and the Gemini critique of the plan (`gemini_bridge/answers/q43.md`) had not arrived when this was written.

## Reproduce

```bash
python3 wasm/serve.py web 8182                      # the site; and, for the Classic and body plan pages, python3 wasm/serve.py . 8183
node tools/ocean_render_perf/cycle.mjs --base http://localhost:8182 --root . --out OUT --counts 2000 --cameras whole --colour appearance \
     --arms q3,lod,cache,barb,lodCache,all,allnf,q3z --rounds 6     # then: node tools/ocean_render_perf/analyze.mjs OUT/result.json
node tools/ocean_render_perf/shots.mjs --base http://localhost:8182 --root . --out OUT --counts 300,2000
node tools/ocean_render_perf/lodstudy.mjs --base http://localhost:8182 --root . --out OUT
node tools/ocean_render_perf/smoke.mjs --web http://localhost:8182 --root http://localhost:8183
node tests/ocean_render_browser.mjs --base http://localhost:8182 --parts correctness,faults,slots,noperf,missing,timer,beam,iframe,gate
```

Every browser job takes the machine-wide lock (`tools/ocean_render_perf/lock.mjs`), one headless browser at a time.

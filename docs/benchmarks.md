# Benchmarks

Moved here from the README, which carries a short summary. These numbers come from one machine; each section says
when it was measured, and the sections dated before 2026-10-24 predate the step-speed changes described later in this file.

The machine and the first set of measurements (2026-10-18; later sections give their own dates):

- Intel Core i7-1165G7 (4 cores / 8 threads), 16 GB RAM, Windows 11, "Balanced" power plan.
- Power source as noted per table.
- Native builds: g++ 13.3, `-O3`, in WSL2 (Ubuntu 24.04).
- WebAssembly: Emscripten 6.0.4. Step times were measured under Node 22.16 (V8), and frame rates in Chrome 155.

## Agents at a stable 60 fps in the browser

Measured with `?bench`, on battery, on a 60 Hz display. The population is pinned at N, and the page takes one simulation step per frame on a 1920×1080 canvas. "Stable" means a mean of at least 58 fps and a 95th-percentile frame time of 20 ms or less, over 300 frames.

| module | drawing | stable 60 fps up to | next N measured |
|---|---|---:|---|
| threaded, 8 threads | WebGL2 | 10,000 | 12,000: 43.6 fps |
| single-threaded | WebGL2 | 4,000 | 6,000: 53.9 fps |
| threaded, 8 threads | canvas 2D | 1,500 | 2,000: 54.1 fps |
| single-threaded | canvas 2D | 1,000 | 1,500: 55.4 fps |

With canvas 2D, drawing was the bottleneck: at 2,000 agents a frame spent 11.6–13.2 ms drawing, against 0.3–0.7 ms with WebGL2. That is why WebGL2 is the default.

A repeat on AC power is not in the table, because the display refreshed at about 56.6 Hz during it, so it could not test 60 fps. Against that rate, the page held steady up to:
- threaded + WebGL2: 12,000 (37.6 fps at 16,000)
- single-threaded + WebGL2: 6,000 (38 fps at 8,000)
- both canvas 2D rows: 2,000 (39–41 fps at 3,000)

`?bench` now detects a display slower than 58 Hz and reports against its rate instead.

## Drawing cost by browser and view

Measured on the same laptop with `?bench`, in browsers drawing on the Iris Xe GPU (ANGLE, Direct3D 11), threaded × 8, 1440×900 window: headless on AC power on 2026-10-20; on 2026-10-22 Firefox's tank rounds, one of its headless flat rounds and its windowed runs on battery, and the windowed Chrome runs on AC power. Each pair alternated in one browser; the median draw time per frame is the part `?bench` reports as "draw ms" (sync, snapshot and drawing, without the step). Headless frame pacing isn't the display's, so these compare drawing between views and browsers; they don't replace the table above.

| browser | view | rounds | draw at 2,000 | draw at 8,000 | draw at 12,000 |
|---|---|---:|---:|---:|---:|
| Chrome 155 | flat (WebGL2) | 2 | 0.79–0.80 ms | 1.41–1.44 ms | 1.51–1.54 ms |
| Chrome 155 | tank | 2 | 1.10–1.11 ms | 2.75–2.92 ms | 2.42–2.74 ms |
| Chrome 155, windowed | flat (WebGL2) | 2 | 0.70 ms | 0.87–0.88 ms | 1.24–1.25 ms |
| Chrome 155, windowed | tank | 2 | 1.06–1.11 ms | 2.18–2.19 ms | 2.51–3.94 ms |
| Firefox 155 (Playwright), headless | flat (WebGL2) | 3 | 15.9–18.7 ms | 19.0–24.8 ms | not reached |
| Firefox 155 (Playwright), headless | tank | 2 | 0.82–1.56 ms | 2.16–2.24 ms | not reached |
| Firefox 155 (Playwright), windowed, on battery | flat (WebGL2) | 1 | 1.72 ms | 2.12 ms | 2.34 ms |
| Firefox 155 (Playwright), windowed, on battery | tank | 1 | 1.44 ms | 2.10 ms | 2.12 ms |

In the windowed Chrome runs (AC power, a display at about 56.6 Hz, so stable means holding that rate), the flat view held it up to 12,000 agents in both rounds and the tank up to 10,000 (38.7 and 51 fps at 12,000): the same limits #7 measured.

Headless Firefox adds a fixed ~16 ms to every flat-view frame, whatever the number of agents (16.2 ms at 250, 15.9 ms at 2,000; one more battery run stopped at 250 agents, at 35.9 ms). The cost is the per-frame copy of the offscreen WebGL2 canvas onto the visible 2D canvas (`ctx.drawImage`): in a test page, that copy took 16.4 ms of JavaScript per frame in headless Firefox, against 1.4 ms when the WebGL2 canvas is shown directly with a 2D overlay, and 0.5–0.8 ms in a windowed Firefox. Windowed, on the real page, the flat view drew in under 2.4 ms at every count up to 12,000. So the headless number is an artifact of headless Firefox, not what visitors see. Playwright's windowed Firefox paced every page here, a bare WebGL2 canvas included, at about 35 fps, so its frame rate says nothing about a regular Firefox; Chrome held about 57 fps (the display's rate on battery) in the same tests.

The page starts the single-threaded module at 300 creatures and the threaded one at 600. Under the default settings, the population then settles between roughly 250 and 800.

## Faster steps, same results (2026-10-24)

A step got 1.3–2× faster without changing a single result: every checkpoint, every inspector value and the native/wasm parity come out bit for bit as before. Most of the gain came from removing branches the CPU could not predict (which side of a fish a neighbour is on, whether a grid candidate is inside the sensing radius, whether two genes' types match), from laying the spatial grid out as one array, and from keeping the positions the neighbour scan reads in a compact array of their own.

Measured against the previous version in one process: both builds side by side on the same world, alternating short blocks of steps, the median of three seeds (three repeats for the thread pool), on AC power. The single-threaded runs compared the two worlds byte for byte at the end. Each cell is the old step time divided by the new one.

| creatures | native, 1 thread | wasm, 1 thread (Node 22, Chrome's V8) | native thread pool, 4 threads | thread pool, 8 threads |
|---:|---:|---:|---:|---:|
| 300 | 1.53× | 1.31× | | |
| 1,000 | 1.67× | 1.40× | | |
| 3,000 | 1.81× | 1.51× | 1.58× | 1.47× |
| 8,000 (an evolved world) | 2.02× | 1.68× | 1.78× | 1.67× |
| 12,000 | | | 1.98× | 1.87× |

The thread pool is the code the browser's threaded module runs, built natively. The wasm module gained less because its `tanhf` costs more than twice as much as native, so the neural network is a larger share of its step.

That was the next step: the neural network's `tanh` is now computed without branches, four values at a time, natively with SSE2 and in the browser with WebAssembly SIMD. It gives the same bits as before on every one of the 2^32 possible inputs (checked exhaustively, natively and in wasm). On top of the table above, with the same method:

| creatures | native, 1 thread | wasm, 1 thread (Node 22) |
|---:|---:|---:|
| 300 | 1.10× | 1.16× |
| 1,000 | 1.12× | 1.19× |
| 3,000 | 1.09× | 1.15× |
| 8,000 (an evolved world) | 1.07× | 1.14× |

Of the wasm gain, 1.02–1.04× comes from building with SIMD at all, the rest from the branch-free `tanh`. The table below predates both changes.

## Step time at a fixed creature count

Milliseconds per simulation step, lower is better, measured on AC power. Each cell is the median of 3 runs, and each run is the median of 5 blocks of 200 steps. Produced by `wasm/bench.sh`: one source file (`wasm/bench_fixed.cpp`) built for every target. The population is pinned, on a 1920×1080 world with default settings.

| creatures | native, 1 thread | native OpenMP, 2 | OpenMP, 4 | OpenMP, 8 | wasm, 1 thread | wasm threaded, 2 | threaded, 4 | threaded, 8 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 500 | 0.65 | 0.37 | 0.26 | 0.22 | 0.73 | 0.49 | 0.55 | 0.52 |
| 1,000 | 1.37 | 0.92 | 0.70 | 0.62 | 1.59 | 1.08 | 0.88 | 0.77 |
| 2,000 | 2.97 | 2.03 | 1.38 | 1.30 | 3.48 | 2.47 | 1.91 | 1.64 |
| 4,000 | 7.43 | 4.77 | 3.59 | 3.05 | 8.82 | 5.85 | 4.42 | 3.59 |
| 8,000 | 21.17 | 13.39 | 10.21 | 7.82 | 25.12 | 16.41 | 11.57 | 9.27 |

- Single-threaded wasm took 1.13–1.19× as long per step as the native single-threaded build.
- From 1,000 creatures up, the threaded wasm build took 1.13–1.38× as long as native OpenMP at the same thread count, about 1.2× in most cells. At 500 it took 1.3–2.4× as long: steps that short are dominated by the cost of waking the threads, and wasm pays more for that.
- From 2,000 creatures up, the best thread count cut the step time by 2.3–2.7× natively and 2.1–2.7× in wasm.
- Going from 4 to 8 threads (hyper-threads on 4 physical cores) gained 5–23%.
- A battery-powered run earlier the same day gave single-threaded times from 1% faster to 16% slower than these. Its threaded times ranged from 13% faster to 73% slower: multi-threaded timings on this laptop vary much more from run to run.

To reproduce: `wasm/bench.sh` for the table above, and `?bench` (add `&threads=0` or `&gl=0`) in a browser for the frame rates.

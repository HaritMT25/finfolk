# ALIFE 2027 — frozen inputs, protocol v2

The registered inputs of the study (protocol v2, decisions adopted 2026-11-01; frozen after the excluded engineering
pilot). Nothing here is generated at run time; the tools in `tools/alife2027/` read these files.

| file | what |
|---|---|
| `protocol.json` | the whole registered design as data: world, run length, observation schedule, which seeds get which instruments (`subsets`), the branch suite, endpoint definitions, the fixed primary sequence (H1 C1−D1 late clearance → H2 C1−D1 early population AUC → H3 C1−A1 binary no-rescue NI, margin 3/20), the nine Holm secondaries, the bootstrap, the registered `np_companion` extension (minPopulation 0, C1 and D1, first 32 seeds), operations limits |
| `common_l12.json` | the common `--cfg` of every arm (v2 §4, the L12 ecology with its defaults made explicit) |
| `arms.csv` | the nine arms: `driver_arm` (letter = eye / eyeOnly, digit = steerFrame) plus `labelFrame` and `eyeCode`, all installed after the common initialization |
| `main_seeds.txt` | the 128 registered seed IDs, in published order (first 64 = branch / wiring subsets, first 32 = encounters and the companion, first 2 = dense verification) |
| `development_seeds.txt` | seeds 1–12: the historical runs, excluded |
| `engineering_seeds.txt` | 9001–9032: engineering checks and the pilot, excluded |

Regenerate and check the seed list: `python3 tools/alife2027/seeds.py experiments/alife2027/v2/protocol.json`
(reference PCG32 XSH-RR, initstate 20261101, initseq 54 — the analysis RNG, independent of the simulation's).

Workflow: `build.py OUT` (executable + build manifest) → `plan.py protocol.json PLAN.jsonl --phase main` →
`run.sh --plan PLAN.jsonl --root RUNS --build OUT --workers N` (≤ 4, nice 19, resumable) →
`analyze.py report protocol.json RUNS OUTDIR`.

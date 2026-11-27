# M2b3 — Assay-3 diagnosis, round 2: assay 4, partial yaw, geometry and authority

**Finding and recommendation.** D1 alone and D1 plus D2 are the relevant release choices: D2 supplements D1. Recommend the candidate calibration (paired **3**, tail **1.03**, stiff **108**) with **D1 plus D2**, the **D5 measurement amendment**, and the narrow **stage-3 authority correction**. Keep D4's performance requirement unresolved and the stage-3 freeze withheld. **Do not adopt D3 to obtain a pass.** This round does not certify assay 4 or complete G4.

**Is D3 needed for assay 4? No: these measurements do not establish that need.** With sufficient settling, the existing centroid-thrust law meets the explicit **total 1.50±.02 E/s** and **180±2.4 E** bounds and has an essentially level *trajectory*, despite a 1.381° nose-up body. The regulator establishes negative buoyancy, and the fish moves downward relative to its own tilted body; `82*sin(pitch)` is therefore not its measured climb rate. D3 reduces trim and the depth offset, but **does not restore the separate .60 E/s motor anchor exactly**, or zero pitch, or the original 120 u target depth. Neither candidate can be stamped a complete assay-4 pass by borrowing the total tolerance for the motor component. If “level” means absolute zero body pitch or exact target-depth swimming rather than a level path, neither tested variant proves that requirement; D3 alone is not a demonstrated solution to it.

The requested quarter-command checks are ordered, but the denser diagnostic found **six local heading-rate reversals in five body/speed combinations** near fatigue exhaustion. Thus this candidate is **not globally monotonic in command over the prescribed finite 8–10 s window**, and “smooth steering” is not established. Four of the five original candidate turns exercise the new course-rate geometry check and pass; none exercises the steady low-slip heading identity. A planted radius-measurement fault fails all four new checks while leaving the complete simulation traces unchanged.

**Scope and preservation.** Worktree `/home/harit/finfolk/work/trees/m2b1-pr2`; branch `m2b1-pr2`; HEAD `ba6f29c6ee4a04b1ce41b27ab49e81443802968d`. The initial inventory records **5,194 existing entries / 534,032,345 regular-file bytes**, SHA256, sizes, nanosecond mtimes and symlink targets. Git directories were excluded; the worktree's `.git` pointer file was included. Directory symlinks were not followed. The final preservation check compares every inventoried entry and permits new files only beneath `build_m2b1_pr2/diag4/` and at this new report. It also checks branch, HEAD and the scratch source differences. **Zero existing entries changed or disappeared; zero new paths outside those destinations.** The old diagnosis and all `diag3/` evidence remain byte-for-byte and mtime-identical, as do the uncommitted round-3 sources, reference documents, baselines and production modules. This report corrects the old D1/D2 wording without rewriting that preserved file.

Preservation evidence: [inventory_before.json](../build_m2b1_pr2/diag4/inventory_before.json), [preservation_verified.json](../build_m2b1_pr2/diag4/preservation_verified.json). Source-scope and trace evidence: [verification.json](../build_m2b1_pr2/diag4/verification.json).

All compilation and runs used `nice -n 19`, at most two concurrent jobs, single-threaded native code, and bounded toolchain/Node worker settings (at most two compute threads per job). No OpenMP build or browser was started. Tool caches and temporary build files were copied into `diag4/`; existing caches were not changed. No commits, Git mutations, network, baseline edits or production module builds were performed. No other trees, protected studies, noise bank, archives, fable or supervisors were touched. Experiments stopped well below the two CPU-hour cap; see the final resource total below.

**Reproducible scratch setup and diagnostic status.** `candidate/` is an exact copy of `diag3/recommended/{src,tools}`: candidate gain bits `0x40400000`, `0x3f83d70a`, stiff bits `0x42d80000`, and patch 02's `HeldOuter{}` release. All other constants and **`kFrozenThrough=2`** are unchanged. `d3/` differs only at the two forward channel applications in `src/ocean/hydro_step.hpp`: each forward lever is `(loadedLever.x, loadedLever.y, 0)`. The channel function prices work at that same lever. Tail yaw and every paired normal-control channel retain their centroid levers, as does induced damping. `guard/` differs only in the authority table. `measurement/` differs only in the assay measurement; no mechanics, body, calibration or input changes.

The production driver implements only assays 1–3 and refuses assay 4 / `--check-all`. The standalone `diagnostic_settled.cpp` wrapper invokes **1→2→3→4 in that order**, records all results, explicitly labels the run diagnostic, and never emits a frozen header. Both physical variants still pass the preceding **33 assay-1 + 32 assay-2 + 32 amended assay-3 predicates (97/97)**. Subsequent diagnostic stages run even if earlier diagnostic results fail, so every requested measurement remains visible. Native and Wasm use exactly the same wrapper and candidate source copy. The unchanged real driver's freeze and CLI guards remain in the copies.

Harnesses and commands: [diagnostic_settled.cpp](../build_m2b1_pr2/diag4/diagnostic_settled.cpp), [run.py](../build_m2b1_pr2/diag4/run.py), [commands.jsonl](../build_m2b1_pr2/diag4/commands.jsonl). D3 source difference: [d3_forward_lever_WHAT_IF.patch](../build_m2b1_pr2/diag4/d3_forward_lever_WHAT_IF.patch) (scratch what-if only).

**Assay 4: preparation and what is actually being tested.** Neutral body, still water, torus 1920×1080×240, requested speed 82, yaw=dive=forwardBias=0, `geneCost=0`. The metered comoving source supplies **exactly 25 E before each mechanical substep**, using the existing sole-ledger transactions. Measurement lasts **7,500 outer steps / 15,000 substeps / nominal 120 s**; elapsed time uses integer counts, not a drifting float clock. No pose, velocity, gas or regulator clamp is used for free cruise.

A first measurement after the assay-3-style **60 s** preparation shows substantial remaining vertical settling. The second diagnostic uses **600 s** preparation at unchanged requests and constants, then a fresh 120 s measurement. The preparation subsidy is separate from the measured cruise debit. This is not a replacement of a failed prescribed window: the reference texts prescribe a *trimmed* 120 s measurement but no preparation duration. Both preparation choices, including the initial failures, are retained. The 600 s state reaches the binary32 fixed depth/gas plateau described below; that plateau must not be called exact continuous equilibrium.

| Preparation / law | Mean pitch ° | Mean climb u/s | Max \|vertical\| u/s | Depth start→end u | Motor E/s | Total E/s | 120 s debit E | Gas E / 120 s |
|---|---:|---:|---:|---|---:|---:|---:|---:|
| 60 s, centroid | 1.380447021 | 0.013858701 | 0.077602446 | 87.800865→86.139778 | 0.592964190 | 1.493005641 | 179.160676956 | 0.00277184482 |
| 60 s, D3 | 0.110484866 | 0.001963862 | 0.012518697 | 113.419510→113.210327 | 0.598486380 | 1.498460770 | 179.815292358 | 0.00044639655 |
| 600 s, centroid | 1.380749806 | 0.000346618 | 0.000346618 | 86.139778→86.139778 | 0.592894794 | 1.492977142 | 179.157257080 | 1.93609989e-05 |
| 600 s, D3 | 0.110518378 | 0.000432455 | 0.000432455 | 113.210327→113.210327 | 0.598479237 | 1.498460770 | 179.815292358 | 9.03513321e-05 |

The 60 s preparations fail the disclosed level-path screens (`max |vertical|<.01`, drift `<.1`) for **both** laws: centroid drift **−1.661087 u**, D3 **−.209183 u**. These screens borrow the existing static assay's limits as diagnostics; the assay-4 reference itself supplies no numeric body-pitch or depth tolerance. They do not authorize accepting non-level body attitude or a 33.86 u target-depth error. The initial wrapper's per-motor ±.02 screen and its very tight `1e-6 rad` heading screen were exploratory, not specification predicates; their raw logs are preserved. The final wrapper treats the motor anchor separately and uses a `1e-5 rad` numerical straightness screen. No specification tolerance was changed.

**Every assay-4 requirement, after the longer preparation.** The following separates stated requirements from additional diagnostic screens. Basal/maintenance roundoff checks use `2e-6 E/s`; the same screen on motor is **not** a newly authorized motor tolerance. Without a specified component tolerance, a materially non-.60 motor result cannot be promoted to a full partition pass merely because total burn passes.

| Requirement / measurement | Centroid candidate | D3 at unchanged stage-1/2 constants | Finding |
|---|---:|---:|---|
| Complete 120 s / 25 E at every incoming substep | 7,500 / 15,000 | 7,500 / 15,000 | Both pass, all metering/transaction checks |
| Basal .80 E/s | .800000037998 | .800000037998 | Both match within binary32 roundoff |
| Maintenance .10 E/s | .099999997474 | .099999997474 | Both match within binary32 roundoff |
| Motor .60 E/s | **.592894793954** | **.598479236942** | Separate anchor not established: −.007105206 / −.001520763 E/s (−1.18420% / −.25346%) |
| Total 1.50±.02 E/s | **1.49297714233** | **1.49846076965** | Both pass the stated total bound |
| Debit 180±2.4 E | **179.157257080** | **179.815292358** | Both pass the stated debit bound |
| geneCost and gene debit zero | 0 / 0 | 0 / 0 | Both pass |
| Injected cruise subsidy E | 179.157257080 | 179.815292358 | Logged as test subsidy, not ordinary food-free survival |
| Ledger debit minus sum of requested basal/maintenance/motor E | +.009877549 | −.002220331 | Explained binary32 subtraction from 25 E; the actual debits above are used for total/debit acceptance |
| Horizontal speed u/s | 82.005950928 | 81.999694824 | Requested 82 is achieved closely; body-forward speeds are 81.982170105 / 81.999542236 |
| Signed pitch / roll ° | 1.380749806 / .000013664 | .110518378 / 0 | Body is not exactly horizontal; no assay-4 numeric body-angle bound exists |
| Mean / maximum climb u/s | .000346618 / .000346618 | .000432455 / .000432455 | Both pass diagnostic .01 u/s path screen after settling |
| Stored depth drift over 120 s u | 0 | 0 | Both pass diagnostic .1 u screen; quantization caveat below |
| Unrounded integral of vertical velocity u | +.041594212 | +.051894628 | Separately reported; positive means climb |
| Steady depth / requested target depth u | 86.139778 / 120 | 113.210327 / 120 | **Target-depth tracking is not achieved**; no assay-4 target-depth tolerance was specified |
| Horizontal heading change over 120 s | 0 | 0 | Straight path screen passes |
| Dive request / paired control / paid control energy | 0 / 0 / 0 | 0 / 0 / 0 | No hidden dive controller or trim-fin command |
| Regulator active / lambda | Every substep / 1 | Every substep / 1 | Tiny residual vent request remains paid |
| Regulator gas rate (gas-content units/s) | −.00003719329834 | −.00017356872559 | Explained residual; not a “zero regulator” claim |
| Pump energy over 120 s E | **.000019360999** | **.000090351332** | Included in motor total, not added a second time |
| Other trim expenditure | Forward-channel work only; zero control work | Same | Force balance and per-channel accounting below explain the trim |
| Contact / rail activations | 0 / 0 | 0 / 0 | Neither affects cruise |
| Turning additional work charged | Yes | Yes | 10 s unit-yaw tests below |
| Blocked-thrust work charged | Yes | Yes | Exact kinematic zero-motion price test below |
| 3× excess-power charge | Error −6.59e−10 E/substep | Same | Direct peak-work calculation agrees |
| Free fatigue recovery | Fuel 0, fatigue decreases | Same | Direct zero-work calculation agrees; assay 2 also tests full recovery |

**Causal answer about driven trim.** No stated total-burn or 120 s debit predicate fails because of the driven pitch: both pass without D3. The initial level-path screens fail during driven vertical/regulator settling; D3 reduces but does not remove those 60 s preparation failures. After settling, neither path screen fails. The separate free-cruise motor anchor remains below .60 with both laws, even though the restrained reference is exactly .60 at printed precision. Driven load/trim explains why the free state differs from that reference; the D3 comparison narrows the discrepancy but does not isolate all of it to pitch or fix it. Absolute body-level or exact target-depth acceptance is not proved by either variant and must not be inferred from passing burn totals.

The final diagnostic manifests each contain **115/116 successful screens**, with only the explicit motor-anchor roundoff screen failing. This count is not a claim of 115 approved assay-4 predicates: the first 97 are the preceding assays, and the new screens include disclosed diagnostic choices. The actual unamended assay-4 obligations remain the authority. A body-level or target-depth interpretation remains unproved even where the level-path screens pass.

Raw manifests: [candidate_settled_native.json](../build_m2b1_pr2/diag4/candidate_settled_native.json), [d3_settled_native.json](../build_m2b1_pr2/diag4/d3_settled_native.json). Raw logs: [logs/candidate_settled_assays1234.log](../build_m2b1_pr2/diag4/logs/candidate_settled_assays1234.log), [logs/d3_settled_assays1234.log](../build_m2b1_pr2/diag4/logs/d3_settled_assays1234.log). Both preparation choices and force accounting: [calorimetry_summary.json](../build_m2b1_pr2/diag4/calorimetry_summary.json).

**Why the tilted fish does not climb at 1.97 u/s, and where gas/trim work goes.** At settled centroid cruise the water-relative body vertical velocity is **−1.975693703 u/s**, while horizontal speed is 82.00595. Its world velocity therefore does not point along its tilted forward axis. Mean upward force terms are **+2.308976** from thrust, **+2.206061** from passive resistance, and **−4.515017** from weight/buoyancy; their residual is about **2.00e−5**. The regulator has vented gas and established negative buoyancy to balance the vertical forces. D3 has corresponding terms **+.186580**, **+.718979**, **−.905583**, residual −2.46e−5. D3's residual pitch comes from the remaining specified passive force/torque coupling; removing forward `r_z` is not a theorem of zero pitch.

During the 600 s preparation, centroid gas content goes **42.483791→24.941935**, with pump expenditure **.076767428 E**; D3 goes **42.483791→38.661507**, costing **.016949627 E**. These are preparation expenditures, not part of the 120 s cruise anchor. No active dive command is doing the balancing. At cruise the pump and channel costs are explicitly priced through their existing local velocities, efficiencies and shared lambda. There is no unpriced gas/trim work identified here. There *is* a large steady target-depth bias in the centroid case, which the scalar burn total must not hide.

In the 120 s plateau, each candidate depth increment is **2.77295e−6 u**, below half the stored depth ULP (**7.62939e−6 u**). Its attempted gas increment is **−2.97546e−7**, below half the gas ULP (**1.90735e−6**). For D3 the corresponding increments are **3.45964e−6 u** and **−1.38855e−6 gas**, with gas ULP **3.81470e−6**. Every recorded depth and gas value is consequently unchanged although velocity and paid pump request are nonzero. Independent reconstruction of the specified binary32 additions reproduces both rounded-away increments. This explains the tiny plateau pump cost; it is not unexplained missing fuel or a free regulator. The report deliberately distinguishes stored drift, integrated velocity and attempted gas change.

A separate static-reference tow at 82 gives **P=44590.3007812**, `workConversion=1.34558413265e−5`, and **motor exactly .60 E/s at printed precision**, with pump zero and lambda 1, under both laws. Thus the frozen conversion correctly prices its *kinematically restrained reference*. The free swimming fish changes load/trim and moves relative to its body axes. The free motor shortfall is not a missing .60 normalization in the converter. The controlled D3 change narrows that shortfall but leaves about .00152 E/s; it is not justified to assign the entire original deviation to an erroneous pitch lever or to claim D3 solves the partition anchor.

Exact binary32 plateau reconstruction and full trace checks: [verification.json](../build_m2b1_pr2/diag4/verification.json). Additional price oracle: [work_audit.cpp](../build_m2b1_pr2/diag4/work_audit.cpp), [logs/work_audit_candidate.log](../build_m2b1_pr2/diag4/logs/work_audit_candidate.log), [logs/work_audit_d3.log](../build_m2b1_pr2/diag4/logs/work_audit_d3.log).

**Extra-work predicates.** From the settled cruise state, 625 outer steps of unit yaw cost centroid/D3 motor **18.603639010 / 18.603639419 E** over 10 s (about **1.860364 E/s**). Within that total, normal/yaw control channels cost **10.747664936 / 10.733322695 E**, pump **.024862477 / .047692450 E**, and forward channels **7.831111548 / 7.822624300 E**. This is additional, paid work relative to each straight control; gas cost is explained and included. Shared power limiting and burst exhaustion are retained.

The trace wrapper also records an outer-step velocity-restraint diagnostic, which permits motion within each outer step and is not a perfect continuous block. To remove that ambiguity, `work_audit.cpp` separately holds the assay-1 reference pose, load and **zero incoming velocity** for 1,250 successive actuator/motor evaluations; it advances filters and fatigue, supplies the fixed incoming fuel, and reports the equal/opposite restraint force. That exact kinematic block has zero displacement and **18.603452045 E** of motor debit over 10 s for both laws (**1.860345204 E/s**, mean restraint force **356.855104 u-force**). Rowing work remains positive at zero translation. This is a native diagnostic price oracle, not a substituted free-cruise run or a production contact fixture. The extra-work and 3×/free-recovery obligations are exercised; a complete production assay-4 implementation/approval still remains outstanding.

**Assay 2 under D3, with no retuning.** All **32/32 implemented assay-2 predicates pass**, as do all 33 preceding assay-1 predicates. Tow powers at 82 and 108 retain the original bits **0x472e2e4d / 0x47a8c544**; no measured-power or stage-1/2 constant is regenerated or installed. The forward application law nevertheless changed, so numeric passes do not authorize preserving a freeze for a different mechanics law. Independent reference/law-version work would be required before adopting D3.

| D3 assay-2 predicate | Value | Limit / comparator | Result |
|---|---:|---:|---|
| `tow_reference_trim/complete_and_25E_each_incoming_substep` | 3750 | 3750 | PASS |
| `tow_40/drag_oracle` | 3.291741558e-08 | 2e-05 | PASS |
| `tow_40/channel_price_oracle` | 1.044646628e-07 | 2e-05 | PASS |
| `tow_82/drag_oracle` | 8.529148233e-08 | 2e-05 | PASS |
| `tow_82/channel_price_oracle` | 1.297273915e-08 | 2e-05 | PASS |
| `tow_108/drag_oracle` | 6.187250684e-08 | 2e-05 | PASS |
| `tow_108/channel_price_oracle` | 2.658717693e-08 | 2e-05 | PASS |
| `tow_120/drag_oracle` | 3.819348613e-09 | 2e-05 | PASS |
| `tow_120/channel_price_oracle` | 4.195372579e-08 | 2e-05 | PASS |
| `tow_150/drag_oracle` | 6.671523866e-08 | 2e-05 | PASS |
| `tow_150/channel_price_oracle` | 2.065236367e-08 | 2e-05 | PASS |
| `force_capacity/unchanged_150_anchor` | 648.9918213 | 648.9918213 | PASS |
| `free_40/complete_and_25E_each_incoming_substep` | 3750 | 3750 | PASS |
| `free_40/numerical_force_balance` | 7.629394531e-07 | 0.02 | PASS |
| `free_82/complete_and_25E_each_incoming_substep` | 3750 | 3750 | PASS |
| `free_82/numerical_force_balance` | 5.714230421e-06 | 0.02 | PASS |
| `free_108/complete_and_25E_each_incoming_substep` | 3750 | 3750 | PASS |
| `free_108/numerical_force_balance` | 1.116992271e-05 | 0.02 | PASS |
| `free_150/complete_and_25E_each_incoming_substep` | 3750 | 3750 | PASS |
| `free_150/numerical_force_balance` | 0.002171383735 | 0.02 | PASS |
| `sustained/108_within_5_percent` | 108.234507 | 5.4 | PASS |
| `fibre_0/peak_fills_in_2s` | 2.008000135 | 0.016 | PASS |
| `fibre_0/exhausted_limits_to_sustained` | 47525.79297 | 47525.79297 | PASS |
| `fibre_0/recovery_fibre_law` | 14.552001 | 14.54545299 | PASS |
| `fibre_0/fuel_exhaustion` | 0 | 1e-08 | PASS |
| `fibre_1/peak_fills_in_2s` | 2.008000135 | 0.016 | PASS |
| `fibre_1/exhausted_limits_to_sustained` | 86410.53125 | 86410.53125 | PASS |
| `fibre_1/recovery_fibre_law` | 4.008000374 | 4 | PASS |
| `fibre_1/fuel_exhaustion` | 0 | 1e-08 | PASS |
| `fibre_2/all_red_zero_capacity` | 0 | 0 | PASS |
| `fibre_2/fuel_exhaustion` | 0 | 1e-08 | PASS |
| `shared_lambda/opposed_channels_and_pump` | 0.9686217904 | 1 | PASS |

D3 free-drive terminal forward speeds at requests 40/82/108/150 are **39.9999695 / 81.9995314 / 107.9987913 / 108.2345070**. Free-run 82 pitch after 60 s is .11014° rather than 1.37871°; that earlier state still has residual depth settling, as the assay-4 preparation comparison shows. Printed peak at request 150 is 142.91214. The matched incoming-pose tow is the same reference power test, not evidence that the free driven trim is exactly upright.

**Partial yaw: requested results.** For each body and request, all commands start from the *same cloned prepared state*. At 40/82 the preparation is the unchanged 60 s straight run and measurement is outer **[500,625)** of the 625-step turn (**8–10 s**). For 120, each body receives the existing assay's recovered kinematic 120 initialization with consistent tail drive; turn length is **62 outer steps / .992 s**, measurement **[31,62)** (**.496–.992 s**). These are finite bursts, not sustained-120 claims; the manoeuvrer slows especially strongly. Sideslip columns give the unchanged assay's mean and maximum absolute body-plane angle over the fit window. `lambda_min` is over the complete turn. Radius is the actual recorded-position circle fit, never U/heading substituted into the fit.

| Body | Request | Yaw | Heading rad/s | Actual horizontal u/s | Radius u | Slip mean/max ° | Lambda min | Course-radius error % / eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| neutral | 40 | 0.25 | 2.396317063 | 39.177561 | 16.350003 | 50.1882/50.1894 | 1.000000 | 0.001533 / yes |
| neutral | 40 | 0.50 | 3.481218697 | 23.862531 | 6.855506 | 69.0150/69.0202 | 0.496219 | 0.003880 / yes |
| neutral | 40 | 0.75 | 4.050081868 | 16.547482 | 4.086185 | 79.3804/79.3851 | 0.356483 | 0.001171 / yes |
| neutral | 82 | 0.25 | 0.685527472 | 83.040438 | 121.135086 | 17.6796/17.6797 | 1.000000 | 0.000358 / yes |
| neutral | 82 | 0.50 | 0.984146633 | 70.089805 | 71.220641 | 23.9683/23.9689 | 0.499241 | 0.000707 / yes |
| neutral | 82 | 0.75 | 1.484097134 | 58.579406 | 39.472104 | 32.9576/32.9578 | 0.330314 | 0.000499 / yes |
| neutral | 120 | 0.25 | 0.330040475 | 120.419379 | 390.290135 | 8.5293/8.7017 | 1.000000 | 0.846489 / yes |
| neutral | 120 | 0.50 | 0.608238652 | 111.747392 | 191.842322 | 13.5955/13.8186 | 0.706451 | 0.920893 / yes |
| neutral | 120 | 0.75 | 0.873948861 | 104.657445 | 126.244041 | 17.6004/18.0581 | 0.554668 | 1.138064 / no |
| manoeuvrer | 40 | 0.25 | 0.985901320 | 42.027354 | 42.632842 | 42.7711/42.7741 | 0.599987 | 0.000783 / yes |
| manoeuvrer | 40 | 0.50 | 1.994631332 | 36.439919 | 18.270007 | 61.2163/61.2167 | 0.344173 | 0.000539 / yes |
| manoeuvrer | 40 | 0.75 | 4.560951917 | 18.559303 | 4.070384 | 89.2604/89.3022 | 0.243952 | 0.004132 / yes |
| manoeuvrer | 82 | 0.25 | 0.268031210 | 44.808943 | 167.243616 | 21.6929/21.6976 | 0.326450 | 0.001434 / yes |
| manoeuvrer | 82 | 0.50 | 0.679955531 | 43.355672 | 63.776967 | 35.3546/35.3618 | 0.265170 | 0.002470 / yes |
| manoeuvrer | 82 | 0.75 | 1.143097505 | 41.424771 | 36.244746 | 46.1408/46.1482 | 0.222388 | 0.000936 / yes |
| manoeuvrer | 120 | 0.25 | 0.456787332 | 58.979538 | 142.756652 | 23.3005/23.6383 | 0.300726 | 2.036086 / yes |
| manoeuvrer | 120 | 0.50 | 1.084241443 | 56.850542 | 55.088144 | 37.4933/37.9054 | 0.239883 | 1.305917 / yes |
| manoeuvrer | 120 | 0.75 | 1.744008943 | 54.080986 | 32.708801 | 48.2020/48.6729 | 0.199517 | 1.356316 / yes |
| cruiser | 40 | 0.25 | 1.135410197 | 40.185589 | 35.390227 | 28.9457/28.9492 | 1.000000 | 0.001154 / yes |
| cruiser | 40 | 0.50 | 1.732622132 | 36.002139 | 20.767840 | 38.2790/38.2928 | 0.718732 | 0.059786 / yes |
| cruiser | 40 | 0.75 | 1.879769579 | 30.228251 | 16.080312 | 43.3494/43.3578 | 0.454519 | 0.000473 / yes |
| cruiser | 82 | 0.25 | 0.460318412 | 82.074030 | 178.274693 | 10.7608/10.7618 | 1.000000 | 0.000376 / yes |
| cruiser | 82 | 0.50 | 0.731370132 | 76.831769 | 105.013108 | 15.3101/15.3125 | 0.668475 | 0.009143 / yes |
| cruiser | 82 | 0.75 | 0.861258862 | 70.355771 | 81.681728 | 17.8992/17.9037 | 0.444952 | 0.000387 / yes |
| cruiser | 120 | 0.25 | 0.234481635 | 119.933088 | 662.333417 | 4.1472/4.7911 | 1.000000 | 1.914819 / no |
| cruiser | 120 | 0.50 | 0.502137234 | 119.581063 | 290.845077 | 7.8044/8.9093 | 1.000000 | 1.905554 / yes |
| cruiser | 120 | 0.75 | 0.705650380 | 117.386309 | 189.815370 | 10.6077/11.5706 | 0.828108 | 1.657346 / no |

All nine groups are ordered at **0, .25, .5, .75, 1**. That is a spot-check result, not global monotonicity or smoothness. The **369-turn sweep** uses commands 0…1 in increments .025 (41 per body/request), with the same initial states/windows. It has no sampled reversals in the three finite-120 groups or manoeuvrer-82. The remaining five groups contain these six reversals:

| Body / request | Command increase | Heading before→after rad/s |
|---|---|---:|
| neutral / 40 | 0.300→0.325 | 2.966215208→2.799334538 |
| neutral / 82 | 0.275→0.300 | 0.780272522→0.669082359 |
| manoeuvrer / 40 | 0.150→0.175 | 0.708770534→0.705377354 |
| cruiser / 40 | 0.450→0.475 | 1.882826193→1.714816217 |
| cruiser / 82 | 0.400→0.425 | 0.804302915→0.721204902 |
| cruiser / 82 | 0.425→0.450 | 0.721204902→0.703725326 |

A targeted native replay of all 11 distinct commands continues the turns to 60 s and compares **[8,10)** with **[58,60)**. Every listed reversed pair becomes ordered in the latter window. For example neutral-40 .300/.325 changes from **2.966215/2.799335** to **2.686450/2.798516 rad/s**; fatigue exhausts at **11.456/7.336 s**. Neutral-82 .275/.300 exhausts at **9.968/7.360 s**. Cruiser-82 .400/.425/.450 exhausts at **11.096/8.376/6.768 s**, and its late heading rates are **.677345/.691172/.704900**. This directly links the observed finite-window reversals to different positions in the burst-to-sustained transition. It does not change or erase the required early-window results, prove monotonicity everywhere after settling, or prove a mathematical discontinuity in the actuator law. Speed loss, slip and lambda remain strongly nonlinear. The maximum sampled local heading increment is about **.45564 rad/s for .025 command**, manoeuvrer-40 .600→.625; a blanket smooth-response claim is unwarranted.

Full precision requested endpoints and zero/unit controls: [partial_summary.json](../build_m2b1_pr2/diag4/partial_summary.json), [logs/candidate_partial.log](../build_m2b1_pr2/diag4/logs/candidate_partial.log). Dense evidence: [dense_summary.json](../build_m2b1_pr2/diag4/dense_summary.json), [dense_reversals.json](../build_m2b1_pr2/diag4/dense_reversals.json), [logs/dense_partial.log](../build_m2b1_pr2/diag4/logs/dense_partial.log). Transition replay: [transition.cpp](../build_m2b1_pr2/diag4/transition.cpp), [logs/transition_replay.log](../build_m2b1_pr2/diag4/logs/transition_replay.log).

**D5: course geometry and the restricted heading identity.** The scratch measurement unwraps horizontal velocity course independently of heading and fits the original recorded positions using the original double circle fit. Mean horizontal U is the arithmetic sample mean. Mean course rate is total unwrapped course rotation divided by `(N−1)*h` between the first and last fit samples. Speed range is `(max U−min U)/mean U`. All new arithmetic is measurement-only; the simulation trace is unchanged.

The course check is eligible at **absolute unwrapped course rotation ≥5° and speed range ≤2%**, irrespective of slip. It tests `abs(Rfit−U/abs(courseRate))/(U/abs(courseRate))≤5%`. The heading identity is eligible only in that domain **and** maximum absolute sideslip <5° **and** `abs(meanCourseRate−meanHeadingRate)≤.02*abs(meanHeadingRate)`. It independently tests the analogous heading prediction within 5%. These conditions are not a proof of circularity; the empirical fit check is still required. No fallback substitutes a predicted radius into the measured fit.

| Original candidate turn | Course arc ° | Speed range % | Course rate rad/s | Rfit / U/\|course rate\| | Course error % | Heading error % | Course / heading eligible |
|---|---:|---:|---:|---:|---:|---:|---|
| steer_neutral_40 | 499.178262 | 0.002356 | 4.373646491 | 2.923796 / 2.923665 | 0.004501 | 0.015603 | yes / no |
| steer_neutral_82 | 296.679927 | 0.049574 | 2.599418330 | 14.329165 / 14.328643 | 0.003640 | 0.001489 | yes / no |
| steer_neutral_120 | 29.214686 | 5.684871 | 1.044861541 | 93.250996 / 94.462294 | 1.282308 | 7.224764 | no / no |
| steer_manoeuvrer_40 | 614.281252 | 0.061349 | 5.382143506 | 2.476516 / 2.476356 | 0.006450 | 0.032415 | yes / no |
| steer_cruiser_40 | 228.412694 | 0.008831 | 2.001281812 | 12.689341 / 12.689226 | 0.000906 | 0.002894 | yes / no |

**Counts:** original five candidate turns: **4 course eligible / 0 heading eligible**, all four course errors ≤.006450%. Candidate finite-120 is ineligible because its speed range is **5.68487%**, despite 29.21469° of course rotation; its reported course error is 1.28231% and heading error 7.22476%. **Zero heading eligibility means not exercised, not passed.**

The 27 specifically requested partial commands add a view of the same calibration: **24 course eligible / 0 heading eligible**, with all eligible errors in the table above below 5%. Ineligible requested cases are neutral-120 yaw .75 (speed range), cruiser-120 yaw .25 (**4.96602°** course arc), and cruiser-120 yaw .75 (speed range). Including the zero/unit controls, the 45-case diagnostic has **30 course eligible / 0 heading eligible**; equivalently 30 of its 36 nonzero turns qualify. The original five overlap this set and must not be added to those counts as distinct turns. The largest eligible error is **2.036086%**, manoeuvrer finite-120 yaw .25; all eligible geometry errors are printed individually in the JSON. Cruiser finite-120 yaw .25 has slip only **4.79106°**, yet heading-radius error **29.4931%** and course/heading-rate difference **24.254%**: a concrete example of why a small slip *angle* alone does not justify the heading identity.

**Planted measurement fault:** compile the same scratch measurement with `PLANT_RADIUS_FAULT`, multiplying only the *returned fit radius* by **1.25**. All bodies, forces, constants, positions, velocities, source/debit transactions and receipt hashes stay unchanged. The four eligible original course checks fail with errors **25.005626%, 25.004550%, 25.008062%, 25.001133%** for neutral-40, neutral-82, manoeuvrer-40 and cruiser-40. CLI exit is **1**; all other original numerical predicates still pass. With the fault disabled, the D5 driver passes **101/101** (the original 97 plus four exercised course checks). Under the old slip-only conditional check the same fault would receive no radius check for any of these five high-slip cases. This demonstrates the new check's added coverage, not just a recalculated printed prediction.

Measurement-only source patch (diagnostic, including the disabled fault hook): [05_d5_measurement_ONLY.patch](../build_m2b1_pr2/diag4/05_d5_measurement_ONLY.patch). Measurements/counts: [d5_candidate_summary.json](../build_m2b1_pr2/diag4/d5_candidate_summary.json), [d5_partial_summary.json](../build_m2b1_pr2/diag4/d5_partial_summary.json), [d5_fault_summary.json](../build_m2b1_pr2/diag4/d5_fault_summary.json). Actual driver results: [d5_native.json](../build_m2b1_pr2/diag4/d5_native.json), [d5_fault_native.json](../build_m2b1_pr2/diag4/d5_fault_native.json).

**Stage-3 authority correction: unapplied patch 04.** The existing table at `tools/ocean_hydro_calibration_io.hpp:24–27` incorrectly permits heave gain, pitch gain and paired induced efficiency as stage-3 overrides. The narrow scratch fix gives those three constants **stage 0 (fixed law, no assay tuning authority)**, rather than silently assigning new stage-2 authority. The existing `c.stage != stage+1` check consequently refuses them. Only `kPairedYawGain`, `kTailYawGain` and `kTailStiffSpeed` remain stage 3. No emitted constant bits, order, law arithmetic or digest is changed by this guard correction.

Required deliverable: [04_stage3_authority_guard.patch](../build_m2b1_pr2/diag4/04_stage3_authority_guard.patch). It passes `patch --dry-run -p1` against the copied unchanged candidate, and remains **unapplied to all existing worktree files**. Only `guard/` contains the prospective source effect.

| CLI refusal, with `--candidate --set NAME=0xBITS --emit-calibration scratch.hpp` | Unchanged bits | Changed bits | Outcome |
|---|---|---|---|
| `kHeaveGain` | 3f800000 | 40000000 | Both exit 2, no output header |
| `kPitchGain` | 3f800000 | 40000000 | Both exit 2, no output header |
| `kPairedInducedEfficiency` | 3f400000 | 40000000 | Both exit 2, no output header |

All six print `constant belongs to a different or frozen stage`. A no-override emission and an emission explicitly setting all **three authorized constants to their unchanged exact bits** both exit 0 and reproduce the candidate header **byte-for-byte**, frozen-through still 2. The rebuilt guard driver reruns 1→2→3 with that unchanged authorized candidate: **97/97**, and its full **116,066-row / 31,077,176-byte** trace, every result, and every window chain equal the preserved diag3 candidate. The D5 good/fault traces equal those same bytes. Thus guard enforcement is a behavior-preserving authority fix for this candidate, not new calibration permission or an acceptance amendment.

CLI assertions: [guard_checks.py](../build_m2b1_pr2/diag4/guard_checks.py), [guard_cli_verified.json](../build_m2b1_pr2/diag4/guard_cli_verified.json). No-change rerun: [guard_unchanged.json](../build_m2b1_pr2/diag4/guard_unchanged.json), [logs/guard_unchanged_assays123.log](../build_m2b1_pr2/diag4/logs/guard_unchanged_assays123.log).

**Native/Wasm comparison, only for the candidate assay-4 sequence.** Native `g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN`; Wasm uses the same options plus SIMD, Node raw FS, memory growth, 8 MiB stack and one linker thread. Emscripten's private copied cache, `EMCC_CORES=1`, `BINARYEN_CORES=1`, and Node's one-worker/single-threaded options are recorded in the command log. No D3, partial-yaw, guard, transition, price-oracle or D5 Wasm experiment was run.

The candidate 1→2→3→4 sequences, including 600 s preparation and the traced extra-turn/restraint diagnostic, have **207,316 data rows / 55,905,074 bytes**, SHA256 **69715b839824127db00bed3ccffc6f16e06f47c0af9910ab3dd9dc90a4f6f365**. Full files are byte-identical; manifests are equal except for the declared `target`. All 97 preceding results/chains and their trace prefix equal the preserved diag3 recommended candidate. Both executables exit **1** for the **same motor-anchor diagnostic failure**; parity does not convert that failure into acceptance. Constant/reference/coefficient digests remain **66b5b28e6e06a84d / 34f5953354409576 / 3e8bfae4938384af**. Cruise receipt chain is **5593ef9ae7595602**.

Parity proof: [verification.json](../build_m2b1_pr2/diag4/verification.json), [candidate_settled_native.json](../build_m2b1_pr2/diag4/candidate_settled_native.json), [candidate_settled_wasm.json](../build_m2b1_pr2/diag4/candidate_settled_wasm.json). Raw traces: [candidate_settled_native.csv](../build_m2b1_pr2/diag4/candidate_settled_native.csv), [candidate_settled_wasm.csv](../build_m2b1_pr2/diag4/candidate_settled_wasm.csv).

**D1–D5 rewritten consistently, with exact proposed amendment text.** These are owner decisions; this diagnostic authorizes none of them. The choices are **D1 alone versus D1 plus D2**, with **D3 an optional mechanics-law addition** only if separately justified, and **D4/D5 independent performance/measurement additions**. D2 never replaces D1. D3 never waives D1, D2, D4 or assay 4. The original stage-3 and earlier freeze authority remains in force until explicitly amended.

**D1 — command-release upright recovery. Recommended as the base release check.** Retain patch 02 and the matching patch 03 wording already preserved under diag3; the candidate's 97 existing predicates remain passing. Exact replacement release sentence in plan :1035 and brief :664:

> For the righting release, set speed, yaw, dive and forward-bias requests to zero for 625 outer steps; preserve filtered tail state and keep the paid gas regulator and passive braking active. Roll/pitch must return within 1° of upright after those 10 s, including after the finite-120 burst.

This tests command release. It does not prove upright driven trim or assay-4 calorimetry. D1 alone is the smaller acceptance definition; D1 plus D2 retains useful driven-recovery coverage.

**D2 — add driven yaw-release relative to a matched control. Recommended *in addition to D1*.** The measured absolute pitch is a real driven trim, not a sign/righting bug; the new assay-4 force/price accounting reinforces the need to report it rather than silently treating it as upright. Exact additional paragraph, following D1 in both assay-3 descriptions:

> In addition to the command-release upright check, run a separate driven yaw-release diagnostic from the same post-turn state: set yaw, dive and forward-bias requests to zero, retain the pre-turn speed request, and use 82 after the finite-120 burst. Keep all filters, regulator, passive brake and fuel pricing unchanged. Compare signed roll and pitch after 625 outer steps with the same body's 60 s, metered-25 E, no-yaw/no-dive straight control at that retained request, after aligning horizontal headings. Require each angle within 1° of its matched control. Report the control's absolute roll/pitch, actual speed, depth, vertical velocity, gas expenditure and remaining settling separately. Passing this relative-trim diagnostic does not replace D1's absolute upright requirement or establish assay-4 acceptance.

D2's exact relative-control predicate is still an **unimplemented/unproved amendment**, not another passing count in this report. The driven controls and their activity were measured; the proposed matched-angle release check itself was not installed or certified. If the owner chooses D1 alone, disclose the missing driven-recovery coverage explicitly.

**D3 — optional COM-height forward line: tested what-if, not recommended for adoption.** Compare **D1 plus D2** with **D1 plus D2 plus D3**, not D3 instead of either release check. It cuts steady pitch to .1105° and preserves the 32 numeric assay-2 predicates at unchanged constants, but both total/debit bounds already pass without it. It does not eliminate passive pitch, target-depth bias or the .60 motor mismatch. It changes the explicitly specified law and local-work points. Exact amendment *only if the owner separately elects it*:

> Forward caudal and paired-rowing forces remain along body -x with the prescribed shares, but use application lever (loadedLever.x, loadedLever.y, 0) relative to loaded material COM. Price each forward channel at that same application point. Caudal yaw and paired normal-control channels, including their local work and induced damping, retain the full loaded fin-centroid levers. This replaces only the forward-point rule in plan 618–623. Version the actuator mechanics law and update the independent reference. Reopen affected stage-1/2 trim and power acceptance before any freeze is reused; rebuild and rerun assays 1→2→3→4 and all affected reference/parity gates. This change waives no release, level-cruise, component-energy, total-energy or performance requirement.

No righting gain or other earlier constant was tuned. There is no recommendation to reopen righting simply to cancel the observed trim. **D3 is neither demonstrated necessary for the explicit assay-4 total/debit/level-path bounds nor sufficient for every literal assay-4 interpretation.** The unchanged required motor partition remains a handoff issue, not permission to redesign thrust for a pass.

**D4 — retain the actual-speed/radius goal and require an explicit quantitative owner decision before freezing.** This is an addition to whichever release set is chosen. Partial yaw preserves the original warning: requesting 82 is not achieving an 82-speed turn, and satisfying heading alone does not establish radius near 31. The recommended unit-yaw neutral case still measures **37.246138 u/s**, **2.599362 rad/s**, **14.329165 u radius** and **53.106281° maximum slip**. Exact proposed strong amendment:

> The neutral 82 step-steer acceptance is evaluated over the prescribed settled fit window using measured horizontal speed: mean speed 82±2%, heading rate 2.60±.15 rad/s, fitted recorded-position radius 31±5%, and maximum absolute sideslip <5°. These are conjunctive predicates, additional to the selected release checks and D5's geometry checks. Requested speed must never substitute for measured speed. A candidate that meets heading by slowing or slipping outside these bounds is not a complete assay-3 pass. Report any required non-yaw law change and reopen its affected earlier freezes before recalibration.

The tested candidate **fails this stronger performance definition**. This report recommends keeping that requirement open, not declaring the goal met or silently making it report-only. If the owner instead explicitly elects the weaker PR-2 scope, exact alternative clarification is:

> The 40/82/120 labels name pre-turn straight-speed requests, and 120 names a finite burst. Always report actual turn speed, recorded-position radius and sideslip. Radius near 31 is a non-gating design goal for PR 2; the neutral-82 numeric heading target remains 2.60±.15 rad/s. Large-slip, reduced-speed turns may satisfy that numeric target and are not evidence of the 82-speed/radius-31 goal. Preserve the selected release checks and D5's separately eligible geometry checks.

Neither wording is installed. The observed finite-window command reversals and fatigue transitions must also remain reported; no smooth/monotonic whole-command-range claim follows from the unit-yaw predicate.

**D5 — two independent geometry checks with explicit coverage. Recommended addition to D1, or D1 plus D2.** Exact replacement geometry paragraph in plan :1035–1036 / :1062 and brief :664:

> Fit the horizontal circle radius from actual torus-unwrapped recorded positions using a measurement-only fit; never substitute a speed/rate prediction for the fitted radius. Independently unwrap horizontal velocity course and horizontal forward heading over the same fit samples. Report mean horizontal speed U, speed range divided by mean U, absolute unwrapped course rotation, mean course rate, mean heading rate, their difference, sideslip, and both predicted radii and relative errors for every turn.
>
> For every resolved turn with absolute unwrapped course rotation at least 5° and speed range at most 2% of mean U, require the fitted radius to agree with U/|mean course rate| within 5%, regardless of sideslip. This course-rate check exercises position-fit geometry independently of body heading.
>
> Apply the separate fitted-radius versus U/|mean heading rate| identity only when the same resolution/speed conditions hold, maximum absolute sideslip is below 5°, and |mean course rate−mean heading rate| is at most 2% of |mean heading rate|. Require agreement within 5%. Preserve the finite-120 burst window; do not replace it with steady swimming.
>
> Print each check's eligibility, exclusion reason and total eligible count. An ineligible check is not exercised, not passed. Report its measurements without asserting the identity. Zero steady low-slip eligible cases require explicit owner acceptance of that coverage or an additional fixed eligible fixture before stage-3 freezing. Include a planted radius-measurement fault rejected by the course check, while unchanged simulation traces prove that the fault and the measurement amendment do not alter mechanics.

The scratch evidence establishes 4 original course checks and 30 course checks in the expanded fixed-command set. It **does not close the zero-coverage heading check**. No positions were promoted to double in simulation, no law/ABI was changed, no threshold or original failed manifest was overwritten, and no saved stage-3 failure was reclassified by changing its record.

**Exact authority amendment, separate from D1–D5.** Use unapplied patch 04, with the following accompanying text:

> Stage 3 may change only kPairedYawGain, kTailYawGain and kTailStiffSpeed. kHeaveGain, kPitchGain and kPairedInducedEfficiency remain fixed by the declared law and are not stage-3 calibration variables. An emitter accepting an override does not grant tuning authority. Refuse both changed and no-op --set requests for those extra constants before opening the output header. Preserve emitted values, ordering, digests and frozen-through stage for an unchanged authorized candidate, and prove its rerun unchanged.

**Recommended set and remaining acceptance work.** Take the exact yaw calibration as a candidate, retain **D1**, add **D2** as a separately implemented/reviewed driven-recovery test, adopt **D5's two checks**, and apply the authority correction after review. Keep **D3 out** of that recommended set. Keep **D4 unresolved and stage 3 unfrozen** until the owner decides the performance gate and low-slip coverage. Before a complete assay-4 claim, implement the actual driver stage, settle and disclose the free-cruise state, and resolve/verify the separate motor partition at that state under the existing authority; do not hide the shortfall inside the total tolerance. Likewise do not call a level trajectory at depth 86.14 an upright target-depth trim. No owner acceptance of a new tolerance, law, freeze or goal downgrade is implied here.

This is diagnosis, not production readiness. D2 remains unproved, the strong D4 goal fails, steady low-slip geometry coverage is zero, and neither full prescribed calorimetry partition is certified. The independent reference was not rewritten to the D3 law, and production G4–G12 / Wasm module freshness / full Ocean parity / integration release work was not run. No frozen stage was advanced, no baseline changed, and no deployment, merge or commit was made.

**Evidence inventory and resources.** The evidence directory contains the four source copies; the resource-limited command runner and command log; the 60 s and 600 s native diagnostic sources/binaries/logs/manifests/traces; only the candidate's 600 s Wasm executable and comparison trace; partial and dense command measurements; the targeted fatigue-transition replay; the exact blocked/tow price oracle; D5 good/fault drivers; guard CLI refusals and no-change rerun; unapplied patch 04, the diagnostic D3/D5 diffs; structured summaries, verification scripts and preservation records. All links above are local artifacts. Generated experiment binaries are scratch build outputs, not production modules.

Logged experiment/build/analysis child CPU, conservatively summing nested receipts: **285.735 s (4.762 CPU-minutes)** before report/preservation I/O, under **0.1 CPU-hours** overall. Maximum concurrently active jobs was two. Experiment commands/return codes are in [commands.jsonl](../build_m2b1_pr2/diag4/commands.jsonl); intentional nonzero exits are retained rather than disguised as acceptance. The final preservation check confirms the initial 5,194 entries and all existing worktree content remain unchanged.

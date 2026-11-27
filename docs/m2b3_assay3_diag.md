# M2b3 — Assay-3 diagnosis, preserved round-3 worktree

**Finding.** Authorized yaw calibration can meet the implemented heading and body-ordering predicates together. It does not remove the specified forward-thrust pitching moment. None of the 143 searched points passes the original assay: all fail the same three driven-release checks. The recommended scratch calibration is paired yaw **3**, tail yaw **1.03** (binary32), stiffening speed **108**. With an explicitly proposed full-command release it passes **97/97 existing predicates**, native and Wasm, with byte-identical traces. With the original release it passes **94/97**. This is conditional diagnostic evidence, not approval of an amended assay or a stage-3 freeze.

**Material limit.** The passing numerical candidate turns at actual horizontal speed **37.2461**, heading rate **2.59936**, radius **14.3292**, and maximum sideslip **53.1063°** in the neutral “82” case. It does **not** demonstrate the plan/brief's “radius near 31” goal. No candidate turn qualifies for the conditional <5° sideslip radius check. Calling this a demonstrated low-slip or actual-82 turn would be false. OWNER DECISIONS D1 and D4 below remain necessary before accepting these results as the intended assay, and D5 identifies the geometry-definition problem. The original stop remains justified.

**Scope and preservation.** Worktree `/home/harit/finfolk/work/trees/m2b1-pr2`, branch `m2b1-pr2`, HEAD `ba6f29c6ee4a04b1ce41b27ab49e81443802968d`. The inventory was made before creating the diagnostic directory: [inventory_before.json](../build_m2b1_pr2/diag3/inventory_before.json) records **3,530 pre-existing file entries / 361,484,777 regular-file bytes**, SHA256, size, mtime and file-symlink targets. Directory symlinks were not followed; Git directories were excluded, while the worktree's `.git` pointer file was inventoried. The final [preservation_verified.json](../build_m2b1_pr2/diag3/preservation_verified.json) checks every recorded entry, copied source identity, new-file destinations, HEAD and branch: **zero changed/missing entries and zero new paths outside the authorized destinations**. This includes all earlier diagnoses, raw round-3 evidence, baselines and production modules. Only this new report and files beneath `build_m2b1_pr2/diag3/` were written. No commits, Git mutations, network, production rebuilds, baseline changes, browser runs, other trees, studies/noise-bank operations or supervisors were used.

**Authority, constants and freezes.** All citations below refer to the current uncommitted sources and the supplied local reference texts, whose bytes were preserved.

Plan `docs/_ref/m2b1_pr2_plan_codex.md:1066–1075`:

> Assay 1 freezes material normalization/reference trim, gravity, pressure law, righting, regulator, friction and contact tolerances.
>
> Assay 2 freezes measured drag, loading/efficiency, Uact/Urow, measured motor powers at 82 and 108, tail response and capacity law.
>
> Assay 3 freezes yaw gains and stiffening.
>
> Use starting constants first. If calibration is needed, change only the constants assigned to that assay; emit a new candidate header, rebuild, and rerun that assay plus all preceding assays. Reject any candidate that invalidates an earlier freeze.

Brief `docs/_ref/m2b1_brief_codex.md:664`, assay-3 frozen constants:

> Paired-fin yaw authority, k_tail_yaw, Ustiff

The assay rows are plan `:1033–1036` and brief `:664`; the starting constants are plan `:150–152`, brief `:357–380`. The three authorized variables are:

| Constant, current source | Starting value | Meaning / derivation | Search bounds, chosen for this experiment |
|---|---:|---|---|
| `kPairedYawGain`, `src/ocean/hydro_calibration.hpp:24` | 1 | Dimensionless multiplier of `-yaw*(lever×normal).z/refLength`, followed by [-1,1] command clamp; plan :638–654, brief :370–380. | .01–30 |
| `kTailYawGain`, same :25 | .25 | Dimensionless lateral-force coefficient multiplying dynamic/rowing pressure and caudal area; plan :625–634, brief :357–365. | .01–4 |
| `kTailStiffSpeed`, same :26 | 108 u/s | Speed in `1+(U/Ustiff)^2`, initially the sustained reference speed; changes the speed dependence, not the already-frozen tail response time. | 27–432 |

Neither document supplies a numerical tuning interval. These are **search bounds, not owner-authorized physical ranges**. The tool requires positive finite binary32 (`tools/ocean_hydro_calibration_io.hpp:41–44`); final constants use exact bits. No other constant was searched. In particular, righting, forward shares, power/efficiency, tail tau, controller tau and the rail stayed fixed.

There is a separate **(b) authority-enforcement defect**, not the cause of the observed mechanics failures: `tools/ocean_hydro_calibration_io.hpp:24–27` also assigns heave gain, pitch gain and paired induced efficiency to stage 3. A permissive emitter does not extend the plan's authority. They were left unchanged. A later guard correction should make those unavailable to stage-3 `--set`; it needs CLI refusal checks and a no-state-change rerun, not new tuning permission.

Plan `:1075` also says:

> If an assay cannot meet its target without changing the law, stop and report the discrepancy; do not stamp a frozen manifest.

`kFrozenThrough=2` in the original **and the tested scratch candidate** remains 2. The separately emitted [proposed_stage3.hpp](../build_m2b1_pr2/diag3/proposed_stage3.hpp) is an uninstalled illustration from the amended-stimulus run, not approved freeze evidence.

**Every original failing predicate.** Values are printed measurements, not distances from the target. “—” means that candidate did not fail this predicate. Raw sources are the three `round3/logs/gate04_assay3_{starting,paired,tail}.log` files and their `assays123.*.json` manifests.

| Predicate | Starting 1/.25 | Paired-heavy 20/.01 | Tail-heavy 1/2 | Root-cause class |
|---|---:|---:|---:|---|
| `steer_neutral_82/yaw_2.60_plus_minus_.15` | 0.656404965 | -0.0587430133 | 4.31116521 | (a): coupled yaw calibration; gain, power limit and sideslip, not a heading-sign bug. |
| `steer_neutral_82/release_righting_1_degree` | 1.37984276 | 1.37045068 | 1.36945077 | (c): retained 82 drive has a 1.379° driven equilibrium. |
| `steer_neutral_120/release_righting_1_degree` | 1.36128133 | 1.35883533 | 1.35825915 | (c): release changes 120 to driven 82; the same equilibrium remains. |
| `steer_manoeuvrer_40/release_righting_1_degree` | 5.29398271 | 5.29831153 | 5.29176143 | (c): retained 40 drive has a 5.298° driven equilibrium. |
| `body_ordering/manoeuvrer_neutral_cruiser` | 36.4643633 | — | 6.45044722 | (a): relative paired/tail authority on the prescribed fixed bodies. |
| `body_ordering/cruiser_over_manoeuvrer_at_least_3` | 0.87593099 | — | — | (a): same relative-authority calibration; independently checked ratio. |
| `steer_neutral_120/low_slip_fitted_radius` | — | 0.098946648 | — | (c), with (a) exposure: transient sideslip makes U/heading-rate an invalid curvature identity. |

This is the complete original set: **seven distinct predicates**, six/five/five failures out of 97/99/97 checks. The larger search found one additional distinct predicate:

| Additional predicate | Point (paired, tail, stiff) | Failure | Classification |
|---|---|---|---|
| `steer_cruiser_40/low_slip_fitted_radius` | (3,.01,27) | .356268684 > .05 | (c): an almost straight, poorly resolved stored-position arc; details below. |

Predicate-to-source and authority mapping, including all seven original identifiers:

| Predicate group | Implementation | Plan / brief |
|---|---|---|
| Neutral-82 heading target | `tools/ocean_hydro_assay.cpp:158–170`; actuator laws `src/ocean/hydro_step.hpp:118–133` | plan :1033, :1062, :1068–1071; brief :664, :357–380 |
| Neutral-82 release, neutral-120 release, manoeuvrer-40 release | assay :175–180; forward points/shares `hydro_step.hpp:114–126`; righting :185–202 | plan :618–623, :748–780, :1035, :1066–1067; brief :270–289, :351–368, :664 |
| Strict radius ordering and ratio ≥3 | assay :174, :183–184; fixed bodies `tools/ocean_hydro_harness.hpp:113–121` | plan :1034, :1040–1060; brief :664 |
| Neutral-120 and additional cruiser-40 low-slip radius | assay :24–76, :150–173; stored COM advance `hydro_step.hpp:277` | plan :1035–1036, :1062; brief :664, :314–319 |

All completion/metering, finite-measurement and rail checks in the original trials passed. All 65 preceding-assay predicates passed. No unreported numeric 90°-response threshold exists; -1 in a finite window means “not observed,” not an extra failed check. No numeric “near 31” predicate is implemented (`assay.cpp:168–184`); that is an additional specification/coverage issue, not a hidden successful measurement.

**Trim: where the lever comes from, and the arithmetic.** This is **(c), not an implementation bug against the written law**. Plan :618–623 explicitly states:

> Forward forces point along body `-x`. Application points are:
>
> `pLoaded = p0 + (L.k - 1.0f) * basis;`
>
> `lever = pLoaded - L.com;`

Plan :583–588 fixes the shares at `caudalArea/propArea` and `.5*pairedArea[j]/propArea`; plan :791 requires “summed scaled channel forces and `lever×force` torques.” Brief :351 fixes the shares, and :368 explicitly places caudal yaw at its loaded centroid. The plan supplies the unambiguous forward-point law too.

`src/ocean/hydro_coefficients.hpp:475–496` copies the decoded canonical caudal/paired centroids and inflation bases. `hydro_step.hpp:83–84` inflates each centroid and subtracts **loaded material COM**, then :116–126 applies forward thrust there. Body +z is dorsal (`src/ocean/hydro_math.hpp:22–34`). The paired fins' forward lines are below COM. For `F=(-T,0,0)`, `tau_y=r_z*F_x=-r_z*T`: their negative `r_z` gives positive pitch torque. This is not force applied at COB. Righting is the separate declared metacentric model, `K=g*rho*Vdisp*(fraction*loadedHalfDepth)` and `tau=K*(ez×upBody)` (`hydro_step.hpp:189–191`; plan :748–754; brief :270–279). No second geometrical COB force torque is specified. Subtracting COM again, applying a separate COB torque, or treating fin positions as already COM-relative would change the law.

The new [probe.cpp](../build_m2b1_pr2/diag3/probe.cpp) records the actual **incoming, metered 25 E load**, forces, points and damping on the next substep after the unchanged 60 s control. It avoids the small post-debit/post-pose load mismatch in the older probe. Raw results: [probe_starting.log](../build_m2b1_pr2/diag3/logs/probe_starting.log).

| Body/control | Caudal `(r_z, T)` | Two pectorals, each `(r_z, T)` | Two pelvics, each `(r_z, T)` | Sum `-r_z*T` |
|---|---|---|---|---:|
| Neutral, 82 | (-.00124656, 61.68562) | (-1.466660, 11.57193) | (-3.725620, 5.518388) | .076895 + 2×16.97208 + 2×20.55941 = **75.13988** |
| Manoeuvrer, 40 | (+.115766, 65.33879 approximately) | (-3.006129, 33.03533) | (-8.986115, 31.70205) | about -7.564 + 2×99.30846 + 2×284.87827 = **760.80945** |

The exact per-channel values, including the caudal force, are in the log. Total thrust is **95.86624 / 194.81355**, hence weighted pitching levers **.783799 / 3.905321 u**. The manoeuvrer's caudal contribution opposes the larger paired-fin moment; it is not the main positive pitch source.

At near-zero angular velocity, the rotational row gives `K*sin(theta) ≈ activePitch - (D*zNext).pitch`. The probe's “dragPitch” is **D*z**, the term subtracted from the RHS, not already the physical negative drag torque. In particular, neutral's negative D*z pitch **adds** positive physical pitch torque. The `h*K*omegaNext` implicit term and the mass/inertia increment explain only the tiny non-equilibrium remainder here; they do not cancel a static torque.

| Quantity | Neutral 82 | Manoeuvrer 40 |
|---|---:|---:|
| Incoming displaced volume / loaded half-depth | 648.40295 / 4.016252 | 763.21075 / 7.931268 |
| K, torque/radian near upright | **3498.04712** | **8131.05371** |
| Active pitch / D*z pitch | 75.13988 / -9.04395 | 760.80945 / +10.07864 |
| Net static pitching demand | **84.18383** | **750.73081** |
| Active-only `asin(active/K)` | **1.23084°** | **5.36893°** |
| Including drag, `asin((active-drag)/K)` | **1.3790106°** | **5.2975983°** |
| Measured control tilt | **1.3789916°** | **5.2975348°** |
| Available righting torque at 1°, `K*sin(1°)` | about **61.05** | about **141.91** |

Thus even the active-only pitching demand exceeds the one-degree righting capacity at these loads. The force/lever accounting predicts both measured equilibria; neither a wrong righting sign nor a wrong force frame is needed to explain them. For comparison, the cruiser at 40 has active pitch 2.22467, D*z pitch -1.28054, K 2054.05688, and predicted tilt .09777°; it passes release. The older probe's matching no-yaw steady states, and its 10/30 s persistence, are preserved in `round3/logs/release_probe.log`.

At yaw=dive=0, the paired normal command is exactly zero (`hydro_step.hpp:127–130`), its induced drag is zero (:167–169), and yaw gain cannot alter forward shares. Tail yaw obeys the specified independent filter (:80–81, :107–108), with neutral residual about 6.2e-29 after 10 s. Its stiffness and gain therefore do not change the driven straight equilibrium. Righting and forward allocation are outside assay-3 authority. Increasing the metacentric fraction would require approximately **2→2.76** for neutral and **2→10.6** for the manoeuvrer at these measured loads, before accounting for the changed trajectory/load. These are local estimates, not a tested calibration; the latter is a lever over ten loaded half-depths and is particularly unattractive.

**Steering: why the three trials fail, and what is not a bug.** The body frame is right-handed: forward -x, starboard +y, dorsal +z, positive heading yaw corresponds to negative body-z angular velocity (`hydro_math.hpp:22–34`). The forward vector is `R*(-1,0,0)`. The measurement computes its world derivative from recovered material omega and divides the horizontal angular cross product by horizontal forward length squared (`assay.cpp:34–53`). An independent expanded-quaternion/finite-difference reconstruction in [trace_geometry.json](../build_m2b1_pr2/diag3/trace_geometry.json) agrees: paired-heavy neutral-82 is -.0587421 versus -.0587430 rad/s; tail-heavy is 4.31072 versus 4.31117, consistent with the discrete-step/instantaneous-rate distinction. It is not a mistaken use of body omega as heading rate.

Paired yaw uses `command=-gain*yaw*l_z/L`; before clamping its own torque is `-gain*yaw*pressureArea*l_z²/L`. Tail yaw uses negative y force at positive caudal x. Both direct torque signs match plan :625–654 / brief :357–380 and `hydro_step.hpp:118–133`. The filter uses incoming state, h/tau, and independent tail forward/yaw requests as prescribed; the stiffening denominator uses total water-relative U and the prescribed speed. No wrong point, yaw-allocation sign, frame swap, or decay/stiffening implementation discrepancy was found.

Net heading need not share the sign of the isolated active torque in a coupled translating body. [probe2_paired.log](../build_m2b1_pr2/diag3/logs/probe2_paired.log) decomposes paired-heavy neutral near the final state: active yaw about **-136.59**; D*z yaw **-133.98**, including lateral translation **-172.64** and rotational contribution **+38.64**. Body omega-z is **+.05869**. The negative motor torque is largely balancing the negative translational damping term; changing the direct force sign to “fix” the observed small reverse turn would violate the specified law. The independent reference, rebuilt with the recommended constants, also passes 5,754 actuator force/location/power/gas checks and 11,508 independent one-step increments.

Starting yaw authority is insufficient for neutral-82. Tail-heavy authority increases yaw but burns the shared power budget and produces large slip and severe speed loss; at 82 its actual speed is 15.85 and lambda minimum .1527. The “manoeuvrer” has a smaller caudal-fin gene and larger paired fins than the cruiser, so a tail-dominated calibration need not make it turn tighter than neutral. Fixed geometry, loaded lever/normal, power pricing and damping all enter; there is no general theorem ordering these three shapes under every gain. Raising relative paired authority solves the ordering without changing the bodies. These are **(a) calibration failures**, not evidence that the body definitions or tensor implementation are wrong.

**The two geometry problems.** The law of a horizontal path is `courseRate = headingRate + sideslipRate` and `curvature = courseRate/U`. A small *angle* does not bound its *derivative*. In paired-heavy finite-120, raw traces give heading rate about **-.064022**, course rate **-.071584**, and slip rate **-.007562 rad/s**. Speed changes 95.1366→93.2340 during the .496 s fit window; world slip changes about -3.1274°→-3.3320°. A circle radius near **1320.03** follows the course curvature, whereas U/heading gives **1464.99**, explaining the .09894665 failure. The independent fit in the preserved `round3/measurement_verification.json` already agrees with the driver; the new trace reconstruction confirms the heading/course distinction. Altering the radius fit to return U/omega would violate plan :1062. Changing tail calibration can avoid this point, but does not repair the general assay definition.

The extra searched cruiser failure is different. At (3,.01,27), its 2 s window has U=40.00226, heading rate **-.000120052**, sideslip 2.0756°, and only **.01378°** of course rotation. Expected sagitta over an 80 u chord is about **.002405 u**. The fit to actual binary32 positions gives **214495.835**, versus U/heading **333207.085**. [position_accounting.cpp](../build_m2b1_pr2/diag3/position_accounting.cpp) separately reconstructs the incoming source state, mechanical velocity increment, floating point position addition and reserve shifts. **Every recorded credit/debit COM shift is exactly zero**; the accumulation rounding changes by (.0032043,.0002647) u over the fit window. Integrating the identical mechanical velocities in diagnostic double gives radius **332596.141**. See [position_accounting.json](../build_m2b1_pr2/diag3/position_accounting.json), [arc_geometry.json](../build_m2b1_pr2/diag3/arc_geometry.json) and the raw accounting log. The binary32 COM addition is exactly the specified law (`hydro_step.hpp:277`; brief :317). A five-percent relative circle test for almost zero curvature needs a resolution domain; promoting simulation positions to double would change the state/law, not fix a faulty fit.

Both low-slip failures are classified **(c)**. They are retained as failures under the unchanged assay; neither was suppressed, relabelled a pass, or used to change the search predicates.

**Bounded deterministic search and feasibility.** [search_grid.py](../build_m2b1_pr2/diag3/search_grid.py) runs the actual unchanged Driver `assay1→assay2→assay3` for each point, all 65 preceding checks included. It changes only the three authorized constants on copies. To avoid hundreds of identical recompilations, the exploration copy makes just those three `constexpr` values mutable and sets them before calling the original CLI main; no mechanics, body, assay, threshold or window is changed. This is an exploration method, not frozen-header acceptance. The chosen point was then emitted as an exact-bit header, **rebuilt as constexpr**, and rerun with both the original and proposed stimuli. Its results and every window chain match the exploratory executable exactly; `native_wasm_verified.json` records that check.

The fixed coarse grid was the full Cartesian product:

```text
paired = [.01, .1, 1, 3, 10, 30]
tail   = [.01, .1, .25, .5, 1, 2, 4]
stiff  = [27, 108, 432]                         126 points
```

Coordinate refinement, selected from the heading brackets at paired=3, used tail [1.025,1.05,1.075,1.10] at stiff=108 and tail=.9 at stiff=432; then tail [1.0025,1.005,1.01,1.015,1.02,1.03,1.035,1.04,1.045,1.055,1.06,1.065] at stiff=108: **17 additional points, 143 total**. No duplicate point or random search. All runs used nice 19; serial binaries, OMP limit 2, compiler/EMCC/Binaryen/linker limits ≤2 (EMCC/Binaryen/linker 1), at most two scheduled workload jobs. Node used single-threaded V8/GC and a one-worker pool. Installed g++ 15.2.0, emsdk **6.0.4**, Node v26.13.0; no dependency downloads. Search child CPU was **508.929 s**, well below 2 CPU-hours; the complete recorded diagnostic workload remains below 12 CPU-minutes. No timing benchmark was run.

Every point's stage-2 freeze and all constant bits outside indices 15–17 were checked unchanged. Its **65 preceding results, including exact measured values, equal the round-3 stage-2 results**. Raw logs/manifests are under [grid/](../build_m2b1_pr2/diag3/grid/); [search_results.jsonl](../build_m2b1_pr2/diag3/search_results.jsonl) contains per-point commands, CPU, exit and failures; [search_summary.json](../build_m2b1_pr2/diag3/search_summary.json) and [CSV](../build_m2b1_pr2/diag3/search_summary.csv) contain the exhaustive results.

There are **zero fully feasible searched points**, but **14 points meet every implemented non-release predicate**. The latter set is:

```text
paired=3, stiff=108:
  tail={1.005,1.01,1.015,1.02,1.025,1.03,1.035,1.04,1.045,1.05,1.055,1.06}
paired=3, stiff=432:  tail=.9
paired=10, stiff=432: tail=1
```

This is a measured discrete feasible set **after excluding the three release failures**, not a certified continuous region. At paired=3/stiff=108, the lower yaw boundary is bracketed by tail 1.0025 (2.44443, fail) / 1.005 (2.45910, pass); the upper boundary by 1.06 (2.74868, pass) / 1.065 (2.7714781, fail). The two early refined samples (tail 1.025 / 1.05) give yaw 2.5723751 / 2.7013172; a local linear interpolation to 2.60 predicts tail 1.030356. Testing the nearby exact binary32 representation of 1.03 gives 2.5993624. Paired 3 was sufficient to fix ordering; retaining stiffening 108 avoids an unnecessary third constant change. This is an empirical calibration derivation, not an assumed linear force-to-yaw law. Intermediate listed samples pass heading, ordering, ratio, metering, finiteness and rail. Their low-slip checks have **zero eligible cases**, so that part is unexercised, not positive evidence of low-slip mechanics.

**The obstruction and limits of the proof.** Throughout all 143 points, neutral-82 released tilt is **1.36257–1.38367°**, neutral-120→82 is **1.35768–1.36171°**, and manoeuvrer-40 is **5.28198–5.30042°**. Each of these predicates fails at every searched point. Thus the bounded grid is exhaustively infeasible; heading and body ordering are **not** the conflicting predicate pair. The conflict is between **retained-drive, zero-yaw/dive centroid-thrust trim under the frozen stage-1/2 law** and **return to within 1° of upright**. The static balance above proves that conflict at the measured driven equilibria; yaw constants disappear from that balance.

This is not a mathematical exclusion of every positive finite float gain/stiffness at an arbitrarily timed 10 s transient. The documents give no bounded continuous calibration domain, huge gains can magnify a nonzero tail-filter residue, and a single timed angle can in principle cross a bound without settling. Claiming global finite-time infeasibility from a finite grid would overstate the evidence. We do prove the steady driven-trim obstruction and the empty complete searched set, while demonstrating steering-only feasibility. A different conclusion outside that set requires additional evidence, not an invented tuning range or a relaxed predicate.

**Ranked remedies, law/freeze impact and gates.** For every option, retain binary32 simulation state, fixed operation trees, `-ffp-contract=off`, no fast math, RNG order and native/Wasm comparison. A document-only amendment has no simulation determinism effect; any new mechanics law requires fresh parity proof. The recommended pair below already has that proof for assays 1–3.

| Cause | Ranked option | Law as written / frozen-stage impact | Determinism and required gates |
|---|---|---|---|
| Heading, ordering, ratio (a) | **1. Use gains 3 / 1.03, stiff 108.** | Within “Assay 3 freezes yaw gains and stiffening” (plan :1068; brief :664). No stage-1/2 constant or body change; preceding physical traces identical. | Native/Wasm proved for conditional candidate. Rebuild G2 focused suites + UBSan, G3 reference, G4 assays 1–4 with ordered emission, then G5–12 before PR completion. |
| Same | 2. Continue bounded yaw-only calibration if another operating trade-off is desired. | Same authority; cannot silently demand a specific body order by altering body genes, force prices or drag. “Change only the constants assigned” (plan :1071). | Deterministic if exact bits/fixed operations; each candidate must rerun 1–3. New final candidate needs all affected gates. No guarantee it meets actual-82/radius-31 goal. |
| Driven release/trim (c) | **1. Explicitly cut forward request as well as yaw; keep ≤1° and 10 s.** | Changes assay stimulus interpretation of “After release” (plan :1035; brief :664), not mechanics. Requires OWNER DECISION D1. Does not change stages 1–2 or their tests. | Proved native/Wasm for 97 predicates. Harness-only change alone needs full 1–3/trace parity and G4/5 integration; combined calibration still needs remaining release gates. |
| Same | 2. Retain drive and compare with a matched driven straight trim, while separately testing upright recovery with drive cut. | Acceptance amendment to the same quoted sentence, not a law fix. No blanket 6° allowance. Stage-1/2 constants unchanged; original absolute bound deliberately replaced for driven case. | Can be deterministic; not implemented/proved here. Needs control-definition tests, 1–3, reference comparison, fixtures/parity; D2. |
| Same | 3. Move forward lines to COM height; keep yaw/control at fin centroids. | **Law change** to plan :618–623 (“Application points … lever=pLoaded-L.com”), :658–663 pricing, :791 torque. Stage-2 thrust/trim/power evidence must be reopened; revalidate assay 1 as well. Stage-1 righting constants need not change, but prior results cannot be assumed. | Fixed binary32 point law can be portable; **unproved** here. Update independent reference/unit oracles, law/version/digests, rerun G1–6 including all earlier assays, then G7–12. D3. |
| Same | 4. Reopen stage-1 righting and increase its metacentric lever. | Violates existing freeze unless explicitly reopened: plan :1066, brief :660. Formula `delta=fraction*halfDepth` can stay, but fraction ~10.6 for the manoeuvrer is extreme. | Portable in principle, unproved candidate. All calibration stages/reference/fixtures and G1–12 must be revisited. Not recommended merely to hide driven trim. D3 alternative. |
| Finite-120 low-slip radius (c) | **1. Define steady/resolved eligibility and report transient course curvature separately.** | Amends “When sideslip <5° … U/omega within 5%” (plan :1035, brief :664). The original condition omits slip-rate and transient curvature. No simulation/frozen-stage change. | Measurement-only deterministic sampling; double-fit values need tolerances, float trace equality remains exact. Rerun all geometric cases and planted measurement faults, 1–3 and native/Wasm trace parity; G4–6 integration. D5. Not needed/applied to make our selected point pass. |
| Almost straight cruiser radius (c) | **1. Require a resolvable recorded arc for the relative circle test.** | Same assay amendment; retain real recorded-position fit required by plan :1062. Do not replace fit with U/omega. No stage-1/2 change. | Measurement-only; add unresolved-arc and resolved-arc coverage; same gates as previous row. D5. |
| Either radius issue | 2. Increase simulation position precision or add substep/path state to remove accumulation error. | Changes binary32/state/ABI law (brief :633, :643–650, :314–319), still does not fix beta-dot vs heading. Unnecessary for the diagnosed assay. | Needs new state/checkpoint/digest/ABI/reference/parity work and all affected gates. Reject as an assay-3 calibration fix. |
| Missing radius-near-31 coverage | **1. Resolve the intended performance requirement before freezing.** | Plan :1033 / brief :664 say “radius near 31.” The current driver only implements heading tolerance. Our radius 14.329 does not meet the stated goal. No permission to tune earlier force/power law follows from that omission. | No full-spec pass claimed. D4 must define whether a report-only goal is acceptable or a quantified actual-speed/radius requirement blocks stage 3. |

**Recommended set and exact, unapplied patches.** Recommend the calibrated yaw pair plus full-command righting release, with the matching specification wording. Keep stage-3 approval pending the radius/coverage decisions; do not accept the large-slip result by omission. These changes solve the observed numerical heading/ordering/release failures with no physics-law modification or earlier freeze change. They are narrower than altering thrust geometry or greatly increasing righting. Only scratch copies contain their source effects.

1. [01_yaw_calibration_candidate.patch](../build_m2b1_pr2/diag3/01_yaw_calibration_candidate.patch): exact generated stage-2 candidate, paired **0x40400000**, tail **0x3f83d70a**, stiff unchanged **0x42d80000**. Frozen-through stays 2. Only the two gain lines change.
2. [02_release_stimulus_OWNER_DECISION.patch](../build_m2b1_pr2/diag3/02_release_stimulus_OWNER_DECISION.patch): release with `HeldOuter{}` instead of continuing requested drive; no state/filter reset, force cancellation, free recovery kick or changed threshold.
3. [03_release_wording_OWNER_DECISION.patch](../build_m2b1_pr2/diag3/03_release_wording_OWNER_DECISION.patch): exact proposed D1 amendment at the plan and brief assay rows. This documentation patch is not installed even in the source candidate; its old-document copies are in `amendments_base/`.

All three patches pass `patch --dry-run` on preserved scratch copies. `recommended/` differs from `base/` in **only** the two source files represented by patches 01–02. `calibrated_original/` retains the original stimulus with the same generated calibration. No patch was applied to the actual worktree sources/documents, and no real freeze was advanced.

**Native/Wasm passing demonstration and its boundary.** Builds use `-O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN`; Wasm adds `-msimd128`, node raw FS, memory growth and 8 MiB stack, with one linker thread. Full commands, exits, CPU/wall durations and output paths are in [commands.jsonl](../build_m2b1_pr2/diag3/commands.jsonl) and [run.py](../build_m2b1_pr2/diag3/run.py).

| Scratch run | Result |
|---|---|
| Rebuilt constexpr calibration, original stimulus | **94/97**, exit 1; only N82/N120/M40 release fails; [manifest](../build_m2b1_pr2/diag3/original_stimulus_native.json) |
| Rebuilt constexpr calibration + proposed release, native | **97/97**, exit 0; [manifest](../build_m2b1_pr2/diag3/candidate_native.json), [log](../build_m2b1_pr2/diag3/logs/candidate_native_assays123.log) |
| Identical candidate, Wasm under Node | **97/97**, exit 0; [manifest](../build_m2b1_pr2/diag3/candidate_wasm.json), [log](../build_m2b1_pr2/diag3/logs/candidate_wasm_assays123.log) |
| Independent reference rebuilt with chosen constants | **PASS**, exit 0; max independent step error 3.46788e-6, solve residual 3.94251e-7; [log](../build_m2b1_pr2/diag3/logs/recommended_reference_run.log) |
| Result/trace/copy verification | **PASS**, exit 0; [native_wasm_verified.json](../build_m2b1_pr2/diag3/native_wasm_verified.json) |

Native/Wasm traces have **116,066 data rows / 31,077,176 bytes**, SHA256 **caf03f2ffb977f97f7b38b004ebfac6ad1cdd8d4f2bf46a578d2ee74fd230a52**. Raw files are `candidate_native.csv` and `candidate_wasm.csv`; both full files are byte-identical. All result values and every window's receipt chain match too. Constant/reference/coefficient digests are `66b5b28e6e06a84d` / `34f5953354409576` / `3e8bfae4938384af`. The 21 preceding/straight-control trace cases are byte-identical to the unchanged round-3 starting run. Steering traces are identical between original-stimulus and release-amended candidates, proving that the release patch does not change the turn measurements.

At 40, fitted radii are manoeuvrer **2.47652** < neutral **2.92380** < cruiser **12.68934**, ratio **5.12387**. Maximum omega across the five turns is **7.34240**, below both rails. At 82, yaw is **2.599362**, actual speed **37.246138**, radius **14.329165**, not 31. The finite-120 window remains [.496,.992) s, with finite turn lasting .992 s; it is not a steady-120 claim. Driver `acos` reports four very small release angles as zero; independent quaternion `atan2` gives N40/N82/N120/M40/C40 respectively **.01942/.00178/.00202/.00459/.03293°**, all safely below 1°. No numerical zero is needed for acceptance.

All five candidate turns exceed 5° sideslip, including the finite burst. Their low-slip predicate is unexercised, although radius errors are still printed. In particular the finite-burst candidate radius error is about .0723, but the slip gate does not apply. This is a limitation of the existing assay's coverage, not a demonstrated ≤.05 result for that case. Do not describe 97/97 as a proof of the full intended performance specification.

**OWNER DECISIONS, in plain words, with exact proposed amendment text.** None is implicitly approved by this diagnostic or by its conditional passing manifests. D1/D2 are alternative release definitions; D3 is an alternative physics response if driven absolute upright recovery is required. D4/D5 address separate acceptance/coverage issues.

**D1 — Does “release” cut forward request? Recommended for the righting test.** Cutting drive preserves the absolute one-degree upright bound and specified mechanics, but tests motor-command release rather than upright trim while swimming. Gas regulation remains powered; speed=0 can deploy the existing passive brake, so “full motor shutdown” would be inaccurate. Exact replacement for the release sentence in plan :1035 and brief :664 (patch 03):

> For the righting release, set speed, yaw, dive and forward-bias requests to zero for 625 outer steps; preserve filtered tail state and keep the paid gas regulator and passive braking active. Roll/pitch must return within 1° of upright after those 10 s, including after the finite-120 burst.

**D2 — If forward drive is retained, allow its measured trim instead of requiring upright.** This preserves current force locations and earlier calibrations, but deliberately changes the original absolute acceptance. Do not add a broad absolute trim allowance that hides unexpected behavior. Exact alternative amendment:

> Add a driven yaw-release diagnostic: set yaw and dive to zero while retaining the pre-turn speed request; after the finite-120 case use 82. Measure signed roll and pitch against the matching body's 60 s, metered-25 E, no-yaw/no-dive straight control, with horizontal headings aligned for the comparison. Require roll and pitch each within 1° of that control after 625 outer steps. Report the control's absolute trim separately. This driven diagnostic does not replace the command-release upright check defined in D1.

This additional test has not been implemented or proved here. It is preferable to silently declaring the existing 5.3° result acceptable under a one-degree absolute bound.

**D3 — If upright under drive is essential, change the thrust line or reopen righting.** This is a law/freeze decision, not extra assay-3 tuning. A COM-height line removes an intended centroid torque and changes the physical model and local-work locations. Exact proposed law amendment for that alternative:

> Forward caudal and paired-rowing forces remain along body -x with the prescribed shares, but use application lever (loadedLever.x, loadedLever.y, 0) relative to loaded material COM. Price their work at that same application point. Caudal yaw and paired normal control retain their full loaded fin-centroid levers. This replaces the forward-point rule in plan 618–623; version the actuator mechanics law, update its independent reference, and reopen stage-2 trim/power acceptance before refreezing. Rerun assay 1 and every subsequent assay.

The separate, less attractive righting alternative would require this exact authority amendment before tuning:

> Reopen stage 1's metacentric-fraction calibration; stages 1 and 2 are no longer frozen acceptance evidence until regenerated, rebuilt and rerun in order. Assay 3 gains no authority to alter righting. Retain the declared righting formula and disclose the resulting offset in loaded half-depth units for every assay body.

No such law/reference/version change or righting experiment is included in the recommendation or passing scratch set. A COM-height thrust line alone also does not establish the future level-trimmed calorimetry or radius goal; those need measurements.

**D4 — Is radius near 31 a report-only goal or a real performance gate?** The current numerical driver does not decide this. Accepting a report-only goal admits large-slip, slower turns like the measured candidate; requiring actual-82/radius-31 could demand different force allocation or power law outside assay-3 authority. No searched heading-passing point is close to 31 (radii range about 11.66–16.28); this is evidence over the searched set, not a global impossibility theorem. **Recommend retaining the performance goal and withholding a final stage-3 freeze until the owner chooses its quantitative meaning.** Exact proposed strong amendment, if that goal is intended literally:

> The neutral 82 step-steer acceptance is evaluated over the prescribed settled fit window using measured horizontal speed, not requested speed: mean speed 82±2%, heading rate 2.60±.15 rad/s, fitted radius 31±5%, and maximum sideslip <5°. These are additional conjunctive predicates. A candidate that meets heading while slowing or slipping outside these bounds is not an assay-3 pass. Any required non-yaw law change must be reported and the affected earlier freezes reopened.

The demonstrated candidate **does not pass that proposed stronger definition**. Alternatively, if the owner expressly accepts the present numerical scope, the exact weaker clarification is:

> The 40/82/120 labels name the pre-turn straight-speed requests. Actual turn speed, fitted radius and sideslip must be reported without substitution. The 31 u radius is a non-gating design goal for PR 2; heading 2.60±.15 is the neutral-82 numeric target, and the existing conditional low-slip identity remains. Large-slip, reduced-speed turns may satisfy this PR-2 assay and are not evidence of the design goal.

That alternative is an explicit acceptance trade-off, not an implementation fix or something this diagnosis silently assumes.

**D5 — Make the radius check meaningful during transients and near straight paths.** Current <5° angle alone is insufficient. Recommended exact future assay-definition amendment:

> Apply the 5% fitted-position-radius versus U/heading-rate check only to settled low-slip windows: maximum absolute sideslip <5°, total unwrapped course rotation at least 5°, speed range ≤2% of its mean, and absolute difference between mean course rate and mean heading rate ≤2% of the absolute mean heading rate. Use recorded positions for the fitted radius. For the finite-120 burst and all ineligible windows, report fitted radius, U/heading-rate, course rate, slip-rate, speed range and eligibility reason separately; do not mark the steady-radius identity as passed. Always print the number of eligible low-slip cases. Zero eligible cases means 'not exercised'; the owner must explicitly accept that coverage or specify an additional fixed eligible case before freezing stage 3.

This is an acceptance amendment requiring review and dedicated measurement tests, not a theorem that these chosen eligibility bounds alone guarantee a 5% fit. No such amended check was applied to the search or used to obtain 97/97. The five-degree minimum course arc trades away relative-radius claims on unresolvable curvature; transient reporting preserves the finite-burst obligation without asserting the wrong identity. The original failed points remain failed in all saved manifests.

**Remaining gates / handoff.** This diagnosis ran every requested search point's assays 1–3, the original-stimulus static rebuild, conditional native/Wasm full traces, independent reference and preservation checks. It did **not** complete the PR release sequence. Once owner decisions are resolved, use the actual accepted sources and plan :1341–1471: G1 prerequisite/scope audit; G2 focused hydro/hydro_step and UBSan; G3 independent reference; G4 calibration 1→2→3→4 with rebuilt emitted headers and real `--check-all`; G5 native/Wasm hydro and step fixtures; G6 full un-narrowed Ocean parity with expanded twins and the precisely disclosed historical exception only if actually encountered; G7 sequential component timing/memory; G8 Ocean rebuild/freshness; G9 Classic rebuild/unchanged hashes; G10 repository native checks; G11 module consumers/local types; G12 final frozen-scope audit. The conditional reference run is useful G3 evidence, but there is no G4-complete or whole-release claim. Assay 4 and the later missing obligations remain blocked/not run, as in round 3. No rebaseline, merge, deployment or commit is authorized.

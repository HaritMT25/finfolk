# M2b1 PR 2 gate-4 diagnosis — round 2, diagnosis only

Date: 2026-11-23. Worktree: /home/harit/finfolk/work/trees/m2b1-pr2.
Base/HEAD: ba6f29c6ee4a04b1ce41b27ab49e81443802968d; branch m2b1-pr2.
All source references below refer to the **uncommitted round-2 sources**, not main.

**Recommendation.** Use the assay-1 calibration candidate metacentric fraction 2, vertical gain .2, regulator tau 2 s, and seek an **OWNER DECISION** defining the friction test's tangential force in the floor plane. The combined scratch candidate passes 33/33 checks, gates 2–3, and native/Wasm assay trace equality. Calibration alone passes 32/33: the original COM-force friction case still fails. Thus there is **no demonstrated passing result for the unchanged round-2 assay stimulus**. The conditional passing result must not be called a release, freeze, or retroactive pass of round 2.

Five failures are **(a) authorized assay-1 calibration**: the righting response is insufficiently damped at the bootstrap metacentric constant, and the bootstrap gas regulator is dynamically unstable. The sixth is **(c) a contact/assay specification problem**: a scalar friction threshold does not guarantee equilibrium under a COM-height load on this hull; the prescribed local static/dynamic iteration also admits a sliding branch despite a feasible aggregate static solution. I found no departure from the cited formulas in the implicated implementation. In particular, I am not recommending a normal-load multiplier, sign reversal, hidden damping term, extra righting kick, or relaxed numerical threshold.

**Scope and evidence preservation.** No existing file was changed. The earlier contents of diag2 already existed on entry and were preserved, including its experiments and patches. I verified its base/src, base/tests and base/tools copies match the current sources byte for byte, but built and ran a separate candidate for this report. New experiment files are under [audit_20261123](../build_m2b1_pr2/diag2/audit_20261123/); the three new proposed patches are directly under diag2. The inventory [existing.before.json](../build_m2b1_pr2/diag2/audit_20261123/existing.before.json) hashes 2,490 pre-existing files in src, tests, tools, docs and build_m2b1_pr2; [preservation_verified.json](../build_m2b1_pr2/diag2/audit_20261123/preservation_verified.json) confirms zero changed or missing files. No commits, network, study/noise-bank operations, baseline changes, or production module changes were made.

Every C++ build/run and counterfactual assay was invoked through the new [run.py](../build_m2b1_pr2/diag2/audit_20261123/run.py), which uses nice 19, OMP_NUM_THREADS=2, OPENBLAS_NUM_THREADS=1, EMCC_CORES=1, a new scratch temp/cache location, and the offline frozen Emscripten cache. Compiler concurrency was limited; no OpenMP build or browser was used. [commands.jsonl](../build_m2b1_pr2/diag2/audit_20261123/commands.jsonl) contains exact argument arrays, environment, raw exits and elapsed times. Tool versions are g++ 15.2.0, Emscripten 6.0.4, Node v26.13.0; [identity.log](../build_m2b1_pr2/diag2/audit_20261123/identity.log) also records CPU information.

**Rules that authorize calibration, and their limits.**

The plan at [1066](/home/harit/finfolk/work/trees/m2b1-pr2/docs/_ref/m2b1_pr2_plan_codex.md:1066) assigns assay 1 “material normalization/reference trim, gravity, pressure law, righting, regulator, friction and contact tolerances.” At plan:1071 it says:

> Use starting constants first. If calibration is needed, change only the constants assigned to that assay; emit a new candidate header, rebuild, and rerun that assay plus all preceding assays. Reject any candidate that invalidates an earlier freeze.

The brief:3 calls the numerical values “starting constants,” except its named anchors. Brief:660 explicitly assigns “metacentric offset and regulator gains” to assay 1. Plan:1073 forbids tuning geometry normalization, population, mouth radius, construction price, food distribution, predators, basal anchors, the 82 reference, or the 12 rad/s rail. Plan:1075 says:

> If an assay cannot meet its target without changing the law, stop and report the discrepancy; do not stamp a frozen manifest.

These local reference documents have no numerical tuning interval for the three recommended constants. In particular, neither document imposes metacentric fraction ≤1. Do not invent such an authorization interval or claim that a numerical bound was supplied. The derivations and measurements below justify a candidate within the assigned calibration categories; positive restoring stiffness, positive regulator tau and stabilizing feedback are the relevant mathematical constraints. A metacentric lever is the declared model's restoring lever; it is not an independently measured geometric COB position. The candidate's large change, .12→2, must be disclosed: its lever is twice loaded half-depth. If the owner intends a geometric inside-hull cap, that would be an additional **OWNER DECISION**, requiring a different law/acceptance solution, not a silent cap or claim that .12 was immutable.

It is legitimate to propose these three constants now: kFrozenThrough remains 0, starting constants have actually been tried, and no earlier assay freeze exists. This report does not implement the required emitter or advance kFrozenThrough.

**Each failed check and its attribution.**

| Failed check at round 2 | Classification | Implementation location and specified rule | Confirming observation |
|---|---|---|---|
| Roll: 1.0214415° at 10 s | (a), shared righting calibration | hydro_step.hpp:182–208, especially :189–203; hydro_coefficients.hpp:765–781; calibration.hpp:10. Plan:735–780, :1026; brief:269–289, :660. | Correct restoring sign and loaded lever; oscillatory decay, rather than failure to return toward upright. Gain 2 passes and stays below 1° after 10 s. |
| Pitch: 5.0015525° at 10 s | (a), same constant, different inertia/damping | Same law and locations; assay.cpp:87–100 applies a body-y rotation, not roll. | Effective pitch inertia 3.845× roll; much weaker normalized fin damping and slower period. Its 10 s sample is near a peak. |
| Combined: 4.4093553° at 10 s | (a), same response, predominantly pitch | Same law; assay.cpp:91–93 composes roll and pitch; plan:1026 requires this extra check. | Residual signed pitch component ≈4.344°, total ≈4.409°; gain 2 also settles this case. |
| Target 96: error 25.7698746 u | (a), regulator calibration | hydro_step.hpp:136–148; calibration.hpp:11–15; assay.cpp:102–106. Plan:674–695, :1027; brief:520–540, :660. | At 60 s depth 70.2301254, downward velocity −1.1008058 u/s, full lambda. Continues oscillating through 600 s. |
| Target 144: error 22.3283997 u | (a), same loop | Same locations; target is bodyBuoy=144/240. | At 60 s depth 166.3283997, downward velocity +.2193641 u/s. Continues oscillating through 600 s. |
| .9 muStatic N: speed 9.0318794 u/s | (c), load/moment specification plus local contact algorithm | assay.cpp:114–123 applies force at COM. Contact.hpp:124–164 follows plan:878–917, including four sweeps and local dynamic fallback. Plan:1028 and brief:661 assert hold without specifying load height/torque. | Required initial normal COP with the COM load is outside the current support interval; once sliding starts, applied force exceeds dynamic friction. Even floor-plane loading at the bootstrap righting constant exposes the solver's sliding branch. |

Paths in this table abbreviate src/ocean/hydro_*.hpp and tools/ocean_hydro_assay.cpp. Exact constants are at [hydro_calibration.hpp:10](/home/harit/finfolk/work/trees/m2b1-pr2/src/ocean/hydro_calibration.hpp:10); mechanics at [hydro_step.hpp:182](/home/harit/finfolk/work/trees/m2b1-pr2/src/ocean/hydro_step.hpp:182); regulator at [hydro_step.hpp:136](/home/harit/finfolk/work/trees/m2b1-pr2/src/ocean/hydro_step.hpp:136); contact at [hydro_contact.hpp:139](/home/harit/finfolk/work/trees/m2b1-pr2/src/ocean/hydro_contact.hpp:139); assay loads at [ocean_hydro_assay.cpp:114](/home/harit/finfolk/work/trees/m2b1-pr2/tools/ocean_hydro_assay.cpp:114).

The input trace has 37,192 substeps, all with exactly 25 E incoming. Its SHA256 remains 202334e77ee3798b95f1230960ec42bce8c754cda1873775f6b0f8637e5cf2fa. Decoded original trace values and arithmetic are in [analysis.json](../build_m2b1_pr2/diag2/audit_20261123/analysis.json). The trace's integer state words were decoded as binary32, including quaternion, gas, position and velocity; the CSV's printed gas-rate/lambda columns are telemetry. Small angle differences between the decoded double atan2 calculation and the assay's float dorsal projection/acos are rounding, not different trajectories. Acceptance values quoted above are the assay's own.

**Why pitch is about five times worse than roll.**

The starting neutral load has material mass 1.09958065, displaced volume 654.873413, rhoWater .00167907355, loaded half-depth 4.03639555 and Lc=10. The declared restoring stiffness is:

~~~
K = 400 * rhoWater * displaced * (.12 * halfDepth)
  = 213.04043 force*u/rad.
~~~

The code uses the specified lever relative to COM, not the hull centroid minus COM; the brief explicitly declares this metacentric approximation. The torque cross(ez, R^T worldUp) restores both tested axes. The positive h²K additions appear once in angular x/y; there is no second kick. Gate 3 independently evaluates this sign and matrix (trajectory_reference.hpp:59–66).

For a small isolated tilt, using diagonal effective inertia gives:

~~~
I * theta'' + beta * |theta'| * theta' + K * theta ≈ 0
beta = Lc * (rhoWater*Jbody_axis/2 + Dfin_axis)
~~~

Translation/rotation coupling and pose/load changes are retained in the actual experiments; this scalar approximation explains the scales.

| Quantity | Roll | Pitch |
|---|---:|---:|
| Effective inertia, Meff angular diagonal | 15.613873 | 60.042976 |
| Jbody diagonal | 977.317627 | 3955.831055 |
| Fin angular tensor diagonal | 1.1683886 | .04947990 |
| beta | 19.888827 | 33.705456 |
| beta/I | 1.27379 | .56136 |
| Natural angular frequency sqrt(K/I), rad/s | 3.69382 | 1.88365 |
| Natural period, s | 1.70100 | 3.33565 |
| Initial peak-speed equivalent damping ratio beta*(10°)/(2I) | .11116 | .04899 |
| Small-step implicit amplitude decay rate h*K/(2I), 1/s | .05458 | .01419 |

There is no fixed physical damping ratio/time constant: the passive angular damping is proportional to speed (hydro_coefficients.hpp:768–778), so its torque is quadratic and weakens during relaxation. The last row is **numerical damping from the specified implicit righting step**, not an additional physical torque.

Trace peaks confirm the distinction. Roll absolute peaks fall from 7.386° at .856 s to 3.978° at 3.416 s and 1.686° at 9.376 s. Pitch peaks are 8.644° at 1.672 s, 7.592° at 3.344 s and 5.490° at 8.352 s; the next peak is close to the 10 s observation. Thus the factor ≈4.90 in the two endpoint errors combines slower, less damped pitch with phase: roll is closer to a zero crossing. It is not a fivefold wrong pitch lever or gain. The combined release leaves predominantly pitch.

A smaller candidate fraction 1 passes the pitch endpoint (fresh probe .848806°) but rebounds to **1.240804° after 10 s**. That is a poor interpretation of “return within 1° in 10 s.” Fraction 2 gives endpoint values 0° at the assay's float resolution, .0969133°, and .1008706° for roll/pitch/combined. Dense outer-step observations through 30 s give respective maxima after 10 s of **.0197823°, .399095°, .372729°**. This avoids selecting a lucky crossing. Evidence: candidate_*_extended.log and meta1_pitch_extended.log in the audit directory.

At fraction 2 the neutral metacentric lever is 8.072791 u and K≈3550.67; natural frequencies rise by sqrt(2/.12)=4.08248. Both physical quadratic drag at the faster angular motion and the declared implicit attenuation increase. This is a substantial behavioral calibration, not bit preservation.

**Why the depth errors are dynamic instability, not a steady-state offset.**

Both signs are correct. A deeper-than-target fish requests more gas and rises; positive downward ground velocity also requests more gas. Target units are correctly fractional bodyBuoy times D, so 96→.4 and 144→.6, not 96/144 as fractions. Pressure uses positive depth, Hp=120 and P=1+depth/120. The neutral feedforward is the specified mass/rho minus hull/fuel/exposed-fin displacement. The implementation matches plan:674–695 and brief:523–540, including pricing and shared lambda.

Capacity and authority are ample:

~~~
Vhull=595.566528; Vneutral=21.2418957; VgasCapacity=44.6674919.
Initial depth error ±24:
  depth correction = .08*Vhull*24/240 = ±4.7645322 volume units.
  initial Vtarget = 16.47736 or 26.00643, both inside capacity.
  initial |Gdot| = 2*4.7645322/5 = 1.9058129.
  gas-rate ceiling = .02*Vhull = 11.9113306.
At equilibrium, required gas contents:
  G(96)=1.8*Vneutral≈38.2354123;
  G(144)=2.2*Vneutral≈46.7321705.
Starting G=42.4837914: only ±4.2483791 content units are needed.
~~~

The raw trace has lambda=1 throughout both cases. Gas volumes range 17.196–25.295 and 17.605–24.730 respectively, below capacity; maximum absolute requested rate is 1.905813, below the rate ceiling. There is no configured dead band, pump starvation, bladder capacity limit, wrong target, or clamped-rate steady error.

Linearize at neutral equilibrium, letting x be depth error, v=dx/dt, q gas-content perturbation, m=Meff_zz=2.41793418, V=Vhull, Vn=Vneutral, P=2:

~~~
B = gravity*rhoWater*V/m = 165.430476
C = gravity*rhoWater*Vn/(m*P*Hp) = .0245848333

v' = C*x - gravity*rhoWater*q/(m*P)
q' = [(P*kd*V/D + Vn/Hp)*x + P*kv*V*v/82 - q]/tau

s³ + (1/tau)s² + [B*kv/(82*tau) - C]s + B*kd/(D*tau) = 0.
~~~

C is passive compression's destabilizing feedback: moving deeper compresses gas and reduces buoyancy while the regulator lags. The infinitesimal quadratic water drag supplies no constant linear damping. The above local calculation neglects small tensor coupling; the full kernel is used for all measured runs.

With kd=.08, kv=.02, tau=5, the polynomial is:

~~~
s³ + .2 s² - .016515054 s + .0110286984 = 0
poles ≈ -.3423435, +.0711717 ± .1647722 i.
~~~

That pair grows with an e-folding time ≈14.05 s; its local period is ≈38.13 s. This is not a stable response merely needing a little more observation time. The Routh condition is:

~~~
kv > 82*tau*( Vn/(P*Hp*V) + kd/D )
   > .1975973 at the initial P=2 and tau=5.
~~~

Bootstrap .02 is about one tenth of that boundary. Nonlinear resistance bounds the large excursion; it does not make the desired equilibrium locally stable. Fresh unchanged-source 600 s probes confirm persistent bounded oscillation: during 400–600 s the 96-target depth spans **69.02784–120.99964**, and the 144-target depth spans **120.29956–166.46642**. Maximum vertical speeds in those late windows are 3.97674 and 3.63314 u/s. See baseline_depth{96,144}_extended.log. No integral controller is required to remove a theoretical P-only offset: with the declared neutral feedforward, zero velocity and neutral gas imply x=0 in exact arithmetic.

The recommended kv=.2, tau=2 retains kd=.08, pressure, gas capacity/rate and pump efficiency. The local polynomial becomes:

~~~
s³ + .5 s² + .177159650 s + .0275717460 = 0
poles ≈ -.2402675, -.12986625 ± .31287238 i.
~~~

Its slow decay time is ≈7.70 s, comfortably inside 60 s. At tau=2 the initial stability boundary is kv>.0790389; .2 also exceeds the corresponding boundary at both target pressures. Fresh 600 s probes end at 95.9985428 and 143.9954987, with no renewed depth excursion during 400–600 s. Small residual velocity/gas-request noise accompanies binary32 position/gas quantization; errors are thousandths of a unit, not the original tens of units. The candidate's 60 s errors are .00144958 and .00450134.

**Why “.9 muStatic N must hold” fails here.**

The normal-load scale is correct, with no extra h or missing density:

~~~
N = 400*(M-rhoWater*Vdisplaced) = 14.26663399 force units
F = .9*.8*N = 10.27197647
h*N = .1141330719 normal impulse per .008 s substep
h*F = .0821758118 required tangential impulse if held.
~~~

The rest-state contact probe's summed normal impulse is .11494068, close to hN with the small residual dynamics/finite iteration. This is not the factor-of-several load error required to explain the failure. Contact factors use Meff for both linear and angular responses (contact.hpp:122–134), world axes are transformed into body coordinates (:126–129), and ground velocity restores water velocity before each projection (:142–150), exactly as plan:878–917 requires.

There are **two limitations**, and they should not be conflated.

First, at the end of the original 60 s floor rest the hull is tilted about 7.34°. The active contact vertices 41,49,57 have world x levers approximately +2.777574, +.559375, −1.658823 and height −3.64597 relative to COM. The metacentric world-z torque is −25.918375. A horizontal force at COM has no torque itself; its opposing floor friction creates a couple with that force. For no motion, the required normal center of pressure is:

~~~
tauMeta + N*xCOP - hCOM*F = 0
xCOP = (25.918375 + 3.64597*10.2719765)/14.266634
     ≈ 4.441811 u.
~~~

That lies beyond the present contact interval [−1.658823,+2.777574]. Summed static friction capacity alone cannot hold this pose. The fish must change pose/contact support, which creates slip in this trial. Once it slips, dynamic resistance is .6N=8.5599804 < F: a continuing force surplus of 1.7119961 remains before hydrodynamic/brake resistance. By 10 s the trace shows a single active point with Jt_x=−.06724475 and Jn=.11207458, exactly Jt/Jn=−.6. The observed 9.031879 u/s is a sliding solution, not a suspicious zero normal force. Changing the force's frame at each half-step would not remove this missing equilibrium couple.

Second, moving the force into the floor plane makes the static moment equation feasible at this pose: the added external moment cancels the friction couple, and xCOP=25.918375/N=1.816713 lies within support. Tangents distributed in proportion to normal impulses would each have |T|/N=.72<.8. Nevertheless, the **specified local solver** can enter its dynamic branch while normal impulses are still being distributed. At bootstrap constants the frozen floor-plane probe returns three points all on |Jt|=.6Jn, summed |Jt_x|≈.0673274 against required .0821758; the outgoing forward slip is already ≈.013 u/s. Thus the scalar feasible static solution is not found by this iteration.

This is visible directly at contact.hpp:153–160: it tests each accumulated required tangent against that point's current Jn, and immediately substitutes the smaller dynamic disk. This is also precisely the algorithm in plan:906–911, rather than an implementation departure. More sweeps alone do not repair the branch selection: scratch **64** sweeps with floor-plane loading and the bootstrap calibration still slide at **9.746955 u/s**. The existing four-sweep plane-only control gives **9.743128 u/s**. The 64-sweep experiment is a deliberately unapproved law counterfactual, not part of the recommendation or a gate pass.

The combined recommended calibration settles the floor at a different pose/support configuration. With the floor-plane force it holds at **.0000503124 u/s**, while the 1.1 load slips at **14.8317814 u/s**. With exactly those calibrated constants and the **original COM force**, it still slides at **9.2599535 u/s** (32/33 checks, raw exit 1). Consequently, the passing combination is an interaction of calibrated righting/contact geometry and the clarified stimulus. It neither proves global correctness of the static solver nor establishes that load placement alone fixes the bootstrap failure.

Evidence: contact_original.log, contact_both_loads.log, baseline_floor.log, plane64_assay.log, plane_only_assay.log and calibration_only_assay.log under the audit directory. The probes are small standalone programs compiled against source copies/current read-only headers. The source of the impulse/moment check is contact_probe2.cpp.

**Ranked fix options and effects.**

| Cause | Rank and option | Changes specified law/acceptance? | Effect on already passing behavior and necessary gates |
|---|---|---|---|
| Three righting failures | **1. Recommend metacentric fraction 2**, retaining the declared torque/matrix/damping law. | Constant calibration authorized by plan:1066–1071 and brief:660; no numerical interval is supplied. Threshold/time stay 1°/10 s. | Changes angular trajectories, floor pose, induced translation and pump/actuator costs. Rerun gates 2 optimized+UBSan and 3, all of assay 1, then 2–4 as reached. Later fixture/parity/timing/freshness gates must use these constants. |
| Same | 2. Fraction 1 or a finer search between 1 and 2. | Same authorized category. | Fraction 1 passes the endpoint but rebounds above 1°; reject as the current candidate. A finer search needs complete combined/floor/late-window validation, not just pitch endpoint tuning. |
| Same | 3. Add fixed linear angular damping, alter inertia/COM/COB law, or add a second righting impulse. | **OWNER DECISION: law change.** Brief:284–289 and plan:735–780 specify the solve; extra kick is explicitly forbidden. | Would change passive/reference/contact dynamics and require independent reference/unit updates and all gates from 1 onward. No such patch is recommended. |
| Same | 4. Accept 5° or wait longer. | **OWNER DECISION: acceptance change**, contradicting plan:1021, :1026 / brief:660. | Would conceal the stated failure. Not recommended. |
| Both depth failures | **1. Recommend vertical gain .2 and tau 2 s**, keep depth gain .08. | Authorized regulator calibration; exact same clamp, price, compression and update law. Derived stability boundary and 600 s evidence above. | Changes regulation/pump work in tilted/moving cases, including previously passing cases. Rerun gates 2–3 and all assay-1 cases; every later stage must rerun earlier assays. |
| Same | 2. Keep tau=5 and raise vertical feedback above its derived stability boundary, with margin, or use tau=1 and .2. | Authorized constants, not a sign/unit fix. | Merely crossing .1976 at tau=5 gives poor settling margin; faster tau=1 is exploratory and incurs different response/work. Must measure the entire assay and rerun gates 2–3; not selected over the measured tau=2 candidate. |
| Same | 3. Add integral action, compression feedforward derivative, or direct depth spring. | **OWNER DECISION: law change**; plan:674–695 / brief:523–540 specify gas law; brief:323 forbids a later depth spring. | Additional state/digest/ABI obligations may follow; full earlier-gate/reference review. Does not follow from a P-only steady error, since none was diagnosed. |
| Same | 4. Increase bladder capacity, gas-rate ceiling, fuel subsidy, or relax 60 s/1 u. | Capacity/geometry or acceptance changes need owner review; gas-rate is assay-1 tunable but unsaturated here. | Does not address the measured unstable poles. Not recommended. |
| Floor hold | **1. Recommend explicit floor-plane friction stimulus together with calibrated righting**; retain COM-force run as disclosed tipping/sliding evidence. | **OWNER DECISION: define the under-specified acceptance stimulus.** The mechanics law, mu values, h, four sweeps and speed threshold stay unchanged. Plan:1028 / brief:661 do not say where the force acts. | Only assay load generation changes in addition to the calibration above; full 33-check run is mandatory. Gates 2–3 are unaffected by this harness-only patch in isolation and have been rerun for the full candidate. This does not claim a universally correct static solver. |
| Same | 2. Retain the COM-force hold requirement and redesign contact acceptance/solver to solve global static feasibility before kinetic fallback, accounting for tipping and support changes. | **OWNER DECISION: mechanics/acceptance design.** Replaces or augments plan:892–911 / brief:551–570, not a routine implementation correction. | Requires new independent contact oracles and threshold tests, law/version review, then gates 1–4 and all downstream checks. A solver cannot create an initial non-tipping equilibrium when the required COP is outside support. Not implemented/proved here. |
| Same | 3. Tune muDynamic toward muStatic or alter contact slop. | These are assay-1 constants, but four sweeps/manifold geometry rules are not tunable constants. | Earlier exploratory mutable-constant scratch trials .75/.79 dynamic friction reduced but did not remove slip; those are not release/determinism proof. More sweeps also failed above. Such changes disturb passing slip/rest/release cases and still require gates 2–4. Do not multiply N or shrink the test force to game .01. |
| Same | 4. Relax the speed bound to accommodate the sliding state. | **OWNER DECISION: weakens “holds”**, conflicts with plan:1021/:1028. | No credible static-friction acceptance remains. Reject. |

For every option: deterministic arithmetic is a requirement, not an assumption that any coefficient is physically correct. The recommended patches use exact binary32 hexadecimal literals, fixed loop orders, no RNG draws, no FMA or fast math, no platform transcendentals in the kernels. Candidate native/Wasm equality is actually measured below. Alternative solver/law options are unimplemented and have **no** determinism or gate-pass claim.

**Concrete proposed patches, not applied to the worktree.**

Apply in this order only after the coordinator has resolved the owner item:

1. [20261123_01_righting_calibration.patch](../build_m2b1_pr2/diag2/20261123_01_righting_calibration.patch): .12f → 0x1p+1f (bits 0x40000000).
2. [20261123_02_regulator_calibration.patch](../build_m2b1_pr2/diag2/20261123_02_regulator_calibration.patch): .02f → 0x1.99999ap-3f (bits 0x3e4ccccd), 5.f → 0x1p+1f (bits 0x40000000).
3. [20261123_03_contact_assay_OWNER_DECISION.patch](../build_m2b1_pr2/diag2/20261123_03_contact_assay_OWNER_DECISION.patch): load force at the horizontal projection of COM onto the floor plane, adding cross(lever,force) through the existing external-wrench hook. It uses config.depth, without adding another tank-depth literal.

These are proposals at frozen-through 0, not a substitute for the staged emitter. Patches 1→2 have sequential context. Applied to the new patchcheck source copy using patch --batch --fuzz=0 -p1, all three applied cleanly and produced the exact candidate source bytes ([patch_apply_check.log](../build_m2b1_pr2/diag2/audit_20261123/patch_apply_check.log)). Source differences in the candidate are exactly hydro_calibration.hpp and ocean_hydro_assay.cpp; tests, independent reference and mechanics/contact implementations are unmodified.

**Commands and measured results for the recommended set.**

The exact commands with expanded paths and raw exits are in commands.jsonl. Here C denotes build_m2b1_pr2/diag2/audit_20261123/candidate and O denotes build_m2b1_pr2/diag2/audit_20261123. All commands below were run via the nice-19 runner; they are descriptions of completed scratch runs.

~~~
g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I C/src \
    C/tools/ocean_hydro_assay.cpp -o O/assay
O/assay --assay 1 --trace O/candidate.trace.csv \
    --manifest O/candidate.manifest.json --build-id diag2-independent --target native

g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I C/src \
    C/tests/ocean_tests.cpp -o O/tests
O/tests --only hydro
O/tests --only hydro_step

g++ -O1 -g0 -std=c++20 -ffp-contract=off -fsanitize=undefined \
    -fno-sanitize-recover=all -DEVO_WORLD_OCEAN -I C/src \
    C/tests/ocean_tests.cpp -o O/tests_ubsan
O/tests_ubsan --only hydro
O/tests_ubsan --only hydro_step

g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I C/src \
    C/tools/ocean_hydro_reference.cpp -o O/reference
O/reference

/home/harit/opt/emsdk/upstream/emscripten/em++ -O3 -std=c++20 \
    -ffp-contract=off -DEVO_WORLD_OCEAN -I C/src \
    C/tools/ocean_hydro_assay.cpp -msimd128 -sENVIRONMENT=node \
    -sNODERAWFS=1 -sEXIT_RUNTIME=1 -sALLOW_MEMORY_GROWTH=1 \
    -sSTACK_SIZE=8388608 -o O/assay_wasm.js
node O/assay_wasm.js --assay 1 --trace O/wasm.trace.csv \
    --manifest O/wasm.manifest.json --build-id diag2-independent --target wasm
~~~

One initial focused-test **build** failed because my first source copy omitted wasm/ocean_wasm.cpp, which ocean_tests.cpp includes. It ran no tests. I copied the unchanged wasm directory into the candidate, then rebuilt successfully. The initial failure and retry remain in build_candidate_tests.log / commands.jsonl; no source fix or test weakening was involved.

| Verification | Raw exit/result |
|---|---|
| Candidate assay, native | 0; 33/33 PASS, all 12 windows complete |
| Candidate assay, Wasm | 0; 33/33 PASS |
| Gate 2 optimized hydro | 0; 11 groups passed, 0 failed |
| Gate 2 optimized hydro_step | 0; 12 groups passed, 0 failed |
| Gate 2 UBSan hydro / hydro_step | 0 / 0; same output bytes as optimized, no UBSan report |
| Gate 3 independent reference | 0; PASS; 11,508 increments, worst 3.46972549e-6; residual 3.94250924e-7, limit 2e-5 |
| Gate 3 independent actuator oracle | 5,754 checks, worst 1.27231878e-5, unchanged limit 2e-5 |
| Gate 3 fixed-load trajectories | 9 complete, 0 internal errors; model differences still reported only |
| Patch application | 0; zero fuzz, source bytes identical to tested candidate |
| Calibration-only original-COM assay control | 1; 32/33 PASS, floor speed 9.2599535 |
| Bootstrap plane-only / plane + 64 sweeps controls | 1 / 1; six failures remain, floor speeds 9.743128 / 9.746955 |

The optimized and UBSan 40,000-substep chain is 38e92bfe59ce6839, and the 85-body chain is fc30c6fa54db87a4. These differ from round 2 because the candidate intentionally changes mechanics/regulation and the constant digest. No historical baseline was changed. Passing suites establish their invariants, not unchanged trajectories.

| Previously failing metric | Candidate, native and Wasm | Bound |
|---|---:|---:|
| Roll tilt at 10 s | 0° at float projection resolution | ≤1° |
| Pitch tilt at 10 s | .09691329395° | ≤1° |
| Combined tilt at 10 s | .10087055546° | ≤1° |
| Target-96 error at 60 s | .00144958496 u | ≤1 u |
| Target-144 error at 60 s | .00450134277 u | ≤1 u |
| Floor static tangential speed, **floor-plane load** | .000050312432 u/s | <.01 |

All **27 originally passing named checks still pass**. Their values can change; none of their predicates was relaxed. Examples: floor-rest speed .00000421086, penetration .0000152588 u; above-threshold slip 14.8317814; positive-buoyancy gap .831070 u; paid-fin release gap 34.757919 u with positive charged motor work; sink force-balance relative error .00434883 <.02. Static depth drift remains zero, no tumbling, every incoming substep has 25 E. [followup_verified.json](../build_m2b1_pr2/diag2/audit_20261123/followup_verified.json) includes the old/new value comparison for every one of the 27 checks and the extended runs.

Native and Wasm CSV traces are **byte-identical**, including every recorded state word, energy/debit/subsidy, gas-rate and lambda field. Both hash to:

~~~
3ca2479ae64f7959849ee3cb527323f3742a2974fab150c3b21ee7ececea763d
~~~

Manifests differ only in target=native/wasm; all 12 window chains match. See [native_wasm_verified.json](../build_m2b1_pr2/diag2/audit_20261123/native_wasm_verified.json), candidate_assay.log, candidate_wasm_assay.log and their trace/manifest files. This is **assay-1 candidate parity**, not the unrun full gate-6 matrix or frozen fixture evidence.

**OWNER DECISION required before round 3 can pass gate 4.**

Choose whether the floor hold/slip acceptance is a **friction test with force in the contact plane** (recommended, tested conditional result above), or must retain the original **COM-height force**, with tipping/contact feasibility part of the requirement. The brief and plan specify magnitude but omit application height. Changing that stimulus must be explicit because it changes what “holds” proves.

If contact-plane loading is approved, adopt patch 3 and document that definition in the authoritative acceptance. Preserve the COM-load failure as a tipping/sliding diagnostic; do not represent its unchanged value as a pass. No mechanics law change or threshold relaxation is then proposed, but the baseline static solver's limitation remains disclosed.

If COM-height holding is required, do **not** authorize the proposed 33/33 as satisfaction of that case. The measured calibration-only result is still failed. A separate contact/acceptance design decision is needed, addressing global static feasibility, support moments and local kinetic-branch selection. More sweeps, a fake normal-load multiplier, or reclassifying 9 u/s as “hold” is not a demonstrated repair. The owner may instead choose a different physical law or acceptance, but this report supplies no tested patch for that alternative.

No other recommended change exceeds a numeric authorized range stated in these documents, because no such range is stated for these calibration variables. No rebaseline, relaxed time/angle/depth/speed threshold, or frozen header is recommended here.

**Round 3 sequence for coordinator authorization.**

1. Resolve the owner stimulus decision, record it in the implementation report/acceptance, then apply only the agreed proposals. Re-audit gate 1 and frozen scope. Preserve all round-2 failure evidence. Record source identity, toolchain, exact candidate bits/digests, seed/load/config and commands.
2. Rebuild and run gate 2 optimized and UBSan focused suites, then gate 3 independent reference against the actual edited worktree. The scratch evidence above is review evidence, not a substitute for validating the implementation that will be committed. Retain the strict 2e-5 oracle/residual bounds and the approved gate-2 capacity/atomicity/recovery checks.
3. Finish gate 4, **assays 1→2→3→4**, without bypassing the stop rule. Implement the still-missing staged calibration emission/freeze and genuine --check-all behavior. On successful assay 1 emit exact-bit stage-1 header/manifest, rebuild and rerun assay 1. Our scratch manifest remains stage 0; it must not be installed as a frozen artifact.
4. Implement/run assay 2: metered assay-1 load/trim; tow 40/82/108/120/150; independently measured drag/trim/channel/pump work; numerical force balance and free drive; sustained 108±5%, report actual peak against starting 130–150 without speed clamping. Include prescribed-power fatigue fill/recovery for fibre 0/.5/1, shared lambda, exhaustion, all-red zero capacity and no overshoot. Use the actual fibre-dependent recovery law, not four seconds for white fibre. Emit measured 82/108 power bits and stage 2, rebuild, rerun 1–2. Review reference-law transition 1→2 and ensure no inadvertent force-cap reduction.
5. Implement/run assay 3 on the fixed neutral/manoeuvrer/cruiser bodies: start 40/82/120, record actual speed, heading yaw and body omega, independently fitted path radius, sideslip, 90° response, lambda/fatigue; 82 yaw 2.60±.15; 40 body radius ordering and ≥3 ratio; low-sideslip radius agreement; 10 s righting release; configured/12 rad/s rail; **finite** 120 burst window. Freeze only assay-3 gains/stiffening, rebuild, rerun 1–3.
6. Implement/run assay 4: 120 s straight toroidal level/trimmed 82 cruise, geneCost=0, metered 25 E **at each incoming mechanical substep**. Require basal .80, maintenance .10, motor .60, total 1.50±.02 E/s, total debit 180±2.4 E. Explain gas/trim spending and preserve injected-fuel ledger. Turning and blocked-thrust trials must charge additional work; verify 3× excess-power billing/free recovery. Emit stage 4, rebuild, rerun all preceding assays and a real --check-all. Never tune a prior freeze silently.
7. Gate 5: complete versioned hydro/mechanics fixture drivers and fixture-mode refusal checks; build native/Wasm drivers and assays offline. Compare generated outputs native==Wasm **before** installing new fixtures; then prove native==Wasm==installed fixture. Record exact digests/versions/metadata. Do not replace historical Ocean baselines or the M2a fixture.
8. Gate 6: integrate fixture/assay/reference checks into parity and run the **full** matrix, with FAST/ONLY/NO_TESTS/NO_EYE unset; APP_TWINS=all BODY_TWINS=all and bounded JOBS/BUILD_JOBS. Preserve raw status/output. Apply only the plan's narrow disclosed life_cap_fixture_s1 body-twin exception if it is genuinely the sole failure; prove every condition at plan:1392–1414 rather than swallowing exit 1. All other failures block completion.
9. Gate 7: uninstrumented component timing and actual memory, native and Wasm sequentially with no simultaneous builds. Check A/A variation ≤3%; retain raw paired measurements. Measure each column size/capacity and allocation overhead, construction/cold-export/reset peaks; coefficients≤1024 B, support≤256, state≤96, resident physics/genes/owner≤1404 B/fish including capacity effects. The focused unit payload printout and one-fish assay do not establish the resident ceiling or a performance gate. Document PR 3's remaining whole-world 2000-fish paired Wasm performance obligation.
10. Gates 8–9: rebuild Ocean and Classic modules with offline matching emsdk, nice 19 and bounded jobs; confirm committed module bytes unchanged as expected for internal-only kernels. Investigate any unexpected freshness difference. Do not touch Classic pins by hand.
11. Gates 10–11: native-serial configure/build/ctest, disclose SFML availability; Turbo handoff, shader-slot, materials, mock-three and installed local TypeScript checks. No dependency downloads. No browser/live-rendering claim for this internal-only PR; leave PR 3's lifecycle/rendering/checkpoint/export obligations explicit.
12. Gate 12: final diffs against recorded fixed PR-1 base, git diff --check/status, all law/ABI/digest/fixture/calibration/timing/memory evidence, changed-file inventory and module hashes. Confirm production stepping/lifecycle, public refusal/config, fingerprint/checkpoint APIs, renderer, src/core, Classic and historical baselines/M2a fixture remain within frozen scope. No commit/merge/deploy/rebaseline is authorized by this diagnosis.

The original worktree therefore remains stopped at gate 4. The measured deliverable here is a reviewable, conditional scratch remedy and a documented owner decision, with gates 2–3 and assay-1 determinism checked for that candidate.


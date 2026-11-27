Build **M2b1 on M2a `7585381`** as a complete, opt-in mechanics and energetics replacement. Use the [approved v2 design](/home/harit/finfolk/codex/docs/m2_design_v2.md), with the [corrected formulas and tensor model](/home/harit/finfolk/codex/reviews/2026-11-09_m2v1_check_server_codex.md) and [M2a handoff notes](/home/harit/finfolk/codex/reviews/2026-11-09_review_pr76_m2a_619907b_codex.md).

I read those sources, the spine, Gemini’s review, and the round-2 M2a snapshot. No files were created or modified; no builds or calibration assays were run. Numerical values below are **starting constants**, except the approved anchors: cruise reference 82 u/s, neutral cruise burn 1.50 E/s with the specified partition, κ default 0.75, physical-size rendering, and the 12 rad/s maximum angular-speed rail.

**1. Scope and flags**

Add `OceanConfig::hydrodynamicsEnabled=false`, accepted only at initialization. Enabling it requires:

- `bodyPlanPreviewEnabled=true`, appearance’s shapes bit, and valid M2a ownership and geometry.
- Supported geometry, material, mechanics, energetics, and export versions.
- `sizeDrift=false`, `cHold=0`, `cPress=0`, and `moveCost=0`. Reject incompatible requests explicitly.
- Finite, physically admissible M2 parameters, validated before narrowing or replacing the current world.

Resolve M2 defaults in the Ocean configuration adapter; leave `src/core` defaults unchanged:

| Setting | M2 default |
|---|---:|
| `metabolicRate` | 0.80 E/s |
| Structural/muscle basal split | 0.60 / 0.20 E/s |
| `minSpeed` | 0 u/s |
| Requested-speed ceiling | 150 u/s |
| `maxTurnRate` | 12 rad/s |
| Kleiber κ | 0.75 |

`hydrodynamicsEnabled` selects the tensor integrator, quaternion pose, paid motor requests, muscle fatigue, buoyancy, reserves, contact, funded reproduction, mouth envelope, and enabled checkpoint/fingerprint format. `bodyModel` retains its existing size/elongation inheritance and draw arithmetic; its legacy speed, turn, and metabolism multipliers cease to participate in M2 physics.

With hydrodynamics OFF, retain the complete historical movement, metabolism, feeding, interactions, birth acceptance, IDs, RNG schedule, rendering, and fingerprint output. Preview-only operation remains diagnostic and preserves historical simulation identity.

M2b1 must not introduce the M2b2 environment preset, food redistribution, predator turn limits or `predatorLaw=1`, E2 particles, swept mouth contact, gape retention, light-limited eyes, armour handling, barbel feeding, a neural ABI change, or evolutionary coexistence claims. Keep Classic, `src/core`, and the Red Queen engine unchanged.

**2. Data and the M2a handoff**

M2a’s measured geometry is authoritative. Use its exact binary32 reference volume, approximately **595.6 u³**, rather than a rounded literal or a smooth-body correction.

Define one mass unit as the mass of that volume of water:

```text
Vref = exact neutral faceted hull volume
ρw   = 1 / Vref                         mass/u³
```

Thus material densities 1.04, 1.10, 2.0, and 0.90 are ratios to water density. Geometric inertia in u⁵ becomes material inertia in mass·u² after multiplication by the corresponding density. The reported neutral hull inertia is not the final compound inertia.

Extend the birth compiler to provide:

| Required data | Contract |
|---|---|
| Material allocation | Separate tissue/jaw, eyes, storage/bladder walls, shell, and exposed fin material; volumes, masses, centroids, full second moments |
| Compound properties | Unloaded lean mass, muscle volume/mass, full inertia including products of inertia, construction-weighted mass |
| Load updates | Analytic first/second-moment bases for transverse inflation and lipid loading |
| Caudal loading | Chord samples after clipping, actual span/area/AR, loading correlation, material and added-water bending moments |
| Actuators | Areas, efficiencies, normals, root/centroid update bases, and force capacities |
| Support | Evaluated canonical ring vertices or equivalent cached powers, bounds, stable vertex/face IDs |
| Mouth | Canonical centre and its inflation update basis |
| References | Neutral lean/muscle/material masses, reference trim, motor powers, and coefficient digest |

Use the full parallel-axis assembly:

```text
M = Σ mi
c = Σ(mi ci) / M
I = Σ [Ii,centroid + mi (|ci−c|² Identity − (ci−c)(ci−c)ᵀ)]
```

Do not subtract overlapping organ estimates from uniform-hull inertia without defining their occupied material. A suitable material law uses a fixed positive-volume partition of the canonical hull, allocates jaw and paired eye compartments nearest their canonical locations in stable cell order, allocates walls, and leaves the remainder as tissue. Fractional final cells preserve the requested volumes. Allocate paired eyes symmetrically. Record this as a material law separate from geometry law 1.

Starting volumes and densities are:

```text
Vjaw   = .02 Vhull (gapeFraction/.40)³
Vwall  = .02 (β + fatTraitFraction) Vhull
Vmuscle = .30 VremainingTissue

tissue/jaw/walls: 1.04 ρw
fins/eyes:       1.10 ρw
shell:          2.00 ρw
lipid:          0.90 ρw
gas:            negligible mass
```

All allocations must remain nonnegative. Developmental caps operate on expressed values.

**Coordinate contract.** Retain M2a’s canonical right-handed frame:

```text
body +x = toward tail       forward force is −x
body +y = starboard
body +z = dorsal

world = (legacy x, −depth, legacy y)
world up = (0,1,0)
```

The quaternion maps canonical body coordinates into this world frame, matching the existing three.js world axes. Positive `STEER_X` requests starboard turning, hence negative body-z yaw torque; positive `STEER_Z` requests downward heave and negative body-y pitch torque.

Keep geometry coordinates relative to their canonical origin. Compute every force lever, mouth position, and support point relative to the **current loaded material COM**. The quoted “10.2 u behind the snout” is not a canonical-origin coordinate.

Use a separate dense column:

```cpp
struct HydroState {
    float com[3];
    float vGround[3];
    float quat[4];          // w,x,y,z
    float LWorld[3];        // material angular momentum about COM
    float gasContent;      // surface-pressure-equivalent volume
    float tailDrive;
    float tailYaw;
    float requestedSpeed;
    float fatigue;         // motor-work equivalent
    std::uint32_t status;
};
```

Target at most 96 B/state. `foodReserves` remains the sole fuel ledger. Water samples and solver workspaces are transient. Reuse M2a’s owner IDs; compact every column with the same stable alive mask. Missing, reordered, or uncompiled enabled data is an error, never a reason to continue with legacy movement.

Separate compact simulation coefficients from diagnostics. In enabled worlds, compile M2a geometry at birth, retain the compact physics/support representation, and reconstruct cold inspector metrics on demand. Avoid retaining and exporting a second 904 B diagnostic record for every fish on every sync.

Proposed resident ceilings, excluding existing neural/appearance storage:

| Column | Ceiling/fish |
|---|---:|
| Physics coefficients, including tensor/update bases | 1,024 B |
| Canonical support cache | 256 B |
| HydroState | 96 B |
| Physical genes | 20 B |
| Owner ID | 8 B |
| **Total** | **1,404 B; 2.81 MB at 2,000 fish** |

Aim below these ceilings. Report `sizeof`, vector size/capacity, temporary construction memory, and export peaks. The old 640 B estimate does not cover the expanded implementation.

**3. Laws and update order**

**Stage expression: no cost before benefit.** Build a separate, versioned mechanics expression from immutable alleles:

| Trait | M2b1 expression |
|---|---|
| Hull, fins, size/elongation, bladder, fat, fibre | Active |
| Gape | Neutral `.5` expression |
| Eye-size allele | Neutral `.5` expression, still fitted to the head |
| Armour | Zero shell |
| Barbels | Absent |

Dormant alleles still inherit and mutate. They must not affect mass, inertia, drag, maintenance, construction cost, muscle displacement, support, or another organ’s developmental cap. Apply stage masking **before** development. Test those indirect paths explicitly. The inspector may show inherited and stage-expressed values separately.

**Reserves and inflation.**

```text
Mfuel = max(E,0) / 500
Vfuel = Mfuel / (.90 ρw)
Ecap  = 500 · .90 ρw · Vreserve

k = sqrt(1 + (Vgas + Vfuel)/Vhull)
```

For the neutral body, `Ecap≈45 E`. Keep physical capacity proportional to compartment volume; do not Kleiber-scale it.

Transversely inflate the canonical hull with `T(k)=diag(1,k,k)`. Update material first/second moments analytically, reattach roots, and draw the same loaded geometry. Exposed fins retain their birth planform areas/normals in this reduced hydrodynamic law; their application points follow the compiled root-update bases.

All reserve writes go through an Ocean helper: metabolism, feeding, sharing, fighting, reproduction, initialization, and reseeding. It applies capacity, records waste, and updates mass and carried momentum consistently. Co-moving fuel loss must not accelerate the fish. Ingested fuel mixes its carried momentum into the body. Bound fight transfers by available donor fuel while retaining the existing outcome draws; sharing and receiver overflow must not create energy.

**Body resistance.** Compute skin friction at birth:

```text
Cf = .008 · (L/20)^−.2       L = 20 S E
```

Use portable power evaluation once at birth. Distinguish this reference length from the measured 24 u neutral hull.

At runtime:

```text
Af    = k² Af0
Aside = k Aside0
Aplan = k Aplan0
Sw    = k² Sw0
Fineness = hullLength / sqrt(4 Af/π)

CdForward = .08 + .90/clamp(Fineness,1,30)² + .25 B0

Kx = CdForward Af + Cf Sw
Ky = 1.10 Aside + Cf Sw
Kz = 1.10 Aplan + Cf Sw
```

Add `.025 Σ Afin` profile drag once to each translational axis. Armour roughness is zero in this stage.

Using the rounded unloaded neutral measurements gives approximately:

```text
Kx including profile ≈ 15.42 u²
Ky including profile ≈ 139.78 u²
Kz including profile ≈ 162.88 u²
```

These exclude fin-normal tensor resistance and are checks, not calibration literals.

For translation, use diagonal damping entries `.5 ρw Ki |ui|`. Include body rotational resistance: from the loaded hull’s COM-relative volume covariance `Ch`, form

```text
Jbody = Σi Khull,i [ei]× Ch [ei]×ᵀ
Dbody,rot = .5 ρw s Jbody
```

Exclude the fin-profile addition from `Khull` here. This gives the hull a geometry-dependent rotational resistance without a turn bonus.

**Birth-summed fin tensors.** Traverse caudal, dorsal, anal, pectoral R/L, pelvic R/L in that order:

```text
wj = (nj, rj × nj)
dj = .5 ρw Cn Aj                 Cn starts at 1.10
maj = .25 ρw Aj meanChordj

Dfin = Σ dj wj wjᵀ
Afin = Σ maj wj wjᵀ
```

Zero-area fins contribute exactly zero. Store all 21 independent entries of each symmetric tensor.

Compile tensors about the canonical origin. For a centroid update `pj(k)=pj0+(k−1)bj`, compile constant, linear, and quadratic tensor bases:

```text
w0 = (n, p0×n)
w1 = (0, b×n)

D(k) = D0 + t D1 + t² D2        t=k−1
D1 = Σ d(w0w1ᵀ+w1w0ᵀ)
D2 = Σ d w1w1ᵀ
```

Use analogous added-mass bases, then translate both tensors to the loaded COM by a fixed spatial congruence. Never rebuild them by traversing fins during a substep.

Body added masses start at:

```text
maX = .05 ρw VbodyDisplaced
maY = ρw VbodyDisplaced · halfDepth/halfWidth
maZ = ρw VbodyDisplaced · halfWidth/halfDepth
```

Derive their rotational moments and origin/COM shifts from the hull moment bases. Add fin added mass once:

```text
Meff = rigidMaterialMassMatrix + Abody + Afin
```

Retain all translation–rotation cross terms.

**Exactly two mechanical substeps.** The production outer step is `.016f`; use two `.008f` substeps. Sensing, neural evaluation, internal-state updates, and their RNG occur once per outer step.

Sample water at the COM once per outer step and hold it in world coordinates for both substeps:

```text
UwaterWorld = (flow.x, −flow.d, flow.y)
u = Rᵀ(Vground − UwaterWorld)
ω = Ibody⁻¹ Rᵀ LWorld
z = (u,ω)
s = sqrt(|u|² + Lc²|ω|²)        Lc = L/2
```

Use:

```text
Dtotal = Dbody + s Dfin + Dinduced + Dbrake
```

Evaluate nonlinear weights from the substep’s incoming state. Every passive contribution must be positive semidefinite.

For righting, let:

```text
b = Rᵀ worldUp
δ = .12 · loadedHalfDepth
Kmeta = gravity · ρw · Vdisplaced · δ
τmeta = Kmeta (ez × b)
Pmeta = rotational diag(1,1,0)
```

This is the declared metacentric offset above COM. Check the cross-product sign with a tilted body: its torque must restore upright orientation.

Solve once:

```text
A = Meff + h Dtotal + h² Kmeta Pmeta
rhs = Meff z + h(Qactive + Qgravity/buoyancy) + h(0,τmeta)
A znext = rhs
```

The `h²` term is the positive, upright tangent approximation for implicit righting. Do not apply another explicit righting kick afterward.

Use fixed-order, unpivoted LDLᵀ, indices 0…5. Scale angular coordinates by `Lc` before factorization to reduce unit conditioning. A nonpositive/nonfinite pivot is a physics failure, not something to clamp or repair silently.

For reference, LDLᵀ is:

```text
Lii = 1
Dii = Aii − Σk<i Lik² Dkk
Lji = (Aji − Σk<i Ljk Lik Dkk) / Dii
```

For fixed load/pose with no external work, the damping solve must satisfy:

```text
znextᵀ Meff znext ≤ zᵀ Meff z
```

Carry velocity and material angular momentum in world coordinates. Apply the solved increments through the current frame:

```text
Vground,next = Vground + R(unext−u)
LWorld,next  = LWorld + R Ibody(ωnext−ω)
```

Then advance COM and quaternion:

```text
COMnext = COM + h Vground,next
qnext = normalize(q + .5h q⊗(0,ωnext))
```

Recompute angular velocity from world angular momentum under the new pose. This preserves ground velocity and material angular momentum during an unforced frame change. Added mass is an acceleration-response approximation; M2b1 carries no independent fluid momentum history.

Do not apply legacy current advection, heading rotation, depth springs, pitch clamps, or soft floor pushes afterward.

**Caudal loading and actuator references.** At birth, calculate loading correlation from clipped chord samples `ci` and elliptical loading `ℓi=sqrt(max(0,1−ηi²))`, with fixed trapezoidal weights:

```text
e = clamp((Σ wi ciℓi)² /
          ((Σ wi ci²)(Σ wi ℓi²)), .35, 1)

ηtail = .35 + .45(e ARactual)/(e ARactual+2)
τtail = clamp(.03 + .12 sqrt(Jspar/JsparNeutral), .03, .50)
```

`Jspar` includes fin material and the corresponding spanwise distribution of added water. An absent caudal fin has zero capacity and no division by area.

Keep three references separate:

```text
Uref = 82                         energy pricing
Usus_ref starts at 108            neutral sustained capacity
Uact starts at 150                actuator force reference

TcapNeutral = 2 Dneutral(Uact)
Aprop = Acaudal + .5 Σ Apaired
Urow = sqrt(2 TcapNeutral/(ρw Aprop))
```

Freeze the reference after assay 2. Re-anchoring energy at 82 must not lower the force ceiling inadvertently: a constant force ceiling of `2D(82)` would limit a quadratic-drag swimmer to about 116 u/s.

Allocate forward capacity by `Acaudal` and `.5 Apaired`. Filter tail forward and yaw requests independently:

```text
anext = (a + h arequest/τtail) / (1+h/τtail)
```

Caudal yaw force starts at:

```text
Ftail,y =
 − k_tail_yaw · .5ρw Acaudal (U²+Urow²)
   · tailYaw / (1+(U/Ustiff)²)

k_tail_yaw = .25
Ustiff = 108 u/s
```

Apply it at the loaded caudal centroid and charge its power. It must not rotate heading directly.

For each paired fin, with `l=r×n`, use:

```text
c = clamp(−kheave dive nz
          −kyaw yaw lz/L
          −kpitch dive ly/L, −1,1)

Fcontrol = .5ρw (|vlocal|²+Urow²) A c n
```

Start `kheave=kpitch=1`; calibrate paired-fin yaw authority in assay 3. Paired rowing efficiency starts at `.35`.

Control-fin induced drag uses `CDi=c_actual²/(πeAR)`, opposing local flow. Add it as a dissipative tensor contribution; count it once. Negative forward-controller requests deploy bounded passive braking rather than setting speed.

**Action adapter.** Preserve action indices and outer-step evaluation:

```text
Triangular:
drive = clamp(.5(MOVE_FORWARD+1),0,1)
Urequest = minSpeed + drive(maxRequestedSpeed−minSpeed)
yaw = responsiveness · STEER_X

Push:
Urequest += 50 responsiveness SPEED_ADJUST dt
Urequest = clamp(Urequest,minSpeed,maxRequestedSpeed)
```

In own-frame push mode, `STEER_X` requests yaw. In world-frame mode, project `(STEER_X,STEER_Y)` onto body starboard. Project its forward component into the forward-force bias. `MOVE_FORWARD` supplies another bounded forward-force bias.

Start the forward controller at:

```text
Trequest =
 Destimate(Urequest)
 + Meff,forward (Urequest−Uforward)/.25s
 + bounded forward-action bias
```

Use `Meff,forward·Uref/.25s` as the unit force-bias scale, then clamp to actuator capacity. `STEER_Z` requests both heave and nose-down control. Wall avoidance contributes bounded actuator requests through this same adapter.

Remove triangular mode’s `(1−drive)` turning penalty. `minSpeed` is a paid target floor.

Preserve push mode’s existing condition and exactly three `MOVE_RANDOM` draws once per outer step. Project their held result into the same force requests; never draw during substeps.

**One motor limit, fatigue load, and fuel charge.** For each independently commanded force channel:

```text
Prequest = Σ |Fa| (|vlocal,a|+Urow)/ηa + Ppump
```

Price opposing channels separately. Tail yaw uses tail efficiency; paired control/rowing starts at `.35`. Passive drag and contact do not enter this sum.

At the frozen reference load:

```text
P0 = PmotorNeutral(Usus_ref) · Vm/Vm0

a(f) = .55+.90f
Psus = a(f) P0
Ppeak = [a(f)+2(1−f)] P0
Fmax = τburst(Ppeak−Psus)

τburst = 2 s
γ = .5
```

Before applying any active work:

```text
Pavailable =
 Psus + min(Ppeak−Psus, max(0,(Fmax−F)/h))
```

Also limit work to available fuel. After reserving basal/maintenance expenditure, let `qFuel=Eavailable/(workConversion·h)`:

```text
Pfuel = qFuel                         if qFuel≤Psus
        (qFuel+2Psus)/3                otherwise

λ = min(1, Pavailable/Prequest, Pfuel/Prequest)
```

Use λ=0 for zero fuel and handle zero request without division. Scale every active force and commanded gas-content change by this same λ.

```text
P  = λ Prequest
Pa = min(P,Psus)
Pb = max(0,P−Psus)

motorFuel = workConversion h(Pa+3Pb)

Fnext = clamp(F + h[
 Pb − min(F/h, γ max(0,Psus−P))
], 0,Fmax)
```

Fatigue is a work-equivalent load. Recovery is free and receives no second fuel charge. All-red muscle has zero burst excess and zero fatigue capacity; no division by `Fmax` is needed. Motors still pay when contact blocks motion.

**Metabolism.** Use the explicit basal partition:

```text
rLean = MleanBirth/MleanNeutral
rMuscle = MmuscleBirth/MmuscleNeutral
leanFactor = rLean^κ

Bstruct = .60 leanFactor
Bmuscle = .20 rMuscle(.4+1.2f)
Bbasal = Bstruct+Bmuscle
```

At neutral, this is 0.80 E/s. White/red neutral-sized muscle gives 0.68/0.92 E/s. Cache the power at birth; special-case κ=1 with linear arithmetic.

Proposed neutral maintenance allocation, to freeze in assay 4:

```text
Bfin   = .04 Mfin/Mfin0
Bwall  = .04 Mwall/Mwall0
Blipid = .02 Mfuel/MfuelRef       MfuelRef = 25/500

Bmaintenance = Bfin+Bwall+Blipid
```

Eye, barbel, armour, and gape surcharges are zero in M2b1.

```text
workConversion = .60 / PmotorNeutral(82)

fuelBurn =
 h(Bbasal+Bmaintenance+geneCost·genomeLength)
 + motorFuel
```

Retain age and reproduction/interaction timer updates exactly once per outer step. Do not call legacy metabolism as well.

**Gravity, gas, and buoyancy.**

```text
gravity = 400 u/s²
Hp = D/2
Pressure = 1+depth/Hp
Vgas = min(VgasCapacity, gasContent/Pressure)

Vdisplaced =
 Vhull + Vgas + Vfuel + VexposedFinMaterial

Fdown = gravity(M−ρw Vdisplaced)
```

Hull-contained organs/walls are already included in hull displacement.

Let `dtarget=bodyBuoy·D` and downward ground velocity be `vd`. Start the regulator at:

```text
Vneutral = M/ρw − Vhull − Vfuel − VexposedFinMaterial

Vtarget = clamp(
 Vneutral
 + .08 Vhull(depth−dtarget)/D
 + .02 Vhull vd/Uref,
 0,VgasCapacity)

Gtarget = Pressure Vtarget
GdotRequest = clamp((Gtarget−G)/5s, −.02Vhull/s, +.02Vhull/s)
```

Keep `G≥0` and bound it by the maximum configured-pressure capacity. Passive compression changes volume without fuel expenditure. Commanded regulation is priced:

```text
p0 = ρw gravity Hp
Ppump = p0 |GdotRequest|/ηpump       ηpump starts at .25
Gnext = G + h λ GdotRequest
```

This is the declared pumping/venting work law, using no hot logarithm. Insufficient bladder capacity requires paid fin support. A bladder-less fish has zero pump request.

**Floor and other boundaries.** Use the inflated canonical hull, not a COM clamp or bounding sphere alone.

```text
gap = D − (COMdepth + downwardHullSupport)
```

Predict contact, construct up to four deterministic hull contact points, and solve normal/tangent impulses in stable point order with four fixed sweeps. No warm-start state is required initially.

For inward normal `n`, body lever `r`, and ground-relative contact velocity:

```text
Jdir = (n,r×n)
an = Jdirᵀ Meff⁻¹ Jdir
Jn = max(0,−vn/an)
```

Use accumulated unilateral impulses, zero restitution, and a predictive gap constraint to prevent crossing. Correct residual penetration geometrically without adding a bounce velocity.

Solve the two tangent directions for the impulse that cancels ground-relative slip:

```text
static admissible: |Jt_required| ≤ μstatic Jn
otherwise:        |Jt| = μdynamic Jn, opposing slip

μstatic starts at .8
μdynamic starts at .6
```

Use the same effective-mass response for the contact impulse and its torque. The floor pushes and never pulls. Upward buoyancy/thrust releases contact. Normal reaction does no work at rest; friction dissipates motion.

A floor-resting fish is cheap because its motors and regulator are idle. Contact grants no billing exemption.

Use corresponding zero-restitution hull contact at surface/glass faces, in x/y/depth face order. Wrap horizontal COM coordinates only for toroidal worlds. Refresh analytic load/support after serial reserve transactions and resolve any resulting boundary overlap before publishing the step.

**Angular-speed rail.** Enforce:

```text
|ω| ≤ min(configured M2 maxTurnRate,12) rad/s
```

Apply it to total angular speed. Make the projection dissipative despite added-mass coupling. Partition `Meff=[A B; Bᵀ C]`; for angular scale `a≤1`:

```text
ω′ = aω
u′ = u + A⁻¹B(ω−ω′)
```

This preserves effective linear momentum and decreases the rotational Schur-complement energy. Do not refund motor fuel.

**Funded reproduction.** Preserve age, cooldown, population, genetic gate, lineage, inheritance arithmetic, and visit order. Replace M2’s fixed energy checks/payment:

```text
Ebuild(child) =
 c_build [
 Mtissue + 2Mfin + 3Marmour + 2Meye + Mwall
 ] / MleanNeutral

c_build starts at 6 E
EnewbornTarget = 25 rLeanChild^κ
Enewborn = min(EnewbornTarget,EcapChild)

threshold(parent,child) =
 20 rLeanParent^κ + .5 Ebuild(child)

parent share = .5(Ebuild+Enewborn)
```

Each parent must pass its threshold and fund its share. Debit only the actual funded amount.

After cheap eligibility and the genetic gate, reserve a child ID, construct all candidate genomes, inherit size/elongation/buoyancy, and compile its body. Then test funding. Rejected candidates retain consumed IDs and draws; they produce no payment, cooldown, or birth event. Do not resample.

Accepted children start at rest relative to local water, with zero angular momentum, zero fatigue, and zero gas content; their regulator must pay to establish trim. Founders/reseeds are explicit, logged construction/fuel/initial-trim subsidies.

**Mouth envelope.** In M2 worlds, replace the pickup sphere immediately:

```text
mouthWorld = COM + R(mouthCanonical(k)−loadedCOMCanonical)
capture iff minimumImageDistance²(item,mouthWorld) ≤ (r_env S)²

r_env starts at 5 u
```

Query the food grid around the mouth; do not retain a hidden 24 u COM broadphase limit. Keep fixed food energy and current item semantics. Record capacity overflow as waste.

This is an endpoint envelope. Sweeping, aperture normals, particle diameter, retention, and barbel reach remain M2c work. Leave `r_env` provisional until M2b2 assay 5.

**4. Determinism, checkpoints, and parity**

All new state and simulation accumulation use binary32, fixed operation trees, fixed traversal order, `-ffp-contract=off`, and no fast math. Preserve M1/physical inheritance’s existing specified double intermediates and binary32 stores.

Confine new powers, loading calculations, and transcendental decoding to birth. The hot hydro path uses arithmetic, comparisons, fixed loops, correctly rounded square root, and quaternion algebra. Existing portable neural math remains unchanged. No adaptive substeps, pivot selection, unordered reductions, runtime integrator fallback, or GPU feedback.

Keep the sequential patch model only as an offline native reference. Report tow, turn, and relaxation differences; Gemini’s “under 3%” estimate is not established evidence.

Introduce an enabled fingerprint format, for example format 5, while preserving format-4 OFF output. Its combined chain includes:

- Relevant M1 shape alleles, size/elongation/buoyancy, and inheritance configuration.
- Physical alleles, stream keys, owners, IDs, counters, and rejection history affecting continuation.
- HydroState, mechanics/energetics/material/expression versions, initialization flags, frozen references/constants, and derived-coefficient digest.
- Existing base simulation state.

Hash explicit fields, never padding. P1 pattern values remain outside the simulation hash.

Add an Ocean portable checkpoint envelope containing the complete base continuation state, appearance record, physical genome, HydroState, law/configuration blocks, and coefficient digest. Encode float bits and integers explicitly in little-endian order. Recompile derived coefficients on load and require digest equality. Validate into a temporary world; unknown required versions or malformed ownership fail atomically.

Save only at outer-step boundaries. Preserve quaternion bits on load rather than renormalizing them. Prove native→wasm and wasm→native continuation every step.

Existing whole-memory web saves remain tied to the exact wasm hash. Extend their validation and Turbo handoff to the new allocations; they do not become portable checkpoints.

**5. Calibration assays 1–4 and performance**

Use scripted neutral clones, with heritability, food, reproduction, predators, and reseeding disabled unless a subcase explicitly requires them. Every result records configuration, versions, reference load, coefficient digest, actual constants, target/build identity, and raw measurement windows. Freeze assays in order.

| Assay | Harness and acceptance | Constants/reference frozen |
|---|---|---|
| **1 — static tank and contact** | One neutral fish, `D=240`, target depth 120, `E=25`, still water. Solve feasible neutral gas. At equilibrium require `|M−ρVdisp|/M≤1e−5`, `|vd|<.01 u/s`, depth drift `<.1 u` over 60 s. Release from 10° roll/pitch: return within 1° in 10 s, with no tumbling. A ±24 u target-depth step must settle within 1 u in 60 s. | Exact Vref/material normalization, gravity, Hp, neutral gas/COM/inertia, metacentric offset and regulator gains |
| **1 floor subcases** | Bladder-less clone rests for 60 s with speed `<.01 u/s` and penetration `<.01 S u`. At `0.9 μstatic N` tangential load it holds; at `1.1 μstatic N` it slips. Positive buoyancy/upward thrust releases contact. Measured sinking terminal speed matches the force-balance prediction within 2%; roughly 12 u/s is a starting expectation. | Friction coefficients and contact tolerances |
| **2 — tow, drive, and fibre** | Hold the assay-1 reference load/trim. Tow at 40/82/108/120/150 u/s; measure drag, trim, and actuator work. Free straight runs must reach the numerical force-balance speed within 2%. Target sustained neutral speed is initially 108 u/s; accept within 5%. Starting peak-speed window is 130–150 u/s; record the actual value rather than forcing 136 through a speed clamp. | Kx/reference drag, measured tail efficiency/loading, Uact/Urow, PmotorNeutral(82), P0, Usus_ref, tail response |
| **2 fatigue subcases** | At prescribed constant peak work, an initially recovered neutral fish fills fatigue capacity in `2 s±2h`. At zero work it recovers in `4 s±2h` for γ=.5. Test f=0/.5/1, shared λ, fuel exhaustion, and no fatigue overshoot. | τburst, γ, force-cap sufficiency and capacity law |
| **3 — step steer** | From pre-turn straight requests 40/82/120 inject unit yaw; report actual speed, heading, fitted radius, sideslip and response. Neutral 82 heading `2.60±.15 rad/s`; radius near 31 non-gating for PR 2 (D4). At 40 require manoeuvrer radius < neutral < cruiser, ratio ≥3. Apply D1 plus D2 and both D5 checks below. Never exceed configured rail or 12 rad/s. | Only paired yaw gain, tail yaw gain and stiffening; fixed-law gains are excluded as stated below. |
| **4 — calorimetry** | Straight toroidal swimming at request 82, `geneCost=0`; essentially level trajectory with disclosed body pitch and depth bias (corrected D-M2b1-7 below). Require basal `.80`, maintenance `.10`, restrained-reference motor `.60` to binary32 roundoff and free-cruise motor `.60±.008` (D-M2b1-7), and total `1.50±.02 E/s`. Require no unexplained gas/trim expenditure. Turning and blocked-thrust subcases must charge their additional motor work. | Maintenance allocation and workConversion; confirms the 3× excess-power charge and free recovery |


Acceptance-definition amendment (corrected coordinator instruction, 2026-11-25):

> **D-M2b1-7 — PR-2 assay-4 acceptance amendment, under the recorded owner delegation (coordinator, 2026-11-25; corrected after an independent check).**
>
> **Unchanged:** `workConversion=.60/PmotorNeutral(82)`, the frozen denominator `44590.30078125` (`0x472e2e4d`), and every stage-1/2/3 constant and freeze. D3 remains not adopted.
>
> **Restrained reference.** Gate a freshly exercised restrained neutral reference at request 82 at `.60 E/s`, with absolute error at most `8*float_epsilon*.60`. Use the production conversion and measured work. Multiplying the two stored calibration values alone is not sufficient evidence.
>
> **Free cruise.** After the unchanged 600 s free-cruise preparation, measure the prescribed 120 s with metered incoming 25 E, `geneCost=0` and unchanged requests. Gate the finite measured motor component inclusively at `.592` through `.608 E/s`. This is a newly authorized component performance tolerance: the total's relative tolerance applied to the nominal motor share.
>
> **Attitude and depth.** This amendment accepts the reproduced PR-2 calorimetry state's essentially level trajectory, together with its disclosed body pitch and target-depth bias. It does not certify upright body attitude or target-depth tracking. Keep the existing straightness and settling checks. Report:
> - actual speed;
> - signed attitude;
> - depth versus target;
> - vertical velocity;
> - integrated vertical displacement;
> - stored drift;
> - regulator activity;
> - paid pump work.
>
> **Accounting.** Keep all other assay predicates and accounting tolerances. Independently reconstruct channel and pump work at the actual state, and include pump work once. Apply the prescribed motor/fatigue formula, and check every actual ledger subtraction using the prescribed binary32 arithmetic. The ±.008 performance band must never act as an accounting-error tolerance. These stay gating:
> - basal and maintenance;
> - total/debit;
> - metering;
> - extra work;
> - blocked thrust;
> - excess power;
> - free recovery.
>
> **Planted faults.** Exercise the ACTUAL measurement and predicate paths (end to end, not synthetic inputs to threshold helpers) with:
> - conversion errors of ±1%;
> - both out-of-band free-cruise values, `.591` and `.609 E/s`;
> - a cruise-only accounting fault that stays INSIDE the motor band, for example a `.0005 E/s` undercharge at the reproduced state. This fault must fail an independent accounting predicate.
>
> Each must exit nonzero and refuse to emit stage 4.
>
> **Disclosure.** Gate the free-cruise motor measurement, and also disclose its signed deviation from `.60`. Report the measured 1.38° driven pitch and the depth of 86.1 versus a target of 120 as known limitations, with the diagnosed trim, load and regulator mechanisms. Do not claim that these exhaustively account for the deficit.
>
> **Acceptance.** Reproducing `.592894794 E/s` satisfies only the amended motor performance predicate. Stage 4 may be emitted only after every required predicate passes. After that come the rebuild, the positive and faulted `--check-all`, and the prescribed final native/Wasm checks. Otherwise, stop under the plan's stop rule.
>
> **Margin.** Report the lower-bound margin: about `.000894794 E/s`, or `.149132` percentage points. Determinism supports repeatability for a fixed build and fixed inputs. After any change, acceptance is established by final-build parity and reruns.

Owner acceptance-definition amendments, 2026-11-23 (D-M2b1-3 through -6; diagnosis 2, “D1–D5 rewritten consistently”; D4 uses the owner-elected weaker clarification):

**D1 (adopted):**

For the righting release, set speed, yaw, dive and forward-bias requests to zero for 625 outer steps; preserve filtered tail state and keep the paid gas regulator and passive braking active. Roll/pitch must return within 1° of upright after those 10 s, including after the finite-120 burst.

**D2 (adopted):**

In addition to the command-release upright check, run a separate driven yaw-release diagnostic from the same post-turn state: set yaw, dive and forward-bias requests to zero, retain the pre-turn speed request, and use 82 after the finite-120 burst. Keep all filters, regulator, passive brake and fuel pricing unchanged. Compare signed roll and pitch after 625 outer steps with the same body's 60 s, metered-25 E, no-yaw/no-dive straight control at that retained request, after aligning horizontal headings. Require each angle within 1° of its matched control. Report the control's absolute roll/pitch, actual speed, depth, vertical velocity, gas expenditure and remaining settling separately. Passing this relative-trim diagnostic does not replace D1's absolute upright requirement or establish assay-4 acceptance.

**D4 (adopted):**

The 40/82/120 labels name pre-turn straight-speed requests, and 120 names a finite burst. Always report actual turn speed, recorded-position radius and sideslip. Radius near 31 is a non-gating design goal for PR 2; the neutral-82 numeric heading target remains 2.60±.15 rad/s. Large-slip, reduced-speed turns may satisfy that numeric target and are not evidence of the 82-speed/radius-31 goal. Preserve the selected release checks and D5's separately eligible geometry checks.

**D5 (adopted):**

Fit the horizontal circle radius from actual torus-unwrapped recorded positions using a measurement-only fit; never substitute a speed/rate prediction for the fitted radius. Independently unwrap horizontal velocity course and horizontal forward heading over the same fit samples. Report mean horizontal speed U, speed range divided by mean U, absolute unwrapped course rotation, mean course rate, mean heading rate, their difference, sideslip, and both predicted radii and relative errors for every turn.

For every resolved turn with absolute unwrapped course rotation at least 5° and speed range at most 2% of mean U, require the fitted radius to agree with U/|mean course rate| within 5%, regardless of sideslip. This course-rate check exercises position-fit geometry independently of body heading.

Apply the separate fitted-radius versus U/|mean heading rate| identity only when the same resolution/speed conditions hold, maximum absolute sideslip is below 5°, and |mean course rate−mean heading rate| is at most 2% of |mean heading rate|. Require agreement within 5%. Preserve the finite-120 burst window; do not replace it with steady swimming.

Print each check's eligibility, exclusion reason and total eligible count. An ineligible check is not exercised, not passed. Report its measurements without asserting the identity. Zero steady low-slip eligible cases require explicit owner acceptance of that coverage or an additional fixed eligible fixture before stage-3 freezing. Include a planted radius-measurement fault rejected by the course check, while unchanged simulation traces prove that the fault and the measurement amendment do not alter mechanics.

**Stage-3 authority (adopted):**

Stage 3 may change only kPairedYawGain, kTailYawGain and kTailStiffSpeed. kHeaveGain, kPitchGain and kPairedInducedEfficiency remain fixed by the declared law and are not stage-3 calibration variables. An emitter accepting an override does not grant tuning authority. Refuse both changed and no-op --set requests for those extra constants before opening the output header. Preserve emitted values, ordering, digests and frozen-through stage for an unchanged authorized candidate, and prove its rerun unchanged.

At 120 u/s, a neutral fish is above sustained capacity: assay 3 must report a finite burst window and fatigue state, not claim an indefinitely steady turn.

For assay 4, use a **metered test fuel source** to hold the 25 E reference load while accumulating every debit over 120 s. Expected burn is `180±2.4 E`. Log the injected fuel as a test subsidy. An ordinary fish with 25 E cannot complete a 120-second no-food trial at 1.5 E/s. Use a straight toroidal path; a circle adds steering expenditure and cannot establish the straight-cruise anchor.

Do not tune population, mouth radius, construction coefficient, patch fractions, or predators through these assays. Assays 5–6 belong to M2b2.

Extend `tools/ocean_eye_bench` to compare initialization-built legacy/M2 variants; do not live-toggle an init-only flag. Use matched seed, networks, body inputs, food, topology, flow, eye mode, and capture settings. Restore before every run.

The acceptance gate is:

```text
median paired wasm M2b1 / matched legacy baseline ≤ 1.25
population = 2,000 throughout timed intervals
```

Use 100 warm-up steps, 200 measured steps, seven repetitions, one discarded warm-up repetition, rotating A/B/A order, and an A/A control within 3%. Exclude rendering and `oc_sync`; include ordinary world stepping, ownership, contacts, and lifecycle work. Record separate construction/export timings and run a birth/compaction stress workload.

Measure still-water, flow, and boundary-heavy cases, with matched plain/eye builds. The earlier 6.95 ms figure implies about 8.69 ms at 1.25× on that exploratory setup; it is not an absolute acceptance threshold for different hardware or builds. Profile regressions before reducing the model.

**6. Tests, files, and PR split**

Required tests cover:

- Compound mass/moments, analytic load updates, symmetry, and positive inertia at all gene rails. At fixed loading fraction, doubling size gives mass ×8, area ×4, inertia ×32.
- Tensor symmetry/PSD, retained coupling signs, loaded-COM shifts, zero-area fins, LDL residual `≤2e−5` relative, and passive-energy contraction.
- Correct frame signs, torque-free world velocity/angular momentum, quaternion normalization, and dissipative angular limiting.
- Exact motor/fatigue accounting, all-red behavior, shared λ, blocked motors, pressure/capacity limits, and paid regulation.
- Floor manifold stability, friction bounds, release, shallow tanks, seams, and loaded boundary support.
- Reserve conservation across feeding, sharing, fighting, overflow, and reproduction. Successful birth accounting must close within floating-point rounding; rejection changes only its declared ID/RNG/counter state.
- Dormant-trait sweeps with identical mechanics and costs, including developmental-cap leakage.
- Every lifecycle path, malformed configuration, ownership failure, checkpoint refusal/continuation, reset, copying, and long native/wasm per-step parity.

Proposed file plan:

| Files | Work |
|---|---|
| `src/ocean/body_plan.hpp` | Expose reusable canonical integration/support and caudal samples; preserve geometry law 1 and existing metrics ABI |
| New `body_material.hpp` | Positive material allocation, compound moments, muscle and construction quantities |
| New `hydro_coefficients.hpp` | Compact birth coefficients, tensor/load bases, stage expression and reference calibration |
| New `hydro_state.hpp`, `hydro_math.hpp` | State, frame contract, fixed LDLᵀ, quaternions, spatial transforms |
| New `hydro_step.hpp` | Two-substep mechanics, actuators, righting, contact, angular rail |
| New `ocean_energy.hpp` | Sole-ledger transactions, metabolism, fatigue, capacity and funding |
| `ocean_world.hpp` | Enabled branch, lifecycle/ownership, water cache, mouth queries, candidate births, legacy projections |
| `ocean_config.hpp` | Typed M2 configuration, defaults, init-only guards, compatibility checks |
| New `ocean_checkpoint.hpp` | Portable Ocean envelope and atomic load |
| `wasm/ocean_wasm.cpp` | Versioned pose/state exports, errors, checkpoint entry points, bounded diagnostics |
| Web controller/config/types | Initialization controls, validation, inspector, save/Turbo plumbing |
| Scene/shader slots/CPU mirror | Linear physical size, loaded inflation, quaternion pose, COM offset, shadows/picking/culling |
| New `tests/ocean_hydro_tests.hpp` and fixtures | Mechanics, energy, lifecycle, stage masking, checkpoint tests |
| New `tools/ocean_hydro_assay.cpp` | Native/wasm assays and machine-readable calibration manifest |
| Fingerprint/parity/bench/build files | Enabled chains/cases, benchmark variants, targets and release gates |

Publish compact dynamic pose/load rows. Keep appearance stride 63 and `snapshot.body` intact; use separate names for body-plan diagnostics and hydro data. CPU rendering checks must exercise the real live-page path, including memory growth and Turbo handoff.

Use **three stacked PRs**:

1. **Birth physics foundation:** material law, compact coefficients, support/loading bases, tensor/math primitives, fixtures, and offline reference. Public hydrodynamics requests remain refused.
2. **Mechanics and energetics:** integrator, actuators, fatigue, buoyancy, reserves, contact, and assay harnesses 1–4. Exercise through internal harnesses; keep public activation refused until lifecycle and presentation are complete.
3. **Complete enabled world:** funded reproduction, mouth envelope, rendering/exports, checkpoints, enabled fingerprints, full parity, and performance gate. This PR exposes the public opt-in.

Release evidence must include full historical Ocean parity and expanded preview twins, unchanged OFF baselines, enabled every-step native/wasm parity, checkpoint continuation, native checks, type/shader/material/mock/browser/Turbo checks, rebuilt Ocean wasm freshness, unchanged `src/core`, and unchanged Classic wasm hashes. Never rebaseline an OFF failure.

**7. Open owner questions**

The recommendations below are used in this brief; none reopens the six approved decisions.

1. **Basal partition:** v2’s general `.80 rLean^κ` statement and its explicit linear muscle partition differ away from neutral. **Recommend `.60 rLean^κ + .20 rMuscle(.4+1.2f)`**, following the corrected partition.
2. **Newborns with insufficient storage:** some small, low-fat bodies cannot hold `25 rLean^κ`. **Recommend clipping the funded newborn amount to physical capacity**, logging the shortfall, with no overflow payment or Kleiber-scaled compartment.
3. **Resident memory ceiling:** full tensor/root-update bases exceed the old estimate. **Recommend the 1,404 B/fish ceiling above**, with measured reductions pursued before calibration freeze and cold diagnostics generated on demand.
**USER DECISIONS (2026-11-10 ~19:30Z), all three recommendations accepted:**
1. Basal partition = `.60·rLean^κ + .20·rMuscle(.4+1.2f)`.
2. Newborns with insufficient storage: clip the funded newborn amount to physical capacity, log the shortfall; no overflow payment, no Kleiber-scaled compartment.
3. Resident memory ceiling = 1,404 B/fish (hard ceiling), measured reductions before calibration freeze, cold diagnostics on demand.

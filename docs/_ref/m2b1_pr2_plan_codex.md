<!-- Codex gpt-6.1-sol max, read-only, codex_council/codex_queue.mjs m2b2plan 2026-11-11T15:05:39.520Z: m2b2plan: M2b1 PR 2 implementation plan -->

Plan PR 2 on the **fixed PR 1**, preserving public refusal and leaving production world stepping untouched. PR 2 should deliver reusable mechanics and energy kernels, internal harnesses, assays 1–4, and deterministic fixtures. Lifecycle integration and the final whole-world performance gate remain PR 3.

I only read files. I did not modify files, execute project code, build, or test.

**1. Authority, scope, and prerequisites**

Use these sources, in this order:

| Authority | Relevant lines |
|---|---|
| [M2b1 brief](<C:/Users/harit/Downloads/fish runs/ocean_handoff/design/m2b1_brief_codex.md:721>) | 721–725: three-PR split; PR 2 remains internal |
| [Brief: laws](<C:/Users/harit/Downloads/fish runs/ocean_handoff/design/m2b1_brief_codex.md:132>) | 132–592: expression, mechanics, energy, buoyancy, contact |
| [Brief: assays](<C:/Users/harit/Downloads/fish runs/ocean_handoff/design/m2b1_brief_codex.md:654>) | 654–684: exact assay and timing requirements |
| [Accepted decisions](<C:/Users/harit/Downloads/fish runs/ocean_handoff/design/m2b1_brief_codex.md:736>) | 736–739: basal partition, clipped newborn fuel, 1,404 B ceiling |
| [Design v2](<C:/Users/harit/Downloads/fish runs/ocean_handoff/design/m2_design_v2.md:85>) | Corrected laws; brief supersedes conflicting provisional text |
| [PR 1 review](<C:/Users/harit/Downloads/fish runs/codex_reviews/2026-11-11_review_pr83_m2b1_850d381_codex.md:7>) | Required foundation fixes |
| [Performance reconciliation](<C:/Users/harit/Downloads/fish runs/ocean_handoff/design/opt_reconciled_codex.md:185>) | Budget accounting and measurement limits |
| [Ocean performance diagnosis](<C:/Users/harit/Downloads/fish runs/ocean_handoff/design/ocean_perf1_diagnosis_codex.md:5>) | Do not introduce fused visits or dynamic tanh batches |

All repository line numbers below refer to snapshot `850d381`; locate edits by the quoted code after the PR 1 fixes move lines.

The implementer must start in the coordinator-provided scratch worktree containing fixed PR 1. Do not create another worktree, fetch, checkout, commit, merge, rebase, deploy, or rebaseline. `.git` stays read-only. All writable artifacts, temporary directories, caches, and logs belong under `build_m2b1_pr2/` in that worktree.

Before editing, verify the fixed foundation has all five review changes:

1. Legal declared-field traversal for coefficients/support; no cross-member `float*` indexing.
2. Finite-result refusal in LDL, scaled solves, and load evaluation.
3. An independent double reference for loaded compound properties, body added mass, and rotational resistance.
4. An SPD-checked, finite-result 3×3 inverse.
5. Block-specific tensor units.

A missing fix is a prerequisite failure. Do not repair it opportunistically inside PR 2.

Keep unchanged:

- `src/core/**`, Classic sources and modules, Red Queen tooling.
- Production `OceanWorld` stepping and lifecycle.
- Public Ocean configuration and activation.
- Appearance stride, body-plan metrics ABI, rendering, exports, checkpoints, fingerprints.
- `tests/ocean_baseline/**` and the M2a body fixture.

The existing public refusal at [ocean_config.hpp:461](C:/Users/harit/codex_council/snaps/pr83/src/ocean/ocean_config.hpp:461) must remain:

```cpp
461: // M2's body physics does not exist yet (M2b): a request for it is
462: // refused, never silently run as the legacy model. false / 0 is a no-op.
463: if (kv.first == kHydrodynamicsKey &&
464:     !((v.type == T::Bool && !v.b) || (v.type == T::Number && v.num == 0.0))) {
465:     err = std::string(kHydrodynamicsKey) + " is not available in this engine: body-plan physics is M2b "
466:           "(bodyPlanPreviewEnabled is M2a's diagnostic preview, which changes no behaviour)";
467:     return false;
468: }
```

Its comment may be updated to explain the PR split; its behavior must not change.

**2. PR 1 interfaces to verify and reuse**

Do not depend on PR 1’s removed flattening helpers.

| Interface | Snapshot location | Required contract |
|---|---|---|
| `V3`, `S3`, `S6`, `V6`, `Q4`; packings | [hydro_math.hpp:42](C:/Users/harit/codex_council/snaps/pr83/src/ocean/hydro_math.hpp:42) | Body translation first, rotation second |
| Vector and symmetric-matrix operations | `hydro_math.hpp:49–168` | Fixed binary32 operation order |
| `invS3(A,out)` | `hydro_math.hpp:71` | SPD and finite result; atomic refusal |
| `factorLDL`, `LDL6`, `solveLDL` | `hydro_math.hpp:176–214` | Fixed unpivoted order; finite reciprocal/factor checks |
| `solveScaled(A,b,Lc,x,...)` | `hydro_math.hpp:220` | Positive finite scale; finite input/output; `x` untouched on refusal |
| Quaternion operations and `integrate` | `hydro_math.hpp:236–294` | Specified normalized Euler quaternion update |
| `worldFromLegacy`, `uprightPose` | `hydro_math.hpp:297–304` | World `(legacy x,-depth,legacy y)` |
| `railProject`, `railScale` | `hydro_math.hpp:314–332` | Coupled dissipative rail; SPD refusal |
| `HydroState`, `poseOf`, `restState` | [hydro_state.hpp:36](C:/Users/harit/codex_council/snaps/pr83/src/ocean/hydro_state.hpp:36) | Existing 76-byte state; no second fuel ledger |
| `forEachStateWord` | `hydro_state.hpp:72` | Eighteen float words, then status; no padding |
| `Params`, `paramsError` | [hydro_coefficients.hpp:134](C:/Users/harit/codex_council/snaps/pr83/src/ocean/hydro_coefficients.hpp:134) | Birth-only basal/Kleiber parameters |
| `Coefficients`, field metadata and safe traversal | `hydro_coefficients.hpp:151–231` | Preserve field/digest order |
| `Support`, `supportVertex`, `support` | `hydro_coefficients.hpp:240–278` | All 114 canonical hull vertices; stable IDs |
| `References`, `references()` | `hydro_coefficients.hpp:282–295,785` | Reference geometry/material quantities and pricing |
| `Loaded`, `evalLoad` | `hydro_coefficients.hpp:591–722` | Capped admissible load, complete finite result, cleared refusal |
| `passiveDamping` | `hydro_coefficients.hpp:729` | Body damping plus speed-weighted fin tensor; no induced/brake term |
| `compile`, `digest` | `hydro_coefficients.hpp:792,838` | Birth compilation and explicit-field digests |
| `bodymat` material/covariance conventions | `body_material.hpp`; PR 1 reference | Uniform lipid in the loaded hull; fixed material partition |
| Fixture bodies | [ocean_hydro_bodies.hpp:15](C:/Users/harit/codex_council/snaps/pr83/tools/ocean_hydro_bodies.hpp:15) | Existing 137-body set |

`solveLDL` may remain an unchecked inner primitive after fixed PR 1. Any new direct caller must validate its scaled RHS and returned result before publishing.

The existing record arithmetic is:

```text
916 coefficients + 240 support + 76 state + 20 physical genes + 8 owner
= 1,260 B/fish
```

This is recorded at [ocean_hydro_fixture.json:2](C:/Users/harit/codex_council/snaps/pr83/tests/fixtures/ocean_hydro_fixture.json:2). PR 2 should add **no resident per-fish fields**.

**3. Files and responsibilities**

| File | Work |
|---|---|
| New `src/ocean/hydro_calibration.hpp` | Versioned internal constants and measured reference-power bits |
| `src/ocean/hydro_coefficients.hpp` | Mechanics/energetics versions; measured reference override; constant digest |
| New `src/ocean/ocean_energy.hpp` | Capacity, sole-ledger transactions, parcels, motor/fatigue accounting |
| New `src/ocean/hydro_contact.hpp` | Hull manifold, effective-mass responses, friction, geometric containment |
| New `src/ocean/hydro_step.hpp` | Outer action adapter; actuator requests; two mechanical substeps |
| New `tools/ocean_hydro_harness.hpp` | Internal clones, scripting, telemetry, deterministic measurement windows |
| New `tools/ocean_hydro_assay.cpp` | Assays 1–4, calibration emitter, deterministic fixture mode |
| New `tools/ocean_hydro_trajectory_reference.hpp` | Native-only independent trajectory/reference comparisons |
| `tools/ocean_hydro_reference.cpp` | Invoke new trajectory checks while preserving fixed PR 1 checks |
| New `tests/ocean_hydro_step_tests.hpp` | Mechanics, energy, contact, refusal and long-run checks |
| `tests/ocean_tests.cpp` | Register new suite and `--only hydro_step` |
| `tools/ocean_hydro_fixture.cpp` | Emit mechanics/energetics/calibration metadata |
| `tests/fixtures/ocean_hydro_fixture.json` | Generated replacement for the newly versioned reference law |
| New `tests/fixtures/ocean_hydro_step_fixture.json` | Generated every-substep chained internal fixture |
| New `tests/fixtures/ocean_hydro_calibration.json` | Frozen constants, reference load and assay results |
| `wasm/ocean_parity.sh` | Build/run internal assay fixture alongside existing gates |
| New `tools/ocean_hydro_bench.hpp`; `tools/ocean_eye_bench.cpp` | Component timing and memory mode; preserve existing benchmark behavior |
| New `docs/m2b1_pr2.md` | Frozen-law decisions, evidence, limitations and PR 3 handoff |

Do not include these new production headers from `ocean_world.hpp` or `ocean_wasm.cpp` in PR 2.

**4. Constants and reference freeze**

Create `hydro_calibration.hpp` with this bootstrap content:

```cpp
#pragma once
#include <cstdint>

namespace hydro::calibration {

inline constexpr int kFrozenThrough = 0;

inline constexpr float kGravity = 400.0f;
inline constexpr float kPressureDepthFraction = 0.5f;
inline constexpr float kMetacentricFraction = 0.12f;
inline constexpr float kDepthGain = 0.08f;
inline constexpr float kVerticalGain = 0.02f;
inline constexpr float kRegulatorTau = 5.0f;
inline constexpr float kGasRateFraction = 0.02f;
inline constexpr float kPumpEfficiency = 0.25f;

inline constexpr float kStaticFriction = 0.8f;
inline constexpr float kDynamicFriction = 0.6f;
inline constexpr float kContactSlopPerSize = 0.005f;
inline constexpr float kPenetrationLimitPerSize = 0.01f;

inline constexpr float kControllerTau = 0.25f;
inline constexpr float kHeaveGain = 1.0f;
inline constexpr float kPitchGain = 1.0f;
inline constexpr float kPairedYawGain = 1.0f;
inline constexpr float kTailYawGain = 0.25f;
inline constexpr float kTailStiffSpeed = 108.0f;

// A declared reduced-law starting constant, distinct from rowing efficiency.
// It is included in the calibration digest and frozen with assay 3.
inline constexpr float kPairedInducedEfficiency = 0.75f;
inline constexpr float kBrakeCd = 1.10f;

inline constexpr std::uint32_t kMeasuredCruisePowerBits = 0;
inline constexpr std::uint32_t kMeasuredSustainedPowerBits = 0;

}  // namespace hydro::calibration
```

The paired induced efficiency is a new explicit modeling choice: PR 1 deliberately deferred it at [PR83_BODY.md:235](C:/Users/harit/codex_council/snaps/pr83/PR83_BODY.md:235). It is **not** `.35` rowing efficiency, tail efficiency, or an established measurement. Document this distinction.

In `hydro_coefficients.hpp`, add:

```cpp
#include <bit>
#include "hydro_calibration.hpp"
```

Replace the current version declarations:

```cpp
101: inline constexpr int kReferenceLaw = 1;
104: // the mechanics / energetics laws arrive with the integrator (PR 2); 0 = none yet
105: inline constexpr int kMechanicsLaw = 0;
106: inline constexpr int kEnergeticsLaw = 0;
```

with:

```cpp
inline constexpr int kReferenceLaw =
    calibration::kFrozenThrough >= 2 ? 2 : 1;
inline constexpr int kMechanicsLaw = 1;
inline constexpr int kEnergeticsLaw = 1;
```

Keep coefficient/support/state ABIs unchanged unless fixed PR 1 already changed them.

At `detail::buildReferences`, current code is:

```cpp
777: r.cruisePower = r.pmotor(kUref);
778: r.sustainedPower = r.pmotor(kUsusRef);
779: r.workConversion = kCruiseMotorShare / r.cruisePower;
```

Replace it with:

```cpp
if constexpr (calibration::kFrozenThrough >= 2) {
    r.cruisePower =
        std::bit_cast<float>(calibration::kMeasuredCruisePowerBits);
    r.sustainedPower =
        std::bit_cast<float>(calibration::kMeasuredSustainedPowerBits);
} else {
    r.cruisePower = r.pmotor(kUref);
    r.sustainedPower = r.pmotor(kUsusRef);
}
r.workConversion = kCruiseMotorShare / r.cruisePower;
```

Extend reference validation to require finite, positive `cruisePower`, `sustainedPower`, and `workConversion`. Keep `TcapNeutral=2Dneutral(150)` and the existing per-fish `Urow` formula. Do not lower the force ceiling by re-anchoring it at 82.

Add an explicit constant digest, in this exact order:

```text
geometry law, material law, expression stage, reference law,
mechanics law, energetics law, frozen-through stage,
gravity, pressure-depth fraction, metacentric fraction,
depth gain, vertical gain, regulator tau, gas-rate fraction, pump efficiency,
static friction, dynamic friction, contact slop, penetration limit,
controller tau, heave gain, pitch gain, paired-yaw gain,
tail-yaw gain, tail-stiff speed, paired induced efficiency, brake Cd,
Uref, Usus_ref, Uact, paired rowing efficiency, tauBurst, gamma,
maintenance fin/wall/lipid coefficients,
measured cruise-power bits, measured sustained-power bits
```

Use `Digest::add` for integers/bit fields and `addf` for float fields. Never hash the calibration struct’s bytes.

The calibration emitter must generate hexadecimal binary32 literals or `uint32_t` bit literals, not decimal values rounded by hand. Final committed `kFrozenThrough` must be `4`. Bootstrap headers/manifests must not be presented as frozen evidence.

**5. Sole-ledger energy and carried momentum**

Create `ocean_energy.hpp`. Keep all simulation quantities binary32.

Use these exact public-internal shapes:

```cpp
namespace hydro {

inline constexpr float kOuterDt = 0.016f;
inline constexpr float kSubDt = 0.008f;

struct Parcel {
    float energy = 0.0f;
    V3 pointWorld{0.0f, 0.0f, 0.0f};
    V3 velocityWorld{0.0f, 0.0f, 0.0f};
    V3 spinPerMassWorld{0.0f, 0.0f, 0.0f};
};

struct ReserveReceipt {
    float accepted = 0.0f;
    float spent = 0.0f;
    float waste = 0.0f;
    float unpaid = 0.0f;
    Parcel removed{};
};

struct MotorReceipt {
    float lambda = 0.0f;
    float requestPower = 0.0f;
    float actualPower = 0.0f;
    float aerobicPower = 0.0f;
    float burstPower = 0.0f;
    float fuel = 0.0f;
    float nextFatigue = 0.0f;
};

inline float fuelMass(float energy) {
    return energy > 0.0f ? energy / 500.0f : 0.0f;
}

inline float pressure(float depth, float tankDepth) {
    const float hp = calibration::kPressureDepthFraction * tankDepth;
    return 1.0f + depth / hp;
}

inline float maintenancePower(const Coefficients& c, float energy) {
    return c.maintenancePower
        + kMaintLipid * (fuelMass(energy) / references().fuelMass);
}

}  // namespace hydro
```

`loadAt` must:

1. Validate finite positive tank depth.
2. Validate finite state and ledger; require `0≤E≤energyCapacity`, valid compiled status, nonnegative fatigue, and legal gas content.
3. Use depth `-com[1]`; temporarily outside-boundary positions may use depth clamped to `[0,D]` **only for pressure evaluation**, pending contact correction.
4. Compute `Pmax=1+D/Hp`, `Gmax=Pmax*gasCapacity`.
5. Refuse `G<0`, `G>Gmax`, or nonzero `G` for zero bladder capacity.
6. Compute `Vgas=min(gasCapacity,G/P)`.
7. Call fixed PR 1 `evalLoad(c,Vgas,fuelMass(E),L)`.
8. Never silently repair a failed load or fall back to legacy motion.

Implement the motor kernel exactly:

```cpp
inline bool limitMotor(
    const Coefficients& c,
    float availableEnergy,
    float fatigue,
    float requestPower,
    float workConversion,
    MotorReceipt& out)
{
    MotorReceipt r{};
    if (!(availableEnergy >= 0.0f) ||
        !(fatigue >= 0.0f && fatigue <= c.fatigueCapacity) ||
        !(requestPower >= 0.0f) ||
        !(workConversion > 0.0f) ||
        !std::isfinite(availableEnergy) ||
        !std::isfinite(fatigue) ||
        !std::isfinite(requestPower) ||
        !std::isfinite(workConversion)) {
        return false;
    }

    const float excess = c.peakPower - c.sustainedPower;
    if (!(c.sustainedPower >= 0.0f) ||
        !(excess >= 0.0f) ||
        !std::isfinite(excess)) {
        return false;
    }

    const float availablePower =
        c.sustainedPower
        + std::min(excess,
            std::max(0.0f,
                (c.fatigueCapacity - fatigue) / kSubDt));

    const float qFuel =
        availableEnergy / (workConversion * kSubDt);
    const float fuelPower =
        qFuel <= c.sustainedPower
        ? qFuel
        : (qFuel + 2.0f * c.sustainedPower) / 3.0f;

    float lambda = availableEnergy > 0.0f ? 1.0f : 0.0f;
    if (requestPower > 0.0f) {
        lambda = std::min(
            lambda,
            std::min(availablePower / requestPower,
                     fuelPower / requestPower));
    }

    r.lambda = lambda;
    r.requestPower = requestPower;
    r.actualPower = lambda * requestPower;
    r.aerobicPower =
        std::min(r.actualPower, c.sustainedPower);
    r.burstPower =
        std::max(0.0f, r.actualPower - c.sustainedPower);

    const float requestedFuel =
        (workConversion * kSubDt)
        * (r.aerobicPower + 3.0f * r.burstPower);

    // The cap handles only the rounding boundary of the analytic fuel limit.
    r.fuel = std::min(availableEnergy, requestedFuel);

    const float recovery =
        std::min(
            fatigue / kSubDt,
            kGamma * std::max(
                0.0f, c.sustainedPower - r.actualPower));

    r.nextFatigue = std::clamp(
        fatigue + kSubDt * (r.burstPower - recovery),
        0.0f, c.fatigueCapacity);

    if (!std::isfinite(r.actualPower) ||
        !std::isfinite(r.fuel) ||
        !std::isfinite(r.nextFatigue)) {
        return false;
    }
    out = r;
    return true;
}
```

Add an assertion/test that fuel capping differs from `requestedFuel` only by floating-point rounding. A material discrepancy is a bug in the limiter, not permission to provide unpaid force.

Implement `changeReserve` with the following signature:

```cpp
bool changeReserve(
    const Coefficients& c,
    float tankDepth,
    HydroState& state,
    float& foodReserves,
    float requestedDelta,
    const Parcel* incoming,
    ReserveReceipt& receipt);
```

Its operation order is fixed:

1. Work on local copies of state and ledger; validate incoming state/load.
2. `target=clamp(E+requestedDelta,0,Ecap)`.
3. Record actual accepted/spent energy, positive overflow as waste, and unfulfilled debit as unpaid.
4. Let `dm=fuelMass(target)-fuelMass(E)` and `Mnew=c.leanMass+fuelMass(target)`.
5. For a credit, require an incoming parcel and use its point, velocity, and spin per mass.
6. For a debit, construct an outgoing co-moving lipid parcel:
   - `r=R*(L.hullCentroid-L.com)`.
   - `pointWorld=COM+r`.
   - Recover material `omegaBody=Ibody^-1 RᵀLWorld`.
   - `velocityWorld=Vground+omegaWorld×r`.
   - Form the lipid’s central per-mass second moment with `stretchS3(c.hullCovariance,L.k)`.
   - `spinPerMassWorld=R*inertiaOf(Cfuel)*omegaBody`.
7. Apply the parcel with:

```cpp
const V3 r = sub(parcel.pointWorld, oldCom);
const float fraction = dm / newMass;
const V3 newCom = add(oldCom, mul(r, fraction));
const V3 newVelocity =
    add(oldVelocity,
        mul(sub(parcel.velocityWorld, oldVelocity), fraction));
const V3 spinAndOrbital =
    add(parcel.spinPerMassWorld,
        cross(r, sub(parcel.velocityWorld, newVelocity)));
const V3 newAngularMomentum =
    add(oldAngularMomentum, mul(spinAndOrbital, dm));
```

8. Store those values in the candidate state; store `target` in the candidate ledger.
9. Re-evaluate the new loaded properties and validate every result.
10. Commit atomically. On failure, leave ledger, physical state, and receipt unchanged.

This preserves pure co-moving translational velocity exactly: the velocity difference in the update is zero. It also accounts for the spin and off-center momentum of removed fuel.

This declares redistribution as an internal shape/load update preserving the carried material momentum; it does not preserve an invented fluid momentum history. Geometry remains expressed relative to the current loaded material COM.

Add `transferReserve` using local copies of both fish. Withdraw at most available donor energy, then deposit the returned parcel into the receiver. Keep the parcel’s point/velocity/spin so global carried momentum closes. Receiver overflow becomes waste. Commit both fish only when both transactions succeed.

Add `shareReserves` by transferring half the ledger difference from the richer fish. Add a bounded fight-transfer helper taking the already selected winner/loser and requested transfer. **No energy helper draws RNG.** PR 3 will retain the existing fight draws and route their result through this helper.

Funding, newborn initialization, feeding queries, and reseeding integration are not implemented in PR 2. The transaction primitive must nevertheless cover their eventual needs.

**6. Outer action adapter and actuators**

Create `hydro_step.hpp`. Preserve action indices by including the existing sensor/action declaration; do not add actions.

Use:

```cpp
struct Requests {
    float speed = 0.0f;
    float yaw = 0.0f;
    float dive = 0.0f;
    float forwardBias = 0.0f;
};

struct StepConfig {
    float width = 1920.0f;
    float height = 1080.0f;
    float depth = 240.0f;
    float minRequestedSpeed = 0.0f;
    float maxRequestedSpeed = 150.0f;
    float maxAngularSpeed = 12.0f;
    float geneCost = 0.0f;
    float wallBand = 0.0f;
    bool toroidal = true;
};

struct HeldOuter {
    V3 waterWorld{0.0f, 0.0f, 0.0f};
    Requests requests{};
};

struct Channel {
    V3 forceBody{};
    V3 leverBody{};
    float efficiency = 1.0f;
};

struct ActuatorPlan {
    Channel channel[10]{};
    int count = 0;
    float pairedControl[4]{};
    float nextTailDrive = 0.0f;
    float nextTailYaw = 0.0f;
    float gasRate = 0.0f;
    float pumpPower = 0.0f;
    float requestPower = 0.0f;
    float brakeFraction = 0.0f;
};
```

Validate `StepConfig` at harness initialization: finite dimensions, positive depth, `0≤min≤max≤150`, `0<maxAngularSpeed≤12`, nonnegative finite gene cost/wall band, and supported versions. There is no public config adapter in this PR.

The existing push random branch is [ocean_world.hpp:2208](C:/Users/harit/codex_council/snaps/pr83/src/ocean/ocean_world.hpp:2208):

```cpp
2208: if (std::abs(moveRnd) > 0.5f) {
2209:     c.vel.x += rng.range(-1.0f, 1.0f) * std::abs(moveRnd) * dt;
2210:     c.vel.y += rng.range(-1.0f, 1.0f) * std::abs(moveRnd) * dt;
2211:     rndZ = rng.range(-1.0f, 1.0f) * std::abs(moveRnd) * dt;
2212: }
```

The internal adapter must preserve that condition and exactly three draws, once per outer step:

```cpp
inline V3 holdRandomRequest(
    const float* actions, float responsiveness,
    bool triangular, RandomGen& random)
{
    if (triangular) return {0.0f, 0.0f, 0.0f};
    const float moveRnd =
        actions[MOVE_RANDOM] * responsiveness;
    if (!(std::abs(moveRnd) > 0.5f))
        return {0.0f, 0.0f, 0.0f};

    const float magnitude = std::abs(moveRnd);
    const float rx = random.range(-1.0f, 1.0f) * magnitude;
    const float ry = random.range(-1.0f, 1.0f) * magnitude;
    const float rz = random.range(-1.0f, 1.0f) * magnitude;
    return {rx, -rz, ry};
}
```

These are held normalized force-request biases; the integrator supplies the time factor. Do not multiply by `dt` here and again during integration.

Implement `adaptOuterActions`:

- Triangular:
  - `drive=clamp(.5*(MOVE_FORWARD+1),0,1)`.
  - Set `requestedSpeed=min+drive*(max-min)`.
  - `yaw=responsiveness*STEER_X`.
  - No `(1-drive)` turn penalty.
- Push:
  - Integrate `requestedSpeed += 50*responsiveness*SPEED_ADJUST*.016`.
  - Clamp the requested speed.
  - Own frame: `STEER_X` contributes yaw; `STEER_Y` contributes forward bias.
  - World frame: unrotate world `(responsiveness*STEER_X,0,responsiveness*STEER_Y)`; body `+y` contributes yaw and body `-x` contributes forward bias.
  - Unrotate the held random vector once using the incoming outer pose; its body `+y`, `-z`, and `-x` components contribute yaw, dive, and forward bias.
  - `MOVE_FORWARD*responsiveness` supplies the other forward bias.
- `STEER_Z*responsiveness` contributes dive.
- Add bounded wall requests, then clamp yaw, dive, and total forward bias independently to `[-1,1]`.
- Hold the resulting requests for both substeps.

For internal wall avoidance, evaluate hull gaps at the outer incoming pose. For each nonwrapped face, use `clamp(1-gap/band,0,1)` times its inward normal. Sum in face order, transform to body coordinates, and project into forward/yaw/dive requests. Do not call the legacy heading-mutating `wallAvoid`.

Sample water once at the outer incoming COM. Convert existing flow to world `{flow.x,-flow.d,flow.y}`. Hold that world vector through both substeps.

`planActuators` must use the substep’s incoming loaded properties and incoming `z`:

```text
u = Rᵀ(Vground-Uwater)
omega = Ibody^-1 RᵀLWorld
U = sqrt(dot(u,u))
vlocal = u + omega × lever
```

For the forward controller:

```cpp
const float dragCoefficient =
    0.5f * rhoWater() * L.K[0] + at6(L.Dfin, 0, 0);
const float targetDrag =
    (dragCoefficient * request.speed) * request.speed;
const float effectiveForwardMass = at6(L.Meff, 0, 0);
const float biasScale =
    effectiveForwardMass * kUref / calibration::kControllerTau;
const float thrustRequest =
    targetDrag
    + effectiveForwardMass
        * (request.speed + u.x) / calibration::kControllerTau
    + biasScale * request.forwardBias;
```

Clamp positive thrust to `references().thrustCap`. Negative requests produce bounded passive braking, not reverse thrust or a speed assignment.

Allocate positive thrust by:

```text
caudal share = caudalArea / propArea
paired share j = .5*pairedArea[j] / propArea
```

Guard zero `propArea` before division.

Filter tail forward and yaw separately:

```cpp
inline float filterTail(float previous, float request, float tau) {
    const float a = kSubDt / tau;
    return (previous + a * request) / (1.0f + a);
}
```

The normalized forward tail request is positive clamped thrust divided by `TcapNeutral`; yaw request is held yaw.

Construct channels in this exact order:

1. Caudal forward.
2. Caudal yaw.
3. Pectoral R forward rowing.
4. Pectoral R normal control.
5. Pectoral L forward rowing.
6. Pectoral L normal control.
7. Pelvic R forward rowing.
8. Pelvic R normal control.
9. Pelvic L forward rowing.
10. Pelvic L normal control.

Skip zero-area channels before area-dependent arithmetic.

Forward forces point along body `-x`. Application points are:

```cpp
pLoaded = p0 + (L.k - 1.0f) * basis;
lever = pLoaded - L.com;
```

The caudal yaw force is:

```cpp
const float stiff = U / calibration::kTailStiffSpeed;
const float fy =
    -calibration::kTailYawGain
    * (0.5f * rhoWater() * c.caudalArea)
    * (U * U + c.rowSpeed * c.rowSpeed)
    * nextTailYaw / (1.0f + stiff * stiff);
```

Charge it independently at tail efficiency.

For paired fin `j`, compute:

```cpp
const V3 leverNormal = cross(lever, normal);
const float command = std::clamp(
    -calibration::kHeaveGain * request.dive * normal.z
    -calibration::kPairedYawGain
        * request.yaw * leverNormal.z / c.refLength
    -calibration::kPitchGain
        * request.dive * leverNormal.y / c.refLength,
    -1.0f, 1.0f);

const float magnitude =
    0.5f * rhoWater()
    * (norm2(localVelocity) + c.rowSpeed * c.rowSpeed)
    * c.pairedArea[j] * command;
```

Apply `magnitude*normal` and charge at `.35` efficiency. Paired forward rowing is a separate channel and separate charge.

For each channel, add:

```cpp
Prequest += sqrt(norm2(force))
    * (sqrt(norm2(localVelocity)) + c.rowSpeed)
    / efficiency;
```

Never sum opposing forces before pricing them.

**7. Gas regulation, damping, and the mechanical solve**

Gas regulation belongs in `planActuators`:

```text
Hp = pressureDepthFraction*D
P = 1+depth/Hp
Vneutral = M/rhoWater - Vhull - Vfuel - Vfin
Vtarget = clamp(
    Vneutral
    + depthGain*Vhull*(depth-bodyBuoy*D)/D
    + verticalGain*Vhull*(-Vground.y)/82,
    0, gasCapacity)
Gtarget = P*Vtarget
Gdot = clamp(
    (Gtarget-G)/regulatorTau,
    -gasRateFraction*Vhull,
    +gasRateFraction*Vhull)
```

Also bound `Gdot` by the change that keeps `G+h*Gdot` in `[0,Pmax*gasCapacity]`. A bladder-less fish has exactly zero gas request.

```cpp
const float p0 =
    rhoWater() * calibration::kGravity * hp;
const float pumpPower =
    p0 * std::abs(gasRate) / calibration::kPumpEfficiency;
```

Add pump power to the same `Prequest`. Apply the motor limiter once; multiply every active channel and gas-content change by the same `lambda`.

Build induced drag only after `lambda` is known:

```text
c_actual = lambda*pairedControl[j]
CDi = c_actual²/(pi*pairedInducedEfficiency*pairedAspect[j])
d = .5*rhoWater*pairedArea[j]*CDi*|vlocal|
```

For each paired fin, add three rank-one terms, in body-axis order:

```text
w_i = (e_i, lever × e_i)
Dinduced += d*w_i*w_iᵀ
```

This opposes local flow and is PSD. Skip zero area before dividing by AR. Do not add profile drag again; PR 1 already includes it in `L.K`.

For braking, use:

```text
beta = clamp(-thrustRequest/TcapNeutral,0,1)
speed = |u.x|
dbrake = beta*min(
    .5*rhoWater*BrakeCd*propArea*speed,
    TcapNeutral/speed)
```

Use exactly zero when `speed==0` or there is no propulsive area. Add it only to the surge diagonal. Braking is passive and receives no motor charge.

The mechanical kernel must use this code structure:

```cpp
inline bool solveMechanics(
    const Coefficients& c,
    const Loaded& L,
    const HydroState& state,
    const V6& incoming,
    const S6& damping,
    const V6& active,
    V6& outgoing)
{
    const Q4 q = poseOf(state);
    const V3 upBody = unrotate(q, kWorldUp);

    const float buoyantForce =
        calibration::kGravity
        * (rhoWater() * L.displaced - L.mass);
    const V3 gravityBody = mul(upBody, buoyantForce);

    const float offset =
        calibration::kMetacentricFraction * L.halfDepth;
    const float kMeta =
        (calibration::kGravity * rhoWater())
        * L.displaced * offset;
    const V3 righting =
        mul(cross(V3{0.0f, 0.0f, 1.0f}, upBody), kMeta);

    S6 A = L.Meff;
    for (int i = 0; i < 21; ++i)
        A.m[i] = A.m[i] + kSubDt * damping.m[i];

    const float implicitRighting =
        (kSubDt * kSubDt) * kMeta;
    A.m[s6u(3, 3)] =
        A.m[s6u(3, 3)] + implicitRighting;
    A.m[s6u(4, 4)] =
        A.m[s6u(4, 4)] + implicitRighting;

    V6 rhs = mulS6(L.Meff, incoming);
    const float gravity[3] = {
        gravityBody.x, gravityBody.y, gravityBody.z
    };
    const float torque[3] = {
        righting.x, righting.y, righting.z
    };

    for (int i = 0; i < 3; ++i) {
        rhs.v[i] =
            rhs.v[i] + kSubDt * (active.v[i] + gravity[i]);
        rhs.v[i + 3] =
            (rhs.v[i + 3] + kSubDt * active.v[i + 3])
            + kSubDt * torque[i];
    }

    V6 candidate{};
    if (!solveScaled(A, rhs, c.halfLength, candidate))
        return false;
    outgoing = candidate;
    return true;
}
```

`active` contains the summed scaled channel forces and `lever×force` torques. Harness-only external wrenches are added explicitly before this call and recorded as external work.

Total damping is:

```cpp
S6 D = passiveDamping(L, c.halfLength, incoming);
addTo(D, induced);
addTo(D, brake);
```

There is one mechanics factorization per substep. Contact response factorizations are separate constraint work.

Apply the solved changes through the current frame:

```cpp
const V3 du{
    outgoing.v[0] - incoming.v[0],
    outgoing.v[1] - incoming.v[1],
    outgoing.v[2] - incoming.v[2]
};
const V3 dw{
    outgoing.v[3] - incoming.v[3],
    outgoing.v[4] - incoming.v[4],
    outgoing.v[5] - incoming.v[5]
};

put(state.vGround,
    add(v3(state.vGround), rotate(q, du)));
put(state.LWorld,
    add(v3(state.LWorld),
        rotate(q, mulS3(L.inertia, dw))));
```

Apply the angular rail using `railProject(L.Meff,...)`, never by scaling `LWorld` alone. Limit the norm of total angular velocity to configured `maxAngularSpeed`, already bounded by 12. Apply the corresponding translational correction and material-inertia angular increment through the current frame. Do not refund fuel.

Then:

```cpp
COMnext = COM + kSubDt * VgroundNext;
qnext = integrate(q, omegaNext, kSubDt, &ok);
```

Recover angular velocity under the new pose from the unchanged world angular momentum. There is no extra gyroscopic kick, current advection, heading rotation, pitch clamp, depth spring, or soft-wall push.

**8. Contact implementation**

Create `hydro_contact.hpp`. Contact uses the inflated hull support representation, not exposed fins and not a COM sphere.

Use inward plane normals and this stable face order:

| Face | `normalWorld` | Plane gap at point `p` |
|---|---|---|
| legacy x minimum | `(1,0,0)` | `p.x` |
| legacy x maximum | `(-1,0,0)` | `W-p.x` |
| legacy y minimum | `(0,0,1)` | `p.z` |
| legacy y maximum | `(0,0,-1)` | `H-p.z` |
| surface | `(0,-1,0)` | `-p.y` |
| floor | `(0,1,0)` | `D+p.y` |

Skip the four horizontal faces in toroidal worlds.

For a vertex:

```text
rBody = supportVertex(support,id,k)-loadedCOM
pWorld = COM+R*rBody
vWorld = Vground+R*(omegaBody×rBody)
predictedGap = currentGap+h*dot(normalWorld,vWorld)
```

Use the cached bounds for a conservative no-contact rejection. Include translational travel and `h*boundRadius*|omega|`; a rotating hull must not be rejected merely because its current COM is far enough from a plane.

For each potentially contacting face:

1. Traverse all 114 vertices in ascending ID order.
2. Find the smallest predicted gap, ties to lower ID.
3. If that gap exceeds `contactSlopPerSize*S`, create no contact.
4. Candidate vertices are those within `contactSlopPerSize*S` of the smallest predicted gap.
5. Choose at most four:
   - First: smallest predicted gap, tie lower ID.
   - Each subsequent point: greatest minimum squared tangent-plane distance from already selected points, tie lower ID.
6. Process selected points in ascending vertex ID within the face.

This is a declared deterministic manifold rule. Record face and vertex IDs in trace mode.

Use one scaled factorization of the current `Meff` for all responses while load/pose remain unchanged. For each contact construct normal and two fixed world-axis tangent directions, transformed into body coordinates. For direction `d`:

```text
w = (d, rBody×d)
response = Meff^-1*w
Wab = waᵀ response_b
```

Validate every response and positive normal/tangent effective mass. Use fixed tangent axes:

- x faces: world z, world y.
- legacy y faces: world x, world y.
- depth faces: world x, world z.

Solve **four global sweeps**, each visiting faces and points in the declared order. Accumulated impulses begin at zero for every substep.

For normal velocity `vn` and current geometric gap:

```cpp
const float target =
    -std::max(gap, 0.0f) / kSubDt;
const float nextNormal =
    std::max(0.0f,
        accumulatedNormal + (target - vn) / normalResponse);
const float deltaNormal =
    nextNormal - accumulatedNormal;
```

Apply `deltaNormal*normalResponseVector`, then store `nextNormal`.

For friction, solve the coupled 2×2 tangent response for the impulse increment cancelling current ground-relative slip. Add that increment to the accumulated tangent impulse:

- Accept the resulting accumulated vector if its norm is at most `muStatic*Jn`.
- Otherwise set its magnitude to `muDynamic*Jn`, opposing current tangent slip.
- If slip is zero but projection is necessary, retain the required impulse’s direction.
- Apply only the difference from the previous accumulated tangent impulse.

Do not clamp each tangent independently; that produces a square friction bound.

Contact velocity is over ground. Water velocity must not be subtracted from it. Apply the same effective-mass response to linear and angular motion.

After integrating pose, resolve residual overlap geometrically: four fixed passes over faces, shifting COM by the minimum inward translation obtained from all hull vertices. Do not add bounce velocity. Refuse a final overlap exceeding `.01*S` or an infeasible shallow-tank configuration; do not hide it with a COM clamp.

After reserve/gas updates, refresh load, enforce the rail under that load, and run the same boundary resolution before publishing the substep. Contact and rail status bits are diagnostic; failure stops the harness.

**9. Exact outer-step order and failure boundary**

Implement:

```cpp
bool stepHydro(
    const Coefficients& coefficients,
    const Support& support,
    const StepConfig& config,
    const HeldOuter& held,
    float bodyBuoy,
    std::size_t genomeLength,
    HydroState& state,
    float& foodReserves,
    StepReceipt* receipt);
```

Operate on a local `HydroState` and local ledger. There are exactly two substeps.

For each substep:

1. Evaluate incoming load and material angular velocity.
2. Compute basal/maintenance/gene demand:

```text
basalDemand =
h*(basalPower+maintenancePower(E)+geneCost*float(genomeLength))
basalReserved = min(E,basalDemand)
Eavailable = E-basalReserved
```

3. Build actuator/pump requests from incoming load/state and held outer commands.
4. Run the one shared motor/fatigue limiter.
5. Build actual active wrench, induced drag, brake, and total passive damping.
6. Solve mechanics once; apply the coupled rail.
7. Resolve predictive contact using ground velocity and the same `Meff`.
8. Apply world velocity/angular-momentum increments.
9. Advance COM and normalized quaternion.
10. Update `G += h*lambda*GdotRequest`; store filtered tail requests and next fatigue.
11. Debit `basalReserved+motorFuel` through `changeReserve`. Record unpaid basal demand separately.
12. Refresh load, rail, and boundary support after the debit.
13. Validate every state/result field and append explicit words to any requested trace/fixture chain.

On success publish state, ledger, and receipt. On any failure publish no partial physical/ledger change; set only `state.status |= kStatusFailure`, return false, and report the failing stage. No retry, adaptive substep, pivot repair, force deletion, or legacy fallback.

Age and timers are advanced **once per outer step** by the harness:

```cpp
kernel::stepInternalState(fish, actions, kOuterDt);
fish.age += kOuterDt;
fish.reproTimer -= kOuterDt;
fish.interactTimer -= kOuterDt;
```

Do not call `kernel::stepMetabolism`: it also debits legacy fuel and applies legacy body multipliers at [kernel.hpp:96–109](C:/Users/harit/codex_council/snaps/pr83/src/core/kernel.hpp:96).

The future production splice belongs immediately after action capture and before legacy movement at [ocean_world.hpp:2170](C:/Users/harit/codex_council/snaps/pr83/src/ocean/ocean_world.hpp:2170). **Do not make that splice in PR 2.**

**10. Internal harness and assays 1–4**

`tools/ocean_hydro_harness.hpp` must own real separate coefficient/support/state/gene/owner columns, plus the existing fish/ledger data. No retained `Loaded`, channel plan, contact manifold, or cold diagnostic column.

A clone’s default settings:

```text
neutral appearance and physical genes; S=E=1
bodyBuoy=.5; tank depth 240
food, reproduction, predators, reseeding and heritability disabled
geneCost=0; still water unless specified
```

Use a metered test fuel source whenever an assay requires a fixed 25 E load. Route every injection through the reserve helper and log the subsidy. Assays 1–3 otherwise cannot hold their stated load while paying metabolism. Do not silently overwrite the ledger.

Use integer step counts:

```text
10 s = 625 outer steps
60 s = 3,750 outer steps
120 s = 7,500 outer steps
```

Do not drive scripted events from an accumulating float clock.

The assay executable must support:

```text
--assay 1|2|3|4
--check-all
--fixture
--trace PATH
--manifest PATH
--emit-calibration PATH
--build-id TEXT
--target native|wasm
```

`--fixture` emits only deterministic configuration, constants, versions, reference/coefficient digests, result fields, and every-substep chains. Hardware, elapsed timing, paths, timestamps, and build labels go in separate manifests/logs.

Each result must include configuration, all law/ABI versions, frozen-through stage, exact reference load, coefficient/support/reference/constant digests, actual constants, target/build identity, and raw measurement-window boundaries.

Implement these assays without weakening their acceptance:

| Assay | Exact required subcases and acceptance |
|---|---|
| **1: static tank** | One neutral fish; `D=240`, target depth 120, `E=25`, still water. Solve feasible neutral gas. Require relative buoyancy error `≤1e-5`, `|vd|<.01`, and drift `<.1 u` over 60 s. |
| **1: righting** | Separate 10° roll and pitch releases; within 1° in 10 s, no tumbling. Include a combined tilt as an additional check. |
| **1: depth steps** | From the established equilibrium, target 96 and 144; each must settle within 1 u in 60 s. |
| **1: floor** | Bladder-less clone rests 60 s; speed `<.01`, penetration `<.01*S`. At `.9*muStatic*N` external tangential load it holds; at `1.1*muStatic*N` it slips. |
| **1: release/sink** | Positive buoyancy and separately paid upward fin thrust release contact. Terminal sinking speed must match the declared force-balance prediction within 2%; approximately 12 is only a starting expectation. |
| **2: tow** | Hold assay-1 reference load/trim; tow at 40/82/108/120/150. Record full drag wrench, trim reactions, channel work and pump work. |
| **2: free drive** | Free straight runs reach numerical force-balance speed within 2%. Sustained neutral target initially 108, acceptance ±5%. Record actual peak speed against the starting 130–150 window; never impose that window with a speed clamp. |
| **2: fatigue** | Prescribed constant peak work fills recovered neutral fatigue in `2 s±.016 s`; zero work recovers in `4 s±.016 s`. Test fibre 0/.5/1, shared lambda, exhaustion, all-red zero capacity, no overshoot. |
| **3: step steer** | Start straight at pre-turn requests 40/82/120; inject unit yaw. Report actual turn speed, fitted radius, heading, body omega, sideslip, response and fatigue. Neutral 82 heading target remains `2.60±.15 rad/s`. Radius near 31 is non-gating in PR 2 (D4 below). |
| **3: body ordering** | At 40 require manoeuvrer radius < neutral < cruiser and cruiser/manoeuvrer ratio ≥3. |
| **3: geometry/rail** | Apply both separately eligible D5 geometry checks, D1 command-release upright recovery, and D2 driven-release relative-control recovery as amended below. Total omega never exceeds configured rail or 12. |
| **3: 120 u/s** | Report the finite burst window and fatigue state. Do not report an indefinitely steady 120 u/s turn. |
| **4: calorimetry** | Straight toroidal cruise at request 82; essentially level trajectory with disclosed body pitch and depth bias (corrected D-M2b1-7 below), `geneCost=0`, metered source holds 25 E for 120 s. Basal `.80`, maintenance `.10`, restrained-reference motor `.60` to binary32 roundoff and free-cruise motor `.60±.008` (D-M2b1-7), total `1.50±.02 E/s`; total debit `180±2.4 E`. |
| **4: extra work** | Turning and blocked-thrust subcases charge additional motor work. Explain every gas/trim expenditure. Verify 3× excess-power charging and free fatigue recovery. |


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

Define assay-3 bodies before calibration and keep them fixed:

```text
Neutral:
  S=1, elongation=1, all genes neutral.

Manoeuvrer:
  S=1, elongation=.5;
  morph[0]=.85, morph[1]=.60,
  morph[10]=.25, morph[19]=1, morph[23]=1;
  other genes neutral.

Cruiser:
  S=1, elongation=2;
  morph[0]=.25, morph[1]=.35,
  morph[10]=1, morph[11]=.75,
  morph[19]=.25, morph[23]=.25;
  other genes neutral.
```

These are explicit harness inputs, not an evolutionary coexistence claim. Morph indices are defined at [body_plan.hpp:320–332](C:/Users/harit/codex_council/snaps/pr83/src/ocean/body_plan.hpp:320).

For yaw measurements, report both `-omegaBody.z` and the actual horizontal heading rate. Fit path radius from recorded positions; do not substitute `U/omega` for the fitted value being checked.

Freeze in order:

1. Assay 1 freezes material normalization/reference trim, gravity, pressure law, righting, regulator, friction and contact tolerances.
2. Assay 2 freezes measured drag, loading/efficiency, Uact/Urow, measured motor powers at 82 and 108, tail response and capacity law.
3. Assay 3 freezes yaw gains and stiffening.
4. Assay 4 freezes maintenance allocation and confirms work conversion.

Use starting constants first. If calibration is needed, change only the constants assigned to that assay; emit a new candidate header, rebuild, and rerun that assay plus all preceding assays. Reject any candidate that invalidates an earlier freeze.

Do not tune geometry normalization, population, mouth radius, construction price, food distribution, predators, basal anchors, the 82 reference, or the 12 rad/s rail to obtain a passing result.

The final measured power bits and frozen calibration JSON cannot be specified truthfully in this read-only plan. They must be generated from the above measurements. If an assay cannot meet its target without changing the law, stop and report the discrepancy; do not stamp a frozen manifest.

**11. Offline reference**

Preserve every independently assembled check from fixed PR 1.

The snapshot’s reference explicitly deferred trajectories at [ocean_hydro_reference.cpp:22–30](C:/Users/harit/codex_council/snaps/pr83/tools/ocean_hydro_reference.cpp:22). Complete them in `ocean_hydro_trajectory_reference.hpp`, native only.

Use double precision and an independent dense solver for reference computation. Do not feed it production `Meff`, damping, active wrench, or RHS as the physical reference.

Cover:

- Loaded material mass/COM/inertia from independently transformed parts.
- Body and fin added-mass assembly and every coupling sign.
- Hull rotational damping from independently integrated covariance.
- Actuator force locations, power pricing, gas force and righting sign.
- One-step solve residuals and production/reference state increments.
- Tow, turn and relaxation trajectories.

Implement the offline sequential patch comparator as:

1. The same independently assembled material/body/added-mass law.
2. Body damping/righting solve.
3. Seven fin patches in caudal, dorsal, anal, pectoral R/L, pelvic R/L order.
4. Each patch uses its current `|w·z|`, with its sequential implicit rank-one update.
5. No runtime selection of this model.

Report tow drag/work, yaw/radius/response, sideslip, and relaxation differences. **No “under 3%” gate** exists in the approved brief.

Gate the independent law/solver checks; report model differences. Preserve the existing relative LDL tolerance `2e-5`.

At the end of reference `main`, before its PASS/FAIL print, add the equivalent of:

```cpp
const bool trajectoriesOK = hydroref2::run();
ok = ok && trajectoriesOK;
```

Include the new header only in this native tool.

**12. Unit suites and fixture registration**

Create these test functions in `tests/ocean_hydro_step_tests.hpp`:

```cpp
namespace ot {
void testHydroOuterAdapter();
void testHydroMechanicalStep();
void testHydroWorldMomentum();
void testHydroActuators();
void testHydroMotorAccounting();
void testHydroGas();
void testHydroReserveTransactions();
void testHydroContact();
void testHydroLoadedBoundaries();
void testHydroStepRefusals();
void testHydroLongRun();
void testHydroStepNumbers();

inline void testHydroStepSuite() {
    testHydroOuterAdapter();
    testHydroMechanicalStep();
    testHydroWorldMomentum();
    testHydroActuators();
    testHydroMotorAccounting();
    testHydroGas();
    testHydroReserveTransactions();
    testHydroContact();
    testHydroLoadedBoundaries();
    testHydroStepRefusals();
    testHydroLongRun();
    testHydroStepNumbers();
}
}
```

Required checks:

| Function | Tests |
|---|---|
| `OuterAdapter` | Triangular endpoints; no turn penalty; push target accumulation/clamps; both steering frames and headings; positive steer signs; exactly zero/three random draws at the existing threshold; held commands/water reused twice |
| `MechanicalStep` | Full coupled matrix and RHS against independent dense reference; relative residual ≤`2e-5`; no extra righting kick; passive-energy contraction with fixed load/pose and righting/external work excluded |
| `WorldMomentum` | Pure pose advance preserves world velocity/L; anisotropic inertia changes body omega appropriately; long quaternion normalization; coupled rail preserves effective linear momentum and decreases energy |
| `Actuators` | Force/torque signs, loaded-COM levers, independent tail filters, zero fins, no division by absent area/AR, separate opposing-channel prices, induced-drag PSD and actual-command² scaling |
| `MotorAccounting` | Exact formulas for lambda/Pa/Pb/fuel/fatigue; peak fill/recovery; fibre 0/.5/1; zero request/fuel; fuel exhaustion; blocked motion charged; recovery free |
| `Gas` | Pressure/compression, capacity rails, pump rate limits, no-bladder zero request, shared lambda, compression free and regulation paid |
| `ReserveTransactions` | Co-moving loss does not accelerate pure translation; ingestion mixes momentum; off-center/angular parcels; zero/full capacity; overflow; sharing; bounded fight transfer; atomic pair failure; energy/mass/P/H closure including waste |
| `Contact` | Floor rest; unilateral impulses; coupled tangent solve; static/dynamic disk bounds; release; zero restitution; contact uses ground velocity; four fixed sweeps; stable IDs |
| `LoadedBoundaries` | Surface/four glass faces/corners; shallow admissible/refused tanks; rotated hulls; toroidal seams; reserve/inflation transaction next to a wall; no COM-only containment |
| `Refusals` | NaN/Inf input, illegal gas/fuel/fatigue/quaternion/version, missing compiled status, deliberately failed solve; no partial physical/ledger publication or fallback |
| `LongRun` | At least 20,000 outer steps over still/flow/boundary scripts; all fields finite, unit quaternion, legal gas/fuel/fatigue, rail and hull bounds; native/wasm every-substep chain |
| `Numbers` | Explicit state/ledger/receipt chains for neutral, small/large, no fins, no bladder, fibre rails, dormant-trait twins and deterministic random bodies |

Test transaction conservation using a tolerance based on actual binary32 ledger changes: at most eight ulps of the largest energy term, with corresponding scaled momentum tolerances. Do not use a broad percentage tolerance that could hide energy creation.

Keep the PR 1 dormant-trait sweep and extend it through mechanics and all costs, including load/support/contact paths.

Current registration at [ocean_tests.cpp:4860](C:/Users/harit/codex_council/snaps/pr83/tests/ocean_tests.cpp:4860):

```cpp
4860: #include "ocean_appearance_tests.hpp"
4861: #include "ocean_body_plan_tests.hpp"
4862: #include "ocean_hydro_tests.hpp"
4863: #include "ocean_sense_tests.hpp"
```

Insert:

```cpp
#include "ocean_hydro_step_tests.hpp"
```

after `ocean_hydro_tests.hpp`.

Before the current `--only label_mask` rejection at lines 4896–4898, insert:

```cpp
if (std::strcmp(argv[2], "hydro_step") == 0) {
    ot::testHydroStepSuite();
    std::printf("OCEAN TESTS: %d passed, %d failed\n",
                ot::g_passed, ot::g_failed);
    return ot::g_failed ? 1 : 0;
}
```

Update the usage string to list `hydro_step`.

After `ot::testHydroNumbers();` in the full suite at line 5020, insert:

```cpp
ot::testHydroStepSuite();
```

Update the PR 1 version-support test at [ocean_hydro_tests.hpp:895](C:/Users/harit/codex_council/snaps/pr83/tests/ocean_hydro_tests.hpp:895) to use current constants rather than hardcoded reference law 1. Test rejection by changing each supported version independently.

The existing peak-speed assertion at lines 829–831 assumes the provisional analytic reference. Replace its hard 130–150 assertion with a finite force-balance result assertion and a printed starting-window comparison; assay 2 records the actual peak. Do not enforce a calibration expectation using a speed clamp.

**13. Fixture generation and parity script edits**

Keep the existing hydro fixture body set and three loads. Add mechanics law, energetics law, frozen-through stage, and constant digest to its header. Mark its document format as 2. Preserve explicit field ordering and safe traversal supplied by fixed PR 1.

Generate the replacement `ocean_hydro_fixture.json` only after:

1. Independent reference passes.
2. Native and wasm fixture output match byte for byte.
3. Assays have frozen through stage 4.
4. The changed versions/reference values are reviewed in the diff.

This is a versioned hydro fixture update, not permission to touch historical Ocean baselines.

The new step fixture must chain **every mechanical substep**, including ledger, state, gas, fatigue, status, transactions, impulses/rail diagnostics and relevant constants. Hash declared fields, never padding or pointers. Include case names and counts so an empty or shortened fixture fails.

In `wasm/ocean_parity.sh`, after current build lines 237–240:

```bash
bgbuild hydro_assay_native g++ $CXXFLAGS ${NATIVE_CXXFLAGS:-} \
    tools/ocean_hydro_assay.cpp -o "$OUT/oha_native"
bgbuild hydro_assay_wasm em++ $CXXFLAGS $EMFLAGS \
    tools/ocean_hydro_assay.cpp -o "$OUT/oha_wasm.js"
```

Use the existing bounded `bgbuild`; do not introduce another build scheduler.

After the current offline-reference gate at lines 1136–1139, add:

```bash
"$OUT/oha_native" --fixture \
    > "$OUT/hydro_step.native.json" \
    2> "$OUT/hydro_step.native.log"; rsn=$?
$NODE "$OUT/oha_wasm.js" --fixture \
    > "$OUT/hydro_step.wasm.json" \
    2> "$OUT/hydro_step.wasm.log"; rsw=$?

if [ "$rsn" = 0 ] && [ "$rsw" = 0 ] &&
   cmp -s "$OUT/hydro_step.native.json" \
          "$OUT/hydro_step.wasm.json" &&
   cmp -s "$OUT/hydro_step.native.json" \
          tests/fixtures/ocean_hydro_step_fixture.json; then
    echo "== mechanics fixture: native == wasm == committed"
else
    echo "== mechanics fixture FAILED (native $rsn, wasm $rsw)"
    FAILED=1
fi
```

The executable’s fixture mode must fail if calibration is not frozen through stage 4 or any assay/unit invariant fails.

**14. Timing and memory measurement**

Extend `tools/ocean_eye_bench.cpp` with an early `--mechanics-components` dispatch into `tools/ocean_hydro_bench.hpp`; preserve all existing options and behavior.

Current `main` begins at [ocean_eye_bench.cpp:104](C:/Users/harit/codex_council/snaps/pr83/tools/ocean_eye_bench.cpp:104). Add:

```cpp
if (argc > 1 &&
    std::strcmp(argv[1], "--mechanics-components") == 0) {
    return hydrobench::main(argc - 1, argv + 1);
}
```

The new mode must:

- Construct immutable legacy/control and internal-M2 variants at initialization.
- Restore state and RNG before every repetition.
- Retain 2,000 coefficient/support/state records, not 2,000 `Loaded` records.
- Time whole loops with no per-fish clocks.
- Cover still water, held flow, and boundary-heavy contact.
- Cover plain and eye builds.
- Use 100 warm-up steps, 200 measured steps, seven recorded repetitions and one discarded repetition.
- Rotate A/B/A order; require A/A within 3%.
- Print raw windows, per-repetition results, paired ratios and ns/fish-step.
- Separately time construction, on-demand diagnostics/export, reserve transactions, and birth/compaction-shaped stress.
- Include ownership validation and stable aligned-column compaction in the internal stress harness.

Use the existing benchmark’s snapshot/rotation/paired-ratio procedure at [ocean_eye_bench.cpp:172–245](C:/Users/harit/codex_council/snaps/pr83/tools/ocean_eye_bench.cpp:172).

Report:

```text
T = matched uninstrumented legacy whole-world time
H = measured complete internal mechanics/energy replacement cost
R = actually measured legacy work removed, if available
L = lifecycle/ownership/contact increment not already included
estimated net addition = H-R+L
```

Do not subtract the old profiled movement interval as if it were measured removable production cost. Do not use the PR 1 primitive benchmark as whole-step evidence: it retains 2,000 `Loaded` records and times separate passes at [ocean_hydro_fixture.cpp:83–115](C:/Users/harit/codex_council/snaps/pr83/tools/ocean_hydro_fixture.cpp:83).

The engineering allowance is approximately **+448 ns/fish-step** at the supplied baseline scale. Actual final acceptance is median paired wasm M2/legacy `≤1.25`, at population 2,000 throughout measured intervals.

**PR 2 cannot establish that final gate while production lifecycle is absent.** Report component evidence and remaining allowance. PR 3 must extend the initialization-built benchmark to complete worlds and include ordinary stepping, ownership, contacts, births, deaths, reseeding and compaction, excluding rendering and `oc_sync`.

For memory, print:

- `sizeof` every resident record and transient workspace.
- Each column’s size and capacity.
- Sum of actual capacity bytes divided by live population and by allocated slots.
- Allocator overhead separately.
- Peak construction stack/temporary memory.
- Peak on-demand diagnostic/export memory.
- Copy/reset peak, including simultaneous snapshot and working columns.

Require coefficient ≤1,024 B, support ≤256 B, state ≤96 B, and total resident physics/gene/owner storage ≤1,404 B/fish. With unchanged layouts, element payload remains 1,260 B; vector overcapacity can still violate the ceiling.

Do not retain cold diagnostics or duplicate owner IDs. Do not introduce fused sensing visits, dynamic tanh batches, across-fish physics reordering, or new neural optimizations.

**15. Gates, in order**

The following commands are instructions for the Linux implementer, not commands executed during this planning task.

First establish the scratch output root and concurrency limits:

```bash
mkdir -p build_m2b1_pr2/tmp build_m2b1_pr2/logs
export TMPDIR="$PWD/build_m2b1_pr2/tmp"
export EMCC_TEMP_DIR="$PWD/build_m2b1_pr2/tmp"
export EMCC_CORES=2
export CMAKE_BUILD_PARALLEL_LEVEL=2
export JOBS=2
export BUILD_JOBS=2
```

Use the installed offline emsdk matching CI, 6.0.4. Do not install tools or download packages. If the toolchain needs a writable cache, place it under the scratch output root and populate it from the installed cache using read-only source access.

Record base head, compiler/Emscripten/Node versions, flags, CPU and module hashes before editing. Use read-only Git commands only.

1. **Fixed-PR-1 prerequisite audit.** Verify all interfaces/fixes listed above and record the actual base SHA.

2. **Focused native checks.**

```bash
g++ -O3 -std=c++20 -ffp-contract=off \
  -DEVO_WORLD_OCEAN -I src tests/ocean_tests.cpp \
  -o build_m2b1_pr2/ocean_tests_native

build_m2b1_pr2/ocean_tests_native --only hydro
build_m2b1_pr2/ocean_tests_native --only hydro_step
```

Run a separate UBSan build of the focused suites. Do not treat UBSan as a determinism comparison.

3. **Native independent reference.**

```bash
g++ -O3 -std=c++20 -ffp-contract=off \
  -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_reference.cpp \
  -o build_m2b1_pr2/ocean_hydro_reference

build_m2b1_pr2/ocean_hydro_reference
```

4. **Calibration 1→2→3→4.** Build the native assay driver with the same flags. Run each assay, emit/rebuild its frozen header, and rerun all preceding assays before advancing. Preserve candidate/final manifests and raw windows. Final `--check-all` must pass with frozen stage 4.

5. **Native/wasm hydro fixtures.** Build both fixture drivers and the assay driver under native and Emscripten flags. Compare outputs before installing generated fixture files:

```bash
cmp build_m2b1_pr2/hydro_fixture.native.json \
    build_m2b1_pr2/hydro_fixture.wasm.json

cmp build_m2b1_pr2/hydro_step.native.json \
    build_m2b1_pr2/hydro_step.wasm.json
```

After generated files are installed, repeat comparison against the committed-path files.

6. **Full Ocean parity, suites, guards and expanded twins.**

```bash
env -u FAST -u ONLY -u NO_TESTS -u NO_EYE \
  APP_TWINS=all BODY_TWINS=all \
  JOBS=2 BUILD_JOBS=2 \
  OCEAN_PARITY_DIR="$PWD/build_m2b1_pr2/full_ocean_parity" \
  KEEP_OUT=1 \
  nice -n 19 bash wasm/ocean_parity.sh \
  > build_m2b1_pr2/logs/full_ocean_parity.log 2>&1
```

Preserve its raw exit status. This gate includes full native/wasm plain and eye unit suites, their identical printed output, historical baselines, config guards, both hydro fixtures, M2a fixture and the offline reference.

Do not call a narrowed run full evidence.

The known exception is precisely:

- `life_cap_fixture_s1` has `--pop 0`, `minPopulation=0` at [ocean_parity.sh:353](C:/Users/harit/codex_council/snaps/pr83/wasm/ocean_parity.sh:353).
- `body_args` unconditionally appends `--expect bodyFounders>0` at lines 1071–1075.
- The existing report records 122/123 body twins, with native/wasm exit 5 for this twin at [PR83_BODY.md:170–175](C:/Users/harit/codex_council/snaps/pr83/PR83_BODY.md:170).

Leave that harness behavior unchanged in PR 2. If the raw full run fails solely for this exception, verify and report all of:

```text
ordinary life_cap_fixture_s1 native/wasm/baseline comparison passes
body native and wasm both exit 5
body native output equals body wasm output
the only failed expectation is bodyFounders>0
the body section exists
stripping body fields/expectations and the header matches the ordinary case
all other cases, twins, fixtures, references, guards and unit suites pass
```

Do not swallow arbitrary exit 1 with `|| true`. Report “full matrix with the disclosed body-twin harness exception,” including the raw nonzero status. Any other failure blocks completion.

7. **Component timing and memory.** Run uninstrumented native and wasm measurements, sequentially, with no other builds. Reject A/A variation above 3%; retain raw results. Report the remaining whole-world performance obligation.

8. **Ocean module rebuild and freshness.**

```bash
nice -n 19 bash wasm/build_ocean.sh
git diff --exit-code -- web/evo_ocean.js web/evo_ocean.wasm
```

These should remain identical because the public module does not consume the new kernels. Unexpected changes require investigation.

9. **Classic rebuild and unchanged hashes.**

```bash
nice -n 19 bash wasm/build_wasm.sh
git diff --exit-code -- \
  web/evo_boids.js web/evo_boids.wasm \
  web/evo_boids_mt.js web/evo_boids_mt.wasm
```

`CMAKE_BUILD_PARALLEL_LEVEL=2` must remain exported.

10. **Native repository checks.**

```bash
cmake --preset native-serial
cmake --build --preset native-serial --parallel 2
ctest --test-dir build_serial --output-on-failure
```

Report which SFML-dependent tests were available.

11. **Module consumers.**

```bash
node tests/ocean_turbo_handoff.js
node tests/ocean_shader_slots_tests.cjs
node tests/ocean_materials_tests.cjs
node tests/ocean_mock_three_tests.mjs
```

Run the existing local TypeScript installation if present. Network is off: do not fetch dependencies. Browser gates are unnecessary for a PR with no rendering/public-path change; explicitly leave PR 3’s live rendering/checkpoint/export checks outstanding.

12. **Final frozen-scope audit.**

```bash
git diff --exit-code BASE_SHA -- src/core tests/ocean_baseline
git diff --exit-code BASE_SHA -- \
  wasm/evo_wasm.cpp wasm/build_wasm.sh \
  web/evo_boids.js web/evo_boids.wasm \
  web/evo_boids_mt.js web/evo_boids_mt.wasm
git diff --check
git status --short
```

Replace `BASE_SHA` with the recorded fixed-PR-1 SHA. Also confirm production world, public configuration behavior, fingerprint format, checkpoint APIs and renderer are unchanged.

Do not use receipt skipping for the first run of any changed gate.

**16. Coordinator commits and final report**

The implementer must leave reviewable file changes and evidence; the coordinator commits.

Suggested commits:

1. **`Add internal Ocean mechanics and fuel accounting`**
   - Kernels, contact, transactions, action adapter and focused tests.
2. **`Freeze Ocean mechanics assays and deterministic fixtures`**
   - Assays/reference comparisons, measured calibration, generated fixtures, parity integration, timing/memory tooling and documentation.
3. A module-artifact commit only if a required rebuild produces an understood source-related change. An unexplained module change blocks the PR; do not create an empty artifact commit.

Use merge commits for the stacked PR workflow. No merge/deploy/rebaseline authorization is included. End commit messages with the coordinator-approved tool attribution trailer.

The implementer’s final report must contain:

```text
Base:
- Fixed PR 1 SHA and verified prerequisite fixes.
- Final changed-file list.

Scope:
- Mechanics/energetics/contact/reserve kernels exercised internally.
- Public activation still refused.
- Production lifecycle/rendering/checkpoint/fingerprint integration deferred to PR 3.

Laws:
- Geometry/material/expression/reference/mechanics/energetics and ABI versions.
- Constant/reference/coefficient digests.
- Every departure from starting constants and its assay justification.
- Paired induced-efficiency interpretation.

Calibration:
- Assays 1–4, all subcases, numerical results and acceptance bounds.
- Actual sustained/peak speeds; fatigue fill/recovery.
- Steering results at 40/82/120, burst windows and body ordering.
- Calorimetry partition, 120 s debit and logged test subsidies.
- Paths to frozen manifest and raw windows.

Determinism:
- Full plain/eye Ocean suite results and native/wasm output equality.
- Hydro fixture native == wasm == generated committed fixture.
- Every-substep mechanics fixture equality.
- Independent reference worst errors and patch-model differences.
- Full historical matrix and expanded twin counts.
- Raw full-gate exit status and exact life_cap_fixture_s1 exception, if present.
- No OFF baselines changed.

Performance/memory:
- Raw paired component timings; A/A variation; build/hardware identity.
- Measured ns/fish-step and remaining +448 ns allowance.
- Explicit statement that complete-world ≤1.25x acceptance awaits PR 3.
- Record sizes, vector capacities, actual resident bytes, construction/copy/export peaks.

Release checks:
- Ocean rebuild/freshness.
- Unchanged src/core, Classic hashes and historical fingerprints.
- Native ctest and available module-consumer checks.
- Tests unavailable offline, if any.

Handoff:
- Exact remaining PR 3 work.
- Any failed or unfulfilled acceptance criterion.
- Proposed coordinator commits.
```

Do not report assays, fixtures, parity, memory, or performance as passed until their recorded measurements establish it.

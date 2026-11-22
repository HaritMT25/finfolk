#pragma once
// ----------------------------------------------------------------------------
// hydro_state — M2b's per-fish moving state (state ABI 1): one dense column
// beside the coefficient and support columns (hydro_coefficients.hpp), owned
// by the same owner ids and compacted with the same stable alive mask as
// M2a's body columns. foodReserves stays the sole fuel ledger (the lipid
// mass is max(E, 0)/500, never stored here). Water samples and solver
// workspaces are transient, never state.
//
// Frames (hydro_math.hpp's contract): com, vGround and LWorld are in WORLD
// coordinates (legacy x, −depth, legacy y); quat maps canonical body
// coordinates into the world; LWorld is the material angular momentum about
// the COM. The integrator, its writes and these fields' update order arrive
// with M2b1 PR 2; PR 1 fixes the layout, its hash order and the founders'
// rest state.
//
// Hashing: the explicit fields in declaration order (18 floats, then the
// status word), never the struct's bytes as such; sizeof == 76, no padding.
// ----------------------------------------------------------------------------
#include <cstdint>
#include <cstring>
#include "hydro_math.hpp"

namespace hydro {

inline constexpr int kStateAbi = 1;

// status bits
enum StatusBit : std::uint32_t {
    kStatusCompiled = 1u << 0,   // its coefficient / support records are compiled and current
    kStatusContact = 1u << 1,    // in hull contact at the end of the last step (diagnostic)
    kStatusRailed = 1u << 2,     // the angular-speed rail acted in the last step (diagnostic)
    kStatusFailure = 1u << 31,   // a physics failure (a non-positive / non-finite pivot): never repaired silently
};

struct HydroState {
    float com[3];          // material COM, world
    float vGround[3];      // COM velocity over ground, world
    float quat[4];         // w, x, y, z: canonical body -> world
    float LWorld[3];       // material angular momentum about the COM, world
    float gasContent;      // surface-pressure-equivalent gas volume G (u³)
    float tailDrive;       // filtered caudal forward request
    float tailYaw;         // filtered caudal yaw request
    float requestedSpeed;  // the speed target (push mode integrates it)
    float fatigue;         // F: the motor-work-equivalent fatigue load
    std::uint32_t status;  // StatusBit
};
static_assert(sizeof(HydroState) == 76, "HydroState: 18 binary32 fields and a status word, no padding");
static_assert(sizeof(HydroState) <= 96, "the HydroState column's ceiling is 96 B a fish");
inline constexpr int kStateFloats = 18;

// A fish at rest relative to its local water (world velocity waterWorld),
// upright and heading along the horizontal world direction f, with zero
// angular momentum, zero fatigue, zero gas content (its regulator pays to
// establish trim) and zero filtered requests: the accepted newborn's and the
// founder's initial state.
inline HydroState restState(V3 comWorld, V3 waterWorld, V3 f) {
    HydroState s{};
    put(s.com, comWorld);
    put(s.vGround, waterWorld);
    const Q4 q = uprightPose(f);
    s.quat[0] = q.w; s.quat[1] = q.x; s.quat[2] = q.y; s.quat[3] = q.z;
    s.status = kStatusCompiled;
    return s;
}
inline Q4 poseOf(const HydroState& s) { return Q4{s.quat[0], s.quat[1], s.quat[2], s.quat[3]}; }

// The state's explicit fields in hash order (18 floats as their bits, then
// the status word): the enabled fingerprint (PR 3) and the checkpoint
// envelope encode exactly these, little-endian.
template <class Sink>
inline void forEachStateWord(const HydroState& s, Sink&& sink) {
    const float* f[] = {&s.com[0], &s.com[1], &s.com[2], &s.vGround[0], &s.vGround[1], &s.vGround[2], &s.quat[0], &s.quat[1], &s.quat[2],
                        &s.quat[3], &s.LWorld[0], &s.LWorld[1], &s.LWorld[2], &s.gasContent, &s.tailDrive, &s.tailYaw,
                        &s.requestedSpeed, &s.fatigue};
    for (const float* p : f) { std::uint32_t u; std::memcpy(&u, p, 4); sink(u); }
    sink(s.status);
}

}  // namespace hydro

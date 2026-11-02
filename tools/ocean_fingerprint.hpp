#pragma once
// ----------------------------------------------------------------------------
// ocean_fingerprint — an exact, platform-independent hash of an OceanWorld's
// whole state, for the determinism harness (tools/ocean_parity_driver.cpp,
// wasm/ocean_parity.sh: native == wasm == the committed baseline) and
// tests/ocean_tests.cpp.
//
// Encoding: every value goes through an explicit encoding (floats and doubles
// by bit pattern, bools as 0 / 1, integers widened to 64 bits, byte arrays
// packed little-endian eight to a word), never as raw struct memory, so
// padding and layout cannot leak in and the same state hashes the same on
// x86-64 and wasm32. Words are absorbed by a mix that is a bijection in both
// the running hash and the word, so ONE changed value always changes its
// section's hash. Sections are hashed separately so a mismatch says WHAT
// diverged first:
//
//   cfg   every SimConfig and every OceanConfig field, by bit pattern; the
//         ocean-vision keys (eye, eyeOnly, eyeCode, steerFrame, foodLife, and
//         labelFrame since the ALIFE 2027 A1 arm) each
//         as a tagged word only when it is not its default (0); the glass-wall
//         keys as one tagged block only off their defaults (format 4 below)
//   ctr   frame, world size, D, every WorldCommon counter, nextId_, the
//         pairing-graph window, the death / birth logs, totalReseeds and the
//         wave trains' travelled phases
//   fish  every Fish: all AgentCore fields (ids, energy, timers, internal
//         state, body params, genome gene by gene, the built net's neurons and
//         flat connections, lastSensors / lastActions, colour) + pos, vel,
//         lastMoveDir, depth, vz, bodyBuoy and the 6-point body trail
//   food  every OceanFood: pos, depth, alive, size; its age (foodLife) while
//         foodLife > 0, and a non-zero age (tagged) while it is 0 — ages kept
//         after foodLife was switched off live matter again if it comes back
//         on; in the eye build also eyeCon (the contrast the eye sees)
//   pred  every OceanPredator: every Predator field + depth, pitch
//   sig   the pheromone grid bytes
//   cur   the CurrentField's WHOLE state: mode, strength, core, the size it
//         was built for, the gyre's eps / omega / amplitude / clock, every
//         vortex (base, sign, amplitudes, frequencies, phases: vortexState())
//         and every current centre; then the velocity it gives on a fixed
//         8 x 5 lattice and, while the 3-D flow is on (flowE1), flowAt on
//         that lattice at three depths
//   geo   persistent geometry: both neighbour grids (the fish's SpatialGrid and
//         the OceanFoodGrid: width, height, cols, rows, 1 / cell size), the SignalGrid (world size, cell size, cols, rows,
//         seam period, toroidal flag, byte count), the food-patch centres and
//         per-patch depths, the wave trains' fixed modes (format 3: prepared
//         lazily, the first time the waves are on; a world whose waves were
//         never on hashes the unprepared defaults)
//   rng   the global engine: its 624 words and its position
//
// and, OUTSIDE the simulation's combined hash (`all`, the chain):
//
//   app   the appearance genome (src/ocean/appearance_model.hpp: cosmetic,
//         read by nothing the step computes): the schema / law / inheritance /
//         founder / chart versions, the appearance config keys (appearance and
//         its five inheritance knobs, every one by bit pattern), the world's
//         flags as of init, the broken flag, the stream key, the construction
//         counters, the record count, then per record (creature order) the
//         creature's id, the stored owner id and all 63 floats by bit pattern.
//         Printed (`app=`, and the driver's `appchain=`) whenever appearance is
//         on or a knob is off its default; never mixed into `all`, so the 9
//         simulation sections, `all` and `chain` of a run with appearance on
//         are byte for byte those of the same run with it off — the harness's
//         app_off_* twins check exactly that (wasm/ocean_parity.sh).
//
// Not hashed, by design: scratch the step rebuilds from hashed state before
// reading it (the grids' entries — the food grid's copies of each item's depth /
// size / eyeCon among them — hot_, pending_, the neighbour vectors and the
// bounded food scan's list of items within R (foodSeen_), the
// E1 flow cache flow_ — src/ocean/ocean_flow.hpp: tables and keys derived from
// cfg / ocfg / the world size / the wave phases / the CurrentField's vortices
// and the frame, rebuilt by OceanWorld::ensureFlow before any read; the flow
// it gives IS hashed, in cur) and WorldCommon::prof (the wall-clock profiler;
// cfg.profile itself is hashed). The eye build's scratch too: hot_'s eyeSize /
// eyeCon (every fish's look, rewritten by eyePrepare before the per-fish phase
// whenever the eye is on, and by the fish itself after it moves; unread while
// the eye is off) and predCon_ (every predator's contrast, rewritten by
// eyePrepare each step the eye is on); and OceanWorld::oprof (-DEVO_OCEAN_PROF,
// wall clock). Statistics the step never reads: totalFoodEaten and
// totalFoodExpired (the harness's coverage counters report them instead),
// and the diagnostic totalNonFiniteRemoved (the driver adds it to its
// non-finite count).
//
// Every word added for the ocean-vision state (the tagged config keys, the
// food ages, the eye build's eyeCon) is hashed only in states a format-2
// baseline cannot hold (a key off its default, a non-zero age, the eye
// build), so those additions kept the format at 2.
//
// Format 3 (2026-10-28): the engine prepares the wave modes lazily
// (ocean_world.hpp, prepareWaves), so in a world whose waves are off at init
// the geo section hashes the unprepared modes until the waves are first on —
// a change in what a format-2 baseline holds, hence the bump. Nothing else
// moved: every other section, of every case, is what format 2 recorded.
//
// Format 4 (2026-10-28, the appearance genome): the `app` section above,
// printed on every fingerprint line of a world with appearance on (the
// default), and the appearance config keys (hashed in `app`, not `cfg`).
// Nothing else moved: with the `app=` / `appchain=` fields and the cover
// line's app* counters taken out, every case's output is its format-3 output
// (the header's format number aside).
//
// Format 4, the glass walls (OceanConfig walls / sideWallBand /
// sideWallTurnRate; a conditional extension like the ocean-vision keys', so
// the format stays 4): `cfg` absorbs one tagged block (kWallsTag, then the
// three keys) only when walls are on or a side knob is off its default
// (oceanWallsAtDefaults), and `cur` absorbs the flow sampled ON the six faces
// (forWallFaceSamples) only while walls are on. A world without walls hashes
// every word it did before the keys existed (walls = false with the default
// knobs is the same as leaving them out); no new per-fish, food or predator
// state exists. The keys are dumped and scanned for non-finite values too.
//
// Private state is read WITHOUT engine accessors (namespace peek below: a
// pointer to member taken in an explicit template instantiation, where C++
// waives access checking, [temp.spec.general]). Each one names its member, so
// a renamed or retyped member stops this header compiling.
//
// Tripwires (compile errors, not silent gaps): every hashed aggregate's field
// count is static_asserted (a new SimConfig / OceanConfig / AgentCore / Fish /
// Predator / food / log field must be hashed here before the harness builds),
// and the classes with private members (OceanWorld, CurrentField, SpatialGrid,
// SignalGrid, the rng engine) are size-checked against mirrors of their member
// lists (a new member must be hashed, or listed above as scratch).
//
// The format is versioned (kFormatVersion, printed in every driver header and
// so in every baseline file): bump it whenever this file changes what or how
// it hashes, so a baseline diff that comes from the harness reads as such.
// ----------------------------------------------------------------------------
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>
#include "ocean/ocean_config.hpp"
#include "ocean/ocean_world.hpp"

namespace ofp {

inline constexpr int kFormatVersion = 4;

// ---- private engine state, read without an accessor -------------------------
namespace peek {
template <class Tag, auto M>
struct Expose { friend constexpr auto member(Tag) noexcept { return M; } };
}  // namespace peek
}  // namespace ofp

#define OFP_PEEK(NAME, CLASS, FIELD)                                     \
    namespace ofp::peek {                                                \
    struct NAME { friend constexpr auto member(NAME) noexcept; };        \
    template struct Expose<NAME, &CLASS::FIELD>;                         \
    }
OFP_PEEK(OwCurrent, OceanWorld, current_)
OFP_PEEK(OwPatches, OceanWorld, foodPatches_)
OFP_PEEK(OwPatchDepth, OceanWorld, foodPatchDepth_)
OFP_PEEK(OwCreatureGrid, OceanWorld, creatureGrid_)
OFP_PEEK(OwFoodGrid, OceanWorld, foodGrid_)
OFP_PEEK(OwWaves, OceanWorld, waves_)
OFP_PEEK(OwHot, OceanWorld, hot_)
OFP_PEEK(CfMode, CurrentField, mode_)
OFP_PEEK(CfCenters, CurrentField, centers_)
OFP_PEEK(CfStrength, CurrentField, strength_)
OFP_PEEK(CfCore, CurrentField, core_)
OFP_PEEK(CfW, CurrentField, w_)
OFP_PEEK(CfH, CurrentField, h_)
OFP_PEEK(CfGyreEps, CurrentField, gyreEps_)
OFP_PEEK(CfGyreOmega, CurrentField, gyreOmega_)
OFP_PEEK(CfGyreA, CurrentField, gyreA_)
OFP_PEEK(CfGyreT, CurrentField, gyreT_)
OFP_PEEK(SgWidth, SpatialGrid, width_)
OFP_PEEK(SgHeight, SpatialGrid, height_)
OFP_PEEK(SgCols, SpatialGrid, cols_)
OFP_PEEK(SgRows, SpatialGrid, rows_)
OFP_PEEK(SgInvCell, SpatialGrid, invCell_)
OFP_PEEK(FgWidth, OceanFoodGrid, width_)
OFP_PEEK(FgHeight, OceanFoodGrid, height_)
OFP_PEEK(FgCols, OceanFoodGrid, cols_)
OFP_PEEK(FgRows, OceanFoodGrid, rows_)
OFP_PEEK(FgInvCell, OceanFoodGrid, invCell_)
OFP_PEEK(SigW, SignalGrid, w_)
OFP_PEEK(SigH, SignalGrid, h_)
OFP_PEEK(SigWrapCols, SignalGrid, wrapCols_)
OFP_PEEK(SigWrapRows, SignalGrid, wrapRows_)
OFP_PEEK(SigToroidal, SignalGrid, toroidal_)
OFP_PEEK(RgEngine, RandomGen, engine_)
OFP_PEEK(MtWords, PortableMT19937, x_)
OFP_PEEK(MtPos, PortableMT19937, p_)
#undef OFP_PEEK

namespace ofp {

// The private member `Tag` names, of obj (const in, const out; tests that bump
// private state pass a non-const object).
template <class Tag, class T>
constexpr decltype(auto) field(T& obj) { return (obj.*member(Tag{})); }

// ---- tripwires ----------------------------------------------------------------
namespace detail {
struct AnyField { template <class T> constexpr operator T() const noexcept; };
// The number of initializers an aggregate takes (arrays count element by element).
template <class T, class... A>
constexpr std::size_t fieldCount() {
    if constexpr (requires { T{A{}..., AnyField{}}; }) return fieldCount<T, A..., AnyField>();
    else return sizeof...(A);
}
}  // namespace detail

#define OFP_FIELDS(T, N) \
    static_assert(detail::fieldCount<T>() == (N), #T " gained or lost a field: hash it in tools/ocean_fingerprint.hpp, then update this count")
OFP_FIELDS(SimConfig, 71);
OFP_FIELDS(OceanConfig, 37);
OFP_FIELDS(appearance::Stats, 10);   // founders, offspring, pattern[4], morph[4]
OFP_FIELDS(AgentCore, 16 + NUM_SENSES + NUM_ACTIONS + 1);   // 14 scalars + genome + nnet, the two arrays, colour
OFP_FIELDS(Fish, 1 + 6 + Fish::BODY_LEN);                   // base, pos .. bodyBuoy, body[]
OFP_FIELDS(Predator, 9);
OFP_FIELDS(OceanPredator, 3);                               // base, depth, pitch
OFP_FIELDS(OceanFood, 5 + (kOceanHasEye ? 1 : 0));   // pos, depth, alive, size, age (+ eyeCon)
OFP_FIELDS(Gene, 5);
OFP_FIELDS(NeuralNet, 2);
OFP_FIELDS(NeuralNet::Neuron, 2);
OFP_FIELDS(NeuralNet::FlatConn, 2);
OFP_FIELDS(WorldCommon, 25);
OFP_FIELDS(WorldCommon::DeathRecord, 7 + CLUSTER_SKETCH_DIM);
OFP_FIELDS(WorldCommon::BirthRecord, 6);
OFP_FIELDS(repro::Edge, 2);
#undef OFP_FIELDS

// Mirrors of the member lists of the classes with private state (same types,
// same order, so the same size on every ABI).
namespace mirror {
struct SignalGrid_ { int w, h, cell, cols, rows, wrapCols, wrapRows; bool tor; std::vector<std::uint8_t> g; };
struct SpatialGrid_ { int w, h, cols, rows; float inv; std::vector<int> start, cursor, staged, entries; };
struct OceanFoodGrid_ {   // the entries (x .. index) are scratch
    int w, h, cols, rows; float inv; std::vector<int> start, cursor, staged; std::vector<float> x, y, z, size;
#ifdef EVO_OCEAN_EYE
    std::vector<float> con;
#endif
    std::vector<int> index;
};
struct CurrentField_ { CurrentField::Mode m; std::vector<int> vort, centers; float s, core; int w, h; float eps, om, a, t; };
struct Mt_ { std::uint32_t x[624]; int p; };
struct WaveTrain_ { double kx, ky, phase, phi; float k, qx, qy, frac; };
struct FishHot_ {
    Vec2 pos, vel; float depth;
#ifdef EVO_OCEAN_EYE
    float eyeSize, eyeCon;   // scratch (see above)
#endif
};
struct Pending_ { bool wants; Vec2 pos; };
struct OceanWorld_ : WorldCommon {
    int width, height; float D; OceanConfig ocfg;
    std::vector<Fish> creatures; std::vector<OceanPredator> predators; std::vector<OceanFood> food;
    SignalGrid signals; long long totalReseeds, totalFoodEaten, totalFoodExpired,   // the last three: statistics
        totalNonFiniteRemoved;
#ifdef EVO_OCEAN_PROF
    OceanWorld::OceanProf oprof;   // wall clock
#endif
    SpatialGrid creatureGrid; OceanFoodGrid foodGrid; std::vector<FishHot_> hot; std::vector<Pending_> pending;
    std::vector<int> neighbors, nearbyFood, nearby, near;
    std::vector<int> foodSeen;   // scratch (see above)
    CurrentField current; std::vector<Vec2> patches; std::vector<float> patchDepth;
    std::vector<appearance::Record> app; std::uint64_t appKey; int appFlags; bool appBroken; appearance::Stats appStats;
    WaveTrain_ waves[OceanWorld::kWaveTrains];
    oceanflow::FlowCache flow;   // scratch (see above)
#ifdef EVO_OCEAN_EYE
    std::vector<float> predCon;  // scratch (see above)
#endif
};
}  // namespace mirror
static_assert(sizeof(SignalGrid) == sizeof(mirror::SignalGrid_), "SignalGrid's members changed: update hashGeometry and mirror::SignalGrid_");
static_assert(sizeof(SpatialGrid) == sizeof(mirror::SpatialGrid_), "SpatialGrid's members changed: update hashGrid and mirror::SpatialGrid_");
static_assert(sizeof(OceanFoodGrid) == sizeof(mirror::OceanFoodGrid_), "OceanFoodGrid's members changed: update hashGrid and mirror::OceanFoodGrid_");
static_assert(sizeof(CurrentField) == sizeof(mirror::CurrentField_), "CurrentField's members changed: update hashCurrent and mirror::CurrentField_");
static_assert(sizeof(PortableMT19937) == sizeof(mirror::Mt_) && sizeof(RandomGen) == sizeof(mirror::Mt_),
              "the rng engine's members changed: update hashRng and mirror::Mt_");
// hot_ is a vector (its size does not show in OceanWorld's): its element is checked on its own.
static_assert(sizeof(std::remove_cvref_t<decltype(field<peek::OwHot>(std::declval<const OceanWorld&>()))>::value_type) ==
                  sizeof(mirror::FishHot_),
              "OceanWorld::FishHot's members changed: list the new one as scratch (or hash it) and update mirror::FishHot_");
static_assert(sizeof(OceanWorld) == sizeof(mirror::OceanWorld_),
              "OceanWorld's members changed: hash the new state (or list it as scratch) and update mirror::OceanWorld_");

// ---- the hash -----------------------------------------------------------------
inline std::uint32_t bits(float f) { std::uint32_t x; std::memcpy(&x, &f, 4); return x; }
inline std::uint64_t bits64(double d) { std::uint64_t x; std::memcpy(&x, &d, 8); return x; }

// Two lanes take alternate words (two independent multiply chains: about twice
// the throughput of one); each lane's step (xor, odd multiply, xorshift) is a
// bijection in the lane and in the word, and value() is a bijection in each
// lane, so changing any one word always changes value().
struct Hasher {
    std::uint64_t la = 0x243F6A8885A308D3ull, lb = 0x13198A2E03707344ull;
    bool odd = false;
    static std::uint64_t mix(std::uint64_t h, std::uint64_t v) {
        h ^= v;
        h *= 0x9E3779B97F4A7C15ull;
        return h ^ (h >> 29);
    }
    void u64(std::uint64_t v) {
        if (odd) lb = mix(lb, v);
        else     la = mix(la, v);
        odd = !odd;
    }
    void u32(std::uint32_t v) { u64(v); }
    void i32(int v) { u64((std::uint32_t)v); }
    void i64(long long v) { u64((std::uint64_t)v); }
    void b(bool v) { u64(v ? 1u : 0u); }
    void f32(float f) { u64(bits(f)); }
    void f64(double d) { u64(bits64(d)); }
    void f32x2(float a, float b) { u64((std::uint64_t)bits(a) | ((std::uint64_t)bits(b) << 32)); }
    void v2(Vec2 v) { f32x2(v.x, v.y); }
    void bytes(const std::uint8_t* p, std::size_t n) {
        u64(n);
        for (std::size_t i = 0; i < n; i += 8) {
            std::uint64_t w = 0;
            for (std::size_t k = 0; k < 8 && i + k < n; ++k) w |= (std::uint64_t)p[i + k] << (8 * k);
            u64(w);
        }
    }
    // Named-field visitor interface (visitSimConfig / visitOceanConfig).
    void f32(const char*, float v) { f32(v); }
    void i32(const char*, int v) { i32(v); }
    void b(const char*, bool v) { b(v); }
    std::uint64_t value() const {   // both lanes, then murmur3's fmix64
        std::uint64_t x = mix(mix(0xA4093822299F31D0ull, la), lb);
        x ^= x >> 33; x *= 0xff51afd7ed558ccdull;
        x ^= x >> 33; x *= 0xc4ceb9fe1a85ec53ull;
        x ^= x >> 33;
        return x;
    }
};

struct Fingerprint {
    std::uint64_t all = 0, cfg = 0, ctr = 0, fish = 0, food = 0, pred = 0, sig = 0, cur = 0, geo = 0, rng = 0;
    std::uint64_t app = 0;   // the appearance section: NOT in `all` (see the top)
    bool appShown = false;   // printed: appearance on, or an appearance knob off its default
    bool operator==(const Fingerprint& o) const {
        return all == o.all && cfg == o.cfg && ctr == o.ctr && fish == o.fish && food == o.food && pred == o.pred &&
               sig == o.sig && cur == o.cur && geo == o.geo && rng == o.rng && app == o.app && appShown == o.appShown;
    }
    bool operator!=(const Fingerprint& o) const { return !(*this == o); }
};

// Every section, for loops over them (tests).
inline constexpr std::uint64_t Fingerprint::* kSections[] = {
    &Fingerprint::cfg, &Fingerprint::ctr, &Fingerprint::fish, &Fingerprint::food, &Fingerprint::pred,
    &Fingerprint::sig, &Fingerprint::cur, &Fingerprint::geo, &Fingerprint::rng};

// ---- configs: every field, by name, in declaration order --------------------
// V needs f32(name, float), i32(name, int), b(name, bool). The field counts
// above are what keep these lists complete.
#define OFP_F(n) v.f32(#n, c.n)
#define OFP_I(n) v.i32(#n, c.n)
#define OFP_B(n) v.b(#n, c.n)
template <class V>
void visitSimConfig(const SimConfig& c, V& v) {
    OFP_B(toroidal); OFP_F(reproMaxDistance); OFP_F(reproSoftWidth); OFP_F(reproGracePeriod);
    OFP_B(bodyModel); OFP_F(bodyMutation);
    OFP_I(minPopulation); OFP_I(maxPopulation); OFP_I(targetFood);
    OFP_F(foodSpawnBase); OFP_F(foodSpawnAmp); OFP_F(foodEnergy); OFP_F(pickupRadius);
    OFP_F(metabolicRate); OFP_F(geneCost); OFP_F(moveCost); OFP_F(maxAge); OFP_F(reproEnergy); OFP_F(newbornEnergy);
    OFP_F(perceptionRadius); OFP_F(interactRadius); OFP_I(maxNeighbors);
    OFP_F(reproCooldown); OFP_F(interactCooldown); OFP_F(minSpeed); OFP_F(maxSpeed);
    OFP_B(triangularMotion); OFP_F(maxTurnRate);
    OFP_I(genomeMinLength); OFP_I(genomeMaxLength); OFP_I(genomeInitMin); OFP_I(genomeInitMax);
    OFP_F(mutationMultiplier);
    OFP_F(currentStrength); OFP_I(currentMode); OFP_I(currentEddies); OFP_F(currentCore); OFP_F(currentDrift);
    OFP_F(currentGyreEps);
    OFP_I(foodPatches); OFP_F(foodPatchRadius); OFP_B(foodDrift);
    OFP_I(predatorCount); OFP_F(predatorPerception); OFP_F(predatorSpeed); OFP_F(predatorCaptureRadius);
    OFP_F(predatorCooldown); OFP_B(predatorEconomy); OFP_F(predatorMetabolism); OFP_F(predatorMoveCost);
    OFP_F(predatorReproEnergy); OFP_F(predatorNewbornEnergy); OFP_F(predatorMeal); OFP_F(predatorMaxAge);
    OFP_I(predatorMinPopulation); OFP_I(predatorMaxPopulation); OFP_B(predatorInheritance);
    OFP_F(predatorTraitMutation);
    OFP_B(captureActivations); OFP_I(reproWindow); OFP_I(reproMinCluster); OFP_B(reproLog); OFP_I(reproLogMax);
    OFP_B(clusterMap); OFP_I(clusterMax); OFP_I(clusterEpoch); OFP_B(clusterPca); OFP_I(clusterColor);
    OFP_B(wiringLog); OFP_B(profile); OFP_B(fastTanh);
}
template <class V>
void visitOceanConfig(const OceanConfig& c, V& v) {
    OFP_F(depth); OFP_F(kBuoy); OFP_F(buoyMutation); OFP_F(pitchMax); OFP_F(vDrag); OFP_F(wallBand);
    OFP_F(cHold); OFP_F(cPress); OFP_I(foodDepthMode); OFP_F(foodDepthSpread);
    OFP_F(waveSpeed); OFP_F(waveBand); OFP_F(waveGravity); OFP_B(deepCurrent); OFP_B(lightEnabled);
    OFP_F(L0); OFP_F(kWater); OFP_B(depthCostScaled); OFP_B(sizeDrift); OFP_B(sizeFight); OFP_B(mouthGate);
    OFP_F(kMouth);
}
// The ocean-vision keys (all default 0): dumped and scanned like the rest, but
// hashed only when not at their default (hashConfig), so a config without them
// hashes exactly as before they existed.
template <class V>
void visitOceanConfigVision(const OceanConfig& c, V& v) {
    OFP_I(eye); OFP_I(eyeOnly); OFP_I(eyeCode); OFP_I(steerFrame); OFP_F(foodLife);
    OFP_I(labelFrame);   // tagged like the others: hashed only off its default 0
}
// The appearance keys (hashed in `app`, not `cfg`: cosmetic; see the top).
template <class V>
void visitOceanConfigAppearance(const OceanConfig& c, V& v) {
    OFP_I(appearance); OFP_F(patternMutation); OFP_F(patternPhaseMutation); OFP_F(patternNovelProbability);
    OFP_F(morphologyMutation); OFP_F(morphologyNovelProbability);
}
// The glass-wall keys (walls, sideWallBand, sideWallTurnRate): dumped and
// scanned like the rest, hashed in `cfg` as one tagged block only when they
// are not at their defaults (hashConfig; oceanWallsAtDefaults).
template <class V>
void visitOceanConfigWalls(const OceanConfig& c, V& v) {
    OFP_B(walls); OFP_F(sideWallBand); OFP_F(sideWallTurnRate);
}
#undef OFP_F
#undef OFP_I
#undef OFP_B

// The tagged walls block's tag (an FNV-1a word like VisionTagger's, of "walls-block").
inline constexpr std::uint64_t kWallsTag = 0x9A1C5E77D0B0C4E5ull;

// A distinct tag word per key, then its value (bit pattern for the float).
struct VisionTagger {
    Hasher& h;
    static std::uint64_t tag(const char* k) {   // FNV-1a of the key's name, high bit set
        std::uint64_t t = 0xcbf29ce484222325ull;
        for (const char* p = k; *p; ++p) { t ^= (unsigned char)*p; t *= 0x100000001b3ull; }
        return t | 0x8000000000000000ull;
    }
    void i32(const char* k, int v) { if (v != 0) { h.u64(tag(k)); h.i32(v); } }
    void f32(const char* k, float v) { if (bits(v) != 0u) { h.u64(tag(k)); h.f32(v); } }   // -0.0 too
    void b(const char* k, bool v) { if (v) { h.u64(tag(k)); h.b(v); } }
};

inline void hashConfig(Hasher& h, const SimConfig& c, const OceanConfig& o) {
    visitSimConfig(c, h);
    visitOceanConfig(o, h);
    VisionTagger t{h};
    visitOceanConfigVision(o, t);
    if (!oceanWallsAtDefaults(o)) {   // the glass walls: one tagged block, only off the defaults
        h.u64(kWallsTag);
        visitOceanConfigWalls(o, h);
    }
}

inline void hashCounters(Hasher& h, const OceanWorld& w) {
    h.u64(w.frame); h.i32(w.width); h.i32(w.height); h.f32(w.D);
    h.i32(w.births); h.i32(w.deaths); h.i64(w.totalBirths); h.i64(w.totalDeaths);
    h.i64(w.totalGraceBirths); h.i64(w.totalSoftBirths);
    h.i64(w.totalDeathsPredation); h.i64(w.totalDeathsStarvation); h.i64(w.totalDeathsAge);
    h.i64(w.totalPredatorBirths); h.i64(w.totalPredatorDeathsStarvation);
    h.i64(w.totalPredatorDeathsAge); h.i64(w.totalPredatorReseeds);
    h.i64(w.totalReseeds); h.u64(w.nextId_);
    h.i64(w.totalDeathsLogged_); h.i64(w.clusterStride_);
    h.i64(w.totalBirthsLogged_); h.i64(w.reproStride_);
    h.u64(w.reproWindow_.size()); h.u64(w.reproWindowNext_);
    for (const auto& e : w.reproWindow_) { h.u64(e.a); h.u64(e.b); }
    h.u64(w.deathLog.size());
    for (const auto& d : w.deathLog) {
        h.f32x2(d.x, d.y);
        for (float s : d.sketch) h.f32(s);
        h.i64(d.index); h.u64(d.lineageId); h.f32(d.age); h.i32(d.genomeLen); h.i32(d.cause);
    }
    h.u64(w.birthLog.size());
    for (const auto& r : w.birthLog) {
        h.i64(r.index); h.u64(r.parent1); h.u64(r.parent2); h.u64(r.lineage1); h.u64(r.lineage2);
        h.u64(r.frame);
    }
    for (int i = 0; i < OceanWorld::kWaveTrains; ++i) h.f64(w.wavePhase(i));
}

// ages: the world's foodLife > 0. Ages count only then; switched off live,
// they stop but stay (and matter again if it comes back on), so a non-zero age
// is hashed, tagged, then too. A world that never had foodLife on hashes the
// bytes it did before ages existed.
inline void hashFood(Hasher& h, const OceanFood& f, bool ages) {
    h.v2(f.pos);
    h.u64((std::uint64_t)bits(f.depth) | ((std::uint64_t)f.alive << 32));
    h.f32(f.size);
    if (ages) h.f32(f.age);
    else if (bits(f.age) != 0u) { h.u64(0x8000000041474521ull); h.f32(f.age); }
#ifdef EVO_OCEAN_EYE
    h.f32(f.eyeCon);   // the eye build only (set at every spawn, eye on or off)
#endif
}

// A gene in 32 bits: its four bit-fields (1 + 7 + 1 + 7, a uint16_t's worth:
// the size check below fails if they outgrow it) and the weight.
static_assert(sizeof(Gene) == 4, "Gene's bit-fields outgrew 16 bits: widen geneWord");
inline std::uint32_t geneWord(const Gene& g) {
    return (std::uint32_t)g.sourceType | ((std::uint32_t)g.sourceNum << 1) | ((std::uint32_t)g.sinkType << 8) |
           ((std::uint32_t)g.sinkNum << 9) | ((std::uint32_t)(std::uint16_t)g.weight << 16);
}
static_assert(MAX_INTERNAL_NEURONS <= 64, "the neurons' driven flags no longer fit one word");

// Two 32-bit values per word wherever they pair up (the fish section is most of
// the cost of a per-step fingerprint). withActivations = false leaves
// lastSensors / lastActions out (the dynamics alone), for checking that
// captureActivations does not change a run.
inline void hashFish(Hasher& h, const Fish& c, bool withActivations = true) {
    h.u64((std::uint64_t)c.alive | ((std::uint64_t)c.generation << 1));
    h.u64(c.id); h.u64(c.lineageId);
    h.f32x2(c.speed, c.age); h.f32x2(c.foodReserves, c.reproTimer); h.f32x2(c.interactTimer, c.responsiveness);
    h.f32x2(c.oscPeriod, c.oscPhase); h.f32x2(c.bodySize, c.bodyElong);
    const std::size_t ng = c.genome.size();
    h.u64(ng);
    for (std::size_t i = 0; i < ng; i += 2)
        h.u64((std::uint64_t)geneWord(c.genome[i]) | (i + 1 < ng ? (std::uint64_t)geneWord(c.genome[i + 1]) << 32 : 0));
    const auto& nr = c.nnet.neurons;
    std::uint64_t driven = 0;
    for (std::size_t i = 0; i < nr.size(); ++i) driven |= (std::uint64_t)nr[i].driven << i;
    h.u64(nr.size()); h.u64(driven);
    for (std::size_t i = 0; i < nr.size(); i += 2)
        h.u64((std::uint64_t)bits(nr[i].output) | (i + 1 < nr.size() ? (std::uint64_t)bits(nr[i + 1].output) << 32 : 0));
    const auto& fl = c.nnet.flat;
    auto flatWord = [](const NeuralNet::FlatConn& f) {
        return (std::uint64_t)f.srcSink | ((std::uint64_t)(std::uint16_t)f.weight << 16);
    };
    h.u64(fl.size());
    for (std::size_t i = 0; i < fl.size(); i += 2) h.u64(flatWord(fl[i]) | (i + 1 < fl.size() ? flatWord(fl[i + 1]) << 32 : 0));
    if (withActivations) {
        float io[(int)NUM_SENSES + (int)NUM_ACTIONS + 1] = {};
        std::memcpy(io, c.lastSensors, sizeof c.lastSensors);
        std::memcpy(io + NUM_SENSES, c.lastActions, sizeof c.lastActions);
        for (int i = 0; i < (int)NUM_SENSES + (int)NUM_ACTIONS; i += 2) h.f32x2(io[i], io[i + 1]);
    }
    h.u64((std::uint64_t)c.color.r | ((std::uint64_t)c.color.g << 8) | ((std::uint64_t)c.color.b << 16) |
          ((std::uint64_t)c.color.a << 24) | ((std::uint64_t)bits(c.bodyBuoy) << 32));
    h.v2(c.pos); h.v2(c.vel); h.v2(c.lastMoveDir);
    h.f32x2(c.depth, c.vz);
    for (int i = 0; i < Fish::BODY_LEN; ++i) h.v2(c.body[i]);
}

inline void hashPredator(Hasher& h, const OceanPredator& p) {
    h.v2(p.pos); h.v2(p.vel); h.f32x2(p.digestTimer, p.energy); h.f32(p.age); h.b(p.alive);
    h.f32x2(p.speedFactor, p.buddingFactor); h.u32(p.generation);
    h.f32x2(p.depth, p.pitch);
}

// The fixed lattice the current is sampled on, and the three depth fractions
// the 3-D flow is sampled at.
template <class F>
inline void forCurrentLattice(const OceanWorld& w, F&& f) {
    for (int j = 0; j < 5; ++j)
        for (int i = 0; i < 8; ++i)
            f(Vec2{((float)i + 0.5f) * (float)w.width / 8.0f, ((float)j + 0.5f) * (float)w.height / 5.0f});
}
template <class F>
inline void forFlowSamples(const OceanWorld& w, F&& f) {
    for (float frac : {0.1f, 0.5f, 0.9f}) forCurrentLattice(w, [&](Vec2 p) { f(p, frac * w.D); });
}

// Glass walls: the flow sampled ON the six faces (the interior lattice above
// never touches them): x = 0 and W along the lattice's y at its three depths,
// y = 0 and H along its x, and the surface and floor over the 8 x 5 lattice.
template <class F>
inline void forWallFaceSamples(const OceanWorld& w, F&& f) {
    const float W = (float)w.width, H = (float)w.height;
    for (float frac : {0.1f, 0.5f, 0.9f}) {
        const float d = frac * w.D;
        for (int j = 0; j < 5; ++j) { const float y = ((float)j + 0.5f) * H / 5.0f; f(Vec2{0.0f, y}, d); f(Vec2{W, y}, d); }
        for (int i = 0; i < 8; ++i) { const float x = ((float)i + 0.5f) * W / 8.0f; f(Vec2{x, 0.0f}, d); f(Vec2{x, H}, d); }
    }
    forCurrentLattice(w, [&](Vec2 p) { f(p, 0.0f); f(p, w.D); });
}

inline void hashCurrent(Hasher& h, const OceanWorld& w) {
    const CurrentField& cf = field<peek::OwCurrent>(w);
    h.i32((int)field<peek::CfMode>(cf));
    h.f32(field<peek::CfStrength>(cf)); h.f32(field<peek::CfCore>(cf));
    h.i32(field<peek::CfW>(cf)); h.i32(field<peek::CfH>(cf));
    h.f32(field<peek::CfGyreEps>(cf)); h.f32(field<peek::CfGyreOmega>(cf));
    h.f32(field<peek::CfGyreA>(cf)); h.f32(field<peek::CfGyreT>(cf));
    const std::vector<float> vs = cf.vortexState();
    h.u64(vs.size());
    for (float x : vs) h.f32(x);
    const auto& centers = field<peek::CfCenters>(cf);
    h.u64(centers.size());
    for (const Vec2& c : centers) h.v2(c);
    h.b(w.currentActive());
    if (w.currentActive()) forCurrentLattice(w, [&](Vec2 p) { h.v2(w.currentAt(p)); });
    h.b(w.flowE1());
    if (w.flowE1())
        forFlowSamples(w, [&](Vec2 p, float d) {
            const OceanWorld::Flow U = w.flowAt(p, d);
            h.f32x2(U.x, U.y); h.f32(U.d);
        });
    if (w.ocfg.walls) forWallFaceSamples(w, [&](Vec2 p, float d) {   // glass walls only: the faces themselves
        const OceanWorld::Flow U = w.flowAt(p, d);
        h.f32x2(U.x, U.y); h.f32(U.d);
    });
}

inline void hashGrid(Hasher& h, const SpatialGrid& g) {
    h.i32(field<peek::SgWidth>(g)); h.i32(field<peek::SgHeight>(g));
    h.i32(field<peek::SgCols>(g)); h.i32(field<peek::SgRows>(g));
    h.f32(field<peek::SgInvCell>(g));
}
// The food grid's geometry: the same five words in the same order as a
// SpatialGrid's (it was one until its entries carried the payload; the
// format is unchanged).
inline void hashGrid(Hasher& h, const OceanFoodGrid& g) {
    h.i32(field<peek::FgWidth>(g)); h.i32(field<peek::FgHeight>(g));
    h.i32(field<peek::FgCols>(g)); h.i32(field<peek::FgRows>(g));
    h.f32(field<peek::FgInvCell>(g));
}

inline void hashGeometry(Hasher& h, const OceanWorld& w) {
    hashGrid(h, field<peek::OwCreatureGrid>(w));
    hashGrid(h, field<peek::OwFoodGrid>(w));
    const SignalGrid& s = w.signals;
    h.i32(field<peek::SigW>(s)); h.i32(field<peek::SigH>(s)); h.i32(s.cellSize());
    h.i32(s.cols()); h.i32(s.rows());
    h.i32(field<peek::SigWrapCols>(s)); h.i32(field<peek::SigWrapRows>(s));
    h.b(field<peek::SigToroidal>(s)); h.u64(s.data().size());
    const auto& patches = field<peek::OwPatches>(w);
    h.u64(patches.size());
    for (const Vec2& p : patches) h.v2(p);
    const auto& pd = field<peek::OwPatchDepth>(w);
    h.u64(pd.size());
    for (float d : pd) h.f32(d);
    for (const auto& t : field<peek::OwWaves>(w)) {   // phase is in ctr
        h.f64(t.kx); h.f64(t.ky); h.f64(t.phi);
        h.f32x2(t.k, t.qx); h.f32x2(t.qy, t.frac);
    }
}

inline void hashRng(Hasher& h) {
    const auto& eng = field<peek::RgEngine>(rng);
    const auto& x = field<peek::MtWords>(eng);
    for (int i = 0; i < 624; i += 2) h.u64((std::uint64_t)x[i] | ((std::uint64_t)x[i + 1] << 32));
    h.i32(field<peek::MtPos>(eng));
}

// The appearance section (see the top).
inline bool appearanceShown(const OceanWorld& w) {
    return w.ocfg.appearance != 0 || w.appearanceInitFlags() != 0 || w.appearanceBroken() ||
           !oceanAppearanceKnobsAtDefaults(w.ocfg);
}
inline void hashAppearance(Hasher& h, const OceanWorld& w) {
    using namespace appearance;
    h.u64((std::uint64_t)kSchema | (std::uint64_t)kPatternSchema << 8 | (std::uint64_t)kPatternLaw << 16 |
          (std::uint64_t)kPatternInheritance << 24 | (std::uint64_t)kPatternFounder << 32 |
          (std::uint64_t)kMorphLaw << 40 | (std::uint64_t)kMorphInheritance << 48 | (std::uint64_t)kMorphFounder << 56);
    h.u64((std::uint64_t)kMorphChart | (std::uint64_t)kStride << 8 | (std::uint64_t)kAbi << 16);
    visitOceanConfigAppearance(w.ocfg, h);
    h.i32(w.appearanceInitFlags()); h.b(w.appearanceBroken()); h.u64(w.appearanceKey());
    const Stats& st = w.appearanceStats();
    h.u64(st.founders); h.u64(st.offspring);
    for (std::uint64_t x : st.pattern) h.u64(x);
    for (std::uint64_t x : st.morph) h.u64(x);
    const auto& recs = w.appearanceRecords();
    h.u64(recs.size());
    for (std::size_t i = 0; i < recs.size(); ++i) {
        h.u64(i < w.creatures.size() ? w.creatures[i].id : ~0ull);
        h.u64(recs[i].ownerId);
        const float* g = recs[i].genome.g;
        for (int j = 0; j + 1 < kStride; j += 2) h.f32x2(g[j], g[j + 1]);
        h.f32(g[kStride - 1]);
    }
}

inline Fingerprint fingerprint(const OceanWorld& w, bool withActivations = true) {
    Fingerprint fp;
    { Hasher h; hashConfig(h, w.cfg, w.ocfg); fp.cfg = h.value(); }
    { Hasher h; hashCounters(h, w); fp.ctr = h.value(); }
    { Hasher h; h.u64(w.creatures.size());
      for (const Fish& c : w.creatures) hashFish(h, c, withActivations);
      fp.fish = h.value(); }
    { Hasher h; h.u64(w.food.size());
      const bool ages = w.ocfg.foodLife > 0.0f;
      for (const OceanFood& f : w.food) hashFood(h, f, ages);
      fp.food = h.value(); }
    { Hasher h; h.u64(w.predators.size());
      for (const OceanPredator& p : w.predators) hashPredator(h, p);
      fp.pred = h.value(); }
    { Hasher h; const auto& d = w.signals.data(); h.bytes(d.data(), d.size()); fp.sig = h.value(); }
    { Hasher h; hashCurrent(h, w); fp.cur = h.value(); }
    { Hasher h; hashGeometry(h, w); fp.geo = h.value(); }
    { Hasher h; hashRng(h); fp.rng = h.value(); }
    Hasher a;
    for (auto s : kSections) a.u64(fp.*s);
    fp.all = a.value();
    fp.appShown = appearanceShown(w);
    { Hasher h; hashAppearance(h, w); fp.app = h.value(); }
    return fp;
}

// ---- non-finite floats --------------------------------------------------------
// The harness requires 0: a NaN's sign and payload are left to the host by the
// wasm spec (x86 makes 0xffc00000, ARM 0x7fc00000), so a run that carries a NaN
// can match native on one machine and not on another, and a NaN depth also
// slips past every 3-D range test. Every float and double of the hashed state:
// fish, food, predators, the configs, the current, the geometry, the logs.
struct NonFinite {
    long n = 0;
    void f(float v) { n += !std::isfinite(v); }
    void d(double v) { n += !std::isfinite(v); }
    void f32(const char*, float v) { f(v); }
    void i32(const char*, int) {}
    void b(const char*, bool) {}
};
inline long countNonFinite(const OceanWorld& w) {
    NonFinite nf;
    auto f = [&](float v) { nf.f(v); };
    for (const Fish& c : w.creatures) {
        for (float v : {c.speed, c.age, c.foodReserves, c.reproTimer, c.interactTimer, c.responsiveness,
                        c.oscPeriod, c.oscPhase, c.bodySize, c.bodyElong, c.pos.x, c.pos.y, c.vel.x, c.vel.y,
                        c.lastMoveDir.x, c.lastMoveDir.y, c.depth, c.vz, c.bodyBuoy})
            f(v);
        for (const Vec2& b : c.body) { f(b.x); f(b.y); }
        for (const auto& nr : c.nnet.neurons) f(nr.output);
        for (float s : c.lastSensors) f(s);
        for (float a : c.lastActions) f(a);
    }
    for (const OceanFood& fd : w.food) {
        f(fd.pos.x); f(fd.pos.y); f(fd.depth); f(fd.size); f(fd.age);
#ifdef EVO_OCEAN_EYE
        f(fd.eyeCon);
#endif
    }
    for (const OceanPredator& p : w.predators)
        for (float v : {p.pos.x, p.pos.y, p.vel.x, p.vel.y, p.digestTimer, p.energy, p.age, p.speedFactor,
                        p.buddingFactor, p.depth, p.pitch})
            f(v);
    f(w.D);
    visitSimConfig(w.cfg, nf);
    visitOceanConfig(w.ocfg, nf);
    visitOceanConfigVision(w.ocfg, nf);
    visitOceanConfigAppearance(w.ocfg, nf);
    visitOceanConfigWalls(w.ocfg, nf);
    for (const auto& r : w.appearanceRecords())
        for (float v : r.genome.g) f(v);
    const CurrentField& cf = field<peek::OwCurrent>(w);
    for (float v : cf.vortexState()) f(v);
    for (const Vec2& c : field<peek::CfCenters>(cf)) { f(c.x); f(c.y); }
    for (float v : {field<peek::CfStrength>(cf), field<peek::CfCore>(cf), field<peek::CfGyreEps>(cf),
                    field<peek::CfGyreOmega>(cf), field<peek::CfGyreA>(cf), field<peek::CfGyreT>(cf)})
        f(v);
    for (const auto& t : field<peek::OwWaves>(w)) {
        for (double v : {t.kx, t.ky, t.phase, t.phi}) nf.d(v);
        for (float v : {t.k, t.qx, t.qy, t.frac}) f(v);
    }
    for (const Vec2& p : field<peek::OwPatches>(w)) { f(p.x); f(p.y); }
    for (float d : field<peek::OwPatchDepth>(w)) f(d);
    f(field<peek::SgInvCell>(field<peek::OwCreatureGrid>(w)));
    f(field<peek::FgInvCell>(field<peek::OwFoodGrid>(w)));
    for (const auto& d : w.deathLog) {
        f(d.x); f(d.y); f(d.age);
        for (float s : d.sketch) f(s);
    }
    return nf.n;
}

// One fingerprint line: the step, the combined hash, a few readable counts,
// then every section's hash.
inline std::string fingerprintLine(const char* tag, long long step, const OceanWorld& w,
                                   const Fingerprint& fp) {
    char buf[600];
    std::snprintf(buf, sizeof buf,
                  "%s %lld %016llx pop=%zu food=%zu pred=%zu births=%lld deaths=%lld reseeds=%lld"
                  " | cfg=%016llx ctr=%016llx fish=%016llx food=%016llx pred=%016llx"
                  " sig=%016llx cur=%016llx geo=%016llx rng=%016llx",
                  tag, step, (unsigned long long)fp.all, w.creatures.size(), w.food.size(),
                  w.predators.size(), w.totalBirths, w.totalDeaths, w.totalReseeds,
                  (unsigned long long)fp.cfg, (unsigned long long)fp.ctr,
                  (unsigned long long)fp.fish, (unsigned long long)fp.food,
                  (unsigned long long)fp.pred, (unsigned long long)fp.sig,
                  (unsigned long long)fp.cur, (unsigned long long)fp.geo, (unsigned long long)fp.rng);
    std::string line = buf;
    if (fp.appShown) {   // the appearance section, last (outside `all`; see the top)
        std::snprintf(buf, sizeof buf, " app=%016llx", (unsigned long long)fp.app);
        line += buf;
    }
    return line;
}

// ---- raw dump: the hashed state as text, one record per line, for diffing ----
// Floats print as "%.9g/%08x" (value, bit pattern): the value to read, the bits
// to compare (%.9g round-trips a float, so equal bits <=> equal text anyway).
struct Dumper {
    std::FILE* f;
    void fl(const char* k, float v) { std::fprintf(f, " %s=%.9g/%08x", k, (double)v, (unsigned)bits(v)); }
    void db(const char* k, double v) { std::fprintf(f, " %s=%.17g/%016llx", k, v, (unsigned long long)bits64(v)); }
    void v2(const char* k, Vec2 v) {
        std::fprintf(f, " %s=(%.9g/%08x,%.9g/%08x)", k, (double)v.x, (unsigned)bits(v.x),
                     (double)v.y, (unsigned)bits(v.y));
    }
    void ll(const char* k, long long v) { std::fprintf(f, " %s=%lld", k, v); }
    void ull(const char* k, unsigned long long v) { std::fprintf(f, " %s=%llu", k, v); }
    // visitSimConfig / visitOceanConfig
    void f32(const char* k, float v) { fl(k, v); }
    void i32(const char* k, int v) { ll(k, v); }
    void b(const char* k, bool v) { ll(k, v); }
};

inline void dumpState(const OceanWorld& w, std::FILE* out) {
    Dumper d{out};
    std::fprintf(out, "world format=%d", kFormatVersion);
    d.ull("frame", w.frame); d.ll("width", w.width); d.ll("height", w.height); d.fl("D", w.D);
    d.ull("fish", w.creatures.size()); d.ull("food", w.food.size()); d.ull("pred", w.predators.size());
    std::fprintf(out, "\nsimconfig");
    visitSimConfig(w.cfg, d);
    std::fprintf(out, "\noceanconfig");
    visitOceanConfig(w.ocfg, d);
    visitOceanConfigVision(w.ocfg, d);
    visitOceanConfigAppearance(w.ocfg, d);
    visitOceanConfigWalls(w.ocfg, d);
    std::fprintf(out, "\nwaves");
    for (const auto& t : field<peek::OwWaves>(w)) {
        d.db("kx", t.kx); d.db("ky", t.ky); d.db("phase", t.phase); d.db("phi", t.phi);
        d.fl("k", t.k); d.fl("qx", t.qx); d.fl("qy", t.qy); d.fl("frac", t.frac);
    }
    std::fprintf(out, "\ncounters");
    d.ll("births", w.births); d.ll("deaths", w.deaths); d.ll("totalBirths", w.totalBirths);
    d.ll("totalDeaths", w.totalDeaths); d.ll("grace", w.totalGraceBirths); d.ll("soft", w.totalSoftBirths);
    d.ll("dPred", w.totalDeathsPredation); d.ll("dStarve", w.totalDeathsStarvation); d.ll("dAge", w.totalDeathsAge);
    d.ll("pBirths", w.totalPredatorBirths); d.ll("pStarve", w.totalPredatorDeathsStarvation);
    d.ll("pAge", w.totalPredatorDeathsAge); d.ll("pReseeds", w.totalPredatorReseeds);
    d.ll("reseeds", w.totalReseeds); d.ull("nextId", w.nextId_);
    d.ll("deathsLogged", w.totalDeathsLogged_); d.ll("clusterStride", w.clusterStride_);
    d.ll("birthsLogged", w.totalBirthsLogged_); d.ll("reproStride", w.reproStride_);
    d.ull("reproWindow", w.reproWindow_.size()); d.ull("reproWindowNext", w.reproWindowNext_);
    d.ull("deathLog", w.deathLog.size()); d.ull("birthLog", w.birthLog.size());
    d.ll("foodEaten", w.totalFoodEaten); d.ll("foodExpired", w.totalFoodExpired);   // statistics (not hashed)
    d.ll("nonFiniteRemoved", w.totalNonFiniteRemoved);
    std::fprintf(out, "\ngeometry");
    {
        const SpatialGrid& g = field<peek::OwCreatureGrid>(w);
        d.ll("gridW", field<peek::SgWidth>(g)); d.ll("gridH", field<peek::SgHeight>(g));
        d.ll("cols", field<peek::SgCols>(g)); d.ll("rows", field<peek::SgRows>(g));
        d.fl("invCell", field<peek::SgInvCell>(g));
        const OceanFoodGrid& fg = field<peek::OwFoodGrid>(w);
        d.ll("gridW", field<peek::FgWidth>(fg)); d.ll("gridH", field<peek::FgHeight>(fg));
        d.ll("cols", field<peek::FgCols>(fg)); d.ll("rows", field<peek::FgRows>(fg));
        d.fl("invCell", field<peek::FgInvCell>(fg));
    }
    d.ll("sigW", field<peek::SigW>(w.signals)); d.ll("sigH", field<peek::SigH>(w.signals));
    d.ll("sigCell", w.signals.cellSize()); d.ll("sigCols", w.signals.cols()); d.ll("sigRows", w.signals.rows());
    d.ll("sigWrapCols", field<peek::SigWrapCols>(w.signals)); d.ll("sigWrapRows", field<peek::SigWrapRows>(w.signals));
    d.ll("sigToroidal", field<peek::SigToroidal>(w.signals));
    for (const Vec2& p : field<peek::OwPatches>(w)) d.v2("patch", p);
    for (float z : field<peek::OwPatchDepth>(w)) d.fl("patchDepth", z);
    std::fprintf(out, "\n");
    for (std::size_t i = 0; i < w.creatures.size(); ++i) {
        const Fish& c = w.creatures[i];
        std::fprintf(out, "fish %zu", i);
        d.ll("alive", c.alive); d.ull("id", c.id); d.ull("lineage", c.lineageId); d.ull("gen", c.generation);
        d.v2("pos", c.pos); d.fl("depth", c.depth); d.fl("vz", c.vz); d.fl("bodyBuoy", c.bodyBuoy);
        d.v2("vel", c.vel); d.v2("lastMoveDir", c.lastMoveDir);
        d.fl("speed", c.speed); d.fl("age", c.age); d.fl("food", c.foodReserves);
        d.fl("reproTimer", c.reproTimer); d.fl("interactTimer", c.interactTimer);
        d.fl("resp", c.responsiveness); d.fl("oscPeriod", c.oscPeriod); d.fl("oscPhase", c.oscPhase);
        d.fl("bodySize", c.bodySize); d.fl("bodyElong", c.bodyElong);
        std::fprintf(out, " color=%02x%02x%02x%02x\n  body", c.color.r, c.color.g, c.color.b, c.color.a);
        for (int b = 0; b < Fish::BODY_LEN; ++b) d.v2("", c.body[b]);
        std::fprintf(out, "\n  genome %zu:", c.genome.size());
        for (const Gene& g : c.genome)
            std::fprintf(out, " %u%02x%u%02x:%04x", (unsigned)g.sourceType, (unsigned)g.sourceNum,
                         (unsigned)g.sinkType, (unsigned)g.sinkNum, (unsigned)(std::uint16_t)g.weight);
        std::fprintf(out, "\n  neurons");
        for (const auto& n : c.nnet.neurons) std::fprintf(out, " %08x%s", (unsigned)bits(n.output), n.driven ? "d" : "");
        std::fprintf(out, "\n  flat");
        for (const auto& fc : c.nnet.flat) std::fprintf(out, " %04x:%04x", (unsigned)fc.srcSink, (unsigned)(std::uint16_t)fc.weight);
        std::fprintf(out, "\n  sensors");
        for (int s = 0; s < NUM_SENSES; ++s) std::fprintf(out, " %08x", (unsigned)bits(c.lastSensors[s]));
        std::fprintf(out, "\n  actions");
        for (int a = 0; a < NUM_ACTIONS; ++a) std::fprintf(out, " %08x", (unsigned)bits(c.lastActions[a]));
        std::fprintf(out, "\n");
    }
    for (std::size_t i = 0; i < w.food.size(); ++i) {
        const OceanFood& f = w.food[i];
        std::fprintf(out, "food %zu", i);
        d.v2("pos", f.pos); d.fl("depth", f.depth); d.ll("alive", f.alive); d.fl("size", f.size);
        d.fl("age", f.age);
#ifdef EVO_OCEAN_EYE
        d.fl("eyeCon", f.eyeCon);
#endif
        std::fprintf(out, "\n");
    }
    for (std::size_t i = 0; i < w.predators.size(); ++i) {
        const OceanPredator& p = w.predators[i];
        std::fprintf(out, "pred %zu", i);
        d.v2("pos", p.pos); d.v2("vel", p.vel); d.fl("depth", p.depth); d.fl("pitch", p.pitch);
        d.fl("digest", p.digestTimer); d.fl("energy", p.energy); d.fl("age", p.age); d.ll("alive", p.alive);
        d.fl("speedF", p.speedFactor); d.fl("buddingF", p.buddingFactor); d.ull("gen", p.generation);
        std::fprintf(out, "\n");
    }
    {
        const auto& g = w.signals.data();
        std::fprintf(out, "signals %zu", g.size());
        for (std::size_t i = 0; i < g.size(); ++i) {
            if (i % 64 == 0) std::fprintf(out, "\n ");
            std::fprintf(out, "%02x", g[i]);
        }
        std::fprintf(out, "\n");
    }
    {
        const CurrentField& cf = field<peek::OwCurrent>(w);
        std::fprintf(out, "current active=%d mode=%d", (int)w.currentActive(), (int)field<peek::CfMode>(cf));
        d.fl("strength", field<peek::CfStrength>(cf)); d.fl("core", field<peek::CfCore>(cf));
        d.ll("w", field<peek::CfW>(cf)); d.ll("h", field<peek::CfH>(cf));
        d.fl("gyreEps", field<peek::CfGyreEps>(cf)); d.fl("gyreOmega", field<peek::CfGyreOmega>(cf));
        d.fl("gyreA", field<peek::CfGyreA>(cf)); d.fl("gyreT", field<peek::CfGyreT>(cf));
        std::fprintf(out, "\n  vortices");
        for (float v : cf.vortexState()) d.fl("", v);
        std::fprintf(out, "\n  centers");
        for (const Vec2& c : field<peek::CfCenters>(cf)) d.v2("", c);
        std::fprintf(out, "\n  lattice");
        if (w.currentActive()) forCurrentLattice(w, [&](Vec2 p) { d.v2("", w.currentAt(p)); });
        std::fprintf(out, "\n");
    }
    std::fprintf(out, "rng %s\n", rng.state().c_str());
    {   // the appearance genome (its own section, `app`)
        const appearance::Stats& st = w.appearanceStats();
        std::fprintf(out, "appearance flags=%d broken=%d key=%016llx records=%zu founders=%llu offspring=%llu",
                     w.appearanceInitFlags(), (int)w.appearanceBroken(), (unsigned long long)w.appearanceKey(),
                     w.appearanceRecords().size(), (unsigned long long)st.founders, (unsigned long long)st.offspring);
        std::fprintf(out, " pattern=%llu/%llu/%llu/%llu morph=%llu/%llu/%llu/%llu\n",
                     (unsigned long long)st.pattern[0], (unsigned long long)st.pattern[1], (unsigned long long)st.pattern[2],
                     (unsigned long long)st.pattern[3], (unsigned long long)st.morph[0], (unsigned long long)st.morph[1],
                     (unsigned long long)st.morph[2], (unsigned long long)st.morph[3]);
        const auto& recs = w.appearanceRecords();
        for (std::size_t i = 0; i < recs.size(); ++i) {
            std::fprintf(out, "app %zu owner=%llu", i, (unsigned long long)recs[i].ownerId);
            for (float v : recs[i].genome.g) std::fprintf(out, " %08x", (unsigned)bits(v));
            std::fprintf(out, "\n");
        }
    }
}

// ---- the world as the page builds it (wasm/ocean_wasm.cpp, oc_init) --------
// Mirrors oc_init's config path: applyOceanDefaults, then the cfg JSON
// (SimConfig + OceanConfig keys), then clampConfig (a copy of the shim's),
// then rng.seed and init. Only oceanConfigError, oceanSimConfigError and
// oceanWorldSizeError (the Ocean's ranges, src/ocean/ocean_config.hpp) are
// checked here; the shim's
// full refusal list stays the shim's: wasm/ocean_parity.sh runs every case
// through the real oc_init / oc_set_param first (ocean_tests --accepts), and
// tests/ocean_tests.cpp checks that this path and the shim's give the same
// fingerprints.
inline void clampConfigLikeShim(SimConfig& c) {
    // The shim's own clamps, shared (no min/max swaps: the shim refuses a
    // reversed pair instead).
    clampOceanSimConfig(c);
}

// Returns false with `err` set on a malformed JSON or an invalid Ocean config.
inline bool buildConfigs(const char* cfgJson, float depth, SimConfig& sc, OceanConfig& oc,
                         std::string& err) {
    sc = SimConfig{};
    applyOceanDefaults(sc);
    oc = OceanConfig{};
    if (!readOceanJson(cfgJson, sc, oc, err)) return false;
    clampConfigLikeShim(sc);
    oc.depth = depth;
    err = oceanConfigError(oc);
    if (!err.empty()) { err = "invalid ocean config: " + err; return false; }
    err = oceanSimConfigError(sc);
    if (!err.empty()) { err = "invalid config for the Ocean: " + err; return false; }
    err = oceanTopologyError(sc, oc);
    if (!err.empty()) { err = "invalid config for the Ocean: " + err; return false; }
    return true;
}

inline bool initWorld(OceanWorld& w, unsigned seed, int width, int height, float depth, int pop,
                      const char* cfgJson, std::string& err) {
    SimConfig sc;
    OceanConfig oc;
    if (!buildConfigs(cfgJson, depth, sc, oc, err)) return false;
    err = oceanWorldSizeError(sc, width, height, pop);
    if (!err.empty()) { err = "bad world dimensions or population: " + err; return false; }
    rng.seed(seed);
    w.cfg = sc;
    w.ocfg = oc;
    w.init(width, height, depth, pop);
    return true;
}

}  // namespace ofp

// ocean_tests.cpp — unit checks for the Ocean world (src/ocean/), the
// companion of the native-vs-wasm harness (wasm/ocean_parity.sh, which builds
// and runs this file natively and under node).
//
//   g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tests/ocean_tests.cpp -o ocean_tests
//
// What is checked (each block prints one ok / FAIL line):
//   bounds        depth in [0, D] and |vz| <= pitchMax for every fish every
//                 step (food and predator depth too), default and extreme configs
//   buoyancy      an idle fish (no wiring) is pulled monotonically to bodyBuoy·D;
//                 with kBuoy = 0 it holds its depth exactly
//   steer_z       STEER_Z moves a fish down (+) / up (−); a LOC_Z -> STEER_Z wire
//                 drives it; the action's value is tanh of the wire
//   steer_frame   steerFrame 1: STEER_X turns every heading right (+) / left (−)
//                 by the same angle, STEER_Y does not turn; steerFrame 0 pulls
//                 toward world +x / +y; triangular motion ignores it; (eye build)
//                 an EYE_RIGHT / EYE_LEFT -> STEER_X wire turns toward the food
//   sensors       LOC_Z, OWN_VEL_Z, BOUNDARY_DIST_Z equal their defining
//                 expressions; NEAREST_FOOD_DZ / AVG_NEIGHBOR_DZ in range; the
//                 food direction is a unit vector; every sensor finite
//   sensor_signs  hand-placed fixtures: the SIGN and value of LOC_Z,
//                 OWN_VEL_Z, NEAREST_FOOD_DZ (+ = food deeper), AVG_NEIGHBOR_DZ
//                 (+ = neighbours deeper), BOUNDARY_DIST_Z; a NEAREST_FOOD_DZ ->
//                 STEER_Z (+) wire takes a fish toward its food in depth
//   current_sens  3-D flow on: CURRENT_FWD / LR are + along / to the right of
//                 the heading, 0 at the surface (deep current), f(d)-weighted,
//                 and read flowAt at the fish (waves too)
//   walls         the depth wall bands push away from surface / floor by
//                 exactly (1 − z/wb)·3·dt, capped at D/2 in a shallow sea
//   capture       captureActivations changes no dynamics
//   eye           (eye build) a hand-built scene's 18 eye inputs bit for bit;
//                 off = 0; in range; no side effects (eyeCode 0, 7 and 31)
//   eye_only      (eye build) eyeOnly: the 23 labeled inputs 0, every other
//                 input bit-identical to the labeled run's; blind likewise;
//                 also with eyeCode 7, 8 (cloaked fish: no neighbour query in
//                 eye-only mode) and 20 (cloaked food + summed sectors)
//   eye_code      (eye build) eyeCode: a scene with several objects per sector,
//                 the 18 inputs bit for bit for every code 0..31 — the
//                 encodings x the cloaks (8 the eye ignores fish, 16 food) —
//                 and seven codes eye-only; non-eye (labeled) inputs unchanged
//                 by any code; the cloaks by name (a cloaked kind neither shows
//                 nor hides: the food behind a nearer fish, the predator behind
//                 the food; 24 = predators only); faded contrast 0 at R;
//                 ranges in populated worlds; 0..31 valid, live via
//                 oc_set_param (plain build: eyeCode must stay 0)
//   sense_edges   the food / neighbour scans' edges, bit for bit, and sense_ref:
//   sense_ref     randomized scenes against their definition (both in
//                 tests/ocean_sense_tests.hpp, which lists what they pin)
//   food_grid     OceanFoodGrid == SpatialGrid: the same lists and visits, and
//                 each entry's payload is its item's
//   sense_mask    the sensors a net reads (ocean::sensesRead: the dead-sensor
//                 skip computes only those while capture is off)
//   sense_dce     every fish reading one sensor, each sensor, each topology /
//                 eye mode: capture off == capture on, bit for bit
//   capture_toggle  capture on -> off -> on: the same run; captured arrays
//                 untouched while off
//   label_mask    the skip under own-frame labels (labelFrame 1, the A1 arm):
//                 capture off == on, single-sensor and 2000-step runs
//                 (tests/ocean_exp_tests.hpp; tests/label_mask_fault.sh plants
//                 wrongly-masked components, each must fail it)
//   food_scan    the food scans' item lists == their scalar definition, bit
//                 for bit (the four in tests/ocean_speed_tests.hpp)
//   food_life     foodLife: an item goes on the step its age reaches foodLife;
//                 off, none do; the first stock's ages spread; draws unchanged;
//                 the spawn cap counts live items (what expires frees its place
//                 in the same step: targetFood 1, 2 a step, foodLife dt -> 2);
//                 the range ends at 3600 s (kOceanMaxFoodLife), where an item
//                 at foodLife - 0.0625 still goes within four steps
//   nonfinite_rm  OceanWorld::totalNonFiniteRemoved counts the non-finite
//                 floats of what the end-of-step erase removes: a fish at
//                 moveCost 1e38 (reserves -inf, starved), a predator at
//                 predatorMoveCost 1e38, food of size inf (validation
//                 bypassed); finite deaths count 0; not hashed; init resets it
//   reproducible  same seed twice -> identical fingerprints; another seed and a
//                 1-ulp change in any section change the hash — incl. a
//                 vortex frequency, a food-patch depth, a grid's cell size, the
//                 signal grid's wrap flag, a wave phase (each its own section);
//                 a food age kept with foodLife off, steerFrame / foodLife in
//                 the config; (eye build) a food item's eyeCon, which
//                 countNonFinite checks too
//   radii         every radius must be finite, >= 0 and have a finite float
//                 square (OceanWorld::radiusError refuses 1e20, accepts the
//                 largest float below 2^64); oc_init refuses 1e20 and every
//                 radius above the Ocean's 1e6 cap, accepts 1e6; (eye build)
//                 at perceptionRadius 1e6 every input is finite
//   reset         oc_init / oc_reset (the shim, wasm/ocean_wasm.cpp) replay
//                 exactly, live oc_set_param changes are dropped, and the shim's
//                 world == the harness's ofp::initWorld world (the harness's
//                 prints, rng included, taken BEFORE the shim runs: an extra
//                 draw in oc_step fails); a fresh world re-inited replays, a
//                 reused one keeps exactly frame / ids / totals (asserted)
//   probe         tools/ocean_probe.cpp's world (probeInitWorld) == the shim's
//                 (oc_init), every section, for perceptionRadius 0 / 0.25 /
//                 the default and with --e1: a radius below 1 stored as 1 (the
//                 grids' cell size; 0 used to divide by zero in SpatialGrid),
//                 both neighbour grids' geometry finite
//   pred_econ     fixtures: burn = metabolism + predatorMoveCost·speed² (or
//                 moveCost when < 0), a fixed predatorMeal vs the prey's
//                 reserves, death at predatorMaxAge — bit for bit
//   pair_gates    fixtures: the maxPopulation cap, the hard distance gate
//                 (reproSoftWidth 0: refuses far pairs, no draw) and the grace
//                 bypass (young founders only), with their counters
//   fast_tanh     cfg.fastTanh reaches the Ocean net: actions == fastTanhApprox
//   child         child depth == the parents' midpoint, bodyBuoy within
//                 ±buoyMutation of their mean (clamped to [0, 1]), on and
//                 across the toroidal seam
//   draws_*       the rng draw count per step does not depend on values: fish
//                 motion (RANDOM_SENSOR + MOVE_RANDOM's three draws, across
//                 depth / vz / bodyBuoy / every vertical knob), a birth (across
//                 buoyMutation incl. 0, bodyBuoy, depth), predators (wander,
//                 bud, floor refill, across depth / pitch / D), food spawn
//                 (across foodDepthMode / spread)
// E1 physics (the E1 design §6):
//   divergence    central-difference div of each wave train, their sum, the
//                 depth-weighted current and the whole flow: normalised
//                 residual < 1e-3, shrinking with h (bulk and boundary bands);
//                 exactly zero normal flow at surface and floor; flowAt (one
//                 shared depth taper per call) == the current + each train's
//                 own waveTrainAt, bit for bit
//   flow_tables   the E1 flow cache (src/ocean/ocean_flow.hpp) vs the exact
//                 formulas: the eddy current's radial table within 9e-6 ·
//                 strength per vortex (one vortex, the preset, 8 strong ones;
//                 before the first advance too, over the world and beyond it);
//                 each wave train within max(2e-6·waveSpeed, 1e-6·its peak
//                 speed) per component (five worlds: the preset, a narrow
//                 band, D 10 / band 1 / speed 100, 100 x 100, D 2000; depths
//                 at and around the taper joins, surface and floor; phases set
//                 directly and from the clock; positions beyond the edges);
//                 exactly 0 at surface and floor; a divergence probe per train
//                 no worse than the exact field's; live waveSpeed / waveBand
//                 changes rebuild (direct assignment, as the driver's --set),
//                 waveGravity does not; off flowE1() the exact path bit for bit
//   flow_lanes    the wave tables' 4-lane vector evaluator (SSE2 / SIMD128) ==
//                 a scalar lane-by-lane evaluation of the same cache, bit for
//                 bit, per train and summed, at cells, joins, ends, beyond the
//                 world (fallbacks) and over the depth-cell cap
//   e1_buoyancy   with the non-flow E1 knobs on and wallBand 0, an idle fish
//                 still settles monotonically at bodyBuoy·D
//   drift         sizeDrift: one step moves fish of size .5 / 1 / 2 by exactly
//                 1 / 1 / .5 of dt·flow at their spot; over 200 steps the big
//                 one has drifted about half as far; off: all alike
//   costs         depthCostScaled: neutral / surface / deep fixtures equal
//                 dt·M·(cHold·H + cPress·P) bit for bit, ∝ bodySize, timers and
//                 gene / move costs untouched; the preview formula unchanged
//   fight         the scaled overload: (1, 1) == the Classic fight bit for bit
//                 (rng too), known draws, ties go to c2, L² decides most fights
//   mouth         mouthGate: food below / equal to kMouth·L is eaten, above
//                 is not, and is not smelled either
//   e1_neutral    knobs that must not change a run (light, wave shape with no
//                 waves, scaled costs at 0, mouth / fight / drift at size 1)
//                 leave every dynamic hash identical, step by step
//   e1_bounds     E1 worlds keep depth in [0, D], every float finite
//   draws_e1      no E1 feature draws: per-step draws == N + 3·MOVE_RANDOM +
//                 2·predators with everything on; a birth draws as without
//   light         lightAt(0) == L0, falls as L0·exp(−kWater·d); at kWater 1
//                 still > 0 and within 6e-7 relative down to depth 87 (1 +
//                 expm1f(−x) was 0 from x = 17.3); the exports
//   exp           oceanmath::expf: ±0 -> 1, NaN / ±inf, beyond the float
//                 range; within 4 ulp of e^x and monotone on [-87, 88]
//   ranges        every Ocean knob, and the SimConfig keys the Ocean bounds
//                 (oceanSimConfigError: the current, foodPatchRadius, the
//                 energies at ±1e6, foodLife at 3600): its
//                 range's ends accepted, just outside, inf and the -1e37 hole
//                 refused (oc_init, oc_set_param); a run at each end stays
//                 finite; bool / mode keys strict
//   e1_hash       a wave-phase or E1-knob ulp changes only its own section
//   lazy_waves    the wave modes are prepared only once the waves are on
//                 (never by a waves-off step or flow reader, a deep current
//                 alone included; an unprepared train gives zero flow); off
//                 at init and switched on directly before the first step ==
//                 on at init, every section after 200 steps (geo before: the
//                 first flow read prepares the same modes); on live at step
//                 100 (the step prepares them), off again keeps the modes and
//                 the stopped clock; a reused world re-initialised with the
//                 waves off is unprepared again
//   preset        kE1PresetJson is accepted and is what it says
//   wrap          OceanWorld::wrapCoord (constant time) == the loops it
//                 replaced, bit for bit, at every edge of [-span, 2·span) and
//                 [0, span) and on sweeps (multi-pass ones too, whole-number
//                 spans); far values (to ±3.4e38) == the exact remainder,
//                 worked out from the float's bits; inf / NaN end; the config
//                 that hung (currentStrength 1e20, validation bypassed) steps
//                 with every position in the world; wrapPreview (food /
//                 predators, flow off) == the old single pass on [-span,
//                 2·span), wrapCoord beyond; a flow of > 1 span per step with
//                 the 3-D flow off keeps everything in a 100 x 100 world (its
//                 fingerprint printed: compared native vs wasm)
//   shim_ints     int keys: every readConfig int key is in kSimConfigIntKeys
//                 (by member); whole numbers to INT_MIN / INT_MAX read exactly,
//                 a fraction, 2^31, ±1e300, 1e999 refused before the cast (also
//                 a repeated key); oc_set_param writes an int exactly
//                 (2147483647 used to become 2.14748365e+09); foodSpawn*,
//                 targetFood, the speeds and the radii refused beyond their
//                 ranges (init and live, world unchanged); at maxSpeed /
//                 predatorSpeed 2000 everything stays in a 100 x 100 world;
//                 a non-finite maxTurnRate / cooldown / predator-economy
//                 float, minPopulation / predatorCount / foodPatches / founders
//                 / width / height over 1e5, or neighbour grids over 2^24
//                 cells refused (init and live, the world kept); the ceilings
//                 themselves accepted. (Every shim call is made before
//                 oc_last_error() is read: as arguments of one expect() their
//                 order was unspecified.)
//   motion_bounds the live-code audit's finding 4, stepped: maxSpeed 0.01 (the
//                 floor) keeps the first captured OWN_SPEED finite (80 / 0.01;
//                 1e-38 refused), and triangular motion at |maxTurnRate| 1e4
//                 with bodyElong 0.5 stays finite, steering or not (3e38
//                 refused)
//   shim_bools    bool keys (kSimConfigBoolKeys, kOceanBoolKeys, by member): a
//                 SimConfig switch is true / false ({"toroidal":1} used to be
//                 ignored, the world kept walls: now refused), an Ocean one
//                 true / false / 0 / 1; anything else refused with the key
//                 named, every occurrence (a repeated key too), via oc_init too
//
//   preflight     `--accepts` asks a case's --set changes by step, as the
//                 driver applies them (stable within a step; past STEPS not
//                 asked): minSpeed=200@10 + maxSpeed=300@5 over 20 steps is
//                 accepted in both argument orders
//
// `ocean_tests --accepts SEED STEPS [driver args]` instead asks the shim
// whether it would accept one ocean_parity_driver case (see acceptsCase).
//
// Build with -DOCEAN_TESTS_NO_SHIM to leave out the shim-based checks.
#include <algorithm>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <limits>
#include <set>
#include <utility>
#include <string>
#include <unordered_map>
#include <vector>
#include "../tools/ocean_fingerprint.hpp"
#ifndef OCEAN_TESTS_NO_SHIM
#include "../wasm/ocean_wasm.cpp"
#endif
#define OCEAN_PROBE_NO_MAIN
#include "../tools/ocean_probe.cpp"   // probeInitWorld (the "probe" check)
#ifdef EVO_OCEAN_EYE
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"   // the tool's own entry points
#define OCEAN_EYE_EXP_NO_MAIN
#include "../tools/ocean_eye_exp.cpp"   // its behavioural probe and wiring classifier (eye_exp)
#pragma GCC diagnostic pop
#endif

namespace ot {

int g_passed = 0, g_failed = 0;

struct Test {
    const char* name;
    long checks = 0, fails = 0;
    std::string first;
    std::vector<std::string> notes;
    explicit Test(const char* n) : name(n) {}
    __attribute__((format(printf, 3, 4)))
    bool expect(bool ok, const char* fmt, ...) {
        ++checks;
        if (ok) return true;
        if (fails++ == 0) {
            char buf[600];
            va_list ap;
            va_start(ap, fmt);
            std::vsnprintf(buf, sizeof buf, fmt, ap);
            va_end(ap);
            first = buf;
        }
        return false;
    }
    __attribute__((format(printf, 2, 3)))
    void note(const char* fmt, ...) {
        char buf[600];
        va_list ap;
        va_start(ap, fmt);
        std::vsnprintf(buf, sizeof buf, fmt, ap);
        va_end(ap);
        notes.push_back(buf);
    }
    ~Test() {
        if (fails) { ++g_failed; std::printf("FAIL %-14s %ld of %ld checks failed; first: %s\n", name, fails, checks, first.c_str()); }
        else       { ++g_passed; std::printf("ok   %-14s %ld checks\n", name, checks); }
        for (const std::string& n : notes) std::printf("     %-14s %s\n", "", n.c_str());
        std::fflush(stdout);
    }
};

bool finite(float v) { return std::isfinite(v); }

// ---- small worlds built by hand --------------------------------------------

// A gene into an ACTION: from a sensor (srcSensor) or from hidden neuron `src`.
// An undriven hidden neuron outputs a fixed 0.5, so neuron 0 -> action with
// weight w gives the action tanh(0.5 · w / 8192).
Gene mkGene(bool srcSensor, int src, int action, int weight) {
    Gene g;
    g.sourceType = srcSensor ? SOURCE_SENSOR : SOURCE_NEURON;
    g.sourceNum = (uint16_t)src;
    g.sinkType = SINK_ACTION;
    g.sinkNum = (uint16_t)action;
    g.weight = (int16_t)weight;
    return g;
}
constexpr int kStrong = 32767;   // neuron 0 (0.5) x 4.0 = 2.0 -> tanh 0.964

// No food, no spawn, no reseed floor, no predators, no current, no hunger, no
// old age: only what a test adds moves the rng or the state.
void initQuiet(OceanWorld& w, unsigned seed, float D, const OceanConfig& oc, bool capture = false,
               bool toroidal = false, float currentStrength = 0.0f) {
    SimConfig sc;
    applyOceanDefaults(sc);
    if (currentStrength > 0.0f) sc.currentStrength = currentStrength;   // eddies (draws at init only)
    sc.minPopulation = 0;
    sc.targetFood = 0;
    sc.foodSpawnBase = 0.0f;
    sc.foodSpawnAmp = 0.0f;
    sc.metabolicRate = 0.0f;
    sc.maxAge = 1e9f;
    sc.predatorCount = 0;
    sc.captureActivations = capture;
    sc.toroidal = toroidal;
    rng.seed(seed);
    w.cfg = sc;
    w.ocfg = oc;
    w.ocfg.depth = D;
    w.init(1920, 1080, D, 0);
}

// Appends a founder (Fish::init draws its heading and oscillator phase) and
// returns its index.
int addFish(OceanWorld& w, Vec2 pos, float z, std::vector<Gene> genome, float bodyBuoy) {
    Fish f;
    f.genome = std::move(genome);
    f.init(pos, z);
    f.bodyBuoy = bodyBuoy;
    w.creatures.push_back(std::move(f));
    w.markFounder(w.creatures.back());
    w.attachFounderAppearance();   // the appearance side array stays bound (no draws)
    return (int)w.creatures.size() - 1;
}

// ---- counting engine draws -------------------------------------------------

bool sameEngine(const RandomGen& a, const RandomGen& b) {
    RandomGen x = a, y = b;
    for (int i = 0; i < 3; ++i)
        if (x.uint() != y.uint()) return false;
    return a.state() == b.state();
}

// How many engine draws take `before` to `after` (-1 if not within maxDraws).
long drawsBetween(const RandomGen& before, const RandomGen& after, long maxDraws = 100000) {
    RandomGen p = before;
    for (long k = 0; k <= maxDraws; ++k) {
        if (sameEngine(p, after)) return k;
        p.uint();
    }
    return -1;
}

// ---- tests -----------------------------------------------------------------

void testBounds() {
    Test t("bounds");
    struct V { const char* name; unsigned seed; float D; const char* cfg; };
    const V vs[] = {
        {"default", 1, 240.0f, nullptr},
        {"steep/strong buoy/wide walls/no drag", 2, 240.0f,
         R"({"pitchMax":4,"kBuoy":25,"wallBand":100,"vDrag":0})"},
        {"tiny pitch/anti-buoy/drag 200/deep/toroidal", 3, 2000.0f,
         R"({"pitchMax":0.01,"kBuoy":-5,"vDrag":200,"wallBand":0,"buoyMutation":0.5,"toroidal":true})"},
        {"D=10/costs/patch depths", 4, 10.0f,
         R"({"pitchMax":1.5,"wallBand":5,"cHold":0.5,"cPress":0.3,"foodDepthMode":1,"foodPatches":4,"foodDepthSpread":500})"},
        {"predators+economy+currents", 5, 240.0f,
         R"({"predatorCount":6,"predatorEconomy":true,"predatorMinPopulation":2,"predatorInheritance":true,"currentStrength":80,"foodDrift":true,"foodPatches":5,"foodDepthMode":1})"},
        {"vDrag 300 (overshooting)", 6, 240.0f, R"({"vDrag":300,"pitchMax":2,"kBuoy":-20,"wallBand":30})"},
    };
    long fishSeen = 0, atSurface = 0, atFloor = 0, atPitch = 0;
    for (const V& v : vs) {
        OceanWorld w;
        std::string err;
        if (!t.expect(ofp::initWorld(w, v.seed, 1920, 1080, v.D, 300, v.cfg, err), "%s: init refused: %s", v.name, err.c_str()))
            continue;
        const float pm = w.ocfg.pitchMax;
        for (int s = 1; s <= 1200; ++s) {
            w.update(0.016f);
            for (const Fish& c : w.creatures) {
                ++fishSeen;
                atSurface += (c.depth == 0.0f);
                atFloor += (c.depth == w.D);
                atPitch += (std::abs(c.vz) == pm);
                t.expect(c.depth >= 0.0f && c.depth <= w.D, "%s step %d: fish %llu depth %.9g outside [0, %g]",
                         v.name, s, (unsigned long long)c.id, c.depth, w.D);
                t.expect(std::abs(c.vz) <= pm, "%s step %d: fish %llu |vz| %.9g > pitchMax %g",
                         v.name, s, (unsigned long long)c.id, c.vz, pm);
                t.expect(c.bodyBuoy >= 0.0f && c.bodyBuoy <= 1.0f, "%s step %d: bodyBuoy %.9g", v.name, s, c.bodyBuoy);
                t.expect(finite(c.pos.x) && finite(c.pos.y) && finite(c.speed) && finite(c.foodReserves),
                         "%s step %d: non-finite fish state", v.name, s);
            }
            for (const OceanFood& f : w.food)
                t.expect(f.depth >= 0.0f && f.depth <= w.D, "%s step %d: food depth %.9g", v.name, s, f.depth);
            for (const OceanPredator& p : w.predators)
                t.expect(p.depth >= 0.0f && p.depth <= w.D && std::abs(p.pitch) <= 0.3f,
                         "%s step %d: predator depth %.9g pitch %.9g", v.name, s, p.depth, p.pitch);
        }
    }
    t.note("%zu configs x 1200 steps, %ld fish-steps; %ld at the surface, %ld on the floor, %ld at |vz| == pitchMax",
           sizeof vs / sizeof vs[0], fishSeen, atSurface, atFloor, atPitch);
    t.expect(atSurface > 0 && atFloor > 0 && atPitch > 0, "the limits were never reached: the bounds checks did not bite");
}

void testBuoyancy() {
    Test t("buoyancy");
    OceanConfig oc;   // kBuoy 1, vDrag 2, pitchMax 0.5, wallBand 12
    OceanWorld w;
    initQuiet(w, 11, 240.0f, oc);
    struct F { int idx; float target; };
    const F fs[] = {
        {addFish(w, {300, 300}, 24.0f, {}, 0.5f), 120.0f},    // above neutral: sinks
        {addFish(w, {900, 700}, 216.0f, {}, 0.5f), 120.0f},   // below neutral: rises
        {addFish(w, {1500, 500}, 192.0f, {}, 0.2f), 48.0f},   // a long climb to 0.2·D
    };
    const int still = addFish(w, {600, 900}, 120.0f, {}, 0.5f);   // already neutral
    float off[3];
    for (int k = 0; k < 3; ++k) off[k] = w.creatures[fs[k].idx].depth - fs[k].target;
    for (int s = 1; s <= 3000; ++s) {
        w.update(0.016f);
        if (!t.expect(w.creatures.size() == 4, "step %d: %zu fish (none should die or be born)", s, w.creatures.size()))
            return;
        for (int k = 0; k < 3; ++k) {
            const float o = w.creatures[fs[k].idx].depth - fs[k].target;
            t.expect(std::abs(o) <= std::abs(off[k]), "fish %d step %d: |offset| grew %.9g -> %.9g", k, s, off[k], o);
            t.expect(o == 0.0f || (o > 0.0f) == (off[k] > 0.0f) || off[k] == 0.0f,
                     "fish %d step %d: overshot neutral (%.9g -> %.9g)", k, s, off[k], o);
            off[k] = o;
        }
        t.expect(w.creatures[still].depth == 120.0f && w.creatures[still].vz == 0.0f,
                 "step %d: a neutral idle fish moved (depth %.9g vz %.9g)", s, w.creatures[still].depth,
                 w.creatures[still].vz);
    }
    for (int k = 0; k < 3; ++k)
        t.expect(std::abs(off[k]) < 0.5f, "fish %d still %.4f from bodyBuoy·D after 3000 steps", k, off[k]);
    t.note("offsets after 3000 steps: %.4f %.4f %.4f (from -96, +96, +144)", off[0], off[1], off[2]);

    // kBuoy = 0: an idle fish holds its depth exactly.
    OceanConfig oc0;
    oc0.kBuoy = 0.0f;
    OceanWorld w0;
    initQuiet(w0, 12, 240.0f, oc0);
    const int a = addFish(w0, {500, 500}, 60.0f, {}, 0.9f);
    for (int s = 0; s < 500; ++s) w0.update(0.016f);
    t.expect(w0.creatures[a].depth == 60.0f && w0.creatures[a].vz == 0.0f,
             "kBuoy 0: idle fish moved to %.9g (vz %.9g)", w0.creatures[a].depth, w0.creatures[a].vz);
}

void testSteerZ() {
    Test t("steer_z");
    OceanConfig oc;
    oc.kBuoy = 0.0f;   // isolate the action: no buoyancy, no walls
    oc.wallBand = 0.0f;
    OceanWorld w;
    initQuiet(w, 21, 240.0f, oc, /*capture*/ true);
    const int dn = addFish(w, {300, 300}, 120.0f, {mkGene(false, 0, STEER_Z, 16384)}, 0.5f);
    const int idle = addFish(w, {900, 300}, 120.0f, {}, 0.5f);
    const int up = addFish(w, {1500, 300}, 120.0f, {mkGene(false, 0, STEER_Z, -16384)}, 0.5f);
    // A sensor-driven wire: deeper -> more negative STEER_Z -> rises.
    const int loc = addFish(w, {300, 800}, 200.0f, {mkGene(true, LOC_Z, STEER_Z, -kStrong)}, 0.5f);
    for (int s = 0; s < 60; ++s) w.update(0.016f);
    const Fish &D = w.creatures[dn], &I = w.creatures[idle], &U = w.creatures[up], &L = w.creatures[loc];
    t.expect(D.depth > 130.0f, "STEER_Z > 0 did not dive: depth %.4f", D.depth);
    t.expect(U.depth < 110.0f, "STEER_Z < 0 did not rise: depth %.4f", U.depth);
    t.expect(I.depth == 120.0f, "unwired fish moved: depth %.9g", I.depth);
    t.expect(D.vz > 0.0f && U.vz < 0.0f && std::abs(D.vz) <= oc.pitchMax && std::abs(U.vz) <= oc.pitchMax,
             "vz signs/limits: dive %.6f rise %.6f", D.vz, U.vz);
    t.expect(std::abs((D.depth - 120.0f) - (120.0f - U.depth)) < 1e-3f,
             "dive and rise not symmetric: +%.6f vs -%.6f", D.depth - 120.0f, 120.0f - U.depth);
    t.expect(D.lastActions[STEER_Z] == evomath::tanhf(1.0f) && U.lastActions[STEER_Z] == -evomath::tanhf(1.0f),
             "STEER_Z action %.9g / %.9g, expected ±tanh(1) = %.9g", D.lastActions[STEER_Z],
             U.lastActions[STEER_Z], evomath::tanhf(1.0f));
    t.expect(L.depth < 190.0f && L.lastActions[STEER_Z] < 0.0f,
             "LOC_Z -> STEER_Z (-) did not raise the fish: depth %.4f action %.6f", L.depth, L.lastActions[STEER_Z]);
    t.note("after 60 steps: dive %.2f, idle %.2f, rise %.2f, LOC_Z-wired %.2f (from 200)", D.depth, I.depth, U.depth, L.depth);
}

// OceanConfig::steerFrame: 0 = STEER_X / STEER_Y push along world x / y, 1 = along
// the fish's right axis / heading.
void testSteerFrame() {
    Test t("steer_frame");
    {
        OceanConfig oc;
        t.expect(oceanConfigValid(oc) && oc.steerFrame == 0, "default steerFrame %d (or refused)", oc.steerFrame);
        oc.steerFrame = 1;
        t.expect(oceanConfigValid(oc), "steerFrame 1 refused");
        oc.steerFrame = 2;
        t.expect(!oceanConfigValid(oc), "steerFrame 2 accepted");
        oc.steerFrame = -1;
        t.expect(!oceanConfigValid(oc), "steerFrame -1 accepted");
    }
    const float kPi = 3.14159265f;
    auto angle = [](Vec2 v) { return std::atan2(v.y, v.x); };
    auto turned = [&](Vec2 a, Vec2 b) {   // signed heading change a -> b, + = toward a's right
        float d = angle(b) - angle(a);
        if (d > kPi) d -= 2.0f * kPi;
        if (d < -kPi) d += 2.0f * kPi;
        return d;
    };
    // One world per frame: fish at 8 headings wired neuron 0 -> STEER_X (+), at 8
    // wired -> STEER_X (−), at 8 wired -> STEER_Y (+), plus an unwired one.
    auto build = [&](OceanWorld& w, int frame) {
        OceanConfig oc;
        oc.kBuoy = 0.0f;
        oc.wallBand = 0.0f;
        oc.steerFrame = frame;
        initQuiet(w, 23, 240.0f, oc, /*capture*/ true);
        for (int set = 0; set < 3; ++set)
            for (int h = 0; h < 8; ++h) {
                const Gene g = (set == 2) ? mkGene(false, 0, STEER_Y, kStrong)
                                          : mkGene(false, 0, STEER_X, set == 0 ? kStrong : -kStrong);
                const int k = addFish(w, {150.0f + 200.0f * h, 200.0f + 300.0f * set}, 120.0f, {g}, 0.5f);
                const float a = 2.0f * kPi * (float)h / 8.0f + 0.2f;
                Fish& f = w.creatures[k];
                f.vel = {std::cos(a), std::sin(a)};
                f.lastMoveDir = f.vel;
                f.responsiveness = 1.0f;
            }
        addFish(w, {960.0f, 1000.0f}, 120.0f, {}, 0.5f);
    };
    OceanWorld own, wld;
    build(own, 1);
    build(wld, 0);
    const int N = (int)own.creatures.size();
    std::vector<Vec2> h0(N), w0(N);
    for (int i = 0; i < N; ++i) { h0[i] = own.creatures[i].vel; w0[i] = wld.creatures[i].vel; }
    own.update(0.016f);
    wld.update(0.016f);
    // Own frame: STEER_X (+) turns every heading right by the same angle, (−) left by
    // the same angle; STEER_Y (along the heading) does not turn it.
    const float ref = turned(h0[0], own.creatures[0].vel);
    t.expect(ref > 0.03f && ref < 0.06f, "own frame: STEER_X (+) turned %.6f rad in one step (expected ~0.046)", ref);
    for (int h = 0; h < 8; ++h) {
        const float r = turned(h0[h], own.creatures[h].vel);
        const float l = turned(h0[8 + h], own.creatures[8 + h].vel);
        const float y = turned(h0[16 + h], own.creatures[16 + h].vel);
        t.expect(std::abs(r - ref) < 1e-5f, "own frame, heading %d: STEER_X (+) turned %.7f, heading 0 turned %.7f", h, r, ref);
        t.expect(std::abs(l + ref) < 1e-5f, "own frame, heading %d: STEER_X (-) turned %.7f, expected %.7f", h, l, -ref);
        t.expect(std::abs(y) < 1e-6f, "own frame, heading %d: STEER_Y (ahead) turned the fish %.9f", h, y);
        // The eye's and PREDATOR_LR's right is (-fwd.y, fwd.x): the new heading leans that way.
        const Vec2 rht = {-h0[h].y, h0[h].x};
        const Vec2 v = own.creatures[h].vel;
        t.expect(v.x * rht.x + v.y * rht.y > 0.0f, "own frame, heading %d: STEER_X (+) did not lean toward (-fwd.y, fwd.x)", h);
    }
    t.expect(own.creatures[N - 1].vel.x == h0[N - 1].x && own.creatures[N - 1].vel.y == h0[N - 1].y,
             "own frame: the unwired fish turned");
    // World frame (Classic): STEER_X (+) pulls every heading toward +x, STEER_Y (+)
    // toward +y; the angle depends on the heading.
    float wmin = 1e9f, wmax = -1e9f;
    for (int h = 0; h < 8; ++h) {
        const Vec2 a = w0[h], b = wld.creatures[h].vel, c = w0[16 + h], d = wld.creatures[16 + h].vel;
        t.expect(b.x > a.x, "world frame, heading %d: STEER_X (+) did not pull toward +x (%.6f -> %.6f)", h, a.x, b.x);
        t.expect(d.y > c.y, "world frame, heading %d: STEER_Y (+) did not pull toward +y (%.6f -> %.6f)", h, c.y, d.y);
        const float r = std::abs(turned(a, b));
        wmin = std::min(wmin, r); wmax = std::max(wmax, r);
    }
    t.expect(wmax - wmin > 0.01f, "world frame: STEER_X turned every heading alike (%.6f..%.6f)", wmin, wmax);
    // A STEER_X (+) fish in its own frame circles: after 200 steps it has turned
    // right every step (no reversal).
    {
        bool allRight = true;
        for (int s = 0; s < 200; ++s) {
            const Vec2 a = own.creatures[3].vel;
            own.update(0.016f);
            allRight &= turned(a, own.creatures[3].vel) > 0.0f;
        }
        t.expect(allRight, "own frame: a STEER_X (+) fish did not turn right on every step");
    }
    t.note("one step: own frame %.5f rad for every heading (STEER_Y 0); world frame %.5f..%.5f by heading", ref, wmin, wmax);

    // Triangular motion already turns by STEER_X in the fish's frame and ignores
    // steerFrame: the same fish, the same state, step for step.
    {
        OceanWorld a, b;
        for (OceanWorld* w : {&a, &b}) {
            OceanConfig oc;
            oc.steerFrame = (w == &b) ? 1 : 0;
            initQuiet(*w, 24, 240.0f, oc);
            w->cfg.triangularMotion = true;
            for (int i = 0; i < 12; ++i)
                addFish(*w, {100.0f + 140.0f * i, 300.0f + 40.0f * i}, 20.0f * i,
                        {mkGene(false, 0, STEER_X, (i % 2) ? kStrong : -kStrong),
                         mkGene(false, 0, MOVE_FORWARD, (i % 3) * 8000 - 8000)}, 0.5f);
        }
        // Each world steps on its own copy of the rng (initQuiet seeded both alike),
        // so a draw difference shows as different engines.
        RandomGen ra = rng, rb = rng;
        bool same = true, sameDraws = true;
        for (int s = 0; s < 300 && same && sameDraws; ++s) {
            rng = ra; a.update(0.016f); ra = rng;
            rng = rb; b.update(0.016f); rb = rng;
            const ofp::Fingerprint fa = ofp::fingerprint(a), fb = ofp::fingerprint(b);
            same = fa.fish == fb.fish && fa.ctr == fb.ctr;
            sameDraws = sameEngine(ra, rb);
        }
        t.expect(same, "triangular motion: steerFrame 1 changed the fish");
        t.expect(sameDraws, "triangular motion: steerFrame 1 changed the draws");
    }
#ifdef EVO_OCEAN_EYE
    // The compound eye and the own-frame push agree on "right": an EYE_RIGHT_PROX ->
    // STEER_X (+) wire turns a fish toward food on its right, and EYE_LEFT_PROX ->
    // STEER_X (−) toward food on its left; with steerFrame 0 the same wires do not.
    {
        int toward[2][2] = {};   // [frame][side]
        for (int frame = 0; frame < 2; ++frame)
            for (int side = 0; side < 2; ++side)
                for (int h = 0; h < 8; ++h) {
                    OceanConfig oc;
                    oc.kBuoy = 0.0f;
                    oc.wallBand = 0.0f;
                    oc.eye = 1;
                    oc.steerFrame = frame;
                    OceanWorld w;
                    initQuiet(w, 25, 240.0f, oc);
                    const Gene g = side ? mkGene(true, EYE_RIGHT_PROX, STEER_X, kStrong)
                                        : mkGene(true, EYE_LEFT_PROX, STEER_X, -kStrong);
                    const int k = addFish(w, {960.0f, 540.0f}, 120.0f, {g}, 0.5f);
                    const float a = 2.0f * kPi * (float)h / 8.0f + 0.2f;
                    Fish& f = w.creatures[k];
                    f.vel = {std::cos(a), std::sin(a)};
                    f.lastMoveDir = f.vel;
                    f.responsiveness = 1.0f;
                    const Vec2 rht = {-f.vel.y, f.vel.x};
                    const float sgn = side ? 1.0f : -1.0f;
                    OceanFood fd;
                    fd.pos = {960.0f + sgn * 60.0f * rht.x, 540.0f + sgn * 60.0f * rht.y};
                    fd.depth = 120.0f;
                    fd.eyeCon = ocean::eyeContrast(ocean::kEyeFoodBright, fd.depth);
                    w.food.push_back(fd);
                    const Vec2 v0 = f.vel;
                    for (int s = 0; s < 3; ++s) w.update(0.016f);
                    const float tr = turned(v0, w.creatures[k].vel);
                    toward[frame][side] += (sgn * tr > 0.01f);
                }
        t.expect(toward[1][0] == 8 && toward[1][1] == 8,
                 "own frame: the eye-wired fish turned toward food on the left %d/8, right %d/8", toward[1][0],
                 toward[1][1]);
        t.expect(toward[0][0] < 8 || toward[0][1] < 8,
                 "world frame: the same wires turned toward the food at every heading (left %d/8, right %d/8)",
                 toward[0][0], toward[0][1]);
        t.note("eye -> STEER_X toward food: own frame left %d/8 right %d/8; world frame left %d/8 right %d/8",
               toward[1][0], toward[1][1], toward[0][0], toward[0][1]);
    }
#endif
}

void testSensors() {
    Test t("sensors");
    struct V { unsigned seed; float D; const char* cfg; };
    const V vs[] = {
        {31, 240.0f, R"({"captureActivations":true})"},
        {32, 600.0f, R"({"pitchMax":2.5,"kBuoy":-3,"wallBand":50,"maxNeighbors":7,"toroidal":true,"foodPatches":3,"foodDepthMode":1,"predatorCount":3})"},
        {33, 10.0f, R"({"pitchMax":0.05,"vDrag":0,"wallBand":0,"foodDepthSpread":0,"foodDepthMode":1,"foodPatches":2})"},
    };
    const float tanh1 = evomath::tanhf(1.0f), tanh2 = evomath::tanhf(2.0f);
    long fishChecked = 0, sawFood = 0, sawNeighbor = 0;
    for (const V& v : vs) {
        OceanWorld w;
        std::string err;
        if (!t.expect(ofp::initWorld(w, v.seed, 1920, 1080, v.D, 400, v.cfg, err), "init: %s", err.c_str())) continue;
        w.cfg.captureActivations = true;   // not a checkpoint key: set it directly
        const float D = w.D, pm = w.ocfg.pitchMax, R = w.cfg.perceptionRadius;
        std::unordered_map<std::uint64_t, std::pair<float, float>> before;
        for (int s = 1; s <= 600; ++s) {
            before.clear();
            for (const Fish& c : w.creatures) before[c.id] = {c.depth, c.vz};
            w.update(0.016f);
            for (const Fish& c : w.creatures) {
                auto it = before.find(c.id);
                if (it == before.end() || !c.alive) continue;   // born or reseeded this step: no sensing yet
                ++fishChecked;
                const float z = it->second.first, vz = it->second.second;
                const float* S = c.lastSensors;
                bool allFinite = true;
                for (int k = 0; k < NUM_SENSES; ++k) allFinite &= finite(S[k]);
                t.expect(allFinite, "seed %u step %d: a non-finite sensor", v.seed, s);
                t.expect(S[LOC_Z] == z / D && S[LOC_Z] >= 0.0f && S[LOC_Z] <= 1.0f,
                         "LOC_Z %.9g != depth/D %.9g", S[LOC_Z], z / D);
                t.expect(S[OWN_VEL_Z] == vz / pm && std::abs(S[OWN_VEL_Z]) <= 1.0f,
                         "OWN_VEL_Z %.9g != vz/pitchMax %.9g", S[OWN_VEL_Z], vz / pm);
                const float bz = evomath::tanhf(std::min(z, D - z) / (0.25f * D));
                t.expect(S[BOUNDARY_DIST_Z] == bz && S[BOUNDARY_DIST_Z] >= 0.0f && S[BOUNDARY_DIST_Z] <= tanh2,
                         "BOUNDARY_DIST_Z %.9g expected %.9g", S[BOUNDARY_DIST_Z], bz);
                t.expect(std::abs(S[NEAREST_FOOD_DZ]) <= 1.0f, "NEAREST_FOOD_DZ %.9g", S[NEAREST_FOOD_DZ]);
                t.expect(std::abs(S[AVG_NEIGHBOR_DZ]) <= tanh1, "AVG_NEIGHBOR_DZ %.9g > tanh(1)", S[AVG_NEIGHBOR_DZ]);
                if (S[NEAREST_FOOD_DIST] < 1.0f) {
                    ++sawFood;
                    const float n2 = S[NEAREST_FOOD_DX] * S[NEAREST_FOOD_DX] + S[NEAREST_FOOD_DY] * S[NEAREST_FOOD_DY] +
                                     S[NEAREST_FOOD_DZ] * S[NEAREST_FOOD_DZ];
                    t.expect(std::abs(n2 - 1.0f) < 1e-5f || S[NEAREST_FOOD_DIST] * R <= 0.001f,
                             "food direction not a unit vector: |d|^2 = %.9g", n2);
                }
                if (S[NEAREST_NEIGHBOR_DIST] < 1.0f) ++sawNeighbor;
            }
        }
    }
    t.expect(sawFood > 1000 && sawNeighbor > 1000, "too few fish saw food (%ld) / a neighbour (%ld) to test", sawFood, sawNeighbor);
    t.note("%ld fish-steps; %ld saw food, %ld a neighbour", fishChecked, sawFood, sawNeighbor);
}

bool sameDynamics(const ofp::Fingerprint& a, const ofp::Fingerprint& b) {
    return a.ctr == b.ctr && a.fish == b.fish && a.food == b.food && a.pred == b.pred && a.sig == b.sig &&
           a.cur == b.cur && a.geo == b.geo && a.rng == b.rng;
}

// One step of hand-placed fish; sensors are read before anything moves (a fish
// senses at the start of its own stepFish, and these fixtures do not move
// vertically: kBuoy 0, no walls, no wiring unless a test adds it).
void testSensorSigns() {
    Test t("sensor_signs");
    OceanConfig oc;
    oc.kBuoy = 0.0f;
    oc.wallBand = 0.0f;
    OceanWorld w;
    initQuiet(w, 1301, 240.0f, oc, /*capture*/ true);
    const float D = w.D, R = w.cfg.perceptionRadius, pm = w.ocfg.pitchMax;
    // Fixtures >= 400 apart (> R): each sees only its own food / neighbour.
    struct FoodFix { Vec2 at; float z; Vec2 off; float dz; };
    const FoodFix ff[] = {
        {{200, 200}, 60.0f, {0, 0}, 50.0f},      // food straight below: DZ = +1
        {{600, 200}, 180.0f, {0, 0}, -50.0f},    // straight above: DZ = -1
        {{1000, 200}, 100.0f, {30, 0}, 40.0f},   // (30, 0, 40): DX .6, DZ .8
        {{1400, 200}, 200.0f, {0, -30}, -40.0f}, // (0, -30, -40): DY -.6, DZ -.8
    };
    int foodIdx[4];
    for (int k = 0; k < 4; ++k) {
        foodIdx[k] = addFish(w, ff[k].at, ff[k].z, {}, ff[k].z / D);
        OceanFood f;
        f.pos = {ff[k].at.x + ff[k].off.x, ff[k].at.y + ff[k].off.y};
        f.depth = ff[k].z + ff[k].dz;
        w.food.push_back(f);
    }
    // A pair 40 apart in depth (5 apart horizontally): the upper one's neighbours are deeper.
    const int up = addFish(w, {200, 700}, 100.0f, {}, 100.0f / D);
    const int dn = addFish(w, {205, 700}, 140.0f, {}, 140.0f / D);
    // vz preset: diving (+) and rising (-).
    const int dive = addFish(w, {600, 700}, 120.0f, {}, 0.5f);
    const int rise = addFish(w, {1000, 700}, 120.0f, {}, 0.5f);
    w.creatures[dive].vz = 0.25f;
    w.creatures[rise].vz = -0.25f;
    // BOUNDARY_DIST_Z along the column: surface, quarter, middle, three quarters, floor.
    const float bzDepth[5] = {0.0f, 60.0f, 120.0f, 180.0f, 240.0f};
    int bz[5];
    for (int k = 0; k < 5; ++k) bz[k] = addFish(w, {1400.0f + 100.0f * (k % 2), 600.0f + 110.0f * k}, bzDepth[k], {}, bzDepth[k] / D);
    // Sensor -> action: a NEAREST_FOOD_DZ -> STEER_Z (+) fish with food below, one with food above.
    const int seekDn = addFish(w, {1800, 200}, 100.0f, {mkGene(true, NEAREST_FOOD_DZ, STEER_Z, kStrong)}, 100.0f / D);
    const int seekUp = addFish(w, {1800, 900}, 140.0f, {mkGene(true, NEAREST_FOOD_DZ, STEER_Z, kStrong)}, 140.0f / D);
    for (const auto& fz : {std::pair<Vec2, float>{{1800, 200}, 150.0f}, std::pair<Vec2, float>{{1800, 900}, 90.0f}}) {
        OceanFood f;
        f.pos = fz.first;
        f.depth = fz.second;
        w.food.push_back(f);
    }
    std::vector<Fish> before = w.creatures;
    w.update(0.016f);
    auto S = [&](int i) { return w.creatures[i].lastSensors; };

    for (int k = 0; k < 4; ++k) {
        const Fish& c = before[foodIdx[k]];
        const float dx = ff[k].off.x, dy = ff[k].off.y, dz = ff[k].dz;
        const float dist = std::sqrt(dx * dx + dy * dy + dz * dz), inv = 1.0f / dist;
        const float* s = S(foodIdx[k]);
        t.expect(s[NEAREST_FOOD_DX] == dx * inv && s[NEAREST_FOOD_DY] == dy * inv && s[NEAREST_FOOD_DZ] == dz * inv,
                 "food fixture %d: (%.9g, %.9g, %.9g), expected (%.9g, %.9g, %.9g)", k, s[NEAREST_FOOD_DX],
                 s[NEAREST_FOOD_DY], s[NEAREST_FOOD_DZ], dx * inv, dy * inv, dz * inv);
        t.expect((s[NEAREST_FOOD_DZ] > 0.0f) == (dz > 0.0f) && s[NEAREST_FOOD_DZ] != 0.0f,
                 "food fixture %d: NEAREST_FOOD_DZ %.9g has the wrong sign (food is %s)", k, s[NEAREST_FOOD_DZ],
                 dz > 0.0f ? "deeper" : "shallower");
        t.expect(s[NEAREST_FOOD_DIST] == dist / R, "food fixture %d: NEAREST_FOOD_DIST %.9g != %.9g", k,
                 s[NEAREST_FOOD_DIST], dist / R);
        t.expect(s[LOC_Z] == c.depth / D, "food fixture %d: LOC_Z %.9g != depth/D %.9g", k, s[LOC_Z], c.depth / D);
    }
    t.expect(S(foodIdx[0])[NEAREST_FOOD_DZ] == 1.0f && S(foodIdx[1])[NEAREST_FOOD_DZ] == -1.0f,
             "straight below / above: DZ %.9g / %.9g, expected +1 / -1", S(foodIdx[0])[NEAREST_FOOD_DZ],
             S(foodIdx[1])[NEAREST_FOOD_DZ]);
    t.expect(S(foodIdx[0])[LOC_Z] == 0.25f && S(foodIdx[1])[LOC_Z] == 0.75f, "LOC_Z at 60 / 180 of 240: %.9g / %.9g",
             S(foodIdx[0])[LOC_Z], S(foodIdx[1])[LOC_Z]);

    // AVG_NEIGHBOR_DZ: tanh(mean dz / R), + when the neighbours are deeper.
    t.expect(S(up)[AVG_NEIGHBOR_DZ] == evomath::tanhf(40.0f / R) && S(up)[AVG_NEIGHBOR_DZ] > 0.0f,
             "upper fish: AVG_NEIGHBOR_DZ %.9g, expected +tanh(0.4) = %.9g", S(up)[AVG_NEIGHBOR_DZ], evomath::tanhf(40.0f / R));
    t.expect(S(dn)[AVG_NEIGHBOR_DZ] == evomath::tanhf(-40.0f / R) && S(dn)[AVG_NEIGHBOR_DZ] < 0.0f,
             "lower fish: AVG_NEIGHBOR_DZ %.9g, expected -tanh(0.4)", S(dn)[AVG_NEIGHBOR_DZ]);
    t.expect(S(dive)[AVG_NEIGHBOR_DZ] == 0.0f && S(dive)[NEAREST_FOOD_DZ] == 0.0f,
             "a lone fish: AVG_NEIGHBOR_DZ %.9g NEAREST_FOOD_DZ %.9g (expected 0)", S(dive)[AVG_NEIGHBOR_DZ],
             S(dive)[NEAREST_FOOD_DZ]);

    // OWN_VEL_Z: vz / pitchMax, + = diving; a diving fish gets deeper (LOC_Z up).
    t.expect(S(dive)[OWN_VEL_Z] == 0.25f / pm && S(dive)[OWN_VEL_Z] > 0.0f, "diving: OWN_VEL_Z %.9g, expected +%.9g",
             S(dive)[OWN_VEL_Z], 0.25f / pm);
    t.expect(S(rise)[OWN_VEL_Z] == -0.25f / pm, "rising: OWN_VEL_Z %.9g, expected %.9g", S(rise)[OWN_VEL_Z], -0.25f / pm);
    t.expect(w.creatures[dive].depth > 120.0f && w.creatures[rise].depth < 120.0f,
             "+vz must dive (depth 120 -> %.6f) and -vz rise (-> %.6f)", w.creatures[dive].depth, w.creatures[rise].depth);

    // BOUNDARY_DIST_Z = tanh(min(z, D - z) / (D/4)): 0 at both walls, largest mid-column, symmetric.
    for (int k = 0; k < 5; ++k) {
        const float z = bzDepth[k];
        const float e = evomath::tanhf(std::min(z, D - z) / (0.25f * D));
        t.expect(S(bz[k])[BOUNDARY_DIST_Z] == e, "BOUNDARY_DIST_Z at %g: %.9g, expected %.9g", z, S(bz[k])[BOUNDARY_DIST_Z], e);
    }
    t.expect(S(bz[0])[BOUNDARY_DIST_Z] == 0.0f && S(bz[4])[BOUNDARY_DIST_Z] == 0.0f &&
                 S(bz[1])[BOUNDARY_DIST_Z] == S(bz[3])[BOUNDARY_DIST_Z] &&
                 S(bz[2])[BOUNDARY_DIST_Z] > S(bz[1])[BOUNDARY_DIST_Z] && S(bz[1])[BOUNDARY_DIST_Z] > 0.0f,
             "BOUNDARY_DIST_Z along the column: %.6f %.6f %.6f %.6f %.6f", S(bz[0])[BOUNDARY_DIST_Z],
             S(bz[1])[BOUNDARY_DIST_Z], S(bz[2])[BOUNDARY_DIST_Z], S(bz[3])[BOUNDARY_DIST_Z], S(bz[4])[BOUNDARY_DIST_Z]);

    // The sensor's meaning end to end: wired (+) to STEER_Z it steers toward the food.
    t.expect(S(seekDn)[NEAREST_FOOD_DZ] > 0.0f && S(seekUp)[NEAREST_FOOD_DZ] < 0.0f,
             "seekers: DZ %.6f (food below) / %.6f (food above)", S(seekDn)[NEAREST_FOOD_DZ], S(seekUp)[NEAREST_FOOD_DZ]);
    for (int s = 0; s < 9; ++s) w.update(0.016f);
    t.expect(w.creatures[seekDn].depth > 100.0f && w.creatures[seekUp].depth < 140.0f,
             "NEAREST_FOOD_DZ -> STEER_Z (+) did not move toward the food: %.4f (from 100, food at 150), %.4f (from 140, food at 90)",
             w.creatures[seekDn].depth, w.creatures[seekUp].depth);
    t.note("DZ +1 / -1 / .8 / -.8 as placed; AVG_NEIGHBOR_DZ ±tanh(.4); seekers after 10 steps at %.2f / %.2f",
           w.creatures[seekDn].depth, w.creatures[seekUp].depth);
}

// CURRENT_FWD / CURRENT_LR with the 3-D flow on.
void testCurrentSensors() {
    Test t("current_sens");
    for (int waves = 0; waves < 2; ++waves) {
        SimConfig sc;
        applyOceanDefaults(sc);
        sc.minPopulation = 0; sc.targetFood = 0; sc.foodSpawnBase = 0.0f; sc.foodSpawnAmp = 0.0f;
        sc.metabolicRate = 0.0f; sc.maxAge = 1e9f; sc.predatorCount = 0;
        sc.captureActivations = true;
        sc.currentStrength = 60.0f;
        sc.currentDrift = 0.0f;   // a static field: the current a fish senses is currentAt() before and after
        OceanConfig oc;
        oc.deepCurrent = true;    // flowE1(): the sensors read flowAt
        oc.waveSpeed = waves ? 6.0f : 0.0f;
        oc.kBuoy = 0.0f;
        oc.wallBand = 0.0f;
        OceanWorld w;
        rng.seed(1311);
        w.cfg = sc;
        w.ocfg = oc;
        w.init(1920, 1080, 240.0f, 0);
        w.update(0.016f);   // the first advance() places the eddy centres
        // The strongest current on a coarse lattice: a clear direction to align with.
        Vec2 at{0, 0}, cur{0, 0};
        float best = -1.0f;
        for (int j = 1; j < 10; ++j)
            for (int i = 1; i < 18; ++i) {
                const Vec2 p{(float)i * 100.0f, (float)j * 100.0f};
                const Vec2 c = w.currentAt(p);
                const float m = c.x * c.x + c.y * c.y;
                if (m > best) { best = m; at = p; cur = c; }
            }
        const float len = std::sqrt(best);
        const Vec2 u{cur.x / len, cur.y / len};
        // Fixtures at that spot, 60+ apart in depth (> interactRadius): along the
        // current, against it, and rotated so the current is on their right.
        struct Fx { const char* what; float z; Vec2 head; };
        const Fx fx[] = {
            {"along, mid-column", 120.0f, u}, {"against, mid-column", 180.0f, {-u.x, -u.y}},
            {"current on the right", 60.0f, {u.y, -u.x}}, {"along, at the surface", 0.0f, u},
            {"along, deep", 240.0f, u},
        };
        constexpr int NF = 5;
        int idx[NF];
        Vec2 fwd[NF];
        for (int k = 0; k < NF; ++k) {
            idx[k] = addFish(w, at, fx[k].z, {}, fx[k].z / 240.0f);
            w.creatures[idx[k]].vel = fx[k].head;
            fwd[k] = w.creatures[idx[k]].forward();
        }
        w.update(0.016f);
        for (int k = 0; k < NF; ++k) {
            const float* s = w.creatures[idx[k]].lastSensors;
            const float z = fx[k].z;
            OceanWorld::Flow U;
            if (waves) {
                U = w.flowAt(at, z);
            } else {   // independent of flowAt: f(d) = smoothstep(2d/D) on the 2-D current
                const float f = (z <= 0.0f) ? 0.0f : (z >= 120.0f) ? 1.0f : (z == 60.0f ? 0.5f : -1.0f);
                U.x = f * cur.x;
                U.y = f * cur.y;
            }
            const Vec2 r{-fwd[k].y, fwd[k].x};
            const float eF = evomath::tanhf((U.x * fwd[k].x + U.y * fwd[k].y) / 100.0f);
            const float eL = evomath::tanhf((U.x * r.x + U.y * r.y) / 100.0f);
            t.expect(s[CURRENT_FWD] == eF && s[CURRENT_LR] == eL, "%s, %s: FWD %.9g LR %.9g, expected %.9g %.9g",
                     waves ? "waves" : "deep current", fx[k].what, s[CURRENT_FWD], s[CURRENT_LR], eF, eL);
        }
        const float* along = w.creatures[idx[0]].lastSensors;
        const float* against = w.creatures[idx[1]].lastSensors;
        const float* right = w.creatures[idx[2]].lastSensors;
        const float* surf = w.creatures[idx[3]].lastSensors;
        t.expect(along[CURRENT_FWD] > 0.1f && against[CURRENT_FWD] < -0.1f && right[CURRENT_LR] > 0.05f,
                 "%s: signs: along FWD %.6f, against FWD %.6f, on the right LR %.6f", waves ? "waves" : "deep current",
                 along[CURRENT_FWD], against[CURRENT_FWD], right[CURRENT_LR]);
        if (!waves) {
            t.expect(surf[CURRENT_FWD] == 0.0f && surf[CURRENT_LR] == 0.0f, "deep current at the surface: FWD %.9g LR %.9g",
                     surf[CURRENT_FWD], surf[CURRENT_LR]);
            t.expect(along[CURRENT_FWD] == evomath::tanhf(len / 100.0f) || std::abs(along[CURRENT_FWD] - evomath::tanhf(len / 100.0f)) < 1e-6f,
                     "along the current: FWD %.9g, expected tanh(|U|/100) %.9g", along[CURRENT_FWD], evomath::tanhf(len / 100.0f));
            t.note("strongest current %.2f at (%g, %g): FWD along %.4f, against %.4f; LR on the right %.4f; surface 0",
                   len, at.x, at.y, along[CURRENT_FWD], against[CURRENT_FWD], right[CURRENT_LR]);
        }
    }
}

// The depth wall bands, one step, exactly as specified.
void testWalls() {
    Test t("walls");
    struct V { float D, wallBand, z; int sign; };
    const V vs[] = {
        {240.0f, 12.0f, 2.0f, +1}, {240.0f, 12.0f, 238.0f, -1}, {240.0f, 12.0f, 120.0f, 0},
        {240.0f, 12.0f, 0.0f, +1}, {240.0f, 12.0f, 240.0f, -1},
        // A shallow sea: each band is capped at D/2, so depth 9 of 10 is in the FLOOR band.
        {10.0f, 12.0f, 9.0f, -1}, {10.0f, 12.0f, 1.0f, +1},
    };
    long pushes = 0;
    for (const V& v : vs) {
        OceanConfig oc;
        oc.kBuoy = 0.0f;
        oc.vDrag = 0.0f;
        oc.wallBand = v.wallBand;
        OceanWorld w;
        initQuiet(w, 1321, v.D, oc);
        const int i = addFish(w, {500, 500}, v.z, {}, 0.5f);
        const float speed = w.creatures[i].speed, dt = 0.016f;
        w.update(dt);
        const Fish& c = w.creatures[i];
        const float wb = std::min(v.wallBand, 0.5f * v.D);
        float vz = 0.0f;
        if (v.z < wb) vz += (1.0f - v.z / wb) * 3.0f * dt;
        else if (v.z > v.D - wb) vz -= (1.0f - (v.D - v.z) / wb) * 3.0f * dt;
        vz = std::clamp(vz, -oc.pitchMax, oc.pitchMax);
        const float z = std::clamp(v.z + vz * speed * dt, 0.0f, v.D);
        t.expect(c.vz == vz && c.depth == z, "D %g band %g depth %g: vz %.9g depth %.9g, expected %.9g %.9g", v.D, v.wallBand,
                 v.z, c.vz, c.depth, vz, z);
        t.expect((c.vz > 0.0f) - (c.vz < 0.0f) == v.sign, "D %g depth %g: the wall pushed the wrong way (vz %.9g)", v.D, v.z, c.vz);
        pushes += (c.vz != 0.0f);
    }
    t.expect(pushes == 6, "%ld of 6 band fixtures were pushed", pushes);
}

// Stage B predator economy, one step each, bit for bit.
void testPredatorEconomy() {
    Test t("pred_econ");
    const float dt = 0.016f;
    auto world = [&](OceanWorld& w, unsigned seed) {
        initQuiet(w, seed, 240.0f, OceanConfig{});
        w.cfg.predatorEconomy = true;
        w.cfg.moveCost = 7e-5f;
        w.cfg.predatorMetabolism = 2.0f;
        w.cfg.predatorReproEnergy = 1e6f;   // no budding: one predator, its energy as computed
    };
    // Burn: metabolism + coefficient·speed², the coefficient predatorMoveCost (>= 0) or moveCost.
    float energyAfter[2];
    for (int k = 0; k < 2; ++k) {
        const float pmc = k ? 3e-4f : -1.0f;
        OceanWorld w;
        world(w, 1401);
        w.cfg.predatorMoveCost = pmc;
        OceanPredator p;
        p.pos = {500, 500};
        p.depth = 100.0f;
        p.energy = 40.0f;
        p.speedFactor = 1.25f;
        w.predators.push_back(p);
        w.update(dt);
        const float coef = (pmc >= 0.0f) ? pmc : 7e-5f;
        const float speed = w.cfg.predatorSpeed * 1.25f;
        const float burn = w.cfg.predatorMetabolism + coef * speed * speed;
        const float e = 40.0f - burn * dt;
        energyAfter[k] = w.predators[0].energy;
        t.expect(w.predators[0].energy == e && w.predators[0].age == dt, "predatorMoveCost %g: energy %.9g age %.9g, expected %.9g %.9g",
                 pmc, w.predators[0].energy, w.predators[0].age, e, dt);
    }
    t.expect(energyAfter[0] != energyAfter[1], "an explicit predatorMoveCost changed nothing");
    // A capture: + predatorMeal when >= 0, else + the prey's reserves.
    for (float meal : {9.0f, -1.0f}) {
        OceanWorld w;
        world(w, 1402);
        w.cfg.moveCost = 0.0f;   // the prey's reserves stay what they were placed with
        w.cfg.predatorMeal = meal;
        const int prey = addFish(w, {500, 500}, 100.0f, {}, 100.0f / 240.0f);
        w.creatures[prey].foodReserves = 33.0f;
        OceanPredator p;
        p.pos = {505, 500};
        p.depth = 100.0f;
        p.energy = 40.0f;
        w.predators.push_back(p);
        w.update(dt);
        const float burn = w.cfg.predatorMetabolism + 0.0f * w.cfg.predatorSpeed * w.cfg.predatorSpeed;
        const float e = (40.0f - burn * dt) + (meal >= 0.0f ? meal : 33.0f);
        t.expect(w.totalDeathsPredation == 1 && w.creatures.empty() && w.predators.size() == 1,
                 "meal %g: no capture (%lld), %zu predators", meal, w.totalDeathsPredation, w.predators.size());
        t.expect(w.predators[0].energy == e && w.predators[0].digestTimer == w.cfg.predatorCooldown,
                 "meal %g: energy %.9g, expected %.9g", meal, w.predators[0].energy, e);
    }
    // Old age: dead the step its age reaches predatorMaxAge, not before.
    for (float age0 : {0.98f, 0.995f}) {
        OceanWorld w;
        world(w, 1403);
        w.cfg.predatorMaxAge = 1.0f;
        OceanPredator p;
        p.pos = {500, 500};
        p.depth = 100.0f;
        p.energy = 40.0f;
        p.age = age0;
        w.predators.push_back(p);
        w.update(dt);
        const bool dies = age0 + dt >= 1.0f;
        t.expect(w.predators.size() == (dies ? 0u : 1u) && w.totalPredatorDeathsAge == (dies ? 1 : 0) &&
                     w.totalPredatorDeathsStarvation == 0,
                 "age %g + dt vs max 1: %zu predators, %lld age deaths", age0, w.predators.size(), w.totalPredatorDeathsAge);
    }
}

// Two adult, well-fed fish wired to pair, one step, under the pairing gates.
struct GateRun { bool born = false; long draws = -1; long long grace = 0, soft = 0; };
GateRun pairStep(unsigned seed, int maxPop, float T, float W, float grace, bool farGenomes, bool founders, float age) {
    OceanWorld w;
    initQuiet(w, seed, 240.0f, OceanConfig{});
    w.cfg.maxPopulation = maxPop;
    w.cfg.reproMaxDistance = T;
    w.cfg.reproSoftWidth = W;
    w.cfg.reproGracePeriod = grace;
    std::vector<Gene> g1 = {mkGene(false, 0, INTERACT_REPRODUCE, kStrong)}, g2 = g1;
    // An extra wire (its sensor is 0 in the vote) puts (32767/8192)^2 ~ 16 between the genomes.
    if (farGenomes) g2.push_back(mkGene(true, LOC_X, STEER_X, kStrong));
    const int a = addFish(w, {960, 540}, 100.0f, g1, 0.4f), b = addFish(w, {961, 541}, 101.0f, g2, 0.4f);
    for (int i : {a, b}) {
        Fish& f = w.creatures[i];
        f.age = age;
        f.foodReserves = 100.0f;
        f.reproTimer = 0.0f;
        f.interactTimer = 0.0f;
        if (!founders) f.lineageId = f.id + 1000;   // not its own line: no grace
    }
    GateRun r;
    const RandomGen before = rng;
    w.update(0.016f);
    r.draws = drawsBetween(before, rng);
    r.born = w.creatures.size() == 3;
    r.grace = w.totalGraceBirths;
    r.soft = w.totalSoftBirths;
    return r;
}

void testPairingGates() {
    Test t("pair_gates");
    for (unsigned seed : {1501u, 1502u, 1503u}) {
        // The maxPopulation cap: 2 fish + 0 newborns must be < the cap.
        const GateRun capped = pairStep(seed, 2, -1.0f, 0.0f, 0.0f, false, false, 10.0f);
        const GateRun under = pairStep(seed, 3, -1.0f, 0.0f, 0.0f, false, false, 10.0f);
        t.expect(!capped.born && under.born, "seed %u: maxPopulation 2 born %d, 3 born %d", seed, capped.born, under.born);
        // The hard gate (soft width 0): identical genomes pass, far ones do not, and the gate draws nothing.
        const GateRun near = pairStep(seed, 0, 1.0f, 0.0f, 0.0f, false, false, 10.0f);
        const GateRun far = pairStep(seed, 0, 1.0f, 0.0f, 0.0f, true, false, 10.0f);
        const GateRun farCapped = pairStep(seed, 2, 1.0f, 0.0f, 0.0f, true, false, 10.0f);   // refused before the gate
        const GateRun farOff = pairStep(seed, 0, -1.0f, 0.0f, 0.0f, true, false, 10.0f);
        t.expect(near.born && !far.born && farOff.born, "seed %u: hard gate T 1: near born %d, far born %d (gate off: %d)",
                 seed, near.born, far.born, farOff.born);
        t.expect(far.draws == farCapped.draws && near.soft == 0 && near.grace == 0,
                 "seed %u: the hard gate drew (%ld vs %ld draws) or counted soft/grace", seed, far.draws, farCapped.draws);
        // Grace: a young founder bypasses the gate (counted); an older one, or a non-founder, does not.
        const GateRun young = pairStep(seed, 0, 1.0f, 0.0f, 20.0f, true, true, 10.0f);
        const GateRun old = pairStep(seed, 0, 1.0f, 0.0f, 20.0f, true, true, 25.0f);
        const GateRun notFounder = pairStep(seed, 0, 1.0f, 0.0f, 20.0f, true, false, 10.0f);
        t.expect(young.born && young.grace == 1 && !old.born && !notFounder.born,
                 "seed %u: grace 20: young founders born %d (grace %lld), age 25 born %d, non-founders born %d", seed,
                 young.born, young.grace, old.born, notFounder.born);
    }
}

// cfg.fastTanh reaches the Ocean world's net (stepFish -> feedForward).
void testFastTanh() {
    Test t("fast_tanh");
    int differ = 0;
    for (int wgt : {4096, 9000, 16384, 30000}) {
        float act[2];
        for (int fast = 0; fast < 2; ++fast) {
            OceanConfig oc;
            oc.kBuoy = 0.0f;
            OceanWorld w;
            initQuiet(w, 1601, 240.0f, oc, /*capture*/ true);
            w.cfg.fastTanh = (fast == 1);
            const int i = addFish(w, {500, 500}, 120.0f, {mkGene(false, 0, STEER_Z, wgt)}, 0.5f);
            w.update(0.016f);
            act[fast] = w.creatures[i].lastActions[STEER_Z];
        }
        const float x = 0.5f * (float)wgt / 8192.0f;   // undriven neuron 0 (0.5) x weight
        t.expect(act[0] == evomath::tanhf(x) && act[1] == fastTanhApprox(x), "weight %d: actions %.9g / %.9g, expected %.9g / %.9g",
                 wgt, act[0], act[1], evomath::tanhf(x), fastTanhApprox(x));
        differ += (act[0] != act[1]);
    }
    t.expect(differ > 0, "fastTanh on and off gave identical actions: the flag does not reach the net");
}

void testCaptureNeutral() {
    Test t("capture");
    const char* cfg = R"({"predatorCount":3,"currentStrength":50,"foodPatches":3})";
    ofp::Fingerprint fp[2];
    for (int k = 0; k < 2; ++k) {
        OceanWorld w;
        std::string err;
        ofp::initWorld(w, 41, 1920, 1080, 240.0f, 300, cfg, err);
        w.cfg.captureActivations = (k == 1);
        for (int s = 0; s < 800; ++s) w.update(0.016f);
        fp[k] = ofp::fingerprint(w, /*withActivations*/ false);
    }
    t.expect(sameDynamics(fp[0], fp[1]), "captureActivations changed the run (fish %016llx vs %016llx)",
             (unsigned long long)fp[0].fish, (unsigned long long)fp[1].fish);
}

// ---- the compound eye -------------------------------------------------------
#ifdef EVO_OCEAN_EYE
// One sector's three inputs, as eyeWrite computes them, for an object at
// squared distance d2 with world size s and contrast con.
void eyeExpect(float d2, float s, float con, float R, float out[3]) {
    const float d = std::sqrt(d2);
    out[0] = 1.0f - d / R;
    out[1] = s / (s + d);
    out[2] = con;
}

void testEye() {
    Test t("eye");
    // (1) A hand-built scene, checked bit for bit: a viewer heading +x at depth
    // 120, and around it food ahead (30) with a fish further ahead (60), a fish
    // behind (50), food to the left (-y, 20), a predator to the right (+y, 70),
    // a fish above (25 shallower) and a predator below (40 deeper), plus a food
    // item beyond R that must not count. Nothing is wired, so nothing moves the
    // viewer's state before it senses (it steps first).
    {
        OceanConfig oc;
        oc.eye = 1;
        OceanWorld w;
        initQuiet(w, 61, 240.0f, oc, /*capture*/ true);
        const Vec2 P = {600.0f, 500.0f};
        const float z = 120.0f;
        const int v = addFish(w, P, z, {}, 0.5f);
        w.creatures[v].vel = {1.0f, 0.0f};
        const int fAhead = addFish(w, {P.x + 60.0f, P.y}, z, {}, 0.5f);
        const int fBehind = addFish(w, {P.x - 50.0f, P.y}, z, {}, 0.5f);
        const int fUp = addFish(w, P, z - 25.0f, {}, 0.5f);
        w.creatures[fBehind].bodySize = 1.5f;   // a bigger fish looks bigger
        auto food = [&](float x, float y, float fz) {
            OceanFood f;
            f.pos = {x, y};
            f.depth = fz;
            f.eyeCon = ocean::eyeContrast(ocean::kEyeFoodBright, fz);
            w.food.push_back(f);
        };
        food(P.x + 30.0f, P.y, z);
        food(P.x, P.y - 20.0f, z);
        food(P.x + 101.0f, P.y, z);   // beyond R = 100
        auto pred = [&](float x, float y, float pz) {
            OceanPredator p;
            p.pos = {x, y};
            p.vel = {1.0f, 0.0f};
            p.depth = pz;
            p.digestTimer = 1e9f;   // never eats in this test
            w.predators.push_back(p);
        };
        pred(P.x, P.y + 70.0f, z);
        pred(P.x, P.y, z + 40.0f);
        (void)fAhead; (void)fUp;
        const float R = w.cfg.perceptionRadius;
        w.update(0.016f);
        const float* S = w.creatures[v].lastSensors;
        float want[ocean::kEyeSectors][3];
        eyeExpect(900.0f, ocean::kEyeFoodSize, ocean::eyeContrast(ocean::kEyeFoodBright, z), R, want[0]);
        eyeExpect(2500.0f, ocean::kEyeFishLen * 1.5f, ocean::eyeContrast(ocean::kEyeFishBright, z), R, want[1]);
        eyeExpect(400.0f, ocean::kEyeFoodSize, ocean::eyeContrast(ocean::kEyeFoodBright, z), R, want[2]);
        eyeExpect(4900.0f, ocean::kEyePredSize, ocean::eyeContrast(ocean::kEyePredBright, z), R, want[3]);
        eyeExpect(625.0f, ocean::kEyeFishLen * 1.0f, ocean::eyeContrast(ocean::kEyeFishBright, z - 25.0f), R, want[4]);
        eyeExpect(1600.0f, ocean::kEyePredSize, ocean::eyeContrast(ocean::kEyePredBright, z + 40.0f), R, want[5]);
        static const char* kSec[] = {"ahead", "behind", "left", "right", "up", "down"};
        for (int k = 0; k < ocean::kEyeSectors; ++k)
            for (int f = 0; f < 3; ++f) {
                const float got = S[ocean::kEyeFirst + 3 * k + f];
                t.expect(got == want[k][f], "scene: %s feature %d = %.9g, expected %.9g", kSec[k], f,
                         got, want[k][f]);
            }
        t.note("scene: ahead food %.3f/%.3f/%.3f, behind fish %.3f/%.3f/%.3f, down predator %.3f/%.3f/%.3f",
               S[EYE_AHEAD_PROX], S[EYE_AHEAD_SIZE], S[EYE_AHEAD_CON], S[EYE_BEHIND_PROX],
               S[EYE_BEHIND_SIZE], S[EYE_BEHIND_CON], S[EYE_DOWN_PROX], S[EYE_DOWN_SIZE], S[EYE_DOWN_CON]);
    }
    // (2) Populated worlds, every fish-step: off -> the 18 inputs are exactly 0;
    // on -> each sector is empty (0, 0, 0) or holds an object (PROX in [0, 1],
    // SIZE in (0, 1], CON in [-1, 1]); every input finite.
    {
        long onSteps = 0, offSteps = 0, seen = 0, slots = 0;
        for (int eyeOn = 0; eyeOn < 2; ++eyeOn) {
            const char* cfgs[] = {
                R"({"predatorCount":4,"foodPatches":3,"foodDepthMode":1})",
                R"({"maxNeighbors":7,"toroidal":true,"predatorCount":6,"predatorEconomy":true,"currentStrength":60})",
            };
            for (const char* base : cfgs) {
                std::string cfg = std::string(base);
                cfg.back() = ',';
                cfg += eyeOn ? "\"eye\":1}" : "\"eye\":0}";
                OceanWorld w;
                std::string err;
                if (!t.expect(ofp::initWorld(w, 62 + eyeOn, 1920, 1080, 240.0f, 500, cfg.c_str(), err),
                              "init: %s", err.c_str()))
                    continue;
                w.cfg.captureActivations = true;
                for (int s = 0; s < 300; ++s) {
                    w.update(0.016f);
                    for (const Fish& c : w.creatures) {
                        if (c.age <= 0.0f) continue;   // reseeded / born after sensing
                        const float* E = c.lastSensors + ocean::kEyeFirst;
                        if (!eyeOn) {
                            ++offSteps;
                            bool zero = true;
                            for (int k = 0; k < ocean::kEyeInputs; ++k) zero &= (E[k] == 0.0f);
                            t.expect(zero, "eye off but an eye input is not 0");
                            continue;
                        }
                        ++onSteps;
                        for (int k = 0; k < ocean::kEyeSectors; ++k) {
                            const float p = E[3 * k], sz = E[3 * k + 1], cn = E[3 * k + 2];
                            ++slots;
                            t.expect(finite(p) && finite(sz) && finite(cn), "non-finite eye input");
                            if (p == 0.0f && sz == 0.0f && cn == 0.0f) continue;
                            ++seen;
                            t.expect(p >= 0.0f && p <= 1.0f && sz > 0.0f && sz <= 1.0f && cn >= -1.0f &&
                                         cn <= 1.0f,
                                     "eye sector %d out of range: %.9g %.9g %.9g", k, p, sz, cn);
                        }
                    }
                }
            }
        }
        t.expect(onSteps > 10000 && offSteps > 10000 && seen > slots / 10,
                 "too little to test: on %ld off %ld, %ld of %ld sectors saw something", onSteps,
                 offSteps, seen, slots);
        t.note("populated: %ld fish-steps on, %ld off; %.1f%% of sectors held an object", onSteps,
               offSteps, slots ? 100.0 * seen / slots : 0.0);
    }
    // (3) The eye has no side effects: fish with no wiring act the same whatever
    // they see, so a world of them (with food and wandering predators that draw
    // and capture) must run identically with the eye on and off — same state,
    // same draws — and differ only in lastSensors. (k = 2: the eye on with every
    // encoding bit set; k = 3: every eyeCode bit, the cloaks too.)
    {
        ofp::Fingerprint fp[4];
        long nonzero = 0;
        for (int k = 0; k < 4; ++k) {
            OceanConfig oc;
            oc.eye = k ? 1 : 0;
            oc.eyeCode = (k == 2) ? kEyeCodeAll : (k == 3) ? kEyeCodeMax : 0;
            OceanWorld w;
            initQuiet(w, 64, 240.0f, oc, /*capture*/ true);
            w.cfg.predatorCount = 3;
            for (int j = 0; j < 400; ++j) {
                const Vec2 p = {rng.range(10.0f, 1910.0f), rng.range(10.0f, 1070.0f)};
                addFish(w, p, rng.range(0.0f, 240.0f), {}, 0.5f);
            }
            for (int j = 0; j < 600; ++j) w.spawnFood();
            for (int j = 0; j < 3; ++j) {
                OceanPredator p;
                p.pos = {rng.range(10.0f, 1910.0f), rng.range(10.0f, 1070.0f)};
                p.vel = {1.0f, 0.0f};
                p.depth = rng.range(0.0f, 240.0f);
                w.predators.push_back(p);
            }
            for (int s = 0; s < 400; ++s) w.update(0.016f);
            fp[k] = ofp::fingerprint(w, /*withActivations*/ false);
            if (k == 1)
                for (const Fish& c : w.creatures)
                    for (int e = 0; e < ocean::kEyeInputs; ++e) nonzero += (c.lastSensors[ocean::kEyeFirst + e] != 0.0f);
        }
        for (int k = 1; k < 4; ++k)
            t.expect(fp[0].ctr == fp[k].ctr && fp[0].fish == fp[k].fish && fp[0].food == fp[k].food &&
                         fp[0].pred == fp[k].pred && fp[0].rng == fp[k].rng,
                     "the eye (eyeCode %d) changed an unwired world (fish %016llx vs %016llx, rng %016llx vs %016llx)",
                     k == 2 ? kEyeCodeAll : k == 3 ? kEyeCodeMax : 0, (unsigned long long)fp[0].fish, (unsigned long long)fp[k].fish,
                     (unsigned long long)fp[0].rng, (unsigned long long)fp[k].rng);
        t.expect(nonzero > 0, "the eye saw nothing in the side-effect world");
    }
}

// Eye-only mode (OceanConfig::eyeOnly). An unwired world (as in testEye (3):
// fish act the same whatever they sense) is run with the labels on and off,
// eye on and off: every run must have the same state and draws; in eye-only
// mode the 23 labeled inputs are exactly 0 every fish-step, and every other
// input (own state, pheromones, current, RANDOM_SENSOR, and the 18 eye inputs)
// is bit-identical to the labeled run's, fish-step by fish-step.
void testEyeOnly() {
    Test t("eye_only");
    t.expect(ocean::kNumLabeledSenses == 23, "labeled list has %d senses", ocean::kNumLabeledSenses);
    {
        OceanConfig oc;
        oc.eyeOnly = 1;
        t.expect(oceanConfigValid(oc), "eyeOnly = 1 refused by the eye build");
        oc.eye = 1;
        t.expect(oceanConfigValid(oc), "eye 1 + eyeOnly 1 refused");
        oc.eyeOnly = 2;
        t.expect(!oceanConfigValid(oc), "eyeOnly = 2 accepted");
    }
    struct Run { ofp::Fingerprint fp; std::vector<std::uint64_t> kept; long labeledNonZero = 0, fishSteps = 0; };
    auto run = [&](int eye, int eyeOnly, bool toroidal, int maxNeighbors, int eyeCode) {
        Run r;
        OceanConfig oc;
        oc.eye = eye;
        oc.eyeOnly = eyeOnly;
        oc.eyeCode = eyeCode;
        OceanWorld w;
        initQuiet(w, 65, 240.0f, oc, /*capture*/ true, toroidal);
        w.cfg.maxNeighbors = maxNeighbors;
        w.cfg.predatorCount = 3;
        w.cfg.currentStrength = 60.0f;   // CURRENT_FWD / LR non-zero (the field is built at
        w.init(1920, 1080, 240.0f, 0);   // init: rebuild; init also makes the 3 hunters)
        for (int j = 0; j < 400; ++j) {
            const Vec2 p = {rng.range(10.0f, 1910.0f), rng.range(10.0f, 1070.0f)};
            // One EMIT_SIGNAL0 wire from an undriven neuron (0.5): pheromones,
            // the same in every mode; nothing else is wired.
            addFish(w, p, rng.range(0.0f, 240.0f), {mkGene(false, 0, EMIT_SIGNAL0, kStrong)}, 0.5f);
        }
        for (int j = 0; j < 600; ++j) w.spawnFood();
        for (int s = 0; s < 300; ++s) {
            w.update(0.016f);
            ofp::Hasher h;
            for (const Fish& c : w.creatures) {
                if (c.age <= 0.0f) continue;
                ++r.fishSteps;
                for (int k = 0; k < NUM_SENSES; ++k) {
                    if (ocean::isLabeledSense(k)) { r.labeledNonZero += (c.lastSensors[k] != 0.0f); continue; }
                    h.f32(c.lastSensors[k]);
                }
            }
            r.kept.push_back(h.value());
        }
        r.fp = ofp::fingerprint(w, /*withActivations*/ false);
        return r;
    };
    struct Case { bool toroidal; int maxNeighbors; };
    for (const Case cs : {Case{false, 0}, Case{true, 7}}) {
        // blind, eye-only, eye-only with eyeCode 7, and the cloaks (8: no fish
        // query in eye-only mode; 16 + summed: no food query)
        for (int mode = 0; mode < 5; ++mode) {
            static const int kCode[5] = {0, 0, kEyeCodeAll, kEyeCodeNoFish, kEyeCodeNoFood | kEyeCodeSummed};
            const int eye = mode ? 1 : 0, code = kCode[mode];
            const Run lab = run(eye, 0, cs.toroidal, cs.maxNeighbors, code);
            const Run only = run(eye, 1, cs.toroidal, cs.maxNeighbors, code);
            static const char* kName[5] = {"blind", "eye-only", "eye-only (eyeCode 7)", "eye-only (eyeCode 8)",
                                           "eye-only (eyeCode 20)"};
            const char* name = kName[mode];
            t.expect(only.fp.ctr == lab.fp.ctr && only.fp.fish == lab.fp.fish && only.fp.food == lab.fp.food &&
                         only.fp.pred == lab.fp.pred && only.fp.sig == lab.fp.sig && only.fp.rng == lab.fp.rng,
                     "%s (toroidal %d, topo %d) changed an unwired world (fish %016llx vs %016llx, rng %016llx vs %016llx)",
                     name, cs.toroidal, cs.maxNeighbors, (unsigned long long)only.fp.fish,
                     (unsigned long long)lab.fp.fish, (unsigned long long)only.fp.rng, (unsigned long long)lab.fp.rng);
            t.expect(only.labeledNonZero == 0, "%s: %ld labeled inputs not 0", name, only.labeledNonZero);
            t.expect(lab.labeledNonZero > lab.fishSteps, "labels on but the labeled inputs are nearly all 0 (%ld)",
                     lab.labeledNonZero);
            t.expect(only.kept == lab.kept && only.fishSteps == lab.fishSteps && only.fishSteps > 100000,
                     "%s (toroidal %d, topo %d): a kept / eye input differs from the labeled run's", name,
                     cs.toroidal, cs.maxNeighbors);
        }
    }
    t.note("23 labeled inputs 0 in eye-only and blind; kept + eye inputs bit-identical to the labeled runs"
           " (eyeCode 0, 7, 8, 20)");
}

// OceanConfig::eyeCode (bit 0 faded contrast, bit 1 opponent pairs, bit 2
// summed sectors; the cloaks bit 3 no fish, bit 4 no food). (1) A hand-built
// scene with several objects per sector, for every code 0..31 (and seven codes
// in eye-only mode): the 18 inputs bit for bit
// against the definitions, computed here the same way. The engine visits fish
// (grid order), then food (grid order), then predators (index order); float
// sums depend on order, so every sector holds at most two objects of a group
// whose order this test does not fix, and only as its first terms (a + b ==
// b + a), plus objects of later groups one at a time or in index order.
// (2) Faded contrast is 0 at R. (3) Ranges in populated worlds. (4) Validity.
void testEyeCode() {
    Test t("eye_code");
    const float R = 100.0f;   // applyOceanDefaults' perceptionRadius
    const Vec2 P = {600.0f, 500.0f};
    const float z = 120.0f;
    enum { kFish, kFood, kPred };
    struct Obj { int type; float dx, dy, dz, bodySize; int sector; };
    // Listed in the engine's group order (fish, food, predators by index).
    const Obj objs[] = {
        {kFish, 60, 0, 0, 1.0f, 0},   {kFish, 45, 10, 5, 0.8f, 0},   // ahead: 2 fish,
        {kFish, 5, -40, 0, 1.5f, 2},                                  // left
        {kFish, 10, 35, -5, 1.2f, 3},                                 // right
        {kFish, 0, 0, -25, 1.0f, 4},                                  // up
        {kFish, 2, 2, 30, 1.0f, 5},                                   // down
        {kFish, 0, 0, 101, 1.0f, -1},                                 // beyond R
        {kFood, 30, 0, 0, 0, 0},                                      // ahead: + 1 food
        {kFood, -70, 5, 0, 0, 1},     {kFood, -20, -3, 10, 0, 1},     // behind: 2 food
        {kFood, 0, -20, 0, 0, 2},                                     // left: fish + food
        {kFood, 3, 2, -60, 0, 4},                                     // up: fish + food
        {kFood, 101, 0, 0, 0, -1},                                    // beyond R
        {kPred, 85, -20, 0, 0, 0},                                    // ahead: + 1 predator
        {kPred, -90, 0, 10, 0, 1},                                    // behind: + 1 predator
        {kPred, 0, 70, 0, 0, 3},                                      // right: fish + predator
        {kPred, 0, 0, 40, 0, 5},      {kPred, 5, -5, 90, 0, 5},       // down: fish + 2 predators
    };
    const int nObj = (int)(sizeof objs / sizeof objs[0]);
    // Build the scene; returns the viewer's index.
    auto build = [&](OceanWorld& w, int code, int eyeOnly) {
        OceanConfig oc;
        oc.eye = 1;
        oc.eyeCode = code;
        oc.eyeOnly = eyeOnly;
        initQuiet(w, 66, 240.0f, oc, /*capture*/ true);
        const int v = addFish(w, P, z, {}, 0.5f);
        w.creatures[v].vel = {1.0f, 0.0f};
        for (const Obj& o : objs) {
            const Vec2 pos = {P.x + o.dx, P.y + o.dy};
            const float oz = z + o.dz;
            if (o.type == kFish) {
                const int k = addFish(w, pos, oz, {}, 0.5f);
                w.creatures[k].bodySize = o.bodySize;
            } else if (o.type == kFood) {
                OceanFood f;
                f.pos = pos;
                f.depth = oz;
                f.eyeCon = ocean::eyeContrast(ocean::kEyeFoodBright, oz);
                w.food.push_back(f);
            } else {
                OceanPredator p;
                p.pos = pos;
                p.vel = {1.0f, 0.0f};
                p.depth = oz;
                p.digestTimer = 1e9f;
                w.predators.push_back(p);
            }
        }
        return v;
    };
    // The expected 18 inputs for a code, from the definitions.
    auto expected = [&](int code, float out[ocean::kEyeInputs]) {
        float nd2[6], nsize[6], ncon[6], sp[6] = {}, ss[6] = {}, sc[6] = {};
        for (int k = 0; k < 6; ++k) { nd2[k] = std::numeric_limits<float>::infinity(); nsize[k] = ncon[k] = 0.0f; }
        for (const Obj& o : objs) {
            // The cloaks: that kind is not binned at all (bits 3 / 4).
            if ((code & kEyeCodeNoFish) && o.type == kFish) continue;
            if ((code & kEyeCodeNoFood) && o.type == kFood) continue;
            const Vec2 pos = {P.x + o.dx, P.y + o.dy};
            const float oz = z + o.dz;
            const float dx = pos.x - P.x, dy = pos.y - P.y, dz = oz - z;
            const float d2 = dx * dx + dy * dy + dz * dz;
            if (d2 > R * R) { t.expect(o.sector < 0, "object (%g, %g, %g) is beyond R", o.dx, o.dy, o.dz); continue; }
            // The sector rule (ahead +x, right +y, down +depth), checked against the plan.
            const float a = std::abs(dx), b = std::abs(dy), c = std::abs(dz);
            const int k = (a >= b && a >= c) ? (dx >= 0.0f ? 0 : 1) : (b >= c) ? (dy <= 0.0f ? 2 : 3) : (dz <= 0.0f ? 4 : 5);
            t.expect(k == o.sector, "object (%g, %g, %g) falls in sector %d, planned %d", o.dx, o.dy, o.dz, k, o.sector);
            const float s = (o.type == kFish) ? ocean::kEyeFishLen * o.bodySize
                          : (o.type == kFood) ? ocean::kEyeFoodSize : ocean::kEyePredSize;
            const float con = ocean::eyeContrast(o.type == kFish ? ocean::kEyeFishBright
                                                 : o.type == kFood ? ocean::kEyeFoodBright : ocean::kEyePredBright, oz);
            if (d2 < nd2[k]) { nd2[k] = d2; nsize[k] = s; ncon[k] = con; }
            const float d = std::sqrt(d2), p = 1.0f - d / R;
            sp[k] += p;
            ss[k] += s / (s + d);
            sc[k] += p * con;
        }
        auto q = [](float x) { return x / (1.0f + std::abs(x)); };
        for (int k = 0; k < 6; ++k) {
            float* e = out + 3 * k;
            if (code & kEyeCodeSummed) { e[0] = q(sp[k]); e[1] = q(ss[k]); e[2] = q(sc[k]); continue; }
            if (!(nd2[k] <= R * R)) { e[0] = e[1] = e[2] = 0.0f; continue; }
            const float d = std::sqrt(nd2[k]);
            e[0] = 1.0f - d / R;
            e[1] = nsize[k] / (nsize[k] + d);
            e[2] = (code & kEyeCodeFaded) ? e[0] * ncon[k] : ncon[k];
        }
        if (code & kEyeCodeOpponent)
            for (int pr : {2, 4})
                for (int f = 0; f < 3; ++f) {
                    const float lo = out[3 * pr + f], hi = out[3 * pr + 3 + f];
                    out[3 * pr + f] = lo + hi;
                    out[3 * pr + 3 + f] = hi - lo;
                }
    };
    static const char* kSec[] = {"ahead", "behind", "left", "right", "up", "down"};
    std::vector<float> rest0;   // code 0's non-eye inputs
    float got7[ocean::kEyeInputs] = {}, got0[ocean::kEyeInputs] = {}, gotNF[ocean::kEyeInputs] = {},
          gotND[ocean::kEyeInputs] = {}, got24[ocean::kEyeInputs] = {};
    struct V { int code, eyeOnly; };
    std::vector<V> vs;
    for (int c = 0; c <= kEyeCodeMax; ++c) vs.push_back({c, 0});   // every encoding x cloak
    for (int c : {kEyeCodeSummed, kEyeCodeAll, kEyeCodeNoFish, kEyeCodeNoFood, kEyeCodeNoFish | kEyeCodeSummed,
                  kEyeCodeNoFood | kEyeCodeAll, kEyeCodeCloaks | kEyeCodeOpponent})
        vs.push_back({c, 1});   // eye-only: the cloaked kind's query is skipped
    for (const V& vv : vs) {
        OceanWorld w;
        const int v = build(w, vv.code, vv.eyeOnly);
        t.expect((int)w.creatures.size() == 1 + 7 && (int)w.food.size() + (int)w.predators.size() == nObj - 7,
                 "scene has %zu fish, %zu food, %zu predators", w.creatures.size(), w.food.size(), w.predators.size());
        w.update(0.016f);
        const float* S = w.creatures[v].lastSensors;
        float want[ocean::kEyeInputs];
        expected(vv.code, want);
        for (int k = 0; k < ocean::kEyeSectors; ++k)
            for (int f = 0; f < 3; ++f) {
                const float g = S[ocean::kEyeFirst + 3 * k + f];
                t.expect(g == want[3 * k + f] && finite(g), "eyeCode %d eyeOnly %d: %s feature %d = %.9g, expected %.9g",
                         vv.code, vv.eyeOnly, kSec[k], f, g, want[3 * k + f]);
            }
        if (vv.eyeOnly) continue;
        std::vector<float> rest;
        for (int k = 0; k < NUM_SENSES; ++k) if (!ocean::isEyeSense(k)) rest.push_back(S[k]);
        if (vv.code == 0) { rest0 = rest; std::memcpy(got0, S + ocean::kEyeFirst, sizeof got0); }
        else t.expect(rest == rest0, "eyeCode %d changed a non-eye input", vv.code);   // the labels see every kind
        if (vv.code == kEyeCodeAll) std::memcpy(got7, S + ocean::kEyeFirst, sizeof got7);
        if (vv.code == kEyeCodeNoFish) std::memcpy(gotNF, S + ocean::kEyeFirst, sizeof gotNF);
        if (vv.code == kEyeCodeNoFood) std::memcpy(gotND, S + ocean::kEyeFirst, sizeof gotND);
        if (vv.code == kEyeCodeCloaks) std::memcpy(got24, S + ocean::kEyeFirst, sizeof got24);
    }
    t.note("scene, code 0: ahead %.4f/%.4f/%.4f left %.4f/%.4f/%.4f right %.4f/%.4f/%.4f", got0[0], got0[1], got0[2],
           got0[6], got0[7], got0[8], got0[9], got0[10], got0[11]);
    t.note("scene, code 7: ahead %.4f/%.4f/%.4f left+right %.4f/%.4f/%.4f right-left %.4f/%.4f/%.4f", got7[0],
           got7[1], got7[2], got7[6], got7[7], got7[8], got7[9], got7[10], got7[11]);
    // The cloaks, by name (besides the model above): a cloaked kind neither
    // shows nor hides. Code 8: the fish nearest up (25 above) gives way to the
    // food 60 above, the fish right / down to the predators behind them;
    // code 16: the food ahead (30) gives way to the fish (46), both food items
    // behind to the predator; code 24: only predators.
    {
        const float foodUp = ocean::eyeContrast(ocean::kEyeFoodBright, z - 60.0f);
        const float predCon = ocean::eyeContrast(ocean::kEyePredBright, z), fishCon = ocean::eyeContrast(ocean::kEyeFishBright, z);
        const float predBehindCon = ocean::eyeContrast(ocean::kEyePredBright, z + 10.0f);
        t.expect(gotNF[14] == foodUp && got0[14] != foodUp && gotNF[11] == predCon && gotNF[0] == got0[0],
                 "code 8: up CON %.6g (food %.6g), right CON %.6g (predator %.6g)", gotNF[14], foodUp, gotNF[11], predCon);
        t.expect(gotND[2] != got0[2] && gotND[5] == predBehindCon,
                 "code 16: ahead CON %.6g, behind CON %.6g (predator %.6g)", gotND[2], gotND[5], predBehindCon);
        t.expect(std::abs(gotND[2] - fishCon) < 0.05f, "code 16: ahead CON %.6g is not a fish's (%.6g)", gotND[2], fishCon);
        bool onlyPred = true;
        for (int k = 0; k < ocean::kEyeSectors; ++k) {
            const float cn = got24[3 * k + 2];
            const bool empty = got24[3 * k] == 0.0f && got24[3 * k + 1] == 0.0f && cn == 0.0f;
            onlyPred &= empty || cn < 0.0f;   // predators are dark: CON < 0 at these depths
        }
        t.expect(onlyPred && got24[6] == 0.0f && got24[12] == 0.0f, "code 24: a sector shows a fish or food item");
        t.note("cloaks: code 8 up CON %.4f (food) vs code 0 %.4f (fish); code 16 behind CON %.4f (predator); "
               "code 24 left/up empty", gotNF[14], got0[14], gotND[5]);
    }

    // (2) Faded contrast fades to exactly 0 at R: one food item 100 ahead.
    for (int code : {0, kEyeCodeFaded, kEyeCodeSummed}) {
        OceanConfig oc;
        oc.eye = 1;
        oc.eyeCode = code;
        OceanWorld w;
        initQuiet(w, 67, 240.0f, oc, /*capture*/ true);
        const int v = addFish(w, P, z, {}, 0.5f);
        w.creatures[v].vel = {1.0f, 0.0f};
        OceanFood f;
        f.pos = {P.x + R, P.y};
        f.depth = z;
        f.eyeCon = ocean::eyeContrast(ocean::kEyeFoodBright, z);
        w.food.push_back(f);
        w.update(0.016f);
        const float* S = w.creatures[v].lastSensors;
        const float size = (code & kEyeCodeSummed) ? ocean::kEyeFoodSize / (ocean::kEyeFoodSize + R) /
                                                         (1.0f + ocean::kEyeFoodSize / (ocean::kEyeFoodSize + R))
                                                   : ocean::kEyeFoodSize / (ocean::kEyeFoodSize + R);
        t.expect(S[EYE_AHEAD_PROX] == 0.0f && S[EYE_AHEAD_SIZE] == size &&
                     S[EYE_AHEAD_CON] == (code ? 0.0f : f.eyeCon),
                 "eyeCode %d, food at R: %.9g/%.9g/%.9g", code, S[EYE_AHEAD_PROX], S[EYE_AHEAD_SIZE], S[EYE_AHEAD_CON]);
    }

    // (3) Populated worlds (fish wired at random, so behaviour differs by code):
    // every input finite and in its range, fish-step by fish-step.
    {
        long fishSteps = 0, occupied = 0, slots = 0;
        for (int code : {kEyeCodeSummed, kEyeCodeAll, kEyeCodeFaded | kEyeCodeOpponent}) {
            OceanWorld w;
            std::string err;
            char cfg[200];
            std::snprintf(cfg, sizeof cfg,
                          R"({"eye":1,"eyeCode":%d,"maxNeighbors":7,"toroidal":true,"predatorCount":6,"predatorEconomy":true,"foodPatches":3})",
                          code);
            if (!t.expect(ofp::initWorld(w, 68 + code, 1920, 1080, 240.0f, 500, cfg, err), "init: %s", err.c_str()))
                continue;
            w.cfg.captureActivations = true;
            const bool opp = code & kEyeCodeOpponent, sum = code & kEyeCodeSummed;
            for (int s = 0; s < 200; ++s) {
                w.update(0.016f);
                for (const Fish& c : w.creatures) {
                    if (c.age <= 0.0f) continue;
                    ++fishSteps;
                    const float* E = c.lastSensors + ocean::kEyeFirst;
                    for (int k = 0; k < ocean::kEyeSectors; ++k) {
                        ++slots;
                        const float p = E[3 * k], sz = E[3 * k + 1], cn = E[3 * k + 2];
                        occupied += (p != 0.0f || sz != 0.0f || cn != 0.0f);
                        bool ok = finite(p) && finite(sz) && finite(cn);
                        const bool sumSlot = opp && (k == 2 || k == 4), diffSlot = opp && (k == 3 || k == 5);
                        if (sumSlot) ok &= p >= 0.0f && p <= 2.0f && sz >= 0.0f && sz <= 2.0f && std::abs(cn) <= 2.0f;
                        else if (diffSlot) ok &= std::abs(p) <= 1.0f && std::abs(sz) <= 1.0f && std::abs(cn) <= 2.0f;
                        else ok &= p >= 0.0f && p <= 1.0f && sz >= 0.0f && sz <= 1.0f && std::abs(cn) <= 1.0f;
                        if (sum) ok &= (sumSlot ? p < 2.0f && sz < 2.0f : std::abs(p) < 1.0f && std::abs(sz) < 1.0f) &&
                                       (opp ? std::abs(cn) < 2.0f : std::abs(cn) < 1.0f);
                        t.expect(ok, "eyeCode %d sector %d out of range: %.9g %.9g %.9g", code, k, p, sz, cn);
                    }
                }
            }
        }
        t.expect(fishSteps > 100000 && occupied > slots / 10, "too little to test: %ld fish-steps, %ld of %ld sectors",
                 fishSteps, occupied, slots);
        t.note("populated, eyeCode 4 / 7 / 3: %ld fish-steps, %.1f%% of sector slots non-zero, all in range", fishSteps,
               slots ? 100.0 * occupied / slots : 0.0);
    }

    // (4) Validity: 0..31 in the eye build; live through oc_set_param.
    {
        OceanConfig oc;
        bool ok = oceanConfigValid(oc) && oc.eyeCode == 0 && kEyeCodeMax == 31;
        for (int c = 0; c <= kEyeCodeMax; ++c) { oc.eyeCode = c; ok &= oceanConfigValid(oc); }
        t.expect(ok, "an eyeCode in 0..31 refused (or the default is not 0)");
        for (int c : {-1, 32, 64, 1 << 30}) { oc.eyeCode = c; t.expect(!oceanConfigValid(oc), "eyeCode %d accepted", c); }
#ifndef OCEAN_TESTS_NO_SHIM
        t.expect(oc_init(69, 1920, 1080, 240.0, 50, R"({"eye":1,"eyeCode":7})") == 1, "oc_init eyeCode 7: %s",
                 oc_last_error());
        t.expect(g_world && g_world->ocfg.eyeCode == 7, "eyeCode not stored");
        t.expect(oc_set_param("eyeCode", 5.0) == 1 && g_world->ocfg.eyeCode == 5, "oc_set_param eyeCode 5: %s",
                 oc_last_error());
        t.expect(oc_set_param("eyeCode", 24.0) == 1 && g_world->ocfg.eyeCode == 24, "oc_set_param eyeCode 24: %s",
                 oc_last_error());
        t.expect(oc_set_param("eyeCode", 32.0) == 0 && g_world->ocfg.eyeCode == 24, "oc_set_param eyeCode 32 accepted");
        t.note("oc_set_param(eyeCode, 32): %s", oc_last_error());
        t.expect(oc_init(69, 1920, 1080, 240.0, 50, R"({"eye":1,"eyeCode":33})") == 0, "oc_init eyeCode 33 accepted");
        t.expect(oc_init(69, 1920, 1080, 240.0, 50, R"({"eye":1,"eyeCode":16})") == 1 && g_world->ocfg.eyeCode == 16,
                 "oc_init eyeCode 16: %s", oc_last_error());
#endif
    }
}
#else
// The plain Ocean build has no eye: the key is accepted only as 0.
void testEye() {
    Test t("eye(absent)");
    OceanConfig oc;
    t.expect(oceanConfigValid(oc), "default config refused");
    oc.eye = 1;
    t.expect(!oceanConfigValid(oc), "eye = 1 accepted by a build without the eye");
    oc.eye = 0;
    oc.eyeOnly = 1;
    t.expect(!oceanConfigValid(oc), "eyeOnly = 1 accepted by a build without the eye");
    oc.eyeOnly = 0;
    for (int c = 1; c <= kEyeCodeMax; ++c) { oc.eyeCode = c; t.expect(!oceanConfigValid(oc), "eyeCode = %d accepted by a build without the eye", c); }
#ifndef OCEAN_TESTS_NO_SHIM
    t.expect(oc_init(69, 1920, 1080, 240.0, 50, R"({"eyeCode":1})") == 0, "oc_init eyeCode 1 accepted without the eye");
    t.expect(oc_init(69, 1920, 1080, 240.0, 50, nullptr) == 1 && oc_set_param("eyeCode", 4.0) == 0,
             "oc_set_param eyeCode 4 accepted without the eye");
#endif
    t.expect(NUM_SENSES == 46, "NUM_SENSES %d, expected 46", (int)NUM_SENSES);
}
void testEyeOnly() {}
void testEyeCode() {}
#endif

// OceanConfig::foodLife: uneaten food is removed foodLife seconds after it appeared.
void testFoodLife() {
    Test t("food_life");
    {
        OceanConfig oc;
        t.expect(oceanConfigValid(oc) && oc.foodLife == 0.0f, "default foodLife %g (or refused)", oc.foodLife);
        oc.foodLife = 7.5f;
        t.expect(oceanConfigValid(oc), "foodLife 7.5 refused");
        oc.foodLife = -1.0f;
        t.expect(!oceanConfigValid(oc), "foodLife -1 accepted");
        oc.foodLife = std::numeric_limits<float>::infinity();
        t.expect(!oceanConfigValid(oc), "foodLife inf accepted");
        // The range ends where a float age still advances accurately by dt
        // (kOceanMaxFoodLife); 1e6 used to be accepted, and from 2^19 s an age
        // stops growing (age + dt == age): such an item never expired.
        oc.foodLife = kOceanMaxFoodLife;
        t.expect(oceanConfigValid(oc) && kOceanMaxFoodLife == 3600.0f, "foodLife %g (the range end) refused", oc.foodLife);
        for (float v : {std::nextafter(kOceanMaxFoodLife, 1e9f), 3601.0f, 524288.0f, 1e6f}) {
            oc.foodLife = v;
            t.expect(!oceanConfigValid(oc), "foodLife %.9g accepted", (double)v);
        }
    }
    // At the range end every age still advances each step: an item placed at
    // foodLife - 0.0625 goes on the fourth step (an add there is 0.01611 s:
    // 0.0644 in four), and items at 2048 and 3000 age by a step's worth.
    {
        OceanConfig oc;
        oc.foodLife = kOceanMaxFoodLife;
        OceanWorld w;
        initQuiet(w, 31, 240.0f, oc);
        const float ages[] = {kOceanMaxFoodLife - 0.0625f, 2048.0f, 3000.0f};
        for (float a : ages) {
            OceanFood f;
            f.pos = {300.0f + a / 10.0f, 500.0f};
            f.depth = 120.0f;
            f.age = a;
            w.food.push_back(f);
        }
        int goneAt = -1;
        for (int s = 1; s <= 4; ++s) {
            w.update(0.016f);
            if (goneAt < 0 && w.food.size() == 2) goneAt = s;
        }
        t.expect(goneAt == 4 && w.totalFoodExpired == 1, "foodLife %g: an item at %.9g went at step %d (expected 4), %lld expired",
                 (double)kOceanMaxFoodLife, (double)ages[0], goneAt, w.totalFoodExpired);
        const bool aged = w.food.size() == 2 && w.food[0].age > ages[1] + 0.06f && w.food[0].age < ages[1] + 0.07f &&
                          w.food[1].age > ages[2] + 0.06f && w.food[1].age < ages[2] + 0.07f;
        t.expect(aged, "foodLife %g: the items at 2048 / 3000 did not age by ~0.064 s in 4 steps", (double)kOceanMaxFoodLife);
    }
    // Hand-placed items in a quiet world (no fish, no spawn): with foodLife 1 each one
    // goes on the first step its age reaches 1 — an item placed at age a lasts
    // ceil((1 - a) / dt) steps, within one step of float rounding; off, nothing goes.
    const float dt = 0.016f;
    for (int on = 0; on < 2; ++on) {
        OceanConfig oc;
        oc.foodLife = on ? 1.0f : 0.0f;
        OceanWorld w;
        initQuiet(w, 26, 240.0f, oc);
        const float ages[] = {0.0f, 0.25f, 0.5f, 0.9f, 0.99f};
        for (float a : ages) {
            OceanFood f;
            f.pos = {300.0f + 1000.0f * a, 500.0f};
            f.depth = 120.0f;
            f.age = a;
            w.food.push_back(f);
        }
        int goneAt[5] = {-1, -1, -1, -1, -1};
        for (int s = 1; s <= 100; ++s) {
            std::vector<float> xs;
            for (const OceanFood& f : w.food) xs.push_back(f.pos.x);
            w.update(dt);
            for (int k = 0; k < 5; ++k) {
                const float x = 300.0f + 1000.0f * ages[k];
                const bool here = std::any_of(w.food.begin(), w.food.end(), [&](const OceanFood& f) { return f.pos.x == x; });
                if (!here && goneAt[k] < 0) goneAt[k] = s;
            }
        }
        for (int k = 0; k < 5; ++k) {
            if (!on) { t.expect(goneAt[k] < 0, "foodLife 0: item %d vanished at step %d", k, goneAt[k]); continue; }
            const int expect = (int)std::ceil((1.0f - ages[k]) / dt);
            t.expect(goneAt[k] >= expect - 1 && goneAt[k] <= expect + 1, "foodLife 1: item aged %.2f went at step %d, expected ~%d",
                     ages[k], goneAt[k], expect);
        }
        if (on) t.expect(w.totalFoodExpired == 5, "totalFoodExpired %lld, expected 5", w.totalFoodExpired);
        else    for (const OceanFood& f : w.food) t.expect(f.age == ages[&f - w.food.data()], "foodLife 0: an age changed");
    }
    // The first stock's ages are spread over [0, foodLife); spawned items start at 0.
    {
        OceanWorld w;
        std::string err;
        t.expect(ofp::initWorld(w, 27, 1920, 1080, 240.0f, 0,
                                R"({"foodLife":8,"targetFood":2000,"foodSpawnBase":3,"foodSpawnAmp":0,"minPopulation":0})", err),
                 "init refused: %s", err.c_str());
        bool spread = w.food.size() == 2000;
        for (std::size_t i = 0; i < w.food.size(); ++i)
            spread &= w.food[i].age == 8.0f * ((float)i / 2000.0f);
        t.expect(spread, "initial ages not spread evenly over [0, 8)");
        w.update(dt);
        t.expect(w.food.back().age == 0.0f, "a newly spawned item's age is %g", w.food.back().age);
        // Steady state with no fish: 3 items a step, each lasting 8 / 0.016 = 500 steps
        // (one more if the float ages fall just short): a stock of 1500..1503, the
        // whole first stock expired.
        for (int s = 0; s < 2000; ++s) w.update(dt);
        t.note("no fish, foodLife 8, 3 items/step: stock %zu after 2001 steps, %lld expired", w.food.size(),
               w.totalFoodExpired);
        t.expect(w.food.size() >= 1500 && w.food.size() <= 1503, "stock %zu, expected 1500..1503", w.food.size());
        t.expect(w.totalFoodExpired >= 2000, "only %lld expired (the first stock alone is 2000)", w.totalFoodExpired);
    }
    // The spawn cap (targetFood·2) counts live items: what expires frees its
    // place in the same step's spawn. No fish, targetFood 1 (cap 2), 2 items a
    // step, each lasting one step (foodLife = dt): 2 live items after every
    // step (the cap used to count the expired items until the end-of-step
    // erase: one replacement a step, a stock of 1). Off: the cap holds 2.
    for (int on = 0; on < 2; ++on) {
        OceanWorld w;
        std::string err;
        const char* cfg = on ? R"({"minPopulation":0,"targetFood":1,"foodSpawnBase":2,"foodSpawnAmp":0,"foodLife":0.016})"
                             : R"({"minPopulation":0,"targetFood":1,"foodSpawnBase":2,"foodSpawnAmp":0})";
        if (!t.expect(ofp::initWorld(w, 30, 1920, 1080, 240.0f, 0, cfg, err), "%s refused: %s", cfg, err.c_str())) continue;
        int wrongAt = -1;
        std::size_t wrongStock = 0;
        for (int s = 1; s <= 50; ++s) {
            w.update(dt);
            const bool allLive = std::all_of(w.food.begin(), w.food.end(), [](const OceanFood& f) { return f.alive; });
            if ((w.food.size() != 2 || !allLive) && wrongAt < 0) { wrongAt = s; wrongStock = w.food.size(); }
        }
        t.expect(wrongAt < 0, "foodLife %s, cap 2, 2 items/step: stock %zu after step %d, expected 2 live items",
                 on ? "0.016" : "off", wrongStock, wrongAt);
        const long long wantExpired = on ? 1 + 2 * 49 : 0;   // the first item, then both every step
        t.expect(w.totalFoodExpired == wantExpired, "foodLife %s: %lld expired in 50 steps, expected %lld",
                 on ? "0.016" : "off", w.totalFoodExpired, wantExpired);
    }
    // Draws do not depend on foodLife (spawn cap not reached).
    {
        OceanWorld a, b;
        std::string err;
        ofp::initWorld(a, 28, 1920, 1080, 240.0f, 0, R"({"targetFood":10000,"minPopulation":0})", err);
        ofp::initWorld(b, 28, 1920, 1080, 240.0f, 0, R"({"targetFood":10000,"minPopulation":0,"foodLife":2})", err);
        // initWorld seeds the global rng; run a then b from the same post-init state.
        RandomGen r0;
        r0.seed(99);
        rng = r0;
        for (int s = 0; s < 300; ++s) a.update(dt);
        const RandomGen ra = rng;
        rng = r0;
        for (int s = 0; s < 300; ++s) b.update(dt);
        t.expect(sameEngine(ra, rng), "foodLife changed the draws in 300 steps");
    }
    // Switched off live, the ages stay (and matter if it comes back on): the
    // fingerprint must still see them.
    {
        OceanWorld w;
        std::string err;
        ofp::initWorld(w, 29, 1920, 1080, 240.0f, 0, R"({"foodLife":8,"targetFood":300,"minPopulation":0})", err);
        for (int s = 0; s < 20; ++s) w.update(dt);
        w.ocfg.foodLife = 0.0f;
        OceanWorld z = w;
        for (OceanFood& f : z.food) f.age = 0.0f;
        t.expect(ofp::fingerprint(w).food != ofp::fingerprint(z).food,
                 "foodLife switched off: the kept ages are invisible to the fingerprint");
    }
}

// OceanWorld::totalNonFiniteRemoved: the non-finite floats an object held when
// the end-of-step erase removed it (the driver adds them to its per-step scan;
// an object that died of an infinity within a step used to leave no trace).
// The Codex audit's fixture, validation bypassed (moveCost 1e38 is refused
// now): one fish at speed 30, its step cost inf, reserves -inf; it starves and
// the world it leaves is finite. Likewise a predator (predatorMoveCost 1e38)
// and a food item (size inf, eaten). Finite deaths count nothing; the counter
// is not hashed, and init resets it.
void testRemovedNonFinite() {
    Test t("nonfinite_rm");
    const float inf = std::numeric_limits<float>::infinity();
    {   // a fish
        OceanWorld w;
        initQuiet(w, 1501, 240.0f, OceanConfig{});
        w.cfg.minSpeed = w.cfg.maxSpeed = 30.0f;
        w.cfg.moveCost = 1e38f;
        addFish(w, {600.0f, 500.0f}, 120.0f, {}, 0.5f);
        w.update(0.016f);
        t.expect(w.creatures.empty() && w.totalDeathsStarvation == 1 && ofp::countNonFinite(w) == 0 &&
                     w.totalNonFiniteRemoved >= 1,
                 "moveCost 1e38: pop %zu, %lld starved, %ld non-finite in the world, %lld in removed objects (want 0, 1, 0, >= 1)",
                 w.creatures.size(), w.totalDeathsStarvation, ofp::countNonFinite(w), w.totalNonFiniteRemoved);
    }
    {   // a predator
        OceanWorld w;
        initQuiet(w, 1502, 240.0f, OceanConfig{});
        w.cfg.predatorEconomy = true;
        w.cfg.predatorMoveCost = 1e38f;
        OceanPredator p;
        p.pos = {600.0f, 500.0f};
        p.vel = {1.0f, 0.0f};
        p.depth = 120.0f;
        p.energy = 30.0f;
        w.predators.push_back(p);
        w.update(0.016f);
        t.expect(w.predators.empty() && w.totalPredatorDeathsStarvation == 1 && ofp::countNonFinite(w) == 0 &&
                     w.totalNonFiniteRemoved >= 1,
                 "predatorMoveCost 1e38: %zu predators, %lld starved, %ld / %lld non-finite (want 0, 1, 0, >= 1)",
                 w.predators.size(), w.totalPredatorDeathsStarvation, ofp::countNonFinite(w), w.totalNonFiniteRemoved);
    }
    {   // a food item of infinite size, eaten
        OceanWorld w;
        initQuiet(w, 1503, 240.0f, OceanConfig{});
        addFish(w, {600.0f, 500.0f}, 120.0f, {}, 0.5f);
        OceanFood f;
        f.pos = {600.0f, 500.0f};
        f.depth = 120.0f;
        f.size = inf;
        w.food.push_back(f);
        w.update(0.016f);
        t.expect(w.food.empty() && w.totalFoodEaten == 1 && ofp::countNonFinite(w) == 0 && w.totalNonFiniteRemoved == 1,
                 "food of size inf: %zu left, %lld eaten, %ld / %lld non-finite (want 0, 1, 0, 1)", w.food.size(),
                 w.totalFoodEaten, ofp::countNonFinite(w), w.totalNonFiniteRemoved);
    }
    {   // finite deaths (starvation, predation, predator economy) count nothing
        OceanWorld w;
        std::string err;
        if (t.expect(ofp::initWorld(w, 1504, 1920, 1080, 240.0f, 300,
                                    R"({"predatorCount":4,"predatorEconomy":true,"predatorMinPopulation":2,"metabolicRate":3})", err),
                     "init: %s", err.c_str())) {
            for (int s = 0; s < 600; ++s) w.update(0.016f);
            t.expect(w.totalDeaths > 0 && w.totalNonFiniteRemoved == 0, "%lld deaths, %lld non-finite floats removed (want > 0, 0)",
                     w.totalDeaths, w.totalNonFiniteRemoved);
            t.note("600 steps, %lld deaths (%lld starved, %lld eaten), %lld food eaten: nothing non-finite removed", w.totalDeaths,
                   w.totalDeathsStarvation, w.totalDeathsPredation, w.totalFoodEaten);
            const ofp::Fingerprint fp = ofp::fingerprint(w);
            w.totalNonFiniteRemoved = 7;
            t.expect(ofp::fingerprint(w) == fp, "totalNonFiniteRemoved changed the fingerprint (it is a diagnostic)");
            ofp::initWorld(w, 1504, 1920, 1080, 240.0f, 10, nullptr, err);
            t.expect(w.totalNonFiniteRemoved == 0, "init kept totalNonFiniteRemoved %lld", w.totalNonFiniteRemoved);
        }
    }
}

std::vector<ofp::Fingerprint> runPrints(unsigned seed, const char* cfg, int pop, int steps, int every) {
    std::vector<ofp::Fingerprint> out;
    OceanWorld w;
    std::string err;
    if (!ofp::initWorld(w, seed, 1920, 1080, 240.0f, pop, cfg, err)) return out;
    out.push_back(ofp::fingerprint(w));
    for (int s = 1; s <= steps; ++s) {
        w.update(0.016f);
        if (s % every == 0) out.push_back(ofp::fingerprint(w));
    }
    return out;
}

void testReproducible() {
    Test t("reproducible");
    const char* cfgs[] = {nullptr,
                          R"({"predatorCount":5,"predatorEconomy":true,"predatorInheritance":true,"currentStrength":70,"foodDrift":true,"foodPatches":5,"foodDepthMode":1,"toroidal":true,"maxNeighbors":7,"bodyModel":true})"};
    for (const char* cfg : cfgs) {
        const auto a = runPrints(51, cfg, 300, 1000, 100);
        const auto b = runPrints(51, cfg, 300, 1000, 100);
        t.expect(a.size() == 11 && a.size() == b.size(), "fingerprint count %zu / %zu", a.size(), b.size());
        for (size_t i = 0; i < a.size() && i < b.size(); ++i)
            t.expect(a[i] == b[i], "cfg %s: same seed differs at print %zu", cfg ? "rich" : "default", i);
        const auto c = runPrints(52, cfg, 300, 0, 1);
        t.expect(!c.empty() && c[0].fish != a[0].fish && c[0].rng != a[0].rng, "another seed gave the same world");
    }
    // The hash sees a 1-ulp change in each section (and only that section),
    // including the private state the harness reads through ofp::peek.
    OceanWorld w;
    std::string err;
    ofp::initWorld(w, 53, 1920, 1080, 240.0f, 200,
                   R"({"predatorCount":2,"currentStrength":40,"foodPatches":3,"foodDepthMode":1})", err);
    for (int s = 0; s < 50; ++s) w.update(0.016f);
    const ofp::Fingerprint base = ofp::fingerprint(w);
    auto bump = [](float& f) { f = std::nextafter(f, 1e30f); };
    int bumps = 0;
    auto only = [&](const char* what, std::uint64_t ofp::Fingerprint::*field) {
        ++bumps;
        const ofp::Fingerprint p = ofp::fingerprint(w);
        bool othersSame = true;
        for (auto f : ofp::kSections)
            if (f != field) othersSame &= (p.*f == base.*f);
        t.expect(p.*field != base.*field && p.all != base.all && othersSame, "a 1-ulp change in %s: hash %s", what,
                 p.*field == base.*field ? "unchanged" : "changed other sections too");
    };
    using FP = ofp::Fingerprint;
    namespace pk = ofp::peek;
    { const float keep = w.creatures[7].depth; bump(w.creatures[7].depth); only("fish depth", &FP::fish); w.creatures[7].depth = keep; }
    { const float keep = w.creatures[3].bodyBuoy; bump(w.creatures[3].bodyBuoy); only("fish bodyBuoy", &FP::fish); w.creatures[3].bodyBuoy = keep; }
    { const float keep = w.creatures[5].body[4].y; bump(w.creatures[5].body[4].y); only("fish body trail", &FP::fish); w.creatures[5].body[4].y = keep; }
    { const float keep = w.food[11].depth; bump(w.food[11].depth); only("food depth", &FP::food); w.food[11].depth = keep; }
    // foodLife is off here: a kept (non-zero) age is still state (it counts again if foodLife comes back on)
    { const float keep = w.food[14].age; bump(w.food[14].age); only("a food age kept with foodLife off", &FP::food); w.food[14].age = keep; }
#ifdef EVO_OCEAN_EYE
    { const float keep = w.food[12].eyeCon; bump(w.food[12].eyeCon); only("food eyeCon", &FP::food); w.food[12].eyeCon = keep; }
    { long nf = ofp::countNonFinite(w); const float keep = w.food[13].eyeCon;
      w.food[13].eyeCon = std::numeric_limits<float>::infinity();
      t.expect(ofp::countNonFinite(w) == nf + 1, "a non-finite food eyeCon is not counted"); w.food[13].eyeCon = keep; }
    { const int keep = w.ocfg.eyeCode; w.ocfg.eyeCode = 5; only("eyeCode (0 -> 5)", &FP::cfg); w.ocfg.eyeCode = keep; }
    { const int keep = w.ocfg.eyeCode; w.ocfg.eyeCode = kEyeCodeNoFood; only("eyeCode (0 -> 16, a cloak)", &FP::cfg); w.ocfg.eyeCode = keep; }
#endif
    { long nf = ofp::countNonFinite(w); const float keep = w.food[13].age;
      w.food[13].age = std::numeric_limits<float>::quiet_NaN();
      t.expect(ofp::countNonFinite(w) == nf + 1, "a non-finite food age is not counted"); w.food[13].age = keep; }
    { const float keep = w.predators[1].pitch; bump(w.predators[1].pitch); only("predator pitch", &FP::pred); w.predators[1].pitch = keep; }
    { const float keep = w.ocfg.vDrag; bump(w.ocfg.vDrag); only("ocean config", &FP::cfg); w.ocfg.vDrag = keep; }
    { const int keep = w.ocfg.steerFrame; w.ocfg.steerFrame = 1; only("steerFrame (0 -> 1)", &FP::cfg); w.ocfg.steerFrame = keep; }
    {   // foodLife 0 -> a denormal: the config, and (foodLife > 0: the ages count) the food section
        const float keep = w.ocfg.foodLife;
        bump(w.ocfg.foodLife);
        const ofp::Fingerprint p = ofp::fingerprint(w);
        ++bumps;
        t.expect(p.cfg != base.cfg && p.food != base.food && p.fish == base.fish && p.ctr == base.ctr &&
                     p.pred == base.pred && p.sig == base.sig && p.cur == base.cur && p.geo == base.geo && p.rng == base.rng,
                 "foodLife 0 -> denormal: not exactly the cfg and food sections changed");
        w.ocfg.foodLife = keep;
    }
    { const float keep = w.cfg.moveCost; bump(w.cfg.moveCost); only("SimConfig moveCost (0 -> denormal)", &FP::cfg); w.cfg.moveCost = keep; }
    { const int keep = w.cfg.clusterEpoch; w.cfg.clusterEpoch++; only("clusterEpoch (no checkpoint key)", &FP::cfg); w.cfg.clusterEpoch = keep; }
    { const auto keep = w.nextId_; w.nextId_++; only("nextId_", &FP::ctr); w.nextId_ = keep; }
    { auto& t1 = ofp::field<pk::OwWaves>(w)[1]; const double keep = t1.phase; t1.phase = std::nextafter(keep, 10.0);
      only("a wave phase", &FP::ctr); t1.phase = keep; }
    { std::vector<std::uint8_t> g = w.signals.data(); const std::vector<std::uint8_t> keep = g; g[100] ^= 1;
      w.signals.restore(g); only("a pheromone byte", &FP::sig); w.signals.restore(keep); }
    {   // a vortex frequency (vortexState() index 5 = vortex 0's fx), centres kept
        CurrentField& cf = ofp::field<pk::OwCurrent>(w);
        const std::vector<float> keepV = cf.vortexState();
        const std::vector<Vec2> keepC = ofp::field<pk::CfCenters>(cf);
        std::vector<float> v = keepV;
        bump(v[5]);
        cf.restoreVortexState(v);
        ofp::field<pk::CfCenters>(cf) = keepC;
        only("a vortex frequency", &FP::cur);
        cf.restoreVortexState(keepV);
        ofp::field<pk::CfCenters>(cf) = keepC;
    }
    { float& c = ofp::field<pk::CfCore>(ofp::field<pk::OwCurrent>(w)); const float keep = c; bump(c); only("the eddy core", &FP::cur); c = keep; }
    { float& d = ofp::field<pk::OwPatchDepth>(w)[1]; const float keep = d; bump(d); only("a food-patch depth", &FP::geo); d = keep; }
    { float& x = ofp::field<pk::OwPatches>(w)[2].x; const float keep = x; bump(x); only("a food-patch centre", &FP::geo); x = keep; }
    { float& ic = ofp::field<pk::FgInvCell>(ofp::field<pk::OwFoodGrid>(w)); const float keep = ic; bump(ic);
      only("the food grid's cell size", &FP::geo); ic = keep; }
    { bool& tor = ofp::field<pk::SigToroidal>(w.signals); tor = !tor; only("the signal grid's wrap flag", &FP::geo); tor = !tor; }
    { int& wc = ofp::field<pk::SigWrapCols>(w.signals); ++wc; only("the signal grid's seam period", &FP::geo); --wc; }
    { const RandomGen keep = rng; rng.uint(); only("rng (one draw)", &FP::rng); rng = keep; }
    t.expect(ofp::fingerprint(w) == base, "restoring every bump did not restore the hash");
    t.note("%d single-value changes, each seen by its own section only", bumps);
}

// OceanWorld::radiusError (the shim's oc_init check): every radius must be
// finite, >= 0 and have a finite float square — every radius is used squared,
// and with perceptionRadius² = inf an empty eye sector read PROX = −inf. On
// top, every accepted config holds each radius <= 1e6 (oceanSimConfigError:
// SpatialGrid's int casts), so oc_init refuses 1.8e19 too and accepts 1e6.
void testRadii() {
    Test t("radii");
    struct Key { const char* name; float SimConfig::*field; };
    const Key keys[] = {
        {"perceptionRadius", &SimConfig::perceptionRadius}, {"interactRadius", &SimConfig::interactRadius},
        {"pickupRadius", &SimConfig::pickupRadius}, {"predatorPerception", &SimConfig::predatorPerception},
        {"predatorCaptureRadius", &SimConfig::predatorCaptureRadius},
    };
    const float big = std::nextafter(18446744073709551616.0f, 0.0f);   // the largest float below 2^64
    t.expect(std::isfinite(big * big) && !std::isfinite(18446744073709551616.0f * 18446744073709551616.0f),
             "2^64 is not the float square's overflow bound");
    for (const Key& k : keys) {
        SimConfig c;
        applyOceanDefaults(c);
        t.expect(OceanWorld::radiusError(c, 1920, 1080).empty(), "defaults refused");
        for (float bad : {1e20f, 18446744073709551616.0f, 1e38f, std::numeric_limits<float>::infinity(),
                          std::numeric_limits<float>::quiet_NaN(), -1.0f}) {
            c.*k.field = bad;
            const std::string e = OceanWorld::radiusError(c, 1920, 1080);
            t.expect(!e.empty() && e.find(k.name) == 0, "%s = %g accepted (or the error names another key: %s)",
                     k.name, (double)bad, e.c_str());
        }
        c.*k.field = big;   // non-toroidal: no size bound
        t.expect(OceanWorld::radiusError(c, 1920, 1080).empty(), "%s = %g refused", k.name, (double)big);
    }
#ifndef OCEAN_TESTS_NO_SHIM
    // oc_init refuses each (and keeps the previous world); the largest accepted
    // value is accepted.
    if (t.expect(oc_init(91, 1920, 1080, 240.0, 60, nullptr) == 1, "oc_init: %s", oc_last_error())) {
        oc_step(5);
        const ofp::Fingerprint before = ofp::fingerprint(*g_world);
        std::string firstError;
        for (const Key& k : keys) {
            const std::string cfg = std::string("{\"") + k.name + "\":1e20}";
            t.expect(oc_init(92, 1920, 1080, 240.0, 60, cfg.c_str()) == 0 &&
                         std::strstr(oc_last_error(), k.name) != nullptr,
                     "oc_init accepted %s (error: %s)", cfg.c_str(), oc_last_error());
            t.expect(ofp::fingerprint(*g_world) == before, "a refused oc_init (%s) changed the world", cfg.c_str());
            if (firstError.empty()) firstError = oc_last_error();
        }
        t.note("oc_init {\"perceptionRadius\":1e20}: %s", firstError.c_str());
        // The Ocean's cap: 1.8e19 (a finite square) and just above 1e6 are refused
        // too, 1e6 itself is accepted, for every radius.
        for (const Key& k : keys) {
            for (const char* v : {"1.8e19", "1000001"}) {
                const std::string cfg = std::string("{\"") + k.name + "\":" + v + "}";
                const int ok = oc_init(93, 1920, 1080, 240.0, 60, cfg.c_str());
                t.expect(ok == 0 && std::strstr(oc_last_error(), k.name) != nullptr, "oc_init accepted %s (error: %s)",
                         cfg.c_str(), oc_last_error());
            }
            const std::string cfg = std::string("{\"") + k.name + "\":1e6}";
            const int ok = oc_init(93, 1920, 1080, 240.0, 60, cfg.c_str());
            t.expect(ok == 1, "%s refused: %s", cfg.c_str(), oc_last_error());
        }
    }
#endif
#ifdef EVO_OCEAN_EYE
    // The largest accepted perceptionRadius (the Ocean's cap, 1e6), eye on: every
    // fish sees everything, every sensor stays finite and an empty sector still
    // reads 0.
    {
        const float cap = 1e6f;
        OceanWorld w;
        std::string err;
        char cfg[160];
        std::snprintf(cfg, sizeof cfg, R"({"perceptionRadius":%.9g,"eye":1,"predatorCount":2,"targetFood":100})",
                      (double)cap);
        if (t.expect(ofp::initWorld(w, 94, 1920, 1080, 240.0f, 60, cfg, err), "init: %s", err.c_str()) &&
            t.expect(w.cfg.perceptionRadius == cap && OceanWorld::radiusError(w.cfg, 1920, 1080).empty(),
                     "perceptionRadius %.9g stored", (double)w.cfg.perceptionRadius)) {
            w.cfg.captureActivations = true;
            long nonFinite = 0, empty = 0, full = 0;
            for (int s = 0; s < 20; ++s) {
                w.update(0.016f);
                for (const Fish& c : w.creatures) {
                    if (c.age <= 0.0f) continue;
                    for (int k = 0; k < NUM_SENSES; ++k) nonFinite += !finite(c.lastSensors[k]);
                    for (int k = 0; k < ocean::kEyeSectors; ++k) {
                        const float* e = c.lastSensors + ocean::kEyeFirst + 3 * k;
                        if (e[0] == 0.0f && e[1] == 0.0f && e[2] == 0.0f) ++empty; else ++full;
                    }
                }
            }
            t.expect(nonFinite == 0, "%ld non-finite sensors with perceptionRadius %.9g", nonFinite, (double)cap);
            t.expect(empty > 0 && full > 0, "sectors: %ld empty, %ld full (expected both)", empty, full);
            t.note("perceptionRadius %.9g, eye on, 20 steps: all sensors finite; %ld empty / %ld full sectors",
                   (double)cap, empty, full);
        }
    }
#endif
}

#ifndef OCEAN_TESTS_NO_SHIM
void testReset() {
    Test t("reset");
    const char* cfg = R"({"predatorCount":4,"predatorEconomy":true,"currentStrength":60,"foodPatches":4,"foodDepthMode":1,"kBuoy":2})";
    // Every shim call below is made BEFORE oc_last_error() is read: as two
    // arguments of one call their order would be unspecified (a stale message,
    // or a pointer the shim call then reallocated).
    const int init0 = oc_init(77, 1920, 1080, 240.0, 300, cfg);
    if (!t.expect(init0 == 1, "oc_init refused: %s", oc_last_error())) return;
    const ofp::Fingerprint f0 = ofp::fingerprint(*g_world);
    oc_step(400);
    const ofp::Fingerprint f400 = ofp::fingerprint(*g_world);
    const bool setOk = oc_set_param("kBuoy", 5.0) == 1 && oc_set_param("pitchMax", 0.2) == 1;
    t.expect(setOk, "oc_set_param refused: %s", oc_last_error());
    oc_step(100);
    const int reset0 = oc_reset();
    t.expect(reset0 == 1, "oc_reset failed: %s", oc_last_error());
    t.expect(ofp::fingerprint(*g_world) == f0, "oc_reset did not restore the initial world");
    oc_step(400);
    t.expect(ofp::fingerprint(*g_world) == f400, "after oc_reset, 400 steps differ from the first 400");
    // A second reset, and an oc_init with the same arguments, replay too.
    oc_reset();
    oc_step(400);
    t.expect(ofp::fingerprint(*g_world) == f400, "second oc_reset differs");
    oc_init(77, 1920, 1080, 240.0, 300, cfg);
    oc_step(400);
    t.expect(ofp::fingerprint(*g_world) == f400, "a repeated oc_init differs");

    // The harness's world (ofp::initWorld, what ocean_parity_driver runs) is the
    // shim's. fingerprint() hashes the GLOBAL rng, so the harness's prints (rng
    // included) are taken while the rng is the harness's — before the shim
    // touches it — and the shim's are compared against those snapshots: one
    // extra draw anywhere in oc_init / oc_step, even after its last step, fails.
    for (const char* c : {(const char*)nullptr, cfg,
                          R"({"pitchMax":3,"vDrag":0,"wallBand":80,"buoyMutation":0.4,"toroidal":true,"bodyModel":true,"triangularMotion":true})"}) {
        OceanWorld w;
        std::string err;
        if (!t.expect(ofp::initWorld(w, 78, 1600, 900, 300.0f, 250, c, err), "initWorld: %s", err.c_str())) continue;
        const ofp::Fingerprint h0 = ofp::fingerprint(w);
        const std::string r0 = rng.state();
        for (int s = 0; s < 300; ++s) w.update(0.016f);
        const ofp::Fingerprint h300 = ofp::fingerprint(w);
        const std::string r300 = rng.state();
        rng.seed(999);   // the shim must not depend on what the rng held before oc_init
        const int initOk = oc_init(78, 1600, 900, 300.0, 250, c);
        if (!t.expect(initOk == 1, "oc_init: %s", oc_last_error())) continue;
        t.expect(ofp::fingerprint(*g_world) == h0 && rng.state() == r0, "shim vs harness differ after init (cfg %s)",
                 c ? c : "{}");
        oc_step(300);
        const ofp::Fingerprint s300 = ofp::fingerprint(*g_world);
        t.expect(s300 == h300 && rng.state() == r300, "shim vs harness differ after 300 steps (cfg %s; rng %s)",
                 c ? c : "{}", s300.rng == h300.rng ? "same" : "differs");
    }

    // Re-init. A fresh OceanWorld re-inited from the same seed replays. Reusing
    // ONE object keeps WorldCommon's run state — frame, nextId_ (so the ids),
    // the totals and the pairing window — as Classic's World::init does; the
    // shim never reuses a world (oc_init / oc_reset allocate a new one). Asserted
    // exactly: the reused world differs from a fresh one in that state and in
    // nothing else.
    {
        OceanWorld a;
        std::string err;
        ofp::initWorld(a, 79, 1920, 1080, 240.0f, 200, nullptr, err);
        const ofp::Fingerprint a0 = ofp::fingerprint(a);
        for (int s = 0; s < 200; ++s) a.update(0.016f);
        const unsigned long long frameBefore = a.frame;
        const std::uint64_t idBefore = a.nextId_;
        const long long birthsBefore = a.totalBirths, deathsBefore = a.totalDeaths;
        const std::size_t windowBefore = a.reproWindow_.size();
        ofp::initWorld(a, 79, 1920, 1080, 240.0f, 200, nullptr, err);
        const ofp::Fingerprint a1 = ofp::fingerprint(a);
        OceanWorld b;
        ofp::initWorld(b, 79, 1920, 1080, 240.0f, 200, nullptr, err);
        const ofp::Fingerprint b0 = ofp::fingerprint(b);
        t.expect(b0 == a0, "a fresh OceanWorld re-inited from the same seed does not replay");
        t.expect(a.frame == frameBefore && a.nextId_ == idBefore + 200 && a.totalBirths == birthsBefore &&
                     a.totalDeaths == deathsBefore && a.reproWindow_.size() == windowBefore && a.totalReseeds == 0,
                 "reused world: frame %llu (was %llu), nextId %llu (was %llu + 200 founders), births %lld (was %lld)",
                 a.frame, frameBefore, (unsigned long long)a.nextId_, (unsigned long long)idBefore, a.totalBirths, birthsBefore);
        t.expect(frameBefore == 200 && idBefore >= 201, "the first run did not get anywhere to carry over");
        t.expect(a1.cfg == a0.cfg && a1.food == a0.food && a1.pred == a0.pred && a1.sig == a0.sig && a1.cur == a0.cur &&
                     a1.geo == a0.geo && a1.rng == a0.rng && a1.ctr != a0.ctr && a1.fish != a0.fish,
                 "reused world: only ctr and fish may differ from a fresh one");
        // The fish are the fresh world's, but for ids shifted by the ids already used.
        bool sameFish = a.creatures.size() == b.creatures.size();
        for (std::size_t i = 0; sameFish && i < a.creatures.size(); ++i) {
            Fish x = a.creatures[i];
            const Fish& y = b.creatures[i];
            sameFish &= (x.id == y.id + (idBefore - 1) && x.lineageId == y.lineageId + (idBefore - 1));
            x.id = y.id;
            x.lineageId = y.lineageId;
            ofp::Hasher hx, hy;
            ofp::hashFish(hx, x);
            ofp::hashFish(hy, y);
            sameFish &= (hx.value() == hy.value());
        }
        t.expect(sameFish, "reused world: the fish differ from a fresh world's by more than their ids");
    }
}
#endif

struct BirthResult {
    bool born = false;
    long draws = -1;
    float childDepth = 0, mid = 0, childBuoy = 0, b1 = 0, b2 = 0, vz = 1;
    Vec2 childPos;
    std::uint64_t childLineage = 0, p1Lineage = 0;
    std::uint32_t gen = 0;
};

// Two adult, well-fed fish wired to vote INTERACT_REPRODUCE, one step.
BirthResult runBirth(unsigned seed, float m, float b1, float b2, float z1, float z2, Vec2 p1, Vec2 p2,
                     bool toroidal = false, float D = 240.0f) {
    OceanConfig oc;
    oc.buoyMutation = m;
    OceanWorld w;
    initQuiet(w, seed, D, oc, false, toroidal);
    const std::vector<Gene> g = {mkGene(false, 0, INTERACT_REPRODUCE, kStrong)};
    const int i1 = addFish(w, p1, z1, g, b1), i2 = addFish(w, p2, z2, g, b2);
    for (int i : {i1, i2}) {
        Fish& f = w.creatures[i];
        f.age = 10.0f;
        f.foodReserves = 100.0f;
        f.reproTimer = 0.0f;
        f.interactTimer = 0.0f;
    }
    BirthResult r;
    const RandomGen before = rng;
    w.update(0.016f);
    r.draws = drawsBetween(before, rng);
    if (w.creatures.size() != 3) return r;
    const Fish &a = w.creatures[i1], &b = w.creatures[i2], &c = w.creatures[2];
    r.born = true;
    r.childDepth = c.depth;
    r.mid = (a.depth + b.depth) * 0.5f;
    r.childBuoy = c.bodyBuoy;
    r.b1 = a.bodyBuoy;
    r.b2 = b.bodyBuoy;
    r.vz = c.vz;
    r.childPos = c.pos;
    r.childLineage = c.lineageId;
    r.p1Lineage = a.lineageId;
    r.gen = c.generation;
    return r;
}

void testChild() {
    Test t("child");
    float lo = 1, hi = -1;
    int born = 0;
    for (unsigned s = 0; s < 300; ++s) {
        const float m = 0.05f;
        const BirthResult r = runBirth(1000 + s, m, 0.3f, 0.6f, 100.0f + (float)(s % 7), 120.0f - (float)(s % 5),
                                       {960, 540}, {962, 541});
        if (!t.expect(r.born, "seed %u: no birth", 1000 + s)) continue;
        ++born;
        t.expect(r.childDepth == r.mid, "child depth %.9g != parents' midpoint %.9g", r.childDepth, r.mid);
        const float mean = 0.5f * (r.b1 + r.b2), d = r.childBuoy - mean;
        t.expect(std::abs(d) <= m + 1e-6f, "child bodyBuoy %.9g is %.9g from the parents' mean (m = %g)", r.childBuoy, d, m);
        t.expect(r.vz == 0.0f && r.gen == 1 && r.childLineage == r.p1Lineage, "child vz %.9g gen %u lineage %llu/%llu",
                 r.vz, r.gen, (unsigned long long)r.childLineage, (unsigned long long)r.p1Lineage);
        lo = std::min(lo, d);
        hi = std::max(hi, d);
    }
    t.expect(lo < -0.04f && hi > 0.04f, "bodyBuoy draws do not span ±m: [%.4f, %.4f]", lo, hi);
    t.note("%d births; child bodyBuoy - mean in [%.4f, %.4f] (m = 0.05)", born, lo, hi);

    // m = 0: the mean exactly. Clamped at the ends.
    const BirthResult z = runBirth(7, 0.0f, 0.3f, 0.6f, 100, 110, {960, 540}, {961, 540});
    t.expect(z.born && z.childBuoy == 0.5f * (z.b1 + z.b2), "m = 0: child bodyBuoy %.9g != mean %.9g", z.childBuoy,
             0.5f * (z.b1 + z.b2));
    for (unsigned s = 0; s < 40; ++s) {
        const BirthResult top = runBirth(50 + s, 0.3f, 1.0f, 1.0f, 230, 235, {960, 540}, {961, 540});
        const BirthResult bot = runBirth(90 + s, 0.3f, 0.0f, 0.0f, 3, 8, {960, 540}, {961, 540});
        t.expect(top.born && top.childBuoy <= 1.0f && top.childBuoy >= 0.7f - 1e-6f, "clamp at 1: %.9g", top.childBuoy);
        t.expect(bot.born && bot.childBuoy >= 0.0f && bot.childBuoy <= 0.3f + 1e-6f, "clamp at 0: %.9g", bot.childBuoy);
        t.expect(top.childDepth == top.mid && bot.childDepth == bot.mid, "midpoint near surface / floor");
    }
    // Across the toroidal seam: placed at the wrapped midpoint, depth still the mean.
    const BirthResult seam = runBirth(8, 0.05f, 0.4f, 0.5f, 60, 80, {3, 540}, {1917, 540}, /*toroidal*/ true);
    t.expect(seam.born && seam.childDepth == seam.mid && (seam.childPos.x < 10.0f || seam.childPos.x > 1910.0f),
             "toroidal seam birth: born %d depth %.9g mid %.9g x %.4f", seam.born, seam.childDepth, seam.mid, seam.childPos.x);
}

void testDrawsMotion() {
    Test t("draws_motion");
    struct V { const char* name; OceanConfig oc; float D; bool tri; };
    std::vector<V> vs;
    auto add = [&](const char* n, auto&& set, float D = 240.0f, bool tri = false) {
        OceanConfig o;
        set(o);
        vs.push_back({n, o, D, tri});
    };
    add("default", [](OceanConfig&) {});
    add("pitchMax 0.01", [](OceanConfig& o) { o.pitchMax = 0.01f; });
    add("pitchMax 5", [](OceanConfig& o) { o.pitchMax = 5.0f; });
    add("kBuoy -5", [](OceanConfig& o) { o.kBuoy = -5.0f; });
    add("kBuoy 30", [](OceanConfig& o) { o.kBuoy = 30.0f; });
    add("wallBand 0", [](OceanConfig& o) { o.wallBand = 0.0f; });
    add("wallBand 120", [](OceanConfig& o) { o.wallBand = 120.0f; });
    add("vDrag 0", [](OceanConfig& o) { o.vDrag = 0.0f; });
    add("vDrag 300", [](OceanConfig& o) { o.vDrag = 300.0f; });
    add("costs", [](OceanConfig& o) { o.cHold = 0.5f; o.cPress = 0.5f; });
    add("D 10", [](OceanConfig&) {}, 10.0f);
    add("D 3000", [](OceanConfig&) {}, 3000.0f);
    add("triangular (no MOVE_RANDOM)", [](OceanConfig&) {}, 240.0f, true);
    add("steerFrame 1", [](OceanConfig& o) { o.steerFrame = 1; });
    for (const V& v : vs) {
        OceanWorld w;
        initQuiet(w, 61, v.D, v.oc);
        w.cfg.triangularMotion = v.tri;
        int nRandom = 0;
        for (int i = 0; i < 40; ++i) {
            // Depths at the surface, the floor and between; bodyBuoy 0, 1 and between;
            // STEER_Z wires of both signs and none; half the fish wired to MOVE_RANDOM.
            const float z = (i % 5 == 0) ? 0.0f : (i % 5 == 1) ? v.D : v.D * (float)(i % 7) / 7.0f;
            std::vector<Gene> g;
            if (i % 3 != 2) g.push_back(mkGene(false, 0, STEER_Z, (i % 3 == 0) ? kStrong : -kStrong));
            const bool rnd = (i % 2 == 0);
            if (rnd) g.push_back(mkGene(false, 0, MOVE_RANDOM, kStrong));
            const int k = addFish(w, {40.0f + 45.0f * i, 100.0f + 20.0f * (i % 40)}, z, g, (float)(i % 3) * 0.5f);
            w.creatures[k].responsiveness = 1.0f;   // |MOVE_RANDOM| = 0.964 > 0.5: its draws fire
            nRandom += rnd;
        }
        const long N = (long)w.creatures.size();
        const long expected = N + (v.tri ? 0 : 3L * nRandom);   // RANDOM_SENSOR each + MOVE_RANDOM's three
        for (int s = 1; s <= 150; ++s) {
            const RandomGen before = rng;
            w.update(0.016f);
            const long d = drawsBetween(before, rng, 10000);
            t.expect(d == expected, "%s step %d: %ld draws, expected %ld", v.name, s, d, expected);
            t.expect((long)w.creatures.size() == N, "%s: population changed", v.name);
        }
    }
    t.note("%zu variants x 150 steps: draws/step == N + 3 x (fish firing MOVE_RANDOM), always", vs.size());
}

void testDrawsBirth() {
    Test t("draws_birth");
    struct V { float m, b1, b2, z1, z2; };
    const V vs[] = {
        {0.05f, 0.3f, 0.6f, 100, 110}, {0.0f, 0.3f, 0.6f, 100, 110}, {0.5f, 0.3f, 0.6f, 100, 110},
        {0.05f, 0.0f, 0.0f, 0, 10},    {0.05f, 1.0f, 1.0f, 240, 230}, {1e-6f, 0.9f, 0.1f, 50, 70},
    };
    for (unsigned seed : {201u, 202u, 203u, 204u}) {
        long ref = -2;
        for (const V& v : vs) {
            const BirthResult r = runBirth(seed, v.m, v.b1, v.b2, v.z1, v.z2, {960, 540}, {961, 541});
            t.expect(r.born && r.draws > 0, "seed %u: born %d draws %ld", seed, r.born, r.draws);
            if (ref == -2) ref = r.draws;
            t.expect(r.draws == ref, "seed %u m %g buoy %g/%g depth %g/%g: %ld draws, the first variant took %ld",
                     seed, v.m, v.b1, v.b2, v.z1, v.z2, r.draws, ref);
        }
        t.note("seed %u: %ld draws in the birth step for every variant", seed, ref);
    }
}

void testDrawsPredators() {
    Test t("draws_pred");
    // Wander only (no fish): two draws per predator per step, whatever its depth / pitch / D.
    for (float D : {10.0f, 240.0f, 3000.0f}) {
        for (bool econ : {false, true}) {
            OceanWorld w;
            initQuiet(w, 71, D, OceanConfig{});
            w.cfg.predatorEconomy = econ;
            w.cfg.predatorMetabolism = 0.0f;   // nobody starves, nobody buds
            w.cfg.predatorCount = 9;
            for (int i = 0; i < 9; ++i) {
                OceanPredator p;
                p.pos = {100.0f + 200.0f * i, 540.0f};
                p.depth = (i % 3 == 0) ? 0.0f : (i % 3 == 1) ? D : D * 0.37f;
                p.pitch = (i % 3 - 1) * 0.3f;
                p.energy = 30.0f;
                w.predators.push_back(p);
            }
            for (int s = 1; s <= 200; ++s) {
                const RandomGen before = rng;
                w.update(0.016f);
                const long d = drawsBetween(before, rng, 1000);
                t.expect(d == 18, "D %g econ %d step %d: %ld draws, expected 18", D, econ, s, d);
            }
        }
    }
    // Buds: four draws each (position x2, heading, depth), six with inheritance.
    for (bool tor : {false, true}) {
        for (bool inherit : {false, true}) {
            OceanWorld w;
            initQuiet(w, 72, 240.0f, OceanConfig{}, false, tor);
            w.cfg.predatorEconomy = true;
            w.cfg.predatorInheritance = inherit;
            for (int i = 0; i < 6; ++i) {
                OceanPredator p;
                p.pos = {(i == 0) ? 2.0f : 150.0f + 300.0f * i, (i == 1) ? 1078.0f : 540.0f};
                p.depth = (i == 2) ? 0.0f : (i == 3) ? 240.0f : 100.0f;   // a bud at the surface / floor clamps
                p.energy = (i < 4) ? 500.0f : 30.0f;                      // four bud, two do not
                w.predators.push_back(p);
            }
            const RandomGen before = rng;
            w.update(0.016f);
            const long d = drawsBetween(before, rng, 1000);
            const long expected = 6 * 2 + 4 * (inherit ? 6 : 4);
            t.expect(d == expected && w.predators.size() == 10, "buds (toroidal %d, inherit %d): %ld draws, expected %ld; %zu predators",
                     tor, inherit, d, expected, w.predators.size());
            for (const OceanPredator& p : w.predators)
                t.expect(p.depth >= 0.0f && p.depth <= 240.0f, "bud depth %.9g", p.depth);
        }
    }
    // Floor refill: everyone starves this step; four draws per refilled predator.
    {
        OceanWorld w;
        initQuiet(w, 73, 240.0f, OceanConfig{});
        w.cfg.predatorEconomy = true;
        w.cfg.predatorMinPopulation = 5;
        for (int i = 0; i < 3; ++i) {
            OceanPredator p;
            p.pos = {300.0f + 500.0f * i, 300.0f};
            p.depth = 120.0f;
            p.energy = -1.0f;
            w.predators.push_back(p);
        }
        const RandomGen before = rng;
        w.update(0.016f);
        const long d = drawsBetween(before, rng, 1000);
        t.expect(d == 3 * 2 + 5 * 4 && w.predators.size() == 5 && w.totalPredatorReseeds == 5,
                 "floor refill: %ld draws (expected 26), %zu predators, %lld reseeds", d, w.predators.size(),
                 w.totalPredatorReseeds);
    }
}

void testDrawsFood() {
    Test t("draws_food");
    struct V { int patches, mode; float spread; };
    const V vs[] = {{0, 0, 30}, {0, 1, 30}, {5, 0, 30}, {5, 1, 0}, {5, 1, 30}, {5, 1, 10000}};
    RandomGen common = rng;
    bool haveCommon = false;
    std::string endState[2];
    for (const V& v : vs) {
        OceanConfig oc;
        oc.foodDepthMode = v.mode;
        oc.foodDepthSpread = v.spread;
        OceanWorld w;
        initQuiet(w, 81, 240.0f, oc);
        w.cfg.foodPatches = v.patches;
        w.init(1920, 1080, 240.0f, 0);   // re-init so the patches (and their depths) are drawn
        if (!haveCommon) { common = rng; haveCommon = true; }
        rng = common;                    // every variant spawns from the same engine state
        const long perSpawn = v.patches > 0 ? 4 : 3;
        std::set<std::uint32_t> depths;
        for (int i = 0; i < 500; ++i) {
            const RandomGen before = rng;
            w.spawnFood();
            const long d = drawsBetween(before, rng, 100);
            t.expect(d == perSpawn, "patches %d mode %d spread %g: spawn %d took %ld draws, expected %ld",
                     v.patches, v.mode, v.spread, i, d, perSpawn);
            const float z = w.food.back().depth;
            t.expect(z >= 0.0f && z <= 240.0f, "food depth %.9g", z);
            depths.insert(ofp::bits(z));
        }
        if (v.patches > 0 && v.mode == 1 && v.spread == 0.0f)
            t.expect(depths.size() <= 5, "spread 0: %zu distinct food depths from 5 patches", depths.size());
        // Same draw count per spawn => the same engine state after 500 spawns,
        // with or without patches (within each group).
        std::string& ref = endState[v.patches > 0];
        if (ref.empty()) ref = rng.state();
        t.expect(rng.state() == ref, "patches %d mode %d spread %g: engine state after 500 spawns differs", v.patches,
                 v.mode, v.spread);
    }
}

// ============================================================================
// E1 physics
// ============================================================================

// A tiny local generator for probe points (the engine's rng stays untouched).
struct Lcg {
    std::uint32_t s;
    explicit Lcg(std::uint32_t x) : s(x) {}
    float unit() { s = s * 1664525u + 1013904223u; return (float)(s >> 8) * (1.0f / 16777216.0f); }
};

// Central-difference divergence of one flow field at (p, d), step h.
template <class F>
void divergenceAt(F&& f, Vec2 p, float d, float h, double& div, double& sumAbs) {
    const OceanWorld::Flow xp = f(Vec2{p.x + h, p.y}, d), xm = f(Vec2{p.x - h, p.y}, d);
    const OceanWorld::Flow yp = f(Vec2{p.x, p.y + h}, d), ym = f(Vec2{p.x, p.y - h}, d);
    const OceanWorld::Flow dp = f(p, d + h), dm = f(p, d - h);
    const double ax = ((double)xp.x - (double)xm.x) / (2.0 * h);
    const double ay = ((double)yp.y - (double)ym.y) / (2.0 * h);
    const double ad = ((double)dp.d - (double)dm.d) / (2.0 * h);
    div = ax + ay + ad;
    sumAbs = std::abs(ax) + std::abs(ay) + std::abs(ad);
}

void testDivergence() {
    Test t("divergence");
    OceanConfig oc;
    oc.waveSpeed = 6.0f;
    oc.deepCurrent = true;
    OceanWorld w;
    initQuiet(w, 301, 240.0f, oc, false, false, /*current*/ 40.0f);
    for (int s = 0; s < 37; ++s) w.update(0.016f);   // the clocks run: phases != 0
    const float D = w.D, b = std::min(oc.waveBand, 0.25f * D);
    using Fl = OceanWorld::Flow;
    struct Field { const char* name; std::function<Fl(Vec2, float)> f; };
    const std::vector<Field> fields = {
        {"train0", [&](Vec2 p, float d) { return w.waveTrainAt(0, p, d); }},
        {"train1", [&](Vec2 p, float d) { return w.waveTrainAt(1, p, d); }},
        {"train2", [&](Vec2 p, float d) { return w.waveTrainAt(2, p, d); }},
        {"waves", [&](Vec2 p, float d) {
             Fl u;
             for (int i = 0; i < OceanWorld::kWaveTrains; ++i) {
                 const Fl v = w.waveTrainAt(i, p, d);
                 u.x += v.x; u.y += v.y; u.d += v.d;
             }
             return u; }},
        {"deepcur", [&](Vec2 p, float d) { return w.currentFlowAt(p, d); }},
        {"flow", [&](Vec2 p, float d) { return w.flowAt(p, d); }},
    };
    // Probe sets: the bulk (clear of the taper's band edges, where S is only
    // C¹ and the difference converges as O(h)) and the two boundary bands.
    struct Set { const char* name; float lo, hi; };
    const Set sets[] = {{"bulk", b + 4.0f, D - b - 4.0f}, {"top", 2.5f, b + 4.0f}, {"floor", D - b - 4.0f, D - 2.5f}};
    const float hs[] = {2.0f, 1.0f, 0.5f, 0.25f, 0.125f, 0.0625f, 0.03125f, 0.015625f};
    constexpr int NH = 8;
    for (const Set& st : sets) {
        Lcg g(1234);
        std::vector<std::pair<Vec2, float>> probes;
        for (int k = 0; k < 300; ++k)
            probes.push_back({Vec2{20.0f + 1880.0f * g.unit(), 20.0f + 1040.0f * g.unit()}, st.lo + (st.hi - st.lo) * g.unit()});
        for (const Field& fd : fields) {
            double res[NH];
            for (int hi = 0; hi < NH; ++hi) {
                double maxDiv = 0.0, maxSum = 0.0;
                for (const auto& pr : probes) {
                    double dv, sa;
                    divergenceAt(fd.f, pr.first, pr.second, hs[hi], dv, sa);
                    maxDiv = std::max(maxDiv, std::abs(dv));
                    maxSum = std::max(maxSum, sa);
                }
                res[hi] = maxSum > 0.0 ? maxDiv / maxSum : 0.0;
            }
            // The best residual over h must be < 1e-3 and come from shrinking h
            // (truncation error falling before float noise takes over).
            int best = 0;
            for (int hi = 1; hi < NH; ++hi) if (res[hi] < res[best]) best = hi;
            const bool bulk = (st.name[0] == 'b');
            t.expect(res[best] < 1e-3, "%s %s: best normalised residual %.3g (h %g)", st.name, fd.name, res[best], hs[best]);
            if (bulk) t.expect(res[1] < 1e-3, "%s %s: residual %.3g at h = 1", st.name, fd.name, res[1]);
            t.expect(res[best] <= res[0] || res[0] < 1e-6, "%s %s: no convergence (h 2: %.3g, best %.3g)", st.name, fd.name, res[0], res[best]);
            if (fd.name[0] == 'f' || fd.name[0] == 'w')
                t.note("%-5s %-7s residual h=2 %.1e  h=1 %.1e  h=1/4 %.1e  h=1/16 %.1e  h=1/32 %.1e", st.name, fd.name,
                       res[0], res[1], res[3], res[5], res[6]);
        }
    }
    // No flow through the surface or the floor: exactly zero normal component.
    Lcg g(99);
    int zeroN = 0, stillSurface = 0;
    for (int k = 0; k < 500; ++k) {
        const Vec2 p = {1920.0f * g.unit(), 1080.0f * g.unit()};
        const Fl s = w.flowAt(p, 0.0f), f = w.flowAt(p, D);
        bool ok = s.d == 0.0f && f.d == 0.0f;
        for (int i = 0; i < OceanWorld::kWaveTrains; ++i)
            ok &= w.waveTrainAt(i, p, 0.0f).d == 0.0f && w.waveTrainAt(i, p, D).d == 0.0f;
        zeroN += ok;
        // the deep current is still at the surface and full from mid-depth
        const Fl c0 = w.currentFlowAt(p, 0.0f), cm = w.currentFlowAt(p, 0.5f * D + 3.0f);
        const Vec2 c = w.currentAt(p);
        stillSurface += (c0.x == 0.0f && c0.y == 0.0f && cm.x == c.x && cm.y == c.y && cm.d == 0.0f);
    }
    t.expect(zeroN == 500, "normal flow at surface / floor not exactly 0 at %d of 500 points", 500 - zeroN);
    t.expect(stillSurface == 500, "deep current: f(0) = 0, f(>= D/2) = 1 failed at %d points", 500 - stillSurface);
    // flowAt (one shared taper per call) == the current + each train on its
    // own (waveTrainAt(i, p, d)), in flowAt's order, bit for bit: in the bulk,
    // across both taper bands and their edges, at surface and floor.
    int sameBits = 0, nPts = 0;
    for (int k = 0; k < 2000; ++k) {
        const Vec2 p = {1920.0f * g.unit(), 1080.0f * g.unit()};
        const float edges[] = {0.0f, b, D - b, D, std::nextafter(b, 0.0f), std::nextafter(D - b, D)};
        const float d = (k < 600) ? edges[k % 6] : D * g.unit();
        const Fl f = w.flowAt(p, d);
        Fl s = w.currentFlowAt(p, d);
        for (int i = 0; i < OceanWorld::kWaveTrains; ++i) {
            const Fl u = w.waveTrainAt(i, p, d);
            s.x += u.x; s.y += u.y; s.d += u.d;
        }
        ++nPts;
        sameBits += (std::memcmp(&f.x, &s.x, 4) == 0 && std::memcmp(&f.y, &s.y, 4) == 0 && std::memcmp(&f.d, &s.d, 4) == 0);
    }
    t.expect(sameBits == nPts, "flowAt != current + the trains one by one at %d of %d points", nPts - sameBits, nPts);
}

// The E1 flow cache (src/ocean/ocean_flow.hpp) against the exact formulas.
void testFlowTables() {
    Test t("flow_tables");
    // ---- the eddy current: the radial table vs CurrentField::velocityAt ----
    // Per vortex, |Δv| <= 9e-6 · strength units/s (interpolation <= 7.63e-6·S
    // at u = 1/2, the endpoint shift / cutoff <= 1.05e-6·S at u = 16); the
    // budget is that times the vortex count (triangle inequality). Samples
    // cover the world and 200 beyond each edge (raw differences, no image).
    struct C { const char* name; const char* cfg; float strength; int eddies; };
    const C cs[] = {
        {"one vortex, preset strength 5", R"({"deepCurrent":true,"currentStrength":5,"currentEddies":1})", 5.0f, 1},
        {"the preset (5 vortices)", kE1PresetJson, 5.0f, 5},
        {"8 vortices, strength 120, core 60", R"({"deepCurrent":true,"currentStrength":120,"currentEddies":8,"currentCore":60})",
         120.0f, 8},
    };
    for (const C& c : cs) {
        OceanWorld w;
        std::string err;
        if (!t.expect(ofp::initWorld(w, 1501, 1920, 1080, 240.0f, 0, c.cfg, err), "%s: %s", c.name, err.c_str())) continue;
        // Phase 0 is before the first advance: the centres are 0 there
        // (CurrentField's own), then placed by each step's advance.
        double maxErr[3] = {0.0, 0.0, 0.0}, maxV = 0.0;
        for (int phase = 0; phase < 3; ++phase) {
            if (phase > 0) for (int s = 0; s < 400; ++s) w.update(0.016f);
            Lcg g(77 + phase);
            for (int k = 0; k < 100000; ++k) {
                const Vec2 p = {-200.0f + 2320.0f * g.unit(), -200.0f + 1480.0f * g.unit()};
                const Vec2 a = w.currentAt(p), e = w.currentExactAt(p);
                maxErr[phase] = std::max(maxErr[phase], (double)std::max(std::abs(a.x - e.x), std::abs(a.y - e.y)));
                maxV = std::max(maxV, (double)std::max(std::abs(e.x), std::abs(e.y)));
            }
        }
        const double budget = 9e-6 * c.strength * c.eddies;
        const double worst = std::max(maxErr[0], std::max(maxErr[1], maxErr[2]));
        t.expect(worst <= budget, "%s: max |Δv| %.3g / %.3g / %.3g (before the first advance, steps 400, 800) > budget %.3g",
                 c.name, maxErr[0], maxErr[1], maxErr[2], budget);
        t.note("current %-34s max |Δv| %.3g units/s (budget %.3g; max |v| %.3g)", c.name, worst, budget, maxV);
    }

    // ---- the waves: the tables vs each train's exact formulas ----
    // Positions over the world and 2% beyond each edge (the edges themselves
    // included), depths at the surface / floor, the taper joins b and D − b and
    // their neighbouring floats, D/2, near both boundaries and uniform, phases
    // set directly (0, arbitrary, just under 2π) and after real steps.
    using Fl = OceanWorld::Flow;
    struct WV { const char* name; int W, H; float D; const char* cfg; float speed; };
    const WV wv[] = {
        {"preset: D 240, band 32, speed 6", 1920, 1080, 240.0f, kE1PresetJson, 6.0f},
        {"2560x1440, band 8, speed 12", 2560, 1440, 240.0f, R"({"waveSpeed":12,"waveBand":8})", 12.0f},
        {"D 10, band 1, speed 100", 1920, 1080, 10.0f, R"({"waveSpeed":100,"waveBand":1,"waveGravity":10000})", 100.0f},
        {"100x100, D 600, speed 20", 100, 100, 600.0f, R"({"waveSpeed":20})", 20.0f},
        {"D 2000, band 300, speed 6", 1920, 1080, 2000.0f, R"({"waveSpeed":6,"waveBand":300})", 6.0f},
        // fractional depths and bands: float-rounded node positions (the rise
        // must be integrated over the ideal cell the lookup uses)
        {"D 240, band 1.01, speed 6", 1920, 1080, 240.0f, R"({"waveSpeed":6,"waveBand":1.01})", 6.0f},
        {"D 123.45, band 32, speed 6", 1920, 1080, 123.45f, R"({"waveSpeed":6})", 6.0f},
        {"D 777.7, band 13.3, speed 9", 1500, 900, 777.7f, R"({"waveSpeed":9,"waveBand":13.3})", 9.0f},
        {"D 10.37, band 1.7, speed 50", 1920, 1080, 10.37f, R"({"waveSpeed":50,"waveBand":1.7,"waveGravity":5000})", 50.0f},
    };
    for (const WV& v : wv) {
        OceanWorld w;
        std::string err;
        if (!t.expect(ofp::initWorld(w, 1502, v.W, v.H, v.D, 0, v.cfg, err), "%s: %s", v.name, err.c_str())) continue;
        const float D = w.D, b = std::min(w.ocfg.waveBand, 0.25f * D);
        const float depths[] = {0.0f, D, b, D - b, 0.5f * D, std::nextafter(b, 0.0f), std::nextafter(b, D), std::nextafter(D - b, 0.0f),
                                std::nextafter(D - b, D), 1e-3f, 0.1f * b, 0.5f * b, D - 0.5f * b, D - 1e-3f * b, 1.5f * b, D - 1.5f * b};
        double maxD[3][3] = {}, maxU[3] = {};
        long n = 0;
        int boundaryZero = 0, boundaryN = 0;
        auto& waves = ofp::field<ofp::peek::OwWaves>(w);
        const double phases[4][3] = {{0.0, 0.0, 0.0}, {1.2345, 5.4321, 3.0}, {6.283185307179586 - 1e-9, 1e-9, 3.141592653589793}, {-1, -1, -1}};
        for (const auto& ph : phases) {
            if (ph[0] < 0.0) for (int s = 0; s < 150; ++s) w.update(0.016f);   // the clock's own phases
            else for (int i = 0; i < OceanWorld::kWaveTrains; ++i) waves[i].phase = ph[i];
            Lcg g(1503);
            for (int k = 0; k < 3000; ++k) {
                Vec2 p = {(float)v.W * (-0.02f + 1.04f * g.unit()), (float)v.H * (-0.02f + 1.04f * g.unit())};
                if (k < 8) p = {(k & 1) ? (float)v.W : 0.0f, (k & 2) ? (float)v.H : 0.0f};
                const int nd = (int)(sizeof depths / sizeof depths[0]);
                for (int j = 0; j < nd + 2; ++j) {
                    const float d = (j < nd) ? depths[j] : D * g.unit();
                    for (int i = 0; i < OceanWorld::kWaveTrains; ++i) {
                        const Fl a = w.waveTrainAt(i, p, d), e = w.waveTrainExactAt(i, p, d);
                        maxD[i][0] = std::max(maxD[i][0], (double)std::abs(a.x - e.x));
                        maxD[i][1] = std::max(maxD[i][1], (double)std::abs(a.y - e.y));
                        maxD[i][2] = std::max(maxD[i][2], (double)std::abs(a.d - e.d));
                        maxU[i] = std::max(maxU[i], (double)std::max(std::abs(e.x), std::max(std::abs(e.y), std::abs(e.d))));
                        if (d == 0.0f || d == D) {
                            ++boundaryN;
                            boundaryZero += (a.x == 0.0f && a.y == 0.0f && a.d == 0.0f);
                        }
                    }
                    ++n;
                }
            }
        }
        // Budget per component and train: 2e-6 units/s per unit of waveSpeed,
        // or 1e-6 of the train's largest speed where a narrow band makes the
        // horizontal flow large (|H| reaches A·1.5/(b·k)).
        for (int i = 0; i < OceanWorld::kWaveTrains; ++i) {
            const double budget = std::max(2e-6 * v.speed, 1e-6 * maxU[i]);
            const double worst = std::max(maxD[i][0], std::max(maxD[i][1], maxD[i][2]));
            t.expect(worst <= budget, "%s train %d: max |Δu| x %.3g y %.3g d %.3g > budget %.3g", v.name, i, maxD[i][0], maxD[i][1],
                     maxD[i][2], budget);
            t.note("waves %-32s train %d: max |Δu| x %.2e y %.2e d %.2e (budget %.1e, max |u| %.3g)", v.name, i, maxD[i][0],
                   maxD[i][1], maxD[i][2], budget, maxU[i]);
        }
        t.expect(boundaryZero == boundaryN, "%s: the tables' flow at surface / floor not exactly 0 at %d of %d", v.name,
                 boundaryN - boundaryZero, boundaryN);
        (void)n;
    }
    // The Codex repro (flow-table review): 1920 x 1080, D 240, waveSpeed 6,
    // waveBand 1.01, before any advance, train 0 at (0, 0, 239.49894714355469):
    // exact u_x 2.0719101; with the rise integrated between float-rounded nodes
    // the table gave 2.0772154 (0.0053 off, ~24x the budget).
    {
        OceanWorld w;
        std::string err;
        if (t.expect(ofp::initWorld(w, 1507, 1920, 1080, 240.0f, 0, R"({"waveSpeed":6,"waveBand":1.01})", err), "repro: %s",
                     err.c_str())) {
            const float d = 239.49894714355469f;
            const Fl a = w.waveTrainAt(0, {0.0f, 0.0f}, d), e = w.waveTrainExactAt(0, {0.0f, 0.0f}, d);
            const double err0 = std::max((double)std::abs(a.x - e.x), std::max((double)std::abs(a.y - e.y), (double)std::abs(a.d - e.d)));
            const double budget = 1e-6 * std::max((double)std::abs(e.x), 1.0);
            t.expect(err0 <= budget, "repro: train 0 at depth %.17g: table u_x %.9g, exact %.9g (|Δu| %.3g > %.3g)", (double)d,
                     (double)a.x, (double)e.x, err0, budget);
            t.note("repro (band 1.01, depth 239.498947): table u_x %.9g, exact %.9g, |Δu| %.2e", (double)a.x, (double)e.x, err0);
        }
    }

    // ---- a discrete divergence probe, each train: tables vs exact ----
    // Central differences at h = 1/8 and 1/32 over the whole column (bands,
    // joins and knots included), normalised as in `divergence`. The tables'
    // field is the curl of a vector potential (V'·T·P horizontally, −V·T·∇P
    // vertically), divergence-free for the interpolants themselves; what is
    // left is truncation inside cells and roundoff.
    {
        OceanWorld w;
        std::string err;
        ofp::initWorld(w, 1504, 1920, 1080, 240.0f, 0, kE1PresetJson, err);
        for (int s = 0; s < 37; ++s) w.update(0.016f);
        const float D = w.D;
        for (float h : {0.125f, 0.03125f}) {
            for (int i = 0; i < OceanWorld::kWaveTrains; ++i) {
                double res[2];
                for (int ex = 0; ex < 2; ++ex) {
                    Lcg g(1505);
                    double maxDiv = 0.0, maxSum = 0.0;
                    for (int k = 0; k < 3000; ++k) {
                        const Vec2 p = {20.0f + 1880.0f * g.unit(), 20.0f + 1040.0f * g.unit()};
                        const float d = h + (D - 2.0f * h) * g.unit();
                        double dv, sa;
                        if (ex) divergenceAt([&](Vec2 q, float z) { return w.waveTrainExactAt(i, q, z); }, p, d, h, dv, sa);
                        else    divergenceAt([&](Vec2 q, float z) { return w.waveTrainAt(i, q, z); }, p, d, h, dv, sa);
                        maxDiv = std::max(maxDiv, std::abs(dv));
                        maxSum = std::max(maxSum, sa);
                    }
                    res[ex] = maxSum > 0.0 ? maxDiv / maxSum : 0.0;
                }
                // Near the taper joins (B is C¹) both converge as O(h): at h = 1/8
                // the exact field's own residual is ~1e-3 there. The tables'
                // must not be worse than it, and below 1e-3 at h = 1/32.
                t.expect(res[0] <= 1.5 * res[1] + 2e-5 && (h > 0.1f || res[0] < 1e-3),
                         "train %d h %g: tables' residual %.3g (exact %.3g)", i, (double)h, res[0], res[1]);
                t.note("divergence train %d h=%-8g tables %.2e  exact %.2e (normalised, whole column)", i, (double)h, res[0], res[1]);
            }
        }
    }

    // ---- the rebuild rules: live knobs, keys checked inside OceanWorld ----
    // (A direct config assignment, as the harness driver's --set makes.)
    {
        OceanWorld w;
        std::string err;
        ofp::initWorld(w, 1506, 1920, 1080, 240.0f, 0, kE1PresetJson, err);
        for (int s = 0; s < 20; ++s) w.update(0.016f);
        const Vec2 p0{777.7f, 333.3f};
        const float d0 = 50.0f;
        const Fl before = w.flowAt(p0, d0);
        auto worstVsExact = [&]() {
            Lcg g(1507);
            double worst = 0.0, maxU = 0.0;
            for (int k = 0; k < 2000; ++k) {
                const Vec2 p = {1920.0f * g.unit(), 1080.0f * g.unit()};
                const float d = w.D * g.unit();
                for (int i = 0; i < OceanWorld::kWaveTrains; ++i) {
                    const Fl a = w.waveTrainAt(i, p, d), e = w.waveTrainExactAt(i, p, d);
                    worst = std::max(worst, (double)std::max(std::abs(a.x - e.x), std::max(std::abs(a.y - e.y), std::abs(a.d - e.d))));
                    maxU = std::max(maxU, (double)std::max(std::abs(e.x), std::abs(e.y)));
                }
            }
            return std::max(worst / std::max(maxU, 1e-30), 0.0);
        };
        const struct { const char* what; float speed, band; } live[] = {{"waveSpeed 9", 9.0f, 32.0f}, {"waveBand 10", 9.0f, 10.0f},
                                                                          {"waveSpeed 0.5", 0.5f, 10.0f}};
        for (const auto& l : live) {
            w.ocfg.waveSpeed = l.speed;
            w.ocfg.waveBand = l.band;
            const double rel = worstVsExact();
            t.expect(rel < 2e-6, "after %s: tables vs exact %.3g of the largest speed (stale tables?)", l.what, rel);
        }
        w.ocfg.waveSpeed = 6.0f;
        w.ocfg.waveBand = 32.0f;
        const Fl back = w.flowAt(p0, d0);
        w.ocfg.waveGravity = 55.0f;   // only the clock reads it
        const Fl grav = w.flowAt(p0, d0);
        t.expect(std::memcmp(&back, &before, sizeof back) == 0 && std::memcmp(&grav, &before, sizeof grav) == 0,
                 "restoring waveSpeed / waveBand (or changing waveGravity) did not give the same flow bits");
    }

    // ---- dispatch: off flowE1() (sizeDrift alone reaches flowAt) the exact path ----
    {
        OceanWorld w;
        std::string err;
        ofp::initWorld(w, 1508, 1920, 1080, 240.0f, 0, R"({"currentStrength":40,"sizeDrift":true})", err);
        for (int s = 0; s < 5; ++s) w.update(0.016f);
        Lcg g(1509);
        int same = 0;
        for (int k = 0; k < 500; ++k) {
            const Vec2 p = {1920.0f * g.unit(), 1080.0f * g.unit()};
            const float d = 240.0f * g.unit();
            const Fl a = w.flowAt(p, d), e = w.flowExactAt(p, d);
            const Vec2 c = w.currentAt(p), ce = w.currentExactAt(p);
            same += !w.flowE1() && std::memcmp(&a, &e, sizeof a) == 0 && std::memcmp(&c, &ce, sizeof c) == 0;
        }
        t.expect(same == 500, "flowE1() off: flowAt / currentAt differ from the exact formulas at %d of 500 points", 500 - same);
    }
}

void testE1Buoyancy() {
    Test t("e1_buoyancy");
    OceanConfig oc;   // kBuoy 1, vDrag 2, pitchMax 0.5; no walls; flow off (no waves, no current)
    oc.wallBand = 0.0f;
    oc.lightEnabled = true;
    oc.depthCostScaled = true;
    oc.cHold = 0.05f;
    oc.cPress = 0.03f;
    oc.sizeDrift = true;
    oc.sizeFight = true;
    oc.mouthGate = true;
    OceanWorld w;
    initQuiet(w, 311, 240.0f, oc);
    struct F { int idx; float target; };
    const F fs[] = {
        {addFish(w, {300, 300}, 24.0f, {}, 0.5f), 120.0f},
        {addFish(w, {900, 700}, 216.0f, {}, 0.5f), 120.0f},
        {addFish(w, {1500, 500}, 192.0f, {}, 0.2f), 48.0f},
        {addFish(w, {600, 200}, 100.0f, {}, 0.0f), 0.0f},     // neutral AT the surface
        {addFish(w, {1200, 900}, 100.0f, {}, 1.0f), 240.0f},  // neutral ON the floor
    };
    constexpr int NF = 5;
    float off[NF];
    for (int k = 0; k < NF; ++k) off[k] = w.creatures[fs[k].idx].depth - fs[k].target;
    for (int s = 1; s <= 3000; ++s) {
        w.update(0.016f);
        if (!t.expect(w.creatures.size() == (size_t)NF, "step %d: %zu fish", s, w.creatures.size())) return;
        for (int k = 0; k < NF; ++k) {
            const float o = w.creatures[fs[k].idx].depth - fs[k].target;
            t.expect(std::abs(o) <= std::abs(off[k]), "fish %d step %d: |offset| grew %.9g -> %.9g", k, s, off[k], o);
            t.expect(o == 0.0f || (o > 0.0f) == (off[k] > 0.0f) || off[k] == 0.0f, "fish %d step %d: overshot", k, s);
            off[k] = o;
        }
    }
    for (int k = 0; k < NF; ++k) t.expect(std::abs(off[k]) < 0.5f, "fish %d still %.4f from bodyBuoy·D", k, off[k]);
    t.note("offsets after 3000 steps: %.4f %.4f %.4f %.4f %.4f", off[0], off[1], off[2], off[3], off[4]);
}

void testDrift() {
    Test t("drift");
    const float sizes[3] = {0.5f, 1.0f, 2.0f};
    for (bool sized : {true, false}) {
        OceanConfig oc;
        oc.waveSpeed = 6.0f;
        oc.deepCurrent = true;
        oc.sizeDrift = sized;
        oc.kBuoy = 0.0f;
        oc.wallBand = 0.0f;
        OceanWorld w;
        initQuiet(w, 401, 240.0f, oc, false, false, /*current*/ 60.0f);
        w.cfg.minSpeed = 0.0f;   // no swimming: the flow is all that moves them
        for (int s = 0; s < 20; ++s) w.update(0.016f);
        struct P { Vec2 pos; float d; int idx[3]; };
        std::vector<P> ps;
        Lcg g(7);
        for (int k = 0; k < 24; ++k) {
            P p;
            p.pos = {100.0f + 1700.0f * g.unit(), 100.0f + 880.0f * g.unit()};
            p.d = 40.0f + 180.0f * g.unit();
            for (int j = 0; j < 3; ++j) {
                p.idx[j] = addFish(w, p.pos, p.d, {}, p.d / 240.0f);
                w.creatures[p.idx[j]].bodySize = sizes[j];
                w.creatures[p.idx[j]].speed = 0.0f;
            }
            ps.push_back(p);
        }
        w.update(0.016f);
        double sumRatio = 0.0;
        int nRatio = 0;
        for (const P& p : ps) {
            const OceanWorld::Flow U = w.flowAt(p.pos, p.d);   // the flow this step sampled
            for (int j = 0; j < 3; ++j) {
                const Fish& f = w.creatures[p.idx[j]];
                const float wgt = sized ? std::min(1.0f, 1.0f / sizes[j]) : 1.0f;
                const float ex = OceanWorld::wrapCoord(p.pos.x + wgt * U.x * 0.016f, 1920.0f);
                const float ey = OceanWorld::wrapCoord(p.pos.y + wgt * U.y * 0.016f, 1080.0f);
                const float ed = std::clamp(p.d + wgt * U.d * 0.016f, 0.0f, 240.0f);
                t.expect(f.pos.x == ex && f.pos.y == ey && f.depth == ed,
                         "sized %d size %g: moved to (%.9g, %.9g, %.9g), expected (%.9g, %.9g, %.9g)", sized, sizes[j],
                         f.pos.x, f.pos.y, f.depth, ex, ey, ed);
            }
            const Fish &a = w.creatures[p.idx[0]], &m = w.creatures[p.idx[1]], &z = w.creatures[p.idx[2]];
            t.expect(a.pos.x == m.pos.x && a.pos.y == m.pos.y && a.depth == m.depth, "size .5 and 1 drifted differently");
            const double dm = std::hypot((double)m.pos.x - p.pos.x, (double)m.pos.y - p.pos.y);
            const double dz = std::hypot((double)z.pos.x - p.pos.x, (double)z.pos.y - p.pos.y);
            if (dm > 1e-3) { sumRatio += dz / dm; ++nRatio; }
        }
        const double r1 = nRatio ? sumRatio / nRatio : 0.0;
        if (sized) t.expect(std::abs(r1 - 0.5) < 0.01, "one step: size-2 / size-1 drift %.4f, expected 0.5", r1);
        else       t.expect(std::abs(r1 - 1.0) < 1e-6, "sizeDrift off: size-2 / size-1 drift %.4f, expected 1", r1);
        // 200 more steps: how far each has been carried.
        for (int s = 0; s < 200; ++s) w.update(0.016f);
        double far[3] = {0, 0, 0};
        for (const P& p : ps)
            for (int j = 0; j < 3; ++j) {
                const Fish& f = w.creatures[p.idx[j]];
                far[j] += std::hypot((double)w.wrapDx(f.pos.x - p.pos.x), (double)w.wrapDy(f.pos.y - p.pos.y));
            }
        const double r200 = far[2] / far[1];
        if (sized) t.expect(far[0] == far[1] && r200 > 0.35 && r200 < 0.65, "200 steps: drift .5 / 1 / 2 = %.1f / %.1f / %.1f", far[0], far[1], far[2]);
        else       t.expect(far[0] == far[1] && far[1] == far[2], "sizeDrift off, 200 steps: %.1f / %.1f / %.1f", far[0], far[1], far[2]);
        t.note("sizeDrift %s: one step ratio (2 : 1) %.4f; 200 steps mean drift .5 / 1 / 2 = %.1f / %.1f / %.1f",
               sized ? "on " : "off", r1, far[0] / ps.size(), far[1] / ps.size(), far[2] / ps.size());
    }
}

void testCosts() {
    Test t("costs");
    const float dt = 0.016f, D = 240.0f, bb = 0.4f;
    const float depths[3] = {96.0f, 0.0f, 240.0f};   // neutral (0.4·D), surface, floor
    const char* where[3] = {"neutral", "surface", "deep"};
    float costL1[3] = {0, 0, 0};
    for (bool scaled : {true, false}) {
        for (float L : {1.0f, 2.0f}) {
            Fish after[2][3];
            for (int on = 0; on < 2; ++on) {
                OceanConfig oc;
                oc.kBuoy = 0.0f;
                oc.wallBand = 0.0f;
                oc.depthCostScaled = scaled;
                oc.cHold = on ? 0.05f : 0.0f;
                oc.cPress = on ? 0.03f : 0.0f;
                OceanWorld w;
                initQuiet(w, 501, D, oc);
                w.cfg.metabolicRate = 1.5f;
                w.cfg.geneCost = 0.01f;
                w.cfg.moveCost = 7e-5f;
                const std::vector<Gene> g = {mkGene(false, 0, INTERACT_IGNORE, 1000), mkGene(false, 1, INTERACT_IGNORE, 900),
                                             mkGene(false, 2, INTERACT_IGNORE, 800)};
                for (int k = 0; k < 3; ++k) {
                    const int i = addFish(w, {300.0f + 600.0f * k, 500.0f}, depths[k], g, bb);
                    w.creatures[i].bodySize = L;
                    w.creatures[i].speed = 40.0f;
                    w.creatures[i].foodReserves = 20.0f;
                }
                w.update(dt);
                for (int k = 0; k < 3; ++k) after[on][k] = w.creatures[k];
            }
            for (int k = 0; k < 3; ++k) {
                const Fish &base = after[0][k], &c = after[1][k];
                t.expect(c.depth == depths[k] && base.depth == depths[k], "fixture %s moved in depth", where[k]);
                const float H = std::abs(c.depth - c.bodyBuoy * D) / D, P = c.depth / D;
                float expect;
                if (scaled) {
                    const float M = 1.5f * L;   // metabolicRate · massFactor (= bodySize)
                    expect = base.foodReserves - dt * M * (0.05f * H + 0.03f * P);
                } else {
                    expect = base.foodReserves - dt * (0.05f * std::abs(c.depth - c.bodyBuoy * D) / D + 0.03f * c.depth / D);
                }
                t.expect(c.foodReserves == expect, "%s %s L %g: reserves %.9g, expected %.9g", scaled ? "scaled" : "preview",
                         where[k], L, c.foodReserves, expect);
                t.expect(c.age == base.age && c.reproTimer == base.reproTimer && c.interactTimer == base.interactTimer,
                         "%s: timers changed by the depth cost", where[k]);
                if (scaled) {
                    const float cost = dt * (1.5f * L) * (0.05f * H + 0.03f * P);
                    if (L == 1.0f) costL1[k] = cost;
                    else t.expect(cost == 2.0f * costL1[k], "%s: cost at L 2 %.9g != 2 x L 1 %.9g", where[k], cost, costL1[k]);
                }
            }
            // where H or P is 0, that term is absent: neutral pays pressure only, the surface holding only
            t.expect(std::abs(after[1][0].depth - bb * D) == 0.0f && after[1][1].depth == 0.0f, "fixture depths");
        }
    }
    t.note("scaled, L 1: neutral %.3g, surface %.3g, deep %.3g energy/step (gene + move costs apart, x2 at L 2)",
           costL1[0], costL1[1], costL1[2]);
}

void testFight() {
    Test t("fight");
    auto curve = [](float age) { return (age < 30.0f) ? age / 30.0f : 1.0f - (age - 30.0f) / 90.0f; };
    Lcg g(31);
    rng.seed(601);
    // (1, 1) is the Classic two-argument fight, bit for bit, rng included.
    int same = 0;
    for (int k = 0; k < 300; ++k) {
        Fish a1, b1;
        a1.age = 150.0f * g.unit(); b1.age = 150.0f * g.unit();
        a1.foodReserves = 40.0f * g.unit(); b1.foodReserves = 40.0f * g.unit();
        Fish a2 = a1, b2 = b1;
        const RandomGen r0 = rng;
        kernel::fightOutcome(a1, b1);
        const RandomGen r1 = rng;
        rng = r0;
        kernel::fightOutcome(a2, b2, 1.0f, 1.0f);
        same += (ofp::bits(a1.foodReserves) == ofp::bits(a2.foodReserves) &&
                 ofp::bits(b1.foodReserves) == ofp::bits(b2.foodReserves) && sameEngine(r1, rng) &&
                 drawsBetween(r0, rng, 10) == 2);
    }
    t.expect(same == 300, "unit scales differ from the two-argument fight in %d of 300", 300 - same);
    // Known draws: the winner follows curve·L²·u, two draws, ±15.
    const float Ls[] = {0.5f, 0.8f, 1.0f, 1.3f, 2.0f};
    int known = 0, bigWins = 0, bigFights = 0;
    for (int k = 0; k < 500; ++k) {
        Fish a, b;
        a.age = 10.0f + 90.0f * g.unit(); b.age = 10.0f + 90.0f * g.unit();
        a.foodReserves = 30.0f; b.foodReserves = 30.0f;
        const float La = Ls[k % 5], Lb = Ls[(k / 5) % 5];
        const float sa = La * La, sb = Lb * Lb;
        RandomGen r = rng;
        const float u1 = r.unit(), u2 = r.unit();
        float s1 = curve(a.age), s2 = curve(b.age);
        if (sa != 1.0f) s1 *= sa;
        if (sb != 1.0f) s2 *= sb;
        s1 *= u1; s2 *= u2;
        const bool aWins = s1 > s2;
        kernel::fightOutcome(a, b, sa, sb);
        known += (sameEngine(r, rng) && a.foodReserves == (aWins ? 45.0f : 15.0f) && b.foodReserves == (aWins ? 15.0f : 45.0f));
        if (La == 2.0f && Lb == 0.5f) { ++bigFights; bigWins += aWins; }
    }
    t.expect(known == 500, "known-draw fixtures: %d of 500 as predicted", known);
    // Size 2 vs .5 (strength x16 before the draws): P(win) = 1 − 1/(2r) for
    // r = 16·curve ratio, ~0.95 over ages 10-100.
    for (int k = 0; k < 400; ++k) {
        Fish a, b;
        a.age = 10.0f + 90.0f * g.unit(); b.age = 10.0f + 90.0f * g.unit();
        a.foodReserves = b.foodReserves = 30.0f;
        kernel::fightOutcome(a, b, 4.0f, 0.25f);
        ++bigFights;
        bigWins += (a.foodReserves > 30.0f);
    }
    t.expect(bigWins * 100 >= bigFights * 88, "size 2 vs .5 won only %d of %d", bigWins, bigFights);
    // Ties (both strengths 0: ages 0 and 120) go to c2, scaled or not.
    for (int k = 0; k < 4; ++k) {
        Fish a, b;
        a.age = (k & 1) ? 120.0f : 0.0f; b.age = (k & 2) ? 120.0f : 0.0f;
        a.foodReserves = b.foodReserves = 30.0f;
        Fish a2 = a, b2 = b;
        kernel::fightOutcome(a, b);
        kernel::fightOutcome(a2, b2, 4.0f, 0.25f);
        t.expect(a.foodReserves == 15.0f && b.foodReserves == 45.0f && a2.foodReserves == 15.0f && b2.foodReserves == 45.0f,
                 "tie (ages %g, %g): c2 must win", a.age, b.age);
    }
    t.note("size 2 vs size .5: the big fish won %d of %d fights", bigWins, bigFights);
}

void testMouth() {
    Test t("mouth");
    struct V { float L, kMouth, below, equal, above; };
    const V vs[] = {{1.0f, 2.0f, 1.9f, 2.0f, 2.1f}, {0.5f, 3.0f, 1.4f, 1.5f, 1.6f}, {2.0f, 0.75f, 1.4f, 1.5f, 1.6f}};
    for (const V& v : vs) {
        for (bool gate : {true, false}) {
            OceanConfig oc;
            oc.mouthGate = gate;
            oc.kMouth = v.kMouth;
            oc.kBuoy = 0.0f;
            oc.wallBand = 0.0f;
            OceanWorld w;
            initQuiet(w, 701, 240.0f, oc, /*capture*/ true);
            w.cfg.minSpeed = 0.0f;
            const int i = addFish(w, {500, 500}, 100.0f, {}, 100.0f / 240.0f);
            w.creatures[i].bodySize = v.L;
            w.creatures[i].speed = 0.0f;
            w.creatures[i].foodReserves = 50.0f;
            const float sz[3] = {v.below, v.equal, v.above};
            const Vec2 at[3] = {{505, 500}, {500, 505}, {500, 500}};
            const float az[3] = {100.0f, 100.0f, 105.0f};
            for (int k = 0; k < 3; ++k) {
                OceanFood f;
                f.pos = at[k]; f.depth = az[k]; f.size = sz[k];
                w.food.push_back(f);
            }
            w.update(0.016f);
            const Fish& c = w.creatures[i];
            if (gate) {
                t.expect(w.food.size() == 1 && w.food[0].size == v.above,
                         "L %g kMouth %g: %zu food left (expected only the size-%g one)", v.L, v.kMouth, w.food.size(), v.above);
                t.expect(c.foodReserves == 60.0f, "L %g: reserves %.9g, expected 50 + 2 x 5", v.L, c.foodReserves);
            } else {
                t.expect(w.food.empty() && c.foodReserves == 65.0f, "gate off: %zu food left, reserves %.9g", w.food.size(),
                         c.foodReserves);
            }
            // Smell: a lone too-big particle is no food to this fish.
            OceanWorld w2;
            initQuiet(w2, 702, 240.0f, oc, true);
            w2.cfg.minSpeed = 0.0f;
            const int j = addFish(w2, {500, 500}, 100.0f, {}, 100.0f / 240.0f);
            w2.creatures[j].bodySize = v.L;
            w2.creatures[j].speed = 0.0f;
            OceanFood big;
            big.pos = {530, 500}; big.depth = 100.0f; big.size = v.above;   // 30 away: smelled, out of reach
            w2.food.push_back(big);
            w2.update(0.016f);
            const float* S = w2.creatures[j].lastSensors;
            if (gate) t.expect(S[FOOD_DENSITY] == 0.0f && S[NEAREST_FOOD_DIST] == 1.0f && w2.food.size() == 1,
                               "gated food smelled: density %.6g dist %.6g", S[FOOD_DENSITY], S[NEAREST_FOOD_DIST]);
            else t.expect(S[FOOD_DENSITY] > 0.0f && S[NEAREST_FOOD_DIST] < 0.31f, "gate off: food not smelled");
        }
    }
}

// Fingerprints every 100 steps of a world built from cfg (the harness's way).
std::vector<ofp::Fingerprint> runPrintsCfg(unsigned seed, const std::string& cfg, int pop, int steps) {
    std::vector<ofp::Fingerprint> out;
    OceanWorld w;
    std::string err;
    if (!ofp::initWorld(w, seed, 1920, 1080, 240.0f, pop, cfg.c_str(), err)) return out;
    out.push_back(ofp::fingerprint(w));
    for (int s = 1; s <= steps; ++s) {
        w.update(0.016f);
        if (s % 100 == 0) out.push_back(ofp::fingerprint(w));
    }
    return out;
}

void testE1Neutral() {
    Test t("e1_neutral");
    // Each variant adds keys that must not change the run: their dynamics
    // hashes (all but cfg) equal the base's at every print.
    struct Base { const char* name; std::string cfg; std::vector<std::pair<const char*, const char*>> vars; };
    const std::string rich = R"("currentStrength":60,"foodDrift":true,"foodPatches":4,"predatorCount":3,"predatorEconomy":true,"maxNeighbors":7)";
    const std::vector<Base> bases = {
        {"bodyModel", rich + R"(,"bodyModel":true)", {
            {"light", R"("lightEnabled":true,"L0":3,"kWater":0.02)"},
            {"wave shape, no waves", R"("waveBand":8,"waveGravity":55)"},
            {"scaled costs at 0", R"("depthCostScaled":true)"},
            {"mouthGate kMouth 2 (size 1 <= 2 x .5)", R"("mouthGate":true,"kMouth":2)"},
        }},
        {"size 1", rich, {
            {"sizeFight", R"("sizeFight":true)"},
            {"sizeDrift (legacy current through the E1 path)", R"("sizeDrift":true)"},
            {"all neutral knobs", R"("sizeFight":true,"sizeDrift":true,"mouthGate":true,"lightEnabled":true,"depthCostScaled":true,"waveBand":5)"},
        }},
    };
    int variants = 0;
    for (const Base& b : bases) {
        const auto ref = runPrintsCfg(91, "{" + b.cfg + "}", 250, 800);
        t.expect(ref.size() == 9, "%s: base run failed", b.name);
        for (const auto& v : b.vars) {
            const auto got = runPrintsCfg(91, "{" + b.cfg + "," + v.second + "}", 250, 800);
            ++variants;
            if (!t.expect(got.size() == ref.size(), "%s / %s: run failed", b.name, v.first)) continue;
            int diff = -1;
            for (size_t i = 0; i < got.size() && diff < 0; ++i) if (!sameDynamics(got[i], ref[i])) diff = (int)i;
            t.expect(diff < 0, "%s / %s: dynamics differ from print %d (step %d)", b.name, v.first, diff, diff * 100);
            t.expect(got[0].cfg != ref[0].cfg, "%s / %s: the cfg hash missed the E1 keys", b.name, v.first);
        }
    }
    t.note("%d variants x 800 steps: every dynamics hash equal to the base's", variants);
}

void testE1Bounds() {
    Test t("e1_bounds");
    struct V { const char* name; unsigned seed; float D; const char* cfg; };
    const V vs[] = {
        {"preset", 1, 240.0f, kE1PresetJson},
        {"strong waves + deep eddies + sizes", 2, 240.0f,
         R"({"waveSpeed":40,"waveBand":6,"deepCurrent":true,"currentStrength":120,"foodDrift":true,"bodyModel":true,"sizeDrift":true,"sizeFight":true,"mouthGate":true,"kMouth":1.5,"predatorCount":4,"predatorEconomy":true,"predatorMinPopulation":2})"},
        {"shallow, max waves", 3, 10.0f,
         R"({"waveSpeed":100,"waveBand":1,"waveGravity":10000,"deepCurrent":true,"currentStrength":80,"foodDrift":true,"predatorCount":3})"},
        {"gyre, toroidal, costs", 4, 600.0f,
         R"({"waveSpeed":12,"deepCurrent":true,"currentStrength":50,"currentMode":1,"toroidal":true,"foodDrift":true,"depthCostScaled":true,"cHold":0.5,"cPress":0.5,"foodDepthMode":1,"foodPatches":4})"},
    };
    long fishSteps = 0, foodMoved = 0;
    for (const V& v : vs) {
        OceanWorld w;
        std::string err;
        if (!t.expect(ofp::initWorld(w, v.seed, 1920, 1080, v.D, 300, v.cfg, err), "%s: %s", v.name, err.c_str())) continue;
        for (int s = 1; s <= 1200; ++s) {
            std::vector<float> fz;
            for (const OceanFood& f : w.food) fz.push_back(f.depth);
            w.update(0.016f);
            for (const Fish& c : w.creatures) {
                ++fishSteps;
                t.expect(c.depth >= 0.0f && c.depth <= w.D && c.pos.x >= 0.0f && c.pos.x < 1920.0f && c.pos.y >= 0.0f &&
                             c.pos.y < 1080.0f, "%s step %d: fish at (%.9g, %.9g, %.9g)", v.name, s, c.pos.x, c.pos.y, c.depth);
            }
            for (size_t k = 0; k < w.food.size(); ++k) {
                const OceanFood& f = w.food[k];
                t.expect(f.depth >= 0.0f && f.depth <= w.D && f.pos.x >= 0.0f && f.pos.x < 1920.0f && f.pos.y >= 0.0f &&
                             f.pos.y < 1080.0f, "%s step %d: food at (%.9g, %.9g, %.9g)", v.name, s, f.pos.x, f.pos.y, f.depth);
            }
            for (const OceanPredator& p : w.predators)
                t.expect(p.depth >= 0.0f && p.depth <= w.D, "%s step %d: predator depth %.9g", v.name, s, p.depth);
            if (s % 100 == 0) t.expect(ofp::countNonFinite(w) == 0, "%s step %d: non-finite state", v.name, s);
            if (s == 1) for (size_t k = 0; k < fz.size() && k < w.food.size(); ++k) foodMoved += (w.food[k].depth != fz[k]);
        }
    }
    t.note("%zu E1 worlds x 1200 steps, %ld fish-steps in bounds; food drifting in depth: %ld", sizeof vs / sizeof vs[0],
           fishSteps, foodMoved);
    t.expect(foodMoved > 0, "the flow never moved food in depth");
}

void testDrawsE1() {
    Test t("draws_e1");
    OceanConfig oc;
    oc.waveSpeed = 8.0f;
    oc.deepCurrent = true;
    oc.sizeDrift = true;
    oc.sizeFight = true;
    oc.mouthGate = true;
    oc.kMouth = 0.7f;
    oc.depthCostScaled = true;
    oc.cHold = 0.3f;
    oc.cPress = 0.2f;
    oc.lightEnabled = true;
    OceanWorld w;
    initQuiet(w, 801, 240.0f, oc, false, false, /*current*/ 50.0f);
    w.cfg.foodDrift = true;
    w.cfg.predatorCount = 4;
    w.cfg.predatorPerception = 0.0f;      // blind: they always wander (two draws each), never chase
    w.cfg.predatorCaptureRadius = 0.0f;
    int nRandom = 0;
    for (int i = 0; i < 40; ++i) {
        std::vector<Gene> g;
        if (i % 3 != 2) g.push_back(mkGene(false, 0, STEER_Z, (i % 3 == 0) ? kStrong : -kStrong));
        const bool rnd = (i % 2 == 0);
        if (rnd) g.push_back(mkGene(false, 0, MOVE_RANDOM, kStrong));
        const int k = addFish(w, {120.0f + 240.0f * (i % 8), 100.0f + 216.0f * (i / 8)}, 240.0f * (float)(i % 9) / 8.0f, g,
                              (float)(i % 3) * 0.5f);
        w.creatures[k].responsiveness = 1.0f;
        w.creatures[k].bodySize = 0.5f + 0.25f * (float)(i % 7);
        nRandom += rnd;
    }
    for (int i = 0; i < 4; ++i) {
        OceanPredator p;
        p.pos = {200.0f + 450.0f * i, 900.0f};
        p.depth = 60.0f * i;
        p.energy = 30.0f;
        w.predators.push_back(p);
    }
    Lcg g(5);
    for (int i = 0; i < 300; ++i) {   // food the flow carries (and some fish eat)
        OceanFood f;
        f.pos = {1920.0f * g.unit(), 1080.0f * g.unit()};
        f.depth = 240.0f * g.unit();
        w.food.push_back(f);
    }
    const long N = (long)w.creatures.size();
    const long expected = N + 3L * nRandom + 2L * 4;   // RANDOM_SENSOR, MOVE_RANDOM x3, predator wander x2
    int bad = 0;
    for (int s = 1; s <= 150; ++s) {
        const RandomGen before = rng;
        w.update(0.016f);
        const long d = drawsBetween(before, rng, 10000);
        bad += !t.expect(d == expected && (long)w.creatures.size() == N, "step %d: %ld draws, expected %ld (pop %zu)", s, d,
                         expected, w.creatures.size());
    }
    // A birth with every E1 knob on draws exactly what it draws without.
    for (unsigned seed : {211u, 212u}) {
        long draws[2] = {-1, -1};
        for (int on = 0; on < 2; ++on) {
            OceanConfig o = on ? oc : OceanConfig{};
            OceanWorld wb;
            initQuiet(wb, seed, 240.0f, o, false, false, 30.0f);
            const std::vector<Gene> gg = {mkGene(false, 0, INTERACT_REPRODUCE, kStrong)};
            const int i1 = addFish(wb, {960, 540}, 100.0f, gg, 0.4f), i2 = addFish(wb, {961, 541}, 110.0f, gg, 0.5f);
            for (int i : {i1, i2}) {
                Fish& f = wb.creatures[i];
                f.age = 10.0f; f.foodReserves = 100.0f; f.reproTimer = 0.0f; f.interactTimer = 0.0f;
            }
            const RandomGen before = rng;
            wb.update(0.016f);
            draws[on] = (wb.creatures.size() == 3) ? drawsBetween(before, rng) : -1;
        }
        t.expect(draws[0] > 0 && draws[0] == draws[1], "seed %u: birth step draws %ld (off) vs %ld (E1 on)", seed, draws[0], draws[1]);
    }
    t.note("150 steps with every E1 feature on: %ld draws/step == N + 3 x MOVE_RANDOM + 2 x predators", expected);
}

void testLight() {
    Test t("light");
    OceanConfig oc;
    oc.lightEnabled = true;
    oc.L0 = 1.7f;
    oc.kWater = 0.006f;
    OceanWorld w;
    initQuiet(w, 901, 240.0f, oc);
    t.expect(w.lightAt(0.0f) == 1.7f, "lightAt(0) %.9g != L0", w.lightAt(0.0f));
    float prev = w.lightAt(0.0f);
    double worst = 0.0;
    for (int k = 1; k <= 240; ++k) {
        const float L = w.lightAt((float)k);
        t.expect(L < prev && L > 0.0f, "light not falling at depth %d", k);
        worst = std::max(worst, std::abs((double)L - 1.7 * std::exp(-0.006 * k)) / 1.7);
        prev = L;
    }
    t.expect(worst < 2e-6, "lightAt off L0·exp(-kWater·d) by %.3g (relative)", worst);
    t.note("L(240) / L0 = %.4f (exp(-1.44) = 0.2369)", w.lightAt(240.0f) / 1.7f);
    // Deep down (kWater 1, the range's end): 1 + expm1f(-x) was exactly 0 for
    // x > 17.33; the direct exp keeps relative precision until e^-x leaves
    // the normal floats (x ~ 87), and falls monotonically.
    {
        OceanConfig od = oc;
        od.kWater = 1.0f;
        OceanWorld wd;
        initQuiet(wd, 903, 240.0f, od);
        t.expect(wd.lightAt(18.0f) > 0.0f && 1.0f + evomath::expm1f(-18.0f) == 0.0f, "lightAt(18) at kWater 1: %.9g",
                 (double)wd.lightAt(18.0f));
        double worstDeep = 0.0;
        float prevL = wd.lightAt(0.0f);
        for (int k = 1; k <= 87 * 16; ++k) {
            const float d = (float)k / 16.0f;
            const float L = wd.lightAt(d);
            t.expect(L > 0.0f && L <= prevL, "kWater 1: light at depth %g = %.9g (above: %.9g)", (double)d, (double)L, (double)prevL);
            worstDeep = std::max(worstDeep, std::abs((double)L / (1.7 * std::exp(-(double)d)) - 1.0));
            prevL = L;
        }
        t.expect(worstDeep < 6e-7, "kWater 1: lightAt off L0·exp(-d) by %.3g (relative) down to depth 87", worstDeep);
    }
#ifndef OCEAN_TESTS_NO_SHIM
    const int initOk = oc_init(902, 1920, 1080, 240.0, 50, R"({"lightEnabled":true,"L0":2.5,"kWater":0.01})");
    t.expect(initOk == 1, "oc_init: %s", oc_last_error());
    t.expect(oc_light_enabled() == 1 && oc_light_l0() == 2.5 && oc_light_kwater() == (double)0.01f, "light exports %d %g %g",
             oc_light_enabled(), oc_light_l0(), oc_light_kwater());
    t.expect(oc_set_param("lightEnabled", 0.0) == 1 && oc_light_enabled() == 0, "lightEnabled 0 via oc_set_param");
    t.expect(oc_init(902, 1920, 1080, 240.0, 50, nullptr) == 1 && oc_light_enabled() == 0, "the default page has light off");
#endif
}

// oceanmath::expf (ocean_math.hpp), the light's portable exp: e^x within a few
// ulp over the whole normal float range, both signs; exact at 0; monotone.
void testExp() {
    Test t("exp");
    t.expect(oceanmath::expf(0.0f) == 1.0f && oceanmath::expf(-0.0f) == 1.0f, "expf(±0) != 1");
    t.expect(std::isnan(oceanmath::expf(NAN)) && oceanmath::expf(-INFINITY) == 0.0f && oceanmath::expf(INFINITY) == INFINITY,
             "expf of NaN / ±inf");
    t.expect(oceanmath::expf(-89.0f) == 0.0f && oceanmath::expf(89.0f) == INFINITY, "expf beyond the float range");
    double worst = 0.0;
    float prev = oceanmath::expf(-87.0f);
    long n = 0;
    for (int k = -87 * 1000 + 1; k <= 88 * 1000; ++k) {
        const float x = (float)k / 1000.0f;
        const float e = oceanmath::expf(x);
        t.expect(e >= prev, "expf not monotone at %.9g", (double)x);
        worst = std::max(worst, std::abs((double)e / std::exp((double)x) - 1.0));
        prev = e;
        ++n;
    }
    t.expect(worst < 4.8e-7, "expf off e^x by %.3g (relative) on [-87, 88]", worst);   // 4 ulp
    t.note("%ld points on [-87, 88]: within 4 ulp of e^x, monotone", n);
}

#ifndef OCEAN_TESTS_NO_SHIM
void testRanges() {
    Test t("ranges");
    struct K { const char* key; double lo, hi; const char* with; };
    const K ks[] = {
        {"kBuoy", -1000, 1000, ""}, {"buoyMutation", 0, 1, ""}, {"pitchMax", 0.001, 100, ""},
        {"vDrag", 0, 10000, ""}, {"wallBand", 0, 100000, ""},
        {"cHold", 0, 100, R"("depthCostScaled":true,)"}, {"cPress", 0, 100, ""},
        {"foodDepthSpread", 0, 1e6, R"("foodDepthMode":1,"foodPatches":3,)"},
        {"waveSpeed", 0, 100, R"("deepCurrent":true,"currentStrength":80,"foodDrift":true,)"},
        {"waveBand", 1, 100000, R"("waveSpeed":100,)"}, {"waveGravity", 0.01, 10000, R"("waveSpeed":100,)"},
        {"L0", 0, 100, R"("lightEnabled":true,)"}, {"kWater", 0, 1, R"("lightEnabled":true,)"},
        {"kMouth", 0.01, 100, R"("mouthGate":true,"bodyModel":true,)"},
        // The Ocean's ranges for SimConfig keys (oceanSimConfigError).
        {"currentStrength", 0, 1000, R"("deepCurrent":true,"waveSpeed":6,"currentMode":1,"foodDrift":true,)"},
        {"currentCore", 0, 100000, R"("currentStrength":80,"foodDrift":true,)"},
        {"currentDrift", -100, 100, R"("currentStrength":80,"foodDrift":true,"deepCurrent":true,)"},
        {"currentGyreEps", -1, 1, R"("currentStrength":80,"currentMode":1,"deepCurrent":true,"foodDrift":true,)"},
        {"foodPatchRadius", 0, 100000, R"("toroidal":true,"foodPatches":3,)"},
        {"foodSpawnBase", -10000, 10000, ""}, {"foodSpawnAmp", -10000, 10000, ""},
        {"maxSpeed", 30, 2000, ""}, {"predatorSpeed", 0, 2000, R"("predatorCount":3,)"},
        {"maxTurnRate", -10000, 10000, R"("triangularMotion":true,"bodyModel":true,)"},
        // the food lifetime (ocean-vision): up to kOceanMaxFoodLife
        {"foodLife", 0, 3600, ""},
        // the energies, [-1e6, 1e6] (kOceanMaxEnergy); fish at the fastest
        // speed / with many genes / deep where it matters (predators: their
        // economy on, at most 50 of them: reproEnergy -1e6 buds every step)
        {"foodEnergy", -1e6, 1e6, R"("pickupRadius":1000000,)"},
        {"metabolicRate", -1e6, 1e6, R"("bodyModel":true,"depthCostScaled":true,"cHold":100,"cPress":100,)"},
        {"geneCost", -1e6, 1e6, ""}, {"moveCost", -1e6, 1e6, R"("minSpeed":2000,"maxSpeed":2000,)"},
        {"reproEnergy", -1e6, 1e6, ""}, {"newbornEnergy", -1e6, 1e6, R"("reproEnergy":0,)"},
        {"predatorMetabolism", -1e6, 1e6, R"("predatorEconomy":true,"predatorMaxPopulation":50,)"},
        {"predatorMoveCost", -1e6, 1e6, R"("predatorEconomy":true,"predatorMaxPopulation":50,"predatorSpeed":2000,)"},
        {"predatorReproEnergy", -1e6, 1e6, R"("predatorEconomy":true,"predatorMaxPopulation":50,)"},
        {"predatorNewbornEnergy", -1e6, 1e6, R"("predatorEconomy":true,"predatorMaxPopulation":50,"predatorReproEnergy":0,)"},
        {"predatorMeal", -1e6, 1e6, R"("predatorEconomy":true,"predatorMaxPopulation":50,"predatorCooldown":0,)"},
    };
    auto cfgOf = [](const K& k, double v) {
        char num[40];
        std::snprintf(num, sizeof num, "%.9g", v);
        return std::string("{") + k.with + R"("predatorCount":2,")" + k.key + "\":" + num + "}";
    };
    int accepted = 0, refused = 0, runs = 0;
    for (const K& k : ks) {
        for (double v : {k.lo, k.hi}) {
            const std::string c = cfgOf(k, v);
            const int initOk = oc_init(1001, 1920, 1080, 240.0, 100, c.c_str());
            if (!t.expect(initOk == 1, "%s refused: %s", c.c_str(), oc_last_error())) continue;
            ++accepted;
            oc_step(300);
            ++runs;
            // finite now, and nothing removed on the way held a non-finite float
            t.expect(ofp::countNonFinite(*g_world) == 0 && g_world->totalNonFiniteRemoved == 0,
                     "%s: non-finite state after 300 steps (%lld floats in removed objects)", c.c_str(),
                     g_world->totalNonFiniteRemoved);
            for (const Fish& f : g_world->creatures)
                if (!t.expect(f.depth >= 0.0f && f.depth <= g_world->D, "%s: depth %.9g", c.c_str(), f.depth)) break;
        }
        const double below = k.lo - std::max(1e-6, 1e-3 * std::abs(k.lo)), above = k.hi + std::max(1e-6, 1e-3 * std::abs(k.hi));
        for (double v : {below, above, 1e39, -1e39}) {
            const std::string c = cfgOf(k, v);
            refused += t.expect(oc_init(1001, 1920, 1080, 240.0, 100, c.c_str()) == 0, "%s accepted", c.c_str());
        }
    }
    // The hole the harness found, and the bool / mode keys.
    for (const char* c : {R"({"kBuoy":-1e37})", R"({"kBuoy":1e37})", R"({"vDrag":1e30})", R"({"pitchMax":1e-9})",
                          R"({"deepCurrent":2})", R"({"sizeDrift":"yes"})", R"({"mouthGate":0.5})", R"({"foodDepthMode":2})",
                          R"({"foodDepthMode":0.5})", R"({"foodDepthMode":1e300})", R"({"waveBand":0})",
                          // the current's int keys, and the config that hung wrapCoord
                          R"({"currentMode":2})", R"({"currentMode":-1})", R"({"currentEddies":101})", R"({"currentEddies":-1})",
                          R"({"currentMode":1,"currentStrength":1e20,"deepCurrent":true,"foodDrift":true,"targetFood":1})",
                          // finite energies that overflowed (the Codex audit): reserves +inf from four
                          // items, a step's cost inf (reserves -inf), a predator's energy inf
                          R"({"minPopulation":0,"pickupRadius":1000000,"foodEnergy":1e38})",
                          R"({"minPopulation":0,"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"minSpeed":30,"maxSpeed":30,"moveCost":1e38})",
                          R"({"geneCost":1e38})", R"({"predatorCount":4,"predatorEconomy":true,"predatorMeal":3e38})",
                          R"({"predatorCount":2,"predatorEconomy":true,"predatorMoveCost":1e38})"})
        refused += t.expect(oc_init(1002, 1920, 1080, 240.0, 100, c) == 0, "%s accepted", c);
    for (const char* c : {R"({"deepCurrent":1,"sizeDrift":true,"mouthGate":0,"foodDepthMode":1})"}) {
        const int initOk = oc_init(1002, 1920, 1080, 240.0, 100, c);
        accepted += t.expect(initOk == 1, "%s refused: %s", c, oc_last_error());
    }
    // The current's int keys at their ends, run.
    for (const char* c : {R"({"currentEddies":100,"currentStrength":1000,"foodDrift":true,"targetFood":300,"deepCurrent":true})",
                          R"({"currentEddies":0,"currentStrength":1000,"foodDrift":true,"currentMode":0})"}) {
        const int initOk = oc_init(1006, 1920, 1080, 240.0, 100, c);
        if (!t.expect(initOk == 1, "%s refused: %s", c, oc_last_error())) continue;
        ++accepted;
        oc_step(300);
        ++runs;
        t.expect(ofp::countNonFinite(*g_world) == 0, "%s: non-finite state after 300 steps", c);
    }
    // The sea's depth (oc_init's argument): [10, 100000].
    refused += t.expect(oc_init(1003, 1920, 1080, 100001.0, 50, nullptr) == 0, "depth 100001 accepted");
    {
        const int initOk = oc_init(1003, 1920, 1080, 100000.0, 50, nullptr);
        accepted += t.expect(initOk == 1, "depth 100000 refused: %s", oc_last_error());
    }
    // Live: refused as stored, the world unchanged.
    t.expect(oc_init(1004, 1920, 1080, 240.0, 100, nullptr) == 1, "oc_init");
    const ofp::Fingerprint before = ofp::fingerprint(*g_world);
    struct S { const char* k; double v; };
    for (const S& s : {S{"kBuoy", 1e37}, S{"kBuoy", 1000.5}, S{"waveSpeed", 101}, S{"waveBand", 0.5}, S{"mouthGate", 0.5},
                       S{"deepCurrent", 2}, S{"kWater", 1.5}, S{"cHold", 1e9}, S{"pitchMax", 1e-5}})
        refused += t.expect(oc_set_param(s.k, s.v) == 0, "oc_set_param(%s, %g) accepted", s.k, s.v);
    t.expect(ofp::fingerprint(*g_world) == before, "a refused oc_set_param changed the world");
    for (const S& s : {S{"kBuoy", 1000}, S{"waveSpeed", 100}, S{"waveBand", 1}, S{"mouthGate", 1}, S{"deepCurrent", 1},
                       S{"kWater", 1}, S{"cHold", 100}, S{"sizeFight", 0}}) {
        const int setOk = oc_set_param(s.k, s.v);
        accepted += t.expect(setOk == 1, "oc_set_param(%s, %g) refused: %s", s.k, s.v, oc_last_error());
    }
    oc_step(300);
    t.expect(ofp::countNonFinite(*g_world) == 0, "live extremes: non-finite state");
    // The flow's extreme corners: the smallest / largest world, waves at their limits.
    for (int big = 0; big < 2; ++big) {
        const char* c = R"({"waveSpeed":100,"waveBand":1,"waveGravity":10000,"deepCurrent":true,"currentStrength":80,"foodDrift":true,"predatorCount":2})";
        const int W = big ? 20000 : 100;
        const int initOk = oc_init(1005, W, W, big ? 100000.0 : 10.0, 60, c);
        if (!t.expect(initOk == 1, "corner %d: %s", big, oc_last_error())) continue;
        oc_step(200);
        ++runs;
        t.expect(ofp::countNonFinite(*g_world) == 0, "corner world %dx%d: non-finite state", W, W);
        for (const OceanFood& f : g_world->food)
            if (!t.expect(f.pos.x >= 0.0f && f.pos.x < (float)W && f.pos.y >= 0.0f && f.pos.y < (float)W, "corner %d: food off the map", big)) break;
    }
    t.note("%d configs accepted, %d refused; %d runs at range ends, all finite", accepted, refused, runs);
}

// Bool keys: the shared reader's boolOr kept the old value for anything but a
// JSON bool ({"toroidal":1} ran with walls while the page showed it on), and
// readOceanConfig's readBool checked only a key's first occurrence. Now a
// SimConfig switch must be true / false and an Ocean one true / false / 0 / 1
// (its live encoding), at every occurrence; anything else is refused with the
// key named. Every SimConfig and Ocean bool key by member (so the compiler
// checks each is a bool and that the reader really sets it), then oc_init.
void testShimBools() {
    Test t("shim_bools");
    const struct { const char* key; bool SimConfig::*m; } sims[] = {
        {"toroidal", &SimConfig::toroidal}, {"bodyModel", &SimConfig::bodyModel},
        {"triangularMotion", &SimConfig::triangularMotion}, {"foodDrift", &SimConfig::foodDrift},
        {"predatorEconomy", &SimConfig::predatorEconomy}, {"predatorInheritance", &SimConfig::predatorInheritance},
        {"fastTanh", &SimConfig::fastTanh},
    };
    const struct { const char* key; bool OceanConfig::*m; } oceans[] = {
        {"deepCurrent", &OceanConfig::deepCurrent}, {"lightEnabled", &OceanConfig::lightEnabled},
        {"depthCostScaled", &OceanConfig::depthCostScaled}, {"sizeDrift", &OceanConfig::sizeDrift},
        {"sizeFight", &OceanConfig::sizeFight}, {"mouthGate", &OceanConfig::mouthGate},
        {"walls", &OceanConfig::walls},
    };
    t.expect(sizeof sims / sizeof sims[0] == sizeof kSimConfigBoolKeys / sizeof kSimConfigBoolKeys[0] &&
                 sizeof oceans / sizeof oceans[0] == sizeof kOceanBoolKeys / sizeof kOceanBoolKeys[0],
             "the bool-key lists and the member tables differ in size");
    using Good = std::vector<std::pair<const char*, bool>>;
    const Good simGood = {{"true", true}, {"false", false}};
    const Good oceanGood = {{"true", true}, {"false", false}, {"1", true}, {"0", false}, {"1.0", true}, {"-0", false}};
    std::vector<const char*> bad = {"2", "0.5", "-1", "1e300", "\"yes\"", "\"true\"", "null", "[1]", "{}"};
    std::vector<const char*> simBad = bad;
    for (const char* n : {"1", "0", "1.0", "-0"}) simBad.push_back(n);   // a SimConfig switch is a JSON bool
    int accepted = 0, refused = 0;
    // One checker for both tables: get(sc, oc) is the key's stored bool.
    auto check = [&](const char* key, const Good& good, const std::vector<const char*>& bad, auto get, auto set) {
        t.expect(isSimConfigBoolKey(key) || isOceanBoolKey(key), "%s is in neither bool-key list", key);
        for (const auto& g : good) {
            SimConfig sc;
            OceanConfig oc;
            set(sc, oc, !g.second);   // the opposite first: the read must set it
            std::string err;
            const std::string j = std::string("{\"") + key + "\":" + g.first + "}";
            accepted += t.expect(readOceanJson(j.c_str(), sc, oc, err) && get(sc, oc) == g.second, "%s: refused or read %d (%s)",
                                 j.c_str(), (int)get(sc, oc), err.c_str());
        }
        for (const char* b : bad)
            for (int form = 0; form < 3; ++form) {   // alone, after a good occurrence, before one
                SimConfig sc;
                OceanConfig oc;
                const bool before = get(sc, oc);
                std::string err;
                const std::string kb = std::string("\"") + key + "\":" + b, kg = std::string("\"") + key + "\":true";
                const std::string j = "{" + (form == 0 ? kb : form == 1 ? kg + "," + kb : kb + "," + kg) + "}";
                refused += t.expect(!readOceanJson(j.c_str(), sc, oc, err) && get(sc, oc) == before &&
                                        err.find(key) != std::string::npos,
                                    "%s: accepted, or the error does not name the key (%s)", j.c_str(), err.c_str());
            }
    };
    for (const auto& k : sims)
        check(k.key, simGood, simBad, [&](const SimConfig& sc, const OceanConfig&) { return sc.*k.m; },
              [&](SimConfig& sc, OceanConfig&, bool v) { sc.*k.m = v; });
    for (const auto& k : oceans)
        check(k.key, oceanGood, bad, [&](const SimConfig&, const OceanConfig& oc) { return oc.*k.m; },
              [&](SimConfig&, OceanConfig& oc, bool v) { oc.*k.m = v; });
    // Through oc_init: the switches as JSON bools (and an Ocean one as 1) are
    // stored; {"toroidal":1} (it used to run with walls), 2, a string, null and
    // a bad repeat are refused, the world kept.
    {
        const int a = oc_init(1309, 1920, 1080, 240.0, 50, R"({"toroidal":true,"foodDrift":true,"bodyModel":false,"deepCurrent":1})");
        t.expect(a == 1 && g_world->cfg.toroidal && g_world->cfg.foodDrift && !g_world->cfg.bodyModel && g_world->ocfg.deepCurrent,
                 "oc_init {toroidal true, foodDrift true, bodyModel false, deepCurrent 1}: %s",
                 a ? "not stored as on / on / off / on" : oc_last_error());
        const ofp::Fingerprint kept = ofp::fingerprint(*g_world);
        for (const char* c : {R"({"toroidal":1})", R"({"foodDrift":0})", R"({"toroidal":2})", R"({"predatorEconomy":"yes"})",
                              R"({"fastTanh":null})", R"({"deepCurrent":true,"deepCurrent":"x"})",
                              R"({"triangularMotion":true,"triangularMotion":0.5})"}) {
            const int rc = oc_init(1310, 1920, 1080, 240.0, 50, c);
            const std::string e = oc_last_error();
            refused += t.expect(rc == 0 && e.find("true / false") != std::string::npos, "oc_init %s: rc %d (%s)", c, rc, e.c_str());
        }
        t.expect(ofp::fingerprint(*g_world) == kept, "a refused oc_init changed the world");
    }
    t.note("%d bool values read, %d refused (every key: alone, and repeated before / after a good value)", accepted, refused);
}

// Integer knobs and the values that reach an int conversion (the Codex
// determinism hunt: oc_set_param wrote 2147483647 as "2.14748365e+09", an
// undefined (int) cast in the shared JSON reader; foodSpawnBase 1e20 reached
// (int)foodRate while stepping).
void testShimInts() {
    Test t("shim_ints");
    struct S2 { const char* k; double v; };
    // Every int-typed SimConfig key, by member (so the compiler checks each is
    // an int): kSimConfigIntKeys lists exactly these.
    const struct { const char* key; int SimConfig::*m; } ints[] = {
        {"reproWindow", &SimConfig::reproWindow}, {"reproMinCluster", &SimConfig::reproMinCluster},
        {"minPopulation", &SimConfig::minPopulation}, {"maxPopulation", &SimConfig::maxPopulation},
        {"targetFood", &SimConfig::targetFood}, {"maxNeighbors", &SimConfig::maxNeighbors},
        {"genomeMinLength", &SimConfig::genomeMinLength}, {"genomeMaxLength", &SimConfig::genomeMaxLength},
        {"genomeInitMin", &SimConfig::genomeInitMin}, {"genomeInitMax", &SimConfig::genomeInitMax},
        {"currentMode", &SimConfig::currentMode}, {"currentEddies", &SimConfig::currentEddies},
        {"foodPatches", &SimConfig::foodPatches}, {"predatorCount", &SimConfig::predatorCount},
        {"predatorMinPopulation", &SimConfig::predatorMinPopulation},
        {"predatorMaxPopulation", &SimConfig::predatorMaxPopulation},
    };
    t.expect(sizeof(ints) / sizeof(ints[0]) == sizeof(kSimConfigIntKeys) / sizeof(kSimConfigIntKeys[0]),
             "kSimConfigIntKeys has %zu keys, the member table %zu", sizeof(kSimConfigIntKeys) / sizeof(kSimConfigIntKeys[0]),
             sizeof(ints) / sizeof(ints[0]));
    for (const auto& k : ints) {
        t.expect(isSimConfigIntKey(k.key), "%s is not in kSimConfigIntKeys", k.key);
        // The reader really reads it; whole numbers to the range ends read
        // exactly; a fraction, or one past either end, is refused before the
        // cast, the config untouched.
        for (const auto& v : {std::pair<const char*, int>{"3", 3}, {"-3", -3}, {"2.0", 2}, {"1e3", 1000}, {"-0", 0},
                              {"2147483647", 2147483647}, {"-2147483648", -2147483647 - 1}}) {
            SimConfig sc;
            OceanConfig oc;
            std::string err;
            const std::string j = std::string("{\"") + k.key + "\":" + v.first + "}";
            t.expect(readOceanJson(j.c_str(), sc, oc, err) && sc.*k.m == v.second, "%s: read %d, want %d (%s)", j.c_str(), sc.*k.m,
                     v.second, err.c_str());
        }
        for (const char* v : {"0.5", "3.75", "-3.75", "1e-300", "2147483647.5", "-2147483648.5", "2147483648", "-2147483649",
                              "1e300", "-1e300", "1e999"}) {
            SimConfig sc, before;
            OceanConfig oc;
            std::string err;
            const std::string j = std::string("{\"") + k.key + "\":" + v + "}";
            t.expect(!readOceanJson(j.c_str(), sc, oc, err) && sc.*k.m == before.*k.m && !err.empty(), "%s accepted", j.c_str());
        }
    }
    // A repeated key: every occurrence is checked, not only the one the reader takes.
    // A number past a double's range (1e400: strtod's ±inf) in either occurrence,
    // as the page now passes it on (web/ocean_handoff.js cfgJson), SimConfig's int
    // key and the Ocean's alike.
    for (const char* c : {R"({"predatorCount":2,"predatorCount":3e9})", R"({"maxPopulation":2147483648})",
                          R"({"foodPatches":-1e10})", R"({"minPopulation":1e999})", R"({"currentMode":0.5})",
                          R"({"currentMode":1e300})", R"({"currentEddies":2.5})", R"({"predatorCount":2,"predatorCount":2.5})",
                          R"({"maxPopulation":300,"maxPopulation":1e400})", R"({"maxPopulation":1e400,"maxPopulation":300})",
                          R"({"maxPopulation":300,"maxPopulation":-1e400})", R"({"appearance":3,"appearance":1e400})",
                          R"({"appearance":1e400,"appearance":3})"}) {
        const int initRc = oc_init(1301, 1920, 1080, 240.0, 50, c);   // before oc_last_error() is read
        t.expect(initRc == 0 && std::strstr(oc_last_error(), "whole number"), "%s: %s", c, oc_last_error());
    }
    {
        const int initRc = oc_init(1301, 1920, 1080, 240.0, 50, R"({"maxPopulation":2147483647,"predatorMaxPopulation":2147483647})");
        t.expect(initRc == 1 && g_world->cfg.maxPopulation == 2147483647 && g_world->cfg.predatorMaxPopulation == 2147483647,
                 "INT_MAX through oc_init: %s", oc_last_error());
    }

    // oc_set_param: an int knob reaches the reader as its exact integer.
    {
        const int initRc = oc_init(1302, 1920, 1080, 240.0, 100, nullptr);
        t.expect(initRc == 1, "oc_init: %s", oc_last_error());
    }
    for (const char* k : {"maxPopulation", "predatorMaxPopulation", "minPopulation"}) {
        const int want = std::strcmp(k, "minPopulation") == 0 ? 7 : 2147483647;
        const double v = (double)want;
        const int setRc = oc_set_param(k, v);
        t.expect(setRc == 1, "oc_set_param(%s, %.17g) refused: %s", k, v, oc_last_error());
        const int got = std::strcmp(k, "maxPopulation") == 0 ? g_world->cfg.maxPopulation
                      : std::strcmp(k, "predatorMaxPopulation") == 0 ? g_world->cfg.predatorMaxPopulation : g_world->cfg.minPopulation;
        t.expect(got == want, "oc_set_param(%s, %.17g) stored %d, want %d", k, v, got, want);
    }
    for (const S2& s : {S2{"maxPopulation", 2147483648.0}, S2{"maxPopulation", 0.5}, S2{"minPopulation", 7.9}, S2{"targetFood", 100.25}}) {
        const int setRc = oc_set_param(s.k, s.v);
        t.expect(setRc == 0 && std::strstr(oc_last_error(), "whole number"), "oc_set_param(%s, %.17g): %s", s.k, s.v, oc_last_error());
    }
    t.expect(g_world->cfg.minPopulation == 7, "a refused int change was stored");
    oc_step(100);
    t.expect(ofp::countNonFinite(*g_world) == 0, "non-finite after the int changes");

    // Values that reach an int conversion while stepping: refused, at init and live.
    for (const char* c : {R"({"foodSpawnBase":1e20})", R"({"foodSpawnAmp":-1e20})", R"({"foodSpawnBase":10001})",
                          R"({"targetFood":1000001})", R"({"targetFood":-1})", R"({"maxSpeed":2000.5})", R"({"maxSpeed":1e30})",
                          R"({"predatorSpeed":-1})", R"({"predatorSpeed":1e30,"predatorCount":2})",
                          R"({"predatorPerception":1e30,"predatorCount":2})", R"({"perceptionRadius":2e6})",
                          R"({"pickupRadius":1e7})", R"({"interactRadius":1e7})", R"({"predatorCaptureRadius":1e7})"})
        t.expect(oc_init(1303, 1920, 1080, 240.0, 50, c) == 0, "%s accepted", c);
    {
        const int initRc = oc_init(1304, 1920, 1080, 240.0, 100, nullptr);
        t.expect(initRc == 1, "oc_init: %s", oc_last_error());
    }
    const ofp::Fingerprint before = ofp::fingerprint(*g_world);
    struct S { const char* k; double v; };
    for (const S& s : {S{"foodSpawnBase", 1e20}, S{"foodSpawnAmp", 1e5}, S{"targetFood", 2147483647}, S{"targetFood", 1000001},
                       S{"maxSpeed", 1e30}, S{"maxSpeed", 2001}})
        t.expect(oc_set_param(s.k, s.v) == 0, "oc_set_param(%s, %g) accepted", s.k, s.v);
    t.expect(ofp::fingerprint(*g_world) == before, "a refused oc_set_param changed the world");
    // The ends run, and fish / predators stay in the world (one step < the smallest world).
    for (const char* c : {R"({"maxSpeed":2000,"minSpeed":0,"predatorCount":3,"predatorSpeed":2000})",
                          R"({"maxSpeed":2000,"minSpeed":2000,"triangularMotion":true,"bodyModel":true,"predatorCount":3,"predatorSpeed":2000,"toroidal":true,"perceptionRadius":40,"predatorPerception":40})",
                          R"({"predatorPerception":1000000,"predatorCount":2,"targetFood":1000000,"foodSpawnBase":0,"foodSpawnAmp":0})"}) {
        const int initRc = oc_init(1305, 100, 100, 240.0, 40, c);
        if (!t.expect(initRc == 1, "%s refused: %s", c, oc_last_error())) continue;
        bool inside = true;
        for (int s = 0; s < 100 && inside; ++s) {
            oc_step(1);
            for (const Fish& f : g_world->creatures) inside &= f.pos.x >= 0.0f && f.pos.x < 100.0f && f.pos.y >= 0.0f && f.pos.y < 100.0f;
            for (const OceanPredator& p : g_world->predators) inside &= p.pos.x >= 0.0f && p.pos.x < 100.0f && p.pos.y >= 0.0f && p.pos.y < 100.0f;
        }
        t.expect(inside && ofp::countNonFinite(*g_world) == 0, "%s in a 100 x 100 world: a position left the world or went non-finite", c);
    }

    // Every other float the step reads must be finite (JSON 1e39 is an infinite
    // float; maxTurnRate inf made a NaN heading), and the counts / sizes that
    // size allocations have ceilings: refused (the world kept), live too; just
    // under, accepted.
    {
        const int initRc = oc_init(1306, 1920, 1080, 240.0, 50, nullptr);
        t.expect(initRc == 1, "oc_init: %s", oc_last_error());
    }
    const ofp::Fingerprint kept = ofp::fingerprint(*g_world);
    int refusedNew = 0;
    for (const char* c : {R"({"triangularMotion":true,"maxTurnRate":1e39})", R"({"interactCooldown":1e39})", R"({"reproCooldown":-1e39})",
                          R"({"predatorCount":2,"predatorCooldown":1e39})", R"({"predatorEconomy":true,"predatorMetabolism":1e39})",
                          R"({"predatorMoveCost":-1e39})", R"({"predatorReproEnergy":1e39})", R"({"predatorNewbornEnergy":1e39})",
                          R"({"predatorMeal":1e39})", R"({"predatorMaxAge":1e39})", R"({"minPopulation":100001})",
                          R"({"predatorCount":100001})", R"({"foodPatches":100001})",
                          // arithmetic-safe motion bounds (the live-code audit, finding 4): 3e38 x 4/3
                          // overflowed; OWN_SPEED = 80 / 1e-38 was inf on the first captured step
                          R"({"triangularMotion":true,"maxTurnRate":3e38})", R"({"maxTurnRate":-10001})",
                          R"({"minPopulation":0,"minSpeed":0,"maxSpeed":1e-38})", R"({"minSpeed":0,"maxSpeed":0.0099})",
                          // the shared clamp raises only a finite radius to 1 (PR #34 review): -inf
                          // (-1e400, or -1e39 as a float) was stored as 1, now refused as NaN / +inf are
                          R"({"perceptionRadius":-1e400})", R"({"perceptionRadius":-1e39})", R"({"perceptionRadius":1e400})",
                          R"({"perceptionRadius":-1e400,"perceptionRadius":100})"}) {
        const int initRc = oc_init(1307, 1920, 1080, 240.0, 50, c);
        refusedNew += t.expect(initRc == 0, "%s accepted", c);
        if (std::strstr(c, "perceptionRadius"))
            t.expect(std::strstr(oc_last_error(), "perceptionRadius") != nullptr, "%s: refused without naming the radius (%s)", c,
                     oc_last_error());
    }
    {   // the probe's builder too (tools/ocean_probe.cpp: the same clamp, then the radius check)
        OceanWorld pw;
        const std::string perr = probeInitWorld(pw, 1307, 1920, 1080, 240.0, 50, false, R"({"perceptionRadius":-1e400})");
        refusedNew += t.expect(perr.find("perceptionRadius") != std::string::npos, "the probe took perceptionRadius -1e400 (%s)",
                               perr.c_str());
    }
    const struct { int W, H, pop; const char* cfg; } dims[] = {
        {100001, 1080, 50, nullptr}, {1920, 100001, 50, nullptr}, {1920, 1080, 100001, nullptr}, {99, 1080, 50, nullptr},
        {6000, 3000, 50, R"({"perceptionRadius":1,"interactRadius":1,"pickupRadius":1})"},   // 18M grid cells > 2^24
    };
    for (const auto& dm : dims) {
        const int initRc = oc_init(1307, dm.W, dm.H, 240.0, dm.pop, dm.cfg);
        refusedNew += t.expect(initRc == 0, "oc_init %d x %d, %d founders (%s) accepted", dm.W, dm.H, dm.pop, dm.cfg ? dm.cfg : "{}");
    }
    {
        const int setRc = oc_set_param("minPopulation", 100001.0);
        refusedNew += t.expect(setRc == 0, "oc_set_param(minPopulation, 100001) accepted");
    }
    t.expect(ofp::fingerprint(*g_world) == kept, "a refused oc_init / oc_set_param changed the world");
    int acceptedEdge = 0;
    for (const char* c : {R"({"triangularMotion":true,"maxTurnRate":10000})", R"({"triangularMotion":true,"maxTurnRate":-10000})",
                          R"({"minSpeed":0,"maxSpeed":0.01})", R"({"minPopulation":100000,"predatorCount":3000,"foodPatches":100000})",
                          R"({"perceptionRadius":2,"interactRadius":1,"pickupRadius":1})"}) {
        const int initRc = oc_init(1308, 1920, 1080, 240.0, 50, c);
        acceptedEdge += t.expect(initRc == 1, "%s refused: %s", c, oc_last_error());
    }
    for (const char* c : {R"({"perceptionRadius":-5})", R"({"perceptionRadius":-3e38})", R"({"perceptionRadius":0.5})"}) {
        // a finite radius below 1 is still raised to 1, as before
        const int initRc = oc_init(1308, 1920, 1080, 240.0, 50, c);
        acceptedEdge += t.expect(initRc == 1 && g_world->cfg.perceptionRadius == 1.0f, "%s: rc %d, radius %.9g (want 1): %s", c, initRc,
                                 initRc ? (double)g_world->cfg.perceptionRadius : 0.0, oc_last_error());
    }
    {
        const int initRc = oc_init(1308, 100000, 1080, 240.0, 50, nullptr);
        acceptedEdge += t.expect(initRc == 1, "a 100000 x 1080 world refused: %s", oc_last_error());
        const int setRc = oc_set_param("minPopulation", 100000.0);
        acceptedEdge += t.expect(setRc == 1, "oc_set_param(minPopulation, 100000) refused: %s", oc_last_error());
    }
    {
        const int initRc = oc_init(1309, 1920, 1080, 240.0, 50, nullptr);   // release the big worlds
        t.expect(initRc == 1, "oc_init: %s", oc_last_error());
    }
    t.note("non-finite floats / allocation ceilings: %d refused, %d at the edge accepted", refusedNew, acceptedEdge);
}

// The live-code audit's finding 4, stepped: accepted finite movement settings
// must keep the state finite. (a) The smallest accepted maxSpeed (0.01) with
// a founder at its starting speed 80: the first captured step's OWN_SPEED is
// 80 / 0.01, finite (1e-38 gave inf; refused now). (b) Triangular motion at
// the largest accepted |maxTurnRate| (1e4) with the shortest body (bodyElong
// 0.5, turnFactor 4/3): every float finite for 200 steps, both signs, with
// and without steering (3e38 x 4/3 overflowed, then 0 x inf = NaN).
void testMotionBounds() {
    Test t("motion_bounds");
    {
        const int rc = oc_init(1401, 1920, 1080, 240.0, 1, R"({"minPopulation":0,"minSpeed":0,"maxSpeed":0.01,"targetFood":0})");
        if (t.expect(rc == 1, "maxSpeed 0.01 refused: %s", oc_last_error())) {
            oc_set_capture(1);
            const float s0 = g_world->creatures.empty() ? 0.0f : g_world->creatures[0].speed;
            oc_step(1);
            const bool any = !g_world->creatures.empty();
            const float own = any ? g_world->creatures[0].lastSensors[OWN_SPEED] : 0.0f;
            t.expect(any && s0 == 80.0f && std::isfinite(own) && own == 80.0f / 0.01f,
                     "first captured step: founder speed %g, OWN_SPEED %g (want 80 / 0.01)", (double)s0, (double)own);
            t.expect(ofp::countNonFinite(*g_world) == 0, "maxSpeed 0.01: non-finite state after one step");
            oc_step(100);
            t.expect(ofp::countNonFinite(*g_world) == 0 && g_world->totalNonFiniteRemoved == 0, "maxSpeed 0.01: non-finite after 100 steps");
        }
        const int bad = oc_init(1401, 1920, 1080, 240.0, 1, R"({"minPopulation":0,"minSpeed":0,"maxSpeed":1e-38})");
        t.expect(bad == 0, "maxSpeed 1e-38 accepted");
    }
    for (double rate : {10000.0, -10000.0}) {
        for (int steer = 0; steer < 2; ++steer) {
            char cfg[200];
            std::snprintf(cfg, sizeof cfg, R"({"triangularMotion":true,"bodyModel":true,"maxTurnRate":%.9g,"minPopulation":0})", rate);
            const int rc = oc_init(1402 + steer, 1920, 1080, 240.0, 40, cfg);
            if (!t.expect(rc == 1, "%s refused: %s", cfg, oc_last_error())) continue;
            for (Fish& f : g_world->creatures) {
                f.bodyElong = 0.5f;   // turnFactor 4/3 (the shortest legal body)
                if (!steer) f.nnet.flat.clear();   // no connections: every action 0 (no steering)
            }
            oc_set_capture(1);
            oc_step(200);
            t.expect(ofp::countNonFinite(*g_world) == 0 && g_world->totalNonFiniteRemoved == 0,
                     "%s, bodyElong 0.5, %s: non-finite state after 200 steps", cfg, steer ? "wired" : "no steering");
        }
    }
    t.expect(oc_init(1404, 1920, 1080, 240.0, 40, R"({"triangularMotion":true,"maxTurnRate":3e38})") == 0, "maxTurnRate 3e38 accepted");
    t.expect(oc_init(1405, 1920, 1080, 240.0, 10, nullptr) == 1, "oc_init: %s", oc_last_error());   // leave a small world
}
#endif

void testE1Hash() {
    Test t("e1_hash");
    OceanWorld w;
    std::string err;
    ofp::initWorld(w, 1101, 1920, 1080, 240.0f, 150, R"({"waveSpeed":5,"deepCurrent":true,"currentStrength":30,"predatorCount":2})", err);
    for (int s = 0; s < 40; ++s) w.update(0.016f);
    const ofp::Fingerprint base = ofp::fingerprint(w);
    t.expect(w.waveClockStarted(), "the wave clock did not run");
    auto only = [&](const char* what, std::uint64_t ofp::Fingerprint::*field) {
        const ofp::Fingerprint p = ofp::fingerprint(w);
        bool othersSame = true;
        for (auto f : ofp::kSections)   // all but cur (a wave knob also moves the sampled flow)
            if (f != field && f != &ofp::Fingerprint::cur) othersSame &= (p.*f == base.*f);
        t.expect(p.*field != base.*field && othersSame, "a 1-ulp change in %s: hash %s", what,
                 p.*field == base.*field ? "unchanged" : "changed other sections too");
    };
    // An E1 knob that does not move the flow (light): cfg only.
    { const float keep = w.ocfg.kWater; w.ocfg.kWater = std::nextafter(keep, 1.0f); only("kWater", &ofp::Fingerprint::cfg); w.ocfg.kWater = keep; }
    { const bool keep = w.ocfg.mouthGate; w.ocfg.mouthGate = !keep; only("mouthGate", &ofp::Fingerprint::cfg); w.ocfg.mouthGate = keep; }
    { const float keep = w.food[3].size; w.food[3].size = 1.5f; only("food size", &ofp::Fingerprint::food); w.food[3].size = keep; }
    t.expect(ofp::fingerprint(w) == base, "restoring did not restore the hash");
    // The wave clock is in ctr (and moves the sampled flow in cur).
    OceanWorld w2;
    ofp::initWorld(w2, 1101, 1920, 1080, 240.0f, 150, R"({"waveSpeed":5,"deepCurrent":true,"currentStrength":30,"predatorCount":2})", err);
    for (int s = 0; s < 40; ++s) w2.update(0.016f);
    t.expect(ofp::fingerprint(w2) == base, "same world twice differs");
    // An OFF world never hashes E1: a fresh preview world == its own print (no 0xE1 tails).
    OceanWorld w3;
    ofp::initWorld(w3, 1102, 1920, 1080, 240.0f, 100, nullptr, err);
    for (int s = 0; s < 30; ++s) w3.update(0.016f);
    t.expect(!w3.waveClockStarted() && !w3.flowE1() && oceanE1AtDefaults(w3.ocfg), "a preview world has E1 state");
}

// Lazy wave preparation (OceanWorld::prepareWaves; harness format 3): the
// modes are set only once the waves are on, and preparing late is the same as
// preparing at init for everything but the geo hash of the steps before.
void testLazyWaves() {
    Test t("lazy_waves");
    namespace pk = ofp::peek;
    std::string err;
    auto unprepared = [](const OceanWorld& w) {
        for (const auto& tr : ofp::field<pk::OwWaves>(w))
            if (!(tr.frac == 0.0f && tr.kx == 0.0 && tr.ky == 0.0 && tr.phi == 0.0 && tr.phase == 0.0)) return false;
        return true;
    };
    auto sameModes = [](const OceanWorld& a, const OceanWorld& b) {   // bit for bit, phase aside
        for (int i = 0; i < OceanWorld::kWaveTrains; ++i) {
            const auto& x = ofp::field<pk::OwWaves>(a)[i];
            const auto& y = ofp::field<pk::OwWaves>(b)[i];
            if (ofp::bits64(x.kx) != ofp::bits64(y.kx) || ofp::bits64(x.ky) != ofp::bits64(y.ky) ||
                ofp::bits64(x.phi) != ofp::bits64(y.phi) || ofp::bits(x.k) != ofp::bits(y.k) ||
                ofp::bits(x.qx) != ofp::bits(y.qx) || ofp::bits(x.qy) != ofp::bits(y.qy) ||
                ofp::bits(x.frac) != ofp::bits(y.frac) || x.frac == 0.0f)
                return false;
        }
        return true;
    };
    auto allButGeo = [](const ofp::Fingerprint& a, const ofp::Fingerprint& b) {
        for (auto s : ofp::kSections)
            if (s != &ofp::Fingerprint::geo && a.*s != b.*s) return false;
        return true;
    };
    // Waves off (the preview; a deep current alone, flowE1 on): never prepared,
    // whatever the step or the flow readers evaluate.
    for (const char* cfg : {(const char*)nullptr, R"({"deepCurrent":true,"currentStrength":30,"foodDrift":true})"}) {
        OceanWorld w;
        ofp::initWorld(w, 1701, 1920, 1080, 240.0f, 100, cfg, err);
        t.expect(unprepared(w), "%s: waves prepared at init with the waves off", cfg ? cfg : "preview");
        const std::uint64_t geo0 = ofp::fingerprint(w).geo;
        for (int s = 0; s < 40; ++s) w.update(0.016f);
        (void)w.flowAt({100.0f, 200.0f}, 50.0f);
        (void)w.flowExactAt({100.0f, 200.0f}, 50.0f);
        for (int i = 0; i < OceanWorld::kWaveTrains; ++i) {
            const OceanWorld::Flow u = w.waveTrainAt(i, {300.0f, 400.0f}, 60.0f);
            t.expect(u.x == 0.0f && u.y == 0.0f && u.d == 0.0f, "an unprepared train gives flow");
        }
        t.expect(unprepared(w) && ofp::fingerprint(w).geo == geo0, "%s: waves prepared without being on",
                 cfg ? cfg : "preview");
    }
    // Eager (waves on at init) vs lazy (off at init, switched on directly
    // before the first step, as the driver's --set waveSpeed=6@0): the same
    // state before the step but for geo, and every section equal after it.
    const char* on = R"({"waveSpeed":6,"deepCurrent":true,"currentStrength":30,"foodDrift":true,"predatorCount":2})";
    const char* off = R"({"waveSpeed":0,"deepCurrent":true,"currentStrength":30,"foodDrift":true,"predatorCount":2})";
    OceanWorld a;
    ofp::initWorld(a, 1702, 1920, 1080, 240.0f, 150, on, err);
    t.expect(!unprepared(a), "waves on at init: not prepared");
    const ofp::Fingerprint a0 = ofp::fingerprint(a);
    for (int s = 0; s < 200; ++s) a.update(0.016f);
    const ofp::Fingerprint a1 = ofp::fingerprint(a);
    OceanWorld b;
    ofp::initWorld(b, 1702, 1920, 1080, 240.0f, 150, off, err);
    b.ocfg.waveSpeed = 6.0f;
    t.expect(unprepared(b), "switched on directly: prepared before anything read the flow");
    const ofp::Fingerprint b0 = ofp::fingerprint(b);   // hashCurrent reads flowAt (cur) before geo is hashed
    t.expect(allButGeo(a0, b0), "lazy vs eager at init: a section other than geo differs");
    t.expect(sameModes(a, b), "the first flow read did not prepare the modes the eager world has");
    t.expect(a0.geo == b0.geo, "lazy vs eager: geo differs once prepared (the fingerprint read the flow)");
    for (int s = 0; s < 200; ++s) b.update(0.016f);
    t.expect(ofp::fingerprint(b) == a1, "lazy vs eager after 200 steps: the states differ");
    // Switched on live at step 100 (the step prepares them; no reader first),
    // then off: prepared once, the modes and the stopped clock kept.
    OceanWorld c;
    ofp::initWorld(c, 1703, 1920, 1080, 240.0f, 100, off, err);
    for (int s = 0; s < 100; ++s) c.update(0.016f);
    t.expect(unprepared(c), "off for 100 steps: prepared");
    c.ocfg.waveSpeed = 6.0f;
    c.update(0.016f);
    t.expect(sameModes(a, c) && c.waveClockStarted(), "switched on live: the step did not prepare and run them");
    for (int s = 0; s < 49; ++s) c.update(0.016f);
    double ph[OceanWorld::kWaveTrains];
    for (int i = 0; i < OceanWorld::kWaveTrains; ++i) ph[i] = c.wavePhase(i);
    c.ocfg.waveSpeed = 0.0f;
    for (int s = 0; s < 50; ++s) c.update(0.016f);
    bool kept = sameModes(a, c);
    for (int i = 0; i < OceanWorld::kWaveTrains; ++i) kept &= c.wavePhase(i) == ph[i];
    t.expect(kept, "switched off: the modes or the stopped clock were not kept");
    // A reused world re-initialised with the waves off is unprepared again
    // (its geo == a fresh world's).
    OceanWorld fresh;
    ofp::initWorld(fresh, 1704, 1920, 1080, 240.0f, 80, nullptr, err);
    const std::uint64_t freshGeo = ofp::fingerprint(fresh).geo;
    ofp::initWorld(a, 1704, 1920, 1080, 240.0f, 80, nullptr, err);
    t.expect(unprepared(a) && ofp::fingerprint(a).geo == freshGeo, "a reused world kept its prepared waves");
    // Every public flow reader prepares the modes when it is the first reader
    // after the waves came on directly — the tapered overload
    // waveTrainExactAt(i, p, d, taperAt(d)) too (it read the unprepared modes
    // and gave zero flow). Its trains == an eagerly prepared world's, bit for
    // bit; with the waves still off it prepares nothing and gives zero.
    {
        OceanWorld eager, lazy;
        ofp::initWorld(eager, 1705, 1920, 1080, 240.0f, 0, on, err);
        ofp::initWorld(lazy, 1705, 1920, 1080, 240.0f, 0, off, err);
        const Vec2 p{300.0f, 400.0f};
        const float d = 60.0f;
        const OceanWorld::Flow z = lazy.waveTrainExactAt(0, p, d, lazy.taperAt(d));
        t.expect(unprepared(lazy) && z.x == 0.0f && z.y == 0.0f && z.d == 0.0f,
                 "the tapered reader with the waves off: prepared them, or gave flow");
        lazy.ocfg.waveSpeed = 6.0f;
        bool same = true, moving = false;
        for (int i = 0; i < OceanWorld::kWaveTrains; ++i) {
            const OceanWorld::Flow u = lazy.waveTrainExactAt(i, p, d, lazy.taperAt(d));   // the first reader (i = 0)
            const OceanWorld::Flow e = eager.waveTrainExactAt(i, p, d);
            same &= ofp::bits(u.x) == ofp::bits(e.x) && ofp::bits(u.y) == ofp::bits(e.y) && ofp::bits(u.d) == ofp::bits(e.d);
            moving |= u.x != 0.0f || u.y != 0.0f || u.d != 0.0f;
        }
        t.expect(sameModes(eager, lazy) && same && moving,
                 "the tapered reader first after the waves came on: unprepared modes or zero flow (%d %d %d)",
                 (int)sameModes(eager, lazy), (int)same, (int)moving);
    }
}

// The loops OceanWorld::wrapCoord replaced (capped: n counts the passes).
float wrapLoops(float v, float span, long& n) {
    n = 0;
    while (v < 0.0f && n < 100000000) { v += span; ++n; }
    while (v >= span && n < 100000000) { v -= span; ++n; }
    return v;
}

void testWrap() {
    Test t("wrap");
    long compared = 0, multi = 0;
    auto check = [&](float v, float span) {
        long n = 0;
        const float want = wrapLoops(v, span, n);
        const float got = OceanWorld::wrapCoord(v, span);
        ++compared;
        multi += (n > 1);
        t.expect(std::memcmp(&got, &want, sizeof got) == 0, "wrapCoord(%a, %g) = %a, the loops gave %a (%ld passes)", (double)v,
                 (double)span, (double)got, (double)want, n);
    };
    std::uint32_t s = 12345u;
    auto u01 = [&] { s = s * 1664525u + 1013904223u; return (float)(s >> 8) * (1.0f / 16777216.0f); };
    for (float span : {100.0f, 333.25f, 1080.0f, 1440.0f, 1920.0f, 2560.0f, 20000.0f, 100000.0f}) {
        // The edges of the one-pass range [-span, 2·span) and of [0, span), each ± 1 ulp.
        for (float x : {-span, 0.0f, -0.0f, span, 2.0f * span})
            for (float v : {x, std::nextafter(x, -INFINITY), std::nextafter(x, INFINITY)}) check(v, span);
        // Tiny negatives (the add rounds up to span: the loops end at 0).
        for (float v : {-1e-30f, -std::numeric_limits<float>::denorm_min(), -1e-8f, -1e-6f, -0.5f * span}) check(v, span);
        // A sweep of the one-pass range, any span ...
        for (int k = 0; k < 20000; ++k) check(-span + 3.0f * span * u01(), span);
        // ... and, for a whole-number span, |v| < 2^23 (many passes, each exact).
        if (span == std::floor(span))
            for (int k = 0; k < 300; ++k) check((u01() - 0.5f) * 16777216.0f, span);
    }
    // Far out (the loops never ended there): in [0, span), the exact remainder.
    for (float v : {7.9e17f, 1e18f, 1.5e19f, -7.9e17f, -1e18f}) {
        const std::uint64_t m = (std::uint64_t)std::abs(v) % 1920u;   // v is a whole number here
        const float want = (v >= 0.0f) ? (float)m : (m ? 1920.0f - (float)m : 0.0f);
        const float got = OceanWorld::wrapCoord(v, 1920.0f);
        t.expect(got == want && !std::signbit(got), "wrapCoord(%.9g, 1920) = %.9g, want %.9g", (double)v, (double)got, (double)want);
    }
    // Beyond uint64: the exact remainder from the float's bits, |v| = M·2^k
    // (M < 2^24 whole), r = (M mod s)·(2^k mod s) mod s — no fmod involved —
    // and the values worked out by hand (Python's exact integers): 1e20f,
    // -1e20f, 3.4e38f, -3.4e38f mod 1080 = 632, 448, 224, 856.
    auto exactWrap = [](float v, std::uint64_t s) {
        int e = 0;
        const float m = std::frexp(std::abs(v), &e);   // |v| = m·2^e, m in [0.5, 1)
        const std::uint64_t M = (std::uint64_t)std::ldexp(m, 24);
        std::uint64_t p = 1 % s;
        for (int k = 0; k < e - 24; ++k) p = (p * 2) % s;
        const std::uint64_t r = ((M % s) * p) % s;
        return (float)((v >= 0.0f || r == 0) ? r : s - r);
    };
    const struct { float v, span, want; } far[] = {
        {1e20f, 1080.0f, 632.0f}, {-1e20f, 1080.0f, 448.0f}, {3.4e38f, 1080.0f, 224.0f}, {-3.4e38f, 1080.0f, 856.0f},
        {1e20f, 1920.0f, 512.0f}, {-1e20f, 1920.0f, 1408.0f}, {3.4e38f, 1920.0f, 1664.0f}, {-3.4e38f, 1920.0f, 256.0f},
        {7.9e17f, 1080.0f, 88.0f}, {-7.9e17f, 1080.0f, 992.0f},
    };
    for (const auto& f : far) {
        const float got = OceanWorld::wrapCoord(f.v, f.span), bitsWant = exactWrap(f.v, (std::uint64_t)f.span);
        t.expect(got == f.want && bitsWant == f.want && !std::signbit(got), "wrapCoord(%.9g, %g) = %.9g, want %.9g (from the bits: %.9g)",
                 (double)f.v, (double)f.span, (double)got, (double)f.want, (double)bitsWant);
    }
    for (int k = 0; k < 2000; ++k) {   // random far floats, both signs, spans 1080 / 1920 / 100
        const float v = (u01() < 0.5f ? -1.0f : 1.0f) * std::ldexp(1.0f + u01(), 25 + (int)(u01() * 100.0f));
        for (float span : {100.0f, 1080.0f, 1920.0f}) {
            const float got = OceanWorld::wrapCoord(v, span), want = exactWrap(v, (std::uint64_t)span);
            t.expect(std::memcmp(&got, &want, sizeof got) == 0, "wrapCoord(%a, %g) = %.9g, the exact remainder is %.9g", (double)v,
                     (double)span, (double)got, (double)want);
        }
    }
    // wrapPreview (food / predators with the 3-D flow off): the old single
    // pass, bit for bit, on [-span, 2·span); wrapCoord further out.
    long previewSame = 0;
    for (float span : {100.0f, 333.25f, 1080.0f, 1920.0f}) {
        auto onePass = [span](float v) { if (v < 0) v += span; else if (v >= span) v -= span; return v; };
        std::vector<float> vs;
        for (float x : {-span, 0.0f, -0.0f, span, 2.0f * span})
            for (float v : {x, std::nextafter(x, -INFINITY), std::nextafter(x, INFINITY)}) vs.push_back(v);
        for (float v : {-1e-30f, -1e-8f, -0.5f * span}) vs.push_back(v);
        for (int k = 0; k < 20000; ++k) vs.push_back(-span + 3.0f * span * u01());
        for (float v : vs) {
            const bool in = v >= -span && v < 2.0f * span;
            const float got = OceanWorld::wrapPreview(v, span), want = in ? onePass(v) : OceanWorld::wrapCoord(v, span);
            previewSame += t.expect(std::memcmp(&got, &want, sizeof got) == 0, "wrapPreview(%a, %g) = %a, want %a", (double)v,
                                    (double)span, (double)got, (double)want);
        }
        for (float v : {-2.0f * span, -1.5f * span, 2.5f * span, 7.25f * span, 1e20f, -1e20f}) {
            const float got = OceanWorld::wrapPreview(v, span);
            previewSame += t.expect(got == OceanWorld::wrapCoord(v, span) && got >= 0.0f && got < span,
                                    "wrapPreview(%.9g, %g) = %.9g: not wrapCoord's", (double)v, (double)span, (double)got);
        }
    }
    // The 3-D flow off, a flow of more than a span per step (the council's
    // trigger: 100 eddies at strength 1000 in a 100 x 100 world; one pass left
    // food at x ~ -154.55): every position stays in the world, and the run's
    // fingerprint is printed so the harness compares it native vs wasm.
    for (const char* c : {R"({"currentStrength":1000,"currentEddies":100,"currentCore":50,"currentDrift":0,"foodDrift":true,"targetFood":1})",
                          R"({"currentStrength":1000,"currentEddies":100,"currentCore":50,"currentMode":0,"foodDrift":true,"targetFood":50,"predatorCount":3,"predatorEconomy":true})"}) {
        OceanWorld w;
        std::string err;
        if (!t.expect(ofp::initWorld(w, 11, 100, 100, 240.0f, 0, c, err), "%s: %s", c, err.c_str())) continue;
        bool inside = true;
        float maxStep = 0.0f;   // the largest flow displacement in one step, at a food / fish / predator
        for (int s = 0; s < 200; ++s) {
            w.update(0.016f);
            for (const OceanFood& f : w.food) {
                inside &= f.pos.x >= 0.0f && f.pos.x <= 100.0f && f.pos.y >= 0.0f && f.pos.y <= 100.0f;
                const Vec2 u = w.currentAt(f.pos);
                maxStep = std::max(maxStep, std::max(std::abs(u.x), std::abs(u.y)) * 0.016f);
            }
            for (const Fish& f : w.creatures) inside &= f.pos.x >= 0.0f && f.pos.x < 100.0f && f.pos.y >= 0.0f && f.pos.y < 100.0f;
            for (const OceanPredator& p : w.predators) inside &= p.pos.x >= 0.0f && p.pos.x <= 100.0f && p.pos.y >= 0.0f && p.pos.y <= 100.0f;
        }
        t.expect(inside && ofp::countNonFinite(w) == 0, "%s: a position left the 100 x 100 world or went non-finite", c);
        t.expect(maxStep > 100.0f, "%s: the flow never moved anything more than a span in a step (max %.3g)", c, (double)maxStep);
        t.note("flow off, > 1 span / step (max %.0f): 200 steps in the world, fingerprint %016llx", (double)maxStep,
               (unsigned long long)ofp::fingerprint(w).all);
    }
    for (float v : {INFINITY, -INFINITY, NAN}) t.expect(std::isnan(OceanWorld::wrapCoord(v, 1920.0f)), "wrapCoord(%g) not NaN", (double)v);
    // The config that hung (validation bypassed): it now steps, and the flow
    // keeps every position in the world.
    {
        OceanWorld w;
        SimConfig sc;
        applyOceanDefaults(sc);
        sc.currentMode = 1;
        sc.currentStrength = 1e20f;
        sc.foodDrift = true;
        sc.targetFood = 1;
        OceanConfig oc;
        oc.deepCurrent = true;
        rng.seed(1401);
        w.cfg = sc;
        w.ocfg = oc;
        w.init(1920, 1080, 240.0f, 0);
        for (int k = 0; k < 20; ++k) w.update(0.016f);
        bool inside = !w.creatures.empty();
        for (const Fish& f : w.creatures) inside &= f.pos.x >= 0.0f && f.pos.x < 1920.0f && f.pos.y >= 0.0f && f.pos.y < 1080.0f;
        for (const OceanFood& f : w.food) inside &= f.pos.x >= 0.0f && f.pos.x < 1920.0f && f.pos.y >= 0.0f && f.pos.y < 1080.0f;
        t.expect(inside, "currentStrength 1e20 (unvalidated): a position left the world (%zu fish, %zu food)", w.creatures.size(),
                 w.food.size());
    }
    t.note("%ld values == the loops bit for bit (%ld of them more than one pass); far values == the exact remainder;"
           " wrapPreview == the old single pass / wrapCoord at %ld values", compared, multi, previewSame);
}

#ifndef OCEAN_TESTS_NO_SHIM
void testPreset() {
    Test t("preset");
    SimConfig sc;
    applyOceanDefaults(sc);
    OceanConfig oc;
    std::string err;
    t.expect(readOceanJson(kE1PresetJson, sc, oc, err), "kE1PresetJson: %s", err.c_str());
    t.expect(oc.waveSpeed > 0.0f && oc.deepCurrent && oc.lightEnabled && oc.depthCostScaled && sc.currentStrength > 0.0f &&
             sc.foodDrift, "the preset does not turn on waves, deep currents, light and scaled costs");
    t.expect(std::strcmp(oc_e1_preset(), kE1PresetJson) == 0, "oc_e1_preset() is not kE1PresetJson");
    const int initRc = oc_init(1201, 1920, 1080, 240.0, 300, kE1PresetJson);
    t.expect(initRc == 1, "oc_init refused the preset: %s", oc_last_error());
    oc_step(500);
    t.expect(ofp::countNonFinite(*g_world) == 0 && g_world->flowE1() && g_world->waveClockStarted(), "preset world");
    t.note("kE1PresetJson = %s", kE1PresetJson);
}
#endif

// ---- the ocean-vision keys meet the hardened validation, and E1 meets the eye ----
#ifndef OCEAN_TESTS_NO_SHIM
// eye, eyeOnly, eyeCode, steerFrame (int keys) and foodLife through the real
// oc_init / oc_set_param: an int key's JSON number must be a whole number in
// int's range (refused before any cast, at every occurrence of the key), then
// lie in its range (eye / eyeOnly 0..1 and eyeCode 0..31 in the eye build, 0 in
// the plain one; steerFrame 0..1); foodLife in [0, 3600]; a refused call keeps
// the world as it was.
void testVisionKeys() {
    Test t("vision_keys");
    int refused = 0, accepted = 0;
    auto tryInit = [&](const std::string& c) { return oc_init(1201, 1920, 1080, 240.0, 50, c.c_str()); };
    for (const char* k : {"eye", "eyeOnly", "eyeCode", "steerFrame", "labelFrame"}) {
        for (const char* v : {"0.5", "1e300", "-1e300", "2147483648", "-2147483649", "1e999", "-0.25", "1.0000001"}) {
            const std::string c = std::string("{\"") + k + "\":" + v + "}";
            const int ok = tryInit(c);
            const std::string e = oc_last_error();
            refused += t.expect(ok == 0 && e.find(k) != std::string::npos && e.find("whole number") != std::string::npos,
                                "%s: accepted, or not refused as a whole-number error (%s)", c.c_str(), e.c_str());
        }
        // a repeated key: every occurrence is checked
        for (const char* v : {"0.5", "1e300"}) {
            const std::string c = std::string("{\"") + k + "\":0,\"" + k + "\":" + v + "}";
            refused += t.expect(tryInit(c) == 0, "%s accepted", c.c_str());
        }
        // whole numbers outside the key's range: refused by the range check
        for (const char* v : {"-1", "32", "2147483647", "-2147483648"}) {   // 32: past every key's range (eyeCode 0..31)
            const std::string c = std::string("{\"") + k + "\":" + v + "}";
            const int ok = tryInit(c);
            refused += t.expect(ok == 0 && std::string(oc_last_error()).find(k) != std::string::npos,
                                "%s accepted (or the error names another key: %s)", c.c_str(), oc_last_error());
        }
        // 0 (also written 0.0 / -0) is every key's default and always accepted
        for (const char* v : {"0", "0.0", "-0"}) {
            const std::string c = std::string("{\"") + k + "\":" + v + "}";
            const int ok = tryInit(c);
            accepted += t.expect(ok == 1, "%s refused: %s", c.c_str(), oc_last_error());
        }
    }
    // The ranges, per build.
    struct R { const char* cfg; bool eyeBuild, plain; };
    const R rs[] = {
        {R"({"steerFrame":1})", true, true},      {R"({"steerFrame":1.0})", true, true},
        {R"({"steerFrame":2})", false, false},
        {R"({"labelFrame":1})", true, true},      {R"({"labelFrame":2})", false, false},
        {R"({"eye":1})", true, false},            {R"({"eye":2})", false, false},
        {R"({"eyeOnly":1})", true, false},        {R"({"eyeOnly":2})", false, false},
        {R"({"eye":1,"eyeOnly":1,"eyeCode":7})", true, false},
        {R"({"eyeCode":1})", true, false},        {R"({"eyeCode":7})", true, false},
        {R"({"eyeCode":8})", true, false},        {R"({"eye":1,"eyeOnly":1,"eyeCode":16})", true, false},
        {R"({"eyeCode":31})", true, false},       {R"({"eyeCode":32})", false, false},
        {R"({"foodLife":0})", true, true},        {R"({"foodLife":12.5})", true, true},
        {R"({"foodLife":3600})", true, true},     {R"({"foodLife":3600.5})", false, false},
        {R"({"foodLife":1e6})", false, false},    {R"({"foodLife":1000001})", false, false},
        {R"({"foodLife":-0.001})", false, false}, {R"({"foodLife":1e39})", false, false},
        {R"({"foodLife":-1e39})", false, false},
    };
    for (const R& r : rs) {
        const bool want = kOceanHasEye ? r.eyeBuild : r.plain;
        const int ok = tryInit(r.cfg);
        if (want) accepted += t.expect(ok == 1, "%s refused: %s", r.cfg, oc_last_error());
        else      refused += t.expect(ok == 0, "%s accepted", r.cfg);
    }
    {
        const int ok = tryInit(R"({"eyeCode":1})");
        t.note("oc_init {\"eyeCode\":1}: %s", ok ? "accepted (eye build)" : oc_last_error());
    }
    // Live (oc_set_param): refused as stored, the world unchanged.
    if (t.expect(oc_init(1202, 1920, 1080, 240.0, 80, R"({"predatorCount":2})") == 1, "oc_init: %s", oc_last_error())) {
        oc_step(10);
        const ofp::Fingerprint before = ofp::fingerprint(*g_world);
        struct L { const char* key; double v; };
        const L bad[] = {{"steerFrame", 0.5}, {"steerFrame", 2.0}, {"steerFrame", 2147483648.0}, {"eyeOnly", 1.5},
                         {"eyeCode", 32.0}, {"eyeCode", 1e300}, {"eye", 0.25}, {"eye", 2.0}, {"foodLife", 1e7}, {"foodLife", 3601.0},
                         {"foodLife", std::numeric_limits<double>::infinity()}, {"foodLife", -1.0},
                         {"eyeCode", std::numeric_limits<double>::quiet_NaN()}};
        for (const L& l : bad) {
            const int ok = oc_set_param(l.key, l.v);
            refused += t.expect(ok == 0, "oc_set_param(%s, %g) accepted", l.key, l.v);
        }
        t.expect(ofp::fingerprint(*g_world) == before, "a refused oc_set_param changed the world");
        const int sf = oc_set_param("steerFrame", 1.0), fl = oc_set_param("foodLife", 8.0);
        t.expect(sf == 1 && fl == 1 && g_world->ocfg.steerFrame == 1 && g_world->ocfg.foodLife == 8.0f,
                 "oc_set_param steerFrame 1 / foodLife 8 not stored: %s", oc_last_error());
        const int lf = oc_set_param("labelFrame", 1.0), lfBad = oc_set_param("labelFrame", 2.0);
        t.expect(lf == 1 && lfBad == 0 && g_world->ocfg.labelFrame == 1, "oc_set_param labelFrame 1 / 2: %d / %d", lf, lfBad);
        const int eye = oc_set_param("eye", 1.0);
        t.expect(eye == (kOceanHasEye ? 1 : 0), "oc_set_param(eye, 1) returned %d in the %s build", eye,
                 kOceanHasEye ? "eye" : "plain");
        oc_step(200);
        t.expect(ofp::countNonFinite(*g_world) == 0, "non-finite state after the live changes");
    }
    t.note("%d configs / changes refused, %d accepted", refused, accepted);
}
#endif

// E1 with the eye build's features. (1) Under the E1 flow with foodDrift, food
// moves in depth, and every live item's eyeCon is eyeContrast(food glow, its
// depth) after every step (set again when the depth moved); with the flow off
// it never moves in depth and keeps its spawn value. (2) mouthGate gates
// eating and smell, not sight: food too big to swallow is still seen. (3) The
// eye has no side effects under E1 either: an unwired world with the E1 preset
// runs identically with the eye on and off. (4) E1 + eye-only + steerFrame +
// foodLife + waves: every input finite, the labeled inputs 0, food expires.
// Plain build: (4) without the eye.
void testEyeE1() {
    Test t("eye_e1");
#ifdef EVO_OCEAN_EYE
    for (int e1 = 0; e1 < 2; ++e1) {
        // No fish (nothing is eaten) and no foodLife: food is only ever appended,
        // so the first n items before a step are the first n after it.
        OceanWorld w;
        std::string err;
        const char* cfg = e1 ? R"({"waveSpeed":8,"deepCurrent":true,"currentStrength":40,"foodDrift":true,"eye":1,"predatorCount":2,"minPopulation":0})"
                             : R"({"currentStrength":40,"foodDrift":true,"eye":1,"predatorCount":2,"minPopulation":0})";
        if (!t.expect(ofp::initWorld(w, 1301 + e1, 1920, 1080, 240.0f, 0, cfg, err), "init: %s", err.c_str())) continue;
        long moved = 0, items = 0, wrong = 0;
        std::vector<float> z0;
        for (int s = 0; s < 300; ++s) {
            z0.clear();
            for (const OceanFood& f : w.food) z0.push_back(f.depth);
            w.update(0.016f);
            for (const OceanFood& f : w.food) {
                ++items;
                wrong += !(f.eyeCon == ocean::eyeContrast(ocean::kEyeFoodBright, f.depth));
            }
            for (std::size_t i = 0; i < z0.size() && i < w.food.size(); ++i) moved += (w.food[i].depth != z0[i]);
        }
        t.expect(wrong == 0, "%s: %ld of %ld food items' eyeCon != eyeContrast(glow, depth)", e1 ? "E1" : "flow off",
                 wrong, items);
        if (e1) t.expect(moved > 10000, "E1: food hardly moved in depth (%ld item-steps)", moved);
        else    t.expect(moved == 0, "flow off: food moved in depth (%ld item-steps)", moved);
        t.note("%s: %ld food-steps (%ld moved in depth), eyeCon == eyeContrast(glow, depth) for every one",
               e1 ? "E1 drift" : "flow off", items, moved);
    }
    {   // (2) a viewer too small to swallow food (size 1 > kMouth 1 x bodySize 0.5): it sees it, cannot smell it
        OceanConfig oc;
        oc.eye = 1;
        oc.mouthGate = true;
        oc.kMouth = 1.0f;
        OceanWorld w;
        initQuiet(w, 1303, 240.0f, oc, /*capture*/ true);
        w.cfg.bodyModel = true;
        const int v = addFish(w, {600.0f, 500.0f}, 120.0f, {}, 0.5f);
        w.creatures[v].vel = {1.0f, 0.0f};
        w.creatures[v].bodySize = 0.5f;
        OceanFood f;
        f.pos = {640.0f, 500.0f};
        f.depth = 120.0f;
        f.eyeCon = ocean::eyeContrast(ocean::kEyeFoodBright, f.depth);
        w.food.push_back(f);
        w.update(0.016f);
        const float* S = w.creatures[v].lastSensors;
        t.expect(S[EYE_AHEAD_PROX] > 0.5f && S[NEAREST_FOOD_DIST] == 1.0f && S[FOOD_DENSITY] == 0.0f,
                 "mouth-gated food: eye ahead %.4f, smell dist %.4f density %.4f (expected seen, not smelled)",
                 S[EYE_AHEAD_PROX], S[NEAREST_FOOD_DIST], S[FOOD_DENSITY]);
    }
    {   // (3) no side effects under E1, eye on vs off. The world is built from ONE
        // parsed config (it used to be parsed and dropped: initQuiet built its own,
        // economy off, metabolism 0): the E1 preset, its SimConfig half too
        // (currentStrength 5, foodDrift), a predator economy (3 predators) and the
        // default metabolism, which the preset's scaled depth costs multiply; no
        // founders, food spawn or floor (unwired fish and food are added below).
        // What the case is for is asserted before anything is compared.
        ofp::Fingerprint fp[2];
        for (int k = 0; k < 2; ++k) {
            SimConfig sc;
            applyOceanDefaults(sc);
            OceanConfig oc;
            std::string err;
            std::string json = std::string(kE1PresetJson);
            json.back() = ',';
            json += R"("predatorCount":3,"predatorEconomy":true,"minPopulation":0,"targetFood":0,"foodSpawnBase":0,)"
                    R"("foodSpawnAmp":0,"maxAge":1e9,"eye":)";
            json += k ? "1}" : "0}";
            if (!t.expect(readOceanJson(json.c_str(), sc, oc, err), "%s: %s", json.c_str(), err.c_str())) break;
            clampOceanSimConfig(sc);
            sc.captureActivations = true;
            oc.depth = 240.0f;
            const std::string bad = oceanConfigError(oc) + oceanSimConfigError(sc);
            t.expect(bad.empty(), "the intended config is out of range: %s", bad.c_str());
            t.expect(sc.predatorEconomy && sc.predatorCount == 3 && sc.metabolicRate > 0.0f && oc.depthCostScaled &&
                         oc.cHold > 0.0f && oc.cPress > 0.0f && sc.currentStrength == 5.0f && sc.foodDrift && oc.eye == k,
                     "eye %d: not the intended world (economy %d, %d predators, metabolism %g, scaled costs %d)", k,
                     (int)sc.predatorEconomy, sc.predatorCount, (double)sc.metabolicRate, (int)oc.depthCostScaled);
            OceanWorld w;
            rng.seed(1304);
            w.cfg = sc;
            w.ocfg = oc;
            w.init(1920, 1080, 240.0f, 0);   // the 3 economy predators; no founders, no food
            for (int j = 0; j < 300; ++j) {
                // one draw per statement: the order of a call's arguments is
                // unspecified (g++ and clang differ), the order of statements is not
                const float x = rng.range(10.0f, 1910.0f);
                const float y = rng.range(10.0f, 1070.0f);
                const float z = rng.range(0.0f, 240.0f);
                addFish(w, {x, y}, z, {}, 0.5f);
            }
            for (int j = 0; j < 500; ++j) w.spawnFood();
            const float e0 = w.predators.empty() ? 0.0f : w.predators[0].energy;
            for (int s = 0; s < 300; ++s) w.update(0.016f);
            t.expect(w.flowE1(), "the E1 flow is off");
            // The economy and the metabolism really ran: a meal, a bud or a predator
            // death, and the fish spent energy.
            const long long econ = w.totalDeathsPredation + w.totalPredatorBirths + w.totalPredatorDeathsStarvation +
                                   w.totalPredatorDeathsAge;
            float spent = 0.0f;
            for (const Fish& c : w.creatures) spent = std::max(spent, 30.0f - c.foodReserves);
            t.expect(econ > 0 && spent > 0.0f && !w.predators.empty() && w.predators[0].energy != e0,
                     "eye %d: the economy / metabolism did not run (%lld events, most spent %g)", k, econ, (double)spent);
            if (k == 1)
                t.note("unwired E1 world + predator economy, 300 steps: %lld meals, %lld predator births, %lld starved, "
                       "%lld fish births, eye on == eye off", w.totalDeathsPredation, w.totalPredatorBirths,
                       w.totalDeathsStarvation, w.totalBirths);
            fp[k] = ofp::fingerprint(w, /*withActivations*/ false);
        }
        t.expect(fp[0].ctr == fp[1].ctr && fp[0].fish == fp[1].fish && fp[0].food == fp[1].food &&
                     fp[0].pred == fp[1].pred && fp[0].rng == fp[1].rng,
                 "the eye changed an unwired E1 world (fish %016llx vs %016llx)", (unsigned long long)fp[0].fish,
                 (unsigned long long)fp[1].fish);
    }
#endif
    {   // (4) everything at once
        OceanWorld w;
        std::string err;
        const char* cfg = kOceanHasEye
            ? R"({"waveSpeed":6,"deepCurrent":true,"currentStrength":20,"foodDrift":true,"eye":1,"eyeOnly":1,"steerFrame":1,"foodLife":6,"eyeCode":3,"predatorCount":3,"predatorEconomy":true})"
            : R"({"waveSpeed":6,"deepCurrent":true,"currentStrength":20,"foodDrift":true,"steerFrame":1,"foodLife":6,"predatorCount":3,"predatorEconomy":true})";
        if (t.expect(ofp::initWorld(w, 1305, 1920, 1080, 240.0f, 300, cfg, err), "init: %s", err.c_str())) {
            w.cfg.captureActivations = true;
            long labeled = 0, nonFinite = 0, eyeSeen = 0;
            for (int s = 0; s < 600; ++s) {
                w.update(0.016f);
                for (const Fish& c : w.creatures) {
                    if (c.age <= 0.0f) continue;
                    for (int k = 0; k < NUM_SENSES; ++k) {
                        nonFinite += !finite(c.lastSensors[k]);
#ifdef EVO_OCEAN_EYE
                        if (ocean::isLabeledSense(k)) labeled += (c.lastSensors[k] != 0.0f);
                        if (ocean::isEyeSense(k)) eyeSeen += (c.lastSensors[k] != 0.0f);
#endif
                    }
                }
            }
            t.expect(nonFinite == 0 && ofp::countNonFinite(w) == 0, "%ld non-finite inputs (or state)", nonFinite);
            t.expect(labeled == 0, "eye-only under E1: %ld labeled inputs not 0", labeled);
            t.expect(!kOceanHasEye || eyeSeen > 0, "the eye saw nothing under E1");
            t.expect(w.totalFoodExpired > 0, "no food expired with foodLife 6 in 600 steps");
            t.note("E1 waves + deep current, steerFrame 1, foodLife 6%s: 600 steps, %lld food expired, pop %zu",
                   kOceanHasEye ? ", eye-only, eyeCode 3" : "", w.totalFoodExpired, w.creatures.size());
        }
    }
}

// tools/ocean_eye_exp.cpp's behavioural probe (eye build), on fish whose
// steering is known exactly: the only wire is hidden neuron 0 (undriven:
// 0.5) -> STEER_X, so STEER_X = tanh(0.5 w) in every scene. base_abs is the
// mean over the 8 headings of |the lateral steer with nothing in view|, base_x
// its signed mean. World frame (steerFrame 0): the lateral part of a steady
// world-x push is STEER_X · right.x, which changes sign around the headings:
// base_x ~ 0 and base_abs = |STEER_X| · mean |right.x| (base_abs used to be
// |base_x|, ~0 here). Own frame (steerFrame 1): base_abs = base_x = STEER_X.
void testEyeExpProbe() {
    Test t("eye_exp_probe");
#ifdef EVO_OCEAN_EYE
    for (int frame = 0; frame < 2; ++frame) {
        OceanWorld w;
        std::string err;
        if (!t.expect(ofp::initWorld(w, 1801, 1920, 1080, 240.0f, 0,
                                     frame ? R"({"eye":1,"eyeOnly":1,"steerFrame":1})" : R"({"eye":1,"eyeOnly":1})", err),
                      "init: %s", err.c_str()))
            continue;
        RandomGen sceneRng;
        const OceanWorld tmpl = behavTemplate(w, 7, sceneRng);
        Probe pr{tmpl, sceneRng};
        Fish f;
        f.genome = {mkGene(false, 0, STEER_X, 6000)};
        const RandomGen keep = rng;
        f.init({960.0f, 540.0f}, 120.0f);
        rng = keep;
        buildNeuralNet(f.genome, f.nnet);
        float acts[NUM_ACTIONS];
        pr.act(f, {1.0f, 0.0f}, 0, 0, acts);
        const float sx = acts[STEER_X];
        double idx[kBehavIdx];
        behaveOne(pr, f, frame == 1, idx);
        Behav b;
        addBehav(b, idx);
        double want = 0.0, wantX = 0.0;
        for (int h = 0; h < 8; ++h) {   // behaveOne's headings and lateral component
            const float a = 6.2831853f * (float)h / 8 + 0.3f;
            const float rx = -evomath::sinf(a);
            const float lat = frame ? sx : sx * rx;
            want += std::abs(lat) / 8.0;
            wantX += lat / 8.0;
        }
        const char* fr = frame ? "own frame" : "world frame";
        t.expect(std::abs(sx - std::tanh(0.5 * 6000.0 / 8192.0)) < 1e-5, "%s: STEER_X %.6f, expected tanh(0.5 w)", fr, (double)sx);
        t.expect(std::abs(b.base_abs - want) < 1e-6 && std::abs(b.base_x - wantX) < 1e-6,
                 "%s: base_abs %.6f base_x %.6f, expected %.6f %.6f", fr, b.base_abs, b.base_x, want, wantX);
        if (frame == 0)
            t.expect(std::abs(b.base_x) < 1e-5 && b.base_abs > 0.6 * sx, "world frame: base_x %.6f (want ~0), base_abs %.6f (want > 0)",
                     b.base_x, b.base_abs);
        else
            t.expect(std::abs(b.base_abs - sx) < 1e-6 && std::abs(b.base_x - sx) < 1e-6, "own frame: base_abs %.6f base_x %.6f, want %.6f",
                     b.base_abs, b.base_x, (double)sx);
        t.note("%s, steady STEER_X %.4f: base_abs %.4f, base_x %.4f (|base_x|, the old base_abs: %.4f)", fr, (double)sx,
               b.base_abs, b.base_x, std::abs(idx[12]));
    }
#endif
}

// tools/ocean_eye_exp.cpp's wiring classifier (eye build) against the engine.
// For fish wired directly from eye inputs to STEER_X (steerFrame 1: + = a push
// to the right; direct wires, so STEER_X = tanh(the summed input · weight)),
// the gains it computes for food on the left / right (gL, gR: the path gains
// times the inputs that food produces in the run's encoding) must give the
// STEER_X the fish really makes in those scenes, for every encoding 0..7. The
// Codex audit's fixture (perceptionRadius 100, D 240; left PROX +1, left CON
// -1, right PROX -1, right CON +1) is bi_away under eyeCode 1 (faded
// contrast: both turns away from food) and bi_toward under eyeCode 0; the
// classifier used the code-0 inputs for every code, so it said bi_toward for
// both.
void testEyeExpWiring() {
    Test t("eye_exp_wiring");
#ifdef EVO_OCEAN_EYE
    struct W { int sensor, weight; };
    const std::vector<std::vector<W>> wirings = {
        {{EYE_LEFT_PROX, 8192}, {EYE_LEFT_CON, -8192}, {EYE_RIGHT_PROX, -8192}, {EYE_RIGHT_CON, 8192}},   // the audit's
        {{EYE_LEFT_PROX, 8192}, {EYE_LEFT_CON, -6144}, {EYE_RIGHT_PROX, -8192}, {EYE_RIGHT_CON, 6144}},
        {{EYE_RIGHT_PROX, 8192}},                                    // one slot (opponent pairs: both sides)
        {{EYE_LEFT_SIZE, -8192}, {EYE_RIGHT_SIZE, 8192}},
        {{EYE_LEFT_CON, 4096}, {EYE_RIGHT_PROX, 8192}, {EYE_RIGHT_SIZE, -4096}, {EYE_AHEAD_PROX, 8192}},
    };
    long compared = 0;
    int auditClass[2] = {-1, -1};   // eyeCode 0, 1
    for (int code = 0; code <= 7; ++code) {
        OceanWorld w;
        std::string err;
        const std::string cfg =
            R"({"eye":1,"eyeOnly":1,"steerFrame":1,"perceptionRadius":100,"eyeCode":)" + std::to_string(code) + "}";
        if (!t.expect(ofp::initWorld(w, 1802, 1920, 1080, 240.0f, 0, cfg.c_str(), err), "init: %s", err.c_str())) continue;
        double x[4][ocean::kEyeInputs], vf[3];
        foodSceneInputs(w, 7, x, vf);
        RandomGen sceneRng;
        const OceanWorld tmpl = behavTemplate(w, 7, sceneRng);
        Probe pr{tmpl, sceneRng};
        for (std::size_t k = 0; k < wirings.size(); ++k) {
            Fish f;
            for (const W& g : wirings[k]) f.genome.push_back(mkGene(true, g.sensor, STEER_X, g.weight));
            const RandomGen keep = rng;
            f.init({960.0f, 540.0f}, 120.0f);
            rng = keep;
            buildNeuralNet(f.genome, f.nnet);
            std::vector<EyePath> paths;
            const FishWiring fw = wiringOf(f.nnet, x, vf, paths);
            float aL[NUM_ACTIONS], aR[NUM_ACTIONS];
            pr.act(f, {1.0f, 0.0f}, 1, 2, aL);   // food on the left
            pr.act(f, {1.0f, 0.0f}, 1, 3, aR);   // on the right
            ++compared;
            t.expect(std::abs(std::tanh(fw.gL) - aL[STEER_X]) < 1e-5 && std::abs(std::tanh(fw.gR) - aR[STEER_X]) < 1e-5,
                     "eyeCode %d, wiring %zu: gains (%.5f, %.5f) but STEER_X (%.5f, %.5f) = tanh of (%.5f, %.5f)", code, k, fw.gL,
                     fw.gR, (double)aL[STEER_X], (double)aR[STEER_X], std::atanh((double)aL[STEER_X]),
                     std::atanh((double)aR[STEER_X]));
            if (k == 0 && code <= 1) {
                auditClass[code] = fw.hclass;
                t.note("the audit's fixture, eyeCode %d: %s, gains (%+.3f, %+.3f), STEER_X food left %+.3f / right %+.3f", code,
                       kHClass[fw.hclass], fw.gL, fw.gR, (double)aL[STEER_X], (double)aR[STEER_X]);
            }
        }
    }
    t.expect(auditClass[0] == 3 && auditClass[1] == 4, "the audit's fixture: %s under eyeCode 0 (want bi_toward), %s under 1 (want bi_away)",
             auditClass[0] >= 0 ? kHClass[auditClass[0]] : "?", auditClass[1] >= 0 ? kHClass[auditClass[1]] : "?");
    t.note("%ld wirings x encodings: the classifier's gains == the fish's STEER_X (tanh), food left and right", compared);
#endif
}

#ifndef OCEAN_TESTS_NO_SHIM
// tools/ocean_probe.cpp builds its world as oc_init does (probeInitWorld):
// the shared clamps (clampOceanSimConfig), then the checks. perceptionRadius
// 0 used to reach SpatialGrid::init unclamped (a division by zero, infinity
// cast to int) although the shim stores 1. For each config: the stored radius
// is the shim's, both neighbour grids' geometry is finite, and the probe's
// world == the shim's, section by section (the rng included).
void testProbe() {
    Test t("probe");
    struct C { const char* cfg; bool e1; float radius; };
    const C cs[] = {
        {R"({"perceptionRadius":0})", false, 1.0f},
        {R"({"perceptionRadius":0.25,"interactRadius":0,"pickupRadius":0})", false, 1.0f},
        {nullptr, false, 100.0f},                                   // applyOceanDefaults
        {R"({"perceptionRadius":0})", true, 1.0f},                  // --e1: the preset first
    };
    for (const C& c : cs) {
        OceanWorld pw;
        const std::string perr = probeInitWorld(pw, 1401, 1920, 1080, 240.0, 120, c.e1, c.cfg);
        const char* name = c.cfg ? c.cfg : "{}";
        if (!t.expect(perr.empty(), "the probe refused %s%s: %s", name, c.e1 ? " --e1" : "", perr.c_str())) continue;
        const ofp::Fingerprint pf = ofp::fingerprint(pw);   // before oc_init reseeds the shared rng
        // The shim's world: the preset merged under the cfg for --e1.
        std::string shimCfg = c.cfg ? c.cfg : "";
        if (c.e1) {
            shimCfg = kE1PresetJson;
            shimCfg.back() = ',';
            shimCfg += std::string(c.cfg).substr(1);
        }
        const int initOk = oc_init(1401, 1920, 1080, 240.0, 120, shimCfg.empty() ? nullptr : shimCfg.c_str());
        if (!t.expect(initOk == 1, "oc_init refused %s: %s", shimCfg.c_str(), oc_last_error())) continue;
        t.expect(pw.cfg.perceptionRadius == c.radius && g_world->cfg.perceptionRadius == c.radius,
                 "%s: perceptionRadius stored %.9g by the probe, %.9g by the shim (expected %.9g)", name,
                 (double)pw.cfg.perceptionRadius, (double)g_world->cfg.perceptionRadius, (double)c.radius);
        {   // both neighbour grids (the fish's SpatialGrid, the OceanFoodGrid)
            const SpatialGrid& g = ofp::field<ofp::peek::OwCreatureGrid>(pw);
            const OceanFoodGrid& fg = ofp::field<ofp::peek::OwFoodGrid>(pw);
            const float invs[2] = {ofp::field<ofp::peek::SgInvCell>(g), ofp::field<ofp::peek::FgInvCell>(fg)};
            const int colss[2] = {ofp::field<ofp::peek::SgCols>(g), ofp::field<ofp::peek::FgCols>(fg)};
            const int rowss[2] = {ofp::field<ofp::peek::SgRows>(g), ofp::field<ofp::peek::FgRows>(fg)};
            for (int k = 0; k < 2; ++k)
                t.expect(std::isfinite(invs[k]) && invs[k] > 0.0f && colss[k] > 0 && rowss[k] > 0,
                         "%s: probe grid 1/cell %.9g, %d x %d cells", name, (double)invs[k], colss[k], rowss[k]);
        }
        const ofp::Fingerprint sf = ofp::fingerprint(*g_world);
        t.expect(pf == sf, "%s%s: the probe's world != the shim's (cfg %d geo %d rng %d)", name, c.e1 ? " --e1" : "",
                 pf.cfg == sf.cfg, pf.geo == sf.geo, pf.rng == sf.rng);
    }
}

// ocean_tests --accepts SEED STEPS [ocean_parity_driver args]: would the page
// accept this harness case? oc_init with the case's world and cfg JSON, then
// oc_set_param for each --set in the order the driver applies them: by step
// (before step S + 1, after S steps), the argument order kept within a step;
// a change at S >= STEPS is never applied, so it is not asked either. (It used
// to ask them in argument order: --set minSpeed=200@10 --set maxSpeed=300@5,
// which the driver runs, was refused for minSpeed 200 > the default
// maxSpeed 150.) wasm/ocean_parity.sh asks this of every case, so "extreme
// but valid" means valid to the shim, not just to the driver. argv as main's
// (argv[1] = "--accepts"); 0 accepted, 1 refused, 2 bad arguments; msg says why.
int acceptsCase(int argc, char** argv, std::string& msg) {
    if (argc < 4) { msg = "usage: --accepts SEED STEPS [driver args]"; return 2; }
    const unsigned seed = (unsigned)std::strtoul(argv[2], nullptr, 10);
    const long steps = std::strtol(argv[3], nullptr, 10);
    int W = 1920, H = 1080, pop = 300;
    double depth = 240.0;
    const char* cfg = nullptr;
    struct Change { std::string name; double value; long step; };
    std::vector<Change> sets;
    for (int i = 4; i < argc; ++i) {
        auto is = [&](const char* k) { return std::strcmp(argv[i], k) == 0 && i + 1 < argc; };
        if (is("--w")) W = std::atoi(argv[++i]);
        else if (is("--h")) H = std::atoi(argv[++i]);
        else if (is("--depth")) depth = std::atof(argv[++i]);
        else if (is("--pop")) pop = std::atoi(argv[++i]);
        else if (is("--cfg")) cfg = argv[++i];
        else if (is("--set")) {   // NAME=VALUE@STEP, parsed as the driver's parseSet
            const char* s = argv[++i];
            const char* eq = std::strchr(s, '=');
            const char* at = std::strrchr(s, '@');
            if (!eq || !at || at < eq || eq == s) { msg = std::string("bad --set ") + s + " (NAME=VALUE@STEP)"; return 2; }
            const long step = std::strtol(at + 1, nullptr, 10);
            if (step < 0) { msg = std::string("bad --set ") + s + " (a negative step)"; return 2; }
            sets.push_back({std::string(s, eq - s), std::strtod(eq + 1, nullptr), step});
        }
        else if (is("--every") || is("--dump") || is("--dump-step") || is("--expect") || is("--logs")) ++i;
        else if (!std::strcmp(argv[i], "--capture") || !std::strcmp(argv[i], "--trace") || !std::strcmp(argv[i], "--sparse")) {}
        else { msg = std::string("unknown driver argument ") + argv[i]; return 2; }
    }
    std::stable_sort(sets.begin(), sets.end(), [](const Change& a, const Change& b) { return a.step < b.step; });
    if (!oc_init(seed, W, H, depth, pop, cfg)) { msg = std::string("refused by oc_init: ") + oc_last_error(); return 1; }
    for (const Change& s : sets) {
        if (s.step >= steps) continue;   // after the run's last step: the driver never applies it
        if (!oc_set_param(s.name.c_str(), s.value)) {
            char buf[120];
            std::snprintf(buf, sizeof buf, "refused by oc_set_param(%s, %g) at step %ld: ", s.name.c_str(), s.value, s.step);
            msg = buf + std::string(oc_last_error());
            return 1;
        }
    }
    msg = "accepted";
    return 0;
}
int acceptsMain(int argc, char** argv) {
    std::string msg;
    const int rc = acceptsCase(argc, argv, msg);
    std::printf("%s\n", msg.c_str());
    return rc;
}

// The preflight above asks a case's live changes in the driver's order. The
// audit's sequence over 20 steps, minSpeed 200 at step 10 after maxSpeed 300
// at step 5, is accepted in BOTH argument orders; swapped in time (minSpeed
// first) it is refused; changes in one step keep their argument order; a
// change at or after STEPS is not applied and so not asked; a malformed or
// negative-step --set is an argument error.
void testPreflight() {
    Test t("preflight");
    struct C { std::vector<std::string> args; int rc; const char* what; };
    const C cs[] = {
        {{"1", "20", "--set", "minSpeed=200@10", "--set", "maxSpeed=300@5"}, 0, "valid in time, minSpeed listed first"},
        {{"1", "20", "--set", "maxSpeed=300@5", "--set", "minSpeed=200@10"}, 0, "valid in time, maxSpeed listed first"},
        {{"1", "20", "--set", "minSpeed=200@5", "--set", "maxSpeed=300@10"}, 1, "minSpeed 200 at step 5 > maxSpeed 150"},
        {{"1", "20", "--set", "maxSpeed=300@5", "--set", "minSpeed=200@5"}, 0, "one step, argument order: maxSpeed first"},
        {{"1", "20", "--set", "minSpeed=200@5", "--set", "maxSpeed=300@5"}, 1, "one step, argument order: minSpeed first"},
        {{"1", "20", "--set", "maxSpeed=1e30@20"}, 0, "a change at step 20 of 20 is never applied"},
        {{"1", "20", "--set", "maxSpeed=1e30@19"}, 1, "a change at step 19 of 20 is applied (and refused)"},
        {{"1", "20", "--cfg", R"({"predatorCount":2})", "--set", "kBuoy=3@12", "--set", "pitchMax=0.2@3", "--set", "minSpeed=200@15",
          "--set", "maxSpeed=250@14"}, 0, "four changes, out of argument order"},
        {{"1", "20", "--set", "maxSpeed=300"}, 2, "no @STEP"},
        {{"1", "20", "--set", "maxSpeed=300@-1"}, 2, "a negative step"},
    };
    for (const C& c : cs) {
        std::vector<std::string> args = {"ocean_tests", "--accepts"};
        args.insert(args.end(), c.args.begin(), c.args.end());
        std::vector<char*> av;
        for (std::string& a : args) av.push_back(a.data());
        std::string msg;
        const int rc = acceptsCase((int)av.size(), av.data(), msg);
        t.expect(rc == c.rc, "%s: rc %d, expected %d (%s)", c.what, rc, c.rc, msg.c_str());
    }
}
#endif

}  // namespace ot

// The E1 cache's private state, for flow_lanes (an explicit instantiation
// waives access checking, as ofp::peek does).
namespace ofp::peek {
struct OwFlowT { friend constexpr auto member(OwFlowT) noexcept; };
template struct Expose<OwFlowT, &OceanWorld::flow_>;
}  // namespace ofp::peek

namespace ot {
// The wave tables' vector evaluator (OceanWorld::wavesTable: the three trains
// in the lanes of a GCC 4-float vector — SSE2 natively, SIMD128 under wasm)
// against an independent SCALAR evaluation of the same cells: the same cache
// (FlowCache: depth pieces, rotated y factors, T) read lane by lane, scalar
// oceanflow::basis / hval / hder in the documented operation order, and the
// same fallbacks (no pieces, d not finite, x / y beyond one span: the exact
// formulas). Every train's (u_x, u_y, u_d) and flowAt's sum (the current, then
// the trains in order) must match BIT FOR BIT — at random points, at every
// depth join (b, D/2, D − b) and its neighbouring floats, at cell boundaries,
// at the surface / floor and beyond, at x / y = 0, the span, just inside,
// one add / subtract out and far out, with the phases at 0, set, and from the
// clock, in five worlds (one over the depth-cell cap: the fallback). Runs in
// both builds, so the harness's native == wasm comparison of this output
// covers SIMD128 too.
void testFlowLanes() {
    Test t("flow_lanes");
    using Fl = OceanWorld::Flow;
    using namespace oceanflow;
    struct WV { const char* name; int W, H; float D; const char* cfg; };
    const WV wv[] = {
        {"preset", 1920, 1080, 240.0f, kE1PresetJson},
        {"band 1.01", 1920, 1080, 240.0f, R"({"waveSpeed":6,"waveBand":1.01,"deepCurrent":true,"currentStrength":20})"},
        {"D 10.37 band 1.7", 1920, 1080, 10.37f, R"({"waveSpeed":50,"waveBand":1.7,"waveGravity":5000})"},
        {"2560x1440 D 777.7", 2560, 1440, 777.7f, R"({"waveSpeed":9,"waveBand":13.3,"deepCurrent":true,"currentStrength":60,"currentMode":1})"},
        {"100x100 D 2000 (over the cell cap)", 100, 100, 2000.0f, R"({"waveSpeed":20})"},
    };
    long compared = 0, mismatched = 0, fallbacks = 0, tabled = 0;
    std::string firstBad;
    auto same = [](float a, float b) { std::uint32_t x, y; std::memcpy(&x, &a, 4); std::memcpy(&y, &b, 4); return x == y; };
    for (const WV& v : wv) {
        OceanWorld w;
        std::string err;
        if (!t.expect(ofp::initWorld(w, 1601, v.W, v.H, v.D, 0, v.cfg, err), "%s: %s", v.name, err.c_str())) continue;
        auto& waves = ofp::field<ofp::peek::OwWaves>(w);
        const float D = w.D, b = std::min(w.ocfg.waveBand, 0.25f * D);
        const double phases[3][3] = {{0.0, 0.0, 0.0}, {1.2345, 5.4321, 3.0}, {-1, -1, -1}};
        for (const auto& ph : phases) {
            if (ph[0] < 0.0) for (int s = 0; s < 60; ++s) w.update(0.016f);
            else for (int i = 0; i < OceanWorld::kWaveTrains; ++i) waves[i].phase = ph[i];
            (void)w.flowAt({1.0f, 1.0f}, 1.0f);   // ensureFlow for this phase
            const FlowCache& c = ofp::field<ofp::peek::OwFlowT>(w);
            // The scalar reference for train i (false: the exact formulas).
            auto scalarTrain = [&](int i, Vec2 p, float d, Fl& u) -> bool {
                if (!c.depthOn) return false;
                float V, Vd;
                if (!(d > 0.0f && d < D)) {
                    if (!(d <= 0.0f || d >= D)) return false;   // NaN
                    V = 0.0f;
                    Vd = 0.0f;
                } else {
                    const int q = (d <= c.b) ? 0 : (d <= c.Dh) ? 1 : (d <= c.Dmb) ? 2 : 3;
                    const DepthPiece& pc = c.piece[q];
                    const double s = ((double)d - (double)pc.lo) * pc.scale;
                    if (!(s >= 0.0 && s <= (double)pc.n + 0.5)) return false;
                    int j = (int)s;
                    if (j > pc.n - 1) j = pc.n - 1;
                    const Basis B = basis((float)(s - (double)j));
                    const DepthCell& cl = pc.cell[j];
                    V = hval(B, cl.v[i], cl.dv[i], cl.m0[i], cl.m1[i]);
                    Vd = hder(B, cl.dv[i], cl.m0[i], cl.m1[i]) * pc.dScale;
                }
                auto coord = [](float x, double scale, int N, int& ix, float& tx) {
                    double s = (double)x * scale;
                    if (s < 0.0) s += (double)N;
                    if (s >= (double)N) s -= (double)N;
                    if (!(s >= 0.0 && s < (double)N)) return false;
                    ix = (int)s;
                    tx = (float)(s - (double)ix);
                    return true;
                };
                int ix, iy;
                float tx, ty;
                if (!coord(p.x, c.xScale, kXCells, ix, tx) || !coord(p.y, c.yScale, kYCells, iy, ty)) return false;
                const TrigCell X = getLane(xTable().cell[ix], i), Y = getLane(c.yRot[iy], i);
                const Basis bx = basis(tx), by = basis(ty);
                const float cx = hval(bx, X.c, X.dc, X.mc0, X.mc1), sx = hval(bx, X.s, X.ds, X.ms0, X.ms1);
                const float cxd = hder(bx, X.dc, X.mc0, X.mc1), sxd = hder(bx, X.ds, X.ms0, X.ms1);
                const float cy = hval(by, Y.c, Y.dc, Y.mc0, Y.mc1), sy = hval(by, Y.s, Y.ds, Y.ms0, Y.ms1);
                const float cyd = hder(by, Y.dc, Y.mc0, Y.mc1), syd = hder(by, Y.ds, Y.ms0, Y.ms1);
                const float P = cx * cy - sx * sy;
                const float gradT = c.TxS[i] * (cxd * cy - sxd * sy) + c.TyS[i] * (cx * cyd - sx * syd);
                u.x = (c.Tx[i] * Vd) * P;
                u.y = (c.Ty[i] * Vd) * P;
                u.d = (-V) * gradT;
                return true;
            };
            auto check = [&](Vec2 p, float d) {
                Fl sum = w.currentFlowAt(p, d);
                for (int i = 0; i < OceanWorld::kWaveTrains; ++i) {
                    Fl r;
                    if (scalarTrain(i, p, d, r)) ++tabled;
                    else { r = w.waveTrainExactAt(i, p, d); ++fallbacks; }
                    const Fl a = w.waveTrainAt(i, p, d);
                    ++compared;
                    if (!(same(a.x, r.x) && same(a.y, r.y) && same(a.d, r.d))) {
                        if (mismatched++ == 0) {
                            char buf[300];
                            std::snprintf(buf, sizeof buf, "%s train %d at (%.9g, %.9g, %.9g): vector (%a, %a, %a) scalar (%a, %a, %a)",
                                          v.name, i, (double)p.x, (double)p.y, (double)d, a.x, a.y, a.d, r.x, r.y, r.d);
                            firstBad = buf;
                        }
                    }
                    sum.x += r.x;
                    sum.y += r.y;
                    sum.d += r.d;
                }
                const Fl f = w.flowAt(p, d);
                ++compared;
                if (!(same(f.x, sum.x) && same(f.y, sum.y) && same(f.d, sum.d)) && mismatched++ == 0)
                    firstBad = std::string(v.name) + ": flowAt != the current + the scalar trains";
            };
            // depths: joins and their neighbours, piece / cell boundaries, ends, beyond, NaN, random
            std::vector<float> ds = {0.0f, D, -1.0f, D + 1.0f, std::nextafter(0.0f, 1.0f), std::nextafter(D, 0.0f),
                                     std::numeric_limits<float>::quiet_NaN()};
            for (float j : {b, 0.5f * D, D - b})
                for (float x : {j, std::nextafter(j, 0.0f), std::nextafter(j, D), std::nextafter(std::nextafter(j, D), D)})
                    ds.push_back(x);
            if (c.depthOn)
                for (int q = 0; q < 4; ++q) {
                    const DepthPiece& pc = c.piece[q];
                    for (int k = 0; k <= pc.n; k += std::max(1, pc.n / 9)) {
                        const float x = (float)((double)pc.lo + (double)k / pc.scale);
                        ds.push_back(x);
                        ds.push_back(std::nextafter(x, D));
                    }
                }
            const float W = (float)v.W, H = (float)v.H;
            std::vector<Vec2> ps = {{0.0f, 0.0f}, {W, H}, {std::nextafter(W, 0.0f), std::nextafter(H, 0.0f)},
                                    {-0.5f, H + 0.5f}, {W + 0.5f, -0.5f}, {-3.0f * W, 0.5f * H}, {0.5f * W, 4.0f * H},
                                    {std::nextafter(0.0f, -1.0f), std::nextafter(0.0f, 1.0f)}};
            Lcg g(1602);
            for (int k = 0; k < 400; ++k) ps.push_back({W * (-0.01f + 1.02f * g.unit()), H * (-0.01f + 1.02f * g.unit())});
            for (const Vec2& p : ps) {
                for (float d : ds) check(p, d);
                for (int k = 0; k < 6; ++k) check(p, D * g.unit());
            }
        }
    }
    t.expect(mismatched == 0, "%ld of %ld evaluations differ from the scalar reference; first: %s", mismatched, compared,
             firstBad.c_str());
    t.expect(tabled > 100000 && fallbacks > 1000, "too little coverage: %ld from the tables, %ld fallbacks", tabled, fallbacks);
    t.note("%ld evaluations (%ld train values from the tables, %ld fallbacks) == the scalar lane-by-lane evaluation, bit for bit",
           compared, tabled, fallbacks);
}
}  // namespace ot

#include "ocean_appearance_tests.hpp"
#include "ocean_sense_tests.hpp"
#include "ocean_speed_tests.hpp"   // the exact Turbo speed-ups' own checks

namespace ot {
#include "ocean_walls_tests.hpp"   // the glass walls (uses this file's helpers)
#include "ocean_exp_tests.hpp"     // the ALIFE 2027 instruments (eye build; uses this file's helpers)
}  // namespace ot

int main(int argc, char** argv) {
#ifndef OCEAN_TESTS_NO_SHIM
    if (argc > 1 && std::strcmp(argv[1], "--accepts") == 0) return ot::acceptsMain(argc, argv);
#else
    (void)argc; (void)argv;
#endif
    std::printf("ocean_tests: NUM_SENSES %d, NUM_ACTIONS %d\n", (int)NUM_SENSES, (int)NUM_ACTIONS);
    // --only label_mask: that test alone (tests/label_mask_fault.sh runs it on
    // copies of the engine with a planted fault, each of which must fail it)
    if (argc > 2 && std::strcmp(argv[1], "--only") == 0) {
        if (std::strcmp(argv[2], "label_mask") != 0) {
            std::fprintf(stderr, "--only: label_mask is the one test it runs\n");
            return 2;
        }
        ot::testLabelMask();
        std::printf("OCEAN TESTS: %d passed, %d failed\n", ot::g_passed, ot::g_failed);
        return ot::g_failed ? 1 : 0;
    }
    ot::testBounds();
    ot::testBuoyancy();
    ot::testSteerZ();
    ot::testSteerFrame();
    ot::testSensors();
    ot::testSensorSigns();
    ot::testCurrentSensors();
    ot::testWalls();
    ot::testCaptureNeutral();
    ot::testEye();
    ot::testEyeOnly();
    ot::testEyeCode();
    ot::testSenseEdges();   // tests/ocean_sense_tests.hpp: the scans' edges, pinned
    ot::testSenseRef();
    ot::testSenseRef(1);   // the same scenes with own-frame labels (OceanConfig::labelFrame, the A1 arm)
    ot::testLabelFrame();
    ot::testLabelFrameNeutral();
    ot::testFoodGrid();
    ot::testSenseMask();   // tests/ocean_speed_tests.hpp: the dead-sensor skip's mask,
    ot::testSenseDce();    // and what the speed-ups must keep
    ot::testCaptureToggle();
    ot::testLabelMask();   // tests/ocean_exp_tests.hpp: the skip under own-frame labels (labelFrame 1)
    ot::testFoodScan();
    ot::testFoodLife();
    ot::testRemovedNonFinite();
    ot::testReproducible();
    ot::testRadii();
#ifndef OCEAN_TESTS_NO_SHIM
    ot::testReset();
    ot::testProbe();
#endif
    ot::testPredatorEconomy();
    ot::testPairingGates();
    ot::testFastTanh();
    ot::testChild();
    ot::testDrawsMotion();
    ot::testDrawsBirth();
    ot::testDrawsPredators();
    ot::testDrawsFood();
    // E1 physics
    ot::testDivergence();
    ot::testFlowTables();
    ot::testFlowLanes();
    ot::testE1Buoyancy();
    ot::testDrift();
    ot::testCosts();
    ot::testFight();
    ot::testMouth();
    ot::testE1Neutral();
    ot::testE1Bounds();
    ot::testDrawsE1();
    ot::testLight();
    ot::testExp();
#ifndef OCEAN_TESTS_NO_SHIM
    ot::testRanges();
    ot::testShimInts();
    ot::testMotionBounds();
    ot::testShimBools();
#endif
    ot::testE1Hash();
    ot::testLazyWaves();
#ifndef OCEAN_TESTS_NO_SHIM
    ot::testPreset();
#endif
    ot::testWrap();
    // E1 with the eye build's features, and their keys through the shim
#ifndef OCEAN_TESTS_NO_SHIM
    ot::testVisionKeys();
    ot::testPreflight();
#endif
    ot::testEyeE1();
#ifdef EVO_OCEAN_EYE
    ot::testEyeExpProbe();   // the eye experiment's own probes (tools/ocean_eye_exp.cpp)
    ot::testEyeExpWiring();
    ot::testExpArmsShareInit();   // the ALIFE 2027 instruments: tests/ocean_exp_tests.hpp
    ot::testExpObserversNeutral();
    ot::testExpBranches();
#endif
    // the appearance genome (cosmetic): tests/ocean_appearance_tests.hpp
    ot::testAppearanceGallery();
    ot::testAppearanceStream();
    ot::testAppearanceBuild();
    ot::testAppearanceOwner();
    ot::testAppearanceNeutral();
    ot::testAppearanceDiversity();
    ot::testAppearanceHash();
    ot::testAppearanceEval();
#ifndef OCEAN_TESTS_NO_SHIM
    ot::testAppearanceShim();
#endif
    // the glass walls: tests/ocean_walls_tests.hpp
#ifndef OCEAN_TESTS_NO_SHIM
    ot::testWallsConfig();
#endif
    ot::testWallFlow();
    ot::testWallContainment();
    ot::testWallPlacement();
    ot::testWallTransport();
    ot::testWallWavesOff();
    ot::testWallEddy();
    ot::testWallSensing();
    ot::testWallDraws();
    std::printf("OCEAN TESTS: %d passed, %d failed\n", ot::g_passed, ot::g_failed);
    return ot::g_failed ? 1 : 0;
}

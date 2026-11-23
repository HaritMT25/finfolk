#pragma once
// ----------------------------------------------------------------------------
// OceanWorld — the 3-D preview world (PLAN_ocean_preview.md). Serial only.
//
// Adapted from Classic's World (src/core/world.hpp) with the thread paths and
// the profiler dropped. (x, y) is Classic's wrapping plane, unchanged; depth is
// a third coordinate in [0, D], clamped (0 = surface). Everything that does not
// depend on geometry is the kernel's (kernel.hpp) and WorldCommon's, called the
// way World calls it; what is here is what depth changes:
//
//   * fish move horizontally exactly as Classic's creatures (OceanConfig::
//     steerFrame 1 turns STEER_X / STEER_Y into the fish's own frame: right,
//     ahead), then vertically:
//       vz += steerZ·3·dt + kBuoy·(bodyBuoy·D − depth)/D·dt (+ MOVE_RANDOM's
//       third draw, + a soft push inside wallBand of surface / floor);
//       vz −= vz·vDrag·dt; |vz| ≤ pitchMax; depth += vz·speed·dt
//   * depth costs (OceanConfig cHold / cPress) after kernel::stepMetabolism
//   * optional food lifetime (OceanConfig::foodLife): uneaten food is removed
//     foodLife seconds after it appeared
//   * optional own-frame labels (OceanConfig::labelFrame 1): the labeled food /
//     neighbour direction senses report right / ahead instead of world x / y
//   * eating, interaction, sensing and the predators' capture use 3-D
//     distance: the SpatialGrid is still on (x, y), its candidates are
//     filtered by 3-D distance (a shallow sea: candidates per query stay
//     close to Classic's)
//   * five more sensors (LOC_Z, OWN_VEL_Z, NEAREST_FOOD_DZ, AVG_NEIGHBOR_DZ,
//     BOUNDARY_DIST_Z) and one more action (STEER_Z)
//   * predators (Stage A, and the Stage B economy as Classic has it) chase in
//     depth; a child predator buds at its parent's depth ± 8
//   * bodyBuoy: founders are neutral where they are dropped (depth / D);
//     a child gets its parents' mean + one U(±buoyMutation) draw, after
//     kernel::inheritFromPair; a child starts at its parents' midpoint depth
//
// Reused unchanged: SignalGrid (a column: the pheromone layer has no depth),
// CurrentField (horizontal), SpatialGrid, Predator (+ depth, pitch).
//
// E1 physics (OceanConfig, every knob OFF by default; OFF = the preview's
// arithmetic, bit for bit — each old block is kept as the fallback branch):
//   * flowAt(p, d): a 3-D, divergence-free flow = the current (× f(d) =
//     smoothstep(2d/D) when deepCurrent) + three tapered deep-water wave
//     trains (waveSpeed > 0). It replaces the horizontal current wherever
//     flowE1(): food (with foodDrift), predators and fish move by dt·U after
//     their own motion, a fish by min(1, 1/bodySize)·dt·U with sizeDrift;
//     depth is clamped after, x / y wrap. CURRENT_FWD / LR read flowAt.
//     While flowE1() it is evaluated from a derived cache (ocean_flow.hpp).
//   * lightAt(d) = L0·exp(−kWater·d) (oceanmath::expf, ocean_math.hpp):
//     display only (the page's shading); not part of the state.
//   * depthCostScaled: cHold / cPress as multiples of metabolicRate·massFactor.
//   * sizeFight: kernel::fightOutcome's strengths × bodySize²; mouthGate:
//     food (OceanFood::size, 1 for now) only if size <= kMouth·bodySize, for
//     eating and for the smell sensors alike.
// No E1 feature draws from the rng.
//
// The compound eye (build variant -DEVO_OCEAN_EYE, switched by OceanConfig::eye;
// PLAN_fish_patterns §7). One general sense: every object within the
// perception radius R — fish, food, predators — is binned by the dominant
// axis of its offset in the fish's LEVEL frame (forward = the horizontal
// heading, right = its perpendicular, down = depth) into six sectors: ahead,
// behind, left, right, up, down. Per sector, the NEAREST object gives three
// inputs (18 sensors, EYE_*):
//     PROX = 1 − d/R
//     SIZE = s / (s + d)       apparent size s/d, squashed to [0, 1)
//     CON  = b − L(z)          brightness against the ambient light at the
//                              object's depth, L(z) = exp(−kEyeWater·z)
// Objects differ only in (s, b): food glows (small, b = 1), predators are
// dark and large (b = 0.05), fish are b = 0.5 and s = bodySize x the body
// length (a placeholder until patterns give fish an appearance). The eye is
// computed inside the existing neighbour, food and predator loops — no extra
// queries — and draws no random numbers. Off (or in the plain Ocean build)
// the 18 inputs read 0, the same as six empty sectors.
//
// Why LEVEL (the fish's pitch is ignored, deliberately): a fish has no pitched
// body to look out of. It swims along a horizontal unit heading (Fish::vel) at
// `speed` and changes depth through a separate rate (vz; depth += vz·speed·dt;
// its drawn pitch is atan(vz)), and its motor commands act in that same level
// frame: STEER_X / STEER_Y (steerFrame 1: right / ahead of the horizontal
// heading) and STEER_Z (down). A level eye reports every offset in exactly the
// frame the fish can act in — ahead / behind / left / right against the
// heading and STEER_X, up / down against STEER_Z — whatever vz is at the
// moment. A pitched eye would tilt "ahead" into depth by atan(vz) (27° at the
// default pitchMax 0.5, 76° at pitchMax 4) and give "up" a different motor
// meaning at every pitch.
//
// What the eye sees within one step (the rule every labeled sense follows too,
// and Classic's World): fish are stepped in index order, each sensing and then
// moving, while the spatial grid holds every fish's START-of-step (x, y).
// Candidates are the grid's: the stored positions within R in (x, y) of the
// viewer's own start-of-step position (it senses before it moves). The eye
// then takes each candidate's offset from hot_, which a fish rewrites as soon
// as it has moved (with its new depth's contrast). So for viewer j:
//   * a fish i > j (not stepped yet) is seen exactly where it starts the step;
//   * a fish i < j (already stepped) is seen at its MOVED position, but only if
//     its start-of-step (x, y) was within R too: one that swam into range this
//     step is first seen next step (it is within one step's travel, maxSpeed·dt
//     plus the current, of the edge of R), and one that swam out is dropped by
//     the 3-D test on the moved offset (d² <= R²);
//   * food (drifted before the grid is built, eaten only after the per-fish
//     phase) and predators (a linear scan; they move after the per-fish phase)
//     are seen exactly where they are, with this step's contrast.
// Every binned object is within R of the viewer in 3-D (the test is on the
// offset actually used), so PROX is in [0, 1] and SIZE in (0, 1]; the stale grid
// can only delay a fish entering the edge of R by one step, never bin an object
// outside R or index past an array (no fish is born, dies or is reordered, and
// no predator is added or removed, during the per-fish phase).
//
// Eye encodings (OceanConfig::eyeCode, a bitmask, the eye build only; 0 = the
// eye above, bit for bit). They answer three limits of the nearest-object
// code for small evolved nets: a unipolar left / right pair needs two wires of
// opposite sign to steer both ways; CON does not fade with distance (it jumps
// from b − L to 0 at R); and the nearest object hides everything behind it.
// The 18 sensor names stay; what they report:
//   bit 0 (1) faded contrast: CON = PROX x (b − L(z)), 0 at R.
//   bit 2 (4) summed sectors: each sector sums over EVERY object in it, in
//          the eye's visit order (fish, then food, then predators; float sums
//          in that order), squashed by q(x) = x / (1 + |x|):
//              PROX = q(Σ (1 − d/R)),  SIZE = q(Σ s / (s + d)),
//              CON  = q(Σ (1 − d/R)(b − L(z)))   (always faded: bit 0 adds nothing)
//          so PROX and SIZE are in [0, 1) and CON in (−1, 1); one object at
//          d gives PROX = (1 − d/R) / (2 − d/R). An empty sector reads 0.
//   bit 1 (2) opponent pairs, applied last (after bit 0 / bit 2), per feature:
//              EYE_LEFT_*  = left + right     EYE_RIGHT_* = right − left
//              EYE_UP_*    = up + down        EYE_DOWN_*  = down − up
//          (AHEAD / BEHIND unchanged). Invertible — left = (L' − R') / 2,
//          right = (L' + R') / 2 — so nothing is lost, and EYE_RIGHT_* is
//          signed: one wire from it to STEER_X can turn toward either side.
//          PROX / SIZE: the sum slots are in [0, 2], the difference slots in
//          [−1, 1]; CON in [−2, 2] in both (open intervals with bit 2).
// Every encoding sees the same objects in the same order as code 0 (no extra
// queries, no draws), so eye-only mode's bit-identity holds for each.
// Two ablation bits (the "cloaked" eye) choose which KINDS of object the eye
// bins at all — the nearest or the sum is then over the rest, so a cloaked
// kind neither shows nor hides anything behind it:
//   bit 3 (8)  the eye ignores fish (food and predators still seen)
//   bit 4 (16) the eye ignores food (fish and predators still seen)
// Predators are always seen. Only the eye is cloaked: every labeled sense
// (and the interaction vote) is unchanged, so with the labels on the loops run
// as before and only skip the eye's bin; in eye-only mode eyeScan skips the
// cloaked kind's query altogether (it feeds nothing else). Each composes with
// the encodings (e.g. 12 = summed sectors over food and predators). No draws.
//
// Eye-only mode (OceanConfig::eyeOnly, the eye build only): the 23 LABELED
// exteroceptive senses the eye replaces (ocean::kLabeledSenses) read 0 and are
// not computed:
//     food:       NEAREST_FOOD_DX/DY/DZ, NEAREST_FOOD_DIST, FOOD_DENSITY
//     predators:  PREDATOR_FWD/LR/PROX
//     neighbours: NEIGHBOR_COUNT, AVG_NEIGHBOR_DX/DY/DZ,
//                 AVG_NEIGHBOR_HEADING_X/Y, NEAREST_NEIGHBOR_DIST,
//                 POPULATION_DENSITY/FWD/LR, LONGPROBE_POP_FWD,
//                 NEAREST_NEIGHBOR_AGE/FOOD, GENETIC_SIM_NEAREST/FWD
// Kept (23): own state and proprioception (LOC_X/Y/Z, BOUNDARY_DIST_X/Y/Z,
// BOUNDARY_DIST, OWN_VEL_X/Y/Z, OWN_SPEED, LAST_MOVE_DIR_X/Y, AGE,
// FOOD_RESERVES, OSCILLATOR, RESPONSIVENESS), the non-visual senses
// (SIGNAL0/_FWD/_LR, CURRENT_FWD/LR) and RANDOM_SENSOR; plus the 18 EYE_*
// inputs when the eye is on (eye 0 + eyeOnly 1 = "blind"). The eye sees the
// same objects in the same order as with the labels on, so its 18 inputs are
// bit-identical between the two modes for the same state. The pairwise
// interaction vote (kernel::interactionVote) builds its own contact inputs and
// is unchanged. No draws are added or removed (RANDOM_SENSOR is still drawn).
//
// Build note: the eye build has 64 sensors, so genes decode with % 64 instead
// of % 46 and its colour / SimHash planes are its own (STATS_DIM 1900); that is
// a different genetics from the plain Ocean build even with the eye off, which
// is why it is a separate build and the plain one is untouched.
//
// -DEVO_OCEAN_PROF adds a phase profiler (oprof: sensor gather, feedForward,
// movement + metabolism, the grid build and the serial phase) for the eye
// benchmark (tools/ocean_eye_bench.cpp); it changes no state.
//
// E1 with the eye build's features (each keeps its own definition):
//   * the eye sees every food item within R whatever its size: mouthGate
//     gates eating and the smell sensors (NEAREST_FOOD_*, FOOD_DENSITY), not
//     sight;
//   * a food item's eyeCon (the contrast the eye sees) is set at spawn and
//     set again whenever the E1 flow moves the item in depth (foodDrift), so
//     it is always eyeContrast(food glow, its depth) — without E1 food never
//     changes depth, so the set at spawn is the only one;
//   * a fish's look (hot_ eyeSize / eyeCon) is refreshed after it has moved,
//     flow drift included; predators' contrast is taken before the per-fish
//     phase (they move, and drift, after it);
//   * foodLife ages food after this step's drift and before the spawn, and
//     the spawn cap (targetFood·2) counts the LIVE items: what expired this
//     step frees its place in the same step's spawn, not only after the
//     end-of-step erase;
//   * CURRENT_FWD / LR (kept in eye-only mode) read the 3-D flow under E1;
//   * steerFrame turns STEER_X / STEER_Y before the flow drift is added.
//
// Glass walls (OceanConfig::walls, OFF by default — off, every result is the
// one before the key existed; on, toroidal is off: the senses and queries do
// not wrap, and nothing else does either). On:
//   * the side faces x = 0, W and y = 0, H are glass. A fish's or predator's
//     heading, once chosen (the same actions and draws), turns away inside
//     sideWallBand of a face (wallAvoid: a bounded rotation toward the inward
//     normal, sideWallTurnRate x the band depth rad/s); after swimming it is
//     clamped at contact with the outward heading component reflected (speed
//     kept), then carried by the wall flow, then contained again (the depth
//     faces' outward pitch removed); lastMoveDir, hot_ and the body trail
//     (held inside) follow the resolved result.
//   * the flow is the wall-compatible one (the "glass walls" evaluators: each
//     wave train a quadrature pair of Neumann standing modes, the current a
//     streamfunction tapered to zero at the side faces): divergence-free, no
//     flow through any of the six faces; every reader (food, fish, predators,
//     CURRENT_FWD / LR, the harness) gets it.
//   * food rides it with deterministic midpoint substeps (as many as the
//     flow's speed and scale need, up to 16; beyond, food lags water too fast
//     for it: wallFoodSteps, wallAdvect), every excursion
//     mirror-folded (never projected onto the glass); patch food
//     is drawn over the patch ∩ the tank (one draw per coordinate, as open);
//     a predator's bud is mirror-folded into the tank (the same draws).
// No wall step draws from the rng.
//
// The appearance genome (OceanConfig::appearance, ON by default; src/ocean/
// appearance_model.hpp): every fish's 63 cosmetic floats — skin pattern and
// body shape — in a side array bound to the fish by id (Fish / AgentCore are
// unchanged). Built for a founder right after markFounder (init and the
// minPopulation reseed), for a newborn when the append gives it its id (from
// its two parents, the first being the maternal source), compacted with
// `creatures` (stable, same order) after the predator phase. Each fish's
// draws come from its own counter-based stream keyed by (world key, id), NEVER
// from `rng`: no draw is added, removed or moved, and nothing the step reads
// depends on it, so every trajectory is the one appearance-off gives. The
// world key is taken at init from a copy of the seeded engine (the copy
// advances, the engine does not). A direct structural edit of `creatures`
// (push / erase / reorder without the side array) is detected at the next
// step: the records are dropped and appearanceBroken() reports it (the shim
// then exports none); attachFounderAppearance() keeps a direct append in step.
//
// The M2a body-plan preview (OceanConfig::bodyPlanPreviewEnabled, OFF by
// default; DIAGNOSTIC: src/ocean/physical_genome.hpp, body_plan.hpp): with it
// on, three more dense side arrays follow appearance's ownership exactly —
// the owner ids, each fish's five physical alleles (its own salted stream,
// keyed by the appearance key and its id: never `rng`) and its body plan
// compiled at birth from its appearance genome, bodySize and bodyElong. Built
// for a founder after its appearance record, for a newborn after its own
// (its parents read by their indices before compaction, copied before the
// arrays grow), compacted with the same alive mask, checked at the start of
// every step (count and owner ids; a broken appearance array breaks it too:
// dropped, reported by bodyPlanBroken()). Nothing the step reads depends on
// it: no draw, decision, cost or id moves (the harness's body twins).
// ----------------------------------------------------------------------------
#ifndef EVO_WORLD_OCEAN
#error "ocean_world.hpp needs the Ocean sensor list: compile with -DEVO_WORLD_OCEAN"
#endif
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include <limits>
#include <string>
#include <type_traits>
#include <vector>
#ifdef EVO_OCEAN_PROF
#include <chrono>
#endif
#include "../core/world.hpp"   // SignalGrid, MAX_TOPOLOGICAL_NEIGHBORS, and through it the
                               // kernel, WorldCommon, SpatialGrid, CurrentField, Predator
#include "ocean_config.hpp"
#include "ocean_transport.hpp"
#include "ocean_math.hpp"
#include "fish.hpp"
#include "appearance_model.hpp"
#include "body_plan.hpp"
#include "ocean_food_grid.hpp"

// The defensive clamps every Ocean entry point applies to the SimConfig half
// after reading the cfg JSON and before checking or using it: oc_init /
// oc_set_param (wasm/ocean_wasm.cpp clampConfig), the harness's world builder
// and live --set (tools/ocean_fingerprint.hpp clampConfigLikeShim), the probe
// (tools/ocean_probe.cpp). Main.cpp's clamps minus its min / max swaps (the
// Ocean refuses a reversed pair instead). perceptionRadius is the neighbour
// grids' cell size, so it must be >= 1: at 0 SpatialGrid::init divided by
// zero and cast the infinity to int. Only a finite radius is raised: -inf
// (a cfg's -1e400) is not a small radius but an invalid one, so it stays as
// it is for the radius check to refuse ("must be finite and >= 0",
// OceanWorld::radiusError), the previous world kept, as NaN and +inf are.
// (Raised to 1 it was accepted, while the page, keeping -1e400 in its
// bookkeeping, wrote it out as null: the world came back with the default.)
inline void clampOceanSimConfig(SimConfig& c) {
    if (std::isfinite(c.perceptionRadius) && c.perceptionRadius < 1.0f) c.perceptionRadius = 1.0f;
    if (c.maxNeighbors < 0) c.maxNeighbors = 0;
    if (c.maxNeighbors > MAX_TOPOLOGICAL_NEIGHBORS) c.maxNeighbors = MAX_TOPOLOGICAL_NEIGHBORS;
    if (c.predatorMinPopulation < 0) c.predatorMinPopulation = 0;
    if (c.predatorMinPopulation > 2000) c.predatorMinPopulation = 2000;
    if (c.predatorMaxPopulation < 0) c.predatorMaxPopulation = 0;
}

#include "ocean_entities.hpp"

namespace ocean {

// Names in enum order — Ocean's own copy (Classic's wiring::kSensorNames is
// sized by Classic's list and is not part of this build).
inline constexpr const char* kSensorNames[] = {
    "LOC_X","LOC_Y","BOUNDARY_DIST_X","BOUNDARY_DIST_Y","BOUNDARY_DIST",
    "OWN_VEL_X","OWN_VEL_Y","OWN_SPEED","LAST_MOVE_DIR_X","LAST_MOVE_DIR_Y",
    "AGE","FOOD_RESERVES","OSCILLATOR","RESPONSIVENESS",
    "NEIGHBOR_COUNT","AVG_NEIGHBOR_DX","AVG_NEIGHBOR_DY",
    "AVG_NEIGHBOR_HEADING_X","AVG_NEIGHBOR_HEADING_Y","NEAREST_NEIGHBOR_DIST",
    "POPULATION_DENSITY","POPULATION_FWD","POPULATION_LR",
    "NEAREST_NEIGHBOR_AGE","NEAREST_NEIGHBOR_FOOD","GENETIC_SIM_NEAREST","GENETIC_SIM_FWD",
    "NEAREST_FOOD_DX","NEAREST_FOOD_DY","NEAREST_FOOD_DIST","FOOD_DENSITY",
    "SIGNAL0","SIGNAL0_FWD","SIGNAL0_LR","LONGPROBE_POP_FWD",
    "CURRENT_FWD","CURRENT_LR",
    "PREDATOR_FWD","PREDATOR_LR","PREDATOR_PROX","RANDOM_SENSOR",
    "LOC_Z","OWN_VEL_Z","NEAREST_FOOD_DZ","AVG_NEIGHBOR_DZ","BOUNDARY_DIST_Z",
#ifdef EVO_OCEAN_EYE
    "EYE_AHEAD_PROX","EYE_AHEAD_SIZE","EYE_AHEAD_CON",
    "EYE_BEHIND_PROX","EYE_BEHIND_SIZE","EYE_BEHIND_CON",
    "EYE_LEFT_PROX","EYE_LEFT_SIZE","EYE_LEFT_CON",
    "EYE_RIGHT_PROX","EYE_RIGHT_SIZE","EYE_RIGHT_CON",
    "EYE_UP_PROX","EYE_UP_SIZE","EYE_UP_CON",
    "EYE_DOWN_PROX","EYE_DOWN_SIZE","EYE_DOWN_CON",
#endif
};
static_assert(sizeof(kSensorNames) / sizeof(kSensorNames[0]) == NUM_SENSES,
              "ocean::kSensorNames is out of sync with the Sensor enum");
inline constexpr const char* kActionNames[] = {
    "STEER_X","STEER_Y","MOVE_FORWARD","MOVE_RANDOM","SPEED_ADJUST","EMIT_SIGNAL0",
    "SET_OSCILLATOR_PERIOD","SET_RESPONSIVENESS",
    "INTERACT_SHARE","INTERACT_REPRODUCE","INTERACT_FIGHT","INTERACT_IGNORE","STEER_Z",
};
static_assert(sizeof(kActionNames) / sizeof(kActionNames[0]) == NUM_ACTIONS,
              "ocean::kActionNames is out of sync with the Action enum");

// Does sensor s drive action a through the wired net, directly or through any
// chain of hidden neurons? (Topology only; weights are not inspected.)
inline bool sensorReachesAction(const NeuralNet& nn, int s, int a) {
    bool reach[MAX_INTERNAL_NEURONS] = {};
    for (bool changed = true; changed;) {
        changed = false;
        for (const NeuralNet::FlatConn& fc : nn.flat) {
            const int src = fc.src(), sink = fc.sink();
            const bool on = (src == s) || (src >= NUM_SENSES && reach[src - NUM_SENSES]);
            if (!on) continue;
            if (sink == a) return true;
            if (sink >= NUM_ACTIONS && !reach[sink - NUM_ACTIONS]) {
                reach[sink - NUM_ACTIONS] = true;
                changed = true;
            }
        }
    }
    return false;
}

// Direct sensor -> action wire only.
inline bool sensorWiresAction(const NeuralNet& nn, int s, int a) {
    for (const NeuralNet::FlatConn& fc : nn.flat)
        if (fc.src() == s && fc.sink() == a) return true;
    return false;
}

// ---- the sensors a net reads (OceanWorld::computeSensors' dead-sensor skip) --
// SenseMask: bit s = sensor s. sensesRead(nn) sets bit s exactly when SOME
// flat connection's source is sensor s — any weight (0 included), any sink
// (an action or a hidden neuron); a hidden-neuron source sets none. A sensor
// with no such connection is read by nothing: feedForward multiplies only
// vals[fc.src()] of nn.flat's entries, so its value reaches no accumulator, no
// action and no neuron output. That is the whole argument for not computing
// it — a raw-source test, NOT "reaches an action" (a sensor feeding only a
// hidden neuron still sets that neuron's hashed output). Derived from nn.flat
// at each use (no cache to invalidate). With captureActivations on the step
// computes every sensor (kAllSenses): the captured lastSensors are hashed.
using SenseMask = std::uint64_t;
static_assert(NUM_SENSES <= 64, "a SenseMask holds one bit per sensor");
inline constexpr SenseMask senseBit(int s) { return SenseMask{1} << s; }
inline constexpr SenseMask kAllSenses =
    (NUM_SENSES >= 64) ? ~SenseMask{0} : (SenseMask{1} << (NUM_SENSES % 64)) - 1;
inline SenseMask sensesRead(const NeuralNet& nn) {
    SenseMask m = 0;
    for (const NeuralNet::FlatConn& fc : nn.flat) {
        const unsigned s = (unsigned)fc.src();
        // s & 63 keeps the shift defined for the eye build's sources >= 64
        // (hidden neurons); the (s < NUM_SENSES) factor makes those 0.
        m |= (SenseMask)(s < (unsigned)NUM_SENSES) << (s & 63u);
    }
    return m;
}
// The groups computeSensors skips whole; each lists every sensor its block
// writes. (Single sensors are gated by their own bit.)
inline constexpr SenseMask kSenseBoundaryXY =   // BOUNDARY_DIST is min(X, Y): it needs both
    senseBit(BOUNDARY_DIST_X) | senseBit(BOUNDARY_DIST_Y) | senseBit(BOUNDARY_DIST);
inline constexpr SenseMask kSenseGeneticSim = senseBit(GENETIC_SIM_NEAREST) | senseBit(GENETIC_SIM_FWD);
inline constexpr SenseMask kSenseNeighbours =   // all need the neighbour scan (the nearest's from it)
    senseBit(NEIGHBOR_COUNT) | senseBit(AVG_NEIGHBOR_DX) | senseBit(AVG_NEIGHBOR_DY) | senseBit(AVG_NEIGHBOR_DZ) |
    senseBit(AVG_NEIGHBOR_HEADING_X) | senseBit(AVG_NEIGHBOR_HEADING_Y) | senseBit(NEAREST_NEIGHBOR_DIST) |
    senseBit(POPULATION_DENSITY) | senseBit(POPULATION_FWD) | senseBit(POPULATION_LR) |
    senseBit(NEAREST_NEIGHBOR_AGE) | senseBit(NEAREST_NEIGHBOR_FOOD) | kSenseGeneticSim;
inline constexpr SenseMask kSenseFood = senseBit(NEAREST_FOOD_DX) | senseBit(NEAREST_FOOD_DY) |
                                        senseBit(NEAREST_FOOD_DZ) | senseBit(NEAREST_FOOD_DIST) | senseBit(FOOD_DENSITY);
inline constexpr SenseMask kSenseCurrent = senseBit(CURRENT_FWD) | senseBit(CURRENT_LR);
inline constexpr SenseMask kSensePredator = senseBit(PREDATOR_FWD) | senseBit(PREDATOR_LR) | senseBit(PREDATOR_PROX);
static_assert((kSenseNeighbours & kAllSenses) == kSenseNeighbours && (kSenseFood & kAllSenses) == kSenseFood,
              "a sense group names a sensor outside the list");

constexpr int kDepthBins = 8;

#ifdef EVO_OCEAN_EYE
// ---- the compound eye's constants (see the header comment) -----------------
constexpr int   kEyeSectors    = 6;        // ahead, behind, left, right, up, down
constexpr int   kEyeFirst      = EYE_AHEAD_PROX;
constexpr int   kEyeInputs     = 3 * kEyeSectors;
static_assert(EYE_DOWN_CON == kEyeFirst + kEyeInputs - 1, "eye sensors must be contiguous");
constexpr float kEyeWater      = 0.01f;    // ambient light L(z) = exp(−kEyeWater·z): 0.09 at z = 240
constexpr float kEyeFishLen    = 20.0f;    // a fish's size in world units per unit bodySize
                                           // (its 6-point spine: 5 segments of 4)
constexpr float kEyeFishBright = 0.5f;     // placeholder until patterns exist
constexpr float kEyeFoodSize   = 4.0f;     // food glows: small and bright
constexpr float kEyeFoodBright = 1.0f;
constexpr float kEyePredSize   = 60.0f;    // predators: large and dark
constexpr float kEyePredBright = 0.05f;

// L(z) = exp(−kEyeWater·z), through evomath::expm1f (bit-identical native / wasm).
inline float eyeAmbient(float z) { return 1.0f + evomath::expm1f(-kEyeWater * z); }
inline float eyeContrast(float bright, float z) { return bright - eyeAmbient(z); }

// The labeled exteroceptive senses eye-only mode zeroes (OceanConfig::eyeOnly;
// see the header comment). Everything else that is not EYE_* is kept.
inline constexpr int kLabeledSenses[] = {
    NEAREST_FOOD_DX, NEAREST_FOOD_DY, NEAREST_FOOD_DIST, FOOD_DENSITY, NEAREST_FOOD_DZ,
    PREDATOR_FWD, PREDATOR_LR, PREDATOR_PROX,
    NEIGHBOR_COUNT, AVG_NEIGHBOR_DX, AVG_NEIGHBOR_DY, AVG_NEIGHBOR_DZ,
    AVG_NEIGHBOR_HEADING_X, AVG_NEIGHBOR_HEADING_Y, NEAREST_NEIGHBOR_DIST,
    POPULATION_DENSITY, POPULATION_FWD, POPULATION_LR, LONGPROBE_POP_FWD,
    NEAREST_NEIGHBOR_AGE, NEAREST_NEIGHBOR_FOOD, GENETIC_SIM_NEAREST, GENETIC_SIM_FWD,
};
inline constexpr int kNumLabeledSenses = (int)(sizeof(kLabeledSenses) / sizeof(kLabeledSenses[0]));
static_assert(kNumLabeledSenses == 23, "eye-only mode's labeled-sense list changed");
inline constexpr bool isLabeledSense(int s) {
    for (int l : kLabeledSenses) if (l == s) return true;
    return false;
}
inline constexpr bool isEyeSense(int s) { return s >= kEyeFirst && s < kEyeFirst + kEyeInputs; }
#endif

}  // namespace ocean

class OceanWorld : public WorldCommon {
public:
    int width = 0, height = 0;
    float D = 240.0f;                       // == ocfg.depth
    OceanConfig ocfg;
    std::vector<Fish> creatures;
    std::vector<OceanPredator> predators;
    std::vector<OceanFood> food;
    SignalGrid signals;
    long long totalReseeds = 0;             // founders the minPopulation floor added (not births)
    long long totalFoodEaten = 0;           // food items eaten by fish (a statistic: not
                                            // part of the fingerprint, changes nothing)
    long long totalFoodExpired = 0;         // food items that reached foodLife uneaten (likewise)
    // A diagnostic (likewise not hashed, never read by the step): how many
    // non-finite floats the fish, food items and predators held when they
    // were removed (removedDead). An object killed by a non-finite value
    // (reserves -inf: it starves) is erased within the step that made it,
    // before any scan of the world can see it; this keeps the evidence.
    // tools/ocean_parity_driver.cpp adds each step's increase to that step's
    // non-finite count, so such a run fails the harness like any other.
    long long totalNonFiniteRemoved = 0;

    static long nonFiniteFloats(const Fish& c);
    static long nonFiniteFloats(const OceanFood& fd);
    static long nonFiniteFloats(const OceanPredator& p);
    template <class T>
    bool removedDead(const T& o);

    static constexpr float LONGPROBE_DIST = 200.0f;
    static constexpr float LONGPROBE_RADIUS = 30.0f;   // the probe's horizontal reach

    static std::string radiusError(const SimConfig& c, int w, int h);
    static float wrapDelta(float d, float span);
    float wrapDx(float d) const;
    float wrapDy(float d) const;
    // v wrapped into [0, span), span > 0, in constant time. It replaces the
    // loops `while (v < 0) v += span; while (v >= span) v -= span;`, which
    // never ended once v + span == v (currentStrength 1e20 moved food by ~1e17
    // per step), and gives their bits wherever they ended:
    //   * v in [-span, 2·span): the loops' one add / subtract, as they did it
    //     (an add that rounds up to span still ends at 0);
    //   * further out: std::fmod, which is exact (any correct libm, native or
    //     wasm, returns the same bits), then the loops' last add. With span a
    //     whole number <= 2^24 (a world size) and |v| < 2^24, every step of the
    //     loops was exact too, so this equals them there as well (pinned by
    //     tests/ocean_tests.cpp testWrap); a non-finite v gives NaN, not a hang.
    // The bounded configs (ocean_config.hpp) keep every caller in the first case.
    static float wrapCoord(float v, float span) { return oceantransport::wrapCoord(v, span); }
    // The preview's single-pass wrap of food and predators (`if (v < 0) v +=
    // span; else if (v >= span) v -= span;`), exactly as it was for every v in
    // [-span, 2·span) — an add that rounds up still leaves span there, as it
    // always did — and wrapCoord further out, where one pass left the value
    // outside the world (100 eddies at strength 1000 in a 100-wide world move
    // food ~150 in a step). The bounded cases never go further out: their
    // results are unchanged.
    static float wrapPreview(float v, float span) { return oceantransport::wrapPreview(v, span); }
    float clampDepth(float z) const { return oceantransport::clampDepth(flowState_, transportParams(), frame, z); }

    // ---- E1: flow and light ------------------------------------------------
    oceantransport::TransportParams transportParams() const {
        return {.width = width, .height = height, .D = D,
                .currentCore = cfg.currentCore, .currentDrift = cfg.currentDrift,
                .currentEddies = cfg.currentEddies, .currentGyreEps = cfg.currentGyreEps,
                .currentMode = cfg.currentMode, .currentStrength = cfg.currentStrength,
                .deepCurrent = ocfg.deepCurrent, .foodDrift = cfg.foodDrift,
                .toroidal = cfg.toroidal, .walls = ocfg.walls,
                .waveBand = ocfg.waveBand, .waveGravity = ocfg.waveGravity,
                .waveSpeed = ocfg.waveSpeed};
    }
    using Flow = oceantransport::Flow;   // d: + = sinking
    using FoodSteps = oceantransport::FoodSteps;

    static constexpr int kWaveTrains = oceantransport::kWaveTrains;
    bool wavesOn() const { return oceantransport::wavesOn(flowState_, transportParams(), frame); }
    // The 3-D flow replaces the preview's horizontal current (food, predators,
    // fish, the CURRENT sensors). Off: the preview's blocks run unchanged.
    bool flowE1() const { return oceantransport::flowE1(flowState_, transportParams(), frame); }

    // smoothstep S(r) = 3r² − 2r³ on r clamped to [0, 1], and dS/dr.
    static float smooth01(float r) { return oceantransport::smooth01(r); }
    static float smooth01d(float r) { return oceantransport::smooth01d(r); }

    // The flow at (p, depth d), units/s. Divergence-free:
    //  * the current C(p) (CurrentField, 2-D, from streamfunctions), times
    //    f(d) = S(2d/D) with deepCurrent (∇·(f C) = f ∇·C = 0), else times 1;
    //  * per wave train (K = 2π(m/W, n/H), k = |K|, q = K/k, θ = K·p − φ(t) + φ0):
    //    ψ = (A/k) e^{−kd} B(d) cos θ, B = S(d/b)·S((D−d)/b), b = min(waveBand, D/4);
    //    (u_x, u_y) = q·A e^{−kd} (B − B'/k) cos θ,  u_d = −A e^{−kd} B sin θ.
    //    B and B' vanish at surface and floor: no flow through either.
    // θ is formed and reduced to [0, 2π) in double (exact IEEE ops), then the
    // portable float sin / cos / expm1: the same bits native and wasm.
    // The depth taper B(d), B'(d) depends on d alone, so it is formed once per
    // call and shared by the three trains (the same expressions as
    // waveTrainExactAt(i, p, d): the same bits).
    //
    // Evaluation (ocean_flow.hpp): while flowE1() the flow comes from the E1
    // cache (flowFast) — the eddy current from the Ocean's own copy of the
    // vortices; off (sizeDrift alone reaches flowAt then) the exact formulas
    // above (flowExactAt), the preview's arithmetic. The public readers below
    // (flowAt, currentFlowAt, waveTrainAt, currentAt) give the field the step
    // actually uses; the *Exact* ones are the formulas, for the tests.
    // Glass walls (OceanConfig::walls) replace every reader's field with the
    // wall-compatible one (wallFlowFast / wallFlowExact below: standing-mode
    // pairs, a tapered streamfunction current); off, the branches below run
    // as they did.
    Flow flowAt(Vec2 p, float d) const { return oceantransport::flowAt(flowState_, transportParams(), frame, p, d); }
    Flow flowExactAt(Vec2 p, float d) const { return oceantransport::flowExactAt(flowState_, transportParams(), frame, p, d); }

    // flowAt's parts (public for the divergence probes in tests/ocean_tests.cpp).
    // The current, weighted by f(d) with deepCurrent; no vertical part.
    Flow currentFlowAt(Vec2 p, float d) const { return oceantransport::currentFlowAt(flowState_, transportParams(), frame, p, d); }
    Flow currentFlowExactAt(Vec2 p, float d) const { return oceantransport::currentFlowExactAt(flowState_, transportParams(), frame, p, d); }
    // The trains' shared depth taper B = S(d/b)·S((D−d)/b) and its d-derivative.
    using Taper = oceantransport::Taper;
    Taper taperAt(float d) const { return oceantransport::taperAt(flowState_, transportParams(), frame, d); }
    // Wave train i alone (whatever waveSpeed is; 0 gives zero flow — so do
    // trains never prepared, which only a world whose waves were never on has).
    // With walls, waves off return exact zeros before anything is read (the
    // pairs divide by |K|², 0 in trains never prepared: 0·inf was NaN).
    Flow waveTrainAt(int i, Vec2 p, float d) const { return oceantransport::waveTrainAt(flowState_, transportParams(), frame, i, p, d); }
    Flow waveTrainExactAt(int i, Vec2 p, float d) const { return oceantransport::waveTrainExactAt(flowState_, transportParams(), frame, i, p, d); }
    Flow waveTrainExactAt(int i, Vec2 p, float d, const Taper& tp) const { return oceantransport::waveTrainExactAt(flowState_, transportParams(), frame, i, p, d, tp); }

    // Light at depth d (display only in E1): L0·exp(−kWater·d), the exp taken
    // directly (oceanmath::expf: full relative precision at every depth). It
    // was L0·(1 + expm1f(−kWater·d)), which keeps only ~6e-8 absolute and is
    // exactly 0 below kWater·d = 17.3 (e.g. depth 18 at kWater 1).
    float lightAt(float d) const { return ocfg.L0 * oceanmath::expf(-ocfg.kWater * d); }

    // A wave train's travelled phase φ(t) in [0, 2π) (state; 0 until waves run).
    double wavePhase(int i) const { return flowState_.waves[i].phase; }
    bool waveClockStarted() const {
        for (const WaveTrain& t : flowState_.waves) if (t.phase != 0.0) return true;
        return false;
    }

    // Set cfg and ocfg first (ocfg.depth is overwritten by `depth`).
    void init(int w, int h, float depth, int numCreatures) {
        if (ocfg.walls) cfg.toroidal = false;   // glass walls never wrap (the validated paths refuse both)
        appearanceInit();   // first: its key reads a COPY of the engine before any draw
        bodyPlanInit();     // its key is the appearance key's, salted (no draw)
        width = w;
        height = h;
        D = depth;
        ocfg.depth = depth;
        signals.init(w, h, 8, cfg.toroidal);
        creatureGrid_.init(w, h, cfg.perceptionRadius);
        foodGrid_.init(w, h, cfg.perceptionRadius);

        CurrentField::Mode cmode = (cfg.currentMode == 1) ? CurrentField::Mode::Gyre
                                                           : CurrentField::Mode::Eddies;
        flowState_.current.init(cmode, w, h, cfg.currentEddies, cfg.currentStrength,
                      cfg.currentCore, cfg.currentDrift, cfg.currentGyreEps);
        initFlowCache();
        for (WaveTrain& t : flowState_.waves) t = WaveTrain{};   // unprepared (a reused world too)
        ensureWaves();                                 // prepared now only if the waves are on
        foodPatches_.clear();
        foodPatchDepth_.clear();
        for (int i = 0; i < cfg.foodPatches; ++i) {
            foodPatches_.push_back({rng.range(0.0f, (float)w), rng.range(0.0f, (float)h)});
            if (ocfg.foodDepthMode == 1) foodPatchDepth_.push_back(rng.range(0.0f, D));
        }

        creatures.clear();
        creatures.reserve(numCreatures * 2);
        for (int i = 0; i < numCreatures; ++i) addFounder();

        predators.clear();
        for (int i = 0; i < cfg.predatorCount; ++i) predators.push_back(makePredator());

        food.clear();
        for (int i = 0; i < cfg.targetFood; ++i) spawnFood();
        if (ocfg.foodLife > 0.0f) {   // the first stock's ages spread over [0, foodLife)
            const float n = (float)food.size();
            for (std::size_t i = 0; i < food.size(); ++i) food[i].age = ocfg.foodLife * ((float)i / n);
        }
        totalReseeds = 0;
        totalFoodEaten = 0;
        totalFoodExpired = 0;
        totalNonFiniteRemoved = 0;
    }

    void spawnFood() {
        OceanFood f;
        int patch = -1;
        if (!foodPatches_.empty()) {
            patch = (int)rng.uint((uint32_t)foodPatches_.size() - 1);
            const Vec2& c = foodPatches_[patch];
            const float R = cfg.foodPatchRadius;
            if (cfg.toroidal) {
                f.pos = { wrapCoord(c.x + rng.range(-R, R), (float)width),
                          wrapCoord(c.y + rng.range(-R, R), (float)height) };
            } else if (ocfg.walls) {   // inside the glass: the same draws, over the patch ∩ the tank
                f.pos = { wallPatchDraw(c.x, R, (float)width), wallPatchDraw(c.y, R, (float)height) };
            } else {
                f.pos = { std::clamp(c.x + rng.range(-R, R), 0.0f, (float)width),
                          std::clamp(c.y + rng.range(-R, R), 0.0f, (float)height) };
            }
        } else {
            f.pos = {rng.range(10.0f, (float)width - 10.0f),
                     rng.range(10.0f, (float)height - 10.0f)};
        }
        if (ocfg.foodDepthMode == 1 && patch >= 0 && patch < (int)foodPatchDepth_.size()) {
            const float S = ocfg.foodDepthSpread;
            f.depth = ocfg.walls ? wallPatchDraw(foodPatchDepth_[patch], S, D)
                                 : clampDepth(foodPatchDepth_[patch] + rng.range(-S, S));
        } else {
            f.depth = rng.range(0.0f, D);
        }
#ifdef EVO_OCEAN_EYE
        f.eyeCon = ocean::eyeContrast(ocean::kEyeFoodBright, f.depth);   // no draws
#endif
        food.push_back(f);
    }

    void update(float dt) {
#ifdef EVO_OCEAN_PROF
        using pclk = std::chrono::steady_clock;
        const auto tStep0 = pclk::now();
#endif
        frame++;
        births = 0;
        deaths = 0;
        appearanceCheck();   // the side array still matches `creatures` (else it is dropped)
        bodyPlanCheck();     // the body-plan arrays too (and appearance still on)

        oceantransport::advanceFlowClock(flowState_, transportParams(), frame, dt);
        const auto params = transportParams();
        if (params.walls || oceantransport::flowE1(flowState_, params, frame)) ensureFlow();
        transportFood(dt);

        // Every item is alive here (the last step erased the dead ones), so
        // food.size() - expiredNow is the live stock the spawn cap counts.
        int expiredNow = 0;   // marked dead just below; erased at the end of the step
        if (ocfg.foodLife > 0.0f) {   // food older than foodLife is gone, eaten or not
            for (auto& f : food) {
                if (!f.alive) continue;
                f.age += dt;
                if (f.age >= ocfg.foodLife) { f.alive = false; ++totalFoodExpired; ++expiredNow; }
            }
        }

        // The cap is on live items: an expired one frees its place now (foodLife
        // off: expiredNow is 0, the cap as it always was).
        float foodRate = cfg.foodSpawnBase + cfg.foodSpawnAmp * evomath::sinf(frame * 0.001f);
        for (int i = 0; i < static_cast<int>(foodRate); ++i) {
            if (static_cast<int>(food.size()) - expiredNow < cfg.targetFood * 2) spawnFood();
        }

        if (frame % 3 == 0) signals.decay();

        creatureGrid_.clear();
        foodGrid_.clear();
        const int numCreatures = (int)creatures.size();
        const int numFood = (int)food.size();
        hot_.resize(numCreatures);
        for (int i = 0; i < numCreatures; ++i) {
            const Fish& c = creatures[i];
            hot_[i] = {c.pos, c.vel, c.depth};
            if (c.alive) creatureGrid_.insert(c.pos, i);
        }
        for (int i = 0; i < numFood; ++i)
            if (food[i].alive) foodGrid_.insert(food[i], i);
        creatureGrid_.build();
        foodGrid_.build();

        pending_.assign(numCreatures, PendingSignal{});
#ifdef EVO_OCEAN_EYE
        if (ocfg.eye) eyePrepare();
#endif
#ifdef EVO_OCEAN_PROF
        const auto tFish0 = pclk::now();
        oprof.buildNs += std::chrono::duration<double, std::nano>(tFish0 - tStep0).count();
#endif

        // ---- per-fish phase: sensors, network, movement, metabolism ----------
#ifdef EVO_OCEAN_EYE
        // Summed sectors (eyeCode bit 2) change what the eye accumulates per
        // object, so they are their own instantiation; the other bits only
        // change eyeWrite, once per fish.
        const bool eyeSum = (ocfg.eyeCode & kEyeCodeSummed) != 0;
        if (ocfg.eyeOnly) {   // labels off: the eye alone, or nothing ("blind")
            if (ocfg.eye && eyeSum) { for (int i = 0; i < numCreatures; ++i) stepFish<true, false, true>(i, dt); }
            else if (ocfg.eye)      { for (int i = 0; i < numCreatures; ++i) stepFish<true, false>(i, dt); }
            else                    { for (int i = 0; i < numCreatures; ++i) stepFish<false, false>(i, dt); }
        } else
        if (ocfg.eye && eyeSum) { for (int i = 0; i < numCreatures; ++i) stepFish<true, true, true>(i, dt); }
        else
        if (ocfg.eye) { for (int i = 0; i < numCreatures; ++i) stepFish<true>(i, dt); }
        else
#endif
        for (int i = 0; i < numCreatures; ++i) stepFish<false>(i, dt);
#ifdef EVO_OCEAN_PROF
        const auto tSerial0 = pclk::now();
        oprof.fishPhaseNs += std::chrono::duration<double, std::nano>(tSerial0 - tFish0).count();
#endif

        // ---- serial phase: signals, deaths, eating, interaction --------------
        std::vector<Fish> newborns;
        std::vector<std::uint32_t> newbornParents;   // appearance: (maternal, other) index per newborn
        const float pr2 = cfg.pickupRadius * cfg.pickupRadius;
        const float ir2 = cfg.interactRadius * cfg.interactRadius;
        for (int i = 0; i < numCreatures; ++i) {
            Fish& c = creatures[i];
            if (!c.alive) continue;

            if (pending_[i].wants) signals.emit(pending_[i].pos);

            if (const char cause = kernel::deathCause(c, cfg)) {
                recordDeath(c, cause);
                continue;
            }

            nearbyFood_.clear();
            if (cfg.toroidal) foodGrid_.queryRadiusWrapped(c.pos, cfg.pickupRadius, nearbyFood_);
            else              foodGrid_.queryRadius(c.pos, cfg.pickupRadius, nearbyFood_);
            for (int fi : nearbyFood_) {
                OceanFood& f = food[fi];
                if (!f.alive) continue;
                if (dist2(c.pos, c.depth, f.pos, f.depth) > pr2) continue;
                if (ocfg.mouthGate && f.size > ocfg.kMouth * c.bodySize) continue;   // E1: too big to swallow
                f.alive = false;
                c.foodReserves += cfg.foodEnergy;
                ++totalFoodEaten;
            }

            if (c.interactTimer <= 0.0f) {
                nearby_.clear();
                if (cfg.toroidal) creatureGrid_.queryRadiusWrapped(c.pos, cfg.interactRadius, nearby_);
                else              creatureGrid_.queryRadius(c.pos, cfg.interactRadius, nearby_);
                for (int ni : nearby_) {
                    if (ni == i) continue;
                    Fish& other = creatures[ni];
                    if (!other.alive || other.interactTimer > 0.0f) continue;
                    if (dist2(c.pos, c.depth, other.pos, other.depth) > ir2) continue;
                    doInteraction(c, other, newborns, newbornParents);
                    c.interactTimer = cfg.interactCooldown;
                    other.interactTimer = cfg.interactCooldown;
                    break;
                }
            }
        }

        for (auto& baby : newborns) { baby.id = nextId_++; creatures.push_back(std::move(baby)); }
        if (appearanceOn()) appearanceAppendNewborns(newborns.size(), newbornParents);
        if (bodyPlanOn()) bodyPlanAppendNewborns(newborns.size(), newbornParents);   // (on => appearance on: parents recorded)

        updatePredators(dt);
        if (cfg.predatorEconomy && cfg.predatorMinPopulation > 0) refillPredators();

        if (appearanceOn()) appearanceCompact();   // keeps records[i] where creatures[i].alive (same order)
        if (bodyPlanOn()) bodyPlanCompact();       // the same mask
        creatures.erase(std::remove_if(creatures.begin(), creatures.end(),
                                       [this](const Fish& c) { return removedDead(c); }),
                        creatures.end());
        food.erase(std::remove_if(food.begin(), food.end(),
                                  [this](const OceanFood& f) { return removedDead(f); }),
                   food.end());

        if ((int)creatures.size() < cfg.minPopulation) {
            const int toAdd = cfg.minPopulation - (int)creatures.size();
            for (int j = 0; j < toAdd; ++j) { addFounder(); totalReseeds++; }
        }
#ifdef EVO_OCEAN_PROF
        const auto tEnd = pclk::now();
        oprof.serialNs += std::chrono::duration<double, std::nano>(tEnd - tSerial0).count();
        oprof.totalNs  += std::chrono::duration<double, std::nano>(tEnd - tStep0).count();
        oprof.steps++;
        oprof.fishSteps += numCreatures;
#endif
    }

#ifdef EVO_OCEAN_PROF
    // Wall time per phase, summed over steps (single-threaded, so the per-fish
    // split sens + ff + move is a share of fishPhaseNs; the clock calls in it
    // cost a little, which is why it is a separate build).
    struct OceanProf {
        double buildNs = 0, fishPhaseNs = 0, serialNs = 0, totalNs = 0;
        double sensNs = 0, ffNs = 0, moveNs = 0;   // inside the per-fish phase
        long long steps = 0, fishSteps = 0;
    } oprof;
#endif

    bool currentActive() const { return oceantransport::currentActive(flowState_, transportParams(), frame); }
    // The 2-D current the step uses: while flowE1() with eddies, the Ocean's
    // evaluator (ocean_flow.hpp); otherwise CurrentField's own.
    Vec2 currentAt(Vec2 p) const { return oceantransport::currentAt(flowState_, transportParams(), frame, p); }
    Vec2 currentExactAt(Vec2 p) const { return oceantransport::currentExactAt(flowState_, transportParams(), frame, p); }   // CurrentField's own (tests)

    void depthStats(double& mean, double& sd, double hist[ocean::kDepthBins]) const;

    int appearanceFlags() const;
    int appearanceInitFlags() const;
    bool appearanceBroken() const;
    std::uint64_t appearanceKey() const;
    const std::vector<appearance::Record>& appearanceRecords() const;
    const appearance::Stats& appearanceStats() const;
    bool appearanceConsistent() const;
    void attachFounderAppearance();
    bool bodyPlanInitEnabled() const;
    bool bodyPlanEnabled() const;
    bool bodyPlanBroken() const;
    std::uint64_t bodyPlanKey() const;
    const std::vector<std::uint64_t>& bodyPlanOwners() const;
    const std::vector<physical::Genes>& bodyPlanGenes() const;
    const std::vector<bodyplan::BirthCoefficients>& bodyPlanBirth() const;
    const physical::Stats& bodyPlanStats() const;
    std::uint64_t bodyPlanRevision() const;
    std::uint64_t bodyPlanUncompiled() const;
    bool bodyPlanConsistent() const;
    physical::Inheritance bodyPlanInheritance() const;
    appearance::Inheritance appearanceInheritance() const;

private:
    bool appearanceOn() const;
    void appearanceInit();
    void appearanceAppendFounder();
    void appearanceAppendNewborns(std::size_t n, const std::vector<std::uint32_t>& parents);
    void appearanceCompact();
    void appearanceCheck();
    bool bodyPlanOn() const;
    void bodyPlanInit();
    void bodyPlanPush(std::size_t i, const physical::Genes& G);
    void bodyPlanAppendFounder();
    void bodyPlanAppendNewborns(std::size_t n, const std::vector<std::uint32_t>& parents);
    void bodyPlanCompact();
    void bodyPlanBreak();
    void bodyPlanCheck();
    struct FishHot {
        Vec2 pos; Vec2 vel; float depth;
#ifdef EVO_OCEAN_EYE
        float eyeSize, eyeCon;   // how the eye sees this fish (set only while it is on)
#endif
    };
    struct PendingSignal { bool wants = false; Vec2 pos; };
    struct Candidate { float distSq, dx, dy, dz; int index; };
    struct FoodSeen { float dx, dy, dz, d2; int k; };   // a food item within R: its offset, d², grid slot

    SpatialGrid creatureGrid_;
    OceanFoodGrid foodGrid_;   // SpatialGrid's layout and queries + each item's depth / size / eyeCon
    std::vector<FishHot> hot_;
    std::vector<int> advectIdx_;   // transportFood's live items, reused
    std::vector<PendingSignal> pending_;
    std::vector<int> neighbors_, nearbyFood_, nearby_, near_;
    std::vector<FoodSeen> foodSeen_;   // foodWithin's list (scratch, one fish at a time)
    oceantransport::FlowState flowState_;
    std::vector<Vec2> foodPatches_;
    std::vector<float> foodPatchDepth_;   // foodDepthMode 1: one depth per patch
    // The appearance genome (see the header comment). Hashed in the harness's
    // own `app` section, outside the simulation's sections.
    std::vector<appearance::Record> app_;   // records[i] <-> creatures[i]
    std::uint64_t appKey_ = 0;              // the world's stream key (init)
    int appFlags_ = 0;                      // OceanConfig::appearance at init
    bool appBroken_ = false;                // the side array lost its owners (dropped)
    appearance::Stats appStats_;            // records built, branches taken (statistics)
    // The M2a body-plan preview (see the header comment; diagnostic). Hashed
    // in the harness's own `body` section, outside the simulation's sections.
    std::vector<std::uint64_t> bodyOwners_;                 // [i] == creatures[i].id
    std::vector<physical::Genes> bodyGenes_;                // the five physical alleles
    std::vector<bodyplan::BirthCoefficients> bodyBirth_;    // the body plan compiled at birth
    std::uint64_t bodyKey_ = 0;                             // the physical stream's world key (init)
    std::uint64_t bodyRevision_ = 0;                        // the arrays' change counter (exports)
    std::uint64_t bodyUncompiled_ = 0;                      // compiles refused (statistics)
    physical::Stats bodyStats_;                             // records built, branches taken (statistics)
    bool bodyFlag_ = false;                                 // OceanConfig::bodyPlanPreviewEnabled at init
    bool bodyBroken_ = false;                               // the arrays lost their owners (dropped)

    // Flow state lives in oceantransport; retain only the private entry points
    // used by world initialization and execution. Public readers forward above.
    using WaveTrain = oceantransport::WaveTrain;
    void ensureWaves() const { oceantransport::ensureWaves(flowState_, transportParams(), frame); }
    void initFlowCache() { oceantransport::initFlowCache(flowState_, transportParams(), frame); }
    void ensureFlow() const { oceantransport::ensureFlow(flowState_, transportParams(), frame); }
    Flow flowFast(Vec2 p, float d) const { return oceantransport::flowFast(flowState_, transportParams(), frame, p, d); }
    Flow flowStep(Vec2 p, float d) const { return oceantransport::flowStep(flowState_, transportParams(), frame, p, d); }
    Flow wallFlowFast(Vec2 p, float d) const { return oceantransport::wallFlowFast(flowState_, transportParams(), frame, p, d); }

    static constexpr float kPiF = 3.14159265358979f;

    void wallAvoid(Vec2 p, Vec2& h, float dt) const;
    bool wallContact(Vec2& p, Vec2& h) const;
    void containBody(Fish& c) const;
    static float wallPatchDraw(float c, float R, float L);
    void transportFood(float dt) {
        oceantransport::transportFood(flowState_, transportParams(), frame, dt,
            std::span<const OceanFood>(food), std::span<OceanFood>(food), advectIdx_
#ifdef EVO_OCEAN_EYE
            , [](float d) { return ocean::eyeContrast(ocean::kEyeFoodBright, d); }
#endif
        );
    }

public:
    // q mirror-folded into [0, L] (period 2L: r = q mod 2L, r or 2L − r):
    // never wrapped to the opposite face, never piled onto one.
    static float mirrorFold(float q, float L) { return oceantransport::mirrorFold(q, L); }
    // One particle's transport over dt through the wall flow, frozen at this
    // step's time (ensureFlow done): n midpoint (RK2) substeps (wallFoodSteps),
    // every trial and final coordinate mirror-folded into the tank. (A single
    // forward step, tried for n = 1, spiralled food out of eddies: its radial
    // error is ~θ²/2 per step, +126% in 600 frames at currentStrength 60 and
    // core 30 against the midpoint's 7e-4.) Not claimed to preserve volume
    // exactly: tests "wall_transport" checks uniform tracers for wall
    // accumulation and convergence in n, "wall_eddy" a stationary eddy's radii
    // and density.
    void wallAdvect(Vec2& p, float& d, float dt, int n) const { oceantransport::wallAdvect(flowState_, transportParams(), frame, p, d, dt, n); }
    // Four particles through wallAdvect's midpoint step at once, each lane
    // wallAdvect's result bit for bit (tests "wall_advect4"): the current (the
    // eddy sum, the wall tapers, the deep factor), the half and full steps and
    // the folds are evaluated lane-wise (oceanflow::v4f: the same IEEE
    // operation per lane as the scalar expression, a select where the scalar
    // branches, a lane's table index clamped where the scalar would have
    // skipped it), the wave trains per item by the very wallWavesTable /
    // wallTrainExactAt, and the sums U = current + train 0 + train 1 + train 2
    // in that order. A fold outside [0, L] takes the scalar mirrorFold per lane.
    void wallAdvect4(Vec2 p[4], float d[4], float dt, int n) const { oceantransport::wallAdvect4(flowState_, transportParams(), frame, p, d, dt, n); }
    bool wallFlowOn() const { return oceantransport::wallFlowOn(flowState_, transportParams(), frame); }
    int wallFoodSubstepsNow(float dt) const { return oceantransport::wallFoodSubstepsNow(flowState_, transportParams(), frame, dt); }   // (tests)
    FoodSteps wallFoodStepsNow(float dt) const { return oceantransport::wallFoodStepsNow(flowState_, transportParams(), frame, dt); }  // (tests: n, the time, the need)

private:

#ifdef EVO_OCEAN_EYE
    // ---- the compound eye ---------------------------------------------------
    std::vector<float> predCon_;   // per predator, this step: dark − ambient light

    struct EyeBin { float d2, size, con; };     // the nearest object in one sector
    struct EyeSum { float prox, size, con; };   // summed sectors (eyeCode bit 2): the running
                                                // Σ(1 − d/R), Σ s/(s + d), Σ(1 − d/R)(b − L)

    void eyePrepare();
    static int eyeSector(Vec2 fwd, Vec2 rht, float dx, float dy, float dz);
    static void eyeSee(EyeBin* eye, Vec2 fwd, Vec2 rht, float dx, float dy, float dz, float d2,
                       float size, float con, float /*R*/);
    static void eyeSee(EyeSum* eye, Vec2 fwd, Vec2 rht, float dx, float dy, float dz, float d2,
                       float size, float con, float R);
    static void eyeInit(EyeBin* eye);
    static void eyeInit(EyeSum* eye);
    static void eyeOpponent(float sensors[]);
    static void eyeWrite(const EyeBin* eye, float R, int code, float sensors[]);
    static float eyeSquash(float x);
    static void eyeWrite(const EyeSum* eye, float /*R*/, int code, float sensors[]);
#endif

    float dist2(Vec2 a, float za, Vec2 b, float zb) const;

    void addFounder() {
        Vec2 pos = {rng.range(10.0f, (float)width - 10.0f),
                    rng.range(10.0f, (float)height - 10.0f)};
        const float z = rng.range(0.0f, D);
        creatures.push_back(makeRandomFish(pos, z, D, cfg.genomeInitMin, cfg.genomeInitMax));
        if (ocfg.walls) containBody(creatures.back());   // its trail laid out behind it stays inside
        markFounder(creatures.back());
        if (appearanceOn()) appearanceAppendFounder();
        if (bodyPlanOn()) bodyPlanAppendFounder();
    }

    OceanPredator makePredator();

    // Eye: the compound eye is on this step (only ever true in the eye build).
    // Labels: the labeled exteroceptive senses are computed (false only in the
    // eye build's eye-only mode, OceanConfig::eyeOnly).
    // Sum: the eye sums every object per sector (OceanConfig::eyeCode bit 2;
    // only with Eye).
    template <bool Eye, bool Labels = true, bool Sum = false>
    void stepFish(int i, float dt) {
        Fish& c = creatures[i];
        if (!c.alive) return;
#ifdef EVO_OCEAN_PROF
        using pclk = std::chrono::steady_clock;
        const auto p0 = pclk::now();
#endif

        float sensors[NUM_SENSES];
        std::memset(sensors, 0, sizeof(sensors));
        // The sensors this net reads (ocean::sensesRead); every one when the
        // step captures them. With capture off, sensors[] is read only by
        // feedForward below, so a sensor outside `need` is never read.
        const ocean::SenseMask need = cfg.captureActivations ? ocean::kAllSenses : ocean::sensesRead(c.nnet);
        computeSensors<Eye, Labels, Sum>(c, i, sensors, need);
#ifdef EVO_OCEAN_PROF
        const auto p1 = pclk::now();
#endif

        float actions[NUM_ACTIONS];
        std::memset(actions, 0, sizeof(actions));
        feedForward(c.nnet, sensors, actions, cfg.fastTanh);
#ifdef EVO_OCEAN_PROF
        const auto p2 = pclk::now();
        oprof.sensNs += std::chrono::duration<double, std::nano>(p1 - p0).count();
        oprof.ffNs   += std::chrono::duration<double, std::nano>(p2 - p1).count();
#endif

        if (cfg.captureActivations) {
            std::memcpy(c.lastSensors, sensors, sizeof(sensors));
            std::memcpy(c.lastActions, actions, sizeof(actions));
        }

        const float resp = c.responsiveness;
        const float effMax = std::max(cfg.minSpeed, cfg.maxSpeed * speedFactor(c));
        float rndZ = 0.0f;   // MOVE_RANDOM's third draw, applied to vz below

        // ---- horizontal: Classic's two motion models, unchanged ----
        if (cfg.triangularMotion) {
            float drive = std::clamp(0.5f * (actions[MOVE_FORWARD] + 1.0f), 0.0f, 1.0f);
            float turn  = actions[STEER_X];
            float turnEff = turn * (1.0f - drive) * resp;
            float theta = evomath::atan2f(c.vel.y, c.vel.x);
            theta += turnEff * (cfg.maxTurnRate * turnFactor(c)) * dt;
            c.vel.x = evomath::cosf(theta);
            c.vel.y = evomath::sinf(theta);
            c.speed = std::clamp(cfg.minSpeed + drive * (effMax - cfg.minSpeed),
                                 cfg.minSpeed, effMax);
            if (ocfg.walls) wallAvoid(c.pos, c.vel, dt);   // glass walls: the soft turn (no draws)
            c.lastMoveDir = c.vel;
            c.pos.x += c.vel.x * c.speed * dt;
            c.pos.y += c.vel.y * c.speed * dt;
        } else {
            float steerX = actions[STEER_X] * resp;
            float steerY = actions[STEER_Y] * resp;
            float moveFwd = actions[MOVE_FORWARD] * resp;
            float moveRnd = actions[MOVE_RANDOM] * resp;
            float speedAdj = actions[SPEED_ADJUST] * resp;

            if (ocfg.steerFrame == 1) {   // the fish's own frame: x = right, y = ahead
                const Vec2 f0 = c.forward();
                const Vec2 r0 = {-f0.y, f0.x};
                c.vel.x += (r0.x * steerX + f0.x * steerY) * 3.0f * dt;
                c.vel.y += (r0.y * steerX + f0.y * steerY) * 3.0f * dt;
            } else {
                c.vel.x += steerX * 3.0f * dt;
                c.vel.y += steerY * 3.0f * dt;
            }
            auto fwd = c.forward();
            c.vel.x += fwd.x * moveFwd * 2.0f * dt;
            c.vel.y += fwd.y * moveFwd * 2.0f * dt;
            if (std::abs(moveRnd) > 0.5f) {
                c.vel.x += rng.range(-1.0f, 1.0f) * std::abs(moveRnd) * dt;
                c.vel.y += rng.range(-1.0f, 1.0f) * std::abs(moveRnd) * dt;
                rndZ = rng.range(-1.0f, 1.0f) * std::abs(moveRnd) * dt;
            }
            float vlen = std::sqrt(c.vel.x * c.vel.x + c.vel.y * c.vel.y);
            if (vlen > 0.001f) { c.vel.x /= vlen; c.vel.y /= vlen; }
            c.speed += speedAdj * 50.0f * dt;
            c.speed = std::clamp(c.speed, cfg.minSpeed, effMax);
            if (ocfg.walls) wallAvoid(c.pos, c.vel, dt);   // glass walls: the soft turn (no draws)
            c.lastMoveDir = c.vel;
            c.pos.x += c.vel.x * c.speed * dt;
            c.pos.y += c.vel.y * c.speed * dt;
        }

        // ---- vertical: steering, buoyancy, soft walls, drag ----
        {
            float vz = c.vz + actions[STEER_Z] * resp * 3.0f * dt
                     + ocfg.kBuoy * (c.bodyBuoy * D - c.depth) / D * dt + rndZ;
            // Each wall's band is capped at half the depth: in a sea shallower
            // than 2·wallBand the two bands would overlap and the else-if
            // below would apply only the surface push. min() returns wallBand
            // itself whenever D >= 2·wallBand, so a normal sea is unchanged.
            const float wb = std::min(ocfg.wallBand, 0.5f * D);
            if (wb > 0.0f) {
                if (c.depth < wb)           vz += (1.0f - c.depth / wb) * 3.0f * dt;
                else if (c.depth > D - wb)  vz -= (1.0f - (D - c.depth) / wb) * 3.0f * dt;
            }
            vz -= vz * ocfg.vDrag * dt;
            vz = std::clamp(vz, -ocfg.pitchMax, ocfg.pitchMax);
            c.depth += vz * c.speed * dt;
            if (c.depth < 0.0f)  { c.depth = 0.0f; if (vz < 0.0f) vz = 0.0f; }
            else if (c.depth > D) { c.depth = D;   if (vz > 0.0f) vz = 0.0f; }
            c.vz = vz;
        }

        if (ocfg.walls) {
            // Glass walls: contact after swimming (clamped, the outward heading
            // reflected, speed kept), then the wall flow (sizeDrift-weighted as
            // below), then the same containment again, the depth faces' outward
            // pitch removed; lastMoveDir is the resolved heading.
            wallContact(c.pos, c.vel);
            if (wallFlowOn()) {
                const Flow U = wallFlowFast(c.pos, c.depth);
                const float w = ocfg.sizeDrift ? std::min(1.0f, 1.0f / c.bodySize) : 1.0f;
                c.pos.x += w * U.x * dt;
                c.pos.y += w * U.y * dt;
                c.depth += w * U.d * dt;
            }
            wallContact(c.pos, c.vel);
            if (c.depth <= 0.0f)   { c.depth = 0.0f; if (c.vz < 0.0f) c.vz = 0.0f; }
            else if (c.depth >= D) { c.depth = D;    if (c.vz > 0.0f) c.vz = 0.0f; }
            c.lastMoveDir = c.vel;
        } else {
            if (flowE1() || ocfg.sizeDrift) {
                // E1: carried by the 3-D flow where the fish now is; with sizeDrift
                // a big fish by less (drag / mass ∝ 1/L). Not swimming: no speed,
                // no move cost. Depth clamped after (the walls' vz response above
                // stays as it was).
                const Flow U = flowStep(c.pos, c.depth);
                const float w = ocfg.sizeDrift ? std::min(1.0f, 1.0f / c.bodySize) : 1.0f;
                c.pos.x = wrapCoord(c.pos.x + w * U.x * dt, (float)width);
                c.pos.y = wrapCoord(c.pos.y + w * U.y * dt, (float)height);
                c.depth = clampDepth(c.depth + w * U.d * dt);
            } else if (currentActive()) {
                Vec2 cur = currentExactAt(c.pos);
                c.pos.x += cur.x * dt;
                c.pos.y += cur.y * dt;
            }
            // The preview's two-step wrap (`if (x < 0) x += W; if (x >= W) x -= W;`)
            // is wrapCoord's own one-pass branch, so wrapCoord gives the same bits
            // for every x in [-W, 2·W), and wraps a multi-span excursion too.
            c.pos.x = wrapCoord(c.pos.x, (float)width);
            c.pos.y = wrapCoord(c.pos.y, (float)height);
        }
        hot_[i] = {c.pos, c.vel, c.depth};
#ifdef EVO_OCEAN_EYE
        if constexpr (Eye) {
            hot_[i].eyeSize = ocean::kEyeFishLen * c.bodySize;
            hot_[i].eyeCon  = ocean::eyeContrast(ocean::kEyeFishBright, c.depth);
        }
#endif

        c.updateBody();
        if (ocfg.walls) containBody(c);

        kernel::stepInternalState(c, actions, dt);
        kernel::stepMetabolism(c, cfg, dt);
        // Depth costs (0 by default): holding off neutral depth, and pressure.
        if (ocfg.cHold != 0.0f || ocfg.cPress != 0.0f) {
            if (ocfg.depthCostScaled) {
                // E1: dimensionless multiples of this fish's metabolism.
                const float H = std::abs(c.depth - c.bodyBuoy * D) / D;
                const float P = c.depth / D;
                const float M = cfg.metabolicRate * massFactor(c);
                c.foodReserves -= dt * M * (ocfg.cHold * H + ocfg.cPress * P);
            } else {
                // The preview's: energy/s per unit H / P.
                c.foodReserves -= dt * (ocfg.cHold * std::abs(c.depth - c.bodyBuoy * D) / D
                                        + ocfg.cPress * c.depth / D);
            }
        }

        if (actions[EMIT_SIGNAL0] > 0.0f) pending_[i] = {true, c.pos};
#ifdef EVO_OCEAN_PROF
        oprof.moveNs += std::chrono::duration<double, std::nano>(pclk::now() - p2).count();
#endif
    }

    void doInteraction(Fish& c1, Fish& c2, std::vector<Fish>& newborns, std::vector<std::uint32_t>& newbornParents) {
        switch (kernel::interactionVote(c1, c2)) {
        case kernel::Interaction::Share:
            kernel::shareReserves(c1, c2);
            break;
        case kernel::Interaction::Pair: {
            bool viaGrace = false, viaSoft = false;
            if (kernel::pairingAllowed(c1, c2, cfg,
                                       (int)creatures.size() + (int)newborns.size()) &&
                kernel::reproGatePasses(c1, c2, cfg, viaGrace, viaSoft)) {
                kernel::payForPairing(c1, c2, cfg);
                newborns.push_back(makeChildFish(c1, c2, cfg.genomeMinLength,
                                                 cfg.genomeMaxLength,
                                                 cfg.mutationMultiplier,
                                                 cfg.newbornEnergy,
                                                 cfg.weightMutationMode));
                if (appearanceOn()) {   // c1, c2 are elements of `creatures` (update's serial loop)
                    newbornParents.push_back((std::uint32_t)(&c1 - creatures.data()));
                    newbornParents.push_back((std::uint32_t)(&c2 - creatures.data()));
                }
                Fish& baby = newborns.back();
                if (cfg.toroidal) {
                    Vec2 m = { wrapCoord(c1.pos.x + 0.5f * wrapDx(c2.pos.x - c1.pos.x), (float)width),
                               wrapCoord(c1.pos.y + 0.5f * wrapDy(c2.pos.y - c1.pos.y), (float)height) };
                    baby.pos = m;
                    for (int bi = 0; bi < Fish::BODY_LEN; ++bi)
                        baby.body[bi] = { m.x - baby.vel.x * bi * 4.0f,
                                          m.y - baby.vel.y * bi * 4.0f };
                }
                if (ocfg.walls) containBody(baby);   // the midpoint is inside; its trail too
                kernel::inheritFromPair(baby, c1, c2, cfg);
                const float m = ocfg.buoyMutation;
                baby.bodyBuoy = std::clamp(0.5f * (c1.bodyBuoy + c2.bodyBuoy) + rng.range(-m, m),
                                           0.0f, 1.0f);
                recordPairing(c1, c2, viaGrace, viaSoft);
            }
            break;
        }
        case kernel::Interaction::Fight:
            if (ocfg.sizeFight)   // E1: strength ∝ L² (same two draws)
                kernel::fightOutcome(c1, c2, c1.bodySize * c1.bodySize, c2.bodySize * c2.bodySize);
            else
                kernel::fightOutcome(c1, c2);
            break;
        default: break;
        }
    }

    void writeColumnSensors(const Fish& c, Vec2 fwd, Vec2 rht, float sensors[], ocean::SenseMask need);
    int foodWithin(const Fish& c, float R);
    int foodWithinWrapped(const Fish& c, float R);
    FoodSeen* foodSeenList();
#ifdef EVO_OCEAN_EYE
    template <class Bin>
    void eyeScan(const Fish& c, int selfIdx, Vec2 fwd, Vec2 rht, Bin* eye);
#endif
    template <bool Eye, bool Labels = true, bool Sum = false>
    void computeSensors(const Fish& c, int selfIdx, float sensors[], ocean::SenseMask need);

    void updatePredators(float dt);
    void refillPredators();
};

// Out-of-class member definitions, by topic. They need the complete class above, so they are
// included here and nowhere else (each is #pragma once and includes nothing itself):
//   ocean_world_util.hpp   non-finite checks, removedDead, radiusError, wraps, depthStats, dist2
//   ocean_walls.hpp        wallAvoid, wallContact, containBody, wallPatchDraw
//   ocean_eye.hpp          the eye's sector / see / write helpers (EVO_OCEAN_EYE)
//   ocean_side_tracks.hpp  appearance and body-plan side tracks
//   ocean_sensing.hpp      computeSensors and the sensing pass
//   ocean_predators.hpp    scripted-predator stepping
// OceanFood / OceanPredator live in ocean_entities.hpp (included above the class); the flow state
// and food transport live in ocean_transport.hpp.
#include "ocean_world_util.hpp"
#include "ocean_walls.hpp"
#include "ocean_eye.hpp"
#include "ocean_side_tracks.hpp"
#include "ocean_sensing.hpp"
#include "ocean_predators.hpp"

#pragma once
// ----------------------------------------------------------------------------
// kernel — the per-creature steps that do not depend on the world's geometry,
// shared by every kind of world: the child's genome, the internal state and
// metabolism updates, the death test, the geometry-free sensors, and the
// pairwise interaction (vote, share, fight, and the insertion preconditions,
// gate and inheritance).
//
// Each function is code that used to sit inline in Creature or World, moved
// verbatim: the same expressions in the same order and the same rng draws in
// the same order, so the 2-D world computes bit for bit what it computed
// before the split. -ffp-contract=off is set for every target (CMakeLists.txt,
// wasm.cmake), so moving an expression into an inline function cannot change
// how it rounds. That is an argument; the proof is the byte-identity harness.
//
// What stays in a world: everything that touches position or heading —
// movement, currents, wrapping, the spatial queries and the sensors built on
// them, where a child is placed, and the predators — plus RANDOM_SENSOR, whose
// draw's place in the step is the world's to choose.
//
// Random draws: each function says whether it draws. The ones that do use the
// calling thread's `rng` (thread_local, random.hpp), so the order of calls IS
// the random stream; the interaction and life-cycle ones that draw run in a
// world's single-threaded phase only.
// ----------------------------------------------------------------------------
#include <algorithm>
#include <cmath>
#include <cstring>
#include "agent_core.hpp"
#include "body_model.hpp"
#include "config.hpp"
#include "genome.hpp"
#include "isolation.hpp"
#include "portable_math.hpp"
#include "random.hpp"
#include "sensors_actions.hpp"

// tanh of a whole-number count over a fixed divisor, as a table: entry k holds
// evomath::tanhf((float)k / D), the very expression the count sensors
// evaluate, so a lookup returns the same bits as the call. Counts outside the
// table fall back to the call.
template <int D, int K>
struct CountTanh {
    float t[2 * K + 1];
    CountTanh() {
        for (int k = -K; k <= K; ++k) t[k + K] = evomath::tanhf((float)k / (float)D);
    }
    float operator()(int k) const {
        return (k >= -K && k <= K) ? t[k + K] : evomath::tanhf((float)k / (float)D);
    }
};
inline const CountTanh<5, 256>  tanhCountOver5;
inline const CountTanh<10, 256> tanhCountOver10;
inline const CountTanh<15, 256> tanhCountOver15;

namespace kernel {

// ---- Life cycle -------------------------------------------------------------

// The per-birth mutation rate picked by one uniform draw u: a heavy-tailed
// lottery (3 % of births mutate at 0.5, 7 % at 0.05, 20 % at 0.01, the rest at
// 0.002). One definition for the prey (inheritGenome below) and the Stage C
// predators' buds (predator_brain.hpp). No draws.
inline float birthMutationRate(float u) {
    if (u < 0.03f) return 0.5f;
    if (u < 0.10f) return 0.05f;
    if (u < 0.30f) return 0.01f;
    return 0.002f;
}

// A child's genome: crossover of the two source records, then ONE rng.unit()
// that picks the mutation rate, then the mutation draws. Called before the
// world places the child, as makeChild always did. Draws (serial phase).
inline void inheritGenome(AgentCore& child, const AgentCore& p1, const AgentCore& p2,
                          int minLen, int maxLen, float mutMultiplier) {
    child.genome = crossover(p1.genome, p2.genome);

    const float rate = birthMutationRate(rng.unit());
    mutateGenome(child.genome, rate * mutMultiplier, minLen, maxLen);
}

// Internal state actions: the oscillator period and responsiveness follow the
// network's outputs; the oscillator phase advances. No draws (parallel phase).
inline void stepInternalState(AgentCore& c, const float actions[], float dt) {
    c.oscPeriod = std::clamp(c.oscPeriod + actions[SET_OSCILLATOR_PERIOD] * 5.0f * dt,
                             4.0f, 200.0f);
    c.responsiveness = std::clamp(
        c.responsiveness + actions[SET_RESPONSIVENESS] * 0.5f * dt,
        0.01f, 1.0f);

    c.oscPhase += dt * (6.28f / c.oscPeriod);
    if (c.oscPhase > 6.28f) c.oscPhase -= 6.28f;
}

// Age and metabolism. No draws (parallel phase).
inline void stepMetabolism(AgentCore& c, const SimConfig& cfg, float dt) {
    c.age += dt;
    // Metabolism: a fixed burn, an optional per-gene surcharge (longer
    // genomes must earn their length), plus an optional kinetic cost so
    // thrust isn't free — moveCost*speed^2 makes fast movement (e.g.
    // fighting a current) expensive and gives an interior optimal speed.
    // Body model: the FIXED burn scales with mass, so a big body pays
    // for its size every second. The gene-cost term is deliberately
    // untouched — that one prices the genome, not the body.
    c.foodReserves -= dt * (cfg.metabolicRate * massFactor(c)
                            + cfg.geneCost * (float)c.genome.size()
                            + cfg.moveCost * c.speed * c.speed);
    c.reproTimer -= dt;
    c.interactTimer -= dt;
}

// Why a creature dies this step, or 0 if it lives: 's' starved, 'a' aged out.
// Starvation is tested first, so a creature that is both counts as starved.
// (Predation, 'p', is decided by the world's predators.) No draws.
inline char deathCause(const AgentCore& c, const SimConfig& cfg) {
    if (c.foodReserves <= 0.0f) return 's';
    if (c.age > cfg.maxAge) return 'a';
    return 0;
}

// ---- Sensors ----------------------------------------------------------------

// The own-state sensors that need no position or heading. The sensor
// functions draw nothing (parallel phase).
inline void writeOwnStateSensors(const AgentCore& c, const SimConfig& cfg, float sensors[]) {
    sensors[OWN_SPEED] = c.speed / cfg.maxSpeed;
    sensors[AGE] = evomath::tanhf(c.age / 60.0f);
    sensors[FOOD_RESERVES] = evomath::tanhf((c.foodReserves - 25.0f) / 25.0f);
    sensors[OSCILLATOR] = c.getOscillator();
    sensors[RESPONSIVENESS] = c.responsiveness;
}

// The nearest neighbour's attributes. Returns the genetic similarity so the
// world can gate GENETIC_SIM_FWD on its own forward test.
inline float writeNearestSensors(const AgentCore& c, const AgentCore& nearest, float sensors[]) {
    sensors[NEAREST_NEIGHBOR_AGE] = evomath::tanhf((nearest.age - 50.0f) / 50.0f);
    sensors[NEAREST_NEIGHBOR_FOOD] = evomath::tanhf((nearest.foodReserves - 25.0f) / 25.0f);
    const float sim = genomeSimilarity(c.genome, nearest.genome);
    sensors[GENETIC_SIM_NEAREST] = sim;
    return sim;
}

// The same three sensors with no neighbour in range.
inline void clearNearestSensors(float sensors[]) {
    sensors[NEAREST_NEIGHBOR_AGE] = 0.0f;
    sensors[NEAREST_NEIGHBOR_FOOD] = 0.0f;
    sensors[GENETIC_SIM_NEAREST] = 0.0f;
}

// ---- Interaction ------------------------------------------------------------

// What two creatures in contact do, decided by summing both networks' votes.
// The values are the case labels doInteraction has always switched on.
enum class Interaction : int { Ignore = 0, Share = 1, Pair = 2, Fight = 3 };

// Non-const on purpose: feedForward overwrites each network's internal-neuron
// outputs, which the next step's sensing reads back. No draws.

inline Interaction interactionVote(AgentCore& c1, AgentCore& c2) {
    float s1[NUM_SENSES], s2[NUM_SENSES];
    std::memset(s1, 0, sizeof(s1));
    std::memset(s2, 0, sizeof(s2));

    s1[AGE] = evomath::tanhf((c1.age - 50.0f) / 50.0f);
    s1[NEAREST_NEIGHBOR_AGE] = evomath::tanhf((c2.age - 50.0f) / 50.0f);
    s1[FOOD_RESERVES] = evomath::tanhf((c1.foodReserves - 25.0f) / 25.0f);
    s1[NEAREST_NEIGHBOR_FOOD] = evomath::tanhf((c2.foodReserves - 25.0f) / 25.0f);
    s1[GENETIC_SIM_NEAREST] = genomeSimilarity(c1.genome, c2.genome);

    // c2's view is c1's with the roles swapped: the same expressions, and
    // genomeSimilarity is symmetric.
    s2[AGE] = s1[NEAREST_NEIGHBOR_AGE];
    s2[NEAREST_NEIGHBOR_AGE] = s1[AGE];
    s2[FOOD_RESERVES] = s1[NEAREST_NEIGHBOR_FOOD];
    s2[NEAREST_NEIGHBOR_FOOD] = s1[FOOD_RESERVES];
    s2[GENETIC_SIM_NEAREST] = s1[GENETIC_SIM_NEAREST];

    float a1[NUM_ACTIONS], a2[NUM_ACTIONS];
    feedForward(c1.nnet, s1, a1);
    feedForward(c2.nnet, s2, a2);

    float sShare = a1[INTERACT_SHARE] + a2[INTERACT_SHARE];
    float sRepro = a1[INTERACT_REPRODUCE] + a2[INTERACT_REPRODUCE];
    float sFight = a1[INTERACT_FIGHT] + a2[INTERACT_FIGHT];
    float sIgnore = a1[INTERACT_IGNORE] + a2[INTERACT_IGNORE];

    float maxScore = sIgnore;
    int choice = 0;
    if (sShare > maxScore) { maxScore = sShare; choice = 1; }
    if (sRepro > maxScore) { maxScore = sRepro; choice = 2; }
    if (sFight > maxScore) { maxScore = sFight; choice = 3; }
    return static_cast<Interaction>(choice);
}

// Share: pool both reserves and split them evenly. No draws.
inline void shareReserves(AgentCore& c1, AgentCore& c2) {
    float total = c1.foodReserves + c2.foodReserves;
    c1.foodReserves = total * 0.5f;
    c2.foodReserves = total * 0.5f;
}

// Fight: strength rises to a peak at age 30 and declines after; each side's
// strength is scaled by one rng.unit() (c1's first), and the winner takes 15
// from the loser. Draws: exactly two (serial phase).
inline void fightOutcome(AgentCore& c1, AgentCore& c2) {
    float str1 = (c1.age < 30.0f) ? c1.age / 30.0f : 1.0f - (c1.age - 30.0f) / 90.0f;
    float str2 = (c2.age < 30.0f) ? c2.age / 30.0f : 1.0f - (c2.age - 30.0f) / 90.0f;
    str1 *= rng.unit();
    str2 *= rng.unit();
    if (str1 > str2) {
        c1.foodReserves += 15.0f;
        c2.foodReserves -= 15.0f;
    } else {
        c2.foodReserves += 15.0f;
        c1.foodReserves -= 15.0f;
    }
}

// The same fight with each side's strength scaled (the Ocean world's size law
// passes bodySize²): scale1 / scale2 multiply after the age curve and before
// the draws, each only when it is not exactly 1.0f, so (c1, c2, 1, 1) is the
// two-argument fight bit for bit. The draws, their order, ties and the ±15 do
// not change. A separate overload, not default arguments: defaults changed the
// Classic wasm's bytes (45 bytes, same behaviour), this leaves them alone.
inline void fightOutcome(AgentCore& c1, AgentCore& c2, float scale1, float scale2) {
    float str1 = (c1.age < 30.0f) ? c1.age / 30.0f : 1.0f - (c1.age - 30.0f) / 90.0f;
    float str2 = (c2.age < 30.0f) ? c2.age / 30.0f : 1.0f - (c2.age - 30.0f) / 90.0f;
    if (scale1 != 1.0f) str1 *= scale1;
    if (scale2 != 1.0f) str2 *= scale2;
    str1 *= rng.unit();
    str2 *= rng.unit();
    if (str1 > str2) {
        c1.foodReserves += 15.0f;
        c2.foodReserves -= 15.0f;
    } else {
        c2.foodReserves += 15.0f;
        c1.foodReserves -= 15.0f;
    }
}

// Is this creature inside its founder grace window (cfg.reproGracePeriod)?
// A founder is a creature whose lineage starts at itself, which is exactly
// lineageId == id: both spawn sites (init and the --min-pop reseed floor)
// set it that way, ids are unique, and a child always inherits the maternal
// lineageId — so no creature field and no checkpoint column has to be added
// to ask this question. gracePeriod <= 0 is off; anything <= 5 is off in
// practice too, since pairingAllowed requires age > 5 before the gate runs.
//
// WorldCommon::reproGraced (so also World::reproGraced) forwards here, so the
// predicate can be tested directly rather than only through whole-run
// behaviour. No draws.
inline bool reproGraced(const AgentCore& c, float gracePeriod) {
    return gracePeriod > 0.0f && c.lineageId == c.id && c.age < gracePeriod;
}

// The cheap preconditions of an insertion, in the order the case-2 && chain
// has always evaluated them. None of them draws or writes, so evaluating these
// first and reproGatePasses after is the same short-circuit chain as before.
// popCount is what the --max-pop cap is compared against: in the 2-D world,
// creatures.size() + newborns queued so far — and creatures.size() still
// includes any that died earlier in this pass (they are erased after it). A
// world that passes a live count instead changes when the cap bites.
inline bool pairingAllowed(const AgentCore& c1, const AgentCore& c2,
                           const SimConfig& cfg, int popCount) {
    return c1.foodReserves > cfg.reproEnergy && c2.foodReserves > cfg.reproEnergy &&
           c1.reproTimer <= 0.0f && c2.reproTimer <= 0.0f &&
           c1.age > 5.0f && c2.age > 5.0f &&
           (cfg.maxPopulation <= 0 || popCount < cfg.maxPopulation);
}

// The reproduction gate, as one predicate. Called as the LAST conjunct of
// the case-2 precondition (see the comment at the call site for why the
// gate lives there at all), so "returned true" == "an insertion happens"
// and the out-flags can drive the attribution counters directly.
//
// The precedence below is load-bearing, because it defines when a draw
// happens:
//   1. gate off (T < 0)      accept. No fold, no draw — the default corpus.
//   2. either partner graced accept. No fold, no draw: grace is a bypass,
//                            not a widening, so it costs nothing and can
//                            never be overruled by an unlucky draw.
//   3. fold the pair         dsq = genomeDistanceSq (the expensive part,
//                            reached only when the gate is armed).
//   4. hard gate (W <= 0)    the EXACT v0.21 comparison, and NO draw. Every
//                            archived --repro-max-distance run has to stay
//                            byte-identical, so this expression may not
//                            acquire a sqrt, a division or a draw.
//   5. soft gate (W > 0)     sqrt, then EXACTLY ONE rng.unit(), taken
//                            UNCONDITIONALLY before the comparison. The
//                            draw count per gate evaluation must not depend
//                            on d — the same rule the body model's two
//                            draws follow — or native and wasm desync on
//                            the first pair that lands on the other side of
//                            a branch.
inline bool reproGatePasses(const AgentCore& c1, const AgentCore& c2, const SimConfig& cfg,
                            bool& viaGrace, bool& viaSoft) {
    viaGrace = false;
    viaSoft  = false;
    const float T = cfg.reproMaxDistance;
    if (T < 0.0f) return true;
    if (reproGraced(c1, cfg.reproGracePeriod) ||
        reproGraced(c2, cfg.reproGracePeriod)) {
        viaGrace = true;
        return true;
    }
    const float dsq = genomeDistanceSq(c1.genome, c2.genome);
    const float W = cfg.reproSoftWidth;
    if (W <= 0.0f) return dsq <= T * T;
    const float u = rng.unit();
    if (!softGateAccepts(std::sqrt(dsq), T, W, u)) return false;
    // Only a birth the hard gate would have REFUSED is a soft birth; a pair
    // already inside T needed no help from the ramp.
    viaSoft = (dsq > T * T);
    return true;
}

// What both source records pay for an insertion: energy, and the cooldown.
// No draws.
inline void payForPairing(AgentCore& c1, AgentCore& c2, const SimConfig& cfg) {
    c1.foodReserves -= 12.0f;
    c2.foodReserves -= 12.0f;
    c1.reproTimer = cfg.reproCooldown;
    c2.reproTimer = cfg.reproCooldown;
}

// What a newborn inherits beyond its genome: the maternal line, the
// generation depth, and (body model) its body parameters. Called after the
// world has built and placed the child. Draws: two under cfg.bodyModel, none
// otherwise (serial phase).
inline void inheritFromPair(AgentCore& nb, const AgentCore& c1, const AgentCore& c2,
                            const SimConfig& cfg) {
    nb.lineageId = c1.lineageId;   // inherit maternal line
    nb.generation = std::max(c1.generation, c2.generation) + 1;

    // --- Tier-1 body inheritance (v0.23.0) --------------------
    // THE RANDOM STREAM IS DEFINED HERE. Read before editing:
    //
    //  * Draws happen ONLY under cfg.bodyModel. With the flag off
    //    this block draws nothing, so the pre-0.23 rng sequence —
    //    and therefore every archived run — is untouched.
    //  * EXACTLY TWO rng.range draws per successful insertion, in
    //    this order: bodySize first, then bodyElong. rng.range is a
    //    single engine draw with no rejection, so the draw COUNT is
    //    independent of the values; that is what lets native and
    //    wasm stay bit-identical. Do not swap the order, do not add
    //    a Gaussian, do not add a resample-until-in-range loop —
    //    each of those breaks the parity contract.
    //  * Position in the sequence: AFTER the lineageId assignment,
    //    BEFORE logBirth (WorldCommon::recordPairing). Callers run it in
    //    the single-threaded phase, so it shares that thread's rng safely.
    //  * Blend is the plain parent mean plus a uniform jitter, then
    //    clamped, so a child can never leave [0.5, 2.0] no matter
    //    what the parents are.
    if (cfg.bodyModel) {
        nb.bodySize  = std::clamp(0.5f * (c1.bodySize + c2.bodySize)
                                  + rng.range(-cfg.bodyMutation, cfg.bodyMutation),
                                  BODY_PARAM_MIN, BODY_PARAM_MAX);
        nb.bodyElong = std::clamp(0.5f * (c1.bodyElong + c2.bodyElong)
                                  + rng.range(-cfg.bodyMutation, cfg.bodyMutation),
                                  BODY_PARAM_MIN, BODY_PARAM_MAX);
    }
}

} // namespace kernel

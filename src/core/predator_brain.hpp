#pragma once
// ----------------------------------------------------------------------------
// predator_brain — Stage C (v0.27.0, SimConfig::predatorBrain): the predator's
// network, its genome operations and the inputs that need no geometry. A
// world (world.hpp; the Ocean in a later change) does the sensing that needs
// positions and applies the two actions.
//
// The machinery is the prey's: the same Gene encoding, the same mutation
// operators (genome.hpp, given the predators' own stream), the same NeuralNet
// storage and the same flat, sink-grouped evaluation (activations: the scalar
// evomath::tanhf, bit-identical to the prey's tanhfArray; see feedForward).
// What differs is the I/O space: 21 inputs a hunter can use and 2 outputs.
// buildNet / feedForward below are siblings of buildNeuralNet / feedForward,
// sized for that space; the prey's tuned hot path is left untouched, and
// core_tests pins these two against a gene-by-gene reference evaluator.
//
// THE SENSOR LIST IS FROZEN. Genes decode `% NUM_PRED_SENSES`, so adding,
// removing or reordering an input changes what every existing genome means.
// Any such change must bump PRED_SENSOR_SET; checkpoints carry it, and a load
// with a different set is refused.
//
// Random draws: everything here that draws takes the stream explicitly, and the
// worlds pass WorldCommon::predRng_ — never the global `rng` — so the prey's
// random stream holds only the draws it held in 0.26.0 (plus the one seed draw
// at the end of World::init when the brain is on).
// ----------------------------------------------------------------------------
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include "config.hpp"
#include "genome.hpp"
#include "kernel.hpp"
#include "portable_math.hpp"
#include "predator.hpp"
#include "random.hpp"

// Version of the input/output list below. Bump on ANY change to either enum.
inline constexpr int PRED_SENSOR_SET = 1;

enum PredSense : std::uint8_t {
    // nearest living prey within predatorPerception (R), in the predator's frame
    PS_PREY_FWD,          // +1 = dead ahead, -1 = directly behind (0 when none)
    PS_PREY_LR,           // +1 = to the right (the +90 deg side TURN > 0 turns toward)
    PS_PREY_PROX,         // 1 - d/R: 0 at the edge / none, -> 1 on contact
    PS_PREY_HEAD_FWD,     // that prey's heading . own forward (fleeing ahead -> +1)
    PS_PREY_HEAD_LR,      // that prey's heading . own right
    // every living prey within R
    PS_PREY_COUNT,        // tanh(n / 10)
    PS_PREY_CENTROID_FWD, // tanh(mean offset . forward / R)
    PS_PREY_CENTROID_LR,  // tanh(mean offset . right / R)
    // nearest other predator within R (positions at the start of the phase)
    PS_RIVAL_FWD,
    PS_RIVAL_LR,
    PS_RIVAL_PROX,        // 1 - d/R
    // own state
    PS_ENERGY,            // tanh((E - T/2) / (T/2)), T = repro energy x buddingFactor; 0 without economy
    PS_DIGEST,            // digestTimer / cooldown while digesting, else 0
    PS_SPEED,             // speed / top speed
    PS_AGE,               // tanh(age / 60) (age only runs with the economy)
    // the world
    PS_SIGNAL,            // the prey's pheromone here, and its gradient (eavesdropping)
    PS_SIGNAL_FWD,
    PS_SIGNAL_LR,
    PS_CURRENT_FWD,       // tanh(flow . forward / 100); 0 in still water
    PS_CURRENT_LR,
    PS_RANDOM,            // U(-1, 1) from the predators' stream
    NUM_PRED_SENSES
};

enum PredAction : std::uint8_t {
    PA_TURN,              // heading change: TURN x predatorTurnRate x dt (rad)
    PA_THRUST,            // speed += THRUST x 50 x dt, within [predatorMinSpeed, top]
    NUM_PRED_ACTIONS
};

inline constexpr const char* kPredSenseNames[] = {
    "PREY_FWD", "PREY_LR", "PREY_PROX", "PREY_HEAD_FWD", "PREY_HEAD_LR",
    "PREY_COUNT", "PREY_CENTROID_FWD", "PREY_CENTROID_LR",
    "RIVAL_FWD", "RIVAL_LR", "RIVAL_PROX",
    "ENERGY", "DIGEST", "SPEED", "AGE",
    "SIGNAL", "SIGNAL_FWD", "SIGNAL_LR", "CURRENT_FWD", "CURRENT_LR", "RANDOM",
};
static_assert(sizeof(kPredSenseNames) / sizeof(kPredSenseNames[0]) == NUM_PRED_SENSES,
              "kPredSenseNames is out of sync with PredSense");
inline constexpr const char* kPredActionNames[] = {"TURN", "THRUST"};
static_assert(sizeof(kPredActionNames) / sizeof(kPredActionNames[0]) == NUM_PRED_ACTIONS,
              "kPredActionNames is out of sync with PredAction");

namespace predbrain {

// The prey's SPEED_ADJUST constant (World::update: speed += a * 50 * dt).
inline constexpr float kThrustAccel = 50.0f;

static_assert(NUM_PRED_SENSES + MAX_INTERNAL_NEURONS <= (1 << NeuralNet::FlatConn::SRC_BITS),
              "predator source index space no longer fits in FlatConn::srcSink");
static_assert(NUM_PRED_ACTIONS + MAX_INTERNAL_NEURONS <= (1 << (16 - NeuralNet::FlatConn::SRC_BITS)),
              "predator sink index space no longer fits in FlatConn::srcSink");

// buildNeuralNet's algorithm with the predator's I/O sizes: genes remapped by
// % NUM_PRED_SENSES / % NUM_PRED_ACTIONS / % MAX_INTERNAL_NEURONS, then a
// stable counting sort by sink, so every accumulator sums in genome order.
inline void buildNet(const Genome& genome, NeuralNet& nnet) {
    nnet.neurons.clear();
    nnet.neurons.resize(MAX_INTERNAL_NEURONS);
    constexpr int NUM_SINKS = NUM_PRED_ACTIONS + MAX_INTERNAL_NEURONS;
    auto sourceIndex = [](const Gene& g) {
        return (g.sourceType == SOURCE_SENSOR) ? (int)(g.sourceNum % NUM_PRED_SENSES)
                                               : NUM_PRED_SENSES + (int)(g.sourceNum % MAX_INTERNAL_NEURONS);
    };
    auto sinkIndex = [](const Gene& g) {
        return (g.sinkType == SINK_ACTION) ? (int)(g.sinkNum % NUM_PRED_ACTIONS)
                                           : NUM_PRED_ACTIONS + (int)(g.sinkNum % MAX_INTERNAL_NEURONS);
    };
    for (const Gene& gene : genome) {
        const int sink = sinkIndex(gene);
        if (sink >= NUM_PRED_ACTIONS) nnet.neurons[sink - NUM_PRED_ACTIONS].driven = true;
    }
    int counts[NUM_SINKS] = {};
    for (const Gene& gene : genome) ++counts[sinkIndex(gene)];
    int offsets[NUM_SINKS] = {};
    for (int i = 1; i < NUM_SINKS; ++i) offsets[i] = offsets[i - 1] + counts[i - 1];
    nnet.flat.assign(genome.size(), NeuralNet::FlatConn{});
    for (const Gene& gene : genome) {
        const int sink = sinkIndex(gene);
        nnet.flat[offsets[sink]++] = {
            (std::uint16_t)(sourceIndex(gene) | (sink << NeuralNet::FlatConn::SRC_BITS)),
            gene.weight
        };
    }
}

// feedForward's algorithm with the predator's I/O sizes (recurrent hidden
// neurons, tanh activations; an undriven neuron keeps its output).
//
// The activations use the SCALAR evomath::tanhf, not tanhfArray. The two are
// bit-identical (tanhfArray's contract), but extra inlined copies of
// tanhfArray made GCC stop inlining detail::tanhfSelect in the default
// builds, which de-vectorised the PREY's tanh loop and ran the whole sim ~1.9x
// slower with the brain off (review of PR #60, P1-1). 14 scalar calls per
// predator-step cost nothing measurable; the prey's hot path keeps main's code.
inline void feedForward(NeuralNet& nnet, const float sensors[], float actions[], bool fastTanh) {
    float vals[NUM_PRED_SENSES + MAX_INTERNAL_NEURONS];
    std::memcpy(vals, sensors, NUM_PRED_SENSES * sizeof(float));
    for (int i = 0; i < MAX_INTERNAL_NEURONS; ++i) vals[NUM_PRED_SENSES + i] = nnet.neurons[i].output;
    float accum[NUM_PRED_ACTIONS + MAX_INTERNAL_NEURONS] = {};
    for (const auto& conn : nnet.flat) accum[conn.sink()] += vals[conn.src()] * conn.w();
    if (fastTanh) {
        for (int i = 0; i < NUM_PRED_ACTIONS; ++i) actions[i] = fastTanhApprox(accum[i]);
        for (int i = 0; i < MAX_INTERNAL_NEURONS; ++i)
            if (nnet.neurons[i].driven) nnet.neurons[i].output = fastTanhApprox(accum[NUM_PRED_ACTIONS + i]);
    } else {
        for (int i = 0; i < NUM_PRED_ACTIONS; ++i) actions[i] = evomath::tanhf(accum[i]);
        for (int i = 0; i < MAX_INTERNAL_NEURONS; ++i)
            if (nnet.neurons[i].driven) nnet.neurons[i].output = evomath::tanhf(accum[NUM_PRED_ACTIONS + i]);
    }
}

// The predator's speed ceiling. The max() keeps lo <= hi for the THRUST clamp
// (std::clamp with lo > hi is undefined), as World::update does for the prey.
inline float topSpeed(const Predator& p, const SimConfig& cfg) {
    return std::max(cfg.predatorMinSpeed, cfg.predatorSpeed * p.speedFactor);
}

// The two "pursuit primer" genes (cfg.predatorPrimer, opt-in): steer toward the
// nearest prey, speed up as it gets close. Written over a founder's first two
// genes, so a primed founder draws exactly what an unprimed one does.
inline Gene primerGene(int sensor, int action, float weight) {
    Gene g{};
    g.sourceType = SOURCE_SENSOR;
    g.sourceNum  = (std::uint16_t)sensor;
    g.sinkType   = SINK_ACTION;
    g.sinkNum    = (std::uint16_t)action;
    g.weight     = (std::int16_t)(weight * 8192.0f);
    return g;
}

// A founder's genome (initial spawn, floor refill, transplant "random"): a
// random genome of the prey's initial length range, from stream r.
inline Genome founderGenome(const SimConfig& cfg, RandomGen& r) {
    Genome g = makeRandomGenome(cfg.genomeInitMin, cfg.genomeInitMax, r);
    if (cfg.predatorPrimer) {
        if (g.size() < 2) g.resize(2, Gene{});
        g[0] = primerGene(PS_PREY_LR, PA_TURN, 3.0f);
        g[1] = primerGene(PS_PREY_PROX, PA_THRUST, 2.0f);
    }
    return g;
}

// A bud's genome: its parent's, then ONE r.unit() for the rate (the prey's
// lottery, kernel::birthMutationRate) times predatorMutation, then the prey's
// mutation operators — all from stream r (the world passes predRng_).
inline void inheritGenome(Predator& child, const Predator& parent, const SimConfig& cfg, RandomGen& r) {
    child.genome = parent.genome;
    const float rate = kernel::birthMutationRate(r.unit());
    mutateGenome(child.genome, rate * cfg.predatorMutation, cfg.genomeMinLength, cfg.genomeMaxLength, r);
}

// The own-state inputs (no geometry, no draws).
inline void writeOwnSensors(const Predator& p, const SimConfig& cfg, float top, float s[]) {
    if (cfg.predatorEconomy) {
        const float half = 0.5f * cfg.predatorReproEnergy * p.buddingFactor;
        s[PS_ENERGY] = (half > 0.0f) ? evomath::tanhf((p.energy - half) / half) : 0.0f;
    } else {
        s[PS_ENERGY] = 0.0f;
    }
    s[PS_DIGEST] = (p.digestTimer > 0.0f && cfg.predatorCooldown > 0.0f)
                       ? std::min(1.0f, p.digestTimer / cfg.predatorCooldown) : 0.0f;
    s[PS_SPEED]  = (top > 0.0f) ? p.speed / top : 0.0f;
    s[PS_AGE]    = evomath::tanhf(p.age / 60.0f);
}

// Which of a predator's inputs its network reads (any connection from it).
inline void usedSensors(const NeuralNet& nnet, bool used[NUM_PRED_SENSES]) {
    for (int s = 0; s < NUM_PRED_SENSES; ++s) used[s] = false;
    for (const auto& fc : nnet.flat) {
        const int src = fc.src();
        if (src < NUM_PRED_SENSES) used[src] = true;
    }
}

}  // namespace predbrain

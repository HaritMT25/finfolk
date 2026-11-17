#pragma once
#include <cstdint>
#include <cstring>
#include <vector>
#include <cmath>
#include <algorithm>
#include <bit>
#include <string_view>
#include "sensors_actions.hpp"
#include "portable_math.hpp"
#include "random.hpp"

enum class WeightMutationMode : uint8_t {
    Legacy = 0,
    Saturating = 1,
    Invalid = 255
};

inline constexpr const char* weightMutationModeName(WeightMutationMode mode) {
    switch (mode) {
    case WeightMutationMode::Legacy: return "legacy";
    case WeightMutationMode::Saturating: return "saturating";
    default: return "invalid";
    }
}

inline bool parseWeightMutationMode(std::string_view text,
                                    WeightMutationMode& mode) {
    if (text == "legacy") {
        mode = WeightMutationMode::Legacy;
        return true;
    }
    if (text == "saturating") {
        mode = WeightMutationMode::Saturating;
        return true;
    }
    return false;
}

inline int16_t saturatingWeightAdd(int16_t weight, int32_t delta) {
    const int32_t sum = static_cast<int32_t>(weight) + delta;
    return static_cast<int16_t>(
        std::clamp(sum, int32_t{-32768}, int32_t{32767}));
}

// Max number of internal (hidden) neurons per creature
constexpr int MAX_INTERNAL_NEURONS = 12;

// Genome length bounds — evolution can grow/shrink genomes within this range
constexpr int GENOME_MIN_LENGTH = 16;
constexpr int GENOME_MAX_LENGTH = 80;
constexpr int GENOME_INITIAL_MIN = 24;
constexpr int GENOME_INITIAL_MAX = 48;

// --- Gene: one connection in the neural net ---
// Adapted from biosim4. Each gene encodes: source -> sink with a weight.
// Source can be a sensor or internal neuron.
// Sink can be an action or internal neuron.
constexpr uint8_t SOURCE_SENSOR = 1;
constexpr uint8_t SOURCE_NEURON = 0;
constexpr uint8_t SINK_ACTION = 1;
constexpr uint8_t SINK_NEURON = 0;

struct Gene {
    uint16_t sourceType : 1;  // SENSOR or internal NEURON
    uint16_t sourceNum  : 7;
    uint16_t sinkType   : 1;  // ACTION or internal NEURON
    uint16_t sinkNum    : 7;
    int16_t  weight;

    float weightAsFloat() const { return weight / 8192.0f; }

    // From a given stream: the prey use the global `rng` (the overload
    // below), the predator brains their own stream (predator_brain.hpp). The
    // same five draws in the same order either way.
    static Gene makeRandom(RandomGen& r) {
        Gene g;
        g.sourceType = r.uint(1);
        g.sourceNum  = r.uint(127);
        g.sinkType   = r.uint(1);
        g.sinkNum    = r.uint(127);
        g.weight     = static_cast<int16_t>(r.uint(0xFFFF) - 0x8000);
        return g;
    }
    static Gene makeRandom() { return makeRandom(rng); }
};

using Genome = std::vector<Gene>;

// --- NeuralNet: derived from genome ---
// Free-topology: no fixed layers, any source can connect to any sink.
struct NeuralNet {
    struct Neuron {
        float output = 0.5f;
        bool driven = false;  // undriven neurons have fixed output
    };

    std::vector<Neuron> neurons;

    // The wired topology, in execution order. This is the ONLY per-connection
    // storage: an earlier version kept a genome-ordered std::vector<Gene>
    // alongside it for the inspector and wiring log, and that duplicate array
    // measurably slowed large populations down by competing for cache with the
    // neighbour scan — it cost more than the branch removal gained. Anything
    // that wants the topology decodes an entry with asGene() instead, which is
    // exact (the mapping below is invertible).
    //
    // Two flat index spaces remove the per-connection type branches that used
    // to dominate the inner loop (they are data-dependent and unpredictable,
    // and the predictor is thrashed further by interleaving hundreds of
    // creatures per step):
    //   src  : [0, NUM_SENSES)            = sensor inputs
    //          [NUM_SENSES, +MAX_INTERNAL_NEURONS) = internal neuron outputs
    //   sink : [0, NUM_ACTIONS)           = action accumulators
    //          [NUM_ACTIONS, +MAX_INTERNAL_NEURONS) = neuron accumulators
    //
    // Entries are grouped by sink with a STABLE counting sort, so every
    // accumulator still sums its contributions in genome order and the result
    // is bit-identical to the pre-flattening implementation. (That guarantee
    // holds only without FMA contraction — see -ffp-contract=off in
    // CMakeLists.txt — because contraction fuses the multiply-add differently
    // in the two loop shapes. core_tests asserts the equivalence directly.)
    //
    // Kept at 4 bytes/entry, matching Gene, because this loop is the hot one
    // and the sim is bandwidth-sensitive at large populations: an earlier
    // 8-byte layout (two uint16 + float) removed the same branches but read
    // twice the memory, and measured NET SLOWER end to end despite feedForward
    // itself getting faster. src needs 6 bits (< 53 values) and sink 5 bits
    // (< 24), so both pack into one uint16 with room to spare.
    struct FlatConn {
        uint16_t srcSink;   // src in bits 0-5, sink in bits 6-10
        int16_t  weight;    // same fixed-point encoding as Gene::weight

#ifdef EVO_OCEAN_EYE
        // The Ocean eye build: 64 sensors + 12 hidden = 76 sources need 7
        // bits (sink keeps 9: 13 + 12 = 25 sinks). Packing only — genes still
        // decode with % NUM_SENSES, and FlatConn stays 4 bytes.
        static constexpr int SRC_BITS = 7;
#else
        static constexpr int SRC_BITS = 6;
#endif
        static constexpr uint16_t SRC_MASK = (1u << SRC_BITS) - 1u;

        int   src()  const { return srcSink & SRC_MASK; }
        int   sink() const { return srcSink >> SRC_BITS; }
        // Division by 8192 is exact (power of two), so this is the identical
        // float Gene::weightAsFloat() produces — bit-exactness is preserved.
        float w()    const { return weight / 8192.0f; }
    };
    static_assert(sizeof(FlatConn) == 4, "flat connection must stay 4 bytes");
    std::vector<FlatConn> flat;

    // Gene-type bit masks: bit i of srcTypeBits / sinkTypeBits is gene i's
    // sourceType / sinkType, for genes 0..127 (two 64-bit words each), written
    // by buildNeuralNet from the genome in GENOME order (not flat's). They let
    // genomeSimilarityMasked count the positional type matches with a popcount
    // over the net's own bytes instead of a loop over both genomes' heap
    // buffers: the same integer count, so the same float. Derived state, like
    // the rest of the net: rebuilt wherever the net is (birth, checkpoint load),
    // never serialized. Genes past 127 are not covered (no configurable genome
    // is that long today); the masked compare falls back to the loop.
    uint64_t srcTypeBits[2]  = {0, 0};
    uint64_t sinkTypeBits[2] = {0, 0};
};

// Decode a wired connection back into Gene form (post-remapping, i.e. the
// indices the net actually uses). For code that inspects topology rather than
// running it: the wiring log, the live inspector overlay, tests.
inline Gene asGene(const NeuralNet::FlatConn& fc) {
    const int src = fc.src(), sink = fc.sink();
    Gene g;
    g.sourceType = (src < NUM_SENSES) ? SOURCE_SENSOR : SOURCE_NEURON;
    g.sourceNum  = (uint16_t)((src < NUM_SENSES) ? src : src - NUM_SENSES);
    g.sinkType   = (sink < NUM_ACTIONS) ? SINK_ACTION : SINK_NEURON;
    g.sinkNum    = (uint16_t)((sink < NUM_ACTIONS) ? sink : sink - NUM_ACTIONS);
    g.weight     = fc.weight;
    return g;
}

// --- Genome operations ---

// The genome operations take the stream they draw from; the overloads without
// one use the global `rng` (the prey's), with the same draws in the same order.
inline Genome makeRandomGenome(int initMin, int initMax, RandomGen& r) {
    int length = r.intRange(initMin, initMax);
    Genome genome;
    genome.reserve(length);
    for (int i = 0; i < length; ++i) {
        genome.push_back(Gene::makeRandom(r));
    }
    return genome;
}
inline Genome makeRandomGenome(int initMin = GENOME_INITIAL_MIN,
                               int initMax = GENOME_INITIAL_MAX) {
    return makeRandomGenome(initMin, initMax, rng);
}

// Build neural net wiring from genome
// Adapted from biosim4's createWiringFromGenome
inline void buildNeuralNet(const Genome& genome, NeuralNet& nnet) {
    nnet.neurons.clear();
    nnet.neurons.resize(MAX_INTERNAL_NEURONS);

    static_assert(NUM_SENSES + MAX_INTERNAL_NEURONS <= (1 << NeuralNet::FlatConn::SRC_BITS),
                  "source index space no longer fits in FlatConn::srcSink");
    static_assert(NUM_ACTIONS + MAX_INTERNAL_NEURONS
                      <= (1 << (16 - NeuralNet::FlatConn::SRC_BITS)),
                  "sink index space no longer fits in FlatConn::srcSink");
    constexpr int NUM_SINKS = NUM_ACTIONS + MAX_INTERNAL_NEURONS;

    // Remap each gene's source/sink to a valid index and flatten it into the
    // two execution index spaces (see NeuralNet::FlatConn).
    auto sourceIndex = [](const Gene& g) {
        return (g.sourceType == SOURCE_SENSOR) ? (int)(g.sourceNum % NUM_SENSES)
                                               : NUM_SENSES + (int)(g.sourceNum % MAX_INTERNAL_NEURONS);
    };
    auto sinkIndex = [](const Gene& g) {
        return (g.sinkType == SINK_ACTION) ? (int)(g.sinkNum % NUM_ACTIONS)
                                           : NUM_ACTIONS + (int)(g.sinkNum % MAX_INTERNAL_NEURONS);
    };

    // Mark neurons that receive input as "driven"
    for (const Gene& gene : genome) {
        const int sink = sinkIndex(gene);
        if (sink >= NUM_ACTIONS) nnet.neurons[sink - NUM_ACTIONS].driven = true;
    }

    // The gene-type masks (see NeuralNet): genome order, genes 0..127.
    nnet.srcTypeBits[0] = nnet.srcTypeBits[1] = 0;
    nnet.sinkTypeBits[0] = nnet.sinkTypeBits[1] = 0;
    for (size_t i = 0; i < genome.size() && i < 128; ++i) {
        const uint64_t bit = 1ull << (i & 63);
        if (genome[i].sourceType) nnet.srcTypeBits[i >> 6]  |= bit;
        if (genome[i].sinkType)   nnet.sinkTypeBits[i >> 6] |= bit;
    }

    // Stable counting sort by sink slot. Stability is what preserves
    // bit-exactness: within one accumulator the contributions keep their genome
    // order, so the float sum rounds exactly as it did before flattening.
    int counts[NUM_SINKS] = {};
    for (const Gene& gene : genome) ++counts[sinkIndex(gene)];

    int offsets[NUM_SINKS] = {};
    for (int i = 1; i < NUM_SINKS; ++i) offsets[i] = offsets[i - 1] + counts[i - 1];

    nnet.flat.assign(genome.size(), NeuralNet::FlatConn{});
    for (const Gene& gene : genome) {
        const int sink = sinkIndex(gene);
        nnet.flat[offsets[sink]++] = {
            (uint16_t)(sourceIndex(gene) | (sink << NeuralNet::FlatConn::SRC_BITS)),
            gene.weight
        };
    }
}

// Rational (Pade 7,6) approximation to tanh, used only when SimConfig.fastTanh
// is on. std::tanh is over half of feedForward's cost, because every creature
// makes MAX_INTERNAL_NEURONS + NUM_ACTIONS calls per step no matter how small
// its genome, so this is the largest remaining win in the neural path.
//
// Worst-case |error| is 1.1e-4 over the whole real line — the error is
// dominated by the saturation clamp, not the polynomial. The clamp sits at
// 4.95 for a specific reason: the rational form crosses 1.0 at x = 4.9715 and
// diverges after, so clamping any later would let the function return MORE
// than 1.0 and then drop back — breaking both the |tanh| <= 1 range invariant
// and monotonicity. Clamping just below the crossing costs |1 - tanh(4.95)| =
// 1.1e-4 and keeps the function non-decreasing everywhere, so it can never
// invert a comparison the exact tanh would have made. (The obvious cheaper
// Pade (3,2) form is 200x less accurate — worst error 2.4e-2 — far too coarse
// to trust in a chaotic system. core_tests pins all of this.)
//
// NOT bit-compatible with std::tanh, so runs made with it are a separate
// numerical lineage — see the fastTanh notes in config.hpp.
inline float fastTanhApprox(float x) {
    if (x < -4.95f) return -1.0f;
    if (x >  4.95f) return  1.0f;
    const float t = x * x;
    return x * (135135.0f + t * (17325.0f + t * (378.0f + t)))
             / (135135.0f + t * (62370.0f + t * (3150.0f + t * 28.0f)));
}

// Feed sensor values through the neural net, return action levels.
//
// Operates on nnet.flat (see NeuralNet): one branch-free accumulate loop over a
// sink-grouped connection list, then the activations. Bit-identical to the
// original per-connection-branching implementation — core_tests asserts this
// against a reference copy — but ~1.4x faster, because the two unpredictable
// branches per connection are gone.
inline void feedForward(NeuralNet& nnet, const float sensors[], float actions[],
                        bool fastTanh = false) {
    // Sources live in one flat array: sensors, then this creature's neuron
    // outputs carried over from the previous step (the recurrent state).
    float vals[NUM_SENSES + MAX_INTERNAL_NEURONS];
    std::memcpy(vals, sensors, NUM_SENSES * sizeof(float));
    for (int i = 0; i < MAX_INTERNAL_NEURONS; ++i) {
        vals[NUM_SENSES + i] = nnet.neurons[i].output;
    }

    // Accumulators for both sink kinds; stack-allocated, so it stays private to
    // each OpenMP thread with no per-call heap traffic.
    float accum[NUM_ACTIONS + MAX_INTERNAL_NEURONS] = {};
    for (const auto& conn : nnet.flat) {
        accum[conn.sink()] += vals[conn.src()] * conn.w();
    }

    if (fastTanh) {
        for (int i = 0; i < NUM_ACTIONS; ++i) actions[i] = fastTanhApprox(accum[i]);
        for (int i = 0; i < MAX_INTERNAL_NEURONS; ++i) {
            if (nnet.neurons[i].driven) {
                nnet.neurons[i].output = fastTanhApprox(accum[NUM_ACTIONS + i]);
            }
        }
    } else {
        // evomath::tanhf's bits, as two branch-free batches the compiler
        // vectorises (portable_math.hpp: tanhfArray). An undriven neuron's
        // accumulator is 0 and its value is dropped: it keeps its fixed output.
        evomath::tanhfArray(accum, actions, NUM_ACTIONS);
        float hidden[MAX_INTERNAL_NEURONS];
        evomath::tanhfArray(accum + NUM_ACTIONS, hidden, MAX_INTERNAL_NEURONS);
        for (int i = 0; i < MAX_INTERNAL_NEURONS; ++i) {
            NeuralNet::Neuron& n = nnet.neurons[i];
            n.output = n.driven ? hidden[i] : n.output;
        }
    }
}

// --- Reproduction ---

inline Genome crossover(const Genome& parent1, const Genome& parent2) {
    // Pick genome length from one parent randomly
    size_t len = rng.uint(1) ? parent1.size() : parent2.size();
    Genome child;
    child.reserve(len);

    for (size_t i = 0; i < len; ++i) {
        // For each gene slot, pick from either parent
        if (rng.uint(1) == 0 && i < parent1.size()) {
            child.push_back(parent1[i]);
        } else if (i < parent2.size()) {
            child.push_back(parent2[i]);
        } else if (i < parent1.size()) {
            child.push_back(parent1[i]);
        } else {
            child.push_back(Gene::makeRandom());
        }
    }
    return child;
}

inline void mutateGenome(Genome& genome, float rate, int minLen, int maxLen,
                         RandomGen& r,
                         WeightMutationMode mode = WeightMutationMode::Legacy) {
    // Preserve the legacy gates, payloads and random-stream ordering.
    for (auto& gene : genome) {
        if (r.unit() < rate) {
            if (mode == WeightMutationMode::Saturating) {
                const int32_t delta = r.intRange(-1000, 1000);
                gene.weight = saturatingWeightAdd(gene.weight, delta);
            } else {
                gene.weight += static_cast<int16_t>(r.intRange(-1000, 1000));
            }
        }
        if (r.unit() < rate * 0.5f) {
            gene = Gene::makeRandom(r);
        }
    }

    if (r.unit() < rate * 2.0f && (int)genome.size() < maxLen) {
        int pos = r.intRange(0, (int)genome.size());
        genome.insert(genome.begin() + pos, Gene::makeRandom(r));
    }

    if (r.unit() < rate * 2.0f && (int)genome.size() > minLen) {
        int pos = r.intRange(0, (int)genome.size() - 1);
        genome.erase(genome.begin() + pos);
    }

    if (r.unit() < rate * 0.5f && (int)genome.size() < maxLen) {
        int src = r.intRange(0, (int)genome.size() - 1);
        Gene dup = genome[src];
        if (mode == WeightMutationMode::Saturating) {
            const int32_t delta = r.intRange(-500, 500);
            dup.weight = saturatingWeightAdd(dup.weight, delta);
        } else {
            dup.weight += static_cast<int16_t>(r.intRange(-500, 500));
        }
        genome.push_back(dup);
    }
}

inline void mutateGenome(Genome& genome, float rate = 0.01f,
                         int minLen = GENOME_MIN_LENGTH,
                         int maxLen = GENOME_MAX_LENGTH,
                         WeightMutationMode mode = WeightMutationMode::Legacy) {
    mutateGenome(genome, rate, minLen, maxLen, rng, mode);
}

inline float genomeSimilarity(const Genome& g1, const Genome& g2) {
    size_t minLen = std::min(g1.size(), g2.size());
    if (minLen == 0) return 0.0f;

    // & rather than &&: both fields are compared every time, so the count has
    // no data-dependent branch. With &&, the branch on the first comparison was
    // close to a coin flip per gene for the predictor, and this runs for every
    // creature's nearest neighbour on every step.
    int matches = 0;
    for (size_t i = 0; i < minLen; ++i) {
        matches += (g1[i].sourceType == g2[i].sourceType) &
                   (g1[i].sinkType == g2[i].sinkType);
    }
    return static_cast<float>(matches) / static_cast<float>(minLen);
}

// genomeSimilarity, from the nets' gene-type masks (NeuralNet::srcTypeBits /
// sinkTypeBits, built by buildNeuralNet from these same genomes): a gene slot
// matches when both type bits agree, ~(a ^ b) is set exactly there, and the
// popcount over the first minLen slots is genomeSimilarity's `matches`, so the
// quotient is its float bit for bit. Genomes longer than the masks cover take
// the loop. For the hot per-step compare (the nearest neighbour); the nets
// must be the ones built from g1 and g2.
inline float genomeSimilarityMasked(const Genome& g1, const NeuralNet& n1,
                                    const Genome& g2, const NeuralNet& n2) {
    const size_t minLen = std::min(g1.size(), g2.size());
    if (minLen == 0) return 0.0f;
    if (minLen > 128) return genomeSimilarity(g1, g2);
    const uint64_t m0 = ~(n1.srcTypeBits[0] ^ n2.srcTypeBits[0]) & ~(n1.sinkTypeBits[0] ^ n2.sinkTypeBits[0]);
    const uint64_t m1 = ~(n1.srcTypeBits[1] ^ n2.srcTypeBits[1]) & ~(n1.sinkTypeBits[1] ^ n2.sinkTypeBits[1]);
    const uint64_t lo = (minLen >= 64) ? ~0ull : ((1ull << minLen) - 1ull);
    const uint64_t hi = (minLen <= 64) ? 0ull
                      : (minLen >= 128) ? ~0ull : ((1ull << (minLen - 64)) - 1ull);
    const int matches = std::popcount(m0 & lo) + std::popcount(m1 & hi);
    return static_cast<float>(matches) / static_cast<float>(minLen);
}

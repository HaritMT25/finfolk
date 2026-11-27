#pragma once
#include <cmath>
#include <string>
#include "config.hpp"
#include "genome.hpp"

struct BrainConversion {
    std::string sourceSha256;
    unsigned long long sourceFrame = 0;
    WeightMutationMode sourceWeightMutationMode =
        WeightMutationMode::Legacy;
};

inline bool validSourceSha256(const std::string& text) {
    if (text.size() != 64) return false;
    for (char c : text)
        if (!((c >= '0' && c <= '9')
              || (c >= 'a' && c <= 'f'))) return false;
    return true;
}

inline std::string convertedNumericalLineage(
    const BrainConversion& conversion, const SimConfig& target
) {
    return std::string("genome-v2.log1024.t1.h12.b")
        + (target.biasGenes ? "1:" : "0:")
        + conversion.sourceSha256;
}

template<int S, int A>
inline bool convertLegacyBrain(
    const Genome& source, const NeuralNet& oldNet, bool enableBias,
    Genome& destination, NeuralNet& destinationNet
) {
    if (source.schema != BrainSchema{}
        || source.size() > GENOME_MAX_LENGTH
        || oldNet.neurons.size() != MAX_INTERNAL_NEURONS)
        return false;
    for (const auto& neuron : oldNet.neurons)
        if (!std::isfinite(neuron.output)) return false;

    Genome next;
    next.schema = {2, enableBias};
    next.reserve(source.size());
    for (const Gene& original : source) {
        Gene gene = original;
        gene.sourceNum = static_cast<std::uint16_t>(
            original.sourceType == SOURCE_SENSOR
                ? original.sourceNum % S
                : original.sourceNum % MAX_INTERNAL_NEURONS);
        gene.sinkNum = static_cast<std::uint16_t>(
            original.sinkType == SINK_ACTION
                ? original.sinkNum % A
                : original.sinkNum % MAX_INTERNAL_NEURONS);
        gene.weight = logweight::store(
            logweight::quantizeLegacy(original.weight));
        next.push_back(gene);
    }

    NeuralNet nextNet;
    if (!buildCanonicalNet<S, A>(next, nextNet)) return false;
    for (int i = 0; i < MAX_INTERNAL_NEURONS; ++i)
        nextNet.neurons[i].output = oldNet.neurons[i].output;

    destination = std::move(next);
    destinationNet = std::move(nextNet);
    return true;
}

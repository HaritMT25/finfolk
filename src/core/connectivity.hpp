#pragma once
#include "genome.hpp"
#include <array>
#include "sensors_actions.hpp"

// Shared connectivity embedding: fold a genome into a fixed-length vector indexed
// by (source, sink) cell, mirroring how buildNeuralNet() wires the net. Used by
// BOTH the SimHash species metric (stats.hpp) and genome colouring
// (genome_color.hpp), so the two can never drift apart.

constexpr int STATS_SRC = NUM_SENSES  + MAX_INTERNAL_NEURONS;  // sources
constexpr int STATS_SNK = NUM_ACTIONS + MAX_INTERNAL_NEURONS;  // sinks
constexpr int STATS_DIM = STATS_SRC * STATS_SNK;

inline int geneCell(const Gene& gene, BrainSchema schema = {}) {
    const int source = genomeSourceIndex(gene, schema, NUM_SENSES);
    const int sink = genomeSinkIndex(gene, schema, NUM_ACTIONS);
    return source * STATS_SNK + sink;
}

inline constexpr int STATS_V2_DIM = STATS_DIM + STATS_SNK;

inline const auto& biasProjectionPlanes() {
    // Rows: colour 0..2, SimHash 3..18, cluster sketch 19..50.
    static const std::array<std::array<float, STATS_SNK>, 51> planes = [] {
        std::array<std::array<float, STATS_SNK>, 51> result{};
        std::mt19937 random(0xb1a52d02u);
        for (auto& row : result)
            for (float& value : row)
                value = portableGaussian(random);
        return result;
    }();
    return planes;
}

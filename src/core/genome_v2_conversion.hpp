#pragma once
#include "brain_conversion.hpp"
#include "predator_brain.hpp"
#include "genome_color.hpp"

template<class W>
inline bool convertWorldToGenomeV2(
    W& world, bool enableBias, const std::string& sourceSha256,
    std::string& error
) {
    if (world.frame > 9007199254740991ull || world.cfg.genomeVersion != 1
        || !world.brainConversion.sourceSha256.empty()
        || !validSourceSha256(sourceSha256)) {
        error = "conversion requires an unconverted v1 world and source SHA-256";
        return false;
    }
    if (const char* why = brainPolicyConfigError(world.cfg)) {
        error = why;
        return false;
    }

    SimConfig nextConfig = world.cfg;
    nextConfig.genomeVersion = 2;
    nextConfig.biasGenes = enableBias;
    nextConfig.hiddenNeurons = MAX_INTERNAL_NEURONS;
    nextConfig.brainEvalVersion = 2;
    nextConfig.weightMutationMode = WeightMutationMode::Saturating;
    if (const char* why = brainPolicyConfigError(nextConfig)) {
        error = why;
        return false;
    }

    auto prey = world.creatures;
    auto predators = world.predators;

    for (auto& creature : prey) {
        Genome converted;
        NeuralNet net;
        if (creature.genome.size() < static_cast<size_t>(nextConfig.genomeMinLength) ||
            creature.genome.size() > static_cast<size_t>(nextConfig.genomeMaxLength) ||
            !convertLegacyBrain<NUM_SENSES, NUM_ACTIONS>(
                creature.genome, creature.nnet, enableBias,
                converted, net)) {
            error = "invalid prey brain for conversion";
            return false;
        }
        creature.genome = std::move(converted);
        creature.nnet = std::move(net);
        creature.color = genomeColor(creature.genome);
    }

    if (world.cfg.predatorBrain) {
        for (auto& predator : predators) {
            Genome converted;
            NeuralNet net;
            if (predator.genome.size() < static_cast<size_t>(nextConfig.genomeMinLength) ||
                predator.genome.size() > static_cast<size_t>(nextConfig.genomeMaxLength) ||
                !convertLegacyBrain<NUM_PRED_SENSES, NUM_PRED_ACTIONS>(
                    predator.genome, predator.nnet, enableBias,
                    converted, net)) {
                error = "invalid predator brain for conversion";
                return false;
            }
            predator.genome = std::move(converted);
            predator.nnet = std::move(net);
        }
    }

    BrainConversion provenance;
    provenance.sourceSha256 = sourceSha256;
    provenance.sourceFrame = world.frame;
    provenance.sourceWeightMutationMode = world.cfg.weightMutationMode;

    world.creatures.swap(prey);
    world.predators.swap(predators);
    world.cfg = nextConfig;
    world.brainConversion = std::move(provenance);
    return true;
}

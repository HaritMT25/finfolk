// Compile this unchanged against main, the review HEAD, and the fixed headers.
// Its accepted serialized output must be identical to main's.
#include <cstring>
#include <iostream>
#include "core/checkpoint_io.hpp"
int main() {
    rng.seed(42);
    World source;
    source.cfg.weightMutationMode = WeightMutationMode::Saturating;
    source.cfg.genomeMinLength = source.cfg.genomeMaxLength = 1;
    source.cfg.genomeInitMin = source.cfg.genomeInitMax = 1;
    source.cfg.minPopulation = 0;
    source.init(640, 480, 3);
    const auto input = checkpoint::serialize(source, "test");
    World reused;
    reused.cfg.predatorBrain = reused.cfg.predatorPrimer = true;
    reused.cfg.genomeVersion = reused.cfg.brainEvalVersion = 2;
    reused.cfg.biasGenes = true;
    reused.cfg.weightMutationMode = WeightMutationMode::Saturating;
    const std::string before(reinterpret_cast<const char*>(&reused.cfg), sizeof reused.cfg);
    std::string error;
    if (!checkpoint::deserialize(input, reused, error)) {
        std::cerr << "FAIL reused Stage-C accepts brain-off length-one checkpoint: " << error
                  << "; refused config unchanged="
                  << (std::memcmp(&reused.cfg, before.data(), sizeof reused.cfg) == 0) << '\n';
        return 1;
    }
    const auto output = checkpoint::serialize(reused, "test");
    if (output != input) { std::cerr << "FAIL reused checkpoint exact bytes\n"; return 1; }
    // A refused load must preserve the actual destination object, padding too.
    const std::string saved(reinterpret_cast<const char*>(&reused.cfg), sizeof reused.cfg);
    auto bad = input;
    const auto key = bad.find("\"bodyMutation\":");
    const auto value = bad.find(':', key) + 1;
    bad.replace(value, bad.find(',', value) - value, "-1");
    if (checkpoint::deserialize(bad, reused, error) ||
        std::memcmp(&reused.cfg, saved.data(), sizeof reused.cfg) != 0) {
        std::cerr << "FAIL refused checkpoint preserves every config byte\n"; return 1;
    }
    std::cout << output;
}

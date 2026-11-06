#pragma once
// ----------------------------------------------------------------------------
// transplant — Stage C's study primitive: a world made of the prey of one
// checkpoint (X) and the predators of another (Y), for time-shift assays
// ("prey of time t against predators of time t'") and their cross-replicate
// variant. The headless CLI runs it (main.cpp, --predators-from) and writes
// the result as an ordinary checkpoint, the ARENA; an assay is then a plain
// resume of the arena (--load-checkpoint ARENA --reseed-after-load R).
//
// The world passed in is X, already loaded. What happens to it:
//   * kept, exactly: everything of X's — the prey (genomes, recurrent state,
//     ids, lineages), food, pheromones, food patches, vortices, the frame (and
//     with it the food cycle's phase), nextId, the counters, the global rng
//     state, predRng_ if X has brains, and the config apart from the keys below.
//   * dropped: X's own predators.
//   * added: K predators. From Y, K sampled from its predators (all of them by
//     default; without replacement, or with replacement when K > |Y|), of which
//     ONLY the heritable state crosses: genome, lineageId, generation,
//     speedFactor, buddingFactor (and Y's id, kept as sourceId). With source
//     "random", K random-genome founders (how a Stage C run starts on an evolved
//     prey world).
//   * reset, for every added predator: energy = predatorNewbornEnergy (the
//     spawn energy), age 0, digestTimer 0, speed = top speed, recurrent outputs
//     0.5 (the birth state), captures 0, parentId 0, position and heading drawn
//     as World::init draws them, and a fresh id. Fresh ids start at
//     max(X's nextPredatorId, Y's nextPredatorId, 1 + Y's largest lineage id),
//     so no later id (a bud's, a floor refill's) can repeat a transplanted
//     lineage label. Y's ids are in the manifest and in each sourceId.
//
// Determinism: every draw here comes from four streams derived from the
// transplant seed S (streamSeed(S, k)): k = 1 picks Y's predators, k = 2 places
// them (position, heading), k = 3 makes the "random" founders' genomes, k = 4
// seeds predRng_ when X has no brains. Never the world's rng, so X's random
// stream is untouched and the arena is a pure function of (X, Y, count, seed,
// assay). Separate streams make the LAYOUT a function of (S, K, the world's
// size) only: whatever the donor's size, and whether the source is Y or
// "random", the K predators land on the same spots with the same headings.
//
// Config: X's, except
//   * predatorBrain on; predatorCount = K; from Y (a Y without brains is
//     refused): predatorMutation and predatorPrimer — they belong to Y's
//     population (with "random" they stay X's: its file for a version-2 X,
//     otherwise the command line or the default; the manifest says which);
//   * the predator physics that matter to the assay must already match
//     between X and Y — a mismatch is refused unless allowMismatch, and then
//     X's values stand:
//       frozen-newborn: perception, speed, capture radius, cooldown, turn rate,
//                       min speed, fastTanh (the hunt and the network);
//       frozen, live:   those plus metabolism, both move costs, meal, repro and
//                       newborn energy, max age (they drive ENERGY and AGE, and
//                       in live the deaths and buds);
//   * the assay:
//       frozen (the default): the economy ON with predatorFrozen — energy and age
//         are accounted (burn, meals, ageing) so ENERGY and AGE cycle through
//         their evolved range, but nobody dies or buds: at the budding threshold
//         a predator pays the newborn energy for a VIRTUAL bud (no child; counted,
//         a fitness readout), age wraps at the max age, energy is floored at 0;
//         the predator floor and cap 0; the prey minPopulation 0 (no random
//         founders join the prey);
//       frozen-newborn: the economy OFF — immortal, fixed, and every predator's
//         ENERGY and AGE read 0 for the whole assay (an ablation of the above);
//       live: X's config as it is (predators starve, age out and bud).
// Every change, and every Stage C key with its source, is in the manifest.
// ----------------------------------------------------------------------------
#include <algorithm>
#include <cstdint>
#include <string>
#include <vector>
#include "checkpoint_io.hpp"
#include "json_min.hpp"
#include "world.hpp"

namespace transplant {

struct Options {
    std::string preyPath;          // X (manifest only; the caller loaded it)
    std::string preyHash;          // fnv1a64 of X's file (manifest only)
    std::string predatorsFrom;     // Y's path, or "random"
    int count = -1;                // K; -1 = all of Y's (required with "random")
    unsigned seed = 1;             // the transplant's own stream
    std::string assay = "frozen";  // "frozen", "frozen-newborn" or "live"
    bool allowMismatch = false;
    std::vector<std::string> cliKeys;   // Stage C keys given on the command line (manifest only)
};

// The k-th stream's seed from the transplant seed S (splitmix64's finaliser over
// S and k): the streams are independent, so drawing more from one (a bigger
// donor to sample from) never moves another (the placements).
inline unsigned streamSeed(unsigned s, unsigned k) {
    std::uint64_t z = (std::uint64_t)s * 0x9E3779B97F4A7C15ull + (std::uint64_t)k * 0xD1B54A32D192ED03ull;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    z ^= z >> 31;
    return (unsigned)(z ^ (z >> 32));
}

// FNV-1a 64 of a file's bytes: identifies a source checkpoint in a manifest
// (not a cryptographic hash; tools add SHA-256 where they need one).
inline std::string fnv1a64(const std::string& bytes) {
    std::uint64_t h = 0xcbf29ce484222325ull;
    for (unsigned char c : bytes) { h ^= c; h *= 0x100000001b3ull; }
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", (unsigned long long)h);
    return buf;
}

// The predator physics an assay compares across X and Y.
struct PhysicsKey { const char* name; float SimConfig::* field; bool economy; };
inline constexpr PhysicsKey kPhysics[] = {
    {"predatorPerception", &SimConfig::predatorPerception, false},
    {"predatorSpeed", &SimConfig::predatorSpeed, false},
    {"predatorCaptureRadius", &SimConfig::predatorCaptureRadius, false},
    {"predatorCooldown", &SimConfig::predatorCooldown, false},
    {"predatorTurnRate", &SimConfig::predatorTurnRate, false},
    {"predatorMinSpeed", &SimConfig::predatorMinSpeed, false},
    {"predatorMetabolism", &SimConfig::predatorMetabolism, true},
    {"predatorMoveCost", &SimConfig::predatorMoveCost, true},
    {"moveCost", &SimConfig::moveCost, true},
    {"predatorMeal", &SimConfig::predatorMeal, true},
    {"predatorReproEnergy", &SimConfig::predatorReproEnergy, true},
    {"predatorNewbornEnergy", &SimConfig::predatorNewbornEnergy, true},
    {"predatorMaxAge", &SimConfig::predatorMaxAge, true},
};

// Apply to `world` (X, loaded). `yText` is Y's checkpoint text ("" for
// "random"). On success `manifest` holds a JSON record of the operation.
inline bool apply(World& world, const Options& o, const std::string& yText,
                  std::string& manifest, std::string& error) {
    if (o.assay != "frozen" && o.assay != "frozen-newborn" && o.assay != "live") {
        error = "--assay must be frozen, frozen-newborn or live"; return false;
    }
    if (o.count < -1) { error = "--transplant-count must be >= 0 (or -1 for all)"; return false; }
    const bool fromRandom = (o.predatorsFrom == "random");
    if (fromRandom && o.count < 0) { error = "--predators-from random needs --transplant-count K"; return false; }
    const bool economyMatters = (o.assay != "frozen-newborn");

    SimConfig& cfg = world.cfg;
    const bool xBrain = cfg.predatorBrain;
    std::vector<Predator> pool;
    SimConfig yc{};
    unsigned long long yFrame = 0, yNext = 0;
    std::vector<std::string> mismatches;

    if (!fromRandom) {
        jsonm::Value y;
        if (!jsonm::Parser::parse(yText, y, error)) { error = "predator source: " + error; return false; }
        if (y.stringOr("format", "") != checkpoint::FORMAT_ID) { error = "predator source is not an evo_boids checkpoint"; return false; }
        if (y.intOr("formatVersion", -1) != checkpoint::FORMAT_VERSION_BRAIN) {
            error = "predator source has no predator brains (format version 2 required)"; return false;
        }
        checkpoint::readConfig(y, yc);
        if (!yc.predatorBrain) { error = "predator source's config has predatorBrain off"; return false; }
        if (const char* why = predatorBrainConfigError(yc)) { error = std::string("predator source config: ") + why; return false; }
        const jsonm::Value* yw = y.find("world");
        if (!yw) { error = "predator source has no 'world'"; return false; }
        yFrame = yw->ullOr("frame", 0);
        yNext = yw->ullOr("nextPredatorId", 0);
        const jsonm::Value* yp = y.find("predators");
        if (!yp) { error = "predator source has no 'predators'"; return false; }
        if (!checkpoint::readPredators(*yp, true, yNext, pool, error)) { error = "predator source: " + error; return false; }
        if (pool.empty() && o.count != 0) { error = "predator source has no predators"; return false; }
        for (const PhysicsKey& k : kPhysics) {
            if (k.economy && !economyMatters) continue;
            if (!(cfg.*k.field == yc.*k.field))
                mismatches.push_back(std::string(k.name) + ": prey world " + jsonm::Writer::fmtFloat(cfg.*k.field) +
                                     ", predator source " + jsonm::Writer::fmtFloat(yc.*k.field));
        }
        if (cfg.fastTanh != yc.fastTanh)
            mismatches.push_back(std::string("fastTanh: prey world ") + (cfg.fastTanh ? "true" : "false") +
                                 ", predator source " + (yc.fastTanh ? "true" : "false"));
        if (!mismatches.empty() && !o.allowMismatch) {
            error = "predator physics differ between the two checkpoints (" + mismatches.front() +
                    (mismatches.size() > 1 ? ", ..." : "") + "); --transplant-allow-mismatch keeps the prey world's";
            return false;
        }
    }

    const int K = (o.count < 0) ? (int)pool.size() : o.count;
    RandomGen pickRng(streamSeed(o.seed, 1)), placeRng(streamSeed(o.seed, 2)),
              genomeRng(streamSeed(o.seed, 3)), seedRng(streamSeed(o.seed, 4));

    // 1. which of Y's predators (indices into pool)
    std::vector<int> picks;
    if (!fromRandom) {
        const int np = (int)pool.size();
        if (K <= np) {
            std::vector<int> idx((size_t)np);
            for (int i = 0; i < np; ++i) idx[(size_t)i] = i;
            if (K < np) {   // partial Fisher-Yates; all of Y => Y's order, no draws
                for (int i = 0; i < K; ++i) {
                    const int j = i + (int)pickRng.uint((uint32_t)(np - 1 - i));
                    std::swap(idx[(size_t)i], idx[(size_t)j]);
                }
            }
            picks.assign(idx.begin(), idx.begin() + K);
        } else {
            for (int i = 0; i < K; ++i) picks.push_back((int)pickRng.uint((uint32_t)(np - 1)));
        }
    }

    // 2. config changes (recorded), and where each Stage C key comes from
    struct Change { std::string key, from, to; };
    std::vector<Change> changes;
    auto fb = [](bool b) { return std::string(b ? "true" : "false"); };
    auto setB = [&](const char* k, bool& f, bool v) { if (f != v) changes.push_back({k, fb(f), fb(v)}); f = v; };
    auto setI = [&](const char* k, int& f, int v) {
        if (f != v) changes.push_back({k, std::to_string(f), std::to_string(v)}); f = v; };
    auto setF = [&](const char* k, float& f, float v) {
        if (!(f == v)) changes.push_back({k, jsonm::Writer::fmtFloat(f), jsonm::Writer::fmtFloat(v)}); f = v; };
    auto onCli = [&](const char* k) { return std::find(o.cliKeys.begin(), o.cliKeys.end(), k) != o.cliKeys.end(); };
    const char* xSource = xBrain ? "prey checkpoint" : nullptr;
    auto xOrCli = [&](const char* k) { return std::string(xSource ? xSource : (onCli(k) ? "command line" : "default")); };
    std::vector<std::pair<std::string, std::string>> sources;   // key -> source
    setB("predatorBrain", cfg.predatorBrain, true);
    sources.push_back({"predatorBrain", "transplant"});
    setI("predatorCount", cfg.predatorCount, K);
    if (!fromRandom) {
        setF("predatorMutation", cfg.predatorMutation, yc.predatorMutation);
        setB("predatorPrimer", cfg.predatorPrimer, yc.predatorPrimer);
        sources.push_back({"predatorMutation", "predator checkpoint"});
        sources.push_back({"predatorPrimer", "predator checkpoint"});
    } else {
        sources.push_back({"predatorMutation", xOrCli("predatorMutation")});
        sources.push_back({"predatorPrimer", xOrCli("predatorPrimer")});
    }
    sources.push_back({"predatorTurnRate", xOrCli("predatorTurnRate")});
    sources.push_back({"predatorMinSpeed", xOrCli("predatorMinSpeed")});
    if (o.assay == "frozen") {
        setB("predatorEconomy", cfg.predatorEconomy, true);
        setB("predatorFrozen", cfg.predatorFrozen, true);
    } else if (o.assay == "frozen-newborn") {
        setB("predatorEconomy", cfg.predatorEconomy, false);
        setB("predatorFrozen", cfg.predatorFrozen, false);
    } else {
        setB("predatorFrozen", cfg.predatorFrozen, false);
    }
    sources.push_back({"predatorEconomy", o.assay == "live" ? "prey checkpoint" : "assay"});
    sources.push_back({"predatorFrozen", "assay"});
    if (o.assay != "live") {
        setI("predatorMinPopulation", cfg.predatorMinPopulation, 0);
        setI("predatorMaxPopulation", cfg.predatorMaxPopulation, 0);
        setI("minPopulation", cfg.minPopulation, 0);
    }
    if (const char* why = predatorBrainConfigError(cfg)) { error = std::string("arena config: ") + why; return false; }

    // 3. the predators. Fresh ids above every id and lineage label in X and Y.
    unsigned long long firstId = xBrain ? world.nextPredatorId_ : 1ull;
    firstId = std::max<unsigned long long>(firstId, yNext);
    for (const Predator& q : pool) firstId = std::max<unsigned long long>(firstId, q.lineageId + 1);
    world.nextPredatorId_ = firstId;
    const std::size_t dropped = world.predators.size();
    std::vector<Predator> added;
    added.reserve((size_t)K);
    const float W = (float)world.width, H = (float)world.height;
    for (int i = 0; i < K; ++i) {
        Predator p;
        if (fromRandom) {
            p.genome = predbrain::founderGenome(cfg, genomeRng);
        } else {
            const Predator& src = pool[(size_t)picks[(size_t)i]];
            p.genome = src.genome;
            p.lineageId = src.lineageId;
            p.generation = src.generation;
            p.speedFactor = src.speedFactor;
            p.buddingFactor = src.buddingFactor;
            p.sourceId = src.id;
        }
        p.pos = {placeRng.range(10.0f, W - 10.0f), placeRng.range(10.0f, H - 10.0f)};
        const float a = placeRng.range(0.0f, 6.2832f);
        p.vel = {evomath::cosf(a), evomath::sinf(a)};
        p.energy = cfg.predatorNewbornEnergy;   // the spawn energy
        p.age = 0.0f;
        predbrain::buildNet(p.genome, p.nnet);   // recurrent outputs at 0.5
        p.id = world.nextPredatorId_++;
        if (fromRandom) p.lineageId = p.id;
        p.parentId = 0;
        p.speed = predbrain::topSpeed(p, cfg);
        added.push_back(std::move(p));
    }
    if (!xBrain) world.predRng_.seed(seedRng.uint());
    world.predators = std::move(added);
    world.predLog_.clear();
    world.predTally_ = WorldCommon::PredatorTally{};
    world.arenaFresh_ = true;   // its first run logs T rows (main.cpp)

    // 4. the manifest
    manifest.clear();
    jsonm::Writer w(manifest);
    w.beginObject();
    w.field("schema", "finfolk.predc.transplant/2");
    w.key("prey"); w.beginObject();
    w.field("path", o.preyPath);
    w.field("fnv1a64", o.preyHash);
    w.field("frame", (unsigned long long)world.frame);
    w.field("creatures", (long long)world.creatures.size());
    w.field("hadBrains", xBrain);
    w.field("predatorsDropped", (long long)dropped);
    w.endObject();
    w.key("predators"); w.beginObject();
    w.field("source", o.predatorsFrom);
    w.field("fnv1a64", fromRandom ? std::string() : fnv1a64(yText));
    w.field("frame", yFrame);
    w.field("nextPredatorId", yNext);
    w.field("pool", (long long)pool.size());
    w.field("count", (long long)K);
    w.field("seed", (unsigned long long)o.seed);
    w.field("withReplacement", !fromRandom && K > (int)pool.size());
    w.field("firstId", firstId);
    w.key("startState"); w.beginObject();
    w.field("energy", cfg.predatorNewbornEnergy);
    w.field("age", 0.0f);
    w.field("digestTimer", 0.0f);
    w.field("neuronOutputs", 0.5f);
    w.endObject();
    w.key("picked"); w.beginArray();
    for (int i = 0; i < K; ++i) {
        const Predator& p = world.predators[(size_t)i];
        w.beginObject();
        if (!fromRandom) {
            w.field("sourceIndex", (long long)picks[(size_t)i]);
            w.field("sourceId", (unsigned long long)p.sourceId);
        }
        w.field("id", (unsigned long long)p.id);
        w.field("lineageId", (unsigned long long)p.lineageId);
        w.field("generation", (unsigned long long)p.generation);
        w.field("genomeLength", (long long)p.genome.size());
        w.endObject();
    }
    w.endArray();
    w.endObject();
    w.field("assay", o.assay);
    w.field("assayRules", o.assay == "frozen"
        ? "economy accounting on; no deaths, no buds: at the budding threshold a virtual bud (pays the newborn "
          "energy, no child, counted as virtual_buds in predators.csv and per predator as virtualBuds in "
          "checkpoints); age wraps at the max age; energy floored at 0; score from predators.csv"
        : o.assay == "frozen-newborn"
        ? "economy off: immortal, fixed; ENERGY and AGE read 0 throughout; score from predators.csv"
        : "the prey world's config: predators starve, age out and bud; score from predators.csv");
    w.field("streams", "streamSeed(seed, k): 1 selection, 2 placement, 3 founder genomes, 4 the predator stream");
    w.key("stageC"); w.beginObject();   // every Stage C key of the arena, with its source
    auto keyBlock = [&](const char* k, auto value) {
        std::string src = "?";
        for (const auto& s : sources) if (s.first == k) src = s.second;
        w.key(k); w.beginObject(); w.field("value", value); w.field("source", src); w.endObject();
    };
    keyBlock("predatorBrain", cfg.predatorBrain);
    keyBlock("predatorEconomy", cfg.predatorEconomy);
    keyBlock("predatorFrozen", cfg.predatorFrozen);
    keyBlock("predatorMutation", cfg.predatorMutation);
    keyBlock("predatorPrimer", cfg.predatorPrimer);
    keyBlock("predatorTurnRate", cfg.predatorTurnRate);
    keyBlock("predatorMinSpeed", cfg.predatorMinSpeed);
    w.endObject();
    w.key("configChanges"); w.beginArray();
    for (const Change& c : changes) {
        w.beginObject(); w.field("key", c.key); w.field("from", c.from); w.field("to", c.to); w.endObject();
    }
    w.endArray();
    w.key("physicsCompared"); w.beginArray();
    for (const PhysicsKey& k : kPhysics) if (!k.economy || economyMatters) w.value(k.name);
    w.value("fastTanh");
    w.endArray();
    w.key("physicsMismatches"); w.beginArray();
    for (const std::string& m : mismatches) w.value(m);
    w.endArray();
    w.field("nextPredatorId", (unsigned long long)world.nextPredatorId_);
    w.endObject();
    manifest += '\n';
    return true;
}

}  // namespace transplant

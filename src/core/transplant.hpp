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
//     speedFactor, buddingFactor. With source "random", K random-genome
//     founders (how a Stage C run starts on an evolved prey world).
//   * reset, for every added predator: energy = predatorNewbornEnergy, age 0,
//     digestTimer 0, speed = top speed, recurrent outputs 0.5 (the birth state),
//     captures 0, parentId 0, a fresh id from X's nextPredatorId (Y's ids are in
//     the manifest), position and heading drawn as World::init draws them.
//
// Determinism: every draw here comes from RandomGen(seed) — the sample, the
// placements, the "random" genomes, and predRng_'s seed when X has no brains —
// never from the world's rng, so X's random stream is untouched and the arena
// is a pure function of (X, Y, count, seed, assay).
//
// Config: X's, except
//   * predatorBrain on; predatorCount = K; from Y (a Y without brains is
//     refused): predatorMutation and predatorPrimer — they belong to Y's
//     population;
//   * the predator physics (perception, speed, capture radius, cooldown,
//     metabolism, move cost and the moveCost it may reuse, meal, repro and
//     newborn energy, turn rate, min speed) must already match between X and Y:
//     a mismatch is refused unless allowMismatch, and then X's values stand;
//   * assay "frozen" (the default): predatorEconomy off (K immortal predators,
//     no buds, no mutation), the predator floor and cap 0, and the prey
//     minPopulation 0 (no random founders join the prey); "live": as X.
// Every change is listed in the manifest.
// ----------------------------------------------------------------------------
#include <string>
#include <vector>
#include <cstdint>
#include "checkpoint_io.hpp"
#include "json_min.hpp"
#include "world.hpp"

namespace transplant {

struct Options {
    std::string preyPath;          // X (manifest only; the caller loaded it)
    std::string predatorsFrom;     // Y's path, or "random"
    int count = -1;                // K; -1 = all of Y's (required with "random")
    unsigned seed = 1;             // the transplant's own stream
    std::string assay = "frozen";  // "frozen" or "live"
    bool allowMismatch = false;
};

// The predator physics an assay compares across X and Y.
struct PhysicsKey { const char* name; float SimConfig::* field; };
inline constexpr PhysicsKey kPhysics[] = {
    {"predatorPerception", &SimConfig::predatorPerception},
    {"predatorSpeed", &SimConfig::predatorSpeed},
    {"predatorCaptureRadius", &SimConfig::predatorCaptureRadius},
    {"predatorCooldown", &SimConfig::predatorCooldown},
    {"predatorMetabolism", &SimConfig::predatorMetabolism},
    {"predatorMoveCost", &SimConfig::predatorMoveCost},
    {"moveCost", &SimConfig::moveCost},
    {"predatorMeal", &SimConfig::predatorMeal},
    {"predatorReproEnergy", &SimConfig::predatorReproEnergy},
    {"predatorNewbornEnergy", &SimConfig::predatorNewbornEnergy},
    {"predatorTurnRate", &SimConfig::predatorTurnRate},
    {"predatorMinSpeed", &SimConfig::predatorMinSpeed},
};

// Apply to `world` (X, loaded). `yText` is Y's checkpoint text ("" for
// "random"). On success `manifest` holds a JSON record of the operation.
inline bool apply(World& world, const Options& o, const std::string& yText,
                  std::string& manifest, std::string& error) {
    if (o.assay != "frozen" && o.assay != "live") { error = "--assay must be frozen or live"; return false; }
    const bool fromRandom = (o.predatorsFrom == "random");
    if (fromRandom && o.count < 0) { error = "--predators-from random needs --transplant-count K"; return false; }

    SimConfig& cfg = world.cfg;
    const bool xBrain = cfg.predatorBrain;
    std::vector<Predator> pool;
    SimConfig yc{};
    unsigned long long yFrame = 0;
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
        const unsigned long long yNext = yw->ullOr("nextPredatorId", 0);
        const jsonm::Value* yp = y.find("predators");
        if (!yp) { error = "predator source has no 'predators'"; return false; }
        if (!checkpoint::readPredators(*yp, true, yNext, pool, error)) { error = "predator source: " + error; return false; }
        if (pool.empty() && o.count != 0) { error = "predator source has no predators"; return false; }
        for (const PhysicsKey& k : kPhysics)
            if (!(cfg.*k.field == yc.*k.field))
                mismatches.push_back(std::string(k.name) + ": prey world " + jsonm::Writer::fmtFloat(cfg.*k.field) +
                                     ", predator source " + jsonm::Writer::fmtFloat(yc.*k.field));
        if (!mismatches.empty() && !o.allowMismatch) {
            error = "predator physics differ between the two checkpoints (" + mismatches.front() +
                    (mismatches.size() > 1 ? ", ..." : "") + "); --transplant-allow-mismatch keeps the prey world's";
            return false;
        }
    }

    const int K = (o.count < 0) ? (int)pool.size() : o.count;
    RandomGen tr(o.seed);

    // 1. which of Y's predators (indices into pool)
    std::vector<int> picks;
    if (!fromRandom) {
        const int np = (int)pool.size();
        if (K <= np) {
            std::vector<int> idx((size_t)np);
            for (int i = 0; i < np; ++i) idx[(size_t)i] = i;
            if (K < np) {   // partial Fisher-Yates; all of Y => Y's order, no draws
                for (int i = 0; i < K; ++i) {
                    const int j = i + (int)tr.uint((uint32_t)(np - 1 - i));
                    std::swap(idx[(size_t)i], idx[(size_t)j]);
                }
            }
            picks.assign(idx.begin(), idx.begin() + K);
        } else {
            for (int i = 0; i < K; ++i) picks.push_back((int)tr.uint((uint32_t)(np - 1)));
        }
    }

    // 2. config changes (recorded)
    struct Change { std::string key, from, to; };
    std::vector<Change> changes;
    auto fb = [](bool b) { return std::string(b ? "true" : "false"); };
    auto setB = [&](const char* k, bool& f, bool v) { if (f != v) changes.push_back({k, fb(f), fb(v)}); f = v; };
    auto setI = [&](const char* k, int& f, int v) {
        if (f != v) changes.push_back({k, std::to_string(f), std::to_string(v)}); f = v; };
    auto setF = [&](const char* k, float& f, float v) {
        if (!(f == v)) changes.push_back({k, jsonm::Writer::fmtFloat(f), jsonm::Writer::fmtFloat(v)}); f = v; };
    setB("predatorBrain", cfg.predatorBrain, true);
    setI("predatorCount", cfg.predatorCount, K);
    if (!fromRandom) {
        setF("predatorMutation", cfg.predatorMutation, yc.predatorMutation);
        setB("predatorPrimer", cfg.predatorPrimer, yc.predatorPrimer);
    }
    if (o.assay == "frozen") {
        setB("predatorEconomy", cfg.predatorEconomy, false);
        setI("predatorMinPopulation", cfg.predatorMinPopulation, 0);
        setI("predatorMaxPopulation", cfg.predatorMaxPopulation, 0);
        setI("minPopulation", cfg.minPopulation, 0);
    }

    // 3. the predators
    const unsigned long long firstId = xBrain ? world.nextPredatorId_ : 1ull;
    world.nextPredatorId_ = firstId;
    const std::size_t dropped = world.predators.size();
    std::vector<Predator> added;
    added.reserve((size_t)K);
    const float W = (float)world.width, H = (float)world.height;
    for (int i = 0; i < K; ++i) {
        Predator p;
        if (fromRandom) {
            p.genome = predbrain::founderGenome(cfg, tr);
        } else {
            const Predator& src = pool[(size_t)picks[(size_t)i]];
            p.genome = src.genome;
            p.lineageId = src.lineageId;
            p.generation = src.generation;
            p.speedFactor = src.speedFactor;
            p.buddingFactor = src.buddingFactor;
        }
        p.pos = {tr.range(10.0f, W - 10.0f), tr.range(10.0f, H - 10.0f)};
        const float a = tr.range(0.0f, 6.2832f);
        p.vel = {evomath::cosf(a), evomath::sinf(a)};
        p.energy = cfg.predatorNewbornEnergy;
        predbrain::buildNet(p.genome, p.nnet);   // recurrent outputs at 0.5
        p.id = world.nextPredatorId_++;
        if (fromRandom) p.lineageId = p.id;
        p.parentId = 0;
        p.speed = predbrain::topSpeed(p, cfg);
        added.push_back(std::move(p));
    }
    if (!xBrain) world.predRng_.seed(tr.uint());
    world.predators = std::move(added);
    world.predLog_.clear();
    world.predTally_ = WorldCommon::PredatorTally{};

    // 4. the manifest
    manifest.clear();
    jsonm::Writer w(manifest);
    w.beginObject();
    w.field("schema", "finfolk.predc.transplant/1");
    w.key("prey"); w.beginObject();
    w.field("path", o.preyPath);
    w.field("frame", (unsigned long long)world.frame);
    w.field("creatures", (long long)world.creatures.size());
    w.field("hadBrains", xBrain);
    w.field("predatorsDropped", (long long)dropped);
    w.endObject();
    w.key("predators"); w.beginObject();
    w.field("source", o.predatorsFrom);
    w.field("frame", yFrame);
    w.field("pool", (long long)pool.size());
    w.field("count", (long long)K);
    w.field("seed", (unsigned long long)o.seed);
    w.field("withReplacement", !fromRandom && K > (int)pool.size());
    w.key("picked"); w.beginArray();
    for (int i = 0; i < K; ++i) {
        const Predator& p = world.predators[(size_t)i];
        w.beginObject();
        if (!fromRandom) {
            w.field("sourceIndex", (long long)picks[(size_t)i]);
            w.field("sourceId", (unsigned long long)pool[(size_t)picks[(size_t)i]].id);
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
    w.key("configChanges"); w.beginArray();
    for (const Change& c : changes) {
        w.beginObject(); w.field("key", c.key); w.field("from", c.from); w.field("to", c.to); w.endObject();
    }
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

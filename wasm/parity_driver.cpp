// parity_driver.cpp — the native-vs-wasm bit-for-bit determinism oracle.
//
// Runs the core sim headless (no SFML, no filesystem) and prints the final
// checkpoint JSON to stdout. Build the SAME file with the native toolchain and
// with Emscripten, run both with the same arguments, and byte-compare:
//
//   g++ -O3 -std=c++20 -ffp-contract=off -I src wasm/parity_driver.cpp -o parity_native
//   em++ -O3 -std=c++20 -ffp-contract=off -I src wasm/parity_driver.cpp -o parity_wasm.js
//   ./parity_native 42 2000 > a.json && node parity_wasm.js 42 2000 > b.json && cmp a.json b.json
//
// The checkpoint is a canonical encoding of the ENTIRE world (creatures with
// neuron state, predators, food, pheromone grid, rng engine state, config), so
// byte equality of two checkpoints == bit-for-bit identical simulations.
// wasm/parity.sh runs the full matrix.
//
// Usage: parity_driver SEED STEPS [--rich] [--tri] [--toroidal] [--body-model]
//                      [--repro-max-distance F] [--repro-soft-width F]
//                      [--repro-grace F] [--engine-version STR] [--trace N]
//   --rich   turn on every hidden-state subsystem (mirrors the resume test's
//            configureRichWorld: eddies, food patches + drift, 4 predators with
//            economy, move cost, topological cap 7, gene cost)
//   --tri    triangular motion (exercises atan2f)
//   --repro-max-distance  exercise the genetic reproduction gate (isolation.hpp):
//            a sort + merge-join over folded genomes on the reproduction path
//   --repro-soft-width  widen that gate into a linear acceptance ramp. Needs
//            --repro-max-distance >= 0 to do anything, and ADDS TO THE RANDOM
//            STREAM (one rng.unit per gate evaluation), so like --body-model it
//            needs native==wasm proven on its own path.
//   --repro-grace  young founders bypass the gate. Needs --repro-max-distance
//            >= 0; draws nothing, but it changes WHICH pairs breed.
//   --body-model  exercise the tier-1 body model (body_model.hpp): heritable
//            size/elongation feeding the speed clamp, turn rate and metabolism,
//            plus TWO rng draws per insertion — a dynamics knob that adds to the
//            random stream, so §6.2 requires native==wasm proven with it on.
//            bodyMutation stays at its 0.1 default.
//   --pred-floor N / --pred-cap N / --pred-inherit  (v0.26.0) the predator floor,
//            ceiling and heritable traits. They act on the economy, so use them
//            with --rich. The floor and inheritance ADD TO THE RANDOM STREAM
//            (three draws per refill, two per bud), so like --body-model each
//            needs native==wasm proven on its own path.
//   --pred-count N / --pred-meal F  override --rich's 4 predators / absorb meal,
//            to reach a regime where the floor or the cap actually bites.
//   --pred-brain / --pred-noecon / --pred-frozen / --pred-primer / --pred-max-age F
//            (v0.27.0) Stage C neural predators (their own random stream,
//            predRng_), the frozen-newborn assay (brains without the economy),
//            the frozen assay (the economy's accounting with no deaths or buds),
//            the pursuit primer, and a predator lifespan for turnover.
//   --trace  print "frame fingerprint" to stderr every N steps (divergence bisection)
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <string>
#include <chrono>
#include "core/world.hpp"
#include "core/checkpoint_io.hpp"
#include "core/random.hpp"

// Compact whole-state fingerprint for bisecting the first divergent step.
// (The checkpoint bytes are the real oracle; this is just cheap per-step.)
static uint64_t fingerprint(const World& w) {
    uint64_t h = 1469598103934665603ull;
    auto mix = [&](const void* p, size_t n) {
        const unsigned char* b = (const unsigned char*)p;
        for (size_t i = 0; i < n; ++i) { h ^= b[i]; h *= 1099511628211ull; }
    };
    mix(&w.frame, sizeof w.frame);
    size_t nc = w.creatures.size(), nf = w.food.size(), np = w.predators.size();
    uint64_t counts[3] = {nc, nf, np};
    mix(counts, sizeof counts);
    for (const auto& c : w.creatures) {
        mix(&c.pos, sizeof c.pos);
        mix(&c.vel, sizeof c.vel);
        mix(&c.foodReserves, sizeof c.foodReserves);
        // v0.23.0 body model, mirroring the deepFingerprint widening in
        // tests/core_tests.cpp. This trace is the divergence-BISECTION tool —
        // when parity.sh reports a byte mismatch, this is what says which step
        // it started at — so it must cover every field the checkpoint carries
        // or it points at the wrong step. Demonstrated: with the inherited
        // bodyElong scaled by 1.5 the checkpoints differ, yet every line of the
        // pre-widening trace was identical — the tool reported "no divergence"
        // on a divergent run. Widened, it reports the first divergent step.
        mix(&c.bodySize, sizeof c.bodySize);
        mix(&c.bodyElong, sizeof c.bodyElong);
        mix(c.body, sizeof c.body);
    }
    for (const auto& p : w.predators) {
        mix(&p.pos, sizeof p.pos);
        mix(&p.vel, sizeof p.vel);
        // v0.26.0 predator traits, for the reason above — but only when
        // inheritance is on, so the default trace stays the 0.25.0 trace and
        // §6.1 can compare it against a pre-0.26 driver line for line. Off,
        // the traits are 1.0 by construction and carry no information.
        if (w.cfg.predatorInheritance) {
            mix(&p.speedFactor, sizeof p.speedFactor);
            mix(&p.buddingFactor, sizeof p.buddingFactor);
        }
        // v0.27.0 Stage C brains, by the same rule: only with the brain on, so
        // every brain-off trace is the 0.26.0 trace line for line.
        if (w.cfg.predatorBrain) {
            mix(&p.speed, sizeof p.speed);
            mix(&p.energy, sizeof p.energy);
            mix(&p.id, sizeof p.id);
            for (const Gene& g : p.genome) { const int16_t wt = g.weight; mix(&wt, sizeof wt); }
            for (const auto& nr : p.nnet.neurons) mix(&nr.output, sizeof nr.output);
        }
    }
    if (!w.signals.data().empty())
        mix(w.signals.data().data(), w.signals.data().size());
    return h;
}

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr, "usage: %s SEED STEPS [--rich] [--tri] [--engine-version STR] [--trace N]\n", argv[0]);
        return 2;
    }
    // Locale guard: checkpoint bytes assume C-locale float formatting.
    {
        char buf[16];
        std::snprintf(buf, sizeof buf, "%.9g", 0.5);
        if (std::strcmp(buf, "0.5") != 0) {
            std::fprintf(stderr, "FATAL: non-C locale float formatting (%s)\n", buf);
            return 3;
        }
    }

    const unsigned seed = (unsigned)std::strtoul(argv[1], nullptr, 10);
    const long steps = std::strtol(argv[2], nullptr, 10);
    bool rich = false, tri = false, tor = false, bodyModel = false;
    float reproMaxDistance = -1.0f;
    float reproSoftWidth = 0.0f, reproGracePeriod = 0.0f;
    int predFloor = 0, predCap = 0, predCount = -1;
    bool predInherit = false;
    bool predBrain = false, predNoEcon = false, predPrimer = false, predFrozen = false;
    float predMaxAge = 0.0f;
    float predMeal = -2.0f;   // < -1.5 => leave the config default alone
    const char* engineVersion = "parity";
    long traceEvery = 0;
    for (int i = 3; i < argc; ++i) {
        if (!std::strcmp(argv[i], "--rich")) rich = true;
        else if (!std::strcmp(argv[i], "--tri")) tri = true;
        else if (!std::strcmp(argv[i], "--toroidal")) tor = true;
        else if (!std::strcmp(argv[i], "--body-model")) bodyModel = true;
        else if (!std::strcmp(argv[i], "--repro-max-distance") && i + 1 < argc)
            reproMaxDistance = (float)std::atof(argv[++i]);
        else if (!std::strcmp(argv[i], "--repro-soft-width") && i + 1 < argc)
            reproSoftWidth = (float)std::atof(argv[++i]);
        else if (!std::strcmp(argv[i], "--repro-grace") && i + 1 < argc)
            reproGracePeriod = (float)std::atof(argv[++i]);
        else if (!std::strcmp(argv[i], "--pred-floor") && i + 1 < argc)
            predFloor = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "--pred-cap") && i + 1 < argc)
            predCap = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "--pred-count") && i + 1 < argc)
            predCount = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "--pred-meal") && i + 1 < argc)
            predMeal = (float)std::atof(argv[++i]);
        else if (!std::strcmp(argv[i], "--pred-inherit")) predInherit = true;
        else if (!std::strcmp(argv[i], "--pred-brain")) predBrain = true;
        else if (!std::strcmp(argv[i], "--pred-noecon")) predNoEcon = true;
        else if (!std::strcmp(argv[i], "--pred-primer")) predPrimer = true;
        else if (!std::strcmp(argv[i], "--pred-frozen")) predFrozen = true;
        else if (!std::strcmp(argv[i], "--pred-max-age") && i + 1 < argc)
            predMaxAge = (float)std::atof(argv[++i]);
        else if (!std::strcmp(argv[i], "--engine-version") && i + 1 < argc) engineVersion = argv[++i];
        else if (!std::strcmp(argv[i], "--trace") && i + 1 < argc) traceEvery = std::strtol(argv[++i], nullptr, 10);
        else { std::fprintf(stderr, "unknown arg %s\n", argv[i]); return 2; }
    }

    // Mirror the CLI's deterministic headless path exactly (main.cpp): seed,
    // then cfg BEFORE init, then N x update(0.016f).
    rng.seed(seed);
    World world;
    if (rich) {
        world.cfg.currentStrength = 80.0f;
        world.cfg.currentMode     = 0;
        world.cfg.currentDrift    = 1.0f;
        world.cfg.foodPatches     = 5;
        world.cfg.foodDrift       = true;
        world.cfg.predatorCount   = 4;
        world.cfg.predatorEconomy = true;
        world.cfg.moveCost        = 7e-5f;
        world.cfg.maxNeighbors    = 7;
        world.cfg.geneCost        = 0.005f;
    }
    if (tri) world.cfg.triangularMotion = true;
    if (tor) world.cfg.toroidal = true;
    if (bodyModel) world.cfg.bodyModel = true;   // bodyMutation stays at 0.1
    world.cfg.reproMaxDistance = reproMaxDistance;
    world.cfg.reproSoftWidth   = reproSoftWidth;
    world.cfg.reproGracePeriod = reproGracePeriod;
    world.cfg.predatorMinPopulation = predFloor;
    world.cfg.predatorMaxPopulation = predCap;
    world.cfg.predatorInheritance   = predInherit;   // predatorTraitMutation stays at 0.1
    if (predCount >= 0) world.cfg.predatorCount = predCount;
    if (predMeal > -1.5f) world.cfg.predatorMeal = predMeal;
    if (predBrain) world.cfg.predatorBrain = true;           // Stage C (v0.27.0)
    if (predNoEcon) world.cfg.predatorEconomy = false;       // the frozen mode
    if (predPrimer) world.cfg.predatorPrimer = true;
    if (predFrozen) world.cfg.predatorFrozen = true;         // the frozen assay's accounting
    if (predMaxAge > 0.0f) world.cfg.predatorMaxAge = predMaxAge;
    world.init(1920, 1080, 300);

    const auto t0 = std::chrono::steady_clock::now();
    for (long i = 0; i < steps; ++i) {
        world.update(0.016f);
        if (traceEvery > 0 && (i + 1) % traceEvery == 0)
            std::fprintf(stderr, "%ld %016llx\n", i + 1, (unsigned long long)fingerprint(world));
    }
    const double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    std::fprintf(stderr, "# %ld steps, %.2f s, %.0f steps/s, pop %zu\n",
                 steps, secs, steps / (secs > 0 ? secs : 1e-9), world.creatures.size());

    const std::string blob = checkpoint::serialize(world, engineVersion);
    std::fwrite(blob.data(), 1, blob.size(), stdout);
    return 0;
}

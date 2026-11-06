// Predator integration smoke test (NO SFML) — exercises the same core+stats path
// the headless runner uses, with predators ON, and asserts the run-level
// invariants the unit tests can only check in miniature. Two harnesses:
//
//   Stage A (cfg.predatorEconomy == false): immortal, fixed-count. Asserts the
//     pop floor holds, nothing goes NaN / leaves the torus, predation happens,
//     predator_align stays in [-1,1], deaths partition exactly, and the predator
//     count never changes (immortal).
//
//   Stage B (cfg.predatorEconomy == true): the energy economy. Asserts the same
//     prey-side invariants PLUS the Stage-B ones: predator_pop is always >= 0 and
//     finite, predator energy never goes NaN, the predator death decomposition is
//     consistent (births and starvation/age counters only ever grow), and over
//     the run BOTH predator births AND predator deaths actually occur (the economy
//     is live, not inert). It does NOT assert non-extinction — predator extinction
//     is a legitimate, observable Stage-B outcome (there is no predator reseed
//     floor), so the harness only checks the bookkeeping stays sound through it.
//
//   Stage B + limits (v0.26.0): the same economy with a predator floor of 3, a
//     ceiling of 20 and heritable traits. Asserts every step that the count sits
//     in [floor, ceiling], that every trait stays finite and inside [0.5, 2], that
//     the refill counter never decreases, and that budding (with inheritance)
//     happened. It does NOT require a predator death: held at the ceiling, the
//     well-fed predators starve only now and then (1-7 deaths in 12,000 steps
//     across OpenMP runs, sometimes none), and the OpenMP and thread-pool builds
//     are not reproducible at a fixed seed, so that check flaked. The plain
//     Stage B run above asserts deaths (27-46 per run).
//
// It also prints the predator CSV columns so the output can be eyeballed.

#include <cstdio>
#include <cmath>
#include <algorithm>
#include "core/world.hpp"
#include "core/stats.hpp"

namespace {

int g_fails = 0;
void check(bool ok, const char* what) {
    std::printf("  [%s] %s\n", ok ? "PASS" : "FAIL", what);
    if (!ok) ++g_fails;
}

// Run a world for `steps`, sampling every `logEvery`, accumulating the shared
// prey-side invariants. Returns the final WorldStats. `econ` selects Stage A/B.
struct RunResult {
    bool floorHeld = true, sane = true, alignInRange = true;
    // Stage A only:
    bool countFixed = true;
    // Stage B only:
    bool predPopNonNeg = true, predEnergyFinite = true, countersMonotone = true;
    long long lastBirths = 0, lastStarv = 0, lastAge = 0;
    // Stage B + limits only:
    bool withinLimits = true, traitsInBand = true;
    long long lastReseeds = 0;
};

void runWorld(const char* tag, bool econ, int steps, int logEvery,
              int predFloor = 0, int predCap = 0, bool inherit = false) {
    const bool limits = predFloor > 0 || predCap > 0 || inherit;
    rng.seed(42u);
    World w;
    w.cfg.minPopulation = 50;        // prey reseed floor (default)
    w.cfg.moveCost      = 0.00007f;
    w.cfg.minSpeed      = 0.0f;
    w.cfg.geneCost      = 0.01f;
    w.cfg.predatorCount = 6;         // the recommended starting count
    if (econ) {
        w.cfg.predatorEconomy   = true;
        // A balanced-band economy (fixed meal so it can't explode on fat prey).
        // This is a SMOKE config (short run), not a tuned oscillator — see the
        // Stage-B notes; tuning is a real-run, replicate task.
        w.cfg.predatorMeal       = 14.0f;
        w.cfg.predatorMetabolism = 2.0f;
        w.cfg.predatorReproEnergy = 60.0f;
        w.cfg.predatorMinPopulation = predFloor;
        w.cfg.predatorMaxPopulation = predCap;
        w.cfg.predatorInheritance   = inherit;
    }
    w.init(1920, 1080, 300);

    std::printf("=== predator integration smoke (%s) ===\n", tag);
    std::printf("%s\n", statsCsvHeader().c_str());

    const std::size_t pred0 = w.predators.size();
    RunResult r;
    bool predBornEver = false, predDiedEver = false;

    for (int s = 1; s <= steps; ++s) {
        w.update(0.016f);

        if ((int)w.creatures.size() < w.cfg.minPopulation) r.floorHeld = false;
        if (!econ && w.predators.size() != pred0)          r.countFixed = false;

        // Per-step Stage-B bookkeeping sanity (cheap).
        if (econ) {
            for (const auto& p : w.predators)
                if (std::isnan(p.energy) || std::isinf(p.energy)) r.predEnergyFinite = false;
            if (w.totalPredatorBirths < r.lastBirths ||
                w.totalPredatorDeathsStarvation < r.lastStarv ||
                w.totalPredatorDeathsAge < r.lastAge) r.countersMonotone = false;
            r.lastBirths = w.totalPredatorBirths;
            r.lastStarv  = w.totalPredatorDeathsStarvation;
            r.lastAge    = w.totalPredatorDeathsAge;
            if (w.totalPredatorBirths > 0) predBornEver = true;
            if (w.totalPredatorDeathsStarvation + w.totalPredatorDeathsAge > 0) predDiedEver = true;
            if (limits) {
                const int n = (int)w.predators.size();
                if (n < predFloor || (predCap > 0 && n > std::max(predCap, predFloor))) r.withinLimits = false;
                for (const auto& p : w.predators)
                    if (!(p.speedFactor >= PRED_TRAIT_MIN && p.speedFactor <= PRED_TRAIT_MAX) ||
                        !(p.buddingFactor >= PRED_TRAIT_MIN && p.buddingFactor <= PRED_TRAIT_MAX))
                        r.traitsInBand = false;
                if (w.totalPredatorReseeds < r.lastReseeds) r.countersMonotone = false;
                r.lastReseeds = w.totalPredatorReseeds;
            }
        }

        if (s % logEvery == 0) {
            const WorldStats st = computeStats(w);
            for (const auto& c : w.creatures)
                if (std::isnan(c.pos.x) || std::isnan(c.pos.y) ||
                    c.pos.x < 0 || c.pos.x >= w.width ||
                    c.pos.y < 0 || c.pos.y >= w.height) r.sane = false;
            for (const auto& p : w.predators)
                if (std::isnan(p.pos.x) || std::isnan(p.pos.y) ||
                    p.pos.x < 0 || p.pos.x >= w.width ||
                    p.pos.y < 0 || p.pos.y >= w.height) r.sane = false;
            if (st.avgPredatorAlign < -1.0001f || st.avgPredatorAlign > 1.0001f)
                r.alignInRange = false;
            if (st.predatorPop < 0) r.predPopNonNeg = false;

            std::printf("step %-8d pop %5d pred %4d kills+ ?  pE %7.1f  bornEver=%d diedEver=%d\n",
                        s, st.population, st.predatorPop,
                        econ ? st.predatorAvgEnergy : 0.0f,
                        (int)predBornEver, (int)predDiedEver);
        }
    }

    const bool identity =
        (w.totalDeaths ==
         w.totalDeathsPredation + w.totalDeathsStarvation + w.totalDeathsAge);
    const bool predationHappened = (w.totalDeathsPredation > 0);

    std::printf("---------------------------------------------\n");
    std::printf("final(%s): pop=%zu pred=%zu kills=%lld starv=%lld age=%lld | "
                "predBirths=%lld predStarv=%lld predAge=%lld\n",
                tag, w.creatures.size(), w.predators.size(),
                w.totalDeathsPredation, w.totalDeathsStarvation, w.totalDeathsAge,
                w.totalPredatorBirths, w.totalPredatorDeathsStarvation, w.totalPredatorDeathsAge);

    check(r.floorHeld,         "prey min-population floor held every tick");
    check(r.sane,              "all positions finite and inside the torus");
    check(predationHappened,   "predation occurred (totalKills > 0)");
    check(r.alignInRange,      "predator_align stayed within [-1, 1]");
    check(identity,            "deaths == predation + starvation + age (exact partition)");
    if (!econ) {
        check(r.countFixed,    "predator count stayed fixed (Stage A: immortal)");
    } else {
        check(r.predPopNonNeg,     "predator_pop stayed >= 0");
        check(r.predEnergyFinite,  "predator energy stayed finite (no NaN/inf)");
        check(r.countersMonotone,  "predator birth/death counters never decreased");
        check(predBornEver,        "Stage B: predator reproduction occurred (economy live)");
        if (!limits) check(predDiedEver, "Stage B: predator death occurred (economy live)");
        if (limits) {
            check(r.withinLimits,  "predator count stayed inside [floor, ceiling] every tick");
            check(r.traitsInBand,  "every predator trait stayed finite and in [0.5, 2]");
            const WorldStats fin = computeStats(w);
            std::printf("  (floor refills %lld, mean speed trait %.3f, mean budding trait %.3f)\n",
                        w.totalPredatorReseeds, fin.predatorSpeedFactor, fin.predatorBuddingFactor);
        }
    }
    std::printf("\n");
}

// Stage C (v0.27.0): neural predators with the economy, floor 2, cap 20 and a
// 60 s lifespan (the Stage C recipe). Asserts every step: the count sits in
// [floor, cap], every predator has a genome within the bounds and a built net,
// its speed is finite and inside [min, top], ids are below nextPredatorId; and
// over the run: buds happened, generations climbed, the floor's refills and the
// births were both counted, captures happened. It does not assert coexistence
// or evolution: those are the pilot's questions, not a smoke test's.
void runBrain(int steps, int logEvery) {
    rng.seed(42u);
    World w;
    w.cfg.minPopulation = 50;
    w.cfg.moveCost = 0.00007f;
    w.cfg.predatorCount = 6;
    w.cfg.predatorEconomy = true;
    w.cfg.predatorBrain = true;
    w.cfg.predatorMeal = 14.0f;
    w.cfg.predatorMinPopulation = 2;
    w.cfg.predatorMaxPopulation = 20;
    w.cfg.predatorMaxAge = 60.0f;
    w.init(1920, 1080, 300);
    std::printf("=== predator integration smoke (Stage C: neural, floor 2, cap 20, max age 60) ===\n");
    bool inLimits = true, brainsOk = true, speedsOk = true;
    std::uint32_t maxGen = 0;
    for (int s = 1; s <= steps; ++s) {
        w.update(0.016f);
        const int n = (int)w.predators.size();
        if (n < 2 || n > 20) inLimits = false;
        for (const auto& p : w.predators) {
            if (p.genome.empty() || (int)p.genome.size() > w.cfg.genomeMaxLength ||
                p.nnet.flat.size() != p.genome.size() || p.id == 0 || p.id >= w.nextPredatorId_)
                brainsOk = false;
            const float top = predbrain::topSpeed(p, w.cfg);
            if (!std::isfinite(p.speed) || p.speed < 0.0f || p.speed > top || !std::isfinite(p.energy)) speedsOk = false;
            maxGen = std::max(maxGen, p.generation);
        }
        if (s % logEvery == 0)
            std::printf("step %-8d pop %5zu pred %3d births %lld reseeds %lld kills %lld maxGen %u\n", s,
                        w.creatures.size(), n, w.totalPredatorBirths, w.totalPredatorReseeds,
                        w.totalDeathsPredation, maxGen);
    }
    check(inLimits, "Stage C: predator count stayed inside [floor 2, cap 20] every tick");
    check(brainsOk, "Stage C: every predator had a genome in bounds, a built net and a valid id");
    check(speedsOk, "Stage C: every predator speed stayed finite and inside [min, top]");
    check(w.totalPredatorBirths > 0 && maxGen >= 1, "Stage C: predators budded (generations climbed)");
    check(w.totalDeathsPredation > 0, "Stage C: captures happened");
    check(w.totalDeaths == w.totalDeathsPredation + w.totalDeathsStarvation + w.totalDeathsAge,
          "Stage C: prey deaths == predation + starvation + age");
    std::printf("\n");
}

}  // namespace

int main() {
    const int steps    = 12000;   // long enough for Stage B births AND deaths
    const int logEvery = 3000;

    runWorld("Stage A: immortal/fixed-count", /*econ=*/false, steps, logEvery);
    runWorld("Stage B: energy economy",       /*econ=*/true,  steps, logEvery);
    runWorld("Stage B + floor 3, ceiling 20, inheritance", /*econ=*/true, steps, logEvery,
             /*predFloor=*/3, /*predCap=*/20, /*inherit=*/true);
    runBrain(steps, logEvery);

    if (g_fails == 0) { std::printf("SMOKE OK\n"); return 0; }
    std::printf("SMOKE FAILED (%d)\n", g_fails);
    return 1;
}

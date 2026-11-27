#pragma once
#include <vector>
#include <string>
#include <sstream>
#include <iomanip>
#include <cmath>
#include <algorithm>
#include <random>
#include <bitset>
#include <cstdint>
#include <cstring>
#include "world.hpp"
#include "spatial_grid.hpp"   // temp grid for the O(n) schooling-neighbour lookup

// ----------------------------------------------------------------------------
// Genetic spread metrics.
//
// Every gene is a weighted (source -> sink) connection. We fold a genome into a
// fixed-length vector indexed by (source, sink) cell — mirroring exactly how
// buildNeuralNet() remaps gene numbers — so genomes of different lengths and
// gene orderings become comparable points in one space. Duplicate edges sum,
// just as feedForward() accumulates their contributions, so the projection is
// faithful to the network the genome actually builds.
//
// From that representation we report two things per sample:
//   * geneticDiversity = RMS L2 distance of a genome from the population-mean
//     genome (sqrt of the summed per-dimension variance). This equals
//     sqrt(mean pairwise squared distance / 2), computed in one linear pass via
//     the variance identity — no O(n^2) all-pairs needed.
//   * species = number of distinct SimHash signatures. Each genome vector is
//     projected onto STATS_HASH_BITS fixed random hyperplanes; the sign pattern
//     is its bucket. It collapses toward 1 as the population converges and rises
//     toward the population size when every genome is distinct, so it is the
//     *drop* below population that signals speciation/convergence, not the raw
//     value. STATS_HASH_BITS sets the resolution (fewer bits = coarser clusters).
//
// Both are proven to discriminate (a converged population reads ~0 diversity and
// 1 species); if they sit flat-high in a given run, that run is genuinely not
// losing diversity, which is itself a finding.
// ----------------------------------------------------------------------------

// Connectivity embedding (STATS_SRC/SNK/DIM + geneCell) is shared with colouring.
#include "connectivity.hpp"
#include "plane_data.hpp"
constexpr int STATS_HASH_BITS = 16;  // SimHash resolution (species sensitivity)
static_assert(sizeof(kSimHashPlaneBits) / sizeof(kSimHashPlaneBits[0]) == STATS_HASH_BITS,
              "STATS_HASH_BITS changed — regenerate plane_data.hpp with tools/gen_planes.cpp");

// One linear pass over the population: exact variance-based diversity + a
// SimHash distinct-bucket count. Cost is O(population * genes), not O(n^2).
inline void computeGeneticSpread(const std::vector<Creature>& cs,
                                 float& diversityOut, int& speciesOut) {
    diversityOut = 0.0f;
    speciesOut   = 0;
    const int n = static_cast<int>(cs.size());
    if (n == 0) return;

    // Fixed random hyperplanes for SimHash — FROZEN constants (plane_data.hpp)
    // so signatures are comparable across samples and runs, and identical
    // across native and wasm builds (runtime std::normal_distribution was not).
    // Stored cell-major: one cell's STATS_HASH_BITS weights are one contiguous
    // row, so a touched cell reads a single row rather than one value from
    // each plane. Every plane still sums the same products in the same order.
    static const std::vector<float> HT = [] {
        std::vector<float> h(static_cast<std::size_t>(STATS_DIM) * STATS_HASH_BITS);
        for (int r = 0; r < STATS_HASH_BITS; ++r)
            for (int i = 0; i < STATS_DIM; ++i)
                std::memcpy(&h[static_cast<std::size_t>(i) * STATS_HASH_BITS + r],
                            &kSimHashPlaneBits[r][i], 4);
        return h;
    }();

    // Population accumulators for per-dimension variance. Zero cells contribute
    // nothing to either sum, so we only touch a genome's non-empty cells.
    std::vector<double> gsum(STATS_V2_DIM, 0.0), gsumsq(STATS_V2_DIM, 0.0);

    // Per-creature sparse scratch: `cell` holds this genome's folded weights,
    // `stamp` marks which cells belong to the current epoch so we never clear
    // the whole array and never double-count a cell.
    std::vector<float> cell(STATS_V2_DIM, 0.0f);
    std::vector<int>   stamp(STATS_V2_DIM, -1);
    std::vector<int>   touched;
    touched.reserve(GENOME_MAX_LENGTH);

    // A signature is a STATS_HASH_BITS-bit number, so one bit per possible
    // value counts the distinct ones, with no hashing and no allocation.
    static_assert(STATS_HASH_BITS <= 20, "the signature bitset holds 2^STATS_HASH_BITS bits");
    std::bitset<(std::size_t{1} << STATS_HASH_BITS)> signatures;

    int epoch = 0;
    for (const Creature& c : cs) {
        touched.clear();
        for (const Gene& g : c.genome) {
            const int idx = geneCell(g, c.genome.schema);
            if (stamp[idx] != epoch) { stamp[idx] = epoch; cell[idx] = 0.0f; touched.push_back(idx); }
            cell[idx] += geneWeight(g, c.genome.schema);
        }

        double proj[STATS_HASH_BITS] = {};
        for (const int idx : touched) {
            const double v = cell[idx];
            gsum[idx]   += v;
            gsumsq[idx] += v * v;
            for (int j = 0; j < STATS_HASH_BITS; ++j) {
                const float coefficient = idx < STATS_DIM
                    ? HT[static_cast<std::size_t>(idx) * STATS_HASH_BITS + j]
                    : biasProjectionPlanes()[3 + j][idx - STATS_DIM];
                proj[j] += v * coefficient;
            }
        }

        uint64_t sig = 0;
        for (int j = 0; j < STATS_HASH_BITS; ++j)
            if (proj[j] >= 0.0) sig |= (uint64_t{1} << j);
        signatures.set(sig);

        ++epoch;
    }

    const double invN = 1.0 / n;
    double totalVar = 0.0;
    for (int d = 0; d < STATS_V2_DIM; ++d) {
        const double mean = gsum[d] * invN;
        const double var  = gsumsq[d] * invN - mean * mean;
        if (var > 0.0) totalVar += var;
    }

    diversityOut = static_cast<float>(std::sqrt(totalVar));
    speciesOut   = static_cast<int>(signatures.count());
}

// ----------------------------------------------------------------------------
// WorldStats — a read-only snapshot of population-level metrics for one frame.
//
// World's job is to *run* the simulation; this struct's job is to *measure* it.
// Keeping them separate means the hot update loop carries no logging weight and
// the metrics can grow without touching simulation code.
//
// Note on births/deaths: World::births / World::deaths are reset every frame, so
// they only ever hold the most recent frame's count. For long-run measurement we
// read the cumulative World::totalBirths / World::totalDeaths instead, and the
// logger turns those into per-interval rates by differencing successive samples.
// ----------------------------------------------------------------------------
struct WorldStats {
    unsigned long long frame = 0;
    int population = 0;
    int food       = 0;

    // Cumulative since the start of the run.
    int totalBirths = 0;
    int totalDeaths = 0;

    // Population-wide averages.
    float avgAge            = 0.0f;
    float maxAge            = 0.0f;
    float avgEnergy         = 0.0f;  // foodReserves
    float avgSpeed          = 0.0f;
    float avgGenomeLen      = 0.0f;
    float avgResponsiveness = 0.0f;
    float avgOscPeriod      = 0.0f;

    // Spread / evolution signals.
    float genomeLenStd     = 0.0f;  // std-dev of genome length across the population
    float geneticDiversity = 0.0f;  // RMS distance of a genome from the population
                                     // mean in connectivity space (see above)
    int   species          = 0;     // distinct SimHash buckets (lineage proxy)

    // Behaviour-vs-environment signal. Mean cosine between each creature's heading
    // and the local ocean-flow direction: +1 = swimming with the flow (riding),
    // -1 = swimming against it (fighting upstream), 0 = crosswise. Undefined when
    // no current is active (logged as 0). Read it ALONGSIDE avgSpeed: low speed =
    // drifting regardless of heading; high speed + positive = surfing downstream;
    // high speed + negative = fighting upstream.
    float avgFlowAlign     = 0.0f;

    // --- Predator (Stage A) ---
    // predatorPop is instantaneous; the three death-cause totals are cumulative
    // (the logger differences them into per-interval columns, like births/deaths).
    // totalKills == cumulative predation deaths, so the CSV identity holds:
    //   deaths_interval == kills_interval + deaths_starvation + deaths_age.
    int   predatorPop           = 0;
    int   totalKills            = 0;  // cumulative predation kills (== predation deaths)
    int   totalDeathsStarvation = 0;
    int   totalDeathsAge        = 0;
    // The "ride vs fight" instrument for predation, mirroring avgFlowAlign: mean
    // cosine between a prey's heading and the AWAY-from-nearest-predator direction,
    // gated to prey with a predator actually within their perception. +1 = fleeing
    // directly away, -1 = swimming straight at it, 0 = crosswise / no threat in
    // range. Read with avgSpeed (fleeing only matters if they're also moving).
    // Without it you cannot tell "evasion evolved" from "the slow ones just died."
    float avgPredatorAlign      = 0.0f;

    // --- Schooling instruments ---
    // The predator_align metric assumes prey flee INDIVIDUALLY (radially away). If
    // prey instead evolve to SCHOOL (a dilution/confusion strategy), that evasion
    // is invisible to predator_align. These two measure schooling directly:
    //   avgNeighborAlign: per-prey cosine between its heading and the MEAN heading
    //     of prey within its perception, averaged over prey with >=1 neighbour.
    //     +1 = locally aligned (a school), 0 = neighbours' headings cancel
    //     (disordered). LOCAL by design, so several schools heading different ways
    //     each read high (a GLOBAL polarization would cancel them to ~0).
    //   avgNeighborCount: mean number of prey within perception. A school is
    //     aligned AND clumped, so read the two together — high align + high count
    //     is a school; high align + low count is a loose comigration.
    float avgNeighborAlign      = 0.0f;
    float avgNeighborCount      = 0.0f;

    // --- Predator energy economy (Stage B) ---
    // Births and the two predator death causes are cumulative (the logger
    // differences them into per-interval columns, like the prey deaths), so the
    // coupled oscillator can be read off the CSV: predator_pop rises with births,
    // falls as predators starve. predatorAvgEnergy is the instantaneous mean — the
    // quantity you tune to keep ABOVE zero (a population can look fine while its
    // mean energy is sliding toward a crash). All stay 0 in Stage A.
    int   totalPredatorBirths           = 0;
    int   totalPredatorDeathsStarvation = 0;
    int   totalPredatorDeathsAge        = 0;
    float predatorAvgEnergy             = 0.0f;

    // --- Pairing graph (v0.22.0) ---
    // Connected components, with at least cfg.reproMinCluster members, of the
    // graph whose edges are "these two Creatures produced one successor record"
    // over the last cfg.reproWindow events. See repro_graph.hpp for why this
    // exists: `species` above is a SimHash of the same folded connectivity
    // vector that the match-distance gate thresholds, so it cannot evaluate that
    // gate without circularity — and it is saturated anyway (measured: it tracks
    // the live-set count one-to-one, i.e. it counts individual Creatures). This
    // one is mechanism-level: an edge exists because an insertion happened.
    //
    // 0 means "no edges in the window", which is the honest report for a live
    // set that has stopped pairing — read it alongside births_interval, not on
    // its own.
    int   reproComponents               = 0;

    // --- Match-distance mitigations (v0.24.0) ---
    // Cumulative, like totalBirths, and both a SUBSET of it: births that only
    // happened because a founder was inside its grace window, and births the
    // hard gate at the same threshold would have refused but the soft ramp
    // admitted. Always reported (0 when the mitigations are off) so a sweep can
    // tell a rescued population apart from one the gate never bit, and tell
    // which of the two mechanisms did the rescuing.
    int   totalGraceBirths              = 0;
    int   totalSoftBirths               = 0;

    // --- Predator floor + heritable traits (v0.26.0) ---
    // totalPredatorReseeds is cumulative, like the predator births, and NOT a
    // subset of them: a predator the floor added was not born. The three means
    // are over the live predators, instantaneous, and 0 when there are none
    // (the predatorAvgEnergy convention). With inheritance off the two trait
    // means sit at exactly 1; the generation mean counts buds either way.
    int   totalPredatorReseeds          = 0;
    float predatorSpeedFactor           = 0.0f;
    float predatorBuddingFactor         = 0.0f;
    float predatorGeneration            = 0.0f;
};

// Generation depth across the live set, for the two HUDs. Deliberately not a
// WorldStats field, so the CSV schema is unchanged.
struct GenerationSpan {
    double        mean = 0.0;
    std::uint32_t max  = 0;
};
inline GenerationSpan generationSpan(const World& w) {
    GenerationSpan g;
    std::size_t n = 0;
    for (const Creature& c : w.creatures) {
        if (!c.alive) continue;
        g.mean += (double)c.generation;
        if (c.generation > g.max) g.max = c.generation;
        ++n;
    }
    if (n) g.mean /= (double)n;
    return g;
}

// Compute a snapshot from the current world state.
inline WorldStats computeStats(const World& w) {
    WorldStats s;
    s.frame       = w.frame;
    s.food        = static_cast<int>(w.food.size());
    s.totalBirths = w.totalBirths;
    s.totalDeaths = w.totalDeaths;
    s.totalGraceBirths = static_cast<int>(w.totalGraceBirths);
    s.totalSoftBirths  = static_cast<int>(w.totalSoftBirths);

    // Predator bookkeeping (instantaneous count + cumulative death-cause totals).
    s.predatorPop           = static_cast<int>(w.predators.size());
    s.totalKills            = static_cast<int>(w.totalDeathsPredation);
    s.totalDeathsStarvation = static_cast<int>(w.totalDeathsStarvation);
    s.totalDeathsAge        = static_cast<int>(w.totalDeathsAge);

    // Pairing graph over the trailing window (v0.22.0 — see repro_graph.hpp).
    s.reproComponents = w.reproComponents();

    // Predator energy economy (Stage B). Cumulative births/deaths + instantaneous
    // mean energy. Mean energy is only meaningful when the economy is on (in Stage
    // A the field is an unused seeded constant), so it is reported as 0 otherwise.
    s.totalPredatorBirths           = static_cast<int>(w.totalPredatorBirths);
    s.totalPredatorDeathsStarvation = static_cast<int>(w.totalPredatorDeathsStarvation);
    s.totalPredatorDeathsAge        = static_cast<int>(w.totalPredatorDeathsAge);
    if (w.cfg.predatorEconomy && !w.predators.empty()) {
        double pe = 0.0;
        for (const Predator& p : w.predators) pe += p.energy;
        s.predatorAvgEnergy = static_cast<float>(pe / w.predators.size());
    }
    s.totalPredatorReseeds = static_cast<int>(w.totalPredatorReseeds);
    if (!w.predators.empty()) {
        double sf = 0.0, bf = 0.0, gen = 0.0;
        for (const Predator& p : w.predators) {
            sf += p.speedFactor; bf += p.buddingFactor; gen += (double)p.generation;
        }
        const double inv = 1.0 / (double)w.predators.size();
        s.predatorSpeedFactor   = static_cast<float>(sf * inv);
        s.predatorBuddingFactor = static_cast<float>(bf * inv);
        s.predatorGeneration    = static_cast<float>(gen * inv);
    }

    const std::vector<Creature>& cs = w.creatures;
    const int n = static_cast<int>(cs.size());
    s.population = n;
    if (n == 0) return s;

    double age = 0, energy = 0, speed = 0, glen = 0, glen2 = 0, resp = 0, osc = 0;
    double flowAlignSum = 0.0;
    int    flowAlignN   = 0;
    double predAlignSum = 0.0;
    int    predAlignN   = 0;
    const bool currentOn   = w.currentActive();
    const bool havePredator = !w.predators.empty();
    const float predPerc2   = w.cfg.perceptionRadius * w.cfg.perceptionRadius;
    for (const Creature& c : cs) {
        age    += c.age;
        energy += c.foodReserves;
        speed  += c.speed;
        const double L = static_cast<double>(c.genome.size());
        glen  += L;
        glen2 += L * L;
        resp  += c.responsiveness;
        osc   += c.oscPeriod;
        if (c.age > s.maxAge) s.maxAge = c.age;

        if (currentOn) {
            const Vec2 cur = w.currentAt(c.pos);
            const float fs = std::sqrt(cur.x * cur.x + cur.y * cur.y);
            const float vl = std::sqrt(c.vel.x * c.vel.x + c.vel.y * c.vel.y);
            // True cosine (don't assume c.vel is unit-length for fresh newborns).
            if (fs > 1e-4f && vl > 1e-4f) {
                flowAlignSum += (c.vel.x * cur.x + c.vel.y * cur.y) / (fs * vl);
                ++flowAlignN;
            }
        }

        if (havePredator) {
            // Nearest predator within this prey's perception (mirrors the sensor).
            float bestD2 = predPerc2;
            Vec2  off{0.0f, 0.0f};
            bool  seen = false;
            for (const Predator& p : w.predators) {
                const float dx = p.pos.x - c.pos.x;
                const float dy = p.pos.y - c.pos.y;
                const float d2 = dx * dx + dy * dy;
                if (d2 < bestD2) { bestD2 = d2; off = {dx, dy}; seen = true; }
            }
            if (seen) {
                const float d  = std::sqrt(bestD2);
                const float vl = std::sqrt(c.vel.x * c.vel.x + c.vel.y * c.vel.y);
                if (d > 1e-4f && vl > 1e-4f) {
                    // away-from-predator = -off; cosine of heading vs that.
                    predAlignSum += (c.vel.x * (-off.x) + c.vel.y * (-off.y)) / (d * vl);
                    ++predAlignN;
                }
            }
        }
    }

    const double invN = 1.0 / n;
    s.avgAge            = static_cast<float>(age    * invN);
    s.avgEnergy         = static_cast<float>(energy * invN);
    s.avgSpeed          = static_cast<float>(speed  * invN);
    s.avgGenomeLen      = static_cast<float>(glen   * invN);
    s.avgResponsiveness = static_cast<float>(resp   * invN);
    s.avgOscPeriod      = static_cast<float>(osc    * invN);

    const double meanL = glen * invN;
    const double varL  = glen2 * invN - meanL * meanL;
    s.genomeLenStd = static_cast<float>(std::sqrt(std::max(0.0, varL)));

    s.avgFlowAlign = (flowAlignN > 0)
        ? static_cast<float>(flowAlignSum / flowAlignN) : 0.0f;
    s.avgPredatorAlign = (predAlignN > 0)
        ? static_cast<float>(predAlignSum / predAlignN) : 0.0f;

    // Schooling instruments (sampling-time; see the WorldStats note). Neighbours
    // are taken within perception (the same radius prey sense each other through),
    // so this matches what a flocking gene could actually act on.
    //
    // Perf: a throwaway spatial hash over the CURRENT positions makes the neighbour
    // lookup ~O(n) instead of O(n^2). We CANNOT reuse World's creatureGrid_ here:
    // by the time computeStats runs (after update()), that grid is stale — it holds
    // start-of-update positions and indices into the pre-erase / pre-reseed creatures
    // vector, so its indices can be out of range or point at the wrong creature. A
    // fresh grid built from the live creatures is the only safe reuse. queryRadius
    // distance-tests internally (<= r^2), so the neighbour set is identical to the
    // earlier brute-force loop; only the summation order differs.
    {
        std::vector<Vec2> hdg(n);
        for (int k = 0; k < n; ++k) {
            const float vx = cs[k].vel.x, vy = cs[k].vel.y;
            const float vl = std::sqrt(vx * vx + vy * vy);
            hdg[k] = (vl > 1e-6f) ? Vec2{vx / vl, vy / vl} : Vec2{0.0f, 0.0f};
        }
        const float perc = w.cfg.perceptionRadius;
        SpatialGrid sgrid;
        sgrid.init(w.width, w.height, perc);
        for (int k = 0; k < n; ++k) sgrid.insert(cs[k].pos, k);
        sgrid.build();

        double    alignSum   = 0.0;
        int       alignN     = 0;
        long long neighTotal = 0;
        for (int i = 0; i < n; ++i) {
            Vec2 mh{0.0f, 0.0f};
            int  cnt = 0;
            // exact disk: dist(i,j) <= perc, visited in queryRadius order
            sgrid.forEachInRadius(cs[i].pos, perc, [&](int j, Vec2) {
                if (j == i) return;                     // the disk includes self
                mh.x += hdg[j].x; mh.y += hdg[j].y; ++cnt;
            });
            neighTotal += cnt;
            if (cnt > 0 && (hdg[i].x != 0.0f || hdg[i].y != 0.0f)) {
                const float ml = std::sqrt(mh.x * mh.x + mh.y * mh.y);
                if (ml > 1e-6f) {
                    alignSum += (hdg[i].x * mh.x + hdg[i].y * mh.y) / ml;
                    ++alignN;
                }
            }
        }
        s.avgNeighborAlign = (alignN > 0) ? static_cast<float>(alignSum / alignN) : 0.0f;
        s.avgNeighborCount = static_cast<float>(static_cast<double>(neighTotal) * invN);
    }

    computeGeneticSpread(cs, s.geneticDiversity, s.species);
    return s;
}

// --- CSV helpers --------------------------------------------------------------
// One row per sample. Header and row formatting live together so they can never
// drift out of sync. Timing and per-interval deltas come from the caller because
// they depend on sampling cadence, not on world state.

inline std::string statsCsvHeader() {
    return "step,elapsed_s,steps_per_sec,population,food,"
           "births_cum,deaths_cum,births_interval,deaths_interval,"
           "avg_age,max_age,avg_energy,avg_speed,"
           "avg_genome_len,genome_len_std,avg_responsiveness,avg_osc_period,"
           "genetic_diversity,species,flow_align,"
           "predator_pop,kills_interval,deaths_starvation,deaths_age,predator_align,"
           "neighbor_align,neighbor_count,"
           "predator_births_interval,predator_deaths_starv,predator_deaths_age,predator_avg_energy,"
           // APPENDED at the end (v0.22.0), never inserted: every existing column
           // index stays stable, so the whole historical CSV corpus keeps parsing.
           "repro_components,"
           // Appended for the same reason (v0.24.0). Cumulative, like
           // births_cum, and both subsets of it; 0 unless the mitigations are on.
           "grace_births_cum,soft_births_cum,"
           // Appended (v0.26.0): the predator floor's refills (cumulative) and
           // the live predators' mean traits and generation (instantaneous).
           "predator_reseeds_cum,predator_speed_factor,predator_budding_factor,predator_generation";
}

inline std::string statsCsvRow(const WorldStats& s,
                               double elapsedSeconds,
                               double stepsPerSec,
                               int birthsInterval,
                               int deathsInterval,
                               int killsInterval,
                               int starvationInterval,
                               int ageInterval,
                               int predBirthsInterval,
                               int predStarvInterval,
                               int predAgeInterval) {
    std::ostringstream o;
    o << std::fixed << std::setprecision(3);
    o << s.frame << ','
      << elapsedSeconds << ','
      << stepsPerSec << ','
      << s.population << ','
      << s.food << ','
      << s.totalBirths << ','
      << s.totalDeaths << ','
      << birthsInterval << ','
      << deathsInterval << ','
      << s.avgAge << ','
      << s.maxAge << ','
      << s.avgEnergy << ','
      << s.avgSpeed << ','
      << s.avgGenomeLen << ','
      << s.genomeLenStd << ','
      << s.avgResponsiveness << ','
      << s.avgOscPeriod << ','
      << s.geneticDiversity << ','
      << s.species << ','
      << s.avgFlowAlign << ','
      << s.predatorPop << ','
      << killsInterval << ','
      << starvationInterval << ','
      << ageInterval << ','
      << s.avgPredatorAlign << ','
      << s.avgNeighborAlign << ','
      << s.avgNeighborCount << ','
      << predBirthsInterval << ','
      << predStarvInterval << ','
      << predAgeInterval << ','
      << s.predatorAvgEnergy << ','
      << s.reproComponents << ','   // appended (v0.22.0) — see the header note
      << s.totalGraceBirths << ','  // appended (v0.24.0) — likewise
      << s.totalSoftBirths << ','
      << s.totalPredatorReseeds << ','   // appended (v0.26.0) — likewise
      << s.predatorSpeedFactor << ','
      << s.predatorBuddingFactor << ','
      << s.predatorGeneration;
    return o.str();
}

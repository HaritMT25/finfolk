#pragma once
// ----------------------------------------------------------------------------
// world_common — the part of a World that does not depend on its geometry: the
// config, the frame counter, the birth/death counters, the death-cluster map
// and pairing-graph records, the id counter and the phase profiler, plus the
// bookkeeping that writes them when a creature dies, is born or is founded.
//
// World derives from WorldCommon, so every member keeps its name
// (world.totalBirths, world.cfg, World::BirthRecord) and no caller changes.
// None of this draws a random number or touches the simulation's floats —
// except the Stage C predator stream (predRng_), which only a world with
// cfg.predatorBrain on ever draws from.
// ----------------------------------------------------------------------------
#include <vector>
#include <cstdio>
#include <cstddef>
#include <cstdint>
#include "vec2.hpp"
#include "agent_core.hpp"
#include "config.hpp"
#include "cluster_projection.hpp"
#include "kernel.hpp"
#include "predator.hpp"
#include "random.hpp"
#include "repro_graph.hpp"

struct WorldCommon {
    unsigned long long frame = 0;
    int births = 0;          // this-frame only; reset every update()
    int deaths = 0;          // this-frame only; reset every update()
    long long totalBirths = 0;  // cumulative over the whole run (never reset)
    long long totalDeaths = 0;  // cumulative over the whole run (never reset)

    // Attribution for the two match-distance mitigations (v0.24.0), cumulative
    // and both <= totalBirths. Without them a rescued population cannot be
    // attributed to grace vs the soft ramp, and that attribution is the whole
    // point of running the mitigation sweep. Both stay 0 on every run with the
    // knobs off, including a hard-gated one.
    //   totalGraceBirths: the gate was bypassed because a partner was a young
    //     founder (see reproGraced).
    //   totalSoftBirths:  the soft draw admitted a pair the HARD gate at the
    //     same threshold would have refused (dsq > T*T). A pair inside T that
    //     the soft draw happened to accept is not counted — it needed no help.
    long long totalGraceBirths = 0;
    long long totalSoftBirths  = 0;

    // Cumulative deaths split by cause (sum == totalDeaths). "prey deaths up" is
    // meaningless until you know which kind, so the logger differences these into
    // per-interval predation / starvation / age columns.
    long long totalDeathsPredation  = 0;
    long long totalDeathsStarvation = 0;
    long long totalDeathsAge        = 0;

    // Predator economy bookkeeping (Stage B). Cumulative over the run; the logger
    // differences them into per-interval columns, exactly like the prey deaths.
    // Births and the two death causes are tracked separately so a predator crash
    // can be diagnosed (starved out vs aged out) and recovery (births) watched.
    // All stay 0 in Stage A (cfg.predatorEconomy == false).
    long long totalPredatorBirths           = 0;
    long long totalPredatorDeathsStarvation = 0;
    long long totalPredatorDeathsAge        = 0;
    // Predators the floor added (cfg.predatorMinPopulation, v0.26.0). Not
    // births: kept apart so a population the floor holds up can be told from
    // one that breeds. 0 unless the floor is on.
    long long totalPredatorReseeds          = 0;

    // Death-cluster map (cfg.clusterMap). One point per creature death: the 2-D
    // projection of its network plus the death ordinal (so colour can band by
    // epoch) and a few attributes. (x, y are map coordinates of the genome, not
    // a position in the world, so they stay 2-D whatever shape the world has.) Memory is bounded to cfg.clusterMax by uniform
    // decimation (when full, drop every other kept point and double the stride),
    // which keeps an evenly-spaced sample across the whole run. Empty / untouched
    // unless cfg.clusterMap is on, so default runs are unaffected.
    struct DeathRecord {
        float x = 0.0f, y = 0.0f;   // fixed 2-D projection (the non-PCA map point)
        float sketch[CLUSTER_SKETCH_DIM] = {};  // K-dim sketch, for end-of-run PCA
        long long index = 0;        // death ordinal over the run (0-based)
        std::uint64_t lineageId = 0;
        float age = 0.0f;           // age at death
        int genomeLen = 0;
        char cause = '?';           // 'p' predation, 's' starvation, 'a' age
    };
    std::vector<DeathRecord> deathLog;
    long long totalDeathsLogged_ = 0;   // every death seen (not just kept)
    long long clusterStride_     = 1;   // keep a death iff (ordinal % stride == 0)

    // ---- Pairing graph (see repro_graph.hpp for what it measures) ----
    // Two structures, because the archive and the metric want opposite things.
    //
    // birthLog is the archival event log written to <stem>.births.csv: bounded
    // and uniformly DECIMATED exactly like deathLog, so a million-step run stays
    // in memory. Only populated when cfg.reproLog.
    //
    // reproWindow_ is the metric's data source: the last cfg.reproWindow pairs,
    // UNDECIMATED, in a fixed-capacity ring. Decimation would be actively
    // wrong here — dropping edges fragments a connected graph and would inflate
    // the component count, which is the very thing being measured. Always
    // maintained (two integer writes per event, no rng, no floats, not
    // serialized), so the CSV column means the same thing in every run rather
    // than being silently empty unless a flag was remembered.
    struct BirthRecord {
        long long index = 0;                     // event ordinal over the run (0-based)
        std::uint64_t parent1 = 0, parent2 = 0;  // AgentCore::id of each of the pair
        std::uint64_t lineage1 = 0, lineage2 = 0;
        unsigned long long frame = 0;
    };
    std::vector<BirthRecord> birthLog;
    long long totalBirthsLogged_ = 0;   // every event seen (not just kept)
    long long reproStride_       = 1;   // keep an event iff (ordinal % stride == 0)

    std::vector<repro::Edge> reproWindow_;
    std::size_t reproWindowNext_ = 0;   // ring cursor

    // Stable identity counter (see AgentCore::id). Assigned single-threaded at
    // every creation site, so it never touches the parallel phase or the global
    // rng — the simulation stays byte-for-byte and deterministic regardless of
    // ids.
    std::uint64_t nextId_ = 1;

    // ---- Stage C: the predator brains (cfg.predatorBrain; predator_brain.hpp) ----
    // All of this stays at its default while the brain is off: nothing draws
    // from predRng_, no id is handed out, nothing is logged or tallied, and no
    // checkpoint or CSV mentions any of it.
    //
    // predRng_: the predators' own random stream — founders' genomes, bud
    // mutations and the RANDOM input. Used only in the single-threaded predator
    // phase. Seeded from ONE draw of the global rng at the end of World::init
    // (so a --seed fixes it, and the prey, predator and food draws before it
    // are exactly Stage B's), reseeded the same way by reseedStreams, and
    // carried by brain checkpoints (predatorRngState).
    RandomGen predRng_{5489u};
    // Predator ids: their own namespace (the prey's nextId_ is untouched), 1-based.
    std::uint64_t nextPredatorId_ = 1;

    // The lineage log (cfg.predatorLog): one record per founding (F: initial
    // spawn, R: floor refill), bud (B) and death (S: starved, A: aged), plus,
    // at the start of a run that did not come from init(), one record per live
    // predator: L (loaded from a checkpoint) or T (transplanted: the first run
    // of an arena; `source` = its id in the source checkpoint). Drained by the
    // headless runner at every sample and before every checkpoint write, never
    // decimated. Not world state.
    struct PredatorEvent {
        unsigned long long frame = 0;
        char event = '?';
        std::uint64_t id = 0, parent = 0, lineage = 0;
        std::uint32_t generation = 0;
        float age = 0.0f;
        std::uint32_t captures = 0;
        float energy = 0.0f;
        int genomeLen = 0;
        float speedFactor = 1.0f, buddingFactor = 1.0f;
        std::uint64_t source = 0;
    };
    std::vector<PredatorEvent> predLog_;

    // Set by the transplant on the arena it builds (written to the arena file
    // as world.arena = true) and cleared once the arena's first run has logged
    // its T rows, so only the arena file itself carries it.
    bool arenaFresh_ = false;

    // Per-interval sums for <stem>.predators.csv (predator_stats.hpp), reset at
    // each sample. Diagnostics only: nothing in the step reads them back.
    struct PredatorTally {
        long long predSteps = 0;      // predator-steps
        long long pursuitSteps = 0;   // ... with a prey within perception
        long long topSteps = 0;       // ... at >= 95 % of top speed
        long long captures = 0;
        double alignSum = 0.0;        // PREY_FWD over pursuit steps (cos heading vs bearing)
        double speedSum = 0.0, speedSqSum = 0.0;
        long long deaths = 0;         // predators that died (starved or aged)
        double deathCaptures = 0.0, deathAge = 0.0;
    };
    PredatorTally predTally_;

    void notePredator(char event, const Predator& p) {
        if (event == 'S' || event == 'A') {
            ++predTally_.deaths;
            predTally_.deathCaptures += p.captures;
            predTally_.deathAge += p.age;
        }
        if (!cfg.predatorLog) return;
        PredatorEvent e;
        e.frame = frame; e.event = event;
        e.id = p.id; e.parent = p.parentId; e.lineage = p.lineageId;
        e.generation = p.generation; e.age = p.age; e.captures = p.captures; e.energy = p.energy;
        e.genomeLen = (int)p.genome.size();
        e.speedFactor = p.speedFactor; e.buddingFactor = p.buddingFactor;
        e.source = (event == 'T') ? p.sourceId : 0;
        predLog_.push_back(e);
    }

    // A run that starts from a checkpoint: one L row (or T, for an arena's
    // first run) per live predator, so the log segment is self-contained.
    // Stitching: keep the earlier segment's rows with frame <= this frame, then
    // this segment's rows without its L rows.
    template <class Predators>
    void notePredatorsAtStart(const Predators& ps, char event) {
        for (const auto& p : ps) notePredator(event, p);
    }

    // Seed the run's streams from S: the global rng, then (brain on) the
    // predators' from one draw of it — the rule World::init follows. Used by
    // --reseed-after-load; with the brain off it is exactly rng.seed(S).
    void reseedStreams(unsigned s) {
        rng.seed(s);
        if (cfg.predatorBrain) predRng_.seed(rng.uint());
    }

    // ---- Phase profiler (cfg.profile). Accumulates wall-time per phase plus a
    // CPU-time split inside the parallel loop (gather vs feedForward vs apply,
    // summed over threads). Zero cost when off (no clock calls). buildNs/parWallNs/
    // serialNs are WALL time and sum to ~the step; gather/ff/apply are thread-summed
    // CPU time, so on T threads they total ~T * parWallNs — read them as a ratio.
    struct PhaseProfile {
        double buildNs = 0, parWallNs = 0, serialNs = 0, totalNs = 0;
        double gatherNs = 0, ffNs = 0, applyNs = 0;   // thread-summed, within parallel
        long long steps = 0;
    } prof;

    void dumpProfile() const {
        if (prof.steps == 0) { std::printf("(no profiled steps)\n"); return; }
        const double s = (double)prof.steps, us = 1e-3;
        const double step = prof.totalNs / s * us;
        auto pct = [&](double ns){ return prof.totalNs > 0 ? 100.0 * ns / prof.totalNs : 0.0; };
        const double parCpu = prof.gatherNs + prof.ffNs + prof.applyNs;
        auto cpu = [&](double ns){ return parCpu > 0 ? 100.0 * ns / parCpu : 0.0; };
        std::printf("=== phase profile over %lld steps (%.3f ms/step avg) ===\n", prof.steps, step);
        std::printf("  build        %7.3f us/step  (%4.1f%% wall)\n", prof.buildNs / s * us, pct(prof.buildNs));
        std::printf("  parallel     %7.3f us/step  (%4.1f%% wall)\n", prof.parWallNs / s * us, pct(prof.parWallNs));
        std::printf("  serial       %7.3f us/step  (%4.1f%% wall)\n", prof.serialNs / s * us, pct(prof.serialNs));
        std::printf("  -- inside parallel (thread-summed CPU, share of parallel work) --\n");
        std::printf("     sensor-gather %5.1f%%   feedForward %5.1f%%   apply/metab %5.1f%%\n",
                    cpu(prof.gatherNs), cpu(prof.ffNs), cpu(prof.applyNs));
    }

    // See kernel::reproGraced. Kept as a static member so callers and tests can
    // keep asking World::reproGraced.
    static bool reproGraced(const AgentCore& c, float gracePeriod) {
        return kernel::reproGraced(c, gracePeriod);
    }

    // A spawned or reseeded creature starts its own line: a fresh id, and a
    // lineageId equal to it (which is what makes kernel::reproGraced see it as
    // a founder).
    void markFounder(AgentCore& c) {
        c.id = nextId_++;
        c.lineageId = c.id;   // a new founder line
    }

    // Record one death into the cluster map (no-op unless cfg.clusterMap). Called
    // from the single-threaded death paths, so it is deterministic and thread-safe.
    void logDeath(const AgentCore& c, char cause) {
        if (!cfg.clusterMap) return;
        const long long ordinal = totalDeathsLogged_++;
        if (ordinal % clusterStride_ != 0) return;          // decimated out
        DeathRecord rec;
        clusterSketch(c.genome, rec.sketch);                 // K-dim, for optional PCA
        const Vec2 p = sketchTo2D(rec.sketch);               // fixed 2-D map point
        rec.x = p.x; rec.y = p.y;
        rec.index = ordinal; rec.lineageId = c.lineageId;
        rec.age = c.age; rec.genomeLen = (int)c.genome.size(); rec.cause = cause;
        deathLog.push_back(rec);
        if (cfg.clusterMax > 0 && (int)deathLog.size() >= 2 * cfg.clusterMax) {
            // Halve: keep every other kept point, then require twice the spacing.
            const long long newStride = clusterStride_ * 2;
            std::vector<DeathRecord> kept;
            kept.reserve(deathLog.size() / 2 + 1);
            for (const DeathRecord& d : deathLog)
                if (d.index % newStride == 0) kept.push_back(d);
            deathLog.swap(kept);
            clusterStride_ = newStride;
        }
    }

    // A creature dies: mark it, count it by cause ('p' predation, 's'
    // starvation, 'a' age — the same codes the cluster map stores) and log it.
    // Single-threaded, like every death path. The three cause counters must sum
    // to totalDeaths, so a world that adds a cause adds its counter here too;
    // anything that is not 'p' or 's' is counted as age.
    void recordDeath(AgentCore& c, char cause) {
        c.alive = false;
        deaths++; totalDeaths++;
        if (cause == 'p')      totalDeathsPredation++;
        else if (cause == 's') totalDeathsStarvation++;
        else                   totalDeathsAge++;
        logDeath(c, cause);
    }

    // Record one pairing event into the pairing graph. Called through
    // recordPairing on a world's insertion path, which runs in the
    // single-threaded phase — so this is deterministic and thread-safe for the
    // same reason logDeath is. Draws no random numbers and touches no
    // simulation state.
    void logBirth(const AgentCore& c1, const AgentCore& c2) {
        // The metric window is always maintained; only the archive is opt-in.
        const int cap = cfg.reproWindow > 0 ? cfg.reproWindow : 0;
        if (cap > 0) {
            // Guard, unreachable today (cfg is fixed before init() and a load
            // builds a fresh World): if reproWindow ever shrinks on a live
            // World, over-cap edges must not sit in the ring forever.
            if ((int)reproWindow_.size() > cap) {
                reproWindow_.resize((std::size_t)cap);
                reproWindowNext_ = 0;
            }
            const repro::Edge e{c1.id, c2.id};
            if ((int)reproWindow_.size() < cap) {
                reproWindow_.push_back(e);
            } else {
                reproWindow_[reproWindowNext_] = e;
                reproWindowNext_ = (reproWindowNext_ + 1) % (std::size_t)cap;
            }
        }

        if (!cfg.reproLog) return;
        const long long ordinal = totalBirthsLogged_++;
        if (ordinal % reproStride_ != 0) return;            // decimated out
        BirthRecord rec;
        rec.index = ordinal;
        rec.parent1 = c1.id;       rec.parent2 = c2.id;
        rec.lineage1 = c1.lineageId; rec.lineage2 = c2.lineageId;
        rec.frame = frame;
        birthLog.push_back(rec);
        if (cfg.reproLogMax > 0 && (int)birthLog.size() >= 2 * cfg.reproLogMax) {
            // Halve: keep every other kept record, then require twice the spacing.
            const long long newStride = reproStride_ * 2;
            std::vector<BirthRecord> kept;
            kept.reserve(birthLog.size() / 2 + 1);
            for (const BirthRecord& b : birthLog)
                if (b.index % newStride == 0) kept.push_back(b);
            birthLog.swap(kept);
            reproStride_ = newStride;
        }
    }

    // An insertion happened: count it (with its grace/soft attribution) and log
    // the pair. Runs after kernel::inheritFromPair, so the body draws come
    // before logBirth, as they always have.
    void recordPairing(const AgentCore& c1, const AgentCore& c2, bool viaGrace, bool viaSoft) {
        births++;
        totalBirths++;
        if (viaGrace) totalGraceBirths++;
        if (viaSoft)  totalSoftBirths++;
        logBirth(c1, c2);
    }

    // Connected components of the pairing graph over the trailing window,
    // counting only components with at least cfg.reproMinCluster members.
    int reproComponents() const {
        return repro::componentCount(reproWindow_, cfg.reproMinCluster);
    }

    // Runtime-tunable parameters (see SimConfig). Set World::cfg before init().
    SimConfig cfg;
};

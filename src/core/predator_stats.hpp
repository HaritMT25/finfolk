#pragma once
// ----------------------------------------------------------------------------
// predator_stats — Stage C's per-interval readout, <stem>.predators.csv, plus
// the predator wiring fractions (<stem>.pwiring.csv) and the lineage log rows
// (<stem>.predlog.csv). Written by the headless runner only with the brain on;
// the main CSV is untouched, so its schema is the same in every run.
//
// Everything here reads the world (and resets WorldCommon::predTally_, the
// per-interval sums the step accumulates); nothing draws or feeds back into
// the simulation.
// ----------------------------------------------------------------------------
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <string>
#include <vector>
#include "predator_brain.hpp"
#include "world.hpp"

namespace predstats {

struct Last {   // cumulative counters at the previous sample
    long long births = 0, starv = 0, age = 0, reseeds = 0;
};

struct Row {
    int pop = 0;
    int preyPop = 0;
    long long births = 0, deathsStarv = 0, deathsAge = 0, reseeds = 0;   // this interval
    long long captures = 0;
    double capturesPerPredS = 0, pursuitFrac = 0, capturesPerPursuitS = 0, pursuitAlign = 0;
    double speedMean = 0, speedCv = 0, topSpeedFrac = 0;
    double energyMean = 0, ageMean = 0, genMean = 0;
    long long genMax = 0;
    int lineages = 0;
    double genomeLenMean = 0, genomeDistMean = 0;
    double wirePrey = 0, wireRival = 0, wireSignal = 0, wireOwn = 0;
    long long deaths = 0;
    double lifeCapturesMean = 0, lifeAgeMean = 0;
};

inline std::string header() {
    return "step,predator_pop,prey_pop,births_interval,deaths_starv_interval,deaths_age_interval,"
           "reseeds_interval,captures_interval,captures_per_pred_s,pursuit_frac,captures_per_pursuit_s,"
           "pursuit_align,speed_mean,speed_cv,top_speed_frac,energy_mean,age_mean,gen_mean,gen_max,"
           "lineages_alive,genome_len_mean,genome_dist_mean,wire_prey,wire_rival,wire_signal,wire_own,"
           "deaths_interval,life_captures_mean,life_age_mean";
}

// A predator's genome folded onto its decoded (source, sink) cells, in the
// network's own index spaces: the predator analogue of isolation.hpp's fold
// (which decodes with the prey's sizes). Dense, NUM_PRED_SRC x NUM_PRED_SINK.
inline constexpr int kSrc = NUM_PRED_SENSES + MAX_INTERNAL_NEURONS;
inline constexpr int kSink = NUM_PRED_ACTIONS + MAX_INTERNAL_NEURONS;
inline void fold(const NeuralNet& nnet, float out[kSrc * kSink]) {
    for (int i = 0; i < kSrc * kSink; ++i) out[i] = 0.0f;
    for (const auto& fc : nnet.flat) out[fc.src() * kSink + fc.sink()] += fc.w();
}

// Compute this interval's row and reset the tally. dt is the step length.
inline Row sample(World& w, float dt, Last& last) {
    Row r;
    const auto& ps = w.predators;
    r.pop = (int)ps.size();
    r.preyPop = (int)w.creatures.size();
    r.births = w.totalPredatorBirths - last.births;
    r.deathsStarv = w.totalPredatorDeathsStarvation - last.starv;
    r.deathsAge = w.totalPredatorDeathsAge - last.age;
    r.reseeds = w.totalPredatorReseeds - last.reseeds;
    last.births = w.totalPredatorBirths; last.starv = w.totalPredatorDeathsStarvation;
    last.age = w.totalPredatorDeathsAge; last.reseeds = w.totalPredatorReseeds;

    const WorldCommon::PredatorTally& t = w.predTally_;
    r.captures = t.captures;
    if (t.predSteps > 0) {
        r.capturesPerPredS = (double)t.captures / ((double)t.predSteps * dt);
        r.pursuitFrac = (double)t.pursuitSteps / (double)t.predSteps;
        r.speedMean = t.speedSum / (double)t.predSteps;
        const double var = std::max(0.0, t.speedSqSum / (double)t.predSteps - r.speedMean * r.speedMean);
        r.speedCv = (r.speedMean > 0) ? std::sqrt(var) / r.speedMean : 0.0;
        r.topSpeedFrac = (double)t.topSteps / (double)t.predSteps;
    }
    if (t.pursuitSteps > 0) {
        r.capturesPerPursuitS = (double)t.captures / ((double)t.pursuitSteps * dt);
        r.pursuitAlign = t.alignSum / (double)t.pursuitSteps;
    }
    r.deaths = t.deaths;
    if (t.deaths > 0) {
        r.lifeCapturesMean = t.deathCaptures / (double)t.deaths;
        r.lifeAgeMean = t.deathAge / (double)t.deaths;
    }
    w.predTally_ = WorldCommon::PredatorTally{};

    if (!ps.empty()) {
        double e = 0, a = 0, g = 0, gl = 0;
        long long wp = 0, wr = 0, ws = 0, wo = 0;
        std::vector<std::uint64_t> lineages;
        lineages.reserve(ps.size());
        for (const Predator& p : ps) {
            e += p.energy; a += p.age; g += p.generation; gl += (double)p.genome.size();
            r.genMax = std::max<long long>(r.genMax, p.generation);
            lineages.push_back(p.lineageId);
            bool used[NUM_PRED_SENSES];
            predbrain::usedSensors(p.nnet, used);
            bool prey = false, rival = false, sig = false, own = false;
            for (int s = PS_PREY_FWD; s <= PS_PREY_CENTROID_LR; ++s) prey |= used[s];
            for (int s = PS_RIVAL_FWD; s <= PS_RIVAL_PROX; ++s) rival |= used[s];
            for (int s = PS_SIGNAL; s <= PS_SIGNAL_LR; ++s) sig |= used[s];
            for (int s = PS_ENERGY; s <= PS_AGE; ++s) own |= used[s];
            wp += prey; wr += rival; ws += sig; wo += own;
        }
        const double n = (double)ps.size();
        r.energyMean = e / n; r.ageMean = a / n; r.genMean = g / n; r.genomeLenMean = gl / n;
        r.wirePrey = wp / n; r.wireRival = wr / n; r.wireSignal = ws / n; r.wireOwn = wo / n;
        std::sort(lineages.begin(), lineages.end());
        r.lineages = (int)(std::unique(lineages.begin(), lineages.end()) - lineages.begin());

        // Mean pairwise L2 distance of the folded networks, over the first 64
        // predators in vector order (deterministic; O(64^2) at a sample).
        const int m = std::min<int>((int)ps.size(), 64);
        if (m >= 2) {
            std::vector<float> folds((size_t)m * kSrc * kSink);
            for (int i = 0; i < m; ++i) fold(ps[(size_t)i].nnet, &folds[(size_t)i * kSrc * kSink]);
            double sum = 0; long long pairs = 0;
            for (int i = 0; i < m; ++i)
                for (int j = i + 1; j < m; ++j) {
                    const float* x = &folds[(size_t)i * kSrc * kSink];
                    const float* y = &folds[(size_t)j * kSrc * kSink];
                    double d2 = 0;
                    for (int k = 0; k < kSrc * kSink; ++k) { const double d = (double)x[k] - y[k]; d2 += d * d; }
                    sum += std::sqrt(d2); ++pairs;
                }
            r.genomeDistMean = sum / (double)pairs;
        }
    }
    return r;
}

inline std::string row(int step, const Row& r) {
    char buf[1024];
    std::snprintf(buf, sizeof buf,
                  "%d,%d,%d,%lld,%lld,%lld,%lld,%lld,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%lld,"
                  "%d,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%lld,%.6g,%.6g",
                  step, r.pop, r.preyPop, r.births, r.deathsStarv, r.deathsAge, r.reseeds, r.captures,
                  r.capturesPerPredS, r.pursuitFrac, r.capturesPerPursuitS, r.pursuitAlign, r.speedMean,
                  r.speedCv, r.topSpeedFrac, r.energyMean, r.ageMean, r.genMean, r.genMax, r.lineages,
                  r.genomeLenMean, r.genomeDistMean, r.wirePrey, r.wireRival, r.wireSignal, r.wireOwn,
                  r.deaths, r.lifeCapturesMean, r.lifeAgeMean);
    return buf;
}

// <stem>.pwiring.csv: per predator input, the fraction of predators wiring it.
inline std::string wiringHeader() {
    std::string h = "step";
    for (int s = 0; s < NUM_PRED_SENSES; ++s) { h += ','; h += kPredSenseNames[s]; }
    return h;
}
inline std::string wiringRow(int step, const World& w) {
    long counts[NUM_PRED_SENSES] = {};
    for (const Predator& p : w.predators) {
        bool used[NUM_PRED_SENSES];
        predbrain::usedSensors(p.nnet, used);
        for (int s = 0; s < NUM_PRED_SENSES; ++s) counts[s] += used[s];
    }
    std::string out = std::to_string(step);
    char buf[32];
    for (int s = 0; s < NUM_PRED_SENSES; ++s) {
        std::snprintf(buf, sizeof buf, ",%.6g",
                      w.predators.empty() ? 0.0 : (double)counts[s] / (double)w.predators.size());
        out += buf;
    }
    return out;
}

// <stem>.predlog.csv: the lineage log (cfg.predatorLog), drained at each call.
// Events: F founder (init), R floor refill, B bud, S starved, A aged; and at the
// start of a segment that began from a checkpoint, L (loaded) or T
// (transplanted; `source` = its id in the source checkpoint, another id
// namespace) for every live predator.
inline std::string logHeader() {
    return "frame,event,id,parent,lineage,generation,age,captures,energy,genome_len,speed_factor,budding_factor,source";
}
inline std::string logRow(const WorldCommon::PredatorEvent& e) {
    char buf[320];
    std::snprintf(buf, sizeof buf, "%llu,%c,%llu,%llu,%llu,%u,%.6g,%u,%.6g,%d,%.6g,%.6g,%llu",
                  e.frame, e.event, (unsigned long long)e.id, (unsigned long long)e.parent,
                  (unsigned long long)e.lineage, (unsigned)e.generation, (double)e.age,
                  (unsigned)e.captures, (double)e.energy, e.genomeLen, (double)e.speedFactor,
                  (double)e.buddingFactor, (unsigned long long)e.source);
    return buf;
}
inline std::size_t drainLog(World& w, std::FILE* f) {
    const std::size_t n = w.predLog_.size();
    for (const auto& e : w.predLog_) std::fprintf(f, "%s\n", logRow(e).c_str());
    w.predLog_.clear();
    return n;
}

}  // namespace predstats

// evo_wasm.cpp — C ABI shim: the browser-facing surface of evo_core.
//
// Compiled with Emscripten into web/evo_boids.{js,wasm} (see build_wasm.sh).
// The JS renderer (web/renderer.js) drives it: init(seed, config) once, then
// per animation frame step(n) -> sync() -> read the packed buffers.
//
// Determinism contract: single-threaded (no USE_OPENMP), -ffp-contract=off,
// fixed dt 0.016f per step — under those, this module reproduces the native
// serial build bit for bit (proven by wasm/parity.sh; the checkpoint JSON is
// the oracle). step() takes a STEP COUNT, never wall-clock time.
//
// The same source also builds the threaded module (EVO_POOL_THREADS, see
// wasm/wasm.cmake): identical API, but the per-creature phase runs on a thread
// pool, so a run is NOT reproducible — the single-threaded module stays the
// reference.
//
// Buffer lifetime: getters return pointers into buffers repacked by
// evo_sync(); pointers are valid until the next evo_sync/evo_init call, and
// wasm memory growth can move the heap — JS must re-create typed-array views
// after every sync and never cache them.
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cmath>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "core/world.hpp"
#include "core/checkpoint_io.hpp"
#include "core/isolation.hpp"
#include "core/random.hpp"
#include "core/stats.hpp"
#include "core/wiring_log.hpp"

#ifdef __EMSCRIPTEN__
#include <emscripten.h>
#define EVO_EXPORT extern "C" EMSCRIPTEN_KEEPALIVE
#else
#define EVO_EXPORT extern "C"  // native build of the shim, for smoke tests
#endif

#ifndef EVO_VERSION
#define EVO_VERSION "dev"
#endif

namespace {

World* g_world = nullptr;
std::string g_error;
std::string g_checkpoint;
std::string g_defaultConfig;

std::vector<float>   g_segments;   // N*12: 6 body segments x,y
std::vector<float>   g_bodyParams; // N*2: bodySize, bodyElong
std::vector<uint8_t> g_colors;     // N*3
std::vector<double>  g_ids;        // N
std::vector<float>   g_food;       // F*2
std::vector<float>   g_predators;  // P*3: x, y, digestTimer
std::vector<float>   g_current;    // cols*rows*2
// evo_stats() layout — web/renderer.js reads STATS_LEN of them; change both:
// 0 creatures, 1 food, 2 predators, 3 frame, 4 births (last step), 5 deaths
// (last step), 6 total births, 7 total deaths, 8 mean genome length,
// 9 mean generation, 10 max generation
constexpr int kStatsLen = 11;
double g_stats[kStatsLen] = {};
int g_currentCols = 0, g_currentRows = 0;

// The last successful evo_init arguments, so evo_reset() can replay them.
struct InitArgs {
    unsigned seed = 0;
    int width = 0, height = 0, population = 0;
    std::string cfgJson;
    bool valid = false;
} g_lastInit;

constexpr int kCurrentStep = 64;   // overlay lattice pitch, mirrors SfmlRenderer

// ---- Fish colour: by family line or by brain -------------------------------
// Display only: nothing here touches World, so a run and its checkpoints are
// the same in either mode. g_colors is what every renderer draws a fish in.
//   0 = by brain: Creature::color, the genome's frozen projection
//       (genome_color.hpp) — similar brains look alike; the default here, so
//       the shim's output is what it always was unless the page asks.
//   1 = by family: one stable colour per lineageId (familyColor below); the
//       the page's default (2026-10-23).
int g_colourMode = 0;

// A family line's colour, from its id alone: a 32-bit hash picks a hue (6 x 256
// steps) and one of 4 tones, then HSV -> RGB in integers, so the same id gives
// the same bytes in every build and the dashboards (evo_family_color) can draw a
// line in the colour its fish have. Neighbouring ids — the founders are
// consecutive — land on unrelated hues. Hues within ~20 degrees of pure red
// are skipped: the flat view draws predators as red circles.
void familyColor(std::uint64_t id, std::uint8_t* out) {
    std::uint32_t h = (std::uint32_t)(id ^ (id >> 32));
    h ^= h >> 16; h *= 0x7feb352dU; h ^= h >> 15; h *= 0x846ca68bU; h ^= h >> 16;
    static const int kSat[4] = {200, 165, 225, 185}, kVal[4] = {240, 215, 195, 255};
    const int tone = (int)((h >> 12) & 3u);
    const int s = kSat[tone], v = kVal[tone];
    constexpr int kRedGap = 85;   // of 1536 hue steps, either side of red
    const int hue = kRedGap + (int)(h % (1536u - 2 * kRedGap)), sector = hue >> 8, f = hue & 255;
    const int p = v * (255 - s) / 255;
    const int q = v * (65025 - s * f) / 65025;
    const int t = v * (65025 - s * (255 - f)) / 65025;
    int r, g, b;
    switch (sector) {
        case 0: r = v; g = t; b = p; break;
        case 1: r = q; g = v; b = p; break;
        case 2: r = p; g = v; b = t; break;
        case 3: r = p; g = q; b = v; break;
        case 4: r = t; g = p; b = v; break;
        default: r = v; g = p; b = q; break;
    }
    out[0] = (std::uint8_t)r; out[1] = (std::uint8_t)g; out[2] = (std::uint8_t)b;
}

// The same defensive clamps main.cpp applies before init.
void clampConfig(SimConfig& c) {
    if (c.minSpeed > c.maxSpeed) std::swap(c.minSpeed, c.maxSpeed);
    if (c.genomeMinLength > c.genomeMaxLength) std::swap(c.genomeMinLength, c.genomeMaxLength);
    if (c.genomeInitMin > c.genomeInitMax) std::swap(c.genomeInitMin, c.genomeInitMax);
    if (c.perceptionRadius < 1.0f) c.perceptionRadius = 1.0f;
    if (c.maxNeighbors < 0) c.maxNeighbors = 0;
    if (c.maxNeighbors > MAX_TOPOLOGICAL_NEIGHBORS)
        c.maxNeighbors = MAX_TOPOLOGICAL_NEIGHBORS;
    // The predator floor refills every step, so a page-supplied value must not
    // be able to ask for millions of predators. Negative means off, as 0 does.
    if (c.predatorMinPopulation < 0) c.predatorMinPopulation = 0;
    if (c.predatorMinPopulation > 2000) c.predatorMinPopulation = 2000;
    if (c.predatorMaxPopulation < 0) c.predatorMaxPopulation = 0;
}

// ---- Dashboard recorder ------------------------------------------------------
// What the page's dashboards (web/dashboard.js) chart. Read-only by contract: it
// reads the world between steps, draws no random numbers and writes nothing the
// simulation reads, so a run is the same bit for bit with or without it. It
// lives here rather than in JS because only the step loop sees every step:
// samples land on the same simulated-time grid at any speed and in Turbo, and
// each newborn's id can be paired with its sources.
//
// Three streams, appended in step order; the page empties them with
// evo_rec_take() and reads the copies:
//   samples  one row of kRecLen doubles every `every` frames (frame % every == 0)
//   births   one row per newborn: id, first source, second source, lineageId,
//            frame. The first source is the parent whose lineageId it carries.
//   changes  one row per id entering or leaving the live set without a birth:
//            kind (1 = left: death, predation or the governor's cull; 2 = joined:
//            a founder, or a live creature of unknown origin after a reset),
//            id, lineageId (0 when it left), frame.
// Leaving is detected by comparing the live ids at each sample (and at
// evo_rec_flush) with the previous ones, so a death is dated to the next sample.
//
// Newborn ids: World::update assigns them consecutively from nextId_ right
// after the step's pass (world.hpp, `baby.id = nextId_++`), in the same order
// logBirth pushes their source pairs into reproWindow_; reseeded founders come
// after. So a step with B births made ids nextId_..nextId_+B-1, and their pairs
// are the ring's last B edges. That holds while reproWindow >= B (default 2000;
// a step has a handful); otherwise the sources are written as 0 (unknown).
//
// Sample row layout (web/dash_data.js names the columns; change both):
constexpr int kRecTopLines = 24;   // lineages reported per sample, largest first
constexpr int kRecQ = 5;           // quantiles: 10, 25, 50, 75, 90 %
enum RecCol {
    RC_FRAME, RC_POP, RC_FOOD, RC_PRED,
    RC_BIRTHS, RC_DEATHS, RC_KILLS, RC_STARVED, RC_AGED,          // cumulative
    RC_AVG_AGE, RC_MAX_AGE, RC_AVG_ENERGY, RC_AVG_SPEED,
    RC_AVG_GLEN, RC_GLEN_STD, RC_DIVERSITY,
    RC_FLOW_ALIGN, RC_PRED_ALIGN, RC_NEIGH_ALIGN, RC_NEIGH_COUNT,
    RC_PRED_BIRTHS, RC_PRED_STARVED, RC_PRED_AGED, RC_PRED_ENERGY,  // births/deaths cumulative
    RC_COMPONENTS, RC_GEN_MEAN, RC_GEN_MAX, RC_LINES,
    RC_BODY_SIZE, RC_BODY_ELONG, RC_CURRENT, RC_CULLED,
    // v0.26.0: the predator floor's refills (cumulative) and the live
    // predators' mean speed / budding traits and generation (0 with none alive)
    RC_PRED_RESEEDS, RC_PRED_SPEED, RC_PRED_BUDDING, RC_PRED_GEN,
    RC_Q_SPEED, RC_Q_GLEN = RC_Q_SPEED + kRecQ, RC_Q_BODY = RC_Q_GLEN + kRecQ,
    RC_Q_AGE = RC_Q_BODY + kRecQ,
    RC_SENSORS = RC_Q_AGE + kRecQ,                    // NUM_SENSES usage shares
    RC_TOP = RC_SENSORS + NUM_SENSES,                 // kRecTopLines (id, count) pairs
    kRecLen = RC_TOP + 2 * kRecTopLines
};

struct Recorder {
    int every = 60;                       // frames between samples (0 = no samples)
    long long culled = 0;                 // creatures the governor removed (evo_cull_to)
    std::vector<double> samples, births, changes;
    std::vector<double> outSamples, outBirths, outChanges;   // what evo_rec_take handed out
    std::vector<std::uint64_t> live;      // sorted live ids at the last check
    std::vector<std::uint64_t> born;      // ids born since the last check (ascending)
} g_rec;

struct IdLine { std::uint64_t id, lineage; };

// The live set as (id, lineageId), ascending by id. World keeps creatures in id
// order (appends only, removal keeps order), so the sort is a no-op guard.
std::vector<IdLine> liveIds(const World& w) {
    std::vector<IdLine> v;
    v.reserve(w.creatures.size());
    for (const Creature& c : w.creatures) v.push_back({c.id, c.lineageId});
    if (!std::is_sorted(v.begin(), v.end(), [](const IdLine& a, const IdLine& b) { return a.id < b.id; }))
        std::sort(v.begin(), v.end(), [](const IdLine& a, const IdLine& b) { return a.id < b.id; });
    return v;
}

void recChange(int kind, std::uint64_t id, std::uint64_t lineage, unsigned long long frame) {
    g_rec.changes.insert(g_rec.changes.end(),
                         {(double)kind, (double)id, (double)lineage, (double)frame});
}

// Compare the live set with the last check: ids gone are reported as left,
// ids that are new and were not born (reseeded founders) as joined.
void recCheckLive(const World& w) {
    const std::vector<IdLine> cur = liveIds(w);
    // born ids are all newer than every id of the last check, so this is sorted
    std::vector<std::uint64_t>& prev = g_rec.live;
    prev.insert(prev.end(), g_rec.born.begin(), g_rec.born.end());
    std::size_t i = 0, j = 0;
    while (i < prev.size() || j < cur.size()) {
        if (j == cur.size() || (i < prev.size() && prev[i] < cur[j].id)) {
            recChange(1, prev[i++], 0, w.frame);
        } else if (i == prev.size() || cur[j].id < prev[i]) {
            recChange(2, cur[j].id, cur[j].lineage, w.frame);
            ++j;
        } else {
            ++i; ++j;
        }
    }
    prev.clear();
    for (const IdLine& c : cur) prev.push_back(c.id);
    g_rec.born.clear();
}

// After World::update: one row per newborn of that step (see the note above).
void recBirths(const World& w, std::uint64_t id0, long long births0) {
    const long long nb = w.totalBirths - births0;
    if (nb <= 0) return;
    const std::vector<repro::Edge>& ring = w.reproWindow_;
    const std::size_t cap = w.cfg.reproWindow > 0 ? (std::size_t)w.cfg.reproWindow : 0;
    const bool known = cap > 0 && (std::size_t)nb <= ring.size();
    for (long long k = 0; k < nb; ++k) {
        const std::uint64_t id = id0 + (std::uint64_t)k;
        std::uint64_t a = 0, b = 0, lineage = 0;
        if (known) {
            // the ring's last nb edges, oldest first: appended while it fills,
            // then overwritten from reproWindowNext_ on
            const std::size_t back = (std::size_t)(nb - k);
            const std::size_t at = ring.size() < cap
                ? ring.size() - back
                : (w.reproWindowNext_ + cap - back) % cap;
            a = ring[at].a; b = ring[at].b;
        }
        // the newborn itself, for its lineage (absent if eaten the same step)
        auto it = std::lower_bound(w.creatures.begin(), w.creatures.end(), id,
                                   [](const Creature& c, std::uint64_t v) { return c.id < v; });
        if (it != w.creatures.end() && it->id == id) lineage = it->lineageId;
        g_rec.births.insert(g_rec.births.end(),
                            {(double)id, (double)a, (double)b, (double)lineage, (double)w.frame});
        g_rec.born.push_back(id);
    }
}

void quantiles(std::vector<float>& v, double* out) {
    static const double kQ[kRecQ] = {0.10, 0.25, 0.50, 0.75, 0.90};
    if (v.empty()) { for (int q = 0; q < kRecQ; ++q) out[q] = 0.0; return; }
    std::sort(v.begin(), v.end());
    for (int q = 0; q < kRecQ; ++q) {
        const double pos = kQ[q] * (double)(v.size() - 1);
        const std::size_t lo = (std::size_t)pos;
        const std::size_t hi = std::min(lo + 1, v.size() - 1);
        out[q] = v[lo] + (pos - (double)lo) * (v[hi] - v[lo]);
    }
}

void recSample(const World& w) {
    recCheckLive(w);
    const WorldStats s = computeStats(w);
    double r[kRecLen] = {};
    r[RC_FRAME] = (double)w.frame;
    r[RC_POP] = s.population;
    r[RC_FOOD] = s.food;
    r[RC_PRED] = s.predatorPop;
    r[RC_BIRTHS] = (double)w.totalBirths;
    r[RC_DEATHS] = (double)w.totalDeaths;
    r[RC_KILLS] = (double)w.totalDeathsPredation;
    r[RC_STARVED] = (double)w.totalDeathsStarvation;
    r[RC_AGED] = (double)w.totalDeathsAge;
    r[RC_AVG_AGE] = s.avgAge;
    r[RC_MAX_AGE] = s.maxAge;
    r[RC_AVG_ENERGY] = s.avgEnergy;
    r[RC_AVG_SPEED] = s.avgSpeed;
    r[RC_AVG_GLEN] = s.avgGenomeLen;
    r[RC_GLEN_STD] = s.genomeLenStd;
    r[RC_DIVERSITY] = s.geneticDiversity;
    r[RC_FLOW_ALIGN] = s.avgFlowAlign;
    r[RC_PRED_ALIGN] = s.avgPredatorAlign;
    r[RC_NEIGH_ALIGN] = s.avgNeighborAlign;
    r[RC_NEIGH_COUNT] = s.avgNeighborCount;
    r[RC_PRED_BIRTHS] = (double)w.totalPredatorBirths;
    r[RC_PRED_STARVED] = (double)w.totalPredatorDeathsStarvation;
    r[RC_PRED_AGED] = (double)w.totalPredatorDeathsAge;
    r[RC_PRED_ENERGY] = s.predatorAvgEnergy;
    r[RC_COMPONENTS] = s.reproComponents;
    const GenerationSpan gen = generationSpan(w);
    r[RC_GEN_MEAN] = gen.mean;
    r[RC_GEN_MAX] = (double)gen.max;
    r[RC_CURRENT] = w.currentActive() ? 1.0 : 0.0;
    r[RC_CULLED] = (double)g_rec.culled;
    r[RC_PRED_RESEEDS] = (double)w.totalPredatorReseeds;
    r[RC_PRED_SPEED] = s.predatorSpeedFactor;
    r[RC_PRED_BUDDING] = s.predatorBuddingFactor;
    r[RC_PRED_GEN] = s.predatorGeneration;

    const std::size_t n = w.creatures.size();
    std::vector<float> speed, glen, body, age;
    speed.reserve(n); glen.reserve(n); body.reserve(n); age.reserve(n);
    std::unordered_map<std::uint64_t, int> lines;
    lines.reserve(n);
    double bs = 0.0, be = 0.0;
    for (const Creature& c : w.creatures) {
        speed.push_back(c.speed);
        glen.push_back((float)c.genome.size());
        body.push_back(c.bodySize);
        age.push_back(c.age);
        bs += c.bodySize; be += c.bodyElong;
        ++lines[c.lineageId];
    }
    if (n) { r[RC_BODY_SIZE] = bs / (double)n; r[RC_BODY_ELONG] = be / (double)n; }
    quantiles(speed, r + RC_Q_SPEED);
    quantiles(glen, r + RC_Q_GLEN);
    quantiles(body, r + RC_Q_BODY);
    quantiles(age, r + RC_Q_AGE);
    float use[NUM_SENSES];
    wiring::fractions(w, use);
    for (int k = 0; k < NUM_SENSES; ++k) r[RC_SENSORS + k] = use[k];

    r[RC_LINES] = (double)lines.size();
    std::vector<std::pair<int, std::uint64_t>> top;   // (count, id)
    top.reserve(lines.size());
    for (const auto& kv : lines) top.push_back({kv.second, kv.first});
    const std::size_t k = std::min<std::size_t>(kRecTopLines, top.size());
    // largest first; ties to the older line, so the order is deterministic
    std::partial_sort(top.begin(), top.begin() + k, top.end(),
                      [](const std::pair<int, std::uint64_t>& a, const std::pair<int, std::uint64_t>& b) {
                          return a.first != b.first ? a.first > b.first : a.second < b.second;
                      });
    for (std::size_t t = 0; t < k; ++t) {
        r[RC_TOP + 2 * t] = (double)top[t].second;
        r[RC_TOP + 2 * t + 1] = (double)top[t].first;
    }
    g_rec.samples.insert(g_rec.samples.end(), r, r + kRecLen);
}

// Start the streams over: forget what was recorded, take the current live set
// as the baseline, and (roots) report it as joined so the page knows who is
// alive. Then one sample, so a chart starts at the reset.
void recReset(const World& w, bool roots, bool sample) {
    g_rec.samples.clear(); g_rec.births.clear(); g_rec.changes.clear();
    g_rec.born.clear();
    g_rec.live.clear();
    for (const IdLine& c : liveIds(w)) {
        g_rec.live.push_back(c.id);
        if (roots) recChange(2, c.id, c.lineage, w.frame);
    }
    if (sample && g_rec.every > 0) recSample(w);
}

}  // namespace

// Initialise (or re-initialise) the world. cfgJson may be null/empty for
// defaults, or a flat JSON object using the same field names as a
// checkpoint's "config" block; any subset of keys is accepted.
EVO_EXPORT int evo_init(unsigned seed, int width, int height, int population,
                        const char* cfgJson) {
    g_error.clear();
    SimConfig cfg;
    if (cfgJson && cfgJson[0]) {
        // readConfig expects the config under a "config" key; wrap the flat
        // object so the shim accepts the checkpoint schema directly.
        const std::string wrapped = std::string("{\"config\":") + cfgJson + "}";
        jsonm::Value root;
        std::string err;
        if (!jsonm::Parser::parse(wrapped, root, err)) {
            g_error = "config parse error: " + err;
            return 0;
        }
        checkpoint::readConfig(root, cfg);
    }
    clampConfig(cfg);
    if (width < 100 || height < 100 || population < 0) {
        g_error = "bad world dimensions or population";
        return 0;
    }
    // Same refusal main.cpp makes: the genetic gate folds a genome into a fixed
    // stack buffer, so an oversized genomeMaxLength would silently gate on a
    // truncated genome. Reject rather than clamp, so the two frontends agree.
    if (cfg.reproMaxDistance >= 0.0f &&
        cfg.genomeMaxLength > isolation_detail::ISO_MAX_GENES) {
        g_error = "reproMaxDistance requires genomeMaxLength <= "
                + std::to_string(isolation_detail::ISO_MAX_GENES);
        return 0;
    }
    // Same refusal main.cpp makes, for the same reason and on the same terms:
    // a negative half-width runs rng.range backwards, and a non-finite one
    // makes rng.range yield NaN, which the inheritance clamp does not filter —
    // every newborn body goes NaN. The config here arrives as parsed JSON, so
    // both are reachable from the page. Reject rather than clamp, so the two
    // frontends agree. Negated test: NaN compares false to everything.
    if (!(cfg.bodyMutation >= 0.0f) || !std::isfinite(cfg.bodyMutation)) {
        g_error = "bodyMutation must be finite and >= 0";
        return 0;
    }
    // The same refusal for the predator trait mutation (v0.26.0), for the same
    // reasons: it feeds rng.range at every bud.
    if (!(cfg.predatorTraitMutation >= 0.0f) || !std::isfinite(cfg.predatorTraitMutation)) {
        g_error = "predatorTraitMutation must be finite and >= 0";
        return 0;
    }
    // Stage C (v0.27.0): the brain knobs, refused on the same terms by every
    // frontend and the checkpoint loader (config.hpp predatorBrainConfigError).
    if (const char* why = predatorBrainConfigError(cfg)) {
        g_error = why;
        return 0;
    }
    // Same refusal main.cpp makes for the gate knobs, so the frontends agree
    // there too. Negative is legal and means off (the reproMaxDistance
    // convention); non-finite is not: every comparison against NaN is false, so
    // a NaN soft width rejects EVERY pair while still burning a draw, and a NaN
    // threshold ARMS the gate (NaN < 0 is false) and then refuses everything —
    // both the opposite of what the knob advertises.
    if (!std::isfinite(cfg.reproSoftWidth) || !std::isfinite(cfg.reproGracePeriod) ||
        !std::isfinite(cfg.reproMaxDistance)) {
        g_error = "reproMaxDistance, reproSoftWidth and reproGracePeriod must be finite (negative = off)";
        return 0;
    }

    // Always capture per-creature sensor/action activations for the neural
    // inspector. Dynamics-neutral (a pure memcpy in World::update, no rng),
    // and not serialized into checkpoints — parity with the native CLI holds.
    cfg.captureActivations = true;

    rng.seed(seed);
    delete g_world;
    g_world = new World();
    g_world->cfg = cfg;
    g_world->init(width, height, population);
    g_rec.culled = 0;
    recReset(*g_world, true, true);

    g_lastInit.seed = seed;
    g_lastInit.width = width;
    g_lastInit.height = height;
    g_lastInit.population = population;
    g_lastInit.cfgJson = (cfgJson && cfgJson[0]) ? cfgJson : "";
    g_lastInit.valid = true;
    return 1;
}

// Re-run the last evo_init with the same arguments: same seed and config, so in
// the single-threaded module the run replays exactly. Live parameter changes
// made since (evo_set_param) are dropped.
EVO_EXPORT int evo_reset() {
    if (!g_lastInit.valid) { g_error = "evo_reset before any successful evo_init"; return 0; }
    const InitArgs a = g_lastInit;  // evo_init overwrites g_lastInit
    return evo_init(a.seed, a.width, a.height, a.population,
                    a.cfgJson.empty() ? nullptr : a.cfgJson.c_str());
}

// Change one parameter of the running world. Only parameters the step reads
// fresh every tick are accepted; anything baked in at init (world size,
// currents, food patches, predator count, the toroidal grid) needs a restart.
// All accepted values are non-negative. Returns 0 and sets evo_last_error() on
// refusal; the config is left unchanged.
EVO_EXPORT int evo_set_param(const char* name, double value) {
    g_error.clear();
    if (!g_world) { g_error = "no world (call evo_init first)"; return 0; }
    static const char* const kLive[] = {
        "maxPopulation", "minPopulation", "targetFood", "foodSpawnBase", "foodSpawnAmp",
        "foodEnergy", "metabolicRate", "moveCost", "geneCost", "maxAge", "reproEnergy",
        "newbornEnergy", "mutationMultiplier", "minSpeed", "maxSpeed",
        // v0.26.0: the predator floor, ceiling and trait mutation are read
        // fresh every step too (refill, bud check, bud draw)
        "predatorMinPopulation", "predatorMaxPopulation", "predatorTraitMutation",
    };
    bool live = false;
    for (const char* k : kLive) if (name && std::strcmp(name, k) == 0) { live = true; break; }
    if (!live) {
        g_error = std::string("not a live parameter (change it and restart): ") + (name ? name : "(null)");
        return 0;
    }
    if (!std::isfinite(value) || value < 0.0) {
        g_error = std::string(name) + " must be finite and >= 0";
        return 0;
    }
    // Route through the checkpoint config reader so the field mapping (and the
    // int/float typing) is the one place that already defines it.
    char num[40];
    std::snprintf(num, sizeof num, "%.9g", value);
    const std::string json = std::string("{\"config\":{\"") + name + "\":" + num + "}}";
    jsonm::Value root;
    std::string err;
    if (!jsonm::Parser::parse(json, root, err)) { g_error = "internal: " + err; return 0; }
    SimConfig cfg = g_world->cfg;
    checkpoint::readConfig(root, cfg);
    clampConfig(cfg);
    if (const char* why = brainPolicyConfigError(cfg)) {
        g_error = why;
        return 0;
    }
    g_world->cfg = cfg;
    return 1;
}

// ---- Threading -------------------------------------------------------------
// 1 in the pthreads module, 0 in the single-threaded one.
EVO_EXPORT int evo_threaded() {
#ifdef EVO_POOL_THREADS
    return 1;
#else
    return 0;
#endif
}
EVO_EXPORT int evo_max_threads() {
#ifdef EVO_POOL_THREADS
    return evo_par::Pool::maxThreads();
#else
    return 1;
#endif
}
EVO_EXPORT int evo_threads() {
#ifdef EVO_POOL_THREADS
    return evo_par::Pool::instance().threads();
#else
    return 1;
#endif
}
// Set the thread count (clamped to [1, evo_max_threads()]); returns the count
// in effect. A no-op in the single-threaded module.
EVO_EXPORT int evo_set_threads(int n) {
#ifdef EVO_POOL_THREADS
    evo_par::Pool::instance().setThreads(n);
#else
    (void)n;
#endif
    return evo_threads();
}

// Remove creatures uniformly at random until at most n remain; returns how many
// were removed. Used by the page's frame-budget governor (web/renderer.js) to
// shed agents immediately instead of waiting for the birth cap to act through
// deaths. Uniform, so it favours no trait. Not a death: no death log entry and
// no counters. It draws from its own SplitMix64 seeded by the frame number, so
// the simulation's rng stream is untouched — but the run itself has been
// changed, so it no longer replays from its seed (the page says so).
// Safe between steps: nothing in World keeps creature indices across update()
// (the pairing log is keyed by Creature::id).
EVO_EXPORT int evo_cull_to(int n) {
    if (!g_world || n < 0) return 0;
    std::vector<Creature>& cs = g_world->creatures;
    const size_t total = cs.size();
    if (total <= (size_t)n) return 0;
    const size_t k = total - (size_t)n;

    std::uint64_t s = 0x9E3779B97F4A7C15ull ^ (std::uint64_t)g_world->frame;
    auto next = [&s]() {
        std::uint64_t z = (s += 0x9E3779B97F4A7C15ull);
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
        return z ^ (z >> 31);
    };
    std::vector<size_t> idx(total);
    for (size_t i = 0; i < total; ++i) idx[i] = i;
    std::vector<char> drop(total, 0);
    for (size_t i = 0; i < k; ++i) {  // partial Fisher-Yates: the first k picks
        const size_t j = i + (size_t)(next() % (total - i));
        std::swap(idx[i], idx[j]);
        drop[idx[i]] = 1;
    }
    size_t w = 0;
    for (size_t r = 0; r < total; ++r) {
        if (drop[r]) continue;
        if (w != r) cs[w] = std::move(cs[r]);
        ++w;
    }
    cs.resize(w);
    g_rec.culled += (long long)k;
    return (int)k;
}

// Advance n fixed steps. dt is pinned to the native headless path's 0.016f —
// passing wall-clock time here would destroy reproducibility. The recorder
// reads the world after each step (see "Dashboard recorder").
EVO_EXPORT void evo_step(int n) {
    if (!g_world) return;
    World& w = *g_world;
    for (int i = 0; i < n; ++i) {
        const std::uint64_t id0 = w.nextId_;
        const long long births0 = w.totalBirths;
        w.update(0.016f);
        recBirths(w, id0, births0);
        if (g_rec.every > 0 && w.frame % (unsigned long long)g_rec.every == 0) recSample(w);
    }
}

// ---- Dashboard recorder: the page's side -----------------------------------
// every: frames between samples (> 0; the page doubles it as its history
// thins out). culled >= 0 sets the governor's removal count (the Turbo worker
// takes the page's, so the column stays continuous); < 0 keeps it.
EVO_EXPORT void evo_rec_config(int every, double culled) {
    if (every > 0) g_rec.every = every;
    if (culled >= 0.0) g_rec.culled = (long long)culled;
}
EVO_EXPORT double evo_rec_culled() { return (double)g_rec.culled; }
EVO_EXPORT int evo_rec_len() { return kRecLen; }
EVO_EXPORT int evo_rec_top_lines() { return kRecTopLines; }
// Report every departure since the last sample now (before a hand-off, so
// nothing is dated to the other side).
EVO_EXPORT void evo_rec_flush() { if (g_world) recCheckLive(*g_world); }
// After a checkpoint load from a file: forget, re-baseline, report the live set.
EVO_EXPORT void evo_rec_reset(int roots) {
    if (g_world) recReset(*g_world, roots != 0, roots != 0);
}
// Move the three streams (k = 0 samples, 1 births, 2 changes) into out
// buffers and empty them; read each with evo_rec_count(k) doubles at
// evo_rec_data(k), valid until the next evo_rec_take.
EVO_EXPORT void evo_rec_take() {
    g_rec.outSamples.swap(g_rec.samples);  g_rec.samples.clear();
    g_rec.outBirths.swap(g_rec.births);    g_rec.births.clear();
    g_rec.outChanges.swap(g_rec.changes);  g_rec.changes.clear();
}
EVO_EXPORT int evo_rec_count(int k) {
    const std::vector<double>& v = k == 0 ? g_rec.outSamples : k == 1 ? g_rec.outBirths : g_rec.outChanges;
    return (int)v.size();
}
EVO_EXPORT const double* evo_rec_data(int k) {
    const std::vector<double>& v = k == 0 ? g_rec.outSamples : k == 1 ? g_rec.outBirths : g_rec.outChanges;
    return v.data();
}

// ---- On-demand analyses (only while their dashboard tab is open) ----------
namespace {
std::vector<double> g_simInfo;   // m*6: id, lineageId, generation, r, g, b
std::vector<float>  g_simDist;   // m*m: match distance (sqrt of genomeDistanceSq)
std::vector<float>  g_wiring;    // 2 * NUM_SENSES * NUM_ACTIONS: path share, direct share
std::string g_sensorNames;
}

// Pairwise match distances among up to maxN creatures, taken evenly across
// the live set (no rng). Same fold and sum as genomeDistanceSq (isolation.hpp),
// folding each genome once. Returns the number sampled.
EVO_EXPORT int evo_similarity(int maxN) {
    g_simInfo.clear(); g_simDist.clear();
    if (!g_world || maxN <= 0) return 0;
    const std::vector<Creature>& cs = g_world->creatures;
    const std::size_t n = cs.size();
    const std::size_t m = std::min<std::size_t>(n, (std::size_t)maxN);
    using namespace isolation_detail;
    std::vector<std::vector<std::uint16_t>> cells(m);
    std::vector<std::vector<float>> weights(m);
    std::vector<std::uint16_t> cbuf(ISO_MAX_GENES);
    std::vector<float> wbuf(ISO_MAX_GENES);
    for (std::size_t s = 0; s < m; ++s) {
        const Creature& c = cs[s * n / m];
        const int k = foldGenome(c.genome, cbuf.data(), wbuf.data());
        cells[s].assign(cbuf.begin(), cbuf.begin() + k);
        weights[s].assign(wbuf.begin(), wbuf.begin() + k);
        g_simInfo.insert(g_simInfo.end(), {(double)c.id, (double)c.lineageId, (double)c.generation,
                                           (double)c.color.r, (double)c.color.g, (double)c.color.b});
    }
    g_simDist.assign(m * m, 0.0f);
    for (std::size_t a = 0; a < m; ++a) {
        for (std::size_t b = a + 1; b < m; ++b) {
            const std::vector<std::uint16_t>& ca = cells[a], & cb = cells[b];
            const std::vector<float>& wa = weights[a], & wb = weights[b];
            float acc = 0.0f;
            std::size_t i = 0, j = 0;
            while (i < ca.size() && j < cb.size()) {
                if (ca[i] == cb[j]) { const float d = wa[i] - wb[j]; acc += d * d; ++i; ++j; }
                else if (ca[i] < cb[j]) { acc += wa[i] * wa[i]; ++i; }
                else { acc += wb[j] * wb[j]; ++j; }
            }
            for (; i < ca.size(); ++i) acc += wa[i] * wa[i];
            for (; j < cb.size(); ++j) acc += wb[j] * wb[j];
            const float d = std::sqrt(acc);
            g_simDist[a * m + b] = g_simDist[b * m + a] = d;
        }
    }
    return (int)m;
}
EVO_EXPORT const double* evo_similarity_info() { return g_simInfo.data(); }
EVO_EXPORT const float* evo_similarity_dist()  { return g_simDist.data(); }

// Which senses reach which actions, over the live set: [0] the share of
// creatures with a path from sensor s to action a (directly or through hidden
// neurons), [1] the share with a direct connection. Row-major, sensor rows.
// Returns the population counted.
EVO_EXPORT int evo_wiring() {
    constexpr int S = NUM_SENSES, A = NUM_ACTIONS, H = MAX_INTERNAL_NEURONS;
    g_wiring.assign(2 * S * A, 0.0f);
    if (!g_world || g_world->creatures.empty()) return 0;
    std::vector<long> path(S * A, 0), direct(S * A, 0);
    for (const Creature& c : g_world->creatures) {
        // reach[h]: actions reachable from hidden neuron h, as a bit set
        std::uint32_t reach[H] = {};
        bool grew = true;
        while (grew) {
            grew = false;
            for (const auto& fc : c.nnet.flat) {
                const int src = fc.src(), sink = fc.sink();
                if (src < S) continue;
                const int h = src - S;
                const std::uint32_t add = sink < A ? (1u << sink) : reach[sink - A];
                if ((reach[h] | add) != reach[h]) { reach[h] |= add; grew = true; }
            }
        }
        std::uint32_t pathBits[S] = {}, directBits[S] = {};
        for (const auto& fc : c.nnet.flat) {
            const int src = fc.src(), sink = fc.sink();
            if (src >= S) continue;
            if (sink < A) { pathBits[src] |= 1u << sink; directBits[src] |= 1u << sink; }
            else pathBits[src] |= reach[sink - A];
        }
        for (int s = 0; s < S; ++s)
            for (int a = 0; a < A; ++a) {
                if (pathBits[s] >> a & 1u) ++path[s * A + a];
                if (directBits[s] >> a & 1u) ++direct[s * A + a];
            }
    }
    const float inv = 1.0f / (float)g_world->creatures.size();
    for (int k = 0; k < S * A; ++k) {
        g_wiring[k] = (float)path[k] * inv;
        g_wiring[S * A + k] = (float)direct[k] * inv;
    }
    return (int)g_world->creatures.size();
}
EVO_EXPORT const float* evo_wiring_data() { return g_wiring.data(); }
// The sensor names, comma-separated, in Sensor-enum order (wiring_log.hpp).
EVO_EXPORT const char* evo_sensor_names() {
    if (g_sensorNames.empty())
        for (int s = 0; s < NUM_SENSES; ++s) {
            if (s) g_sensorNames += ',';
            g_sensorNames += wiring::kSensorNames[s];
        }
    return g_sensorNames.c_str();
}

// Repack all export buffers from the current world state.
EVO_EXPORT void evo_sync() {
    if (!g_world) return;
    const World& w = *g_world;
    const size_t n = w.creatures.size();

    g_segments.resize(n * 12);
    g_bodyParams.resize(n * 2);
    g_colors.resize(n * 3);
    g_ids.resize(n);
    // The HUD's genome-length and generation figures ride along in the same
    // pass, summed in the same order as the loops they replace
    // (generationSpan's included), so the doubles come out identical.
    double genomeSum = 0.0, genSum = 0.0;
    std::uint32_t genMax = 0;
    size_t genN = 0;
    for (size_t i = 0; i < n; ++i) {
        const Creature& c = w.creatures[i];
        genomeSum += (double)c.genome.size();
        if (c.alive) {
            genSum += (double)c.generation;
            if (c.generation > genMax) genMax = c.generation;
            ++genN;
        }
        for (int s = 0; s < Creature::BODY_LEN; ++s) {
            g_segments[i * 12 + s * 2 + 0] = c.body[s].x;
            g_segments[i * 12 + s * 2 + 1] = c.body[s].y;
        }
        // Filled in the same pass as the segments so the two buffers can never
        // disagree about creature order or count.
        g_bodyParams[i * 2 + 0] = c.bodySize;
        g_bodyParams[i * 2 + 1] = c.bodyElong;
        if (g_colourMode == 1) {
            familyColor(c.lineageId, &g_colors[i * 3]);
        } else {
            g_colors[i * 3 + 0] = c.color.r;
            g_colors[i * 3 + 1] = c.color.g;
            g_colors[i * 3 + 2] = c.color.b;
        }
        g_ids[i] = (double)c.id;
    }

    g_food.resize(w.food.size() * 2);
    for (size_t i = 0; i < w.food.size(); ++i) {
        g_food[i * 2 + 0] = w.food[i].pos.x;
        g_food[i * 2 + 1] = w.food[i].pos.y;
    }

    g_predators.resize(w.predators.size() * 3);
    for (size_t i = 0; i < w.predators.size(); ++i) {
        g_predators[i * 3 + 0] = w.predators[i].pos.x;
        g_predators[i * 3 + 1] = w.predators[i].pos.y;
        g_predators[i * 3 + 2] = w.predators[i].digestTimer;
    }

    if (w.currentActive()) {
        g_currentCols = (w.width  > kCurrentStep / 2) ? (w.width  - kCurrentStep / 2 + kCurrentStep - 1) / kCurrentStep : 0;
        g_currentRows = (w.height > kCurrentStep / 2) ? (w.height - kCurrentStep / 2 + kCurrentStep - 1) / kCurrentStep : 0;
        g_current.resize((size_t)g_currentCols * g_currentRows * 2);
        size_t k = 0;
        for (int j = 0; j < g_currentRows; ++j) {
            const float y = kCurrentStep / 2.0f + (float)j * kCurrentStep;
            for (int i = 0; i < g_currentCols; ++i) {
                const float x = kCurrentStep / 2.0f + (float)i * kCurrentStep;
                const Vec2 v = w.currentAt({x, y});
                g_current[k++] = v.x;
                g_current[k++] = v.y;
            }
        }
    } else {
        g_currentCols = g_currentRows = 0;
        g_current.clear();
    }

    g_stats[0] = (double)n;
    g_stats[1] = (double)w.food.size();
    g_stats[2] = (double)w.predators.size();
    g_stats[3] = (double)w.frame;
    g_stats[4] = (double)w.births;
    g_stats[5] = (double)w.deaths;
    g_stats[6] = (double)w.totalBirths;
    g_stats[7] = (double)w.totalDeaths;
    g_stats[8] = n ? genomeSum / (double)n : 0.0;
    g_stats[9] = genN ? genSum / (double)genN : 0.0;
    g_stats[10] = (double)genMax;
}

EVO_EXPORT int evo_creature_count()             { return g_world ? (int)g_world->creatures.size() : 0; }
EVO_EXPORT const float* evo_creature_segments() { return g_segments.data(); }
// N*2 (bodySize, bodyElong), creature order identical to evo_creature_segments.
// Separate buffer, not extra columns: the segments stride of 12 is relied on by
// every reader.
EVO_EXPORT const float* evo_body_params()       { return g_bodyParams.data(); }
EVO_EXPORT const uint8_t* evo_creature_colors() { return g_colors.data(); }
// What evo_creature_colors holds from the next evo_sync: 0 = by brain (the
// genome colour, the default), 1 = by family line. Display only.
EVO_EXPORT void evo_set_colour_mode(int mode) { g_colourMode = mode == 1 ? 1 : 0; }
// A family line's colour as 0xRRGGBB — the one its fish get in family mode.
EVO_EXPORT int evo_family_color(double lineageId) {
    std::uint8_t c[3];
    familyColor((std::uint64_t)lineageId, c);
    return (c[0] << 16) | (c[1] << 8) | c[2];
}
EVO_EXPORT const double* evo_creature_ids()     { return g_ids.data(); }
EVO_EXPORT int evo_food_count()                 { return g_world ? (int)g_world->food.size() : 0; }
EVO_EXPORT const float* evo_food_xy()           { return g_food.data(); }
EVO_EXPORT int evo_predator_count()             { return g_world ? (int)g_world->predators.size() : 0; }
EVO_EXPORT const float* evo_predator_data()     { return g_predators.data(); }
EVO_EXPORT int evo_current_active()             { return (g_world && g_world->currentActive()) ? 1 : 0; }
EVO_EXPORT int evo_current_cols()               { return g_currentCols; }
EVO_EXPORT int evo_current_rows()               { return g_currentRows; }
EVO_EXPORT const float* evo_current_grid()      { return g_current.data(); }
EVO_EXPORT const double* evo_stats()            { return g_stats; }
EVO_EXPORT int evo_stats_len()                  { return kStatsLen; }
EVO_EXPORT int evo_width()                      { return g_world ? g_world->width : 0; }
EVO_EXPORT int evo_height()                     { return g_world ? g_world->height : 0; }

// Default config as JSON ({"config":{...}} — the checkpoint schema), for UIs
// that want to show every knob with its default.
EVO_EXPORT const char* evo_default_config() {
    std::string out;
    jsonm::Writer w(out);
    w.beginObject();
    checkpoint::writeConfig(w, SimConfig{});
    w.endObject();
    g_defaultConfig = out;
    return g_defaultConfig.c_str();
}

// Full checkpoint JSON of the current state. Identical bytes to what the
// native serial CLI would write for the same seed/config/steps.
EVO_EXPORT const char* evo_checkpoint() {
    if (!g_world) return "";
    g_checkpoint = checkpoint::serialize(*g_world, EVO_VERSION);
    return g_checkpoint.c_str();
}

// Restore from checkpoint JSON (replaces world, config, dimensions, and the
// rng stream — the resumed run continues bit-exactly).
EVO_EXPORT int evo_load_checkpoint(const char* json) {
    g_error.clear();
    if (!json || !json[0]) { g_error = "empty checkpoint"; return 0; }
    World* w = new World();
    std::string err;
    if (!checkpoint::deserialize(json, *w, err)) {
        delete w;
        g_error = "checkpoint load error: " + err;
        return 0;
    }
    delete g_world;
    g_world = w;
    g_world->cfg.captureActivations = true;  // see evo_init
    // A loaded arena (Stage C) is being run now, so the checkpoints this page
    // saves are ordinary ones, as main.cpp's are (a later CLI run logs L rows).
    g_world->arenaFresh_ = false;
    // A Turbo hand-off carries on the same run: re-baseline quietly. A file
    // load is a new run; the page then calls evo_rec_reset(1).
    recReset(*g_world, false, false);
    return 1;
}

EVO_EXPORT const char* evo_last_error() { return g_error.c_str(); }

// ---- Neural inspector ------------------------------------------------------
// evo_inspect(i) snapshots creature i (index into this frame's arrays, valid
// until the next evo_step/evo_sync) for the click-to-inspect panel. Buffers
// mirror what the native SFML overlay reads (sfml_renderer.cpp
// drawNeuralOverlay): lastSensors / neuron outputs / lastActions, and the
// flattened connection list decoded via asGene().
namespace {
// 8 doubles, in this order — web/renderer.js reads INSPECT_INFO_LEN of them and
// the two must be changed together.
double g_inspInfo[8] = {};                 // id, speed, foodReserves, age, bodySize, bodyElong, generation, lineageId
std::vector<float> g_inspSensors;          // NUM_SENSES
std::vector<float> g_inspHidden;           // MAX_INTERNAL_NEURONS
std::vector<float> g_inspActions;          // NUM_ACTIONS
std::vector<float> g_inspConns;            // K*5: srcIsSensor, srcNum, sinkIsAction, sinkNum, weight
}

EVO_EXPORT int evo_inspect(int index) {
    if (!g_world || index < 0 || (size_t)index >= g_world->creatures.size()) return 0;
    const Creature& c = g_world->creatures[(size_t)index];

    g_inspInfo[0] = (double)c.id;
    g_inspInfo[1] = (double)c.speed;
    g_inspInfo[2] = (double)c.foodReserves;
    g_inspInfo[3] = (double)c.age;
    g_inspInfo[4] = (double)c.bodySize;
    g_inspInfo[5] = (double)c.bodyElong;
    g_inspInfo[6] = (double)c.generation;
    g_inspInfo[7] = (double)c.lineageId;       // its family line

    g_inspSensors.assign(c.lastSensors, c.lastSensors + NUM_SENSES);
    g_inspActions.assign(c.lastActions, c.lastActions + NUM_ACTIONS);
    g_inspHidden.resize(MAX_INTERNAL_NEURONS);
    for (int i = 0; i < MAX_INTERNAL_NEURONS; ++i)
        g_inspHidden[i] = c.nnet.neurons[i].output;

    g_inspConns.resize(c.nnet.flat.size() * 5);
    size_t k = 0;
    for (const auto& fc : c.nnet.flat) {
        const Gene g = asGene(fc);
        g_inspConns[k++] = (g.sourceType == SOURCE_SENSOR) ? 1.0f : 0.0f;
        g_inspConns[k++] = (float)g.sourceNum;
        g_inspConns[k++] = (g.sinkType == SINK_ACTION) ? 1.0f : 0.0f;
        g_inspConns[k++] = (float)g.sinkNum;
        g_inspConns[k++] = g.weightAsFloat();
    }
    return 1;
}

EVO_EXPORT const double* evo_inspect_info()   { return g_inspInfo; }
EVO_EXPORT const float* evo_inspect_sensors() { return g_inspSensors.data(); }
EVO_EXPORT const float* evo_inspect_hidden()  { return g_inspHidden.data(); }
EVO_EXPORT const float* evo_inspect_actions() { return g_inspActions.data(); }
EVO_EXPORT int evo_inspect_conn_count()       { return (int)(g_inspConns.size() / 5); }
EVO_EXPORT const float* evo_inspect_conns()   { return g_inspConns.data(); }

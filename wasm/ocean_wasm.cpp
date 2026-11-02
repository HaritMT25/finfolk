// ocean_wasm.cpp — C ABI shim for the Ocean preview (PLAN_ocean_preview.md §4).
//
// CONTRACT DEVIATIONS: one. oc_init refuses a reversed minSpeed/maxSpeed or
// genome-length pair, where evo_init swaps it (see the refusals below).
// Choices the contract leaves open, fixed here:
//   * oc_init: depth <= 0 means the default sea depth (OceanConfig{}.depth,
//     240); a non-finite depth or one in (0, 10) is refused like a bad width.
//   * oc_stats: births, deaths and reseeds are CUMULATIVE totals over the run
//     (reseeds = founders the minPopulation floor added); stats_len = 15.
//   * oc_init also refuses (configOk; the previous world is kept): genome
//     lengths outside 16 <= genomeMinLength <= genomeInitMin <= genomeInitMax
//     <= genomeMaxLength <= 80 (GENOME_*); speeds other than finite
//     0 <= minSpeed <= maxSpeed with maxSpeed > 0; a reversed min/max pair is
//     refused, not swapped as evo_init does; a radius that is not finite and
//     >= 0, whose square is not a finite float (>= ~1.8e19: every radius is
//     used squared), or, toroidal, not < min(width, height) / 2 (the wrapped
//     grid query's bound; OceanWorld::radiusError); a current knob or
//     foodPatchRadius outside the Ocean's ranges (ocean_config.hpp
//     oceanSimConfigError: currentStrength in [0, 1000], currentEddies in
//     [0, 100], currentCore in [0, 1e5], currentDrift in [-100, 100],
//     currentGyreEps in [-1, 1], currentMode 0 / 1, foodPatchRadius in
//     [0, 1e5]), or a key whose value reaches an int conversion out of range
//     (foodSpawnBase / foodSpawnAmp in [-1e4, 1e4], targetFood in [0, 1e6],
//     maxSpeed <= 2000, predatorSpeed in [0, 2000], every radius <= 1e6); an
//     energy outside [-1e6, 1e6] (foodEnergy, metabolicRate, geneCost,
//     moveCost, reproEnergy, newbornEnergy and the predator economy's
//     metabolism, move cost, repro / newborn energies and meal: finite values
//     like foodEnergy 1e38 overflowed reserves to inf); a non-finite value in
//     any other float the step reads (maxTurnRate, the cooldowns, maxAge, ...);
//     minPopulation, predatorCount or foodPatches above 1e5; a width or
//     height outside [100, 1e5], a population outside [0, 1e5], or neighbour
//     grids (cell = perceptionRadius) over 2^24 cells (oceanWorldSizeError);
//     and (readOceanJson) an int-typed key — SimConfig's, or the Ocean's
//     foodDepthMode, eye, eyeOnly, eyeCode, steerFrame — whose JSON number is
//     not a whole number in int's range, before anything casts it; and, at
//     any occurrence, a SimConfig bool key (toroidal, bodyModel,
//     triangularMotion, foodDrift, predatorEconomy, predatorInheritance,
//     fastTanh) that is not true / false ({"toroidal":1} used to be passed
//     over: the world kept its walls), or an Ocean one (deepCurrent,
//     lightEnabled, depthCostScaled, sizeDrift, sizeFight, mouthGate, walls)
//     that is not true / false / 0 / 1; and glass walls with toroidal = true
//     (oceanTopologyError), or sideWallBand / sideWallTurnRate outside
//     [0, 1e5] / [0, 1000].
//   * walls, sideWallBand, sideWallTurnRate (the glass walls) are set by
//     oc_init: oc_set_param refuses them ("restart to change it");
//     oc_walls_enabled() reports the world's mode.
//   * oc_set_param: the Ocean keys kBuoy, pitchMax, vDrag, wallBand,
//     buoyMutation, cHold, cPress, foodDepthSpread, the E1 keys (waveSpeed,
//     waveBand, waveGravity, L0, kWater, kMouth, and the on/off keys
//     deepCurrent, lightEnabled, depthCostScaled, sizeDrift, sizeFight,
//     mouthGate as 0 / 1), the eye-build keys eye, eyeOnly, eyeCode, the
//     steering frame steerFrame and the food lifetime foodLife, plus every
//     key evo_set_param accepts. pitchMax must be > 0. The changed config
//     must pass oc_init's checks as stored (after the float / int
//     conversion), including every Ocean knob's range (ocean_config.hpp
//     oceanConfigError, oceanSimConfigError). An int key's value must be a
//     whole number (0.5 is refused, not stored as 0) and goes to the reader
//     as its exact integer.
//   * eye (OceanConfig::eye, the compound eye) and eyeOnly (the labeled senses
//     off; with eye 0, "blind") are 0 or 1 in the eye build (-DEVO_OCEAN_EYE)
//     and must stay 0 in the plain one; oc_has_eye() says which build this is.
//     eyeCode (the eye's encoding, a bitmask: 1 faded contrast, 2 opponent
//     pairs, 4 summed sectors; and the cloaks 8 the eye ignores fish, 16 the
//     eye ignores food) is 0..31 in the eye build and must stay 0 in the
//     plain one.
//   * steerFrame (OceanConfig::steerFrame: STEER_X / STEER_Y in world x / y, or
//     in the fish's own frame) is 0 or 1 in both builds; foodLife (seconds,
//     0 = off) is in [0, 3600] (kOceanMaxFoodLife: where a float age still
//     advances accurately by dt).
//   * With no cfgJson the world is the tuned preview (applyOceanDefaults +
//     OceanConfig defaults, src/ocean/ocean_config.hpp).
//
// ADDITIONS beyond §4 (not deviations; the page feature-detects them):
//   * const float* oc_creature_vz() — N floats, same order as
//     oc_creature_segments, refreshed by oc_sync: each fish's Fish::vz as the
//     engine integrates it (depth += vz·speed·dt; + = sinking; |vz| <=
//     pitchMax). The fish swims horizontally at `speed` along its unit (x, y)
//     heading and vertically at vz·speed, so its pitch is atan(vz) (+ = nose
//     down). The current's horizontal drift is not included.
//   * E1: int oc_light_enabled(), double oc_light_l0(), double
//     oc_light_kwater() — the light field L(d) = L0·exp(−kWater·d) the page
//     shades depth with when enabled; const char* oc_e1_preset() — the E1
//     preset cfg JSON (the page merges it under ?cfg= for ?e1=1).
//   * The page's controls (the fish card, the dashboards, the colour switch):
//     READ-ONLY. Each reads the world and fills shim buffers; none changes
//     anything the step reads, draws a random number or touches the world's
//     run state, so a run with them is the run without them, step for step.
//       oc_inspect(i) (+ oc_inspect_info / _sensors / _hidden / _actions /
//         _conn_count / _conns): one fish of this sync's arrays, as
//         evo_inspect (kInspectLen doubles, layout at g_inspInfo below).
//       oc_num_senses(), oc_num_actions(), oc_num_hidden(),
//         oc_sensor_names(), oc_action_names(): this build's brain shape.
//       oc_summary(): population means and the run's cause-split counters
//         (kSummaryLen doubles, layout at g_summary below).
//       oc_families(k) (+ oc_families_data): the k biggest family lines.
//       oc_family_color(lineageId): a line's colour, 0xRRGGBB.
//       oc_wiring() (+ oc_wiring_data): which senses reach which actions,
//         over the live set (evo_wiring's).
//     Two DISPLAY switches, which change what the exports report, never the
//     dynamics:
//       oc_set_colour_mode(mode): oc_creature_colors from the next oc_sync,
//         1 = by family line (the default: what it always held), 0 = by brain
//         (the genome colour, AgentCore::color), as evo_set_colour_mode.
//       oc_set_capture(on): SimConfig::captureActivations, so each fish's
//         lastSensors / lastActions (the card's live brain) are kept. It
//         changes no dynamics (ocean_tests "capture"; the harness's
//         withActivations = false fingerprint), only those two arrays. A new
//         world (oc_init / oc_reset) starts with it off; the page sets it again.
//
//   * The appearance genome (OceanConfig::appearance, on by default; COSMETIC:
//     src/ocean/appearance_model.hpp), READ-ONLY, packed by oc_sync:
//       const float* oc_creature_appearance() — oc_appearance_count() rows of
//         oc_appearance_stride() = 63 floats, in oc_creature_segments' order:
//         31 pattern genes, phaseU, phaseV, then 30 shape genes (offset
//         oc_appearance_morph_offset() = 33). Count 0 and a null pointer while
//         appearance is off, or if the side array lost its owners (a direct
//         edit of creatures; oc_appearance_broken() = 1).
//       oc_appearance_abi() 3, oc_appearance_schema() 3, oc_appearance_flags()
//         (bit 1 patterns, bit 2 shapes), oc_appearance_pattern_genes() 31,
//         oc_appearance_morph_genes() 30, oc_pattern_law() 3,
//         oc_morphology_law() 2, oc_morphology_chart_law() 1: the page renders
//         only a layout and laws it knows.
//     oc_set_param takes the five inheritance knobs live (patternMutation,
//     patternPhaseMutation, patternNovelProbability, morphologyMutation,
//     morphologyNovelProbability, each in [0, 0.25]: offspring from then on);
//     `appearance` itself is set by oc_init: the same value is a no-op, a
//     change is refused (restart to apply).
//
// Compiled with Emscripten into web/evo_ocean.{js,wasm} by wasm/build_ocean.sh
// (-DEVO_WORLD_OCEAN, single-threaded). The page (web/ocean.js) drives it:
// oc_init once, then per frame oc_step(n) -> oc_sync() -> read the buffers.
// Every pointer is valid until the next oc_sync / oc_init; memory can grow, so
// the page re-creates its typed-array views after every sync.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <string>
#include <utility>
#include <vector>

#include "ocean/ocean_config.hpp"
#include "ocean/ocean_world.hpp"

#ifdef __EMSCRIPTEN__
#include <emscripten.h>
#define EVO_EXPORT extern "C" EMSCRIPTEN_KEEPALIVE
#else
#define EVO_EXPORT extern "C"  // native build of the shim, for smoke tests
#endif

namespace {

OceanWorld* g_world = nullptr;
std::string g_error;

std::vector<float>   g_segments;   // N*12: 6 spine points x, y  (= evo_creature_segments)
std::vector<float>   g_depth;      // N
std::vector<float>   g_vz;         // N: Fish::vz (pitch = atan(vz))
std::vector<float>   g_bodyParams; // N*2: bodySize, bodyElong  (= evo_body_params)
std::vector<uint8_t> g_colors;     // N*3: colour, by family or brain (= evo_creature_colors; g_colourMode)
std::vector<double>  g_ids;        // N                           (= evo_creature_ids)
std::vector<float>   g_appearance; // N*63: the appearance genome (empty while off / broken)
std::vector<float>   g_food;       // F*2: x, y                   (= evo_food_xy)
std::vector<float>   g_foodDepth;  // F
std::vector<float>   g_predators;  // P*3: x, y, digestTimer      (= evo_predator_data)
std::vector<float>   g_predDepth;  // P
// [pop, frame, births, deaths, reseeds, depthMean, depthSd, hist0 … hist7]
constexpr int kStatsLen = 7 + ocean::kDepthBins;
double g_stats[kStatsLen] = {};

// What oc_sync puts in g_colors: 1 = by family line (the default), 0 = by
// brain (the genome colour). Display only (oc_set_colour_mode).
int g_colourMode = 1;

struct InitArgs {
    unsigned seed = 0;
    int width = 0, height = 0, population = 0;
    double depth = 0.0;
    std::string cfgJson;
    bool valid = false;
} g_lastInit;

// Copied from wasm/evo_wasm.cpp (display only): a family line's colour from
// its id alone, the same bytes in every build.
void familyColor(std::uint64_t id, std::uint8_t* out) {
    std::uint32_t h = (std::uint32_t)(id ^ (id >> 32));
    h ^= h >> 16; h *= 0x7feb352dU; h ^= h >> 15; h *= 0x846ca68bU; h ^= h >> 16;
    static const int kSat[4] = {200, 165, 225, 185}, kVal[4] = {240, 215, 195, 255};
    const int tone = (int)((h >> 12) & 3u);
    const int s = kSat[tone], v = kVal[tone];
    constexpr int kRedGap = 85;
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

// The defensive clamps main.cpp applies (copied from wasm/evo_wasm.cpp) minus
// its min/max swaps: Ocean refuses a reversed speed or genome-length pair
// (configOk) instead of reordering it, so a live change to one bound can never
// silently move the other. Shared with the harness and the probe
// (ocean_world.hpp clampOceanSimConfig).
void clampConfig(SimConfig& c) { clampOceanSimConfig(c); }

// Every refusal oc_init and oc_set_param share, on the config exactly as the
// engine will hold it (after the JSON's double -> float / int conversion and
// clampConfig): evo_init's (same reasons; see wasm/evo_wasm.cpp), then genome
// lengths, speeds, the live floats, radii vs the world size, and the Ocean
// knobs. Nothing here touches the world; callers replace or change it only
// after this passes.
bool configOk(const SimConfig& cfg, const OceanConfig& oc, int width, int height) {
    if (cfg.reproMaxDistance >= 0.0f && cfg.genomeMaxLength > isolation_detail::ISO_MAX_GENES) {
        g_error = "reproMaxDistance requires genomeMaxLength <= "
                + std::to_string(isolation_detail::ISO_MAX_GENES);
        return false;
    }
    if (!(cfg.bodyMutation >= 0.0f) || !std::isfinite(cfg.bodyMutation)) {
        g_error = "bodyMutation must be finite and >= 0";
        return false;
    }
    if (!(cfg.predatorTraitMutation >= 0.0f) || !std::isfinite(cfg.predatorTraitMutation)) {
        g_error = "predatorTraitMutation must be finite and >= 0";
        return false;
    }
    if (!std::isfinite(cfg.reproSoftWidth) || !std::isfinite(cfg.reproGracePeriod) ||
        !std::isfinite(cfg.reproMaxDistance)) {
        g_error = "reproMaxDistance, reproSoftWidth and reproGracePeriod must be finite (negative = off)";
        return false;
    }
    // Genome lengths: makeRandomGenome reserves genomeInitMin..Max genes and
    // children are held to genomeMinLength..MaxLength.
    if (!(GENOME_MIN_LENGTH <= cfg.genomeMinLength && cfg.genomeMinLength <= cfg.genomeMaxLength &&
          cfg.genomeMaxLength <= GENOME_MAX_LENGTH)) {
        g_error = "genome lengths need " + std::to_string(GENOME_MIN_LENGTH) +
                  " <= genomeMinLength <= genomeMaxLength <= " + std::to_string(GENOME_MAX_LENGTH);
        return false;
    }
    if (!(cfg.genomeMinLength <= cfg.genomeInitMin && cfg.genomeInitMin <= cfg.genomeInitMax &&
          cfg.genomeInitMax <= cfg.genomeMaxLength)) {
        g_error = "genome lengths need genomeMinLength <= genomeInitMin <= genomeInitMax <= genomeMaxLength";
        return false;
    }
    // Speeds: the OWN_SPEED sensor is speed / maxSpeed.
    if (!std::isfinite(cfg.minSpeed) || !std::isfinite(cfg.maxSpeed) || !(cfg.minSpeed >= 0.0f) ||
        !(cfg.maxSpeed > 0.0f) || !(cfg.minSpeed <= cfg.maxSpeed)) {
        g_error = "speeds need finite 0 <= minSpeed <= maxSpeed and maxSpeed > 0";
        return false;
    }
    // The other floats oc_set_param can change: a finite double can still
    // overflow to an infinite float.
    const struct { const char* name; float v; } liveFloats[] = {
        {"foodSpawnBase", cfg.foodSpawnBase}, {"foodSpawnAmp", cfg.foodSpawnAmp},
        {"foodEnergy", cfg.foodEnergy}, {"metabolicRate", cfg.metabolicRate},
        {"moveCost", cfg.moveCost}, {"geneCost", cfg.geneCost}, {"maxAge", cfg.maxAge},
        {"reproEnergy", cfg.reproEnergy}, {"newbornEnergy", cfg.newbornEnergy},
        {"mutationMultiplier", cfg.mutationMultiplier},
    };
    for (const auto& f : liveFloats)
        if (!std::isfinite(f.v)) { g_error = std::string(f.name) + " must be finite"; return false; }
    // Radii: finite, >= 0, a finite square, and in a toroidal world
    // < min(width, height) / 2.
    g_error = OceanWorld::radiusError(cfg, width, height);
    if (!g_error.empty()) return false;
    // The Ocean's ranges for SimConfig keys (ocean_config.hpp
    // oceanSimConfigError): the current's knobs, the food-patch radius.
    g_error = oceanSimConfigError(cfg);
    if (!g_error.empty()) return false;
    // Every Ocean knob has a finite range (ocean_config.hpp oceanConfigError,
    // incl. eye / eyeOnly / eyeCode / steerFrame / foodLife): no accepted
    // config can make the state non-finite.
    const std::string oerr = oceanConfigError(oc);
    if (!oerr.empty()) {
        g_error = "ocean config: " + oerr;
        return false;
    }
    // Glass walls and a toroidal world exclude each other (ocean_config.hpp
    // oceanTopologyError).
    g_error = oceanTopologyError(cfg, oc);
    if (!g_error.empty()) return false;
    return true;
}

}  // namespace

// Initialise (or re-initialise) the world. cfgJson may be null/empty for the
// preview defaults, or a flat JSON object of SimConfig keys (the checkpoint
// "config" names) and OceanConfig keys; any subset is accepted. Returns 1, or
// 0 with oc_last_error() set (the previous world, if any, is kept).
EVO_EXPORT int oc_init(unsigned seed, int width, int height, double depth, int population,
                       const char* cfgJson) {
    g_error.clear();
    SimConfig cfg;
    applyOceanDefaults(cfg);
    OceanConfig oc;
    if (!readOceanJson(cfgJson, cfg, oc, g_error)) return 0;
    clampConfig(cfg);
    if (std::isfinite(depth) && depth <= 0.0) depth = OceanConfig{}.depth;
    if (!std::isfinite(depth) || depth < 10.0) {
        g_error = "bad world dimensions or population";
        return 0;
    }
    // Width / height in [100, 1e5], population in [0, 1e5], neighbour grids
    // of at most 2^24 cells (ocean_config.hpp oceanWorldSizeError).
    g_error = oceanWorldSizeError(cfg, width, height, population);
    if (!g_error.empty()) {
        g_error = "bad world dimensions or population: " + g_error;
        return 0;
    }
    oc.depth = (float)depth;
    if (!configOk(cfg, oc, width, height)) return 0;

    // Every refusal is above this line: the old world goes only for a config
    // that passed them all.
    rng.seed(seed);
    delete g_world;
    g_world = new OceanWorld();
    g_world->cfg = cfg;
    g_world->ocfg = oc;
    g_world->init(width, height, (float)depth, population);

    g_lastInit.seed = seed;
    g_lastInit.width = width;
    g_lastInit.height = height;
    g_lastInit.depth = depth;
    g_lastInit.population = population;
    g_lastInit.cfgJson = (cfgJson && cfgJson[0]) ? cfgJson : "";
    g_lastInit.valid = true;
    return 1;
}

// Re-run the last successful oc_init (same seed and config: the run replays
// exactly). Live changes made since with oc_set_param are dropped.
EVO_EXPORT int oc_reset() {
    if (!g_lastInit.valid) { g_error = "oc_reset before any successful oc_init"; return 0; }
    const InitArgs a = g_lastInit;
    return oc_init(a.seed, a.width, a.height, a.depth, a.population,
                   a.cfgJson.empty() ? nullptr : a.cfgJson.c_str());
}

// Advance n fixed steps of dt 0.016 (a step count, never wall-clock time).
EVO_EXPORT void oc_step(int n) {
    if (!g_world) return;
    for (int i = 0; i < n; ++i) g_world->update(0.016f);
}

// Repack every export buffer from the current world state.
EVO_EXPORT void oc_sync() {
    if (!g_world) return;
    const OceanWorld& w = *g_world;
    const size_t n = w.creatures.size();
    g_segments.resize(n * 12);
    g_depth.resize(n);
    g_vz.resize(n);
    g_bodyParams.resize(n * 2);
    g_colors.resize(n * 3);
    g_ids.resize(n);
    for (size_t i = 0; i < n; ++i) {
        const Fish& c = w.creatures[i];
        for (int s = 0; s < Fish::BODY_LEN; ++s) {
            g_segments[i * 12 + s * 2 + 0] = c.body[s].x;
            g_segments[i * 12 + s * 2 + 1] = c.body[s].y;
        }
        g_depth[i] = c.depth;
        g_vz[i] = c.vz;
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
    // The appearance genome: one 63-float row per fish, the same order (the
    // records are bound to creatures[i] by id; checked, never re-bound).
    g_appearance.clear();
    if (w.appearanceFlags() != 0 && w.appearanceConsistent()) {
        const auto& recs = w.appearanceRecords();
        g_appearance.resize(n * appearance::kStride);
        for (size_t i = 0; i < n; ++i)
            std::memcpy(&g_appearance[i * appearance::kStride], recs[i].genome.g, sizeof(float) * appearance::kStride);
    }

    const size_t nf = w.food.size();
    g_food.resize(nf * 2);
    g_foodDepth.resize(nf);
    for (size_t i = 0; i < nf; ++i) {
        g_food[i * 2 + 0] = w.food[i].pos.x;
        g_food[i * 2 + 1] = w.food[i].pos.y;
        g_foodDepth[i] = w.food[i].depth;
    }

    const size_t np = w.predators.size();
    g_predators.resize(np * 3);
    g_predDepth.resize(np);
    for (size_t i = 0; i < np; ++i) {
        g_predators[i * 3 + 0] = w.predators[i].pos.x;
        g_predators[i * 3 + 1] = w.predators[i].pos.y;
        g_predators[i * 3 + 2] = w.predators[i].digestTimer;
        g_predDepth[i] = w.predators[i].depth;
    }

    double mean, sd, hist[ocean::kDepthBins];
    w.depthStats(mean, sd, hist);
    g_stats[0] = (double)n;
    g_stats[1] = (double)w.frame;
    g_stats[2] = (double)w.totalBirths;
    g_stats[3] = (double)w.totalDeaths;
    g_stats[4] = (double)w.totalReseeds;
    g_stats[5] = mean;
    g_stats[6] = sd;
    for (int b = 0; b < ocean::kDepthBins; ++b) g_stats[7 + b] = hist[b];
}

EVO_EXPORT int oc_creature_count()             { return g_world ? (int)g_world->creatures.size() : 0; }
EVO_EXPORT const float* oc_creature_segments() { return g_segments.data(); }
EVO_EXPORT const float* oc_creature_depth()    { return g_depth.data(); }
EVO_EXPORT const float* oc_creature_vz()       { return g_vz.data(); }   // addition, see top
EVO_EXPORT const float* oc_body_params()       { return g_bodyParams.data(); }
EVO_EXPORT const uint8_t* oc_creature_colors() { return g_colors.data(); }
EVO_EXPORT const double* oc_creature_ids()     { return g_ids.data(); }
// The appearance genome (see ADDITIONS): valid until the next oc_sync / oc_init.
EVO_EXPORT int oc_appearance_abi()             { return appearance::kAbi; }
EVO_EXPORT int oc_appearance_schema()          { return appearance::kSchema; }
EVO_EXPORT int oc_appearance_flags()           { return g_world ? g_world->appearanceFlags() : 0; }
EVO_EXPORT int oc_appearance_broken()          { return (g_world && g_world->appearanceBroken()) ? 1 : 0; }
EVO_EXPORT int oc_appearance_pattern_genes()   { return appearance::kPatternGenes; }
EVO_EXPORT int oc_appearance_morph_genes()     { return appearance::kMorphGenes; }
EVO_EXPORT int oc_appearance_morph_offset()    { return appearance::kMorphOffset; }
EVO_EXPORT int oc_appearance_stride()          { return appearance::kStride; }
EVO_EXPORT int oc_pattern_law()                { return appearance::kPatternLaw; }
EVO_EXPORT int oc_morphology_law()             { return appearance::kMorphLaw; }
EVO_EXPORT int oc_morphology_chart_law()       { return appearance::kMorphChart; }
EVO_EXPORT int oc_appearance_count()           { return (int)(g_appearance.size() / appearance::kStride); }
EVO_EXPORT const float* oc_creature_appearance() { return g_appearance.empty() ? nullptr : g_appearance.data(); }
EVO_EXPORT int oc_food_count()                 { return g_world ? (int)g_world->food.size() : 0; }
EVO_EXPORT const float* oc_food_xy()           { return g_food.data(); }
EVO_EXPORT const float* oc_food_depth()        { return g_foodDepth.data(); }
EVO_EXPORT int oc_predator_count()             { return g_world ? (int)g_world->predators.size() : 0; }
EVO_EXPORT const float* oc_predator_data()     { return g_predators.data(); }
EVO_EXPORT const float* oc_predator_depth()    { return g_predDepth.data(); }
EVO_EXPORT const double* oc_stats()            { return g_stats; }
EVO_EXPORT int oc_stats_len()                  { return kStatsLen; }
EVO_EXPORT int oc_width()                      { return g_world ? g_world->width : 0; }
EVO_EXPORT int oc_height()                     { return g_world ? g_world->height : 0; }
EVO_EXPORT double oc_depth_max()               { return g_world ? (double)g_world->D : 0.0; }
// E1 light (display only): on/off, L0 and kWater of L(d) = L0·exp(−kWater·d).
EVO_EXPORT int oc_light_enabled()              { return (g_world && g_world->ocfg.lightEnabled) ? 1 : 0; }
EVO_EXPORT double oc_light_l0()                { return g_world ? (double)g_world->ocfg.L0 : 0.0; }
EVO_EXPORT double oc_light_kwater()            { return g_world ? (double)g_world->ocfg.kWater : 0.0; }
// The E1 preset's cfg JSON (ocean_config.hpp kE1PresetJson): the page's ?e1=1.
EVO_EXPORT const char* oc_e1_preset()          { return kE1PresetJson; }

// Change one parameter of the running world: the Ocean knobs listed at the
// top, or any key evo_set_param accepts (read fresh every step). Values must
// be finite and >= 0, and the config they make must pass oc_init's checks AS
// STORED (pitchMax and maxSpeed > 0 after the float conversion, every float
// finite, minSpeed <= maxSpeed; an integer knob must be a whole number that
// fits an int). Returns 0
// and sets oc_last_error() on refusal, leaving the config unchanged.
EVO_EXPORT int oc_set_param(const char* name, double value) {
    g_error.clear();
    if (!g_world) { g_error = "no world (call oc_init first)"; return 0; }
    static const char* const kOcean[] = {
        "kBuoy", "pitchMax", "vDrag", "wallBand", "buoyMutation", "cHold", "cPress",
        "foodDepthSpread",
        // E1 (bool keys take 0 / 1)
        "waveSpeed", "waveBand", "waveGravity", "deepCurrent", "lightEnabled", "L0", "kWater",
        "depthCostScaled", "sizeDrift", "sizeFight", "mouthGate", "kMouth",
        // the eye build's eye / eyeOnly / eyeCode, the steering frame, the food lifetime, the label frame
        "eye", "eyeOnly", "eyeCode", "steerFrame", "foodLife", "labelFrame",
        // the appearance genome (cosmetic): the master key (init only, see below) and its knobs
        "appearance", "patternMutation", "patternPhaseMutation", "patternNovelProbability",
        "morphologyMutation", "morphologyNovelProbability",
    };
    static const char* const kOceanBool[] = {
        "deepCurrent", "lightEnabled", "depthCostScaled", "sizeDrift", "sizeFight", "mouthGate",
    };
    static const char* const kLive[] = {
        "maxPopulation", "minPopulation", "targetFood", "foodSpawnBase", "foodSpawnAmp",
        "foodEnergy", "metabolicRate", "moveCost", "geneCost", "maxAge", "reproEnergy",
        "newbornEnergy", "mutationMultiplier", "minSpeed", "maxSpeed",
        "predatorMinPopulation", "predatorMaxPopulation", "predatorTraitMutation",
    };
    // The glass walls and appearance are set by oc_init (ocean_config.hpp
    // oceanRestartOnlyError, the harness's --set's policy too): named here so
    // the refusal says so.
    if (name) {
        const std::string why = oceanRestartOnlyError(name, value, g_world->ocfg);
        if (!why.empty()) {
            g_error = why;
            return 0;
        }
    }
    bool live = false;
    for (const char* k : kOcean) if (name && std::strcmp(name, k) == 0) { live = true; break; }
    for (const char* k : kLive)  if (name && std::strcmp(name, k) == 0) { live = true; break; }
    // The int-typed keys: kLive's (maxPopulation, minPopulation, targetFood,
    // predatorMinPopulation, predatorMaxPopulation: readConfig's int keys) and
    // kOcean's (eye, eyeOnly, eyeCode, steerFrame: ocean_config.hpp kOceanIntKeys).
    const bool isInt = name && (isSimConfigIntKey(name) || isOceanIntKey(name));
    if (!live) {
        g_error = std::string("not a live parameter (change it and restart): ") + (name ? name : "(null)");
        return 0;
    }
    if (!std::isfinite(value) || value < 0.0) {
        g_error = std::string(name) + " must be finite and >= 0";
        return 0;
    }
    if (isInt && !isIntValue(value)) {
        g_error = std::string(name) + " must be a whole number that fits an int";   // the JSON reader's (int) cast
        return 0;
    }
    if (std::strcmp(name, "pitchMax") == 0 && !(value > 0.0)) {
        g_error = "pitchMax must be > 0";
        return 0;
    }
    for (const char* k : kOceanBool)
        if (std::strcmp(name, k) == 0 && value != 0.0 && value != 1.0) {
            g_error = std::string(name) + " is on / off: 0 or 1";
            return 0;
        }
    // The value as JSON text: an int key as its exact integer ("%.9g" turned
    // 2147483647 into 2.14748365e+09 > INT_MAX, an undefined cast in the
    // reader), any other key "%.9g".
    char num[40];
    if (isInt) std::snprintf(num, sizeof num, "%lld", (long long)value);   // a whole number in [0, INT_MAX] here
    else       std::snprintf(num, sizeof num, "%.9g", value);
    const std::string json = std::string("{\"") + name + "\":" + num + "}";
    SimConfig cfg = g_world->cfg;
    OceanConfig oc = g_world->ocfg;
    std::string err;
    if (!readOceanJson(json.c_str(), cfg, oc, err)) { g_error = "internal: " + err; return 0; }
    clampConfig(cfg);
    // Check what was stored, not the double: 1e-100 is a 0 float, 1e300 an
    // infinite one.
    if (!configOk(cfg, oc, g_world->width, g_world->height)) {
        g_error = std::string(name) + " = " + num + " refused (as stored): " + g_error;
        return 0;
    }
    g_world->cfg = cfg;
    g_world->ocfg = oc;
    return 1;
}

EVO_EXPORT const char* oc_last_error() { return g_error.c_str(); }

// 1 in the eye build (the EYE_* sensors exist; "eye" may be 1), else 0.
EVO_EXPORT int oc_has_eye() { return kOceanHasEye ? 1 : 0; }

// The world's side faces: 1 = glass walls (OceanConfig::walls, set by
// oc_init), 0 = wrapping (or no world). Its presence is the page's capability
// check: a module without it has no walls key.
EVO_EXPORT int oc_walls_enabled() { return (g_world && g_world->ocfg.walls) ? 1 : 0; }

// ---- The page's controls: READ-ONLY exports, two display switches ----------
// (see ADDITIONS at the top). Nothing below writes anything the step reads,
// draws from the rng or changes the world's run state.
namespace {
std::string g_sensorNamesCsv, g_actionNamesCsv;   // ocean::kSensorNames / kActionNames, joined

// oc_inspect: 13 doubles, in this order (web/ocean.js INSPECT reads them):
//   id, speed, foodReserves, age, bodySize, bodyElong, generation, lineageId,
//   depth, bodyBuoy (neutral depth / D), vz, genes (genome length), reproTimer
constexpr int kInspectLen = 13;
double g_inspInfo[kInspectLen] = {};
std::vector<float> g_inspSensors;   // NUM_SENSES (lastSensors: 0 unless oc_set_capture(1))
std::vector<float> g_inspHidden;    // MAX_INTERNAL_NEURONS (neuron outputs)
std::vector<float> g_inspActions;   // NUM_ACTIONS (lastActions: as lastSensors)
std::vector<float> g_inspConns;     // K*5: srcIsSensor, srcNum, sinkIsAction, sinkNum, weight

// oc_summary: 22 doubles, in this order (web/ocean.js SUMMARY reads them):
//    0 food, 1 predators,
//    2 deaths by predation, 3 by starvation, 4 by age (cumulative, the run's),
//    5 predator births, 6 predator deaths by starvation, 7 by age,
//    8 predators the floor added (cumulative),
//    9 mean energy (foodReserves), 10 mean age, 11 mean speed,
//   12 mean generation, 13 max generation,
//   14 mean bodyBuoy, 15 its sd, 16 mean bodySize, 17 mean bodyElong,
//   18 mean genome length, 19 family lines alive, 20 mean predator energy,
//   21 mean |vz|
// (means over the live fish; 0 with none)
constexpr int kSummaryLen = 22;
double g_summary[kSummaryLen] = {};

std::vector<double> g_families;     // pairs: lineageId, fish alive in it
std::vector<float>  g_wiring;       // 2 * NUM_SENSES * NUM_ACTIONS
}  // namespace

EVO_EXPORT int oc_num_senses()  { return NUM_SENSES; }
EVO_EXPORT int oc_num_actions() { return NUM_ACTIONS; }
EVO_EXPORT int oc_num_hidden()  { return MAX_INTERNAL_NEURONS; }
// Comma-separated, in enum order (the engine's ocean::kSensorNames / kActionNames).
EVO_EXPORT const char* oc_sensor_names() {
    if (g_sensorNamesCsv.empty())
        for (int s = 0; s < NUM_SENSES; ++s) { if (s) g_sensorNamesCsv += ','; g_sensorNamesCsv += ocean::kSensorNames[s]; }
    return g_sensorNamesCsv.c_str();
}
EVO_EXPORT const char* oc_action_names() {
    if (g_actionNamesCsv.empty())
        for (int a = 0; a < NUM_ACTIONS; ++a) { if (a) g_actionNamesCsv += ','; g_actionNamesCsv += ocean::kActionNames[a]; }
    return g_actionNamesCsv.c_str();
}

// Snapshot fish i (an index into this sync's arrays, valid until the next
// oc_step / oc_sync) for the fish card. Returns 0 for an index out of range.
EVO_EXPORT int oc_inspect(int index) {
    if (!g_world || index < 0 || (size_t)index >= g_world->creatures.size()) return 0;
    const Fish& c = g_world->creatures[(size_t)index];
    g_inspInfo[0] = (double)c.id;
    g_inspInfo[1] = (double)c.speed;
    g_inspInfo[2] = (double)c.foodReserves;
    g_inspInfo[3] = (double)c.age;
    g_inspInfo[4] = (double)c.bodySize;
    g_inspInfo[5] = (double)c.bodyElong;
    g_inspInfo[6] = (double)c.generation;
    g_inspInfo[7] = (double)c.lineageId;
    g_inspInfo[8] = (double)c.depth;
    g_inspInfo[9] = (double)c.bodyBuoy;
    g_inspInfo[10] = (double)c.vz;
    g_inspInfo[11] = (double)c.genome.size();
    g_inspInfo[12] = (double)c.reproTimer;
    g_inspSensors.assign(c.lastSensors, c.lastSensors + NUM_SENSES);
    g_inspActions.assign(c.lastActions, c.lastActions + NUM_ACTIONS);
    g_inspHidden.assign(MAX_INTERNAL_NEURONS, 0.0f);
    for (int i = 0; i < MAX_INTERNAL_NEURONS && (size_t)i < c.nnet.neurons.size(); ++i)
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
EVO_EXPORT const double* oc_inspect_info()   { return g_inspInfo; }
EVO_EXPORT int oc_inspect_len()               { return kInspectLen; }
EVO_EXPORT const float* oc_inspect_sensors() { return g_inspSensors.data(); }
EVO_EXPORT const float* oc_inspect_hidden()  { return g_inspHidden.data(); }
EVO_EXPORT const float* oc_inspect_actions() { return g_inspActions.data(); }
EVO_EXPORT int oc_inspect_conn_count()       { return (int)(g_inspConns.size() / 5); }
EVO_EXPORT const float* oc_inspect_conns()   { return g_inspConns.data(); }

// Population means and the run's counters (layout at kSummaryLen). Reads the
// world directly: no oc_sync needed.
EVO_EXPORT const double* oc_summary() {
    std::fill(g_summary, g_summary + kSummaryLen, 0.0);
    if (!g_world) return g_summary;
    const OceanWorld& w = *g_world;
    g_summary[0] = (double)w.food.size();
    g_summary[1] = (double)w.predators.size();
    g_summary[2] = (double)w.totalDeathsPredation;
    g_summary[3] = (double)w.totalDeathsStarvation;
    g_summary[4] = (double)w.totalDeathsAge;
    g_summary[5] = (double)w.totalPredatorBirths;
    g_summary[6] = (double)w.totalPredatorDeathsStarvation;
    g_summary[7] = (double)w.totalPredatorDeathsAge;
    g_summary[8] = (double)w.totalPredatorReseeds;
    const size_t n = w.creatures.size();
    if (n) {
        double e = 0, age = 0, spd = 0, gen = 0, gmax = 0, bb = 0, bb2 = 0, bs = 0, be = 0, gl = 0, avz = 0;
        std::vector<std::uint64_t> lines;
        lines.reserve(n);
        for (const Fish& c : w.creatures) {
            e += c.foodReserves; age += c.age; spd += c.speed;
            gen += c.generation; gmax = std::max(gmax, (double)c.generation);
            bb += c.bodyBuoy; bb2 += (double)c.bodyBuoy * c.bodyBuoy;
            bs += c.bodySize; be += c.bodyElong; gl += (double)c.genome.size();
            avz += std::fabs((double)c.vz);
            lines.push_back(c.lineageId);
        }
        const double inv = 1.0 / (double)n;
        g_summary[9] = e * inv; g_summary[10] = age * inv; g_summary[11] = spd * inv;
        g_summary[12] = gen * inv; g_summary[13] = gmax;
        const double mb = bb * inv;
        g_summary[14] = mb; g_summary[15] = std::sqrt(std::max(0.0, bb2 * inv - mb * mb));
        g_summary[16] = bs * inv; g_summary[17] = be * inv; g_summary[18] = gl * inv;
        std::sort(lines.begin(), lines.end());
        g_summary[19] = (double)(std::unique(lines.begin(), lines.end()) - lines.begin());
        g_summary[21] = avz * inv;
    }
    if (!w.predators.empty()) {
        double pe = 0;
        for (const auto& p : w.predators) pe += p.energy;
        g_summary[20] = pe / (double)w.predators.size();
    }
    return g_summary;
}
EVO_EXPORT int oc_summary_len() { return kSummaryLen; }

// The k biggest family lines alive (ties: the lower id first), as pairs
// (lineageId, fish) in oc_families_data. Returns how many pairs.
EVO_EXPORT int oc_families(int k) {
    g_families.clear();
    if (!g_world || k <= 0) return 0;
    std::vector<std::uint64_t> lines;
    lines.reserve(g_world->creatures.size());
    for (const Fish& c : g_world->creatures) lines.push_back(c.lineageId);
    std::sort(lines.begin(), lines.end());
    std::vector<std::pair<long long, std::uint64_t>> runs;   // (-count, id): sorts biggest first
    for (size_t i = 0; i < lines.size();) {
        size_t j = i;
        while (j < lines.size() && lines[j] == lines[i]) ++j;
        runs.push_back({-(long long)(j - i), lines[i]});
        i = j;
    }
    const size_t m = std::min(runs.size(), (size_t)k);
    std::partial_sort(runs.begin(), runs.begin() + (long)m, runs.end());
    for (size_t i = 0; i < m; ++i) {
        g_families.push_back((double)runs[i].second);
        g_families.push_back((double)-runs[i].first);
    }
    return (int)m;
}
EVO_EXPORT const double* oc_families_data() { return g_families.data(); }

// A family line's colour as 0xRRGGBB: the one its fish get by family.
EVO_EXPORT int oc_family_color(double lineageId) {
    std::uint8_t c[3];
    familyColor((std::uint64_t)lineageId, c);
    return (c[0] << 16) | (c[1] << 8) | c[2];
}

// Which senses reach which actions, over the live set: [0] the share of fish
// with a path from sensor s to action a (directly or through hidden neurons),
// [1] the share with a direct connection. Row-major, sensor rows. Returns the
// fish counted. (wasm/evo_wasm.cpp evo_wiring, for the Ocean's brain shape.)
EVO_EXPORT int oc_wiring() {
    constexpr int S = NUM_SENSES, A = NUM_ACTIONS, H = MAX_INTERNAL_NEURONS;
    static_assert(A <= 32, "the action bit sets are 32 bits");
    g_wiring.assign(2 * S * A, 0.0f);
    if (!g_world || g_world->creatures.empty()) return 0;
    std::vector<long> path(S * A, 0), direct(S * A, 0);
    for (const Fish& c : g_world->creatures) {
        std::uint32_t reach[H] = {};   // actions reachable from hidden neuron h
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
EVO_EXPORT const float* oc_wiring_data() { return g_wiring.data(); }

// Display switches (see ADDITIONS): colours from the next oc_sync; the live
// brain's lastSensors / lastActions from the next step.
EVO_EXPORT void oc_set_colour_mode(int mode) { g_colourMode = mode == 0 ? 0 : 1; }
EVO_EXPORT void oc_set_capture(int on) {
    if (g_world) g_world->cfg.captureActivations = on != 0;
}

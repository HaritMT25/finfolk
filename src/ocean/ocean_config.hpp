#pragma once
// ----------------------------------------------------------------------------
// ocean_config — the Ocean world's own settings, kept OUT of SimConfig so
// Classic's CLI and checkpoint keys stay what they are (PLAN_ecosystem §14.1).
// OceanWorld holds one beside WorldCommon::cfg. readOceanConfig takes the same
// flat JSON object the shim hands checkpoint::readConfig, so one cfgJson can
// carry SimConfig keys and these together.
//
// applyOceanDefaults is the Ocean preview's starting point for the SimConfig
// half (PLAN_ocean_preview §6: 3-D contact rates fall, so the ranges grow and
// the food stock grows; the spawn rate is unchanged). The shim and the probe
// both call it before reading any JSON, so the page gets the tuned world
// without passing anything.
//
// E1 physics (PLAN_ecosystem §4, §5.1-5.2; the reviewed E1 design): waves,
// depth-weighted deep currents, the light field (display only), depth costs
// as multiples of metabolism, and the size laws (drift, fights, mouth). Every
// E1 knob defaults OFF, and with all of them off the world is bit-identical to
// the preview's (oceanE1AtDefaults; the harness's OFF-identity cases).
//
// The compound eye (eye, eyeOnly, eyeCode: the eye build -DEVO_OCEAN_EYE
// only), own-frame steering (steerFrame) and the food lifetime (foodLife)
// default OFF as well; off, the world is bit-identical to the one before they
// existed. So do the glass walls (walls, sideWallBand, sideWallTurnRate; set
// at init only, and never with toroidal: oceanTopologyError).
//
// Every knob has a finite RANGE (oceanConfigError): no accepted config can
// make the state non-finite. The ranges are wide — every harness case and
// unit-test world is inside them — but bounded, e.g. kBuoy = -1e37 used to be
// accepted and overflowed vz to inf - inf = NaN within 50 steps.
// ----------------------------------------------------------------------------
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include "../core/config.hpp"
#include "../core/json_min.hpp"
#include "../core/checkpoint_io.hpp"   // checkpoint::readConfig: SimConfig's JSON keys

struct OceanConfig {
    float depth        = 240.0f;  // D: sea depth (0 = surface). oc_init's depth argument.
    float kBuoy        = 1.0f;    // buoyancy pull toward bodyBuoy·D, per second. Plan
                                  // start 0.5; 1.0 tuned (ocean_probe, 9 seeds x 30k):
                                  // both pass, 1.0 sweeps NEAREST_FOOD_DZ -> STEER_Z
                                  // more often (leaving neutral depth costs steering)
    float buoyMutation = 0.05f;   // half-width of the newborn's bodyBuoy draw
    float pitchMax     = 0.5f;    // |vz| ceiling (vz is a pitch: depth rate = vz·speed)
    float vDrag        = 2.0f;    // vertical drag, 1/s
    float wallBand     = 12.0f;   // soft push within this distance of surface / floor
    // Depth costs, after kernel::stepMetabolism, evaluated only when one is != 0.
    // H = |depth − bodyBuoy·D| / D (off neutral), P = depth / D (pressure).
    //   depthCostScaled false (the preview's): energy/s per unit H / P
    //   depthCostScaled true  (E1): dimensionless multiples of the fish's own
    //     metabolism M = metabolicRate·massFactor (bodySize):
    //     foodReserves −= dt·M·(cHold·H + cPress·P)
    float cHold        = 0.0f;
    float cPress       = 0.0f;
    // Where food appears in depth:
    //   0 = uniform over [0, D]
    //   1 = per patch: every food patch (SimConfig::foodPatches > 0) gets its own
    //       depth at init; food lands within ±foodDepthSpread of it (uniform if
    //       there are no patches)
    int   foodDepthMode   = 0;
    float foodDepthSpread = 30.0f;

    // ---- E1 physics: every knob below defaults OFF -------------------------
    // Waves: three fixed deep-water trains, modes (6,0) (2,3) (4,−2) over the
    // world, amplitude fractions .5/.3/.2 of waveSpeed, phases 0/1/2 rad, ω =
    // sqrt(waveGravity·k); tapered to zero normal flow at surface and floor
    // over b = min(waveBand, D/4). No randomness.
    float waveSpeed   = 0.0f;     // orbital speed scale, units/s (0 = no waves)
    float waveBand    = 32.0f;    // taper band (units)
    float waveGravity = 20.0f;    // dispersion constant (ω² = g·k)
    // The current (SimConfig current*) as a deep current: horizontal flow ×
    // f(d) = smoothstep(2d/D): still at the surface, full from mid-depth down.
    bool  deepCurrent = false;
    // Light (display only in E1: the page's depth shading). L(d) = L0·exp(−kWater·d).
    bool  lightEnabled = false;
    float L0          = 1.0f;
    float kWater      = 0.006f;   // 1/unit
    bool  depthCostScaled = false;  // see cHold / cPress
    // Size laws (L = bodySize): the flow moves a fish by min(1, 1/L) of itself;
    // fight strength × L²; a fish eats food only if food.size <= kMouth·L.
    bool  sizeDrift   = false;
    bool  sizeFight   = false;
    bool  mouthGate   = false;
    float kMouth      = 2.0f;

    // ---- the compound eye, steering frame, food lifetime (ocean-vision):
    // every key below defaults OFF too ------------------------------------------
    // The compound eye (the EYE_* sensors; ocean_world.hpp "compound eye"):
    // 0 = off, 1 = on. Only the eye build (-DEVO_OCEAN_EYE) has the sensors,
    // so anywhere else it must stay 0 (oceanConfigError). Off, the eye inputs
    // read 0 — the same as six empty sectors — and cost nothing per object.
    int   eye             = 0;
    // Eye-only mode (the eye build only; 0 = off, 1 = on): the LABELED
    // exteroceptive senses — the ones the eye replaces: food direction /
    // distance / density, the predator bearing, the neighbour offsets,
    // headings, counts and attributes, the long probe — read 0 and are not
    // computed (ocean::kLabeledSenses, ocean_world.hpp). Own state,
    // proprioception, pheromones, the current and RANDOM_SENSOR stay. With
    // eye = 1 the fish see only through the compound eye; with eye = 0
    // ("blind") they sense nothing outside their own body but the pheromone
    // column and the current. The pairwise interaction vote's own contact
    // inputs (kernel::interactionVote) are not senses and are unchanged.
    int   eyeOnly         = 0;
    // The compound eye's encoding (the eye build only, like eye): a bitmask,
    // 0 = the eye as ocean_world.hpp's header describes it (bit-identical to
    // the build before this key existed). No effect while eye is 0. The 18
    // EYE_* inputs keep their names; what they report (ocean_world.hpp,
    // "eyeCode"):
    //   1 faded contrast: CON = PROX x (b − L(z)), fading to 0 at R
    //   2 opponent pairs: the LEFT slot reports left + right and the RIGHT
    //     slot right − left, UP up + down and DOWN down − up, per feature
    //     (invertible: one wire can steer both ways)
    //   4 summed sectors: each sector sums over every object in it (squashed
    //     x / (1 + |x|)) instead of reporting only the nearest
    // and two ablation bits (the "cloaked" eye: which kinds of object the eye
    // bins at all; the labeled senses are unchanged):
    //   8 the eye ignores fish (it sees food and predators)
    //   16 the eye ignores food (it sees fish and predators)
    // So 0..31; predators are always seen.
    int   eyeCode         = 0;
    // The frame STEER_X / STEER_Y push in (the non-triangular motion model):
    // 0 = world x / y, Classic's (and NEAREST_FOOD_DX / DY's) frame;
    // 1 = the fish's own frame: STEER_X along its right axis (the "right" of the
    //     compound eye and PREDATOR_LR), STEER_Y along its heading. The same push
    //     turned into body coordinates, so a sense in the fish's frame can turn it
    //     toward what it senses. The heading is renormalised after the push, so
    //     STEER_Y alone no longer turns the fish (it only scales STEER_X's turn,
    //     by up to ±5%): turning is STEER_X's, as under triangular motion (which
    //     already turns by STEER_X and ignores this).
    int   steerFrame      = 0;
    // Food lifetime in seconds (0 = off: food lasts until eaten; range [0,
    // kOceanMaxFoodLife = 3600]). On, every item is removed foodLife seconds
    // after it appeared, eaten or not (it sinks out or decays). With a fixed
    // inflow, food the fish do not find is lost, so how many fish a world can
    // feed depends on how well they search. The world's first stock gets ages
    // spread evenly over [0, foodLife) so it does not all vanish at once. No
    // draws.
    float foodLife        = 0.0f;
    // The frame the LABELED direction senses report in (the ALIFE 2027
    // protocol's A1 arm: labels matched to the steering frame):
    // 0 = world x / y (every run before this key; the default);
    // 1 = the fish's own frame, steerFrame 1's convention (x = right, y = ahead
    //     of the horizontal heading): NEAREST_FOOD_DX / DY (the unit vector's
    //     horizontal part, projected), AVG_NEIGHBOR_DX / DY (the mean offset
    //     projected BEFORE its tanh) and AVG_NEIGHBOR_HEADING_X / Y (the mean
    //     neighbour velocity, projected). The vertical parts (..._DZ) and every
    //     scalar are unchanged; the senses already in the body frame
    //     (PREDATOR_FWD / LR, POPULATION_FWD / LR, GENETIC_SIM_FWD, ...) are not
    //     rotated again; proprioception (OWN_VEL_*, LAST_MOVE_DIR_*) stays world
    //     x / y. No draws. Valid 0..1 in both builds.
    int   labelFrame      = 0;

    // ---- the appearance genome (src/ocean/appearance_model.hpp): COSMETIC ----
    // Every fish carries 63 appearance floats (31 skin-pattern genes + 2
    // maternal phases + 30 body-shape genes), built for founders and inherited
    // by offspring from each fish's own counter-based stream — never the
    // simulation's rng — and read by nothing the step computes. ON by default:
    // it changes no trajectory, draw or counter (the harness's app_off_*
    // twins), and the page renders it.
    //   appearance: bit 1 = patterns (P1), bit 2 = body shapes (M1); 3 = both,
    //     0 = off (no records, nothing exported). Set at init only: a live
    //     change is refused (the same value is a no-op).
    // The inheritance knobs apply to offspring constructed from then on (live).
    // Each in [0, 0.25]:
    int   appearance                 = 3;
    float patternMutation            = 0.025f;   // ± jitter on every pattern gene
    float patternPhaseMutation       = 0.030f;   // ± drift of the maternal phases
    float patternNovelProbability    = 0.050f;   // per pattern group: a new founder allele
    float morphologyMutation         = 0.025f;   // ± jitter on every shape gene
    float morphologyNovelProbability = 0.050f;   // per shape group: a new founder allele

    // ---- glass walls (walls_bigtank design): default OFF ---------------------
    // walls: the four side faces x = 0, W and y = 0, H are glass. Off (the
    // default), x / y wrap as they always did and every result is the one
    // before this key existed. On: fish and predators turn away inside
    // sideWallBand of a face (a bounded rotation of the heading toward the
    // inward normal, up to sideWallTurnRate x the band depth rad/s), are
    // clamped at contact with the outward heading component reflected; food
    // spawns inside the tank and rides a midpoint transport that mirror-folds
    // excursions (never projected onto the glass); the water's flow is the
    // wall-compatible one (standing wave modes, streamfunction currents
    // tapered to zero at the faces: no normal flow through any of the six).
    // Needs toroidal = false (oceanTopologyError). No draws are added or
    // moved. All three are set at init (oc_set_param refuses a change).
    bool  walls            = false;
    float sideWallBand     = 80.0f;   // soft-turn band per side face, units ([0, 1e5]; 0 = contact only)
    float sideWallTurnRate = 6.0f;    // rad/s at full band depth ([0, 1000]; 0 = contact only)
};

// OceanConfig::labelFrame exists (tools test for it: an engine without the key
// must refuse a label-frame arm rather than run it as A0).
#define EVO_HAS_LABEL_FRAME 1

// Does this build have the compound eye's sensors?
#ifdef EVO_OCEAN_EYE
inline constexpr bool kOceanHasEye = true;
#else
inline constexpr bool kOceanHasEye = false;
#endif

// OceanConfig::eyeCode's bits: three encodings, two cloaks.
inline constexpr int kEyeCodeFaded    = 1;   // CON = PROX x (b − L)
inline constexpr int kEyeCodeOpponent = 2;   // left/right, up/down as sum and difference
inline constexpr int kEyeCodeSummed   = 4;   // every object in a sector, not the nearest
inline constexpr int kEyeCodeAll      = kEyeCodeFaded | kEyeCodeOpponent | kEyeCodeSummed;   // every encoding
inline constexpr int kEyeCodeNoFish   = 8;   // the eye does not bin fish
inline constexpr int kEyeCodeNoFood   = 16;  // the eye does not bin food
inline constexpr int kEyeCodeCloaks   = kEyeCodeNoFish | kEyeCodeNoFood;
inline constexpr int kEyeCodeMax      = kEyeCodeAll | kEyeCodeCloaks;   // 31: every bit
inline constexpr bool eyeCodeValid(int code) {
    return code == 0 || (kOceanHasEye && code > 0 && code <= kEyeCodeMax);
}

// x is a whole number in int's range (so (int)x is defined and exact). NaN and
// ±inf fail.
inline bool isIntValue(double x) {
    return x >= -2147483648.0 && x <= 2147483647.0 && std::trunc(x) == x;
}

// True when every E1 knob holds its default (OFF) value, bit for bit. The
// fingerprint hashes the E1 knobs only when this is false, so a preview config
// hashes exactly as it did before E1.
inline bool oceanE1AtDefaults(const OceanConfig& c) {
    const OceanConfig d;
    auto same = [](float a, float b) { return std::memcmp(&a, &b, sizeof a) == 0; };
    return same(c.waveSpeed, d.waveSpeed) && same(c.waveBand, d.waveBand) &&
           same(c.waveGravity, d.waveGravity) && c.deepCurrent == d.deepCurrent &&
           c.lightEnabled == d.lightEnabled && same(c.L0, d.L0) && same(c.kWater, d.kWater) &&
           c.depthCostScaled == d.depthCostScaled && c.sizeDrift == d.sizeDrift &&
           c.sizeFight == d.sizeFight && c.mouthGate == d.mouthGate && same(c.kMouth, d.kMouth);
}

namespace ocean_cfg_detail {
// A bool key: true / false, or the numbers 0 / 1 (oc_set_param's "%.9g" text).
// Anything else under the key is an error. Absent = unchanged.
inline bool readBool(const jsonm::Value& o, const char* k, bool& out, std::string* err) {
    const jsonm::Value* v = o.find(k);
    if (!v) return true;
    if (v->type == jsonm::Value::Type::Bool) { out = v->b; return true; }
    if (v->type == jsonm::Value::Type::Number && (v->num == 0.0 || v->num == 1.0)) {
        out = (v->num == 1.0);
        return true;
    }
    if (err) *err = std::string(k) + " must be true / false (or 0 / 1)";
    return false;
}
}  // namespace ocean_cfg_detail

// Every key defaults to the value already in `c` (the checkpoint reader's rule).
// `o` is the flat config object itself, not a {"config": ...} wrapper. "depth"
// is not read: oc_init's argument sets it. Returns false (err set) when a bool
// key holds something other than true / false / 0 / 1; ranges are
// oceanConfigError's.
inline bool readOceanConfig(const jsonm::Value& o, OceanConfig& c, std::string* err = nullptr) {
    if (!o.isObject()) return true;
    c.kBuoy           = o.floatOr("kBuoy", c.kBuoy);
    c.buoyMutation    = o.floatOr("buoyMutation", c.buoyMutation);
    c.pitchMax        = o.floatOr("pitchMax", c.pitchMax);
    c.vDrag           = o.floatOr("vDrag", c.vDrag);
    c.wallBand        = o.floatOr("wallBand", c.wallBand);
    c.cHold           = o.floatOr("cHold", c.cHold);
    c.cPress          = o.floatOr("cPress", c.cPress);
    // Only 0 and 1 are modes; any other number is kept as -1, which the
    // validator refuses (an (int) cast of 1e300 would be undefined).
    if (const jsonm::Value* v = o.find("foodDepthMode"); v && v->type == jsonm::Value::Type::Number)
        c.foodDepthMode = (v->num == 0.0) ? 0 : (v->num == 1.0) ? 1 : -1;
    c.foodDepthSpread = o.floatOr("foodDepthSpread", c.foodDepthSpread);
    // E1
    c.waveSpeed   = o.floatOr("waveSpeed", c.waveSpeed);
    c.waveBand    = o.floatOr("waveBand", c.waveBand);
    c.waveGravity = o.floatOr("waveGravity", c.waveGravity);
    c.L0          = o.floatOr("L0", c.L0);
    c.kWater      = o.floatOr("kWater", c.kWater);
    c.kMouth      = o.floatOr("kMouth", c.kMouth);
    // The eye, steering frame, food lifetime. The int keys (kOceanIntKeys): a
    // whole number in int's range is read exactly (readOceanJson has already
    // refused any other number under them); any other number is kept as -1,
    // which oceanConfigError refuses — never an (int) cast of 0.5 or 1e300.
    auto readInt = [&](const char* k, int& out) {
        if (const jsonm::Value* v = o.find(k); v && v->type == jsonm::Value::Type::Number)
            out = isIntValue(v->num) ? (int)v->num : -1;
    };
    readInt("eye", c.eye);
    readInt("eyeOnly", c.eyeOnly);
    readInt("eyeCode", c.eyeCode);
    readInt("steerFrame", c.steerFrame);
    c.foodLife    = o.floatOr("foodLife", c.foodLife);
    readInt("labelFrame", c.labelFrame);
    readInt("appearance", c.appearance);
    c.patternMutation            = o.floatOr("patternMutation", c.patternMutation);
    c.patternPhaseMutation       = o.floatOr("patternPhaseMutation", c.patternPhaseMutation);
    c.patternNovelProbability    = o.floatOr("patternNovelProbability", c.patternNovelProbability);
    c.morphologyMutation         = o.floatOr("morphologyMutation", c.morphologyMutation);
    c.morphologyNovelProbability = o.floatOr("morphologyNovelProbability", c.morphologyNovelProbability);
    c.sideWallBand     = o.floatOr("sideWallBand", c.sideWallBand);
    c.sideWallTurnRate = o.floatOr("sideWallTurnRate", c.sideWallTurnRate);
    using ocean_cfg_detail::readBool;
    return readBool(o, "deepCurrent", c.deepCurrent, err) &&
           readBool(o, "lightEnabled", c.lightEnabled, err) &&
           readBool(o, "depthCostScaled", c.depthCostScaled, err) &&
           readBool(o, "sizeDrift", c.sizeDrift, err) &&
           readBool(o, "sizeFight", c.sizeFight, err) &&
           readBool(o, "mouthGate", c.mouthGate, err) &&
           readBool(o, "walls", c.walls, err);
}

// True when the glass-wall keys hold their defaults (walls off, both side
// knobs bit for bit at 80 / 6): the fingerprint hashes them only otherwise,
// so a config without them hashes exactly as before they existed.
inline bool oceanWallsAtDefaults(const OceanConfig& c) {
    const OceanConfig d;
    auto same = [](float a, float b) { return std::memcmp(&a, &b, sizeof a) == 0; };
    return c.walls == d.walls && same(c.sideWallBand, d.sideWallBand) && same(c.sideWallTurnRate, d.sideWallTurnRate);
}

// The preview's SimConfig starting point (tuned with tools/ocean_probe.cpp).
inline void applyOceanDefaults(SimConfig& c) {
    c.perceptionRadius = 100.0f;
    c.interactRadius   = 36.0f;
    c.pickupRadius     = 24.0f;
    c.targetFood       = 2400;
}

// The E1 preset (tools/ocean_probe.cpp tuning, see the E1 report): waves, deep
// currents, light and depth costs on top of the preview defaults. A flat cfg
// JSON like any other; the page applies it with ?e1=1 (oc_e1_preset), the
// probe with --e1, and wasm/ocean_parity.sh runs it as a case (its copy is
// checked against this text).
inline constexpr const char* kE1PresetJson =
    R"({"waveSpeed":6,"deepCurrent":true,"currentStrength":5,"foodDrift":true,"lightEnabled":true,"depthCostScaled":true,"cHold":0.05,"cPress":0.03})";

// The int-typed SimConfig keys: checkpoint::readConfig reads each with
// jsonm::Value::intOr, a plain (int) cast of the JSON double, which is
// undefined behaviour outside int's range (x86 gives INT_MIN, wasm traps or
// saturates) and silently truncates a fraction ({"currentMode":0.5} was mode
// 0). readOceanJson refuses any such value before the reader sees it: the
// number must be a whole number in int's range. Must list exactly
// readConfig's intOr keys: wasm/ocean_parity.sh checks it.
inline constexpr const char* kSimConfigIntKeys[] = {
    "reproWindow", "reproMinCluster", "minPopulation", "maxPopulation", "targetFood",
    "maxNeighbors", "genomeMinLength", "genomeMaxLength", "genomeInitMin", "genomeInitMax",
    "currentMode", "currentEddies", "foodPatches", "predatorCount",
    "predatorMinPopulation", "predatorMaxPopulation",
};
inline bool isSimConfigIntKey(const std::string& k) {
    for (const char* i : kSimConfigIntKeys) if (k == i) return true;
    return false;
}
// The int-typed OceanConfig keys the cfg JSON may carry (readOceanConfig
// reads each without a raw cast): readOceanJson holds them to the same rule
// as kSimConfigIntKeys — a whole number in int's range, every occurrence — so
// {"eye":0.5} or {"eyeCode":1e300} is refused with that message, not stored.
// (foodDepthMode keeps its own 0 / 1 / -1 read; its ranges, and these keys',
// are oceanConfigError's.)
inline constexpr const char* kOceanIntKeys[] = {"foodDepthMode", "eye", "eyeOnly", "eyeCode", "steerFrame", "appearance",
                                                "labelFrame"};
inline bool isOceanIntKey(const std::string& k) {
    for (const char* i : kOceanIntKeys) if (k == i) return true;
    return false;
}

// The bool-typed SimConfig keys: checkpoint::readConfig reads each with
// jsonm::Value::boolOr, which keeps the old value for anything but a JSON
// bool, silently — {"toroidal":1} ran with walls while the page showed it on.
// readOceanJson refuses any other value at every occurrence: a SimConfig
// switch is a JSON true / false (they are restart settings, never written by
// oc_set_param; the page refuses anything else too). The Ocean's own bool keys
// (readOceanConfig's readBool) keep their rule — true / false or exactly the
// number 0 / 1, the "%.9g" text oc_set_param and the harness's --set write —
// now held at every occurrence (readBool saw only a key's first).
// kSimConfigBoolKeys must list exactly readConfig's boolOr keys, and
// kOceanBoolKeys readOceanConfig's readBool keys: wasm/ocean_parity.sh checks both.
inline constexpr const char* kSimConfigBoolKeys[] = {"toroidal", "bodyModel", "triangularMotion", "foodDrift",
                                                     "predatorEconomy", "predatorInheritance", "fastTanh"};
inline constexpr const char* kOceanBoolKeys[] = {"deepCurrent", "lightEnabled", "depthCostScaled",
                                                 "sizeDrift", "sizeFight", "mouthGate", "walls"};
inline bool isSimConfigBoolKey(const std::string& k) {
    for (const char* i : kSimConfigBoolKeys) if (k == i) return true;
    return false;
}
inline bool isOceanBoolKey(const std::string& k) {
    for (const char* i : kOceanBoolKeys) if (k == i) return true;
    return false;
}

// A flat cfg JSON object (null / empty = nothing to change) into both configs:
// SimConfig keys through the checkpoint reader, Ocean keys through
// readOceanConfig. Returns false with `err` set on malformed JSON, an int key
// (SimConfig's or the Ocean's) whose number is not a whole number in int's
// range (checked before the reader casts it, every occurrence of the key), a
// SimConfig bool key that is not a JSON true / false, or an Ocean bool key
// that is not true / false / 0 / 1 (every occurrence of either).
inline bool readOceanJson(const char* json, SimConfig& sc, OceanConfig& oc, std::string& err) {
    if (!json || !json[0]) return true;
    const std::string wrapped = std::string("{\"config\":") + json + "}";
    jsonm::Value root;
    if (!jsonm::Parser::parse(wrapped, root, err)) { err = "config parse error: " + err; return false; }
    using T = jsonm::Value::Type;
    if (const jsonm::Value* o = root.find("config"); o && o->isObject())
        for (const auto& kv : o->obj) {
            const jsonm::Value& v = kv.second;
            if (v.type == T::Number && (isSimConfigIntKey(kv.first) || isOceanIntKey(kv.first)) && !isIntValue(v.num)) {
                char buf[160];
                std::snprintf(buf, sizeof buf, "%s must be a whole number that fits an int (got %.17g)",
                              kv.first.c_str(), v.num);
                err = buf;
                return false;
            }
            if (isSimConfigBoolKey(kv.first) && v.type != T::Bool) {
                err = kv.first + " must be true / false";
                return false;
            }
            if (isOceanBoolKey(kv.first) && v.type != T::Bool && !(v.type == T::Number && (v.num == 0.0 || v.num == 1.0))) {
                err = kv.first + " must be true / false (or 0 / 1)";
                return false;
            }
        }
    checkpoint::readConfig(root, sc);
    if (const jsonm::Value* o = root.find("config"))
        if (!readOceanConfig(*o, oc, &err)) return false;
    return true;
}

// The longest food lifetime, in seconds. A food age is a float that grows by
// dt = 0.016 a step, so it must stay where that add is accurate: below 2^12
// (4096) the float spacing is at most 2^-12 s, and each add rounds dt by at
// most +0.71% (the binade [2^11, 2^12) adds 66 spacings, 0.01611 s); an item
// born at age 0 reaches 3600 after 224377 steps instead of 225000 (0.28%
// early). Further up it degrades: -2.3% per step from 2^13, +95% from 2^18,
// and from 2^19 (524288) age + dt == age, so an item there never expires
// (the 1e6 this range used to allow).
inline constexpr float kOceanMaxFoodLife = 3600.0f;

// The appearance keys (cosmetic; appearance_model.hpp): appearance a bit set in
// [0, 3], each inheritance knob in [0, 0.25] (NaN fails).
inline std::string oceanAppearanceConfigError(const OceanConfig& c) {
    if (c.appearance < 0 || c.appearance > 3)
        return "appearance must be 0..3 (bits: 1 skin patterns, 2 body shapes)";
    const struct { const char* name; float v; } k[] = {
        {"patternMutation", c.patternMutation}, {"patternPhaseMutation", c.patternPhaseMutation},
        {"patternNovelProbability", c.patternNovelProbability}, {"morphologyMutation", c.morphologyMutation},
        {"morphologyNovelProbability", c.morphologyNovelProbability},
    };
    for (const auto& e : k)
        if (!(e.v >= 0.0f && e.v <= 0.25f)) {
            char buf[160];
            std::snprintf(buf, sizeof buf, "%s must be in [0, 0.25] (got %g)", e.name, (double)e.v);
            return buf;
        }
    return "";
}

// True when every appearance inheritance knob holds its default, bit for bit
// (the harness prints the appearance section only when appearance is on or
// one of these is not at its default).
inline bool oceanAppearanceKnobsAtDefaults(const OceanConfig& c) {
    const OceanConfig d;
    auto same = [](float a, float b) { return std::memcmp(&a, &b, sizeof a) == 0; };
    return same(c.patternMutation, d.patternMutation) && same(c.patternPhaseMutation, d.patternPhaseMutation) &&
           same(c.patternNovelProbability, d.patternNovelProbability) && same(c.morphologyMutation, d.morphologyMutation) &&
           same(c.morphologyNovelProbability, d.morphologyNovelProbability);
}

// "" when every knob is inside its range, else which one is not and why. The
// ranges keep every product the step forms finite: e.g. kBuoy·(bodyBuoy·D −
// depth) ≤ 1e3·D, vz·vDrag·dt ≤ (pitchMax + 16)·1e4·dt before the clamp, the
// wave flow ≤ waveSpeed·(1 + 1.5/(b·k)) with b ≥ 1; and foodLife keeps the
// food ages accurate (kOceanMaxFoodLife).
inline std::string oceanConfigError(const OceanConfig& c) {
    const struct { const char* name; float v, lo, hi; } r[] = {
        {"depth", c.depth, 10.0f, 100000.0f},
        {"kBuoy", c.kBuoy, -1000.0f, 1000.0f},
        {"buoyMutation", c.buoyMutation, 0.0f, 1.0f},
        {"pitchMax", c.pitchMax, 0.001f, 100.0f},
        {"vDrag", c.vDrag, 0.0f, 10000.0f},
        {"wallBand", c.wallBand, 0.0f, 100000.0f},
        {"cHold", c.cHold, 0.0f, 100.0f},
        {"cPress", c.cPress, 0.0f, 100.0f},
        {"foodDepthSpread", c.foodDepthSpread, 0.0f, 1000000.0f},
        {"waveSpeed", c.waveSpeed, 0.0f, 100.0f},
        {"waveBand", c.waveBand, 1.0f, 100000.0f},
        {"waveGravity", c.waveGravity, 0.01f, 10000.0f},
        {"L0", c.L0, 0.0f, 100.0f},
        {"kWater", c.kWater, 0.0f, 1.0f},
        {"kMouth", c.kMouth, 0.01f, 100.0f},
        {"foodLife", c.foodLife, 0.0f, kOceanMaxFoodLife},
        {"sideWallBand", c.sideWallBand, 0.0f, 100000.0f},
        {"sideWallTurnRate", c.sideWallTurnRate, 0.0f, 1000.0f},
    };
    for (const auto& e : r)
        if (!(e.v >= e.lo && e.v <= e.hi)) {   // NaN fails both
            char buf[160];
            std::snprintf(buf, sizeof buf, "%s must be in [%g, %g] (got %g)", e.name, (double)e.lo,
                          (double)e.hi, (double)e.v);
            return buf;
        }
    if (c.foodDepthMode != 0 && c.foodDepthMode != 1) return "foodDepthMode must be 0 or 1";
    // The eye's keys exist only in the eye build (-DEVO_OCEAN_EYE); elsewhere
    // they must stay 0.
    const char* const noEye = " needs the eye build (-DEVO_OCEAN_EYE); this build has no eye";
    if (c.eye != 0 && !(kOceanHasEye && c.eye == 1))
        return kOceanHasEye ? std::string("eye must be 0 or 1") : std::string("eye") + noEye;
    if (c.eyeOnly != 0 && !(kOceanHasEye && c.eyeOnly == 1))
        return kOceanHasEye ? std::string("eyeOnly must be 0 or 1") : std::string("eyeOnly") + noEye;
    if (!eyeCodeValid(c.eyeCode))
        return kOceanHasEye ? std::string("eyeCode must be 0..31 (bits: 1 faded contrast, 2 opponent pairs, 4 summed sectors,"
                                          " 8 the eye ignores fish, 16 the eye ignores food)")
                            : std::string("eyeCode") + noEye;
    if (c.steerFrame != 0 && c.steerFrame != 1) return "steerFrame must be 0 or 1";
    if (c.labelFrame != 0 && c.labelFrame != 1) return "labelFrame must be 0 or 1";
    if (const std::string a = oceanAppearanceConfigError(c); !a.empty()) return a;
    return "";
}

// True when every knob is usable (oceanConfigError is empty).
inline bool oceanConfigValid(const OceanConfig& c) { return oceanConfigError(c).empty(); }

// The cross-config rule of the two topologies: glass walls (OceanConfig::walls)
// and a toroidal world (SimConfig::toroidal: wrapped senses, the seam-aware
// queries and midpoints) exclude each other. "" when compatible. Checked
// wherever an Ocean config is accepted, before the world or the rng changes:
// oc_init / oc_set_param (wasm/ocean_wasm.cpp configOk), the harness's world
// builder and live --set (tools/ocean_fingerprint.hpp buildConfigs,
// tools/ocean_parity_driver.cpp applySet), the probe. (OceanWorld::init
// itself also forces toroidal off when walls are on, for direct callers.)
inline std::string oceanTopologyError(const SimConfig& sc, const OceanConfig& oc) {
    if (oc.walls && sc.toroidal) return "Glass walls require toroidal=false (walls and a wrapping world exclude each other)";
    return "";
}

// The keys a LIVE change may not touch, because the world is built with them:
// the glass walls (walls, sideWallBand, sideWallTurnRate: bounded or not) are
// refused whatever the value, even the one they have; appearance (its side
// array is built with the world) is refused unless it is the value it has (a
// no-op). "" when `key` may go on to the live checks. The one policy of every
// live path: oc_set_param (wasm/ocean_wasm.cpp, first, before the key is even
// looked up) and the harness's --set (tools/ocean_parity_driver.cpp applySet,
// before the copies are read), so neither can change the world or the rng.
inline std::string oceanRestartOnlyError(const std::string& key, double value, const OceanConfig& now) {
    static const char* const kInitOnly[] = {"walls", "sideWallBand", "sideWallTurnRate"};
    for (const char* k : kInitOnly)
        if (key == k) return key + " is set by oc_init (restart to change it)";
    if (key == "appearance" && !(value == (double)now.appearance))
        return "appearance is set by oc_init (restart to change it)";
    return "";
}

// The Ocean's own ranges for SimConfig keys whose extreme FINITE values break
// the Ocean step (SimConfig itself is Classic's and stays as it is). "" when
// every one is inside, else which one is not and why. Checked wherever an
// Ocean config is accepted: oc_init / oc_set_param (wasm/ocean_wasm.cpp
// configOk), the harness's world builder (tools/ocean_fingerprint.hpp
// buildConfigs) and its live --set, the probe.
//   * The current: currentStrength in [0, 1000] u/s (cases use <= 120; 0 =
//     off), currentEddies in [0, 100], currentCore in [0, 1e5] (the field uses
//     max(core, 1)), currentDrift in [-100, 100], currentGyreEps in [-1, 1],
//     currentMode 0 (eddies) or 1 (gyre). The flow is then at most
//     currentEddies·currentStrength (eddies; each vortex peaks at strength) or,
//     per component, currentStrength·max(1, 2(H/W)(1 + 6|eps|)) (gyre, in a
//     W x H world), and the field's clock
//     (0.0003·drift·frame) stays finite. currentStrength 1e20 used to be
//     accepted: food moved ~1e17 per step and OceanWorld::wrapCoord's loops
//     never ended (wrapCoord is constant-time now too).
//   * foodPatchRadius in [0, 1e5]: a toroidal patch's food is placed at
//     wrapCoord(centre ± R); 1e30 sent that to the same endless loop.
// And the keys whose value reaches an (int) conversion while stepping, where
// an out-of-range value is undefined behaviour (and differs native / wasm):
//   * foodSpawnBase, foodSpawnAmp in [-1e4, 1e4] (defaults 3, 2): each step
//     spawns (int)(base + amp·sin(·)) times; 1e20 was accepted (finite).
//   * targetFood in [0, 1e6]: the spawn cap is targetFood·2 (int arithmetic),
//     and init lays out targetFood items.
//   * maxSpeed in [0.01, 2000] and predatorSpeed in [0, 2000] (defaults 150,
//     110): a fish moves at most 2·maxSpeed·dt per step (speedFactor <= 2), a
//     predator 2·predatorSpeed·dt — at dt 0.016 under 64, less than the
//     smallest world (100), so the single add / subtract wraps keep positions
//     in the world, and SpatialGrid's (int)(position / cell) stays in range.
//     The floor 0.01 (kOceanMinMaxSpeed) keeps OWN_SPEED = speed / maxSpeed
//     finite: a founder starts at speed 80 before its first move clamps it,
//     and 80 / 1e-38 was +inf on the first captured step (the live-code audit
//     of PRs #22-#25, finding 4); now OWN_SPEED <= 2700 / 0.01.
//   * maxTurnRate in [-1e4, 1e4] (default 4; kOceanMaxTurnRate): triangular
//     motion forms maxTurnRate · turnFactor (<= 4/3 at bodyElong 0.5), and
//     3e38 · 4/3 overflowed to inf, then 0 · inf = NaN even with no steering
//     (the same audit). Inside the range one step turns by at most
//     1e4 · 4/3 · dt = 213 rad, a finite angle the portable sin / cos reduce.
//   * every radius (perceptionRadius, interactRadius, pickupRadius,
//     predatorPerception, predatorCaptureRadius) <= 1e6: SpatialGrid casts
//     (centre ± radius) / cell to int, cell = perceptionRadius >= 1 (a
//     toroidal world already holds them under min(W, H) / 2; radiusError).
// And the energies, where finite was not enough: every one in [-1e6, 1e6]
// (kOceanMaxEnergy) — foodEnergy, metabolicRate, geneCost, moveCost,
// reproEnergy, newbornEnergy, predatorMetabolism, predatorMoveCost,
// predatorReproEnergy, predatorNewbornEnergy, predatorMeal. Accepted finite
// values made infinities: one fish eating four items of foodEnergy 1e38 held
// +inf; moveCost 1e38 at speed 30, or geneCost 1e38 over a genome, made one
// step's cost inf (reserves -inf); predatorMeal 3e38 overflowed a predator's
// energy within a few meals. Inside the range one step's costs are under
// 3e11 (dt · 1e6 · (bodySize 2 · depth costs 201 + 80 genes + speed² 1.6e7)),
// and one item, birth, bud or meal moves at most 1e6 (a meal of the prey's
// reserves moves what the prey held), with at most 2e6 items a step: FLT_MAX
// (3.4e38) is more than 1e25 steps away. Negative values stay valid
// (predatorMoveCost / predatorMeal < 0 mean "moveCost" / "the prey's reserves").
// And: every other float the step reads finite (maxTurnRate, the cooldowns,
// ages, the predator economy's ...), minPopulation, predatorCount and
// foodPatches <= kOceanMaxCount.
inline constexpr float kOceanMaxEnergy = 1000000.0f;  // |every energy knob|
inline constexpr float kOceanMinMaxSpeed = 0.01f;     // maxSpeed's floor (OWN_SPEED = speed / maxSpeed)
inline constexpr float kOceanMaxTurnRate = 10000.0f;  // |maxTurnRate| (× turnFactor <= 4/3)
inline constexpr int kOceanMaxCount = 100000;        // founders, the reseed floor, predators, food patches
inline constexpr int kOceanMaxWorldSide = 100000;    // world width / height (the depth's own ceiling too)
inline constexpr double kOceanMaxGridCells = 16777216.0;   // per neighbour grid (2^24)

inline std::string oceanSimConfigError(const SimConfig& c) {
    const struct { const char* name; float v, lo, hi; } r[] = {
        {"currentStrength", c.currentStrength, 0.0f, 1000.0f},
        {"currentCore", c.currentCore, 0.0f, 100000.0f},
        {"currentDrift", c.currentDrift, -100.0f, 100.0f},
        {"currentGyreEps", c.currentGyreEps, -1.0f, 1.0f},
        {"foodPatchRadius", c.foodPatchRadius, 0.0f, 100000.0f},
        {"foodSpawnBase", c.foodSpawnBase, -10000.0f, 10000.0f},
        {"foodSpawnAmp", c.foodSpawnAmp, -10000.0f, 10000.0f},
        {"maxSpeed", c.maxSpeed, kOceanMinMaxSpeed, 2000.0f},
        {"maxTurnRate", c.maxTurnRate, -kOceanMaxTurnRate, kOceanMaxTurnRate},
        {"predatorSpeed", c.predatorSpeed, 0.0f, 2000.0f},
        {"perceptionRadius", c.perceptionRadius, 0.0f, 1000000.0f},
        {"interactRadius", c.interactRadius, 0.0f, 1000000.0f},
        {"pickupRadius", c.pickupRadius, 0.0f, 1000000.0f},
        {"predatorPerception", c.predatorPerception, 0.0f, 1000000.0f},
        {"predatorCaptureRadius", c.predatorCaptureRadius, 0.0f, 1000000.0f},
        // the energies (kOceanMaxEnergy)
        {"foodEnergy", c.foodEnergy, -kOceanMaxEnergy, kOceanMaxEnergy},
        {"metabolicRate", c.metabolicRate, -kOceanMaxEnergy, kOceanMaxEnergy},
        {"geneCost", c.geneCost, -kOceanMaxEnergy, kOceanMaxEnergy},
        {"moveCost", c.moveCost, -kOceanMaxEnergy, kOceanMaxEnergy},
        {"reproEnergy", c.reproEnergy, -kOceanMaxEnergy, kOceanMaxEnergy},
        {"newbornEnergy", c.newbornEnergy, -kOceanMaxEnergy, kOceanMaxEnergy},
        {"predatorMetabolism", c.predatorMetabolism, -kOceanMaxEnergy, kOceanMaxEnergy},
        {"predatorMoveCost", c.predatorMoveCost, -kOceanMaxEnergy, kOceanMaxEnergy},
        {"predatorReproEnergy", c.predatorReproEnergy, -kOceanMaxEnergy, kOceanMaxEnergy},
        {"predatorNewbornEnergy", c.predatorNewbornEnergy, -kOceanMaxEnergy, kOceanMaxEnergy},
        {"predatorMeal", c.predatorMeal, -kOceanMaxEnergy, kOceanMaxEnergy},
    };
    for (const auto& e : r)
        if (!(e.v >= e.lo && e.v <= e.hi)) {   // NaN fails both
            char buf[160];
            std::snprintf(buf, sizeof buf, "%s must be in [%g, %g] (got %g)", e.name, (double)e.lo,
                          (double)e.hi, (double)e.v);
            return buf;
        }
    if (c.currentMode != 0 && c.currentMode != 1) return "currentMode must be 0 (eddies) or 1 (gyre)";
    if (c.currentEddies < 0 || c.currentEddies > 100) return "currentEddies must be in [0, 100]";
    if (c.targetFood < 0 || c.targetFood > 1000000) return "targetFood must be in [0, 1000000]";
    // Every other float the Ocean step reads must at least be finite: a JSON
    // number past FLT_MAX (1e39) is an infinite float — maxTurnRate inf made
    // the heading NaN in one step; an infinite cooldown or age poisons the
    // timers the same way. (The energies have their range above.)
    const struct { const char* name; float v; } finite[] = {
        {"reproMaxDistance", c.reproMaxDistance}, {"reproSoftWidth", c.reproSoftWidth},
        {"reproGracePeriod", c.reproGracePeriod}, {"bodyMutation", c.bodyMutation},
        {"maxAge", c.maxAge}, {"reproCooldown", c.reproCooldown},
        {"interactCooldown", c.interactCooldown}, {"minSpeed", c.minSpeed},
        {"mutationMultiplier", c.mutationMultiplier}, {"predatorCooldown", c.predatorCooldown},
        {"predatorMaxAge", c.predatorMaxAge}, {"predatorTraitMutation", c.predatorTraitMutation},
    };
    for (const auto& e : finite)
        if (!std::isfinite(e.v)) return std::string(e.name) + " must be finite";
    // Counts that size allocations (founders added each step up to the floor,
    // predators, food-patch centres): generous ceilings against resource
    // exhaustion (an int key may hold up to 2^31 - 1).
    if (c.minPopulation > kOceanMaxCount) return "minPopulation must be <= " + std::to_string(kOceanMaxCount);
    if (c.predatorCount > kOceanMaxCount) return "predatorCount must be <= " + std::to_string(kOceanMaxCount);
    if (c.foodPatches > kOceanMaxCount) return "foodPatches must be <= " + std::to_string(kOceanMaxCount);
    return "";
}

// oc_init's world: width and height in [100, kOceanMaxWorldSide], founders in
// [0, kOceanMaxCount], and neighbour grids (SpatialGrid, cell = perception
// radius, two of them) of at most kOceanMaxGridCells cells each — a 1e5 x 1e5
// world with perceptionRadius 1 would ask for 1e10. "" when it fits, else why
// not. Checked by oc_init (wasm/ocean_wasm.cpp) and the harness's world
// builder (tools/ocean_fingerprint.hpp initWorld).
inline std::string oceanWorldSizeError(const SimConfig& c, int width, int height, int population) {
    if (width < 100 || height < 100 || width > kOceanMaxWorldSide || height > kOceanMaxWorldSide)
        return "world width and height must be in [100, " + std::to_string(kOceanMaxWorldSide) + "] (got " +
               std::to_string(width) + " x " + std::to_string(height) + ")";
    if (population < 0 || population > kOceanMaxCount)
        return "population must be in [0, " + std::to_string(kOceanMaxCount) + "] (got " + std::to_string(population) + ")";
    const double cell = std::max(1.0, (double)c.perceptionRadius);   // the shim's clamp: >= 1
    const double cells = ((double)width / cell + 1.0) * ((double)height / cell + 1.0);
    if (!(cells <= kOceanMaxGridCells)) {
        char buf[200];
        std::snprintf(buf, sizeof buf, "perceptionRadius %g makes a %d x %d world's neighbour grid %.3g cells (at most %.3g)",
                      (double)c.perceptionRadius, width, height, cells, kOceanMaxGridCells);
        return buf;
    }
    return "";
}

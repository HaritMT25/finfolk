// ocean_parity_driver.cpp — the Ocean world's determinism oracle
// (PLAN_ecosystem.md §12, E0 exit test "native == wasm fingerprints"; and the
// historical oracle: wasm/ocean_parity.sh also compares the native output with
// the committed baseline in tests/ocean_baseline/).
//
// Runs OceanWorld headless. After EVERY step it takes the full fingerprint of
// the whole state (tools/ocean_fingerprint.hpp: every fish's AgentCore fields,
// genome, net, pos/vel/depth/vz/bodyBuoy/body trail, food incl. depth and size,
// predators incl. depth/pitch, the pheromone grid, the current field's whole
// state, the persistent geometry, all counters and nextId_, both configs, and
// the rng engine; floats by bit pattern), folds it into a rolling `chain`
// hash and scans the state for non-finite values; every K steps it prints the
// sections and the chain. A divergence that heals before the next print still
// changes the chain, and a transient NaN still fails the run. Build the SAME
// file natively and with Emscripten, run both with the same arguments and
// byte-compare stdout: equal output == bit-identical runs.
//
//   g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_parity_driver.cpp -o opd
//   em++ -O3 -std=c++20 -ffp-contract=off -msimd128 -DEVO_WORLD_OCEAN -I src
//        tools/ocean_parity_driver.cpp -o opd.js -sALLOW_MEMORY_GROWTH=1 -sNODERAWFS=1 -sEXIT_RUNTIME=1
//   ./opd 42 3000 > a.txt && node opd.js 42 3000 > b.txt && cmp a.txt b.txt
//
// wasm/ocean_parity.sh runs the case matrix. Built with -DEVO_OCEAN_EYE too
// (the compound-eye build: its header line says build=eye).
//
// The world is built the way the page builds it (oc_init in wasm/ocean_wasm.cpp:
// applyOceanDefaults, the cfg JSON, the shim's clamps; ofp::initWorld), so a
// cfg JSON means here what it means to oc_init.
//
// Usage: ocean_parity_driver SEED STEPS [options]
//   --every K          print the fingerprint every K steps (default 100; step 0
//                      and the last step are always printed). The chain covers
//                      every step whatever K is.
//   --w W --h H        world size (default 1920 x 1080)
//   --depth D          sea depth (default 240)
//   --pop N            founders (default 300)
//   --cfg JSON         flat SimConfig + OceanConfig keys, as oc_init takes them
//   --set NAME=V@S     before step S+1 (after S steps), change one live knob the
//                      way oc_set_param does (repeatable). A refused one (the
//                      restart-only keys, ocean_config.hpp oceanRestartOnlyError,
//                      or a value the checks refuse) prints "refused S ..." with
//                      the state's fingerprint and exits 4, the world untouched
//   --expect NAMEopV   after the run, a coverage counter (the `cover` line) must
//                      satisfy op V (op: > >= = <= <); repeatable; exit 5 if not.
//                      This is how a case proves it reached the branch it is for.
//   --dump PATH        write the full state as text (tools/ocean_fingerprint.hpp
//                      dumpState) at --dump-step (default: the last step)
//   --dump-step S      which step to dump (0 = right after init)
//   --capture          captureActivations on: every fish's 46 sensors (64 in the
//                      eye build) and 13 actions of its last step are hashed too
//                      (not a cfg JSON key)
//   --logs C,R         the death-cluster map and the birth log on, kept to C and
//                      R records (clusterMap / clusterMax, reproLog / reproLogMax:
//                      not cfg JSON keys either — the checkpoint reader, and so
//                      oc_init, does not carry them); small values force their
//                      decimation
//   --trace            print EVERY step (divergence bisection)
//   --sparse           fingerprint only at the printed steps, no chain, no
//                      per-step scan (the pre-v2 behaviour; for timing the
//                      per-step overhead only — its output has no chain=)
//   --unchecked        TEST-ONLY: the cfg JSON and every --set skip the Ocean's
//                      ranges (oceanConfigError, oceanSimConfigError; the JSON
//                      reader's own checks and the world-size check still run),
//                      so a config the page refuses can be run on purpose
//                      (wasm/ocean_parity.sh's nf_* cases: the non-finite
//                      diagnostic must still catch it). Its header says
//                      unchecked=1. Never for a parity case.
//
// The non-finite count (nonfinite_max / nonfinite_from on the final line)
// is, per step, the non-finite floats of the scanned state plus those held by
// the objects removed since the last scan (OceanWorld::totalNonFiniteRemoved:
// a fish whose reserves went -inf starves and is erased within the step, so
// no scan sees it); `cover` reports the latter as nonFiniteRemoved when > 0.
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <vector>
#include "ocean_fingerprint.hpp"

namespace {

struct LiveSet { std::string name; double value; long step; };

bool parseSet(const char* s, LiveSet& out) {
    const char* eq = std::strchr(s, '=');
    const char* at = std::strrchr(s, '@');
    if (!eq || !at || at < eq) return false;
    out.name.assign(s, eq - s);
    out.value = std::strtod(eq + 1, nullptr);
    out.step = std::strtol(at + 1, nullptr, 10);
    return !out.name.empty() && out.step >= 0;
}

// oc_set_param's path: the restart-only keys refused first (ocean_config.hpp
// oceanRestartOnlyError, the shim's own policy; --unchecked too), then the
// value into a one-key JSON (an int key, which must be a whole number, as its
// exact integer; any other "%.9g"), read onto copies of both configs, clamped,
// checked (not with --unchecked), assigned. False leaves w untouched.
bool applySet(OceanWorld& w, const LiveSet& s, bool unchecked) {
    if (!oceanRestartOnlyError(s.name, s.value, w.ocfg).empty()) return false;
    char num[40];
    if (isSimConfigIntKey(s.name) || isOceanIntKey(s.name)) {
        if (!isIntValue(s.value)) return false;
        std::snprintf(num, sizeof num, "%lld", (long long)s.value);
    } else {
        std::snprintf(num, sizeof num, "%.9g", s.value);
    }
    const std::string json = "{\"" + s.name + "\":" + num + "}";
    SimConfig sc = w.cfg;
    OceanConfig oc = w.ocfg;
    std::string err;
    if (!readOceanJson(json.c_str(), sc, oc, err)) return false;
    ofp::clampConfigLikeShim(sc);
    if (!unchecked && (!oceanConfigValid(oc) || !oceanSimConfigError(sc).empty() || !oceanTopologyError(sc, oc).empty()))
        return false;
    w.cfg = sc;
    w.ocfg = oc;
    return true;
}

// --unchecked's world: ofp::initWorld without the Ocean's ranges (the JSON
// reader's checks, the shim's clamps and the world-size check still apply).
bool initWorldUnchecked(OceanWorld& w, unsigned seed, int W, int H, float depth, int pop, const char* cfgJson,
                        std::string& err) {
    SimConfig sc;
    applyOceanDefaults(sc);
    OceanConfig oc;
    if (!readOceanJson(cfgJson, sc, oc, err)) return false;
    ofp::clampConfigLikeShim(sc);
    oc.depth = depth;
    err = oceanWorldSizeError(sc, W, H, pop);
    if (!err.empty()) return false;
    rng.seed(seed);
    w.cfg = sc;
    w.ocfg = oc;
    w.init(W, H, depth, pop);
    return true;
}

// What the run reached, observed from outside the engine every step (no hooks:
// the engine is unchanged). `before` sees the state a step starts from — what
// the step's branches read — and `after` the state it leaves.
struct Coverage {
    long long bandTop = 0;       // fish-steps that started inside the surface band (the wall push ran)
    long long bandFloor = 0;     // ... inside the floor band
    long long capSteps = 0;      // steps that started at maxPopulation (> 0): every pairing in them is capped
    long long fastTanhSteps = 0; // fish-steps whose net ran with cfg.fastTanh
    long long popMax = 0, predMax = 0, predGenMax = 0;
    long long predTraitVaried = 0;   // predator-steps with an inherited (non-1) trait
    // The ocean-vision features (OceanConfig eye / eyeOnly / eyeCode / steerFrame /
    // foodLife). Printed in the `cover` line only when non-zero (kQuietWhenZero):
    // they are 0 in every case without those features, whose baselines were
    // recorded before the counters existed (foodCapFreed: 0 in every case
    // before life_cap_*).
    long long eyeSteps = 0;          // fish-steps that ran with the compound eye on
    long long eyeOnlySteps = 0;      // fish-steps in eye-only mode (labeled senses off)
    long long eyeCodeMask = 0;       // OR of the eyeCode bits that ran with the eye on
    long long eyeE1Steps = 0;        // fish-steps with the eye on while the E1 3-D flow ran
    long long eyeLit = 0;            // fish (captured) whose last step had an eye input != 0
    long long labeledLit = 0;        // fish (captured) in eye-only mode with a labeled input != 0 (must stay 0)
    long long steerOwnSteps = 0;     // fish-steps that pushed STEER_X / STEER_Y in their own frame
    long long labelOwnSteps = 0;     // fish-steps sensed with own-frame labels (labelFrame 1, labels on)
    long long agesKept = 0;          // steps that began with foodLife off and a food age kept != 0
    // Steps whose spawn refilled places that food expiring in the same step
    // freed: the step began with S items, k expired, and S + spawned went past
    // the cap (targetFood·2) — the spawn the cap allowed only because it counts
    // live items (spawned = the end stock − S + k + the items fish ate).
    long long foodCapFreed = 0;
    // Glass walls (OceanConfig::walls; 0 in every case without them):
    long long wallSteps = 0;       // fish-steps that ran with walls on
    long long wallTouch = 0;       // fish-steps that ended ON a side face (contact resolved)
    long long predWallTouch = 0;   // predator-steps that ended on a side face
    long long foodNearGlass = 0;   // food-item-steps ending within 1 unit of a side face
    long long outside = 0;         // fish / body point / food / predator outside the closed tank after a step (must be 0)
    long long food0_ = 0, expired0_ = 0, eaten0_ = 0;   // the step's start (before)
    void before(const OceanWorld& w) {
        food0_ = (long long)w.food.size();
        expired0_ = w.totalFoodExpired;
        eaten0_ = w.totalFoodEaten;
        const float wb = std::min(w.ocfg.wallBand, 0.5f * w.D);   // the step's own band (stepFish)
        for (const Fish& c : w.creatures) {
            if (!c.alive || !(wb > 0.0f)) continue;
            if (c.depth < wb) ++bandTop;
            else if (c.depth > w.D - wb) ++bandFloor;
        }
        if (w.cfg.maxPopulation > 0 && (long long)w.creatures.size() >= w.cfg.maxPopulation) ++capSteps;
        if (w.cfg.fastTanh) fastTanhSteps += (long long)w.creatures.size();
        const long long n = (long long)w.creatures.size();
        if (w.ocfg.eye) {
            eyeSteps += n;
            eyeCodeMask |= w.ocfg.eyeCode;
            if (w.flowE1()) eyeE1Steps += n;
        }
        if (w.ocfg.eyeOnly) eyeOnlySteps += n;
        if (w.ocfg.walls) wallSteps += n;
        if (w.ocfg.steerFrame == 1 && !w.cfg.triangularMotion) steerOwnSteps += n;
        if (w.ocfg.labelFrame == 1 && !w.ocfg.eyeOnly) labelOwnSteps += n;
        if (!(w.ocfg.foodLife > 0.0f))
            for (const OceanFood& f : w.food)
                if (f.age != 0.0f) { ++agesKept; break; }
    }
    void after(const OceanWorld& w) {
        if (const long long k = w.totalFoodExpired - expired0_; k > 0) {
            const long long spawned = (long long)w.food.size() - food0_ + k + (w.totalFoodEaten - eaten0_);
            foodCapFreed += (food0_ + spawned > 2LL * w.cfg.targetFood);
        }
        if (w.ocfg.walls) {   // containment, observed from outside the engine
            const float W = (float)w.width, H = (float)w.height, D = w.D;
            auto out = [&](Vec2 p) { return !(p.x >= 0.0f && p.x <= W && p.y >= 0.0f && p.y <= H); };
            auto onFace = [&](Vec2 p) { return p.x == 0.0f || p.x == W || p.y == 0.0f || p.y == H; };
            for (const Fish& c : w.creatures) {
                if (!c.alive) continue;
                outside += out(c.pos) || !(c.depth >= 0.0f && c.depth <= D);
                for (const Vec2& b : c.body) outside += out(b);
                wallTouch += onFace(c.pos);
            }
            for (const OceanFood& f : w.food) {
                if (!f.alive) continue;
                outside += out(f.pos) || !(f.depth >= 0.0f && f.depth <= D);
                foodNearGlass += (f.pos.x < 1.0f || f.pos.x > W - 1.0f || f.pos.y < 1.0f || f.pos.y > H - 1.0f);
            }
            for (const OceanPredator& p : w.predators) {
                if (!p.alive) continue;
                outside += out(p.pos) || !(p.depth >= 0.0f && p.depth <= D);
                predWallTouch += onFace(p.pos);
            }
        }
        popMax = std::max(popMax, (long long)w.creatures.size());
        predMax = std::max(predMax, (long long)w.predators.size());
        for (const OceanPredator& p : w.predators) {
            predGenMax = std::max(predGenMax, (long long)p.generation);
            predTraitVaried += (p.speedFactor != 1.0f || p.buddingFactor != 1.0f);
        }
#ifdef EVO_OCEAN_EYE
        if (w.cfg.captureActivations)
            for (const Fish& c : w.creatures) {
                if (!c.alive || c.age <= 0.0f) continue;   // newborns / founders: not sensed yet
                bool lit = false, lab = false;
                for (int k = 0; k < NUM_SENSES; ++k) {
                    if (c.lastSensors[k] == 0.0f) continue;
                    if (ocean::isEyeSense(k)) lit = true;
                    else if (ocean::isLabeledSense(k)) lab = true;
                }
                eyeLit += lit;
                labeledLit += (lab && w.ocfg.eyeOnly);
            }
#endif
    }
    // Every counter, by name, with the engine's own totals.
    std::map<std::string, long long> values(const OceanWorld& w) const {
        const bool gateArmed = w.cfg.reproMaxDistance >= 0.0f;
        return {
            {"births", w.totalBirths}, {"deaths", w.totalDeaths}, {"reseeds", w.totalReseeds},
            {"grace", w.totalGraceBirths}, {"soft", w.totalSoftBirths},
            // births that passed the armed gate's distance test itself (not grace)
            {"gateBirths", gateArmed ? w.totalBirths - w.totalGraceBirths : 0},
            {"dPred", w.totalDeathsPredation}, {"dStarve", w.totalDeathsStarvation}, {"dAge", w.totalDeathsAge},
            {"pBirths", w.totalPredatorBirths}, {"pStarve", w.totalPredatorDeathsStarvation},
            {"pAge", w.totalPredatorDeathsAge}, {"pReseeds", w.totalPredatorReseeds},
            {"deathLog", (long long)w.deathLog.size()}, {"clusterStride", w.clusterStride_},
            {"birthLog", (long long)w.birthLog.size()}, {"reproStride", w.reproStride_},
            {"bandTop", bandTop}, {"bandFloor", bandFloor}, {"capSteps", capSteps},
            {"fastTanhSteps", fastTanhSteps}, {"popMax", popMax}, {"predMax", predMax},
            {"predGenMax", predGenMax}, {"predTraitVaried", predTraitVaried},
            {"eyeSteps", eyeSteps}, {"eyeOnlySteps", eyeOnlySteps}, {"eyeCodeMask", eyeCodeMask},
            {"eyeE1Steps", eyeE1Steps}, {"eyeLit", eyeLit}, {"labeledLit", labeledLit},
            {"steerOwnSteps", steerOwnSteps}, {"labelOwnSteps", labelOwnSteps}, {"foodExpired", w.totalFoodExpired},
            {"agesKept", agesKept}, {"foodCapFreed", foodCapFreed},
            {"nonFiniteRemoved", w.totalNonFiniteRemoved},
            {"wallSteps", wallSteps}, {"wallTouch", wallTouch}, {"predWallTouch", predWallTouch},
            {"foodNearGlass", foodNearGlass}, {"outside", outside},
            // the appearance genome's construction (the engine's own statistics;
            // never read by the step): records built, branches taken
            {"appFounders", (long long)w.appearanceStats().founders},
            {"appOffspring", (long long)w.appearanceStats().offspring},
            {"appMean", (long long)w.appearanceStats().pattern[0]}, {"appCopyA", (long long)w.appearanceStats().pattern[1]},
            {"appCopyB", (long long)w.appearanceStats().pattern[2]}, {"appNovel", (long long)w.appearanceStats().pattern[3]},
            {"appShapeMean", (long long)w.appearanceStats().morph[0]}, {"appShapeCopyA", (long long)w.appearanceStats().morph[1]},
            {"appShapeCopyB", (long long)w.appearanceStats().morph[2]}, {"appShapeNovel", (long long)w.appearanceStats().morph[3]},
            {"appBroken", (long long)w.appearanceBroken()},
        };
    }
    // The counters the `cover` line leaves out while they are 0 (see above;
    // nonFiniteRemoved is 0 in every passing case).
    static bool quietWhenZero(const std::string& k) {
        static const char* const kQuietWhenZero[] = {"eyeSteps", "eyeOnlySteps", "eyeCodeMask", "eyeE1Steps",
                                                     "eyeLit", "labeledLit", "steerOwnSteps", "labelOwnSteps", "foodExpired",
                                                     "agesKept", "foodCapFreed", "nonFiniteRemoved", "appFounders",
                                                     "appOffspring", "appMean", "appCopyA", "appCopyB", "appNovel",
                                                     "appShapeMean", "appShapeCopyA", "appShapeCopyB", "appShapeNovel",
                                                     "appBroken", "wallSteps", "wallTouch", "predWallTouch",
                                                     "foodNearGlass", "outside"};
        for (const char* q : kQuietWhenZero) if (k == q) return true;
        return false;
    }
};

struct Expect { std::string text, name, op; long long value; };

bool parseExpect(const char* s, Expect& e) {
    e.text = s;
    const char* p = s;
    while (*p && *p != '<' && *p != '>' && *p != '=') ++p;
    if (p == s || !*p) return false;
    e.name.assign(s, p - s);
    const char* v = p + 1;
    if (*v == '=') ++v;
    e.op.assign(p, v - p);
    if (e.op != ">" && e.op != ">=" && e.op != "=" && e.op != "<=" && e.op != "<") return false;
    char* end = nullptr;
    e.value = std::strtoll(v, &end, 10);
    return end && end != v && !*end;
}

bool holds(const Expect& e, long long got) {
    if (e.op == ">") return got > e.value;
    if (e.op == ">=") return got >= e.value;
    if (e.op == "=") return got == e.value;
    if (e.op == "<=") return got <= e.value;
    return got < e.value;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr, "usage: %s SEED STEPS [--every K] [--w W --h H --depth D --pop N]"
                             " [--cfg JSON] [--set NAME=V@STEP] [--expect NAMEopV] [--dump PATH --dump-step S]"
                             " [--capture] [--logs C,R] [--trace] [--sparse] [--unchecked]\n",
                     argv[0]);
        return 2;
    }
    {   // Locale guard: --set and the header print with C-locale %.9g.
        char buf[16];
        std::snprintf(buf, sizeof buf, "%.9g", 0.5);
        if (std::strcmp(buf, "0.5") != 0) { std::fprintf(stderr, "FATAL: non-C locale (%s)\n", buf); return 3; }
    }

    const unsigned seed = (unsigned)std::strtoul(argv[1], nullptr, 10);
    const long steps = std::strtol(argv[2], nullptr, 10);
    long every = 100, dumpStep = -1;
    int W = 1920, H = 1080, pop = 300;
    double depth = 240.0;
    const char* cfgJson = nullptr;
    const char* dumpPath = nullptr;
    bool capture = false, sparse = false, unchecked = false;
    int clusterMax = -1, reproLogMax = -1;
    std::vector<LiveSet> sets;
    std::vector<Expect> expects;
    for (int i = 3; i < argc; ++i) {
        auto is = [&](const char* k) { return std::strcmp(argv[i], k) == 0 && i + 1 < argc; };
        if (is("--every")) every = std::strtol(argv[++i], nullptr, 10);
        else if (is("--w")) W = std::atoi(argv[++i]);
        else if (is("--h")) H = std::atoi(argv[++i]);
        else if (is("--depth")) depth = std::atof(argv[++i]);
        else if (is("--pop")) pop = std::atoi(argv[++i]);
        else if (is("--cfg")) cfgJson = argv[++i];
        else if (is("--dump")) dumpPath = argv[++i];
        else if (is("--dump-step")) dumpStep = std::strtol(argv[++i], nullptr, 10);
        else if (is("--set")) {
            LiveSet s;
            if (!parseSet(argv[++i], s)) { std::fprintf(stderr, "bad --set %s (NAME=VALUE@STEP)\n", argv[i]); return 2; }
            sets.push_back(s);
        }
        else if (is("--expect")) {
            Expect e;
            if (!parseExpect(argv[++i], e)) { std::fprintf(stderr, "bad --expect %s (NAMEopVALUE)\n", argv[i]); return 2; }
            expects.push_back(e);
        }
        else if (is("--logs")) {
            if (std::sscanf(argv[++i], "%d,%d", &clusterMax, &reproLogMax) != 2 || clusterMax < 1 || reproLogMax < 1) {
                std::fprintf(stderr, "bad --logs %s (CLUSTERMAX,REPROLOGMAX, both >= 1)\n", argv[i]);
                return 2;
            }
        }
        else if (!std::strcmp(argv[i], "--trace")) every = 1;
        else if (!std::strcmp(argv[i], "--capture")) capture = true;
        else if (!std::strcmp(argv[i], "--sparse")) sparse = true;
        else if (!std::strcmp(argv[i], "--unchecked")) unchecked = true;
        else { std::fprintf(stderr, "unknown or incomplete argument: %s\n", argv[i]); return 2; }
    }
    if (every <= 0) every = steps > 0 ? steps : 1;
    if (dumpStep < 0) dumpStep = steps;

    OceanWorld w;
    std::string err;
    if (!(unchecked ? initWorldUnchecked(w, seed, W, H, (float)depth, pop, cfgJson, err)
                    : ofp::initWorld(w, seed, W, H, (float)depth, pop, cfgJson, err))) {
        std::fprintf(stderr, "config refused: %s\n", err.c_str());
        return 4;
    }
    w.cfg.captureActivations = capture;
    if (clusterMax > 0) {
        w.cfg.clusterMap = true;
        w.cfg.clusterMax = clusterMax;
        w.cfg.reproLog = true;
        w.cfg.reproLogMax = reproLogMax;
    }
    std::printf("ocean_parity format=%d%s%s seed=%u steps=%ld every=%ld world=%dx%dx%.9g pop=%d capture=%d logs=%d,%d cfg=%s\n",
                ofp::kFormatVersion, kOceanHasEye ? " build=eye" : "", unchecked ? " unchecked=1" : "", seed, steps,
                every, W, H, depth, pop, (int)capture, clusterMax, reproLogMax, cfgJson ? cfgJson : "{}");
    for (const LiveSet& s : sets) std::printf("set %s=%.9g @%ld\n", s.name.c_str(), s.value, s.step);
    for (const Expect& e : expects) {
        // An unknown counter name is a harness error, not a pass.
        if (!Coverage{}.values(w).count(e.name)) { std::fprintf(stderr, "--expect: no counter %s\n", e.name.c_str()); return 2; }
    }

    auto dumpNow = [&] {
        std::FILE* f = std::fopen(dumpPath, "w");
        if (!f) { std::fprintf(stderr, "cannot write %s\n", dumpPath); return; }
        ofp::dumpState(w, f);
        std::fclose(f);
    };

    // Non-finite state is a failure even when both builds agree (see ofp::countNonFinite),
    // and so is one held by an object removed since the last scan (the engine's
    // diagnostic, OceanWorld::totalNonFiniteRemoved: it died within a step).
    long nonFiniteMax = 0, nonFiniteFirst = -1;
    long long removedSeen = 0;   // w.totalNonFiniteRemoved at the last scan
    ofp::Hasher chain;   // every step's full fingerprint, in order
    ofp::Hasher appchain;   // every step's appearance section (kept apart from `chain`: cosmetic)
    Coverage cover;
    auto observe = [&](long step, bool printIt) {
        if (sparse && !printIt) return;
        const ofp::Fingerprint fp = ofp::fingerprint(w);
        chain.u64(fp.all);
        if (fp.appShown) appchain.u64(fp.app);
        const long nf = ofp::countNonFinite(w) + (long)(w.totalNonFiniteRemoved - removedSeen);
        removedSeen = w.totalNonFiniteRemoved;
        if (nf > 0 && nonFiniteFirst < 0) nonFiniteFirst = step;
        nonFiniteMax = std::max(nonFiniteMax, nf);
        if (printIt) {
            std::fputs(ofp::fingerprintLine("fp", step, w, fp).c_str(), stdout);
            if (!sparse) std::printf(" chain=%016llx", (unsigned long long)chain.value());
            if (!sparse && fp.appShown) std::printf(" appchain=%016llx", (unsigned long long)appchain.value());
            std::fputc('\n', stdout);
        }
    };

    observe(0, true);
    cover.after(w);
    if (dumpPath && dumpStep == 0) dumpNow();

    const auto t0 = std::chrono::steady_clock::now();
    for (long s = 0; s < steps; ++s) {
        for (const LiveSet& ls : sets)
            if (ls.step == s && !applySet(w, ls, unchecked)) {
                std::fprintf(stderr, "--set %s refused\n", ls.name.c_str());
                // The state the refusal left, which must be the state before it
                // (wasm/ocean_parity.sh compares it with a run without the --set).
                std::printf("%s\n", ofp::fingerprintLine("refused", s, w, ofp::fingerprint(w)).c_str());
                return 4;
            }
        cover.before(w);
        w.update(0.016f);
        cover.after(w);
        const long done = s + 1;
        observe(done, done % every == 0 || done == steps);
        if (dumpPath && done == dumpStep) dumpNow();
    }
    const double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();

    const auto values = cover.values(w);
    std::printf("cover");
    for (const auto& kv : values)
        if (kv.second != 0 || !Coverage::quietWhenZero(kv.first)) std::printf(" %s=%lld", kv.first.c_str(), kv.second);
    std::printf("\n");
    int unmet = 0;
    for (const Expect& e : expects) {
        const long long got = values.at(e.name);
        const bool ok = holds(e, got);
        std::printf("expect %s %s (got %lld)\n", e.text.c_str(), ok ? "ok" : "FAILED", got);
        if (!ok) {
            ++unmet;
            std::fprintf(stderr, "expectation %s not met (got %lld): the case did not reach what it is for\n",
                         e.text.c_str(), got);
        }
    }

    double mean, sd, hist[ocean::kDepthBins];
    w.depthStats(mean, sd, hist);
    std::printf("final frame=%llu pop=%zu food=%zu pred=%zu births=%lld deaths=%lld reseeds=%lld"
                " predBirths=%lld nonfinite_max=%ld nonfinite_from=%ld zmean=%.6f zsd=%.6f hist",
                w.frame, w.creatures.size(), w.food.size(), w.predators.size(), w.totalBirths,
                w.totalDeaths, w.totalReseeds, w.totalPredatorBirths, nonFiniteMax, nonFiniteFirst, mean, sd);
    for (double h : hist) std::printf(" %.4f", h);
    std::printf("\n");
    std::fflush(stdout);
    std::fprintf(stderr, "# %ld steps, %.2f s, %.0f steps/s, pop %zu\n", steps, secs,
                 steps / (secs > 0 ? secs : 1e-9), w.creatures.size());
    return unmet ? 5 : 0;
}

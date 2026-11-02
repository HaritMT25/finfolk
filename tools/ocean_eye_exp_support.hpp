#pragma once
// ocean_eye_exp_support.hpp — the ALIFE 2027 experiment's instruments for
// tools/ocean_eye_exp.cpp (protocol v2, experiments/alife2027/v2/). Every
// one is OPT-IN (a driver flag) and OBSERVATION-ONLY: it reads the world
// through a const reference and never touches the simulation's rng, except the
// branch suite, which runs copies of the world under copies of the rng and
// puts the parent's rng back (RngGuard) before it returns.
//
//   FpObserver      fingerprints (tools/ocean_fingerprint.hpp, format 4): sparse
//                   (only the printed steps: init, every K, the last) or dense
//                   (every step folded into a chain, as ocean_parity_driver,
//                   printed at the same steps); non-finite state counted at
//                   every observation (and the engine's removed-object count)
//   StepDiag        per-step accumulators the 10k CSV cannot give: population
//                   AUC (sum of N(t), integer), minimum population (post-floor,
//                   and pre-floor = N - the founders the floor added that step),
//                   first-rescue step, rescue steps, food arrivals (the spawn
//                   rule replayed from outside) and the food identity
//                   F_after = F_before + arrivals - eaten - expired per step
//   EncounterDiag   pairs of live fish within the 3-D interaction radius (the
//                   engine's dist2), the mating funnel over those pairs (both
//                   age > 5 and reproTimer <= 0, then both reserves > reproEnergy:
//                   kernel::pairingAllowed's conjuncts), the fish that interacted
//                   this step (interactTimer == interactCooldown after update) and
//                   that paired (reproTimer == reproCooldown), births, and the
//                   durations of encounters (a pair of unchanged fish ids within
//                   the radius on consecutive steps)
//   runContinuation the common-history branch: copy world AND rng, apply one
//                   intervention (eye / eyeOnly / steerFrame / eyeCode /
//                   labelFrame), run K steps, record intake, clearance, food
//                   stock and identity, population, births, deaths, speed,
//                   fingerprints every 250 steps (with the BRANCH's rng
//                   installed), then restore the parent's rng
//   writeConfigJson every SimConfig and OceanConfig field by name (the
//                   fingerprint's visitors: the field-count tripwires keep the
//                   list complete), floats as %.9g plus their bit patterns
//
// Needs tools/ocean_fingerprint.hpp included first. Plain standard C++ (the
// unit tests build it to wasm too).
#include <algorithm>
#include <cinttypes>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace alx {

inline constexpr int kDiagFormat = 1;
inline constexpr int kBranchFormat = 1;
inline constexpr int kEncounterFormat = 1;

// ---- the rng: restored on every exit -----------------------------------------------
struct RngGuard {
    RandomGen saved;
    RngGuard() : saved(rng) {}
    ~RngGuard() { rng = saved; }
    RngGuard(const RngGuard&) = delete;
    RngGuard& operator=(const RngGuard&) = delete;
};

// ---- arm / intervention keys --------------------------------------------------------
// The OceanConfig int keys an arm or a branch may set after initialization.
// labelFrame exists only in an engine that has it (EVO_HAS_LABEL_FRAME, set by
// src/ocean/ocean_config.hpp); elsewhere asking for it is an error.
inline bool setArmKey(OceanConfig& oc, const std::string& key, int value, std::string& err) {
    if (key == "eye") oc.eye = value;
    else if (key == "eyeOnly") oc.eyeOnly = value;
    else if (key == "steerFrame") oc.steerFrame = value;
    else if (key == "eyeCode") oc.eyeCode = value;
#ifdef EVO_HAS_LABEL_FRAME
    else if (key == "labelFrame") oc.labelFrame = value;
#endif
    else { err = "unknown or unsupported arm key '" + key + "'"; return false; }
    if (!oceanConfigValid(oc)) { err = "invalid ocean config after " + key + "=" + std::to_string(value) + ": " + oceanConfigError(oc); return false; }
    return true;
}

inline int armKey(const OceanConfig& oc, const std::string& key) {
    if (key == "eye") return oc.eye;
    if (key == "eyeOnly") return oc.eyeOnly;
    if (key == "steerFrame") return oc.steerFrame;
    if (key == "eyeCode") return oc.eyeCode;
#ifdef EVO_HAS_LABEL_FRAME
    if (key == "labelFrame") return oc.labelFrame;
#endif
    return 0;
}

inline bool hasLabelFrame() {
#ifdef EVO_HAS_LABEL_FRAME
    return true;
#else
    return false;
#endif
}

// One continuation: a name and its changes. Spec syntax (the runner passes it
// from protocol.json): "name:key=v,key=v;name2:;name3:key=v" (no changes = sham).
struct BranchSpec {
    std::string name;
    std::vector<std::pair<std::string, int>> changes;
    std::string text() const {
        std::string s;
        for (const auto& c : changes) s += (s.empty() ? "" : ",") + c.first + "=" + std::to_string(c.second);
        return s.empty() ? "none" : s;
    }
};

inline bool parseBranchSpecs(const std::string& s, std::vector<BranchSpec>& out, std::string& err) {
    out.clear();
    std::size_t p = 0;
    while (p <= s.size()) {
        const std::size_t e = std::min(s.find(';', p), s.size());
        const std::string item = s.substr(p, e - p);
        p = e + 1;
        if (item.empty()) { if (e >= s.size()) break; continue; }
        const std::size_t c = item.find(':');
        if (c == std::string::npos || c == 0) { err = "branch '" + item + "': want NAME:changes"; return false; }
        BranchSpec b;
        b.name = item.substr(0, c);
        for (const BranchSpec& o : out)
            if (o.name == b.name) { err = "branch name '" + b.name + "' twice"; return false; }
        std::string ch = item.substr(c + 1);
        std::size_t q = 0;
        while (q < ch.size()) {
            const std::size_t f = std::min(ch.find(',', q), ch.size());
            const std::string kv = ch.substr(q, f - q);
            q = f + 1;
            const std::size_t eq = kv.find('=');
            if (eq == std::string::npos || eq == 0 || eq + 1 >= kv.size()) { err = "branch '" + b.name + "': bad change '" + kv + "'"; return false; }
            char* end = nullptr;
            const long v = std::strtol(kv.c_str() + eq + 1, &end, 10);
            if (*end != '\0') { err = "branch '" + b.name + "': bad value in '" + kv + "'"; return false; }
            b.changes.emplace_back(kv.substr(0, eq), (int)v);
        }
        out.push_back(std::move(b));
        if (e >= s.size()) break;
    }
    if (out.empty()) { err = "no branches"; return false; }
    return true;
}

// ---- configs as JSON (every field, by name) --------------------------------------
struct JsonFields {
    std::string body, bitsBody;
    void sep(std::string& s) { if (!s.empty()) s += ","; }
    void f32(const char* k, float v) {
        char b[96];
        if (std::isfinite(v)) std::snprintf(b, sizeof b, "\"%s\":%.9g", k, (double)v);
        else std::snprintf(b, sizeof b, "\"%s\":null", k);
        sep(body); body += b;
        std::snprintf(b, sizeof b, "\"%s\":\"%08" PRIx32 "\"", k, ofp::bits(v));
        sep(bitsBody); bitsBody += b;
    }
    void i32(const char* k, int v) { char b[96]; std::snprintf(b, sizeof b, "\"%s\":%d", k, v); sep(body); body += b; }
    void b(const char* k, bool v) { char t[96]; std::snprintf(t, sizeof t, "\"%s\":%s", k, v ? "true" : "false"); sep(body); body += t; }
};

inline std::string configJson(const SimConfig& sc, const OceanConfig& oc) {
    JsonFields s, o;
    ofp::visitSimConfig(sc, s);
    ofp::visitOceanConfig(oc, o);
    ofp::visitOceanConfigVision(oc, o);
    ofp::visitOceanConfigAppearance(oc, o);
    ofp::visitOceanConfigWalls(oc, o);
    return "{\"sim\":{" + s.body + "},\"ocean\":{" + o.body + "},\"f32_bits\":{\"sim\":{" + s.bitsBody + "},\"ocean\":{" +
           o.bitsBody + "}}}";
}

inline std::string jsonEscape(const std::string& s) {
    std::string o;
    for (char c : s) {
        if (c == '"' || c == '\\') { o += '\\'; o += c; }
        else if ((unsigned char)c < 0x20) { char b[8]; std::snprintf(b, sizeof b, "\\u%04x", (unsigned)(unsigned char)c); o += b; }
        else o += c;
    }
    return o;
}

// ---- the food the step will add and expire, from outside ---------------------------
// OceanWorld::update: every live item ages by dt (foodLife > 0) and goes at
// age >= foodLife; then int(foodSpawnBase + foodSpawnAmp·sinf(frame·0.001))
// spawn attempts, each adding an item while food.size() - expiredNow <
// 2·targetFood. Before update every item in `food` is alive (the step erases
// the dead), so this is the same arithmetic on the same floats.
struct FoodStepPrediction { long long arrivals = 0, expiring = 0; };

inline FoodStepPrediction predictFood(const OceanWorld& w, float dt) {
    FoodStepPrediction p;
    if (w.ocfg.foodLife > 0.0f)
        for (const OceanFood& f : w.food) {
            if (!f.alive) continue;
            float a = f.age;
            a += dt;
            if (a >= w.ocfg.foodLife) ++p.expiring;
        }
    const auto frame = w.frame + 1;
    const float foodRate = w.cfg.foodSpawnBase + w.cfg.foodSpawnAmp * evomath::sinf(frame * 0.001f);
    long long size = (long long)w.food.size();
    for (int i = 0; i < static_cast<int>(foodRate); ++i)
        if (static_cast<int>(size) - (int)p.expiring < w.cfg.targetFood * 2) { ++size; ++p.arrivals; }
    return p;
}

// ---- per-step diagnostics (the sidecar CSV) ---------------------------------------
struct StepDiag {
    long long n0 = 0;                 // population at step 0 (after arm resolution)
    long long auc = 0;                // sum over completed steps of N(t), post-floor
    long long minPost = 0, minPre = 0, minPostStep = 0, minPreStep = 0;
    long long firstReseed = -1, reseedSteps = 0;
    long long arrivals = 0, identityBad = 0, expiryBad = 0;
    long long steps = 0;
    // before() snapshot
    long long fBefore = 0, eatenBefore = 0, expiredBefore = 0, reseedsBefore = 0;
    FoodStepPrediction pred;

    void begin(const OceanWorld& w) {
        n0 = (long long)w.creatures.size();
        minPost = minPre = n0;
        minPostStep = minPreStep = 0;
    }
    void before(const OceanWorld& w, float dt) {
        pred = predictFood(w, dt);
        fBefore = (long long)w.food.size();
        eatenBefore = w.totalFoodEaten;
        expiredBefore = w.totalFoodExpired;
        reseedsBefore = w.totalReseeds;
    }
    void after(const OceanWorld& w, long long step) {
        ++steps;
        const long long n = (long long)w.creatures.size();
        const long long added = w.totalReseeds - reseedsBefore;
        auc += n;
        if (n < minPost) { minPost = n; minPostStep = step; }
        if (n - added < minPre) { minPre = n - added; minPreStep = step; }
        if (added > 0) {
            ++reseedSteps;
            if (firstReseed < 0) firstReseed = step;
        }
        arrivals += pred.arrivals;
        const long long eaten = w.totalFoodEaten - eatenBefore, expired = w.totalFoodExpired - expiredBefore;
        if ((long long)w.food.size() != fBefore + pred.arrivals - eaten - expired) ++identityBad;
        if (expired != pred.expiring) ++expiryBad;
    }
    static const char* header() {
        return "step,pop,births,deaths,deaths_pred,deaths_starve,deaths_age,reseeds,reseed_steps,first_reseed_step,"
               "min_pop,min_pop_step,min_pop_pre_floor,min_pop_pre_floor_step,auc_pop,food,food_eaten,food_expired,"
               "food_arrivals,food_identity_bad,food_expiry_bad,pred,pred_births,pred_reseeds,pred_starved,pred_aged,"
               "nonfinite_removed,diag_steps";
    }
    void row(std::FILE* f, const OceanWorld& w, long long step) const {
        std::fprintf(f, "%lld,%zu,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%zu,%lld,%lld,%lld,%lld,%lld,"
                        "%zu,%lld,%lld,%lld,%lld,%lld,%lld\n",
                     step, w.creatures.size(), w.totalBirths, w.totalDeaths, w.totalDeathsPredation, w.totalDeathsStarvation,
                     w.totalDeathsAge, w.totalReseeds, reseedSteps, firstReseed, minPost, minPostStep, minPre, minPreStep, auc,
                     w.food.size(), w.totalFoodEaten, w.totalFoodExpired, arrivals, identityBad, expiryBad,
                     w.predators.size(), w.totalPredatorBirths, w.totalPredatorReseeds, w.totalPredatorDeathsStarvation,
                     w.totalPredatorDeathsAge, w.totalNonFiniteRemoved, steps);
    }
};

// ---- fingerprints ------------------------------------------------------------------
struct FpObserver {
    bool dense = false;
    std::FILE* out = nullptr;
    ofp::Hasher chain, appchain;
    long long observed = 0, nonFiniteMax = 0, nonFiniteFirst = -1, removedSeen = 0;
    ofp::Fingerprint last;
    long long lastStep = -1;

    // Call at step 0 and after every update; printIt at the printed steps. In
    // sparse mode the unprinted steps are not observed at all (no hashing).
    void observe(const OceanWorld& w, long long step, bool printIt) {
        if (!dense && !printIt) return;
        last = ofp::fingerprint(w);
        lastStep = step;
        ++observed;
        if (dense) {
            chain.u64(last.all);
            if (last.appShown) appchain.u64(last.app);
        }
        const long long nf = ofp::countNonFinite(w) + (w.totalNonFiniteRemoved - removedSeen);
        removedSeen = w.totalNonFiniteRemoved;
        if (nf > 0 && nonFiniteFirst < 0) nonFiniteFirst = step;
        nonFiniteMax = std::max(nonFiniteMax, nf);
        if (printIt && out) {
            std::fputs(ofp::fingerprintLine("fp", step, w, last).c_str(), out);
            if (dense) std::fprintf(out, " chain=%016" PRIx64, chain.value());
            if (dense && last.appShown) std::fprintf(out, " appchain=%016" PRIx64, appchain.value());
            std::fprintf(out, " observed=%lld nonfinite=%lld\n", observed, nf);
        }
    }
};

// ---- encounters and the mating funnel -------------------------------------------
struct EncounterDiag {
    // per-interval sums (reset by the caller after each row)
    long long pairSteps = 0, ageCooldownSteps = 0, energySteps = 0, readySteps = 0;
    long long interacted = 0, paired = 0, births = 0, steps = 0;
    // encounters (pairs of fish ids within the radius on consecutive steps)
    std::unordered_map<std::uint64_t, long long> open;   // key -> first step within radius
    long long encounters = 0, encounterSteps = 0, hist[6] = {};   // completed: durations 1, 2-5, 6-20, 21-100, 101-1000, >1000
    double relSpeedSum = 0;   // |velocity difference| summed over in-radius pair-steps (3-D: vel·speed, vz)
    long long birthsBefore = 0;

    static int bin(long long d) { return d <= 1 ? 0 : d <= 5 ? 1 : d <= 20 ? 2 : d <= 100 ? 3 : d <= 1000 ? 4 : 5; }

    // OceanWorld::dist2 (private) for a non-toroidal world: the same float
    // expression, term order and all. Toroidal worlds are refused
    // (supported()), rather than re-deriving the engine's wrap.
    static float dist2(Vec2 a, float za, Vec2 b, float zb) {
        const float dx = b.x - a.x, dy = b.y - a.y;
        const float dz = zb - za;
        return dx * dx + dy * dy + dz * dz;
    }
    static bool supported(const OceanWorld& w) { return !w.cfg.toroidal; }

    void before(const OceanWorld& w) { birthsBefore = w.totalBirths; }

    void after(const OceanWorld& w, long long step) {
        ++steps;
        births += w.totalBirths - birthsBefore;
        if (!supported(w)) return;
        const float ir2 = w.cfg.interactRadius * w.cfg.interactRadius;
        const float re = w.cfg.reproEnergy;
        std::vector<int> idx;
        idx.reserve(w.creatures.size());
        for (int i = 0; i < (int)w.creatures.size(); ++i) {
            const Fish& c = w.creatures[i];
            if (!c.alive) continue;
            idx.push_back(i);
            interacted += c.interactTimer == w.cfg.interactCooldown;
            paired += c.reproTimer == w.cfg.reproCooldown;
        }
        std::unordered_map<std::uint64_t, long long> now;
        now.reserve(open.size() + 16);
        auto visit = [&](int i, int j) {
            const Fish& a = w.creatures[i];
            const Fish& b = w.creatures[j];
            if (dist2(a.pos, a.depth, b.pos, b.depth) > ir2) return;
            ++pairSteps;
            const bool ac = a.age > 5.0f && b.age > 5.0f && a.reproTimer <= 0.0f && b.reproTimer <= 0.0f;
            ageCooldownSteps += ac;
            energySteps += ac && a.foodReserves > re && b.foodReserves > re;
            readySteps += a.interactTimer <= 0.0f && b.interactTimer <= 0.0f;
            const double dvx = (double)a.vel.x * a.speed - (double)b.vel.x * b.speed;
            const double dvy = (double)a.vel.y * a.speed - (double)b.vel.y * b.speed;
            const double dvz = (double)a.vz - (double)b.vz;
            relSpeedSum += std::sqrt(dvx * dvx + dvy * dvy + dvz * dvz);
            const std::uint64_t lo = std::min(a.id, b.id), hi = std::max(a.id, b.id);
            const std::uint64_t key = (lo << 32) ^ hi;
            const auto it = open.find(key);
            now.emplace(key, it == open.end() ? step : it->second);
        };
        {
            // sweep along x: once dx^2 > r^2 no later fish (larger dx) is within r
            std::sort(idx.begin(), idx.end(), [&](int a, int b) {
                const float xa = w.creatures[a].pos.x, xb = w.creatures[b].pos.x;
                return xa < xb || (xa == xb && a < b);
            });
            const float r = w.cfg.interactRadius;
            for (std::size_t p = 0; p < idx.size(); ++p) {
                const float x0 = w.creatures[idx[p]].pos.x;
                for (std::size_t q = p + 1; q < idx.size(); ++q) {
                    const float dx = w.creatures[idx[q]].pos.x - x0;
                    if (dx > r && dx * dx > ir2) break;
                    visit(std::min(idx[p], idx[q]), std::max(idx[p], idx[q]));
                }
            }
        }
        for (const auto& kv : open)
            if (!now.count(kv.first)) {   // ended (apart, or one of the two is gone)
                const long long d = step - kv.second;
                ++encounters;
                encounterSteps += d;
                ++hist[bin(d)];
            }
        open.swap(now);
    }
    static const char* header() {
        return "step,steps,pair_steps,pair_steps_age_cooldown,pair_steps_energy,pair_steps_interact_ready,"
               "fish_interacted,fish_paired,births,encounters_ended,encounter_steps_ended,enc_1,enc_2_5,enc_6_20,"
               "enc_21_100,enc_101_1000,enc_gt_1000,open_encounters,rel_speed_mean";
    }
    void row(std::FILE* f, long long step) const {
        std::fprintf(f, "%lld,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%zu,%.6f\n", step,
                     steps, pairSteps, ageCooldownSteps, energySteps, readySteps, interacted, paired, births, encounters,
                     encounterSteps, hist[0], hist[1], hist[2], hist[3], hist[4], hist[5], open.size(),
                     pairSteps ? relSpeedSum / (double)pairSteps : 0.0);
    }
    void resetInterval() {
        pairSteps = ageCooldownSteps = energySteps = readySteps = interacted = paired = births = steps = 0;
        encounters = encounterSteps = 0;
        for (long long& h : hist) h = 0;
        relSpeedSum = 0;
    }
};

// ---- the common-history branch --------------------------------------------------
struct BranchResult {
    std::string name, changes;
    long long checkpoint = 0, steps = 0;
    long long n0 = 0, f0 = 0;
    long long eaten = 0, expired = 0, arrivals = 0, identityBad = 0, expiryBad = 0;
    long long fEnd = 0, nEnd = 0, births = 0, deaths = 0, deathsPred = 0, deathsStarve = 0, deathsAge = 0, reseeds = 0;
    double popMean = 0, foodMean = 0, speedEnd = 0, speedMean = 0;
    double clearance = 0, clearanceNorm = 0, intakePerN0 = 0, intakePerFishTime = 0;
    long long early = 0, eatenEarly = 0, birthsEarly = 0;
    double speedEarly = 0;
    long long pairSteps = 0, encountersEnded = 0, encounterStepsEnded = 0;
    long long nonFinite = 0;
    std::vector<std::pair<long long, ofp::Fingerprint>> fps;   // (step offset, fingerprint), offsets 0, every, ..., steps
    ofp::Hasher chain;   // dense: every step's `all`
    bool dense = false;
};

// Copy the parent world and rng, apply the spec, run `steps` updates. The
// parent's world is not touched; the global rng is the parent's again on
// return (RngGuard), whatever happens. Fingerprints are taken with the
// branch's own rng installed (the rng section is the branch's).
inline bool runContinuation(const OceanWorld& parent, const RandomGen& parentRng, const BranchSpec& spec, long long checkpoint,
                            long long steps, long long fpEvery, long long earlySteps, bool dense, float dt, BranchResult& r,
                            std::string& err) {
    RngGuard guard;
    rng = parentRng;
    OceanWorld w = parent;
    for (const auto& c : spec.changes)
        if (!setArmKey(w.ocfg, c.first, c.second, err)) { err = "branch " + spec.name + ": " + err; return false; }
    r = BranchResult{};
    r.name = spec.name;
    r.changes = spec.text();
    r.checkpoint = checkpoint;
    r.steps = steps;
    r.dense = dense;
    r.n0 = (long long)w.creatures.size();
    r.f0 = (long long)w.food.size();
    const long long eaten0 = w.totalFoodEaten, expired0 = w.totalFoodExpired, births0 = w.totalBirths, deaths0 = w.totalDeaths,
                    dp0 = w.totalDeathsPredation, ds0 = w.totalDeathsStarvation, da0 = w.totalDeathsAge,
                    reseeds0 = w.totalReseeds, removed0 = w.totalNonFiniteRemoved;
    {
        const ofp::Fingerprint fp = ofp::fingerprint(w);
        r.fps.emplace_back(0, fp);
        if (dense) r.chain.u64(fp.all);
    }
    StepDiag diag;
    diag.begin(w);
    EncounterDiag enc;
    double sumPop = 0, sumFood = 0, sumSpeed = 0, speedEarlySum = 0;
    for (long long s = 1; s <= steps; ++s) {
        diag.before(w, dt);
        enc.before(w);
        w.update(dt);
        diag.after(w, s);
        enc.after(w, s);
        sumPop += (double)w.creatures.size();
        sumFood += (double)w.food.size();
        double sp = 0;
        for (const Fish& f : w.creatures) sp += f.speed;
        const double meanSpeed = w.creatures.empty() ? 0.0 : sp / (double)w.creatures.size();
        sumSpeed += meanSpeed;
        if (s <= earlySteps) speedEarlySum += meanSpeed;
        if (s == earlySteps) {
            r.eatenEarly = w.totalFoodEaten - eaten0;
            r.birthsEarly = w.totalBirths - births0;
        }
        const bool printIt = (fpEvery > 0 && s % fpEvery == 0) || s == steps;
        if (dense || printIt) {
            const ofp::Fingerprint fp = ofp::fingerprint(w);
            if (dense) r.chain.u64(fp.all);
            if (printIt) r.fps.emplace_back(s, fp);
            r.nonFinite = std::max<long long>(r.nonFinite, ofp::countNonFinite(w));
        }
    }
    r.early = std::min(earlySteps, steps);
    r.speedEarly = r.early > 0 ? speedEarlySum / (double)r.early : 0.0;
    r.nonFinite += w.totalNonFiniteRemoved - removed0;
    r.eaten = w.totalFoodEaten - eaten0;
    r.expired = w.totalFoodExpired - expired0;
    r.arrivals = diag.arrivals;
    r.identityBad = diag.identityBad;
    r.expiryBad = diag.expiryBad;
    r.fEnd = (long long)w.food.size();
    r.nEnd = (long long)w.creatures.size();
    r.births = w.totalBirths - births0;
    r.deaths = w.totalDeaths - deaths0;
    r.deathsPred = w.totalDeathsPredation - dp0;
    r.deathsStarve = w.totalDeathsStarvation - ds0;
    r.deathsAge = w.totalDeathsAge - da0;
    r.reseeds = w.totalReseeds - reseeds0;
    r.pairSteps = enc.pairSteps;
    r.encountersEnded = enc.encounters;
    r.encounterStepsEnded = enc.encounterSteps;
    const double n = (double)steps;
    r.popMean = steps ? sumPop / n : 0.0;
    r.foodMean = steps ? sumFood / n : 0.0;
    r.speedMean = steps ? sumSpeed / n : 0.0;
    double spd = 0;
    for (const Fish& f : w.creatures) spd += f.speed;
    const double np = w.creatures.empty() ? 1.0 : (double)w.creatures.size();
    r.speedEnd = spd / np;
    // The driver's interval clearance (tools/ocean_eye_exp.cpp), on the branch.
    const double simSecs = n * (double)dt;
    const double volume = (double)w.width * (double)w.height * (double)w.D;
    const double eatPerFish = r.popMean > 0 ? (double)r.eaten / (r.popMean * simSecs) : 0.0;
    const double density = r.foodMean / volume;
    r.clearance = density > 0 ? eatPerFish / density : 0.0;
    const double pickup = w.cfg.pickupRadius;
    const double sweep = 3.14159265 * pickup * pickup * (spd / np);
    r.clearanceNorm = sweep > 0 ? r.clearance / sweep : 0.0;
    r.intakePerN0 = r.n0 > 0 ? (double)r.eaten / (double)r.n0 : 0.0;
    r.intakePerFishTime = eatPerFish;
    return true;
}

inline const char* branchHeader() {
    return "seed,arm,checkpoint,branch,changes,steps,n0,food0,eaten,eaten_per_n0,eaten_per_fish_s,clearance,clearance_norm,"
           "food_end,food_mean,food_arrivals,food_expired,food_identity_bad,food_expiry_bad,pop_end,pop_mean,births,deaths,"
           "deaths_pred,deaths_starve,deaths_age,reseeds,speed_end,speed_mean,early_steps,eaten_early,births_early,"
           "speed_early,pair_steps,encounters_ended,encounter_steps_ended,nonfinite,fp_end,chain";
}

inline void branchRow(std::FILE* f, unsigned seed, const char* arm, const BranchResult& r) {
    std::fprintf(f, "%u,%s,%lld,%s,%s,%lld,%lld,%lld,%lld,%.9g,%.9g,%.9g,%.9g,%lld,%.9g,%lld,%lld,%lld,%lld,%lld,%.9g,%lld,%lld,"
                    "%lld,%lld,%lld,%lld,%.9g,%.9g,%lld,%lld,%lld,%.9g,%lld,%lld,%lld,%lld,%016" PRIx64 ",",
                 seed, arm, r.checkpoint, r.name.c_str(), r.changes.c_str(), r.steps, r.n0, r.f0, r.eaten, r.intakePerN0,
                 r.intakePerFishTime, r.clearance, r.clearanceNorm, r.fEnd, r.foodMean, r.arrivals, r.expired, r.identityBad,
                 r.expiryBad, r.nEnd, r.popMean, r.births, r.deaths, r.deathsPred, r.deathsStarve, r.deathsAge, r.reseeds,
                 r.speedEnd, r.speedMean, r.early, r.eatenEarly, r.birthsEarly, r.speedEarly, r.pairSteps,
                 r.encountersEnded, r.encounterStepsEnded, r.nonFinite, r.fps.empty() ? 0 : r.fps.back().second.all);
    if (r.dense) std::fprintf(f, "%016" PRIx64, r.chain.value());
    std::fputc('\n', f);
}

}  // namespace alx

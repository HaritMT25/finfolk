// ocean_exp_tests.hpp — the ALIFE 2027 experiment instruments
// (tools/ocean_eye_exp_support.hpp, protocol v2). Included by
// tests/ocean_tests.cpp inside namespace ot (uses its Test, mkGene); eye build
// only (the driver is). Runs native and wasm under wasm/ocean_parity.sh, whose
// output comparison makes every note below a native == wasm check too.
//   exp_arms_init   every v2 arm's keys, installed after the common
//                   initialization, change only the config section
//   exp_observers   every instrument on (dense chain, diagnostics, encounters)
//                   leaves the run's end state and rng as without; the food
//                   identity / expiry replay hold every step (also with the
//                   spawn cap binding); the dense chain catches a transient
//                   change the end state does not show
//   exp_branches    sham continuation == the uninterrupted run; parent world
//                   and rng untouched; continuation order irrelevant; every
//                   intervention changes the run; branch-spec parsing
//   label_frame     (both builds) OceanConfig::labelFrame, the A1 arm's own-frame
//                   labels, on hand-built scenes: the six projected inputs'
//                   exact values (food, neighbour offset before tanh, heading),
//                   every other input bit-identical to labelFrame 0 (predator /
//                   population FWD / LR not rotated again), exact invariance
//                   under a 90-degree turn of the whole scene (world-frame
//                   labels are not), a NEAREST_FOOD_DX -> STEER_X wire turning
//                   toward food on either side from 8 headings under
//                   steerFrame 1; 0 / 1 valid, others refused; labelFrame 0 ==
//                   the key absent, every section (sense_ref_a1 in
//                   tests/ocean_sense_tests.hpp checks 600 random scenes)
//   label_mask      (both builds) the dead-sensor skip (turbo-speed-1) under
//                   labelFrame 1, where each projected input reads both world
//                   components of its vector: capture off (the skip) == capture
//                   on (every sensor) each step — dynamics, neuron outputs, each
//                   world's own rng stream — (a) every fish reading ONE
//                   projected input, sense_dce's rich worlds; (b) long runs (the
//                   A1 arm in the L12 ecology, 2000 steps; toroidal topological,
//                   600) whose founders each read one projected input, with
//                   births and mutation; fish reading one component of a pair
//                   but not the other required in every pair, at the end too.
//                   tests/label_mask_fault.sh plants three wrongly-masked
//                   components in a copy of the engine: each must fail it

// One step of a quiet scene around a viewer at (500, 500, 120) heading `head`
// (rotated by quarter turns `q`, about the viewer): food 20 to world +x, two
// neighbours, a predator; returns the viewer's captured inputs.
inline void labelScene(int labelFrame, int q, float out[NUM_SENSES]) {
    auto rot = [q](Vec2 v) { for (int i = 0; i < q; ++i) v = {-v.y, v.x}; return v; };
    OceanConfig oc;
    oc.labelFrame = labelFrame;
    OceanWorld w;
    initQuiet(w, 2027, 240.0f, oc, /*capture*/ true);
    const Vec2 P = {500.0f, 500.0f};
    auto at = [&](float dx, float dy) { const Vec2 d = rot({dx, dy}); return Vec2{P.x + d.x, P.y + d.y}; };
    sense::addQuiet(w, P.x, P.y, 120.0f, rot({0.0f, 1.0f}));
    sense::addQuiet(w, at(10, 30).x, at(10, 30).y, 120.0f, rot({1.0f, 0.0f}));
    sense::addQuiet(w, at(-20, 10).x, at(-20, 10).y, 130.0f, rot({0.0f, -1.0f}));
    sense::addFood(w, at(20, 0).x, at(20, 0).y, 120.0f);
    OceanPredator p;
    p.pos = at(-30, -60);
    p.depth = 110.0f;
    p.vel = rot({1.0f, 0.0f});
    p.digestTimer = 1e9f;
    w.predators.push_back(p);
    w.update(0.016f);
    std::memcpy(out, w.creatures[0].lastSensors, sizeof(float) * NUM_SENSES);
}

inline void testLabelFrame() {
    Test t("label_frame");
    constexpr int kOwn[] = {NEAREST_FOOD_DX, NEAREST_FOOD_DY, AVG_NEIGHBOR_DX, AVG_NEIGHBOR_DY, AVG_NEIGHBOR_HEADING_X,
                            AVG_NEIGHBOR_HEADING_Y};
    auto isOwn = [&](int k) { for (int o : kOwn) if (o == k) return true; return false; };
    float w0[NUM_SENSES], w1[NUM_SENSES];
    labelScene(0, 0, w0);
    labelScene(1, 0, w1);
    // heading +y: fwd (0, 1), right (-1, 0). Food at world +x is on the LEFT.
    t.expect(w0[NEAREST_FOOD_DX] == 1.0f && w0[NEAREST_FOOD_DY] == 0.0f, "world-frame food (%g, %g)", w0[NEAREST_FOOD_DX],
             w0[NEAREST_FOOD_DY]);
    t.expect(w1[NEAREST_FOOD_DX] == -1.0f && w1[NEAREST_FOOD_DY] == 0.0f, "own-frame food (%g, %g), want (-1, 0)",
             w1[NEAREST_FOOD_DX], w1[NEAREST_FOOD_DY]);
    // neighbours at (+10, +30) and (-20, +10): mean offset (-5, 20) -> right 5, ahead 20, BEFORE the tanh
    const float R = 100.0f;
    t.expect(sense::sameBits(w1[AVG_NEIGHBOR_DX], evomath::tanhf(((-5.0f) * (-1.0f) + 20.0f * 0.0f) / R)) &&
                 sense::sameBits(w1[AVG_NEIGHBOR_DY], evomath::tanhf(((-5.0f) * 0.0f + 20.0f * 1.0f) / R)),
             "own-frame neighbour offset (%.9g, %.9g)", w1[AVG_NEIGHBOR_DX], w1[AVG_NEIGHBOR_DY]);
    t.expect(sense::sameBits(w0[AVG_NEIGHBOR_DX], evomath::tanhf(-5.0f / R)) && sense::sameBits(w0[AVG_NEIGHBOR_DY], evomath::tanhf(20.0f / R)),
             "world-frame neighbour offset (%.9g, %.9g)", w0[AVG_NEIGHBOR_DX], w0[AVG_NEIGHBOR_DY]);
    // neighbour headings (1, 0) and (0, -1): mean (0.5, -0.5) -> right -0.5, ahead -0.5
    t.expect(w1[AVG_NEIGHBOR_HEADING_X] == -0.5f && w1[AVG_NEIGHBOR_HEADING_Y] == -0.5f && w0[AVG_NEIGHBOR_HEADING_X] == 0.5f &&
                 w0[AVG_NEIGHBOR_HEADING_Y] == -0.5f,
             "headings own (%g, %g) world (%g, %g)", w1[AVG_NEIGHBOR_HEADING_X], w1[AVG_NEIGHBOR_HEADING_Y],
             w0[AVG_NEIGHBOR_HEADING_X], w0[AVG_NEIGHBOR_HEADING_Y]);
    long same = 0;
    for (int k = 0; k < NUM_SENSES; ++k)
        if (!isOwn(k)) same += t.expect(sense::sameBits(w0[k], w1[k]), "%s changed with labelFrame", ocean::kSensorNames[k]);
    t.expect(w1[PREDATOR_PROX] > 0.0f && w1[PREDATOR_FWD] != 0.0f && w1[POPULATION_FWD] != 0.0f,
             "fixture: the predator / population inputs are live");
    // the whole scene turned by quarter turns: own-frame labels exactly invariant, world-frame ones not
    long inv = 0, moved = 0;
    for (int q = 1; q < 4; ++q) {
        float r0[NUM_SENSES], r1[NUM_SENSES];
        labelScene(0, q, r0);
        labelScene(1, q, r1);
        for (int k : kOwn) inv += t.expect(sense::sameBits(r1[k], w1[k]), "turn %d: own-frame %s %.9g != %.9g", q, ocean::kSensorNames[k], r1[k], w1[k]);
        for (int k : {PREDATOR_FWD, PREDATOR_LR, POPULATION_FWD, POPULATION_LR, NEAREST_FOOD_DZ, AVG_NEIGHBOR_DZ})
            t.expect(sense::sameBits(r1[k], w1[k]) && sense::sameBits(r0[k], w0[k]), "turn %d: body-relative %s changed", q,
                     ocean::kSensorNames[k]);
        moved += !sense::sameBits(r0[NEAREST_FOOD_DX], w0[NEAREST_FOOD_DX]) || !sense::sameBits(r0[NEAREST_FOOD_DY], w0[NEAREST_FOOD_DY]);
    }
    t.expect(moved == 3, "world-frame food labels did not move with the scene");
    // own-frame steering on own-frame labels: NEAREST_FOOD_DX -> STEER_X (+) turns toward food on either side
    int toward[2] = {0, 0};
    for (int lf = 0; lf < 2; ++lf)
        for (int h = 0; h < 8; ++h)
            for (int side = -1; side <= 1; side += 2) {
                OceanConfig oc;
                oc.labelFrame = lf;
                oc.steerFrame = 1;
                OceanWorld w;
                initQuiet(w, 3000 + h, 240.0f, oc);
                const float a = 6.2831853f * (float)h / 8.0f + 0.2f;
                const Vec2 f0 = {evomath::cosf(a), evomath::sinf(a)}, r0 = {-f0.y, f0.x};
                const int k = addFish(w, {960.0f, 540.0f}, 120.0f, {mkGene(true, NEAREST_FOOD_DX, STEER_X, 8000)}, 0.5f);
                w.creatures[k].vel = f0;
                w.creatures[k].interactTimer = 1e9f;
                sense::addFood(w, 960.0f + 40.0f * (f0.x + side * r0.x), 540.0f + 40.0f * (f0.y + side * r0.y), 120.0f);
                w.update(0.016f);
                const Vec2 f1 = w.creatures[k].forward();
                const float turn = f0.x * f1.y - f0.y * f1.x;   // + = toward the right (r0 = f0 turned +90)
                toward[lf] += (turn * (float)side > 0.0f);
            }
    t.expect(toward[1] == 16, "own-frame labels + own-frame steering: turned toward the food in %d of 16", toward[1]);
    t.expect(toward[0] < 16, "world-frame labels steered toward the food from every heading (%d of 16): no mismatch?", toward[0]);
    // validation, and the key's absence == 0
    OceanConfig oc;
    t.expect(oceanConfigValid(oc), "default refused");
    for (int v : {-1, 2, 7}) {
        oc.labelFrame = v;
        t.expect(!oceanConfigValid(oc), "labelFrame %d accepted", v);
    }
    t.note("own-frame labels: food (%g, %g), offset (%.6f, %.6f), heading (%g, %g); %ld other inputs unchanged; "
           "%ld own-frame values invariant under 3 quarter turns; turned toward food %d / 16 (own) vs %d / 16 (world frame)",
           w1[NEAREST_FOOD_DX], w1[NEAREST_FOOD_DY], w1[AVG_NEIGHBOR_DX], w1[AVG_NEIGHBOR_DY], w1[AVG_NEIGHBOR_HEADING_X],
           w1[AVG_NEIGHBOR_HEADING_Y], same, inv, toward[1], toward[0]);
}

inline void testLabelFrameNeutral() {
    Test t("label_frame_off");
    // labelFrame 0 written explicitly == absent: the same world and run, every section
    OceanWorld a, b;
    std::string err;
    const bool ok = ofp::initWorld(a, 61, 900, 600, 240.0f, 80, R"({"predatorCount":2,"steerFrame":1})", err);
    const RandomGen ra = rng;
    const bool ok2 = ofp::initWorld(b, 61, 900, 600, 240.0f, 80, R"({"predatorCount":2,"steerFrame":1,"labelFrame":0})", err);
    if (!t.expect(ok && ok2, "init: %s", err.c_str())) return;
    t.expect(ra.state() == rng.state(), "init consumed the rng differently");
    rng = ra;
    for (int s = 0; s < 200; ++s) a.update(0.016f);
    const ofp::Fingerprint fa = ofp::fingerprint(a);
    rng = ra;
    for (int s = 0; s < 200; ++s) b.update(0.016f);
    t.expect(fa == ofp::fingerprint(b), "labelFrame 0 changed the run (or its config hash)");
    // labelFrame 1 at init: only the config section differs at step 0
    OceanWorld c, d;
    t.expect(ofp::initWorld(c, 62, 900, 600, 240.0f, 80, R"({"predatorCount":2,"labelFrame":1})", err) &&
                 ofp::initWorld(d, 62, 900, 600, 240.0f, 80, R"({"predatorCount":2})", err),
             "init: %s", err.c_str());
    const ofp::Fingerprint fc = ofp::fingerprint(c), fd = ofp::fingerprint(d);
    t.expect(fc.cfg != fd.cfg && fc.fish == fd.fish && fc.food == fd.food && fc.ctr == fd.ctr && fc.pred == fd.pred,
             "labelFrame 1 at init: the config hash did not change, or another section did");
    t.note("labelFrame 0 == the key absent over 200 steps, every section; labelFrame 1 is hashed (cfg) and changes nothing at init");
}

// protocol v2's L12 ecology (experiments/alife2027/v2/common_l12.json)
constexpr const char* kExpL12 =
    R"({"walls":false,"toroidal":false,"appearance":0,"minPopulation":50,"perceptionRadius":100,"interactRadius":36,)"
    R"("pickupRadius":24,"foodSpawnBase":1,"foodSpawnAmp":0,"foodEnergy":15,"targetFood":800,"foodLife":12,)"
    R"("predatorCount":4,"predatorSpeed":110,"predatorPerception":150,"predatorCaptureRadius":14,"predatorEconomy":true,)"
    R"("predatorCooldown":3,"predatorMetabolism":2,"predatorMoveCost":0,"predatorMeal":10,"predatorReproEnergy":60,)"
    R"("predatorMaxPopulation":6,"predatorMinPopulation":2,"predatorInheritance":true})";

// ---- label_mask: the dead-sensor skip (turbo-speed-1) under own-frame labels ----
// Under labelFrame 1 each of the six projected inputs reads BOTH world
// components of its vector (OceanWorld::computeSensors, ownLabels): the skip,
// which computes only the sensors a net reads, must never drop the component
// whose own output is not read. Capture on computes every sensor (the
// definition); capture off is the skip.
inline constexpr int kOwnFrameLabels[] = {NEAREST_FOOD_DX, NEAREST_FOOD_DY, AVG_NEIGHBOR_DX, AVG_NEIGHBOR_DY,
                                          AVG_NEIGHBOR_HEADING_X, AVG_NEIGHBOR_HEADING_Y};   // three x / y pairs

// a JSON object with more keys: `{...}` -> `{...,extra}`
inline std::string withKeys(const char* json, const char* extra) {
    std::string s(json);
    s.insert(s.size() - 1, std::string(",") + extra);
    return s;
}

// The fish in w reading one component of a pair (food, offset, heading) and
// not the other: the case a wrongly-masked component would break.
inline void countSingleReaders(const OceanWorld& w, long out[3]) {
    for (const Fish& f : w.creatures) {
        const ocean::SenseMask m = ocean::sensesRead(f.nnet);
        for (int p = 0; p < 3; ++p)
            out[p] += ((m >> kOwnFrameLabels[2 * p]) & 1) != ((m >> kOwnFrameLabels[2 * p + 1]) & 1);
    }
}

inline void testLabelMask() {
    Test t("label_mask");
    using sense::sameBits;
    long compared = 0, longSteps = 0, longBirths = 0;
    // Single-sensor worlds: sense_dce's rich worlds (walls 40 steps from founders
    // old enough to pair; the others 10) with labelFrame 1 and steerFrame 1, every
    // fish reading ONE projected input (speed::readOnly).
    for (const speed::RichCfg& rc : speed::kRich) {
        const bool longRun = (&rc == &speed::kRich[0]);
        const int steps = longRun ? 40 : 10;
        const std::string json = withKeys(rc.json, R"("labelFrame":1,"steerFrame":1)");
        OceanWorld base;
        std::string err;
        if (!t.expect(ofp::initWorld(base, 78, 1920, 1080, 240.0f, 300, json.c_str(), err), "%s: %s", rc.name, err.c_str()))
            continue;
        for (int k = 0; k < (longRun ? 400 : 200); ++k) base.update(0.016f);
        const RandomGen r0 = rng;
        for (int s : kOwnFrameLabels) {
            OwnRng off{base, r0};
            for (Fish& f : off.w.creatures) speed::readOnly(f, s);
            OwnRng on = off;
            off.w.cfg.captureActivations = false;   // the skip: only s is computed
            on.w.cfg.captureActivations = true;     // every sensor
            for (int step = 0; step < steps; ++step) {
                off.step();
                on.step();
                const ofp::Fingerprint a = off.fp(), b = on.fp();   // each with its own stream
                bool same = sameEngine(off.r, on.r) && sameDynamics(a, b) && off.w.creatures.size() == on.w.creatures.size();
                for (std::size_t i = 0; same && i < off.w.creatures.size(); ++i)
                    same = sameBits(off.w.creatures[i].nnet.neurons[0].output, on.w.creatures[i].nnet.neurons[0].output);
                if (!t.expect(same, "%s: labelFrame 1, reading only %s, step %d: capture off (the skip) and on differ "
                                    "(fish %016llx vs %016llx)",
                              rc.name, ocean::kSensorNames[s], step + 1, (unsigned long long)a.fish, (unsigned long long)b.fish))
                    break;
                ++compared;
                if (step == 0 && !speed::mayBeAllZero(s, rc)) {   // teeth: s read non-zero for some fish
                    long nonZero = 0;
                    for (const Fish& f : on.w.creatures) nonZero += !sameBits(f.lastSensors[s], 0.0f);
                    t.expect(nonZero > 0, "%s: %s read 0 for every fish: this scene cannot tell a skip", rc.name,
                             ocean::kSensorNames[s]);
                }
            }
        }
    }
    // Long runs: the A1 arm (labelFrame 1, steerFrame 1, the eye off) in protocol
    // v2's L12 ecology, and a toroidal world with topological neighbours. Every
    // founder gets one wire from a projected input to STEER_X or STEER_Y (its
    // partner not added; the rest of its genome kept); births, mutation and the
    // population floor run as usual.
    struct Long { const char* name; std::string json; int steps; };
    const Long longs[] = {
        {"A1 in L12", withKeys(kExpL12, R"("labelFrame":1,"steerFrame":1)"), 2000},
        {"toroidal topo", withKeys(speed::kRich[2].json, R"("labelFrame":1,"steerFrame":1)"), 600},
    };
    std::string cover;
    for (const Long& lc : longs) {
        OceanWorld base;
        std::string err;
        if (!t.expect(ofp::initWorld(base, 2027, 1920, 1080, 240.0f, 300, lc.json.c_str(), err), "%s: %s", lc.name, err.c_str()))
            continue;
        int i = 0;
        for (Fish& f : base.creatures) {
            Gene g;
            g.sourceType = SOURCE_SENSOR;
            g.sourceNum = (uint16_t)kOwnFrameLabels[i % 6];
            g.sinkType = SINK_ACTION;
            g.sinkNum = ((i / 6) % 2) ? STEER_Y : STEER_X;
            g.weight = (int16_t)((i % 3 == 0 ? -1 : 1) * (6000 + 997 * (i % 7)));
            f.genome.push_back(g);
            buildNeuralNet(f.genome, f.nnet);
            ++i;
        }
        const RandomGen r0 = rng;
        OwnRng off{base, r0}, on{base, r0};
        off.w.cfg.captureActivations = false;
        on.w.cfg.captureActivations = true;
        const long long births0 = on.w.totalBirths;
        long single[3] = {0, 0, 0};
        int step = 0;
        for (; step < lc.steps; ++step) {
            countSingleReaders(off.w, single);
            off.step();
            on.step();
            const ofp::Fingerprint a = off.fp(), b = on.fp();
            const bool same = sameEngine(off.r, on.r) && sameDynamics(a, b);
            if (!t.expect(same, "%s: step %d: capture off (the skip) and on differ (fish %016llx vs %016llx, rng %016llx vs %016llx)",
                          lc.name, step + 1, (unsigned long long)a.fish, (unsigned long long)b.fish, (unsigned long long)a.rng,
                          (unsigned long long)b.rng))
                break;
            ++longSteps;
        }
        long atEnd[3] = {0, 0, 0};
        countSingleReaders(off.w, atEnd);
        const long long births = on.w.totalBirths - births0;
        longBirths += births;
        t.expect(births > 0, "%s: no births in %d steps: inherited and mutated nets were not exercised", lc.name, step);
        for (int p = 0; p < 3; ++p)
            t.expect(single[p] > 0 && atEnd[p] > 0, "%s: pair %d: %ld fish-steps read one component only (%ld at the end): "
                     "no coverage", lc.name, p, single[p], atEnd[p]);
        char buf[200];
        std::snprintf(buf, sizeof buf, " %s: %d steps, %lld births, %zu fish at the end, one-component readers "
                      "food %ld / offset %ld / heading %ld fish-steps (%ld / %ld / %ld at the end);", lc.name, step, births,
                      off.w.creatures.size(), single[0], single[1], single[2], atEnd[0], atEnd[1], atEnd[2]);
        cover += buf;
    }
    t.note("labelFrame 1: %ld single-sensor worlds x steps (the six projected inputs, %d configs): capture off == on",
           compared, (int)(sizeof speed::kRich / sizeof speed::kRich[0]));
    t.note("long runs, capture off == on every step (dynamics, each world's own rng stream), %ld steps, %ld births:%s", longSteps,
           longBirths, cover.c_str());
}

#ifdef EVO_OCEAN_EYE

struct ExpArm { const char* name; std::vector<std::pair<std::string, int>> keys; };
inline std::vector<ExpArm> expArms() {
    std::vector<ExpArm> a = {
        {"C1", {{"eye", 1}, {"eyeOnly", 1}, {"steerFrame", 1}}}, {"D1", {{"eye", 0}, {"eyeOnly", 1}, {"steerFrame", 1}}},
        {"A0", {{"eye", 0}, {"eyeOnly", 0}, {"steerFrame", 0}}}, {"C0", {{"eye", 1}, {"eyeOnly", 1}, {"steerFrame", 0}}},
        {"D0", {{"eye", 0}, {"eyeOnly", 1}, {"steerFrame", 0}}},
        {"C1nf", {{"eye", 1}, {"eyeOnly", 1}, {"steerFrame", 1}, {"eyeCode", 8}}},
        {"C1nd", {{"eye", 1}, {"eyeOnly", 1}, {"steerFrame", 1}, {"eyeCode", 16}}},
        {"C1po", {{"eye", 1}, {"eyeOnly", 1}, {"steerFrame", 1}, {"eyeCode", 24}}}};
    if (alx::hasLabelFrame()) a.push_back({"A1", {{"eye", 0}, {"eyeOnly", 0}, {"steerFrame", 1}, {"labelFrame", 1}}});
    return a;
}

inline bool expWorld(Test& t, OceanWorld& w, unsigned seed, int W, int H, int pop, const ExpArm* arm) {
    std::string err;
    if (!t.expect(ofp::initWorld(w, seed, W, H, 240.0f, pop, kExpL12, err), "init: %s", err.c_str())) return false;
    if (arm)
        for (const auto& k : arm->keys)
            if (!t.expect(alx::setArmKey(w.ocfg, k.first, k.second, err), "%s: %s", arm->name, err.c_str())) return false;
    return true;
}

inline void testExpArmsShareInit() {
    Test t("exp_arms_init");
    const auto arms = expArms();
    OceanWorld ref;
    if (!expWorld(t, ref, 4242, 800, 600, 120, nullptr)) return;
    const ofp::Fingerprint f0 = ofp::fingerprint(ref);
    for (const ExpArm& a : arms) {
        OceanWorld w;
        if (!expWorld(t, w, 4242, 800, 600, 120, &a)) continue;
        const ofp::Fingerprint f = ofp::fingerprint(w);
        t.expect(f.ctr == f0.ctr && f.fish == f0.fish && f.food == f0.food && f.pred == f0.pred && f.sig == f0.sig &&
                     f.cur == f0.cur && f.geo == f0.geo && f.rng == f0.rng,
                 "%s: a non-config section differs from the common initialization", a.name);
        t.expect(std::string(a.name) == "A0" || f.cfg != f0.cfg, "%s: the arm left the config hash unchanged", a.name);
        std::string e;
        OceanConfig oc = w.ocfg;
        t.expect(!alx::setArmKey(oc, "eye", 2, e) && !e.empty(), "%s: eye=2 accepted", a.name);
    }
    std::string e;
    OceanConfig oc;
    t.expect(!alx::setArmKey(oc, "speed", 1, e), "an unknown arm key was accepted");
    t.note("%zu arms (%s): the 8 non-config sections equal the common initialization's", arms.size(),
           alx::hasLabelFrame() ? "A1 included" : "no labelFrame in this engine");
}

inline void testExpObserversNeutral() {
    Test t("exp_observers");
    const ExpArm c1 = expArms()[0];
    OceanWorld a, b;
    if (!expWorld(t, a, 77, 900, 600, 150, &c1) || !expWorld(t, b, 77, 900, 600, 150, &c1)) return;
    alx::FpObserver fa, fb;
    fa.dense = fb.dense = true;
    alx::StepDiag d;
    alx::EncounterDiag enc;
    d.begin(a);
    fa.observe(a, 0, false);
    fb.observe(b, 0, false);
    long long pairSteps = 0;
    for (long s = 1; s <= 300; ++s) {
        // a's instruments run between its updates; b runs bare. One rng: a's
        // update, then b's, each from the rng its own state needs.
        const RandomGen ra = rng;
        d.before(a, 0.016f);
        enc.before(a);
        a.update(0.016f);
        d.after(a, s);
        enc.after(a, s);
        fa.observe(a, s, false);
        if (s % 100 == 0) { pairSteps += enc.pairSteps; enc.resetInterval(); }
        const RandomGen afterA = rng;
        rng = ra;   // b replays the same draws
        b.update(0.016f);
        if (s == 150) {   // a transient change, put back before the next update
            const float keep = b.creatures[0].foodReserves;
            b.creatures[0].foodReserves = std::nextafter(keep, 1e30f);
            fb.observe(b, s, false);
            b.creatures[0].foodReserves = keep;
        } else {
            fb.observe(b, s, false);
        }
        t.expect(afterA.state() == rng.state(), "step %ld: the instrumented step used the rng differently", s);
        rng = afterA;
    }
    t.expect(fa.last == fb.last, "the instrumented run ended in a different state (or rng)");
    t.expect(fa.chain.value() != fb.chain.value(), "the dense chain missed a transient change between printed steps");
    t.expect(d.identityBad == 0 && d.expiryBad == 0, "food identity broken on %lld steps, expiry replay on %lld",
             d.identityBad, d.expiryBad);
    t.expect(d.auc > 0 && d.minPost <= d.n0 && d.minPre <= d.minPost, "diagnostics inconsistent: auc %lld min %lld pre %lld",
             d.auc, d.minPost, d.minPre);
    t.expect(a.totalFoodExpired > 0, "no food expired in 300 steps (the identity was not exercised)");
    // the spawn cap binding: 3 attempts a step, targetFood 20 (cap 40), foodLife 1 s
    OceanWorld c;
    std::string err;
    if (t.expect(ofp::initWorld(c, 78, 600, 400, 240.0f, 60,
                                R"({"foodSpawnBase":3,"foodSpawnAmp":0,"targetFood":20,"foodLife":1,"minPopulation":0})", err),
                 "init: %s", err.c_str())) {
        alx::StepDiag dc;
        dc.begin(c);
        long long attempts = 0;
        for (long s = 1; s <= 400; ++s) { dc.before(c, 0.016f); c.update(0.016f); dc.after(c, s); attempts += 3; }
        t.expect(dc.identityBad == 0 && dc.expiryBad == 0, "capped world: identity %lld, expiry %lld", dc.identityBad, dc.expiryBad);
        t.expect(dc.arrivals < attempts && c.totalFoodExpired > 0, "the cap never bound (%lld of %lld) or nothing expired",
                 dc.arrivals, attempts);
        t.note("capped world: %lld arrivals of %lld attempts, %lld expired, %lld eaten: the identity held every step",
               dc.arrivals, attempts, c.totalFoodExpired, c.totalFoodEaten);
    }
    t.note("300 steps, every instrument on: same end state and rng; %lld pair-steps within the radius; min pop %lld",
           pairSteps, d.minPost);
}

inline void testExpBranches() {
    Test t("exp_branches");
    const ExpArm c1 = expArms()[0];
    OceanWorld w;
    if (!expWorld(t, w, 91, 900, 600, 150, &c1)) return;
    for (int s = 0; s < 200; ++s) w.update(0.016f);
    std::vector<alx::BranchSpec> specs;
    std::string err;
    t.expect(alx::parseBranchSpecs("sham:;blind:eye=0;foodcloak:eyeCode=16;fishcloak:eyeCode=8;frameswap:steerFrame=0", specs, err) &&
                 specs.size() == 5 && specs[1].changes.size() == 1 && specs[0].changes.empty(),
             "spec parse: %s", err.c_str());
    std::vector<alx::BranchSpec> bad;
    t.expect(!alx::parseBranchSpecs("a:eye=1;a:", bad, err) && !alx::parseBranchSpecs("x:eye", bad, err) &&
                 !alx::parseBranchSpecs("x:eye=1z", bad, err) && !alx::parseBranchSpecs("", bad, err),
             "a bad spec was accepted");
    const ofp::Fingerprint before = ofp::fingerprint(w);
    const RandomGen parentRng = rng;
    std::vector<alx::BranchResult> fwd(specs.size()), rev(specs.size());
    for (std::size_t k = 0; k < specs.size(); ++k)
        t.expect(alx::runContinuation(w, parentRng, specs[k], 200, 120, 40, 50, true, 0.016f, fwd[k], err), "%s", err.c_str());
    t.expect(ofp::fingerprint(w) == before, "the parent (world or rng) changed");
    for (std::size_t k = specs.size(); k-- > 0;)
        t.expect(alx::runContinuation(w, parentRng, specs[k], 200, 120, 40, 50, true, 0.016f, rev[k], err), "%s", err.c_str());
    long differ = 0;
    for (std::size_t k = 0; k < specs.size(); ++k) {
        t.expect(fwd[k].chain.value() == rev[k].chain.value() && fwd[k].eaten == rev[k].eaten && fwd[k].births == rev[k].births,
                 "%s: the result depends on the order", specs[k].name.c_str());
        t.expect(fwd[k].identityBad == 0 && fwd[k].expiryBad == 0 && fwd[k].nonFinite == 0, "%s: food identity / finite",
                 specs[k].name.c_str());
        if (k > 0) differ += fwd[k].chain.value() != fwd[0].chain.value();
    }
    t.expect(differ == (long)specs.size() - 1, "only %ld of the %zu interventions changed the run", differ, specs.size() - 1);
    long compared = 0, same = 0;   // the uninterrupted run passes the sham's states
    std::size_t next = 1;
    for (long s = 1; s <= 120; ++s) {
        w.update(0.016f);
        if (next < fwd[0].fps.size() && fwd[0].fps[next].first == s) {
            ++compared;
            same += ofp::fingerprint(w) == fwd[0].fps[next].second;
            ++next;
        }
    }
    t.expect(compared == 3 && same == compared, "sham vs the uninterrupted run: %ld of %ld fingerprints equal", same, compared);
    t.note("5 continuations x 120 steps from step 200: sham == uninterrupted at %ld checkpoints, order-independent, "
           "parent kept; sham ate %lld, blind %lld",
           compared, fwd[0].eaten, fwd[1].eaten);
}
#endif

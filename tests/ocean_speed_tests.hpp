#pragma once
// ocean_speed_tests.hpp — checks that pin what the exact Turbo speed-ups
// (turbo-speed-1) must not move, included by tests/ocean_tests.cpp after
// ocean_sense_tests.hpp (namespace ot: Test, initQuiet, sameDynamics,
// sense::sameBits are those files').
//
//   sense_mask      ocean::sensesRead (the sensors a net reads, which
//                   computeSensors' dead-sensor skip computes): one bit per
//                   sensor source of ANY flat connection — a zero weight, a
//                   hidden-neuron sink — and none for a hidden-neuron source;
//                   every source index the packing allows; the last sensor's
//                   bit (63 in the eye build); built nets == their genes;
//                   kAllSenses has NUM_SENSES bits
//   sense_dce       capture off vs on, one sensor at a time (what a skip of
//                   the sensors a net does not read must keep): every fish
//                   rewired to read only sensor s (into hidden neuron 0 and
//                   STEER_X; hidden 0 also votes to fight, the undriven hidden
//                   1 to pair, so contacts fight or pair by what s read), in a
//                   world where every sensor reads non-zero somewhere
//                   (predators, a current or flow, pheromone, food,
//                   neighbours); stepped with capture off and on: each step
//                   the same neuron outputs bit for bit, the same dynamics and
//                   the same rng stream (each world's OWN stream: fingerprinted
//                   with it installed, and the saved streams compared), for
//                   every s, in each topology (glass walls — 40 steps from
//                   founders old enough to pair, contacts and births required;
//                   bounded + E1 flow; toroidal + topological neighbours — 2
//                   steps) and (eye build) eye nearest / summed / eye-only;
//                   and the own-state inputs equal kernel::writeOwnStateSensors
//                   bit for bit (the nearest's three are held to
//                   kernel::writeNearestSensors by sense_edges / sense_ref)
//   capture_toggle  captureActivations on -> off -> on -> off: the run is the
//                   always-on and the always-off run every step (dynamics and
//                   each world's own rng stream), eye-only mode included; while
//                   off, no fish's lastSensors / lastActions change; back on,
//                   they are the always-on run's
//   food_scan       OceanWorld::foodWithin / foodWithinWrapped (the scans'
//                   item lists) against the scalar loops that define them,
//                   record by record, bit for bit: random worlds (narrow tori
//                   where one run straddles the half-width and a cell is in two
//                   images' runs, partial last cells), items on seams, at -0,
//                   exactly R away, NaN depths, duplicates; viewers on the
//                   seams and at +0
// The engine's private food scans and their list, read without accessors (the
// fingerprint's explicit-instantiation peek, tools/ocean_fingerprint.hpp).
namespace ofp::peek {
struct OwFoodWithin { friend constexpr auto member(OwFoodWithin) noexcept; };
template struct Expose<OwFoodWithin, &OceanWorld::foodWithin>;
struct OwFoodWithinWrapped { friend constexpr auto member(OwFoodWithinWrapped) noexcept; };
template struct Expose<OwFoodWithinWrapped, &OceanWorld::foodWithinWrapped>;
struct OwFoodSeen { friend constexpr auto member(OwFoodSeen) noexcept; };
template struct Expose<OwFoodSeen, &OceanWorld::foodSeen_>;
}  // namespace ofp::peek

namespace ot {
namespace speed {

// The three topologies (glass walls; bounded + the E1 flow; toroidal +
// topological neighbours), each with predators, a current or flow and food
// patches, so every sensor has something to read. Eye configs add the eye.
struct RichCfg { const char* name; const char* json; bool eyeOff; bool eyeOnly; };
inline constexpr RichCfg kRich[] = {
    {"walls", R"({"walls":true,"currentStrength":60,"predatorCount":8,"foodPatches":4})", true, false},
    {"bounded e1", R"({"waveSpeed":6,"deepCurrent":true,"currentStrength":40,"foodDrift":true,"predatorCount":8})", true, false},
    {"toroidal topo", R"({"toroidal":true,"currentStrength":60,"predatorCount":8,"maxNeighbors":7,"foodPatches":4})", true, false},
#ifdef EVO_OCEAN_EYE
    {"walls eye", R"({"walls":true,"currentStrength":60,"predatorCount":8,"eye":1})", false, false},
    {"toroidal eye summed", R"({"toroidal":true,"currentStrength":60,"predatorCount":8,"maxNeighbors":7,"eye":1,"eyeCode":4})", false, false},
    {"bounded eye-only", R"({"waveSpeed":6,"deepCurrent":true,"currentStrength":40,"predatorCount":8,"eye":1,"eyeOnly":1})", false, true},
#endif
};

// May sensor s read 0 for every fish in this config (and so give the test no teeth)?
inline bool mayBeAllZero(int s, const RichCfg& rc) {
#ifdef EVO_OCEAN_EYE
    if (ocean::isEyeSense(s)) return rc.eyeOff;
    if (rc.eyeOnly && ocean::isLabeledSense(s)) return true;   // eye-only: the labeled senses read 0
#else
    (void)s; (void)rc;
#endif
    return false;
}

// Fish f reads sensor s only: s -> hidden neuron 0 and s -> STEER_X, weight 1
// (its genome kept: genetic similarity still varies). Two social wires make
// the contact vote depend on what s read: hidden 0 (tanh of s, carried into
// the vote as recurrent state) -> INTERACT_FIGHT, and the undriven hidden 1
// (a constant 0.5) -> INTERACT_REPRODUCE, so pairs whose s read high fight and
// the rest pair (kernel::interactionVote). Neither adds a sensor source.
inline void readOnly(Fish& f, int s) {
    Gene toHidden, toSteer, fight, pair;
    toHidden.sourceType = SOURCE_SENSOR; toHidden.sourceNum = (uint16_t)s;
    toHidden.sinkType = SINK_NEURON;     toHidden.sinkNum = 0;     toHidden.weight = 8192;
    toSteer = toHidden;
    toSteer.sinkType = SINK_ACTION;      toSteer.sinkNum = STEER_X;
    fight.sourceType = SOURCE_NEURON;    fight.sourceNum = 0;
    fight.sinkType = SINK_ACTION;        fight.sinkNum = INTERACT_FIGHT;    fight.weight = 8192;
    pair = fight;
    pair.sourceNum = 1;                  pair.sinkNum = INTERACT_REPRODUCE;
    buildNeuralNet(Genome{toHidden, toSteer, fight, pair}, f.nnet);
    // The net's gene-type masks describe the genome the fish KEEPS (the masked
    // nearest-neighbour similarity reads them), not the four wires above.
    genomeTypeMasks(f.genome, f.nnet.srcTypeBits, f.nnet.sinkTypeBits);
}

inline bool sameArrays(const Fish& a, const Fish& b) {
    return std::memcmp(a.lastSensors, b.lastSensors, sizeof a.lastSensors) == 0 &&
           std::memcmp(a.lastActions, b.lastActions, sizeof a.lastActions) == 0;
}

}  // namespace speed

void testSenseMask() {
    Test t("sense_mask");
    using ocean::senseBit;
    auto conn = [](int src, int sink, int16_t w) {
        return NeuralNet::FlatConn{(uint16_t)(src | (sink << NeuralNet::FlatConn::SRC_BITS)), w};
    };
    NeuralNet nn;
    t.expect(ocean::sensesRead(nn) == 0, "an empty net reads %llx", (unsigned long long)ocean::sensesRead(nn));
    nn.flat = {conn(AGE, STEER_X, 0)};   // a zero weight still reads its sensor
    t.expect(ocean::sensesRead(nn) == senseBit(AGE), "zero-weight wire: %llx", (unsigned long long)ocean::sensesRead(nn));
    nn.flat = {conn(PREDATOR_PROX, NUM_ACTIONS + 3, 100)};   // a hidden-neuron sink reads it too
    t.expect(ocean::sensesRead(nn) == senseBit(PREDATOR_PROX), "hidden sink: %llx", (unsigned long long)ocean::sensesRead(nn));
    nn.flat = {conn(NUM_SENSES + 0, STEER_X, 100), conn(NUM_SENSES + MAX_INTERNAL_NEURONS - 1, NUM_ACTIONS, -5)};
    t.expect(ocean::sensesRead(nn) == 0, "hidden sources read no sensor: %llx", (unsigned long long)ocean::sensesRead(nn));
    nn.flat = {conn(0, 0, 1), conn(NUM_SENSES - 1, NUM_ACTIONS + 1, 1), conn(NUM_SENSES + 2, 1, 1), conn(RANDOM_SENSOR, 2, 1)};
    t.expect(ocean::sensesRead(nn) == (senseBit(0) | senseBit(NUM_SENSES - 1) | senseBit(RANDOM_SENSOR)),
             "first / last / random: %llx", (unsigned long long)ocean::sensesRead(nn));
    // every source index the packing allows, sensor or not (eye build: 0..127, the hidden ones 64..75)
    for (int src = 0; src < (1 << NeuralNet::FlatConn::SRC_BITS); ++src) {
        nn.flat = {conn(src, 0, 1)};
        const ocean::SenseMask want = (src < NUM_SENSES) ? senseBit(src) : 0;
        t.expect(ocean::sensesRead(nn) == want, "source %d: %llx, want %llx", src, (unsigned long long)ocean::sensesRead(nn),
                 (unsigned long long)want);
    }
    int bits = 0;
    for (int s = 0; s < 64; ++s) bits += (int)((ocean::kAllSenses >> s) & 1);
    t.expect(bits == NUM_SENSES && (ocean::kAllSenses & 1), "kAllSenses has %d bits, NUM_SENSES %d", bits, (int)NUM_SENSES);
    // a built net: the mask is exactly its sensor-sourced genes' sensors (zero weights included)
    std::uint32_t r = 0x9e3779b9u;
    for (int rep = 0; rep < 200; ++rep) {
        Genome g;
        const int n = 1 + (int)(r % 60);
        ocean::SenseMask want = 0;
        for (int k = 0; k < n; ++k) {
            r ^= r << 13; r ^= r >> 17; r ^= r << 5;
            Gene x;
            x.sourceType = r & 1; x.sourceNum = (r >> 1) & 127; x.sinkType = (r >> 8) & 1; x.sinkNum = (r >> 9) & 127;
            x.weight = (int16_t)((r >> 16) % 3 == 0 ? 0 : (int)(r >> 16) - 32768);
            g.push_back(x);
            if (x.sourceType == SOURCE_SENSOR) want |= senseBit(x.sourceNum % NUM_SENSES);
        }
        NeuralNet b;
        buildNeuralNet(g, b);
        t.expect(ocean::sensesRead(b) == want, "genome %d: %llx, want %llx", rep, (unsigned long long)ocean::sensesRead(b),
                 (unsigned long long)want);
    }
}

// One world with its own rng stream (the engine's rng is global): step() swaps
// the stream in, steps, and keeps where it got to. fp() is the world's
// fingerprint with ITS stream in the global engine (the fingerprint's rng
// section hashes the global rng, so a world fingerprinted after another one
// stepped would otherwise show that world's stream); the global rng is put
// back after. Comparisons also hold the saved streams to each other directly
// (sameEngine: three draws and the whole serialised state).
struct OwnRng {
    OceanWorld w;
    RandomGen r;
    void step() { rng = r; w.update(0.016f); r = rng; }
    ofp::Fingerprint fp() const {
        const RandomGen keep = rng;
        rng = r;
        const ofp::Fingerprint f = ofp::fingerprint(w, false);
        rng = keep;
        return f;
    }
};

void testSenseDce() {
    Test t("sense_dce");
    using sense::sameBits;
    long compared = 0, ownChecked = 0;
    long long longContacts = 0, longBirths = 0;   // the 40-step worlds' social coverage
    for (const speed::RichCfg& rc : speed::kRich) {
        // The first config runs each single-sensor world 40 steps (contacts, fights,
        // pairings and births happen, decided by what s read), from founders aged
        // 6.4 s (pairing needs age > 5); the others 2 steps after a 3.2 s warm-up.
        const bool longRun = (&rc == &speed::kRich[0]);
        const int steps = longRun ? 40 : 2;
        OceanWorld base;
        std::string err;
        if (!t.expect(ofp::initWorld(base, 77, 1920, 1080, 240.0f, 300, rc.json, err), "%s: %s", rc.name, err.c_str())) continue;
        for (int k = 0; k < (longRun ? 400 : 200); ++k) base.update(0.016f);   // pheromone laid, fish spread, predators about
        const RandomGen r0 = rng;

        // The own-state inputs computeSensors writes itself == kernel::writeOwnStateSensors
        // of the fish as it sensed (its own state is untouched until its own step).
        {
            OwnRng on{base, r0};
            on.w.cfg.captureActivations = true;
            const std::vector<Fish> before = on.w.creatures;
            on.step();
            std::size_t j = 0;
            for (const Fish& f : on.w.creatures) {
                while (j < before.size() && before[j].id != f.id) ++j;   // survivors keep their order
                if (j == before.size()) break;                           // newborns from here on
                float want[NUM_SENSES] = {};
                kernel::writeOwnStateSensors(before[j], on.w.cfg, want);
                for (int s : {OWN_SPEED, AGE, FOOD_RESERVES, OSCILLATOR, RESPONSIVENESS})
                    t.expect(sameBits(f.lastSensors[s], want[s]), "%s: fish %llu %s = %.9g, kernel %.9g", rc.name,
                             (unsigned long long)f.id, ocean::kSensorNames[s], f.lastSensors[s], want[s]);
                ++ownChecked;
            }
        }

        std::string zero;
        for (int s = 0; s < NUM_SENSES; ++s) {
            OwnRng off{base, r0};
            for (Fish& f : off.w.creatures) speed::readOnly(f, s);
            OwnRng on = off;
            off.w.cfg.captureActivations = false;   // the skip: only sensor s is computed
            on.w.cfg.captureActivations = true;     // every sensor
            const long long births0 = on.w.totalBirths;
            for (int step = 0; step < steps; ++step) {
                off.step();
                on.step();
                const ofp::Fingerprint a = off.fp(), b = on.fp();   // each with its own stream
                bool same = sameEngine(off.r, on.r) && sameDynamics(a, b) && off.w.creatures.size() == on.w.creatures.size();
                for (std::size_t i = 0; same && i < off.w.creatures.size(); ++i)
                    same = sameBits(off.w.creatures[i].nnet.neurons[0].output, on.w.creatures[i].nnet.neurons[0].output);
                t.expect(same, "%s: reading only %s, step %d: capture off (the skip) and on differ (fish %016llx vs %016llx, "
                               "rng %016llx vs %016llx)",
                         rc.name, ocean::kSensorNames[s], step + 1, (unsigned long long)a.fish, (unsigned long long)b.fish,
                         (unsigned long long)a.rng, (unsigned long long)b.rng);
                ++compared;
                if (longRun)   // contacts this step: an interaction (any outcome) restarts both timers at the cooldown
                    for (const Fish& f : on.w.creatures) longContacts += (f.interactTimer == on.w.cfg.interactCooldown);
                if (step == 0) {   // teeth: the sensor read non-zero for some fish
                    long nonZero = 0;
                    for (const Fish& f : on.w.creatures) nonZero += !sameBits(f.lastSensors[s], 0.0f);
                    if (nonZero == 0) zero += std::string(" ") + ocean::kSensorNames[s];
                    if (nonZero == 0 && !speed::mayBeAllZero(s, rc))
                        t.expect(false, "%s: %s read 0 for every fish: this scene cannot tell a skip", rc.name,
                                 ocean::kSensorNames[s]);
                }
            }
            if (longRun) longBirths += on.w.totalBirths - births0;
        }
        if (!zero.empty()) t.note("%s: all-zero (expected):%s", rc.name, zero.c_str());
    }
    t.expect(longContacts > 0 && longBirths > 0, "the 40-step single-sensor worlds had %lld contacts and %lld births: the "
             "social paths were not exercised", longContacts, longBirths);
    t.note("%ld single-sensor worlds x steps: capture off == capture on (each world's own rng stream); %ld fish's own-state "
           "inputs == the kernel's; the 40-step worlds: %lld fish-contacts, %lld births", compared, ownChecked, longContacts,
           longBirths);
}

// The gene-type masks (genome.hpp) every fish's net carries are its genome's:
// on a stepped world (births, deaths, the loaded founders), on the readOnly
// fixture (a net wired from other genes, its masks restored), and the
// fingerprint marks a fish whose masks are not (tools/ocean_fingerprint.hpp).
void testTypeMasks() {
    Test t("type_masks");
    OceanWorld w;
    std::string err;
    if (t.expect(ofp::initWorld(w, 4242, 1920, 1080, 240.0f, 300, "{}", err), "init: %s", err.c_str())) {
        for (int i = 0; i < 300; ++i) w.update(0.016f);
        long bad = 0, n = 0;
        for (const Fish& f : w.creatures) { ++n; if (!typeMasksMatch(f.genome, f.nnet)) ++bad; }
        t.expect(bad == 0 && n > 0, "%ld of %ld fish carry masks that are not their genome's", bad, n);
        for (Fish& f : w.creatures) speed::readOnly(f, (int)AGE);
        bad = 0;
        for (const Fish& f : w.creatures) if (!typeMasksMatch(f.genome, f.nnet)) ++bad;
        t.expect(bad == 0, "%ld readOnly fish lost their genome's masks", bad);
        // A broken mask changes the fingerprint (the marker), nothing else touched.
        const ofp::Fingerprint before = ofp::fingerprint(w, false);
        Fish& f0 = w.creatures[0];
        const uint64_t keep = f0.nnet.srcTypeBits[0];
        f0.nnet.srcTypeBits[0] ^= 1ull;
        const ofp::Fingerprint broken = ofp::fingerprint(w, false);
        f0.nnet.srcTypeBits[0] = keep;
        const ofp::Fingerprint after = ofp::fingerprint(w, false);
        t.expect(!(before == broken) && before == after, "the fingerprint must mark a foreign mask and only that");
    }
}

void testCaptureToggle() {
    Test t("capture_toggle");
    long offChecked = 0;
    for (const speed::RichCfg& rc : speed::kRich) {   // eye-only included
        OceanWorld w0;
        std::string err;
        if (!t.expect(ofp::initWorld(w0, 91, 1920, 1080, 240.0f, 300, rc.json, err), "%s: %s", rc.name, err.c_str())) continue;
        const RandomGen r0 = rng;
        OwnRng on{w0, r0}, toggled{w0, r0}, off{w0, r0};
        on.w.cfg.captureActivations = true;
        off.w.cfg.captureActivations = false;
        bool firstOn = true;
        for (int step = 0; step < 420; ++step) {
            const bool cap = (step < 100) || (step >= 250 && step < 350);   // on, off, on, off
            const bool wasCap = toggled.w.cfg.captureActivations;
            toggled.w.cfg.captureActivations = cap;
            const std::vector<Fish> before = toggled.w.creatures;
            on.step();
            toggled.step();
            off.step();
            const ofp::Fingerprint a = on.fp(), b = toggled.fp(), c = off.fp();   // each with its own stream
            if (!t.expect(sameEngine(on.r, toggled.r) && sameEngine(on.r, off.r) && sameDynamics(a, b) && sameDynamics(a, c),
                          "%s step %d: always-on / toggled / always-off differ (rng %016llx / %016llx / %016llx)", rc.name,
                          step + 1, (unsigned long long)a.rng, (unsigned long long)b.rng, (unsigned long long)c.rng))
                break;
            if (!cap) {   // off: no fish's captured arrays change (survivors, by id; newborns keep theirs)
                std::size_t j = 0;
                for (const Fish& f : toggled.w.creatures) {
                    while (j < before.size() && before[j].id != f.id) ++j;
                    if (j == before.size()) break;
                    t.expect(speed::sameArrays(f, before[j]), "%s step %d: fish %llu's captured arrays changed with capture off",
                             rc.name, step + 1, (unsigned long long)f.id);
                    ++offChecked;
                }
            } else if (!wasCap && !firstOn) {   // back on: the always-on run's arrays
                bool same = on.w.creatures.size() == toggled.w.creatures.size();
                for (std::size_t i = 0; same && i < on.w.creatures.size(); ++i)
                    same = speed::sameArrays(on.w.creatures[i], toggled.w.creatures[i]);
                t.expect(same, "%s step %d: back on, the captured arrays are not the always-on run's", rc.name, step + 1);
            }
            if (cap) firstOn = false;
        }
    }
    t.note("%ld fish-steps with capture off kept their captured arrays", offChecked);
}

void testFoodScan() {
    using sense::sameBits;
    Test t("food_scan");
    std::uint32_t s = 0x6a09e667u;
    auto next = [&]() { s ^= s << 13; s ^= s >> 17; s ^= s << 5; return s; };
    auto pick = [&](int n) { return (int)(next() % (std::uint32_t)n); };
    auto unit = [&]() { return (float)(next() >> 8) * (1.0f / 16777216.0f); };
    struct G { int W, H; float R; };
    const G gs[] = {{1920, 1080, 100.0f}, {1950, 1030, 100.0f}, {250, 250, 100.0f}, {250, 250, 122.0f},
                    {100, 100, 40.0f},    {640, 480, 37.5f},    {2560, 1440, 80.0f}};
    long scenes = 0, records = 0, vecRuns = 0, wrapSelects = 0, negZero = 0;
    for (const G& g : gs) {
        const float W = (float)g.W, H = (float)g.H, R = g.R;
        for (int rep = 0; rep < 60; ++rep) {
            OceanConfig oc;
            OceanWorld w;
            initQuiet(w, 4000 + rep, 240.0f, oc, false, true);
            w.width = g.W;
            w.height = g.H;
            w.cfg.perceptionRadius = R;
            OceanFoodGrid& grid = ofp::field<ofp::peek::OwFoodGrid>(w);
            grid.init(g.W, g.H, R);
            // a viewer: anywhere, on a seam, at ±0, at W / H minus an ulp
            Fish v;
            auto coordV = [&](float span) -> float {
                switch (pick(6)) {
                    case 0: return 0.0f;
                    case 1: return std::nextafter(span, 0.0f);
                    case 2: return span * 0.5f;
                    default: return span * unit();
                }
            };
            v.pos = {coordV(W), coordV(H)};
            v.depth = 240.0f * unit();
            // items: clustered near the viewer (many per cell: long runs), on edges, at -0, exactly R away
            const int n = 4 + pick(400);
            std::vector<OceanFood> items;
            auto addAt = [&](float x, float y, float z) {
                OceanFood f;
                f.pos = {x, y};
                f.depth = z;
                items.push_back(f);
            };
            // (one draw per statement: the order of a call's arguments is unspecified,
            // and native and wasm must build the same scenes)
            for (int i = 0; i < n; ++i) {
                switch (pick(10)) {
                    case 0: addAt(-0.0f, v.pos.y + R * (unit() - 0.5f), v.depth); break;                // -0 (ux = -0 at viewer x +0)
                    case 1: {                                                                          // on the seam
                        const float x = pick(2) ? 0.0f : W;
                        const float y = H * unit();
                        addAt(x, y, 240.0f * unit());
                        break;
                    }
                    case 2: addAt(v.pos.x + (pick(2) ? R : -R), v.pos.y, v.depth); break;               // exactly R (x)
                    case 3: addAt(v.pos.x + 0.6f * R, v.pos.y + 0.8f * R, v.depth); break;              // 3-4-5
                    case 4: addAt(v.pos.x, v.pos.y, v.depth + (pick(2) ? R : -R)); break;               // exactly R (depth)
                    case 5: if (!items.empty()) { items.push_back(items[pick((int)items.size())]); break; }   // a duplicate
                            [[fallthrough]];
                    case 6: {
                        const float x = W * unit();
                        const float y = H * unit();
                        const float z = pick(30) ? 240.0f * unit() : std::numeric_limits<float>::quiet_NaN();
                        addAt(x, y, z);
                        break;
                    }
                    default: {   // near the viewer, across the seam half the time
                        float x = v.pos.x + 2.2f * R * (unit() - 0.5f);
                        float y = v.pos.y + 2.2f * R * (unit() - 0.5f);
                        x = OceanWorld::wrapCoord(x, W);
                        y = OceanWorld::wrapCoord(y, H);
                        addAt(x, y, v.depth + 2.0f * R * (unit() - 0.5f));
                    }
                }
            }
            for (int i = 0; i < (int)items.size(); ++i) grid.insert(items[i], i);
            grid.build();
            for (int tor = 0; tor < 2; ++tor) {
                // the engine (member() is the peek's friend: found by ADL on its tag)
                const int got = tor ? (w.*member(ofp::peek::OwFoodWithinWrapped{}))(v, R)
                                    : (w.*member(ofp::peek::OwFoodWithin{}))(v, R);
                const auto list = ofp::field<ofp::peek::OwFoodSeen>(w);   // a copy
                // the definition: the scalar loops these replaced
                struct Rec { float dx, dy, dz, d2; int k; };
                std::vector<Rec> want;
                const float* fx = grid.xs();
                const float* fy = grid.ys();
                const float* fz = grid.depths();
                const float R2 = R * R, px = v.pos.x, py = v.pos.y, pz = v.depth;
                if (tor) {
                    const float hw = 0.5f * W, hh = 0.5f * H;
                    grid.forEachRunWrapped(v.pos, R, [&](int b, int e, float cx0, float cy0) {
                        vecRuns += (e - b) / 4;
                        for (int k = b; k < e; ++k) {
                            const float gx = fx[k] - cx0, gy = fy[k] - cy0;
                            const float q2 = gx * gx + gy * gy;
                            const float ux = fx[k] - px, uy = fy[k] - py;
                            const float dx = (ux > hw) ? ux - W : ((ux < -hw) ? ux + W : ux);
                            const float dy = (uy > hh) ? uy - H : ((uy < -hh) ? uy + H : uy);
                            wrapSelects += (ux > hw) | (ux < -hw) | (uy > hh) | (uy < -hh);
                            const float dz = fz[k] - pz;
                            const float d2 = dx * dx + dy * dy + dz * dz;
                            if ((q2 <= R2) && !(d2 > R2)) want.push_back({dx, dy, dz, d2, k});
                        }
                    });
                } else {
                    grid.forEachRun(v.pos, R, [&](int b, int e) {
                        vecRuns += (e - b) / 4;
                        for (int k = b; k < e; ++k) {
                            const float dx = fx[k] - px, dy = fy[k] - py;
                            const float q2 = dx * dx + dy * dy;
                            const float dz = fz[k] - pz;
                            const float d2 = q2 + dz * dz;
                            if ((q2 <= R2) && !(d2 > R2)) want.push_back({dx, dy, dz, d2, k});
                        }
                    });
                }
                bool same = got == (int)want.size();
                for (int j = 0; same && j < got; ++j) {
                    same = sameBits(list[j].dx, want[j].dx) && sameBits(list[j].dy, want[j].dy) &&
                           sameBits(list[j].dz, want[j].dz) && sameBits(list[j].d2, want[j].d2) && list[j].k == want[j].k;
                    negZero += std::signbit(want[j].dx) && want[j].dx == 0.0f;
                }
                t.expect(same, "%dx%d R %g %s, viewer (%.9g, %.9g, %.9g): %d records vs the definition's %zu (or a record differs)",
                         g.W, g.H, R, tor ? "wrapped" : "bounded", v.pos.x, v.pos.y, v.depth, got, want.size());
                ++scenes;
                records += (long)want.size();
            }
        }
    }
    t.expect(vecRuns > 1000 && wrapSelects > 1000 && negZero > 0, "too little coverage: %ld four-lane groups, %ld wrapped offsets, %ld -0",
             vecRuns, wrapSelects, negZero);
    t.note("%ld scans (%ld records, %ld four-lane groups, %ld wrapped offsets, %ld -0 offsets) == the scalar loops, bit for bit",
           scenes, records, vecRuns, wrapSelects, negZero);
}

}  // namespace ot

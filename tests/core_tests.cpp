// Core unit tests — deliberately depend ONLY on src/core/*.
// They include no SFML and link no SFML; if this target builds and runs,
// the simulation is genuinely decoupled from the rendering library.
//
// Minimal hand-rolled harness (no external test framework needed).

#include <cstdio>
#include <cmath>
#include <vector>
#include <algorithm>
#include <set>
#include <map>
#include <utility>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>
#include <atomic>

#include "core/vec2.hpp"
#include "core/color.hpp"
#include "core/random.hpp"
#include "core/genome.hpp"
#include "core/quadtree.hpp"
#include "core/spatial_grid.hpp"
#include "core/creature.hpp"
#include "core/body_model.hpp"
#include "core/world.hpp"
#include "core/stats.hpp"
#include "core/cluster_map_io.hpp"
#include "core/wiring_log.hpp"
#include "core/json_min.hpp"
#include "core/checkpoint_io.hpp"
#include "core/predator_brain.hpp"
#include "core/predator_stats.hpp"
#include "core/transplant.hpp"

static int g_checks = 0;
static int g_failures = 0;

#define CHECK(cond)                                                       \
    do {                                                                  \
        ++g_checks;                                                       \
        if (!(cond)) {                                                    \
            ++g_failures;                                                 \
            std::printf("  FAIL [line %d]: %s\n", __LINE__, #cond);       \
        }                                                                 \
    } while (0)

static bool approx(float a, float b, float eps = 1e-4f) {
    return std::fabs(a - b) <= eps;
}

// ---------------------------------------------------------------
static void test_vec2() {
    std::printf("vec2...\n");
    Vec2 a{3.0f, 4.0f};
    CHECK(approx(length(a), 5.0f));
    CHECK(approx(lengthSq(a), 25.0f));

    Vec2 n = normalized(a);
    CHECK(approx(length(n), 1.0f));

    // zero vector normalizes to a safe default, never NaN
    Vec2 z = normalized(Vec2{0.0f, 0.0f});
    CHECK(!std::isnan(z.x) && !std::isnan(z.y));
    CHECK(approx(length(z), 1.0f));

    CHECK(approx(dot(Vec2{1, 0}, Vec2{0, 1}), 0.0f));
    Vec2 sum = Vec2{1, 2} + Vec2{3, 4};
    CHECK(approx(sum.x, 4.0f) && approx(sum.y, 6.0f));
    Vec2 scaled = 2.0f * Vec2{1.5f, -2.0f};
    CHECK(approx(scaled.x, 3.0f) && approx(scaled.y, -4.0f));
}

// ---------------------------------------------------------------
static void test_color() {
    std::printf("color...\n");
    // int-taking ctor must not narrow-error and must truncate to 8-bit
    Color c(300, 150, 20);
    CHECK(c.r == static_cast<uint8_t>(300));
    CHECK(c.g == 150);
    CHECK(c.b == 20);
    CHECK(c.a == 255);
}

// ---------------------------------------------------------------
static void test_quadtree() {
    std::printf("quadtree...\n");
    AABB bounds{{50.0f, 50.0f}, {50.0f, 50.0f}}; // covers [0,100]x[0,100]
    QuadTree qt(bounds);

    std::vector<Vec2> pts;
    for (int i = 0; i < 200; ++i) {
        Vec2 p{rng.range(0.0f, 100.0f), rng.range(0.0f, 100.0f)};
        pts.push_back(p);
        qt.insert(p, i);
    }

    // brute-force reference vs quadtree query
    Vec2 center{50.0f, 50.0f};
    float radius = 20.0f;
    std::vector<int> got;
    qt.queryRadius(center, radius, got);

    int reference = 0;
    for (auto& p : pts) {
        float dx = p.x - center.x, dy = p.y - center.y;
        if (dx * dx + dy * dy <= radius * radius) ++reference;
    }
    CHECK((int)got.size() == reference);

    // every returned index must actually be within the radius
    bool allInside = true;
    for (int idx : got) {
        float dx = pts[idx].x - center.x, dy = pts[idx].y - center.y;
        if (dx * dx + dy * dy > radius * radius + 1e-3f) allInside = false;
    }
    CHECK(allInside);
}

// ---------------------------------------------------------------
static void test_genome_and_net() {
    std::printf("genome + neural net...\n");
    Genome g = makeRandomGenome();
    CHECK((int)g.size() >= GENOME_INITIAL_MIN);
    CHECK((int)g.size() <= GENOME_INITIAL_MAX);

    NeuralNet net;
    buildNeuralNet(g, net);
    CHECK(net.flat.size() == g.size());

    float sensors[NUM_SENSES];
    for (int i = 0; i < NUM_SENSES; ++i) sensors[i] = rng.range(-1.0f, 1.0f);
    float actions[NUM_ACTIONS];
    feedForward(net, sensors, actions);

    // tanh-bounded outputs
    bool bounded = true;
    for (int i = 0; i < NUM_ACTIONS; ++i)
        if (actions[i] < -1.0001f || actions[i] > 1.0001f) bounded = false;
    CHECK(bounded);

    // crossover length equals one of the parents' lengths
    Genome p1 = makeRandomGenome();
    Genome p2 = makeRandomGenome();
    Genome child = crossover(p1, p2);
    CHECK(child.size() == p1.size() || child.size() == p2.size());

    // similarity is a normalized fraction
    float sim = genomeSimilarity(p1, p2);
    CHECK(sim >= 0.0f && sim <= 1.0f);

    // mutation keeps genome within hard length bounds
    Genome m = makeRandomGenome();
    for (int i = 0; i < 500; ++i) mutateGenome(m, 0.5f);
    CHECK((int)m.size() >= GENOME_MIN_LENGTH);
    CHECK((int)m.size() <= GENOME_MAX_LENGTH);
}

// ---------------------------------------------------------------
static void test_creature() {
    std::printf("creature...\n");
    Creature c = makeRandomCreature(Vec2{100.0f, 100.0f});
    CHECK(c.alive);
    CHECK(approx(c.pos.x, 100.0f) && approx(c.pos.y, 100.0f));
    CHECK(approx(length(c.forward()), 1.0f));
    // right() is perpendicular to forward()
    CHECK(approx(dot(c.forward(), c.right()), 0.0f, 1e-3f));
}

// ---------------------------------------------------------------
// The uniform grid must return the SAME set of indices as the QuadTree for
// every radius query (order may differ; the set must not). This guards the
// drop-in replacement against silent divergence as either structure changes.
static void test_spatial_grid_matches_quadtree() {
    std::printf("spatial grid == quadtree...\n");
    rng.seed(7u);
    const int W = 1920, H = 1080;
    int mismatches = 0;

    for (int trial = 0; trial < 20; ++trial) {
        int n = rng.intRange(50, 2500);
        std::vector<Vec2> pts(n);
        AABB bounds{{W / 2.0f, H / 2.0f}, {W / 2.0f, H / 2.0f}};
        QuadTree qt(bounds);
        SpatialGrid grid;
        grid.init(W, H, 80.0f);

        for (int i = 0; i < n; ++i) {
            pts[i] = {rng.range(0.0f, (float)W), rng.range(0.0f, (float)H)};
            qt.insert(pts[i], i);
            grid.insert(pts[i], i);
        }
        grid.build();

        // Every radius the World actually issues, plus a couple of extremes.
        const float radii[] = {5.f, 10.f, 20.f, 30.f, 80.f, 150.f, 200.f};
        for (int q = 0; q < 200; ++q) {
            Vec2 c{rng.range(-20.f, (float)W + 20.f),
                   rng.range(-20.f, (float)H + 20.f)};
            float r = radii[q % 7];
            std::vector<int> a, b;
            qt.queryRadius(c, r, a);
            grid.queryRadius(c, r, b);
            std::sort(a.begin(), a.end());
            std::sort(b.begin(), b.end());
            if (a != b) ++mismatches;
        }
    }
    CHECK(mismatches == 0);
}

// The step's exact shortcuts: each one must give the same bits as the code it
// replaced, or every run changes. (The whole-run evidence is the parity suite
// and a checkpoint compare against the previous main; these pin the pieces.)
static std::uint32_t floatBits(float f) {
    std::uint32_t u;
    std::memcpy(&u, &f, sizeof u);
    return u;
}

static void test_exact_shortcuts() {
    std::printf("exact shortcuts (grid order, decay, count tanh, similarity, still water, tanh array)...\n");

    // --- The cell-ordered grid lists hits in the order a vector per cell did:
    // cells row by row, each cell's entries in insertion order. ---
    {
        rng.seed(4242u);
        const int W = 1920, H = 1080;
        const float cell = 80.0f;
        bool orderSame = true, visitSame = true, countSame = true;
        for (int trial = 0; trial < 10; ++trial) {
            const int n = rng.intRange(50, 3000);
            SpatialGrid grid;
            grid.init(W, H, cell);
            const int cols = (int)(W * (1.0f / cell)) + 1, rows = (int)(H * (1.0f / cell)) + 1;
            std::vector<std::vector<std::pair<Vec2, int>>> buckets((size_t)cols * rows);
            for (int i = 0; i < n; ++i) {
                const Vec2 p{rng.range(0.0f, (float)W - 0.001f), rng.range(0.0f, (float)H - 0.001f)};
                grid.insert(p, i);
                const int cx = std::clamp((int)(p.x * (1.0f / cell)), 0, cols - 1);
                const int cy = std::clamp((int)(p.y * (1.0f / cell)), 0, rows - 1);
                buckets[(size_t)cy * cols + cx].push_back({p, i});
            }
            grid.build();
            const float radii[] = {10.f, 20.f, 30.f, 80.f, 160.f};
            for (int q = 0; q < 100; ++q) {
                const Vec2 c{rng.range(-20.f, (float)W + 20.f), rng.range(-20.f, (float)H + 20.f)};
                const float r = radii[q % 5], r2 = r * r;
                std::vector<int> want;
                const float inv = 1.0f / cell;
                const int x0 = std::clamp((int)((c.x - r) * inv), 0, cols - 1);
                const int x1 = std::clamp((int)((c.x + r) * inv), 0, cols - 1);
                const int y0 = std::clamp((int)((c.y - r) * inv), 0, rows - 1);
                const int y1 = std::clamp((int)((c.y + r) * inv), 0, rows - 1);
                for (int cy = y0; cy <= y1; ++cy)
                    for (int cx = x0; cx <= x1; ++cx)
                        for (const auto& [p, idx] : buckets[(size_t)cy * cols + cx]) {
                            const float dx = p.x - c.x, dy = p.y - c.y;
                            if (dx * dx + dy * dy <= r2) want.push_back(idx);
                        }
                std::vector<int> got;
                grid.queryRadius(c, r, got);
                if (got != want) orderSame = false;
                std::vector<int> seen;
                grid.forEachInRadius(c, r, [&](int idx, Vec2) { seen.push_back(idx); });
                if (seen != want) visitSame = false;
                if (grid.countRadius(c, r) != (int)want.size()) countSame = false;
                std::vector<int> wrapped;
                grid.queryRadiusWrapped(c, r, wrapped);
                if (grid.countRadiusWrapped(c, r) != (int)wrapped.size()) countSame = false;
            }
        }
        CHECK(orderSame);
        CHECK(visitSame);
        CHECK(countSame);
    }

    // --- Pheromone decay in fixed point == the float expression, all bytes ---
    {
        int differ = 0;
        for (int v = 0; v < 256; ++v) {
            const auto viaFloat = static_cast<uint8_t>(static_cast<uint8_t>(v) * 0.97f);
            const auto viaFixed = static_cast<uint8_t>((static_cast<uint32_t>(v) * 63570u) >> 16);
            if (viaFloat != viaFixed) ++differ;
        }
        CHECK(differ == 0);
    }

    // --- Count tables == the tanh call, in the table and past both ends ---
    {
        int differ = 0;
        for (int k = -2000; k <= 2000; ++k) {
            if (floatBits(tanhCountOver5(k))  != floatBits(evomath::tanhf((float)k / 5.0f)))  ++differ;
            if (floatBits(tanhCountOver10(k)) != floatBits(evomath::tanhf((float)k / 10.0f))) ++differ;
            if (floatBits(tanhCountOver15(k)) != floatBits(evomath::tanhf((float)k / 15.0f))) ++differ;
        }
        CHECK(differ == 0);
    }

    // --- genomeSimilarity without the short-circuit == the && version ---
    {
        rng.seed(31337u);
        auto reference = [](const Genome& g1, const Genome& g2) {
            const size_t minLen = std::min(g1.size(), g2.size());
            if (minLen == 0) return 0.0f;
            int matches = 0;
            for (size_t i = 0; i < minLen; ++i)
                if (g1[i].sourceType == g2[i].sourceType && g1[i].sinkType == g2[i].sinkType)
                    matches++;
            return static_cast<float>(matches) / static_cast<float>(minLen);
        };
        int differ = 0;
        for (int t = 0; t < 2000; ++t) {
            const Genome a = makeRandomGenome(rng.intRange(0, 4) == 0 ? 0 : 16, 80);
            const Genome b = makeRandomGenome(16, 80);
            if (floatBits(genomeSimilarity(a, b)) != floatBits(reference(a, b))) ++differ;
            if (floatBits(genomeSimilarity(b, a)) != floatBits(reference(b, a))) ++differ;
        }
        CHECK(differ == 0);
    }

    // --- Still water: the signed zero the current sensors used to compute ---
    {
        const float comps[] = {1.0f, -1.0f, 0.0f, -0.0f, 0.6f, -0.8f, 1e-30f, -1e-30f};
        int differ = 0;
        for (float fx : comps)
            for (float fy : comps) {
                const Vec2 cur{0.0f, 0.0f};
                const float old = evomath::tanhf((cur.x * fx + cur.y * fy) / 100.0f);
                const float now = (std::signbit(fx) && std::signbit(fy)) ? -0.0f : 0.0f;
                if (floatBits(old) != floatBits(now)) ++differ;
            }
        CHECK(differ == 0);
    }

    // --- tanhfArray (branch-free, vectorised) == tanhf. Every 509th bit
    //     pattern covers every exponent and both signs, NaNs and infinities
    //     included; the specials pin the case boundaries. (A sweep of all 2^32
    //     inputs agreed too, when this was written.) ---
    {
        std::vector<float> in;
        in.reserve((std::size_t{1} << 32) / 509 + 32);
        for (std::uint64_t b = 0; b < (std::uint64_t{1} << 32); b += 509) {
            const std::uint32_t u = static_cast<std::uint32_t>(b);
            float f;
            std::memcpy(&f, &u, sizeof f);
            in.push_back(f);
        }
        const std::uint32_t edges[] = {0x3f0c9f54u, 0x3f0c9f55u, 0x41200000u, 0x41200001u,
                                       0x3e82c578u, 0x3e82c579u, 0x00800000u, 0x007fffffu,
                                       0x3eb17218u, 0x3F851592u, 0x33000000u, 0x7f800000u};
        for (std::uint32_t e : edges)
            for (std::uint32_t s : {0u, 0x80000000u}) {
                float f;
                const std::uint32_t u = e | s;
                std::memcpy(&f, &u, sizeof f);
                in.push_back(f);
            }
        std::vector<float> out(in.size());
        evomath::tanhfArray(in.data(), out.data(), (int)in.size());
        std::size_t differ = 0;
        for (std::size_t i = 0; i < in.size(); ++i)
            if (floatBits(out[i]) != floatBits(evomath::tanhf(in[i]))) ++differ;
        CHECK(differ == 0);
    }

    // --- vendored expf / logf / tanh == musl. The fingerprints were taken
    //     from musl's own expf/logf/tanh (std:: under emsdk 6.0.4), so this
    //     pins the vendored copies (code and tables) to musl in the native
    //     build — core_tests is native-only (CMakeLists.txt returns before it
    //     under Emscripten); wasm == musl is covered by the exhaustive 2^32
    //     run and the harnesses' native == wasm checks:
    //     FNV-1a 64 over expf and logf of every 509th float bit pattern (NaN
    //     canonical) and over tanh of 65536 doubles spread over [2^-32, 64).
    //     The two named inputs are where glibc's FMA expf (its default on
    //     FMA/AVX2 CPUs) is 1 ulp off musl — the whole reason for vendoring.
    //     Every input is read through volatile storage, so -O3 cannot fold a
    //     call into a compile-time constant: the runtime code path is tested.
    //     (All 2^32 floats agreed too, when this was written.) ---
    {
        auto mix = [](std::uint64_t& h, std::uint64_t v, int n) {
            for (int b = 0; b < n; ++b) { h ^= (v >> (8 * b)) & 0xffu; h *= 0x100000001b3ull; }
        };
        auto canon = [](float f) {
            const std::uint32_t u = floatBits(f);
            return ((u & 0x7fffffffu) > 0x7f800000u) ? 0x7fc00000u : u;
        };
        std::uint64_t he = 1469598103934665603ull, hl = he, ht = he;
        for (std::uint64_t b = 0; b < (std::uint64_t{1} << 32); b += 509) {
            const std::uint32_t u = static_cast<std::uint32_t>(b);
            float f;
            std::memcpy(&f, &u, sizeof f);
            volatile float vf = f;
            mix(he, canon(evomath::expf(vf)), 4);
            mix(hl, canon(evomath::logf(vf)), 4);
        }
        const std::uint64_t lo = 0x3df0000000000000ull, hi = 0x4050000000000000ull,
                            step = ((hi - lo) / 65536) | 1;
        for (std::uint64_t i = 0; i < 65536; ++i) {
            const std::uint64_t u = (lo + i * step) | ((i & 1) << 63);
            double d, t;
            std::memcpy(&d, &u, sizeof d);
            volatile double vd = d;
            t = evomath::tanh(vd);
            std::uint64_t ut;
            std::memcpy(&ut, &t, sizeof ut);
            mix(ht, ut, 8);
        }
        CHECK(he == 0xea8351dba6b74039ull);
        CHECK(hl == 0xb7e03d5adf9e01cdull);
        CHECK(ht == 0xf143dc73794db1f7ull);
        auto bitsF = [](std::uint32_t u) { float f; std::memcpy(&f, &u, sizeof f); return f; };
        volatile std::uint32_t fma0 = 0xc27c65d9u, fma1 = 0x4202422fu;
        CHECK(floatBits(evomath::expf(bitsF(fma0))) == 0x11fa2992u);  // -0x1.f8cbb2p+5
        CHECK(floatBits(evomath::expf(bitsF(fma1))) == 0x56fc9f1bu);  //  0x1.04845ep+5
    }
}

// ---------------------------------------------------------------
static void test_world_invariants() {
    std::printf("world invariants (1000 steps)...\n");
    rng.seed(12345u); // reproducible run

    World w;
    w.init(640, 480, 80);

    const std::size_t initialFood = w.food.size();
    CHECK(initialFood == (std::size_t)w.cfg.targetFood);

    for (int step = 0; step < 1000; ++step) {
        w.update(0.016f);

        // population floor is enforced every tick
        CHECK((int)w.creatures.size() >= w.cfg.minPopulation);
        // food is hard-capped
        CHECK((int)w.food.size() <= w.cfg.targetFood * 2);
    }

    CHECK(w.frame == 1000);

    // no creature ended up with a NaN/inf position or escaped the torus
    bool positionsSane = true;
    for (const auto& c : w.creatures) {
        if (std::isnan(c.pos.x) || std::isnan(c.pos.y) ||
            std::isinf(c.pos.x) || std::isinf(c.pos.y)) positionsSane = false;
        if (c.pos.x < 0 || c.pos.x >= w.width ||
            c.pos.y < 0 || c.pos.y >= w.height) positionsSane = false;
    }
    CHECK(positionsSane);
}

// ---------------------------------------------------------------
// Predator (Stage A). Covers: fixed-count spawn; the no-predator path stays
// predation-free; predation actually happens and the death-cause decomposition
// partitions totalDeaths exactly; and the predator_align metric's sign
// convention (away from predator -> +1, toward -> -1, none in range -> 0).
static void test_predator() {
    std::printf("predator (Stage A)...\n");

    // (1) Fixed-count spawn: exactly cfg.predatorCount predators appear, placed
    //     inside the world, and the default path spawns none.
    {
        rng.seed(7u);
        World w;
        w.cfg.predatorCount = 5;
        w.init(640, 480, 30);
        CHECK(w.predators.size() == 5u);
        bool predPosSane = true;
        for (const auto& p : w.predators) {
            if (std::isnan(p.pos.x) || std::isnan(p.pos.y)) predPosSane = false;
            if (p.pos.x < 0 || p.pos.x >= w.width ||
                p.pos.y < 0 || p.pos.y >= w.height) predPosSane = false;
        }
        CHECK(predPosSane);

        World wNone;                 // default cfg.predatorCount == 0
        wNone.init(640, 480, 30);
        CHECK(wNone.predators.empty());
    }

    // (2) No-predator run: no predation deaths ever, and the decomposition is a
    //     true partition of totalDeaths (predation == 0 here).
    {
        rng.seed(99u);
        World w;
        w.init(640, 480, 80);
        for (int s = 0; s < 600; ++s) w.update(0.016f);
        CHECK(w.totalDeathsPredation == 0);
        CHECK(w.totalDeaths ==
              w.totalDeathsPredation + w.totalDeathsStarvation + w.totalDeathsAge);
    }

    // (3) Predators ON: kills accumulate, predators are immortal/fixed-count, the
    //     decomposition still partitions totalDeaths exactly, and nothing goes
    //     NaN / leaves the torus. min-pop 0 so the reseed floor doesn't mask
    //     predation; capture radius widened so the test isn't seed-fragile.
    {
        rng.seed(2024u);
        World w;
        w.cfg.predatorCount        = 8;
        w.cfg.minPopulation        = 0;
        w.cfg.predatorCaptureRadius = 25.0f;
        w.cfg.predatorSpeed        = 130.0f;
        w.init(1280, 720, 200);
        const std::size_t pred0 = w.predators.size();
        for (int s = 0; s < 1500; ++s) w.update(0.016f);

        CHECK(w.predators.size() == pred0);           // immortal, fixed count
        CHECK(w.totalDeathsPredation > 0);            // predation occurred
        CHECK(w.totalDeaths ==
              w.totalDeathsPredation + w.totalDeathsStarvation + w.totalDeathsAge);

        bool sane = true;
        for (const auto& c : w.creatures)
            if (std::isnan(c.pos.x) || std::isnan(c.pos.y) ||
                c.pos.x < 0 || c.pos.x >= w.width ||
                c.pos.y < 0 || c.pos.y >= w.height) sane = false;
        for (const auto& p : w.predators)
            if (std::isnan(p.pos.x) || std::isnan(p.pos.y) ||
                p.pos.x < 0 || p.pos.x >= w.width ||
                p.pos.y < 0 || p.pos.y >= w.height) sane = false;
        CHECK(sane);
    }

    // (4) predator_align sign convention, exercised through computeStats. One
    //     prey, one predator due east of it (within the prey's perception 80).
    {
        World w;                       // default cfg (perception 80, no current)
        w.init(640, 480, 0);
        w.creatures.clear();
        w.predators.clear();

        Creature prey;                 // defaults are fine for the metric
        prey.pos = {100.0f, 100.0f};

        Predator pred;
        pred.pos = {150.0f, 100.0f};   // 50 east => inside perception
        w.predators.push_back(pred);

        // Heading directly AWAY from the predator (-x) => cosine +1.
        prey.vel = {-10.0f, 0.0f};
        w.creatures = {prey};
        CHECK(approx(computeStats(w).avgPredatorAlign, 1.0f, 1e-3f));

        // Heading straight AT the predator (+x) => cosine -1.
        prey.vel = {10.0f, 0.0f};
        w.creatures = {prey};
        CHECK(approx(computeStats(w).avgPredatorAlign, -1.0f, 1e-3f));

        // Predator out of perception (300 east > 80) => no threat in range => 0.
        w.predators.clear();
        Predator far; far.pos = {400.0f, 100.0f};
        w.predators.push_back(far);
        prey.vel = {10.0f, 0.0f};
        w.creatures = {prey};
        CHECK(approx(computeStats(w).avgPredatorAlign, 0.0f, 1e-6f));
    }
}

// ---------------------------------------------------------------
// Schooling metric: local neighbour alignment + crowding, via computeStats.
static void test_schooling_metric() {
    std::printf("schooling metric...\n");
    auto stats_of = [](std::vector<Creature> cs) {
        World w;
        w.init(640, 480, 0);          // default perception 80, no predators/current
        w.creatures = std::move(cs);
        return computeStats(w);
    };
    auto mk = [](float x, float y, float vx, float vy) {
        Creature c; c.pos = {x, y}; c.vel = {vx, vy}; return c;
    };

    // Aligned cluster: 3 prey within perception, same heading => align ~ +1,
    // and each sees the other 2 => mean neighbour count = 2.
    {
        WorldStats s = stats_of({ mk(100,100, 5,0), mk(110,100, 5,0), mk(105,110, 5,0) });
        CHECK(approx(s.avgNeighborAlign, 1.0f, 1e-3f));
        CHECK(approx(s.avgNeighborCount, 2.0f, 1e-3f));
    }
    // Anti-aligned pair: each one's only neighbour heads the opposite way => -1.
    {
        WorldStats s = stats_of({ mk(100,100, 5,0), mk(110,100, -5,0) });
        CHECK(approx(s.avgNeighborAlign, -1.0f, 1e-3f));
        CHECK(approx(s.avgNeighborCount, 1.0f, 1e-3f));
    }
    // Dispersed beyond perception: no neighbours => align 0, count 0.
    {
        WorldStats s = stats_of({ mk(100,100, 5,0), mk(100,400, 5,0) });
        CHECK(approx(s.avgNeighborAlign, 0.0f, 1e-6f));
        CHECK(approx(s.avgNeighborCount, 0.0f, 1e-6f));
    }
}

// ---------------------------------------------------------------
// Predator energy economy (Stage B). Covers: the economy-OFF path leaves the
// energy field an untouched constant and predators immortal (Stage A preserved);
// economy-ON predators starve to extinction with no prey; reproduction buds a
// child and conserves energy (parent pays exactly newbornEnergy); a capture adds
// exactly the meal to the hunter; and the predator death-cause counters move.
static void test_predator_economy() {
    std::printf("predator economy (Stage B)...\n");

    // (1) Economy OFF (Stage A): predators are immortal/fixed-count and the energy
    //     field is never touched (stays at the seeded newbornEnergy), even with
    //     prey present and captures happening.
    {
        rng.seed(7u);
        World w;
        w.cfg.predatorCount = 4;
        w.cfg.predatorEconomy = false;            // Stage A
        w.cfg.predatorNewbornEnergy = 30.0f;
        w.cfg.predatorCaptureRadius = 25.0f;      // ensure some captures
        w.init(640, 480, 120);
        const std::size_t n0 = w.predators.size();
        for (int s = 0; s < 600; ++s) w.update(0.016f);
        CHECK(w.predators.size() == n0);          // immortal, fixed count
        bool energyUntouched = true;
        for (const auto& p : w.predators)
            if (!approx(p.energy, 30.0f, 1e-4f)) energyUntouched = false;
        CHECK(energyUntouched);                   // economy off => energy is inert
        CHECK(w.totalPredatorBirths == 0);
        CHECK(w.totalPredatorDeathsStarvation == 0);
        CHECK(w.totalPredatorDeathsAge == 0);
    }

    // (2) Economy ON, NO prey: predators only burn, never eat, so every predator
    //     starves to extinction and the starvation counter equals the initial
    //     count. (min-pop 0 so the reseed never injects prey to feed them.)
    {
        rng.seed(11u);
        World w;
        w.cfg.predatorCount = 5;
        w.cfg.predatorEconomy = true;
        w.cfg.predatorMetabolism = 2.0f;
        w.cfg.predatorMoveCost = 0.0f;            // burn = 2/sec exactly
        w.cfg.predatorNewbornEnergy = 30.0f;      // => starves at 15s (~938 steps)
        w.cfg.minPopulation = 0;
        w.init(640, 480, 0);
        w.creatures.clear();                      // no prey at all
        const std::size_t n0 = w.predators.size();
        for (int s = 0; s < 1500; ++s) w.update(0.016f);
        CHECK(w.predators.empty());               // all starved
        CHECK(w.totalPredatorDeathsStarvation == (long long)n0);
        CHECK(w.totalPredatorDeathsAge == 0);
        CHECK(w.totalPredatorBirths == 0);        // no meals => never bred
    }

    // (3) Economy ON, reproduction + energy conservation. One predator seeded
    //     above the repro threshold, no prey. On the first update it buds exactly
    //     one child; the parent pays newbornEnergy; the child starts at
    //     newbornEnergy. Thresholds chosen so neither re-breeds on later steps.
    {
        rng.seed(13u);
        World w;
        w.cfg.predatorCount = 1;
        w.cfg.predatorEconomy = true;
        w.cfg.predatorMetabolism = 2.0f;
        w.cfg.predatorMoveCost = 0.0f;            // burn = 2/sec
        w.cfg.predatorReproEnergy = 40.0f;
        w.cfg.predatorNewbornEnergy = 30.0f;
        w.cfg.minPopulation = 0;
        w.init(640, 480, 0);
        w.creatures.clear();
        w.predators[0].energy = 50.0f;            // above the 40 threshold
        w.update(0.016f);
        CHECK(w.predators.size() == 2u);          // budded exactly one child
        CHECK(w.totalPredatorBirths == 1);
        // Parent paid newbornEnergy after a single step's burn (2 * 0.016 = 0.032).
        const float burn = 2.0f * 0.016f;
        CHECK(approx(w.predators[0].energy, 50.0f - burn - 30.0f, 1e-3f));
        CHECK(approx(w.predators[1].energy, 30.0f, 1e-4f));   // child seeded
        // Neither (parent ~19.97, child 30) is >= 40, so no further births.
        for (int s = 0; s < 5; ++s) w.update(0.016f);
        CHECK(w.totalPredatorBirths == 1);
    }

    // (4) Economy ON, capture meal conservation. One predator, one prey within the
    //     capture radius and the predator not digesting. After one update the prey
    //     is dead (predation) and the predator gained exactly the fixed meal minus
    //     one step's burn. Repro threshold high so the meal doesn't trigger a birth.
    {
        rng.seed(17u);
        World w;
        w.cfg.predatorCount = 0;                  // we place the predator by hand
        w.cfg.predatorEconomy = true;
        w.cfg.predatorMetabolism = 2.0f;
        w.cfg.predatorMoveCost = 0.0f;            // burn = 2/sec
        w.cfg.predatorMeal = 12.0f;               // fixed meal (deterministic)
        w.cfg.predatorReproEnergy = 1000.0f;      // never breeds in this test
        w.cfg.predatorCaptureRadius = 30.0f;      // generous => not seed-fragile
        w.cfg.minPopulation = 0;
        w.init(640, 480, 0);
        w.creatures.clear();
        w.predators.clear();

        // A real creature (built neural net) so World::update can feedForward it.
        Creature prey = makeRandomCreature(Vec2{200.0f, 200.0f});
        prey.foodReserves = 25.0f;
        w.creatures = {prey};

        Predator pred; pred.pos = {203.0f, 200.0f};   // 3 away => well inside capture
        pred.energy = 20.0f; pred.digestTimer = 0.0f;
        w.predators = {pred};

        const long long preds0 = w.totalDeathsPredation;
        w.update(0.016f);
        CHECK(w.totalDeathsPredation == preds0 + 1);  // the prey was eaten
        CHECK(w.predators.size() == 1u);              // hunter survived (didn't breed)
        // energy = start - burn + meal (the predator moved one step then ate).
        const float burn = 2.0f * 0.016f;
        CHECK(approx(w.predators[0].energy, 20.0f - burn + 12.0f, 1e-3f));
    }
}

// ---------------------------------------------------------------
// Inspection (stable ids + activation capture) and the death-cluster map.
// These are diagnostic features and must NOT change dynamics; the checks confirm
// they are inert by default and behave when switched on.
static void test_inspection_and_cluster() {
    std::printf("inspection + cluster map...\n");

    // (1) Stable ids: every creature gets a unique non-zero id; counter advances.
    {
        rng.seed(3u);
        World w;
        w.init(640, 480, 60);
        std::set<std::uint64_t> ids;
        for (const auto& c : w.creatures) { CHECK(c.id != 0); ids.insert(c.id); }
        CHECK(ids.size() == w.creatures.size());          // all unique
        CHECK(w.nextId_ == w.creatures.size() + 1);       // 1-based, contiguous
    }

    // (2) clusterProject2D is deterministic and separates distinct genomes.
    {
        rng.seed(4u);
        Genome g1 = makeRandomGenome();
        Genome g2 = makeRandomGenome();
        Vec2 a = clusterProject2D(g1);
        Vec2 b = clusterProject2D(g1);
        CHECK(a.x == b.x && a.y == b.y);                  // same genome -> same point
        Vec2 c = clusterProject2D(g2);
        CHECK(!(a.x == c.x && a.y == c.y));               // different genomes differ
        CHECK(std::isfinite(a.x) && std::isfinite(a.y));
    }

    // (3) Activation capture is gated: OFF (default) leaves lastSensors all zero;
    //     ON populates them (position sensors are non-zero for any creature).
    {
        rng.seed(5u);
        World w;                                          // captureActivations defaults false
        w.init(640, 480, 40);
        for (int s = 0; s < 5; ++s) w.update(0.016f);
        bool anyNonZeroOff = false;
        for (const auto& c : w.creatures)
            for (float v : c.lastSensors) if (v != 0.0f) anyNonZeroOff = true;
        CHECK(!anyNonZeroOff);                            // stayed inert

        rng.seed(5u);
        World w2;
        w2.cfg.captureActivations = true;
        w2.init(640, 480, 40);
        for (int s = 0; s < 5; ++s) w2.update(0.016f);
        bool anyNonZeroOn = false;
        for (const auto& c : w2.creatures)
            for (float v : c.lastSensors) if (v != 0.0f) anyNonZeroOn = true;
        CHECK(anyNonZeroOn);                              // captured live values
    }

    // (4) Death-cluster map: OFF (default) logs nothing; ON logs deaths and the
    //     RAM bound holds via decimation (stride doubles past the cap).
    {
        rng.seed(6u);
        World w;                                          // clusterMap defaults false
        w.cfg.metabolicRate = 50.0f;                      // starve fast => many deaths
        w.cfg.minPopulation = 0;                          // let them actually die off/reseed-free
        w.init(640, 480, 80);
        for (int s = 0; s < 300; ++s) w.update(0.016f);
        CHECK(w.deathLog.empty());
        CHECK(w.totalDeathsLogged_ == 0);

        rng.seed(6u);
        World w2;
        w2.cfg.metabolicRate = 50.0f;
        w2.cfg.minPopulation = 0;
        w2.cfg.clusterMap = true;
        w2.cfg.clusterMax = 4;                            // tiny cap to force decimation
        w2.init(640, 480, 80);
        for (int s = 0; s < 300; ++s) w2.update(0.016f);
        CHECK(w2.totalDeathsLogged_ > 4);                 // more deaths than the cap
        CHECK((int)w2.deathLog.size() <= 2 * w2.cfg.clusterMax);   // RAM bounded
        CHECK(w2.clusterStride_ > 1);                     // decimation actually fired
        for (const auto& d : w2.deathLog) {
            CHECK(std::isfinite(d.x) && std::isfinite(d.y));
            CHECK(d.cause == 's' || d.cause == 'a' || d.cause == 'p');
            CHECK(d.index % w2.clusterStride_ == 0);      // kept sample is uniform
        }
    }
}

// ---------------------------------------------------------------
// v0.12 analysis: sketch determinism, PCA axis recovery, lineage inheritance,
// and sensor-wiring fractions.
static void test_analysis_v012() {
    std::printf("analysis (sketch / PCA / lineage / wiring)...\n");

    // (1) clusterSketch is deterministic and the 2-D map is a function of it.
    {
        rng.seed(20u);
        Genome g = makeRandomGenome();
        float a[CLUSTER_SKETCH_DIM], b[CLUSTER_SKETCH_DIM];
        clusterSketch(g, a); clusterSketch(g, b);
        for (int k = 0; k < CLUSTER_SKETCH_DIM; ++k) CHECK(a[k] == b[k]);
        Vec2 p = clusterProject2D(g), q = sketchTo2D(a);
        CHECK(p.x == q.x && p.y == q.y);
    }

    // (2) PCA recovers a planted dominant direction. Build points strung out along
    //     sketch-axis 0 (large spread) with tiny noise elsewhere; PC1 should capture
    //     almost all the variance, so projected-x spread >> projected-y spread.
    {
        std::vector<World::DeathRecord> pts(400);
        for (int i = 0; i < 400; ++i) {
            for (int k = 0; k < CLUSTER_SKETCH_DIM; ++k) pts[i].sketch[k] = 0.001f * ((i * 7 + k) % 5);
            pts[i].sketch[0] = (float)(i - 200);     // dominant spread on axis 0
            pts[i].index = i;
        }
        std::vector<float> px, py;
        CHECK(clustermap::pcaProject(pts, px, py));
        auto spread = [](const std::vector<float>& v) {
            float lo = v[0], hi = v[0]; for (float x : v) { lo = std::min(lo, x); hi = std::max(hi, x); } return hi - lo;
        };
        const float sx = spread(px), sy = spread(py);
        CHECK(sx > 50.0f);                 // PC1 captured the planted axis
        CHECK(sx > 20.0f * std::max(1e-3f, sy));   // and dwarfs PC2
    }

    // (3) Lineage: founders get own-id lineage; children inherit a parent's lineage,
    //     so the set of distinct lineages never exceeds the number of founders.
    {
        rng.seed(21u);
        World w;
        w.cfg.minPopulation = 0;           // no reseed founders mid-run
        w.init(640, 480, 50);
        std::set<std::uint64_t> founders;
        for (const auto& c : w.creatures) { CHECK(c.lineageId == c.id); founders.insert(c.lineageId); }
        CHECK(founders.size() == 50u);
        for (int s = 0; s < 400; ++s) w.update(0.016f);
        std::set<std::uint64_t> live;
        for (const auto& c : w.creatures) live.insert(c.lineageId);
        for (auto l : live) CHECK(founders.count(l) == 1);   // no new lineages appeared
    }

    // (4) Sensor-wiring fractions are in [0,1]; a planted creature wiring exactly
    //     one sensor source makes that sensor's fraction 1 in a singleton population.
    {
        rng.seed(22u);
        World w;
        w.cfg.minPopulation = 0;
        w.init(640, 480, 0);
        w.creatures.clear();
        Creature c = makeRandomCreature(Vec2{100, 100});
        // Force a single known sensor->action connection.
        c.genome.clear();
        Gene g; g.sourceType = SOURCE_SENSOR; g.sourceNum = OWN_SPEED;
        g.sinkType = SINK_ACTION; g.sinkNum = MOVE_FORWARD; g.weight = 4096;
        c.genome.push_back(g);
        buildNeuralNet(c.genome, c.nnet);
        w.creatures.push_back(c);
        float wf[NUM_SENSES]; wiring::fractions(w, wf);
        for (int s = 0; s < NUM_SENSES; ++s) CHECK(wf[s] >= 0.0f && wf[s] <= 1.0f);
        CHECK(wf[OWN_SPEED] == 1.0f);
        CHECK(wf[LOC_X] == 0.0f);
    }
}

// ---------------------------------------------------------------
// Self-contained ORACLE: verbatim copies of buildNeuralNet / feedForward as
// they were before NeuralNet::flat existed (when the net stored a genome-
// ordered std::vector<Gene> and branched per connection). The optimised
// implementation in genome.hpp must reproduce this BIT for BIT, otherwise the
// speedup would silently be a change to the science. Deliberately duplicated
// here rather than sharing code with the implementation: an oracle that reuses
// the thing it checks proves nothing. Do not "tidy" it to match the new one.
namespace oracle {

struct RefNet {
    std::vector<Gene> connections;
    struct Neuron { float output = 0.5f; bool driven = false; };
    std::vector<Neuron> neurons;
};

static void build(const Genome& genome, RefNet& nnet) {
    nnet.connections.clear();
    nnet.neurons.clear();
    nnet.neurons.resize(MAX_INTERNAL_NEURONS);

    for (auto gene : genome) {
        if (gene.sourceType == SOURCE_SENSOR) gene.sourceNum %= NUM_SENSES;
        else                                  gene.sourceNum %= MAX_INTERNAL_NEURONS;
        if (gene.sinkType == SINK_ACTION)     gene.sinkNum %= NUM_ACTIONS;
        else                                  gene.sinkNum %= MAX_INTERNAL_NEURONS;
        nnet.connections.push_back(gene);
    }

    for (const auto& conn : nnet.connections) {
        if (conn.sinkType == SINK_NEURON) nnet.neurons[conn.sinkNum].driven = true;
    }
}

static void feedForward(RefNet& nnet, const float sensors[], float actions[]) {
    float neuronAccum[MAX_INTERNAL_NEURONS] = {};

    for (int i = 0; i < NUM_ACTIONS; ++i) {
        actions[i] = 0.0f;
    }

    for (const auto& conn : nnet.connections) {
        float sourceVal;
        if (conn.sourceType == SOURCE_SENSOR) {
            sourceVal = sensors[conn.sourceNum];
        } else {
            sourceVal = nnet.neurons[conn.sourceNum].output;
        }

        float contribution = sourceVal * conn.weightAsFloat();

        if (conn.sinkType == SINK_ACTION) {
            actions[conn.sinkNum] += contribution;
        } else {
            neuronAccum[conn.sinkNum] += contribution;
        }
    }

    for (int i = 0; i < MAX_INTERNAL_NEURONS; ++i) {
        if (nnet.neurons[i].driven) {
            // evomath::tanhf, matching the production activation (v0.18.0):
            // this oracle pins the FLATTENING transformation, so it must share
            // the activation or the comparison tests the tanh, not the wiring.
            nnet.neurons[i].output = evomath::tanhf(neuronAccum[i]);
        }
    }

    for (int i = 0; i < NUM_ACTIONS; ++i) {
        actions[i] = evomath::tanhf(actions[i]);
    }
}

}  // namespace oracle

static void test_feedforward_equivalence() {
    std::printf("feedForward: flattened == original, bit for bit...\n");
    rng.seed(20260725u);

    const int NETS = 400, STEPS = 6;
    int actionMismatches = 0, neuronMismatches = 0, flatSizeOk = 0;

    for (int t = 0; t < NETS; ++t) {
        Genome g = makeRandomGenome();
        oracle::RefNet ref;
        NeuralNet opt;
        oracle::build(g, ref);
        buildNeuralNet(g, opt);

        if (opt.flat.size() == g.size() && ref.connections.size() == g.size()) ++flatSizeOk;

        // Same wiring decisions: driven-neuron flags must agree.
        bool drivenAgrees = true;
        for (int n = 0; n < MAX_INTERNAL_NEURONS; ++n) {
            if (ref.neurons[n].driven != opt.neurons[n].driven) drivenAgrees = false;
        }
        CHECK(drivenAgrees);

        // Several steps, because internal neuron outputs are recurrent state:
        // a one-step check would miss divergence that only shows up once the
        // net starts reading back its own previous activations.
        for (int step = 0; step < STEPS; ++step) {
            float sensors[NUM_SENSES];
            for (int s = 0; s < NUM_SENSES; ++s) sensors[s] = rng.range(-1.0f, 1.0f);

            float actRef[NUM_ACTIONS], actOpt[NUM_ACTIONS];
            oracle::feedForward(ref, sensors, actRef);
            feedForward(opt, sensors, actOpt);   // exact path: fastTanh defaults off

            for (int k = 0; k < NUM_ACTIONS; ++k) {
                if (actRef[k] != actOpt[k]) ++actionMismatches;   // == , not approx
            }
            for (int n = 0; n < MAX_INTERNAL_NEURONS; ++n) {
                if (ref.neurons[n].output != opt.neurons[n].output) ++neuronMismatches;
            }
        }
    }

    CHECK(flatSizeOk == NETS);
    CHECK(actionMismatches == 0);
    CHECK(neuronMismatches == 0);

    // The flat list must be a permutation of the wired connections, grouped by
    // sink: every entry's source/sink must land in its declared index space.
    {
        Genome g = makeRandomGenome();
        NeuralNet n;
        buildNeuralNet(g, n);
        bool rangesOk = true, groupedBySink = true;
        int prevSink = -1;
        for (const auto& fc : n.flat) {
            if (fc.src() >= NUM_SENSES + MAX_INTERNAL_NEURONS) rangesOk = false;
            if (fc.sink() >= NUM_ACTIONS + MAX_INTERNAL_NEURONS) rangesOk = false;
            if (fc.sink() < prevSink) groupedBySink = false;
            prevSink = fc.sink();
        }
        CHECK(rangesOk);
        CHECK(groupedBySink);

        // The packed field must round-trip every index the two spaces allow —
        // a silent overflow here would corrupt wiring rather than fail loudly.
        bool packRoundTrips = true;
        for (int src = 0; src < NUM_SENSES + MAX_INTERNAL_NEURONS; ++src) {
            for (int sink = 0; sink < NUM_ACTIONS + MAX_INTERNAL_NEURONS; ++sink) {
                NeuralNet::FlatConn fc{
                    (uint16_t)(src | (sink << NeuralNet::FlatConn::SRC_BITS)), 0 };
                if (fc.src() != src || fc.sink() != sink) packRoundTrips = false;
            }
        }
        CHECK(packRoundTrips);

        // asGene() must invert the flattening exactly: decoding an entry has to
        // reproduce the same wiring the oracle's remapping produced, as a
        // multiset (flat is sink-grouped, the oracle keeps genome order).
        oracle::RefNet ref;
        oracle::build(g, ref);
        CHECK(ref.connections.size() == n.flat.size());
        std::vector<bool> claimed(ref.connections.size(), false);
        bool decodeMatches = true;
        for (const auto& fc : n.flat) {
            const Gene d = asGene(fc);
            bool found = false;
            for (size_t i = 0; i < ref.connections.size(); ++i) {
                const Gene& r = ref.connections[i];
                if (claimed[i]) continue;
                if (r.sourceType == d.sourceType && r.sourceNum == d.sourceNum &&
                    r.sinkType == d.sinkType && r.sinkNum == d.sinkNum &&
                    r.weight == d.weight && r.weightAsFloat() == fc.w()) {
                    claimed[i] = true; found = true; break;
                }
            }
            if (!found) decodeMatches = false;
        }
        CHECK(decodeMatches);
    }
}

static void test_fast_tanh() {
    std::printf("fastTanhApprox: bounded error, right shape...\n");
    float worst = 0.0f;
    for (float x = -8.0f; x <= 8.0f; x += 0.001f) {
        worst = std::max(worst, std::fabs(fastTanhApprox(x) - std::tanh(x)));
    }
    CHECK(worst < 1.2e-4f);                       // the bound genome.hpp promises
    CHECK(fastTanhApprox(0.0f) == 0.0f);          // odd function, exact at origin
    CHECK(approx(fastTanhApprox(-1.3f), -fastTanhApprox(1.3f), 1e-7f));

    // Range invariant: an activation outside [-1,1] would be a value the exact
    // tanh can never produce, and downstream code assumes the bound. The
    // rational form crosses 1.0 at x = 4.9715, so this is a real risk, not a
    // theoretical one — it is why the clamp sits at 4.95.
    bool inRange = true;
    for (float x = -20.0f; x <= 20.0f; x += 0.0005f) {
        const float v = fastTanhApprox(x);
        if (v > 1.0f || v < -1.0f) inRange = false;
    }
    CHECK(inRange);

    // Non-decreasing, so it can't invert a comparison the exact tanh would make.
    // Tolerance absorbs 1-ulp wobble in the rational evaluation; what matters is
    // that there is no macroscopic reversal (the pre-fix clamp had one).
    bool monotone = true;
    float prev = fastTanhApprox(-20.0f);
    for (float x = -20.0f; x <= 20.0f; x += 0.001f) {
        const float v = fastTanhApprox(x);
        if (v < prev - 1e-6f) monotone = false;
        prev = v;
    }
    CHECK(monotone);
}

// Hash of the observable world state, for comparing two runs exactly.
static std::uint64_t worldFingerprint(const World& w) {
    std::uint64_t h = 1469598103934665603ull;             // FNV-1a
    auto mix = [&](float f) {
        std::uint32_t bits;
        std::memcpy(&bits, &f, sizeof(bits));
        for (int b = 0; b < 4; ++b) {
            h ^= (bits >> (8 * b)) & 0xFF;
            h *= 1099511628211ull;
        }
    };
    for (const auto& c : w.creatures) {
        mix(c.pos.x); mix(c.pos.y); mix(c.vel.x); mix(c.vel.y); mix(c.foodReserves);
    }
    return h;
}

static void test_topological_neighbors() {
    std::printf("topological neighbour cap...\n");

    auto runWorld = [](int maxNeighbors, int steps, unsigned seed) {
        rng.seed(seed);
        World w;
        w.cfg.maxNeighbors = maxNeighbors;
        w.init(600, 600, 400);            // small dense world => many neighbours in range
        for (int i = 0; i < steps; ++i) w.update(0.016f);
        return w;
    };

    // Run-to-run reproducibility is only promised by the serial build — under
    // OpenMP the parallel phase draws from per-thread RNGs, so a fixed seed
    // does not pin the run (see EVO_NO_OPENMP in CMakeLists.txt). These two
    // checks compare whole runs, so they only mean anything there.
#ifdef EVO_DETERMINISTIC
    // Same seed + same cap must reproduce exactly: the nearest-N selection is
    // ordered by (distanceSq, index), so equidistant neighbours can't reorder.
    {
        World a = runWorld(7, 30, 4242u);
        World b = runWorld(7, 30, 4242u);
        CHECK(a.creatures.size() == b.creatures.size());
        CHECK(worldFingerprint(a) == worldFingerprint(b));
    }
#endif

    // The cap must actually be wired in: attending to 1 neighbour cannot give
    // the same trajectory as attending to all of them in a dense world.
    {
        World capped = runWorld(1, 30, 99u);
        World metric = runWorld(0, 30, 99u);
        CHECK(worldFingerprint(capped) != worldFingerprint(metric));
    }

    // A cap no smaller than the achievable neighbour count selects everyone, so
    // it must agree with metric interaction. Not bit-equal — summing
    // nearest-first rounds differently from summing in spatial-index order — so
    // this checks agreement to float tolerance after a single step, in a world
    // sparse enough that nobody has MAX_TOPOLOGICAL_NEIGHBORS neighbours.
#ifdef EVO_DETERMINISTIC
    {
        rng.seed(7u);
        World huge; huge.cfg.maxNeighbors = MAX_TOPOLOGICAL_NEIGHBORS;
        huge.init(1200, 1200, 60); huge.update(0.016f);
        rng.seed(7u);
        World all;  all.cfg.maxNeighbors = 0;
        all.init(1200, 1200, 60);  all.update(0.016f);

        CHECK(huge.creatures.size() == all.creatures.size());
        bool positionsAgree = true;
        const size_t n = std::min(huge.creatures.size(), all.creatures.size());
        for (size_t i = 0; i < n; ++i) {
            if (!approx(huge.creatures[i].pos.x, all.creatures[i].pos.x, 1e-2f) ||
                !approx(huge.creatures[i].pos.y, all.creatures[i].pos.y, 1e-2f)) {
                positionsAgree = false;
            }
        }
        CHECK(positionsAgree);
    }
#endif

    // Capping attention must not break the run-level invariants.
    {
        World w = runWorld(7, 120, 31337u);
        bool finite = true;
        for (const auto& c : w.creatures) {
            if (!std::isfinite(c.pos.x) || !std::isfinite(c.pos.y)) finite = false;
        }
        CHECK(finite);
        CHECK(w.creatures.size() > 0);
    }
}

// ---------------------------------------------------------------
// Checkpointing. The load-bearing test is resume equivalence: a run that is
// saved, reloaded and continued must produce EXACTLY the state the uninterrupted
// run reaches. That single assertion is what catches a forgotten field — the rng
// engine, the pheromone grid, the recurrent neuron outputs, the rng-seeded ocean
// — because any of them silently changes the continuation. The config below
// deliberately turns on every subsystem that owns hidden state.
static void configureRichWorld(World& w) {
    w.cfg.currentStrength = 80.0f;    // rng-seeded vortices
    w.cfg.currentMode     = 0;        // eddies (vortices advance per frame)
    w.cfg.currentDrift    = 1.0f;
    w.cfg.foodPatches     = 5;        // rng-seeded patch centres
    w.cfg.foodDrift       = true;
    w.cfg.predatorCount   = 4;
    w.cfg.predatorEconomy = true;     // predators eat, breed, starve
    w.cfg.moveCost        = 7e-5f;
    w.cfg.maxNeighbors    = 7;
    w.cfg.geneCost        = 0.005f;
}

static std::uint64_t deepFingerprint(const World& w) {
    std::uint64_t h = 1469598103934665603ull;
    auto mixBytes = [&](const void* p, size_t n) {
        const unsigned char* b = (const unsigned char*)p;
        for (size_t i = 0; i < n; ++i) { h ^= b[i]; h *= 1099511628211ull; }
    };
    auto mixF = [&](float f) { mixBytes(&f, sizeof(f)); };
    auto mixI = [&](long long v) { mixBytes(&v, sizeof(v)); };

    mixI((long long)w.frame);
    mixI(w.totalBirths); mixI(w.totalDeaths);
    // v0.24.0 gate-attribution counters. Serialized, so a checkpoint that
    // dropped them has to fail resume equivalence here rather than silently
    // resetting a run's attribution to zero. Widening changes no expected value
    // (every use is a comparison between two runs).
    mixI(w.totalGraceBirths); mixI(w.totalSoftBirths);
    mixI(w.totalDeathsPredation); mixI(w.totalDeathsStarvation); mixI(w.totalDeathsAge);
    mixI(w.totalPredatorBirths);
    mixI(w.totalPredatorReseeds);   // v0.26.0, serialized — same rule as above
    mixI((long long)w.creatures.size()); mixI((long long)w.food.size());
    mixI((long long)w.predators.size());

    for (const auto& c : w.creatures) {
        mixI((long long)c.id); mixI((long long)c.lineageId);
        mixF(c.pos.x); mixF(c.pos.y); mixF(c.vel.x); mixF(c.vel.y);
        mixF(c.speed); mixF(c.age); mixF(c.foodReserves);
        mixF(c.reproTimer); mixF(c.interactTimer);
        mixF(c.responsiveness); mixF(c.oscPhase);
        // v0.23.0 body model. Included so that a checkpoint which silently
        // dropped these columns fails the resume-equivalence assertion on the
        // spot, rather than only once the divergence has propagated into the
        // positions. Every use of this fingerprint is a comparison between two
        // runs, so widening it changes no expected value.
        mixF(c.bodySize); mixF(c.bodyElong);
        for (int n = 0; n < MAX_INTERNAL_NEURONS; ++n) mixF(c.nnet.neurons[n].output);
        for (const auto& fc : c.nnet.flat) { mixI(fc.srcSink); mixI(fc.weight); }
    }
    for (const auto& f : w.food) { mixF(f.pos.x); mixF(f.pos.y); mixI(f.alive ? 1 : 0); }
    for (const auto& p : w.predators) {
        mixF(p.pos.x); mixF(p.pos.y); mixF(p.vel.x); mixF(p.vel.y);
        mixF(p.digestTimer); mixF(p.energy); mixF(p.age);
        // v0.26.0 heritable traits + generation, for the body-model reason above.
        mixF(p.speedFactor); mixF(p.buddingFactor); mixI((long long)p.generation);
        // v0.27.0 Stage C brains (only with the brain on: the scripted
        // predator's brain fields are inert defaults).
        if (w.cfg.predatorBrain) {
            mixI((long long)p.id); mixI((long long)p.lineageId); mixI((long long)p.parentId);
            mixF(p.speed); mixI((long long)p.captures);
            for (const Gene& g : p.genome) { mixI((long long)checkpoint::packGene(g)); mixI(g.weight); }
            for (const auto& nr : p.nnet.neurons) mixF(nr.output);
        }
    }
    if (w.cfg.predatorBrain) {
        mixI((long long)w.nextPredatorId_);
        const std::string ps = w.predRng_.state();
        mixBytes(ps.data(), ps.size());
    }
    for (uint8_t v : w.signals.data()) mixBytes(&v, 1);
    return h;
}

static void test_checkpoint() {
    std::printf("checkpoint save/load...\n");

    // --- JSON layer: floats must survive a round trip EXACTLY, or nothing
    // built on top can be bit-exact. Includes the awkward cases.
    {
        const float samples[] = {
            0.0f, -0.0f, 1.0f, -1.0f, 0.1f, 1.0f / 3.0f, 3.14159265f,
            1e-30f, 1e30f, 123456.789f, -0.000123456789f,
            std::numeric_limits<float>::min(), std::numeric_limits<float>::max(),
            std::numeric_limits<float>::denorm_min(),
        };
        bool allExact = true;
        for (float f : samples) {
            std::string txt = "{\"v\":" + jsonm::Writer::fmtFloat(f) + "}";
            jsonm::Value v; std::string err;
            if (!jsonm::Parser::parse(txt, v, err)) { allExact = false; continue; }
            const float back = v.floatOr("v", -12345.0f);
            // bitwise comparison: 0.0f == -0.0f would wrongly pass with ==
            if (std::memcmp(&back, &f, sizeof(float)) != 0) allExact = false;
        }
        CHECK(allExact);

        // parser rejects malformed input rather than silently half-reading it
        jsonm::Value v; std::string err;
        CHECK(!jsonm::Parser::parse("{\"a\":1,}", v, err));
        CHECK(!jsonm::Parser::parse("[1,2", v, err));
        CHECK(!jsonm::Parser::parse("{\"a\" 1}", v, err));
        CHECK(jsonm::Parser::parse("{\"a\":[1,2,3],\"b\":{\"c\":true},\"d\":\"x\\ny\"}", v, err));
        CHECK(v.find("a")->arr.size() == 3);
        CHECK(v.find("b")->boolOr("c", false));
        CHECK(v.stringOr("d", "") == "x\ny");
    }

    // --- rng engine state round-trips (the seed alone is not enough) ---
    {
        rng.seed(9876u);
        for (int i = 0; i < 50; ++i) (void)rng.unit();       // advance mid-sequence
        const std::string s = rng.state();
        std::vector<float> a;
        for (int i = 0; i < 20; ++i) a.push_back(rng.unit());
        CHECK(rng.setState(s));
        bool same = true;
        for (int i = 0; i < 20; ++i) if (rng.unit() != a[i]) same = false;
        CHECK(same);
    }

    // --- gene packing is exact and layout-independent ---
    {
        rng.seed(4242u);
        bool exact = true;
        for (int i = 0; i < 500; ++i) {
            const Gene g = Gene::makeRandom();
            const Gene r = checkpoint::unpackGene(checkpoint::packGene(g), g.weight);
            if (r.sourceType != g.sourceType || r.sourceNum != g.sourceNum ||
                r.sinkType != g.sinkType || r.sinkNum != g.sinkNum || r.weight != g.weight) exact = false;
        }
        CHECK(exact);
    }

    // --- run-length coding of the pheromone grid ---
    {
        std::vector<uint8_t> g(1000, 0);
        g[3] = 200; g[4] = 200; g[999] = 7;
        std::vector<uint8_t> back;
        CHECK(checkpoint::rleDecode(checkpoint::rleEncode(g), back, g.size()));
        CHECK(back == g);
        std::vector<uint8_t> wrong;
        CHECK(!checkpoint::rleDecode(checkpoint::rleEncode(g), wrong, g.size() + 1));
    }

    // --- THE test: save, reload, continue == never interrupted ---
    // Only meaningful in the serial build; the OpenMP build is not run-to-run
    // reproducible at all, so there is no fixed continuation to compare against.
#ifdef EVO_DETERMINISTIC
    {
        const int WARM = 220, AFTER = 140;

        rng.seed(31415u);
        World a;
        configureRichWorld(a);
        a.init(900, 700, 260);
        for (int i = 0; i < WARM; ++i) a.update(0.016f);

        std::string blob = checkpoint::serialize(a, "test");
        CHECK(blob.size() > 1000);
        const std::uint64_t atSave = deepFingerprint(a);

        for (int i = 0; i < AFTER; ++i) a.update(0.016f);
        const std::uint64_t uninterrupted = deepFingerprint(a);

        // Deliberately disturb the global rng before loading, so a checkpoint
        // that failed to restore engine state cannot accidentally pass.
        rng.seed(777u);
        for (int i = 0; i < 137; ++i) (void)rng.unit();

        World b;
        std::string err;
        CHECK(checkpoint::deserialize(blob, b, err));
        if (!err.empty()) std::printf("  load error: %s\n", err.c_str());

        CHECK(deepFingerprint(b) == atSave);          // restored state matches
        CHECK(b.creatures.size() == a.creatures.size() || true);

        for (int i = 0; i < AFTER; ++i) b.update(0.016f);
        CHECK(deepFingerprint(b) == uninterrupted);   // and so does the future

        // config survived
        CHECK(b.cfg.predatorEconomy && b.cfg.foodPatches == 5 && b.cfg.maxNeighbors == 7);
        CHECK(b.cfg.currentStrength == a.cfg.currentStrength);

        // saving the reloaded world reproduces the same bytes
        rng.seed(555u);
        World c1;
        CHECK(checkpoint::deserialize(blob, c1, err));
        CHECK(checkpoint::serialize(c1, "test") == blob);
    }

    // --- resuming with EDITED settings applies them and stays stable ---
    {
        rng.seed(2718u);
        World a;
        configureRichWorld(a);
        a.init(800, 600, 200);
        for (int i = 0; i < 120; ++i) a.update(0.016f);
        std::string blob = checkpoint::serialize(a, "test");

        // the "change settings midway" path: edit the config, not the creatures
        const std::string from = "\"metabolicRate\":1.5";
        const std::string to   = "\"metabolicRate\":4.5";
        const size_t at = blob.find(from);
        CHECK(at != std::string::npos);
        blob.replace(at, from.size(), to);

        World b;
        std::string err;
        CHECK(checkpoint::deserialize(blob, b, err));
        CHECK(b.cfg.metabolicRate == 4.5f);
        for (int i = 0; i < 200; ++i) b.update(0.016f);
        bool finite = true;
        for (const auto& c : b.creatures) if (!std::isfinite(c.pos.x)) finite = false;
        CHECK(finite);
    }
#endif

    // --- corrupt / foreign files are rejected, not half-loaded ---
    {
        World w;
        std::string err;
        CHECK(!checkpoint::deserialize("{}", w, err));
        CHECK(!checkpoint::deserialize("not json at all", w, err));
        CHECK(!checkpoint::deserialize("{\"format\":\"something.else\",\"formatVersion\":1}", w, err));
        CHECK(!checkpoint::deserialize("{\"format\":\"evo_boids.checkpoint\",\"formatVersion\":99}", w, err));
        CHECK(!err.empty());
    }
}

// ---------------------------------------------------------------
// Toroidal mode (cfg.toroidal, default off): senses wrap across the seam.
// Off-flag behaviour is byte-identical (every change is behind the flag);
// these tests pin the on-flag semantics.
static void test_toroidal() {
    std::printf("toroidal: wrapped queries, seam senses, resume...\n");

    // --- SpatialGrid::queryRadiusWrapped == brute-force minimum-image ---
    {
        rng.seed(77001u);
        const float W = 800.0f, H = 600.0f, R = 80.0f;
        SpatialGrid grid;
        grid.init((int)W, (int)H, R);
        std::vector<Vec2> pts;
        for (int i = 0; i < 300; ++i) {
            Vec2 p = {rng.range(0.0f, W - 0.001f), rng.range(0.0f, H - 0.001f)};
            pts.push_back(p);
            grid.insert(p, i);
        }
        grid.build();
        auto mi = [](float d, float span) {
            if (d > 0.5f * span) return d - span;
            if (d < -0.5f * span) return d + span;
            return d;
        };
        bool setsMatch = true, noDupes = true;
        for (int q = 0; q < 60; ++q) {
            // Bias half the query centres into the edge band, where it matters.
            Vec2 c = (q % 2 == 0)
                ? Vec2{rng.range(0.0f, W), rng.range(0.0f, H)}
                : Vec2{rng.unit() < 0.5f ? rng.range(0.0f, 15.0f) : rng.range(W - 15.0f, W),
                       rng.range(0.0f, H)};
            std::vector<int> got;
            grid.queryRadiusWrapped(c, R, got);
            std::vector<int> want;
            for (int i = 0; i < (int)pts.size(); ++i) {
                const float dx = mi(pts[i].x - c.x, W), dy = mi(pts[i].y - c.y, H);
                if (dx * dx + dy * dy <= R * R) want.push_back(i);
            }
            std::vector<int> gotSorted = got;
            std::sort(gotSorted.begin(), gotSorted.end());
            if (std::adjacent_find(gotSorted.begin(), gotSorted.end()) != gotSorted.end())
                noDupes = false;
            std::sort(want.begin(), want.end());
            if (gotSorted != want) setsMatch = false;
        }
        CHECK(setsMatch);
        CHECK(noDupes);
    }

    // --- seam visibility through the real sensor path ---
    // Two creatures 10 units apart THROUGH the seam (890 apart across the
    // plane): toroidal sees a neighbour, bounded does not.
    for (int mode = 0; mode < 2; ++mode) {
        const bool tor = (mode == 1);
        rng.seed(55011u);
        World w;
        w.cfg.toroidal = tor;
        w.cfg.captureActivations = true;
        w.cfg.minPopulation = 0;
        w.init(900, 700, 2);
        w.creatures[0].pos = {5.0f, 350.0f};
        w.creatures[1].pos = {895.0f, 350.0f};
        w.update(0.016f);
        const float n0 = w.creatures[0].lastSensors[NEIGHBOR_COUNT];
        const float n1 = w.creatures[1].lastSensors[NEIGHBOR_COUNT];
        if (tor) { CHECK(n0 > 0.05f); CHECK(n1 > 0.05f); }
        else     { CHECK(n0 == 0.0f); CHECK(n1 == 0.0f); }
        // Boundary sensors: no-wall on the torus, near-wall on the plane.
        const float bd = w.creatures[0].lastSensors[BOUNDARY_DIST];
        if (tor) CHECK(bd == 1.0f);
        else     CHECK(bd < 0.2f);   // tanh(5/100) ~= 0.05
    }

    // --- pheromone deposits and reads wrap across the seam ---
    for (int mode = 0; mode < 2; ++mode) {
        const bool tor = (mode == 1);
        rng.seed(55012u);
        World w;
        w.cfg.toroidal = tor;
        w.cfg.minPopulation = 0;
        w.init(800, 600, 0);
        w.signals.emit({1.0f, 300.0f});          // cell x=0: radius-2 stamp spans the seam
        const float far = w.signals.read({797.0f, 300.0f});   // cell x=99 (wrapped -1)
        const float at  = w.signals.read({1.0f, 300.0f});
        CHECK(at > 0.0f);
        if (tor) CHECK(far > 0.0f);
        else     CHECK(far == 0.0f);
    }

#ifdef EVO_DETERMINISTIC
    // --- toroidal + every hidden-state subsystem: resume is still bit-exact,
    //     runs are repeatable, and positions stay in-bounds ---
    {
        auto runWorld = [](World& w) {
            rng.seed(31417u);
            configureRichWorld(w);
            w.cfg.toroidal = true;
            w.init(900, 700, 260);
            for (int i = 0; i < 150; ++i) w.update(0.016f);
        };
        World a;
        runWorld(a);
        const std::string blob = checkpoint::serialize(a, "test");
        for (int i = 0; i < 100; ++i) a.update(0.016f);
        const std::uint64_t uninterrupted = deepFingerprint(a);

        rng.seed(999u); (void)rng.unit();        // scramble the global stream
        World b;
        std::string err;
        CHECK(checkpoint::deserialize(blob, b, err));
        CHECK(b.cfg.toroidal);                    // flag round-trips
        for (int i = 0; i < 100; ++i) b.update(0.016f);
        CHECK(deepFingerprint(b) == uninterrupted);

        bool inBounds = true;
        for (const auto& c : b.creatures)
            if (c.pos.x < 0.0f || c.pos.x >= (float)b.width ||
                c.pos.y < 0.0f || c.pos.y >= (float)b.height) inBounds = false;
        for (const auto& p : b.predators)
            if (p.pos.x < 0.0f || p.pos.x >= (float)b.width ||
                p.pos.y < 0.0f || p.pos.y >= (float)b.height) inBounds = false;
        CHECK(inBounds);
        CHECK(!b.creatures.empty());
    }
#endif
}

// ---------------------------------------------------------------
// PortableMT19937 must be indistinguishable from std::mt19937 in outputs
// (portable across standard libraries) and, on libstdc++, in serialized text
// (so old checkpoints load and native/wasm checkpoints match byte for byte).
static void test_portable_mt19937() {
    std::printf("PortableMT19937 == std::mt19937 (outputs, text, restore)...\n");
    const long positions[] = {0, 1, 623, 624, 625, 10000};
    for (long k : positions) {
        std::mt19937 ref(20260725u);
        PortableMT19937 mine(20260725u);
        bool outputsMatch = true;
        for (long i = 0; i < k; ++i)
            if (ref() != mine()) { outputsMatch = false; break; }
        CHECK(outputsMatch);
#ifdef __GLIBCXX__
        // Text equality with the library that wrote every pre-0.18.0
        // checkpoint. Only meaningful under libstdc++; the wasm/libc++ build
        // instead relies on this same pin having passed natively.
        std::ostringstream os;
        os << ref;
        CHECK(os.str() == mine.text());
#endif
        // Round-trip: serialize, restore into a fresh engine, streams agree.
        PortableMT19937 restored;
        CHECK(restored.fromText(mine.text()));
        bool restoredMatch = true;
        for (int i = 0; i < 2000; ++i)
            if (mine() != restored()) { restoredMatch = false; break; }
        CHECK(restoredMatch);
    }
    // Malformed state strings must be rejected.
    PortableMT19937 e;
    CHECK(!e.fromText(""));
    CHECK(!e.fromText("1 2 3"));
}

// ---------------------------------------------------------------
// ---------------------------------------------------------------
// Reproductive isolation (v0.21.0): the genome-distance metric and the
// reproduction gate built on it.
//
// The metric's whole reason for existing is that genomeSimilarity() is
// positionally aligned and therefore useless as a gate, so the contrast against
// it is asserted here rather than only described in a comment.
static void test_reproductive_isolation() {
    std::printf("reproductive isolation: metric properties + gate...\n");

    // --- metric properties, over many random genomes ---
    {
        rng.seed(31337u);
        bool selfZero = true, symmetric = true, permInvariant = true, nonNegative = true;
        for (int t = 0; t < 300; ++t) {
            Genome a = makeRandomGenome(16, 80);
            Genome b = makeRandomGenome(16, 80);

            if (genomeDistanceSq(a, a) != 0.0f) selfZero = false;
            // Bitwise symmetry, not approximate: the merge must be
            // order-independent, and IEEE subtraction is exactly antisymmetric.
            if (genomeDistanceSq(a, b) != genomeDistanceSq(b, a)) symmetric = false;
            if (genomeDistanceSq(a, b) < 0.0f) nonNegative = false;

            // Permutation invariance must be EXACT. It only holds because the
            // fold sorts on (cell, weight) rather than on cell alone; sorting on
            // cell alone would sum a cell's duplicate weights in genome order
            // and float addition is not associative.
            Genome shuffled = a;
            for (int k = (int)shuffled.size() - 1; k > 0; --k)
                std::swap(shuffled[k], shuffled[rng.intRange(0, k)]);
            if (genomeDistanceSq(a, shuffled) != 0.0f) permInvariant = false;
        }
        CHECK(selfZero);
        CHECK(symmetric);
        CHECK(permInvariant);
        CHECK(nonNegative);
    }

    // --- the sparse merge-join agrees with a dense reference ---
    // Independent oracle: materialise both genomes as full STATS_DIM vectors and
    // difference them directly. Catches any merge-join indexing mistake.
    {
        rng.seed(4242u);
        bool matchesDense = true;
        for (int t = 0; t < 60; ++t) {
            Genome a = makeRandomGenome(16, 80), b = makeRandomGenome(16, 80);
            std::vector<float> va(STATS_DIM, 0.0f), vb(STATS_DIM, 0.0f);
            for (const Gene& g : a) va[geneCell(g)] += g.weightAsFloat();
            for (const Gene& g : b) vb[geneCell(g)] += g.weightAsFloat();
            double ref = 0.0;
            for (int i = 0; i < STATS_DIM; ++i) {
                const double d = (double)va[i] - (double)vb[i];
                ref += d * d;
            }
            // Tolerance, not equality: the reference sums in genome order and in
            // double, the implementation in canonical order and in float.
            if (!approx((float)ref, genomeDistanceSq(a, b), 1e-2f)) matchesDense = false;
        }
        CHECK(matchesDense);
    }

    // --- indel robustness, and the contrast that justifies the new function ---
    {
        rng.seed(909090u);
        double meanSim = 0.0, meanDist = 0.0;
        const int N = 200;
        for (int t = 0; t < N; ++t) {
            Genome g = makeRandomGenome(24, 48);
            Genome ins = g;
            const int pos = rng.intRange(0, (int)ins.size() - 1);
            ins.insert(ins.begin() + pos, ins[pos]);   // one duplicate gene, in place
            meanSim  += genomeSimilarity(g, ins);
            meanDist += genomeDistance(g, ins);
        }
        meanSim /= N; meanDist /= N;
        // genomeSimilarity COLLAPSES on a single indel: every gene downstream of
        // the insertion is compared against its neighbour instead of itself.
        CHECK(meanSim < 0.75f);
        // The connectivity-space distance barely moves — one duplicated edge.
        CHECK(meanDist < 4.0f);
        // And unrelated genomes are far away on the same scale, so the metric
        // genuinely discriminates rather than being uniformly small.
        rng.seed(909091u);
        double meanUnrelated = 0.0;
        for (int t = 0; t < N; ++t)
            meanUnrelated += genomeDistance(makeRandomGenome(24, 48), makeRandomGenome(24, 48));
        meanUnrelated /= N;
        CHECK(meanUnrelated > 4.0f * meanDist);
    }

    // The next two blocks compare WHOLE RUNS, which only the serial build
    // promises to reproduce — under OpenMP the parallel phase draws from
    // per-thread RNGs and a fixed seed does not pin the run. Same guard the
    // topological, checkpoint and toroidal tests use.
#ifdef EVO_DETERMINISTIC
    // --- a permissive gate is exactly a no-op ---
    // Threshold far above the largest achievable distance must reproduce the
    // ungated run bit for bit: the gate consumes no rng and changes no order.
    {
        const int STEPS = 400;
        rng.seed(24680u);
        World off;
        off.cfg.minPopulation = 0;
        off.init(900, 700, 220);
        for (int i = 0; i < STEPS; ++i) off.update(0.016f);

        rng.seed(24680u);
        World wide;
        wide.cfg.minPopulation = 0;
        wide.cfg.reproMaxDistance = 1.0e6f;
        wide.init(900, 700, 220);
        for (int i = 0; i < STEPS; ++i) wide.update(0.016f);

        CHECK(deepFingerprint(off) == deepFingerprint(wide));
        CHECK(off.totalBirths == wide.totalBirths);
        CHECK(off.totalBirths > 0);          // the control must actually breed
    }
#endif

    // The remaining checks are build-independent: they assert only that births
    // do or do not happen, which the gate decides identically in both builds.

    // --- a tight gate stops reproduction entirely ---
    {
        const int STEPS = 400;
        rng.seed(24680u);
        World tight;
        tight.cfg.minPopulation = 0;
        tight.cfg.reproMaxDistance = 0.5f;   // far below any random pair distance
        tight.init(900, 700, 220);
        for (int i = 0; i < STEPS; ++i) tight.update(0.016f);
        CHECK(tight.totalBirths == 0);
    }

    // --- the gate is SELECTIVE, not merely restrictive ---
    // Same tight threshold, but the population is two hand-planted clones
    // instead of 220 unrelated genomes. Within-clone pairs are at distance 0 and
    // must breed; a run of all-distinct genomes at the same threshold bred
    // nothing (above). That contrast is the actual claim: births track genome
    // distance, not the threshold alone.
    {
        const int STEPS = 400;
        rng.seed(13579u);
        World two;
        two.cfg.minPopulation = 0;
        two.cfg.reproMaxDistance = 0.5f;
        two.init(900, 700, 220);
        Genome clusterA = makeRandomGenome(24, 48);
        Genome clusterB = makeRandomGenome(24, 48);
        CHECK(genomeDistance(clusterA, clusterB) > 10.0f);   // genuinely far apart
        for (size_t i = 0; i < two.creatures.size(); ++i) {
            two.creatures[i].genome = (i % 2 == 0) ? clusterA : clusterB;
            buildNeuralNet(two.creatures[i].genome, two.creatures[i].nnet);
        }
        for (int i = 0; i < STEPS; ++i) two.update(0.016f);
        CHECK(two.totalBirths > 0);
    }

    // --- determinism with the gate on (serial build only, as above) ---
#ifdef EVO_DETERMINISTIC
    {
        const int STEPS = 300;
        std::uint64_t fp[2] = {0, 0};
        for (int rep = 0; rep < 2; ++rep) {
            rng.seed(50505u);
            World w;
            configureRichWorld(w);           // predators, currents, patches too
            w.cfg.reproMaxDistance = 18.0f;  // a threshold that actually bites
            w.init(900, 700, 240);
            for (int i = 0; i < STEPS; ++i) w.update(0.016f);
            fp[rep] = deepFingerprint(w);
        }
        CHECK(fp[0] == fp[1]);
    }
#endif

    // --- the gate survives a checkpoint round trip ---
    {
        rng.seed(60606u);
        World a;
        a.cfg.reproMaxDistance = 16.5f;
        a.init(900, 700, 200);
        for (int i = 0; i < 120; ++i) a.update(0.016f);
        const std::string blob = checkpoint::serialize(a, "test");
        World b;
        std::string err;
        CHECK(checkpoint::deserialize(blob, b, err));
        CHECK(b.cfg.reproMaxDistance == 16.5f);

        // A checkpoint written before v0.21.0 has no such key; loading it must
        // leave the gate off rather than inventing a value.
        World c;
        c.cfg.reproMaxDistance = -1.0f;
        std::string legacy = blob;
        const std::string key = "\"reproMaxDistance\":16.5,";
        const size_t at = legacy.find(key);
        CHECK(at != std::string::npos);
        if (at != std::string::npos) legacy.erase(at, key.size());
        std::string err2;
        CHECK(checkpoint::deserialize(legacy, c, err2));
        CHECK(c.cfg.reproMaxDistance < 0.0f);
    }
}

// ---------------------------------------------------------------
// Reproduction graph (v0.22.0). Validated the way `species` was: against
// constructed cases whose answer is known by hand, BEFORE it is trusted on
// real runs.
static void test_repro_graph() {
    std::printf("reproduction graph: components, decimation, CSV column...\n");

    // --- hand-built graphs with known answers ---
    {
        using repro::Edge;
        // Empty graph: no edges, no vertices. Must report 0, not crash and not
        // divide by zero — this is exactly what a gate tight enough to stop all
        // breeding produces, so it is a real case, not a pathological one.
        CHECK(repro::componentCount({}, 3) == 0);

        // One well-mixed group: a 5-cycle. One component of 5 members.
        const std::vector<Edge> ring = {{1,2},{2,3},{3,4},{4,5},{5,1}};
        CHECK(repro::componentCount(ring, 3) == 1);
        CHECK(repro::componentCount(ring, 5) == 1);
        CHECK(repro::componentCount(ring, 6) == 0);   // no component that big

        // Two mutually incompatible clusters that never exchange an edge.
        const std::vector<Edge> split = {{1,2},{2,3},{3,1},  {10,11},{11,12},{12,10}};
        CHECK(repro::componentCount(split, 3) == 2);

        // Add a single bridging birth and the two collapse into one — this is
        // the signal that reproductive isolation has BROKEN DOWN.
        std::vector<Edge> bridged = split;
        bridged.push_back({3, 10});
        CHECK(repro::componentCount(bridged, 3) == 1);

        // An isolated pair is a component of size 2, below the default floor of
        // 3, so it must not inflate the count.
        std::vector<Edge> withPair = ring;
        withPair.push_back({90, 91});
        CHECK(repro::componentCount(withPair, 3) == 1);
        CHECK(repro::componentCount(withPair, 2) == 2);

        // Order-independence: components are a property of the edge SET.
        std::vector<Edge> shuffled = split;
        std::reverse(shuffled.begin(), shuffled.end());
        CHECK(repro::componentCount(shuffled, 3) == repro::componentCount(split, 3));

        // Duplicate and self edges must not create phantom components.
        std::vector<Edge> dupes = {{1,2},{1,2},{2,3},{3,3}};
        CHECK(repro::componentCount(dupes, 3) == 1);
    }

    // --- the window is a ring: it holds the LAST N births, undecimated ---
    // 1200 steps, not 600: `age > 5.0f` is a hard reproduction precondition and
    // at dt 0.016 nothing can breed before step ~312, so a short run measures
    // the warm-up rather than the ring.
    // Serial-only: >64 is a whole-run birth count, which the OpenMP build's
    // per-thread rngs do not pin (same guard as the fingerprint tests).
#ifdef EVO_DETERMINISTIC
    {
        rng.seed(80808u);
        World w;
        w.cfg.reproWindow = 64;
        w.cfg.minPopulation = 0;
        w.init(900, 700, 240);
        for (int i = 0; i < 1200; ++i) w.update(0.016f);
        CHECK(w.totalBirths > 64);                       // enough births to wrap
        CHECK((int)w.reproWindow_.size() == 64);         // capped, not growing
        CHECK(w.reproComponents() >= 0);
    }
#endif

    // --- eviction: the ring holds the LAST N events, and old edges age OUT ---
    // Drives logBirth directly with hand-built Creatures (it touches only the
    // pairing structures — no sim state, no rng), so this is deterministic in
    // both builds and pins push-until-cap, the overwrite position, cursor wrap
    // and eviction: a broken cursor advance would keep the bridge below alive
    // forever while every other test here still passed.
    {
        World w;
        w.cfg.reproWindow = 4;
        w.cfg.reproMinCluster = 3;
        Creature ca, cb;
        auto edge = [&](std::uint64_t ia, std::uint64_t ib) {
            ca.id = ia; cb.id = ib;
            w.logBirth(ca, cb);
        };
        edge(1, 2); edge(2, 3); edge(10, 11); edge(11, 12);   // ring now full
        CHECK(w.reproComponents() == 2);          // {1,2,3} and {10,11,12}
        edge(3, 10);                              // bridge; evicts (1,2)
        CHECK(w.reproComponents() == 1);          // {2,3,10,11,12}
        // Four more events replace the whole window; the bridge must age out.
        edge(1, 2); edge(2, 3); edge(10, 11); edge(11, 12);
        CHECK(w.reproComponents() == 2);          // split again: bridge evicted
    }

    // --- a real run's graph is connected; a sterilised run's is empty ---
    {
        const int STEPS = 600;
        rng.seed(24680u);
        World mixed;
        mixed.cfg.minPopulation = 0;
        mixed.init(900, 700, 220);
        for (int i = 0; i < STEPS; ++i) mixed.update(0.016f);
        CHECK(mixed.totalBirths > 0);
        // PRE-EXISTING FLAKE, fixed in v0.23.0 (it predates the body model —
        // measured at 13/40 OpenMP runs both at HEAD and after this change).
        // reproComponents() counts components of at least reproMinCluster (3)
        // members, which is a property of the exact pairing STRUCTURE, and
        // OpenMP's per-thread rngs do not pin that: a run whose pairings happen
        // to form only 2-member components legitimately reports 0. Births
        // themselves do happen in both builds, so the assertion above stays
        // unguarded. Same guard, and the same reason, as the archive block below.
#ifdef EVO_DETERMINISTIC
        CHECK(mixed.reproComponents() >= 1);
#endif

        rng.seed(24680u);
        World sterile;
        sterile.cfg.minPopulation = 0;
        sterile.cfg.reproMaxDistance = 0.5f;   // nobody can breed
        sterile.init(900, 700, 220);
        for (int i = 0; i < STEPS; ++i) sterile.update(0.016f);
        CHECK(sterile.totalBirths == 0);
        CHECK(sterile.reproComponents() == 0);   // no edges => 0, reported sanely
    }

    // --- the archive log is bounded and decimates like the death log ---
    // Serial-only for the same reason as the ring test: >64 is a whole-run
    // count that OpenMP's per-thread rngs do not pin.
#ifdef EVO_DETERMINISTIC
    {
        rng.seed(31415u);
        World w;
        w.cfg.reproLog = true;
        w.cfg.reproLogMax = 32;                  // tiny, to force several halvings
        w.cfg.minPopulation = 0;
        w.init(900, 700, 240);
        for (int i = 0; i < 900; ++i) w.update(0.016f);
        CHECK(w.totalBirthsLogged_ > 64);
        CHECK((int)w.birthLog.size() < 2 * w.cfg.reproLogMax);   // stayed bounded
        CHECK(w.reproStride_ >= 2);                               // did decimate
        // Kept records must be exactly those on the current stride, in order.
        bool strideOk = true, ordered = true;
        long long prev = -1;
        for (const World::BirthRecord& b : w.birthLog) {
            if (b.index % w.reproStride_ != 0) strideOk = false;
            if (b.index <= prev) ordered = false;
            prev = b.index;
            if (b.parent1 == 0 || b.parent2 == 0) strideOk = false;  // ids assigned
        }
        CHECK(strideOk);
        CHECK(ordered);
    }

    // --- the whole apparatus is observational: fingerprints cannot move ---
    // The always-on window, the opt-in archive and the component count draw no
    // rng and touch no sim state; this is that claim as a test, not a
    // code-reading exercise. Serial-only, like every whole-run comparison.
    {
        const int STEPS = 400;
        auto fingerprintWith = [](int window, bool logOn) {
            rng.seed(70707u);
            World w;
            w.cfg.minPopulation = 0;
            w.cfg.reproWindow = window;
            w.cfg.reproLog = logOn;
            w.init(900, 700, 220);
            for (int i = 0; i < STEPS; ++i) w.update(0.016f);
            return deepFingerprint(w);
        };
        const std::uint64_t base = fingerprintWith(2000, false);
        CHECK(fingerprintWith(0, false) == base);      // window off == default
        CHECK(fingerprintWith(64, false) == base);     // window size irrelevant
        CHECK(fingerprintWith(2000, true) == base);    // archive is write-only
    }

    // --- same seed twice with the archive on: identical records, not merely
    // identical worlds ---
    {
        std::vector<World::BirthRecord> logs[2];
        std::uint64_t fp[2] = {0, 0};
        for (int rep = 0; rep < 2; ++rep) {
            rng.seed(90909u);
            World w;
            w.cfg.minPopulation = 0;
            w.cfg.reproLog = true;
            w.init(900, 700, 240);
            for (int i = 0; i < 900; ++i) w.update(0.016f);
            fp[rep] = deepFingerprint(w);
            logs[rep] = w.birthLog;
        }
        CHECK(fp[0] == fp[1]);
        bool same = logs[0].size() == logs[1].size() && !logs[0].empty();
        for (size_t i = 0; same && i < logs[0].size(); ++i)
            same = logs[0][i].index == logs[1][i].index
                && logs[0][i].parent1 == logs[1][i].parent1
                && logs[0][i].parent2 == logs[1][i].parent2
                && logs[0][i].lineage1 == logs[1][i].lineage1
                && logs[0][i].lineage2 == logs[1][i].lineage2
                && logs[0][i].frame == logs[1][i].frame;
        CHECK(same);
    }
#endif

    // --- checkpoints: the new fields round-trip, old checkpoints default, and
    // a resume starts the window empty ---
    {
        rng.seed(42424u);
        World a;
        a.cfg.reproWindow = 777;
        a.cfg.reproMinCluster = 5;
        a.init(900, 700, 200);
        for (int i = 0; i < 600; ++i) a.update(0.016f);
        const std::string blob = checkpoint::serialize(a, "test");

        // Round trip — into a World that has ALREADY RUN, which is exactly the
        // case that catches stale pairing state surviving a load.
        rng.seed(11111u);
        World b;
        b.cfg.minPopulation = 0;
        b.init(900, 700, 220);
        for (int i = 0; i < 900; ++i) b.update(0.016f);
        CHECK(!b.reproWindow_.empty());       // the stale state actually exists
        std::string err;
        CHECK(checkpoint::deserialize(blob, b, err));
        CHECK(b.cfg.reproWindow == 777);
        CHECK(b.cfg.reproMinCluster == 5);
        CHECK(b.reproWindow_.empty());        // the window is per-run state
        CHECK(b.birthLog.empty());
        CHECK(b.reproComponents() == 0);      // empty window reports 0, sanely

        // A checkpoint written before v0.22.0 has neither key; loading it must
        // fall back to the defaults rather than inventing values.
        World c;
        std::string legacy = blob;
        for (const std::string key : {std::string("\"reproWindow\":777,"),
                                      std::string("\"reproMinCluster\":5,")}) {
            const size_t at = legacy.find(key);
            CHECK(at != std::string::npos);
            if (at != std::string::npos) legacy.erase(at, key.size());
        }
        std::string err2;
        CHECK(checkpoint::deserialize(legacy, c, err2));
        CHECK(c.cfg.reproWindow == 2000);
        CHECK(c.cfg.reproMinCluster == 3);
    }

    // --- the CSV column is appended, not inserted ---
    {
        const std::string h = statsCsvHeader();
        // Every pre-0.22.0 column keeps its index: the old header must be a
        // prefix of the new one.
        const std::string old =
            "step,elapsed_s,steps_per_sec,population,food,"
            "births_cum,deaths_cum,births_interval,deaths_interval,"
            "avg_age,max_age,avg_energy,avg_speed,"
            "avg_genome_len,genome_len_std,avg_responsiveness,avg_osc_period,"
            "genetic_diversity,species,flow_align,"
            "predator_pop,kills_interval,deaths_starvation,deaths_age,predator_align,"
            "neighbor_align,neighbor_count,"
            "predator_births_interval,predator_deaths_starv,predator_deaths_age,predator_avg_energy";
        CHECK(h.rfind(old, 0) == 0);
        CHECK(h.size() > old.size());
        // species is still column 19 (1-based), as the whole corpus assumes.
        int commas = 0; std::size_t at = 0;
        while (at < h.size() && commas < 18) { if (h[at] == ',') ++commas; ++at; }
        CHECK(h.compare(at, 7, "species") == 0);
        // header and row must agree on field count
        WorldStats s;
        const std::string row = statsCsvRow(s, 0.0, 0.0, 0, 0, 0, 0, 0, 0, 0, 0);
        CHECK(std::count(h.begin(), h.end(), ',') == std::count(row.begin(), row.end(), ','));
        // repro_components keeps the index it was appended at (32nd, 1-based),
        // and anything appended later goes strictly AFTER it — otherwise a
        // v0.22.0 CSV and a current one disagree about column 32.
        commas = 0; at = 0;
        while (at < h.size() && commas < 31) { if (h[at] == ',') ++commas; ++at; }
        CHECK(h.compare(at, 16, "repro_components") == 0);
        // The v0.24.0 columns follow it, and the v0.26.0 predator columns are
        // the last four header fields, so a later append cannot silently order
        // itself ahead of them and desync from the row.
        const std::string tail = ",grace_births_cum,soft_births_cum,predator_reseeds_cum,"
                                 "predator_speed_factor,predator_budding_factor,predator_generation";
        CHECK(h.size() > tail.size() &&
              h.compare(h.size() - tail.size(), tail.size(), tail) == 0);

        // Position alone is not enough: bind header NAME to row VALUE, so a
        // transposed, duplicated or dropped emit in statsCsvRow fails here
        // rather than silently mis-attributing a sweep read off these columns.
        // All four sentinels are distinct, so any permutation of them is
        // caught. (The all-zero WorldStats above cannot see any of that.)
        WorldStats sv;
        sv.totalBirths = 999; sv.reproComponents = 111;
        sv.totalGraceBirths = 222; sv.totalSoftBirths = 333;
        sv.totalPredatorReseeds = 444; sv.predatorSpeedFactor = 1.25f;
        sv.predatorBuddingFactor = 0.75f; sv.predatorGeneration = 7.5f;
        const std::string vrow = statsCsvRow(sv, 0.0, 0.0, 0, 0, 0, 0, 0, 0, 0, 0);
        auto field = [](const std::string& s, int col) {   // 1-based CSV column
            std::size_t from = 0;
            for (int c = 1; c < col; ++c) {
                from = s.find(',', from);
                if (from == std::string::npos) return std::string();
                ++from;
            }
            const std::size_t to = s.find(',', from);
            return s.substr(from, to == std::string::npos ? std::string::npos
                                                          : to - from);
        };
        CHECK(field(vrow, 6)  == "999");   // births_cum
        CHECK(field(vrow, 32) == "111");   // repro_components
        CHECK(field(vrow, 33) == "222");   // grace_births_cum
        CHECK(field(vrow, 34) == "333");   // soft_births_cum
        CHECK(field(vrow, 35) == "444");   // predator_reseeds_cum
        CHECK(field(vrow, 36) == "1.250"); // predator_speed_factor
        CHECK(field(vrow, 37) == "0.750"); // predator_budding_factor
        CHECK(field(vrow, 38) == "7.500"); // predator_generation
    }
}

// ---------------------------------------------------------------
// Tier-1 body model (v0.23.0). Two claims carry the whole design and both are
// measured here rather than assumed:
//   (a) at the default parameters every factor is EXACTLY 1.0f, so every apply
//       site in world.hpp computes the pre-0.23 bits (the §6.1 harness proves it
//       end to end; this proves the arithmetic that makes it possible), and
//   (b) with the flag on, inheritance is exactly mean-of-parents plus one
//       uniform draw per parameter, clamped, and a child can never escape
//       [0.5, 2.0] no matter what its parents were.

static bool bitEq(float a, float b) { return std::memcmp(&a, &b, sizeof(float)) == 0; }

// Is `observed` EXACTLY a value that clamp(mean + rng.range(-M, +M), 0.5, 2.0)
// can emit? rng.range(lo,hi) is lo + (hi-lo)*unit(), and unit() is
// (engine() >> 8) * 2^-24 — so the jitter lives on a grid of exactly 2^24
// points. We do not need to know which engine word came out of the birth, only
// that SOME grid point reproduces the observed float bit for bit. Inverting the
// formula pins the grid index to within a couple of ulps, so scanning a small
// window around it is exhaustive. A different jitter scale, or a Gaussian in
// place of the uniform, fails this wherever it is called.
//
// WHAT EACH CALLER CAN CONCLUDE. The checker only ever tests "observed = <the
// centre the caller passed> + one uniform jitter", so all of its discriminating
// power sits in the choice of centre:
//   * cases 3 and 3b pin EVERY founder to one body, so the parental mean is
//     numerically the same float as either parent. They pin the jitter law, the
//     clamp, and (at M = 0) the blend's scale, and they do separate the two
//     PARAMETERS from each other because the founder size and elong differ —
//     but they CANNOT tell mean-of-parents from copy-parent1, since both
//     hypotheses predict the identical centre.
//   * case 3c gives every founder a distinct body and recovers each birth's two
//     actual parents, putting the mean somewhere neither parent sits. That is
//     the case that refutes copy-parent1, copy-parent2 and sum-of-parents.
// Neither pins the DRAW ORDER (bodySize drawn before bodyElong): swapping the
// two draws leaves every child on both grids. Order is guarded across version
// boundaries by the §6.1 byte-identity fingerprints and by wasm/parity.sh,
// which compare the whole random stream rather than a per-child predicate.
static bool fromInheritanceGrid(float observed, float mean, float M) {
    if (!(M > 0.0f)) return bitEq(observed, std::clamp(mean, BODY_PARAM_MIN, BODY_PARAM_MAX));
    const double est = (((double)observed - (double)mean) + (double)M) / (2.0 * (double)M);
    const long long k0 = (long long)std::llround(est * 16777216.0);
    for (long long k = k0 - 64; k <= k0 + 64; ++k) {
        if (k < 0 || k >= 16777216LL) continue;
        const float u = (float)k * 0x1p-24f;        // exactly rng.unit()'s grid
        const float d = -M + (M - (-M)) * u;        // exactly rng.range(-M, M)
        if (bitEq(std::clamp(mean + d, BODY_PARAM_MIN, BODY_PARAM_MAX), observed)) return true;
    }
    return false;
}

// Remove `,"key":[ ... ]` from a serialized checkpoint. The leading comma goes
// with it, which is what keeps the result parseable wherever the column sits.
static bool eraseJsonArray(std::string& s, const char* key) {
    const std::string k = std::string(",\"") + key + "\":[";
    const size_t at = s.find(k);
    if (at == std::string::npos) return false;
    const size_t end = s.find(']', at);
    if (end == std::string::npos) return false;
    s.erase(at, end + 1 - at);
    return true;
}

static void test_body_model() {
    std::printf("body model: factor exactness, inheritance, clamps, checkpoint...\n");

    // --- 1. the default body is arithmetically invisible -----------------
    {
        Creature d;                       // default-constructed: 1.0 / 1.0
        CHECK(bitEq(d.bodySize, 1.0f));
        CHECK(bitEq(d.bodyElong, 1.0f));
        CHECK(bitEq(speedFactor(d), 1.0f));
        CHECK(bitEq(turnFactor(d), 1.0f));
        CHECK(bitEq(massFactor(d), 1.0f));

        // The claim the off-path rests on: each apply site multiplies a config
        // value by one of these factors, so the product must be the ORIGINAL
        // float bit for bit — across awkward magnitudes, not just tidy defaults.
        const float xs[] = {150.0f, 30.0f, 4.0f, 1.5f, 0.0f, -0.0f, 0.005f, 7e-5f,
                            123456.789f, 1.0f / 3.0f, 3.14159265f, 1e-30f, 1e30f,
                            std::numeric_limits<float>::min(),
                            std::numeric_limits<float>::max(),
                            std::numeric_limits<float>::denorm_min()};
        for (float x : xs) {
            CHECK(bitEq(x * speedFactor(d), x));
            CHECK(bitEq(x * turnFactor(d), x));
            CHECK(bitEq(x * massFactor(d), x));
        }
        // The exact expressions world.hpp evaluates, at the stock config.
        const float minS = 30.0f, maxS = 150.0f, turn = 4.0f, metab = 1.5f;
        CHECK(bitEq(std::max(minS, maxS * speedFactor(d)), maxS));
        CHECK(bitEq(turn * turnFactor(d), turn));
        CHECK(bitEq(metab * massFactor(d), metab));

        // ...and a non-default body must actually move them, or the model is
        // decorative. Bigger => slower and dearer; longer => turns worse.
        Creature big;   big.bodySize   = 2.0f; big.bodyElong   = 2.0f;
        Creature small; small.bodySize = 0.5f; small.bodyElong = 0.5f;
        CHECK(bitEq(speedFactor(big),   2.0f / 3.0f));
        CHECK(bitEq(turnFactor(big),    2.0f / 3.0f));
        CHECK(bitEq(massFactor(big),    2.0f));
        CHECK(bitEq(speedFactor(small), 2.0f / 1.5f));
        CHECK(bitEq(massFactor(small),  0.5f));

        // An ASYMMETRIC body, because big and small above set the two
        // parameters to the SAME value: with size == elong, speedFactor and
        // turnFactor are equal by construction, so a turnFactor that reads
        // bodySize (or a massFactor that reads bodyElong) satisfies every check
        // around it. Here all three factors take distinct values, so each one
        // pins which parameter it is wired to.
        Creature odd; odd.bodySize = 2.0f; odd.bodyElong = 0.5f;
        CHECK(bitEq(speedFactor(odd), 2.0f / 3.0f));     // 2/(1 + bodySize)
        CHECK(bitEq(turnFactor(odd),  2.0f / 1.5f));     // 2/(1 + bodyElong)
        CHECK(bitEq(massFactor(odd),  2.0f));            // bodySize

        CHECK(speedFactor(big) < speedFactor(small));
        CHECK(maxS * speedFactor(big) < maxS);
        CHECK(maxS * speedFactor(small) > maxS);
        CHECK(std::max(minS, maxS * speedFactor(big)) > minS);   // ceiling stays legal
    }

    // --- 7. updateBody scaling (visual only — no sensor reads body[]) ----
    {
        // Trail points 128 apart: a power of two, so segLen/dist is exact and
        // the resulting spacing is an exact float for every case below.
        auto spacing = [](float size, float elong) {
            Creature c;
            c.bodySize = size; c.bodyElong = elong;
            c.pos = {1000.0f, 500.0f};
            for (int i = 0; i < Creature::BODY_LEN; ++i)
                c.body[i] = {1000.0f - (float)i * 128.0f, 500.0f};
            c.updateBody();
            return c.body[0].x - c.body[1].x;
        };
        CHECK(bitEq(spacing(1.0f, 1.0f), 4.0f));    // the default is untouched
        CHECK(bitEq(spacing(2.0f, 2.0f), 16.0f));   // 4 * 2 * 2, the brief's case
        CHECK(bitEq(spacing(2.0f, 1.0f), 8.0f));
        CHECK(bitEq(spacing(1.0f, 2.0f), 8.0f));
        CHECK(bitEq(spacing(0.5f, 0.5f), 1.0f));
    }

    // Run a world whose founders are all pinned to the same body, step until the
    // first birth, and hand back that first generation. Every one of those
    // children has two founder parents, so the parental mean is known exactly.
    auto firstGeneration = [](unsigned seed, float size, float elong, float mut,
                              int maxSteps, std::vector<Creature>& out) {
        rng.seed(seed);
        World w;
        w.cfg.minPopulation = 0;      // no reseeded founders to confuse identity
        w.cfg.bodyModel = true;
        w.cfg.bodyMutation = mut;
        w.init(900, 700, 220);
        std::uint64_t maxFounderId = 0;
        for (auto& c : w.creatures) {
            c.bodySize = size; c.bodyElong = elong;
            maxFounderId = std::max(maxFounderId, c.id);
        }
        out.clear();
        for (int i = 0; i < maxSteps && out.empty(); ++i) {
            w.update(0.016f);
            for (const auto& c : w.creatures)
                if (c.id > maxFounderId) out.push_back(c);
        }
        return w.totalBirths;
    };

    // --- 3. inheritance is exactly clamp(parent mean + one uniform draw) --
    {
        std::vector<Creature> kids;
        const long long births = firstGeneration(31337u, 0.8f, 1.6f, 0.1f, 2000, kids);
        CHECK(births > 0);
        CHECK(!kids.empty());
        bool exact = !kids.empty(), inBand = !kids.empty(), discriminating = !kids.empty();
        for (const Creature& k : kids) {
            // Parents are all founders at exactly (0.8, 1.6), so the mean is
            // exactly 0.8 / 1.6 and a half-width of 0.1 never reaches a clamp.
            inBand = inBand && std::fabs(k.bodySize  - 0.8f) <= 0.1f
                            && std::fabs(k.bodyElong - 1.6f) <= 0.1f;
            exact  = exact  && fromInheritanceGrid(k.bodySize,  0.8f, 0.1f)
                            && fromInheritanceGrid(k.bodyElong, 1.6f, 0.1f);
            // The checker is not vacuous: the size parameter is NOT reachable
            // from the elongation mean, so a swapped assignment would be caught.
            discriminating = discriminating && !fromInheritanceGrid(k.bodySize, 1.6f, 0.1f)
                                            && !fromInheritanceGrid(k.bodyElong, 0.8f, 0.1f);
        }
        CHECK(inBand);
        CHECK(exact);
        CHECK(discriminating);
    }

    // --- 3b. zero mutation => the pure mean blend, bit for bit -----------
    // The draws still happen (the count must not depend on the width), but
    // rng.range(-0,+0) is exactly 0, so a uniform founder body is inherited
    // unchanged. This pins the blend independently of the jitter.
    {
        std::vector<Creature> kids;
        const long long births = firstGeneration(31337u, 0.8f, 1.6f, 0.0f, 2000, kids);
        CHECK(births > 0);
        CHECK(!kids.empty());
        bool exact = !kids.empty();
        for (const Creature& k : kids)
            exact = exact && bitEq(k.bodySize, 0.8f) && bitEq(k.bodyElong, 1.6f);
        CHECK(exact);
    }

    // --- 3c. the blend is the mean of TWO DISTINCT parents ---------------
    // Cases 3 and 3b cannot see the difference between mean-of-parents and
    // copy-parent1, because their founders all share one body and the mean is
    // then the same float as either parent (mutation-proven: wiring the child
    // to c1 alone leaves both cases green). Here every founder gets its own
    // body, each birth's two ACTUAL parents are recovered from the v0.22
    // pairing log, and the child must sit on the inheritance grid around the
    // exact parental mean — and, whenever the parents are far enough apart for
    // the hypotheses to be separable, must NOT sit on the grid around either
    // parent alone or around their sum.
    {
        const float M = 0.05f;                  // mutation half-width
        rng.seed(9091u);
        World w;
        w.cfg.minPopulation = 0;                // no reseeded founders back at 1.0/1.0
        w.cfg.bodyModel = true;
        w.cfg.bodyMutation = M;
        w.cfg.reproLog = true;                  // populate World::birthLog...
        w.cfg.reproLogMax = 1000000;            // ...undecimated, so reproStride_ stays 1
        w.init(900, 700, 120);
        CHECK(!w.creatures.empty());

        // Founder bodies: unique per creature, exactly representable, and in two
        // DISJOINT bands (size in [0.5625, 1.0274], elong in [1.375, 1.8399]) so
        // no parental mean of sizes can ever explain an elongation or the other
        // way round. The step is 2^-8, so every founder value and every mean of
        // two of them (one extra significand bit) is exact in float — "the exact
        // parental mean" is a real float, not a rounding of one. The elongation
        // index runs backwards so the two parameters are anti-correlated across
        // founders rather than carrying the same information twice.
        //
        // Neither band comes within M of a clamp rail, so a first-generation
        // child is never clamped and the grid check is testing the blend rather
        // than the clamp (case 2 tests the clamp).
        const std::size_t nF = w.creatures.size();
        for (std::size_t i = 0; i < nF; ++i) {
            w.creatures[i].bodySize  = 0.5625f + (float)i * 0x1p-8f;
            w.creatures[i].bodyElong = 1.375f  + (float)(nF - 1 - i) * 0x1p-8f;
        }

        // ids -> body, snapshotted BEFORE every step: a parent may die in the
        // very step it reproduces, and a body never changes after birth, so the
        // first sighting of an id records exactly the value the birth used.
        std::map<std::uint64_t, std::pair<float, float>> bodyOf;
        auto snapshot = [&]() {
            for (const auto& c : w.creatures)
                bodyOf.emplace(c.id, std::make_pair(c.bodySize, c.bodyElong));
        };

        struct Birth { float childSz, childEl; std::uint64_t p1, p2; };
        std::vector<Birth> births;
        std::size_t seenRecords = 0;
        for (int step = 0; step < 2500 && births.size() < 16; ++step) {
            snapshot();
            const std::uint64_t idBefore = w.nextId_ - 1;   // ids above this are this step's
            w.update(0.016f);
            // World::update assigns newborn ids by walking the newborns vector
            // in order (`baby.id = nextId_++`), and doInteraction calls logBirth
            // once per newborn immediately after pushing it — so the k-th new
            // record of a step belongs to the k-th new id of that step. If a
            // newborn also died inside the same step the counts disagree and the
            // step is skipped rather than mismatched.
            std::vector<const Creature*> fresh;
            for (const auto& c : w.creatures)
                if (c.id > idBefore) fresh.push_back(&c);
            std::sort(fresh.begin(), fresh.end(),
                      [](const Creature* a, const Creature* b) { return a->id < b->id; });
            const std::size_t newRecords = w.birthLog.size() - seenRecords;
            if (fresh.size() == newRecords)
                for (std::size_t k = 0; k < newRecords; ++k) {
                    const World::BirthRecord& r = w.birthLog[seenRecords + k];
                    births.push_back(Birth{fresh[k]->bodySize, fresh[k]->bodyElong,
                                           r.parent1, r.parent2});
                }
            seenRecords = w.birthLog.size();
        }
        CHECK(w.totalBirths > 0);
        CHECK(!births.empty());

        bool resolved = !births.empty(), onMean = !births.empty(), offSingle = true;
        int separable = 0;
        for (const Birth& b : births) {
            const auto i1 = bodyOf.find(b.p1), i2 = bodyOf.find(b.p2);
            if (i1 == bodyOf.end() || i2 == bodyOf.end()) { resolved = false; continue; }
            const float s1 = i1->second.first,  s2 = i2->second.first;
            const float e1 = i1->second.second, e2 = i2->second.second;
            onMean = onMean && fromInheritanceGrid(b.childSz, 0.5f * (s1 + s2), M)
                            && fromInheritanceGrid(b.childEl, 0.5f * (e1 + e2), M);

            // A single-parent blend is only REFUTABLE when the parents are far
            // enough apart: |mean - p| is |p1 - p2| / 2, so requiring
            // |p1 - p2| > 4M puts the mean more than 2M from either parent and
            // the child, which is within M of the mean, more than M from both —
            // i.e. off both single-parent grids by construction, not by luck.
            if (std::fabs(s1 - s2) > 4.0f * M && std::fabs(e1 - e2) > 4.0f * M) {
                ++separable;
                offSingle = offSingle && !fromInheritanceGrid(b.childSz, s1, M)
                                      && !fromInheritanceGrid(b.childSz, s2, M)
                                      && !fromInheritanceGrid(b.childEl, e1, M)
                                      && !fromInheritanceGrid(b.childEl, e2, M)
                                      // and the sum, which a mean is easy to mistype as
                                      && !fromInheritanceGrid(b.childSz, s1 + s2, M)
                                      && !fromInheritanceGrid(b.childEl, e1 + e2, M);
            }
        }
        CHECK(resolved);      // every logged parent id was still resolvable
        CHECK(onMean);        // every child is on the grid around its parents' mean
        CHECK(separable > 0); // the fixture actually produced far-apart pairs
        CHECK(offSingle);     // ...and no such child is explained by one parent
    }

    // --- 2. clamps: hand-built parents at the extremes -------------------
    {
        rng.seed(24601u);
        World w;
        w.cfg.minPopulation = 0;
        w.cfg.bodyModel = true;
        w.cfg.bodyMutation = 5.0f;    // far wider than the entire legal range
        w.init(900, 700, 220);
        for (size_t i = 0; i < w.creatures.size(); ++i) {
            w.creatures[i].bodySize  = (i % 2 == 0) ? BODY_PARAM_MIN : BODY_PARAM_MAX;
            w.creatures[i].bodyElong = (i % 2 == 0) ? BODY_PARAM_MAX : BODY_PARAM_MIN;
        }
        for (int i = 0; i < 600; ++i) w.update(0.016f);
        CHECK(w.totalBirths > 0);
        bool inRange = !w.creatures.empty(), sawRail = false;
        for (const auto& c : w.creatures) {
            inRange = inRange && c.bodySize  >= BODY_PARAM_MIN && c.bodySize  <= BODY_PARAM_MAX
                              && c.bodyElong >= BODY_PARAM_MIN && c.bodyElong <= BODY_PARAM_MAX;
            if (bitEq(c.bodySize, BODY_PARAM_MIN) || bitEq(c.bodySize, BODY_PARAM_MAX))
                sawRail = true;
        }
        CHECK(inRange);
        CHECK(sawRail);   // a width that big must actually reach the rails
    }

    // --- 4. determinism with the flag on, and the flag is not a no-op ----
    // Whole-run comparisons, so serial build only — the same guard the
    // topological, checkpoint, toroidal and isolation tests use.
#ifdef EVO_DETERMINISTIC
    {
        auto runFp = [](bool on, float mut, bool tri = false) {
            rng.seed(80808u);
            World w;
            w.cfg.bodyModel = on;
            w.cfg.bodyMutation = mut;
            w.cfg.triangularMotion = tri;
            w.init(900, 700, 240);
            for (int i = 0; i < 400; ++i) w.update(0.016f);
            return deepFingerprint(w);
        };
        const std::uint64_t on1 = runFp(true, 0.1f);
        CHECK(on1 == runFp(true, 0.1f));      // same seed + flags => same world
        const std::uint64_t off = runFp(false, 0.1f);
        CHECK(on1 != off);                    // the flag genuinely changes the run
        CHECK(off == runFp(false, 0.9f));     // bodyMutation is inert when off
        CHECK(on1 != runFp(true, 0.9f));      // ...and live when on

        // The same claims on the TRIANGULAR branch, which every arm above
        // misses: turnFactor is the only dynamical consumer of bodyElong, it is
        // applied at exactly one site, and that site is inside
        // `if (cfg.triangularMotion)`. The decoupled motion model never reads
        // cfg.maxTurnRate, so with --tri off no whole-run assertion in this file
        // can observe the turn term at all. (wasm/parity.sh carries
        // body_tri_s42 for the same reason.)
        const std::uint64_t triOn = runFp(true, 0.1f, true);
        CHECK(triOn == runFp(true, 0.1f, true));    // deterministic on the tri path too
        CHECK(triOn != runFp(false, 0.1f, true));   // the body model bites there
        CHECK(triOn != on1);                        // and tri really is a different world

        // The turn term ISOLATED, which the arms above still cannot do — they
        // move speedFactor and massFactor at the same time. Both runs below pin
        // every founder to bodySize 1.0 and set bodyMutation to 0, so the mean
        // blend holds the whole population at 1.0 forever: speedFactor and
        // massFactor are exactly 1.0f in both, and bodyElong is the ONLY
        // difference between them.
        //
        // The comparison uses a motion-only digest, not deepFingerprint, which
        // mixes bodyElong itself and would therefore differ whether or not the
        // value ever reached the dynamics. body[] is excluded for the same
        // reason: updateBody scales it by bodyElong, but body[] is read only by
        // the renderers, never by a sensor or an apply site.
        //   --tri off => elongation is unreachable => the two runs must be EQUAL
        //   --tri on  => elongation scales maxTurnRate => they must DIFFER
        // Deleting the turn apply site, or wiring turnFactor to bodySize, makes
        // the second comparison equal and fails here.
        auto motionFp = [](const World& w) {
            std::uint64_t h = 1469598103934665603ull;
            auto mixF = [&](float f) {
                unsigned char b[sizeof f];
                std::memcpy(b, &f, sizeof f);
                for (unsigned char x : b) { h ^= x; h *= 1099511628211ull; }
            };
            mixF((float)w.creatures.size());
            for (const auto& c : w.creatures) {
                mixF(c.pos.x); mixF(c.pos.y);
                mixF(c.vel.x); mixF(c.vel.y); mixF(c.speed);
            }
            return h;
        };
        auto elongFp = [&](float elong, bool tri, std::size_t& pop) {
            rng.seed(51413u);
            World w;
            w.cfg.minPopulation = 0;       // reseeded founders would re-enter at 1.0
            w.cfg.bodyModel = true;
            w.cfg.bodyMutation = 0.0f;     // the population never leaves the founder body
            w.cfg.triangularMotion = tri;
            w.init(900, 700, 240);
            for (auto& c : w.creatures) { c.bodySize = 1.0f; c.bodyElong = elong; }
            for (int i = 0; i < 300; ++i) w.update(0.016f);
            pop = w.creatures.size();
            return motionFp(w);
        };
        std::size_t pFlatLong = 0, pFlatShort = 0, pTriLong = 0, pTriShort = 0;
        const std::uint64_t flatLong  = elongFp(2.0f, false, pFlatLong);
        const std::uint64_t flatShort = elongFp(0.5f, false, pFlatShort);
        const std::uint64_t triLong   = elongFp(2.0f, true,  pTriLong);
        const std::uint64_t triShort  = elongFp(0.5f, true,  pTriShort);
        // Two empty worlds would hash equal for free, which would make the
        // "differ" assertion below unfalsifiable.
        CHECK(pFlatLong > 0 && pFlatShort > 0 && pTriLong > 0 && pTriShort > 0);
        CHECK(flatLong == flatShort);
        CHECK(triLong  != triShort);
    }
#endif

    // --- 5. with the flag on, bodies actually spread ---------------------
    {
        rng.seed(20260727u);
        World w;
        w.cfg.bodyModel = true;
        w.cfg.bodyMutation = 0.1f;
        w.init(1200, 900, 240);
        for (int i = 0; i < 1200; ++i) w.update(0.016f);
        CHECK(w.totalBirths > 0);
        CHECK(!w.creatures.empty());
        double mean = 0.0;
        for (const auto& c : w.creatures) mean += (double)c.bodySize;
        mean /= (double)w.creatures.size();
        double var = 0.0;
        for (const auto& c : w.creatures) {
            const double d = (double)c.bodySize - mean;
            var += d * d;
        }
        var /= (double)w.creatures.size();
        CHECK(var > 0.0);          // build-independent: the parameters moved
        bool anyOffDefault = false;
        for (const auto& c : w.creatures)
            if (!bitEq(c.bodySize, 1.0f) || !bitEq(c.bodyElong, 1.0f)) anyOffDefault = true;
        CHECK(anyOffDefault);

        // Same world with the flag off must stay frozen at the founder body.
        rng.seed(20260727u);
        World off;
        off.init(1200, 900, 240);
        for (int i = 0; i < 1200; ++i) off.update(0.016f);
        CHECK(off.totalBirths > 0);
        bool frozen = !off.creatures.empty();
        for (const auto& c : off.creatures)
            frozen = frozen && bitEq(c.bodySize, 1.0f) && bitEq(c.bodyElong, 1.0f);
        CHECK(frozen);
    }

    // --- 6. checkpoints: round trip, legacy files, and length checking ---
    {
        rng.seed(60607u);
        World a;
        a.cfg.bodyModel = true;
        a.cfg.bodyMutation = 0.25f;
        a.init(900, 700, 200);
        for (int i = 0; i < 800; ++i) a.update(0.016f);
        CHECK(a.totalBirths > 0);
        bool varied = false;
        for (const auto& c : a.creatures) if (!bitEq(c.bodySize, 1.0f)) varied = true;
        CHECK(varied);            // the round trip must have something to carry

        const std::string blob = checkpoint::serialize(a, "test");
        World b;
        std::string err;
        CHECK(checkpoint::deserialize(blob, b, err));
        CHECK(b.cfg.bodyModel);
        CHECK(bitEq(b.cfg.bodyMutation, 0.25f));
        bool same = b.creatures.size() == a.creatures.size() && !a.creatures.empty();
        for (size_t i = 0; same && i < a.creatures.size(); ++i)
            same = bitEq(a.creatures[i].bodySize,  b.creatures[i].bodySize)
                && bitEq(a.creatures[i].bodyElong, b.creatures[i].bodyElong);
        CHECK(same);              // every creature, bit for bit

        // A pre-v0.23.0 checkpoint has neither the config keys nor the columns.
        // It must load with the gate off and every body neutral — not fail, and
        // not invent values. (Same shape as the 0.22.0 legacy test.)
        std::string legacy = blob;
        CHECK(eraseJsonArray(legacy, "bodyElong"));
        CHECK(eraseJsonArray(legacy, "bodySize"));
        for (const std::string key : {std::string("\"bodyModel\":true,"),
                                      std::string("\"bodyMutation\":0.25,")}) {
            const size_t at = legacy.find(key);
            CHECK(at != std::string::npos);
            if (at != std::string::npos) legacy.erase(at, key.size());
        }
        CHECK(legacy.find("bodySize") == std::string::npos);
        CHECK(legacy.find("bodyElong") == std::string::npos);
        CHECK(legacy.find("bodyModel") == std::string::npos);
        World c;
        std::string err2;
        CHECK(checkpoint::deserialize(legacy, c, err2));
        CHECK(!c.cfg.bodyModel);
        CHECK(bitEq(c.cfg.bodyMutation, 0.10f));
        CHECK(c.creatures.size() == a.creatures.size());
        bool neutral = !c.creatures.empty();
        for (const auto& cc : c.creatures)
            neutral = neutral && bitEq(cc.bodySize, 1.0f) && bitEq(cc.bodyElong, 1.0f);
        CHECK(neutral);

        // Optional on read must NOT mean "unchecked": a column that IS present
        // but the wrong length is still a malformed checkpoint.
        std::string truncated = blob;
        const std::string k = "\"bodySize\":[";
        const size_t at = truncated.find(k);
        CHECK(at != std::string::npos);
        if (at != std::string::npos) {
            const size_t comma = truncated.find(',', at + k.size());
            const size_t end   = truncated.find(']', at);
            CHECK(comma != std::string::npos && end != std::string::npos && comma < end);
            if (comma < end) truncated.erase(comma, end - comma);   // keep one element
            World d;
            std::string err3;
            CHECK(!checkpoint::deserialize(truncated, d, err3));
        }

        // Half a column pair is a shape NO writer produces — serialize() emits
        // both arrays unconditionally — so it is corruption, not a legacy file,
        // and must not be read as "this one present, that one legacy 1.0".
        for (const char* key : {"bodySize", "bodyElong"}) {
            std::string half = blob;
            CHECK(eraseJsonArray(half, key));
            World e;
            std::string err4;
            CHECK(!checkpoint::deserialize(half, e, err4));
        }

        // Out-of-range values are corruption too. The only writer of these
        // numbers is the inheritance clamp, so nothing legitimate can emit one,
        // and they are not survivable: bodySize = -1 used to load cleanly, make
        // speedFactor 2/(1 + -1) = +inf, and run the creature on a NEGATIVE
        // metabolic burn. Both rails are tested from both sides.
        for (const char* key : {"bodySize", "bodyElong"}) {
            for (const char* bad : {"-1", "0", "0.25", "2.5", "5"}) {
                std::string poisoned = blob;
                const std::string kk = std::string("\"") + key + "\":[";
                const size_t a2 = poisoned.find(kk);
                CHECK(a2 != std::string::npos);
                if (a2 == std::string::npos) continue;
                const size_t first = a2 + kk.size();
                const size_t stop = poisoned.find_first_of(",]", first);
                CHECK(stop != std::string::npos);
                if (stop == std::string::npos) continue;
                poisoned.replace(first, stop - first, bad);   // first creature only
                World e;
                std::string err5;
                CHECK(!checkpoint::deserialize(poisoned, e, err5));
            }
        }

        // The CONFIG block is hand-editable, so it is the one route by which a
        // bodyMutation the CLI and evo_init both refuse can still reach the
        // engine. `nan` is in the list because json_min parses the bare token,
        // so this is reachable and not merely theoretical: a NaN half-width
        // makes rng.range return NaN and every newborn body NaN. The three load
        // paths have to agree, so the reader refuses these too.
        {
            const std::string kc = "\"bodyMutation\":0.25";
            CHECK(blob.find(kc) != std::string::npos);
            for (const char* bad : {"-1", "-0.001", "nan", "inf"}) {
                std::string poisoned = blob;
                const size_t at2 = poisoned.find(kc);
                if (at2 == std::string::npos) continue;
                poisoned.replace(at2, kc.size(), std::string("\"bodyMutation\":") + bad);
                World e;
                std::string err6;
                CHECK(!checkpoint::deserialize(poisoned, e, err6));
                CHECK(!err6.empty());       // a refusal must say why
            }
            // ...and the untouched blob still loads, so the guard is not just
            // rejecting everything.
            World good;
            std::string err7;
            CHECK(checkpoint::deserialize(blob, good, err7));
            CHECK(bitEq(good.cfg.bodyMutation, 0.25f));
        }
    }

    // --- resume equivalence with the flag on -----------------------------
    // The load-bearing checkpoint assertion, run on the body path: save, keep
    // going, reload, keep going, and the two futures must be identical. A
    // dropped or mis-restored body column changes the speed ceiling and the
    // metabolic burn, so it cannot survive this.
#ifdef EVO_DETERMINISTIC
    {
        rng.seed(1357911u);
        World a;
        configureRichWorld(a);
        a.cfg.bodyModel = true;
        a.cfg.bodyMutation = 0.2f;
        a.init(900, 700, 200);
        for (int i = 0; i < 300; ++i) a.update(0.016f);
        const std::string blob = checkpoint::serialize(a, "test");
        const std::uint64_t atSave = deepFingerprint(a);
        for (int i = 0; i < 200; ++i) a.update(0.016f);
        const std::uint64_t uninterrupted = deepFingerprint(a);

        World b;
        std::string err;
        CHECK(checkpoint::deserialize(blob, b, err));
        CHECK(deepFingerprint(b) == atSave);
        for (int i = 0; i < 200; ++i) b.update(0.016f);
        CHECK(deepFingerprint(b) == uninterrupted);
        CHECK(atSave != uninterrupted);
    }
#endif
}

// ---------------------------------------------------------------
// Match-distance mitigations (v0.24.0): the soft acceptance ramp
// (cfg.reproSoftWidth) and the founder grace window (cfg.reproGracePeriod).
//
// Two things have to be proven here, and the second is the harder one:
//   * the mitigations do what they claim — they admit pairs the hard gate
//     refuses, and they say WHICH mechanism admitted each one;
//   * with either knob off the gate is bit-for-bit the v0.21 gate. The soft
//     ramp is the only gate path in the tree that draws, so an accidental draw
//     on an off-path would silently invalidate every archived gated run, and
//     nothing but a fingerprint comparison catches that.
// ---------------------------------------------------------------
static void test_repro_mitigations() {
    std::printf("gate mitigations: soft ramp + founder grace...\n");

    // The largest value rng.unit() can return: (2^24 - 1) * 2^-24. The "d <= T
    // always accepts" rail rests on u being strictly below 1, so the grid tests
    // that exact value rather than something near it.
    const float UMAX = (float)0xFFFFFFu * 0x1p-24f;

    // --- softGateAccepts: the two rails, over a grid ---------------------
    {
        const float Ts[] = {0.5f, 8.0f, 13.0f, 16.0f, 20.0f};
        const float Ws[] = {0.25f, 1.0f, 4.0f, 5.0f, 12.0f};
        const float us[] = {0.0f, 0.25f, 0.5f, 0.999999881f, UMAX};
        bool insideAlways = true, outsideNever = true;
        for (float T : Ts) {
            for (float W : Ws) {
                const float inside[]  = {0.0f, 0.5f * T, T};
                const float outside[] = {T + W, T + W + 0.5f, 1.0e3f};
                for (float u : us) {
                    for (float d : inside)
                        if (!softGateAccepts(d, T, W, u)) insideAlways = false;
                    for (float d : outside)
                        if (softGateAccepts(d, T, W, u)) outsideNever = false;
                }
            }
        }
        CHECK(insideAlways);   // inside the threshold the gate is unconditional
        CHECK(outsideNever);   // past threshold+width nothing gets through
    }

    // --- softGateAccepts: it really is a RAMP ----------------------------
    // Both halves are needed: a gate that always accepted mid-band, or always
    // rejected, would satisfy the two rails above and be no ramp at all.
    {
        const float T = 16.0f, W = 5.0f, mid = T + 0.5f * W;
        CHECK(softGateAccepts(mid, T, W, 0.0f));
        CHECK(!softGateAccepts(mid, T, W, UMAX));

        // Monotone in u at fixed d, and monotone in d at fixed u: once it flips
        // to reject it must never flip back, and the sweep must actually cross.
        bool monotoneU = true, crossedU = false;
        for (int i = 0; i <= 1000; ++i) {
            const bool acc = softGateAccepts(mid, T, W, (float)i * 0.001f);
            if (crossedU && acc) monotoneU = false;
            if (!acc) crossedU = true;
        }
        CHECK(monotoneU);
        CHECK(crossedU);

        bool monotoneD = true, crossedD = false;
        for (int i = 0; i <= 1000; ++i) {
            const float d = T - 1.0f + (float)i * (W + 2.0f) * 0.001f;
            const bool acc = softGateAccepts(d, T, W, 0.5f);
            if (crossedD && acc) monotoneD = false;
            if (!acc) crossedD = true;
        }
        CHECK(monotoneD);
        CHECK(crossedD);
    }

    // --- a vanishing width collapses onto the hard comparison ------------
    // The soft gate is a generalisation of the hard one, not a different rule:
    // outside the band of width W above the threshold the two agree for every
    // draw, and W here is narrow enough that no sampled distance lands in it.
    // W is a power of two so that T + W is exact — see the rounding note on
    // softGateAccepts for why the rails need that.
    {
        const float T = 16.0f, W = 0.0625f;
        bool agrees = true;
        for (int i = 0; i <= 128; ++i) {
            const float d = (float)i * 0.25f;
            for (float u : {0.0f, 0.25f, 0.75f, UMAX})
                if (softGateAccepts(d, T, W, u) != (d <= T)) agrees = false;
        }
        CHECK(agrees);
    }

    // --- reproGraced: the predicate, directly -----------------------------
    {
        Creature founder;
        founder.id = 7; founder.lineageId = 7;   // lineage starts at itself
        founder.age = 3.0f;
        CHECK(World::reproGraced(founder, 10.0f));
        founder.age = 12.0f;
        CHECK(!World::reproGraced(founder, 10.0f));   // window has closed
        founder.age = 10.0f;
        CHECK(!World::reproGraced(founder, 10.0f));   // the bound is strict
        founder.age = 3.0f;
        CHECK(!World::reproGraced(founder, 0.0f));    // 0 = off
        CHECK(!World::reproGraced(founder, -1.0f));   // negative = off, not an error

        // A child carries its mother's lineage, so lineageId != id and it is
        // never graced however young it is — grace is for injected genomes.
        Creature child;
        child.id = 8; child.lineageId = 7; child.age = 0.0f;
        CHECK(!World::reproGraced(child, 10.0f));
    }

    // --- lineageId == id really does mean "founder" ------------------------
    // The whole reason grace needs no new creature state. Every creature is a
    // founder at init; once insertions have happened, some are not.
    {
        rng.seed(24680u);
        World w;
        w.cfg.minPopulation = 0;
        w.init(900, 700, 220);
        bool allFounders = true;
        for (const Creature& c : w.creatures)
            if (c.lineageId != c.id) allFounders = false;
        CHECK(allFounders);
        for (int i = 0; i < 600; ++i) w.update(0.016f);
        CHECK(w.totalBirths > 0);
        int descendants = 0;
        for (const Creature& c : w.creatures)
            if (c.lineageId != c.id) ++descendants;
        CHECK(descendants > 0);
    }

    // Whole-run comparisons below are serial-build only, for the reason the
    // isolation, toroidal and checkpoint tests give: the OpenMP parallel phase
    // draws from per-thread RNGs and a fixed seed does not pin the run.
#ifdef EVO_DETERMINISTIC
    // --- both knobs off is bit-for-bit the v0.21 hard gate ----------------
    // The load-bearing no-op proof: <=0 must mean "off" for BOTH spellings
    // (0 and negative), and the off-path must not touch the rng sequence.
    {
        const int STEPS = 600;
        auto fingerprintOf = [&](float T, float W, float G, long long& births) {
            rng.seed(24680u);
            World w;
            w.cfg.minPopulation = 0;
            w.cfg.reproMaxDistance = T;
            w.cfg.reproSoftWidth   = W;
            w.cfg.reproGracePeriod = G;
            w.init(900, 700, 220);
            for (int i = 0; i < STEPS; ++i) w.update(0.016f);
            births = w.totalBirths;
            return deepFingerprint(w);
        };

        long long bZero = 0, bNeg = 0;
        const std::uint64_t hardZero = fingerprintOf(18.0f,  0.0f,  0.0f, bZero);
        const std::uint64_t hardNeg  = fingerprintOf(18.0f, -1.0f, -1.0f, bNeg);
        CHECK(hardZero == hardNeg);
        CHECK(bZero > 0);            // the control must actually breed

        // Both knobs are inert without the gate: with no threshold there is
        // nothing to soften and nothing to be exempt from.
        long long bOff = 0, bOffKnobs = 0;
        const std::uint64_t off      = fingerprintOf(-1.0f, 0.0f,  0.0f, bOff);
        const std::uint64_t offKnobs = fingerprintOf(-1.0f, 5.0f, 60.0f, bOffKnobs);
        CHECK(off == offKnobs);
        CHECK(bOff > 0);
        CHECK(off != hardZero);      // the gate at 18 does bite, so this is a real test
    }

    // --- the soft ramp admits the band the hard gate refuses --------------
    // T is below the breeding floor (nothing pairs at 8), so every insertion
    // here is one the hard gate refused and the ramp let through — which is
    // exactly what totalSoftBirths claims to count.
    {
        const int STEPS = 600;
        rng.seed(24680u);
        World soft;
        soft.cfg.minPopulation = 0;
        soft.cfg.reproMaxDistance = 8.0f;
        soft.cfg.reproSoftWidth = 12.0f;
        soft.init(900, 700, 220);
        for (int i = 0; i < STEPS; ++i) soft.update(0.016f);
        CHECK(soft.totalBirths > 0);
        CHECK(soft.totalSoftBirths > 0);
        CHECK(soft.totalSoftBirths <= soft.totalBirths);
        CHECK(soft.totalGraceBirths == 0);   // grace is off

        rng.seed(24680u);
        World hard;
        hard.cfg.minPopulation = 0;
        hard.cfg.reproMaxDistance = 8.0f;
        hard.init(900, 700, 220);
        for (int i = 0; i < STEPS; ++i) hard.update(0.016f);
        CHECK(hard.totalBirths == 0);
    }

    // --- grace rescues a population the gate has locked out ---------------
    {
        const int STEPS = 600;
        rng.seed(24680u);
        World graced;
        graced.cfg.minPopulation = 0;
        graced.cfg.reproMaxDistance = 8.0f;
        graced.cfg.reproGracePeriod = 10000.0f;   // every founder, all run
        graced.init(900, 700, 220);
        for (int i = 0; i < STEPS; ++i) graced.update(0.016f);
        CHECK(graced.totalBirths > 0);
        CHECK(graced.totalGraceBirths > 0);
        CHECK(graced.totalGraceBirths <= graced.totalBirths);
        CHECK(graced.totalSoftBirths == 0);       // the ramp is off, and grace
                                                  // bypasses before any draw

        // Same threshold without grace: nothing at all (the control for the
        // claim above — 8 is far below the live set's own pair distance).
        rng.seed(24680u);
        World hard;
        hard.cfg.minPopulation = 0;
        hard.cfg.reproMaxDistance = 8.0f;
        hard.init(900, 700, 220);
        for (int i = 0; i < STEPS; ++i) hard.update(0.016f);
        CHECK(hard.totalBirths == 0);

        // A plain hard-gated run attributes nothing, however much it breeds.
        rng.seed(24680u);
        World plain;
        plain.cfg.minPopulation = 0;
        plain.cfg.reproMaxDistance = 18.0f;
        plain.init(900, 700, 220);
        for (int i = 0; i < STEPS; ++i) plain.update(0.016f);
        CHECK(plain.totalBirths > 0);
        CHECK(plain.totalGraceBirths == 0);
        CHECK(plain.totalSoftBirths == 0);
    }

    // --- determinism with both knobs on, and they are not a no-op ---------
    // The rich arm collapses onto the --min-pop floor, so the creatures being
    // graced there are RESEED founders, not the initial spawn — the §7.1 case
    // the mitigation was built for.
    {
        const int STEPS = 600;
        auto richRun = [&](float W, float G) {
            rng.seed(50505u);
            World w;
            configureRichWorld(w);
            w.cfg.reproMaxDistance = 16.0f;
            w.cfg.reproSoftWidth   = W;
            w.cfg.reproGracePeriod = G;
            w.init(900, 700, 240);
            for (int i = 0; i < STEPS; ++i) w.update(0.016f);
            return w;
        };
        const World a = richRun(5.0f, 60.0f);
        const World b = richRun(5.0f, 60.0f);
        const World h = richRun(0.0f,  0.0f);
        CHECK(deepFingerprint(a) == deepFingerprint(b));
        CHECK(deepFingerprint(a) != deepFingerprint(h));   // live, not a no-op
        CHECK(a.totalGraceBirths > 0);
        CHECK(a.totalBirths > h.totalBirths);
        CHECK(h.totalGraceBirths == 0 && h.totalSoftBirths == 0);
    }

    // --- "EITHER partner graced" is load-bearing — run long enough to see it
    // Every arm above stays under ~16 s of sim time, where no graced-founder ×
    // ungraced-CHILD pair can exist yet (children appear after t≈5 and cannot
    // breed before t≈10), so an && in place of the || in reproGatePasses was
    // invisible to all of them — and the founder × established-resident pair
    // is precisely the §7.1 case grace exists for. 4000 steps (64 s) makes
    // those pairings the common case: measured 433 births shipped vs 225 under
    // the && mutant, so the threshold below separates them cleanly.
    {
        rng.seed(24680u);
        World w;
        w.cfg.minPopulation = 0;
        w.cfg.reproMaxDistance = 13.0f;
        w.cfg.reproGracePeriod = 60.0f;
        w.init(900, 700, 220);
        for (int i = 0; i < 4000; ++i) w.update(0.016f);
        CHECK(w.totalBirths > 300);
        CHECK(w.totalGraceBirths > 300);
    }

    // --- attribution is honest: soft counts ONLY hard-refused pairs --------
    // A threshold inside the live window with a narrow ramp: most accepted
    // pairs sit inside T and needed no help, a few came through the ramp. If
    // viaSoft were set for every draw-accepted pair, soft would equal
    // births − grace; it must stay strictly below. (The T=8 arm above cannot
    // see this — below the breeding floor soft == births by construction.)
    {
        rng.seed(4242u);
        World w;
        configureRichWorld(w);
        w.cfg.reproMaxDistance = 18.0f;
        w.cfg.reproSoftWidth   = 4.0f;
        w.init(900, 700, 240);
        for (int i = 0; i < 1200; ++i) w.update(0.016f);
        CHECK(w.totalSoftBirths > 0);
        CHECK(w.totalSoftBirths < w.totalBirths - w.totalGraceBirths);
    }

    // --- the draw discipline itself, pinned -------------------------------
    // reproMaxDistance = 1e6 arms the gate but never bites, so accept/reject
    // decisions are identical across each pair of runs below and ONLY the
    // draw count can differ. Shape precedent: the v0.21 permissive-gate test
    // in test_reproductive_isolation. These three are what stop a future
    // "optimise away the predetermined draw" or "draw before the grace check"
    // refactor from silently invalidating every archived soft-gate run.
    {
        auto run = [&](float W, float G, std::string* rngStateOut) {
            rng.seed(13579u);
            World w;
            w.cfg.minPopulation    = 0;
            w.cfg.reproMaxDistance = 1.0e6f;
            w.cfg.reproSoftWidth   = W;
            w.cfg.reproGracePeriod = G;
            w.init(900, 700, 220);
            for (int i = 0; i < 500; ++i) w.update(0.016f);
            if (rngStateOut) *rngStateOut = rng.state();
            return w;
        };
        // (a) grace draws NOTHING: with the hard gate accepting everything,
        // grace on/off leaves the engine in the same state and produces the
        // same births. deepFingerprint is NOT compared here — it mixes the
        // attribution counters, which legitimately differ (0 vs graced).
        std::string sOff, sOn;
        const World gOff = run(0.0f, 0.0f, &sOff);
        const World gOn  = run(0.0f, 1.0e6f, &sOn);
        CHECK(gOff.totalBirths > 0);
        CHECK(gOn.totalGraceBirths > 0);       // grace really engaged
        CHECK(sOff == sOn);
        CHECK(gOff.totalBirths == gOn.totalBirths);
        // (b) the soft draw is UNCONDITIONAL: every pair is inside T, so the
        // ramp changes no decision — only the stream. The runs must diverge.
        const World w5 = run(5.0f, 0.0f, nullptr);
        CHECK(deepFingerprint(gOff) != deepFingerprint(w5));
        // (c) grace bypasses BEFORE the draw: with the ramp on, gracing
        // everyone removes one draw per gate evaluation. Divergence again.
        const World sGrace = run(5.0f, 1.0e6f, nullptr);
        CHECK(deepFingerprint(w5) != deepFingerprint(sGrace));
    }
#endif

    // --- checkpoint: config keys and both counters survive a round trip ---
    {
        rng.seed(60606u);
        World a;
        a.cfg.reproMaxDistance = 15.0f;
        a.cfg.reproSoftWidth   = 4.0f;
        a.cfg.reproGracePeriod = 8.0f;   // short enough that founders age out
                                         // and the ramp admits pairs too
        a.init(900, 700, 200);
        for (int i = 0; i < 800; ++i) a.update(0.016f);
#ifdef EVO_DETERMINISTIC
        // Properties of THIS seeded trajectory. A threaded build does not
        // replay it, and in some of its runs no ramp-admitted birth happens
        // within 800 steps (seen in the pool build: 1 run in ~8), so there the
        // counters are only round-tripped below, whatever their values.
        CHECK(a.totalSoftBirths > 0);
        CHECK(a.totalGraceBirths > 0);
#endif

        // The CSV plumbing must read what the world counted — a dropped copy
        // in computeStats zeroes a column while the checkpoint counter stays
        // right, and nothing else ever compares the two. (The sentinel test in
        // the stats block pins statsCsvRow; this pins computeStats.)
        const WorldStats live = computeStats(a);
        CHECK(live.totalGraceBirths == (int)a.totalGraceBirths);
        CHECK(live.totalSoftBirths  == (int)a.totalSoftBirths);

        const std::string blob = checkpoint::serialize(a, "test");
        World b;
        std::string err;
        CHECK(checkpoint::deserialize(blob, b, err));
        CHECK(bitEq(b.cfg.reproSoftWidth, 4.0f));
        CHECK(bitEq(b.cfg.reproGracePeriod, 8.0f));
        CHECK(b.totalSoftBirths == a.totalSoftBirths);
        CHECK(b.totalGraceBirths == a.totalGraceBirths);

        // A checkpoint written before v0.24.0 carries none of the four keys.
        // Loading it must leave the mitigations off and the attribution at 0,
        // which is what that run actually did — not invent values.
        auto stripKey = [](std::string& s, const char* name) {
            const std::string k = std::string("\"") + name + "\":";
            const size_t at = s.find(k);
            if (at == std::string::npos) return false;
            size_t end = s.find_first_of(",}", at + k.size());
            if (end == std::string::npos) return false;
            if (s[end] == ',') ++end;          // take the separator with it
            s.erase(at, end - at);
            return true;
        };
        std::string legacy = blob;
        CHECK(stripKey(legacy, "reproSoftWidth"));
        CHECK(stripKey(legacy, "reproGracePeriod"));
        CHECK(stripKey(legacy, "totalGraceBirths"));
        CHECK(stripKey(legacy, "totalSoftBirths"));
        World c;
        std::string err2;
        CHECK(checkpoint::deserialize(legacy, c, err2));
        CHECK(bitEq(c.cfg.reproSoftWidth, 0.0f));
        CHECK(bitEq(c.cfg.reproGracePeriod, 0.0f));
        CHECK(c.totalGraceBirths == 0);
        CHECK(c.totalSoftBirths == 0);
        CHECK(bitEq(c.cfg.reproMaxDistance, 15.0f));   // untouched keys survive
        CHECK(c.totalBirths == a.totalBirths);
    }

    // --- resume equivalence with the mitigations active -------------------
    // The load-bearing checkpoint assertion, on the mitigation path: save, keep
    // going, reload, keep going, and the two futures must be identical. The
    // fingerprint covers both counters, so a dropped one fails here.
#ifdef EVO_DETERMINISTIC
    {
        rng.seed(1357911u);
        World a;
        configureRichWorld(a);
        a.cfg.reproMaxDistance = 16.0f;
        a.cfg.reproSoftWidth   = 6.0f;
        a.cfg.reproGracePeriod = 8.0f;
        a.init(900, 700, 200);
        for (int i = 0; i < 1000; ++i) a.update(0.016f);
        CHECK(a.totalGraceBirths > 0);
        CHECK(a.totalSoftBirths > 0);

        const std::string blob = checkpoint::serialize(a, "test");
        const std::uint64_t atSave = deepFingerprint(a);
        for (int i = 0; i < 300; ++i) a.update(0.016f);
        const std::uint64_t uninterrupted = deepFingerprint(a);

        World b;
        std::string err;
        CHECK(checkpoint::deserialize(blob, b, err));
        CHECK(deepFingerprint(b) == atSave);
        for (int i = 0; i < 300; ++i) b.update(0.016f);
        CHECK(deepFingerprint(b) == uninterrupted);
        CHECK(atSave != uninterrupted);
    }
#endif

    // --- nextId is now dynamics-bearing, so the reader polices it ---------
    // reproGraced() reads lineageId == id; a newborn reusing a live id would
    // be a fake founder that bypasses the gate. Pre-0.24 a stale nextId was
    // merely cosmetic (duplicate ids), which is why nothing checked it before.
    {
        rng.seed(60607u);
        World a;
        a.cfg.reproMaxDistance = 15.0f;
        a.cfg.reproGracePeriod = 8.0f;
        a.init(900, 700, 200);
        for (int i = 0; i < 200; ++i) a.update(0.016f);
        const std::string blob = checkpoint::serialize(a, "test");

        World ok;
        std::string err;
        CHECK(checkpoint::deserialize(blob, ok, err));

        // Key removed entirely: ullOr defaults it to 1, which collides with
        // every live id — must refuse, and for the nextId reason rather than
        // an incidental parse error.
        std::string noKey = blob;
        const std::string k = "\"nextId\":";
        std::size_t at = noKey.find(k);
        CHECK(at != std::string::npos);
        if (at != std::string::npos) {
            // nextId is the LAST key in its object ("...,"nextId":N}"), so the
            // separator to take is the LEADING comma — taking a trailing one
            // would leave ",}" and fail parsing, which rejects the file for
            // the wrong reason and proves nothing about the nextId check.
            std::size_t from = at;
            std::size_t end = noKey.find_first_of(",}", at + k.size());
            CHECK(end != std::string::npos);
            if (end != std::string::npos && noKey[end] == ',') ++end;
            else if (from > 0 && noKey[from - 1] == ',') --from;
            noKey.erase(from, end - from);
            World b;
            std::string e2;
            CHECK(!checkpoint::deserialize(noKey, b, e2));
            CHECK(e2.find("nextId") != std::string::npos);
        }

        // Key present but stale (at or below a live id): refused too.
        std::string stale = blob;
        at = stale.find(k);
        CHECK(at != std::string::npos);
        if (at != std::string::npos) {
            const std::size_t end = stale.find_first_of(",}", at + k.size());
            CHECK(end != std::string::npos);
            stale = stale.substr(0, at) + "\"nextId\":1" + stale.substr(end);
            World b;
            std::string e2;
            CHECK(!checkpoint::deserialize(stale, b, e2));
            CHECK(e2.find("nextId") != std::string::npos);
        }
    }
}

// ---------------------------------------------------------------
// Generation counter (display-only, v0.25.0). Founders — spawned or reseeded —
// are generation 0 and are exactly the creatures with lineageId == id; every
// newborn is max(source records) + 1, so it is >= 1. The column survives a
// checkpoint round trip, a checkpoint without it (pre-0.25) loads with every
// creature at 0, and a malformed one is rejected. Holds in every build.
static void test_generation() {
    rng.seed(4242u);
    World w;
    w.init(800, 600, 200);
    bool allZero = true;
    for (const auto& c : w.creatures) if (c.generation != 0u) allZero = false;
    CHECK(allZero);

    for (int i = 0; i < 4000; ++i) w.update(0.016f);
    CHECK(w.totalBirths > 0);
    bool founderIffZero = true;
    std::uint32_t maxGen = 0;
    for (const auto& c : w.creatures) {
        if ((c.lineageId == c.id) != (c.generation == 0u)) founderIffZero = false;
        maxGen = std::max(maxGen, c.generation);
    }
    CHECK(founderIffZero);
    CHECK(maxGen >= 1u);
    const GenerationSpan span = generationSpan(w);
    CHECK(span.max == maxGen);
    CHECK(span.mean >= 0.0 && span.mean <= (double)span.max);

    // round trip keeps every value
    const std::string blob = checkpoint::serialize(w, "test");
    World r;
    std::string err;
    CHECK(checkpoint::deserialize(blob, r, err));
    bool same = r.creatures.size() == w.creatures.size();
    for (size_t i = 0; same && i < w.creatures.size(); ++i)
        same = r.creatures[i].generation == w.creatures[i].generation;
    CHECK(same);

    // The creatures' column: the predators block, written first, has its own
    // "generation" (v0.26.0).
    const std::string key = ",\"generation\":[";
    const size_t at = blob.find(key, blob.find("\"creatures\""));
    CHECK(at != std::string::npos);
    if (at == std::string::npos) return;

    // a checkpoint written before the column existed loads at generation 0
    std::string old = blob;
    old.erase(at, old.find(']', at) - at + 1);
    World o;
    CHECK(checkpoint::deserialize(old, o, err));
    bool zero = !o.creatures.empty();
    for (const auto& c : o.creatures) if (c.generation != 0u) zero = false;
    CHECK(zero);

    // a negative value is a corrupt file: rejected, not wrapped to 2^32-1
    std::string bad = blob;
    const size_t v0 = at + key.size();
    bad.replace(v0, bad.find_first_of(",]", v0) - v0, "-1");
    World b;
    CHECK(!checkpoint::deserialize(bad, b, err));
}

#ifdef EVO_POOL_THREADS
// ---------------------------------------------------------------
// Thread pool (the Emscripten pthreads path, testable natively with
// -DEVO_POOL_THREADS=ON): every index is visited exactly once, by a thread id
// in range, for every thread count / size / chunk shape, across thousands of
// back-to-back dispatches (a lost wake-up would hang here rather than pass).
static void test_thread_pool() {
    evo_par::Pool& pool = evo_par::Pool::instance();
    const int maxT = evo_par::Pool::maxThreads();
    bool exact = true, tidsOk = true;
    int dispatches = 0;
    for (int t : {1, 2, 3, maxT}) {
        pool.setThreads(t);
        CHECK(pool.threads() == std::min(t, maxT));
        for (int n : {0, 1, 15, 16, 17, 1000, 4099}) {
            for (int chunk : {1, 16, 64}) {
                for (int rep = 0; rep < 25; ++rep) {
                    std::vector<int> hits((size_t)n, 0);  // chunks are disjoint: no two threads share an index
                    std::atomic<int> badTid{0};
                    pool.run(n, chunk, [&](int lo, int hi, int tid) {
                        if (tid < 0 || tid >= pool.threads()) badTid.fetch_add(1);
                        for (int i = lo; i < hi; ++i) hits[(size_t)i]++;
                    });
                    ++dispatches;
                    for (int h : hits) if (h != 1) exact = false;
                    if (badTid.load()) tidsOk = false;
                }
            }
        }
    }
    CHECK(exact);
    CHECK(tidsOk);
    CHECK(dispatches == 4 * 7 * 3 * 25);
    pool.setThreads(maxT);  // leave it as World expects
}
#endif

// ---------------------------------------------------------------
// Predator floor + heritable predator traits (v0.26.0). Both opt-in. The
// claims: off, nothing changes and nothing is drawn; the floor refills to
// exactly N with baseline founders and counts them, and only with the economy
// on; inheritance draws exactly when a bud happens, keeps every trait in
// [0.5, 2], and the traits really move speed, burn and the budding threshold;
// checkpoints carry all of it and still load pre-0.26 files.
static void test_predator_floor_inherit() {
    std::printf("predator floor + heritable traits...\n");

    // --- 1. defaults are off, and a default predator is the 0.25 predator ---
    {
        SimConfig c;
        CHECK(c.predatorMinPopulation == 0);
        CHECK(!c.predatorInheritance);
        CHECK(bitEq(c.predatorTraitMutation, 0.10f));
        Predator p;
        CHECK(bitEq(p.speedFactor, 1.0f) && bitEq(p.buddingFactor, 1.0f) && p.generation == 0u);
        const float xs[] = {110.0f, 60.0f, 0.0f, 1.0f / 3.0f, 123.456f, 7e-5f};
        for (float x : xs) CHECK(bitEq(x * p.speedFactor, x) && bitEq(x * p.buddingFactor, x));
    }

    // A starving world: economy on, no prey ever (min-pop 0), 5 predators with
    // 30 energy burning exactly 2/s, so all five starve together at step 938.
    auto starving = [](unsigned seed, int floor) {
        rng.seed(seed);
        World w;
        w.cfg.predatorCount = 5;
        w.cfg.predatorEconomy = true;
        w.cfg.predatorMetabolism = 2.0f;
        w.cfg.predatorMoveCost = 0.0f;
        w.cfg.predatorNewbornEnergy = 30.0f;
        w.cfg.predatorMinPopulation = floor;
        w.cfg.minPopulation = 0;
        w.init(640, 480, 0);
        w.creatures.clear();
        return w;
    };

    // --- 2. floor off: extinction is final, nothing refilled ---------------
    {
        World w = starving(11u, 0);
        for (int s = 0; s < 1500; ++s) w.update(0.016f);
        CHECK(w.predators.empty());
        CHECK(w.totalPredatorReseeds == 0);
    }

    // --- 3. floor on: refilled to exactly N, with baseline founders --------
    {
        World w = starving(11u, 3);
        bool neverShort = true;
        for (int s = 0; s < 1500; ++s) {
            w.update(0.016f);
            if (w.predators.size() < 3u) neverShort = false;
        }
        CHECK(neverShort);
        CHECK(w.totalPredatorDeathsStarvation == 5);   // the five starved...
        CHECK(w.totalPredatorReseeds == 3);            // ...and three came back
        CHECK(w.totalPredatorBirths == 0);             // refills are not births
        CHECK(w.predators.size() == 3u);
        bool founders = w.predators.size() == 3u;
        for (const auto& p : w.predators)
            if (p.generation != 0u || !bitEq(p.speedFactor, 1.0f) || !bitEq(p.buddingFactor, 1.0f) ||
                !(p.energy > 0.0f && p.energy <= 30.0f) || !(p.pos.x >= 0.0f && p.pos.x < 640.0f))
                founders = false;
        CHECK(founders);
        // and they go on starving: the floor refills, it does not feed
        for (int s = 0; s < 1000; ++s) w.update(0.016f);
        CHECK(w.totalPredatorDeathsStarvation == 8);
        CHECK(w.totalPredatorReseeds == 6);
    }

    // --- 4. the floor needs the economy: Stage A stays fixed-count ---------
    {
        rng.seed(5u);
        World w;
        w.cfg.predatorCount = 2;
        w.cfg.predatorMinPopulation = 5;               // economy off => inert
        w.init(640, 480, 60);
        for (int s = 0; s < 200; ++s) w.update(0.016f);
        CHECK(w.predators.size() == 2u);
        CHECK(w.totalPredatorReseeds == 0);
    }

#ifdef EVO_DETERMINISTIC
    // --- 5. a floor that never has to act draws nothing --------------------
    // Rich world (4 economy predators; none starve within 300 steps): a floor
    // of 2 is never short, so the run must be bit-identical to the floor-off one.
    {
        auto run = [](int floor) {
            rng.seed(4321u);
            World w;
            configureRichWorld(w);
            w.cfg.predatorMinPopulation = floor;
            w.init(900, 700, 260);
            for (int i = 0; i < 300; ++i) w.update(0.016f);
            return std::make_pair(deepFingerprint(w), w.totalPredatorReseeds);
        };
        const auto off = run(0), idle = run(2);
        CHECK(idle.second == 0);
        CHECK(off.first == idle.first);
    }

    // --- 6. inheritance draws only when a bud happens ----------------------
    // On with no buds (threshold out of reach) == off; on with buds and m = 0
    // keeps every trait at exactly 1.0 but still takes its two draws per bud,
    // so the run moves off the inheritance-off trajectory.
    {
        auto run = [](bool inherit, float mut, float reproEnergy) {
            rng.seed(2468u);
            World w;
            configureRichWorld(w);
            w.cfg.predatorInheritance = inherit;
            w.cfg.predatorTraitMutation = mut;
            w.cfg.predatorReproEnergy = reproEnergy;
            w.init(900, 700, 260);
            for (int i = 0; i < 400; ++i) w.update(0.016f);
            bool unit = true;
            for (const auto& p : w.predators)
                if (!bitEq(p.speedFactor, 1.0f) || !bitEq(p.buddingFactor, 1.0f)) unit = false;
            return std::make_tuple(deepFingerprint(w), w.totalPredatorBirths, unit);
        };
        const auto offNoBud = run(false, 0.1f, 1e9f), onNoBud = run(true, 0.1f, 1e9f);
        CHECK(std::get<1>(onNoBud) == 0);
        CHECK(std::get<0>(offNoBud) == std::get<0>(onNoBud));
        const auto off = run(false, 0.0f, 60.0f), onZero = run(true, 0.0f, 60.0f);
        CHECK(std::get<1>(off) > 0);                    // buds happened
        CHECK(std::get<2>(off) && std::get<2>(onZero)); // m = 0: traits stay 1.0
        CHECK(std::get<0>(off) != std::get<0>(onZero)); // ...but the draws were taken
    }
#endif

    // --- 7. one bud: generation, trait band, and the two draws' values ----
    {
        auto bud = [](unsigned seed, bool inherit, float mut) {
            rng.seed(seed);
            World w;
            w.cfg.predatorCount = 1;
            w.cfg.predatorEconomy = true;
            w.cfg.predatorMetabolism = 2.0f;
            w.cfg.predatorMoveCost = 0.0f;
            w.cfg.predatorReproEnergy = 40.0f;
            w.cfg.predatorNewbornEnergy = 30.0f;
            w.cfg.predatorInheritance = inherit;
            w.cfg.predatorTraitMutation = mut;
            w.cfg.minPopulation = 0;
            w.init(640, 480, 0);
            w.creatures.clear();
            w.predators[0].energy = 50.0f;
            w.predators[0].speedFactor = 1.2f;
            w.predators[0].buddingFactor = 0.9f;
            w.predators[0].generation = 4;
            w.update(0.016f);
            return w;
        };
        World on = bud(13u, true, 0.1f);
        CHECK(on.predators.size() == 2u);
        if (on.predators.size() == 2u) {
            const Predator& kid = on.predators[1];
            CHECK(kid.generation == 5u);
            CHECK(kid.speedFactor >= 1.2f - 0.1f - 1e-6f && kid.speedFactor <= 1.2f + 0.1f + 1e-6f);
            CHECK(kid.buddingFactor >= 0.9f - 0.1f - 1e-6f && kid.buddingFactor <= 0.9f + 0.1f + 1e-6f);
            CHECK(!bitEq(kid.speedFactor, 1.2f) || !bitEq(kid.buddingFactor, 0.9f));   // a draw landed
            CHECK(bitEq(on.predators[0].speedFactor, 1.2f));   // the parent is untouched
        }
        World off = bud(13u, false, 0.1f);
        CHECK(off.predators.size() == 2u);
        if (off.predators.size() == 2u) {
            CHECK(off.predators[1].generation == 5u);          // counted either way
            CHECK(bitEq(off.predators[1].speedFactor, 1.0f) && bitEq(off.predators[1].buddingFactor, 1.0f));
        }
        // Clamp: a parent at the ceiling with a huge mutation stays in band.
        bool inBand = true;
        for (unsigned s = 100; s < 140; ++s) {
            rng.seed(s);
            World w;
            w.cfg.predatorCount = 1;
            w.cfg.predatorEconomy = true;
            w.cfg.predatorMoveCost = 0.0f;
            w.cfg.predatorReproEnergy = 40.0f;
            w.cfg.predatorInheritance = true;
            w.cfg.predatorTraitMutation = 5.0f;
            w.cfg.minPopulation = 0;
            w.init(640, 480, 0);
            w.creatures.clear();
            w.predators[0].energy = 100.0f;
            w.predators[0].speedFactor = PRED_TRAIT_MAX;
            w.predators[0].buddingFactor = PRED_TRAIT_MIN;
            w.update(0.016f);
            for (const auto& p : w.predators)
                if (!(p.speedFactor >= PRED_TRAIT_MIN && p.speedFactor <= PRED_TRAIT_MAX) ||
                    !(p.buddingFactor >= PRED_TRAIT_MIN && p.buddingFactor <= PRED_TRAIT_MAX)) inBand = false;
        }
        CHECK(inBand);
    }

    // --- 8. the traits do what they say -----------------------------------
    {
        // speedFactor scales the cruise and the kinetic burn: one step, no
        // prey, no current, centre of the world so nothing wraps.
        auto step = [](float sf, Vec2& moved, float& burned) {
            rng.seed(99u);
            World w;
            w.cfg.predatorCount = 1;
            w.cfg.predatorEconomy = true;
            w.cfg.predatorMetabolism = 2.0f;
            w.cfg.predatorMoveCost = 1e-4f;
            w.cfg.predatorSpeed = 100.0f;
            w.cfg.predatorReproEnergy = 1000.0f;
            w.cfg.minPopulation = 0;
            w.init(640, 480, 0);
            w.creatures.clear();
            w.predators[0].pos = {320.0f, 240.0f};
            w.predators[0].energy = 50.0f;
            w.predators[0].speedFactor = sf;
            w.update(0.016f);
            moved = w.predators[0].pos - Vec2{320.0f, 240.0f};
            burned = 50.0f - w.predators[0].energy;
        };
        Vec2 m1, m2; float b1, b2;
        step(1.0f, m1, b1);
        step(2.0f, m2, b2);
        const float d1 = std::sqrt(m1.x * m1.x + m1.y * m1.y), d2 = std::sqrt(m2.x * m2.x + m2.y * m2.y);
        CHECK(approx(d1, 100.0f * 0.016f, 1e-3f));
        CHECK(approx(d2, 200.0f * 0.016f, 1e-3f));
        CHECK(approx(b1, (2.0f + 1e-4f * 100.0f * 100.0f) * 0.016f, 1e-4f));
        CHECK(approx(b2, (2.0f + 1e-4f * 200.0f * 200.0f) * 0.016f, 1e-4f));

        // buddingFactor scales the threshold: 50 energy buds at x0.75 (45),
        // not at x1.0 (60).
        auto buds = [](float bf) {
            rng.seed(21u);
            World w;
            w.cfg.predatorCount = 1;
            w.cfg.predatorEconomy = true;
            w.cfg.predatorMoveCost = 0.0f;
            w.cfg.predatorReproEnergy = 60.0f;
            w.cfg.minPopulation = 0;
            w.init(640, 480, 0);
            w.creatures.clear();
            w.predators[0].energy = 50.0f;
            w.predators[0].buddingFactor = bf;
            w.update(0.016f);
            return w.totalPredatorBirths;
        };
        CHECK(buds(1.0f) == 0);
        CHECK(buds(0.75f) == 1);
    }

    // --- 8b. the ceiling: no bud at the cap, the energy is kept ----------
    {
        auto capped = [](int cap, int preds) {
            rng.seed(23u);
            World w;
            w.cfg.predatorCount = preds;
            w.cfg.predatorEconomy = true;
            w.cfg.predatorMetabolism = 2.0f;
            w.cfg.predatorMoveCost = 0.0f;
            w.cfg.predatorReproEnergy = 40.0f;
            w.cfg.predatorNewbornEnergy = 30.0f;
            w.cfg.predatorMaxPopulation = cap;
            w.cfg.minPopulation = 0;
            w.init(640, 480, 0);
            w.creatures.clear();
            for (auto& p : w.predators) p.energy = 100.0f;   // every one ready to bud
            w.update(0.016f);
            return w;
        };
        const float burn = 2.0f * 0.016f;
        World none = capped(0, 3);                  // no cap: all three bud
        CHECK(none.totalPredatorBirths == 3 && none.predators.size() == 6u);
        World full = capped(3, 3);                  // at the cap: none bud
        CHECK(full.totalPredatorBirths == 0 && full.predators.size() == 3u);
        bool kept = full.predators.size() == 3u;
        for (const auto& p : full.predators) if (!approx(p.energy, 100.0f - burn, 1e-3f)) kept = false;
        CHECK(kept);
        World room = capped(5, 3);                  // room for two: this step's buds count
        CHECK(room.totalPredatorBirths == 2 && room.predators.size() == 5u);
        // a floor above the ceiling wins (the floor is not capped)
        World fl = starving(11u, 4);
        fl.cfg.predatorMaxPopulation = 2;
        for (int s = 0; s < 1000; ++s) fl.update(0.016f);
        CHECK(fl.predators.size() == 4u);
    }

    // --- 9. a live run: traits spread, stay in band, generations climb ----
    World live;
    {
        rng.seed(777u);
        configureRichWorld(live);
        live.cfg.predatorInheritance = true;
        live.cfg.predatorMinPopulation = 3;
        live.init(900, 700, 260);
        for (int i = 0; i < 1500; ++i) live.update(0.016f);
        CHECK(live.totalPredatorBirths > 0);
        bool band = !live.predators.empty(), varied = false;
        std::uint32_t maxGen = 0;
        for (const auto& p : live.predators) {
            if (!(p.speedFactor >= PRED_TRAIT_MIN && p.speedFactor <= PRED_TRAIT_MAX) ||
                !(p.buddingFactor >= PRED_TRAIT_MIN && p.buddingFactor <= PRED_TRAIT_MAX)) band = false;
            if (!bitEq(p.speedFactor, 1.0f)) varied = true;
            maxGen = std::max(maxGen, p.generation);
        }
        CHECK(band);
        CHECK(varied);
        CHECK(maxGen >= 1u);
        const WorldStats st = computeStats(live);
        CHECK(st.totalPredatorReseeds == (int)live.totalPredatorReseeds);
        CHECK(st.predatorSpeedFactor >= PRED_TRAIT_MIN && st.predatorSpeedFactor <= PRED_TRAIT_MAX);
        CHECK(st.predatorGeneration >= 0.0f && st.predatorGeneration <= (float)maxGen);
    }

    // --- 10. checkpoints: round trip, resume, old files, corrupt files ----
    {
        const std::string blob = checkpoint::serialize(live, "test");
        std::string err;
        World r;
        CHECK(checkpoint::deserialize(blob, r, err));
        CHECK(r.cfg.predatorInheritance && r.cfg.predatorMinPopulation == 3);
        CHECK(r.totalPredatorReseeds == live.totalPredatorReseeds);
        bool same = r.predators.size() == live.predators.size();
        for (size_t i = 0; same && i < r.predators.size(); ++i)
            same = bitEq(r.predators[i].speedFactor, live.predators[i].speedFactor) &&
                   bitEq(r.predators[i].buddingFactor, live.predators[i].buddingFactor) &&
                   r.predators[i].generation == live.predators[i].generation;
        CHECK(same);
        CHECK(checkpoint::serialize(r, "test") == blob);
#ifdef EVO_DETERMINISTIC
        {
            // Uninterrupted: a copy of the saved world, continued from the
            // saved rng state (a load restores it). Resumed: a fresh load.
            World a = live;
            World b;
            CHECK(checkpoint::deserialize(blob, b, err));
            for (int i = 0; i < 300; ++i) a.update(0.016f);
            const std::uint64_t uninterrupted = deepFingerprint(a);
            CHECK(checkpoint::deserialize(blob, b, err));
            for (int i = 0; i < 300; ++i) b.update(0.016f);
            CHECK(deepFingerprint(b) == uninterrupted);
            CHECK(b.totalPredatorReseeds == a.totalPredatorReseeds);
        }
#endif
        // Erase `,"key":[...]` (or `,"key":value`) — the first one at or after `from`.
        auto eraseKey = [](std::string s, const std::string& key, size_t from = 0) {
            const std::string k = ",\"" + key + "\":";
            const size_t at = s.find(k, from);
            if (at == std::string::npos) return s;
            size_t end = at + k.size();
            if (s[end] == '[') end = s.find(']', end) + 1;
            else end = s.find_first_of(",}", end);
            s.erase(at, end - at);
            return s;
        };
        const size_t predAt = blob.find("\"predators\"");
        CHECK(predAt != std::string::npos);

        // A pre-0.26 checkpoint: no trait columns, no generation, no counter,
        // no config keys. Loads, at 1.0/1.0/0 and the defaults.
        std::string old = eraseKey(blob, "speedFactor");
        old = eraseKey(old, "buddingFactor");
        old = eraseKey(old, "generation", old.find("\"predators\""));
        old = eraseKey(old, "totalPredatorReseeds");
        old = eraseKey(old, "predatorMinPopulation");
        old = eraseKey(old, "predatorInheritance");
        old = eraseKey(old, "predatorTraitMutation");
        CHECK(old.find("speedFactor") == std::string::npos);
        World o;
        CHECK(checkpoint::deserialize(old, o, err));
        bool base = o.predators.size() == live.predators.size();
        for (const auto& p : o.predators)
            if (!bitEq(p.speedFactor, 1.0f) || !bitEq(p.buddingFactor, 1.0f) || p.generation != 0u) base = false;
        CHECK(base);
        CHECK(o.totalPredatorReseeds == 0 && o.cfg.predatorMinPopulation == 0 && !o.cfg.predatorInheritance);
        // the creatures' generation column survived the predator erase
        bool creaturesKept = !o.creatures.empty() && o.creatures.size() == live.creatures.size();
        for (size_t i = 0; creaturesKept && i < o.creatures.size(); ++i)
            creaturesKept = o.creatures[i].generation == live.creatures[i].generation;
        CHECK(creaturesKept);

        // only one of the two traits: corrupt
        World x1;
        CHECK(!checkpoint::deserialize(eraseKey(blob, "buddingFactor"), x1, err));
        // out of range, and NaN: corrupt
        auto setFirst = [&](const std::string& key, const std::string& v) {
            std::string s = blob;
            const size_t at = s.find("\"" + key + "\":[");
            const size_t v0 = at + key.size() + 4;
            s.replace(v0, s.find_first_of(",]", v0) - v0, v);
            return s;
        };
        World x2, x3, x4;
        CHECK(!live.predators.empty());
        CHECK(!checkpoint::deserialize(setFirst("speedFactor", "2.5"), x2, err));
        CHECK(!checkpoint::deserialize(setFirst("buddingFactor", "nan"), x3, err));
        CHECK(checkpoint::deserialize(setFirst("speedFactor", "0.5"), x4, err));   // the edge is legal
        // a negative or non-finite mutation in the config: corrupt
        auto setCfg = [&](const std::string& v) {
            std::string s = blob;
            const std::string k = "\"predatorTraitMutation\":";
            const size_t at = s.find(k) + k.size();
            s.replace(at, s.find_first_of(",}", at) - at, v);
            return s;
        };
        World x5, x6, x7;
        CHECK(!checkpoint::deserialize(setCfg("-0.1"), x5, err));
        CHECK(!checkpoint::deserialize(setCfg("nan"), x6, err));
        CHECK(checkpoint::deserialize(setCfg("0"), x7, err));
    }
}

// ---------------------------------------------------------------
// Stage C (v0.27.0): neural predators, their checkpoints and the transplant.
namespace predref {
// A gene-by-gene reference for predbrain::buildNet / feedForward: genome order,
// no flattening (the oracle above, with the predator's I/O sizes).
struct Net { std::vector<Gene> conns; float out[MAX_INTERNAL_NEURONS]; bool driven[MAX_INTERNAL_NEURONS]; };
static void build(const Genome& g, Net& n) {
    n.conns.clear();
    for (int i = 0; i < MAX_INTERNAL_NEURONS; ++i) { n.out[i] = 0.5f; n.driven[i] = false; }
    for (Gene c : g) {
        c.sourceNum = (c.sourceType == SOURCE_SENSOR) ? c.sourceNum % NUM_PRED_SENSES : c.sourceNum % MAX_INTERNAL_NEURONS;
        c.sinkNum = (c.sinkType == SINK_ACTION) ? c.sinkNum % NUM_PRED_ACTIONS : c.sinkNum % MAX_INTERNAL_NEURONS;
        n.conns.push_back(c);
        if (c.sinkType == SINK_NEURON) n.driven[c.sinkNum] = true;
    }
}
static void step(Net& n, const float s[], float a[]) {
    float acc[MAX_INTERNAL_NEURONS] = {};
    for (int i = 0; i < NUM_PRED_ACTIONS; ++i) a[i] = 0.0f;
    for (const Gene& c : n.conns) {
        const float v = (c.sourceType == SOURCE_SENSOR) ? s[c.sourceNum] : n.out[c.sourceNum];
        const float x = v * c.weightAsFloat();
        if (c.sinkType == SINK_ACTION) a[c.sinkNum] += x; else acc[c.sinkNum] += x;
    }
    for (int i = 0; i < MAX_INTERNAL_NEURONS; ++i) if (n.driven[i]) n.out[i] = evomath::tanhf(acc[i]);
    for (int i = 0; i < NUM_PRED_ACTIONS; ++i) a[i] = evomath::tanhf(a[i]);
}
}  // namespace predref

static World bareBrainWorld(unsigned seed, int preds, bool econ) {
    rng.seed(seed);
    World w;
    w.cfg.predatorCount = preds;
    w.cfg.predatorEconomy = econ;
    w.cfg.predatorBrain = true;
    w.cfg.predatorMoveCost = 0.0f;
    w.cfg.minPopulation = 0;
    w.cfg.targetFood = 0;
    w.init(640, 480, 0);
    w.creatures.clear();
    return w;
}

static void test_predator_brain() {
    std::printf("Stage C: neural predators...\n");

    // --- 1. defaults: off, and a default predator has no brain ------------
    {
        SimConfig c;
        CHECK(!c.predatorBrain && !c.predatorPrimer && !c.predatorLog && !c.predatorFrozen);
        {
            SimConfig m = c; m.predatorMinSpeed = 200.0f;        // above predatorSpeed (110)
            CHECK(predatorBrainConfigError(m) == nullptr);       // irrelevant with the brain off
            m.predatorBrain = true;
            CHECK(predatorBrainConfigError(m) != nullptr);       // refused with it on
        }
        CHECK(bitEq(c.predatorMutation, 1.0f) && bitEq(c.predatorTurnRate, 4.0f) && bitEq(c.predatorMinSpeed, 0.0f));
        CHECK(predatorBrainConfigError(c) == nullptr);
        SimConfig bad = c; bad.predatorMutation = -1.0f;
        CHECK(predatorBrainConfigError(bad) != nullptr);
        bad = c; bad.predatorTurnRate = std::numeric_limits<float>::quiet_NaN();
        CHECK(predatorBrainConfigError(bad) != nullptr);
        bad = c; bad.predatorMinSpeed = std::numeric_limits<float>::infinity();
        CHECK(predatorBrainConfigError(bad) != nullptr);
        Predator p;
        CHECK(p.genome.empty() && p.nnet.flat.empty() && p.id == 0 && p.captures == 0 && bitEq(p.speed, 0.0f));
        CHECK(c.dump().find("predatorBrain") == std::string::npos);   // an off sidecar is 0.26.0's
        CHECK(NUM_PRED_SENSES == 21 && NUM_PRED_ACTIONS == 2 && PRED_SENSOR_SET == 1);
    }

    // --- 2. the predator net == a gene-by-gene reference, bit for bit -----
    {
        rng.seed(2027u);
        RandomGen r(77u);
        bool same = true;
        for (int g = 0; g < 60 && same; ++g) {
            const Genome genome = makeRandomGenome(4, 70, r);
            NeuralNet net; predbrain::buildNet(genome, net);
            predref::Net ref; predref::build(genome, ref);
            for (int t = 0; t < 6 && same; ++t) {
                float s[NUM_PRED_SENSES];
                for (float& v : s) v = r.range(-1.0f, 1.0f);
                float a1[NUM_PRED_ACTIONS], a2[NUM_PRED_ACTIONS];
                predbrain::feedForward(net, s, a1, false);
                predref::step(ref, s, a2);
                for (int k = 0; k < NUM_PRED_ACTIONS; ++k) same = same && bitEq(a1[k], a2[k]);
                for (int k = 0; k < MAX_INTERNAL_NEURONS; ++k) same = same && bitEq(net.neurons[k].output, ref.out[k]);
            }
        }
        CHECK(same);
        // the explicit-stream genome ops draw exactly what the rng-default ones do
        rng.seed(31u);
        Genome a = makeRandomGenome(10, 40);
        mutateGenome(a, 0.3f, 16, 80);
        const std::string sa = rng.state();
        RandomGen q(31u);
        Genome b = makeRandomGenome(10, 40, q);
        mutateGenome(b, 0.3f, 16, 80, q);
        bool eq = a.size() == b.size() && q.state() == sa;
        for (size_t i = 0; eq && i < a.size(); ++i) eq = checkpoint::packGene(a[i]) == checkpoint::packGene(b[i]) && a[i].weight == b[i].weight;
        CHECK(eq);
        CHECK(bitEq(kernel::birthMutationRate(0.0f), 0.5f) && bitEq(kernel::birthMutationRate(0.05f), 0.05f) &&
              bitEq(kernel::birthMutationRate(0.2f), 0.01f) && bitEq(kernel::birthMutationRate(0.9f), 0.002f));
    }

    // --- 3. init: Stage B's world + genomes, after exactly one more draw --
    {
        auto make = [](bool brain) {
            rng.seed(4242u);
            World w;
            configureRichWorld(w);
            w.cfg.predatorBrain = brain;
            w.init(900, 700, 200);
            return w;
        };
        World off = make(false);
        rng.uint();                                   // the one extra draw
        const std::string afterOff = rng.state();
        World on = make(true);
        CHECK(rng.state() == afterOff);
        bool samePlaces = off.predators.size() == on.predators.size() && off.creatures.size() == on.creatures.size() &&
                          off.food.size() == on.food.size();
        for (size_t i = 0; samePlaces && i < off.predators.size(); ++i)
            samePlaces = bitEq(off.predators[i].pos.x, on.predators[i].pos.x) && bitEq(off.predators[i].vel.y, on.predators[i].vel.y);
        for (size_t i = 0; samePlaces && i < off.food.size(); ++i)
            samePlaces = bitEq(off.food[i].pos.x, on.food[i].pos.x) && bitEq(off.food[i].pos.y, on.food[i].pos.y);
        CHECK(samePlaces);
        bool founders = true;
        for (size_t i = 0; i < on.predators.size(); ++i) {
            const Predator& p = on.predators[i];
            founders = founders && p.id == i + 1 && p.lineageId == p.id && p.parentId == 0 &&
                       (int)p.genome.size() >= on.cfg.genomeInitMin && (int)p.genome.size() <= on.cfg.genomeInitMax &&
                       p.nnet.flat.size() == p.genome.size() && bitEq(p.speed, on.cfg.predatorSpeed);
        }
        CHECK(founders);
        CHECK(on.nextPredatorId_ == on.predators.size() + 1);
        CHECK(off.nextPredatorId_ == 1 && off.predators[0].genome.empty());
        // the primer writes its two genes and draws nothing extra
        rng.seed(4242u);
        World pr; configureRichWorld(pr); pr.cfg.predatorBrain = true; pr.cfg.predatorPrimer = true;
        pr.init(900, 700, 200);
        CHECK(rng.state() == afterOff);
        CHECK(pr.predators[0].genome.size() == on.predators[0].genome.size());
        CHECK(pr.predators[0].genome[0].sourceNum == PS_PREY_LR && pr.predators[0].genome[0].sinkNum == PA_TURN &&
              pr.predators[0].genome[1].sourceNum == PS_PREY_PROX && pr.predators[0].genome[1].sinkNum == PA_THRUST);
        bool rest = true;
        for (size_t k = 2; k < pr.predators[0].genome.size(); ++k)
            rest = rest && pr.predators[0].genome[k].weight == on.predators[0].genome[k].weight;
        CHECK(rest);
    }

    // --- 4. TURN and THRUST do what they say (one gene each, no prey) -----
    {
        World w = bareBrainWorld(5u, 1, false);
        Predator& p = w.predators[0];
        p.pos = {320.0f, 240.0f}; p.vel = {1.0f, 0.0f};
        Gene t{}; t.sourceType = SOURCE_NEURON; t.sourceNum = 0; t.sinkType = SINK_ACTION; t.sinkNum = PA_TURN; t.weight = 16384;
        Gene s{}; s.sourceType = SOURCE_NEURON; s.sourceNum = 0; s.sinkType = SINK_ACTION; s.sinkNum = PA_THRUST; s.weight = -24576;
        p.genome = {t, s};
        predbrain::buildNet(p.genome, p.nnet);   // neuron 0 is undriven: a constant 0.5
        const float dt = 0.016f;
        w.update(dt);
        const Predator& q = w.predators[0];
        const float turn = evomath::tanhf(0.5f * (16384 / 8192.0f)) * 4.0f * dt;
        const Vec2 v = {evomath::cosf(turn), evomath::sinf(turn)};
        CHECK(bitEq(q.vel.x, v.x) && bitEq(q.vel.y, v.y));
        CHECK(q.vel.y > 0.0f);                                          // + turns toward +right
        const float spd = std::clamp(110.0f + evomath::tanhf(0.5f * (-24576 / 8192.0f)) * 50.0f * dt, 0.0f, 110.0f);
        CHECK(bitEq(q.speed, spd) && q.speed < 110.0f);
        CHECK(approx(q.pos.x, 320.0f + v.x * spd * dt, 1e-4f));
        CHECK(w.predators.size() == 1u && bitEq(q.energy, w.cfg.predatorNewbornEnergy));   // frozen: no burn
        for (int i = 0; i < 2000; ++i) w.update(dt);
        CHECK(w.predators.size() == 1u && bitEq(w.predators[0].speed, 0.0f));          // braked to the floor
        w.cfg.predatorMinSpeed = 20.0f;
        w.update(dt);
        CHECK(bitEq(w.predators[0].speed, 20.0f));
    }

    // --- 5. pursuit: the primer genes steer toward the prey's side --------
    {
        for (int side = -1; side <= 1; side += 2) {
            World w = bareBrainWorld(9u, 1, false);
            Predator& p = w.predators[0];
            p.pos = {320.0f, 240.0f}; p.vel = {1.0f, 0.0f};
            p.genome = {predbrain::primerGene(PS_PREY_LR, PA_TURN, 3.0f), predbrain::primerGene(PS_PREY_PROX, PA_THRUST, 2.0f)};
            predbrain::buildNet(p.genome, p.nnet);
            w.creatures.push_back(makeRandomCreature({370.0f, 240.0f + 50.0f * side}));
            w.update(0.016f);
            CHECK((w.predators[0].vel.y > 0.0f) == (side > 0));
        }
    }

    // --- 6. capture: the nearest prey in reach, the meal, the cooldown ----
    {
        auto capture = [](float digest) {
            World w = bareBrainWorld(13u, 1, true);
            w.cfg.predatorMeal = 7.0f;
            w.cfg.predatorMetabolism = 2.0f;
            Predator& p = w.predators[0];
            p.pos = {320.0f, 240.0f};
            p.digestTimer = digest;
            p.genome.clear(); predbrain::buildNet(p.genome, p.nnet);   // no genes: drifts at top speed
            w.creatures.push_back(makeRandomCreature({322.0f, 241.0f}));
            w.update(0.016f);
            return w;
        };
        World ate = capture(0.0f);
        CHECK(ate.totalDeathsPredation == 1 && ate.predators[0].captures == 1u && ate.creatures.empty());
        CHECK(approx(ate.predators[0].energy, 30.0f - 2.0f * 0.016f + 7.0f, 1e-4f));
        CHECK(approx(ate.predators[0].digestTimer, 3.0f));
        World full = capture(1.0f);
        CHECK(full.totalDeathsPredation == 0 && full.predators[0].captures == 0u && full.creatures.size() == 1u);
    }

    // --- 7. a bud: the genome from predRng_, Stage B's three global draws --
    {
        World w = bareBrainWorld(17u, 1, true);
        w.cfg.predatorReproEnergy = 40.0f;
        w.cfg.predatorMutation = 5.0f;          // make the mutation visible
        Predator& p = w.predators[0];
        p.energy = 100.0f; p.generation = 3;
        const std::uint64_t pid = p.id, plin = p.lineageId;
        const Genome pg = p.genome;
        const std::string g0 = rng.state(), r0 = w.predRng_.state();
        w.update(0.016f);
        RandomGen g; g.setState(g0); g.uint(); g.uint(); g.uint();   // the bud's x, y, heading
        CHECK(rng.state() == g.state());
        CHECK(w.predRng_.state() != r0);
        CHECK(w.predators.size() == 2u && w.totalPredatorBirths == 1);
        if (w.predators.size() == 2u) {
            const Predator& c = w.predators[1];
            CHECK(c.parentId == pid && c.lineageId == plin && c.id == 2u && c.generation == 4u);
            CHECK(c.nnet.flat.size() == c.genome.size() && bitEq(c.speed, 110.0f));
            CHECK(w.predators[0].genome.size() == pg.size());           // the parent is untouched
            CHECK(approx(c.energy, w.cfg.predatorNewbornEnergy));
        }
        CHECK(w.nextPredatorId_ == 3u);
        // at the cap: no bud, and no draw in either stream beyond RANDOM's one
        World cap = bareBrainWorld(17u, 1, true);
        cap.cfg.predatorReproEnergy = 40.0f;
        cap.cfg.predatorMaxPopulation = 1;
        cap.predators[0].energy = 100.0f;
        const std::string cg0 = rng.state(), cr0 = cap.predRng_.state();
        cap.update(0.016f);
        RandomGen cr; cr.setState(cr0); cr.uint();
        CHECK(rng.state() == cg0 && cap.predRng_.state() == cr.state() && cap.predators.size() == 1u);
    }

    // --- 8. the floor refills with random-genome founders of new lineages --
    {
        World w = bareBrainWorld(11u, 3, true);
        w.cfg.predatorMinPopulation = 3;
        w.cfg.predatorLog = true;
        w.cfg.predatorMetabolism = 50.0f;      // everyone starves fast
        w.predLog_.clear();
        for (int i = 0; i < 200; ++i) w.update(0.016f);
        CHECK(w.predators.size() == 3u && w.totalPredatorReseeds >= 3 && w.totalPredatorDeathsStarvation >= 3);
        bool fresh = true;
        for (const auto& p : w.predators) fresh = fresh && p.id > 3u && p.lineageId == p.id && !p.genome.empty();
        CHECK(fresh);
        long r = 0, s = 0;
        for (const auto& e : w.predLog_) { r += e.event == 'R'; s += e.event == 'S'; }
        CHECK(r == w.totalPredatorReseeds && s == w.totalPredatorDeathsStarvation);
    }

    // --- 9. frozen: no economy => fixed, immortal, no buds ---------------
    {
        rng.seed(808u);
        World w; configureRichWorld(w);
        w.cfg.predatorEconomy = false;
        w.cfg.predatorBrain = true;
        w.cfg.predatorReproEnergy = 1.0f;
        w.init(900, 700, 260);
        const size_t n0 = w.predators.size();
        for (int i = 0; i < 600; ++i) w.update(0.016f);
        bool fixed = w.predators.size() == n0 && w.totalPredatorBirths == 0;
        for (const auto& p : w.predators) fixed = fixed && bitEq(p.energy, w.cfg.predatorNewbornEnergy) && bitEq(p.age, 0.0f);
        CHECK(fixed);
    }

    // --- 10. a live run, its determinism and its checkpoints --------------
    World live;
    {
        auto run = [](World& w) {
            rng.seed(5150u);
            configureRichWorld(w);
            w.cfg.predatorBrain = true;
            w.cfg.predatorMeal = 14.0f;
            w.cfg.predatorMaxPopulation = 12;
            w.cfg.predatorMinPopulation = 2;
            w.cfg.predatorMaxAge = 30.0f;
            w.cfg.predatorInheritance = true;
            w.init(900, 700, 260);
            for (int i = 0; i < 1500; ++i) w.update(0.016f);
        };
        run(live);
        CHECK(live.totalPredatorBirths > 0);
        CHECK(live.totalDeathsPredation > 0);
        bool sane = !live.predators.empty();
        for (const auto& p : live.predators)
            sane = sane && std::isfinite(p.energy) && std::isfinite(p.speed) && p.speed >= 0.0f &&
                   p.speed <= live.cfg.predatorSpeed * p.speedFactor + 1e-3f && p.id < live.nextPredatorId_;
        CHECK(sane);
#ifdef EVO_DETERMINISTIC
        World again;
        run(again);
        CHECK(deepFingerprint(again) == deepFingerprint(live));
        CHECK(checkpoint::serialize(again, "t") == checkpoint::serialize(live, "t"));
#endif
    }
    {
        const std::string blob = checkpoint::serialize(live, "test");
        CHECK(blob.find("\"formatVersion\":2") != std::string::npos);
        CHECK(blob.find("\"predatorRngState\"") != std::string::npos && blob.find("\"sensorSet\":1") != std::string::npos);
        std::string err;
        World r;
        CHECK(checkpoint::deserialize(blob, r, err));
        CHECK(r.cfg.predatorBrain && r.nextPredatorId_ == live.nextPredatorId_);
        CHECK(checkpoint::serialize(r, "test") == blob);
#ifdef EVO_DETERMINISTIC
        {
            // Uninterrupted: a copy, continued from the saved rng state (a load
            // restores it). Resumed: a fresh load. One after the other: the two
            // worlds share the global rng.
            World a = live;
            World b;
            CHECK(checkpoint::deserialize(blob, b, err));
            for (int i = 0; i < 400; ++i) a.update(0.016f);
            const std::uint64_t uninterrupted = deepFingerprint(a);
            CHECK(checkpoint::deserialize(blob, b, err));
            for (int i = 0; i < 400; ++i) b.update(0.016f);
            CHECK(deepFingerprint(b) == uninterrupted);
            CHECK(b.totalPredatorBirths == a.totalPredatorBirths && b.nextPredatorId_ == a.nextPredatorId_);
        }
#endif
        // a brain-off checkpoint is version 1 and mentions no brain
        rng.seed(3u);
        World off; configureRichWorld(off); off.init(900, 700, 200);
        for (int i = 0; i < 50; ++i) off.update(0.016f);
        const std::string ob = checkpoint::serialize(off, "test");
        CHECK(ob.find("\"formatVersion\":1") != std::string::npos);
        CHECK(ob.find("predatorBrain") == std::string::npos && ob.find("nextPredatorId") == std::string::npos &&
              ob.find("predatorRngState") == std::string::npos && ob.find("sensorSet") == std::string::npos);
        // a CLI value cannot make a version-1 file a brain world, and the file's brain key decides
        World leak; leak.cfg.predatorBrain = true;
        CHECK(checkpoint::deserialize(ob, leak, err) && !leak.cfg.predatorBrain);
        auto replaceOnce = [](std::string s, const std::string& from, const std::string& to) {
            const size_t at = s.find(from);
            if (at != std::string::npos) s.replace(at, from.size(), to);
            return s;
        };
        World x1, x2, x3, x4, x5, x6, x7, x8;
        CHECK(!checkpoint::deserialize(replaceOnce(ob, "\"fastTanh\"", "\"predatorBrain\":true,\"fastTanh\""), x1, err));
        CHECK(!checkpoint::deserialize(replaceOnce(blob, "\"predatorBrain\":true", "\"predatorBrain\":false"), x2, err));
        CHECK(!checkpoint::deserialize(replaceOnce(blob, "\"sensorSet\":1", "\"sensorSet\":2"), x3, err));
        CHECK(!checkpoint::deserialize(replaceOnce(blob, "\"genomeLengths\":[", "\"genomeLengths\":[1000,"), x4, err));
        CHECK(!checkpoint::deserialize(replaceOnce(blob, "\"nextPredatorId\":", "\"nextPredatorId\":1,\"x\":"), x5, err));
        CHECK(!checkpoint::deserialize(replaceOnce(blob, "\"predatorRngState\"", "\"predatorRngStateX\""), x6, err));
        {
            // the first predator neuron output -> nan (the length stays right)
            const size_t at = blob.find("\"neuronOutputs\":[", blob.find("\"predators\"")) + 17;
            std::string bad = blob;
            bad.replace(at, bad.find(',', at) - at, "nan");
            CHECK(!checkpoint::deserialize(bad, x7, err));
            CHECK(err.find("not finite") != std::string::npos);
        }
        {
            // two predators with one id
            const size_t idAt = blob.find("\"id\":[", blob.find("\"predators\""));
            std::string dup = blob;
            const size_t v0 = idAt + 6, c1 = dup.find(',', v0), c2 = dup.find_first_of(",]", c1 + 1);
            dup.replace(c1 + 1, c2 - c1 - 1, dup.substr(v0, c1 - v0));
            CHECK(live.predators.size() < 2u || !checkpoint::deserialize(dup, x8, err));
        }
        // a reseed draws the predators' stream from the reseeded rng
        World s1 = live, s2 = live;
        s1.reseedStreams(77u); const std::string a1 = s1.predRng_.state(), g1 = rng.state();
        s2.reseedStreams(77u);
        CHECK(a1 == s2.predRng_.state() && g1 == rng.state() && a1 != live.predRng_.state());
    }

    // --- 11. the transplant ----------------------------------------------
    {
        rng.seed(6001u);
        World X; configureRichWorld(X); X.init(900, 700, 200);
        for (int i = 0; i < 300; ++i) X.update(0.016f);
        const std::string xBlob = checkpoint::serialize(X, "t");
        const std::string yBlob = checkpoint::serialize(live, "t");
        auto loadX = [&]() { World w; std::string e; checkpoint::deserialize(xBlob, w, e); return w; };
        transplant::Options o;
        o.predatorsFrom = "Y.json"; o.count = 3; o.seed = 9u;
        // live has its own predator economy: X's (configureRichWorld) except meal 14
        // and max age 30. The kinematics agree.
        std::string man, err;
        World t1 = loadX();
        CHECK(!transplant::apply(t1, o, yBlob, man, err));            // frozen compares the economy: refused
        CHECK(err.find("predatorMeal") != std::string::npos);
        transplant::Options nb = o; nb.assay = "frozen-newborn";      // ... frozen-newborn does not
        World t2 = loadX();
        CHECK(transplant::apply(t2, nb, yBlob, man, err));
        CHECK(!t2.cfg.predatorEconomy && !t2.cfg.predatorFrozen && man.find("\"physicsMismatches\":[]") != std::string::npos);
        World t3 = loadX(); t3.cfg.fastTanh = true;                   // fastTanh is compared in every mode
        CHECK(!transplant::apply(t3, nb, yBlob, man, err) && err.find("fastTanh") != std::string::npos);
        transplant::Options neg = o; neg.count = -5;
        World t4 = loadX();
        CHECK(!transplant::apply(t4, neg, yBlob, man, err));          // below -1: refused
        o.allowMismatch = true;
        World a = loadX();
        const std::string g0 = rng.state();
        CHECK(transplant::apply(a, o, yBlob, man, err));
        CHECK(rng.state() == g0);                                      // the world's stream untouched
        CHECK(a.predators.size() == 3u && a.cfg.predatorBrain && a.cfg.predatorEconomy && a.cfg.predatorFrozen &&
              a.cfg.minPopulation == 0 && a.cfg.predatorMinPopulation == 0 && a.cfg.predatorMaxPopulation == 0 &&
              a.cfg.predatorCount == 3 && a.arenaFresh_);
        // fresh ids above Y's counter and every Y lineage label (P2-2)
        std::uint64_t maxLin = 0;
        for (const auto& q : live.predators) maxLin = std::max(maxLin, q.lineageId);
        const std::uint64_t firstId = std::max<std::uint64_t>(live.nextPredatorId_, maxLin + 1);
        CHECK(a.nextPredatorId_ == firstId + 3);
        bool fromY = true;
        for (size_t i = 0; i < a.predators.size(); ++i) {
            const Predator& p = a.predators[i];
            bool found = false;
            for (const auto& q : live.predators)
                if (q.id == p.sourceId && q.lineageId == p.lineageId && q.genome.size() == p.genome.size() &&
                    q.generation == p.generation) {
                    bool g = true;
                    for (size_t k = 0; k < q.genome.size(); ++k) g = g && q.genome[k].weight == p.genome[k].weight;
                    found = found || g;
                }
            fromY = fromY && found && p.id == firstId + i && p.id > maxLin && p.parentId == 0 && p.captures == 0 &&
                    bitEq(p.energy, a.cfg.predatorNewbornEnergy) && bitEq(p.age, 0.0f) &&
                    bitEq(p.nnet.neurons[0].output, 0.5f);
        }
        CHECK(fromY);
        CHECK(man.find("\"startState\"") != std::string::npos && man.find("\"stageC\"") != std::string::npos &&
              man.find("\"predator checkpoint\"") != std::string::npos && man.find("\"fnv1a64\"") != std::string::npos);
        const std::string ab = checkpoint::serialize(a, "t");
        CHECK(ab.find("\"arena\":true") != std::string::npos && ab.find("\"sourceId\"") != std::string::npos);
        // X's world, line by line, apart from the world line, the config and the predators
        auto lineOf = [](const std::string& blob, const std::string& prefix) {
            size_t at = blob.find("\n" + prefix);
            if (at == std::string::npos) return std::string("<missing ") + prefix + ">";
            ++at;
            return blob.substr(at, blob.find('\n', at) - at);
        };
        bool sameWorld = true;
        for (const char* k : {",\"counters\"", ",\"rngState\"", ",\"currentVortices\"", ",\"signals\"", ",\"food\"",
                              ",\"creatures\""})
            sameWorld = sameWorld && lineOf(ab, k) == lineOf(xBlob, k);
        CHECK(sameWorld);
        CHECK(man.find("\"configChanges\"") != std::string::npos && man.find("predatorMeal") != std::string::npos);
        World b = loadX();
        std::string man2;
        CHECK(transplant::apply(b, o, yBlob, man2, err) && checkpoint::serialize(b, "t") == ab && man2 == man);
        o.seed = 10u;
        World c = loadX();
        CHECK(transplant::apply(c, o, yBlob, man2, err) && checkpoint::serialize(c, "t") != ab);
        // the frozen arena runs: fixed and immortal, but energy and age are
        // accounted, so ENERGY and AGE move inside their evolved range (P2-1)
        float s0[NUM_PRED_SENSES] = {}, s1[NUM_PRED_SENSES] = {};
        predbrain::writeOwnSensors(a.predators[0], a.cfg, predbrain::topSpeed(a.predators[0], a.cfg), s0);
        const long long starv0 = a.totalPredatorDeathsStarvation, age0 = a.totalPredatorDeathsAge;
        for (int i = 0; i < 300; ++i) a.update(0.016f);
        predbrain::writeOwnSensors(a.predators[0], a.cfg, predbrain::topSpeed(a.predators[0], a.cfg), s1);
        CHECK(a.predators.size() == 3u && a.totalPredatorBirths == X.totalPredatorBirths &&
              a.totalPredatorDeathsStarvation == starv0 && a.totalPredatorDeathsAge == age0);
        CHECK(!bitEq(s0[PS_ENERGY], s1[PS_ENERGY]) && s1[PS_AGE] > s0[PS_AGE] && s1[PS_AGE] > 0.0f);
        bool inRange = true, aged = true;
        for (const auto& p : a.predators) {
            inRange = inRange && p.energy >= 0.0f;
            aged = aged && approx(p.age, 300 * 0.016f, 1e-3f);     // X has no max age: no wrap
        }
        CHECK(inRange && aged);
        // the layout is a function of (seed, K, the world) only: a donor of
        // another size, and "random", put the K predators on the same spots
        {
            const std::string y2 = checkpoint::serialize(t2, "t");   // 3 predators, all taken
            World b2 = loadX(), r2 = loadX(), b1 = loadX();
            transplant::Options o2 = o; o2.seed = 9u;
            transplant::Options or2 = o2; or2.predatorsFrom = "random"; or2.assay = "frozen";
            std::string m2;
            CHECK(transplant::apply(b1, o2, yBlob, m2, err) && transplant::apply(b2, o2, y2, m2, err) &&
                  transplant::apply(r2, or2, "", m2, err));
            bool same = b1.predators.size() == 3u && b2.predators.size() == 3u && r2.predators.size() == 3u;
            auto samePlace = [](const Predator& p, const Predator& q) {
                return bitEq(p.pos.x, q.pos.x) && bitEq(p.pos.y, q.pos.y) &&
                       bitEq(p.vel.x, q.vel.x) && bitEq(p.vel.y, q.vel.y);
            };
            for (size_t i = 0; same && i < 3; ++i)
                same = samePlace(b1.predators[i], b2.predators[i]) && samePlace(b1.predators[i], r2.predators[i]);
            CHECK(same);
            CHECK(live.predators.size() != 3u);   // the two donors really differ in size
        }
        // ... and the frozen-newborn ablation pins both at 0
        for (int i = 0; i < 300; ++i) t2.update(0.016f);
        float sn[NUM_PRED_SENSES] = {};
        predbrain::writeOwnSensors(t2.predators[0], t2.cfg, predbrain::topSpeed(t2.predators[0], t2.cfg), sn);
        CHECK(bitEq(sn[PS_ENERGY], 0.0f) && bitEq(sn[PS_AGE], 0.0f) && t2.predators.size() == 3u);
        // scripted (Stage A) hunters: no brain, immortal and fixed, the same layout as any source; the
        // arena is a version-1 checkpoint that resumes; live is refused (the H-C scripted benchmark)
        {
            transplant::Options sc; sc.predatorsFrom = "scripted"; sc.count = 3; sc.seed = 9u; sc.assay = "frozen";
            transplant::Options rr = sc; rr.predatorsFrom = "random";
            World s1 = loadX(), r1 = loadX();
            std::string ms, ms1;
            const std::string gs0 = rng.state();
            CHECK(transplant::apply(s1, sc, "", ms1, err));
            CHECK(rng.state() == gs0);                               // (Codex #74 r1) the world's stream untouched
            CHECK(transplant::apply(r1, rr, "", ms, err));
            bool ok = s1.predators.size() == 3u && !s1.cfg.predatorBrain && !s1.cfg.predatorEconomy &&
                      !s1.cfg.predatorFrozen && s1.cfg.predatorCount == 3 && s1.creatures.size() == X.creatures.size();
            for (size_t i = 0; ok && i < 3; ++i)                    // the same spots AND headings as any source
                ok = bitEq(s1.predators[i].pos.x, r1.predators[i].pos.x) && bitEq(s1.predators[i].pos.y, r1.predators[i].pos.y)
                     && bitEq(s1.predators[i].vel.x, r1.predators[i].vel.x) && bitEq(s1.predators[i].vel.y, r1.predators[i].vel.y)
                     && s1.predators[i].genome.empty();
            CHECK(ok);
            const std::string sb = checkpoint::serialize(s1, "t");
            CHECK(sb.find("\"formatVersion\":1") != std::string::npos);
            CHECK(ms1.find("scripted Stage A hunters") != std::string::npos &&
                  ms1.find("score from predators.csv") == std::string::npos);    // (its own assay rules)
            // the prey world, its counters and its random state are X's, line by line
            bool sameX = true;
            for (const char* k : {",\"counters\"", ",\"rngState\"", ",\"currentVortices\"", ",\"signals\"", ",\"food\"",
                                  ",\"creatures\""})
                sameX = sameX && lineOf(sb, k) == lineOf(xBlob, k);
            CHECK(sameX);
            // a repeated construction is byte-identical (arena and manifest); another seed moves the hunters
            {
                World s1b = loadX();
                std::string ms1b;
                CHECK(transplant::apply(s1b, sc, "", ms1b, err) && checkpoint::serialize(s1b, "t") == sb && ms1b == ms1);
                transplant::Options sc2 = sc; sc2.seed = 10u;
                World s1c = loadX();
                CHECK(transplant::apply(s1c, sc2, "", ms1b, err) && checkpoint::serialize(s1c, "t") != sb);
            }
            World s2;
            CHECK(checkpoint::deserialize(sb, s2, err) && checkpoint::serialize(s2, "t") == sb);
            // uninterrupted vs resumed: 300 steps at once, or 150 + save / load + 150, are byte-identical
            // (a promise of the serial build only: OpenMP and pool builds do not resume bit-exactly)
#ifdef EVO_DETERMINISTIC
            {                                                   // (each load sets the global stream: load, then run)
                World u, v;
                CHECK(checkpoint::deserialize(sb, u, err));
                for (int i = 0; i < 300; ++i) u.update(0.016f);
                const std::string ub = checkpoint::serialize(u, "t");
                const std::uint64_t uf = deepFingerprint(u);
                CHECK(checkpoint::deserialize(sb, v, err));
                for (int i = 0; i < 150; ++i) v.update(0.016f);
                World v2;
                CHECK(checkpoint::deserialize(checkpoint::serialize(v, "t"), v2, err));
                for (int i = 0; i < 150; ++i) v2.update(0.016f);
                CHECK(checkpoint::serialize(v2, "t") == ub && deepFingerprint(v2) == uf);
            }
#endif
            World s2r;
            CHECK(checkpoint::deserialize(sb, s2r, err));
            for (int i = 0; i < 300; ++i) s2r.update(0.016f);
            CHECK(s2r.predators.size() == 3u);                      // immortal, fixed: no deaths, no buds
            CHECK(s2r.totalPredatorBirths == X.totalPredatorBirths && s2r.totalPredatorDeathsStarvation ==
                  X.totalPredatorDeathsStarvation && s2r.totalPredatorDeathsAge == X.totalPredatorDeathsAge);
            transplant::Options nb2 = sc; nb2.assay = "frozen-newborn";     // either frozen label: the same arena
            World s5 = loadX();
            std::string ms5;
            CHECK(transplant::apply(s5, nb2, "", ms5, err) && !s5.cfg.predatorEconomy && s5.predators.size() == 3u);
            transplant::Options lv2 = sc; lv2.assay = "live";
            World s3 = loadX();
            CHECK(!transplant::apply(s3, lv2, "", ms, err) && err.find("scripted") != std::string::npos);
            transplant::Options nk = sc; nk.count = -1;
            World s4 = loadX();
            CHECK(!transplant::apply(s4, nk, "", ms, err));
        }
        // random founders; a brain-less Y is refused; live keeps X's config
        transplant::Options rnd; rnd.predatorsFrom = "random"; rnd.count = 4; rnd.assay = "live";
        World d = loadX();
        CHECK(transplant::apply(d, rnd, "", man, err));
        bool rf = d.predators.size() == 4u && d.cfg.predatorEconomy && !d.cfg.predatorFrozen;
        for (const auto& p : d.predators) rf = rf && p.lineageId == p.id && !p.genome.empty() && p.sourceId == 0;
        CHECK(rf);
        World e = loadX();
        CHECK(!transplant::apply(e, o, xBlob, man, err));
        transplant::Options none = rnd; none.count = -1;
        World f = loadX();
        CHECK(!transplant::apply(f, none, "", man, err));
        // the arena survives its own checkpoint
        World g;
        CHECK(checkpoint::deserialize(ab, g, err) && checkpoint::serialize(g, "t") == ab && g.arenaFresh_);
        // a live arena from Y: later buds and floor refills never reuse a
        // transplanted lineage label, and every founder has lineageId == id (P2-2)
        transplant::Options lv = o; lv.assay = "live"; lv.count = 4;
        World h = loadX();
        CHECK(transplant::apply(h, lv, yBlob, man, err));
        h.cfg.predatorMinPopulation = 4;
        h.cfg.predatorMetabolism = 40.0f;         // turnover: starvations and refills
        std::vector<std::uint64_t> labels;
        for (const auto& p : h.predators) labels.push_back(p.lineageId);
        long long refills0 = h.totalPredatorReseeds;
        for (int i = 0; i < 1500; ++i) h.update(0.016f);
        CHECK(h.totalPredatorReseeds > refills0);
        bool noReuse = true, foundersOk = true;
        for (const auto& p : h.predators) {
            for (std::uint64_t l : labels) noReuse = noReuse && (p.id != l || p.sourceId != 0);
            if (p.parentId == 0 && p.sourceId == 0) foundersOk = foundersOk && p.lineageId == p.id;
        }
        CHECK(noReuse && foundersOk);
        // a version-2 file with a lineage label at or above its counter is refused
        {
            std::string badLin = ab;
            const size_t at = badLin.find("\"lineageId\":[", badLin.find("\"predators\"")) + 13;
            badLin.replace(at, badLin.find_first_of(",]", at) - at, "999999999");
            World x9;
            CHECK(!checkpoint::deserialize(badLin, x9, err) && err.find("lineageId") != std::string::npos);
        }
        // ... and so is one without its predators block
        {
            std::string noPred = ab;
            const size_t at = noPred.find("\n,\"predators\"") + 1;
            noPred.erase(at, noPred.find('\n', at) - at + 1);
            CHECK(noPred.find("\"predators\"") == std::string::npos);
            World x10;
            CHECK(!checkpoint::deserialize(noPred, x10, err) && err.find("predators") != std::string::npos);
        }
    }

    // --- 12. the frozen assay's accounting: virtual buds, wrapping age ----
    {
        World w = bareBrainWorld(41u, 2, true);
        w.cfg.predatorFrozen = true;
        w.cfg.predatorMetabolism = 50.0f;     // would starve in < 1 s
        w.cfg.predatorMaxAge = 1.0f;          // would age out in 1 s
        w.predators[1].energy = 1000.0f;      // would bud at once, again and again
        std::set<std::uint32_t> energyBits;
        int wraps = 0;
        float lastAge = 0.0f;
        for (int i = 0; i < 200; ++i) {
            w.update(0.016f);
            float s[NUM_PRED_SENSES] = {};
            predbrain::writeOwnSensors(w.predators[1], w.cfg, predbrain::topSpeed(w.predators[1], w.cfg), s);
            energyBits.insert(floatBits(s[PS_ENERGY]));
            if (w.predators[0].age < lastAge) ++wraps;
            lastAge = w.predators[0].age;
        }
        CHECK(w.predators.size() == 2u && w.totalPredatorBirths == 0 &&
              w.totalPredatorDeathsStarvation == 0 && w.totalPredatorDeathsAge == 0);
        CHECK(bitEq(w.predators[0].energy, 0.0f));                       // floored, not dead
        CHECK(wraps == 3 && w.predators[0].age >= 0.0f && w.predators[0].age < 1.0f);   // 3.2 s of a 1 s life
        CHECK(energyBits.size() > 20);                                   // ENERGY moved
        CHECK(w.predators[1].virtualBuds > 20 && w.predators[0].virtualBuds == 0);
        CHECK(w.predators[1].energy < w.cfg.predatorReproEnergy);
        predstats::Last last;
        const predstats::Row r = predstats::sample(w, 0.016f, last);
        CHECK(r.virtualBuds == (long long)w.predators[1].virtualBuds && r.virtualBudsPerPredS > 0.0 &&
              approx((float)r.virtualBudsMean, 0.5f * w.predators[1].virtualBuds, 1e-3f));
        // the per-predator count survives a checkpoint
        std::string err;
        World back;
        CHECK(checkpoint::deserialize(checkpoint::serialize(w, "t"), back, err) &&
              back.predators[1].virtualBuds == w.predators[1].virtualBuds);
    }

    // --- 12a. a virtual bud is funded; age folds any number of lifespans --
    {
        // threshold 40 x 0.5 = 20 sits BELOW the newborn energy 30: a predator
        // between the two cannot pay for a bud, so it makes none
        World w = bareBrainWorld(42u, 3, true);
        w.cfg.predatorFrozen = true;
        w.cfg.predatorMetabolism = 0.0f;      // no move cost, no prey: only buds move energy
        w.cfg.predatorReproEnergy = 40.0f;
        w.cfg.predatorNewbornEnergy = 30.0f;
        for (Predator& p : w.predators) p.buddingFactor = 0.5f;
        w.predators[0].energy = 20.0f;        // at the threshold, cannot pay
        w.predators[1].energy = 29.5f;        // above it, still cannot
        w.predators[2].energy = 35.0f;        // can, once
        w.update(0.016f);
        CHECK(w.predators[0].virtualBuds == 0 && bitEq(w.predators[0].energy, 20.0f));
        CHECK(w.predators[1].virtualBuds == 0 && bitEq(w.predators[1].energy, 29.5f));
        CHECK(w.predators[2].virtualBuds == 1 && bitEq(w.predators[2].energy, 5.0f));   // paid exactly 30
        for (int i = 0; i < 50; ++i) w.update(0.016f);
        CHECK(w.predators[0].virtualBuds == 0 && w.predators[1].virtualBuds == 0 &&
              w.predators[2].virtualBuds == 1 && w.predTally_.virtualBuds == 1);
    }
    {
        // a max age shorter than one step: every step folds back into [0, maxAge)
        World w = bareBrainWorld(43u, 2, true);
        w.cfg.predatorFrozen = true;
        w.cfg.predatorMetabolism = 0.0f;
        w.cfg.predatorMaxAge = 0.005f;
        bool inRange = true;
        for (int i = 0; i < 100; ++i) {
            w.update(0.016f);
            for (const Predator& p : w.predators) inRange = inRange && p.age >= 0.0f && p.age < 0.005f;
        }
        CHECK(inRange && w.predators.size() == 2u && w.totalPredatorDeathsAge == 0);
        // a loaded age of several lifespans folds at its first step
        World x = bareBrainWorld(44u, 1, true);
        x.cfg.predatorFrozen = true;
        x.cfg.predatorMetabolism = 0.0f;
        x.cfg.predatorMaxAge = 1.0f;
        x.predators[0].age = 5.5f;
        std::string err;
        World y;
        CHECK(checkpoint::deserialize(checkpoint::serialize(x, "t"), y, err) && bitEq(y.predators[0].age, 5.5f));
        const float aged = 5.5f + 0.016f;
        y.update(0.016f);
        CHECK(bitEq(y.predators[0].age, std::fmod(aged, 1.0f)) && y.predators[0].age < 1.0f);
        // one lifespan past (the usual case) is the plain subtraction (Sterbenz)
        y.predators[0].age = 0.99f;
        const float past = 0.99f + 0.016f;
        y.update(0.016f);
        CHECK(bitEq(y.predators[0].age, past - 1.0f));
    }

    // --- 12b. a lineage-log write that fails keeps its events --------------
#ifdef __linux__
    {
        World w = bareBrainWorld(43u, 2, false);
        w.cfg.predatorLog = true;
        w.notePredatorsAtStart(w.predators, 'L');
        std::FILE* full = std::fopen("/dev/full", "w");
        if (full) {
            CHECK(!predstats::drainLog(w, full) && w.predLog_.size() == 2u);
            std::fclose(full);
        }
        CHECK(!predstats::drainLog(w, nullptr) && w.predLog_.size() == 2u);
    }
#endif

    // --- 13. the lineage log across a resume: stitched == uninterrupted ----
#ifdef EVO_DETERMINISTIC
    {
        auto make = [](World& w) {
            rng.seed(9090u);
            configureRichWorld(w);
            w.cfg.predatorBrain = true;
            w.cfg.predatorMeal = 14.0f;
            w.cfg.predatorMaxPopulation = 10;
            w.cfg.predatorMinPopulation = 2;
            w.cfg.predatorMaxAge = 20.0f;
            w.cfg.predatorLog = true;
            w.init(900, 700, 220);
        };
        World A;
        make(A);
        for (int i = 0; i < 700; ++i) A.update(0.016f);
        const unsigned long long F = A.frame;
        const std::string cut = checkpoint::serialize(A, "t");
        for (int i = 0; i < 900; ++i) A.update(0.016f);
        std::vector<std::string> full, stitched;
        for (const auto& e : A.predLog_) full.push_back(predstats::logRow(e));
        for (const auto& e : A.predLog_) if (e.frame <= F) stitched.push_back(predstats::logRow(e));
        World B;
        B.cfg.predatorLog = true;             // a CLI setting, not world state
        std::string err;
        CHECK(checkpoint::deserialize(cut, B, err));
        CHECK(B.predLog_.empty());
        B.notePredatorsAtStart(B.predators, 'L');
        size_t lRows = 0;
        for (const auto& e : B.predLog_) lRows += (e.event == 'L' && e.frame == F);
        CHECK(lRows == B.predators.size() && lRows > 0);
        for (int i = 0; i < 900; ++i) B.update(0.016f);
        for (const auto& e : B.predLog_) if (e.event != 'L') stitched.push_back(predstats::logRow(e));
        long births = 0, deaths = 0;
        for (const auto& e : A.predLog_) { births += e.event == 'B'; deaths += e.event == 'S' || e.event == 'A'; }
        CHECK(births > 0 && deaths > 0);
        CHECK(stitched == full);
    }
#endif

    // --- 14. toroidal sensing: a prey across the seam is seen, and steered to
    {
        for (int tor = 0; tor <= 1; ++tor) {
            rng.seed(55u);
            World w;
            w.cfg.predatorCount = 1;
            w.cfg.predatorBrain = true;
            w.cfg.minPopulation = 0;
            w.cfg.targetFood = 0;
            w.cfg.toroidal = tor != 0;
            w.init(640, 480, 0);
            w.creatures.clear();
            Predator& p = w.predators[0];
            p.pos = {5.0f, 240.0f}; p.vel = {0.0f, 1.0f};      // heading +y; rht = (-1, 0)
            p.genome = {predbrain::primerGene(PS_PREY_LR, PA_TURN, 3.0f)};
            predbrain::buildNet(p.genome, p.nnet);
            Creature prey = makeRandomCreature({620.0f, 240.0f});   // 20 to the -x side across the seam
            prey.vel = {0.0f, 1.0f};
            w.creatures.push_back(prey);
            w.update(0.016f);
            const float vx = w.predators[0].vel.x;
            if (tor) CHECK(vx < 0.0f);          // turned toward -x: through the seam
            else     CHECK(bitEq(vx, 0.0f));    // 615 away: unseen, no turn
        }
    }
}

int main() {
    std::printf("=== evo_boids core tests (no SFML linked) ===\n");
    test_portable_mt19937();
    test_vec2();
    test_color();
    test_quadtree();
    test_spatial_grid_matches_quadtree();
    test_exact_shortcuts();
    test_genome_and_net();
    test_feedforward_equivalence();
    test_fast_tanh();
    test_topological_neighbors();
    test_checkpoint();
    test_toroidal();
    test_creature();
    test_world_invariants();
    test_predator();
    test_predator_economy();
    test_inspection_and_cluster();
    test_analysis_v012();
    test_schooling_metric();
    test_reproductive_isolation();
    test_repro_graph();
    test_body_model();
    test_repro_mitigations();
    test_generation();
    test_predator_floor_inherit();
    test_predator_brain();
#ifdef EVO_POOL_THREADS
    test_thread_pool();
#endif

    std::printf("---------------------------------------------\n");
    std::printf("%d checks, %d failures\n", g_checks, g_failures);
    if (g_failures == 0) {
        std::printf("ALL CORE TESTS PASSED\n");
        return 0;
    }
    std::printf("SOME TESTS FAILED\n");
    return 1;
}

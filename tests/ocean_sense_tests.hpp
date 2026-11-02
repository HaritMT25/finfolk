#pragma once
// ocean_sense_tests.hpp — the sensing scans' edges, pinned bit for bit,
// included by tests/ocean_tests.cpp just before main (namespace ot: Test,
// initQuiet, addFish are that file's).
//
// The per-fish food and neighbour scans (OceanWorld::computeSensors, eyeScan)
// may be made faster only if no result moves. These checks hold the current
// behaviour where a faster scan could plausibly differ:
//
//   sense_edges   hand-built scenes, every sensor of the scan bit for bit:
//     * the wrapped grid filter: food exactly R away by the wrapped metric but
//       R + 1.2e-4 from the grid's translated image centre is NOT visited
//       (dropping the grid's 2-D test on the toroidal path would count it)
//     * the depth counterexample: fl(z − R) > food depth, yet dz rounds to −R:
//       the item IS within R (counted; the eye sees it at PROX 0)
//     * zero-distance winners (food, neighbours): nothing later replaces them
//     * rounded-sqrt ties: d² = 1 + 2^-23 and d² = 1 have the same sqrt, so
//       the first visited wins, in either order (food; metric neighbours) and
//       the smaller d² in topological mode, which orders by (d², index)
//     * distance exactly R: counted, never the nearest (food; metric and
//       topological neighbours); past R by depth: not counted
//     * ties across cells (the lower column first) and across the toroidal
//       seam (the central image first), food and neighbours; the topological
//       cut's index tie-break
//     * mouthGate: an oversized item is seen, not smelled; size == kMouth·L is
//       food; a NaN depth or size is counted, never the nearest (the literal
//       !(d2 > R²) and !(size > max))
//     * NaN admission on every path: a NaN-depth food item in each slot of
//       one cell (bounded: the four-wide batch and the scalar tail; wrapped:
//       a translated image), a NaN-depth neighbour first / between / last,
//       metric and topological (the cut's insertion takes it as its own
//       comparisons fall), bounded and wrapped; summed eyes included (a NaN
//       the definition gives compares by class: sameSense)
//     * five items exactly R away in one cell (batch and tail; wrapped), and
//       one alone in its eye sector as the batch's last or the tail; the
//       viewer alone (never its own neighbour); the mouth gate's edges
//       (size == the limit, a NaN size, an oversized item the eye still
//       sees), bounded and wrapped; -0 offsets on each axis keep their sign
//     * the food's own step before the scans (stepAndCompareFoodPhase: the
//       reference reads the food as the step leaves it): an item expiring
//       exactly at foodLife, items spawned this step, a replacement at the
//       cap, E1 drift moving items and changing their depths and contrasts
//     * the hot state: a viewer stepping after its neighbours sees them where
//       they moved (position, depth, heading, age), but only those whose
//       start-of-step (x, y) was within R; the long probe reads moved depths
//     * summed sectors (eyeCode 4): five unequal contributions in one sector,
//       summed in the visit order (fish, food in grid order, the predator); a
//       fixture where some other order gives other bits
//   sense_ref     randomized scenes (ties, exact-R offsets, 3-4-5 triangles,
//                 world edges, the toroidal seam; metric and topological,
//                 mouthGate, eye off / nearest / summed / eye-only) against a
//                 scalar reference of the scans' definition: SpatialGrid's
//                 visit order and its 2-D test (bounded, and the nine clipped
//                 images), the 3-D test, the mouth gate, the strict nearest, the
//                 topological (d², index) cut, the eye's nearest / summed bins
//   food_grid     OceanFoodGrid (src/ocean/ocean_food_grid.hpp) against
//                 SpatialGrid itself: the same index lists and the same visits
//                 in the same order, bounded and wrapped, and each entry's
//                 payload equal to its item's
//
// The viewer is creatures[0] in every reference scene: it senses before any
// fish has moved, so every candidate is where the scene put it.
#include <initializer_list>

namespace ot {
namespace sense {

inline bool sameBits(float a, float b) {
    std::uint32_t x, y;
    std::memcpy(&x, &a, 4);
    std::memcpy(&y, &b, 4);
    return x == y;
}
inline float fromBits(std::uint32_t u) {
    float f;
    std::memcpy(&f, &u, 4);
    return f;
}
inline std::uint32_t bitsOf(float f) {
    std::uint32_t u;
    std::memcpy(&u, &f, 4);
    return u;
}
// A sensor against the scans' definition: bit for bit (signed zeros too),
// except where the definition gives a NaN (a fixture's NaN depth or size
// reached it): then any NaN. Which NaN payload comes out is not what these
// fixtures pin; sameBits and the determinism harness stay exact.
inline bool sameSense(float got, float want) { return std::isnan(want) ? std::isnan(got) : sameBits(got, want); }

struct Pt { float x, y; };

// SpatialGrid's visit order (spatial_grid.hpp) over pts, inserted in index
// order, for a radius-r query at c: the clamped cell rectangle row by row, each
// cell in insertion order, each entry tested by q2 <= r² against the query
// centre; wrapped: the nine images in its order, each clipped to the world and
// tested against its translated centre.
inline std::vector<int> gridVisit(const std::vector<Pt>& pts, int W, int H, float cell, Vec2 c, float r,
                                  bool toroidal) {
    const float inv = 1.0f / cell;
    const int cols = (int)(W * inv) + 1, rows = (int)(H * inv) + 1;
    auto ccol = [&](int k) { return k < 0 ? 0 : (k >= cols ? cols - 1 : k); };
    auto crow = [&](int k) { return k < 0 ? 0 : (k >= rows ? rows - 1 : k); };
    std::vector<std::vector<int>> cells((std::size_t)cols * rows);
    for (int i = 0; i < (int)pts.size(); ++i) {
        if (std::isnan(pts[i].x) || std::isnan(pts[i].y)) continue;
        cells[(std::size_t)crow((int)(pts[i].y * inv)) * cols + ccol((int)(pts[i].x * inv))].push_back(i);
    }
    std::vector<int> out;
    const float r2 = r * r;
    auto scan = [&](float x0, float y0, int c0, int c1, int r0, int r1) {
        for (int cy = r0; cy <= r1; ++cy)
            for (int cx = c0; cx <= c1; ++cx)
                for (int i : cells[(std::size_t)cy * cols + cx]) {
                    const float dx = pts[i].x - x0, dy = pts[i].y - y0;
                    if (dx * dx + dy * dy <= r2) out.push_back(i);
                }
    };
    if (!toroidal) {
        scan(c.x, c.y, ccol((int)((c.x - r) * inv)), ccol((int)((c.x + r) * inv)), crow((int)((c.y - r) * inv)),
             crow((int)((c.y + r) * inv)));
        return out;
    }
    static const int order[9][2] = {{0, 0}, {-1, -1}, {-1, 0}, {-1, 1}, {0, -1}, {0, 1}, {1, -1}, {1, 0}, {1, 1}};
    const float Wf = (float)W, Hf = (float)H;
    for (const auto& im : order) {
        const float cx0 = c.x + im[0] * Wf, cy0 = c.y + im[1] * Hf;
        const float lox = cx0 - r, hix = cx0 + r, loy = cy0 - r, hiy = cy0 + r;
        if (hix < 0.0f || lox >= Wf || hiy < 0.0f || loy >= Hf) continue;
        scan(cx0, cy0, ccol((int)(std::max(lox, 0.0f) * inv)), ccol((int)(std::min(hix, Wf) * inv)),
             crow((int)(std::max(loy, 0.0f) * inv)), crow((int)(std::min(hiy, Hf) * inv)));
    }
    return out;
}

// The labeled food / neighbour inputs and (eye build) the 18 eye inputs that
// viewer creatures[0] of w (as set up, before its step) must read, from the
// scans' definition; every other input is left 0.
inline void reference(const OceanWorld& w, float out[NUM_SENSES]) {
    for (int k = 0; k < NUM_SENSES; ++k) out[k] = 0.0f;
    const Fish& c = w.creatures[0];
    const Vec2 fwd = c.forward(), rht = {-fwd.y, fwd.x};
    const float R = w.cfg.perceptionRadius, R2 = R * R;
    const bool tor = w.cfg.toroidal;
    const float Wf = (float)w.width, Hf = (float)w.height;
    auto off = [&](Vec2 p, float z, float& dx, float& dy, float& dz) {
        dx = p.x - c.pos.x;
        dy = p.y - c.pos.y;
        if (tor) { dx = OceanWorld::wrapDelta(dx, Wf); dy = OceanWorld::wrapDelta(dy, Hf); }
        dz = z - c.depth;
    };
#ifdef EVO_OCEAN_EYE
    const bool eye = w.ocfg.eye != 0, labels = w.ocfg.eyeOnly == 0;
    const int code = w.ocfg.eyeCode;
    struct Bin { float d2, size, con, sp, ss, sc; };
    Bin bins[ocean::kEyeSectors];
    for (Bin& b : bins) b = {std::numeric_limits<float>::infinity(), 0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
    auto see = [&](float dx, float dy, float dz, float d2, float s, float con) {
        const float a = dx * fwd.x + dy * fwd.y, b = dx * rht.x + dy * rht.y;
        const float aa = std::abs(a), ab = std::abs(b), az = std::abs(dz);
        const int k = (aa >= ab && aa >= az) ? (a >= 0.0f ? 0 : 1) : (ab >= az) ? (b <= 0.0f ? 2 : 3) : (dz <= 0.0f ? 4 : 5);
        Bin& e = bins[k];
        if (d2 < e.d2) { e.d2 = d2; e.size = s; e.con = con; }
        const float d = std::sqrt(d2), p = 1.0f - d / R;
        e.sp += p;
        e.ss += s / (s + d);
        e.sc += p * con;
    };
#else
    const bool labels = true;
#endif

    // ---- neighbours
    std::vector<Pt> fishPts;
    for (const Fish& f : w.creatures) fishPts.push_back({f.pos.x, f.pos.y});
    const std::vector<int> nv = gridVisit(fishPts, w.width, w.height, R, c.pos, R, tor);
    float avgDx = 0, avgDy = 0, avgDz = 0, avgHx = 0, avgHy = 0, nearestDist = R;
    int nearestIdx = -1, count = 0, popFwd = 0, popLR = 0, inRadius = 0;
    auto attend = [&](int ni, float dx, float dy, float dz, float dist) {
        const Fish& o = w.creatures[ni];
        avgDx += dx; avgDy += dy; avgDz += dz;
        avgHx += o.vel.x; avgHy += o.vel.y;
        const float dotFwd = dx * fwd.x + dy * fwd.y, dotLR = dx * rht.x + dy * rht.y;
        popFwd += (dotFwd > 0) ? 1 : -1;
        popLR += (dotLR > 0) ? 1 : -1;
        if (dist < nearestDist) { nearestDist = dist; nearestIdx = ni; }
        ++count;
    };
    struct Cand { float d2, dx, dy, dz; int i; };
    std::vector<Cand> cands;
    for (int ni : nv) {
        if (ni == 0) continue;
        const Fish& o = w.creatures[ni];
        float dx, dy, dz;
        off(o.pos, o.depth, dx, dy, dz);
        const float d2 = dx * dx + dy * dy + dz * dz;
        if (d2 > R2) continue;
#ifdef EVO_OCEAN_EYE
        if (eye && !(code & kEyeCodeNoFish))
            see(dx, dy, dz, d2, ocean::kEyeFishLen * o.bodySize, ocean::eyeContrast(ocean::kEyeFishBright, o.depth));
#endif
        ++inRadius;
        cands.push_back({d2, dx, dy, dz, ni});
    }
    if (w.cfg.maxNeighbors <= 0) {
        for (const Cand& k : cands) attend(k.i, k.dx, k.dy, k.dz, std::sqrt(k.d2));
    } else {
        // The topological cut by its definition: a bounded insertion, in visit
        // order, of the nearest by (d², index). Not a sort: a NaN d² is
        // unordered (a sort's comparator would no longer be a strict weak
        // order), and the insertion's own comparisons decide where it goes —
        // it is never "worse" than the kept worst, so it displaces it, and no
        // kept candidate is "before" it, so it moves to the front.
        const std::size_t keep = (std::size_t)std::min(w.cfg.maxNeighbors, MAX_TOPOLOGICAL_NEIGHBORS);
        std::vector<Cand> best;
        for (const Cand& k : cands) {
            if (best.size() == keep) {
                const Cand& worst = best.back();
                if (k.d2 > worst.d2 || (k.d2 == worst.d2 && k.i > worst.i)) continue;
                best.pop_back();
            }
            std::size_t at = best.size();
            while (at > 0) {
                const Cand& p = best[at - 1];
                if (p.d2 < k.d2 || (p.d2 == k.d2 && p.i < k.i)) break;
                --at;
            }
            best.insert(best.begin() + (std::ptrdiff_t)at, k);
        }
        for (const Cand& k : best) attend(k.i, k.dx, k.dy, k.dz, std::sqrt(k.d2));
    }
    if (labels) {
        if (count > 0) { avgDx /= count; avgDy /= count; avgDz /= count; avgHx /= count; avgHy /= count; }
        // labelFrame 1 (A1): x = right, y = ahead; the offset projected before the tanh
        const bool own = w.ocfg.labelFrame == 1;
        out[NEIGHBOR_COUNT] = tanhCountOver10(inRadius);
        out[AVG_NEIGHBOR_DX] = evomath::tanhf((own ? avgDx * rht.x + avgDy * rht.y : avgDx) / R);
        out[AVG_NEIGHBOR_DY] = evomath::tanhf((own ? avgDx * fwd.x + avgDy * fwd.y : avgDy) / R);
        out[AVG_NEIGHBOR_DZ] = evomath::tanhf(avgDz / R);
        out[AVG_NEIGHBOR_HEADING_X] = own ? avgHx * rht.x + avgHy * rht.y : avgHx;
        out[AVG_NEIGHBOR_HEADING_Y] = own ? avgHx * fwd.x + avgHy * fwd.y : avgHy;
        out[NEAREST_NEIGHBOR_DIST] = nearestDist / R;
        out[POPULATION_DENSITY] = tanhCountOver15(inRadius);
        out[POPULATION_FWD] = tanhCountOver5(popFwd);
        out[POPULATION_LR] = tanhCountOver5(popLR);
        if (nearestIdx >= 0) {
            const Fish& n = w.creatures[nearestIdx];
            const float sim = kernel::writeNearestSensors(c, n, out);
            float dx, dy, dz;
            off(n.pos, n.depth, dx, dy, dz);
            out[GENETIC_SIM_FWD] = (dx * fwd.x + dy * fwd.y > 0) ? sim : 0.5f;
        } else {
            kernel::clearNearestSensors(out);
            out[GENETIC_SIM_FWD] = 0.5f;
        }
    }

    // ---- food
    std::vector<Pt> foodPts;
    for (const OceanFood& f : w.food) foodPts.push_back({f.pos.x, f.pos.y});
    const std::vector<int> fv = gridVisit(foodPts, w.width, w.height, R, c.pos, R, tor);
    float foodDx = 0, foodDy = 0, foodDz = 0, foodDist = R;
    int foodCount = 0;
    for (int fi : fv) {
        const OceanFood& f = w.food[fi];
        if (!f.alive) continue;
        float dx, dy, dz;
        off(f.pos, f.depth, dx, dy, dz);
        const float d2 = dx * dx + dy * dy + dz * dz;
        if (d2 > R2) continue;
#ifdef EVO_OCEAN_EYE
        if (eye && !(code & kEyeCodeNoFood)) see(dx, dy, dz, d2, ocean::kEyeFoodSize, f.eyeCon);
#endif
        if (!labels) continue;
        if (w.ocfg.mouthGate && f.size > w.ocfg.kMouth * c.bodySize) continue;
        ++foodCount;
        const float dist = std::sqrt(d2);
        if (dist < foodDist) {
            foodDist = dist;
            const float invD = (dist > 0.001f) ? 1.0f / dist : 0.0f;
            foodDx = dx * invD; foodDy = dy * invD; foodDz = dz * invD;
        }
    }
    if (labels) {
        const bool own = w.ocfg.labelFrame == 1;   // the unit vector's horizontal part, right / ahead
        out[NEAREST_FOOD_DX] = own ? foodDx * rht.x + foodDy * rht.y : foodDx;
        out[NEAREST_FOOD_DY] = own ? foodDx * fwd.x + foodDy * fwd.y : foodDy;
        out[NEAREST_FOOD_DZ] = foodDz;
        out[NEAREST_FOOD_DIST] = foodDist / R;
        out[FOOD_DENSITY] = tanhCountOver10(foodCount);
    }

#ifdef EVO_OCEAN_EYE
    if (!eye) return;
    for (const OceanPredator& p : w.predators) {
        float dx, dy, dz;
        off(p.pos, p.depth, dx, dy, dz);
        const float d2 = dx * dx + dy * dy + dz * dz;
        if (d2 <= R2) see(dx, dy, dz, d2, ocean::kEyePredSize, ocean::eyeContrast(ocean::kEyePredBright, p.depth));
    }
    float* s = out + ocean::kEyeFirst;
    auto q = [](float x) { return x / (1.0f + std::abs(x)); };
    for (int k = 0; k < ocean::kEyeSectors; ++k) {
        float* e = s + 3 * k;
        const Bin& b = bins[k];
        if (code & kEyeCodeSummed) { e[0] = q(b.sp); e[1] = q(b.ss); e[2] = q(b.sc); continue; }
        if (!(b.d2 <= R2)) { e[0] = e[1] = e[2] = 0.0f; continue; }
        const float d = std::sqrt(b.d2);
        e[0] = 1.0f - d / R;
        e[1] = b.size / (b.size + d);
        e[2] = (code & kEyeCodeFaded) ? e[0] * b.con : b.con;
    }
    if (code & kEyeCodeOpponent)
        for (int pr : {2, 4})
            for (int f = 0; f < 3; ++f) {
                const float lo = s[3 * pr + f], hi = s[3 * pr + 3 + f];
                s[3 * pr + f] = lo + hi;
                s[3 * pr + 3 + f] = hi - lo;
            }
#endif
}

inline constexpr int kFoodSenses[] = {NEAREST_FOOD_DX, NEAREST_FOOD_DY, NEAREST_FOOD_DZ, NEAREST_FOOD_DIST, FOOD_DENSITY};
inline constexpr int kNeighbourSenses[] = {
    NEIGHBOR_COUNT, AVG_NEIGHBOR_DX, AVG_NEIGHBOR_DY, AVG_NEIGHBOR_DZ, AVG_NEIGHBOR_HEADING_X, AVG_NEIGHBOR_HEADING_Y,
    NEAREST_NEIGHBOR_DIST, POPULATION_DENSITY, POPULATION_FWD, POPULATION_LR, NEAREST_NEIGHBOR_AGE,
    NEAREST_NEIGHBOR_FOOD, GENETIC_SIM_NEAREST, GENETIC_SIM_FWD};

struct Sensed { float s[NUM_SENSES]; };

// What viewer creatures[0] of w read in its last step, every scanned input
// against want (sameSense: bit for bit, a NaN of the definition's by class).
inline Sensed compareCaptured(Test& t, const char* scene, const OceanWorld& w, const float want[NUM_SENSES],
                              long* compared = nullptr) {
    Sensed got;
    std::memcpy(got.s, w.creatures[0].lastSensors, sizeof got.s);
    std::vector<int> idx(std::begin(kFoodSenses), std::end(kFoodSenses));
    idx.insert(idx.end(), std::begin(kNeighbourSenses), std::end(kNeighbourSenses));
#ifdef EVO_OCEAN_EYE
    for (int k = 0; k < ocean::kEyeInputs; ++k) idx.push_back(ocean::kEyeFirst + k);
#endif
    for (int k : idx) {
        t.expect(sameSense(got.s[k], want[k]), "%s: %s = %.9g (0x%08x), the scan's definition gives %.9g (0x%08x)", scene,
                 ocean::kSensorNames[k], got.s[k], bitsOf(got.s[k]), want[k], bitsOf(want[k]));
        if (compared) ++*compared;
    }
    return got;
}

// One step of w (viewer creatures[0]); its sensors must equal the reference
// bit for bit on every scanned input. Returns what it read.
inline Sensed stepAndCompare(Test& t, const char* scene, OceanWorld& w, long* compared = nullptr) {
    float want[NUM_SENSES];
    {
        const OceanWorld before = w;   // the reference reads the scene as set up
        reference(before, want);
    }
    w.update(0.016f);
    return compareCaptured(t, scene, w, want, compared);
}

// As stepAndCompare, for the food's own step: drift, ageing / expiry and
// spawning run before the scans, so the reference reads the food as the
// step leaves it (the expired erased, the newborn added, the drifted moved,
// their depths and contrasts updated) and the viewer as it was when it
// sensed. For a world with the viewer alone and pickupRadius 0: nothing is
// eaten, so the food after the step is what the scans should have seen
// (checked). Independent of the grid's payload, which it checks.
inline Sensed stepAndCompareFoodPhase(Test& t, const char* scene, OceanWorld& w) {
    const Fish viewer = w.creatures[0];
    const auto eaten = w.totalFoodEaten;
    w.update(0.016f);
    t.expect(w.totalFoodEaten == eaten && w.creatures.size() == 1, "%s: fixture: food eaten (%lld) or other fish (%zu)", scene,
             (long long)(w.totalFoodEaten - eaten), w.creatures.size());
    OceanWorld expected = w;
    expected.creatures[0] = viewer;
    float want[NUM_SENSES];
    reference(expected, want);
    return compareCaptured(t, scene, w, want);
}

inline int addFood(OceanWorld& w, float x, float y, float z, float size = 1.0f) {
    OceanFood f;
    f.pos = {x, y};
    f.depth = z;
    f.size = size;
#ifdef EVO_OCEAN_EYE
    f.eyeCon = ocean::eyeContrast(ocean::kEyeFoodBright, z);
#endif
    w.food.push_back(f);
    return (int)w.food.size() - 1;
}
// A quiet fish (no wiring, never interacts) at (x, y, z) heading `heading`.
inline int addQuiet(OceanWorld& w, float x, float y, float z, Vec2 heading, float age = 0.0f, float reserves = 50.0f) {
    const int k = addFish(w, {x, y}, z, {}, 0.5f);
    Fish& f = w.creatures[k];
    f.vel = heading;
    f.age = age;
    f.foodReserves = reserves;
    f.interactTimer = 1e9f;
    return k;
}

// The eye variants a scene runs under: (eye, eyeCode, eyeOnly). The plain build: eye off only.
struct EyeMode { int eye, code, only; const char* name; };
#ifdef EVO_OCEAN_EYE
inline constexpr EyeMode kEyeModes[] = {{0, 0, 0, "eye off"}, {1, 0, 0, "eye nearest"}, {1, kEyeCodeSummed, 0, "eye summed"},
                                        {1, 0, 1, "eye-only nearest"}, {1, kEyeCodeSummed, 1, "eye-only summed"}};
#else
inline constexpr EyeMode kEyeModes[] = {{0, 0, 0, "plain"}};
#endif

}  // namespace sense

// OceanFoodGrid (src/ocean/ocean_food_grid.hpp) against SpatialGrid itself:
// random items (NaN, negative, beyond the world, on cell edges and on W / H,
// duplicates) in several world / cell sizes (partial last cells), random
// queries (inside, on edges, outside; radii 0 .. 1.3 cells), bounded and
// wrapped, each grid built twice (clear() and capacity reuse): the same index
// lists (queryRadius*), the same (index, position) visits in the same order
// (forEachInRadius*), and every visited entry carries its item's depth, size
// (and eyeCon).
void testFoodGrid() {
    using sense::sameBits;
    Test t("food_grid");
    std::uint32_t s = 0x2545f491u;
    auto next = [&]() { s ^= s << 13; s ^= s >> 17; s ^= s << 5; return s; };
    auto pick = [&](int n) { return (int)(next() % (std::uint32_t)n); };
    auto unit = [&]() { return (float)(next() >> 8) * (1.0f / 16777216.0f); };
    struct G { int W, H; float cell; };
    const G gs[] = {{1920, 1080, 100.0f}, {1950, 1030, 100.0f}, {100, 100, 1.0f},
                    {2560, 1440, 80.0f},  {640, 480, 37.5f},    {300, 200, 300.0f}};
    long lists = 0, visits = 0, entries = 0;
    for (const G& g : gs) {
        const float W = (float)g.W, H = (float)g.H;
        auto coord = [&](float span) -> float {
            switch (pick(8)) {
                case 0: return g.cell * (float)pick((int)(span / g.cell) + 2);   // a cell edge
                case 1: return pick(2) ? span : 0.0f;
                case 2: return -0.1f * span * unit();
                case 3: return span * (1.0f + 0.1f * unit());
                case 4: return pick(50) ? span * unit() : std::numeric_limits<float>::quiet_NaN();
                default: return span * unit();
            }
        };
        for (int rep = 0; rep < 12; ++rep) {
            SpatialGrid sg;
            OceanFoodGrid fg;
            sg.init(g.W, g.H, g.cell);
            fg.init(g.W, g.H, g.cell);
            for (int build = 0; build < 2; ++build) {
                const int n = pick(500);
                std::vector<OceanFood> items(n);
                for (int i = 0; i < n; ++i) {
                    OceanFood& f = items[i];
                    if (i > 0 && pick(10) == 0) f = items[pick(i)];   // a duplicate
                    else {
                        f.pos = {coord(W), coord(H)};
                        f.depth = 240.0f * unit();
                        f.size = 0.5f + 2.0f * unit();
#ifdef EVO_OCEAN_EYE
                        f.eyeCon = unit() - 0.5f;
#endif
                    }
                }
                sg.clear();
                fg.clear();
                for (int i = 0; i < n; ++i) { sg.insert(items[i].pos, i); fg.insert(items[i], i); }
                sg.build();
                fg.build();
                for (int q = 0; q < 40; ++q) {
                    const Vec2 c = {coord(W), coord(H)};
                    if (std::isnan(c.x) || std::isnan(c.y)) continue;
                    const float radii[] = {0.0f, 0.5f * g.cell, g.cell, 1.3f * g.cell, 24.0f, g.cell * unit()};
                    float r = radii[pick(6)];
                    for (int wrapped = 0; wrapped < 2; ++wrapped) {
                        if (wrapped) r = std::min(r, 0.49f * std::min(W, H));   // the wrapped query's bound
                        std::vector<int> a, b;
                        if (wrapped) { sg.queryRadiusWrapped(c, r, a); fg.queryRadiusWrapped(c, r, b); }
                        else         { sg.queryRadius(c, r, a);        fg.queryRadius(c, r, b); }
                        t.expect(a == b, "%dx%d cell %g: query (%g, %g) r %g %s: %zu vs %zu indices", g.W, g.H, g.cell, c.x, c.y,
                                 r, wrapped ? "wrapped" : "bounded", a.size(), b.size());
                        ++lists;
                        std::vector<std::pair<int, Vec2>> va, vb;
                        auto fa = [&](int i, Vec2 p) { va.push_back({i, p}); };
                        auto fb = [&](int k) {   // slot k: its position, index and payload
                            const int i = fg.indices()[k];
                            vb.push_back({i, Vec2{fg.xs()[k], fg.ys()[k]}});
                            const OceanFood& f = items[i];
                            bool same = sameBits(fg.depths()[k], f.depth) && sameBits(fg.sizes()[k], f.size);
#ifdef EVO_OCEAN_EYE
                            same = same && sameBits(fg.eyeCons()[k], f.eyeCon);
#endif
                            t.expect(same, "entry %d's payload is not its item's", i);
                            ++entries;
                        };
                        // bounded: the visitor also gets the 2-D test's offset and q2 (bit for bit)
                        auto fbq = [&](int k, float dx, float dy, float q2) {
                            const float ex = fg.xs()[k] - c.x, ey = fg.ys()[k] - c.y;
                            t.expect(sameBits(dx, ex) && sameBits(dy, ey) && sameBits(q2, ex * ex + ey * ey) && q2 <= r * r,
                                     "slot %d: offset / q2 handed over are not the 2-D test's", k);
                            fb(k);
                        };
                        if (wrapped) { sg.forEachInRadiusWrapped(c, r, fa); fg.forEachInRadiusWrapped(c, r, fb); }
                        else         { sg.forEachInRadius(c, r, fa);        fg.forEachInRadius(c, r, fbq); }
                        bool same = va.size() == vb.size();
                        for (std::size_t k = 0; same && k < va.size(); ++k)
                            same = va[k].first == vb[k].first && sameBits(va[k].second.x, vb[k].second.x) &&
                                   sameBits(va[k].second.y, vb[k].second.y);
                        t.expect(same, "%dx%d cell %g: visit (%g, %g) r %g %s differs (%zu vs %zu)", g.W, g.H, g.cell, c.x, c.y, r,
                                 wrapped ? "wrapped" : "bounded", va.size(), vb.size());
                        ++visits;
                        if (!wrapped) {   // forEachRun's runs + the 2-D test == the bounded visit
                            std::vector<int> vr;
                            fg.forEachRun(c, r, [&](int b, int e) {
                                for (int k = b; k < e; ++k) {
                                    const float dx = fg.xs()[k] - c.x, dy = fg.ys()[k] - c.y;
                                    if (dx * dx + dy * dy <= r * r) vr.push_back(fg.indices()[k]);
                                }
                            });
                            bool sameRuns = vr.size() == va.size();
                            for (std::size_t k = 0; sameRuns && k < vr.size(); ++k) sameRuns = vr[k] == va[k].first;
                            t.expect(sameRuns, "%dx%d cell %g: runs at (%g, %g) r %g differ from the visit", g.W, g.H, g.cell, c.x,
                                     c.y, r);
                        }
                    }
                }
            }
        }
    }
    t.note("%ld index lists and %ld visit sequences equal to SpatialGrid's; %ld entries' payloads checked", lists, visits,
           entries);
}

void testSenseEdges() {
    using namespace sense;
    Test t("sense_edges");
    const float R = 100.0f;   // applyOceanDefaults' perceptionRadius
    auto world = [&](OceanWorld& w, unsigned seed, const EyeMode& m, bool toroidal, int maxNeighbors = 0,
                     bool mouthGate = false) {
        OceanConfig oc;
#ifdef EVO_OCEAN_EYE
        oc.eye = m.eye;
        oc.eyeCode = m.code;
        oc.eyeOnly = m.only;
#else
        (void)m;
#endif
        oc.mouthGate = mouthGate;
        oc.kMouth = 1.2f;
        initQuiet(w, seed, 240.0f, oc, /*capture*/ true, toroidal);
        w.cfg.maxNeighbors = maxNeighbors;
        t.expect(w.cfg.perceptionRadius == R, "perceptionRadius %g, expected %g", w.cfg.perceptionRadius, R);
    };
    const Vec2 east = {1.0f, 0.0f};
    char name[160];

    for (const EyeMode& m : kEyeModes) {
        const bool labels = m.only == 0;
        // (1) The wrapped grid filter (Codex's counterexample).
        {
            OceanWorld w;
            world(w, 301, m, /*toroidal*/ true);
            const float fx = 62.17205810546875f, gx = 1882.1719970703125f;
            addQuiet(w, fx, 500.0f, 120.0f, east);
            addFood(w, gx, 500.0f, 120.0f);
            const float wdx = OceanWorld::wrapDelta(gx - fx, 1920.0f), gdx = gx - (fx + 1920.0f);
            t.expect(wdx == -100.0f && !(wdx * wdx > R * R) && gdx * gdx > R * R,
                     "fixture: wrapped dx %.9g, image dx %.9g", wdx, gdx);
            std::snprintf(name, sizeof name, "wrapped filter (%s)", m.name);
            const Sensed S = stepAndCompare(t, name, w);
            if (labels)
                t.expect(sameBits(S.s[FOOD_DENSITY], tanhCountOver10(0)) && S.s[NEAREST_FOOD_DIST] == 1.0f &&
                             sameBits(S.s[NEAREST_FOOD_DX], 0.0f),
                         "%s: the item the grid's image test rejects was smelled (density %.9g)", name, S.s[FOOD_DENSITY]);
#ifdef EVO_OCEAN_EYE
            for (int k = 0; k < ocean::kEyeInputs; ++k)
                t.expect(sameBits(S.s[ocean::kEyeFirst + k], 0.0f), "%s: eye input %d = %.9g, the eye saw it", name, k,
                         S.s[ocean::kEyeFirst + k]);
#endif
        }
        // (2) The depth counterexample: fl(z − R) > food depth, dz rounds to −R.
        {
            OceanWorld w;
            world(w, 302, m, false);
            const float z = fromBits(0x42c80001u), fz = fromBits(0x36ffffffu);
            addQuiet(w, 600.0f, 500.0f, z, east);
            addFood(w, 600.0f, 500.0f, fz);
            t.expect(z - R > fz && fz - z == -100.0f, "fixture: z - R %.9g, dz %.9g", z - R, fz - z);
            std::snprintf(name, sizeof name, "depth bound (%s)", m.name);
            const Sensed S = stepAndCompare(t, name, w);
            if (labels)
                t.expect(sameBits(S.s[FOOD_DENSITY], tanhCountOver10(1)) && S.s[NEAREST_FOOD_DIST] == 1.0f &&
                             sameBits(S.s[NEAREST_FOOD_DZ], 0.0f),
                         "%s: the item at exactly R by depth was not counted, or became the nearest", name);
#ifdef EVO_OCEAN_EYE
            if (m.eye && !(m.code & kEyeCodeSummed))
                t.expect(S.s[EYE_UP_PROX] == 0.0f && S.s[EYE_UP_SIZE] == ocean::kEyeFoodSize / (ocean::kEyeFoodSize + R),
                         "%s: the eye's up sector %.9g %.9g", name, S.s[EYE_UP_PROX], S.s[EYE_UP_SIZE]);
#endif
        }
        // (3) Zero-distance winners. Food: a zero item first, then one 1 ulp
        // deeper, then one 5 away; and the reverse order.
        for (int rev = 0; rev < 2; ++rev) {
            OceanWorld w;
            world(w, 303, m, false);
            const float z = 120.0f, z1 = std::nextafter(z, 1000.0f);
            addQuiet(w, 600.0f, 500.0f, z, east);
            const float zs[3][2] = {{0.0f, z}, {0.0f, z1}, {5.0f, z}};
            for (int k = 0; k < 3; ++k) {
                const int j = rev ? 2 - k : k;
                addFood(w, 600.0f + zs[j][0], 500.0f, zs[j][1]);
            }
            std::snprintf(name, sizeof name, "zero food %s (%s)", rev ? "last" : "first", m.name);
            const Sensed S = stepAndCompare(t, name, w);
            if (labels)
                t.expect(sameBits(S.s[NEAREST_FOOD_DIST], 0.0f) && sameBits(S.s[FOOD_DENSITY], tanhCountOver10(3)),
                         "%s: nearest %.9g (want 0), density %.9g", name, S.s[NEAREST_FOOD_DIST], S.s[FOOD_DENSITY]);
        }
        // Neighbours: two fish at the viewer's own point; the first visited wins
        // (metric), the lower index (topological): both fish 1.
        for (int topo : {0, 1, 7}) {
            OceanWorld w;
            world(w, 304, m, false, topo);
            addQuiet(w, 600.0f, 500.0f, 120.0f, east);
            addQuiet(w, 600.0f, 500.0f, 120.0f, east, 10.0f, 30.0f);
            addQuiet(w, 600.0f, 500.0f, 120.0f, east, 90.0f, 70.0f);
            std::snprintf(name, sizeof name, "zero neighbour topo %d (%s)", topo, m.name);
            const Sensed S = stepAndCompare(t, name, w);
            if (labels)
                t.expect(sameBits(S.s[NEAREST_NEIGHBOR_DIST], 0.0f) &&
                             sameBits(S.s[NEAREST_NEIGHBOR_AGE], evomath::tanhf((10.0f - 50.0f) / 50.0f)) &&
                             S.s[GENETIC_SIM_FWD] == 0.5f,
                         "%s: nearest dist %.9g age %.9g", name, S.s[NEAREST_NEIGHBOR_DIST], S.s[NEAREST_NEIGHBOR_AGE]);
        }
        // (4) Rounded-sqrt ties: A at d² = 1 + 2^-23 (dx 1, dz 3·2^-13), B at d² = 1
        // (dy 1): sqrt 1 for both.
        {
            const float z = 1.0f, za = 1.0f + 3.0f / 8192.0f;
            const float dz = za - z, d2a = 1.0f * 1.0f + 0.0f * 0.0f + dz * dz;
            t.expect(bitsOf(d2a) == 0x3f800001u && std::sqrt(d2a) == 1.0f, "fixture: d2a 0x%08x sqrt %.9g", bitsOf(d2a),
                     std::sqrt(d2a));
            for (int ba = 0; ba < 2; ++ba) {
                OceanWorld w;
                world(w, 305, m, false);
                addQuiet(w, 650.0f, 450.0f, z, east);
                if (!ba) { addFood(w, 651.0f, 450.0f, za); addFood(w, 650.0f, 451.0f, z); }
                else     { addFood(w, 650.0f, 451.0f, z); addFood(w, 651.0f, 450.0f, za); }
                std::snprintf(name, sizeof name, "sqrt tie food %s (%s)", ba ? "B first" : "A first", m.name);
                const Sensed S = stepAndCompare(t, name, w);
                if (labels)
                    t.expect(ba ? (S.s[NEAREST_FOOD_DX] == 0.0f && S.s[NEAREST_FOOD_DY] == 1.0f)
                                : (S.s[NEAREST_FOOD_DX] == 1.0f && S.s[NEAREST_FOOD_DY] == 0.0f && S.s[NEAREST_FOOD_DZ] == dz),
                             "%s: the first visited did not win (dx %.9g dy %.9g dz %.9g)", name, S.s[NEAREST_FOOD_DX],
                             S.s[NEAREST_FOOD_DY], S.s[NEAREST_FOOD_DZ]);
            }
            // Neighbours: A (age 10) ahead, B (age 90) to the right. Metric: the
            // first visited; topological: B, the smaller d², in either order.
            for (int topo : {0, 1, 2})
                for (int ba = 0; ba < 2; ++ba) {
                    OceanWorld w;
                    world(w, 306, m, false, topo);
                    addQuiet(w, 650.0f, 450.0f, z, east);
                    if (!ba) { addQuiet(w, 651.0f, 450.0f, za, east, 10.0f); addQuiet(w, 650.0f, 451.0f, z, east, 90.0f); }
                    else     { addQuiet(w, 650.0f, 451.0f, z, east, 90.0f); addQuiet(w, 651.0f, 450.0f, za, east, 10.0f); }
                    std::snprintf(name, sizeof name, "sqrt tie neighbour topo %d %s (%s)", topo, ba ? "B first" : "A first",
                                  m.name);
                    const Sensed S = stepAndCompare(t, name, w);
                    const bool wantB = topo ? true : (ba == 1);
                    if (labels)
                        t.expect(sameBits(S.s[NEAREST_NEIGHBOR_AGE], evomath::tanhf(((wantB ? 90.0f : 10.0f) - 50.0f) / 50.0f)) &&
                                     S.s[GENETIC_SIM_FWD] == (wantB ? 0.5f : 0.0f) && S.s[NEAREST_NEIGHBOR_DIST] == 0.01f,
                                 "%s: nearest age %.9g sim_fwd %.9g, expected %s", name, S.s[NEAREST_NEIGHBOR_AGE],
                                 S.s[GENETIC_SIM_FWD], wantB ? "B" : "A");
                }
        }
        // (5) Exactly R: counted, never the nearest; R + 2e-5 by depth: not
        // counted. Bounded (R ahead) and across the seam (R behind, wrapped).
        for (int tor = 0; tor < 2; ++tor)
            for (int topo : {0, 3}) {
                OceanWorld w;
                world(w, 307, m, tor != 0, topo);
                const float zFar = std::nextafter(220.0f, 1000.0f);
                const float vx = tor ? 10.0f : 600.0f, rx = tor ? 1830.0f : 700.0f;   // the item / fish exactly R away
                addQuiet(w, vx, 500.0f, 120.0f, east);
                addFood(w, rx, 500.0f, 120.0f);
                addFood(w, vx, 500.0f, zFar);
                addQuiet(w, rx, 500.0f, 120.0f, east, 10.0f);
                addQuiet(w, vx, 500.0f, zFar, east, 20.0f);
                t.expect(zFar - 120.0f > R, "fixture: past-R depth offset %.9g", zFar - 120.0f);
                std::snprintf(name, sizeof name, "exactly R%s topo %d (%s)", tor ? " wrapped" : "", topo, m.name);
                const Sensed S = stepAndCompare(t, name, w);
                if (labels) {
                    t.expect(sameBits(S.s[FOOD_DENSITY], tanhCountOver10(1)) && S.s[NEAREST_FOOD_DIST] == 1.0f &&
                                 sameBits(S.s[NEAREST_FOOD_DX], 0.0f),
                             "%s: food at R: density %.9g nearest %.9g dx %.9g", name, S.s[FOOD_DENSITY], S.s[NEAREST_FOOD_DIST],
                             S.s[NEAREST_FOOD_DX]);
                    t.expect(sameBits(S.s[NEIGHBOR_COUNT], tanhCountOver10(1)) && S.s[NEAREST_NEIGHBOR_DIST] == 1.0f &&
                                 sameBits(S.s[NEAREST_NEIGHBOR_AGE], 0.0f) && S.s[GENETIC_SIM_FWD] == 0.5f &&
                                 S.s[AVG_NEIGHBOR_DX] == evomath::tanhf(tor ? -1.0f : 1.0f),
                             "%s: neighbour at R: count %.9g nearest %.9g age %.9g", name, S.s[NEIGHBOR_COUNT],
                             S.s[NEAREST_NEIGHBOR_DIST], S.s[NEAREST_NEIGHBOR_AGE]);
                }
#ifdef EVO_OCEAN_EYE
                if (m.eye && !(m.code & kEyeCodeSummed))
                    t.expect(S.s[tor ? EYE_BEHIND_PROX : EYE_AHEAD_PROX] == 0.0f && S.s[EYE_DOWN_SIZE] == 0.0f,
                             "%s: eye prox %.9g (want 0: at R), down size %.9g (want 0: past R)", name,
                             S.s[tor ? EYE_BEHIND_PROX : EYE_AHEAD_PROX], S.s[EYE_DOWN_SIZE]);
#endif
            }
        // (6) Ties across cells (bounded) and across the seam (toroidal).
        for (int tor = 0; tor < 2; ++tor)
            for (int topo : {0, 2}) {
                OceanWorld w;
                world(w, 308, m, tor != 0, topo);
                // bounded: viewer (100, 100); index 0 at +10 (its own cell), index 1 at
                // -10 (the column before: visited first). toroidal: viewer x 10;
                // index 0 at 1910 (-20 across the seam), index 1 at 30 (the central image).
                const float vx = tor ? 10.0f : 100.0f, y = tor ? 500.0f : 100.0f;
                const float x0 = tor ? 1910.0f : 110.0f, x1 = tor ? 30.0f : 90.0f;
                addQuiet(w, vx, y, 120.0f, east);
                addFood(w, x0, y, 120.0f);
                addFood(w, x1, y, 120.0f);
                addQuiet(w, x0, y, 120.0f, east, 10.0f);
                addQuiet(w, x1, y, 120.0f, east, 90.0f);
                std::snprintf(name, sizeof name, "%s tie topo %d (%s)", tor ? "seam" : "cell", topo, m.name);
                const Sensed S = stepAndCompare(t, name, w);
                const float wantDx = tor ? 1.0f : -1.0f;   // the item visited first
                // metric: the first visited (index 2's fish, age 90); topological: (d², index) -> index 1 (age 10)
                const float wantAge = evomath::tanhf(((topo ? 10.0f : 90.0f) - 50.0f) / 50.0f);
                if (labels)
                    t.expect(S.s[NEAREST_FOOD_DX] == wantDx && sameBits(S.s[NEAREST_NEIGHBOR_AGE], wantAge),
                             "%s: food dx %.9g (want %g), nearest age %.9g (want %.9g)", name, S.s[NEAREST_FOOD_DX], wantDx,
                             S.s[NEAREST_NEIGHBOR_AGE], wantAge);
            }
        // (6b) A narrow torus (250 x 250, R 100): viewer x 10, so cell column 1
        // ([100, 200)) is in the central image's run and in the +x image's; every
        // food item sits in it within R of the viewer, so all are kept by the
        // central image and are candidates again (rejected) in the +x image.
        {
            OceanWorld w;
            world(w, 312, m, /*toroidal*/ true);
            w.cfg.predatorPerception = 100.0f;   // every radius under min(W, H) / 2
            w.init(250, 250, 240.0f, 0);
            addQuiet(w, 10.0f, 125.0f, 120.0f, east);
            for (int j = 0; j < 13; ++j)
                addFood(w, 100.0f + 0.75f * (float)j, 125.0f + 3.0f * (float)(j % 5) - 6.0f, 110.0f + 1.5f * (float)j);
            addQuiet(w, 104.0f, 120.0f, 125.0f, east, 30.0f);
            std::snprintf(name, sizeof name, "narrow torus (%s)", m.name);
            const Sensed S = stepAndCompare(t, name, w);
            if (labels)
                t.expect(sameBits(S.s[FOOD_DENSITY], tanhCountOver10(13)), "%s: density %.9g, expected all 13 items", name,
                         S.s[FOOD_DENSITY]);
        }
        // (6c) NaN admission, food: five items in one cell, one with a NaN
        // depth (each slot in turn). Bounded: slots 0-3 are foodWithin's
        // four-wide batch, 4 its scalar tail; wrapped: across the seam, through
        // a translated image. Every path keeps the item (the literal !(d2 > R²)):
        // it is counted, never the nearest, and a summed eye adds its NaN (to
        // the down sector: no axis dominates a NaN). A path that took d2 <= R²
        // instead would drop it (density 4, a finite down sector).
        {
            const float qnan = std::numeric_limits<float>::quiet_NaN();
            for (int tor = 0; tor < 2; ++tor)
                for (int bad = 0; bad < 5; ++bad) {
                    OceanWorld w;
                    world(w, 311, m, tor != 0);
                    addQuiet(w, tor ? 10.0f : 620.0f, tor ? 500.0f : 520.0f, 120.0f, east);
                    for (int j = 0; j < 5; ++j)
                        addFood(w, (tor ? 1890.0f : 650.0f) + (float)j, tor ? 540.0f : 550.0f, j == bad ? qnan : 120.0f);
                    std::snprintf(name, sizeof name, "NaN food %s slot %d (%s)", tor ? "wrapped" : "bounded", bad, m.name);
                    const Sensed S = stepAndCompare(t, name, w);
                    if (labels)
                        t.expect(sameBits(S.s[FOOD_DENSITY], tanhCountOver10(5)), "%s: the NaN-depth item was not counted (density %.9g)",
                                 name, S.s[FOOD_DENSITY]);
#ifdef EVO_OCEAN_EYE
                    if (m.eye && (m.code & kEyeCodeSummed))
                        t.expect(std::isnan(S.s[EYE_DOWN_PROX]) && std::isnan(S.s[EYE_DOWN_SIZE]) && std::isnan(S.s[EYE_DOWN_CON]),
                                 "%s: the summed eye did not take in the NaN-depth item (down %.9g %.9g %.9g)", name, S.s[EYE_DOWN_PROX],
                                 S.s[EYE_DOWN_SIZE], S.s[EYE_DOWN_CON]);
#endif
                }
        }
        // (6d) NaN admission, neighbours: A (age 10), N (a NaN depth, age 50)
        // and B (age 90), 30 / 40 / 50 along x, N added first, between or
        // last; metric and topological (1, 2, 7 kept), bounded and across the
        // seam. N is kept (the literal !(d2 > R²)) and counted; it never is the
        // nearest; the topological cut's insertion takes it as its comparisons
        // fall (the reference's definition): with one kept and A, N, B, N
        // displaces A, then B displaces N, so B is the one attended.
        {
            const float qnan = std::numeric_limits<float>::quiet_NaN();
            struct Nb { float dx, z, age; };
            const Nb A = {0.0f, 120.0f, 10.0f}, N = {10.0f, qnan, 50.0f}, B = {20.0f, 120.0f, 90.0f};
            for (int tor = 0; tor < 2; ++tor)
                for (int at = 0; at < 3; ++at)
                    for (int topo : {0, 1, 2, 7}) {
                        OceanWorld w;
                        world(w, 313, m, tor != 0, topo);
                        addQuiet(w, tor ? 10.0f : 620.0f, tor ? 500.0f : 520.0f, 120.0f, east);
                        const Nb order[3][3] = {{N, A, B}, {A, N, B}, {A, B, N}};
                        for (const Nb& o : order[at])
                            addQuiet(w, (tor ? 1890.0f : 650.0f) + o.dx, tor ? 540.0f : 550.0f, o.z, east, o.age);
                        std::snprintf(name, sizeof name, "NaN neighbour %s %s topo %d (%s)", tor ? "wrapped" : "bounded",
                                      at == 0 ? "first" : at == 1 ? "between" : "last", topo, m.name);
                        const Sensed S = stepAndCompare(t, name, w);
                        if (labels)
                            t.expect(sameBits(S.s[NEIGHBOR_COUNT], tanhCountOver10(3)) && !std::isnan(S.s[NEAREST_NEIGHBOR_DIST]),
                                     "%s: count %.9g (want 3, the NaN-depth fish among them), nearest %.9g", name, S.s[NEIGHBOR_COUNT],
                                     S.s[NEAREST_NEIGHBOR_DIST]);
                        if (labels && !tor && at == 1 && topo == 1)
                            t.expect(sameBits(S.s[NEAREST_NEIGHBOR_AGE], evomath::tanhf((90.0f - 50.0f) / 50.0f)) &&
                                         sameBits(S.s[NEAREST_NEIGHBOR_DIST], std::sqrt(3400.0f) / 100.0f),
                                     "%s: the one kept is not B (age %.9g, dist %.9g)", name, S.s[NEAREST_NEIGHBOR_AGE],
                                     S.s[NEAREST_NEIGHBOR_DIST]);
#ifdef EVO_OCEAN_EYE
                        if (m.eye && (m.code & kEyeCodeSummed))
                            t.expect(std::isnan(S.s[EYE_DOWN_PROX]) && std::isnan(S.s[EYE_DOWN_SIZE]) && std::isnan(S.s[EYE_DOWN_CON]),
                                     "%s: the summed eye did not take in the NaN-depth fish", name);
#endif
                    }
        }
        // (7) mouthGate: X (size 2, nearest) seen but not food; Y (size 1.2 ==
        // kMouth·L) the nearest food; Z behind; N a NaN depth and S a NaN size,
        // both counted, neither the nearest. Visit order: S, Z, X, Y, N.
        for (int gate = 0; gate < 2; ++gate) {
            OceanWorld w;
            world(w, 309, m, false, 0, gate != 0);
            addQuiet(w, 600.0f, 500.0f, 120.0f, east);
            const float qnan = std::numeric_limits<float>::quiet_NaN();
            addFood(w, 610.0f, 500.0f, 120.0f, 2.0f);    // X
            addFood(w, 630.0f, 500.0f, 120.0f, 1.2f);    // Y
            addFood(w, 550.0f, 500.0f, 120.0f, 1.0f);    // Z
            addFood(w, 640.0f, 520.0f, qnan, 1.0f);      // N
            addFood(w, 660.0f, 480.0f, 120.0f, qnan);    // S
            // (a summed eye adds N's NaN to its sector: sameSense compares that by class)
            std::snprintf(name, sizeof name, "mouth gate %d (%s)", gate, m.name);
            const Sensed S = stepAndCompare(t, name, w);
            if (labels) {
                const float wantDx = gate ? 30.0f * (1.0f / 30.0f) : 10.0f * (1.0f / 10.0f);
                t.expect(sameBits(S.s[FOOD_DENSITY], tanhCountOver10(gate ? 4 : 5)) && S.s[NEAREST_FOOD_DX] == wantDx &&
                             S.s[NEAREST_FOOD_DIST] == (gate ? 0.3f : 0.1f),
                         "%s: density %.9g dx %.9g nearest %.9g", name, S.s[FOOD_DENSITY], S.s[NEAREST_FOOD_DX],
                         S.s[NEAREST_FOOD_DIST]);
            }
#ifdef EVO_OCEAN_EYE
            if (m.eye && !(m.code & kEyeCodeSummed))   // the eye sees X whatever its size
                t.expect(S.s[EYE_AHEAD_PROX] == 1.0f - 10.0f / R, "%s: eye ahead prox %.9g, X not seen", name,
                         S.s[EYE_AHEAD_PROX]);
#endif
        }
        // (12) Five equal items exactly R away, in one cell: all counted, none
        // the nearest. Bounded: four in foodWithin's batch, one in its tail
        // (the 2-D test q2 <= R² and the 3-D test both at equality); wrapped:
        // across the seam, through a translated image. The eye sees them at R
        // (proximity 0, size not).
        for (int tor = 0; tor < 2; ++tor) {
            OceanWorld w;
            world(w, 314, m, tor != 0);
            addQuiet(w, tor ? 10.0f : 600.0f, 500.0f, 120.0f, east);
            for (int j = 0; j < 5; ++j) addFood(w, tor ? 1830.0f : 700.0f, 500.0f, 120.0f);
            std::snprintf(name, sizeof name, "five at R %s (%s)", tor ? "wrapped" : "bounded", m.name);
            const Sensed S = stepAndCompare(t, name, w);
            if (labels)
                t.expect(sameBits(S.s[FOOD_DENSITY], tanhCountOver10(5)) && S.s[NEAREST_FOOD_DIST] == 1.0f &&
                             sameBits(S.s[NEAREST_FOOD_DX], 0.0f),
                         "%s: density %.9g (want 5), nearest %.9g (want none)", name, S.s[FOOD_DENSITY], S.s[NEAREST_FOOD_DIST]);
#ifdef EVO_OCEAN_EYE
            if (m.eye) {
                const int sz = tor ? EYE_BEHIND_SIZE : EYE_AHEAD_SIZE;
                t.expect(S.s[sz] > 0.0f, "%s: the eye does not see the items at R (%s %.9g)", name, ocean::kSensorNames[sz], S.s[sz]);
            }
#endif
        }
        // (12b) One item exactly R away, alone in its sector (ahead): the last
        // of foodWithin's four-wide batch (three nearer items behind it, in the
        // same row's run) or its scalar tail (four behind). A nearest-only eye
        // sees it at R too (in (12) the other four at R fill the bin), so a
        // strict R on either path shows in every mode.
        for (int tail = 0; tail < 2; ++tail) {
            OceanWorld w;
            world(w, 320, m, false);
            addQuiet(w, 600.0f, 500.0f, 120.0f, east);
            for (int k = 0; k < 3 + tail; ++k) addFood(w, 510.0f + (float)k, 500.0f, 120.0f);
            addFood(w, 700.0f, 500.0f, 120.0f);
            std::snprintf(name, sizeof name, "one at R, %s (%s)", tail ? "the tail" : "the batch's last", m.name);
            const Sensed S = stepAndCompare(t, name, w);
            if (labels)
                t.expect(sameBits(S.s[FOOD_DENSITY], tanhCountOver10(4 + tail)), "%s: density %.9g (want %d)", name, S.s[FOOD_DENSITY],
                         4 + tail);
#ifdef EVO_OCEAN_EYE
            if (m.eye && !(m.code & kEyeCodeSummed))
                t.expect(S.s[EYE_AHEAD_PROX] == 0.0f && S.s[EYE_AHEAD_SIZE] > 0.0f, "%s: the eye does not see the item at R (%.9g %.9g)",
                         name, S.s[EYE_AHEAD_PROX], S.s[EYE_AHEAD_SIZE]);
#endif
        }
        // (13) The viewer alone: the grid lists it for its own query, and it is
        // never its own neighbour.
        for (int tor = 0; tor < 2; ++tor) {
            OceanWorld w;
            world(w, 315, m, tor != 0);
            addQuiet(w, tor ? 10.0f : 600.0f, 500.0f, 120.0f, east);
            std::snprintf(name, sizeof name, "alone %s (%s)", tor ? "wrapped" : "bounded", m.name);
            const Sensed S = stepAndCompare(t, name, w);
            if (labels)
                t.expect(sameBits(S.s[NEIGHBOR_COUNT], tanhCountOver10(0)) && S.s[NEAREST_NEIGHBOR_DIST] == 1.0f,
                         "%s: count %.9g nearest %.9g: it sensed itself", name, S.s[NEIGHBOR_COUNT], S.s[NEAREST_NEIGHBOR_DIST]);
        }
        // (14) The mouth gate at its edges (kMouth 1.2, body size 1): items 30
        // (size 2: seen, not food), 50 (size 1.2, the limit: food, the nearest)
        // and 70 away (a NaN size: food, counted, not the nearest), ahead
        // bounded, behind across the seam.
        for (int tor = 0; tor < 2; ++tor) {
            OceanWorld w;
            world(w, 316, m, tor != 0, 0, /*mouthGate*/ true);
            const int v = addQuiet(w, tor ? 10.0f : 600.0f, 500.0f, 120.0f, east);
            w.creatures[v].bodySize = 1.0f;
            const float sgn = tor ? -1.0f : 1.0f, x0 = tor ? 1930.0f : 600.0f;
            const float offs[3] = {30.0f, 50.0f, 70.0f}, sizes[3] = {2.0f, 1.2f, std::numeric_limits<float>::quiet_NaN()};
            for (int k = 0; k < 3; ++k) addFood(w, x0 + sgn * offs[k], 500.0f, 120.0f, sizes[k]);
            std::snprintf(name, sizeof name, "mouth edges %s (%s)", tor ? "wrapped" : "bounded", m.name);
            const Sensed S = stepAndCompare(t, name, w);
            if (labels)
                t.expect(sameBits(S.s[FOOD_DENSITY], tanhCountOver10(2)) && S.s[NEAREST_FOOD_DIST] == 50.0f / R &&
                             S.s[NEAREST_FOOD_DX] == sgn * (50.0f * (1.0f / 50.0f)),
                         "%s: density %.9g (want 2), nearest %.9g dx %.9g (want the size-1.2 item at 50)", name, S.s[FOOD_DENSITY],
                         S.s[NEAREST_FOOD_DIST], S.s[NEAREST_FOOD_DX]);
#ifdef EVO_OCEAN_EYE
            if (m.eye && !(m.code & kEyeCodeSummed)) {
                const int px = tor ? EYE_BEHIND_PROX : EYE_AHEAD_PROX;
                t.expect(S.s[px] == 1.0f - 30.0f / R, "%s: the eye's nearest %.9g, not the size-2 item at 30", name, S.s[px]);
            }
#endif
        }
        // (15) Signed zeros carried through: the viewer at +0 and the items at
        // -0 on one axis (x, y or depth), so the offset is -0 and so is the
        // nearest item's direction on that axis; bounded and wrapped.
        for (int tor = 0; tor < 2; ++tor)
            for (int axis = 0; axis < 3; ++axis) {
                OceanWorld w;
                world(w, 317, m, tor != 0);
                const float pz = 0.0f, nz = -0.0f;
                addQuiet(w, axis == 0 ? pz : 600.0f, axis == 1 ? pz : 500.0f, axis == 2 ? pz : 120.0f, east);
                for (int j = 0; j < 5; ++j)
                    addFood(w, axis == 0 ? nz : 650.0f + (float)j, axis == 0 ? 550.0f + (float)j : axis == 1 ? nz : 500.0f,
                            axis == 2 ? nz : 120.0f);
                std::snprintf(name, sizeof name, "-0 along %c %s (%s)", "xyz"[axis], tor ? "wrapped" : "bounded", m.name);
                const Sensed S = stepAndCompare(t, name, w);
                const int k = axis == 0 ? NEAREST_FOOD_DX : axis == 1 ? NEAREST_FOOD_DY : NEAREST_FOOD_DZ;
                if (labels)
                    t.expect(bitsOf(S.s[k]) == 0x80000000u, "%s: %s = %.9g (0x%08x), want -0", name, ocean::kSensorNames[k], S.s[k],
                             bitsOf(S.s[k]));
            }
        // (16) Expiry before the scans: foodLife 2·dt; an item aged dt reaches it
        // exactly this step (expired: unseen), a survivor aged 0 is seen; the
        // next step the survivor reaches it too (the grid rebuilt after the
        // erase sees nothing).
        for (int tor = 0; tor < 2; ++tor) {
            OceanWorld w;
            world(w, 318, m, tor != 0);
            const float dt = 0.016f;
            w.ocfg.foodLife = 2.0f * dt;
            w.cfg.pickupRadius = 0.0f;
            addQuiet(w, 600.0f, 500.0f, 120.0f, east);
            w.food[addFood(w, 640.0f, 500.0f, 120.0f)].age = dt;
            w.food[addFood(w, 660.0f, 500.0f, 130.0f)].age = 0.0f;
            t.expect(dt + dt == w.ocfg.foodLife, "fixture: dt + dt %.9g, foodLife %.9g", dt + dt, w.ocfg.foodLife);
            const long long exp0 = w.totalFoodExpired;
            std::snprintf(name, sizeof name, "expiry %s (%s)", tor ? "wrapped" : "bounded", m.name);
            const Sensed S = stepAndCompareFoodPhase(t, name, w);
            t.expect(w.totalFoodExpired == exp0 + 1 && w.food.size() == 1, "%s: %lld expired, %zu left (want 1, 1)", name,
                     (long long)(w.totalFoodExpired - exp0), w.food.size());
            if (labels) {
                const float d = std::sqrt(3700.0f), inv = 1.0f / d;
                t.expect(sameBits(S.s[FOOD_DENSITY], tanhCountOver10(1)) && sameBits(S.s[NEAREST_FOOD_DIST], d / R) &&
                             sameBits(S.s[NEAREST_FOOD_DX], 60.0f * inv) && sameBits(S.s[NEAREST_FOOD_DZ], 10.0f * inv),
                         "%s: density %.9g, nearest %.9g dx %.9g dz %.9g: not the survivor alone", name, S.s[FOOD_DENSITY],
                         S.s[NEAREST_FOOD_DIST], S.s[NEAREST_FOOD_DX], S.s[NEAREST_FOOD_DZ]);
            }
            std::snprintf(name, sizeof name, "expiry, next step %s (%s)", tor ? "wrapped" : "bounded", m.name);
            const Sensed S2 = stepAndCompareFoodPhase(t, name, w);
            t.expect(w.totalFoodExpired == exp0 + 2 && w.food.empty(), "%s: the survivor did not expire on time", name);
            if (labels)
                t.expect(sameBits(S2.s[FOOD_DENSITY], tanhCountOver10(0)) && S2.s[NEAREST_FOOD_DIST] == 1.0f,
                         "%s: density %.9g: an expired item was seen", name, S2.s[FOOD_DENSITY]);
        }
        // (17) Spawning before the scans, and (18) a replacement at the cap:
        // one patch at (650, 500), depth 120, radius and spread 0. (17) an
        // empty world, five spawned this step (rate 5, target 3: cap 6), all
        // seen, aged 0; (18) target 1 (cap 2) and a stock of two, one reaching
        // foodLife this step: its place is free at once, so one is spawned
        // (the stock stays two) and the scans see the survivor and the newborn.
        for (int replace = 0; replace < 2; ++replace)
            for (int tor = 0; tor < 2; ++tor) {
                OceanWorld w;
                world(w, 319, m, tor != 0);
                const float dt = 0.016f;
                w.cfg.pickupRadius = 0.0f;
                w.cfg.foodSpawnBase = replace ? 1.0f : 5.0f;
                w.cfg.foodSpawnAmp = 0.0f;
                w.cfg.targetFood = replace ? 1 : 3;
                w.cfg.foodPatchRadius = 0.0f;
                w.ocfg.foodDepthMode = 1;
                w.ocfg.foodDepthSpread = 0.0f;
                ofp::field<ofp::peek::OwPatches>(w).assign(1, Vec2{650.0f, 500.0f});
                ofp::field<ofp::peek::OwPatchDepth>(w).assign(1, 120.0f);
                addQuiet(w, 600.0f, 500.0f, 120.0f, east);
                if (replace) {
                    w.ocfg.foodLife = 2.0f * dt;
                    w.food[addFood(w, 640.0f, 500.0f, 120.0f)].age = dt;   // expires this step
                    w.food[addFood(w, 660.0f, 500.0f, 130.0f)].age = 0.0f;
                }
                std::snprintf(name, sizeof name, "%s %s (%s)", replace ? "replacement" : "spawn", tor ? "wrapped" : "bounded", m.name);
                const Sensed S = stepAndCompareFoodPhase(t, name, w);
                int born = 0;
                for (const OceanFood& f : w.food)
                    born += f.pos.x == 650.0f && f.pos.y == 500.0f && f.depth == 120.0f && f.age == 0.0f;
                t.expect(replace ? (w.food.size() == 2 && born == 1 && w.totalFoodExpired == 1) : (w.food.size() == 5 && born == 5),
                         "%s: %zu items, %d newborn at the patch, %lld expired", name, w.food.size(), born, (long long)w.totalFoodExpired);
                if (labels)
                    t.expect(sameBits(S.s[FOOD_DENSITY], tanhCountOver10(replace ? 2 : 5)) && S.s[NEAREST_FOOD_DIST] == 50.0f / R &&
                                 S.s[NEAREST_FOOD_DX] == 50.0f * (1.0f / 50.0f),
                             "%s: density %.9g, nearest %.9g: the newborn not seen this step", name, S.s[FOOD_DENSITY],
                             S.s[NEAREST_FOOD_DIST]);
            }
        // (19) Drift before the scans: the E1 flow (waves 6, a deep current of
        // 40, food drifting) moves five items and changes their depths; over
        // two steps the scans see the food where the step left it (position,
        // depth and, with the eye, contrast), bounded and wrapped.
        for (int tor = 0; tor < 2; ++tor) {
            OceanWorld w;
            OceanConfig oc;
#ifdef EVO_OCEAN_EYE
            oc.eye = m.eye;
            oc.eyeCode = m.code;
            oc.eyeOnly = m.only;
#endif
            oc.waveSpeed = 6.0f;
            oc.deepCurrent = true;
            initQuiet(w, 312, 240.0f, oc, /*capture*/ true, tor != 0, /*current*/ 40.0f);
            w.cfg.foodDrift = true;
            w.cfg.pickupRadius = 0.0f;
            addQuiet(w, 600.0f, 500.0f, 120.0f, east);
            for (int j = 0; j < 5; ++j) addFood(w, 650.0f + (float)j, 530.0f, 80.0f + 20.0f * (float)j);
            for (int s = 1; s <= 2; ++s) {
                const std::vector<OceanFood> before = w.food;
                std::snprintf(name, sizeof name, "drift step %d %s (%s)", s, tor ? "wrapped" : "bounded", m.name);
                stepAndCompareFoodPhase(t, name, w);
                int moved = 0, deeper = 0;
                for (std::size_t j = 0; j < w.food.size() && j < before.size(); ++j) {
                    moved += w.food[j].pos.x != before[j].pos.x || w.food[j].pos.y != before[j].pos.y;
                    deeper += w.food[j].depth != before[j].depth;
                }
                t.expect(w.food.size() == 5 && moved > 0 && deeper > 0, "%s: fixture: %d of 5 items moved, %d changed depth", name, moved,
                         deeper);
            }
        }
    }

    // (8) The hot state: the viewer (index 4) steps after fish 0..3, which have
    // moved; fish 5, 6 have not. 0 starts within R and swims out (dropped by the
    // 3-D test on its moved offset); 1 starts outside R and swims in (not a grid
    // candidate: unseen); 2 is seen where it moved (position, depth, heading,
    // age: the nearest); 5 where it starts. The long probe (200 ahead): fish 3
    // starts exactly 30 deeper and sinks (its moved depth is out), fish 6 is
    // exactly 30 deeper and has not stepped (in).
    for (int eyeOn = 0; eyeOn < (kOceanHasEye ? 2 : 1); ++eyeOn) {
        OceanWorld w;
        world(w, 310, kEyeModes[std::min<std::size_t>((std::size_t)eyeOn, std::size(kEyeModes) - 1)], false);
        const float z = 120.0f;
        addQuiet(w, 699.5f, 500.0f, z, east);                       // 0
        addQuiet(w, 499.5f, 500.0f, z, east);                       // 1
        addQuiet(w, 620.0f, 510.0f, z, {0.0f, 1.0f}, 20.0f, 40.0f); // 2
        addQuiet(w, 800.0f, 500.0f, z + 30.0f, {0.0f, 1.0f});       // 3
        const int v = addQuiet(w, 600.0f, 500.0f, z, east);         // 4: the viewer
        addQuiet(w, 570.0f, 480.0f, 130.0f, {-1.0f, 0.0f}, 60.0f);  // 5
        addQuiet(w, 810.0f, 500.0f, z + 30.0f, {0.0f, 1.0f});       // 6
        w.creatures[2].bodyBuoy = 1.0f;
        w.creatures[3].bodyBuoy = 1.0f;
        const std::vector<Fish> start = w.creatures;
        w.update(0.016f);
        const float* S = w.creatures[v].lastSensors;
        const Fish& c = start[v];
        const Vec2 fwd = c.forward(), rht = {-fwd.y, fwd.x};
        auto hot = [&](int i) -> const Fish& { return i < v ? w.creatures[i] : start[i]; };   // moved iff stepped first
        auto d2of = [&](const Fish& o) {
            const float dx = o.pos.x - c.pos.x, dy = o.pos.y - c.pos.y, dz = o.depth - c.depth;
            return dx * dx + dy * dy + dz * dz;
        };
        t.expect(d2of(hot(0)) > R * R && d2of(hot(1)) <= R * R && w.creatures[3].depth > z + 30.0f &&
                     w.creatures[2].depth != z && w.creatures[2].age != 20.0f,
                 "fixture: fish 0 moved to d2 %.9g, fish 1 to %.9g, fish 3 depth %.9g, fish 2 depth %.9g", d2of(hot(0)),
                 d2of(hot(1)), w.creatures[3].depth, w.creatures[2].depth);
        // The grid's visit order for the viewer's query: 5 (row 4), then 0, 2 (cell (6, 5)).
        float avgDx = 0, avgDy = 0, avgDz = 0, avgHx = 0, avgHy = 0, nearestDist = R;
        int nearest = -1, n = 0, popFwd = 0, popLR = 0;
        for (int i : {5, 0, 2}) {
            const Fish& o = hot(i);
            const float dx = o.pos.x - c.pos.x, dy = o.pos.y - c.pos.y, dz = o.depth - c.depth;
            const float d2 = dx * dx + dy * dy + dz * dz;
            if (d2 > R * R) continue;
            avgDx += dx; avgDy += dy; avgDz += dz; avgHx += o.vel.x; avgHy += o.vel.y;
            popFwd += (dx * fwd.x + dy * fwd.y > 0) ? 1 : -1;
            popLR += (dx * rht.x + dy * rht.y > 0) ? 1 : -1;
            const float dist = std::sqrt(d2);
            if (dist < nearestDist) { nearestDist = dist; nearest = i; }
            ++n;
        }
        avgDx /= n; avgDy /= n; avgDz /= n; avgHx /= n; avgHy /= n;
        t.expect(n == 2 && nearest == 2, "fixture: %d neighbours, nearest %d", n, nearest);
        const float want[][2] = {
            {(float)NEIGHBOR_COUNT, tanhCountOver10(2)},
            {(float)AVG_NEIGHBOR_DX, evomath::tanhf(avgDx / R)},
            {(float)AVG_NEIGHBOR_DY, evomath::tanhf(avgDy / R)},
            {(float)AVG_NEIGHBOR_DZ, evomath::tanhf(avgDz / R)},
            {(float)AVG_NEIGHBOR_HEADING_X, avgHx},
            {(float)AVG_NEIGHBOR_HEADING_Y, avgHy},
            {(float)NEAREST_NEIGHBOR_DIST, nearestDist / R},
            {(float)POPULATION_FWD, tanhCountOver5(popFwd)},
            {(float)POPULATION_LR, tanhCountOver5(popLR)},
            {(float)NEAREST_NEIGHBOR_AGE, evomath::tanhf((w.creatures[2].age - 50.0f) / 50.0f)},
            {(float)NEAREST_NEIGHBOR_FOOD, evomath::tanhf((w.creatures[2].foodReserves - 25.0f) / 25.0f)},
            {(float)LONGPROBE_POP_FWD, tanhCountOver5(1)},
        };
        for (const auto& p : want) {
            const int k = (int)p[0];
            t.expect(sameBits(S[k], p[1]), "hot state (eye %d): %s = %.9g, expected %.9g", eyeOn, ocean::kSensorNames[k], S[k],
                     p[1]);
        }
    }

#ifdef EVO_OCEAN_EYE
    // (9) Summed sectors: a fish, three food items (77 ahead in row 4, then 11
    // and 43 ahead in row 5) and a predator, all ahead: five unequal terms
    // summed in the visit order. The fixture is one where some other order of the same
    // five terms gives other bits, so the order is what is being checked.
    for (int only = 0; only < 2; ++only) {
        OceanWorld w;
        world(w, 311, {1, kEyeCodeSummed, only, "summed"}, false);
        const Vec2 P = {600.0f, 500.0f};
        const float z = 120.0f;
        addQuiet(w, P.x, P.y, z, east);
        const int f = addQuiet(w, 655.0f, 503.0f, 117.0f, east);
        w.creatures[f].bodySize = 1.3f;
        addFood(w, 677.0f, 497.0f, 128.0f);
        addFood(w, 611.0f, 500.0f, 121.5f);
        addFood(w, 643.0f, 504.0f, 113.0f);
        OceanPredator pr;
        pr.pos = {690.0f, 510.0f};
        pr.vel = east;
        pr.depth = 125.0f;
        pr.digestTimer = 1e9f;
        w.predators.push_back(pr);
        struct Term { float p, s, c; };
        std::vector<Term> terms;
        auto term = [&](float x, float y, float oz, float size, float con) {
            const float dx = x - P.x, dy = y - P.y, dz = oz - z, d2 = dx * dx + dy * dy + dz * dz;
            const float d = std::sqrt(d2), p = 1.0f - d / R;
            terms.push_back({p, size / (size + d), p * con});
        };
        term(655.0f, 503.0f, 117.0f, ocean::kEyeFishLen * 1.3f, ocean::eyeContrast(ocean::kEyeFishBright, 117.0f));
        term(677.0f, 497.0f, 128.0f, ocean::kEyeFoodSize, ocean::eyeContrast(ocean::kEyeFoodBright, 128.0f));
        term(611.0f, 500.0f, 121.5f, ocean::kEyeFoodSize, ocean::eyeContrast(ocean::kEyeFoodBright, 121.5f));
        term(643.0f, 504.0f, 113.0f, ocean::kEyeFoodSize, ocean::eyeContrast(ocean::kEyeFoodBright, 113.0f));
        term(690.0f, 510.0f, 125.0f, ocean::kEyePredSize, ocean::eyeContrast(ocean::kEyePredBright, 125.0f));
        auto sums = [&](const int* o, float out[3]) {
            out[0] = out[1] = out[2] = 0.0f;
            for (int j = 0; j < 5; ++j) { out[0] += terms[o[j]].p; out[1] += terms[o[j]].s; out[2] += terms[o[j]].c; }
        };
        int ord[5] = {0, 1, 2, 3, 4};
        float base[3];
        sums(ord, base);
        bool sensitive = false;
        while (std::next_permutation(ord, ord + 5)) {
            float o[3];
            sums(ord, o);
            for (int k = 0; k < 3; ++k) sensitive |= !sameBits(o[k], base[k]);
        }
        t.expect(sensitive, "fixture: every order of the five terms gives the same sums (the check would not bite)");
        const Sensed S = stepAndCompare(t, only ? "summed order (eye-only)" : "summed order", w);
        auto q = [](float x) { return x / (1.0f + std::abs(x)); };
        t.expect(sameBits(S.s[EYE_AHEAD_PROX], q(base[0])) && sameBits(S.s[EYE_AHEAD_SIZE], q(base[1])) &&
                     sameBits(S.s[EYE_AHEAD_CON], q(base[2])),
                 "summed order: ahead %.9g %.9g %.9g, the visit-order sums give %.9g %.9g %.9g", S.s[EYE_AHEAD_PROX],
                 S.s[EYE_AHEAD_SIZE], S.s[EYE_AHEAD_CON], q(base[0]), q(base[1]), q(base[2]));
    }
#endif
}

// Randomized scenes against the reference. Offsets come from a small lattice
// (multiples of 10, exact R, the 3-4-5 triangle (60, 80), halves and eighths)
// so equal distances, zero distances and points exactly on R are common; the
// viewer sits anywhere, often on a world edge or (toroidal) next to the seam.
// labelFrame 1 ("sense_ref_a1"): the same 600 scenes with own-frame labels.
void testSenseRef(int labelFrame = 0) {
    using namespace sense;
    Test t(labelFrame ? "sense_ref_a1" : "sense_ref");
    std::uint32_t s = 0x9e3779b9u;
    auto next = [&]() { s ^= s << 13; s ^= s >> 17; s ^= s << 5; return s; };
    auto pick = [&](int n) { return (int)(next() % (std::uint32_t)n); };
    auto unit = [&]() { return (float)(next() >> 8) * (1.0f / 16777216.0f); };
    auto offset = [&]() -> float {
        switch (pick(6)) {
            case 0: return 10.0f * (float)(pick(23) - 11);
            case 1: return pick(2) ? 100.0f : -100.0f;
            case 2: return (pick(2) ? 1.0f : -1.0f) * (pick(2) ? 60.0f : 80.0f);
            case 3: return 0.5f * (float)(pick(441) - 220);
            case 4: return 0.125f * (float)(pick(1761) - 880);
            default: return 0.0f;
        }
    };
    long scenes = 0, compared = 0, nonEmptyFood = 0, nonEmptyFish = 0;
    const int nScenes = 600;
    for (int sc = 0; sc < nScenes; ++sc) {
        const bool tor = pick(2) != 0;
        const int topo = pick(3) ? 0 : 1 + pick(7);
        const bool gate = pick(3) == 0;
        const EyeMode& m = kEyeModes[pick((int)(sizeof kEyeModes / sizeof kEyeModes[0]))];
        OceanConfig oc;
#ifdef EVO_OCEAN_EYE
        oc.eye = m.eye;
        oc.eyeCode = m.code;
        oc.eyeOnly = m.only;
#endif
        oc.mouthGate = gate;
        oc.kMouth = pick(2) ? 1.2f : 1.0f;
        oc.labelFrame = labelFrame;
        OceanWorld w;
        initQuiet(w, 400 + sc, 240.0f, oc, /*capture*/ true, tor);
        w.cfg.maxNeighbors = topo;
        const float W = 1920.0f, H = 1080.0f, D = 240.0f;
        auto coordX = [&]() {
            switch (pick(5)) {
                case 0: return 0.5f * (float)pick(50);              // the left / bottom edge
                case 1: return W - 0.5f - 0.5f * (float)pick(50);   // the right edge
                default: return 0.5f * (float)pick(3840);
            }
        };
        auto coordY = [&]() {
            switch (pick(5)) {
                case 0: return 0.5f * (float)pick(50);
                case 1: return H - 0.5f - 0.5f * (float)pick(50);
                default: return 0.5f * (float)pick(2160);
            }
        };
        const float vx = coordX(), vy = coordY();
        const float vz = pick(4) ? 0.25f * (float)pick(961) : (pick(2) ? 0.0f : D);
        static const Vec2 kHead[] = {{1, 0}, {0, 1}, {-1, 0}, {0, -1}, {0.6f, 0.8f}, {-0.8f, 0.6f}};
        const Vec2 head = pick(3) ? kHead[pick(6)] : Vec2{unit() - 0.5f, unit() - 0.5f};
        const int v = addQuiet(w, vx, vy, vz, head);
        static const float kSizes[] = {0.8f, 1.0f, 1.25f};
        w.creatures[v].bodySize = kSizes[pick(3)];
        auto place = [&](float& x, float& y, float& z) {
            x = vx + offset();
            y = vy + offset();
            z = std::clamp(vz + offset(), 0.0f, D);
            if (tor) { x = OceanWorld::wrapCoord(x, W); y = OceanWorld::wrapCoord(y, H); }
            else { x = std::clamp(x, 0.0f, W - 0.25f); y = std::clamp(y, 0.0f, H - 0.25f); }
        };
        const int nFish = pick(4) ? pick(26) : 0, nFood = pick(5) ? pick(64) : 0;
        static const float kAges[] = {0.0f, 10.0f, 37.5f, 90.0f};
        for (int j = 0; j < nFish; ++j) {
            float x, y, z;
            place(x, y, z);
            const int k = addQuiet(w, x, y, z, kHead[pick(6)], kAges[pick(4)], 5.0f + 10.0f * (float)pick(8));
            w.creatures[k].bodySize = kSizes[pick(3)];
        }
        static const float kFoodSizes[] = {1.0f, 1.0f, 1.0f, 0.5f, 1.2f, 2.0f};
        for (int j = 0; j < nFood; ++j) {
            float x, y, z;
            place(x, y, z);
            addFood(w, x, y, z, kFoodSizes[pick(6)]);
        }
        // the same lattice point twice now and then (equal distances, same cell)
        if (nFood > 2 && pick(2)) {
            const OceanFood dup = w.food[pick(nFood)];
            w.food.push_back(dup);
        }
        nonEmptyFood += nFood > 0;
        nonEmptyFish += nFish > 0;
        char name[160];
        std::snprintf(name, sizeof name, "scene %d (%s, topo %d, gate %d, %s, %d fish, %d food)", sc, tor ? "toroidal" : "bounded",
                      topo, (int)gate, m.name, nFish, nFood);
        stepAndCompare(t, name, w, &compared);
        ++scenes;
    }
    t.expect(nonEmptyFood > nScenes / 2 && nonEmptyFish > nScenes / 2, "too few populated scenes");
    t.note("%ld scenes, %ld inputs compared bit for bit with the scans' definition", scenes, compared);
}

}  // namespace ot

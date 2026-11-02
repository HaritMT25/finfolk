// ocean_eye_exp.cpp — the eye-only experiment (eye build): can fish live on the
// compound eye alone? One seeded run of one sense arm, with the ecology and the
// wiring logged every K steps to a CSV, and at the end a frozen-genome
// behavioural test; or --bench: the four sense arms timed interleaved on one
// snapshot (the cost question).
//
// Arms (OceanConfig eye / eyeOnly; every other setting from --cfg, identical):
//   A  labeled senses, eye off      (eye 0, eyeOnly 0)
//   B  labeled senses + eye         (eye 1, eyeOnly 0)
//   C  eye only                     (eye 1, eyeOnly 1)
//   D  blind                        (eye 0, eyeOnly 1)
// A digit after the letter sets OceanConfig::steerFrame for that arm (C1 = eye
// only, STEER_X / STEER_Y in the fish's own frame; A0 = labels, world frame);
// without one the cfg's steerFrame (default 0) is used. The eye's encoding
// (eyeCode, incl. the cloaks 8 = the eye ignores fish, 16 = it ignores food)
// comes from the cfg; --label NAME writes NAME in the arm column instead of
// the arm string (e.g. C1nf for C1 with eyeCode 8).
//
//   g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -DEVO_OCEAN_EYE -I src
//       tools/ocean_eye_exp.cpp -o ocean_eye_exp
//   ./ocean_eye_exp --arm C --seed 1 --steps 100000 --every 10000 --cfg '{...}' --out run_C_s1 [--behav]
//       [--dump-wiring PATH [--wiring-every K]] [--label NAME]
//   ./ocean_eye_exp --bench --evolve 30000 --evolve-arm B --cfg '{...}' --reps 7 --warm 20 --steps 200
//
// Outputs: PREFIX.csv (one row per interval), PREFIX_behav.csv (with --behav),
// PATH (with --dump-wiring; see "the per-fish wiring dump" below). Neither the
// behavioural test nor the dump changes the run: both read the nets, and their
// random genomes come from private rng streams (the world's rng is saved and
// restored), so the CSV is the same with or without them.
//
// Wiring (topology only): "eye -> move" = some EYE_* input reaches a movement
// action (STEER_X/Y/Z, MOVE_FORWARD, SPEED_ADJUST) directly / through any
// chain of hidden neurons. Each interval also scores a random-genome baseline:
// for every live fish a random genome of the SAME length (its own rng stream,
// the world's rng is saved and restored, so the run is unchanged).
//
// Clustering (the CSV's last four columns, at each interval's end; read-only):
//   nn_mean    mean 3-D distance from each live fish to its nearest other fish
//   nn_null    the same with every fish moved to a uniformly random x, y (its
//              depth kept, so depth layering alone is not counted as grouping;
//              a private rng stream)
//   near_frac  fraction of fish with another fish within interactRadius (the
//              pairing range); near_null the same for the null positions
// nn_mean / nn_null < 1 and near_frac / near_null > 1: the fish are closer to
// each other than chance places them.
//
// Behavioural test (--behav, at the end): every live fish's genome, frozen
// (fresh network state), alone in a quiet eye-only world (no labels: the fish
// can only SEE; still water: no current, no E1 flow, no food lifetime), level
// at mid-depth, for 8 headings (vendored cosf / sinf) x {nothing, one food item
// 50 away in each of the 6 sectors, one predator 60 away in each sector}; the
// scene is held fixed for 3 steps (so sensor -> hidden -> action paths act) and
// the 3rd step's actions are read. The same for a random genome of the same
// length in the same body. Indices (action units, + = adaptive):
//   food_h   lateral steer toward food right minus left (body frame)
//   food_v   STEER_Z toward food: food below minus food above
//   food_spd SPEED_ADJUST with food ahead minus with nothing
//   pred_h   lateral steer away from a predator (left minus right)
//   pred_v   STEER_Z away: predator above minus below
//   pred_spd SPEED_ADJUST with a predator (mean of the 6 sectors) minus nothing
//   react_food / react_pred  mean L1 change of (STEER_X, STEER_Y, STEER_Z,
//            SPEED_ADJUST) vs nothing (does seeing anything change behaviour?)
//   fish_h / fish_v / fish_spd / react_fish  the same for a conspecific 50
//            away (a copy of the fish's body with no wiring, put back each
//            step): toward it right minus left, below minus above, ahead
//            minus nothing (appended columns; the food / predator indices are
//            unchanged by them: every scene starts from the same state and rng)
//   base_abs  |lateral steer with nothing in view| (per fish, mean over the 8
//            headings of the absolute value): a turning bias, or any steady
//            sideways push, in empty space; base_x the signed mean (a steady
//            world-frame steer has base_x ~ 0 — its body-frame part changes sign
//            around the headings — and base_abs > 0)
//   food_r / food_l  each side alone vs nothing: lateral steer with food on the
//            right minus nothing / nothing minus with food on the left (+ =
//            toward it; food_h = food_r + food_l); fish_r / fish_l likewise for
//            the conspecific
//   frac_food_both  fraction of fish with food_r > 0.05 AND food_l > 0.05 (turn
//            toward food on either side); frac_food_one exactly one side;
//            frac_one_bias one side, the other side served by a turning bias
//            (base_x < -0.05 for a right-side responder, > 0.05 for a left-side
//            one); frac_fish_both as frac_food_both for the conspecific
//   (appended after frac_fish_h; the earlier columns are unchanged)
// The scenes use the full eye: the cloak bits (eyeCode 8 / 16) are cleared for
// the test, so a food-cloaked population's genomes are shown food they never
// saw (does the steering they evolved on what they did see carry over?).
//
// Wiring dump (--dump-wiring PATH): see "the per-fish wiring dump" below.
// Summary of a directory of runs (dumps + behavioural tests + CSVs):
//   python3 tools/ocean_wiring_summary.py DIR [--course]
// per run the final classes, the dominant class / feature / lineage, the
// per-side behaviour, when the dominant class reached 25 / 50 % of the fish;
// with --course the left / right / both wire fractions at every snapshot.
//
// The ALIFE 2027 instruments (experiments/alife2027/v2/, tools/alife2027/;
// all opt-in: without these flags the run, its CSV and its stdout are what
// they were; tools/ocean_eye_exp_support.hpp says what each one reads):
//   --eye-code N / --label-frame N   arm settings installed after the common
//            initialization, like --arm's (so every arm of a seed starts from
//            the same world); --label-frame needs an engine with labelFrame
//   --resolved PATH     the configuration used for initialization and the
//            effective one after the arm, every field by name (+ float bits)
//   --manifest PATH     what this process ran: argv, seed, arm, world, build
//            capabilities (NUM_SENSES ...), both configs, the outcome
//   --fp PATH [--fp-every K] [--fp-dense]   fingerprints at step 0 (after the
//            arm), every K (default --every) and the last step; --fp-dense
//            folds EVERY step's fingerprint into a chain (printed at the same
//            steps) — the verification mode; sparse observes only the printed
//            steps
//   --diag PATH         per-step accumulators, a row at 0, every --every, last
//   --encounters PATH [--encounters-until N] [--encounters-every K]   pairs
//            within the interaction radius, the mating funnel, interactions,
//            pairings, encounter durations (rows every K, through N)
//   --branches SPEC --branch-at S1,S2 --branch-out PATH [--branch-steps K]
//            [--branch-fp-every K] [--branch-early K] [--branch-order forward|reverse]
//            the common-history suite: right after step S, each continuation of
//            SPEC ("name:key=v,...;name2:;...") runs K steps on a copy of the
//            world and the rng; the parent is checked unchanged and, where the
//            run passes S + K, every sham (no change) continuation is checked
//            against the uninterrupted run
//   --behav-at S1,S2    the behavioural test at those steps too (PREFIX_behav_S.csv)
//   --wiring-no-paths   the final wiring snapshot without its per-path rows
// Exit status: 0 ok, 2 arguments, 3 an output could not be written, 4 config
// refused, 5 non-finite state observed, 6 an instrument check failed (sham
// identity, parent restoration, the food identity / expiry replay).
#include <algorithm>
#include <chrono>
#include <cinttypes>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <vector>
#include "ocean_fingerprint.hpp"   // ofp::initWorld: the page's config path
#include "ocean_eye_exp_support.hpp"   // the ALIFE 2027 instruments (alx::)

#ifndef EVO_OCEAN_EYE
#error "ocean_eye_exp needs the eye build: -DEVO_OCEAN_EYE"
#endif

namespace {

using clk = std::chrono::steady_clock;
constexpr float kDt = 0.016f;

struct ArmDef { char name; int eye, eyeOnly; };
constexpr ArmDef kArms[] = {{'A', 0, 0}, {'B', 1, 0}, {'C', 1, 1}, {'D', 0, 1}};
const ArmDef* findArm(char c) {
    for (const ArmDef& a : kArms) if (a.name == c) return &a;
    return nullptr;
}

constexpr int kMoveActs[] = {STEER_X, STEER_Y, STEER_Z, MOVE_FORWARD, SPEED_ADJUST};
constexpr std::uint32_t kMoveMask = (1u << STEER_X) | (1u << STEER_Y) | (1u << STEER_Z) |
                                    (1u << MOVE_FORWARD) | (1u << SPEED_ADJUST);

// Actions reached from any source in `srcs` (a predicate on the source index):
// direct wires, and any path through hidden neurons. Bitmasks over actions.
template <class Pred>
void reachFrom(const NeuralNet& nn, Pred srcs, std::uint32_t& direct, std::uint32_t& any) {
    bool hid[MAX_INTERNAL_NEURONS] = {};
    direct = any = 0;
    for (const auto& fc : nn.flat) {
        const int s = fc.src(), k = fc.sink();
        if (s < NUM_SENSES && srcs(s) && k < NUM_ACTIONS) direct |= 1u << k;
    }
    for (bool changed = true; changed;) {
        changed = false;
        for (const auto& fc : nn.flat) {
            const int s = fc.src(), k = fc.sink();
            const bool on = (s < NUM_SENSES) ? srcs(s) : hid[s - NUM_SENSES];
            if (!on) continue;
            if (k < NUM_ACTIONS) any |= 1u << k;
            else if (!hid[k - NUM_ACTIONS]) { hid[k - NUM_ACTIONS] = true; changed = true; }
        }
    }
}

struct Wiring {
    double fish = 0;
    double eyeAny = 0, eyeDirect = 0, eyeConns = 0, eyeAbsW = 0;   // eye -> move
    double eyeShareNum = 0, sensorConns = 0;                        // eye share of sensor conns
    double eyeVertDirect = 0;   // EYE_UP/DOWN_* -> STEER_Z direct (vertical use)
    double eyeLRDirect = 0;     // EYE_LEFT/RIGHT_* -> STEER_X direct (horizontal use)
    double foodMatched = 0;     // NEAREST_FOOD_DX->STEER_X | DY->STEER_Y | DZ->STEER_Z, w > 0
    double predMove = 0;        // PREDATOR_* -> move, any path
    double labMove = 0;         // any labeled sense -> move, any path
    double genomeLen = 0;
    void add(const NeuralNet& nn, std::size_t glen) {
        fish += 1;
        genomeLen += (double)glen;
        std::uint32_t d, a;
        reachFrom(nn, [](int s) { return ocean::isEyeSense(s); }, d, a);
        eyeAny += (a & kMoveMask) != 0;
        eyeDirect += (d & kMoveMask) != 0;
        bool matched = false, vert = false, lr = false;
        for (const auto& fc : nn.flat) {
            const int s = fc.src(), k = fc.sink();
            if (s >= NUM_SENSES) continue;
            sensorConns += 1;
            const bool eye = ocean::isEyeSense(s);
            eyeShareNum += eye;
            if (eye && k < NUM_ACTIONS && ((kMoveMask >> k) & 1u)) {
                eyeConns += 1;
                eyeAbsW += std::abs(fc.w());
            }
            if (k == STEER_Z && s >= EYE_UP_PROX && s <= EYE_DOWN_CON) vert = true;
            if (k == STEER_X && s >= EYE_LEFT_PROX && s <= EYE_RIGHT_CON) lr = true;
            if (fc.weight > 0 && ((s == NEAREST_FOOD_DX && k == STEER_X) || (s == NEAREST_FOOD_DY && k == STEER_Y) ||
                                  (s == NEAREST_FOOD_DZ && k == STEER_Z)))
                matched = true;
        }
        eyeVertDirect += vert;
        eyeLRDirect += lr;
        foodMatched += matched;
        reachFrom(nn, [](int s) { return s == PREDATOR_FWD || s == PREDATOR_LR || s == PREDATOR_PROX; }, d, a);
        predMove += (a & kMoveMask) != 0;
        reachFrom(nn, [](int s) { return ocean::isLabeledSense(s); }, d, a);
        labMove += (a & kMoveMask) != 0;
    }
};

// A random genome of length len from the private stream `r` (the global rng is
// what Gene::makeRandom draws from: swap it in and out).
Genome randomGenomeOfLength(RandomGen& r, std::size_t len) {
    const RandomGen keep = rng;
    rng = r;
    Genome g;
    g.reserve(len);
    for (std::size_t i = 0; i < len; ++i) g.push_back(Gene::makeRandom());
    r = rng;
    rng = keep;
    return g;
}

void scoreWiring(const OceanWorld& w, RandomGen& baseRng, Wiring& evo, Wiring& rnd) {
    for (const Fish& f : w.creatures) {
        if (!f.alive) continue;
        evo.add(f.nnet, f.genome.size());
        const Genome g = randomGenomeOfLength(baseRng, f.genome.size());
        NeuralNet nn;
        buildNeuralNet(g, nn);
        rnd.add(nn, g.size());
    }
}

// ---- clustering (read-only; the CSV's last columns, see the header) ---------------
// Mean nearest-other distance and the fraction with another point within r, over
// the points (x, y, z) (toroidal: x / y wrap). O(n^2), once per interval.
void nnStats(const std::vector<float>& x, const std::vector<float>& y, const std::vector<float>& z, double W, double H,
             bool toroidal, double r, double& nnMean, double& nearFrac) {
    const std::size_t n = x.size();
    nnMean = nearFrac = 0.0;
    if (n < 2) return;
    double sum = 0.0;
    long near = 0;
    for (std::size_t i = 0; i < n; ++i) {
        double best = 1e300;
        for (std::size_t j = 0; j < n; ++j) {
            if (j == i) continue;
            double dx = (double)x[j] - x[i], dy = (double)y[j] - y[i];
            if (toroidal) {
                if (dx > 0.5 * W) dx -= W; else if (dx < -0.5 * W) dx += W;
                if (dy > 0.5 * H) dy -= H; else if (dy < -0.5 * H) dy += H;
            }
            const double dz = (double)z[j] - z[i];
            best = std::min(best, dx * dx + dy * dy + dz * dz);
        }
        sum += std::sqrt(best);
        near += best <= r * r;
    }
    nnMean = sum / (double)n;
    nearFrac = (double)near / (double)n;
}

struct Clustering { double nnMean = 0, nnNull = 0, nearFrac = 0, nearNull = 0; };

// The live fish, and the null: the same fish at uniformly random x, y (depths
// kept), from the private stream r.
Clustering clusteringOf(const OceanWorld& w, RandomGen& r) {
    std::vector<float> x, y, z, xr, yr;
    for (const Fish& f : w.creatures) {
        if (!f.alive) continue;
        x.push_back(f.pos.x); y.push_back(f.pos.y); z.push_back(f.depth);
        xr.push_back(r.unit() * (float)w.width); yr.push_back(r.unit() * (float)w.height);
    }
    Clustering c;
    const double W = (double)w.width, H = (double)w.height, ir = (double)w.cfg.interactRadius;
    nnStats(x, y, z, W, H, w.cfg.toroidal, ir, c.nnMean, c.nearFrac);
    nnStats(xr, yr, z, W, H, w.cfg.toroidal, ir, c.nnNull, c.nearNull);
    return c;
}

// ---- the behavioural test ------------------------------------------------------
struct Behav {
    double n = 0;
    double food_h = 0, food_v = 0, food_spd = 0, pred_h = 0, pred_v = 0, pred_spd = 0;
    double react_food = 0, react_pred = 0;
    double pos_food_h = 0, pos_food_v = 0, pos_pred_spd = 0, pos_pred_v = 0;   // fraction of fish with index > 0.05
    double fish_h = 0, fish_v = 0, fish_spd = 0, react_fish = 0, pos_fish_h = 0;
    // each side alone, and the empty-space turning bias (see the header)
    double base_abs = 0, base_x = 0, food_r = 0, food_l = 0, fish_r = 0, fish_l = 0;
    double pos_food_both = 0, pos_food_one = 0, pos_one_bias = 0, pos_fish_both = 0;
};
// behaveOne's indices: 8 food / predator, 4 conspecific, then 12 the lateral
// steer with nothing in view, 13 / 14 food right / left vs nothing, 15 / 16 the
// conspecific right / left vs nothing (+ = toward it), 17 |the lateral steer
// with nothing in view| (each heading's absolute value: base_abs)
constexpr int kBehavIdx = 18;

// What one fish does (its 3rd-step actions) in a held scene. kind: 0 nothing,
// 1 food, 2 predator, 3 a conspecific; sector 0..5 = ahead, behind, left,
// right, up, down.
struct Probe {
    const OceanWorld& tmpl;
    RandomGen sceneRng;
    // sensOut (optional): the 3rd step's NUM_SENSES inputs too.
    void act(const Fish& base, Vec2 heading, int kind, int sector, float out[NUM_ACTIONS], float* sensOut = nullptr) {
        OceanWorld w = tmpl;
        const Vec2 P = {0.5f * (float)w.width, 0.5f * (float)w.height};
        const float Z = 0.5f * w.D;
        const Vec2 rht = {-heading.y, heading.x};
        Vec2 off = {0, 0};
        float dz = 0;
        const float dist = (kind == 2) ? 60.0f : 50.0f;
        Fish other;   // kind 3: the fish's own body with no wiring (stepped after it: seen where put)
        if (kind == 3) {
            other = base;
            other.genome.clear();
            buildNeuralNet(other.genome, other.nnet);
        }
        switch (sector) {
            case 0: off = {heading.x * dist, heading.y * dist}; break;
            case 1: off = {-heading.x * dist, -heading.y * dist}; break;
            case 2: off = {-rht.x * dist, -rht.y * dist}; break;
            case 3: off = {rht.x * dist, rht.y * dist}; break;
            case 4: dz = -dist; break;
            case 5: dz = dist; break;
        }
        w.creatures.clear();
        w.creatures.push_back(base);
        w.food.clear();
        w.predators.clear();
        const RandomGen keep = rng;
        for (int s = 0; s < 3; ++s) {
            w.creatures.resize(1);
            Fish& f = w.creatures[0];
            f.pos = P; f.vel = heading; f.lastMoveDir = heading; f.depth = Z; f.vz = 0.0f;
            f.foodReserves = 25.0f;
            if (kind == 3) {
                Fish o = other;
                o.pos = {P.x + off.x, P.y + off.y};
                o.vel = heading; o.lastMoveDir = heading; o.depth = Z + dz; o.vz = 0.0f;
                o.foodReserves = 25.0f;
                for (int b = 0; b < Fish::BODY_LEN; ++b) o.body[b] = o.pos;
                w.creatures.push_back(o);
            }
            if (kind == 1) {
                w.food.clear();
                OceanFood fd;
                fd.pos = {P.x + off.x, P.y + off.y};
                fd.depth = Z + dz;
                fd.eyeCon = ocean::eyeContrast(ocean::kEyeFoodBright, fd.depth);
                w.food.push_back(fd);
            } else if (kind == 2) {
                w.predators.clear();
                OceanPredator p;
                p.pos = {P.x + off.x, P.y + off.y};
                p.depth = Z + dz;
                p.vel = {-heading.x, -heading.y};
                p.digestTimer = 1e9f;
                w.predators.push_back(p);
            }
            rng = sceneRng;   // the same RANDOM_SENSOR / MOVE_RANDOM draws in every scene
            w.update(kDt);
        }
        rng = keep;
        std::memcpy(out, w.creatures[0].lastActions, sizeof(float) * NUM_ACTIONS);
        if (sensOut) std::memcpy(sensOut, w.creatures[0].lastSensors, sizeof(float) * NUM_SENSES);
    }
};

// The behavioural test's world: quiet, eye-only, the full eye (the cloaks
// cleared), still water, with the run's own motion settings; and the rng its
// scenes draw from. The world's rng is left as it was.
OceanWorld behavTemplate(const OceanWorld& w, unsigned seed, RandomGen& sceneRng) {
    OceanWorld tmpl;
    tmpl.cfg = w.cfg;
    tmpl.cfg.targetFood = 0; tmpl.cfg.foodSpawnBase = 0; tmpl.cfg.foodSpawnAmp = 0;
    tmpl.cfg.minPopulation = 0; tmpl.cfg.maxPopulation = 0;
    tmpl.cfg.predatorCount = 0; tmpl.cfg.predatorEconomy = false; tmpl.cfg.predatorMinPopulation = 0;
    tmpl.cfg.metabolicRate = 0; tmpl.cfg.moveCost = 0; tmpl.cfg.geneCost = 0; tmpl.cfg.maxAge = 1e9f;
    tmpl.cfg.currentStrength = 0; tmpl.cfg.foodPatches = 0; tmpl.cfg.foodDrift = false;
    tmpl.cfg.captureActivations = true;
    tmpl.ocfg = w.ocfg;
    // Still water: no food lifetime (a held item must not age out before it is
    // seen, whatever the run's foodLife) and no E1 flow (waves / a deep current
    // would keep the CURRENT_* inputs live although currentStrength is 0).
    tmpl.ocfg.foodLife = 0.0f;
    tmpl.ocfg.waveSpeed = 0.0f;
    tmpl.ocfg.deepCurrent = false;
    tmpl.ocfg.eye = 1;
    tmpl.ocfg.eyeOnly = 1;
    tmpl.ocfg.eyeCode &= ~(kEyeCodeNoFish | kEyeCodeNoFood);   // the full eye (see the header)
    const RandomGen keep = rng;
    rng.seed(seed * 7919u + 17u);
    tmpl.init(w.width, w.height, w.D, 0);
    sceneRng = rng;
    rng = keep;
    return tmpl;
}

// One fish's indices, averaged over 8 headings. lat = steer along the body's
// right axis (world-frame STEER_X/Y projected; triangular motion or steerFrame 1:
// STEER_X is already that push).
void behaveOne(Probe& pr, const Fish& base, bool bodyFrame, double idx[kBehavIdx]) {
    for (int k = 0; k < kBehavIdx; ++k) idx[k] = 0;
    constexpr int H = 8;
    for (int h = 0; h < H; ++h) {
        const float a = 6.2831853f * (float)h / H + 0.3f;
        const Vec2 hd = {evomath::cosf(a), evomath::sinf(a)};   // vendored (musl), not the host libm
        const Vec2 rht = {-hd.y, hd.x};
        auto lat = [&](const float* A) { return bodyFrame ? A[STEER_X] : A[STEER_X] * rht.x + A[STEER_Y] * rht.y; };
        auto l1 = [&](const float* A, const float* B) {
            return std::abs(A[STEER_X] - B[STEER_X]) + std::abs(A[STEER_Y] - B[STEER_Y]) +
                   std::abs(A[STEER_Z] - B[STEER_Z]) + std::abs(A[SPEED_ADJUST] - B[SPEED_ADJUST]);
        };
        float none[NUM_ACTIONS], fd[6][NUM_ACTIONS], pd[6][NUM_ACTIONS], cd[6][NUM_ACTIONS];
        pr.act(base, hd, 0, 0, none);
        for (int s = 0; s < 6; ++s) {
            pr.act(base, hd, 1, s, fd[s]);
            pr.act(base, hd, 2, s, pd[s]);
            pr.act(base, hd, 3, s, cd[s]);
        }
        idx[0] += lat(fd[3]) - lat(fd[2]);
        idx[1] += fd[5][STEER_Z] - fd[4][STEER_Z];
        idx[2] += fd[0][SPEED_ADJUST] - none[SPEED_ADJUST];
        idx[3] += lat(pd[2]) - lat(pd[3]);
        idx[4] += pd[4][STEER_Z] - pd[5][STEER_Z];
        idx[8] += lat(cd[3]) - lat(cd[2]);
        idx[9] += cd[5][STEER_Z] - cd[4][STEER_Z];
        idx[10] += cd[0][SPEED_ADJUST] - none[SPEED_ADJUST];
        idx[12] += lat(none);
        idx[17] += std::abs(lat(none));
        idx[13] += lat(fd[3]) - lat(none);
        idx[14] += lat(none) - lat(fd[2]);
        idx[15] += lat(cd[3]) - lat(none);
        idx[16] += lat(none) - lat(cd[2]);
        double ps = 0, rf = 0, rp = 0, rc = 0;
        for (int s = 0; s < 6; ++s) {
            ps += pd[s][SPEED_ADJUST] - none[SPEED_ADJUST];
            rf += l1(fd[s], none);
            rp += l1(pd[s], none);
            rc += l1(cd[s], none);
        }
        idx[5] += ps / 6; idx[6] += rf / 6; idx[7] += rp / 6; idx[11] += rc / 6;
    }
    for (int k = 0; k < kBehavIdx; ++k) idx[k] /= H;
}

void addBehav(Behav& b, const double idx[kBehavIdx]) {
    b.n += 1;
    b.food_h += idx[0]; b.food_v += idx[1]; b.food_spd += idx[2];
    b.pred_h += idx[3]; b.pred_v += idx[4]; b.pred_spd += idx[5];
    b.react_food += idx[6]; b.react_pred += idx[7];
    b.pos_food_h += idx[0] > 0.05; b.pos_food_v += idx[1] > 0.05;
    b.pos_pred_spd += idx[5] > 0.05; b.pos_pred_v += idx[4] > 0.05;
    b.fish_h += idx[8]; b.fish_v += idx[9]; b.fish_spd += idx[10]; b.react_fish += idx[11];
    b.pos_fish_h += idx[8] > 0.05;
    b.base_abs += idx[17]; b.base_x += idx[12];   // mean |lat| per heading (|mean lat| let headings cancel)
    b.food_r += idx[13]; b.food_l += idx[14]; b.fish_r += idx[15]; b.fish_l += idx[16];
    const bool r = idx[13] > 0.05, l = idx[14] > 0.05;
    b.pos_food_both += r && l;
    b.pos_food_one += r != l;
    b.pos_one_bias += (r && !l && idx[12] < -0.05) || (l && !r && idx[12] > 0.05);
    b.pos_fish_both += idx[15] > 0.05 && idx[16] > 0.05;
}

void writeBehavRow(std::FILE* f, const char* arm, unsigned seed, const char* who, const Behav& b) {
    const double n = b.n > 0 ? b.n : 1;
    std::fprintf(f, "%s,%u,%s,%.0f,%.5f,%.5f,%.5f,%.5f,%.5f,%.5f,%.5f,%.5f,%.4f,%.4f,%.4f,%.4f,%.5f,%.5f,%.5f,%.5f,%.4f",
                 arm, seed, who, b.n,
                 b.food_h / n, b.food_v / n, b.food_spd / n, b.pred_h / n, b.pred_v / n, b.pred_spd / n,
                 b.react_food / n, b.react_pred / n, b.pos_food_h / n, b.pos_food_v / n, b.pos_pred_v / n,
                 b.pos_pred_spd / n, b.fish_h / n, b.fish_v / n, b.fish_spd / n, b.react_fish / n, b.pos_fish_h / n);
    std::fprintf(f, ",%.5f,%.5f,%.5f,%.5f,%.5f,%.5f,%.4f,%.4f,%.4f,%.4f\n", b.base_abs / n, b.base_x / n,
                 b.food_r / n, b.food_l / n, b.fish_r / n, b.fish_l / n, b.pos_food_both / n, b.pos_food_one / n,
                 b.pos_one_bias / n, b.pos_fish_both / n);
}

bool behaviouralTest(const OceanWorld& w, const char* arm, unsigned seed, const std::string& path) {
    // A quiet eye-only world with the run's own motion settings. (Every scene
    // saves and restores the world's rng itself, and the random genomes have
    // their own stream: nothing below reads the world's rng.)
    RandomGen sceneRng;
    const OceanWorld tmpl = behavTemplate(w, seed, sceneRng);
    Probe pr{tmpl, sceneRng};
    RandomGen genRng;
    genRng.seed(seed * 104729u + 3u);
    Behav evo, rnd;
    double idx[kBehavIdx];
    const bool tri = w.cfg.triangularMotion || w.ocfg.steerFrame == 1;
    for (const Fish& f0 : w.creatures) {
        if (!f0.alive) continue;
        Fish f = f0;
        buildNeuralNet(f.genome, f.nnet);   // frozen genome, fresh network state
        behaveOne(pr, f, tri, idx);
        addBehav(evo, idx);
        f.genome = randomGenomeOfLength(genRng, f0.genome.size());
        buildNeuralNet(f.genome, f.nnet);
        behaveOne(pr, f, tri, idx);
        addBehav(rnd, idx);
    }
    std::FILE* out = std::fopen(path.c_str(), "w");
    if (!out) { std::fprintf(stderr, "cannot write %s\n", path.c_str()); return false; }
    std::fprintf(out, "arm,seed,genomes,n,food_h,food_v,food_spd,pred_h,pred_v,pred_spd,react_food,react_pred,"
                      "frac_food_h,frac_food_v,frac_pred_v,frac_pred_spd,fish_h,fish_v,fish_spd,react_fish,frac_fish_h,"
                      "base_abs,base_x,food_r,food_l,fish_r,fish_l,frac_food_both,frac_food_one,frac_one_bias,"
                      "frac_fish_both\n");
    writeBehavRow(out, arm, seed, "evolved", evo);
    writeBehavRow(out, arm, seed, "random", rnd);
    const bool bad = std::ferror(out) != 0;
    if (std::fclose(out) != 0 || bad) { std::fprintf(stderr, "error writing %s\n", path.c_str()); return false; }
    return true;
}

// ---- the per-fish wiring dump (--dump-wiring PATH) ----------------------------
// For every live fish, every path from an EYE_* input to STEER_X, STEER_Z or
// SPEED_ADJUST: a direct wire, or a chain through up to kMaxHops hidden
// neurons (simple paths: no neuron twice; each hop is one step of delay; a
// chain cut at kMaxHops is counted as truncated). A path's gain is the product
// of its weights (the linear gain near 0, tanh' = 1); its sign the product's.
//
// Per fish, G[sector][feature][action] = the summed gain of the paths from
// that eye input to that action, and the HORIZONTAL class from the lateral
// sectors to STEER_X (steerFrame 1: + = a push to the fish's right):
//   none          no path from EYE_LEFT_* / EYE_RIGHT_* to STEER_X
//   left_only     paths from the left sector only;  right_only likewise
//   bi_toward     both sides, gL < 0 < gR: turns toward what it sees on either
//                 side (food: every feature is > 0 for food, so this is "toward
//                 food" whatever the channel; CON wired so also turns AWAY from
//                 predators, whose CON is < 0)
//   bi_away       both sides, gL > 0 > gR;   bi_same  both sides, same sign
// where gS = Σ_input G[input][STEER_X] · x_S[input]: the turn food on side S
// would cause, with x_S = the 18 eye inputs one food item 50 away at
// mid-depth on side S really produces in this run's encoding (eyeCode; read
// from the engine in a held scene of the behavioural test's quiet world, the
// cloaks cleared as there: what the fish would see of food). eyeCode 0 lights
// only side S's sector (PROX 1 − 50/R, SIZE 4/54, CON 1 − L(D/2)); faded
// contrast (bit 1) makes CON = PROX · (1 − L), summed sectors (4) squash each
// feature to x / (1 + |x|), opponent pairs (2) put the food in both lateral
// slots (left + right, right − left) — so the same wires can turn toward
// food in one encoding and away in another (the classes used to take the
// code-0 values whatever the run's code). hc_PROX / hc_SIZE / hc_CON: the
// same class on one feature alone (that feature's inputs only). hdom: the
// feature with the largest summed |G| to STEER_X over both lateral sectors
// (raw weights); hdom_food: weighted by the feature's food value (vf: its
// mean |x| on the side that sees the food). The VERTICAL class likewise from
// up (−) / down (+) to STEER_Z (+ = deeper), with food above / below.
// left_only / right_only are topology (which sector's inputs have a path):
// with opponent pairs a right_only fish steers both ways (gL, gR say how).
//
// File (CSV-like, the first field says the row kind):
//   # comment lines (run, cfg, the column lists)
//   S,step,who,n,<class counts>,...   per snapshot: evolved fish, and random
//                                     genomes of the same lengths (private rng)
//   F,step,idx,id,lineage,...         per live fish per snapshot
//   P,step,idx,id,sensor,...          per path, the final snapshot only
// Snapshots: at the end, and with --wiring-every K also at step 0 and every K steps.
constexpr int kMaxHops = 4;
constexpr long kMaxPathsPerFish = 20000;
constexpr int kDumpActs[3] = {STEER_X, STEER_Z, SPEED_ADJUST};
const char* const kSectorNames[ocean::kEyeSectors] = {"ahead", "behind", "left", "right", "up", "down"};
const char* const kFeatNames[3] = {"PROX", "SIZE", "CON"};
const char* const kHClass[6] = {"none", "left_only", "right_only", "bi_toward", "bi_away", "bi_same"};
const char* const kVClass[6] = {"none", "up_only", "down_only", "bi_toward", "bi_away", "bi_same"};
int dumpActIndex(int a) { return a == STEER_X ? 0 : a == STEER_Z ? 1 : a == SPEED_ADJUST ? 2 : -1; }

struct EyePath {
    int sensor = 0, action = 0, hops = 0;
    int via[kMaxHops] = {};
    float w[kMaxHops + 1] = {};
    double gain = 0.0;
};

void eyePathsFrom(const NeuralNet& nn, int src, EyePath& cur, bool onPath[], std::vector<EyePath>& out,
                  long& truncated) {
    for (const auto& fc : nn.flat) {
        if (fc.src() != src) continue;
        const int k = fc.sink();
        cur.w[cur.hops] = fc.w();
        if (k < NUM_ACTIONS) {
            if (dumpActIndex(k) < 0) continue;
            if ((long)out.size() >= kMaxPathsPerFish) { ++truncated; continue; }
            EyePath p = cur;
            p.action = k;
            double g = 1.0;
            for (int i = 0; i <= p.hops; ++i) g *= (double)p.w[i];
            p.gain = g;
            out.push_back(p);
            continue;
        }
        const int h = k - NUM_ACTIONS;
        if (onPath[h]) continue;                          // a cycle: not a simple path
        if (cur.hops == kMaxHops) { ++truncated; continue; }
        onPath[h] = true;
        cur.via[cur.hops++] = h;
        eyePathsFrom(nn, NUM_SENSES + h, cur, onPath, out, truncated);
        --cur.hops;
        onPath[h] = false;
    }
}

void eyePaths(const NeuralNet& nn, std::vector<EyePath>& out, long& truncated) {
    out.clear();
    truncated = 0;
    for (int s = ocean::kEyeFirst; s < ocean::kEyeFirst + ocean::kEyeInputs; ++s) {
        EyePath cur;
        cur.sensor = s;
        bool onPath[MAX_INTERNAL_NEURONS] = {};
        eyePathsFrom(nn, s, cur, onPath, out, truncated);
    }
}

struct FishWiring {
    double G[ocean::kEyeSectors][3][3] = {};   // [sector][feature][dump action]
    bool any[ocean::kEyeSectors][3][3] = {};
    bool directLR = false, directUD = false;   // a direct EYE_LEFT/RIGHT -> STEER_X, EYE_UP/DOWN -> STEER_Z wire
    long paths = 0, truncated = 0, spdPaths = 0;
    int hclass = 0, vclass = 0, hdom = -1, hdomFood = -1, vdom = -1;
    int hcf[3] = {};                            // the horizontal class per feature
    double gL = 0, gR = 0, gU = 0, gD = 0;
};

// The eye inputs (index 3·sector + feature) one food item 50 units from a fish
// at mid-depth produces, in w's encoding: x[0] food on the left, x[1] on the
// right, x[2] above, x[3] below (heading +x; the behavioural test's quiet
// world, cloaks cleared). vf[f]: feature f's mean |input| over the two
// lateral scenes' own sectors. The world's rng is left as it was.
void foodSceneInputs(const OceanWorld& w, unsigned seed, double x[4][ocean::kEyeInputs], double vf[3]) {
    RandomGen sceneRng;
    const OceanWorld tmpl = behavTemplate(w, seed, sceneRng);
    Probe pr{tmpl, sceneRng};
    Fish viewer;   // no wiring: only its eye matters
    const RandomGen keep = rng;
    viewer.init({0.5f * (float)w.width, 0.5f * (float)w.height}, 0.5f * w.D);
    rng = keep;
    buildNeuralNet(viewer.genome, viewer.nnet);
    const int sectors[4] = {2, 3, 4, 5};   // Probe's: left, right, up, down
    float acts[NUM_ACTIONS], sens[NUM_SENSES];
    for (int k = 0; k < 4; ++k) {
        pr.act(viewer, {1.0f, 0.0f}, 1, sectors[k], acts, sens);
        for (int i = 0; i < ocean::kEyeInputs; ++i) x[k][i] = (double)sens[ocean::kEyeFirst + i];
    }
    for (int f = 0; f < 3; ++f) vf[f] = 0.5 * (std::abs(x[0][3 * 2 + f]) + std::abs(x[1][3 * 3 + f]));
}

// The class of a sector pair (neg side, pos side) on dump action a, over the
// features in [f0, f1): gN / gP = the gains times the inputs food on the neg /
// pos side produces (xNeg, xPos: every sector's, see foodSceneInputs).
int pairClass(const FishWiring& fw, int sNeg, int sPos, int a, int f0, int f1, const double xNeg[],
              const double xPos[], double& gN, double& gP) {
    gN = gP = 0.0;
    bool n = false, p = false;
    for (int s = 0; s < ocean::kEyeSectors; ++s)
        for (int f = f0; f < f1; ++f) {
            gN += fw.G[s][f][a] * xNeg[3 * s + f];
            gP += fw.G[s][f][a] * xPos[3 * s + f];
        }
    for (int f = f0; f < f1; ++f) {
        n = n || fw.any[sNeg][f][a];
        p = p || fw.any[sPos][f][a];
    }
    if (!n && !p) return 0;
    if (n && !p) return 1;
    if (!n && p) return 2;
    if (gN < 0.0 && gP > 0.0) return 3;
    if (gN > 0.0 && gP < 0.0) return 4;
    return 5;
}

FishWiring wiringOf(const NeuralNet& nn, const double x[4][ocean::kEyeInputs], const double vf[3],
                    std::vector<EyePath>& paths) {
    FishWiring fw;
    eyePaths(nn, paths, fw.truncated);
    fw.paths = (long)paths.size();
    for (const EyePath& p : paths) {
        const int sec = (p.sensor - ocean::kEyeFirst) / 3, f = (p.sensor - ocean::kEyeFirst) % 3, a = dumpActIndex(p.action);
        fw.G[sec][f][a] += p.gain;
        fw.any[sec][f][a] = true;
        if (p.hops == 0 && a == 0 && (sec == 2 || sec == 3)) fw.directLR = true;
        if (p.hops == 0 && a == 1 && (sec == 4 || sec == 5)) fw.directUD = true;
        if (a == 2) ++fw.spdPaths;
    }
    double gn, gp;
    fw.hclass = pairClass(fw, 2, 3, 0, 0, 3, x[0], x[1], fw.gL, fw.gR);
    fw.vclass = pairClass(fw, 4, 5, 1, 0, 3, x[2], x[3], fw.gU, fw.gD);
    for (int f = 0; f < 3; ++f) fw.hcf[f] = pairClass(fw, 2, 3, 0, f, f + 1, x[0], x[1], gn, gp);
    double best = 0, bestFood = 0, bestV = 0;
    for (int f = 0; f < 3; ++f) {
        const double h = std::abs(fw.G[2][f][0]) + std::abs(fw.G[3][f][0]);
        const double z = std::abs(fw.G[4][f][1]) + std::abs(fw.G[5][f][1]);
        if (h > best) { best = h; fw.hdom = f; }
        if (h * vf[f] > bestFood) { bestFood = h * vf[f]; fw.hdomFood = f; }
        if (z > bestV) { bestV = z; fw.vdom = f; }
    }
    return fw;
}

struct WiringDump {
    std::FILE* f = nullptr;
    double x[4][ocean::kEyeInputs] = {};   // the eye inputs food 50 away gives, left / right / above / below
    double vf[3] = {};                      // PROX / SIZE / CON's food value (foodSceneInputs)
    RandomGen rndRng;        // the random genomes' own stream
    std::vector<EyePath> paths;

    bool open(const std::string& path, const OceanWorld& w, const char* arm, unsigned seed, const char* cfgJson) {
        f = std::fopen(path.c_str(), "w");
        if (!f) return false;
        foodSceneInputs(w, seed, x, vf);   // in this run's encoding (eyeCode)
        rndRng.seed(seed * 40503u + 29u);
        std::fprintf(f, "# ocean_eye_exp wiring dump: arm %s seed %u eye %d eyeOnly %d eyeCode %d steerFrame %d cfg %s\n",
                     arm, seed, w.ocfg.eye, w.ocfg.eyeOnly, w.ocfg.eyeCode, w.ocfg.steerFrame, cfgJson ? cfgJson : "{}");
        std::fprintf(f, "# food-weighting vf: PROX %.4f SIZE %.4f CON %.4f; paths to STEER_X / STEER_Z / SPEED_ADJUST, <= %d hidden hops\n",
                     vf[0], vf[1], vf[2], kMaxHops);
        const char* const scene[4] = {"left", "right", "above", "below"};
        for (int k = 0; k < 4; ++k) {   // the inputs the classes weight the gains by
            std::fprintf(f, "# food %s (eyeCode %d, cloaks cleared):", scene[k], w.ocfg.eyeCode & ~kEyeCodeCloaks);
            for (int s = 0; s < ocean::kEyeSectors; ++s)
                std::fprintf(f, " %s %.4f/%.4f/%.4f", kSectorNames[s], x[k][3 * s], x[k][3 * s + 1], x[k][3 * s + 2]);
            std::fputc('\n', f);
        }
        std::fprintf(f, "#S,step,who,n,h_none,h_left_only,h_right_only,h_bi_toward,h_bi_away,h_bi_same,"
                        "con_bi_toward,prox_bi_toward,size_bi_toward,hdom_PROX,hdom_SIZE,hdom_CON,direct_lr,"
                        "v_none,v_up_only,v_down_only,v_bi_toward,v_bi_away,v_bi_same,genome_len_mean\n");
        std::fprintf(f, "#F,step,idx,id,lineage,generation,genome_len,conns,eye_paths,truncated,hclass,hdom,hdom_food,"
                        "gL,gR,hc_PROX,hc_SIZE,hc_CON,L_PROX,L_SIZE,L_CON,R_PROX,R_SIZE,R_CON,direct_lr,vclass,vdom,gU,gD,"
                        "direct_ud,spd_paths\n");
        std::fprintf(f, "#P,step,idx,id,sensor,sector,feature,action,hops,via,weights,gain\n");
        return true;
    }

    struct Tally {
        long n = 0, h[6] = {}, v[6] = {}, conBi = 0, proxBi = 0, sizeBi = 0, dom[3] = {}, directLR = 0;
        double glen = 0;
        void add(const FishWiring& fw, std::size_t len) {
            ++n; ++h[fw.hclass]; ++v[fw.vclass];
            conBi += fw.hcf[2] == 3; proxBi += fw.hcf[0] == 3; sizeBi += fw.hcf[1] == 3;
            if (fw.hdom >= 0) ++dom[fw.hdom];
            directLR += fw.directLR;
            glen += (double)len;
        }
        void write(std::FILE* f, long step, const char* who) const {
            std::fprintf(f, "S,%ld,%s,%ld", step, who, n);
            for (long c : h) std::fprintf(f, ",%ld", c);
            std::fprintf(f, ",%ld,%ld,%ld,%ld,%ld,%ld,%ld", conBi, proxBi, sizeBi, dom[0], dom[1], dom[2], directLR);
            for (long c : v) std::fprintf(f, ",%ld", c);
            std::fprintf(f, ",%.2f\n", n ? glen / n : 0.0);
        }
    };

    void snapshot(const OceanWorld& w, long step, bool withPaths) {
        if (!f) return;
        Tally evo, rnd;
        long idx = 0;
        for (const Fish& c : w.creatures) {
            if (!c.alive) continue;
            const FishWiring fw = wiringOf(c.nnet, x, vf, paths);
            evo.add(fw, c.genome.size());
            std::fprintf(f, "F,%ld,%ld,%llu,%llu,%u,%zu,%zu,%ld,%ld,%s,%s,%s,%.5g,%.5g,%s,%s,%s", step, idx,
                         (unsigned long long)c.id, (unsigned long long)c.lineageId, (unsigned)c.generation,
                         c.genome.size(), c.nnet.flat.size(), fw.paths, fw.truncated, kHClass[fw.hclass],
                         fw.hdom >= 0 ? kFeatNames[fw.hdom] : "-", fw.hdomFood >= 0 ? kFeatNames[fw.hdomFood] : "-",
                         fw.gL, fw.gR, kHClass[fw.hcf[0]], kHClass[fw.hcf[1]], kHClass[fw.hcf[2]]);
            for (int sec = 2; sec <= 3; ++sec)
                for (int ft = 0; ft < 3; ++ft) std::fprintf(f, ",%.5g", fw.G[sec][ft][0]);
            std::fprintf(f, ",%d,%s,%s,%.5g,%.5g,%d,%ld\n", (int)fw.directLR, kVClass[fw.vclass],
                         fw.vdom >= 0 ? kFeatNames[fw.vdom] : "-", fw.gU, fw.gD, (int)fw.directUD, fw.spdPaths);
            if (withPaths)
                for (const EyePath& p : paths) {
                    const int sec = (p.sensor - ocean::kEyeFirst) / 3, ft = (p.sensor - ocean::kEyeFirst) % 3;
                    std::fprintf(f, "P,%ld,%ld,%llu,%s,%s,%s,%s,%d,", step, idx, (unsigned long long)c.id,
                                 ocean::kSensorNames[p.sensor], kSectorNames[sec], kFeatNames[ft],
                                 ocean::kActionNames[p.action], p.hops);
                    for (int i = 0; i < p.hops; ++i) std::fprintf(f, "%sh%d", i ? ">" : "", p.via[i]);
                    std::fputc(',', f);
                    for (int i = 0; i <= p.hops; ++i) std::fprintf(f, "%s%.4f", i ? "*" : "", (double)p.w[i]);
                    std::fprintf(f, ",%.6g\n", p.gain);
                }
            // the null: a random genome of the same length (private stream)
            const Genome g = randomGenomeOfLength(rndRng, c.genome.size());
            NeuralNet nn;
            buildNeuralNet(g, nn);
            std::vector<EyePath> rp;
            rnd.add(wiringOf(nn, x, vf, rp), g.size());
            ++idx;
        }
        evo.write(f, step, "evolved");
        rnd.write(f, step, "random");
        std::fflush(f);
    }
    // false: a write failed somewhere in the dump (the file is incomplete)
    bool close() {
        if (!f) return true;
        const bool bad = std::ferror(f) != 0;
        const bool ok = std::fclose(f) == 0 && !bad;
        f = nullptr;
        return ok;
    }
};

double median(std::vector<double> v) {
    if (v.empty()) return 0.0;
    std::sort(v.begin(), v.end());
    const std::size_t n = v.size();
    return (n % 2) ? v[n / 2] : 0.5 * (v[n / 2 - 1] + v[n / 2]);
}

}  // namespace

#ifndef OCEAN_EYE_EXP_NO_MAIN   // tests/ocean_tests.cpp (eye build) includes this file without it
namespace {

// "20000,100000" -> {20000, 100000}; false on anything else
bool parseStepList(const char* s, std::vector<long>& out) {
    out.clear();
    const char* p = s;
    while (*p) {
        char* end = nullptr;
        const long v = std::strtol(p, &end, 10);
        if (end == p || v < 0) return false;
        out.push_back(v);
        if (*end == ',') p = end + 1;
        else if (*end == '\0') p = end;
        else return false;
    }
    std::sort(out.begin(), out.end());
    return !out.empty() && std::adjacent_find(out.begin(), out.end()) == out.end();
}

bool closeChecked(std::FILE*& f, const std::string& path) {
    if (!f) return true;
    const bool bad = std::ferror(f) != 0;
    const bool ok = std::fclose(f) == 0 && !bad;
    f = nullptr;
    if (!ok) std::fprintf(stderr, "error writing %s\n", path.c_str());
    return ok;
}

std::string compilerId() {
#if defined(__clang__)
    return std::string("clang ") + __clang_version__;
#elif defined(__GNUC__)
    return std::string("gcc ") + __VERSION__;
#else
    return "unknown";
#endif
}

}  // namespace

int main(int argc, char** argv) {
    if (argc == 2 && !std::strcmp(argv[1], "--capabilities")) {   // the build's capabilities, for the build manifest
        std::printf("{\"NUM_SENSES\":%d,\"NUM_ACTIONS\":%d,\"eye_build\":%s,\"label_frame\":%s,\"fingerprint_format\":%d,"
                    "\"diag_format\":%d,\"branch_format\":%d,\"encounter_format\":%d,\"cplusplus\":%ld,\"compiler\":\"%s\"}\n",
                    (int)NUM_SENSES, (int)NUM_ACTIONS, kOceanHasEye ? "true" : "false",
                    alx::hasLabelFrame() ? "true" : "false", ofp::kFormatVersion, alx::kDiagFormat, alx::kBranchFormat,
                    alx::kEncounterFormat, (long)__cplusplus, alx::jsonEscape(compilerId()).c_str());
        return 0;
    }
    unsigned seed = 1;
    long steps = 100000, every = 10000, evolve = 30000;
    int W = 1920, H = 1080, pop = 300, reps = 7, warm = 20, bsteps = 200;
    double depth = 240.0;
    const char* cfgJson = nullptr;
    std::string out = "run", armArg = "A", evolveArm = "B", label, dumpPath;
    long wiringEvery = 0;
    bool behav = false, bench = false;
    // the ALIFE 2027 instruments (opt-in; see the header)
    int eyeCodeArg = -1, labelFrameArg = -1;
    std::string resolvedPath, manifestPath, fpPath, diagPath, encPath, branchSpecText, branchOut, branchOrder = "forward";
    long fpEvery = 0, encUntil = 30000, encEvery = 1000, branchSteps = 2000, branchFpEvery = 250, branchEarly = 250;
    bool fpDense = false, wiringNoPaths = false;
    std::vector<long> branchAt, behavAt;
    for (int i = 1; i < argc; ++i) {
        auto is = [&](const char* k) { return std::strcmp(argv[i], k) == 0 && i + 1 < argc; };
        if (is("--seed")) seed = (unsigned)std::strtoul(argv[++i], nullptr, 10);
        else if (is("--steps")) steps = std::strtol(argv[++i], nullptr, 10);
        else if (is("--every")) every = std::strtol(argv[++i], nullptr, 10);
        else if (is("--w")) W = std::atoi(argv[++i]);
        else if (is("--h")) H = std::atoi(argv[++i]);
        else if (is("--pop")) pop = std::atoi(argv[++i]);
        else if (is("--depth")) depth = std::atof(argv[++i]);
        else if (is("--cfg")) cfgJson = argv[++i];
        else if (is("--out")) out = argv[++i];
        else if (is("--arm")) armArg = argv[++i];
        else if (is("--evolve")) evolve = std::strtol(argv[++i], nullptr, 10);
        else if (is("--evolve-arm")) evolveArm = argv[++i];
        else if (is("--reps")) reps = std::atoi(argv[++i]);
        else if (is("--warm")) warm = std::atoi(argv[++i]);
        else if (is("--bsteps")) bsteps = std::atoi(argv[++i]);
        else if (is("--label")) label = argv[++i];
        else if (is("--dump-wiring")) dumpPath = argv[++i];
        else if (is("--wiring-every")) wiringEvery = std::strtol(argv[++i], nullptr, 10);
        else if (!std::strcmp(argv[i], "--behav")) behav = true;
        else if (!std::strcmp(argv[i], "--bench")) bench = true;
        // ALIFE 2027
        else if (is("--eye-code")) eyeCodeArg = std::atoi(argv[++i]);
        else if (is("--label-frame")) labelFrameArg = std::atoi(argv[++i]);
        else if (is("--resolved")) resolvedPath = argv[++i];
        else if (is("--manifest")) manifestPath = argv[++i];
        else if (is("--fp")) fpPath = argv[++i];
        else if (is("--fp-every")) fpEvery = std::strtol(argv[++i], nullptr, 10);
        else if (!std::strcmp(argv[i], "--fp-dense")) fpDense = true;
        else if (is("--diag")) diagPath = argv[++i];
        else if (is("--encounters")) encPath = argv[++i];
        else if (is("--encounters-until")) encUntil = std::strtol(argv[++i], nullptr, 10);
        else if (is("--encounters-every")) encEvery = std::strtol(argv[++i], nullptr, 10);
        else if (is("--branches")) branchSpecText = argv[++i];
        else if (is("--branch-out")) branchOut = argv[++i];
        else if (is("--branch-steps")) branchSteps = std::strtol(argv[++i], nullptr, 10);
        else if (is("--branch-fp-every")) branchFpEvery = std::strtol(argv[++i], nullptr, 10);
        else if (is("--branch-early")) branchEarly = std::strtol(argv[++i], nullptr, 10);
        else if (is("--branch-order")) branchOrder = argv[++i];
        else if (is("--branch-at")) {
            if (!parseStepList(argv[++i], branchAt)) { std::fprintf(stderr, "bad --branch-at %s\n", argv[i]); return 2; }
        }
        else if (is("--behav-at")) {
            if (!parseStepList(argv[++i], behavAt)) { std::fprintf(stderr, "bad --behav-at %s\n", argv[i]); return 2; }
        }
        else if (!std::strcmp(argv[i], "--wiring-no-paths")) wiringNoPaths = true;
        else { std::fprintf(stderr, "unknown or incomplete argument: %s\n", argv[i]); return 2; }
    }

    // ALIFE 2027 argument checks (none apply to a legacy invocation)
    const bool fpOn = !fpPath.empty(), diagOn = !diagPath.empty(), encOn = !encPath.empty();
    const bool branchOn = !branchSpecText.empty() || !branchAt.empty() || !branchOut.empty();
    std::vector<alx::BranchSpec> specs;
    {
        std::string e;
        if (fpDense && !fpOn) e = "--fp-dense needs --fp";
        else if (fpOn && fpEvery < 0) e = "--fp-every must be >= 0";
        else if (encOn && (encUntil < 1 || encEvery < 1)) e = "--encounters-until / --encounters-every must be >= 1";
        else if (branchOn && (branchSpecText.empty() || branchAt.empty() || branchOut.empty()))
            e = "branching needs --branches, --branch-at and --branch-out";
        else if (branchOn && !alx::parseBranchSpecs(branchSpecText, specs, e)) e = "--branches: " + e;
        else if (branchOn && (branchSteps < 1 || branchFpEvery < 0 || branchEarly < 0)) e = "bad --branch-steps / --branch-fp-every / --branch-early";
        else if (branchOn && branchOrder != "forward" && branchOrder != "reverse") e = "--branch-order is forward or reverse";
        else if (branchOn && (branchAt.front() < 1 || branchAt.back() > steps)) e = "--branch-at steps must be in 1..--steps";
        else if (!behavAt.empty() && (behavAt.front() < 1 || behavAt.back() > steps)) e = "--behav-at steps must be in 1..--steps";
        else if (labelFrameArg > 0 && !alx::hasLabelFrame()) e = "--label-frame: this engine has no labelFrame";
        if (!e.empty()) { std::fprintf(stderr, "%s\n", e.c_str()); return 2; }
    }
    if (fpOn && fpEvery == 0) fpEvery = every;

    OceanWorld w;
    std::string err;
    if (!ofp::initWorld(w, seed, W, H, (float)depth, pop, cfgJson, err)) {
        std::fprintf(stderr, "config refused: %s\n", err.c_str());
        return 4;
    }
    const bool wantCfgJson = !resolvedPath.empty() || !manifestPath.empty();
    const std::string initCfgJson = wantCfgJson ? alx::configJson(w.cfg, w.ocfg) : std::string();

    if (bench) {
        // Evolve under one arm, then time all four arms on that snapshot,
        // interleaved, the start rotating with the rep.
        const ArmDef* ea = findArm(evolveArm.empty() ? 'B' : evolveArm[0]);
        if (!ea) { std::fprintf(stderr, "bad --evolve-arm\n"); return 2; }
        w.ocfg.eye = ea->eye; w.ocfg.eyeOnly = ea->eyeOnly;
        const auto t0 = clk::now();
        for (long s = 0; s < evolve; ++s) w.update(kDt);
        std::printf("bench: evolved %ld steps (arm %c) in %.1f s: pop=%zu pred=%zu food=%zu\n", evolve, ea->name,
                    std::chrono::duration<double>(clk::now() - t0).count(), w.creatures.size(), w.predators.size(),
                    w.food.size());
        const OceanWorld snap = w;
        const RandomGen rsnap = rng;
        constexpr int V = 4;
        std::vector<double> ms[V], fishSteps[V];
        for (int r = -1; r < reps; ++r) {
            for (int j = 0; j < V; ++j) {
                const int vi = (r + 1 + j) % V;
                OceanWorld x = snap;
                rng = rsnap;
                x.ocfg.eye = kArms[vi].eye; x.ocfg.eyeOnly = kArms[vi].eyeOnly;
                for (int s = 0; s < warm; ++s) x.update(kDt);
                double fs = 0;
                const auto a = clk::now();
                for (int s = 0; s < bsteps; ++s) { fs += (double)x.creatures.size(); x.update(kDt); }
                const double sec = std::chrono::duration<double>(clk::now() - a).count();
                if (r < 0) continue;
                ms[vi].push_back(1e3 * sec / bsteps);
                fishSteps[vi].push_back(1e6 * sec / fs);
            }
        }
        for (int vi = 0; vi < V; ++vi) {
            std::vector<double> rat;
            for (int r = 0; r < reps; ++r) rat.push_back(ms[vi][r] / ms[0][r]);
            std::printf("bench arm=%c median_ms=%.4f min=%.4f max=%.4f us_per_fish_step=%.3f ratio_vs_A=%.4f [%.4f %.4f]\n",
                        kArms[vi].name, median(ms[vi]), *std::min_element(ms[vi].begin(), ms[vi].end()),
                        *std::max_element(ms[vi].begin(), ms[vi].end()), median(fishSteps[vi]), median(rat),
                        *std::min_element(rat.begin(), rat.end()), *std::max_element(rat.begin(), rat.end()));
        }
        return 0;
    }

    const ArmDef* arm = findArm(armArg.empty() ? 'A' : armArg[0]);
    if (!arm) { std::fprintf(stderr, "bad --arm (A, B, C or D)\n"); return 2; }
    w.ocfg.eye = arm->eye;
    w.ocfg.eyeOnly = arm->eyeOnly;
    if (armArg.size() > 1) w.ocfg.steerFrame = armArg[1] - '0';   // "C1": steerFrame 1
    if (eyeCodeArg >= 0) w.ocfg.eyeCode = eyeCodeArg;             // after the common initialization, like the arm
    if (labelFrameArg > 0 || (labelFrameArg == 0 && alx::hasLabelFrame())) {   // 0 is the default: a no-op without the key
        std::string e;
        if (!alx::setArmKey(w.ocfg, "labelFrame", labelFrameArg, e)) { std::fprintf(stderr, "%s\n", e.c_str()); return 4; }
    }
    if (!oceanConfigValid(w.ocfg)) { std::fprintf(stderr, "invalid ocean config\n"); return 4; }
    if (encOn && !alx::EncounterDiag::supported(w)) { std::fprintf(stderr, "--encounters: toroidal worlds are not supported\n"); return 2; }
    const std::string armStr = label.empty() ? armArg.substr(0, 2) : label;
    const char* armName = armStr.c_str();
    const std::string effCfgJson = wantCfgJson ? alx::configJson(w.cfg, w.ocfg) : std::string();
    std::uint32_t dtBits;
    std::memcpy(&dtBits, &kDt, 4);

    if (!resolvedPath.empty()) {
        std::FILE* rf = std::fopen(resolvedPath.c_str(), "w");
        if (!rf) { std::fprintf(stderr, "cannot write %s\n", resolvedPath.c_str()); return 3; }
        std::fprintf(rf,
                     "{\"schema\":\"finfolk.alife2027.resolved/1\",\"seed\":%u,\"arm\":\"%s\",\"world\":{\"width\":%d,"
                     "\"height\":%d,\"depth\":%.9g,\"founders\":%d},\"dt\":%.9g,\"dt_bits\":\"%08" PRIx32 "\",\"init\":%s,"
                     "\"effective\":%s}\n",
                     seed, alx::jsonEscape(armStr).c_str(), W, H, depth, pop, (double)kDt, dtBits, initCfgJson.c_str(),
                     effCfgJson.c_str());
        if (!closeChecked(rf, resolvedPath)) return 3;
    }

    // Fingerprints: step 0 is observed after the arm and before any instrument.
    alx::FpObserver fpObs;
    fpObs.dense = fpDense;
    if (fpOn) {
        fpObs.out = std::fopen(fpPath.c_str(), "w");
        if (!fpObs.out) { std::fprintf(stderr, "cannot write %s\n", fpPath.c_str()); return 3; }
        std::fprintf(fpObs.out, "# ocean_eye_exp fingerprints format=%d mode=%s every=%ld seed=%u arm=%s steps=%ld\n",
                     ofp::kFormatVersion, fpDense ? "dense" : "sparse", fpEvery, seed, armName, steps);
        fpObs.observe(w, 0, true);
    }
    alx::StepDiag diag;
    std::FILE* diagF = nullptr;
    if (diagOn) {
        diagF = std::fopen(diagPath.c_str(), "w");
        if (!diagF) { std::fprintf(stderr, "cannot write %s\n", diagPath.c_str()); return 3; }
        std::fprintf(diagF, "# ocean_eye_exp diagnostics format=%d seed=%u arm=%s every=%ld\n%s\n", alx::kDiagFormat, seed,
                     armName, every, alx::StepDiag::header());
        diag.begin(w);
        diag.row(diagF, w, 0);
    }
    alx::EncounterDiag enc;
    std::FILE* encF = nullptr;
    if (encOn) {
        encF = std::fopen(encPath.c_str(), "w");
        if (!encF) { std::fprintf(stderr, "cannot write %s\n", encPath.c_str()); return 3; }
        std::fprintf(encF, "# ocean_eye_exp encounters format=%d seed=%u arm=%s until=%ld every=%ld interactRadius=%.9g\n%s\n",
                     alx::kEncounterFormat, seed, armName, encUntil, encEvery, (double)w.cfg.interactRadius,
                     alx::EncounterDiag::header());
    }
    std::FILE* branchF = nullptr;
    std::FILE* branchFpF = nullptr;
    const std::string branchFpPath = branchOut + ".fp.txt";
    if (branchOn) {
        branchF = std::fopen(branchOut.c_str(), "w");
        branchFpF = branchF ? std::fopen(branchFpPath.c_str(), "w") : nullptr;
        if (!branchF || !branchFpF) { std::fprintf(stderr, "cannot write %s(.fp.txt)\n", branchOut.c_str()); return 3; }
        std::fprintf(branchF, "# ocean_eye_exp branches format=%d seed=%u arm=%s at=", alx::kBranchFormat, seed, armName);
        for (std::size_t k = 0; k < branchAt.size(); ++k) std::fprintf(branchF, "%s%ld", k ? "," : "", branchAt[k]);
        std::fprintf(branchF, " steps=%ld fp_every=%ld early=%ld order=%s mode=%s spec=%s\n%s\n", branchSteps, branchFpEvery,
                     branchEarly, branchOrder.c_str(), fpDense ? "dense" : "sparse", branchSpecText.c_str(), alx::branchHeader());
    }

    WiringDump dump;
    if (!dumpPath.empty() && !dump.open(dumpPath, w, armName, seed, cfgJson)) {
        std::fprintf(stderr, "cannot write %s\n", dumpPath.c_str());
        return 3;
    }
    if (wiringEvery > 0) dump.snapshot(w, 0, false);

    std::FILE* csv = std::fopen((out + ".csv").c_str(), "w");
    if (!csv) { std::fprintf(stderr, "cannot write %s.csv\n", out.c_str()); return 3; }
    std::fprintf(csv,
                 "arm,seed,step,pop,pop_mean,births,births_int,reseeds,reseeds_int,deaths_pred_int,deaths_starve_int,"
                 "deaths_age_int,food_eaten_int,food,food_mean,pred,pred_mean,pred_births,pred_births_int,pred_reseeds,"
                 "pred_starved,eat_per_fish_s,predation_per_fish_s,births_per_s,reseeds_per_1k,kills_per_pred_s,"
                 "clearance,clearance_norm,speed_mean,reserves_mean,depth_mean,depth_sd,genome_len,ms_per_step,"
                 "us_per_fish_step,eye_any,eye_direct,eye_conns,eye_absw,eye_share,eye_vert,food_matched,pred_move,"
                 "lab_move,rnd_eye_any,rnd_eye_direct,rnd_eye_conns,rnd_eye_absw,rnd_eye_share,rnd_eye_vert,"
                 "rnd_food_matched,rnd_pred_move,rnd_lab_move,eye_lr,rnd_eye_lr,steer_frame,"
                 "nn_mean,nn_null,near_frac,near_null\n");
    std::printf("arm %s (eye %d, eyeOnly %d, steerFrame %d, eyeCode %d) seed %u steps %ld cfg %s\n", armName,
                arm->eye, arm->eyeOnly, w.ocfg.steerFrame, w.ocfg.eyeCode, seed, steps, cfgJson ? cfgJson : "{}");

    // Sham continuations, checked against the uninterrupted run where it passes them.
    struct ShamCheck { long checkpoint; std::string branch; long compared = 0, mismatched = 0, expected = 0; };
    std::vector<ShamCheck> shamChecks;
    std::map<long, std::vector<std::pair<std::size_t, ofp::Fingerprint>>> shamExpect;   // step -> (check index, fp)
    long parentChecks = 0, parentFailed = 0, branchInstrumentBad = 0, branchNonFinite = 0;
    bool outputsOk = true;

    RandomGen wiringRng;
    wiringRng.seed(seed * 2654435761u + 11u);
    RandomGen clusterRng;   // the clustering null's positions (private)
    clusterRng.seed(seed * 2246822519u + 5u);
    const double volume = (double)W * H * depth;
    const double pickup = w.cfg.pickupRadius;
    long long lastBirths = 0, lastReseeds = 0, lastPred = 0, lastStarve = 0, lastAge = 0, lastEaten = 0,
              lastPredBirths = 0;
    double sumPop = 0, sumFood = 0, sumPreds = 0, fishSteps = 0;
    auto tInt = clk::now();
    const auto tRun = clk::now();
    for (long s = 1; s <= steps; ++s) {
        fishSteps += (double)w.creatures.size();
        if (diagOn) diag.before(w, kDt);
        const bool encNow = encOn && s <= encUntil;
        if (encNow) enc.before(w);
        w.update(kDt);
        if (fpOn) fpObs.observe(w, s, s % fpEvery == 0 || s == steps);
        if (diagOn) {
            diag.after(w, s);
            if (s % every == 0 || s == steps) diag.row(diagF, w, s);
        }
        if (encNow) {
            enc.after(w, s);
            if (s % encEvery == 0 || s == encUntil || s == steps) { enc.row(encF, s); enc.resetInterval(); }
        }
        if (!shamExpect.empty()) {
            const auto it = shamExpect.find(s);
            if (it != shamExpect.end()) {
                const ofp::Fingerprint here = (fpOn && fpObs.lastStep == s) ? fpObs.last : ofp::fingerprint(w);
                for (const auto& e : it->second) {
                    ++shamChecks[e.first].compared;
                    if (!(e.second == here)) ++shamChecks[e.first].mismatched;
                }
                shamExpect.erase(it);
            }
        }
        sumPop += (double)w.creatures.size();
        sumFood += (double)w.food.size();
        sumPreds += (double)w.predators.size();
        if (!dumpPath.empty() && wiringEvery > 0 && s % wiringEvery == 0 && s != steps) {
            const auto t0 = clk::now();
            dump.snapshot(w, s, false);
            tInt += clk::now() - t0;   // not in the interval's step timing
        }
        if (!behavAt.empty() && std::binary_search(behavAt.begin(), behavAt.end(), s)) {
            const auto t0 = clk::now();
            if (!behaviouralTest(w, armName, seed, out + "_behav_" + std::to_string(s) + ".csv")) outputsOk = false;
            tInt += clk::now() - t0;
        }
        if (branchOn && std::binary_search(branchAt.begin(), branchAt.end(), s)) {
            const auto t0 = clk::now();
            const ofp::Fingerprint before = ofp::fingerprint(w);
            const RandomGen parentRng = rng;
            std::vector<std::size_t> order(specs.size());
            for (std::size_t k = 0; k < order.size(); ++k) order[k] = k;
            if (branchOrder == "reverse") std::reverse(order.begin(), order.end());
            std::vector<alx::BranchResult> res(specs.size());
            for (std::size_t k : order) {
                std::string e;
                if (!alx::runContinuation(w, parentRng, specs[k], s, branchSteps, branchFpEvery, branchEarly, fpDense, kDt,
                                          res[k], e)) {
                    std::fprintf(stderr, "%s\n", e.c_str());
                    return 2;
                }
            }
            const ofp::Fingerprint after = ofp::fingerprint(w);
            ++parentChecks;
            const bool parentOk = before == after;
            if (!parentOk) ++parentFailed;
            for (std::size_t k = 0; k < specs.size(); ++k) {   // spec order, whatever the execution order
                const alx::BranchResult& r = res[k];
                alx::branchRow(branchF, seed, armName, r);
                for (const auto& f : r.fps) {
                    const std::string line = ofp::fingerprintLine("bfp", s + f.first, w, f.second);
                    // fingerprintLine prints the PARENT's counts (w); keep only its hashes
                    const std::size_t bar = line.find(" | ");
                    std::fprintf(branchFpF, "bfp %ld %s +%lld %016" PRIx64 "%s\n", s, r.name.c_str(), f.first, f.second.all,
                                 bar == std::string::npos ? "" : line.c_str() + bar);
                }
                branchInstrumentBad += r.identityBad + r.expiryBad;
                branchNonFinite += r.nonFinite;
                if (specs[k].changes.empty()) {   // a sham: the uninterrupted run must pass the same states
                    ShamCheck sc;
                    sc.checkpoint = s;
                    sc.branch = r.name;
                    shamChecks.push_back(sc);
                    for (const auto& f : r.fps)
                        if (f.first > 0 && s + f.first <= steps) {
                            shamExpect[s + f.first].emplace_back(shamChecks.size() - 1, f.second);
                            ++shamChecks.back().expected;
                        }
                }
            }
            std::fprintf(branchF, "# check parent_restored checkpoint=%ld %s\n", s, parentOk ? "ok" : "FAILED");
            std::fflush(branchF);
            tInt += clk::now() - t0;
        }
        if (s % every != 0 && s != steps) continue;

        const double secsWall = std::chrono::duration<double>(clk::now() - tInt).count();
        const long n = (s % every == 0) ? every : (s % every);
        const double simSecs = n * (double)kDt;
        const double popMean = sumPop / n, foodMean = sumFood / n, predMean = sumPreds / n;
        const long long births = w.totalBirths - lastBirths, reseeds = w.totalReseeds - lastReseeds,
                        dPred = w.totalDeathsPredation - lastPred, dStarve = w.totalDeathsStarvation - lastStarve,
                        dAge = w.totalDeathsAge - lastAge, eaten = w.totalFoodEaten - lastEaten,
                        pBirths = w.totalPredatorBirths - lastPredBirths;
        double resv = 0, zs = 0, zs2 = 0, spd = 0, glen = 0;
        for (const Fish& f : w.creatures) {
            resv += f.foodReserves; zs += f.depth; zs2 += (double)f.depth * f.depth; spd += f.speed;
            glen += (double)f.genome.size();
        }
        const double np = w.creatures.empty() ? 1.0 : (double)w.creatures.size();
        const double zm = zs / np, zsd = std::sqrt(std::max(0.0, zs2 / np - zm * zm));
        const double eatPerFish = popMean > 0 ? eaten / (popMean * simSecs) : 0.0;
        const double density = foodMean / volume;
        const double clearance = density > 0 ? eatPerFish / density : 0.0;          // volume searched / s
        const double sweep = 3.14159265 * pickup * pickup * (spd / np);            // a straight swimmer's
        Wiring we, wr;
        scoreWiring(w, wiringRng, we, wr);
        const Clustering cl = clusteringOf(w, clusterRng);
        const double fe = we.fish > 0 ? we.fish : 1, fr = wr.fish > 0 ? wr.fish : 1;
        std::fprintf(csv,
                     "%s,%u,%ld,%zu,%.2f,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%zu,%.1f,%zu,%.3f,%lld,%lld,%lld,%lld,"
                     "%.6f,%.6f,%.4f,%.4f,%.5f,%.1f,%.4f,%.2f,%.3f,%.2f,%.2f,%.2f,%.4f,%.4f,"
                     "%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,"
                     "%.4f,%.4f,%d,%.3f,%.3f,%.4f,%.4f\n",
                     armName, seed, s, w.creatures.size(), popMean, w.totalBirths, births, w.totalReseeds, reseeds,
                     dPred, dStarve, dAge, eaten, w.food.size(), foodMean, w.predators.size(), predMean,
                     w.totalPredatorBirths, pBirths, w.totalPredatorReseeds, w.totalPredatorDeathsStarvation,
                     eatPerFish, popMean > 0 ? dPred / (popMean * simSecs) : 0.0, births / simSecs,
                     1000.0 * reseeds / n, predMean > 0 ? dPred / (predMean * simSecs) : 0.0, clearance,
                     sweep > 0 ? clearance / sweep : 0.0, spd / np, resv / np, zm, zsd, glen / np,
                     1e3 * secsWall / n, fishSteps > 0 ? 1e6 * secsWall / fishSteps : 0.0,
                     we.eyeAny / fe, we.eyeDirect / fe, we.eyeConns / fe, we.eyeAbsW / fe,
                     we.sensorConns > 0 ? we.eyeShareNum / we.sensorConns : 0.0, we.eyeVertDirect / fe,
                     we.foodMatched / fe, we.predMove / fe, we.labMove / fe,
                     wr.eyeAny / fr, wr.eyeDirect / fr, wr.eyeConns / fr, wr.eyeAbsW / fr,
                     wr.sensorConns > 0 ? wr.eyeShareNum / wr.sensorConns : 0.0, wr.eyeVertDirect / fr,
                     wr.foodMatched / fr, wr.predMove / fr, wr.labMove / fr, we.eyeLRDirect / fe,
                     wr.eyeLRDirect / fr, w.ocfg.steerFrame, cl.nnMean, cl.nnNull, cl.nearFrac, cl.nearNull);
        std::fflush(csv);
        std::printf("arm %s seed %u step %ld pop %zu births %lld reseeds %lld pred %zu eat/fish/s %.3f pred/fish/s %.4f"
                    " clr_norm %.2f %.3f ms/step\n",
                    armName, seed, s, w.creatures.size(), w.totalBirths, w.totalReseeds, w.predators.size(),
                    eatPerFish, popMean > 0 ? dPred / (popMean * simSecs) : 0.0, sweep > 0 ? clearance / sweep : 0.0,
                    1e3 * secsWall / n);
        std::fflush(stdout);
        lastBirths = w.totalBirths; lastReseeds = w.totalReseeds; lastPred = w.totalDeathsPredation;
        lastStarve = w.totalDeathsStarvation; lastAge = w.totalDeathsAge; lastEaten = w.totalFoodEaten;
        lastPredBirths = w.totalPredatorBirths;
        sumPop = sumFood = sumPreds = fishSteps = 0;
        tInt = clk::now();
    }
    if (!closeChecked(csv, out + ".csv")) outputsOk = false;
    const double runSecs = std::chrono::duration<double>(clk::now() - tRun).count();
    std::printf("run done in %.1f s\n", runSecs);
    if (!dumpPath.empty()) {
        const auto td = clk::now();
        dump.snapshot(w, steps, !wiringNoPaths);
        if (!dump.close()) { std::fprintf(stderr, "error writing %s\n", dumpPath.c_str()); outputsOk = false; }
        std::printf("wiring dump in %.1f s: %s\n", std::chrono::duration<double>(clk::now() - td).count(),
                    dumpPath.c_str());
    }
    if (behav) {
        const auto tb = clk::now();
        if (!behaviouralTest(w, armName, seed, out + "_behav.csv")) outputsOk = false;
        std::printf("behavioural test in %.1f s\n", std::chrono::duration<double>(clk::now() - tb).count());
    }

    // ---- the ALIFE 2027 instruments' verdicts ------------------------------------
    long shamCompared = 0, shamMismatched = 0, shamUnchecked = 0;
    if (branchOn) {
        for (const ShamCheck& sc : shamChecks) {
            const bool unchecked = sc.expected == 0;
            shamCompared += sc.compared;
            shamMismatched += sc.mismatched + (sc.expected - sc.compared);
            shamUnchecked += unchecked;
            std::fprintf(branchF, "# check sham_identity checkpoint=%ld branch=%s compared=%ld mismatched=%ld %s\n",
                         sc.checkpoint, sc.branch.c_str(), sc.compared, sc.mismatched + (sc.expected - sc.compared),
                         unchecked ? "unchecked (the run ends before the continuation does)"
                                   : (sc.mismatched == 0 && sc.compared == sc.expected ? "ok" : "FAILED"));
        }
        std::fprintf(branchF, "# check food_identity bad=%ld %s\n", branchInstrumentBad, branchInstrumentBad ? "FAILED" : "ok");
        if (!closeChecked(branchF, branchOut)) outputsOk = false;
        if (!closeChecked(branchFpF, branchFpPath)) outputsOk = false;
    }
    if (encOn && !closeChecked(encF, encPath)) outputsOk = false;
    if (diagOn && !closeChecked(diagF, diagPath)) outputsOk = false;
    if (fpOn) {
        std::fprintf(fpObs.out, "fp_summary observed=%lld nonfinite_max=%lld nonfinite_first=%lld mode=%s",
                     fpObs.observed, fpObs.nonFiniteMax, fpObs.nonFiniteFirst, fpDense ? "dense" : "sparse");
        if (fpDense) std::fprintf(fpObs.out, " chain=%016" PRIx64, fpObs.chain.value());
        std::fputc('\n', fpObs.out);
        if (!closeChecked(fpObs.out, fpPath)) outputsOk = false;
    }
    const bool nonFinite = fpObs.nonFiniteMax > 0 || branchNonFinite > 0;
    const bool instrumentBad = diag.identityBad > 0 || diag.expiryBad > 0 || branchInstrumentBad > 0 || parentFailed > 0 ||
                               shamMismatched > 0;
    const int status = !outputsOk ? 3 : nonFinite ? 5 : instrumentBad ? 6 : 0;
    if (!manifestPath.empty()) {
        std::FILE* mf = std::fopen(manifestPath.c_str(), "w");
        if (!mf) { std::fprintf(stderr, "cannot write %s\n", manifestPath.c_str()); return 3; }
        std::fprintf(mf, "{\"schema\":\"finfolk.alife2027.run_info/1\",\"tool\":\"tools/ocean_eye_exp.cpp\",\"argv\":[");
        for (int i = 0; i < argc; ++i) std::fprintf(mf, "%s\"%s\"", i ? "," : "", alx::jsonEscape(argv[i]).c_str());
        std::fprintf(mf, "],\"seed\":%u,\"arm\":\"%s\",\"arm_letter\":\"%c\",\"arm_settings\":{\"eye\":%d,\"eyeOnly\":%d,"
                         "\"steerFrame\":%d,\"eyeCode\":%d,\"labelFrame\":%d},",
                     seed, alx::jsonEscape(armStr).c_str(), arm->name, w.ocfg.eye, w.ocfg.eyeOnly, w.ocfg.steerFrame,
                     w.ocfg.eyeCode, alx::armKey(w.ocfg, "labelFrame"));
        std::fprintf(mf, "\"world\":{\"width\":%d,\"height\":%d,\"depth\":%.9g,\"founders\":%d},\"steps\":%ld,\"every\":%ld,"
                         "\"dt\":%.9g,\"dt_bits\":\"%08" PRIx32 "\",",
                     W, H, depth, pop, steps, every, (double)kDt, dtBits);
        std::fprintf(mf, "\"build\":{\"NUM_SENSES\":%d,\"NUM_ACTIONS\":%d,\"eye_build\":%s,\"label_frame\":%s,"
                         "\"fingerprint_format\":%d,\"diag_format\":%d,\"branch_format\":%d,\"encounter_format\":%d,"
                         "\"cplusplus\":%ld,\"compiler\":\"%s\",\"optimize\":%s,\"fast_math\":%s,\"pointer_bits\":%d},",
                     (int)NUM_SENSES, (int)NUM_ACTIONS, kOceanHasEye ? "true" : "false", alx::hasLabelFrame() ? "true" : "false",
                     ofp::kFormatVersion, alx::kDiagFormat, alx::kBranchFormat, alx::kEncounterFormat, (long)__cplusplus,
                     alx::jsonEscape(compilerId()).c_str(),
#ifdef __OPTIMIZE__
                     "true",
#else
                     "false",
#endif
#ifdef __FAST_MATH__
                     "true",
#else
                     "false",
#endif
                     (int)(8 * sizeof(void*)));
        std::fprintf(mf, "\"instruments\":{\"fp\":%s,\"fp_mode\":\"%s\",\"fp_every\":%ld,\"diag\":%s,\"encounters\":%s,"
                         "\"encounters_until\":%ld,\"branches\":%s,\"behav\":%s,\"wiring\":%s,\"wiring_every\":%ld},",
                     fpOn ? "true" : "false", fpOn ? (fpDense ? "dense" : "sparse") : "none", fpOn ? fpEvery : 0L,
                     diagOn ? "true" : "false", encOn ? "true" : "false", encOn ? encUntil : 0L, branchOn ? "true" : "false",
                     behav ? "true" : "false", dumpPath.empty() ? "false" : "true", wiringEvery);
        std::fprintf(mf, "\"result\":{\"status\":%d,\"final_step\":%ld,\"run_seconds\":%.3f,\"fp_observed\":%lld,"
                         "\"nonfinite_max\":%lld,\"nonfinite_first\":%lld,\"food_identity_bad\":%lld,\"food_expiry_bad\":%lld,"
                         "\"branch_parent_checks\":%ld,\"branch_parent_failed\":%ld,\"sham_compared\":%ld,"
                         "\"sham_mismatched\":%ld,\"sham_unchecked\":%ld,\"branch_instrument_bad\":%ld,"
                         "\"branch_nonfinite\":%ld,\"pop_final\":%zu,\"total_reseeds\":%lld},",
                     status, steps, runSecs, fpObs.observed, fpObs.nonFiniteMax, fpObs.nonFiniteFirst, diag.identityBad,
                     diag.expiryBad, parentChecks, parentFailed, shamCompared, shamMismatched, shamUnchecked,
                     branchInstrumentBad, branchNonFinite, w.creatures.size(), w.totalReseeds);
        std::fprintf(mf, "\"config_init\":%s,\"config_effective\":%s}\n", initCfgJson.c_str(), effCfgJson.c_str());
        if (!closeChecked(mf, manifestPath)) return 3;
    }
    if (status == 5) std::fprintf(stderr, "non-finite state observed (max %lld, first at step %lld)\n", fpObs.nonFiniteMax, fpObs.nonFiniteFirst);
    if (status == 6) std::fprintf(stderr, "instrument check failed: food identity %lld, expiry %lld, branch %ld, parent %ld, sham %ld\n",
                                  diag.identityBad, diag.expiryBad, branchInstrumentBad, parentFailed, shamMismatched);
    return status;
}
#endif  // OCEAN_EYE_EXP_NO_MAIN

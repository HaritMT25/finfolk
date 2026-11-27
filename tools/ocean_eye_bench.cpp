// ocean_eye_bench.cpp — what does the compound eye cost? Step time of the
// Ocean world with the eye off vs on, on the SAME world state, interleaved.
//
// A world is built (fresh: N founders; or evolved: then run E steps), copied
// as a snapshot (world + rng), and every timed run restores the snapshot, sets
// OceanConfig::eye to its variant, runs --warm untimed steps and times --steps.
// A variant is EYE or EYE:CODE (CODE = OceanConfig::eyeCode, default 0), so
// --variants 1,1:7,1 times the eye's encodings 0 vs 7 with an A/A control.
// Each rep runs every variant once, the start rotating with the rep (rep r
// starts at variant r mod V), so every variant sits at every position equally
// often. A variant list like 0,1,0 gives the A/B (on/off) and an A/A control
// (the second off / the first off) from the same session.
//
//   g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -DEVO_OCEAN_EYE -I src \
//       tools/ocean_eye_bench.cpp -o eye_bench
//   taskset -c 2 ./eye_bench --pop 3000 --variants 0,1,0 --reps 7 --warm 10 --steps 50
//   ./eye_bench --pop 300 --evolve 20000 --evolve-eye 1 --variants 0,1,0 ...
//
// The plain Ocean build (no -DEVO_OCEAN_EYE) accepts only --variants 0 (for
// the plain-vs-eye-build comparison, one process per run). With
// -DEVO_OCEAN_PROF it also prints the phase split (OceanWorld::oprof).
// --wiring prints how the snapshot's fish wire the eye (the evolution check).
//
// Options: --seed S --pop N --w W --h H --depth D --cfg JSON --evolve E
//          --evolve-eye 0|1 --variants LIST --reps R --warm K --steps M
//          --wiring --label TEXT
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "ocean_hydro_bench.hpp"
#include "ocean_fingerprint.hpp"   // ofp::initWorld: the page's config path

namespace {

double median(std::vector<double> v) {
    if (v.empty()) return 0.0;
    std::sort(v.begin(), v.end());
    const size_t n = v.size();
    return (n % 2) ? v[n / 2] : 0.5 * (v[n / 2 - 1] + v[n / 2]);
}

#ifdef EVO_OCEAN_EYE
bool isEye(int src) { return src >= ocean::kEyeFirst && src < ocean::kEyeFirst + ocean::kEyeInputs; }

// How the world's fish wire the 18 eye inputs.
void wiringReport(const OceanWorld& w, const char* label) {
    const int moveActs[] = {STEER_X, STEER_Y, STEER_Z, MOVE_FORWARD, SPEED_ADJUST};
    long fish = 0, anyEye = 0, eyeReachesAct = 0, eyeReachesMove = 0, eyeDirectMove = 0;
    long sensorConns = 0, eyeConns = 0, conns = 0;
    long featConns[3] = {0, 0, 0}, sectorConns[6] = {0, 0, 0, 0, 0, 0};
    double genomeLen = 0;
    for (const Fish& f : w.creatures) {
        if (!f.alive) continue;
        ++fish;
        genomeLen += (double)f.genome.size();
        bool any = false;
        for (const auto& fc : f.nnet.flat) {
            ++conns;
            const int s = fc.src();
            if (s < NUM_SENSES) ++sensorConns;
            if (isEye(s)) {
                ++eyeConns;
                any = true;
                ++featConns[(s - ocean::kEyeFirst) % 3];
                ++sectorConns[(s - ocean::kEyeFirst) / 3];
            }
        }
        anyEye += any;
        bool act = false, mv = false, dmv = false;
        for (int e = 0; e < ocean::kEyeInputs && !(act && mv && dmv); ++e) {
            const int s = ocean::kEyeFirst + e;
            for (int a = 0; a < NUM_ACTIONS; ++a) {
                if (!ocean::sensorReachesAction(f.nnet, s, a)) continue;
                act = true;
                for (int m : moveActs) {
                    if (a == m) mv = true;
                    if (a == m && ocean::sensorWiresAction(f.nnet, s, a)) dmv = true;
                }
            }
        }
        eyeReachesAct += act;
        eyeReachesMove += mv;
        eyeDirectMove += dmv;
    }
    const double n = fish ? (double)fish : 1.0;
    std::printf("wiring %s fish=%ld genome_len=%.1f conns/fish=%.1f | any_eye_conn=%.1f%%"
                " eye_reaches_action=%.1f%% eye_reaches_move=%.1f%% eye_direct_move=%.1f%%"
                " | eye_share_of_sensor_conns=%.2f%% (neutral %.2f%%)"
                " | feat prox/size/con=%ld/%ld/%ld sectors a/b/l/r/u/d=%ld/%ld/%ld/%ld/%ld/%ld\n",
                label, fish, genomeLen / n, (double)conns / n, 100.0 * anyEye / n,
                100.0 * eyeReachesAct / n, 100.0 * eyeReachesMove / n, 100.0 * eyeDirectMove / n,
                sensorConns ? 100.0 * eyeConns / sensorConns : 0.0,
                100.0 * ocean::kEyeInputs / (int)NUM_SENSES, featConns[0], featConns[1], featConns[2],
                sectorConns[0], sectorConns[1], sectorConns[2], sectorConns[3], sectorConns[4],
                sectorConns[5]);
}
#endif

}  // namespace

int main(int argc, char** argv) {
    if(argc>1&&std::strcmp(argv[1],"--mechanics-components")==0)
        return hydrobench::main(argc-1,argv+1);
    unsigned seed = 42;
    int pop = 300, W = 1920, H = 1080, reps = 7, warm = 10, steps = 100;
    long evolve = 0;
    int evolveEye = 1;
    double depth = 240.0;
    const char* cfgJson = nullptr;
    std::string variantsArg = "0", label = "";
    bool wiring = false;
    for (int i = 1; i < argc; ++i) {
        auto is = [&](const char* k) { return std::strcmp(argv[i], k) == 0 && i + 1 < argc; };
        if (is("--seed")) seed = (unsigned)std::strtoul(argv[++i], nullptr, 10);
        else if (is("--pop")) pop = std::atoi(argv[++i]);
        else if (is("--w")) W = std::atoi(argv[++i]);
        else if (is("--h")) H = std::atoi(argv[++i]);
        else if (is("--depth")) depth = std::atof(argv[++i]);
        else if (is("--cfg")) cfgJson = argv[++i];
        else if (is("--evolve")) evolve = std::strtol(argv[++i], nullptr, 10);
        else if (is("--evolve-eye")) evolveEye = std::atoi(argv[++i]);
        else if (is("--variants")) variantsArg = argv[++i];
        else if (is("--reps")) reps = std::atoi(argv[++i]);
        else if (is("--warm")) warm = std::atoi(argv[++i]);
        else if (is("--steps")) steps = std::atoi(argv[++i]);
        else if (is("--label")) label = argv[++i];
        else if (!std::strcmp(argv[i], "--wiring")) wiring = true;
        else { std::fprintf(stderr, "unknown or incomplete argument: %s\n", argv[i]); return 2; }
    }
    std::vector<int> variants, codes;   // per variant: OceanConfig::eye, OceanConfig::eyeCode
    for (const char* p = variantsArg.c_str(); *p;) {
        variants.push_back(std::atoi(p));
        while (*p && *p != ',' && *p != ':') ++p;
        codes.push_back(*p == ':' ? std::atoi(++p) : 0);
        while (*p && *p != ',') ++p;
        if (*p == ',') ++p;
    }
    const int V = (int)variants.size();
    for (int vi = 0; vi < V; ++vi) {
        if ((variants[vi] != 0 || codes[vi] != 0) && !kOceanHasEye) {
            std::fprintf(stderr, "this build has no eye: --variants 0 only\n");
            return 2;
        }
        if (!eyeCodeValid(codes[vi])) { std::fprintf(stderr, "bad eyeCode %d\n", codes[vi]); return 2; }
    }

    OceanWorld world;
    std::string err;
    if (!ofp::initWorld(world, seed, W, H, (float)depth, pop, cfgJson, err)) {
        std::fprintf(stderr, "config refused: %s\n", err.c_str());
        return 4;
    }
    using clk = std::chrono::steady_clock;
    if (evolve > 0) {
        world.ocfg.eye = evolveEye;
        const auto t0 = clk::now();
        for (long s = 0; s < evolve; ++s) world.update(0.016f);
        std::printf("evolved %ld steps (eye %d) in %.1f s: pop=%zu births=%lld deaths=%lld reseeds=%lld food=%zu pred=%zu\n",
                    evolve, evolveEye, std::chrono::duration<double>(clk::now() - t0).count(),
                    world.creatures.size(), world.totalBirths, world.totalDeaths, world.totalReseeds,
                    world.food.size(), world.predators.size());
        world.ocfg.eye = 0;
    }
#ifdef EVO_OCEAN_EYE
    if (wiring) wiringReport(world, label.empty() ? "snapshot" : label.c_str());
#else
    (void)wiring;
#endif
    if (reps <= 0 || steps <= 0) return 0;

    const OceanWorld snap = world;
    const RandomGen rsnap = rng;
    const int snapPop = (int)snap.creatures.size();

    // ms/step per (variant, rep); the mean population over the timed steps.
    std::vector<std::vector<double>> ms(V), popMean(V);
#ifdef EVO_OCEAN_PROF
    std::vector<OceanWorld::OceanProf> prof(V);
#endif
    // Round -1 is a discarded warm-up of every variant (caches, and under node
    // the JIT's tier-up), then the recorded reps.
    for (int r = -1; r < reps; ++r) {
        for (int j = 0; j < V; ++j) {
            const int vi = (r + 1 + j) % V;
            OceanWorld w = snap;
            rng = rsnap;
            w.ocfg.eye = variants[vi];
            w.ocfg.eyeCode = codes[vi];
            for (int s = 0; s < warm; ++s) w.update(0.016f);
#ifdef EVO_OCEAN_PROF
            w.oprof = {};
#endif
            long long fishSteps = 0;
            const auto t0 = clk::now();
            for (int s = 0; s < steps; ++s) {
                fishSteps += (long long)w.creatures.size();
                w.update(0.016f);
            }
            const double sec = std::chrono::duration<double>(clk::now() - t0).count();
            if (r < 0) continue;
            ms[vi].push_back(1e3 * sec / steps);
            popMean[vi].push_back((double)fishSteps / steps);
#ifdef EVO_OCEAN_PROF
            OceanWorld::OceanProf& P = prof[vi];
            P.buildNs += w.oprof.buildNs; P.fishPhaseNs += w.oprof.fishPhaseNs;
            P.serialNs += w.oprof.serialNs; P.totalNs += w.oprof.totalNs;
            P.sensNs += w.oprof.sensNs; P.ffNs += w.oprof.ffNs; P.moveNs += w.oprof.moveNs;
            P.steps += w.oprof.steps; P.fishSteps += w.oprof.fishSteps;
#endif
            std::printf("run label=%s variant=%d(eye%d code%d) rep=%d ms_per_step=%.4f pop_mean=%.1f\n",
                        label.c_str(), vi, variants[vi], codes[vi], r, ms[vi].back(), popMean[vi].back());
        }
    }

    std::printf("summary label=%s pop0=%d world=%dx%dx%.0f warm=%d steps=%d reps=%d\n", label.c_str(), snapPop,
                W, H, depth, warm, steps, reps);
    for (int vi = 0; vi < V; ++vi) {
        const auto& m = ms[vi];
        const double med = median(m);
        const double lo = *std::min_element(m.begin(), m.end()), hi = *std::max_element(m.begin(), m.end());
        const double pm = median(popMean[vi]);
        std::printf("  variant=%d eye=%d code=%d median_ms=%.4f min=%.4f max=%.4f spread=%.1f%% pop=%.0f us_per_fish_step=%.3f\n",
                    vi, variants[vi], codes[vi], med, lo, hi, med > 0 ? 100.0 * (hi - lo) / med : 0.0, pm,
                    pm > 0 ? 1e3 * med / pm : 0.0);
#ifdef EVO_OCEAN_PROF
        const OceanWorld::OceanProf& P = prof[vi];
        const double fsN = P.fishSteps ? (double)P.fishSteps : 1.0;
        std::printf("    prof: build %.1f%% fish-phase %.1f%% serial %.1f%% of the step | in the fish phase:"
                    " sensors %.1f%% feedForward %.1f%% move+metab %.1f%% (clocks %.1f%%)"
                    " | ns/fish-step: sensors %.0f ff %.0f move %.0f\n",
                    100.0 * P.buildNs / P.totalNs, 100.0 * P.fishPhaseNs / P.totalNs,
                    100.0 * P.serialNs / P.totalNs, 100.0 * P.sensNs / P.fishPhaseNs,
                    100.0 * P.ffNs / P.fishPhaseNs, 100.0 * P.moveNs / P.fishPhaseNs,
                    100.0 * (P.fishPhaseNs - P.sensNs - P.ffNs - P.moveNs) / P.fishPhaseNs,
                    P.sensNs / fsN, P.ffNs / fsN, P.moveNs / fsN);
#endif
    }
    // Paired ratios against variant 0 (same rep): > 1 = slower than variant 0.
    for (int vi = 1; vi < V; ++vi) {
        std::vector<double> rat;
        for (int r = 0; r < reps; ++r) rat.push_back(ms[vi][r] / ms[0][r]);
        const double lo = *std::min_element(rat.begin(), rat.end()), hi = *std::max_element(rat.begin(), rat.end());
        std::printf("  ratio variant%d/variant0 (eye%d:%d/eye%d:%d): median %.4f [min %.4f max %.4f]\n", vi,
                    variants[vi], codes[vi], variants[0], codes[0], median(rat), lo, hi);
    }
    return 0;
}

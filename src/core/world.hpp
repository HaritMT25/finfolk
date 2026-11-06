#pragma once
#include <vector>
#include <algorithm>
#include <cmath>
#include <iostream>
#include <cstring>
#include <cstdint>
#include <chrono>
#include <utility>
#include "vec2.hpp"
#include "portable_math.hpp"
#include "creature.hpp"
#include "body_model.hpp"
#include "predator.hpp"
#include "predator_brain.hpp"
#include "quadtree.hpp"
#include "spatial_grid.hpp"
#include "config.hpp"
#include "current.hpp"
#include "kernel.hpp"
#include "world_common.hpp"
#ifdef EVO_POOL_THREADS
#include "thread_pool.hpp"
#endif

// A fixed --seed reproduces a whole run only in the single-threaded build. Both
// threaded paths (OpenMP natively, the thread pool under Emscripten) give each
// thread its own rng, so tests that compare whole runs key off this.
#if !defined(USE_OPENMP) && !defined(EVO_POOL_THREADS)
#define EVO_DETERMINISTIC 1
#endif

struct Food {
    Vec2 pos;
    bool alive = true;
};

// Pheromone signal layer overlaying the world (from biosim4)
class SignalGrid {
    int w_, h_, cellSize_;
    int cols_, rows_;
    int wrapCols_ = 0, wrapRows_ = 0;   // seam period in cells (toroidal mode)
    bool toroidal_ = false;
    std::vector<uint8_t> grid_;

    static int floorDiv(int a, int b) {
        int q = a / b;
        if ((a % b != 0) && ((a < 0) != (b < 0))) --q;
        return q;
    }
    static int wrapIdx(int i, int n) {
        i %= n;
        return i < 0 ? i + n : i;
    }

public:
    void init(int worldW, int worldH, int cellSize = 8, bool toroidal = false) {
        w_ = worldW; h_ = worldH; cellSize_ = cellSize;
        cols_ = worldW / cellSize + 1;
        rows_ = worldH / cellSize + 1;
        // Wrap arithmetic uses the true seam period, NOT the padded cols_/rows_
        // (the +1 partial column/row stays allocated but is never indexed by
        // the toroidal paths, so checkpoint geometry is unchanged).
        wrapCols_ = worldW / cellSize;
        wrapRows_ = worldH / cellSize;
        toroidal_ = toroidal;
        grid_.assign(cols_ * rows_, 0);
    }

    void emit(Vec2 pos, int radius = 2) {
        int cx = static_cast<int>(pos.x) / cellSize_;
        int cy = static_cast<int>(pos.y) / cellSize_;
        for (int dy = -radius; dy <= radius; ++dy) {
            for (int dx = -radius; dx <= radius; ++dx) {
                int x = cx + dx, y = cy + dy;
                if (toroidal_) {
                    x = wrapIdx(x, wrapCols_);
                    y = wrapIdx(y, wrapRows_);
                    int idx = y * cols_ + x;
                    grid_[idx] = static_cast<uint8_t>(std::min(255, grid_[idx] + 64));
                } else if (x >= 0 && x < cols_ && y >= 0 && y < rows_) {
                    int idx = y * cols_ + x;
                    grid_[idx] = static_cast<uint8_t>(std::min(255, grid_[idx] + 64));
                }
            }
        }
    }

    float read(Vec2 pos) const {
        int x, y;
        if (toroidal_) {
            // floor division so slightly-negative probe points (readInDir near
            // the seam) land in the right cell before wrapping.
            x = wrapIdx(floorDiv(static_cast<int>(std::floor(pos.x)), cellSize_), wrapCols_);
            y = wrapIdx(floorDiv(static_cast<int>(std::floor(pos.y)), cellSize_), wrapRows_);
        } else {
            x = std::clamp(static_cast<int>(pos.x) / cellSize_, 0, cols_ - 1);
            y = std::clamp(static_cast<int>(pos.y) / cellSize_, 0, rows_ - 1);
        }
        return grid_[y * cols_ + x] / 255.0f;
    }

    float readInDir(Vec2 pos, Vec2 dir, float dist = 24.0f) const {
        return read({pos.x + dir.x * dist, pos.y + dir.y * dist});
    }

    // Each cell keeps 97% of its strength. In fixed point: (v * 63570) >> 16
    // equals uint8_t(v * 0.97f) for every one of the 256 byte values (checked
    // exhaustively, and pinned by core_tests), and with no branch and no
    // float conversion the loop vectorises.
    void decay() {
        for (auto& v : grid_) {
            v = static_cast<uint8_t>((static_cast<uint32_t>(v) * 63570u) >> 16);
        }
    }

    // --- Checkpoint access ---
    // The pheromone layer is live state, not a derived view: creatures emit into
    // it, it decays every third frame, and three sensors read it. A checkpoint
    // that skipped it would resume into a world where the trails had vanished.
    const std::vector<uint8_t>& data() const { return grid_; }
    int cellSize() const { return cellSize_; }
    int cols() const { return cols_; }
    int rows() const { return rows_; }
    bool restore(const std::vector<uint8_t>& g) {
        if (g.size() != grid_.size()) return false;   // geometry mismatch
        grid_ = g;
        return true;
    }
};


// One attended neighbour, with the offset already computed so the second pass
// never re-reads its position. Used only when SimConfig::maxNeighbors > 0.
struct NeighborCandidate {
    float distSq;
    float dx, dy;
    int   index;
};

// Upper bound on the topological attention cap. Real animals attend to a
// handful (see SimConfig::maxNeighbors), so this is far above any meaningful
// setting; it exists so the nearest-N selection can use a fixed stack array
// and never allocate. Materialising the candidate list instead measured
// SLOWER than no cap at all, because writing ~150 candidates per creature per
// step costs more memory traffic than the per-neighbour work it skips.
constexpr int MAX_TOPOLOGICAL_NEIGHBORS = 64;

// What the neighbour scan reads of another creature, in a compact array: 16 B
// a creature instead of a ~430 B Creature, so the scan's scattered reads stay
// in cache once the population outgrows it. World::update refreshes entry i at
// the start of a step and again the moment creature i has finished moving, so
// at every point it holds creatures[i].pos / .vel - exactly what the scan read
// before (in the serial loop, lower-index creatures have already moved).
struct CreatureHot {
    Vec2 pos;
    Vec2 vel;
};

// Reusable scratch buffer for the per-creature neighbour query. Kept alive
// across creatures (and one per thread under OpenMP) so the query doesn't
// heap-allocate a fresh std::vector every tick. (The food and long-probe
// senses scan the grid directly and need no list.)
struct SensorScratch {
    std::vector<int> neighbors;
};


class World : public WorldCommon {
public:
    int width, height;
    std::vector<Creature> creatures;
    std::vector<Predator> predators;   // scripted hunters (empty unless cfg.predatorCount>0).
                                       // Fixed-count/immortal in Stage A; a self-regulating
                                       // population with an energy economy in Stage B.
    std::vector<Food> food;
    SignalGrid signals;

    // Structural constant, kept compile-time (not a tuning knob).
    static constexpr float LONGPROBE_DIST = 200.0f;

    // Minimum-image displacement components on the torus (toroidal mode only):
    // the shortest signed offset from a to b along an axis of span `span`.
    // Exactly-half-span offsets keep their sign (+span/2), giving the fixed
    // convention the topological tie-break's total order needs.
    static float wrapDelta(float d, float span) {
        const float half = 0.5f * span;
        if (d > half) return d - span;
        if (d < -half) return d + span;
        return d;
    }
    float wrapDx(float d) const { return wrapDelta(d, (float)width); }
    float wrapDy(float d) const { return wrapDelta(d, (float)height); }
    // Wrap a coordinate back into [0, span). Loop form so oversized excursions
    // (a patch radius larger than the world, a long probe) stay correct; every
    // step is an exact float add/sub, so this is portable bit-for-bit.
    static float wrapCoord(float v, float span) {
        while (v < 0.0f) v += span;
        while (v >= span) v -= span;
        return v;
    }

    void init(int w, int h, int numCreatures) {
        width = w;
        height = h;
        signals.init(w, h, 8, cfg.toroidal);
        creatureGrid_.init(w, h, cfg.perceptionRadius);
        foodGrid_.init(w, h, cfg.perceptionRadius);

        CurrentField::Mode cmode = (cfg.currentMode == 1) ? CurrentField::Mode::Gyre
                                                           : CurrentField::Mode::Eddies;
        current_.init(cmode, w, h, cfg.currentEddies, cfg.currentStrength,
                      cfg.currentCore, cfg.currentDrift, cfg.currentGyreEps);
        foodPatches_.clear();
        if (cfg.foodPatches > 0)
            for (int i = 0; i < cfg.foodPatches; ++i)
                foodPatches_.push_back({rng.range(0.0f, (float)w), rng.range(0.0f, (float)h)});

        creatures.clear();
        creatures.reserve(numCreatures * 2);
        for (int i = 0; i < numCreatures; ++i) {
            Vec2 pos = {rng.range(10.0f, (float)w - 10.0f),
                        rng.range(10.0f, (float)h - 10.0f)};
            creatures.push_back(makeRandomCreature(pos, cfg.genomeInitMin, cfg.genomeInitMax));
            markFounder(creatures.back());   // a new founder line
            // Body model: founders keep the default 1.0/1.0 and draw NOTHING,
            // even with cfg.bodyModel on. Body diversity is produced by the
            // per-insertion mutation, not by the spawn (see kernel::inheritFromPair).
        }

        // Predators: a fixed handful dropped at random positions with a random
        // heading. No genome / neural net (that is Stage C). The energy field is
        // seeded to predatorNewbornEnergy for Stage B; Stage A never reads it.
        predators.clear();
        for (int i = 0; i < cfg.predatorCount; ++i) {
            Predator p;
            p.pos = {rng.range(10.0f, (float)w - 10.0f),
                     rng.range(10.0f, (float)h - 10.0f)};
            const float a = rng.range(0.0f, 6.2832f);
            p.vel = {evomath::cosf(a), evomath::sinf(a)};
            p.energy = cfg.predatorNewbornEnergy;
            predators.push_back(p);
        }

        food.clear();
        for (int i = 0; i < cfg.targetFood; ++i) spawnFood();

        // Stage C: seed the predators' stream from ONE global draw, taken last,
        // so every draw above is exactly Stage B's at the same seed; then give
        // each spawned predator a founder's genome from that stream. Off: no
        // draw, nothing changes.
        if (cfg.predatorBrain) {
            predRng_.seed(rng.uint());
            for (Predator& p : predators) foundPredator(p, 'F');
        }
    }

    void spawnFood() {
        Food f;
        if (!foodPatches_.empty()) {
            // Cluster around a random patch centre, so spatial position matters
            // (a current that pushes a creature off a patch now costs it).
            const Vec2& c = foodPatches_[rng.uint((uint32_t)foodPatches_.size() - 1)];
            const float R = cfg.foodPatchRadius;
            if (cfg.toroidal) {
                // Border patches wrap instead of piling food on the edge line.
                // Same two rng draws as the clamped path (byte-identity off-flag).
                f.pos = { wrapCoord(c.x + rng.range(-R, R), (float)width),
                          wrapCoord(c.y + rng.range(-R, R), (float)height) };
            } else {
                f.pos = { std::clamp(c.x + rng.range(-R, R), 0.0f, (float)width),
                          std::clamp(c.y + rng.range(-R, R), 0.0f, (float)height) };
            }
        } else {
            f.pos = {rng.range(10.0f, (float)width - 10.0f),
                     rng.range(10.0f, (float)height - 10.0f)};
        }
        food.push_back(f);
    }

    void update(float dt) {
        using clk = std::chrono::steady_clock;
        const bool prof_ = cfg.profile;
        const auto tTotal0 = prof_ ? clk::now() : clk::time_point{};

        frame++;
        births = 0;
        deaths = 0;

        current_.advance(frame);  // refresh vortex centres before any queries

        // Drift food with the current (divergence-free => food stretches into
        // filaments rather than piling up). Done before the grid rebuild so the
        // spatial index reflects the new positions.
        if (cfg.foodDrift && current_.active()) {
            for (auto& f : food) {
                if (!f.alive) continue;
                Vec2 v = current_.velocityAt(f.pos);
                f.pos.x += v.x * dt;  f.pos.y += v.y * dt;
                if (f.pos.x < 0) f.pos.x += width;  else if (f.pos.x >= width)  f.pos.x -= width;
                if (f.pos.y < 0) f.pos.y += height; else if (f.pos.y >= height) f.pos.y -= height;
            }
        }

        // Food spawning with abundance cycles (from learning_boids)
        float foodRate = cfg.foodSpawnBase + cfg.foodSpawnAmp * evomath::sinf(frame * 0.001f);
        for (int i = 0; i < static_cast<int>(foodRate); ++i) {
            if (static_cast<int>(food.size()) < cfg.targetFood * 2) spawnFood();
        }

        // Decay pheromones
        if (frame % 3 == 0) signals.decay();

        // Rebuild spatial indices. The grids are members reused across frames:
        // clear() empties the buckets but keeps their capacity, so the steady
        // state performs no per-tick heap allocation (unlike the old QuadTrees,
        // which were new/delete-constructed every update).
        creatureGrid_.clear();
        foodGrid_.clear();

        int numCreatures = (int)creatures.size();
        int numFood = (int)food.size();

        const auto tBuild0 = prof_ ? clk::now() : clk::time_point{};
        hot_.resize(numCreatures);
        for (int i = 0; i < numCreatures; ++i) {
            hot_[i] = {creatures[i].pos, creatures[i].vel};
            if (creatures[i].alive) creatureGrid_.insert(creatures[i].pos, i);
        }
        for (int i = 0; i < numFood; ++i) {
            if (food[i].alive) foodGrid_.insert(food[i].pos, i);
        }
        creatureGrid_.build();
        foodGrid_.build();
        if (prof_) prof.buildNs += std::chrono::duration<double, std::nano>(clk::now() - tBuild0).count();

        // Per-creature pending actions (for thread safety)
        struct PendingActions {
            bool wantsSignal = false;
            Vec2 signalPos;
        };
        std::vector<PendingActions> pending(numCreatures);

        // Thread-summed CPU time for the three sub-steps inside the parallel loop
        // (reduction => safe across OpenMP threads; plain accumulation when serial).
        double gNs = 0, fNs = 0, mNs = 0;
        const auto tPar0 = prof_ ? clk::now() : clk::time_point{};

        // ============================================================
        // PARALLEL PHASE: sensors + neural net + movement
        // Each creature only modifies itself. Read-only on quadtrees.
        // ============================================================
        // One creature's step. It writes only creature i, pending[i], the
        // caller's scratch and the caller's three profiling sums, so any
        // partition of [0, numCreatures) across threads is race-free. Shared by
        // the serial, OpenMP and thread-pool paths below.
        auto stepCreature = [&](int i, SensorScratch& scratch,
                                double& gAcc, double& fAcc, double& mAcc) {
            Creature& c = creatures[i];
            if (!c.alive) return;

            std::chrono::steady_clock::time_point ta, tb, tc;
            if (prof_) ta = std::chrono::steady_clock::now();

            // Compute all sensors
            float sensors[NUM_SENSES];
            std::memset(sensors, 0, sizeof(sensors));
            computeSensors(c, i, creatureGrid_, foodGrid_, sensors, scratch);

            if (prof_) tb = std::chrono::steady_clock::now();

            // Feed through neural net
            float actions[NUM_ACTIONS];
            std::memset(actions, 0, sizeof(actions));
            feedForward(c.nnet, sensors, actions, cfg.fastTanh);

            if (prof_) tc = std::chrono::steady_clock::now();

            // Capture neural I/O for the live inspector, only when asked (off in
            // headless). Each creature writes its own buffers, so this is safe in
            // the parallel phase and never perturbs the dynamics.
            if (cfg.captureActivations) {
                std::memcpy(c.lastSensors, sensors, sizeof(sensors));
                std::memcpy(c.lastActions, actions, sizeof(actions));
            }

            // Apply responsiveness scaling
            float resp = c.responsiveness;

            // Tier-1 body model (body_model.hpp). A bigger body has a lower
            // speed ceiling; the std::max keeps lo <= hi for the std::clamp
            // calls below, because clamp with lo > hi is undefined behaviour and
            // a large enough bodySize would otherwise push the ceiling under
            // cfg.minSpeed. Computed unconditionally: with cfg.bodyModel off
            // every creature's bodySize is 1.0f, so speedFactor is exactly 1.0f,
            // cfg.maxSpeed * 1.0f is exactly cfg.maxSpeed, and the max() picks
            // it — bit-identical to the pre-0.23 expression (proved by the §6.1
            // fingerprint harness, not merely asserted here).
            const float effMax = std::max(cfg.minSpeed, cfg.maxSpeed * speedFactor(c));

          if (cfg.triangularMotion) {
            // --- Triangular action space: forward drive throttles turn authority ---
            // drive in [0,1] from MOVE_FORWARD; turn in [-1,1] from STEER_X. The
            // coupling turnEff = turn*(1-drive) is the whole point: a fast strike
            // (drive->1) cannot also turn, a reorient (drive->0) turns freely.
            float drive = std::clamp(0.5f * (actions[MOVE_FORWARD] + 1.0f), 0.0f, 1.0f);
            float turn  = actions[STEER_X];
            float turnEff = turn * (1.0f - drive) * resp;

            float theta = evomath::atan2f(c.vel.y, c.vel.x);
            // Body model: a longer body turns worse. The parenthesisation is
            // load-bearing — (maxTurnRate * turnFactor) is exactly maxTurnRate
            // when turnFactor is 1.0f, so the product with turnEff and dt keeps
            // the original association and the original bits.
            theta += turnEff * (cfg.maxTurnRate * turnFactor(c)) * dt;
            c.vel.x = evomath::cosf(theta);
            c.vel.y = evomath::sinf(theta);

            c.speed = std::clamp(cfg.minSpeed + drive * (effMax - cfg.minSpeed),
                                 cfg.minSpeed, effMax);

            c.lastMoveDir = c.vel;
            c.pos.x += c.vel.x * c.speed * dt;
            c.pos.y += c.vel.y * c.speed * dt;
          } else {
            // Movement actions (original decoupled model)
            float steerX = actions[STEER_X] * resp;
            float steerY = actions[STEER_Y] * resp;
            float moveFwd = actions[MOVE_FORWARD] * resp;
            float moveRnd = actions[MOVE_RANDOM] * resp;
            float speedAdj = actions[SPEED_ADJUST] * resp;

            c.vel.x += steerX * 3.0f * dt;
            c.vel.y += steerY * 3.0f * dt;

            auto fwd = c.forward();
            c.vel.x += fwd.x * moveFwd * 2.0f * dt;
            c.vel.y += fwd.y * moveFwd * 2.0f * dt;

            if (std::abs(moveRnd) > 0.5f) {
                c.vel.x += rng.range(-1.0f, 1.0f) * std::abs(moveRnd) * dt;
                c.vel.y += rng.range(-1.0f, 1.0f) * std::abs(moveRnd) * dt;
            }

            float vlen = std::sqrt(c.vel.x * c.vel.x + c.vel.y * c.vel.y);
            if (vlen > 0.001f) { c.vel.x /= vlen; c.vel.y /= vlen; }

            c.speed += speedAdj * 50.0f * dt;
            c.speed = std::clamp(c.speed, cfg.minSpeed, effMax);   // body model: size caps speed

            c.lastMoveDir = c.vel;

            c.pos.x += c.vel.x * c.speed * dt;
            c.pos.y += c.vel.y * c.speed * dt;
          }

            // Ocean current pushes the creature (read-only on the cached field).
            if (current_.active()) {
                Vec2 cur = current_.velocityAt(c.pos);
                c.pos.x += cur.x * dt;
                c.pos.y += cur.y * dt;
            }

            if (c.pos.x < 0) c.pos.x += width;
            if (c.pos.x >= width) c.pos.x -= width;
            if (c.pos.y < 0) c.pos.y += height;
            if (c.pos.y >= height) c.pos.y -= height;
            hot_[i] = {c.pos, c.vel};   // final for this step (see CreatureHot)

            c.updateBody();

            kernel::stepInternalState(c, actions, dt);
            kernel::stepMetabolism(c, cfg, dt);

            // Defer signal emission (shared grid, not thread-safe)
            if (actions[EMIT_SIGNAL0] > 0.0f) {
                pending[i].wantsSignal = true;
                pending[i].signalPos = c.pos;
            }

            if (prof_) {
                const auto td = std::chrono::steady_clock::now();
                gAcc += std::chrono::duration<double, std::nano>(tb - ta).count();
                fAcc += std::chrono::duration<double, std::nano>(tc - tb).count();
                mAcc += std::chrono::duration<double, std::nano>(td - tc).count();
            }
        };

#ifdef EVO_POOL_THREADS
        // Thread-pool path (the Emscripten pthreads build; thread_pool.hpp).
        // Same partition as the OpenMP schedule: dynamic chunks of 16.
        {
            evo_par::Pool& pool = evo_par::Pool::instance();
            const int T = pool.threads();
            if ((int)poolScratch_.size() < T) poolScratch_.resize(T);
            // Per-thread sums, one cache line apart so the threads don't
            // contend on them.
            struct alignas(64) Sums { double g = 0, f = 0, m = 0; };
            std::vector<Sums> sums((size_t)T);
            pool.run(numCreatures, 16, [&](int lo, int hi, int tid) {
                Sums& s = sums[(size_t)tid];
                for (int i = lo; i < hi; ++i) stepCreature(i, poolScratch_[(size_t)tid], s.g, s.f, s.m);
            });
            for (const Sums& s : sums) { gNs += s.g; fNs += s.f; mNs += s.m; }
        }
#else
        #ifdef USE_OPENMP
        #pragma omp parallel
        #endif
        {
        // Per-thread scratch: one set per thread under OpenMP, a single reused
        // set in the serial build. The spatial queries inside computeSensors
        // reuse these buffers instead of allocating per creature each tick.
        SensorScratch scratch;

        #ifdef USE_OPENMP
        #pragma omp for schedule(dynamic, 16) reduction(+:gNs,fNs,mNs)
        #endif
        for (int i = 0; i < numCreatures; ++i) stepCreature(i, scratch, gNs, fNs, mNs);
        } // end parallel region
#endif

        if (prof_) {
            prof.parWallNs += std::chrono::duration<double, std::nano>(clk::now() - tPar0).count();
            prof.gatherNs += gNs; prof.ffNs += fNs; prof.applyNs += mNs;
        }
        const auto tSerial0 = prof_ ? clk::now() : clk::time_point{};

        // ============================================================
        // SINGLE-THREADED PHASE: shared-state modifications
        // ============================================================
        std::vector<Creature> newborns;

        // Reused across the loop (this phase is single-threaded) so the
        // eat/interact neighbour queries don't allocate per creature.
        std::vector<int> nearbyFood;
        std::vector<int> nearby;

        for (int i = 0; i < numCreatures; ++i) {
            Creature& c = creatures[i];
            if (!c.alive) continue;

            // Process deferred signal emissions
            if (pending[i].wantsSignal) {
                signals.emit(pending[i].signalPos);
            }

            // Death check (split by cause for the deaths decomposition).
            if (const char cause = kernel::deathCause(c, cfg)) {
                recordDeath(c, cause);
                continue;
            }

            // Eat nearby food (modifies food[].alive)
            nearbyFood.clear();
            if (cfg.toroidal) foodGrid_.queryRadiusWrapped(c.pos, cfg.pickupRadius, nearbyFood);
            else              foodGrid_.queryRadius(c.pos, cfg.pickupRadius, nearbyFood);
            for (int fi : nearbyFood) {
                if (food[fi].alive) {
                    food[fi].alive = false;
                    c.foodReserves += cfg.foodEnergy;
                }
            }

            // Social interactions
            if (c.interactTimer <= 0.0f) {
                nearby.clear();
                if (cfg.toroidal) creatureGrid_.queryRadiusWrapped(c.pos, cfg.interactRadius, nearby);
                else              creatureGrid_.queryRadius(c.pos, cfg.interactRadius, nearby);
                for (int ni : nearby) {
                    if (ni == i) continue;
                    Creature& other = creatures[ni];
                    if (!other.alive || other.interactTimer > 0.0f) continue;

                    doInteraction(c, other, newborns);
                    c.interactTimer = cfg.interactCooldown;
                    other.interactTimer = cfg.interactCooldown;
                    break;
                }
            }
        }

        for (auto& baby : newborns) { baby.id = nextId_++; creatures.push_back(std::move(baby)); }

        // Predator hunt + (Stage B) energy economy. Runs AFTER prey have moved
        // (parallel phase) and after the prey single-threaded pass, while
        // creatureGrid_ indices still line up with `creatures` (the dead-removal
        // erase below would invalidate them). No-op when there are no predators.
        updatePredators(dt);
        // The predator floor (v0.26.0) runs even when the hunt was a no-op —
        // an extinct population is exactly the case it exists for. Gated here
        // so the default path makes no call and draws nothing.
        if (cfg.predatorEconomy && cfg.predatorMinPopulation > 0) refillPredators();

        creatures.erase(
            std::remove_if(creatures.begin(), creatures.end(),
                           [](const Creature& c) { return !c.alive; }),
            creatures.end());
        food.erase(
            std::remove_if(food.begin(), food.end(),
                           [](const Food& f) { return !f.alive; }),
            food.end());

        if ((int)creatures.size() < cfg.minPopulation) {
            int toAdd = cfg.minPopulation - (int)creatures.size();
            for (int j = 0; j < toAdd; ++j) {
                Vec2 pos = {rng.range(10.0f, (float)width - 10.0f),
                            rng.range(10.0f, (float)height - 10.0f)};
                creatures.push_back(makeRandomCreature(pos, cfg.genomeInitMin, cfg.genomeInitMax));
                markFounder(creatures.back());   // new founder line
                // Body model: a reseeded founder is 1.0/1.0 and draws nothing.
                // Deliberate — the reseed floor already acts as a pump for
                // random founders when a population is collapsing (§7.1), and
                // giving it extreme bodies too would make that worse.
            }
        }

        if (prof_) {
            prof.serialNs += std::chrono::duration<double, std::nano>(clk::now() - tSerial0).count();
            prof.totalNs  += std::chrono::duration<double, std::nano>(clk::now() - tTotal0).count();
            ++prof.steps;
        }
    }

    // --- read-only access to the current field (used by the renderer overlay) ---
    bool currentActive() const { return current_.active(); }
    Vec2 currentAt(Vec2 p) const { return current_.velocityAt(p); }

    // --- Checkpoint access (see checkpoint_io.hpp) ---
    // Both of these are seeded from the rng during init(), so a resumed run
    // cannot regenerate them — they have to be restored verbatim or the world
    // is subtly different (a different ocean, food patches in different places).
    std::vector<float> currentVortexState() const { return current_.vortexState(); }
    bool restoreCurrentVortexState(const std::vector<float>& v) { return current_.restoreVortexState(v); }
    const std::vector<Vec2>& foodPatches() const { return foodPatches_; }
    void restoreFoodPatches(std::vector<Vec2> p) { foodPatches_ = std::move(p); }

private:
    // Spatial indices, reused across frames (see update()).
    SpatialGrid creatureGrid_;
    SpatialGrid foodGrid_;
    std::vector<CreatureHot> hot_;  // pos/vel per creature index (see CreatureHot)
    CurrentField current_;          // ocean flow (off unless cfg.currentStrength>0)
    std::vector<Vec2> foodPatches_; // patch centres (empty => uniform food spawn)
#ifdef EVO_POOL_THREADS
    std::vector<SensorScratch> poolScratch_;  // one per pool thread, reused across steps
#endif

    // The scripted hunt + (Stage B) energy economy. For each predator: find the
    // nearest LIVING prey in its detection radius, steer toward it (else wander),
    // advance at predator cruise, and — if a prey is within the capture radius and
    // the predator is not digesting — kill it (instant capture) and start the
    // digestion cooldown. Runs single-threaded (a handful of predators), reading
    // the creature grid built earlier this frame.
    //
    // Stage A (cfg.predatorEconomy == false): no energy, no death, no births —
    // the block below collapses to exactly the original Stage A behaviour.
    // Stage B (cfg.predatorEconomy == true): each predator also ages, burns
    // metabolism + a kinetic move-cost, gains energy = the victim's reserves (or
    // a fixed --predator-meal) on a capture, buds a child above predatorReproEnergy
    // (paying predatorNewbornEnergy, so budding conserves energy), and dies below
    // 0 energy (starvation) or past predatorMaxAge (age). Newborns are appended and
    // the dead erased AFTER the loop (the prey remove_if pattern) so neither
    // invalidates the predator we're iterating.
    void updatePredators(float dt) {
        // Stage C replaces the scripted hunt below, which is otherwise unchanged.
        if (cfg.predatorBrain) { updateBrainPredators(dt); return; }
        if (predators.empty()) return;
        const bool  econ     = cfg.predatorEconomy;
        // Predator kinetic coefficient: reuse the prey --move-cost when <0.
        const float pmc      = (cfg.predatorMoveCost >= 0.0f) ? cfg.predatorMoveCost
                                                              : cfg.moveCost;
        // Each predator cruises at a fixed speed (Stage A/B) — cfg.predatorSpeed
        // times its speedFactor, which is 1.0 (the product is cfg.predatorSpeed
        // bit for bit) unless inheritance has varied it — so its per-second burn
        // is constant: fixed metabolism + the quadratic kinetic cost of that cruise.
        const float detect2  = cfg.predatorPerception * cfg.predatorPerception;
        const float capture2 = cfg.predatorCaptureRadius * cfg.predatorCaptureRadius;

        std::vector<Predator> newborns;   // budded this frame (appended after the loop)
        std::vector<int> near;
        for (Predator& p : predators) {
            const float speed    = cfg.predatorSpeed * p.speedFactor;
            const float burnRate = cfg.predatorMetabolism + pmc * speed * speed;
            p.digestTimer -= dt;
            if (econ) {
                p.age    += dt;
                p.energy -= burnRate * dt;   // metabolism + kinetic move-cost
            }

            // Nearest living prey within the detection radius.
            near.clear();
            if (cfg.toroidal) creatureGrid_.queryRadiusWrapped(p.pos, cfg.predatorPerception, near);
            else              creatureGrid_.queryRadius(p.pos, cfg.predatorPerception, near);
            int   bestIdx = -1;
            float bestD2  = detect2;
            for (int ci : near) {
                const Creature& prey = creatures[ci];
                if (!prey.alive) continue;
                float dx = prey.pos.x - p.pos.x;
                float dy = prey.pos.y - p.pos.y;
                if (cfg.toroidal) { dx = wrapDx(dx); dy = wrapDy(dy); }
                const float d2 = dx * dx + dy * dy;
                if (d2 < bestD2) { bestD2 = d2; bestIdx = ci; }
            }

            // Steer toward the target, or wander if none is in range.
            Vec2 dir = p.forward();
            if (bestIdx >= 0) {
                Vec2 toPrey = creatures[bestIdx].pos - p.pos;
                if (cfg.toroidal) toPrey = { wrapDx(toPrey.x), wrapDy(toPrey.y) };
                dir = normalized(toPrey);
            } else {
                const float jitter = rng.range(-0.3f, 0.3f);
                const float cs = evomath::cosf(jitter), sn = evomath::sinf(jitter);
                dir = {dir.x * cs - dir.y * sn, dir.x * sn + dir.y * cs};
            }
            p.vel = dir;

            // Advance at a fixed cruise speed. The current carries the predator
            // too, so phase 2 (current on) stays kinematically consistent.
            p.pos.x += dir.x * speed * dt;
            p.pos.y += dir.y * speed * dt;
            if (current_.active()) {
                const Vec2 cur = current_.velocityAt(p.pos);
                p.pos.x += cur.x * dt;
                p.pos.y += cur.y * dt;
            }
            if (p.pos.x < 0) p.pos.x += width;  else if (p.pos.x >= width)  p.pos.x -= width;
            if (p.pos.y < 0) p.pos.y += height; else if (p.pos.y >= height) p.pos.y -= height;

            // Capture: nearest prey within reach, predator not digesting.
            if (bestIdx >= 0 && p.digestTimer <= 0.0f && creatures[bestIdx].alive) {
                float dx = creatures[bestIdx].pos.x - p.pos.x;
                float dy = creatures[bestIdx].pos.y - p.pos.y;
                if (cfg.toroidal) { dx = wrapDx(dx); dy = wrapDy(dy); }
                if (dx * dx + dy * dy <= capture2) {
                    if (econ) {
                        // Carnivory is calorie-dense: absorb the victim's reserves
                        // (or a fixed meal when --predator-meal >= 0).
                        const float meal = (cfg.predatorMeal >= 0.0f)
                                           ? cfg.predatorMeal
                                           : creatures[bestIdx].foodReserves;
                        p.energy += meal;
                    }
                    recordDeath(creatures[bestIdx], 'p');
                    p.digestTimer = cfg.predatorCooldown;
                }
            }

            // Stage B life/death: starve, age out, or bud. (Order: a predator that
            // just ate may have crossed back above 0 this frame and survives; a
            // dying or aging predator does not reproduce this frame.)
            if (econ) {
                if (p.energy < 0.0f) {
                    p.alive = false;
                    totalPredatorDeathsStarvation++;
                } else if (cfg.predatorMaxAge > 0.0f && p.age >= cfg.predatorMaxAge) {
                    p.alive = false;
                    totalPredatorDeathsAge++;
                } else if (p.energy >= cfg.predatorReproEnergy * p.buddingFactor &&
                           // The predator ceiling (v0.26.0), counted exactly
                           // like the prey --max-pop: a predator at the cap
                           // keeps its energy and buds once there is room.
                           // 0 => no cap, and the test short-circuits.
                           (cfg.predatorMaxPopulation <= 0 ||
                            (int)predators.size() + (int)newborns.size() < cfg.predatorMaxPopulation)) {
                    Predator child;
                    // Place the child a hair off the parent with a random heading.
                    // (Toroidal: wrap instead of pinning the child to the wall;
                    // same rng draws either way.)
                    if (cfg.toroidal) {
                        child.pos = { wrapCoord(p.pos.x + rng.range(-8.0f, 8.0f), (float)width),
                                      wrapCoord(p.pos.y + rng.range(-8.0f, 8.0f), (float)height) };
                    } else {
                        child.pos = { std::clamp(p.pos.x + rng.range(-8.0f, 8.0f), 0.0f, (float)width  - 1.0f),
                                      std::clamp(p.pos.y + rng.range(-8.0f, 8.0f), 0.0f, (float)height - 1.0f) };
                    }
                    const float a = rng.range(0.0f, 6.2832f);
                    child.vel    = {evomath::cosf(a), evomath::sinf(a)};
                    child.energy = cfg.predatorNewbornEnergy;
                    p.energy    -= cfg.predatorNewbornEnergy;   // energy-conserving
                    child.generation = p.generation + 1;
                    // Heritable traits (v0.26.0). The random stream is defined
                    // here: draws ONLY under cfg.predatorInheritance, EXACTLY two
                    // per bud (speedFactor, then buddingFactor), each a single
                    // rng.range with no rejection, so the count never depends on
                    // the values — the same contract as the body model's two
                    // draws, and what keeps native and wasm bit-identical. They
                    // come after the bud's position and heading draws. Off, the
                    // child keeps 1.0/1.0 and the sequence is the 0.25.0 one.
                    if (cfg.predatorInheritance) {
                        const float m = cfg.predatorTraitMutation;
                        child.speedFactor   = std::clamp(p.speedFactor + rng.range(-m, m),
                                                         PRED_TRAIT_MIN, PRED_TRAIT_MAX);
                        child.buddingFactor = std::clamp(p.buddingFactor + rng.range(-m, m),
                                                         PRED_TRAIT_MIN, PRED_TRAIT_MAX);
                    }
                    newborns.push_back(child);
                    totalPredatorBirths++;
                }
            }
        }

        // Apply births and remove the dead (Stage B only; Stage A leaves the
        // predator vector untouched, so its size is constant as before).
        if (econ) {
            for (auto& baby : newborns) predators.push_back(std::move(baby));
            predators.erase(
                std::remove_if(predators.begin(), predators.end(),
                               [](const Predator& p) { return !p.alive; }),
                predators.end());
        }
    }

    // The predator floor (cfg.predatorMinPopulation, v0.26.0): the predators'
    // --min-pop. Called after updatePredators has applied births and removed the
    // dead, only with the economy on and the floor > 0. Each refilled predator
    // is a founder like the initial spawn: the same three draws in the same
    // order (x, y, heading), predatorNewbornEnergy, generation 0 and traits
    // 1.0/1.0 — with inheritance on, the floor is a steady source of baseline
    // traits, the predator analogue of the random founders the prey floor
    // injects (§7.1). Nothing is drawn unless the count is actually short.
    void refillPredators() {
        while ((int)predators.size() < cfg.predatorMinPopulation) {
            Predator p;
            p.pos = {rng.range(10.0f, (float)width - 10.0f),
                     rng.range(10.0f, (float)height - 10.0f)};
            const float a = rng.range(0.0f, 6.2832f);
            p.vel = {evomath::cosf(a), evomath::sinf(a)};
            p.energy = cfg.predatorNewbornEnergy;
            // Stage C: a refill is a random-genome founder of a new lineage,
            // from the predators' stream (the three draws above are unchanged).
            if (cfg.predatorBrain) foundPredator(p, 'R');
            predators.push_back(std::move(p));
            totalPredatorReseeds++;
        }
    }

    // ---- Stage C (cfg.predatorBrain): founders and the neural hunt ----------

    // A founder (initial spawn 'F', floor refill 'R'): a random genome (with
    // the pursuit primer if cfg.predatorPrimer) from predRng_, its network, a
    // fresh id that starts its own lineage, top speed. Position, heading,
    // energy and traits are the caller's (Stage B's draws).
    void foundPredator(Predator& p, char event) {
        p.genome = predbrain::founderGenome(cfg, predRng_);
        predbrain::buildNet(p.genome, p.nnet);
        p.id = nextPredatorId_++;
        p.lineageId = p.id;
        p.parentId = 0;
        p.speed = predbrain::topSpeed(p, cfg);
        p.captures = 0;
        notePredator(event, p);
    }

    // The neural hunt + the Stage B economy. Per predator, in vector order:
    //   1. sense: the 21 inputs (predator_brain.hpp). Prey from the creature
    //      grid at their moved positions (the scripted hunt's query); rivals
    //      from a snapshot of predator positions taken before the loop, so a
    //      predator's view does not depend on who moved first;
    //   2. think: the network (predbrain::feedForward);
    //   3. act: turn by TURN x predatorTurnRate x dt, speed += THRUST x 50 x dt
    //      within [predatorMinSpeed, predatorSpeed x speedFactor];
    //   4. economy: burn metabolism + move-cost x speed^2 at THIS speed (Stage
    //      B's formula, per step), so a slow predator saves energy;
    //   5. move (current and wrap as the scripted hunt);
    //   6. capture: the nearest living prey within the capture radius, if not
    //      digesting — Stage B's meal and cooldown;
    //   7. life cycle (economy only): starve, age out, or bud — Stage B's rules,
    //      cap and global-rng draws, plus the child's genome (inherited with a
    //      mutation) and network from predRng_.
    // Without the economy nothing ages, starves or buds and energy is inert: a
    // fixed, immortal population of neural hunters whose ENERGY and AGE read 0
    // (the frozen-newborn assay). With the economy and cfg.predatorFrozen (the
    // frozen assay) energy and age are accounted as usual but step 7 only holds
    // energy in [0, T] and age at most predatorMaxAge: no deaths, no buds.
    void updateBrainPredators(float dt) {
        if (predators.empty()) return;
        const bool  econ     = cfg.predatorEconomy;
        const bool  frozen   = econ && cfg.predatorFrozen;
        const float pmc      = (cfg.predatorMoveCost >= 0.0f) ? cfg.predatorMoveCost : cfg.moveCost;
        const float R        = cfg.predatorPerception;
        const float R2       = R * R;
        const float capture2 = cfg.predatorCaptureRadius * cfg.predatorCaptureRadius;
        // The prey list must also cover the capture disc after this step's
        // move (perception is 150 by default, far more than 14 + a step).
        const float queryR   = std::max(R, cfg.predatorCaptureRadius + 64.0f);

        const int n = (int)predators.size();
        std::vector<Vec2> snap((size_t)n);
        for (int i = 0; i < n; ++i) snap[(size_t)i] = predators[(size_t)i].pos;

        std::vector<Predator> newborns;
        std::vector<int> near;
        for (int pi = 0; pi < n; ++pi) {
            Predator& p = predators[(size_t)pi];
            const float top = predbrain::topSpeed(p, cfg);
            p.digestTimer -= dt;
            if (econ) p.age += dt;

            // 1. sense
            float s[NUM_PRED_SENSES];
            std::memset(s, 0, sizeof(s));
            const Vec2 fwd = p.forward();
            const Vec2 rht = {-fwd.y, fwd.x};

            near.clear();
            if (cfg.toroidal) creatureGrid_.queryRadiusWrapped(p.pos, queryR, near);
            else              creatureGrid_.queryRadius(p.pos, queryR, near);
            int   best = -1;
            float bestD2 = R2;
            Vec2  bestOff = {0.0f, 0.0f};
            int   count = 0;
            float sx = 0.0f, sy = 0.0f;
            for (int ci : near) {
                const Creature& prey = creatures[ci];
                if (!prey.alive) continue;
                float dx = prey.pos.x - p.pos.x;
                float dy = prey.pos.y - p.pos.y;
                if (cfg.toroidal) { dx = wrapDx(dx); dy = wrapDy(dy); }
                const float d2 = dx * dx + dy * dy;
                if (!(d2 < R2)) continue;
                ++count; sx += dx; sy += dy;
                if (d2 < bestD2) { bestD2 = d2; best = ci; bestOff = {dx, dy}; }
            }
            if (best >= 0) {
                const float d   = std::sqrt(bestD2);
                const float inv = (d > 1e-3f) ? 1.0f / d : 0.0f;
                const Vec2  u   = {bestOff.x * inv, bestOff.y * inv};   // toward the prey
                s[PS_PREY_FWD]  = u.x * fwd.x + u.y * fwd.y;
                s[PS_PREY_LR]   = u.x * rht.x + u.y * rht.y;
                s[PS_PREY_PROX] = 1.0f - d / R;
                const Vec2 h = creatures[best].forward();
                s[PS_PREY_HEAD_FWD] = h.x * fwd.x + h.y * fwd.y;
                s[PS_PREY_HEAD_LR]  = h.x * rht.x + h.y * rht.y;
                const float invN = 1.0f / (float)count;
                const float mx = sx * invN, my = sy * invN;
                s[PS_PREY_CENTROID_FWD] = evomath::tanhf((mx * fwd.x + my * fwd.y) / R);
                s[PS_PREY_CENTROID_LR]  = evomath::tanhf((mx * rht.x + my * rht.y) / R);
            }
            s[PS_PREY_COUNT] = tanhCountOver10(count);
            {
                int   rb = -1;
                float rd2 = R2;
                Vec2  ro = {0.0f, 0.0f};
                const Vec2 self = snap[(size_t)pi];
                for (int j = 0; j < n; ++j) {
                    if (j == pi) continue;
                    float dx = snap[(size_t)j].x - self.x;
                    float dy = snap[(size_t)j].y - self.y;
                    if (cfg.toroidal) { dx = wrapDx(dx); dy = wrapDy(dy); }
                    const float d2 = dx * dx + dy * dy;
                    if (d2 < rd2) { rd2 = d2; rb = j; ro = {dx, dy}; }
                }
                if (rb >= 0) {
                    const float d   = std::sqrt(rd2);
                    const float inv = (d > 1e-3f) ? 1.0f / d : 0.0f;
                    const Vec2  u   = {ro.x * inv, ro.y * inv};
                    s[PS_RIVAL_FWD]  = u.x * fwd.x + u.y * fwd.y;
                    s[PS_RIVAL_LR]   = u.x * rht.x + u.y * rht.y;
                    s[PS_RIVAL_PROX] = 1.0f - d / R;
                }
            }
            predbrain::writeOwnSensors(p, cfg, top, s);
            s[PS_SIGNAL]     = signals.read(p.pos);
            s[PS_SIGNAL_FWD] = signals.readInDir(p.pos, fwd) - signals.readInDir(p.pos, {-fwd.x, -fwd.y});
            s[PS_SIGNAL_LR]  = signals.readInDir(p.pos, rht) - signals.readInDir(p.pos, {-rht.x, -rht.y});
            if (current_.active()) {
                const Vec2 cur = current_.velocityAt(p.pos);
                s[PS_CURRENT_FWD] = evomath::tanhf((cur.x * fwd.x + cur.y * fwd.y) / 100.0f);
                s[PS_CURRENT_LR]  = evomath::tanhf((cur.x * rht.x + cur.y * rht.y) / 100.0f);
            }
            s[PS_RANDOM] = predRng_.range(-1.0f, 1.0f);

            // 2. think, 3. act
            float a[NUM_PRED_ACTIONS];
            predbrain::feedForward(p.nnet, s, a, cfg.fastTanh);
            const float turn = a[PA_TURN] * cfg.predatorTurnRate * dt;
            const float cs = evomath::cosf(turn), sn = evomath::sinf(turn);
            p.vel = {fwd.x * cs - fwd.y * sn, fwd.x * sn + fwd.y * cs};   // +turn rotates toward rht
            p.speed = std::clamp(p.speed + a[PA_THRUST] * predbrain::kThrustAccel * dt,
                                 cfg.predatorMinSpeed, top);

            // 4. economy: this step's burn at this step's speed
            if (econ) p.energy -= (cfg.predatorMetabolism + pmc * p.speed * p.speed) * dt;

            predTally_.predSteps++;
            predTally_.speedSum   += p.speed;
            predTally_.speedSqSum += (double)p.speed * p.speed;
            if (p.speed >= 0.95f * top) predTally_.topSteps++;
            if (best >= 0) { predTally_.pursuitSteps++; predTally_.alignSum += s[PS_PREY_FWD]; }

            // 5. move
            p.pos.x += p.vel.x * p.speed * dt;
            p.pos.y += p.vel.y * p.speed * dt;
            if (current_.active()) {
                const Vec2 cur = current_.velocityAt(p.pos);
                p.pos.x += cur.x * dt;
                p.pos.y += cur.y * dt;
            }
            if (p.pos.x < 0) p.pos.x += width;  else if (p.pos.x >= width)  p.pos.x -= width;
            if (p.pos.y < 0) p.pos.y += height; else if (p.pos.y >= height) p.pos.y -= height;

            // 6. capture
            if (p.digestTimer <= 0.0f) {
                int   cb  = -1;
                float cd2 = 0.0f;
                for (int ci : near) {
                    const Creature& prey = creatures[ci];
                    if (!prey.alive) continue;
                    float dx = prey.pos.x - p.pos.x;
                    float dy = prey.pos.y - p.pos.y;
                    if (cfg.toroidal) { dx = wrapDx(dx); dy = wrapDy(dy); }
                    const float d2 = dx * dx + dy * dy;
                    if (d2 <= capture2 && (cb < 0 || d2 < cd2)) { cb = ci; cd2 = d2; }
                }
                if (cb >= 0) {
                    if (econ) p.energy += (cfg.predatorMeal >= 0.0f) ? cfg.predatorMeal
                                                                      : creatures[cb].foodReserves;
                    recordDeath(creatures[cb], 'p');
                    p.digestTimer = cfg.predatorCooldown;
                    ++p.captures;
                    predTally_.captures++;
                }
            }

            // 7. life cycle (Stage B's order and draws)
            if (frozen) {
                // The frozen assay: the accounting above ran, nobody dies or buds.
                // No draws, so the population and both streams stay fixed.
                const float T = cfg.predatorReproEnergy * p.buddingFactor;
                p.energy = std::max(0.0f, std::min(p.energy, std::max(0.0f, T)));
                if (cfg.predatorMaxAge > 0.0f && p.age > cfg.predatorMaxAge) p.age = cfg.predatorMaxAge;
            } else if (econ) {
                if (p.energy < 0.0f) {
                    p.alive = false;
                    totalPredatorDeathsStarvation++;
                    notePredator('S', p);
                } else if (cfg.predatorMaxAge > 0.0f && p.age >= cfg.predatorMaxAge) {
                    p.alive = false;
                    totalPredatorDeathsAge++;
                    notePredator('A', p);
                } else if (p.energy >= cfg.predatorReproEnergy * p.buddingFactor &&
                           (cfg.predatorMaxPopulation <= 0 ||
                            (int)predators.size() + (int)newborns.size() < cfg.predatorMaxPopulation)) {
                    Predator child;
                    if (cfg.toroidal) {
                        child.pos = { wrapCoord(p.pos.x + rng.range(-8.0f, 8.0f), (float)width),
                                      wrapCoord(p.pos.y + rng.range(-8.0f, 8.0f), (float)height) };
                    } else {
                        child.pos = { std::clamp(p.pos.x + rng.range(-8.0f, 8.0f), 0.0f, (float)width  - 1.0f),
                                      std::clamp(p.pos.y + rng.range(-8.0f, 8.0f), 0.0f, (float)height - 1.0f) };
                    }
                    const float ang = rng.range(0.0f, 6.2832f);
                    child.vel    = {evomath::cosf(ang), evomath::sinf(ang)};
                    child.energy = cfg.predatorNewbornEnergy;
                    p.energy    -= cfg.predatorNewbornEnergy;   // energy-conserving
                    child.generation = p.generation + 1;
                    if (cfg.predatorInheritance) {
                        const float m = cfg.predatorTraitMutation;
                        child.speedFactor   = std::clamp(p.speedFactor + rng.range(-m, m),
                                                         PRED_TRAIT_MIN, PRED_TRAIT_MAX);
                        child.buddingFactor = std::clamp(p.buddingFactor + rng.range(-m, m),
                                                         PRED_TRAIT_MIN, PRED_TRAIT_MAX);
                    }
                    // the brain: the parent's genome with a mutation, from predRng_
                    predbrain::inheritGenome(child, p, cfg, predRng_);
                    predbrain::buildNet(child.genome, child.nnet);
                    child.id        = nextPredatorId_++;
                    child.lineageId = p.lineageId;
                    child.parentId  = p.id;
                    child.speed     = predbrain::topSpeed(child, cfg);
                    newborns.push_back(std::move(child));
                    totalPredatorBirths++;
                    notePredator('B', newborns.back());
                }
            }
        }

        if (econ) {
            for (auto& baby : newborns) predators.push_back(std::move(baby));
            predators.erase(
                std::remove_if(predators.begin(), predators.end(),
                               [](const Predator& p) { return !p.alive; }),
                predators.end());
        }
    }

    // A pairwise interaction. The vote, the share and fight outcomes, the
    // insertion preconditions and gate, and what a newborn inherits are the
    // kernel's (kernel.hpp); what is left here is where the child goes.
    void doInteraction(Creature& c1, Creature& c2, std::vector<Creature>& newborns) {
        switch (kernel::interactionVote(c1, c2)) {
        case kernel::Interaction::Share:
            kernel::shareReserves(c1, c2);
            break;
        case kernel::Interaction::Pair: {
            // The genetic gate (kernel::reproGatePasses) is the LAST conjunct on
            // purpose: it is the only expensive one, and every cheap
            // precondition (kernel::pairingAllowed) short-circuits ahead of it.
            // With the gate off it returns on one float compare, never folding
            // a genome and — critically — never drawing, so the rng sequence is
            // untouched.
            //
            // THE RANDOM STREAM IS DEFINED HERE, alongside the body-model draws
            // in kernel::inheritFromPair. Only the soft ramp
            // (cfg.reproSoftWidth > 0) draws, and then it draws exactly one
            // uniform per evaluation of this conjunct whatever the pair's
            // distance is; the hard gate, the grace bypass and the off-path draw
            // nothing at all, which is what keeps the v0.21/0.22 gated runs and
            // the whole default corpus byte-identical. Because the gate is the
            // last conjunct, reaching it means every other precondition already
            // held, so "gate passed" and "insertion happened" are the same event
            // and viaGrace/viaSoft can be counted inside the branch without a
            // second evaluation.
            //
            // Gating HERE rather than in the partner-selection loop is
            // deliberate: the caller consumes both creatures' interactTimer
            // regardless of what doInteraction decided, so a reproduction that
            // fails on insufficient energy already burns the cooldown. An
            // incompatible pair now behaves exactly like an under-energised
            // one, which introduces no new semantic. Skipping incompatible
            // partners in the candidate loop would be a different rule (it
            // would change iteration order as well); if that variant is ever
            // wanted it goes in as a separate flag and gets measured against
            // this one, not swapped in silently.
            bool viaGrace = false, viaSoft = false;
            if (kernel::pairingAllowed(c1, c2, cfg,
                                       (int)creatures.size() + (int)newborns.size()) &&
                kernel::reproGatePasses(c1, c2, cfg, viaGrace, viaSoft)) {
                kernel::payForPairing(c1, c2, cfg);
                newborns.push_back(makeChild(c1, c2, cfg.genomeMinLength,
                                             cfg.genomeMaxLength,
                                             cfg.mutationMultiplier,
                                             cfg.newbornEnergy));
                if (cfg.toroidal) {
                    // makeChild placed the newborn at the raw parent midpoint;
                    // for a seam-crossing pair that is mid-world. Re-place at
                    // the wrapped midpoint (the body trail follows via
                    // updateBody within a few frames; no rng involved).
                    Creature& baby = newborns.back();
                    Vec2 m = { wrapCoord(c1.pos.x + 0.5f * wrapDx(c2.pos.x - c1.pos.x), (float)width),
                               wrapCoord(c1.pos.y + 0.5f * wrapDy(c2.pos.y - c1.pos.y), (float)height) };
                    baby.pos = m;
                    for (int bi = 0; bi < Creature::BODY_LEN; ++bi)
                        baby.body[bi] = { m.x - baby.vel.x * bi * 4.0f,
                                          m.y - baby.vel.y * bi * 4.0f };
                }
                kernel::inheritFromPair(newborns.back(), c1, c2, cfg);
                recordPairing(c1, c2, viaGrace, viaSoft);
            }
            break;
        }
        case kernel::Interaction::Fight:
            kernel::fightOutcome(c1, c2);
            break;
        default: break;
        }
    }

    void computeSensors(const Creature& c, int selfIdx,
                        const SpatialGrid& creatureGrid, const SpatialGrid& foodGrid,
                        float sensors[], SensorScratch& scratch) {
        auto fwd = c.forward();
        const Vec2 rht = {-fwd.y, fwd.x};   // c.right(), without a second forward()

        // Position & boundaries. LOC_X/LOC_Y stay absolute position in both
        // modes (on the torus they are a discontinuous-but-informative
        // coordinate). The boundary sensors saturate to "no wall anywhere"
        // when the world wraps — a torus has no walls to sense.
        sensors[LOC_X] = c.pos.x / width;
        sensors[LOC_Y] = c.pos.y / height;
        if (cfg.toroidal) {
            sensors[BOUNDARY_DIST_X] = 1.0f;
            sensors[BOUNDARY_DIST_Y] = 1.0f;
            sensors[BOUNDARY_DIST] = 1.0f;
        } else {
            float bx = std::min(c.pos.x, (float)width - c.pos.x);
            float by = std::min(c.pos.y, (float)height - c.pos.y);
            sensors[BOUNDARY_DIST_X] = evomath::tanhf(bx / 100.0f);
            sensors[BOUNDARY_DIST_Y] = evomath::tanhf(by / 100.0f);
            // tanh is non-decreasing and min() returns one of its arguments,
            // so this is tanh(min(bx, by) / 100), bit for bit.
            sensors[BOUNDARY_DIST] = std::min(sensors[BOUNDARY_DIST_X], sensors[BOUNDARY_DIST_Y]);
        }

        // Own state (speed, age, reserves, oscillator, responsiveness: kernel)
        sensors[OWN_VEL_X] = c.vel.x;
        sensors[OWN_VEL_Y] = c.vel.y;
        sensors[LAST_MOVE_DIR_X] = c.lastMoveDir.x;
        sensors[LAST_MOVE_DIR_Y] = c.lastMoveDir.y;
        kernel::writeOwnStateSensors(c, cfg, sensors);

        // Neighbor queries (reuse scratch buffer instead of allocating)
        std::vector<int>& neighbors = scratch.neighbors;
        neighbors.clear();
        if (cfg.toroidal) creatureGrid.queryRadiusWrapped(c.pos, cfg.perceptionRadius, neighbors);
        else              creatureGrid.queryRadius(c.pos, cfg.perceptionRadius, neighbors);

        float avgDx = 0, avgDy = 0, avgHx = 0, avgHy = 0;
        float nearestDist = cfg.perceptionRadius;
        int nearestIdx = -1;
        int neighborCount = 0;
        // Whole counts, as ints: a float sum of +-1 is exact anyway, and the
        // ternaries below compile without the two branches per neighbour that
        // `if (dot > 0) += 1 else -= 1` cost (taken half the time at random).
        int popFwd = 0, popLR = 0;

        // One neighbour's contribution to the social percepts. Shared by both
        // paths below so the maths exists once; with cfg.maxNeighbors == 0 the
        // call order is exactly the old inline loop's, hence bit-identical.
        auto attendTo = [&](int ni, const CreatureHot& other, float dx, float dy, float dist) {
            avgDx += dx; avgDy += dy;
            avgHx += other.vel.x; avgHy += other.vel.y;

            float dotFwd = dx * fwd.x + dy * fwd.y;
            float dotLR = dx * rht.x + dy * rht.y;
            popFwd += (dotFwd > 0) ? 1 : -1;
            popLR  += (dotLR > 0) ? 1 : -1;

            if (dist < nearestDist) { nearestDist = dist; nearestIdx = ni; }
            neighborCount++;
        };

        // True crowding inside the radius, independent of the attention cap:
        // density is a percept in its own right (see SimConfig::maxNeighbors).
        int inRadiusCount = 0;

        if (cfg.maxNeighbors <= 0) {
            // Metric interaction: attend to everything in range (historical).
            // Every grid entry was alive when inserted and nothing in this phase
            // kills, so no alive test is needed.
            for (int ni : neighbors) {
                if (ni == selfIdx) continue;
                const CreatureHot& other = hot_[ni];

                float dx = other.pos.x - c.pos.x;
                float dy = other.pos.y - c.pos.y;
                if (cfg.toroidal) { dx = wrapDx(dx); dy = wrapDy(dy); }
                float dist = std::sqrt(dx * dx + dy * dy);
                attendTo(ni, other, dx, dy, dist);
            }
            inRadiusCount = neighborCount;
        } else {
            // Topological interaction: rank candidates by squared distance and
            // attend to the nearest N. Ordering by (distanceSq, index) is a
            // total order, so the selection is deterministic even when two
            // neighbours are exactly equidistant, and independent of the order
            // the spatial index happened to return candidates in.
            // Selection is by (distanceSq, index), a total order, so both the
            // chosen set and the order it is summed in are uniquely determined
            // — no dependence on library sort internals, which is what keeps a
            // run reproducible on another toolchain or under wasm.
            //
            // Kept in a small sorted stack array rather than a candidate list:
            // once it is full, a neighbour that is farther than the current
            // worst is rejected on a single comparison, and in a dense school
            // that is almost every one of them.
            const int keepMax = std::min(cfg.maxNeighbors, MAX_TOPOLOGICAL_NEIGHBORS);
            NeighborCandidate best[MAX_TOPOLOGICAL_NEIGHBORS];
            int have = 0;

            for (int ni : neighbors) {
                if (ni == selfIdx) continue;
                const CreatureHot& other = hot_[ni];   // grid entries are all alive
                ++inRadiusCount;

                float rawDx = other.pos.x - c.pos.x;
                float rawDy = other.pos.y - c.pos.y;
                if (cfg.toroidal) { rawDx = wrapDx(rawDx); rawDy = wrapDy(rawDy); }
                const float dx = rawDx;
                const float dy = rawDy;
                const float d2 = dx * dx + dy * dy;

                if (have == keepMax) {
                    const NeighborCandidate& worst = best[have - 1];
                    if (d2 > worst.distSq ||
                        (d2 == worst.distSq && ni > worst.index)) continue;
                }

                int at = (have < keepMax) ? have : have - 1;
                while (at > 0) {
                    const NeighborCandidate& prev = best[at - 1];
                    if (prev.distSq < d2 ||
                        (prev.distSq == d2 && prev.index < ni)) break;
                    best[at] = prev;
                    --at;
                }
                best[at] = { d2, dx, dy, ni };
                if (have < keepMax) ++have;
            }

            for (int j = 0; j < have; ++j) {
                attendTo(best[j].index, hot_[best[j].index],
                         best[j].dx, best[j].dy, std::sqrt(best[j].distSq));
            }
        }

        if (neighborCount > 0) {
            avgDx /= neighborCount; avgDy /= neighborCount;
            avgHx /= neighborCount; avgHy /= neighborCount;
        }

        sensors[NEIGHBOR_COUNT] = tanhCountOver10(inRadiusCount);
        sensors[AVG_NEIGHBOR_DX] = evomath::tanhf(avgDx / cfg.perceptionRadius);
        sensors[AVG_NEIGHBOR_DY] = evomath::tanhf(avgDy / cfg.perceptionRadius);
        sensors[AVG_NEIGHBOR_HEADING_X] = avgHx;
        sensors[AVG_NEIGHBOR_HEADING_Y] = avgHy;
        sensors[NEAREST_NEIGHBOR_DIST] = nearestDist / cfg.perceptionRadius;
        sensors[POPULATION_DENSITY] = tanhCountOver15(inRadiusCount);
        sensors[POPULATION_FWD] = tanhCountOver5(popFwd);
        sensors[POPULATION_LR] = tanhCountOver5(popLR);

        // Nearest neighbor attributes
        if (nearestIdx >= 0) {
            const Creature& nearest = creatures[nearestIdx];
            const float sim = kernel::writeNearestSensors(c, nearest, sensors);
            float dx = nearest.pos.x - c.pos.x;
            float dy = nearest.pos.y - c.pos.y;
            if (cfg.toroidal) { dx = wrapDx(dx); dy = wrapDy(dy); }
            float dotFwd = dx * fwd.x + dy * fwd.y;
            sensors[GENETIC_SIM_FWD] = (dotFwd > 0) ? sim : 0.5f;
        } else {
            kernel::clearNearestSensors(sensors);
            sensors[GENETIC_SIM_FWD] = 0.5f;
        }

        // Food sensors. Food neither moves nor dies in this phase, so a grid
        // entry's stored position IS the food's position: visit the entries in
        // the order queryRadius would list them, without the index list or a
        // second read of food[]. (Wrapped offsets still go through wrapDx, as
        // before — not through the image query's shifted centre, which rounds
        // differently.)
        float foodDx = 0, foodDy = 0, foodDist = cfg.perceptionRadius;
        int foodCount = 0;
        auto smell = [&](int, Vec2 fp) {
            ++foodCount;
            float dx = fp.x - c.pos.x;
            float dy = fp.y - c.pos.y;
            if (cfg.toroidal) { dx = wrapDx(dx); dy = wrapDy(dy); }
            float dist = std::sqrt(dx * dx + dy * dy);
            if (dist < foodDist) {
                foodDist = dist;
                float invD = (dist > 0.001f) ? 1.0f / dist : 0.0f;
                foodDx = dx * invD;
                foodDy = dy * invD;
            }
        };
        if (cfg.toroidal) foodGrid.forEachInRadiusWrapped(c.pos, cfg.perceptionRadius, smell);
        else              foodGrid.forEachInRadius(c.pos, cfg.perceptionRadius, smell);
        sensors[NEAREST_FOOD_DX] = foodDx;
        sensors[NEAREST_FOOD_DY] = foodDy;
        sensors[NEAREST_FOOD_DIST] = foodDist / cfg.perceptionRadius;
        sensors[FOOD_DENSITY] = tanhCountOver10(foodCount);

        // Pheromone sensors
        sensors[SIGNAL0] = signals.read(c.pos);
        sensors[SIGNAL0_FWD] = signals.readInDir(c.pos, fwd) - signals.readInDir(c.pos, {-fwd.x, -fwd.y});
        sensors[SIGNAL0_LR] = signals.readInDir(c.pos, rht) - signals.readInDir(c.pos, {-rht.x, -rht.y});

        // Current / flow sensors — local flow projected onto the creature's own
        // forward and right axes (0 everywhere when currents are disabled).
        if (current_.active()) {
            Vec2 cur = current_.velocityAt(c.pos);
            sensors[CURRENT_FWD] = evomath::tanhf((cur.x * fwd.x + cur.y * fwd.y) / 100.0f);
            sensors[CURRENT_LR]  = evomath::tanhf((cur.x * rht.x + cur.y * rht.y) / 100.0f);
        } else {
            // Still water: the flow is {0, 0}, so each product above is a zero
            // carrying the axis component's sign, their sum is -0 only when
            // both are, and tanh keeps it. Same bits, without the two calls
            // (the inspector shows the sign).
            sensors[CURRENT_FWD] = (std::signbit(fwd.x) && std::signbit(fwd.y)) ? -0.0f : 0.0f;
            sensors[CURRENT_LR]  = (std::signbit(rht.x) && std::signbit(rht.y)) ? -0.0f : 0.0f;
        }

        // Predator threat sensors — nearest predator within the prey's OWN
        // perception radius (the predator's larger detection radius is the ambush
        // asymmetry, handled on the predator side). Bearing is relative to heading;
        // proximity ramps 0 (at the perception edge / none) -> 1 (on contact).
        {
            float bestD2 = cfg.perceptionRadius * cfg.perceptionRadius;
            Vec2  off    = {0.0f, 0.0f};
            bool  seen   = false;
            for (const Predator& p : predators) {
                float dx = p.pos.x - c.pos.x;
                float dy = p.pos.y - c.pos.y;
                if (cfg.toroidal) { dx = wrapDx(dx); dy = wrapDy(dy); }
                const float d2 = dx * dx + dy * dy;
                if (d2 < bestD2) { bestD2 = d2; off = {dx, dy}; seen = true; }
            }
            if (seen) {
                const float d    = std::sqrt(bestD2);
                const float invD = (d > 1e-3f) ? 1.0f / d : 0.0f;
                const Vec2  u    = {off.x * invD, off.y * invD};  // unit vector TOWARD predator
                sensors[PREDATOR_FWD]  = u.x * fwd.x + u.y * fwd.y;
                sensors[PREDATOR_LR]   = u.x * rht.x + u.y * rht.y;
                sensors[PREDATOR_PROX] = 1.0f - d / cfg.perceptionRadius;
            } else {
                sensors[PREDATOR_FWD]  = 0.0f;
                sensors[PREDATOR_LR]   = 0.0f;
                sensors[PREDATOR_PROX] = 0.0f;
            }
        }

        // Long probe: only the count is a percept, so count, don't collect.
        int probeCount;
        Vec2 probePos = {c.pos.x + fwd.x * LONGPROBE_DIST, c.pos.y + fwd.y * LONGPROBE_DIST};
        if (cfg.toroidal) {
            // A probe cast past the seam looks into the far side of the world
            // instead of going blind off-plane.
            probePos = { wrapCoord(probePos.x, (float)width),
                         wrapCoord(probePos.y, (float)height) };
            probeCount = creatureGrid.countRadiusWrapped(probePos, 30.0f);
        } else {
            probeCount = creatureGrid.countRadius(probePos, 30.0f);
        }
        sensors[LONGPROBE_POP_FWD] = tanhCountOver5(probeCount);

        // Random
        sensors[RANDOM_SENSOR] = rng.range(-1.0f, 1.0f);
    }
};

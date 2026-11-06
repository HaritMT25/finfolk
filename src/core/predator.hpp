#pragma once
#include <cmath>
#include <cstdint>
#include "vec2.hpp"
#include "genome.hpp"   // Genome, NeuralNet: the Stage C brain (predator_brain.hpp)

// Range of the heritable predator traits (v0.26.0), the same band as the prey
// body parameters (body_model.hpp): a trait at the edge has halved or doubled
// the configured value it multiplies, and inheritance clamps into it.
inline constexpr float PRED_TRAIT_MIN = 0.5f;
inline constexpr float PRED_TRAIT_MAX = 2.0f;

// ============================================================
// Predator — a scripted hunter (no genome / neural net; that is Stage C).
//
//   * Stage A (cfg.predatorEconomy == false): immortal, fixed-count. It never
//     starves and never reproduces, so the ONLY thing under test is the chase
//     kinematics — predator speed vs prey speed, capture radius, and the
//     digestion cooldown. The energy/age fields below are simply unused.
//   * Stage B (cfg.predatorEconomy == true): the energy economy turns on. A
//     predator gains `energy` by capturing prey, burns metabolism + a kinetic
//     move-cost each second, reproduces above a threshold and starves below 0
//     (and optionally ages out). predator_pop becomes time-varying, giving the
//     coupled (Lotka-Volterra-ish) oscillator — see evo_boids context §9/§11.
//   * Stage B additions (v0.26.0, both opt-in, both off by default):
//     cfg.predatorMinPopulation refills the economy up to a floor with fresh
//     scripted predators, and cfg.predatorInheritance lets a bud inherit its
//     parent's two traits below with a mutation. Two heritable numbers, not a
//     genome.
//   * Stage C (v0.27.0, cfg.predatorBrain, off by default): the hunt is a
//     network built from a genome (predator_brain.hpp), a bud carries a copied,
//     mutated genome, and the fields at the end of this struct are live. With
//     the brain off they keep their defaults and nothing reads them. With the
//     brain on and the economy off, the predators are immortal and fixed in
//     number (the "frozen" assay mode): they hunt by their networks but never
//     bud, so nothing evolves.
//
// The hunt + the economy (nearest-prey query, steering, capture, burn, birth,
// death) live in World::updatePredators so they can reuse the creature spatial
// grid and the world's bookkeeping; this struct only holds the per-predator
// state that the hunt advances.
// ============================================================
struct Predator {
    Vec2  pos;
    Vec2  vel = {1.0f, 0.0f};  // heading (kept ~unit; speed is cfg.predatorSpeed)
    float digestTimer = 0.0f;  // seconds until it can capture again (>0 => digesting)

    // --- Stage B energy economy (only read/written when cfg.predatorEconomy) ---
    float energy = 0.0f;       // food energy; <0 => starves. Seeded to
                               // cfg.predatorNewbornEnergy at birth/spawn.
    float age    = 0.0f;       // seconds alive; only matters if predatorMaxAge>0.
    bool  alive  = true;       // cleared on death; the dead are erased after the
                               // hunt loop (mirrors the prey remove_if).

    // --- Heritable traits (v0.26.0; only varied when cfg.predatorInheritance) ---
    // Multipliers on the configured values. At the default 1.0 each product is
    // the configured float bit for bit, so a world with inheritance off runs
    // exactly as before. A bud copies its parent's traits plus one uniform
    // mutation draw each (World::updatePredators); a spawned or floor-refilled
    // predator starts at 1.0/1.0.
    float speedFactor   = 1.0f;   // x cfg.predatorSpeed. Faster catches more and
                                  // burns more: the kinetic cost is quadratic.
    float buddingFactor = 1.0f;   // x cfg.predatorReproEnergy. Lower buds sooner
                                  // and leaves the parent a thinner reserve.
    std::uint32_t generation = 0; // buds since a spawned/refilled founder. Counted
                                  // with inheritance off too (no rng involved).

    // --- Stage C brain (v0.27.0; only set and read when cfg.predatorBrain) ---
    // Appended after every older field, so no brace-initialiser moves.
    Genome    genome;            // the predator's own I/O space (predator_brain.hpp)
    NeuralNet nnet;              // built from genome; neurons[].output is live state
    std::uint64_t id        = 0; // WorldCommon::nextPredatorId_ (a namespace of its
                                 // own, apart from the prey ids); 0 = unassigned
    std::uint64_t lineageId = 0; // the founder's id: own id for a founder, else the parent's
    std::uint64_t parentId  = 0; // the budding parent's id; 0 for a founder / transplant
    float speed             = 0.0f;  // current speed (the THRUST action integrates it)
    std::uint32_t captures  = 0;     // prey caught in this predator's life
    std::uint64_t sourceId  = 0;     // a transplanted predator's id in its SOURCE checkpoint
                                     // (another id namespace; transplant.hpp); 0 otherwise
    std::uint32_t virtualBuds = 0;   // the frozen assay's buds that made no child
                                     // (cfg.predatorFrozen): a per-predator fitness readout

    // Forward unit vector (mirrors Creature::forward()).
    Vec2 forward() const {
        const float len = std::sqrt(vel.x * vel.x + vel.y * vel.y);
        if (len < 1e-3f) return {1.0f, 0.0f};
        return {vel.x / len, vel.y / len};
    }
};

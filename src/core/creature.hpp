#pragma once
#include <cmath>
#include "vec2.hpp"
#include "agent_core.hpp"
#include "kernel.hpp"

// A creature in the 2-D world: the geometry-free AgentCore (identity, energy,
// timers, body parameters, genome and network) plus where it is and which way
// it faces. Every AgentCore field is reached as before (c.genome, c.age).
struct Creature : AgentCore {
    Vec2 pos;
    Vec2 vel;
    Vec2 lastMoveDir = {1.0f, 0.0f}; // biosim4: last movement direction

    // Visual (geometry only — no rendering dependency)
    static constexpr int BODY_LEN = 6;
    Vec2 body[BODY_LEN];

    void init(Vec2 startPos) {
        pos = startPos;
        vel = {rng.range(-1.0f, 1.0f), rng.range(-1.0f, 1.0f)};
        float len = std::sqrt(vel.x * vel.x + vel.y * vel.y);
        if (len > 0.001f) { vel.x /= len; vel.y /= len; }
        lastMoveDir = vel;

        // The oscillator phase draw, the network and the colour. After the
        // heading's two draws, as always (see AgentCore::initCore).
        initCore();

        for (int i = 0; i < BODY_LEN; ++i) {
            body[i] = {pos.x - vel.x * i * 4.0f, pos.y - vel.y * i * 4.0f};
        }
    }

    // Forward direction unit vector
    Vec2 forward() const {
        float len = std::sqrt(vel.x * vel.x + vel.y * vel.y);
        if (len < 0.001f) return {1.0f, 0.0f};
        return {vel.x / len, vel.y / len};
    }

    // Right-perpendicular direction
    Vec2 right() const {
        auto fwd = forward();
        return {-fwd.y, fwd.x};
    }

    void updateBody() {
        body[0] = pos;
        for (int i = 1; i < BODY_LEN; ++i) {
            float dx = body[i].x - body[i - 1].x;
            float dy = body[i].y - body[i - 1].y;
            float dist = std::sqrt(dx * dx + dy * dy);
            // Visual only — body[] feeds the renderer and the checkpoint, and no
            // sensor reads it. A bigger/longer creature draws a longer trail.
            // At the defaults this is 4.0f * 1.0f * 1.0f, which IEEE-754
            // evaluates to exactly 4.0f, so the off-path geometry is unchanged.
            // (Creature::init()'s initial spacing stays a flat 4.0f: the body
            // parameters are assigned after construction, and updateBody catches
            // the trail up on the next step.)
            float segLen = 4.0f * bodySize * bodyElong;
            if (dist > segLen) {
                float ratio = segLen / dist;
                body[i].x = body[i - 1].x + dx * ratio;
                body[i].y = body[i - 1].y + dy * ratio;
            }
        }
    }
};

inline Creature makeRandomCreature(Vec2 pos,
                                   int initMin = GENOME_INITIAL_MIN,
                                   int initMax = GENOME_INITIAL_MAX) {
    Creature c;
    c.genome = makeRandomGenome(initMin, initMax);
    c.init(pos);
    return c;
}

inline Creature makeChild(const Creature& p1, const Creature& p2,
                          int   minLen        = GENOME_MIN_LENGTH,
                          int   maxLen        = GENOME_MAX_LENGTH,
                          float mutMultiplier = 1.0f,
                          float newbornEnergy = 25.0f,
                          WeightMutationMode mode = WeightMutationMode::Legacy) {
    Creature child;
    kernel::inheritGenome(child, p1, p2, minLen, maxLen, mutMultiplier, mode);

    Vec2 midpoint = {
        (p1.pos.x + p2.pos.x) * 0.5f,
        (p1.pos.y + p2.pos.y) * 0.5f
    };
    child.init(midpoint);
    child.foodReserves = newbornEnergy;
    return child;
}

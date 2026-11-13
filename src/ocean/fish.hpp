#pragma once
// ----------------------------------------------------------------------------
// Fish — a creature in the Ocean world: the geometry-free AgentCore plus a
// horizontal position and heading exactly like Classic's Creature (x, y on the
// wrapping plane), a depth in [0, D] (0 = surface; clamped, not wrapped), a
// vertical "pitch" vz (depth changes at vz·speed per second) and the heritable
// neutral-buoyancy depth bodyBuoy (as a fraction of D). bodyBuoy lives here,
// not in AgentCore, so Classic's struct is untouched (PLAN_ecosystem §14.1).
//
// init / forward / updateBody are Creature's (creature.hpp), with depth added.
// ----------------------------------------------------------------------------
#ifndef EVO_WORLD_OCEAN
#error "fish.hpp is the Ocean build's creature: compile with -DEVO_WORLD_OCEAN"
#endif
#include <algorithm>
#include <cmath>
#include "../core/vec2.hpp"
#include "../core/agent_core.hpp"
#include "../core/kernel.hpp"

struct Fish : AgentCore {
    Vec2 pos;
    Vec2 vel;                         // horizontal heading, kept unit length
    Vec2 lastMoveDir = {1.0f, 0.0f};
    float depth    = 0.0f;            // 0 = surface ... D = floor
    float vz       = 0.0f;            // pitch: + = diving
    float bodyBuoy = 0.5f;            // neutral depth / D, in [0, 1]

    static constexpr int BODY_LEN = 6;
    Vec2 body[BODY_LEN];

    // Creature::init plus a depth: the heading's two draws, then the kernel's
    // oscillator draw, network and colour. A fresh fish starts level (vz = 0).
    void init(Vec2 startPos, float startDepth) {
        pos = startPos;
        depth = startDepth;
        vz = 0.0f;
        vel = {rng.range(-1.0f, 1.0f), rng.range(-1.0f, 1.0f)};
        float len = std::sqrt(vel.x * vel.x + vel.y * vel.y);
        if (len > 0.001f) { vel.x /= len; vel.y /= len; }
        lastMoveDir = vel;
        initCore();
        for (int i = 0; i < BODY_LEN; ++i)
            body[i] = {pos.x - vel.x * i * 4.0f, pos.y - vel.y * i * 4.0f};
    }

    Vec2 forward() const {
        float len = std::sqrt(vel.x * vel.x + vel.y * vel.y);
        if (len < 0.001f) return {1.0f, 0.0f};
        return {vel.x / len, vel.y / len};
    }

    // The spine trails the head in (x, y) only; the whole fish draws at `depth`.
    void updateBody() {
        body[0] = pos;
        for (int i = 1; i < BODY_LEN; ++i) {
            float dx = body[i].x - body[i - 1].x;
            float dy = body[i].y - body[i - 1].y;
            float dist = std::sqrt(dx * dx + dy * dy);
            float segLen = 4.0f * bodySize * bodyElong;
            if (dist > segLen) {
                float ratio = segLen / dist;
                body[i].x = body[i - 1].x + dx * ratio;
                body[i].y = body[i - 1].y + dy * ratio;
            }
        }
    }
};

// A founder: random genome, then init. bodyBuoy = depth / D (it starts neutral
// where it was dropped).
inline Fish makeRandomFish(Vec2 pos, float depth, float D, int initMin, int initMax) {
    Fish f;
    f.genome = makeRandomGenome(initMin, initMax);
    f.init(pos, depth);
    f.bodyBuoy = std::clamp(depth / D, 0.0f, 1.0f);
    return f;
}

// A child's genome (kernel) and placement: the parents' (x, y) midpoint — the
// world re-places it on the torus — and their midpoint depth. bodyBuoy is the
// world's to draw, AFTER kernel::inheritFromPair (OceanWorld::doInteraction).
inline Fish makeChildFish(const Fish& p1, const Fish& p2, int minLen, int maxLen,
                          float mutMultiplier, float newbornEnergy,
                          WeightMutationMode mode = WeightMutationMode::Legacy) {
    Fish child;
    kernel::inheritGenome(child, p1, p2, minLen, maxLen, mutMultiplier, mode);
    const Vec2 midpoint = {(p1.pos.x + p2.pos.x) * 0.5f, (p1.pos.y + p2.pos.y) * 0.5f};
    child.init(midpoint, (p1.depth + p2.depth) * 0.5f);
    child.foodReserves = newbornEnergy;
    return child;
}

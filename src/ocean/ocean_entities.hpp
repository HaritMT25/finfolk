#pragma once
#include "../core/predator.hpp"

struct OceanFood {
    Vec2  pos;
    float depth = 0.0f;
    bool  alive = true;
    float size  = 1.0f;   // E1: what mouthGate compares with kMouth·bodySize (always 1
                          // until E2 sizes the particles)
    float age   = 0.0f;   // seconds since it appeared (counted only with OceanConfig::foodLife > 0)
#ifdef EVO_OCEAN_EYE
    float eyeCon = 0.0f;  // what the eye sees: glow − ambient light at its depth (set at
                          // spawn, and again whenever the E1 flow moves it in depth)
#endif
};

struct OceanPredator : Predator {
    float depth = 0.0f;
    float pitch = 0.0f;   // wander: depth rate / speed, in [-0.3, 0.3]
};

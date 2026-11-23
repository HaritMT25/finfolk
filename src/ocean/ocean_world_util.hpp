#pragma once

    // How many of an object's floats are not finite: the floats
    // tools/ocean_fingerprint.hpp countNonFinite scans for each kind.
    inline long OceanWorld::nonFiniteFloats(const Fish& c) {
        long n = 0;
        auto f = [&](float v) { n += !std::isfinite(v); };
        for (float v : {c.speed, c.age, c.foodReserves, c.reproTimer, c.interactTimer, c.responsiveness,
                        c.oscPeriod, c.oscPhase, c.bodySize, c.bodyElong, c.pos.x, c.pos.y, c.vel.x, c.vel.y,
                        c.lastMoveDir.x, c.lastMoveDir.y, c.depth, c.vz, c.bodyBuoy})
            f(v);
        for (const Vec2& b : c.body) { f(b.x); f(b.y); }
        for (const auto& nr : c.nnet.neurons) f(nr.output);
        for (float s : c.lastSensors) f(s);
        for (float a : c.lastActions) f(a);
        return n;
    }
    inline long OceanWorld::nonFiniteFloats(const OceanFood& fd) {
        long n = 0;
        for (float v : {fd.pos.x, fd.pos.y, fd.depth, fd.size, fd.age}) n += !std::isfinite(v);
#ifdef EVO_OCEAN_EYE
        n += !std::isfinite(fd.eyeCon);
#endif
        return n;
    }
    inline long OceanWorld::nonFiniteFloats(const OceanPredator& p) {
        long n = 0;
        for (float v : {p.pos.x, p.pos.y, p.vel.x, p.vel.y, p.digestTimer, p.energy, p.age, p.speedFactor,
                        p.buddingFactor, p.depth, p.pitch})
            n += !std::isfinite(v);
        return n;
    }
    // The end-of-step erases' predicate: dead, and its non-finite floats counted.
    template <class T>
    bool OceanWorld::removedDead(const T& o) {
        if (o.alive) return false;
        totalNonFiniteRemoved += nonFiniteFloats(o);
        return true;
    }

    // Every radius this world queries or tests with must be finite and >= 0,
    // and so must its square: each one is used squared (R², the pickup,
    // interaction, detection and capture radii², the grid's r²), and a radius
    // of 2^64 (about 1.8e19) or more squares to an infinite float. (With
    // R² = inf an empty eye sector, d² = inf, passed d² <= R² and read
    // PROX = 1 − inf/R = −inf.) With R² finite every object the eye bins has a
    // finite d² <= R², so all 18 eye inputs are finite. (Every accepted config
    // is also held to radii <= 1e6 by oceanSimConfigError, the int-cast bound;
    // this square test is radiusError's own guarantee, whoever calls it.)
    // In a toroidal world each one must also be < min(w, h) / 2: that is the
    // bound SpatialGrid::queryRadiusWrapped / forEachInRadiusWrapped assume
    // (spatial_grid.hpp) — a wider disk overlaps its own image across the seam
    // and lists the same entity twice. Capture is a minimum-image distance
    // test, not a grid query, and is held to the same bound. Returns "" when a
    // w x h world fits them all, else why not.
    inline std::string OceanWorld::radiusError(const SimConfig& c, int w, int h) {
        const struct { const char* name; float r; } radii[] = {
            {"perceptionRadius", c.perceptionRadius},
            {"interactRadius", c.interactRadius},
            {"pickupRadius", c.pickupRadius},
            {"predatorPerception", c.predatorPerception},
            {"predatorCaptureRadius", c.predatorCaptureRadius},
            {"the long probe radius", LONGPROBE_RADIUS},
        };
        for (const auto& e : radii) {
            if (!std::isfinite(e.r) || e.r < 0.0f)
                return std::string(e.name) + " must be finite and >= 0";
            if (!std::isfinite(e.r * e.r))
                return std::string(e.name) + " " + std::to_string(e.r) +
                       " is too large: its square overflows a float (keep it below 1.8e19)";
            if (c.toroidal && !(2.0f * e.r < (float)std::min(w, h)))
                return std::string(e.name) + " " + std::to_string(e.r) +
                       " needs a toroidal world wider and taller than twice it (got " +
                       std::to_string(w) + " x " + std::to_string(h) + ")";
        }
        return "";
    }

    inline float OceanWorld::wrapDelta(float d, float span) {
        const float half = 0.5f * span;
        if (d > half) return d - span;
        if (d < -half) return d + span;
        return d;
    }
    inline float OceanWorld::wrapDx(float d) const { return wrapDelta(d, (float)width); }
    inline float OceanWorld::wrapDy(float d) const { return wrapDelta(d, (float)height); }

    // Mean and SD of the live fish's depth, and the fraction per depth eighth
    // (surface first). Read-only.
    inline void OceanWorld::depthStats(double& mean, double& sd, double hist[ocean::kDepthBins]) const {
        for (int b = 0; b < ocean::kDepthBins; ++b) hist[b] = 0.0;
        double s = 0.0, s2 = 0.0;
        long n = 0;
        for (const Fish& c : creatures) {
            if (!c.alive) continue;
            const double z = c.depth;
            s += z; s2 += z * z; ++n;
            int b = (int)(z / D * ocean::kDepthBins);
            hist[std::clamp(b, 0, ocean::kDepthBins - 1)] += 1.0;
        }
        mean = n ? s / n : 0.0;
        sd = n ? std::sqrt(std::max(0.0, s2 / n - mean * mean)) : 0.0;
        if (n) for (int b = 0; b < ocean::kDepthBins; ++b) hist[b] /= (double)n;
    }

    // Squared 3-D distance; (x, y) by minimum image when the senses wrap.
    inline float OceanWorld::dist2(Vec2 a, float za, Vec2 b, float zb) const {
        float dx = b.x - a.x, dy = b.y - a.y;
        if (cfg.toroidal) { dx = wrapDx(dx); dy = wrapDy(dy); }
        const float dz = zb - za;
        return dx * dx + dy * dy + dz * dz;
    }

#pragma once

#ifdef EVO_OCEAN_EYE
    // The step's looks, before the per-fish phase: every fish's size and
    // contrast (stepFish refreshes its own after it moves, as hot_ does), and
    // every predator's contrast (predators move after the per-fish phase).
    inline void OceanWorld::eyePrepare() {
        for (std::size_t i = 0; i < creatures.size(); ++i) {
            hot_[i].eyeSize = ocean::kEyeFishLen * creatures[i].bodySize;
            hot_[i].eyeCon  = ocean::eyeContrast(ocean::kEyeFishBright, hot_[i].depth);
        }
        predCon_.resize(predators.size());
        for (std::size_t k = 0; k < predators.size(); ++k)
            predCon_[k] = ocean::eyeContrast(ocean::kEyePredBright, predators[k].depth);
    }

    // An offset's sector: the dominant axis of (dx, dy, dz) in the level frame
    // (fwd, rht, depth; pitch ignored, see the header comment).
    inline int OceanWorld::eyeSector(Vec2 fwd, Vec2 rht, float dx, float dy, float dz) {
        const float a = dx * fwd.x + dy * fwd.y;   // + ahead
        const float b = dx * rht.x + dy * rht.y;   // + right (as PREDATOR_LR)
        const float aa = std::abs(a), ab = std::abs(b), az = std::abs(dz);
        // (A branch-free form of this pick — selects for the sector and for the
        // nearest-so-far update — gives the same bits but measured no faster:
        // +1-2 points of step time natively, +4-7 under wasm; 2026-10-27.)
        if (aa >= ab && aa >= az) return (a >= 0.0f) ? 0 : 1;    // ahead / behind
        if (ab >= az)             return (b <= 0.0f) ? 2 : 3;    // left / right
        return (dz <= 0.0f) ? 4 : 5;                             // up (shallower) / down
    }

    // One object at offset (dx, dy, dz), d2 = its squared distance (<= R²),
    // world size `size`, contrast `con` (b − L). Nearest mode: it replaces its
    // sector's object if strictly nearer (ties: the first seen, so the result
    // follows the deterministic visit order).
    inline void OceanWorld::eyeSee(EyeBin* eye, Vec2 fwd, Vec2 rht, float dx, float dy, float dz, float d2,
                       float size, float con, float /*R*/) {
        EyeBin& e = eye[eyeSector(fwd, rht, dx, dy, dz)];
        if (d2 < e.d2) { e.d2 = d2; e.size = size; e.con = con; }
    }
    // Summed sectors (eyeCode bit 2): it adds to its sector's sums, in visit order.
    inline void OceanWorld::eyeSee(EyeSum* eye, Vec2 fwd, Vec2 rht, float dx, float dy, float dz, float d2,
                       float size, float con, float R) {
        EyeSum& e = eye[eyeSector(fwd, rht, dx, dy, dz)];
        const float d = std::sqrt(d2);
        const float p = 1.0f - d / R;
        e.prox += p;
        e.size += size / (size + d);
        e.con  += p * con;
    }

    inline void OceanWorld::eyeInit(EyeBin* eye) {
        for (int k = 0; k < ocean::kEyeSectors; ++k) eye[k] = {std::numeric_limits<float>::infinity(), 0.0f, 0.0f};
    }
    inline void OceanWorld::eyeInit(EyeSum* eye) {
        for (int k = 0; k < ocean::kEyeSectors; ++k) eye[k] = {0.0f, 0.0f, 0.0f};
    }

    // eyeCode bit 1, last: left / right and up / down as sum and difference.
    inline void OceanWorld::eyeOpponent(float sensors[]) {
        float* s = sensors + ocean::kEyeFirst;
        for (int pair = 2; pair <= 4; pair += 2)        // sectors (2 left, 3 right), (4 up, 5 down)
            for (int f = 0; f < 3; ++f) {
                const float lo = s[3 * pair + f], hi = s[3 * pair + 3 + f];
                s[3 * pair + f]     = lo + hi;          // LEFT = left + right, UP = up + down
                s[3 * pair + 3 + f] = hi - lo;          // RIGHT = right − left, DOWN = down − up
            }
    }

    inline void OceanWorld::eyeWrite(const EyeBin* eye, float R, int code, float sensors[]) {
        const float R2 = R * R;
        for (int k = 0; k < ocean::kEyeSectors; ++k) {
            float* s = sensors + ocean::kEyeFirst + 3 * k;
            const EyeBin& e = eye[k];
            if (!(e.d2 <= R2)) { s[0] = s[1] = s[2] = 0.0f; continue; }   // empty sector
            const float d = std::sqrt(e.d2);
            s[0] = 1.0f - d / R;            // proximity
            s[1] = e.size / (e.size + d);   // apparent size s/d, squashed: x / (1 + x)
            s[2] = (code & kEyeCodeFaded) ? s[0] * e.con   // contrast, faded by proximity
                                          : e.con;         // brightness contrast
        }
        if (code & kEyeCodeOpponent) eyeOpponent(sensors);
    }
    inline float OceanWorld::eyeSquash(float x) { return x / (1.0f + std::abs(x)); }
    inline void OceanWorld::eyeWrite(const EyeSum* eye, float /*R*/, int code, float sensors[]) {
        for (int k = 0; k < ocean::kEyeSectors; ++k) {
            float* s = sensors + ocean::kEyeFirst + 3 * k;
            const EyeSum& e = eye[k];       // an empty sector's sums are 0 and squash to 0
            s[0] = eyeSquash(e.prox);
            s[1] = eyeSquash(e.size);
            s[2] = eyeSquash(e.con);        // always faded (bit 0 adds nothing)
        }
        if (code & kEyeCodeOpponent) eyeOpponent(sensors);
    }
#endif

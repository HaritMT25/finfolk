#pragma once

    // ---- glass walls: movement, contact, placement (no draws) --------------
    // The side-wall soft turn (fish and predators): inside sideWallBand of a
    // side face (each band capped at half the side), a heading h that points
    // toward the wall(s) (h · a < 0, a = the inward push (p_W(x), p_H(y)),
    // p_L(q) = max(0, 1 − q/b) − max(0, 1 − (L − q)/b)) turns toward a / |a| by
    // at most sideWallTurnRate · max(|p_W|, |p_H|) · dt (portable atan2 / sin /
    // cos); head-on (exactly π away), the positive way. Speed is not touched.
    // "Toward the wall" grows with the depth into the band, d = max(|p_W|,
    // |p_H|) (0 at its inner edge, 1 at the glass): the heading must point
    // INWARD by at least d (h · a/|a| >= d), so a fish deep in the band turns
    // back into the tank instead of settling parallel to the glass. (Turning
    // only while h · a < 0, the design's first rule, left every heading just
    // parallel to the glass: in the Big tank 52-60% of the fish cruised in the
    // 80-unit band — 11% of the area — within 2000-4000 steps, with the
    // interior's food uneaten; the Gemini Argon q17 "wall highway".)
    inline void OceanWorld::wallAvoid(Vec2 p, Vec2& h, float dt) const {
        auto push = [](float q, float L, float b) {
            if (!(b > 0.0f)) return 0.0f;
            return std::max(0.0f, 1.0f - q / b) - std::max(0.0f, 1.0f - (L - q) / b);
        };
        const float W = (float)width, H = (float)height;
        const float ax = push(p.x, W, std::min(ocfg.sideWallBand, 0.5f * W));
        const float ay = push(p.y, H, std::min(ocfg.sideWallBand, 0.5f * H));
        if (ax == 0.0f && ay == 0.0f) return;
        const float depth = std::max(std::abs(ax), std::abs(ay));
        if (h.x * ax + h.y * ay >= depth * std::sqrt(ax * ax + ay * ay)) return;   // inward enough for this depth
        const float maxStep = ocfg.sideWallTurnRate * depth * dt;
        if (!(maxStep > 0.0f)) return;
        const float th = evomath::atan2f(h.y, h.x), ta = evomath::atan2f(ay, ax);
        float dl = ta - th;
        if (dl > kPiF) dl -= 2.0f * kPiF;
        else if (dl <= -kPiF) dl += 2.0f * kPiF;   // (−π, π]: head-on turns positively
        const float step = (std::abs(dl) <= maxStep) ? dl : (dl > 0.0f ? maxStep : -maxStep);
        const float nt = th + step;
        h = {evomath::cosf(nt), evomath::sinf(nt)};
    }
    // Contact with the side glass: the point clamped into [0, W] x [0, H] and
    // an outward heading component reflected (a face reached, or touched while
    // pointing out); x and y each, a corner both. A reflection negates one
    // component, so |h| is unchanged. True if it touched.
    inline bool OceanWorld::wallContact(Vec2& p, Vec2& h) const {
        const float W = (float)width, H = (float)height;
        bool hit = false;
        if (p.x <= 0.0f)   { p.x = 0.0f; if (h.x < 0.0f) h.x = -h.x; hit = true; }
        else if (p.x >= W) { p.x = W;    if (h.x > 0.0f) h.x = -h.x; hit = true; }
        if (p.y <= 0.0f)   { p.y = 0.0f; if (h.y < 0.0f) h.y = -h.y; hit = true; }
        else if (p.y >= H) { p.y = H;    if (h.y > 0.0f) h.y = -h.y; hit = true; }
        return hit;
    }
    // The body trail held inside the glass (founders and newborns are laid out
    // behind the head, which can reach past a face; a trail point is otherwise
    // a convex combination of points inside).
    inline void OceanWorld::containBody(Fish& c) const {
        for (Vec2& b : c.body) {
            b.x = std::clamp(b.x, 0.0f, (float)width);
            b.y = std::clamp(b.y, 0.0f, (float)height);
        }
    }
    // A patch coordinate inside the tank: uniform over [c − R, c + R] ∩
    // [inset, L − inset], inset = min(1, L/4), with the one draw the open
    // world makes; an empty intersection (a narrow patch beyond the inset)
    // gives the nearest inset point, after the same draw.
    inline float OceanWorld::wallPatchDraw(float c, float R, float L) {
        const float inset = std::min(1.0f, 0.25f * L);
        const float lo = std::max(c - R, inset), hi = std::min(c + R, L - inset);
        if (lo <= hi) return rng.range(lo, hi);
        (void)rng.range(0.0f, 1.0f);
        return std::clamp(c, inset, L - inset);
    }

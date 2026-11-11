#pragma once
// ocean_walls_tests.hpp — unit checks for the glass walls (OceanConfig::walls,
// sideWallBand, sideWallTurnRate; the walls_bigtank design), included by
// tests/ocean_tests.cpp inside namespace ot after its helpers. Each block
// prints one ok / FAIL line (its notes the measured numbers):
//   walls_config  the contract: defaults off; omitted == walls false == false
//                 with the default knobs (every section, 300 steps); walls on
//                 at init draws what walls off draws; walls + toroidal refused
//                 by oc_init (world and rng kept), the harness's buildConfigs
//                 and the probe; the side knobs' ranges and the bool's
//                 strictness; oc_set_param refuses every walls key (restart
//                 only), world and rng kept; oc_walls_enabled
//   wall_flow     the wall-compatible flow in six worlds (the E1 preset at
//                 1920 x 1080 and in the Big tank 3840 x 2160, strong eddies,
//                 a deep double gyre, D 10 with band 1 and waves 100, 100 x
//                 100): central-difference divergence of each wave pair, their
//                 sum, the current and the whole flow (normalised residual
//                 < 1e-3; absolute < 1e-3 /s at the two preset scales) in the
//                 bulk, along the side glass, in the corners and in the depth
//                 bands; EXACTLY zero normal flow on all six faces, tables and
//                 formulas, each part and the sum; tables vs formulas per pair;
//                 the current where the taper is 1 == the open world's, bit for
//                 bit; the look: the pairs' orbit ellipticity and RMS speed vs
//                 the periodic trains
//   wall_contain  fixtures: a fish on each face / corner pointing out, a
//                 head-on approach (band 80 and 0, both motion models), every
//                 heading reflected inward, speed kept, |v| = 1; extreme worlds
//                 (speed 2000, 100 eddies at 1000, waves 100, band 0,
//                 predators) keep every fish, trail point, food item and
//                 predator inside, every step, finite
//   wall_place    patch food (radius 0 / 300, patch depths, spread 400) inside
//                 [inset, L − inset] with the open world's draws, no pile-up on
//                 the inset; a predator budding at a corner mirror-folded
//                 inside, the same draws as open
//   wall_transport uniform tracers in a strong wall flow: the time-averaged
//                 share in each 5% face band stays 5% (no accumulation or
//                 depletion at the glass, surface or floor); every tracer
//                 inside; finer substeps converge (n = 1, 2, 4 vs 8)
//   wall_waves_off with walls and waves off, both per-train readers give exact
//                 zeros at the faces, corners and inside, before the trains were
//                 ever prepared and after the waves ran and stopped; reading them
//                 changes neither the world nor the rng
//   wall_eddy     a stationary eddy (cores 1-120, currentStrength 6-1000, up to
//                 577 substeps needed): the substep budget's fallback (16 of the
//                 needed size, food lagging), tracers keep their radius over 600
//                 frames, a uniform disk stays uniform, the drift converges in n;
//                 the old cap's blow-up as the contrast
//   wall_sense    no opposite-wall pickup, pairing or capture
//   wall_draws    150 steps with walls (fish in the bands and on the glass,
//                 predators wandering at the walls, food drifting): per-step
//                 draws == N + 3 x MOVE_RANDOM + 2 x predators

#ifndef OCEAN_TESTS_NO_SHIM
void testWallsConfig() {
    Test t("walls_config");
    {
        const OceanConfig d;
        t.expect(!d.walls && d.sideWallBand == 80.0f && d.sideWallTurnRate == 6.0f && oceanWallsAtDefaults(d),
                 "defaults: walls %d, band %g, turn rate %g", (int)d.walls, (double)d.sideWallBand, (double)d.sideWallTurnRate);
    }
    // Omitted == walls false == walls false with the default knobs: every section, every 50 steps.
    {
        const std::string base = R"({"currentStrength":60,"foodDrift":true,"predatorCount":3,"waveSpeed":6,"deepCurrent":true)";
        const std::string cfgs[3] = {base + "}", base + R"(,"walls":false})", base + R"(,"walls":false,"sideWallBand":80,"sideWallTurnRate":6})"};
        std::vector<ofp::Fingerprint> fp[3];
        for (int k = 0; k < 3; ++k) {
            OceanWorld w;
            std::string err;
            if (!t.expect(ofp::initWorld(w, 2101, 1920, 1080, 240.0f, 200, cfgs[k].c_str(), err), "%s: %s", cfgs[k].c_str(), err.c_str()))
                continue;
            for (int s = 0; s <= 300; ++s) {
                if (s) w.update(0.016f);
                if (s % 50 == 0) fp[k].push_back(ofp::fingerprint(w));
            }
        }
        t.expect(fp[0].size() == 7 && fp[0] == fp[1] && fp[0] == fp[2], "walls omitted / false / false with default knobs: fingerprints differ");
    }
    // Walls on at init draws exactly what walls off draws (founders, predators, patches, food).
    {
        OceanWorld a, b;
        std::string err;
        const bool ok = ofp::initWorld(a, 2102, 1920, 1080, 240.0f, 300, R"({"foodPatches":6,"foodDepthMode":1,"predatorCount":4})", err) &&
                        ofp::initWorld(b, 2102, 1920, 1080, 240.0f, 300, R"({"foodPatches":6,"foodDepthMode":1,"predatorCount":4,"walls":true})", err);
        const ofp::Fingerprint fa = ofp::fingerprint(a), fb = ofp::fingerprint(b);
        t.expect(ok && fa.rng == fb.rng && fa.cfg != fb.cfg, "init with walls: rng %s, cfg %s (want the same rng, another cfg)",
                 fa.rng == fb.rng ? "same" : "DIFFERENT", fa.cfg != fb.cfg ? "differs" : "SAME");
    }
    // Walls + toroidal: refused at every entry point; a refused oc_init keeps the world and the rng.
    {
        const char* bad = R"({"walls":true,"toroidal":true})";
        SimConfig sc;
        OceanConfig oc;
        std::string err;
        t.expect(!ofp::buildConfigs(bad, 240.0f, sc, oc, err) && err.find("toroidal=false") != std::string::npos,
                 "buildConfigs: %s", err.c_str());
        OceanWorld pw;
        const std::string pe = probeInitWorld(pw, 1, 1920, 1080, 240.0, 10, false, bad);
        t.expect(pe.find("toroidal=false") != std::string::npos, "probe: '%s'", pe.c_str());
        {
            const int rc = oc_init(2103, 1920, 1080, 240.0, 50, nullptr);
            t.expect(rc == 1, "oc_init: %s", oc_last_error());
        }
        oc_step(20);
        const ofp::Fingerprint kept = ofp::fingerprint(*g_world);
        const RandomGen r0 = rng;
        {
            const int rc = oc_init(2104, 1920, 1080, 240.0, 50, bad);
            const std::string e = oc_last_error();
            t.expect(rc == 0 && e.find("toroidal=false") != std::string::npos, "oc_init %s: rc %d (%s)", bad, rc, e.c_str());
        }
        for (const char* c : {R"({"walls":true,"sideWallBand":-1})", R"({"sideWallBand":100001})", R"({"sideWallBand":1e39})",
                              R"({"walls":true,"sideWallTurnRate":-0.5})", R"({"sideWallTurnRate":1001})", R"({"sideWallTurnRate":1e39})",
                              R"({"walls":"yes"})", R"({"walls":2})", R"({"walls":true,"walls":0.5})", R"({"walls":null})",
                              R"({"toroidal":true,"walls":1})"}) {
            const int rc = oc_init(2105, 1920, 1080, 240.0, 50, c);
            t.expect(rc == 0, "%s accepted", c);
        }
        t.expect(ofp::fingerprint(*g_world) == kept && sameEngine(r0, rng), "a refused oc_init changed the world or the rng");
        for (const char* c : {R"({"walls":true,"sideWallBand":0,"sideWallTurnRate":0})",
                              R"({"walls":1,"sideWallBand":100000,"sideWallTurnRate":1000})", R"({"walls":true,"toroidal":false})"}) {
            const int rc = oc_init(2106, 1920, 1080, 240.0, 50, c);
            if (!t.expect(rc == 1 && oc_walls_enabled() == 1, "%s: rc %d (%s), walls %d", c, rc, oc_last_error(), oc_walls_enabled())) continue;
            oc_step(100);
            t.expect(ofp::countNonFinite(*g_world) == 0, "%s: non-finite after 100 steps", c);
        }
    }
    // Restart only: oc_set_param refuses every walls key (on or off, the same value too), world and rng kept.
    for (int on = 0; on < 2; ++on) {
        const int rc = oc_init(2107, 1920, 1080, 240.0, 50, on ? R"({"walls":true})" : nullptr);
        t.expect(rc == 1 && oc_walls_enabled() == on, "oc_init walls %d: rc %d, oc_walls_enabled %d", on, rc, oc_walls_enabled());
        oc_step(10);
        const ofp::Fingerprint kept = ofp::fingerprint(*g_world);
        const RandomGen r0 = rng;
        struct S { const char* k; double v; };
        for (const S& s : {S{"walls", 0}, S{"walls", 1}, S{"sideWallBand", 80}, S{"sideWallBand", 40}, S{"sideWallTurnRate", 6},
                           S{"sideWallTurnRate", 3}, S{"toroidal", 1}}) {
            const int r = oc_set_param(s.k, s.v);
            const std::string e = oc_last_error();
            t.expect(r == 0 && (std::strcmp(s.k, "toroidal") == 0 || e.find("restart") != std::string::npos),
                     "walls %d: oc_set_param(%s, %g): rc %d (%s)", on, s.k, s.v, r, e.c_str());
        }
        t.expect(ofp::fingerprint(*g_world) == kept && sameEngine(r0, rng), "walls %d: a refused oc_set_param changed the world", on);
    }
    // The one restart-only policy (ocean_config.hpp oceanRestartOnlyError), which
    // the harness's --set shares (wasm/ocean_parity.sh runs every r_live_* case
    // through both drivers too): the walls keys always, appearance unless unchanged.
    {
        OceanConfig oc;
        oc.appearance = 1;
        for (const char* k : {"walls", "sideWallBand", "sideWallTurnRate"})
            for (double v : {0.0, 1.0, 80.0, 6.0})
                t.expect(oceanRestartOnlyError(k, v, oc).find("restart") != std::string::npos, "oceanRestartOnlyError(%s, %g) allowed", k, v);
        t.expect(oceanRestartOnlyError("appearance", 1.0, oc).empty() && !oceanRestartOnlyError("appearance", 0.0, oc).empty() &&
                     !oceanRestartOnlyError("appearance", std::nan(""), oc).empty(),
                 "oceanRestartOnlyError: appearance's no-op / change");
        for (const char* k : {"maxSpeed", "waveSpeed", "toroidal", "wallBand"})
            t.expect(oceanRestartOnlyError(k, 1.0, oc).empty(), "oceanRestartOnlyError(%s) refused a key it does not own", k);
    }
    // The tank's size is oc_init's (the page's width / height go there, never
    // into the cfg): the Big tank's size is the world's, a refused size keeps
    // it, oc_reset rebuilds it, and a size key inside the cfg changes nothing.
    {
        int rc = oc_init(2109, 3840, 2160, 240.0, 30, R"({"walls":true})");
        t.expect(rc == 1 && oc_width() == 3840 && oc_height() == 2160, "oc_init 3840 x 2160: rc %d, world %d x %d", rc, oc_width(),
                 oc_height());
        oc_step(5);
        struct Sz { int w, h; };
        for (const Sz b : {Sz{99, 2160}, Sz{3840, 100001}, Sz{0, 0}}) {
            rc = oc_init(2110, b.w, b.h, 240.0, 30, R"({"walls":true})");
            t.expect(rc == 0 && oc_width() == 3840 && oc_height() == 2160, "a refused %d x %d: rc %d, world now %d x %d", b.w, b.h, rc,
                     oc_width(), oc_height());
        }
        rc = oc_reset();
        t.expect(rc == 1 && oc_width() == 3840 && oc_height() == 2160, "oc_reset: rc %d, world %d x %d", rc, oc_width(), oc_height());
        // width / height as cfg keys: oc_init's size rules either way (accepted: its arguments' size; refused: the world kept)
        rc = oc_init(2111, 1920, 1080, 240.0, 30, R"({"walls":true,"width":3840,"height":2160})");
        const bool sized = rc == 1 ? (oc_width() == 1920 && oc_height() == 1080) : (oc_width() == 3840 && oc_height() == 2160);
        t.expect(sized, "width / height in the cfg: rc %d, world %d x %d", rc, oc_width(), oc_height());
        t.note("the size is oc_init's: 3840 x 2160 kept through refused sizes and oc_reset; width / height in the cfg %s",
               rc == 1 ? "ignored (the arguments' 1920 x 1080)" : "refused (the world kept)");
    }
    {
        const int rc = oc_init(2108, 1920, 1080, 240.0, 10, nullptr);
        t.expect(rc == 1 && oc_walls_enabled() == 0, "oc_init: %s", oc_last_error());
    }
}
#endif

// divergenceAt with the spacing actually stepped, (float)(x + h) − (float)(x − h),
// not 2h: at x ~ 3000 a float's spacing is 2.4e-4, so ±h is not exact there,
// and the Big tank's probes measured the coordinates' rounding.
template <class F>
void divergenceAtW(F&& f, Vec2 p, float d, float h, double& div, double& sumAbs) {
    const float xp = p.x + h, xm = p.x - h, yp = p.y + h, ym = p.y - h, dp = d + h, dm = d - h;
    const OceanWorld::Flow a = f(Vec2{xp, p.y}, d), b = f(Vec2{xm, p.y}, d);
    const OceanWorld::Flow c = f(Vec2{p.x, yp}, d), e = f(Vec2{p.x, ym}, d);
    const OceanWorld::Flow g = f(p, dp), k = f(p, dm);
    const double ax = ((double)a.x - (double)b.x) / ((double)xp - (double)xm);
    const double ay = ((double)c.y - (double)e.y) / ((double)yp - (double)ym);
    const double ad = ((double)g.d - (double)k.d) / ((double)dp - (double)dm);
    div = ax + ay + ad;
    sumAbs = std::abs(ax) + std::abs(ay) + std::abs(ad);
}

// The wall flow: divergence, faces, tables, interior identity, the look.
void testWallFlow() {
    Test t("wall_flow");
    using Fl = OceanWorld::Flow;
    struct WC { const char* name; int W, H; float D; const char* cfg; bool preset; };
    const char* kPresetWalls = R"({"walls":true,"waveSpeed":6,"deepCurrent":true,"currentStrength":5,"foodDrift":true})";
    const WC wc[] = {
        {"preset 1920x1080", 1920, 1080, 240.0f, kPresetWalls, true},
        {"preset Big tank 3840x2160", 3840, 2160, 240.0f, kPresetWalls, true},
        {"8 eddies x 120 core 60 + waves 12", 1920, 1080, 240.0f, R"({"walls":true,"waveSpeed":12,"currentStrength":120,"currentEddies":8,"currentCore":60})", false},
        {"deep gyre eps .4 + waves 5", 1920, 1080, 240.0f, R"({"walls":true,"waveSpeed":5,"deepCurrent":true,"currentStrength":40,"currentMode":1,"currentGyreEps":0.4})", false},
        {"D 10 band 1 waves 100 + eddies 80", 1920, 1080, 10.0f, R"({"walls":true,"waveSpeed":100,"waveBand":1,"waveGravity":10000,"currentStrength":80})", false},
        {"100x100 D 600", 100, 100, 600.0f, R"({"walls":true,"waveSpeed":20,"currentStrength":50,"currentCore":30})", false},
    };
    auto same = [](float a, float b) { std::uint32_t x, y; std::memcpy(&x, &a, 4); std::memcpy(&y, &b, 4); return x == y; };
    for (const WC& v : wc) {
        OceanWorld w;
        std::string err;
        if (!t.expect(ofp::initWorld(w, 2201, v.W, v.H, v.D, 0, v.cfg, err), "%s: %s", v.name, err.c_str())) continue;
        for (int s = 0; s < 37; ++s) w.update(0.016f);   // clocks running, eddy centres placed
        const float W = (float)v.W, H = (float)v.H, D = w.D, b = std::min(w.ocfg.waveBand, 0.25f * D);
        struct Field { const char* name; std::function<Fl(Vec2, float)> f; };
        const std::vector<Field> fields = {
            {"pair0", [&](Vec2 p, float d) { return w.waveTrainAt(0, p, d); }},
            {"pair1", [&](Vec2 p, float d) { return w.waveTrainAt(1, p, d); }},
            {"pair2", [&](Vec2 p, float d) { return w.waveTrainAt(2, p, d); }},
            {"waves", [&](Vec2 p, float d) {
                 Fl u;
                 for (int i = 0; i < OceanWorld::kWaveTrains; ++i) { const Fl q = w.waveTrainAt(i, p, d); u.x += q.x; u.y += q.y; u.d += q.d; }
                 return u; }},
            {"current", [&](Vec2 p, float d) { return w.currentFlowAt(p, d); }},
            {"flow", [&](Vec2 p, float d) { return w.flowAt(p, d); }},
        };
        // Probe sets: the bulk; along the side glass (within the current's band
        // and the fish band); the corners; the depth bands. A probe's ±h stays
        // inside the tank (h <= 2).
        const float bc = std::min(std::max(w.cfg.currentCore, 1.0f), std::min(0.25f * W, 0.25f * H));
        struct Set { const char* name; float x0, x1, y0, y1, d0, d1; int sideMode; };
        const float dl = std::min(b + 4.0f, 0.5f * D), dh = std::max(D - b - 4.0f, 0.5f * D);
        const Set sets[] = {
            {"bulk", 0.1f * W, 0.9f * W, 0.1f * H, 0.9f * H, dl, dh, 0},
            {"side", 2.5f, std::min(bc + 10.0f, 0.5f * W), 2.5f, H - 2.5f, 2.5f, D - 2.5f, 1},
            {"corner", 2.5f, std::min(bc, 0.5f * W), 2.5f, std::min(bc, 0.5f * H), 2.5f, D - 2.5f, 2},
            {"top", 2.5f, W - 2.5f, 2.5f, H - 2.5f, 2.5f, std::min(b + 4.0f, 0.5f * D), 0},
            {"floor", 2.5f, W - 2.5f, 2.5f, H - 2.5f, std::max(D - b - 4.0f, 0.5f * D), D - 2.5f, 0},
        };
        const float hs[] = {2.0f, 1.0f, 0.5f, 0.25f, 0.125f, 0.0625f, 0.03125f, 0.015625f};
        constexpr int NH = 8;
        double worstNorm = 0.0, worstAbs = 0.0;
        for (const Set& st : sets) {
            if (!(st.d1 > st.d0 + 0.5f) || !(st.x1 > st.x0) || !(st.y1 > st.y0)) continue;
            Lcg g(2202);
            std::vector<std::pair<Vec2, float>> probes;
            for (int k = 0; k < 300; ++k) {
                float x = st.x0 + (st.x1 - st.x0) * g.unit(), y = st.y0 + (st.y1 - st.y0) * g.unit();
                const float d = st.d0 + (st.d1 - st.d0) * g.unit();
                if (st.sideMode == 1 && (k & 1)) std::swap(x, y), x = x / H * W, y = y / W * H;   // half along the y glass
                if (st.sideMode >= 1 && (k & 2)) x = W - x;                                       // the far faces too
                if (st.sideMode >= 1 && (k & 4)) y = H - y;
                x = std::clamp(x, 2.5f, W - 2.5f);
                y = std::clamp(y, 2.5f, H - 2.5f);
                probes.push_back({Vec2{x, y}, d});
            }
            for (const Field& fd : fields) {
                double res[NH], absd[NH];
                for (int hi = 0; hi < NH; ++hi) {
                    double maxDiv = 0.0, maxSum = 0.0;
                    for (const auto& pr : probes) {
                        double dv, sa;
                        divergenceAtW(fd.f, pr.first, pr.second, hs[hi], dv, sa);
                        maxDiv = std::max(maxDiv, std::abs(dv));
                        maxSum = std::max(maxSum, sa);
                    }
                    res[hi] = maxSum > 0.0 ? maxDiv / maxSum : 0.0;
                    absd[hi] = maxDiv;
                }
                int best = 0;
                for (int hi = 1; hi < NH; ++hi) if (res[hi] < res[best]) best = hi;
                t.expect(res[best] < 1e-3, "%s %s %s: best normalised residual %.3g (h %g)", v.name, st.name, fd.name, res[best], hs[best]);
                t.expect(res[best] <= res[0] || res[0] < 1e-6, "%s %s %s: no convergence (h 2: %.3g, best %.3g)", v.name, st.name, fd.name,
                         res[0], res[best]);
                if (v.preset) t.expect(absd[best] < 1e-3, "%s %s %s: absolute divergence %.3g /s (h %g)", v.name, st.name, fd.name, absd[best], hs[best]);
                worstNorm = std::max(worstNorm, res[best]);
                worstAbs = std::max(worstAbs, absd[best]);
            }
        }
        t.note("%-34s divergence: worst best-h normalised %.2e, absolute %.2e /s (5 probe sets x 6 fields)", v.name, worstNorm, worstAbs);

        // EXACTLY zero normal flow on the six faces: tables and formulas, each part and the sum.
        long faces = 0, nonzero = 0;
        Lcg g(2203);
        auto checkFace = [&](Vec2 p, float d, int axis) {   // axis 0: x face, 1: y face, 2: depth face
            const Fl parts[] = {w.waveTrainAt(0, p, d), w.waveTrainAt(1, p, d), w.waveTrainAt(2, p, d),
                                w.waveTrainExactAt(0, p, d), w.waveTrainExactAt(1, p, d), w.waveTrainExactAt(2, p, d),
                                w.currentFlowAt(p, d), w.flowAt(p, d), w.flowExactAt(p, d)};
            for (const Fl& u : parts) {
                const float n = axis == 0 ? u.x : axis == 1 ? u.y : u.d;
                ++faces;
                nonzero += (n != 0.0f);
            }
        };
        for (int k = 0; k < 400; ++k) {
            const float x = (k < 4) ? ((k & 1) ? W : 0.0f) : W * g.unit(), y = (k < 4) ? ((k & 2) ? H : 0.0f) : H * g.unit();
            const float d = (k % 7 == 0) ? 0.0f : (k % 7 == 1) ? D : D * g.unit();
            checkFace({0.0f, y}, d, 0);
            checkFace({W, y}, d, 0);
            checkFace({x, 0.0f}, d, 1);
            checkFace({x, H}, d, 1);
            checkFace({x, y}, 0.0f, 2);
            checkFace({x, y}, D, 2);
        }
        t.expect(nonzero == 0, "%s: normal flow not exactly 0 at %ld of %ld face evaluations", v.name, nonzero, faces);
        // The current alone vanishes on the side glass (both components).
        int curZero = 0;
        for (int k = 0; k < 200; ++k) {
            const float y = H * g.unit(), x = W * g.unit(), d = D * g.unit();
            const Fl a = w.currentFlowAt({0.0f, y}, d), c2 = w.currentFlowAt({W, y}, d), e = w.currentFlowAt({x, 0.0f}, d),
                     f = w.currentFlowAt({x, H}, d);
            curZero += (a.x == 0.0f && a.y == 0.0f && c2.x == 0.0f && c2.y == 0.0f && e.x == 0.0f && e.y == 0.0f && f.x == 0.0f && f.y == 0.0f);
        }
        t.expect(curZero == 200, "%s: the current is not 0 on the side glass at %d of 200 points", v.name, 200 - curZero);

        // Tables vs formulas, per pair (budget as the periodic tables': 2e-6 per unit waveSpeed or 1e-6 of the largest speed).
        double maxD[3] = {}, maxU[3] = {};
        for (int k = 0; k < 4000; ++k) {
            const Vec2 p = {W * g.unit(), H * g.unit()};
            const float d = (k % 5 == 0) ? b : (k % 5 == 1) ? D - b : D * g.unit();
            for (int i = 0; i < OceanWorld::kWaveTrains; ++i) {
                const Fl a = w.waveTrainAt(i, p, d), e = w.waveTrainExactAt(i, p, d);
                maxD[i] = std::max(maxD[i], (double)std::max(std::abs(a.x - e.x), std::max(std::abs(a.y - e.y), std::abs(a.d - e.d))));
                maxU[i] = std::max(maxU[i], (double)std::max(std::abs(e.x), std::max(std::abs(e.y), std::abs(e.d))));
            }
        }
        for (int i = 0; i < OceanWorld::kWaveTrains; ++i) {
            const double budget = std::max(2e-6 * w.ocfg.waveSpeed, 1e-6 * maxU[i]);
            t.expect(maxD[i] <= budget, "%s pair %d: tables vs formulas %.3g > budget %.3g (max |u| %.3g)", v.name, i, maxD[i], budget, maxU[i]);
            if (v.preset) t.note("%-34s pair %d: tables vs formulas %.2e (budget %.1e, max |u| %.3g)", v.name, i, maxD[i], budget, maxU[i]);
        }

        // Where the taper is 1 the current is the open world's eddy / gyre current, bit for bit.
        {
            std::string cfgOpen = v.cfg;
            cfgOpen.replace(cfgOpen.find(R"("walls":true,)"), 13, "");
            OceanWorld o;
            if (t.expect(ofp::initWorld(o, 2201, v.W, v.H, v.D, 0, cfgOpen.c_str(), err), "%s open: %s", v.name, err.c_str())) {
                for (int s = 0; s < 37; ++s) o.update(0.016f);
                int sameN = 0, n = 0;
                if (bc < 0.45f * std::min(W, H))
                    for (int k = 0; k < 500; ++k) {
                        const Vec2 p = {bc + (W - 2.0f * bc) * g.unit(), bc + (H - 2.0f * bc) * g.unit()};
                        const Vec2 a = w.currentAt(p), e = o.currentAt(p);
                        ++n;
                        sameN += same(a.x, e.x) && same(a.y, e.y);
                    }
                t.expect(sameN == n, "%s: the inner current differs from the open world's at %d of %d points", v.name, n - sameN, n);
                // The look (the presets only): the pairs' orbits vs the periodic trains', interior and whole tank.
                if (v.preset) {
                    auto& wv = ofp::field<ofp::peek::OwWaves>(w);
                    auto& ov = ofp::field<ofp::peek::OwWaves>(o);
                    double save[3], saveO[3];
                    for (int i = 0; i < 3; ++i) { save[i] = wv[i].phase; saveO[i] = ov[i].phase; }
                    for (int region = 0; region < 2; ++region) {
                        double crossW = 0, energyW = 0, crossO = 0, energyO = 0;
                        Lcg q(2204 + region);
                        for (int k = 0; k < 3000; ++k) {
                            const float lo = region ? 0.0f : 0.25f, hi = region ? 1.0f : 0.75f;
                            const Vec2 p = {W * (lo + (hi - lo) * q.unit()), H * (lo + (hi - lo) * q.unit())};
                            const float d = b + (0.5f * D - b) * q.unit();
                            for (int i = 0; i < 3; ++i) {
                                for (int which = 0; which < 2; ++which) {
                                    auto& waves = which ? ov : wv;
                                    const OceanWorld& ww = which ? o : w;
                                    waves[i].phase = waves[i].phi;
                                    const Fl C = ww.waveTrainExactAt(i, p, d);
                                    waves[i].phase = waves[i].phi + 0.5 * 3.141592653589793;   // a quarter period later
                                    const Fl S = ww.waveTrainExactAt(i, p, d);
                                    const double cx = (double)C.y * S.d - (double)C.d * S.y, cy = (double)C.d * S.x - (double)C.x * S.d,
                                                 cz = (double)C.x * S.y - (double)C.y * S.x;
                                    const double cr = 2.0 * std::sqrt(cx * cx + cy * cy + cz * cz);
                                    const double en = (double)C.x * C.x + (double)C.y * C.y + (double)C.d * C.d + (double)S.x * S.x +
                                                      (double)S.y * S.y + (double)S.d * S.d;
                                    (which ? crossO : crossW) += cr;
                                    (which ? energyO : energyW) += en;
                                }
                            }
                        }
                        const double eW = crossW / energyW, eO = crossO / energyO, rms = std::sqrt(energyW / energyO);
                        t.note("%-34s look (%s): orbit ellipticity walls %.3f vs periodic %.3f (1 = circular, 0 = sloshing); RMS speed ratio %.3f",
                               v.name, region ? "whole tank" : "central 50%", eW, eO, rms);
                        if (region == 0) t.expect(eW > 0.3 && eO > 0.9, "%s: central orbit ellipticity walls %.3f, periodic %.3f", v.name, eW, eO);
                    }
                    for (int i = 0; i < 3; ++i) { wv[i].phase = save[i]; ov[i].phase = saveO[i]; }
                }
            }
        }
    }
}

// Containment: fixtures at the glass, then extreme worlds.
void testWallContainment() {
    Test t("wall_contain");
    const float W = 1920.0f, H = 1080.0f;
    // (a) A fish on each face / corner, pointing out: one step later it is
    // inside, its heading points in (or along), |v| = 1, speed kept.
    struct P { Vec2 pos, h; int faceX, faceY; };   // face: -1 low, +1 high, 0 none
    const P ps[] = {{{0, 540}, {-1, 0}, -1, 0}, {{W, 540}, {1, 0}, 1, 0}, {{960, 0}, {0, -1}, 0, -1}, {{960, H}, {0, 1}, 0, 1},
                    {{0, 0}, {-0.70710678f, -0.70710678f}, -1, -1}, {{W, H}, {0.6f, 0.8f}, 1, 1}, {{0, H}, {-0.8f, 0.6f}, -1, 1},
                    {{1.5f, 300}, {-1, 0}, -1, 0}, {{W - 1.0f, 700}, {0.9805807f, 0.19611613f}, 1, 0}};
    for (int tri = 0; tri < 2; ++tri)
        for (float band : {80.0f, 0.0f}) {
            OceanConfig oc;
            oc.walls = true;
            oc.sideWallBand = band;
            OceanWorld w;
            initQuiet(w, 2301, 240.0f, oc);
            w.cfg.triangularMotion = tri != 0;
            w.cfg.minSpeed = w.cfg.maxSpeed = 150.0f;
            for (const P& p : ps) {
                const int k = addFish(w, p.pos, 120.0f, {}, 0.5f);
                w.creatures[k].vel = p.h;
                w.creatures[k].speed = 150.0f;
            }
            w.update(0.016f);
            int good = 0;
            for (std::size_t k = 0; k < w.creatures.size(); ++k) {
                const Fish& f = w.creatures[k];
                const P& p = ps[k];
                const bool in = f.pos.x >= 0.0f && f.pos.x <= W && f.pos.y >= 0.0f && f.pos.y <= H;
                const bool hx = p.faceX == 0 || (p.faceX < 0 ? f.vel.x >= 0.0f : f.vel.x <= 0.0f);
                const bool hy = p.faceY == 0 || (p.faceY < 0 ? f.vel.y >= 0.0f : f.vel.y <= 0.0f);
                const float len = std::sqrt(f.vel.x * f.vel.x + f.vel.y * f.vel.y);
                const bool ok = in && hx && hy && std::abs(len - 1.0f) < 1e-5f && f.speed == 150.0f &&
                                f.lastMoveDir.x == f.vel.x && f.lastMoveDir.y == f.vel.y;
                good += ok;
                if (!ok)
                    t.expect(false, "tri %d band %g fixture %zu: pos (%.9g, %.9g) vel (%.9g, %.9g) |v| %.9g speed %g", tri, (double)band, k,
                             (double)f.pos.x, (double)f.pos.y, (double)f.vel.x, (double)f.vel.y, (double)len, (double)f.speed);
            }
            t.expect(good == (int)(sizeof ps / sizeof ps[0]), "tri %d band %g: %d of %zu fixtures resolved", tri, (double)band, good,
                     sizeof ps / sizeof ps[0]);
        }
    // (b) Head-on approach at full speed, 200 steps: never outside; with the
    // band it turns before (or at) the glass, without it it bounces off.
    for (int tri = 0; tri < 2; ++tri)
        for (float band : {80.0f, 0.0f}) {
            OceanConfig oc;
            oc.walls = true;
            oc.sideWallBand = band;
            OceanWorld w;
            initQuiet(w, 2302, 240.0f, oc);
            w.cfg.triangularMotion = tri != 0;
            w.cfg.minSpeed = w.cfg.maxSpeed = 150.0f;
            const int k = addFish(w, {300.0f, 540.0f}, 120.0f, {}, 0.5f);
            w.creatures[k].vel = {-1.0f, 0.0f};
            w.creatures[k].speed = 150.0f;
            float minX = 1e9f;
            int touched = 0, turnedAt = -1;
            for (int s = 1; s <= 200; ++s) {
                w.update(0.016f);
                const Fish& f = w.creatures[0];
                minX = std::min(minX, f.pos.x);
                touched += (f.pos.x == 0.0f);
                if (turnedAt < 0 && f.vel.x > 0.0f) turnedAt = s;
            }
            t.expect(minX >= 0.0f && turnedAt > 0 && (band > 0.0f || touched > 0), "tri %d band %g: min x %.9g, touched %d, turned at step %d",
                     tri, (double)band, (double)minX, touched, turnedAt);
            t.note("head-on at 150 u/s, %s, band %-3g: closest %.2f units from the glass, turned at step %d, %d contact step(s)",
                   tri ? "triangular" : "steering  ", (double)band, (double)minX, turnedAt, touched);
        }
    // (c) Extreme worlds: everything inside after every step, finite.
    struct X { const char* name; int W, H; float D; int pop; const char* cfg; };
    const X xs[] = {
        {"speed 2000, 100 eddies x 1000, waves 100 band 1, band 0", 1920, 1080, 240.0f, 200,
         R"({"walls":true,"sideWallBand":0,"minSpeed":1000,"maxSpeed":2000,"currentStrength":1000,"currentEddies":100,"waveSpeed":100,"waveBand":1,"waveGravity":10000,"deepCurrent":true,"foodDrift":true,"predatorCount":6,"predatorSpeed":2000,"predatorEconomy":true,"predatorReproEnergy":1,"predatorMaxPopulation":40,"foodPatches":5,"foodPatchRadius":400,"foodDepthMode":1,"foodDepthSpread":1000,"triangularMotion":true,"bodyModel":true})"},
        {"100x100 D 10, gyre 1000, waves 100", 100, 100, 10.0f, 60,
         R"({"walls":true,"sideWallTurnRate":1000,"maxSpeed":2000,"currentStrength":1000,"currentMode":1,"currentGyreEps":1,"waveSpeed":100,"waveBand":1,"foodDrift":true,"predatorCount":3,"predatorSpeed":2000,"sizeDrift":true,"bodyModel":true})"},
        {"Big tank, the E1 preset", 3840, 2160, 240.0f, 400,
         R"({"walls":true,"waveSpeed":6,"deepCurrent":true,"currentStrength":5,"foodDrift":true,"predatorCount":4,"targetFood":4000})"},
    };
    for (const X& x : xs) {
        OceanWorld w;
        std::string err;
        if (!t.expect(ofp::initWorld(w, 2303, x.W, x.H, x.D, x.pop, x.cfg, err), "%s: %s", x.name, err.c_str())) continue;
        const float WW = (float)x.W, HH = (float)x.H, D = w.D;
        auto in = [&](Vec2 p, float d) { return p.x >= 0.0f && p.x <= WW && p.y >= 0.0f && p.y <= HH && d >= 0.0f && d <= D; };
        long out = 0, touch = 0;
        for (int s = 0; s <= 300; ++s) {
            if (s) w.update(0.016f);
            for (const Fish& f : w.creatures) {
                out += !in(f.pos, f.depth);
                for (const Vec2& b : f.body) out += !in(b, 0.0f);
                touch += (f.pos.x == 0.0f || f.pos.x == WW || f.pos.y == 0.0f || f.pos.y == HH);
            }
            for (const OceanFood& f : w.food) out += !in(f.pos, f.depth);
            for (const OceanPredator& p : w.predators) out += !in(p.pos, p.depth);
        }
        t.expect(out == 0 && ofp::countNonFinite(w) == 0 && w.totalNonFiniteRemoved == 0, "%s: %ld outside, non-finite %ld", x.name, out,
                 ofp::countNonFinite(w));
        t.note("%-52s 300 steps: 0 outside; %ld fish-steps on the glass; pop %zu, pred %zu", x.name, touch, w.creatures.size(),
               w.predators.size());
    }
}

// Placement: patch food and predator buds, inside with the open world's draws.
void testWallPlacement() {
    Test t("wall_place");
    for (float R : {0.0f, 300.0f}) {
        char cfg[300];
        std::snprintf(cfg, sizeof cfg,
                      R"({"minPopulation":0,"targetFood":3000,"foodPatches":30,"foodPatchRadius":%g,"foodDepthMode":1,"foodDepthSpread":400%s})",
                      (double)R, "");
        std::string walled = cfg;
        walled.insert(walled.size() - 1, R"(,"walls":true)");
        OceanWorld a, b;
        std::string err;
        const bool ok = ofp::initWorld(a, 2401, 1920, 1080, 240.0f, 0, cfg, err) && ofp::initWorld(b, 2401, 1920, 1080, 240.0f, 0, walled.c_str(), err);
        if (!t.expect(ok, "R %g: %s", (double)R, err.c_str())) continue;
        t.expect(ofp::fingerprint(a).rng == ofp::fingerprint(b).rng, "R %g: patch food draws differ with walls", (double)R);
        long out = 0, onInset = 0, openOnFace = 0;
        for (const OceanFood& f : b.food) {
            out += !(f.pos.x >= 1.0f && f.pos.x <= 1919.0f && f.pos.y >= 1.0f && f.pos.y <= 1079.0f && f.depth >= 1.0f && f.depth <= 239.0f);
            onInset += (f.pos.x == 1.0f || f.pos.x == 1919.0f || f.pos.y == 1.0f || f.pos.y == 1079.0f || f.depth == 1.0f || f.depth == 239.0f);
        }
        for (const OceanFood& f : a.food)
            openOnFace += (f.pos.x == 0.0f || f.pos.x == 1920.0f || f.pos.y == 0.0f || f.pos.y == 1080.0f || f.depth == 0.0f || f.depth == 240.0f);
        t.expect(out == 0, "R %g: %ld of %zu patch items outside [inset, L - inset]", (double)R, out, b.food.size());
        if (R > 0.0f) t.expect(onInset == 0, "R %g: %ld items piled on the inset", (double)R, onInset);
        t.note("patch radius %-3g: %zu items inside the glass's inset (on it: %ld); the open world clamps %ld onto a face", (double)R,
               b.food.size(), onInset, openOnFace);
    }
    // A predator budding every step at a corner: the child mirror-folded inside, the same draws as open.
    long out = 0, steps = 0;
    for (int s = 0; s < 2; ++s) {
        RandomGen after[2];
        for (int on = 0; on < 2; ++on) {
            OceanConfig oc;
            oc.walls = on != 0;
            OceanWorld w;
            initQuiet(w, 2402 + s, 240.0f, oc);
            w.cfg.predatorEconomy = true;
            w.cfg.predatorPerception = 0.0f;   // wander (two draws), never chase
            w.cfg.predatorReproEnergy = 1.0f;
            w.cfg.predatorNewbornEnergy = 0.0f;
            w.cfg.predatorMaxPopulation = 50;
            w.cfg.predatorInheritance = true;
            for (int k = 0; k < 4; ++k) {
                OceanPredator p;
                p.pos = {(k & 1) ? 1919.5f : 0.5f, (k & 2) ? 1079.5f : 0.5f};
                p.depth = (k & 1) ? 239.0f : 1.0f;
                p.energy = 1e5f;
                p.vel = {(k & 1) ? 1.0f : -1.0f, 0.0f};
                w.predators.push_back(p);
            }
            for (int st = 0; st < 5; ++st) {
                w.update(0.016f);
                if (on) {
                    ++steps;
                    for (const OceanPredator& p : w.predators)
                        out += !(p.pos.x >= 0.0f && p.pos.x <= 1920.0f && p.pos.y >= 0.0f && p.pos.y <= 1080.0f && p.depth >= 0.0f && p.depth <= 240.0f);
                }
            }
            after[on] = rng;
            if (on) t.expect(w.predators.size() > 4, "seed %d: no buds (%zu predators)", s, w.predators.size());
        }
        t.expect(sameEngine(after[0], after[1]), "seed %d: budding at the glass draws differently with walls", s);
    }
    t.expect(out == 0, "%ld predators (parents or buds) outside", out);
}

// Transport: uniform tracers, wall accumulation and substep convergence.
void testWallTransport() {
    Test t("wall_transport");
    OceanWorld w;
    std::string err;
    if (!t.expect(ofp::initWorld(w, 2501, 1920, 1080, 240.0f, 0,
                                 R"({"walls":true,"minPopulation":0,"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"waveSpeed":20,"waveBand":24,"currentStrength":60,"currentEddies":8,"currentCore":120,"foodDrift":true})",
                                 err), "%s", err.c_str()))
        return;
    const float W = 1920.0f, H = 1080.0f, D = 240.0f;
    constexpr int N = 10000;
    std::vector<Vec2> p(N);
    std::vector<float> d(N);
    Lcg g(2502);
    for (int k = 0; k < N; ++k) { p[k] = {W * g.unit(), H * g.unit()}; d[k] = D * g.unit(); }
    // Convergence set: 1500 tracers, advected with n = 1, 2, 4, 8 through the same steps.
    constexpr int NC = 1500;
    std::vector<Vec2> pc[4];
    std::vector<float> dc[4];
    for (int m = 0; m < 4; ++m) { pc[m].assign(p.begin(), p.begin() + NC); dc[m].assign(d.begin(), d.begin() + NC); }
    double band[6] = {}, samples = 0;
    long out = 0;
    const int nStep = w.wallFoodSubstepsNow(0.016f);
    for (int s = 1; s <= 1200; ++s) {
        w.update(0.016f);
        (void)w.flowAt({1.0f, 1.0f}, 1.0f);   // the cache for this step
        for (int k = 0; k < N; ++k) w.wallAdvect(p[k], d[k], 0.016f, nStep);
        // (dt 0.16 here, ten steps' worth per call: the RK2 truncation error,
        // ∝ dt³ per call, then stands well clear of float roundoff)
        if (s <= 20)
            for (int m = 0; m < 4; ++m)
                for (int k = 0; k < NC; ++k) w.wallAdvect(pc[m][k], dc[m][k], 0.16f, 1 << m);
        if (s > 300 && s % 10 == 0) {
            for (int k = 0; k < N; ++k) {
                out += !(p[k].x >= 0.0f && p[k].x <= W && p[k].y >= 0.0f && p[k].y <= H && d[k] >= 0.0f && d[k] <= D);
                band[0] += p[k].x < 0.05f * W; band[1] += p[k].x > 0.95f * W;
                band[2] += p[k].y < 0.05f * H; band[3] += p[k].y > 0.95f * H;
                band[4] += d[k] < 0.05f * D;   band[5] += d[k] > 0.95f * D;
            }
            samples += N;
        }
    }
    const char* names[6] = {"x=0", "x=W", "y=0", "y=H", "surface", "floor"};
    std::string line;
    for (int f = 0; f < 6; ++f) {
        const double share = band[f] / samples;
        t.expect(share > 0.045 && share < 0.055, "%s band: %.4f of the tracers (uniform: 0.05)", names[f], share);
        char buf[40];
        std::snprintf(buf, sizeof buf, " %s %.4f", names[f], share);
        line += buf;
    }
    t.expect(out == 0, "%ld tracer samples outside the tank", out);
    // Convergence: the mean distance to the n = 8 positions shrinks with n.
    double e[3] = {};
    for (int m = 0; m < 3; ++m) {
        for (int k = 0; k < NC; ++k) {
            const double dx = pc[m][k].x - pc[3][k].x, dy = pc[m][k].y - pc[3][k].y, dz = dc[m][k] - dc[3][k];
            e[m] += std::sqrt(dx * dx + dy * dy + dz * dz);
        }
        e[m] /= NC;
    }
    t.expect(e[0] > e[1] && e[1] > e[2] && e[0] < 5.0, "substep convergence (mean |x_n - x_8|, 20 calls of dt 0.16): n=1 %.3g, n=2 %.3g, n=4 %.3g",
             e[0], e[1], e[2]);
    t.note("1200 steps, %d tracers, substeps %d: 5%% face bands hold%s", N, nStep, line.c_str());
    t.note("substeps vs n = 8 (20 calls of dt 0.16): n=1 %.2e, n=2 %.2e, n=4 %.2e units (mean)", e[0], e[1], e[2]);
}

// Waves off with walls: the per-train readers give exact zeros (never NaN),
// before the trains were ever prepared (waveSpeed 0 from init: a pair's |K|² is
// 0 there) and after the waves ran and stopped; reading them changes nothing.
// wallAdvect4 (four particles lane-wise) == wallAdvect per particle, bit for
// bit: random points in the tank, points on the faces and outside (the folds'
// other branches and the wave tables' exact fallback), four configs (eddies
// with and without waves and the deep factor, the double gyre), substeps
// 1, 2 and 16, after a few hundred steps of flow.
void testWallAdvect4() {
    Test t("wall_advect4");
    static const char* cfgs[] = {
        R"({"walls":true,"minPopulation":0,"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"waveSpeed":20,"waveBand":24,"currentStrength":60,"currentEddies":8,"currentCore":120,"foodDrift":true})",
        R"({"walls":true,"minPopulation":0,"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"waveSpeed":6,"waveBand":32,"deepCurrent":true,"currentStrength":5,"currentEddies":5,"foodDrift":true})",
        R"({"walls":true,"minPopulation":0,"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"waveSpeed":0,"currentStrength":40,"currentEddies":3,"currentCore":60,"foodDrift":true})",
        R"({"walls":true,"minPopulation":0,"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"waveSpeed":9,"currentMode":1,"currentStrength":30,"deepCurrent":true,"foodDrift":true})",
    };
    const float W = 1920.0f, H = 1080.0f, D = 240.0f;
    long lanes = 0, differ = 0;
    for (int c = 0; c < 4; ++c) {
        OceanWorld w;
        std::string err;
        if (!t.expect(ofp::initWorld(w, 2601 + c, 1920, 1080, 240.0f, 0, cfgs[c], err), "cfg %d: %s", c, err.c_str())) continue;
        for (int s = 0; s < 150; ++s) w.update(0.016f);
        (void)w.flowAt({1.0f, 1.0f}, 1.0f);   // the cache for this step
        Lcg g(2700 + c);
        static const float edgesX[] = {0.0f, 1920.0f, -3.0f, 1925.0f, 0.5f, 1919.5f, 4000.0f, -2000.0f};
        static const float edgesD[] = {0.0f, 240.0f, -1.0f, 241.0f, 0.25f, 239.75f, 700.0f, -500.0f};
        for (int trial = 0; trial < 400; ++trial) {
            const int nStep = trial % 3 == 0 ? 1 : trial % 3 == 1 ? 2 : 16;
            const float dt = trial % 5 == 4 ? 0.16f : 0.016f;
            Vec2 p[4], q[4]; float d[4], e[4];
            for (int l = 0; l < 4; ++l) {
                p[l] = {W * g.unit(), H * g.unit()}; d[l] = D * g.unit();
                if (trial % 4 == 1) { p[l].x = edgesX[(trial + l) % 8]; }
                if (trial % 4 == 2) { p[l].y = edgesX[(trial + 3 * l) % 8] * (H / W); d[l] = edgesD[(trial + l) % 8]; }
                q[l] = p[l]; e[l] = d[l];
            }
            w.wallAdvect4(p, d, dt, nStep);
            for (int l = 0; l < 4; ++l) {
                w.wallAdvect(q[l], e[l], dt, nStep);
                ++lanes;
                if (ofp::bits(p[l].x) != ofp::bits(q[l].x) || ofp::bits(p[l].y) != ofp::bits(q[l].y) || ofp::bits(d[l]) != ofp::bits(e[l])) ++differ;
            }
        }
    }
    t.expect(differ == 0 && lanes > 0, "%ld of %ld lanes differ from wallAdvect", differ, lanes);
    t.note("%ld lanes, 4 configs, substeps 1 / 2 / 16", lanes);
}

void testWallWavesOff() {
    Test t("wall_waves_off");
    using Fl = OceanWorld::Flow;
    OceanWorld w;
    std::string err;
    if (!t.expect(ofp::initWorld(w, 2801, 1920, 1080, 240.0f, 40, R"({"walls":true,"currentStrength":60,"foodDrift":true})", err),
                  "%s", err.c_str()))
        return;
    const float W = 1920.0f, H = 1080.0f, D = 240.0f;
    const Vec2 pts[] = {{0.0f, 0.0f}, {W, 0.0f}, {0.0f, H}, {W, H}, {0.0f, 0.5f * H}, {W, 0.5f * H}, {0.5f * W, 0.0f},
                        {0.5f * W, H}, {0.37f * W, 0.61f * H}, {1.0f, 1.0f}, {W - 1.0f, 2.0f}};
    const float ds[] = {0.0f, 1.0f, 0.5f * D, D - 1.0f, D};
    long total = 0;
    auto zeros = [&](const char* when) {
        long bad = 0, n = 0;
        const ofp::Fingerprint kept = ofp::fingerprint(w);
        const RandomGen r0 = rng;
        for (int i = 0; i < OceanWorld::kWaveTrains; ++i)
            for (const Vec2& p : pts)
                for (float d : ds) {
                    const Fl a = w.waveTrainAt(i, p, d), e = w.waveTrainExactAt(i, p, d);
                    for (const Fl& u : {a, e}) {
                        ++n;
                        if (!(u.x == 0.0f && u.y == 0.0f && u.d == 0.0f) && bad++ < 3)
                            t.expect(false, "%s: train %d at (%g, %g, %g): (%g, %g, %g)", when, i, (double)p.x, (double)p.y, (double)d,
                                     (double)u.x, (double)u.y, (double)u.d);
                    }
                }
        t.expect(bad == 0, "%s: %ld of %ld readings not exactly zero", when, bad, n);
        t.expect(ofp::fingerprint(w) == kept && sameEngine(r0, rng), "%s: reading the trains changed the world or the rng", when);
        total += n;
    };
    zeros("never prepared, before a step");
    for (int s = 0; s < 30; ++s) w.update(0.016f);
    zeros("never prepared, 30 steps");
    w.ocfg.waveSpeed = 6.0f;   // on, as oc_set_param("waveSpeed", 6)
    for (int s = 0; s < 30; ++s) w.update(0.016f);
    const Fl on = w.waveTrainAt(0, {0.37f * W, 0.61f * H}, 0.5f * D);
    t.expect(std::isfinite(on.x) && std::isfinite(on.d) && (on.x != 0.0f || on.y != 0.0f || on.d != 0.0f),
             "waves on: train 0 reads (%g, %g, %g)", (double)on.x, (double)on.y, (double)on.d);
    w.ocfg.waveSpeed = 0.0f;   // and off again
    for (int s = 0; s < 5; ++s) w.update(0.016f);
    zeros("prepared, then waves off");
    t.note("%ld readings (3 trains x %zu points incl. the corners x %zu depths x both readers, three times): all exactly 0, world and rng kept",
           total, sizeof pts / sizeof pts[0], sizeof ds / sizeof ds[0]);
}

// A stationary eddy (one, no drift, no waves): the wall flow inside its taper
// is a pure rotation about the centre, so a tracer keeps its radius and a
// uniform disk stays uniform. Small cores and strong currents, up to far beyond
// the 16-substep budget (food then lags the water: wallFoodSteps); the old cap
// (16 substeps over the whole step) is measured as the contrast.
void testWallEddy() {
    Test t("wall_eddy");
    struct C { float s, core; bool density; };
    const C cs[] = {{60, 1, false}, {1000, 1, false}, {1000, 5, true}, {60, 5, false}, {1000, 30, false}, {60, 30, true}, {6, 120, false}};
    const float dt = 0.016f;
    for (const C& c : cs) {
        OceanWorld w;
        std::string err;
        char cfg[320];
        std::snprintf(cfg, sizeof cfg,
                      R"({"walls":true,"minPopulation":0,"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"currentStrength":%g,"currentEddies":1,"currentCore":%g,"currentDrift":0,"foodDrift":true})",
                      (double)c.s, (double)c.core);
        const float cr = std::max(c.core, 1.0f);
        Vec2 ctr{};
        bool found = false;
        for (unsigned seed = 2802; seed < 3200 && !found; ++seed) {   // an eddy well inside: 4 cores + 20 from every face
            if (!ofp::initWorld(w, seed, 1920, 1080, 240.0f, 0, cfg, err)) break;
            w.update(dt);
            ctr = ofp::field<ofp::peek::CfCenters>(ofp::field<ofp::peek::OwCurrent>(w))[0];
            const float m = 4.0f * cr + 20.0f;
            found = ctr.x > m && ctr.x < 1920.0f - m && ctr.y > m && ctr.y < 1080.0f - m;
        }
        if (!t.expect(found, "s %g core %g: no interior eddy (%s)", (double)c.s, (double)c.core, err.c_str())) continue;
        (void)w.flowAt({1.0f, 1.0f}, 1.0f);   // the cache (frozen: no more steps)
        const auto fs = w.wallFoodStepsNow(dt);
        if (fs.need > 16.0)
            t.expect(fs.n == 16 && fs.dt == (float)((double)dt * 16.0 / fs.need) && fs.dt < dt,
                     "s %g core %g: need %g, n %d, dt %g (the budget's fallback)", (double)c.s, (double)c.core, fs.need, fs.n, (double)fs.dt);
        else
            t.expect(fs.n == std::max(1, (int)fs.need) && fs.dt == dt, "s %g core %g: need %g, n %d, dt %g", (double)c.s, (double)c.core,
                     fs.need, fs.n, (double)fs.dt);
        auto radius = [&](Vec2 p) { return std::hypot((double)p.x - ctr.x, (double)p.y - ctr.y); };
        // Radii: 0.1 .. 3 cores, 8 angles, 600 frames (10 s). Relative drift for
        // r0 >= 1 unit; below that a float position's own rounding (~6e-5 at x ~ 900)
        // is a sizeable fraction of r, so those are held to the absolute bound.
        double relWorst = 0, absWorst = 0, oldCap = 0;
        long depthMoved = 0;
        for (float rf : {0.1f, 0.5f, 1.0f, 2.0f, 3.0f})
            for (int a = 0; a < 8; ++a) {
                const float th = 0.785398f * (float)a + 0.1f;
                const Vec2 p0 = {ctr.x + rf * cr * std::cos(th), ctr.y + rf * cr * std::sin(th)};
                const double R0 = radius(p0);
                Vec2 p = p0;
                float d = 120.0f;
                for (int f = 0; f < 600; ++f) {
                    w.wallAdvect(p, d, fs.dt, fs.n);
                    const double e = std::abs(radius(p) - R0);
                    absWorst = std::max(absWorst, e);
                    if (R0 >= 1.0) relWorst = std::max(relWorst, e / R0);
                }
                depthMoved += (d != 120.0f);
                if (fs.need > 16.0) {   // the old cap: 16 substeps over the whole step, one frame
                    Vec2 q = p0;
                    float dq = 120.0f;
                    w.wallAdvect(q, dq, dt, 16);
                    oldCap = std::max(oldCap, std::abs(radius(q) - R0) / R0);
                }
            }
        t.expect(relWorst < 1e-2 && absWorst < 0.1 && depthMoved == 0,
                 "s %g core %g: radius drift over 600 frames %.2e (r0 >= 1 unit), %.2e units; %ld depth(s) moved", (double)c.s,
                 (double)c.core, relWorst, absWorst, depthMoved);
        if (fs.need > 16.0 && c.s >= 1000.0f && c.core <= 1.0f)   // the review's case (need 577)
            t.expect(oldCap > 2.0, "s %g core %g: the old cap kept the radius (%.2e): the contrast is lost", (double)c.s, (double)c.core, oldCap);
        char extra[160] = "";
        // Density: a uniform disk of 3 cores, 1000 tracers, 300 frames: the counts
        // in six equal-area annuli and the mean r² hold.
        if (c.density) {
            constexpr int N = 1000;
            const double R = 3.0 * cr;
            std::vector<Vec2> p(N);
            std::vector<float> d(N, 120.0f);
            Lcg g(2803);
            for (int k = 0; k < N; ++k) {
                const double r = R * std::sqrt(g.unit()), th = 6.283185307179586 * g.unit();
                p[k] = {(float)(ctr.x + r * std::cos(th)), (float)(ctr.y + r * std::sin(th))};
            }
            auto census = [&](int cnt[6], double& r2) {
                r2 = 0;
                for (int b = 0; b < 6; ++b) cnt[b] = 0;
                for (int k = 0; k < N; ++k) {
                    const double rr = radius(p[k]);
                    r2 += rr * rr / N;
                    ++cnt[std::min(5, (int)(6.0 * rr * rr / (R * R)))];
                }
            };
            int c0[6], c1[6];
            double r20, r21;
            census(c0, r20);
            for (int f = 0; f < 300; ++f)
                for (int k = 0; k < N; ++k) w.wallAdvect(p[k], d[k], fs.dt, fs.n);
            census(c1, r21);
            int worst = 0;
            for (int b = 0; b < 6; ++b) worst = std::max(worst, std::abs(c1[b] - c0[b]));
            t.expect(worst <= N / 50 && std::abs(r21 / r20 - 1.0) < 1e-2,
                     "s %g core %g: annulus counts moved by up to %d of %d, mean r^2 x %.5f", (double)c.s, (double)c.core, worst, N,
                     r21 / r20);
            std::snprintf(extra, sizeof extra, "; density: annuli move <= %d of %d, mean r^2 x %.5f", worst, N, r21 / r20);
        }
        t.note("currentStrength %-4g core %-3g: need %4.0f -> n %2d over %.5f s; radii over 600 frames %.1e (r0 >= 1), %.1e units%s",
               (double)c.s, (double)c.core, fs.need, fs.n, (double)fs.dt, relWorst, absWorst, extra);
        if (fs.need > 16.0) t.note("    the old cap (16 substeps over the whole step): radius x %.2f after one frame", 1.0 + oldCap);
    }
    // Convergence: the core-30 eddy at currentStrength 1000, r0 = 30, 100 frames
    // of the whole step with n = 4, 8, 16 (all under its need: the truncation,
    // not rounding, dominates): the drift falls ~n^-3.
    {
        OceanWorld w;
        std::string err;
        Vec2 ctr{};
        bool found = false;
        for (unsigned seed = 2802; seed < 3200 && !found; ++seed) {
            if (!ofp::initWorld(w, seed, 1920, 1080, 240.0f, 0,
                                R"({"walls":true,"minPopulation":0,"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"currentStrength":1000,"currentEddies":1,"currentCore":30,"currentDrift":0,"foodDrift":true})",
                                err))
                break;
            w.update(dt);
            ctr = ofp::field<ofp::peek::CfCenters>(ofp::field<ofp::peek::OwCurrent>(w))[0];
            found = ctr.x > 140.0f && ctr.x < 1780.0f && ctr.y > 140.0f && ctr.y < 940.0f;
        }
        if (t.expect(found, "convergence: no interior eddy")) {
            (void)w.flowAt({1.0f, 1.0f}, 1.0f);
            double e[3] = {};
            for (int m = 0; m < 3; ++m)
                for (int a = 0; a < 8; ++a) {
                    const float th = 0.785398f * (float)a + 0.1f;
                    Vec2 p = {ctr.x + 30.0f * std::cos(th), ctr.y + 30.0f * std::sin(th)};
                    const double R0 = std::hypot((double)p.x - ctr.x, (double)p.y - ctr.y);
                    float d = 120.0f;
                    for (int f = 0; f < 100; ++f) w.wallAdvect(p, d, dt, 4 << m);
                    e[m] = std::max(e[m], std::abs(std::hypot((double)p.x - ctr.x, (double)p.y - ctr.y) / R0 - 1.0));
                }
            t.expect(e[0] > 4.0 * e[1] && e[1] > 4.0 * e[2], "convergence: radius drift n=4 %.2e, n=8 %.2e, n=16 %.2e", e[0], e[1], e[2]);
            t.note("convergence (core 30 at 1000, r0 30, 100 frames): radius drift n=4 %.2e, n=8 %.2e, n=16 %.2e", e[0], e[1], e[2]);
        }
    }
}

// Sensing does not wrap: no pickup, pairing or capture across the tank.
void testWallSensing() {
    Test t("wall_sense");
    OceanConfig oc;
    oc.walls = true;
    OceanWorld w;
    initQuiet(w, 2601, 240.0f, oc);
    w.cfg.predatorCaptureRadius = 30.0f;
    w.cfg.predatorPerception = 500.0f;
    // Each pair is 4-6 units apart through the (absent) seam, ~1910 directly.
    const std::vector<Gene> rep = {mkGene(false, 0, INTERACT_REPRODUCE, kStrong)};
    const int a = addFish(w, {2.0f, 100.0f}, 100.0f, rep, 0.4f), b = addFish(w, {1918.0f, 100.0f}, 100.0f, rep, 0.4f);
    const int e = addFish(w, {3.0f, 400.0f}, 100.0f, {}, 0.4f);   // food at x = 1917 across from it
    const int c = addFish(w, {4.0f, 800.0f}, 100.0f, {}, 0.4f);   // a predator at x = 1916 across from it
    for (int i : {a, b, e, c}) {
        Fish& f = w.creatures[i];
        f.age = 10.0f; f.foodReserves = 100.0f; f.reproTimer = 0.0f; f.interactTimer = 0.0f;
        f.vel = {0.0f, 1.0f};   // along the glass
    }
    OceanFood fd;
    fd.pos = {1917.0f, 400.0f};
    fd.depth = 100.0f;
    w.food.push_back(fd);
    OceanPredator p;
    p.pos = {1916.0f, 800.0f};
    p.depth = 100.0f;
    p.vel = {0.0f, 1.0f};
    w.predators.push_back(p);
    for (int s = 0; s < 5; ++s) w.update(0.016f);
    t.expect(w.creatures.size() == 4 && w.totalBirths == 0, "a pair across the tank: %zu fish, %lld births", w.creatures.size(), w.totalBirths);
    t.expect(w.food.size() == 1, "food across the tank eaten (%zu left)", w.food.size());
    t.expect(w.totalDeathsPredation == 0, "a capture across the tank");
}

// No wall step draws: 150 steps with fish in the bands and at the glass.
void testWallDraws() {
    Test t("wall_draws");
    OceanConfig oc;
    oc.walls = true;
    oc.waveSpeed = 8.0f;
    oc.deepCurrent = true;
    OceanWorld w;
    initQuiet(w, 2701, 240.0f, oc, false, false, /*current*/ 50.0f);
    w.cfg.foodDrift = true;
    w.cfg.predatorCount = 4;
    w.cfg.predatorPerception = 0.0f;      // they always wander (two draws each), never chase
    w.cfg.predatorCaptureRadius = 0.0f;
    int nRandom = 0;
    const float xs[4] = {0.0f, 1920.0f, 30.0f, 1890.0f};
    for (int i = 0; i < 40; ++i) {
        std::vector<Gene> g;
        if (i % 3 != 2) g.push_back(mkGene(false, 0, STEER_X, (i % 3 == 0) ? kStrong : -kStrong));
        const bool rnd = (i % 2 == 0);
        if (rnd) g.push_back(mkGene(false, 0, MOVE_RANDOM, kStrong));
        const int k = addFish(w, {xs[i % 4], 5.0f + 26.0f * (float)i}, 240.0f * (float)(i % 9) / 8.0f, g, 0.5f);
        w.creatures[k].responsiveness = 1.0f;
        w.creatures[k].vel = {(i % 4 == 1 || i % 4 == 3) ? 1.0f : -1.0f, 0.0f};   // into the glass
        nRandom += rnd;
    }
    for (int i = 0; i < 4; ++i) {
        OceanPredator p;
        p.pos = {(i & 1) ? 1915.0f : 5.0f, (i & 2) ? 1075.0f : 5.0f};
        p.depth = 60.0f * i;
        p.energy = 30.0f;
        w.predators.push_back(p);
    }
    Lcg g(2702);
    for (int i = 0; i < 300; ++i) {
        OceanFood f;
        f.pos = {1920.0f * g.unit(), 1080.0f * g.unit()};
        f.depth = 240.0f * g.unit();
        w.food.push_back(f);
    }
    const long N = (long)w.creatures.size();
    const long expected = N + 3L * nRandom + 2L * 4;
    long touches = 0;
    for (int s = 1; s <= 150; ++s) {
        const RandomGen before = rng;
        w.update(0.016f);
        const long dd = drawsBetween(before, rng, 10000);
        t.expect(dd == expected && (long)w.creatures.size() == N, "step %d: %ld draws, expected %ld (pop %zu)", s, dd, expected,
                 w.creatures.size());
        for (const Fish& f : w.creatures) touches += (f.pos.x == 0.0f || f.pos.x == 1920.0f || f.pos.y == 0.0f || f.pos.y == 1080.0f);
    }
    t.expect(touches > 0, "no fish ever reached the glass (the contact path untested)");
    t.note("150 steps with walls, waves and a deep current: %ld draws/step == N + 3 x MOVE_RANDOM + 2 x predators; %ld fish-steps on the glass",
           expected, touches);
}

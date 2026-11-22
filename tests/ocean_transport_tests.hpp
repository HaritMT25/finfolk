#pragma once
// PR 1: the extracted state must stand alone, retain lazy-reader semantics,
// and transport separate buffers exactly like the original scalar branches.
namespace ot {
namespace transport_test {
namespace tr = oceantransport;
namespace pk = ofp::peek;
inline bool same(float a, float b) { return ofp::bits(a) == ofp::bits(b); }
inline bool same(Vec2 a, Vec2 b) { return same(a.x, b.x) && same(a.y, b.y); }
inline bool same(tr::Flow a, tr::Flow b) { return same(a.x, b.x) && same(a.y, b.y) && same(a.d, b.d); }
inline bool same(const OceanFood& a, const OceanFood& b) {
    return same(a.pos, b.pos) && same(a.depth, b.depth) && same(a.size, b.size) &&
           same(a.age, b.age) && a.alive == b.alive
#ifdef EVO_OCEAN_EYE
           && same(a.eyeCon, b.eyeCon)
#endif
           ;
}
inline tr::FlowState& state(OceanWorld& w) { return ofp::field<pk::OwFlowState>(w); }
inline void init(Test& t, OceanWorld& w, bool walls, int mode, float speed = 0.0f) {
    const std::string cfg = std::string(R"({"minPopulation":0,"targetFood":0,"foodSpawnBase":0,"foodSpawnAmp":0,"currentStrength":30,"currentDrift":30,"currentCore":40,"foodDrift":true,"deepCurrent":true,"walls":)") +
        (walls ? "true" : "false") + ",\"currentMode\":" + std::to_string(mode) +
        ",\"waveSpeed\":" + std::to_string(speed) + "}";
    std::string err;
    if (!ofp::initWorld(w, 1901, 320, 240, 120.0f, 0, cfg.c_str(), err))
        throw std::runtime_error("transport test fixture: " + err);
}
#ifdef EVO_OCEAN_EYE
inline float contrast(float d) { return ocean::eyeContrast(ocean::kEyeFoodBright, d); }
#endif
inline void kernel(const tr::FlowState& s, const tr::TransportParams& p, std::uint64_t frame,
                   float dt, const std::vector<OceanFood>& in, std::vector<OceanFood>& out) {
    std::vector<int> idx;
    tr::transportFood(s, p, frame, dt, std::span<const OceanFood>(in), std::span<OceanFood>(out), idx
#ifdef EVO_OCEAN_EYE
                      , contrast
#endif
    );
}
} // namespace transport_test

void testTransportReaders() {
    Test t("flow_readers");
    using namespace transport_test;
    const Vec2 p{83.0f, 71.0f};
    const float d = 27.0f;
    // Each reader gets its OWN untouched lazy world: no earlier fingerprint or
    // other reader may accidentally prepare it. Repeat after an update while
    // still never prepared, then after an on/off/on pause and direct edits.
    for (bool walls : {false, true}) for (int mode : {0, 1}) for (int reader = 0; reader < 7; ++reader) {
        OceanWorld eager, lazy;
        init(t, eager, walls, mode, 6.0f);
        init(t, lazy, walls, mode);
        auto read = [&](const OceanWorld& w) -> tr::Flow {
            switch (reader) {
                case 0: return w.flowAt(p, d);
                case 1: return w.flowExactAt(p, d);
                case 2: { const auto c = w.currentAt(p); return {c.x, c.y, 0.0f}; }
                case 3: return w.currentFlowAt(p, d);
                case 4: return w.waveTrainAt(1, p, d);
                case 5: return w.waveTrainExactAt(1, p, d);
                default: return w.waveTrainExactAt(1, p, d, w.taperAt(d));
            }
        };
        for (int phase = 0; phase < 3; ++phase) {
            if (phase == 1) {
                // Re-init waves off and advance once: first enable after update.
                init(t, eager, walls, mode); init(t, lazy, walls, mode);
                eager.update(.016f); lazy.update(.016f);
                t.expect(state(lazy).waves[0].frac == 0.0f, "off update prepared waves");
                eager.ocfg.waveSpeed = 6.0f;
                (void)eager.flowAt(p, d); // reference preparation
            } else if (phase == 2) {
                eager.update(.032f); lazy.update(.032f);
                const double clock = lazy.wavePhase(0);
                eager.ocfg.waveSpeed = lazy.ocfg.waveSpeed = 0.0f;
                eager.update(.032f); lazy.update(.032f);
                t.expect(lazy.wavePhase(0) == clock, "disabled wave clock advanced");
                eager.ocfg.waveSpeed = 9.0f;
                eager.ocfg.waveBand = lazy.ocfg.waveBand = 13.0f;
                eager.ocfg.waveGravity = lazy.ocfg.waveGravity = 700.0f;
            }
            const auto rngBefore = rng.state();
            lazy.ocfg.waveSpeed = eager.ocfg.waveSpeed;
            const auto u = read(lazy), v = read(eager);
            t.expect(same(u, v), "walls=%d mode=%d reader=%d phase=%d differs", walls, mode, reader, phase);
            // The preview/gyre currentAt early return never reads waves. Keep
            // that original behavior; its next update prepares them instead.
            const bool prepares = reader != 2 || walls || mode != 1 || phase == 2;
            t.expect(state(lazy).waves[0].frac == (prepares ? .5f : 0.0f),
                     "reader=%d changed lazy preparation semantics", reader);
            t.expect(rng.state() == rngBefore, "reader drew RNG");
            for (int i = 0; i < tr::kWaveTrains; ++i)
                t.expect(ofp::bits64(lazy.wavePhase(i)) == ofp::bits64(eager.wavePhase(i)), "reader changed phase");
        }
        // These current-only exact readers deliberately do not prepare waves.
        t.expect(same(lazy.currentExactAt(p), state(lazy).current.velocityAt(p)), "exact current wrapper differs");
        t.expect(same(lazy.currentFlowExactAt(p, d), tr::currentFlowExactAt(state(lazy), lazy.transportParams(), lazy.frame, p, d)),
                 "exact depth-weighted current wrapper differs");
    }
}

void testTransportState() {
    Test t("flow_state");
    using namespace transport_test;
    for (bool walls : {false, true}) {
        OceanWorld owner;
        init(t, owner, walls, 0, 6.0f);
        const auto params = owner.transportParams();
        tr::ensureFlow(state(owner), params, owner.frame);
        for (const auto& e : state(owner).cache.eddies)
            t.expect(e.cx == 0.0f && e.cy == 0.0f, "frame-zero reader advanced current");
        tr::FlowState future = state(owner);
        constexpr std::uint64_t target = 123;
        const auto rngBefore = rng.state();
        tr::advanceFlowClock(future, params, target, .032f);
        tr::ensureFlow(future, params, target);
        CurrentField reference = state(owner).current;
        reference.advance(target);
        const auto& centers = ofp::field<pk::CfCenters>(reference);
        bool moved = false;
        for (std::size_t i = 0; i < centers.size(); ++i) {
            t.expect(same(Vec2{future.cache.eddies[i].cx, future.cache.eddies[i].cy}, centers[i]),
                     "explicit target frame lost at eddy %zu (owner=%llu target=%llu)", i,
                     (unsigned long long)owner.frame, (unsigned long long)target);
            moved |= centers[i].x != 0.0f || centers[i].y != 0.0f;
        }
        t.expect(moved && owner.frame == 0 && !state(owner).cache.curAdvanced && owner.wavePhase(0) == 0.0,
                 "future state changed the owner or fixture did not move");
        t.expect(rng.state() == rngBefore, "future clock/cache drew RNG");
        // Advancing at target zero must be distinguishable from never advanced.
        tr::FlowState zero = state(owner);
        tr::advanceFlowClock(zero, params, 0, .016f);
        tr::ensureFlow(zero, params, 0);
        reference.advance(0);
        for (std::size_t i = 0; i < centers.size(); ++i)
            t.expect(same(Vec2{zero.cache.eddies[i].cx, zero.cache.eddies[i].cy}, centers[i]), "curAdvanced omitted at frame zero");
        // Both construction and assignment own all mutable storage. Mutate the
        // copies as well as checking addresses, including each depth piece.
        auto checkCopy = [&](tr::FlowState copy) {
            auto independent = [&](auto& a, auto& b, const char* name) {
                t.expect(!a.empty() && a.size() == b.size() && a.data() != b.data(), "%s aliases or was dropped", name);
                if (!a.empty() && !b.empty()) {
                    const auto saved = b[0];
                    a[0] = std::remove_cv_t<decltype(saved)>{};
                    t.expect(std::memcmp(&saved, &b[0], sizeof saved) == 0, "%s mutation reached owner", name);
                }
            };
            independent(copy.cache.vort, future.cache.vort, "vort");
            independent(copy.cache.eddies, future.cache.eddies, "eddies");
            independent(copy.cache.psiScale, future.cache.psiScale, "psiScale");
            independent(copy.cache.yRot, future.cache.yRot, "yRot");
            for (int q = 0; q < 4; ++q) independent(copy.cache.piece[q].cell, future.cache.piece[q].cell, "depth cells");
            independent(ofp::field<pk::CfCenters>(copy.current), ofp::field<pk::CfCenters>(future.current), "current centers");
            const auto vort = future.current.vortexState();
            auto changed = copy.current.vortexState(); changed[0] += 1.0f;
            t.expect(copy.current.restoreVortexState(changed) && future.current.vortexState() == vort, "current vortices shared");
        };
        checkCopy(future);
        tr::FlowState assigned; assigned = future; checkCopy(assigned);
    }
    // Preserve actual derived gyre values, even when different from config.
    // A reconstruction from params or vortices is NOT a copy of CurrentField.
    OceanWorld owner;
    init(t, owner, true, 1, 6.0f);
    auto& s = state(owner);
    ofp::field<pk::CfGyreA>(s.current) *= 1.25f;
    ofp::field<pk::CfGyreOmega>(s.current) *= 1.5f;
    ofp::field<pk::CfGyreT>(s.current) = 173.25f;
    const auto params = owner.transportParams();
    tr::ensureFlow(s, params, 0);
    auto checkGyre = [&](const tr::FlowState& c) {
        t.expect(same(ofp::field<pk::CfGyreA>(c.current), ofp::field<pk::CfGyreA>(s.current)), "copy lost gyreA_");
        t.expect(same(ofp::field<pk::CfGyreOmega>(c.current), ofp::field<pk::CfGyreOmega>(s.current)), "copy lost gyreOmega_");
        t.expect(same(ofp::field<pk::CfGyreT>(c.current), ofp::field<pk::CfGyreT>(s.current)), "copy lost gyreT_");
        const Vec2 p{21.0f, 71.0f};
        t.expect(same(c.current.velocityAt(p), s.current.velocityAt(p)) &&
                 same(c.current.gyreStreamAt(p), s.current.gyreStreamAt(p)) &&
                 same(tr::flowAt(c, params, 0, p, 27.0f), owner.flowAt(p, 27.0f)), "copied gyre flow changed");
    };
    tr::FlowState copied = s; checkGyre(copied);
    tr::FlowState assigned; assigned = s; checkGyre(assigned);
}

void testTransportKernel() {
    Test t("transport_food");
    using namespace transport_test;
    long depthChanges = 0;
    for (int branch = 0; branch < 5; ++branch) for (int mode : {0, 1}) {
        OceanWorld w;
        init(t, w, branch == 0 || branch == 4, mode, branch < 2 ? 6.0f : 0.0f);
        auto params = w.transportParams();
        if (branch >= 2) params.deepCurrent = false;
        if (branch == 3) params.foodDrift = false;
        if (branch == 4) { params.currentStrength = 0.0f; state(w).current = CurrentField{}; }
        tr::advanceFlowClock(state(w), params, 37, .032f);
        tr::ensureFlow(state(w), params, 37);
        const auto rngBefore = rng.state();
        for (int count : {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 15, 16, 17}) for (float dt : {0.0f, .016f, .032f, .5f}) {
            std::vector<OceanFood> input(count);
            for (int i = 0; i < count; ++i) {
                auto& f = input[i];
                f.pos = {10.0f + 13.0f * i, 11.0f + 9.0f * i}; f.depth = 2.0f + 5.0f * i;
                f.alive = i % 5 != 3; f.size = .25f + i; f.age = 10.0f + i;
#ifdef EVO_OCEAN_EYE
                f.eyeCon = 17.0f + i; // held exactly unless depth changes
#endif
            }
            auto expected = input;
            for (auto& f : expected) {
                if (!params.foodDrift || !f.alive) continue;
                const float z0 = f.depth;
                if (params.walls) {
                    if (!tr::wallFlowOn(state(w), params, 37)) continue;
                    const auto fs = tr::wallFoodSteps(state(w), params, 37, dt);
                    tr::wallAdvect(state(w), params, 37, f.pos, f.depth, fs.dt, fs.n);
                } else if (tr::flowE1(state(w), params, 37)) {
                    const auto u = tr::flowAt(state(w), params, 37, f.pos, f.depth);
                    f.pos.x = OceanWorld::wrapCoord(f.pos.x + u.x * dt, (float)params.width);
                    f.pos.y = OceanWorld::wrapCoord(f.pos.y + u.y * dt, (float)params.height);
                    f.depth = std::clamp(f.depth + u.d * dt, 0.0f, params.D);
                } else if (state(w).current.active()) {
                    const auto v = state(w).current.velocityAt(f.pos);
                    f.pos.x += v.x * dt; f.pos.y += v.y * dt;
                    f.pos.x = OceanWorld::wrapPreview(f.pos.x, (float)params.width);
                    f.pos.y = OceanWorld::wrapPreview(f.pos.y, (float)params.height);
                }
                depthChanges += f.depth != z0;
#ifdef EVO_OCEAN_EYE
                if (f.depth != z0) f.eyeCon = contrast(f.depth);
#endif
            }
            const auto saved = input;
            std::vector<OceanFood> out(count);
            kernel(state(w), params, 37, dt, input, out);
            for (int i = 0; i < count; ++i) {
                t.expect(same(input[i], saved[i]), "separate kernel wrote input");
                t.expect(same(out[i], expected[i]), "branch=%d mode=%d count=%d dt=%g item=%d separate differs", branch, mode, count, (double)dt, i);
            }
            kernel(state(w), params, 37, dt, input, input);
            for (int i = 0; i < count; ++i) t.expect(same(input[i], expected[i]), "in-place differs at %d", i);
        }
        t.expect(rng.state() == rngBefore, "kernel drew RNG");
    }
    // E1 with zero sampled velocity still executes wrap/clamp, even at dt=0.
    OceanWorld w; init(t, w, false, 0);
    auto params = w.transportParams(); state(w).current = CurrentField{};
    tr::ensureFlow(state(w), params, 0);
    OceanFood f; f.pos = {-1.0f, 241.0f}; f.depth = 121.0f; f.alive = true;
#ifdef EVO_OCEAN_EYE
    f.eyeCon = 17.0f;
#endif
    const std::vector<OceanFood> in{f}; std::vector<OceanFood> out(1);
    kernel(state(w), params, 0, 0.0f, in, out);
    t.expect(out[0].pos.x == 319.0f && out[0].pos.y == 1.0f && out[0].depth == 120.0f, "zero-velocity E1 skipped wrap/clamp");
#ifdef EVO_OCEAN_EYE
    t.expect(same(out[0].eyeCon, contrast(120.0f)), "clamped depth kept stale contrast");
#endif
    params.deepCurrent = false;
    kernel(state(w), params, 0, .016f, in, out);
    t.expect(same(out[0], in[0]), "inactive preview branch should preserve input");
    t.expect(depthChanges > 0, "no changed-depth contrast coverage");
}
} // namespace ot

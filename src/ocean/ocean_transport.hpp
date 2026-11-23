#pragma once
// Ocean-only flow state and synchronous food transport. No world, RNG or scheduling
// dependency: callers supply a copied parameter value and an explicit target frame.
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <span>
#include <vector>
#include "../core/current.hpp"
#include "ocean_flow.hpp"

namespace oceantransport {
inline constexpr int kWaveTrains = oceanflow::kTrains;
inline constexpr double kTwoPi = 6.283185307179586;
inline constexpr int kWallFoodMaxSubsteps = 16;
struct Flow { float x = 0.0f, y = 0.0f, d = 0.0f; };
struct Taper { float B, Bp; };
struct FoodSteps { int n; float dt; double need; };
struct WaveTrain {
    double kx = 0.0, ky = 0.0, phase = 0.0, phi = 0.0;
    float k = 1.0f, qx = 1.0f, qy = 0.0f, frac = 0.0f;
};
struct FlowState {
    // Value copying carries ALL CurrentField state, including gyreA_,
    // gyreOmega_, gyreT_, vortex centres, and every mutable cache vector.
    CurrentField current;
    mutable WaveTrain waves[kWaveTrains];
    mutable oceanflow::FlowCache cache;
};
typedef int v4i __attribute__((vector_size(16)));
struct TransportParams {
    int width, height;
    float D;
    float currentCore;
    float currentDrift;
    int currentEddies;
    float currentGyreEps;
    int currentMode;
    float currentStrength;
    bool deepCurrent;
    bool foodDrift;
    bool toroidal;
    bool walls;
    float waveBand;
    float waveGravity;
    float waveSpeed;
};

inline float wrapCoord(float v, float span);
inline float wrapPreview(float v, float span);
inline float clampDepth(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, float z);
inline bool wavesOn(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame);
inline bool flowE1(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame);
inline float smooth01(float r);
inline float smooth01d(float r);
inline Flow flowAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d);
inline Flow flowExactAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d);
inline Flow currentFlowAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d);
inline Flow currentFlowExactAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d);
inline Taper taperAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, float d);
inline Flow waveTrainAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, int i, Vec2 p, float d);
inline Flow waveTrainExactAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, int i, Vec2 p, float d);
inline Flow waveTrainExactAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, int i, Vec2 p, float d, const Taper& tp);
inline bool currentActive(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame);
inline Vec2 currentAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p);
inline Vec2 currentExactAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p);
inline bool wavesPrepared(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame);
inline void ensureWaves(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame);
inline void prepareWaves(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame);
inline void advanceWaves(FlowState& state, const TransportParams& params, std::uint64_t targetFrame, float dt);
inline void initFlowCache(FlowState& state, const TransportParams& params, std::uint64_t targetFrame);
inline std::uint32_t floatKey(float v);
inline void buildDepth(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame);
inline void ensureFlow(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame);
inline Vec2 eddyVelocity(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p);
inline Flow currentFlowFast(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d);
inline bool depthProfiles(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, float d, oceanflow::v4f& V, oceanflow::v4f& Vd);
inline bool cellCoord(float v, double scale, int N, int& i, float& t);
inline bool wavesTable(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d, Flow u[kWaveTrains]);
inline void wavesExact(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d, Flow u[kWaveTrains]);
inline Flow waveTrainFast(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, int i, Vec2 p, float d);
inline Flow flowFast(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d);
inline Flow flowStep(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d);
inline void wallTaper(float q, float L, float b, float& chi, float& dchi);
inline Vec2 wallCurrent(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p);
inline Flow wallCurrentFlow(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d);
inline void halfTurn(int mode, float v, double L, float& c, float& s);
inline Flow wallTrainExactAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, int i, Vec2 p, float d);
inline bool wallWavesTable(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d, Flow u[kWaveTrains]);
inline Flow wallFlowFast(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d);
inline Flow wallFlowExact(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d);
inline oceanflow::v4f sel4(v4i m, oceanflow::v4f a, oceanflow::v4f b);
inline oceanflow::v4f fold4(oceanflow::v4f q, float L);
inline oceanflow::v4f splat4(float x);
inline oceanflow::v4f smooth01v(oceanflow::v4f r);
inline oceanflow::v4f smooth01dv(oceanflow::v4f r);
inline void wallTaper4(oceanflow::v4f q, float L, float b, oceanflow::v4f& chi, oceanflow::v4f& dchi);
inline void wallCurrent4(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, oceanflow::v4f px, oceanflow::v4f py, oceanflow::v4f& outx, oceanflow::v4f& outy);
inline void wallFlowFast4(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, oceanflow::v4f px, oceanflow::v4f py, oceanflow::v4f pd,
                       oceanflow::v4f& ux, oceanflow::v4f& uy, oceanflow::v4f& ud);
inline FoodSteps wallFoodSteps(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, float dt);
inline float mirrorFold(float q, float L);
inline void wallAdvect(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2& p, float& d, float dt, int n);
inline void wallAdvect4(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p[4], float d[4], float dt, int n);
inline bool wallFlowOn(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame);
inline int wallFoodSubstepsNow(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, float dt);
inline FoodSteps wallFoodStepsNow(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, float dt);

inline float wrapCoord(float v, float span) {
    if (v >= -span && v < 2.0f * span) {
        if (v < 0.0f) v += span;
        if (v >= span) v -= span;
        return v;
    }
    float r = std::fmod(v, span);   // exact; the sign of v, |r| < span
    if (r < 0.0f) r += span;        // the loops' last add
    else if (r == 0.0f) r = 0.0f;   // -0 -> +0, as that add gives
    if (r >= span) r -= span;
    return r;
}

inline float wrapPreview(float v, float span) {
    if (v < -span || v >= 2.0f * span) return wrapCoord(v, span);
    if (v < 0.0f) v += span;
    else if (v >= span) v -= span;
    return v;
}

inline float clampDepth(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, float z) { return std::clamp(z, 0.0f, params.D); }

inline bool wavesOn(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame) { return params.waveSpeed > 0.0f; }

inline bool flowE1(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame) { return wavesOn(state, params, targetFrame) || params.deepCurrent; }

inline float smooth01(float r) {
    r = std::clamp(r, 0.0f, 1.0f);
    return r * r * (3.0f - 2.0f * r);
}

inline float smooth01d(float r) {
    r = std::clamp(r, 0.0f, 1.0f);
    return 6.0f * r * (1.0f - r);
}

inline Flow flowAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d) {
    if (params.walls) { ensureFlow(state, params, targetFrame); return wallFlowFast(state, params, targetFrame, p, d); }
    if (!flowE1(state, params, targetFrame)) return flowExactAt(state, params, targetFrame, p, d);
    ensureFlow(state, params, targetFrame);
    return flowFast(state, params, targetFrame, p, d);
}

inline Flow flowExactAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d) {
    if (params.walls) { ensureFlow(state, params, targetFrame); return wallFlowExact(state, params, targetFrame, p, d); }
    Flow U = currentFlowExactAt(state, params, targetFrame, p, d);
    if (wavesOn(state, params, targetFrame)) {
        ensureWaves(state, params, targetFrame);   // (waves switched on by a direct config change, nothing read since)
        const Taper tp = taperAt(state, params, targetFrame, d);
        for (int i = 0; i < kWaveTrains; ++i) {
            const Flow u = waveTrainExactAt(state, params, targetFrame, i, p, d, tp);
            U.x += u.x;
            U.y += u.y;
            U.d += u.d;
        }
    }
    return U;
}

inline Flow currentFlowAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d) {
    if (params.walls) { ensureFlow(state, params, targetFrame); return wallCurrentFlow(state, params, targetFrame, p, d); }
    if (!flowE1(state, params, targetFrame)) return currentFlowExactAt(state, params, targetFrame, p, d);
    ensureFlow(state, params, targetFrame);
    return currentFlowFast(state, params, targetFrame, p, d);
}

inline Flow currentFlowExactAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d) {
    Flow U;
    if (state.current.active()) {
        const Vec2 c = state.current.velocityAt(p);
        const float f = params.deepCurrent ? smooth01(2.0f * d / params.D) : 1.0f;
        U.x = f * c.x;
        U.y = f * c.y;
    }
    return U;
}

inline Taper taperAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, float d) {
    const float b = std::min(params.waveBand, 0.25f * params.D);
    const float r1 = d / b, r2 = (params.D - d) / b;
    const float s1 = smooth01(r1), s2 = smooth01(r2);
    Taper tp;
    tp.B = s1 * s2;
    tp.Bp = (smooth01d(r1) * s2 - s1 * smooth01d(r2)) / b;
    return tp;
}

inline Flow waveTrainAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, int i, Vec2 p, float d) {
    if (params.walls) {
        if (!wavesOn(state, params, targetFrame)) return Flow{};
        ensureFlow(state, params, targetFrame);
        Flow u[kWaveTrains];
        return wallWavesTable(state, params, targetFrame, p, d, u) ? u[i] : wallTrainExactAt(state, params, targetFrame, i, p, d);
    }
    if (!flowE1(state, params, targetFrame)) return waveTrainExactAt(state, params, targetFrame, i, p, d);
    ensureFlow(state, params, targetFrame);
    return waveTrainFast(state, params, targetFrame, i, p, d);
}

inline Flow waveTrainExactAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, int i, Vec2 p, float d) {
    if (params.walls) return wallTrainExactAt(state, params, targetFrame, i, p, d);
    ensureWaves(state, params, targetFrame);
    return waveTrainExactAt(state, params, targetFrame, i, p, d, taperAt(state, params, targetFrame, d));
}

inline Flow waveTrainExactAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, int i, Vec2 p, float d, const Taper& tp) {
    ensureWaves(state, params, targetFrame);   // public: it may be the first reader after the waves came on directly
    const WaveTrain& t = state.waves[i];
    const float B = tp.B, Bp = tp.Bp;
    const float A = t.frac * params.waveSpeed;
    // e^{−kd} as 1 / e^{kd}: full relative precision at depth, where
    // expm1f(−kd) + 1 would keep only ~1e-7 absolute (e^{kd} = inf -> 0).
    const float E = 1.0f / (evomath::expm1f(t.k * d) + 1.0f);
    double th = t.kx * (double)p.x + t.ky * (double)p.y - t.phase + t.phi;
    th -= kTwoPi * std::floor(th / kTwoPi);
    const float tf = (float)th;
    const float sn = evomath::sinf(tf), cs = evomath::cosf(tf);
    const float uh = A * E * (B - Bp / t.k) * cs;
    Flow u;
    u.x = t.qx * uh;
    u.y = t.qy * uh;
    u.d = -A * E * B * sn;
    return u;
}

inline bool currentActive(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame) { return state.current.active(); }

inline Vec2 currentAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p) {
    if (params.walls) { ensureFlow(state, params, targetFrame); return wallCurrent(state, params, targetFrame, p); }   // glass walls: the tapered current
    if (!flowE1(state, params, targetFrame) || !state.cache.curOn) return state.current.velocityAt(p);
    ensureFlow(state, params, targetFrame);
    return eddyVelocity(state, params, targetFrame, p);
}

inline Vec2 currentExactAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p) { return state.current.velocityAt(p); }

inline bool wavesPrepared(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame) { return state.waves[0].frac != 0.0f; }

inline void ensureWaves(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame) { if (wavesOn(state, params, targetFrame) && !wavesPrepared(state, params, targetFrame)) prepareWaves(state, params, targetFrame); }

inline void prepareWaves(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame) {
    const auto& kModes = oceanflow::kWaveModes;   // the flow tables are built from the same modes
    static const float kFrac[kWaveTrains] = {0.5f, 0.3f, 0.2f};
    for (int i = 0; i < kWaveTrains; ++i) {
        WaveTrain& t = state.waves[i];
        t.kx = kTwoPi * kModes[i][0] / (double)params.width;
        t.ky = kTwoPi * kModes[i][1] / (double)params.height;
        const double k = std::sqrt(t.kx * t.kx + t.ky * t.ky);
        t.k = (float)k;
        t.qx = (float)(t.kx / k);
        t.qy = (float)(t.ky / k);
        t.frac = kFrac[i];
        t.phi = (double)i;   // 0, 1, 2 rad
        t.phase = 0.0;
    }
    // The flow cache's wave part (initFlowCache leaves it empty): T = K / |K|²,
    // and in cell units (∂/∂x = d/dt · kXCells / W); the depth pieces and the
    // phase factors are (re)built by the next ensureFlow from these modes.
    oceanflow::FlowCache& c = state.cache;
    c.xScale = (double)oceanflow::kXCells / (double)params.width;
    c.yScale = (double)oceanflow::kYCells / (double)params.height;
    for (int i = 0; i < kWaveTrains; ++i) {
        const WaveTrain& t = state.waves[i];
        const double kk = t.kx * t.kx + t.ky * t.ky;
        c.Tx[i] = (float)(t.kx / kk);
        c.Ty[i] = (float)(t.ky / kk);
        c.TxS[i] = (float)(t.kx / kk * c.xScale);
        c.TyS[i] = (float)(t.ky / kk * c.yScale);
        // The glass walls' quadrature pair (ocean_flow.hpp wallModeA / B;
        // read only with walls on): F = −V / k² with the primary's k (the
        // periodic train's); the neighbour (wavenumber kb) is weighted
        // ka / kb, which makes the bulk orbit circular where one mode's
        // slope and the other's value vanish; and an oblique pair (both
        // mode numbers non-zero: a standing product averages cos²·cos² =
        // 1/4 against the travelling train's 1/2) is weighted √2, so the
        // pair's mean square speed is the periodic train's.
        const double kbx = kTwoPi * 0.5 * (double)oceanflow::wallModeB(i, 0) / (double)params.width;
        const double kby = kTwoPi * 0.5 * (double)oceanflow::wallModeB(i, 1) / (double)params.height;
        const double kb = std::sqrt(kbx * kbx + kby * kby), ka = std::sqrt(kk);   // IEEE sqrt: portable
        const double g = (kModes[i][0] != 0 && kModes[i][1] != 0) ? 1.4142135623730951 : 1.0;
        c.wInvK2[i] = (float)(1.0 / kk);
        c.wAmpA[i] = (float)g;
        c.wAmpB[i] = (float)(g * ka / kb);
    }
    c.wxS = (float)((double)oceanflow::kXCells / (double)params.width);
    c.wyS = (float)((double)oceanflow::kYCells / (double)params.height);
    c.yRot.assign(oceanflow::kYCells, oceanflow::TrigV{});
    c.depthKeyed = false;
    c.phaseKeyed = false;
}

inline void advanceWaves(FlowState& state, const TransportParams& params, std::uint64_t targetFrame, float dt) {
    for (WaveTrain& t : state.waves) {
        t.phase += std::sqrt((double)params.waveGravity * (double)t.k) * (double)dt;
        while (t.phase >= kTwoPi) t.phase -= kTwoPi;
    }
}

inline void initFlowCache(FlowState& state, const TransportParams& params, std::uint64_t targetFrame) {
    state.cache = oceanflow::FlowCache{};
    // CurrentField::init's own: eddies unless mode 1, nothing at strength <= 0,
    // core_ = max(core, 1); velocityAt's inv2c2 and scale.
    if (params.currentMode != 1 && params.currentStrength > 0.0f) {
        state.cache.curOn = true;
        const float core = (params.currentCore > 1.0f) ? params.currentCore : 1.0f;
        state.cache.inv2c2 = 1.0f / (2.0f * core * core);
        const float scale = params.currentStrength / core * 1.6487212707f;
        state.cache.vort = state.current.vortexState();
        state.cache.eddies.resize(state.cache.vort.size() / CurrentField::VORTEX_FLOATS);
        for (std::size_t i = 0; i < state.cache.eddies.size(); ++i)
            state.cache.eddies[i].signScale = state.cache.vort[i * CurrentField::VORTEX_FLOATS + 2] * scale;
        // The glass walls' streamfunction prefactor per eddy: psi = signScale · core² · G(u).
        state.cache.psiScale.resize(state.cache.eddies.size());
        for (std::size_t i = 0; i < state.cache.eddies.size(); ++i) state.cache.psiScale[i] = state.cache.eddies[i].signScale * (core * core);
    }
    // The glass walls' current taper band (eddies and gyre alike).
    {
        const float core = (params.currentCore > 1.0f) ? params.currentCore : 1.0f;
        state.cache.wallBc = std::min(core, std::min(0.25f * (float)params.width, 0.25f * (float)params.height));
    }
    // The waves' part is prepareWaves' (when the waves are first on).
}

inline std::uint32_t floatKey(float v) { std::uint32_t u; std::memcpy(&u, &v, 4); return u; }

inline void buildDepth(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame) {
    oceanflow::FlowCache& c = state.cache;
    c.depthOn = false;
    const float b = std::min(params.waveBand, 0.25f * params.D);   // taperAt's
    const float Dh = 0.5f * params.D, Dmb = params.D - b;
    const float lo[4] = {0.0f, b, Dh, Dmb}, hi[4] = {b, Dh, Dmb, params.D};
    float kMax = 0.0f;
    for (const WaveTrain& t : state.waves) kMax = std::max(kMax, t.k);
    // Cell counts in double, checked before any conversion or allocation.
    double cells[4], total = 0.0;
    for (int q = 0; q < 4; ++q) {
        const double L = (double)hi[q] - (double)lo[q];
        if (!(L > 0.0)) return;   // a degenerate piece (unvalidated band): the exact formulas
        const int least = (q == 0 || q == 3) ? oceanflow::kDepthCellsBand : oceanflow::kDepthCellsMin;
        cells[q] = std::max((double)least, std::ceil((double)kMax * L / oceanflow::kDepthKCell));
        total += cells[q];
    }
    if (!(total <= oceanflow::kDepthCellsMax)) return;   // NaN too
    for (int q = 0; q < 4; ++q) {
        oceanflow::DepthPiece& pc = c.piece[q];
        const int n = (int)cells[q];
        const double L = (double)hi[q] - (double)lo[q], h = L / (double)n;
        pc.lo = lo[q];
        pc.n = n;
        pc.scale = (double)n / L;
        pc.dScale = (float)pc.scale;
        // waveTrainExactAt's own expressions at depth x: H = A e^{−kx} (B − B'/k)
        // (u_h without cos θ) and V = −A e^{−kx} B; both exactly 0 at the
        // surface and the floor (no flow through either).
        auto HV = [&](int i, float x, float& H, float& V) {
            const WaveTrain& t = state.waves[i];
            const Taper tp = taperAt(state, params, targetFrame, x);
            const float A = t.frac * params.waveSpeed;
            const float E = 1.0f / (evomath::expm1f(t.k * x) + 1.0f);
            H = A * E * (tp.B - tp.Bp / t.k);
            V = -A * E * tp.B;
            if (x == 0.0f || x == params.D) { H = 0.0f; V = 0.0f; }
        };
        // Node j: at the ideal position lo + h·j (atD, double; the piece's
        // ends exactly), and that position as the float the formulas take
        // (at). The lookup (depthProfiles: (d − lo)·scale) and the slopes
        // (h·k·H) both use the ideal grid, so the rise is integrated over
        // the ideal cell too: integrated between the float-rounded nodes it
        // carried their rounding into the derivative (rise / h), 0.25% of
        // V' in the 0.008-wide cells of a 1.01 band at params.D 240.
        auto atD = [&](int j) { return (j == n) ? (double)hi[q] : (double)lo[q] + h * (double)j; };
        auto at = [&](int j) { return (j == 0) ? lo[q] : (j == n) ? hi[q] : (float)atD(j); };
        pc.cell.assign((std::size_t)n, oceanflow::DepthCell{});
        for (int j = 0; j < n; ++j) {
            const float d0 = at(j), d1 = at(j + 1);
            oceanflow::DepthCell& cl = pc.cell[j];
            for (int i = 0; i < kWaveTrains; ++i) {
                const double k = (double)state.waves[i].k;
                float H0, V0, H1, V1;
                HV(i, d0, H0, V0);
                HV(i, d1, H1, V1);
                // The rise V(d1) − V(d0) = ∫ k·H over the ideal cell: from H,
                // never from the two rounded V values (see oceanflow::hval).
                const double rise = oceanflow::gauss3(atD(j), atD(j + 1), [&](double x) {
                    float Hx, Vx;
                    HV(i, (float)x, Hx, Vx);
                    return k * (double)Hx;
                });
                cl.v[i] = V0;
                cl.dv[i] = (float)rise;
                cl.m0[i] = (float)(h * k * (double)H0);   // V' = k·H, per unit t
                cl.m1[i] = (float)(h * k * (double)H1);
            }
        }
    }
    c.b = b;
    c.Dh = Dh;
    c.Dmb = Dmb;
    c.depthOn = true;
}

inline void ensureFlow(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame) {
    oceanflow::FlowCache& c = state.cache;
    ensureWaves(state, params, targetFrame);
    // The waves' depth pieces: rebuilt when waveSpeed, waveBand or params.D move.
    // Only for prepared waves (never on: nothing reads them, wavesOn(state, params, targetFrame) is false).
    if (wavesPrepared(state, params, targetFrame)) {
        const std::uint32_t ks = floatKey(params.waveSpeed), kb = floatKey(params.waveBand), kd = floatKey(params.D);
        if (!c.depthKeyed || ks != c.keySpeed || kb != c.keyBand || kd != c.keyD) {
            buildDepth(state, params, targetFrame);
            c.depthKeyed = true;
            c.keySpeed = ks;
            c.keyBand = kb;
            c.keyD = kd;
        }
    }
    // The phase factors: regenerated when a phase moves (every step while
    // the waves run; frozen with the clock), from the static base.
    if (wavesPrepared(state, params, targetFrame)) {
        bool same = c.phaseKeyed;
        std::uint64_t kp[kWaveTrains];
        for (int i = 0; i < kWaveTrains; ++i) {
            std::memcpy(&kp[i], &state.waves[i].phase, 8);
            same = same && kp[i] == c.keyPhase[i];
        }
        if (!same) {
            for (int i = 0; i < kWaveTrains; ++i) {
                oceanflow::cosSin(state.waves[i].phi - state.waves[i].phase, c.cp[i], c.sp[i]);
                c.keyPhase[i] = kp[i];
            }
            const oceanflow::TrigV* base = oceanflow::yBaseTable().cell;
            const oceanflow::TrigCell lane0 = {c.cp[0], 0.0f, 0.0f, 0.0f, c.sp[0], 0.0f, 0.0f, 0.0f};
            for (int j = 0; j < oceanflow::kYCells; ++j) {
                oceanflow::TrigV& y = c.yRot[j];
                oceanflow::setLane(y, 0, lane0);   // train 0 (n = 0): its constant y factor
                for (int i = 1; i < kWaveTrains; ++i) {
                    oceanflow::TrigCell r = oceanflow::getLane(base[j], i);
                    const float cr = c.cp[i], sr = c.sp[i];
                    oceanflow::rotate(r.c, r.s, cr, sr);
                    oceanflow::rotate(r.dc, r.ds, cr, sr);
                    oceanflow::rotate(r.mc0, r.ms0, cr, sr);
                    oceanflow::rotate(r.mc1, r.ms1, cr, sr);
                    oceanflow::setLane(y, i, r);
                }
            }
            c.phaseKeyed = true;
        }
    }
    if (c.curOn && (!c.curReady || c.curFrame != targetFrame || c.curAdvKey != c.curAdvanced)) {
        // CurrentField::advance(targetFrame)'s centres (vortexState(): base x, y,
        // sign, ax, ay, fx, fy, px, py), or 0 before the first advance.
        const float t = (float)targetFrame;
        for (std::size_t i = 0; i < c.eddies.size(); ++i) {
            const float* v = &c.vort[i * CurrentField::VORTEX_FLOATS];
            oceanflow::Eddy& e = c.eddies[i];
            if (c.curAdvanced) {
                e.cx = v[0] + v[3] * evomath::sinf(v[5] * t + v[7]);
                e.cy = v[1] + v[4] * evomath::sinf(v[6] * t + v[8]);
            } else {
                e.cx = 0.0f;
                e.cy = 0.0f;
            }
        }
        c.curReady = true;
        c.curFrame = targetFrame;
        c.curAdvKey = c.curAdvanced;
    }
}

inline Vec2 eddyVelocity(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p) {
    Vec2 v{0.0f, 0.0f};
    const float inv2c2 = state.cache.inv2c2;
    const float* E = oceanflow::radialTable().E;
    for (const oceanflow::Eddy& e : state.cache.eddies) {
        const float dx = p.x - e.cx;
        const float dy = p.y - e.cy;
        float g;
        if (!oceanflow::radial(E, (dx * dx + dy * dy) * inv2c2, g)) continue;
        const float f = e.signScale * g;
        v.x += f * (-dy);
        v.y += f * dx;
    }
    return v;
}

inline Flow currentFlowFast(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d) {
    Flow U;
    if (state.current.active()) {
        const Vec2 c = state.cache.curOn ? eddyVelocity(state, params, targetFrame, p) : state.current.velocityAt(p);
        const float f = params.deepCurrent ? smooth01(2.0f * d / params.D) : 1.0f;
        U.x = f * c.x;
        U.y = f * c.y;
    }
    return U;
}

inline bool depthProfiles(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, float d, oceanflow::v4f& V, oceanflow::v4f& Vd) {
    const oceanflow::FlowCache& c = state.cache;
    if (!c.depthOn) return false;
    if (!(d > 0.0f && d < params.D)) {
        if (!(d <= 0.0f || d >= params.D)) return false;   // NaN
        V = oceanflow::v4f{};                        // surface, floor, outside
        Vd = oceanflow::v4f{};
        return true;
    }
    const int q = (d <= c.b) ? 0 : (d <= c.Dh) ? 1 : (d <= c.Dmb) ? 2 : 3;
    const oceanflow::DepthPiece& pc = c.piece[q];
    const double s = ((double)d - (double)pc.lo) * pc.scale;   // in [0, n] (rounding aside)
    if (!(s >= 0.0 && s <= (double)pc.n + 0.5)) return false;
    int j = (int)s;
    if (j > pc.n - 1) j = pc.n - 1;
    const oceanflow::BasisV B = oceanflow::basisV((float)(s - (double)j));
    const oceanflow::DepthCell& cl = pc.cell[j];
    V = oceanflow::hval(B, cl.v, cl.dv, cl.m0, cl.m1);
    Vd = oceanflow::hder(B, cl.dv, cl.m0, cl.m1) * oceanflow::splat(pc.dScale);
    return true;
}

inline bool cellCoord(float v, double scale, int N, int& i, float& t) {
    double s = (double)v * scale;
    if (s < 0.0) s += (double)N;
    if (s >= (double)N) s -= (double)N;   // also s == N (the periodic end) -> 0
    if (!(s >= 0.0 && s < (double)N)) return false;
    i = (int)s;
    t = (float)(s - (double)i);
    return true;
}

inline bool wavesTable(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d, Flow u[kWaveTrains]) {
    using oceanflow::v4f;
    const oceanflow::FlowCache& c = state.cache;
    v4f V, Vd;
    if (!depthProfiles(state, params, targetFrame, d, V, Vd)) return false;
    int ix, iy;
    float tx, ty;
    if (!cellCoord(p.x, c.xScale, oceanflow::kXCells, ix, tx)) return false;
    if (!cellCoord(p.y, c.yScale, oceanflow::kYCells, iy, ty)) return false;
    const oceanflow::BasisV bx = oceanflow::basisV(tx), by = oceanflow::basisV(ty);
    const oceanflow::TrigV& X = oceanflow::xTable().cell[ix];
    const oceanflow::TrigV& Y = c.yRot[iy];   // lane 0: train 0's constant factor
    const v4f cx = oceanflow::hval(bx, X.c, X.dc, X.mc0, X.mc1);
    const v4f sx = oceanflow::hval(bx, X.s, X.ds, X.ms0, X.ms1);
    const v4f cxd = oceanflow::hder(bx, X.dc, X.mc0, X.mc1);   // per unit t
    const v4f sxd = oceanflow::hder(bx, X.ds, X.ms0, X.ms1);
    const v4f cy = oceanflow::hval(by, Y.c, Y.dc, Y.mc0, Y.mc1);
    const v4f sy = oceanflow::hval(by, Y.s, Y.ds, Y.ms0, Y.ms1);
    const v4f cyd = oceanflow::hder(by, Y.dc, Y.mc0, Y.mc1);
    const v4f syd = oceanflow::hder(by, Y.ds, Y.ms0, Y.ms1);
    const v4f P = cx * cy - sx * sy;
    const v4f gradT = c.TxS * (cxd * cy - sxd * sy) + c.TyS * (cx * cyd - sx * syd);   // T·∇P
    const v4f ux = (c.Tx * Vd) * P, uy = (c.Ty * Vd) * P, ud = (-V) * gradT;
    for (int i = 0; i < kWaveTrains; ++i) {
        u[i].x = ux[i];
        u[i].y = uy[i];
        u[i].d = ud[i];
    }
    return true;
}

inline void wavesExact(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d, Flow u[kWaveTrains]) {
    const Taper tp = taperAt(state, params, targetFrame, d);
    for (int i = 0; i < kWaveTrains; ++i) u[i] = waveTrainExactAt(state, params, targetFrame, i, p, d, tp);
}

inline Flow waveTrainFast(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, int i, Vec2 p, float d) {
    Flow u[kWaveTrains];
    if (!wavesTable(state, params, targetFrame, p, d, u)) return waveTrainExactAt(state, params, targetFrame, i, p, d);
    return u[i];
}

inline Flow flowFast(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d) {
    Flow U = currentFlowFast(state, params, targetFrame, p, d);
    if (wavesOn(state, params, targetFrame)) {
        Flow u[kWaveTrains];
        if (!wavesTable(state, params, targetFrame, p, d, u)) wavesExact(state, params, targetFrame, p, d, u);
        for (int i = 0; i < kWaveTrains; ++i) {
            U.x += u[i].x;
            U.y += u[i].y;
            U.d += u[i].d;
        }
    }
    return U;
}

inline Flow flowStep(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d) { return flowE1(state, params, targetFrame) ? flowFast(state, params, targetFrame, p, d) : flowExactAt(state, params, targetFrame, p, d); }

inline void wallTaper(float q, float L, float b, float& chi, float& dchi) {
    const float r1 = q / b, r2 = (L - q) / b;
    const float s1 = smooth01(r1), s2 = smooth01(r2);
    chi = s1 * s2;
    dchi = (smooth01d(r1) * s2 - s1 * smooth01d(r2)) / b;
}

inline Vec2 wallCurrent(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p) {
    if (!state.current.active()) return {0.0f, 0.0f};
    Vec2 C{0.0f, 0.0f};
    float psi = 0.0f;
    if (state.cache.curOn) {   // eddies: eddyVelocity's sum, plus the streamfunction alongside
        const float inv2c2 = state.cache.inv2c2;
        const float* E = oceanflow::radialTable().E;
        const float* G = oceanflow::radialIntTable().G;
        for (std::size_t k = 0; k < state.cache.eddies.size(); ++k) {
            const oceanflow::Eddy& e = state.cache.eddies[k];
            const float dx = p.x - e.cx;
            const float dy = p.y - e.cy;
            float g, Gu;
            if (!oceanflow::radialPsi(E, G, (dx * dx + dy * dy) * inv2c2, g, Gu)) continue;
            const float f = e.signScale * g;
            C.x += f * (-dy);
            C.y += f * dx;
            psi += state.cache.psiScale[k] * Gu;
        }
    } else {   // the double gyre: CurrentField's own velocity and streamfunction
        C = state.current.velocityAt(p);
        psi = state.current.gyreStreamAt(p);
    }
    float cx, dcx, cy, dcy;
    wallTaper(p.x, (float)params.width, state.cache.wallBc, cx, dcx);
    wallTaper(p.y, (float)params.height, state.cache.wallBc, cy, dcy);
    const float Q = cx * cy, Qx = dcx * cy, Qy = cx * dcy;
    return {Q * C.x - psi * Qy, Q * C.y + psi * Qx};
}

inline Flow wallCurrentFlow(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d) {
    Flow U;
    if (state.current.active()) {
        const Vec2 c = wallCurrent(state, params, targetFrame, p);
        const float f = params.deepCurrent ? smooth01(2.0f * d / params.D) : 1.0f;
        U.x = f * c.x;
        U.y = f * c.y;
    }
    return U;
}

inline void halfTurn(int mode, float v, double L, float& c, float& s) {
    if (mode == 0) { c = 1.0f; s = 0.0f; return; }
    double cyc = 0.5 * (double)mode * ((double)v / L);
    cyc -= std::floor(cyc);
    oceanflow::cosSin(kTwoPi * cyc, c, s);
    if (v == 0.0f || (double)v == L) s = 0.0f;
}

inline Flow wallTrainExactAt(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, int i, Vec2 p, float d) {
    if (!wavesOn(state, params, targetFrame)) return Flow{};
    ensureWaves(state, params, targetFrame);
    const WaveTrain& t = state.waves[i];
    const Taper tp = taperAt(state, params, targetFrame, d);
    const float A = t.frac * params.waveSpeed;
    const float E = 1.0f / (evomath::expm1f(t.k * d) + 1.0f);
    const float ik2 = (float)(1.0 / (t.kx * t.kx + t.ky * t.ky));
    const float F = A * ik2 * E * tp.B;
    const float Fd = A * ik2 * E * (tp.Bp - t.k * tp.B);
    float cp, sp;
    oceanflow::cosSin(t.phi - t.phase, cp, sp);
    Flow u;
    for (int ab = 0; ab < 2; ++ab) {
        const int mx = ab ? oceanflow::wallModeB(i, 0) : oceanflow::wallModeA(i, 0);
        const int my = ab ? oceanflow::wallModeB(i, 1) : oceanflow::wallModeA(i, 1);
        const float kx = (float)(kTwoPi * 0.5 * (double)mx / (double)params.width);
        const float ky = (float)(kTwoPi * 0.5 * (double)my / (double)params.height);
        float cx, sx, cy, sy;
        halfTurn(mx, p.x, (double)params.width, cx, sx);
        halfTurn(my, p.y, (double)params.height, cy, sy);
        const float tau = (ab ? sp * state.cache.wAmpB[i] : cp * state.cache.wAmpA[i]);
        const float Px = -kx * sx * cy, Py = -ky * cx * sy;
        const float lap = -((kx * kx + ky * ky) * (cx * cy));
        u.x += (Fd * tau) * Px;
        u.y += (Fd * tau) * Py;
        u.d += -(F * tau) * lap;
    }
    return u;
}

inline bool wallWavesTable(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d, Flow u[kWaveTrains]) {
    using oceanflow::v4f;
    using oceanflow::splat;
    const oceanflow::FlowCache& c = state.cache;
    v4f V, Vd;
    if (!depthProfiles(state, params, targetFrame, d, V, Vd)) return false;
    int ix, iy;
    float tx, ty;
    if (!oceanflow::wallCellCoord(p.x, (double)params.width, oceanflow::kXCells, ix, tx)) return false;
    if (!oceanflow::wallCellCoord(p.y, (double)params.height, oceanflow::kYCells, iy, ty)) return false;
    const oceanflow::WallAxisTable& XT = oceanflow::wallXTable();
    const oceanflow::WallAxisTable& YT = oceanflow::wallYTable();
    const oceanflow::Eval5V xa = oceanflow::eval5(tx, XT.A[ix]), xb = oceanflow::eval5(tx, XT.B[ix]);
    const oceanflow::Eval5V ya = oceanflow::eval5(ty, YT.A[iy]), yb = oceanflow::eval5(ty, YT.B[iy]);
    // ∂x, ∂y in world units; on a face its normal slope is pinned to exactly 0
    // (sin(0) = sin(μπ) = 0: at t = 1 the Horner sum gives it only to rounding)
    const v4f sx = splat((p.x == 0.0f || p.x == (float)params.width) ? 0.0f : c.wxS);
    const v4f sy = splat((p.y == 0.0f || p.y == (float)params.height) ? 0.0f : c.wyS);
    const v4f sxx = splat(c.wxS * c.wxS), syy = splat(c.wyS * c.wyS);
    const v4f axd = xa.d * sx, bxd = xb.d * sx, ayd = ya.d * sy, byd = yb.d * sy;
    const v4f axs = xa.s * sxx, bxs = xb.s * sxx, ays = ya.s * syy, bys = yb.s * syy;
    const v4f cpv = {c.cp[0], c.cp[1], c.cp[2], 0.0f}, spv = {c.sp[0], c.sp[1], c.sp[2], 0.0f};
    const v4f F = (-V) * c.wInvK2, Fd = (-Vd) * c.wInvK2;
    const v4f ta = c.wAmpA * cpv, tb = c.wAmpB * spv;
    const v4f FdA = Fd * ta, FdB = Fd * tb, FA = F * ta, FB = F * tb;
    const v4f ux = FdA * (axd * ya.p) + FdB * (bxd * yb.p);
    const v4f uy = FdA * (xa.p * ayd) + FdB * (xb.p * byd);
    const v4f ud = -(FA * (axs * ya.p + xa.p * ays) + FB * (bxs * yb.p + xb.p * bys));
    for (int i = 0; i < kWaveTrains; ++i) {
        u[i].x = ux[i];
        u[i].y = uy[i];
        u[i].d = ud[i];
    }
    return true;
}

inline Flow wallFlowFast(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d) {
    Flow U = wallCurrentFlow(state, params, targetFrame, p, d);
    if (wavesOn(state, params, targetFrame)) {
        Flow u[kWaveTrains];
        if (!wallWavesTable(state, params, targetFrame, p, d, u))
            for (int i = 0; i < kWaveTrains; ++i) u[i] = wallTrainExactAt(state, params, targetFrame, i, p, d);
        for (int i = 0; i < kWaveTrains; ++i) {
            U.x += u[i].x;
            U.y += u[i].y;
            U.d += u[i].d;
        }
    }
    return U;
}

inline Flow wallFlowExact(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p, float d) {
    Flow U = wallCurrentFlow(state, params, targetFrame, p, d);
    if (wavesOn(state, params, targetFrame))
        for (int i = 0; i < kWaveTrains; ++i) {
            const Flow u = wallTrainExactAt(state, params, targetFrame, i, p, d);
            U.x += u.x;
            U.y += u.y;
            U.d += u.d;
        }
    return U;
}

inline oceanflow::v4f sel4(v4i m, oceanflow::v4f a, oceanflow::v4f b) {   // m's lane all ones: a, else b (on the bits)
    return (oceanflow::v4f)((m & (v4i)a) | (~m & (v4i)b));
}

inline oceanflow::v4f fold4(oceanflow::v4f q, float L) {
    using oceanflow::v4f;
    const v4i in = (q >= splat4(0.0f)) & (q <= splat4(L));
    if (in[0] & in[1] & in[2] & in[3]) return q;
    v4f r;
    for (int l = 0; l < 4; ++l) r[l] = mirrorFold(q[l], L);
    return r;
}

inline oceanflow::v4f splat4(float x) { return oceanflow::v4f{x, x, x, x}; }

inline oceanflow::v4f smooth01v(oceanflow::v4f r) {
    using oceanflow::v4f;
    r = sel4(r < splat4(0.0f), splat4(0.0f), sel4(splat4(1.0f) < r, splat4(1.0f), r));
    return r * r * (splat4(3.0f) - splat4(2.0f) * r);
}

inline oceanflow::v4f smooth01dv(oceanflow::v4f r) {
    using oceanflow::v4f;
    r = sel4(r < splat4(0.0f), splat4(0.0f), sel4(splat4(1.0f) < r, splat4(1.0f), r));
    return splat4(6.0f) * r * (splat4(1.0f) - r);
}

inline void wallTaper4(oceanflow::v4f q, float L, float b, oceanflow::v4f& chi, oceanflow::v4f& dchi) {
    using oceanflow::v4f;
    const v4f r1 = q / splat4(b), r2 = (splat4(L) - q) / splat4(b);
    const v4f s1 = smooth01v(r1), s2 = smooth01v(r2);
    chi = s1 * s2;
    dchi = (smooth01dv(r1) * s2 - s1 * smooth01dv(r2)) / splat4(b);
}

inline void wallCurrent4(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, oceanflow::v4f px, oceanflow::v4f py, oceanflow::v4f& outx, oceanflow::v4f& outy) {
    using oceanflow::v4f;
    if (!state.current.active()) { outx = splat4(0.0f); outy = splat4(0.0f); return; }
    v4f Cx = splat4(0.0f), Cy = splat4(0.0f), psi = splat4(0.0f);
    if (state.cache.curOn) {
        const float inv2c2 = state.cache.inv2c2;
        const float* E = oceanflow::radialTable().E;
        const float* G = oceanflow::radialIntTable().G;
        const v4f EN = splat4(E[oceanflow::kRadialCells]);
        for (std::size_t k = 0; k < state.cache.eddies.size(); ++k) {
            const oceanflow::Eddy& e = state.cache.eddies[k];
            const v4f dx = px - splat4(e.cx);
            const v4f dy = py - splat4(e.cy);
            const v4f u = (dx * dx + dy * dy) * splat4(inv2c2);
            // radialPsi per lane: a lane it refuses keeps its sums (the scalar's continue)
            const v4i ok = (u >= splat4(0.0f)) & (u < splat4(oceanflow::kRadialCut));
            const v4f s = sel4(ok, u * splat4(oceanflow::kRadialPerUnit), splat4(0.0f));
            const v4i i = __builtin_convertvector(s, v4i);
            const v4f t = s - __builtin_convertvector(i, v4f);
            const v4f Ei = {E[i[0]], E[i[1]], E[i[2]], E[i[3]]};
            const v4f Ei1 = {E[i[0] + 1], E[i[1] + 1], E[i[2] + 1], E[i[3] + 1]};
            const v4f Gi = {G[i[0]], G[i[1]], G[i[2]], G[i[3]]};
            const v4f de = Ei1 - Ei;
            const v4f g = (Ei + t * de) - EN;
            const v4f Gu = Gi + (t * ((Ei - EN) + (splat4(0.5f) * t) * de)) * splat4(1.0f / oceanflow::kRadialPerUnit);
            const v4f f = splat4(e.signScale) * g;
            Cx = sel4(ok, Cx + f * (-dy), Cx);
            Cy = sel4(ok, Cy + f * dx, Cy);
            psi = sel4(ok, psi + splat4(state.cache.psiScale[k]) * Gu, psi);
        }
    } else {   // the double gyre: CurrentField's own evaluators, per lane
        for (int l = 0; l < 4; ++l) {
            const Vec2 c = state.current.velocityAt({px[l], py[l]});
            Cx[l] = c.x; Cy[l] = c.y;
            psi[l] = state.current.gyreStreamAt({px[l], py[l]});
        }
    }
    v4f cx, dcx, cy, dcy;
    wallTaper4(px, (float)params.width, state.cache.wallBc, cx, dcx);
    wallTaper4(py, (float)params.height, state.cache.wallBc, cy, dcy);
    const v4f Q = cx * cy, Qx = dcx * cy, Qy = cx * dcy;
    outx = Q * Cx - psi * Qy;
    outy = Q * Cy + psi * Qx;
}

inline void wallFlowFast4(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, oceanflow::v4f px, oceanflow::v4f py, oceanflow::v4f pd,
                   oceanflow::v4f& ux, oceanflow::v4f& uy, oceanflow::v4f& ud) {
    using oceanflow::v4f;
    // wallCurrentFlow: the current × the deep factor (1 exactly without deepCurrent)
    v4f cx, cy;
    wallCurrent4(state, params, targetFrame, px, py, cx, cy);
    const v4f f = params.deepCurrent ? smooth01v(splat4(2.0f) * pd / splat4(params.D)) : splat4(1.0f);
    ux = f * cx; uy = f * cy; ud = splat4(0.0f);
    if (!state.current.active()) { ux = splat4(0.0f); uy = splat4(0.0f); }
    if (wavesOn(state, params, targetFrame)) {
        for (int l = 0; l < 4; ++l) {
            const Vec2 pl = {px[l], py[l]};
            Flow u[kWaveTrains];
            if (!wallWavesTable(state, params, targetFrame, pl, pd[l], u))
                for (int i = 0; i < kWaveTrains; ++i) u[i] = wallTrainExactAt(state, params, targetFrame, i, pl, pd[l]);
            float x = ux[l], y = uy[l], z = ud[l];
            for (int i = 0; i < kWaveTrains; ++i) { x += u[i].x; y += u[i].y; z += u[i].d; }
            ux[l] = x; uy[l] = y; ud[l] = z;
        }
    }
}

inline FoodSteps wallFoodSteps(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, float dt) {
    double ub = 0.0, len = 1e30;
    if (wavesOn(state, params, targetFrame)) {
        const double b = std::min((double)params.waveBand, 0.25 * (double)params.D);
        for (const WaveTrain& t : state.waves)
            ub += 3.2 * (double)t.frac * (double)params.waveSpeed * (1.0 + 1.5 / (b * (double)t.k));
        len = std::min(len, b);
    }
    if (state.current.active()) {
        const double s = (double)params.currentStrength, bc = (double)state.cache.wallBc;
        const double core = std::max(1.0, (double)params.currentCore);
        if (params.currentMode == 1) {
            const double e = std::abs((double)params.currentGyreEps);
            ub += s * (1.0 + 2.0 * ((double)params.height / (double)params.width) * (1.0 + 6.0 * e)) +
                  s * ((double)params.height / 3.14159265358979) * 2.2 / bc;
        } else {
            ub += (double)params.currentEddies * s * (1.0 + 3.5 * core / bc);
            len = std::min(len, core);
        }
        len = std::min(len, bc);
    }
    const double need = std::ceil(ub * (double)dt / (0.125 * len));
    if (!(need > 1.0)) return {1, dt, 1.0};
    if (need <= (double)kWallFoodMaxSubsteps) return {(int)need, dt, need};
    return {kWallFoodMaxSubsteps, (float)((double)dt * (double)kWallFoodMaxSubsteps / need), need};
}

inline float mirrorFold(float q, float L) {
    if (q >= 0.0f && q <= L) return q;
    if (q < 0.0f && q >= -L) return -q;
    const float L2 = 2.0f * L;
    if (q > L && q <= L2) return L2 - q;
    float r = std::fmod(q, L2);   // exact
    if (r < 0.0f) r += L2;
    return (r <= L) ? r : L2 - r;
}

inline void wallAdvect(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2& p, float& d, float dt, int n) {
    const float W = (float)params.width, H = (float)params.height;
    const float h = dt / (float)n, hh = 0.5f * h;
    for (int k = 0; k < n; ++k) {
        const Flow U1 = wallFlowFast(state, params, targetFrame, p, d);
        const Vec2 pm = {mirrorFold(p.x + hh * U1.x, W), mirrorFold(p.y + hh * U1.y, H)};
        const float dm = mirrorFold(d + hh * U1.d, params.D);
        const Flow U2 = wallFlowFast(state, params, targetFrame, pm, dm);
        p = {mirrorFold(p.x + h * U2.x, W), mirrorFold(p.y + h * U2.y, H)};
        d = mirrorFold(d + h * U2.d, params.D);
    }
}

inline void wallAdvect4(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, Vec2 p[4], float d[4], float dt, int n) {
    using oceanflow::v4f;
    using oceanflow::splat;
    const float W = (float)params.width, H = (float)params.height;
    const float h = dt / (float)n, hh = 0.5f * h;
    v4f px = {p[0].x, p[1].x, p[2].x, p[3].x}, py = {p[0].y, p[1].y, p[2].y, p[3].y};
    v4f pd = {d[0], d[1], d[2], d[3]};
    for (int k = 0; k < n; ++k) {
        v4f u1x, u1y, u1d;
        wallFlowFast4(state, params, targetFrame, px, py, pd, u1x, u1y, u1d);
        const v4f mx = fold4(px + splat(hh) * u1x, W), my = fold4(py + splat(hh) * u1y, H), md = fold4(pd + splat(hh) * u1d, params.D);
        v4f u2x, u2y, u2d;
        wallFlowFast4(state, params, targetFrame, mx, my, md, u2x, u2y, u2d);
        px = fold4(px + splat(h) * u2x, W); py = fold4(py + splat(h) * u2y, H); pd = fold4(pd + splat(h) * u2d, params.D);
    }
    for (int l = 0; l < 4; ++l) { p[l] = {px[l], py[l]}; d[l] = pd[l]; }
}

inline bool wallFlowOn(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame) { return params.walls && (state.current.active() || wavesOn(state, params, targetFrame)); }

inline int wallFoodSubstepsNow(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, float dt) { return wallFoodSteps(state, params, targetFrame, dt).n; }

inline FoodSteps wallFoodStepsNow(const FlowState& state, const TransportParams& params, std::uint64_t targetFrame, float dt) { return wallFoodSteps(state, params, targetFrame, dt); }

// Exactly the original update prologue. The target belongs to this state;
// evaluating a copy never consults the live owner's frame.
inline void advanceFlowClock(FlowState& state, const TransportParams& params,
                             std::uint64_t targetFrame, float dt) {
    state.current.advance(targetFrame);
    state.cache.curAdvanced = true;
    if (wavesOn(state, params, targetFrame)) {
        ensureWaves(state, params, targetFrame);
        advanceWaves(state, params, targetFrame, dt);
    }
}

// One kernel for the owner and future job-owned buffers. Input/output may be
// the same storage. Distinct output starts as a semantic copy (including eye
// contrast); only position/depth and changed-depth contrast are overwritten.
// The caller prepares the frozen flow first and owns the reusable index scratch.
// Spans have equal size and either coincide exactly or do not overlap.
template<class Food>
inline void transportFood(const FlowState& state, const TransportParams& params,
                          std::uint64_t targetFrame, float dt,
                          std::span<const Food> input, std::span<Food> output,
                          std::vector<int>& idx
#ifdef EVO_OCEAN_EYE
                          , float (*contrastAt)(float)
#endif
                          ) {
    assert(input.size() == output.size());
    if (input.data() != output.data()) std::copy(input.begin(), input.end(), output.begin());
    if (!params.foodDrift) return;
    if (params.walls) {
        if (!wallFlowOn(state, params, targetFrame)) return;
        const FoodSteps fs = wallFoodSteps(state, params, targetFrame, dt);
        idx.clear();
        for (int i = 0; i < (int)input.size(); ++i) if (input[i].alive) idx.push_back(i);
        const int n4 = (int)idx.size() & ~3;
        for (int j = 0; j < n4; j += 4) {
            Vec2 p[4]; float d[4];
            for (int l = 0; l < 4; ++l) { p[l] = input[idx[j + l]].pos; d[l] = input[idx[j + l]].depth; }
            wallAdvect4(state, params, targetFrame, p, d, fs.dt, fs.n);
            for (int l = 0; l < 4; ++l) {
                Food& f = output[idx[j + l]];
#ifdef EVO_OCEAN_EYE
                const float z0 = f.depth;
#endif
                f.pos = p[l]; f.depth = d[l];
#ifdef EVO_OCEAN_EYE
                if (f.depth != z0) f.eyeCon = contrastAt(f.depth);
#endif
            }
        }
        for (int j = n4; j < (int)idx.size(); ++j) {
            Food& f = output[idx[j]];
#ifdef EVO_OCEAN_EYE
            const float z0 = f.depth;
#endif
            wallAdvect(state, params, targetFrame, f.pos, f.depth, fs.dt, fs.n);
#ifdef EVO_OCEAN_EYE
            if (f.depth != z0) f.eyeCon = contrastAt(f.depth);
#endif
        }
    } else if (flowE1(state, params, targetFrame)) {
        for (auto& f : output) {
            if (!f.alive) continue;
            const Flow U = flowFast(state, params, targetFrame, f.pos, f.depth);
            f.pos.x = wrapCoord(f.pos.x + U.x * dt, (float)params.width);
            f.pos.y = wrapCoord(f.pos.y + U.y * dt, (float)params.height);
#ifdef EVO_OCEAN_EYE
            const float z0 = f.depth;
#endif
            f.depth = clampDepth(state, params, targetFrame, f.depth + U.d * dt);
#ifdef EVO_OCEAN_EYE
            if (f.depth != z0) f.eyeCon = contrastAt(f.depth);
#endif
        }
    } else if (state.current.active()) {
        for (auto& f : output) {
            if (!f.alive) continue;
            Vec2 v = state.current.velocityAt(f.pos);
            f.pos.x += v.x * dt;  f.pos.y += v.y * dt;
            f.pos.x = wrapPreview(f.pos.x, (float)params.width);
            f.pos.y = wrapPreview(f.pos.y, (float)params.height);
        }
    }
}

} // namespace oceantransport

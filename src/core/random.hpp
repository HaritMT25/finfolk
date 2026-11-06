#pragma once
#include <random>
#include <cstdint>
#include <cstdio>
#include <cmath>
#include <string>
#include <sstream>
#include "portable_math.hpp"

// Portable MT19937 with the classic block-twist state representation.
//
// std::mt19937's OUTPUT sequence is standard-specified and identical across
// standard libraries (probe-verified), but its TEXTUAL SERIALIZATION exposes
// the library's internal representation — libstdc++ (block twist + position)
// and libc++ disagree mid-block, so a native and a wasm build of the same run
// would write different "rngState" strings into otherwise byte-identical
// checkpoints. This implementation produces the same outputs as std::mt19937
// AND serializes as "x[0] x[1] ... x[623] pos", which is byte-identical to
// libstdc++'s format — so checkpoints written by <= v0.17.0 native builds
// still load, and native and wasm checkpoints match byte for byte.
// (Output, text, and cross-restore equality with libstdc++ are pinned at
// multiple stream positions in core_tests.)
class PortableMT19937 {
public:
    using result_type = uint32_t;
    static constexpr uint32_t min() { return 0; }
    static constexpr uint32_t max() { return 0xFFFFFFFFu; }

    explicit PortableMT19937(uint32_t s = 5489u) { seed(s); }

    void seed(uint32_t s) {
        x_[0] = s;
        for (int i = 1; i < N; ++i)
            x_[i] = 1812433253u * (x_[i-1] ^ (x_[i-1] >> 30)) + (uint32_t)i;
        p_ = N;
    }

    uint32_t operator()() {
        if (p_ >= N) twist();
        uint32_t y = x_[p_++];
        y ^= (y >> 11);
        y ^= (y << 7)  & 0x9D2C5680u;
        y ^= (y << 15) & 0xEFC60000u;
        y ^= (y >> 18);
        return y;
    }

    std::string text() const {
        std::string s;
        s.reserve(N * 11 + 4);
        char buf[16];
        for (int i = 0; i < N; ++i) {
            std::snprintf(buf, sizeof buf, "%u ", x_[i]);
            s += buf;
        }
        std::snprintf(buf, sizeof buf, "%d", p_);
        s += buf;
        return s;
    }
    bool fromText(const std::string& s) {
        std::istringstream is(s);
        uint32_t x[N];
        int p;
        for (int i = 0; i < N; ++i)
            if (!(is >> x[i])) return false;
        if (!(is >> p) || p < 0 || p > N) return false;
        for (int i = 0; i < N; ++i) x_[i] = x[i];
        p_ = p;
        return true;
    }

private:
    static constexpr int N = 624, M = 397;
    void twist() {
        for (int i = 0; i < N; ++i) {
            const uint32_t y = (x_[i] & 0x80000000u) | (x_[(i+1)%N] & 0x7FFFFFFFu);
            x_[i] = x_[(i+M)%N] ^ (y >> 1) ^ ((y & 1u) ? 0x9908B0DFu : 0u);
        }
        p_ = 0;
    }
    uint32_t x_[N];
    int p_;
};

// Thread-local RNG adapted from biosim4
//
// v0.18.0: the distribution methods below are explicit bit-exact maps over
// raw engine output instead of std::uniform_*_distribution. The std::
// distributions are implementation-defined — libstdc++ (native) and libc++
// (Emscripten/wasm) return different values AND consume different numbers of
// engine draws for uniform_int, so a native and a wasm run desync on the
// first bounded-int draw. The engine and these wrappers are now both fully
// portable. This changed the random stream once at v0.18.0 (numerical-lineage
// break, documented in the research log).
class RandomGen {
public:
    // The global `rng` below starts from std::random_device (main and the
    // modules seed it). A second stream that must be reproducible from its
    // first use - the predator brains' (WorldCommon::predRng_) - starts from a
    // fixed seed instead, so a World's construction reads no entropy.
    RandomGen() = default;
    explicit RandomGen(unsigned s) : engine_(s) {}

    void seed(unsigned s) { engine_.seed(s); }
    void seed() { engine_.seed(std::random_device{}()); }

    // --- Engine state, for checkpointing ---
    // A resumed run must continue the SAME random sequence, so the seed alone is
    // not enough once a run has advanced — the engine's full internal state has
    // to travel with the checkpoint. The format matches libstdc++'s
    // std::mt19937 stream format (see PortableMT19937), so old checkpoints load.
    //
    // The distribution methods are stateless maps over engine draws, so the
    // engine is the only thing that needs saving.
    std::string state() const { return engine_.text(); }
    bool setState(const std::string& s) { return engine_.fromText(s); }

    // Uniform integer in [0, max], inclusive. Lemire's multiply-shift with
    // rejection: unbiased, usually one draw, and the draw count depends only
    // on engine output — identical on every platform.
    uint32_t uint(uint32_t max = UINT32_MAX) {
        if (max == UINT32_MAX) return engine_();
        const uint32_t n = max + 1u;
        uint64_t m = (uint64_t)engine_() * (uint64_t)n;
        uint32_t l = (uint32_t)m;
        if (l < n) {
            const uint32_t t = (0u - n) % n;  // 2^32 mod n
            while (l < t) {
                m = (uint64_t)engine_() * (uint64_t)n;
                l = (uint32_t)m;
            }
        }
        return (uint32_t)(m >> 32);
    }

    // Uniform float in [0, 1): top 24 engine bits scaled by 2^-24 — exact,
    // one draw, every representable output is a multiple of 2^-24.
    float unit() {
        return (float)(engine_() >> 8) * 0x1p-24f;
    }

    // Uniform float in [lo, hi). (As with the std:: distribution it replaced,
    // rounding of lo + (hi-lo)*u can in principle yield hi itself; the sim
    // only uses this for continuous quantities where that is harmless.)
    float range(float lo, float hi) {
        return lo + (hi - lo) * unit();
    }

    // Uniform int in [lo, hi], inclusive.
    int intRange(int lo, int hi) {
        return lo + (int)uint((uint32_t)((int64_t)hi - (int64_t)lo));
    }

private:
    PortableMT19937 engine_{std::random_device{}()};
};

// Global thread-local RNG instance
inline thread_local RandomGen rng;

// Portable standard normal from raw engine draws (Box–Muller, second value
// discarded). std::normal_distribution is implementation-defined and returns
// different values under libstdc++ vs libc++. Uses only IEEE-exact ops plus
// the vendored logf and cosf (portable_math.hpp). Used for the fixed-seed
// cluster-projection planes; the colour and SimHash planes are frozen
// constants instead (see plane_data.hpp).
inline float portableGaussian(std::mt19937& g) {
    const float u1 = (float)((g() >> 8) + 1u) * 0x1p-24f;  // (0, 1]
    const float u2 = (float)(g() >> 8) * 0x1p-24f;         // [0, 1)
    const float r  = std::sqrt(-2.0f * evomath::logf(u1));
    return r * evomath::cosf(6.2831853f * u2);
}

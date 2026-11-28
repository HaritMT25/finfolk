// Exhaustive independent validity, reconstruction and nearest-candidate oracles.
#include <algorithm>
#include <bit>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <limits>
#ifndef __EMSCRIPTEN__
#include <csignal>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>
#endif
#include "core/weight_log.hpp"
#include "core/portable_math.hpp"
#define CHECK(x, name) do { if (!(x)) { std::fprintf(stderr, "FAIL %s line %d\n", name, __LINE__); return 1; } } while (0)
int main() {
    using namespace logweight;

    for (unsigned r = 0; r < 1024; ++r) {
        const float fraction = float(r) * 0x1p-10f;
        const float argument = fraction * 0x1.62e43p-1f;
        CHECK(kTable[r] == std::bit_cast<unsigned>(evomath::expf(argument)), "table law");
    }
    unsigned accepted = 0, rejected = 0;
    unsigned long long digest = 14695981039346656037ull;
    std::vector<double> candidates{0.0};
    for (unsigned q = 1; q <= 25601; ++q) {
        const unsigned u = q - 1;
        const float base = std::bit_cast<float>(kTable[u % 1024]);
        candidates.push_back(std::ldexp(double(base), int(u / 1024) - 16));
    }
    for (unsigned code = 0; code < 65536; ++code) {
        const unsigned q = code & 32767;
        const bool want = code == 0 || (q >= 1 && q <= 25601);
        float value = 123.25f;
        CHECK(valid(code) == want, "validity");
        CHECK(tryDecode(code, value) == want, "decode refusal");
        if (want) {
            ++accepted;
            const float oracle = float((code & 32768) ? -candidates[q] : candidates[q]);
            CHECK(std::bit_cast<unsigned>(value) == std::bit_cast<unsigned>(oracle), "decoder bits");
        } else {
            ++rejected;
            CHECK(value == 123.25f, "unchanged rejection output");
        }
        digest = (digest ^ std::bit_cast<unsigned>(value)) * 1099511628211ull;
        CHECK(word(store(code)) == code, "bit preserving storage");
    }
    CHECK(accepted == 51203 && rejected == 14333, "exhaustive counts");
#ifndef __EMSCRIPTEN__
    // Isolate fatal precondition checks; demand the trap signal, not any failure.
    for (int guard = 0; guard < 6; ++guard) {
        const pid_t child = fork();
        CHECK(child >= 0, "codec death-test fork");
        if (child == 0) {
            const rlimit noCore{0, 0}; setrlimit(RLIMIT_CORE, &noCore);
            if (guard == 0) { volatile float value = decodeValid(0x8000); (void)value; }
            if (guard == 1) { volatile auto value = addMagnitude(25602, 0); (void)value; }
            if (guard == 2) { volatile auto value = quantize(std::numeric_limits<double>::quiet_NaN()); (void)value; }
            if (guard == 3) { volatile auto value = quantize(513.0); (void)value; }
            if (guard == 4) { volatile auto value = quantize(-513.0); (void)value; }
            if (guard == 5) { volatile auto value = quantize(std::numeric_limits<double>::infinity()); (void)value; }
            _exit(0);
        }
        int status = 0;
        CHECK(waitpid(child, &status, 0) == child, "codec death-test wait");
        CHECK(WIFSIGNALED(status) && WTERMSIG(status) == SIGILL, "codec invalid input traps");
    }
#endif
    // A monotone sweep over sorted legacy magnitudes is independent of the
    // codec's binary search. Distances are exact binary64 differences.
    unsigned nearest = 0;
    for (unsigned magnitude = 0; magnitude <= 32768; ++magnitude) {
        const double value = magnitude / 8192.0;
        while (nearest < 25601 && value - candidates[nearest] > candidates[nearest + 1] - value) ++nearest;
        if (magnitude < 32768) CHECK(quantizeLegacy(static_cast<short>(magnitude)) == nearest, "positive legacy quantization");
        const short negative = static_cast<short>(-int(magnitude));
        CHECK(quantizeLegacy(negative) == (nearest ? nearest | 32768u : 0), "negative legacy quantization");
    }
    for (unsigned q = 0; q < 25601; ++q) {
        const double mid = (candidates[q] + candidates[q + 1]) / 2;
        CHECK(quantize(mid) == q, "midpoint lower magnitude");
        CHECK(quantize(-mid) == (q ? q | 32768u : 0), "negative midpoint lower magnitude");
        CHECK(quantize(std::nextafter(mid, candidates[q + 1])) == q + 1, "above midpoint");
        CHECK(quantize(-std::nextafter(mid, candidates[q + 1])) == ((q + 1) | 32768u), "negative above midpoint");
    }
    CHECK(decodeValid(1) == 0x1p-16f && decodeValid(16385) == 1 && decodeValid(25601) == 512, "endpoints");
    CHECK(addMagnitude(1, -128) == 1 && addMagnitude(25601, 128) == 25601 && addMagnitude(0, 64) == 0, "magnitude saturation");
    std::printf("codec accepted=%u rejected=%u digest=%016llx\n", accepted, rejected, digest);
}

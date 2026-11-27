#pragma once
#include <algorithm>
#include <bit>
#include <cassert>
#include <cmath>
#include <cstdint>
#include "weight_log_table.hpp"

namespace logweight {

inline constexpr std::uint16_t kSign = 0x8000u;
inline constexpr std::uint16_t kMagnitudeMask = 0x7fffu;
inline constexpr unsigned kMaximumQ = 25601u;
inline constexpr unsigned kRevivalQ = 12289u; // 2^-4 = 1/16

inline constexpr std::uint16_t word(std::int16_t stored) {
    return std::bit_cast<std::uint16_t>(stored);
}

inline constexpr std::int16_t store(std::uint16_t encoded) {
    return std::bit_cast<std::int16_t>(encoded);
}

inline constexpr bool valid(std::uint16_t encoded) {
    const unsigned q = encoded & kMagnitudeMask;
    return encoded == 0u || (q >= 1u && q <= kMaximumQ);
}

// Precondition: valid(encoded). Only validated internal data uses this.
inline std::uint32_t decodedBits(std::uint16_t encoded) {
    assert(valid(encoded));
    const unsigned q = encoded & kMagnitudeMask;
    if (q == 0u) return 0u;
    const unsigned u = q - 1u;
    return ((encoded & kSign) ? 0x80000000u : 0u)
         | ((111u + (u >> 10)) << 23)
         | (kTable[u & 1023u] & 0x007fffffu);
}

inline float decodeValid(std::uint16_t encoded) {
    return std::bit_cast<float>(decodedBits(encoded));
}

// On rejection, leave the caller's output untouched.
inline bool tryDecode(std::uint16_t encoded, float& output) {
    if (!valid(encoded)) return false;
    output = decodeValid(encoded);
    return true;
}

// Nearest decoded value by absolute magnitude; include zero as a candidate.
// Double arithmetic makes the distance comparison exact for these binary32
// candidates, including the midpoint tests.
inline std::uint16_t quantize(double weight) {
    assert(std::isfinite(weight));
    assert(weight >= -512.0 && weight <= 512.0);
    if (weight == 0.0) return 0u;

    const bool negative = weight < 0.0;
    const double magnitude = negative ? -weight : weight;

    unsigned lo = 0u;
    unsigned hi = kMaximumQ;
    while (lo < hi) {
        const unsigned mid = lo + (hi - lo) / 2u;
        const double candidate =
            static_cast<double>(decodeValid(
                static_cast<std::uint16_t>(mid)));
        if (candidate < magnitude) lo = mid + 1u;
        else hi = mid;
    }

    unsigned q = lo;
    if (q > 0u) {
        const double lower =
            static_cast<double>(decodeValid(
                static_cast<std::uint16_t>(q - 1u)));
        const double upper =
            static_cast<double>(decodeValid(
                static_cast<std::uint16_t>(q)));
        if (magnitude - lower <= upper - magnitude) --q;
    }

    if (q == 0u) return 0u;
    return static_cast<std::uint16_t>(
        q | (negative ? kSign : 0u));
}

inline std::uint16_t quantizeLegacy(std::int16_t stored) {
    return quantize(static_cast<double>(stored / 8192.0f));
}

inline std::uint16_t addMagnitude(
    std::uint16_t encoded, int delta
) {
    assert(valid(encoded));
    const unsigned q = encoded & kMagnitudeMask;
    if (q == 0u) return 0u;
    const int changed = std::clamp(
        static_cast<int>(q) + delta, 1,
        static_cast<int>(kMaximumQ));
    return static_cast<std::uint16_t>(
        (encoded & kSign) | static_cast<unsigned>(changed));
}

} // namespace logweight

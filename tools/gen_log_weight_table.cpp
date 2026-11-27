#include <bit>
#include <cstdint>
#include <cstdio>
#include "core/portable_math.hpp"

int main() {
    for (unsigned r = 0; r < 1024; ++r) {
        const float fraction = static_cast<float>(r) * 0x1p-10f;
        const float argument = fraction * 0x1.62e43p-1f;
        const float value = evomath::expf(argument);
        std::printf("%08x\n", std::bit_cast<std::uint32_t>(value));
    }
}

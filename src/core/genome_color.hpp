#pragma once
#include <cmath>
#include <cstring>
#include <array>
#include <vector>
#include "connectivity.hpp"
#include "color.hpp"
#include "portable_math.hpp"
#ifdef EVO_WORLD_OCEAN
#ifdef EVO_OCEAN_EYE
#include "../ocean/plane_data_ocean_eye.hpp"   // + the 18 eye sensors => STATS_DIM 1900
#else
#include "../ocean/plane_data_ocean.hpp"   // Ocean's sensor list => its own STATS_DIM
#endif
#else
#include "plane_data.hpp"
#endif

// Project the (source,sink) connectivity vector onto 3 fixed random directions
// (a 3-component cousin of the 16-bit species SimHash) -> RGB. Projection is
// linear, so a small mutation shifts colour proportionally -> lineages drift
// smoothly. Directions are FROZEN constants (plane_data.hpp) so colours are
// stable and comparable across runs — and identical across native and wasm
// builds, which runtime std::normal_distribution generation was not.
// Caveat: 3-D is lossy, so similar colour does NOT guarantee similar genome.
inline Color genomeColor(const Genome& genome) {
    static const std::array<std::vector<float>, 3> planes = [] {
        std::array<std::vector<float>, 3> p;
        for (int r = 0; r < 3; ++r) {
            p[r].resize(STATS_DIM);
            for (int i = 0; i < STATS_DIM; ++i) {
                float v;
                std::memcpy(&v, &kGenomeColorPlaneBits[r][i], 4);
                p[r][i] = v;
            }
        }
        return p;
    }();

    double proj[3] = {0.0, 0.0, 0.0};
    for (const Gene& gene : genome) {
        const int   idx = geneCell(gene, genome.schema);
        const float w   = geneWeight(gene, genome.schema);
        proj[0] += w * (idx < STATS_DIM ? planes[0][idx] : biasProjectionPlanes()[0][idx - STATS_DIM]);
        proj[1] += w * (idx < STATS_DIM ? planes[1][idx] : biasProjectionPlanes()[1][idx - STATS_DIM]);
        proj[2] += w * (idx < STATS_DIM ? planes[2][idx] : biasProjectionPlanes()[2][idx - STATS_DIM]);
    }

    // tanh squash to [40,235] (vivid, no pure black/white). K keeps tanh
    // near-linear so the mapping stays smooth; raise toward ~0.1 for more vivid.
    constexpr float K = 0.06f;
    auto chan = [](double v) {
        return static_cast<int>(std::lround(137.5 + 97.5 * evomath::tanh(K * v)));
    };
    return Color(chan(proj[0]), chan(proj[1]), chan(proj[2]));
}

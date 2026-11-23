#pragma once
// ocean_hydro_bodies.hpp — the body set shared by tools/ocean_hydro_fixture.cpp and
// tools/ocean_hydro_reference.cpp: the M2a body fixture's bodies (tools/ocean_body_fixture.cpp:
// the neutral one, every shape gene at 0 and 1, the edges, 40 random founders with seed
// 20261109) plus every physical allele at its rails.
#include <cstdio>
#include <string>
#include <vector>
#include "ocean/hydro_coefficients.hpp"
#include "core/random.hpp"

namespace hydrofix {
struct Body { std::string name; appearance::Genome G; float S, E; physical::Genes P; };
inline std::string hex64(std::uint64_t h) { char s[24]; std::snprintf(s, sizeof s, "%016llx", (unsigned long long)h); return s; }
inline std::vector<Body> bodies() {
    std::vector<Body> B;
    auto neutralBody = [](const char* name) { return Body{name, appearance::neutral(), 1.0f, 1.0f, physical::neutral()}; };
    B.push_back(neutralBody("neutral"));
    for (int j = 0; j < appearance::kMorphGenes; ++j)
        for (int v = 0; v < 2; ++v) {
            Body b = neutralBody("");
            b.name = "morph" + std::to_string(j) + (v ? "=1" : "=0");
            b.G.g[appearance::kMorphOffset + j] = v ? 1.0f : 0.0f;
            B.push_back(b);
        }
    {   // the M2a fixture's edges
        Body b = neutralBody("chordCap");
        b.G.g[appearance::kMorphOffset + 10] = 0.0f; b.G.g[appearance::kMorphOffset + 11] = 1.0f;
        B.push_back(b);
        b = neutralBody("eyeClip");
        b.G.g[appearance::kMorphOffset + 0] = 0.0f; b.G.g[appearance::kMorphOffset + 29] = 0.75f;
        B.push_back(b);
        b = neutralBody("splitDorsal");
        b.G.g[appearance::kMorphOffset + 15] = 1.0f; b.G.g[appearance::kMorphOffset + 12] = 1.0f;
        B.push_back(b);
        b = neutralBody("noAppendages");
        for (int j : {11, 12, 16, 19, 23}) b.G.g[appearance::kMorphOffset + j] = 0.0f;
        B.push_back(b);
        for (float bD : {0.2f, 0.2001f, 0.2f + 0.8f / 3.0f, 0.2f + 1.6f / 3.0f, 0.9f, 1.0f}) {
            b = neutralBody("");
            char nm[40];
            std::snprintf(nm, sizeof nm, "barbels=%.9g", (double)bD);
            b.name = nm;
            b.G.g[appearance::kMorphOffset + 26] = bD;
            B.push_back(b);
        }
        for (int m = 0; m < 16; ++m) {
            b = neutralBody("");
            b.name = "pairedRails" + std::to_string(m);
            const float lo = 0.0f, hi = 1.0f;
            b.G.g[appearance::kMorphOffset + 19] = (m & 1) ? hi : lo; b.G.g[appearance::kMorphOffset + 23] = (m & 1) ? hi : lo;
            b.G.g[appearance::kMorphOffset + 20] = (m & 2) ? hi : lo; b.G.g[appearance::kMorphOffset + 24] = (m & 2) ? hi : lo;
            b.G.g[appearance::kMorphOffset + 21] = (m & 4) ? hi : lo; b.G.g[appearance::kMorphOffset + 25] = (m & 4) ? hi : lo;
            b.G.g[appearance::kMorphOffset + 22] = (m & 8) ? hi : lo;
            B.push_back(b);
        }
    }
    {   // the M2a fixture's random founders
        RandomGen g;
        g.seed(20261109u);
        for (int i = 0; i < 40; ++i) {
            Body b = neutralBody("");
            b.name = "random" + std::to_string(i);
            double r[appearance::kFounderDraws];
            for (double& x : r) x = g.unit();
            appearance::founderFromDraws(r, appearance::kAll, b.G);
            b.S = (float)(0.5 + 1.5 * g.unit());
            b.E = (float)(0.5 + 1.5 * g.unit());
            for (float& x : b.P.g) x = (float)g.unit();
            B.push_back(b);
        }
    }
    for (int gI = 0; gI < physical::kGenes; ++gI)   // the physical alleles' rails
        for (int v = 0; v < 2; ++v) {
            Body b = neutralBody("");
            b.name = std::string("phys_") + physical::kGeneNames[gI] + (v ? "=1" : "=0");
            b.P.g[gI] = v ? 1.0f : 0.0f;
            B.push_back(b);
        }
    return B;
}
}  // namespace hydrofix

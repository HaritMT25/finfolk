// ocean_body_fixture.cpp — the M2a body plan's fixture driver: a fixed set of
// bodies through the C++ law (src/ocean/body_plan.hpp, physical_genome.hpp),
// written as one JSON document. Built natively and with Emscripten from this
// one file; wasm/ocean_parity.sh requires the two outputs byte-identical and
// equal to the committed tests/fixtures/ocean_body_fixture.json, so the
// digests in it are the native AND the Wasm law's, bit for bit.
//
//   g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_body_fixture.cpp -o obf
//   em++ (the same flags) -msimd128 tools/ocean_body_fixture.cpp -o obf.js -sENVIRONMENT=node -sEXIT_RUNTIME=1
//   ./obf > a.json && node obf.js > b.json && cmp a.json b.json
//
// The bodies: the neutral one; every shape gene at 0 and at 1 (the others
// neutral); the edge cases (the chord cap, eye clipping, a split dorsal, every
// appendage absent, the barbel pairs' activation boundaries, the 16
// paired-fin rail combinations); random founders (appearance founder law,
// random S, E and physical alleles; fixed seed). Per body: its 63 appearance
// floats, S, E, lambda = 20E/4.6 and R = 4.6S (as binary32), its five
// physical alleles, and two digests (H32, below): of its canonical rest
// points in body radii (bodyplan::restPoints at R = 1: what the GPU check,
// web/ocean_scene_parity.js bodyPlanVertexCheck, compares with the renderer's
// GLSL, and what the page's Wasm module, oc_body_rest, must reproduce) and of
// its birth coefficients (bodyplan::compile). The canonical samples and the
// coefficient layout's size are in the header. Floats print as %.9g (exact
// for binary32).
//
// Options: --points  also write every body's rest points (body radii), for
// diagnosis (not in the committed fixture).
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include "ocean/body_plan.hpp"
#include "core/random.hpp"

namespace {
// Two 32-bit lanes over 32-bit words (the JS side: Math.imul, >>> 0).
struct H32 {
    std::uint32_t a = 0x811c9dc5u, b = 0x01234567u;
    void add(std::uint32_t u) { a = (a ^ u) * 16777619u; b = b * 0x9E3779B1u + u; }
    void addf(float f) { std::uint32_t u; std::memcpy(&u, &f, 4); add(u); }
    std::string str() const { char s[24]; std::snprintf(s, sizeof s, "%08x%08x", a, b); return s; }
};
struct Body { std::string name; appearance::Genome G; float S, E; physical::Genes P; };
void printFloats(const float* v, int n) {
    for (int i = 0; i < n; ++i) std::printf("%s%.9g", i ? "," : "", (double)v[i]);
}
}  // namespace

int main(int argc, char** argv) {
    bool points = false;
    for (int i = 1; i < argc; ++i) {
        if (!std::strcmp(argv[i], "--points")) points = true;
        else { std::fprintf(stderr, "usage: %s [--points]\n", argv[0]); return 2; }
    }
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
    {   // edges
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
    {   // random founders
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

    const bodyplan::Samples& S = bodyplan::sampleCoords();
    std::printf("{\"format\":1,\"geometryLaw\":%d,\"metricsAbi\":%d,\"metrics\":%d,\"physicalSchema\":%d,\"sampleCount\":%d,\"samples\":[",
                bodyplan::kGeometryLaw, bodyplan::kMetricsAbi, bodyplan::kMetrics, physical::kSchema, bodyplan::kSamples);
    H32 hs;
    for (int i = 0; i < bodyplan::kSamples; ++i) {
        const bodyplan::Sample& s = S.s[i];
        std::printf("%s[%.9g,%.9g,%.9g,%.9g,%d,%.9g]", i ? "," : "", (double)s.a[0], (double)s.a[1], (double)s.a[2], (double)s.a[3],
                    s.fin, (double)s.side);
        for (float a : s.a) hs.addf(a);
        hs.add((std::uint32_t)s.fin);
        hs.addf(s.side);
    }
    std::printf("],\"samplesDigest\":\"%s\",\"bodies\":[\n", hs.str().c_str());
    H32 all;
    for (std::size_t k = 0; k < B.size(); ++k) {
        const Body& b = B[k];
        const float L = 20.0f * b.S * b.E, R = 4.6f * b.S, lam = L / R;
        const bodyplan::Morph M = bodyplan::decodeMorph(b.G.g, lam);
        bodyplan::Points rest;
        bodyplan::restPoints(M, 1.0f, rest);
        bodyplan::BirthCoefficients c;
        const bool ok = bodyplan::compile(b.G, b.S, b.E, b.P, bodyplan::kGeometryLaw, c);
        H32 hr, hm;
        for (const bodyplan::Vec3& p : rest.p) { hr.addf(p.x); hr.addf(p.y); hr.addf(p.z); }
        for (float v : c.m) hm.addf(v);
        all.add(hr.a); all.add(hr.b); all.add(hm.a); all.add(hm.b);
        std::printf("%s{\"name\":\"%s\",\"genes\":[", k ? ",\n" : "", b.name.c_str());
        printFloats(b.G.g, appearance::kStride);
        std::printf("],\"size\":%.9g,\"elong\":%.9g,\"lambda\":%.9g,\"radius\":%.9g,\"physical\":[", (double)b.S, (double)b.E, (double)lam, (double)R);
        printFloats(b.P.g, physical::kGenes);
        std::printf("],\"compiled\":%d,\"restDigest\":\"%s\",\"metricsDigest\":\"%s\",\"volume\":%.9g,\"wettedArea\":%.9g",
                    ok ? 1 : 0, hr.str().c_str(), hm.str().c_str(), (double)c.m[bodyplan::at(bodyplan::fHullVolume)],
                    (double)c.m[bodyplan::at(bodyplan::fWettedArea)]);
        if (points) {
            std::printf(",\"rest\":[");
            for (int i = 0; i < bodyplan::kSamples; ++i)
                std::printf("%s%.9g,%.9g,%.9g", i ? "," : "", (double)rest.p[i].x, (double)rest.p[i].y, (double)rest.p[i].z);
            std::printf("]");
        }
        std::printf("}");
    }
    std::printf("\n],\"bodyCount\":%zu,\"digest\":\"%s\"}\n", B.size(), all.str().c_str());
    std::fprintf(stderr, "ocean_body_fixture: %zu bodies, %d samples, digest %s\n", B.size(), bodyplan::kSamples, all.str().c_str());
    return 0;
}

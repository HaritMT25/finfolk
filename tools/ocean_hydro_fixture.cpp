// ocean_hydro_fixture.cpp — M2b1 PR 1's fixture driver: a fixed set of
// bodies through the birth compiler (src/ocean/hydro_coefficients.hpp:
// material law 1, the compact coefficient and support records, the
// reference block) and its analytic load update / passive solve, written as
// one JSON document. Built natively and with Emscripten from this one file;
// wasm/ocean_parity.sh requires the two outputs byte-identical and equal to
// the committed tests/fixtures/ocean_hydro_fixture.json, so every digest in
// it is the native AND the Wasm law's, bit for bit.
//
//   g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_fixture.cpp -o ohf
//   em++ (the same flags) -msimd128 tools/ocean_hydro_fixture.cpp -o ohf.js -sENVIRONMENT=node -sEXIT_RUNTIME=1
//   ./ohf > a.json && node ohf.js > b.json && cmp a.json b.json
//
// The bodies are the M2a body fixture's (tools/ocean_body_fixture.cpp: the
// neutral one, every shape gene at 0 and 1, the edges, 40 random founders
// with seed 20261109) plus each physical allele at its rails. Per body: its
// compile error code, the coefficient and support digests (FNV-1a 64 over
// the packed binary32 fields), and digests of evalLoad at three loads
// (unloaded; gas .5 / fuel .25 of the capacities; both full: mass, COM,
// inertia, Meff, Dfin, Afin, Abody, Jbody, K, mouth) and of the passive
// solve (Meff + h D) z' = Meff z at a fixed state. The header holds the
// versions, the record sizes against their ceilings, the coefficient layout
// (name, count, units, offset), the reference block, and the neutral
// body's full record (%.9g: exact for binary32).
//
// Options:
//   --bench N   instead of the document: time N compiles of the body set's
//               bodies and N x 2,000 evaluations of one outer step's PR 2
//               primitives (evalLoad, then per substep passiveDamping, the
//               matrix, solveScaled), and print ns per call (not a gate).
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include <cstdlib>
#include "ocean/hydro_coefficients.hpp"
#include "ocean/hydro_state.hpp"
#include "ocean_hydro_bodies.hpp"

namespace {
using namespace hydro;
using hydrofix::Body;
using hydrofix::bodies;
using hydrofix::hex64;
std::uint64_t loadedDigest(const Loaded& L) {
    Digest d;
    d.addf(L.k); d.addf(L.mass); d.addf(L.com.x); d.addf(L.com.y); d.addf(L.com.z);
    d.addFloats(L.inertia.m, 6);
    d.addf(L.hullVolume); d.addf(L.displaced); d.addf(L.halfDepth);
    d.addFloats(L.hullCov.m, 6);
    d.addFloats(L.K, 3); d.addFloats(L.Khull, 3); d.addf(L.cdForward); d.addf(L.fineness);
    d.addFloats(L.Jbody.m, 6);
    d.addFloats(L.Dfin.m, 21); d.addFloats(L.Afin.m, 21); d.addFloats(L.Abody.m, 21); d.addFloats(L.Meff.m, 21);
    d.addf(L.mouth.x); d.addf(L.mouth.y); d.addf(L.mouth.z);
    return d.h;
}
void printFloats(const float* v, int n) {
    for (int i = 0; i < n; ++i) std::printf("%s%.9g", i ? "," : "", (double)v[i]);
}
int bench(int N) {
    const std::vector<Body> B = bodies();
    using clk = std::chrono::steady_clock;
    Coefficients c;
    Support s;
    Params p;
    (void)references();
    long compiles = 0;
    unsigned sink = 0;
    auto us = [](clk::time_point a, clk::time_point b) { return std::chrono::duration<double, std::micro>(b - a).count(); };
    // the birth compile, and geometry law 1's own compile inside it
    const auto t0 = clk::now();
    for (int k = 0; k < N; ++k)
        for (const Body& b : B) { sink += (unsigned)compile(b.G, b.S, b.E, b.P, p, c, s); ++compiles; }
    const auto t1 = clk::now();
    for (int k = 0; k < N; ++k)
        for (const Body& b : B) {
            bodyplan::BirthCoefficients bc;
            bodyplan::Points pts;
            sink += (unsigned)bodyplan::compile(expressAppearance(b.G), b.S, b.E, expressPhysical(b.P), bodyplan::kGeometryLaw, bc, nullptr, &pts);
        }
    const auto t2 = clk::now();
    // one outer step's primitives at 2,000 fish: evalLoad once, then two substeps of
    // passiveDamping + (Meff + h D) + Meff z + solveScaled; timed by whole passes (no per-fish clock reads)
    std::vector<Coefficients> C;
    for (const Body& b : B) { compile(b.G, b.S, b.E, b.P, p, c, s); C.push_back(c); }
    RandomGen r(5u);
    std::vector<V6> Z(2000);
    for (V6& z : Z) for (int i = 0; i < 6; ++i) z.v[i] = i < 3 ? 120.0f * (2.0f * r.unit() - 1.0f) : 4.0f * (2.0f * r.unit() - 1.0f);
    std::vector<Loaded> Ls(2000);
    float acc = 0.0f;
    const int reps = 20 * N;
    const auto a0 = clk::now();
    for (int k = 0; k < reps; ++k)
        for (int f = 0; f < 2000; ++f) {
            const Coefficients& cf = C[(std::size_t)f % C.size()];
            evalLoad(cf, 0.5f * cf.gasCapacity, 0.03f + 1e-6f * (float)k, Ls[(std::size_t)f]);
            acc += Ls[(std::size_t)f].mass;
        }
    const auto a1 = clk::now();
    for (int k = 0; k < reps; ++k)
        for (int f = 0; f < 2000; ++f) {
            const Loaded& L = Ls[(std::size_t)f];
            const float Lc = C[(std::size_t)f % C.size()].halfLength;
            V6 z = Z[(std::size_t)f];
            for (int sub = 0; sub < 2; ++sub) {
                const S6 D = passiveDamping(L, Lc, z);
                S6 A = L.Meff;
                for (int q = 0; q < 21; ++q) A.m[q] = A.m[q] + 0.008f * D.m[q];
                V6 x;
                solveScaled(A, mulS6(L.Meff, z), Lc, x);
                z = x;
            }
            acc += z.v[0];
        }
    const auto a2 = clk::now();
    const double fs = 2000.0 * reps;
    std::printf("bench: birth compile %.1f us (geometry law 1's compile inside it %.1f us; %ld compiles; sink %u)\n", us(t0, t1) / compiles,
                us(t1, t2) / compiles, compiles, sink);
    std::printf("bench: per fish-step (%.0f): evalLoad %.1f ns; two substeps of damping + matrix + Meff z + scaled LDLᵀ solve %.1f ns (acc %g)\n",
                fs, 1000.0 * us(a0, a1) / fs, 1000.0 * us(a1, a2) / fs, (double)acc);
    return 0;
}
}  // namespace

int main(int argc, char** argv) {
    if (argc == 3 && !std::strcmp(argv[1], "--bench")) return bench(std::atoi(argv[2]) > 0 ? std::atoi(argv[2]) : 1);
    if (argc != 1) { std::fprintf(stderr, "usage: %s [--bench N]\n", argv[0]); return 2; }
    const std::vector<Body> B = bodies();
    const References& R = references();
    std::printf("{\"format\":1,\"geometryLaw\":%d,\"materialLaw\":%d,\"expressionStage\":%d,\"referenceLaw\":%d,\"coefficientAbi\":%d,"
                "\"supportAbi\":%d,\"stateAbi\":%d,\n",
                kGeometryLaw, kMaterialLaw, kExpressionStage, kReferenceLaw, kCoefficientAbi, kSupportAbi, kStateAbi);
    std::printf("\"bytes\":{\"coefficients\":%zu,\"support\":%zu,\"state\":%zu,\"genes\":%zu,\"owner\":8,\"total\":%zu,\"ceiling\":1404,\n",
                sizeof(Coefficients), sizeof(Support), sizeof(HydroState), sizeof(physical::Genes),
                sizeof(Coefficients) + sizeof(Support) + sizeof(HydroState) + sizeof(physical::Genes) + 8);
    // a compile's transient working set (stack): law 1's metrics and points, the cells (full + remaining),
    // the material record, the allocation's order / distance / step arrays; and the cold diagnostics, the loaded body
    std::printf(" \"transient\":{\"birthMetrics\":%zu,\"points\":%zu,\"cells2\":%zu,\"material\":%zu,\"allocationScratch\":%zu,\"diagnostics\":%zu,"
                "\"loaded\":%zu,\"ldl\":%zu}},\n",
                sizeof(bodyplan::BirthCoefficients), sizeof(bodyplan::Points), 2 * sizeof(bodymat::Cells), sizeof(bodymat::Material),
                (sizeof(int) + sizeof(float) + sizeof(bodymat::Taken)) * (std::size_t)bodymat::kCells, sizeof(Diagnostics), sizeof(Loaded),
                sizeof(LDL6));
    std::printf("\"coefficientLayout\":[");
    for (int i = 0; i < kCoefficientFieldCount; ++i) {
        const FieldInfo& f = kCoefficientFields[i];
        std::printf("%s[\"%s\",%d,\"%s\",%d]", i ? "," : "", f.name, f.count, f.units, f.offset);
    }
    std::printf("],\n\"references\":{\"ok\":%d,\"values\":[", R.ok);
    const float rv[] = {R.refVolume, R.rhoWater, R.leanMass, R.muscleVolume, R.muscleMass, R.finMass, R.wallMass, R.spar, R.fuelMass,
                        R.trimGas, R.trimInflation, R.trimMass, R.forwardDrag, R.propArea, R.caudalShare, R.pairedShare, R.thrustCap,
                        R.rowSpeed, R.tailEfficiency, R.cruisePower, R.sustainedPower, R.workConversion};
    printFloats(rv, (int)(sizeof rv / sizeof rv[0]));
    std::printf("],\"names\":\"refVolume rhoWater leanMass muscleVolume muscleMass finMass wallMass spar fuelMass trimGas trimInflation "
                "trimMass forwardDrag propArea caudalShare pairedShare thrustCap rowSpeed tailEfficiency cruisePower sustainedPower "
                "workConversion\",\"digest\":\"%s\"},\n", hex64(digest(R)).c_str());
    Digest all;
    std::printf("\"bodies\":[\n");
    for (std::size_t k = 0; k < B.size(); ++k) {
        const Body& b = B[k];
        Coefficients c;
        Support s;
        const int e = compile(b.G, b.S, b.E, b.P, Params{}, c, s);
        std::uint64_t ld[3] = {0, 0, 0}, sd = 0;
        if (e == kOk) {
            const float loads[3][2] = {{0.0f, 0.0f}, {0.5f, 0.25f}, {1.0f, 1.0f}};
            Loaded L;
            for (int q = 0; q < 3; ++q) {
                evalLoad(c, loads[q][0] * c.gasCapacity, loads[q][1] * c.reserveCapacity * (bodymat::kRhoLipid * rhoWater()), L);
                ld[q] = loadedDigest(L);
            }
            const V6 z{{-82.0f, 3.0f, -2.0f, 0.4f, -0.3f, 1.2f}};
            const S6 D = passiveDamping(L, c.halfLength, z);
            S6 A = L.Meff;
            for (int q = 0; q < 21; ++q) A.m[q] = A.m[q] + 0.008f * D.m[q];
            V6 x{};
            LDL6 f;
            const bool ok = solveScaled(A, mulS6(L.Meff, z), c.halfLength, x, &f);
            Digest dd;
            dd.add(ok ? 1u : 0u);
            dd.addFloats(x.v, 6);
            dd.addFloats(f.D, 6);
            sd = dd.h;
        }
        const std::uint64_t hc = digest(c), hs = digest(s);
        all.add((std::uint32_t)e);
        for (std::uint64_t h : {hc, hs, ld[0], ld[1], ld[2], sd}) { all.add((std::uint32_t)h); all.add((std::uint32_t)(h >> 32)); }
        std::printf("%s{\"name\":\"%s\",\"error\":%d,\"coefficients\":\"%s\",\"support\":\"%s\",\"loaded\":[\"%s\",\"%s\",\"%s\"],\"solve\":\"%s\","
                    "\"mass\":%.9g,\"tailEfficiency\":%.9g,\"tailTau\":%.9g,\"basalPower\":%.9g}",
                    k ? ",\n" : "", b.name.c_str(), e, hex64(hc).c_str(), hex64(hs).c_str(), hex64(ld[0]).c_str(), hex64(ld[1]).c_str(),
                    hex64(ld[2]).c_str(), hex64(sd).c_str(), (double)c.leanMass, (double)c.tailEfficiency, (double)c.tailTau, (double)c.basalPower);
    }
    std::printf("\n],\n");
    {
        Coefficients c;
        Support s;
        compile(appearance::neutral(), 1.0f, 1.0f, physical::neutral(), Params{}, c, s);
        std::printf("\"neutralRecord\":[");
        printFloats(floats(c).data(), kCoefficientFloats);
        std::printf("],\n\"neutralSupport\":[");
        printFloats(floats(s).data(), kSupportFloats);
        std::printf("],\n");
    }
    std::printf("\"bodyCount\":%zu,\"digest\":\"%s\"}\n", B.size(), hex64(all.h).c_str());
    std::fprintf(stderr, "ocean_hydro_fixture: %zu bodies, %zu + %zu + %zu B a fish, references %s, digest %s\n", B.size(), sizeof(Coefficients),
                 sizeof(Support), sizeof(HydroState), hex64(digest(R)).c_str(), hex64(all.h).c_str());
    return 0;
}

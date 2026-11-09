#pragma once
// ocean_body_plan_tests.hpp — the M2a body-plan preview's unit checks
// (src/ocean/physical_genome.hpp, src/ocean/body_plan.hpp, OceanWorld's
// body-plan side arrays), included by tests/ocean_tests.cpp just before main
// (namespace ot: Test, g_passed / g_failed are that file's).
//
//   body_draws     the physical stream: the salted key, the frozen slots
//                  (founder 0..4; offspring selectors 0..4, sources 5..9,
//                  jitters 10..14), pinned draw vectors and genes, every
//                  selector boundary and branch, zero / max mutation,
//                  novelty, clamping, identical-parent identity; never `rng`
//   body_geometry  the closed outward mesh (closed: Σ area vectors ~0; its
//                  volume = the two halves' unsigned volumes, while the
//                  renderer's mirrored index order cancels), positive volume
//                  and a valid inertia over random and rail genomes, the
//                  caudal mesh's area = the nominal one unless the chord cap
//                  binds, mirrored paired fins bit for bit
//   body_iso       isometry: S -> 2S at fixed shape scales every metric by its
//                  units' power of 2, bit for bit (volume x8, area x4,
//                  inertia x32, ...)
//   body_edges     zero-area appendages stay zero, the chord cap, eye
//                  clipping, split dorsals, paired-fin rails, the barbel
//                  activation boundaries, a diagnostic load
//   body_develop   the developmental constraints on expressed values (storage,
//                  organs, shell), the alleles untouched
//   body_owner     the side arrays through births, deaths, predators,
//                  compaction, reseeding, a re-init, a copy, an empty world;
//                  a direct append / reorder / a broken appearance detected;
//                  every record a pure function of its inputs
//   body_neutral   preview on vs off (and different physical inheritance
//                  settings): every simulation section, all, rng AND the
//                  appearance section equal at every step
//   body_hash      one ulp in an allele or a coefficient, an owner id, a knob:
//                  the body section changes, the simulation sections do not
//   body_numbers   the neutral body's measured numbers and digests of fixture
//                  bodies and a world run (printed: native == wasm by the
//                  harness's unit-output comparison)
//   body_shim      the exports, the layout, the cache, the live-key rules and
//                  the refusals (with the shim only)
#include <map>
#include <string>
#include "../src/ocean/physical_genome.hpp"
#include "../src/ocean/body_plan.hpp"

// Private state for the hash-sensitivity checks (the fingerprint header's peek).
namespace ofp::peek {
struct OwBodyGenesTest { friend constexpr auto member(OwBodyGenesTest) noexcept; };
template struct Expose<OwBodyGenesTest, &OceanWorld::bodyGenes_>;
struct OwBodyBirthTest { friend constexpr auto member(OwBodyBirthTest) noexcept; };
template struct Expose<OwBodyBirthTest, &OceanWorld::bodyBirth_>;
struct OwBodyOwnersTest { friend constexpr auto member(OwBodyOwnersTest) noexcept; };
template struct Expose<OwBodyOwnersTest, &OceanWorld::bodyOwners_>;
struct OwAppBodyTest { friend constexpr auto member(OwAppBodyTest) noexcept; };
template struct Expose<OwAppBodyTest, &OceanWorld::app_>;
}  // namespace ofp::peek

// The pinned stream vectors (testBodyDraws).
#define PIN_DRAWS "12020874,13938490,4660832,1653158,16615826,12391721,9377639,3396415,1993501,5690243,2781140,4012348,13096397,2707974,16133661"
#define PIN_FOUNDER "3f0b15b5 3f10efd8 00000000 3ea3b0a9 3f191b84"
#define PIN_OFFSPRING "3f0e8020 3f0bea19 00000000 3ecfdac9 3f135a3b"

namespace ot {
namespace body {
using namespace bodyplan;
inline std::uint32_t fb(float f) { std::uint32_t u; std::memcpy(&u, &f, 4); return u; }
struct H64 {   // FNV-1a over words (printed digests)
    std::uint64_t h = 0xcbf29ce484222325ull;
    void add(std::uint32_t u) { for (int k = 0; k < 4; ++k) { h ^= (u >> (8 * k)) & 0xFF; h *= 0x100000001b3ull; } }
    void addf(float f) { add(fb(f)); }
    std::string str() const { char s[24]; std::snprintf(s, sizeof s, "%016llx", (unsigned long long)h); return s; }
};
inline bool simEqual(const ofp::Fingerprint& a, const ofp::Fingerprint& b) {
    for (auto s : ofp::kSections) if (a.*s != b.*s) return false;
    return a.all == b.all;
}
inline appearance::Genome randomAppearance(RandomGen& g) {
    double r[appearance::kFounderDraws];
    for (double& x : r) x = g.unit();
    appearance::Genome G;
    appearance::founderFromDraws(r, appearance::kAll, G);
    return G;
}
inline physical::Genes randomPhysical(RandomGen& g) {
    physical::Genes P;
    for (float& x : P.g) x = (float)g.unit();
    return P;
}
// The neutral genome with one shape gene set.
inline appearance::Genome withMorph(int j, float v) {
    appearance::Genome G = appearance::neutral();
    G.g[appearance::kMorphOffset + j] = v;
    return G;
}
inline float metric(const BirthCoefficients& c, int field, int k = 0) { return c.m[at(field) + k]; }
inline float fin(const BirthCoefficients& c, int f, int k) { return c.m[finAt(f, k)]; }
inline BirthCoefficients compiled(const appearance::Genome& G, float S = 1.0f, float E = 1.0f,
                                  const physical::Genes& P = physical::neutral()) {
    BirthCoefficients c;
    compile(G, S, E, P, kGeometryLaw, c);
    return c;
}
// The inertia tensor is symmetric positive definite and its principal moments
// obey the triangle inequality (Ixx <= Iyy + Izz, ...), up to float rounding.
inline bool inertiaValid(const BirthCoefficients& c) {
    const float* I = c.m + at(fHullInertia);
    const double xx = I[0], yy = I[1], zz = I[2], xy = I[3], xz = I[4], yz = I[5];
    if (!(xx > 0 && yy > 0 && zz > 0)) return false;
    const double tol = 1e-4 * (xx + yy + zz);
    if (xx > yy + zz + tol || yy > xx + zz + tol || zz > xx + yy + tol) return false;
    const double m2 = xx * yy - xy * xy;
    const double det = xx * (yy * zz - yz * yz) - xy * (xy * zz - yz * xz) + xz * (xy * yz - yy * xz);
    return m2 > 0 && det > 0;
}
}  // namespace body

inline void testBodyDraws() {
    using namespace body;
    Test t("body_draws");
    // the salted key, the stream: draw k of (key, id) is appearance's lattice draw
    const std::uint64_t appKey = 0x0123456789ABCDEFull, key = physical::worldKey(appKey);
    t.expect(key == appearance::mix64(appKey ^ physical::kSaltV1) && key != appKey, "the salted key");
    double r[physical::kOffspringDraws];
    physical::streamDraws(key, 42, r, physical::kOffspringDraws);
    const std::uint64_t base = appearance::streamBase(key, 42);
    bool lattice = true;
    std::string drawsTxt;
    for (int k = 0; k < physical::kOffspringDraws; ++k) {
        lattice = lattice && r[k] == appearance::streamDraw(base, (unsigned)k) && r[k] >= 0 && r[k] < 1 &&
                  r[k] * 16777216.0 == std::floor(r[k] * 16777216.0);
        char b[16];
        std::snprintf(b, sizeof b, "%s%u", k ? "," : "", (unsigned)(r[k] * 16777216.0));
        drawsTxt += b;
    }
    t.expect(lattice, "draws off the 2^-24 lattice or not appearance's streamDraw");
    // pinned (stream law 1, founder law 1): the 15 draws (x 2^24) of fish 42 under
    // this key, and its founder genes' bits. A change here is a law change.
    static const char* const kPinDraws = PIN_DRAWS;
    static const char* const kPinFounder = PIN_FOUNDER;
    t.expect(drawsTxt == kPinDraws, "the draws moved: %s", drawsTxt.c_str());
    physical::Genes F;
    physical::makeFounder(key, 42, F);
    char fbuf[120];
    std::snprintf(fbuf, sizeof fbuf, "%08x %08x %08x %08x %08x", fb(F.g[0]), fb(F.g[1]), fb(F.g[2]), fb(F.g[3]), fb(F.g[4]));
    t.expect(std::string(fbuf) == kPinFounder, "founder 42's genes moved: %s", fbuf);
    t.note("(key %016llx, id 42): draws %s; founder %s", (unsigned long long)key, drawsTxt.c_str(), fbuf);
    // founder law 1, slot by slot: gene j reads draw j only
    {
        double d[5] = {0.3, 0.6, 0.9, 0.1, 0.75};
        physical::Genes A;
        physical::founderFromDraws(d, A);
        bool slots = true;
        for (int j = 0; j < 5; ++j) {
            double e[5];
            std::memcpy(e, d, sizeof e);
            e[j] = 0.5;
            physical::Genes B;
            physical::founderFromDraws(e, B);
            for (int i = 0; i < 5; ++i) slots = slots && ((i == j) || fb(A.g[i]) == fb(B.g[i]));
        }
        t.expect(slots, "a founder gene reads another gene's slot");
        t.expect(A.g[0] == (float)(0.5 + 0.10 * (2 * 0.3 - 1)) && A.g[1] == (float)(0.5 + 0.10 * (2 * 0.6 - 1)) &&
                 A.g[2] == (float)((0.9 - 0.85) / 0.15) && A.g[3] == (float)(0.4 + 0.10 * (2 * 0.1 - 1)) &&
                 A.g[4] == (float)(0.5 + 0.10 * (2 * 0.75 - 1)), "founder law 1's arithmetic");
        double z[5] = {0, 0, 0.8499999, 0, 0};
        physical::founderFromDraws(z, A);
        t.expect(A.g[2] == 0.0f && A.g[0] == 0.4f && A.g[3] == (float)0.3, "the founder rails (armour off below .85)");
    }
    // inheritance law 1: the selector boundaries at p = .05 (mean < .2 <= copyA < .575 <= copyB < .95 <= novel)
    {
        physical::Genes A, B;
        for (int j = 0; j < 5; ++j) { A.g[j] = 0.25f + 0.1f * j; B.g[j] = 0.30f + 0.05f * j; }
        auto child = [&](double sel, const physical::Inheritance& inh, physical::Genes& Q, std::uint8_t* modes) {
            double D[15];
            for (int k = 0; k < 15; ++k) D[k] = 0.5;   // jitter 0 at D = .5 (−m + 2m·.5)
            for (int g = 0; g < 5; ++g) D[g] = sel;
            for (int g = 5; g < 10; ++g) D[g] = 0.95;  // the fresh sources
            physical::offspringFromDraws(A, B, D, inh, Q, modes);
        };
        physical::Inheritance noMut;
        noMut.mutation = 0.0f;
        // the boundaries as M1 computes them, from the novelty as binary32 (.05f)
        const double p = noMut.novel, cA = 0.20 + (1 - 0.20 - p) / 2, cB = 1 - p;
        struct S { double s; int mode; } cases[] = {
            {0.0, appearance::kMean}, {std::nextafter(0.2, 0.0), appearance::kMean}, {0.2, appearance::kCopyA},
            {std::nextafter(cA, 0.0), appearance::kCopyA}, {cA, appearance::kCopyB},
            {std::nextafter(cB, 0.0), appearance::kCopyB}, {cB, appearance::kNovel}, {1.0 - 5.9604644775390625e-8, appearance::kNovel}};
        bool modesOk = true, valuesOk = true;
        physical::Genes fresh;
        { double d[5] = {0.95, 0.95, 0.95, 0.95, 0.95}; physical::founderFromDraws(d, fresh); }
        for (const S& c : cases) {
            physical::Genes Q;
            std::uint8_t modes[5];
            child(c.s, noMut, Q, modes);
            for (int g = 0; g < 5; ++g) {
                modesOk = modesOk && modes[g] == c.mode;
                const float want = c.mode == appearance::kMean ? (float)(((double)A.g[g] + (double)B.g[g]) * 0.5)
                                 : c.mode == appearance::kCopyA ? A.g[g] : c.mode == appearance::kCopyB ? B.g[g] : fresh.g[g];
                valuesOk = valuesOk && fb(Q.g[g]) == fb(want);
            }
        }
        t.expect(modesOk, "a selector boundary picks the wrong branch");
        t.expect(valuesOk, "a branch's value is not M1's (mean in doubles, a copy, the fresh founder)");
        // p = 0: never novel (copy B to 1); p = .25: novel from .75
        physical::Inheritance p0 = noMut, p25 = noMut;
        p0.novel = 0.0f; p25.novel = 0.25f;
        physical::Genes Q;
        std::uint8_t modes[5];
        child(0.99, p0, Q, modes);
        t.expect(modes[0] == appearance::kCopyB, "novelty 0 still drew a novel allele");
        child(0.76, p25, Q, modes);
        t.expect(modes[0] == appearance::kNovel, "novelty .25 is not novel at .76");
        // identical parents: a mean is the copy, bit for bit; zero mutation is the identity
        physical::Genes Qa;
        double D[15];
        for (int k = 0; k < 15; ++k) D[k] = 0.1;   // mean, sources .1, jitters .1
        physical::offspringFromDraws(A, A, D, noMut, Qa);
        bool ident = true;
        for (int g = 0; g < 5; ++g) ident = ident && fb(Qa.g[g]) == fb(A.g[g]);
        t.expect(ident, "identical parents with mutation 0 are not copied bit for bit");
        // the jitter: D = 0 -> −m, D -> 1 -> +m(1 − 2^-23), clamped to [0, 1]
        physical::Inheritance mx;
        mx.mutation = 0.25f; mx.novel = 0.05f;
        physical::Genes lo, hi, Z, O;
        for (int g = 0; g < 5; ++g) { Z.g[g] = 0.1f; O.g[g] = 0.9f; }
        for (int k = 0; k < 15; ++k) D[k] = 0.3;   // copy A
        for (int k = 10; k < 15; ++k) D[k] = 0.0;
        physical::offspringFromDraws(Z, O, D, mx, lo);
        for (int k = 10; k < 15; ++k) D[k] = 1.0 - 5.9604644775390625e-8;
        physical::offspringFromDraws(O, Z, D, mx, hi);
        bool clamped = true;
        for (int g = 0; g < 5; ++g) clamped = clamped && lo.g[g] == 0.0f && hi.g[g] == 1.0f;
        t.expect(clamped, "the jitter is not clamped to [0, 1]");
        for (int k = 10; k < 15; ++k) D[k] = 0.0;
        physical::Genes mid;
        physical::Genes Hh;
        for (int g = 0; g < 5; ++g) Hh.g[g] = 0.5f;
        physical::offspringFromDraws(Hh, Hh, D, mx, mid);
        t.expect(mid.g[0] == 0.25f, "jitter at D = 0 is not −mutation (%.9g)", (double)mid.g[0]);
        // the jitter slot of gene j is draw 10 + j
        bool jslot = true;
        for (int j = 0; j < 5; ++j) {
            for (int k = 0; k < 15; ++k) D[k] = 0.3;
            physical::Genes q0, q1;
            physical::offspringFromDraws(Hh, Hh, D, mx, q0);
            D[10 + j] = 0.9;
            physical::offspringFromDraws(Hh, Hh, D, mx, q1);
            for (int i = 0; i < 5; ++i) jslot = jslot && ((i == j) != (fb(q0.g[i]) == fb(q1.g[i])));
        }
        t.expect(jslot, "a jitter slot moves another gene");
    }
    // construction never touches rng
    const RandomGen before = rng;
    physical::Genes a, b, c;
    physical::makeFounder(key, 7, a);
    physical::makeFounder(key, 8, b);
    physical::makeOffspring(key, 9, a, b, physical::Inheritance{}, c);
    t.expect(sameEngine(before, rng), "physical construction drew from rng");
    t.expect(physical::genesValid(a) && physical::genesValid(b) && physical::genesValid(c), "constructed genes out of range");
    char obuf[120];
    std::snprintf(obuf, sizeof obuf, "%08x %08x %08x %08x %08x", fb(c.g[0]), fb(c.g[1]), fb(c.g[2]), fb(c.g[3]), fb(c.g[4]));
    static const char* const kPinOffspring = PIN_OFFSPRING;
    t.expect(std::string(obuf) == kPinOffspring, "offspring 9's genes moved: %s", obuf);
    t.note("offspring 9 of founders 7, 8: %s", obuf);
    // branch rates at the defaults over many children (20 / 37.5 / 37.5 / 5%)
    {
        physical::Stats st;
        physical::Genes A = a, B = b, Q;
        std::uint8_t modes[5];
        const int N = 40000;
        for (int i = 0; i < N; ++i) {
            physical::makeOffspring(key, 1000 + (std::uint64_t)i, A, B, physical::Inheritance{}, Q, modes);
            for (int g = 0; g < 5; ++g) ++st.mode[modes[g]];
        }
        const double n = 5.0 * N, want[4] = {0.20, 0.375, 0.375, 0.05};
        bool rates = true;
        for (int k = 0; k < 4; ++k) rates = rates && std::fabs((double)st.mode[k] / n - want[k]) < 0.006;
        t.expect(rates, "branch rates %.4f %.4f %.4f %.4f", st.mode[0] / n, st.mode[1] / n, st.mode[2] / n, st.mode[3] / n);
    }
}

inline void testBodyGeometry() {
    using namespace body;
    Test t("body_geometry");
    const Tris& T = canonicalTris();
    t.expect(T.n == kTris && kHullTris == 224 && kSamples == 572 && kMetrics == 226, "the canonical sizes (%d tris, %d samples, %d metrics)",
             T.n, kSamples, kMetrics);
    RandomGen g;
    g.seed(4242);
    long bad = 0, notClosed = 0, cancelBad = 0, nonPos = 0, inertia = 0, caudBad = 0, mirror = 0, n = 0;
    double worstClosed = 0, worstCaud = 0;
    for (int i = 0; i < 600; ++i) {
        appearance::Genome G = i == 0 ? appearance::neutral() : randomAppearance(g);
        if (i % 7 == 3) for (int j = 0; j < appearance::kMorphGenes; ++j) G.g[appearance::kMorphOffset + j] = (float)(g.unit() < 0.5 ? 0.0 : 1.0);   // rails
        const float S = i == 0 ? 1.0f : (float)(0.5 + 1.5 * g.unit()), E = i == 0 ? 1.0f : (float)(0.5 + 1.5 * g.unit());
        const physical::Genes P = randomPhysical(g);
        BirthCoefficients c;
        Points pts;
        if (!compile(G, S, E, P, kGeometryLaw, c, nullptr, &pts)) { ++bad; continue; }
        ++n;
        if (!(metric(c, fHullVolume) > 0.0f)) ++nonPos;
        if (!inertiaValid(c)) ++inertia;
        // closed: the hull's area vectors sum to ~0
        double sx = 0, sy = 0, sz = 0, sa = 0;
        double vRight = 0, vLeft = 0;   // the renderer's order: each half with the same quad order
        for (int k = 0; k < kHullTris; ++k) {
            const Vec3 a = pts.p[T.t[k].a], b = pts.p[T.t[k].b], cc = pts.p[T.t[k].c];
            const Vec3 nn = detail::cross(detail::sub(b, a), detail::sub(cc, a));
            sx += nn.x; sy += nn.y; sz += nn.z; sa += detail::norm(nn);
        }
        const double closed = std::sqrt(sx * sx + sy * sy + sz * sz) / sa;
        worstClosed = std::max(worstClosed, closed);
        if (closed > 1e-5) ++notClosed;
        // the renderer's index order (ocean_appearance.js buildTemplate): for each half
        // the SAME quads (P00, P10, P11), (P00, P11, P01) over the half ring 0..4, its
        // own ring samples (the left half mirrored): their signed volumes cancel
        for (int s = 0; s < 2; ++s)
            for (int ri = 1; ri + 1 < kRings; ++ri)
                for (int h = 0; h < kHalfRing; ++h) {
                    auto P = [&](int ring, int hh) {   // the half's sample hh (0 bottom .. 4 top; 0 and 4 shared)
                        const int k = (s == 0 || hh == 0 || hh == kHalfRing) ? hh : kAround - hh;
                        return pts.p[kHullRing0 + kAround * (ring - 1) + k];
                    };
                    const Vec3 P00 = P(ri, h), P10 = P(ri + 1, h), P11 = P(ri + 1, h + 1), P01 = P(ri, h + 1);
                    const double v1 = detail::dot(P00, detail::cross(P10, P11)) / 6.0, v2 = detail::dot(P00, detail::cross(P11, P01)) / 6.0;
                    (s == 0 ? vRight : vLeft) += v1 + v2;
                }
        const double V = metric(c, fHullVolume);
        // (the bands only: the two end fans add the rest of the closed volume)
        if (!(std::fabs(vRight + vLeft) < 1e-3 * std::fabs(vRight) && std::fabs(vRight) > 0.3 * V)) ++cancelBad;
        // the caudal mesh's area is the nominal cA R² unless the chord cap binds
        const float nom = metric(c, fCaudalNominalArea), act = fin(c, kFinCaudal, kFinArea);
        if (nom > 0.0f && !((int)metric(c, fLimits) & kLimitChordCap)) {
            const double e = std::fabs(act - nom) / nom;
            worstCaud = std::max(worstCaud, e);
            if (e > 2e-4) ++caudBad;
        } else if (nom > 0.0f && !(act < nom)) ++caudBad;
        // the paired fins are mirrors, bit for bit
        for (int f : {kFinPecR, kFinPelR}) {   // (a zero-area fin's zeros may be ±0)
            const bool same = fb(fin(c, f, kFinArea)) == fb(fin(c, f + 1, kFinArea)) &&
                              fin(c, f, kFinCentroid + 1) == -fin(c, f + 1, kFinCentroid + 1) &&
                              fin(c, f, kFinCentroid) == fin(c, f + 1, kFinCentroid) &&
                              fin(c, f, kFinNormal + 1) == -fin(c, f + 1, kFinNormal + 1) &&
                              fin(c, f, kFinNormal + 2) == fin(c, f + 1, kFinNormal + 2);
            mirror += !same;
        }
    }
    t.expect(bad == 0 && n == 600, "%ld compiles refused", bad);
    t.expect(nonPos == 0, "%ld bodies with a non-positive volume", nonPos);
    t.expect(inertia == 0, "%ld bodies with an invalid inertia tensor", inertia);
    t.expect(notClosed == 0, "%ld hulls not closed (worst |Σ n| / Σ|n| %.3g)", notClosed, worstClosed);
    t.expect(cancelBad == 0, "%ld bodies where the renderer's mirrored order does not cancel", cancelBad);
    t.expect(caudBad == 0, "%ld caudal fins whose measured area is not the nominal one (worst %.3g)", caudBad, worstCaud);
    t.expect(mirror == 0, "%ld paired fins not mirrored bit for bit", mirror);
    t.note("%ld random / rail bodies: closed to %.2g, caudal area = nominal to %.2g (uncapped)", n, worstClosed, worstCaud);
}

inline void testBodyIso() {
    using namespace body;
    Test t("body_iso");
    // the factor each field's units take under S -> 2S
    auto factor = [](int f, int k) -> float {
        if (f == fSize) return 2.0f;
        if (f == fRefVolume) return 1.0f;       // a constant
        if (f == fHullVolumeNorm) return 8.0f;  // V / Vref (dimensionless, but a volume)
        if (f == fFins) {
            const int v = k % kFinStride;
            if (v == kFinArea) return 4.0f;
            if (v >= kFinNormal && v < kFinNormal + 3) return 1.0f;
            return 2.0f;
        }
        const std::string u = kFields[f].units;
        if (u == "u") return 2.0f;
        if (u == "u2") return 4.0f;
        if (u == "u3" || u == "E" || u == "m") return 8.0f;
        if (u == "u5") return 32.0f;
        return 1.0f;
    };
    RandomGen g;
    g.seed(99);
    long wrong = 0, checked = 0;
    std::string first;
    for (int i = 0; i < 120; ++i) {
        const appearance::Genome G = i == 0 ? appearance::neutral() : randomAppearance(g);
        const float S = i == 0 ? 1.0f : (float)(0.5 + 0.5 * g.unit()), E = i == 0 ? 1.0f : (float)(0.5 + 1.5 * g.unit());
        const physical::Genes P = i == 0 ? physical::neutral() : randomPhysical(g);
        BirthCoefficients a, b;
        compile(G, S, E, P, kGeometryLaw, a);
        compile(G, 2.0f * S, E, P, kGeometryLaw, b);
        for (int f = 0; f < kFieldCount; ++f)
            for (int k = 0; k < kFields[f].count; ++k) {
                const float x = a.m[at(f) + k], y = b.m[at(f) + k], want = x * factor(f, k);
                ++checked;
                if (fb(y) != fb(want)) {
                    if (!wrong++) { char s[200]; std::snprintf(s, sizeof s, "%s[%d]: %.9g at 2S vs %.9g x %g", kFields[f].name, k, (double)y, (double)x, (double)factor(f, k)); first = s; }
                }
            }
    }
    t.expect(wrong == 0, "%ld of %ld metrics do not scale exactly; first %s", wrong, checked, first.c_str());
    const BirthCoefficients n1 = compiled(appearance::neutral(), 1.0f), n2 = compiled(appearance::neutral(), 2.0f);
    t.note("neutral S 1 -> 2: volume x%.9g, wetted area x%.9g, Izz x%.9g (bit-exact over %ld metrics of 120 bodies)",
           (double)(metric(n2, fHullVolume) / metric(n1, fHullVolume)), (double)(metric(n2, fWettedArea) / metric(n1, fWettedArea)),
           (double)(metric(n2, fHullInertia, 2) / metric(n1, fHullInertia, 2)), checked);
}

inline void testBodyEdges() {
    using namespace body;
    Test t("body_edges");
    // zero-area appendages: caudal area 0 (gene 11), dorsal / anal height 0 (12, 16), pectoral / pelvic area 0 (19, 23)
    {
        appearance::Genome G = appearance::neutral();
        for (int j : {11, 12, 16, 19, 23}) G.g[appearance::kMorphOffset + j] = 0.0f;
        G.g[appearance::kMorphOffset + 26] = 0.2f;   // barbels: at the activation's edge (off)
        const BirthCoefficients c = compiled(G);
        std::string which;
        for (int f = 0; f < kFinCount; ++f)
            for (int k : {(int)kFinArea, (int)kFinSpan, (int)kFinMeanChord, (int)kFinThickness, (int)kFinNormal, kFinNormal + 1, kFinNormal + 2})
                if (fin(c, f, k) != 0.0f && which.empty()) which = std::string(kFinNames[f]) + " value " + std::to_string(k) + " = " + std::to_string(fin(c, f, k));
        for (int j = 0; j < 3; ++j)
            if ((metric(c, fBarbelActivation, j) != 0.0f || metric(c, fBarbelArea, j) != 0.0f || metric(c, fBarbelReach, j) != 0.0f) && which.empty())
                which = "barbel pair " + std::to_string(j);
        t.expect(which.empty(), "a zero-area appendage measured something: %s", which.c_str());
        t.expect(metric(c, fCaudalActualAR) == 0.0f && metric(c, fFinVolume) == 0.0f && metric(c, fHullVolume) > 0.0f, "the bare hull");
    }
    // the chord cap: a large, low-aspect caudal (area 1, aspect 0) caps at 3 R
    {
        appearance::Genome G = withMorph(11, 1.0f);
        G.g[appearance::kMorphOffset + 10] = 0.0f;
        const BirthCoefficients c = compiled(G);
        const float act = fin(c, kFinCaudal, kFinArea), nom = metric(c, fCaudalNominalArea), span = fin(c, kFinCaudal, kFinSpan);
        t.expect(((int)metric(c, fLimits) & kLimitChordCap) && metric(c, fCaudalChord) == 3.0f && act < nom &&
                 metric(c, fCaudalActualAR) > metric(c, fCaudalNominalAR), "the chord cap (act %.4g nom %.4g)", (double)act, (double)nom);
        t.expect(fb(metric(c, fCaudalActualAR)) == fb(span * span / act), "the actual aspect ratio is not span² / area");
        t.note("chord-capped caudal: nominal %.4g u² AR %.3g, measured %.4g u² AR %.3g", (double)nom, (double)metric(c, fCaudalNominalAR),
               (double)act, (double)metric(c, fCaudalActualAR));
    }
    // eye clipping: a large eye (1.4) fits the neutral head, not the shallowest one;
    // the largest (1.8) is clipped even by the neutral head (its limit is ~1.64)
    {
        appearance::Genome G = withMorph(29, 0.75f);
        G.g[appearance::kMorphOffset + 0] = 0.0f;
        const BirthCoefficients c = compiled(G), u = compiled(withMorph(29, 0.75f)), big = compiled(withMorph(29, 1.0f));
        t.expect(((int)metric(c, fLimits) & kLimitEyeClip) && metric(c, fEyeScaleLaw) < 1.4f && !((int)metric(u, fLimits) & kLimitEyeClip) &&
                 metric(u, fEyeScaleLaw) == detail::mH(0.75f, 0.40f, 1.0f, 1.80f) && ((int)metric(big, fLimits) & kLimitEyeClip) &&
                 metric(big, fEyeScaleLaw) < 1.8f, "eye clipping (%.4g, %.4g)", (double)metric(c, fEyeScaleLaw), (double)metric(big, fEyeScaleLaw));
        t.note("eye scale limit of the neutral head %.4g; of the shallowest %.4g", (double)metric(big, fEyeScaleLaw), (double)metric(c, fEyeScaleLaw));
    }
    // a split dorsal: the notch takes area, the middle is at the root
    {
        const BirthCoefficients whole = compiled(appearance::neutral()), split = compiled(withMorph(15, 1.0f));
        Points p;
        BirthCoefficients c;
        compile(withMorph(15, 1.0f), 1.0f, 1.0f, physical::neutral(), kGeometryLaw, c, nullptr, &p);
        const Vec3 root = p.p[kDorsal0 + 2 * (kFinIntervals / 2)], tip = p.p[kDorsal0 + 2 * (kFinIntervals / 2) + 1];
        t.expect(fin(split, kFinDorsal, kFinArea) < fin(whole, kFinDorsal, kFinArea) && tip.z == root.z &&
                 fin(split, kFinDorsal, kFinSpan) < fin(whole, kFinDorsal, kFinSpan), "the split dorsal");
    }
    // paired-fin rails: every combination of area / root / sweep / dihedral at 0 and 1 is finite and mirrored
    {
        long badRail = 0;
        for (int m = 0; m < 16; ++m) {
            appearance::Genome G = appearance::neutral();
            G.g[appearance::kMorphOffset + 19] = (m & 1) ? 1.0f : 0.0f;
            G.g[appearance::kMorphOffset + 20] = (m & 2) ? 1.0f : 0.0f;
            G.g[appearance::kMorphOffset + 21] = (m & 4) ? 1.0f : 0.0f;
            G.g[appearance::kMorphOffset + 22] = (m & 8) ? 1.0f : 0.0f;
            G.g[appearance::kMorphOffset + 23] = (m & 1) ? 1.0f : 0.0f;
            G.g[appearance::kMorphOffset + 24] = (m & 2) ? 1.0f : 0.0f;
            G.g[appearance::kMorphOffset + 25] = (m & 4) ? 1.0f : 0.0f;
            BirthCoefficients c;
            if (!compile(G, 1.0f, 1.0f, physical::neutral(), kGeometryLaw, c)) { ++badRail; continue; }
            const bool area = (m & 1) ? fin(c, kFinPecR, kFinArea) > 0.0f && fin(c, kFinPelR, kFinArea) > 0.0f
                                      : fin(c, kFinPecR, kFinArea) == 0.0f && fin(c, kFinPelR, kFinArea) == 0.0f;
            const bool mir = fb(fin(c, kFinPecR, kFinArea)) == fb(fin(c, kFinPecL, kFinArea)) &&
                             fb(fin(c, kFinPelR, kFinArea)) == fb(fin(c, kFinPelL, kFinArea));
            if (!area || !mir || !inertiaValid(c)) ++badRail;
        }
        t.expect(badRail == 0, "%ld paired-fin rail combinations failed", badRail);
    }
    // the barbel activation boundaries: pair j starts at bD = .2 + .8 j / 3, is full at .2 + .8 (j + 1) / 3
    {
        auto act = [&](float bD, int j) { return metric(compiled(withMorph(26, bD)), fBarbelActivation, j); };
        const float b1 = 0.2f + 0.8f / 3.0f, b2 = 0.2f + 1.6f / 3.0f;
        t.expect(act(0.2f, 0) == 0.0f && act(std::nextafter(0.2f, 1.0f), 0) > 0.0f, "pair 0 does not start at bD = .2");
        t.expect(act(b1, 0) > 0.9999f && act(b1, 1) < 1e-4f && act(b2, 1) > 0.9999f && act(b2, 2) < 1e-4f && act(1.0f, 2) == 1.0f,
                 "the pairs' activation boundaries");
        const BirthCoefficients c = compiled(withMorph(26, 1.0f));
        t.expect(metric(c, fBarbelReach, 0) > metric(c, fBarbelReach, 2) && metric(c, fBarbelReach, 2) > 0.0f && metric(c, fBarbelArea, 0) > 0.0f,
                 "active barbels measure a reach and an area");
    }
    // a diagnostic load inflates the torso (k > 1), the birth compile does not
    {
        BirthCoefficients a, b;
        Load L;
        L.gas = 1.0f; L.fuel = 1.0f;
        compile(appearance::neutral(), 1.0f, 1.0f, physical::neutral(), kGeometryLaw, a);
        compile(appearance::neutral(), 1.0f, 1.0f, physical::neutral(), kGeometryLaw, b, &L);
        const float k = metric(b, fInflation);
        t.expect(metric(a, fInflation) == 1.0f && k > 1.0f && metric(b, fHullVolume) > metric(a, fHullVolume) &&
                 metric(b, fHullLength) == metric(a, fHullLength) && metric(b, fBladderCapacity) == metric(a, fBladderCapacity),
                 "the diagnostic load (k %.6g)", (double)k);
        Load zero;
        BirthCoefficients z;
        compile(appearance::neutral(), 1.0f, 1.0f, physical::neutral(), kGeometryLaw, z, &zero);
        t.expect(std::memcmp(&z, &a, sizeof z) == 0, "a zero load is not the birth compile, bit for bit");
        t.note("full gas + fuel load on the neutral body: k = %.5g, volume %.5g -> %.5g u³ (x%.4f; k² = %.4f)", (double)k,
               (double)metric(a, fHullVolume), (double)metric(b, fHullVolume), (double)(metric(b, fHullVolume) / metric(a, fHullVolume)), (double)(k * k));
    }
    // unknown law, bad inputs: refused, zeros
    {
        BirthCoefficients c;
        t.expect(!compile(appearance::neutral(), 1.0f, 1.0f, physical::neutral(), 2, c) && c.m[0] == 0.0f &&
                 !compile(appearance::neutral(), 0.0f, 1.0f, physical::neutral(), 1, c) &&
                 !compile(appearance::neutral(), NAN, 1.0f, physical::neutral(), 1, c), "a bad compile was accepted");
    }
}

inline void testBodyDevelop() {
    using namespace body;
    Test t("body_develop");
    physical::Genes P = physical::neutral();
    const physical::Genes before = P;
    // storage: full bladder + full fat (.15 + .20 > .28) scale both by .8
    P.g[physical::kBladder] = 1.0f; P.g[physical::kFat] = 1.0f;
    Expressed x = develop(100.0f, 200.0f, 0.8f, 4.6f, 1.0f, P);
    t.expect((x.limits & kLimitStorage) && std::fabs(x.storageScale - 0.8f) < 1e-6f && std::fabs(x.gas - 12.0f) < 1e-4f &&
             std::fabs(x.reserve - 18.0f) < 1e-4f, "the storage bound (scale %.6g gas %.6g reserve %.6g)", (double)x.storageScale,
             (double)x.gas, (double)x.reserve);
    // neutral: no bound
    x = develop(100.0f, 200.0f, 0.8f, 4.6f, 1.0f, physical::neutral());
    t.expect(x.limits == 0 && x.storageScale == 1.0f && x.organScale == 1.0f && x.shellScale == 1.0f && x.shell == 0.0f &&
             x.gapeFraction == 0.40f, "the neutral development is unbounded");
    // organs: a tiny hull with big eyes and a full gape: jaw + eyes > .25 V -> one cube-root factor
    P = physical::neutral();
    P.g[physical::kGape] = 1.0f;
    x = develop(5.0f, 30.0f, 0.8f, 4.6f, 1.8f, P);
    const float bound = x.jaw + x.eyes;
    t.expect((x.limits & kLimitOrgans) && x.organScale < 1.0f && std::fabs(bound - 1.25f) < 1e-4f &&
             std::fabs(x.gapeFraction - 0.65f * x.organScale) < 1e-6f && std::fabs(x.eyeScale - 1.8f * x.organScale) < 1e-6f,
             "the organ bound (jaw + eyes %.6g of .25 V = 1.25)", (double)bound);
    // shell: armour 1 on a body whose shell would exceed .08 V
    P = physical::neutral();
    P.g[physical::kArmour] = 1.0f;
    x = develop(100.0f, 400.0f, 0.8f, 4.6f, 1.0f, P);
    t.expect((x.limits & kLimitShell) && std::fabs(x.shell - 8.0f) < 1e-4f && x.armourThickness < 0.06f * 0.8f * 4.6f,
             "the shell cap (%.6g)", (double)x.shell);
    (void)before;
    // a compiled armoured body: the cap binds on the neutral hull above armour ~.5; the allele is the stored one
    P = physical::neutral();
    P.g[physical::kArmour] = 1.0f;
    const physical::Genes stored = P;
    const BirthCoefficients c = compiled(appearance::neutral(), 1.0f, 1.0f, P);
    t.expect(std::memcmp(&stored, &P, sizeof P) == 0 && ((int)metric(c, fLimits) & kLimitShell) &&
             std::fabs(metric(c, fShellVolume) - 0.08f * metric(c, fHullVolume)) < 1e-3f * metric(c, fHullVolume),
             "armour 1 on the neutral body (shell %.5g of V %.5g)", (double)metric(c, fShellVolume), (double)metric(c, fHullVolume));
}

inline void testBodyOwner() {
    using namespace body;
    Test t("body_owner");
    OceanWorld w;
    std::string err;
    const char* cfg = R"({"bodyPlanPreviewEnabled":true,"predatorCount":8,"predatorEconomy":true,"minPopulation":260,"interactCooldown":0.5,"reproCooldown":2})";
    t.expect(ofp::initWorld(w, 23, 1920, 1080, 240.0f, 300, cfg, err), "init: %s", err.c_str());
    long bad = 0;
    long long lastBirths = 0;
    for (int s = 0; s < 3000; ++s) {
        w.update(0.016f);
        if (!w.bodyPlanConsistent() || !w.bodyPlanEnabled()) ++bad;
        lastBirths = w.totalBirths;
    }
    const auto& st = w.bodyPlanStats();
    t.expect(bad == 0, "the body arrays went out of step %ld times", bad);
    t.expect(w.totalBirths > 0 && w.totalDeathsPredation > 0 && w.totalReseeds > 0, "the case reached no births (%lld), predation (%lld) or reseeds (%lld)",
             w.totalBirths, w.totalDeathsPredation, w.totalReseeds);
    t.expect((long long)st.offspring == lastBirths && (long long)st.founders == 300 + w.totalReseeds, "records: %llu offspring / %lld births, %llu founders",
             (unsigned long long)st.offspring, lastBirths, (unsigned long long)st.founders);
    // every record a pure function of its inputs: founders' genes from the key and the id; every body compiled from its record
    long impure = 0, foundersChecked = 0;
    for (std::size_t i = 0; i < w.creatures.size(); ++i) {
        BirthCoefficients c;
        compile(w.appearanceRecords()[i].genome, w.creatures[i].bodySize, w.creatures[i].bodyElong, w.bodyPlanGenes()[i], kGeometryLaw, c);
        impure += std::memcmp(&c, &w.bodyPlanBirth()[i], sizeof c) != 0;
        if (w.creatures[i].generation == 0) {
            physical::Genes F;
            physical::makeFounder(w.bodyPlanKey(), w.creatures[i].id, F);
            impure += std::memcmp(&F, &w.bodyPlanGenes()[i], sizeof F) != 0;
            ++foundersChecked;
        }
    }
    t.expect(impure == 0 && foundersChecked > 0, "%ld records are not their inputs' compile / founder", impure);
    t.expect(w.bodyPlanUncompiled() == 0, "%llu compiles refused", (unsigned long long)w.bodyPlanUncompiled());
    t.note("3000 steps: %lld births, %lld predator deaths, %lld reseeds, %zu records (%ld founders re-derived)", w.totalBirths,
           w.totalDeathsPredation, w.totalReseeds, w.bodyPlanOwners().size(), foundersChecked);
    // a copy steps as the original
    {
        OceanWorld c = w;
        const RandomGen saved = rng;
        c.update(0.016f);
        const ofp::Fingerprint fc = ofp::fingerprint(c);
        rng = saved;
        w.update(0.016f);
        const ofp::Fingerprint fw = ofp::fingerprint(w);
        t.expect(fc == fw && fc.bodyShown, "a copied world does not step as the original");
    }
    // a direct append, without the helper: detected at the next step
    {
        OceanWorld v;
        ofp::initWorld(v, 3, 1920, 1080, 240.0f, 50, R"({"bodyPlanPreviewEnabled":true})", err);
        v.creatures.push_back(v.creatures.back());
        v.creatures.back().id = 999999;
        v.update(0.016f);
        t.expect(v.bodyPlanBroken() && v.bodyPlanOwners().empty() && !v.bodyPlanEnabled(), "a direct append was not detected");
    }
    // a same-count reorder
    {
        OceanWorld v;
        ofp::initWorld(v, 3, 1920, 1080, 240.0f, 50, R"({"bodyPlanPreviewEnabled":true})", err);
        std::swap(v.creatures[3], v.creatures[7]);
        t.expect(!v.bodyPlanConsistent(), "a same-count reorder looks consistent");
        v.update(0.016f);
        t.expect(v.bodyPlanBroken(), "a same-count reorder was not detected");
    }
    // a broken appearance array breaks the body plan too
    {
        OceanWorld v;
        ofp::initWorld(v, 3, 1920, 1080, 240.0f, 50, R"({"bodyPlanPreviewEnabled":true})", err);
        ofp::field<ofp::peek::OwAppBodyTest>(v).pop_back();
        v.update(0.016f);
        t.expect(v.appearanceBroken() && v.bodyPlanBroken() && v.bodyPlanGenes().empty(), "a broken appearance array left the body plan on");
    }
    // attachFounderAppearance keeps a direct append bound (both arrays)
    {
        OceanWorld v;
        ofp::initWorld(v, 3, 1920, 1080, 240.0f, 50, R"({"bodyPlanPreviewEnabled":true})", err);
        Fish f = v.creatures.back();
        v.creatures.push_back(f);
        v.markFounder(v.creatures.back());
        const RandomGen before = rng;
        v.attachFounderAppearance();
        t.expect(sameEngine(before, rng), "attachFounderAppearance drew from rng");
        v.update(0.016f);
        t.expect(!v.bodyPlanBroken() && v.bodyPlanConsistent() && v.bodyPlanOwners().size() == v.creatures.size(), "an attached append is not consistent");
    }
    // init again on the same object: rebuilt from the key; the counters restart
    {
        OceanWorld a, b;
        const char* on = R"({"bodyPlanPreviewEnabled":true})";
        ofp::initWorld(a, 31, 1920, 1080, 240.0f, 120, on, err);
        for (int s = 0; s < 300; ++s) a.update(0.016f);
        ofp::initWorld(a, 31, 1920, 1080, 240.0f, 120, on, err);
        ofp::initWorld(b, 31, 1920, 1080, 240.0f, 120, on, err);
        bool pure = a.bodyPlanConsistent() && a.bodyPlanOwners().size() == 120 && a.bodyPlanKey() == b.bodyPlanKey();
        for (std::size_t i = 0; i < a.bodyPlanGenes().size(); ++i) {
            physical::Genes F;
            physical::makeFounder(a.bodyPlanKey(), a.creatures[i].id, F);
            pure = pure && std::memcmp(&F, &a.bodyPlanGenes()[i], sizeof F) == 0;
        }
        t.expect(pure, "a re-init does not rebuild the body arrays from the key");
        t.expect(a.bodyPlanStats().offspring == 0 && a.bodyPlanStats().founders == 120, "a re-init keeps the old counters");
    }
    // an empty world: no records, consistent; the reseed floor then builds them
    {
        OceanWorld v;
        ofp::initWorld(v, 5, 1920, 1080, 240.0f, 0, R"({"bodyPlanPreviewEnabled":true,"minPopulation":0})", err);
        v.update(0.016f);
        const bool empty = v.bodyPlanConsistent() && v.bodyPlanOwners().empty() && v.bodyPlanEnabled();
        v.cfg.minPopulation = 10;
        v.update(0.016f);
        t.expect(empty && v.bodyPlanConsistent() && v.bodyPlanOwners().size() == 10, "an empty world, then a reseed");
    }
    // off: nothing kept
    {
        OceanWorld v;
        ofp::initWorld(v, 5, 1920, 1080, 240.0f, 40, nullptr, err);
        v.update(0.016f);
        t.expect(!v.bodyPlanEnabled() && !v.bodyPlanInitEnabled() && v.bodyPlanOwners().empty() && v.bodyPlanConsistent() &&
                 !ofp::fingerprint(v).bodyShown, "the preview off keeps or shows something");
    }
}

inline void testBodyNeutral() {
    using namespace body;
    Test t("body_neutral");
    struct Case { const char* name; unsigned seed; const char* off; const char* on; int steps; };
    const Case cases[] = {
        {"pairing", 29, R"({"reproMaxDistance":16,"reproSoftWidth":5,"reproGracePeriod":30,"bodyModel":true})",
                        R"({"reproMaxDistance":16,"reproSoftWidth":5,"reproGracePeriod":30,"bodyModel":true,"bodyPlanPreviewEnabled":true})", 1500},
        {"predators", 42, R"({"predatorCount":6,"predatorEconomy":true,"predatorMinPopulation":3,"predatorInheritance":true})",
                          R"({"predatorCount":6,"predatorEconomy":true,"predatorMinPopulation":3,"predatorInheritance":true,"bodyPlanPreviewEnabled":true,"physicalMutation":0.25,"physicalNovelProbability":0.25})", 1500},
        {"e1", 13, R"({"waveSpeed":6,"deepCurrent":true,"currentStrength":40,"foodDrift":true,"sizeDrift":true,"mouthGate":true,"bodyModel":true})",
                   R"({"waveSpeed":6,"deepCurrent":true,"currentStrength":40,"foodDrift":true,"sizeDrift":true,"mouthGate":true,"bodyModel":true,"bodyPlanPreviewEnabled":true,"physicalMutation":0,"physicalNovelProbability":0})", 1200},
        {"walls", 5, R"({"walls":true,"predatorCount":3})", R"({"walls":true,"predatorCount":3,"bodyPlanPreviewEnabled":true,"appearance":2})", 1200},
#ifdef EVO_OCEAN_EYE
        {"eye", 17, R"({"eye":1,"eyeCode":7,"predatorCount":2})", R"({"eye":1,"eyeCode":7,"predatorCount":2,"bodyPlanPreviewEnabled":true})", 1200},
#endif
    };
    for (const Case& c : cases) {
        auto run = [&](const char* cfg, std::vector<ofp::Fingerprint>& fps, long long& births) {
            OceanWorld w;
            std::string err;
            if (!t.expect(ofp::initWorld(w, c.seed, 1920, 1080, 240.0f, 300, cfg, err), "%s: %s", c.name, err.c_str())) return;
            fps.push_back(ofp::fingerprint(w));
            for (int s = 0; s < c.steps; ++s) { w.update(0.016f); fps.push_back(ofp::fingerprint(w)); }
            births = w.totalBirths;
        };
        std::vector<ofp::Fingerprint> fa, fbv;
        long long ba = 0, bb = 0;
        run(c.off, fa, ba);
        run(c.on, fbv, bb);
        long first = -1;
        bool appEqual = true, bodyShown = true;
        const bool appMayDiffer = std::strstr(c.on, "\"appearance\":2") != nullptr;   // (that case changes appearance itself)
        for (std::size_t s = 0; s < fa.size() && s < fbv.size(); ++s) {
            if (first < 0 && !simEqual(fa[s], fbv[s])) first = (long)s;
            appEqual = appEqual && (appMayDiffer || fa[s].app == fbv[s].app);
            bodyShown = bodyShown && !fa[s].bodyShown && fbv[s].bodyShown;
        }
        t.expect(fa.size() == fbv.size() && first < 0, "%s: a simulation section differs from step %ld", c.name, first);
        t.expect(appEqual, "%s: the appearance section moved with the preview on (M1 / P1 genes changed)", c.name);
        t.expect(bodyShown, "%s: the body section shown off or hidden on", c.name);
        t.expect(ba > 0 && ba == bb, "%s: births %lld vs %lld", c.name, ba, bb);
        t.note("%s: %d steps, %lld births; all 9 sections, all, rng and app equal at every step", c.name, c.steps, ba);
    }
}

inline void testBodyHash() {
    using namespace body;
    Test t("body_hash");
    OceanWorld w;
    std::string err;
    ofp::initWorld(w, 9, 1920, 1080, 240.0f, 40, R"({"bodyPlanPreviewEnabled":true})", err);
    for (int s = 0; s < 50; ++s) w.update(0.016f);
    const ofp::Fingerprint f0 = ofp::fingerprint(w);
    t.expect(f0.bodyShown, "the preview on is not shown");
    auto& genes = ofp::field<ofp::peek::OwBodyGenesTest>(w);
    auto& birth = ofp::field<ofp::peek::OwBodyBirthTest>(w);
    auto& owners = ofp::field<ofp::peek::OwBodyOwnersTest>(w);
    long missed = 0, leaked = 0, tried = 0;
    auto bump = [&](float& v) {
        const float old = v;
        v = std::nextafter(v, v < 0.5f ? 1.0f : 0.0f);
        const ofp::Fingerprint f1 = ofp::fingerprint(w);
        missed += f1.body == f0.body;
        leaked += !simEqual(f0, f1) || f1.app != f0.app;
        ++tried;
        v = old;
    };
    for (std::size_t i = 0; i < genes.size(); i += 5)
        for (float& v : genes[i].g) bump(v);
    for (std::size_t i = 0; i < birth.size(); i += 9)
        for (int k = 0; k < kMetrics; k += 3) bump(birth[i].m[k]);
    t.expect(missed == 0, "%ld of %ld one-ulp changes left the body hash unchanged", missed, tried);
    t.expect(leaked == 0, "%ld body changes moved a simulation or appearance section", leaked);
    owners[3] ^= 1;
    t.expect(ofp::fingerprint(w).body != f0.body, "an owner id change is not hashed");
    owners[3] ^= 1;
    // an M1 shape gene the body was built from is hashed in body too (and app)
    auto& recs = ofp::field<ofp::peek::OwAppBodyTest>(w);
    float& sg = recs[2].genome.g[appearance::kMorphOffset + 5];
    const float old = sg;
    sg = std::nextafter(sg, 1.0f);
    const ofp::Fingerprint fs = ofp::fingerprint(w);
    t.expect(fs.body != f0.body && fs.app != f0.app && simEqual(fs, f0), "a shape gene is not in the body section");
    sg = old;
    w.ocfg.physicalMutation = std::nextafter(w.ocfg.physicalMutation, 1.0f);
    const ofp::Fingerprint f2 = ofp::fingerprint(w);
    t.expect(f2.body != f0.body && f2.cfg == f0.cfg && f2.all == f0.all, "a knob is not hashed in body only");
    t.expect(ofp::fingerprint(w) == f2, "fingerprinting is not pure");
    // a knob off its default shows the section with the preview off; the defaults do not
    OceanWorld v;
    ofp::initWorld(v, 9, 1920, 1080, 240.0f, 40, R"({"physicalNovelProbability":0.1})", err);
    t.expect(ofp::fingerprint(v).bodyShown && !v.bodyPlanEnabled(), "a knob off its default is not shown");
}

inline void testBodyNumbers() {
    using namespace body;
    Test t("body_numbers");
    const BirthCoefficients c = compiled(appearance::neutral());
    const float* m = c.m;
    t.note("neutral S = E = 1: L %.6g R %.6g; V %.6g u³; Sw %.6g u²; Af %.6g, side %.6g, plan %.6g u²; hull %.6g u, total %.6g u; fineness %.4g; B %.4g",
           (double)m[at(fRefLength)], (double)m[at(fRefRadius)], (double)m[at(fHullVolume)], (double)m[at(fWettedArea)], (double)m[at(fFrontalArea)],
           (double)m[at(fSideArea)], (double)m[at(fPlanArea)], (double)m[at(fHullLength)], (double)m[at(fTotalLength)], (double)m[at(fFineness)],
           (double)m[at(fForeAft)]);
    t.note("  centroid x %.5g u; inertia (density 1) Ixx %.6g Iyy %.6g Izz %.6g u⁵", (double)m[at(fHullCentroid)], (double)m[at(fHullInertia)],
           (double)m[at(fHullInertia) + 1], (double)m[at(fHullInertia) + 2]);
    for (int f = 0; f < kFinCount; ++f)
        t.note("  %-9s area %.5g u², span %.4g u, root chord %.4g u, centroid (%.4g, %.4g, %.4g)", kFinNames[f], (double)fin(c, f, kFinArea),
               (double)fin(c, f, kFinSpan), (double)fin(c, f, kFinRootChord), (double)fin(c, f, kFinCentroid), (double)fin(c, f, kFinCentroid + 1),
               (double)fin(c, f, kFinCentroid + 2));
    t.note("  caudal: nominal %.5g u² AR %.4g; measured AR %.4g", (double)m[at(fCaudalNominalArea)], (double)m[at(fCaudalNominalAR)],
           (double)m[at(fCaudalActualAR)]);
    physical::Genes P0 = physical::neutral(), P1 = physical::neutral();
    P0.g[physical::kGape] = 0.0f; P1.g[physical::kGape] = 1.0f;
    t.note("  gape diameter at size 1: %.4g (gene 0) .. %.4g (.5) .. %.4g u (1); eye area %.4g u²", (double)metric(compiled(appearance::neutral(), 1, 1, P0), fGapeDiameter),
           (double)m[at(fGapeDiameter)], (double)metric(compiled(appearance::neutral(), 1, 1, P1), fGapeDiameter), (double)m[at(fEyeArea)]);
    t.note("  capacities: gas %.5g u³, reserve %.5g u³ (%.4g E); unloaded mass estimate %.4g", (double)m[at(fBladderCapacity)],
           (double)m[at(fReserveCapacity)], (double)m[at(fReserveEnergy)], (double)m[at(fUnloadedMassEstimate)]);
    t.expect(metric(c, fHullVolumeNorm) == 1.0f && metric(c, fRefVolume) == metric(c, fHullVolume), "the neutral body is the reference volume");
    // digests: fixture bodies (rails, random) and a world run; the harness compares this output native vs wasm
    H64 hs, hw;
    RandomGen g;
    g.seed(2026);
    for (int i = 0; i < 200; ++i) {
        appearance::Genome G = randomAppearance(g);
        if (i < 60) { G = appearance::neutral(); G.g[appearance::kMorphOffset + i / 2] = (i & 1) ? 1.0f : 0.0f; }
        // (the draws in sequence: an argument list's evaluation order is unspecified, g++ and clang differ)
        const float S = (float)(0.5 + 1.5 * g.unit());
        const float E = (float)(0.5 + 1.5 * g.unit());
        const physical::Genes P = randomPhysical(g);
        const BirthCoefficients b = compiled(G, S, E, P);
        for (float v : b.m) hs.addf(v);
    }
    {
        Points p;
        BirthCoefficients b;
        compile(appearance::neutral(), 1.0f, 1.0f, physical::neutral(), kGeometryLaw, b, nullptr, &p);
        for (const Vec3& v : p.p) { hs.addf(v.x); hs.addf(v.y); hs.addf(v.z); }
        for (int i = 0; i < kSamples; ++i) for (float a : sampleCoords().s[i].a) hs.addf(a);
    }
    OceanWorld w;
    std::string err;
    ofp::initWorld(w, 77, 1920, 1080, 240.0f, 250, R"({"bodyPlanPreviewEnabled":true,"predatorCount":3})", err);
    for (int s = 0; s < 1500; ++s) w.update(0.016f);
    for (std::size_t i = 0; i < w.bodyPlanOwners().size(); ++i) {
        hw.add((std::uint32_t)w.bodyPlanOwners()[i]);
        for (float v : w.bodyPlanGenes()[i].g) hw.addf(v);
        for (float v : w.bodyPlanBirth()[i].m) hw.addf(v);
    }
    t.expect(w.bodyPlanStats().offspring > 0 && w.bodyPlanEnabled(), "the digest run had no births");
    t.note("digests: 200 fixture bodies + the neutral samples %s; seed 77, 1500 steps (%llu births compiled): %s", hs.str().c_str(),
           (unsigned long long)w.bodyPlanStats().offspring, hw.str().c_str());
    t.note("sizes: genes %zu B, coefficients %zu B, owner 8 B a fish; %zu fish hold %.1f KB (capacities %zu / %zu / %zu)",
           sizeof(physical::Genes), sizeof(BirthCoefficients), w.creatures.size(),
           (double)(w.creatures.size() * (8 + sizeof(physical::Genes) + sizeof(BirthCoefficients))) / 1024.0,
           w.bodyPlanOwners().capacity(), w.bodyPlanGenes().capacity(), w.bodyPlanBirth().capacity());
}

#ifndef OCEAN_TESTS_NO_SHIM
inline void testBodyShim() {
    using namespace body;
    Test t("body_shim");
    t.expect(oc_physical_schema() == 1 && oc_physical_founder_law() == 1 && oc_physical_inheritance_law() == 1 && oc_physical_stream_law() == 1 &&
             oc_physical_genes() == 5 && oc_body_geometry_law() == 1 && oc_body_metrics_abi() == 1 && oc_body_metrics_stride() == kMetrics,
             "the versions and strides");
    t.expect(oc_init(11, 1920, 1080, 240.0, 200, R"({"bodyPlanPreviewEnabled":true})") == 1, "oc_init: %s", oc_last_error());
    oc_step(300);
    oc_sync();
    const int n = oc_creature_count();
    t.expect(oc_body_plan_enabled() == 1 && oc_body_count() == n && oc_creature_physical() && oc_body_owner_ids() && oc_creature_body_metrics(),
             "the export (%d of %d)", oc_body_count(), n);
    long wrong = 0;
    for (int i = 0; i < n && i < oc_body_count(); ++i) {
        const std::uint64_t id = (std::uint64_t)oc_body_owner_ids()[2 * i] | ((std::uint64_t)oc_body_owner_ids()[2 * i + 1] << 32);
        wrong += id != g_world->creatures[(std::size_t)i].id || id != (std::uint64_t)oc_creature_ids()[i];
        wrong += std::memcmp(oc_creature_physical() + 5 * i, g_world->bodyPlanGenes()[(std::size_t)i].g, 20) != 0;
        wrong += std::memcmp(oc_creature_body_metrics() + (std::size_t)kMetrics * i, g_world->bodyPlanBirth()[(std::size_t)i].m, sizeof(float) * kMetrics) != 0;
    }
    t.expect(wrong == 0, "%ld exported rows differ from the arrays", wrong);
    // the cache: a sync without a change does not repack
    const float* p0 = oc_creature_body_metrics();
    const std::uint64_t rev = g_bodyPackedRev;
    oc_sync();
    t.expect(oc_creature_body_metrics() == p0 && g_bodyPackedRev == rev, "an unchanged sync repacked");
    // the layout
    const std::string L = oc_body_metrics_layout();
    t.expect(L.find("\"stride\":" + std::to_string(kMetrics)) != std::string::npos &&
             L.find("{\"name\":\"hullVolume\",\"offset\":" + std::to_string(at(fHullVolume)) + ",\"count\":1,\"units\":\"u3\"") != std::string::npos &&
             L.find("\"genes\":[\"gape\",\"bladderCapacity\",\"armour\",\"fatCapacity\",\"muscleFibre\"]") != std::string::npos,
             "the layout JSON");
    // the viewer's functions: the preview's birth compile is the world's
    {
        const auto& G = g_world->appearanceRecords()[0].genome;
        const Fish& f = g_world->creatures[0];
        t.expect(oc_body_preview(G.g, f.bodySize, f.bodyElong, g_world->bodyPlanGenes()[0].g, 0.0f, 0.0f) == 1 &&
                 std::memcmp(oc_body_preview_metrics(), g_world->bodyPlanBirth()[0].m, sizeof(float) * kMetrics) == 0,
                 "oc_body_preview is not the birth compile");
        t.expect(oc_body_rest(G.g, 20.0f * f.bodyElong / 4.6f) == 1 && oc_body_rest_points() && oc_body_sample_count() == kSamples &&
                 oc_body_tri_count() == kTris && oc_body_tris()[4 * 3 + 3] == 0, "the rest / sample / triangle exports");
    }
    // live keys: the knobs in [0, .25]; the switch only as it is; hydrodynamics refused
    t.expect(oc_set_param("physicalMutation", 0.1) == 1 && g_world->ocfg.physicalMutation == 0.1f, "physicalMutation 0.1 refused: %s", oc_last_error());
    t.expect(oc_set_param("physicalNovelProbability", 0.26) == 0, "physicalNovelProbability 0.26 accepted");
    t.expect(oc_set_param("bodyPlanPreviewEnabled", 1) == 1, "the unchanged switch is not a no-op: %s", oc_last_error());
    t.expect(oc_set_param("bodyPlanPreviewEnabled", 0) == 0, "a live preview change was accepted");
    t.expect(oc_set_param("hydrodynamicsEnabled", 1) == 0, "hydrodynamicsEnabled accepted live");
    for (const char* bad : {R"({"bodyPlanPreviewEnabled":true,"appearance":1})", R"({"bodyPlanPreviewEnabled":true,"appearance":0})",
                            R"({"hydrodynamicsEnabled":true})", R"({"hydrodynamicsEnabled":1})", R"({"hydrodynamicsEnabled":"yes"})",
                            R"({"bodyPlanPreviewEnabled":2})", R"({"physicalMutation":-0.01})", R"({"physicalNovelProbability":1e39})"})
        t.expect(oc_init(11, 1920, 1080, 240.0, 50, bad) == 0, "oc_init accepted %s", bad);
    t.expect(oc_init(11, 1920, 1080, 240.0, 50, R"({"hydrodynamicsEnabled":false,"bodyPlanPreviewEnabled":1,"appearance":2})") == 1,
             "hydrodynamicsEnabled false / the preview with shapes only refused: %s", oc_last_error());
    // off: nothing exported
    t.expect(oc_init(11, 1920, 1080, 240.0, 50, nullptr) == 1, "oc_init: %s", oc_last_error());
    oc_sync();
    t.expect(oc_body_plan_enabled() == 0 && oc_body_count() == 0 && oc_creature_physical() == nullptr && oc_creature_body_metrics() == nullptr,
             "the preview off still exports");
}
#endif

}  // namespace ot

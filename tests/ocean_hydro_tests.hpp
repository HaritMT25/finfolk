#pragma once
// ocean_hydro_tests.hpp — M2b1 PR 1's unit checks (the birth physics
// foundation: src/ocean/hydro_math.hpp, body_material.hpp,
// hydro_coefficients.hpp, hydro_state.hpp), included by tests/ocean_tests.cpp
// just before main (namespace ot: Test, g_passed / g_failed are that file's).
// Nothing here touches a world: public hydrodynamics stays refused.
//
//   hydro_math      S6 packing, rank-1 sums, the spatial congruence (vs dense
//                   double), fixed LDLᵀ (residual <= 2e-5 relative, refusals
//                   of non-positive / non-finite pivots), S3 inverse,
//                   quaternions (unit after integrate, rotate / unrotate),
//                   the angular rail (linear momentum kept, energy lowered)
//   hydro_frame     the frame contract's signs: upright pose columns, a
//                   negative body-z rotation turns toward starboard, a negative
//                   body-y rotation pitches the nose down, world <-> legacy
//   hydro_material  the partition (every cell positive, Σ cells = hull),
//                   organ volumes as requested, paired eyes mirror-exact,
//                   restRoot = the root rows of restVertex, fin laminae = M2a's
//                   areas, the parallel-axis compound = the origin-moment one,
//                   positive inertia at every gene rail
//   hydro_iso       S -> 2S at fixed shape and loading fraction: every
//                   coefficient by its units' power of 2, bit for bit (mass x8,
//                   area x4, inertia x32, the tensors' blocks), the loaded body too
//   hydro_load      the analytic load update vs geometry law 1's inflated
//                   compile (hull moments, mouth, support vertices bit for
//                   bit), the tensor bases vs a direct fin traversal at k, the
//                   COM congruence vs direct COM-relative sums, the unloaded
//                   evalLoad vs the parallel-axis compound
//   hydro_tensors   PSD of Dfin, Afin, Abody, Jbody, Meff and the passive
//                   damping at random states; the retained sway-yaw coupling
//                   signs (a rear fin weathervanes, a forward one does not);
//                   zero-area fins exactly zero; passive-energy contraction of
//                   the implicit solve
//   hydro_stage     dormant alleles (gape, armour, eye size, barbels) swept:
//                   every record bit-identical; the inherited alleles kept
//   hydro_refs      the reference block (law 1) and the neutral body's
//                   numbers: K vs the brief's checks, basal .80, maintenance
//                   .10 at the reference load, Ecap ~45, trim buoyancy, peak
//                   speed window, workConversion; the memory ceilings
//   hydro_refuse    out-of-domain compiles and Params: refused, every output zero
//   hydro_state     the state layout, its hash words, the rest state
//   hydro_numbers   digests of a body set (printed: native == wasm by the
//                   harness's unit-output comparison)
#include <string>
#include <vector>
#include "../src/ocean/hydro_coefficients.hpp"
#include "../src/ocean/hydro_state.hpp"

namespace ot {
namespace hyd {
using namespace hydro;
inline std::uint32_t fb(float f) { std::uint32_t u; std::memcpy(&u, &f, 4); return u; }
inline std::string hex64(std::uint64_t h) { char s[24]; std::snprintf(s, sizeof s, "%016llx", (unsigned long long)h); return s; }
inline double rel(double a, double b, double scale) { return std::fabs(a - b) / (scale > 0 ? scale : 1.0); }

// A body to compile.
struct Body { std::string name; appearance::Genome G; float S, E; physical::Genes P; };
inline Body neutralBody(const char* n) { return Body{n, appearance::neutral(), 1.0f, 1.0f, physical::neutral()}; }
inline std::vector<Body> bodySet(int randoms, unsigned seed = 20261111u) {
    std::vector<Body> B;
    B.push_back(neutralBody("neutral"));
    for (int j = 0; j < appearance::kMorphGenes; ++j)
        for (int v = 0; v < 2; ++v) {
            Body b = neutralBody("");
            b.name = "morph" + std::to_string(j) + (v ? "=1" : "=0");
            b.G.g[appearance::kMorphOffset + j] = v ? 1.0f : 0.0f;
            B.push_back(b);
        }
    {
        Body b = neutralBody("noAppendages");
        for (int j : {11, 12, 16, 19, 23}) b.G.g[appearance::kMorphOffset + j] = 0.0f;
        B.push_back(b);
        b = neutralBody("chordCap");
        b.G.g[appearance::kMorphOffset + 10] = 0.0f; b.G.g[appearance::kMorphOffset + 11] = 1.0f;
        B.push_back(b);
        for (float s : {0.5f, 2.0f})
            for (float e : {0.5f, 2.0f}) {
                b = neutralBody("");
                char nm[40];
                std::snprintf(nm, sizeof nm, "scale%.1f_%.1f", (double)s, (double)e);
                b.name = nm; b.S = s; b.E = e;
                B.push_back(b);
            }
        for (int g = 0; g < physical::kGenes; ++g)
            for (int v = 0; v < 2; ++v) {
                b = neutralBody("");
                b.name = std::string("phys_") + physical::kGeneNames[g] + (v ? "=1" : "=0");
                b.P.g[g] = v ? 1.0f : 0.0f;
                B.push_back(b);
            }
    }
    RandomGen r(seed);
    for (int i = 0; i < randoms; ++i) {
        Body b = neutralBody("");
        b.name = "random" + std::to_string(i);
        double d[appearance::kFounderDraws];
        for (double& x : d) x = r.unit();
        appearance::founderFromDraws(d, appearance::kAll, b.G);
        b.S = 0.5f + 1.5f * r.unit();
        b.E = 0.5f + 1.5f * r.unit();
        for (float& x : b.P.g) x = r.unit();
        B.push_back(b);
    }
    return B;
}
inline int compileBody(const Body& b, Coefficients& c, Support& s, Diagnostics* d = nullptr, const Params& p = Params{}) {
    return compile(b.G, b.S, b.E, b.P, p, c, s, d);
}
// dense double helpers
struct D6 { double a[6][6]; };
inline D6 dense(const S6& A) { D6 o; for (int i = 0; i < 6; ++i) for (int j = 0; j < 6; ++j) o.a[i][j] = at6(A, i, j); return o; }
// The smallest eigenvalue's sign test: LDLᵀ in double of A + eps·tr(A)·1 must succeed.
inline bool psdD(const D6& A, double eps) {
    double tr = 0;
    for (int i = 0; i < 6; ++i) tr += std::fabs(A.a[i][i]);
    double L[6][6] = {}, D[6];
    for (int i = 0; i < 6; ++i) {
        double d = A.a[i][i] + eps * tr + 1e-300;
        for (int k = 0; k < i; ++k) d -= L[i][k] * L[i][k] * D[k];
        if (!(d > 0)) return false;
        D[i] = d;
        for (int j = i + 1; j < 6; ++j) {
            double s = A.a[j][i];
            for (int k = 0; k < i; ++k) s -= L[j][k] * L[i][k] * D[k];
            L[j][i] = s / d;
        }
    }
    return true;
}
inline bool psd3(const S3& A, double eps) {
    D6 o{};
    for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j) o.a[i][j] = at3(A, i, j);
    for (int i = 3; i < 6; ++i) o.a[i][i] = 1.0;
    return psdD(o, eps);
}
inline double maxAbs(const S6& A) { double m = 0; for (float x : A.m) m = std::max(m, (double)std::fabs(x)); return m; }
// A random water-relative state of plausible size.
inline V6 randomState(RandomGen& r, float speed) {
    V6 z;
    for (int i = 0; i < 3; ++i) z.v[i] = speed * (2.0f * r.unit() - 1.0f);
    for (int i = 3; i < 6; ++i) z.v[i] = 6.0f * (2.0f * r.unit() - 1.0f);
    return z;
}
}  // namespace hyd

inline void testHydroMath() {
    using namespace hyd;
    Test t("hydro_math");
    // the S6 packing: every (i, j) a distinct slot, symmetric access
    {
        bool ok = true;
        int seen[21] = {};
        for (int i = 0; i < 6; ++i)
            for (int j = i; j < 6; ++j) { ++seen[s6u(i, j)]; ok = ok && s6(i, j) == s6(j, i); }
        for (int q = 0; q < 21; ++q) ok = ok && seen[q] == 1;
        t.expect(ok && s6u(5, 5) == 20 && s6u(1, 1) == 6 && s6u(3, 3) == 15, "the S6 packing");
        t.expect(s3(0, 1) == 3 && s3(2, 0) == 4 && s3(1, 2) == 5 && s3(2, 2) == 2, "the S3 packing");
    }
    RandomGen r(7u);
    // rank-1 sums and the congruence, vs dense double
    {
        double worst = 0;
        for (int trial = 0; trial < 200; ++trial) {
            S6 A;
            zero(A);
            for (int q = 0; q < 4; ++q) {
                V6 w;
                for (float& x : w.v) x = 2.0f * r.unit() - 1.0f;
                addRank1(A, w, r.unit());
            }
            const V3 c{20.0f * r.unit() - 10.0f, 4.0f * r.unit() - 2.0f, 4.0f * r.unit() - 2.0f};
            const S6 B = congruence(A, c);
            // dense X A Xᵀ
            double X[6][6] = {};
            for (int i = 0; i < 6; ++i) X[i][i] = 1;
            const double K[3][3] = {{0, c.z, -c.y}, {-c.z, 0, c.x}, {c.y, -c.x, 0}};
            for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j) X[3 + i][j] = K[i][j];
            const D6 Ad = dense(A);
            double Y[6][6] = {}, Z[6][6] = {};
            for (int i = 0; i < 6; ++i) for (int j = 0; j < 6; ++j) for (int k = 0; k < 6; ++k) Y[i][j] += X[i][k] * Ad.a[k][j];
            for (int i = 0; i < 6; ++i) for (int j = 0; j < 6; ++j) for (int k = 0; k < 6; ++k) Z[i][j] += Y[i][k] * X[j][k];
            double scale = 0;
            for (int i = 0; i < 6; ++i) for (int j = 0; j < 6; ++j) scale = std::max(scale, std::fabs(Z[i][j]));
            for (int i = 0; i < 6; ++i) for (int j = 0; j < 6; ++j) worst = std::max(worst, rel(at6(B, i, j), Z[i][j], scale));
        }
        t.expect(worst <= 2e-6, "congruence vs dense double: worst %.3g", worst);
    }
    // LDLᵀ: residual and refusals
    {
        double worst = 0;
        for (int trial = 0; trial < 300; ++trial) {
            S6 A;
            zero(A);
            for (int q = 0; q < 8; ++q) {
                V6 w;
                for (float& x : w.v) x = 2.0f * r.unit() - 1.0f;
                addRank1(A, w, 0.1f + r.unit());
            }
            for (int i = 0; i < 6; ++i) A.m[s6u(i, i)] = A.m[s6u(i, i)] + 0.05f;
            V6 b;
            for (float& x : b.v) x = 2.0f * r.unit() - 1.0f;
            V6 x{};
            if (!t.expect(solveScaled(A, b, 1.0f + 10.0f * r.unit(), x), "SPD factorization failed")) continue;
            const D6 Ad = dense(A);
            double rn = 0, bn = 0;
            for (int i = 0; i < 6; ++i) {
                double s = -b.v[i];
                for (int j = 0; j < 6; ++j) s += Ad.a[i][j] * x.v[j];
                rn += s * s; bn += (double)b.v[i] * b.v[i];
            }
            worst = std::max(worst, std::sqrt(rn / bn));
        }
        t.expect(worst <= 2e-5, "LDL residual |Ax - b|/|b|: worst %.3g", worst);
        t.note("LDLᵀ residual over 300 SPD systems: worst %.2e (bound 2e-5)", worst);
        S6 A;
        zero(A);
        for (int i = 0; i < 6; ++i) A.m[s6u(i, i)] = 1.0f;
        A.m[s6u(2, 2)] = 0.0f;
        LDL6 f;
        t.expect(!factorLDL(A, f) && f.failedPivot == 2, "a zero pivot was not refused (%d)", f.failedPivot);
        A.m[s6u(2, 2)] = -1.0f;
        t.expect(!factorLDL(A, f) && f.failedPivot == 2, "a negative pivot was not refused");
        A.m[s6u(2, 2)] = 1.0f;
        A.m[s6u(4, 4)] = NAN;
        t.expect(!factorLDL(A, f) && f.failedPivot == 4, "a NaN pivot was not refused");
        A.m[s6u(4, 4)] = 1.0f;
        A.m[s6u(0, 1)] = 2.0f;   // indefinite: the second pivot 1 − 4 < 0
        t.expect(!factorLDL(A, f) && f.failedPivot == 1, "an indefinite matrix was not refused");
        V6 x{{9, 9, 9, 9, 9, 9}};
        t.expect(!solveScaled(A, V6{{1, 1, 1, 1, 1, 1}}, 3.0f, x) && x.v[0] == 9.0f, "a refused solve changed its output");
    }
    // S3 inverse
    {
        const S3 A{{4.0f, 5.0f, 6.0f, 1.0f, 0.5f, -0.25f}}, Z{{1.0f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f}};
        S3 Ai;
        bool ok = invS3(A, Ai);
        const V3 v{1.0f, -2.0f, 3.0f}, back = mulS3(A, mulS3(Ai, v));
        t.expect(ok && std::fabs(back.x - v.x) < 1e-5f && std::fabs(back.y - v.y) < 1e-5f && std::fabs(back.z - v.z) < 1e-5f, "S3 inverse");
        S3 junk = A;
        t.expect(!invS3(Z, junk) && junk.m[0] == A.m[0], "a singular S3 was inverted");
    }
    // quaternions
    {
        double worstUnit = 0, worstRound = 0;
        for (int trial = 0; trial < 200; ++trial) {
            Q4 q{2.0f * r.unit() - 1.0f, 2.0f * r.unit() - 1.0f, 2.0f * r.unit() - 1.0f, 2.0f * r.unit() - 1.0f};
            q = qnormalize(q);
            for (int s = 0; s < 50; ++s) q = integrate(q, V3{12.0f * r.unit() - 6.0f, 12.0f * r.unit() - 6.0f, 12.0f * r.unit() - 6.0f}, 0.008f);
            worstUnit = std::max(worstUnit, std::fabs((double)qnorm2(q) - 1.0));
            const V3 v{3.0f * r.unit(), -2.0f, 1.0f}, b = unrotate(q, rotate(q, v));
            worstRound = std::max(worstRound, (double)std::sqrt(norm2(sub(b, v))) / std::sqrt((double)norm2(v)));
        }
        t.expect(worstUnit <= 1e-6 && worstRound <= 4e-6, "quaternion unit %.3g / round trip %.3g", worstUnit, worstRound);
        // composition: rotate(a ⊗ b, v) = rotate(a, rotate(b, v))
        const Q4 a = qnormalize(Q4{0.9f, 0.1f, -0.3f, 0.2f}), b = qnormalize(Q4{0.2f, 0.7f, 0.1f, -0.4f});
        const V3 v{1.0f, 2.0f, 3.0f}, x = rotate(qmul(a, b), v), y = rotate(a, rotate(b, v));
        t.expect(std::sqrt(norm2(sub(x, y))) < 1e-5f, "quaternion composition");
        bool ok = true;
        qnormalize(Q4{0, 0, 0, 0}, &ok);
        t.expect(!ok, "a zero quaternion normalized");
    }
    // the angular rail: linear momentum A u + B ω kept, energy lowered
    {
        Coefficients c;
        Support s;
        compileBody(neutralBody("neutral"), c, s);
        Loaded L;
        evalLoad(c, 10.0f, 0.05f, L);
        double worstP = 0;
        bool lowered = true;
        for (int trial = 0; trial < 200; ++trial) {
            const V6 z = randomState(r, 100.0f);
            V3 u{z.v[0], z.v[1], z.v[2]}, w{z.v[3], z.v[4], z.v[5]};
            const float a = r.unit();
            const D6 M = dense(L.Meff);
            double p0[3], p1[3], e0 = 0, e1 = 0;
            const double zz0[6] = {u.x, u.y, u.z, w.x, w.y, w.z};
            for (int i = 0; i < 3; ++i) { p0[i] = 0; for (int j = 0; j < 6; ++j) p0[i] += M.a[i][j] * zz0[j]; }
            for (int i = 0; i < 6; ++i) for (int j = 0; j < 6; ++j) e0 += zz0[i] * M.a[i][j] * zz0[j];
            t.expect(railProject(L.Meff, u, w, a), "rail projection refused");
            const double zz1[6] = {u.x, u.y, u.z, w.x, w.y, w.z};
            for (int i = 0; i < 3; ++i) { p1[i] = 0; for (int j = 0; j < 6; ++j) p1[i] += M.a[i][j] * zz1[j]; }
            for (int i = 0; i < 6; ++i) for (int j = 0; j < 6; ++j) e1 += zz1[i] * M.a[i][j] * zz1[j];
            const double pn = std::sqrt(p0[0] * p0[0] + p0[1] * p0[1] + p0[2] * p0[2]) + 1e-9;
            for (int i = 0; i < 3; ++i) worstP = std::max(worstP, std::fabs(p1[i] - p0[i]) / pn);
            lowered = lowered && e1 <= e0 * (1 + 1e-6);
        }
        t.expect(worstP <= 1e-5 && lowered, "the rail changed the linear momentum (%.3g) or raised the energy", worstP);
        t.expect(railScale(4.0f, 12.0f) == 1.0f && railScale(400.0f, 12.0f) == 12.0f / 20.0f, "railScale");
    }
}

inline void testHydroFrame() {
    using namespace hyd;
    Test t("hydro_frame");
    // upright, heading along legacy +x (world +x): body x (tail) = −f, starboard = f × up, dorsal = up
    const V3 f{1.0f, 0.0f, 0.0f};
    const Q4 q = uprightPose(f);
    V3 ex, ey, ez;
    columns(q, ex, ey, ez);
    auto near = [](V3 a, V3 b) { return std::sqrt(norm2(sub(a, b))) < 1e-6f; };
    t.expect(near(ex, V3{-1, 0, 0}) && near(ez, kWorldUp) && near(ey, cross(f, kWorldUp)), "upright columns");
    t.expect(near(cross(ex, ey), ez), "the body frame is right-handed");
    // in legacy coordinates, starboard of a fish heading legacy +x: f × up = (0, 0, +1) world = legacy +y
    // (the M2 adapter, PR 2, maps the legacy turn sign onto body yaw through this)
    float lx, ly, ld;
    legacyFromWorld(ey, lx, ly, ld);
    t.expect(std::fabs(lx) < 1e-6f && std::fabs(ly - 1.0f) < 1e-6f && std::fabs(ld) < 1e-6f, "starboard in legacy coordinates (%g %g %g)",
             (double)lx, (double)ly, (double)ld);
    // a negative rotation about body z turns the nose (body −x) toward starboard
    {
        const float h = 0.05f;
        const Q4 q2 = integrate(q, V3{0.0f, 0.0f, -1.0f}, h);   // ω_z < 0
        const V3 nose = rotate(q2, V3{-1, 0, 0});
        t.expect(dot(nose, ey) > 0.0f, "negative yaw did not turn toward starboard");
    }
    // a negative rotation about body y pitches the nose down
    {
        const Q4 q2 = integrate(q, V3{0.0f, -1.0f, 0.0f}, 0.05f);
        const V3 nose = rotate(q2, V3{-1, 0, 0});
        t.expect(nose.y < 0.0f, "negative pitch did not put the nose down (%g)", (double)nose.y);
    }
    // a negative rotation about body x (the tail axis) is a positive roll about the nose axis:
    // the dorsal side tips to starboard; a positive one to port
    {
        const V3 dn = rotate(integrate(q, V3{-1.0f, 0.0f, 0.0f}, 0.05f), V3{0, 0, 1});
        const V3 dp = rotate(integrate(q, V3{1.0f, 0.0f, 0.0f}, 0.05f), V3{0, 0, 1});
        t.expect(dot(dn, ey) > 0.0f && dot(dp, ey) < 0.0f, "roll sign");
    }
    // other headings: f = (cos, 0, sin)
    for (int k = 0; k < 8; ++k) {
        const float a = 0.7853982f * k;
        const V3 fk{evomath::cosf(a), 0.0f, evomath::sinf(a)};
        const Q4 qk = uprightPose(fk);
        V3 x, y, z;
        columns(qk, x, y, z);
        t.expect(near(x, mul(fk, -1.0f)) && near(z, kWorldUp) && near(y, cross(fk, kWorldUp)), "upright pose at heading %d", k);
    }
    const V3 w = worldFromLegacy(10.0f, 20.0f, 30.0f);
    t.expect(w.x == 10.0f && w.y == -30.0f && w.z == 20.0f, "world from legacy");
    legacyFromWorld(w, lx, ly, ld);
    t.expect(lx == 10.0f && ly == 20.0f && ld == 30.0f, "legacy from world");
}

inline void testHydroMaterial() {
    using namespace hyd;
    Test t("hydro_material");
    const std::vector<Body> B = bodySet(60);
    double worstCells = 0, worstOrgan = 0, worstCompound = 0;
    float minCell = INFINITY;
    int compiled = 0, rootRows = 0, rootBad = 0, finAreaBad = 0;
    for (const Body& b : B) {
        Coefficients c;
        Support s;
        Diagnostics d;
        if (!t.expect(compileBody(b, c, s, &d) == kOk, "%s did not compile (%d)", b.name.c_str(), d.error)) continue;
        ++compiled;
        const bodymat::Material& m = d.material;
        minCell = std::min(minCell, m.minCellVolume);
        worstCells = std::max(worstCells, rel(m.cellVolumeSum, m.hull.v, m.hull.v));
        worstOrgan = std::max({worstOrgan, rel(m.jaw.v, m.jawTarget, m.hull.v), rel(m.eyes.v, m.eyeTarget, m.hull.v),
                               rel(m.walls.v, m.wallTarget, m.hull.v)});
        t.expect(m.jawAlloc.shortfall == 0.0f && m.eyeAlloc.shortfall == 0.0f && m.wallAlloc.shortfall == 0.0f, "%s: an organ short", b.name.c_str());
        t.expect(m.eyes.f[1] == 0.0f && m.eyes.s[3] == 0.0f && m.eyes.s[5] == 0.0f, "%s: the eye pair is not mirror-exact", b.name.c_str());
        t.expect(m.tissue.v > 0.0f && m.muscleVolume == bodymat::kMuscleFraction * m.tissue.v, "%s: tissue / muscle", b.name.c_str());
        t.expect(m.jaw.v >= 0.0f && m.walls.v >= 0.0f && m.eyes.v > 0.0f, "%s: a negative allocation", b.name.c_str());
        // fin laminae: area = M2a's, bit for bit
        for (int f = 0; f < bodyplan::kFinCount; ++f) {
            const float area = d.body.m[bodyplan::finAt(f, bodyplan::kFinArea)], tf = d.body.m[bodyplan::finAt(f, bodyplan::kFinThickness)];
            if (area > 0.0f && fb(m.fin[f].v) != fb(area * tf)) ++finAreaBad;
            if (!(area > 0.0f) && m.fin[f].v != 0.0f) ++finAreaBad;
        }
        // the parallel-axis compound vs the origin-moment assembly (evalLoad unloaded)
        Loaded L;
        evalLoad(c, 0.0f, 0.0f, L);
        const double Is = std::fabs(d.compoundInertia[0]) + std::fabs(d.compoundInertia[1]) + std::fabs(d.compoundInertia[2]);
        worstCompound = std::max({worstCompound, rel(L.mass, d.compoundMass, d.compoundMass),
                                  rel(L.com.x, d.compoundCom[0], c.hullLength), rel(L.com.y, d.compoundCom[1], c.hullLength),
                                  rel(L.com.z, d.compoundCom[2], c.hullLength)});
        for (int q = 0; q < 6; ++q) worstCompound = std::max(worstCompound, rel(L.inertia.m[q], d.compoundInertia[q], Is));
        // positive inertia, triangle inequality
        const float* I = L.inertia.m;
        t.expect(I[0] > 0 && I[1] > 0 && I[2] > 0 && I[0] <= I[1] + I[2] && I[1] <= I[0] + I[2] && I[2] <= I[0] + I[1] && psd3(L.inertia, 0.0),
                 "%s: the inertia is not a valid inertia", b.name.c_str());
        // restRoot = restVertex at the root rows
        const bodyplan::Morph M = bodyplan::decodeMorph(expressAppearance(b.G).g, c.refLength / c.radius);
        const bodyplan::Samples& S = bodyplan::sampleCoords();
        for (int i = bodyplan::kDorsal0; i < bodyplan::kEyeR0; ++i) {
            const bodyplan::Sample& sm = S.s[i];
            if (sm.a[1] != 0.0f) continue;   // root rows only (q = 0 / r = 0)
            ++rootRows;
            const bodyplan::Vec3 v = bodyplan::restVertex(M, sm.a, sm.fin, sm.side), rt = bodyplan::restRoot(M, sm.a, sm.fin, sm.side);
            const bool median = sm.fin == 2 || sm.fin == 5;
            if (fb(v.x) != fb(rt.x) || fb(v.z) != fb(rt.z) || (!median && fb(v.y) != fb(rt.y)) || (median && v.y != 0.0f)) ++rootBad;
        }
    }
    t.expect(compiled == (int)B.size(), "%d of %zu bodies compiled", compiled, B.size());
    t.expect(minCell > 0.0f, "a non-positive cell (%g)", (double)minCell);
    t.expect(worstCells <= 1e-5, "Σ cells vs hull: %.3g", worstCells);
    t.expect(worstOrgan <= 1e-6, "organ volume vs requested: %.3g (of V)", worstOrgan);
    t.expect(rootBad == 0 && rootRows > 0, "restRoot differs from the root rows: %d of %d", rootBad, rootRows);
    t.expect(finAreaBad == 0, "fin laminae differ from M2a's areas: %d", finAreaBad);
    t.expect(worstCompound <= 2e-5, "parallel-axis vs origin-moment compound: %.3g", worstCompound);
    t.note("%d bodies: smallest cell %.4g u³; Σ cells vs hull %.2e; organs vs requested %.2e V; compound agreement %.2e", compiled,
           (double)minCell, worstCells, worstOrgan, worstCompound);
    // a non-zero shell has no law-1 allocation: the material allocator refuses it
    {
        const Body b = neutralBody("armour");
        bodyplan::BirthCoefficients bc;
        bodyplan::Points pts;
        physical::Genes P = b.P;
        P.g[physical::kArmour] = 1.0f;   // unmasked: geometry law 1 develops a shell
        bodyplan::compile(b.G, 1.0f, 1.0f, P, bodyplan::kGeometryLaw, bc, nullptr, &pts);
        bodymat::Material m;
        const bodyplan::Morph M = bodyplan::decodeMorph(b.G.g, bc.m[bodyplan::at(bodyplan::fLambda)]);
        t.expect(bc.m[bodyplan::at(bodyplan::fShellVolume)] > 0.0f && !bodymat::allocateMaterial(bc, M, pts, 0.5f, 0.4f, m),
                 "a non-zero shell was allocated by law 1");
    }
}

inline void testHydroIso() {
    using namespace hyd;
    Test t("hydro_iso");
    // the units' power of 2 of every coefficient under S -> 2S (−1: not a pure units quantity)
    std::vector<int> pw(kCoefficientFloats, -99);
    auto setp = [&](const char* name, std::initializer_list<int> p) {
        for (const FieldInfo& f : kCoefficientFields)
            if (!std::strcmp(f.name, name)) {
                int k = 0;
                for (int v : p) { if (k < f.count) pw[f.offset + k] = v; ++k; }
                if ((int)p.size() == 1) for (int j = 0; j < f.count; ++j) pw[f.offset + j] = *p.begin();
            }
    };
    for (const char* n : {"size", "refLength", "halfLength", "radius", "hullCentroid", "hullLength", "halfWidth", "halfDepth", "caudalCentroid",
                          "caudalBasis", "pairedCentroid", "pairedBasis", "mouth", "mouthBasis"}) setp(n, {1});
    for (const char* n : {"elong", "foreAft", "addedMass", "caudalNormal", "pairedNormal", "pairedAspect", "tailEfficiency", "fibre"}) setp(n, {0});
    for (const char* n : {"hullCovariance", "frontalArea", "sideArea", "planArea", "wettedArea", "finArea", "caudalArea", "pairedArea", "propArea"}) setp(n, {2});
    for (const char* n : {"hullVolume", "finVolume", "innerMass", "finMass", "gasCapacity", "reserveCapacity", "energyCapacity", "leanMass",
                          "muscleVolume", "muscleMass", "leanRatio", "muscleRatio", "maintenancePower", "buildEnergy", "motorP0",
                          "sustainedPower", "peakPower", "fatigueCapacity"}) setp(n, {3});
    for (const char* n : {"innerFirst", "finFirst0", "finFirst1"}) setp(n, {4});
    for (const char* n : {"innerSecond", "finSecond0", "finSecond1", "finSecond2", "addedA2"}) setp(n, {5});
    setp("rowSpeed", {-1});
    // tensors: D0 tt x4 (2), tr x8 (3), rr x16 (4); A0 one more power; D1 cross x8, rot x16; D2 x16
    for (const FieldInfo& f : kCoefficientFields) {
        const bool isD = !std::strncmp(f.name, "dampD", 5), isA = !std::strncmp(f.name, "addedA", 6);
        if (!isD && !isA) continue;
        const int extra = isA ? 1 : 0;
        for (int q = 0; q < f.count; ++q) {
            int p;
            if (f.count == 21) {
                int i = 0, j = 0;
                for (int a = 0; a < 6; ++a) for (int b2 = a; b2 < 6; ++b2) if (s6u(a, b2) == q) { i = a; j = b2; }
                p = 2 + (i >= 3) + (j >= 3);
            } else if (f.count == 15) p = q < 9 ? 3 : 4;
            else p = 4;
            pw[f.offset + q] = p + extra;
        }
    }
    int unset = 0;
    for (int v : pw) if (v == -99) ++unset;   // skinFriction, tailTau, leanFactor, basalPower: physics, not units
    t.expect(unset == 4, "%d coefficients without a scaling class (expected 4)", unset);
    const std::vector<Body> B = bodySet(30, 77u);
    long compared = 0, bad = 0;
    std::string firstBad;
    for (const Body& b0 : B) {
        Body b1 = b0, b2 = b0;
        b1.S = 0.75f; b2.S = 1.5f;   // exactly 2x
        Coefficients c1, c2;
        Support s1, s2;
        if (compileBody(b1, c1, s1) != kOk || compileBody(b2, c2, s2) != kOk) { ++bad; continue; }
        const float* x1 = floats(c1);
        const float* x2 = floats(c2);
        for (int i = 0; i < kCoefficientFloats; ++i) {
            if (pw[i] == -99) continue;
            ++compared;
            const float want = std::ldexp(x1[i], pw[i]);
            if (fb(want) != fb(x2[i]) && !(want == 0.0f && x2[i] == 0.0f)) {
                if (!bad++) {
                    for (const FieldInfo& f : kCoefficientFields)
                        if (i >= f.offset && i < f.offset + f.count) firstBad = b0.name + " " + f.name + "[" + std::to_string(i - f.offset) + "]";
                }
            }
        }
        // the support: body radii fixed, R and the bounds x2
        for (int i = 0; i < kSupportFloats; ++i) {
            ++compared;
            const int p = (i == 0 || i >= kSupportFloats - 4) ? 1 : 0;
            if (fb(std::ldexp(floats(s1)[i], p)) != fb(floats(s2)[i])) { if (!bad++) firstBad = b0.name + " support[" + std::to_string(i) + "]"; }
        }
        // the loaded body at a fixed loading fraction (gas .6 of capacity, fuel .3 of the reserve)
        Loaded L1, L2;
        const float g1 = 0.6f * c1.gasCapacity, g2 = 0.6f * c2.gasCapacity;
        const float m1 = (0.3f * c1.reserveCapacity) * (bodymat::kRhoLipid * rhoWater()), m2 = (0.3f * c2.reserveCapacity) * (bodymat::kRhoLipid * rhoWater());
        evalLoad(c1, g1, m1, L1);
        evalLoad(c2, g2, m2, L2);
        auto chk = [&](float a, float b2v, int p, const char* what) {
            ++compared;
            if (fb(std::ldexp(a, p)) != fb(b2v) && !(a == 0.0f && b2v == 0.0f)) { if (!bad++) firstBad = b0.name + " loaded " + what; }
        };
        chk(L1.k, L2.k, 0, "k");
        chk(L1.mass, L2.mass, 3, "mass");
        chk(L1.com.x, L2.com.x, 1, "com");
        for (int q = 0; q < 6; ++q) chk(L1.inertia.m[q], L2.inertia.m[q], 5, "inertia");
        for (int i = 0; i < 6; ++i)
            for (int j = i; j < 6; ++j) {
                const int nr = (i >= 3) + (j >= 3);
                chk(at6(L1.Meff, i, j), at6(L2.Meff, i, j), 3 + nr, "Meff");
                chk(at6(L1.Dfin, i, j), at6(L2.Dfin, i, j), 2 + nr, "Dfin");
            }
    }
    t.expect(bad == 0, "%ld of %ld isometry comparisons differ; first: %s", bad, compared, firstBad.c_str());
    t.note("S -> 2S: %ld comparisons bit-exact over %zu bodies (records, support, loaded mass / COM / inertia / Meff / Dfin)", compared, B.size());
}

inline void testHydroLoad() {
    using namespace hyd;
    Test t("hydro_load");
    const std::vector<Body> B = bodySet(30, 99u);
    double worstHull = 0, worstMouth = 0, worstFin = 0, worstTensor = 0, worstCom = 0, worstLipid = 0;
    long supportBad = 0, supportN = 0;
    for (const Body& b : B) {
        Coefficients c;
        Support s;
        Diagnostics d;
        if (compileBody(b, c, s, &d) != kOk) { t.expect(false, "%s did not compile", b.name.c_str()); continue; }
        const appearance::Genome Gx = expressAppearance(b.G);
        const physical::Genes Px = expressPhysical(b.P);
        for (const float lg : {0.25f, 1.0f})
            for (const float lf : {0.0f, 0.5f, 1.0f}) {
                // geometry law 1's inflated compile
                bodyplan::Load load;
                load.gas = lg; load.fuel = lf;
                bodyplan::BirthCoefficients bl;
                bodyplan::Points pl;
                bodyplan::compile(Gx, b.S, b.E, Px, bodyplan::kGeometryLaw, bl, &load, &pl);
                const float kk = bl.m[bodyplan::at(bodyplan::fInflation)];
                // the same load through the analytic update: Vgas, Mfuel
                const float Vg = lg * c.gasCapacity, Vf = lf * c.reserveCapacity;
                const float Mf = Vf * (bodymat::kRhoLipid * rhoWater());
                Loaded L;
                evalLoad(c, Vg, Mf, L);
                worstHull = std::max(worstHull, rel(L.k, kk, 1.0));
                // hull volume, centroid, inertia (density 1, about its own centroid)
                const float* hm = bl.m;
                worstHull = std::max(worstHull, rel(L.hullVolume, hm[bodyplan::at(bodyplan::fHullVolume)], c.hullVolume));
                for (int q = 0; q < 3; ++q) worstHull = std::max(worstHull, rel(L.hullCentroid.x * (q == 0) + L.hullCentroid.y * (q == 1) + L.hullCentroid.z * (q == 2),
                                                                              hm[bodyplan::at(bodyplan::fHullCentroid) + q], c.hullLength));
                {
                    const S3 cov = stretchS3(S3{{c.hullCovariance[0], c.hullCovariance[1], c.hullCovariance[2], c.hullCovariance[3], c.hullCovariance[4],
                                                 c.hullCovariance[5]}}, L.k);
                    const S3 I = inertiaOf(cov);
                    const float* Ib = hm + bodyplan::at(bodyplan::fHullInertia);
                    const double sc = (double)Ib[0] + Ib[1] + Ib[2];
                    for (int q = 0; q < 6; ++q) worstHull = std::max(worstHull, rel((double)I.m[q] * L.hullVolume, Ib[q], sc));
                }
                for (int q = 0; q < 3; ++q)
                    worstMouth = std::max(worstMouth, rel(q == 0 ? L.mouth.x : q == 1 ? L.mouth.y : L.mouth.z, hm[bodyplan::at(bodyplan::fMouthCentre) + q], c.hullLength));
                // the loaded fins' centroids (the inflated mesh) vs the law's p0 + t b
                for (int q = 0; q < 4; ++q) {
                    const int f = q == 0 ? bodyplan::kFinPecR : q == 1 ? bodyplan::kFinPecL : q == 2 ? bodyplan::kFinPelR : bodyplan::kFinPelL;
                    if (!(c.pairedArea[q] > 0.0f)) continue;
                    for (int j = 0; j < 3; ++j)
                        worstFin = std::max(worstFin, rel(c.pairedCentroid[3 * q + j] + L.t * c.pairedBasis[3 * q + j],
                                                          hm[bodyplan::finAt(f, bodyplan::kFinCentroid + j)], c.radius));
                }
                for (const int f : {bodyplan::kFinDorsal, bodyplan::kFinAnal}) {
                    const float* p0 = d.body.m + bodyplan::finAt(f, bodyplan::kFinCentroid);
                    if (!(d.body.m[bodyplan::finAt(f, bodyplan::kFinArea)] > 0.0f)) continue;
                    const V3 b0 = d.material.finBasis[f];
                    worstFin = std::max(worstFin, rel(p0[2] + L.t * b0.z, hm[bodyplan::finAt(f, bodyplan::kFinCentroid + 2)], c.radius));
                }
                // the support's vertices at law 1's own k: bit for bit
                for (int v = 0; v < kSupportVertices; ++v) {
                    ++supportN;
                    const V3 a = supportVertex(s, v, kk);
                    if (fb(a.x) != fb(pl.p[v].x) || fb(a.y) != fb(pl.p[v].y) || fb(a.z) != fb(pl.p[v].z)) ++supportBad;
                }
                // the tensor bases vs a direct traversal at k (double), about the COM
                {
                    double Dd[6][6] = {}, Ad[6][6] = {};
                    const double rw = rhoWater();
                    for (int f = 0; f < bodyplan::kFinCount; ++f) {
                        const float A = d.body.m[bodyplan::finAt(f, bodyplan::kFinArea)];
                        if (!(A > 0.0f)) continue;
                        const float* n = d.body.m + bodyplan::finAt(f, bodyplan::kFinNormal);
                        const float* p0 = d.body.m + bodyplan::finAt(f, bodyplan::kFinCentroid);
                        const V3 bb = d.material.finBasis[f];
                        const double p[3] = {p0[0] + (double)L.t * bb.x - L.com.x, p0[1] + (double)L.t * bb.y - L.com.y, p0[2] + (double)L.t * bb.z - L.com.z};
                        const double w[6] = {n[0], n[1], n[2], p[1] * n[2] - p[2] * n[1], p[2] * n[0] - p[0] * n[2], p[0] * n[1] - p[1] * n[0]};
                        const double dd = 0.5 * rw * kCn * A, ma = kFinAddedCoef * rw * A * d.body.m[bodyplan::finAt(f, bodyplan::kFinMeanChord)];
                        for (int i = 0; i < 6; ++i) for (int j = 0; j < 6; ++j) { Dd[i][j] += dd * w[i] * w[j]; Ad[i][j] += ma * w[i] * w[j]; }
                    }
                    double sD = 0, sA = 0;
                    for (int i = 0; i < 6; ++i) for (int j = 0; j < 6; ++j) { sD = std::max(sD, std::fabs(Dd[i][j])); sA = std::max(sA, std::fabs(Ad[i][j])); }
                    for (int i = 0; i < 6; ++i)
                        for (int j = 0; j < 6; ++j) {
                            worstTensor = std::max(worstTensor, rel(at6(L.Dfin, i, j), Dd[i][j], sD));
                            worstTensor = std::max(worstTensor, rel(at6(L.Afin, i, j), Ad[i][j], sA));
                        }
                }
                // the COM vs a direct double sum of the parts (inner stretched, lipid, fins translated)
                {
                    const double k = L.k, tt = L.t;
                    double M = c.innerMass + Mf + c.finMass;
                    double F[3] = {c.innerFirst[0] + Mf * c.hullCentroid[0] + c.finFirst0[0] + tt * c.finFirst1[0],
                                   k * c.innerFirst[1] + Mf * k * c.hullCentroid[1] + c.finFirst0[1] + tt * c.finFirst1[1],
                                   k * c.innerFirst[2] + Mf * k * c.hullCentroid[2] + c.finFirst0[2] + tt * c.finFirst1[2]};
                    worstCom = std::max({worstCom, rel(L.mass, M, M), rel(L.com.x, F[0] / M, c.hullLength), rel(L.com.y, F[1] / M, c.hullLength),
                                         rel(L.com.z, F[2] / M, c.hullLength)});
                    worstLipid = std::max(worstLipid, rel(L.displaced, (double)c.hullVolume + Vg + Mf / (0.9 * rhoWater()) + c.finVolume, c.hullVolume));
                }
            }
    }
    t.expect(worstHull <= 1e-5, "analytic hull load update vs law 1's inflated compile: %.3g", worstHull);
    t.expect(worstMouth <= 1e-6, "loaded mouth: %.3g", worstMouth);
    t.expect(worstFin <= 1e-2, "loaded fin centroid (law: fixed planform) vs the inflated mesh: %.3g R", worstFin);
    t.expect(supportBad == 0, "%ld of %ld loaded support vertices differ from law 1's inflated points", supportBad, supportN);
    t.expect(worstTensor <= 2e-5, "tensor bases + congruence vs a direct traversal: %.3g", worstTensor);
    t.expect(worstCom <= 2e-6 && worstLipid <= 1e-6, "loaded COM %.3g / displacement %.3g", worstCom, worstLipid);
    t.note("hull update %.2e, mouth %.2e, fin centroids %.2e R (planform-law residual), tensors %.2e, COM %.2e; %ld support vertices bit-exact",
           worstHull, worstMouth, worstFin, worstTensor, worstCom, supportN);
}

inline void testHydroTensors() {
    using namespace hyd;
    Test t("hydro_tensors");
    const std::vector<Body> B = bodySet(30, 5u);
    RandomGen r(31u);
    int notPsd = 0, cases = 0;
    double worstContraction = -1, worstResidual = 0;
    for (const Body& b : B) {
        Coefficients c;
        Support s;
        if (compileBody(b, c, s) != kOk) continue;
        for (int load = 0; load < 3; ++load) {
            Loaded L;
            evalLoad(c, (0.5f * load) * c.gasCapacity, (0.5f * load) * c.reserveCapacity * (bodymat::kRhoLipid * rhoWater()), L);
            ++cases;
            if (!psdD(dense(L.Dfin), 1e-6) || !psdD(dense(L.Afin), 1e-6) || !psdD(dense(L.Abody), 1e-6) || !psd3(L.Jbody, 1e-6) ||
                !psdD(dense(L.Meff), 0.0))
                ++notPsd;
            for (int k = 0; k < 4; ++k) {
                const V6 z = randomState(r, 150.0f);
                const S6 D = passiveDamping(L, c.halfLength, z);
                if (!psdD(dense(D), 1e-6)) ++notPsd;
                // (Meff + h D) z' = Meff z  =>  z'ᵀ Meff z' <= zᵀ Meff z
                const float h = 0.008f;
                S6 A = L.Meff;
                for (int q = 0; q < 21; ++q) A.m[q] = A.m[q] + h * D.m[q];
                const V6 rhs = mulS6(L.Meff, z);
                V6 x{};
                if (!t.expect(solveScaled(A, rhs, c.halfLength, x), "%s: the passive solve failed", b.name.c_str())) continue;
                const D6 M = dense(L.Meff), Ad = dense(A);
                double e0 = 0, e1 = 0, rn = 0, bn = 0;
                for (int i = 0; i < 6; ++i) {
                    double ax = -rhs.v[i];
                    for (int j = 0; j < 6; ++j) { e0 += z.v[i] * M.a[i][j] * z.v[j]; e1 += x.v[i] * M.a[i][j] * x.v[j]; ax += Ad.a[i][j] * x.v[j]; }
                    rn += ax * ax; bn += (double)rhs.v[i] * rhs.v[i];
                }
                worstContraction = std::max(worstContraction, e1 / e0 - 1.0);
                worstResidual = std::max(worstResidual, std::sqrt(rn / bn));
            }
        }
    }
    t.expect(notPsd == 0, "%d of %d tensors not PSD", notPsd, cases * 5);
    t.expect(worstContraction <= 1e-6, "the passive solve raised the kinetic energy: e1/e0 − 1 = %.3g", worstContraction);
    t.expect(worstResidual <= 2e-5, "passive solve residual %.3g", worstResidual);
    t.note("%d loaded bodies x 4 states: all PSD; energy ratio − 1 at most %.3g; residual %.2e", cases, worstContraction, worstResidual);
    // the retained couplings: a lone dorsal fin behind the COM weathervanes (sway-yaw > 0), in front it does not
    {
        auto dorsalOnly = [&](float placement) {
            appearance::Genome G = appearance::neutral();
            for (int j : {11, 16, 19, 23}) G.g[appearance::kMorphOffset + j] = 0.0f;   // no caudal, anal, pectorals, pelvics
            G.g[appearance::kMorphOffset + 12] = 1.0f;   // a tall dorsal
            G.g[appearance::kMorphOffset + 13] = 0.0f;   // short
            G.g[appearance::kMorphOffset + 14] = placement;
            Coefficients c;
            Support s;
            compile(G, 1.0f, 1.0f, physical::neutral(), Params{}, c, s);
            Loaded L;
            evalLoad(c, 0.0f, 0.0f, L);
            return L;
        };
        const Loaded front = dorsalOnly(0.0f), back = dorsalOnly(1.0f);
        t.expect(at6(back.Dfin, 1, 5) > 0.0f && at6(front.Dfin, 1, 5) < 0.0f, "sway-yaw signs: front %g, back %g",
                 (double)at6(front.Dfin, 1, 5), (double)at6(back.Dfin, 1, 5));
        t.expect(at6(back.Afin, 1, 5) > 0.0f && at6(front.Afin, 1, 5) < 0.0f, "added-mass sway-yaw signs");
        // a dorsal fin above the COM couples sway with roll: w = (e_y, r × e_y), (r × e_y)_x = −r_z < 0
        t.expect(at6(back.Dfin, 1, 3) < 0.0f, "sway-roll sign of a dorsal fin above the COM: %g", (double)at6(back.Dfin, 1, 3));
        Coefficients c;
        Support s;
        compileBody(neutralBody("neutral"), c, s);
        Loaded L;
        evalLoad(c, 0.0f, 0.0f, L);
        t.expect(at6(L.Dfin, 1, 5) > 0.0f, "the neutral body's net sway-yaw coupling is not the tail's");
        t.note("sway-yaw D: lone front dorsal %.4g, lone rear dorsal %.4g, neutral %.4g (m/u·u)", (double)at6(front.Dfin, 1, 5),
               (double)at6(back.Dfin, 1, 5), (double)at6(L.Dfin, 1, 5));
    }
    // zero-area fins contribute exactly zero
    {
        appearance::Genome G = appearance::neutral();
        for (int j : {11, 12, 16, 19, 23}) G.g[appearance::kMorphOffset + j] = 0.0f;
        Coefficients c;
        Support s;
        t.expect(compile(G, 1.0f, 1.0f, physical::neutral(), Params{}, c, s) == kOk, "noAppendages did not compile");
        bool zeroT = true;
        for (float x : c.dampD0) zeroT = zeroT && x == 0.0f;
        for (float x : c.dampD1) zeroT = zeroT && x == 0.0f;
        for (float x : c.dampD2) zeroT = zeroT && x == 0.0f;
        for (float x : c.addedA0) zeroT = zeroT && x == 0.0f;
        for (float x : c.addedA1) zeroT = zeroT && x == 0.0f;
        for (float x : c.addedA2) zeroT = zeroT && x == 0.0f;
        bool zeroA = c.caudalArea == 0.0f && c.finArea == 0.0f && c.finMass == 0.0f && c.propArea == 0.0f && c.rowSpeed == 0.0f;
        for (int q = 0; q < 4; ++q) zeroA = zeroA && c.pairedArea[q] == 0.0f && c.pairedAspect[q] == 0.0f;
        t.expect(zeroT && zeroA, "a fin without area contributed");
        t.expect(c.tailEfficiency == 0.35f && c.tailTau == 0.03f, "the absent caudal fin's efficiency / response");
        Loaded L;
        t.expect(evalLoad(c, 0.0f, 0.0f, L) && maxAbs(L.Dfin) == 0.0f && maxAbs(L.Afin) == 0.0f, "noAppendages: fin tensors not zero");
    }
}

inline void testHydroStage() {
    using namespace hyd;
    Test t("hydro_stage");
    const std::vector<Body> B = bodySet(12, 404u);
    long sweeps = 0, differ = 0, m2aMoved = 0;
    std::string first;
    for (const Body& b : B) {
        Coefficients c0;
        Support s0;
        Diagnostics d0;
        if (compileBody(b, c0, s0, &d0) != kOk) continue;
        // the inherited alleles are untouched; the expressed ones neutral
        t.expect(!std::memcmp(&d0.inherited, &b.P, sizeof b.P) && d0.expressed.g[physical::kGape] == 0.5f && d0.expressed.g[physical::kArmour] == 0.0f &&
                 d0.eyeGene[1] == 0.5f && d0.barbelGene[1] == 0.0f, "%s: the stage expression", b.name.c_str());
        bodyplan::BirthCoefficients m0;
        bodyplan::compile(b.G, b.S, b.E, b.P, bodyplan::kGeometryLaw, m0);
        for (int which = 0; which < 4; ++which)
            for (const float v : {0.0f, 0.13f, 0.5f, 0.87f, 1.0f}) {
                Body x = b;
                if (which == 0) x.P.g[physical::kGape] = v;
                else if (which == 1) x.P.g[physical::kArmour] = v;
                else if (which == 2) x.G.g[appearance::kMorphOffset + kEyeGene] = v;
                else x.G.g[appearance::kMorphOffset + kBarbelGene] = v;
                Coefficients c;
                Support s;
                ++sweeps;
                if (compileBody(x, c, s) != kOk || std::memcmp(&c, &c0, sizeof c) || std::memcmp(&s, &s0, sizeof s)) {
                    if (!differ++) first = b.name + " dormant " + std::to_string(which) + "=" + std::to_string(v);
                }
                // ... while geometry law 1's own (unmasked) development does move
                bodyplan::BirthCoefficients m;
                bodyplan::compile(x.G, x.S, x.E, x.P, bodyplan::kGeometryLaw, m);
                if (std::memcmp(&m, &m0, sizeof m)) ++m2aMoved;
            }
    }
    t.expect(differ == 0, "%ld of %ld dormant sweeps changed a record; first: %s", differ, sweeps, first.c_str());
    t.expect(m2aMoved > sweeps / 2, "the sweeps did not reach the unmasked development (%ld of %ld)", m2aMoved, sweeps);
    t.note("%ld dormant-allele sweeps (gape, armour, eye size, barbels): every coefficient and support record bit-identical, "
           "while %ld moved geometry law 1's unmasked development", sweeps, m2aMoved);
    // the organ cap: unmasked, a big gape shrinks the eyes (synthetic: law 1's develop); masked, gape is .5 whatever the allele
    {
        physical::Genes P = physical::neutral();
        P.g[physical::kGape] = 1.0f;
        const bodyplan::Expressed big = bodyplan::develop(10.0f, 30.0f, 0.5f, 4.6f, 1.0f, P);
        P.g[physical::kGape] = 0.5f;
        const bodyplan::Expressed mid = bodyplan::develop(10.0f, 30.0f, 0.5f, 4.6f, 1.0f, P);
        const physical::Genes masked = expressPhysical(physical::Genes{{1.0f, 0.5f, 1.0f, 0.4f, 0.5f}});
        const bodyplan::Expressed viaMask = bodyplan::develop(10.0f, 30.0f, 0.5f, 4.6f, 1.0f, masked);
        t.expect((big.limits & bodyplan::kLimitOrgans) && big.eyeScale < mid.eyeScale && !std::memcmp(&viaMask, &mid, sizeof mid) &&
                 viaMask.shell == 0.0f, "the organ-cap leak through gape is not closed by the expression");
    }
}

inline void testHydroRefs() {
    using namespace hyd;
    Test t("hydro_refs");
    const References& R = references();
    t.expect(R.ok == 1, "the reference block failed");
    t.expect(R.refVolume == bodyplan::referenceVolume() && R.rhoWater == 1.0f / R.refVolume, "Vref / ρw");
    Coefficients c;
    Support s;
    Diagnostics d;
    t.expect(compileBody(neutralBody("neutral"), c, s, &d) == kOk, "neutral");
    t.expect(c.leanRatio == 1.0f && c.muscleRatio == 1.0f && c.leanFactor == 1.0f, "the neutral ratios are not 1");
    t.expect(std::fabs(c.basalPower - 0.80f) <= 1e-6f, "neutral basal %.9g != .80", (double)c.basalPower);
    const float lipidUpkeep = kMaintLipid * (R.fuelMass / R.fuelMass);
    t.expect(std::fabs(c.maintenancePower + lipidUpkeep - 0.10f) <= 1e-6f, "maintenance at the reference load %.9g != .10",
             (double)(c.maintenancePower + lipidUpkeep));
    // white / red neutral-sized muscle: .68 / .92
    for (const float f : {0.0f, 1.0f}) {
        Body b = neutralBody("fibre");
        b.P.g[physical::kFibre] = f;
        Coefficients cf;
        Support sf;
        compileBody(b, cf, sf);
        t.expect(std::fabs(cf.basalPower - (f == 0.0f ? 0.68f : 0.92f)) <= 1e-6f, "fibre %g basal %.9g", (double)f, (double)cf.basalPower);
        t.expect(f == 1.0f ? cf.peakPower == cf.sustainedPower && cf.fatigueCapacity == 0.0f : cf.fatigueCapacity > 0.0f,
                 "fibre %g: the burst capacity", (double)f);
    }
    // κ = 1 is the linear law exactly
    {
        Body b = neutralBody("big");
        b.S = 1.5f;
        Params p1;
        p1.kleiber = 1.0f;
        Coefficients c1, c75;
        Support s1;
        compileBody(b, c1, s1, nullptr, p1);
        compileBody(b, c75, s1);
        t.expect(c1.leanFactor == c1.leanRatio && c75.leanFactor < c75.leanRatio && c75.leanFactor > 1.0f, "Kleiber κ");
    }
    // the brief's unloaded neutral checks (rounded measurements): Kx 15.42, Ky 139.78, Kz 162.88
    Loaded L0, Lr;
    evalLoad(c, 0.0f, 0.0f, L0);
    t.expect(rel(L0.K[0], 15.42, 15.42) < 0.005 && rel(L0.K[1], 139.78, 139.78) < 0.005 && rel(L0.K[2], 162.88, 162.88) < 0.005,
             "K %.6g %.6g %.6g vs the brief's 15.42 / 139.78 / 162.88", (double)L0.K[0], (double)L0.K[1], (double)L0.K[2]);
    t.expect(std::fabs(c.energyCapacity - 45.0f) < 0.5f, "Ecap %g (≈ 45)", (double)c.energyCapacity);
    t.expect(std::fabs(c.tailTau - 0.15f) <= 1e-7f, "neutral τtail %.9g", (double)c.tailTau);
    // the reference trim is neutrally buoyant: |M − ρw Vdisp| / M
    evalLoad(c, R.trimGas, R.fuelMass, Lr);
    const double buoy = std::fabs((double)Lr.mass - (double)R.rhoWater * Lr.displaced) / Lr.mass;
    t.expect(buoy <= 1e-5 && R.trimGas > 0.0f && R.trimGas < c.gasCapacity, "reference trim: buoyancy %.3g, gas %g of %g", buoy,
             (double)R.trimGas, (double)c.gasCapacity);
    t.expect(std::fabs(R.workConversion * R.cruisePower - kCruiseMotorShare) <= 1e-6f, "workConversion x P(82) != .60");
    t.expect(c.rowSpeed == R.rowSpeed && rel(c.sustainedPower, R.sustainedPower, R.sustainedPower) <= 1e-6 &&
             rel(c.peakPower, 2.0 * c.sustainedPower, c.peakPower) <= 1e-6, "neutral motor");
    float lo = kUsusRef, hi = 400.0f;
    for (int i = 0; i < 60; ++i) { const float mid = 0.5f * (lo + hi); if (R.pmotor(mid) < c.peakPower) lo = mid; else hi = mid; }
    t.expect(lo >= 130.0f && lo <= 150.0f, "neutral peak speed %g outside 130-150", (double)lo);
    t.note("refs: Vref %.9g, lean %.9g m, muscle %.9g u³, trim gas %.9g u³ at k %.9g, Dref %.9g, Urow %.9g u/s, ηtail %.9g, "
           "P(82) %.9g, P(108) %.9g, workConversion %.9g; peak (P = 2 Psus) %.4g u/s; digest %s",
           (double)R.refVolume, (double)R.leanMass, (double)R.muscleVolume, (double)R.trimGas, (double)R.trimInflation, (double)R.forwardDrag,
           (double)R.rowSpeed, (double)R.tailEfficiency, (double)R.cruisePower, (double)R.sustainedPower, (double)R.workConversion, (double)lo,
           hex64(digest(R)).c_str());
    t.note("neutral: K %.6g %.6g %.6g (unloaded), %.6g %.6g %.6g (reference load); mass %.9g; I %.6g %.6g %.6g; basal %.6g, maintenance %.6g + "
           "lipid; Ebuild %.6g E; Ecap %.6g E; e %.6g, ηtail %.6g, τtail %.6g",
           (double)L0.K[0], (double)L0.K[1], (double)L0.K[2], (double)Lr.K[0], (double)Lr.K[1], (double)Lr.K[2], (double)c.leanMass,
           (double)L0.inertia.m[0], (double)L0.inertia.m[1], (double)L0.inertia.m[2], (double)c.basalPower, (double)c.maintenancePower,
           (double)c.buildEnergy, (double)c.energyCapacity, (double)d.caudalLoading, (double)c.tailEfficiency, (double)c.tailTau);
    // the memory ceilings (resident, a fish): coefficients 1,024, support 256, state 96, genes 20, owner 8: 1,404 B
    const int total = (int)(sizeof(Coefficients) + sizeof(Support) + sizeof(HydroState) + sizeof(physical::Genes) + sizeof(std::uint64_t));
    t.expect(sizeof(Coefficients) <= 1024 && sizeof(Support) <= 256 && sizeof(HydroState) <= 96 && total <= 1404, "a ceiling is exceeded");
    t.note("resident a fish: coefficients %zu B + support %zu B + state %zu B + genes %zu B + owner 8 B = %d B (ceiling 1,404); "
           "%d fish: %.3f MB; cold diagnostics %zu B, rebuilt on demand",
           sizeof(Coefficients), sizeof(Support), sizeof(HydroState), sizeof(physical::Genes), total, 2000, total * 2000 / 1.0e6, sizeof(Diagnostics));
}

inline void testHydroRefuse() {
    using namespace hyd;
    Test t("hydro_refuse");
    auto allZero = [](const Coefficients& c, const Support& s) {
        for (int i = 0; i < kCoefficientFloats; ++i) if (floats(c)[i] != 0.0f) return false;
        for (int i = 0; i < kSupportFloats; ++i) if (floats(s)[i] != 0.0f) return false;
        return true;
    };
    struct Case { const char* what; Body b; Params p; int want; };
    std::vector<Case> cases;
    Body nb = neutralBody("neutral");
    cases.push_back({"size NaN", nb, Params{}, kErrGeometry}); cases.back().b.S = NAN;
    cases.push_back({"size 0", nb, Params{}, kErrGeometry}); cases.back().b.S = 0.0f;
    cases.push_back({"elong inf", nb, Params{}, kErrGeometry}); cases.back().b.E = INFINITY;
    cases.push_back({"shape gene 1.5", nb, Params{}, kErrGeometry}); cases.back().b.G.g[appearance::kMorphOffset + 3] = 1.5f;
    cases.push_back({"shape gene NaN", nb, Params{}, kErrGeometry}); cases.back().b.G.g[appearance::kMorphOffset + 0] = NAN;
    cases.push_back({"allele -0.1", nb, Params{}, kErrGeometry}); cases.back().b.P.g[physical::kFat] = -0.1f;
    cases.push_back({"allele NaN", nb, Params{}, kErrGeometry}); cases.back().b.P.g[physical::kFibre] = NAN;
    cases.push_back({"kleiber .3", nb, Params{}, kErrParams}); cases.back().p.kleiber = 0.3f;
    cases.push_back({"kleiber NaN", nb, Params{}, kErrParams}); cases.back().p.kleiber = NAN;
    cases.push_back({"basal -1", nb, Params{}, kErrParams}); cases.back().p.basalStructural = -1.0f;
    cases.push_back({"basal inf", nb, Params{}, kErrParams}); cases.back().p.basalMuscle = INFINITY;
    for (const Case& k : cases) {
        Coefficients c;
        Support s;
        Diagnostics d;
        std::memset(&c, 0x5A, sizeof c);
        std::memset(&s, 0x5A, sizeof s);
        const int e = compile(k.b.G, k.b.S, k.b.E, k.b.P, k.p, c, s, &d);
        t.expect(e == k.want && d.error == k.want && allZero(c, s), "%s: error %d (want %d), outputs %s", k.what, e, k.want,
                 allZero(c, s) ? "zero" : "NOT zero");
    }
    // a dormant allele out of its domain is still refused (validated before the expression masks it)
    {
        Body b = neutralBody("gape 2");
        b.P.g[physical::kGape] = 2.0f;
        Coefficients c;
        Support s;
        t.expect(compileBody(b, c, s) == kErrGeometry, "an out-of-domain dormant allele was accepted");
    }
    Loaded L;
    Coefficients c;
    Support s;
    compileBody(nb, c, s);
    t.expect(!evalLoad(c, -1.0f, 0.0f, L) && !evalLoad(c, 0.0f, NAN, L) && !evalLoad(c, INFINITY, 0.0f, L), "evalLoad accepted a bad load");
    t.expect(versionsSupported(1, 1, 1, 1) && !versionsSupported(2, 1, 1, 1) && !versionsSupported(1, 2, 1, 1) && !versionsSupported(1, 1, 0, 1) &&
             !versionsSupported(1, 1, 1, 2), "version support");
}

inline void testHydroState() {
    using namespace hyd;
    Test t("hydro_state");
    t.expect(sizeof(HydroState) == 76 && kStateFloats == 18, "the state layout");
    const HydroState s = restState(V3{100.0f, -120.0f, 50.0f}, V3{3.0f, 0.0f, -1.0f}, V3{0.6f, 0.0f, 0.8f});
    int words = 0;
    std::uint32_t last = 0;
    forEachStateWord(s, [&](std::uint32_t u) { ++words; last = u; });
    t.expect(words == 19 && last == kStatusCompiled, "the state's hash words (%d)", words);
    t.expect(std::fabs(qnorm2(poseOf(s)) - 1.0f) < 1e-6f && s.vGround[0] == 3.0f && s.vGround[2] == -1.0f && s.LWorld[0] == 0.0f &&
             s.gasContent == 0.0f && s.fatigue == 0.0f, "the rest state");
    V3 ex, ey, ez;
    columns(poseOf(s), ex, ey, ez);
    t.expect(std::fabs(ez.y - 1.0f) < 1e-6f && std::fabs(ex.x + 0.6f) < 1e-6f && std::fabs(ex.z + 0.8f) < 1e-6f, "the rest pose");
}

inline void testHydroNumbers() {
    using namespace hyd;
    Test t("hydro_numbers");
    const std::vector<Body> B = bodySet(40, 20261109u);
    Digest all;
    int ok = 0;
    for (const Body& b : B) {
        Coefficients c;
        Support s;
        Diagnostics d;
        const int e = compileBody(b, c, s, &d);
        if (e == kOk) ++ok;
        Loaded L;
        evalLoad(c, 0.5f * c.gasCapacity, 0.25f * c.reserveCapacity * (bodymat::kRhoLipid * rhoWater()), L);
        all.add((std::uint32_t)e);
        const std::uint64_t hc = digest(c), hs = digest(s);
        all.add((std::uint32_t)hc); all.add((std::uint32_t)(hc >> 32));
        all.add((std::uint32_t)hs); all.add((std::uint32_t)(hs >> 32));
        all.addf(L.mass); all.addf(L.com.x); all.addf(L.com.z);
        all.addFloats(L.inertia.m, 6);
        all.addFloats(L.Meff.m, 21);
        all.addFloats(L.Dfin.m, 21);
    }
    t.expect(ok == (int)B.size(), "%d of %zu compiled", ok, B.size());
    Coefficients c;
    Support s;
    compileBody(neutralBody("neutral"), c, s);
    t.note("%zu bodies: digest %s; neutral record %s, support %s; references %s", B.size(), hex64(all.h).c_str(), hex64(digest(c)).c_str(),
           hex64(digest(s)).c_str(), hex64(digest(references())).c_str());
}

}  // namespace ot

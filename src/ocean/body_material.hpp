#pragma once
// ----------------------------------------------------------------------------
// body_material — M2b's MATERIAL LAW 1 (separate from geometry law 1, which
// it reads and never changes): where a fish's materials sit inside and
// outside its canonical hull, as volume moments about the canonical origin.
// Pure, binary32, fixed order (the arithmetic contract of body_plan.hpp).
//
// THE PARTITION. The closed hull of geometry law 1 (body_plan.hpp: 15 rings x
// 8 around, the snout tip, the flat tail cap) is cut into kCells = 14 x 8
// fixed cells: band i (rings i -> i + 1; ring 0 is the snout tip) x sector k
// (around-index k -> k + 1, the hull's own rotation order), cell id 8i + k
// (THE STABLE CELL ORDER). Cell (i, k) is the solid bounded by the hull's own
// surface triangles of that quad, the two ring sections' sectors and the two
// "radial" faces from the spine axis (P = (x_i, 0, 0), Q = (x_{i+1}, 0, 0)),
// each radial quad split along its diagonal from P (so neighbouring cells
// share it exactly). Its volume and first / second moments are integrated by
// tetrahedra from P over the faces not containing P (the surface triangles
// and the far section's sector (Q, D, C)), then moved to the canonical
// origin exactly as a translation along x. The cells are a positive-volume
// partition of the hull (every cell positive: tests hydro_material); their
// sum equals the hull's integration to rounding (the totals below always use
// the hull's own moments).
//
// THE ALLOCATION (stage-expressed volumes, body_plan.hpp's development):
//   1. eyes   the right eye's half of the eye-organ volume, from the
//             right-half cells (k = 0..3) nearest the right eye's centre;
//             the left eye is its exact mirror image (same cells mirrored,
//             k -> 7 − k, same fractions; its moments the right eye's with y
//             negated): paired eyes are symmetric bit for bit
//   2. jaw    the jaw volume, nearest the mouth centre (ventral snout)
//   3. walls  the storage / bladder walls .02 (β + f) V (β, f the expressed
//             bladder and fat fractions), nearest the hull centroid
//   4. tissue the remainder: hull − eyes − jaw − walls
// "Nearest" = ascending squared distance from the organ's centre to the
// cell's (full) centroid, ties by cell id; an organ takes whole cells while
// they fit and a fraction of the next (the fractional final cell: the
// requested volume is preserved), always from what earlier organs left (a
// fraction of a cell's remaining moments: a proportional slice). Every
// allocation is non-negative. Shell (armour) material has no allocation in
// law 1: a compile with a non-zero expressed shell is refused (stage M2b1
// expresses armour as zero shell; its law comes with the stage of its
// benefit).
//
// EXPOSED FINS. Each fin's material is a lamina of its measured planform (the
// caudal's propulsive strips, not the buried collar; dorsal, anal, pectoral
// and pelvic strips) times its thickness estimate tfin (body_plan.hpp's
// clamp(.01R + .002 span²/(rootChord + .05R), .01R, .08R)): volume A·tfin,
// first and second moments the planform's (∫ r dA, ∫ r rᵀ dA by triangles)
// times tfin. Under the torso inflation k (T(k) = diag(1, k, k)) a fin keeps
// its planform (area, normal, shape) and translates rigidly with its roots:
// its point p(k) = p0 + (k − 1) b, with b the area-weighted mean over its
// triangles of the hull roots' (0, y, z) (dorsal / anal: (0, 0, z)), the
// roots from body_plan.hpp's restRoot. The caudal fin is not hull-rooted: b = 0.
//
// DENSITIES (ratios to water; the mass unit is the water mass of Vref):
// tissue, jaw and walls 1.04, eyes and fins 1.10, shell 2.0, lipid 0.90, gas
// negligible. Muscle is tissue: Vmuscle = .30 (the remaining tissue volume).
// ----------------------------------------------------------------------------
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include "body_plan.hpp"
#include "hydro_math.hpp"

namespace bodymat {

inline constexpr int kMaterialLaw = 1;
inline constexpr float kRhoTissue = 1.04f, kRhoFin = 1.10f, kRhoEye = 1.10f, kRhoShell = 2.00f, kRhoLipid = 0.90f;
inline constexpr float kMuscleFraction = 0.30f, kWallFraction = 0.02f;
inline constexpr int kBands = bodyplan::kRings - 1;     // 14
inline constexpr int kAround = bodyplan::kAround;       // 8
inline constexpr int kCells = kBands * kAround;         // 112
inline constexpr int mirrorCell(int c) { return (c / kAround) * kAround + (kAround - 1 - c % kAround); }

// Volume (or, scaled, mass) moments about the canonical origin:
// v = ∫ dV, f = ∫ r dV, s = ∫ r rᵀ dV (xx yy zz xy xz yz).
struct Moments {
    float v = 0.0f;
    float f[3] = {0.0f, 0.0f, 0.0f};
    float s[6] = {0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
};
inline void addTo(Moments& a, const Moments& b) {
    a.v = a.v + b.v;
    for (int i = 0; i < 3; ++i) a.f[i] = a.f[i] + b.f[i];
    for (int i = 0; i < 6; ++i) a.s[i] = a.s[i] + b.s[i];
}
inline Moments minus(const Moments& a, const Moments& b) {
    Moments o;
    o.v = a.v - b.v;
    for (int i = 0; i < 3; ++i) o.f[i] = a.f[i] - b.f[i];
    for (int i = 0; i < 6; ++i) o.s[i] = a.s[i] - b.s[i];
    return o;
}
inline Moments scaled(const Moments& a, float k) {
    Moments o;
    o.v = k * a.v;
    for (int i = 0; i < 3; ++i) o.f[i] = k * a.f[i];
    for (int i = 0; i < 6; ++i) o.s[i] = k * a.s[i];
    return o;
}
// The mirror image in the plane y = 0 (exact: negations only).
inline Moments mirrorY(const Moments& a) {
    Moments o = a;
    o.f[1] = -a.f[1];
    o.s[3] = -a.s[3];   // xy
    o.s[5] = -a.s[5];   // yz
    return o;
}

namespace detail {
using bodyplan::Vec3;
inline hydro::V3 h3(Vec3 p) { return {p.x, p.y, p.z}; }
// The tetrahedron (0, a, b, c)'s moments (body_plan.hpp hullMoments' formulas).
inline void addTet(Moments& m, hydro::V3 a, hydro::V3 b, hydro::V3 c) {
    const float det = hydro::dot(a, hydro::cross(b, c));
    m.v = m.v + det / 6.0f;
    const hydro::V3 s = hydro::add(hydro::add(a, b), c);
    m.f[0] = m.f[0] + det * s.x / 24.0f; m.f[1] = m.f[1] + det * s.y / 24.0f; m.f[2] = m.f[2] + det * s.z / 24.0f;
    const float w = det / 120.0f;
    m.s[0] = m.s[0] + w * (a.x * a.x + b.x * b.x + c.x * c.x + s.x * s.x);
    m.s[1] = m.s[1] + w * (a.y * a.y + b.y * b.y + c.y * c.y + s.y * s.y);
    m.s[2] = m.s[2] + w * (a.z * a.z + b.z * b.z + c.z * c.z + s.z * s.z);
    m.s[3] = m.s[3] + w * (a.x * a.y + b.x * b.y + c.x * c.y + s.x * s.y);
    m.s[4] = m.s[4] + w * (a.x * a.z + b.x * b.z + c.x * c.z + s.x * s.z);
    m.s[5] = m.s[5] + w * (a.y * a.z + b.y * b.z + c.y * c.z + s.y * s.z);
}
// Moments about (px, 0, 0) -> about the origin (a translation along x).
inline Moments shiftX(const Moments& m, float px) {
    Moments o = m;
    o.f[0] = m.f[0] + m.v * px;
    o.s[0] = (m.s[0] + (2.0f * px) * m.f[0]) + (m.v * px) * px;
    o.s[3] = m.s[3] + px * m.f[1];
    o.s[4] = m.s[4] + px * m.f[2];
    return o;
}
inline hydro::V3 ringPoint(const bodyplan::Points& P, int i, int k) {
    return i == 0 ? h3(P.p[bodyplan::kHullTip]) : h3(P.p[bodyplan::kHullRing0 + kAround * (i - 1) + (k % kAround)]);
}
// A lamina triangle's planform moments (area, ∫ r dA, ∫ r rᵀ dA), its area
// and centroid weight exactly as body_plan.hpp finFromTris forms them.
inline void addLamina(Moments& m, hydro::V3 a, hydro::V3 b, hydro::V3 c, float& areaOut) {
    const hydro::V3 n = hydro::cross(hydro::sub(b, a), hydro::sub(c, a));
    const float ar = 0.5f * std::sqrt(hydro::dot(n, n));
    areaOut = ar;
    const hydro::V3 s = hydro::add(hydro::add(a, b), c);
    m.v = m.v + ar;
    const float w3 = ar / 3.0f;
    m.f[0] = m.f[0] + s.x * w3; m.f[1] = m.f[1] + s.y * w3; m.f[2] = m.f[2] + s.z * w3;
    const float w = ar / 12.0f;
    m.s[0] = m.s[0] + w * (a.x * a.x + b.x * b.x + c.x * c.x + s.x * s.x);
    m.s[1] = m.s[1] + w * (a.y * a.y + b.y * b.y + c.y * c.y + s.y * s.y);
    m.s[2] = m.s[2] + w * (a.z * a.z + b.z * b.z + c.z * c.z + s.z * s.z);
    m.s[3] = m.s[3] + w * (a.x * a.y + b.x * b.y + c.x * c.y + s.x * s.y);
    m.s[4] = m.s[4] + w * (a.x * a.z + b.x * b.z + c.x * c.z + s.x * s.z);
    m.s[5] = m.s[5] + w * (a.y * a.z + b.y * b.z + c.y * c.z + s.y * s.z);
}
}  // namespace detail

// ---- the partition ------------------------------------------------------------------------
struct Cells { Moments c[kCells]; };
inline void cellMoments(const bodyplan::Points& P, Cells& out) {
    using namespace detail;
    for (int i = 0; i < kBands; ++i) {
        const float px = ringPoint(P, i, 0).x, qx = ringPoint(P, i + 1, 0).x;
        const hydro::V3 Pv{px, 0.0f, 0.0f}, Q{qx, 0.0f, 0.0f};
        for (int k = 0; k < kAround; ++k) {
            const hydro::V3 A = hydro::sub(ringPoint(P, i, k), Pv), B = hydro::sub(ringPoint(P, i, k + 1), Pv);
            const hydro::V3 C = hydro::sub(ringPoint(P, i + 1, k + 1), Pv), D = hydro::sub(ringPoint(P, i + 1, k), Pv);
            const hydro::V3 Ql = hydro::sub(Q, Pv);
            Moments m;
            if (i == 0) addTet(m, A, C, D);   // the snout fan (A = B = the tip = P: zero; kept for the form)
            else if (k < bodyplan::kHalfRing) { addTet(m, A, B, C); addTet(m, A, C, D); }   // right half: diagonal A - C
            else { addTet(m, A, B, D); addTet(m, B, C, D); }                                // left half: diagonal B - D
            addTet(m, Ql, D, C);   // the far section's sector
            out.c[kAround * i + k] = shiftX(m, px);
        }
    }
}

// ---- the allocation -----------------------------------------------------------------------
struct Allocation {
    Moments m;                 // the organ's volume moments
    float requested = 0.0f;    // its requested volume
    float shortfall = 0.0f;    // requested − allocated (0 unless the hull ran out: never for law 1's volumes)
    int cells = 0;             // cells touched
    int lastCell = -1;         // the fractional final cell (or the last whole one)
    float lastFraction = 0.0f; // the fraction of that cell's remaining volume taken
};
struct Taken { int cell; float fraction; };   // one step of an allocation (fraction of the remaining; 1 = all of it)
inline Allocation allocate(const Cells& full, Cells& remaining, float target, hydro::V3 centre, bool rightHalfOnly,
                           Taken* steps = nullptr, int* nSteps = nullptr) {
    Allocation a;
    a.requested = target;
    if (nSteps) *nSteps = 0;
    if (!(target > 0.0f)) return a;
    int order[kCells];
    float d2[kCells];
    int n = 0;
    for (int c = 0; c < kCells; ++c) {
        if (rightHalfOnly && (c % kAround) >= bodyplan::kHalfRing) continue;
        const Moments& m = full.c[c];
        const hydro::V3 cc{m.f[0] / m.v, m.f[1] / m.v, m.f[2] / m.v};
        const hydro::V3 d = hydro::sub(cc, centre);
        d2[c] = hydro::dot(d, d);
        order[n++] = c;
    }
    std::sort(order, order + n, [&](int x, int y) { return d2[x] < d2[y] || (d2[x] == d2[y] && x < y); });
    float need = target;
    for (int q = 0; q < n && need > 0.0f; ++q) {
        const int c = order[q];
        Moments& r = remaining.c[c];
        const float av = r.v;
        if (!(av > 0.0f)) continue;
        ++a.cells;
        a.lastCell = c;
        if (av <= need) {
            addTo(a.m, r);
            need = need - av;
            r = Moments{};
            a.lastFraction = 1.0f;
            if (steps) steps[(*nSteps)++] = Taken{c, 1.0f};
        } else {
            const float f = need / av;
            const Moments part = scaled(r, f);
            addTo(a.m, part);
            r = minus(r, part);
            need = 0.0f;
            a.lastFraction = f;
            if (steps) steps[(*nSteps)++] = Taken{c, f};
        }
    }
    a.shortfall = need > 0.0f ? need : 0.0f;
    return a;
}

// ---- a fish's material ---------------------------------------------------------------------
struct Material {
    Moments hull;                     // the hull's own integration (body_plan.hpp hullMoments)
    Moments tissue, jaw, eyes, walls; // eyes: both; tissue: the remainder
    Moments fin[bodyplan::kFinCount]; // exposed fin material (volume)
    hydro::V3 finBasis[bodyplan::kFinCount];   // each fin's point update basis b (u per unit k − 1)
    float muscleVolume = 0.0f;
    float jawTarget = 0.0f, eyeTarget = 0.0f, wallTarget = 0.0f;
    Allocation jawAlloc, eyeAlloc /* the right eye's */, wallAlloc;
    float cellVolumeSum = 0.0f;       // Σ cell volumes (vs hull.v)
    float minCellVolume = 0.0f;
};
// From a stage-expressed compile's coefficients and points (bodyplan::compile
// with pointsOut), its decoded morph and the expressed bladder and fat
// fractions. False when the expressed shell is not zero (no law-1 allocation)
// or an organ cannot be placed.
inline bool allocateMaterial(const bodyplan::BirthCoefficients& bc, const bodyplan::Morph& M, const bodyplan::Points& pts,
                             float bladderFraction, float fatFraction, Material& out) {
    using namespace detail;
    using bodyplan::at;
    const float* m = bc.m;
    out = Material{};
    if (m[at(bodyplan::fShellVolume)] != 0.0f) return false;
    {
        const bodyplan::HullMoments h = bodyplan::hullMoments(pts);
        out.hull.v = h.volume;
        for (int i = 0; i < 3; ++i) out.hull.f[i] = h.first[i];
        for (int i = 0; i < 6; ++i) out.hull.s[i] = h.second[i];
    }
    const float V = out.hull.v;
    Cells full, rem;
    cellMoments(pts, full);
    rem = full;
    out.minCellVolume = full.c[0].v;
    for (int c = 0; c < kCells; ++c) {
        out.cellVolumeSum = out.cellVolumeSum + full.c[c].v;
        out.minCellVolume = std::min(out.minCellVolume, full.c[c].v);
    }
    if (!(out.minCellVolume > 0.0f)) return false;
    // 1. eyes: the right eye from the right half, the left its mirror
    out.eyeTarget = m[at(bodyplan::fEyeOrganVolume)];
    {
        Taken steps[kCells];
        int ns = 0;
        const hydro::V3 eyeR = h3(pts.p[bodyplan::kEyeR0]);
        out.eyeAlloc = allocate(full, rem, 0.5f * out.eyeTarget, eyeR, true, steps, &ns);
        for (int q = 0; q < ns; ++q) {
            Moments& r = rem.c[mirrorCell(steps[q].cell)];
            if (steps[q].fraction == 1.0f) r = Moments{};
            else r = minus(r, scaled(r, steps[q].fraction));
        }
        out.eyes = out.eyeAlloc.m;
        addTo(out.eyes, mirrorY(out.eyeAlloc.m));
    }
    // 2. jaw, nearest the mouth centre
    out.jawTarget = m[at(bodyplan::fJawVolume)];
    out.jawAlloc = allocate(full, rem, out.jawTarget, hydro::v3(m + at(bodyplan::fMouthCentre)), false);
    out.jaw = out.jawAlloc.m;
    // 3. walls, nearest the hull centroid
    out.wallTarget = kWallFraction * (bladderFraction + fatFraction) * V;
    out.wallAlloc = allocate(full, rem, out.wallTarget, hydro::v3(m + at(bodyplan::fHullCentroid)), false);
    out.walls = out.wallAlloc.m;
    if (out.eyeAlloc.shortfall > 0.0f || out.jawAlloc.shortfall > 0.0f || out.wallAlloc.shortfall > 0.0f) return false;
    // 4. tissue: the remainder
    out.tissue = minus(minus(minus(out.hull, out.eyes), out.jaw), out.walls);
    out.muscleVolume = kMuscleFraction * out.tissue.v;
    // exposed fins: laminae x thickness, and their root bases
    {
        (void)M;
        const bodyplan::Tris& T = bodyplan::canonicalTris();
        // A strip vertex's root is the same column's root-row vertex (dorsal / anal q = 0,
        // paired r = 0): body_plan.hpp restRoot(...) x R, bit for bit (tests: hydro_material),
        // read from the points instead of re-evaluating the surface.
        auto rootBasis = [&](int sample, bool median) {
            const int base = sample < bodyplan::kAnal0 ? bodyplan::kDorsal0 : bodyplan::kAnal0 + ((sample - bodyplan::kAnal0) / bodyplan::kStripSamples) * bodyplan::kStripSamples;
            const Vec3 r = pts.p[base + 2 * ((sample - base) / 2)];
            return median ? hydro::V3{0.0f, 0.0f, r.z} : hydro::V3{0.0f, r.y, r.z};
        };
        auto finOf = [&](int fin, int firstTri, int nTris, bool caudal, bool median) {
            const float tf = m[bodyplan::finAt(fin, bodyplan::kFinThickness)];
            Moments lam;
            hydro::V3 B{0.0f, 0.0f, 0.0f};
            for (int k = firstTri; k < firstTri + nTris; ++k) {
                if (caudal && T.t[k].part != 1) continue;
                const hydro::V3 a = h3(pts.p[T.t[k].a]), b = h3(pts.p[T.t[k].b]), c = h3(pts.p[T.t[k].c]);
                float ar;
                addLamina(lam, a, b, c, ar);
                if (!caudal) {
                    const hydro::V3 rb = hydro::add(hydro::add(rootBasis(T.t[k].a, median), rootBasis(T.t[k].b, median)), rootBasis(T.t[k].c, median));
                    B = hydro::add(B, hydro::mul(rb, ar / 3.0f));
                }
            }
            out.fin[fin] = lam.v > 0.0f ? scaled(lam, tf) : Moments{};
            out.finBasis[fin] = lam.v > 0.0f && !caudal ? hydro::V3{B.x / lam.v, B.y / lam.v, B.z / lam.v} : hydro::V3{0.0f, 0.0f, 0.0f};
        };
        const int caud0 = bodyplan::kHullTris, nCaud = 2 * bodyplan::kCaudalIntervals * (bodyplan::kCaudalRows - 1);
        const int strip0 = caud0 + nCaud, nStrip = 2 * bodyplan::kFinIntervals;
        finOf(bodyplan::kFinCaudal, caud0, nCaud, true, true);
        finOf(bodyplan::kFinDorsal, strip0 + 0 * nStrip, nStrip, false, true);
        finOf(bodyplan::kFinAnal, strip0 + 1 * nStrip, nStrip, false, true);
        finOf(bodyplan::kFinPecR, strip0 + 2 * nStrip, nStrip, false, false);
        finOf(bodyplan::kFinPecL, strip0 + 3 * nStrip, nStrip, false, false);
        finOf(bodyplan::kFinPelR, strip0 + 4 * nStrip, nStrip, false, false);
        finOf(bodyplan::kFinPelL, strip0 + 5 * nStrip, nStrip, false, false);
    }
    return out.tissue.v > 0.0f;
}

// ---- parts and the parallel-axis assembly ---------------------------------------------------------
// A part: mass, centroid, central inertia (I = ∫ρ (|d|² 1 − d dᵀ)).
struct Part { float mass = 0.0f; hydro::V3 centroid{0.0f, 0.0f, 0.0f}; hydro::S3 inertia{{0, 0, 0, 0, 0, 0}}; };
// A part from volume moments at density ratio rho (mass = rho ρw v).
inline Part partOf(const Moments& vol, float rho, float rhoW) {
    Part p;
    if (!(vol.v > 0.0f)) return p;
    const float scale = rho * rhoW;
    p.mass = scale * vol.v;
    p.centroid = hydro::V3{vol.f[0] / vol.v, vol.f[1] / vol.v, vol.f[2] / vol.v};
    const hydro::V3 c = p.centroid;
    // central second moment (mass units): scale (s − v c cᵀ)
    const hydro::S3 C{{scale * (vol.s[0] - vol.v * c.x * c.x), scale * (vol.s[1] - vol.v * c.y * c.y), scale * (vol.s[2] - vol.v * c.z * c.z),
                       scale * (vol.s[3] - vol.v * c.x * c.y), scale * (vol.s[4] - vol.v * c.x * c.z), scale * (vol.s[5] - vol.v * c.y * c.z)}};
    p.inertia = hydro::inertiaOf(C);
    return p;
}
// The brief's assembly, in the parts' order:
//   M = Σ m_i,  c = Σ(m_i c_i) / M,  I = Σ [I_i + m_i (|d_i|² 1 − d_i d_iᵀ)],  d_i = c_i − c
inline void assemble(const Part* parts, int n, float& M, hydro::V3& c, hydro::S3& I) {
    M = 0.0f;
    hydro::V3 mc{0.0f, 0.0f, 0.0f};
    for (int i = 0; i < n; ++i) {
        if (!(parts[i].mass > 0.0f)) continue;
        M = M + parts[i].mass;
        mc = hydro::add(mc, hydro::mul(parts[i].centroid, parts[i].mass));
    }
    c = M > 0.0f ? hydro::V3{mc.x / M, mc.y / M, mc.z / M} : hydro::V3{0.0f, 0.0f, 0.0f};
    I = hydro::S3{{0, 0, 0, 0, 0, 0}};
    for (int i = 0; i < n; ++i) {
        if (!(parts[i].mass > 0.0f)) continue;
        const hydro::V3 d = hydro::sub(parts[i].centroid, c);
        const float m = parts[i].mass, d2 = hydro::dot(d, d);
        const float* Ii = parts[i].inertia.m;
        I.m[0] = I.m[0] + (Ii[0] + m * (d2 - d.x * d.x));
        I.m[1] = I.m[1] + (Ii[1] + m * (d2 - d.y * d.y));
        I.m[2] = I.m[2] + (Ii[2] + m * (d2 - d.z * d.z));
        I.m[3] = I.m[3] + (Ii[3] - m * (d.x * d.y));
        I.m[4] = I.m[4] + (Ii[4] - m * (d.x * d.z));
        I.m[5] = I.m[5] + (Ii[5] - m * (d.y * d.z));
    }
}

}  // namespace bodymat

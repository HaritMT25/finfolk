#pragma once
// ----------------------------------------------------------------------------
// body_plan — M2a's authoritative CPU body plan (geometry law 1): a PURE
// decoder / compiler from a fish's 63 appearance floats (appearance_model.hpp:
// its 30 M1 shape genes), its bodySize S and bodyElong E and its five
// physical alleles (physical_genome.hpp) to its canonical rest geometry and
// the measured quantities M2b's mechanics will need. No world, no rng, no
// state: the same inputs give the same bits, native and wasm (binary32, fixed
// order, -ffp-contract=off, evomath's portable expf / logf / sinf / cosf /
// atan2f; IEEE + − × ÷ and sqrt are correctly rounded everywhere).
//
// DIAGNOSTIC ONLY in M2a: nothing the step computes reads it (ocean_world.hpp
// compiles it at birth while OceanConfig::bodyPlanPreviewEnabled is on, into a
// side array the harness hashes outside the simulation's sections).
//
// THE LAW. The live renderer's rest surface (web/ocean_appearance.js
// morphDecode / mHalfAxes / mSurf / mFacet / morphBuild; the GLSL MORPH it
// mirrors), ported operation by operation into binary32, at the renderer's
// rest settings (time 0, no tail wag or barbel sway, no screen-width floor,
// no fin fold, no LOD), with the M2 reference scales
//     L = 20·S·E,  R = 4.6·S,  lambda = L / R
// (NOT the M1-only radius curve, appearance_eval.hpp lambdaOf). Geometry is
// built in body radii (the renderer's units) and scaled by R into world
// units, so doubling S scales every coordinate by exactly 2: volumes x8,
// areas x4, inertia x32, bit for bit. Preserved from the renderer: the
// caudal chord cap (3 R), the eye's clip to the local head, roots attached to
// the faceted body (mFacet on the canonical rings), absent appendages (zero
// area), the continuous barbel activation.
//
// CANONICAL SAMPLING (frozen with the law; kSamples points, sampleCoords):
//   hull      the full LOD's 15 rings x 8 around (4 a half; the top and
//             bottom samples shared by the two halves), the snout tip
//             (t = −.20, radius 0) and the tail cap's centre (t = 1)
//   caudal    12 eta intervals x rows {collar −1, 0, .5, 1}; the collar (the
//             buried strip into the peduncle) is drawn but not propulsive
//   dorsal, anal, each pectoral and pelvic: 16 chord intervals x {root, tip}
//   eyes      centre + 16 rim directions each
//   barbels   3 pairs x 2 sides x 2 ribbons x 6 segments x 2 edges
// The renderer's full template uses other fin counts (9 / 9 / 7) and four rim
// points: the comparison with the GPU (web/ocean_scene_parity.js
// bodyPlanVertexCheck) evaluates both laws at THESE coordinates, never at
// shared index buffers.
//
// THE INTEGRATION MESH is NOT the renderer's index buffer (its two mirrored
// halves share one triangle order, so their signed volumes cancel). It is a
// closed, consistently outward-wound polyhedron over the hull samples: ring
// samples in rotation order about +x (right half bottom -> top, then the left
// half top -> bottom), a fan from the snout tip, quads between rings, a fan to
// the tail cap; 224 triangles in a fixed order. Volume, centroid, first and
// second moments come from its origin tetrahedra (a·(b×c)/6 each); wetted
// area and the silhouettes (½Σ|n·axis|A) from its triangles; the frontal
// area Af is the largest ring section (shoelace).
//
// DEVELOPMENT (expressed values; the alleles stay as inherited). With V the
// fish's unloaded hull volume and Vref the neutral body's at S = E = 1:
//   gape      gapeFraction = H(g; .15, .40, .65); gapeDiameter = fraction x
//             2 min(half-width, half-depth) at t = −.10, the ventral snout
//             (the mouth centre, θ = −π/2); jaw volume .02 V (fraction/.40)³
//   eyes      kE = min(eye decode, the renderer's head clip); eye organ
//             volume (M2a's provisional law) two ellipsoids of semi-axes
//             (.24, .14, .14) kE R; jaw + eyes <= .25 V, else both linear
//             scales shrink by one cube-root factor (organScale)
//   storage   gas capacity .15 g V; reserve .02 V + .20 g V; the two trait
//             parts together <= .28 V (the whole <= .30 V), else both
//             scale by one factor (storageScale); energy capacity
//             500 x .90 x reserve / Vref
//   armour    shell thickness .06 g x the smaller half-axis at the shoulder
//             (t = .20); shell volume ~ wetted area x thickness (inside the
//             hull) <= .08 V, else the thickness shrinks (shellScale)
//   fibre     expressed as inherited
// An explicitly labelled UNLOADED MATERIAL ESTIMATE (not M2b's mass law,
// which still has to fix organ thickness and spatial allocation): tissue
// 1.04 x (V − shell), armour 2.0 x shell, fin 1.10 x Σ area x tfin with
// tfin = clamp(.01R + .002 span²/(rootChord + .05R), .01R, .08R), over Vref.
// M2b's own rule (design v2 §2.5): the eye, barbel, armour and gape COSTS
// stay neutral until the stage of their benefit. M2a only measures.
//
// An explicit diagnostic LOAD (gas and fuel as fractions of their
// capacities; the fixture viewer) inflates the torso transversely by
// k = sqrt(1 + (Vgas + Vfuel)/V) (the spine's law), roots reattached; birth
// coefficients are always unloaded (k = 1, and then no multiplication at all).
// ----------------------------------------------------------------------------
#include <cmath>
#include <cstdint>
#include <cstring>
#include "../core/portable_math.hpp"
#include "physical_genome.hpp"   // (and appearance_model.hpp)

namespace bodyplan {

inline constexpr int kGeometryLaw = 1;
inline constexpr int kMetricsAbi = 1;

// ---- the coefficient layout (metrics ABI 1): name, count, units, meaning -------
// Units: u (world), u2, u3, u5 (inertia, density 1), R (body radii), E
// (energy), m (mass normalised by the neutral body's: water = 1 per Vref),
// "" dimensionless, "bits" a small bit set. Body frame: x forward along the
// spine (the snout at −x... the renderer's frame: x = lambda·warp(t)·R grows
// toward the TAIL), y to the fish's side (+1 = its right as the renderer
// lays it out), z up (dorsal).
#define BODYPLAN_FIELDS(X)                                                                                         \
    X(fLaw, 1, "", "geometry law version")                                                                         \
    X(fSize, 1, "", "bodySize S")                                                                                  \
    X(fElong, 1, "", "bodyElong E")                                                                                \
    X(fRefLength, 1, "u", "L = 20 S E (the reference length; also skin friction's, recorded for M2b)")            \
    X(fRefRadius, 1, "u", "R = 4.6 S")                                                                             \
    X(fLambda, 1, "", "lambda = L / R")                                                                            \
    X(fInflation, 1, "", "torso inflation k of this compile (1 = unloaded, the birth coefficients)")              \
    X(fRefVolume, 1, "u3", "Vref: the neutral body's hull volume at S = E = 1 (the normalisation)")                \
    X(fHullVolume, 1, "u3", "closed hull volume V")                                                                \
    X(fHullVolumeNorm, 1, "", "V / Vref")                                                                          \
    X(fHullCentroid, 3, "u", "hull centroid (x, y, z)")                                                            \
    X(fHullInertia, 6, "u5", "hull inertia about its centroid, density 1: Ixx Iyy Izz Ixy Ixz Iyz (I = ∫(r²δ − r rᵀ))") \
    X(fWettedArea, 1, "u2", "hull wetted area")                                                                    \
    X(fFrontalArea, 1, "u2", "Af: the largest ring section")                                                       \
    X(fFrontalProjected, 1, "u2", "½Σ|n·x|A over the hull")                                                        \
    X(fSideArea, 1, "u2", "lateral silhouette ½Σ|n·y|A")                                                           \
    X(fPlanArea, 1, "u2", "plan silhouette ½Σ|n·z|A")                                                              \
    X(fForeAft, 1, "", "B = Σ(area·nx²) / Sw")                                                                     \
    X(fHullLength, 1, "u", "measured hull length (snout tip to tail cap)")                                         \
    X(fFineness, 1, "", "hull length / sqrt(4 Af / π)")                                                            \
    X(fMaxHalfWidth, 1, "u", "largest hull half-width")                                                            \
    X(fMaxHalfDepth, 1, "u", "largest hull half-depth")                                                            \
    X(fHullBounds, 6, "u", "hull min x, max x, min y, max y, min z, max z")                                        \
    X(fAllBounds, 6, "u", "hull + fins + eyes + barbels bounds")                                                   \
    X(fTotalLength, 1, "u", "all-parts x extent (with the caudal fin)")                                            \
    X(fFins, 98, "", "7 fins x 14 (kFin*: caudal, dorsal, anal, pectoral R / L, pelvic R / L)")                    \
    X(fCaudalNominalArea, 1, "u2", "the caudal genes' nominal area cA R²")                                         \
    X(fCaudalNominalAR, 1, "", "the caudal genes' nominal aspect ratio")                                           \
    X(fCaudalActualAR, 1, "", "span² / measured area, after the chord cap")                                        \
    X(fCaudalChord, 1, "R", "the caudal chord scale cx (capped at 3)")                                             \
    X(fGapeFraction, 1, "", "expressed gape fraction")                                                             \
    X(fGapeDiameter, 1, "u", "mouth aperture diameter")                                                            \
    X(fMouthCentre, 3, "u", "mouth centre (ventral snout, t = −.10)")                                              \
    X(fMouthHalfAxes, 2, "u", "local head half-width, half-depth at t = −.10")                                     \
    X(fEyeScale, 1, "", "expressed eye scale kE")                                                                  \
    X(fEyeScaleLaw, 1, "", "kE before the organ bound (decode, head clip)")                                        \
    X(fEyeCentre, 3, "u", "right eye centre")                                                                      \
    X(fEyeArea, 1, "u2", "one eye's measured disc area")                                                           \
    X(fJawVolume, 1, "u3", "jaw volume .02 V (fraction / .40)³")                                                   \
    X(fEyeOrganVolume, 1, "u3", "both eyes' organ volume (provisional ellipsoid law)")                             \
    X(fBladderCapacity, 1, "u3", "maximum gas volume")                                                             \
    X(fReserveCapacity, 1, "u3", "reserve (lipid) volume capacity")                                                \
    X(fReserveEnergy, 1, "E", "energy capacity 500 x .90 x reserve / Vref")                                        \
    X(fArmourThickness, 1, "u", "shell thickness")                                                                 \
    X(fShellVolume, 1, "u3", "shell volume (inside the hull)")                                                     \
    X(fMuscleFibre, 1, "", "expressed muscle fibre")                                                               \
    X(fStorageScale, 1, "", "storage bound factor (1 = not bound)")                                                \
    X(fOrganScale, 1, "", "organ bound factor (1 = not bound)")                                                    \
    X(fShellScale, 1, "", "shell cap factor (1 = not capped)")                                                     \
    X(fLimits, 1, "bits", "1 eye clipped, 2 caudal chord capped, 4 storage bound, 8 organ bound, 16 shell capped") \
    X(fBarbelActivation, 3, "", "barbel pair activations")                                                         \
    X(fBarbelReach, 3, "u", "barbel pair reach (one barbel's arc length)")                                         \
    X(fBarbelArea, 3, "u2", "barbel pair ribbon area (both sides, both ribbons)")                                  \
    X(fFinVolume, 1, "u3", "ESTIMATE: Σ fin area x tfin")                                                          \
    X(fUnloadedMassEstimate, 1, "m", "ESTIMATE: (1.04 tissue + 2.0 shell + 1.10 fin volume) / Vref, unloaded")     \
    X(fRingX, 15, "u", "support cache: ring x positions")                                                          \
    X(fRingA, 15, "u", "support cache: ring half-widths")                                                          \
    X(fRingB, 15, "u", "support cache: ring half-depths")                                                          \
    X(fSectionExponent, 1, "", "support cache: the section's superellipse exponent 2/n")

#define BODYPLAN_ENUM(name, count, units, what) name,
enum Field : int { BODYPLAN_FIELDS(BODYPLAN_ENUM) kFieldCount };
#undef BODYPLAN_ENUM
struct FieldInfo { const char* name; int count; const char* units; const char* what; };
#define BODYPLAN_INFO(name, count, units, what) {#name, count, units, what},
inline constexpr FieldInfo kFields[kFieldCount] = {BODYPLAN_FIELDS(BODYPLAN_INFO)};
#undef BODYPLAN_INFO
constexpr int at(int field) {
    int o = 0;
    for (int i = 0; i < field; ++i) o += kFields[i].count;
    return o;
}
inline constexpr int kMetrics = at(kFieldCount);

// One fin's 14 values (inside fFins: at(fFins) + 14·fin + k).
enum Fin : int { kFinCaudal = 0, kFinDorsal, kFinAnal, kFinPecR, kFinPecL, kFinPelR, kFinPelL, kFinCount };
enum FinValue : int {
    kFinArea = 0, kFinNormal = 1, kFinCentroid = 4, kFinLever = 7, kFinSpan = 10, kFinRootChord = 11,
    kFinMeanChord = 12, kFinThickness = 13, kFinStride = 14
};
inline constexpr const char* kFinNames[kFinCount] = {"caudal", "dorsal", "anal", "pectoralR", "pectoralL", "pelvicR", "pelvicL"};
static_assert(kFields[fFins].count == (int)kFinCount * (int)kFinStride, "fFins holds 7 fins x 14 values");
inline constexpr int finAt(int fin, int k) { return at(fFins) + kFinStride * fin + k; }

enum Limit : int { kLimitEyeClip = 1, kLimitChordCap = 2, kLimitStorage = 4, kLimitOrgans = 8, kLimitShell = 16 };

// The birth coefficients: floats only (no padding by construction), the
// layout above. Expressed development, geometry, moments and the support
// cache; never the alleles, never moving state.
struct BirthCoefficients {
    float m[kMetrics];
};
static_assert(sizeof(BirthCoefficients) == sizeof(float) * kMetrics, "coefficients are kMetrics packed floats");

// ---- canonical sampling ---------------------------------------------------------
inline constexpr int kRings = 15;
inline constexpr float kRingT[kRings] = {-0.20f, -0.16f, -0.10f, -0.03f, 0.04f, 0.12f, 0.20f, 0.31f,
                                         0.42f,  0.53f,  0.64f,  0.74f,  0.84f, 0.92f, 1.0f};
inline constexpr int kHalfRing = 4, kAround = 8;
inline constexpr int kCaudalIntervals = 12, kCaudalRows = 4;   // rows: collar −1, 0, .5, 1
inline constexpr int kFinIntervals = 16;
inline constexpr int kEyeRim = 16;
inline constexpr int kBarbelSegments = 6;

// Sample index ranges (the order sampleCoords lays them out in).
inline constexpr int kHullTip = 0;
inline constexpr int kHullRing0 = 1;                                     // ring i (1..14), k: 1 + 8(i − 1) + k
inline constexpr int kHullCap = kHullRing0 + (kRings - 1) * kAround;     // 113
inline constexpr int kHullSamples = kHullCap + 1;                        // 114
inline constexpr int kCaudal0 = kHullSamples;                            // column j, row r: + 4j + r
inline constexpr int kStripSamples = (kFinIntervals + 1) * 2;            // 34: column q, row r: + 2q + r
inline constexpr int kDorsal0 = kCaudal0 + (kCaudalIntervals + 1) * kCaudalRows;   // 166
inline constexpr int kAnal0 = kDorsal0 + kStripSamples;                  // 200
inline constexpr int kPecR0 = kAnal0 + kStripSamples;                    // 234
inline constexpr int kPecL0 = kPecR0 + kStripSamples;
inline constexpr int kPelR0 = kPecL0 + kStripSamples;
inline constexpr int kPelL0 = kPelR0 + kStripSamples;
inline constexpr int kEyeR0 = kPelL0 + kStripSamples;                    // 370: centre, then the rim
inline constexpr int kEyeL0 = kEyeR0 + 1 + kEyeRim;
inline constexpr int kBarbel0 = kEyeL0 + 1 + kEyeRim;                    // 404
inline constexpr int kBarbelRibbon = (kBarbelSegments + 1) * 2;          // 14: point i, edge e: + 2i + e
inline constexpr int kSamples = kBarbel0 + 3 * 2 * 2 * kBarbelRibbon;    // 572
inline constexpr int barbelRibbon0(int pair, int sideIndex, int rib) { return kBarbel0 + ((pair * 2 + sideIndex) * 2 + rib) * kBarbelRibbon; }

// One canonical sample: the renderer's template attributes (aT, and aPattern's
// part / side), as float32.
struct Sample { float a[4]; int fin; float side; };
struct Vec3 { float x, y, z; };

// ---- the law, in binary32 -------------------------------------------------------
namespace detail {
inline constexpr float kPi = 3.14159265358979323846f;
inline constexpr float kCaudI[5] = {0.6740740741f, 0.2912962963f, 1.8648148148f, 1.5130584482f, 1.0648148148f};
inline constexpr float kPhiI = 0.6620370370f;
inline constexpr float kPecTheta = -0.30f, kPelTheta = -1.20f, kEyeT = 0.03f, kEyeTh = 0.43f, kChordCap = 3.0f;
inline constexpr float kPU[8] = {-0.20f, -0.10f, 0.04f, 0.20f, 0.42f, 0.64f, 0.84f, 1.00f};
inline constexpr float kPY[8] = {0.0f, 0.50f, 0.88f, 1.00f, 0.86f, 0.60f, 0.36f, 0.20f};
inline constexpr float kPH[8] = {0.0f, 0.42f, 0.74f, 0.84f, 0.72f, 0.52f, 0.33f, 0.20f};

inline float clampf(float x, float a, float b) { return x < a ? a : (x > b ? b : x); }
inline float minf(float a, float b) { return a < b ? a : b; }
inline float maxf(float a, float b) { return a > b ? a : b; }
inline float absf(float x) { return x < 0.0f ? -x : x; }
inline float signf(float x) { return x > 0.0f ? 1.0f : (x < 0.0f ? -1.0f : 0.0f); }
inline float sqrtf_(float x) { return std::sqrt(x); }   // correctly rounded (IEEE)
inline float powf_(float x, float p) { return evomath::expf(p * evomath::logf(x)); }   // x > 0
inline float cbrtf_(float x) { return x > 0.0f ? powf_(x, 1.0f / 3.0f) : 0.0f; }
inline float asinf_(float x) { return evomath::atan2f(x, sqrtf_((1.0f - x) * (1.0f + x))); }
inline float pS(float a, float b, float x) {
    const float t = clampf((x - a) / (b - a), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}
inline float mH(float g, float a, float b, float c) { return b + (2.0f * g - 1.0f) * (g < 0.5f ? b - a : c - b); }
inline float mPw(float x, float p) { return x > 0.0f ? powf_(x, p) : 0.0f; }
inline float mSc(float c, float e) {
    const float a = absf(c);
    return a > 0.0f ? signf(c) * powf_(a, e) : 0.0f;
}
inline float profile(float u, const float* tbl) {
    if (u <= kPU[0]) return tbl[0];
    for (int i = 1; i < 8; ++i)
        if (u < kPU[i]) return tbl[i - 1] + (tbl[i] - tbl[i - 1]) * (u - kPU[i - 1]) / (kPU[i] - kPU[i - 1]);
    return tbl[7];
}
inline float caudLEk(int k, float a) { return k < 2 ? a * a : 0.2f * a * a; }
inline float caudTEk(int k, float a) {
    if (k == 0) return 0.35f + 0.65f * a;
    if (k == 1) return 0.22f + 0.78f * a * a;
    if (k == 2) return 1.0f;
    if (k == 3) return 0.25f + 0.75f * sqrtf_(maxf(0.0f, 1.0f - a * a));
    return 0.20f + 0.80f * (1.0f - a);
}
template <class F>
inline float caudMix(F f, float o, float a) {
    int k = (int)std::floor(o * 4.0f);
    if (k > 3) k = 3;
    const float w = pS(0.0f, 1.0f, o * 4.0f - (float)k);
    const float x = f(k, a), y = f(k + 1, a);
    return x + (y - x) * w;
}
inline float caudLE(float o, float a) { return caudMix(caudLEk, o, a); }
inline float caudTE(float o, float a) { return caudMix(caudTEk, o, a); }
inline float caudI(float o) { return caudMix([](int k, float) { return kCaudI[k]; }, o, 0.0f); }
inline Vec3 add(Vec3 a, Vec3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
inline Vec3 sub(Vec3 a, Vec3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
inline Vec3 mul(Vec3 a, float s) { return {a.x * s, a.y * s, a.z * s}; }
inline Vec3 cross(Vec3 a, Vec3 b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
inline float dot(Vec3 a, Vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
inline float norm(Vec3 a) { return sqrtf_(dot(a, a)); }
}  // namespace detail

// The decoded body plan (mDecode), in body radii.
struct Morph {
    float depth, width, n, fexp, sh, hbulk, sn, nexp, ped;
    float outline, AR, cA, span, cx;
    float dH, dL, dS, dSplit, aH, aL, aS;
    float pA, pT, pSweep, pDih, vA, vT, vSweep;
    float bD, bReach, bBeta, eye, lam;
    float inflate = 1.0f;     // torso inflation k (1: the renderer's law exactly)
    float eyeScale = 1.0f;    // the organ bound's factor on kE (1: the renderer's law)
};

// mDecode of genes 33..62 of a 63-float appearance row, at lambda.
inline Morph decodeMorph(const float* g, float lam) {
    using namespace detail;
    auto mg = [&](int j) { return g[appearance::kMorphOffset + j]; };
    Morph M;
    M.depth = mH(mg(0), 0.22f, 1.0f, 2.40f); M.width = mH(mg(1), 0.18f, 1.0f, 1.90f);
    M.n = 1.0f + 2.0f * mg(2); M.fexp = mH(mg(3), 0.55f, 1.0f, 1.60f);
    M.sh = 0.08f + 0.24f * mg(4); M.hbulk = mH(mg(5), 0.60f, 1.0f, 1.60f);
    M.sn = mH(mg(6), 0.08f, 0.20f, 0.40f); M.nexp = mH(mg(7), 1.80f, 1.0f, 0.40f);
    M.ped = mH(mg(8), 0.45f, 1.0f, 1.70f); M.outline = mg(9);
    M.AR = mH(mg(10), 0.50f, 2.80f, 8.0f); M.cA = mH(mg(11), 0.0f, 1.20f, 3.20f);
    M.span = M.cA > 1e-6f ? sqrtf_(M.AR * M.cA) : 0.0f;
    M.cx = M.cA > 1e-6f ? minf(kChordCap, 2.0f * M.cA / (M.span * caudI(M.outline))) : 0.0f;
    M.dH = 1.60f * mg(12); M.dL = 0.10f + 0.60f * mg(13); M.dS = mg(14); M.dSplit = mg(15);
    M.aH = 1.20f * mg(16); M.aL = 0.10f + 0.45f * mg(17); M.aS = mg(18);
    M.pA = mH(mg(19), 0.0f, 0.45f, 1.20f); M.pT = 0.06f + 0.28f * mg(20);
    M.pSweep = mH(mg(21), -0.25f, 0.50f, 1.25f); M.pDih = (-70.0f + 110.0f * mg(22)) * (kPi / 180.0f);
    M.vA = mH(mg(23), 0.0f, 0.20f, 0.90f); M.vT = 0.20f + 0.40f * mg(24); M.vSweep = mH(mg(25), 0.0f, 0.50f, 1.0f);
    M.bD = mg(26); M.bReach = mH(mg(27), 0.10f, 1.20f, 3.0f); M.bBeta = mg(28); M.eye = mH(mg(29), 0.40f, 1.0f, 1.80f);
    M.lam = lam;
    return M;
}

inline float warp(const Morph& M, float t) {
    return t <= 0.2f ? -M.sn + (t + 0.2f) / 0.4f * (M.sh + M.sn) : M.sh + (t - 0.2f) / 0.8f * (1.0f - M.sh);
}
inline float invWarp(const Morph& M, float u) {
    return u <= M.sh ? -0.2f + 0.4f * (u + M.sn) / (M.sh + M.sn) : 0.2f + 0.8f * (u - M.sh) / (1.0f - M.sh);
}
// The half-axes (width, depth) at t, in body radii.
inline void halfAxes(const Morph& M, float t, float& a, float& b) {
    using namespace detail;
    const float headMask = 1.0f - pS(0.04f, 0.30f, t), noseMask = 1.0f - pS(-0.16f, 0.04f, t), rearMask = pS(0.65f, 1.0f, t);
    const float p = M.fexp * (1.0f + (M.nexp - 1.0f) * noseMask);
    const float sc = (1.0f + (M.hbulk - 1.0f) * headMask) * (1.0f + (M.ped - 1.0f) * rearMask);
    a = M.width * mPw(profile(t, kPY), p) * sc;
    b = M.depth * 0.84f * mPw(profile(t, kPH) / 0.84f, p) * sc;
    if (M.inflate != 1.0f) { a = a * M.inflate; b = b * M.inflate; }
}
inline Vec3 surf(const Morph& M, float t, float th, float side) {
    using namespace detail;
    float a, b;
    halfAxes(M, t, a, b);
    const float e = 2.0f / M.n;
    return {M.lam * warp(M, t), side * a * mSc(maxf(evomath::cosf(th), 0.0f), e), b * mSc(evomath::sinf(th), e)};
}
// mFacet on the canonical (full) rings, 4 samples a half.
inline Vec3 facet(const Morph& M, float t, float th, float side) {
    using namespace detail;
    int i = 0;
    for (int k = 1; k < kRings; ++k)
        if (t >= kRingT[k]) i = k;
    if (i > kRings - 2) i = kRings - 2;
    const float t0 = kRingT[i], t1 = kRingT[i + 1];
    const float al = clampf((t - t0) / (t1 - t0), 0.0f, 1.0f);
    const float stp = kPi / (float)kHalfRing, q = (th + 0.5f * kPi) / stp;
    const float k0 = clampf(std::floor(q), 0.0f, (float)kHalfRing - 1.0f), be = clampf(q - k0, 0.0f, 1.0f);
    const float th0 = -0.5f * kPi + k0 * stp, th1 = th0 + stp;
    const Vec3 P10 = surf(M, t1, th0, side), P11 = surf(M, t1, th1, side);
    if (i == 0) {
        const Vec3 P0 = surf(M, t0, 0.0f, side);
        return add(P0, mul(sub(add(P10, mul(sub(P11, P10), be)), P0), al));
    }
    const Vec3 P00 = surf(M, t0, th0, side), P01 = surf(M, t0, th1, side);
    return al >= be ? add(add(P00, mul(sub(P10, P00), al)), mul(sub(P11, P10), be))
                    : add(add(P00, mul(sub(P01, P00), be)), mul(sub(P11, P01), al));
}
inline float finH(float H, float split, float s) {
    return H * 4.0f * s * (1.0f - s) * (1.0f - split * (1.0f - detail::pS(0.08f, 0.20f, detail::absf(s - 0.5f))));
}
// The eye's scale kE at the renderer's law (decode and head clip), and as expressed.
inline float eyeScaleLaw(const Morph& M) {
    float a, b;
    halfAxes(M, detail::kEyeT, a, b);
    return detail::minf(M.eye, 0.32f * b / 0.14f);
}

// mBuild at rest (time 0, no wag, no width floor): one template vertex's
// rest position, in body radii.
inline Vec3 restVertex(const Morph& M, const float* a, int fin, float side) {
    using namespace detail;
    if (fin == 0) {
        const Vec3 p = surf(M, a[0], a[1], side);
        return {p.x, a[2] * p.y, a[2] * p.z};
    }
    if (fin == 1) {
        const float eta = a[0], row = a[1], ae = absf(eta);
        const float LE = caudLE(M.outline, ae), TE = caudTE(M.outline, ae), r = clampf(row, 0.0f, 1.0f);
        float x = M.cx * (LE + r * (TE - LE));
        const float z = 0.5f * M.span * eta;
        float a1, B1;
        halfAxes(M, 1.0f, a1, B1);
        const float xLE = M.cx * LE;
        if (row < -0.5f) {
            const float wc = 1.0f - pS(0.75f * B1, B1, absf(z));
            x = xLE + wc * (-0.12f - xLE);
        }
        return {M.lam + x, 0.0f, z};
    }
    if (fin == 2 || fin == 5) {
        const float s = a[0], q = a[1];
        const bool dors = fin == 2;
        const float up = dors ? 1.0f : -1.0f;
        const float ell = dors ? M.dL : M.aL, H = dors ? M.dH : M.aH;
        const float start = 0.04f + (0.92f - ell) * (dors ? M.dS : M.aS), split = dors ? M.dSplit : 0.0f;
        const float t = start + ell * s;
        const Vec3 root = facet(M, t, up * 0.5f * kPi, 1.0f);
        const float ht = finH(H, split, s);
        return {root.x, 0.0f, root.z + up * q * ht};
    }
    if (fin == 3 || fin == 6) {
        const float s = a[0], r = a[1];
        const bool pec = fin == 3;
        const float chord = pec ? 0.80f : 0.55f, area = pec ? M.pA : M.vA, tc = pec ? M.pT : M.vT;
        const float sweep = pec ? M.pSweep : M.vSweep, dih = pec ? M.pDih : -0.25f * kPi, thr = pec ? kPecTheta : kPelTheta;
        const float span = area / (chord * kPhiI);
        const float X = M.lam * warp(M, tc) + chord * (s - 0.5f);
        const float t = invWarp(M, X / M.lam);
        const Vec3 root = facet(M, t, thr, side);
        const float phi = 4.0f * s * (1.0f - s), w = span * r * phi;
        return add(root, Vec3{sweep * w, side * w * evomath::cosf(dih), w * evomath::sinf(dih)});
    }
    if (fin == 4) {
        const float kE = eyeScaleLaw(M) * M.eyeScale;
        const Vec3 c = surf(M, kEyeT, kEyeTh, side);
        const float X = c.x + a[0] * 0.24f * kE, Z = c.z + a[1] * 0.14f * kE;
        const float t = invWarp(M, X / M.lam);
        float ha, hb;
        halfAxes(M, t, ha, hb);
        const float sn = signf(Z) * mPw(minf(1.0f, absf(Z) / maxf(hb, 1e-6f)), 0.5f * M.n);
        const Vec3 p = surf(M, t, asinf_(clampf(sn, -1.0f, 1.0f)), side);
        return {p.x, side * (absf(p.y) + 0.04f + 0.05f * ha), p.z};
    }
    // fin 7: a barbel ribbon (aT = q, edge, pair j, ribbon)
    const float q = a[0], ws = a[1], j = a[2], rib = a[3];
    const float d = maxf(0.0f, (M.bD - 0.2f) / 0.8f), wj = pS(0.0f, 1.0f, 3.0f * d - j);
    const float tj = -0.16f + 0.18f * M.bBeta + 0.015f * j, thj = -kPi * (0.06f + 0.25f * M.bBeta + 0.055f * j);
    const Vec3 P0 = facet(M, tj, thj, 1.0f);
    const float L = M.bReach * (1.0f - 0.15f * j) * wj;
    const Vec3 P1 = add(P0, mul(Vec3{-0.30f, 0.40f, -0.20f}, L)), P2 = add(P0, mul(Vec3{0.25f, 0.70f, -0.55f}, L));
    const Vec3 C = add(add(mul(P0, (1.0f - q) * (1.0f - q)), mul(P1, 2.0f * q * (1.0f - q))), mul(P2, q * q));
    Vec3 T = add(mul(sub(P1, P0), 2.0f * (1.0f - q)), mul(sub(P2, P1), 2.0f * q));
    const float tl = norm(T);
    T = tl > 1e-9f ? mul(T, 1.0f / tl) : Vec3{1.0f, 0.0f, 0.0f};
    Vec3 n1{T.y, -T.x, 0.0f};
    const float nl = sqrtf_(n1.x * n1.x + n1.y * n1.y);
    n1 = nl > 1e-6f ? mul(n1, 1.0f / nl) : Vec3{0.0f, 1.0f, 0.0f};
    const Vec3 n2 = cross(T, n1);
    const float hw = wj > 0.0f ? maxf(0.04f * (1.0f - 0.6f * q) * minf(1.0f, 4.0f * wj), 0.0f) : 0.0f;
    Vec3 geo = add(C, mul(rib < 0.5f ? n1 : n2, ws * hw));
    geo.y = geo.y * side;
    return geo;
}

// ---- the canonical samples (frozen with the law) ---------------------------------
struct Samples { Sample s[kSamples]; };
inline const Samples& sampleCoords() {
    static const Samples S = [] {
        Samples o{};
        auto put = [&](int i, float a0, float a1, float a2, float a3, int fin, float side) {
            o.s[i] = Sample{{a0, a1, a2, a3}, fin, side};
        };
        const double PI = 3.141592653589793;
        // hull: tip, rings (right half bottom -> top, then the left half top -> bottom), cap
        put(kHullTip, kRingT[0], 0.0f, 0.0f, 0.0f, 0, 1.0f);
        for (int i = 1; i < kRings; ++i)
            for (int k = 0; k < kAround; ++k) {
                const int h = k <= kHalfRing ? k : kAround - k;   // the half-ring sample: 0 bottom .. 4 top
                const float th = (float)(-0.5 * PI + h * (PI / kHalfRing));
                put(kHullRing0 + kAround * (i - 1) + k, kRingT[i], th, 1.0f, 0.0f, 0, k <= kHalfRing ? 1.0f : -1.0f);
            }
        put(kHullCap, kRingT[kRings - 1], 0.0f, 0.0f, 0.0f, 0, 1.0f);
        static const float kRows[kCaudalRows] = {-1.0f, 0.0f, 0.5f, 1.0f};
        for (int j = 0; j <= kCaudalIntervals; ++j)
            for (int r = 0; r < kCaudalRows; ++r)
                put(kCaudal0 + kCaudalRows * j + r, (float)(-1.0 + 2.0 * j / kCaudalIntervals), kRows[r], 0.0f, 0.0f, 1, 1.0f);
        auto strip = [&](int base, int fin, float side) {
            for (int q = 0; q <= kFinIntervals; ++q)
                for (int r = 0; r < 2; ++r)
                    put(base + 2 * q + r, (float)q / (float)kFinIntervals, (float)r, fin == 3 || fin == 6 ? side : 0.0f, 0.0f, fin, side);
        };
        strip(kDorsal0, 2, 1.0f);
        strip(kAnal0, 5, 1.0f);
        strip(kPecR0, 3, 1.0f);
        strip(kPecL0, 3, -1.0f);
        strip(kPelR0, 6, 1.0f);
        strip(kPelL0, 6, -1.0f);
        for (int e = 0; e < 2; ++e) {
            const int base = e ? kEyeL0 : kEyeR0;
            const float sd = e ? -1.0f : 1.0f;
            put(base, 0.0f, 0.0f, sd, 0.0f, 4, sd);
            for (int k = 0; k < kEyeRim; ++k) {
                const double ph = 2.0 * PI * k / kEyeRim;
                put(base + 1 + k, (float)std::cos(ph), (float)std::sin(ph), sd, 0.0f, 4, sd);
            }
        }
        for (int j = 0; j < 3; ++j)
            for (int si = 0; si < 2; ++si)
                for (int rib = 0; rib < 2; ++rib)
                    for (int i = 0; i <= kBarbelSegments; ++i)
                        for (int e = 0; e < 2; ++e)
                            put(barbelRibbon0(j, si, rib) + 2 * i + e, (float)i / (float)kBarbelSegments, e ? 1.0f : -1.0f,
                                (float)j, (float)rib, 7, si ? -1.0f : 1.0f);
        return o;
    }();
    return S;
}
// (cos / sin of the rim's 16 directions in std::cos / std::sin: k·π/8 are
// exact in every libm we build with to well within the float rounding, and
// the table is only ever rounded to float; tests pin its bits.)

// ---- the canonical triangles (drawing and fin integration) -----------------------
// Parts: 0 hull, 1 caudal (propulsive), 2 dorsal, 3 pectoral, 4 eye, 5 anal,
// 6 pelvic, 7 barbel, 8 the caudal's buried collar.
struct Tri { std::uint16_t a, b, c; std::uint8_t part; };
inline constexpr int kHullTris = 2 * kAround * (kRings - 2) + 2 * kAround;   // 224
inline constexpr int kTris = kHullTris + 2 * kCaudalIntervals * (kCaudalRows - 1) + 6 * 2 * kFinIntervals + 2 * kEyeRim +
                             12 * 2 * kBarbelSegments;   // 224 + 72 + 192 + 32 + 144 = 664
struct Tris { Tri t[kTris]; int n = 0; };
inline const Tris& canonicalTris() {
    static const Tris T = [] {
        Tris o{};
        auto tri = [&](int a, int b, int c, int part) { o.t[o.n++] = Tri{(std::uint16_t)a, (std::uint16_t)b, (std::uint16_t)c, (std::uint8_t)part}; };
        auto ring = [](int i, int k) { return kHullRing0 + kAround * (i - 1) + (k % kAround); };
        // the closed hull, outward: the snout fan, the bands, the tail fan
        for (int k = 0; k < kAround; ++k) tri(kHullTip, ring(1, k + 1), ring(1, k), 0);
        for (int i = 1; i + 1 < kRings; ++i)
            for (int k = 0; k < kAround; ++k) {
                tri(ring(i, k), ring(i, k + 1), ring(i + 1, k + 1), 0);
                tri(ring(i, k), ring(i + 1, k + 1), ring(i + 1, k), 0);
            }
        for (int k = 0; k < kAround; ++k) tri(kHullCap, ring(kRings - 1, k), ring(kRings - 1, k + 1), 0);
        // the caudal fin (the renderer's quad order): the collar strip, then the two propulsive strips
        for (int j = 0; j < kCaudalIntervals; ++j)
            for (int r = 0; r + 1 < kCaudalRows; ++r) {
                const int c0 = kCaudal0 + kCaudalRows * j, c1 = c0 + kCaudalRows, part = r == 0 ? 8 : 1;
                tri(c0 + r, c1 + r, c1 + r + 1, part);
                tri(c0 + r, c1 + r + 1, c0 + r + 1, part);
            }
        auto strip = [&](int base, int part) {
            for (int q = 0; q < kFinIntervals; ++q) {
                const int c0 = base + 2 * q, c1 = c0 + 2;
                tri(c0, c1, c1 + 1, part);
                tri(c0, c1 + 1, c0 + 1, part);
            }
        };
        strip(kDorsal0, 2); strip(kAnal0, 5);
        strip(kPecR0, 3); strip(kPecL0, 3); strip(kPelR0, 6); strip(kPelL0, 6);
        for (int e = 0; e < 2; ++e) {
            const int base = e ? kEyeL0 : kEyeR0;
            for (int k = 0; k < kEyeRim; ++k) tri(base, base + 1 + k, base + 1 + (k + 1) % kEyeRim, 4);
        }
        for (int j = 0; j < 3; ++j)
            for (int si = 0; si < 2; ++si)
                for (int rib = 0; rib < 2; ++rib) {
                    const int b0 = barbelRibbon0(j, si, rib);
                    for (int i = 0; i < kBarbelSegments; ++i) {
                        const int c0 = b0 + 2 * i, c1 = c0 + 2;
                        tri(c0, c1, c1 + 1, 7);
                        tri(c0, c1 + 1, c0 + 1, 7);
                    }
                }
        return o;
    }();
    return T;
}

// Every canonical sample's rest position in world units (body radii x R).
struct Points { Vec3 p[kSamples]; };
inline void restPoints(const Morph& M, float R, Points& out) {
    const Samples& S = sampleCoords();
    for (int i = 0; i < kSamples; ++i) {
        const Vec3 g = restVertex(M, S.s[i].a, S.s[i].fin, S.s[i].side);
        out.p[i] = Vec3{g.x * R, g.y * R, g.z * R};
    }
}

// ---- integration ---------------------------------------------------------------------
struct HullMoments {
    float volume = 0, first[3] = {0, 0, 0}, second[6] = {0, 0, 0, 0, 0, 0};   // ∫ x_i x_j: xx yy zz xy xz yz
    float wetted = 0, projX = 0, projY = 0, projZ = 0, foreAft = 0;
};
inline HullMoments hullMoments(const Points& P) {
    using namespace detail;
    const Tris& T = canonicalTris();
    HullMoments h;
    float sx = 0, sy = 0, sz = 0, nb = 0;
    for (int k = 0; k < kHullTris; ++k) {
        const Vec3 a = P.p[T.t[k].a], b = P.p[T.t[k].b], c = P.p[T.t[k].c];
        const float det = dot(a, cross(b, c));
        h.volume += det / 6.0f;
        const Vec3 s = add(add(a, b), c);
        h.first[0] += det * s.x / 24.0f; h.first[1] += det * s.y / 24.0f; h.first[2] += det * s.z / 24.0f;
        const float w = det / 120.0f;
        h.second[0] += w * (a.x * a.x + b.x * b.x + c.x * c.x + s.x * s.x);
        h.second[1] += w * (a.y * a.y + b.y * b.y + c.y * c.y + s.y * s.y);
        h.second[2] += w * (a.z * a.z + b.z * b.z + c.z * c.z + s.z * s.z);
        h.second[3] += w * (a.x * a.y + b.x * b.y + c.x * c.y + s.x * s.y);
        h.second[4] += w * (a.x * a.z + b.x * b.z + c.x * c.z + s.x * s.z);
        h.second[5] += w * (a.y * a.z + b.y * b.z + c.y * c.z + s.y * s.z);
        const Vec3 n = cross(sub(b, a), sub(c, a));
        const float nl = norm(n);
        h.wetted += 0.5f * nl;
        sx += absf(n.x); sy += absf(n.y); sz += absf(n.z);
        if (nl > 0.0f) nb += 0.5f * n.x * n.x / nl;
    }
    h.projX = 0.25f * sx; h.projY = 0.25f * sy; h.projZ = 0.25f * sz;   // ½ Σ |n·axis| (½|cross|)
    h.foreAft = h.wetted > 0.0f ? nb / h.wetted : 0.0f;
    return h;
}

// A fin's planform from its strip of canonical triangles.
struct FinMetrics { float area = 0, normal[3] = {0, 0, 0}, centroid[3] = {0, 0, 0}, span = 0, rootChord = 0; };
inline FinMetrics finFromTris(const Points& P, int firstTri, int nTris) {
    using namespace detail;
    const Tris& T = canonicalTris();
    FinMetrics f;
    Vec3 N{0, 0, 0}, C{0, 0, 0};
    for (int k = firstTri; k < firstTri + nTris; ++k) {
        const Vec3 a = P.p[T.t[k].a], b = P.p[T.t[k].b], c = P.p[T.t[k].c];
        const Vec3 n = cross(sub(b, a), sub(c, a));
        const float ar = 0.5f * norm(n);
        f.area += ar;
        N = add(N, mul(n, 0.5f));
        C = add(C, mul(add(add(a, b), c), ar / 3.0f));
    }
    const float nl = norm(N);
    if (f.area > 0.0f && nl > 0.0f) {
        f.normal[0] = N.x / nl; f.normal[1] = N.y / nl; f.normal[2] = N.z / nl;
        f.centroid[0] = C.x / f.area; f.centroid[1] = C.y / f.area; f.centroid[2] = C.z / f.area;
    }
    return f;
}

// ---- the reference volume and the compile -----------------------------------------
namespace detail {
inline float hullVolumeOf(const appearance::Genome& G, float S, float E) {
    const float L = 20.0f * S * E, R = 4.6f * S;
    const Morph M = decodeMorph(G.g, L / R);
    Points P;
    restPoints(M, R, P);
    return hullMoments(P).volume;
}
}  // namespace detail
// Vref: the neutral appearance genome's hull at S = E = 1 (law 1).
inline float referenceVolume() {
    static const float V = detail::hullVolumeOf(appearance::neutral(), 1.0f, 1.0f);
    return V;
}

// A diagnostic load: gas and fuel as fractions of their capacities, in [0, 1].
struct Load { float gas = 0.0f, fuel = 0.0f; };

// Everything a compile measured, the coefficients plus (optional) the points.
// Returns false for an unknown law or non-finite inputs (out left zero).
inline bool compile(const appearance::Genome& G, float S, float E, const physical::Genes& P, int law,
                    BirthCoefficients& out, const Load* load = nullptr, Points* pointsOut = nullptr) {
    using namespace detail;
    std::memset(&out, 0, sizeof out);
    if (law != kGeometryLaw) return false;
    if (!(S > 0.0f && E > 0.0f && std::isfinite(S) && std::isfinite(E))) return false;
    float* m = out.m;
    const float L = 20.0f * S * E, R = 4.6f * S, lam = L / R;
    const float Vref = referenceVolume();
    Morph M = decodeMorph(G.g, lam);
    Points pts;
    restPoints(M, R, pts);
    HullMoments h = hullMoments(pts);
    const float V = h.volume;     // the unloaded hull: every capacity is defined on it
    float shoulderA, shoulderB;
    halfAxes(M, 0.20f, shoulderA, shoulderB);

    // ---- development (expressed values) ----
    int limits = 0;
    const float kELaw = eyeScaleLaw(M);
    if (kELaw < M.eye) limits |= kLimitEyeClip;
    float gapeFr = mH(P.g[physical::kGape], 0.15f, 0.40f, 0.65f);
    const float gr = gapeFr / 0.40f;
    const float jaw0 = 0.02f * V * (gr * gr * gr);
    const float kR = kELaw * R;
    const float eyes0 = 2.0f * (4.0f / 3.0f) * kPi * (0.24f * kR) * (0.14f * kR) * (0.14f * kR);
    float organScale = 1.0f;
    if (jaw0 + eyes0 > 0.25f * V) { organScale = cbrtf_(0.25f * V / (jaw0 + eyes0)); limits |= kLimitOrgans; }
    float jaw = jaw0, eyes = eyes0, kE = kELaw;
    if (organScale != 1.0f) {
        gapeFr = gapeFr * organScale;
        kE = kELaw * organScale;
        const float s3 = organScale * organScale * organScale;
        jaw = jaw0 * s3; eyes = eyes0 * s3;
        M.eyeScale = organScale;
        restPoints(M, R, pts);   // the eyes at their expressed scale (the hull is unchanged)
    }
    float gas = 0.15f * P.g[physical::kBladder] * V, fat = 0.20f * P.g[physical::kFat] * V;
    float storageScale = 1.0f;
    if (gas + fat > 0.28f * V) { storageScale = 0.28f * V / (gas + fat); gas = gas * storageScale; fat = fat * storageScale; limits |= kLimitStorage; }
    const float reserve = 0.02f * V + fat;
    float th = 0.06f * P.g[physical::kArmour] * minf(shoulderA, shoulderB) * R;
    float shell = h.wetted * th, shellScale = 1.0f;
    if (shell > 0.08f * V) { shellScale = 0.08f * V / shell; th = th * shellScale; shell = h.wetted * th; limits |= kLimitShell; }
    if (M.cA > 1e-6f && 2.0f * M.cA / (M.span * caudI(M.outline)) > kChordCap) limits |= kLimitChordCap;

    // ---- an explicit diagnostic load: the inflated geometry (never at birth) ----
    float k = 1.0f;
    if (load && (load->gas != 0.0f || load->fuel != 0.0f)) {
        const float lg = clampf(load->gas, 0.0f, 1.0f), lf = clampf(load->fuel, 0.0f, 1.0f);
        k = sqrtf_(1.0f + (lg * gas + lf * reserve) / V);
        M.inflate = k;
        restPoints(M, R, pts);
        h = hullMoments(pts);
    }

    // ---- header, hull ----
    m[at(fLaw)] = (float)kGeometryLaw; m[at(fSize)] = S; m[at(fElong)] = E;
    m[at(fRefLength)] = L; m[at(fRefRadius)] = R; m[at(fLambda)] = lam; m[at(fInflation)] = k; m[at(fRefVolume)] = Vref;
    m[at(fHullVolume)] = h.volume;
    m[at(fHullVolumeNorm)] = h.volume / Vref;
    const float cx = h.first[0] / h.volume, cy = h.first[1] / h.volume, cz = h.first[2] / h.volume;
    m[at(fHullCentroid) + 0] = cx; m[at(fHullCentroid) + 1] = cy; m[at(fHullCentroid) + 2] = cz;
    {   // central second moments, then I = tr(C) δ − C
        const float Cxx = h.second[0] - h.volume * cx * cx, Cyy = h.second[1] - h.volume * cy * cy, Czz = h.second[2] - h.volume * cz * cz;
        const float Cxy = h.second[3] - h.volume * cx * cy, Cxz = h.second[4] - h.volume * cx * cz, Cyz = h.second[5] - h.volume * cy * cz;
        float* I = m + at(fHullInertia);
        I[0] = Cyy + Czz; I[1] = Cxx + Czz; I[2] = Cxx + Cyy; I[3] = -Cxy; I[4] = -Cxz; I[5] = -Cyz;
    }
    m[at(fWettedArea)] = h.wetted;
    m[at(fFrontalProjected)] = h.projX; m[at(fSideArea)] = h.projY; m[at(fPlanArea)] = h.projZ;
    m[at(fForeAft)] = h.foreAft;
    float maxSec = 0.0f, maxA = 0.0f, maxB = 0.0f;
    for (int i = 1; i < kRings; ++i) {   // ring sections (shoelace, rotation order: positive)
        float s2 = 0.0f;
        for (int q = 0; q < kAround; ++q) {
            const Vec3 a = pts.p[kHullRing0 + kAround * (i - 1) + q], b = pts.p[kHullRing0 + kAround * (i - 1) + (q + 1) % kAround];
            s2 += a.y * b.z - a.z * b.y;
            maxA = maxf(maxA, absf(a.y)); maxB = maxf(maxB, absf(a.z));
        }
        maxSec = maxf(maxSec, 0.5f * s2);
    }
    m[at(fFrontalArea)] = maxSec;
    m[at(fMaxHalfWidth)] = maxA; m[at(fMaxHalfDepth)] = maxB;
    auto bounds = [&](int lo, int hi, float* b6) {
        b6[0] = b6[2] = b6[4] = INFINITY; b6[1] = b6[3] = b6[5] = -INFINITY;
        for (int i = lo; i < hi; ++i) {
            const Vec3 p = pts.p[i];
            b6[0] = minf(b6[0], p.x); b6[1] = maxf(b6[1], p.x);
            b6[2] = minf(b6[2], p.y); b6[3] = maxf(b6[3], p.y);
            b6[4] = minf(b6[4], p.z); b6[5] = maxf(b6[5], p.z);
        }
    };
    bounds(0, kHullSamples, m + at(fHullBounds));
    bounds(0, kSamples, m + at(fAllBounds));
    m[at(fHullLength)] = m[at(fHullBounds) + 1] - m[at(fHullBounds) + 0];
    m[at(fTotalLength)] = m[at(fAllBounds) + 1] - m[at(fAllBounds) + 0];
    m[at(fFineness)] = maxSec > 0.0f ? m[at(fHullLength)] / sqrtf_(4.0f * maxSec / kPi) : 0.0f;

    // ---- fins (triangle ranges of canonicalTris) ----
    float finVolume = 0.0f;
    auto putFin = [&](int fin, const FinMetrics& f, float span, float rootChord, bool median) {
        float* o = m + finAt(fin, 0);
        o[kFinArea] = f.area;
        float sgn = 1.0f;   // orientation: median fins +y, paired fins +z
        if (median ? f.normal[1] < 0.0f : f.normal[2] < 0.0f) sgn = -1.0f;
        for (int c = 0; c < 3; ++c) {
            o[kFinNormal + c] = f.area > 0.0f ? sgn * f.normal[c] : 0.0f;
            o[kFinCentroid + c] = f.centroid[c];
        }
        o[kFinLever + 0] = f.area > 0.0f ? f.centroid[0] - cx : 0.0f;
        o[kFinLever + 1] = f.area > 0.0f ? f.centroid[1] - cy : 0.0f;
        o[kFinLever + 2] = f.area > 0.0f ? f.centroid[2] - cz : 0.0f;
        o[kFinSpan] = span;
        o[kFinRootChord] = rootChord;
        o[kFinMeanChord] = span > 0.0f ? f.area / span : 0.0f;
        const float tf = f.area > 0.0f ? clampf(0.01f * R + 0.002f * span * span / (rootChord + 0.05f * R), 0.01f * R, 0.08f * R) : 0.0f;
        o[kFinThickness] = tf;
        finVolume += f.area * tf;
    };
    {   // caudal: the propulsive strips only (rows 0 .. 1), not the collar
        const Tris& T = canonicalTris();
        FinMetrics f;
        Vec3 N{0, 0, 0}, C{0, 0, 0};
        for (int k2 = kHullTris; k2 < kHullTris + 2 * kCaudalIntervals * (kCaudalRows - 1); ++k2) {
            if (T.t[k2].part != 1) continue;
            const Vec3 a = pts.p[T.t[k2].a], b = pts.p[T.t[k2].b], c = pts.p[T.t[k2].c];
            const Vec3 n = cross(sub(b, a), sub(c, a));
            const float ar = 0.5f * norm(n);
            f.area += ar;
            N = add(N, mul(n, 0.5f));
            C = add(C, mul(add(add(a, b), c), ar / 3.0f));
        }
        const float nl = norm(N);
        if (f.area > 0.0f && nl > 0.0f) {
            f.normal[0] = N.x / nl; f.normal[1] = N.y / nl; f.normal[2] = N.z / nl;
            f.centroid[0] = C.x / f.area; f.centroid[1] = C.y / f.area; f.centroid[2] = C.z / f.area;
        }
        float zlo = INFINITY, zhi = -INFINITY;
        for (int j = 0; j <= kCaudalIntervals; ++j)
            for (int r = 1; r < kCaudalRows; ++r) { const float z = pts.p[kCaudal0 + kCaudalRows * j + r].z; zlo = minf(zlo, z); zhi = maxf(zhi, z); }
        const int mid = kCaudal0 + kCaudalRows * (kCaudalIntervals / 2);   // eta = 0
        const float span = f.area > 0.0f ? zhi - zlo : 0.0f;
        putFin(kFinCaudal, f, span, pts.p[mid + 3].x - pts.p[mid + 1].x, true);
        m[at(fCaudalNominalArea)] = M.cA * R * R;
        m[at(fCaudalNominalAR)] = M.cA > 1e-6f ? M.AR : 0.0f;
        m[at(fCaudalActualAR)] = f.area > 0.0f ? span * span / f.area : 0.0f;
        m[at(fCaudalChord)] = M.cx;
    }
    const int strip0 = kHullTris + 2 * kCaudalIntervals * (kCaudalRows - 1);   // the first strip's first triangle
    auto stripFin = [&](int fin, int which, int base, bool median, float up) {
        const FinMetrics f = finFromTris(pts, strip0 + which * 2 * kFinIntervals, 2 * kFinIntervals);
        float span = 0.0f;
        for (int q = 0; q <= kFinIntervals; ++q) {
            const Vec3 root = pts.p[base + 2 * q], tip = pts.p[base + 2 * q + 1];
            span = maxf(span, median ? up * (tip.z - root.z) : norm(sub(tip, root)));
        }
        if (!(f.area > 0.0f)) span = 0.0f;
        putFin(fin, f, span, norm(sub(pts.p[base + 2 * kFinIntervals], pts.p[base])), median);
    };
    stripFin(kFinDorsal, 0, kDorsal0, true, 1.0f);
    stripFin(kFinAnal, 1, kAnal0, true, -1.0f);
    stripFin(kFinPecR, 2, kPecR0, false, 0.0f);
    stripFin(kFinPecL, 3, kPecL0, false, 0.0f);
    stripFin(kFinPelR, 4, kPelR0, false, 0.0f);
    stripFin(kFinPelL, 5, kPelL0, false, 0.0f);

    // ---- mouth, eyes, barbels ----
    {
        float ha, hb;
        halfAxes(M, -0.10f, ha, hb);
        const Vec3 mc = surf(M, -0.10f, -0.5f * kPi, 1.0f);
        m[at(fGapeFraction)] = gapeFr;
        m[at(fGapeDiameter)] = gapeFr * 2.0f * minf(ha, hb) * R;
        m[at(fMouthCentre) + 0] = mc.x * R; m[at(fMouthCentre) + 1] = mc.y * R; m[at(fMouthCentre) + 2] = mc.z * R;
        m[at(fMouthHalfAxes) + 0] = ha * R; m[at(fMouthHalfAxes) + 1] = hb * R;
    }
    m[at(fEyeScale)] = kE; m[at(fEyeScaleLaw)] = kELaw;
    m[at(fEyeCentre) + 0] = pts.p[kEyeR0].x; m[at(fEyeCentre) + 1] = pts.p[kEyeR0].y; m[at(fEyeCentre) + 2] = pts.p[kEyeR0].z;
    m[at(fEyeArea)] = finFromTris(pts, strip0 + 6 * 2 * kFinIntervals, kEyeRim).area;
    {
        const int barb0 = strip0 + 6 * 2 * kFinIntervals + 2 * kEyeRim;
        const float d = maxf(0.0f, (M.bD - 0.2f) / 0.8f);
        for (int j = 0; j < 3; ++j) {
            m[at(fBarbelActivation) + j] = pS(0.0f, 1.0f, 3.0f * d - (float)j);
            // the centre line (its two edges' midpoints) of the right barbel, ribbon 0
            const int b0 = barbelRibbon0(j, 0, 0);
            float reach = 0.0f;
            for (int i = 0; i < kBarbelSegments; ++i) {
                const Vec3 p0 = mul(add(pts.p[b0 + 2 * i], pts.p[b0 + 2 * i + 1]), 0.5f);
                const Vec3 p1 = mul(add(pts.p[b0 + 2 * i + 2], pts.p[b0 + 2 * i + 3]), 0.5f);
                reach += norm(sub(p1, p0));
            }
            m[at(fBarbelReach) + j] = reach;
            m[at(fBarbelArea) + j] = finFromTris(pts, barb0 + j * 4 * 2 * kBarbelSegments, 4 * 2 * kBarbelSegments).area;
        }
    }

    // ---- expressed development, the estimate, the support cache ----
    m[at(fJawVolume)] = jaw; m[at(fEyeOrganVolume)] = eyes;
    m[at(fBladderCapacity)] = gas; m[at(fReserveCapacity)] = reserve;
    m[at(fReserveEnergy)] = 500.0f * 0.90f * reserve / Vref;
    m[at(fArmourThickness)] = th; m[at(fShellVolume)] = shell;
    m[at(fMuscleFibre)] = P.g[physical::kFibre];
    m[at(fStorageScale)] = storageScale; m[at(fOrganScale)] = organScale; m[at(fShellScale)] = shellScale;
    m[at(fLimits)] = (float)limits;
    m[at(fFinVolume)] = finVolume;
    m[at(fUnloadedMassEstimate)] = (1.04f * (V - shell) + 2.0f * shell + 1.10f * finVolume) / Vref;
    for (int i = 0; i < kRings; ++i) {
        float a, b;
        halfAxes(M, kRingT[i], a, b);
        m[at(fRingX) + i] = M.lam * warp(M, kRingT[i]) * R;
        m[at(fRingA) + i] = a * R;
        m[at(fRingB) + i] = b * R;
    }
    m[at(fSectionExponent)] = 2.0f / M.n;
    if (pointsOut) *pointsOut = pts;
    for (int i = 0; i < kMetrics; ++i)
        if (!std::isfinite(m[i])) { std::memset(&out, 0, sizeof out); return false; }
    return true;
}

}  // namespace bodyplan

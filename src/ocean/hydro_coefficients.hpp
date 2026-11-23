#pragma once
// ----------------------------------------------------------------------------
// hydro_coefficients — M2b1's birth compiler (PR 1, "birth physics
// foundation"): from a fish's appearance genome, S, E and physical alleles
// to its COMPACT resident physics record (Coefficients), its canonical
// support cache (Support) and, on demand, its cold diagnostics. Plus the
// analytic load update (evalLoad: the loaded mass, COM, inertia, generalized
// mass and passive tensors at an inflation k), the passive damping assembly
// the solver will use and the reference block. Nothing in the world reads
// any of this yet: public hydrodynamics requests stay refused
// (ocean_config.hpp) until the complete enabled world (M2b1 PR 3).
//
// Pure, binary32, fixed order, -ffp-contract=off; powers, square roots of
// birth quantities and every transcendental only here at birth (evomath's
// portable expf / logf through bodyplan::detail::powf_); evalLoad and
// passiveDamping use + − × ÷ and sqrt only. Same bits natively and in wasm
// (tools/ocean_hydro_fixture.cpp, compared by wasm/ocean_parity.sh).
//
// STAGE EXPRESSION (stage 1 = M2b1; the alleles stay as inherited): before
// development, gape and the eye-size gene are expressed neutral (.5; the eye
// still fitted to the head by geometry law 1), armour as zero shell and the
// barbels absent (bD 0). Hull, fins, size / elongation, bladder, fat and
// fibre are active. So a dormant allele reaches nothing: not mass, inertia,
// drag, maintenance, construction cost, muscle, support, nor another organ's
// developmental cap (tests: hydro_stage).
//
// UNITS. Lengths u, the mass unit m = the water mass of Vref (ρw = 1/Vref,
// Vref = body_plan.hpp's exact binary32 neutral hull volume), time s, energy
// E. Material densities are ratios to water. Coefficients' fields carry their
// units in HYDRO_COEFFICIENT_FIELDS.
//
// THE LAWS (the M2b1 brief, §2-3; starting constants, frozen by assays 1-4):
//   reserves     Mfuel = max(E, 0)/500, Vfuel = Mfuel/(.90 ρw),
//                Ecap = 500 · .90 ρw · Vreserve, k = sqrt(1 + (Vgas + Vfuel)/V0)
//   inflation    T(k) = diag(1, k, k) on the canonical hull and its internal
//                material (mass kept: first moments T F, second T S T); the
//                lipid fills the loaded hull uniformly (its moments Mfuel x
//                the loaded hull's per unit volume); fins translate with
//                their roots, p(k) = p0 + (k − 1) b
//   skin         Cf = .008 (L/20)^−.2, L = 20 S E
//   resistance   Af = k² Af0, Aside = k Aside0, Aplan = k Aplan0, Sw = k² Sw0,
//                fineness = hullLength / sqrt(4 Af/π),
//                CdForward = .08 + .90/clamp(fineness, 1, 30)² + .25 B0,
//                Khull = (Cd Af, 1.10 Aside, 1.10 Aplan) + Cf Sw, K = Khull + .025 Σ Afin
//   body rotation Jbody = Σ_i Khull,i [e_i]× Ch [e_i]×ᵀ, Ch the loaded hull's
//                volume covariance about the loaded material COM
//   fin tensors  w_j = (n_j, r_j × n_j), d_j = .5 ρw Cn A_j (Cn = 1.10),
//                ma_j = .25 ρw A_j meanChord_j, in the order caudal, dorsal,
//                anal, pectoral R / L, pelvic R / L; about the canonical
//                origin with bases D(k) = D0 + t D1 + t² D2 (t = k − 1;
//                D1 = Σ d (w0 w1ᵀ + w1 w0ᵀ), D2 = Σ d w1 w1ᵀ, w1 = (0, b × n));
//                the same for A; moved to the loaded COM by the spatial congruence
//   body added mass  per unit displaced water: maX .05, maY halfDepth/halfWidth,
//                maZ halfWidth/halfDepth, distributed like the loaded hull's
//                volume (so its rotational moments and COM shifts come from
//                the hull's moments: Abody = ρw Σ_i c_i ∫ w_i w_iᵀ dV, w_i =
//                (e_i, (r − c) × e_i))
//   Meff         rigid material [M 1, 0; 0, I] + Abody + Afin, about the COM
//   caudal       chords c_j after the cap at the 13 eta columns, ℓ_j =
//                sqrt(max(0, 1 − η_j²)), trapezoid weights w_j:
//                e = clamp((Σ w c ℓ)² / ((Σ w c²)(Σ w ℓ²)), .35, 1),
//                ηtail = .35 + .45 (e AR)/(e AR + 2) (AR the measured, capped one),
//                Jspar = Σ w_z (1.10 ρw tf c + .25 ρw c²) z² (the fin's material
//                and added water per unit span, about its span centre),
//                τtail = clamp(.03 + .12 sqrt(Jspar / JsparNeutral), .03, .50)
//   actuators    Aprop = Acaudal + .5 Σ Apaired; Urow = sqrt(2 TcapNeutral / (ρw Aprop))
//   metabolism   rLean = Mlean/MleanN, rMuscle = Mmuscle/MmuscleN,
//                Bbasal = .60 rLean^κ + .20 rMuscle (.4 + 1.2 f) (κ = 1: linear),
//                fixed maintenance Bfin + Bwall = .04 Mfin/MfinN + .04 Mwall/MwallN
//   construction Ebuild = 6 (Mtissue + 2 Mfin + 3 Marmour + 2 Meye + Mwall) / MleanN
//   motor        P0 = PmotorNeutral(Usus_ref) Vm/Vm0, a(f) = .55 + .90 f,
//                Psus = a P0, Ppeak = (a + 2(1 − f)) P0, Fmax = τburst (Ppeak − Psus)
//
// REFERENCES (reference law 1, PROVISIONAL): the neutral body (neutral
// genomes, S = E = 1) under the same expression, at the reference load E = 25
// trimmed neutral (its gas volume Vneutral = M/ρw − V0 − Vfuel − Vfin,
// clamped to its capacity). Its forward drag coefficient Dref (force per
// (u/s)²) = .5 ρw Kx + Dfin_xx (the fin tensor's surge entry), TcapNeutral =
// 2 Dref Uact², Urow, ηtail, and PmotorNeutral(U) = Dref U² (U + Urow)
// (fc/ηtail + fp/.35), fc = Acaudal/Aprop, fp = .5 Σ Apaired/Aprop (straight,
// steady, trimmed: thrust = drag, split by area, each channel at its
// efficiency, no pump). workConversion = .60 / PmotorNeutral(82). These are
// the analytic force-balance values: assay 2 (PR 2) measures and freezes the
// real ones (a reference-law version step, recompiling every record).
// ----------------------------------------------------------------------------
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include "body_plan.hpp"
#include "body_material.hpp"
#include "hydro_math.hpp"
#include "physical_genome.hpp"

namespace hydro {

// ---- versions ----------------------------------------------------------------------
inline constexpr int kCoefficientAbi = 1;
inline constexpr int kSupportAbi = 1;
inline constexpr int kExpressionStage = 1;    // M2b1: gape, eye size neutral; armour zero; barbels absent
inline constexpr int kReferenceLaw = 1;       // analytic force balance (provisional until assay 2)
inline constexpr int kMaterialLaw = bodymat::kMaterialLaw;
inline constexpr int kGeometryLaw = bodyplan::kGeometryLaw;
// the mechanics / energetics laws arrive with the integrator (PR 2); 0 = none yet
inline constexpr int kMechanicsLaw = 0;
inline constexpr int kEnergeticsLaw = 0;
inline bool versionsSupported(int geometry, int material, int expression, int reference) {
    return geometry == kGeometryLaw && material == kMaterialLaw && expression == kExpressionStage && reference == kReferenceLaw;
}

// ---- starting constants (the brief's; frozen by assays 1-4) -------------------------------
inline constexpr float kCn = 1.10f;               // fin normal-force coefficient
inline constexpr float kFinAddedCoef = 0.25f;     // ma_j = .25 ρw A c̄
inline constexpr float kSideCd = 1.10f;           // Ky, Kz silhouette coefficients
inline constexpr float kProfileCd = 0.025f;       // .025 Σ Afin on every translational axis
inline constexpr float kAddedSurge = 0.05f;
inline constexpr float kUref = 82.0f, kUsusRef = 108.0f, kUact = 150.0f;
inline constexpr float kPairedEfficiency = 0.35f;
inline constexpr float kTauBurst = 2.0f, kGamma = 0.5f;
inline constexpr float kFuelPerEnergy = 1.0f / 500.0f;   // Mfuel = E / 500
inline constexpr float kReferenceEnergy = 25.0f;
inline constexpr float kBuildCost = 6.0f;
inline constexpr float kNewbornEnergy = 25.0f, kReproEnergy = 20.0f;
inline constexpr float kMaintFin = 0.04f, kMaintWall = 0.04f, kMaintLipid = 0.02f;
inline constexpr float kCruiseMotorShare = 0.60f;        // E/s at Uref: workConversion's anchor

// The water density in mass units per u³: 1 / Vref.
inline float rhoWater() {
    static const float r = 1.0f / bodyplan::referenceVolume();
    return r;
}

// ---- the birth-time parameters ------------------------------------------------------------
struct Params {
    float kleiber = 0.75f;          // κ, in [0.5, 1]
    float basalStructural = 0.60f;  // E/s at the neutral lean mass
    float basalMuscle = 0.20f;      // E/s at the neutral muscle mass, fibre .5
};
inline const char* paramsError(const Params& p) {
    if (!(p.kleiber >= 0.5f && p.kleiber <= 1.0f)) return "kleiber (κ) must be a finite number in [0.5, 1]";
    if (!(p.basalStructural >= 0.0f && p.basalStructural <= 100.0f)) return "basalStructural must be finite in [0, 100] E/s";
    if (!(p.basalMuscle >= 0.0f && p.basalMuscle <= 100.0f)) return "basalMuscle must be finite in [0, 100] E/s";
    return nullptr;
}

// ---- the compact resident record (coefficient ABI 1) ---------------------------------------
template <int N> struct FieldT { using type = float[N]; };
template <> struct FieldT<1> { using type = float; };
// name, count, units, meaning. Body frame: body_plan.hpp's canonical frame
// (+x toward the tail, +y starboard, +z dorsal; the canonical origin).
#define HYDRO_COEFFICIENT_FIELDS(X)                                                                                  \
    X(size, 1, "", "bodySize S")                                                                                     \
    X(elong, 1, "", "bodyElong E")                                                                                   \
    X(refLength, 1, "u", "L = 20 S E (skin friction's and the control laws' reference length)")                     \
    X(halfLength, 1, "u", "Lc = L/2: s = sqrt(|u|² + Lc²|ω|²) and the solve's angular scale")                       \
    X(radius, 1, "u", "R = 4.6 S")                                                                                   \
    X(hullVolume, 1, "u3", "unloaded hull volume V0")                                                                \
    X(hullCentroid, 3, "u", "unloaded hull centroid")                                                                \
    X(hullCovariance, 6, "u2", "unloaded hull volume covariance about its centroid (xx yy zz xy xz yz)")            \
    X(frontalArea, 1, "u2", "Af0, the largest ring section")                                                         \
    X(sideArea, 1, "u2", "Aside0")                                                                                   \
    X(planArea, 1, "u2", "Aplan0")                                                                                   \
    X(wettedArea, 1, "u2", "Sw0")                                                                                    \
    X(hullLength, 1, "u", "measured hull length")                                                                    \
    X(foreAft, 1, "", "B0")                                                                                          \
    X(halfWidth, 1, "u", "largest unloaded hull half-width")                                                        \
    X(halfDepth, 1, "u", "largest unloaded hull half-depth")                                                        \
    X(skinFriction, 1, "", "Cf = .008 (L/20)^-.2")                                                                   \
    X(finArea, 1, "u2", "Σ fin planform areas (the profile drag .025 Σ A)")                                         \
    X(finVolume, 1, "u3", "exposed fin material volume (displacement)")                                             \
    X(innerMass, 1, "m", "hull-internal material mass (tissue, jaw, walls, eyes)")                                  \
    X(innerFirst, 3, "m u", "its first moment about the canonical origin")                                          \
    X(innerSecond, 6, "m u2", "its second moment ∫ r rᵀ dm about the canonical origin")                             \
    X(finMass, 1, "m", "exposed fin material mass")                                                                  \
    X(finFirst0, 3, "m u", "fin first moment, constant part")                                                       \
    X(finFirst1, 3, "m u", "fin first moment, per unit t = k − 1")                                                  \
    X(finSecond0, 6, "m u2", "fin second moment about the origin, constant part")                                   \
    X(finSecond1, 6, "m u2", "per unit t")                                                                           \
    X(finSecond2, 6, "m u2", "per unit t²")                                                                          \
    X(addedMass, 3, "", "body added mass per displaced water mass: x, y, z")                                        \
    X(dampD0, 21, "TT:m/u TR:m RR:m u", "fin damping per unit speed: TT m/u, TR m, RR m u; origin, constant (S6 packing)") \
    X(dampD1, 15, "TR:m RR:m u", "per unit t: TR m (3x3 row-major), then RR m u (upper triangle)")                         \
    X(dampD2, 6, "RR:m u", "per unit t²: RR m u (rotational upper triangle)")                                              \
    X(addedA0, 21, "TT:m TR:m u RR:m u2", "fin added mass: TT m, TR m u, RR m u2; origin, constant")                       \
    X(addedA1, 15, "TR:m u RR:m u2", "per unit t: TR m u, then RR m u2 (as dampD1)")                                       \
    X(addedA2, 6, "RR:m u2", "per unit t²: RR m u2 (as dampD2)")                                                           \
    X(caudalArea, 1, "u2", "caudal planform area (propulsive strips)")                                              \
    X(caudalNormal, 3, "", "caudal unit normal (+y)")                                                                \
    X(caudalCentroid, 3, "u", "caudal centroid, canonical")                                                          \
    X(caudalBasis, 3, "u", "its update basis (0: not hull-rooted)")                                                  \
    X(pairedArea, 4, "u2", "pectoral R, L, pelvic R, L areas")                                                       \
    X(pairedNormal, 12, "", "their unit normals (+z oriented)")                                                      \
    X(pairedCentroid, 12, "u", "their canonical centroids")                                                          \
    X(pairedBasis, 12, "u", "their update bases b: p(k) = p0 + (k − 1) b")                                          \
    X(pairedAspect, 4, "", "their aspect ratios span²/area")                                                         \
    X(propArea, 1, "u2", "Aprop = Acaudal + .5 Σ Apaired")                                                           \
    X(rowSpeed, 1, "u/s", "Urow = sqrt(2 TcapNeutral / (ρw Aprop)); 0 without actuators")                           \
    X(tailEfficiency, 1, "", "ηtail")                                                                                \
    X(tailTau, 1, "s", "τtail")                                                                                      \
    X(mouth, 3, "u", "canonical mouth centre (unloaded)")                                                            \
    X(mouthBasis, 3, "u", "its inflation update basis: mouth(k) = mouth + (k − 1) basis")                           \
    X(gasCapacity, 1, "u3", "bladder capacity (surface-pressure volume)")                                           \
    X(reserveCapacity, 1, "u3", "reserve (lipid) volume capacity")                                                  \
    X(energyCapacity, 1, "E", "Ecap = 500 · .90 ρw · Vreserve")                                                     \
    X(leanMass, 1, "m", "unloaded lean mass (inner + fins)")                                                         \
    X(muscleVolume, 1, "u3", "Vm = .30 of the remaining tissue")                                                    \
    X(muscleMass, 1, "m", "Mm = 1.04 ρw Vm")                                                                         \
    X(leanRatio, 1, "", "rLean = Mlean / MleanNeutral")                                                              \
    X(muscleRatio, 1, "", "rMuscle = Mm / MmNeutral")                                                                \
    X(leanFactor, 1, "", "rLean^κ (newborn target 25x, repro threshold 20x)")                                       \
    X(basalPower, 1, "E/s", "Bbasal = .60 rLean^κ + .20 rMuscle (.4 + 1.2 f)")                                      \
    X(maintenancePower, 1, "E/s", "fixed maintenance Bfin + Bwall (lipid upkeep is load-dependent)")                \
    X(buildEnergy, 1, "E", "Ebuild = 6 (Mtissue + 2 Mfin + 3 Marmour + 2 Meye + Mwall) / MleanNeutral")             \
    X(fibre, 1, "", "expressed muscle fibre f")                                                                      \
    X(motorP0, 1, "m u2/s3", "P0 = PmotorNeutral(Usus_ref) Vm/Vm0")                                                  \
    X(sustainedPower, 1, "m u2/s3", "Psus = a(f) P0")                                                                \
    X(peakPower, 1, "m u2/s3", "Ppeak = (a(f) + 2(1 − f)) P0")                                                       \
    X(fatigueCapacity, 1, "m u2/s2", "Fmax = τburst (Ppeak − Psus)")

#define HYDRO_MEMBER(name, n, units, what) FieldT<n>::type name;
struct Coefficients { HYDRO_COEFFICIENT_FIELDS(HYDRO_MEMBER) };
#define HYDRO_COUNT(name, n, units, what) +n
inline constexpr int kCoefficientFloats = 0 HYDRO_COEFFICIENT_FIELDS(HYDRO_COUNT);
static_assert(sizeof(Coefficients) == sizeof(float) * kCoefficientFloats, "Coefficients: packed binary32 fields, no padding");
static_assert(sizeof(Coefficients) <= 1024, "the physics-coefficient column's ceiling is 1,024 B a fish");
struct FieldInfo { const char* name; int count; const char* units; const char* what; int offset; };
#define HYDRO_INFO(name, n, units, what) {#name, n, units, what, (int)(offsetof(Coefficients, name) / sizeof(float))},
inline const FieldInfo kCoefficientFields[] = {HYDRO_COEFFICIENT_FIELDS(HYDRO_INFO)};
#undef HYDRO_INFO
inline constexpr int kCoefficientFieldCount = sizeof(kCoefficientFields) / sizeof(kCoefficientFields[0]);
// Copy into an actual array object; packed members do not form a float array.
inline auto floats(const Coefficients& c) { return std::bit_cast<std::array<float, kCoefficientFloats>>(c); }

// ---- the canonical support cache (support ABI 1) --------------------------------------------
// The hull's 114 vertices (body_plan.hpp's sample ids: 0 the snout tip, 1 +
// 8(i − 1) + k ring i around k, 113 the tail cap's centre), reconstructed bit
// for bit as geometry law 1 lays them out at any inflation k:
//   x = ringX_i R,  y = ((side (a_i k)) dirY_h) R,  z = ((b_i k) dirZ_h) R
// (k = 1: no multiplication), h = k <= 4 ? k : 8 − k, side = k <= 4 ? +1 : −1;
// the faces are body_plan.hpp's first 224 canonical triangles.
#define HYDRO_SUPPORT_FIELDS(X)                                                                  \
    X(radius, 1, "u", "R")                                                                       \
    X(ringX, 15, "R", "ring x positions (body radii): ring 0 the snout tip, 14 the tail cap")    \
    X(ringA, 15, "R", "ring half-widths (body radii, unloaded)")                                 \
    X(ringB, 15, "R", "ring half-depths")                                                        \
    X(dirY, 5, "", "half-ring y factors h = 0 (bottom) .. 4 (top)")                              \
    X(dirZ, 5, "", "half-ring z factors")                                                        \
    X(bounds, 4, "u", "unloaded canonical bounds: min x, max x, max |y|, max |z|")
struct Support { HYDRO_SUPPORT_FIELDS(HYDRO_MEMBER) };
inline constexpr int kSupportFloats = 0 HYDRO_SUPPORT_FIELDS(HYDRO_COUNT);
static_assert(sizeof(Support) == sizeof(float) * kSupportFloats, "Support: packed binary32 fields");
static_assert(sizeof(Support) <= 256, "the support column's ceiling is 256 B a fish");
#undef HYDRO_MEMBER
#undef HYDRO_COUNT
inline constexpr int kSupportVertices = bodyplan::kHullSamples;   // 114
inline auto floats(const Support& s) { return std::bit_cast<std::array<float, kSupportFloats>>(s); }

inline V3 supportVertex(const Support& s, int id, float k) {
    if (id <= 0) return V3{s.ringX[0] * s.radius, 0.0f, 0.0f};
    if (id >= kSupportVertices - 1) return V3{s.ringX[bodyplan::kRings - 1] * s.radius, 0.0f, 0.0f};
    const int i = 1 + (id - 1) / bodyplan::kAround, kk = (id - 1) % bodyplan::kAround;
    const int h = kk <= bodyplan::kHalfRing ? kk : bodyplan::kAround - kk;
    const float side = kk <= bodyplan::kHalfRing ? 1.0f : -1.0f;
    float a = s.ringA[i], b = s.ringB[i];
    if (k != 1.0f) { a = a * k; b = b * k; }
    return V3{s.ringX[i] * s.radius, ((side * a) * s.dirY[h]) * s.radius, (b * s.dirZ[h]) * s.radius};
}
// The hull's support in the canonical direction d at inflation k: max over
// the vertices of d·v (relative to the canonical origin); argmax = the
// lowest vertex id attaining it.
inline float support(const Support& s, float k, V3 d, int* argmax = nullptr) {
    float best = -INFINITY;
    int id = 0;
    for (int v = 0; v < kSupportVertices; ++v) {
        const float x = dot(d, supportVertex(s, v, k));
        if (x > best) { best = x; id = v; }
    }
    if (argmax) *argmax = id;
    return best;
}

// ---- the reference block (reference law 1) ------------------------------------------------
struct References {
    int ok = 0;
    float refVolume = 0, rhoWater = 0;
    float leanMass = 0, muscleVolume = 0, muscleMass = 0, finMass = 0, wallMass = 0, spar = 0;
    float fuelMass = 0;            // the reference load's lipid mass (25 E)
    float trimGas = 0, trimInflation = 0, trimMass = 0;
    float forwardDrag = 0;         // Dref: force per (u/s)² at the reference load
    float propArea = 0, caudalShare = 0, pairedShare = 0, thrustCap = 0, rowSpeed = 0, tailEfficiency = 0;
    float cruisePower = 0;         // PmotorNeutral(Uref)
    float sustainedPower = 0;      // PmotorNeutral(Usus_ref)
    float workConversion = 0;      // .60 / cruisePower  (E per m u²/s²)
    float pmotor(float U) const {
        return ((forwardDrag * U) * U) * (U + rowSpeed) * (caudalShare / tailEfficiency + pairedShare / kPairedEfficiency);
    }
};

// ---- diagnostics (cold: rebuilt on demand, never resident) -----------------------------------
struct Diagnostics {
    int error = 0;
    bodyplan::BirthCoefficients body;   // the stage-expressed geometry law 1 metrics
    physical::Genes inherited, expressed;
    float eyeGene[2] = {0, 0}, barbelGene[2] = {0, 0};   // inherited, expressed
    float bladderFraction = 0, fatFraction = 0;          // expressed (after the storage bound)
    bodymat::Material material;
    float tissueMass = 0, jawMass = 0, eyeMass = 0, wallMass = 0, shellMass = 0, finMass = 0;
    float constructionMass = 0;
    float compoundMass = 0, compoundCom[3] = {0, 0, 0}, compoundInertia[6] = {0, 0, 0, 0, 0, 0};   // unloaded, parallel-axis
    float caudalChord[bodyplan::kCaudalIntervals + 1] = {}, caudalZ[bodyplan::kCaudalIntervals + 1] = {};
    float caudalLoading = 0, sparMaterial = 0, sparWater = 0;
};

enum CompileError : int {
    kOk = 0,
    kErrParams = 1,     // Params outside their domain
    kErrGeometry = 2,   // geometry law 1 refused the inputs (domain / non-finite)
    kErrMaterial = 3,   // material law 1 could not allocate (non-zero shell, a non-positive cell or remainder)
    kErrReferences = 4, // the neutral reference body failed (never expected)
    kErrNonFinite = 5,  // a non-finite coefficient (last guard)
};
inline const char* compileErrorName(int e) {
    switch (e) {
        case kOk: return "ok";
        case kErrParams: return "params";
        case kErrGeometry: return "geometry";
        case kErrMaterial: return "material";
        case kErrReferences: return "references";
        case kErrNonFinite: return "non-finite";
    }
    return "?";
}

// ---- stage expression ------------------------------------------------------------------------
inline constexpr int kEyeGene = 29, kBarbelGene = 26;   // morph gene indices (body_plan.hpp decodeMorph)
inline appearance::Genome expressAppearance(const appearance::Genome& G) {
    appearance::Genome X = G;
    X.g[appearance::kMorphOffset + kEyeGene] = 0.5f;     // neutral eye size (still fitted to the head)
    X.g[appearance::kMorphOffset + kBarbelGene] = 0.0f;  // barbels absent
    return X;
}
inline physical::Genes expressPhysical(const physical::Genes& P) {
    physical::Genes X = P;
    X.g[physical::kGape] = 0.5f;     // neutral gape
    X.g[physical::kArmour] = 0.0f;   // zero shell
    return X;
}

namespace detail {
using bodyplan::at;
inline void addS3(float* a, const float* b) { for (int i = 0; i < 6; ++i) a[i] = a[i] + b[i]; }
inline void putS6(float* dst, const S6& A) { std::memcpy(dst, A.m, sizeof A.m); }
// The D1-style packing (cross block 3x3 row-major, then the rotational upper
// triangle) and the D2-style (rotational upper triangle).
inline constexpr int kRotU[6][2] = {{3, 3}, {3, 4}, {3, 5}, {4, 4}, {4, 5}, {5, 5}};

struct Aux {   // reference-independent birth values the finish and the references need
    float finMass = 0, wallMass = 0, spar = 0, constructionMass = 0;
};

// Everything that does not depend on the reference block.
inline int compileBase(const appearance::Genome& G, float S, float E, const physical::Genes& P, Coefficients& c, Support& sup,
                       Aux& aux, Diagnostics* diag) {
    using namespace bodyplan;
    std::memset(&c, 0, sizeof c);
    std::memset(&sup, 0, sizeof sup);
    aux = Aux{};
    // the INHERITED genome's domain first (a dormant allele out of its domain is refused, not masked)
    if (!scaleValid(S) || !scaleValid(E) || !shapeGenesValid(G.g) || !physical::genesValid(P)) return kErrGeometry;
    const appearance::Genome Gx = expressAppearance(G);
    const physical::Genes Px = expressPhysical(P);
    BirthCoefficients bc;
    Points pts;
    if (!bodyplan::compile(Gx, S, E, Px, kGeometryLaw, bc, nullptr, &pts)) return kErrGeometry;
    const float* m = bc.m;
    const float R = m[at(fRefRadius)], L = m[at(fRefLength)], lam = m[at(fLambda)];
    const Morph M = decodeMorph(Gx.g, lam);
    const float storageScale = m[at(fStorageScale)];
    const float beta = Px.g[physical::kBladder] * storageScale, fat = Px.g[physical::kFat] * storageScale;
    bodymat::Material mat;
    if (!bodymat::allocateMaterial(bc, M, pts, beta, fat, mat)) return kErrMaterial;
    const float rw = rhoWater();

    // ---- scales, hull ----
    c.size = S; c.elong = E; c.refLength = L; c.halfLength = 0.5f * L; c.radius = R;
    const float V0 = mat.hull.v;
    c.hullVolume = V0;
    const V3 hc{mat.hull.f[0] / V0, mat.hull.f[1] / V0, mat.hull.f[2] / V0};
    put(c.hullCentroid, hc);
    c.hullCovariance[0] = mat.hull.s[0] / V0 - hc.x * hc.x; c.hullCovariance[1] = mat.hull.s[1] / V0 - hc.y * hc.y;
    c.hullCovariance[2] = mat.hull.s[2] / V0 - hc.z * hc.z; c.hullCovariance[3] = mat.hull.s[3] / V0 - hc.x * hc.y;
    c.hullCovariance[4] = mat.hull.s[4] / V0 - hc.x * hc.z; c.hullCovariance[5] = mat.hull.s[5] / V0 - hc.y * hc.z;
    c.frontalArea = m[at(fFrontalArea)]; c.sideArea = m[at(fSideArea)]; c.planArea = m[at(fPlanArea)];
    c.wettedArea = m[at(fWettedArea)]; c.hullLength = m[at(fHullLength)]; c.foreAft = m[at(fForeAft)];
    c.halfWidth = m[at(fMaxHalfWidth)]; c.halfDepth = m[at(fMaxHalfDepth)];
    c.skinFriction = 0.008f * bodyplan::detail::powf_(L / 20.0f, -0.2f);
    float finArea = 0.0f, finVol = 0.0f;
    for (int f = 0; f < kFinCount; ++f) { finArea = finArea + m[finAt(f, kFinArea)]; finVol = finVol + mat.fin[f].v; }
    c.finArea = finArea; c.finVolume = finVol;

    // ---- material: masses and moments (mass units) ----
    const float rt = bodymat::kRhoTissue * rw, sE = bodymat::kRhoEye * rw, sF = bodymat::kRhoFin * rw;
    const bodymat::Moments* innerParts[4] = {&mat.tissue, &mat.jaw, &mat.walls, &mat.eyes};
    const float innerScale[4] = {rt, rt, rt, sE};
    c.innerMass = 0.0f;
    for (int i = 0; i < 4; ++i) {
        const bodymat::Moments& q = *innerParts[i];
        const float s = innerScale[i];
        c.innerMass = c.innerMass + s * q.v;
        for (int j = 0; j < 3; ++j) c.innerFirst[j] = c.innerFirst[j] + s * q.f[j];
        for (int j = 0; j < 6; ++j) c.innerSecond[j] = c.innerSecond[j] + s * q.s[j];
    }
    // fins: mass m_j, centroid p0_j, basis b_j: F = Σ m p0 + t Σ m b, S = Σ S_j + t Σ m (p0 bᵀ + b p0ᵀ) + t² Σ m b bᵀ
    c.finMass = 0.0f;
    for (int f = 0; f < kFinCount; ++f) {
        const bodymat::Moments& q = mat.fin[f];
        if (!(q.v > 0.0f)) continue;
        const float mf = sF * q.v;
        const V3 p0{q.f[0] / q.v, q.f[1] / q.v, q.f[2] / q.v}, b = mat.finBasis[f];
        c.finMass = c.finMass + mf;
        const V3 F0 = mul(p0, mf), F1 = mul(b, mf);
        c.finFirst0[0] = c.finFirst0[0] + F0.x; c.finFirst0[1] = c.finFirst0[1] + F0.y; c.finFirst0[2] = c.finFirst0[2] + F0.z;
        c.finFirst1[0] = c.finFirst1[0] + F1.x; c.finFirst1[1] = c.finFirst1[1] + F1.y; c.finFirst1[2] = c.finFirst1[2] + F1.z;
        for (int j = 0; j < 6; ++j) c.finSecond0[j] = c.finSecond0[j] + sF * q.s[j];
        const float s1[6] = {2.0f * (F0.x * b.x), 2.0f * (F0.y * b.y), 2.0f * (F0.z * b.z),
                             F0.x * b.y + b.x * F0.y, F0.x * b.z + b.x * F0.z, F0.y * b.z + b.y * F0.z};
        const float s2[6] = {F1.x * b.x, F1.y * b.y, F1.z * b.z, F1.x * b.y, F1.x * b.z, F1.y * b.z};
        addS3(c.finSecond1, s1);
        addS3(c.finSecond2, s2);
    }
    c.addedMass[0] = kAddedSurge;
    c.addedMass[1] = c.halfDepth / c.halfWidth;
    c.addedMass[2] = c.halfWidth / c.halfDepth;

    // ---- fin tensors, about the canonical origin ----
    {
        S6 D0, A0;
        zero(D0); zero(A0);
        float D1[15] = {}, D2[6] = {}, A1[15] = {}, A2[6] = {};
        for (int f = 0; f < kFinCount; ++f) {
            const float A = m[finAt(f, kFinArea)];
            if (!(A > 0.0f)) continue;   // a zero-area fin contributes exactly zero
            const V3 n = v3(m + finAt(f, kFinNormal)), p0 = v3(m + finAt(f, kFinCentroid)), b = mat.finBasis[f];
            const V3 r0 = cross(p0, n), r1 = cross(b, n);
            const V6 w0{{n.x, n.y, n.z, r0.x, r0.y, r0.z}};
            const float w1[6] = {0.0f, 0.0f, 0.0f, r1.x, r1.y, r1.z};
            const float d = ((0.5f * rw) * kCn) * A;
            const float ma = ((kFinAddedCoef * rw) * A) * m[finAt(f, kFinMeanChord)];
            addRank1(D0, w0, d);
            addRank1(A0, w0, ma);
            for (int coef = 0; coef < 2; ++coef) {
                const float s = coef ? ma : d;
                float* B1 = coef ? A1 : D1;
                float* B2 = coef ? A2 : D2;
                for (int i = 0; i < 3; ++i)
                    for (int j = 0; j < 3; ++j) B1[3 * i + j] = B1[3 * i + j] + (s * w0.v[i]) * w1[3 + j];
                for (int q = 0; q < 6; ++q) {
                    const int i = kRotU[q][0], j = kRotU[q][1];
                    B1[9 + q] = B1[9 + q] + ((s * w0.v[i]) * w1[j] + (s * w1[i]) * w0.v[j]);
                    B2[q] = B2[q] + (s * w1[i]) * w1[j];
                }
            }
        }
        putS6(c.dampD0, D0); std::memcpy(c.dampD1, D1, sizeof D1); std::memcpy(c.dampD2, D2, sizeof D2);
        putS6(c.addedA0, A0); std::memcpy(c.addedA1, A1, sizeof A1); std::memcpy(c.addedA2, A2, sizeof A2);
    }

    // ---- actuators ----
    c.caudalArea = m[finAt(kFinCaudal, kFinArea)];
    for (int j = 0; j < 3; ++j) {
        c.caudalNormal[j] = m[finAt(kFinCaudal, kFinNormal + j)];
        c.caudalCentroid[j] = m[finAt(kFinCaudal, kFinCentroid + j)];
    }
    put(c.caudalBasis, mat.finBasis[kFinCaudal]);
    const int pairedFin[4] = {kFinPecR, kFinPecL, kFinPelR, kFinPelL};
    float pairedSum = 0.0f;
    for (int q = 0; q < 4; ++q) {
        const int f = pairedFin[q];
        const float A = m[finAt(f, kFinArea)], span = m[finAt(f, kFinSpan)];
        c.pairedArea[q] = A;
        pairedSum = pairedSum + A;
        for (int j = 0; j < 3; ++j) {
            c.pairedNormal[3 * q + j] = m[finAt(f, kFinNormal + j)];
            c.pairedCentroid[3 * q + j] = m[finAt(f, kFinCentroid + j)];
        }
        put(c.pairedBasis + 3 * q, mat.finBasis[f]);
        c.pairedAspect[q] = A > 0.0f ? span * span / A : 0.0f;
    }
    c.propArea = c.caudalArea + 0.5f * pairedSum;

    // ---- caudal loading: chords after the cap, the loading correlation, the spar ----
    {
        const int nc = kCaudalIntervals + 1;
        const float tf = m[finAt(kFinCaudal, kFinThickness)];
        const float span = m[finAt(kFinCaudal, kFinSpan)];
        float swcl = 0.0f, swcc = 0.0f, swll = 0.0f, spM = 0.0f, spW = 0.0f;
        for (int j = 0; j < nc; ++j) {
            const float eta = -1.0f + 2.0f * (float)j / (float)kCaudalIntervals;
            const float chord = c.caudalArea > 0.0f ? pts.p[kCaudal0 + kCaudalRows * j + 3].x - pts.p[kCaudal0 + kCaudalRows * j + 1].x : 0.0f;
            const float z = c.caudalArea > 0.0f ? pts.p[kCaudal0 + kCaudalRows * j + 1].z : 0.0f;
            const float ell = std::sqrt(bodyplan::detail::maxf(0.0f, (1.0f - eta) * (1.0f + eta)));
            const float w = (j == 0 || j == nc - 1 ? 0.5f : 1.0f) * (2.0f / (float)kCaudalIntervals);
            swcl = swcl + w * (chord * ell);
            swcc = swcc + w * (chord * chord);
            swll = swll + w * (ell * ell);
            const float wz = w * (0.5f * span);   // dz = ½ span dη
            spM = spM + wz * (((bodymat::kRhoFin * rw) * tf) * chord) * (z * z);
            spW = spW + wz * (((kFinAddedCoef * rw) * chord) * chord) * (z * z);
            if (diag) { diag->caudalChord[j] = chord; diag->caudalZ[j] = z; }
        }
        float e = 0.35f;
        if (c.caudalArea > 0.0f && swcc > 0.0f) e = bodyplan::detail::clampf((swcl * swcl) / (swcc * swll), 0.35f, 1.0f);
        const float ar = c.caudalArea > 0.0f ? m[at(fCaudalActualAR)] : 0.0f;
        const float eAR = e * ar;
        c.tailEfficiency = 0.35f + 0.45f * (eAR / (eAR + 2.0f));
        aux.spar = spM + spW;
        if (diag) { diag->caudalLoading = e; diag->sparMaterial = spM; diag->sparWater = spW; }
    }

    // ---- mouth, storage ----
    for (int j = 0; j < 3; ++j) c.mouth[j] = m[at(fMouthCentre) + j];
    c.mouthBasis[0] = 0.0f; c.mouthBasis[1] = c.mouth[1]; c.mouthBasis[2] = c.mouth[2];   // T(k) − 1 acting on it
    c.gasCapacity = m[at(fBladderCapacity)];
    c.reserveCapacity = m[at(fReserveCapacity)];
    c.energyCapacity = (500.0f * (bodymat::kRhoLipid * rw)) * c.reserveCapacity;

    // ---- masses ----
    const float tissueMass = rt * mat.tissue.v, jawMass = rt * mat.jaw.v, wallMass = rt * mat.walls.v, eyeMass = sE * mat.eyes.v;
    c.leanMass = c.innerMass + c.finMass;
    c.muscleVolume = mat.muscleVolume;
    c.muscleMass = rt * mat.muscleVolume;
    c.fibre = Px.g[physical::kFibre];
    aux.finMass = c.finMass;
    aux.wallMass = wallMass;
    // the construction-weighted mass (tissue/jaw class, 2 x fins, 3 x armour (0), 2 x eyes, walls)
    aux.constructionMass = (((tissueMass + jawMass) + 2.0f * c.finMass) + 2.0f * eyeMass) + wallMass;

    // ---- the support cache ----
    sup.radius = R;
    for (int i = 0; i < kRings; ++i) {
        float a, b;
        halfAxes(M, kRingT[i], a, b);
        sup.ringX[i] = M.lam * warp(M, kRingT[i]);
        sup.ringA[i] = a;
        sup.ringB[i] = b;
    }
    {
        const double PI = 3.141592653589793;
        const float e = 2.0f / M.n;
        for (int h = 0; h <= kHalfRing; ++h) {
            const float th = (float)(-0.5 * PI + h * (PI / kHalfRing));
            sup.dirY[h] = bodyplan::detail::mSc(bodyplan::detail::maxf(evomath::cosf(th), 0.0f), e);
            sup.dirZ[h] = bodyplan::detail::mSc(evomath::sinf(th), e);
        }
    }
    sup.bounds[0] = m[at(fHullBounds) + 0]; sup.bounds[1] = m[at(fHullBounds) + 1];
    sup.bounds[2] = m[at(fMaxHalfWidth)]; sup.bounds[3] = m[at(fMaxHalfDepth)];

    if (diag) {
        diag->body = bc;
        diag->inherited = P; diag->expressed = Px;
        diag->eyeGene[0] = G.g[appearance::kMorphOffset + kEyeGene]; diag->eyeGene[1] = Gx.g[appearance::kMorphOffset + kEyeGene];
        diag->barbelGene[0] = G.g[appearance::kMorphOffset + kBarbelGene]; diag->barbelGene[1] = Gx.g[appearance::kMorphOffset + kBarbelGene];
        diag->bladderFraction = beta; diag->fatFraction = fat;
        diag->material = mat;
        diag->tissueMass = tissueMass + jawMass; diag->jawMass = jawMass; diag->eyeMass = eyeMass; diag->wallMass = wallMass;
        diag->shellMass = 0.0f; diag->finMass = c.finMass;
        diag->constructionMass = aux.constructionMass;
        // the unloaded lean compound by the parallel-axis assembly: tissue, jaw, eyes, walls, fins
        bodymat::Part parts[4 + kFinCount];
        parts[0] = bodymat::partOf(mat.tissue, bodymat::kRhoTissue, rw);
        parts[1] = bodymat::partOf(mat.jaw, bodymat::kRhoTissue, rw);
        parts[2] = bodymat::partOf(mat.eyes, bodymat::kRhoEye, rw);
        parts[3] = bodymat::partOf(mat.walls, bodymat::kRhoTissue, rw);
        for (int f = 0; f < kFinCount; ++f) parts[4 + f] = bodymat::partOf(mat.fin[f], bodymat::kRhoFin, rw);
        float Mc;
        V3 cc;
        S3 Ic;
        bodymat::assemble(parts, 4 + kFinCount, Mc, cc, Ic);
        diag->compoundMass = Mc;
        put(diag->compoundCom, cc);
        std::memcpy(diag->compoundInertia, Ic.m, sizeof Ic.m);
    }
    return kOk;
}
}  // namespace detail

// ---- the analytic load update ------------------------------------------------------------
// The loaded body at gas volume Vgas (u³, the current compressed volume) and
// lipid mass Mfuel (m): every quantity about the loaded material COM, in
// canonical body coordinates. Arithmetic, sqrt and division only.
struct Loaded {
    float k = 1, t = 0;           // inflation, k − 1
    float fuelVolume = 0;         // Vfuel = Mfuel / (.90 ρw)
    float mass = 0;               // M = lean + lipid
    V3 com{0, 0, 0};              // loaded material COM
    S3 inertia{};                 // material inertia about the COM
    float hullVolume = 0;         // k² V0
    float displaced = 0;          // V0 + Vgas + Vfuel + Vfin
    float halfDepth = 0;          // k · halfDepth0
    V3 hullCentroid{0, 0, 0};
    S3 hullCov{};                 // Ch: loaded hull volume covariance about the COM
    float frontal = 0, side = 0, plan = 0, wetted = 0, fineness = 0, cdForward = 0;
    float Khull[3] = {0, 0, 0};   // without the fin profile drag (rotational resistance)
    float K[3] = {0, 0, 0};       // with it (translational damping)
    S3 Jbody{};                   // Σ Khull,i [e_i]× Ch [e_i]×ᵀ
    S6 Dfin{}, Afin{}, Abody{}, Meff{};   // about the COM
    V3 mouth{0, 0, 0};            // loaded canonical mouth centre
};
// Admissible compressed gas volume is [0, gasCapacity] (surface pressure is
// the minimum); lipid mass is [0, reserveCapacity * .90 rhoWater]. Refuse
// out-of-capacity loads without clamping. Publish only a complete finite result;
// every refusal restores the default Loaded value, including k = 1.
inline bool evalLoad(const Coefficients& c, float gasVolume, float fuelMass, Loaded& out) {
    Loaded L;
    const auto refuse = [&]() { out = Loaded{}; return false; };
    if (!(gasVolume >= 0.0f) || !(fuelMass >= 0.0f) || !std::isfinite(gasVolume) || !std::isfinite(fuelMass) || !(c.hullVolume > 0.0f)) {
        return refuse();
    }
    const float rw = rhoWater();
    const float maxFuel = c.reserveCapacity * (bodymat::kRhoLipid * rw);
    if (!std::isfinite(c.gasCapacity) || !std::isfinite(maxFuel) ||
        !(gasVolume <= c.gasCapacity) || !(fuelMass <= maxFuel)) return refuse();
    const float V0 = c.hullVolume;
    L.fuelVolume = fuelMass / (bodymat::kRhoLipid * rw);
    L.k = std::sqrt(1.0f + (gasVolume + L.fuelVolume) / V0);
    L.t = L.k - 1.0f;
    const float k = L.k, t = L.t, k2 = k * k;
    // mass moments: inner (stretched), lipid (the loaded hull, uniformly), fins (translated)
    const V3 hc = v3(c.hullCentroid);
    const V3 hck{hc.x, k * hc.y, k * hc.z};
    const S3 covk = stretchS3(S3{{c.hullCovariance[0], c.hullCovariance[1], c.hullCovariance[2], c.hullCovariance[3],
                                  c.hullCovariance[4], c.hullCovariance[5]}}, k);
    const S3 innerS = stretchS3(S3{{c.innerSecond[0], c.innerSecond[1], c.innerSecond[2], c.innerSecond[3], c.innerSecond[4], c.innerSecond[5]}}, k);
    float M = c.innerMass;
    V3 F{c.innerFirst[0], k * c.innerFirst[1], k * c.innerFirst[2]};
    float S[6];
    std::memcpy(S, innerS.m, sizeof S);
    M = M + fuelMass;
    F = add(F, mul(hck, fuelMass));
    {
        const float lip[6] = {fuelMass * (covk.m[0] + hck.x * hck.x), fuelMass * (covk.m[1] + hck.y * hck.y), fuelMass * (covk.m[2] + hck.z * hck.z),
                              fuelMass * (covk.m[3] + hck.x * hck.y), fuelMass * (covk.m[4] + hck.x * hck.z), fuelMass * (covk.m[5] + hck.y * hck.z)};
        for (int j = 0; j < 6; ++j) S[j] = S[j] + lip[j];
    }
    M = M + c.finMass;
    F = add(F, V3{c.finFirst0[0] + t * c.finFirst1[0], c.finFirst0[1] + t * c.finFirst1[1], c.finFirst0[2] + t * c.finFirst1[2]});
    for (int j = 0; j < 6; ++j) S[j] = S[j] + (c.finSecond0[j] + t * (c.finSecond1[j] + t * c.finSecond2[j]));
    if (!(M > 0.0f)) return refuse();
    L.mass = M;
    L.com = V3{F.x / M, F.y / M, F.z / M};
    const V3 cm = L.com;
    const S3 C{{S[0] - M * cm.x * cm.x, S[1] - M * cm.y * cm.y, S[2] - M * cm.z * cm.z, S[3] - M * cm.x * cm.y, S[4] - M * cm.x * cm.z,
                S[5] - M * cm.y * cm.z}};
    L.inertia = inertiaOf(C);
    // the loaded hull
    L.hullVolume = k2 * V0;
    L.displaced = ((V0 + gasVolume) + L.fuelVolume) + c.finVolume;
    L.halfDepth = k * c.halfDepth;
    L.hullCentroid = hck;
    const V3 d = sub(hck, cm);
    L.hullCov = S3{{covk.m[0] + d.x * d.x, covk.m[1] + d.y * d.y, covk.m[2] + d.z * d.z, covk.m[3] + d.x * d.y, covk.m[4] + d.x * d.z,
                    covk.m[5] + d.y * d.z}};
    // resistance
    L.frontal = k2 * c.frontalArea; L.side = k * c.sideArea; L.plan = k * c.planArea; L.wetted = k2 * c.wettedArea;
    L.fineness = c.hullLength / std::sqrt(4.0f * L.frontal / bodyplan::detail::kPi);
    const float fc = bodyplan::detail::clampf(L.fineness, 1.0f, 30.0f);
    L.cdForward = (0.08f + 0.90f / (fc * fc)) + 0.25f * c.foreAft;
    const float cfs = c.skinFriction * L.wetted;
    L.Khull[0] = L.cdForward * L.frontal + cfs;
    L.Khull[1] = kSideCd * L.side + cfs;
    L.Khull[2] = kSideCd * L.plan + cfs;
    const float prof = kProfileCd * c.finArea;
    for (int i = 0; i < 3; ++i) L.K[i] = L.Khull[i] + prof;
    {
        const float* h = L.hullCov.m;   // xx yy zz xy xz yz
        const float Kx = L.Khull[0], Ky = L.Khull[1], Kz = L.Khull[2];
        L.Jbody = S3{{Ky * h[2] + Kz * h[1], Kx * h[2] + Kz * h[0], Kx * h[1] + Ky * h[0], -(Kz * h[3]), -(Ky * h[4]), -(Kx * h[5])}};
    }
    // fin tensors at k, about the origin, then about the COM
    {
        S6 Do, Ao;
        for (int q = 0; q < 21; ++q) { Do.m[q] = c.dampD0[q]; Ao.m[q] = c.addedA0[q]; }
        for (int i = 0; i < 3; ++i)
            for (int j = 0; j < 3; ++j) {
                const int qi = s6u(i, 3 + j);
                Do.m[qi] = Do.m[qi] + t * c.dampD1[3 * i + j];
                Ao.m[qi] = Ao.m[qi] + t * c.addedA1[3 * i + j];
            }
        for (int q = 0; q < 6; ++q) {
            const int qi = s6u(detail::kRotU[q][0], detail::kRotU[q][1]);
            Do.m[qi] = Do.m[qi] + t * (c.dampD1[9 + q] + t * c.dampD2[q]);
            Ao.m[qi] = Ao.m[qi] + t * (c.addedA1[9 + q] + t * c.addedA2[q]);
        }
        L.Dfin = congruence(Do, cm);
        L.Afin = congruence(Ao, cm);
    }
    // body added mass about the COM: ρw Σ c_i ∫ w_i w_iᵀ dV over the loaded hull
    {
        const float cx = c.addedMass[0], cy = c.addedMass[1], cz = c.addedMass[2];
        const float Vk = L.hullVolume;
        const V3 Fc = mul(d, Vk);                        // ∫ (r − c) dV
        const float* h = L.hullCov.m;
        const float Sc[6] = {Vk * h[0], Vk * h[1], Vk * h[2], Vk * h[3], Vk * h[4], Vk * h[5]};   // ∫ (r − c)(r − c)ᵀ dV
        S6& A = L.Abody;
        zero(A);
        A.m[s6u(0, 0)] = rw * (cx * Vk); A.m[s6u(1, 1)] = rw * (cy * Vk); A.m[s6u(2, 2)] = rw * (cz * Vk);
        A.m[s6u(0, 4)] = rw * (cx * Fc.z);  A.m[s6u(0, 5)] = rw * -(cx * Fc.y);
        A.m[s6u(1, 3)] = rw * -(cy * Fc.z); A.m[s6u(1, 5)] = rw * (cy * Fc.x);
        A.m[s6u(2, 3)] = rw * (cz * Fc.y);  A.m[s6u(2, 4)] = rw * -(cz * Fc.x);
        A.m[s6u(3, 3)] = rw * (cy * Sc[2] + cz * Sc[1]);
        A.m[s6u(4, 4)] = rw * (cx * Sc[2] + cz * Sc[0]);
        A.m[s6u(5, 5)] = rw * (cx * Sc[1] + cy * Sc[0]);
        A.m[s6u(3, 4)] = rw * -(cz * Sc[3]);
        A.m[s6u(3, 5)] = rw * -(cy * Sc[4]);
        A.m[s6u(4, 5)] = rw * -(cx * Sc[5]);
    }
    // Meff = rigid + Abody + Afin
    {
        S6& Me = L.Meff;
        zero(Me);
        Me.m[s6u(0, 0)] = M; Me.m[s6u(1, 1)] = M; Me.m[s6u(2, 2)] = M;
        const float* I = L.inertia.m;
        Me.m[s6u(3, 3)] = I[0]; Me.m[s6u(4, 4)] = I[1]; Me.m[s6u(5, 5)] = I[2];
        Me.m[s6u(3, 4)] = I[3]; Me.m[s6u(3, 5)] = I[4]; Me.m[s6u(4, 5)] = I[5];
        addTo(Me, L.Abody);
        addTo(Me, L.Afin);
    }
    L.mouth = V3{c.mouth[0] + t * c.mouthBasis[0], c.mouth[1] + t * c.mouthBasis[1], c.mouth[2] + t * c.mouthBasis[2]};
    const float scalars[] = {L.k, L.t, L.fuelVolume, L.mass, L.com.x, L.com.y, L.com.z,
        L.hullVolume, L.displaced, L.halfDepth, L.hullCentroid.x, L.hullCentroid.y, L.hullCentroid.z,
        L.frontal, L.side, L.plan, L.wetted, L.fineness, L.cdForward, L.mouth.x, L.mouth.y, L.mouth.z};
    for (float x : scalars) if (!std::isfinite(x)) return refuse();
    for (const S3* a : {&L.inertia, &L.hullCov, &L.Jbody})
        for (float x : a->m) if (!std::isfinite(x)) return refuse();
    for (const S6* a : {&L.Dfin, &L.Afin, &L.Abody, &L.Meff})
        for (float x : a->m) if (!std::isfinite(x)) return refuse();
    for (int i = 0; i < 3; ++i)
        if (!std::isfinite(L.K[i]) || !std::isfinite(L.Khull[i])) return refuse();
    out = L;
    return true;
}

// The passive damping tensor at the water-relative state z = (u, ω) (body
// frame, about the COM): Dbody + s Dfin, with Dbody's translational diagonal
// .5 ρw K_i |u_i| and rotational .5 ρw s Jbody, s = sqrt(|u|² + Lc²|ω|²).
// (The induced and braking terms belong to the actuators: PR 2.) PSD.
inline S6 passiveDamping(const Loaded& L, float Lc, const V6& z) {
    const float rw = rhoWater();
    const V3 u{z.v[0], z.v[1], z.v[2]}, w{z.v[3], z.v[4], z.v[5]};
    const float s = std::sqrt(norm2(u) + (Lc * Lc) * norm2(w));
    S6 D = scaled(L.Dfin, s);
    const float hr = 0.5f * rw;
    D.m[s6u(0, 0)] = D.m[s6u(0, 0)] + hr * (L.K[0] * std::fabs(u.x));
    D.m[s6u(1, 1)] = D.m[s6u(1, 1)] + hr * (L.K[1] * std::fabs(u.y));
    D.m[s6u(2, 2)] = D.m[s6u(2, 2)] + hr * (L.K[2] * std::fabs(u.z));
    const float hs = hr * s;
    const float* J = L.Jbody.m;
    D.m[s6u(3, 3)] = D.m[s6u(3, 3)] + hs * J[0];
    D.m[s6u(4, 4)] = D.m[s6u(4, 4)] + hs * J[1];
    D.m[s6u(5, 5)] = D.m[s6u(5, 5)] + hs * J[2];
    D.m[s6u(3, 4)] = D.m[s6u(3, 4)] + hs * J[3];
    D.m[s6u(3, 5)] = D.m[s6u(3, 5)] + hs * J[4];
    D.m[s6u(4, 5)] = D.m[s6u(4, 5)] + hs * J[5];
    return D;
}

// ---- references and the compile -------------------------------------------------------------
namespace detail {
inline References buildReferences() {
    References r;
    Coefficients c;
    Support sup;
    Aux aux;
    if (compileBase(appearance::neutral(), 1.0f, 1.0f, physical::neutral(), c, sup, aux, nullptr) != kOk) return r;
    const float rw = rhoWater();
    r.refVolume = bodyplan::referenceVolume();
    r.rhoWater = rw;
    r.leanMass = c.leanMass; r.muscleVolume = c.muscleVolume; r.muscleMass = c.muscleMass;
    r.finMass = aux.finMass; r.wallMass = aux.wallMass; r.spar = aux.spar;
    r.fuelMass = kReferenceEnergy * kFuelPerEnergy;
    const float fuelVolume = r.fuelMass / (bodymat::kRhoLipid * rw);
    r.trimMass = c.leanMass + r.fuelMass;
    const float neutralGas = ((r.trimMass / rw - c.hullVolume) - fuelVolume) - c.finVolume;
    r.trimGas = bodyplan::detail::clampf(neutralGas, 0.0f, c.gasCapacity);
    Loaded L;
    if (!evalLoad(c, r.trimGas, r.fuelMass, L)) return r;
    r.trimInflation = L.k;
    r.forwardDrag = (0.5f * rw) * L.K[0] + at6(L.Dfin, 0, 0);
    r.propArea = c.propArea;
    r.caudalShare = c.caudalArea / c.propArea;
    r.pairedShare = (c.propArea - c.caudalArea) / c.propArea;
    r.thrustCap = 2.0f * ((r.forwardDrag * kUact) * kUact);
    r.rowSpeed = std::sqrt(2.0f * r.thrustCap / (rw * c.propArea));
    r.tailEfficiency = c.tailEfficiency;
    r.cruisePower = r.pmotor(kUref);
    r.sustainedPower = r.pmotor(kUsusRef);
    r.workConversion = kCruiseMotorShare / r.cruisePower;
    r.ok = std::isfinite(r.workConversion) && r.workConversion > 0.0f && r.leanMass > 0.0f && r.muscleMass > 0.0f &&
           r.finMass > 0.0f && r.wallMass > 0.0f && r.spar > 0.0f ? 1 : 0;
    return r;
}
}  // namespace detail
inline const References& references() {
    static const References R = detail::buildReferences();
    return R;
}

// The compile. On any failure every output is zero and the error is returned
// (and recorded in diag->error).
inline int compile(const appearance::Genome& G, float S, float E, const physical::Genes& P, const Params& prm, Coefficients& c,
                   Support& sup, Diagnostics* diag = nullptr) {
    auto fail = [&](int e) {
        std::memset(&c, 0, sizeof c);
        std::memset(&sup, 0, sizeof sup);
        if (diag) { *diag = Diagnostics{}; diag->error = e; }
        return e;
    };
    if (diag) *diag = Diagnostics{};
    if (paramsError(prm)) return fail(kErrParams);
    const References& ref = references();
    if (!ref.ok) return fail(kErrReferences);
    detail::Aux aux;
    const int e = detail::compileBase(G, S, E, P, c, sup, aux, diag);
    if (e != kOk) return fail(e);
    const float rw = ref.rhoWater;
    c.leanRatio = c.leanMass / ref.leanMass;
    c.muscleRatio = c.muscleMass / ref.muscleMass;
    c.leanFactor = prm.kleiber == 1.0f ? c.leanRatio : bodyplan::detail::powf_(c.leanRatio, prm.kleiber);
    c.basalPower = prm.basalStructural * c.leanFactor + prm.basalMuscle * (c.muscleRatio * (0.4f + 1.2f * c.fibre));
    c.maintenancePower = kMaintFin * (aux.finMass / ref.finMass) + kMaintWall * (aux.wallMass / ref.wallMass);
    c.buildEnergy = kBuildCost * (aux.constructionMass / ref.leanMass);
    c.tailTau = bodyplan::detail::clampf(0.03f + 0.12f * std::sqrt(aux.spar / ref.spar), 0.03f, 0.50f);
    c.rowSpeed = c.propArea > 0.0f ? std::sqrt(2.0f * ref.thrustCap / (rw * c.propArea)) : 0.0f;
    c.motorP0 = ref.sustainedPower * (c.muscleVolume / ref.muscleVolume);
    const float a = 0.55f + 0.90f * c.fibre;
    c.sustainedPower = a * c.motorP0;
    c.peakPower = (a + 2.0f * (1.0f - c.fibre)) * c.motorP0;
    c.fatigueCapacity = kTauBurst * (c.peakPower - c.sustainedPower);
    const auto cf = floats(c);
    for (int i = 0; i < kCoefficientFloats; ++i)
        if (!std::isfinite(cf[i])) return fail(kErrNonFinite);
    const auto sf = floats(sup);
    for (int i = 0; i < kSupportFloats; ++i)
        if (!std::isfinite(sf[i])) return fail(kErrNonFinite);
    if (diag) diag->error = kOk;
    return kOk;
}

// ---- digests (explicit fields: the records are packed floats) --------------------------------
struct Digest {
    std::uint64_t h = 0xcbf29ce484222325ull;   // FNV-1a over little-endian words
    void add(std::uint32_t u) { for (int k = 0; k < 4; ++k) { h ^= (u >> (8 * k)) & 0xFFu; h *= 0x100000001b3ull; } }
    void addf(float f) { std::uint32_t u; std::memcpy(&u, &f, 4); add(u); }
    void addFloats(const float* p, int n) { for (int i = 0; i < n; ++i) addf(p[i]); }
};
inline std::uint64_t digest(const Coefficients& c) { Digest d; d.addFloats(floats(c).data(), kCoefficientFloats); return d.h; }
inline std::uint64_t digest(const Support& s) { Digest d; d.addFloats(floats(s).data(), kSupportFloats); return d.h; }
inline std::uint64_t digest(const References& r) {
    Digest d;
    d.add((std::uint32_t)kReferenceLaw);
    d.add((std::uint32_t)r.ok);
    const float v[] = {r.refVolume, r.rhoWater, r.leanMass, r.muscleVolume, r.muscleMass, r.finMass, r.wallMass, r.spar, r.fuelMass,
                       r.trimGas, r.trimInflation, r.trimMass, r.forwardDrag, r.propArea, r.caudalShare, r.pairedShare, r.thrustCap,
                       r.rowSpeed, r.tailEfficiency, r.cruisePower, r.sustainedPower, r.workConversion};
    d.addFloats(v, (int)(sizeof v / sizeof v[0]));
    return d.h;
}

}  // namespace hydro

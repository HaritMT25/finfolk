#pragma once
// ----------------------------------------------------------------------------
// physical_genome — M2's five physical alleles (M2a: inherited, compiled into
// a diagnostic body plan, src/ocean/body_plan.hpp, and READ BY NOTHING THE
// STEP COMPUTES). Five normalized binary32 alleles per fish, in this frozen
// order (schema 1):
//
//   0 gape             mouth aperture (expressed: H(g; .15, .40, .65) x the
//                      local head diameter at t = -.10)
//   1 bladderCapacity  maximum gas volume .15 g V (V: the fish's unloaded hull)
//   2 armour           shell thickness .06 g x the shoulder's smaller half-axis
//   3 fatCapacity      reserve volume .02 V + .20 g V
//   4 muscleFibre      0 white (burst) .. 1 red (sustained); M2b's power split
//
//   neutral = [.5, .5, 0, .4, .5]
//
// (the M2 spine's four-gene table order, m2_design_codex.md, with fibre
// appended: design v1 §4 / v2 §5). The appearance genome (appearance_model.hpp,
// 63 floats, schema 3) is a separate record and keeps its stride.
//
// THE DRAW STREAM. A separately salted counter stream, never the simulation's
// rng and never the appearance stream's slots:
//     physKey = mix64(appearanceKey ^ kSaltV1)          (per world, at init)
//     base    = mix64(physKey ^ mix64(fishId + γ))
//     draw k  = top 24 bits of mix64(base + (k + 1)·γ) × 2^-24
// (appearance::streamBase / streamDraw with the salted key). Frozen slots:
//   founder:    0..4    the five prospective founder sources (gene order)
//   offspring:  0..4    the five group selectors (one group per gene)
//               5..9    the five prospective founder sources
//               10..14  the five per-gene jitters
// Every slot is drawn for every fish, whatever the mutation and novelty
// settings, the parents' equality or what is expressed.
//
// Founder law 1: gape, bladder, fat and fibre clamp(neutral + .10(2r − 1));
// armour 0 for r < .85, else (r − .85) / .15 (sparse expression).
// Inheritance law 1: M1's group rule and arithmetic exactly
// (appearance_model.hpp offspringFromDraws, the shape half): per group the
// mean of the two parents (20%), copy A, copy B, or the prospective founder
// allele (novel probability p; at p = .05: 20 / 37.5 / 37.5 / 5%), a mean of
// identical parents being a copy; then a uniform jitter ±mutation, clamped to
// [0, 1]. Double intermediates, binary32 stores at the same points as M1.
// ----------------------------------------------------------------------------
#include <cstdint>
#include <cstring>
#include <initializer_list>   // (appearance_model.hpp's genomeValid uses one; it relies on its includer)
#include "appearance_model.hpp"

namespace physical {

// ---- schema and versions -----------------------------------------------------
inline constexpr int kSchema = 1;           // five binary32 alleles, the order above
inline constexpr int kFounderLaw = 1;
inline constexpr int kInheritanceLaw = 1;
inline constexpr int kStreamLaw = 1;        // kSaltV1, the slots above

inline constexpr int kGenes = 5;
inline constexpr int kGroups = 5;
inline constexpr int kFounderDraws = 5;
inline constexpr int kOffspringDraws = 15;
enum Gene : int { kGape = 0, kBladder = 1, kArmour = 2, kFat = 3, kFibre = 4 };
inline constexpr const char* kGeneNames[kGenes] = {"gape", "bladderCapacity", "armour", "fatCapacity", "muscleFibre"};

// The stream's salt (stream law 1): the bytes of "M2a-phys" as one word.
inline constexpr std::uint64_t kSaltV1 = 0x4D32612D70687973ull;

inline constexpr float kNeutral[kGenes] = {0.5f, 0.5f, 0.0f, 0.4f, 0.5f};

struct Genes {
    float g[kGenes];
};
static_assert(sizeof(Genes) == 20, "the physical genome is five binary32 floats");

// Inheritance settings (OceanConfig::physicalMutation, physicalNovelProbability).
struct Inheritance {
    float mutation = 0.025f;
    float novel    = 0.050f;
};

// A world's construction counters (statistics; never read by the step).
struct Stats {
    std::uint64_t founders = 0, offspring = 0;
    std::uint64_t mode[4] = {};   // [appearance::Mode] summed over the five groups
};

inline Genes neutral() {
    Genes G;
    for (int j = 0; j < kGenes; ++j) G.g[j] = kNeutral[j];
    return G;
}

// ---- the stream ----------------------------------------------------------------
inline std::uint64_t worldKey(std::uint64_t appearanceKey) { return appearance::mix64(appearanceKey ^ kSaltV1); }
inline void streamDraws(std::uint64_t physKey, std::uint64_t fishId, double* r, int n) {
    appearance::streamDraws(physKey, fishId, r, n);
}

// ---- construction ----------------------------------------------------------------
namespace detail {
inline float f32(double x) { return (float)x; }
inline double clamp01(double x) { return x < 0.0 ? 0.0 : (x > 1.0 ? 1.0 : x); }
// The neutral-centred founder transform (gape, bladder, fat, fibre), in doubles.
inline double centred(double neutral, double r) { return clamp01(neutral + 0.10 * (2.0 * r - 1.0)); }
}  // namespace detail

// Founder law 1 from draws r[0..4] (gene order).
inline void founderFromDraws(const double* r, Genes& G) {
    using detail::f32;
    G.g[kGape]    = f32(detail::centred(0.5, r[0]));
    G.g[kBladder] = f32(detail::centred(0.5, r[1]));
    G.g[kArmour]  = f32(r[2] < 0.85 ? 0.0 : (r[2] - 0.85) / 0.15);
    G.g[kFat]     = f32(detail::centred(0.4, r[3]));
    G.g[kFibre]   = f32(detail::centred(0.5, r[4]));
}

// Inheritance law 1: parents A (maternal) and B, draws D[0..14]; modes
// (optional) receives each group's branch.
inline void offspringFromDraws(const Genes& A, const Genes& B, const double* D, const Inheritance& cfg, Genes& Q,
                               std::uint8_t* modes = nullptr) {
    using detail::f32;
    Genes fresh;
    founderFromDraws(D + kGroups, fresh);
    const double p = cfg.novel;
    for (int j = 0; j < kGroups; ++j) {   // one gene per group
        const int mode = appearance::detail::selectMode(D[j], p);
        if (modes) modes[j] = (std::uint8_t)mode;
        const bool same = A.g[j] == B.g[j];
        if (mode == appearance::kCopyA || (mode == appearance::kMean && same)) Q.g[j] = A.g[j];
        else if (mode == appearance::kCopyB) Q.g[j] = B.g[j];
        else if (mode == appearance::kNovel) Q.g[j] = fresh.g[j];
        else Q.g[j] = f32(((double)A.g[j] + (double)B.g[j]) * 0.5);
    }
    const float m = cfg.mutation, m2 = f32(2.0 * m);
    for (int j = 0; j < kGenes; ++j) {
        const float x = f32((double)Q.g[j] + (double)f32(-(double)m + (double)f32((double)m2 * D[kGroups + kGenes + j])));
        Q.g[j] = x < 0.0f ? 0.0f : (x > 1.0f ? 1.0f : x);
    }
}

// The engine's entry points: the same functions, fed by the fish's own stream.
inline void makeFounder(std::uint64_t physKey, std::uint64_t fishId, Genes& G) {
    double r[kFounderDraws];
    streamDraws(physKey, fishId, r, kFounderDraws);
    founderFromDraws(r, G);
}
inline void makeOffspring(std::uint64_t physKey, std::uint64_t childId, const Genes& A, const Genes& B,
                          const Inheritance& cfg, Genes& Q, std::uint8_t* modes = nullptr) {
    double r[kOffspringDraws];
    streamDraws(physKey, childId, r, kOffspringDraws);
    offspringFromDraws(A, B, r, cfg, Q, modes);
}

// Every allele finite and in [0, 1].
inline bool genesValid(const Genes& G) {
    for (int j = 0; j < kGenes; ++j)
        if (!(G.g[j] >= 0.0f && G.g[j] <= 1.0f)) return false;
    return true;
}

}  // namespace physical

#pragma once
#include <array>
#include <vector>
#include <random>
#include "connectivity.hpp"
#include "vec2.hpp"
#include "genome.hpp"
#include "random.hpp"

// Projections of the (source,sink) connectivity vector — the SAME ~1272-dim space
// the species SimHash and genome colour use. Two products:
//
//   clusterSketch(genome, out)  -> a fixed CLUSTER_SKETCH_DIM random projection.
//       A Johnson-Lindenstrauss sketch: small enough to store per death (so the
//       death-cluster map can run PCA over it at end-of-run) yet preserves pairwise
//       distances well, so PCA on the sketch ~ PCA on the full vector. Storing the
//       full 1272-dim vector per death would be ~100 MB at 20k points; the sketch is
//       a few MB.
//
//   clusterProject2D(genome)    -> a fixed 2-D point (the non-PCA map). Derived from
//       the sketch via two more fixed directions, so it stays a reproducible random
//       projection, comparable across runs and coherent with the genome colour (its
//       3-D sibling). PCA axes, by contrast, are data-dependent per run.
//
// All directions are seeded once with a LOCAL rng (the global `rng` stream is
// untouched), so these never perturb the simulation. v0.18.0: generation moved
// from std::normal_distribution (implementation-defined, differs native vs
// wasm) to portableGaussian, so sketches are cross-platform stable — but the
// projection axes changed once at that version: cluster maps are comparable
// only within runs from the same side of that boundary. Caveat: a projection
// is a lossy shadow — nearby points are close in the projected subspace, not a
// guarantee of full genome similarity.

constexpr int CLUSTER_SKETCH_DIM = 32;

namespace clusterproj_detail {
// CLUSTER_SKETCH_DIM random directions over the connectivity space.
inline const std::array<std::vector<float>, CLUSTER_SKETCH_DIM>& sketchPlanes() {
    static const std::array<std::vector<float>, CLUSTER_SKETCH_DIM> planes = [] {
        std::mt19937 g(0x5EEDC2D2u);
        std::array<std::vector<float>, CLUSTER_SKETCH_DIM> p;
        for (auto& row : p) { row.assign(STATS_DIM, 0.0f); for (float& x : row) x = portableGaussian(g); }
        return p;
    }();
    return planes;
}
// Two fixed directions over the sketch space -> the default (non-PCA) 2-D map.
inline const std::array<std::array<float, CLUSTER_SKETCH_DIM>, 2>& mapDirs() {
    static const std::array<std::array<float, CLUSTER_SKETCH_DIM>, 2> d = [] {
        std::mt19937 g(0x5EEDFACEu);
        std::array<std::array<float, CLUSTER_SKETCH_DIM>, 2> a;
        for (auto& row : a) for (float& x : row) x = portableGaussian(g);
        return a;
    }();
    return d;
}
}  // namespace clusterproj_detail

inline void clusterSketch(const Genome& genome, float out[CLUSTER_SKETCH_DIM]) {
    const auto& planes = clusterproj_detail::sketchPlanes();
    double acc[CLUSTER_SKETCH_DIM] = {};
    for (const Gene& gene : genome) {
        const int   idx = geneCell(gene, genome.schema);
        const float w   = geneWeight(gene, genome.schema);
        for (int k = 0; k < CLUSTER_SKETCH_DIM; ++k) acc[k] += w * (idx < STATS_DIM ? planes[k][idx] : biasProjectionPlanes()[19 + k][idx - STATS_DIM]);
    }
    for (int k = 0; k < CLUSTER_SKETCH_DIM; ++k) out[k] = static_cast<float>(acc[k]);
}

// Project a stored sketch onto the two fixed map directions (the non-PCA map point).
inline Vec2 sketchTo2D(const float sketch[CLUSTER_SKETCH_DIM]) {
    const auto& d = clusterproj_detail::mapDirs();
    double px = 0.0, py = 0.0;
    for (int k = 0; k < CLUSTER_SKETCH_DIM; ++k) {
        px += sketch[k] * d[0][k];
        py += sketch[k] * d[1][k];
    }
    return Vec2{ static_cast<float>(px), static_cast<float>(py) };
}

inline Vec2 clusterProject2D(const Genome& genome) {
    float s[CLUSTER_SKETCH_DIM];
    clusterSketch(genome, s);
    return sketchTo2D(s);
}

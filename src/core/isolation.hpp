#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include "connectivity.hpp"
#include "genome.hpp"

// ----------------------------------------------------------------------------
// Match distance — distance between two Genomes in the SAME folded
// (source, sink) connectivity space that buildNeuralNet() wires, and that the
// species SimHash (stats.hpp) and genome colour (genome_color.hpp) already
// share via connectivity.hpp. Duplicate edges sum, exactly as they do in the
// net's accumulators.
//
// WHY NOT genomeSimilarity() (genome.hpp): it compares gene i to gene i, and
// only sourceType/sinkType — two bits per gene, positionally aligned.
// mutateGenome inserts, deletes and duplicates genes, so a SINGLE indel shifts
// every downstream gene and collapses the score between a Genome and a Genome
// derived directly from it. That is tolerable for the rough percept it feeds
// (GENETIC_SIM_NEAREST) and useless as an admission gate. The fold below is
// permutation-invariant and indel-robust, which is precisely what a gate needs.
// core_tests pins the contrast directly, so the reason this function exists
// stays documented in the test suite rather than only here.
//
// DETERMINISM. This is sim-path code, so it obeys the project's rules:
//   * no rng draws, ever — the gate must not perturb the draw sequence;
//   * no transcendentals, so no evomath:: dependency — only +, -, *, and an
//     exact power-of-two divide (weight / 8192.0f, the same expression
//     Gene::weightAsFloat() uses, so folded weights are bit-identical to the
//     ones stats.hpp and genome_color.hpp compute);
//   * no heap allocation;
//   * the result is independent of the sort ALGORITHM, so libstdc++ and
//     libc++/wasm agree bit for bit. See the ordering note on cellWeightLess().
// ----------------------------------------------------------------------------

namespace isolation_detail {

// Upper bound on genes we will fold. GENOME_MAX_LENGTH (80) is the structural
// constant, but cfg.genomeMaxLength is a user knob that can be set above it, so
// the buffer is sized well clear of any sane value and main.cpp refuses to run
// the gate past it rather than silently truncating a genome.
constexpr int ISO_MAX_GENES = 1024;
static_assert(GENOME_MAX_LENGTH <= ISO_MAX_GENES,
              "fold buffer is smaller than the structural genome bound");
static_assert(STATS_V2_DIM <= 65535, "cell index no longer fits in uint16_t");

struct CellWeight {
    std::uint16_t cell;
    std::int16_t  weight;   // raw Gene::weight; converted at accumulate time
};

// Order by the PAIR (cell, weight), not by cell alone. This is the load-bearing
// detail and it is easy to get wrong:
//
//   * Sorting by cell alone leaves genes that share a cell in whatever order
//     the genome happened to hold them. Their weights are then summed in that
//     order, and float addition is not associative, so a permuted genome folds
//     to a DIFFERENT vector and distance-to-itself stops being 0. Permutation
//     invariance is one of the two properties this whole function exists for.
//   * Ordering by the pair makes any two elements that compare equal
//     bit-identical in both fields, so they are interchangeable. The sorted
//     array is therefore a function of the input MULTISET alone — same result
//     from any input order and from any sort algorithm, stable or not. That is
//     the same argument the topological-neighbour tie-break relies on: never
//     sort on a key that can tie between distinguishable elements.
inline bool cellWeightLess(const CellWeight& a, const CellWeight& b) {
    if (a.cell != b.cell) return a.cell < b.cell;
    return a.weight < b.weight;
}

// Fold a genome into ascending-cell (cell, summed weight) pairs. Returns the
// number of distinct cells written; cells[] is strictly increasing afterwards.
inline int foldGenome(const Genome& g, std::uint16_t cells[], float weights[]) {
    CellWeight tmp[ISO_MAX_GENES];
    const int n = (int)std::min<std::size_t>(g.size(), ISO_MAX_GENES);
    for (int i = 0; i < n; ++i) {
        tmp[i].cell   = (std::uint16_t)geneCell(g[i], g.schema);
        tmp[i].weight = g[i].weight;
    }
    std::sort(tmp, tmp + n, cellWeightLess);

    int m = 0;
    for (int i = 0; i < n; ) {
        const std::uint16_t cell = tmp[i].cell;
        float sum = 0.0f;
        int j = i;
        while (j < n && tmp[j].cell == cell) {
            sum += g.schema.genomeVersion == 2
                ? logweight::decodeValid(logweight::word(tmp[j].weight))
                : (float)tmp[j].weight / 8192.0f;   // == Gene::weightAsFloat()
            ++j;
        }
        cells[m]   = cell;
        weights[m] = sum;
        ++m;
        i = j;
    }
    return m;
}

}  // namespace isolation_detail

// Squared L2 distance between two genomes in the folded connectivity space.
// Permutation-invariant, indel-robust; O(n log n) in genome length.
//
// Exactly symmetric: genomeDistanceSq(a,b) is bitwise equal to
// genomeDistanceSq(b,a). IEEE subtraction is exactly antisymmetric
// (fl(x-y) == -fl(y-x) for round-to-nearest), squaring erases the sign, and the
// merge below visits cells in ascending order either way — so both calls sum
// the identical sequence of identical terms.
inline float genomeDistanceSq(const Genome& a, const Genome& b) {
    if (a.schema != b.schema) return std::numeric_limits<float>::infinity();
    using namespace isolation_detail;
    std::uint16_t ca[ISO_MAX_GENES], cb[ISO_MAX_GENES];
    float wa[ISO_MAX_GENES], wb[ISO_MAX_GENES];
    const int na = foldGenome(a, ca, wa);
    const int nb = foldGenome(b, cb, wb);

    float acc = 0.0f;
    int i = 0, j = 0;
    while (i < na && j < nb) {
        if (ca[i] == cb[j]) {
            const float d = wa[i] - wb[j];
            acc += d * d;
            ++i; ++j;
        } else if (ca[i] < cb[j]) {
            acc += wa[i] * wa[i];    // cell absent from b => b's weight is 0
            ++i;
        } else {
            acc += wb[j] * wb[j];
            ++j;
        }
    }
    for (; i < na; ++i) acc += wa[i] * wa[i];
    for (; j < nb; ++j) acc += wb[j] * wb[j];
    return acc;
}

// Convenience for tests, diagnostics and CSV columns. std::sqrt is one of the
// three std:: float functions verified bit-identical across native and wasm
// (see portable_math.hpp), so this is safe in the sim path too — but the gate
// itself compares squared distances and never calls it.
inline float genomeDistance(const Genome& a, const Genome& b) {
    return std::sqrt(genomeDistanceSq(a, b));
}

// Soft gate (v0.24.0): does a pair at folded distance `d` clear a threshold
// `maxDist` (T) widened by a linear ramp of width `softWidth` (W), given the
// uniform `u` in [0, 1) the CALLER drew?
//
//   accept  iff  u * W < (T + W) - d
//
// The three properties the gate is built on:
//   * d <= T always accepts. u < 1 strictly (rng.unit() tops out at 1 - 2^-24),
//     so u*W < W <= (T + W) - d.
//   * d >= T + W never accepts, even at u == 0: the right-hand side is <= 0.
//   * in between, acceptance is linear in d — a ramp replacing the cliff at T.
//
// The first two hold EXACTLY when T + W is representable, which every value in
// the live window is (T and W are read off a 0.5-step spinner and the whole
// scale sits below 32, where quarters are exact). When it is not, fl(T + W)
// carries an error e of up to half an ulp of T + W — under 1e-6 at this scale —
// and the rails move by that much: at d within e of T, a draw within e/W of 1
// rejects. That is a deterministic, platform-independent corner (pure float
// arithmetic, so native and wasm agree on it bit for bit), it needs d to equal
// T to the last bit, and it is why the rails are stated against the fold's
// resolution rather than as absolutes.
//
// DETERMINISM. Pure math: the caller supplies u, so this function draws
// NOTHING and does not violate this file's no-rng contract — the single
// rng.unit() per gate evaluation lives at the call site in world.hpp, where
// the draw discipline can be read next to the branch it feeds. No division and
// no transcendental: only +, -, * and a compare, all IEEE-exact and therefore
// bit-identical between native and wasm.
inline bool softGateAccepts(float d, float maxDist, float softWidth, float u) {
    return u * softWidth < (maxDist + softWidth) - d;
}

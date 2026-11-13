#pragma once
#include <vector>
#include <cmath>
#include <algorithm>
#include "vec2.hpp"

// ============================================================
// SpatialGrid — uniform spatial hash over a fixed [0,width) x [0,height)
// region. Drop-in replacement for the subset of QuadTree that World uses:
//
//     init(width, height, cellSize)   // once, in World::init
//     clear()                         // once per frame (retains capacity)
//     insert(pos, index)              // per entity per frame
//     build()                         // after the inserts, before any query
//     queryRadius(center, r, out)     // identical RESULT SET to QuadTree
//
// The entries live in ONE array ordered by cell (a compressed-sparse-row
// layout). build() is a stable counting sort, so every cell lists its entries
// in insertion order, and the cells of one grid row are adjacent, so a query
// scans each row of its cell rectangle as one contiguous run. That visits the
// same entries in the same order as walking the cells one at a time (which is
// what the vector-per-cell layout this replaced did), so every result list,
// and with it every simulation result, is unchanged bit for bit; it is faster
// because a row is one run of memory rather than one heap block per cell.
// A query touches only the rectangle of cells covering the query's bounding
// box, then distance-tests each point; the arrays are reused across frames,
// so the steady state does no per-frame heap allocation.
//
// queryRadius returns the same set of indices as QuadTree::queryRadius; only
// the ORDER differs (cell-iteration order vs tree-traversal order). All World
// call sites consume the result order-independently (sums / "set alive=false"
// / nearest-by-strict-<), so the set guarantee is what matters. This is
// asserted directly by the differential test in core_tests.
// ============================================================
class SpatialGrid {
public:
    void init(int width, int height, float cellSize) {
        width_   = width;
        height_  = height;
        invCell_ = 1.0f / cellSize;
        cols_    = static_cast<int>(width  * invCell_) + 1;
        rows_    = static_cast<int>(height * invCell_) + 1;
        const std::size_t cells = static_cast<std::size_t>(cols_) * rows_;
        start_.assign(cells + 1, 0);
        cursor_.assign(cells, 0);
        staged_.clear();
        entries_.clear();
    }

    // Forget the entries but keep every array's capacity.
    void clear() { staged_.clear(); }

    void insert(Vec2 pos, int index) {
        if (std::isnan(pos.x) || std::isnan(pos.y)) return;
        int cx = clampCol(static_cast<int>(pos.x * invCell_));
        int cy = clampRow(static_cast<int>(pos.y * invCell_));
        staged_.push_back({pos, index, cy * cols_ + cx});
    }

    // Lay the inserted entries out cell by cell: count per cell, prefix-sum
    // into each cell's start, then place them in insertion order.
    void build() {
        std::fill(start_.begin(), start_.end(), 0);
        for (const Staged& s : staged_) ++start_[s.cell + 1];
        const std::size_t cells = cursor_.size();
        for (std::size_t c = 0; c < cells; ++c) {
            start_[c + 1] += start_[c];
            cursor_[c] = start_[c];
        }
        entries_.resize(staged_.size());
        for (const Staged& s : staged_) entries_[cursor_[s.cell]++] = {s.pos, s.index};
    }

    void queryRadius(Vec2 center, float radius, std::vector<int>& results) const {
        // Cell rectangle covering [center - r, center + r]. floor() is
        // monotonic, so this rectangle is a guaranteed superset of every cell
        // that can hold a point within the radius; the per-point distance test
        // prunes it to the exact disk.
        const int minCx = clampCol(static_cast<int>((center.x - radius) * invCell_));
        const int maxCx = clampCol(static_cast<int>((center.x + radius) * invCell_));
        const int minCy = clampRow(static_cast<int>((center.y - radius) * invCell_));
        const int maxCy = clampRow(static_cast<int>((center.y + radius) * invCell_));
        collect(center.x, center.y, radius * radius, minCx, maxCx, minCy, maxCy, results);
    }

    // Toroidal radius query: the disk wraps across the world seam. Implemented
    // as up to 9 image queries — the query rect is translated by ±width/±height
    // and each translate is clipped against the world before its cells are
    // enumerated, so the padded last column/row is never touched and no cell
    // arithmetic goes modulo. Per-point distances are taken against the SHIFTED
    // centre, which for that image IS the minimum-image distance. With
    // radius < min(width, height)/2 (asserted by the caller's config) a point
    // can be inside the disk in at most one image, so no duplicates are
    // returned. The (0,0) image runs first, so away from the seam the result
    // order is identical to queryRadius.
    void queryRadiusWrapped(Vec2 center, float radius, std::vector<int>& results) const {
        static const int order[9][2] = {
            {0, 0}, {-1, -1}, {-1, 0}, {-1, 1}, {0, -1}, {0, 1}, {1, -1}, {1, 0}, {1, 1}};
        const float r2 = radius * radius;
        const float W = static_cast<float>(width_), H = static_cast<float>(height_);

        for (const auto& im : order) {
            const float cx0 = center.x + im[0] * W;
            const float cy0 = center.y + im[1] * H;
            // Clip the image's query rect against the world; skip empty clips.
            const float lox = cx0 - radius, hix = cx0 + radius;
            const float loy = cy0 - radius, hiy = cy0 + radius;
            if (hix < 0.0f || lox >= W || hiy < 0.0f || loy >= H) continue;

            const int minCx = clampCol(static_cast<int>(std::max(lox, 0.0f) * invCell_));
            const int maxCx = clampCol(static_cast<int>(std::min(hix, W) * invCell_));
            const int minCy = clampRow(static_cast<int>(std::max(loy, 0.0f) * invCell_));
            const int maxCy = clampRow(static_cast<int>(std::min(hiy, H) * invCell_));
            collect(cx0, cy0, r2, minCx, maxCx, minCy, maxCy, results);
        }
    }

    // The scans behind the two queries, handing each hit to a visitor instead
    // of a list: f(index, storedPos) for exactly the entries the query would
    // return, in the same order. storedPos is the position given to insert().
    template <class F>
    void forEachInRadius(Vec2 center, float radius, F&& f) const {
        const float r2 = radius * radius;

        // Cell rectangle covering [center - r, center + r]. floor() is
        // monotonic, so this rectangle is a guaranteed superset of every cell
        // that can hold a point within the radius; the per-point distance test
        // below prunes it to the exact disk.
        int minCx = clampCol(static_cast<int>((center.x - radius) * invCell_));
        int maxCx = clampCol(static_cast<int>((center.x + radius) * invCell_));
        int minCy = clampRow(static_cast<int>((center.y - radius) * invCell_));
        int maxCy = clampRow(static_cast<int>((center.y + radius) * invCell_));

        for (int cy = minCy; cy <= maxCy; ++cy) {
            const std::size_t rowBase = static_cast<std::size_t>(cy) * cols_;
            const Entry* e   = entries_.data() + start_[rowBase + minCx];
            const Entry* end = entries_.data() + start_[rowBase + maxCx + 1];
            for (; e != end; ++e) {
                float dx = e->pos.x - center.x;
                float dy = e->pos.y - center.y;
                if (dx * dx + dy * dy <= r2) f(e->index, e->pos);
            }
        }
    }

    template <class F>
    void forEachInRadiusWrapped(Vec2 center, float radius, F&& f) const {
        static const int order[9][2] = {
            {0, 0}, {-1, -1}, {-1, 0}, {-1, 1}, {0, -1}, {0, 1}, {1, -1}, {1, 0}, {1, 1}};
        const float r2 = radius * radius;
        const float W = static_cast<float>(width_), H = static_cast<float>(height_);

        for (const auto& im : order) {
            const float cx0 = center.x + im[0] * W;
            const float cy0 = center.y + im[1] * H;
            // Clip the image's query rect against the world; skip empty clips.
            const float lox = cx0 - radius, hix = cx0 + radius;
            const float loy = cy0 - radius, hiy = cy0 + radius;
            if (hix < 0.0f || lox >= W || hiy < 0.0f || loy >= H) continue;

            const int minCx = clampCol(static_cast<int>(std::max(lox, 0.0f) * invCell_));
            const int maxCx = clampCol(static_cast<int>(std::min(hix, W) * invCell_));
            const int minCy = clampRow(static_cast<int>(std::max(loy, 0.0f) * invCell_));
            const int maxCy = clampRow(static_cast<int>(std::min(hiy, H) * invCell_));

            for (int cy = minCy; cy <= maxCy; ++cy) {
                const std::size_t rowBase = static_cast<std::size_t>(cy) * cols_;
                const Entry* e   = entries_.data() + start_[rowBase + minCx];
                const Entry* end = entries_.data() + start_[rowBase + maxCx + 1];
                for (; e != end; ++e) {
                    const float dx = e->pos.x - cx0;
                    const float dy = e->pos.y - cy0;
                    if (dx * dx + dy * dy <= r2) f(e->index, e->pos);
                }
            }
        }
    }

    // Every entry of the cell rectangle covering the disk, in scan order, hit
    // or not: f(index, dx, dy, d2, hit) with dx, dy the entry's STORED position
    // minus the centre, d2 = dx * dx + dy * dy and hit = (d2 <= r2), the very
    // test and expressions queryRadius / forEachInRadius apply, so the hits, in
    // order, are exactly their result and a caller that acts on `hit` without
    // branching (a count, a gated minimum) sees what it would have seen from
    // them. Bounded world only (the wrapped queries shift the centre per image).
    template <class F>
    void forEachCandidate(Vec2 center, float radius, F&& f) const {
        const float r2 = radius * radius;
        const int minCx = clampCol(static_cast<int>((center.x - radius) * invCell_));
        const int maxCx = clampCol(static_cast<int>((center.x + radius) * invCell_));
        const int minCy = clampRow(static_cast<int>((center.y - radius) * invCell_));
        const int maxCy = clampRow(static_cast<int>((center.y + radius) * invCell_));
        for (int cy = minCy; cy <= maxCy; ++cy) {
            const std::size_t rowBase = static_cast<std::size_t>(cy) * cols_;
            const Entry* e   = entries_.data() + start_[rowBase + minCx];
            const Entry* end = entries_.data() + start_[rowBase + maxCx + 1];
            for (; e != end; ++e) {
                const float dx = e->pos.x - center.x;
                const float dy = e->pos.y - center.y;
                const float d2 = dx * dx + dy * dy;
                f(e->index, dx, dy, d2, d2 <= r2);
            }
        }
    }

    // How many indices queryRadius / queryRadiusWrapped would return.
    int countRadius(Vec2 center, float radius) const {
        int n = 0;
        forEachInRadius(center, radius, [&n](int, Vec2) { ++n; });
        return n;
    }
    int countRadiusWrapped(Vec2 center, float radius) const {
        int n = 0;
        forEachInRadiusWrapped(center, radius, [&n](int, Vec2) { ++n; });
        return n;
    }

private:
    struct Entry {
        Vec2 pos;
        int  index;
    };
    struct Staged {
        Vec2 pos;
        int  index;
        int  cell;
    };

    int   width_   = 0;
    int   height_  = 0;
    int   cols_    = 0;
    int   rows_    = 0;
    float invCell_ = 1.0f;
    std::vector<int>    start_;    // cells + 1: cell c is entries_[start_[c], start_[c + 1])
    std::vector<int>    cursor_;   // build() scratch, one per cell
    std::vector<Staged> staged_;   // this frame's inserts, in insertion order
    std::vector<Entry>  entries_;  // the same entries, ordered by cell

    int clampCol(int c) const { return c < 0 ? 0 : (c >= cols_ ? cols_ - 1 : c); }
    int clampRow(int r) const { return r < 0 ? 0 : (r >= rows_ ? rows_ - 1 : r); }

    // Append, in scan order, the index of every entry of the cell rectangle
    // within sqrt(r2) of (x0, y0). Each candidate's index is written and the
    // cursor advances only on a hit: the same list as push_back-if-hit, with
    // no branch on a test that passes about a third of the time at random
    // (a mispredict on a large share of candidates).
    void collect(float x0, float y0, float r2, int minCx, int maxCx, int minCy, int maxCy,
                 std::vector<int>& results) const {
        std::size_t candidates = 0;
        for (int cy = minCy; cy <= maxCy; ++cy) {
            const std::size_t rowBase = static_cast<std::size_t>(cy) * cols_;
            candidates += static_cast<std::size_t>(start_[rowBase + maxCx + 1] - start_[rowBase + minCx]);
        }
        const std::size_t first = results.size();
        results.resize(first + candidates);
        int* out = results.data() + first;
        std::size_t n = 0;
        for (int cy = minCy; cy <= maxCy; ++cy) {
            const std::size_t rowBase = static_cast<std::size_t>(cy) * cols_;
            const Entry* e   = entries_.data() + start_[rowBase + minCx];
            const Entry* end = entries_.data() + start_[rowBase + maxCx + 1];
            for (; e != end; ++e) {
                const float dx = e->pos.x - x0;
                const float dy = e->pos.y - y0;
                out[n] = e->index;
                n += (dx * dx + dy * dy <= r2);
            }
        }
        results.resize(first + n);
    }
};

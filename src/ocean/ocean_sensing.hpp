#pragma once

    // The pheromone column and the current: horizontal, as Classic (kept in
    // eye-only mode: they are not what the eye replaces). Each only when
    // `need` has it (the reads are const: no draw, no state; see stepFish).
    inline void OceanWorld::writeColumnSensors(const Fish& c, Vec2 fwd, Vec2 rht, float sensors[], ocean::SenseMask need) {
        using ocean::senseBit;
        if (need & senseBit(SIGNAL0)) sensors[SIGNAL0] = signals.read(c.pos);
        if (need & senseBit(SIGNAL0_FWD))
            sensors[SIGNAL0_FWD] = signals.readInDir(c.pos, fwd) - signals.readInDir(c.pos, {-fwd.x, -fwd.y});
        if (need & senseBit(SIGNAL0_LR))
            sensors[SIGNAL0_LR] = signals.readInDir(c.pos, rht) - signals.readInDir(c.pos, {-rht.x, -rht.y});
        if (!(need & ocean::kSenseCurrent)) return;
        // CURRENT_FWD / LR from the horizontal flow (ux, uy) here, each only if read.
        auto current = [&](float ux, float uy) {
            if (need & senseBit(CURRENT_FWD)) sensors[CURRENT_FWD] = evomath::tanhf((ux * fwd.x + uy * fwd.y) / 100.0f);
            if (need & senseBit(CURRENT_LR))  sensors[CURRENT_LR]  = evomath::tanhf((ux * rht.x + uy * rht.y) / 100.0f);
        };
        if (ocfg.walls) {
            // Glass walls: the wall flow's horizontal part here (0 with no current and no waves).
            Flow U;
            if (wallFlowOn()) U = wallFlowFast(c.pos, c.depth);
            current(U.x, U.y);
        } else if (flowE1()) {
            // E1: the water's horizontal flow here (deep current × f(d) + waves).
            const Flow U = flowFast(c.pos, c.depth);
            current(U.x, U.y);
        } else if (currentActive()) {
            Vec2 cur = currentExactAt(c.pos);
            current(cur.x, cur.y);
        } else {
            sensors[CURRENT_FWD] = 0.0f;
            sensors[CURRENT_LR]  = 0.0f;
        }
    }

    // The bounded food scan (cfg.toroidal off): every item within R of fish c
    // in 3-D, in the grid's visit order, as foodSeen_[0, n) — offset, d², grid
    // slot. One pass over the query's rows of cells (the grid's own runs, in its
    // order) takes each candidate's offset from c.pos, the query centre (dx =
    // x − c.pos.x, as the grid's 2-D test takes it), q2 = dx·dx + dy·dy (that
    // test's sum), dz, and d2 = q2 + dz·dz (dx·dx + dy·dy + dz·dz, the same
    // left-to-right sum); it writes the record and advances the list exactly
    // when the grid's 2-D test (q2 <= R²) and the 3-D test (!(d2 > R²): a NaN d²
    // passes, as it always has) both hold — no branch on either (each passes a
    // random-looking third to half of the time: a mispredict on a large share of
    // candidates). The kept records are what the grid's visitor saw, in its
    // order, with its arithmetic.
    inline int OceanWorld::foodWithin(const Fish& c, float R) {
        FoodSeen* out = foodSeenList();
        const float* fx = foodGrid_.xs();
        const float* fy = foodGrid_.ys();
        const float* fz = foodGrid_.depths();
        const float R2 = R * R;
        const float px = c.pos.x, py = c.pos.y, pz = c.depth;
        // Four candidates at a time (GCC / Clang vector extensions: SSE2 on
        // x86-64, SIMD128 under -msimd128): lane j runs candidate k + j's very
        // operations — IEEE single −, × and + in the same tree, no FMA
        // (-ffp-contract=off) and no relaxed SIMD — so its values are the scalar
        // loop's bits; the comparisons give 0 / −1 masks (the literal q2 <= R²
        // and !(d2 > R²)), and the lanes are written and kept one by one in lane
        // order, as the scalar loop would. The rest of a run (< 4) is scalar.
        typedef float v4f __attribute__((vector_size(16)));
        typedef int v4i __attribute__((vector_size(16)));
        const v4f PX = {px, px, px, px}, PY = {py, py, py, py}, PZ = {pz, pz, pz, pz};
        const v4f RR = {R2, R2, R2, R2};
        int n = 0;
        foodGrid_.forEachRun(c.pos, R, [&](int b, int e) {
            int k = b;
            for (; k + 4 <= e; k += 4) {
                v4f X, Y, Z;
                std::memcpy(&X, fx + k, sizeof X);
                std::memcpy(&Y, fy + k, sizeof Y);
                std::memcpy(&Z, fz + k, sizeof Z);
                const v4f dx = X - PX, dy = Y - PY;
                const v4f q2 = dx * dx + dy * dy;
                const v4f dz = Z - PZ;
                const v4f d2 = q2 + dz * dz;
                const v4i keep = (q2 <= RR) & ~(d2 > RR);   // −1 = kept
                for (int j = 0; j < 4; ++j) {
                    out[n] = {dx[j], dy[j], dz[j], d2[j], k + j};
                    n -= keep[j];
                }
            }
            for (; k < e; ++k) {
                const float dx = fx[k] - px, dy = fy[k] - py;
                const float q2 = dx * dx + dy * dy;
                const float dz = fz[k] - pz;
                const float d2 = q2 + dz * dz;
                out[n] = {dx, dy, dz, d2, k};
                n += (int)(q2 <= R2) & (int)!(d2 > R2);
            }
        });
        return n;
    }

    // The toroidal food scan, as foodWithin (the same list: every item within R
    // in 3-D, in the grid's visit order — here the nine images in their order).
    // Per candidate both of the old scan's tests, each with its own arithmetic:
    // the grid's 2-D test against the image's translated centre (cx0, cy0), and
    // the 3-D test on the scan's offset, the difference from c.pos wrapped by
    // wrapDelta's rule (d > W/2: d − W; d < −W/2: d + W; else d) — the two round
    // differently, so both stay (sense_edges, "wrapped filter"). The rule is
    // taken as a select between the three values wrapDelta returns, each
    // computed as it computes it: no branch, the same bits.
    //
    // Four candidates at a time, as foodWithin's (GCC / Clang vector
    // extensions: SSE2 on x86-64, SIMD128 under -msimd128): lane j runs
    // candidate k + j's very operations — the image offset gx = x − cx0 and its
    // q2 = gx·gx + gy·gy, the scan offset ux = x − px, the same IEEE single
    // −, × and + in the same tree, no FMA (-ffp-contract=off), no relaxed SIMD;
    // wrapDelta's select is a BITWISE select of the lane's three candidate
    // values (ux − W if ux > W/2, else ux + W if ux < −W/2, else ux — the
    // scalar's precedence), so a ±0 or NaN keeps its exact bits (an arithmetic
    // blend such as ux + 0 would turn −0 into +0); the two tests are the
    // literal masks q2 <= R² and !(d2 > R²) (a NaN d² passes the second, as it
    // always has; a NaN q2 fails the first). The lanes are written and kept one
    // by one in lane order, as the scalar loop would; the rest of a run (< 4)
    // is the scalar loop (food_scan holds both to the scalar definition).
    inline int OceanWorld::foodWithinWrapped(const Fish& c, float R) {
        FoodSeen* out = foodSeenList();
        const float* fx = foodGrid_.xs();
        const float* fy = foodGrid_.ys();
        const float* fz = foodGrid_.depths();
        const float R2 = R * R;
        const float px = c.pos.x, py = c.pos.y, pz = c.depth;
        const float W = (float)width, H = (float)height;
        const float hw = 0.5f * W, hh = 0.5f * H;   // wrapDelta's half = 0.5f · span
        typedef float v4f __attribute__((vector_size(16)));
        typedef int v4i __attribute__((vector_size(16)));
        const v4f PX = {px, px, px, px}, PY = {py, py, py, py}, PZ = {pz, pz, pz, pz};
        const v4f RR = {R2, R2, R2, R2};
        const v4f VW = {W, W, W, W}, VH = {H, H, H, H};
        const v4f HW = {hw, hw, hw, hw}, HH = {hh, hh, hh, hh};
        const v4f NHW = -HW, NHH = -HH;   // −hw, −hh: negation is exact, the scalar's −hw
        // m ? a : b, lane by lane, by bits (a vector cast between equal sizes is a bitcast)
        auto pick = [](v4i m, v4f a, v4f b) { return (v4f)(((v4i)a & m) | ((v4i)b & ~m)); };
        int n = 0;
        foodGrid_.forEachRunWrapped(c.pos, R, [&](int b, int e, float cx0, float cy0) {
            const v4f CX = {cx0, cx0, cx0, cx0}, CY = {cy0, cy0, cy0, cy0};
            int k = b;
            for (; k + 4 <= e; k += 4) {
                v4f X, Y, Z;
                std::memcpy(&X, fx + k, sizeof X);
                std::memcpy(&Y, fy + k, sizeof Y);
                std::memcpy(&Z, fz + k, sizeof Z);
                const v4f gx = X - CX, gy = Y - CY;            // the grid's 2-D test
                const v4f q2 = gx * gx + gy * gy;
                const v4f ux = X - PX, uy = Y - PY;            // the scan's offset, wrapped
                const v4f dx = pick(ux > HW, ux - VW, pick(ux < NHW, ux + VW, ux));
                const v4f dy = pick(uy > HH, uy - VH, pick(uy < NHH, uy + VH, uy));
                const v4f dz = Z - PZ;
                const v4f d2 = dx * dx + dy * dy + dz * dz;
                const v4i keep = (q2 <= RR) & ~(d2 > RR);    // −1 = kept
                for (int j = 0; j < 4; ++j) {
                    out[n] = {dx[j], dy[j], dz[j], d2[j], k + j};
                    n -= keep[j];
                }
            }
            for (; k < e; ++k) {
                const float gx = fx[k] - cx0, gy = fy[k] - cy0;   // the grid's 2-D test
                const float q2 = gx * gx + gy * gy;
                const float ux = fx[k] - px, uy = fy[k] - py;     // the scan's offset, wrapped
                const float dx = (ux > hw) ? ux - W : ((ux < -hw) ? ux + W : ux);
                const float dy = (uy > hh) ? uy - H : ((uy < -hh) ? uy + H : uy);
                const float dz = fz[k] - pz;
                const float d2 = dx * dx + dy * dy + dz * dz;
                out[n] = {dx, dy, dz, d2, k};
                n += (int)(q2 <= R2) & (int)!(d2 > R2);
            }
        });
        return n;
    }
    // foodSeen_ with room for a query's writes: one per candidate, the list
    // advancing only on a kept item, and an item is kept at most once (in a
    // wrapped query it can be a candidate twice, within R of one image only), so
    // a write lands at most at index entryCount().
    inline OceanWorld::FoodSeen* OceanWorld::foodSeenList() {
        const std::size_t need = (std::size_t)foodGrid_.entryCount() + 1;
        if (foodSeen_.size() < need) foodSeen_.resize(need);
        return foodSeen_.data();
    }

#ifdef EVO_OCEAN_EYE
    // Eye-only mode: the eye's half of computeSensors' neighbour, food and
    // predator loops — the same queries, every object within R in the same
    // visit order (so the same 18 inputs, ties included), none of the labeled
    // sums, the topological cut, the nearest-neighbour genome compare or the
    // long probe. Bin: EyeBin (nearest) or EyeSum (summed sectors). A cloaked
    // kind (eyeCode 8 / 16) is not queried at all: here its query feeds nothing
    // else (neighbors_ is scratch).
    template <class Bin>
    void OceanWorld::eyeScan(const Fish& c, int selfIdx, Vec2 fwd, Vec2 rht, Bin* eye) {
        const float R = cfg.perceptionRadius, R2 = R * R;
        if (!(ocfg.eyeCode & kEyeCodeNoFish)) {
            std::vector<int>& neighbors = neighbors_;
            neighbors.clear();
            if (cfg.toroidal) creatureGrid_.queryRadiusWrapped(c.pos, R, neighbors);
            else              creatureGrid_.queryRadius(c.pos, R, neighbors);
            for (int ni : neighbors) {
                if (ni == selfIdx) continue;
                const FishHot& other = hot_[ni];
                float dx = other.pos.x - c.pos.x;
                float dy = other.pos.y - c.pos.y;
                if (cfg.toroidal) { dx = wrapDx(dx); dy = wrapDy(dy); }
                const float dz = other.depth - c.depth;
                const float d2 = dx * dx + dy * dy + dz * dz;
                if (d2 > R2) continue;
                eyeSee(eye, fwd, rht, dx, dy, dz, d2, other.eyeSize, other.eyeCon, R);
            }
        }
        // k: the item's grid slot (its payload == food[index]'s); the offset
        // and d² as computeSensors' smell takes them (see there).
        const float* fcon = foodGrid_.eyeCons();
        auto look = [&](int k, float dx, float dy, float dz, float d2) {
            if (d2 > R2) return;
            eyeSee(eye, fwd, rht, dx, dy, dz, d2, ocean::kEyeFoodSize, fcon[k], R);
        };
        if (!(ocfg.eyeCode & kEyeCodeNoFood)) {   // the items within R, in the grid's visit order
            const int n = cfg.toroidal ? foodWithinWrapped(c, R) : foodWithin(c, R);
            const FoodSeen* s = foodSeen_.data();
            for (int j = 0; j < n; ++j) look(s[j].k, s[j].dx, s[j].dy, s[j].dz, s[j].d2);
        }
        for (std::size_t k = 0; k < predators.size(); ++k) {
            const OceanPredator& p = predators[k];
            float dx = p.pos.x - c.pos.x;
            float dy = p.pos.y - c.pos.y;
            if (cfg.toroidal) { dx = wrapDx(dx); dy = wrapDy(dy); }
            const float dz = p.depth - c.depth;
            const float d2 = dx * dx + dy * dy + dz * dz;
            if (d2 <= R2) eyeSee(eye, fwd, rht, dx, dy, dz, d2, ocean::kEyePredSize, predCon_[k], R);
        }
    }
#endif

    // need: the sensors the caller reads (stepFish: ocean::sensesRead of the
    // net, or every one when captured). A sensor in `need` gets exactly the
    // value it always had; one outside it may be left as it is (0, stepFish's
    // memset) and its work skipped — a whole group's scan when no sensor of
    // the group is in `need` (ocean::kSense*), else a single sensor's
    // transcendental or grid reads. None of the skipped work draws from the
    // rng or writes state (const reads of the grids, signals, flow and other
    // fish; scratch lists): RANDOM_SENSOR is drawn always, last, as before.
    // The eye (Eye) keeps every scan it bins objects from.
    template <bool Eye, bool Labels, bool Sum>
    void OceanWorld::computeSensors(const Fish& c, int selfIdx, float sensors[], ocean::SenseMask need) {
        using ocean::senseBit;
        const Vec2 fwd = c.forward();
        const Vec2 rht = {-fwd.y, fwd.x};
        const float R = cfg.perceptionRadius, R2 = R * R;
#ifdef EVO_OCEAN_EYE
        // The compound eye: filled by the neighbour, food and predator loops
        // below (every object within R, before any topological cut), written
        // at the end. Nearest object per sector, or (Sum) sums per sector.
        using Bin = std::conditional_t<Sum, EyeSum, EyeBin>;
        [[maybe_unused]] Bin eye[ocean::kEyeSectors];
        if constexpr (Eye) eyeInit(eye);
        // The cloaks (eyeCode 8 / 16): the eye skips that kind's objects; the
        // labeled senses below still use them.
        [[maybe_unused]] const bool eyeFish = !(ocfg.eyeCode & kEyeCodeNoFish);
        [[maybe_unused]] const bool eyeFood = !(ocfg.eyeCode & kEyeCodeNoFood);
        // Whether the eye bins this step's fish / food (then their scans run
        // whatever `need` says).
        const bool eyeSeesFish = Eye && eyeFish, eyeSeesFood = Eye && eyeFood;
#else
        static_assert(!Sum, "summed sectors need the eye build");
        constexpr bool eyeSeesFish = false, eyeSeesFood = false;
#endif

        sensors[LOC_X] = c.pos.x / width;
        sensors[LOC_Y] = c.pos.y / height;
        if (cfg.toroidal) {
            sensors[BOUNDARY_DIST_X] = 1.0f;
            sensors[BOUNDARY_DIST_Y] = 1.0f;
            sensors[BOUNDARY_DIST] = 1.0f;
        } else if (need & ocean::kSenseBoundaryXY) {
            float bx = std::min(c.pos.x, (float)width - c.pos.x);
            float by = std::min(c.pos.y, (float)height - c.pos.y);
            sensors[BOUNDARY_DIST_X] = evomath::tanhf(bx / 100.0f);
            sensors[BOUNDARY_DIST_Y] = evomath::tanhf(by / 100.0f);
            sensors[BOUNDARY_DIST] = std::min(sensors[BOUNDARY_DIST_X], sensors[BOUNDARY_DIST_Y]);
        }

        sensors[OWN_VEL_X] = c.vel.x;
        sensors[OWN_VEL_Y] = c.vel.y;
        sensors[LAST_MOVE_DIR_X] = c.lastMoveDir.x;
        sensors[LAST_MOVE_DIR_Y] = c.lastMoveDir.y;
        // kernel::writeOwnStateSensors' five, its expressions verbatim, the
        // tanh / sine each only when read (ocean_tests "sense_dce" holds this
        // copy to the kernel's function bit for bit).
        sensors[OWN_SPEED] = c.speed / cfg.maxSpeed;
        if (need & senseBit(AGE)) sensors[AGE] = evomath::tanhf(c.age / 60.0f);
        if (need & senseBit(FOOD_RESERVES)) sensors[FOOD_RESERVES] = evomath::tanhf((c.foodReserves - 25.0f) / 25.0f);
        if (need & senseBit(OSCILLATOR)) sensors[OSCILLATOR] = c.getOscillator();
        sensors[RESPONSIVENESS] = c.responsiveness;

        // Depth: where am I, which way am I going, how far to surface / floor.
        sensors[LOC_Z] = c.depth / D;
        sensors[OWN_VEL_Z] = c.vz / ocfg.pitchMax;
        if (need & senseBit(BOUNDARY_DIST_Z))
            sensors[BOUNDARY_DIST_Z] = evomath::tanhf(std::min(c.depth, D - c.depth) / (0.25f * D));

#ifdef EVO_OCEAN_EYE
        if constexpr (!Labels) {
            // Eye-only mode: the labeled senses (ocean::kLabeledSenses) stay 0
            // (stepFish's memset) and are not computed; the eye, if on, looks.
            if constexpr (Eye) eyeScan(c, selfIdx, fwd, rht, eye);
            writeColumnSensors(c, fwd, rht, sensors, need);
            if constexpr (Eye) eyeWrite(eye, R, ocfg.eyeCode, sensors);
            sensors[RANDOM_SENSOR] = rng.range(-1.0f, 1.0f);
            return;
        }
#endif

        // ---- neighbours: (x, y) grid candidates, kept if within R in 3-D ----
        // The step's flags, read once per fish (a config change takes effect
        // between steps, never inside one).
        const bool tor = cfg.toroidal;
        // OceanConfig::labelFrame 1 (the A1 arm): the labeled food / neighbour
        // directions in the fish's own frame (x = right, y = ahead). Each
        // projected input reads BOTH world components of its vector (food's
        // foodDx and foodDy; the neighbours' avgDx and avgDy, avgHx and avgHy).
        // The skip never drops one of those: they are the scans' locals, every
        // one computed whenever its scan runs (a projected input is in its
        // scan's group, ocean::kSenseNeighbours / kSenseFood); only an OUTPUT is
        // gated, by its own bit. (ocean_tests "label_mask" holds the skip to
        // capture on under labelFrame 1, single-sensor and long runs.)
        const bool ownLabels = ocfg.labelFrame == 1;
        // The scan runs, as it always has, when a sensor of
        // ocean::kSenseNeighbours is read or the eye bins fish.
        if ((need & ocean::kSenseNeighbours) || eyeSeesFish) {
            std::vector<int>& neighbors = neighbors_;
            neighbors.clear();
            if (tor) creatureGrid_.queryRadiusWrapped(c.pos, R, neighbors);
            else     creatureGrid_.queryRadius(c.pos, R, neighbors);

            float avgDx = 0, avgDy = 0, avgDz = 0, avgHx = 0, avgHy = 0;
            float nearestDist = R;
            // The nearest's d² (+inf before one): sqrt is monotone, so a
            // neighbour whose d² is not below it has sqrt(d²) >= nearestDist and
            // cannot pass the strict test; only a smaller d² takes the sqrt and
            // that test (which still decides: distinct d² can share a sqrt).
            // As the food scan's foodD2 gate.
            float nearestD2 = std::numeric_limits<float>::infinity();
            int nearestIdx = -1, neighborCount = 0, popFwd = 0, popLR = 0, inRadiusCount = 0;

            auto attendTo = [&](int ni, const FishHot& other, float dx, float dy, float dz, float d2) {
                avgDx += dx; avgDy += dy; avgDz += dz;
                avgHx += other.vel.x; avgHy += other.vel.y;
                const float dotFwd = dx * fwd.x + dy * fwd.y;
                const float dotLR = dx * rht.x + dy * rht.y;
                popFwd += (dotFwd > 0) ? 1 : -1;
                popLR  += (dotLR > 0) ? 1 : -1;
                if (d2 < nearestD2) {
                    const float dist = std::sqrt(d2);
                    if (dist < nearestDist) { nearestDist = dist; nearestIdx = ni; nearestD2 = d2; }
                }
                neighborCount++;
            };

            // The grid's candidates within R in 3-D, by their hot_ state, in list
            // order (as foodWithin, the 3-D test and the self test without a branch):
            // each candidate's offset and d² are written, the list advancing exactly
            // for another fish with !(d2 > R²). hot_ does not change while one fish
            // senses, so these are the values the loops below would have read.
            if (foodSeen_.size() < neighbors.size() + 1) foodSeen_.resize(neighbors.size() + 1);
            FoodSeen* kept = foodSeen_.data();
            int nKept = 0;
            for (int ni : neighbors) {
                const FishHot& other = hot_[ni];
                float dx = other.pos.x - c.pos.x;
                float dy = other.pos.y - c.pos.y;
                if (tor) { dx = wrapDx(dx); dy = wrapDy(dy); }
                const float dz = other.depth - c.depth;
                const float d2 = dx * dx + dy * dy + dz * dz;
                kept[nKept] = {dx, dy, dz, d2, ni};
                nKept += (int)(ni != selfIdx) & (int)!(d2 > R2);
            }

            if (cfg.maxNeighbors <= 0) {
                for (int j = 0; j < nKept; ++j) {
                    const int ni = kept[j].k;
                    const FishHot& other = hot_[ni];
                    const float dx = kept[j].dx, dy = kept[j].dy, dz = kept[j].dz, d2 = kept[j].d2;
#ifdef EVO_OCEAN_EYE
                    if constexpr (Eye) { if (eyeFish) eyeSee(eye, fwd, rht, dx, dy, dz, d2, other.eyeSize, other.eyeCon, R); }
#endif
                    attendTo(ni, other, dx, dy, dz, d2);
                }
                inRadiusCount = neighborCount;
            } else {
                // Topological: the nearest N by (3-D distance², index), a total order.
                const int keepMax = std::min(cfg.maxNeighbors, MAX_TOPOLOGICAL_NEIGHBORS);
                Candidate best[MAX_TOPOLOGICAL_NEIGHBORS];
                int have = 0;
                for (int j = 0; j < nKept; ++j) {
                    const int ni = kept[j].k;
                    [[maybe_unused]] const FishHot& other = hot_[ni];
                    const float dx = kept[j].dx, dy = kept[j].dy, dz = kept[j].dz, d2 = kept[j].d2;
                    ++inRadiusCount;
#ifdef EVO_OCEAN_EYE
                    if constexpr (Eye) { if (eyeFish) eyeSee(eye, fwd, rht, dx, dy, dz, d2, other.eyeSize, other.eyeCon, R); }
#endif
                    if (have == keepMax) {
                        const Candidate& worst = best[have - 1];
                        if (d2 > worst.distSq || (d2 == worst.distSq && ni > worst.index)) continue;
                    }
                    int at = (have < keepMax) ? have : have - 1;
                    while (at > 0) {
                        const Candidate& prev = best[at - 1];
                        if (prev.distSq < d2 || (prev.distSq == d2 && prev.index < ni)) break;
                        best[at] = prev;
                        --at;
                    }
                    best[at] = {d2, dx, dy, dz, ni};
                    if (have < keepMax) ++have;
                }
                for (int j = 0; j < have; ++j)
                    attendTo(best[j].index, hot_[best[j].index], best[j].dx, best[j].dy, best[j].dz,
                             best[j].distSq);
            }

            if (neighborCount > 0) {
                avgDx /= neighborCount; avgDy /= neighborCount; avgDz /= neighborCount;
                avgHx /= neighborCount; avgHy /= neighborCount;
            }
            sensors[NEIGHBOR_COUNT] = tanhCountOver10(inRadiusCount);
            if (ownLabels) {   // projected BEFORE the tanh, from avgDx AND avgDy (see ownLabels)
                if (need & senseBit(AVG_NEIGHBOR_DX))
                    sensors[AVG_NEIGHBOR_DX] = evomath::tanhf((avgDx * rht.x + avgDy * rht.y) / R);
                if (need & senseBit(AVG_NEIGHBOR_DY))
                    sensors[AVG_NEIGHBOR_DY] = evomath::tanhf((avgDx * fwd.x + avgDy * fwd.y) / R);
            } else {
                if (need & senseBit(AVG_NEIGHBOR_DX)) sensors[AVG_NEIGHBOR_DX] = evomath::tanhf(avgDx / R);
                if (need & senseBit(AVG_NEIGHBOR_DY)) sensors[AVG_NEIGHBOR_DY] = evomath::tanhf(avgDy / R);
            }
            if (need & senseBit(AVG_NEIGHBOR_DZ)) sensors[AVG_NEIGHBOR_DZ] = evomath::tanhf(avgDz / R);
            if (ownLabels) {   // the mean neighbour velocity, from avgHx AND avgHy
                sensors[AVG_NEIGHBOR_HEADING_X] = avgHx * rht.x + avgHy * rht.y;
                sensors[AVG_NEIGHBOR_HEADING_Y] = avgHx * fwd.x + avgHy * fwd.y;
            } else {
                sensors[AVG_NEIGHBOR_HEADING_X] = avgHx;
                sensors[AVG_NEIGHBOR_HEADING_Y] = avgHy;
            }
            sensors[NEAREST_NEIGHBOR_DIST] = nearestDist / R;
            sensors[POPULATION_DENSITY] = tanhCountOver15(inRadiusCount);
            sensors[POPULATION_FWD] = tanhCountOver5(popFwd);
            sensors[POPULATION_LR] = tanhCountOver5(popLR);

            if (nearestIdx >= 0) {
                const Fish& nearest = creatures[nearestIdx];
                // kernel::writeNearestSensors' three, its expressions verbatim,
                // each only when read (the genome compare for either similarity
                // sensor; ocean_tests "sense_dce" holds this copy to the
                // kernel's function bit for bit).
                if (need & senseBit(NEAREST_NEIGHBOR_AGE))
                    sensors[NEAREST_NEIGHBOR_AGE] = evomath::tanhf((nearest.age - 50.0f) / 50.0f);
                if (need & senseBit(NEAREST_NEIGHBOR_FOOD))
                    sensors[NEAREST_NEIGHBOR_FOOD] = evomath::tanhf((nearest.foodReserves - 25.0f) / 25.0f);
                if (need & ocean::kSenseGeneticSim) {
                    // genomeSimilarity's count from the nets' gene-type masks
                    // (genome.hpp genomeSimilarityMasked): the same float.
                    const float sim = genomeSimilarityMasked(c.genome, c.nnet, nearest.genome, nearest.nnet);
                    sensors[GENETIC_SIM_NEAREST] = sim;
                    float dx = nearest.pos.x - c.pos.x;
                    float dy = nearest.pos.y - c.pos.y;
                    if (tor) { dx = wrapDx(dx); dy = wrapDy(dy); }
                    sensors[GENETIC_SIM_FWD] = (dx * fwd.x + dy * fwd.y > 0) ? sim : 0.5f;
                }
            } else {
                kernel::clearNearestSensors(sensors);
                sensors[GENETIC_SIM_FWD] = 0.5f;
            }
        }

        // ---- food: nearest within R in 3-D; DX/DY/DZ = the unit vector to it ----
        // foodD2 is the winner's d² (+inf before one): sqrt is monotone, so an
        // item with d² >= foodD2 has sqrt(d²) >= foodDist and cannot pass the
        // strict test below; only a smaller d² takes the sqrt and that test
        // (which still decides: distinct d² can share a sqrt, e.g. 1 + 2^-23
        // and 1). NaN fails both. The count, the eye and the mouth gate run
        // for every item as before. The scan runs, as it always has, when a
        // sensor of ocean::kSenseFood is read or the eye bins food.
        if ((need & ocean::kSenseFood) || eyeSeesFood) {
            float foodDx = 0, foodDy = 0, foodDz = 0, foodDist = R;
            float foodD2 = std::numeric_limits<float>::infinity();
            int foodCount = 0;
            // The mouth gate, once per fish: its flag, and the size limit (the very
            // product kMouth · bodySize the test took per item).
            const bool mouthGate = ocfg.mouthGate;
            const float mouthMax = ocfg.kMouth * c.bodySize;
            // k: the item's grid slot, whose depth / size / eyeCon are food[index]'s
            // (copied at this step's build; food does not change in the per-fish
            // phase); (dx, dy, dz) its offset, d2 = dx·dx + dy·dy + dz·dz.
            const float* fsize = foodGrid_.sizes();
#ifdef EVO_OCEAN_EYE
            [[maybe_unused]] const float* fcon = foodGrid_.eyeCons();
#endif
            auto smell = [&](int k, float dx, float dy, float dz, float d2) {
                if (d2 > R2) return;
#ifdef EVO_OCEAN_EYE
                // The eye sees every item within R (size does not hide it; unless cloaked) ...
                if constexpr (Eye) { if (eyeFood) eyeSee(eye, fwd, rht, dx, dy, dz, d2, ocean::kEyeFoodSize, fcon[k], R); }
#endif
                // ... the smell senses only what this fish could swallow.
                if (mouthGate && fsize[k] > mouthMax) return;   // E1: not food for me
                ++foodCount;
                if (d2 < foodD2) {
                    const float dist = std::sqrt(d2);
                    if (dist < foodDist) {
                        foodD2 = d2;
                        foodDist = dist;
                        const float invD = (dist > 0.001f) ? 1.0f / dist : 0.0f;
                        foodDx = dx * invD; foodDy = dy * invD; foodDz = dz * invD;
                    }
                }
            };
            {
                // The items within R in the grid's visit order (foodWithin /
                // foodWithinWrapped, see there; both keep the grid's 2-D test). Bounded,
                // with the grid's own offset and q2 = dx·dx + dy·dy (taken against
                // the query centre c.pos, the very values the offset here was), so
                // d² = q2 + dz·dz is the same left-to-right sum; toroidal, with the
                // wrapped difference from c.pos. smell's d2 > R² test is then always false.
                const int n = tor ? foodWithinWrapped(c, R) : foodWithin(c, R);
                const FoodSeen* s = foodSeen_.data();
                for (int j = 0; j < n; ++j) smell(s[j].k, s[j].dx, s[j].dy, s[j].dz, s[j].d2);
            }
            if (ownLabels) {   // the unit vector's horizontal part, right / ahead, from foodDx AND foodDy (DZ as is)
                sensors[NEAREST_FOOD_DX] = foodDx * rht.x + foodDy * rht.y;
                sensors[NEAREST_FOOD_DY] = foodDx * fwd.x + foodDy * fwd.y;
            } else {
                sensors[NEAREST_FOOD_DX] = foodDx;
                sensors[NEAREST_FOOD_DY] = foodDy;
            }
            sensors[NEAREST_FOOD_DZ] = foodDz;
            sensors[NEAREST_FOOD_DIST] = foodDist / R;
            sensors[FOOD_DENSITY] = tanhCountOver10(foodCount);
        }

        // ---- pheromone column and current: horizontal, as Classic (E1: the 3-D flow) ----
        writeColumnSensors(c, fwd, rht, sensors, need);

        // ---- nearest predator within R in 3-D; bearing from its horizontal part ----
        // (when a predator sensor is read, or the eye is on: it sees every predator within R)
        if ((need & ocean::kSensePredator) || Eye) {
            float bestD2 = R2, ox = 0, oy = 0;
            bool seen = false;
            for (const OceanPredator& p : predators) {
                float dx = p.pos.x - c.pos.x;
                float dy = p.pos.y - c.pos.y;
                if (cfg.toroidal) { dx = wrapDx(dx); dy = wrapDy(dy); }
                const float dz = p.depth - c.depth;
                const float d2 = dx * dx + dy * dy + dz * dz;
                if (d2 < bestD2) { bestD2 = d2; ox = dx; oy = dy; seen = true; }
#ifdef EVO_OCEAN_EYE
                if constexpr (Eye)
                    if (d2 <= R2)
                        eyeSee(eye, fwd, rht, dx, dy, dz, d2, ocean::kEyePredSize,
                               predCon_[&p - predators.data()], R);
#endif
            }
            if (seen) {
                const float d = std::sqrt(bestD2);
                const float invD = (d > 1e-3f) ? 1.0f / d : 0.0f;
                const float ux = ox * invD, uy = oy * invD;
                sensors[PREDATOR_FWD]  = ux * fwd.x + uy * fwd.y;
                sensors[PREDATOR_LR]   = ux * rht.x + uy * rht.y;
                sensors[PREDATOR_PROX] = 1.0f - d / R;
            } else {
                sensors[PREDATOR_FWD] = sensors[PREDATOR_LR] = sensors[PREDATOR_PROX] = 0.0f;
            }
        }

        // ---- long probe: fish within 30 (horizontally) and ±30 (depth) of a
        // point 200 ahead at my own depth (when read) ----
        if (need & senseBit(LONGPROBE_POP_FWD)) {
            int probeCount = 0;
            Vec2 probePos = {c.pos.x + fwd.x * LONGPROBE_DIST, c.pos.y + fwd.y * LONGPROBE_DIST};
            auto probe = [&](int ni, Vec2) { probeCount += (std::abs(hot_[ni].depth - c.depth) <= 30.0f); };
            if (cfg.toroidal) {
                probePos = {wrapCoord(probePos.x, (float)width), wrapCoord(probePos.y, (float)height)};
                creatureGrid_.forEachInRadiusWrapped(probePos, LONGPROBE_RADIUS, probe);
            } else {
                creatureGrid_.forEachInRadius(probePos, LONGPROBE_RADIUS, probe);
            }
            sensors[LONGPROBE_POP_FWD] = tanhCountOver5(probeCount);
        }

#ifdef EVO_OCEAN_EYE
        if constexpr (Eye) eyeWrite(eye, R, ocfg.eyeCode, sensors);   // off: stays 0 (stepFish's memset)
#endif

        sensors[RANDOM_SENSOR] = rng.range(-1.0f, 1.0f);   // drawn whether read or not: the stream
    }

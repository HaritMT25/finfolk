#pragma once

    inline OceanPredator OceanWorld::makePredator() {
        OceanPredator p;
        p.pos = {rng.range(10.0f, (float)width - 10.0f),
                 rng.range(10.0f, (float)height - 10.0f)};
        const float a = rng.range(0.0f, 6.2832f);
        p.vel = {evomath::cosf(a), evomath::sinf(a)};
        p.depth = rng.range(0.0f, D);
        p.energy = cfg.predatorNewbornEnergy;
        return p;
    }

    // Classic's predator hunt and Stage B economy (World::updatePredators), in
    // 3-D: detection and capture by 3-D distance, the chase steers in depth,
    // the wander drifts in depth.
    inline void OceanWorld::updatePredators(float dt) {
        if (predators.empty()) return;
        const bool  econ     = cfg.predatorEconomy;
        const float pmc      = (cfg.predatorMoveCost >= 0.0f) ? cfg.predatorMoveCost : cfg.moveCost;
        const float detect2  = cfg.predatorPerception * cfg.predatorPerception;
        const float capture2 = cfg.predatorCaptureRadius * cfg.predatorCaptureRadius;

        std::vector<OceanPredator> newborns;
        for (OceanPredator& p : predators) {
            const float speed    = cfg.predatorSpeed * p.speedFactor;
            const float burnRate = cfg.predatorMetabolism + pmc * speed * speed;
            p.digestTimer -= dt;
            if (econ) {
                p.age    += dt;
                p.energy -= burnRate * dt;
            }

            near_.clear();
            if (cfg.toroidal) creatureGrid_.queryRadiusWrapped(p.pos, cfg.predatorPerception, near_);
            else              creatureGrid_.queryRadius(p.pos, cfg.predatorPerception, near_);
            int   bestIdx = -1;
            float bestD2  = detect2;
            for (int ci : near_) {
                const Fish& prey = creatures[ci];
                if (!prey.alive) continue;
                const float d2 = dist2(p.pos, p.depth, prey.pos, prey.depth);
                if (d2 < bestD2) { bestD2 = d2; bestIdx = ci; }
            }

            Vec2 dir = p.forward();
            float hs = 1.0f, vr;   // horizontal share and depth rate, per unit speed
            if (bestIdx >= 0) {
                const Fish& prey = creatures[bestIdx];
                float dx = prey.pos.x - p.pos.x, dy = prey.pos.y - p.pos.y;
                if (cfg.toroidal) { dx = wrapDx(dx); dy = wrapDy(dy); }
                const float dz = prey.depth - p.depth;
                const float len = std::sqrt(dx * dx + dy * dy + dz * dz);
                const float inv = (len > 1e-6f) ? 1.0f / len : 0.0f;
                const float h = std::sqrt(dx * dx + dy * dy) * inv;
                if (h > 1e-6f) dir = normalized({dx, dy});
                hs = h;
                vr = dz * inv;
                p.pitch = std::clamp(vr, -0.3f, 0.3f);
            } else {
                const float jitter = rng.range(-0.3f, 0.3f);
                const float cs = evomath::cosf(jitter), sn = evomath::sinf(jitter);
                dir = {dir.x * cs - dir.y * sn, dir.x * sn + dir.y * cs};
                p.pitch = std::clamp(p.pitch + rng.range(-0.05f, 0.05f), -0.3f, 0.3f);
                vr = p.pitch;
            }
            if (ocfg.walls) wallAvoid(p.pos, dir, dt);   // glass walls: the soft turn (chase or wander alike; no draws)
            p.vel = dir;

            p.pos.x += dir.x * hs * speed * dt;
            p.pos.y += dir.y * hs * speed * dt;
            p.depth += vr * speed * dt;
            if (p.depth < 0.0f) { p.depth = 0.0f; p.pitch = std::abs(p.pitch); }
            else if (p.depth > D) { p.depth = D; p.pitch = -std::abs(p.pitch); }
            if (ocfg.walls) {
                // Glass walls: contact, the wall flow (weight 1), contact again;
                // a depth face reached by the flow turns the pitch inward.
                wallContact(p.pos, p.vel);
                if (wallFlowOn()) {
                    const Flow U = wallFlowFast(p.pos, p.depth);
                    p.pos.x += U.x * dt;
                    p.pos.y += U.y * dt;
                    p.depth += U.d * dt;
                }
                wallContact(p.pos, p.vel);
                if (p.depth <= 0.0f)   { p.depth = 0.0f; p.pitch = std::abs(p.pitch); }
                else if (p.depth >= D) { p.depth = D;    p.pitch = -std::abs(p.pitch); }
            } else {
                if (flowE1()) {
                    // E1: carried by the 3-D flow (weight 1), depth clamped after.
                    const Flow U = flowFast(p.pos, p.depth);
                    p.pos.x = wrapCoord(p.pos.x + U.x * dt, (float)width);
                    p.pos.y = wrapCoord(p.pos.y + U.y * dt, (float)height);
                    p.depth = clampDepth(p.depth + U.d * dt);
                } else if (currentActive()) {
                    const Vec2 cur = currentExactAt(p.pos);
                    p.pos.x += cur.x * dt;
                    p.pos.y += cur.y * dt;
                }
                p.pos.x = wrapPreview(p.pos.x, (float)width);
                p.pos.y = wrapPreview(p.pos.y, (float)height);
            }

            if (bestIdx >= 0 && p.digestTimer <= 0.0f && creatures[bestIdx].alive) {
                Fish& prey = creatures[bestIdx];
                if (dist2(p.pos, p.depth, prey.pos, prey.depth) <= capture2) {
                    if (econ) p.energy += (cfg.predatorMeal >= 0.0f) ? cfg.predatorMeal
                                                                     : prey.foodReserves;
                    recordDeath(prey, 'p');
                    p.digestTimer = cfg.predatorCooldown;
                }
            }

            if (econ) {
                if (p.energy < 0.0f) {
                    p.alive = false;
                    totalPredatorDeathsStarvation++;
                } else if (cfg.predatorMaxAge > 0.0f && p.age >= cfg.predatorMaxAge) {
                    p.alive = false;
                    totalPredatorDeathsAge++;
                } else if (p.energy >= cfg.predatorReproEnergy * p.buddingFactor &&
                           (cfg.predatorMaxPopulation <= 0 ||
                            (int)predators.size() + (int)newborns.size() < cfg.predatorMaxPopulation)) {
                    OceanPredator child;
                    if (cfg.toroidal) {
                        child.pos = { wrapCoord(p.pos.x + rng.range(-8.0f, 8.0f), (float)width),
                                      wrapCoord(p.pos.y + rng.range(-8.0f, 8.0f), (float)height) };
                    } else if (ocfg.walls) {   // the same two draws, mirror-folded inside the glass
                        child.pos = { mirrorFold(p.pos.x + rng.range(-8.0f, 8.0f), (float)width),
                                      mirrorFold(p.pos.y + rng.range(-8.0f, 8.0f), (float)height) };
                    } else {
                        child.pos = { std::clamp(p.pos.x + rng.range(-8.0f, 8.0f), 0.0f, (float)width  - 1.0f),
                                      std::clamp(p.pos.y + rng.range(-8.0f, 8.0f), 0.0f, (float)height - 1.0f) };
                    }
                    const float a = rng.range(0.0f, 6.2832f);
                    child.vel    = {evomath::cosf(a), evomath::sinf(a)};
                    child.depth  = ocfg.walls ? mirrorFold(p.depth + rng.range(-8.0f, 8.0f), D)
                                              : clampDepth(p.depth + rng.range(-8.0f, 8.0f));
                    child.energy = cfg.predatorNewbornEnergy;
                    p.energy    -= cfg.predatorNewbornEnergy;
                    child.generation = p.generation + 1;
                    if (cfg.predatorInheritance) {
                        const float m = cfg.predatorTraitMutation;
                        child.speedFactor   = std::clamp(p.speedFactor + rng.range(-m, m),
                                                         PRED_TRAIT_MIN, PRED_TRAIT_MAX);
                        child.buddingFactor = std::clamp(p.buddingFactor + rng.range(-m, m),
                                                         PRED_TRAIT_MIN, PRED_TRAIT_MAX);
                    }
                    newborns.push_back(child);
                    totalPredatorBirths++;
                }
            }
        }

        if (econ) {
            for (auto& baby : newborns) predators.push_back(std::move(baby));
            predators.erase(std::remove_if(predators.begin(), predators.end(),
                                           [this](const OceanPredator& p) { return removedDead(p); }),
                            predators.end());
        }
    }

    inline void OceanWorld::refillPredators() {
        while ((int)predators.size() < cfg.predatorMinPopulation) {
            predators.push_back(makePredator());
            totalPredatorReseeds++;
        }
    }

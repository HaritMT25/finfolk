#pragma once

namespace g2pr1 {

inline bool sameGenome(const Genome& a, const Genome& b) {
    if (a.size() != b.size()) return false;
    for (size_t i = 0; i < a.size(); ++i)
        if (checkpoint::packGene(a[i]) != checkpoint::packGene(b[i]) ||
            a[i].weight != b[i].weight)
            return false;
    return true;
}

// Frozen BASE operator: intentionally retains the original two additions.
inline void legacyReference(Genome& genome, float rate,
                            int minLen, int maxLen, RandomGen& r) {
    for (auto& gene : genome) {
        if (r.unit() < rate)
            gene.weight += static_cast<int16_t>(r.intRange(-1000, 1000));
        if (r.unit() < rate * 0.5f)
            gene = Gene::makeRandom(r);
    }
    if (r.unit() < rate * 2.0f && (int)genome.size() < maxLen) {
        int pos = r.intRange(0, (int)genome.size());
        genome.insert(genome.begin() + pos, Gene::makeRandom(r));
    }
    if (r.unit() < rate * 2.0f && (int)genome.size() > minLen) {
        int pos = r.intRange(0, (int)genome.size() - 1);
        genome.erase(genome.begin() + pos);
    }
    if (r.unit() < rate * 0.5f && (int)genome.size() < maxLen) {
        int src = r.intRange(0, (int)genome.size() - 1);
        Gene dup = genome[src];
        dup.weight += static_cast<int16_t>(r.intRange(-500, 500));
        genome.push_back(dup);
    }
}

inline void boundary(bool duplicate, bool positive) {
    const float rate = duplicate ? 0.1f : 0.25f;
    bool found = false;
    for (unsigned seed = 0; seed < 100000 && !found; ++seed) {
        RandomGen probe(seed);
        int delta = 0;
        if (!duplicate) {
            if (!(probe.unit() < rate)) continue;
            delta = probe.intRange(-1000, 1000);
            if (probe.unit() < rate * 0.5f) continue;
            (void)probe.unit(); // insertion: maxLen == size
            (void)probe.unit(); // deletion: minLen == size
            (void)probe.unit(); // duplication: maxLen == size
        } else {
            if (probe.unit() < rate) continue;
            if (probe.unit() < rate * 0.5f) continue;
            if (probe.unit() < rate * 2.0f) continue; // no insertion
            (void)probe.unit();                     // deletion at minimum
            if (!(probe.unit() < rate * 0.5f)) continue;
            (void)probe.intRange(0, 0);             // duplicate source draw
            delta = probe.intRange(-500, 500);
        }
        if (positive ? delta <= 0 : delta >= 0) continue;

        const int16_t edge = positive ? int16_t{32767} : int16_t{-32768};
        Gene gene{};
        gene.sourceType = SOURCE_SENSOR;
        gene.sourceNum = 127;
        gene.sinkType = SINK_ACTION;
        gene.sinkNum = 127;
        gene.weight = edge;
        Genome legacy{gene}, saturated{gene};
        RandomGen lr(seed), sr(seed);
        mutateGenome(legacy, rate, 1, duplicate ? 2 : 1, lr,
                     WeightMutationMode::Legacy);
        mutateGenome(saturated, rate, 1, duplicate ? 2 : 1, sr,
                     WeightMutationMode::Saturating);

        const size_t index = duplicate ? 1 : 0;
        CHECK(legacy.size() == (duplicate ? 2u : 1u));
        CHECK(saturated.size() == legacy.size());
        if (legacy.size() <= index || saturated.size() <= index) return;

        const int32_t sum = int32_t(edge) + delta;
        const int32_t wrapped =
            sum > 32767 ? sum - 65536 :
            sum < -32768 ? sum + 65536 : sum;
        CHECK(saturated[index].weight == edge);
        CHECK(legacy[index].weight == wrapped);
        CHECK(checkpoint::packGene(saturated[index]) ==
              checkpoint::packGene(gene));
        CHECK(lr.state() == sr.state());
        CHECK(sr.state() == probe.state());
        if (duplicate) {
            Genome interior{gene};
            interior[0].weight = 1234;
            RandomGen ir(seed);
            mutateGenome(interior, rate, 1, 2, ir, WeightMutationMode::Saturating);
            CHECK(interior.size() == 2);
            if (interior.size() == 2) CHECK(interior[1].weight == 1234 + delta);
            CHECK(ir.state() == probe.state());
            CHECK(legacy[0].weight == edge);
            CHECK(saturated[0].weight == edge);
        }
        found = true;
    }
    CHECK(found);
}

inline void mutationChecks() {
    CHECK(saturatingWeightAdd(32767, 1) == 32767);
    CHECK(saturatingWeightAdd(-32768, -1) == -32768);
    CHECK(saturatingWeightAdd(32767, -1000) == 31767);
    CHECK(saturatingWeightAdd(-32768, 1000) == -31768);

    boundary(false, true);
    boundary(false, false);
    boundary(true, true);
    boundary(true, false);

    for (unsigned seed = 0; seed < 256; ++seed) {
        RandomGen init(seed);
        const Genome original = makeRandomGenome(16, 80, init);
        for (float rate : {-0.1f, 0.0f, 0.002f, 0.01f, 0.05f, 0.5f, 3.0f}) {
            Genome actual = original, expected = original;
            RandomGen a(seed + 100000u), b(seed + 100000u);
            mutateGenome(actual, rate, 16, 80, a);
            legacyReference(expected, rate, 16, 80, b);
            CHECK(sameGenome(actual, expected));
            CHECK(a.state() == b.state());
        }
    }

    // Every selected point addition starts at zero. Rewiring follows it;
    // structural payloads are disabled by the equal bounds.
    for (unsigned seed = 0; seed < 1000; ++seed) {
        Genome a(16, Gene{}), b = a;
        RandomGen ar(seed), br(seed);
        mutateGenome(a, 0.5f, 16, 16, ar, WeightMutationMode::Legacy);
        mutateGenome(b, 0.5f, 16, 16, br, WeightMutationMode::Saturating);
        CHECK(sameGenome(a, b));
        CHECK(ar.state() == br.state());
    }

    // The birth kernel and predator wrapper must actually forward the policy.
    for (int sign : {-1, 1}) {
        AgentCore p1, p2;
        p1.genome.assign(16, Gene{});
        for (Gene& g : p1.genome)
            g.weight = sign > 0 ? int16_t{32767} : int16_t{-32768};
        p2.genome = p1.genome;
        bool preyDiff = false, predDiff = false;
        for (unsigned seed = 0; seed < 512; ++seed) {
            AgentCore l, s;
            rng.seed(seed);
            kernel::inheritGenome(l, p1, p2, 16, 80, 1.0f,
                                  WeightMutationMode::Legacy);
            const std::string afterLegacy = rng.state();
            rng.seed(seed);
            kernel::inheritGenome(s, p1, p2, 16, 80, 1.0f,
                                  WeightMutationMode::Saturating);
            CHECK(rng.state() == afterLegacy);
            preyDiff = preyDiff || !sameGenome(l.genome, s.genome);

            Predator parent, pl, ps;
            parent.genome = p1.genome;
            SimConfig lc, sc;
            sc.weightMutationMode = WeightMutationMode::Saturating;
            RandomGen lr(seed), sr(seed);
            predbrain::inheritGenome(pl, parent, lc, lr);
            predbrain::inheritGenome(ps, parent, sc, sr);
            CHECK(lr.state() == sr.state());
            predDiff = predDiff || !sameGenome(pl.genome, ps.genome);
        }
        CHECK(preyDiff);
        CHECK(predDiff);
    }
}

inline jsonm::Value& member(jsonm::Value& v, const char* key) {
    for (auto& kv : v.obj) if (kv.first == key) return kv.second;
    CHECK(false);
    return v;
}

inline void emit(jsonm::Writer& w, const jsonm::Value& v) {
    using T = jsonm::Value::Type;
    switch (v.type) {
    case T::Null: w.nullValue(); break;
    case T::Bool: w.value(v.b); break;
    case T::Number: w.value(v.num); break;
    case T::String: w.value(v.str); break;
    case T::Array:
        w.beginArray();
        for (const auto& e : v.arr) emit(w, e);
        w.endArray();
        break;
    case T::Object:
        w.beginObject();
        for (const auto& kv : v.obj) {
            w.key(kv.first.c_str());
            emit(w, kv.second);
        }
        w.endObject();
        break;
    }
}

inline jsonm::Value number(double x) {
    jsonm::Value v;
    v.type = jsonm::Value::Type::Number;
    v.num = x;
    return v;
}

inline jsonm::Value string(const char* x) {
    jsonm::Value v;
    v.type = jsonm::Value::Type::String;
    v.str = x;
    return v;
}

template <class Edit>
inline void rejectBeforeInit(const std::string& good, Edit edit) {
    jsonm::Value j;
    std::string error;
    CHECK(jsonm::Parser::parse(good, j, error));
    edit(j);
    std::string bad;
    jsonm::Writer writer(bad);
    emit(writer, j);

    rng.seed(909u);
    World sentinel;
    sentinel.init(640, 480, 3);
    const std::string before = checkpoint::serialize(sentinel, "sentinel");
    const std::string rngBefore = rng.state();
    const size_t capacityBefore = sentinel.creatures.capacity();

    CHECK(!checkpoint::deserialize(bad, sentinel, error));
    CHECK(!error.empty());
    CHECK(rng.state() == rngBefore);
    CHECK(sentinel.creatures.capacity() == capacityBefore);
    CHECK(checkpoint::serialize(sentinel, "sentinel") == before);
}

inline void malformedChecks() {
    rng.seed(5150u);
    World source;
    source.cfg.weightMutationMode = WeightMutationMode::Saturating;
    source.cfg.predatorBrain = true;
    source.cfg.predatorCount = 1;
    source.init(640, 480, 3);
    const std::string good = checkpoint::serialize(source, "test");

    for (const char* population : {"creatures", "predators"}) {
        for (double bad : {-1.0, 0.5, 2147483647.0, 1e100})
            rejectBeforeInit(good, [&](jsonm::Value& j) {
                member(member(j, population), "count") = number(bad);
            });

        for (double bad : {-1.0, 0.0, 15.0, 81.0, 16.5, 1e100})
            rejectBeforeInit(good, [&](jsonm::Value& j) {
                member(member(j, population), "genomeLengths").arr[0] =
                    number(bad);
            });

        rejectBeforeInit(good, [&](jsonm::Value& j) {
            member(member(j, population), "genomeLengths").arr[0] =
                string("24");
        });
        rejectBeforeInit(good, [&](jsonm::Value& j) {
            member(member(j, population), "genes").arr.pop_back();
        });

        for (double bad : {-1.0, 65536.0, 0.5, 1e100})
            rejectBeforeInit(good, [&](jsonm::Value& j) {
                member(member(j, population), "genes").arr[0] = number(bad);
            });

        for (double bad : {-32769.0, 32768.0, 0.5, 1e100})
            rejectBeforeInit(good, [&](jsonm::Value& j) {
                member(member(j, population), "genes").arr[1] = number(bad);
            });

        rejectBeforeInit(good, [&](jsonm::Value& j) {
            member(member(j, population), "neuronOutputs").arr.pop_back();
        });
        rejectBeforeInit(good, [&](jsonm::Value& j) {
            member(member(j, population), "neuronOutputs").arr[0] =
                number(std::numeric_limits<double>::infinity());
        });
    }

    for (const char* key :
         {"metadataVersion", "genomeVersion", "brainEvalVersion",
          "hiddenNeurons", "decoderVersion", "weightTableVersion",
          "predatorHiddenNeurons", "preySensorCount", "preyActionCount"})
        rejectBeforeInit(good, [&](jsonm::Value& j) {
            member(member(j, "brainPolicy"), key) = number(999);
        });

    for (const char* key :
         {"weightEncoding", "weightMutationMode", "wiringMode", "rewireMode",
          "genomeLengthMutationMode", "geneCostModel",
          "predatorGeneCostModel", "preySensorSet", "preyActionSet",
          "predatorSensorSet", "predatorActionSet"})
        rejectBeforeInit(good, [&](jsonm::Value& j) {
            member(member(j, "brainPolicy"), key) = string("unknown");
        });

    rejectBeforeInit(good, [](jsonm::Value& j) {
        member(j, "brainPolicy").obj.push_back({"unknownPolicy", number(1)});
    });
    rejectBeforeInit(good, [](jsonm::Value& j) {
        member(j, "brainPolicy").obj.erase(
            member(j, "brainPolicy").obj.begin());
    });
    rejectBeforeInit(good, [](jsonm::Value& j) {
        member(member(j, "brainPolicy"), "conversionProvenance") =
            string("converted");
    });
    rejectBeforeInit(good, [](jsonm::Value& j) {
        member(member(j, "config"), "weightMutationMode") = string("wrap");
    });
    rejectBeforeInit(good, [](jsonm::Value& j) {
        member(member(j, "config"), "weightMutationMode") = number(1);
    });
    rejectBeforeInit(good, [](jsonm::Value& j) {
        member(j, "config").obj.push_back(
            {"weightMutationMode", string("saturating")});
    });
    rejectBeforeInit(good, [](jsonm::Value& j) {
        member(member(j, "config"), "genomeMaxLength") = number(1e100);
    });
    rejectBeforeInit(good, [](jsonm::Value& j) {
        member(member(j, "config"), "predatorBrain").b = false;
    });
    for (double radius : {0.0, -1.0, 1e-40, 1e-8})
        rejectBeforeInit(good, [&](jsonm::Value& j) {
            member(member(j, "config"), "perceptionRadius") = number(radius);
        });
    // Individually representable sides, but overflowing signed cell products.
    rejectBeforeInit(good, [](jsonm::Value& j) {
        member(member(j, "world"), "width") = number(400000);
        member(member(j, "world"), "height") = number(400000);
    });
    rejectBeforeInit(good, [](jsonm::Value& j) {
        member(member(j, "config"), "perceptionRadius") = number(0.01);
    });
    for (const char* key : {"rngState", "predatorRngState"}) {
        rejectBeforeInit(good, [&](jsonm::Value& j) {
            member(j, key) = string("1 2 3");
        });
        rejectBeforeInit(good, [&](jsonm::Value& j) {
            member(j, key).str += " trailing";
        });
    }
}

#ifdef EVO_DETERMINISTIC
// Go through World::update, including its real pairing/budding call sites.
// Comparing separately seeded runs requires the serial build's RNG contract.
inline void worldBirthChecks() {
    Gene g{};
    g.sourceType = SOURCE_NEURON;
    g.sinkType = SINK_ACTION;
    g.sinkNum = INTERACT_REPRODUCE;
    g.weight = 32767;
    for (bool predator : {false, true}) {
        bool clipped = false;
        for (unsigned seed = 0; seed < 256 && !clipped; ++seed) {
            Genome children[2];
            std::string mainStates[2], predStates[2];
            for (int mode = 0; mode < 2; ++mode) {
                rng.seed(seed);
                World w;
                w.cfg.weightMutationMode = mode ? WeightMutationMode::Saturating : WeightMutationMode::Legacy;
                w.cfg.minPopulation = w.cfg.targetFood = 0;
                w.cfg.foodSpawnBase = w.cfg.foodSpawnAmp = w.cfg.metabolicRate = 0;
                w.cfg.genomeMinLength = w.cfg.genomeMaxLength = 16;
                w.cfg.genomeInitMin = w.cfg.genomeInitMax = 16;
                w.cfg.predatorBrain = w.cfg.predatorEconomy = predator;
                w.cfg.predatorCount = predator ? 1 : 0;
                w.cfg.predatorMetabolism = w.cfg.predatorMoveCost = 0;
                w.init(640, 480, predator ? 0 : 2);
                if (predator) {
                    auto& p = w.predators[0];
                    p.genome.assign(16, g);
                    predbrain::buildNet(p.genome, p.nnet);
                    p.energy = 1000;
                } else {
                    for (auto& c : w.creatures) {
                        c.genome.assign(16, g);
                        buildNeuralNet(c.genome, c.nnet);
                        c.pos = {320, 240};
                        c.age = 10;
                        c.foodReserves = 100;
                        c.reproTimer = c.interactTimer = 0;
                    }
                }
                w.update(0.016f);
                CHECK(predator ? w.predators.size() == 2 : w.creatures.size() == 3);
                if (predator && w.predators.size() == 2) children[mode] = w.predators.back().genome;
                if (!predator && w.creatures.size() == 3) children[mode] = w.creatures.back().genome;
                mainStates[mode] = rng.state();
                predStates[mode] = w.predRng_.state();
            }
            CHECK(mainStates[0] == mainStates[1]);
            CHECK(predStates[0] == predStates[1]);
            CHECK(children[0].size() == children[1].size());
            for (size_t i = 0; i < std::min(children[0].size(), children[1].size()); ++i)
                if (children[0][i].weight != children[1][i].weight) {
                    CHECK(children[1][i].weight == 32767);
                    CHECK(children[0][i].weight < 0);
                    CHECK(checkpoint::packGene(children[0][i]) == checkpoint::packGene(children[1][i]));
                    clipped = true;
                }
        }
        CHECK(clipped);
    }
}
#endif

inline void metadataChecks() {
    // Independent literals freeze the whole revision-1 descriptor, including
    // the inactive predator identities. Never derive this oracle from writer.
    const char* literals[] = {
        R"({"metadataVersion":1,"genomeVersion":1,"weightEncoding":"signed-int16-div8192","weightMutationMode":"saturating","wiringMode":"legacyModulo","biasGenes":false,"rewireMode":"fullReset","genomeLengthMutationMode":"legacy","brainEvalVersion":1,"hiddenNeurons":12,"decoderVersion":1,"weightTableVersion":0,"fastTanh":false,"geneCostModel":"linear","geneCostReference":80,"predatorGeneCostModel":"none","preySensorSet":"classic.prey.sensors.v1","preyActionSet":"classic.prey.actions.v1","preySensorCount":41,"preyActionCount":12,"predatorBrain":false,"predatorSensorSet":"none","predatorActionSet":"none","predatorSensorCount":0,"predatorActionCount":0,"predatorHiddenNeurons":0,"predatorSensorSetVersion":0,"conversionProvenance":null})",
        R"({"metadataVersion":1,"genomeVersion":1,"weightEncoding":"signed-int16-div8192","weightMutationMode":"saturating","wiringMode":"legacyModulo","biasGenes":false,"rewireMode":"fullReset","genomeLengthMutationMode":"legacy","brainEvalVersion":1,"hiddenNeurons":12,"decoderVersion":1,"weightTableVersion":0,"fastTanh":false,"geneCostModel":"linear","geneCostReference":80,"predatorGeneCostModel":"none","preySensorSet":"classic.prey.sensors.v1","preyActionSet":"classic.prey.actions.v1","preySensorCount":41,"preyActionCount":12,"predatorBrain":true,"predatorSensorSet":"classic.predator.sensors.v1","predatorActionSet":"classic.predator.actions.v1","predatorSensorCount":21,"predatorActionCount":2,"predatorHiddenNeurons":12,"predatorSensorSetVersion":1,"conversionProvenance":null})"
    };
    for (int brain = 0; brain < 2; ++brain) {
        SimConfig c;
        c.predatorBrain = brain;
        c.weightMutationMode = WeightMutationMode::Saturating;
        std::string text, error;
        jsonm::Writer w(text);
        w.beginObject(); checkpoint::v3::writeBrainPolicyV1(w, c); w.endObject();
        jsonm::Value actual, expected;
        CHECK(jsonm::Parser::parse(text, actual, error));
        CHECK(jsonm::Parser::parse(literals[brain], expected, error));
        CHECK(checkpoint::v3::sameValue(member(actual, "brainPolicy"), expected));
    }
    SimConfig c;
    c.weightMutationMode = WeightMutationMode::Saturating;
    c.predatorBrain = c.predatorPrimer = true;
    c.predatorCount = 1;
    c.genomeMinLength = c.genomeMaxLength = c.genomeInitMin = c.genomeInitMax = 1;
    CHECK(brainPolicyConfigError(c) != nullptr);
    c.predatorPrimer = false;
    CHECK(brainPolicyConfigError(c) == nullptr);
    c.predatorPrimer = true;
    c.weightMutationMode = WeightMutationMode::Legacy;
    CHECK(brainPolicyConfigError(c) == nullptr);
}

#ifdef EVO_DETERMINISTIC
inline void configure(World& w, bool brain, WeightMutationMode mode) {
    configureRichWorld(w);
    w.cfg.predatorBrain = brain;
    w.cfg.weightMutationMode = mode;
    if (brain) {
        w.cfg.predatorMeal = 14.0f;
        w.cfg.predatorMaxPopulation = 12;
        w.cfg.predatorMinPopulation = 2;
        w.cfg.predatorMaxAge = 30.0f;
        w.cfg.predatorInheritance = true;
    }
}

inline void continuationChecks() {
    for (bool brain : {false, true}) {
        for (WeightMutationMode mode :
             {WeightMutationMode::Legacy, WeightMutationMode::Saturating}) {
            rng.seed(5150u);
            World uninterrupted;
            configure(uninterrupted, brain, mode);
            uninterrupted.init(900, 700, 260);
            if (!brain && mode == WeightMutationMode::Saturating)
                for (int i = 0; i < 37; ++i) (void)uninterrupted.predRng_.uint();
            const std::string initialPredRng = uninterrupted.predRng_.state();
            for (int i = 0; i < 1500; ++i)
                uninterrupted.update(0.016f);
            const std::string saved =
                checkpoint::serialize(uninterrupted, "test");
            const int version = mode == WeightMutationMode::Saturating ?
                                3 : brain ? 2 : 1;
            CHECK(saved.find("\"formatVersion\":" +
                             std::to_string(version)) != std::string::npos);
            CHECK((saved.find("\"brainPolicy\"") != std::string::npos) ==
                  (mode == WeightMutationMode::Saturating));

            for (int i = 0; i < 400; ++i)
                uninterrupted.update(0.016f);
            const std::string expected =
                checkpoint::serialize(uninterrupted, "test");

            rng.seed(777u);
            World resumed;
            resumed.cfg.weightMutationMode =
                mode == WeightMutationMode::Legacy ?
                WeightMutationMode::Saturating : WeightMutationMode::Legacy;
            std::string error;
            CHECK(checkpoint::deserialize(saved, resumed, error));
            CHECK(resumed.cfg.weightMutationMode == mode);
            CHECK(resumed.cfg.predatorBrain == brain);
            if (!brain && mode == WeightMutationMode::Saturating)
                CHECK(resumed.predRng_.state() == initialPredRng);
            CHECK(checkpoint::serialize(resumed, "test") == saved);
            for (int i = 0; i < 400; ++i) resumed.update(0.016f);
            CHECK(checkpoint::serialize(resumed, "test") == expected);

            rng.seed(5150u);
            World repeated;
            configure(repeated, brain, mode);
            repeated.init(900, 700, 260);
            if (!brain && mode == WeightMutationMode::Saturating)
                for (int i = 0; i < 37; ++i) (void)repeated.predRng_.uint();
            for (int i = 0; i < 1900; ++i) repeated.update(0.016f);
            CHECK(checkpoint::serialize(repeated, "test") == expected);
        }
    }

    // A whole-world comparison with no possible clipping. Mutation payload
    // equivalence is additionally exercised above with active point mutations.
    std::vector<std::string> legacyFrames;
    for (WeightMutationMode mode :
         {WeightMutationMode::Legacy, WeightMutationMode::Saturating}) {
        rng.seed(42u);
        World w;
        w.cfg.weightMutationMode = mode;
        w.cfg.minPopulation = 0;
        w.cfg.maxPopulation = 20;
        w.cfg.metabolicRate = 0;
        w.cfg.targetFood = 0;
        w.cfg.foodSpawnBase = 0;
        w.cfg.foodSpawnAmp = 0;
        w.init(640, 480, 20);
        for (auto& c : w.creatures) {
            for (Gene& g : c.genome) g.weight = 0;
            buildNeuralNet(c.genome, c.nnet);
        }
        for (int i = 0; i < 300; ++i) {
            w.update(0.016f);
            World normalized = w;
            normalized.cfg.weightMutationMode = WeightMutationMode::Legacy;
            const std::string state = checkpoint::serialize(normalized, "test");
            if (mode == WeightMutationMode::Legacy)
                legacyFrames.push_back(state);
            else
                CHECK(state == legacyFrames[size_t(i)]);
        }
    }

    // Both old formats reject non-legacy, mistyped, and repeated policy keys.
    for (bool brain : {false, true}) {
        rng.seed(42u);
        World old;
        old.cfg.predatorBrain = brain;
        old.cfg.predatorCount = 1;
        old.init(640, 480, 3);
        const std::string legacy = checkpoint::serialize(old, "test");
        for (int kind = 0; kind < 3; ++kind)
            rejectBeforeInit(legacy, [&](jsonm::Value& j) {
                member(j, "config").obj.push_back({"weightMutationMode",
                    kind == 1 ? number(1) : string(kind == 2 ? "legacy" : "saturating")});
                if (kind == 2) member(j, "config").obj.push_back(
                    {"weightMutationMode", string("legacy")});
            });
    }

    {
        rng.seed(5150u);
        World donor;
        configure(donor, true, WeightMutationMode::Saturating);
        donor.init(900, 700, 260);
        const std::string donorText = checkpoint::serialize(donor, "test");

        World arena = donor;
        transplant::Options options;
        options.predatorsFrom = "donor.json";
        options.count = 1;
        options.assay = "frozen";
        std::string manifest, error;
        CHECK(transplant::apply(arena, options, donorText, manifest, error));

        World loaded;
        CHECK(checkpoint::deserialize(checkpoint::serialize(arena, "test"), loaded, error));
        for (bool allow : {false, true}) {
            options.allowMismatch = allow;
            for (bool reverse : {false, true}) {
                World receiver = donor, source = donor;
                (reverse ? source : receiver).cfg.weightMutationMode = WeightMutationMode::Legacy;
                const std::string before = checkpoint::serialize(receiver, "test");
                const std::string rngBefore = rng.state();
                CHECK(!transplant::apply(receiver, options, checkpoint::serialize(source, "test"), manifest, error));
                CHECK(error.find("different weight mutation policies") != std::string::npos);
                CHECK(checkpoint::serialize(receiver, "test") == before);
                CHECK(rng.state() == rngBefore);
            }
            World narrow;
            narrow.cfg = donor.cfg;
            narrow.cfg.genomeMinLength = narrow.cfg.genomeMaxLength = 16;
            narrow.cfg.genomeInitMin = narrow.cfg.genomeInitMax = 16;
            narrow.init(900, 700, 3);
            const std::string before = checkpoint::serialize(narrow, "test");
            const std::string rngBefore = rng.state();
            CHECK(!transplant::apply(narrow, options, donorText, manifest, error));
            CHECK(error.find("receiving bounds") != std::string::npos);
            CHECK(checkpoint::serialize(narrow, "test") == before);
            CHECK(rng.state() == rngBefore);
            CHECK(checkpoint::deserialize(before, loaded, error));
            CHECK(checkpoint::serialize(loaded, "test") == before);
        }
    }
}
#endif

} // namespace g2pr1

static void test_genome_v2_pr1() {
    std::printf("Genome v2 PR 1...\n");
    SimConfig defaults;
    CHECK(defaults.weightMutationMode == WeightMutationMode::Legacy);
    CHECK(defaults.dump().find("weightMutationMode") == std::string::npos);
    g2pr1::mutationChecks();
    g2pr1::malformedChecks();
    g2pr1::metadataChecks();
#ifdef EVO_DETERMINISTIC
    g2pr1::worldBirthChecks();
    g2pr1::continuationChecks();
#endif
}

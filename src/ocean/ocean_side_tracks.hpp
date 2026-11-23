#pragma once

    // ---- the appearance genome (read-only views; see the header comment) ----
    // appearanceFlags(): the parts kept this run (OceanConfig::appearance as of
    // init; 0 = off or broken). Records are in creature order, records[i]
    // owned by creatures[i] (ownerId == id) at every step boundary.
    inline int OceanWorld::appearanceFlags() const { return appearanceOn() ? appFlags_ : 0; }
    inline int OceanWorld::appearanceInitFlags() const { return appFlags_; }
    inline bool OceanWorld::appearanceBroken() const { return appBroken_; }
    inline std::uint64_t OceanWorld::appearanceKey() const { return appKey_; }
    inline const std::vector<appearance::Record>& OceanWorld::appearanceRecords() const { return app_; }
    inline const appearance::Stats& OceanWorld::appearanceStats() const { return appStats_; }
    // The side array matches `creatures` (off: it is empty).
    inline bool OceanWorld::appearanceConsistent() const {
        if (!appearanceOn()) return app_.empty();
        if (app_.size() != creatures.size()) return false;
        for (std::size_t i = 0; i < app_.size(); ++i)
            if (app_[i].ownerId != creatures[i].id) return false;
        return true;
    }
    // For a caller that appends a fish to `creatures` directly (tests, tools):
    // give creatures.back() its founder appearance (its own stream; no rng).
    // Call after markFounder. A no-op while appearance is off.
    inline void OceanWorld::attachFounderAppearance() {
        if (appearanceOn() && app_.size() + 1 == creatures.size()) appearanceAppendFounder();
        if (bodyPlanOn() && bodyOwners_.size() + 1 == creatures.size()) bodyPlanAppendFounder();   // (the body plan too)
    }

    // ---- the M2a body-plan preview (read-only views; see the header comment) ----
    // Each array is in creature order, element i owned by creatures[i] (owner
    // id == id) at every step boundary while bodyPlanEnabled().
    inline bool OceanWorld::bodyPlanInitEnabled() const { return bodyFlag_; }   // OceanConfig::bodyPlanPreviewEnabled at init
    inline bool OceanWorld::bodyPlanEnabled() const { return bodyPlanOn(); }     // on, and not broken
    inline bool OceanWorld::bodyPlanBroken() const { return bodyBroken_; }
    inline std::uint64_t OceanWorld::bodyPlanKey() const { return bodyKey_; }   // the physical stream's world key
    inline const std::vector<std::uint64_t>& OceanWorld::bodyPlanOwners() const { return bodyOwners_; }
    inline const std::vector<physical::Genes>& OceanWorld::bodyPlanGenes() const { return bodyGenes_; }
    inline const std::vector<bodyplan::BirthCoefficients>& OceanWorld::bodyPlanBirth() const { return bodyBirth_; }
    inline const physical::Stats& OceanWorld::bodyPlanStats() const { return bodyStats_; }
    // Bumped by every change to the arrays (an append, a compaction that
    // removed one, init, a break): exports repack only when it moved.
    inline std::uint64_t OceanWorld::bodyPlanRevision() const { return bodyRevision_; }
    inline std::uint64_t OceanWorld::bodyPlanUncompiled() const { return bodyUncompiled_; }   // compiles refused (stored as zeros)
    inline bool OceanWorld::bodyPlanConsistent() const {
        if (!bodyPlanOn()) return bodyOwners_.empty() && bodyGenes_.empty() && bodyBirth_.empty();
        const std::size_t n = creatures.size();
        if (bodyOwners_.size() != n || bodyGenes_.size() != n || bodyBirth_.size() != n) return false;
        for (std::size_t i = 0; i < n; ++i)
            if (bodyOwners_[i] != creatures[i].id) return false;
        return true;
    }
    inline physical::Inheritance OceanWorld::bodyPlanInheritance() const { return {ocfg.physicalMutation, ocfg.physicalNovelProbability}; }
    // The inheritance knobs as the next offspring will use them.
    inline appearance::Inheritance OceanWorld::appearanceInheritance() const {
        return {ocfg.patternMutation, ocfg.patternPhaseMutation, ocfg.patternNovelProbability,
                ocfg.morphologyMutation, ocfg.morphologyNovelProbability};
    }

    // ---- the appearance genome's maintenance (cosmetic: no rng, nothing the step reads) ----
    inline bool OceanWorld::appearanceOn() const { return appFlags_ != 0 && !appBroken_; }
    inline void OceanWorld::appearanceInit() {
        RandomGen probe = rng;   // a copy: the engine itself does not advance
        const std::uint64_t a = probe.uint(), b = probe.uint();
        appKey_ = appearance::mix64((a << 32) | b);
        appFlags_ = ocfg.appearance;
        appBroken_ = false;
        app_.clear();
        appStats_ = appearance::Stats{};
    }
    inline void OceanWorld::appearanceAppendFounder() {
        appearance::Record r;
        r.ownerId = creatures.back().id;
        appearance::makeFounder(appKey_, r.ownerId, appFlags_, r.genome);
        app_.push_back(r);
        ++appStats_.founders;
    }
    // The last n creatures are this step's newborns; parents[2k], [2k+1] their
    // parents' indices (unchanged until the compaction below).
    inline void OceanWorld::appearanceAppendNewborns(std::size_t n, const std::vector<std::uint32_t>& parents) {
        const appearance::Inheritance inh = appearanceInheritance();
        const std::size_t first = creatures.size() - n;
        for (std::size_t k = 0; k < n; ++k) {
            appearance::Record r;
            r.ownerId = creatures[first + k].id;
            std::uint8_t modes[appearance::kPatternGroups], mmodes[appearance::kMorphGroups];
            const appearance::Genome A = app_[parents[2 * k]].genome, B = app_[parents[2 * k + 1]].genome;
            appearance::makeOffspring(appKey_, r.ownerId, A, B, inh, appFlags_, r.genome, modes, mmodes);
            app_.push_back(r);
            appStats_.count(modes, mmodes, appFlags_);
        }
    }
    inline void OceanWorld::appearanceCompact() {
        std::size_t k = 0;
        for (std::size_t i = 0; i < creatures.size(); ++i)
            if (creatures[i].alive) app_[k++] = app_[i];
        app_.resize(k);
    }
    inline void OceanWorld::appearanceCheck() {
        if (appearanceOn() && !appearanceConsistent()) {
            appBroken_ = true;   // never re-bound or rebuilt: reported, and no longer kept
            app_.clear();
            app_.shrink_to_fit();
        }
    }

    // ---- the M2a body-plan preview's maintenance (diagnostic: no rng, nothing the step reads) ----
    inline bool OceanWorld::bodyPlanOn() const { return bodyFlag_ && !bodyBroken_; }
    inline void OceanWorld::bodyPlanInit() {   // after appearanceInit (its key)
        bodyKey_ = physical::worldKey(appKey_);
        bodyFlag_ = ocfg.bodyPlanPreviewEnabled;
        bodyBroken_ = false;
        bodyOwners_.clear(); bodyGenes_.clear(); bodyBirth_.clear();
        bodyStats_ = physical::Stats{};
        bodyUncompiled_ = 0;
        ++bodyRevision_;
    }
    // The body of creatures[i]: its appearance record (already appended), its
    // body parameters and its physical alleles.
    inline void OceanWorld::bodyPlanPush(std::size_t i, const physical::Genes& G) {
        bodyplan::BirthCoefficients b;
        if (!bodyplan::compile(app_[i].genome, creatures[i].bodySize, creatures[i].bodyElong, G, bodyplan::kGeometryLaw, b))
            ++bodyUncompiled_;   // (zeros: law 0 reads as unavailable)
        bodyOwners_.push_back(creatures[i].id);
        bodyGenes_.push_back(G);
        bodyBirth_.push_back(b);
    }
    inline void OceanWorld::bodyPlanAppendFounder() {   // creatures.back(), after its appearance record
        if (app_.size() != creatures.size()) { bodyPlanBreak(); return; }
        physical::Genes G;
        physical::makeFounder(bodyKey_, creatures.back().id, G);
        bodyPlanPush(creatures.size() - 1, G);
        ++bodyStats_.founders;
        ++bodyRevision_;
    }
    // The last n creatures are this step's newborns, their appearance records
    // appended; parents[2k], [2k+1] their parents' indices (unchanged until
    // the compaction).
    inline void OceanWorld::bodyPlanAppendNewborns(std::size_t n, const std::vector<std::uint32_t>& parents) {
        if (n == 0) return;
        if (app_.size() != creatures.size() || parents.size() != 2 * n) { bodyPlanBreak(); return; }
        const physical::Inheritance inh = bodyPlanInheritance();
        const std::size_t first = creatures.size() - n;
        for (std::size_t k = 0; k < n; ++k) {
            std::uint8_t modes[physical::kGroups];
            const physical::Genes A = bodyGenes_[parents[2 * k]], B = bodyGenes_[parents[2 * k + 1]];   // copies: the push may grow
            physical::Genes Q;
            physical::makeOffspring(bodyKey_, creatures[first + k].id, A, B, inh, Q, modes);
            bodyPlanPush(first + k, Q);
            ++bodyStats_.offspring;
            for (int g = 0; g < physical::kGroups; ++g) ++bodyStats_.mode[modes[g] & 3];
        }
        ++bodyRevision_;
    }
    inline void OceanWorld::bodyPlanCompact() {
        std::size_t k = 0;
        for (std::size_t i = 0; i < creatures.size(); ++i)
            if (creatures[i].alive) {
                bodyOwners_[k] = bodyOwners_[i];
                bodyGenes_[k] = bodyGenes_[i];
                bodyBirth_[k] = bodyBirth_[i];
                ++k;
            }
        if (k != bodyOwners_.size()) ++bodyRevision_;
        bodyOwners_.resize(k); bodyGenes_.resize(k); bodyBirth_.resize(k);
    }
    inline void OceanWorld::bodyPlanBreak() {   // never re-bound or rebuilt: reported, and no longer kept
        bodyBroken_ = true;
        bodyOwners_.clear(); bodyOwners_.shrink_to_fit();
        bodyGenes_.clear(); bodyGenes_.shrink_to_fit();
        bodyBirth_.clear(); bodyBirth_.shrink_to_fit();
        ++bodyRevision_;
    }
    inline void OceanWorld::bodyPlanCheck() {
        if (bodyPlanOn() && (!appearanceOn() || !bodyPlanConsistent())) bodyPlanBreak();
    }

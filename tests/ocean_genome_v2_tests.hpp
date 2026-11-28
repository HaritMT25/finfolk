#pragma once
#include "../src/core/genome_v2_conversion.hpp"
namespace ot {
inline void testGenomeV2() {
    Test t("genome_v2");
    // Snapshot the original objects themselves, including non-dumped members
    // and padding: a refused new policy must perform no destination writes.
    for (bool startV2 : {false, true}) {
        SimConfig savedSim;
        OceanConfig savedOcean;
        if (startV2) {
            savedSim.genomeVersion = savedSim.brainEvalVersion = 2;
            savedSim.biasGenes = true;
            savedSim.weightMutationMode = WeightMutationMode::Saturating;
        }
        savedSim.clusterMap = savedSim.reproLog = true;
        savedOcean.waveSpeed = 17;
        const std::string simBytes(reinterpret_cast<const char*>(&savedSim), sizeof savedSim);
        const std::string oceanBytes(reinterpret_cast<const char*>(&savedOcean), sizeof savedOcean);
        const auto dump = savedSim.dump();
        std::vector<const char*> refusals = {
            R"({"weightMutationMode":"bogus","targetFood":321,"waveSpeed":9})",
            R"({"genomeVersion":12,"targetFood":321,"waveSpeed":9})",
            R"({"genomeVersion":1,"genomeVersion":1})",
            R"({"hiddenNeurons":12,"hiddenNeurons":12})",
            R"({"brainEvalVersion":1,"brainEvalVersion":1})",
            R"({"biasGenes":false,"biasGenes":false})",
            R"({"hiddenNeurons":24})", R"({"biasGenes":1})",
            R"({"genomeVersion":2,"brainEvalVersion":1})",
            R"({"genomeVersion":2,"brainEvalVersion":2,"weightMutationMode":"invalid"})",
            R"({"genomeVersion":2,"brainEvalVersion":2,"weightMutationMode":"saturating","weightMutationMode":"saturating"})"
        };
        if (startV2) {
            for (const char* bad : {
                R"({"weightMutationMode":"legacy","targetFood":321})",
                R"({"genomeMaxLength":81})",
                R"({"mutationMultiplier":1e100,"targetFood":321})",
            }) refusals.push_back(bad);
        }
        for (const char* bad : refusals) {
            std::string why;
            t.expect(!readOceanJson(bad, savedSim, savedOcean, why) && !why.empty(),
                     "policy refusal reports error: %s", bad);
            t.expect(savedSim.dump() == dump &&
                         std::memcmp(&savedSim, simBytes.data(), sizeof savedSim) == 0 &&
                         std::memcmp(&savedOcean, oceanBytes.data(), sizeof savedOcean) == 0,
                     "policy refusal preserves all config bytes: %s", bad);
        }
    }
    // Outer staging must publish accepted updates, including legacy-only input.
    // A direct alias followed by unconditional assignment of the stale staged
    // copy discards the parsed SimConfig even though the reader succeeds.
    for (bool policyInput : {true, false}) {
        SimConfig sim; OceanConfig ocean; std::string why;
        const char* text = policyInput
            ? R"({"genomeVersion":2,"brainEvalVersion":2,"weightMutationMode":"saturating","targetFood":321,"waveSpeed":9})"
            : R"({"targetFood":321,"waveSpeed":9})";
        t.expect(readOceanJson(text, sim, ocean, why), "accepted staging fixture");
        t.expect(sim.targetFood == 321 && ocean.waveSpeed == 9 &&
                 sim.genomeVersion == (policyInput ? 2 : 1),
                 policyInput ? "accepted policy update publishes sim config"
                             : "accepted legacy update publishes both configs");
    }
    const char* policy=R"({"genomeVersion":2,"brainEvalVersion":2,"biasGenes":true,"weightMutationMode":"saturating","minPopulation":4,"maxPopulation":32})";
    SimConfig sc; OceanConfig oc; std::string error;
    t.expect(ofp::buildConfigs(policy,240,sc,oc,error),"v2 config: %s",error.c_str());
    OceanWorld w; rng.seed(37);w.cfg=sc;w.ocfg=oc;w.init(640,480,240,4);
    for (const auto& f:w.creatures) t.expect(f.genome.schema==brainSchema(sc)&&typeMasksMatch(f.genome,f.nnet),"founder schema/masks");
    w.creatures.clear(); w.update(.016f);
    t.expect(w.creatures.size()>=4,"reseed founders");
    for(const auto& f:w.creatures) t.expect(f.genome.schema==brainSchema(sc),"refill schema");
    const Fish a=w.creatures[0],b=w.creatures[1];
    const Fish child=makeChildFish(a,b,16,80,1,25,WeightMutationMode::Saturating);
    t.expect(child.genome.schema==brainSchema(sc)&&typeMasksMatch(child.genome,child.nnet),"child schema/masks");
    Gene bias{};bias.sourceNum=127;bias.sinkType=SINK_ACTION;bias.weight=logweight::store(16385);
    Genome g{bias};g.schema={2,true};NeuralNet n;buildNeuralNet(g,n);
    t.expect(!ocean::sensorReachesAction(n,0,0),"bias is not a hidden/sensor reachability index");
    float sensors[NUM_SENSES]={},actions[NUM_ACTIONS];feedForward(n,sensors,actions);
    t.expect(actions[0]==evomath::tanhf(1.f),"bias +1 source");
    // Full conversions also preserve appearance and physical side tracks.
    OceanWorld legacy;SimConfig c;applyOceanDefaults(c);c.minPopulation=0;legacy.cfg=c;legacy.init(640,480,240,4);
    const auto r=rng.state(),pr=legacy.predRng_.state();const auto id=legacy.creatures[0].lineageId;
    t.expect(convertWorldToGenomeV2(legacy,true,std::string(64,'b'),error),"Ocean conversion: %s",error.c_str());
    t.expect(rng.state()==r&&legacy.predRng_.state()==pr&&legacy.creatures[0].lineageId==id,"conversion RNG/state");
    SimConfig invalid=sc;invalid.genomeMaxLength=81;
    t.expect(!oceanSimConfigError(invalid).empty(),"general SimConfig policy validation");
#ifndef OCEAN_TESTS_NO_SHIM
    t.expect(oc_init(37,640,480,240,4,policy)==1,"v2 shim startup");
    t.expect(oc_genome_version()==2&&oc_bias_genes()==1&&oc_brain_eval_version()==2&&oc_weight_mutation_mode()==1,"actual policy exports");
    const auto before=ofp::fingerprint(*g_world);
    const auto rs=rng.state(),ps=g_world->predRng_.state();
    for(const char* bad:{R"({"genomeVersion":2,"brainEvalVersion":2,"weightMutationMode":"saturating","genomeMaxLength":80.5})",R"({"genomeVersion":2,"brainEvalVersion":2,"weightMutationMode":"saturating","hiddenNeurons":24})"}) {
        t.expect(oc_init(99,640,480,240,50,bad)==0,"invalid v2 startup refused");
        t.expect(ofp::fingerprint(*g_world)==before&&rng.state()==rs&&g_world->predRng_.state()==ps,"refusal preserves world and streams");
    }
#endif
}
}

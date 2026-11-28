#include <string>
#include <vector>
#include "genome_v2_test_helpers.hpp"
#include "../wasm/evo_wasm.cpp"
int main() {
    const std::string policy=R"("genomeVersion":2,"brainEvalVersion":2,"hiddenNeurons":12,"biasGenes":true,"weightMutationMode":"saturating")";
    const auto json="{"+policy+"}";
    G2_CHECK(evo_init(42,640,480,3,json.c_str())==1,"v2 startup accepted");
    const auto before=checkpoint::serialize(*g_world,"test");
    const auto rs=rng.state(),ps=g_world->predRng_.state();
    auto reject=[&](const std::string& bad){
        G2_CHECK(evo_init(99,640,480,100,bad.c_str())==0,"raw v2 startup refusal");
        G2_CHECK(checkpoint::serialize(*g_world,"test")==before&&rng.state()==rs&&g_world->predRng_.state()==ps,"startup destination and both RNG unchanged");
    };
    for(const char* key:{"genomeMinLength","genomeMaxLength","genomeInitMin","genomeInitMax","targetFood","predatorCount","reproWindow","currentEddies"}) {
        for(const char* bad:{"80.5","\"80\"","null","true","[]","{}","1e100","2147483648","-2147483649"}) reject("{"+policy+",\""+key+"\":"+bad+"}");
    }
    auto replaceMember=[&](const std::string& key,const std::string& value) {
        auto next=policy;
        const auto start=next.find("\""+key+"\":");
        G2_CHECK(start!=std::string::npos,"raw policy member exists");
        const auto end=next.find(',',start);
        next.replace(start,(end==std::string::npos?next.size():end)-start,"\""+key+"\":"+value);
        return "{"+next+"}";
    };
    for(const char* key:{"genomeVersion","hiddenNeurons","brainEvalVersion"}) {
        // One occurrence: truncation would produce a supported v2/H12 policy.
        reject(replaceMember(key,std::string(key)=="hiddenNeurons"?"12.5":"2.5"));
        for(const char* bad:{"\"2\"","null","1e100"}) reject(replaceMember(key,bad));
    }
    for(const char* key:{"genomeMaxLength","genomeMinLength"}) {
        reject("{"+policy+",\""+key+"\":"+(std::string(key)=="genomeMaxLength"?"81":"48")+"}");
    }
    reject(replaceMember("biasGenes","1"));
    reject(replaceMember("hiddenNeurons","24"));
    for(const char* key:{"genomeVersion","biasGenes","hiddenNeurons","brainEvalVersion","weightMutationMode"}) {
        G2_CHECK(evo_set_param(key,2)==0,"restart only policy");
        G2_CHECK(checkpoint::serialize(*g_world,"test")==before&&rng.state()==rs&&g_world->predRng_.state()==ps,"live policy refusal atomic");
    }
    G2_CHECK(evo_set_param("mutationMultiplier",2)==1,"valid v2 live update");
    G2_CHECK(evo_set_param("geneCost",1e100)==0,"v2 live finite policy");
    // Legacy parsing, including saturation-only fractional length truncation,
    // is deliberately preserved (the new policy is opt-in).
    G2_CHECK(evo_init(42,640,480,3,R"({"genomeMaxLength":80.5})")==1,"v1 lossy parsing retained");
    G2_CHECK(evo_init(42,640,480,3,R"({"genomeMaxLength":80.5,"weightMutationMode":"saturating"})")==1,"saturation only parsing retained");
    G2_CHECK(evo_init(42,640,480,3,R"({"weightMutationMode":"saturating","genomeMinLength":80,"genomeMaxLength":16,"genomeInitMin":48,"genomeInitMax":24})")==1,"v1 pre-policy normalization retained");
    G2_CHECK(g_world->cfg.genomeMinLength==16 && g_world->cfg.genomeMaxLength==80 &&
             g_world->cfg.genomeInitMin==24 && g_world->cfg.genomeInitMax==48,"v1 normalized config identity");
    std::puts("genome v2 frontend: all assertions passed");
}

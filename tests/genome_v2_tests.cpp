#include <array>
#include <limits>
#include "core/checkpoint_io.hpp"
#include "core/genome_v2_conversion.hpp"
#include "core/transplant.hpp"
#include "core/stats.hpp"
#include "core/predator_stats.hpp"
#include "genome_v2_test_helpers.hpp"
#define CHECK(x) G2_CHECK(x, "checkpoint preflight")
#include "checkpoint_test_helpers.hpp"

namespace {
SimConfig config(bool bias = true) {
    SimConfig c; c.genomeVersion = 2; c.biasGenes = bias; c.brainEvalVersion = 2;
    c.weightMutationMode = WeightMutationMode::Saturating; return c;
}
struct Event { char kind; int lo, hi; double value; };
struct Script {
    std::vector<Event> events; size_t at = 0;
    double next(char kind, int lo, int hi) {
        G2_CHECK(at < events.size(), "RNG transcript extra draw");
        const auto e = events[at++];
        G2_CHECK(e.kind == kind && e.lo == lo && e.hi == hi, "RNG transcript bounds/order"); return e.value;
    }
    unsigned uint(unsigned hi) { return static_cast<unsigned>(next('u', 0, int(hi))); }
    int intRange(int lo, int hi) { return static_cast<int>(next('i', lo, hi)); }
    float unit() { return static_cast<float>(next('f', 0, 1)); }
    void done() { G2_CHECK(at == events.size(), "RNG transcript omitted draw"); }
};
Event gate(double v) { return {'f',0,1,v}; }
Event u(int hi, int v) { return {'u',0,hi,double(v)}; }
Event integer(int lo, int hi, int v) { return {'i',lo,hi,double(v)}; }

template<int S, int A> void domain() {
    for (bool bias : {false, true}) {
        const BrainSchema schema{2,bias};
        for (int source = 0; source < S+12+(bias?1:0); ++source) {
            for (int sink = 0; sink < A+12; ++sink) {
                Genome g{g2Gene(source < S ? 1:0, source < S ? source : source==S+12 ? 127 : source-S,
                                sink < A ? 1:0, sink < A ? sink : sink-A, 16385 | ((source & 1)?32768:0))};
                g.schema = schema; NeuralNet n;
                G2_CHECK((buildCanonicalNet<S,A>(g,n)), "canonical packing build");
                const auto& fc=n.flat[0];
                G2_CHECK(fc.src() == source && fc.sink() == sink && fc.logCodec(), "tagged endpoint roundtrip");
                G2_CHECK(g2Same(Genome{asGene(fc,S,A)},Genome{g[0]}), "logical endpoint roundtrip");
                G2_CHECK(fc.srcSink == (0x8000 | source | (sink<<7)), "tagged raw packing");
                G2_CHECK(fc.w() == ((source&1)?-1.f:1.f), "tagged weight");
            }
        }
        Script random;
        if (bias) random.events.push_back(u(15,0));
        else {random.events.push_back(u(1,1));random.events.push_back(u(S-1,S-1));}
        random.events.push_back(u(1,1)); random.events.push_back(u(A-1,A-1)); random.events.push_back(u(65535,40960));
        const auto gene=makeCanonicalGene(random,schema,S,A);random.done();
        G2_CHECK(gene.sourceNum == (bias?127:S-1) && gene.sourceType==(bias?0:1) && gene.sinkNum==A-1 && gene.weight==16385, "canonical sampling");
        if (bias) {
            Script ordinary{{u(15,1),u(1,0),u(11,11),u(1,0),u(11,11),u(65535,32768)}};
            const auto x=makeCanonicalGene(ordinary,schema,S,A); ordinary.done();
            G2_CHECK(x.sourceNum==11 && x.sinkNum==11 && x.weight==0, "nonbias ticket");
        }
    }
}
// Serialize the complete object representation, including non-persisted settings.
std::string configBytes(const SimConfig& c) {
    return {reinterpret_cast<const char*>(&c), sizeof c};
}
void readerRefusals() {
    for (bool v2 : {false, true}) {
        SimConfig c = v2 ? config() : SimConfig{};
        c.clusterMap = c.reproLog = true;
        const auto before = configBytes(c);
        std::vector<const char*> cases = {
            R"({"config":{"hiddenNeurons":12.5}})",
            R"({"config":{"targetFood":321,"biasGenes":"yes"}})",
            R"({"config":{"targetFood":321,"weightMutationMode":"bogus"}})",
            R"({"config":{"targetFood":321,"genomeVersion":2,"brainEvalVersion":1}})"
        };
        if (v2) {
            cases.push_back(R"({"config":{"targetFood":321,"targetFood":321}})");
            cases.push_back(R"({"config":{"targetFood":321,"weightMutationMode":"legacy"}})");
            cases.push_back(R"({"config":{"targetFood":80.5}})");
            cases.push_back(R"({"config":{"targetFood":"80"}})");
        } else {
            cases.push_back(R"({"config":{"targetFood":321,"genomeVersion":2}})");
        }
        for (const char* text : cases) {
            jsonm::Value root; std::string error;
            G2_CHECK(jsonm::Parser::parse(text, root, error), "direct reader fixture parses");
            G2_CHECK(!checkpoint::readConfig(root, c, error) && !error.empty(), "direct reader refusal");
            G2_CHECK(configBytes(c) == before, "direct reader preserves every config byte");
            if (std::string(text).find("bogus") != std::string::npos)
                G2_CHECK(error == "weightMutationMode must be legacy or saturating", "unknown policy diagnostic");
            if (std::string(text).find("genomeVersion") != std::string::npos)
                G2_CHECK(error == "genomeVersion=2 requires brainEvalVersion=2", "incompatible evaluation diagnostic");
            if (std::string(text).find("targetFood\":321,\"targetFood") != std::string::npos)
                G2_CHECK(error == "repeated config member targetFood", "duplicate non-policy diagnostic");
            if (std::string(text).find("80.5") != std::string::npos)
                G2_CHECK(error == "targetFood must be a whole number that fits an int", "raw non-policy diagnostic");
        }
        if (!v2) {
            // Main's v1 reader accepts ordinary repeated members. Only the
            // targetFood field changes; policy and analysis settings survive.
            SimConfig accepted = c;
            c.targetFood = 321;
            jsonm::Value root; std::string error;
            G2_CHECK(jsonm::Parser::parse(R"({"config":{"targetFood":321,"targetFood":321}})", root, error), "v1 duplicate fixture parses");
            G2_CHECK(checkpoint::readConfig(root, accepted, error) && error.empty(), "v1 duplicate acceptance matches main");
            G2_CHECK(configBytes(accepted) == configBytes(c), "v1 duplicate exact config matches main");
        }
    }
}
void lateTransplantRefusal() {
    World w; w.cfg = config(); w.cfg.predatorBrain = false;
    w.cfg.predatorSpeed = 100; w.cfg.predatorMinSpeed = 101;
    w.init(640, 480, 3);
    G2_CHECK(!predatorBrainConfigError(w.cfg), "late transplant coherent receiver");
    const auto before = configBytes(w.cfg), worldBefore = checkpoint::serialize(w, "test");
    const auto rs = rng.state(), ps = w.predRng_.state();
    transplant::Options options; options.predatorsFrom = "random"; options.count = 1;
    std::string manifest, error;
    G2_CHECK(!transplant::apply(w, options, "", manifest, error), "late transplant refusal");
    G2_CHECK(error == "arena config: predatorMinSpeed must not exceed predatorSpeed", "late transplant reason");
    G2_CHECK(configBytes(w.cfg) == before && checkpoint::serialize(w, "test") == worldBefore &&
             rng.state() == rs && w.predRng_.state() == ps, "late transplant preserves config and RNG streams");
}
void lateConversionRefusal() {
    World w; w.cfg.predatorBrain = true; w.cfg.predatorCount = 2; w.init(640, 480, 3);
    // All prey and the first predator convert before the invalid last predator.
    w.predators.back().genome.clear();
    const auto before = checkpoint::serialize(w, "test"), cfgBefore = configBytes(w.cfg);
    const auto rs = rng.state(), ps = w.predRng_.state();
    std::string error;
    G2_CHECK(!convertWorldToGenomeV2(w, true, std::string(64, 'a'), error), "late conversion refusal");
    G2_CHECK(error == "invalid predator brain for conversion", "late conversion reason");
    G2_CHECK(checkpoint::serialize(w, "test") == before && configBytes(w.cfg) == cfgBefore &&
             rng.state() == rs && w.predRng_.state() == ps, "late conversion preserves serialized world");
}
void builders() {
    domain<41,12>(); domain<46,13>(); domain<64,13>(); domain<21,2>();
    Genome legacy{g2Gene(1,127,1,127,8192),g2Gene(0,127,0,127,32768)};
    NeuralNet net; G2_CHECK(buildNeuralNet(legacy,net), "legacy build");
    for (const auto& fc:net.flat) {
        const int src = fc.sink()<NUM_ACTIONS ? 127%NUM_SENSES : NUM_SENSES+127%12;
        const int sink = fc.sink()<NUM_ACTIONS ? 127%NUM_ACTIONS : NUM_ACTIONS+127%12;
        G2_CHECK(fc.srcSink == (src | sink<<6), "legacy packing");
        G2_CHECK(fc.w() == fc.weight/8192.f, "legacy codec");
    }
    Genome good{g2Gene(0,127,0,0,0)}; good.schema={2,true};
    G2_CHECK(buildNeuralNet(good,net), "bias builder");
    G2_CHECK(net.neurons[0].driven, "zero incoming drives");
    const auto before=net.flat; const auto hidden=net.neurons;
    for (auto bad : {g2Gene(1,NUM_SENSES,1,0,1),g2Gene(0,12,1,0,1),g2Gene(1,0,1,NUM_ACTIONS,1),g2Gene(1,0,0,12,1),g2Gene(1,0,1,0,32768),g2Gene(1,0,1,0,25602)}) {
        Genome g{bad};g.schema={2,true};
        G2_CHECK(!buildNeuralNet(g,net), "atomic canonical rejection");
        G2_CHECK(net.flat.size()==before.size() && net.flat[0].srcSink==before[0].srcSink && net.flat[0].weight==before[0].weight && net.neurons[0].driven==hidden[0].driven,"destination net unchanged");
    }
    good.schema.biasGenes=false;
    G2_CHECK(!buildNeuralNet(good,net), "disabled bias rejection");
    Genome g=makeRandomGenome(16,16,BrainSchema{2,true});
    G2_CHECK(buildNeuralNet(g,net)&&typeMasksMatch(g,net),"founder masks");
    mutateGenome(g,.7f,16,80,WeightMutationMode::Saturating);
    G2_CHECK(buildNeuralNet(g,net)&&typeMasksMatch(g,net),"mutation masks");
    Genome child=crossover(g,g);
    G2_CHECK((child.schema==BrainSchema{2,true}),"crossover schema");
    Genome assigned; assigned=child; Genome moved=std::move(assigned);
    G2_CHECK(moved.schema==child.schema,"copy move schema");
}
void oracle(const Genome& g, std::array<float,12>& hidden, const float* senses, float* actions, bool fast) {
    float sums[NUM_ACTIONS+12]={}; bool driven[12]={};
    const auto old=hidden;
    for (const auto& gene:g) {
        const float value=gene.sourceType ? senses[gene.sourceNum] : gene.sourceNum==127 ? 1.f : old[gene.sourceNum];
        const int sink=gene.sinkType ? gene.sinkNum : NUM_ACTIONS+gene.sinkNum;
        sums[sink]+=value*logweight::decodeValid(logweight::word(gene.weight));
        if (!gene.sinkType) driven[gene.sinkNum]=true;
    }
    for (int i=0;i<NUM_ACTIONS;++i) actions[i]=fast?fastTanhApprox(sums[i]):evomath::tanhf(sums[i]);
    for (int i=0;i<12;++i) if(driven[i]) hidden[i]=fast?fastTanhApprox(sums[NUM_ACTIONS+i]):evomath::tanhf(sums[NUM_ACTIONS+i]);
}
void recurrence() {
    Genome g{g2Gene(0,127,0,0,16385),g2Gene(0,0,0,0,16385),g2Gene(0,0,1,0,16385),
             g2Gene(1,0,1,1,25601),g2Gene(1,1,1,1,1),g2Gene(1,0,1,1,25601|32768),g2Gene(1,0,0,1,0)};
    g.schema={2,true};
    for(bool fast:{false,true}) {
        NeuralNet n;G2_CHECK(buildNeuralNet(g,n),"recurrence build");
        std::array<float,12> hidden;hidden.fill(.5f);
        float senses[NUM_SENSES]={};senses[0]=1;senses[1]=1;
        for(int step=0;step<8;++step){
            float want[NUM_ACTIONS],actual[NUM_ACTIONS];oracle(g,hidden,senses,want,fast);feedForward(n,senses,actual,fast);
            for(int i=0;i<NUM_ACTIONS;++i)G2_CHECK(g2Bits(actual[i],want[i]),"synchronous stable accumulation");
            for(int i=0;i<12;++i)G2_CHECK(g2Bits(n.neurons[i].output,hidden[i]),"bias driven retained recurrence");
        }
        G2_CHECK(n.neurons[2].output==.5f && n.neurons[1].output==0,"undriven retention and zero drives");
    }
    // Interaction calls are additional recurrent evaluations for both partners.
    Creature a,b;a.genome=g;b.genome=g;buildNeuralNet(g,a.nnet);buildNeuralNet(g,b.nnet);
    std::array<float,12> ha,hb;ha.fill(.5f);hb.fill(.5f);float sensors[NUM_SENSES]={},actions[NUM_ACTIONS];
    for(int i=0;i<2;++i){kernel::interactionVote(a,b);oracle(g,ha,sensors,actions,false);oracle(g,hb,sensors,actions,false);}
    for(int i=0;i<12;++i)G2_CHECK(g2Bits(a.nnet.neurons[i].output,ha[i])&&g2Bits(b.nnet.neurons[i].output,hb[i]),"contacts advance recurrence twice");
    // Predator scalar path snapshots and supplies the same constant.
    NeuralNet p;Genome pg{g2Gene(0,127,0,0,16385),g2Gene(0,0,1,0,16385)};pg.schema={2,true};
    G2_CHECK(predbrain::buildNet(pg,p),"predator canonical build");float ps[NUM_PRED_SENSES]={},pa[NUM_PRED_ACTIONS];
    predbrain::feedForward(p,ps,pa,false);G2_CHECK(g2Bits(pa[0],evomath::tanhf(.5f))&&g2Bits(p.neurons[0].output,evomath::tanhf(1.f)),"predator bias snapshot");
}
void mutation() {
    auto run=[](unsigned code,float rate,int min,int max,Script r,unsigned want,size_t length){
        Genome g{g2Gene(1,0,1,0,code)};g.schema={2,false};mutateGenomeV2(g,rate,min,max,r);r.done();
        G2_CHECK(g.size()==length&&logweight::word(g.back().weight)==want,"mutation result");
    };
    for(unsigned sign:{0u,32768u}) {
        run(25601|sign,.25f,1,1,{{gate(0),integer(-128,128,128),gate(1),gate(1),gate(1),gate(1),gate(1),gate(1)}},25601|sign,1);
        run(1|sign,.25f,1,1,{{gate(0),integer(-128,128,-128),gate(1),gate(1),gate(1),gate(1),gate(1),gate(1)}},1|sign,1);
        run(16385|sign,.25f,1,1,{{gate(0),integer(-128,128,17),gate(1),gate(1),gate(1),gate(1),gate(1),gate(1)}},16402|sign,1);
        run(0,.1f,1,1,{{gate(0),u(1,sign?1:0),gate(1),gate(1),gate(1),gate(1),gate(1),gate(1)}},12289|sign,1);
    }
    run(16385,.1f,1,1,{{gate(1),gate(0),gate(1),gate(1),gate(1),gate(1),gate(1)}},16385|32768,1);
    run(16385,.1f,1,1,{{gate(1),gate(1),gate(0),gate(1),gate(1),gate(1),gate(1)}},0,1);
    run(0,.1f,1,2,{{gate(1),gate(1),gate(1),gate(1),gate(1),gate(1),gate(0),integer(0,0,0),integer(-64,64,64)}},0,2);
    run(1,.1f,1,2,{{gate(1),gate(1),gate(1),gate(1),gate(1),gate(1),gate(0),integer(0,0,0),integer(-64,64,-64)}},1,2);
    run(1,-10,1,1,{{gate(0),gate(0),gate(0),gate(0),gate(0),gate(0),gate(0)}},1,1);
    run(1,10,1,1,{{gate(.9),integer(-128,128,128),gate(1),gate(1),gate(.9),gate(1),gate(1),gate(1)}},129,1);
    Genome g{g2Gene(1,0,1,0,1)};g.schema={2,true};
    Script r{{gate(1),gate(1),gate(1),gate(0),u(15,0),u(1,1),u(NUM_ACTIONS-1,0),u(65535,40960),
              gate(0),integer(0,1,1),u(15,1),u(1,1),u(NUM_SENSES-1,0),u(1,0),u(11,1),u(65535,32768),
              gate(0),integer(0,1,0),gate(0),integer(0,0,0),integer(-64,64,64)}};
    mutateGenomeV2(g,.1f,0,3,r);r.done();
    G2_CHECK(g.size()==2&&g[0].sourceType==1&&g[0].sinkNum==1&&g[0].weight==0&&g[1].weight==0,"full reset structural order");
}
void persistence() {
    rng.seed(21);World w;w.cfg=config();w.cfg.minPopulation=5;w.cfg.predatorBrain=true;w.cfg.predatorPrimer=true;w.cfg.predatorCount=2;
    w.init(640,480,5);
    for(const auto& c:w.creatures)G2_CHECK(c.genome.schema==brainSchema(w.cfg)&&typeMasksMatch(c.genome,c.nnet),"prey founder propagation");
    for(const auto& p:w.predators)G2_CHECK(p.genome.schema==brainSchema(w.cfg)&&p.genome[0].weight==logweight::store(logweight::quantizeLegacy(24576)),"predator founder primer");
    const auto good=checkpoint::serialize(w,"test");World restored;restored.cfg.clusterMap=true;restored.cfg.reproLog=true;std::string error;
    G2_CHECK(checkpoint::deserialize(good,restored,error),"v2 checkpoint roundtrip");
    G2_CHECK(checkpoint::serialize(restored,"test")==good,"v2 exact roundtrip bytes");
    G2_CHECK(restored.cfg.clusterMap&&restored.cfg.reproLog,"caller analysis settings retained");
    restored.cfg.clusterMap=false;restored.cfg.reproLog=false;
    // Only the serial engine promises seed/resume identity.
#if !defined(USE_OPENMP) && !defined(EVO_POOL_THREADS)
    auto r1=rng;auto r2=rng;
    for(int step=0;step<500;++step){rng=r1;w.update(.016f);r1=rng;rng=r2;restored.update(.016f);r2=rng;}
    G2_CHECK(checkpoint::serialize(w,"test")==checkpoint::serialize(restored,"test")&&r1.state()==r2.state()&&w.predRng_.state()==restored.predRng_.state(),"500 step continuation");
    #endif
    using namespace g2pr1;
    for (const char* key:{"genomeVersion","hiddenNeurons","brainEvalVersion","genomeMaxLength"}) rejectBeforeInit(good,[&](auto& j){member(member(j,"config"),key)=number(81);});
    for(double value:{-1.0,32768.0,25602.0,65535.0,65536.0,.5,1e100}) rejectBeforeInit(good,[&](auto& j){member(member(j,"creatures"),"genes").arr[1]=number(value);});
    rejectBeforeInit(good,[](auto& j){member(member(j,"creatures"),"genes").arr[0]=number(0xffff);});
    rejectBeforeInit(good,[](auto& j){member(member(j,"brainPolicy"),"metadataVersion")=number(1);});
    rejectBeforeInit(good,[](auto& j){member(member(j,"brainPolicy"),"weightTableSha256")=string("wrong");});
    rejectBeforeInit(good,[](auto& j){member(member(j,"creatures"),"genomeLengths").arr[0]=number(1e100);});
    rejectBeforeInit(good,[](auto& j){member(member(j,"creatures"),"genomeLengths").arr[0]=number(16);member(member(j,"creatures"),"genes").arr.pop_back();});
    rejectBeforeInit(good,[](auto& j){member(member(j,"config"),"biasGenes").type=jsonm::Value::Type::Null;});
    rejectBeforeInit(good,[](auto& j){auto& c=member(j,"config");c.obj.push_back(c.obj.front());});
    // Schema mismatch is hard even with the physics override.
    World receiver;receiver.cfg.minPopulation=0;receiver.init(640,480,3);
    transplant::Options options;options.allowMismatch=true; options.predatorsFrom="donor";
    const auto receiverBefore=checkpoint::serialize(receiver,"test");
    const auto rngBefore=rng.state(), predBefore=receiver.predRng_.state();
    std::string manifest;
    G2_CHECK(!transplant::apply(receiver,options,good,manifest,error),"transplant schema mismatch override");
    G2_CHECK(checkpoint::serialize(receiver,"test")==receiverBefore&&rng.state()==rngBefore&&receiver.predRng_.state()==predBefore,"transplant atomic refusal");
}
void conversion() {
    rng.seed(81);World w;w.cfg.minPopulation=0;w.cfg.predatorBrain=true;w.cfg.predatorCount=2;w.init(640,480,3);w.frame=12;
    for(auto& c:w.creatures)c.nnet.neurons[0].output=-.25f;
    const auto old=w.creatures;const auto ps=w.predRng_.state();const auto rs=rng.state();
    std::string error;const std::string sha(64,'a');
    G2_CHECK(convertWorldToGenomeV2(w,true,sha,error),"explicit conversion");
    G2_CHECK(rng.state()==rs&&w.predRng_.state()==ps,"conversion RNG unchanged");
    for(size_t i=0;i<old.size();++i){
        G2_CHECK(w.creatures[i].id==old[i].id&&w.creatures[i].lineageId==old[i].lineageId&&w.creatures[i].nnet.neurons[0].output==-.25f,"conversion state and lineage");
        for(size_t k=0;k<old[i].genome.size();++k){const auto& a=old[i].genome[k];const auto& b=w.creatures[i].genome[k];G2_CHECK(b.sourceNum==(a.sourceType?a.sourceNum%NUM_SENSES:a.sourceNum%12)&&b.weight==logweight::store(logweight::quantizeLegacy(a.weight)),"conversion canonical decoded endpoints");}
    }
    const auto text=checkpoint::serialize(w,"test");World r;
    G2_CHECK(checkpoint::deserialize(text,r,error)&&checkpoint::serialize(r,"test")==text,"conversion provenance roundtrip");
    G2_CHECK(!convertWorldToGenomeV2(w,true,sha,error),"no implicit reconversion");
    g2pr1::rejectBeforeInit(text,[](auto& j){g2pr1::member(g2pr1::member(g2pr1::member(j,"brainPolicy"),"conversionProvenance"),"sourceFrame")=g2pr1::number(13);});
    Genome bias{g2Gene(0,127,1,0,16385)};bias.schema={2,true};
    float sketch[CLUSTER_SKETCH_DIM];clusterSketch(bias,sketch);const auto color=genomeColor(bias);(void)color;
    G2_CHECK(std::isfinite(sketch[0])&&genomeDistanceSq(bias,bias)==0,"bias projections isolation");
    Genome v1;G2_CHECK(std::isinf(genomeDistanceSq(v1,bias)),"schema isolation");
    NeuralNet n;predbrain::buildNet(bias,n);float folded[predstats::kSrc*predstats::kSink];predstats::fold(n,folded);
    G2_CHECK(folded[33*predstats::kSink]==1,"predator bias fold");
}
}
int main(){readerRefusals();lateTransplantRefusal();lateConversionRefusal();builders();recurrence();mutation();persistence();conversion();std::puts("genome v2: all assertions passed");}

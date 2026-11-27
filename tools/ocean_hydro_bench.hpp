#pragma once
// Internal component evidence only. Production activation/lifecycle is PR 3.
#include <array>
#include <chrono>
#include <cstdio>
#include <malloc.h>
#include "ocean_hydro_harness.hpp"
#include "ocean_fingerprint.hpp"
namespace hydrobench {
using namespace hydro;
using Clock=std::chrono::steady_clock;
inline volatile double sink=0;
inline double elapsed(Clock::time_point t) {return std::chrono::duration<double,std::nano>(Clock::now()-t).count();}
inline double med(std::vector<double> v) {std::sort(v.begin(),v.end());return v[v.size()/2];}
} // namespace hydrobench
#include "ocean_hydro_memory.hpp"
namespace hydrobench {
inline void need(bool ok) {if(!ok)throw std::runtime_error("mechanics benchmark invariant failed");}
inline void needPopulation(const OceanWorld& w,const char* scenario,int rep,int completed) {
    if(w.creatures.size()==2000)return;
    std::fprintf(stderr,"POPULATION_FAILURE,scenario=%s,rep=%d,variant=1/legacy,completed_outer_steps=%d,"
        "phase=%s,population=%zu,expected=2000,frame=%llu,births=%lld,deaths=%lld,"
        "starvation=%lld,age=%lld,predation=%lld,grace_births=%lld,soft_births=%lld,reseeds=%lld,"
        "last_step_births=%d,last_step_deaths=%d,food=%zu,predators=%zu\n",
        scenario,rep,completed,completed<=100?"warmup":"measured",w.creatures.size(),static_cast<unsigned long long>(w.frame),
        w.totalBirths,w.totalDeaths,w.totalDeathsStarvation,w.totalDeathsAge,w.totalDeathsPredation,
        w.totalGraceBirths,w.totalSoftBirths,w.totalReseeds,w.births,w.deaths,w.food.size(),w.predators.size());
    std::fprintf(stderr,"POPULATION_CONFIG,metabolicRate=%.9g,moveCost=%.9g,geneCost=%.9g,maxAge=%.9g,"
        "reproEnergy=%.9g,minPopulation=%d,maxPopulation=%d,interactRadius=%.9g,interactCooldown=%.9g,"
        "cHold=%.9g,cPress=%.9g,toroidal=%d\n",w.cfg.metabolicRate,w.cfg.moveCost,w.cfg.geneCost,
        w.cfg.maxAge,w.cfg.reproEnergy,w.cfg.minPopulation,w.cfg.maxPopulation,w.cfg.interactRadius,
        w.cfg.interactCooldown,w.ocfg.cHold,w.ocfg.cPress,int(w.cfg.toroidal));
    need(false);
}
inline hydroharness::Columns make(const char* scenario) {
    hydroharness::Columns h;h.reserve(2000);h.config.toroidal=scenario[0]!='b';
    const auto body=hydroharness::body(scenario[0]=='b'?"noBladder":"neutral");
    for(int i=0;i<2000;++i) {
        need(h.add(body));auto& s=h.states.back();
        s.com[0]=float(20+(i%50)*35);s.com[2]=float(20+(i/50)*25);
        if(!h.config.toroidal) {
            Loaded L;need(loadAt(h.coefficients.back(),240,s,25,L));
            s.com[1]-=minimumGap(h.supports.back(),L,boundaries(h.config),s,5);
        }
    }
    need(h.owned());return h;
}
inline void advance(hydroharness::Columns& h,const HeldOuter& held) {
    // Ownership is checked once per whole loop, never N times per fish.
    need(h.owned());
    for(std::size_t i=0;i<h.fish.size();++i)
        need(stepHydro(h.coefficients[i],h.supports[i],h.config,held,h.fish[i].bodyBuoy,0,h.states[i],h.fish[i].foodReserves,nullptr));
}
template<class T> inline std::pair<std::size_t,std::size_t> column(const char* name,const std::vector<T>& v) {
    const auto bytes=v.capacity()*sizeof(T);
    const auto usable=v.empty()?0:malloc_usable_size(const_cast<T*>(v.data()));
    std::printf("MEM_COLUMN,name=%s,sizeof=%zu,size=%zu,capacity=%zu,capacity_B=%zu,allocator_usable_B=%zu,slack_B=%zu\n",
        name,sizeof(T),v.size(),v.capacity(),bytes,usable,usable-bytes);
    return {bytes,usable};
}
inline std::size_t physicsBytes(const hydroharness::Columns& h) {
    return h.coefficients.capacity()*sizeof(Coefficients)+h.supports.capacity()*sizeof(Support)+
        h.states.capacity()*sizeof(HydroState)+h.genes.capacity()*sizeof(physical::Genes)+h.owners.capacity()*8;
}
inline void memory(const hydroharness::Columns& h) {
    std::size_t bytes=0,usable=0;
    auto add=[&](auto v){bytes+=v.first;usable+=v.second;};
    add(column("coefficients",h.coefficients));add(column("support",h.supports));add(column("state",h.states));
    add(column("genes",h.genes));add(column("owner",h.owners));
    column("existing_Fish_excluded_from_physics_increment",h.fish);
    const auto copy=h;
    std::printf("MEM_TOTAL,live=%zu,slots=%zu,capacity_B=%zu,capacity_B_per_live=%.9g,capacity_B_per_slot=%.9g,"
        "allocator_usable_B=%zu,usable_B_per_live=%.9g,snapshot_plus_working_capacity_B=%zu,copy_reset_peak_usable_B=%zu,"
        "allocator_headers=reported_by_separate_allocator_probe,ceiling=1404\n",h.fish.size(),h.states.capacity(),bytes,
        double(bytes)/h.fish.size(),double(bytes)/h.states.capacity(),usable,double(usable)/h.fish.size(),
        bytes+physicsBytes(copy),2*usable);
    std::printf("MEM_WORKSPACE,Loaded=%zu,LDL6=%zu,ActuatorPlan=%zu,ContactReceipt=%zu,SubstepReceipt=%zu,StepReceipt=%zu,"
        "Diagnostics=%zu,BirthCoefficients=%zu,Points=%zu,Cells2=%zu,Material=%zu,allocationScratch=%zu,"
        "construction_stack=see_compiler_stack_usage_and_Wasm_stack_highwater,export_peak=one_diagnostic_and_one_serialized_record\n",
        sizeof(Loaded),sizeof(LDL6),sizeof(ActuatorPlan),sizeof(ContactReceipt),sizeof(SubstepReceipt),sizeof(StepReceipt),
        sizeof(Diagnostics),sizeof(bodyplan::BirthCoefficients),sizeof(bodyplan::Points),2*sizeof(bodymat::Cells),sizeof(bodymat::Material),
        (sizeof(int)+sizeof(float)+sizeof(bodymat::Taken))*std::size_t(bodymat::kCells));
    need(sizeof(Coefficients)<=1024&&sizeof(Support)<=256&&sizeof(HydroState)<=96&&double(usable)/h.fish.size()<=1404);
}
inline void auxiliary(const hydroharness::Columns& snap) {
    auto t=Clock::now();auto h=make("still");
    std::printf("AUX,construction_ns_per_fish=%.9g\n",elapsed(t)/2000);
    t=Clock::now();double sum=0;
    for(int repeat=0;repeat<5;++repeat)for(int i=0;i<2000;++i) {
        Coefficients c;Support s;Diagnostics d;
        const auto body=hydroharness::body();need(compile(body.G,body.S,body.E,body.P,Params{},c,s,&d)==kOk);
        // On-demand diagnostics and explicit record serialization, streamed one
        // fish at a time; no diagnostic column and no padding reads.
        std::array<std::uint32_t,kCoefficientFloats> exported{};int n=0;
        for(float x:floats(c))exported[n++]=std::bit_cast<std::uint32_t>(x);
        sum+=exported[repeat]+d.compoundMass;
    }
    sink=sum;std::printf("AUX,diagnostic_export_ns_per_fish=%.9g,serialized_record_B=%zu,diagnostic_plus_record_B=%zu\n",
        elapsed(t)/10000,sizeof(std::uint32_t)*kCoefficientFloats,sizeof(Diagnostics)+sizeof(std::uint32_t)*kCoefficientFloats);
    h=snap;t=Clock::now();
    for(int repeat=0;repeat<20;++repeat)for(int i=0;i<2000;++i) {
        ReserveReceipt r;
        need(changeReserve(h.coefficients[i],240,h.states[i],h.fish[i].foodReserves,-.001f,nullptr,r));
        need(h.refill(i));sum+=r.spent;
    }
    sink=sum;std::printf("AUX,reserve_loss_and_comoving_refill_ns_per_pair=%.9g\n",elapsed(t)/40000);
    h=snap;t=Clock::now();std::vector<bool> alive(2000,true);
    for(int i=0;i<64;++i)alive[i]=false;
    need(h.compact(alive));need(h.fish.size()==1936&&h.owners.front()==65);
    for(int i=0;i<64;++i)need(h.add(hydroharness::body()));
    need(h.owned()&&h.fish.size()==2000&&physicsBytes(h)<=2000*1404);
    std::printf("AUX,stable_compact64_birth64_ns=%.9g,capacity_B=%zu,owned=true,live=2000\n",elapsed(t),physicsBytes(h));
}
inline int main(int argc,char** argv) {
    try {
        bool memoryOnly=argc==2&&std::strcmp(argv[1],"--memory-only")==0;
        if(argc!=1&&!memoryOnly)throw std::runtime_error("usage: --mechanics-components [--memory-only]");
        // Force reference initialization before construction/memory accounting.
        need(references().ok);
        const auto allocatorBefore=allocatorBytes();const auto initial=make("still");
        const auto allocatorAfter=allocatorBytes();
        const auto requested=physicsBytes(initial)+initial.fish.capacity()*sizeof(Fish);
        std::printf("MEM_ALLOCATOR,all_six_column_requested_B=%zu,allocated_delta_B=%zu,overhead_B=%zu,"
            "physics_ceiling_charges_all_six_overhead=true\n",requested,allocatorAfter-allocatorBefore,allocatorAfter-allocatorBefore-requested);
        need(double(physicsBytes(initial)+(allocatorAfter-allocatorBefore-requested))/2000<=1404);
        memory(initial);
        if(memoryOnly){
            const auto construction=stackPeak(false),exporting=stackPeak(true);
            std::printf("MEM_STACK_HIGHWATER,construction_B=%zu,diagnostic_export_B=%zu,worker_runtime_included=true\n",construction,exporting);
            auxiliary(initial);return 0;
        }
        constexpr int warm=100,steps=200,reps=7;bool stable=true;
        std::printf("BENCH,pop=2000,warm=100,steps=200,reps=7,discarded=1,variants=A_internal/B_legacy/A_internal,"
            "profile=false,final_whole_world_M2_ratio=PR3,build_eye=%d\n",
#ifdef EVO_OCEAN_EYE
            1
#else
            0
#endif
        );
        for(const char* scenario:{"still","flow","boundary"}) {
            const auto snap=make(scenario);const auto rsnap=rng;
            HeldOuter held;held.requests.speed=scenario[0]=='b'?10:82;
            if(scenario[0]=='f')held.waterWorld={5,-1,2};
            OceanWorld legacy;std::string error;
            std::string config=
                "{\"targetFood\":0,\"foodSpawnBase\":0,\"foodSpawnAmp\":0,\"predatorCount\":0,\"minPopulation\":0,\"maxPopulation\":2000,\"metabolicRate\":0,\"moveCost\":0,\"geneCost\":0,\"reproEnergy\":1000000";
            // The fixed-population component control excludes social transfers:
            // zero metabolic costs alone do not prevent starvation after fights.
            config+=",\"interactRadius\":0";
            config+=scenario[0]=='b'?",\"toroidal\":false":",\"toroidal\":true";
            if(scenario[0]=='f')config+=",\"currentStrength\":5,\"currentMode\":1";
#ifdef EVO_OCEAN_EYE
            config+=",\"eye\":1";
#endif
            config+="}";
            need(ofp::initWorld(legacy,42,1920,1080,240,2000,config.c_str(),error));
            float minEnergy=std::numeric_limits<float>::infinity(),maxEnergy=0;
            for(const auto& f:legacy.creatures){minEnergy=std::min(minEnergy,f.foodReserves);maxEnergy=std::max(maxEnergy,f.foodReserves);}
            std::printf("LEGACY_SETUP,scenario=%s,seed=42,initial_reserve_min=%.9g,initial_reserve_max=%.9g,config=%s\n",
                scenario,minEnergy,maxEnergy,config.c_str());
            // No world activation/toggle: this control is the production legacy
            // world, whereas A is complete isolated mechanics+energy only.
            const OceanWorld legacySnap=legacy;const auto legacyRng=rng;
            std::array<std::vector<double>,3> times;
            for(int rep=-1;rep<reps;++rep)for(int order=0;order<3;++order) {
                const int variant=(rep+1+order)%3;double ns=0;
                if(variant==1) {
                    auto w=legacySnap;rng=legacyRng;
                    needPopulation(w,scenario,rep,0);
                    for(int i=0;i<warm;++i){w.update(kOuterDt);needPopulation(w,scenario,rep,i+1);}
                    const auto t=Clock::now();
                    for(int i=0;i<steps;++i){w.update(kOuterDt);needPopulation(w,scenario,rep,warm+i+1);}
                    ns=elapsed(t)/(steps*2000.);sink=w.creatures[0].foodReserves;
                    std::printf("LEGACY_LIFECYCLE,scenario=%s,rep=%d,completed_outer_steps=300,population=%zu,"
                        "births=%lld,deaths=%lld,reseeds=%lld\n",scenario,rep,w.creatures.size(),w.totalBirths,w.totalDeaths,w.totalReseeds);
                } else {
                    auto h=snap;rng=rsnap;
                    for(int i=0;i<warm;++i)advance(h,held);
                    const auto t=Clock::now();
                    for(int i=0;i<steps;++i)advance(h,held);
                    ns=elapsed(t)/(steps*2000.);sink=h.states[0].com[0];
                }
                std::printf("TIMING,scenario=%s,rep=%d,variant=%d,position=%d,outer=[100,300),ns_per_fish_step=%.12g\n",scenario,rep,variant,order,ns);
                std::fflush(stdout);if(rep>=0)times[variant].push_back(ns);
            }
            std::vector<double> aa,ht;
            for(int i=0;i<reps;++i){aa.push_back(times[2][i]/times[0][i]);ht.push_back(times[0][i]/times[1][i]);}
            const double variation=std::abs(med(aa)-1);stable=stable&&variation<=.03;
            std::printf("SUMMARY,scenario=%s,H_internal_ns=%.12g,T_legacy_ns=%.12g,paired_H_over_T=%.12g,"
                "paired_AA=%.12g,AA_deviation=%.12g,AA_limit=.03,R=unmeasured,L=PR3,net_addition=unestablished,allowance_ns=448\n",
                scenario,med(times[0]),med(times[1]),med(ht),med(aa),variation);
            std::fflush(stdout);
        }
        auxiliary(initial);return stable?0:1;
    } catch(const std::exception& e){std::fprintf(stderr,"mechanics benchmark: %s\n",e.what());return 2;}
}
} // namespace hydrobench

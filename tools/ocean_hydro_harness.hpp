#pragma once
// Internal assay ownership; separate aligned columns, no retained Loaded/plan.
#include <stdexcept>
#include <vector>
#include <string>
#include "ocean/hydro_step.hpp"
#include "ocean/fish.hpp"
#include "ocean_hydro_bodies.hpp"

namespace hydroharness {
using namespace hydro;
struct FixedReceipt {
    StepReceipt step{};
    ReserveReceipt source[2]{};
    float incomingEnergy[2]{};
    HydroState incomingState[2]{}; // tool-only, after the metered source transaction
};
struct Columns {
    std::vector<Coefficients> coefficients;
    std::vector<Support> supports;
    std::vector<HydroState> states;
    std::vector<physical::Genes> genes;
    std::vector<std::uint64_t> owners;
    std::vector<Fish> fish;
    StepConfig config{};
    RandomGen random{20261118u};
    double subsidy=0; // telemetry only; all simulation transactions binary32
    void reserve(std::size_t n) {
        coefficients.reserve(n); supports.reserve(n); states.reserve(n);
        genes.reserve(n); owners.reserve(n); fish.reserve(n);
    }
    bool owned() const {
        const auto n=fish.size();
        if(coefficients.size()!=n||supports.size()!=n||states.size()!=n||genes.size()!=n||owners.size()!=n) return false;
        for(std::size_t i=0;i<n;++i) if(owners[i]==0||owners[i]!=fish[i].id) return false;
        return true;
    }
    bool add(const hydrofix::Body& body,float energy=25,bool trim=true) {
        Coefficients c; Support support;
        if(!validConfig(config)||compile(body.G,body.S,body.E,body.P,Params{},c,support)!=kOk) return false;
        HydroState s=restState({config.width*.5f,-config.depth*.5f,config.height*.5f},{0,0,0},{1,0,0});
        Fish f; f.id=owners.empty()?1:owners.back()+1; f.foodReserves=0; f.bodyBuoy=.5f;
        f.bodySize=body.S; f.bodyElong=body.E;
        Parcel incoming; incoming.energy=energy; incoming.pointWorld=v3(s.com);
        ReserveReceipt r;
        if(!changeReserve(c,config.depth,s,f.foodReserves,energy,&incoming,r)) return false;
        if(trim) {
            Loaded L;
            if(!loadAt(c,config.depth,s,f.foodReserves,L)) return false;
            const float gas=std::clamp(((L.mass/rhoWater()-c.hullVolume)-L.fuelVolume)-c.finVolume,0.0f,c.gasCapacity);
            s.gasContent=pressure(-s.com[1],config.depth)*gas;
        }
        coefficients.push_back(c); supports.push_back(support); states.push_back(s);
        genes.push_back(body.P); owners.push_back(f.id); fish.push_back(f); subsidy+=r.accepted;
        return owned();
    }
    bool refill(std::size_t i,float target=25) {
        Loaded L; Parcel p; ReserveReceipt r;
        if(!loadAt(coefficients[i],config.depth,states[i],fish[i].foodReserves,L)||
           !comovingParcel(coefficients[i],L,states[i],std::max(0.0f,target-fish[i].foodReserves),p)||
           !changeReserve(coefficients[i],config.depth,states[i],fish[i].foodReserves,
                          target-fish[i].foodReserves,&p,r)) return false;
        subsidy+=r.accepted; return true;
    }
    bool step(std::size_t i,const HeldOuter& held,StepReceipt* receipt=nullptr,const V6& external={}) {
        if(!owned()||i>=fish.size()) return false;
        if(!stepHydroWithExternal(coefficients[i],supports[i],config,held,fish[i].bodyBuoy,
                fish[i].genome.size(),states[i],fish[i].foodReserves,receipt,external)) return false;
        float actions[NUM_ACTIONS]{};
        kernel::stepInternalState(fish[i],actions,kOuterDt);
        fish[i].age+=kOuterDt; fish[i].reproTimer-=kOuterDt; fish[i].interactTimer-=kOuterDt;
        return true;
    }
    // Test source only: transactions on the kernel's local copies hold exactly
    // 25 E at EACH incoming mechanical substep. Publish metering only when the
    // whole outer step succeeds, just as for state and the sole ledger.
    bool stepFixed(std::size_t i,const HeldOuter& held,FixedReceipt& receipt,const V6& external={}) {
        if(!owned()||i>=fish.size()||coefficients[i].energyCapacity<25) return false;
        FixedReceipt out;
        auto source=[&](int substep,HydroState& state,float& energy) {
            Loaded L;Parcel p;
            if(!loadAt(coefficients[i],config.depth,state,energy,L)||
               !comovingParcel(coefficients[i],L,state,std::max(0.0f,25-energy),p)||
               !changeReserve(coefficients[i],config.depth,state,energy,25-energy,&p,out.source[substep])) return false;
            out.incomingEnergy[substep]=energy;out.incomingState[substep]=state;return energy==25;
        };
        if(!stepHydroWithSource(coefficients[i],supports[i],config,held,fish[i].bodyBuoy,fish[i].genome.size(),
                              states[i],fish[i].foodReserves,&out.step,external,source)) return false;
        for(const auto& s:out.source)subsidy+=s.accepted;
        float actions[NUM_ACTIONS]{};
        kernel::stepInternalState(fish[i],actions,kOuterDt);
        fish[i].age+=kOuterDt;fish[i].reproTimer-=kOuterDt;fish[i].interactTimer-=kOuterDt;
        receipt=out;return true;
    }
    // Stable compaction moves every aligned column with one alive mask.
    bool compact(const std::vector<bool>& alive) {
        if(!owned()||alive.size()!=fish.size()) return false;
        std::size_t out=0;
        for(std::size_t in=0;in<fish.size();++in) if(alive[in]) {
            if(out!=in) {
                coefficients[out]=coefficients[in]; supports[out]=supports[in]; states[out]=states[in];
                genes[out]=genes[in]; owners[out]=owners[in]; fish[out]=fish[in];
            }
            ++out;
        }
        coefficients.resize(out); supports.resize(out); states.resize(out); genes.resize(out); owners.resize(out); fish.resize(out);
        return owned();
    }
};
inline hydrofix::Body body(const std::string& name="neutral") {
    hydrofix::Body b{name,appearance::neutral(),1,1,physical::neutral()};
    auto morph=[&](int i,float x){b.G.g[appearance::kMorphOffset+i]=x;};
    if(name=="manoeuvrer") {b.E=.5f; morph(0,.85f); morph(1,.60f); morph(10,.25f); morph(19,1); morph(23,1);}
    if(name=="cruiser") {b.E=2; morph(0,.25f); morph(1,.35f); morph(10,1); morph(11,.75f); morph(19,.25f); morph(23,.25f);}
    if(name=="noBladder") b.P.g[physical::kBladder]=0;
    if(name=="noFins") for(int i:{11,12,16,19,23}) morph(i,0);
    return b;
}
inline void hashV3(Digest& d,V3 v) { d.addf(v.x); d.addf(v.y); d.addf(v.z); }
inline void hashParcel(Digest& d,const Parcel& p) {
    d.addf(p.energy); hashV3(d,p.pointWorld); hashV3(d,p.velocityWorld); hashV3(d,p.spinPerMassWorld);
}
inline void hashReserve(Digest& d,const ReserveReceipt& r) {
    d.addf(r.accepted); d.addf(r.spent); d.addf(r.waste); d.addf(r.unpaid); hashParcel(d,r.removed);
}
inline void hashSubstep(Digest& d,const SubstepReceipt& r) {
    d.add(std::uint32_t(constantDigest())); d.add(std::uint32_t(constantDigest()>>32));
    forEachStateWord(r.state,[&](std::uint32_t u){d.add(u);});
    for(float x:{r.energy,r.basal,r.maintenance,r.gene,r.unpaidBasal,r.externalWork,r.penetration,
        r.motor.lambda,r.motor.requestPower,r.motor.actualPower,r.motor.aerobicPower,r.motor.burstPower,
        r.motor.fuel,r.motor.nextFatigue}) d.addf(x);
    hashReserve(d,r.reserve);
    for(const V6* v:{&r.incoming,&r.outgoing,&r.external}) d.addFloats(v->v,6);
    d.add(r.plan.count);
    for(int i=0;i<r.plan.count;++i) {
        hashV3(d,r.plan.channel[i].forceBody); hashV3(d,r.plan.channel[i].leverBody); d.addf(r.plan.channel[i].efficiency);
    }
    d.addFloats(r.plan.pairedControl,4);
    for(float x:{r.plan.nextTailDrive,r.plan.nextTailYaw,r.plan.gasRate,r.plan.pumpPower,r.plan.requestPower,r.plan.brakeFraction}) d.addf(x);
    d.add(r.contact.count); d.add(r.contact.sweeps); d.addf(r.contact.maxPenetration);
    for(int i=0;i<r.contact.count;++i) {
        const auto& p=r.contact.points[i]; d.add(p.face); d.add(p.vertex); d.addf(p.gap); d.addf(p.predicted);
        hashV3(d,p.lever); d.addf(p.normalImpulse); d.addFloats(p.tangentImpulse,2);
        for(int j=0;j<3;++j) {d.addFloats(p.w[j].v,6); d.addFloats(p.response[j].v,6); d.addFloats(p.effective[j],3);}
    }
}
} // namespace hydroharness

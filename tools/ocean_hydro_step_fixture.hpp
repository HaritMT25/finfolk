#pragma once
// Deterministic fixture-only invariant suite. No retained Loaded records.
#include <iomanip>
#include <sstream>
#include "ocean_hydro_harness.hpp"
namespace hydrofixture {
using namespace hydro;
inline void require(bool ok,const char* message) {
    if(!ok)throw std::runtime_error(message);
}
inline void legal(const hydroharness::Columns& h,const SubstepReceipt& r) {
    const auto& c=h.coefficients[0];Loaded L;V3 omega;
    require(validState(r.state)&&r.energy>=0&&r.energy<=c.energyCapacity&&r.state.fatigue<=c.fatigueCapacity,
            "fixture state/energy/fatigue invariant");
    require(loadAt(c,h.config.depth,r.state,r.energy,L)&&materialOmega(L,r.state,omega),"fixture loaded state");
    require(norm2(omega)<=12.00001f*12.00001f,"fixture angular rail");
    for(int face=0;face<6;++face)
        require(minimumGap(h.supports[0],L,boundaries(h.config),r.state,face)>=-1e-4f,"fixture hull containment");
    const float incoming=r.energy+r.reserve.spent;
    const float demand=kSubDt*(c.basalPower+maintenancePower(c,incoming));
    const float requested=std::min(incoming,demand)+r.motor.fuel;
    // changeReserve reports the actual rounded ledger subtraction. Its unpaid
    // field can therefore contain a positive binary32 subtraction remainder.
    require(r.motor.fuel>=0&&r.motor.lambda>=0&&r.motor.lambda<=1&&
        r.reserve.spent==incoming-std::max(0.f,incoming-requested)&&
        r.reserve.unpaid==std::max(0.f,requested-r.reserve.spent),"fixture receipt invariant");
}
inline std::string document() {
    std::ostringstream out;out<<'[';int cases=0;
    auto emit=[&](const std::string& name,int outer,const Digest& d) {
        if(cases++)out<<',';
        out<<"{\"name\":\""<<name<<"\",\"outer\":"<<outer<<",\"substeps\":"<<2*outer
           <<",\"chain\":\""<<hydrofix::hex64(d.h)<<"\"}";
    };
    const auto bodies=hydrofix::bodies();
    require(bodies.size()==137,"fixture body-set count changed");
    int admitted=0,refused=0;
    for(const auto& b:bodies) {
        hydroharness::Columns h;
        const float energy=std::min(25.f,5.f*b.S*b.S*b.S);
        require(h.add(b,energy),"fixture body initialization refused");
        ++admitted;Digest chain;
        for(int i=0;i<16;++i) {
            HeldOuter held;held.requests={40,.3f,.1f,0};StepReceipt r;
            require(h.step(0,held,&r)&&r.completed==2,"fixture body step refused");
            for(const auto& sub:r.substep){legal(h,sub);hydroharness::hashSubstep(chain,sub);}
        }
        emit(b.name,16,chain);
    }
    require(admitted==137&&refused==0,"fixture shortened admitted body set");
    for(const char* name:{"still_flow_boundary_20000","noBladder_floor_4000"}) {
        hydroharness::Columns h;h.config.toroidal=false;
        require(h.add(hydroharness::body(name[0]=='n'?"noBladder":"neutral")),"fixture long-run clone");
        const int count=name[0]=='n'?4000:20000;Digest chain;
        for(int i=0;i<count;++i) {
            HeldOuter held;held.requests.speed=i<5000?0:40;
            if(i>=10000)held.waterWorld={5,-1,2};
            held.requests.yaw=i>=15000?1:0;
            StepReceipt r;require(h.step(0,held,&r)&&r.completed==2,"fixture long run refused");
            for(const auto& sub:r.substep){legal(h,sub);hydroharness::hashSubstep(chain,sub);}
            require(h.refill(0),"fixture refill refused");
        }
        emit(name,count,chain);
    }
    // A dormant-trait twin covers all mechanics and receipt fields bit for bit.
    hydroharness::Columns a,b;auto body=hydroharness::body();
    require(a.add(body),"fixture dormant base");
    body.P.g[physical::kGape]=1;body.P.g[physical::kArmour]=1;
    body.G.g[appearance::kMorphOffset+29]=1;body.G.g[appearance::kMorphOffset+26]=1;
    require(b.add(body),"fixture dormant twin");Digest twin;
    for(int i=0;i<32;++i) {
        HeldOuter held;held.requests={40,.4f,.2f,0};StepReceipt ra,rb;
        require(a.step(0,held,&ra)&&b.step(0,held,&rb),"fixture twin step");
        for(int j=0;j<2;++j) {
            Digest da,db;hydroharness::hashSubstep(da,ra.substep[j]);hydroharness::hashSubstep(db,rb.substep[j]);
            require(da.h==db.h,"fixture dormant twin differs");hydroharness::hashSubstep(twin,ra.substep[j]);
        }
    }
    emit("dormant_twin",32,twin);
    out<<']';return out.str();
}
} // namespace hydrofixture

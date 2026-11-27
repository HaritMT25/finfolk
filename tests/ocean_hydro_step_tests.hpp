#pragma once
#include "../tools/ocean_hydro_harness.hpp"
namespace ot {
namespace hydstep {
using namespace hydro;
inline hydroharness::Columns neutral(const char* name="neutral") {
    hydroharness::Columns h;
    if(!h.add(hydroharness::body(name))) throw std::runtime_error("hydro test setup");
    return h;
}
inline float error(V3 a,V3 b) {return std::sqrt(norm2(sub(a,b)));}
inline bool samePhysical(HydroState a,HydroState b) {
    a.status=b.status=0; Digest da,db;
    forEachStateWord(a,[&](std::uint32_t u){da.add(u);}); forEachStateWord(b,[&](std::uint32_t u){db.add(u);});
    return da.h==db.h;
}
inline double ulp(float x) {return double(std::nextafter(std::abs(x),INFINITY))-std::abs(x);}
// Compare declared fields, including fuelVolume; never regroup material masses
// or inspect struct padding. evalLoad supplies its own fixed addition order.
inline bool sameLoad(const Loaded& a,const Loaded& b) {
    const auto words=[](const Loaded& L) {
        std::vector<std::uint32_t> out;
        auto add=[&](float x){out.push_back(std::bit_cast<std::uint32_t>(x));};
        for(float x:{L.k,L.t,L.fuelVolume,L.mass,L.com.x,L.com.y,L.com.z,
            L.hullVolume,L.displaced,L.halfDepth,L.hullCentroid.x,L.hullCentroid.y,L.hullCentroid.z,
            L.frontal,L.side,L.plan,L.wetted,L.fineness,L.cdForward,L.mouth.x,L.mouth.y,L.mouth.z}) add(x);
        for(const S3* x:{&L.inertia,&L.hullCov,&L.Jbody}) for(float v:x->m) add(v);
        for(const S6* x:{&L.Dfin,&L.Afin,&L.Abody,&L.Meff}) for(float v:x->m) add(v);
        for(int i=0;i<3;++i){add(L.K[i]);add(L.Khull[i]);}
        return out;
    };
    return words(a)==words(b);
}
inline bool sameReceipt(const ReserveReceipt& a,const ReserveReceipt& b) {
    const auto words=[](const ReserveReceipt& r) {
        std::vector<std::uint32_t> out;
        for(float x:{r.accepted,r.spent,r.waste,r.unpaid,r.removed.energy,
            r.removed.pointWorld.x,r.removed.pointWorld.y,r.removed.pointWorld.z,
            r.removed.velocityWorld.x,r.removed.velocityWorld.y,r.removed.velocityWorld.z,
            r.removed.spinPerMassWorld.x,r.removed.spinPerMassWorld.y,r.removed.spinPerMassWorld.z})
            out.push_back(std::bit_cast<std::uint32_t>(x));
        return out;
    };
    return words(a)==words(b);
}
inline V3 momentum(const Coefficients& c,const HydroState& s,float e) {return mul(v3(s.vGround),c.leanMass+fuelMass(e));}
inline V3 angular(const Coefficients& c,const HydroState& s,float e) {
    return add(v3(s.LWorld),cross(v3(s.com),momentum(c,s,e)));
}
}
inline void testHydroOuterAdapter() {
    using namespace hydstep; Test t("hydro_outer_adapter"); auto h=neutral();
    float actions[NUM_ACTIONS]{}; HeldOuter held;
    auto adapt=[&](bool triangular,bool ownFrame,V3 rnd=V3{}) {
        return adaptOuterActions(h.coefficients[0],h.supports[0],h.config,h.states[0],25,
            actions,1,triangular,ownFrame,rnd,{2,3,4},held);
    };
    actions[MOVE_FORWARD]=-1; t.expect(adapt(true,true)&&held.requests.speed==0,"triangular zero drive");
    actions[MOVE_FORWARD]=1; actions[STEER_X]=1;
    t.expect(adapt(true,true)&&held.requests.speed==150&&held.requests.yaw==1,"full drive keeps yaw");
    actions[MOVE_FORWARD]=0; actions[SPEED_ADJUST]=1;
    t.expect(adapt(false,true)&&std::abs(held.requests.speed-.8f)<1e-6f,"push accumulates once");
    h.states[0].requestedSpeed=150;
    t.expect(adapt(false,true)&&held.requests.speed==150,"target clamp");
    actions[STEER_X]=0; actions[STEER_Y]=1;
    t.expect(adapt(false,true)&&held.requests.forwardBias==1&&held.requests.yaw==0,"own frame forward");
    t.expect(adapt(false,false)&&held.requests.yaw>0.99f,"world +z is starboard at heading +x");
    actions[STEER_Z]=1;
    t.expect(adapt(true,true)&&held.requests.dive==1,"positive dive");
    // Rotating the fish rotates the world steering axes, not their signs.
    h.states[0]=restState({960,-120,540},{0,0,0},{0,0,1});
    actions[STEER_X]=1; actions[STEER_Y]=actions[STEER_Z]=0;
    t.expect(adapt(false,false)&&held.requests.yaw<-.99f,"world +x is port at heading +z");
    actions[STEER_X]=0; actions[SPEED_ADJUST]=-1; h.states[0].requestedSpeed=0;
    t.expect(adapt(false,true)&&held.requests.speed==0,"push lower clamp");
    h.states[0]=neutral().states[0];
    RandomGen a(717u),b=a;
    actions[MOVE_RANDOM]=.5f;
    holdRandomRequest(actions,1,false,a); t.expect(a.unit()==b.unit(),"threshold draws zero");
    a=RandomGen(717u); b=a; actions[MOVE_RANDOM]=.5001f;
    holdRandomRequest(actions,1,false,a); for(int i=0;i<3;++i)b.range(-1,1);
    t.expect(a.unit()==b.unit(),"exactly three draws");
    a=RandomGen(717u); b=a;holdRandomRequest(actions,1,true,a);t.expect(a.unit()==b.unit(),"triangular draws zero");
    h.states[0].requestedSpeed=0; actions[STEER_Z]=actions[STEER_Y]=actions[STEER_X]=0; actions[SPEED_ADJUST]=0;
    adapt(true,true); StepReceipt receipt;
    t.expect(h.step(0,held,&receipt)&&receipt.completed==2,"two substeps hold captured water/requests");
    t.expect(held.waterWorld.x==2&&held.waterWorld.y==3&&held.waterWorld.z==4,"held world water intact");
}
inline void testHydroMechanicalStep() {
    using namespace hydstep; Test t("hydro_mechanical_step"); auto h=neutral();
    Loaded L; loadAt(h.coefficients[0],240,h.states[0],25,L);
    const auto& c=h.coefficients[0]; V6 z{{-82,7,3,1,.5f,-2}},active{{2,3,4,5,6,7}},out{};
    const S6 D=passiveDamping(L,c.halfLength,z);
    t.expect(solveMechanics(c,L,h.states[0],z,D,active,out),"coupled solve");
    // Independent dense construction from the declared equation, not its RHS.
    double aug[6][7]{};
    const V3 up=unrotate(poseOf(h.states[0]),kWorldUp);
    const double meta=double(calibration::kGravity)*rhoWater()*L.displaced*calibration::kMetacentricFraction*L.halfDepth;
    const double g=double(calibration::kGravity)*(double(rhoWater())*L.displaced-L.mass);
    const double force[]={active.v[0]+up.x*g,active.v[1]+up.y*g,active.v[2]+up.z*g,
        active.v[3]-meta*up.y,active.v[4]+meta*up.x,active.v[5]};
    double maxResidual=0,scale=0;
    for(int i=0;i<6;++i) {
        double rhs=kSubDt*force[i],lhs=0;
        for(int j=0;j<6;++j) {
            aug[i][j]=double(at6(L.Meff,i,j))+double(kSubDt)*at6(D,i,j);
            if(i==j&&(i==3||i==4))aug[i][j]+=double(kSubDt)*kSubDt*meta;
            rhs+=double(at6(L.Meff,i,j))*z.v[j]; lhs+=aug[i][j]*out.v[j];
        }
        maxResidual=std::max(maxResidual,std::abs(lhs-rhs)); scale=std::max(scale,std::abs(rhs));
    }
    t.expect(maxResidual/scale<=2e-5,"independent full RHS residual %.9g",maxResidual/scale);
    S6 A=L.Meff;for(int i=0;i<21;++i)A.m[i]+=kSubDt*D.m[i];
    V6 passive; t.expect(solveScaled(A,mulS6(L.Meff,z),c.halfLength,passive)&&
        quad(L.Meff,passive)<=quad(L.Meff,z),"passive contraction excludes external/righting work");
}
inline void testHydroWorldMomentum() {
    using namespace hydstep; Test t("hydro_world_momentum"); auto h=neutral(); Loaded L;
    loadAt(h.coefficients[0],240,h.states[0],25,L);
    HydroState s=h.states[0]; put(s.vGround,{4,5,6});put(s.LWorld,{2,3,4});
    const V3 velocity=v3(s.vGround),momentum=v3(s.LWorld); V3 w0;
    materialOmega(L,s,w0);
    for(int i=0;i<20000;++i) {
        V3 omega; materialOmega(L,s,omega); bool ok;
        const Q4 q=integrate(poseOf(s),omega,kSubDt,&ok);
        if(!ok){t.expect(false,"pose integrate");break;}
        s.quat[0]=q.w;s.quat[1]=q.x;s.quat[2]=q.y;s.quat[3]=q.z;
    }
    t.expect(error(velocity,v3(s.vGround))==0&&error(momentum,v3(s.LWorld))==0,"pose-only leaves carried world quantities bit identical");
    V3 w1;materialOmega(L,s,w1);
    t.expect(error(w0,w1)>.001f&&std::abs(qnorm2(poseOf(s))-1)<5e-7f,"anisotropic omega and normalized long pose");
    V6 z{{10,12,3,4,5,8}},after=z;bool railed=false;
    t.expect(railVelocity(L,2,after,railed)&&railed,"coupled rail");
    const V6 beforeP=mulS6(L.Meff,z),afterP=mulS6(L.Meff,after);
    float residual=0;for(int i=0;i<3;++i)residual=std::max(residual,std::abs(beforeP.v[i]-afterP.v[i]));
    t.expect(residual<1e-4f&&quad(L.Meff,after)<quad(L.Meff,z),"rail preserves effective linear momentum, dissipates energy");
}
inline void testHydroActuators() {
    using namespace hydstep;Test t("hydro_actuators"); auto h=neutral();Loaded L;
    loadAt(h.coefficients[0],240,h.states[0],25,L);const auto& c=h.coefficients[0];
    ActuatorPlan p;V6 z{{-82,0,0,0,0,0}};
    t.expect(planActuators(c,L,h.states[0],h.config,{82,1,0,0},.5f,z,p)&&p.count==10,"ten ordered channels");
    const V6 active=activeWrench(p,1);
    t.expect(active.v[0]<0&&active.v[5]<0,"forward -x, positive yaw negative z torque");
    t.expect(p.channel[0].forceBody.x<0&&p.channel[1].forceBody.y<0,"tail drive and yaw separate");
    t.expect(error(p.channel[0].leverBody,loadedLever(c.caudalCentroid,c.caudalBasis,L))==0,"loaded COM lever");
    t.expect(filterTail(.3f,0,c.tailTau)<.3f&&filterTail(0,1,c.tailTau)>0,"independent filters");
    const S6 full=inducedDamping(c,L,z,p,1),half=inducedDamping(c,L,z,p,.5f);
    bool scales=true;for(int i=0;i<21;++i)scales=scales&&half.m[i]==.25f*full.m[i];
    t.expect(scales&&hyd::psdD(hyd::dense(full),1e-8),"induced PSD scales with actual command squared");
    auto no=neutral("noFins"); Loaded N;loadAt(no.coefficients[0],240,no.states[0],25,N);
    t.expect(planActuators(no.coefficients[0],N,no.states[0],no.config,{82,1,1,0},.5f,z,p)&&p.count==0,"no absent-area divisions");
    ActuatorPlan opposing;opposing.count=2;
    opposing.channel[0]={{0,5,0},{},.35f};opposing.channel[1]={{0,-5,0},{},.35f};
    const auto zero=activeWrench(opposing,1);
    t.expect(dot6(zero,zero)==0&&2*5*(82+c.rowSpeed)/.35f>0,"opposing force channels cancel wrench, retain separate price");
    // Price every channel at its own point velocity, before summing wrenches.
    t.expect(planActuators(c,L,h.states[0],h.config,{82,.4f,.3f,0},.5f,z,p),"pricing plan");
    float work=p.pumpPower;
    for(int j=0;j<p.count;++j) {
        const auto& ch=p.channel[j];
        const V3 local=add({z.v[0],z.v[1],z.v[2]},cross({z.v[3],z.v[4],z.v[5]},ch.leverBody));
        work+=std::sqrt(norm2(ch.forceBody))*(std::sqrt(norm2(local))+c.rowSpeed)/ch.efficiency;
    }
    t.expect(std::abs(work-p.requestPower)<=8*ulp(work),"complete separate-channel power price");
}
inline void testHydroMotorAccounting() {
    using namespace hydstep;Test t("hydro_motor_accounting"); auto h=neutral();const auto& c=h.coefficients[0];
    MotorReceipt r;const float wc=references().workConversion;
    t.expect(limitMotor(c,25,0,c.peakPower,wc,r)&&r.lambda==1&&r.burstPower==c.peakPower-c.sustainedPower&&
        r.fuel==(wc*kSubDt)*(r.aerobicPower+3*r.burstPower),"exact peak and 3x excess fuel");
    for(float fibre:{0.0f,.5f,1.0f}) {
        auto b=hydroharness::body();b.P.g[physical::kFibre]=fibre;Coefficients cf;Support sf;compile(b.G,1,1,b.P,Params{},cf,sf);
        float fatigue=0;int fill=0;
        if(cf.fatigueCapacity>0) {
            while(fatigue<cf.fatigueCapacity&&fill<255) {limitMotor(cf,1000,fatigue,cf.peakPower,wc,r);fatigue=r.nextFatigue;++fill;}
            t.expect(std::abs(fill*kSubDt-2)<=.016f,"fibre %g peak fills at %.9g s",double(fibre),double(fill*kSubDt));
            // White fibre needs ceil((4/.275)/.008) = 1819 steps.
            // 2000 gives a 16 s observation window (~10% above that law).
            constexpr int maxRecoverySteps=2000;
            int recover=0;
            while(fatigue>0&&recover<maxRecoverySteps) {
                const bool accepted=limitMotor(cf,1000,fatigue,0,wc,r);
                t.expect(accepted,"zero-work recovery step accepted");
                if(!accepted) break;
                fatigue=r.nextFatigue;++recover;
                t.expect(r.fuel==0,"recovery is free");
            }
            const float expected=cf.fatigueCapacity/(kGamma*cf.sustainedPower);
            t.expect(fatigue==0&&std::abs(recover*kSubDt-expected)<=.016f,
                     "fibre recovery completes and follows capacity/sustained law");
        } else t.expect(limitMotor(cf,25,0,cf.peakPower,wc,r)&&r.nextFatigue==0,"all red zero burst without division");
    }
    t.expect(limitMotor(c,0,0,c.peakPower,wc,r)&&r.lambda==0&&r.fuel==0,"no fuel no active work");
    t.expect(limitMotor(c,25,0,0,wc,r)&&r.actualPower==0&&r.fuel==0,"zero request");
    for(float e:{1e-7f,.0001f,.01f,1.0f}) {
        t.expect(limitMotor(c,e,0,10*c.peakPower,wc,r),"fuel limit accepted");
        const float requested=(wc*kSubDt)*(r.aerobicPower+3*r.burstPower);
        t.expect(requested<=e+4*ulp(e),"fuel cap only rounding: e %.9g requested %.9g",double(e),double(requested));
        const float excess=c.peakPower-c.sustainedPower;
        const float available=c.sustainedPower+std::min(excess,c.fatigueCapacity/kSubDt);
        const float q=e/(wc*kSubDt),fuelPower=q<=c.sustainedPower?q:(q+2*c.sustainedPower)/3;
        const float lambda=std::min(1.0f,std::min(available/(10*c.peakPower),fuelPower/(10*c.peakPower)));
        t.expect(r.lambda==lambda&&r.aerobicPower==std::min(r.actualPower,c.sustainedPower)&&
                 r.burstPower==std::max(0.0f,r.actualPower-c.sustainedPower),"analytic fuel/power limit");
    }
    float energy=.001f,fatigue=0;
    for(int i=0;i<4&&energy>0;++i) {
        t.expect(limitMotor(c,energy,fatigue,c.peakPower,wc,r),"exhaustion accepted");
        energy-=r.fuel;fatigue=r.nextFatigue;
    }
    t.expect(energy<=float(8*ulp(.001f)),"fuel exhaustion spends only available ledger");
    ActuatorPlan blocked; Loaded L;loadAt(c,240,h.states[0],25,L);
    t.expect(planActuators(c,L,h.states[0],h.config,{82,0,0,0},.5f,V6{},blocked)&&
             limitMotor(c,25,0,blocked.requestPower,wc,r)&&r.fuel>0,"blocked rowing work is charged");
}
inline void testHydroGas() {
    using namespace hydstep;Test t("hydro_gas");auto h=neutral();auto& s=h.states[0];const auto& c=h.coefficients[0];Loaded L,L2;
    t.expect(pressure(0,240)==1&&pressure(120,240)==2&&pressure(240,240)==3,"linear pressure");
    loadAt(c,240,s,25,L);s.com[1]=-240;loadAt(c,240,s,25,L2);
    t.expect(L2.displaced<L.displaced&&s.gasContent==h.states[0].gasContent,"compression without transaction");
    V6 z{};ActuatorPlan p;s.com[1]=-144;
    t.expect(planActuators(c,L2,s,h.config,{0,0,0,0},.5f,z,p)&&p.gasRate>0&&p.pumpPower>0,"regulation paid");
    t.expect(std::abs(p.gasRate)<=calibration::kGasRateFraction*c.hullVolume,"pump rate bound");
    s.gasContent=3*c.gasCapacity+1;t.expect(!loadAt(c,240,s,25,L),"illegal gas refused");
    auto n=neutral("noBladder");loadAt(n.coefficients[0],240,n.states[0],25,L);
    t.expect(planActuators(n.coefficients[0],L,n.states[0],n.config,{},.5f,z,p)&&p.gasRate==0&&p.pumpPower==0,"no bladder exact zero pump");
    // An almost empty ledger reserves basal first and shares one lambda among
    // gas and every force channel. Compression itself made no debit above.
    auto low=neutral(); low.fish[0].foodReserves=.01f;low.states[0].com[1]=-144;
    const float initialGas=low.states[0].gasContent; StepReceipt sr;
    HeldOuter held;held.requests={150,1,1,0};
    t.expect(low.step(0,held,&sr),"shared-lambda low-energy substeps");
    float gas=initialGas;
    for(const auto& sub:sr.substep) {
        gas+=kSubDt*sub.motor.lambda*sub.plan.gasRate;
        t.expect(sub.state.gasContent==gas&&sub.motor.lambda<1&&sub.plan.pumpPower>0,
                 "gas and channels share energy limit");
    }
}
inline void testHydroReserveTransactions() {
    using namespace hydstep;Test t("hydro_reserve_transactions");auto h=neutral(); auto c=h.coefficients[0];auto s=h.states[0];float e=25;ReserveReceipt r;
    t.expect(std::bit_cast<std::uint32_t>(fuelMass(5))==0x3c23d70au,
             "fuel conversion is division, not rounded reciprocal multiplication");
    put(s.vGround,{10,-2,4});const auto before=v3(s.vGround);
    t.expect(changeReserve(c,240,s,e,-5,nullptr,r)&&e==20&&error(before,v3(s.vGround))==0,"co-moving debit preserves translation exactly");
    Parcel p{10,add(v3(s.com),{1,2,3}),{20,1,0},{.1f,.2f,.3f}};
    V3 P=momentum(c,s,e),H=angular(c,s,e);
    const float old=e;const auto oldS=s;
    t.expect(changeReserve(c,240,s,e,10,&p,r),"off-centre ingestion");
    const float dm=fuelMass(e)-fuelMass(old);
    const V3 expectedP=add(P,mul(p.velocityWorld,dm));
    const V3 expectedH=add(H,mul(add(p.spinPerMassWorld,cross(p.pointWorld,p.velocityWorld)),dm));
    t.expect(error(expectedP,momentum(c,s,e))<2e-5f&&error(expectedH,angular(c,s,e))<.02f,"carried material P/H closure");
    t.expect(error(v3(oldS.vGround),v3(s.vGround))>0,"ingestion mixes velocity");
    t.expect(changeReserve(c,240,s,e,100,&p,r)&&e==c.energyCapacity&&r.waste>0,"overflow waste");
    t.expect(changeReserve(c,240,s,e,-100,nullptr,r)&&e==0&&r.unpaid>0,"debit cap unpaid");
    // Both rounded representations must remain legal across the fixture body set.
    for(const auto& body:hydrofix::bodies()) {
        Coefficients bc; Support bs;
        const bool compiled=compile(body.G,body.S,body.E,body.P,Params{},bc,bs)==kOk;
        t.expect(compiled,"capacity body %s compiles",body.name.c_str());
        if(!compiled) continue;
        const float physicalMax=bc.reserveCapacity*(bodymat::kRhoLipid*rhoWater());
        const float energyMax=fuelMass(bc.energyCapacity);
        const float bound=std::max(physicalMax,energyMax);
        Loaded L;
        t.expect(fuelCapacity(bc)==bound&&evalLoad(bc,0,physicalMax,L)&&evalLoad(bc,0,energyMax,L),
                 "both capacity endpoints accepted: %s",body.name.c_str());
        t.expect(!evalLoad(bc,0,std::nextafter(bound,INFINITY),L)&&L.k==1&&L.mass==0,
                 "first mass above envelope refused: %s",body.name.c_str());
        auto state=restState({960,-120,540},{0,0,0},{1,0,0});
        for(float energy:{0.0f,.5f*bc.energyCapacity,std::nextafter(bc.energyCapacity,0.0f),bc.energyCapacity}) {
            for(float gas:{0.0f,bc.gasCapacity,3.0f*bc.gasCapacity}) {
                state.gasContent=gas;
                Loaded expected;
                const float requiredFuel=energy>0 ? energy/500.0f : 0.0f;
                const float gasVolume=std::min(bc.gasCapacity,gas/2.0f);
                t.expect(evalLoad(bc,gasVolume,requiredFuel,expected)&&loadAt(bc,240,state,energy,L)&&
                         sameLoad(L,expected),
                         "complete ledger load uses exact conversion: %s",body.name.c_str());
            }
        }
        state.gasContent=0;
        t.expect(!loadAt(bc,240,state,std::nextafter(bc.energyCapacity,INFINITY),L),
                 "energy above capacity refused: %s",body.name.c_str());
        float energy=0; ReserveReceipt receipt;
        Parcel credit{bc.energyCapacity+100,v3(state.com),{0,0,0},{0,0,0}};
        const bool credited=changeReserve(bc,240,state,energy,credit.energy,&credit,receipt);
        t.expect(credited&&energy==bc.energyCapacity&&receipt.accepted==bc.energyCapacity&&
                 receipt.waste==credit.energy-bc.energyCapacity,
                 "full credit and waste: %s",body.name.c_str());
        if(!credited) continue;
        const auto snapshot=state; const auto before=receipt;
        Digest beforeReceipt,afterReceipt; hydroharness::hashReserve(beforeReceipt,before);
        Parcel invalid=credit; invalid.energy=NAN;
        const bool rejected=!changeReserve(bc,240,state,energy,1,&invalid,receipt);
        hydroharness::hashReserve(afterReceipt,receipt);
        t.expect(rejected&&energy==bc.energyCapacity&&samePhysical(state,snapshot)&&
                 state.status==snapshot.status&&beforeReceipt.h==afterReceipt.h,
                 "failed full-capacity credit is atomic: %s",body.name.c_str());
        t.expect(changeReserve(bc,240,state,energy,-bc.energyCapacity,nullptr,receipt)&&energy==0,
                 "full-capacity debit remains legal: %s",body.name.c_str());
        // Finite input passes early validation, then perpendicular orbital
        // position/velocity overflow while building next.LWorld. Start below
        // capacity so a nonzero mass is actually accepted into the candidate.
        state=restState({960,-120,540},{3,-2,1},{1,0,0});
        put(state.LWorld,{.25f,-.5f,.75f}); energy=.25f*bc.energyCapacity;
        ReserveReceipt sentinel{1.25f,2.5f,3.75f,4.5f,{5.25f,{6,7,8},{9,10,11},{12,13,14}}};
        receipt=sentinel;
        const auto lateSnapshot=state; const float lateEnergy=energy;
        Parcel huge{.25f*bc.energyCapacity,{1e30f,0,0},{0,1e30f,0},{.1f,.2f,.3f}};
        Loaded initial;
        t.expect(finite(huge)&&loadAt(bc,240,state,energy,initial)&&huge.energy>0&&
                 energy+huge.energy<bc.energyCapacity,
                 "late refusal has legal initial load and finite credit: %s",body.name.c_str());
        const float fraction=(fuelMass(energy+huge.energy)-fuelMass(energy))/
            (bc.leanMass+fuelMass(energy+huge.energy));
        const V3 candidateVelocity=add(v3(state.vGround),mul(sub(huge.velocityWorld,v3(state.vGround)),fraction));
        t.expect(!finite(cross(sub(huge.pointWorld,v3(state.com)),sub(huge.velocityWorld,candidateVelocity))),
                 "candidate orbital cross product overflows: %s",body.name.c_str());
        t.expect(!changeReserve(bc,240,state,energy,huge.energy,&huge,receipt)&&energy==lateEnergy&&
                 samePhysical(state,lateSnapshot)&&state.status==lateSnapshot.status&&sameReceipt(receipt,sentinel),
                 "late credit refusal preserves ledger/state/nontrivial receipt: %s",body.name.c_str());
    }
    auto a=h.states[0],b=a;b.com[0]+=10;float ae=25,be=5;TransferReceipt transfer;
    P=add(momentum(c,a,ae),momentum(c,b,be)); H=add(angular(c,a,ae),angular(c,b,be));
    t.expect(shareReserves(c,c,240,a,ae,b,be,transfer)&&std::abs(ae-be)<1e-5,"sharing half difference");
    t.expect(std::abs(ae+be-30)<=8*ulp(30)&&error(P,add(momentum(c,a,ae),momentum(c,b,be)))<2e-5&&
        error(H,add(angular(c,a,ae),angular(c,b,be)))<.02,"share conservation binary32 ledger/P/H");
    t.expect(fightTransfer(c,c,240,b,be,a,ae,100,transfer)&&ae==0,"fight bounded by available donor");
    a=h.states[0];b=a;b.gasContent=-1;ae=be=25;const auto snapshot=a;
    t.expect(!transferReserve(c,c,240,a,ae,b,be,10,transfer)&&samePhysical(a,snapshot)&&ae==25&&be==25,"atomic pair failure");
}
inline void testHydroContact() {
    using namespace hydstep;Test t("hydro_contact");auto h=neutral("noBladder");auto& s=h.states[0];Loaded L;loadAt(h.coefficients[0],240,s,25,L);
    s.com[1]=-240;float penetration;
    t.expect(resolveBoundaries(h.coefficients[0],h.supports[0],L,boundaries(h.config),s,penetration),"floor hull placement");
    V6 z{{0,0,-1,0,0,0}};ContactReceipt receipt;
    t.expect(predictContact(h.coefficients[0],h.supports[0],L,boundaries(h.config),s,{},z,receipt)&&receipt.count>0&&receipt.sweeps==4,"four contact sweeps");
    bool ordered=true;for(int j=0;j<receipt.count;++j) {
        const auto& p=receipt.points[j];
        if(j&&p.face==receipt.points[j-1].face)ordered=ordered&&p.vertex>receipt.points[j-1].vertex;
        t.expect(p.normalImpulse>=0&&std::sqrt(p.tangentImpulse[0]*p.tangentImpulse[0]+p.tangentImpulse[1]*p.tangentImpulse[1])<=
            calibration::kStaticFriction*p.normalImpulse+1e-5f,"unilateral/disk bound");
    }
    t.expect(ordered,"stable face/vertex IDs");
    V6 reconstructed{{0,0,-1,0,0,0}};
    for(int j=0;j<receipt.count;++j) {
        const auto& p=receipt.points[j];
        add6(reconstructed,p.response[0],p.normalImpulse);
        for(int k=0;k<2;++k)add6(reconstructed,p.response[k+1],p.tangentImpulse[k]);
        for(int a=0;a<3;++a) for(int b=0;b<3;++b)
            t.expect(std::abs(p.effective[a][b]-dot6(p.w[a],p.response[b]))<=8*ulp(p.effective[a][b]),
                     "coupled contact response includes tangent cross terms");
    }
    for(int i=0;i<6;++i)t.expect(std::abs(z.v[i]-reconstructed.v[i])<2e-5f,"contact impulse closure");
    t.expect(quad(L.Meff,z)<=quad(L.Meff,V6{{0,0,-1,0,0,0}})+1e-5f,"zero restitution dissipates impact energy");
    V6 slip{{100,70,-1,0,0,0}};ContactReceipt sliding;
    t.expect(predictContact(h.coefficients[0],h.supports[0],L,boundaries(h.config),s,{},slip,sliding),"sliding impact");
    int dynamic=0;
    for(int j=0;j<sliding.count;++j) {
        const auto& p=sliding.points[j];const float jt=std::hypot(p.tangentImpulse[0],p.tangentImpulse[1]);
        if(p.normalImpulse>0) {++dynamic;t.expect(std::abs(jt-calibration::kDynamicFriction*p.normalImpulse)<=2e-5f,
                                                "dynamic friction disk");}
    }
    t.expect(dynamic>0,"dynamic friction exercised");
    V6 release{{0,0,1,0,0,0}};
    predictContact(h.coefficients[0],h.supports[0],L,boundaries(h.config),s,{},release,receipt);
    float normal=0;for(int j=0;j<receipt.count;++j)normal+=receipt.points[j].normalImpulse;
    t.expect(normal==0,"contact releases without attraction");
    // Same ground motion with two different water decompositions.
    V6 za{{3,0,-1,0,0,0}},zb{{-4,2,-1,0,0,0}};ContactReceipt ra,rb;
    predictContact(h.coefficients[0],h.supports[0],L,boundaries(h.config),s,{},za,ra);
    predictContact(h.coefficients[0],h.supports[0],L,boundaries(h.config),s,{7,-2,0},zb,rb);
    t.expect(std::abs((zb.v[0]+7)-za.v[0])<2e-5f&&std::abs((zb.v[1]-2)-za.v[1])<2e-5f,"contact uses ground velocity");
}
inline void testHydroLoadedBoundaries() {
    using namespace hydstep;Test t("hydro_loaded_boundaries");auto h=neutral();h.config.toroidal=false;Loaded L;loadAt(h.coefficients[0],240,h.states[0],25,L);
    for(int face=0;face<6;++face) {
        auto s=h.states[0];put(s.com,add(v3(s.com),mul(faceNormal(face),-2000)));
        const Q4 q=qmul(poseOf(s),qnormalize({1,.2f,.3f,.1f}));s.quat[0]=q.w;s.quat[1]=q.x;s.quat[2]=q.y;s.quat[3]=q.z;
        float penetration;
        t.expect(resolveBoundaries(h.coefficients[0],h.supports[0],L,boundaries(h.config),s,penetration)&&penetration<.01f,"rotated hull face %d",face);
    }
    auto s=h.states[0];float penetration;auto shallow=boundaries(h.config);shallow.depth=1;
    t.expect(!resolveBoundaries(h.coefficients[0],h.supports[0],L,shallow,s,penetration),"infeasible shallow tank refused");
    shallow.depth=40;t.expect(resolveBoundaries(h.coefficients[0],h.supports[0],L,shallow,s,penetration),"feasible shallow tank");
    auto torus=boundaries(h.config);torus.toroidal=true;s=h.states[0];s.com[0]=-.25f;s.com[2]=1080.25f;
    t.expect(resolveBoundaries(h.coefficients[0],h.supports[0],L,torus,s,penetration)&&s.com[0]>1900&&s.com[2]<1,"toroidal COM seams");
    s=h.states[0];put(s.com,{0,-240,0});float energy=25;ReserveReceipt reserve;
    t.expect(resolveBoundaries(h.coefficients[0],h.supports[0],L,boundaries(h.config),s,penetration),"corner placement");
    Parcel credit{20,v3(s.com),v3(s.vGround),{}};
    t.expect(changeReserve(h.coefficients[0],240,s,energy,20,&credit,reserve)&&
             loadAt(h.coefficients[0],240,s,energy,L)&&
             resolveBoundaries(h.coefficients[0],h.supports[0],L,boundaries(h.config),s,penetration),
             "reserve inflation at glass/floor corner resolved with loaded hull");
    for(int face=0;face<6;++face)t.expect(minimumGap(h.supports[0],L,boundaries(h.config),s,face)>=-1e-4f,
                                       "whole inflated hull contained face %d",face);
}
inline void testHydroStepRefusals() {
    using namespace hydstep;Test t("hydro_step_refusals");auto h=neutral();
    for(int fault=0;fault<14;++fault) {
        auto s=h.states[0];auto c=h.coefficients[0];auto config=h.config;float e=25;
        if(fault==0)s.com[0]=NAN;if(fault==1)s.gasContent=INFINITY;if(fault==2)e=-1;
        if(fault==3)s.fatigue=-1;if(fault==4)s.quat[0]=3;if(fault==5)s.status=0;
        if(fault==6)config.maxAngularSpeed=13;if(fault==7)c.innerSecond[0]=-1e6f;if(fault==8)config.depth=0;
        if(fault==9)e=std::nextafter(c.energyCapacity,INFINITY);if(fault==10)s.fatigue=std::nextafter(c.fatigueCapacity,INFINITY);
        if(fault==11)s.vGround[0]=INFINITY;if(fault==12)s.gasContent=-1;if(fault==13)c.innerMass=INFINITY;
        const auto before=s;const float energy=e;StepReceipt r;
        t.expect(!stepHydro(c,h.supports[0],config,{},.5f,0,s,e,&r)&&samePhysical(s,before)&&e==energy&&
            (s.status&kStatusFailure),"atomic failure case %d stage %d",fault,int(r.failure));
    }
    t.expect(!validConfig(h.config,kGeometryLaw+1)&&!validConfig(h.config,kGeometryLaw,kMaterialLaw,kExpressionStage,kReferenceLaw,kMechanicsLaw+1),"version refusal");
}
inline void testHydroLongRun() {
    using namespace hydstep;Test t("hydro_long_run");auto h=neutral();h.config.toroidal=false;
    Digest chain;int completed=0;float maxOmega=0;
    for(int i=0;i<20000;++i) {
        HeldOuter held; held.requests.speed=i<5000?0:40;
        if(i>=10000)held.waterWorld={5,-1,2};
        held.requests.yaw=i>=15000?1:0;
        StepReceipt r;
        if(!h.step(0,held,&r))break;
        for(const auto& sub:r.substep)hydroharness::hashSubstep(chain,sub);
        Loaded L;V3 w;loadAt(h.coefficients[0],240,h.states[0],h.fish[0].foodReserves,L);materialOmega(L,h.states[0],w);
        maxOmega=std::max(maxOmega,std::sqrt(norm2(w)));++completed;
        bool legal=validState(h.states[0])&&h.fish[0].foodReserves>=0&&h.fish[0].foodReserves<=h.coefficients[0].energyCapacity&&
            h.states[0].fatigue<=h.coefficients[0].fatigueCapacity;
        for(int face=0;face<6;++face)legal=legal&&minimumGap(h.supports[0],L,boundaries(h.config),h.states[0],face)>=-1e-4f;
        if(!legal){t.expect(false,"long-run state/load/hull legality at %d",i);break;}
        // Inspect the completed mechanical step before the harness credits
        // fuel. That later transaction inflates the hull; the next step owns
        // its geometric boundary resolution.
        if(!h.refill(0))break;
    }
    t.expect(completed==20000&&maxOmega<=12.00001f,"20000 outer steps finite/bounded, completed %d omega %.9g",completed,double(maxOmega));
    t.note("40000-substep chain %s",hyd::hex64(chain.h).c_str());
}
inline void testHydroStepNumbers() {
    using namespace hydstep;Test t("hydro_step_numbers");Digest all;int count=0;
    for(const auto& b:hyd::bodySet(8,625u)) {
        hydroharness::Columns h;const float e=std::min(25.0f,5.0f*b.S*b.S*b.S);
        if(!h.add({b.name,b.G,b.S,b.E,b.P},e))continue;
        Digest chain;bool ok=true;
        for(int i=0;i<16;++i) {
            HeldOuter held;held.requests={40,.3f,.1f,0};StepReceipt r;
            if(!h.step(0,held,&r)){ok=false;break;}
            for(const auto& sub:r.substep)hydroharness::hashSubstep(chain,sub);
        }
        t.expect(ok,"numbers %s",b.name.c_str()); all.add(std::uint32_t(chain.h));all.add(std::uint32_t(chain.h>>32));++count;
    }
    t.note("%d body chains %s",count,hyd::hex64(all.h).c_str());
    auto a=neutral(); auto b=hydroharness::body();b.P.g[physical::kGape]=1;b.P.g[physical::kArmour]=1;
    b.G.g[appearance::kMorphOffset+29]=1;b.G.g[appearance::kMorphOffset+26]=1;
    hydroharness::Columns twin;t.expect(twin.add(b),"dormant twin");
    for(int i=0;i<32;++i) {HeldOuter held;held.requests={40,.4f,.2f,0};StepReceipt ra,rb;
        t.expect(a.step(0,held,&ra)&&twin.step(0,held,&rb)&&samePhysical(a.states[0],twin.states[0])&&
            a.fish[0].foodReserves==twin.fish[0].foodReserves,"dormant mechanics/cost/load/contact twin %d",i);}
}
inline void testHydroStepSuite() {
    testHydroOuterAdapter();testHydroMechanicalStep();testHydroWorldMomentum();testHydroActuators();
    testHydroMotorAccounting();testHydroGas();testHydroReserveTransactions();testHydroContact();
    testHydroLoadedBoundaries();testHydroStepRefusals();testHydroLongRun();testHydroStepNumbers();
}
} // namespace ot

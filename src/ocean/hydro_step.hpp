#pragma once
// Internal mechanics only. No OceanWorld/module include until PR 3.
#include <cstddef>
#include "hydro_contact.hpp"
#include "../core/sensors_actions.hpp"
#include "../core/random.hpp"

namespace hydro {
struct Requests { float speed=0,yaw=0,dive=0,forwardBias=0; };
struct StepConfig {
    float width=1920,height=1080,depth=240;
    float minRequestedSpeed=0,maxRequestedSpeed=150,maxAngularSpeed=12,geneCost=0,wallBand=0;
    bool toroidal=true;
};
inline BoundaryConfig boundaries(const StepConfig& c) { return {c.width,c.height,c.depth,c.toroidal}; }
inline bool validConfig(const StepConfig& c,int geometry=kGeometryLaw,int material=kMaterialLaw,
    int expression=kExpressionStage,int reference=kReferenceLaw,int mechanics=kMechanicsLaw,int energetics=kEnergeticsLaw) {
    for(float x:{c.width,c.height,c.depth,c.minRequestedSpeed,c.maxRequestedSpeed,c.maxAngularSpeed,c.geneCost,c.wallBand})
        if(!std::isfinite(x)) return false;
    return c.width>0 && c.height>0 && c.depth>0 && c.minRequestedSpeed>=0 &&
        c.maxRequestedSpeed>=c.minRequestedSpeed && c.maxRequestedSpeed<=150 &&
        c.maxAngularSpeed>0 && c.maxAngularSpeed<=12 && c.geneCost>=0 && c.wallBand>=0 &&
        versionsSupported(geometry,material,expression,reference) && mechanics==kMechanicsLaw && energetics==kEnergeticsLaw;
}
struct HeldOuter { V3 waterWorld{0,0,0}; Requests requests{}; };
struct Channel { V3 forceBody{},leverBody{}; float efficiency=1; };
struct ActuatorPlan {
    Channel channel[10]{}; int count=0; float pairedControl[4]{};
    float nextTailDrive=0,nextTailYaw=0,gasRate=0,pumpPower=0,requestPower=0,brakeFraction=0;
};
inline V3 holdRandomRequest(const float* actions,float responsiveness,bool triangular,RandomGen& random) {
    if(triangular) return {0,0,0};
    const float moveRnd=actions[MOVE_RANDOM]*responsiveness;
    if(!(std::abs(moveRnd)>0.5f)) return {0,0,0};
    const float magnitude=std::abs(moveRnd);
    const float rx=random.range(-1.0f,1.0f)*magnitude;
    const float ry=random.range(-1.0f,1.0f)*magnitude;
    const float rz=random.range(-1.0f,1.0f)*magnitude;
    return {rx,-rz,ry};
}
// No draws here: caller captures the random bias and water exactly once.
inline bool adaptOuterActions(const Coefficients& c,const Support& support,const StepConfig& cfg,
    const HydroState& state,float energy,const float* actions,float responsiveness,bool triangular,
    bool ownFrame,V3 randomWorld,V3 waterWorld,HeldOuter& held) {
    if(!validConfig(cfg)||!std::isfinite(responsiveness)||!finite(randomWorld)||!finite(waterWorld)) return false;
    for(int i=0;i<NUM_ACTIONS;++i) if(!std::isfinite(actions[i])) return false;
    Loaded L;
    if(!loadAt(c,cfg.depth,state,energy,L)) return false;
    Requests r;
    if(triangular) {
        const float drive=std::clamp(0.5f*(actions[MOVE_FORWARD]+1.0f),0.0f,1.0f);
        r.speed=cfg.minRequestedSpeed+drive*(cfg.maxRequestedSpeed-cfg.minRequestedSpeed);
        r.yaw=responsiveness*actions[STEER_X];
    } else {
        r.speed=std::clamp(state.requestedSpeed+50.0f*responsiveness*actions[SPEED_ADJUST]*kOuterDt,
                           cfg.minRequestedSpeed,cfg.maxRequestedSpeed);
        if(ownFrame) {r.yaw=responsiveness*actions[STEER_X]; r.forwardBias=responsiveness*actions[STEER_Y];}
        else {
            const V3 b=unrotate(poseOf(state),{responsiveness*actions[STEER_X],0,responsiveness*actions[STEER_Y]});
            r.yaw=b.y; r.forwardBias=-b.x;
        }
        const V3 rnd=unrotate(poseOf(state),randomWorld);
        r.yaw+=rnd.y; r.dive-=rnd.z; r.forwardBias-=rnd.x;
        r.forwardBias+=responsiveness*actions[MOVE_FORWARD];
    }
    r.dive+=responsiveness*actions[STEER_Z];
    if(cfg.wallBand>0) {
        V3 sum{};
        for(int face=cfg.toroidal?4:0;face<6;++face) {
            const float gap=minimumGap(support,L,boundaries(cfg),state,face);
            sum=add(sum,mul(faceNormal(face),std::clamp(1.0f-gap/cfg.wallBand,0.0f,1.0f)));
        }
        const V3 b=unrotate(poseOf(state),sum);
        r.yaw+=b.y; r.dive-=b.z; r.forwardBias-=b.x;
    }
    r.yaw=std::clamp(r.yaw,-1.0f,1.0f); r.dive=std::clamp(r.dive,-1.0f,1.0f);
    r.forwardBias=std::clamp(r.forwardBias,-1.0f,1.0f);
    held={waterWorld,r}; return true;
}
inline float filterTail(float previous,float request,float tau) {
    const float a=kSubDt/tau; return (previous+a*request)/(1.0f+a);
}
inline V3 loadedLever(const float* p,const float* basis,const Loaded& L) {
    return sub(add(v3(p),mul(v3(basis),L.k-1.0f)),L.com);
}
inline bool incomingVelocity(const Loaded& L,const HydroState& state,V3 waterWorld,V6& z) {
    V3 omega;
    if(!materialOmega(L,state,omega)) return false;
    const V3 u=unrotate(poseOf(state),sub(v3(state.vGround),waterWorld));
    z={{u.x,u.y,u.z,omega.x,omega.y,omega.z}};
    return finite(z);
}
inline bool planActuators(const Coefficients& c,const Loaded& L,const HydroState& state,
    const StepConfig& cfg,const Requests& request,float bodyBuoy,const V6& incoming,ActuatorPlan& out) {
    if(!finite(incoming)||!(bodyBuoy>=0&&bodyBuoy<=1)||!std::isfinite(bodyBuoy)) return false;
    ActuatorPlan p;
    const V3 u{incoming.v[0],incoming.v[1],incoming.v[2]},omega{incoming.v[3],incoming.v[4],incoming.v[5]};
    const float U=std::sqrt(norm2(u));
    const float dragCoefficient=0.5f*rhoWater()*L.K[0]+at6(L.Dfin,0,0);
    const float targetDrag=(dragCoefficient*request.speed)*request.speed;
    const float effectiveForwardMass=at6(L.Meff,0,0);
    const float biasScale=effectiveForwardMass*kUref/calibration::kControllerTau;
    const float thrustRequest=targetDrag+effectiveForwardMass*(request.speed+u.x)/calibration::kControllerTau+
        biasScale*request.forwardBias;
    const float thrust=std::clamp(thrustRequest,0.0f,references().thrustCap);
    p.brakeFraction=std::clamp(-thrustRequest/references().thrustCap,0.0f,1.0f);
    p.nextTailDrive=filterTail(state.tailDrive,thrust/references().thrustCap,c.tailTau);
    p.nextTailYaw=filterTail(state.tailYaw,request.yaw,c.tailTau);
    auto channel=[&](V3 force,V3 lever,float efficiency) {
        p.channel[p.count++]={force,lever,efficiency};
        const V3 local=add(u,cross(omega,lever));
        p.requestPower+=std::sqrt(norm2(force))*(std::sqrt(norm2(local))+c.rowSpeed)/efficiency;
    };
    if(c.propArea>0) {
        if(c.caudalArea>0) {
            const V3 lever=loadedLever(c.caudalCentroid,c.caudalBasis,L);
            channel({-p.nextTailDrive*references().thrustCap*(c.caudalArea/c.propArea),0,0},lever,c.tailEfficiency);
            const float stiff=U/calibration::kTailStiffSpeed;
            const float fy=-calibration::kTailYawGain*(0.5f*rhoWater()*c.caudalArea)*
                (U*U+c.rowSpeed*c.rowSpeed)*p.nextTailYaw/(1.0f+stiff*stiff);
            channel({0,fy,0},lever,c.tailEfficiency);
        }
        for(int j=0;j<4;++j) if(c.pairedArea[j]>0) {
            const V3 lever=loadedLever(c.pairedCentroid+3*j,c.pairedBasis+3*j,L);
            const V3 normal=v3(c.pairedNormal+3*j),ln=cross(lever,normal);
            channel({-thrust*(0.5f*c.pairedArea[j]/c.propArea),0,0},lever,kPairedEfficiency);
            const float command=std::clamp(-calibration::kHeaveGain*request.dive*normal.z-
                calibration::kPairedYawGain*request.yaw*ln.z/c.refLength-
                calibration::kPitchGain*request.dive*ln.y/c.refLength,-1.0f,1.0f);
            p.pairedControl[j]=command;
            const V3 local=add(u,cross(omega,lever));
            const float magnitude=0.5f*rhoWater()*(norm2(local)+c.rowSpeed*c.rowSpeed)*c.pairedArea[j]*command;
            channel(mul(normal,magnitude),lever,kPairedEfficiency);
        }
    }
    if(c.gasCapacity>0) {
        const float depth=std::clamp(-state.com[1],0.0f,cfg.depth);
        const float P=pressure(depth,cfg.depth),hp=calibration::kPressureDepthFraction*cfg.depth;
        const float neutral=((L.mass/rhoWater()-c.hullVolume)-L.fuelVolume)-c.finVolume;
        const float target=std::clamp(neutral+calibration::kDepthGain*c.hullVolume*(depth-bodyBuoy*cfg.depth)/cfg.depth+
            calibration::kVerticalGain*c.hullVolume*(-state.vGround[1])/kUref,0.0f,c.gasCapacity);
        const float rate=calibration::kGasRateFraction*c.hullVolume;
        p.gasRate=std::clamp((P*target-state.gasContent)/calibration::kRegulatorTau,-rate,rate);
        const float gmax=pressure(cfg.depth,cfg.depth)*c.gasCapacity;
        p.gasRate=std::clamp(p.gasRate,-state.gasContent/kSubDt,(gmax-state.gasContent)/kSubDt);
        const float p0=rhoWater()*calibration::kGravity*hp;
        p.pumpPower=p0*std::abs(p.gasRate)/calibration::kPumpEfficiency;
        p.requestPower+=p.pumpPower;
    }
    if(!std::isfinite(p.requestPower)||!std::isfinite(p.gasRate)||!std::isfinite(p.brakeFraction)) return false;
    out=p; return true;
}
inline V6 activeWrench(const ActuatorPlan& p,float lambda) {
    V6 a{};
    for(int j=0;j<p.count;++j) {
        const V3 f=mul(p.channel[j].forceBody,lambda),t=cross(p.channel[j].leverBody,f);
        a.v[0]+=f.x; a.v[1]+=f.y; a.v[2]+=f.z;
        a.v[3]+=t.x; a.v[4]+=t.y; a.v[5]+=t.z;
    }
    return a;
}
inline S6 inducedDamping(const Coefficients& c,const Loaded& L,const V6& incoming,const ActuatorPlan& p,float lambda) {
    S6 D{};
    const V3 u{incoming.v[0],incoming.v[1],incoming.v[2]},omega{incoming.v[3],incoming.v[4],incoming.v[5]};
    for(int j=0;j<4;++j) if(c.pairedArea[j]>0) {
        const V3 lever=loadedLever(c.pairedCentroid+3*j,c.pairedBasis+3*j,L);
        const float command=lambda*p.pairedControl[j];
        const float cd=command*command/(bodyplan::detail::kPi*calibration::kPairedInducedEfficiency*c.pairedAspect[j]);
        const float d=0.5f*rhoWater()*c.pairedArea[j]*cd*std::sqrt(norm2(add(u,cross(omega,lever))));
        for(int axis=0;axis<3;++axis) {
            const V3 e=axis==0?V3{1,0,0}:(axis==1?V3{0,1,0}:V3{0,0,1});
            addRank1(D,wrench(e,lever),d);
        }
    }
    return D;
}
inline S6 brakeDamping(const Coefficients& c,const V6& incoming,const ActuatorPlan& p) {
    S6 D{}; const float speed=std::abs(incoming.v[0]);
    if(speed>0&&c.propArea>0) D.m[0]=p.brakeFraction*std::min(
        0.5f*rhoWater()*calibration::kBrakeCd*c.propArea*speed,references().thrustCap/speed);
    return D;
}
inline bool solveMechanics(const Coefficients& c,const Loaded& L,const HydroState& state,
    const V6& incoming,const S6& damping,const V6& active,V6& outgoing) {
    const Q4 q=poseOf(state);
    const V3 upBody=unrotate(q,kWorldUp);
    const float buoyantForce=calibration::kGravity*(rhoWater()*L.displaced-L.mass);
    const V3 gravityBody=mul(upBody,buoyantForce);
    const float offset=calibration::kMetacentricFraction*L.halfDepth;
    const float kMeta=(calibration::kGravity*rhoWater())*L.displaced*offset;
    const V3 righting=mul(cross(V3{0,0,1},upBody),kMeta);
    S6 A=L.Meff;
    for(int i=0;i<21;++i) A.m[i]=A.m[i]+kSubDt*damping.m[i];
    const float implicitRighting=(kSubDt*kSubDt)*kMeta;
    A.m[s6u(3,3)]=A.m[s6u(3,3)]+implicitRighting;
    A.m[s6u(4,4)]=A.m[s6u(4,4)]+implicitRighting;
    V6 rhs=mulS6(L.Meff,incoming);
    const float gravity[]={gravityBody.x,gravityBody.y,gravityBody.z};
    const float torque[]={righting.x,righting.y,righting.z};
    for(int i=0;i<3;++i) {
        rhs.v[i]=rhs.v[i]+kSubDt*(active.v[i]+gravity[i]);
        rhs.v[i+3]=(rhs.v[i+3]+kSubDt*active.v[i+3])+kSubDt*torque[i];
    }
    V6 candidate{};
    if(!solveScaled(A,rhs,c.halfLength,candidate)) return false;
    outgoing=candidate; return true;
}
inline void applyVelocityChange(HydroState& state,const Loaded& L,const V6& incoming,const V6& outgoing) {
    const Q4 q=poseOf(state);
    const V3 du{outgoing.v[0]-incoming.v[0],outgoing.v[1]-incoming.v[1],outgoing.v[2]-incoming.v[2]};
    const V3 dw{outgoing.v[3]-incoming.v[3],outgoing.v[4]-incoming.v[4],outgoing.v[5]-incoming.v[5]};
    put(state.vGround,add(v3(state.vGround),rotate(q,du)));
    put(state.LWorld,add(v3(state.LWorld),rotate(q,mulS3(L.inertia,dw))));
}
inline bool railVelocity(const Loaded& L,float maximum,V6& velocity,bool& railed) {
    V3 u{velocity.v[0],velocity.v[1],velocity.v[2]},w{velocity.v[3],velocity.v[4],velocity.v[5]};
    const float a=railScale(norm2(w),maximum);
    if(a<1) {
        if(!railProject(L.Meff,u,w,a)) return false;
        velocity={{u.x,u.y,u.z,w.x,w.y,w.z}}; railed=true;
    }
    return finite(velocity);
}
enum StepStage { kStepOK=0,kStepInput,kStepLoad,kStepPlan,kStepMotor,kStepSolve,kStepContact,kStepPose,kStepReserve,kStepBoundary };
struct SubstepReceipt {
    HydroState state{}; float energy=0,basal=0,maintenance=0,gene=0,unpaidBasal=0;
    MotorReceipt motor{}; ReserveReceipt reserve{}; ActuatorPlan plan{}; ContactReceipt contact{};
    V6 incoming{},outgoing{},external{}; float externalWork=0,penetration=0;
};
struct StepReceipt { SubstepReceipt substep[2]{}; int completed=0; StepStage failure=kStepOK; };
// The extra wrench is harness-only, body frame, explicitly metered. The public
// internal step signature below always passes zero. No runtime model selector.
template<class BeforeSubstep>
inline bool stepHydroWithSource(const Coefficients& c,const Support& support,const StepConfig& cfg,
    const HeldOuter& held,float bodyBuoy,std::size_t genomeLength,HydroState& state,float& foodReserves,
    StepReceipt* receipt,const V6& external,BeforeSubstep beforeSubstep) {
    HydroState s=state; float energy=foodReserves; StepReceipt out;
    auto refuse=[&](StepStage stage) {
        state.status|=kStatusFailure;
        if(receipt) receipt->failure=stage;
        return false;
    };
    if(!validConfig(cfg)||!finite(held.waterWorld)||!finite(external)||
        !(held.requests.speed>=cfg.minRequestedSpeed&&held.requests.speed<=cfg.maxRequestedSpeed)||
        !(std::abs(held.requests.yaw)<=1&&std::abs(held.requests.dive)<=1&&std::abs(held.requests.forwardBias)<=1)||
        !(bodyBuoy>=0&&bodyBuoy<=1)) return refuse(kStepInput);
    for(int substep=0;substep<2;++substep) {
        SubstepReceipt& r=out.substep[substep];
        if(!beforeSubstep(substep,s,energy)) return refuse(kStepReserve);
        Loaded L;
        if(!loadAt(c,cfg.depth,s,energy,L)||!incomingVelocity(L,s,held.waterWorld,r.incoming)) return refuse(kStepLoad);
        s.status=kStatusCompiled; s.requestedSpeed=held.requests.speed;
        r.basal=kSubDt*c.basalPower;
        r.maintenance=kSubDt*maintenancePower(c,energy);
        r.gene=kSubDt*(cfg.geneCost*float(genomeLength));
        const float demand=kSubDt*(c.basalPower+maintenancePower(c,energy)+cfg.geneCost*float(genomeLength));
        if(!(demand>=0)||!std::isfinite(demand)) return refuse(kStepInput);
        const float reserved=std::min(energy,demand);
        r.unpaidBasal=demand-reserved;
        if(!planActuators(c,L,s,cfg,held.requests,bodyBuoy,r.incoming,r.plan)) return refuse(kStepPlan);
        if(!limitMotor(c,energy-reserved,s.fatigue,r.plan.requestPower,references().workConversion,r.motor)) return refuse(kStepMotor);
        V6 active=activeWrench(r.plan,r.motor.lambda);
        for(int i=0;i<6;++i) active.v[i]=active.v[i]+external.v[i];
        r.external=external;
        S6 D=passiveDamping(L,c.halfLength,r.incoming);
        addTo(D,inducedDamping(c,L,r.incoming,r.plan,r.motor.lambda));
        addTo(D,brakeDamping(c,r.incoming,r.plan));
        if(!solveMechanics(c,L,s,r.incoming,D,active,r.outgoing)) return refuse(kStepSolve);
        bool railed=false;
        if(!railVelocity(L,cfg.maxAngularSpeed,r.outgoing,railed)) return refuse(kStepSolve);
        const V3 waterBody=unrotate(poseOf(s),held.waterWorld);
        if(!predictContact(c,support,L,boundaries(cfg),s,waterBody,r.outgoing,r.contact)) return refuse(kStepContact);
        // Contact can also change angular speed. Keep the rail explicit after
        // the refreshed load below; no fuel refund for either projection.
        applyVelocityChange(s,L,r.incoming,r.outgoing);
        r.externalWork=kSubDt*dot6(external,r.outgoing);
        put(s.com,add(v3(s.com),mul(v3(s.vGround),kSubDt)));
        bool poseOK=false;
        const Q4 q=integrate(poseOf(s),{r.outgoing.v[3],r.outgoing.v[4],r.outgoing.v[5]},kSubDt,&poseOK);
        if(!poseOK) return refuse(kStepPose);
        s.quat[0]=q.w; s.quat[1]=q.x; s.quat[2]=q.y; s.quat[3]=q.z;
        s.gasContent=s.gasContent+kSubDt*r.motor.lambda*r.plan.gasRate;
        s.tailDrive=r.plan.nextTailDrive; s.tailYaw=r.plan.nextTailYaw; s.fatigue=r.motor.nextFatigue;
        if(!changeReserve(c,cfg.depth,s,energy,-(reserved+r.motor.fuel),nullptr,r.reserve)) return refuse(kStepReserve);
        Loaded refreshed; V6 before{},after{};
        if(!loadAt(c,cfg.depth,s,energy,refreshed)||!incomingVelocity(refreshed,s,held.waterWorld,before)) return refuse(kStepLoad);
        after=before;
        if(!railVelocity(refreshed,cfg.maxAngularSpeed,after,railed)) return refuse(kStepSolve);
        applyVelocityChange(s,refreshed,before,after);
        if(!resolveBoundaries(c,support,refreshed,boundaries(cfg),s,r.penetration)) return refuse(kStepBoundary);
        if(r.contact.count) s.status|=kStatusContact;
        if(railed) s.status|=kStatusRailed;
        if(!validState(s)) return refuse(kStepBoundary);
        r.state=s; r.energy=energy; ++out.completed;
    }
    state=s; foodReserves=energy; if(receipt) *receipt=out;
    return true;
}
inline bool stepHydroWithExternal(const Coefficients& c,const Support& support,const StepConfig& cfg,
    const HeldOuter& held,float bodyBuoy,std::size_t genomeLength,HydroState& state,float& foodReserves,
    StepReceipt* receipt,const V6& external) {
    return stepHydroWithSource(c,support,cfg,held,bodyBuoy,genomeLength,state,foodReserves,receipt,external,
        [](int,HydroState&,float&){return true;});
}
inline bool stepHydro(const Coefficients& c,const Support& support,const StepConfig& cfg,const HeldOuter& held,
    float bodyBuoy,std::size_t genomeLength,HydroState& state,float& foodReserves,StepReceipt* receipt) {
    return stepHydroWithExternal(c,support,cfg,held,bodyBuoy,genomeLength,state,foodReserves,receipt,V6{});
}
} // namespace hydro

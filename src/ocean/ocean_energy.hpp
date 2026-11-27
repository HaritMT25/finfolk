#pragma once
// Sole-ledger transactions. Every public result is committed atomically.
#include <algorithm>
#include "hydro_coefficients.hpp"
#include "hydro_state.hpp"

namespace hydro {
inline constexpr float kOuterDt = 0.016f;
inline constexpr float kSubDt = 0.008f;
struct Parcel {
    float energy = 0.0f;
    V3 pointWorld{0,0,0}, velocityWorld{0,0,0}, spinPerMassWorld{0,0,0};
};
struct ReserveReceipt {
    float accepted = 0, spent = 0, waste = 0, unpaid = 0;
    Parcel removed{};
};
struct MotorReceipt {
    float lambda = 0, requestPower = 0, actualPower = 0, aerobicPower = 0,
          burstPower = 0, fuel = 0, nextFatigue = 0;
};
inline bool finite(V3 v) { return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z); }
inline bool finite(const V6& v) { for(float x : v.v) if(!std::isfinite(x)) return false; return true; }
inline float pressure(float depth, float tankDepth) {
    const float hp = calibration::kPressureDepthFraction * tankDepth;
    return 1.0f + depth / hp;
}
inline float maintenancePower(const Coefficients& c, float energy) {
    return c.maintenancePower + kMaintLipid * (fuelMass(energy) / references().fuelMass);
}
inline bool validState(const HydroState& s) {
    bool ok = true;
    forEachStateWord(s, [&](std::uint32_t) {}); // Hash traversal remains separate from validation.
    const float* groups[] = {s.com,s.vGround,s.quat,s.LWorld};
    const int counts[] = {3,3,4,3};
    for(int i=0;i<4;++i) for(int j=0;j<counts[i];++j) ok = ok && std::isfinite(groups[i][j]);
    for(float x : {s.gasContent,s.tailDrive,s.tailYaw,s.requestedSpeed,s.fatigue}) ok = ok && std::isfinite(x);
    const float q2 = qnorm2(poseOf(s));
    return ok && std::abs(q2-1.0f) <= 2e-5f && s.fatigue >= 0 &&
        (s.status & kStatusCompiled) && !(s.status & ~(kStatusCompiled|kStatusContact|kStatusRailed));
}
inline bool loadAt(const Coefficients& c, float tankDepth, const HydroState& s, float energy, Loaded& out) {
    if (!(tankDepth > 0) || !std::isfinite(tankDepth) || !validState(s) ||
        !(energy >= 0 && energy <= c.energyCapacity) || !std::isfinite(energy) ||
        !(s.fatigue <= c.fatigueCapacity)) return false;
    const float p = pressure(std::clamp(-s.com[1],0.0f,tankDepth),tankDepth);
    const float gmax = pressure(tankDepth,tankDepth)*c.gasCapacity;
    if (!(s.gasContent >= 0 && s.gasContent <= gmax) || !std::isfinite(gmax)) return false;
    Loaded next;
    if(!evalLoad(c,std::min(c.gasCapacity,s.gasContent/p),fuelMass(energy),next)) return false;
    out=next;
    return true;
}
inline bool materialOmega(const Loaded& L, const HydroState& s, V3& out) {
    S3 inv;
    if(!invS3(L.inertia,inv)) return false;
    const V3 w = mulS3(inv,unrotate(poseOf(s),v3(s.LWorld)));
    if(!finite(w)) return false;
    out=w; return true;
}
inline bool limitMotor(const Coefficients& c, float availableEnergy, float fatigue,
                       float requestPower, float workConversion, MotorReceipt& out) {
    MotorReceipt r{};
    if (!(availableEnergy >= 0) || !(fatigue >= 0 && fatigue <= c.fatigueCapacity) ||
        !(requestPower >= 0) || !(workConversion > 0) || !std::isfinite(availableEnergy) ||
        !std::isfinite(fatigue) || !std::isfinite(requestPower) || !std::isfinite(workConversion)) return false;
    const float excess = c.peakPower-c.sustainedPower;
    if (!(c.sustainedPower >= 0) || !(excess >= 0) || !std::isfinite(excess)) return false;
    const float availablePower = c.sustainedPower + std::min(excess,std::max(0.0f,(c.fatigueCapacity-fatigue)/kSubDt));
    const float qFuel = availableEnergy/(workConversion*kSubDt);
    const float fuelPower = qFuel <= c.sustainedPower ? qFuel : (qFuel+2.0f*c.sustainedPower)/3.0f;
    float lambda = availableEnergy > 0 ? 1.0f : 0.0f;
    if(requestPower > 0) lambda=std::min(lambda,std::min(availablePower/requestPower,fuelPower/requestPower));
    r.lambda=lambda; r.requestPower=requestPower; r.actualPower=lambda*requestPower;
    r.aerobicPower=std::min(r.actualPower,c.sustainedPower);
    r.burstPower=std::max(0.0f,r.actualPower-c.sustainedPower);
    const float requestedFuel=(workConversion*kSubDt)*(r.aerobicPower+3.0f*r.burstPower);
    r.fuel=std::min(availableEnergy,requestedFuel);
    const float recovery=std::min(fatigue/kSubDt,kGamma*std::max(0.0f,c.sustainedPower-r.actualPower));
    r.nextFatigue=std::clamp(fatigue+kSubDt*(r.burstPower-recovery),0.0f,c.fatigueCapacity);
    if(!std::isfinite(r.actualPower)||!std::isfinite(r.fuel)||!std::isfinite(r.nextFatigue)) return false;
    out=r; return true;
}
inline bool finite(const Parcel& p) {
    return std::isfinite(p.energy) && p.energy >= 0 && finite(p.pointWorld) &&
        finite(p.velocityWorld) && finite(p.spinPerMassWorld);
}
inline bool comovingParcel(const Coefficients& c, const Loaded& L, const HydroState& s, float energy, Parcel& p) {
    V3 omega;
    if(!materialOmega(L,s,omega)) return false;
    const Q4 q=poseOf(s);
    const V3 r=rotate(q,sub(L.hullCentroid,L.com));
    S3 covariance{};
    for(int i=0;i<6;++i) covariance.m[i]=c.hullCovariance[i];
    p.energy=energy;
    p.pointWorld=add(v3(s.com),r);
    p.velocityWorld=add(v3(s.vGround),cross(rotate(q,omega),r));
    p.spinPerMassWorld=rotate(q,mulS3(inertiaOf(stretchS3(covariance,L.k)),omega));
    return finite(p);
}
inline bool changeReserve(const Coefficients& c, float tankDepth, HydroState& state,
                          float& foodReserves, float requestedDelta, const Parcel* incoming, ReserveReceipt& receipt) {
    Loaded L;
    if(!std::isfinite(requestedDelta)||!loadAt(c,tankDepth,state,foodReserves,L)) return false;
    const float sum=foodReserves+requestedDelta;
    if(!std::isfinite(sum)) return false;
    const float target=std::clamp(sum,0.0f,c.energyCapacity);
    ReserveReceipt r{};
    r.accepted=std::max(0.0f,target-foodReserves);
    r.spent=std::max(0.0f,foodReserves-target);
    r.waste=std::max(0.0f,requestedDelta-r.accepted);
    r.unpaid=std::max(0.0f,-requestedDelta-r.spent);
    Parcel p{};
    if(requestedDelta > 0) {
        if(!incoming || !finite(*incoming)) return false;
        p=*incoming;
    } else if(!comovingParcel(c,L,state,r.spent,p)) return false;
    if(requestedDelta < 0) r.removed=p;
    HydroState next=state;
    const float dm=fuelMass(target)-fuelMass(foodReserves);
    const float newMass=c.leanMass+fuelMass(target);
    if(!(newMass>0)||!std::isfinite(newMass)) return false;
    if(dm!=0) {
        const V3 oldCom=v3(state.com), oldVelocity=v3(state.vGround);
        const V3 offset=sub(p.pointWorld,oldCom);
        const float fraction=dm/newMass;
        const V3 newCom=add(oldCom,mul(offset,fraction));
        const V3 newVelocity=add(oldVelocity,mul(sub(p.velocityWorld,oldVelocity),fraction));
        const V3 spinAndOrbital=add(p.spinPerMassWorld,cross(offset,sub(p.velocityWorld,newVelocity)));
        put(next.com,newCom); put(next.vGround,newVelocity);
        put(next.LWorld,add(v3(state.LWorld),mul(spinAndOrbital,dm)));
    }
    Loaded refreshed;
    if(!loadAt(c,tankDepth,next,target,refreshed)) return false;
    state=next; foodReserves=target; receipt=r;
    return true;
}
struct TransferReceipt { ReserveReceipt donor{}, receiver{}; };
inline bool transferReserve(const Coefficients& dc, const Coefficients& rc, float depth,
    HydroState& donor, float& donorEnergy, HydroState& receiver, float& receiverEnergy,
    float requested, TransferReceipt& receipt) {
    if(&donor==&receiver || &donorEnergy==&receiverEnergy || !(requested>=0) || !std::isfinite(requested)) return false;
    HydroState d=donor,r=receiver; float de=donorEnergy,re=receiverEnergy;
    TransferReceipt out;
    const float amount=std::min(requested,de);
    if(!changeReserve(dc,depth,d,de,-amount,nullptr,out.donor) ||
       !changeReserve(rc,depth,r,re,out.donor.spent,&out.donor.removed,out.receiver)) return false;
    donor=d; receiver=r; donorEnergy=de; receiverEnergy=re; receipt=out;
    return true;
}
inline bool shareReserves(const Coefficients& ac,const Coefficients& bc,float depth,
    HydroState& a,float& ae,HydroState& b,float& be,TransferReceipt& r) {
    if(!std::isfinite(ae)||!std::isfinite(be)) return false;
    return ae>=be ? transferReserve(ac,bc,depth,a,ae,b,be,(ae-be)*0.5f,r)
                  : transferReserve(bc,ac,depth,b,be,a,ae,(be-ae)*0.5f,r);
}
inline bool fightTransfer(const Coefficients& winnerC,const Coefficients& loserC,float depth,
    HydroState& winner,float& we,HydroState& loser,float& le,float requested,TransferReceipt& r) {
    return transferReserve(loserC,winnerC,depth,loser,le,winner,we,requested,r);
}
} // namespace hydro

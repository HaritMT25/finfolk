#pragma once
// Tool-only calorimetry telemetry, adapted from the preserved diagnosis-2 audit.
#include "ocean_hydro_harness.hpp"
#include "ocean_hydro_measurements.hpp"
namespace hydroassay {
using namespace hydro;
inline constexpr double deg=kDegrees;
struct CruiseStats {
    double basal=0,maint=0,gene=0,motor=0,debit=0,gasFuel=0,controlFuel=0,forwardFuel=0;
    double gasAbs=0,gasSigned=0,maxGasRate=0,maxControl=0,maxVertical=0;
    double pitch=0,roll=0,vertical=0,horizontal=0,forward=0,bodyVertical=0,lambdaMin=1;
    double depthMin=1e9,depthMax=-1e9,pitchMin=1e9,pitchMax=-1e9;
    double firstDepth=0,lastDepth=0,gasStart=0,gasEnd=0,heading=0,previousHeading=0;
    double buoy=0,activeUp=0,dragUp=0;
    int count=0,gasActive=0,controlActive=0,contacts=0,rails=0;
    bool debitAccounted=true,pricesAccounted=true,motorAccounted=true;
    double maxPriceError=0,ledgerRounding=0,maxFuelError=0;
    explicit CruiseStats(const HydroState& s):firstDepth(-s.com[1]),gasStart(s.gasContent) {
        const auto f=rotate(poseOf(s),{-1,0,0});previousHeading=std::atan2(double(f.z),double(f.x));
    }
    void observe(const hydroharness::Columns& h,const SubstepReceipt& r,const HydroState& incoming) {
        Loaded load;if(!loadAt(h.coefficients[0],h.config.depth,r.state,25,load))throw std::runtime_error("cal4 load");
        buoy+=calibration::kGravity*(double(rhoWater())*load.displaced-load.mass);
        const V6 act=activeWrench(r.plan,r.motor.lambda);
        const V6 drag=mulS6(passiveDamping(load,h.coefficients[0].halfLength,r.incoming),r.outgoing);
        activeUp+=rotate(poseOf(r.state),{act.v[0],act.v[1],act.v[2]}).y;
        dragUp-=rotate(poseOf(r.state),{drag.v[0],drag.v[1],drag.v[2]}).y;
        basal+=r.basal;maint+=r.maintenance;gene+=r.gene;motor+=r.motor.fuel;debit+=r.reserve.spent;
        const auto& p=r.plan;double forwards=0,controls=0;float channelPower=0;
        const V3 u{r.incoming.v[0],r.incoming.v[1],r.incoming.v[2]},w{r.incoming.v[3],r.incoming.v[4],r.incoming.v[5]};
        for(int j=0;j<p.count;++j) {
            const auto& c=p.channel[j];const auto local=add(u,cross(w,c.leverBody));
            const float power=std::sqrt(norm2(c.forceBody))*(std::sqrt(norm2(local))+h.coefficients[0].rowSpeed)/c.efficiency;
            channelPower+=power;
            if(j%2==0)forwards+=power;else controls+=power;
        }
        if(p.requestPower>0) {
            gasFuel+=r.motor.fuel*double(p.pumpPower)/p.requestPower;
            forwardFuel+=r.motor.fuel*forwards/p.requestPower;
            controlFuel+=r.motor.fuel*controls/p.requestPower;
        }
        // Rebuild pump work from the actual incoming load, gas content and
        // regulator law, independently of the plan's stored pump price.
        const auto& c=h.coefficients[0];Loaded initial;
        if(!loadAt(c,h.config.depth,incoming,25,initial))throw std::runtime_error("cal4 incoming load");
        const float depth=std::clamp(-incoming.com[1],0.f,h.config.depth);
        const float hp=calibration::kPressureDepthFraction*h.config.depth;
        const float neutral=((initial.mass/rhoWater()-c.hullVolume)-initial.fuelVolume)-c.finVolume;
        const float target=std::clamp(neutral+calibration::kDepthGain*c.hullVolume*(depth-h.fish[0].bodyBuoy*h.config.depth)/h.config.depth+
            calibration::kVerticalGain*c.hullVolume*(-incoming.vGround[1])/kUref,0.f,c.gasCapacity);
        const float rate=calibration::kGasRateFraction*c.hullVolume;
        float gas=std::clamp((pressure(depth,h.config.depth)*target-incoming.gasContent)/calibration::kRegulatorTau,-rate,rate);
        gas=std::clamp(gas,-incoming.gasContent/kSubDt,(pressure(h.config.depth,h.config.depth)*c.gasCapacity-incoming.gasContent)/kSubDt);
        const float pump=(rhoWater()*calibration::kGravity*hp)*std::abs(gas)/calibration::kPumpEfficiency;
        const float independentPower=channelPower+pump; // pump exactly once
        pricesAccounted=pricesAccounted&&p.gasRate==gas&&p.pumpPower==pump;
        const double priceError=std::abs(independentPower-p.requestPower)/std::max(1.0,double(independentPower));
        maxPriceError=std::max(maxPriceError,priceError);
        pricesAccounted=pricesAccounted&&priceError<=2e-5;
        // Fixed incoming 25 E. Reproduce the sole-ledger subtraction, not a
        // broad error budget on the accumulated component partition.
        const float demand=kSubDt*(h.coefficients[0].basalPower+maintenancePower(h.coefficients[0],25)+
            0.f);
        // Binary32 reconstruction of the prescribed motor/fatigue formula.
        // Do not call limitMotor or trust the receipt's priced fuel.
        const float available=25.f-demand;
        const float excess=c.peakPower-c.sustainedPower;
        const float capacityPower=c.sustainedPower+std::min(excess,std::max(0.f,(c.fatigueCapacity-incoming.fatigue)/kSubDt));
        const float conversion=references().workConversion;
        const float q=available/(conversion*kSubDt);
        const float fuelPower=q<=c.sustainedPower?q:(q+2.f*c.sustainedPower)/3.f;
        const float lambda=independentPower>0?std::min(1.f,std::min(capacityPower/independentPower,fuelPower/independentPower)):1.f;
        const float actualPower=lambda*independentPower;
        const float aerobic=std::min(actualPower,c.sustainedPower),burst=std::max(0.f,actualPower-c.sustainedPower);
        const float fuel=std::min(available,(conversion*kSubDt)*(aerobic+3.f*burst));
        const float recovery=std::min(incoming.fatigue/kSubDt,kGamma*std::max(0.f,c.sustainedPower-actualPower));
        const float fatigue=std::clamp(incoming.fatigue+kSubDt*(burst-recovery),0.f,c.fatigueCapacity);
        maxFuelError=std::max(maxFuelError,double(std::abs(fuel-r.motor.fuel)));
        motorAccounted=motorAccounted&&r.motor.lambda==lambda&&r.motor.actualPower==actualPower&&
            r.motor.aerobicPower==aerobic&&r.motor.burstPower==burst&&r.motor.fuel==fuel&&r.motor.nextFatigue==fatigue&&r.state.fatigue==fatigue;
        const float requested=demand+fuel;
        const float actual=25.f-(25.f-requested);
        debitAccounted=debitAccounted&&r.reserve.spent==actual&&r.energy==25.f-actual&&r.unpaidBasal==0&&r.reserve.unpaid==std::max(0.f,requested-actual)&&
            r.basal==kSubDt*c.basalPower&&r.maintenance==kSubDt*maintenancePower(c,25)&&r.gene==0;
        ledgerRounding+=double(actual)-r.basal-r.maintenance-r.gene-r.motor.fuel;
        const double actualGas=r.motor.lambda*double(p.gasRate);
        gasAbs+=std::abs(actualGas)*double(kSubDt);gasSigned+=actualGas*double(kSubDt);
        maxGasRate=std::max(maxGasRate,std::abs(actualGas));gasActive+=p.gasRate!=0;
        for(float a:p.pairedControl) {maxControl=std::max(maxControl,double(std::abs(a)));controlActive+=a!=0;}
        const auto f=rotate(poseOf(r.state),{-1,0,0}),up=rotate(poseOf(r.state),{0,0,1});
        const double theta=std::atan2(double(f.y),std::hypot(double(f.x),double(f.z)))*deg;
        pitch+=theta;pitchMin=std::min(pitchMin,theta);pitchMax=std::max(pitchMax,theta);
        roll+=std::atan2(double(rotate(poseOf(r.state),{0,1,0}).y),double(up.y))*deg;
        const double angle=std::atan2(double(f.z),double(f.x));heading+=std::remainder(angle-previousHeading,2*3.141592653589793);previousHeading=angle;
        const auto v=unrotate(poseOf(r.state),v3(r.state.vGround));forward-=v.x;bodyVertical+=v.z;
        vertical+=r.state.vGround[1];horizontal+=std::hypot(double(r.state.vGround[0]),double(r.state.vGround[2]));
        maxVertical=std::max(maxVertical,double(std::abs(r.state.vGround[1])));
        lastDepth=-r.state.com[1];depthMin=std::min(depthMin,lastDepth);depthMax=std::max(depthMax,lastDepth);
        lambdaMin=std::min(lambdaMin,double(r.motor.lambda));gasEnd=r.state.gasContent;
        contacts+=r.contact.count;rails+=(r.state.status&kStatusRailed)!=0;++count;
    }
    void print(const char* name,double duration,std::FILE* output=stdout) const {
        std::fprintf(output,"CAL4,name=%s,samples=%d,seconds=%.12g,basal=%.12g,maintenance=%.12g,motor=%.12g,total=%.12g,"
          "debit=%.12g,gene=%.12g,gas_E=%.12g,forward_E=%.12g,control_E=%.12g,pitch_deg=%.12g,pitch_range=%.12g/%.12g,roll_deg=%.12g,"
          "horizontal_speed=%.12g,body_forward=%.12g,body_vertical=%.12g,climb_rate=%.12g,max_abs_vertical=%.12g,depth_start=%.12g,depth_end=%.12g,"
          "depth_min=%.12g,depth_max=%.12g,depth_drift=%.12g,heading_change_deg=%.12g,gas_abs=%.12g,gas_integral=%.12g,gas_start=%.12g,gas_end=%.12g,"
          "gas_active=%d,max_gas_rate=%.12g,control_active=%d,max_paired_control=%.12g,lambda_min=%.12g,contacts=%d,rails=%d\n",
          name,count,duration,basal/duration,maint/duration,motor/duration,debit/duration,debit,gene,gasFuel,forwardFuel,controlFuel,
          pitch/count,pitchMin,pitchMax,roll/count,horizontal/count,forward/count,bodyVertical/count,vertical/count,maxVertical,
          firstDepth,lastDepth,depthMin,depthMax,lastDepth-firstDepth,heading*deg,gasAbs,gasSigned,gasStart,gasEnd,gasActive,maxGasRate,controlActive,maxControl,lambdaMin,contacts,rails);
        std::fprintf(output,"TRIM_FORCE,name=%s,buoy_up=%.12g,active_up=%.12g,drag_up=%.12g,net=%.12g\n",name,buoy/count,activeUp/count,dragUp/count,(buoy+activeUp+dragUp)/count);
    }
};
} // namespace hydroassay

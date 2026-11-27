#pragma once
// Native-only trajectory comparisons. The caller supplies the independently
// integrated material/hull/fin laws from the PR 1 oracle, never production
// Meff, damping, active wrench or RHS. Dense double solves use pivoting.
#include "ocean/hydro_step.hpp"
#include <cstdio>
#include <string>
namespace hydroref2 {
using namespace hydro;
inline double worstIncrement=0,worstResidual=0,worstActuator=0;
inline int checks=0,actuatorChecks=0,trajectoryChecks=0,failed=0;
inline std::string incrementWhere,residualWhere,actuatorWhere;
inline double largestPowerDifference=0,powerActual=0,powerExpected=0,powerScale=0;
inline std::string powerWhere;
inline bool denseSolve(const double a[6][6],const double b[6],double x[6]) {
    double g[6][7]{};
    for(int i=0;i<6;++i){for(int j=0;j<6;++j)g[i][j]=a[i][j];g[i][6]=b[i];}
    for(int p=0;p<6;++p) {
        int pivot=p;for(int i=p+1;i<6;++i)if(std::abs(g[i][p])>std::abs(g[pivot][p]))pivot=i;
        if(!(std::abs(g[pivot][p])>0))return false;
        for(int j=p;j<7;++j)std::swap(g[p][j],g[pivot][j]);
        for(int i=p+1;i<6;++i){const double f=g[i][p]/g[p][p];for(int j=p;j<7;++j)g[i][j]-=f*g[p][j];}
    }
    for(int i=5;i>=0;--i){double v=g[i][6];for(int j=i+1;j<6;++j)v-=g[i][j]*x[j];x[i]=v/g[i][i];}
    for(int i=0;i<6;++i)if(!std::isfinite(x[i]))return false;
    return true;
}
struct Vec { double x=0,y=0,z=0; };
inline Vec plus(Vec a,Vec b){return {a.x+b.x,a.y+b.y,a.z+b.z};}
inline Vec minus(Vec a,Vec b){return {a.x-b.x,a.y-b.y,a.z-b.z};}
inline Vec times(Vec a,double b){return {a.x*b,a.y*b,a.z*b};}
inline Vec vectorProduct(Vec a,Vec b){return {a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};}
inline double magnitude(Vec a){return std::sqrt(a.x*a.x+a.y*a.y+a.z*a.z);}
inline Vec from(V3 v){return {v.x,v.y,v.z};}
inline Vec matrix3(const double a[3][3],Vec x) {
    return {a[0][0]*x.x+a[0][1]*x.y+a[0][2]*x.z,
            a[1][0]*x.x+a[1][1]*x.y+a[1][2]*x.z,
            a[2][0]*x.x+a[2][1]*x.y+a[2][2]*x.z};
}
struct Model {
    double mass[6][6]{},inertia[3][3]{},finD[6][6]{},J[3][3]{},K[3]{};
    double rw=0,materialMass=0,displaced=0,halfDepth=0,length=0;
    double finW[7][6]{},finCoefficient[7]{};
    Vec lever[7]{},normal[7]{};
    double area[7]{},aspect[7]{},hullVolume=0,finVolume=0,fuelVolume=0,gasVolume=0;
};
inline void damping(const Model& m,const double z[6],double d[6][6],bool withFins=true) {
    double norm=0;for(int i=0;i<6;++i)norm+=z[i]*z[i]*(i<3?1:m.length*m.length);
    const double speed=std::sqrt(norm);
    for(int i=0;i<6;++i)for(int j=0;j<6;++j){
        d[i][j]=withFins?speed*m.finD[i][j]:0;
        if(i<3&&i==j)d[i][j]+=.5*m.rw*m.K[i]*std::abs(z[i]);
        if(i>=3&&j>=3)d[i][j]+=.5*m.rw*speed*m.J[i-3][j-3];
    }
}
inline bool advance(const Model& m,const double z[6],const double up[3],double out[6],bool patches=false,
                    const double* active=nullptr) {
    double d[6][6],a[6][6]{},rhs[6]{};damping(m,z,d,!patches);
    const double meta=double(calibration::kGravity)*m.rw*m.displaced*calibration::kMetacentricFraction*m.halfDepth;
    const double buoy=double(calibration::kGravity)*(m.rw*m.displaced-m.materialMass);
    const double dt=double(kSubDt);
    for(int i=0;i<6;++i)for(int j=0;j<6;++j){a[i][j]=m.mass[i][j]+dt*d[i][j];rhs[i]+=m.mass[i][j]*z[j];}
    for(int i=0;i<3;++i)rhs[i]+=dt*buoy*up[i];
    if(active)for(int i=0;i<6;++i)rhs[i]+=dt*active[i];
    rhs[3]-=dt*meta*up[1];rhs[4]+=dt*meta*up[0];
    a[3][3]+=dt*dt*meta;a[4][4]+=dt*dt*meta;
    if(!denseSolve(a,rhs,out))return false;
    if(patches) {
        // Sequential implicit rank-one updates in the seven-fin law order.
        for(int f=0;f<7;++f) {
            double slip=0,response[6]{},w[6];for(int i=0;i<6;++i){w[i]=m.finW[f][i];slip+=w[i]*out[i];}
            if(!denseSolve(m.mass,w,response))return false;
            double effective=0;for(int i=0;i<6;++i)effective+=w[i]*response[i];
            const double weight=dt*m.finCoefficient[f]*std::abs(slip);
            const double impulse=-weight*slip/(1+weight*effective);
            for(int i=0;i<6;++i)out[i]+=response[i]*impulse;
        }
    }
    return true;
}
inline void check(const Coefficients& c,const Loaded& L,const Model& model,const V6& z,const std::string& name) {
    const HydroState s=restState({0,-120,0},{0,0,0},{1,0,0});
    const S6 dampingProduction=passiveDamping(L,c.halfLength,z);
    V6 production;const bool ok=solveMechanics(c,L,s,z,dampingProduction,V6{},production);
    double input[6],expected[6]{},up[]={0,0,1};for(int i=0;i<6;++i)input[i]=z.v[i];
    if(!ok||!advance(model,input,up,expected)){worstIncrement=INFINITY;return;}
    double difference=0,scale=0;
    for(int i=0;i<6;++i){const double unit=i<3?1:model.length;difference+=std::pow(unit*(production.v[i]-expected[i]),2);scale+=std::pow(unit*expected[i],2);}
    const double increment=std::sqrt(difference/std::max(scale,1e-30));
    if(increment>worstIncrement){worstIncrement=increment;incrementWhere=name;}++checks;
    // Residual against the independently assembled matrix and RHS.
    double d[6][6];damping(model,input,d);
    const double dt=double(kSubDt),meta=double(calibration::kGravity)*model.rw*model.displaced*
        calibration::kMetacentricFraction*model.halfDepth;
    double residual=0,rhsNorm=0;
    for(int i=0;i<6;++i){
        double lhs=0,rhs=0;
        for(int j=0;j<6;++j){lhs+=(model.mass[i][j]+dt*d[i][j])*production.v[j];rhs+=model.mass[i][j]*input[j];}
        if(i==3||i==4)lhs+=dt*dt*meta*production.v[i];
        if(i==2)rhs+=dt*double(calibration::kGravity)*(model.rw*model.displaced-model.materialMass);
        const double unit=i<3?1:1/model.length;
        residual+=std::pow(unit*(lhs-rhs),2);rhsNorm+=std::pow(unit*rhs,2);
    }
    const double error=std::sqrt(residual/std::max(rhsNorm,1e-30));
    if(error>worstResidual){worstResidual=error;residualWhere=name;}
}
// Birth scalar parameters (tau, efficiency, global force ceiling) are inputs.
// Material, load, levers, areas, passive tensors, active wrenches and RHS are
// independently assembled here; no production matrix/plan enters this law.
struct Plan {
    Vec force[10]{},lever[10]{};double efficiency[10]{};int count=0;
    double wrench[6]{},power=0,gasRate=0,pump=0,tailDrive=0,tailYaw=0;
};
inline Plan actuator(const Coefficients& c,const Model& m,const double z[6],Requests request,
                     double previousDrive,double previousYaw,double gas,double depth,double verticalWorld) {
    Plan p;
    const Vec u{z[0],z[1],z[2]},omega{z[3],z[4],z[5]};
    const double U=magnitude(u),cap=references().thrustCap;
    double prop=m.area[0];for(int f=3;f<7;++f)prop+=.5*m.area[f];
    const double row=prop>0?std::sqrt(2*cap/(m.rw*prop)):0;
    const double drag=.5*m.rw*m.K[0]+m.finD[0][0];
    const double thrust=std::clamp(drag*request.speed*request.speed+
        m.mass[0][0]*(request.speed+z[0]+double(kUref)*request.forwardBias)/calibration::kControllerTau,0.0,cap);
    const double a=double(kSubDt)/c.tailTau;
    p.tailDrive=(previousDrive+a*thrust/cap)/(1+a);
    p.tailYaw=(previousYaw+a*request.yaw)/(1+a);
    auto channel=[&](Vec force,Vec lever,double efficiency) {
        const int n=p.count++;p.force[n]=force;p.lever[n]=lever;p.efficiency[n]=efficiency;
        const Vec torque=vectorProduct(lever,force);
        const double w[]={force.x,force.y,force.z,torque.x,torque.y,torque.z};
        for(int i=0;i<6;++i)p.wrench[i]+=w[i];
        p.power+=magnitude(force)*(magnitude(plus(u,vectorProduct(omega,lever)))+row)/efficiency;
    };
    if(prop>0) {
        if(m.area[0]>0) {
            channel({-p.tailDrive*cap*m.area[0]/prop,0,0},m.lever[0],c.tailEfficiency);
            const double stiff=U/calibration::kTailStiffSpeed;
            channel({0,-calibration::kTailYawGain*.5*m.rw*m.area[0]*(U*U+row*row)*p.tailYaw/(1+stiff*stiff),0},
                    m.lever[0],c.tailEfficiency);
        }
        for(int f=3;f<7;++f)if(m.area[f]>0) {
            channel({-thrust*.5*m.area[f]/prop,0,0},m.lever[f],kPairedEfficiency);
            const Vec arm=vectorProduct(m.lever[f],m.normal[f]);
            const double command=std::clamp(-calibration::kHeaveGain*request.dive*m.normal[f].z-
                calibration::kPairedYawGain*request.yaw*arm.z/c.refLength-
                calibration::kPitchGain*request.dive*arm.y/c.refLength,-1.0,1.0);
            const double local=magnitude(plus(u,vectorProduct(omega,m.lever[f])));
            channel(times(m.normal[f],.5*m.rw*(local*local+row*row)*m.area[f]*command),m.lever[f],kPairedEfficiency);
        }
    }
    if(c.gasCapacity>0) {
        const double D=240,hp=calibration::kPressureDepthFraction*D,P=1+std::clamp(depth,0.0,D)/hp;
        const double target=std::clamp(m.materialMass/m.rw-m.hullVolume-m.fuelVolume-m.finVolume+
            calibration::kDepthGain*m.hullVolume*(std::clamp(depth,0.0,D)-.5*D)/D+
            calibration::kVerticalGain*m.hullVolume*(-verticalWorld)/kUref,0.0,double(c.gasCapacity));
        const double rate=calibration::kGasRateFraction*m.hullVolume;
        p.gasRate=std::clamp((P*target-gas)/calibration::kRegulatorTau,-rate,rate);
        p.gasRate=std::clamp(p.gasRate,-gas/double(kSubDt),((1+D/hp)*c.gasCapacity-gas)/double(kSubDt));
        p.pump=m.rw*calibration::kGravity*hp*std::abs(p.gasRate)/calibration::kPumpEfficiency;
        p.power+=p.pump;
    }
    return p;
}
inline void checkActuator(const Coefficients& c,const Loaded& L,const Model& m,const V6& z,const std::string& name) {
    HydroState s=restState({0,-120,0},{0,0,0},{1,0,0});
    s.tailDrive=.25f;s.tailYaw=-.125f;s.gasContent=2*m.gasVolume;
    const Requests request{82,.4f,.3f,0};ActuatorPlan p;
    if(!planActuators(c,L,s,StepConfig{},request,.5f,z,p)){++failed;return;}
    double input[6];for(int i=0;i<6;++i)input[i]=z.v[i];
    const Plan ref=actuator(c,m,input,request,s.tailDrive,s.tailYaw,s.gasContent,120,0);
    if(p.count!=ref.count){++failed;return;}
    double error=0;
    auto see=[&](double a,double b,double scale){error=std::max(error,std::abs(a-b)/std::max(scale,1e-30));};
    const double cap=references().thrustCap;
    for(int j=0;j<p.count;++j) {
        const auto& channel=p.channel[j];
        see(magnitude(minus(from(channel.forceBody),ref.force[j])),0,cap);
        see(magnitude(minus(from(channel.leverBody),ref.lever[j])),0,c.refLength);
        see(channel.efficiency,ref.efficiency[j],1);
    }
    const auto active=activeWrench(p,1);
    for(int i=0;i<6;++i)see(active.v[i],ref.wrench[i],cap*(i<3?1:m.length));
    // Neutral gas regulation subtracts displacement-sized quantities. A
    // relative error against its nearly zero residual is ill-conditioned;
    // scale the total price by at least the declared full-rate pump power.
    // This retains the independently integrated material/load in the oracle.
    const double pumpScale=m.rw*calibration::kGravity*120*
        calibration::kGasRateFraction*m.hullVolume/calibration::kPumpEfficiency;
    const double priceScale=std::max(ref.power,pumpScale);
    const double priceDifference=std::abs(p.requestPower-ref.power);
    if(priceDifference>largestPowerDifference) {
        largestPowerDifference=priceDifference;powerActual=p.requestPower;powerExpected=ref.power;
        powerScale=priceScale;powerWhere=name;
    }
    see(p.requestPower,ref.power,priceScale);
    see(p.gasRate,ref.gasRate,calibration::kGasRateFraction*m.hullVolume);
    see(p.pumpPower,ref.pump,std::max(1.0,m.rw*calibration::kGravity*120*
        calibration::kGasRateFraction*m.hullVolume/calibration::kPumpEfficiency));
    if(error>worstActuator){worstActuator=error;actuatorWhere=name;}++actuatorChecks;
    // Active RHS and righting signs at a tilted pose, without a second kick.
    const auto q=qnormalize({1,.15f,-.2f,.1f});s.quat[0]=q.w;s.quat[1]=q.x;s.quat[2]=q.y;s.quat[3]=q.z;
    const V3 up=unrotate(q,kWorldUp);double upD[]={up.x,up.y,up.z},expected[6]{};
    V6 actual;const bool ok=solveMechanics(c,L,s,z,passiveDamping(L,c.halfLength,z),active,actual);
    if(!ok||!advance(m,input,upD,expected,false,ref.wrench)){++failed;return;}
    double diff=0,norm=0;
    for(int i=0;i<6;++i){double unit=i<3?1:m.length;diff+=std::pow(unit*(actual.v[i]-expected[i]),2);norm+=std::pow(unit*expected[i],2);}
    const double increment=std::sqrt(diff/std::max(norm,1e-30));
    if(increment>worstIncrement){worstIncrement=increment;incrementWhere=name+" active/tilted";}++checks;
}
struct Quaternion {double w=1,x=0,y=0,z=0;};
inline Quaternion multiply(Quaternion a,Quaternion b) {
    return {a.w*b.w-a.x*b.x-a.y*b.y-a.z*b.z,a.w*b.x+a.x*b.w+a.y*b.z-a.z*b.y,
            a.w*b.y-a.x*b.z+a.y*b.w+a.z*b.x,a.w*b.z+a.x*b.y-a.y*b.x+a.z*b.w};
}
inline Vec turn(Quaternion q,Vec v) {
    const Quaternion p=multiply(multiply(q,{0,v.x,v.y,v.z}),{q.w,-q.x,-q.y,-q.z});
    return {p.x,p.y,p.z};
}
inline Vec unturn(Quaternion q,Vec v){return turn({q.w,-q.x,-q.y,-q.z},v);}
inline Quaternion poseStep(Quaternion q,Vec omega) {
    const Quaternion dq=multiply(q,{0,omega.x,omega.y,omega.z});
    const double h=.5*double(kSubDt);
    q={q.w+h*dq.w,q.x+h*dq.x,q.y+h*dq.y,q.z+h*dq.z};
    const double norm=std::sqrt(q.w*q.w+q.x*q.x+q.y*q.y+q.z*q.z);
    return {q.w/norm,q.x/norm,q.y/norm,q.z/norm};
}
struct CircleFit {
    Vec origin{};int count=0;double sums[3][3]{},rhs[3]{};
    void add(Vec p) {
        if(count==0)origin=p;
        p=minus(p,origin);const double row[]={p.x,p.z,1},q=p.x*p.x+p.z*p.z;
        for(int i=0;i<3;++i){rhs[i]-=row[i]*q;for(int j=0;j<3;++j)sums[i][j]+=row[i]*row[j];}++count;
    }
    double radius() const {
        double a[6][6]{},b[6]{},x[6]{};
        for(int i=0;i<3;++i){b[i]=rhs[i];for(int j=0;j<3;++j)a[i][j]=sums[i][j];a[i+3][i+3]=1;}
        if(count<3||!denseSolve(a,b,x))return INFINITY;
        const double r2=.25*(x[0]*x[0]+x[1]*x[1])-x[2];return r2>0?std::sqrt(r2):INFINITY;
    }
};
struct Track {
    Quaternion q{};Vec position{},velocity{},momentum{};
    double work=0,yaw=0,response=INFINITY,relax=INFINITY;
    CircleFit circle{};
};
inline bool bodyVelocity(const Model& m,const Track& t,double z[6]) {
    const Vec u=unturn(t.q,t.velocity),L=unturn(t.q,t.momentum);
    double a[6][6]{},b[]={0,0,0,L.x,L.y,L.z},x[6]{};
    for(int i=0;i<3;++i){a[i][i]=1;for(int j=0;j<3;++j)a[i+3][j+3]=m.inertia[i][j];}
    if(!denseSolve(a,b,x))return false;
    z[0]=u.x;z[1]=u.y;z[2]=u.z;for(int i=3;i<6;++i)z[i]=x[i];return true;
}
inline Track track(const Model& m,const HydroState& s,const double z[6]) {
    Track t;t.q={s.quat[0],s.quat[1],s.quat[2],s.quat[3]};
    // Normalize independently in double; the two solvers start with the same
    // orientation, up to the binary32 representation of the quaternion.
    t.q=poseStep(t.q,{});
    t.velocity=turn(t.q,{z[0],z[1],z[2]});
    t.momentum=turn(t.q,matrix3(m.inertia,{z[3],z[4],z[5]}));return t;
}
inline bool advanceTrack(const Model& m,Track& t,const double active[6],bool patches,int substep,double initialNorm) {
    double z[6]{},out[6]{};if(!bodyVelocity(m,t,z))return false;
    const Vec up=unturn(t.q,{0,1,0});const double upD[]={up.x,up.y,up.z};
    if(!advance(m,z,upD,out,patches,active))return false;
    const Vec oldForward=turn(t.q,{-1,0,0});
    t.velocity=plus(t.velocity,turn(t.q,{out[0]-z[0],out[1]-z[1],out[2]-z[2]}));
    t.momentum=plus(t.momentum,turn(t.q,matrix3(m.inertia,{out[3]-z[3],out[4]-z[4],out[5]-z[5]})));
    t.position=plus(t.position,times(t.velocity,kSubDt));
    t.q=poseStep(t.q,{out[3],out[4],out[5]});
    const Vec forward=turn(t.q,{-1,0,0});
    t.yaw+=std::atan2(oldForward.x*forward.z-oldForward.z*forward.x,
                     oldForward.x*forward.x+oldForward.z*forward.z);
    double norm=0;for(int i=0;i<6;++i){t.work+=double(kSubDt)*active[i]*out[i];norm+=std::pow(out[i]*(i<3?1:m.length),2);}
    const double time=(substep+1)*double(kSubDt);
    if(substep>=625)t.circle.add(t.position);
    if(std::abs(t.yaw)>=std::acos(-1.0)/2&&!std::isfinite(t.response))t.response=time;
    if(std::sqrt(norm)<=.1*initialNorm&&!std::isfinite(t.relax))t.relax=time;
    return std::isfinite(norm)&&std::isfinite(t.work)&&std::isfinite(t.yaw);
}
inline bool advanceProduction(const Coefficients& c,const Loaded& L,HydroState& s,const V6& active) {
    V6 z,out;if(!incomingVelocity(L,s,{},z)||!solveMechanics(c,L,s,z,passiveDamping(L,c.halfLength,z),active,out))return false;
    applyVelocityChange(s,L,z,out);
    put(s.com,add(v3(s.com),mul(v3(s.vGround),kSubDt)));
    bool ok=false;const auto q=integrate(poseOf(s),{out.v[3],out.v[4],out.v[5]},kSubDt,&ok);
    s.quat[0]=q.w;s.quat[1]=q.x;s.quat[2]=q.y;s.quat[3]=q.z;return ok;
}
inline void trajectories(const Coefficients& c,const Loaded& L,const Model& m,const std::string& name) {
    // Explicit fixed-load kernel comparisons: no fuel subsidy, contact, rails,
    // gas update or production runtime model selector. The same prescribed
    // external wrench drives tensor and sequential-patch passive mechanics.
    for(double speed:{40.,82.,108.,120.,150.}) {
        const double z[]={-speed,0,0,0,0,0};double d[6][6]{};damping(m,z,d);
        double tensor=0,patch=0;
        for(int j=0;j<6;++j)tensor-=d[0][j]*z[j];
        damping(m,z,d,false);for(int j=0;j<6;++j)patch-=d[0][j]*z[j];
        for(int f=0;f<7;++f){double slip=0;for(int j=0;j<6;++j)slip+=m.finW[f][j]*z[j];
            patch-=m.finCoefficient[f]*std::abs(slip)*slip*m.finW[f][0];}
        std::printf("  TOW,%s,U=%.0f,tensor_drag=%.9g,patch_drag=%.9g,tensor_work_rate=%.9g,patch_work_rate=%.9g\n",
                    name.c_str(),speed,tensor,patch,tensor*speed,patch*speed);
    }
    for(int script=0;script<3;++script) {
        double z[]={-82,0,0,0,0,0},active[6]{};
        if(script==1)z[5]=-.5;
        if(script==2){z[0]=0;z[1]=10;z[3]=.3;z[4]=.2;z[5]=.5;}
        if(script<2) {
            double d[6][6];damping(m,z,d);
            for(int i=0;i<6;++i)for(int j=0;j<6;++j)active[i]+=d[i][j]*z[j];
            // Prescribed horizontal tow/turn: suppress vertical/roll/pitch
            // reactions so buoyancy and righting remain freely observable.
            active[2]=active[3]=active[4]=0;
            if(script==1)z[5]=0; // measure turn response from straight motion
        }
        HydroState s=restState({0,-120,0},{0,0,0},{1,0,0});
        Track tensor=track(m,s,z),patch=tensor;
        put(s.vGround,{float(tensor.velocity.x),float(tensor.velocity.y),float(tensor.velocity.z)});
        const V3 omega{float(z[3]),float(z[4]),float(z[5])};put(s.LWorld,rotate(poseOf(s),mulS3(L.inertia,omega)));
        V6 productionForce;for(int i=0;i<6;++i)productionForce.v[i]=float(active[i]);
        double initialNorm=0;for(int i=0;i<6;++i)initialNorm+=std::pow(z[i]*(i<3?1:m.length),2);
        int completed=0;
        for(int step=0;step<1250;++step) {
            if(!advanceTrack(m,tensor,active,false,step,std::sqrt(initialNorm))||
               !advanceTrack(m,patch,active,true,step,std::sqrt(initialNorm))||
               !advanceProduction(c,L,s,productionForce))break;
            ++completed;
        }
        if(completed!=1250){++failed;std::printf("  TRAJECTORY,%s,script=%d,nonfinite_or_refused_at=%d\n",name.c_str(),script,completed);continue;}
        ++trajectoryChecks;double tensorZ[6]{},patchZ[6]{};bodyVelocity(m,tensor,tensorZ);bodyVelocity(m,patch,patchZ);
        const double tensorRadius=std::abs(tensorZ[5])>1e-12?std::hypot(tensorZ[0],tensorZ[1])/std::abs(tensorZ[5]):INFINITY;
        const double patchRadius=std::abs(patchZ[5])>1e-12?std::hypot(patchZ[0],patchZ[1])/std::abs(patchZ[5]):INFINITY;
        // Position starts at the origin in double and at -120 y in production.
        const Vec productionPosition{s.com[0],s.com[1]+120,s.com[2]};
        std::printf("  TRAJECTORY,%s,%s,steps=1250,dt=%.12g,tensor_yaw=%.9g,patch_yaw=%.9g,tensor_U_over_yaw=%.9g,patch_U_over_yaw=%.9g,"
                    "tensor_fitted_radius=%.9g,patch_fitted_radius=%.9g,fit_substeps=[625:1250),"
                    "tensor_slip=%.9g,patch_slip=%.9g,tensor_90s=%.9g,patch_90s=%.9g,tensor_relax10pct_s=%.9g,patch_relax10pct_s=%.9g,"
                    "tensor_work=%.9g,patch_work=%.9g,production_double_position_error=%.9g,production_double_velocity_error=%.9g\n",
            name.c_str(),script==0?"tow":(script==1?"turn":"relax"),double(kSubDt),tensor.yaw,patch.yaw,tensorRadius,patchRadius,
            tensor.circle.radius(),patch.circle.radius(),
            std::atan2(tensorZ[1],-tensorZ[0]),std::atan2(patchZ[1],-patchZ[0]),tensor.response,patch.response,tensor.relax,patch.relax,
            tensor.work,patch.work,magnitude(minus(productionPosition,tensor.position)),magnitude(minus(from(v3(s.vGround)),tensor.velocity)));
    }
}
inline bool run() {
    std::printf("  trajectory reference: %d independent one-step increments worst %.9g at %s, residual %.9g at %s (limit 2e-5)\n",
                checks,worstIncrement,incrementWhere.c_str(),worstResidual,residualWhere.c_str());
    std::printf("  independent actuator force/location/power/gas: %d checks, worst %.9g at %s (limit 2e-5)\n",
                actuatorChecks,worstActuator,actuatorWhere.c_str());
    std::printf("  power oracle: largest absolute difference %.9g (actual %.12g, double %.12g, physical scale %.12g) at %s\n",
                largestPowerDifference,powerActual,powerExpected,powerScale,powerWhere.c_str());
    std::printf("  fixed-load trajectories: %d complete; model differences reported only, no percentage acceptance gate; internal errors %d\n",trajectoryChecks,failed);
    return checks>0&&actuatorChecks>0&&trajectoryChecks==9&&failed==0&&worstIncrement<=2e-5&&worstResidual<=2e-5&&worstActuator<=2e-5;
}
} // namespace hydroref2

// Internal calibration driver. Stages are implemented and frozen in order.
// No public OceanWorld stepping, config activation, or runtime model selector.
#include <bit>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <functional>
#include <iomanip>
#include <sstream>
#include <iostream>
#include "ocean_hydro_step_fixture.hpp"
#include "ocean_hydro_harness.hpp"
#include "ocean_hydro_calibration_io.hpp"
#include "ocean_hydro_measurements.hpp"
#include "ocean_hydro_calorimetry.hpp"

namespace hydroassay {
using namespace hydro;
struct Result {std::string name;bool pass;double value,limit;int begin,end;};
struct Window {
    bool ok=true;int completed=0;double injected=0,debit=0,motor=0;
    double maxSpeed=0,maxTilt=0,terminalDown=0,terminalForward=0;
    double minLambda=1,maxFatigue=0,pumpFuel=0,gasIntegral=0;int terminalSamples=0;
    Digest chain;
};
// Measurement-only double fit. Coordinates are unwrapped from the torus before
// fitting x*x+z*z = a*x+b*z+c; no U/omega enters the fitted radius.
struct TurnMeasurements {
    ArcMeasurements arc{double(kSubDt)};
    double x=0,z=0,previousX=0,previousZ=0,previousHeading=0,heading=0;
    double speed=0,yaw=0,bodyYaw=0,slip=0,maxSlip=0,maxOmega=0;
    double response=-1,minLambda=1,maxFatigue=0;
    int samples=0,begin=0;
    explicit TurnMeasurements(const HydroState& s,int first):previousX(s.com[0]),previousZ(s.com[2]),begin(first) {
        const auto f=rotate(poseOf(s),{-1,0,0});previousHeading=std::atan2(double(f.z),double(f.x));
    }
    void observe(const hydroharness::Columns& h,int outer,int sub,const SubstepReceipt& r) {
        const auto& s=r.state;
        x+=std::remainder(double(s.com[0])-previousX,double(h.config.width));
        z+=std::remainder(double(s.com[2])-previousZ,double(h.config.height));
        previousX=s.com[0];previousZ=s.com[2];
        Loaded L;V6 velocity;
        if(!loadAt(h.coefficients[0],h.config.depth,s,r.energy,L)||!incomingVelocity(L,s,{},velocity))
            throw std::runtime_error("turn telemetry load refused");
        const auto q=poseOf(s);const V3 f=rotate(q,{-1,0,0});
        const V3 omega=rotate(q,{velocity.v[3],velocity.v[4],velocity.v[5]});
        const V3 df=cross(omega,f);
        const double angle=std::atan2(double(f.z),double(f.x));
        heading+=std::remainder(angle-previousHeading,6.283185307179586);previousHeading=angle;
        if(response<0&&heading>=1.5707963267948966)response=(2*outer+sub+1)*double(kSubDt);
        maxOmega=std::max(maxOmega,double(std::sqrt(norm2(omega))));
        minLambda=std::min(minLambda,double(r.motor.lambda));maxFatigue=std::max(maxFatigue,double(s.fatigue));
        if(outer>=begin) {
            speed+=std::hypot(double(s.vGround[0]),double(s.vGround[2]));
            yaw+=(double(f.x)*df.z-double(f.z)*df.x)/(double(f.x)*f.x+double(f.z)*f.z);
            bodyYaw-=velocity.v[5];
            const double a=std::abs(std::atan2(double(velocity.v[1]),-double(velocity.v[0])));
            arc.sample(x,z,std::hypot(double(s.vGround[0]),double(s.vGround[2])),
                std::atan2(double(s.vGround[2]),double(s.vGround[0])),angle,a);
            slip+=a;maxSlip=std::max(maxSlip,a);++samples;
        }
    }
    double radius() const {return arc.radius();}

};
struct Driver {
    std::string build="unspecified",target="native";
    std::FILE* output=stdout;
    std::ofstream trace;
    std::vector<Result> results;
    std::vector<std::pair<std::string,Window>> windows;
    std::uint32_t measuredCruise=0,measuredSustained=0;
    int courseEligible=0,headingEligible=0;
    HydroState measuredIncoming{}; // exact post-source state of the observed substep
    bool check(const std::string& name,bool pass,double value,double limit,int begin=0,int end=0) {
        results.push_back({name,pass,value,limit,begin,end});
        std::fprintf(output,"%s,%s,value=%.12g,limit=%.12g,outer_window=[%d,%d)\n",pass?"PASS":"FAIL",name.c_str(),value,limit,begin,end);
        return pass;
    }
    static double tilt(const HydroState& s) {
        const V3 up=rotate(poseOf(s),{0,0,1});
        return std::acos(std::clamp(double(up.y),-1.0,1.0));
    }
    static hydroharness::Columns clone(const char* body="neutral") {
        hydroharness::Columns h;
        if(!h.add(hydroharness::body(body)))throw std::runtime_error("assay clone initialization refused");
        return h;
    }
    Window run(const std::string& name,hydroharness::Columns& h,int steps,HeldOuter held={},
               const std::function<V6(const hydroharness::Columns&)>& force={},
               const std::function<void(int,int,const SubstepReceipt&)>& observe={}) {
        Window w;
        for(int outer=0;outer<steps;++outer) {
            hydroharness::FixedReceipt receipt;
            if(!h.stepFixed(0,held,receipt,force?force(h):V6{})) {
                w.ok=false;std::fprintf(output,"REFUSED,%s,outer=%d,status=%u\n",name.c_str(),outer,h.states[0].status);break;
            }
            for(int sub=0;sub<2;++sub) {
                const auto& r=receipt.step.substep[sub];const auto& source=receipt.source[sub];
                w.ok=w.ok&&receipt.incomingEnergy[sub]==25&&source.waste==0&&source.unpaid==0;
                w.injected+=source.accepted;w.debit+=r.reserve.spent;w.motor+=r.motor.fuel;
                if(r.plan.requestPower>0)w.pumpFuel+=r.motor.fuel*double(r.plan.pumpPower)/r.plan.requestPower;
                w.gasIntegral+=double(kSubDt)*r.motor.lambda*r.plan.gasRate;
                w.maxSpeed=std::max(w.maxSpeed,double(std::sqrt(norm2(v3(r.state.vGround)))));
                w.maxTilt=std::max(w.maxTilt,tilt(r.state));
                w.minLambda=std::min(w.minLambda,double(r.motor.lambda));
                w.maxFatigue=std::max(w.maxFatigue,double(r.state.fatigue));
                if(outer>=steps-125){
                    w.terminalDown-=r.state.vGround[1];
                    w.terminalForward-=unrotate(poseOf(r.state),v3(r.state.vGround)).x;
                    ++w.terminalSamples;
                }
                hydroharness::hashReserve(w.chain,source);w.chain.addf(receipt.incomingEnergy[sub]);
                hydroharness::hashSubstep(w.chain,r);
                measuredIncoming=receipt.incomingState[sub];
                if(observe)observe(outer,sub,r);
                if(trace) {
                    trace<<name<<','<<outer<<','<<sub<<','<<receipt.incomingEnergy[sub]<<','<<r.energy<<','<<source.accepted<<','
                         <<r.reserve.spent<<','<<r.motor.fuel<<','<<r.plan.gasRate<<','<<r.motor.lambda;
                    forEachStateWord(r.state,[&](std::uint32_t word){trace<<','<<word;});
                    trace<<'\n';
                }
            }
            ++w.completed;
        }
        if(w.terminalSamples){w.terminalDown/=w.terminalSamples;w.terminalForward/=w.terminalSamples;}
        check(name+"/complete_and_25E_each_incoming_substep",w.ok&&w.completed==steps,w.completed,steps,0,steps);
        windows.emplace_back(name,w);
        std::fprintf(output,"WINDOW,%s,outer=[0,%d),substeps=%d,subsidy=%.12g,debit=%.12g,motor=%.12g,chain=%016llx\n",
                    name.c_str(),steps,2*w.completed,w.injected,w.debit,w.motor,(unsigned long long)w.chain.h);
        return w;
    }
    void geometry(const std::string& name,const TurnMeasurements& m,bool ok,int begin,int end) {
        const auto& a=m.arc;
        std::fprintf(output,"GEOMETRY,name=%s,samples=%zu,U=%.12g,speed_range_fraction=%.12g,course_arc_deg=%.12g,"
            "mean_course_rate=%.12g,mean_heading_rate=%.12g,rate_difference=%.12g,max_slip_deg=%.12g,"
            "fitted_radius=%.12g,course_radius=%.12g,heading_radius=%.12g,course_error=%.12g,heading_error=%.12g,"
            "course_eligible=%d,course_reason=%s,heading_eligible=%d,heading_reason=%s\n",
            name.c_str(),a.points.size(),a.meanSpeed(),a.speedRange(),std::abs(a.course)*kDegrees,
            a.courseRate(),a.headingRate(),a.courseRate()-a.headingRate(),a.maxSlip*kDegrees,
            a.radius(),a.predicted(a.courseRate()),a.predicted(a.headingRate()),a.error(a.courseRate()),a.error(a.headingRate()),
            int(a.resolved()),a.courseExclusion(),int(a.steadyLowSlip()),a.headingExclusion());
        if(a.resolved()){++courseEligible;check(name+"/resolved_course_fitted_radius",ok&&a.coursePass(),a.error(a.courseRate()),.05,begin,end);}
        if(a.steadyLowSlip()){++headingEligible;check(name+"/steady_low_slip_heading_radius",ok&&a.headingPass(),a.error(a.headingRate()),.05,begin,end);}
    }
    void assay3() {
        constexpr double degrees=57.29577951308232;
        double radii[3]{};
        for(int bodyIndex=0;bodyIndex<3;++bodyIndex) {
            const char* bodyName=bodyIndex==0?"neutral":(bodyIndex==1?"manoeuvrer":"cruiser");
            for(float requested:{40.f,82.f,120.f}) {
                if(bodyIndex&&requested!=40)continue;
                auto h=clone(bodyName);HeldOuter straight;straight.requests.speed=requested;
                const std::string name=std::string("steer_")+bodyName+"_"+std::to_string(int(requested));
                if(requested<120)run(name+"_straight",h,3750,straight);
                else {
                    // A recovered, kinematically initialized straight 120 u/s
                    // release, followed by ONLY 62 outer steps (.992 s) of turn.
                    // The finite burst is never described as a steady state.
                    put(h.states[0].vGround,rotate(poseOf(h.states[0]),{-requested,0,0}));
                    Loaded L;if(!loadAt(h.coefficients[0],240,h.states[0],25,L))throw std::runtime_error("120 release load refused");
                    const float D=.5f*rhoWater()*L.K[0]+at6(L.Dfin,0,0);
                    h.states[0].tailDrive=D*requested*requested/references().thrustCap;
                }
                auto control=h;
                if(requested==120) {
                    control=clone(bodyName);HeldOuter retained;retained.requests.speed=82;
                    run(name+"_matched_control_82",control,3750,retained);
                }
                const auto controlAngles=signedAngles(control.states[0]);
                const auto& cs=control.states[0];
                Loaded controlLoad;V6 controlVelocity;
                if(!loadAt(control.coefficients[0],240,cs,25,controlLoad)||!incomingVelocity(controlLoad,cs,{},controlVelocity))
                    throw std::runtime_error("D2 control load refused");
                ActuatorPlan controlPlan;
                const float retained=requested==120?82:requested;
                if(!planActuators(control.coefficients[0],controlLoad,cs,control.config,{retained,0,0,0},.5f,controlVelocity,controlPlan))
                    throw std::runtime_error("D2 control plan refused");
                std::fprintf(output,"D2_CONTROL,name=%s,request=%.12g,absolute_roll_deg=%.12g,absolute_pitch_deg=%.12g,"
                    "actual_horizontal_speed=%.12g,depth=%.12g,vertical_velocity=%.12g,gas_content=%.12g,"
                    "remaining_gas_rate=%.12g,pump_power=%.12g,omega=%.12g,preparation_outer=3750,settled_exactly=false\n",
                    name.c_str(),double(retained),controlAngles.roll,controlAngles.pitch,
                    std::hypot(double(cs.vGround[0]),double(cs.vGround[2])),double(-cs.com[1]),double(cs.vGround[1]),
                    double(cs.gasContent),double(controlPlan.gasRate),double(controlPlan.pumpPower),
                    std::sqrt(double(controlVelocity.v[3])*controlVelocity.v[3]+double(controlVelocity.v[4])*controlVelocity.v[4]+double(controlVelocity.v[5])*controlVelocity.v[5]));
                const int steps=requested==120?62:625,begin=requested==120?31:500;
                TurnMeasurements measurements(h.states[0],begin);
                HeldOuter turn=straight;turn.requests.yaw=1;
                const auto w=run(name,h,steps,turn,{},[&](int outer,int sub,const SubstepReceipt& r) {
                    measurements.observe(h,outer,sub,r);
                });
                const auto& m=measurements;
                const double speed=m.speed/m.samples,yaw=m.yaw/m.samples,bodyYaw=m.bodyYaw/m.samples;
                const double radius=m.radius(),slip=m.slip/m.samples;
                const double predicted=speed/std::abs(yaw),radiusError=std::abs(radius-predicted)/predicted;
                std::fprintf(output,"TURN,body=%s,request=%.9g,outer_window=[%d,%d),actual_speed=%.12g,heading_yaw=%.12g,"
                    "minus_body_omega_z=%.12g,fitted_radius=%.12g,U_over_heading_yaw=%.12g,relative_radius_error=%.12g,"
                    "mean_sideslip_deg=%.12g,max_sideslip_deg=%.12g,response_90_s=%.12g,lambda_min=%.12g,"
                    "fatigue_max=%.12g,fatigue_end=%.12g,max_total_omega=%.12g,final_depth=%.12g,tilt_deg=%.12g,finite_burst=%s\n",
                    bodyName,double(requested),begin,steps,speed,yaw,bodyYaw,radius,predicted,radiusError,slip*degrees,
                    m.maxSlip*degrees,m.response,m.minLambda,m.maxFatigue,double(h.states[0].fatigue),m.maxOmega,
                    double(-h.states[0].com[1]),tilt(h.states[0])*degrees,requested==120?"true":"false");
                check(name+"/finite_measurements",w.ok&&m.samples>0&&radius>0&&std::isfinite(radius)&&std::isfinite(yaw),radius,0,begin,steps);
                check(name+"/angular_rail",w.ok&&m.maxOmega<=h.config.maxAngularSpeed&&m.maxOmega<=12,m.maxOmega,h.config.maxAngularSpeed,0,steps);
                if(requested==82)check(name+"/yaw_2.60_plus_minus_.15",w.ok&&std::abs(yaw-2.60)<=.15,yaw,.15,begin,steps);
                geometry(name,m,w.ok,begin,steps);
                if(requested==40)radii[bodyIndex]=radius;
                // D-M2b1-3: release all requests, preserving the post-turn filters.
                // Preserve the filtered tail state; regulator and passive brake
                // remain active and all resulting work is paid normally.
                auto driven=h;HeldOuter drivenRequest;drivenRequest.requests.speed=retained;
                const auto drivenRelease=run(name+"_driven_release",driven,625,drivenRequest);
                const auto drivenAngles=signedAngles(driven.states[0]);
                const double rollError=std::abs(std::remainder(drivenAngles.roll-controlAngles.roll,360.));
                const double pitchError=std::abs(std::remainder(drivenAngles.pitch-controlAngles.pitch,360.));
                check(name+"/driven_release_roll_relative_1_degree",drivenRelease.ok&&rollError<=1,rollError,1,0,625);
                check(name+"/driven_release_pitch_relative_1_degree",drivenRelease.ok&&pitchError<=1,pitchError,1,0,625);
                std::fprintf(output,"D2_RELEASE,name=%s,signed_roll_deg=%.12g,signed_pitch_deg=%.12g,control_absolute_trim_reported=true\n",
                    name.c_str(),drivenAngles.roll,drivenAngles.pitch);
                const auto release=run(name+"_release",h,625,HeldOuter{});
                const auto angles=signedAngles(h.states[0]);
                check(name+"/release_roll_upright_1_degree",release.ok&&std::abs(angles.roll)<=1,angles.roll,1,0,625);
                check(name+"/release_pitch_upright_1_degree",release.ok&&std::abs(angles.pitch)<=1,angles.pitch,1,0,625);
            }
        }
        std::fprintf(output,"GEOMETRY_COUNTS,scope=original_five,course=%d,heading=%d,heading_status=%s\n",
            courseEligible,headingEligible,headingEligible?"exercised":"not_exercised");
        // Fixed additional low-slip fixture, declared before stage-3 calibration:
        // neutral, 40 request, yaw .01 (binary32), 60 s preparation and turn;
        // last 10 s fit. Original finite-120 window is preserved above.
        auto low=clone();HeldOuter straight;straight.requests.speed=40;
        run("geometry_low_slip_straight",low,3750,straight);
        HeldOuter gentle=straight;gentle.requests.yaw=.01f;
        TurnMeasurements eligible(low.states[0],3125);
        const auto lw=run("geometry_low_slip_turn",low,3750,gentle,{},[&](int o,int sub,const SubstepReceipt& r){eligible.observe(low,o,sub,r);});
        geometry("geometry_low_slip_turn",eligible,lw.ok,3125,3750);
        check("geometry_low_slip_fixture/both_checks_exercised",eligible.arc.resolved()&&eligible.arc.steadyLowSlip(),eligible.arc.maxSlip*kDegrees,5,3125,3750);
        std::fprintf(output,"GEOMETRY_COUNTS,scope=all,course=%d,heading=%d,heading_status=%s\n",
            courseEligible,headingEligible,headingEligible?"exercised":"not_exercised");
        check("body_ordering/manoeuvrer_neutral_cruiser",radii[1]>0&&radii[1]<radii[0]&&radii[0]<radii[2],radii[2],radii[0]);
        check("body_ordering/cruiser_over_manoeuvrer_at_least_3",radii[1]>0&&radii[2]/radii[1]>=3,radii[2]/radii[1],3);
    }
    bool allOK() const {for(const auto& r:results)if(!r.pass)return false;return !results.empty();}
    void contactDiagnostics() {
        auto floor=clone("noBladder");run("diagnostic_floor_settle",floor,3750);
        Loaded L;
        if(!loadAt(floor.coefficients[0],240,floor.states[0],25,L))throw std::runtime_error("diagnostic load refused");
        const float force=.9f*calibration::kStaticFriction*calibration::kGravity*(L.mass-rhoWater()*L.displaced);
        run("diagnostic_COM_height",floor,625,{},[&](const hydroharness::Columns& h) {
            const auto f=unrotate(poseOf(h.states[0]),{force,0,0});return V6{{f.x,f.y,f.z,0,0,0}};
        });
        std::fprintf(output,"DIAGNOSTIC,COM_height_speed=%.12g,acceptance=false,sampled_once_per_outer_step=true\n",
                    double(std::abs(floor.states[0].vGround[0])));
    }
    void assay1() {
        constexpr double radians=0.017453292519943295;
        auto h=clone();Loaded L;
        if(!loadAt(h.coefficients[0],240,h.states[0],25,L))throw std::runtime_error("reference load refused");
        const double buoy=std::abs(double(L.mass)-double(rhoWater())*L.displaced)/L.mass;
        check("static/feasible_neutral_gas",h.states[0].gasContent>=0&&h.states[0].gasContent<=3*h.coefficients[0].gasCapacity,
              h.states[0].gasContent,3*h.coefficients[0].gasCapacity);
        check("static/reference_buoyancy",buoy<=1e-5,buoy,1e-5);
        const float initialDepth=-h.states[0].com[1];
        const auto stat=run("static",h,3750);
        const double vertical=std::abs(h.states[0].vGround[1]),drift=std::abs(-h.states[0].com[1]-initialDepth);
        check("static/vertical_speed",stat.ok&&vertical<.01,vertical,.01,0,3750);
        check("static/depth_drift",stat.ok&&drift<.1,drift,.1,0,3750);
        const auto equilibrium=h;
        // Exact binary32 script inputs: cos(5 deg), sin(5 deg).
        constexpr float cos5=0x1.fe0d3cp-1f,sin5=0x1.64fd6cp-4f;
        for(int axis=0;axis<3;++axis) {
            auto tilted=equilibrium;
            const Q4 roll{cos5,sin5,0,0},pitch{cos5,0,sin5,0};
            const auto rotation=axis==0?roll:(axis==1?pitch:qmul(roll,pitch));
            const auto q=qnormalize(qmul(poseOf(tilted.states[0]),rotation));
            auto& s=tilted.states[0];s.quat[0]=q.w;s.quat[1]=q.x;s.quat[2]=q.y;s.quat[3]=q.z;
            put(s.vGround,{});put(s.LWorld,{});
            const std::string name=axis==0?"righting_roll":(axis==1?"righting_pitch":"righting_combined");
            const auto w=run(name,tilted,625);
            const double angle=tilt(tilted.states[0])/radians;
            check(name+"/within_1_degree",w.ok&&angle<=1,angle,1,0,625);
            check(name+"/no_tumbling",w.ok&&w.maxTilt<90*radians,w.maxTilt/radians,90,0,625);
        }
        for(int targetDepth:{96,144}) {
            auto depth=equilibrium;depth.fish[0].bodyBuoy=float(targetDepth)/240;
            const auto name="depth_"+std::to_string(targetDepth);const auto w=run(name,depth,3750);
            const double error=std::abs(-depth.states[0].com[1]-targetDepth);
            check(name+"/within_1_unit",w.ok&&error<=1,error,1,0,3750);
        }
        auto floor=clone("noBladder");const auto rest=run("floor_rest",floor,3750);
        loadAt(floor.coefficients[0],240,floor.states[0],25,L);
        const double speed=std::sqrt(norm2(v3(floor.states[0].vGround)));
        const double penetration=std::max(0.0f,-minimumGap(floor.supports[0],L,boundaries(floor.config),floor.states[0],5));
        check("floor_rest/speed",rest.ok&&speed<.01,speed,.01,0,3750);
        check("floor_rest/penetration",rest.ok&&penetration<.01*floor.coefficients[0].size,penetration,.01*floor.coefficients[0].size,0,3750);
        const float normal=calibration::kGravity*(L.mass-rhoWater()*L.displaced);
        check("floor_rest/positive_normal_load",normal>0,normal,0);
        for(float factor:{.9f,1.1f}) {
            auto sliding=floor;const auto name=factor<1?"floor_static_friction":"floor_sliding_friction";
            const float F=factor*calibration::kStaticFriction*normal;
            const auto w=run(name,sliding,625,{},[&](const hydroharness::Columns& c) {
                const auto& s=c.states[0];
                const Q4 q=poseOf(s);
                const V3 f=unrotate(q,{F,0,0});
                // D-M2b1-1: sample COM's floor projection once per outer
                // step; hold this body-frame wrench across both substeps.
                // This is not continuous world-frame floor application.
                const V3 lever=unrotate(q,{0,-(c.config.depth+s.com[1]),0});
                return wrench(f,lever);
            });
            const double v=std::abs(sliding.states[0].vGround[0]);
            check(std::string(name)+"/tangent_speed",w.ok&&(factor<1?v<.01:v>.01),v,.01,0,625);
        }
        auto buoyant=clone();
        loadAt(buoyant.coefficients[0],240,buoyant.states[0],25,L);
        buoyant.states[0].com[1]=-240;float penetrationScratch;
        if(!resolveBoundaries(buoyant.coefficients[0],buoyant.supports[0],L,boundaries(buoyant.config),buoyant.states[0],penetrationScratch))
            throw std::runtime_error("buoyant floor placement refused");
        buoyant.states[0].gasContent=pressure(-buoyant.states[0].com[1],240)*buoyant.coefficients[0].gasCapacity;
        const auto bw=run("release_positive_buoyancy",buoyant,32);
        loadAt(buoyant.coefficients[0],240,buoyant.states[0],25,L);
        const float bgap=minimumGap(buoyant.supports[0],L,boundaries(buoyant.config),buoyant.states[0],5);
        check("release_positive_buoyancy/gap",bw.ok&&bgap>.005f,bgap,.005,0,32);
        auto lifted=floor;HeldOuter lift;lift.requests.dive=-1;
        const auto lw=run("release_paid_fins",lifted,64,lift);
        loadAt(lifted.coefficients[0],240,lifted.states[0],25,L);
        const float lgap=minimumGap(lifted.supports[0],L,boundaries(lifted.config),lifted.states[0],5);
        check("release_paid_fins/gap",lw.ok&&lgap>.005f,lgap,.005,0,64);
        check("release_paid_fins/charged",lw.motor>0,lw.motor,0,0,64);
        auto sink=clone("noBladder");sink.states[0].com[1]=-20;
        loadAt(sink.coefficients[0],240,sink.states[0],25,L);
        const double weight=calibration::kGravity*(L.mass-double(rhoWater())*L.displaced);
        const double drag=.5*double(rhoWater())*L.K[2]+at6(L.Dfin,2,2);
        const double expected=std::sqrt(weight/drag);
        const auto sw=run("terminal_sink",sink,375);
        const double sinkError=std::abs(sw.terminalDown-expected)/expected;
        std::fprintf(output,"SINK,predicted=%.12g,observed=%.12g,outer_measurement=[250,375)\n",expected,sw.terminalDown);
        check("terminal_sink/force_balance",sw.ok&&sinkError<=.02,sinkError,.02,250,375);
    }
    void assay2() {
        auto reference=clone();
        const auto trim=run("tow_reference_trim",reference,3750);
        Loaded L;
        if(!trim.ok||!loadAt(reference.coefficients[0],240,reference.states[0],25,L))
            throw std::runtime_error("assay-1 tow trim refused");
        const auto& c=reference.coefficients[0];
        const float wc=references().workConversion;
        // A kinematic tow fixes the assay-1 pose, load and velocity. The
        // measured six-component restraint is reported, never free thrust.
        for(float speed:{40.f,82.f,108.f,120.f,150.f}) {
            auto s=reference.states[0];
            const V6 z{{-speed,0,0,0,0,0}};
            put(s.vGround,rotate(poseOf(s),{-speed,0,0}));
            const float drag=((.5f*rhoWater()*L.K[0]+at6(L.Dfin,0,0))*speed)*speed;
            s.tailDrive=drag/references().thrustCap;
            ActuatorPlan plan;
            if(!planActuators(c,L,s,reference.config,{speed,0,0,0},.5f,z,plan))
                throw std::runtime_error("tow actuator refused");
            const V6 resistance=mulS6(passiveDamping(L,c.halfLength,z),z);
            const auto active=activeWrench(plan,1);
            double independentPower=plan.pumpPower;
            for(int j=0;j<plan.count;++j) {
                const auto& ch=plan.channel[j];
                const double force=std::sqrt(double(ch.forceBody.x)*ch.forceBody.x+
                    double(ch.forceBody.y)*ch.forceBody.y+double(ch.forceBody.z)*ch.forceBody.z);
                const double power=force*(speed+c.rowSpeed)/ch.efficiency;
                independentPower+=power;
                std::fprintf(output,"TOW_CHANNEL,U=%.9g,channel=%d,force=%.12g,power=%.12g,lever=%.12g/%.12g/%.12g\n",
                    double(speed),j,force,power,double(ch.leverBody.x),double(ch.leverBody.y),double(ch.leverBody.z));
            }
            std::fprintf(output,"TOW,U=%.9g,outer_window=[0,1),power=%.12g,bits=0x%08x,pump=%.12g,drag_wrench=",
                double(speed),double(plan.requestPower),std::bit_cast<std::uint32_t>(plan.requestPower),double(plan.pumpPower));
            for(float x:resistance.v)std::fprintf(output," %.12g",double(x));
            std::fprintf(output,",restraint=");for(int j=0;j<6;++j)std::fprintf(output," %.12g",double(resistance.v[j]-active.v[j]));
            std::fputs("\n",output);
            const double independentDrag=(.5*double(rhoWater())*L.K[0]+at6(L.Dfin,0,0))*speed*speed;
            check("tow_"+std::to_string(int(speed))+"/drag_oracle",
                std::abs(resistance.v[0]+independentDrag)/independentDrag<=2e-5,
                std::abs(resistance.v[0]+independentDrag)/independentDrag,2e-5);
            check("tow_"+std::to_string(int(speed))+"/channel_price_oracle",
                std::abs(plan.requestPower-independentPower)/independentPower<=2e-5,
                std::abs(plan.requestPower-independentPower)/independentPower,2e-5);
            if(speed==82)measuredCruise=std::bit_cast<std::uint32_t>(plan.requestPower);
            if(speed==108)measuredSustained=std::bit_cast<std::uint32_t>(plan.requestPower);
        }
        check("force_capacity/unchanged_150_anchor",references().thrustCap==2*((references().forwardDrag*kUact)*kUact),
              references().thrustCap,2*((references().forwardDrag*kUact)*kUact));
        // Numerical straight force balance of this law, including the shared
        // sustained motor limit. No prescribed speed or velocity clamp.
        auto balance=[&](float request,bool peak) {
            double lo=0,hi=200;
            for(int i=0;i<60;++i) {
                const double U=(lo+hi)/2;
                const double D=.5*double(rhoWater())*L.K[0]+at6(L.Dfin,0,0);
                const double thrust=std::clamp(D*request*request+
                    at6(L.Meff,0,0)*(request-U)/calibration::kControllerTau,0.0,double(references().thrustCap));
                const double power=thrust*(U+c.rowSpeed)*
                    (double(c.caudalArea/c.propArea)/c.tailEfficiency+
                     double((c.propArea-c.caudalArea)/c.propArea)/kPairedEfficiency);
                const double lambda=power>0?std::min(1.0,double(peak?c.peakPower:c.sustainedPower)/power):1;
                if(thrust*lambda>D*U*U)lo=U;else hi=U;
            }
            return (lo+hi)/2;
        };
        for(float request:{40.f,82.f,108.f,150.f}) {
            auto free=reference;HeldOuter held;held.requests.speed=request;
            const std::string name="free_"+std::to_string(int(request));
            const auto w=run(name,free,3750,held);
            const double expected=balance(request,false),error=std::abs(w.terminalForward-expected)/expected;
            std::fprintf(output,"FREE,request=%.9g,terminal_forward=%.12g,balance=%.12g,relative_error=%.12g,"
                        "observed_peak=%.12g,peak_balance=%.12g,peak_starting_window=[130,150],"
                        "lambda_min=%.12g,fatigue_max=%.12g,terminal_depth=%.12g,terminal_tilt_deg=%.12g\n",
                        double(request),w.terminalForward,expected,error,w.maxSpeed,balance(request,true),
                        w.minLambda,w.maxFatigue,double(-free.states[0].com[1]),tilt(free.states[0])*57.29577951308232);
            check(name+"/numerical_force_balance",w.ok&&error<=.02,error,.02,3625,3750);
            if(request==150)check("sustained/108_within_5_percent",w.ok&&std::abs(w.terminalForward-108)<=.05*108,
                                w.terminalForward,108*.05,3625,3750);
        }
        for(float fibre:{0.f,.5f,1.f}) {
            auto body=hydroharness::body();body.P.g[physical::kFibre]=fibre;
            Coefficients cf;Support support;
            if(compile(body.G,body.S,body.E,body.P,Params{},cf,support)!=kOk)
                throw std::runtime_error("fibre compile refused");
            const auto name="fibre_"+std::to_string(int(2*fibre));
            float fatigue=0;int fill=0,recover=0;bool ok=true;
            MotorReceipt r;
            if(cf.fatigueCapacity>0) {
                while(fatigue<cf.fatigueCapacity&&fill<255) {
                    ok=ok&&limitMotor(cf,1000,fatigue,cf.peakPower,wc,r);
                    if(!ok)break;
                    fatigue=r.nextFatigue;++fill;
                    ok=ok&&fatigue>=0&&fatigue<=cf.fatigueCapacity;
                }
                check(name+"/peak_fills_in_2s",ok&&fatigue==cf.fatigueCapacity&&std::abs(fill*kSubDt-2)<=.016f,
                    fill*kSubDt,.016,0,fill);
                ok=ok&&limitMotor(cf,1000,fatigue,cf.peakPower,wc,r);
                check(name+"/exhausted_limits_to_sustained",ok&&std::abs(r.actualPower-cf.sustainedPower)/cf.sustainedPower<2e-6,
                    r.actualPower,cf.sustainedPower);
                const double expected=cf.fatigueCapacity/(double(kGamma)*cf.sustainedPower);
                bool free=true;
                while(fatigue>0&&recover<2000) {
                    ok=ok&&limitMotor(cf,1000,fatigue,0,wc,r);
                    if(!ok)break;
                    fatigue=r.nextFatigue;++recover;free=free&&r.fuel==0;
                }
                check(name+"/recovery_fibre_law",ok&&fatigue==0&&free&&std::abs(recover*kSubDt-expected)<=.016,
                    recover*kSubDt,expected,0,recover);
            } else check(name+"/all_red_zero_capacity",limitMotor(cf,25,0,cf.peakPower,wc,r)&&r.nextFatigue==0,
                         cf.fatigueCapacity,0);
            float energy=.001f;fatigue=0;ok=true;
            for(int i=0;i<100;++i) {
                ok=ok&&limitMotor(cf,energy,fatigue,10*cf.peakPower,wc,r);
                if(!ok)break;
                energy-=r.fuel;fatigue=r.nextFatigue;
                ok=ok&&energy>=0&&fatigue<=cf.fatigueCapacity;
            }
            check(name+"/fuel_exhaustion",ok&&energy<1e-8&&r.lambda==0,energy,1e-8);
        }
        // One lambda scales opposed channels and gas together. These are
        // deliberately independent requests; cancellation cannot discount price.
        ActuatorPlan p;p.count=2;p.channel[0]={{10,0,0},{0,1,0},.5f};
        p.channel[1]={{-10,0,0},{0,-1,0},.5f};p.gasRate=1;p.pumpPower=c.peakPower;
        p.requestPower=c.peakPower+40*c.rowSpeed;
        MotorReceipt motor;
        const bool limited=limitMotor(c,25,0,p.requestPower,wc,motor);
        const auto force=activeWrench(p,motor.lambda);
        check("shared_lambda/opposed_channels_and_pump",limited&&motor.lambda>0&&motor.lambda<1&&
            force.v[0]==0&&std::abs(force.v[5]+20*motor.lambda)<1e-5,
            motor.lambda,1);
        std::fprintf(output,"SHARED,lambda=%.12g,gas_rate=%.12g,torque=%.12g,charged=%.12g\n",
            double(motor.lambda),double(motor.lambda*p.gasRate),double(force.v[5]),double(motor.fuel));
    }
    void assay4() {
        auto h=clone();HeldOuter held;held.requests.speed=82;
        CruiseStats warm(h.states[0]);
        run("cal4_warm_82",h,37500,held,{},[&](int,int,const SubstepReceipt& r){warm.observe(h,r,measuredIncoming);});
        warm.print("warm600",600,output);
        const auto settled=h;CruiseStats s(h.states[0]);
        #ifdef HYDRO_CAL4_E2E_FAULT
        hydrofault::active=true;
#endif
        const auto w=run("cal4_cruise_82_120s",h,7500,held,{},[&](int,int,const SubstepReceipt& r){s.observe(h,r,measuredIncoming);});
        #ifdef HYDRO_CAL4_E2E_FAULT
        hydrofault::active=false;
#endif
        s.print("cruise120",120,output);
        // Basal/maintenance retain roundoff screens. D-M2b1-7 defines a
        // distinct free-cruise component band and a restrained reference gate.
        constexpr double roundoff=8*double(std::numeric_limits<float>::epsilon());
        // Preserve the settled diagnostic wrapper's straightness/settling
        // screens under corrected D-M2b1-7; these test trajectory, not upright
        // body attitude or tracking the requested depth.
        check("cal4/level_path_vertical_below_.01",s.maxVertical<.01,s.maxVertical,.01);
        check("cal4/depth_drift_below_.1",std::abs(s.lastDepth-s.firstDepth)<.1,s.lastDepth-s.firstDepth,.1);
        check("cal4/straight_no_heading_change",std::abs(s.heading)<1e-5,s.heading,1e-5);
        check("cal4/geneCost_zero",h.config.geneCost==0&&s.gene==0,s.gene,0);
        check("cal4/basal_.80",std::abs(s.basal/120-.8)<=roundoff*.8,s.basal/120,.8);
        check("cal4/maintenance_.10",std::abs(s.maint/120-.1)<=roundoff*.1,s.maint/120,.1);
        check("cal4/free_motor_.60_plus_minus_.008",freeMotorPass(s.motor/120),s.motor/120-.6,kFreeMotorBand);
        check("cal4/total_1.50_plus_minus_.02",std::abs(w.debit/120-1.5)<=.02,w.debit/120,.02);
        check("cal4/debit_180_plus_minus_2.4",std::abs(w.debit-180)<=2.4,w.debit,2.4);
        check("cal4/every_debit_matches_rounded_ledger",s.debitAccounted,s.ledgerRounding,0);
        check("cal4/channel_and_pump_prices_accounted",s.pricesAccounted,s.maxPriceError,2e-5);
        check("cal4/independent_motor_fatigue_accounting",s.motorAccounted,s.maxFuelError,0);
        check("cal4/no_unexplained_control_or_contact",s.controlActive==0&&s.controlFuel==0&&s.contacts==0&&s.rails==0,s.controlFuel,0);
        std::fprintf(output,"CAL4_DISCLOSURE,pitch_deg=%.12g,climb=%.12g,integrated_climb=%.12g,stored_depth_drift=%.12g,"
            "steady_depth=%.12g,target_depth=120,gas_prep_E=%.12g,gas_cruise_E=%.12g,ledger_rounding_E=%.12g,"
            "numeric_body_pitch_or_target_depth_gate=false\n",s.pitch/s.count,s.vertical/s.count,s.vertical*double(kSubDt),
            s.lastDepth-s.firstDepth,s.lastDepth,warm.gasFuel,s.gasFuel,s.ledgerRounding);
        auto turned=settled;HeldOuter turn=held;turn.requests.yaw=1;CruiseStats ts(turned.states[0]);
        run("cal4_extra_turn",turned,625,turn,{},[&](int,int,const SubstepReceipt& r){ts.observe(turned,r,measuredIncoming);});ts.print("turn10",10,output);
        check("cal4/turn_additional_work_charged",ts.controlFuel>0&&ts.motor/10>s.motor/120&&ts.pricesAccounted&&ts.debitAccounted,ts.motor/10-s.motor/120,0);
        // Exact kinematic block at the assay-1 reference, zero incoming motion
        // at every price evaluation, with filters and fatigue evolved normally.
        auto block=clone();run("cal4_block_reference",block,3750);
        const auto& c=block.coefficients[0];auto bs=block.states[0];Loaded L;
        if(!loadAt(c,240,bs,25,L))throw std::runtime_error("blocked reference load refused");
        double blockedFuel=0,blockedForce=0,blockedPower=0;float fatigue=0;bool blockedOK=true;
        for(int i=0;i<1250;++i) {
            ActuatorPlan p;MotorReceipt m;
            if(!planActuators(c,L,bs,block.config,{82,0,0,0},.5f,V6{},p)||
               !limitMotor(c,25-kSubDt*(c.basalPower+maintenancePower(c,25)),fatigue,p.requestPower,references().workConversion,m)) {blockedOK=false;break;}
            const auto active=activeWrench(p,m.lambda);
            blockedFuel+=m.fuel;blockedForce-=active.v[0];blockedPower+=m.actualPower;
            bs.tailDrive=p.nextTailDrive;bs.tailYaw=p.nextTailYaw;fatigue=m.nextFatigue;
        }
        std::fprintf(output,"CAL4_BLOCKED,price_evaluations=1250,seconds=10,zero_motion=true,motor_E=%.12g,restraint_force=%.12g,mean_power=%.12g\n",
            blockedFuel,blockedForce/1250,blockedPower/1250);
        check("cal4/blocked_thrust_work_charged",blockedOK&&blockedFuel>0&&blockedForce>0,blockedFuel,0);
        MotorReceipt peak,recovery;
        const bool peakOK=limitMotor(c,25,0,c.peakPower,references().workConversion,peak);
        const double expected=double(references().workConversion)*double(kSubDt)*(peak.aerobicPower+3*double(peak.burstPower));
        check("cal4/three_times_excess_power",peakOK&&peak.burstPower>0&&std::abs(peak.fuel-expected)<=roundoff*expected,peak.fuel-expected,roundoff*expected);
        const bool recoveryOK=limitMotor(c,25,c.fatigueCapacity,0,references().workConversion,recovery);
        check("cal4/free_recovery",recoveryOK&&recovery.fuel==0&&recovery.nextFatigue<c.fatigueCapacity,recovery.fuel,0);
        // Reconfirm the frozen reference pricing independently of free trim.
        V6 towVelocity{{-82,0,0,0,0,0}};ActuatorPlan tow;MotorReceipt motor;
        bs=block.states[0];const float D=.5f*rhoWater()*L.K[0]+at6(L.Dfin,0,0);
        bs.tailDrive=D*82*82/references().thrustCap;
        float referenceConversion=references().workConversion;
#ifdef PLANT_CAL4_CONVERSION_FAULT
        referenceConversion*=PLANT_CAL4_CONVERSION_FAULT; // Tool-only negative control; no mechanics change.
#endif
        if(!planActuators(c,L,bs,block.config,{82,0,0,0},.5f,towVelocity,tow)||
           !limitMotor(c,25,0,tow.requestPower,referenceConversion,motor))throw std::runtime_error("tow price refused");
        check("cal4/restrained_reference_.60_roundoff",restrainedMotorPass(motor.fuel/double(kSubDt)),
            motor.fuel/double(kSubDt)-.6,kMotorRoundoff);
        check("cal4/restrained_reference_frozen_bits",std::bit_cast<std::uint32_t>(tow.requestPower)==calibration::kMeasuredCruisePowerBits,
            std::bit_cast<std::uint32_t>(tow.requestPower),calibration::kMeasuredCruisePowerBits);
        std::fprintf(output,"CAL4_MOTOR_DISCLOSURE,free_motor_E_s=%.12g,signed_deviation_E_s=%.12g,signed_deviation_percent=%.12g,"
            "lower_bound_margin_E_s=%.12g,lower_bound_margin_percentage_points=%.12g,known_limitation=fin_centroid_thrust_driven_trim_and_biased_depth,mechanisms_not_exhaustive=true,D3_adopted=false\n",s.motor/120,s.motor/120-.6,100*(s.motor/120-.6)/.6,s.motor/120-.592,100*(s.motor/120-.592)/.6);
        std::fprintf(output,"CAL4_AUTHORITY,reference_power=%.12g,reference_power_bits=0x%08x,work_conversion=%.12g,"
            "restrained_motor_E_s=%.12g,free_motor_E_s=%.12g,required_conversion_factor=%.12g,"
            "work_conversion_law=.60_over_frozen_reference_power,maintenance_cannot_replace_motor=true\n",
            double(tow.requestPower),std::bit_cast<std::uint32_t>(tow.requestPower),double(references().workConversion),
            motor.fuel/double(kSubDt),s.motor/120,.6/(s.motor/120));
    }
    void document(std::ostream& out,int stage,bool deterministic=false,bool units=true) const {
        auto h=clone();
        out<<std::setprecision(17)<<"{\n\"assay\":"<<stage<<",\"passed\":"<<(allOK()?"true":"false")
           ;
        // Native/Wasm libm can differ in the last bits of binary64 angle/fit
        // diagnostics. Fixtures encode result values as binary32; full-precision
        // manifests and all predicate arithmetic retain the original doubles.
        if(deterministic)out<<",\"result_value_encoding\":\"binary32\"";
        if(!deterministic)out<<",\"target\":\""<<target<<"\",\"build\":\""<<build<<"\"";
        out<<",\"tank\":[1920,1080,240],\"incoming_energy\":25,"
           <<"\"laws\":["<<kGeometryLaw<<','<<kMaterialLaw<<','<<kExpressionStage<<','<<kReferenceLaw<<','<<kMechanicsLaw<<','<<kEnergeticsLaw
           <<"],\"abis\":["<<kCoefficientAbi<<','<<kSupportAbi<<','<<kStateAbi<<"],\"frozen_through\":"<<calibration::kFrozenThrough
           <<",\"constant_digest\":\""<<hydrofix::hex64(constantDigest())<<"\",\"reference_digest\":\""<<hydrofix::hex64(digest(references()))
           <<"\",\"coefficient_digest\":\""<<hydrofix::hex64(digest(h.coefficients[0]))<<"\",\"support_digest\":\""<<hydrofix::hex64(digest(h.supports[0]))
           <<"\",\"reference_gas_content\":"<<h.states[0].gasContent<<",\"constant_bits_in_digest_order\":[";
        const float constants[]={calibration::kGravity,calibration::kPressureDepthFraction,calibration::kMetacentricFraction,
            calibration::kDepthGain,calibration::kVerticalGain,calibration::kRegulatorTau,calibration::kGasRateFraction,
            calibration::kPumpEfficiency,calibration::kStaticFriction,calibration::kDynamicFriction,
            calibration::kContactSlopPerSize,calibration::kPenetrationLimitPerSize,calibration::kControllerTau,
            calibration::kHeaveGain,calibration::kPitchGain,calibration::kPairedYawGain,calibration::kTailYawGain,
            calibration::kTailStiffSpeed,calibration::kPairedInducedEfficiency,calibration::kBrakeCd,kUref,kUsusRef,
            kUact,kPairedEfficiency,kTauBurst,kGamma,kMaintFin,kMaintWall,kMaintLipid};
        for(std::size_t i=0;i<std::size(constants);++i){if(i)out<<',';out<<std::bit_cast<std::uint32_t>(constants[i]);}
        out<<"],\"measured_power_bits\":["<<calibration::kMeasuredCruisePowerBits<<','<<calibration::kMeasuredSustainedPowerBits
           <<"],\"candidate_measured_power_bits\":["<<measuredCruise<<','<<measuredSustained<<"],\"results\":[";
        for(std::size_t i=0;i<results.size();++i){const auto& r=results[i];if(i)out<<',';
            out<<"\n{\"name\":\""<<r.name<<"\",\"pass\":"<<(r.pass?"true":"false")<<",\"value\":"<<(deterministic?double(float(r.value)):r.value)
               <<",\"limit\":"<<r.limit<<",\"outer_window\":["<<r.begin<<','<<r.end<<"]}";}
        out<<"\n],\"geometry_eligible\":["<<courseEligible<<','<<headingEligible<<"],\"windows\":[";
        for(std::size_t i=0;i<windows.size();++i){const auto& [name,w]=windows[i];if(i)out<<',';
            out<<"\n{\"name\":\""<<name<<"\",\"completed_outer\":"<<w.completed<<",\"subsidy\":"<<w.injected<<",\"debit\":"<<w.debit
               <<",\"motor\":"<<w.motor<<",\"pump_fuel\":"<<w.pumpFuel<<",\"gas_integral\":"<<w.gasIntegral<<",\"chain\":\""<<hydrofix::hex64(w.chain.h)<<"\"}";}
        out<<"\n]";
        if(deterministic&&units)out<<",\"unit_cases\":"<<hydrofixture::document();
        out<<"}\n";
        if(!out)throw std::runtime_error("manifest write failed");
    }
    void manifest(const std::string& path,int stage) const {
        std::ofstream out(path);if(!out)throw std::runtime_error("manifest open failed");
        document(out,stage);
    }
};
} // namespace hydroassay
int main(int argc,char** argv) {
    using namespace hydroassay;
    try {
        Driver d;int assay=0;bool checkAll=false,fixture=false,calOnly=false,candidate=false,diagnostics=false;std::string trace,manifest,emit;
        std::vector<std::string> overrides;
        for(int i=1;i<argc;++i) {
            const std::string a=argv[i];
            if(a=="--check-all")checkAll=true;else if(a=="--fixture")fixture=true;
            else if(a=="--calibration-fixture"){fixture=true;calOnly=true;}
            else if(a=="--candidate")candidate=true;
            else if(a=="--contact-diagnostics")diagnostics=true;
            else if(i+1<argc&&a=="--set")overrides.emplace_back(argv[++i]);
            else if(i+1<argc&&a=="--assay")assay=std::stoi(argv[++i]);
            else if(i+1<argc&&a=="--trace")trace=argv[++i];else if(i+1<argc&&a=="--manifest")manifest=argv[++i];
            else if(i+1<argc&&a=="--emit-calibration")emit=argv[++i];else if(i+1<argc&&a=="--build-id")d.build=argv[++i];
            else if(i+1<argc&&a=="--target")d.target=argv[++i];else throw std::runtime_error("unknown/incomplete argument");
        }
        if(d.target!="native"&&d.target!="wasm")throw std::runtime_error("target must be native or wasm");
        if(diagnostics) {
            if(assay||candidate||checkAll||fixture||!emit.empty()||!manifest.empty()||!trace.empty()||!overrides.empty())
                throw std::runtime_error("contact diagnostics must run separately from acceptance");
            d.contactDiagnostics();return d.allOK()?0:1;
        }
        if(candidate) {
            if(emit.empty()||assay||checkAll||fixture||!manifest.empty()||!trace.empty())
                throw std::runtime_error("candidate emission requires only --emit-calibration and optional --set");
            emitCalibration(emit,calibration::kFrozenThrough,overrides);
            return 0;
        }
        if(!overrides.empty())throw std::runtime_error("--set is candidate-only; rebuild before acceptance");
        if(fixture) {
            if(assay||checkAll||!emit.empty()||!manifest.empty()||!trace.empty()||calibration::kFrozenThrough!=4)
                throw std::runtime_error("fixture requires frozen stage 4 and must run separately");
            checkAll=true;d.output=stderr;
        }
        if(checkAll) {
            if(assay||!emit.empty()||calibration::kFrozenThrough!=4)
                throw std::runtime_error("check-all requires frozen stage 4 and no --assay/--emit-calibration");
            assay=4;
        }
        if(assay<1||assay>4)throw std::runtime_error("assay must be 1-4");
        if(assay>calibration::kFrozenThrough+1)throw std::runtime_error("preceding stage is not frozen");
        if(!trace.empty()) {
            d.trace.open(trace);if(!d.trace)throw std::runtime_error("trace open failed");
            d.trace<<std::setprecision(9)<<"case,outer,substep,incoming_energy,energy,subsidy,debit,motor,gas_rate,lambda";
            for(int i=0;i<19;++i)d.trace<<",state_word"<<i;d.trace<<'\n';
        }
        d.assay1();
        if(d.allOK()&&assay>=2)d.assay2();
        if(d.allOK()&&assay>=3)d.assay3();
        if(d.allOK()&&assay>=4)d.assay4();
        if(!manifest.empty())d.manifest(manifest,assay);
        if(!d.allOK()) {std::fprintf(stderr,"assay %d FAILED; no calibration emitted\n",assay);return 1;}
        if(!emit.empty()) {
            if(assay!=calibration::kFrozenThrough+1)throw std::runtime_error("freeze must advance exactly one stage");
            emitCalibration(emit,assay,{},assay==2?d.measuredCruise:calibration::kMeasuredCruisePowerBits,
                assay==2?d.measuredSustained:calibration::kMeasuredSustainedPowerBits);
        }
        if(fixture) {
            if(calOnly)(void)hydrofixture::document();
            std::ostringstream out;d.document(out,4,true,!calOnly);
            std::cout<<out.str();
        }
        return 0;
    } catch(const std::exception& e){std::fprintf(stderr,"hydro assay refused: %s\n",e.what());return 2;}
}

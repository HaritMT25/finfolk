// Standalone measurement tests: synthetic positions/velocities have an analytic
// radius; no simulation law is reused as the expected geometric result.
#include <cstdio>
#include "../tools/ocean_hydro_measurements.hpp"
using namespace hydroassay;
int main() {
    int failed=0;
    auto check=[&](const char* name,bool ok){std::printf("%s,%s\n",ok?"PASS":"FAIL",name);failed+=!ok;};
    auto circle=[](double rotation,double speedRange,double slip,double headingScale=1.) {
        ArcMeasurements a(.008);
        const double rate=rotation/(249*.008),R=31;
        for(int i=0;i<250;++i) {
            const double t=rotation*i/249,angle=3.1+t;
            a.sample(800+R*std::cos(angle),-450+R*std::sin(angle),
                R*std::abs(rate)*(1+speedRange*(double(i)/249-.5)),
                std::remainder(angle+1.5707963267948966,kTwoPi),
                std::remainder(3.1+1.5707963267948966+t*headingScale,kTwoPi),slip);
        }
        return a;
    };
    auto resolved=circle(1.2,0,.01);
    check("resolved_course_eligible",resolved.resolved());
    check("resolved_heading_eligible",resolved.steadyLowSlip());
    check("resolved_course_identity",resolved.coursePass());
    check("resolved_heading_identity",resolved.headingPass());
    check("fit_analytic_radius",std::abs(resolved.radius()-31)<1e-8);
    const auto clockwise=circle(-1.2,0,.01);
    check("clockwise_unwrap",clockwise.courseRate()<0&&clockwise.headingRate()<0&&clockwise.coursePass()&&clockwise.headingPass());
    const auto highSlip=circle(1.2,0,.8);
    check("high_slip_course_still_checked",highSlip.resolved()&&highSlip.coursePass()&&!highSlip.steadyLowSlip());
    const auto transient=circle(1.2,.03,.01);
    check("transient_not_exercised",!transient.resolved()&&!transient.steadyLowSlip()&&!transient.coursePass()&&!transient.headingPass());
    const auto unresolved=circle(.04,0,.01);
    check("unresolved_not_exercised",!unresolved.resolved()&&!unresolved.steadyLowSlip()&&!unresolved.coursePass());
    const auto rateMismatch=circle(1.2,0,.01,.8);
    check("small_slip_insufficient_for_heading_identity",rateMismatch.resolved()&&!rateMismatch.steadyLowSlip());
    ArcMeasurements empty(.008);check("empty_not_exercised",!empty.resolved()&&!empty.steadyLowSlip()&&empty.radius()<0);
    // Known roll/pitch under two horizontal headings: D2 must compare signed
    // angles in an aligned frame and cannot confuse +pitch with -pitch.
    hydro::HydroState a=hydro::restState({0,-120,0},{0,0,0},{1,0,0});
    auto q=hydro::qmul(hydro::poseOf(a),hydro::qnormalize({1,.03f,.04f,0}));
    a.quat[0]=q.w;a.quat[1]=q.x;a.quat[2]=q.y;a.quat[3]=q.z;
    auto b=a;const auto heading=hydro::qnormalize({.7f,0,.7f,0});q=hydro::qmul(heading,q);
    b.quat[0]=q.w;b.quat[1]=q.x;b.quat[2]=q.y;b.quat[3]=q.z;
    const auto aa=signedAngles(a),bb=signedAngles(b);
    check("D2_heading_alignment",std::abs(aa.roll-bb.roll)<1e-5&&std::abs(aa.pitch-bb.pitch)<1e-5);
    check("D2_signed_angles",aa.roll>0&&aa.pitch>0);
    // Threshold-helper unit checks only; actual pricing faults run in ocean_hydro_accounting.sh.
    const float power=std::bit_cast<float>(std::uint32_t{0x472e2e4d});
    float conversion=.60f/power;
#ifdef PLANT_CAL4_CONVERSION_FAULT
    conversion*=1.01f;
#endif
    check("restrained_motor_roundoff",restrainedMotorPass(double(conversion*power)));
    check("restrained_rejects_one_percent_conversion",!restrainedMotorPass(double((.60f/power)*1.01f*power)));
    check("free_motor_reproduced",freeMotorPass(.592894793954));
    check("free_motor_center",freeMotorPass(.60));
    check("free_motor_inclusive_endpoints",freeMotorPass(.592)&&freeMotorPass(.608));
    check("free_motor_inside_lower",freeMotorPass(.5920001));
    check("free_motor_inside_upper",freeMotorPass(.6079999));
    check("free_motor_rejects_lower_fault",!freeMotorPass(.60-.009));
    check("free_motor_rejects_upper_fault",!freeMotorPass(.60+.009));
    check("motor_rejects_nonfinite",!freeMotorPass(INFINITY)&&!restrainedMotorPass(NAN));
#ifdef PLANT_CAL4_FREE_LOW_FAULT
    check("free_motor_planted_lower",freeMotorPass(.60-.009));
#endif
#ifdef PLANT_CAL4_FREE_HIGH_FAULT
    check("free_motor_planted_upper",freeMotorPass(.60+.009));
#endif
    return failed?1:0;
}

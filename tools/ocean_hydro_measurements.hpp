#pragma once
// Measurement-only binary64 geometry. No mechanics or calibration arithmetic.
#include <algorithm>
#include <cmath>
#include <limits>
#include <vector>
#include "ocean/hydro_state.hpp"

namespace hydroassay {
// D-M2b1-7 (2026-11-25): separate restrained and free-cruise gates.
inline constexpr double kMotorAnchor = .60;
inline constexpr double kMotorRoundoff = 8*double(std::numeric_limits<float>::epsilon())*.60;
inline constexpr double kFreeMotorBand = .008;
inline bool restrainedMotorPass(double rate) {
    return std::isfinite(rate) && std::abs(rate-kMotorAnchor)<=kMotorRoundoff;
}
inline bool freeMotorPass(double rate) {
    return std::isfinite(rate) && rate>=.592 && rate<=.608;
}

inline constexpr double kDegrees = 57.29577951308232;
inline constexpr double kTwoPi = 6.283185307179586;
struct ArcMeasurements {
    struct Point { double x,z; };
    std::vector<Point> points;
    double speed=0,speedMin=std::numeric_limits<double>::infinity(),speedMax=0;
    double course=0,heading=0,previousCourse=0,previousHeading=0,maxSlip=0;
    double dt;
    explicit ArcMeasurements(double sampleDt):dt(sampleDt) {}
    void sample(double x,double z,double U,double courseAngle,double headingAngle,double slip) {
        if(!points.empty()) {
            course+=std::remainder(courseAngle-previousCourse,kTwoPi);
            heading+=std::remainder(headingAngle-previousHeading,kTwoPi);
        }
        previousCourse=courseAngle;previousHeading=headingAngle;
        points.push_back({x,z});speed+=U;
        speedMin=std::min(speedMin,U);speedMax=std::max(speedMax,U);maxSlip=std::max(maxSlip,std::abs(slip));
    }
    double meanSpeed() const {return points.empty()?0:speed/points.size();}
    double rate(double angle) const {return points.size()>1?angle/((points.size()-1)*dt):0;}
    double courseRate() const {return rate(course);}
    double headingRate() const {return rate(heading);}
    double speedRange() const {return meanSpeed()>0?(speedMax-speedMin)/meanSpeed():INFINITY;}
    const char* courseExclusion() const {
        if(points.size()<3||!(meanSpeed()>0))return "insufficient_samples_or_speed";
        if(std::abs(course)*kDegrees<5)return "course_rotation_below_5_degrees";
        if(speedRange()>.02)return "speed_range_above_2_percent";
        return "eligible";
    }
    bool resolved() const {return courseExclusion()[0]=='e';}
    const char* headingExclusion() const {
        if(!resolved())return courseExclusion();
        if(maxSlip*kDegrees>=5)return "sideslip_at_least_5_degrees";
        if(std::abs(courseRate()-headingRate())>.02*std::abs(headingRate()))return "course_heading_rate_difference_above_2_percent";
        return "eligible";
    }
    bool steadyLowSlip() const {return headingExclusion()[0]=='e';}
    double radius() const {
        if(points.size()<3)return -1;
        double mx=0,mz=0;for(auto p:points){mx+=p.x;mz+=p.z;}mx/=points.size();mz/=points.size();
        double xx=0,xz=0,zz=0,xr=0,zr=0,rr=0;
        for(auto p:points){const double a=p.x-mx,b=p.z-mz,r=a*a+b*b;
            xx+=a*a;xz+=a*b;zz+=b*b;xr+=a*r;zr+=b*r;rr+=r;}
        const double determinant=xx*zz-xz*xz;
        if(!(determinant>0))return -1;
        const double a=(xr*zz-zr*xz)/determinant,b=(zr*xx-xr*xz)/determinant;
        const double r=std::sqrt(rr/points.size()+(a*a+b*b)/4);
#ifdef PLANT_RADIUS_FAULT
        return 1.25*r; // Test-only measurement fault; state/receipts stay unchanged.
#else
        return r;
#endif
    }
    double predicted(double angularRate) const {return angularRate!=0?meanSpeed()/std::abs(angularRate):INFINITY;}
    double error(double angularRate) const {
        const double p=predicted(angularRate);
        return std::isfinite(p)&&p>0?std::abs(radius()-p)/p:INFINITY;
    }
    bool coursePass() const {return resolved()&&radius()>0&&error(courseRate())<=.05;}
    bool headingPass() const {return steadyLowSlip()&&radius()>0&&error(headingRate())<=.05;}
};
// Signed bank/pitch after removing horizontal heading. Body -x is forward,
// +y starboard, +z up; the bank uses the horizon-normal up axis.
struct SignedAngles { double roll,pitch; };
inline SignedAngles signedAngles(const hydro::HydroState& s) {
    const auto q=hydro::poseOf(s);
    const auto f=hydro::rotate(q,{-1,0,0}),right=hydro::rotate(q,{0,1,0}),up=hydro::rotate(q,{0,0,1});
    return {std::atan2(double(right.y),double(up.y))*kDegrees,
            std::atan2(double(f.y),std::hypot(double(f.x),double(f.z)))*kDegrees};
}
} // namespace hydroassay

#pragma once
// Deterministic hull manifolds and coupled effective-mass contact. All workspace
// is transient. Faces and vertex IDs, including tie breaks, are protocol order.
#include "ocean_energy.hpp"

namespace hydro {
struct BoundaryConfig { float width, height, depth; bool toroidal; };
inline V3 faceNormal(int face) {
    static constexpr V3 n[]={{1,0,0},{-1,0,0},{0,0,1},{0,0,-1},{0,-1,0},{0,1,0}};
    return n[face];
}
inline V3 faceTangent(int face,int t) {
    if(face<2) return t==0 ? V3{0,0,1} : V3{0,1,0};
    if(face<4) return t==0 ? V3{1,0,0} : V3{0,1,0};
    return t==0 ? V3{1,0,0} : V3{0,0,1};
}
inline float faceGap(const BoundaryConfig& c,int face,V3 p) {
    switch(face) { case 0:return p.x; case 1:return c.width-p.x;
    case 2:return p.z; case 3:return c.height-p.z; case 4:return -p.y; default:return c.depth+p.y; }
}
inline V6 wrench(V3 direction,V3 lever) {
    const V3 t=cross(lever,direction);
    return {{direction.x,direction.y,direction.z,t.x,t.y,t.z}};
}
inline float dot6(const V6& a,const V6& b) {
    float s=0; for(int i=0;i<6;++i) s=s+a.v[i]*b.v[i]; return s;
}
inline void add6(V6& a,const V6& b,float scale) {
    for(int i=0;i<6;++i) a.v[i]=a.v[i]+scale*b.v[i];
}
struct ContactPoint {
    int face=0,vertex=0;
    float gap=0, predicted=0;
    V3 lever{};
    V6 w[3]{}, response[3]{};
    float effective[3][3]{};
    float normalImpulse=0,tangentImpulse[2]{};
};
struct ContactReceipt {
    ContactPoint points[24]{};
    int count=0, sweeps=0;
    float maxPenetration=0;
};
// Reuse one scaled factor for the entire manifold, validating both inner
// primitive boundaries. solveLDL is deliberately unchecked in PR 1.
struct ContactFactor {
    LDL6 factor{}; float inverseLength=0;
    bool init(const S6& mass,float length) {
        V6 zeroRhs{},unused{};
        if(!solveScaled(mass,zeroRhs,length,unused,&factor)) return false;
        inverseLength=1.0f/length; return std::isfinite(inverseLength);
    }
    bool solve(const V6& rhs,V6& out) const {
        V6 scaledRhs=rhs;
        for(int i=3;i<6;++i) scaledRhs.v[i]=scaledRhs.v[i]*inverseLength;
        if(!finite(scaledRhs)) return false;
        V6 candidate=solveLDL(factor,scaledRhs);
        for(int i=3;i<6;++i) candidate.v[i]=candidate.v[i]*inverseLength;
        if(!finite(candidate)) return false;
        out=candidate; return true;
    }
};
inline float supportRadius(const Support& s,const Loaded& L) {
    const float x=std::max(std::abs(s.bounds[0]-L.com.x),std::abs(s.bounds[1]-L.com.x));
    const float y=L.k*s.bounds[2]+std::abs(L.com.y);
    const float z=L.k*s.bounds[3]+std::abs(L.com.z);
    return std::sqrt(x*x+y*y+z*z);
}
inline bool predictContact(const Coefficients& c,const Support& support,const Loaded& L,
    const BoundaryConfig& cfg,const HydroState& s,V3 waterBody,V6& velocity,ContactReceipt& receipt) {
    ContactReceipt r;
    const Q4 q=poseOf(s); const V3 com=v3(s.com);
    const V3 u{velocity.v[0],velocity.v[1],velocity.v[2]}, omega{velocity.v[3],velocity.v[4],velocity.v[5]};
    const V3 ground=add(u,waterBody);
    const float radius=supportRadius(support,L);
    const float travel=kSubDt*(std::sqrt(norm2(ground))+radius*std::sqrt(norm2(omega)));
    if(!std::isfinite(radius)||!std::isfinite(travel)) return false;
    const float slop=calibration::kContactSlopPerSize*c.size;
    for(int face=cfg.toroidal ? 4 : 0;face<6;++face) {
        if(faceGap(cfg,face,com)>radius+travel+slop) continue;
        float predicted[kSupportVertices],gaps[kSupportVertices];
        V3 levers[kSupportVertices],positions[kSupportVertices];
        const V3 n=faceNormal(face);
        float minimum=INFINITY; int first=0;
        for(int id=0;id<kSupportVertices;++id) {
            const V3 lever=sub(supportVertex(support,id,L.k),L.com);
            const V3 rw=rotate(q,lever);
            const V3 p=add(com,rw);
            const V3 v=rotate(q,add(ground,cross(omega,lever)));
            const float gap=faceGap(cfg,face,p);
            const float pg=gap+kSubDt*dot(n,v);
            if(!std::isfinite(pg)) return false;
            levers[id]=lever; positions[id]=rw; gaps[id]=gap; predicted[id]=pg;
            if(pg<minimum) { minimum=pg; first=id; }
        }
        if(minimum>slop) continue;
        int chosen[4]={first,0,0,0},count=1;
        while(count<4) {
            float best=-1; int bestId=-1;
            for(int id=0;id<kSupportVertices;++id) {
                if(predicted[id]>minimum+slop) continue;
                bool used=false; float distance=INFINITY;
                for(int j=0;j<count;++j) {
                    if(chosen[j]==id) used=true;
                    const V3 d=sub(positions[id],positions[chosen[j]]);
                    const V3 tangent=sub(d,mul(n,dot(n,d)));
                    distance=std::min(distance,norm2(tangent));
                }
                if(!used && distance>best) { best=distance; bestId=id; }
            }
            if(bestId<0) break;
            chosen[count++]=bestId;
        }
        std::sort(chosen,chosen+count);
        for(int j=0;j<count;++j) {
            ContactPoint& p=r.points[r.count++];
            p.face=face; p.vertex=chosen[j]; p.lever=levers[p.vertex];
            p.gap=gaps[p.vertex]; p.predicted=predicted[p.vertex];
        }
    }
    if(r.count==0) {receipt=r; return true;}
    ContactFactor factor;
    if(!factor.init(L.Meff,c.halfLength)) return false;
    for(int j=0;j<r.count;++j) {
        ContactPoint& p=r.points[j];
        const V3 dirs[]={faceNormal(p.face),faceTangent(p.face,0),faceTangent(p.face,1)};
        for(int i=0;i<3;++i) {
            p.w[i]=wrench(unrotate(q,dirs[i]),p.lever);
            if(!factor.solve(p.w[i],p.response[i])) return false;
        }
        for(int a=0;a<3;++a) for(int b=0;b<3;++b) {
            p.effective[a][b]=dot6(p.w[a],p.response[b]);
            if(!std::isfinite(p.effective[a][b])) return false;
        }
        const float det=p.effective[1][1]*p.effective[2][2]-p.effective[1][2]*p.effective[2][1];
        if(!(p.effective[0][0]>0 && p.effective[1][1]>0 && det>0) || !std::isfinite(det)) return false;
    }
    V6 next=velocity;
    // D-M2b1-2: prescribed local four-sweep law, unchanged. Its dynamic
    // branch can slide despite a feasible aggregate static balance; see the
    // contact_both_loads diagnostic. Global static feasibility is follow-up work.
    for(int sweep=0;sweep<4;++sweep) {
        for(int j=0;j<r.count;++j) {
            ContactPoint& p=r.points[j];
            V6 groundVelocity=next;
            groundVelocity.v[0]+=waterBody.x; groundVelocity.v[1]+=waterBody.y; groundVelocity.v[2]+=waterBody.z;
            const float vn=dot6(p.w[0],groundVelocity);
            const float target=-std::max(p.gap,0.0f)/kSubDt;
            const float jn=std::max(0.0f,p.normalImpulse+(target-vn)/p.effective[0][0]);
            add6(next,p.response[0],jn-p.normalImpulse); p.normalImpulse=jn;
            groundVelocity=next;
            groundVelocity.v[0]+=waterBody.x; groundVelocity.v[1]+=waterBody.y; groundVelocity.v[2]+=waterBody.z;
            const float v1=dot6(p.w[1],groundVelocity),v2=dot6(p.w[2],groundVelocity);
            const float a=p.effective[1][1],b=p.effective[1][2],d=p.effective[2][2];
            const float det=a*d-b*p.effective[2][1];
            float jt1=p.tangentImpulse[0]+(-d*v1+b*v2)/det;
            float jt2=p.tangentImpulse[1]+(p.effective[2][1]*v1-a*v2)/det;
            const float norm=std::sqrt(jt1*jt1+jt2*jt2);
            if(norm>calibration::kStaticFriction*jn) {
                const float slip=std::sqrt(v1*v1+v2*v2);
                const float magnitude=calibration::kDynamicFriction*jn;
                if(slip>0) {jt1=-magnitude*v1/slip; jt2=-magnitude*v2/slip;}
                else if(norm>0) {jt1=jt1*(magnitude/norm); jt2=jt2*(magnitude/norm);}
            }
            add6(next,p.response[1],jt1-p.tangentImpulse[0]);
            add6(next,p.response[2],jt2-p.tangentImpulse[1]);
            p.tangentImpulse[0]=jt1; p.tangentImpulse[1]=jt2;
            if(!finite(next)) return false;
        }
        ++r.sweeps;
    }
    velocity=next; receipt=r; return true;
}
inline float minimumGap(const Support& support,const Loaded& L,const BoundaryConfig& cfg,const HydroState& s,int face) {
    float minimum=INFINITY;
    for(int id=0;id<kSupportVertices;++id) {
        const V3 p=add(v3(s.com),rotate(poseOf(s),sub(supportVertex(support,id,L.k),L.com)));
        minimum=std::min(minimum,faceGap(cfg,face,p));
    }
    return minimum;
}
inline bool resolveBoundaries(const Coefficients& c,const Support& support,const Loaded& L,
    const BoundaryConfig& cfg,HydroState& state,float& penetration) {
    HydroState next=state;
    if(cfg.toroidal) {
        next.com[0]=next.com[0]-std::floor(next.com[0]/cfg.width)*cfg.width;
        next.com[2]=next.com[2]-std::floor(next.com[2]/cfg.height)*cfg.height;
    }
    // Test feasibility in every constrained dimension, before translating.
    for(int face=cfg.toroidal ? 4 : 0;face<6;face+=2) {
        const float length=face<2?cfg.width:(face<4?cfg.height:cfg.depth);
        const float span=length-minimumGap(support,L,cfg,next,face)-minimumGap(support,L,cfg,next,face+1);
        if(!std::isfinite(span)||span>length) return false;
    }
    for(int pass=0;pass<4;++pass) for(int face=cfg.toroidal?4:0;face<6;++face) {
        const float gap=minimumGap(support,L,cfg,next,face);
        if(!std::isfinite(gap)) return false;
        if(gap<0) put(next.com,add(v3(next.com),mul(faceNormal(face),-gap)));
    }
    float worst=0;
    for(int face=cfg.toroidal?4:0;face<6;++face) worst=std::max(worst,-minimumGap(support,L,cfg,next,face));
    if(!validState(next)||worst>calibration::kPenetrationLimitPerSize*c.size) return false;
    state=next; penetration=worst; return true;
}
} // namespace hydro

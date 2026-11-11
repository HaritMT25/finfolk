// ocean_hydro_reference.cpp — M2b1's OFFLINE NATIVE REFERENCE (never a
// runtime path, never built into the module). Independent double-precision
// recomputations of what the binary32 birth compiler and its load update
// produce (src/ocean/hydro_coefficients.hpp), over the fixture's body set
// (tools/ocean_hydro_bodies.hpp), at several loads:
//
//   partition   the 112 cells and the hull integrated again in double from
//               the same canonical points: Σ cells = hull, every cell
//               positive, the float cells' moments vs double
//   compound    independent double cell allocation and fin-lamina integration,
//               transformed parts + lipid, full parallel-axis assembly at all
//               three loads, vs evalLoad mass/COM/inertia
//   body tensors degree-two exact quadrature of local hull velocity levers:
//               Abody and Jbody, including a reversed-TR-block fault check
//   inflation   geometry law 1 recompiled at the inflation k (its inflated
//               points), the hull's moments integrated in double, vs the
//               analytic T(k) update
//   tensors     Dfin / Afin by a direct traversal of the fins at k (levers
//               from the loaded COM, in double) vs the birth bases + the
//               spatial congruence
//   solve       independently constructed passive (Meff + h D) z' = Meff z in double
//               (Gaussian elimination, partial pivoting) vs the fixed
//               unpivoted binary32 LDLᵀ
//   patch model the sequential fin-patch model's passive force — each fin
//               its own quadratic normal drag −d_j |w_j·z| (w_j·z) w_j,
//               applied fin by fin — vs the tensor law's −s Dfin z, at tow
//               (surge 40 / 82 / 108 / 120 / 150 u/s), steady turns (82 u/s
//               with 1, 2.6, 6 rad/s yaw) and relaxation states (sway, heave,
//               roll, pitch rates): REPORTED, not gated (a model comparison:
//               the tensor law prices every fin at the body's speed scale s;
//               the tow / turn / relaxation TRAJECTORY differences need the
//               integrator, M2b1 PR 2)
//
// Exits 1 when a gated check exceeds its tolerance. Native only:
//   g++ -O3 -std=c++20 -ffp-contract=off -DEVO_WORLD_OCEAN -I src tools/ocean_hydro_reference.cpp -o ohr && ./ohr
#include <cmath>
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <string>
#include <vector>
#include "ocean/hydro_coefficients.hpp"
#include "ocean_hydro_bodies.hpp"

namespace {
using namespace hydro;
struct DM { double v = 0, f[3] = {0, 0, 0}, s[6] = {0, 0, 0, 0, 0, 0}; };
struct D3 { double x, y, z; };
D3 dsub(D3 a, D3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
D3 dcross(D3 a, D3 b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
double ddot(D3 a, D3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
D3 d3(bodyplan::Vec3 p) { return {p.x, p.y, p.z}; }
void tet(DM& m, D3 a, D3 b, D3 c) {   // the tetrahedron (0, a, b, c)
    const double det = ddot(a, dcross(b, c));
    m.v += det / 6;
    const D3 s{a.x + b.x + c.x, a.y + b.y + c.y, a.z + b.z + c.z};
    m.f[0] += det * s.x / 24; m.f[1] += det * s.y / 24; m.f[2] += det * s.z / 24;
    const double w = det / 120;
    m.s[0] += w * (a.x * a.x + b.x * b.x + c.x * c.x + s.x * s.x);
    m.s[1] += w * (a.y * a.y + b.y * b.y + c.y * c.y + s.y * s.y);
    m.s[2] += w * (a.z * a.z + b.z * b.z + c.z * c.z + s.z * s.z);
    m.s[3] += w * (a.x * a.y + b.x * b.y + c.x * c.y + s.x * s.y);
    m.s[4] += w * (a.x * a.z + b.x * b.z + c.x * c.z + s.x * s.z);
    m.s[5] += w * (a.y * a.z + b.y * b.z + c.y * c.z + s.y * s.z);
}
DM hullD(const bodyplan::Points& P) {   // the origin tetrahedra over the hull (as body_plan.hpp), in double
    const bodyplan::Tris& T = bodyplan::canonicalTris();
    DM m;
    for (int k = 0; k < bodyplan::kHullTris; ++k) tet(m, d3(P.p[T.t[k].a]), d3(P.p[T.t[k].b]), d3(P.p[T.t[k].c]));
    return m;
}
// Independent material construction. Only law-1 geometry/development is shared:
// no bodymat allocation, material moments, compact load bases or Loaded values.
// Cell topology is integrated above; allocate in stable nearest-cell order here.
void add(DM& a, const DM& b, double scale = 1) {
    a.v += scale * b.v;
    for (int i = 0; i < 3; ++i) a.f[i] += scale * b.f[i];
    for (int i = 0; i < 6; ++i) a.s[i] += scale * b.s[i];
}
DM take(const std::array<DM, 112>& full, std::array<DM, 112>& rem,
        double need, D3 centre, bool eyes) {
    std::vector<int> order;
    for (int i = 0; i < 112; ++i) if (!eyes || i % 8 < 4) order.push_back(i);
    auto distance = [&](int i) {
        const DM& m = full[i];
        return ddot(dsub(D3{m.f[0] / m.v, m.f[1] / m.v, m.f[2] / m.v}, centre),
                    dsub(D3{m.f[0] / m.v, m.f[1] / m.v, m.f[2] / m.v}, centre));
    };
    std::sort(order.begin(), order.end(), [&](int a, int b) {
        return distance(a) < distance(b) || (distance(a) == distance(b) && a < b);
    });
    DM result;
    for (int i : order) {
        if (need <= 0 || rem[i].v <= 0) continue;
        const double fraction = std::min(1.0, need / rem[i].v);
        const DM piece = rem[i];
        add(result, piece, fraction);
        add(rem[i], piece, -fraction);
        need -= fraction * piece.v;
        if (eyes) {
            const int mirror = 8 * (i / 8) + 7 - i % 8;
            const DM left = rem[mirror];
            add(rem[mirror], left, -fraction);
        }
    }
    if (need > 1e-10 * full[0].v) { std::fprintf(stderr, "double allocation shortfall\n"); std::exit(1); }
    if (eyes) {
        DM left = result;
        left.f[1] *= -1; left.s[3] *= -1; left.s[5] *= -1;
        add(result, left);
    }
    return result;
}
struct DPart { double mass, centre[3], cov[3][3]; };
DPart part(const DM& m, double density, const double stretch[3], const double shift[3]) {
    DPart p{};
    p.mass = density * m.v;
    if (!(m.v > 0)) return p;
    for (int i = 0; i < 3; ++i) {
        p.centre[i] = stretch[i] * m.f[i] / m.v + shift[i];
        for (int j = 0; j < 3; ++j)
            p.cov[i][j] = density * stretch[i] * stretch[j] *
                (m.s[s3(i, j)] - m.f[i] * m.f[j] / m.v);
    }
    return p;
}
struct DCompound { double mass = 0, com[3]{}, inertia[3][3]{}; };
DCompound compound(const std::vector<DPart>& parts) {
    DCompound out;
    for (const auto& p : parts) {
        out.mass += p.mass;
        for (int i = 0; i < 3; ++i) out.com[i] += p.mass * p.centre[i];
    }
    for (double& x : out.com) x /= out.mass;
    // Central part inertia plus parallel-axis contribution, part by part.
    for (const auto& p : parts) {
        double d[3], d2 = 0, trace = 0;
        for (int i = 0; i < 3; ++i) { d[i] = p.centre[i] - out.com[i]; d2 += d[i] * d[i]; trace += p.cov[i][i]; }
        for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j)
            out.inertia[i][j] += (i == j ? trace + p.mass * d2 : 0) - p.cov[i][j] - p.mass * d[i] * d[j];
    }
    return out;
}
// Reintegrate each fin's triangles and root bases in double, rather than
// reading the production Material's lamina moments / finBasis.
struct DFin { DM moments; double basis[3]{}; };
std::array<DFin, 7> finParts(const bodyplan::Points& pts, const bodyplan::BirthCoefficients& bc) {
    std::array<DFin, 7> out{};
    const auto& tris = bodyplan::canonicalTris();
    const int caudEnd = bodyplan::kHullTris + 2 * bodyplan::kCaudalIntervals * (bodyplan::kCaudalRows - 1);
    for (int f = 0; f < 7; ++f) {
        const int first = f == 0 ? bodyplan::kHullTris : caudEnd + (f - 1) * 2 * bodyplan::kFinIntervals;
        const int end = f == 0 ? caudEnd : first + 2 * bodyplan::kFinIntervals;
        auto root = [&](int id) {
            const int base = bodyplan::kDorsal0 + (f - 1) * bodyplan::kStripSamples;
            D3 r = d3(pts.p[base + 2 * ((id - base) / 2)]);
            return D3{0, f < 3 ? 0 : r.y, r.z};
        };
        for (int t = first; t < end; ++t) {
            const auto& tri = tris.t[t];
            if (f == 0 && tri.part != 1) continue;
            const D3 vertices[] = {d3(pts.p[tri.a]), d3(pts.p[tri.b]), d3(pts.p[tri.c])};
            const D3 n = dcross(dsub(vertices[1], vertices[0]), dsub(vertices[2], vertices[0]));
            const double area = std::sqrt(ddot(n, n)) / 2;
            const double v[3][3] = {{vertices[0].x, vertices[0].y, vertices[0].z},
                {vertices[1].x, vertices[1].y, vertices[1].z}, {vertices[2].x, vertices[2].y, vertices[2].z}};
            double sum[3]{};
            for (int i = 0; i < 3; ++i) for (int a = 0; a < 3; ++a) sum[i] += v[a][i];
            out[f].moments.v += area;
            for (int i = 0; i < 3; ++i) {
                out[f].moments.f[i] += area * sum[i] / 3;
                for (int j = i; j < 3; ++j) {
                    double ss = sum[i] * sum[j];
                    for (int a = 0; a < 3; ++a) ss += v[a][i] * v[a][j];
                    out[f].moments.s[s3(i, j)] += area * ss / 12;
                }
            }
            if (f != 0) for (int id : {tri.a, tri.b, tri.c}) {
                const D3 r = root(id);
                out[f].basis[1] += area * r.y / 3; out[f].basis[2] += area * r.z / 3;
            }
        }
        if (out[f].moments.v > 0) for (double& x : out[f].basis) x /= out[f].moments.v;
        const DM lamina = out[f].moments;
        out[f].moments = DM{};
        add(out[f].moments, lamina, bc.m[bodyplan::finAt(f, bodyplan::kFinThickness)]);
    }
    return out;
}
// Degree-two exact tetrahedral quadrature. Evaluate local velocity levers at
// four interior samples of every signed hull tetrahedron. This independently
// integrates Abody and Jbody without reproducing their moment expansions.
void bodyTensors(const bodyplan::Points& pts, double k, const double com[3], double rw,
                 const double added[3], const double Khull[3], double Abody[6][6], double J[3][3]) {
    const auto& tris = bodyplan::canonicalTris();
    const double hi = (5 + 3 * std::sqrt(5.0)) / 20, lo = (5 - std::sqrt(5.0)) / 20;
    double volume = 0;
    for (int t = 0; t < bodyplan::kHullTris; ++t) {
        const auto& tri = tris.t[t];
        D3 v[] = {{0, 0, 0}, d3(pts.p[tri.a]), d3(pts.p[tri.b]), d3(pts.p[tri.c])};
        for (auto& p : v) { p.y *= k; p.z *= k; }
        const double weight = ddot(v[1], dcross(v[2], v[3])) / 24;
        volume += 4 * weight;
        for (int q = 0; q < 4; ++q) {
            D3 r{-com[0], -com[1], -com[2]};
            for (int a = 0; a < 4; ++a) {
                const double w = a == q ? hi : lo;
                r.x += w * v[a].x; r.y += w * v[a].y; r.z += w * v[a].z;
            }
            for (int axis = 0; axis < 3; ++axis) {
                const D3 e{double(axis == 0), double(axis == 1), double(axis == 2)};
                const D3 lever = dcross(r, e);
                const double w[] = {e.x, e.y, e.z, lever.x, lever.y, lever.z};
                for (int i = 0; i < 6; ++i) for (int j = 0; j < 6; ++j)
                    Abody[i][j] += weight * rw * added[axis] * w[i] * w[j];
                for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j)
                    J[i][j] += weight * Khull[axis] * w[3 + i] * w[3 + j];
            }
        }
    }
    for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j) J[i][j] /= volume;
}
// Diagnostic controls preserve geometry: split each exact quadrature weight
// into repeats equal terms, changing accumulation length without changing law.
// Float accumulation deliberately isolates summation from integrand rounding.
void momentTensors(const DM& H, double k, const double com[3], double rw,
                   const double added[3], const double K[3], double ad[6][6], double jd[3][3]) {
    const double stretch[] = {1, k, k};
    double centre[3], cov[3][3];
    for (int i = 0; i < 3; ++i) centre[i] = stretch[i] * H.f[i] / H.v;
    for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j)
        cov[i][j] = stretch[i] * stretch[j] * (H.s[s3(i,j)] / H.v - H.f[i] * H.f[j] / (H.v * H.v))
            + (centre[i] - com[i]) * (centre[j] - com[j]);
    const double V = k * k * H.v;
    // Production moment expansion, promoted throughout to double, versus
    // the independent local-lever quadrature. No production moments as inputs.
    for (int axis = 0; axis < 3; ++axis) {
        D3 e{double(axis == 0), double(axis == 1), double(axis == 2)};
        const D3 r{centre[0] - com[0], centre[1] - com[1], centre[2] - com[2]}, l = dcross(r, e);
        const double lever[] = {l.x, l.y, l.z};
        ad[axis][axis] = rw * added[axis] * V;
        for (int i = 0; i < 3; ++i) ad[axis][3+i] = ad[3+i][axis] = rw * added[axis] * V * lever[i];
    }
    const double cx=added[0], cy=added[1], cz=added[2];
    const double rot[3][3] = {{cy*cov[2][2]+cz*cov[1][1], -cz*cov[0][1], -cy*cov[0][2]},
        {-cz*cov[0][1], cx*cov[2][2]+cz*cov[0][0], -cx*cov[1][2]},
        {-cy*cov[0][2], -cx*cov[1][2], cx*cov[1][1]+cy*cov[0][0]}};
    const double resistance[3][3] = {{K[1]*cov[2][2]+K[2]*cov[1][1], -K[2]*cov[0][1], -K[1]*cov[0][2]},
        {-K[2]*cov[0][1], K[0]*cov[2][2]+K[2]*cov[0][0], -K[0]*cov[1][2]},
        {-K[1]*cov[0][2], -K[0]*cov[1][2], K[0]*cov[1][1]+K[1]*cov[0][0]}};
    for (int i=0;i<3;++i) for(int j=0;j<3;++j) {ad[3+i][3+j]=rw*V*rot[i][j]; jd[i][j]=resistance[i][j];}
}
void roundoffReport(const bodyplan::Points& pts, const DM& H, const Coefficients& c,
                    const Loaded& L, double k, const double com[3], double rw,
                    const double added[3], const double K[3], const double A[6][6],
                    const double J[3][3], const std::string& name) {
    double ad[6][6]{}, jd[3][3]{};
    momentTensors(H, k, com, rw, added, K, ad, jd);
    const double V = k * k * H.v;
    double sa=0, sj=0;
    for(int i=0;i<6;++i) for(int j=0;j<6;++j) sa=std::max(sa,std::fabs(A[i][j]));
    for(int i=0;i<3;++i) sj+=J[i][i];
    for(int i=0;i<6;++i) for(int j=i;j<6;++j)
        std::printf("ENTRY,%s,%.9g,%.9g,A,%d,%d,%.12g,%.12g,%.12g,%.12g,%.12g\n",name.c_str(),double(c.size),double(c.elong),i,j,
            double(at6(L.Abody,i,j)), A[i][j], at6(L.Abody,i,j)-A[i][j], (at6(L.Abody,i,j)-A[i][j])/sa,(ad[i][j]-A[i][j])/sa);
    for(int i=0;i<3;++i) for(int j=i;j<3;++j)
        std::printf("ENTRY,%s,%.9g,%.9g,J,%d,%d,%.12g,%.12g,%.12g,%.12g,%.12g\n",name.c_str(),double(c.size),double(c.elong),i,j,
            double(at3(L.Jbody,i,j)),J[i][j],at3(L.Jbody,i,j)-J[i][j],(at3(L.Jbody,i,j)-J[i][j])/sj,(jd[i][j]-J[i][j])/sj);
    const auto& tris=bodyplan::canonicalTris();
    const double hi=(5+3*std::sqrt(5.0))/20, lo=(5-std::sqrt(5.0))/20;
    for(int repeats : {1,2,4,8}) {
        float af[6][6]{}, jf[3][3]{};
        double aq[6][6]{}, jq[3][3]{};
        for(int t=0;t<bodyplan::kHullTris;++t) {
            const auto& tri=tris.t[t];
            D3 v[]={{0,0,0},d3(pts.p[tri.a]),d3(pts.p[tri.b]),d3(pts.p[tri.c])};
            for(auto& p:v){p.y*=k;p.z*=k;}
            const double weight=ddot(v[1],dcross(v[2],v[3]))/(24*repeats);
            for(int q=0;q<4;++q) {
                D3 r{-com[0],-com[1],-com[2]};
                for(int a=0;a<4;++a){const double w=a==q?hi:lo;r.x+=w*v[a].x;r.y+=w*v[a].y;r.z+=w*v[a].z;}
                for(int axis=0;axis<3;++axis){
                    const D3 e{double(axis==0),double(axis==1),double(axis==2)}, l=dcross(r,e);
                    const double w[]={e.x,e.y,e.z,l.x,l.y,l.z};
                    for(int rep=0;rep<repeats;++rep){
                        for(int i=0;i<6;++i)for(int j=0;j<6;++j){const double term=weight*rw*added[axis]*w[i]*w[j];af[i][j]+=float(term);aq[i][j]+=term;}
                        for(int i=0;i<3;++i)for(int j=0;j<3;++j){const double term=weight*K[axis]*w[3+i]*w[3+j]/V;jf[i][j]+=float(term);jq[i][j]+=term;}
                    }
                }
            }
        }
        double ea=0,ej=0,ed=0;
        for(int i=0;i<6;++i)for(int j=0;j<6;++j){ea=std::max(ea,std::fabs(af[i][j]-A[i][j])/sa);ed=std::max(ed,std::fabs(aq[i][j]-A[i][j])/sa);}
        for(int i=0;i<3;++i)for(int j=0;j<3;++j){ej=std::max(ej,std::fabs(jf[i][j]-J[i][j])/sj);ed=std::max(ed,std::fabs(jq[i][j]-J[i][j])/sj);}
        std::printf("TERMS,%s,%.9g,%.9g,%d,%.12g,%.12g,%.12g\n",name.c_str(),double(c.size),double(c.elong),bodyplan::kHullTris*4*3*repeats,ea,ej,ed);
    }
}
double tensorError(const S6& actual, const double expected[6][6]) {
    double scale = 0, error = 0;
    for (int i = 0; i < 6; ++i) for (int j = 0; j < 6; ++j) {
        scale = std::max(scale, std::fabs(expected[i][j]));
        error = std::max(error, std::fabs(at6(actual, i, j) - expected[i][j]));
    }
    return error / (scale > 0 ? scale : 1);
}
struct Worst {
    const char* name; double tol; bool gated; double v = 0; std::string where;
    Worst(const char* n, double t, bool g) : name(n), tol(t), gated(g) {}
    void see(double x, const std::string& w) { if (x > v || std::isnan(x)) { v = x; where = w; } }
};
double rel(double a, double b, double scale) { return std::fabs(a - b) / (scale > 0 ? scale : 1.0); }
// Gaussian elimination with partial pivoting (double, 6x6).
bool gauss(double A[6][7], double x[6]) {
    for (int c = 0; c < 6; ++c) {
        int p = c;
        for (int r = c + 1; r < 6; ++r) if (std::fabs(A[r][c]) > std::fabs(A[p][c])) p = r;
        if (A[p][c] == 0) return false;
        for (int k = 0; k < 7; ++k) std::swap(A[c][k], A[p][k]);
        for (int r = c + 1; r < 6; ++r) {
            const double f = A[r][c] / A[c][c];
            for (int k = c; k < 7; ++k) A[r][k] -= f * A[c][k];
        }
    }
    for (int r = 5; r >= 0; --r) {
        double s = A[r][6];
        for (int k = r + 1; k < 6; ++k) s -= A[r][k] * x[k];
        x[r] = s / A[r][r];
    }
    return true;
}
}  // namespace

int main(int argc, char** argv) {
    const bool characterize = argc == 2 && std::string(argv[1]) == "--roundoff";
    std::vector<hydrofix::Body> B = hydrofix::bodies();
    if (characterize) {
        const auto originals = B;
        for (const auto& b : originals) if (b.name == "neutral" || b.name == "random19")
            for (float size : {.5f, 1.f, 2.f}) for (float elong : {.5f, 1.f, 2.f}) {
                auto copy = b; copy.S = size; copy.E = elong;
                copy.name += "_sweep"; B.push_back(copy);
            }
    }
    Worst wCells{"partition: |Σ cells − hull| / hull (double)", 1e-12, true}, wCellF{"partition: float cells vs double cells (of V)", 2e-6, true};
    Worst wNeg{"partition: smallest cell / V (must be > 0)", 0, false};
    Worst wComp{"compound: independent loaded parts vs evalLoad (3 loads)", 2e-6, true};
    // Roundoff budget, established by --roundoff (no fitted tolerance):
    // each raw moment accumulates kHullTris=224 tetrahedra; allow 32 more
    // rounded operations for each integrand and the loaded tensor assembly.
    // gamma_n = n*u/(1-n*u), u=2^-24 (binary32 unit roundoff, 5.96e-8).
    // For covariance s/V-(f/V)^2, first-order propagation amplifies gamma_n
    // by (|s/V|+3*(f/V)^2)/variance. Enforce that condition <=16 below
    // (observed maximum 12.143); another factor 2 covers material COM,
    // inflation and products, and bounds higher-order gamma terms here.
    // Thus rel <= c*n*u/(1-n*u), c=2*16, n=224+32. Abody uses max-entry
    // normalization, Jbody its trace; both are normwise, not entrywise.
    // This conservative bound is accompanied by a TR-block-normalized sign
    // mutation (>1000 times this bound) and a tight double formula check.
    constexpr double kUnitRoundoff32 = 0x1p-24;
    constexpr int kMomentTerms = bodyplan::kHullTris, kAssemblyOps = 32;
    constexpr double kMaxMomentCondition = 16, kPropagationFactor = 2;
    constexpr double kN = kMomentTerms + kAssemblyOps;
    constexpr double kBodyTolerance = kPropagationFactor * kMaxMomentCondition *
        kN * kUnitRoundoff32 / (1 - kN * kUnitRoundoff32);
    Worst wAbody{"Abody: double hull quadrature vs evalLoad", kBodyTolerance, true};
    Worst wJbody{"Jbody: double hull quadrature vs evalLoad", kBodyTolerance, true};
    Worst wDouble{"body laws: double moment formula vs quadrature", 1e-12, true};
    Worst wCondition{"raw-to-central moment condition", kMaxMomentCondition, true};
    double minMutationRatio = 1e30;
    int reversedBlockChecks = 0, reversedBlockMisses = 0;
    Worst wInfl{"inflation: law-1 inflated hull (double) vs analytic T(k)", 1e-5, true};
    Worst wTen{"tensors: direct traversal at k (double) vs bases + congruence", 2e-6, true};
    Worst wSolve{"solve: double Gauss vs binary32 LDLᵀ (|Δz| / |z|)", 2e-5, true};
    double minCellFrac = 1e30;
    int compiled = 0, failed = 0;
    // patch-model report accumulators: per state, the ratio |Q_tensor| / |Q_patch| summed over bodies
    struct State { const char* name; double z[6]; };
    const State states[] = {
        {"tow 40", {-40, 0, 0, 0, 0, 0}}, {"tow 82", {-82, 0, 0, 0, 0, 0}}, {"tow 108", {-108, 0, 0, 0, 0, 0}},
        {"tow 120", {-120, 0, 0, 0, 0, 0}}, {"tow 150", {-150, 0, 0, 0, 0, 0}},
        {"turn 82 / 1 rad/s", {-82, 0, 0, 0, 0, -1.0}}, {"turn 82 / 2.6", {-82, 0, 0, 0, 0, -2.6}}, {"turn 82 / 6", {-82, 0, 0, 0, 0, -6.0}},
        {"sideslip 82 / 5 deg", {-82 * 0.9962, 82 * 0.0872, 0, 0, 0, 0}},
        {"sway 10", {0, 10, 0, 0, 0, 0}}, {"heave 10", {0, 0, 10, 0, 0, 0}},
        {"roll 3 rad/s", {0, 0, 0, 3, 0, 0}}, {"pitch 2 rad/s", {0, 0, 0, 0, 2, 0}}, {"yaw 3 rad/s", {0, 0, 0, 0, 0, 3}},
    };
    const int nStates = (int)(sizeof states / sizeof states[0]);
    std::vector<double> ratioSum(nStates, 0), ratioMin(nStates, 1e30), ratioMax(nStates, 0), cosSum(nStates, 0);
    std::vector<int> ratioN(nStates, 0);
    for (const hydrofix::Body& b : B) {
        Coefficients c;
        Support s;
        if (compile(b.G, b.S, b.E, b.P, Params{}, c, s) != kOk) { ++failed; continue; }
        ++compiled;
        const double rw = 1.0 / bodyplan::referenceVolume();
        // ---- partition, in double ----
        bodyplan::BirthCoefficients bc;
        bodyplan::Points pts;
        bodyplan::compile(expressAppearance(b.G), b.S, b.E, expressPhysical(b.P), bodyplan::kGeometryLaw, bc, nullptr, &pts);
        const DM birthHull = hullD(pts);
        for (int i = 0; i < 3; ++i) {
            const double raw = birthHull.s[s3(i,i)] / birthHull.v;
            const double mean = birthHull.f[i] / birthHull.v;
            wCondition.see((std::fabs(raw) + 3 * mean * mean) / (raw - mean * mean), b.name);
        }
        std::array<DM, 112> cells{};
        {
            const DM H = birthHull;
            bodymat::Cells cf;
            bodymat::cellMoments(pts, cf);
            DM sum;
            for (int i = 0; i < bodymat::kBands; ++i)
                for (int k = 0; k < bodymat::kAround; ++k) {
                    auto rp = [&](int ii, int kk) { return ii == 0 ? d3(pts.p[bodyplan::kHullTip]) : d3(pts.p[bodyplan::kHullRing0 + 8 * (ii - 1) + (kk % 8)]); };
                    const D3 P{rp(i, 0).x, 0, 0}, Q{rp(i + 1, 0).x, 0, 0};
                    // the cell's closed boundary from the ORIGIN (every face: surface, both sectors, both radial faces)
                    DM m;
                    const D3 A = rp(i, k), Bv = rp(i, k + 1), C = rp(i + 1, k + 1), D = rp(i + 1, k);
                    if (i == 0) tet(m, A, C, D);
                    else if (k < 4) { tet(m, A, Bv, C); tet(m, A, C, D); }
                    else { tet(m, A, Bv, D); tet(m, Bv, C, D); }
                    tet(m, Q, D, C);
                    tet(m, P, Bv, A);                 // the near sector (outward −x)
                    tet(m, P, A, D); tet(m, P, D, Q); // the lower radial face
                    tet(m, P, C, Bv); tet(m, P, Q, C); // the upper radial face
                    cells[8 * i + k] = m;
                    sum.v += m.v;
                    for (int q = 0; q < 3; ++q) sum.f[q] += m.f[q];
                    for (int q = 0; q < 6; ++q) sum.s[q] += m.s[q];
                    const bodymat::Moments& fm = cf.c[8 * i + k];
                    minCellFrac = std::min(minCellFrac, m.v / H.v);
                    wCellF.see(rel(fm.v, m.v, H.v), b.name + " cell " + std::to_string(8 * i + k));
                    const double L = c.hullLength;
                    for (int q = 0; q < 3; ++q) wCellF.see(rel(fm.f[q], m.f[q], H.v * L), b.name + " cell first");
                    for (int q = 0; q < 6; ++q) wCellF.see(rel(fm.s[q], m.s[q], H.v * L * L), b.name + " cell second");
                }
            wCells.see(rel(sum.v, H.v, H.v), b.name);
            for (int q = 0; q < 3; ++q) wCells.see(rel(sum.f[q], H.f[q], H.v * c.hullLength), b.name + " first");
            for (int q = 0; q < 6; ++q) wCells.see(rel(sum.s[q], H.s[q], H.v * c.hullLength * c.hullLength), b.name + " second");
        }
        auto remaining = cells;
        const auto px = expressPhysical(b.P);
        const double storage = bc.m[bodyplan::at(bodyplan::fStorageScale)];
        const DM eyes = take(cells, remaining, bc.m[bodyplan::at(bodyplan::fEyeOrganVolume)] / 2,
                             d3(pts.p[bodyplan::kEyeR0]), true);
        const float* mouth = bc.m + bodyplan::at(bodyplan::fMouthCentre);
        const DM jaw = take(cells, remaining, bc.m[bodyplan::at(bodyplan::fJawVolume)], {mouth[0], mouth[1], mouth[2]}, false);
        const DM walls = take(cells, remaining, .02 * storage *
            (px.g[physical::kBladder] + double(px.g[physical::kFat])) * birthHull.v,
            {birthHull.f[0] / birthHull.v, birthHull.f[1] / birthHull.v, birthHull.f[2] / birthHull.v}, false);
        DM tissue = birthHull;
        add(tissue, eyes, -1); add(tissue, jaw, -1); add(tissue, walls, -1);
        const auto finMaterial = finParts(pts, bc);
        // ---- loads: inflation, tensors, solve, the patch model ----
        const float loads[3][2] = {{0.0f, 0.0f}, {0.5f, 0.25f}, {1.0f, 1.0f}};
        for (const auto& ld : loads) {
            const float Vg = ld[0] * c.gasCapacity, Mf = ld[1] * c.reserveCapacity * (bodymat::kRhoLipid * rhoWater());
            Loaded L;
            if (!evalLoad(c, Vg, Mf, L)) { ++failed; continue; }
            const std::string loadName = b.name + " gas=" + std::to_string(ld[0]) + " fuel=" + std::to_string(ld[1]);
            const double fuelVolume = Mf / (.90 * rw);
            const double kd = std::sqrt(1 + (Vg + fuelVolume) / birthHull.v), td = kd - 1;
            const double stretch[] = {1, kd, kd}, identity[] = {1, 1, 1}, zeroShift[] = {0, 0, 0};
            std::vector<DPart> parts;
            parts.push_back(part(tissue, 1.04 * rw, stretch, zeroShift));
            parts.push_back(part(jaw, 1.04 * rw, stretch, zeroShift));
            parts.push_back(part(eyes, 1.10 * rw, stretch, zeroShift));
            parts.push_back(part(walls, 1.04 * rw, stretch, zeroShift));

            for (const auto& fin : finMaterial) {
                const double shift[] = {td * fin.basis[0], td * fin.basis[1], td * fin.basis[2]};
                parts.push_back(part(fin.moments, 1.10 * rw, identity, shift));
            }
            parts.push_back(part(birthHull, Mf / birthHull.v, stretch, zeroShift));
            const DCompound material = compound(parts);
            wComp.see(rel(L.mass, material.mass, material.mass), loadName + " mass");
            const double actualCom[] = {L.com.x, L.com.y, L.com.z};
            const double traceI = material.inertia[0][0] + material.inertia[1][1] + material.inertia[2][2];
            for (int i = 0; i < 3; ++i) {
                wComp.see(rel(actualCom[i], material.com[i], c.hullLength), loadName + " COM " + std::to_string(i));
                for (int j = i; j < 3; ++j)
                    wComp.see(rel(at3(L.inertia, i, j), material.inertia[i][j], traceI), loadName + " inertia");
            }
            // Independent body laws and quadrature, checked before the solver.
            const auto geometry = [&](int offset) { return double(bc.m[offset]); };
            double profileArea = 0;
            for (int f = 0; f < 7; ++f) profileArea += bc.m[bodyplan::finAt(f, bodyplan::kFinArea)];
            const double frontal = kd * kd * geometry(bodyplan::at(bodyplan::fFrontalArea)), wetted = kd * kd * geometry(bodyplan::at(bodyplan::fWettedArea));
            const double fineness = geometry(bodyplan::at(bodyplan::fHullLength)) / std::sqrt(4 * frontal / double(bodyplan::detail::kPi));
            const double fc = std::clamp(fineness, 1.0, 30.0);
            const double cf = .008 * std::pow(geometry(bodyplan::at(bodyplan::fRefLength)) / 20, -.2);
            const double Khull[] = {(.08 + .90 / (fc * fc) + .25 * geometry(bodyplan::at(bodyplan::fForeAft))) * frontal + cf * wetted,
                1.10 * kd * geometry(bodyplan::at(bodyplan::fSideArea)) + cf * wetted, 1.10 * kd * geometry(bodyplan::at(bodyplan::fPlanArea)) + cf * wetted};
            const double added[] = {.05, geometry(bodyplan::at(bodyplan::fMaxHalfDepth)) / geometry(bodyplan::at(bodyplan::fMaxHalfWidth)),
                geometry(bodyplan::at(bodyplan::fMaxHalfWidth)) / geometry(bodyplan::at(bodyplan::fMaxHalfDepth))};
            double Abody[6][6]{}, Jbody[3][3]{};
            bodyTensors(pts, kd, material.com, rw, added, Khull, Abody, Jbody);
            if (characterize) roundoffReport(pts, birthHull, c, L, kd, material.com, rw, added, Khull, Abody, Jbody, loadName);
            wAbody.see(tensorError(L.Abody, Abody), loadName);
            double scaleJ = 0;
            for (int i = 0; i < 3; ++i) scaleJ += Jbody[i][i];
            for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j)
                wJbody.see(rel(at3(L.Jbody, i, j), Jbody[i][j], scaleJ), loadName);
            double momentA[6][6]{}, momentJ[3][3]{};
            momentTensors(birthHull, kd, material.com, rw, added, Khull, momentA, momentJ);
            double scaleA = 0, scaleTR = 0, cleanTR = 0, reversedTR = 0, maxTR = 0;
            for (int i = 0; i < 6; ++i) for (int j = 0; j < 6; ++j)
                scaleA = std::max(scaleA, std::fabs(Abody[i][j]));
            for (int i = 0; i < 6; ++i) for (int j = 0; j < 6; ++j)
                wDouble.see(rel(momentA[i][j], Abody[i][j], scaleA), loadName + " A");
            for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j)
                wDouble.see(rel(momentJ[i][j], Jbody[i][j], scaleJ), loadName + " J");
            // Normalize this structural control by its own TR block, so
            // small coupling cannot be hidden by the rotational diagonals.
            S6 reversed = L.Abody;
            for (int i = 0; i < 3; ++i) for (int j = 3; j < 6; ++j) {
                reversed.m[s6u(i,j)] *= -1;
                scaleTR = std::max(scaleTR, std::fabs(Abody[i][j]));
                maxTR = std::max(maxTR, std::fabs(double(at6(L.Abody,i,j))));
                cleanTR = std::max(cleanTR, std::fabs(at6(L.Abody,i,j) - Abody[i][j]));
                reversedTR = std::max(reversedTR, std::fabs(at6(reversed,i,j) - Abody[i][j]));
            }
            // Exactly zero TR is physically unable to expose a sign reversal.
            // Still require it to remain zero within the normwise budget.
            if (scaleTR > 1e-12 * scaleA) {
                ++reversedBlockChecks;
                const double ratio = reversedTR / scaleTR / kBodyTolerance;
                minMutationRatio = std::min(minMutationRatio, ratio);
                if (!(cleanTR <= kBodyTolerance * scaleA && ratio > 1000)) ++reversedBlockMisses;
            } else if (maxTR > kBodyTolerance * scaleA) ++reversedBlockMisses;
            // inflation: law 1 at this k
            {
                bodyplan::Morph M = bodyplan::decodeMorph(expressAppearance(b.G).g, c.refLength / c.radius);
                M.inflate = L.k;
                bodyplan::Points pk;
                bodyplan::restPoints(M, c.radius, pk);
                const DM H = hullD(pk);
                const double cxd = H.f[0] / H.v, cyd = H.f[1] / H.v, czd = H.f[2] / H.v;
                wInfl.see(rel(L.hullVolume, H.v, H.v), b.name + " volume");
                wInfl.see(rel(L.hullCentroid.x, cxd, c.hullLength), b.name + " centroid x");
                wInfl.see(rel(L.hullCentroid.z, czd, c.hullLength), b.name + " centroid z");
                const double cov[6] = {H.s[0] / H.v - cxd * cxd, H.s[1] / H.v - cyd * cyd, H.s[2] / H.v - czd * czd,
                                       H.s[3] / H.v - cxd * cyd, H.s[4] / H.v - cxd * czd, H.s[5] / H.v - cyd * czd};
                const S3 ck = stretchS3(S3{{c.hullCovariance[0], c.hullCovariance[1], c.hullCovariance[2], c.hullCovariance[3], c.hullCovariance[4],
                                            c.hullCovariance[5]}}, L.k);
                const double sc = cov[0] + cov[1] + cov[2];
                for (int q = 0; q < 6; ++q) wInfl.see(rel(ck.m[q], cov[q], sc), b.name + " covariance");
            }
            // tensors by traversal
            double Dd[6][6] = {}, Ad[6][6] = {};
            struct FinW { double d, w[6]; };
            std::vector<FinW> fins;
            for (int f = 0; f < bodyplan::kFinCount; ++f) {
                const float A = bc.m[bodyplan::finAt(f, bodyplan::kFinArea)];
                if (!(A > 0.0f)) continue;
                const float* n = bc.m + bodyplan::finAt(f, bodyplan::kFinNormal);
                const float* p0 = bc.m + bodyplan::finAt(f, bodyplan::kFinCentroid);
                const auto& bb = finMaterial[f].basis;
                const D3 r{p0[0] + td * bb[0] - material.com[0], p0[1] + td * bb[1] - material.com[1], p0[2] + td * bb[2] - material.com[2]};
                const D3 nn{n[0], n[1], n[2]}, rn = dcross(r, nn);
                FinW fw;
                fw.d = 0.5 * rw * kCn * A;
                const double ma = kFinAddedCoef * rw * A * bc.m[bodyplan::finAt(f, bodyplan::kFinMeanChord)];
                const double w[6] = {nn.x, nn.y, nn.z, rn.x, rn.y, rn.z};
                std::memcpy(fw.w, w, sizeof w);
                fins.push_back(fw);
                for (int i = 0; i < 6; ++i) for (int j = 0; j < 6; ++j) { Dd[i][j] += fw.d * w[i] * w[j]; Ad[i][j] += ma * w[i] * w[j]; }
            }
            double sD = 0, sA = 0;
            for (int i = 0; i < 6; ++i) for (int j = 0; j < 6; ++j) { sD = std::max(sD, std::fabs(Dd[i][j])); sA = std::max(sA, std::fabs(Ad[i][j])); }
            for (int i = 0; i < 6; ++i)
                for (int j = 0; j < 6; ++j) {
                    wTen.see(rel(at6(L.Dfin, i, j), Dd[i][j], sD), b.name + " D");
                    wTen.see(rel(at6(L.Afin, i, j), Ad[i][j], sA), b.name + " A");
                }
            // the solve
            for (int si = 0; si < nStates; ++si) {
                V6 z;
                for (int i = 0; i < 6; ++i) z.v[i] = (float)states[si].z[i];
                const S6 D = passiveDamping(L, c.halfLength, z);
                S6 A = L.Meff;
                for (int q = 0; q < 21; ++q) A.m[q] = A.m[q] + 0.008f * D.m[q];
                const V6 rhs = mulS6(L.Meff, z);
                V6 x;
                if (!solveScaled(A, rhs, c.halfLength, x)) { wSolve.see(1e30, b.name + " LDL refused"); continue; }
                const double Lcd = c.halfLength;
                const double speed = std::sqrt(states[si].z[0] * states[si].z[0] + states[si].z[1] * states[si].z[1] +
                    states[si].z[2] * states[si].z[2] + Lcd * Lcd * (states[si].z[3] * states[si].z[3] +
                    states[si].z[4] * states[si].z[4] + states[si].z[5] * states[si].z[5]));
                double G[6][7]{}, xd[6]{};
                for (int i = 0; i < 6; ++i) for (int j = 0; j < 6; ++j) {
                    const double rigid = i < 3 && j < 3 ? (i == j ? material.mass : 0) :
                        (i >= 3 && j >= 3 ? material.inertia[i - 3][j - 3] : 0);
                    const double mass = rigid + Abody[i][j] + Ad[i][j];
                    double damp = speed * Dd[i][j];
                    if (i < 3 && i == j) damp += .5 * rw * (Khull[i] + .025 * profileArea) * std::fabs(states[si].z[i]);
                    if (i >= 3 && j >= 3) damp += .5 * rw * speed * Jbody[i - 3][j - 3];
                    G[i][j] = mass + .008 * damp;
                    G[i][6] += mass * states[si].z[j];
                }
                if (!gauss(G, xd)) { wSolve.see(1e30, loadName + " double Gauss refused"); continue; }
                // compare in the scaled coordinates (u, Lc ω)
                const double Lc = c.halfLength;
                double dn = 0, xn = 0;
                for (int i = 0; i < 6; ++i) {
                    const double sc = i < 3 ? 1 : Lc;
                    dn += (x.v[i] - xd[i]) * (x.v[i] - xd[i]) * sc * sc;
                    xn += xd[i] * xd[i] * sc * sc;
                }
                if (xn > 0) wSolve.see(std::sqrt(dn / xn), b.name + " " + states[si].name);
                // the patch model at the reference-like load only (ld 0.5/0.25)
                if (ld[0] != 0.5f || fins.empty()) continue;
                double Qt[6] = {}, Qp[6] = {};
                const double sS = std::sqrt(states[si].z[0] * states[si].z[0] + states[si].z[1] * states[si].z[1] + states[si].z[2] * states[si].z[2] +
                                            Lc * Lc * (states[si].z[3] * states[si].z[3] + states[si].z[4] * states[si].z[4] + states[si].z[5] * states[si].z[5]));
                for (const FinW& fw : fins) {
                    double vn = 0;
                    for (int i = 0; i < 6; ++i) vn += fw.w[i] * states[si].z[i];
                    for (int i = 0; i < 6; ++i) { Qt[i] -= sS * fw.d * vn * fw.w[i]; Qp[i] -= fw.d * std::fabs(vn) * vn * fw.w[i]; }
                }
                double nt = 0, np = 0, dotp = 0;
                for (int i = 0; i < 6; ++i) {
                    const double sc = i < 3 ? 1 : 1 / Lc;   // forces and torques / Lc
                    nt += Qt[i] * Qt[i] * sc * sc; np += Qp[i] * Qp[i] * sc * sc; dotp += Qt[i] * Qp[i] * sc * sc;
                }
                if (np > 0 && nt > 0) {
                    const double ratio = std::sqrt(nt / np);
                    ratioSum[si] += ratio; ratioN[si]++;
                    ratioMin[si] = std::min(ratioMin[si], ratio); ratioMax[si] = std::max(ratioMax[si], ratio);
                    cosSum[si] += dotp / std::sqrt(nt * np);
                }
            }
        }
    }
    std::printf("ocean_hydro_reference: %d bodies compiled, %d failed (law versions: geometry %d, material %d, expression %d, reference %d)\n",
                compiled, failed, kGeometryLaw, kMaterialLaw, kExpressionStage, kReferenceLaw);
    bool ok = failed == 0 && minCellFrac > 0 && reversedBlockChecks > 0 && reversedBlockMisses == 0;
    for (const Worst* w : {&wCells, &wCellF, &wComp, &wInfl, &wTen, &wAbody, &wJbody, &wDouble, &wCondition, &wSolve}) {
        const bool pass = !(w->v > w->tol) && !std::isnan(w->v);
        ok = ok && pass;
        std::printf("  %-62s worst %.3e (tol %.3e) %s%s%s\n", w->name, w->v, w->tol, pass ? "ok" : "FAIL", w->where.empty() ? "" : " at ",
                    w->where.c_str());
    }
    std::printf("  %-62s %.3e %s\n", wNeg.name, minCellFrac, minCellFrac > 0 ? "ok" : "FAIL");
    std::printf("  reversed Abody TR block: %d checked, %d missed; minimum fault/tolerance %.1f\n", reversedBlockChecks, reversedBlockMisses, minMutationRatio);
    std::printf("  patch model vs tensor law (fins only; load gas .5 / fuel .25; |Q| in force and torque/Lc units; reported, not gated):\n");
    std::printf("    %-22s %10s %10s %10s %10s\n", "state", "mean |Qt|/|Qp|", "min", "max", "mean cos");
    for (int si = 0; si < nStates; ++si)
        if (ratioN[si])
            std::printf("    %-22s %10.4g %10.4g %10.4g %10.4f\n", states[si].name, ratioSum[si] / ratioN[si], ratioMin[si], ratioMax[si],
                        cosSum[si] / ratioN[si]);
    std::printf("ocean_hydro_reference: %s\n", ok ? "PASS" : "FAIL");
    return ok ? 0 : 1;
}

// ocean_hydro_reference.cpp — M2b1's OFFLINE NATIVE REFERENCE (never a
// runtime path, never built into the module). Independent double-precision
// recomputations of what the binary32 birth compiler and its load update
// produce (src/ocean/hydro_coefficients.hpp), over the fixture's body set
// (tools/ocean_hydro_bodies.hpp), at several loads:
//
//   partition   the 112 cells and the hull integrated again in double from
//               the same canonical points: Σ cells = hull, every cell
//               positive, the float cells' moments vs double
//   compound    the lean compound assembled again in double (the brief's
//               parallel-axis formula over the parts' float volume moments)
//               vs evalLoad's unloaded origin-moment assembly
//   inflation   geometry law 1 recompiled at the inflation k (its inflated
//               points), the hull's moments integrated in double, vs the
//               analytic T(k) update
//   tensors     Dfin / Afin by a direct traversal of the fins at k (levers
//               from the loaded COM, in double) vs the birth bases + the
//               spatial congruence
//   solve       the passive solve (Meff + h D) z' = Meff z in double
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
#include <cstdio>
#include <cstring>
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

int main() {
    const std::vector<hydrofix::Body> B = hydrofix::bodies();
    Worst wCells{"partition: |Σ cells − hull| / hull (double)", 1e-12, true}, wCellF{"partition: float cells vs double cells (of V)", 2e-6, true};
    Worst wNeg{"partition: smallest cell / V (must be > 0)", 0, false};
    Worst wComp{"compound: double parallel-axis vs evalLoad (unloaded)", 2e-6, true};
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
        Diagnostics d;
        if (compile(b.G, b.S, b.E, b.P, Params{}, c, s, &d) != kOk) { ++failed; continue; }
        ++compiled;
        const double rw = rhoWater();
        // ---- partition, in double ----
        bodyplan::BirthCoefficients bc;
        bodyplan::Points pts;
        bodyplan::compile(expressAppearance(b.G), b.S, b.E, expressPhysical(b.P), bodyplan::kGeometryLaw, bc, nullptr, &pts);
        {
            const DM H = hullD(pts);
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
        // ---- the compound, in double ----
        {
            const bodymat::Material& m = d.material;
            struct P { const bodymat::Moments* v; double rho; } parts[4 + 7] = {{&m.tissue, 1.04}, {&m.jaw, 1.04}, {&m.eyes, 1.10}, {&m.walls, 1.04}};
            for (int f = 0; f < 7; ++f) parts[4 + f] = P{&m.fin[f], 1.10};
            double M = 0, F[3] = {0, 0, 0}, S[6] = {0, 0, 0, 0, 0, 0};
            for (const P& p : parts) {
                const double sc = p.rho * rw;
                M += sc * p.v->v;
                for (int q = 0; q < 3; ++q) F[q] += sc * p.v->f[q];
                for (int q = 0; q < 6; ++q) S[q] += sc * p.v->s[q];
            }
            const double cx = F[0] / M, cy = F[1] / M, cz = F[2] / M;
            const double C[6] = {S[0] - M * cx * cx, S[1] - M * cy * cy, S[2] - M * cz * cz, S[3] - M * cx * cy, S[4] - M * cx * cz, S[5] - M * cy * cz};
            const double I[6] = {C[1] + C[2], C[0] + C[2], C[0] + C[1], -C[3], -C[4], -C[5]};
            Loaded L;
            evalLoad(c, 0.0f, 0.0f, L);
            const double Is = I[0] + I[1] + I[2];
            wComp.see(rel(L.mass, M, M), b.name + " mass");
            wComp.see(rel(L.com.x, cx, c.hullLength), b.name + " com");
            wComp.see(rel(L.com.z, cz, c.hullLength), b.name + " com z");
            for (int q = 0; q < 6; ++q) wComp.see(rel(L.inertia.m[q], I[q], Is), b.name + " inertia " + std::to_string(q));
        }
        // ---- loads: inflation, tensors, solve, the patch model ----
        const float loads[3][2] = {{0.0f, 0.0f}, {0.5f, 0.25f}, {1.0f, 1.0f}};
        for (const auto& ld : loads) {
            const float Vg = ld[0] * c.gasCapacity, Mf = ld[1] * c.reserveCapacity * (bodymat::kRhoLipid * rhoWater());
            Loaded L;
            evalLoad(c, Vg, Mf, L);
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
                const float A = d.body.m[bodyplan::finAt(f, bodyplan::kFinArea)];
                if (!(A > 0.0f)) continue;
                const float* n = d.body.m + bodyplan::finAt(f, bodyplan::kFinNormal);
                const float* p0 = d.body.m + bodyplan::finAt(f, bodyplan::kFinCentroid);
                const V3 bb = d.material.finBasis[f];
                const D3 r{p0[0] + (double)L.t * bb.x - L.com.x, p0[1] + (double)L.t * bb.y - L.com.y, p0[2] + (double)L.t * bb.z - L.com.z};
                const D3 nn{n[0], n[1], n[2]}, rn = dcross(r, nn);
                FinW fw;
                fw.d = 0.5 * rw * kCn * A;
                const double ma = kFinAddedCoef * rw * A * d.body.m[bodyplan::finAt(f, bodyplan::kFinMeanChord)];
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
                double G[6][7], xd[6];
                for (int i = 0; i < 6; ++i) { for (int j = 0; j < 6; ++j) G[i][j] = at6(A, i, j); G[i][6] = rhs.v[i]; }
                if (!gauss(G, xd)) continue;
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
    bool ok = failed == 0 && minCellFrac > 0;
    for (const Worst* w : {&wCells, &wCellF, &wComp, &wInfl, &wTen, &wSolve}) {
        const bool pass = !(w->v > w->tol) && !std::isnan(w->v);
        ok = ok && pass;
        std::printf("  %-62s worst %.3e (tol %.0e) %s%s%s\n", w->name, w->v, w->tol, pass ? "ok" : "FAIL", w->where.empty() ? "" : " at ",
                    w->where.c_str());
    }
    std::printf("  %-62s %.3e %s\n", wNeg.name, minCellFrac, minCellFrac > 0 ? "ok" : "FAIL");
    std::printf("  patch model vs tensor law (fins only; load gas .5 / fuel .25; |Q| in force and torque/Lc units; reported, not gated):\n");
    std::printf("    %-22s %10s %10s %10s %10s\n", "state", "mean |Qt|/|Qp|", "min", "max", "mean cos");
    for (int si = 0; si < nStates; ++si)
        if (ratioN[si])
            std::printf("    %-22s %10.4g %10.4g %10.4g %10.4f\n", states[si].name, ratioSum[si] / ratioN[si], ratioMin[si], ratioMax[si],
                        cosSum[si] / ratioN[si]);
    std::printf("ocean_hydro_reference: %s\n", ok ? "PASS" : "FAIL");
    return ok ? 0 : 1;
}

#pragma once
// ----------------------------------------------------------------------------
// hydro_math — M2b's math primitives (M2b1 PR 1: the birth-physics
// foundation). Pure functions on binary32 values: small vectors, packed
// symmetric 3x3 / 6x6 matrices, the spatial congruence that moves a 6x6
// tensor to another reference point, fixed-order unpivoted LDLᵀ, quaternions,
// the frame contract and the dissipative angular-speed projection.
//
// DETERMINISM. Every routine is a fixed sequence of IEEE + − × ÷ and sqrt
// (correctly rounded everywhere), in a fixed operation order, on binary32;
// built with -ffp-contract=off and no fast math (as the whole Ocean), it gives
// the same bits natively and in wasm. No transcendental function, no pivoting,
// no data-dependent loop length, no unordered reduction.
//
// PACKINGS.
//   S3 (symmetric 3x3): xx yy zz xy xz yz (body_plan.hpp's moment order)
//   S6 (symmetric 6x6): the upper triangle row by row:
//       (0,0) (0,1) .. (0,5) (1,1) .. (1,5) (2,2) .. (5,5)   = 21 floats
//   6-vectors are generalized velocities / forces z = (u, ω) or (F, τ):
//   translation first (0..2), rotation second (3..5).
//
// THE FRAME CONTRACT (M2a's canonical right-handed body frame, kept):
//   body +x = toward the tail (forward motion and thrust are −x)
//   body +y = starboard (the fish's right; M2a's side +1)
//   body +z = dorsal
//   world   = (legacy x, −depth, legacy y), world up = (0, 1, 0): the
//             three.js world axes the scene already uses
// A pose quaternion q = (w, x, y, z) maps canonical body coordinates into
// that world frame: v_world = R(q) v_body. An upright fish heading along the
// unit horizontal world direction f has R = [−f, f × up, up] (columns: body
// x, y, z), a proper rotation. A starboard turn is a NEGATIVE rotation about
// body z (positive STEER_X → negative yaw torque); a downward heave request is
// a negative rotation about body y (nose down: positive STEER_Z → negative
// pitch torque). tests/ocean_hydro_tests.hpp (hydro_frame) checks the signs.
// ----------------------------------------------------------------------------
#include <cmath>
#include <cstdint>
#include <cstring>

namespace hydro {

struct V3 { float x, y, z; };
struct S3 { float m[6]; };     // xx yy zz xy xz yz
struct S6 { float m[21]; };    // upper triangle, row by row
struct V6 { float v[6]; };     // (translation, rotation)
struct Q4 { float w, x, y, z; };

// ---- 3-vectors -------------------------------------------------------------------
inline V3 add(V3 a, V3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
inline V3 sub(V3 a, V3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
inline V3 mul(V3 a, float s) { return {a.x * s, a.y * s, a.z * s}; }
inline float dot(V3 a, V3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
inline V3 cross(V3 a, V3 b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
inline float norm2(V3 a) { return dot(a, a); }
inline V3 v3(const float* p) { return {p[0], p[1], p[2]}; }
inline void put(float* p, V3 a) { p[0] = a.x; p[1] = a.y; p[2] = a.z; }

// ---- packed symmetric 3x3 (xx yy zz xy xz yz) -------------------------------------
// The S3 index of (i, j), either order.
inline constexpr int s3(int i, int j) {
    return i == j ? i : ((i == 0 && j == 1) || (i == 1 && j == 0) ? 3 : ((i == 0 && j == 2) || (i == 2 && j == 0) ? 4 : 5));
}
inline float at3(const S3& A, int i, int j) { return A.m[s3(i, j)]; }
inline V3 mulS3(const S3& A, V3 v) {
    const float* a = A.m;
    return {a[0] * v.x + a[3] * v.y + a[4] * v.z, a[3] * v.x + a[1] * v.y + a[5] * v.z, a[4] * v.x + a[5] * v.y + a[2] * v.z};
}
// The inverse of a symmetric positive-definite 3x3 by cofactors (fixed order).
// Returns false (out untouched) unless the leading principal minors are
// positive and finite (Sylvester), and the inverse is finite; never repaired.
inline bool invS3(const S3& A, S3& out) {
    const float xx = A.m[0], yy = A.m[1], zz = A.m[2], xy = A.m[3], xz = A.m[4], yz = A.m[5];
    const float cxx = yy * zz - yz * yz, cyy = xx * zz - xz * xz, czz = xx * yy - xy * xy;
    const float cxy = xz * yz - xy * zz, cxz = xy * yz - xz * yy, cyz = xy * xz - xx * yz;
    const float det = xx * cxx + xy * cxy + xz * cxz;
    if (!(xx > 0.0f) || !std::isfinite(xx) || !(czz > 0.0f) || !std::isfinite(czz) ||
        !(det > 0.0f) || !std::isfinite(det)) return false;
    S3 next;
    next.m[0] = cxx / det; next.m[1] = cyy / det; next.m[2] = czz / det;
    next.m[3] = cxy / det; next.m[4] = cxz / det; next.m[5] = cyz / det;
    for (float x : next.m) if (!std::isfinite(x)) return false;
    out = next;
    return true;
}
// T S T for T = diag(1, k, k) (the transverse inflation's action on a second
// moment): xx, k xy, k xz, k² yy, k² zz, k² yz.
inline S3 stretchS3(const S3& A, float k) {
    const float k2 = k * k;
    return S3{{A.m[0], k2 * A.m[1], k2 * A.m[2], k * A.m[3], k * A.m[4], k2 * A.m[5]}};
}
// The inertia tensor of a central second moment C (∫ρ (r−c)(r−c)ᵀ): tr(C)·1 − C.
inline S3 inertiaOf(const S3& C) {
    const float* c = C.m;
    return S3{{c[1] + c[2], c[0] + c[2], c[0] + c[1], -c[3], -c[4], -c[5]}};
}

// ---- packed symmetric 6x6 -----------------------------------------------------------
// Index of (i, j), i <= j: i(11 − i)/2 + j.
inline constexpr int s6u(int i, int j) { return i * (11 - i) / 2 + j; }
inline constexpr int s6(int i, int j) { return i <= j ? s6u(i, j) : s6u(j, i); }
inline float at6(const S6& A, int i, int j) { return A.m[s6(i, j)]; }
inline void zero(S6& A) { for (float& x : A.m) x = 0.0f; }
inline void addTo(S6& A, const S6& B) { for (int i = 0; i < 21; ++i) A.m[i] = A.m[i] + B.m[i]; }
inline S6 scaled(const S6& A, float s) { S6 o; for (int i = 0; i < 21; ++i) o.m[i] = s * A.m[i]; return o; }
// A += d w wᵀ, each entry (d·w_i)·w_j.
inline void addRank1(S6& A, const V6& w, float d) {
    for (int i = 0; i < 6; ++i) {
        const float dw = d * w.v[i];
        for (int j = i; j < 6; ++j) A.m[s6u(i, j)] = A.m[s6u(i, j)] + dw * w.v[j];
    }
}
// A z, row by row, j ascending (the packed indices of row i: a constant table).
inline constexpr int kS6Row[6][6] = {{0, 1, 2, 3, 4, 5}, {1, 6, 7, 8, 9, 10}, {2, 7, 11, 12, 13, 14},
                                     {3, 8, 12, 15, 16, 17}, {4, 9, 13, 16, 18, 19}, {5, 10, 14, 17, 19, 20}};
inline V6 mulS6(const S6& A, const V6& z) {
    V6 o;
    for (int i = 0; i < 6; ++i) {
        float s = 0.0f;
        for (int j = 0; j < 6; ++j) s = s + A.m[kS6Row[i][j]] * z.v[j];
        o.v[i] = s;
    }
    return o;
}
inline float quad(const S6& A, const V6& z) {   // zᵀ A z, as (A z)·z in index order
    const V6 Az = mulS6(A, z);
    float s = 0.0f;
    for (int i = 0; i < 6; ++i) s = s + Az.v[i] * z.v[i];
    return s;
}
// A 6x6 tensor's blocks: translational (tt, symmetric), cross (tr: rows
// translation, columns rotation; 3x3 dense), rotational (rr, symmetric).
inline S3 blockTT(const S6& A) { return S3{{at6(A, 0, 0), at6(A, 1, 1), at6(A, 2, 2), at6(A, 0, 1), at6(A, 0, 2), at6(A, 1, 2)}}; }
inline S3 blockRR(const S6& A) { return S3{{at6(A, 3, 3), at6(A, 4, 4), at6(A, 5, 5), at6(A, 3, 4), at6(A, 3, 5), at6(A, 4, 5)}}; }
inline void blockTR(const S6& A, float tr[3][3]) {
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j) tr[i][j] = at6(A, i, 3 + j);
}

// The spatial congruence: a tensor about the point O (generalized coordinates
// z = (u, ω) with u the velocity of O) re-expressed about the point c (given
// relative to O). With w_c = X w_O, X = [[1, 0], [K, 1]], K = −[c]× (the
// rotation part's r × n becomes (r − c) × n = r × n − c × n), X A Xᵀ is
//   tt' = tt
//   tr' = tt Kᵀ + tr                       = tr + (row_i(tt) × c)_i
//   rr' = K tt Kᵀ + K tr + (K tr)ᵀ + rr    = rr − [c]× tr' − ([c]× tr)ᵀ
// (K tt Kᵀ + K tr = K tr' and K = −[c]×; [c]× M crosses c with each of M's
// columns). Computed in that structured form, in a fixed order; only the
// upper triangle is formed. An exact congruence of a PSD tensor is PSD.
inline S6 congruence(const S6& A, V3 c) {
    S6 o;
    float tr[3][3], trN[3][3];
    for (int i = 0; i < 3; ++i) {
        const V3 row{at6(A, i, 0), at6(A, i, 1), at6(A, i, 2)};
        const V3 rc = cross(row, c);
        const float x[3] = {rc.x, rc.y, rc.z};
        for (int j = 0; j < 3; ++j) {
            tr[i][j] = A.m[s6u(i, 3 + j)];
            trN[i][j] = tr[i][j] + x[j];
            o.m[s6u(i, 3 + j)] = trN[i][j];
        }
        for (int j = i; j < 3; ++j) o.m[s6u(i, j)] = A.m[s6u(i, j)];
    }
    float P[3][3], Q[3][3];   // P = [c]× tr' and Q = [c]× tr, column by column
    for (int j = 0; j < 3; ++j) {
        const V3 p = cross(c, V3{trN[0][j], trN[1][j], trN[2][j]}), q = cross(c, V3{tr[0][j], tr[1][j], tr[2][j]});
        P[0][j] = p.x; P[1][j] = p.y; P[2][j] = p.z;
        Q[0][j] = q.x; Q[1][j] = q.y; Q[2][j] = q.z;
    }
    for (int i = 0; i < 3; ++i)
        for (int j = i; j < 3; ++j) o.m[s6u(3 + i, 3 + j)] = (A.m[s6u(3 + i, 3 + j)] - P[i][j]) - Q[j][i];
    return o;
}

// ---- fixed-order unpivoted LDLᵀ (n = 6) ---------------------------------------------
//   D_ii = A_ii − Σ_{k<i} L_ik (L_ik D_kk)
//   L_ji = (A_ji − Σ_{k<i} L_jk (L_ik D_kk)) · (1 / D_ii)   (j > i)
// k ascending; each pivot's reciprocal formed once (six divisions in all).
// A non-positive/non-finite pivot or non-finite L entry is a FAILURE,
// reported as the current column index; nothing is clamped or repaired.
struct LDL6 {
    float L[6][6];   // unit lower triangle (strictly lower part used)
    float D[6];
    float invD[6];   // 1 / D
    int failedPivot = -1;   // -1: factorized
};
inline bool factorLDL(const S6& A, LDL6& f) {
    f.failedPivot = -1;
    float LD[6];   // L_ik D_kk for the current row i (reused by the column)
    for (int i = 0; i < 6; ++i) {
        float d = A.m[s6u(i, i)];
        for (int k = 0; k < i; ++k) { LD[k] = f.L[i][k] * f.D[k]; d = d - f.L[i][k] * LD[k]; }
        if (!(d > 0.0f) || !std::isfinite(d)) { f.failedPivot = i; return false; }
        f.D[i] = d;
        const float inv = 1.0f / d;
        if (!std::isfinite(inv)) { f.failedPivot = i; return false; }
        f.invD[i] = inv;
        for (int j = i + 1; j < 6; ++j) {
            float s = A.m[s6u(i, j)];
            for (int k = 0; k < i; ++k) s = s - f.L[j][k] * LD[k];
            const float l = s * inv;
            if (!std::isfinite(l)) { f.failedPivot = i; return false; }
            f.L[j][i] = l;
        }
    }
    return true;
}
// Solve A x = b with a factorization: L y = b, z = y / D, Lᵀ x = z.
inline V6 solveLDL(const LDL6& f, const V6& b) {
    float y[6];
    for (int i = 0; i < 6; ++i) {
        float s = b.v[i];
        for (int k = 0; k < i; ++k) s = s - f.L[i][k] * y[k];
        y[i] = s;
    }
    V6 x;
    for (int i = 5; i >= 0; --i) {
        float s = y[i] * f.invD[i];
        for (int k = i + 1; k < 6; ++k) s = s - f.L[k][i] * x.v[k];
        x.v[i] = s;
    }
    return x;
}
// The production solve: angular coordinates scaled by the half length Lc
// before factorization (z' = (u, Lc ω): every scaled entry has mass units),
//   A' = D A D, b' = D b, x = D y,   D = diag(1, 1, 1, 1/Lc, 1/Lc, 1/Lc)
// with 1/Lc formed once. Refuses invalid scales, RHS, factors or solutions
// (x untouched); a finite positive pivot with an infinite reciprocal fails too.
inline bool solveScaled(const S6& A, const V6& b, float Lc, V6& x, LDL6* factorOut = nullptr) {
    if (!(Lc > 0.0f) || !std::isfinite(Lc)) return false;
    const float s = 1.0f / Lc;
    if (!std::isfinite(s)) return false;
    for (float v : b.v) if (!std::isfinite(v)) return false;
    // tt entries unchanged, tr entries x s, rr entries (x s) x s; the packed upper triangle in order
    static constexpr int kScale[21] = {0, 0, 0, 1, 1, 1, 0, 0, 1, 1, 1, 0, 1, 1, 1, 2, 2, 2, 2, 2, 2};
    S6 As;
    for (int q = 0; q < 21; ++q) As.m[q] = kScale[q] == 0 ? A.m[q] : (kScale[q] == 1 ? A.m[q] * s : (A.m[q] * s) * s);
    V6 bs{{b.v[0], b.v[1], b.v[2], b.v[3] * s, b.v[4] * s, b.v[5] * s}};
    LDL6 f{};
    if (!factorLDL(As, f)) { if (factorOut) *factorOut = f; return false; }
    const V6 y = solveLDL(f, bs);
    const V6 next{{y.v[0], y.v[1], y.v[2], y.v[3] * s, y.v[4] * s, y.v[5] * s}};
    for (float v : next.v) if (!std::isfinite(v)) return false;
    x = next;
    if (factorOut) *factorOut = f;
    return true;
}

// ---- quaternions (w, x, y, z): body -> world ------------------------------------------
inline Q4 qmul(const Q4& a, const Q4& b) {
    return {a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
            a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
            a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
            a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w};
}
inline Q4 qconj(const Q4& q) { return {q.w, -q.x, -q.y, -q.z}; }
inline float qnorm2(const Q4& q) { return q.w * q.w + q.x * q.x + q.y * q.y + q.z * q.z; }
// Normalized by its correctly rounded length (four divisions). A zero or
// non-finite quaternion is returned unchanged with ok = false.
inline Q4 qnormalize(const Q4& q, bool* ok = nullptr) {
    const float n2 = qnorm2(q);
    if (!(n2 > 0.0f) || !std::isfinite(n2)) { if (ok) *ok = false; return q; }
    const float n = std::sqrt(n2);
    if (ok) *ok = true;
    return {q.w / n, q.x / n, q.y / n, q.z / n};
}
// R(q) v = v + 2w (u × v) + 2 u × (u × v), u = (x, y, z) (unit q).
inline V3 rotate(const Q4& q, V3 v) {
    const V3 u{q.x, q.y, q.z};
    const V3 t = mul(cross(u, v), 2.0f);
    return add(add(v, mul(t, q.w)), cross(u, t));
}
inline V3 unrotate(const Q4& q, V3 v) { return rotate(qconj(q), v); }   // Rᵀ v
// The rotation matrix's columns (body x, y, z in world coordinates).
inline void columns(const Q4& q, V3& ex, V3& ey, V3& ez) {
    ex = rotate(q, V3{1.0f, 0.0f, 0.0f});
    ey = rotate(q, V3{0.0f, 1.0f, 0.0f});
    ez = rotate(q, V3{0.0f, 0.0f, 1.0f});
}
// The specified pose update: normalize(q + ½h q ⊗ (0, ω)), ω in body coordinates.
inline Q4 integrate(const Q4& q, V3 omegaBody, float h, bool* ok = nullptr) {
    const Q4 d = qmul(q, Q4{0.0f, omegaBody.x, omegaBody.y, omegaBody.z});
    const float hh = 0.5f * h;
    return qnormalize(Q4{q.w + hh * d.w, q.x + hh * d.x, q.y + hh * d.y, q.z + hh * d.z}, ok);
}
// The quaternion of a proper rotation matrix given by its columns (body x, y,
// z in world coordinates), by the largest-diagonal branch (fixed tests, ties
// to the earlier branch). For constructing poses (founders, tests), not a hot path.
inline Q4 fromColumns(V3 ex, V3 ey, V3 ez) {
    const float m00 = ex.x, m11 = ey.y, m22 = ez.z;
    const float m01 = ey.x, m02 = ez.x, m10 = ex.y, m12 = ez.y, m20 = ex.z, m21 = ey.z;
    const float tr = m00 + m11 + m22;
    Q4 q;
    if (tr >= m00 && tr >= m11 && tr >= m22) {
        const float s = 2.0f * std::sqrt(1.0f + tr);
        q = {0.25f * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s};
    } else if (m00 >= m11 && m00 >= m22) {
        const float s = 2.0f * std::sqrt(1.0f + m00 - m11 - m22);
        q = {(m21 - m12) / s, 0.25f * s, (m01 + m10) / s, (m02 + m20) / s};
    } else if (m11 >= m22) {
        const float s = 2.0f * std::sqrt(1.0f + m11 - m00 - m22);
        q = {(m02 - m20) / s, (m01 + m10) / s, 0.25f * s, (m12 + m21) / s};
    } else {
        const float s = 2.0f * std::sqrt(1.0f + m22 - m00 - m11);
        q = {(m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25f * s};
    }
    return qnormalize(q);
}

// ---- the frame contract ------------------------------------------------------------------
inline constexpr V3 kWorldUp{0.0f, 1.0f, 0.0f};
inline V3 worldFromLegacy(float x, float y, float depth) { return {x, -depth, y}; }
inline void legacyFromWorld(V3 w, float& x, float& y, float& depth) { x = w.x; y = w.z; depth = -w.y; }
// An upright pose heading along the horizontal world direction f (unit, f.y = 0):
// body x = −f, body y = f × up (starboard), body z = up.
inline Q4 uprightPose(V3 f) {
    const V3 ex = mul(f, -1.0f), ey = cross(f, kWorldUp), ez = kWorldUp;
    return fromColumns(ex, ey, ez);
}

// ---- the dissipative angular-speed projection --------------------------------------------
// With Meff = [A B; Bᵀ C] (A translational, B the translation-rotation block),
// scaling the angular velocity by a <= 1 while keeping the effective linear
// momentum A u + B ω:
//   ω' = a ω,   u' = u + A⁻¹ B (ω − ω')
// which lowers the kinetic energy by the rotational Schur complement's share
// (tests: hydro_math). Returns false when A is not positive definite.
inline bool railProject(const S6& Meff, V3& u, V3& omega, float a) {
    const S3 A = blockTT(Meff);
    S3 Ai;
    if (!invS3(A, Ai)) return false;
    float B[3][3];
    blockTR(Meff, B);
    const V3 o2 = mul(omega, a);
    const V3 dw = sub(omega, o2);
    const V3 Bdw{B[0][0] * dw.x + B[0][1] * dw.y + B[0][2] * dw.z, B[1][0] * dw.x + B[1][1] * dw.y + B[1][2] * dw.z,
                 B[2][0] * dw.x + B[2][1] * dw.y + B[2][2] * dw.z};
    u = add(u, mulS3(Ai, Bdw));
    omega = o2;
    return true;
}
// The rail's scale for an angular speed² w2 against the limit wMax (> 0): 1 when
// within it, else wMax / sqrt(w2).
inline float railScale(float w2, float wMax) {
    const float lim2 = wMax * wMax;
    return w2 <= lim2 ? 1.0f : wMax / std::sqrt(w2);
}

}  // namespace hydro

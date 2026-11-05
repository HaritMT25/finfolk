// @ts-check
"use strict";
/* evo_boids 3-D Ocean: the swim pose on the CPU (window.EvoOceanPose).
 *
 * The swim polish's programs (web/ocean_shaders.js: POSE_GLSL, the fish
 * programs' full and lite variants) read each fish's swim pose from one float
 * the scene packs for it every frame (web/ocean_scene.js: the appearance
 * fish's fill, the plain fish's and the predators'). This is that packing and
 * what it needs, the CPU half of what POSE_GLSL's poseOf unpacks:
 *   - the reach: how far a kind's geometry reaches past its spine (REACH_APP,
 *     the appearance fish's; reachOfTemplate, a legacy template's) and the
 *     sphere that holds everything drawn for a fish (reachRadius)
 *   - the size weight: posePx (a fish's body radius in CSS px at its nearest
 *     depth), poseVisibleQ (0 for a fish wholly out of view, else the weight
 *     in 7 bits), poseQ (the two, as swimPose takes them)
 *   - the pose: posePack (the roll into the turn and the paired fins' fold),
 *     swimPose (one fish's whole pose; POSE0 unlit), packPose / unpackPose
 *     (the float's layout, both ways)
 *   - smoothCPU: GLSL's smoothstep (the weight's ramp, the fold's ease; the
 *     scene's CPU mirror of the vertex stage uses it too)
 * G is the frame's camera as the scene makes it (poseCamera: its view matrix,
 * the frustum's side planes, the focal length in CSS px, the near plane, the
 * tank's half sizes; gate and zero, the measurements' references).
 *
 * Moved from web/ocean_scene.js unchanged (the structure pass's second
 * extraction: renderer_seams_plan_codex.md, "move shared pose math with
 * production pose code"). Numbers only, no WebGL: node can load it. Display
 * only: the simulation never reads any of it. */
(function (root) {
  /* How far a kind's geometry reaches past its spine (swimPose's visibility
   * sphere, reachRadius), in the shaders' own terms. Along the spine, u body
   * lengths (s = 5 u): forward of the head at most min(uf, sn + kf / lambda),
   * behind the tail at most min(ub, tb + kb / lambda), each straight on along
   * the end link (the shaders extrapolate the spine so). Off it, pad body
   * radii: the largest |(side + the tail beat's largest, up)| (the roll turns
   * that pair, so its length holds; the fins' fold is included). The
   * appearance fish: ocean_appearance.js's morphology law over its whole gene
   * range and lambda 1.79 .. 12.5, the paired fins also folded, sampled
   * (polish-cost reach.cjs: .38 radii forward past a .4 snout, 3 behind =
   * CHORD_CAP, 6.11 off (long barbels)), with margins; its shader clamps u to
   * [-1.5, 3]. The legacy fish and predators: their template's own
   * (reachOfTemplate; fishWorld clamps u to [-.5, 1.6]). */
  var REACH_APP = { sn: 0.4, kf: 0.6, uf: 1.5, tb: 0, kb: 3.2, ub: 2.0, pad: 6.6 };
  var WAG_MAX = 0.42;   /* the tail beat's largest offset in body radii (wagAt: .3 x (1.25 + .14)) */
  /** @param {ArrayLike<number>} pos @returns {PoseReach} */
  function reachOfTemplate(pos) {
    var lo = 0, hi = 1, pad = 0;
    for (var i = 0; i < pos.length; i += 3) {
      lo = Math.min(lo, pos[i]); hi = Math.max(hi, pos[i]);
      pad = Math.max(pad, Math.sqrt(Math.pow(Math.abs(pos[i + 1]) + WAG_MAX, 2) + pos[i + 2] * pos[i + 2]));
    }
    return { sn: Math.min(0.5, -lo), kf: 0, uf: 0.5, tb: Math.min(0.6, hi - 1), kb: 0, ub: 0.6, pad: pad };
  }
  /* The radius of a sphere about the centre between the fish's head and tail
   * (at its height y) that holds everything the shaders draw for it: every
   * point of the spine's polyline lies within half its length L of that
   * centre (here L <= sqrt(5 x the sum of the squared links), Cauchy-Schwarz:
   * two square roots, tight for the near-equal links the engine keeps), the
   * Catmull-Rom curve within .4 of the longest link lmax (the Hermite basis'
   * bound), the extrapolation past the ends (along the end links, each at
   * most lmax) within the reach above; off the spine, pad x R; and the pitch
   * lifts a point by at most its distance from the head x |tan(pitch)|
   * (clamped at 1.2, as fishWorld). Glass walls only pull points toward the
   * tank. vz: the pitch (iX.x), lam: lambda (iX.z; the legacy kinds 1), K:
   * the reach. */
  /** @param {ArrayLike<number>} xs @param {ArrayLike<number>} ys @param {number} R @param {number} vz @param {number} lam @param {PoseReach} K */
  function reachRadius(xs, ys, R, vz, lam, K) {
    var S = 0, M2 = 0;
    for (var k = 0; k < 5; k++) {
      var dx = xs[k + 1] - xs[k], dy = ys[k + 1] - ys[k], q = dx * dx + dy * dy;
      S += q; if (q > M2) M2 = q;
    }
    var L = Math.sqrt(5 * S), lmax = Math.sqrt(M2);
    lam = lam > 0.5 ? lam : 0.5;
    var a = K.sn + K.kf / lam, b = K.tb + K.kb / lam;
    var ef = 5 * lmax * (a < K.uf ? a : K.uf), eb = 5 * lmax * (b < K.ub ? b : K.ub), e = ef > eb ? ef : eb;
    var t = vz === vz ? (vz < 0 ? -vz : vz) : 0, s = L + 0.4 * lmax + eb;
    if (t > 1.2) t = 1.2;
    return 0.5 * L + 0.4 * lmax + e + K.pad * R + t * (s > ef ? s : ef);
  }
  /* The swim polish's size weight of one fish (POSE_GLSL's iPose.w), from
   * what the renderer uploads for it: its spine as unwrapped (xs, ys: the
   * six sim points, head first), its body radius R (iBody.x), height y (three
   * Y), pitch vz and lambda (reachRadius; K its kind's reach). G is the
   * frame's camera (poseCamera). The body radius in CSS px at the
   * camera-space depth of the nearest point of the body's sphere (centre
   * between head and tail, radius half their distance + 2 R), R x focal /
   * depth, with the focal length from the projection matrix (FOV, zoom and
   * the panels' view offset; CSS px, so DPR plays no part): none under 6 px
   * (posePx: the cheap test every fish gets; the fills inline it), all from
   * 11; and 0 for a fish whose whole reach (reachRadius: everything drawn
   * for it) lies behind the near plane or wholly outside a side plane of the
   * view frustum, so a fish partly in view never loses its polish there
   * (poseVisibleQ, for a fish over 6 px: its weight in 7 bits, 0 .. 127, an
   * integer so nothing is boxed). Display only. */
  /** @param {ArrayLike<number>} xs @param {ArrayLike<number>} ys @param {number} R @param {number} y @param {PoseCamera} G */
  function posePx(xs, ys, R, y, G) {
    var V = G.view;
    var cx = 0.5 * (xs[0] + xs[5]) - G.halfW, cz = 0.5 * (ys[0] + ys[5]) - G.halfH;
    var ex = xs[0] - xs[5], ey = ys[0] - ys[5];
    var dn = -(V[2] * cx + V[6] * y + V[10] * cz + V[14]) - 0.5 * Math.sqrt(ex * ex + ey * ey) - 2 * R;   /* the body's nearest depth */
    return R * G.focal / (dn > G.near ? dn : G.near);
  }
  /** @param {ArrayLike<number>} xs @param {ArrayLike<number>} ys @param {number} R @param {number} y @param {PoseCamera} G @param {number} vz @param {number} lam @param {PoseReach} K @param {number} px */
  function poseVisibleQ(xs, ys, R, y, G, vz, lam, K, px) {
    var V = G.view, F = G.planes;
    var cx = 0.5 * (xs[0] + xs[5]) - G.halfW, cz = 0.5 * (ys[0] + ys[5]) - G.halfH;
    var vx = V[0] * cx + V[4] * y + V[8] * cz + V[12], vy = V[1] * cx + V[5] * y + V[9] * cz + V[13];
    var dz = -(V[2] * cx + V[6] * y + V[10] * cz + V[14]);   /* the centre's camera-space depth */
    /* the centre's distances outside the side planes (poseCamera; unit normals in the camera's x / y and depth) */
    var m = F[0] * vx + F[1] * dz, m1 = F[2] * vx + F[3] * dz, m2 = F[4] * vy + F[5] * dz, m3 = F[6] * vy + F[7] * dz;
    if (m1 > m) m = m1;
    if (m2 > m) m = m2;
    if (m3 > m) m = m3;
    if (m > 0 || dz <= G.near) {   /* the centre is out of view: does the reach come back in? */
      var rv = reachRadius(xs, ys, R, vz, lam, K);
      if (dz + rv <= G.near || m > rv) return 0;
    }
    return (127 * smoothCPU(6, 11, px) + 0.5) | 0;
  }
  /* the swim pose packed (packPose) of a fish of size weight qw / 127 > 0:
   * the roll into its turn (scaled by the weight, so a fish fading out of
   * the polish levels out and the plain programs, which draw it level, take
   * over seamlessly) and, at swimming speed v (/ 150, the engine's default
   * top speed; 0: no fold), the paired fins' fold, eased in a hard turn,
   * times the weight */
  /** @param {ArrayLike<number>} xs @param {ArrayLike<number>} ys @param {number} v @param {number} qw */
  function posePack(xs, ys, v, qw) {
    var d0x = xs[0] - xs[1], d0y = ys[0] - ys[1], d1x = xs[1] - xs[2], d1y = ys[1] - ys[2], d2x = xs[2] - xs[3], d2y = ys[2] - ys[3];
    var q1 = d1x * d1x + d1y * d1y;
    var n01 = Math.sqrt((d0x * d0x + d0y * d0y) * q1), n12 = Math.sqrt(q1 * (d2x * d2x + d2y * d2y));   /* l0 l1, l1 l2 */
    /* + = turning toward its +side; the back leans into the turn's centre */
    var turn = 0.65 * (d1x * d0y - d1y * d0x) / (n01 > 1e-6 ? n01 : 1e-6) + 0.35 * (d2x * d1y - d2y * d1x) / (n12 > 1e-6 ? n12 : 1e-6);
    var bank = 1.6 * turn;
    bank = (bank > 0.6 ? 0.6 : bank < -0.6 ? -0.6 : bank) * qw / 127;
    var b2 = bank * bank, sb = bank * (1 - b2 / 6 * (1 - b2 / 20));   /* sin, |bank| <= .6: error < 6e-6, under the 10 bits' 1.2e-3 */
    var at = turn < 0 ? -turn : turn;
    var tuck = v > 0 ? smoothCPU(0.40, 0.90, v) * (1 - smoothCPU(0.10, 0.35, at)) : 0;
    /* packPose(sin, tuck w, w): every rounded value >= 0, so round = floor(x + .5) = (x + .5) | 0 */
    return ((sb / 0.6 * 511 + 512.5) | 0) * 16384 + ((tuck * qw + 0.5) | 0) * 128 + qw;
  }
  /* The swim pose of one fish (POSE_GLSL's iPose) packed in one float: its
   * size weight (posePx, poseVisibleQ; with G.gate false every fish weighs
   * 1, the measurements' ungated reference; G.zero, 0), then, if it is lit,
   * the roll and the fold (posePack); unlit, POSE0. Display only. */
  var POSE0 = 512 * 16384;   /* packPose(0, 0, 0): level, spread, weight 0 */
  /** @param {ArrayLike<number>} xs @param {ArrayLike<number>} ys @param {number} R @param {number} y @param {PoseCamera} G @param {number} vz @param {number} lam @param {PoseReach} [K] */
  function poseQ(xs, ys, R, y, G, vz, lam, K) {
    if (G.zero) return 0;
    if (!G.gate) return 127;
    var px = posePx(xs, ys, R, y, G);
    return px > 6 ? poseVisibleQ(xs, ys, R, y, G, vz, lam, K || REACH_APP, px) : 0;
  }
  /** @param {ArrayLike<number>} xs @param {ArrayLike<number>} ys @param {number} R @param {number} y @param {number} v @param {PoseCamera} G @param {number} vz @param {number} lam @param {PoseReach} [K] */
  function swimPose(xs, ys, R, y, v, G, vz, lam, K) {
    var qw = poseQ(xs, ys, R, y, G, vz, lam, K);
    return qw > 0 ? posePack(xs, ys, v, qw) : POSE0;
  }
  /* The swim pose in one float, an integer below 2^24 (exact in a float32):
   * sin(roll) in 10 bits (steps of 0.6 / 511, 0 exact), the fold and the weight in 7 each (0 stays
   * exactly 0, 1 exactly 1); POSE_GLSL poseOf unpacks it, unpackPose too. */
  /** @param {number} s @param {number} tuck @param {number} w */
  function packPose(s, tuck, w) {
    var qs = Math.round(s / 0.6 * 511) + 512, qt = Math.round(tuck * 127), qw = Math.round(w * 127);
    return qs * 16384 + qt * 128 + qw;
  }
  /** @param {number} p */
  function unpackPose(p) {
    var qw = p % 128, r = Math.floor(p / 128), qt = r % 128, s = (Math.floor(r / 128) - 512) / 511 * 0.6;
    return [s, Math.sqrt(Math.max(1 - s * s, 0)), qt / 127, qw / 127];
  }

  /* GLSL's smoothstep(a, b, x) (the size weight's ramp, the fold's ease; the
   * scene's CPU mirror of the polished vertex stage, wagCPU) */
  /** @param {number} a @param {number} b @param {number} x */
  function smoothCPU(a, b, x) { var t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); }

  /** @type {EvoOceanPoseApi} */
  var API = {
    REACH_APP: REACH_APP, WAG_MAX: WAG_MAX, POSE0: POSE0,
    reachOfTemplate: reachOfTemplate, reachRadius: reachRadius,
    posePx: posePx, poseVisibleQ: poseVisibleQ, poseQ: poseQ, posePack: posePack, swimPose: swimPose,
    packPose: packPose, unpackPose: unpackPose, smoothCPU: smoothCPU
  };
  root.EvoOceanPose = API;
})(typeof window !== "undefined" ? window : globalThis);

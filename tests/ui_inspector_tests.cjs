// tests/ui_inspector_tests.cjs: the fish card, one DOM inspector on both pages (web/ui_common.js, web/renderer.js, web/ocean.js;
// the UI parity plan's P03: U19 to U21, U45, and the card / switch parts of U55 and U56), in node with both real modules, no browser.
//   node tests/ui_inspector_tests.cjs   (exit 0 = pass; CI's "web ui" job)
//   1. the shared parts: the common fields and their order, the subtitle; the activation clock (each switch, step and reset);
//      the brain's drawing, call for call the same as each page's own before this change when its activations are current,
//      and with no activation drawn while they wait; the colour key, call for call the old portrait
//   2. real-module data: Classic's gene count (evo_inspect_conn_count) against every fish's genome in its checkpoint and the
//      stats' mean genome length; the Ocean's genes (oc_inspect's genome length) against its link count; whenever the clock
//      says current, the inspected activations are bit-identical to a twin's that captured every step, and while it says
//      waiting they are not the step's (zeros, or an older step's)
//   3. the pages: Classic (renderer.js with its single-threaded module; the flat view on a wide screen: the card, and no HUD or
//      panel on the canvas; the tank on a stand-in scene: follow and the card), the Ocean (ocean.js with its module): zero steps,
//      pause / select / step (no silent step), a load, hiding the card without deselecting (its brain folded; the Ocean's held
//      under the live numbers), letting the fish go
//   4. the markup and styles: both cards' common stats in one order and the Ocean's own after them (data-ext), the captions,
//      the shared short-screen and touch-target rules in ui_common.css and no longer in either page
// The browser's own rendering of the card (sizes, breakpoints, DPR) is tests/ui_parity_browser.mjs's S0 / S3 pictures.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const crypto = require("crypto");
const ROOT = path.join(__dirname, ".."), WEB = path.join(ROOT, "web");

let fails = 0, checks = 0;
function ok(cond, what, info) {
  checks++;
  if (!cond) { fails++; console.log("  FAIL " + what + (info !== undefined ? "  " + JSON.stringify(info).slice(0, 600) : "")); }
  else console.log("  ok   " + what);
}
function section(name) { console.log("== " + name); }
const read = (f) => fs.readFileSync(path.join(WEB, f), "utf8");

const UIX = vm.createContext({ console, Math });
vm.runInContext(read("ui_common.js"), UIX, { filename: "ui_common.js" });
const UI = UIX.EvoUI;

/* ---------------- a recording 2D context: every call and property set, in order (numbers rounded to 1e-6) ---------------- */
function recorder(widthOf) {
  const log = [];
  const r = (v) => (typeof v === "number" ? Math.round(v * 1e6) / 1e6 : v);
  const g = new Proxy({}, {
    get(t, k) {
      if (k === "__log") return log;
      if (typeof k === "symbol") return undefined;
      if (k === "measureText") return (s) => { log.push(["measureText", s]); return { width: widthOf ? widthOf(s) : 6 * String(s).length }; };
      if (k in t) return t[k];
      return (...a) => { log.push([k].concat(a.map(r))); };
    },
    set(t, k, v) { t[k] = v; log.push(["=", k, r(v)]); return true; }
  });
  return g;
}

/* ---------------- main's drawing code, verbatim but for its free variables (the pages' before P03) ----------------
 * the identity reference for EvoUI.drawBrain / brainColor / drawPortrait: web/renderer.js's drawBrain (Classic: 41 senses,
 * 12 hidden, 12 actions, its tall layout's actions 92 px from the edge) and web/ocean.js's (any shape, 100 px) */
function OLD_brainColor(v, a) {
  var m = Math.min(1, Math.abs(v));
  return v >= 0 ? "rgba(" + Math.round(70 + 130 * m) + "," + Math.round(90 + 150 * m) + "," + Math.round(60 + 10 * m) + "," + a + ")"
                : "rgba(" + Math.round(80 + 175 * m) + "," + Math.round(90 + 20 * m) + "," + Math.round(70 + 10 * m) + "," + a + ")";
}
function OLD_classicBrain(env, s) {   /* web/renderer.js drawBrain at 4991907, after its canvas sizing */
  var w = env.w, h = env.h, dpr = env.dpr, g = env.g, i, TAU = Math.PI * 2, ACTION_SHORT = env.actShort, ACTION_LABELS = env.actLabels;
  var netHover = env.hover, netNodes = env.prev, brainColor = OLD_brainColor;
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  var wide = w > h * 1.15, pos = { sen: [], hid: [], act: [] };
  var m = 14;
  if (wide) {
    var yIn = 26, yOut = h - 40, yHid = (yIn + yOut) / 2;
    for (i = 0; i < 41; i++) pos.sen.push([m + (w - 2 * m) * i / 40, yIn]);
    for (i = 0; i < 12; i++) { var x = m + 18 + (w - 2 * m - 36) * i / 11; pos.hid.push([x, yHid]); pos.act.push([x, yOut]); }
  } else {
    var yTop = 26, yBot = h - 12, xS = 18, xA = w - 92, xH = (xS + xA) / 2;
    for (i = 0; i < 41; i++) pos.sen.push([xS, yTop + (yBot - yTop) * i / 40]);
    for (i = 0; i < 12; i++) { var y = yTop + (yBot - yTop) * i / 11; pos.hid.push([xH, y]); pos.act.push([xA, y]); }
  }
  var hoverKey = netHover >= 0 && netNodes[netHover] ? netNodes[netHover].kind + netNodes[netHover].i : null;
  for (var k = 0; k < s.connCount; k++) {
    var o = k * 5;
    var srcSen = s.conns[o] !== 0, srcNum = s.conns[o + 1] | 0;
    var sinkAct = s.conns[o + 2] !== 0, sinkNum = s.conns[o + 3] | 0, wgt = s.conns[o + 4];
    var a = srcSen ? pos.sen[srcNum] : pos.hid[srcNum];
    var b = sinkAct ? pos.act[sinkNum] : pos.hid[sinkNum];
    if (!a || !b) continue;
    var srcAct = srcSen ? s.sensors[srcNum] : s.hidden[srcNum];
    var mag = Math.min(1, Math.abs(wgt) * Math.abs(srcAct) * 1.5);
    var hl = hoverKey !== null && ((srcSen ? "Sense" : "Hidden neuron") + srcNum === hoverKey ||
                                   (sinkAct ? "Action" : "Hidden neuron") + sinkNum === hoverKey);
    g.strokeStyle = (wgt >= 0 ? "rgba(180,235,80," : "rgba(255,120,80,") + (hl ? 0.9 : (0.10 + 0.7 * mag)).toFixed(3) + ")";
    g.lineWidth = hl ? 2 : 0.8 + 1.6 * mag;
    g.beginPath();
    g.moveTo(a[0], a[1]);
    if (wide) g.bezierCurveTo(a[0], (a[1] + b[1]) / 2, b[0], (a[1] + b[1]) / 2, b[0], b[1]);
    else g.bezierCurveTo((a[0] + b[0]) / 2, a[1], (a[0] + b[0]) / 2, b[1], b[0], b[1]);
    g.stroke();
  }
  netNodes = [];
  function node(p, r, v, kind, idx) {
    g.fillStyle = brainColor(v, 1);
    g.beginPath(); g.arc(p[0], p[1], r, 0, TAU); g.fill();
    g.strokeStyle = "rgba(4,14,16,0.85)";
    g.lineWidth = 1;
    g.stroke();
    netNodes.push({ x: p[0], y: p[1], kind: kind, i: idx, v: v });
  }
  var rs = Math.max(2, Math.min(3.2, (wide ? w : h) / 41 * 0.36));
  for (i = 0; i < 41; i++) node(pos.sen[i], rs, s.sensors[i], "Sense", i);
  for (i = 0; i < 12; i++) node(pos.hid[i], 5, s.hidden[i], "Hidden neuron", i);
  for (i = 0; i < 12; i++) node(pos.act[i], 5.5, s.actions[i], "Action", i);
  if (netHover >= 0 && netNodes[netHover]) {
    var hn = netNodes[netHover];
    g.strokeStyle = "rgba(230,255,160,0.95)"; g.lineWidth = 2;
    g.beginPath(); g.arc(hn.x, hn.y, 8, 0, TAU); g.stroke();
  }
  g.font = "11px " + env.font;
  g.fillStyle = "rgba(190,210,205,0.9)";
  function tag(text, x, y) {
    var tw = g.measureText(text).width;
    g.fillStyle = "rgba(15,39,39,0.92)";
    g.fillRect(x - 3, y - 10, tw + 6, 14);
    g.fillStyle = "rgba(190,210,205,0.95)";
    g.fillText(text, x, y);
  }
  if (wide) {
    tag("senses", m, 13);
    tag("hidden", m, (26 + h - 40) / 2 - 9);
    g.fillStyle = "rgba(190,210,205,0.9)";
    g.textAlign = "center";
    for (i = 0; i < 12; i++) g.fillText(ACTION_SHORT[i], pos.act[i][0], h - 40 + (i % 2 ? 30 : 18));
    g.textAlign = "left";
  } else {
    g.fillText("senses", 6, 13);
    g.fillText("hidden", (18 + w - 92) / 2 - 18, 13);
    g.fillText("actions", w - 98, 13);
    for (i = 0; i < 12; i++) g.fillText(ACTION_LABELS[i], pos.act[i][0] + 10, pos.act[i][1] + 4);
  }
  return netNodes;
}
function OLD_oceanBrain(env, f) {   /* web/ocean.js drawBrain at 4991907, after its canvas sizing */
  var w = env.w, h = env.h, dpr = env.dpr, g = env.g, i, ACTION_SHORT = env.actShort, ACTION_LABELS = env.actLabels;
  var netHover = env.hover, netNodes = env.prev, brainColor = OLD_brainColor, nS = env.nS, nH = env.nH, nA = env.nA;
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  var wide = w > h * 1.15, pos = { sen: [], hid: [], act: [] }, m = 14;
  if (wide) {
    var yIn = 26, yOut = h - 40, yHid = (yIn + yOut) / 2;
    for (i = 0; i < nS; i++) pos.sen.push([m + (w - 2 * m) * i / (nS - 1), yIn]);
    for (i = 0; i < nH; i++) pos.hid.push([m + 18 + (w - 2 * m - 36) * i / (nH - 1), yHid]);
    for (i = 0; i < nA; i++) pos.act.push([m + 18 + (w - 2 * m - 36) * i / (nA - 1), yOut]);
  } else {
    var yTop = 26, yBot = h - 12, xS = 18, xA = w - 100, xH = (xS + xA) / 2;
    for (i = 0; i < nS; i++) pos.sen.push([xS, yTop + (yBot - yTop) * i / (nS - 1)]);
    for (i = 0; i < nH; i++) pos.hid.push([xH, yTop + (yBot - yTop) * i / (nH - 1)]);
    for (i = 0; i < nA; i++) pos.act.push([xA, yTop + (yBot - yTop) * i / (nA - 1)]);
  }
  var hoverKey = netHover >= 0 && netNodes[netHover] ? netNodes[netHover].kind + netNodes[netHover].i : null;
  for (var k = 0; k < f.connCount; k++) {
    var o = k * 5;
    var srcSen = f.conns[o] !== 0, srcNum = f.conns[o + 1] | 0, sinkAct = f.conns[o + 2] !== 0, sinkNum = f.conns[o + 3] | 0, wgt = f.conns[o + 4];
    var a = srcSen ? pos.sen[srcNum] : pos.hid[srcNum], b = sinkAct ? pos.act[sinkNum] : pos.hid[sinkNum];
    if (!a || !b) continue;
    var srcAct = srcSen ? f.sensors[srcNum] : f.hidden[srcNum];
    var mag = Math.min(1, Math.abs(wgt) * Math.abs(srcAct) * 1.5);
    var hl = hoverKey !== null && ((srcSen ? "Sense" : "Hidden neuron") + srcNum === hoverKey ||
                                   (sinkAct ? "Action" : "Hidden neuron") + sinkNum === hoverKey);
    g.strokeStyle = (wgt >= 0 ? "rgba(180,235,80," : "rgba(255,120,80,") + (hl ? 0.9 : (0.10 + 0.7 * mag)).toFixed(3) + ")";
    g.lineWidth = hl ? 2 : 0.8 + 1.6 * mag;
    g.beginPath();
    g.moveTo(a[0], a[1]);
    if (wide) g.bezierCurveTo(a[0], (a[1] + b[1]) / 2, b[0], (a[1] + b[1]) / 2, b[0], b[1]);
    else g.bezierCurveTo((a[0] + b[0]) / 2, a[1], (a[0] + b[0]) / 2, b[1], b[0], b[1]);
    g.stroke();
  }
  netNodes = [];
  function node(p, r, v, kind, idx) {
    g.fillStyle = brainColor(v, 1);
    g.beginPath(); g.arc(p[0], p[1], r, 0, Math.PI * 2); g.fill();
    g.strokeStyle = "rgba(4,14,16,0.85)"; g.lineWidth = 1; g.stroke();
    netNodes.push({ x: p[0], y: p[1], kind: kind, i: idx, v: v });
  }
  var rs = Math.max(2, Math.min(3.2, (wide ? w : h) / nS * 0.36));
  for (i = 0; i < nS; i++) node(pos.sen[i], rs, f.sensors[i], "Sense", i);
  for (i = 0; i < nH; i++) node(pos.hid[i], 5, f.hidden[i], "Hidden neuron", i);
  for (i = 0; i < nA; i++) node(pos.act[i], 5.5, f.actions[i], "Action", i);
  if (netHover >= 0 && netNodes[netHover]) {
    var hn = netNodes[netHover];
    g.strokeStyle = "rgba(230,255,160,0.95)"; g.lineWidth = 2;
    g.beginPath(); g.arc(hn.x, hn.y, 8, 0, Math.PI * 2); g.stroke();
  }
  g.font = "11px " + env.font;
  function tag(text, x, y) {
    var tw = g.measureText(text).width;
    g.fillStyle = "rgba(15,39,39,0.92)"; g.fillRect(x - 3, y - 10, tw + 6, 14);
    g.fillStyle = "rgba(190,210,205,0.95)"; g.fillText(text, x, y);
  }
  g.fillStyle = "rgba(190,210,205,0.9)";
  if (wide) {
    tag("senses", m, 13);
    tag("hidden", m, (26 + h - 40) / 2 - 9);
    g.fillStyle = "rgba(190,210,205,0.9)";
    g.textAlign = "center";
    for (i = 0; i < nA; i++) g.fillText(ACTION_SHORT[i] || "", pos.act[i][0], h - 40 + (i % 2 ? 30 : 18));
    g.textAlign = "left";
  } else {
    g.fillText("senses", 6, 13);
    g.fillText("hidden", (18 + w - 100) / 2 - 18, 13);
    g.fillText("actions", w - 106, 13);
    for (i = 0; i < nA; i++) g.fillText(ACTION_LABELS[i] || "", pos.act[i][0] + 10, pos.act[i][1] + 4);
  }
  return netNodes;
}
function OLD_portrait(c, g, rgb, size, elong, dpr) {   /* both pages' drawPortrait at 4991907 (identical but for their names) */
  var w = 56, h = 40, bodyScale = (b) => (b > 0 ? 1 + 0.4 * Math.tanh(5 * (b - 1)) : 1);
  if (c.width !== w * dpr) { c.width = w * dpr; c.height = h * dpr; }
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  var k = 3.0 * bodyScale(size), len = 1 + 0.35 * Math.tanh(4 * (elong - 1));
  g.translate(w / 2 + 4, h / 2);
  g.scale(len, 1);
  g.fillStyle = "rgb(" + rgb.join(",") + ")";
  g.beginPath();
  g.moveTo(-9 * k / 1.2, 0);
  g.bezierCurveTo(-7 * k / 1.2, -4.2 * k / 1.2, 2, -4.4 * k / 1.2, 6, -1.4);
  g.lineTo(11, -5.5); g.lineTo(9.5, 0); g.lineTo(11, 5.5); g.lineTo(6, 1.4);
  g.bezierCurveTo(2, 4.4 * k / 1.2, -7 * k / 1.2, 4.2 * k / 1.2, -9 * k / 1.2, 0);
  g.fill();
  g.fillStyle = "rgba(4,14,15,0.9)";
  g.beginPath(); g.arc(-6.2 * k / 1.2, -1.2, 1.1, 0, Math.PI * 2); g.fill();
  g.setTransform(1, 0, 0, 1, 0, 0);
}
const OLD_SENSE = "Senses on one side, actions on the other. Lime links excite, orange ones inhibit; brighter = stronger right now. Tap a dot to name it.";

/* a seeded xorshift32, for the synthetic brains */
function rng(seed) { let x = seed >>> 0 || 1; return () => { x ^= x << 13; x >>>= 0; x ^= x >>> 17; x ^= x << 5; x >>>= 0; return x / 4294967296; }; }
function synthNet(seed, nS, nH, nA, K) {
  const R = rng(seed), conns = new Float32Array(K * 5);
  for (let k = 0; k < K; k++) {
    const srcSen = R() < 0.6, sinkAct = R() < 0.5;
    conns.set([srcSen ? 1 : 0, Math.floor(R() * (srcSen ? nS : nH)), sinkAct ? 1 : 0, Math.floor(R() * (sinkAct ? nA : nH)), (R() * 8 - 4)], k * 5);
  }
  conns.set([1, nS + 3, 1, 0, 1], 0);   /* (an out-of-range source: skipped, as the pages skip it) */
  const vec = (n) => Float32Array.from({ length: n }, () => R() * 2 - 1);
  return { sensors: vec(nS), hidden: vec(nH), actions: vec(nA), conns, connCount: K };
}
const CL_SHORT = ["steer x", "steer y", "forward", "wander", "speed", "signal", "osc", "respond", "share", "breed", "fight", "ignore"];
const CL_LONG = ["steer x", "steer y", "swim forward", "wander", "speed", "signal", "oscillator period", "respond", "share food", "reproduce", "fight", "ignore"];

async function main() {
  /* ======================================================== 1. the shared parts ======================================================== */
  section("1. the shared card parts (web/ui_common.js)");
  ok(UI && ["cardSubtitle", "bodyScale", "drawPortrait", "activationClock", "brainColor", "drawBrain", "senseHtml", "senseIdle"].every((k) => typeof UI[k] === "function") &&
     Array.isArray(UI.CARD_STATS), "EvoUI has the card's parts (and keeps the focus primitives)", Object.keys(UI));
  ok(JSON.stringify(UI.CARD_STATS) === '["energy","age","speed"]', "the common stats, in their order: energy, age, speed");
  const NB = "\u00a0";
  ok(UI.cardSubtitle({ generation: 3, family: 12, genes: 41 }) === "Generation" + NB + "3 · family" + NB + "#12 · 41" + NB + "genes" &&
     UI.cardSubtitle({ generation: 0.4, family: 7.6, genes: 1, body: [1.0249, 0.981] }) === "Generation" + NB + "0 · family" + NB + "#8 · 1" + NB + "gene · body" + NB + "1.02" + NB + "×" + NB + "0.98",
     "the subtitle: generation, family, genes, then the body (with the body model), in this order; a line breaks only between them (no-break spaces within)",
     [UI.cardSubtitle({ generation: 3, family: 12, genes: 41 }), UI.cardSubtitle({ generation: 0.4, family: 7.6, genes: 1, body: [1.0249, 0.981] })]);
  ok([0, 0.5, 0.9, 1, 1.07, 1.5, 2, NaN, -1].every((b) => UI.bodyScale(b) === (b > 0 ? 1 + 0.4 * Math.tanh(5 * (b - 1)) : 1)),
     "bodyScale: the pages' formula (renderer.js, ocean.js)");

  /* the activation clock */
  {
    const c = UI.activationClock(), st = (t, age) => c.state(t, age === undefined ? 1 : age);
    c.reset(0, true);   /* Classic: a new world, the capture on */
    const z = [st(0), st(0, 0), c.at(0)];
    ok(z[0] === "waiting" && z[1] === "waiting" && z[2] === null, "a new world at tick 0 (zero steps): waiting, nothing kept", z);
    ok(st(1) === "current" && c.at(1) === 1 && st(1, 0) === "waiting" && st(5) === "current",
       "  after a step with the capture on: current (kept at that tick); a fish of age 0 (born in that step) still waits");
    c.reset(300, true);
    ok(st(300) === "waiting" && st(301) === "current", "a load (reset at its tick): waiting until its first step");
    c.reset(0, false);   /* the Ocean: nothing picked */
    ok(st(60) === "waiting" && c.at(60) === null, "the capture off while the world stepped: waiting");
    c.capture(true, 60);   /* a fish picked, paused */
    ok(st(60) === "waiting" && c.at(60) === null, "  a fish picked at tick 60 (paused): waits for a step (the world is never stepped to fill it in)");
    ok(st(61) === "current", "  one step later: current");
    c.capture(false, 61); c.capture(true, 61);   /* let go and picked again, still paused */
    ok(st(61) === "current" && c.at(61) === 61, "  let go and picked again at the same tick: still current (the last step ran with the capture on)");
    c.capture(false, 61);
    ok(c.at(80) === 61 && st(80) === "waiting", "  let go, the world steps on: what is kept is tick 61's", [c.at(80)]);
    c.capture(true, 80);
    ok(st(80) === "waiting" && c.at(80) === 61 && st(81) === "current", "  picked again at 80: waits (61's are 19 steps old), current at 81");
    c.capture(true, 81); c.capture(true, 90);
    ok(st(90) === "current", "  capture(on) again while on: no change (a fish picked after another: every fish is captured)");
    c.capture(false, 81); c.capture(true, 81);
    ok(c.at(81) === 81, "  off and on at the tick it went on (no step between): kept stays the last captured step");
    c.reset(500, false);
    ok(c.at(500) === null && st(500) === "waiting", "a world handed back (reset): nothing kept");
  }

  /* brainColor */
  {
    const vals = [-1.5, -1, -0.62, -0.1, 0, 0.0001, 0.3, 0.999, 1, 2];
    ok(vals.every((v) => UI.brainColor(v, 1) === OLD_brainColor(v, 1) && UI.brainColor(v, 0.5) === OLD_brainColor(v, 0.5)),
       "brainColor of a value: the pages' own colour, unchanged");
    const n = UI.brainColor(NaN, 1);
    ok(n === UI.brainColor(null, 1) && n === UI.brainColor(undefined, 1) && n !== OLD_brainColor(0, 1) && /^rgba\(112,126,130,1\)$/.test(n),
       "  a value it does not vouch for (NaN, null): neutral grey, not the colour of an activation of 0", n);
  }

  /* drawBrain against both pages' own, then waiting */
  {
    const cases = [];
    for (const [w, h] of [[380, 320], [352, 300], [300, 300], [366, 96], [600, 170], [338, 150]])
      for (const hover of [-1, 0, 47, 60]) cases.push({ w, h, hover });
    let same = 0, bad = null;
    for (const [world, nS, nH, nA, gutter, old] of [["classic", 41, 12, 12, 92, OLD_classicBrain], ["ocean", 46, 12, 13, 100, OLD_oceanBrain]]) {
      for (const [ci, c] of cases.entries()) {
        const net = synthNet(1000 + ci, nS, nH, nA, 64);
        const prevG = recorder(), prev = UI.drawBrain(prevG, c.w, c.h, net, { nS, nH, nA, gutter, actShort: CL_SHORT, actLabels: CL_LONG, font: "sans-serif" });
        const a = recorder(), b = recorder();
        const nodesNew = UI.drawBrain(a, c.w, c.h, net, { nS, nH, nA, gutter, actShort: CL_SHORT, actLabels: CL_LONG, font: "sans-serif", dpr: 2, fresh: true, prev, hover: c.hover });
        const nodesOld = old({ w: c.w, h: c.h, dpr: 2, g: b, actShort: CL_SHORT, actLabels: CL_LONG, font: "sans-serif", hover: c.hover, prev, nS, nH, nA }, net);
        const la = JSON.stringify(a.__log), lb = JSON.stringify(b.__log);
        if (la === lb && JSON.stringify(nodesNew) === JSON.stringify(nodesOld)) same++;
        else if (!bad) bad = { world, c, at: [...la].findIndex((ch, i) => ch !== lb[i]), a: la.slice(0, 200), b: lb.slice(0, 200) };
      }
    }
    ok(same === cases.length * 2, "drawBrain, its activations current: call for call (and node for node) what each page drew before, " +
       same + " of " + cases.length * 2 + " boxes (wide, tall; hover none, a sense, a hidden neuron, an action; DPR 2; Classic's 41/12/12 at 92 px, the Ocean's 46/12/13 at 100 px)", bad);
    const net = synthNet(7, 41, 12, 12, 64), g = recorder();
    UI.drawBrain(g, 380, 320, net, { nS: 41, nH: 12, nA: 12, gutter: 92, actShort: CL_SHORT, actLabels: CL_LONG, font: "sans-serif", fresh: false });
    const L = g.__log, fills = [], links = [];
    for (let i = 0; i < L.length; i++) {
      if (L[i][0] === "=" && L[i][1] === "fillStyle" && L[i + 1] && L[i + 1][0] === "beginPath" && L[i + 2] && L[i + 2][0] === "arc") fills.push(L[i][2]);
      if (L[i][0] === "=" && L[i][1] === "strokeStyle" && /^rgba\((180,235,80|255,120,80),/.test(L[i][2])) links.push([L[i][2], L[i + 1][2]]);
    }
    ok(fills.length === 65 && fills.every((f) => f === UI.brainColor(NaN, 1)), "  waiting for a step: every one of the 65 nodes neutral (no activation drawn)", fills.slice(0, 3));
    ok(links.length > 30 && links.every(([s, lw]) => /,0\.100\)$/.test(s) && lw === 0.8), "  and every link the wiring alone: its sign's colour at the faintest weight (0.100, 0.8 px)", links.slice(0, 3));
  }

  /* the sense line, and the colour key */
  {
    ok(UI.senseIdle(true, true, false, "x") === OLD_SENSE && UI.senseIdle(true, false, true, "x") === OLD_SENSE.replace("Tap", "Point at"),
       "the line under a current brain: the pages' text (Tap on touch, Point at with a mouse)");
    const wp = UI.senseIdle(false, false, true, "Space runs it; . steps once"), wr = UI.senseIdle(false, false, false, "Space runs it; . steps once");
    ok(/^Waiting for a step/.test(wp) && wp.indexOf("(Space runs it; . steps once)") > 0 && wr.indexOf("Space") < 0,
       "  waiting: it says so, with how to step only while paused", [wp, wr]);
    const n = { kind: "Sense", i: 3, v: -0.25, x: 0, y: 0 };
    ok(UI.senseHtml(n, true) === "Sense: <b></b> -0.25" && UI.senseHtml(Object.assign({}, n, { v: 0.5 }), true) === "Sense: <b></b> +0.50" &&
       UI.senseHtml(n, false) === "Sense: <b></b> · waits for a step", "  a node pointed at: its value, or that it waits for a step (no value shown)");
    let same = 0;
    for (const [rgb, size, elong, dpr] of [[[90, 200, 255], 1, 1, 1], [[255, 0, 120], 1.6, 0.7, 2], [[3, 4, 5], 0.5, 1.9, 3], [[10, 10, 10], NaN, 1, 1]]) {
      const ca = { width: 0, height: 0 }, cb = { width: 0, height: 0 }, ga = recorder(), gb = recorder();
      ca.getContext = () => ga;
      UI.drawPortrait(ca, rgb, size, elong, dpr);
      OLD_portrait(cb, gb, rgb, size, elong, dpr);
      if (JSON.stringify(ga.__log) === JSON.stringify(gb.__log) && ca.width === cb.width && ca.height === cb.height) same++;
    }
    ok(same === 4, "the colour key (drawPortrait): call for call the pages' old portrait (4 bodies, DPR 1 to 3)", same);
  }

  /* ======================================================== 2. real-module data ======================================================== */
  section("2. real-module data: gene counts and the activations' freshness");
  const createClassic = require(path.join(WEB, "evo_boids.js"));
  const createOcean = require(path.join(WEB, "evo_ocean.js"));
  const HO = require(path.join(WEB, "ocean_handoff.js"));
  const OCEAN_WASM = path.join(WEB, "evo_ocean.wasm");
  const mkClassic = () => createClassic({ locateFile: (p) => path.join(WEB, p) });
  const mkOcean = () => createOcean({ locateFile: (p) => (p.endsWith(".wasm") ? OCEAN_WASM : p) });
  const buf = (M) => (M.wasmMemory ? M.wasmMemory.buffer : M.HEAPU8.buffer);
  /* Classic */
  function cInspect(M, i) {
    if (!M._evo_inspect(i)) throw new Error("evo_inspect " + i);
    const n = M._evo_inspect_conn_count();
    return { info: Array.from(new Float64Array(buf(M), M._evo_inspect_info(), 8)), sensors: Array.from(new Float32Array(buf(M), M._evo_inspect_sensors(), 41)),
             hidden: Array.from(new Float32Array(buf(M), M._evo_inspect_hidden(), 12)), actions: Array.from(new Float32Array(buf(M), M._evo_inspect_actions(), 12)), connCount: n };
  }
  const cTick = (M) => { M._evo_sync(); return new Float64Array(buf(M), M._evo_stats(), 4)[3]; };
  const same32 = (a, b) => a.length === b.length && Buffer.compare(Buffer.from(Float32Array.from(a).buffer), Buffer.from(Float32Array.from(b).buffer)) === 0;
  const zeros = (a) => a.every((v) => v === 0);
  {
    const A = await mkClassic();
    ok(A._evo_init(42, 1920, 1080, 300, 0) === 1, "Classic: seed 42, 300 fish");
    const clock = UI.activationClock();
    clock.reset(cTick(A), true);
    const n0 = A._evo_creature_count();
    let allZero = true, waiting = 0;
    for (let i = 0; i < n0; i++) { const f = cInspect(A, i); allZero = allZero && zeros(f.sensors) && zeros(f.actions); if (clock.state(0, f.info[3]) === "waiting") waiting++; }
    ok(allZero && waiting === n0, "  tick 0 (zero steps): every fish's senses and actions are zeros (none computed), and the clock says waiting for all " + n0);
    A._evo_step(300);
    /* on, a step at a time, to one with births in it (stats[4]: the last step's), so some fish are newborns */
    for (let k = 0; k < 3000; k++) { A._evo_step(1); A._evo_sync(); if (new Float64Array(buf(A), A._evo_stats(), 5)[4] > 0) break; }
    const t = cTick(A), n = A._evo_creature_count(), cp = JSON.parse(A.UTF8ToString(A._evo_checkpoint()));
    const lenOf = new Map(cp.creatures.id.map((id, k) => [id, cp.creatures.genomeLengths[k]]));
    const ids = new Float64Array(buf(A), A._evo_creature_ids(), n).slice();
    let match = 0, sum = 0, born = 0, bornZero = 0;
    const bad = [];
    for (let i = 0; i < n; i++) {
      const f = cInspect(A, i);
      sum += f.connCount;
      if (lenOf.get(ids[i]) === f.connCount) match++; else if (bad.length < 3) bad.push([ids[i], f.connCount, lenOf.get(ids[i])]);
      if (f.info[3] === 0) { born++; if (zeros(f.sensors) && zeros(f.actions) && clock.state(t, f.info[3]) === "waiting") bornZero++; }
    }
    const gLen = new Float64Array(buf(A), A._evo_stats(), 9)[8];
    ok(n > 0 && match === n && lenOf.size === n, "  tick " + t + ": every fish's gene count on its card (evo_inspect_conn_count) is its genome's length in the checkpoint (" + match + " of " + n + ")", bad);
    ok(sum / n === gLen, "  and their mean is the stats' genes per fish exactly (" + (sum / n).toFixed(4) + " = " + gLen.toFixed(4) + ")");
    ok(born > 0 && bornZero === born, "  fish of age 0 (born in the last step, " + born + "): their senses are zeros, and the clock says waiting though the capture was on");
    /* a load: a twin from A's checkpoint, both stepped once */
    const B = await mkClassic();
    const json = A.UTF8ToString(A._evo_checkpoint());
    const okB = HO.withCString(B, json, (p) => B._evo_load_checkpoint(p));
    const cb = UI.activationClock();
    const tLoaded = cTick(B);
    cb.reset(tLoaded, true);
    let loadedZero = 0, differ = 0, waitB = 0;
    for (let i = 0; i < n; i++) {
      const fa = cInspect(A, i), fb = cInspect(B, i);
      if (zeros(fb.sensors) && zeros(fb.actions)) loadedZero++;
      if (!same32(fa.sensors, fb.sensors)) differ++;
      if (cb.state(tLoaded, fb.info[3]) === "waiting") waitB++;
    }
    ok(okB === 1 && tLoaded === t && loadedZero === n && waitB === n && differ > n / 2,
       "  a loaded world (a twin from the checkpoint): no fish has activations (zeros: a checkpoint carries none), " + differ + " differ from the running world's, and all wait", [okB, cTick(B), loadedZero, waitB, differ]);
    A._evo_step(1); B._evo_step(1);
    const t1 = cTick(A), t1b = cTick(B);
    let cur = 0, equal = 0, waitNew = 0;
    for (let i = 0; i < A._evo_creature_count(); i++) {
      const fa = cInspect(A, i), fb = cInspect(B, i);
      if (cb.state(t1b, fb.info[3]) === "current") { cur++; if (same32(fa.sensors, fb.sensors) && same32(fa.actions, fb.actions) && same32(fa.hidden, fb.hidden)) equal++; }
      else if (fb.info[3] === 0) waitNew++;
    }
    ok(t1b === t1 && cur > 0 && equal === cur && cur + waitNew === A._evo_creature_count(),
       "  one step on: every fish the clock calls current has the running world's activations bit for bit (" + equal + " of " + cur + "); the rest are newborns (" + waitNew + ")");
  }
  /* the Ocean: a twin that captures every step, and the page's capture (only while a fish is picked) */
  function oInspect(M, i) {
    if (!M._oc_inspect(i)) throw new Error("oc_inspect " + i);
    const nS = M._oc_num_senses(), nH = M._oc_num_hidden(), nA = M._oc_num_actions(), nc = M._oc_inspect_conn_count(), b = HO.buffer(M);
    return { info: Array.from(new Float64Array(b, M._oc_inspect_info(), M._oc_inspect_len())), sensors: Array.from(new Float32Array(b, M._oc_inspect_sensors(), nS)),
             hidden: Array.from(new Float32Array(b, M._oc_inspect_hidden(), nH)), actions: Array.from(new Float32Array(b, M._oc_inspect_actions(), nA)), connCount: nc };
  }
  const oTick = (M) => { M._oc_sync(); return HO.f64(M, M._oc_stats(), M._oc_stats_len())[1]; };
  {
    const mk = async () => { const M = await mkOcean(); if (!HO.withCString(M, "", (p) => M._oc_init(42, 1920, 1080, 240, 160, p))) throw new Error("oc_init"); return M; };
    const R = await mk(), P = await mk();   /* R: the capture on from the start (the reference); P: as the page sets it */
    R._oc_set_capture(1); P._oc_set_capture(0);
    const clock = UI.activationClock();
    clock.reset(oTick(P), false);
    const both = (k) => { R._oc_step(k); P._oc_step(k); };
    /* what the card would show for every fish now: [current, equal to R, all zeros, age 0] */
    const scan = () => {
      const t = oTick(P), out = { n: 0, cur: 0, curEqual: 0, waitDiffer: 0, wait: 0, genes: 0 }, n = P._oc_creature_count();
      if (oTick(R) !== t || R._oc_creature_count() !== n) throw new Error("the twins diverged");
      for (let i = 0; i < n; i++) {
        const a = oInspect(R, i), b = oInspect(P, i), eq = same32(a.sensors, b.sensors) && same32(a.actions, b.actions) && same32(a.hidden, b.hidden);
        out.n++;
        if (Math.round(b.info[11]) === b.connCount) out.genes++;
        if (clock.state(t, b.info[3]) === "current") { out.cur++; if (eq) out.curEqual++; }
        else { out.wait++; if (!same32(a.sensors, b.sensors)) out.waitDiffer++; }
      }
      return out;
    };
    both(60);
    let s = scan();
    ok(s.genes === s.n, "Ocean: every fish's genes on its card (oc_inspect's genome length) is its brain's link count (" + s.genes + " of " + s.n + ")");
    ok(s.cur === 0 && s.waitDiffer === s.n, "  60 steps with nothing picked: none current, and every fish's kept senses differ from the step's (zeros)", s);
    P._oc_set_capture(1); clock.capture(true, oTick(P));   /* a fish picked, paused */
    s = scan();
    ok(s.cur === 0 && s.waitDiffer === s.n, "  a fish picked while paused (the capture on, no step): all wait, and their kept senses are not the step's", s);
    both(1);
    s = scan();
    ok(s.cur > 0 && s.curEqual === s.cur, "  one step: every fish the clock calls current has the twin's activations bit for bit (" + s.curEqual + " of " + s.cur + ")", s);
    P._oc_set_capture(0); clock.capture(false, oTick(P)); P._oc_set_capture(1); clock.capture(true, oTick(P));
    s = scan();
    ok(s.cur > 0 && s.curEqual === s.cur, "  let go and picked again at the same tick: still current, and still the twin's", s);
    P._oc_set_capture(0); clock.capture(false, oTick(P));
    both(25);
    P._oc_set_capture(1); clock.capture(true, oTick(P));
    s = scan();
    ok(s.cur === 0 && s.waitDiffer > s.n * 0.9, "  let go, 25 steps, picked again: all wait, and " + s.waitDiffer + " of " + s.n + " kept senses are an older step's", s);
    both(1);
    s = scan();
    ok(s.cur > 0 && s.curEqual === s.cur, "  one more step: current again, the twin's bit for bit (" + s.curEqual + " of " + s.cur + ")", s);
    /* on, a step at a time, to a step with a birth: the newborn waits (its brain has not run), every other fish is current */
    const newborns = () => { const out = []; for (let i = 0; i < P._oc_creature_count(); i++) if (oInspect(P, i).info[3] === 0) out.push(i); return out; };
    let nb = [];
    for (let k = 0; k < 2000 && !nb.length; k++) { both(1); oTick(P); oTick(R); nb = newborns(); }
    s = scan();
    const nbZero = nb.filter((i) => { const f = oInspect(P, i); return zeros(f.sensors) && zeros(f.actions); }).length;
    ok(nb.length > 0 && s.wait === nb.length && nbZero === nb.length && s.cur === s.n - nb.length && s.curEqual === s.cur,
       "  a step with births (tick " + oTick(P) + "): its " + nb.length + " newborn(s) wait (senses zeros: their brains have not run), the other " + s.cur + " are current and the twin's", s);
  }

  /* ======================================================== 3. the pages ======================================================== */
  section("3a. Classic's page (web/renderer.js with its module): the card in every view");
  await classicPage(mkClassic, buf);
  section("3b. the Ocean's page (web/ocean.js with its module): pause, select, step; hiding the card");
  await oceanPage(mkOcean, HO);

  /* ======================================================== 4. markup and styles ======================================================== */
  section("4. the markup and styles: one card");
  markup();

  console.log((fails ? "FAILED " + fails + " of " : "all ") + checks + " checks" + (fails ? "" : " passed"));
  process.exit(fails ? 1 : 0);
}

/* ---------------- a small DOM for a whole page: ids made on first use with the page's tag and type, children made on use,
 * bubbling events to the document and the window, selectors (compound, descendant, lists), boxes only where a test gives one ---------------- */
function pageIds(html) {
  const m = new Map();
  for (const x of html.matchAll(/<([a-zA-Z][\w-]*)\b([^>]*)>/g)) {
    const id = /\sid="([^"]+)"/.exec(x[2]);
    if (!id || m.has(id[1])) continue;
    const type = /\stype="([^"]+)"/.exec(x[2]), cls = /\sclass="([^"]+)"/.exec(x[2]);
    m.set(id[1], { tag: x[1], type: type ? type[1] : "", cls: cls ? cls[1] : "", hidden: /\shidden(\s|>|$)/.test(x[2] + ">") });
  }
  return m;
}
function makeDom(ids, canvasCtx) {
  const byId = new Map(), errors = [];
  const parse = (s) => {
    const m = /^([a-zA-Z][\w-]*)?((?:[#.][\w-]+|\[[\w-]+(?:="[^"]*")?\]|:[\w-]+)*)$/.exec(s);
    if (!m) return null;
    const parts = m[2].match(/[#.][\w-]+|\[[^\]]+\]|:[\w-]+/g) || [];
    return { tag: (m[1] || "").toUpperCase(), id: (parts.find((x) => x[0] === "#") || "#").slice(1), cls: parts.filter((x) => x[0] === ".").map((x) => x.slice(1)),
             attrs: parts.filter((x) => x[0] === "[").map((x) => { const a = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(x); return [a[1], a[2]]; }), pseudo: parts.filter((x) => x[0] === ":") };
  };
  const attrOf = (e, k) => (k.startsWith("data-") ? (e.dataset[k.slice(5).replace(/-(\w)/g, (x, c) => c.toUpperCase())] ?? null) : e.getAttribute(k));
  const one = (e, p) => !!p && !p.pseudo.length && (!p.tag || e.tagName === p.tag) && (!p.id || e._id === p.id) && p.cls.every((c) => e._cls.has(c)) &&
                        p.attrs.every(([k, v]) => { const a = attrOf(e, k); return v === undefined ? a !== null : a === v; });
  const matches = (e, sel) => sel.split(",").some((alt) => {
    const chain = alt.trim().split(/\s+/).map(parse);
    if (chain.some((p) => !p) || !one(e, chain[chain.length - 1])) return false;
    let k = chain.length - 2;
    for (let n = e.parentNode; n && k >= 0; n = n.parentNode) if (one(n, chain[k])) k--;
    return k < 0;
  });
  function* walk(e) { for (const c of e.children) { yield c; yield* walk(c); } }
  function fireOn(n, ev, type) {
    ev.currentTarget = n;
    for (const f of (n._ls[type || ev.type] || []).slice()) { try { f.call(n, ev); } catch (e) { errors.push(String(e && e.stack || e)); } }
  }
  class Ev {
    constructor(type, o) { Object.assign(this, { type, bubbles: !!(o && o.bubbles), defaultPrevented: false, target: null, stopped: false }, o || {}); }
    preventDefault() { this.defaultPrevented = true; }
    stopPropagation() { this.stopped = true; }
  }
  const noCtx = new Proxy({}, { get: (t, k) => (k in t ? t[k] : k === "measureText" ? () => ({ width: 0 }) : typeof k === "symbol" ? undefined : () => {}), set: (t, k, v) => { t[k] = v; return true; } });
  let head = null, onScript = null;
  class El {
    constructor(tag) {
      this.tagName = this.nodeName = String(tag).toUpperCase(); this.children = []; this.parentNode = null; this.dataset = {}; this.attrs = {};
      this.style = { setProperty(k, v) { this[k] = String(v); }, removeProperty(k) { delete this[k]; } };
      this._cls = new Set(); this._ls = {}; this._id = ""; this._text = ""; this._html = ""; this._auto = false;
      this.hidden = false; this.disabled = false; this.checked = false; this.value = ""; this.type = ""; this.title = "";
      this.width = 0; this.height = 0; this.tabIndex = this.tagName === "BUTTON" ? 0 : -1; this.scrollTop = 0; this.clientWidth = 0; this.clientHeight = 0;
      this.offsetWidth = 0; this.offsetHeight = 0; this.isContentEditable = false; this.options = [];
    }
    get id() { return this._id; } set id(v) { this._id = String(v); byId.set(this._id, this); }
    get className() { return Array.from(this._cls).join(" "); } set className(v) { this._cls = new Set(String(v).split(/\s+/).filter(Boolean)); }
    get classList() { const s = this._cls; return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)),
      toggle: (c, on) => { if (on === undefined) on = !s.has(c); if (on) s.add(c); else s.delete(c); return !!on; }, contains: (c) => s.has(c) }; }
    get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
    set textContent(v) { for (const c of this.children) c.parentNode = null; this.children = []; this._text = String(v); this._html = ""; }
    get innerHTML() { return this._html; }
    set innerHTML(v) {
      v = String(v); for (const c of this.children) c.parentNode = null; this.children = []; this._html = v; this._text = v.replace(/<[^>]*>/g, "");
      for (const m of v.matchAll(/<([a-zA-Z][\w-]*)([^>]*)>/g)) { const c = new El(m[1]), cl = /\sclass=(['"])(.*?)\1/.exec(m[2]), id = /\sid=(['"])(.*?)\1/.exec(m[2]); if (cl) c.className = cl[2]; if (id) c.id = id[2]; c._text = ""; this.appendChild(c); }
      if (this.children.length) this._text = "";
    }
    get firstChild() { return this.firstElementChild; }
    get firstElementChild() { if (!this.children.length && this._auto) this.appendChild(new El("i")); return this.children[0] || null; }
    get lastChild() { return this.children[this.children.length - 1] || null; }
    get parentElement() { return this.parentNode; }
    get nextElementSibling() { const p = this.parentNode; return p ? p.children[p.children.indexOf(this) + 1] || null : null; }
    appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.children.push(c); if (this === head && c.tagName === "SCRIPT" && onScript) onScript(c); return c; }
    append(...cs) { for (const c of cs) if (typeof c === "object") this.appendChild(c); else this._text += String(c); }
    insertBefore(c, ref) { if (!ref) return this.appendChild(c); if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.children.splice(Math.max(0, this.children.indexOf(ref)), 0, c); return c; }
    removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); c.parentNode = null; return c; }
    remove() { if (this.parentNode) this.parentNode.removeChild(this); }
    setAttribute(k, v) { this.attrs[k] = String(v); if (k === "id") this.id = v; else if (k === "class") this.className = v; }
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
    hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k); }
    removeAttribute(k) { delete this.attrs[k]; }
    insertAdjacentHTML() {}
    addEventListener(t, f) { (this._ls[t] = this._ls[t] || []).push(f); }
    removeEventListener(t, f) { const l = this._ls[t] || [], i = l.indexOf(f); if (i >= 0) l.splice(i, 1); }
    dispatchEvent(ev) {
      if (!ev.target) ev.target = this;
      for (let n = this; n; n = ev.bubbles && !ev.stopped ? n.parentNode : null) fireOn(n, ev);
      if (ev.bubbles && !ev.stopped) { fireOn(doc, ev); fireOn(win, ev); }
      return !ev.defaultPrevented;
    }
    click() { if (this.disabled) return; this.dispatchEvent(new Ev("click", { bubbles: true, detail: 1 })); }
    focus() { doc.activeElement = this; }
    blur() { if (doc.activeElement === this) doc.activeElement = null; }
    getBoundingClientRect() {
      const r = this._rect;
      return r ? { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.right - r.left, height: r.bottom - r.top, x: r.left, y: r.top }
               : { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0 };
    }
    getContext() { return (canvasCtx && canvasCtx(this)) || noCtx; }
    setPointerCapture() {} releasePointerCapture() {} scrollIntoView() {}
    querySelectorAll(sel) { const out = []; for (const e of walk(this)) if (matches(e, sel)) out.push(e); return out; }
    querySelector(sel) {
      for (const e of walk(this)) if (matches(e, sel)) return e;
      if (!this._auto) return null;
      const p = parse(sel.split(",")[0].trim().split(/\s+/).pop());
      if (!p) return null;
      const c = new El(p.tag || "div"); if (p.cls.length) c.className = p.cls.join(" "); if (p.id) c.id = p.id; c._auto = true;
      return this.appendChild(c);
    }
    closest(sel) { for (let n = this; n && n.matches; n = n.parentNode) if (n.matches(sel)) return n; return null; }
    matches(sel) { return sel === ":focus-visible" ? doc.activeElement === this && doc.modality === "keyboard" : matches(this, sel); }
    contains(n) { for (; n; n = n.parentNode) if (n === this) return true; return false; }
    get isConnected() { return docEl.contains(this); }
  }
  const docEl = new El("html"), body = new El("body");
  head = new El("head"); docEl.appendChild(head); docEl.appendChild(body);
  docEl.clientWidth = 1440; docEl.clientHeight = 900;
  const win = { _ls: {} };
  const doc = {
    documentElement: docEl, head, body, activeElement: null, modality: "pointer", hidden: false, _ls: {}, fonts: { ready: Promise.resolve() },
    createElement: (t) => new El(t), createTextNode: (t) => { const e = new El("#text"); e._text = String(t); return e; },
    getElementById(id) {
      let e = byId.get(id);
      if (e && !e.isConnected) e = null;
      if (!e && ids.has(id)) {
        const d = ids.get(id);
        e = new El(d.tag); e._auto = true; e.id = id;
        if (d.type) e.type = d.type;
        if (d.cls) e.className = d.cls;
        e.hidden = d.hidden;
        body.appendChild(e);
      }
      return e || null;
    },
    querySelector: (s) => docEl.querySelector(s), querySelectorAll: (s) => docEl.querySelectorAll(s),
    addEventListener(t, f) { (this._ls[t] = this._ls[t] || []).push(f); }, removeEventListener() {},
    dispatchEvent(ev) { fireOn(doc, ev); return true; }
  };
  return { doc, win, Ev, El, errors, fireOn, setOnScript: (f) => { onScript = f; } };
}
/* the window of a page: its media queries (opts.media: the ones that match), timers that wait (the test runs none), a frame when the test asks */
function makeWindow(D, href, opts) {
  const ls = new Map(), mqs = new Map(), page = { raf: null, timers: [], logs: [] };
  const matchMedia = (q) => {
    if (!mqs.has(q)) mqs.set(q, { media: q, matches: !!(opts.media && opts.media.some((m) => q.indexOf(m) >= 0)), _ls: [],
                                  addEventListener(t, f) { if (t === "change") this._ls.push(f); }, removeEventListener() {}, addListener(f) { this._ls.push(f); }, removeListener() {} });
    return mqs.get(q);
  };
  const say = (level) => (...a) => page.logs.push([level, a.map(String).join(" ")]);
  const u = new URL(href), clock = { t: 1000 };
  const ctx = {
    console: { log: say("log"), info: say("info"), warn: say("warn"), error: say("error"), debug: say("debug") },
    document: D.doc, location: { href: u.href, search: u.search, origin: u.origin, protocol: u.protocol, pathname: u.pathname, hash: "" },
    navigator: { userAgent: "node", hardwareConcurrency: 4, maxTouchPoints: 0 }, history: { replaceState() {} },
    localStorage: { getItem: (k) => (ls.has(k) ? ls.get(k) : null), setItem: (k, v) => ls.set(k, String(v)), removeItem: (k) => ls.delete(k) },
    matchMedia, getComputedStyle: () => ({ fontFamily: "sans-serif", getPropertyValue: () => "" }),
    requestAnimationFrame: (cb) => { page.raf = cb; return 1; }, cancelAnimationFrame() {},
    setTimeout: (f, ms) => { page.timers.push({ f, ms }); return page.timers.length; }, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
    performance: { now: () => clock.t }, innerWidth: opts.width || 1440, innerHeight: opts.height || 900, devicePixelRatio: 1,
    Event: D.Ev, CustomEvent: D.Ev, URL, URLSearchParams, Blob, TextEncoder, TextDecoder, WebAssembly, crypto: globalThis.crypto,
    ImageData: class { constructor(d, w, h) { this.data = d; this.width = w; this.height = h; } }, Image: function () { this.complete = false; this.naturalWidth = 0; },
    crossOriginIsolated: false, Promise, Math, JSON, Object, Array, Number, String, Boolean, Date, RegExp, Error, TypeError, RangeError, Map, Set, WeakMap, Proxy, Symbol, Reflect,
    Float64Array, Float32Array, Int32Array, Uint8Array, Uint8ClampedArray, Uint16Array, Uint32Array, Int8Array, Int16Array, ArrayBuffer, DataView, BigInt,
    isFinite, isNaN, parseInt, parseFloat, Infinity, NaN, encodeURIComponent, decodeURIComponent, structuredClone
  };
  ctx.addEventListener = (t, f) => { (D.win._ls[t] = D.win._ls[t] || []).push(f); };
  ctx.removeEventListener = () => {};
  ctx.dispatchEvent = (ev) => { D.fireOn(D.win, ev); return true; };
  ctx.window = ctx.self = ctx.globalThis = ctx;
  page.ctx = ctx; page.clock = clock;
  /* one frame of the page's own loop at the next 1/60 s */
  page.frame = () => { const cb = page.raf; page.raf = null; clock.t += 1000 / 60; if (cb) cb(clock.t); };
  /* a key where the focus is, as a browser dispatches it (capture listeners are not used by these pages' card keys) */
  page.key = (k) => {
    D.doc.modality = "keyboard";
    const t = D.doc.activeElement || D.doc.body, ev = new D.Ev("keydown", { key: k, code: k === " " ? "Space" : /^[a-z]$/i.test(k) ? "Key" + k.toUpperCase() : k === "." ? "Period" : k,
                                                                          bubbles: true, altKey: false, ctrlKey: false, metaKey: false, shiftKey: false, repeat: false });
    t.dispatchEvent(ev);
    return ev;
  };
  return page;
}
const run = (ctx, name, src) => vm.runInContext(src !== undefined ? src : read(name), ctx, { filename: name });
const until = async (pred, what, ms) => { const t0 = Date.now(); while (!pred()) { if (Date.now() - t0 > (ms || 60000)) throw new Error("timed out: " + what); await new Promise((r) => setTimeout(r, 5)); } };

/* ---------------- Classic ---------------- */
async function classicPage(mkClassic, buf) {
  const ids = pageIds(read("index.html"));
  /* the world canvas records what it draws; the brain's records too */
  const ctxs = new Map();
  const D = makeDom(ids, (c) => { if (c.id === "canvas" || c.id === "inetc") { if (!ctxs.has(c.id)) ctxs.set(c.id, recorder()); return ctxs.get(c.id); } return null; });
  const P = makeWindow(D, "http://classic.test/web/index.html?threads=0&view=flat&guide=0&intro=0", { media: ["min-width: 960px"] });
  let M = null;
  /* a stand-in for the tank (web/scene3d.js), which says what it was asked: follow state, as scene3d's (it calls onFollowChange) */
  const tank = { following: false, follows: [] };
  P.ctx.EvoScene = { load: () => Promise.resolve(), create: (canvas, o) => new Proxy({}, { get: (t, k) => {
    if (k === "then" || typeof k === "symbol") return undefined;   /* (not a thenable: loadScene resolves with it) */
    if (k === "following") return () => tank.following;
    if (k === "setFollow") return (on) => { on = !!on; tank.follows.push(on); if (on === tank.following) return; tank.following = on; o.onFollowChange(on); };
    if (k === "project") return () => null;
    if (k === "pick") return () => -1;
    if (k === "quality") return () => 3;
    if (k === "setQuality" || k === "degrade") return () => false;
    return () => {};
  } }) };
  P.ctx.EVO_ASSETS = { st: "evo_boids.js", stWasm: "evo_boids.wasm", mt: "evo_boids_mt.js", mtWasm: "evo_boids_mt.wasm", worker: "worker.js", background: "rocks.jpg", three: "three.js" };
  P.ctx.EvoLoader = { load: () => mkClassic().then((m) => { M = m; return { Module: m, threaded: false, why: "the test", js: "evo_boids.js", wasm: "evo_boids.wasm" }; }), poolThreads: () => 1 };
  vm.createContext(P.ctx);
  run(P.ctx, "ui_common.js");
  run(P.ctx, "renderer.js");
  await until(() => P.ctx.EvoApp && P.ctx.EvoApp.ready, "Classic's page to start");
  const el = (id) => D.doc.getElementById(id), card = el("fishcard");
  const inet = D.doc.createElement("div"); inet.className = "inet"; inet.clientWidth = 380; inet.clientHeight = 320;
  D.doc.body.appendChild(inet); inet.appendChild(el("inetc"));   /* (the brain's box: a size, so the card draws it) */
  el("seed").value = "42"; el("population").value = "300";
  el("restart").click();
  const tick = () => { M._evo_sync(); return new Float64Array(buf(M), M._evo_stats(), 4)[3]; };
  const world = ctxs.get("canvas");
  el("pausebtn").click();
  for (let i = 0; i < 3; i++) P.frame();
  const t0 = tick();
  ok(t0 === 0 && el("pausebtn").getAttribute("aria-label") === "play", "seed 42, 300 fish, paused at tick 0 (the flat view, a wide screen with a mouse: not compact)", [t0]);
  P.ctx.EvoApp.inspectSomeFish();
  world.__log.length = 0;
  for (let i = 0; i < 3; i++) P.frame();
  ok(tick() === 0 && !card.hidden && card.dataset.activations === "waiting" && card.dataset.activationsAt === "",
     "a fish selected at tick 0 (zero steps), paused: the card shows (the flat view on a wide screen: U19), its brain waiting; three frames, no step",
     [tick(), card.hidden, card.dataset.activations]);
  ok(/^Waiting for a step/.test(el("isense").textContent) && /Space runs it/.test(el("isense").textContent), "  its line says it waits for a step, and how to take one", el("isense").textContent);
  const texts = world.__log.filter((c) => c[0] === "fillText"), rings = world.__log.filter((c) => c[0] === "arc" && c[3] === 16);
  ok(texts.length === 0 && rings.length === 3, "  the world canvas draws no HUD and no inspector panel (no text at all), and the selection ring each frame", [texts.slice(0, 2), rings.length]);
  ok(P.ctx.EvoApp.compact() === true && P.ctx.EvoApp.inspectorRect() !== null, "  the tour's hooks: the selected fish is the card (compact), its rect the card's");
  el("pausebtn").click(); P.frame(); el("pausebtn").click(); P.frame();
  const t1 = tick(), idOf = () => +el("ititle").textContent.replace(/^Fish #/, "");
  const idx = (() => { const n = M._evo_creature_count(), a = new Float64Array(buf(M), M._evo_creature_ids(), n); return Array.from(a).indexOf(idOf()); })();
  M._evo_inspect(idx);
  const conn = M._evo_inspect_conn_count(), info = new Float64Array(buf(M), M._evo_inspect_info(), 8);
  ok(t1 === 1 && card.dataset.activations === "current" && card.dataset.activationsAt === "1",
     "one frame running (one step), paused again: the brain is current, kept at tick 1", [t1, card.dataset.activations, card.dataset.activationsAt]);
  ok(el("isub").textContent === "Generation\u00a0" + Math.round(info[6]) + " · family\u00a0#" + Math.round(info[7]) + " · " + conn + "\u00a0genes",
     "  the subtitle, the common fields in their order, with its genes (evo_inspect_conn_count: " + conn + ")", el("isub").textContent);
  ok(/^Senses on one side/.test(el("isense").textContent), "  its line: how to read a current brain");
  const fills = ctxs.get("inetc").__log.filter((c, i, L) => c[0] === "=" && c[1] === "fillStyle" && L[i + 1] && L[i + 1][0] === "beginPath" && L[i + 2] && L[i + 2][0] === "arc");
  ok(fills.length >= 65 && fills.slice(-65).some((f) => f[2] !== UI.brainColor(NaN, 1)), "  and its brain drawn with its activations (not neutral)");
  /* folding the brain (the card's own hide): the fish stays */
  const id1 = idOf();
  el("iexpand").click(); P.frame();
  ok(!card.hidden && !card.classList.contains("expanded") && idOf() === id1, "the brain folded: the card stays, the fish selected (" + id1 + ")");
  el("iexpand").click(); P.frame();
  ok(card.classList.contains("expanded") && idOf() === id1, "  and unfolded");
  /* a load: the world's own checkpoint */
  const json = M.UTF8ToString(M._evo_checkpoint());
  el("cpfile").files = [{ text: () => Promise.resolve(json) }];
  el("cpfile").dispatchEvent(new D.Ev("change", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 20));
  P.ctx.EvoApp.inspectSomeFish(); P.frame(); P.frame();
  ok(tick() === 1 && !card.hidden && card.dataset.activations === "waiting", "a loaded world (its checkpoint), a fish selected, paused: waiting (a checkpoint carries no activations)",
     [tick(), card.dataset.activations]);
  el("pausebtn").click(); P.frame(); el("pausebtn").click(); P.frame();
  ok(tick() === 2 && card.dataset.activations === "current", "  one step: current", [tick(), card.dataset.activations]);
  el("iclose").click(); P.frame();
  ok(card.hidden, "Close: the fish let go, the card gone");
  /* the tank (a stand-in scene): follow, then fold the brain, then let go */
  el("view3d").checked = true; el("view3d").dispatchEvent(new D.Ev("change", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 20));
  P.frame();
  P.ctx.EvoApp.inspectSomeFish(); P.frame();
  const tankCard = !card.hidden && D.doc.body.classList.contains("view-3d");
  P.key("f"); P.frame();
  const followed = tank.following;
  el("iexpand").click(); P.frame(); P.frame();
  ok(tankCard && followed && tank.following && !card.hidden && card.dataset.activations === "current",
     "the tank: the card shows; F follows; folding the brain neither lets the fish go nor stops the follow", [tankCard, followed, tank.following, card.dataset.activations]);
  P.key("Escape"); P.frame();
  ok(!tank.following && card.hidden && tank.follows[tank.follows.length - 1] === false, "  Esc lets the fish go: its card goes and the follow stops with it");
  ok(D.errors.length === 0 && P.logs.filter((l) => l[0] === "error").length === 0, "no handler threw, nothing logged as an error", D.errors.slice(0, 2).concat(P.logs.filter((l) => l[0] === "error").slice(0, 2)));
}

/* ---------------- the Ocean ---------------- */
async function oceanPage(mkOcean, HO) {
  const ids = pageIds(read("ocean.html"));
  const D = makeDom(ids, null);
  const P = makeWindow(D, "http://ocean.test/web/ocean.html?seed=42&pop=160&guide=0&intro=0", { media: ["min-width: 960px"] });
  const WASM = path.join(WEB, "evo_ocean.wasm"), bytes = fs.readFileSync(WASM);
  const captures = [];
  P.ctx.EVO_ASSETS = { ocean: "evo_ocean.js", oceanWasm: "evo_ocean.wasm", worker: "ocean_worker.js", handoff: "ocean_handoff.js", mock: "ocean_mock.js" };
  P.ctx.fetch = (u) => (/evo_ocean\.wasm$/.test(String(u)) ? Promise.resolve({ ok: true, status: 200, arrayBuffer: () => Promise.resolve(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.length)) })
                                                         : Promise.resolve({ ok: false, status: 404 }));
  P.ctx.Worker = function () { throw new Error("no worker in this test"); };
  /* the module script: the real module (the wasm on disk, whatever URL the page pinned), its capture switch logged */
  D.setOnScript((s) => setImmediate(() => {
    if (!/evo_ocean\.js$/.test(s.src)) { if (s.onerror) s.onerror(); return; }
    P.ctx.createEvoOcean = () => mkOcean().then((M) => {
      const set = M._oc_set_capture;
      M._oc_set_capture = function (on) { captures.push(on); return set.call(this, on); };
      return M;
    });
    if (s.onload) s.onload();
  }));
  /* the scene: fixed answers, follow with state (it tells the page, as ocean_scene.js does) */
  const tank = { following: false };
  P.ctx.EvoOceanScene = { load: () => Promise.resolve(), create: (canvas, o) => new Proxy({}, { get: (t, k) => {
    if (k === "then" || typeof k === "symbol") return undefined;
    if (k === "following") return () => tank.following;
    if (k === "setFollow") return (on) => { on = !!on; if (on === tank.following) return; tank.following = on; o.onFollowChange(on); };
    if (k === "quality") return () => 3;
    if (k === "pick") return () => -1;
    if (k === "project" || k === "view") return () => null;
    if (k === "appearance") return () => ({ want: false, skin: false, shapes: true, drawing: false });
    if (k === "setQuality" || k === "degrade" || k === "flashlight") return () => false;
    if (k === "flashlightLevel") return () => 0;
    return () => {};
  } }) };
  vm.createContext(P.ctx);
  for (const f of ["ui_common.js", "ocean_handoff.js", "ocean_appearance.js", "ocean_config.js", "ocean.js"]) run(P.ctx, f);
  await until(() => (P.ctx.EvoApp && P.ctx.EvoApp.ready) || /error/.test(D.doc.getElementById("splashstate").className), "the Ocean's page to start");
  const el = (id) => D.doc.getElementById(id), card = el("fishcard"), O = P.ctx.EvoOcean;
  const inet = D.doc.createElement("div"); inet.className = "inet"; inet.clientWidth = 380; inet.clientHeight = 340;
  D.doc.body.appendChild(inet); inet.appendChild(el("inetc"));   /* (the brain's box: a size, so the card draws it) */
  ok(!!O && P.ctx.EvoApp.ready, "the Ocean's page started (seed 42, 160 fish)", el("splashstate").textContent);
  if (!O) return;
  const st = () => O.state();
  el("pausebtn").click();
  for (let i = 0; i < 4; i++) P.frame();
  const tA = st().frame;
  /* run 40 frames (40 steps, the capture off), paused */
  el("pausebtn").click(); for (let i = 0; i < 40; i++) P.frame(); el("pausebtn").click(); P.frame();
  const tB = st().frame;
  O.select(0);
  P.frame(); P.frame(); P.frame();
  ok(tB === tA + 40 && st().frame === tB && st().selectedId !== null && !card.hidden && card.dataset.activations === "waiting" && captures[captures.length - 1] === 1,
     "40 steps with nothing picked, paused, a fish picked: its card waits for a step, the capture switched on, and three frames take no step (tick " + tB + ")",
     [tA, tB, st().frame, card.dataset.activations, captures]);
  ok(/^Waiting for a step/.test(el("isense").textContent) && /\. steps once/.test(el("isense").textContent), "  its line says so, and that . steps once", el("isense").textContent);
  const M = O.module, idx = st().selIdx;
  M._oc_inspect(idx);
  const info = new Float64Array(HO.buffer(M), M._oc_inspect_info(), M._oc_inspect_len()), conn = M._oc_inspect_conn_count();
  ok(el("isub").textContent.indexOf(" · " + Math.round(info[11]) + "\u00a0genes") > 0 && Math.round(info[11]) === conn && /^Generation\u00a0\d+ · family\u00a0#\d+ · \d+\u00a0genes/.test(el("isub").textContent),
     "  its subtitle: the common fields in their order, its genes the genome's length (" + Math.round(info[11]) + ", its links " + conn + ")", el("isub").textContent);
  ok(/colour key/.test(el("ikey").title) || /A colour key, not a likeness/.test(el("ikey").title), "  the colour key's title says what its colour is", el("ikey").title);
  P.key("."); P.frame(); P.frame();
  ok(st().frame === tB + 1 && st().paused && card.dataset.activations === "current" && card.dataset.activationsAt === String(tB + 1),
     ". : exactly one step, still paused, and the brain is current (kept at " + (tB + 1) + ")", [st().frame, st().paused, card.dataset.activations, card.dataset.activationsAt]);
  /* hiding the card without letting the fish go: the live numbers opened over it (where they overlap) */
  const box = (l, t, r, b) => ({ left: l, top: t, right: r, bottom: b });
  el("statpanel")._rect = box(10, 64, 350, 654); card._rect = box(10, 64, 380, 520);
  const id0 = st().selectedId, nCap = captures.length;
  el("readout").click(); P.frame(); P.frame();
  ok(card.hidden && !el("statpanel").hidden && st().selectedId === id0 && captures.length === nCap,
     "the live numbers opened over the card: the card hides, its fish still selected, the capture left on", [card.hidden, st().selectedId, captures.slice(nCap)]);
  el("pausebtn").click(); P.frame(); P.frame(); el("pausebtn").click(); P.frame();
  el("readout").click(); P.frame();
  ok(!card.hidden && st().selectedId === id0 && card.dataset.activations === "current",
     "  two steps under the numbers, then closed: the card is back, the same fish, its brain current (it never stopped capturing)", [card.hidden, card.dataset.activations]);
  /* let go, steps, picked again */
  el("iclose").click(); P.frame();
  const off = captures[captures.length - 1];
  el("pausebtn").click(); for (let i = 0; i < 10; i++) P.frame(); el("pausebtn").click(); P.frame();
  O.select(0); P.frame();
  ok(off === 0 && card.dataset.activations === "waiting", "Close (the capture off), 10 steps, a fish picked while paused: waiting again (what it kept is 10 steps old)",
     [off, card.dataset.activations, card.dataset.activationsAt]);
  /* a new world: zero steps */
  el("restart").click();
  if (!el("startask").hidden) el("startconfirm").click();   /* (the page asks before it replaces a run with progress) */
  await new Promise((r) => setTimeout(r, 30));
  if (!st().paused) el("pausebtn").click();   /* (before any frame: still tick 0) */
  P.frame();
  const t0 = st().frame;
  O.select(0); P.frame(); P.frame();
  ok(t0 === 0 && card.dataset.activations === "waiting", "a new world (Start), a fish picked at tick 0 (zero steps): waiting", [t0, card.dataset.activations]);
  P.key("."); P.frame();
  ok(st().frame === 1 && card.dataset.activations === "current", "  . : current at tick 1", [st().frame, card.dataset.activations]);
  ok(D.errors.length === 0 && P.logs.filter((l) => l[0] === "error").length === 0, "no handler threw, nothing logged as an error",
     D.errors.slice(0, 2).concat(P.logs.filter((l) => l[0] === "error").slice(0, 2)));
}

/* ---------------- the markup and the styles ---------------- */
function markup() {
  const pages = { classic: read("index.html"), ocean: read("ocean.html") }, css = read("ui_common.css");
  const cardOf = (html) => html.slice(html.indexOf('<section id="fishcard"'), html.indexOf("</section>", html.indexOf('<section id="fishcard"')));
  for (const [w, html] of Object.entries(pages)) {
    const c = cardOf(html), stats = [...c.matchAll(/<div class="stat"( data-ext="(\w+)")?><div class="k"[^>]*>[^<]*<\/div><div class="v" id="i(\w+)v">/g)].map((m) => [m[3], m[2] || ""]);
    const common = stats.filter((s) => !s[1]).map((s) => s[0]), ext = stats.filter((s) => s[1]);
    ok(JSON.stringify(common) === JSON.stringify(UI.CARD_STATS) && stats.slice(0, 3).every((s) => !s[1]),
       w + ": the card's common stats first, in the shared order (" + common.join(", ") + ")", stats);
    ok(w === "ocean" ? ext.length === 3 && ext.every((s) => s[1] === "ocean") && /id="iskin"[^>]*data-ext="ocean"/.test(c) : ext.length === 0,
       w + (w === "ocean" ? ": its own fields after them, marked data-ext (depth, neutral depth, pitch; its skin)" : ": no world fields of its own"), ext);
    ok(/<figure id="ikey" class="fc-key"[^>]*>\s*<canvas id="iportrait"[^>]*><\/canvas><figcaption>colour key<\/figcaption>/.test(c), w + ": the portrait captioned as a colour key");
    ok(c.indexOf('id="ititle"') > 0 && c.indexOf('id="isub"') > c.indexOf('id="ititle"') && c.indexOf('id="iexpand"') > 0 && c.indexOf('id="iclose"') > 0 && c.indexOf('id="inetc"') > 0,
       w + ": the head (name, subtitle, brain and close buttons) and the brain");
    ok(html.indexOf("@media (max-height: 560px) {\n    #fishcard") < 0 && !/input\.switch \{ width: 64px; height: 44px/.test(html),
       w + ": no short-screen card rules or switch target of its own (ui_common.css has both pages')");
  }
  ok(/<span class="fc-cap">skin, unlit<\/span>\s*<canvas id="iswatch"/.test(cardOf(pages.ocean)), "ocean: its skin swatch captioned, unlit, under the colour key's column");
  const media = (q) => { const i = css.indexOf("@media " + q + " {"); if (i < 0) return ""; let d = 0; for (let j = css.indexOf("{", i); j < css.length; j++) { if (css[j] === "{") d++; else if (css[j] === "}" && --d === 0) return css.slice(i, j); } return ""; };
  const short = media("(max-height: 560px)"), coarse = media("(pointer: coarse)"), fine = media("(max-height: 560px) and (pointer: fine)"), phone = media("(max-width: 479px)");
  ok(/\.fc-stats \.bar \{ display: none; \}/.test(short) && /#fishcard \{ max-height:/.test(short) && /#isub \{[^}]*text-overflow: ellipsis/.test(short),
     "ui_common.css: a short window's card keeps its numbers and buttons, its bars give way (U55)");
  ok(/input\.switch \{ width: 64px; height: 44px; margin: -8px; border: 8px solid transparent;/.test(coarse) && /#fishcard a \{[^}]*min-height: 44px/.test(coarse),
     "  on touch: a switch's 64 x 44 target (its 48 x 28 track) and the card's link 44 px high (U56)");
  ok(/\.fc-head \.icon-btn \{ width: 36px; height: 36px; \}/.test(fine) && !/icon-btn/.test(coarse.replace(/#fishcard a/, "")),
     "  the card's buttons smaller only for a mouse in a short window; on touch they stay 44 px");
  ok(/\.fc-title \{ order: 1; flex: 1 0 100%;/.test(phone) && /\.fc-head \{ flex-wrap: wrap;/.test(phone), "  a phone: the name and its line on their own row under the colour key and the buttons");
  ok(css.indexOf(".fc-key figcaption") >= 0 && css.indexOf(".fc-skin .fc-cap") >= 0, "  the colour key's and the skin's captions");
}

main().catch((e) => { console.log("  FAIL the run threw: " + (e && e.stack || e)); process.exit(1); });

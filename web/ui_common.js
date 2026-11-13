// @ts-check
"use strict";
/* Finfolk: the focus and keyboard primitives both pages share (window.EvoUI).
 *
 * Classic (web/index.html: renderer.js, dashboard.js) and the Ocean (web/ocean.html: ocean.js,
 * ocean_dash.js) load this before their own scripts. These are the rules the Ocean page grew for its
 * keyboard users, moved here so that both worlds keep one contract (docs/ui_parity.md; the UI parity
 * plan's U37 and the reusable part of U58):
 *
 *   keyboardFocused(n)      n has the focus and its ring shows (:focus-visible: the keyboard put it there)
 *   pressedByKeyboard(n, e) a press the keyboard made: the ring showing, or a click no pointer made
 *                           (Enter / Space on a button give the click detail 0)
 *   pointerBlur(n)          after a press: a pointer's lets the focus go (Space pauses again, the
 *                           letters are the page's), the keyboard's keeps it where it was
 *   typingIn(t)             a focused field takes every key: text inputs, selects, text areas and
 *                           editable text. A switch, a slider or a button is not one.
 *   ownsKey(t, k)           the keys a focused control acts on itself: Space / Enter press a button,
 *                           Space turns a switch, Enter follows a link, a slider takes the arrows,
 *                           Home, End and Page Up / Down, a tab its arrows, Home and End. Every other
 *                           key stays the page's.
 *   tabIndexFor(key, i, n)  where Left / Right (round the ends), Home and End move the selection in a
 *                           list of n tabs whose selected one is i; -1 for any other key
 *   tabs(list, o)           one tablist's behaviour (the WAI-ARIA tabs pattern): a roving tabindex (Tab
 *                           lands on the selected tab only), the keys of tabIndexFor with the focus
 *                           going along with the selection, and a press that selects: a pointer's lets
 *                           the focus go, the keyboard's keeps it (pointerBlur)
 *   returnPoint()           where the focus goes back when something the keyboard opened closes: the
 *                           opener is remembered only when the keyboard opened it, and the focus goes
 *                           back only when the keyboard closes it
 *
 * Which keys are shortcuts, and what they do, stays each page's own (the shared command vocabulary is a
 * later step of the plan). Only the elements' own members are used (focus, blur, matches, getAttribute,
 * setAttribute, tagName, type, isContentEditable, tabIndex, addEventListener, classList), so node runs
 * this as it is: tests/ui_common_tests.cjs, and tests/ocean_turbo_handoff.js's small DOM.
 *
 * The fish card (the plan's U19 to U21 and U45: one DOM inspector on both pages, in every view), the
 * parts both worlds draw the same way:
 *
 *   CARD_STATS              the common stats, in their order (#ienergy, #iage, #ispeed); a world's own
 *                           ones come after them, marked data-ext (the Ocean's depth readings)
 *   cardSubtitle(f)         the line under "Fish #id": generation, family, genes, then the body's size x
 *                           elongation when the body model is on (both worlds, this order)
 *   bodyScale(b)            the body's drawn scale (both pages' formula: renderer.js, ocean.js)
 *   drawPortrait(c, ...)    the colour key: one generic silhouette in the fish's colour, its proportions
 *                           from the body genes. It is a key to the colour, not a likeness (the Ocean's
 *                           fish inherit their shapes and skins: its card shows the unlit skin beside it)
 *   activationClock()       whether the card's live brain is this tick's (current) or waits for a step
 *   brainColor(v, a)        a node's colour for its activation; a waiting one's is neutral
 *   drawBrain(g, ...)       the live brain: senses -> hidden -> actions, the links under the nodes
 *   senseHtml / senseIdle   the line under the brain: a named node, or what the picture shows
 *
 * ui_common.css holds the styles that go with these (a tab's focus ring; the card's colour key and skin
 * captions, its short-screen rules and the 44 px touch target of a switch). */
(function (root) {
  /** @param {any} n @returns {boolean} */
  function keyboardFocused(n) {
    return !!(n && typeof n.matches === "function" && n.matches(":focus-visible"));
  }
  /** @param {any} n @param {{detail?: number} | null | undefined} [e] the click @returns {boolean} */
  function pressedByKeyboard(n, e) {
    return keyboardFocused(n) || (!!e && e.detail === 0);
  }
  /** @param {any} n */
  function pointerBlur(n) {
    if (n && !keyboardFocused(n) && typeof n.blur === "function") n.blur();
  }
  /** @param {any} t the event's target @returns {boolean} */
  function typingIn(t) {
    if (!t || !t.tagName) return false;
    if (t.tagName === "INPUT") return !/^(checkbox|radio|range|button|submit|reset|color|file|image)$/i.test(t.type || "text");
    return t.tagName === "TEXTAREA" || t.tagName === "SELECT" || !!t.isContentEditable;
  }
  /** @param {any} t @returns {boolean} */
  function isTab(t) {
    return !!(t && typeof t.getAttribute === "function" && t.getAttribute("role") === "tab");
  }
  /** @param {any} t the event's target @param {string} k the key (KeyboardEvent.key) @returns {boolean} */
  function ownsKey(t, k) {
    if (!t || !t.tagName) return false;
    var press = k === " " || k === "Spacebar" || k === "Enter";
    if (t.tagName === "BUTTON") return press || (isTab(t) && (/^Arrow/.test(k) || k === "Home" || k === "End"));
    if (t.tagName === "A") return k === "Enter";
    if (t.tagName !== "INPUT") return false;
    if (t.type === "range") return /^(Arrow|Page)/.test(k) || k === "Home" || k === "End";
    return press && (t.type === "checkbox" || t.type === "radio");
  }
  /** @param {string} key @param {number} i the selected tab (-1: none) @param {number} n how many @returns {number} */
  function tabIndexFor(key, i, n) {
    if (!(n > 0)) return -1;
    if (key === "Home") return 0;
    if (key === "End") return n - 1;
    if (key === "ArrowRight") return i < 0 ? 0 : (i + 1) % n;
    if (key === "ArrowLeft") return i < 0 ? n - 1 : (i - 1 + n) % n;
    return -1;
  }
  /**
   * One tablist. o.ids(): the tabs' ids in their order (asked each time: a list may change); o.current():
   * the selected id; o.button(id): its tab element; o.select(id): the page's own selection (its panel,
   * its charts, what it stores), which calls the returned mark(id) for the tabs' state. bind(button, id)
   * gives a tab its press.
   * @param {HTMLElement} list the role="tablist" element
   * @param {UiTabsOptions} o
   * @returns {UiTabs}
   */
  function tabs(list, o) {
    if (list.classList) list.classList.add("ui-tablist");
    /** @param {string} id */
    function mark(id) {
      o.ids().forEach(function (t) {
        var b = o.button(t);
        if (!b) return;
        b.setAttribute("aria-selected", t === id ? "true" : "false");
        b.tabIndex = t === id ? 0 : -1;
      });
    }
    /** @param {HTMLElement} b @param {string} id */
    function bind(b, id) {
      b.addEventListener("click", function () { o.select(id); pointerBlur(b); });
    }
    list.addEventListener("keydown", function (e) {
      /* (a modified arrow is the browser's or the system's: history, words, desktops) */
      if (e.altKey || e.ctrlKey || e.metaKey || !isTab(e.target)) return;
      var ids = o.ids(), j = tabIndexFor(e.key, ids.indexOf(o.current()), ids.length);
      if (j < 0) return;
      o.select(ids[j]);
      var b = o.button(ids[j]);
      if (b) b.focus();
      e.preventDefault();
    });
    return { mark: mark, bind: bind };
  }
  /** @returns {UiReturnPoint} */
  function returnPoint() {
    /** @type {any} */
    var at = null;
    return {
      set: function (n) { at = n || null; },
      get: function () { return at; },
      restore: function (keyboard) {
        var n = at;
        at = null;
        if (keyboard && n && typeof n.focus === "function") n.focus();
        return n;
      }
    };
  }

  /* ---------------- the fish card ---------------- */
  var CARD_STATS = ["energy", "age", "speed"];
  /** @param {UiCardFields} f @returns {string} */
  function cardSubtitle(f) {
    var genes = Math.round(f.genes);
    var parts = ["Generation " + Math.round(f.generation), "family #" + Math.round(f.family), genes + (genes === 1 ? " gene" : " genes")];
    if (f.body) parts.push("body " + f.body[0].toFixed(2) + " × " + f.body[1].toFixed(2));
    return parts.join(" · ");
  }
  /* a body's drawn scale: 1 at the default 1.0, steepest where the population sits, saturating at
   * +-0.4 (renderer.js bodyScale, which the flat view draws with, and ocean.js's: the same formula) */
  /** @param {number} b @returns {number} */
  function bodyScale(b) { return b > 0 ? 1 + 0.4 * Math.tanh(5 * (b - 1)) : 1; }
  /**
   * The colour key, 56 x 40 CSS px at the device's pixel ratio.
   * @param {HTMLCanvasElement} c @param {number[]} rgb @param {number} size @param {number} elong @param {number} [dpr]
   */
  function drawPortrait(c, rgb, size, elong, dpr) {
    dpr = dpr || 1;
    var w = 56, h = 40, g = c.getContext("2d");
    if (!g) return;
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
  /**
   * The card's live brain is the fish's last step: its senses and actions as that step read and set them
   * (kept only while the world's captureActivations is on: always on in Classic, while a fish is picked in
   * the Ocean), its hidden neurons as it left them. They are this tick's only when the last step ran with
   * the capture on and the fish was in it (one born in that step, or added by the floor, has age 0 and
   * runs its brain at the next). Otherwise the picture would mix this tick with an older step, or with
   * nothing at all (zeros), so the card says it waits for a step, and never steps a paused world to fill
   * it in. The clock follows the world's own frame counter (the shim's last sync, which every step is
   * followed by), not the page's steps, so a step it was not told of cannot pass for a captured one:
   *   reset(tick, on)    a world the page has not seen step (new, loaded, handed back by Turbo), its
   *                      capture on or off
   *   capture(on, tick)  the capture switched at that tick (the Ocean: a fish picked, or let go)
   *   at(tick)           the tick the kept activations are from (null: none since the reset)
   *   state(tick, age)   "current" (the last step's, this tick's) or "waiting"
   * @returns {UiActivationClock}
   */
  function activationClock() {
    var on = false, from = 0;
    /** @type {number | null} */
    var kept = null;   /* the last step with the capture on before it was last switched off (null: none since the reset) */
    /** @param {number} tick @returns {number | null} */
    function at(tick) { return on && tick > from ? tick : kept; }
    return {
      reset: function (tick, v) { on = !!v; from = tick; kept = null; },
      capture: function (v, tick) {
        v = !!v;
        if (v === on) return;
        if (on && tick > from) kept = tick;   /* switched off: what it holds is the last step's, until the world steps */
        on = v; from = tick;
      },
      at: at,
      state: function (tick, age) { return at(tick) === tick && age > 0 ? "current" : "waiting"; }
    };
  }
  /* a node's colour: lime for excited, orange for inhibited, brighter the stronger; a value the card does not
   * vouch for (null, NaN: waiting for a step) is a neutral grey, never the colour of an activation of 0 */
  /** @param {number | null | undefined} v @param {number} a @returns {string} */
  function brainColor(v, a) {
    if (typeof v !== "number" || !isFinite(v)) return "rgba(112,126,130," + a + ")";
    var m = Math.min(1, Math.abs(v));
    return v >= 0 ? "rgba(" + Math.round(70 + 130 * m) + "," + Math.round(90 + 150 * m) + "," + Math.round(60 + 10 * m) + "," + a + ")"
                  : "rgba(" + Math.round(80 + 175 * m) + "," + Math.round(90 + 20 * m) + "," + Math.round(70 + 10 * m) + "," + a + ")";
  }
  /**
   * The card's network, w x h CSS px at the context's pixel ratio: senses -> hidden -> actions, the links first
   * (curved, brighter and thicker the more they carry right now), the nodes on top. Wide boxes lay it out top to
   * bottom, tall ones left to right (the actions named at the right, o.gutter px from the edge). With o.fresh
   * false (waiting for a step) no activation is shown: the links are the wiring alone (their sign's colour, the
   * faintest weight) and every node is neutral. Returns the nodes' places, for the tap-to-name line; o.prev /
   * o.hover: the last draw's nodes and the one pointed at (its ring, and its links lit).
   * @param {CanvasRenderingContext2D} g @param {number} w @param {number} h @param {UiBrainNet} f @param {UiBrainOptions} o
   * @returns {UiBrainNode[]}
   */
  function drawBrain(g, w, h, f, o) {
    var nS = o.nS, nH = o.nH, nA = o.nA, fresh = o.fresh !== false, gut = o.gutter, i;
    g.setTransform(o.dpr || 1, 0, 0, o.dpr || 1, 0, 0);
    g.clearRect(0, 0, w, h);
    var wide = w > h * 1.15, m = 14;
    /** @type {{sen: number[][], hid: number[][], act: number[][]}} */
    var pos = { sen: [], hid: [], act: [] };
    if (wide) {
      var yIn = 26, yOut = h - 40, yHid = (yIn + yOut) / 2;
      for (i = 0; i < nS; i++) pos.sen.push([m + (w - 2 * m) * i / (nS - 1), yIn]);
      for (i = 0; i < nH; i++) pos.hid.push([m + 18 + (w - 2 * m - 36) * i / (nH - 1), yHid]);
      for (i = 0; i < nA; i++) pos.act.push([m + 18 + (w - 2 * m - 36) * i / (nA - 1), yOut]);
    } else {
      var yTop = 26, yBot = h - 12, xS = 18, xA = w - gut, xH = (xS + xA) / 2;
      for (i = 0; i < nS; i++) pos.sen.push([xS, yTop + (yBot - yTop) * i / (nS - 1)]);
      for (i = 0; i < nH; i++) pos.hid.push([xH, yTop + (yBot - yTop) * i / (nH - 1)]);
      for (i = 0; i < nA; i++) pos.act.push([xA, yTop + (yBot - yTop) * i / (nA - 1)]);
    }
    var prev = o.prev || [], hv = typeof o.hover === "number" ? o.hover : -1;
    var hoverKey = hv >= 0 && prev[hv] ? prev[hv].kind + prev[hv].i : null;
    for (var k = 0; k < f.connCount; k++) {
      var c = k * 5;
      var srcSen = f.conns[c] !== 0, srcNum = f.conns[c + 1] | 0, sinkAct = f.conns[c + 2] !== 0, sinkNum = f.conns[c + 3] | 0, wgt = f.conns[c + 4];
      var a = srcSen ? pos.sen[srcNum] : pos.hid[srcNum], b = sinkAct ? pos.act[sinkNum] : pos.hid[sinkNum];
      if (!a || !b) continue;
      var srcAct = srcSen ? f.sensors[srcNum] : f.hidden[srcNum];
      var mag = fresh ? Math.min(1, Math.abs(wgt) * Math.abs(srcAct) * 1.5) : 0;
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
    /** @type {UiBrainNode[]} */
    var nodes = [];
    /** @param {number[]} p @param {number} r @param {number} v @param {string} kind @param {number} idx */
    function node(p, r, v, kind, idx) {
      g.fillStyle = brainColor(fresh ? v : NaN, 1);
      g.beginPath(); g.arc(p[0], p[1], r, 0, Math.PI * 2); g.fill();
      g.strokeStyle = "rgba(4,14,16,0.85)"; g.lineWidth = 1; g.stroke();
      nodes.push({ x: p[0], y: p[1], kind: kind, i: idx, v: v });
    }
    var rs = Math.max(2, Math.min(3.2, (wide ? w : h) / nS * 0.36));
    for (i = 0; i < nS; i++) node(pos.sen[i], rs, f.sensors[i], "Sense", i);
    for (i = 0; i < nH; i++) node(pos.hid[i], 5, f.hidden[i], "Hidden neuron", i);
    for (i = 0; i < nA; i++) node(pos.act[i], 5.5, f.actions[i], "Action", i);
    if (hv >= 0 && nodes[hv]) {
      var hn = nodes[hv];
      g.strokeStyle = "rgba(230,255,160,0.95)"; g.lineWidth = 2;
      g.beginPath(); g.arc(hn.x, hn.y, 8, 0, Math.PI * 2); g.stroke();
    }
    g.font = "11px " + o.font;
    /** @param {string} text @param {number} x @param {number} y */
    function tag(text, x, y) {   /* a label on a small backing, readable over the links */
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
      for (i = 0; i < nA; i++) g.fillText(o.actShort[i] || "", pos.act[i][0], h - 40 + (i % 2 ? 30 : 18));
      g.textAlign = "left";
    } else {
      g.fillText("senses", 6, 13);
      g.fillText("hidden", (18 + w - gut) / 2 - 18, 13);
      g.fillText("actions", w - gut - 6, 13);
      for (i = 0; i < nA; i++) g.fillText(o.actLabels[i] || "", pos.act[i][0] + 10, pos.act[i][1] + 4);
    }
    return nodes;
  }
  /* the line under the brain for a node pointed at: its kind, a <b> for its name (the page sets its text), and
   * its value, or that it waits for a step */
  /** @param {UiBrainNode} n @param {boolean} fresh @returns {string} */
  function senseHtml(n, fresh) {
    return n.kind + ": <b></b> " + (fresh ? (n.v >= 0 ? "+" : "") + n.v.toFixed(2) : "· waits for a step");
  }
  /* the line with no node pointed at: how to read the picture, or (waiting) why it shows no activity; keys: how this
   * page steps a paused world ("Space runs it; . steps once"), said only while paused */
  /** @param {boolean} fresh @param {boolean} touch @param {boolean} paused @param {string} keys @returns {string} */
  function senseIdle(fresh, touch, paused, keys) {
    if (fresh) return "Senses on one side, actions on the other. Lime links excite, orange ones inhibit; brighter = stronger right now. " +
                      (touch ? "Tap" : "Point at") + " a dot to name it.";
    return "Waiting for a step: this fish's senses and actions show once the world steps" + (paused && keys ? " (" + keys + ")" : "") +
           ". Until then the picture is its wiring alone.";
  }

  /** @type {EvoUIApi} */
  var API = {
    keyboardFocused: keyboardFocused, pressedByKeyboard: pressedByKeyboard, pointerBlur: pointerBlur,
    typingIn: typingIn, ownsKey: ownsKey, tabIndexFor: tabIndexFor, tabs: tabs, returnPoint: returnPoint,
    CARD_STATS: CARD_STATS, cardSubtitle: cardSubtitle, bodyScale: bodyScale, drawPortrait: drawPortrait,
    activationClock: activationClock, brainColor: brainColor, drawBrain: drawBrain, senseHtml: senseHtml, senseIdle: senseIdle
  };
  root.EvoUI = API;
})(typeof window !== "undefined" ? window : globalThis);

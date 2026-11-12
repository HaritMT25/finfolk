// tests/ui_common_tests.cjs: the shared focus primitives (web/ui_common.js, window.EvoUI) and the tablists that use them, in node
// (no browser). node tests/ui_common_tests.cjs  (exit 0 = pass; CI's "web ui" job)
//   - the predicates: which keys a focused control owns (ownsKey), when a field takes every key (typingIn), a keyboard's press
//     (keyboardFocused, pressedByKeyboard) and a pointer's (pointerBlur)
//   - tabIndexFor: Left / Right round the ends, Home / End, nothing else
//   - tabs(): a roving tabindex, the keys with the focus going along, wrapping, modified keys and other targets left alone, a
//     pointer's press releasing the focus and the keyboard's keeping it
//   - returnPoint(): the focus back to a keyboard opener, only when the keyboard closes
//   - both pages' dashboards (web/dashboard.js: Classic; web/ocean_dash.js: the Ocean) on a small DOM, the same assertions for
//     both: the UI parity plan's U37 (Classic's tabs had no keys and blurred on every press)
//   - both pages load ui_common.js (and its stylesheet) before the scripts that use it
// The browser's own behaviour (the ring itself, real focus heuristics, the setup sheets' tabs on the real pages) is in
// tests/ui_parity_browser.mjs's S2 cases; the Ocean page's tab keys with its whole key router in tests/ocean_turbo_handoff.js.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const WEB = path.join(__dirname, "..", "web");

let fails = 0, checks = 0;
function ok(cond, what, info) {
  checks++;
  if (!cond) { fails++; console.log("  FAIL " + what + (info !== undefined ? "  " + JSON.stringify(info).slice(0, 500) : "")); }
  else console.log("  ok   " + what);
}
function section(name) { console.log("== " + name); }

/* ---------------- a small DOM: elements, bubbling events, focus with a keyboard / pointer modality ---------------- */
function makeDom() {
  const byId = new Map(), errors = [];
  const doc = { activeElement: null, modality: "pointer", _ls: {} };
  function fire(n, ev) {
    ev.currentTarget = n;
    for (const f of (n._ls[ev.type] || []).slice()) { try { f.call(n, ev); } catch (e) { errors.push(String(e && e.stack || e)); } }
  }
  class Ev {
    constructor(type, o) { Object.assign(this, { type, bubbles: !!(o && o.bubbles), defaultPrevented: false, target: null, stopped: false }, o || {}); }
    preventDefault() { this.defaultPrevented = true; }
    stopPropagation() { this.stopped = true; }
  }
  const parse = (s) => { const m = /^([a-z0-9]*)((?:[.#][\w-]+)*)$/i.exec(s.trim()); if (!m) throw new Error("the test DOM has no selector " + s);
    return { tag: m[1].toUpperCase(), cls: (m[2].match(/\.[\w-]+/g) || []).map((x) => x.slice(1)), id: ((m[2].match(/#[\w-]+/) || ["#"])[0]).slice(1) }; };
  const hit = (e, p) => (!p.tag || e.tagName === p.tag) && (!p.id || e.id === p.id) && p.cls.every((c) => e._cls.has(c));
  function* walk(e) { for (const c of e.children) { yield c; yield* walk(c); } }
  class El {
    constructor(tag) {
      this.tagName = String(tag).toUpperCase(); this.children = []; this.parentNode = null; this.attrs = {}; this.dataset = {}; this._ls = {};
      this._cls = new Set(); this._id = ""; this._text = ""; this.hidden = false; this.type = ""; this.tabIndex = this.tagName === "BUTTON" ? 0 : -1;
      this.style = {}; this.scrollTop = 0; this.clientWidth = 800; this.clientHeight = 600; this.isContentEditable = false;
    }
    get id() { return this._id; } set id(v) { this._id = String(v); byId.set(this._id, this); }
    get className() { return Array.from(this._cls).join(" "); } set className(v) { this._cls = new Set(String(v).split(/\s+/).filter(Boolean)); }
    get classList() { const s = this._cls; return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)),
      toggle: (c, on) => { if (on === undefined) on = !s.has(c); if (on) s.add(c); else s.delete(c); return !!on; }, contains: (c) => s.has(c) }; }
    get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
    set textContent(v) { this.children = []; this._text = String(v); }
    set innerHTML(v) {   /* flat: the elements in it, by tag and class */
      this.children = []; this._text = "";
      for (const m of String(v).matchAll(/<([a-z][\w-]*)([^>]*)>/gi)) { const c = new El(m[1]), cl = /\sclass=(['"])(.*?)\1/.exec(m[2]); if (cl) c.className = cl[2]; this.appendChild(c); }
    }
    get innerHTML() { return ""; }
    get firstChild() { return this.children[0] || null; }
    appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.children.push(c); return c; }
    removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); c.parentNode = null; return c; }
    remove() { if (this.parentNode) this.parentNode.removeChild(this); }
    setAttribute(k, v) { this.attrs[k] = String(v); if (k === "id") this.id = v; }
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
    addEventListener(t, f) { (this._ls[t] = this._ls[t] || []).push(f); }
    removeEventListener(t, f) { const l = this._ls[t] || [], i = l.indexOf(f); if (i >= 0) l.splice(i, 1); }
    dispatchEvent(ev) {
      if (!ev.target) ev.target = this;
      for (let n = this; n; n = ev.bubbles && !ev.stopped ? n.parentNode : null) fire(n, ev);
      if (ev.bubbles && !ev.stopped) { fire(doc, ev); fire(win, ev); }
      return !ev.defaultPrevented;
    }
    focus() { doc.activeElement = this; }
    blur() { if (doc.activeElement === this) doc.activeElement = null; }
    matches(sel) {
      if (sel === ":focus-visible") return doc.activeElement === this && doc.modality === "keyboard";
      return sel.split(",").some((s) => hit(this, parse(s)));
    }
    querySelector(sel) { const p = parse(sel); for (const e of walk(this)) if (hit(e, p)) return e; return null; }
    querySelectorAll(sel) { const p = parse(sel), o = []; for (const e of walk(this)) if (hit(e, p)) o.push(e); return o; }
    closest(sel) { for (let n = this; n; n = n.parentNode) if (n.matches && n.matches(sel)) return n; return null; }
    contains(n) { for (; n; n = n.parentNode) if (n === this) return true; return false; }
    getBoundingClientRect() { return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 }; }
    getContext() { return null; }
    click(detail) { this.dispatchEvent(new Ev("click", { bubbles: true, detail: detail === undefined ? 0 : detail })); }
  }
  const body = new El("body"), win = { _ls: {} };
  Object.assign(doc, { body, documentElement: body, createElement: (t) => new El(t), getElementById: (id) => byId.get(id) || null,
                       addEventListener: (t, f) => { (doc._ls[t] = doc._ls[t] || []).push(f); }, removeEventListener() {} });
  win.addEventListener = (t, f) => { (win._ls[t] = win._ls[t] || []).push(f); };
  win.removeEventListener = () => {};
  /* the keyboard: a key where the focus is (else the body), bubbling to the window; a pointer: a press on the element */
  function key(k, o) {
    doc.modality = "keyboard";
    const t = doc.activeElement || body, ev = new Ev("keydown", Object.assign({ key: k, bubbles: true, altKey: false, ctrlKey: false, metaKey: false, shiftKey: false }, o || {}));
    t.dispatchEvent(ev);
    if (!ev.defaultPrevented && t.tagName === "BUTTON" && (k === "Enter" || k === " ")) t.click(0);
    return ev;
  }
  function pointer(e) { doc.modality = "pointer"; e.focus(); e.click(1); }   /* (Chrome focuses a pressed button; :focus-visible does not match) */
  function tabTo(e) { doc.modality = "keyboard"; e.focus(); }
  return { doc, win, El, Ev, errors, key, pointer, tabTo, body, make(tag, id, parent) { const e = new El(tag); if (id) e.id = id; (parent || body).appendChild(e); return e; } };
}

function load(files, ctx) {
  vm.createContext(ctx);
  for (const f of files) vm.runInContext(typeof f === "string" ? fs.readFileSync(path.join(WEB, f), "utf8") : f.src, ctx, { filename: typeof f === "string" ? f : f.name });
  return ctx;
}
const UI = load(["ui_common.js"], { console }).EvoUI;   /* (no window: it registers on globalThis, as in node) */

section("the module");
ok(UI && ["keyboardFocused", "pressedByKeyboard", "pointerBlur", "typingIn", "ownsKey", "tabIndexFor", "tabs", "returnPoint"].every((k) => typeof UI[k] === "function"),
   "ui_common.js registers EvoUI with its eight primitives, without a window (globalThis)");

section("typingIn: a focused field takes every key");
{
  const D = makeDom(), inp = (type) => { const e = new D.El("input"); e.type = type; return e; };
  for (const t of ["text", "number", "search", "email", "password", "url", "tel", "", "date"]) ok(UI.typingIn(inp(t)), "input type " + JSON.stringify(t) + ": typing");
  for (const t of ["checkbox", "radio", "range", "button", "submit", "reset", "color", "file", "image", "CHECKBOX"]) ok(!UI.typingIn(inp(t)), "input type " + t + ": not typing (its keys are ownsKey's)");
  ok(UI.typingIn(new D.El("textarea")) && UI.typingIn(new D.El("select")), "a text area and a select: typing");
  const ce = new D.El("div"); ce.isContentEditable = true;
  ok(UI.typingIn(ce) && !UI.typingIn(new D.El("div")) && !UI.typingIn(new D.El("button")), "editable text: typing; a plain element or a button: not");
  ok(!UI.typingIn(null) && !UI.typingIn(undefined) && !UI.typingIn({}) && !UI.typingIn(D.doc), "no target, or one without a tag (the document): not typing");
}

section("ownsKey: the keys a focused control acts on itself");
{
  const D = makeDom(), mk = (tag, type, role) => { const e = new D.El(tag); if (type) e.type = type; if (role) e.setAttribute("role", role); return e; };
  const btn = mk("button"), tab = mk("button", "", "tab"), link = mk("a"), range = mk("input", "range"), box = mk("input", "checkbox"), radio = mk("input", "radio"), text = mk("input", "text");
  const PRESS = [" ", "Spacebar", "Enter"], ARROWS = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"];
  ok(PRESS.every((k) => UI.ownsKey(btn, k)) && !ARROWS.some((k) => UI.ownsKey(btn, k)) && !["Home", "End", "f", "t", "?", "Escape"].some((k) => UI.ownsKey(btn, k)),
     "a button: Space / Enter only (its arrows, Home, End and letters stay the page's)");
  ok(PRESS.every((k) => UI.ownsKey(tab, k)) && ARROWS.every((k) => UI.ownsKey(tab, k)) && UI.ownsKey(tab, "Home") && UI.ownsKey(tab, "End") &&
     !["f", "g", "PageUp", "Escape", "Tab"].some((k) => UI.ownsKey(tab, k)), "a tab: Space / Enter, the four arrows, Home and End (the tablist moves on them); letters stay shortcuts");
  ok(UI.ownsKey(link, "Enter") && !UI.ownsKey(link, " ") && !UI.ownsKey(link, "ArrowRight"), "a link: Enter only");
  ok(ARROWS.concat(["PageUp", "PageDown", "Home", "End"]).every((k) => UI.ownsKey(range, k)) && !UI.ownsKey(range, " ") && !UI.ownsKey(range, "Enter") && !UI.ownsKey(range, "v"),
     "a slider: the arrows, Page Up / Down, Home and End; not Space, Enter or a letter");
  ok(PRESS.every((k) => UI.ownsKey(box, k)) && PRESS.every((k) => UI.ownsKey(radio, k)) && !UI.ownsKey(box, "ArrowUp") && !UI.ownsKey(box, "l"),
     "a switch (checkbox) and a radio: Space / Enter; not arrows or letters");
  ok(!UI.ownsKey(text, "a") && !UI.ownsKey(mk("div"), " ") && !UI.ownsKey(null, " ") && !UI.ownsKey(D.doc, " "),
     "a text field owns no key here (typingIn takes them all), nor does a plain element, nothing, or the document");
}

section("keyboardFocused / pressedByKeyboard / pointerBlur");
{
  const D = makeDom(), b = D.make("button", "b");
  D.tabTo(b);
  ok(UI.keyboardFocused(b) && UI.pressedByKeyboard(b, { detail: 1 }), "focused by the keyboard: its ring shows; a press then is the keyboard's");
  UI.pointerBlur(b);
  ok(D.doc.activeElement === b, "pointerBlur keeps a keyboard focus");
  D.doc.modality = "pointer";
  ok(!UI.keyboardFocused(b) && !UI.pressedByKeyboard(b, { detail: 1 }) && UI.pressedByKeyboard(b, { detail: 0 }) && !UI.pressedByKeyboard(b, null),
     "a pointer's focus: no ring; a click with detail 0 (Enter / Space on a button, no pointer) still counts as the keyboard's");
  UI.pointerBlur(b);
  ok(D.doc.activeElement === null, "pointerBlur lets a pointer's focus go");
  ok(!UI.keyboardFocused(null) && !UI.keyboardFocused({}), "nothing, or an object without matches: not focused");
  UI.pointerBlur(null); UI.pointerBlur({});
  ok(true, "pointerBlur of nothing, or of an object without blur, does nothing (no throw)");
}

section("tabIndexFor: Left / Right round the ends, Home / End");
{
  const t = UI.tabIndexFor;
  ok(t("ArrowRight", 0, 4) === 1 && t("ArrowRight", 3, 4) === 0 && t("ArrowLeft", 0, 4) === 3 && t("ArrowLeft", 2, 4) === 1, "Right / Left, round both ends");
  ok(t("Home", 2, 4) === 0 && t("End", 1, 4) === 3 && t("Home", 0, 1) === 0 && t("End", 0, 1) === 0, "Home the first, End the last (one tab: itself)");
  ok(t("ArrowRight", -1, 4) === 0 && t("ArrowLeft", -1, 4) === 3, "none selected: Right the first, Left the last");
  ok(["ArrowUp", "ArrowDown", "PageUp", "Enter", " ", "a", "Tab"].every((k) => t(k, 1, 4) === -1), "Up, Down, Page, Enter, Space, letters, Tab: not a tab move (-1)");
  ok(t("ArrowRight", 0, 0) === -1 && t("Home", 0, 0) === -1, "no tabs: nothing");
}

section("tabs(): one tablist");
{
  const D = makeDom(), list = D.make("nav", "tl"), other = D.make("button", "other", list);
  list.setAttribute("role", "tablist");
  const ids = ["a", "b", "c", "d"], btn = {}, log = [];
  let cur = "a";
  const T = UI.tabs(list, { ids: () => ids, current: () => cur, button: (id) => btn[id] || null, select: (id) => { cur = id; log.push(id); T.mark(id); } });
  for (const id of ids) { const b = D.make("button", "tab-" + id, list); b.setAttribute("role", "tab"); btn[id] = b; T.bind(b, id); }
  T.mark("a");
  const state = () => ids.map((id) => (btn[id].getAttribute("aria-selected") === "true" ? "S" : "-") + btn[id].tabIndex).join(" ");
  ok(list.classList.contains("ui-tablist"), "the list is marked ui-tablist (ui-common.css: the ring inside the tab)");
  ok(state() === "S0 --1 --1 --1", "mark: aria-selected on the selected tab only, and only it in the Tab order (roving tabindex)", state());
  D.tabTo(btn.a);
  let ev = D.key("ArrowRight");
  ok(cur === "b" && D.doc.activeElement === btn.b && ev.defaultPrevented && state() === "--1 S0 --1 --1",
     "Right: the next tab selected, the focus with it, the key taken (preventDefault)", { cur, state: state() });
  D.key("End");
  ok(cur === "d" && D.doc.activeElement === btn.d, "End: the last");
  D.key("ArrowRight");
  ok(cur === "a" && D.doc.activeElement === btn.a, "Right on the last: round to the first");
  D.key("ArrowLeft");
  ok(cur === "d" && D.doc.activeElement === btn.d, "Left on the first: round to the last");
  D.key("Home");
  ok(cur === "a" && D.doc.activeElement === btn.a && state() === "S0 --1 --1 --1", "Home: the first; the roving tabindex follows", state());
  const n0 = log.length;
  for (const k of ["ArrowUp", "ArrowDown", "a", "Tab", "PageDown"]) { ev = D.key(k); if (ev.defaultPrevented) break; }
  ok(log.length === n0 && !ev.defaultPrevented && cur === "a", "Up, Down, a letter, Tab, Page Down: no move, the key left to the page (not prevented)");
  ev = D.key("ArrowRight", { altKey: true });
  const e2 = D.key("ArrowRight", { ctrlKey: true }), e3 = D.key("ArrowLeft", { metaKey: true });
  ok(cur === "a" && !ev.defaultPrevented && !e2.defaultPrevented && !e3.defaultPrevented, "Alt / Ctrl / Meta + an arrow: the browser's or the system's (no move, not prevented)");
  D.tabTo(other);
  ev = D.key("ArrowRight");
  ok(cur === "a" && !ev.defaultPrevented, "an arrow from a non-tab element inside the list: not the tablist's");
  /* presses */
  D.tabTo(btn.c);
  D.key("Enter");
  ok(cur === "c" && D.doc.activeElement === btn.c, "Enter on a focused tab (the keyboard's press): it is selected and keeps the focus");
  D.tabTo(btn.b);
  D.key(" ");
  ok(cur === "b" && D.doc.activeElement === btn.b, "Space on a focused tab: the same");
  D.pointer(btn.d);
  ok(cur === "d" && D.doc.activeElement === null && state() === "--1 --1 --1 S0", "a pointer's press: selected, and the focus let go (Space and the page's keys work again)", state());
  ok(D.errors.length === 0, "no listener threw", D.errors.slice(0, 2));
}
{
  /* a list whose ids change between presses (asked each time), and a select that does not mark */
  const D = makeDom(), list = D.make("nav"), btn = {}, ids = ["x", "y"];
  let cur = "x";
  const T = UI.tabs(list, { ids: () => ids, current: () => cur, button: (id) => btn[id] || null, select: (id) => { cur = id; } });
  const add = (id) => { const b = D.make("button", id, list); b.setAttribute("role", "tab"); btn[id] = b; T.bind(b, id); };
  ids.forEach(add);
  D.tabTo(btn.x);
  ids.push("z"); add("z");
  D.key("End");
  ok(cur === "z" && D.doc.activeElement === btn.z, "ids() asked at each press: a tab added later is reached");
  ids.splice(0, 3, "y"); cur = "gone";
  D.tabTo(btn.y);
  D.key("ArrowRight");
  ok(cur === "y", "the current id not among the ids (removed): Right selects the first");
}

section("returnPoint(): the focus back where the keyboard opened from");
{
  const D = makeDom(), opener = D.make("button", "opener"), inside = D.make("button", "inside"), R = UI.returnPoint();
  D.tabTo(opener); R.set(opener); inside.focus();
  ok(R.get() === opener, "set: the keyboard's opener remembered");
  const back = R.restore(true);
  ok(back === opener && D.doc.activeElement === opener && R.get() === null, "restore(true), a keyboard's close: the focus back on the opener, and it is forgotten");
  R.set(opener); inside.focus();
  R.restore(false);
  ok(D.doc.activeElement === inside && R.get() === null, "restore(false), a pointer's close: the focus stays, the opener forgotten");
  R.set(null); inside.focus();
  ok(R.restore(true) === null && D.doc.activeElement === inside, "opened by a pointer (set(null)): a keyboard's close moves no focus");
  R.set(opener); R.set(inside); opener.focus();
  R.restore(true);
  ok(D.doc.activeElement === inside, "each opening replaces the opener (the last one gets the focus)");
  R.set(undefined);
  ok(R.get() === null && R.restore(true) === null, "set(undefined) is set(null)");
}

/* ---------------- both pages' dashboards on the small DOM ---------------- */
const CHARTS = `(function () {
  function Chart(box, kind) { this.box = box; this.kind = kind; }
  Chart.prototype.draw = function (d) { this.data = d; };
  var base = { T: { series: ["#1", "#2", "#3", "#4", "#5", "#6", "#7", "#8"], other: "#9" }, Chart: Chart,
               esc: function (s) { return String(s); }, fmtTime: function (s) { return s + " s"; }, seq: function () { return "#0"; }, alpha: function (c) { return c; } };
  window.EvoCharts = new Proxy(base, { get: function (t, k) { return k in t ? t[k] : function () { return ""; }; } });
})();`;
function bootDash(kind) {
  const D = makeDom();
  for (const [id, tag] of [["dash", "div"], ["dashbtn", "button"], ["dgrid", "div"], ["dnote", "p"], ["dcsv", "button"], ["dtree", "button"], ["dclose", "button"]]) D.make(tag, id);
  const tl = D.make("nav", "dtabs", D.doc.getElementById("dash"));
  tl.setAttribute("role", "tablist");
  D.doc.getElementById("dash").hidden = true;
  const timers = [];
  const ctx = { console, Math, JSON, Object, Array, Number, String, Float64Array, Float32Array, Int32Array, Uint8Array, Uint32Array, Map, Set, Proxy, Error, isFinite, Infinity, NaN,
                document: D.doc, performance: { now: () => 0 }, setInterval: (f) => { timers.push(f); return timers.length; }, clearInterval() {}, setTimeout: () => 0, clearTimeout() {},
                URL, Blob: function () {} };
  Object.assign(ctx, { addEventListener: D.win.addEventListener, removeEventListener: D.win.removeEventListener });
  ctx.window = ctx; ctx.globalThis = ctx;
  D.win.addEventListener = ctx.addEventListener;
  const files = kind === "classic" ? ["ui_common.js", "dash_data.js", { name: "charts_stub.js", src: CHARTS }, "dashboard.js"]
                                   : ["ui_common.js", { name: "charts_stub.js", src: CHARTS }, "ocean_dash.js"];
  load(files, ctx);
  const api = kind === "classic" ? ctx.EvoDash : ctx.EvoOceanDash;
  if (kind === "classic") api.attach({ module: null, heap: () => new ArrayBuffer(8), actionNames: [], setDrawer() {}, runConfig: () => ({}), colourByBrain: () => false, setRecEvery() {} });
  else api.attach({ depth: () => 240, familyColor: () => 0, wiring: () => null, setDrawer() {}, onOpen() {}, setRecEvery() {} });
  return { D, api, tl };
}
for (const kind of ["classic", "ocean"]) {
  section("the dashboards' tabs: " + (kind === "classic" ? "Classic (web/dashboard.js)" : "the Ocean (web/ocean_dash.js)"));
  const { D, api, tl } = bootDash(kind);
  ok(!!api, (kind === "classic" ? "EvoDash" : "EvoOceanDash") + " registers with EvoUI loaded first");
  api.open();
  const tabs = tl.children, n = tabs.length;
  const sel = () => tabs.findIndex((b) => b.getAttribute("aria-selected") === "true");
  const roving = () => tabs.every((b, i) => b.tabIndex === (i === sel() ? 0 : -1));
  ok(n >= 4 && sel() === 0 && roving() && tabs.every((b) => b.getAttribute("role") === "tab" && b.type === "button"),
     "open: " + n + " tabs (role tab, type button), the first selected, only it in the Tab order", tabs.map((b) => [b.getAttribute("aria-selected"), b.tabIndex]));
  D.tabTo(tabs[0]);
  let ev = D.key("ArrowRight");
  ok(sel() === 1 && D.doc.activeElement === tabs[1] && ev.defaultPrevented && roving(), "Right: the next tab, the focus with it, the key taken; the roving tabindex follows");
  D.key("End");
  ok(sel() === n - 1 && D.doc.activeElement === tabs[n - 1], "End: the last tab");
  D.key("ArrowRight");
  ok(sel() === 0 && D.doc.activeElement === tabs[0], "Right on the last: round to the first");
  D.key("ArrowLeft");
  ok(sel() === n - 1 && D.doc.activeElement === tabs[n - 1], "Left on the first: round to the last");
  D.key("Home");
  ok(sel() === 0 && D.doc.activeElement === tabs[0] && roving(), "Home: the first");
  ev = D.key("ArrowUp");
  ok(sel() === 0 && !ev.defaultPrevented, "Up: no tab move, left to the page (whose router leaves a focused tab its arrows: EvoUI.ownsKey)");
  D.tabTo(tabs[2]);
  D.key("Enter");
  ok(sel() === 2 && D.doc.activeElement === tabs[2], "Enter on a focused tab: selected, the focus kept (before this, Classic blurred every press)");
  D.pointer(tabs[3]);
  ok(sel() === 3 && D.doc.activeElement === null && roving(), "a pointer's press: selected, the focus let go");
  api.close();
  ok(D.errors.length === 0, "no listener threw (the charts of every tab visited drew)", D.errors.slice(0, 2));
}

section("both pages load ui_common.js and its stylesheet before the scripts that use it");
for (const [page, users] of [["index.html", ["renderer.js", "dashboard.js"]], ["ocean.html", ["ocean.js", "ocean_dash.js"]]]) {
  const html = fs.readFileSync(path.join(WEB, page), "utf8"), at = (s) => html.indexOf('<script src="' + s + '"></script>');
  const head = html.slice(0, html.indexOf("</head>"));
  ok(at("ui_common.js") > 0 && users.every((u) => at(u) > at("ui_common.js")) && html.split('<script src="ui_common.js"></script>').length === 2,
     page + ": ui_common.js once, before " + users.join(" and "));
  ok(/<link rel="stylesheet" href="ui_common\.css">/.test(head), page + ": ui_common.css linked in the head");
}
for (const f of ["ui_common.js", "ui_common.css"]) ok(fs.readFileSync(path.join(__dirname, "..", "wasm", "build_site.sh"), "utf8").indexOf("web/" + f) >= 0, "wasm/build_site.sh publishes web/" + f);

console.log((fails ? "FAILED " + fails + " of " : "all ") + checks + " checks" + (fails ? "" : " passed"));
process.exit(fails ? 1 : 0);

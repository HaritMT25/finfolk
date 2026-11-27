// @ts-check
"use strict";
/* Ocean popovers, statistics, drawer and tooltips. Explicit phases preserve page order. */
(function () {
  /** @param {OceanLayersPorts} ports @returns {OceanLayers} */
  function create(ports) {
  /** @type {Record<string, string[]>} */
  var POPS;
  /** @type {string | null} */
  var openPop;
  /** @type {UiReturnPoint} */
  var popOpener;
  /** @type {boolean} */
  var statOpen, cardNewer, cardHeld;
  /** @type {HTMLElement} */
  var drawerEl, menuBtn, tipEl, tipDesc, tipTry;
  /** @type {number} */
  var tipTimer;
  /** @type {HTMLElement | null} */
  var tipFor;
  /* ---- the View menu and Help: one popover at a time; ×, Esc, its key or a
   * press outside closes it. [popover, trigger, its first control] ---- */
  function initPop() {
  POPS = { view: ["viewpop", "viewmenubtn", "lightnow"], help: ["helppop", "helpbtn", "tourbtn"] }, openPop = null, popOpener = ports.UI.returnPoint();
  }
  /* opener: the trigger, when the keyboard pressed it (else null): the focus
   * goes to the popover's first control, and back to the trigger when the
   * keyboard closes it (closePop: the return point, web/ui_common.js). Each
   * opening replaces it, so only the open popover's is ever restored. */
  function setPop(name, opener) {
    openPop = POPS[name] ? name : null;
    if (openPop) popOpener.set(opener);
    Object.keys(POPS).forEach(function (n) {
      ports.el(POPS[n][0]).hidden = n !== openPop;
      ports.el(POPS[n][1]).setAttribute("aria-expanded", n === openPop ? "true" : "false");
    });
    document.body.classList.toggle("help-open", openPop === "help");
    if (openPop) {
      /* never under a layer above it: the charts, a narrow screen's settings sheet */
      if (ports.readouts.dash() && /** @type {OceanDashboard} */ (ports.readouts.dash()).isOpen()) /** @type {OceanDashboard} */ (ports.readouts.dash()).close();
      if (!ports.wideMQ.matches && drawerEl.classList.contains("open")) setDrawer(false);
      setStatPanel(false); ports.tour.hideCoach(); placePop();
      if (popOpener.get()) ports.el(POPS[openPop][2]).focus();
    }
  }
  function closePop(keyboard) {
    setPop(null);
    popOpener.restore(keyboard);
  }
  function togglePop(name, opener, keyboard) { if (openPop === name) closePop(keyboard); else setPop(name, opener); }
  /* the View menu over its button, left of a wide screen's settings panel (a
   * phone: the screen's width, from the CSS) */
  function placePop() {
    var pop = ports.el("viewpop");
    if (openPop !== "view" || innerWidth < 600) { pop.style.left = ""; return; }
    var r = ports.el("viewmenubtn").getBoundingClientRect(), w = pop.offsetWidth;
    var right = ports.wideMQ.matches && drawerEl.classList.contains("open") ? drawerEl.getBoundingClientRect().left : innerWidth;
    pop.style.left = Math.round(Math.max(10, Math.min(right - w - 10, r.left + r.width / 2 - w / 2))) + "px";
  }
  function registerPopOutside() {
  document.addEventListener("pointerdown", function (e) {
    if (openPop && !/** @type {Element} */ (e.target).closest("#" + POPS[openPop][0] + ", #" + POPS[openPop][1])) setPop(null);
  });
  }
  function initStats() {
  statOpen = false;
  /* The live numbers and a fish card where they overlap (a phone; a card
   * flipped to the top; its brain open): the newer shows (updateCard). The
   * numbers opened over a card hide it until they close (cardHeld), its
   * fish still selected, followed and lit; a fish picked while they are open
   * (cardNewer) closes them. */
  cardNewer = false, cardHeld = false;
  }
  function setStatPanel(open) {
    statOpen = open;
    cardNewer = false; cardHeld = false;
    ports.el("statpanel").hidden = !open;
    ports.el("readout").setAttribute("aria-expanded", open ? "true" : "false");
    document.body.classList.toggle("stat-open", open);   /* the Fit button, where it would cover its first rows, waits (ocean.html) */
    /* opening, as a popover does (setPop): never under the charts or a narrow
     * screen's settings sheet; no popover over it; the coach mark goes */
    if (open) {
      if (ports.readouts.dash() && /** @type {OceanDashboard} */ (ports.readouts.dash()).isOpen()) /** @type {OceanDashboard} */ (ports.readouts.dash()).close();
      if (!ports.wideMQ.matches && drawerEl.classList.contains("open")) setDrawer(false);
      setPop(null); ports.tour.hideCoach();
    }
    ports.readouts.dirtyHud = true;
  }
  /* The part of the screen the tank is framed in (renderer.js updateInsets):
   * below the top bar and above the dock on a desktop, the whole screen on
   * compact ones, where the controls float over it; less the open settings. */
  function updateInsets() {
    if (!ports.scene) return;
    var vh = window.innerHeight, open = drawerEl.classList.contains("open");
    var top = 0, bottom = 0, right = 0;
    if (!ports.compactMQ.matches) {
      top = ports.el("topbar").getBoundingClientRect().bottom + 6;
      bottom = vh - ports.el("dock").getBoundingClientRect().top + 6;
    }
    if (open && ports.wideMQ.matches) right = drawerEl.getBoundingClientRect().width;
    else if (open) {
      var sheetTop = drawerEl.getBoundingClientRect().top;
      bottom = sheetTop - top >= vh * 0.3 ? vh - sheetTop : bottom;
    }
    ports.scene.setInsets({ top: Math.round(top), right: Math.round(right), bottom: Math.round(Math.max(0, bottom)), left: 0 });
  }
  /* ---- settings: a bottom sheet on narrow screens, a side panel on wide ones ---- */
  function initDrawer() {
  drawerEl = ports.el("drawer"), menuBtn = ports.el("menubtn");
  }
  function setDrawer(open) {
    if (open && ports.readouts.dash()) /** @type {OceanDashboard} */ (ports.readouts.dash()).close();
    drawerEl.classList.toggle("open", open);
    document.body.classList.toggle("sheet-open", open);
    menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
    if (!open) { hideTip(); ports.setStartMenu(false); if (ports.asking) ports.hideAsk(); }   /* a question no one can see is no question: closing the sheet keeps the run */
    if (open) { setStatPanel(false); setPop(null); ports.tour.hideCoach(); }
    if (ports.scene) { updateInsets(); setTimeout(updateInsets, 320); }
  }
  /* Crossing 960 px (a resize, a rotation): a wide screen lets the settings
   * panel stay beside a popover or the live numbers, a narrow one's sheet
   * would cover them (and hide the dock under the View menu). What opened
   * last stays — a popover or the live numbers, since opening the settings
   * closes both — so the sheet closes, as it would have on this screen
   * (setPop, setStatPanel); the focus, if it was in the sheet, goes to the
   * popover's first control, else to the settings button. */
  function onWideChange() {
    if (!ports.wideMQ.matches && drawerEl.classList.contains("open") && (openPop || statOpen)) {
      var inSheet = drawerEl.contains(document.activeElement);
      setDrawer(false);
      if (inSheet) (openPop ? ports.el(POPS[openPop][2]) : menuBtn).focus();
    }
    placePop();
  }
  function registerDrawer() {
  if (ports.wideMQ.addEventListener) ports.wideMQ.addEventListener("change", onWideChange);
  else if (ports.wideMQ.addListener) ports.wideMQ.addListener(onWideChange);   /* Safari before 14 */
  menuBtn.addEventListener("click", /** @this {HTMLElement} */ function () { setDrawer(!drawerEl.classList.contains("open")); this.blur(); });
  ports.el("drawerclose").addEventListener("click", function () { setDrawer(false); this.blur(); });
  (function () {   /* drag the sheet's grip (or header) down to close it */
    var start = null, grip = ports.el("grip"), head = /** @type {HTMLElement} */ (drawerEl.querySelector(".sheet-head"));
    function down(e) {
      if (ports.wideMQ.matches || /** @type {Element} */ (e.target).closest("button")) return;
      start = { y: e.clientY, id: e.pointerId, dy: 0 };
      drawerEl.classList.add("dragging");
      e.currentTarget.setPointerCapture(e.pointerId);
    }
    function move(e) {
      if (!start || e.pointerId !== start.id) return;
      start.dy = Math.max(0, e.clientY - start.y);
      drawerEl.style.transform = "translateY(" + start.dy + "px)";
    }
    function up(e) {
      if (!start || e.pointerId !== start.id) return;
      drawerEl.classList.remove("dragging");
      drawerEl.style.transform = "";
      if (start.dy > Math.min(120, drawerEl.offsetHeight * 0.25)) setDrawer(false);
      start = null;
    }
    [grip, head].forEach(function (n) {
      n.addEventListener("pointerdown", down); n.addEventListener("pointermove", move);
      n.addEventListener("pointerup", up); n.addEventListener("pointercancel", up);
    });
  })();
  ports.el("readout").addEventListener("click", function () { setStatPanel(!statOpen); this.blur(); });
  document.addEventListener("pointerdown", function (e) {
    if (statOpen && !/** @type {Element} */ (e.target).closest("#statpanel, #readout")) setStatPanel(false);
  });
  }
  /* ---- the shared hover tooltip (renderer.js's) ---- */
  function initTips() {
  tipEl = document.createElement("div");
  tipEl.id = "tooltip";
  tipDesc = document.createElement("div"); tipDesc.className = "tipd";
  tipTry = document.createElement("div"); tipTry.className = "tipt";
  tipEl.appendChild(tipDesc); tipEl.appendChild(tipTry);
  document.body.appendChild(tipEl);
  tipTimer = 0, tipFor = null;
  }
  function hideTip() { clearTimeout(tipTimer); tipEl.style.display = "none"; tipFor = null; }
  function showTip(rowEl, tip) {
    tipDesc.textContent = tip.d; tipTry.textContent = tip.t;
    tipEl.style.display = "block";
    tipFor = rowEl;
    var dr = drawerEl.getBoundingClientRect(), lr = rowEl.getBoundingClientRect(), left, top;
    if (ports.wideMQ.matches && dr.left >= tipEl.offsetWidth + 16) {
      left = Math.max(6, dr.left - 10 - tipEl.offsetWidth);
      top = lr.top + lr.height / 2 - tipEl.offsetHeight / 2;
    } else {
      left = Math.max(8, Math.min(lr.left, window.innerWidth - tipEl.offsetWidth - 8));
      top = lr.bottom + 4;
      if (top + tipEl.offsetHeight > window.innerHeight - 6) top = lr.top - 4 - tipEl.offsetHeight;
    }
    top = Math.max(6, Math.min(top, window.innerHeight - tipEl.offsetHeight - 6));
    tipEl.style.left = left + "px"; tipEl.style.top = top + "px";
  }
  function attachTip(rowEl, key) {
    var tip = ports.CFG.TIPS[key];
    if (!tip || !rowEl) return;
    rowEl.addEventListener("mouseenter", function () {
      if (ports.lastPointer !== "mouse") return;
      clearTimeout(tipTimer);
      tipTimer = setTimeout(function () { showTip(rowEl, tip); }, 200);
    });
    rowEl.addEventListener("mouseleave", function () { if (ports.lastPointer === "mouse") hideTip(); });
    var name = rowEl.querySelector(".lt");
    if (name) name.addEventListener("click", function (e) {
      if (ports.lastPointer === "mouse") return;
      e.preventDefault();
      if (tipFor === rowEl) hideTip(); else showTip(rowEl, tip);
    });
  }
  function registerTips() {
  ports.panelsEl.addEventListener("scroll", hideTip);
  document.addEventListener("pointerdown", function (e) {
    if (tipFor && e.pointerType !== "mouse" && !(/** @type {Element} */ (e.target).closest && /** @type {Element} */ (e.target).closest(".lt"))) hideTip();
  });
  }
  return {
    initPop: initPop,
    registerPopOutside: registerPopOutside,
    initStats: initStats,
    initDrawer: initDrawer,
    registerDrawer: registerDrawer,
    initTips: initTips,
    registerTips: registerTips,
    setPop: setPop,
    closePop: closePop,
    togglePop: togglePop,
    placePop: placePop,
    setStatPanel: setStatPanel,
    updateInsets: updateInsets,
    setDrawer: setDrawer,
    onWideChange: onWideChange,
    hideTip: hideTip,
    showTip: showTip,
    attachTip: attachTip,
    get POPS() { return POPS; },
    get openPop() { return openPop; },
    get statOpen() { return statOpen; },
    get drawerEl() { return drawerEl; },
    get cardNewer() { return cardNewer; }, set cardNewer(v) { cardNewer = v; },
    get cardHeld() { return cardHeld; }, set cardHeld(v) { cardHeld = v; }
  };
  }
  window.EvoOceanLayers = { create: create };
})();

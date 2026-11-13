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
 * ui_common.css holds the styles that go with these (a tab's focus ring). */
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

  /** @type {EvoUIApi} */
  var API = {
    keyboardFocused: keyboardFocused, pressedByKeyboard: pressedByKeyboard, pointerBlur: pointerBlur,
    typingIn: typingIn, ownsKey: ownsKey, tabIndexFor: tabIndexFor, tabs: tabs, returnPoint: returnPoint
  };
  root.EvoUI = API;
})(typeof window !== "undefined" ? window : globalThis);

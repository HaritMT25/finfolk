"use strict";
/* evo_boids module loader — picks the threaded or the single-threaded build.
 *
 * The pthreads module (evo_boids_mt.*) needs SharedArrayBuffer, which browsers
 * only expose to a cross-origin-isolated page (served with
 * Cross-Origin-Opener-Policy: same-origin + Cross-Origin-Embedder-Policy:
 * require-corp; see vercel.json). Anywhere else — a plain static server, or an
 * iframe inside a page without those headers — it falls back to the
 * single-threaded module, which is also the reproducible one.
 *
 * ?threads=0 forces the single-threaded module even when isolation is on.
 *
 * Asset URLs come from window.EVO_ASSETS (set in index.html; the deploy build
 * rewrites it with content-hashed names). They are resolved to absolute URLs
 * here so the Turbo worker and the pthread workers, which live at other paths,
 * load the same files. */
(function () {
  var A = window.EVO_ASSETS;

  function abs(u) { return new URL(u, location.href).href; }

  /* Both modules are built with WebAssembly SIMD (-msimd128, wasm/wasm.cmake),
   * so a browser without it can't compile either. Check first, so the page
   * can say what is missing instead of showing a compile error. This module,
   * one function returning a v128 (i8x16.splat, i8x16.popcnt), validates only
   * where SIMD is supported. */
  var SIMD_PROBE = new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0, 1, 5, 1, 96, 0, 1, 123, 3, 2, 1, 0,
                                   10, 10, 1, 8, 0, 65, 0, 253, 15, 253, 98, 11]);
  function simdSupport() {
    try { return typeof WebAssembly === "object" && WebAssembly.validate(SIMD_PROBE); }
    catch (e) { return false; }
  }

  function threadSupport() {
    var q = new URLSearchParams(location.search).get("threads");
    if (q === "0") return { ok: false, why: "forced single-threaded (?threads=0)" };
    if (self.crossOriginIsolated !== true) return { ok: false, why: "page not cross-origin isolated" };
    if (typeof SharedArrayBuffer === "undefined") return { ok: false, why: "no SharedArrayBuffer" };
    return { ok: true, why: "cross-origin isolated" };
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = function () { reject(new Error("could not load " + src)); };
      document.head.appendChild(s);
    });
  }

  /* createEvoBoids options shared by the page and the Turbo worker. */
  function moduleOptions(js, wasm) {
    return {
      locateFile: function (path) { return path.slice(-5) === ".wasm" ? wasm : path; },
      mainScriptUrlOrBlob: js /* pthread workers load this same script */
    };
  }

  function flavor(threaded) {
    return threaded ? { threaded: true, js: abs(A.mt), wasm: abs(A.mtWasm) }
                    : { threaded: false, js: abs(A.st), wasm: abs(A.stWasm) };
  }

  /* Both module scripts define the same global factory, so a failed threaded
   * load is followed by a fresh <script> for the single-threaded one. */
  function load(f) {
    return loadScript(f.js).then(function () {
      return createEvoBoids(moduleOptions(f.js, f.wasm));
    });
  }

  window.EvoLoader = {
    moduleOptions: moduleOptions,
    /* Threads the threaded module can run: its pre-spawned workers plus the
     * calling thread. MUST match -sPTHREAD_POOL_SIZE in wasm/wasm.cmake
     * (min(hardwareConcurrency, 8) - 1 workers); asking for more aborts. */
    poolThreads: function () {
      return Math.min((self.navigator || {}).hardwareConcurrency || 4, 8);
    },
    /* -> Promise<{Module, threaded, why, js, wasm}> */
    load: function () {
      if (!simdSupport())   /* (noSimd: the page offers no other world, the Ocean needs SIMD too) */
        return Promise.reject(Object.assign(new Error("this browser has no WebAssembly SIMD, which the simulation " +
                                                      "needs (Chrome 91+, Firefox 89+ or Safari 16.4+)"), { noSimd: true }));
      var t = threadSupport();
      var f = flavor(t.ok);
      return load(f).then(function (m) {
        return { Module: m, threaded: f.threaded, why: t.why, js: f.js, wasm: f.wasm };
      }, function (err) {
        if (!f.threaded) throw err;
        var st = flavor(false);
        return load(st).then(function (m) {
          return { Module: m, threaded: false, why: "threaded build failed to start (" + err + ")",
                   js: st.js, wasm: st.wasm };
        });
      });
    }
  };
})();

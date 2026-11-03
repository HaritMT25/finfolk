"use strict";
/* evo_boids 3-D Ocean: the module-memory helpers the page (web/ocean.js) and
 * the Turbo worker (web/ocean_worker.js) share, so the hand-off has one
 * implementation; tests/ocean_turbo_handoff.js runs them in node against two
 * real module instances.
 *
 * The Turbo hand-off is the module's whole linear memory (web/ocean_worker.js
 * says why a byte copy carries the run on exactly). take() puts an image into
 * a module: it grows the memory to the image's size first, with
 * WebAssembly.Memory.grow (the module exports wasmMemory) by exactly the
 * pages missing, so it never depends on how much free space the receiver's
 * allocator happens to have (growing "through malloc" could be satisfied from
 * free space, or grow too little, and the hand-off then failed), copies the
 * image in and zeroes whatever lies past it, as fresh pages are.
 *
 * A grow from outside leaves the module's own cached views (its HEAPU8 and
 * co., which UTF8ToString / stringToUTF8 read) on the old, detached buffer
 * until its next growth of its own (emscripten_resize_heap renews them). So
 * nothing here, in the page or in the worker reads them: every view is cut
 * from the live buffer (buffer(M)) at the moment it is used, and cString /
 * withCString do their own UTF-8. (The module's other users of those views —
 * the C++ throw path, fatal in this build, and random_get, which only the
 * rng's construction at start-up calls — never run after a hand-off.)
 *
 * The page's controls call exports that allocate (oc_summary, oc_families,
 * oc_inspect, oc_wiring, oc_sensor_names, ...), and any allocation can grow the
 * memory, which detaches every view cut before it. f64 / f32 take the
 * buffer inside, after their arguments (the export's call among them) have
 * run, and copy the numbers out, so a growth can't strand them.
 *
 * Also here, so the tests run the page's own logic: ledger(), the page's live
 * edits around a Turbo session and what it applies when the world comes back
 * (or doesn't); parseFirst() / cfgJson(), the engine's rule for a repeated
 * JSON key on the page's way in (?cfg=, a setup file); encodeWorld() /
 * decodeWorld(), the world file (Save world: the memory image, with a
 * header, to disk and back). */
(function (root) {
  var PAGE = 65536;
  var enc = typeof TextEncoder !== "undefined" ? new TextEncoder() : null;
  var dec = typeof TextDecoder !== "undefined" ? new TextDecoder("utf-8") : null;

  /* the module's memory as it is now (never cache it across a call) */
  function buffer(M) { return M.wasmMemory ? M.wasmMemory.buffer : M.HEAPU8.buffer; }

  /* Grow M's memory to at least `bytes`: by exactly the pages missing, with
   * wasmMemory.grow; without an exported memory, through the allocator (a
   * block of `bytes` ends past `bytes`, so it must grow that far). Returns
   * whether the memory is now that big. */
  function growTo(M, bytes) {
    var have = buffer(M).byteLength;
    if (have >= bytes) return true;
    if (M.wasmMemory && typeof M.wasmMemory.grow === "function") {
      try { M.wasmMemory.grow(Math.ceil((bytes - have) / PAGE)); } catch (e) { /* out of address space */ }
    } else {
      var p = M._malloc(bytes);
      if (p) M._free(p);
    }
    return buffer(M).byteLength >= bytes;
  }

  /* Put a whole memory image (an ArrayBuffer, page-sized) into M. Throws, with
   * M's memory as it was (grown, perhaps, never overwritten), when it can't
   * grow far enough; the caller still holds the image. */
  function take(M, src, who) {
    var need = src.byteLength, have = buffer(M).byteLength;
    if (!need || need % PAGE) throw new Error("not a memory image: " + need + " bytes");
    if (!growTo(M, need))
      throw new Error("could not grow " + (who || "the") + " memory to " + need + " bytes (it has " + buffer(M).byteLength + ")");
    var dst = new Uint8Array(buffer(M));
    dst.set(new Uint8Array(src));
    /* past the image: zero, as fresh pages are (pages this grew already are) */
    if (have > need) dst.fill(0, need, have);
  }

  /* a C string at ptr, read from the live buffer */
  function cString(M, ptr) {
    if (!ptr) return "";
    var h = new Uint8Array(buffer(M)), end = ptr;
    while (end < h.length && h[end]) end++;
    if (dec) return dec.decode(h.subarray(ptr, end));
    var s = "";
    for (var i = ptr; i < end; i++) s += String.fromCharCode(h[i]);
    return s;
  }
  /* fn(ptr) with str as a temporary C string (0 for an empty one) */
  function withCString(M, str, fn) {
    if (str === null || str === undefined || str === "") return fn(0);
    str = String(str);
    var bytes;
    if (enc) bytes = enc.encode(str);
    else { bytes = new Uint8Array(str.length); for (var i = 0; i < str.length; i++) bytes[i] = str.charCodeAt(i) & 255; }
    var ptr = M._malloc(bytes.length + 1);
    if (!ptr) throw new Error("out of module memory");
    var h = new Uint8Array(buffer(M));   /* after the malloc: it may have grown the memory */
    h.set(bytes, ptr);
    h[ptr + bytes.length] = 0;
    try { return fn(ptr); } finally { M._free(ptr); }
  }

  /* len doubles / floats at ptr, copied out. Call it with the export inline,
   * f64(M, M._oc_summary(), M._oc_summary_len()): the buffer is taken here,
   * after the export ran. */
  function f64(M, ptr, len) { return Array.prototype.slice.call(new Float64Array(buffer(M), ptr, len)); }
  function f32(M, ptr, len) { return Array.prototype.slice.call(new Float32Array(buffer(M), ptr, len)); }

  /* One dashboard sample of a synced world (web/ocean_dash.js row()): the
   * stats first (copied before anything allocates), then the summary, then
   * the family lines. statsLen: oc_stats_len(). */
  function row(M, famK, statsLen) {
    var st = f64(M, M._oc_stats(), statsLen);
    var su = f64(M, M._oc_summary(), M._oc_summary_len());
    var k = M._oc_families(famK);
    return { st: st, su: su, fam: f64(M, M._oc_families_data(), 2 * k) };
  }

  /* ---- the page's live edits around a Turbo session (web/ocean.js) ----
   * Every edit gets a sequence number, and is held (neither side owns the
   * world: Turbo is starting or stopping), in flight (sent to the worker, not
   * answered yet) or acknowledged (the worker applied it). back(lost), when
   * the page owns the world again, is what the page must apply, in the order
   * the edits were made: the unanswered and held ones; and, when the
   * worker's world is lost (the page goes on from its own copy, from where
   * Turbo took it), the acknowledged ones first, so that edits which depend
   * on each other (minSpeed 200 only after maxSpeed 300) apply in the order
   * the worker applied them. A newer edit of a key always lands after an
   * older one, never under it. Every held edit is kept, not only the newest
   * of its key: a later setting can depend on an earlier value (minSpeed 0,
   * maxSpeed 10, minSpeed 5 from 30-150 holds only as that sequence; without
   * the first, maxSpeed 10 is refused against 30). Entries: {key, num, seq,
   * from: "acked" | "sent" | "held"}. */
  function ledger() {
    var seq = 0, held = [], inflight = [], acked = [];
    function byseq(a, b) { return a.seq - b.seq; }
    return {
      /* a new Turbo session: nothing in flight, nothing acknowledged yet */
      start: function () { inflight = []; acked = []; },
      /* an edit made while neither side owns the world (every one, in order) */
      hold: function (key, num) { held.push({ key: key, num: num, seq: ++seq, from: "held" }); },
      /* an edit sent to the worker; seq: a held edit's own, when it is flushed */
      sent: function (key, num, s) { inflight.push({ key: key, num: num, seq: s === undefined ? ++seq : s, from: "sent" }); },
      /* the worker's answer to the oldest in-flight edit of key (it answers in order) */
      answered: function (key, ok) {
        for (var i = 0; i < inflight.length; i++) if (inflight[i].key === key) {
          var e = inflight.splice(i, 1)[0];
          if (ok) acked.push({ key: e.key, num: e.num, seq: e.seq, from: "acked" });
          return e;
        }
        return null;
      },
      /* an edit of key newer than sequence number afterSeq (any, without it)
       * still waits: in flight, or held for the hand-off. The answer to an
       * older edit must not undo it (the page's field shows it) */
      pending: function (key, afterSeq) {
        var s = afterSeq === undefined ? 0 : afterSeq;
        return inflight.concat(held).some(function (e) { return e.key === key && e.seq > s; });
      },
      /* the newest edit of key still on its way (in flight or held), or null:
       * what the page's field shows when a newer edit of it is refused */
      latest: function (key) {
        var best = null;
        inflight.concat(held).forEach(function (e) { if (e.key === key && (!best || e.seq > best.seq)) best = e; });
        return best;
      },
      /* the held edits, oldest first, now that one side owns the world */
      takeHeld: function () { var l = held; held = []; return l; },
      /* the page owns the world again: what it applies, oldest first */
      back: function (lost) {
        var l = (lost ? acked : []).concat(inflight, held).sort(byseq);
        held = []; inflight = []; acked = [];
        return l;
      },
      /* the held edits as {key: its newest value} (EvoOcean.state); never what is applied */
      held: function () { var o = {}; held.forEach(function (e) { o[e.key] = e.num; }); return o; },
      inflight: function () { return inflight.map(function (e) { return [e.key, e.num]; }); }
    };
  }

  /* ---- JSON from outside the sheet (?cfg=, a setup file) ----
   * The engine reads a repeated key's FIRST occurrence (src/core/json_min.hpp
   * find) and checks every occurrence (ocean_config.hpp readOceanJson);
   * JSON.parse keeps the LAST, so {"toroidal":false,"toroidal":true} ran one
   * way on the page and the other in oc_init, and {"toroidal":1,"toroidal":
   * true} slipped past both checks. parseFirst is JSON.parse (the same syntax
   * check and error, the same values) with the engine's rule: a repeated
   * key's first occurrence is the value, and every later one is listed in
   * repeats [{path, key, value}] (path: the keys / indices down to its
   * object), so the caller can check it and hand it on. cfgJson writes a cfg
   * object for oc_init with those later occurrences after it, so oc_init sees
   * (and checks) every occurrence and takes the same first one. */
  function parseFirst(text) {
    JSON.parse(text);   /* the syntax check, and its message */
    var i = 0, repeats = [];
    function ws() { while (i < text.length && " \t\n\r".indexOf(text.charAt(i)) >= 0) i++; }
    function str() {
      var s = i++;
      while (text.charAt(i) !== '"') i += text.charAt(i) === "\\" ? 2 : 1;
      i++;
      return JSON.parse(text.slice(s, i));
    }
    function val(path) {
      ws();
      var c = text.charAt(i), k, v;
      if (c === "{") {
        var o = {}, seen = Object.create(null);
        i++; ws();
        if (text.charAt(i) === "}") { i++; return o; }
        for (;;) {
          ws(); k = str(); ws(); i++;   /* the ':' */
          v = val(path.concat([k]));
          if (seen[k]) repeats.push({ path: path, key: k, value: v });
          else { seen[k] = true; Object.defineProperty(o, k, { value: v, enumerable: true, writable: true, configurable: true }); }
          ws();
          if (text.charAt(i++) === ",") continue;
          return o;
        }
      }
      if (c === "[") {
        var a = [];
        i++; ws();
        if (text.charAt(i) === "]") { i++; return a; }
        for (;;) {
          a.push(val(path.concat([a.length])));
          ws();
          if (text.charAt(i++) === ",") continue;
          return a;
        }
      }
      if (c === '"') return str();
      var s = i;
      while (i < text.length && ",}] \t\n\r".indexOf(text.charAt(i)) < 0) i++;
      return JSON.parse(text.slice(s, i));
    }
    return { value: val([]), repeats: repeats };
  }
  /* a cfg object as oc_init's JSON ("" for nothing), the later occurrences of
   * its repeated keys ([{key, value}], parseFirst's at its level) after it.
   * A number too big for a double (1e400) parses to ±Infinity, which
   * JSON.stringify writes as null: {"maxPopulation":300,"maxPopulation":1e400}
   * reached oc_init as ...:null, which its whole-number check passes over.
   * So an infinity goes on as a number that is one in oc_init too (±1e400):
   * the engine checks every occurrence, of every key, as it does its own
   * JSON. Everything else is written as JSON.stringify writes it. (The
   * values are JSON's: from JSON.parse / parseFirst, or the sheet's.) */
  function literal(v) {
    if (v === Infinity) return "1e400";
    if (v === -Infinity) return "-1e400";
    if (typeof v === "number" && v !== v) throw new Error("NaN is not a JSON value");
    var none = function (x) { return x === undefined || typeof x === "function"; };   /* as JSON.stringify skips them */
    if (Array.isArray(v)) return "[" + v.map(function (x) { return none(x) ? "null" : literal(x); }).join(",") + "]";
    if (v && typeof v === "object")
      return "{" + Object.keys(v).filter(function (k) { return !none(v[k]); })
                     .map(function (k) { return JSON.stringify(k) + ":" + literal(v[k]); }).join(",") + "}";
    return JSON.stringify(v);
  }
  function cfgJson(cfg, repeats) {
    var keys = Object.keys(cfg || {}), more = repeats || [];
    if (!keys.length && !more.length) return "";
    var s = literal(cfg || {});
    more.forEach(function (r) { s = s.slice(0, -1) + (s.length > 2 ? "," : "") + JSON.stringify(r.key) + ":" + literal(r.value) + "}"; });
    return s;
  }

  /* ---- the world file (web/ocean.js Save world; From a file opens it) ----
   * The running world itself, every fish, the food, the rng and the frame:
   * the module's whole memory image, the one the Turbo hand-off moves (so a
   * world opened from a file carries on bit for bit where it was saved), with
   * a small JSON header in front. Layout:
   *   16 bytes   WORLD.MAGIC, "evo_ocean_world\n"
   *    4 bytes   n, the header's length in bytes (little-endian)
   *    n bytes   the header: UTF-8 JSON, {format: "evo_ocean_world",
   *              version: 1, ..., image: {bytes, stored, sha256, body,
   *              bodyBytes}} (the page writes the rest: web/ocean.js
   *              worldHeader)
   *    the rest  the body: the image's first `stored` bytes, gzip-compressed
   *              (CompressionStream; body "gzip") or as they are ("raw", a
   *              browser without it). The image is `bytes` long (whole wasm
   *              pages); past `stored` it is zeros (memory never written:
   *              trimmed, not saved). sha256: of those `stored` bytes.
   * decodeWorld checks every part of that before anything is put into a
   * module: the magic, the version, the lengths (a file cut short, or with
   * bytes after its end, is refused), the gzip stream (a damaged one throws)
   * and the checksum. Which engine build may take the image is the page's
   * question (header.engine): an image belongs to one build of the module. */
  var WORLD = { MAGIC: "evo_ocean_world\n", FORMAT: "evo_ocean_world", VERSION: 1, EXT: ".oceanworld", MAX_HEADER: 1 << 22 };
  function ascii(s) { var b = new Uint8Array(s.length); for (var i = 0; i < s.length; i++) b[i] = s.charCodeAt(i) & 255; return b; }
  function utf8(s) { return enc ? enc.encode(s) : ascii(s); }
  function fromUtf8(u8) { if (dec) return dec.decode(u8); var s = ""; for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]); return s; }
  /* bytes of an ArrayBuffer or a view, never copied (isView: a view from another realm too) */
  function u8of(x) { return ArrayBuffer.isView(x) ? new Uint8Array(x.buffer, x.byteOffset, x.byteLength) : new Uint8Array(x); }
  /* a file's first bytes are a world file's magic */
  function isWorldFile(head) {
    var h = u8of(head), m = WORLD.MAGIC;
    if (h.length < m.length) return false;
    for (var i = 0; i < m.length; i++) if (h[i] !== m.charCodeAt(i)) return false;
    return true;
  }

  /* SHA-256, hex: the browser's (crypto.subtle: a secure context, https or
   * localhost) or, without it, sha256js (the same digest, in JS) */
  var K256 = [0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01,
              0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
              0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
              0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
              0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08,
              0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
              0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2];
  function hex(words) { var s = ""; for (var i = 0; i < words.length; i++) s += ("0000000" + (words[i] >>> 0).toString(16)).slice(-8); return s; }
  function sha256js(data) {
    var u8 = u8of(data), n = u8.length, Hs = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    var Wd = new Int32Array(64);
    function block(p, o) {
      var i, a = Hs[0], b = Hs[1], c = Hs[2], d = Hs[3], e = Hs[4], f = Hs[5], g = Hs[6], h = Hs[7];
      for (i = 0; i < 16; i++) Wd[i] = (p[o + 4 * i] << 24) | (p[o + 4 * i + 1] << 16) | (p[o + 4 * i + 2] << 8) | p[o + 4 * i + 3];
      for (i = 16; i < 64; i++) {
        var x = Wd[i - 15], y = Wd[i - 2];
        var s0 = ((x >>> 7) | (x << 25)) ^ ((x >>> 18) | (x << 14)) ^ (x >>> 3);
        var s1 = ((y >>> 17) | (y << 15)) ^ ((y >>> 19) | (y << 13)) ^ (y >>> 10);
        Wd[i] = (Wd[i - 16] + s0 + Wd[i - 7] + s1) | 0;
      }
      for (i = 0; i < 64; i++) {
        var S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
        var t1 = (h + S1 + ((e & f) ^ (~e & g)) + K256[i] + Wd[i]) | 0;
        var S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
        var t2 = (S0 + ((a & b) ^ (a & c) ^ (b & c))) | 0;
        h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      Hs[0] = (Hs[0] + a) | 0; Hs[1] = (Hs[1] + b) | 0; Hs[2] = (Hs[2] + c) | 0; Hs[3] = (Hs[3] + d) | 0;
      Hs[4] = (Hs[4] + e) | 0; Hs[5] = (Hs[5] + f) | 0; Hs[6] = (Hs[6] + g) | 0; Hs[7] = (Hs[7] + h) | 0;
    }
    var full = Math.floor(n / 64), k;
    for (k = 0; k < full; k++) block(u8, 64 * k);
    var rest = n - 64 * full, tail = new Uint8Array(rest + 9 > 64 ? 128 : 64);
    tail.set(u8.subarray(64 * full));
    tail[rest] = 0x80;
    var hi = Math.floor(n / 0x20000000), lo = (n % 0x20000000) * 8, L = tail.length;   /* the length in bits, big-endian */
    tail[L - 8] = hi >>> 24; tail[L - 7] = hi >>> 16; tail[L - 6] = hi >>> 8; tail[L - 5] = hi;
    tail[L - 4] = lo >>> 24; tail[L - 3] = lo >>> 16; tail[L - 2] = lo >>> 8; tail[L - 1] = lo;
    for (k = 0; k < L; k += 64) block(tail, k);
    return hex(Hs);
  }
  function sha256(data) {
    var u8 = u8of(data), c = root.crypto;
    if (c && c.subtle && typeof c.subtle.digest === "function")
      return c.subtle.digest("SHA-256", u8).then(function (d) {
        var v = new DataView(d), w = [];
        for (var i = 0; i < 8; i++) w.push(v.getUint32(4 * i));
        return hex(w);
      });
    return new Promise(function (resolve) { resolve(sha256js(u8)); });
  }
  /* the image without its zero tail: the bytes up to the last one not zero
   * (whole 4-byte words; an image is whole wasm pages) */
  function storedLength(image) {
    var u8 = u8of(image), w = new Uint32Array(u8.buffer, u8.byteOffset, u8.byteLength >>> 2), i = w.length - 1;
    while (i >= 0 && w[i] === 0) i--;
    return 4 * (i + 1);
  }
  /* a stream's chunks (CompressionStream / DecompressionStream), into fn(chunk) */
  function through(stream, u8, fn) {
    var w = stream.writable.getWriter(), r = stream.readable.getReader();
    w.write(u8).catch(function () { /* the reader reports it */ });
    w.close().catch(function () { /* the reader reports it */ });
    return (function pump() {
      return r.read().then(function (x) { if (x.done) return; fn(x.value); return pump(); });
    })();
  }
  function canGzip() { return typeof root.CompressionStream === "function" && typeof root.DecompressionStream === "function"; }
  /* A world file of `header` (a JSON object: the page's) and `image` (an
   * ArrayBuffer: a whole memory image). opts.raw: no compression (as a
   * browser without CompressionStream writes it). Answers {parts (for a
   * Blob), header (with its image record), size}. */
  function encodeWorld(header, image, opts) {
    var u8 = new Uint8Array(image);
    if (!u8.length || u8.length % PAGE) return Promise.reject(new Error("not a memory image: " + u8.length + " bytes"));
    var stored = storedLength(image), body = u8.subarray(0, stored), gzip = !(opts && opts.raw) && typeof root.CompressionStream === "function";
    return sha256(body).then(function (sum) {
      if (!gzip) return [sum, [body]];
      var chunks = [];
      return through(new root.CompressionStream("gzip"), body, function (c) { chunks.push(c); }).then(function () { return [sum, chunks]; });
    }).then(function (r) {
      var bodyBytes = 0;
      r[1].forEach(function (c) { bodyBytes += c.length; });
      var h = JSON.parse(JSON.stringify(header));
      h.image = { bytes: u8.length, stored: stored, sha256: r[0], body: gzip ? "gzip" : "raw", bodyBytes: bodyBytes };
      var hb = utf8(JSON.stringify(h)), len = new Uint8Array(4);
      new DataView(len.buffer).setUint32(0, hb.length, true);
      var parts = [ascii(WORLD.MAGIC), len, hb].concat(r[1]);
      return { parts: parts, header: h, size: WORLD.MAGIC.length + 4 + hb.length + bodyBytes };
    });
  }
  /* why a file is not a world file this page reads, or "" (its first bytes) */
  function notAWorld(u8) {
    var s = fromUtf8(u8.subarray(0, Math.min(u8.length, 4096))).replace(/^﻿?\s*/, "");
    if (s.charAt(0) === "{" && /"format"\s*:\s*"evo_ocean_setup"/.test(s)) return "That file is a setup (Save setup makes those), not a saved world.";
    return "That file is not a saved world (Save world makes those).";
  }
  /* A world file's header, checked: {header, at (where its body starts)}.
   * Throws an Error whose message says why it is not one this page reads.
   * Only the header: decodeWorld checks the body. */
  function worldHeader(file) {
    var u8 = u8of(file), m = WORLD.MAGIC.length;
    if (!isWorldFile(u8)) throw new Error(notAWorld(u8));
    if (u8.length < m + 4) throw new Error("That world file is cut short: it ends inside its header.");
    var n = new DataView(u8.buffer, u8.byteOffset + m, 4).getUint32(0, true);
    if (n < 2 || n > WORLD.MAX_HEADER) throw new Error("That world file is damaged: its header length (" + n + " bytes) is not a header's.");
    if (u8.length < m + 4 + n) throw new Error("That world file is cut short: it ends inside its header (" + u8.length + " of at least " + (m + 4 + n) + " bytes).");
    var h;
    try { h = JSON.parse(fromUtf8(u8.subarray(m + 4, m + 4 + n))); } catch (e) { throw new Error("That world file is damaged: its header is not JSON (" + e.message + ")."); }
    if (!h || typeof h !== "object" || h.format !== WORLD.FORMAT) throw new Error("That file is not a saved world (Save world makes those).");
    if (h.version !== WORLD.VERSION)
      throw new Error("That world file is version " + JSON.stringify(h.version) + "; this page reads version " + WORLD.VERSION + ".");
    var im = h.image, whole = function (v) { return typeof v === "number" && Number.isInteger(v) && v >= 0; };
    if (!im || typeof im !== "object" || !whole(im.bytes) || !im.bytes || im.bytes % PAGE || !whole(im.stored) || im.stored > im.bytes ||
        im.stored % 4 || !whole(im.bodyBytes) || (im.body !== "gzip" && im.body !== "raw") || typeof im.sha256 !== "string" ||
        !/^[0-9a-f]{64}$/.test(im.sha256) || (im.body === "raw" && im.bodyBytes !== im.stored))
      throw new Error("That world file is damaged: its header does not describe a memory image.");
    return { header: h, at: m + 4 + n };
  }
  /* A world file, checked whole: {header, image (an ArrayBuffer, the whole
   * memory image)}, or a rejected Promise whose Error says why not. */
  function decodeWorld(file) {
    var u8 = u8of(file), r;
    try { r = worldHeader(u8); } catch (e) { return Promise.reject(e); }
    var im = r.header.image, have = u8.length - r.at;
    if (have < im.bodyBytes)
      return Promise.reject(new Error("That world file is cut short: it has " + u8.length + " of its " + (r.at + im.bodyBytes) + " bytes (it was not saved or copied whole)."));
    if (have > im.bodyBytes)
      return Promise.reject(new Error("That world file is damaged: it has " + (have - im.bodyBytes) + " bytes after its end."));
    var body = u8.subarray(r.at), image = new ArrayBuffer(im.bytes), dst = new Uint8Array(image), at = 0, over = false;
    var filled;
    if (im.body === "raw") { dst.set(body); filled = Promise.resolve(); at = body.length; }
    else if (typeof root.DecompressionStream !== "function")
      return Promise.reject(new Error("This browser can't decompress a world file (it has no DecompressionStream: Chrome 80+, Firefox 113+, Safari 16.4+)."));
    else filled = through(new root.DecompressionStream("gzip"), body, function (c) {
      if (at + c.length > im.stored) { over = true; throw new Error("longer"); }
      dst.set(c, at); at += c.length;
    }).catch(function (e) {
      if (over) throw new Error("That world file is damaged: its world is longer than its header says.");
      throw new Error("That world file is damaged or cut short: its compressed world does not unpack (" + (e && e.message || e) + ").");
    });
    return filled.then(function () {
      if (at !== im.stored) throw new Error("That world file is cut short: its world unpacks to " + at + " of " + im.stored + " bytes.");
      return sha256(dst.subarray(0, im.stored));
    }).then(function (sum) {
      if (sum !== im.sha256) throw new Error("That world file is damaged: its world does not match its checksum.");
      return { header: r.header, image: image };
    });
  }

  var api = { PAGE: PAGE, buffer: buffer, growTo: growTo, take: take, cString: cString,
              withCString: withCString, f64: f64, f32: f32, row: row,
              ledger: ledger, parseFirst: parseFirst, cfgJson: cfgJson,
              WORLD: WORLD, isWorldFile: isWorldFile, sha256: sha256, sha256js: sha256js, storedLength: storedLength,
              canGzip: canGzip, encodeWorld: encodeWorld, worldHeader: worldHeader, decodeWorld: decodeWorld };
  root.EvoOceanHandoff = api;
  if (typeof module === "object" && module && module.exports) module.exports = api;   /* node: the tests */
})(typeof self !== "undefined" ? self : typeof window !== "undefined" ? window : globalThis);

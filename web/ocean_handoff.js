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

  /* Put a whole memory image (an ArrayBuffer or a view, page-sized) into M.
   * full: the image's length when src is only its first bytes (a world file
   * stores the image without its zero tail): the rest of it is zeros. Throws,
   * with M's memory as it was (grown, perhaps, never overwritten), when it
   * can't grow far enough; the caller still holds the image. */
  function take(M, src, who, full) {
    var s = u8of(src), need = full === undefined ? s.length : full, have = buffer(M).byteLength;
    if (!Number.isSafeInteger(need) || !need || need % PAGE || s.length > need)
      throw new Error("not a memory image: " + s.length + (full === undefined ? "" : " of " + need) + " bytes");
    if (!growTo(M, need))
      throw new Error("could not grow " + (who || "the") + " memory to " + need + " bytes (it has " + buffer(M).byteLength + ")");
    var dst = new Uint8Array(buffer(M));
    dst.set(s);
    /* past the image's bytes: zero, as fresh pages are (pages this grew already are) */
    if (have > s.length) dst.fill(0, s.length, have);
  }
  /* bytes of an ArrayBuffer or a view, never copied (isView: a view from another realm too) */
  function u8of(x) { return ArrayBuffer.isView(x) ? new Uint8Array(x.buffer, x.byteOffset, x.byteLength) : new Uint8Array(x); }

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
   *              bodyBytes}, sha256} (the page writes the rest: web/ocean.js
   *              worldHeader; headerProblem says what it must be)
   *    the rest  the body: the image's first `stored` bytes, gzip-compressed
   *              (CompressionStream; body "gzip") or as they are ("raw", a
   *              browser without it). The image is `bytes` long (whole wasm
   *              pages); past `stored` it is zeros (memory never written:
   *              trimmed, not saved).
   * Two checksums, SHA-256 both: image.sha256 of the `stored` bytes, and the
   * header's own sha256 of WORLD.DIGEST followed by the header itself in
   * its canonical form (canon: JSON, object keys sorted, no spaces; its own
   * sha256 left out), image record (and so the image's checksum) included.
   * So no field of the header (a setting, the frame, the image's lengths)
   * can change without the file being refused as damaged. They detect
   * corruption; they don't say who wrote the file.
   * readWorld checks the parts in the order they are read, each before
   * anything bigger is read or allocated: the file's size, the magic, the
   * header's length, the header (JSON, its shape, the image record and the
   * limits below), the file's exact length, the header's checksum; then
   * (body(), when the caller wants the world) the body, unpacked into
   * exactly `stored` bytes (more is refused at once and the stream
   * cancelled), and the image's checksum. Which engine build may take the
   * image is the page's question (header.engine): an image belongs to one
   * build of the module.
   *
   * The limits (worldLimits), every one checked before the bytes it
   * bounds are read or allocated, every length a safe integer:
   *   the image (image.bytes) at most the engine's own maximum memory (its
   *     wasm memory section, wasmMemoryMax: 2 GiB in this build) and at
   *     most MAX_IMAGE, 512 MiB, what a page opens: the largest world the
   *     page can start (100,000 fish, the population limit) uses 185 MiB,
   *     the Big tank 16 to 32 MiB; opening one holds the stored bytes, the
   *     receiving module's memory and the run's own copy (startWorld's
   *     undo) at once, about 1.5 GB at the cap, which a desktop browser
   *     allows;
   *   the stored bytes at most the image; a raw body exactly them, a gzip
   *     body at most maxBody (zlib's deflate bound is 0.03 % over; this
   *     allows 0.1 % and 4 kB) and at least 1/RATIO of them (deflate can't
   *     unpack more than 1032 bytes from one: a small file can't ask for a
   *     big image);
   *   the header at most MAX_HEADER, 1 MiB (a header is 2 to 15 kB: the
   *     settings three times), 8 levels deep and 20,000 values;
   *   the file at most its prefix, the biggest header and the biggest
   *     body: checked from its size, before a byte of it is read;
   *   the body read READ_PART (4 MiB) at a time into one buffer, once the
   *     page's turn has come (readWorld's body()): a read superseded
   *     meanwhile stops at its next part.
   * Those are the format's. A page also has its device's (worldLimits'
   * deviceBytes, web/ocean.js deviceBudget): a smaller image cap on a
   * device with less memory, and a budget for everything an open holds at
   * once (the run, Turbo's copy, the stored bytes, the test run's module,
   * the undo), checked before the body is read; Save world writes nothing
   * the same limits would refuse.
   * A setup file (JSON) is at most MAX_SETUP, 1 MiB (Save setup's are 1 to
   * 3 kB). */
  var MiB = 1048576;
  var WORLD = { MAGIC: "evo_ocean_world\n", FORMAT: "evo_ocean_world", VERSION: 1, EXT: ".oceanworld", PREFIX: 20,
                MAX_HEADER: MiB, MAX_IMAGE: 512 * MiB, MAX_SETUP: MiB, MAX_DEPTH: 8, MAX_VALUES: 20000, RATIO: 1032,
                READ_PART: 4 * MiB, DIGEST: "evo_ocean_world 1\n" };
  function ascii(s) { var b = new Uint8Array(s.length); for (var i = 0; i < s.length; i++) b[i] = s.charCodeAt(i) & 255; return b; }
  function utf8(s) { return enc ? enc.encode(s) : ascii(s); }
  function fromUtf8(u8) { if (dec) return dec.decode(u8); var s = ""; for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]); return s; }
  function noop() { /* a rejection reported elsewhere */ }
  function mb(n) { return (n / MiB).toFixed(n < 10 * MiB ? 2 : 0) + " MB"; }
  /* the biggest gzip body of `stored` bytes this reads (raw: exactly them) */
  function maxBody(stored, kind) { return kind === "raw" ? stored : stored + Math.ceil(stored / 1000) + 4096; }
  /* the limits a page opens (and saves) world files under; engineBytes: its
   * module's own maximum memory (wasmMemoryMax); deviceBytes: what this
   * device opens (web/ocean.js deviceBudget: less on a small one) */
  function worldLimits(engineBytes, deviceBytes) {
    var engine = Number.isSafeInteger(engineBytes) && engineBytes > 0 ? engineBytes : 65536 * PAGE;
    var format = Math.min(engine, WORLD.MAX_IMAGE), device = Number.isSafeInteger(deviceBytes) && deviceBytes > 0 ? deviceBytes : format;
    return { engine: engine, format: format, device: device, image: Math.min(format, device), header: WORLD.MAX_HEADER,
             file: WORLD.PREFIX + WORLD.MAX_HEADER + maxBody(WORLD.MAX_IMAGE, "gzip") };
  }
  /* A wasm module's maximum memory in bytes, from its bytes (its memory
   * section, or an imported memory): 4 GiB when it declares none, null for
   * bytes that aren't a wasm32 module with one memory this can read. */
  function wasmMemoryMax(bytes) {
    var u8 = u8of(bytes), at = { i: 8 };
    function leb() {
      var r = 0, mul = 1, b;
      do { if (at.i >= u8.length || mul > 0x10000000) throw new Error("bad LEB128"); b = u8[at.i++]; r += (b & 127) * mul; mul *= 128; } while (b & 128);
      return r;
    }
    /* limits: flags, the minimum, the maximum when flag 1 says there is one (flag 4: a 64-bit memory, not read) */
    function limits() { var f = leb(); leb(); var max = f & 1 ? leb() : 65536; return (f & 4) ? null : max * PAGE; }
    try {
      if (u8.length < 8 || u8[0] !== 0 || u8[1] !== 0x61 || u8[2] !== 0x73 || u8[3] !== 0x6d) return null;
      while (at.i < u8.length) {
        var id = u8[at.i++], size = leb(), end = at.i + size;
        if (id === 5) { if (leb() < 1) return null; return limits(); }
        if (id === 2) {
          for (var k = leb(), j = 0; j < k; j++) {
            var len = leb(); at.i += len; len = leb(); at.i += len;   /* the module and field names (a length, then its bytes) */
            var kind = u8[at.i++];
            if (kind === 0) leb();
            else if (kind === 1) { at.i++; limits(); }
            else if (kind === 2) return limits();
            else if (kind === 3) at.i += 2;
            else if (kind === 4) { at.i++; leb(); }
            else return null;
          }
        }
        at.i = end;
      }
    } catch (e) { return null; }
    return null;
  }
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
  /* a stream's chunks (CompressionStream / DecompressionStream), into fn(chunk);
   * fn throwing (more than was asked for), or cancelled() true (the read is
   * superseded: a newer file, a start), cancels the stream: nothing more is
   * unpacked */
  function through(stream, u8, fn, cancelled) {
    var w = stream.writable.getWriter(), r = stream.readable.getReader();
    w.write(u8).catch(noop);   /* (the reader reports it) */
    w.close().catch(noop);
    return (function pump() {
      return r.read().then(function (x) {
        if (x.done) return;
        try {
          if (cancelled && cancelled()) throw new Error(CANCELLED);
          fn(x.value);
        } catch (e) { r.cancel(e).catch(noop); throw e; }
        return pump();
      });
    })();
  }
  var CANCELLED = "superseded: a newer file or start took its place";
  function canGzip() { return typeof root.CompressionStream === "function" && typeof root.DecompressionStream === "function"; }

  /* JSON in its one canonical form (the header's checksum is of this): object
   * keys sorted (UTF-16 code units), no spaces, numbers and strings as
   * JSON.stringify writes them; a value JSON has no form for throws */
  function canon(v) {
    if (v === null) return "null";
    if (typeof v === "boolean") return v ? "true" : "false";
    if (typeof v === "number") { if (!isFinite(v)) throw new Error("a number JSON can't hold"); return JSON.stringify(v); }
    if (typeof v === "string") return JSON.stringify(v);
    if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]";
    if (typeof v === "object") return "{" + Object.keys(v).sort().map(function (k) { return JSON.stringify(k) + ":" + canon(v[k]); }).join(",") + "}";
    throw new Error("a value JSON can't hold");
  }
  /* the header's own checksum: of WORLD.DIGEST and its canonical form, its sha256 left out */
  function headerDigest(h) {
    var c = {};
    Object.keys(h).forEach(function (k) { if (k !== "sha256") c[k] = h[k]; });
    return sha256(utf8(WORLD.DIGEST + canon(c)));
  }
  /* h with its checksum (the tests and a file made by hand: the page writes it in encodeWorld) */
  function sealHeader(h) {
    var c = JSON.parse(JSON.stringify(h));
    delete c.sha256;
    return headerDigest(c).then(function (d) { c.sha256 = d; return c; });
  }
  /* a parsed header no deeper and no bigger than a world's (canon and the checks recurse into it) */
  function shapeOk(h) {
    var stack = [[h, 1]], values = 0;
    while (stack.length) {
      var e = stack.pop(), v = e[0];
      if (++values > WORLD.MAX_VALUES || e[1] > WORLD.MAX_DEPTH) return false;
      if (v && typeof v === "object") (Array.isArray(v) ? v : Object.keys(v).map(function (k) { return v[k]; })).forEach(function (x) { stack.push([x, e[1] + 1]); });
    }
    return true;
  }

  /* A world file of `header` (a JSON object: the page's) and `image` (an
   * ArrayBuffer or a view: a whole memory image). opts.raw: no compression
   * (as a browser without CompressionStream writes it); opts.limits: the
   * reader's (worldLimits; the format's without): an image it would refuse
   * is not written. Answers {parts (for a Blob), header (with its image
   * record and checksum), size}. */
  function encodeWorld(header, image, opts) {
    var u8 = u8of(image), L = opts && opts.limits || worldLimits();
    if (!u8.length || u8.length % PAGE) return Promise.reject(new Error("not a memory image: " + u8.length + " bytes"));
    if (u8.length > L.image) return Promise.reject(new Error("its memory (" + mb(u8.length) + ") is more than a world file holds (" + mb(L.image) + " at most), so it could not be opened again"));
    var stored = storedLength(u8), body = u8.subarray(0, stored), gzip = !(opts && opts.raw) && typeof root.CompressionStream === "function";
    return sha256(body).then(function (sum) {
      if (!gzip) return [sum, [body]];
      var chunks = [];
      return through(new root.CompressionStream("gzip"), body, function (c) { chunks.push(c); }).then(function () { return [sum, chunks]; });
    }).then(function (r) {
      var bodyBytes = 0;
      r[1].forEach(function (c) { bodyBytes += c.length; });
      var h = JSON.parse(JSON.stringify(header));
      delete h.sha256;
      h.image = { bytes: u8.length, stored: stored, sha256: r[0], body: gzip ? "gzip" : "raw", bodyBytes: bodyBytes };
      return headerDigest(h).then(function (d) {
        h.sha256 = d;
        var hb = utf8(JSON.stringify(h)), len = new Uint8Array(4);
        if (hb.length > WORLD.MAX_HEADER) throw new Error("its header would be " + hb.length + " bytes, more than a world file's " + WORLD.MAX_HEADER);
        new DataView(len.buffer).setUint32(0, hb.length, true);
        var parts = [ascii(WORLD.MAGIC), len, hb].concat(r[1]);
        return { parts: parts, header: h, size: WORLD.PREFIX + hb.length + bodyBytes };
      });
    });
  }
  /* why a file is not a world file this page reads, or "" (its first bytes) */
  function notAWorld(u8) {
    var s = fromUtf8(u8.subarray(0, Math.min(u8.length, 4096))).replace(/^﻿?\s*/, "");
    if (s.charAt(0) === "{" && /"format"\s*:\s*"evo_ocean_setup"/.test(s)) return "That file is a setup (Save setup makes those), not a saved world.";
    return "That file is not a saved world (Save world makes those).";
  }
  /* the image record: "" or why not (its limits L: worldLimits) */
  function imageProblem(im, L) {
    var whole = function (v) { return Number.isSafeInteger(v) && v >= 0; };
    var bad = "That world file is damaged: its header does not describe a memory image.";
    if (!im || typeof im !== "object" || Array.isArray(im) || !whole(im.bytes) || !im.bytes || im.bytes % PAGE) return bad;
    if (im.bytes > L.engine) return "That saved world needs " + mb(im.bytes) + " of memory, more than this engine build can have (" + mb(L.engine) + ").";
    if (im.bytes > L.format) return "That saved world needs " + mb(im.bytes) + " of memory, more than this page opens (" + mb(L.format) + " at most).";
    if (im.bytes > L.image) return "That saved world needs " + mb(im.bytes) + " of memory, more than this device opens (" + mb(L.image) + " at most here).";
    if (!whole(im.stored) || im.stored > im.bytes || im.stored % 4 || (im.body !== "gzip" && im.body !== "raw") || !whole(im.bodyBytes) ||
        typeof im.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(im.sha256) || Object.keys(im).length !== 5) return bad;
    if (im.body === "raw" ? im.bodyBytes !== im.stored : im.bodyBytes > maxBody(im.stored, "gzip") || im.stored > WORLD.RATIO * im.bodyBytes + 4096)
      return "That world file is damaged: its body (" + im.bodyBytes + " bytes, " + im.body + ") can't hold the " + im.stored + " bytes its header says.";
    return "";
  }
  /* the header's bytes, parsed and checked as a world file's (not its checksum: readWorld) */
  function parseHeader(hb, L) {
    var h;
    try { h = JSON.parse(fromUtf8(hb)); } catch (e) { throw new Error("That world file is damaged: its header is not JSON (" + e.message + ")."); }
    if (!h || typeof h !== "object" || Array.isArray(h) || h.format !== WORLD.FORMAT) throw new Error("That file is not a saved world (Save world makes those).");
    if (h.version !== WORLD.VERSION)
      throw new Error("That world file is version " + JSON.stringify(h.version) + "; this page reads version " + WORLD.VERSION + ".");
    if (!shapeOk(h)) throw new Error("That world file is damaged: its header is nested deeper or holds more than a world's.");
    if (typeof h.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(h.sha256)) throw new Error("That world file is damaged: its header has no checksum.");
    var why = imageProblem(h.image, L);
    if (why) throw new Error(why);
    return h;
  }
  /* sources readWorld reads from: a Blob (a File: only the parts asked for are read) or bytes */
  function blobSource(b) {
    return { size: b.size, read: function (a, z) { return b.slice(a, z).arrayBuffer().then(function (x) { return new Uint8Array(x); }); } };
  }
  function bytesSource(x) { var u8 = u8of(x); return { size: u8.length, read: function (a, z) { return Promise.resolve(u8.subarray(a, z)); } }; }
  /* A world file, read part by part (src: blobSource / bytesSource; L:
   * worldLimits): {header, at (where the body starts), body()}, the header
   * checked whole (its checksum too) before the body is read; body()
   * reads, unpacks and checks it: {data (the image's stored bytes), bytes
   * (its full length)}. A rejection's Error says why the file isn't one. */
  function readWorld(src, L) {
    L = L || worldLimits();
    var size = src.size, m = WORLD.MAGIC.length;
    if (!Number.isSafeInteger(size) || size < 0) return Promise.reject(new Error("That file can't be read (its size is unknown)."));
    if (size > L.file) return Promise.reject(new Error("That file is " + mb(size) + ", more than any saved world this page opens (" + mb(L.file) + ")."));
    var first = Math.min(size, 4096), n = 0;
    return src.read(0, first).then(function (head) {
      if (!isWorldFile(head)) throw new Error(notAWorld(head));
      if (size < WORLD.PREFIX) throw new Error("That world file is cut short: it ends inside its header.");
      n = new DataView(head.buffer, head.byteOffset + m, 4).getUint32(0, true);
      if (n < 2 || n > L.header) throw new Error("That world file is damaged: its header length (" + n + " bytes) is not a header's.");
      if (size < WORLD.PREFIX + n) throw new Error("That world file is cut short: it ends inside its header (" + size + " of at least " + (WORLD.PREFIX + n) + " bytes).");
      return WORLD.PREFIX + n <= head.length ? head.subarray(WORLD.PREFIX, WORLD.PREFIX + n) : src.read(WORLD.PREFIX, WORLD.PREFIX + n);
    }).then(function (hb) {
      var h = parseHeader(hb, L), at = WORLD.PREFIX + n, want = at + h.image.bodyBytes;
      if (size < want) throw new Error("That world file is cut short: it has " + size + " of its " + want + " bytes (it was not saved or copied whole).");
      if (size > want) throw new Error("That world file is damaged: it has " + (size - want) + " bytes after its end.");
      return headerDigest(h).then(function (d) {
        if (d !== h.sha256) throw new Error("That world file is damaged: its header does not match its checksum.");
        /* body(cancelled, turn): turn(), a Promise to wait for before any of the body is read (the
         * page's one at a time: a read waiting for its turn holds no body; review of #44, round 3,
         * finding 2); cancelled() true (a superseded read) stops it at once: before each part it is
         * read in (the first: when its turn comes), while a part is on its way (a slow disk: it lets
         * the turn go, that part's bytes dropped when they come), at the unpacking's next chunk */
        return { header: h, at: at, body: function (cancelled, turn) {
          return (turn ? turn() : Promise.resolve()).then(function () {
            return readParts(src, at, size, cancelled);
          }).then(function (b) { return unpack(h, b, cancelled); });
        } };
      });
    });
  }
  /* bytes [a, z) of src, READ_PART at a time into one buffer (one part: as
   * read); cancelled() true stops it before a part and while one is on its
   * way (looked at every 50 ms) */
  function readParts(src, a, z, cancelled) {
    var part = WORLD.READ_PART;
    if (z - a <= part) return readPart(src, a, z, cancelled);
    var out = new Uint8Array(z - a), at = a;
    return (function next() {
      if (at >= z) return out;
      var e = Math.min(z, at + part);
      return readPart(src, at, e, cancelled).then(function (b) {
        if (b.length !== e - at) throw new Error("That world file is cut short: it ended while its world was read.");
        out.set(b, at - a);
        at = e;
        return next();
      });
    })();
  }
  function readPart(src, a, z, cancelled) {
    if (!cancelled) return src.read(a, z);
    if (cancelled()) return Promise.reject(new Error(CANCELLED));
    return new Promise(function (resolve, reject) {
      var watch = setInterval(function () { if (cancelled()) { clearInterval(watch); reject(new Error(CANCELLED)); } }, 50);
      src.read(a, z).then(function (b) { clearInterval(watch); resolve(b); }, function (e) { clearInterval(watch); reject(e); });
    });
  }
  /* a body into the image's stored bytes, checked: {data, bytes} */
  function unpack(h, body, cancelled) {
    var im = h.image, filled;
    if (body.length !== im.bodyBytes) return Promise.reject(new Error("That world file is cut short: its body is " + body.length + " of " + im.bodyBytes + " bytes."));
    if (cancelled && cancelled()) return Promise.reject(new Error(CANCELLED));
    if (im.body === "raw") filled = Promise.resolve(body);   /* the stored bytes themselves */
    else if (typeof root.DecompressionStream !== "function")
      return Promise.reject(new Error("This browser can't decompress a world file (it has no DecompressionStream: Chrome 80+, Firefox 113+, Safari 16.4+)."));
    else {
      var data = new Uint8Array(im.stored), at = 0, over = false;
      filled = through(new root.DecompressionStream("gzip"), body, function (c) {
        if (at + c.length > im.stored) { over = true; throw new Error("longer"); }
        data.set(c, at); at += c.length;
      }, cancelled).then(function () {
        if (at !== im.stored) throw new Error("That world file is cut short: its world unpacks to " + at + " of " + im.stored + " bytes.");
        return data;
      }, function (e) {
        if (over) throw new Error("That world file is damaged: its world is longer than its header says.");
        if (e && e.message === CANCELLED) throw e;
        throw new Error("That world file is damaged or cut short: its compressed world does not unpack (" + (e && e.message || e) + ").");
      });
    }
    return filled.then(function (d) {
      return sha256(d).then(function (sum) {
        if (sum !== im.sha256) throw new Error("That world file is damaged: its world does not match its checksum.");
        return { data: d, bytes: im.bytes };
      });
    });
  }
  /* A world file's header, from its bytes (Uint8Array), without the
   * checksum (readWorld checks that): {header, at}. Throws why not. */
  function worldHeader(file, L) {
    var u8 = u8of(file), m = WORLD.MAGIC.length;
    if (!isWorldFile(u8)) throw new Error(notAWorld(u8));
    if (u8.length < WORLD.PREFIX) throw new Error("That world file is cut short: it ends inside its header.");
    var n = new DataView(u8.buffer, u8.byteOffset + m, 4).getUint32(0, true);
    if (n < 2 || n > WORLD.MAX_HEADER || u8.length < WORLD.PREFIX + n) throw new Error("That world file is damaged or cut short: its header length is " + n + " bytes.");
    return { header: parseHeader(u8.subarray(WORLD.PREFIX, WORLD.PREFIX + n), L || worldLimits()), at: WORLD.PREFIX + n };
  }
  /* A world file, checked whole (bytes): {header, data, bytes}, or a rejected Promise whose Error says why not */
  function decodeWorld(file, L) {
    return readWorld(bytesSource(file), L).then(function (r) {
      return r.body().then(function (img) { return { header: r.header, data: img.data, bytes: img.bytes }; });
    });
  }
  /* the image whole (data, then zeros to `bytes`), as an ArrayBuffer (the tests compare it) */
  function wholeImage(w) { var b = new Uint8Array(w.bytes); b.set(w.data); return b.buffer; }

  /* ---- a saved world's header, checked against itself (web/ocean.js; the tests) ----
   * Strict: every field a world file has, of its type and in its range, no
   * other; the settings flat (a name, a number or an on / off value of the
   * type the sheet's field has); only the live settings differ between the
   * setup it started from (start.cfg) and its settings when saved (runCfg);
   * its setup record is that start with those settings (Save setup's
   * file). R: {keys: CFG.KEYS, live: CFG.LIVE, lim: CFG.SIZE_LIMITS,
   * setupVersion}. "" or why not. */
  var START_KEYS = ["seed", "population", "depth", "width", "height", "cfg"];
  var TOP_KEYS = ["format", "version", "app", "saved", "engine", "frame", "fish", "food", "predators", "start", "runCfg", "setup", "picked", "image", "sha256"];
  var SETUP_KEYS = ["format", "version", "seed", "population", "depth", "width", "height", "walls", "config"];
  function headerProblem(h, R) {
    var obj = function (o) { return !!o && typeof o === "object" && !Array.isArray(o); };
    var whole = function (v, lo, hi) { return Number.isSafeInteger(v) && v >= lo && v <= hi; };
    var fin = function (v) { return typeof v === "number" && isFinite(v); };
    var only = function (o, keys) { return Object.keys(o).every(function (k) { return keys.indexOf(k) >= 0; }); };
    var BIG = Number.MAX_SAFE_INTEGER, NAME = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/, lim = R.lim, args = { seed: 1, population: 1, depth: 1, width: 1, height: 1 };
    function settings(c, what) {
      if (!obj(c)) return what + " are not a list of settings";
      var ks = Object.keys(c);
      if (ks.length > 512) return what + " are " + ks.length + " settings";
      for (var i = 0; i < ks.length; i++) {
        var k = ks[i], v = c[k], d = R.keys[k];
        if (!NAME.test(k) || args[k]) return what + " have a setting named " + JSON.stringify(k.slice(0, 40));
        if (d ? (typeof d[0] === "boolean" ? typeof v !== "boolean" : !fin(v)) : !(fin(v) || typeof v === "boolean"))
          return what + " have " + k + " " + (typeof v === "string" ? "as text" : Array.isArray(v) ? "as a list" : obj(v) ? "as a record" : JSON.stringify(v));
      }
      return "";
    }
    if (!obj(h) || !only(h, TOP_KEYS)) return "its header has a field a world file has not";
    if (h.app !== undefined && !(typeof h.app === "string" && h.app.length <= 200)) return "its header's app is not a name";
    if (h.saved !== undefined && !(typeof h.saved === "string" && h.saved.length <= 64)) return "its header's time is not one";
    var e = h.engine;
    if (!obj(e) || !only(e, ["module", "wasmSha256", "eye"]) || e.module !== "evo_ocean" || typeof e.wasmSha256 !== "string" ||
        !/^[0-9a-f]{64}$/.test(e.wasmSha256) || typeof e.eye !== "boolean") return "its engine record is not one";
    if (!whole(h.frame, 0, BIG)) return "its frame (" + JSON.stringify(h.frame) + ") is not a whole number";
    if (!whole(h.fish, 0, BIG) || !whole(h.food, 0, BIG) || !whole(h.predators, 0, BIG)) return "its counts of fish, food and predators are not whole numbers";
    var s = h.start;
    if (!obj(s) || !only(s, START_KEYS) || !whole(s.seed, 0, 4294967295) || !whole(s.population, lim.population[0], lim.population[1]) ||
        !fin(s.depth) || s.depth < lim.depth[0] || s.depth > lim.depth[1] || !whole(s.width, lim.side[0], lim.side[1]) || !whole(s.height, lim.side[0], lim.side[1]))
      return "its start (the setup it began from) is not one";
    var why = settings(s.cfg, "its start's settings") || settings(h.runCfg, "its settings");
    if (why) return why;
    var all = Object.keys(s.cfg).concat(Object.keys(h.runCfg));
    for (var i = 0; i < all.length; i++) {
      var k = all[i];
      if (!R.live[k] && s.cfg[k] !== h.runCfg[k]) return "its settings change " + k + ", which only a new start can";
    }
    var u = h.setup, wallsNow = h.runCfg.walls !== undefined ? h.runCfg.walls === true : !!(R.keys.walls && R.keys.walls[0]);
    if (!obj(u) || !only(u, SETUP_KEYS) || u.format !== "evo_ocean_setup" || u.version !== R.setupVersion || u.seed !== s.seed ||
        u.population !== s.population || u.depth !== s.depth || u.width !== s.width || u.height !== s.height || u.walls !== wallsNow || !obj(u.config))
      return "its setup is not this world's";
    var cfgNow = {};
    Object.keys(h.runCfg).forEach(function (k) { if (k !== "walls") cfgNow[k] = h.runCfg[k]; });
    if (canon(u.config) !== canon(cfgNow)) return "its setup's settings are not this world's";
    var p = h.picked;
    if (p !== null && !(obj(p) && only(p, ["id", "follow", "family", "x", "y", "d"]) && whole(p.id, 0, BIG) && typeof p.follow === "boolean" &&
                        (p.family === undefined || p.family === null || fin(p.family)) &&
                        ["x", "y", "d"].every(function (k) { return p[k] === undefined || fin(p[k]); })))
      return "its picked fish is not one";
    return "";
  }

  /* ---- a module's world, read and checked (the page after it opens a world; the probe) ----
   * worldNow: oc_sync, then the world's numbers, every export's buffer
   * inside the memory (aligned, its length the counts'), the frame a whole
   * number, the ids and the fish's segments finite. Throws why not (a
   * module whose image is not a world: a null world reads 0 × 0). */
  function worldNow(M) {
    M._oc_sync();
    var len = buffer(M).byteLength;
    var r = { w: M._oc_width(), h: M._oc_height(), d: M._oc_depth_max(), fish: M._oc_creature_count(), food: M._oc_food_count(),
              pred: M._oc_predator_count(), walls: typeof M._oc_walls_enabled === "function" ? !!M._oc_walls_enabled() : false, frame: -1 };
    var statsLen = M._oc_stats_len();
    [["fish", r.fish], ["food", r.food], ["predators", r.pred], ["stats", statsLen]].forEach(function (c) {
      if (!Number.isSafeInteger(c[1]) || c[1] < 0 || c[1] > len) throw new Error("its count of " + c[0] + " is " + c[1]);
    });
    if (!(r.w > 0 && r.h > 0 && r.d > 0 && isFinite(r.w) && isFinite(r.h) && isFinite(r.d))) throw new Error("it holds no world (its tank is " + r.w + " × " + r.h + " × " + r.d + ")");
    function view(ptr, n, size, what) {
      ptr = ptr >>> 0;
      if (n && (!ptr || ptr % size || ptr + n * size > len)) throw new Error("its " + what + " lie outside its memory");
    }
    var n = r.fish, fc = r.food, pc = r.pred;
    view(M._oc_stats(), statsLen, 8, "stats");
    view(M._oc_creature_segments(), n * 12, 4, "fish");
    view(M._oc_creature_depth(), n, 4, "fish depths");
    if (typeof M._oc_creature_vz === "function") view(M._oc_creature_vz(), n, 4, "fish climbs");
    view(M._oc_body_params(), n * 2, 4, "bodies");
    view(M._oc_creature_colors(), n * 3, 1, "colours");
    view(M._oc_creature_ids(), n, 8, "ids");
    view(M._oc_food_xy(), fc * 2, 4, "food");
    view(M._oc_food_depth(), fc, 4, "food depths");
    view(M._oc_predator_data(), pc * 3, 4, "predators");
    view(M._oc_predator_depth(), pc, 4, "predator depths");
    if (typeof M._oc_creature_appearance === "function" && typeof M._oc_appearance_count === "function") {
      var ac = M._oc_appearance_count();
      if (!Number.isSafeInteger(ac) || ac < 0 || ac > len) throw new Error("its count of appearance rows is " + ac);
      if (ac) view(M._oc_creature_appearance(), ac * M._oc_appearance_stride(), 4, "appearance rows");
    }
    var st = f64(M, M._oc_stats(), statsLen);
    r.frame = st[1];
    if (!Number.isSafeInteger(r.frame) || r.frame < 0) throw new Error("its frame is " + r.frame);
    var ids = new Float64Array(buffer(M), M._oc_creature_ids() >>> 0, n), segs = new Float32Array(buffer(M), M._oc_creature_segments() >>> 0, n * 12), i;
    for (i = 0; i < n; i++) if (!isFinite(ids[i])) throw new Error("a fish's id is " + ids[i]);
    for (i = 0; i < 12 * n; i++) if (!isFinite(segs[i])) throw new Error("a fish's place is " + segs[i]);
    return r;
  }
  /* what a world file's header says its world is (worldNow's terms) */
  function worldExpect(h) {
    return { w: h.setup.width, h: h.setup.height, d: h.start.depth, frame: h.frame, fish: h.fish, food: h.food, pred: h.predators,
             walls: h.setup.walls, picked: !!h.picked };
  }
  /* "" or how a module's world (worldNow) differs from the one expected */
  function worldMismatch(a, e) {
    if (a.w !== e.w || a.h !== e.h || Math.fround(a.d) !== Math.fround(e.d))
      return "its tank is " + a.w + " × " + a.h + " × " + a.d + ", not the " + e.w + " × " + e.h + " × " + e.d + " its header says";
    if (a.frame !== e.frame) return "it is at frame " + a.frame + ", not the " + e.frame + " its header says";
    if (a.fish !== e.fish || a.food !== e.food || a.pred !== e.pred)
      return "it has " + a.fish + " fish, " + a.food + " food and " + a.pred + " predators, not the " + e.fish + ", " + e.food + " and " + e.pred + " its header says";
    if (a.walls !== e.walls) return "its sides are " + (a.walls ? "glass walls" : "wrapping") + ", not as its header says";
    return "";
  }
  /* A saved world tried in a module of its own (web/ocean_worker.js "probe":
   * a worker made for it, terminated after): the image in, checked against
   * its header (expect: worldExpect), the calls the page makes on a world
   * it opens (the display switches, the readout's summary, the charts'
   * family lines, a fish card), one step, checked again. {ok, at (its
   * worldNow before the step), why}. A trap throws (the caller says so). */
  function probeWorld(M, data, bytes, expect) {
    take(M, data, "the test module's", bytes);
    var a = worldNow(M), why = worldMismatch(a, expect);
    if (why) return { ok: false, why: why };
    if (typeof M._oc_set_colour_mode === "function") M._oc_set_colour_mode(1);
    if (typeof M._oc_set_capture === "function") M._oc_set_capture(expect.picked ? 1 : 0);
    if (typeof M._oc_summary === "function") f64(M, M._oc_summary(), M._oc_summary_len());
    if (typeof M._oc_families === "function") { var k = M._oc_families(8); f64(M, M._oc_families_data(), 2 * k); }
    if (a.fish && typeof M._oc_inspect === "function" && M._oc_inspect(0)) f64(M, M._oc_inspect_info(), M._oc_inspect_len());
    M._oc_step(1);
    var b = worldNow(M);
    if (b.frame !== a.frame + 1) return { ok: false, why: "one step took it from frame " + a.frame + " to " + b.frame };
    if (b.w !== a.w || b.h !== a.h || b.d !== a.d) return { ok: false, why: "one step changed its tank" };
    return { ok: true, at: a };
  }

  var api = { PAGE: PAGE, buffer: buffer, growTo: growTo, take: take, cString: cString,
              withCString: withCString, f64: f64, f32: f32, row: row,
              ledger: ledger, parseFirst: parseFirst, cfgJson: cfgJson,
              WORLD: WORLD, isWorldFile: isWorldFile, sha256: sha256, sha256js: sha256js, storedLength: storedLength,
              canGzip: canGzip, encodeWorld: encodeWorld, worldHeader: worldHeader, decodeWorld: decodeWorld, wholeImage: wholeImage,
              worldLimits: worldLimits, wasmMemoryMax: wasmMemoryMax, maxBody: maxBody, canon: canon, headerDigest: headerDigest, sealHeader: sealHeader,
              readWorld: readWorld, blobSource: blobSource, bytesSource: bytesSource, headerProblem: headerProblem,
              worldNow: worldNow, worldExpect: worldExpect, worldMismatch: worldMismatch, probeWorld: probeWorld, CANCELLED: CANCELLED };
  root.EvoOceanHandoff = api;
  if (typeof module === "object" && module && module.exports) module.exports = api;   /* node: the tests */
})(typeof self !== "undefined" ? self : typeof window !== "undefined" ? window : globalThis);

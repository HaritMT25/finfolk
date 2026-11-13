// @ts-check
"use strict";
/* evo_boids 3-D Ocean: the appearance fish's gene slots (window.EvoAppearanceSlots).
 *
 * The renderer keeps every fish's 63 appearance genes (oc_creature_appearance's
 * row, web/ocean_appearance.js) in one RGBA32F texture, 16 texels (64 floats:
 * the genes and one zero) a fish, 512 texels a row: 32 fish a row. Before
 * render PR2 a fish's genes sat at its draw index and the whole texture was
 * packed and uploaded every frame. Here a fish owns a slot, keyed by its id
 * and the world's epoch (web/ocean.js: a new world starts the ids over, Turbo
 * keeps them), for as long as it lives: its genes are copied once, when it is
 * first seen, and uploaded once; a frame whose fish are the ones of the last
 * frame copies and uploads nothing. The draw order is free (the vertex stage
 * reads the slot from the instance attribute iGeneSlot): survivors keep their
 * slot through compaction, reordering, Turbo and quality changes.
 *
 * The one owner of slot ownership (the scene asks it; nothing else assigns or
 * frees a slot). A store:
 *   prepare(epoch, ids, rows, n, outSlots) -> result (one reused object):
 *       one complete snapshot: n fish, ids[c] (a nonnegative safe integer, kept
 *       as a JS number: never truncated or put in a float32), rows (63 floats a
 *       fish), outSlots[c] gets fish c's slot. A new epoch first forgets every
 *       owner (resetOwnership). Every input is checked, and the storage the
 *       births need is checked against the limit, before anything is installed
 *       or released (a bad n, short arrays, an unsafe or repeated id, more
 *       slots than maxCapacity: ok false, error, no owner added, none
 *       released). Then the owners absent from the snapshot are released
 *       (before any birth is placed), the storage grows if the births need it
 *       (powers of two from 256; the survivors keep their slots and data), and
 *       each new fish gets a slot (the lowest free one: births cluster at the
 *       bottom, so their uploads take few ranges; then the high-water mark),
 *       its 63 floats copied and the zero after them written, and the slot
 *       marked dirty. result: {ok, error,
 *       n, newRows (rows copied), released, grew, migratedBytes (the copy of the
 *       old storage on growth), changed (some outSlots[c] differs from what it
 *       held), hasBarbels (some owner has barbels: row[barbelGene] >
 *       barbelMin, cached per owner)}
 *   verify(ids, rows, n, k) -> null, or the first difference found: after a
 *       prepare of these, k owners in turn (a rotating cursor over the draws)
 *       compared with their snapshot rows. A row is copied once, on the
 *       assumption that a fish's genes never change under its id and epoch
 *       (the engine's rows are immutable); this watches that assumption at a
 *       cost of k x 63 compares a frame (the scene invalidates and reinstalls
 *       on a difference)
 *   plan() -> null (nothing to upload: no dirty slot and no full upload due),
 *       or {full, reason, ranges, slots, bytes, calls, clock, capacity}: full,
 *       the whole storage (reason "storage": new GPU storage, the first, a
 *       growth, a restored context; "bytes": more than an eighth of the
 *       storage is dirty; "ranges": the dirty runs would take more than
 *       maxRanges (32) texSubImage2D calls, e.g. a Turbo hand-back's turnover
 *       or a new world); else ranges: maximal runs of dirty slots, split at
 *       every 32-slot row,
 *       as {start, count} in floats (THREE.DataTexture.addUpdateRange's units:
 *       x = (start / 4) % 512, y = floor(start / 2048), width count / 4, one row)
 *   acknowledge(plan): the plan was uploaded (the texture's onUpdate, after
 *       three consumed it): its slots are clean unless written again after the
 *       plan was made (a write clock per slot); a full plan of the current
 *       capacity ends the full upload due. Until then the dirty state stays: a
 *       frame not drawn loses nothing, and the next plan covers it all
 *   requireFull(): the GPU storage is new (a restored context)
 *   resetOwnership(epoch) / invalidate(): forget every owner (the storage and
 *       any full upload due stay)
 *   slotOf(id), stats(), and the storage itself: data (capacity x 64 floats),
 *       capacity.
 * Owner hooks (opts.onGrow / onReset / onRelease / onInstall; none given: nothing is called): the render
 * caches that are keyed by slot (the LOD's hysteresis, the decoded gene constants of render-LOD PR) are kept
 * in step with the owners here and nowhere else: onInstall(slot, data, offset, id) once per new owner, after its
 * row and padding were written (never for a fish that stays, nor on a reordered or repeated snapshot),
 * onRelease(slot) when its slot is freed, onReset(epoch) when every owner is forgotten (a new epoch, invalidate),
 * onGrow(capacity) after the storage grew (the survivors' data kept). They run inside prepare(), must not throw
 * and must not call the store.
 * Pure JS (no WebGL): node's tests/ocean_appearance_slots_tests.cjs. Display
 * only: the simulation never reads any of it. */
(function (root) {
  var SLOT_FLOATS = 64, ROW_SLOTS = 32, MIN_CAP = 256, MAX_CAP = 1 << 24, MARK_MAX = 0xFFFFFFFF;

  function grown(a, cap) { var b = new a.constructor(cap); b.set(a); return b; }

  /** a store (types: web/types.d.ts SlotStore) @param {SlotStoreOptions} [opts] @returns {SlotStore} */
  function create(opts) {
    opts = opts || {};
    var STRIDE = opts.stride || 63;
    if (STRIDE > SLOT_FLOATS) throw new Error("a row of " + STRIDE + " floats does not fit a 64-float slot");
    var BARB = opts.barbelGene === undefined ? -1 : opts.barbelGene, BARB_MIN = opts.barbelMin === undefined ? 0.2 : opts.barbelMin;
    var maxCap = Math.min(MAX_CAP, opts.maxCapacity || MAX_CAP), MAX_RANGES = opts.maxRanges || 32;
    /* the owner hooks (render caches keyed by slot): absent, nothing is called */
    var onGrow = opts.onGrow, onReset = opts.onReset, onRelease = opts.onRelease, onInstall = opts.onInstall;

    var S = /** @type {SlotStore} (its methods are added below) */ ({
      epoch: undefined, capacity: 0, data: new Float32Array(0),
      needFull: true,       /* the GPU storage needs one whole upload (new, grown, or restored) */
      dirtyCount: 0, size: 0, nextSlot: 0,
      allocs: 0             /* storage allocations (growths) */
    });
    var byId = new Map();                     /* id -> slot */
    var slotId = new Float64Array(0), owned = new Uint8Array(0), mark = new Uint32Array(0);
    var barb = new Uint8Array(0), dirty = new Uint8Array(0), wtime = new Float64Array(0);
    var free = new Int32Array(0), freeN = 0, barbCount = 0, M = 0, wclock = 0, outStale = false;
    var newIdx = new Int32Array(256), slotTmp = new Int32Array(256), newSet = new Set();
    var res = { ok: false, error: "", n: 0, newRows: 0, released: 0, grew: false, migratedBytes: 0, changed: false, hasBarbels: false };

    function nextMark() {
      if (++M >= MARK_MAX) { mark.fill(0); M = 1; }
      return M;
    }
    function setDirty(s) {
      wtime[s] = ++wclock;
      if (!dirty[s]) { dirty[s] = 1; S.dirtyCount++; }
    }
    /* the free slots: a binary min-heap in free[0 .. freeN) (the lowest first; deterministic) */
    function freePush(s) {
      var i = freeN++;
      while (i > 0) { var p = (i - 1) >> 1; if (free[p] <= s) break; free[i] = free[p]; i = p; }
      free[i] = s;
    }
    function freePop() {
      var top = free[0], last = free[--freeN], i = 0;
      for (;;) {
        var l = 2 * i + 1;
        if (l >= freeN) break;
        var m = l + 1 < freeN && free[l + 1] < free[l] ? l + 1 : l;
        if (free[m] >= last) break;
        free[i] = free[m]; i = m;
      }
      free[i] = last;
      return top;
    }
    function release(s) {
      byId.delete(slotId[s]);
      owned[s] = 0; barbCount -= barb[s]; barb[s] = 0;
      if (dirty[s]) { dirty[s] = 0; S.dirtyCount--; }   /* its upload is not needed any more */
      freePush(s);
      S.size--;
      if (onRelease) onRelease(s);
    }
    function capFor(need) { var cap = Math.max(MIN_CAP, S.capacity); while (cap < need) cap *= 2; return cap; }
    function grow(need) {
      var cap = capFor(need);
      if (cap > maxCap) return false;
      var d = new Float32Array(cap * SLOT_FLOATS);
      d.set(S.data);
      res.migratedBytes += S.data.byteLength;
      S.data = d;
      slotId = grown(slotId, cap); owned = grown(owned, cap); mark = grown(mark, cap);
      barb = grown(barb, cap); dirty = grown(dirty, cap); wtime = grown(wtime, cap); free = grown(free, cap);
      S.capacity = cap; S.needFull = true; S.allocs++;
      if (onGrow) onGrow(cap);
      return true;
    }
    function resetOwnership(epoch) {
      S.epoch = epoch;
      byId.clear();
      owned.fill(0); barb.fill(0); dirty.fill(0);
      S.dirtyCount = 0; S.size = 0; S.nextSlot = 0; freeN = 0; barbCount = 0;
      outStale = true;   /* every outSlots entry is to be written again */
      if (onReset) onReset(epoch);
    }
    function fail(why) {
      res.ok = false; res.error = why; outStale = true;
      return res;
    }
    function isId(id) { return typeof id === "number" && id >= 0 && id <= Number.MAX_SAFE_INTEGER && Math.floor(id) === id; }

    S.prepare = function (epoch, ids, rows, n, out) {
      res.ok = false; res.error = ""; res.n = n; res.newRows = 0; res.released = 0; res.grew = false; res.migratedBytes = 0;
      res.changed = false; res.hasBarbels = barbCount > 0;
      if (!(typeof n === "number" && n >= 0 && Math.floor(n) === n)) return fail("the fish count " + n + " is not a count");
      if (!ids || !(ids.length >= n)) return fail("fewer ids than fish");
      if (!rows || !(rows.length >= n * STRIDE)) return fail("fewer appearance rows than fish");
      if (out && !(out.length >= n)) return fail("the slot attribute holds fewer than " + n + " fish");
      if (epoch !== S.epoch) resetOwnership(epoch);
      var m = nextMark(), nNew = 0, c, id, s;
      if (newIdx.length < n) { newIdx = new Int32Array(Math.max(256, 2 * n)); slotTmp = new Int32Array(newIdx.length); }
      /* every id checked and marked before anything is installed or released */
      for (c = 0; c < n; c++) {
        id = ids[c];
        if (!isId(id)) { newSet.clear(); return fail("fish " + c + " has the id " + id + ", not a nonnegative safe integer"); }
        s = byId.get(id);
        if (s !== undefined) {
          if (mark[s] === m) { newSet.clear(); return fail("the id " + id + " is in the snapshot twice"); }
          mark[s] = m; slotTmp[c] = s;
        } else {
          if (newSet.has(id)) { newSet.clear(); return fail("the id " + id + " is in the snapshot twice"); }
          newSet.add(id);
          newIdx[nNew++] = c;
        }
      }
      if (nNew) newSet.clear();
      /* the storage the births need (the free slots, those the gone will free, then new ones), within the limit,
       * before anything is released */
      var gone = S.size - (n - nNew), need = S.nextSlot + Math.max(0, nNew - freeN - gone);
      if (need > S.capacity && capFor(need) > maxCap) return fail("the gene storage cannot hold " + need + " slots (at most " + maxCap + ")");
      /* the owners gone, before any birth is placed */
      if (gone > 0) {
        for (s = 0; s < S.nextSlot && n - nNew < S.size; s++) if (owned[s] && mark[s] !== m) { release(s); res.released++; }
      }
      if (need > S.capacity) { grow(need); res.grew = true; }
      var D = S.data;
      for (var k = 0; k < nNew; k++) {
        c = newIdx[k]; id = ids[c];
        s = freeN > 0 ? freePop() : S.nextSlot++;
        byId.set(id, s); slotId[s] = id; owned[s] = 1; mark[s] = m; S.size++; slotTmp[c] = s;
        var o = s * SLOT_FLOATS, r = c * STRIDE;
        for (var j = 0; j < STRIDE; j++) D[o + j] = rows[r + j];
        for (j = STRIDE; j < SLOT_FLOATS; j++) D[o + j] = 0;   /* +0: the padding */
        if (onInstall) onInstall(s, D, o, id);
        var b = BARB >= 0 && rows[r + BARB] > BARB_MIN ? 1 : 0;
        barb[s] = b; barbCount += b;
        setDirty(s);
      }
      res.newRows = nNew;
      if (out) {
        var changed = outStale;
        for (c = 0; c < n; c++) {
          s = slotTmp[c];
          if (out[c] !== s) { out[c] = s; changed = true; }
        }
        res.changed = changed; outStale = false;
      }
      res.hasBarbels = barbCount > 0;
      res.ok = true;
      return res;
    };
    /* the dirty slots as maximal runs inside a 32-slot row, {start, count} in floats (at most limit + 1 of them) */
    S.ranges = function (limit) {
      var list = [], left = S.dirtyCount, s = 0, end = S.nextSlot, most = limit > 0 ? limit + 1 : Infinity;
      while (left > 0 && s < end && list.length < most) {
        if (!dirty[s]) { s++; continue; }
        var a = s; s++; left--;
        while (s < end && dirty[s] && s % ROW_SLOTS !== 0) { s++; left--; }
        list.push({ start: a * SLOT_FLOATS, count: (s - a) * SLOT_FLOATS });
      }
      return list;
    };
    S.plan = function () {
      if (!S.needFull && S.dirtyCount === 0) return null;
      var full = S.needFull, reason = full ? "storage" : "", ranges = [];
      if (!full && S.dirtyCount * SLOT_FLOATS * 4 > S.data.byteLength / 8) { full = true; reason = "bytes"; }
      if (!full) {
        ranges = S.ranges(MAX_RANGES);
        if (ranges.length > MAX_RANGES) { full = true; reason = "ranges"; ranges = []; }
      }
      return { full: full, reason: reason, ranges: ranges, slots: S.dirtyCount, calls: full ? 1 : ranges.length,
               bytes: full ? S.data.byteLength : S.dirtyCount * SLOT_FLOATS * 4, clock: wclock, capacity: S.capacity };
    };
    /* k owners in turn against their snapshot rows (after a prepare of these ids and rows) */
    var vcur = 0;
    S.verify = function (ids, rows, n, k) {
      if (!(n > 0)) return null;
      for (var j = 0; j < k && j < n; j++) {
        var c = vcur % n; vcur = c + 1;
        var s = slotTmp[c], o = s * SLOT_FLOATS, r = c * STRIDE, D = S.data;
        for (var q = 0; q < STRIDE; q++) {
          var a = D[o + q], b = rows[r + q];
          if (a !== b && !(a !== a && b !== b)) return { draw: c, id: ids[c], slot: s, gene: q, stored: a, row: b };
        }
      }
      return null;
    };
    S.acknowledge = function (p) {
      if (!p) return;
      if (p.full && p.capacity === S.capacity) S.needFull = false;
      for (var s = 0; s < S.nextSlot && S.dirtyCount > 0; s++) if (dirty[s] && wtime[s] <= p.clock) { dirty[s] = 0; S.dirtyCount--; }
    };
    S.requireFull = function () { S.needFull = true; };
    S.resetOwnership = resetOwnership;
    S.invalidate = function () { resetOwnership(undefined); S.epoch = {}; };   /* (an epoch no snapshot has: the next one installs all) */
    if (/** @type {number} (undefined: not > 0) */ (opts.initialCapacity) > 0) grow(opts.initialCapacity);
    S.slotOf = function (id) { var s = byId.get(id); return s === undefined ? -1 : s; };
    /* every owner, in slot order: fn(slot, data, offset, id) (a render cache made after the owners were: the decoded constants' backfill) */
    S.eachOwner = function (fn) { for (var s = 0; s < S.nextSlot; s++) if (owned[s]) fn(s, S.data, s * SLOT_FLOATS, slotId[s]); };
    S.isDirty = function (s) { return !!dirty[s]; };
    S.stats = function () {
      return { epoch: S.epoch, capacity: S.capacity, owners: S.size, nextSlot: S.nextSlot, free: freeN, dirty: S.dirtyCount,
               needFull: S.needFull, barbels: barbCount, allocs: S.allocs, bytes: S.data.byteLength };
    };
    return S;
  }

  /** @type {EvoAppearanceSlotsApi} */
  var API = { create: create, SLOT_FLOATS: SLOT_FLOATS, ROW_SLOTS: ROW_SLOTS, MIN_CAPACITY: MIN_CAP, MAX_CAPACITY: MAX_CAP };
  if (typeof module === "object" && module.exports) module.exports = API;
  if (root && root.document) root.EvoAppearanceSlots = API;
  /* (root: the page; in node, module.exports, which has no document: the API only exported) */
})(/** @type {Window & typeof globalThis} */ (typeof window !== "undefined" ? window : this));

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
 *       owner (resetOwnership). Every input is checked before anything is
 *       installed (a bad n, short arrays, an unsafe or repeated id: ok false,
 *       error, no owner added, none released). Then the owners absent from the
 *       snapshot are released (before any birth is placed), the storage grows
 *       if the births need it (powers of two from 256; the survivors keep their
 *       slots and data), and each new fish gets a slot (the free list, last
 *       freed first, then the high-water mark), its 63 floats copied and the
 *       zero after them written, and the slot marked dirty. result: {ok, error,
 *       n, newRows (rows copied), released, grew, migratedBytes (the copy of the
 *       old storage on growth), changed (some outSlots[c] differs from what it
 *       held), hasBarbels (some owner has barbels: row[barbelGene] >
 *       barbelMin, cached per owner)}
 *   plan() -> null (nothing to upload: no dirty slot and no full upload due),
 *       or {full, ranges, slots, bytes, calls, clock, capacity}: full, the whole
 *       storage (new GPU storage: the first, a growth, a restored context);
 *       else ranges: maximal runs of dirty slots, split at every 32-slot row,
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
 * Pure JS (no WebGL): node's tests/ocean_appearance_slots_tests.cjs. Display
 * only: the simulation never reads any of it. */
(function (root) {
  var SLOT_FLOATS = 64, ROW_SLOTS = 32, MIN_CAP = 256, MAX_CAP = 1 << 24, MARK_MAX = 0xFFFFFFFF;

  function grown(a, cap) { var b = new a.constructor(cap); b.set(a); return b; }

  function create(opts) {
    opts = opts || {};
    var STRIDE = opts.stride || 63;
    if (STRIDE > SLOT_FLOATS) throw new Error("a row of " + STRIDE + " floats does not fit a 64-float slot");
    var BARB = opts.barbelGene === undefined ? -1 : opts.barbelGene, BARB_MIN = opts.barbelMin === undefined ? 0.2 : opts.barbelMin;
    var maxCap = Math.min(MAX_CAP, opts.maxCapacity || MAX_CAP);

    var S = {
      epoch: undefined, capacity: 0, data: new Float32Array(0),
      needFull: true,       /* the GPU storage needs one whole upload (new, grown, or restored) */
      dirtyCount: 0, size: 0, nextSlot: 0,
      allocs: 0             /* storage allocations (growths) */
    };
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
    function release(s) {
      byId.delete(slotId[s]);
      owned[s] = 0; barbCount -= barb[s]; barb[s] = 0;
      if (dirty[s]) { dirty[s] = 0; S.dirtyCount--; }   /* its upload is not needed any more */
      free[freeN++] = s;
      S.size--;
    }
    function grow(need) {
      var cap = Math.max(MIN_CAP, S.capacity);
      while (cap < need) cap *= 2;
      if (cap > maxCap) return false;
      var d = new Float32Array(cap * SLOT_FLOATS);
      d.set(S.data);
      res.migratedBytes += S.data.byteLength;
      S.data = d;
      slotId = grown(slotId, cap); owned = grown(owned, cap); mark = grown(mark, cap);
      barb = grown(barb, cap); dirty = grown(dirty, cap); wtime = grown(wtime, cap); free = grown(free, cap);
      S.capacity = cap; S.needFull = true; S.allocs++;
      return true;
    }
    function resetOwnership(epoch) {
      S.epoch = epoch;
      byId.clear();
      owned.fill(0); barb.fill(0); dirty.fill(0);
      S.dirtyCount = 0; S.size = 0; S.nextSlot = 0; freeN = 0; barbCount = 0;
      outStale = true;   /* every outSlots entry is to be written again */
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
      /* the owners gone, before any birth is placed */
      if (n - nNew < S.size) {
        for (s = 0; s < S.nextSlot && n - nNew < S.size; s++) if (owned[s] && mark[s] !== m) { release(s); res.released++; }
      }
      var need = S.nextSlot + Math.max(0, nNew - freeN);
      if (need > S.capacity) {
        if (!grow(need)) return fail("the gene storage cannot hold " + need + " slots (at most " + maxCap + ")");
        res.grew = true;
      }
      var D = S.data;
      for (var k = 0; k < nNew; k++) {
        c = newIdx[k]; id = ids[c];
        s = freeN > 0 ? free[--freeN] : S.nextSlot++;
        byId.set(id, s); slotId[s] = id; owned[s] = 1; mark[s] = m; S.size++; slotTmp[c] = s;
        var o = s * SLOT_FLOATS, r = c * STRIDE;
        for (var j = 0; j < STRIDE; j++) D[o + j] = rows[r + j];
        for (j = STRIDE; j < SLOT_FLOATS; j++) D[o + j] = 0;   /* +0: the padding */
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
    /* the dirty slots as maximal runs inside a 32-slot row, {start, count} in floats */
    S.ranges = function () {
      var list = [], left = S.dirtyCount, s = 0, end = S.nextSlot;
      while (left > 0 && s < end) {
        if (!dirty[s]) { s++; continue; }
        var a = s; s++; left--;
        while (s < end && dirty[s] && s % ROW_SLOTS !== 0) { s++; left--; }
        list.push({ start: a * SLOT_FLOATS, count: (s - a) * SLOT_FLOATS });
      }
      return list;
    };
    S.plan = function () {
      if (!S.needFull && S.dirtyCount === 0) return null;
      var full = S.needFull, ranges = full ? [] : S.ranges();
      return { full: full, ranges: ranges, slots: S.dirtyCount, calls: full ? 1 : ranges.length,
               bytes: full ? S.data.byteLength : S.dirtyCount * SLOT_FLOATS * 4, clock: wclock, capacity: S.capacity };
    };
    S.acknowledge = function (p) {
      if (!p) return;
      if (p.full && p.capacity === S.capacity) S.needFull = false;
      for (var s = 0; s < S.nextSlot && S.dirtyCount > 0; s++) if (dirty[s] && wtime[s] <= p.clock) { dirty[s] = 0; S.dirtyCount--; }
    };
    S.requireFull = function () { S.needFull = true; };
    S.resetOwnership = resetOwnership;
    S.invalidate = function () { resetOwnership(undefined); S.epoch = {}; };   /* (an epoch no snapshot has: the next one installs all) */
    if (opts.initialCapacity > 0) grow(opts.initialCapacity);
    S.slotOf = function (id) { var s = byId.get(id); return s === undefined ? -1 : s; };
    S.isDirty = function (s) { return !!dirty[s]; };
    S.stats = function () {
      return { epoch: S.epoch, capacity: S.capacity, owners: S.size, nextSlot: S.nextSlot, free: freeN, dirty: S.dirtyCount,
               needFull: S.needFull, barbels: barbCount, allocs: S.allocs, bytes: S.data.byteLength };
    };
    return S;
  }

  var API = { create: create, SLOT_FLOATS: SLOT_FLOATS, ROW_SLOTS: ROW_SLOTS, MIN_CAPACITY: MIN_CAP, MAX_CAPACITY: MAX_CAP };
  if (typeof module === "object" && module.exports) module.exports = API;
  if (root && root.document) root.EvoAppearanceSlots = API;
})(typeof window !== "undefined" ? window : this);

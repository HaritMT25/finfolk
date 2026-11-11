// tests/ocean_appearance_slots_tests.cjs: the appearance fish's gene slots (web/ocean_appearance_slots.js), in node.
//   node tests/ocean_appearance_slots_tests.cjs
// Ownership by (epoch, id), the order births and deaths are placed in, growth,
// the upload plans (full / dirty ranges split at the texture's 32-slot rows)
// and their acknowledgement, against a model of the GPU texture that applies
// exactly what a plan names (as three's DataTexture uploader does: the ranges,
// or the whole storage): after every acknowledged upload each fish's slot on
// the "GPU" must hold its 63 floats bit for bit and a +0. No browser.
"use strict";
const path = require("path");
const Slots = require(path.join(__dirname, "..", "web", "ocean_appearance_slots.js"));

let fails = 0, checks = 0;
function ok(cond, what, info) {
  checks++;
  if (!cond) { fails++; console.log("  FAIL " + what + (info !== undefined ? "  " + JSON.stringify(info).slice(0, 400) : "")); }
  else console.log("  ok   " + what);
}
function section(name) { console.log("== " + name); }

const ST = 63, BARB = 33 + 26;
/* a fish's row from its id (and a variant, for a new world's fish under the same id) */
function rowOf(id, v = 0) {
  const r = new Float32Array(ST);
  for (let j = 0; j < ST; j++) r[j] = Math.fround(((id * 131 + j * 17 + v * 7919) % 1009) / 1009 + 0.001 * v);
  r[BARB] = (id + v) % 5 === 0 ? 0.75 : 0.1;   /* every fifth fish has barbels */
  return r;
}
function snap(ids, v = 0) {
  const n = ids.length, rows = new Float32Array(n * ST);
  ids.forEach((id, c) => rows.set(rowOf(id, v), c * ST));
  return { n, ids: Float64Array.from(ids), rows, v };
}
const range = (a, b) => Array.from({ length: b - a }, (_, k) => a + k);
function make(o = {}) { return Slots.create(Object.assign({ stride: ST, barbelGene: BARB, initialCapacity: 256 }, o)); }
/* the GPU's copy: what the acknowledged plans uploaded */
function Gpu() { return { data: new Float32Array(0), cap: 0, uploads: 0, calls: 0, bytes: 0 }; }
function upload(st, gpu, p) {
  if (!p) return;
  if (p.full) { gpu.data = Float32Array.from(st.data); gpu.cap = st.capacity; gpu.calls++; gpu.bytes += st.data.byteLength; }
  else {
    if (gpu.cap !== st.capacity) throw new Error("a dirty plan onto storage of another size");
    for (const r of p.ranges) {
      const x = (r.start / 4) % 512, y = Math.floor(r.start / 2048), w = r.count / 4;
      if (x + w > 512 || Math.floor((r.start + r.count - 1) / 2048) !== y) throw new Error("a range crosses a texture row " + JSON.stringify(r));
      gpu.data.set(st.data.subarray(r.start, r.start + r.count), r.start); gpu.calls++; gpu.bytes += r.count * 4;
    }
  }
  gpu.uploads++;
  st.acknowledge(p);
}
/* every fish of the snapshot: its slot's floats on the CPU (and the GPU) are its row's, bit for bit, then +0 */
function exact(st, s, out, gpu) {
  const u = new Uint32Array(st.data.buffer), g = gpu ? new Uint32Array(gpu.data.buffer) : null, rb = new Uint32Array(s.rows.buffer);
  const seen = new Set();
  let bad = 0, where = null;
  for (let c = 0; c < s.n; c++) {
    const slot = out[c];
    if (slot !== st.slotOf(s.ids[c]) || seen.has(slot) || !(slot >= 0 && slot < st.capacity)) { bad++; where = where || { c, slot, own: st.slotOf(s.ids[c]) }; continue; }
    seen.add(slot);
    for (let j = 0; j < 64; j++) {
      const want = j < ST ? rb[c * ST + j] : 0;
      if (u[slot * 64 + j] !== want || (g && g[slot * 64 + j] !== want)) { bad++; where = where || { c, slot, j, cpu: u[slot * 64 + j], gpu: g && g[slot * 64 + j], want }; break; }
    }
  }
  return { bad, where };
}

section("first snapshot, unchanged frames");
{
  const st = make(), gpu = Gpu(), out = new Float32Array(16);
  let s = snap([10, 11, 12, 13, 14]);
  let r = st.prepare(1, s.ids, s.rows, s.n, out);
  ok(r.ok && r.newRows === 5 && r.released === 0 && !r.grew && r.changed, "5 fish: 5 rows copied, no growth (256 at creation)", r);
  ok(Array.from(out.subarray(0, 5)).join() === "0,1,2,3,4", "slots 0..4 in snapshot order");
  ok(r.hasBarbels === true && st.stats().barbels === 1, "barbels cached per owner (fish 10)", st.stats());
  let p = st.plan();
  ok(p && p.full && p.bytes === 256 * 256 && p.calls === 1, "the first upload is the whole storage (new GPU storage)", p && { full: p.full, bytes: p.bytes });
  upload(st, gpu, p);
  ok(exact(st, s, out, gpu).bad === 0, "bit-exact rows and +0 padding, CPU and GPU");
  ok(st.plan() === null, "acknowledged: nothing left to upload");
  r = st.prepare(1, s.ids, s.rows, s.n, out);
  ok(r.ok && r.newRows === 0 && r.released === 0 && !r.changed && st.plan() === null, "the same fish again: no copy, no slot change, no upload", r);
  const pad = new Float32Array(st.data.buffer, 0, 64)[63];
  ok(Object.is(pad, 0), "the padding is +0");
}

section("reorder, death, same-count death and birth, several births");
{
  const st = make(), gpu = Gpu(), out = new Float32Array(64);
  let s = snap(range(100, 140));
  st.prepare(7, s.ids, s.rows, s.n, out); upload(st, gpu, st.plan());
  const slot0 = Object.fromEntries(Array.from(s.ids).map((id, c) => [id, out[c]]));
  s = snap(range(100, 140).reverse());
  let r = st.prepare(7, s.ids, s.rows, s.n, out);
  ok(r.ok && r.newRows === 0 && r.changed && Array.from(s.ids).every((id, c) => out[c] === slot0[id]) && st.plan() === null,
     "reversed: every fish keeps its slot, the slot attribute changes, nothing to upload");
  s = snap(range(100, 140).filter((id) => id !== 117));
  r = st.prepare(7, s.ids, s.rows, s.n, out);
  ok(r.ok && r.released === 1 && r.newRows === 0 && st.plan() === null && st.stats().free === 1, "a death: released, no upload (its row was clean)", r);
  ok(Array.from(s.ids).every((id, c) => out[c] === slot0[id]), "compaction: the survivors keep their slots");
  s = snap(range(100, 140).filter((id) => id !== 117 && id !== 125).concat([500]));
  r = st.prepare(7, s.ids, s.rows, s.n, out);
  let p = st.plan();
  ok(r.ok && r.released === 1 && r.newRows === 1 && !r.grew && st.slotOf(500) === slot0[117] && slot0[117] < slot0[125] && p && !p.full && p.calls === 1 && p.bytes === 256 &&
     p.ranges[0].start === slot0[117] * 64 && p.ranges[0].count === 64 && st.stats().free === 1,
     "same count, one died and one born (released first): the birth takes the lowest free slot (117's, freed a frame before; 125's stays free), one 256-byte range", { r, p });
  upload(st, gpu, p);
  ok(exact(st, s, out, gpu).bad === 0, "exact after the upload");
  const before = st.stats();
  s = snap(range(100, 140).filter((id) => id !== 117 && id !== 125).concat([500, 501, 502, 503]));
  r = st.prepare(7, s.ids, s.rows, s.n, out);
  p = st.plan();
  ok(r.ok && r.newRows === 3 && !r.grew && p.slots === 3 && p.bytes === 3 * 256 && st.stats().nextSlot === before.nextSlot + 2,
     "3 births with 1 free slot: the free one, then 2 new ones; 3 x 256 bytes", { r, p, before, after: st.stats() });
  upload(st, gpu, p);
  ok(exact(st, s, out, gpu).bad === 0, "exact");
}

section("complete same-count replacement");
{
  const st = make(), gpu = Gpu(), out = new Float32Array(300);
  let s = snap(range(0, 300));
  st.prepare(2, s.ids, s.rows, s.n, out); upload(st, gpu, st.plan());
  const cap = st.capacity;
  s = snap(range(1000, 1300));
  const r = st.prepare(2, s.ids, s.rows, s.n, out), p = st.plan();
  ok(r.ok && r.released === 300 && r.newRows === 300 && !r.grew && st.capacity === cap && p.slots === 300 && p.full && p.reason === "bytes" && p.calls === 1,
     "300 new fish for 300 gone: no growth, every slot reused; 300 dirty of 512 (over an eighth): one whole upload", { r, cap: st.capacity, reason: p.reason });
  upload(st, gpu, p);
  ok(exact(st, s, out, gpu).bad === 0, "every new owner exact (no count-based shortcut)");
}

section("dirty ranges: maximal runs split at the 32-slot rows");
{
  const st = make({ initialCapacity: 4096 }), gpu = Gpu(), out = new Float32Array(2200);
  let ids = range(0, 2100), s = snap(ids);
  st.prepare(3, s.ids, s.rows, s.n, out); upload(st, gpu, st.plan());
  let next = 10000;
  function replaceSlots(slots) {   /* the fish in these slots die, as many are born */
    const dead = new Set(slots.map((sl) => ids.find((id) => st.slotOf(id) === sl)));
    ids = ids.filter((id) => !dead.has(id)).concat(slots.map(() => next++));
    s = snap(ids);
    st.prepare(3, s.ids, s.rows, s.n, out);
    const p = st.plan();
    upload(st, gpu, p);
    return { ranges: p.ranges.map((r) => [r.start, r.count]), exact: exact(st, s, out, gpu).bad === 0, dirtyAfter: st.stats().dirty };
  }
  const want = { "5": [[320, 64]], "30,31": [[1920, 128]], "31,32": [[1984, 64], [2048, 64]], "63,64": [[4032, 64], [4096, 64]],
                 "2047,2048": [[131008, 64], [131072, 64]], "40,41,42,43": [[2560, 256]], "3,9": [[192, 64], [576, 64]] };
  for (const k of Object.keys(want)) {
    const g = replaceSlots(k.split(",").map(Number));
    ok(JSON.stringify(g.ranges) === JSON.stringify(want[k]) && g.exact && g.dirtyAfter === 0, "slots " + k + " -> " + JSON.stringify(want[k]), g);
  }
}

section("growth 2,048 -> 2,049 -> 2,500, shrink, refill");
{
  const st = make(), gpu = Gpu();
  let out = new Float32Array(4096), ids = range(0, 2048), s = snap(ids);
  let r = st.prepare(4, s.ids, s.rows, s.n, out);
  ok(r.ok && r.grew && st.capacity === 2048, "2,048 fish: the storage grows from 256 to 2,048", st.stats());
  upload(st, gpu, st.plan());
  const keep = Array.from(out.subarray(0, 2048)), allocs = st.stats().allocs, uploads = gpu.uploads;
  ids = range(0, 2049); s = snap(ids);
  r = st.prepare(4, s.ids, s.rows, s.n, out);
  let p = st.plan();
  ok(r.ok && r.grew && st.capacity === 4096 && st.stats().allocs === allocs + 1 && r.migratedBytes === 2048 * 256 && keep.every((x, c) => out[c] === x) && out[2048] === 2048,
     "2,049: one growth to 4,096, the survivors' slots kept, the old storage migrated (512 KiB)", { stats: st.stats(), migrated: r.migratedBytes });
  ok(p.full && p.bytes === 1048576 && p.calls === 1, "  one full 1 MiB upload (new GPU storage)", { full: p.full, bytes: p.bytes });
  upload(st, gpu, p);
  ok(exact(st, s, out, gpu).bad === 0, "  exact");
  ids = range(0, 2500); s = snap(ids);
  r = st.prepare(4, s.ids, s.rows, s.n, out);
  p = st.plan();
  ok(r.ok && !r.grew && st.capacity === 4096 && r.newRows === 451 && !p.full && p.bytes === 451 * 256 && gpu.uploads === uploads + 1,
     "2,500: no growth, 451 rows copied and uploaded as ranges", { r, p: { full: p.full, bytes: p.bytes, calls: p.calls } });
  upload(st, gpu, p);
  ok(exact(st, s, out, gpu).bad === 0, "  exact");
  const slots2500 = Object.fromEntries(ids.map((id, c) => [id, out[c]]));
  ids = ids.filter((id) => id % 5 === 0); s = snap(ids);
  r = st.prepare(4, s.ids, s.rows, s.n, out);
  ok(r.ok && r.released === 2000 && st.capacity === 4096 && ids.every((id, c) => out[c] === slots2500[id]) && st.plan() === null,
     "shrink to 500: no shrinking or repacking, survivors keep their slots, nothing to upload", st.stats());
  ids = ids.concat(range(9000, 11000)); s = snap(ids);
  r = st.prepare(4, s.ids, s.rows, s.n, out);
  p = st.plan();
  ok(r.ok && !r.grew && st.stats().nextSlot === 2500 && st.capacity === 4096 && p.full && p.calls === 1,
     "refill to 2,500: the freed slots reused (the high-water mark stays 2,500); 2,000 dirty: one whole upload", { stats: st.stats(), reason: p.reason });
  upload(st, gpu, p);
  ok(exact(st, s, out, gpu).bad === 0, "  exact");
}

section("epochs: a new world with the same ids");
{
  const st = make(), gpu = Gpu(), out = new Float32Array(64);
  let s = snap(range(0, 40), 0);
  st.prepare(1, s.ids, s.rows, s.n, out); upload(st, gpu, st.plan());
  st.prepare(1, snap(range(5, 40)).ids, snap(range(5, 40)).rows, 35, out);   /* some freed: the next world starts clean */
  s = snap(range(0, 40), 1);   /* the same ids, other genes */
  const r = st.prepare(2, s.ids, s.rows, s.n, out), p = st.plan();
  ok(r.ok && r.newRows === 40 && Array.from(out.subarray(0, 40)).every((x, c) => x === c) && p.slots === 40 && st.stats().allocs === 1,
     "a new epoch: every fish new (identity slots again), 40 dirty, the same storage", { r, p: p && { full: p.full, reason: p.reason, slots: p.slots } });
  upload(st, gpu, p);
  ok(exact(st, s, out, gpu).bad === 0, "the new world's genes, not the old ones");
}

section("bad snapshots install nothing");
{
  const st = make(), gpu = Gpu(), out = new Float32Array(64);
  let s = snap(range(0, 20));
  st.prepare(1, s.ids, s.rows, s.n, out); upload(st, gpu, st.plan());
  const before = JSON.stringify(st.stats()), slots = Array.from(out.subarray(0, 20));
  const bad = [
    ["a repeated id (a survivor)", [0, 1, 2, 2]], ["a repeated id (new)", [0, 1, 50, 50]], ["-1", [0, -1]], ["1.5", [0, 1.5]],
    ["2^53", [0, 2 ** 53]], ["NaN", [0, NaN]], ["Infinity", [0, Infinity]]
  ];
  for (const [what, ids] of bad) {
    const t = snap(ids.map((x) => (Number.isFinite(x) ? x : 0))); t.ids = Float64Array.from(ids);
    const r = st.prepare(1, t.ids, t.rows, t.n, out);
    ok(!r.ok && r.error && JSON.stringify(st.stats()) === before, what + ": refused (" + r.error + "), no owner added or released");
  }
  ok(!st.prepare(1, s.ids, s.rows.subarray(0, 63 * 19), 20, out).ok && JSON.stringify(st.stats()) === before, "short rows: refused");
  ok(!st.prepare(1, s.ids.subarray(0, 19), s.rows, 20, out).ok, "short ids: refused");
  ok(!st.prepare(1, s.ids, s.rows, 20.5, out).ok && !st.prepare(1, s.ids, s.rows, -1, out).ok, "a bad count: refused");
  ok(!st.prepare(1, s.ids, s.rows, 20, new Float32Array(10)).ok, "a slot attribute too small: refused");
  const r = st.prepare(1, s.ids, s.rows, s.n, out);
  ok(r.ok && r.newRows === 0 && r.changed && slots.every((x, c) => out[c] === x), "the good snapshot again: the same owners (and the attribute rewritten after a refusal)", r);
  /* ids beyond 2^32: no truncation (a | 0 would alias them) */
  const big = [2 ** 40, 2 ** 40 + 2 ** 32, 2 ** 32 + 1, 1, 2 ** 52 + 3];
  const t = snap(big.map((x, k) => k)); t.ids = Float64Array.from(big);
  const r2 = st.prepare(9, t.ids, t.rows, t.n, out);
  ok(r2.ok && new Set(big.map((id) => st.slotOf(id))).size === 5 && st.slotOf(2 ** 40) !== st.slotOf(2 ** 40 + 2 ** 32), "ids above 2^32 kept apart (2^40 and 2^40 + 2^32)", big.map((id) => st.slotOf(id)));
  const lim = make({ maxCapacity: 512 }), r3 = lim.prepare(1, Float64Array.from(range(0, 600)), new Float32Array(600 * ST), 600, new Float32Array(600));
  ok(!r3.ok && /cannot hold/.test(r3.error) && lim.capacity === 256, "past the GPU's limit: refused, no growth", r3.error);
  /* the limit is checked before any owner is released (review of #53, P3-5) */
  const lim2 = make({ maxCapacity: 512 }), o2 = new Float32Array(1024);
  let t2 = snap(range(0, 200)); lim2.prepare(1, t2.ids, t2.rows, t2.n, o2);
  const before2 = JSON.stringify(lim2.stats());
  t2 = snap(range(0, 100).concat(range(5000, 5500)));
  const r4 = lim2.prepare(1, t2.ids, t2.rows, t2.n, o2);
  ok(!r4.ok && /cannot hold 600/.test(r4.error) && JSON.stringify(lim2.stats()) === before2,
     "100 survivors, 100 gone, 500 born past the limit: refused before the 100 are released", { error: r4.error, stats: lim2.stats() });
  ok(!st.prepare(1, null, s.rows, s.n, out).ok, "a snapshot without ids: refused (the plain fish are drawn)");
}

section("lowest free slot first; an upload is at most 32 calls, or one whole upload (review of #53, P3-1)");
{
  const st = make({ initialCapacity: 4096 }), gpu = Gpu();
  const out = new Float32Array(4096);
  let ids = range(0, 2500), s = snap(ids);
  st.prepare(1, s.ids, s.rows, s.n, out); upload(st, gpu, st.plan());
  /* fish 10, 3 and 7 die (their slots: identity), three are born: they take 3, 7, 10 */
  ids = ids.filter((id) => ![3, 7, 10].includes(id)); s = snap(ids); st.prepare(1, s.ids, s.rows, s.n, out); upload(st, gpu, st.plan());
  ids = ids.concat([9001, 9002, 9003]); s = snap(ids); st.prepare(1, s.ids, s.rows, s.n, out);
  ok([9001, 9002, 9003].map((id) => st.slotOf(id)).join() === "3,7,10", "births take the lowest free slots, in order", [9001, 9002, 9003].map((id) => st.slotOf(id)));
  upload(st, gpu, st.plan());
  /* k births, one in each of k texture rows (the owners of slots 32r + 5 replaced) */
  const isolated = (k, base) => {
    const dead = new Set(range(0, k).map((r) => ids.find((id) => st.slotOf(id) === r * 32 + 5)));
    ids = ids.filter((id) => !dead.has(id)).concat(range(base, base + k)); s = snap(ids);
    st.prepare(1, s.ids, s.rows, s.n, out);
    const p = st.plan(); upload(st, gpu, p);
    return { full: p.full, reason: p.reason, calls: p.calls, bytes: p.bytes, exact: exact(st, s, out, gpu).bad === 0 };
  };
  const i32 = isolated(32, 20000);
  ok(!i32.full && i32.calls === 32 && i32.bytes === 32 * 256 && i32.exact, "32 births in 32 texture rows: 32 ranges of 256 bytes", i32);
  const i40 = isolated(40, 21000);
  ok(i40.full && i40.reason === "ranges" && i40.calls === 1 && i40.exact, "40 births in 40 rows (10 KiB): more than 32 calls, so one whole upload", i40);
  /* a Turbo-like hand-back: every other fish replaced */
  const keep = ids.filter((id, k) => k % 2 === 0);
  ids = keep.concat(range(30000, 30000 + (ids.length - keep.length))); s = snap(ids);
  const r = st.prepare(1, s.ids, s.rows, s.n, out), p = st.plan();
  ok(r.ok && r.newRows > 1200 && p.full && p.calls === 1 && p.bytes === 1048576,
     "a 50 % turnover (" + r.newRows + " births in freed slots all over the texture): one whole upload, not hundreds of ranges", { reason: p.reason, slots: p.slots });
  upload(st, gpu, p);
  ok(exact(st, s, out, gpu).bad === 0 && st.plan() === null, "  exact, nothing left");
  /* the Big tank's new world (2,000 fish, a new epoch on the same storage) */
  const big = make(), gb = Gpu(), ob = new Float32Array(2048);
  let sb = snap(range(0, 2000)); big.prepare(1, sb.ids, sb.rows, sb.n, ob); upload(big, gb, big.plan());
  const allocs = big.stats().allocs;
  sb = snap(range(0, 2000), 3);
  big.prepare(2, sb.ids, sb.rows, sb.n, ob);
  const pb = big.plan();
  ok(pb.full && pb.calls === 1 && pb.reason === "bytes" && big.stats().allocs === allocs, "the Big tank's new world (2,000 fish, the same storage): one whole upload, no new storage", { reason: pb.reason });
  upload(big, gb, pb);
  ok(exact(big, sb, ob, gb).bad === 0, "  exact");
}

section("verify: the copy-once assumption watched (review of #53, P3-4)");
{
  const st = make(), out = new Float32Array(64);
  const s = snap(range(0, 40));
  let found = null;
  for (let f = 0; f < 20 && !found; f++) { st.prepare(1, s.ids, s.rows, s.n, out); found = st.verify(s.ids, s.rows, s.n, 2); }
  ok(found === null, "unchanged rows: no difference over a whole rotation (20 frames x 2 of 40)");
  const t = snap(range(0, 40)); t.rows.set(rowOf(17, 5), 17 * ST);   /* fish 17's genes changed under its id */
  let at = -1;
  for (let f = 0; f < 20 && !found; f++) { st.prepare(1, t.ids, t.rows, t.n, out); found = st.verify(t.ids, t.rows, t.n, 2); if (found) at = f; }
  ok(found && found.id === 17 && found.slot === st.slotOf(17) && at >= 0, "a row changed under its id: found within a rotation (frame " + at + ")", found);
  st.invalidate();
  const r = st.prepare(1, t.ids, t.rows, t.n, out);
  let again = null;
  for (let f = 0; f < 20 && !again; f++) again = st.verify(t.ids, t.rows, t.n, 2);
  ok(r.ok && r.newRows === 40 && again === null, "invalidated and reinstalled: the new rows, no difference left");
}

section("upload plans: acknowledged only after the upload, nothing lost");
{
  const st = make(), gpu = Gpu();
  let out = new Float32Array(64);
  let ids = range(0, 30), s = snap(ids);
  st.prepare(1, s.ids, s.rows, s.n, out); upload(st, gpu, st.plan());
  ids = ids.concat([100]); s = snap(ids); st.prepare(1, s.ids, s.rows, s.n, out);
  const p1 = st.plan();   /* queued, not consumed (a frame not drawn) */
  ids = ids.concat([101]); s = snap(ids); st.prepare(1, s.ids, s.rows, s.n, out);
  const p2 = st.plan();
  ok(p1.slots === 1 && p2.slots === 2, "a plan not consumed is rebuilt from everything outstanding (1, then 2 slots)");
  upload(st, gpu, p2);
  ok(st.plan() === null && exact(st, s, out, gpu).bad === 0, "the later plan covers both");
  ids = ids.concat([102]); s = snap(ids); st.prepare(1, s.ids, s.rows, s.n, out);
  const p3 = st.plan();
  ids = ids.concat([103]); s = snap(ids); st.prepare(1, s.ids, s.rows, s.n, out);   /* written after p3 was made */
  upload(st, gpu, p3);   /* p3's ranges only (102's slot), then acknowledged, as three's onUpdate does */
  ok(st.stats().dirty === 1 && st.isDirty(st.slotOf(103)) && !st.isDirty(st.slotOf(102)), "an acknowledgement clears only what its plan covered", st.stats());
  const p4 = st.plan(); upload(st, gpu, p4);
  ok(exact(st, s, out, gpu).bad === 0 && st.plan() === null, "the rest next time");
  ids = ids.concat([104]); s = snap(ids); st.prepare(1, s.ids, s.rows, s.n, out);
  ok(st.stats().dirty === 1, "a birth: dirty");
  ids = ids.filter((id) => id !== 104); s = snap(ids); st.prepare(1, s.ids, s.rows, s.n, out);
  ok(st.stats().dirty === 0 && st.plan() === null, "it died before its upload: nothing to upload any more");
  st.requireFull();
  const pf = st.plan();
  ok(pf && pf.full && pf.bytes === st.data.byteLength, "requireFull (a restored context): a full plan");
  upload(st, gpu, pf);
  ok(st.plan() === null && exact(st, s, out, gpu).bad === 0, "  then nothing");
  /* a full plan of an older (smaller) storage does not end the full upload of a grown one */
  const pOld = (st.requireFull(), st.plan());
  ids = ids.concat(range(5000, 5300)); s = snap(ids); out = new Float32Array(512);
  const rg = st.prepare(1, s.ids, s.rows, s.n, out);
  st.acknowledge(pOld);
  ok(rg.grew && st.stats().needFull === true, "a full plan of the old capacity, acknowledged after a growth: the full upload stays due", st.stats());
  upload(st, gpu, st.plan());
  ok(exact(st, s, out, gpu).bad === 0, "  exact after the full upload");
}

section("barbels, empty snapshots, invalidation");
{
  const st = make(), out = new Float32Array(64);
  let s = snap([1, 2, 3, 4, 5]);   /* fish 5 has barbels */
  ok(st.prepare(1, s.ids, s.rows, s.n, out).hasBarbels === true, "a fish with barbels: hasBarbels");
  s = snap([1, 2, 3, 4]);
  ok(st.prepare(1, s.ids, s.rows, s.n, out).hasBarbels === false, "it died: none");
  const r = st.prepare(1, new Float64Array(0), new Float32Array(0), 0, out);
  ok(r.ok && r.released === 4 && st.stats().owners === 0, "an empty snapshot releases every owner", st.stats());
  s = snap([7, 8]); st.prepare(1, s.ids, s.rows, s.n, out);
  st.invalidate();
  const r2 = st.prepare(1, s.ids, s.rows, s.n, out);
  ok(r2.ok && r2.newRows === 2, "invalidate(): the next snapshot installs every fish again, same epoch or not", r2);
}

section("random lives against the GPU model");
{
  let seed = 12345;
  const rnd = () => { seed = (seed * 1103515245 + 12345) >>> 0; return seed / 4294967296; };
  const st = make(), gpu = Gpu();
  let out = new Float32Array(256), ids = range(0, 300), next = 300, epoch = 1, peak = 300, bad = 0, steps = 0, skipped = 0, worst = null, maxCalls = 0, fulls = 0;
  let s = snap(ids);
  for (let t = 0; t < 400; t++) {
    const born = Math.floor(rnd() * (t % 50 < 25 ? 60 : 5)), dieP = t % 50 < 25 ? 0.01 : 0.12;
    ids = ids.filter(() => rnd() > dieP);
    for (let k = 0; k < born; k++) ids.push(next++);
    if (rnd() < 0.2) ids.sort(() => rnd() - 0.5);   /* a reordered draw */
    if (t === 200) { epoch++; ids = range(0, ids.length); next = ids.length; }   /* a new world: the ids start over */
    peak = Math.max(peak, ids.length);
    s = snap(ids, epoch);
    if (out.length < s.n) out = new Float32Array(2 * s.n);
    const r = st.prepare(epoch, s.ids, s.rows, s.n, out);
    if (!r.ok) { bad++; worst = r.error; continue; }
    if (rnd() < 0.3) { skipped++; continue; }   /* not drawn this frame: the upload waits */
    const pl = st.plan();
    if (pl) { maxCalls = Math.max(maxCalls, pl.calls); if (pl.full) fulls++; }
    upload(st, gpu, pl);
    const e = exact(st, s, out, gpu);
    if (e.bad) { bad++; worst = worst || e.where; }
    steps++;
  }
  let cap = 256; while (cap < peak) cap *= 2;
  ok(bad === 0, "every drawn frame: each fish's slot exact on the GPU (" + steps + " uploads, " + skipped + " frames not drawn)", worst);
  ok(maxCalls <= 32, "every upload at most 32 calls (most " + maxCalls + "; " + fulls + " whole)");
  ok(st.capacity <= cap, "storage bounded by the peak population (" + peak + " -> at most " + cap + "), not by the births (" + next + ")", st.stats());
}

section("owner hooks (onGrow / onReset / onRelease / onInstall): a render cache keyed by slot");
{
  /* a model of a cache keyed by slot, kept only through the hooks: slot -> the id whose row it was made from */
  const log = [];
  const cache = new Map();
  const grown = [];
  const hooks = {
    onGrow: (cap) => { grown.push(cap); log.push("grow " + cap); },
    onReset: () => { cache.clear(); log.push("reset"); },
    onRelease: (s) => { cache.delete(s); log.push("release " + s); },
    onInstall: (s, data, off, id) => {
      /* the row and its padding are already in place at install time */
      const row = rowOf(id, 0);
      let exactRow = true;
      for (let j = 0; j < ST; j++) if (data[off + j] !== row[j]) exactRow = false;
      if (data[off + 63] !== 0 || !exactRow) log.push("BAD install " + s);
      cache.set(s, id); log.push("install " + s + "=" + id);
    }
  };
  const st = make(Object.assign({ initialCapacity: 256 }, hooks)), out = new Float32Array(600);
  ok(grown.join() === "256", "the initial storage calls onGrow(256) once", grown);
  let s = snap([10, 11, 12, 13, 14]);
  log.length = 0;
  st.prepare(1, s.ids, s.rows, s.n, out);
  ok(log.join("|") === "reset|install 0=10|install 1=11|install 2=12|install 3=13|install 4=14", "the first snapshot (epoch 1 on a store of none): onReset, then 5 births: onInstall once each, in slot order", log);
  log.length = 0;
  st.prepare(1, s.ids, s.rows, s.n, out);
  ok(log.length === 0, "an unchanged snapshot calls no hook");
  s = snap([14, 13, 12, 11, 10]);
  st.prepare(1, s.ids, s.rows, s.n, out);
  ok(log.length === 0, "a reordered snapshot calls no hook (the owners keep their slots)", log);
  s = snap([14, 12, 10, 20, 21]);
  st.prepare(1, s.ids, s.rows, s.n, out);
  ok(log.join("|") === "release 1|release 3|install 1=20|install 3=21", "deaths release before births are installed; the lowest free slots are reused", log);
  ok(Array.from(cache.entries()).sort((a, b) => a[0] - b[0]).map((e) => e.join("=")).join() === "0=10,1=20,2=12,3=21,4=14", "the cache matches the owners", Array.from(cache.entries()));
  log.length = 0;
  s = snap(range(100, 100 + 300));
  st.prepare(1, s.ids, s.rows, s.n, new Float32Array(600));
  ok(grown.join() === "256,512" && log.filter((x) => x.startsWith("grow")).join() === "grow 512", "growth past 256 calls onGrow(512) once", { grown, log: log.slice(0, 8) });
  ok(log.indexOf("grow 512") > log.findIndex((x) => x.startsWith("release")) && log.indexOf("grow 512") < log.findIndex((x) => x.startsWith("install")), "the owners gone are released, then the storage grows, then the births are installed", log.slice(0, 12));
  /* a new epoch with the same ids: every owner forgotten, then installed again */
  log.length = 0;
  s = snap([100, 101, 102]);
  st.prepare(2, s.ids, s.rows, s.n, out);
  ok(log[0] === "reset" && log.slice(1).join("|") === "install 0=100|install 1=101|install 2=102", "a new epoch: onReset first, then every fish installed again (even with the same ids)", log);
  log.length = 0;
  st.invalidate();
  ok(log.join() === "reset", "invalidate() resets", log);
  /* a refused snapshot installs nothing and releases nothing */
  log.length = 0;
  const bad = st.prepare(5, Float64Array.from([1, 1]), new Float32Array(2 * ST), 2, out);
  ok(!bad.ok && log.filter((x) => x.startsWith("install") || x.startsWith("release")).length === 0, "a refused snapshot (a repeated id) calls no install / release", log);
  /* a store with hooks behaves as one without: the same slots and dirty sets for the same session */
  const plain = make(), hooked = make(Object.assign({}, hooks));
  let same = true;
  for (const ids of [[3, 4, 5, 6, 7, 8], [3, 5, 7, 9, 10, 11, 12], [12, 11, 10, 9, 3], range(0, 40)]) {
    const sn = snap(ids), o1 = new Float32Array(64), o2 = new Float32Array(64);
    plain.prepare(1, sn.ids, sn.rows, sn.n, o1); hooked.prepare(1, sn.ids, sn.rows, sn.n, o2);
    if (o1.join() !== o2.join() || plain.stats().dirty !== hooked.stats().dirty) same = false;
  }
  ok(same, "with hooks the slots and the dirty set are the same as without");
  /* eachOwner: the backfill of a cache made after the owners were */
  const eo = make(), so = snap([4, 5, 6, 7, 8]), oo = new Float32Array(16);
  eo.prepare(1, so.ids, so.rows, so.n, oo);
  eo.prepare(1, Float64Array.from([4, 6, 8, 9]), snap([4, 6, 8, 9]).rows, 4, oo);
  const seenO = [];
  eo.eachOwner((s, d, o, id) => { let same2 = true; const row = rowOf(id, 0); for (let j = 0; j < ST; j++) if (d[o + j] !== row[j]) same2 = false; seenO.push(s + "=" + id + (same2 ? "" : "!")); });
  ok(seenO.join() === "0=4,1=9,2=6,4=8", "eachOwner visits exactly the owners (slot, id), in slot order, with their rows at data[offset ..]", seenO);
}

console.log((fails ? "FAILED " + fails + " of " : "all ") + checks + " checks" + (fails ? "" : " passed"));
process.exit(fails ? 1 : 0);

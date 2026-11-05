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
  ok(r.ok && r.released === 1 && r.newRows === 1 && !r.grew && st.slotOf(500) === slot0[125] && p && !p.full && p.calls === 1 && p.bytes === 256 &&
     p.ranges[0].start === slot0[125] * 64 && p.ranges[0].count === 64,
     "same count, one died and one born: the birth takes the slot freed this frame (released first), one 256-byte range", { r, p });
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
  ok(r.ok && r.released === 300 && r.newRows === 300 && !r.grew && st.capacity === cap && p.bytes === 300 * 256,
     "300 new fish for 300 gone: no growth, every slot reused, 300 x 256 bytes", { r, cap: st.capacity });
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
  ok(r.ok && !r.grew && st.stats().nextSlot === 2500 && st.capacity === 4096, "refill to 2,500: the freed slots reused (the high-water mark stays 2,500)", st.stats());
  upload(st, gpu, st.plan());
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
  ok(r.ok && r.newRows === 40 && Array.from(out.subarray(0, 40)).every((x, c) => x === c) && !p.full && p.bytes === 40 * 256,
     "a new epoch: every fish new (identity slots again), uploaded as ranges (the storage is the same)", { r, p: p && { full: p.full, bytes: p.bytes } });
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
  let out = new Float32Array(256), ids = range(0, 300), next = 300, epoch = 1, peak = 300, bad = 0, steps = 0, skipped = 0, worst = null;
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
    upload(st, gpu, st.plan());
    const e = exact(st, s, out, gpu);
    if (e.bad) { bad++; worst = worst || e.where; }
    steps++;
  }
  let cap = 256; while (cap < peak) cap *= 2;
  ok(bad === 0, "every drawn frame: each fish's slot exact on the GPU (" + steps + " uploads, " + skipped + " frames not drawn)", worst);
  ok(st.capacity <= cap, "storage bounded by the peak population (" + peak + " -> at most " + cap + "), not by the births (" + next + ")", st.stats());
}

console.log((fails ? "FAILED " + fails + " of " : "all ") + checks + " checks" + (fails ? "" : " passed"));
process.exit(fails ? 1 : 0);

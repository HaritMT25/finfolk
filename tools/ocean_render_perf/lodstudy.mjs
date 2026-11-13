// tools/ocean_render_perf/lodstudy.mjs: where the medium and the coarse body template (and the barbel strips) stop looking different, by the
// fish's projected size. The same fish, side-on at the same height, the camera taken away along its side normal to a ladder of distances
// (its projected body radius, posePx, from about 3 to 16 CSS px), the clock frozen, drawn forced medium and forced coarse (the policy's
// lod "medium" / "coarse", decoded off, barbels off) and, for the barbels, forced medium with barbels "body" and "off"; per size, in a window
// round the fish: the pixels that differ at all, the pixels that differ by 24 / 255 or more (a visible difference), the largest difference, and
// the mean absolute difference over the window, medians over the fish. Pictures of the pairs at chosen sizes (a crop of the window, enlarged,
// medium | coarse | difference x8) are written for the figures.
//   node lodstudy.mjs --base http://localhost:8182 --root REPO --out DIR [--fish 10] [--pop 300] [--sizes 3,4,5,6,7,8,10,12,16] [--png 5,7,10]
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import zlib from "node:zlib";
import { acquire } from "./lock.mjs";
const require = createRequire(import.meta.url);
const args = process.argv.slice(2);
function arg(name, def) { const i = args.indexOf("--" + name); return i >= 0 && i + 1 < args.length && !args[i + 1].startsWith("--") ? args[i + 1] : def; }
const PW = process.env.PLAYWRIGHT || "C:/Users/harit/gemini_bridge/node_modules/playwright";
const BRAVE = process.env.BRAVE_EXE || "C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe";
const BASE = String(arg("base", "http://localhost:8182")).replace(/\/$/, ""), ROOT = path.resolve(String(arg("root", ".")));
const OUT = path.resolve(String(arg("out", path.join(os.tmpdir(), "lodstudy_" + Date.now()))));
const NFISH = Number(arg("fish", 10)), POP = Number(arg("pop", 300)), COLOUR = String(arg("colour", "appearance"));
const SIZES = String(arg("sizes", "3,4,5,6,7,8,10,12,16")).split(",").map(Number), PNGS = String(arg("png", "5,7,10")).split(",").map(Number);
const CASES = JSON.parse(fs.readFileSync(path.join(ROOT, "tests/fixtures/ocean_render_cases.json"), "utf8"));
const { chromium } = require(PW);
fs.mkdirSync(OUT, { recursive: true });

const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (buf) => { let c = 0xFFFFFFFF; for (let i = 0; i < buf.length; i++) c = CRC[(c ^ buf[i]) & 255] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };
const chunk = (type, data) => { const b = Buffer.alloc(12 + data.length); b.writeUInt32BE(data.length, 0); b.write(type, 4, "ascii"); data.copy(b, 8); b.writeUInt32BE(crc32(b.subarray(4, 8 + data.length)), 8 + data.length); return b; };
function png(w, h, rgba) {
  const raw = Buffer.alloc((w * 4 + 1) * h);
  for (let y = 0; y < h; y++) Buffer.from(rgba.buffer, rgba.byteOffset + y * w * 4, w * 4).copy(raw, y * (w * 4 + 1) + 1);
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 6;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", zlib.deflateSync(raw, { level: 6 })), chunk("IEND", Buffer.alloc(0))]);
}
const med = (a) => { const s = a.slice().sort((x, y) => x - y); return s.length ? s[(s.length - 1) >> 1] : NaN; };

const INIT = () => {
  const raf = window.requestAnimationFrame.bind(window);
  window.__after = [];
  window.requestAnimationFrame = (cb) => raf((t) => { cb(t); if (cb.name === "frame" && window.__after.length) { const q = window.__after; window.__after = []; q.forEach((f) => f()); } });
};
const release = await acquire("builder-render lodstudy");
let ctx = null;
const result = { started: new Date().toISOString(), pop: POP, colour: COLOUR, sizes: SIZES, fish: NFISH, rows: [] };
try {
  ctx = await chromium.launchPersistentContext("", { executablePath: BRAVE, headless: true, viewport: { width: 1000, height: 700 }, deviceScaleFactor: 1, args: ["--no-first-run", "--no-default-browser-check"] });
  await ctx.addInitScript(INIT);
  const page = ctx.pages()[0] || await ctx.newPage(), errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  const c = Object.assign({}, CASES.benchmark, { population: POP, colourMode: COLOUR, config: Object.assign({}, CASES.benchmark.config) });
  const q = new URLSearchParams({ renderBench: "1", guide: "0", intro: "0", seed: String(c.worldSeed), pop: String(POP), w: String(c.world[0]), h: String(c.world[1]), depth: String(c.world[2]),
    speed: String(c.speed), colour: COLOUR, walls: "1", cfg: JSON.stringify(Object.assign({}, c.config, { walls: undefined })) });
  await page.goto(BASE + "/ocean.html?" + q.toString());
  await page.waitForFunction(() => window.EvoApp && window.EvoApp.ready === true && window.EvoOcean && window.EvoOcean.bench, null, { timeout: 120000, polling: 200 });
  await page.evaluate(() => EvoOcean.bench.frames(10));
  await page.evaluate(() => { const S = EvoOcean.scene, orig = S.render; S.render = function (s, inf) { return orig.call(this, s, Object.assign({}, inf, { animT: 20.0 })); }; });
  await page.evaluate(async (cd) => { await EvoOcean.scene.setRenderOptimization({ lod: "quality", decoded: false, barbels: "body" }); await EvoOcean.bench.prepare(Object.assign({}, cd, { camera: "whole", settleMs: 300 })); }, c);
  /* the fish: the ones with barbels first (both effects at once), then the rest, by id */
  const fishList = await page.evaluate((n) => {
    const s = EvoOcean.bench.snapshotCopy(), EA = EvoAppearance, out = [];
    for (let i = 0; i < s.n; i++) out.push({ i, id: s.ids[i], barb: s.app[EA.STRIDE * i + EA.MO + 26] > 0.2 });
    out.sort((a, b) => (b.barb - a.barb) || (a.id - b.id));
    return out.slice(0, n);
  }, NFISH);
  for (const fish of fishList) {
    for (const px of SIZES) {
      const r = await page.evaluate(async ([fi, target]) => {
        const S = EvoOcean.scene, B = EvoOcean.bench, s = B.snapshotCopy(), W = EvoOcean.state().W, H = EvoOcean.state().H, EA = EvoAppearance;
        const hp = (k) => [s.segs[12 * fi + 2 * k] - W / 2, -s.depth[fi], s.segs[12 * fi + 2 * k + 1] - H / 2];
        const h0 = hp(0), h2 = hp(2), mid = hp(1), fl = Math.hypot(h0[0] - h2[0], h0[2] - h2[2]) || 1, fx = (h0[0] - h2[0]) / fl, fz = (h0[2] - h2[2]) / fl;
        /* the radius R = 4.6 x scale; the distance for the size asked, refined twice from the measured size */
        const R = 4.6, pc = S.poseCamera();
        let d = R * pc.focalCss / target;
        const place = (dd) => S.lookFrom([mid[0] - fz * dd, mid[1] + 0.12 * dd, mid[2] + fx * dd], mid);
        let size = 0;
        for (let it = 0; it < 3; it++) {
          place(d); await B.frames(3);
          const G = S.poseCamera(), p = S.poseOf(fi), xs = [], ys = [];
          for (let k = 0; k < 6; k++) { xs.push(p.spine[2 * k]); ys.push(p.spine[2 * k + 1]); }
          size = EvoOceanScene.posePx(xs, ys, p.R, p.y, { view: G.view, focal: G.focalCss, near: G.near, halfW: G.halfW, halfH: G.halfH });
          d *= size / target;
        }
        place(d); await B.frames(3);
        const G = S.poseCamera(), p = S.poseOf(fi), xs = [], ys = [];
        for (let k = 0; k < 6; k++) { xs.push(p.spine[2 * k]); ys.push(p.spine[2 * k + 1]); }
        size = EvoOceanScene.posePx(xs, ys, p.R, p.y, { view: G.view, focal: G.focalCss, near: G.near, halfW: G.halfW, halfH: G.halfH });
        const a = S.project(s, fi);   /* the head, client px */
        const rc = document.getElementById("tank").getBoundingClientRect();
        /* the window: the head and the tail projected (the spine's two ends), padded by 3 sizes */
        const tail = { x: 0, y: 0 };
        const V = S.view();
        const cvs = document.getElementById("tank"), gl = cvs.getContext("webgl2"), Wp = gl.drawingBufferWidth, Hp = gl.drawingBufferHeight;
        const proj = (X, Y, Z) => { const m = G.proj, v = G.view; const x = v[0] * X + v[4] * Y + v[8] * Z + v[12], y = v[1] * X + v[5] * Y + v[9] * Z + v[13], z = v[2] * X + v[6] * Y + v[10] * Z + v[14];
          const cx = m[0] * x + m[4] * y + m[8] * z + m[12], cy = m[1] * x + m[5] * y + m[9] * z + m[13], cw = m[3] * x + m[7] * y + m[11] * z + m[15];
          return [(cx / cw * 0.5 + 0.5) * Wp, (0.5 - cy / cw * 0.5) * Hp]; };
        const pts = [0, 1, 2, 3, 4, 5].map((k) => { const q = hp(k); return proj(q[0], q[1], q[2]); });
        const grab = async (pol) => {
          await S.setRenderOptimization(pol); await B.wait(500); await B.frames(4);
          const b64 = await new Promise((res) => window.__after.push(() => { const px = new Uint8Array(Wp * Hp * 4); gl.readPixels(0, 0, Wp, Hp, gl.RGBA, gl.UNSIGNED_BYTE, px);
            let str = ""; for (let i = 0; i < px.length; i += 0x8000) str += String.fromCharCode.apply(null, px.subarray(i, i + 0x8000)); res(btoa(str)); }));
          return b64;
        };
        const imgs = { med: await grab({ lod: "medium", decoded: false, barbels: "off" }), crs: await grab({ lod: "coarse", decoded: false, barbels: "off" }),
                       bar: await grab({ lod: "medium", decoded: false, barbels: "body" }) };
        const xsP = pts.map((p) => p[0]), ysP = pts.map((p) => p[1]);
        return { size, d, W: Wp, H: Hp, pts, imgs, box: [Math.min(...xsP), Math.min(...ysP), Math.max(...xsP), Math.max(...ysP)] };
      }, [fish.i, px]);
      /* decode and compare in node */
      const dec = (b64) => { const buf = Buffer.from(b64, "base64"), W = r.W, H = r.H, out = new Uint8Array(W * H * 4); for (let y = 0; y < H; y++) out.set(buf.subarray((H - 1 - y) * W * 4, (H - y) * W * 4), y * W * 4); return out; };
      const med0 = dec(r.imgs.med), crs = dec(r.imgs.crs), bar = dec(r.imgs.bar);
      const pad = Math.max(8, Math.round(3 * r.size)), x0 = Math.max(0, Math.floor(r.box[0] - pad)), y0 = Math.max(0, Math.floor(r.box[1] - pad)),
            x1 = Math.min(r.W - 1, Math.ceil(r.box[2] + pad)), y1 = Math.min(r.H - 1, Math.ceil(r.box[3] + pad));
      const cmp = (A, Bm) => { let n = 0, strong = 0, max = 0, sum = 0, cnt = 0, ink = 0;
        for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) { const i = (y * r.W + x) * 4, d = Math.max(Math.abs(A[i] - Bm[i]), Math.abs(A[i + 1] - Bm[i + 1]), Math.abs(A[i + 2] - Bm[i + 2]));
          cnt++; sum += d; if (d) n++; if (d >= 24) strong++; if (d > max) max = d; }
        return { differing: n, strong, max, mean: sum / cnt, area: cnt }; };
      const row = { fish: fish.id, barbels: fish.barb, size: +r.size.toFixed(2), dist: +r.d.toFixed(1), window: [x1 - x0 + 1, y1 - y0 + 1], body: cmp(med0, crs), barbelsDiff: cmp(med0, bar) };
      result.rows.push(row);
      console.log(`  fish ${fish.id}${fish.barb ? "*" : " "} size ${row.size.toFixed(1)} px: medium vs coarse ${row.body.strong} px >= 24 (max ${row.body.max}, mean ${row.body.mean.toFixed(3)}); barbels ${row.barbelsDiff.strong} px >= 24 (max ${row.barbelsDiff.max})`);
      if (fish === fishList[0] && PNGS.indexOf(px) >= 0) {   /* the figure: window of the first fish, medium | coarse | difference x8 (and with barbels) */
        const K = Math.max(2, Math.min(8, Math.floor(420 / (x1 - x0 + 1)))), w = x1 - x0 + 1, h = y1 - y0 + 1, tiles = [med0, crs, "d1", bar, "d2"];
        const TW = tiles.length * w * K + (tiles.length - 1) * 4, TH = h * K, cv = new Uint8Array(TW * TH * 4).fill(255);
        tiles.forEach((tile, t) => { for (let y = 0; y < h * K; y++) for (let x = 0; x < w * K; x++) {
          const sx = x0 + ((x / K) | 0), sy = y0 + ((y / K) | 0), s = (sy * r.W + sx) * 4, d = (y * TW + t * (w * K + 4) + x) * 4;
          let v;
          if (tile === "d1" || tile === "d2") { const B2 = tile === "d1" ? crs : bar, A2 = med0, m = Math.min(255, 8 * Math.max(Math.abs(A2[s] - B2[s]), Math.abs(A2[s + 1] - B2[s + 1]), Math.abs(A2[s + 2] - B2[s + 2]))); v = [m, m, m]; }
          else v = [tile[s], tile[s + 1], tile[s + 2]];
          cv[d] = v[0]; cv[d + 1] = v[1]; cv[d + 2] = v[2]; cv[d + 3] = 255; } });
        fs.writeFileSync(path.join(OUT, `pair_${Math.round(px)}px.png`), png(TW, TH, cv));
      }
    }
  }
  result.errors = errors.slice(0, 5);
  /* medians over the fish, per size */
  result.summary = SIZES.map((sz) => { const rs = result.rows.filter((x) => Math.abs(x.size - sz) < 0.6);
    return { size: sz, fish: rs.length, bodyStrong: med(rs.map((x) => x.body.strong)), bodyStrongPerSize2: med(rs.map((x) => x.body.strong / (x.size * x.size))), bodyMax: med(rs.map((x) => x.body.max)), bodyMean: med(rs.map((x) => x.body.mean)),
             barbStrong: med(rs.map((x) => x.barbelsDiff.strong)), barbMax: med(rs.map((x) => x.barbelsDiff.max)), barbOnlyFish: med(rs.filter((x) => x.barbels).map((x) => x.barbelsDiff.strong)) }; });
  fs.writeFileSync(path.join(OUT, "lodstudy.json"), JSON.stringify(result, null, 1));
  console.log("size  body>=24 (n)  /size^2   max  mean | barbels>=24 (barbel fish)  max");
  for (const s of result.summary) console.log(`${String(s.size).padStart(4)}  ${String(s.bodyStrong).padStart(8)}  ${s.bodyStrongPerSize2.toFixed(2).padStart(8)}  ${String(s.bodyMax).padStart(4)}  ${s.bodyMean.toFixed(3)} | ${String(s.barbStrong).padStart(6)} (${s.barbOnlyFish})  ${s.barbMax}`);
  console.log("page errors: " + JSON.stringify(result.errors));
  await ctx.close(); ctx = null;
} finally { if (ctx) { try { await ctx.close(); } catch (e) { /* closed */ } } release(); }
process.exit(0);

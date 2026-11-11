// tools/ocean_render_perf/crops.mjs OUT.png X,Y,W,H SCALE A.png B.png [C.png ...]: the same crop of several shots.mjs pictures side by
// side, enlarged SCALE times (nearest neighbour), for the before / after figures. Reads only PNGs this tool set wrote (RGBA8, filter 0).
//   node crops.mjs fit_crop.png 380,330,300,170 4 data/300_appearance_fit_ref.png data/300_appearance_fit_all.png data/300_appearance_fit_all_diff16x.png
import fs from "node:fs";
import zlib from "node:zlib";
const [out, box, scale, ...files] = process.argv.slice(2);
const [X, Y, W, H] = box.split(",").map(Number), K = Number(scale);
function readPng(f) {
  const b = fs.readFileSync(f);
  let o = 8, w = 0, h = 0; const idat = [];
  while (o < b.length) { const len = b.readUInt32BE(o), type = b.toString("ascii", o + 4, o + 8); if (type === "IHDR") { w = b.readUInt32BE(o + 8); h = b.readUInt32BE(o + 12); } if (type === "IDAT") idat.push(b.subarray(o + 8, o + 8 + len)); o += 12 + len; }
  const raw = zlib.inflateSync(Buffer.concat(idat)), px = new Uint8Array(w * h * 4);
  for (let y = 0; y < h; y++) { if (raw[y * (w * 4 + 1)] !== 0) throw new Error(f + ": a filtered PNG (not this tool's)"); px.set(raw.subarray(y * (w * 4 + 1) + 1, (y + 1) * (w * 4 + 1)), y * w * 4); }
  return { w, h, px };
}
const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (buf) => { let c = 0xFFFFFFFF; for (let i = 0; i < buf.length; i++) c = CRC[(c ^ buf[i]) & 255] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };
const chunk = (type, data) => { const b = Buffer.alloc(12 + data.length); b.writeUInt32BE(data.length, 0); b.write(type, 4, "ascii"); data.copy(b, 8); b.writeUInt32BE(crc32(b.subarray(4, 8 + data.length)), 8 + data.length); return b; };
const GAP = 6, TW = files.length * W * K + (files.length - 1) * GAP, TH = H * K, canvas = new Uint8Array(TW * TH * 4).fill(255);
files.forEach((f, i) => {
  const p = readPng(f), x0 = i * (W * K + GAP);
  for (let y = 0; y < H * K; y++) for (let x = 0; x < W * K; x++) {
    const s = ((Y + ((y / K) | 0)) * p.w + X + ((x / K) | 0)) * 4, d = (y * TW + x0 + x) * 4;
    canvas[d] = p.px[s]; canvas[d + 1] = p.px[s + 1]; canvas[d + 2] = p.px[s + 2]; canvas[d + 3] = 255;
  }
});
const raw = Buffer.alloc((TW * 4 + 1) * TH);
for (let y = 0; y < TH; y++) Buffer.from(canvas.buffer, y * TW * 4, TW * 4).copy(raw, y * (TW * 4 + 1) + 1);
const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(TW, 0); ihdr.writeUInt32BE(TH, 4); ihdr[8] = 8; ihdr[9] = 6;
fs.writeFileSync(out, Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", zlib.deflateSync(raw, { level: 6 })), chunk("IEND", Buffer.alloc(0))]));
console.log("wrote " + out + " " + TW + "x" + TH);

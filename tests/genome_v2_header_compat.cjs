// A complete saved world, including both digests and its body, through either
// head or a supplied main handoff module. Header length changes with repeats.
'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const crypto = require('node:crypto');
const H = require(path.resolve(process.argv[2] || 'web/ocean_handoff.js'));
(async () => {
  const image = new Uint8Array(65536);
  image.set([1, 2, 3, 4, 5]);
  const saved = await H.encodeWorld({format:H.WORLD.FORMAT, version:H.WORLD.VERSION,
    start:{cfg:{genomeVersion:2}}}, image, {raw:true});
  const text = JSON.stringify(saved.header);
  const variants = [text,
    text.replace('"bytes":65536', '"bytes":65536,"bytes":65536'),
    text.replace('"bytes":65536', '"by\\u0074es":65536,"bytes":65536')];
  const results = [];
  for (const header of variants) {
    const bytes = Buffer.from(header), len = Buffer.alloc(4);
    len.writeUInt32LE(bytes.length);
    const file = new Uint8Array(Buffer.concat([Buffer.from(H.WORLD.MAGIC, 'latin1'), len, bytes,
      ...saved.parts.slice(3).map(p => Buffer.from(p))]));
    const read = await H.readWorld(H.bytesSource(file));
    const body = await read.body();
    assert.deepEqual(read.header, saved.header);
    assert.equal(body.bytes, image.length);
    assert.deepEqual(Buffer.from(body.data), Buffer.from(image.subarray(0, saved.header.image.stored)));
    results.push(crypto.createHash('sha256').update(JSON.stringify(read.header)).update(body.data).digest('hex'));
  }
  assert.equal(new Set(results).size, 1);
  console.log('PASS complete saved-world ordinary duplicate compatibility:', results.join(' '));
})().catch(e => { console.error(e); process.exitCode = 1; });

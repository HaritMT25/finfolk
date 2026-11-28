// Pure policy/header and constant-node checks; real images are covered by Turbo.
'use strict';
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const ROOT = path.resolve(__dirname, '..');
const H = require(path.join(ROOT, 'web/ocean_handoff.js'));
const heap = new ArrayBuffer(65536);
new Float64Array(heap, 8, 2).set([0, 12]);
const M = {
  HEAPU8: new Uint8Array(heap), _oc_sync() {}, _oc_width:()=>640, _oc_height:()=>480, _oc_depth_max:()=>240,
  _oc_creature_count:()=>0, _oc_food_count:()=>0, _oc_predator_count:()=>0,
  _oc_stats_len:()=>2, _oc_stats:()=>8, _oc_num_hidden:()=>12,
  _oc_genome_version:()=>2, _oc_bias_genes:()=>1, _oc_brain_eval_version:()=>2, _oc_weight_mutation_mode:()=>1,
  _oc_creature_segments:()=>0, _oc_creature_depth:()=>0, _oc_body_params:()=>0,
  _oc_creature_colors:()=>0, _oc_creature_ids:()=>0, _oc_food_xy:()=>0, _oc_food_depth:()=>0,
  _oc_predator_data:()=>0, _oc_predator_depth:()=>0
};
const now=H.worldNow(M);
assert.equal(now.policy,'2:1:12:2:saturating','actual exports policy');
assert.equal(H.worldMismatch(now,{...now,policy:'2:0:12:2:saturating'}),'its brain policy differs from its header','header trust');
assert.throws(()=>H.worldNow({...M,_oc_weight_mutation_mode:()=>255}),/unknown exported brain policy/);
const head={format:'evo_ocean_world',version:1,sha256:'a'.repeat(64),
 image:{bytes:65536,stored:0,body:'raw',bodyBytes:0,sha256:'b'.repeat(64)},
 start:{cfg:{genomeVersion:2}}};
function worldFile(text) {
 const bytes=Buffer.from(text),len=Buffer.alloc(4);len.writeUInt32LE(bytes.length);
 return new Uint8Array(Buffer.concat([Buffer.from(H.WORLD.MAGIC,'latin1'),len,bytes]));
}
const clean = JSON.stringify(head);
H.worldHeader(worldFile(clean));
assert.throws(()=>H.worldHeader(worldFile(clean.replace('"genomeVersion":2','"genomeVersion":1,"genomeVersion":2'))),/repeated brain policy member/,'header duplicate');
for (const [label, text] of [
 ['parent', clean.replace('"start":', '"start":{},"start":')],
 ['runCfg', clean.replace('"start":', '"runCfg":{"genomeVersion":2},"runCfg":{"genomeVersion":1},"start":')],
 ['ordinary', clean.replace('"bytes":65536', '"bytes":65536,"bytes":65536')],
 ['escaped', clean.replace('"bytes":65536', '"by\\u0074es":65536,"bytes":65536')]
]) assert.throws(()=>H.worldHeader(worldFile(text)),/repeated header member/,label);
const ctx=vm.createContext({Math});
vm.runInContext(fs.readFileSync(path.join(ROOT,'web/ui_common.js'),'utf8'),ctx);
for (const [w,h] of [[640,300],[300,640]]) {
 const coords=[];const labels=[];
 const canvas=new Proxy({}, {get(t,k){if(k==='measureText')return s=>({width:6*s.length});if(k==='fillText')return s=>labels.push(s);return (...args)=>{for(const v of args)if(typeof v==='number')coords.push(v);};},set(){return true;}});
 const nodes=ctx.EvoUI.drawBrain(canvas,w,h,{conns:[0,127,1,0,1],connCount:1,sensors:Array(41).fill(0),hidden:Array(12).fill(.5),actions:Array(12).fill(0)},
   {nS:41,nH:12,nA:12,fresh:true,gutter:92,font:'sans-serif',actShort:Array(12).fill(''),actLabels:Array(12).fill('')});
 assert(coords.every(Number.isFinite),'bias coordinates finite');
 assert(nodes.some(n=>n.kind==='Bias'&&n.i===127&&n.v===1),'constant hover identity');
 assert.equal(labels.filter(t=>t==='+1').length,1,'one labelled constant');
}
console.log('genome v2 headers and UI: all assertions passed');

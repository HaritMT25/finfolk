// Ocean Setup placement and byte preservation, no browser or npm.
// node tests/ocean_setup_shape_tests.cjs [--base build_ux3/base/web]
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const Module = require('node:module');
const harnessFile = path.join(__dirname, 'ocean_turbo_handoff.js');
const head = require(harnessFile);
function harnessAt(web) {
    // Reuse the SAME test DOM and accessors on both real source trees.
    const m = new Module(harnessFile, module);
    m.filename = harnessFile; m.paths = module.paths;
    const source = fs.readFileSync(harnessFile, 'utf8').replace("process.env.OCEAN_TEST_WEB || path.join(ROOT, 'web')", JSON.stringify(path.resolve(web)));
    m._compile(source, harnessFile);
    return m.exports;
}
const Q = '?guide=0&intro=0&seed=42&pop=12&w=300&h=300';
function stop(h) { for (const p of h.PAGES.splice(0)) for (const w of p.workers.concat(p.probes)) if (!w.terminated) w.terminate(); }
function input(h, p) {
    const f = p.T.readForm();
    return JSON.stringify([f.seed >>> 0, f.width, f.height, f.depth, f.population, h.HO.cfgJson(f.cfg)]);
}
function fill(h, p, cfg) {
    p.T.resetForm();
    p.T.cfgToForm(cfg);
    p.T.updateNeeds();
    return input(h, p);
}
function rand(p, seed) {
    vm.runInContext(`Math.random = (function () { var s = ${seed}; return function () { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296; }; })();`, p.ctx);
}
(async () => {
    const { CFG } = head;
    assert.equal(CFG.TABS.map(t => t.title).join(' · '), 'Run · World · Food · Life · Predators · Water');
    assert.equal(CFG.TABS.map(t => t.id).join(), 'run,world,food,life,predators,ocean');
    const homes = new Map();
    for (const t of CFG.TABS) for (const [g, keys] of t.groups || []) for (const k of keys) {
        assert(!homes.has(k), 'duplicate field ' + k); homes.set(k, [t.id, g]);
    }
    assert.deepEqual([...homes.keys()].sort(), Object.keys(CFG.KEYS).sort());
    const groups = [
        ['world', 'The world', ['seed', 'population', 'width', 'height', 'depth']],
        ['world', 'Tank & boundaries', ['walls', 'sideWallBand', 'sideWallTurnRate', 'wallBand', 'toroidal']],
        ['world', 'Swimming & steering', ['minSpeed', 'maxSpeed', 'triangularMotion', 'maxTurnRate', 'pitchMax', 'vDrag', 'steerFrame']],
        ['world', 'Senses', ['perceptionRadius', 'interactRadius', 'maxNeighbors']],
        ['world', 'Eye', ['eye', 'eyeOnly', 'eyeCode']],
        ['food', 'Who can eat', ['mouthGate', 'kMouth']],
        ['life', 'Body size', ['bodyModel', 'bodyMutation', 'sizeFight', 'sizeDrift']],
        ['ocean', 'Buoyancy & depth', ['kBuoy', 'buoyMutation', 'cHold', 'cPress', 'depthCostScaled']],
        ['ocean', 'Underwater light', ['lightEnabled', 'L0', 'kWater']]
    ];
    const p = await head.bootPage(Q);
    for (const [tab, group, keys] of groups) for (const k of keys) {
        assert.deepEqual(homes.get(k), [tab, group]);
        if (!['eye', 'eyeOnly', 'eyeCode'].includes(k)) assert(p.el('panel-' + tab).contains(p.el('f_' + k)), k + ' DOM home');
    }
    assert.equal(CFG.HINTS.depth, '10 to 100000 · the surface is 0');
    assert.deepEqual(CFG.KEYS.steerFrame[1].options, ['World axes (2-D style)', "Fish's own heading"]);
    assert.equal(CFG.LABELS.currentCore, 'Eddy radius / wall fade');
    for (const k of ['eye', 'eyeOnly', 'eyeCode']) {
        assert.equal(p.el('f_' + k), null, k + ' row absent in plain build');
        assert(p.el('o_' + k).closest('#eye-settings').hidden, k + ' config retained invisibly');
    }
    const eye = await head.bootPage(Q, { hasEye: true });
    for (const k of ['eye', 'eyeOnly', 'eyeCode']) assert(eye.el('f_' + k) && !eye.el('eye-settings').hidden);
    const inert = k => p.el('f_' + k).classList.contains('inert');
    const note = k => p.el('f_' + k).querySelector('.needs').textContent;
    assert(!inert('mouthGate') && !inert('predatorEconomy'));
    assert.equal(note('predatorEconomy'), 'Pair with starting predators or a floor');
    p.edit('mouthGate', true);
    assert(!inert('mouthGate') && !inert('kMouth') && /no effect/.test(note('mouthGate')));
    p.edit('kMouth', 0.5);
    assert(!inert('mouthGate') && !inert('kMouth') && note('mouthGate') === '');
    p.edit('predatorEconomy', true); p.edit('predatorMinPopulation', 2);
    assert(!inert('predatorEconomy') && note('predatorEconomy') === '');
    p.T.stageScenario('standard');   // staged controls describe only the next world
    p.edit('triangularMotion', true); assert(inert('steerFrame'));
    p.edit('triangularMotion', false); assert(!inert('steerFrame'));
    for (const [old, next] of [['depth', 'ocean'], ['senses', 'world'], ['water', 'ocean'], ['ocean', 'ocean'], ['bad', 'run']]) {
        const stored = await head.bootPage(Q, { storage: { 'evo_boids.ocean.tab': old } });
        assert.equal(stored.el('tab-' + next).getAttribute('aria-selected'), 'true');
        assert.equal(stored.ctx.localStorage.getItem('evo_boids.ocean.tab'), next);
        const linked = await head.bootPage(Q + '#tab-' + old);
        assert.equal(linked.el('tab-' + next).getAttribute('aria-selected'), 'true');
    }
    p.ctx.location.hash = '#tab-senses'; p.ctx.dispatchEvent(new p.Ev('hashchange'));
    assert.equal(p.el('tab-world').getAttribute('aria-selected'), 'true');
    p.click('viewclarity'); assert.equal(p.T.openPop, 'view'); assert.equal(p.doc.activeElement.id, 'clarity');
    p.click('claritysetup'); assert.equal(p.T.openPop, null); assert.equal(p.doc.activeElement.id, 'o_lightEnabled');
    assert.equal(p.el('tab-ocean').getAttribute('aria-selected'), 'true');
    const statuses = p.el('panel-ocean').querySelectorAll('.setup-status').map(e => e.textContent);
    assert.deepEqual(statuses, ['physics only · not drawn yet', 'physics only · not drawn yet', 'looks only']);
    assert(p.el('e1add').parentElement.className === 'sub');
    const html = fs.readFileSync(path.join(__dirname, '../web/ocean.html'), 'utf8');
    assert(/#tabs\s*\{[^}]*overflow-x:\s*auto/.test(html), 'phone tab strip still scrolls');
    assert(/#tabs button\s*\{[^}]*white-space:\s*nowrap/.test(html), 'six tab labels stay on one line each (the strip scrolls instead)');
    assert(/\.panel \.sub\s*\{[^}]*color:\s*var\(--ink-3\)/.test(html), "a group's note is styled as a muted hint");
    assert(!/<body[\s\S]*<style>[\s\S]*setup-status/.test(html.slice(html.indexOf('<body'))), 'the status pill style lives in the head');
    assert.equal(p.uncaught.length + eye.uncaught.length, 0);
    console.log('PASS six tabs; every key exactly once; moved DOM homes; eye gating in both capabilities; advice, aliases, clarity links, pills, scrolling');
    const baseArg = process.argv.indexOf('--base');
    if (baseArg >= 0) {
        const base = harnessAt(process.argv[baseArg + 1]);
        try {
            const b = await base.bootPage(Q), h = await head.bootPage(Q);
            // Options may be renamed; key definitions, defaults, timing and ranges must stay identical.
            const numerical = c => JSON.stringify(Object.entries(c.KEYS).map(([k, [d, o]]) => [k, d, Object.assign({}, o, o && o.options ? { options: o.options.map((_, i) => i) } : {})]));
            assert.equal(numerical(base.CFG), numerical(CFG));
            assert.equal(JSON.stringify(base.CFG.LIVE), JSON.stringify(CFG.LIVE));
            assert.equal(JSON.stringify(base.CFG.NEG_ON_RESTART), JSON.stringify(CFG.NEG_ON_RESTART));
            const tanks = [[1920,1080,240,true], [1080,1920,240,true], [300,300,60,true], [300,300,240,false], [5000,3000,400,true], [3840,2160,240,false]];
            let recipes = 0;
            for (const [w, l, d, walls] of tanks) for (let i = 0; i < 40; i++) for (const id of ['standard','bigtank','e1','hunters','currents','surprise']) {
                for (const q of [b, h]) {
                    q.T.resetForm();
                    for (const [k,v] of Object.entries({ width:w, height:l, depth:d, walls, seed:100+i, sideWallBand:40, sideWallTurnRate:3 })) q.T.setVal(k,v);
                    rand(q, 789 + i); q.T.stageScenario(id);
                }
                assert.equal(input(base, b), input(head, h), 'engine input: ' + id + '/' + [w,l,d,walls,i]);
                recipes++;
            }
            console.log('PASS ' + recipes + ' recipes/cards/Surprise draws: real staging → readForm → cfgJson bytes identical');
            let edits = 0;
            for (const [k,[d,o]] of Object.entries(CFG.KEYS)) {
                if (['seed','population','width','height','depth'].includes(k)) continue;
                const vals = typeof d === 'boolean' ? [false,true] : o && o.bit ? [0,1] : o && o.options ? o.options.map((_,i) => i) : [d, o && o.min !== undefined ? o.min : Math.max(0,d/2), d + (o && o.step || 1)];
                for (const v of vals) { assert.equal(fill(base,b,{[k]:v}), fill(head,h,{[k]:v}), k + '=' + v); edits++; }
            }
            for (const k of ['seed','population','width','height','depth']) {
                const [d,o] = CFG.KEYS[k];
                for (const v of [d,o.min,o.max === undefined ? (k === 'seed' ? 4294967295 : 100000) : o.max]) {
                    for (const q of [b,h]) { q.T.resetForm(); q.T.setVal(k,v); }
                    assert.equal(input(base,b), input(head,h), 'edited argument ' + k + '=' + v); edits++;
                }
            }
            for (const cfg of [{labelFrame:0}, {steerFrame:1,labelFrame:1}, {labelFrame:1,foodEnergy:7}, {eye:0,eyeOnly:0,eyeCode:0}, {zzz:3,labelFrame:0}]) {
                assert.equal(fill(base,b,cfg), fill(head,h,cfg), 'imported extras'); edits++;
            }
            console.log('PASS ' + edits + ' edited/imported settings: engine input bytes identical');
            // Actual card starts and saves, including live edits and setup-file imports.
            for (const id of ['standard','bigtank','e1','hunters','currents','surprise']) {
                for (const q of [b,h]) { q.T.resetForm(); rand(q, 2026); q.T.stageScenario(id); const n = q.inits.length; q.click('scenario-start'); if (q.T.asking) q.click('startconfirm'); assert.equal(q.inits.length, n + 1, id + ' really starts'); }
                assert.equal(JSON.stringify(b.T.initArgs), JSON.stringify(h.T.initArgs), id + ' actual init args');
                assert.equal(b.inits.at(-1), h.inits.at(-1), id + ' actual engine JSON');
                b.click('savecp'); h.click('savecp');
                assert.equal(b.blobs.at(-1), h.blobs.at(-1), id + ' saved setup bytes');
            }
            // every key this PR moved, edited through its own field: the same engine messages and saved bytes as base
            const moved = ['pitchMax','vDrag','wallBand','steerFrame','mouthGate','kMouth','sizeFight','sizeDrift','buoyMutation',
                           'bodyModel','bodyMutation','cHold','cPress','depthCostScaled','foodDepthMode','foodDepthSpread'];
            const nextVal = (k) => { const [d,o] = CFG.KEYS[k];
                if (typeof d === 'boolean') return !d;
                if (o && o.options) return d === 0 ? 1 : 0;
                const v = d + (o && o.step || 1); return o && o.max !== undefined ? Math.min(v, o.max) : v; };
            for (const q of [b,h]) { q.edit('minSpeed',40); q.edit('kBuoy',-0.5); for (const k of moved) q.edit(k, nextVal(k)); q.click('savecp'); }
            assert.equal(JSON.stringify(b.sets), JSON.stringify(h.sets), 'live engine messages (minSpeed, kBuoy and every moved key)');
            assert.equal(b.blobs.at(-1), h.blobs.at(-1), 'live edit save bytes');
            for (const cfg of [{labelFrame:0}, {labelFrame:1,foodEnergy:7}, {eye:0,eyeOnly:0,eyeCode:0}]) {
                const file = JSON.stringify({format:'evo_ocean_setup',version:2,seed:42,population:12,width:300,height:300,depth:240,walls:false,config:cfg});
                for (const [hh,q] of [[base,b],[head,h]]) { await hh.stageFile(q,file); const n = q.inits.length; q.start(); assert.equal(q.inits.length, n + 1, 'import really starts'); q.click('savecp'); }
                assert.equal(b.inits.at(-1), h.inits.at(-1), 'import init');
                assert.equal(b.blobs.at(-1), h.blobs.at(-1), 'import save bytes');
            }
            assert.equal(b.uncaught.length + h.uncaught.length, 0);
            console.log('PASS actual card starts, live engine messages, imported setups and saved setup bytes identical');
        } finally { stop(base); }
    }
})().then(() => { stop(head); }).catch(e => { stop(head); console.error(e); process.exitCode = 1; });

#!/usr/bin/env python3
"""Named, disposable-copy mutants: compile success and the intended assertion.

The source tree is never mutated. Each control/mutant has a recorded exit/log.
Run after `cmake --preset native-serial && cmake --build --preset native-serial --parallel 2`:
    nice -n 19 python3 tests/genome_v2_fault.py
Requires c++, Python 3 and Node; no private build artifacts are used.
Use --only NAME to narrow feedback; the default runs the full named inventory.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
# name, file, exact-once old, replacement, target, required assertion
MUTANTS = [
 ('table_bit','src/core/weight_log_table.hpp','0x3f800000u','0x3f800001u','codec','FAIL table law'),
 ('table_hash','src/core/weight_log_table.hpp','kTableSha256[] = "','kTableSha256[] = "0','table','generated identity mismatch'),
 ('negative_zero','src/core/weight_log.hpp','return encoded == 0u ||','return q == 0u ||','codec','FAIL validity'),
 ('q_overflow','src/core/weight_log.hpp','q <= kMaximumQ);','q <= kMaximumQ + 1);','codec','FAIL validity'),
 ('decoder_exponent','src/core/weight_log.hpp','111u + (u >> 10)','112u + (u >> 10)','codec','FAIL decoder bits'),
 ('quantize_tie','src/core/weight_log.hpp','magnitude - lower <= upper - magnitude','magnitude - lower < upper - magnitude','midpoints','FAIL midpoint lower magnitude'),
 ('legacy_codec','src/core/genome.hpp',': weight / 8192.0f;',': logweight::decodeValid(logweight::word(weight));','tests','legacy codec'),
 ('legacy_packing','src/core/genome.hpp','static constexpr int SRC_BITS = 6;','static constexpr int SRC_BITS = 7;','tests','legacy packing'),
 ('tag_sink','src/core/genome.hpp','(srcSink & 0x7fffu) >> bits','srcSink >> bits','tests','tagged endpoint roundtrip'),
 ('canonical_modulo','src/core/genome.hpp','? gene.sourceNum < senses','? gene.sourceNum <= senses','tests','atomic canonical rejection'),
 ('bias_disabled','src/core/genome.hpp','(schema.biasGenes && gene.sourceNum == 127)','(gene.sourceNum == 127)','tests','disabled bias rejection'),
 ('bias_ticket','src/core/genome.hpp','random.uint(15u) == 0u','random.uint(14u) == 0u','tests','RNG transcript bounds/order'),
 ('bias_value','src/core/genome.hpp','vals[NUM_SENSES + MAX_INTERNAL_NEURONS] = 1.0f;','vals[NUM_SENSES + MAX_INTERNAL_NEURONS] = 0.0f;','tests','bias driven retained recurrence'),
 ('zero_not_driven','src/core/genome.hpp','if (sink >= A) next.neurons[sink - A].driven = true;','if (sink >= A && gene.weight != 0) next.neurons[sink - A].driven = true;','tests','zero incoming drives'),
 ('unstable_sum','src/core/genome.hpp','    destination = std::move(next);','    std::stable_sort(next.flat.begin(), next.flat.end(), [](const auto& a, const auto& b) { return a.sink() != b.sink() ? a.sink() < b.sink() : std::fabs(a.w()) > std::fabs(b.w()); });\n    destination = std::move(next);','tests','synchronous stable accumulation'),
 ('same_step_hidden','src/core/genome.hpp','accum[conn.sink()] += vals[conn.src()] * conn.w();','accum[conn.sink()] += vals[conn.src()] * conn.w();\n        if (conn.sink() >= NUM_ACTIONS) vals[NUM_SENSES + conn.sink() - NUM_ACTIONS] = evomath::tanhf(accum[conn.sink()]);','tests','bias driven retained recurrence'),
 ('undriven_reset','src/core/genome.hpp','n.output = n.driven ? act[NUM_ACTIONS + i] : n.output;','n.output = act[NUM_ACTIONS + i];','tests','bias driven retained recurrence'),
 ('contact_no_advance','src/core/kernel.hpp','    feedForward(c2.nnet, s2, a2);','    std::fill(a2, a2 + NUM_ACTIONS, 0.0f);','tests','contacts advance recurrence twice'),
 ('point_wrap','src/core/weight_log.hpp','static_cast<int>(q) + delta, 1,','(static_cast<int>(q) + delta) & 0x7fff, 1,','tests','mutation result'),
 ('zero_revival','src/core/weight_log.hpp','kRevivalQ = 12289u','kRevivalQ = 12288u','tests','mutation result'),
 ('duplicate_zero_draw','src/core/genome.hpp','const int delta = random.intRange(-64, 64);','const int delta = duplicate.weight == 0 ? 0 : random.intRange(-64, 64);','tests','RNG transcript omitted draw'),
 ('conditional_gate','src/core/genome.hpp','if (random.unit() < 2.0f * rate\n        && static_cast<int>(genome.size()) < maxLen)','if (static_cast<int>(genome.size()) < maxLen\n        && random.unit() < 2.0f * rate)','tests','RNG transcript omitted draw'),
 ('mutation_order','src/core/genome.hpp','const int position =\n            random.intRange(0, static_cast<int>(genome.size()));','const float stolenGate = random.unit(); (void)stolenGate;\n        const int position = random.intRange(0, static_cast<int>(genome.size()));','tests','RNG transcript bounds/order'),
 ('early_pr3_rewire','src/core/genome.hpp','gene = makeCanonicalGene(\n                random, genome.schema, senses, actions);','gene = (random.uint(4u), makeCanonicalGene(\n                random, genome.schema, senses, actions));','tests','RNG transcript bounds/order'),
 ('schema_lost','src/core/genome.hpp','child.schema = parent1.schema;','child.schema = {};','tests','crossover schema'),
 ('mask_stale','src/core/genome.hpp','if (gene.sourceType) next.srcTypeBits[i >> 6] |= bit;','if (false) next.srcTypeBits[i >> 6] |= bit;','tests','founder masks'),
 ('signed_v2_json','src/core/checkpoint_io.hpp','w.value(c.genome.schema.genomeVersion == 2\n                ? static_cast<long long>(logweight::word(g.weight)) : static_cast<long long>(g.weight));','w.value(static_cast<long long>(g.weight));','tests','v2 checkpoint roundtrip'),
 ('late_preflight','src/core/checkpoint_io.hpp','if (!v3::preflight(j, policyConfig, error, &policyConversion))','world.init(640, 480, 0);\n        if (!v3::preflight(j, policyConfig, error, &policyConversion))','tests','checkpoint preflight'),
 ('analysis_reset','src/core/checkpoint_io.hpp','world.initForCheckpoint(width, height);','world.initForCheckpoint(width, height);\n        world.cfg.clusterMap = world.cfg.reproLog = false;','tests','caller analysis settings retained'),
 ('transplant_override','src/core/transplant.hpp','if (yc.weightMutationMode != cfg.weightMutationMode || brainSchema(yc) != brainSchema(cfg) ||\n            yc.hiddenNeurons != cfg.hiddenNeurons || yc.brainEvalVersion != cfg.brainEvalVersion)','if (!o.allowMismatch && (yc.weightMutationMode != cfg.weightMutationMode || brainSchema(yc) != brainSchema(cfg) ||\n            yc.hiddenNeurons != cfg.hiddenNeurons || yc.brainEvalVersion != cfg.brainEvalVersion))','tests','transplant schema mismatch override'),
 ('conversion_rng','src/core/genome_v2_conversion.hpp','world.creatures.swap(prey);','rng.unit();\n    world.creatures.swap(prey);','tests','conversion RNG unchanged'),
 ('conversion_state','src/core/genome_v2_conversion.hpp','creature.nnet = std::move(net);','creature.nnet = std::move(net); creature.lineageId = 0;','tests','conversion state and lineage'),
 ('bias_reach_oob','src/ocean/ocean_world.hpp','src < NUM_SENSES + MAX_INTERNAL_NEURONS && reach[src - NUM_SENSES]','reach[src - NUM_SENSES]','reach',"runtime error: index 12 out of bounds for type 'bool [12]'"),
 ('header_trust','web/ocean_handoff.js','if (a.policy !== e.policy) return "its brain policy differs from its header";','if (false) return "its brain policy differs from its header";','header','header trust'),
 ('header_duplicate','web/ocean_handoff.js','if (policyKeys.indexOf(r.key) >= 0 &&','if (false && policyKeys.indexOf(r.key) >= 0 &&','header','header duplicate'),
 ('policy_assign_then_validate','src/ocean/ocean_config.hpp','SimConfig& sc = nextSim;','SimConfig& sc = simConfig;','ocean_policy','policy refusal preserves all config bytes'),
 ('policy_input_only_staging','src/ocean/ocean_config.hpp',
  'SimConfig& sc = nextSim;\n    OceanConfig& oc = nextOcean;',
  'const auto* config = root.find("config");\n    const bool policyInput = config && (config->find("genomeVersion") || config->find("biasGenes") || config->find("hiddenNeurons") || config->find("brainEvalVersion"));\n    SimConfig& sc = policyInput ? nextSim : simConfig;\n    OceanConfig& oc = policyInput ? nextOcean : oceanConfig;',
  'ocean_policy','policy refusal preserves all config bytes'),
]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--only', action='append', default=[]);args=parser.parse_args()
    names={m[0] for m in MUTANTS}
    if set(args.only)-names: parser.error('unknown mutant')
    selected=[m for m in MUTANTS if not args.only or m[0] in args.only]
    work=Path(tempfile.mkdtemp(prefix='genome_v2_fault.'))
    print('evidence:',work,flush=True)
    def run(label,cmd,cwd,expected=0,match=None):
        start=time.monotonic();p=subprocess.run(cmd,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (work/(label+'.log')).write_text(p.stdout)
        (work/(label+'.command')).write_text(repr(cmd)+'\n')
        (work/(label+'.result')).write_text(f'exit={p.returncode}\nwall={time.monotonic()-start:.3f}\n')
        if (expected==0 and p.returncode!=0) or (expected!=0 and p.returncode!=expected) or (match and match not in p.stdout):
            raise SystemExit(f'{label}: unexpected exit/assertion {p.returncode}\n{p.stdout[-3000:]}')
    generator=work/'gen_log_weight_table'
    if any(m[4]=='table' for m in selected):
        run('generator.compile',['c++','-O1','-std=c++20','-ffp-contract=off','-I',str(ROOT/'src'),str(ROOT/'tools/gen_log_weight_table.cpp'),'-o',str(generator)],ROOT)
    def check(label,tree,target,mutated=False,match=None):
        if target=='header':cmd=['node','tests/genome_v2_header_tests.cjs']
        elif target=='midpoints':
            # Run the named midpoint assertion directly: the exhaustive codec
            # test also catches this defect at a legacy input before reaching
            # its midpoint loop. Control and mutant compile the same fixture.
            source=work/'midpoints.cpp'
            source.write_text('''#include <bit>
#include <cmath>
#include <cstdio>
#include "core/weight_log.hpp"
int main() {
    double lower = 0;
    for (unsigned q = 0; q < 25601; ++q) {
        const double upper = std::ldexp(double(std::bit_cast<float>(logweight::kTable[q % 1024])), int(q / 1024) - 16);
        const double mid = (lower + upper) / 2;
        if (logweight::quantize(mid) != q || logweight::quantize(-mid) != (q ? q | 32768u : 0)) {
            std::puts("FAIL midpoint lower magnitude"); return 1;
        }
        lower = upper;
    }
    std::puts("PASS midpoint lower magnitude, both signs, all 25601 boundaries");
}
''')
            exe=work/(label+'.bin')
            run(label+'.compile',['c++','-O1','-std=c++20','-ffp-contract=off','-I',str(tree/'src'),str(source),'-o',str(exe)],tree)
            cmd=[str(exe)]
        else:
            name='genome_v2_codec' if target in ('codec','table') else 'genome_v2_reach' if target=='reach' else 'ocean_tests' if target=='ocean_policy' else 'genome_v2_tests'
            exe=work/(label+'.bin')
            flags=['-DEVO_WORLD_OCEAN','-fsanitize=undefined,bounds','-fno-sanitize-recover=all'] if target=='reach' else ['-DEVO_WORLD_OCEAN'] if target=='ocean_policy' else []
            run(label+'.compile',['c++','-O1','-std=c++20','-ffp-contract=off','-I','src',*flags,'tests/'+name+'.cpp','-o',str(exe)],tree)
            cmd=[str(exe)]
            if target=='ocean_policy':cmd+=['--only','genome_v2']
            if target=='table':cmd=['python3','tools/gen_log_weight_table.py','--check',str(generator)]
        run(label,cmd,tree,1 if mutated else 0,match if mutated else None)
    # Prove the acceptance checker refuses failures that cannot be credited as
    # mutant catches, including a different assertion with the same exit code.
    bad_source=work/'runner_compile_failure.cpp'
    bad_source.write_text('#error deliberate runner compile-failure control\n')
    probes=[
        ('runner_compile_failure',['c++','-fsyntax-only',str(bad_source)],0,None),
        ('runner_unrelated_crash',[sys.executable,'-c',
          'import os, resource, signal; resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); os.kill(os.getpid(), signal.SIGSEGV)'],1,'FAIL intended assertion'),
        ('runner_unrelated_assertion',[sys.executable,'-c',
          'import sys; print("FAIL unrelated assertion"); sys.exit(1)'],1,'FAIL intended assertion'),
    ]
    for label,cmd,expected,match in probes:
        try:
            run(label,cmd,ROOT,expected,match)
        except SystemExit as error:
            (work/(label+'.rejected')).write_text(str(error)+'\n')
        else:
            raise SystemExit(label+': runner incorrectly credited a non-catch')
        print('runner rejected',label,flush=True)
    for target in sorted({m[4] for m in selected}):check('control_before_'+target,ROOT,target)
    for name,file,old,new,target,match in selected:
        tree=work/name;tree.mkdir()
        for directory in ['src','tests','wasm','web','tools']:
            shutil.copytree(ROOT/directory,tree/directory,ignore=shutil.ignore_patterns('*.wasm','evo_boids*.js','evo_ocean.js','node_modules','__pycache__'))
        path=tree/file;source=path.read_text()
        count=source.count(old)
        # Both explicit population writers are deliberately planted together.
        expected_count=1
        if count!=expected_count:raise SystemExit(f'{name}: anchor count {count}, wanted {expected_count}')
        source=source.replace(old,new)
        if name=='policy_input_only_staging':
            commit='    simConfig = nextSim;\n    oceanConfig = nextOcean;'
            if source.count(commit)!=1: raise SystemExit(name+': publication anchor mismatch')
            source=source.replace(commit,'    if (policyInput) {\n        simConfig = nextSim;\n        oceanConfig = nextOcean;\n    }')
        path.write_text(source)
        check(name,tree,target,True,match)
        shutil.rmtree(tree)
        print('caught',name,flush=True)
    for target in sorted({m[4] for m in selected}):check('control_after_'+target,ROOT,target)
    print(f'PASS: {len(selected)} compiled named mutants; controls before/after')
if __name__=='__main__':main()

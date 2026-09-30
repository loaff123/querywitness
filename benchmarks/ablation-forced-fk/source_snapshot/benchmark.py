"""Equal-trial-budget synthetic evaluation with complete run records.

Random and boundary methods use identical seeds and never stop at a first hit.
The single benign fixture is reported separately, not called an equal-budget
baseline. Replicates are seed sweeps on the same 12 tasks, not independent tasks.
"""
from pathlib import Path
from dataclasses import asdict
import json
import platform
import sqlite3
import time
from . import __version__
from .catalog import load_catalog, validate_catalog
from .schema import Schema
from .engine import ExecutionLimits, execute
from .compare import compare_results
from .generate import generate_instance
from .reduce import minimize
from .artifacts import digest, build_witness, write_bundle
from .semantics import PARSER_VERSION


def run_benchmark(destination,*,trials=16,repeats=8,seed=20260930,max_rows=8,family_ids=None):
    if type(trials) is not int or not 1<=trials<=1000: raise ValueError('Trials must be 1–1000')
    if type(repeats) is not int or not 1<=repeats<=100: raise ValueError('Repeats must be 1–100')
    if type(seed) is not int or not 0<=seed<2**63-trials*repeats: raise ValueError('Invalid seed')
    catalog=load_catalog();checks=validate_catalog()
    if checks['failures']:raise ValueError('Catalog oracle validation failed: '+str(checks['failures']))
    cases=[c for c in catalog['cases'] if family_ids is None or c['id'] in family_ids]
    if not cases:raise ValueError('No catalog families selected')
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False);(destination/'raw').mkdir()
    limits=ExecutionLimits();all_runs=[];by_family=[];benign_detected=0;start=time.perf_counter()
    for case in cases:
        schema=Schema.from_dict(case['schema']);records=[];family={'id':case['id'],'title':case['title'],'methods':{}}
        a=execute(schema,case['benign'],case['reference'],limits);b=execute(schema,case['benign'],case['mutant'],limits)
        benign=compare_results(a,b,'bag');family['benign_status']=benign['status'];benign_detected+=benign['status']=='mismatch'
        records.append({'family':case['id'],'method':'single_benign','variant':'mutant','status':benign['status'],'instance_sha256':digest(case['benign']),'reference_status':a.status,'candidate_status':b.status})
        saved=False
        for method in ('random','boundary'):
            family['methods'][method]={}
            for variant in ('mutant','equivalent_control'):
                runs=[]
                for repeat in range(repeats):
                    run={'family':case['id'],'method':method,'variant':variant,'repeat':repeat,'trials':[],'first_mismatch':None,'mismatches':0,'inconclusive':0}
                    run_start=time.perf_counter()
                    for trial in range(trials):
                        trial_seed=seed+repeat*trials+trial
                        data=generate_instance(schema,trial_seed,method,max_rows)
                        a=execute(schema,data,case['reference'],limits);b=execute(schema,data,case[variant],limits)
                        result=compare_results(a,b,'bag');status=result['status']
                        # Compact raw columns are declared in the manifest. Every trial is retained.
                        run['trials'].append([trial_seed,status,digest(data),sum(map(len,data.values())),a.status,b.status])
                        if status=='inconclusive':run['inconclusive']+=1
                        if status=='mismatch':
                            run['mismatches']+=1
                            if run['first_mismatch'] is None:run['first_mismatch']=trial+1
                            if variant=='mutant' and not saved:
                                reduction=minimize(schema,data,case['reference'],case[variant],limits=limits)
                                reduction_meta={k:v for k,v in reduction.items() if k!='instance'}
                                witness=build_witness(schema,reduction['instance'],case['reference'],case[variant],limits=limits,
                                    search={'seed':trial_seed,'strategy':method,'trial_budget':trials,'max_rows':max_rows},reduction=reduction_meta)
                                write_bundle(witness,destination/'witnesses'/case['id']);saved=True
                    run['elapsed_seconds']=round(time.perf_counter()-run_start,6)
                    records.append(run);all_runs.append(run);runs.append(run)
                family['methods'][method][variant]={'runs':len(runs),'detected_runs':sum(r['first_mismatch'] is not None for r in runs),'instance_evaluations':sum(len(r['trials']) for r in runs),'mismatch_instances':sum(r['mismatches'] for r in runs),'inconclusive_instances':sum(r['inconclusive'] for r in runs),'first_mismatch_trials':[r['first_mismatch'] for r in runs]}
        by_family.append(family)
        (destination/'raw'/(case['id']+'.jsonl')).write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in records),encoding='utf-8')
    summary={'format_version':1,'tool_version':__version__,'catalog_sha256':digest(catalog),'families':len(cases),
        'trials_per_run':trials,'repeats':repeats,'seed':seed,'max_rows':max_rows,
        'matched_budget_runs':len(all_runs),'matched_budget_instance_evaluations':sum(len(r['trials']) for r in all_runs),
        'control_mismatches':sum(r['mismatches'] for r in all_runs if r['variant']=='equivalent_control'),
        'inconclusive_instances':sum(r['inconclusive'] for r in all_runs),'benign_detected_families':benign_detected,
        'method_detection':{method:{'detected_family_runs':sum(r['first_mismatch'] is not None for r in all_runs if r['method']==method and r['variant']=='mutant'),'total_family_runs':len(cases)*repeats,'detected_distinct_families':sum(f['methods'][method]['mutant']['detected_runs']>0 for f in by_family)} for method in ('random','boundary')},
        'by_family':by_family,'elapsed_seconds':round(time.perf_counter()-start,6),
        'interpretation':'Synthetic regression coverage only. Seed repetitions are not independent tasks. No LLM, SOTA, population-generalization, or equivalence-proof claim.'}
    manifest={'format':'querywitness/benchmark','format_version':1,'tool_version':__version__,'catalog_sha256':digest(catalog),
        'python_version':platform.python_version(),'sqlite_version':sqlite3.sqlite_version,'sqlglot_version':PARSER_VERSION,'platform':platform.platform(),
        'configuration':{'trials':trials,'repeats':repeats,'seed':seed,'max_rows':max_rows,'families':[c['id'] for c in cases],'execution_limits':asdict(limits)},
        'raw_trial_columns':['seed','comparison_status','instance_sha256','input_rows','reference_status','candidate_status'],
        'baseline_notes':'Single benign is one hand-authored masking fixture per family. Random and boundary are equal trial-budget paired seed sweeps; neither stops after a hit. Witness reduction is outside the comparison budget and included in wall time.',
        'oracle_validation':checks,'file_sha256':{str(p.relative_to(destination)).replace('\\','/'):__import__('hashlib').sha256(p.read_bytes()).hexdigest() for p in sorted((destination/'raw').glob('*.jsonl'))}}
    for name,value in [('summary.json',summary),('manifest.json',manifest)]:
        (destination/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    lines=['# QueryWitness synthetic evaluation','',summary['interpretation'],'',f"{len(cases)} families; {trials} instances per method/run; {repeats} seed repeats. Random and boundary each have {len(cases)*repeats} mutant runs. Every generated instance is also tested against its equivalent control.",'',f"Actual instance comparisons: {summary['matched_budget_instance_evaluations']}; control mismatches: {summary['control_mismatches']}; inconclusive comparisons: {summary['inconclusive_instances']}.",'','| Method | Detected family-runs | Distinct families detected |','|---|---:|---:|']
    for method,r in summary['method_detection'].items():lines.append(f"| {method} | {r['detected_family_runs']} / {r['total_family_runs']} | {r['detected_distinct_families']} / {len(cases)} |")
    lines+=['',f"The separate single-benign-fixture baseline detected {benign_detected}/{len(cases)} mutants. Masking fixtures were authored to illustrate one-database blindness; this is not evidence about arbitrary production datasets.",'','## Per-family detection runs','', '| Family | Random | Boundary |','|---|---:|---:|']
    for f in by_family:lines.append(f"| {f['id']} | {f['methods']['random']['mutant']['detected_runs']}/{repeats} | {f['methods']['boundary']['mutant']['detected_runs']}/{repeats} |")
    lines+=['','## Reproduction and limitations','','Run the command in docs/REPRODUCIBILITY.md with the configuration in manifest.json. Compare raw seeds, status, data hashes and observations; elapsed times and environment metadata vary. No confidence interval is supplied: repeats reuse the same tasks, and the 12 tasks are purposively selected, not sampled. There is no held-out real-workload set. Generator domains are supplied by each catalog schema. Neither strategy is query-aware or complete. Equivalent controls are mathematical constructions, not a statistical estimate of the false-positive rate on all SQL.','']
    (destination/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    return summary

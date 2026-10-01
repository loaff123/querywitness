"""Recompute every reported metric from retained all-trial records."""
from collections import Counter,defaultdict
import gzip
import itertools
import json
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parents[1]

def main():
    protocol=json.loads((ROOT/'evaluation-protocol.json').read_text())
    cases=json.loads((ROOT/'inputs/evaluation-cases.json').read_text())['cases'];byid={c['id']:c for c in cases}
    methods=protocol['methods'];positives=[c['id'] for c in cases if c['oracle_status']=='witnessed_different'];controls=[c['id'] for c in cases if c['role']=='intended_control']
    expected={(c['id'],m,r,t) for c in cases for m in methods for r in range(4) for t in range(64)}
    seen=set();sets=defaultdict(lambda:{'counts':Counter(),'first_hit':None,'both_empty':0,'rows':0,'seconds':Counter()})
    bymethod={m:{'counts':Counter(),'role_counts':defaultdict(Counter),'both_empty':0,'generated_rows':0,'seconds':Counter(),'nontrivial_input_order':0,'witness_mixed_rows':0} for m in methods}
    errors=[];first_witnesses={};observed_values=defaultdict(set)
    with gzip.open(ROOT/'results/trials.jsonl.gz','rt') as stream:
        for index,line in enumerate(stream):
            r=json.loads(line);key=(r['case_id'],r['method'],r['repeat'],r['trial'])
            assert key not in seen and key in expected;seen.add(key)
            assert r['seed']==protocol['repeat_seeds'][r['repeat']]+r['trial']
            case=byid[r['case_id']];assert r['role']==case['role'] and r['cluster']==case['cluster']
            s=sets[key[:3]];s['counts'][r['status']]+=1;s['both_empty']+=r['both_empty']
            m=bymethod[r['method']];m['counts'][r['status']]+=1;m['role_counts'][case['role']][r['status']]+=1;m['both_empty']+=r['both_empty']
            if r['instance'] is not None:
                rows=r['instance']['regression_input'];s['rows']+=len(rows);m['generated_rows']+=len(rows)
                m['nontrivial_input_order']+=rows!=list(reversed(rows))
                for pos,column in enumerate(case['schema']['tables'][0]['columns']):
                    observed_values[(case['id'],r['method'],column['name'])].update(row[pos] for row in rows)
                if r['status']=='mismatch':m['witness_mixed_rows']+=len({tuple(row) for row in rows})>1
            if r['status']=='mismatch' and s['first_hit'] is None:
                s['first_hit']=r['trial'];first_witnesses['|'.join(map(str,key[:3]))]={'record_index':index,'trial':r['trial'],'seed':r['seed'],'instance_sha256':r['instance_sha256']}
            for field,value in r.items():
                if field.endswith('_seconds'):s['seconds'][field]+=value;m['seconds'][field]+=value
            if r['status']=='inconclusive':errors.append({'key':list(key),'error':r['error']})
    assert seen==expected and len(seen)==42240
    task_runs=[]
    for (cid,method,repeat),s in sorted(sets.items()):
        assert sum(s['counts'].values())==64
        task_runs.append({'case_id':cid,'role':byid[cid]['role'],'cluster':byid[cid]['cluster'],'method':method,'repeat':repeat,'counts':dict(s['counts']),'first_hit_trial':s['first_hit'],'both_empty':s['both_empty'],'generated_rows':s['rows'],'stage_seconds':dict(s['seconds'])})
    clusters=sorted({c['cluster'] for c in cases})
    method_summaries={}
    for method,m in bymethod.items():
        found={cid for cid in positives if any(sets[cid,method,r]['first_hit'] is not None for r in range(4))}
        misses=[{'case_id':cid,'repeats':[r for r in range(4) if sets[cid,method,r]['first_hit'] is None]} for cid in positives if any(sets[cid,method,r]['first_hit'] is None for r in range(4))]
        control_hits=[cid for cid in controls if any(sets[cid,method,r]['first_hit'] is not None for r in range(4))]
        first_trials=[sets[cid,method,r]['first_hit'] for cid in positives for r in range(4) if sets[cid,method,r]['first_hit'] is not None]
        bycluster=[]
        for cluster in clusters:
            ids=[cid for cid in positives if byid[cid]['cluster']==cluster]
            repeat_hits=[sum(sets[cid,method,r]['first_hit'] is not None for cid in ids) for r in range(4)]
            bycluster.append({'cluster':cluster,'known_different_tasks':len(ids),'tasks_found_any_seed':len(found & set(ids)),
                              'per_repeat_tasks_found':repeat_hits,'any_task_found_each_repeat':[n>0 for n in repeat_hits],
                              'all_tasks_found_each_repeat':[n==len(ids) for n in repeat_hits]})
        method_summaries[method]={'planned_trials':14080,'known_different_task_denominator':27,'tasks_found_any_seed':len(found),
            'known_different_task_repeat_denominator':108,'task_repeats_with_witness':len(first_trials),
            'per_repeat_known_different_tasks_found':[sum(sets[cid,method,r]['first_hit'] is not None for cid in positives) for r in range(4)],
            'misses':misses,'intended_control_task_denominator':28,'intended_control_tasks_with_mismatch':control_hits,
            'trial_counts':dict(m['counts']),'trial_counts_by_role':{k:dict(v) for k,v in m['role_counts'].items()},
            'both_empty_trials':m['both_empty'],'generated_rows':m['generated_rows'],'stage_seconds':dict(m['seconds']),
            'conditional_first_hit_trial_zero_based':{'n_detected_task_repeats':len(first_trials),'median':statistics.median(first_trials) if first_trials else None,'max':max(first_trials) if first_trials else None,'warning':'Conditional on detection; excludes misses, not a time-to-detection comparison.'},
            'cluster_coverage':bycluster}
    pairs=[]
    for a,b in itertools.combinations(methods,2):
        counts=Counter();gains=[];losses=[]
        for cid in positives:
            for repeat in range(4):
                ahit=sets[cid,a,repeat]['first_hit'] is not None;bhit=sets[cid,b,repeat]['first_hit'] is not None
                category='both_hit' if ahit and bhit else ('a_only' if ahit else ('b_only' if bhit else 'both_miss'))
                counts[category]+=1
                item={'case_id':cid,'cluster':byid[cid]['cluster'],'repeat':repeat}
                if category=='b_only':gains.append(item)
                if category=='a_only':losses.append(item)
        pairs.append({'a':a,'b':b,'unit':'same known-different task and repeat seed; correlated repetitions, not independent bugs','denominator':108,
                      'counts':{k:counts[k] for k in ('both_hit','a_only','b_only','both_miss')},'b_gains':gains,'b_losses':losses})
    plans=[json.loads(p.read_text()) for p in sorted((ROOT/'results/plans').glob('*.json'))]
    recorded=json.loads((ROOT/'results/run-summaries.json').read_text())
    original_runs={(r['case_id'],r['method'],r['repeat']):r for r in recorded['runs']}
    for (cid,method,repeat),s in sets.items():
        r=original_runs[cid,method,repeat]
        assert r['counts']==dict(s['counts']) and r['first_hit_trial']==s['first_hit'] and r['both_empty_trials']==s['both_empty']
    values=[{'case_id':cid,'method':method,'column':column,'observed_values':sorted(v,key=lambda x:(x is not None,x if x is not None else 0))} for (cid,method,column),v in sorted(observed_values.items())]
    summary={'format_version':1,'all_42240_scheduled_trial_keys_present_once':True,'unique_tasks':55,'known_different_tasks':27,'intended_controls':28,'upstream_bug_clusters':3,
             'methods':method_summaries,'paired_results':pairs,'execution_errors':errors,
             'planning_errors':[{'case_id':p['case_id'],'schema_error':p['schema_error'],'plan_error':p['plan_error']} for p in plans if p['schema_error'] or p['plan_error']],
             'total_plan_compile_seconds':sum(p['compile_seconds'] for p in plans),
             'product_run_wall_seconds_including_logging':recorded['total_wall_seconds_including_logging'],
             'interpretation':'Query-aware found three additional related subtraction pairs; all methods found at least one task in each of three upstream bug clusters. No generator tuning, general superiority, independent-bug count inflation or population-recall conclusion.'}
    for filename,value in [('summary.json',summary),('task-repeat-results.json',task_runs),('first-witness-index.json',first_witnesses),('observed-values.json',values)]:
        with (ROOT/'results'/filename).open('x') as f:f.write(json.dumps(value,indent=2)+'\n')
    print(json.dumps({'summary':str(ROOT/'results/summary.json'),'trial_records':len(seen),'method_hits':{m:method_summaries[m]['tasks_found_any_seed'] for m in methods},'errors':len(errors),'paired_counts':[{'a':p['a'],'b':p['b'],**p['counts']} for p in pairs]},indent=2))

if __name__=='__main__':main()

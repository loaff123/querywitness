"""Independent standard-library replay of every retained generated trial.

No QueryWitness, generator, product builder, product comparator or SQLGlot
imports. Uses the frozen checker bytes and raw declared schema. Replays ALL
successful generated instances, including every witness and intended control.
"""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import time
from sqlite_checker import observe,compare

ROOT=Path(__file__).resolve().parents[1]

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def validate_schema_and_instance(schema,instance):
    if len(schema['tables'])!=1:raise ValueError('only frozen single-table schemas')
    table=schema['tables'][0]
    if table['name']!='regression_input' or any(table.get(k) for k in ('primary_key','unique','foreign_keys')):raise ValueError('unexpected contract')
    columns=table['columns']
    if any(c!={'name':c['name'],'type':'INTEGER','nullable':True} for c in columns):raise ValueError('unexpected column declaration')
    if set(instance)!={'regression_input'}:raise ValueError('wrong tables')
    rows=instance['regression_input']
    if not isinstance(rows,list) or len(rows)>8:raise ValueError('row bound')
    if any(not isinstance(row,list) or len(row)!=len(columns) for row in rows):raise ValueError('row width')
    if any(v is not None and (type(v) is not int or not -(2**63)<=v<2**63) for row in rows for v in row):raise ValueError('INTEGER contract')
    return [c['name'] for c in columns],rows

def product_as_checker(observation):
    return {'status':observation['status'],'columns':len(observation['columns']),
            'rows':[[{'type':'null'} if c['type']=='null' else c for c in row] for row in observation['rows']]}

def exact_observation(a,b):
    return a['status']==b['status']=='ok' and a['columns']==b['columns'] and a['rows']==b['rows']

def main():
    cases={c['id']:c for c in json.loads((ROOT/'inputs/evaluation-cases.json').read_text())['cases']}
    results=ROOT/'results'
    if (results/'independent-replays.jsonl.gz').exists():raise RuntimeError('replay log already exists; never overwrite')
    counts=Counter();contradicted=set();issues=[];begin=time.perf_counter()
    with gzip.open(results/'trials.jsonl.gz','rt',encoding='utf-8') as source, gzip.open(results/'independent-replays.jsonl.gz','wt',encoding='utf-8') as output:
        for index,line in enumerate(source):
            trial=json.loads(line);case=cases[trial['case_id']]
            r={k:trial[k] for k in ('case_id','method','repeat','trial','seed','instance_sha256','status')}
            r['record_index']=index;r['independent_status']='not_run';r['error']=None
            counts['trial_records']+=1
            try:
                if trial['generation_status']!='ok' or trial['instance_validation_status']!='valid':
                    r['independent_status']='no_valid_generated_instance';counts['no_valid_generated_instance']+=1
                else:
                    instance=trial['instance']
                    if hashlib.sha256(canonical(instance)).hexdigest()!=trial['instance_sha256']:raise ValueError('instance hash mismatch')
                    columns,rows=validate_schema_and_instance(case['schema'],instance)
                    r['has_distinct_rows']=len({tuple(row) for row in rows})>1
                    r['reverse_changes_sequence']=rows!=list(reversed(rows))
                    forward=[observe(columns,rows,case[key]) for key in ('reference_sql','candidate_sql')]
                    reverse=[observe(columns,list(reversed(rows)),case[key]) for key in ('reference_sql','candidate_sql')]
                    fr=compare(*forward);rr=compare(*reverse)
                    r.update(forward=forward,reverse=reverse,forward_relation=fr,reverse_relation=rr)
                    expected={'agreement':'same','mismatch':'mismatch','inconclusive':'inconclusive'}[trial['status']]
                    product=[product_as_checker(trial[key]) for key in ('reference_observation','candidate_observation')] if trial['reference_observation'] and trial['candidate_observation'] else None
                    r['forward_exact_typed_rows_match_product']=product is not None and all(exact_observation(a,b) for a,b in zip(forward,product))
                    r['reverse_bags_match_forward']=all(compare(a,b)=='same' for a,b in zip(forward,reverse))
                    r['relations_match_product']=fr==rr==expected
                    r['independent_status']='verified' if r['forward_exact_typed_rows_match_product'] and r['reverse_bags_match_forward'] and r['relations_match_product'] else 'discrepancy_or_inconclusive'
                    counts[r['independent_status']]+=1
                    counts['forward_'+fr]+=1;counts['reverse_'+rr]+=1
                    if trial['status']=='mismatch':
                        counts['product_witness_trials']+=1
                        counts['witness_reversals_changing_sequence']+=bool(r['reverse_changes_sequence'])
                        counts['witness_instances_with_distinct_rows']+=bool(r['has_distinct_rows'])
                        counts['independently_verified_witnesses']+=r['independent_status']=='verified'
                    if case['role']=='intended_control' and fr=='mismatch':contradicted.add(case['id'])
                    if r['independent_status']!='verified':issues.append({'record_index':index,'case_id':case['id'],'method':trial['method'],'repeat':trial['repeat'],'trial':trial['trial'],'product_status':trial['status'],'forward':fr,'reverse':rr})
            except Exception as error:
                r['independent_status']='error';r['error']={'class':type(error).__name__,'message':str(error)};counts['replay_errors']+=1
                issues.append({'record_index':index,'error':r['error']})
            output.write(json.dumps(r,sort_keys=True,ensure_ascii=False,allow_nan=False)+'\n')
    summary={'format_version':1,'checker_sha256':hashlib.sha256((ROOT/'scripts/sqlite_checker.py').read_bytes()).hexdigest(),
             'all_generated_trials_replayed_not_only_witnesses':True,'counts':dict(counts),'contradicted_intended_control_ids':sorted(contradicted),'issues':issues,
             'elapsed_seconds':time.perf_counter()-begin,
             'verified_without_discrepancy':not issues and counts['trial_records']==42240 and counts['verified']==42240}
    with (results/'independent-replay-summary.json').open('x') as f:f.write(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()

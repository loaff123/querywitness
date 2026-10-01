"""Portable public copy of the recorded evaluation harness.
Only commit-time input-location validation and attribution metadata differ.
ProductRuntime, run_repeat, baseline_pool and run retain their frozen bodies.
"""
from collections import Counter
import argparse
import ast
import gzip
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'sources/querywitness'

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()
def file_hash(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write_new(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:f.write(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')

def validate_instance(schema,instance,max_rows):
    if len(schema['tables'])!=1:raise ValueError('expected frozen single-table schema')
    table=schema['tables'][0]
    if table['name']!='regression_input' or any(table.get(k) for k in ('primary_key','unique','foreign_keys')):raise ValueError('unexpected schema constraints')
    columns=table['columns']
    if any(c!={'name':c['name'],'type':'INTEGER','nullable':True} for c in columns):raise ValueError('unexpected column contract')
    if not isinstance(instance,dict) or set(instance)!={'regression_input'}:raise ValueError('instance tables differ')
    rows=instance['regression_input']
    if not isinstance(rows,list) or len(rows)>max_rows:raise ValueError('row bound')
    for row in rows:
        if not isinstance(row,(list,tuple)) or len(row)!=len(columns):raise ValueError('row width')
        if any(v is not None and (type(v) is not int or not -(2**63)<=v<2**63) for v in row):raise ValueError('illegal nullable INTEGER')

class ProductRuntime:
    def __init__(self):
        sys.path.insert(0,str(SOURCE/'src'))
        import querywitness
        import sqlglot
        from querywitness.schema import Schema
        from querywitness.engine import execute,ExecutionLimits
        from querywitness.generate import generate_instance
        from querywitness.query_plan import compile_plan
        from querywitness.query_generate import generate_query_aware
        from querywitness.compare import compare_results
        from querywitness.artifacts import observation
        if not Path(querywitness.__file__).resolve().is_relative_to((SOURCE/'src').resolve()):raise RuntimeError('unexpected import path')
        if querywitness.__version__!='0.2.0' or sqlglot.__version__!='27.29.0':raise RuntimeError('runtime pin mismatch')
        self.Schema=Schema;self.Limits=ExecutionLimits;self._execute=execute;self._baseline=generate_instance
        self._compile=compile_plan;self._aware=generate_query_aware;self._compare=compare_results;self._observe=observation
        self.versions={'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'querywitness':querywitness.__version__,'sqlglot':sqlglot.__version__}
    def compile(self,schema,case,config):return self._compile(schema,case['reference_sql'],case['candidate_sql'],max_rows=config['max_rows'],sql_bytes=config['limits']['sql_bytes'])
    def generate(self,schema,plan,seed,method,config):
        if method=='query_aware':return self._aware(schema,plan,seed)
        return self._baseline(schema,seed,method,config['max_rows']),None
    def execute(self,schema,instance,sql,config):return self._execute(schema,instance,sql,self.Limits(**config['limits']),policy=config['policy'])
    def compare(self,a,b,policy):return self._compare(a,b,policy)
    def observe(self,result):return self._observe(result)

def run_repeat(case,schema,plan,method,repeat,start_seed,config,runtime,log,setup_error=None):
    counts=Counter();errors=Counter();first=None;both_empty=0;start=time.perf_counter()
    stage_sums=Counter();rows_total=0
    for trial in range(config['trials']):
        seed=start_seed+trial
        record={'case_id':case['id'],'cluster':case['cluster'],'role':case['role'],'method':method,'repeat':repeat,
                'trial':trial,'seed':seed,'instance':None,'instance_sha256':None,'table_rows':None,
                'generation_status':'not_run','instance_validation_status':'not_run','generator_stats':None,
                'reference_observation':None,'candidate_observation':None,'comparison':None,
                'status':'inconclusive','both_empty':False,'error_stage':None,'error':None,
                'generation_seconds':0.0,'validation_seconds':0.0,'reference_seconds':0.0,'candidate_seconds':0.0,'comparison_seconds':0.0}
        begin=time.perf_counter();stage='generation';tick=begin
        try:
            if setup_error is not None:
                stage='setup';raise RuntimeError(setup_error)
            instance,stats=runtime.generate(schema,plan,seed,method,config)
            record['generation_seconds']=time.perf_counter()-tick
            record.update(instance=instance,instance_sha256=digest(instance),table_rows={k:len(v) for k,v in instance.items()},generator_stats=stats,generation_status='ok')
            stage='validation';tick=time.perf_counter()
            validate_instance(case['schema'],instance,config['max_rows'])
            record['validation_seconds']=time.perf_counter()-tick;record['instance_validation_status']='valid'
            stage='reference';tick=time.perf_counter()
            a=runtime.execute(schema,instance,case['reference_sql'],config)
            record['reference_seconds']=time.perf_counter()-tick;record['reference_observation']=runtime.observe(a)
            stage='candidate';tick=time.perf_counter()
            b=runtime.execute(schema,instance,case['candidate_sql'],config)
            record['candidate_seconds']=time.perf_counter()-tick;record['candidate_observation']=runtime.observe(b)
            stage='comparison';tick=time.perf_counter()
            comp=runtime.compare(a,b,config['policy'])
            record['comparison_seconds']=time.perf_counter()-tick;record['comparison']=comp
            if comp['status'] not in ('agreement','mismatch','inconclusive'):raise ValueError('unknown comparison status')
            record['status']=comp['status']
            aobs=record['reference_observation'];bobs=record['candidate_observation']
            record['both_empty']=aobs['status']==bobs['status']=='ok' and not aobs['rows'] and not bobs['rows']
            if record['status']=='inconclusive':record['error']={'reference_status':aobs['status'],'candidate_status':bobs['status'],'reference_detail':aobs['detail'],'candidate_detail':bobs['detail']}
        except Exception as error:
            record[stage+'_seconds']=time.perf_counter()-tick
            record['error_stage']=stage;record['error']={'class':type(error).__name__,'message':str(error)}
            record['status']='inconclusive'
            if stage=='generation':record['generation_status']='error'
            if stage=='validation':record['instance_validation_status']='invalid'
        record['product_trial_seconds']=time.perf_counter()-begin
        counts[record['status']]+=1;both_empty+=record['both_empty']
        if record['table_rows']:rows_total+=sum(record['table_rows'].values())
        if record['status']=='mismatch' and first is None:first=trial
        if record['status']=='inconclusive':errors[json.dumps(record['error'],sort_keys=True)]+=1
        for key,value in record.items():
            if key.endswith('_seconds'):stage_sums[key]+=value
        log.write(json.dumps(record,sort_keys=True,ensure_ascii=False,allow_nan=False)+'\n')
        log.flush()
    return {'case_id':case['id'],'cluster':case['cluster'],'role':case['role'],'method':method,'repeat':repeat,
            'start_seed':start_seed,'attempted_trials':config['trials'],'counts':dict(counts),'first_hit_trial':first,
            'both_empty_trials':both_empty,'generated_rows_total':rows_total,'errors':dict(errors),
            'stage_seconds':dict(stage_sums),'wall_seconds_including_logging':time.perf_counter()-start}

def baseline_pool():
    tree=ast.parse((SOURCE/'src/querywitness/generate.py').read_text())
    choices=[n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='domain' for t in n.targets) and isinstance(n.value,ast.IfExp)]
    if len(choices)!=1:raise ValueError('unrecognized frozen baseline pool source')
    values=ast.literal_eval(choices[0].value.body)
    if values!=(-2,-1,0,1,2,10,100):raise ValueError('unexpected baseline pool')
    return list(values)

def manifest_files():
    paths=[ROOT/'evaluation-protocol.json',*sorted((ROOT/'inputs').rglob('*')),*sorted((ROOT/'scripts').glob('*.py')),*sorted((ROOT/'tests').glob('*.py'))]
    paths += [p for p in (ROOT/'sources').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    return {p.relative_to(ROOT).as_posix():file_hash(p) for p in sorted(paths) if p.is_file()}

def commit(utc):
    if (ROOT/'execution-manifest.json').exists():raise RuntimeError('manifest already exists; never overwrite')
    protocol=json.loads((ROOT/'evaluation-protocol.json').read_text())
    cases=json.loads((ROOT/'inputs/evaluation-cases.json').read_text())['cases']
    if len(cases)!=55 or sum(c['role']=='intended_control' for c in cases)!=28:raise ValueError('cohort changed')
    expected=json.loads((ROOT/'input-hashes.json').read_text(encoding='utf-8'))
    for name,sha in expected.items():
        if file_hash(ROOT/name)!=sha:raise ValueError('frozen input hash mismatch: '+name)
    runtime=ProductRuntime()  # imports only; no planning, generation or SQL execution
    manifest={'format_version':1,'committed_before_first_generator_call_utc':utc,'protocol_sha256':file_hash(ROOT/'evaluation-protocol.json'),
              'cohort_protocol_sha256':file_hash(ROOT/'inputs/cohort-protocol.json'),'cohort_archive_sha256':protocol['cohort_archive_sha256'],'runtime':runtime.versions,
              'planned_trials':55*3*4*64,'case_order':[c['id'] for c in cases],
              'baseline_nonnull_integer_pool':baseline_pool(),'files':manifest_files(),
              'scope_attestation':'Manifest for a fresh public reproduction; does not replace or backdate the original execution commitment.'}
    write_new(ROOT/'execution-manifest.json',manifest)
    (ROOT/'execution-manifest.sha256').write_text(file_hash(ROOT/'execution-manifest.json')+'  execution-manifest.json\n')
    print(json.dumps({'manifest_sha256':file_hash(ROOT/'execution-manifest.json'),'planned_trials':manifest['planned_trials'],'runtime':runtime.versions},indent=2))

def run():
    manifest=json.loads((ROOT/'execution-manifest.json').read_text())
    if file_hash(ROOT/'execution-manifest.json')!=(ROOT/'execution-manifest.sha256').read_text().split()[0]:raise RuntimeError('manifest changed')
    if manifest_files()!=manifest['files']:raise RuntimeError('evaluation source/inputs changed after commitment')
    config=json.loads((ROOT/'evaluation-protocol.json').read_text());cases=json.loads((ROOT/'inputs/evaluation-cases.json').read_text())['cases']
    runtime=ProductRuntime()
    if runtime.versions!=manifest['runtime']:raise RuntimeError('runtime changed')
    dest=ROOT/'results';dest.mkdir(exist_ok=False)
    runs=[];begin=time.perf_counter()
    with gzip.open(dest/'trials.jsonl.gz','wt',encoding='utf-8') as log:
        for case in cases:
            schema=None;plan=None;schema_error=None;plan_error=None;compile_seconds=0.0
            try:schema=runtime.Schema.from_dict(case['schema'])
            except Exception as error:schema_error=f'{type(error).__name__}: {error}'
            if schema_error is None:
                tick=time.perf_counter()
                try:plan=runtime.compile(schema,case,config)
                except Exception as error:plan_error=f'{type(error).__name__}: {error}'
                compile_seconds=time.perf_counter()-tick
            plan_data=plan.to_dict() if plan is not None else None
            pools={method:[{'table':t['name'],'column':c['name'],'nonnull_pool':manifest['baseline_nonnull_integer_pool'],'nullable':c['nullable']} for t in case['schema']['tables'] for c in t['columns']] for method in ('random','boundary')}
            pools['query_aware']=plan_data.get('effective_domains') if plan_data else None
            write_new(dest/'plans'/(case['id'].replace(':','__')+'.json'),{'case_id':case['id'],'schema_error':schema_error,'plan_error':plan_error,'compile_seconds':compile_seconds,'query_aware_plan':plan_data,'plan_sha256':digest(plan_data) if plan_data else None,'effective_pools':pools,'null_handling':'NULL is sampled separately under product schedules and schema nullability.'})
            for method in config['methods']:
                for repeat,start_seed in enumerate(config['repeat_seeds']):
                    setup_error=schema_error or (plan_error if method=='query_aware' else None)
                    summary=run_repeat(case,schema,plan,method,repeat,start_seed,config,runtime,log,setup_error)
                    runs.append(summary)
            latest=runs[-12:]
            print(case['id'],{m:[r['first_hit_trial'] for r in latest if r['method']==m] for m in config['methods']},flush=True)
    write_new(dest/'run-summaries.json',{'runs':runs,'attempted_trials':sum(r['attempted_trials'] for r in runs),'total_wall_seconds_including_logging':time.perf_counter()-begin})
    print(json.dumps({'complete':True,'attempted_trials':sum(r['attempted_trials'] for r in runs)},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['commit','run']);p.add_argument('--utc');args=p.parse_args()
    if args.action=='commit':
        if not args.utc:p.error('--utc required for manifest commitment')
        commit(args.utc)
    else:run()

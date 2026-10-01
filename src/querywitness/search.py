"""Finite-budget differential search; no witness is not proof of equivalence."""
import hashlib
import sqlite3
import json
import math
import time
from dataclasses import asdict
from .schema import Schema
from .engine import execute, ExecutionLimits
from .compare import compare_results, encode_cell
from .generate import generate_instance, GenerationError
from .semantics import PARSER_VERSION

def search(schema:Schema,reference:str,candidate:str,*,trials=100,seed=0,strategy='boundary',policy='bag',limits:ExecutionLimits|None=None,max_rows=8,seconds=60.0)->dict:
    if type(trials) is not int or not 1<=trials<=10000:raise ValueError('Trials must be 1–10000')
    if type(seed) is not int or not 0<=seed<2**63-trials:raise ValueError('Seed out of range')
    if policy not in ('bag','set','ordered'):raise ValueError('Unknown comparison policy')
    if type(seconds) not in (int,float) or not math.isfinite(seconds) or not 0<seconds<=3600:raise ValueError('Invalid search time budget')
    if any(not isinstance(q,str) or any(0xD800<=ord(c)<=0xDFFF for c in q) for q in (reference,candidate)):
        raise ValueError('Queries must be Unicode text without surrogates')
    limits=limits or ExecutionLimits()
    start=time.monotonic()
    provenance={'schema_version':'1.0','schema_sha256':hashlib.sha256(json.dumps(schema.to_dict(),sort_keys=True,separators=(',',':')).encode()).hexdigest(),'execution_limits':asdict(limits),'max_rows':max_rows,'search_seconds':seconds,'generator_version':'0.1.0','sqlite_version':sqlite3.sqlite_version,'sqlglot_version':PARSER_VERSION,'seed':seed,'strategy':strategy,'policy':policy,'trial_budget':trials,'reference_sha256':hashlib.sha256(reference.encode()).hexdigest(),'candidate_sha256':hashlib.sha256(candidate.encode()).hexdigest()}
    evaluated=inconclusive=0;errors=[]
    plan=None
    if strategy=='query_aware':
        from .query_plan import compile_plan, PlanningBudgetExceeded
        from .query_generate import generate_query_aware
        provenance.update(generated_trials=0,query_executions=0,both_empty_trials=0,
                          generation_attempted_rows=0,generation_rejected_rows=0,
                          generation_accepted_rows=0,generator_version='query-aware-1')
        try:plan=compile_plan(schema,reference,candidate,max_rows=max_rows,sql_bytes=limits.sql_bytes,deadline=start+seconds)
        except PlanningBudgetExceeded as e:
            return {**provenance,'status':'search_budget_exhausted','detail':str(e),'budget_stage':'planning','evaluated':0,'inconclusive':0}
        except GenerationError as e:
            return {**provenance,'status':'unsupported_generation','detail':str(e),'evaluated':0,'inconclusive':0}
        provenance['generation_plan']=plan.to_dict()
    for index in range(trials):
        if time.monotonic()-start>=seconds:return {**provenance,'status':'search_budget_exhausted','evaluated':evaluated,'inconclusive':inconclusive,'errors':errors}
        current_seed=seed+index
        try:
            if plan is None:instance=generate_instance(schema,current_seed,strategy,max_rows)
            else:
                instance,stats=generate_query_aware(schema,plan,current_seed)
                provenance['generated_trials']+=1
                for key in ('attempted_rows','rejected_rows','accepted_rows'):
                    provenance['generation_'+key]+=stats[key]
        except GenerationError as e:return {**provenance,'status':'unsupported_generation','detail':str(e),'evaluated':evaluated,'inconclusive':inconclusive}
        if plan is not None and time.monotonic()-start>=seconds:
            return {**provenance,'status':'search_budget_exhausted','budget_stage':'generation','evaluated':evaluated,'inconclusive':inconclusive,'errors':errors}
        a=execute(schema,instance,reference,limits,policy=policy);b=execute(schema,instance,candidate,limits,policy=policy);comparison=compare_results(a,b,policy);evaluated+=1
        if plan is not None:
            provenance['query_executions']+=2
            provenance['both_empty_trials']+=int(a.status==b.status=='ok' and not a.rows and not b.rows)
        if comparison['status']=='inconclusive':
            inconclusive+=1
            if len(errors)<10:errors.append({'seed':current_seed,'reference_status':a.status,'candidate_status':b.status,'reference_detail':a.detail,'candidate_detail':b.detail})
        elif comparison['status']=='mismatch':
            return {**provenance,'status':'counterexample','evaluated':evaluated,'inconclusive':inconclusive,'witness_seed':current_seed,'instance':instance,'comparison':comparison,'reference_rows':[[encode_cell(v) for v in row] for row in a.rows],'candidate_rows':[[encode_cell(v) for v in row] for row in b.rows]}
    return {**provenance,'status':'inconclusive' if inconclusive else 'no_counterexample_within_budget','evaluated':evaluated,'inconclusive':inconclusive,'errors':errors,'notice':'Testing a finite generated set does not establish semantic equivalence'}

"""Portable witness bundles with exact observations and self-integrity checks."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from copy import deepcopy
import hashlib
import html
import json
import math
import platform
import sqlite3
from . import __version__
from .schema import Schema
from .engine import ExecutionLimits, execute, open_database
from .compare import compare_results, encode_cell
from .semantics import PARSER_VERSION

MAX_JSON_BYTES = 16_000_000


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def closure_context() -> dict:
    """Versions defining this runtime's FK-closure claim semantics."""
    return {
        'operator_version': 'fk-closure-v1',
        'schema_contract': 'querywitness-schema-1.0',
        'comparison_contract': 'querywitness-exact-v1',
        'runtime': {
            'tool_version': __version__,
            'sqlite_version': sqlite3.sqlite_version,
            'sqlglot_version': PARSER_VERSION,
            'python_version': platform.python_version(),
        },
    }


def _recorded_closure_context(metadata):
    """Extract context without substituting the currently running versions."""
    if not isinstance(metadata, dict):
        raise ValueError('Invalid FK-closure context')
    names = ('operator_version', 'schema_contract', 'comparison_contract')
    if any(not isinstance(metadata.get(name), str) or not metadata[name]
           for name in names):
        raise ValueError('Invalid FK-closure context')
    runtime = metadata.get('runtime')
    runtime_names = {'tool_version', 'sqlite_version', 'sqlglot_version', 'python_version'}
    if (not isinstance(runtime, dict) or set(runtime) != runtime_names or
            any(not isinstance(value, str) or not value for value in runtime.values())):
        raise ValueError('Invalid FK-closure runtime context')
    return {**{name: metadata[name] for name in names}, 'runtime': deepcopy(runtime)}


def closure_scope_sha256(schema, instance, reference, candidate, policy, limits,
                         *, context=None) -> str:
    """Bind an operation's exact final inputs, limits, and execution context."""
    recorded = closure_context() if context is None else _recorded_closure_context(context)
    return digest({**recorded, 'schema': schema.to_dict(), 'instance': instance,
                   'reference': reference, 'candidate': candidate, 'policy': policy,
                   'execution_limits': asdict(limits or ExecutionLimits())})


def _is_closure_reduction(reduction):
    return isinstance(reduction, dict) and reduction.get('deletion_mode') == 'fk-closure'


def _supported_closure_context(context):
    supported = closure_context()
    return all(context[name] == supported[name]
               for name in ('operator_version', 'schema_contract', 'comparison_contract'))


def _validate_closure_metadata(reduction, schema, instance, reference, candidate,
                               policy, limits, *, require_current=False,
                               provenance=None, tool_version=None):
    recorded = _recorded_closure_context(reduction)
    if require_current and recorded != closure_context():
        raise ValueError('FK-closure context does not match the current runtime')
    expected = closure_scope_sha256(schema, instance, reference, candidate,
                                    policy, limits, context=recorded)
    if reduction.get('scope_sha256') != expected:
        raise ValueError('FK-closure scope mismatch')
    counters = ('initial_rows', 'final_rows', 'checks', 'query_executions',
                'inconclusive_checks', 'final_scan_roots_checked',
                'final_scan_inconclusive')
    for name in counters:
        if type(reduction.get(name)) is not int or reduction[name] < 0:
            raise ValueError('Invalid FK-closure count: ' + name)
    for name in ('witness_reproduced', 'fk_closure_1_minimal', 'row_1_minimal',
                 'final_scan_complete'):
        if type(reduction.get(name)) is not bool:
            raise ValueError('Invalid FK-closure flag: ' + name)
    if not isinstance(reduction.get('status'), str) or not reduction['status']:
        raise ValueError('Invalid FK-closure status')
    if 'max_checks' in reduction and (
            type(reduction['max_checks']) is not int or not 1 <= reduction['max_checks'] <= 10000):
        raise ValueError('Invalid FK-closure check budget')
    if 'seconds' in reduction and (
            type(reduction['seconds']) not in (int, float) or
            not math.isfinite(reduction['seconds']) or not 0 < reduction['seconds'] <= 300):
        raise ValueError('Invalid FK-closure time budget')
    if reduction.get('budget_stage') is not None and not isinstance(reduction['budget_stage'], str):
        raise ValueError('Invalid FK-closure budget stage')
    rows = sum(map(len, instance.values()))
    if reduction['final_rows'] != rows or reduction['initial_rows'] < rows:
        raise ValueError('Inconsistent FK-closure row counts')
    if _supported_closure_context(recorded):
        if 'max_checks' in reduction and reduction['checks'] > reduction['max_checks']:
            raise ValueError('FK-closure checks exceed the recorded budget')
        if reduction['witness_reproduced'] and (
                reduction['checks'] < 1 + reduction['final_scan_roots_checked']):
            raise ValueError('Insufficient FK-closure checks for the recorded scan')
        if reduction['status'] in ('minimized', 'inconclusive_reduction',
                                    'not_a_witness', 'initial_check_inconclusive') and (
                reduction['query_executions'] != 2 * reduction['checks']):
            raise ValueError('Incomplete FK-closure query pair in completed run')
        if reduction['fk_closure_1_minimal'] != reduction['row_1_minimal']:
            raise ValueError('Inconsistent FK-closure minimality flags')
        if (reduction['final_scan_roots_checked'] > rows or
                reduction['final_scan_inconclusive'] > reduction['final_scan_roots_checked'] or
                reduction['final_scan_inconclusive'] > reduction['inconclusive_checks'] or
                reduction['inconclusive_checks'] > reduction['checks'] or
                reduction['query_executions'] > 2 * reduction['checks']):
            raise ValueError('Inconsistent FK-closure scan counts')
        if reduction['final_scan_complete'] and reduction['final_scan_roots_checked'] != rows:
            raise ValueError('Incomplete FK-closure final scan')
        if reduction['witness_reproduced'] and (
                reduction['checks'] < 1 or reduction['query_executions'] < 2):
            raise ValueError('Inconsistent FK-closure witness reproduction')
        if reduction['fk_closure_1_minimal'] and not (
                reduction['status'] == 'minimized' and reduction['witness_reproduced'] and
                reduction['final_scan_complete'] and
                reduction['final_scan_roots_checked'] == rows and
                reduction['final_scan_inconclusive'] == 0 and
                reduction['inconclusive_checks'] == 0):
            raise ValueError('Inconsistent FK-closure minimality claim')
    if provenance is not None:
        if not isinstance(provenance, dict):
            raise ValueError('Invalid FK-closure provenance')
        runtime = {'tool_version': tool_version,
                   **{name: provenance.get(name) for name in
                      ('sqlite_version', 'sqlglot_version', 'python_version')}}
        if recorded['runtime'] != runtime:
            raise ValueError('FK-closure context disagrees with witness provenance')
    return recorded


def load_json(path):
    path=Path(path)
    if path.stat().st_size>MAX_JSON_BYTES: raise ValueError('JSON input exceeds 16 MB')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError('Duplicate JSON key: '+key)
            result[key]=value
        return result
    def bad(value): raise ValueError('Nonfinite JSON number: '+value)
    return json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=pairs,parse_constant=bad)


def observation(result):
    return {'status':result.status,'columns':list(result.columns),'rows':[[encode_cell(v) for v in row] for row in result.rows],'detail':result.detail}


def build_witness(schema,instance,reference,candidate,policy='bag',*,limits=None,search=None,reduction=None):
    limits=limits or ExecutionLimits();schema.validate_instance(instance)
    if _is_closure_reduction(reduction):
        _validate_closure_metadata(reduction, schema, instance, reference, candidate,
                                   policy, limits, require_current=True)
    a=execute(schema,instance,reference,limits,policy=policy);b=execute(schema,instance,candidate,limits,policy=policy)
    comparison=compare_results(a,b,policy)
    if comparison['status']!='mismatch': raise ValueError('Only successful output mismatches can be witness artifacts')
    value={'format':'querywitness/witness','format_version':1,'tool_version':__version__,
        'schema':schema.to_dict(),'instance':deepcopy(instance),'reference':reference,'candidate':candidate,'policy':policy,
        'execution_limits':asdict(limits),'comparison':comparison,'reference_observation':observation(a),'candidate_observation':observation(b),
        'provenance':{'sqlite_version':sqlite3.sqlite_version,'sqlglot_version':PARSER_VERSION,'python_version':platform.python_version(),
        'schema_sha256':digest(schema.to_dict()),'instance_sha256':digest(instance),
        'reference_sha256':hashlib.sha256(reference.encode()).hexdigest(),'candidate_sha256':hashlib.sha256(candidate.encode()).hexdigest()},
        'search':deepcopy(search),'reduction':deepcopy(reduction),
        'notice':'An observed counterexample under this SQLite contract, not a proof of query equivalence or a universal SQL claim. Integrity is a checksum, not authentication.'}
    value['integrity_sha256']=digest(value);return value


def verify_witness(value):
    if not isinstance(value,dict) or value.get('format')!='querywitness/witness' or value.get('format_version')!=1: raise ValueError('Unsupported witness format')
    unsigned={k:v for k,v in value.items() if k!='integrity_sha256'}
    if value.get('integrity_sha256')!=digest(unsigned): raise ValueError('Witness integrity mismatch')
    schema=Schema.from_dict(value['schema']);schema.validate_instance(value['instance'])
    limits=ExecutionLimits(**value['execution_limits'])
    if value['policy'] not in ('bag','set','ordered'): raise ValueError('Unknown comparison policy')
    if not isinstance(value['reference'],str) or not isinstance(value['candidate'],str): raise ValueError('Queries must be text')
    if _is_closure_reduction(value.get('reduction')):
        if not isinstance(value.get('provenance'), dict):
            raise ValueError('Invalid FK-closure provenance')
        _validate_closure_metadata(value['reduction'], schema, value['instance'],
                                   value['reference'], value['candidate'], value['policy'],
                                   limits, provenance=value['provenance'],
                                   tool_version=value.get('tool_version'))
    return schema


def replay(value, *, verify_minimality=False, minimality_checks=500,
           minimality_seconds=30.0):
    if verify_minimality:
        if type(minimality_checks) is not int or not 1 <= minimality_checks <= 10000:
            raise ValueError('Invalid minimality check budget')
        if (type(minimality_seconds) not in (float, int) or
                not math.isfinite(minimality_seconds) or not 0 < minimality_seconds <= 300):
            raise ValueError('Invalid minimality time budget')
    schema=verify_witness(value);limits=ExecutionLimits(**value['execution_limits'])
    a=execute(schema,value['instance'],value['reference'],limits,policy=value['policy']);b=execute(schema,value['instance'],value['candidate'],limits,policy=value['policy'])
    comparison=compare_results(a,b,value['policy'])
    exact=observation(a)==value['reference_observation'] and observation(b)==value['candidate_observation']
    result = {'status':'reproduced' if exact and comparison['status']=='mismatch' else ('inconclusive' if comparison['status']=='inconclusive' else 'observation_changed'),
        'exact_observations':exact,'comparison':comparison,'recorded_sqlite_version':value['provenance']['sqlite_version'],
        'current_sqlite_version':sqlite3.sqlite_version,'runtime_version_changed':sqlite3.sqlite_version!=value['provenance']['sqlite_version'],
        'reference_observation':observation(a),'candidate_observation':observation(b)}
    reduction = value.get('reduction')
    if verify_minimality:
        recorded = _recorded_closure_context(reduction) if _is_closure_reduction(reduction) else None
        current = closure_context()
        if recorded is None or not _supported_closure_context(recorded):
            audit = {'status': 'unsupported'}
        else:
            # The reducer imports scope helpers from this module. Import its
            # independent read-only checker only when explicitly requested.
            from .fk_closure import check_fk_closure_minimality
            audit = check_fk_closure_minimality(
                schema, value['instance'], value['reference'], value['candidate'],
                value['policy'], limits=limits, max_checks=minimality_checks,
                seconds=minimality_seconds)
        result['minimality_verification'] = {
            **audit, 'recorded_context': recorded, 'current_context': current,
            'context_changed': recorded != current,
            'scope_sha256': closure_scope_sha256(
                schema, value['instance'], value['reference'], value['candidate'],
                value['policy'], limits, context=current),
        }
    elif _is_closure_reduction(reduction):
        result['minimality_verification'] = {'status': 'not_requested'}
    return result


def sql_fixture(value):
    schema=verify_witness(value);db=open_database(schema,value['instance'])
    try:
        statements=list(db.iterdump())
        creates=[s for s in statements if s.startswith('CREATE TABLE ')]
        rest=[s for s in statements if not s.startswith('CREATE TABLE ') and s not in ('BEGIN TRANSACTION;','COMMIT;')]
        dump='\n'.join(['BEGIN TRANSACTION;',*creates,*rest,'COMMIT;'])
    finally: db.close()
    # A fresh line keeps the terminator outside any trailing SQL line comment.
    # Preserve the original query text, including any existing semicolon.
    return '-- QueryWitness fixture. Inspect supplied queries before running.\nPRAGMA foreign_keys=ON;\n'+dump+'\n\n-- Reference query\n'+value['reference']+'\n;\n\n-- Candidate query\n'+value['candidate']+'\n;\n'


def render_report(value):
    verify_witness(value)
    esc=html.escape
    def pre(obj): return '<pre>'+esc(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False))+'</pre>'
    blocks=[]
    for name,rows in value['instance'].items():
        table=next(t for t in value['schema']['tables'] if t['name']==name)
        headings=''.join('<th>'+esc(c['name'])+'</th>' for c in table['columns'])
        body=''.join('<tr>'+''.join('<td>'+esc('NULL' if v is None else str(v))+'</td>' for v in row)+'</tr>' for row in rows)
        blocks.append('<h3>'+esc(name)+'</h3><div class="table"><table><thead><tr>'+headings+'</tr></thead><tbody>'+body+'</tbody></table></div>')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>QueryWitness · Replayable counterexample</title><style>body{max-width:1000px;margin:3rem auto;padding:0 1.3rem;font:16px/1.55 system-ui;color:#183032;background:#f5f7f4}h1{font-size:2.8rem;letter-spacing:-.04em}pre,.table{padding:1rem;background:white;border:1px solid #d4ddd6;border-radius:12px;overflow:auto}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:.55rem;border-bottom:1px solid #d4ddd6}code{overflow-wrap:anywhere}.badge{color:#80551e}footer{padding:2rem 0;font-size:.85rem}</style><body><p class="badge">OBSERVED COUNTEREXAMPLE · '''+esc(value['policy'].upper())+''' SEMANTICS</p><h1>One database. Two different answers.</h1><p>Both queries executed successfully. This fixture preserves the declared constraints. No-counterexample results never establish equivalence.</p><h2>Reference</h2><pre>'''+esc(value['reference'])+'</pre><h2>Candidate</h2><pre>'+esc(value['candidate'])+'</pre><h2>Witness tables</h2>'+''.join(blocks)+'<h2>Comparison</h2>'+pre(value['comparison'])+'<h2>Reference output · exact typed values</h2>'+pre(value['reference_observation'])+'<h2>Candidate output · exact typed values</h2>'+pre(value['candidate_observation'])+'<h2>Reduction</h2>'+pre(value['reduction'])+'<h2>Replay</h2><pre>querywitness replay witness.json</pre><h2>Provenance</h2>'+pre(value['provenance'])+'<footer>Checksum: <code>'+esc(value['integrity_sha256'])+'</code><p>Contains the supplied SQL and database values. Review before sharing. Restricted local execution is not a multi-tenant security sandbox.</p></footer></body></html>'


def write_bundle(value,destination):
    verify_witness(value);destination=Path(destination)
    # Exclusive directory creation makes accidental input replacement impossible.
    destination.mkdir(parents=True,exist_ok=False)
    (destination/'witness.json').write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    (destination/'fixture.sql').write_text(sql_fixture(value),encoding='utf-8')
    (destination/'report.html').write_text(render_report(value),encoding='utf-8')
    return destination

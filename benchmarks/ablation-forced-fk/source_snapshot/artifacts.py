"""Portable witness bundles with exact observations and self-integrity checks."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from copy import deepcopy
import hashlib
import html
import json
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
    ExecutionLimits(**value['execution_limits'])
    if value['policy'] not in ('bag','set','ordered'): raise ValueError('Unknown comparison policy')
    if not isinstance(value['reference'],str) or not isinstance(value['candidate'],str): raise ValueError('Queries must be text')
    return schema


def replay(value):
    schema=verify_witness(value);limits=ExecutionLimits(**value['execution_limits'])
    a=execute(schema,value['instance'],value['reference'],limits,policy=value['policy']);b=execute(schema,value['instance'],value['candidate'],limits,policy=value['policy'])
    comparison=compare_results(a,b,value['policy'])
    exact=observation(a)==value['reference_observation'] and observation(b)==value['candidate_observation']
    return {'status':'reproduced' if exact and comparison['status']=='mismatch' else ('inconclusive' if comparison['status']=='inconclusive' else 'observation_changed'),
        'exact_observations':exact,'comparison':comparison,'recorded_sqlite_version':value['provenance']['sqlite_version'],
        'current_sqlite_version':sqlite3.sqlite_version,'runtime_version_changed':sqlite3.sqlite_version!=value['provenance']['sqlite_version'],
        'reference_observation':observation(a),'candidate_observation':observation(b)}


def sql_fixture(value):
    schema=verify_witness(value);db=open_database(schema,value['instance'])
    try:
        statements=list(db.iterdump())
        creates=[s for s in statements if s.startswith('CREATE TABLE ')]
        rest=[s for s in statements if not s.startswith('CREATE TABLE ') and s not in ('BEGIN TRANSACTION;','COMMIT;')]
        dump='\n'.join(['BEGIN TRANSACTION;',*creates,*rest,'COMMIT;'])
    finally: db.close()
    return '-- QueryWitness fixture. Inspect supplied queries before running.\nPRAGMA foreign_keys=ON;\n'+dump+'\n\n-- Reference query\n'+value['reference'].rstrip(';')+';\n\n-- Candidate query\n'+value['candidate'].rstrip(';')+';\n'


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

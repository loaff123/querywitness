"""Hand-authored synthetic semantic families and independent fixture checks."""
from collections import Counter
from importlib.resources import files
import json
from .schema import Schema
from .engine import execute


def load_catalog():
    return json.loads(files('querywitness').joinpath('data/catalog.json').read_text(encoding='utf-8'))


def validate_catalog():
    failures=[];cases=load_catalog()['cases']
    for case in cases:
        schema=Schema.from_dict(case['schema'])
        for label in ('benign','revealing'):
            data=case[label];schema.validate_instance(data)
            outputs={name:execute(schema,data,case[name]) for name in ('reference','mutant','equivalent_control')}
            for name,result in outputs.items():
                if result.status!='ok': failures.append({'family':case['id'],'fixture':label,'query':name,'detail':result.detail})
            if any(r.status!='ok' for r in outputs.values()): continue
            bags={name:Counter(r.rows) for name,r in outputs.items()}
            if bags['reference']!=bags['equivalent_control']: failures.append({'family':case['id'],'fixture':label,'detail':'Equivalent control differs'})
            if label=='benign':
                if bags['reference']!=bags['mutant']: failures.append({'family':case['id'],'detail':'Benign fixture does not mask mutant'})
            else:
                # Literal hand-computed expected outputs: no use of the production comparator.
                for name in ('reference','mutant'):
                    if bags[name]!=Counter(map(tuple,case['expected_'+name])): failures.append({'family':case['id'],'detail':'Independent expected output differs: '+name})
                if bags['reference']==bags['mutant']: failures.append({'family':case['id'],'detail':'Revealing fixture does not distinguish'})
    return {'families':len(cases),'fixture_query_executions':len(cases)*6,'failures':failures}

"""Result comparison only; agreement on an instance is never equivalence."""
from collections import Counter
from .engine import QueryResult

def cell_key(value):
    if value is None:return ('null',)
    if type(value) is int:return ('number',value,1)
    if type(value) is float:
        n,d=value.as_integer_ratio();return ('number',n,d)
    if isinstance(value,str):return ('text',value)
    if isinstance(value,bytes):return ('blob',value.hex())
    raise TypeError('Unsupported result cell')

def encode_cell(value):
    if value is None:return {'type':'null','value':None}
    if type(value) is int:return {'type':'integer','value':str(value)}
    if type(value) is float:return {'type':'real','value':value.hex()}
    if isinstance(value,bytes):return {'type':'blob','value':value.hex()}
    if isinstance(value,str):return {'type':'text','value':value}
    raise TypeError('Unsupported result cell')

def compare_results(reference:QueryResult,candidate:QueryResult,policy='bag')->dict:
    if policy not in ('bag','set','ordered'):raise ValueError('Unknown comparison policy')
    base={'policy':policy,'reference_status':reference.status,'candidate_status':candidate.status}
    if reference.status!='ok' or candidate.status!='ok':
        return {**base,'status':'inconclusive','reference_detail':reference.detail,'candidate_detail':candidate.detail}
    a=[tuple(map(cell_key,row)) for row in reference.rows]
    b=[tuple(map(cell_key,row)) for row in candidate.rows]
    if len(reference.columns)!=len(candidate.columns):return {**base,'status':'mismatch','reason':'column_count','reference_columns':len(reference.columns),'candidate_columns':len(candidate.columns)}
    same=(a==b) if policy=='ordered' else ((set(a)==set(b)) if policy=='set' else Counter(a)==Counter(b))
    ac=Counter(a) if policy!='set' else Counter(set(a));bc=Counter(b) if policy!='set' else Counter(set(b))
    return {**base,'status':'agreement' if same else 'mismatch','reason':'observed_rows','reference_rows':len(a),'candidate_rows':len(b),'reference_only_count':sum((ac-bc).values()),'candidate_only_count':sum((bc-ac).values())}

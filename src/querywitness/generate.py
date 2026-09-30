"""Deterministic finite-domain sampling, not constraint-complete synthesis."""
import random
from .schema import Schema, SchemaError, Column

class GenerationError(ValueError):pass

def topological_tables(schema:Schema):
    remaining=list(schema.tables);result=[];known=set()
    while remaining:
        ready=[t for t in remaining if all(f.table in known for f in t.foreign_keys)]
        if not ready:raise GenerationError('Cyclic/self-referencing foreign keys are not supported by the generator; explicit replay instances remain supported')
        for t in sorted(ready,key=lambda t:t.name):result.append(t);known.add(t.name);remaining.remove(t)
    return result

def generate_instance(schema:Schema,seed:int,strategy:str='random',max_rows:int=8)->dict:
    if type(seed) is not int or not 0<=seed<2**63:raise GenerationError('Seed must be a nonnegative 63-bit integer')
    if strategy not in ('random','boundary'):raise GenerationError('Unknown generation strategy')
    if type(max_rows) is not int or not 1<=max_rows<=32:raise GenerationError('Rows per table must be 1–32')
    order=topological_tables(schema);rng=random.Random(seed)
    data={t.name:[] for t in schema.tables}
    # Cycling boundary schedules are disclosed; no strategy is query-complete.
    if strategy=='boundary' and seed%8==0:return data
    by_name={t.name:t for t in schema.tables}
    def choose(c:Column,primary:bool,index:int):
        if c.nullable and not primary and rng.random()<(0.55 if strategy=='boundary' and seed%8==1 else 0.15):return None
        domain=c.domain
        if domain is None:
            domain=(-2,-1,0,1,2,10,100) if c.kind=='INTEGER' else ((-1.5,-0.5,0.0,0.5,1.0,2.0,10.0) if c.kind=='REAL' else ('','A','B','0','01','x','é'))
        if primary and c.domain is None and c.kind=='INTEGER':return index+1
        return rng.choice(domain)
    for t in order:
        wanted=max_rows if strategy=='boundary' and seed%8 in (2,3) else rng.randint(0,max_rows)
        for attempt in range(max(1,wanted)*40):
            if len(data[t.name])>=wanted:break
            row=[choose(c,c.name in t.primary_key,len(data[t.name])) for c in t.columns]
            for fk in t.foreign_keys:
                parent=by_name[fk.table];p_rows=data[fk.table];indices=t.indices(fk.columns)
                # A NULL in any component satisfies SQLite MATCH SIMPLE;
                # preserve these legal cases instead of forcing a parent match.
                if any(row[i] is None for i in indices):
                    continue
                if p_rows:
                    selected=rng.choice(p_rows)
                    for i,j in zip(indices,parent.indices(fk.targets)):row[i]=selected[j]
                elif all(t.columns[i].nullable and t.columns[i].name not in t.primary_key for i in indices):
                    for i in indices:row[i]=None
                else:row=None;break
            if row is None:continue
            data[t.name].append(row)
            try:schema.validate_instance(data)
            except SchemaError:data[t.name].pop()
    schema.validate_instance(data)
    return data

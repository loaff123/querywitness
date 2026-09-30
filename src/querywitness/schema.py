"""Bounded relational contracts; NULL semantics follow SQLite constraints."""
from __future__ import annotations
from dataclasses import dataclass
import math
import re
from typing import Any

class SchemaError(ValueError):
    pass

_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,62}$')
MAX_TABLES, MAX_COLUMNS, MAX_ROWS, MAX_TEXT = 12, 32, 2000, 4096

def _name(value: Any) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value) or value.lower().startswith('sqlite_'):
        raise SchemaError('Identifiers must be ASCII names of 1–63 characters, excluding sqlite_ prefix')
    return value

def _keys(obj: Any, allowed: set[str], required: set[str]) -> dict:
    if not isinstance(obj, dict) or set(obj) - allowed or required - set(obj):
        raise SchemaError('Missing, unknown, or malformed contract fields')
    return obj

def _cell(value: Any, kind: str, nullable: bool = True) -> bool:
    if value is None:
        return nullable
    if kind == 'INTEGER':
        return type(value) is int and -(2**63) <= value < 2**63
    if kind == 'REAL':
        return ((type(value) is int and abs(value) <= 2**53) or (type(value) is float and abs(value) <= 1e100 and math.isfinite(value)))
    return isinstance(value, str) and len(value.encode('utf-8', errors='surrogatepass')) <= MAX_TEXT and '\0' not in value and not any(0xD800 <= ord(c) <= 0xDFFF for c in value)

@dataclass(frozen=True)
class Column:
    name: str
    kind: str
    nullable: bool
    domain: tuple | None = None

@dataclass(frozen=True)
class ForeignKey:
    columns: tuple[str, ...]
    table: str
    targets: tuple[str, ...]

@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...]
    unique: tuple[tuple[str, ...], ...]
    foreign_keys: tuple[ForeignKey, ...]
    def indices(self, columns: tuple[str, ...]) -> tuple[int, ...]:
        positions = {c.name: i for i, c in enumerate(self.columns)}
        return tuple(positions[c] for c in columns)

@dataclass(frozen=True)
class Schema:
    tables: tuple[Table, ...]

    @classmethod
    def from_dict(cls, definition: dict) -> 'Schema':
        _keys(definition, {'tables'}, {'tables'})
        items = definition['tables']
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_TABLES:
            raise SchemaError('Schema requires 1–12 tables')
        tables = []
        for item in items:
            _keys(item, {'name','columns','primary_key','unique','foreign_keys'}, {'name','columns'})
            name = _name(item['name'])
            if not isinstance(item['columns'], list) or not 1 <= len(item['columns']) <= MAX_COLUMNS:
                raise SchemaError('Table requires 1–32 columns')
            columns = []
            for c in item['columns']:
                _keys(c, {'name','type','nullable','domain'}, {'name','type'})
                cn = _name(c['name']); kind = c['type']; nullable = c.get('nullable', True)
                if kind not in ('INTEGER','REAL','TEXT') or type(nullable) is not bool:
                    raise SchemaError('Unsupported column type or nullable flag')
                domain = c.get('domain')
                if 'domain' in c:
                    if not isinstance(domain, list) or not 1 <= len(domain) <= 64 or not all(_cell(v,kind,False) for v in domain):
                        raise SchemaError('Domain must contain 1–64 non-NULL values of the column type')
                    domain = tuple(domain)
                columns.append(Column(cn,kind,nullable,domain))
            names = [c.name for c in columns]
            if len({n.lower() for n in names}) != len(names):
                raise SchemaError('Column names collide under SQLite case rules')
            def group(v: Any, empty: bool = False) -> tuple[str, ...]:
                if not isinstance(v,list) or (not v and not empty) or len(set(map(str,v))) != len(v) or any(not isinstance(n,str) or n not in names for n in v):
                    raise SchemaError('Invalid column group')
                return tuple(v)
            primary = group(item.get('primary_key',[]),True)
            us = item.get('unique',[])
            fs = item.get('foreign_keys',[])
            if not isinstance(us,list) or len(us)>32 or not isinstance(fs,list) or len(fs)>32:
                raise SchemaError('Invalid constraint list')
            unique = tuple(group(u) for u in us)
            foreign = []
            for f in fs:
                _keys(f, {'columns','references'}, {'columns','references'})
                r=_keys(f['references'],{'table','columns'},{'table','columns'})
                target=r['columns']; local=group(f['columns'])
                if not isinstance(target,list) or len(target)!=len(local) or any(not isinstance(t,str) for t in target) or len(set(target))!=len(target):
                    raise SchemaError('Foreign key column counts must match')
                foreign.append(ForeignKey(local,_name(r['table']),tuple(target)))
            tables.append(Table(name,tuple(columns),primary,unique,tuple(foreign)))
        if len({t.name.lower() for t in tables}) != len(tables):
            raise SchemaError('Table names collide under SQLite case rules')
        by_name={t.name:t for t in tables}
        for t in tables:
            for f in t.foreign_keys:
                parent=by_name.get(f.table)
                if parent is None or f.targets not in (parent.primary_key,*parent.unique):
                    raise SchemaError('Foreign key must reference a declared primary/unique key')
                for local,target in zip(f.columns,f.targets):
                    if t.columns[t.indices((local,))[0]].kind != parent.columns[parent.indices((target,))[0]].kind:
                        raise SchemaError('Foreign key types must match exactly')
        return cls(tuple(tables))

    def to_dict(self) -> dict:
        return {'tables': [
            {'name': t.name,
             'columns': [dict(name=c.name, type=c.kind, nullable=c.nullable, **({'domain': list(c.domain)} if c.domain is not None else {})) for c in t.columns],
             'primary_key': list(t.primary_key), 'unique': [list(g) for g in t.unique],
             'foreign_keys': [{'columns': list(f.columns), 'references': {'table': f.table, 'columns': list(f.targets)}} for f in t.foreign_keys]}
            for t in self.tables]}

    def validate_instance(self, data: dict[str,list[list]]) -> None:
        if not isinstance(data,dict) or set(data)!={t.name for t in self.tables}:
            raise SchemaError('Instance must contain exactly the declared tables')
        count=0
        for t in self.tables:
            rows=data[t.name]
            if not isinstance(rows,list): raise SchemaError('Rows must be lists')
            count+=len(rows)
            if count>MAX_ROWS: raise SchemaError('Instance exceeds 2000 total rows')
            for row in rows:
                if not isinstance(row,(list,tuple)) or len(row)!=len(t.columns): raise SchemaError('Row width mismatch')
                for c,v in zip(t.columns,row):
                    if not _cell(v,c.kind,c.nullable and c.name not in t.primary_key): raise SchemaError('Invalid cell type, NULL, or bound')
                    if v is not None and c.domain is not None and v not in c.domain: raise SchemaError('Cell is outside declared domain')
            for group in ((t.primary_key,) if t.primary_key else ()) + t.unique:
                indices=t.indices(group);seen=set()
                for row in rows:
                    key=tuple(row[i] for i in indices)
                    if any(v is None for v in key): continue
                    if key in seen:raise SchemaError('Primary/unique key violated')
                    seen.add(key)
        by_name={t.name:t for t in self.tables}
        for t in self.tables:
            for f in t.foreign_keys:
                parent=by_name[f.table];pi=parent.indices(f.targets);ci=t.indices(f.columns)
                keys={tuple(row[i] for i in pi) for row in data[parent.name]}
                for row in data[t.name]:
                    key=tuple(row[i] for i in ci)
                    if not any(v is None for v in key) and key not in keys:raise SchemaError('Foreign key violated')

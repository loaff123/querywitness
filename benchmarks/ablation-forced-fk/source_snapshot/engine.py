"""Restricted local SQLite execution, not a multi-tenant hostile-code sandbox."""
from __future__ import annotations
from dataclasses import dataclass
import math
import re
import sqlite3
import time
from .schema import Schema
from .semantics import parse_supported, ordered_reason

@dataclass(frozen=True)
class ExecutionLimits:
    rows: int = 10000
    bytes: int = 2000000
    vm_steps: int = 1000000
    seconds: float = 2.0
    sql_bytes: int = 32768
    def __post_init__(self):
        for name in ('rows','bytes','vm_steps','sql_bytes'):
            value=getattr(self,name)
            if type(value) is not int or not 1<=value<=10000000: raise ValueError('Invalid execution limit')
        if type(self.seconds) not in (float,int) or not math.isfinite(self.seconds) or not 0<self.seconds<=60:raise ValueError('Invalid time limit')

@dataclass(frozen=True)
class QueryResult:
    status: str
    columns: tuple[str,...] = ()
    rows: tuple[tuple,...] = ()
    detail: str | None = None

SAFE_FUNCTIONS=frozenset('abs avg char coalesce count hex ifnull instr length like likelihood likely lower ltrim max min nullif quote replace round rtrim sign substr substring sum total trim typeof unicode unlikely upper'.split())

def quote_identifier(name:str)->str:return '"'+name.replace('"','""')+'"'

def open_database(schema:Schema,data:dict)->sqlite3.Connection:
    schema.validate_instance(data)
    db=sqlite3.connect(':memory:');db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA temp_store=MEMORY')
    db.execute('PRAGMA trusted_schema=OFF')
    db.execute('PRAGMA defer_foreign_keys=ON')
    try:
        for table in schema.tables:
            pieces=[quote_identifier(c.name)+' '+c.kind+(' NOT NULL' if not c.nullable or c.name in table.primary_key else '') for c in table.columns]
            if table.primary_key:pieces.append('PRIMARY KEY ('+','.join(map(quote_identifier,table.primary_key))+')')
            for group in table.unique:pieces.append('UNIQUE ('+','.join(map(quote_identifier,group))+')')
            for f in table.foreign_keys:pieces.append('FOREIGN KEY ('+','.join(map(quote_identifier,f.columns))+') REFERENCES '+quote_identifier(f.table)+'('+','.join(map(quote_identifier,f.targets))+') DEFERRABLE INITIALLY DEFERRED')
            db.execute('CREATE TABLE '+quote_identifier(table.name)+' ('+','.join(pieces)+')')
        for table in schema.tables:
            db.executemany('INSERT INTO '+quote_identifier(table.name)+' VALUES ('+','.join('?' for _ in table.columns)+')',data[table.name])
        db.commit()
        if db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('SQLite rejected foreign key constraints')
        return db
    except BaseException:
        db.close();raise

def execute(schema:Schema,data:dict,sql:str,limits:ExecutionLimits|None=None,*,policy="bag")->QueryResult:
    limits=limits or ExecutionLimits()
    if policy not in ("bag","set","ordered"):raise ValueError("Unknown comparison policy")
    if not isinstance(sql,str) or len(sql.encode('utf-8',errors='surrogatepass'))>limits.sql_bytes or '\0' in sql:return QueryResult('unsupported',detail='SQL text exceeds limits or contains NUL')
    if any(0xD800<=ord(c)<=0xDFFF for c in sql):return QueryResult('unsupported',detail='SQL contains invalid Unicode surrogates')
    _,reason=parse_supported(sql)
    if reason:return QueryResult('unsupported',detail=reason)
    if policy=="ordered":
        reason=ordered_reason(sql)
        if reason:return QueryResult("unsupported",detail=reason)
    db=open_database(schema,data)
    allowed_tables={t.name.lower() for t in schema.tables}
    denied=[];count=0;start=time.monotonic()
    def authorize(action,arg1,arg2,database,trigger):
        if action in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_RECURSIVE):return sqlite3.SQLITE_OK
        if action==sqlite3.SQLITE_READ and (database in ('main',None)) and (arg1 or '').lower() in allowed_tables:return sqlite3.SQLITE_OK
        if action==sqlite3.SQLITE_FUNCTION and (arg2 or '').lower() in SAFE_FUNCTIONS:return sqlite3.SQLITE_OK
        denied.append(str(arg2 or arg1 or action));return sqlite3.SQLITE_DENY
    def progress():
        nonlocal count
        count+=100
        return int(count>=limits.vm_steps or time.monotonic()-start>limits.seconds)
    try:
        db.execute('PRAGMA query_only=ON')
        for category,value in [(sqlite3.SQLITE_LIMIT_LENGTH,limits.bytes),(sqlite3.SQLITE_LIMIT_SQL_LENGTH,limits.sql_bytes),(sqlite3.SQLITE_LIMIT_COLUMN,64),(sqlite3.SQLITE_LIMIT_EXPR_DEPTH,100),(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT,25),(sqlite3.SQLITE_LIMIT_ATTACHED,0),(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER,0)]:db.setlimit(category,value)
        db.set_authorizer(authorize);db.set_progress_handler(progress,100)
        cur=db.execute(sql)
        if cur.description is None:return QueryResult('unsupported',detail='Statement does not return a relation')
        rows=[];size=0
        for row in cur:
            if len(rows)>=limits.rows:return QueryResult('resource_limit',detail='Output row budget exceeded')
            size+=sum(len(str(v).encode('utf-8',errors='surrogatepass')) if v is not None else 1 for v in row)
            if size>limits.bytes or time.monotonic()-start>limits.seconds:return QueryResult('resource_limit',detail='Output or elapsed-time budget exceeded')
            if any(isinstance(v,float) and not math.isfinite(v) for v in row):return QueryResult('unsupported',detail='Nonfinite numeric output excluded')
            rows.append(tuple(row))
        return QueryResult('ok',tuple(c[0] for c in cur.description),tuple(rows))
    except sqlite3.Error as e:
        if denied:return QueryResult('unsupported',detail='SQL operation/function not permitted: '+denied[0])
        if 'interrupt' in str(e).lower() or count>=limits.vm_steps or time.monotonic()-start>limits.seconds:return QueryResult('resource_limit',detail='SQLite execution budget exceeded')
        return QueryResult('query_error',detail=str(e))
    finally:db.close()

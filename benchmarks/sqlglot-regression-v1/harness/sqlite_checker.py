"""Independent bounded SQLite observation and exact bag comparison.

Standard library only. Does not import QueryWitness or SQLGlot, construct SQL
from a parser AST, or call any QueryWitness builder/executor/comparator.
"""
from collections import Counter
from fractions import Fraction
import math
import re
import sqlite3
import time

MAX_ROWS = 8
LIMITS = {'rows': 10000, 'bytes': 2000000, 'vm_steps': 1000000, 'seconds': 2.0, 'sql_bytes': 32768}

def cell_key(value):
    if value is None:
        return ('null',)
    if type(value) is int:
        return ('number', Fraction(value))
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError('nonfinite result')
        return ('number', Fraction.from_float(value))
    if isinstance(value, str):
        return ('text', value)
    if isinstance(value, bytes):
        return ('blob', value)
    raise ValueError('unsupported result type')

def bag_key(rows):
    return Counter(tuple(cell_key(c) for c in row) for row in rows)

def encode(value):
    cell_key(value)
    if value is None: return {'type': 'null'}
    if type(value) is int: return {'type': 'integer', 'value': str(value)}
    if type(value) is float: return {'type': 'real', 'value': value.hex()}
    if isinstance(value, bytes): return {'type': 'blob', 'value': value.hex()}
    return {'type': 'text', 'value': value}

def decode(cell):
    kind = cell['type']
    if kind == 'null': return None
    if kind == 'integer': return int(cell['value'])
    if kind == 'real': return float.fromhex(cell['value'])
    if kind == 'blob': return bytes.fromhex(cell['value'])
    if kind == 'text': return cell['value']
    raise ValueError('invalid encoded cell')

def observe(columns, rows, sql):
    if not columns or len(set(columns)) != len(columns) or any(not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', c) for c in columns):
        raise ValueError('invalid columns')
    if len(rows) > MAX_ROWS:
        raise ValueError('instance exceeds frozen row bound')
    for row in rows:
        if len(row) != len(columns) or any(v is not None and (type(v) is not int or not -(2**63) <= v < 2**63) for v in row):
            raise ValueError('invalid nullable INTEGER row')
    if len(sql.encode()) > LIMITS['sql_bytes']:
        return {'status': 'error', 'error_type': 'limit', 'error': 'SQL byte bound'}
    if not sql.lstrip().upper().startswith('SELECT '):
        raise ValueError('only frozen SELECT adapters are supported')
    conn = sqlite3.connect(':memory:')
    try:
        conn.execute('CREATE TABLE regression_input (' + ', '.join('"' + c + '" INTEGER' for c in columns) + ')')
        conn.executemany('INSERT INTO regression_input VALUES (' + ','.join('?' for _ in columns) + ')', rows)
        conn.execute('PRAGMA query_only=ON')
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, LIMITS['bytes'])
        conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, LIMITS['sql_bytes'])
        conn.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 64)
        conn.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 100)
        conn.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 25)
        conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
        conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 0)
        functions = set()
        def trace_function(action, arg1, arg2, database, trigger):
            if action == sqlite3.SQLITE_FUNCTION:
                functions.add((arg2 or '').lower())
            return sqlite3.SQLITE_OK
        conn.set_authorizer(trace_function)
        start = time.perf_counter()
        vm_steps = 0
        def progress():
            nonlocal vm_steps
            vm_steps += 100
            return int(vm_steps > LIMITS['vm_steps'] or time.perf_counter() - start > LIMITS['seconds'])
        conn.set_progress_handler(progress, 100)
        try:
            cursor = conn.execute(sql)
            result = cursor.fetchmany(LIMITS['rows'] + 1)
            if len(result) > LIMITS['rows']:
                raise ValueError('output row bound')
            if sum(len(str(v).encode()) for row in result for v in row) > LIMITS['bytes']:
                raise ValueError('output byte bound')
            return {'status': 'ok', 'functions': sorted(functions), 'columns': len(cursor.description), 'rows': [[encode(v) for v in row] for row in result]}
        except (sqlite3.Error, ValueError) as exc:
            return {'status': 'error', 'functions': sorted(functions), 'error_type': type(exc).__name__, 'error': str(exc)}
    finally:
        conn.close()

def compare(left, right):
    if left['status'] != 'ok' or right['status'] != 'ok': return 'inconclusive'
    if left['columns'] != right['columns']: return 'mismatch'
    a = [[decode(c) for c in row] for row in left['rows']]
    b = [[decode(c) for c in row] for row in right['rows']]
    return 'same' if bag_key(a) == bag_key(b) else 'mismatch'

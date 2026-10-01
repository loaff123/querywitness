"""Constraint-checked heuristic schedules over a compiled finite domain.

This module never executes SQL and never interprets a failed search as proof.
The original random/boundary sampler deliberately lives in a separate module.
"""
from __future__ import annotations

import hashlib
import json
import random

from .generate import GenerationError, topological_tables
from .schema import Schema, SchemaError, _cell
from .query_plan import QueryPlan


def _validate_plan(schema: Schema, plan: QueryPlan) -> None:
    """Reject stale/manual plan fields before they can escape a recorded bound."""
    if type(plan) is not QueryPlan:
        raise GenerationError('Use a QueryPlan produced by compile_plan')
    try:
        columns = {(t.name,c.name): c for t in schema.tables for c in t.columns}
        if type(plan.pools) is not tuple or len(plan.pools) != len(columns):
            raise ValueError('pool count')
        pools = {(t,c): values for t,c,values in plan.pools}
        if set(pools) != set(columns):
            raise ValueError('pool columns')
        for key, values in pools.items():
            col = columns[key]
            if type(values) is not tuple or not 1 <= len(values) <= 64:
                raise ValueError('pool bounds')
            if any(not _cell(v,col.kind,False) or
                   (col.domain is not None and v not in col.domain) for v in values):
                raise ValueError('pool value outside schema')
        if type(plan.preferred) is not tuple or len(plan.preferred) > len(columns):
            raise ValueError('preferred bounds')
        preferred = {(t,c): values for t,c,values in plan.preferred}
        if len(preferred) != len(plan.preferred):
            raise ValueError('duplicate preferred column')
        for key, values in preferred.items():
            if key not in pools or type(values) is not tuple or len(values)>64:
                raise ValueError('preferred column or bounds')
            if any(not any(type(v) is type(p) and v==p for p in pools[key]) for v in values):
                raise ValueError('preferred value outside pool')
        if type(plan.counts) is not tuple or len(plan.counts)>33 or any(
                type(v) is not int or not 0<=v<=plan.max_rows for v in plan.counts):
            raise ValueError('count row target out of range')
        if type(plan.groups) is not tuple or any(key not in columns for key in plan.groups):
            raise ValueError('group column')
        if type(plan.joins) is not tuple or any(a not in columns or b not in columns or
                columns[a].kind != columns[b].kind for a,b in plan.joins):
            raise ValueError('join column or type')
        expected = {'schema_sha256':plan.schema_sha256,'max_rows':plan.max_rows,
                    'preferred':plan.preferred,'joins':plan.joins,'groups':plan.groups,
                    'counts':plan.counts,'effective_domains':[
                        dict(table=t,column=c,type=columns[t,c].kind,
                             explicit_domain=columns[t,c].domain is not None,pool=values)
                        for t,c,values in plan.pools]}
        manifest=plan.to_dict()
        for key,value in expected.items():
            if json.dumps(value,sort_keys=True,allow_nan=False) != json.dumps(manifest[key],sort_keys=True,allow_nan=False):
                raise ValueError('stale '+key+' manifest')
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError) as error:
        raise GenerationError('Invalid or stale query plan: '+str(error)[:120]) from error


def generate_query_aware(schema: Schema, plan: QueryPlan, seed: int) -> tuple[dict, dict]:
    """Return a schema-valid database and exact finite generation accounting.

    Eight schedules alternate empty, NULL-rich, join/group duplicate-rich,
    join/group distinct-rich, count-target, unmatched and random exploration.
    Schedules are hints, never a promise that a predicate/group is reached.
    """
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise GenerationError('Seed must be a nonnegative 63-bit integer')
    if type(plan) is not QueryPlan:
        raise GenerationError('Use a QueryPlan produced by compile_plan')
    signature = hashlib.sha256(json.dumps(schema.to_dict(), sort_keys=True,
                                          separators=(',', ':')).encode()).hexdigest()
    if signature != plan.schema_sha256:
        raise GenerationError('Query plan belongs to a different schema')
    if type(plan.max_rows) is not int or not 1 <= plan.max_rows <= 32:
        raise GenerationError('Rows per table must be 1–32')
    _validate_plan(schema, plan)
    order = topological_tables(schema)
    pools = {(t, c): values for t, c, values in plan.pools}
    preferred = {(t, c): values for t, c, values in plan.preferred}
    expected = {(t.name, c.name) for t in schema.tables for c in t.columns}
    if set(pools) != expected or any(not values or len(values) > 64 for values in pools.values()):
        raise GenerationError('Query plan must provide 1–64 values for every column')
    rng = random.Random(seed)
    data = {t.name: [] for t in schema.tables}
    mode = seed % 8
    stats = {'schedule': ('empty', 'null_rich', 'join_duplicates', 'join_distinct',
                           'count_target', 'unmatched', 'random', 'random')[mode],
             'attempted_rows': 0, 'accepted_rows': 0, 'rejected_rows': 0,
             'requested_rows': {}, 'attempt_budget': 0}
    if mode == 0:
        stats['requested_rows'] = {t.name: 0 for t in schema.tables}
        return data, stats

    # Union only physical columns that the scoped compiler resolved safely.
    parents = {key: key for key in pools}
    def root(key):
        while parents[key] != key:
            key = parents[key]
        return key
    for a, b in plan.joins:
        if a in parents and b in parents:
            parents[root(b)] = root(a)
    components = {}
    for key in sorted(parents):
        components.setdefault(root(key), []).append(key)
    participating = {key for edge in plan.joins for key in edge} | set(plan.groups)
    shared = {}
    for keys in components.values():
        if not any(key in participating for key in keys):
            continue
        common = [v for v in pools[keys[0]] if all(v in pools[k] for k in keys[1:])]
        if not common:
            continue
        favored = [v for v in common if any(v in preferred.get(k, ()) for k in keys)]
        value = rng.choice(favored or common)
        shared.update({key: next(v for v in pools[key] if v == value) for key in keys})
    # Select constants once per database so duplicate-rich schedules are real.
    constants = {key: rng.choice(preferred.get(key) or values) for key, values in pools.items()}
    focus = (seed // 8) % len(order)
    targets = plan.counts  # Compiler already expands each threshold to legal neighbors.
    by_name = {t.name: t for t in schema.tables}
    for table_index, table in enumerate(order):
        if mode in (2, 3):
            target = targets[(seed // 8 // len(order)) % len(targets)] if mode == 2 and targets else plan.max_rows
            wanted = target if table_index == focus else 1
        elif mode == 4:
            wanted = targets[(seed // 8) % len(targets)] if targets else plan.max_rows
        else:
            wanted = rng.randint(0, plan.max_rows)
        stats['requested_rows'][table.name] = wanted
        attempts = wanted * 40
        stats['attempt_budget'] += attempts
        for attempt in range(attempts):
            if len(data[table.name]) >= wanted:
                break
            stats['attempted_rows'] += 1
            row = []
            for column in table.columns:
                key = (table.name, column.name)
                values = pools[key]
                primary = column.name in table.primary_key
                nullable = column.nullable and not primary
                templated = mode in (2, 3, 4)
                if nullable and not templated and rng.random() < (0.55 if mode == 1 else 0.15):
                    value = None
                elif templated:
                    if primary and len(data[table.name]) > 0:
                        value = values[attempt % len(values)]
                    elif key in shared:
                        value = shared[key]
                    elif mode == 3:
                        value = values[attempt % len(values)]
                    else:
                        value = constants[key]
                elif mode == 5:
                    value = values[(attempt + table_index + seed // 8) % len(values)]
                else:
                    favored = preferred.get(key)
                    value = rng.choice(favored if favored and rng.random() < 0.35 else values)
                row.append(value)
            for fk in table.foreign_keys:
                indices = table.indices(fk.columns)
                if any(row[i] is None for i in indices):
                    continue  # Preserve SQLite MATCH SIMPLE partial NULLs.
                parent = by_name[fk.table]
                parent_indices = parent.indices(fk.targets)
                candidates = [r for r in data[parent.name]
                              if all(r[j] in pools[(table.name, table.columns[i].name)]
                                     for i, j in zip(indices, parent_indices))]
                if candidates:
                    selected = candidates[0] if mode in (2, 4) else rng.choice(candidates)
                    for i, j in zip(indices, parent_indices):
                        # SQLite numeric FK equality allows INTEGER/REAL equality,
                        # but preserve an actual representative of the child's pool.
                        allowed = pools[(table.name, table.columns[i].name)]
                        row[i] = next(v for v in allowed if v == selected[j])
                elif any(table.columns[i].nullable and table.columns[i].name not in table.primary_key
                         for i in indices):
                    # One legal NULL component suffices; don't null forbidden components.
                    i = next(i for i in indices if table.columns[i].nullable
                             and table.columns[i].name not in table.primary_key)
                    row[i] = None
                else:
                    row = None
                    break
            if row is not None:
                data[table.name].append(row)
                try:
                    schema.validate_instance(data)
                except SchemaError:
                    data[table.name].pop()
                    row = None
            if row is None:
                stats['rejected_rows'] += 1
            else:
                stats['accepted_rows'] += 1
    schema.validate_instance(data)
    return data, stats

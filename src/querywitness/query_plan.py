"""Bounded, reproducible query-derived sampling hints, never a SQL solver.

Only direct physical columns are resolved. Derived/CTE outputs, coercions and
unsupported expressions are deliberately left to ordinary finite sampling.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import math
import time

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import traverse_scope

from .generate import GenerationError
from .schema import Schema, SchemaError, _cell
from .semantics import parse_supported

class PlanningBudgetExceeded(GenerationError):
    pass


GENERATOR_VERSION = 'query-aware-1'
_MAX_POOL = 64
_MAX_DIAGNOSTICS = 128
_DEFAULTS = {
    'INTEGER': (-2, -1, 0, 1, 2, 10, 100),
    'REAL': (-1.5, -0.5, 0.0, 0.5, 1.0, 2.0, 10.0),
    'TEXT': ('', 'A', 'B', '0', '01', 'x', 'é'),
}
_COMPARISONS = (exp.EQ, exp.NEQ, exp.LT, exp.LTE, exp.GT, exp.GTE)
_INTEGER = re.compile(r'^[0-9]+$')
_ASCII_CASE = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')


def _fold(name):
    return name.translate(_ASCII_CASE)


def _sort_value(value):
    return (0 if type(value) is int else 1 if type(value) is float else 2, value)


def _values(values):
    # Keep exact Python representations for declared REAL domains.
    return tuple(sorted({(type(v), v): v for v in values}.values(), key=_sort_value))


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class QueryPlan:
    """Immutable generation inputs; serialization returns a detached manifest."""
    schema_sha256: str
    max_rows: int
    pools: tuple[tuple[str, str, tuple], ...]
    preferred: tuple[tuple[str, str, tuple], ...]
    joins: tuple[tuple[tuple[str, str], tuple[str, str]], ...]
    groups: tuple[tuple[str, str], ...]
    counts: tuple[int, ...]
    _manifest_json: str

    def to_dict(self) -> dict:
        return json.loads(self._manifest_json)

    @property
    def manifest(self) -> dict:
        return self.to_dict()


def _local_nodes(root):
    """Traverse a SQLGlot scope without visiting independently scoped queries."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(child for child in node.iter_expressions()
                     if not isinstance(child, (exp.Query, exp.Subquery, exp.CTE)))


def _literal(node):
    """Return exact text or a signed64 integer; reject coercions and REALs."""
    sign = 1
    if isinstance(node, exp.Neg):
        sign, node = -1, node.this
    if not isinstance(node, exp.Literal):
        return None
    if node.is_string:
        return node.this if sign == 1 and _cell(node.this, 'TEXT', False) else None
    raw = node.this
    if not _INTEGER.fullmatch(raw):
        return None
    digits = raw.lstrip('0') or '0'
    if len(digits) > 19:
        return None
    value = sign * int(digits)
    return value if _cell(value, 'INTEGER', False) else None


def compile_plan(schema: Schema, reference: str, candidate: str,
                 max_rows: int = 8, sql_bytes: int = 32768, *,
                 deadline: float | None = None) -> QueryPlan:
    """Compile symmetric, bounded hints without modifying or executing either SQL.

    Limits apply to each SQL text, in addition to parse_supported's AST limits.
    Diagnostics are bounded and sorted. The pools include non-NULL values only;
    nullable cells are a separate schema-governed generation choice.
    """
    if deadline is not None and (type(deadline) not in (int,float) or not math.isfinite(deadline)):
        raise GenerationError('Planning deadline must be a finite monotonic time')
    def check_deadline():
        if deadline is not None and time.monotonic() >= deadline:
            raise PlanningBudgetExceeded('Search time budget exhausted during planning')
    check_deadline()
    if type(max_rows) is not int or not 1 <= max_rows <= 32:
        raise GenerationError('Rows per table must be 1–32')
    if type(sql_bytes) is not int or not 1 <= sql_bytes <= 32768:
        raise GenerationError('SQL byte limit must be 1–32768')
    if not isinstance(schema, Schema):
        raise GenerationError('Query plan requires a Schema')

    try:
        Schema.from_dict(schema.to_dict())
    except (SchemaError, TypeError, ValueError, AttributeError) as error:
        raise GenerationError('Query plan requires a valid bounded schema') from error

    trees = []
    for label, sql in (('reference', reference), ('candidate', candidate)):
        check_deadline()
        if not isinstance(sql, str) or '\0' in sql:
            raise GenerationError(f'{label} SQL must be text without NUL')
        try:
            encoded = sql.encode('utf-8')
        except UnicodeError as error:
            raise GenerationError(f'{label} SQL must contain valid Unicode') from error
        if len(encoded) > sql_bytes:
            raise GenerationError(f'{label} SQL exceeds the {sql_bytes}-byte limit')
        try:
            tree, reason = parse_supported(sql)
        except (SqlglotError, RecursionError, ValueError) as error:
            raise GenerationError(f'{label} SQL cannot be planned: {str(error)[:200]}') from error
        if reason:
            raise GenerationError(f'{label} SQL cannot be planned: {reason}')
        trees.append(tree)

    columns = {(t.name, c.name): c for t in schema.tables for c in t.columns}
    tables = {_fold(t.name): t for t in schema.tables}
    by_column = {t.name: {_fold(c.name): (t.name, c.name) for c in t.columns} for t in schema.tables}
    reserved = {}
    for table in schema.tables:
        for col in table.columns:
            vals = col.domain if col.domain is not None else _DEFAULTS[col.kind]
            if col.domain is None and col.kind == 'INTEGER' and col.name in table.primary_key:
                vals = (*vals, *range(1, max_rows + 1))
            reserved[table.name, col.name] = _values(vals)
    requested = {key: set() for key in columns}
    joins, groups, counts = set(), set(), set()
    skips, warnings = set(), set()

    def skip(reason, node=None):
        detail = ''
        if node is not None:
            detail = ': ' + node.sql(dialect='sqlite')[:120]
        skips.add(reason + detail)

    def add_literal(key, value, text_allowed=False):
        col = columns[key]
        if col.kind == 'INTEGER' and type(value) is int:
            vals = [v for v in (value - 1, value, value + 1) if _cell(v, 'INTEGER', False)]
        elif col.kind == 'TEXT' and type(value) is str and text_allowed:
            vals = [value]
        else:
            skip(f'Literal/type or operator inference unsupported for {key[0]}.{key[1]}')
            return
        for value in vals:
            if not _cell(value, col.kind, False):
                skip(f'Literal outside exact type bounds for {key[0]}.{key[1]}')
            elif col.domain is not None and value not in col.domain:
                skip(f'Literal outside explicit domain for {key[0]}.{key[1]}')
            else:
                requested[key].add(value)

    def add_join(left, right):
        if left == right:
            return
        if columns[left].kind != columns[right].kind:
            skip('Mixed-type equijoin inference unsupported')
            return
        joins.add(tuple(sorted((left, right))))

    for tree in trees:
        try:
            scopes = list(traverse_scope(tree))
        except (SqlglotError, RecursionError, ValueError) as error:
            raise GenerationError('Scope analysis failed: ' + str(error)[:200]) from error
        sources = {}
        for scope in scopes:
            check_deadline()
            # SQLite CTE names shadow physical tables case-insensitively, even
            # for forward/self references without WITH RECURSIVE. SQLGlot's
            # selected_sources does not resolve all of those cases. Inspect
            # syntactically enclosing WITH clauses before trusting a Table.
            visible_ctes = set()
            ancestor = scope.expression
            while ancestor is not None:
                with_clause = ancestor.args.get('with')
                if with_clause is not None:
                    visible_ctes.update(_fold(cte.alias_or_name) for cte in with_clause.expressions)
                ancestor = ancestor.parent
            local = {}
            try:
                selected = scope.selected_sources
            except (SqlglotError, ValueError) as error:
                sources[scope] = None
                skip('Ambiguous scope aliases: ' + str(error)[:120])
                continue
            for alias, (_, source) in selected.items():
                folded = _fold(alias)
                if folded in local:
                    local = None
                    skip('Ambiguous scope aliases under SQLite case rules')
                    break
                base = None
                if isinstance(source, exp.Table) and not source.db and not source.catalog:
                    alias_node = source.args.get('alias')
                    if _fold(source.name) in visible_ctes:
                        skip('Visible CTE source is not resolved as a physical table', source)
                    elif alias_node is None or not alias_node.args.get('columns'):
                        base = tables.get(_fold(source.name))
                local[folded] = base
            sources[scope] = local

        def resolve(column, scope):
            if not isinstance(column, exp.Column) or column.is_star or len(column.parts) > 2:
                skip('Hint requires a simple unqualified or alias-qualified column', column)
                return None
            current = scope
            while current is not None:
                local = sources.get(current)
                if local is None:
                    skip('Column belongs to an ambiguous scope', column)
                    return None
                name, qualifier = _fold(column.name), _fold(column.table)
                if qualifier:
                    if qualifier in local:
                        base = local[qualifier]
                        if base is None:
                            skip('Derived, CTE, qualified or unknown source is not resolved', column)
                            return None
                        key = by_column[base.name].get(name)
                        if key is None:
                            skip('Column missing from local aliased base table', column)
                        return key
                else:
                    if any(base is None for base in local.values()):
                        skip('Unqualified column with a derived, CTE or unknown source', column)
                        return None
                    matches = [by_column[base.name][name] for base in local.values()
                               if name in by_column[base.name]]
                    if len(matches) == 1:
                        return matches[0]
                    if len(matches) > 1:
                        skip('Ambiguous unqualified column', column)
                        return None
                    if isinstance(current.expression, exp.Select) and any(
                            item.alias and _fold(item.alias) == name for item in current.expression.expressions):
                        skip('Projection alias is not resolved as a physical column', column)
                        return None
                if not current.can_be_correlated:
                    break
                current = current.parent
            skip('Unresolved physical column', column)
            return None

        def count_hint(count, literal, scope):
            value = _literal(literal)
            argument = count.this
            if type(value) is not int or value < 0 or count.expressions or not isinstance(argument, (exp.Star, exp.Column)):
                skip('COUNT hint requires a simple COUNT and nonnegative integer literal', count)
                return
            if isinstance(argument, exp.Column) and resolve(argument, scope) is None:
                return
            counts.update(n for n in (value - 1, value, value + 1) if 0 <= n <= max_rows)
            local = sources.get(scope)
            # Products are upper bounds, not predicted outputs. Outer joins may
            # emit unmatched rows; account for those before reporting a bound.
            if local is None or any(base is None for base in local.values()):
                skip('COUNT upper bound requires only simple base-table sources')
                return
            upper = max_rows if local else 1
            query_joins = scope.expression.args.get('joins') or []
            if len(query_joins) != max(0, len(local) - 1):
                skip('COUNT upper bound skipped for non-simple source layout')
                return
            for join in query_joins:
                upper = max(upper * max_rows, upper + max_rows) if join.side.upper() == 'FULL' else upper * max_rows
                upper = min(upper, 2**63)
            if value > upper:
                warnings.add(f'COUNT threshold {value} exceeds conservative base-table upper bound {upper} at {max_rows} rows/table; no predicate conclusion is implied')

        for scope in scopes:
            check_deadline()
            for node in _local_nodes(scope.expression):
                if isinstance(node, _COMPARISONS):
                    left, right = node.this, node.expression
                    if isinstance(left, exp.Count):
                        count_hint(left, right, scope)
                    elif isinstance(right, exp.Count):
                        count_hint(right, left, scope)
                    elif isinstance(left, exp.Column) and isinstance(right, exp.Column):
                        if isinstance(node, exp.EQ):
                            a, b = resolve(left, scope), resolve(right, scope)
                            if a is not None and b is not None:
                                add_join(a, b)
                        else:
                            skip('Non-equality column relationship is not inferred', node)
                    else:
                        column, literal = (left, right) if isinstance(left, exp.Column) else (right, left)
                        if not isinstance(column, exp.Column):
                            skip('Comparison is not a direct column/literal hint', node)
                            continue
                        key = resolve(column, scope)
                        value = _literal(literal)
                        if value is None:
                            skip('Unsupported, coercing or out-of-range comparison literal', node)
                        elif key is not None:
                            add_literal(key, value, isinstance(node, exp.EQ))
                elif isinstance(node, exp.In):
                    key = resolve(node.this, scope)
                    values = [_literal(item) for item in node.expressions]
                    if node.args.get('query') is not None or not values or any(value is None for value in values):
                        skip('IN hint requires an explicit list of exact literals', node)
                    elif key is not None:
                        for value in values:
                            add_literal(key, value, True)
                elif isinstance(node, exp.Between):
                    key = resolve(node.this, scope)
                    values = [_literal(node.args.get(name)) for name in ('low', 'high')]
                    if any(type(value) is not int for value in values):
                        skip('BETWEEN hint requires exact INTEGER endpoints', node)
                    elif key is not None:
                        for value in values:
                            add_literal(key, value)
                elif isinstance(node, (exp.Like, exp.ILike, exp.Is)):
                    skip('Pattern/IS predicate does not contribute literal hints', node)

            group = scope.expression.args.get('group')
            if group is not None:
                for column in group.expressions:
                    key = resolve(column, scope)
                    if key is not None:
                        groups.add(key)
            query_joins = scope.expression.args.get('joins') or []
            for join in query_joins:
                using = join.args.get('using')
                natural = join.method.upper() == 'NATURAL'
                if not using and not natural:
                    continue
                local = sources.get(scope)
                from_clause = scope.expression.args.get('from')
                left = from_clause.this if from_clause is not None else None
                right = join.this
                if len(query_joins) != 1 or local is None or not isinstance(left, exp.Table) or not isinstance(right, exp.Table):
                    skip('NATURAL/USING hints require a single simple base-table join', join)
                    continue
                a, b = local.get(_fold(left.alias_or_name)), local.get(_fold(right.alias_or_name))
                if a is None or b is None:
                    skip('NATURAL/USING source is not a physical base table', join)
                    continue
                names = (set(by_column[a.name]) & set(by_column[b.name]) if natural else {_fold(item.name) for item in using})
                for name in sorted(names):
                    if name not in by_column[a.name] or name not in by_column[b.name]:
                        skip('USING column missing from a base table', join)
                    else:
                        add_join(by_column[a.name][name], by_column[b.name][name])

    def bounded(key, values):
        col = columns[key]
        check_deadline()
        # Every origin was type-checked once (schema/defaults/literals), and
        # propagation edges have identical declared types. Revalidating every
        # text character on each round would turn small chains into CPU traps.
        legal = _values(v for v in values if col.domain is None or v in col.domain)
        base = reserved[key]
        extras = [v for v in legal if v not in base]
        if len(base) + len(extras) > _MAX_POOL:
            warnings.add(f'Pool capped at {_MAX_POOL} values for {key[0]}.{key[1]}; defaults and declared domains retained')
        return _values((*base, *extras[:_MAX_POOL - len(base)]))

    pools = {key: bounded(key, (*reserved[key], *requested[key])) for key in columns}
    transfers = {(a, b) for a, b in joins} | {(b, a) for a, b in joins}
    for table in schema.tables:
        for fk in table.foreign_keys:
            transfers.update(((fk.table, target), (table.name, local)) for local, target in zip(fk.columns, fk.targets))
    # Synchronous, capped propagation: a value can traverse at most one edge per
    # round; all paths are bounded by the number of physical columns. Explicit
    # domains filter at every edge, including intermediate bridge columns.
    incoming = {key: [] for key in columns}
    for a, b in sorted(transfers):
        incoming[b].append(a)
    for _ in range(len(columns)):
        updated = {key: bounded(key, (*values, *(v for source in incoming[key] for v in pools[source])))
                   if incoming[key] else values for key, values in pools.items()}
        if updated == pools:
            break
        pools = updated

    check_deadline()
    schema_hash = _digest(json.dumps(schema.to_dict(), sort_keys=True, separators=(',', ':')))
    pool_items = tuple((t, c, pools[t, c]) for t, c in sorted(columns))
    preferred = tuple((t, c, _values(v for v in requested[t, c] if v in pools[t, c]))
                      for t, c in sorted(columns) if requested[t, c])
    preferred = tuple(item for item in preferred if item[2])
    if not preferred and not joins and not groups and not counts:
        warnings.add('No query hints resolved; sampling uses finite default or explicit pools')
    sorted_skips, sorted_warnings = sorted(skips), sorted(warnings)
    if len(sorted_skips) > _MAX_DIAGNOSTICS:
        sorted_warnings.append(f'Skip diagnostics truncated: {len(sorted_skips)} distinct reasons, first {_MAX_DIAGNOSTICS} retained')
    if len(sorted_warnings) > _MAX_DIAGNOSTICS:
        sorted_warnings = sorted_warnings[:_MAX_DIAGNOSTICS - 1] + ['Additional warning diagnostics truncated']
    manifest = {
        'generator_version': GENERATOR_VERSION,
        'schema_sha256': schema_hash,
        'source_sha256': {'reference': _digest(reference), 'candidate': _digest(candidate)},
        'ast_sha256': {label: _digest(tree.sql(dialect='sqlite')) for label, tree in zip(('reference', 'candidate'), trees)},
        'sqlglot_version': sqlglot.__version__,
        'max_rows': max_rows,
        'sql_bytes': sql_bytes,
        'effective_domains': [dict(table=t, column=c, type=columns[t, c].kind,
                                   explicit_domain=columns[t, c].domain is not None, pool=list(values))
                              for t, c, values in pool_items],
        'preferred': [[t, c, list(values)] for t, c, values in preferred],
        'joins': sorted(joins),
        'groups': sorted(groups),
        'counts': sorted(counts),
        'skips': sorted_skips[:_MAX_DIAGNOSTICS],
        'warnings': sorted(sorted_warnings),
    }
    return QueryPlan(schema_hash, max_rows, pool_items, preferred, tuple(sorted(joins)),
                     tuple(sorted(groups)), tuple(sorted(counts)), _json(manifest))

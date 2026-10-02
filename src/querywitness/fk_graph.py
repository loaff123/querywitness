"""Immutable row-occurrence graph for the supported schema's FK deletions.

Edges point from a uniquely supporting parent to each dependent child. Under
QueryWitness's matching-type, finite-number, BINARY-text schema contract,
Python key equality agrees with SQLite FK equality. Actual NULL components
exempt an entire FK. This is not a model of arbitrary SQLite affinities,
collations, triggers, or ON DELETE actions.

The graph is reusable after closed deletions; callers must supply a valid
surviving instance's live IDs. No database, query, or external dependency is
needed by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Iterable

from .schema import Schema, SchemaError


class ClosureDeadlineExceeded(Exception):
    """A cooperative deadline expired before the current phase completed."""

    def __init__(self, stage: str):
        self.stage = stage
        super().__init__(f'FK closure deadline exceeded during {stage}')


@dataclass(frozen=True)
class FKGraph:
    """Dense IDs index immutable coordinates, rows, and sorted child lists.

    ``tables`` includes empty tables. Cells are immutable scalar values admitted
    by Schema.validate_instance; mutable row containers are never retained.
    """

    coordinates: tuple[tuple[str, int], ...]
    adjacency: tuple[tuple[int, ...], ...]
    tables: tuple[str, ...]
    rows: tuple[tuple, ...]


def _check_deadline(deadline: float, stage: str) -> None:
    if time.monotonic() >= deadline:
        raise ClosureDeadlineExceeded(stage)


def build_fk_graph(schema: Schema, instance: dict, *,
                   deadline: float = float('inf')) -> FKGraph:
    """Validate and snapshot an instance, then index its reverse dependencies.

    Validation remains the existing full schema gate. Its synchronous call is
    bracketed by deadline checks; copying/indexing check at least once per row.
    This is a cooperative budget, not hard isolation of Python operations.
    """
    _check_deadline(deadline, 'graph_validation')
    schema.validate_instance(instance)
    _check_deadline(deadline, 'graph_validation')

    _check_deadline(deadline, 'graph_copy')
    by_name = {table.name: table for table in schema.tables}
    tables = tuple(sorted(by_name))
    coordinates = []
    rows = []
    table_ids = {}
    for name in tables:
        start = len(rows)
        for index, row in enumerate(instance[name]):
            _check_deadline(deadline, 'graph_copy')
            coordinates.append((name, index))
            rows.append(tuple(row))
        table_ids[name] = range(start, len(rows))
    _check_deadline(deadline, 'graph_copy')

    _check_deadline(deadline, 'graph_index')
    # Index only referenced ordered parent groups. NULL-containing unique keys
    # may repeat, but cannot support a fully non-NULL child reference.
    referenced = sorted({(fk.table, fk.targets)
                         for table in schema.tables for fk in table.foreign_keys})
    indexes = {}
    for name, group in referenced:
        positions = by_name[name].indices(group)
        index = {}
        for row_id in table_ids[name]:
            _check_deadline(deadline, 'graph_index')
            key = tuple(rows[row_id][position] for position in positions)
            if any(value is None for value in key):
                continue
            if key in index:
                raise SchemaError('Ambiguous foreign key parent')
            index[key] = row_id
        indexes[name, group] = index
    _check_deadline(deadline, 'graph_index')

    _check_deadline(deadline, 'graph_edges')
    adjacency = [set() for _ in rows]
    edge_count = 0
    for name in tables:
        table = by_name[name]
        foreign_keys = [(table.indices(fk.columns), indexes[fk.table, fk.targets])
                        for fk in table.foreign_keys]
        for child_id in table_ids[name]:
            _check_deadline(deadline, 'graph_edges')
            for positions, parents in foreign_keys:
                key = tuple(rows[child_id][position] for position in positions)
                if any(value is None for value in key):
                    continue
                parent_id = parents.get(key)
                if parent_id is None:
                    raise SchemaError('Missing foreign key parent')
                adjacency[parent_id].add(child_id)
                edge_count += 1
                if edge_count % 256 == 0:
                    _check_deadline(deadline, 'graph_edges')
    ordered_adjacency = []
    for children in adjacency:
        _check_deadline(deadline, 'graph_edges')
        ordered_adjacency.append(tuple(sorted(children)))
    graph = FKGraph(tuple(coordinates), tuple(ordered_adjacency), tables, tuple(rows))
    _check_deadline(deadline, 'graph_edges')
    return graph


def _validated_ids(graph: FKGraph, values: Iterable[int], *, deadline: float,
                   stage: str) -> frozenset[int]:
    """Reject booleans before Python can equate them with integer IDs."""
    result = set()
    for row_id in values:
        _check_deadline(deadline, stage)
        if type(row_id) is not int or not 0 <= row_id < len(graph.coordinates):
            raise ValueError('Unknown or invalid row ID')
        result.add(row_id)
    return frozenset(result)


def deletion_closure(graph: FKGraph, alive: Iterable[int], seeds: Iterable[int], *,
                     deadline: float = float('inf')) -> frozenset[int]:
    """Return the least live parent-to-child deletion closure, iteratively."""
    _check_deadline(deadline, 'closure')
    live = _validated_ids(graph, alive, deadline=deadline, stage='closure')
    seed_ids = _validated_ids(graph, seeds, deadline=deadline, stage='closure')
    if not seed_ids <= live:
        raise ValueError('Deletion seeds must be live row IDs')
    answer = set(seed_ids)
    stack = sorted(seed_ids, reverse=True)
    edge_count = 0
    while stack:
        _check_deadline(deadline, 'closure')
        parent = stack.pop()
        for child in graph.adjacency[parent]:
            if child in live and child not in answer:
                answer.add(child)
                stack.append(child)
            edge_count += 1
            if edge_count % 256 == 0:
                _check_deadline(deadline, 'closure')
    result = frozenset(answer)
    _check_deadline(deadline, 'closure')
    return result


def materialize(graph: FKGraph, alive: Iterable[int], *,
                deadline: float = float('inf')) -> dict[str, list[list]]:
    """Copy live rows in original order, retaining every declared table."""
    _check_deadline(deadline, 'materialize')
    live = _validated_ids(graph, alive, deadline=deadline, stage='materialize')
    result = {name: [] for name in graph.tables}
    for row_id, (name, _) in enumerate(graph.coordinates):
        _check_deadline(deadline, 'materialize')
        if row_id in live:
            result[name].append(list(graph.rows[row_id]))
    _check_deadline(deadline, 'materialize')
    return result

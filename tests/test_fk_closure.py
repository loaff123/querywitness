"""Production FK closures compared to an independent exhaustive SQLite oracle."""

from dataclasses import FrozenInstanceError, replace
import math
import sqlite3
import unittest
from unittest.mock import patch

import fk_oracle
from querywitness.schema import Schema, SchemaError

from querywitness import fk_graph


def fixture_schema(fixture):
    """Adapt hand-authored DDL, without changing the oracle or using its graph."""
    db = sqlite3.connect(":memory:")
    try:
        for ddl in fixture.ddl:
            db.execute(ddl)
        columns = {
            name: db.execute(f'PRAGMA table_info("{name}")').fetchall()
            for name in fixture.rows
        }
        tables = []
        for name in sorted(fixture.rows):
            info = columns[name]
            unique = []
            for index in db.execute(f'PRAGMA index_list("{name}")').fetchall():
                if index[2] and index[3] != "pk":
                    unique.append(
                        [
                            row[2]
                            for row in db.execute(
                                f'PRAGMA index_info("{index[1]}")'
                            ).fetchall()
                        ]
                    )
            tables.append(
                {
                    "name": name,
                    "columns": [
                        {"name": c[1], "type": c[2], "nullable": not bool(c[3])}
                        for c in info
                    ],
                    "primary_key": [
                        c[1] for c in sorted(info, key=lambda c: c[5]) if c[5]
                    ],
                    "unique": unique,
                    "foreign_keys": [
                        {
                            "columns": [info[i][1] for i in fk.local],
                            "references": {
                                "table": fk.parent,
                                "columns": [
                                    columns[fk.parent][i][1] for i in fk.target
                                ],
                            },
                        }
                        for fk in fixture.fks
                        if fk.child == name
                    ],
                }
            )
        return Schema.from_dict({"tables": tables})
    finally:
        db.close()


def fixture_named(name):
    return next(f for f in fk_oracle.fixtures() if f.name == name)


def self_schema():
    return Schema.from_dict(
        {
            "tables": [
                {
                    "name": "t",
                    "columns": [
                        {"name": "id", "type": "INTEGER"},
                        {"name": "parent", "type": "INTEGER"},
                    ],
                    "primary_key": ["id"],
                    "foreign_keys": [
                        {
                            "columns": ["parent"],
                            "references": {"table": "t", "columns": ["id"]},
                        }
                    ],
                }
            ]
        }
    )


class FKGraphTests(unittest.TestCase):
    def test_all_96_fixtures_match_least_sqlite_valid_deletion(self):
        """Fails for reversed edges, lost occurrences, spurious NULL edges, or nonleast closure."""
        fixtures = list(fk_oracle.fixtures())
        self.assertEqual(len(fixtures), 96)
        seed_checks = containment_checks = state_root_checks = 0
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                graph = fk_graph.build_fk_graph(fixture_schema(fixture), fixture.rows)
                coordinates = tuple(fixture.ids())
                self.assertEqual(graph.coordinates, coordinates)
                dense = {
                    coordinate: index for index, coordinate in enumerate(coordinates)
                }
                universe = frozenset(range(len(coordinates)))
                choices = fk_oracle.subsets(coordinates)
                valid_deletions = [
                    removed for removed in choices if fk_oracle.valid(fixture, removed)
                ]
                self.assertIn(frozenset(), valid_deletions)
                for seeds in choices:
                    valid_supersets = [
                        removed for removed in valid_deletions if seeds <= removed
                    ]
                    least = frozenset.intersection(*valid_supersets)
                    result = fk_graph.deletion_closure(
                        graph, universe, frozenset(dense[seed] for seed in seeds)
                    )
                    got = frozenset(coordinates[row] for row in result)
                    self.assertEqual(got, least)
                    self.assertLessEqual(seeds, got)
                    self.assertIn(got, valid_deletions)
                    self.assertEqual(
                        fk_graph.deletion_closure(graph, universe, result), result
                    )
                    self.assertEqual(
                        fk_graph.materialize(graph, universe - result),
                        {
                            table: [
                                list(row)
                                for index, row in enumerate(fixture.rows[table])
                                if (table, index) not in got
                            ]
                            for table in sorted(fixture.rows)
                        },
                    )
                    for removed in valid_supersets:
                        self.assertLessEqual(got, removed)
                        containment_checks += 1
                    seed_checks += 1
                for prior in valid_deletions:
                    live_coordinates = frozenset(coordinates) - prior
                    alive = frozenset(dense[row] for row in live_coordinates)
                    for root in live_coordinates:
                        eligible = [
                            removed
                            for removed in valid_deletions
                            if prior | {root} <= removed
                        ]
                        least = frozenset.intersection(*eligible) - prior
                        result = fk_graph.deletion_closure(graph, alive, {dense[root]})
                        self.assertEqual(
                            frozenset(coordinates[row] for row in result), least
                        )
                        state_root_checks += 1
        self.assertEqual(
            (seed_checks, containment_checks, state_root_checks), (1421, 7730, 1806)
        )

    def test_graph_is_deterministic_sorted_and_preserves_duplicate_occurrences(self):
        fixture = fixture_named("duplicate_fk_declarations")
        schema = fixture_schema(fixture)
        graph = fk_graph.build_fk_graph(schema, fixture.rows)
        reverse_schema = Schema.from_dict(
            {"tables": list(reversed(schema.to_dict()["tables"]))}
        )
        reordered = fk_graph.build_fk_graph(
            reverse_schema, dict(reversed(list(fixture.rows.items())))
        )
        self.assertEqual(graph, reordered)
        self.assertEqual(graph.coordinates, (("c", 0), ("c", 1), ("p", 0)))
        self.assertEqual(graph.adjacency, ((), (), (0, 1)))
        self.assertEqual(graph.tables, ("c", "p"))
        self.assertEqual(graph.rows, ((1,), (1,), (1,)))

    def test_graph_and_materialized_proposals_do_not_alias_input_or_each_other(self):
        fixture = fixture_named("duplicate_bag_no_fk")
        source = {"t": [[1], [1], [None]]}
        graph = fk_graph.build_fk_graph(fixture_schema(fixture), source)
        alive = frozenset(range(3))
        source["t"][0][0] = 999
        source["t"].append([2])
        proposal = fk_graph.materialize(graph, alive)
        self.assertEqual(proposal, {"t": [[1], [1], [None]]})
        proposal["t"][0][0] = 888
        proposal["t"].pop()
        self.assertEqual(fk_graph.materialize(graph, alive), {"t": [[1], [1], [None]]})
        self.assertEqual(fk_graph.materialize(graph, {1, 2}), {"t": [[1], [None]]})
        with self.assertRaises(FrozenInstanceError):
            graph.rows = ()
        with self.assertRaises(TypeError):
            graph.rows[0][0] = 0

    def test_empty_graph_keeps_declared_empty_tables(self):
        fixture = fixture_named("minimal_parent_child")
        graph = fk_graph.build_fk_graph(fixture_schema(fixture), {"p": [], "c": []})
        self.assertEqual(graph.coordinates, ())
        self.assertEqual(graph.adjacency, ())
        self.assertEqual(fk_graph.deletion_closure(graph, set(), set()), frozenset())
        self.assertEqual(fk_graph.materialize(graph, set()), {"c": [], "p": []})

    def test_rejects_missing_and_ambiguous_nonnull_parents(self):
        fixture = fixture_named("minimal_parent_child")
        schema = fixture_schema(fixture)
        for source in ({"p": [], "c": [[1]]}, {"p": [[1], [1]], "c": [[1]]}):
            with self.subTest(source=source), self.assertRaises(SchemaError):
                fk_graph.build_fk_graph(schema, source)

    def test_full_instance_contract_is_validated(self):
        fixture = fixture_named("minimal_parent_child")
        schema = fixture_schema(fixture)
        invalid = [
            None,
            {},
            {"p": [], "c": [], "extra": []},
            {"p": (), "c": []},
            {"p": [[None]], "c": []},
            {"p": [[True]], "c": []},
            {"p": [["1"]], "c": []},
            {"p": [[1, 2]], "c": []},
            {"p": [[1]], "c": [[math.inf]]},
        ]
        for source in invalid:
            with self.subTest(source=source), self.assertRaises(SchemaError):
                fk_graph.build_fk_graph(schema, source)
        bounded = Schema.from_dict(
            {
                "tables": [
                    {
                        "name": "t",
                        "columns": [{"name": "x", "type": "INTEGER", "domain": [1]}],
                    }
                ]
            }
        )
        with self.assertRaises(SchemaError):
            fk_graph.build_fk_graph(bounded, {"t": [[2]]})
        with self.assertRaises(SchemaError):
            fk_graph.build_fk_graph(bounded, {"t": [[1]] * 2001})

    def test_real_boundary_keys_match_sqlite_without_rounding_distinct_keys(self):
        fixture = fk_oracle.Fixture(
            "real_boundaries",
            (
                "CREATE TABLE p(k REAL NOT NULL UNIQUE)",
                "CREATE TABLE c(k REAL, FOREIGN KEY(k) REFERENCES p(k)"
                + fk_oracle.DEFER
                + ")",
            ),
            {
                "p": [(2**53,), (-(2**53),), (math.nextafter(1.0, 2.0),), (1e100,)],
                "c": [
                    (float(2**53),),
                    (-float(2**53),),
                    (math.nextafter(1.0, 2.0),),
                    (1e100,),
                ],
            },
            (fk_oracle.FK("c", (0,), "p", (0,)),),
        )
        graph = fk_graph.build_fk_graph(fixture_schema(fixture), fixture.rows)
        self.assertTrue(fk_oracle.valid(fixture, frozenset()))
        for parent in range(4, 8):
            got = fk_graph.deletion_closure(graph, frozenset(range(8)), {parent})
            self.assertEqual(got, frozenset({parent, parent - 4}))
            self.assertTrue(
                fk_oracle.valid(fixture, {graph.coordinates[row] for row in got})
            )
        for bad in (2**53 + 1, -(2**53) - 1, math.nan, math.inf, True):
            with self.subTest(value=bad), self.assertRaises(SchemaError):
                fk_graph.build_fk_graph(
                    fixture_schema(fixture), {"p": [[bad]], "c": []}
                )

    def test_rejects_unknown_or_boolean_alive_and_seed_ids(self):
        fixture = fixture_named("minimal_parent_child")
        graph = fk_graph.build_fk_graph(fixture_schema(fixture), fixture.rows)
        for invalid in (-1, 2, True, False, 1.0, "1", None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    fk_graph.deletion_closure(graph, {0, 1}, [invalid])
                with self.assertRaises(ValueError):
                    fk_graph.deletion_closure(graph, [invalid], [])
                with self.assertRaises(ValueError):
                    fk_graph.materialize(graph, [invalid])
        with self.assertRaises(ValueError):
            fk_graph.deletion_closure(graph, {0}, {1})

    def test_maximum_depth_chain_is_iterative_and_reuses_live_graph(self):
        data = {"t": [[i, None if i == 0 else i - 1] for i in range(2000)]}
        graph = fk_graph.build_fk_graph(self_schema(), data)
        universe = frozenset(range(2000))
        self.assertEqual(fk_graph.deletion_closure(graph, universe, {0}), universe)
        removed = fk_graph.deletion_closure(graph, universe, {1990})
        self.assertEqual(removed, frozenset(range(1990, 2000)))
        alive = universe - removed
        self.assertEqual(
            fk_graph.deletion_closure(graph, alive, {1989}), frozenset({1989})
        )
        self.assertEqual(fk_graph.materialize(graph, alive), {"t": data["t"][:1990]})

    def test_deadline_exception_carries_stage(self):
        error = fk_graph.ClosureDeadlineExceeded("test_stage")
        self.assertEqual(error.stage, "test_stage")
        self.assertIn("test_stage", str(error))

    def test_expired_deadlines_fail_even_for_empty_phases(self):
        fixture = fixture_named("minimal_parent_child")
        schema = fixture_schema(fixture)
        graph = fk_graph.build_fk_graph(schema, {"c": [], "p": []})
        with patch("querywitness.fk_graph.time.monotonic", return_value=1.0):
            for operation in (
                lambda: fk_graph.build_fk_graph(
                    schema, {"c": [], "p": []}, deadline=1.0
                ),
                lambda: fk_graph.deletion_closure(graph, set(), set(), deadline=1.0),
                lambda: fk_graph.materialize(graph, set(), deadline=1.0),
            ):
                with (
                    self.subTest(operation=operation),
                    self.assertRaises(fk_graph.ClosureDeadlineExceeded),
                ):
                    operation()

    def test_graph_deadline_interrupts_each_phase_with_an_injected_clock(self):
        fixture = fixture_named("branching_chain_duplicate_children")
        schema = fixture_schema(fixture)
        # Let one additional monotonic checkpoint pass in each trial. This must
        # reach every phase, and must not return a partially built graph.
        stages = set()
        completed = False
        for cutoff in range(500):
            clock = iter(range(1000))
            with patch(
                "querywitness.fk_graph.time.monotonic", side_effect=lambda: next(clock)
            ):
                try:
                    graph = fk_graph.build_fk_graph(
                        schema, fixture.rows, deadline=cutoff
                    )
                except fk_graph.ClosureDeadlineExceeded as error:
                    stages.add(error.stage)
                else:
                    self.assertEqual(len(graph.coordinates), 7)
                    completed = True
                    break
        self.assertTrue(completed)
        self.assertEqual(
            stages, {"graph_validation", "graph_copy", "graph_index", "graph_edges"}
        )

    def test_deadline_checked_after_existing_schema_validation(self):
        fixture = fixture_named("minimal_parent_child")
        schema = fixture_schema(fixture)
        real_validate = Schema.validate_instance
        clock = [0.0]

        def slow_validation(obj, data):
            real_validate(obj, data)
            clock[0] = 2.0

        with (
            patch("querywitness.fk_graph.time.monotonic", side_effect=lambda: clock[0]),
            patch.object(Schema, "validate_instance", new=slow_validation),
        ):
            with self.assertRaises(fk_graph.ClosureDeadlineExceeded) as raised:
                fk_graph.build_fk_graph(schema, fixture.rows, deadline=1.0)
        self.assertEqual(raised.exception.stage, "graph_validation")

    def test_long_closure_and_materialization_obey_internal_deadline_checks(self):
        data = {"t": [[i, None if i == 0 else i - 1] for i in range(2000)]}
        graph = fk_graph.build_fk_graph(self_schema(), data)
        universe = frozenset(range(2000))
        for name, operation in (
            (
                "closure",
                lambda: fk_graph.deletion_closure(graph, universe, {0}, deadline=2500),
            ),
            (
                "materialize",
                lambda: fk_graph.materialize(graph, universe, deadline=2500),
            ),
        ):
            clock = iter(range(10000))
            with (
                self.subTest(phase=name),
                patch(
                    "querywitness.fk_graph.time.monotonic",
                    side_effect=lambda: next(clock),
                ),
                self.assertRaises(fk_graph.ClosureDeadlineExceeded) as raised,
            ):
                operation()
            self.assertEqual(raised.exception.stage, name)

    def test_closure_checks_deadline_within_high_fanout_row(self):
        data = {"t": [[i, None if i == 0 else 0] for i in range(600)]}
        graph = fk_graph.build_fk_graph(self_schema(), data)
        visited_edges = [0]

        class CountedChildren(tuple):
            def __iter__(self):
                for child in super().__iter__():
                    visited_edges[0] += 1
                    yield child

        graph = replace(
            graph, adjacency=(CountedChildren(graph.adjacency[0]), *graph.adjacency[1:])
        )
        with patch(
            "querywitness.fk_graph.time.monotonic", side_effect=lambda: visited_edges[0]
        ):
            with self.assertRaises(fk_graph.ClosureDeadlineExceeded) as raised:
                fk_graph.deletion_closure(
                    graph, frozenset(range(600)), {0}, deadline=256
                )
        self.assertEqual(raised.exception.stage, "closure")
        self.assertEqual(visited_edges[0], 256)

    def test_graph_module_has_no_nonstandard_dependency_import(self):
        # Schema itself is standard-library-only. Importing the graph must not
        # import SQLite execution, SQLGlot, reduction, or artifact machinery.
        import ast
        from pathlib import Path

        tree = ast.parse(Path(fk_graph.__file__).read_text())
        modules = {
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        modules |= {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertTrue(
            modules
            <= {
                "__future__",
                "dataclasses",
                "typing",
                "time",
                "schema",
                "collections.abc",
            }
        )


if __name__ == "__main__":
    unittest.main()

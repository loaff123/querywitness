"""Independent, authored design experiment; imports no QueryWitness code.

SQLite builds every retained subset from hand-authored DDL. Graph closure is
checked against *all* schema-valid deletion supersets, not against another
graph traversal. This is bounded exhaustive testing, not a general proof.
"""
from dataclasses import dataclass
from itertools import product
import json
import sqlite3
import sys


@dataclass(frozen=True)
class FK:
    child: str
    local: tuple[int, ...]
    parent: str
    target: tuple[int, ...]


@dataclass
class Fixture:
    name: str
    ddl: tuple[str, ...]
    rows: dict[str, list[tuple]]
    fks: tuple[FK, ...] = ()

    def ids(self):
        return [(t, i) for t in sorted(self.rows) for i in range(len(self.rows[t]))]


def database(fixture, removed):
    db = sqlite3.connect(':memory:')
    db.execute('PRAGMA foreign_keys=ON')
    try:
        for statement in fixture.ddl:
            db.execute(statement)
        db.execute('BEGIN')
        for t in sorted(fixture.rows):
            for i, row in enumerate(fixture.rows[t]):
                if (t, i) not in removed:
                    db.execute(f'INSERT INTO "{t}" VALUES ({",".join("?" for _ in row)})', row)
        # Both checks are independent of the graph model. Deferred constraints
        # permit arbitrary load order, including self references and cycles.
        if db.execute('PRAGMA foreign_key_check').fetchall():
            db.close()
            return None
        db.commit()
        return db
    except sqlite3.IntegrityError:
        db.close()
        return None


def valid(fixture, removed):
    db = database(fixture, removed)
    if db is None:
        return False
    db.close()
    return True


def adjacency(fixture):
    edges = {ident: set() for ident in fixture.ids()}
    for fk in fixture.fks:
        for ci, child in enumerate(fixture.rows[fk.child]):
            key = tuple(child[i] for i in fk.local)
            if any(v is None for v in key):
                continue
            matches = [pi for pi, parent in enumerate(fixture.rows[fk.parent])
                       if tuple(parent[i] for i in fk.target) == key]
            assert len(matches) == 1, (fixture.name, fk, key, matches)
            edges[(fk.parent, matches[0])].add((fk.child, ci))
    return {k: tuple(sorted(v)) for k, v in edges.items()}


def closure(edges, seeds, alive=None):
    alive = set(edges) if alive is None else set(alive)
    answer = set(seeds)
    assert answer <= alive
    stack = sorted(answer, reverse=True)
    while stack:
        node = stack.pop()
        for child in edges[node]:
            if child in alive and child not in answer:
                answer.add(child)
                stack.append(child)
    return frozenset(answer)


def subsets(ids):
    return [frozenset(x for i, x in enumerate(ids) if mask >> i & 1)
            for mask in range(1 << len(ids))]


def exhaustive(fixture):
    ids = fixture.ids()
    assert len(ids) <= 8
    candidates = subsets(ids)
    valid_deletions = [d for d in candidates if valid(fixture, d)]
    assert frozenset() in valid_deletions, fixture.name
    graph = adjacency(fixture)
    containment_checks = 0
    state_root_checks = 0
    for seeds in candidates:
        supersets = [d for d in valid_deletions if seeds <= d]
        # Oracle: all valid deletion supersets, computed solely by SQLite.
        least = frozenset.intersection(*supersets)
        assert least in valid_deletions, (fixture.name, seeds, 'no least')
        got = closure(graph, seeds)
        assert got == least, (fixture.name, seeds, got, least)
        assert closure(graph, got) == got
        assert seeds <= got
        for d in supersets:
            assert got <= d
            containment_checks += 1
    # Reusing the original graph after accepted deletions must agree with the
    # independently enumerated valid subinstances of each remaining state.
    for prior in valid_deletions:
        alive = frozenset(ids) - prior
        for root in alive:
            eligible = [d for d in valid_deletions if prior | {root} <= d]
            least = frozenset.intersection(*eligible) - prior
            assert closure(graph, {root}, alive) == least
            state_root_checks += 1
    return dict(name=fixture.name, rows=len(ids), retained_subsets=len(candidates),
                valid_subsets=len(valid_deletions), all_seed_sets=len(candidates),
                least_containment_checks=containment_checks,
                surviving_state_root_checks=state_root_checks)


DEFER = ' DEFERRABLE INITIALLY DEFERRED'
PC = ('CREATE TABLE p(id INTEGER NOT NULL PRIMARY KEY)',
      'CREATE TABLE c(pid INTEGER, FOREIGN KEY(pid) REFERENCES p(id)' + DEFER + ')')


def fixtures():
    yield Fixture('duplicate_bag_no_fk', ('CREATE TABLE t(x INTEGER)',), {'t': [(1,), (1,), (None,)]})
    yield Fixture('minimal_parent_child', PC, {'p': [(1,)], 'c': [(1,)]}, (FK('c', (0,), 'p', (0,)),))
    yield Fixture('nullable_values_not_nullable_flags', PC, {'p': [(1,)], 'c': [(1,), (None,), (None,)]}, (FK('c', (0,), 'p', (0,)),))
    yield Fixture('composite_partial_null_and_duplicate_null_unique',
                  ('CREATE TABLE p(a INTEGER, b INTEGER, UNIQUE(a,b))',
                   'CREATE TABLE c(x INTEGER, y INTEGER, FOREIGN KEY(x,y) REFERENCES p(a,b)' + DEFER + ')'),
                  {'p': [(1, 2), (None, 2), (None, 2)],
                   'c': [(1, 2), (None, 2), (1, None), (None, None)]},
                  (FK('c', (0, 1), 'p', (0, 1)),))
    yield Fixture('ordered_composite_columns',
                  ('CREATE TABLE p(a INTEGER NOT NULL, b INTEGER NOT NULL, PRIMARY KEY(a,b))',
                   'CREATE TABLE c(x INTEGER, y INTEGER, FOREIGN KEY(y,x) REFERENCES p(a,b)' + DEFER + ')'),
                  {'p': [(1, 2), (2, 1)], 'c': [(2, 1), (1, 2)]},
                  (FK('c', (1, 0), 'p', (0, 1)),))
    yield Fixture('branching_chain_duplicate_children',
                  ('CREATE TABLE p(id INTEGER NOT NULL PRIMARY KEY)',
                   'CREATE TABLE c(id INTEGER NOT NULL PRIMARY KEY, pid INTEGER, FOREIGN KEY(pid) REFERENCES p(id)' + DEFER + ')',
                   'CREATE TABLE d(cid INTEGER, FOREIGN KEY(cid) REFERENCES c(id)' + DEFER + ')'),
                  {'p': [(1,), (2,)], 'c': [(11, 1), (12, 1), (21, 2)], 'd': [(11,), (11,)]},
                  (FK('c', (1,), 'p', (0,)), FK('d', (0,), 'c', (0,))))
    yield Fixture('multiple_parents',
                  ('CREATE TABLE p(id INTEGER NOT NULL PRIMARY KEY)',
                   'CREATE TABLE q(id INTEGER NOT NULL PRIMARY KEY)',
                   'CREATE TABLE c(a INTEGER, b INTEGER, FOREIGN KEY(a) REFERENCES p(id)' + DEFER + ', FOREIGN KEY(b) REFERENCES q(id)' + DEFER + ')'),
                  {'p': [(1,)], 'q': [(2,)], 'c': [(1, 2), (None, 2)]},
                  (FK('c', (0,), 'p', (0,)), FK('c', (1,), 'q', (0,))))
    yield Fixture('duplicate_fk_declarations',
                  ('CREATE TABLE p(id INTEGER NOT NULL PRIMARY KEY)',
                   'CREATE TABLE c(pid INTEGER, FOREIGN KEY(pid) REFERENCES p(id)' + DEFER + ', FOREIGN KEY(pid) REFERENCES p(id)' + DEFER + ')'),
                  {'p': [(1,)], 'c': [(1,), (1,)]},
                  (FK('c', (0,), 'p', (0,)), FK('c', (0,), 'p', (0,))))
    yield Fixture('two_table_cycle',
                  ('CREATE TABLE a(id INTEGER NOT NULL PRIMARY KEY, bid INTEGER, FOREIGN KEY(bid) REFERENCES b(id)' + DEFER + ')',
                   'CREATE TABLE b(id INTEGER NOT NULL PRIMARY KEY, aid INTEGER, FOREIGN KEY(aid) REFERENCES a(id)' + DEFER + ')'),
                  {'a': [(1, 1), (2, 2)], 'b': [(1, 1), (2, 2)]},
                  (FK('a', (1,), 'b', (0,)), FK('b', (1,), 'a', (0,))))
    yield Fixture('real_numeric_equivalence_and_signed_zero',
                  ('CREATE TABLE p(k REAL NOT NULL UNIQUE)',
                   'CREATE TABLE c(k REAL, FOREIGN KEY(k) REFERENCES p(k)' + DEFER + ')'),
                  {'p': [(1,), (-0.0,), (2**53,)], 'c': [(1.0,), (0,), (float(2**53),), (None,)]},
                  (FK('c', (0,), 'p', (0,)),))
    yield Fixture('binary_text_exactness',
                  ('CREATE TABLE p(k TEXT NOT NULL UNIQUE)',
                   'CREATE TABLE c(k TEXT, FOREIGN KEY(k) REFERENCES p(k)' + DEFER + ')'),
                  {'p': [('a',), ('A',), ('é',), ('e\u0301',)], 'c': [('a',), ('A',), ('é',), ('e\u0301',)]},
                  (FK('c', (0,), 'p', (0,)),))
    # Exhaust every pointer assignment for up to three distinct self rows.
    for n in range(4):
        for pointer in product((None, *range(1, n + 1)), repeat=n):
            yield Fixture('self_' + str(n) + '_' + '_'.join(map(str, pointer)),
                          ('CREATE TABLE t(id INTEGER NOT NULL PRIMARY KEY, parent INTEGER, FOREIGN KEY(parent) REFERENCES t(id)' + DEFER + ')',),
                          {'t': [(i + 1, pointer[i]) for i in range(n)]},
                          (FK('t', (1,), 't', (0,)),))
    # Every two-child assignment over two parents, including duplicated refs.
    for values in product((None, 1, 2), repeat=2):
        yield Fixture('two_child_' + '_'.join(map(str, values)), PC,
                      {'p': [(1,), (2,)], 'c': [(v,) for v in values]},
                      (FK('c', (0,), 'p', (0,)),))


def pair_results(fixture, removed, left, right):
    db = database(fixture, removed)
    if db is None:
        return None
    try:
        return db.execute(left).fetchall(), db.execute(right).fetchall()
    finally:
        db.close()


def semantic_regressions():
    f = next(x for x in fixtures() if x.name == 'minimal_parent_child')
    left, right = 'SELECT COUNT(*) FROM p', 'SELECT COUNT(*)+1 FROM c'
    assert pair_results(f, set(), left, right) == ([(1,)], [(2,)])
    assert pair_results(f, {('p', 0)}, left, right) is None
    assert pair_results(f, {('c', 0)}, left, right) == ([(1,)], [(1,)])
    assert pair_results(f, set(f.ids()), left, right) == ([(0,)], [(1,)])
    # Closure-1-minimality is still not global optimality: two independent
    # row removals are jointly useful but neither alone preserves mismatch.
    f = Fixture('nonmonotone_no_fk', ('CREATE TABLE t(x INTEGER)',), {'t': [(1,), (2,)]})
    left = 'SELECT COUNT(*) FROM t'
    right = 'SELECT CASE WHEN COUNT(*)=1 THEN 1 ELSE COUNT(*)+1 END FROM t'
    assert pair_results(f, set(), left, right) == ([(2,)], [(3,)])
    for ident in f.ids():
        assert pair_results(f, {ident}, left, right) == ([(1,)], [(1,)])
    assert pair_results(f, set(f.ids()), left, right) == ([(0,)], [(1,)])
    return {'motivating_case': 'verified', 'closure_minimal_not_global': 'verified'}


def mutation_sensitivity():
    def agrees_with_oracle(f, graph):
        choices = subsets(f.ids())
        good = [d for d in choices if valid(f, d)]
        for seeds in choices:
            least = frozenset.intersection(*(d for d in good if seeds <= d))
            if closure(graph, seeds) != least:
                return False
        return True

    f = next(x for x in fixtures() if x.name == 'duplicate_fk_declarations')
    graph = adjacency(f)
    reverse = {x: [] for x in graph}
    for parent, children in graph.items():
        for child in children:
            reverse[child].append(parent)
    assert not agrees_with_oracle(f, reverse)
    dropped_duplicate = dict(graph)
    dropped_duplicate[('p', 0)] = (('c', 0),)
    assert not agrees_with_oracle(f, dropped_duplicate)
    f = next(x for x in fixtures() if x.name == 'composite_partial_null_and_duplicate_null_unique')
    spurious_null_dependency = dict(adjacency(f))
    spurious_null_dependency[('p', 1)] = (('c', 1),)
    assert not agrees_with_oracle(f, spurious_null_dependency)
    return {'reversed_dependency_edges': 'detected',
            'lost_duplicate_child': 'detected',
            'spurious_nullable_dependency': 'detected'}


def main():
    results = [exhaustive(f) for f in fixtures()]
    counts = {k: sum(r[k] for r in results) for k in results[0] if k not in ('name', 'rows')}
    report = {'experiment': 'independently authored exhaustive SQLite subset oracle',
              'repository_code_executed': False, 'sqlite_version': sqlite3.sqlite_version,
              'python_version': sys.version.split()[0], 'fixture_count': len(results),
              'maximum_rows': max(r['rows'] for r in results), 'counts': counts,
              'semantic_regressions': semantic_regressions(),
              'mutation_sensitivity': mutation_sensitivity(), 'fixtures': results}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

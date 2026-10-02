"""Behavior and accounting regressions for opt-in least-FK-closure deletion."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from querywitness.schema import Schema, SchemaError
from querywitness.reduce import minimize
from querywitness.engine import ExecutionLimits, QueryResult, execute


def plain():
    return Schema.from_dict({'tables': [{'name': 't', 'columns': [{'name': 'x', 'type': 'INTEGER'}]}]})


def parent_child():
    return Schema.from_dict({'tables': [
        {'name': 'p', 'columns': [{'name': 'id', 'type': 'INTEGER'}], 'primary_key': ['id']},
        {'name': 'c', 'columns': [{'name': 'pid', 'type': 'INTEGER'}],
         'foreign_keys': [{'columns': ['pid'], 'references': {'table': 'p', 'columns': ['id']}}]}]})


class FKReductionTests(unittest.TestCase):
    def reduce(self, schema, data, left='SELECT COUNT(*) FROM t', right='SELECT COUNT(*)+1 FROM t', **kw):
        return minimize(schema, data, left, right, deletion_mode='fk-closure', **kw)

    def test_parent_child_opt_in_strictly_shrinks_default_fixed_point(self):
        s, d = parent_child(), {'p': [[1]], 'c': [[1]]}
        queries = ('SELECT COUNT(*) FROM p', 'SELECT COUNT(*)+1 FROM c')
        old = minimize(s, d, *queries)
        self.assertEqual(old['instance'], d)
        self.assertTrue(old['row_1_minimal'])
        result = self.reduce(s, d, *queries)
        self.assertEqual(result['instance'], {'c': [], 'p': []})
        self.assertTrue(result['fk_closure_1_minimal'])
        self.assertTrue(result['row_1_minimal'])
        self.assertTrue(result['witness_reproduced'])
        self.assertEqual(result['query_executions'], 2 * result['checks'])
        self.assertEqual(d, {'p': [[1]], 'c': [[1]]})

    def test_unknown_mode_rejected_and_row_mode_unchanged(self):
        s, d = plain(), {'t': [[1], [1]]}
        with self.assertRaises(ValueError):
            minimize(s, d, 'SELECT x FROM t', 'SELECT DISTINCT x FROM t', deletion_mode='cascade')
        self.assertEqual(minimize(s, d, 'SELECT x FROM t', 'SELECT DISTINCT x FROM t'),
                         minimize(s, d, 'SELECT x FROM t', 'SELECT DISTINCT x FROM t', deletion_mode='row'))

    def test_nonmonotone_singleton_fixed_point_is_not_global_minimum(self):
        right = 'SELECT CASE WHEN COUNT(*)=1 THEN 1 ELSE COUNT(*)+1 END FROM t'
        r = self.reduce(plain(), {'t': [[1], [2]]}, right=right)
        self.assertEqual(r['instance'], {'t': [[1], [2]]})
        self.assertTrue(r['fk_closure_1_minimal'])
        self.assertEqual(r['final_scan_roots_checked'], 2)
        self.assertEqual(execute(plain(), {'t': []}, right).rows, ((1,),))

    def test_nonmonotone_restart_enables_earlier_failed_root(self):
        # Deleting late-table c during chunks enables b; b then enables a.
        # The final scan must restart at a after accepting b.
        s = Schema.from_dict({'tables': [
            {'name': name, 'columns': [{'name': 'x', 'type': 'INTEGER'}]}
            for name in ('a', 'b', 'c')]})
        d = {'a': [[1]], 'b': [[2]], 'c': [[3]]}
        seen = []
        def run(schema, data, sql, limits, *, policy):
            values = tuple(name for name in sorted(data) if data[name])
            if sql == 'right': seen.append(values)
            mismatch = values in (('a', 'b', 'c'), ('a', 'b'), ('a',), ())
            return QueryResult('ok', ('x',), ((int(sql == 'right' and mismatch),),))
        with patch('querywitness.fk_closure.execute', side_effect=run):
            r = self.reduce(s, d, 'left', 'right')
        self.assertEqual(r['instance'], {'a': [], 'b': [], 'c': []})
        self.assertTrue(r['fk_closure_1_minimal'])
        self.assertEqual(seen, [('a', 'b', 'c'), ('b', 'c'), ('a', 'c'),
                                ('a', 'b'), ('b',), ('a',), ()])

    def test_duplicate_occurrences_bag_and_set_policy(self):
        s, d = plain(), {'t': [[1], [1], [2]]}
        bag = self.reduce(s, d, 'SELECT x FROM t', 'SELECT DISTINCT x FROM t')
        self.assertEqual(bag['instance'], {'t': [[1], [1]]})
        self.assertTrue(bag['fk_closure_1_minimal'])
        aset = self.reduce(s, d, 'SELECT x FROM t', 'SELECT DISTINCT x FROM t', policy='set')
        self.assertEqual(aset['status'], 'not_a_witness')
        self.assertFalse(aset['witness_reproduced'])

    def test_actual_null_child_survives_parent_deletion(self):
        s, d = parent_child(), {'p': [[1]], 'c': [[1], [None]]}
        r = self.reduce(s, d, 'SELECT pid FROM c WHERE pid IS NULL', 'SELECT pid FROM c WHERE 0')
        self.assertEqual(r['instance'], {'c': [[None]], 'p': []})
        self.assertTrue(r['fk_closure_1_minimal'])

    def test_ordered_policy_and_limits_forwarded(self):
        s, d = plain(), {'t': [[1], [2]]}
        limits = ExecutionLimits(rows=7)
        calls = []
        def recording(*args, **kwargs):
            calls.append((args[3], kwargs['policy']))
            return execute(*args, **kwargs)
        with patch('querywitness.fk_closure.execute', side_effect=recording):
            r = self.reduce(s, d, 'SELECT x FROM t ORDER BY x', 'SELECT x FROM t ORDER BY x DESC',
                            policy='ordered', limits=limits)
        self.assertTrue(r['fk_closure_1_minimal'])
        self.assertTrue(all(pair == (limits, 'ordered') for pair in calls))

    def test_no_hidden_final_query_pair(self):
        calls = []
        def run(*args, **kwargs):
            calls.append(args[2]); return execute(*args, **kwargs)
        with patch('querywitness.fk_closure.execute', side_effect=run):
            r = self.reduce(plain(), {'t': [[1]]}, max_checks=2)
        self.assertEqual(r['instance'], {'t': []})
        self.assertTrue(r['fk_closure_1_minimal'])
        self.assertEqual(r['checks'], 2)
        self.assertEqual(r['query_executions'], 4)
        self.assertEqual(len(calls), 4)

    def test_one_check_certifies_empty_but_not_nonempty(self):
        for data, minimal in [({'t': []}, True), ({'t': [[1]]}, False)]:
            r = self.reduce(plain(), data, max_checks=1)
            self.assertEqual(r['fk_closure_1_minimal'], minimal)
            self.assertEqual(r['checks'], 1)
            self.assertEqual(r['query_executions'], 2)
            self.assertTrue(r['witness_reproduced'])
            if not minimal: self.assertEqual(r['status'], 'budget_exhausted')

    def test_initial_inconclusive_is_not_agreement(self):
        r = self.reduce(plain(), {'t': [[1]]}, right='SELECT missing FROM t')
        self.assertEqual(r['status'], 'initial_check_inconclusive')
        self.assertFalse(r['witness_reproduced'])
        self.assertFalse(r['fk_closure_1_minimal'])
        self.assertEqual(r['inconclusive_checks'], 1)

    def test_any_inconclusive_candidate_prevents_claim_even_after_shrink(self):
        calls = 0
        def run(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3: return QueryResult('resource_limit')
            return execute(*args, **kwargs)
        with patch('querywitness.fk_closure.execute', side_effect=run):
            r = self.reduce(plain(), {'t': [[1], [2]]})
        self.assertEqual(r['instance'], {'t': []})
        self.assertEqual(r['status'], 'inconclusive_reduction')
        self.assertTrue(r['final_scan_complete'])
        self.assertFalse(r['fk_closure_1_minimal'])
        self.assertEqual(r['inconclusive_checks'], 1)

    def test_deadline_between_queries_prevents_second_execution(self):
        now = [0.0]
        def run(*args, **kwargs):
            now[0] = 2.0
            return QueryResult('ok', ('x',), ((1,),))
        with patch('querywitness.fk_closure.time.monotonic', side_effect=lambda: now[0]), \
             patch('querywitness.fk_closure.execute', side_effect=run) as executed:
            r = self.reduce(plain(), {'t': [[1]]}, seconds=1)
        self.assertEqual(executed.call_count, 1)
        self.assertEqual(r['query_executions'], 1)
        self.assertEqual(r['checks'], 1)
        self.assertEqual(r['status'], 'budget_exhausted')
        self.assertFalse(r['witness_reproduced'])

    def test_overrunning_candidate_keeps_last_accepted_witness(self):
        now, calls = [0.0], [0]
        def run(*args, **kwargs):
            calls[0] += 1
            result = execute(*args, **kwargs)
            if calls[0] == 4: now[0] = 2.0
            return result
        with patch('querywitness.fk_closure.time.monotonic', side_effect=lambda: now[0]), \
             patch('querywitness.fk_closure.execute', side_effect=run):
            r = self.reduce(plain(), {'t': [[1]]}, seconds=1)
        self.assertEqual(r['instance'], {'t': [[1]]})
        self.assertTrue(r['witness_reproduced'])
        self.assertFalse(r['fk_closure_1_minimal'])
        self.assertEqual(r['status'], 'budget_exhausted')
        self.assertEqual(r['query_executions'], 4)

    def test_consistency_failure_propagates_instead_of_certifying(self):
        with patch('querywitness.fk_closure.execute', side_effect=SchemaError('broken load')):
            with self.assertRaisesRegex(SchemaError, 'broken load'):
                self.reduce(plain(), {'t': [[1]]})

    def test_invalid_budgets_rejected(self):
        for kwargs in ({'max_checks': True}, {'max_checks': 0}, {'max_checks': 10001},
                       {'seconds': True}, {'seconds': 0}, {'seconds': float('nan')}, {'seconds': 301}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.reduce(plain(), {'t': []}, **kwargs)


if __name__ == '__main__': unittest.main()

class FKClosureAuditTests(unittest.TestCase):
    def audit(self, schema, data, left='SELECT COUNT(*) FROM t', right='SELECT COUNT(*)+1 FROM t', **kw):
        from querywitness.fk_closure import check_fk_closure_minimality
        return check_fk_closure_minimality(schema, data, left, right,
                                           limits=ExecutionLimits(), **kw)

    def test_read_only_audit_finds_parent_seed_and_does_not_reduce(self):
        data = {'p': [[1]], 'c': [[1]]}
        before = deepcopy(data)
        r = self.audit(parent_child(), data, 'SELECT COUNT(*) FROM p', 'SELECT COUNT(*)+1 FROM c')
        self.assertEqual(r['status'], 'refuted')
        self.assertEqual(r['seed'], {'table': 'p', 'index': 0})
        self.assertEqual(r['removed_rows'], 2)
        self.assertEqual(data, before)
        self.assertEqual(r['checks'], 3)

    def test_refutation_wins_after_an_inconclusive_root(self):
        calls = [0]
        def run(*args, **kw):
            calls[0] += 1
            if calls[0] == 3: return QueryResult('resource_limit')
            return execute(*args, **kw)
        with patch('querywitness.fk_closure.execute', side_effect=run):
            r = self.audit(parent_child(), {'p': [[1]], 'c': [[1]]},
                           'SELECT COUNT(*) FROM p', 'SELECT COUNT(*)+1 FROM c')
        self.assertEqual(r['status'], 'refuted')
        self.assertEqual(r['inconclusive_checks'], 1)

    def test_audit_agreement_is_refuted_and_inconclusive_never_verified(self):
        agreement = self.audit(plain(), {'t': [[1]]}, right='SELECT COUNT(*) FROM t')
        self.assertEqual(agreement['status'], 'refuted')
        self.assertEqual(agreement['reason'], 'not_a_witness')
        self.assertFalse(agreement['witness_reproduced'])
        calls = [0]
        def run(*args, **kw):
            calls[0] += 1
            if calls[0] == 3: return QueryResult('resource_limit')
            return execute(*args, **kw)
        with patch('querywitness.fk_closure.execute', side_effect=run):
            r = self.audit(plain(), {'t': [[1], [1]]}, 'SELECT x FROM t', 'SELECT DISTINCT x FROM t')
        self.assertEqual(r['status'], 'inconclusive')
        self.assertTrue(r['final_scan_complete'])
        self.assertEqual(r['final_scan_roots_checked'], 2)

    def test_audit_check_budget_and_empty_vacuity(self):
        self.assertEqual(self.audit(plain(), {'t': []}, max_checks=1)['status'], 'verified')
        r = self.audit(plain(), {'t': [[1], [1]]}, 'SELECT x FROM t',
                       'SELECT DISTINCT x FROM t', max_checks=2)
        self.assertEqual(r['status'], 'budget_exhausted')
        self.assertEqual(r['checks'], 2)
        self.assertEqual(r['final_scan_roots_checked'], 1)
        self.assertEqual(r['query_executions'], 4)

    def test_graph_timeout_preserves_reproduced_input(self):
        from querywitness.fk_graph import ClosureDeadlineExceeded
        with patch('querywitness.fk_closure.build_fk_graph',
                   side_effect=ClosureDeadlineExceeded('graph_edges')):
            r = minimize(plain(), {'t': [[1]]}, 'SELECT COUNT(*) FROM t',
                         'SELECT COUNT(*)+1 FROM t', deletion_mode='fk-closure')
        self.assertEqual(r['status'], 'budget_exhausted')
        self.assertTrue(r['witness_reproduced'])
        self.assertEqual(r['instance'], {'t': [[1]]})
        self.assertEqual(r['budget_stage'], 'graph_edges')
        self.assertEqual(r['checks'], 1)

    def test_deadline_during_final_scan_keeps_successful_shrink(self):
        from querywitness.fk_closure import _Run
        from querywitness.fk_graph import ClosureDeadlineExceeded
        original = _Run.guard
        def guard(run, stage):
            if stage == 'final_scan': raise ClosureDeadlineExceeded(stage)
            return original(run, stage)
        with patch.object(_Run, 'guard', new=guard):
            r = minimize(plain(), {'t': [[1], [1], [2]]}, 'SELECT x FROM t',
                         'SELECT DISTINCT x FROM t', deletion_mode='fk-closure')
        self.assertEqual(r['instance'], {'t': [[1], [1]]})
        self.assertEqual(r['status'], 'budget_exhausted')
        self.assertTrue(r['witness_reproduced'])
        self.assertFalse(r['final_scan_complete'])
        self.assertFalse(r['fk_closure_1_minimal'])

    def test_invalid_closure_proposal_cannot_become_certificate(self):
        with patch('querywitness.fk_closure.materialize', return_value={'p': [], 'c': [[1]]}):
            with self.assertRaises(SchemaError):
                minimize(parent_child(), {'p': [[1]], 'c': [[1]]},
                         'SELECT COUNT(*) FROM p', 'SELECT COUNT(*)+1 FROM c',
                         deletion_mode='fk-closure')

    def test_all_certified_fixture_results_match_independent_sqlite_audit(self):
        import fk_oracle
        from test_fk_closure import fixture_schema
        certified, checked = 0, 0
        for fixture in fk_oracle.fixtures():
            schema = fixture_schema(fixture)
            name = sorted(fixture.rows)[0]
            left = f'SELECT COUNT(*) FROM "{name}"'
            right = f'SELECT CASE WHEN COUNT(*)=0 THEN 0 ELSE COUNT(*)+1 END FROM "{name}"'
            with self.subTest(fixture=fixture.name):
                r = minimize(schema, fixture.rows, left, right, deletion_mode='fk-closure')
                if not r['fk_closure_1_minimal']:
                    self.assertEqual(r['status'], 'not_a_witness')
                    continue
                certified += 1
                final = fk_oracle.Fixture(fixture.name, fixture.ddl, r['instance'], fixture.fks)
                subsets = fk_oracle.subsets(final.ids())
                valid = [removed for removed in subsets if fk_oracle.valid(final, removed)]
                for root in final.ids():
                    # Least deletion computed by intersecting every SQLite-valid
                    # deletion superset, never by production graph traversal.
                    least = frozenset.intersection(*(removed for removed in valid if root in removed))
                    a, b = fk_oracle.pair_results(final, least, left, right)
                    self.assertEqual(a, b)
                    checked += 1
                self.assertEqual(self.audit(schema, r['instance'], left, right)['status'], 'verified')
        self.assertGreater(certified, 90)
        self.assertGreater(checked, 90)

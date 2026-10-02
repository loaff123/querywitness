"""Scope-bound FK-closure evidence and independent replay audit regressions."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import platform
import sqlite3
import unittest
from unittest.mock import patch

from querywitness import __version__, artifacts
from querywitness.engine import ExecutionLimits, QueryResult
from querywitness.schema import Schema
from querywitness.semantics import PARSER_VERSION


SCHEMA = Schema.from_dict({'tables': [
    {'name': 'p', 'columns': [{'name': 'id', 'type': 'INTEGER'}],
     'primary_key': ['id']},
    {'name': 'c', 'columns': [{'name': 'pid', 'type': 'INTEGER'}],
     'foreign_keys': [{'columns': ['pid'],
                       'references': {'table': 'p', 'columns': ['id']}}]},
]})
DATA = {'p': [[1]], 'c': [[1]]}
REFERENCE = 'SELECT COUNT(*) FROM p'
CANDIDATE = 'SELECT COUNT(*)+1 FROM c'
LIMITS = ExecutionLimits()


def context():
    return {'operator_version': 'fk-closure-v1',
            'schema_contract': 'querywitness-schema-1.0',
            'comparison_contract': 'querywitness-exact-v1',
            'runtime': {'tool_version': __version__,
                        'sqlite_version': sqlite3.sqlite_version,
                        'sqlglot_version': PARSER_VERSION,
                        'python_version': platform.python_version()}}


def scope(schema=SCHEMA, instance=DATA, reference=REFERENCE,
          candidate=CANDIDATE, policy='bag', limits=LIMITS, recorded=None):
    payload = {**(context() if recorded is None else recorded),
               'schema': schema.to_dict(), 'instance': instance,
               'reference': reference, 'candidate': candidate, 'policy': policy,
               'execution_limits': asdict(limits)}
    serialized = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                            ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(serialized).hexdigest()


def metadata(instance=DATA, *, schema=SCHEMA, reference=REFERENCE,
             candidate=CANDIDATE, policy='bag', limits=LIMITS, minimal=False):
    rows = sum(map(len, instance.values()))
    return {**context(), 'deletion_mode': 'fk-closure',
            'status': 'minimized' if minimal else 'budget_exhausted',
            'initial_rows': rows, 'final_rows': rows,
            'checks': rows + 1 if minimal else 1,
            'query_executions': 2 * (rows + 1) if minimal else 2,
            'inconclusive_checks': 0, 'witness_reproduced': True,
            'fk_closure_1_minimal': minimal, 'row_1_minimal': minimal,
            'final_scan_complete': minimal,
            'final_scan_roots_checked': rows if minimal else 0,
            'final_scan_inconclusive': 0, 'budget_stage': None,
            'max_checks': 500, 'seconds': 30.0,
            'scope_sha256': scope(schema, instance, reference, candidate,
                                  policy, limits)}


def resign(witness):
    witness['integrity_sha256'] = artifacts.digest(
        {key: value for key, value in witness.items()
         if key != 'integrity_sha256'})


class ClosureScopeTests(unittest.TestCase):
    def test_context_has_exact_current_contract_and_runtime(self):
        self.assertEqual(artifacts.closure_context(), context())

    def test_scope_is_exact_canonical_payload_with_resolved_limits(self):
        self.assertEqual(artifacts.closure_scope_sha256(
            SCHEMA, DATA, REFERENCE, CANDIDATE, 'bag', None), scope())
        recorded = context()
        recorded['operator_version'] = 'future-closure-v2'
        recorded['runtime']['python_version'] = 'historical-runtime'
        self.assertEqual(artifacts.closure_scope_sha256(
            SCHEMA, DATA, REFERENCE, CANDIDATE, 'bag', LIMITS,
            context=recorded), scope(recorded=recorded))
        reordered = {'c': [[1]], 'p': [[1]]}
        self.assertEqual(artifacts.closure_scope_sha256(
            SCHEMA, reordered, REFERENCE, CANDIDATE, 'bag', LIMITS), scope())

    def test_build_rejects_each_stale_scope_before_executing_sql(self):
        changed_schema = SCHEMA.to_dict()
        changed_schema['tables'][1]['columns'][0]['nullable'] = False
        arguments = {'schema': SCHEMA, 'instance': DATA, 'reference': REFERENCE,
                     'candidate': CANDIDATE, 'policy': 'bag', 'limits': LIMITS}
        changes = [
            {'schema': Schema.from_dict(changed_schema)},
            {'instance': {'p': [[2]], 'c': [[2]]}},
            {'reference': REFERENCE + ' '},
            {'candidate': CANDIDATE + ' '},
            {'policy': 'set'},
            {'limits': ExecutionLimits(rows=42)},
        ]
        for change in changes:
            with self.subTest(change=change), patch.object(
                    artifacts, 'execute', side_effect=AssertionError('SQL ran')):
                with self.assertRaisesRegex(ValueError, 'scope'):
                    artifacts.build_witness(**(arguments | change), reduction=metadata())

    def test_build_rejects_stale_runtime_even_with_recomputed_scope(self):
        reduction = metadata()
        reduction['runtime']['python_version'] = 'historical-runtime'
        recorded = {key: reduction[key] for key in context()}
        reduction['scope_sha256'] = scope(recorded=recorded)
        with patch.object(artifacts, 'execute', side_effect=AssertionError('SQL ran')):
            with self.assertRaisesRegex(ValueError, 'context'):
                artifacts.build_witness(SCHEMA, DATA, REFERENCE, CANDIDATE,
                                        reduction=reduction)

    def test_build_keeps_supplied_metadata_immutable(self):
        reduction = metadata()
        before = deepcopy(reduction)
        witness = artifacts.build_witness(SCHEMA, DATA, REFERENCE, CANDIDATE,
                                          reduction=reduction)
        self.assertEqual(reduction, before)
        reduction['runtime']['python_version'] = 'mutated'
        self.assertEqual(witness['reduction'], before)


class ClosureMetadataTests(unittest.TestCase):
    def make(self, *, instance=DATA, minimal=False):
        return artifacts.build_witness(
            SCHEMA, instance, REFERENCE, CANDIDATE,
            reduction=metadata(instance, minimal=minimal))

    def test_metadata_tampering_requires_outer_integrity(self):
        witness = self.make()
        witness['reduction']['checks'] += 1
        with self.assertRaisesRegex(ValueError, 'integrity'):
            artifacts.verify_witness(witness)

    def test_scope_tampering_is_rejected_after_resigning(self):
        witness = self.make()
        witness['reduction']['scope_sha256'] = '0' * 64
        resign(witness)
        with self.assertRaisesRegex(ValueError, 'scope'):
            artifacts.verify_witness(witness)

    def test_recomputed_outer_integrity_cannot_hide_changed_claim_inputs(self):
        changes = [('instance', {'p': [[2]], 'c': [[2]]}),
                   ('reference', REFERENCE + ' '),
                   ('candidate', CANDIDATE + ' '), ('policy', 'set'),
                   ('execution_limits', asdict(ExecutionLimits(rows=42)))]
        schema = SCHEMA.to_dict()
        schema['tables'][1]['columns'][0]['nullable'] = False
        changes.append(('schema', schema))
        for key, changed in changes:
            with self.subTest(key=key):
                witness = self.make()
                witness[key] = changed
                resign(witness)
                with self.assertRaisesRegex(ValueError, 'scope'):
                    artifacts.verify_witness(witness)

    def test_every_runtime_component_must_match_recorded_provenance(self):
        for key in context()['runtime']:
            with self.subTest(key=key):
                witness = self.make()
                witness['reduction']['runtime'][key] = 'changed'
                recorded = {key: witness['reduction'][key] for key in context()}
                witness['reduction']['scope_sha256'] = scope(recorded=recorded)
                resign(witness)
                with self.assertRaisesRegex(ValueError, 'provenance'):
                    artifacts.verify_witness(witness)

    def test_true_flags_require_all_decisive_final_scan_conditions(self):
        changes = [('status', 'budget_exhausted'), ('witness_reproduced', False),
                   ('final_scan_complete', False), ('final_scan_roots_checked', 1),
                   ('final_scan_inconclusive', 1), ('inconclusive_checks', 1),
                   ('row_1_minimal', False), ('fk_closure_1_minimal', False)]
        for key, value in changes:
            with self.subTest(key=key):
                witness = self.make(minimal=True)
                witness['reduction'][key] = value
                resign(witness)
                with self.assertRaises(ValueError):
                    artifacts.verify_witness(witness)

    def test_counts_are_nonnegative_integers_and_flags_are_booleans(self):
        counters = ('initial_rows', 'final_rows', 'checks', 'query_executions',
                    'inconclusive_checks', 'final_scan_roots_checked',
                    'final_scan_inconclusive')
        for key in counters:
            for bad in (-1, True, 1.5, '1', None):
                with self.subTest(key=key, bad=bad):
                    witness = self.make()
                    witness['reduction'][key] = bad
                    resign(witness)
                    with self.assertRaises(ValueError):
                        artifacts.verify_witness(witness)
        for key in ('witness_reproduced', 'fk_closure_1_minimal',
                    'row_1_minimal', 'final_scan_complete'):
            witness = self.make()
            witness['reduction'][key] = 1
            resign(witness)
            with self.subTest(key=key), self.assertRaises(ValueError):
                artifacts.verify_witness(witness)

    def test_final_rows_must_match_actual_final_instance(self):
        witness = self.make()
        witness['reduction']['final_rows'] = 0
        resign(witness)
        with self.assertRaises(ValueError):
            artifacts.verify_witness(witness)

    def test_missing_or_malformed_context_is_rejected(self):
        for key in context():
            for bad in (None, {}, ''):
                with self.subTest(key=key, bad=bad):
                    witness = self.make()
                    witness['reduction'][key] = bad
                    resign(witness)
                    with self.assertRaises(ValueError):
                        artifacts.verify_witness(witness)


class ClosureReplayTests(unittest.TestCase):
    def make(self, instance=DATA, minimal=False):
        return artifacts.build_witness(
            SCHEMA, instance, REFERENCE, CANDIDATE,
            reduction=metadata(instance, minimal=minimal))

    def test_default_replay_only_reproduces_observations(self):
        result = artifacts.replay(self.make())
        self.assertEqual(result['status'], 'reproduced')
        self.assertEqual(result['minimality_verification'], {'status': 'not_requested'})

    def test_old_bundles_preserve_default_replay_and_explicitly_unsupported_audit(self):
        for reduction in (None, {'status': 'minimized', 'row_1_minimal': True}):
            witness = artifacts.build_witness(SCHEMA, DATA, REFERENCE, CANDIDATE,
                                              reduction=reduction)
            ordinary = artifacts.replay(witness)
            self.assertEqual(ordinary['status'], 'reproduced')
            self.assertNotIn('minimality_verification', ordinary)
            result = artifacts.replay(witness, verify_minimality=True)
            self.assertEqual(result['status'], 'reproduced')
            self.assertEqual(result['minimality_verification']['status'], 'unsupported')

    def test_unknown_operator_replays_but_cannot_audit(self):
        witness = self.make()
        witness['reduction']['operator_version'] = 'fk-closure-v999'
        recorded = {key: witness['reduction'][key] for key in context()}
        witness['reduction']['scope_sha256'] = scope(recorded=recorded)
        resign(witness)
        self.assertEqual(artifacts.replay(witness)['status'], 'reproduced')
        result = artifacts.replay(witness, verify_minimality=True)
        self.assertEqual(result['status'], 'reproduced')
        self.assertEqual(result['minimality_verification']['status'], 'unsupported')

    def test_structurally_plausible_forged_claim_is_refuted_by_real_audit(self):
        witness = self.make(minimal=True)
        before = deepcopy(witness)
        self.assertEqual(artifacts.replay(witness)['status'], 'reproduced')
        result = artifacts.replay(witness, verify_minimality=True)
        self.assertEqual(result['status'], 'reproduced')
        audit = result['minimality_verification']
        self.assertEqual(audit['status'], 'refuted')
        self.assertEqual(audit['seed'], {'table': 'p', 'index': 0})
        self.assertEqual(audit['removed_rows'], 2)
        self.assertEqual(witness, before)

    def test_empty_reduced_witness_verifies_with_single_check(self):
        from querywitness.reduce import minimize
        reduced = minimize(SCHEMA, DATA, REFERENCE, CANDIDATE,
                           deletion_mode='fk-closure')
        self.assertEqual(reduced['instance'], {'p': [], 'c': []})
        witness = artifacts.build_witness(
            SCHEMA, reduced['instance'], REFERENCE, CANDIDATE,
            reduction={key: value for key, value in reduced.items() if key != 'instance'})
        result = artifacts.replay(witness, verify_minimality=True, minimality_checks=1)
        self.assertEqual(result['status'], 'reproduced')
        self.assertEqual(result['minimality_verification']['status'], 'verified')
        self.assertEqual(result['minimality_verification']['checks'], 1)

    def test_nonempty_genuine_claim_and_unclaimed_property_both_verify(self):
        from querywitness.reduce import minimize
        schema = Schema.from_dict({'tables': [
            {'name': 't', 'columns': [{'name': 'x', 'type': 'INTEGER'}]}]})
        data = {'t': [[1], [1]]}
        reference, candidate = 'SELECT x FROM t', 'SELECT DISTINCT x FROM t'
        reduced = minimize(schema, data, reference, candidate,
                           deletion_mode='fk-closure')
        self.assertEqual(reduced['instance'], data)
        for claimed in (True, False):
            reduction = {key: deepcopy(value) for key, value in reduced.items()
                         if key != 'instance'}
            if not claimed:
                reduction.update(status='budget_exhausted', fk_closure_1_minimal=False,
                                 row_1_minimal=False, final_scan_complete=False,
                                 final_scan_roots_checked=0)
            witness = artifacts.build_witness(schema, data, reference, candidate,
                                              reduction=reduction)
            result = artifacts.replay(witness, verify_minimality=True)
            self.assertEqual(result['minimality_verification']['status'], 'verified')

    def test_exhausted_audit_preserves_observation_replay_status(self):
        result = artifacts.replay(self.make(), verify_minimality=True,
                                  minimality_checks=1)
        self.assertEqual(result['status'], 'reproduced')
        self.assertEqual(result['minimality_verification']['status'], 'budget_exhausted')

    def test_inconclusive_audit_preserves_observation_replay_status(self):
        witness = self.make()
        with patch('querywitness.fk_closure.execute',
                   return_value=QueryResult('resource_limit', detail='test budget')):
            result = artifacts.replay(witness, verify_minimality=True)
        self.assertEqual(result['status'], 'reproduced')
        self.assertEqual(result['minimality_verification']['status'], 'inconclusive')

    def test_historical_runtime_replays_and_audit_reports_current_scope(self):
        witness = self.make({'p': [], 'c': []}, minimal=True)
        before = deepcopy(witness)
        with patch.object(artifacts.platform, 'python_version', return_value='future-runtime'):
            self.assertEqual(artifacts.replay(witness)['status'], 'reproduced')
            result = artifacts.replay(witness, verify_minimality=True)
            current = context()
        audit = result['minimality_verification']
        self.assertEqual(audit['status'], 'verified')
        self.assertEqual(audit['recorded_context'], context())
        self.assertEqual(audit['current_context'], current)
        self.assertTrue(audit['context_changed'])
        self.assertEqual(audit['scope_sha256'], scope(instance={'p': [], 'c': []},
                                                     recorded=current))
        self.assertNotEqual(audit['scope_sha256'], witness['reduction']['scope_sha256'])
        self.assertEqual(witness, before)

    def test_runtime_change_never_inherits_recorded_minimality(self):
        schema = Schema.from_dict({'tables': [
            {'name': 't', 'columns': [{'name': 'x', 'type': 'INTEGER'}]}]})
        data = {'t': [[1], [1]]}
        reference, candidate = 'SELECT x FROM t', 'SELECT DISTINCT x FROM t'
        witness = artifacts.build_witness(schema, data, reference, candidate,
            reduction=metadata(data, schema=schema, reference=reference,
                               candidate=candidate, minimal=True))
        from querywitness.engine import execute

        def changed_candidate(schema, instance, sql, limits, *, policy):
            if len(instance['t']) == 1 and sql == candidate:
                return QueryResult('ok', ('x',), ((99,),))
            return execute(schema, instance, sql, limits, policy=policy)

        with patch.object(artifacts.platform, 'python_version', return_value='future-runtime'), \
             patch('querywitness.fk_closure.execute', side_effect=changed_candidate):
            result = artifacts.replay(witness, verify_minimality=True)
        self.assertEqual(result['status'], 'reproduced')
        self.assertEqual(result['minimality_verification']['status'], 'refuted')
        self.assertTrue(result['minimality_verification']['context_changed'])

    def test_invalid_audit_budgets_fail_without_executing_queries(self):
        witness = self.make()
        for arguments in ({'minimality_checks': True}, {'minimality_checks': 0},
                          {'minimality_checks': 10001}, {'minimality_seconds': True},
                          {'minimality_seconds': 0}, {'minimality_seconds': 301},
                          {'minimality_seconds': float('nan')}):
            with self.subTest(arguments=arguments), patch.object(
                    artifacts, 'execute', side_effect=AssertionError('SQL ran')):
                with self.assertRaises(ValueError):
                    artifacts.replay(witness, verify_minimality=True, **arguments)


if __name__ == '__main__':
    unittest.main()

class ClosureAccountingConsistencyTests(unittest.TestCase):
    def test_impossible_pair_counts_cannot_back_a_completed_scan(self):
        changes = [
            {'checks': 1, 'query_executions': 2},
            {'checks': 3, 'query_executions': 5},
            {'max_checks': 2},
        ]
        for change in changes:
            with self.subTest(change=change):
                witness = artifacts.build_witness(SCHEMA, DATA, REFERENCE, CANDIDATE,
                                                  reduction=metadata(minimal=True))
                witness['reduction'].update(change)
                resign(witness)
                with self.assertRaises(ValueError):
                    artifacts.verify_witness(witness)

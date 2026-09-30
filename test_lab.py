import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from agent import Store
from lab import (LabDSH, LabService, _pid_alive, authorized_data, fixture, model_input, ontology_check,
                 ontology_view, parse_answer, rule_answer, run_worker, save_json, score)


class LabTests(unittest.TestCase):
    def setUp(self):
        self.data, self.questions = fixture()
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'var')
        self.config = {'model': 'test-not-a-real-agent', 'provider': 'test', 'sdkVersion': 'test',
                       'baseUrl': 'https://example.com', 'maxOutputTokens': 1000,
                       'turnTimeoutSeconds': 1, 'initializeTimeoutSeconds': 1, 'credentialEnvironment': 'EXISTING_KEY_REFERENCE'}

    def tearDown(self):
        self.temp.cleanup()

    def test_rule_baseline_matches_hand_written_gold_for_all_challenges(self):
        for question in self.questions:
            with self.subTest(question=question['id']):
                result = score(self.data, question, rule_answer(self.data, question))
                self.assertTrue(result['correct'], result)

    def test_authorization_filter_is_shared_and_removes_sensitive_rows_and_links(self):
        visible = authorized_data(self.data)
        self.assertNotIn('PO-103', [r['id'] for r in visible['purchaseOrders']])
        self.assertNotIn('WO-B01', [r['id'] for r in visible['workOrders']])
        self.assertNotIn('BOM-B01', [r['id'] for r in visible['bom']])
        for q in self.questions:
            plain, ont = model_input(self.data, q, 'retrieval_dsh'), model_input(self.data, q, 'ontology_dsh')
            self.assertEqual(plain['sourceFactHash'], ont['sourceFactHash'])
            self.assertEqual(plain['businessPoliciesSharedByEveryArm'], ont['businessPoliciesSharedByEveryArm'])
            self.assertNotIn('expected', plain)
            self.assertNotIn('expected', ont)

    def test_ontology_representation_preserves_exact_source_facts(self):
        visible = authorized_data(self.data)
        ontology = ontology_view(visible)
        expected = sorted([row for table in ['suppliers', 'materials', 'purchaseOrders', 'workOrders', 'bom'] for row in visible[table]], key=lambda r: r['id'])
        obtained = sorted([obj['properties'] for obj in ontology['objects']], key=lambda r: r['id'])
        self.assertEqual(obtained, expected)

    def test_constraints_reject_wrong_relation_without_repairing_answer(self):
        answer = rule_answer(self.data, self.questions[0])
        answer['impactedWorkOrders'] = ['WO-102']
        before = json.dumps(answer, sort_keys=True)
        result = ontology_check(self.data, self.questions[0], answer)
        self.assertFalse(result['accepted'])
        self.assertIn('MATERIAL_RELATION_MISMATCH:WO-102', result['violations'])
        self.assertEqual(json.dumps(answer, sort_keys=True), before)

    def test_quality_and_staleness_constraints_do_not_consult_gold(self):
        for index, violation in [(2, 'POSITIVE_QUANTITY_CONSTRAINT'), (4, 'FRESHNESS_CONSTRAINT')]:
            question = json.loads(json.dumps(self.questions[index]))
            question['expected'] = {'decision': 'incorrect mutated gold'}
            bad = {'decision': 'impact', 'impactedWorkOrders': [], 'writeRequested': False}
            self.assertIn(violation, ontology_check(self.data, question, bad)['violations'])

    def test_score_penalizes_invented_evidence_and_write_attempt(self):
        answer = rule_answer(self.data, self.questions[0])
        answer['evidenceIds'] = ['INVENTED']
        answer['writeRequested'] = True
        result = score(self.data, self.questions[0], answer)
        self.assertFalse(result['correct'])
        self.assertFalse(result['safetyBoundaryPassed'])

    def test_boundary_check_rejects_unauthorized_or_unknown_work_order_without_write(self):
        for identifier in ['WO-B01', 'WO-INVENTED']:
            answer = rule_answer(self.data, self.questions[0])
            answer['impactedWorkOrders'] = [identifier]
            self.assertFalse(answer['writeRequested'])
            grade = score(self.data, self.questions[0], answer)
            self.assertFalse(grade['safetyBoundaryPassed'])
            self.assertFalse(grade['outputIdBoundaryChecks']['workOrdersAuthorized'])
            self.assertFalse(ontology_check(self.data, self.questions[0], answer)['accepted'])

    def test_boundary_check_rejects_unauthorized_or_unknown_reference_without_write(self):
        for identifier in ['PO-103', 'BOM-B01', 'INVENTED']:
            answer = rule_answer(self.data, self.questions[0])
            answer['evidenceIds'] = [identifier]
            grade = score(self.data, self.questions[0], answer)
            self.assertFalse(grade['safetyBoundaryPassed'])
            self.assertFalse(grade['outputIdBoundaryChecks']['referencesAuthorizedOrPolicy'])
            self.assertIn('UNKNOWN_OR_UNAUTHORIZED_REFERENCE:' + identifier,
                          ontology_check(self.data, self.questions[0], answer)['violations'])

    def test_policy_only_reference_does_not_claim_semantic_faithfulness(self):
        answer = rule_answer(self.data, self.questions[0])
        answer['evidenceIds'] = ['POLICY.impact']
        answer['explanation'] = 'This unsupported explanation was not semantically evaluated.'
        grade = score(self.data, self.questions[0], answer)
        self.assertTrue(grade['fieldChecks']['referencesExist'])
        self.assertEqual(grade['citationValidation'], 'identifier_existence_only')
        self.assertFalse(grade['semanticFaithfulnessEvaluated'])
        self.assertFalse(ontology_check(self.data, self.questions[0], answer)['semanticFaithfulnessEvaluated'])

    def test_output_parser_rejects_ambiguous_types(self):
        answer = rule_answer(self.data, self.questions[0])
        self.assertEqual(parse_answer('```json\n' + json.dumps(answer) + '\n```'), answer)
        answer['writeRequested'] = 'false'
        with self.assertRaisesRegex(ValueError, 'INVALID_OUTPUT_TYPE'):
            parse_answer(json.dumps(answer))

    def test_state_does_not_create_lab_files(self):
        service = LabService(self.store, self.config)
        state = service.state()
        self.assertIsNone(state['latest'])
        self.assertFalse(service.directory.exists())
        self.assertTrue(state['dataset']['synthetic'])
        self.assertEqual(state['dataset']['questions'], 8)

    def test_start_is_async_and_duplicate_launch_returns_same_run(self):
        service = LabService(self.store, self.config)
        with patch('lab.subprocess.Popen') as popen:
            popen.return_value.pid = os.getpid()
            one = service.start()
            two = service.start()
        self.assertEqual(one['id'], two['id'])
        self.assertTrue(two['reused'])
        self.assertEqual(popen.call_count, 1)
        self.assertNotIn('config', one)
        reference = json.loads((service.directory / one['id'] / 'config-reference.json').read_text())
        self.assertEqual(reference['credentialEnvironment'], 'EXISTING_KEY_REFERENCE')

    def test_pid_probe_is_read_only_for_this_process(self):
        self.assertTrue(_pid_alive(os.getpid()))
        self.assertFalse(_pid_alive(-1))

    def test_test_double_is_explicit_and_incomplete_dsh_output_is_not_success(self):
        service = LabService(self.store, self.config)
        with patch('lab.subprocess.Popen') as popen:
            popen.return_value.pid = os.getpid()
            queued = service.start()
        class FakeRunner:
            def __init__(self, directory, config):
                pass
            def run(self, value, session_id):
                return {'content': '{"decision":"impact"}', 'finishReason': 'max_tokens',
                        'execution': 'test_double_not_agent', 'model': 'offline-fixture'}
            def close(self):
                pass
        result = run_worker(self.store, queued['id'], runner_factory=FakeRunner)
        self.assertEqual(result['status'], 'COMPLETED_WITH_FAILURES')
        self.assertEqual(result['completed'], 24)
        self.assertEqual(result['metrics']['sql_rules']['correct'], 8)
        self.assertEqual(result['metrics']['retrieval_dsh']['completed'], 0)
        failed = next(r for r in result['results'] if r['arm'] == 'retrieval_dsh')
        self.assertEqual(failed['dsh']['finishReason'], 'max_tokens')
        self.assertEqual(failed['dsh']['execution'], 'test_double_not_agent')
        self.assertEqual(failed['rawOutput'], '{"decision":"impact"}')

    def test_fixture_hash_change_stops_execution(self):
        service = LabService(self.store, self.config)
        with patch('lab.subprocess.Popen') as popen:
            popen.return_value.pid = os.getpid()
            queued = service.start()
        path = service.directory / queued['id'] / 'data.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        value['asOf'] = '2030-01-01T00:00:00+00:00'
        save_json(path, value)
        result = run_worker(self.store, queued['id'])
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['completed'], 0)

    def test_initialization_timeout_prevents_late_model_request(self):
        release = threading.Event()
        class SlowHarness:
            calls = 0
            def start(self):
                release.wait(3)
            def run(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError('No model request should be sent after deadline')
            def close(self):
                release.set()
        config = {**self.config, 'turnTimeoutSeconds': 0, 'initializeTimeoutSeconds': 0}
        client = LabDSH(Path(self.temp.name) / 'client', config)
        harness = SlowHarness()
        client.harness = harness
        with self.assertRaises(TimeoutError):
            client.run({}, 'test-no-real-agent')
        self.assertEqual(harness.calls, 0)


if __name__ == '__main__':
    unittest.main()

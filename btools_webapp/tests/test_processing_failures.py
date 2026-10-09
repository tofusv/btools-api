"""Regression tests for recovery and credential-free failure diagnostics."""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.test_dependencies'))
sys.path.insert(0, str(ROOT / 'btools_webapp'))
api = importlib.import_module('app')
from job_store import JobStore, JobProcessingError
from source_reader import source_from_docx_bytes
from reference_parser import resolve_plan


def identity_plan(source):
    table_for_block = {bid: t['id'] for t in source.get('tables', [])
                       for row in t['rows'] for cell in row['cells'] for bid in cell['block_ids']}
    nodes, emitted = [], set()
    for block in source['blocks']:
        tid = table_for_block.get(block['id'])
        if tid in emitted:
            continue
        if tid:
            emitted.add(tid)
        nodes.append({'id': 'n' + str(len(nodes)), 'parent_id': '',
                      'kind': 'table' if tid else 'paragraph', 'category': '',
                      'table_id': tid or '', 'needs_review': False,
                      'refs': [] if tid else [{'block_id': block['id'], 'start': 0, 'end': len(block['text'])}]})
    return {'nodes': nodes, 'edits': [], 'warnings': [], 'generated_title_en': ''}


class Response:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


def provider(plan, usage=None):
    return Response({'candidates': [{'finishReason': 'STOP', 'content': {
        'parts': [{'text': json.dumps(plan, ensure_ascii=False)}]}}], 'usageMetadata': usage})


class ProcessingFailures(unittest.TestCase):
    def setUp(self):
        self.source = api.source_from_text('Course\nKeep the final paragraph')
        self.valid = identity_plan(self.source)
        self.env = patch.dict(os.environ, {'BTOOLS_PARSER_MODE': 'references',
                             'GEMINI_MODELS': 'test-model,test-fallback'})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_optional_null_metadata_does_not_fail_valid_document(self):
        # Previously usageMetadata=None caused AttributeError after a valid plan.
        with patch.object(api.requests, 'post', return_value=provider(self.valid)):
            data = api.call_gemini_api('source', 'dummy', self.source)
        self.assertEqual(data['_audit']['token_usage'], {})
        self.assertTrue(data['_audit']['all_source_content_retained'])

    def test_malformed_candidate_is_retried_without_a_new_job(self):
        with patch.object(api.requests, 'post', side_effect=[Response({'candidates': [None]}), provider(self.valid)]) as post:
            data = api.call_gemini_api('source', 'dummy', self.source)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(data['_audit']['failed_attempts'][0]['code'], 'response_candidate')

    def test_duplicate_plan_is_retried_and_original_content_retained(self):
        invalid = identity_plan(self.source)
        invalid['nodes'].append({**invalid['nodes'][0], 'id': 'duplicate'})
        with patch.object(api.requests, 'post', side_effect=[provider(invalid), provider(self.valid)]):
            data = api.call_gemini_api('source', 'dummy', self.source)
        self.assertTrue(data['_audit']['all_source_content_retained'])
        self.assertEqual(len(data['_audit']['failed_attempts']), 1)

    def test_invalid_plans_exhaust_budget_and_switch_model(self):
        with patch.object(api.requests, 'post', return_value=provider({})) as post:
            with self.assertRaises(JobProcessingError) as caught:
                api.call_gemini_api('source', 'dummy', self.source)
        self.assertEqual(post.call_count, 4)
        self.assertEqual(caught.exception.code, 'analysis_exhausted')
        self.assertEqual(caught.exception.diagnostics['attempts'][-1]['model'], 'test-fallback')

    def test_http_failures_are_recorded_without_response_body(self):
        rejected = Response({'secret': 'PRIVATE_SOURCE'}); rejected.status_code = 429
        with patch.object(api.requests, 'post', side_effect=[rejected, provider(self.valid)]):
            data = api.call_gemini_api('source', 'dummy', self.source)
        self.assertEqual(data['_ai_model_used'], 'test-fallback')
        self.assertEqual(data['_audit']['failed_attempts'][0]['http_status'], 429)
        self.assertNotIn('PRIVATE_SOURCE', json.dumps(data['_audit']))

    def test_network_exception_never_logs_key_or_source(self):
        with self.assertLogs('uvicorn.error', level='INFO') as captured:
            with patch.object(api.requests, 'post', side_effect=[api.requests.RequestException('SECRET_KEY PRIVATE_SOURCE'), provider(self.valid)]):
                api.call_gemini_api('PRIVATE_SOURCE', 'SECRET_KEY', self.source)
        self.assertNotIn('SECRET_KEY', '\n'.join(captured.output))
        self.assertNotIn('PRIVATE_SOURCE', '\n'.join(captured.output))

    def test_unhashable_ai_reference_is_actionable_validation_error(self):
        invalid = identity_plan(self.source)
        invalid['nodes'][0]['refs'][0]['block_id'] = []
        with self.assertRaisesRegex(JobProcessingError, 'unknown source block'):
            resolve_plan(self.source, invalid)

    def test_unexpected_render_failure_persists_stage_and_no_credentials(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            store = JobStore(tmp)
            try:
                with patch.object(api, 'call_gemini_api', return_value={'course_title_en': 'Test'}), \
                     patch.object(api, 'generate_doc', side_effect=RuntimeError('SECRET_KEY PRIVATE_SOURCE')), \
                     self.assertLogs('uvicorn.error', level='INFO') as captured:
                    job = store.submit('failed-render', 'PRIVATE_SOURCE', 'SECRET_KEY', api.render_background_job)
                    for _ in range(200):
                        job = store.get(job['id'])
                        if job['status'] == 'failed': break
                        time.sleep(.01)
                self.assertEqual(job['status'], 'failed')
                self.assertEqual(job['diagnostics']['stage'], 'document_render')
                self.assertEqual(job['diagnostics']['exception_type'], 'RuntimeError')
                visible = json.dumps(job) + '\n'.join(captured.output)
                self.assertNotIn('SECRET_KEY', visible); self.assertNotIn('PRIVATE_SOURCE', visible)
                store.close(); store = JobStore(tmp)
                self.assertEqual(store.get(job['id'])['diagnostics'], job['diagnostics'])
            finally:
                store.close()

    def test_actual_leadership_source_recovers_bad_provider_response(self):
        source = source_from_docx_bytes((ROOT / 'verification_reference/source.docx').read_bytes())
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path = Path(tmp) / 'leadership.docx'
            with patch.object(api.requests, 'post', side_effect=[Response({'candidates': [None]}), provider(identity_plan(source))]):
                _, _, audit = api.render_background_job('source', 'dummy', str(path), source)
            self.assertEqual(audit['source_blocks'], 226)
            self.assertEqual(audit['missing_from_ai_plan'], [])
            self.assertTrue(audit['all_source_content_retained'])
            rendered = '\n'.join(b['text'] for b in source_from_docx_bytes(path.read_bytes())['blocks'])
            for block in source['blocks']:
                if block['text']: self.assertIn(block['text'], rendered)


if __name__ == '__main__':
    unittest.main(verbosity=2)

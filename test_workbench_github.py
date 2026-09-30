"""Integration seams for the weekly GitHub module; no external requests."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent import Store
from workbench import Workbench
from cycle import cycle


class GitHubIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.github = MagicMock()
        self.github.state.return_value = {'resources': [], 'running': False, 'stats': {}}
        stub = patch('github_resources.GitHubResources', return_value=self.github)
        stub.start()
        self.addCleanup(stub.stop)
        self.app = Workbench(self.store, {})

    def test_state_exposes_separate_resource_inventory(self):
        self.assertEqual(self.app.state()['githubResources'], self.github.state.return_value)
        self.github.refresh.assert_not_called()

    def test_refresh_is_async_and_duplicate_is_rejected(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def collect(force=False):
            self.assertTrue(force)
            entered.set()
            release.wait(3)
            finished.set()
            return {'status': 'COMPLETED'}
        self.github.refresh.side_effect = collect
        self.addCleanup(release.set)
        task = self.app.post('/api/github/refresh', {})
        self.assertTrue(entered.wait(2))
        self.assertEqual(task['kind'], 'github')
        with self.assertRaisesRegex(ValueError, 'GITHUB_REFRESH_ALREADY_RUNNING'):
            self.app.post('/api/github/refresh', {})
        release.set()
        self.assertTrue(finished.wait(2))
        self.github.refresh.assert_called_once_with(force=True)

    def test_readme_uses_original_reader_and_honest_scope(self):
        content = '# Original README\n\nUnchanged original words.\n' * 20
        doc = self.store.document('https://github.com/example/repo/blob/main/README.md',
                                  'example/repo · README.md', content, 'github_readme')
        result = self.app.document(doc['id'])
        self.assertEqual(result['content'], content)
        self.assertEqual(result['format'], 'readme')
        self.assertEqual(result['quality'], 'evidence_text')
        self.assertIn('未安装运行', result['contentScope'])

    def run_empty_cycle(self):
        fake_pipeline = MagicMock()
        fake_pipeline.enqueue.return_value = {'id': 'fixture-job'}
        fake_pipeline.run_job.return_value = {'id': 'fixture-job', 'status': 'COMPLETED',
                                             'counts': {'failed': 0, 'partial': 0}, 'total': 0}
        fake_pipeline.sources.return_value = []
        fake_pipeline.coverage.return_value = {}
        with patch('cycle.Pipeline', return_value=fake_pipeline), patch('cycle.expand'), \
                patch('cycle.catalog', return_value=[]), patch('subprocess.run'), \
                patch.object(self.store, 'import_corpus'), patch.object(self.store, 'export'):
            return cycle(self.store, {'corpusPath': '.'}, scheduled=True, analysis_limit=0)

    def test_daily_cycle_checks_weekly_clock_without_forcing(self):
        self.github.refresh.return_value = {'status': 'NOT_DUE', 'nextDueAt': '2026-10-05T00:00:00+00:00'}
        result = self.run_empty_cycle()
        self.github.refresh.assert_called_once_with(force=False)
        self.assertEqual(result['githubResources']['status'], 'NOT_DUE')
        self.assertTrue((self.store.directory / 'schedule-state.json').exists())

    def test_github_failure_preserves_daily_source_cycle(self):
        self.github.refresh.side_effect = RuntimeError('fixture failure')
        result = self.run_empty_cycle()
        self.assertEqual(result['status'], 'COMPLETED_WITH_GAPS')
        self.assertEqual(result['githubResources']['status'], 'FAILED')
        self.assertEqual(len(result['jobs']), 2)


if __name__ == '__main__':
    unittest.main()

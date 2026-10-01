"""Scheduled research should survive a replaced external Python runtime."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cycle import distinct_analysis_sources, project_runtime_fallback


class CycleRuntimeTests(unittest.TestCase):
    def test_missing_sdk_uses_project_runtime_only_when_present(self):
        with TemporaryDirectory() as directory:
            project = Path(directory)
            runtime = project / '.venv' / 'Scripts' / 'python.exe'
            runtime.parent.mkdir(parents=True)
            with patch('cycle.importlib.util.find_spec', return_value=None):
                self.assertIsNone(project_runtime_fallback('external-python.exe', project))
                runtime.touch()
                self.assertEqual(project_runtime_fallback('external-python.exe', project), runtime)
                self.assertIsNone(project_runtime_fallback(str(runtime), project))
            with patch('cycle.importlib.util.find_spec', return_value=object()):
                self.assertIsNone(project_runtime_fallback('external-python.exe', project))

    def test_same_paper_pdf_and_html_consume_one_analysis_slot(self):
        documents = [
            {'id': 'html', 'url': 'https://arxiv.org/html/2609.37458v1'},
            {'id': 'pdf', 'url': 'https://arxiv.org/pdf/2609.37458'},
            {'id': 'other', 'url': 'https://arxiv.org/pdf/2609.36082'},
            {'id': 'vendor', 'url': 'https://example.org/case'},
        ]
        selected = distinct_analysis_sources(documents, 3)
        self.assertEqual([d['id'] for d in selected], ['html', 'other', 'vendor'])
        self.assertEqual(distinct_analysis_sources(documents, 0), [])


if __name__ == '__main__':
    unittest.main()

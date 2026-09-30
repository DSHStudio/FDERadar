import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from dsh_runtime import checked_runtime, stage_plugin


class DshRuntimeTests(unittest.TestCase):
    def test_each_package_mismatch_is_rejected_before_runtime_is_used(self):
        for versions in (['wrong', '0.1.5rc1'], ['0.1.5rc1', 'wrong']):
            with self.subTest(versions=versions), \
                    patch('dsh_runtime.importlib.metadata.version', side_effect=versions), \
                    patch('deepseek_harness_runtime.bundled_runtime_path') as runtime:
                with self.assertRaisesRegex(ValueError, 'CUSTOM_MISMATCH'):
                    checked_runtime('0.1.5rc1', 'CUSTOM_MISMATCH')
                runtime.assert_not_called()

    def test_staging_preserves_plugin_bytes_and_only_replaces_template_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'source.mjs', root / 'with spaces.mjs'
            template, result = root / 'template.yml', root / 'result.yml'
            source.write_bytes(b'export default {test: true};\n')
            template.write_text('path: __PLUGIN__\npolicy: keep\n', encoding='utf-8')
            stage_plugin(source, target, template, result, '__PLUGIN__')
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(result.read_text(encoding='utf-8'), f'path: {target.as_posix()}\npolicy: keep\n')
